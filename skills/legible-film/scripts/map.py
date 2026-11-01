#!/usr/bin/env python3
"""Register and map local source media.

  python map.py add PROJECT FILE... --role interview [--copy] [--stream INDEX]
  python map.py run PROJECT [--alias int_01] [--words auto|skip|import:FILE] [--prompt TEXT]
      [--ggml-model PATH] [--retranscribe ALIAS] [--download]
  python map.py relink PROJECT ALIAS PATH
  python map.py fix PROJECT WORD_ID [TEXT] [--start S] [--end E] [--by person|agent]
  python map.py confirm-words PROJECT ALIAS --note TEXT [--stream INDEX] [--by person|agent]
  python map.py words PROJECT ALIAS [--from TIME] [--to TIME]
  python map.py run PROJECT [--alias ALIAS] --check
  python map.py run PROJECT [--alias ALIAS] --rebuild

The chosen audio stream and displayed square-pixel geometry are recorded. Mapping writes a readable transcript.md
and review prompts beside words.json. Speech-band energy is a fallible prompt, not a speech detector; no words are
deleted. Fix preserves the ID, validates timing and records the change in decisions.jsonl. It prints the word's ID,
time and text before and after with a few words either side, and each film.md spoken line over the word that stops
(or starts) matching the transcript the way cut.py check matches it; an ID that does not exist is refused with the
nearest one; a refused timing names the neighbouring words with their times and the window that would pass.
Words prints each word's ID and source-second edges and, between words, the pause a cut can use: how long nothing is
spoken (the map's voice-activity segments) and how far the gap's quarter-second level falls below the words either
side. FFmpeg's fixed -40 dB silence threshold is shown only where it found quiet, and the header says when a source's
room tone sits above it. Maps made before voice activity was recorded, or without faster-whisper, show levels only.
Maps are drafts and detected cuts and silences need inspection. Shot-change candidates within 1 s of each other
that return to the same picture (a flash or effect inside one shot) are recorded in shots.json as effects, not shot
changes; maps made before this keep their shots until --rebuild. Exit 0 on success, 1 for an incomplete --check or
when a transcript is stale (its warning names both remedies), 2 on error.
Uncached transcription weights download only with --download or with setup.py --install transcription and consent.
Transcripts retain their original media and sound-stream binding when a source changes; stale transcripts warn on
every run, words, fix and the readable transcript. Retranscribe, or explicitly confirm a checked transcript with a
note, to rebind it. Older unbound transcripts are bound to the previously registered media on run. A binding does
not prove word accuracy.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
try:
    import numpy as np
except ImportError as error:
    print(project.dependency_message('numpy'), file=sys.stderr)
    sys.exit(2)
transcribe_spec = importlib.util.spec_from_file_location('lf_transcribe', Path(__file__).with_name('transcribe.py'))
transcribe = importlib.util.module_from_spec(transcribe_spec)
transcribe_spec.loader.exec_module(transcribe)
render_spec = importlib.util.spec_from_file_location('lf_render_common', Path(__file__).with_name('render_common.py'))
render_common = importlib.util.module_from_spec(render_spec)
try:
    render_spec.loader.exec_module(render_common)
except ImportError as error:
    if error.name and (error.name == 'PIL' or error.name.startswith('PIL.')):
        print(project.dependency_message('PIL'), file=sys.stderr)
        sys.exit(2)
    raise
SCRIPTS = Path(__file__).resolve().parent
# Bump when the shot, sheet or audio-map outputs intentionally change.
MAP_FORMAT_VERSION = 1
# FFmpeg silencedetect threshold for audio.json silences: every sample must stay below it, so steady room tone near
# it (Tears of Steel's pauses sit at about -39.5 dB) hides every pause from it.
SILENCE_DB = -40
# The voice-activity settings (300 ms minimum silence, 100 ms padding each side) join pauses shorter than this.
VAD_JOIN_S = 0.5
# A pause counts as clear, for judging the fixed threshold, when its quietest quarter-second falls this far below the
# source's typical speech level and it lasts this long.
CLEAR_DROP_DB = 12.0
CLEAR_PAUSE_S = 0.4
# Shot-change candidates this close together are an effect inside one shot (a flash, a glitch, a quick push) when the
# picture after the last matches the picture before the first: their 32x18 grey thumbnails differ by at most
# SAME_SHOT_LEVELS grey levels on average (a cut to another shot differs far more).
EFFECT_S = 1.0
SAME_SHOT_LEVELS = 12.0


def digest(path):
    """Hash a file without loading it into memory."""
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def probe(path):
    """Read format and stream facts."""
    require_tool('ffprobe')
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError('ffprobe: ' + (result.stderr.strip() or 'could not read media'))
    return json.loads(result.stdout)


def require_tool(name):
    """Give an actionable error when a required media tool is absent."""
    if not shutil.which(name):
        raise ValueError(f'{name} not found; install FFmpeg (including ffmpeg and ffprobe) and add it to PATH')


def mapped_duration(facts, role):
    """Still images may have no duration; timed media needs a verified presentation bound."""
    try:
        return transcribe.presentation_duration(facts)
    except ValueError:
        if role == 'still':
            return 0.0
        raise


def add(root, files, role, copy=False, stream=None):
    """Register local paths, optionally copying to alias-named project media."""
    root = Path(root).resolve()
    project.init(root)
    target = root / 'map' / 'sources.json'
    for name in files:
        _add(root, name, role, copy, target, stream)


def _add(root, name, role, copy, target, stream=None):
    """Prepare media without holding the index lock, then register it atomically."""
    source = Path(name).resolve(strict=True)
    if (root / 'refs') in source.parents:
        raise ValueError(f'{source.name} is a reference (refs/, look.py): references are studied, never cut into the '
                         'film; add the original footage instead')
    fingerprint = digest(source)
    references = project.load_json(root / 'refs' / 'index.json', {}) or {}
    if any(row.get('sha256') == fingerprint for row in references.get('refs', []) if isinstance(row, dict)):
        raise ValueError(f'{source.name} is the same file as a reference in refs/: references are studied, never cut '
                         'into the film; add the original footage instead')
    facts = probe(source)
    video = next((s for s in facts['streams'] if s['codec_type'] == 'video'
                  and not s.get('disposition', {}).get('attached_pic')), None)
    audio = transcribe.audio_stream_info(facts, stream)
    temporary = None
    installed = None
    try:
        if copy:
            media = root / 'media'
            media.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(prefix='.map-copy-', suffix=source.suffix.lower(), dir=str(media))
            os.close(handle)
            temporary = Path(name)
            shutil.copyfile(source, temporary)
            if digest(temporary) != fingerprint:
                raise ValueError('source changed while being copied; add it again')
        size = (temporary or source).stat().st_size
        with project.file_lock(target):
            data = project.load_json(target, {'version': 1, 'sources': []})
            duplicate = next((row for row in data['sources'] if row.get('sha256') == fingerprint), None)
            if duplicate:
                print(f"already registered as {duplicate['alias']}; "
                      f"if moved, use map.py relink \"{root}\" {duplicate['alias']} PATH")
                return
            alias = project.new_alias(role, {row['alias'] for row in data['sources']})
            dest = root / 'media' / (alias + source.suffix.lower()) if copy else source
            if copy:
                try:
                    fd = os.open(str(dest), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as error:
                    raise ValueError(f'refusing to overwrite existing project media: {dest}') from error
                os.close(fd)
                installed = dest
                os.replace(temporary, dest)
                temporary = None
            try:
                stored_path = dest.relative_to(root).as_posix()
            except ValueError:
                stored_path = str(dest)
            row = {'alias': alias, 'role': role, 'path': stored_path, 'sha256': fingerprint,
                   'bytes': size, 'duration_s': mapped_duration(facts, role),
                   'video': None, 'audio': None, 'mapped': {'words': False, 'shots': False, 'audio': False}}
            if video:
                row['video'] = {**render_common.display_geometry(video), 'fps': video['avg_frame_rate']}
            if audio:
                row['audio'] = audio
            data['sources'].append(row)
            project.save_json(target, data)
            installed = None
            print(f'added {alias}')
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if installed is not None:
            installed.unlink(missing_ok=True)


def shots(path, end):
    """Find scene cut candidates with FFmpeg scdet: (shots, effects), where candidates that return to the same
    picture within EFFECT_S seconds are one effect inside a shot, not shot changes."""
    import re
    run = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(path), '-vf', 'scdet=threshold=10',
                          '-an', '-f', 'null', '-'], capture_output=True, text=True, check=True)
    times = [float(x) for x in re.findall(r'lavfi\.scd\.time:\s*([\d.]+)', run.stderr)]
    cuts, effects = split_effects(path, [t for t in times if 0 < t < end])
    boundaries = [0.0] + cuts + [end]
    return [{'start': a, 'end': b} for a, b in zip(boundaries, boundaries[1:])], effects


def thumbnail(path, moment):
    """A 32x18 grey thumbnail of the frame shown at a source time, or None when it cannot be decoded."""
    run = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-ss', f'{max(0.0, moment):.4f}',
                          '-i', str(path), '-map', '0:v:0', '-frames:v', '1', '-vf',
                          'scale=32:18:flags=area,format=gray', '-f', 'rawvideo', '-'], capture_output=True)
    return run.stdout if run.returncode == 0 and len(run.stdout) == 32 * 18 else None


def split_effects(path, times):
    """(shot changes, effects): a run of candidates each within EFFECT_S of the last, where the frame after the run
    matches the frame before it, is a flash or effect inside one shot and leaves the shot whole."""
    groups = []
    for moment in times:
        if groups and moment - groups[-1][-1] <= EFFECT_S:
            groups[-1].append(moment)
        else:
            groups.append([moment])
    cuts, effects = [], []
    for group in groups:
        if len(group) > 1:
            before, after = thumbnail(path, group[0] - 0.06), thumbnail(path, group[-1] + 0.02)
            if before is not None and after is not None:
                level = sum(abs(a - b) for a, b in zip(before, after)) / len(before)
                if level <= SAME_SHOT_LEVELS:
                    effects.append({'start': group[0], 'end': group[-1], 'changes': len(group),
                                    'kind': 'effect inside one shot', 'difference_levels': round(level, 1)})
                    continue
        cuts.extend(group)
    return cuts, effects


def audio_map(path, has_audio, length, stream=None):
    """Measure quarter-second RMS and FFmpeg loudness and silence events."""
    import re
    result = {'integrated_lufs': None, 'levels_db': {'step_s': 0.25, 'values': []},
              'speech_band_db': {'step_s': 0.25, 'values': []}, 'silences': []}
    if not has_audio:
        return result
    require_tool('ffmpeg')
    info = transcribe.probe_audio(path, stream)
    cmd = transcribe.audio_window_command(path, info['index'], 0.0, length, rate=8000)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    while True:
        raw = proc.stdout.read(8000)
        if not raw:
            break
        samples = np.frombuffer(raw[:len(raw) // 4 * 4], dtype='<f4')
        rms = math.sqrt(float(np.mean(samples * samples))) if len(samples) else 0
        result['levels_db']['values'].append(round(20 * math.log10(rms), 2) if rms > 1e-10 else -200.0)
        if len(samples):
            spectrum = np.fft.rfft(samples)
            frequencies = np.fft.rfftfreq(len(samples), 1 / 8000)
            spectrum[(frequencies < 150) | (frequencies > 3800)] = 0
            filtered = np.fft.irfft(spectrum, n=len(samples))
            speech_rms = math.sqrt(float(np.mean(filtered * filtered)))
        else:
            speech_rms = 0
        result['speech_band_db']['values'].append(round(20 * math.log10(speech_rms), 2)
                                                  if speech_rms > 1e-10 else -200.0)
    if proc.wait():
        raise ValueError('audio decode failed')
    clock = f"asetpts=PTS-({info['origin_s']:.9f})/TB,aresample=async=1:first_pts=0"
    run = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-copyts', '-i', str(path),
                          '-map', f"0:{info['index']}",
                          '-af', clock + f',ebur128,silencedetect=noise={SILENCE_DB}dB:d=0.1',
                          '-f', 'null', '-'],
                         capture_output=True, text=True, check=True)
    loudness = re.findall(r'I:\s*(-?[\d.]+) LUFS', run.stderr)
    if loudness:
        result['integrated_lufs'] = float(loudness[-1])
    events = re.findall(r'silence_(start|end):\s*(-?[\d.]+)', run.stderr)
    start = None
    for kind, value in events:
        if kind == 'start':
            start = max(0.0, float(value))
        elif start is not None:
            result['silences'].append({'start': start, 'end': float(value)})
            start = None
    if start is not None:
        result['silences'].append({'start': start, 'end': length})
    result['speech_activity'] = transcribe.speech_activity(path, info['index'], length)
    return result


def sheet_indices(count):
    """Choose every shot through 600, then evenly sample 600."""
    if count <= 600:
        return list(range(count))
    return [i * count // 600 for i in range(600)]


def transcript_markdown(alias, words, review=None, identity_state=None):
    """Write timed, readable phrases with each underlying word ID visible."""
    phrases = []
    group = []
    for word in words:
        if group and (len(group) >= 12 or word['start'] - group[-1]['end'] >= .6
                      or group[-1]['text'].rstrip().endswith(('.', '?', '!'))):
            phrases.append(group)
            group = []
        group.append(word)
    if group:
        phrases.append(group)
    lines = [f'# Transcript: {alias}', '',
             'Draft: check the words against the sound. Correct a word by its ID with map.py fix.', '']
    if identity_state == 'stale':
        lines.extend([f'STALE: this transcript is not bound to the current media and sound stream. '
                      f'Retranscribe with --retranscribe {alias}, or check it and use '
                      f'map.py confirm-words PROJECT {alias} --note TEXT.', ''])
    if review:
        lines.extend(['## Review prompts', '', review['note'], review['energy_check'], ''])
        for prompt in review['prompts']:
            ids = ' '.join('`' + str(word_id) + '`' for word_id in prompt.get('word_ids', []) if word_id)
            lines.append(f"- {project.format_time(prompt['start'])}-{project.format_time(prompt['end'])}: "
                         f"{prompt['detail']} {ids}".rstrip())
        lines.append('')
    for phrase in phrases:
        start = project.format_time(phrase[0]['start'])
        end = project.format_time(phrase[-1]['end'])
        text = ' '.join(str(word.get('text', '')).strip() for word in phrase)
        ids = ' '.join('`' + str(word.get('id', '?')) + '`' for word in phrase)
        lines += [f'**{start}-{end}**  {text}', '', ids, '']
    return '\n'.join(lines)


def write_transcript(folder, alias, words, identity_state=None, audio_current=True):
    """Refresh the human-readable transcript from the authoritative words."""
    folder = Path(folder)
    audio = project.load_json(folder / 'audio.json', {}) if audio_current else {}
    review = transcribe.transcript_review(words, audio)
    review['source'] = alias
    project.save_json(folder / 'transcript-review.json', review)
    project.write_atomic(folder / 'transcript.md', transcript_markdown(alias, words, review, identity_state))


def source_at_file(root, source):
    """Compare against current file bytes, not just the last registered fingerprint."""
    current = dict(source)
    if not source.get('path'):
        return current
    path = Path(root) / source['path']
    if path.is_file():
        current['sha256'] = digest(path)
    return current


STALE = []


class NotTranscribed(ValueError):
    """transcribe.py could not run here and has already printed why and the fix."""


def warn_stale(root, source, data):
    """Show both explicit ways to resolve a transcript bound to different media or a different stream. A stale
    transcript makes the command exit 1, so a caller that reads only the exit code does not take its words as usable."""
    state, reason = project.transcript_state(source, data)
    media = project.transcript_media(data)
    if state == 'current' and ((media or {}).get('audio_stream') is None
                               or (source.get('audio') or {}).get('index') is None):
        state, reason = 'stale', 'the transcript or source does not record its sound stream'
    if state == 'stale':
        alias = source['alias']
        STALE.append(alias)
        print(f'warning: {alias} transcript is stale: {reason}. '
              f'Retranscribe with map.py run "{root}" --alias {alias} --retranscribe {alias}, '
              f'or check it and use map.py confirm-words "{root}" {alias} --note TEXT.', file=sys.stderr)
    return state


def bind_legacy_words(path, source, actual):
    """Preserve an old transcript against the source registered before the current file was inspected."""
    path = Path(path)
    if not path.is_file():
        return
    with project.file_lock(path):
        data = project.load_json(path, None)
        if not isinstance(data, dict) or project.transcript_media(data):
            return
        old_hash = source.get('sha256')
        if not isinstance(old_hash, str) or not old_hash:
            print(f"warning: {source['alias']} transcript is unbound and the registered media hash is missing; "
                  'retranscribe or confirm it after checking.', file=sys.stderr)
            return
        stream = data.get('audio_stream')
        if stream is None:
            stream = (source.get('audio') or {}).get('index')
        media = {'sha256': old_hash, 'audio_stream': stream, 'binding': 'previous source registration'}
        if source.get('bytes') is not None:
            media['bytes'] = source['bytes']
        data['media'] = media
        project.save_json(path, data)
        if old_hash == actual:
            print(f"{source['alias']}: bound the legacy transcript to the unchanged registered media")
        else:
            print(f"{source['alias']}: bound the legacy transcript to the previously registered media")


def confirm_words(root, alias, note, by='agent', stream_index=None):
    """Record a checked transcript's deliberate rebind and append its decision."""
    note = (note or '').strip()
    if not note:
        raise ValueError('confirmation needs a nonempty --note describing the check')
    root = Path(root).resolve()
    index = root / 'map' / 'sources.json'
    words_path = root / 'map' / alias / 'words.json'
    with project.file_lock(index):
        data = project.load_json(index, None)
        sources = data.get('sources', []) if isinstance(data, dict) else []
        source = next((row for row in sources if row.get('alias') == alias), None)
        if source is None:
            raise ValueError(f'unknown alias: {alias}')
        path = root / source['path']
        if not path.is_file():
            raise ValueError(f'{alias}: source is missing; relink it before confirming')
        actual = digest(path)
        size = path.stat().st_size
        facts = probe(path)
        selected = stream_index if stream_index is not None else (source.get('audio') or {}).get('index')
        stream = transcribe.audio_stream_info(facts, selected)
        if stream is None:
            raise ValueError(f'{alias}: source has no audio stream to confirm')
        if digest(path) != actual or path.stat().st_size != size:
            raise ValueError(f'{alias}: source changed while confirming; try again')
        with project.file_lock(words_path):
            if not words_path.is_file():
                raise ValueError(f'{alias} has no words.json; map the source first')
            original = project.read_text(words_path)
            words = json.loads(original)
            if not isinstance(words, dict) or not isinstance(words.get('words'), list):
                raise ValueError(f'{words_path}: not a readable transcript')
            previous = project.transcript_media(words)
            confirmation = {'at': project.now(), 'by': by, 'note': note, 'previous_media': previous}
            words['media'] = {'sha256': actual, 'bytes': size, 'audio_stream': stream['index'],
                              'confirmation': confirmation}
            decision = {'at': confirmation['at'], 'by': by, 'category': 'captions', 'subject': alias,
                        'decision': f'Confirmed transcript against current media: {note}', 'rejected': [],
                        'version': project.current_version(root)}
            old_index = json.dumps(data)
            if actual != source.get('sha256') or stream != source.get('audio'):
                source.update(sha256=actual, bytes=size, audio=stream,
                              duration_s=mapped_duration(facts, source['role']))
                video = next((row for row in facts['streams'] if row['codec_type'] == 'video'
                              and not row.get('disposition', {}).get('attached_pic')), None)
                source['video'] = ({**render_common.display_geometry(video), 'fps': video['avg_frame_rate']}
                                   if video else None)
                source.setdefault('mapped', {}).update(shots=False, audio=False)
            project.save_json(words_path, words)
            try:
                project.save_json(index, data)
                project.append_jsonl(root / 'decisions.jsonl', decision)
            except BaseException:
                project.write_atomic(words_path, original)
                project.write_atomic(index, old_index)
                raise
            try:
                write_transcript(words_path.parent, alias, words['words'], 'current',
                                 bool((source.get('mapped') or {}).get('audio')))
            except (OSError, ValueError, TypeError, KeyError) as error:
                print(f'warning: confirmation saved, but transcript.md was not refreshed: {error}; '
                      f'run map.py run with --alias {alias}', file=sys.stderr)
    print(f'{alias}: transcript confirmed against current media; decision recorded')


