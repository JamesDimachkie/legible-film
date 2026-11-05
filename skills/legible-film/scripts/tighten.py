#!/usr/bin/env python3
"""Tighten a recording into an editable paper cut, or run a one-file edit.

  python cut.py tighten PROJECT ALIAS [--pause 0.35] [--fillers named|LIST]
      [--punch-in 1.1] [--music-bed] [--reel-limit N] [--out film.md] [--force]
  python tighten.py FILE [--out FILE-tight.mp4] [--pause 0.35] [--fillers named|LIST]
      [--punch-in 1.1] [--music-bed] [--reel-limit N] [--silence-only]

The project mode removes only requested fillers (named is a built-in list) that measured quiet bounds on both sides. It
shortens only a contiguous measured quiet stretch, crossfades sound where quiet handles permit, lists picture and audio
removals, flags untranscribed sound and makes a labelled BEFORE/AFTER reel. It preserves 120 ms transcript handles and
requires the sound around fades to remain within 8 dB of the measured room floor. Pauses requiring cuts under 120 ms are
kept. Declare a known continuous music or ambience bed with --music-bed: pauses and fillers stay to preserve the bed. A
steady bed cannot be identified reliably from levels alone. The one-file mode keeps its project beside the result
(OUT-project) so the edit can be revised. Silence-only does not remove fillers. Measured quiet and transcript coverage
do not prove that no speech was missed; listen to the source and every join. Needs numpy, Pillow and FFmpeg. Local
transcription additionally needs faster-whisper and cached model weights; install with
setup.py --install transcription --download. No weights are downloaded by this command. Exit codes: 0 ran, 1 ran with items to inspect, 2 could not run.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

HERE = Path(__file__).resolve().parent
NAMED = ('um', 'umm', 'uhm', 'uh', 'uhh', 'erm', 'errm', 'er', 'err', 'ah', 'ahh', 'hmm', 'hmmm', 'mm', 'mmm')
ROOM_MARGIN_DB = 8.0
WORD_HANDLE = 0.12
EDGE_WINDOW = 0.03
MIN_REMOVAL = 0.12
# The reel holds every cut and only the first few listening prompts (all stay in the report): a reel longer than the
# film it reviews does not get listened to. Each clip's quiet edge is looked for at most this far beyond its words.
REEL_PROMPTS = 5
REEL_SEARCH = 2.0
# Picture either side of a join whose frame-to-frame change stands for the shot's own motion.
JUMP_WINDOW = 0.5


class DecayGuard:
    """Measure 10 ms RMS windows relative to the source's fifth-percentile room level."""

    def __init__(self, samples, rate=16000):
        hop = int(round(rate * .005))
        count = len(samples) // hop
        blocks = samples[:count * hop].reshape(-1, hop).astype(np.float64)
        power = np.mean(blocks * blocks, axis=1)
        window = (power[:-1] + power[1:]) / 2
        self.db = 10 * np.log10(window + 1e-20)
        self.hop = hop / rate
        self.floor = float(np.percentile(self.db[::2], 5)) if len(self.db) else -200.0
        self.limit = self.floor + ROOM_MARGIN_DB

    @classmethod
    def from_source(cls, source_map, alias, cut):
        """Decode the selected stream on the source clock; a failed decode cannot mean quiet."""
        stream = (source_map.sources[alias].get('audio') or {}).get('index')
        transcribe = cut.load_sibling('transcribe')
        samples = transcribe.decode_audio_window(source_map.path(alias), stream, 0, source_map.duration(alias),
                                                 rate=16000)
        if len(samples) < 1600:
            raise ValueError('source sound is too short to measure its room tone')
        return cls(samples)

    def quiet(self, low, high):
        """Every overlapping 10 ms window must be near the floor."""
        if low < 0 or high <= low:
            return False
        first = max(0, int(math.floor(low / self.hop)) - 1)
        last = min(len(self.db), int(math.ceil(high / self.hop)))
        return first < last and bool(np.all(self.db[first:last] <= self.limit))

    def quiet_runs(self, low, high):
        """Continuous measured near-floor intervals inside a source-clock range."""
        first = max(0, int(math.ceil(low / self.hop)))
        last = min(len(self.db), int(math.floor(high / self.hop)))
        mask = self.db[first:last] <= self.limit
        boundaries = np.flatnonzero(np.diff(np.r_[False, mask, False]))
        return [(max(low, (first + a) * self.hop), min(high, (first + b) * self.hop))
                for a, b in zip(boundaries[::2], boundaries[1::2])]