def fix_word(root, word_id, text=None, by='agent', start=None, end=None):
    """Correct a word's text or edges under its transcript lock and append an audit decision."""
    root = Path(root).resolve()
    if text is not None:
        text = text.strip()
        if not text or any(char in text for char in '\r\n'):
            raise ValueError('TEXT must be a nonempty, single-line correction')
    if text is None and start is None and end is None:
        raise ValueError('give TEXT, --start or --end')
    sources = project.load_json(root / 'map' / 'sources.json', {}).get('sources', [])
    matches = [row for row in sources if word_id.startswith(row['alias'] + '-w')]
    if len(matches) != 1:
        aliases = sorted(row['alias'] for row in sources)
        close = difflib.get_close_matches(word_id.split('-w')[0], aliases, 1, 0.5)
        hint = (f'; did you mean {close[0]}? ' if close else '; ') + (
            f'registered sources: {", ".join(aliases)}' if aliases else 'no sources are registered')
        raise ValueError(f'{word_id}: no registered source has that word ID{hint}')
    source = matches[0]
    alias = source['alias']
    folder = root / 'map' / alias
    path = folder / 'words.json'
    with project.file_lock(path):
        if not path.is_file():
            raise ValueError(f'{alias} has no words.json; map the source first')
        original = project.read_text(path)
        data = json.loads(original)
        identity_state = warn_stale(root, source_at_file(root, source), data)
        words = data.get('words', [])
        matches = [index for index, row in enumerate(words) if row.get('id') == word_id]
        if not matches:
            raise ValueError(f'{word_id}: no such word in {alias}; {nearest_word(words, word_id)}')
        if len(matches) != 1:
            raise ValueError(f'{word_id}: expected one word, found {len(matches)}')
        index = matches[0]
        word = words[index]
        before = {key: word.get(key) for key in ('text', 'start', 'end')}
        after = dict(before)
        if text is not None:
            after['text'] = text
        if start is not None or end is not None:
            try:
                duration = float(source['duration_s'])
                after['start'] = float(start if start is not None else before['start'])
                after['end'] = float(end if end is not None else before['end'])
                previous = float(words[index - 1]['end']) if index else 0.0
                following = float(words[index + 1]['start']) if index + 1 < len(words) else duration
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError('timing correction needs a source duration and valid neighbouring word edges') \
                    from error
            values = (duration, previous, following, after['start'], after['end'])
            if (not all(math.isfinite(value) for value in values)
                    or not 0 <= previous <= after['start'] < after['end'] <= following <= duration):
                raise ValueError('word times must be within the source, start before end, and not overlap neighbours'
                                 + timing_window(words, index, duration, after))
        if before == after:
            print(f'{word_id}: no change ({word_place(words, index)})')
            return
        old_words = [dict(row) for row in words]
        word.update(after)
        decision = {'at': project.now(), 'by': by, 'category': 'captions', 'subject': word_id,
                    'decision': f'Correct transcript word from {before!r} to {after!r}',
                    'rejected': [], 'version': project.current_version(root)}
        project.save_json(path, data)
        try:
            project.append_jsonl(root / 'decisions.jsonl', decision)
        except BaseException:
            project.write_atomic(path, original)
            raise
        try:
            write_transcript(folder, alias, words, identity_state)
        except OSError as error:
            print(f'warning: correction saved, but transcript.md was not refreshed: {error}; '
                  f'run map.py run with --alias {alias}', file=sys.stderr)
    print(fix_summary(word_id, before, after))
    print(f'  before: {word_context(old_words, index)}')
    print(f'  after:  {word_context(words, index)}')
    for row in film_matches(root, alias, old_words, words, index, [item['alias'] for item in sources]):
        print(row)


def timing_window(words, index, duration, asked):
    """Why a timing correction was refused: the times asked for, the neighbouring words with their times, and the
    range the word's edges must stay within."""
    def seconds(value):
        return f'{value:.3f}' if isinstance(value, float) and math.isfinite(value) else str(value)
    low = float(words[index - 1]['end']) if index else 0.0
    high = float(words[index + 1]['start']) if index + 1 < len(words) else duration
    rows = [f'; asked for {seconds(asked["start"])}-{seconds(asked["end"])} s']
    if index:
        before = words[index - 1]
        rows.append(f'the word before is {before.get("id")} "{before.get("text")}" at '
                    f'{float(before["start"]):.3f}-{low:.3f} s')
    else:
        rows.append('no word before it (the source starts at 0.000 s)')
    if index + 1 < len(words):
        after = words[index + 1]
        rows.append(f'the word after is {after.get("id")} "{after.get("text")}" at '
                    f'{high:.3f}-{float(after["end"]):.3f} s')
    else:
        rows.append(f'no word after it (the source ends at {duration:.3f} s)')
    rows.append(f'start and end must fall within {low:.3f}-{high:.3f} s, start before end')
    return '; '.join(rows)


def word_place(words, index):
    """A word's text and source time, for a message."""
    word = words[index]
    return f'"{word.get("text")}" at {project.format_time(float(word["start"]))}'