def load_cut():
    """Load the existing compiler, without adding a second implementation of its cut rules."""
    spec = importlib.util.spec_from_file_location('lf_tighten_cut', HERE / 'cut.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def overlap(a, b, c, d):
    """Whether two intervals overlap by more than rounding noise."""
    return min(b, d) - max(a, c) > 0.002


def carry_crossfades(compiler, total):
    """Carry sound over declared tighten cuts only when both source handles are measured quiet."""
    if compiler.envelopes is None:
        return
    pieces = [piece for line in compiler.line_pieces for piece in line]
    for before, after in zip(pieces, pieces[1:]):
        if (before['entry'].get('section') != 'Tighten (declared jump cuts)'
                or after['entry'].get('section') != 'Tighten (declared jump cuts)'
                or before['alias'] != after['alias'] or not before['item'] or not after['item']
                or before['speed'] != 1 or after['speed'] != 1
                or after['in'] - before['out'] < 0.2 or after.get('continuous')):
            continue
        if (before['entry']['mods'].get('tail') or after['entry']['mods'].get('lead')
                or compiler.join_of(after['entry']) or after['carry'].get('dissolve')):
            continue
        join = after['at']
        low = before['last_word'] + 0.03 if before['last_word'] is not None else before['at']
        high = after['first_word'] - 0.03 if after['first_word'] is not None else after['end']
        if high - low < 0.101 or not low <= join <= high:
            continue
        alias = before['alias']
        start, end = float(before['out']), float(after['in'])
        if start < 0.1 or end - 0.1 < start:
            continue
        envelope = compiler.envelopes.get(alias, start - 0.5, end + 0.5)
        if envelope is None or not envelope.reliable:
            continue
        first = envelope.quiet_runs(start, start + 0.1)
        second = envelope.quiet_runs(end - 0.1, end)
        if not any(a <= start + 0.005 and b >= start + 0.095 for a, b in first):
            continue
        if not any(a <= end - 0.095 and b >= end - 0.005 for a, b in second):
            continue
        words = compiler.map.words(alias) or []
        if any(overlap(start, start + 0.1, float(word['start']), float(word['end']))
               or overlap(end - 0.1, end, float(word['start']), float(word['end'])) for word in words):
            continue
        previous = [float(word['end']) for word in words if float(word['end']) <= start + .003]
        following = [float(word['start']) for word in words if float(word['start']) >= end - .003]
        if (not previous or not following or start - .1 < max(previous) + WORD_HANDLE
                or end + .1 > min(following) - WORD_HANDLE):
            continue
        guard = getattr(compiler, 'tighten_guard', None)
        if guard is None:
            try:
                guard = DecayGuard.from_source(compiler.map, alias, load_cut())
            except (OSError, ValueError, subprocess.TimeoutExpired):
                continue
            compiler.tighten_guard = guard
        if not guard.quiet(start - .1, start + .1) or not guard.quiet(end - .1, end + .1):
            continue
        compiler.carry_dissolve(before, after, 0.1, total)
        crossfade = after['carry'].pop('dissolve', None)
        if crossfade:
            after['carry']['tighten_crossfade'] = crossfade
            after['record'].setdefault('tighten_crossfades', []).append(crossfade)


def filler_indices(words, requested, cut):
    """Find whole transcript words matching requested phrases, including multiword phrases."""
    if not requested:
        return set()
    phrases = NAMED if requested.strip().lower() == 'named' else requested.split(',')
    patterns = [cut.normal_tokens(phrase) for phrase in phrases]
    if not patterns or any(not pattern for pattern in patterns):
        raise ValueError('--fillers needs named or a comma-separated list of whole words or phrases')
    tokens = []
    owners = []
    for index, word in enumerate(words):
        for token in cut.normal_tokens(word['text']):
            tokens.append(token)
            owners.append(index)
    selected = set()
    position = 0
    patterns.sort(key=len, reverse=True)
    while position < len(tokens):
        match = next((pattern for pattern in patterns if tokens[position:position + len(pattern)] == pattern), None)
        if not match:
            position += 1
            continue
        end = position + len(match)
        if ((position == 0 or owners[position - 1] != owners[position])
                and (end == len(tokens) or owners[end - 1] != owners[end])):
            selected.update(owners[position:end])
        position = end
    return selected


def unknown_sound(words, envelope, duration):
    """Flag energetic intervals outside word edges; this is a listening prompt, not speech recognition."""
    mask = np.ones(len(envelope.db), dtype=bool)
    for word in words:
        start = max(0.0, float(word['start']) - 0.08)
        end = min(duration, float(word['end']) + 0.08)
        first = max(0, int(start / 0.005))
        last = min(len(mask), int(math.ceil(end / 0.005)))
        mask[first:last] = False
    active = mask & (envelope.db >= envelope.threshold)
    boundaries = np.flatnonzero(np.diff(np.r_[False, active, False]))
    runs = []
    for first, last in zip(boundaries[::2], boundaries[1::2]):
        start = float(envelope.times[first] - 0.0025)
        end = min(duration, float(envelope.times[last - 1] + 0.0025))
        if end - start < 0.08:
            continue
        if runs and start - runs[-1]['end'] <= 0.08:
            runs[-1]['end'] = end
        else:
            runs.append({'start': start, 'end': end, 'kind': 'untranscribed sound',
                         'what': 'energy outside transcript words; listen'})
    return runs


def safe_pause_splits(words, selected, envelope, pause, guard, unknown):
    """Choose removals whose boundaries leave a word handle and a near-floor edge."""
    splits = []
    for index in range(1, len(words)):
        if index - 1 in selected or index in selected:
            continue
        split = protected_gap(words, index, guard, pause, unknown)
        if split and split['end'] - split['start'] >= MIN_REMOVAL - .001:
            splits.append(split)
    return splits


def protected_gap(words, index, guard, pause, unknown=()):
    """Find a near-floor portion with 120 ms word handles and 30 ms of quiet at each edge."""
    low = float(words[index - 1]['end'])
    high = float(words[index]['start'])
    if high <= low:
        return None
    desired = max(0.0, high - low - pause)
    candidates = []
    fragments = guard.quiet_runs(low, high)
    for event in unknown:
        next_fragments = []
        for start, end in fragments:
            if not overlap(start, end, event['start'], event['end']):
                next_fragments.append((start, end))
                continue
            if event['start'] > start:
                next_fragments.append((start, min(end, event['start'] - .005)))
            if event['end'] < end:
                next_fragments.append((max(start, event['end'] + .005), end))
        fragments = next_fragments
    for start, end in fragments:
        left = max(start + EDGE_WINDOW + .015, low + WORD_HANDLE + .015)
        right = min(end - EDGE_WINDOW - .015, high - WORD_HANDLE - .015)
        removal = min(desired, right - left)
        if removal >= MIN_REMOVAL:
            left = max(left, min(right - removal, low + pause / 2))
            candidates.append({'index': index, 'start': round(left, 3), 'end': round(left + removal, 3)})
    return max(candidates, key=lambda item: item['end'] - item['start']) if candidates else None


def partial_pause_splits(words, selected, envelope, pause, actual, splits, unknown, guard):
    """When max_pause made no cut, use an available quiet portion without touching detected sound."""
    existing = {item.get('index') for item in splits}
    result = []
    for index in range(1, len(words)):
        if index in existing or index - 1 in selected or index in selected:
            continue
        low = float(words[index - 1]['end'])
        high = float(words[index]['start'])
        if high - low <= pause + 0.04 or any(overlap(low, high, a, b) for a, b in actual):
            continue
        split = protected_gap(words, index, guard, pause, unknown)
        if not split:
            continue
        if any(overlap(split['start'], split['end'], item['start'], item['end']) for item in unknown):
            continue
        if silent_between(envelope, split['start'], split['end'], []):
            result.append(split)
    return result


def candidate_fillers(words, selected, envelope):
    """Keep a requested filler only when words and measured quiet bound both sides."""
    accepted = set()
    skipped = []
    indices = sorted(selected)
    groups = []
    for index in indices:
        if groups and groups[-1][-1] + 1 == index:
            groups[-1].append(index)
        else:
            groups.append([index])
    for group in groups:
        first, last = group[0], group[-1]
        before = first > 0 and envelope.quiet_runs(float(words[first - 1]['end']), float(words[first]['start']))
        after = last + 1 < len(words) and envelope.quiet_runs(float(words[last]['end']),
                                                               float(words[last + 1]['start']))
        if before and after:
            accepted.update(group)
        else:
            skipped.append(' '.join(str(words[index]['text']).strip() for index in group)
                           + ': no measured quiet on both sides; kept')
    return accepted, skipped


def film_text(root, source_map, alias, words, splits, struck, punch, pause, cut, silence_only=False, use_max=True,
              prefix=0.0, suffix=None):
    """Write ordinary film.md syntax, with split ranges and visible strikethroughs."""
    duration = source_map.duration(alias)
    size = source_map.size(alias) or (1920, 1080)
    fps = source_map.fps(alias) or 30
    title = cut.project.read_status(root).get('title') or root.name
    title = ' '.join(str(title).split())
    header = ['---', f'title: {title}', f'size: {size[0]}x{size[1]}', f'fps: {fps}',
              'captions: none' if silence_only else 'captions: srt, vtt']
    if not silence_only:
        header.append(f'max_pause: {pause:g}' if use_max else 'max_pause: none')
    header += ['---', '', 'Measured quiet only; review the report and listen to every join.', '',
               '## Tighten (declared jump cuts)']
    pairs = [(0.0, duration)]
    if splits:
        pairs = []
        cursor = 0.0
        for split in splits:
            pairs.append((cursor, split['start']))
            cursor = split['end']
        pairs.append((cursor, duration))
    if prefix > 0.001:
        header.append(f'- {alias} 0:00.000-{cut.project.format_time(prefix, 3)} {{sound 0dB}}')
        pairs[0] = (prefix, pairs[0][1])
    if suffix is not None and suffix < duration - 0.001:
        pairs[-1] = (pairs[-1][0], suffix)
    for number, (start, end) in enumerate(pairs):
        zoom = f' {{zoom {punch:g}}}' if punch and number % 2 else ''
        if silence_only:
            mods = f' {{sound 0dB, zoom {punch:g}}}' if punch and number % 2 else ' {sound 0dB}'
            header.append(f'- {alias} {cut.project.format_time(start, 3)}-{cut.project.format_time(end, 3)}{mods}')
            continue
        indices = cut.range_words(words, start, end)
        if not indices:
            raise ValueError('a split produced a line without transcript words')
        text = []
        for index in indices:
            word = str(words[index]['text']).strip()
            text.append('~~' + word + '~~' if index in struck else word)
        header.append(f'> {alias} {cut.project.format_time(start, 3)}-{cut.project.format_time(end, 3)} '
                      + ' '.join(text) + zoom)
    if suffix is not None and suffix < duration - 0.001:
        header.append(f'- {alias} {cut.project.format_time(suffix, 3)}-{cut.project.format_time(duration, 3)} '
                      '{sound 0dB}')
    return '\n'.join(header) + '\n'


def compile_text(text, root, source_map, cut, guard=None):
    """Compile before publishing so the report names the actual cut points."""
    problems = cut.Problems()
    settings, entries = cut.parse_film(text, problems, set(source_map.sources), root)
    envelopes = cut.Envelopes(source_map, cut.find_tool('ffmpeg'))
    compiler = cut.Compiler(settings, entries, source_map, envelopes, problems)
    compiler.tighten_guard = guard
    plan = compiler.run()
    errors = [item['message'] for item in problems.items if item['severity'] == 'error']
    if errors:
        raise ValueError('generated paper edit did not compile: ' + '; '.join(errors[:4]))
    intervals = sorted((float(item['in']), float(item['out'])) for item in plan['audio']
                       if item.get('src') in source_map.sources)
    return plan, intervals


def removed_intervals(intervals, duration):
    """The complement of actual source audio intervals, in source time."""
    result = []
    cursor = 0.0
    for start, end in intervals:
        if start > cursor + 0.002:
            result.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.002:
        result.append((cursor, duration))
    return result


def picture_removals(plan, alias):
    """Picture cuts on the source clock, before any sound carries across their joins."""
    pieces = [piece for line in plan['pieces'] for piece in line]
    result = []
    for before, after in zip(pieces, pieces[1:]):
        if before['alias'] == alias and after['alias'] == alias and after['in'] > before['out'] + 0.002:
            result.append({'start': float(before['out']), 'end': float(after['in']), 'edit_at': float(after['at']),
                           'crossfade': after['carry'].get('tighten_crossfade')})
    return result


def silent_between(envelope, low, high, exclusions):
    """Check that material outside expressly removed word spans is measured quiet."""
    first = max(0, int(low / 0.005))
    last = min(len(envelope.db), int(math.ceil(high / 0.005)))
    if first >= last:
        return True
    times = envelope.times[first:last]
    loud = envelope.db[first:last] >= envelope.threshold
    for start, end in exclusions:
        loud &= ~((times >= start - 0.08) & (times <= end + 0.08))
    return not bool(loud.any())


def audio_pair(plan, alias, low, high):
    """Find the two compiler audio items on either side of a source omission."""
    items = [item for item in plan['audio'] if item.get('src') == alias]
    left = [item for item in items if abs(float(item['out']) - low) < .003]
    right = [item for item in items if abs(float(item['in']) - high) < .003]
    pairs = [(a, b) for a in left for b in right if float(b['at']) >= float(a['at'])]
    if not pairs:
        return None
    return min(pairs, key=lambda pair: abs(float(pair[0]['at']) + float(pair[0]['out'])
                                           - float(pair[0]['in']) - float(pair[1]['at'])))


def audio_fade(item, side):
    """Match assemble.py's default and proportional shortening for this audio item."""
    default = float(item.get('fade_ms', 15))
    fade_in = float(item.get('fade_in_ms', default)) / 1000
    fade_out = float(item.get('fade_out_ms', default)) / 1000
    duration = float(item['out']) - float(item['in'])
    scale = min(1.0, duration / (fade_in + fade_out)) if fade_in + fade_out else 1.0
    return (fade_in if side == 'in' else fade_out) * scale


def safe_join(plan, alias, low, high, words, selected, guard):
    """Protect the kept audio before and throughout both actual compiler fades."""
    if high - low < MIN_REMOVAL - .001:
        return False
    pair = audio_pair(plan, alias, low, high)
    if not pair:
        return False
    left, right = pair
    fade_start = low - audio_fade(left, 'out')
    fade_end = high + audio_fade(right, 'in')
    previous = [float(word['end']) for index, word in enumerate(words)
                if index not in selected and float(word['end']) <= low + .003]
    following = [float(word['start']) for index, word in enumerate(words)
                 if index not in selected and float(word['start']) >= high - .003]
    if previous and low < max(previous) + WORD_HANDLE - .002:
        return False
    if following and high > min(following) - WORD_HANDLE + .002:
        return False
    return guard.quiet(fade_start - EDGE_WINDOW, low) and guard.quiet(high, fade_end + EDGE_WINDOW)


def reel_context(words, item, duration, guard):
    """Find near-floor edges outside words, at least one second from the event when possible."""
    left = max(0.0, float(item['start']) - 1.0)
    right = min(duration, float(item['end']) + 1.0)
    before = [float(word['start']) for word in words if float(word['start']) <= left]
    after = [float(word['end']) for word in words if float(word['end']) >= right]
    left = max(before) if before else (left if not words else 0.0)
    right = min(after) if after else (right if not words else duration)
    # Without a quiet stretch near the words, the clip starts and ends at the words themselves (its edges fade).
    start, end = left, right
    for low, high in reversed(guard.quiet_runs(max(0.0, left - REEL_SEARCH), left)):
        point = high - .04
        if point >= low and guard.quiet(point, point + .03) and not any(
                overlap(point, point + .03, float(word['start']), float(word['end'])) for word in words):
            start = point
            break
    for low, high in guard.quiet_runs(right, min(duration, right + REEL_SEARCH)):
        point = low + .04
        if point <= high and guard.quiet(point - .03, point) and not any(
                overlap(point - .03, point, float(word['start']), float(word['end'])) for word in words):
            end = point
            break
    return start, end


def comparison_audio(source_map, alias, item, plan, start, end, folder, cut):
    """Use assemble's audio renderer and the actual compiler fade parameters for a single join."""
    assemble = cut.load_sibling('assemble')
    ffmpeg, ffprobe = cut.find_tool('ffmpeg'), cut.find_tool('ffprobe')
    stream = (source_map.sources[alias].get('audio') or {}).get('index')
    source = {'file': str(source_map.path(alias)), 'audio_stream': stream}
    if item['kind'] == 'untranscribed sound':
        audio = [{'src': alias, 'track': 'comparison', 'in': start, 'out': end, 'at': 0,
                  'fade_in_ms': 0, 'fade_out_ms': 0}]
        total = end - start
    else:
        pair = audio_pair(plan, alias, item['audio_start'], item['audio_end'])
        if not pair:
            raise ValueError('review reel cannot identify the compiled audio join')
        left, right = (dict(row) for row in pair)
        overlap_s = float(left['at']) + float(left['out']) - float(left['in']) - float(right['at'])
        left_fade = audio_fade(left, 'out') * 1000
        right_fade = audio_fade(right, 'in') * 1000
        left.update({'track': 'comparison', 'in': start, 'at': 0, 'fade_in_ms': 0, 'fade_out_ms': left_fade})
        right.update({'track': 'comparison', 'out': end, 'fade_out_ms': 0, 'fade_in_ms': right_fade})
        right['at'] = float(left['out']) - start - overlap_s
        if right['at'] < 0:
            raise ValueError('review context does not cover the compiled audio overlap')
        audio = [left, right]
        total = max(float(left['out']) - start, right['at'] + end - float(right['in']))
    edit = {'sources': {alias: source}, 'audio': audio}
    clips = [{'src': alias, 'speed': 1.0, 'start': 0.0, 'stop': source_map.duration(alias)}]
    notes = []
    assemble.render_audio(ffmpeg, ffprobe, edit, Path('.'), clips, total, str(folder), folder, notes)
    return folder / 'comparison.wav', total


def reel_clip(source, label, audio, start, end, item, kind, total, out, ffmpeg):
    """Render source picture with the comparison sound and 30 ms fades at both clip edges."""
    frames = max(1, int(math.ceil(total * 24 - 1e-9)))
    padded = frames / 24
    if kind == 'AFTER':
        left = float(item['start']) - start
        right = float(item['end']) - start
        picture = (f'[0:v:0]split=2[v0][v1];[v0]trim=start=0:end={left:.6f},setpts=PTS-STARTPTS[a];'
                   f'[v1]trim=start={right:.6f}:end={end - start:.6f},setpts=PTS-STARTPTS[b];'
                   '[a][b]concat=n=2:v=1:a=0[v];')
    else:
        picture = f'[0:v:0]trim=start=0:end={end - start:.6f},setpts=PTS-STARTPTS[v];'
    filters = (picture + '[v]scale=640:360:force_original_aspect_ratio=decrease,'
               f'pad=640:360:(ow-iw)/2:(oh-ih)/2,setsar=1,tpad=stop_mode=clone:stop_duration=0.1,'
               f'fps=24,trim=duration={padded:.9f}[scaled];'
               '[scaled][1:v]overlay=0:0:shortest=0[out]')
    fade_out = max(0.0, total - .03)
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-ss', f'{start:.6f}', '-i', str(source),
               '-i', str(label), '-i', str(audio), '-filter_complex', filters, '-map', '[out]', '-map', '2:a:0',
               '-af', f'afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out:.6f}:d=0.03,'
                      f'apad=whole_dur={padded:.9f},atrim=duration={padded:.9f}',
               '-t', f'{padded:.9f}', '-frames:v', str(frames), '-r', '24', '-c:v', 'libx264',
               '-preset', 'ultrafast', '-pix_fmt',
               'yuv420p', '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', str(out)]
    result = subprocess.run(command, capture_output=True, timeout=600)
    if result.returncode:
        raise ValueError('review reel failed: ' + result.stderr.decode(errors='replace')[-500:])