def nearest_word(words, word_id):
    """The existing word ID nearest a missing one by number, with its text and time, and the source's ID range."""
    numbered = []
    for index, row in enumerate(words):
        tail = str(row.get('id', '')).rsplit('-w', 1)[-1]
        if tail.isdigit():
            numbered.append((int(tail), index))
    if not numbered:
        return 'the transcript has no word IDs'
    wanted = word_id.rsplit('-w', 1)[-1]
    number = int(wanted) if wanted.isdigit() else 0
    _, index = min(numbered, key=lambda pair: (abs(pair[0] - number), pair[0]))
    first, last = words[min(numbered)[1]]['id'], words[max(numbered)[1]]['id']
    return f'the nearest is {words[index]["id"]} {word_place(words, index)} (IDs run {first} to {last})'


def word_context(words, index, reach=4):
    """A few words either side of one word, the word itself in [brackets]."""
    low, high = max(0, index - reach), min(len(words), index + reach + 1)
    parts = [f'[{row.get("text")}]' if spot == index else str(row.get('text'))
             for spot, row in enumerate(words[low:high], low)]
    return ('... ' if low else '') + ' '.join(parts) + (' ...' if high < len(words) else '')


def fix_summary(word_id, before, after):
    """The word's ID, time and what changed, before and after."""
    def span(row):
        return f'{project.format_time(float(row["start"]))}-{project.format_time(float(row["end"]))}'
    parts = [f'{word_id} at {span(before)}:']
    if before['text'] != after['text']:
        parts.append(f'"{before["text"]}" -> "{after["text"]}"')
    if (before['start'], before['end']) != (after['start'], after['end']):
        parts.append(f'timing {span(before)} -> {span(after)}')
    return ' '.join(parts) + '; ID retained'


def cut_words(rows):
    """Transcript rows the way cut.py reads them (worded and timed, each with its index), and for every row its place
    in that list (None for a row cut.py skips), so a film.md line can be matched against them."""
    kept, places = [], []
    for row in rows:
        usable = (str(row.get('text', '')).strip() and isinstance(row.get('start'), (int, float))
                  and isinstance(row.get('end'), (int, float)))
        places.append(len(kept) if usable else None)
        if usable:
            kept.append(dict(row, index=len(kept)))
    return kept, places


def film_matches(root, alias, old_rows, new_rows, index, aliases):
    """Lines telling which film.md spoken lines over the changed word stop (or start) matching the transcript, the
    way cut.py check matches them. Empty when film.md has no line over the word."""
    film = root / 'film.md'
    if not film.is_file():
        return []
    try:
        cut_spec = importlib.util.spec_from_file_location('lf_map_cut', SCRIPTS / 'cut.py')
        cut = importlib.util.module_from_spec(cut_spec)
        cut_spec.loader.exec_module(cut)
        _, entries = cut.parse_film(project.read_text(film), cut.Problems(), aliases, root)
    except Exception as error:  # the correction is saved; a film.md this cannot read is cut.py check's to report
        return [f'film.md not compared: {error}']
    old_words, old_places = cut_words(old_rows)
    new_words, new_places = cut_words(new_rows)
    rows = []
    for entry in entries:
        if entry.get('kind') != 'spoken' or entry.get('alias') != alias or entry.get('bad'):
            continue
        if (old_places[index] not in cut.range_words(old_words, entry['start'], entry['end'])
                and new_places[index] not in cut.range_words(new_words, entry['start'], entry['end'])):
            continue
        before = cut.match_spoken(entry, old_words, cut.Problems()) is not None
        problems = cut.Problems()
        after = cut.match_spoken(entry, new_words, problems) is not None
        where = f'film.md line {entry["line"]} ({alias} {cut.fmt(entry["start"])}-{cut.fmt(entry["end"])})'
        if before and not after:
            why = problems.items[0]['message'] if problems.items else 'it no longer matches'
            old, new = old_rows[index].get('text'), new_rows[index].get('text')
            rows.append(f'{where} stops matching: {why}; write "{new}" for "{old}" in that line, or put the word '
                        f'back with map.py fix PROJECT {new_rows[index].get("id")} "{old}"')
        elif after and not before:
            rows.append(f'{where} now matches the transcript')
        elif after:
            rows.append(f'{where} still matches')
    return rows


def level_track(audio):
    """(step seconds, values) of the map's quarter-second levels_db, or None when the map has none."""
    track = audio.get('levels_db') if isinstance(audio, dict) else None
    if not isinstance(track, dict):
        return None
    values, step = track.get('values'), track.get('step_s')
    if not isinstance(values, list) or not values or not isinstance(step, (int, float)) or step <= 0:
        return None
    return float(step), [float(value) for value in values]


def speech_segments(audio):
    """Sorted voice-activity speech spans from audio.json, or None for maps without them (older maps, or mapped
    without faster-whisper, which stores null)."""
    activity = audio.get('speech_activity') if isinstance(audio, dict) else None
    rows = activity.get('segments') if isinstance(activity, dict) else None
    if not isinstance(rows, list):
        return None
    spans = [(float(row[0]), float(row[1])) for row in rows if isinstance(row, (list, tuple)) and len(row) >= 2]
    return sorted(span for span in spans if span[1] > span[0])


def unspoken_spans(segments, duration):
    """The stretches of [0, duration] that no speech span covers."""
    spans = []
    cursor = 0.0
    for start, end in segments:
        if start > cursor:
            spans.append((cursor, start))
        cursor = max(cursor, end)
    if duration > cursor:
        spans.append((cursor, duration))
    return spans


def levels_centred(track, start, end):
    """Levels of the bins whose centres fall in [start, end]; the bin holding the midpoint when none does."""
    step, values = track
    first = max(0, int(math.ceil(start / step - 0.5)))
    last = min(len(values) - 1, int(math.floor(end / step - 0.5)))
    if last >= first:
        return values[first:last + 1]
    index = int((start + end) / 2 / step)
    return [values[index]] if 0 <= index < len(values) else []


def levels_touching(track, start, end):
    """Levels of every bin that overlaps [start, end]."""
    step, values = track
    first = max(0, int(start / step))
    last = min(len(values), max(first + 1, int(math.ceil(end / step))))
    return values[first:last]


def touches(span, low, high):
    """Whether a span overlaps [low, high], or contains the point when low == high."""
    if high > low:
        return span[0] < high and span[1] > low
    return span[0] < low < span[1]


def overlap(first, second):
    """Seconds two spans share."""
    return max(0.0, min(first[1], second[1]) - max(first[0], second[0]))


def threshold_coverage(words, segments, unspoken, track, silences, duration):
    """(clear pauses, how many the fixed-threshold silences touch, typical quietest level) over the whole source.
    Pauses are voice-activity gaps, else word gaps, between speech; a pause is clear when it lasts CLEAR_PAUSE_S and
    its quietest quarter-second falls CLEAR_DROP_DB below the median level of the source's speech."""
    if track is None or not isinstance(silences, list):
        return None
    if unspoken is not None:
        candidates = [span for span in unspoken if span[0] > 0 and span[1] < duration]
        speech = segments
    else:
        edges = [(float(word['start']), float(word['end'])) for word in words]
        candidates = [(left[1], right[0]) for left, right in zip(edges, edges[1:])]
        speech = edges
    spoken = [level for start, end in speech for level in levels_centred(track, start, end)]
    if not spoken:
        return None
    speech_db = float(np.median(spoken))
    clear = []
    for span in candidates:
        if span[1] - span[0] < CLEAR_PAUSE_S:
            continue
        floor = min(levels_centred(track, *span), default=None)
        if floor is not None and floor <= speech_db - CLEAR_DROP_DB:
            clear.append((span, floor))
    quiet = [(float(row['start']), float(row['end'])) for row in silences]
    seen = sum(1 for span, _ in clear if any(overlap(span, row) > 0 for row in quiet))
    typical = float(np.median([floor for _, floor in clear])) if clear else None
    return len(clear), seen, typical


def words_header(unspoken, track, silences, coverage):
    """The legend for map.py words, naming which measurements this map holds."""
    lines = ['Source seconds. Word edges are estimates and a word gap is not silence; listen before cutting.']
    if unspoken is not None:
        lines.append(f'Nothing spoken: no speech from the map\'s voice-activity model; it joins pauses under about '
                     f'{VAD_JOIN_S:.1f}s and its edges can be 0.2s out.')
    else:
        lines.append('Nothing spoken: unavailable; this map has no voice activity (mapped before it was recorded, or '
                     'without faster-whisper). Install it with setup.py --install transcription and add it with '
                     'map.py run PROJECT --alias ALIAS --rebuild; the transcript is kept.')
    if track is not None:
        lines.append('Level: the quietest quarter-second in the gap, and how far it falls below the loudest '
                     'quarter-second of the words either side.')
    else:
        lines.append('Level: unavailable; this map has no quarter-second levels.')
    if not isinstance(silences, list):
        lines.append('Threshold quiet: unavailable; this map has no silence list.')
    elif coverage and coverage[0] >= 3 and coverage[1] * 2 < coverage[0]:
        lines.append(f'Threshold quiet (FFmpeg silencedetect, fixed {SILENCE_DB} dB) touches {coverage[1]} of the '
                     f'{coverage[0]} clear pauses in this source: its room tone stays above the threshold (quietest '
                     f'quarter-second typically {coverage[2]:.1f} dB, and every sample must fall below '
                     f'{SILENCE_DB} dB), so it cannot see these pauses. Judge them by nothing spoken and level.')
    else:
        lines.append(f'Threshold quiet: FFmpeg silencedetect below {SILENCE_DB} dB, sample-accurate; shown only where '
                     f'it found quiet.')
    return lines


def gap_line(before, after, unspoken, track, silences):
    """One line describing the pause between two words, or None when they touch and nothing hears a pause."""
    low, high = float(before['end']), float(after['start'])
    gap = max(0.0, high - low)
    bounds = (float(before['start']), float(after['end']))
    pause = None
    missed = []
    if unspoken is not None:
        found = [span for span in unspoken if touches(span, min(low, high), max(low, high))]
        widest = max(found, key=lambda span: span[1] - span[0], default=None)
        if widest is not None:
            pause = (max(widest[0], bounds[0]), min(widest[1], bounds[1]))
            missed = [word for word in (before, after) if overlap(widest, (float(word['start']), float(word['end'])))
                      >= float(word['end']) - float(word['start']) - 0.02]
    if gap <= 0 and pause is None:
        return None
    parts = [f'word gap {gap:.3f}s']
    if unspoken is not None and pause is None:
        parts.append('voice activity: no pause')
    elif pause is not None:
        parts.append(f'nothing spoken {pause[0]:.3f}-{pause[1]:.3f}s ({pause[1] - pause[0]:.3f}s)')
    for word in missed:
        parts.append(f"voice activity hears no speech during \"{word.get('text', '')}\"; check that word")
    if track is not None:
        parts.append(gap_level(track, before, after, (low, high), pause))
    if isinstance(silences, list):
        quiet = max((overlap((low, high), (float(row['start']), float(row['end']))) for row in silences),
                    default=0.0)
        if quiet > 0:
            parts.append(f'threshold quiet {quiet:.3f}s (below {SILENCE_DB} dB)')
    return '  ' + '; '.join(parts)


def gap_level(track, before, after, gap, pause):
    """The gap's quietest quarter-second and its drop below the louder bins of the words either side. It is
    measured where the word gap and the unspoken stretch agree, else whichever spans at least one level step."""
    step = track[0]
    span = gap
    if pause is not None:
        shared = (max(gap[0], pause[0]), min(gap[1], pause[1]))
        if shared[1] - shared[0] >= step:
            span = shared
        elif gap[1] - gap[0] < step and pause[1] - pause[0] >= step:
            span = pause
    if span[1] - span[0] < step:
        return f'level not measurable (shorter than one {step:g}s level step)'
    floor = min(levels_centred(track, *span), default=None)
    sides = [max(levels_touching(track, float(word['start']), float(word['end'])), default=None)
             for word in (before, after)]
    if floor is None or None in sides:
        return 'level unavailable (outside the measured audio)'
    drop = min(sides) - floor
    if drop < 1:
        return f'level {floor:.1f} dB, no lower than the words either side'
    return f'level falls to {floor:.1f} dB, {drop:.0f} dB below the words either side'