def reel_duration(path, ffprobe):
    """Measure a reel clip's encoded duration for the listening index."""
    result = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
                            capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise ValueError('could not measure the review reel: ' + result.stderr[-500:])
    return float(json.loads(result.stdout)['format']['duration'])


def labelled_reel(source_map, alias, items, out, cut, words, plan, limit, guard):
    """Render labelled BEFORE/AFTER pairs and LISTEN prompts, with faded edges and silent gaps."""
    if not items:
        return {'made': False, 'events': 0, 'total_events': 0, 'duration_s': 0.0}
    ffmpeg = cut.find_tool('ffmpeg')
    ffprobe = cut.find_tool('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('FFmpeg and ffprobe are required to make the review reel')
    source = source_map.path(alias)
    duration = source_map.duration(alias)
    cuts = [item for item in items if item['kind'] != 'untranscribed sound']
    prompts = [item for item in items if item['kind'] == 'untranscribed sound']
    chosen = cuts + prompts[:REEL_PROMPTS] if limit is None else (cuts + prompts)[:limit]
    chosen = sorted(chosen, key=lambda item: (item['start'], item['end']))
    guard = guard or DecayGuard.from_source(source_map, alias, cut)
    boundary_events = 0
    with tempfile.TemporaryDirectory(prefix='lf-tighten-reel-') as folder:
        folder = Path(folder)
        clips = []
        index = []
        position = 0.0
        try:
            font = ImageFont.truetype('arial.ttf', 20)
        except OSError:
            font = ImageFont.load_default()
        silence = folder / 'silence.mkv'
        command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                   'color=c=black:s=640x360:r=24:d=0.25', '-f', 'lavfi', '-i',
                   'anullsrc=r=48000:cl=stereo', '-t', '0.25', '-c:v', 'libx264', '-preset', 'ultrafast',
                   '-pix_fmt', 'yuv420p', '-c:a', 'pcm_f32le', '-ar', '48000', '-ac', '2', str(silence)]
        result = subprocess.run(command, capture_output=True, timeout=600)
        if result.returncode:
            raise ValueError('review reel silence failed: ' + result.stderr.decode(errors='replace')[-500:])
        silence_duration = reel_duration(silence, ffprobe)
        for number, item in enumerate(chosen):
            start_at, end_at = reel_context(words, item, duration, guard)
            if start_at == 0 or end_at == duration:
                boundary_events += 1
            kinds = ['LISTEN'] if item['kind'] == 'untranscribed sound' else ['BEFORE', 'AFTER']
            for kind in kinds:
                label = Image.new('RGBA', (640, 66), (0, 0, 0, 220))
                draw = ImageDraw.Draw(label)
                a = cut.project.format_time(item['start'], 2)
                b = cut.project.format_time(item['end'], 2)
                draw.text((10, 6), f'{kind}  {number + 1}/{len(chosen)}  {a}-{b}', font=font, fill='white')
                draw.text((10, 35), str(item['what'])[:65], font=font, fill='white')
                label_path = folder / f'label-{number:05d}-{kind}.png'
                label.save(label_path)
                part = folder / f'audio-{number:05d}-{kind}'
                part.mkdir()
                audio_item = item if kind == 'AFTER' else {'kind': 'untranscribed sound'}
                audio, total = comparison_audio(source_map, alias, audio_item, plan, start_at, end_at, part, cut)
                clip = folder / f'clip-{number:05d}-{kind}.mkv'
                reel_clip(source, label_path, audio, start_at, end_at, item, kind, total, clip, ffmpeg)
                if clips:
                    clips.append(silence)
                    position += silence_duration
                clips.append(clip)
                clip_duration = reel_duration(clip, ffprobe)
                index.append({'kind': kind, 'event_start': item['start'], 'event_end': item['end'],
                              'source_start': start_at, 'source_end': end_at, 'reel_start': round(position, 6),
                              'duration_s': clip_duration,
                              'picture_join': float(item['start']) - start_at if kind == 'AFTER' else None})
                position += clip_duration
        listing = folder / 'clips.txt'
        listing.write_text(''.join("file '" + clip.as_posix().replace("'", "'\\''") + "'\n" for clip in clips),
                           encoding='utf-8')
        result = subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
                                 '-i', str(listing), '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
                                 '-af', 'aresample=async=1000:min_hard_comp=0.001:first_pts=0',
                                 '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                                 '-movflags', '+faststart', str(out)],
                                capture_output=True, timeout=600)
        if result.returncode:
            raise ValueError('review reel concat failed: ' + result.stderr.decode(errors='replace')[-500:])
    seconds = reel_duration(out, ffprobe)
    played = sum(1 for item in chosen if item['kind'] == 'untranscribed sound')
    return {'made': True, 'events': len(chosen), 'total_events': len(items), 'duration_s': seconds,
            'cuts': len(chosen) - played, 'total_cuts': len(cuts), 'prompts': played, 'total_prompts': len(prompts),
            'source_boundary_events': boundary_events, 'clips': index}