def show_words(root, alias, from_time=None, to_time=None):
    """Print source-clock word edges and, between consecutive displayed words, the pause a cut can use."""
    root = Path(root).resolve()
    sources = project.load_json(root / 'map' / 'sources.json', {}).get('sources', [])
    source = next((row for row in sources if row.get('alias') == alias), None)
    if source is None:
        raise ValueError(f'unknown alias: {alias}')
    start = project.parse_time(from_time) if from_time is not None else 0.0
    end = project.parse_time(to_time) if to_time is not None else float(source.get('duration_s') or float('inf'))
    if end <= start:
        raise ValueError('--to must be after --from')
    folder = root / 'map' / alias
    data = project.load_json(folder / 'words.json', None)
    if not isinstance(data, dict) or not isinstance(data.get('words'), list):
        raise ValueError(f'{alias} has no readable words.json')
    warn_stale(root, source_at_file(root, source), data)
    audio = project.load_json(folder / 'audio.json', None)
    silences = audio.get('silences') if isinstance(audio, dict) else None
    track = level_track(audio)
    segments = speech_segments(audio)
    words = data['words']
    duration = float(source.get('duration_s') or 0.0)
    if duration <= 0:
        duration = max([float(word['end']) for word in words] + [row[1] for row in segments or []] + [0.0])
    unspoken = unspoken_spans(segments, duration) if segments is not None else None
    coverage = threshold_coverage(words, segments, unspoken, track, silences, duration)
    selected = [word for word in words if float(word['end']) >= start and float(word['start']) <= end]
    print('\n'.join(words_header(unspoken, track, silences, coverage)))
    previous = None
    for word in selected:
        if previous is not None:
            line = gap_line(previous, word, unspoken, track, silences)
            if line:
                print(line)
        print(f"{word.get('id', '?')} {float(word['start']):.3f}-{float(word['end']):.3f}s {word.get('text', '')}")
        previous = word
    if not selected:
        print('No words in this range.')


def map_key(sha256, stream):
    """Identity for shot/sheet/audio outputs; transcript replacement has separate explicit controls."""
    return {'format_version': MAP_FORMAT_VERSION, 'sha256': sha256, 'audio_stream': stream}


def map_complete(folder, source, key):
    """Check the v1 output structure and files without decoding media or rehashing the source."""
    folder = Path(folder)
    cache = project.load_json(folder / 'cache.json', None)
    legacy = (isinstance(cache, dict) and 'format_version' not in cache
              and isinstance(cache.get('scripts'), dict) and isinstance(cache.get('ffmpeg'), list))
    if not isinstance(key['sha256'], str) or len(key['sha256']) != 64:
        return False, 'source identity is missing'
    if legacy:
        if MAP_FORMAT_VERSION != 1:
            return False, 'legacy map predates this map format'
        if cache.get('sha256') != key['sha256'] or cache.get('audio_stream') != key['audio_stream']:
            return False, 'legacy cache source or audio stream differs'
    elif cache != key:
        return False, 'cache identity or map format differs'
    shots_data = project.load_json(folder / 'shots.json', None)
    audio = project.load_json(folder / 'audio.json', None)
    alias = source['alias']
    if (not isinstance(shots_data, dict) or shots_data.get('version') != 1
            or shots_data.get('source') != alias or not isinstance(shots_data.get('shots'), list)):
        return False, 'missing or invalid shots.json'
    if (not isinstance(audio, dict) or audio.get('version') != 1 or audio.get('source') != alias
            or audio.get('stream_index') != key['audio_stream'] or not isinstance(audio.get('silences'), list)):
        return False, 'missing or invalid audio.json'
    for name in ('levels_db', 'speech_band_db'):
        levels = audio.get(name)
        if not isinstance(levels, dict) or not isinstance(levels.get('values'), list):
            return False, 'missing audio measurements: ' + name
    if (source.get('mapped') or {}).get('words'):
        transcript = project.load_json(folder / 'words.json', None)
        if not isinstance(transcript, dict) or not isinstance(transcript.get('words'), list):
            return False, 'missing or invalid words.json'
    rows = shots_data['shots']
    if source.get('video') and not rows:
        return False, 'video has no mapped shots'
    expected = set(sheet_indices(len(rows))) if source.get('video') else set()
    for number, row in enumerate(rows):
        if not isinstance(row, dict):
            return False, 'invalid shot'
        try:
            valid = (math.isfinite(float(row['start'])) and math.isfinite(float(row['end']))
                     and 0 <= float(row['start']) < float(row['end']))
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            return False, 'invalid shot range'
        if number in expected:
            name = row.get('sheet')
            if not isinstance(name, str) or Path(name).name != name or not (folder / name).is_file():
                return False, 'missing referenced contact sheet'
            if not isinstance(row.get('tile'), int) or not 1 <= row['tile'] <= 60:
                return False, 'invalid sheet tile'
    return True, 'legacy v1 outputs' if legacy else 'current map format'


def check_map(root, aliases):
    """Report structural completeness quickly, without changing files or reading source contents."""
    root = Path(root).resolve()
    data = project.load_json(root / 'map' / 'sources.json', None)
    if not isinstance(data, dict) or not data.get('sources'):
        raise ValueError('no sources registered')
    selected = [row for row in data['sources'] if not aliases or row['alias'] in aliases]
    if aliases and set(aliases) != {row['alias'] for row in selected}:
        raise ValueError('unknown alias')
    complete = True
    for source in selected:
        path = root / source['path']
        key = map_key(source.get('sha256'), (source.get('audio') or {}).get('index'))
        if not path.is_file():
            ok, detail = False, 'source missing'
        else:
            try:
                ok, detail = map_complete(root / 'map' / source['alias'], source, key)
            except (OSError, ValueError, TypeError, KeyError) as error:
                ok, detail = False, str(error)
        complete = complete and ok
        words = 'transcript present' if (root / 'map' / source['alias'] / 'words.json').is_file() else 'no transcript'
        if words == 'transcript present':
            transcript = project.load_json(root / 'map' / source['alias'] / 'words.json', {})
            warn_stale(root, source, transcript)
        print(f"{source['alias']}: {'complete' if ok else 'incomplete'} ({detail}; {words})")
    print('File and structure check only; source content was not rehashed and transcript accuracy was not checked.')
    return 0 if complete else 1


def clean_words_temps(folder, unknown_mapper):
    """Remove abandoned transcript temporaries without touching a live mapper's file."""
    uncertain = False
    for path in folder.glob('.words-*.json'):
        parts = path.name[len('.words-'):].split('-', 1)
        pid = int(parts[0]) if len(parts) == 2 and parts[0].isdigit() else None
        known = pid is not None and 0 < pid <= 2147483647
        if not known and unknown_mapper:
            uncertain = True
            continue
        if known and project.process_alive(pid):
            continue
        path.unlink(missing_ok=True)
    if uncertain:
        print('warning: retained old transcript temporaries because an earlier map job has no PID; '
              'rerun after confirming it has stopped', file=sys.stderr)