def reel_coverage(reel_info):
    """What the reel plays, cuts and listening prompts counted apart, so a reel never implies it holds every prompt."""
    text = (f"Reel plays {reel_info['cuts']} of {reel_info['total_cuts']} cuts and {reel_info['prompts']} of "
            f"{reel_info['total_prompts']} listening prompts")
    if reel_info['events'] < reel_info['total_events']:
        text += (f" (the report lists every one; --reel-limit {reel_info['total_events']} plays them all)")
    return text + f"; {reel_info['duration_s']:.1f} s."


def grey_frames(ffmpeg, path, start, length):
    """Small grey frames of [start, start + length) of a source at its own rate, or None when it cannot be read."""
    command = [ffmpeg, '-v', 'error', '-ss', f'{max(0.0, start):.6f}', '-i', str(path), '-t', f'{length:.6f}',
               '-map', '0:v:0', '-vf', 'scale=64:36,format=gray', '-f', 'rawvideo', '-']
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        return None
    data = np.frombuffer(result.stdout, dtype=np.uint8)
    return data[:len(data) // 2304 * 2304].reshape(-1, 36, 64).astype(np.float32)


def picture_jumps(source_map, alias, removals, cut):
    """Score each removal's join by how much the picture changes across it, as a multiple of the shot's own
    frame-to-frame change either side. A hand or head that moved during a removed pause jumps at the join (an editor
    found two such joins among ten on a raw interview). This ranks joins for review; it does not judge continuity."""
    ffmpeg = cut.find_tool('ffmpeg')
    if not ffmpeg or not source_map.has_video(alias):
        return
    path = source_map.path(alias)
    for item in removals:
        lead = min(JUMP_WINDOW, item['start'])
        before = grey_frames(ffmpeg, path, item['start'] - lead, lead) if lead > 0 else []
        after = grey_frames(ffmpeg, path, item['end'], JUMP_WINDOW)
        if before is None or after is None:
            item['picture_jump_unassessed'] = 'the picture either side could not be decoded'
            continue
        if len(before) < 2 or len(after) < 2:
            item['picture_jump_unassessed'] = 'under two frames of picture on one side (a source edge)'
            continue
        join = float(np.mean(np.abs(after[0] - before[-1])))
        steps = [float(np.mean(np.abs(second - first))) for frames in (before, after)
                 for first, second in zip(frames, frames[1:])]
        item['picture_jump'] = round(join / max(float(np.median(steps)), 0.5), 1)


def reel_advice(reel_info):
    """Offer only a count limit that can shorten the current reel."""
    if reel_info['events'] == 1:
        if reel_info['duration_s'] > 60:
            return 'One event is over 60 s; a count limit cannot shorten its context. Review the source directly.'
        return ''
    return 'Use --reel-limit N for a shorter reel (cuts first).'


def report_text(alias, pause, removals, unknown, skipped, words, reel, reel_info, silence_only, sound_assessed,
                music_bed, cut):
    """A scan-friendly account of every actual removal and uncertain sound."""
    sound_summary = f'{len(unknown)} prompts' if sound_assessed else 'not assessed'
    lines = ['# Tighten report', '']
    if music_bed:
        lines += ['Music or ambience under the speech: pauses were left; cutting would make the bed jump.', '']
    else:
        lines += ['A steady music or ambience bed can be mistaken for room tone and cut; inspect the source.', '']
    lines += [f'Source: {alias}. Target pause: {pause:g} s.',
             f'Actual removals: {len(removals)}. Untranscribed sound: {sound_summary}.',
             'Times below are picture removals on the source clock; the reel pairs BEFORE and AFTER for each cut.',
             'Audio crossfades may carry quiet sound across the cut; the audio omission is listed separately.',
             'The transcript is a draft. Quiet is not proof of silence; music, breath and noise can trigger prompts,',
             'and quiet speech can be missed. Listen to the source, the reel, every tight cut and every jump cut.',
             'A removal can create a same-shot jump. A cutaway at each edit time can hide it;',
             'inspect rhythm and framing.',
             'To restore a filler, remove its ~~ marks. To restore a split-range pause, merge its lines and ranges;',
             'also change max_pause if it would shorten that restored pause again.',
             'For an in-line max_pause cut, split the line at a continuous source boundary in that pause, or set',
             'max_pause: none to restore all in-line pauses. Recheck the edit after changes.',
             f'Reel: {reel if reel else "none (no removals or prompts)"}.', '', '## Removed']
    if reel_info['made']:
        lines.insert(-2, reel_coverage(reel_info))
        advice = reel_advice(reel_info)
        if advice:
            lines.insert(-2, advice)
        if silence_only:
            lines.insert(-2, 'No transcript: reel context cannot be placed at verified word boundaries.')
        if reel_info['source_boundary_events']:
            lines.insert(-2, f'{reel_info["source_boundary_events"]} reel events reach a source edge; '
                             'a complete surrounding word may be unavailable.')
    for item in removals:
        jump = (f"; picture changes {item['picture_jump']:g}x the shot's own frame to frame"
                if 'picture_jump' in item else f"; picture change not assessed: {item['picture_jump_unassessed']}"
                if 'picture_jump_unassessed' in item else '')
        lines.append(f'- {cut.project.format_time(item["start"], 3)}-{cut.project.format_time(item["end"], 3)}: '
                     f'{item["what"]}; {item["reason"]}; {item["end"] - item["start"]:.3f} s{jump}; '
                     f'cutaway over edit {cut.project.format_time(item["edit_at"], 3)} can hide the jump')
        lines.append(f'  Audio omitted {cut.project.format_time(item["audio_start"], 3)}-'
                     f'{cut.project.format_time(item["audio_end"], 3)}; {item["sound"]}.')
    if not removals:
        lines.append('- None.')
    ranked = sorted((item for item in removals if 'picture_jump' in item), key=lambda item: -item['picture_jump'])
    if len(ranked) > 1:
        lines.append('- Joins by picture change, largest first (a hand or head that moved during the pause jumps '
                     'there; check these in the reel first): '
                     + ', '.join(f'edit {cut.project.format_time(item["edit_at"], 3)} {item["picture_jump"]:g}x'
                                 for item in ranked[:3]) + '.')
    lines += ['', '## Untranscribed sound: listen']
    if music_bed and unknown:
        lines.append(f'- {len(unknown)} prompts are timed in the JSON list; the reel plays the first '
                     f'{min(len(unknown), REEL_PROMPTS)} unless --reel-limit says otherwise; some may be words.')
    else:
        for item in unknown:
            lines.append(f'- {cut.project.format_time(item["start"], 3)}-{cut.project.format_time(item["end"], 3)}: '
                         + item['what'])
    if silence_only:
        lines.append('- Not assessed: no transcript was supplied.')
    elif not sound_assessed:
        lines.append('- Not assessed: source sound levels could not be measured reliably.')
    elif not unknown:
        lines.append('- None detected; this does not rule out omitted or quiet speech.')
    lines += ['', '## Kept or review candidates']
    lines += ['- ' + item for item in skipped if not music_bed or not item.startswith('Pause at ')]
    if music_bed and not silence_only:
        lines.append('- Pauses beyond the target tolerance are timed in JSON; any requested fillers were kept.')
    for first, second in zip(words, words[1:]):
        one, two = cut.normal_tokens(first['text']), cut.normal_tokens(second['text'])
        if one and one == two:
            lines.append(f'- {cut.project.format_time(float(first["start"]), 3)}: repeated '
                         f'{str(first["text"]).strip()} {str(second["text"]).strip()}; kept, listen for false start')
        elif str(first['text']).rstrip().endswith('-'):
            lines.append(f'- {cut.project.format_time(float(first["start"]), 3)}: possible false start; kept')
    if silence_only:
        lines.append('- No transcript: filler and word coverage were not assessed; silence-only is approximate.')
    lines.append('')
    return '\n'.join(lines)


def backup_name(path):
    """Choose an unused backup name so a later --force does not destroy an earlier backup."""
    candidate = path.with_name(path.name + '.bak')
    number = 2
    while candidate.exists():
        candidate = path.with_name(path.name + f'.bak.{number}')
        number += 1
    return candidate


def tighten_project(args, cut):
    """Generate and check a paper edit, removal report and listening reel."""
    root = cut.load_project(args.project)
    source_map = cut.SourceMap(root)
    alias = args.alias
    if alias not in source_map.sources:
        raise ValueError(f'unknown source alias {alias}')
    if not source_map.has_audio(alias) or not source_map.has_video(alias):
        raise ValueError('tighten needs a source with both picture and sound')
    source_map.verify_media = True
    duration = source_map.duration(alias)
    if not duration or duration <= 0 or not math.isfinite(duration):
        raise ValueError('source duration is missing or invalid')
    if not 0.1 <= args.pause <= 5:
        raise ValueError('--pause must be between 0.1 and 5 seconds')
    if args.punch_in is not None and not 1 <= args.punch_in <= 2:
        raise ValueError('--punch-in must be between 1 and 2')
    if args.reel_limit is not None and args.reel_limit < 1:
        raise ValueError('--reel-limit must be a positive event count')
    if args.silence_only and args.fillers:
        raise ValueError('--fillers needs a transcript; omit it in --silence-only')
    words = [] if args.silence_only else source_map.words(alias)
    if not args.silence_only and not words:
        raise ValueError('no transcript; run map.py run, or use --silence-only to keep only measured nonquiet audio')
    stale = source_map.stale_transcript(alias) if words else source_map.media_change(alias, source_map.sources[alias])
    if stale:
        raise ValueError(f'{alias}: {stale}')
    for index, word in enumerate(words):
        text = str(word['text'])
        start, end = float(word['start']), float(word['end'])
        if ('~~' in text or '{' in text or '}' in text or '\n' in text or '\r' in text
                or not 0 <= start <= end <= duration or (index and start < float(words[index - 1]['start']))):
            raise ValueError(f'invalid or unsafe transcript word at index {index + 1}; correct the map first')
    output = Path(args.out) if args.out else root / 'film.md'
    output = output.resolve()
    if output.suffix.lower() != '.md':
        raise ValueError('the paper edit output must be a Markdown .md file')
    report = output.with_name(output.stem + '.tighten-report.md')
    data_path = output.with_name(output.stem + '.tighten.json')
    reel = output.with_name(output.stem + '.tighten-reel.mp4')
    outputs = [output, report, data_path, reel]
    inputs = [source_map.path(alias), root / 'map' / 'sources.json', root / 'map' / alias / 'words.json',
              root / 'map' / alias / 'audio.json', root / 'map' / alias / 'transcript.md']
    cut.project.refuse_overwriting_inputs(outputs, inputs)
    exists = [path for path in outputs if path.exists()]
    if exists and not args.force:
        raise ValueError(f'{exists[0]} exists; pass --force to replace the edit and report')
    if not output.parent.is_dir():
        raise ValueError(f'output folder does not exist: {output.parent}')
    envelope = cut.Envelopes(source_map, cut.find_tool('ffmpeg')).get(alias, 0, duration)
    if (envelope is None or not envelope.reliable) and not args.music_bed:
        raise ValueError('source sound could not be reliably measured; no automatic cuts were made')
    guard = None if args.music_bed else DecayGuard.from_source(source_map, alias, cut)
    sound_assessed = not args.silence_only and envelope is not None and envelope.reliable
    unknown = unknown_sound(words, envelope, duration) if sound_assessed else []
    requested = filler_indices(words, args.fillers, cut) if words else set()
    struck, skipped = candidate_fillers(words, requested, envelope) if words and not args.music_bed else (set(), [])
    if args.music_bed:
        splits = []
        use_max = False
    elif args.silence_only:
        splits = []
        for low, high in envelope.quiet_runs(0, duration):
            removal = high - low - args.pause
            if removal > 0.04 and low > 0 and high < duration:
                splits.append({'start': round(low + args.pause / 2, 3),
                               'end': round(high - args.pause / 2, 3)})
        use_max = False
    else:
        # max_pause is the ordinary path. Alternating framing requires separate lines at pause jumps.
        splits = safe_pause_splits(words, struck, envelope, args.pause, guard, unknown) if args.punch_in else []
        use_max = True
    # Rebuild whenever the existing compiler would cut energetic, untranscribed audio or select different words.
    for _ in range(len(words) + len(splits) + 3):
        text = film_text(root, source_map, alias, words, splits, struck, args.punch_in, args.pause, cut,
                         args.silence_only, use_max)
        plan, intervals = compile_text(text, root, source_map, cut, guard)
        prefix = intervals[0][0] if intervals else 0
        suffix = intervals[-1][1] if intervals else duration
        if not args.silence_only and (prefix > 0.002 or suffix < duration - 0.002):
            text = film_text(root, source_map, alias, words, splits, struck, args.punch_in, args.pause, cut,
                             use_max=use_max, prefix=prefix, suffix=suffix)
            plan, intervals = compile_text(text, root, source_map, cut, guard)
        actual = removed_intervals(intervals, duration)
        if args.music_bed and actual:
            raise ValueError('the compiler could not preserve the full declared bed; no edit was written')
        expected = {words[i].get('id') for i in range(len(words)) if i not in struck}
        got = {word.get('id') for word in plan['words']}
        if words and expected != got:
            if struck:
                skipped.append('Some requested fillers could not be matched unambiguously; all were kept.')
                struck = set()
                splits = (safe_pause_splits(words, struck, envelope, args.pause, guard, unknown)
                          if args.punch_in or not use_max else [])
                continue
            raise ValueError('the compiler did not preserve every transcript word; no edit was written')
        unsafe = []
        for low, high in actual:
            removed_words = [word for index, word in enumerate(words) if index in struck
                             and overlap(low, high, float(word['start']), float(word['end']))]
            exclusions = [(float(word['start']), float(word['end'])) for word in removed_words]
            hits = any(overlap(low, high, event['start'], event['end']) for event in unknown)
            if (hits or not silent_between(envelope, low, high, exclusions)
                    or not safe_join(plan, alias, low, high, words, struck, guard)):
                unsafe.append((low, high))
        if not unsafe:
            for index, word in enumerate(words):
                if index in struck:
                    continue
                if not any(start <= float(word['start']) + 0.003 and end >= float(word['end']) - 0.003
                           for start, end in intervals):
                    raise ValueError(f'the compiler would clip kept word {word.get("id")}; no edit was written')
            if words and use_max:
                extra = partial_pause_splits(words, struck, envelope, args.pause, actual, splits, unknown, guard)
                if extra:
                    splits.extend(extra)
                    splits.sort(key=lambda row: row['start'])
                    continue
            break
        changed = False
        for low, high in unsafe:
            old = len(struck)
            struck = {index for index in struck if not overlap(low, high, float(words[index]['start']),
                                                                float(words[index]['end']))}
            if len(struck) < old:
                skipped.append(f'Filler near {cut.project.format_time(low, 3)} kept: nearby sound is not quiet.')
                changed = True
            if words and use_max:
                use_max = False
                splits = safe_pause_splits(words, struck, envelope, args.pause, guard, unknown)
                skipped.append('max_pause could not preserve the word tails or near-floor edges; '
                               'using verified quiet range splits.')
                changed = True
                break
            else:
                retained = [split for split in splits if not overlap(low, high, split['start'], split['end'])]
                if len(retained) < len(splits):
                    splits = retained
                    changed = True
        if not changed:
            if use_max:
                use_max = False
                splits = safe_pause_splits(words, struck, envelope, args.pause, guard, unknown)
                skipped.append('max_pause could not preserve all detected sound; using verified quiet range splits.')
                continue
            raise ValueError('the compiler would remove sound outside the requested words; no edit was written')
    else:
        raise ValueError('could not find a safe set of automatic removals')
    picture_cuts = picture_removals(plan, alias)
    for before, after in zip(words, words[1:]):
        low, high = float(before['end']), float(after['start'])
        if high - low <= args.pause + 0.04:
            continue
        removed_duration = sum(max(0.0, min(high, item['end']) - max(low, item['start']))
                               for item in picture_cuts)
        remaining = high - low - removed_duration
        if remaining > args.pause + 0.04:
            skipped.append(f'Pause at {cut.project.format_time(low, 3)}: {remaining:.2f} s remains; '
                           f'the {args.pause:g} s target was not safely reached.')
    removals = []
    audio_items = sorted((item for item in plan['audio'] if item.get('src') == alias), key=lambda item: item['at'])
    for low, high in actual:
        removed = [str(word['text']).strip() for index, word in enumerate(words) if index in struck
                   and overlap(low, high, float(word['start']), float(word['end']))]
        matching = [item for item in picture_cuts if item['start'] <= low + 0.003 and item['end'] >= high - 0.003]
        next_items = [item for item in audio_items if abs(float(item['in']) - high) < 0.003]
        picture = matching[0] if matching else None
        edit_at = picture['edit_at'] if picture else (float(next_items[0]['at']) if next_items else 0.0)
        crossfade = picture and picture.get('crossfade')
        crossfade_s = round(crossfade[1] - crossfade[0], 4) if crossfade else None
        sound = f'{crossfade_s:g} s audio crossfade' if crossfade else 'short edge fades; no audio crossfade'
        removals.append({'start': picture['start'] if picture else low, 'end': picture['end'] if picture else high,
                         'audio_start': low, 'audio_end': high, 'sound': sound, 'crossfade_s': crossfade_s,
                         'edit_at': edit_at, 'kind': 'filler' if removed else 'pause',
                         'what': ' '.join(removed) if removed else 'measured quiet',
                         'reason': 'requested filler' if removed else 'shorten pause'})
    picture_jumps(source_map, alias, removals, cut)
    events = sorted(removals + unknown, key=lambda row: (row['start'], row['end']))
    with tempfile.TemporaryDirectory(prefix='lf-tighten-output-') as folder:
        temporary_reel = Path(folder) / 'reel.mp4'
        reel_info = labelled_reel(source_map, alias, events, temporary_reel, cut, words, plan, args.reel_limit, guard)
        made_reel = reel_info['made']
        if output.exists():
            shutil.copy2(output, backup_name(output))
        if made_reel:
            shutil.copy2(temporary_reel, reel)
        elif reel.exists():
            reel.rename(backup_name(reel))
        cut.project.write_atomic(report, report_text(alias, args.pause, removals, unknown, skipped, words,
                                                       reel if made_reel else None, reel_info, args.silence_only,
                                                       sound_assessed, args.music_bed, cut))
        cut.project.save_json(data_path, {'version': 1, 'source': alias, 'pause_target_s': args.pause,
                                         'removals': removals, 'untranscribed_sound': unknown,
                                         'untranscribed_sound_assessed': sound_assessed,
                                         'skipped': skipped, 'reel': str(reel) if made_reel else None,
                                         'reel_info': reel_info,
                                         'transcript_word_count': len(words), 'selected_filler_count': len(struck),
                                         'music_bed_declared': args.music_bed,
                                         'mode': 'silence-only' if args.silence_only else 'transcript'})
        cut.project.write_atomic(output, text)
    sound_summary = ('untranscribed sound not assessed' if not sound_assessed
                     else f'{len(unknown)} untranscribed sound prompts')
    print(f'wrote {output}; {len(removals)} removals, {sound_summary}')
    print(f'report: {report}')
    if made_reel:
        print(f'reel: {reel}')
        print(reel_coverage(reel_info))
        if reel_info['duration_s'] > 60:
            print(f'The reel is {reel_info["duration_s"]:.1f} s. {reel_advice(reel_info)}')
    if output != root / 'film.md':
        print('To render this edit, place it at the project film.md after reviewing it.')
    return 1 if unknown or skipped or args.music_bed else 0


def run_tool(script, *arguments, accepted=(0,)):
    """Run a sibling command and preserve its diagnostic rather than silently falling back."""
    result = subprocess.run([sys.executable, '-I', str(HERE / script), *map(str, arguments)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    if result.returncode not in accepted:
        raise ValueError(f'{script} exited {result.returncode}; its output above has the reason')
    return result.returncode


def quick_file(args):
    """Make a project beside the result, then render and check one file beside its original."""
    source = Path(args.file).resolve()
    if not source.is_file():
        raise ValueError(f'no input file: {source}')
    out = Path(args.out).resolve() if args.out else source.with_name(source.stem + '-tight.mp4')
    if out.suffix.lower() != '.mp4':
        raise ValueError('the one-file output must be an .mp4')
    if not out.parent.is_dir():
        raise ValueError(f'output folder does not exist: {out.parent}')
    report = out.with_name(out.stem + '.tighten-report.md')
    data = out.with_name(out.stem + '.tighten.json')
    reel = out.with_name(out.stem + '.tighten-reel.mp4')
    checks = out.with_name(out.stem + '.tighten-checks.json')
    targets = [out, report, data, reel, checks]
    if any(path == source for path in targets):
        raise ValueError('the output would overwrite the original')
    existing = [path for path in targets if path.exists()]
    if existing:
        raise ValueError(f'{existing[0]} exists; choose a new output name')
    if not args.silence_only and importlib.util.find_spec('faster_whisper') is None:
        raise ValueError('faster-whisper is not installed. Ask before installing: run setup.py --install '
                         'transcription, or choose --silence-only without a transcript.')
    if args.silence_only and args.fillers:
        raise ValueError('--silence-only cannot remove named fillers')
    # The project stays beside the result, so the cut can be revised later (a temporary folder would not survive).
    folder = out.with_name(out.stem + '-project')
    number = 2
    while folder.exists():
        folder = out.with_name(f'{out.stem}-project-{number}')
        number += 1
    print(f'Revision project: {folder}', flush=True)
    run_tool('project.py', 'init', folder, '--title', source.stem)
    run_tool('map.py', 'add', folder, source, '--role', 'interview')
    mode = 'skip' if args.silence_only else 'auto'
    # Offline is explicit: an uncached model must stop, never silently download.
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    run_tool('map.py', 'run', folder, '--alias', 'int_01', '--words', mode)
    command = ['tighten', folder, 'int_01', '--pause', args.pause]
    if args.fillers:
        command += ['--fillers', args.fillers]
    if args.punch_in is not None:
        command += ['--punch-in', args.punch_in]
    if args.silence_only:
        command.append('--silence-only')
    if args.music_bed:
        command.append('--music-bed')
    if args.reel_limit is not None:
        command += ['--reel-limit', args.reel_limit]
    tighten_code = run_tool('cut.py', *command, accepted=(0, 1))
    render_code = run_tool('cut.py', 'render', folder, '--final', accepted=(0, 1))
    current = (folder / 'cuts' / 'current').read_text(encoding='utf-8').strip()
    picture = folder / 'cuts' / current / 'preview.mp4'
    if not picture.is_file():
        raise ValueError(f'render did not produce a file; project retained at {folder}')
    shutil.copy2(picture, out)
    shutil.copy2(folder / 'film.tighten-report.md', report)
    shutil.copy2(folder / 'film.tighten.json', data)
    source_reel = folder / 'film.tighten-reel.mp4'
    if source_reel.is_file():
        shutil.copy2(source_reel, reel)
    with report.open('a', encoding='utf-8', newline='\n') as handle:
        handle.write(f'\nRevision project: {folder}\nOutput: {out}\n')
    check_code = run_tool('check.py', '--file', out, '--no-speech', '--json', checks, accepted=(0, 1, 2))
    print(f'Output: {out}\nReport: {report}\nRevision project: {folder}\nChecks: {checks}')
    if check_code == 2:
        print('The output check could not complete; inspect its diagnostic above.', file=sys.stderr)
    return 1 if tighten_code or render_code or check_code else 0


def main():
    """Command line for a single file."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file')
    parser.add_argument('--out')
    parser.add_argument('--pause', type=float, default=0.35)
    parser.add_argument('--fillers', help='named or comma-separated words and phrases; off by default')
    parser.add_argument('--punch-in', type=float, help='alternate this zoom on each line; off by default')
    parser.add_argument('--music-bed', action='store_true', help='keep pauses and fillers when a bed is present')
    parser.add_argument('--reel-limit', type=int, help='show at most N reel events, cuts first; off by default')
    parser.add_argument('--silence-only', action='store_true', help='keep measured nonquiet audio without a transcript')
    args = parser.parse_args()
    try:
        return quick_file(args)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'tighten: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