def run(root, aliases, words_mode, ggml_model=None, engine=None, quality=None, retranscribe=None, stream=None,
        prompt=None, rebuild=False, download=False):
    """Map each source and cache outputs by source, audio stream and map format."""
    root = Path(root).resolve()
    index = root / 'map' / 'sources.json'
    data = project.load_json(index)
    if not data:
        raise ValueError('no sources registered')
    selected = [s for s in data['sources'] if not aliases or s['alias'] in aliases]
    if aliases and set(aliases) != {s['alias'] for s in selected}:
        raise ValueError('unknown alias')
    if words_mode.startswith('import:') and (not aliases or len(aliases) != 1):
        raise ValueError('--words import:FILE requires exactly one --alias')
    if retranscribe and (retranscribe not in {s['alias'] for s in selected} or words_mode == 'skip'):
        raise ValueError('--retranscribe must name a selected alias and requires words')
    if stream is not None and (not aliases or len(aliases) != 1):
        raise ValueError('--stream on run requires exactly one --alias')
    for name in ('ffmpeg', 'ffprobe'):
        require_tool(name)
    project.set_stage(root, 'map', 'mapping sources')
    owned = set()
    try:
        for i, source in enumerate(selected):
            alias = source['alias']
            job_name = 'map ' + alias
            folder = root / 'map' / alias
            folder.mkdir(parents=True, exist_ok=True)
            with project.file_lock(root / 'status.json'):
                status = project.read_status(root)
                previous = [job for job in status.get('running', []) if job.get('job') == job_name]
                if any(type(job.get('pid')) is int and 0 < job['pid'] <= 2147483647
                       and project.process_alive(job['pid']) for job in previous):
                    raise ValueError(f'{alias}: mapping is already running; wait for it to finish')
                clean_words_temps(folder, bool(previous))
                running = [job for job in status.get('running', []) if job.get('job') != job_name]
                running.append({'job': job_name, 'started': project.now(), 'progress': i / len(selected),
                                'pid': os.getpid()})
                project._update_status(root, {'running': running})
                owned.add(job_name)
            path = root / source['path']
            if not path.is_file():
                raise ValueError(f'source {alias} is missing; use map.py relink "{root}" {alias} PATH')
            actual = digest(path)
            facts = probe(path)
            current_video = next((s for s in facts['streams'] if s['codec_type'] == 'video'
                                  and not s.get('disposition', {}).get('attached_pic')), None)
            if current_video:
                source['video'] = {**render_common.display_geometry(current_video),
                                   'fps': current_video['avg_frame_rate']}
            old_audio = source.get('audio') or {}
            old_index = old_audio.get('index')
            try:
                selected_audio = transcribe.audio_stream_info(facts, stream if stream is not None else old_index)
            except ValueError as error:
                if (folder / 'words.json').exists():
                    bind_legacy_words(folder / 'words.json', source, actual)
                    raise ValueError(f'{alias}: transcript stream is unavailable ({error}); '
                                     f'use --stream INDEX --retranscribe {alias}, or check it and use '
                                     f'map.py confirm-words "{root}" {alias} --stream INDEX --note TEXT') from error
                raise
            if (old_index is not None and selected_audio and old_index != selected_audio['index']
                    and (folder / 'words.json').exists() and retranscribe != alias):
                raise ValueError(f'{alias}: changing streams needs --retranscribe {alias} or a checked '
                                 f'map.py confirm-words "{root}" {alias} --stream {selected_audio["index"]} '
                                 '--note TEXT')
            bind_legacy_words(folder / 'words.json', source, actual)
            source['audio'] = selected_audio
            key = map_key(actual, selected_audio['index'] if selected_audio else None)
            try:
                complete, detail = map_complete(folder, source, key)
            except (OSError, ValueError, TypeError, KeyError):
                complete, detail = False, 'invalid map'
            if complete and not rebuild:
                print(f'{alias}: cached ({detail})')
                if detail == 'legacy v1 outputs':
                    print(f'{alias}: reusing pre-versioned v1 outputs; --rebuild regenerates them')
            else:
                source['sha256'] = actual
                source['bytes'] = path.stat().st_size
                source['duration_s'] = mapped_duration(facts, source['role'])
                found, effects = shots(path, source['duration_s']) if source.get('video') else ([], [])
                sampled = len(found) > 600
                indices = sheet_indices(len(found))
                for page in range(0, len(indices), 60):
                    batch = indices[page:page + 60]
                    times = [(found[n]['start'] + found[n]['end']) / 2 for n in batch]
                    sheet = folder / f'sheet-{page // 60 + 1:02d}.jpg'
                    handle, temporary = tempfile.mkstemp(prefix='.sheet-', suffix='.jpg', dir=str(folder))
                    os.close(handle)
                    try:
                        cmd = [sys.executable, str(SCRIPTS / 'frame_sheet.py'), str(path), '--at',
                               ','.join(str(t) for t in times), '--width', '240', '--out', temporary]
                        subprocess.run(cmd, check=True, capture_output=True, text=True)
                        os.replace(temporary, sheet)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                    for tile, n in enumerate(batch, 1):
                        found[n].update({'sheet': sheet.name, 'tile': tile})
                project.save_json(folder / 'shots.json', {'version': 1, 'source': alias, 'shots': found,
                                                         'effects': effects, 'sampled': sampled,
                                                         'sampled_count': len(indices)})
                audio = audio_map(path, bool(selected_audio), source['duration_s'],
                                  selected_audio['index'] if selected_audio else None)
                audio['stream_index'] = selected_audio['index'] if selected_audio else None
                project.save_json(folder / 'audio.json', {'version': 1, 'source': alias, **audio})
                source['mapped'].update({'shots': True, 'audio': True})
                with project.file_lock(index):
                    latest = project.load_json(index)
                    target = next(s for s in latest['sources'] if s['alias'] == alias)
                    target.update({key: source[key] for key in ('sha256', 'bytes', 'duration_s', 'video')})
                    target.setdefault('mapped', {}).update({'shots': True, 'audio': True})
                    project.save_json(index, latest)
                    data = latest
                    source = target
                    source['audio'] = selected_audio
            if words_mode != 'skip' and source.get('audio'):
                if not (folder / 'words.json').exists() or retranscribe == alias:
                    words_path = folder / 'words.json'
                    before = digest(words_path) if words_path.exists() else None
                    if before is not None and retranscribe != alias:
                        raise ValueError(f'{alias}: transcript appeared during mapping; retained it')
                    handle, temporary = tempfile.mkstemp(prefix=f'.words-{os.getpid()}-', suffix='.json',
                                                        dir=str(folder))
                    os.close(handle)
                    cmd = [sys.executable, str(SCRIPTS / 'transcribe.py'), str(path), '--project', str(root),
                           '--alias', alias, '--out', temporary]
                    cmd += ['--stream', str(selected_audio['index'])]
                    if download:
                        cmd.append('--download')
                    else:
                        rerun = [Path(__file__), 'run', root]
                        for selected_alias in aliases or []:
                            rerun += ['--alias', selected_alias]
                        for option, value in (('--words', words_mode), ('--ggml-model', ggml_model),
                                              ('--engine', engine), ('--quality', quality),
                                              ('--retranscribe', retranscribe), ('--stream', stream),
                                              ('--prompt', prompt)):
                            if value is not None:
                                rerun += [option, str(value)]
                        if rebuild:
                            rerun.append('--rebuild')
                        rerun.append('--download')
                        cmd += ['--download-help-command', project.python_command(rerun)]
                    if engine and words_mode == 'auto':
                        cmd += ['--engine', engine]
                    if quality and words_mode == 'auto':
                        cmd += ['--quality', quality]
                    if prompt and words_mode == 'auto':
                        cmd += ['--prompt', prompt]
                    if ggml_model and words_mode == 'auto':
                        cmd += ['--ggml-model', ggml_model]
                    if words_mode.startswith('import:'):
                        cmd += ['--engine', 'import', '--import-file', words_mode[7:]]
                    try:
                        if subprocess.run(cmd).returncode:
                            imported = words_mode.startswith('import:')
                            error = NotTranscribed(f"{alias}: no transcript yet; transcribe.py gave the reason "
                                                   f"{'(the file to import)' if imported else 'and the fix'} above")
                            error.line = ('map waiting: the transcript to import could not be read' if imported
                                          else 'map waiting: transcription is not set up here')
                            raise error
                        with project.file_lock(words_path):
                            after = digest(words_path) if words_path.exists() else None
                            if before != after:
                                raise ValueError(f'{alias}: transcript changed during transcription; retained it')
                            project.write_atomic(words_path, project.read_text(temporary))
                        with project.file_lock(index):
                            data = project.load_json(index)
                            source = next(s for s in data['sources'] if s['alias'] == alias)
                            source.setdefault('mapped', {})['words'] = True
                            project.save_json(index, data)
                    finally:
                        Path(temporary).unlink(missing_ok=True)
                else:
                    message = f'{alias}: existing transcript retained'
                    if words_mode.startswith('import:'):
                        message += f'; to replace it with {words_mode[7:]}, add --retranscribe {alias}'
                    print(message)
            with project.file_lock(index):
                latest = project.load_json(index)
                target = next(s for s in latest['sources'] if s['alias'] == alias)
                target['audio'] = selected_audio
                target['video'] = source.get('video')
                project.save_json(index, latest)
            project.save_json(folder / 'cache.json', key)
            shot_data = project.load_json(folder / 'shots.json', {}).get('shots', [])
            words_path = folder / 'words.json'
            with project.file_lock(words_path):
                transcript = project.load_json(words_path, {})
                word_data = transcript.get('words', [])
                if words_path.is_file():
                    current = dict(source, sha256=actual, audio=selected_audio)
                    identity_state = warn_stale(root, current, transcript)
                    write_transcript(folder, alias, word_data, identity_state)
            silence = project.load_json(folder / 'audio.json', {}).get('silences', [])
            print(f"{alias} {source['role']} {source['duration_s']:.2f}s "
                  f'{len(shot_data)} shots {len(word_data)} words {len(silence)} silences')
        with project.file_lock(root / 'status.json'):
            status = project.read_status(root)
            fields = {'running': [job for job in status.get('running', [])
                                  if not (job.get('job') in owned and job.get('pid') == os.getpid())]}
            if status.get('stage') == 'map' and (status.get('stages') or {}).get('map') != 'waiting':
                latest = project.load_json(index, {'sources': []})
                complete = all(s.get('mapped', {}).get('shots') and s.get('mapped', {}).get('audio')
                               for s in latest['sources'])
                if complete:
                    fields.update(stages={'map': 'done'}, line='map complete')
                else:
                    fields.update(stages={'map': 'now'}, line='more sources need mapping')
            project._update_status(root, fields)
    except BaseException as error:
        with project.file_lock(root / 'status.json'):
            status = project.read_status(root)
            fields = {'running': [job for job in status.get('running', [])
                                  if not (job.get('job') in owned and job.get('pid') == os.getpid())]}
            if isinstance(error, NotTranscribed):
                fields.update(stages={'map': 'waiting'}, line=error.line)
            elif (owned and status.get('stage') == 'map'
                    and (status.get('stages') or {}).get('map') != 'waiting'):
                fields.update(stages={'map': 'now'}, line='map interrupted')
            project._update_status(root, fields)
        raise


def relink(root, alias, path):
    """Relink an alias only when the new file matches its registered content."""
    root = Path(root).resolve()
    index = root / 'map' / 'sources.json'
    with project.file_lock(index):
        data = project.load_json(index, {'sources': []})
        row = next((s for s in data['sources'] if s['alias'] == alias), None)
        if not row:
            raise ValueError(f'unknown alias: {alias}')
        source = Path(path).resolve(strict=True)
        if digest(source) != row['sha256']:
            raise ValueError(f'{alias}: file hash does not match; original source is required')
        try:
            row['path'] = source.relative_to(root).as_posix()
        except ValueError:
            row['path'] = str(source)
        project.save_json(index, data)
    print(f'relinked {alias}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    a = sub.add_parser('add', help='register one or more local sources')
    a.add_argument('project', help='project folder')
    a.add_argument('files', nargs='+', help='local media files to register')
    a.add_argument('--role', required=True, choices=sorted(project.ROLE_PREFIX), help='source role and alias prefix')
    a.add_argument('--copy', action='store_true', help='copy verified media into the project')
    a.add_argument('--stream', type=int, help='absolute audio stream index from ffprobe')
    r = sub.add_parser('run', help='map sources and make transcript drafts')
    r.add_argument('project', help='project folder')
    r.add_argument('--alias', action='append', help='source alias to map; repeat to select more')
    r.add_argument('--words', default='auto', help='auto, skip, or import:FILE for one selected alias')
    r.add_argument('--ggml-model', help='local GGML model for the FFmpeg speech engine')
    r.add_argument('--engine', choices=['faster-whisper', 'ffmpeg'], help='local speech engine')
    r.add_argument('--quality', choices=['fast', 'balanced', 'best'], help='speech model quality')
    r.add_argument('--prompt', help='names and terms to guide the local transcription')
    r.add_argument('--download', action='store_true', help='permit downloading missing transcription weights')
    r.add_argument('--retranscribe', metavar='ALIAS', help='replace the selected alias transcript explicitly')
    r.add_argument('--stream', type=int, help='absolute audio stream index; requires one --alias')
    r.add_argument('--check', action='store_true', help='quick structural completeness check; no rehash or writes')
    r.add_argument('--rebuild', action='store_true', help='rebuild shot, sheet and audio outputs')
    link = sub.add_parser('relink', help='point an alias at an identical moved file')
    link.add_argument('project', help='project folder')
    link.add_argument('alias', help='registered source alias')
    link.add_argument('path', help='new path to the same content')
    fix = sub.add_parser('fix', help='correct a transcript word and record the decision')
    fix.add_argument('project', help='project folder')
    fix.add_argument('word_id', help='word ID from transcript.md or words.json')
    fix.add_argument('text', nargs='?', help='corrected text (optional when changing timing)')
    fix.add_argument('--start', type=float, help='corrected start in source seconds')
    fix.add_argument('--end', type=float, help='corrected end in source seconds')
    fix.add_argument('--by', choices=('agent', 'person'), default='agent', help='who made the correction')
    confirm = sub.add_parser('confirm-words', help='confirm checked words against the current media and sound stream')
    confirm.add_argument('project', help='project folder')
    confirm.add_argument('alias', help='registered source alias')
    confirm.add_argument('--note', required=True, help='what was checked before confirming')
    confirm.add_argument('--stream', type=int, help='checked absolute audio stream index, if it changed')
    confirm.add_argument('--by', choices=('agent', 'person'), default='agent', help='who checked the transcript')
    show = sub.add_parser('words', help='show word timings in a source range and the pause between words: '
                                        'how long nothing is spoken and how far the level falls')
    show.add_argument('project')
    show.add_argument('alias')
    show.add_argument('--from', dest='from_time', help='start in source time (seconds or m:ss)')
    show.add_argument('--to', dest='to_time', help='end in source time (seconds or m:ss)')
    args = parser.parse_args()
    project.safe_output()
    try:
        if args.command == 'add':
            add(args.project, args.files, args.role, args.copy, args.stream)
        elif args.command == 'relink':
            relink(args.project, args.alias, args.path)
        elif args.command == 'fix':
            fix_word(args.project, args.word_id, args.text, args.by, args.start, args.end)
        elif args.command == 'confirm-words':
            confirm_words(args.project, args.alias, args.note, args.by, args.stream)
        elif args.command == 'words':
            show_words(args.project, args.alias, args.from_time, args.to_time)
        elif args.check:
            if args.rebuild:
                raise ValueError('--check and --rebuild cannot be combined')
            return max(check_map(args.project, args.alias), 1 if STALE else 0)
        else:
            if args.words not in ('auto', 'skip') and not args.words.startswith('import:'):
                raise ValueError('--words must be auto, skip or import:FILE')
            run(args.project, args.alias, args.words, args.ggml_model, args.engine, args.quality, args.retranscribe,
                args.stream, args.prompt, args.rebuild, args.download)
        return 1 if STALE else 0
    except Exception as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
