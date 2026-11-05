#!/usr/bin/env python3
"""Check a cut, or any video file, and say plainly what passes, what to look at and what needs a person.

  python check.py PROJECT [--version vNNN] [--final FILE [--captions FILE]] [--caption-profile FILE] [--no-speech]
  python check.py --file EXPORT [--captions FILE] [--caption-profile FILE]
                  [--timeline XML (--project DIR | --source-words FILE ...) [--map FILE=ALIAS] [--track N]
                   | --edit-words FILE] [--speech-words FILE | --no-speech] [--delivery FILE]
                  [--spec WxH@FPS] [--duration S] [--target LUFS] [--vcodec h264] [--pix-fmt yuv420p]
                  [--color bt709] [--allow-bars] [--json checks.json]
  python check.py --verify CHECKS.json

It picks the checks the file and the job call for, runs the existing scripts, and writes checks.json
(references/project.md section 5), each item in one state: pass (measured and fine), look (measured; a person should
look), fail (measured and wrong), you (only a person can judge) or skip (not assessed, with the reason and how to
supply what it needs; its label begins "Not assessed", and the readiness line counts it as not assessed, never as
passed):
- spec: frame size or shape, frame rate, duration, codec, pixel format, colour tags (qc_file.py);
- measured loudness, compared with a target only when supplied; final files with sound also get a lossy true-peak
  check. Every sound check reads the stream a player plays by default, and a file with several says which it read and
  names the others with their levels (a look when that stream is silent and another has sound);
- clicks at the start and a cut-off tail (qc_file.py's audio edges), and holes of digital silence inside the film
  (a look: the room tone drops out). A tail that ends away from silence is named as the last sound still playing
  when the picture ends; for a project version whose edit places its last sound past the picture's last frame (a
  film length that is not a whole number of frames), the item says by how much and how to fix it;
- flashing (flash_scan.py, WCAG 2.3.1) and near-empty frames (blank_scan.py);
- an empty first frame: frame 0 (most feeds' thumbnail and autoplay frame) black, white or one colour is a look,
  with the time the picture first shows something; a designed fade in from the start is named as its cause;
- stereo fold-down, candidate borders, interlacing and freezes, sampled colour range, DC and sample peaks;
  inconclusive detectors skip with a reason, and designed holds are excluded from freeze prompts;
- captions, as three items that say what each compared and which caption file they read:
  reading rules (line length, lines, overlaps; reading speed and duration as looks; with --caption-profile, a house
  style passed to captions.py check --profile);
  captions follow the edit: against edit-time words (a version's lines.json, or the words exchange.py places on an
  editor's timeline), which finds words cut but still captioned, and kept words no caption shows (it compares text
  with text, not with the sound);
  captions match the speech: against a transcript of the checked file's own audio (transcribe.py with faster-whisper,
  local, never downloading weights here), every word heard checked against the whole caption timeline, gaps
  included; differences and speech no caption carries are looks, since a transcript can mishear. It passes only when
  every word heard is in a caption. This is the only item that compares captions with what is said; without
  faster-whisper it is not assessed and says how to install it. A transcript with no words is "no speech was heard"
  only when the sound measures as silence; over measurable sound it is not assessed, since speech may have been missed;
  a caption file with no captions on a film with sound is a look, or a failure when captions are required;
- title contrast, when the version has titles: each title's letters against the picture around them at its midpoint
  (a look below 3:1, naming for each low title the nearest colour and the black plate that would reach 3.3:1 against
  the ground measured there, with their ratios); full-frame cards are not measured;
- with --against IN --edit KIND, what that kind of edit must keep: its duration and streams, and its content where
  that is cheap to compare: sampled pictures against the source frames the edit says they show (trim, speed, convert,
  compress) and the sound against the source's (trim, convert, compress, extract-audio, reframe), tolerant of
  re-encoding and scaling. Confident disagreement fails; too little to compare (flat picture, a steady tone) is not
  assessed. What is not compared says "Not assessed: content": a reframe's picture and a speed change's sound;
- what only a person can judge: watched muted, heard with sound, names in captions; an item a person has recorded
  in status.json (`reviewed`) counts as passed only for the file it was recorded against (its SHA-256; an older
  record without one counts for the version's preview only), so watching the preview never passes a final file.

An editor's export (--file), checked as delivered, without rebuilding the film as a paper edit: give the caption
sidecar delivered with it (--captions: SRT, WebVTT or caption JSON); the timeline it was exported from (--timeline,
Final Cut Pro 7 XML, which Premiere Pro writes with File > Export > Final Cut Pro XML) with the source transcripts
(--project DIR, whose map holds them, or --source-words FILE ...; --map and --track pass to exchange.py words), or
edit-time words exchange.py words already made (--edit-words); and a transcript of this export (--speech-words),
else it is transcribed here as for a project. A --speech-words transcript must record the media it was made from
("media": {"sha256", ...}, as transcribe.py writes): one of another file is never used as this export's speech (the
item says so and is not assessed), and one that records no media is at most a look ("cannot confirm this transcript
is of this export"). The timeline item says how exchange.py followed it: clips not mapped (speed changes, nested
sequences), without a transcript, or whose transcript is stale (made from other media) are a look with counts, since
captions over them are not checked against the edit. When the export has sound and no --captions was given, captions
are not assessed (or fail when the delivery settings require them; "captions_required": false leaves them out).
--delivery FILE is the expected delivery as JSON: size ("1920x1080"), fps ("24000/1001"), frames or duration_s,
loudness (LUFS target), vcodec, pix_fmt, color, captions_required, allow_bars; flags override it, and an unknown key is
refused. The timeline's words are in sequence time: the export must start at the sequence's start (an export of an
in-to-out range shifts every caption against them).

Every result names what it depends on. checks.json records `inputs`, one row per file (role, an absolute path for
--file, or for a project relative to the project folder; sha256, bytes, mtime_ns; a file that did not exist is recorded
with no hash, so adding it expires the result): for --file the export, captions, timeline and its media, source and
edit words, speech transcript, delivery settings and caption profile; for a project the preview or final, the captions
checked, title assets, the version's lines.json, edit.json, film.md, declared.json, manifest.json and caption-burn.json,
and the map transcripts and listing used to select speech settings. It records `tools`: the skill version, Python,
FFmpeg and FFprobe version lines, relevant package versions, the speech model when a speech check is attempted, and the
SHA-256 of invoked, imported and required scripts. --verify CHECKS.json
re-hashes them and says current, or lists each changed input or tool. project.py status and the Screening Room use a
fast size-and-time comparison for file inputs; a change preserving both can escape it. Transcript listings, tool
versions and script hashes are compared on status reads. When a change is detected the checks file is out of date,
naming the input, and never counted as passing.

A final is checked with its own captions: --final FILE --captions FILE checks the sidecar delivered with it; without
--captions, the caption items say they checked the version's captions.srt (which is in the inputs).

Every scanner writes into a fresh folder for this run; only a report this run produced is used, then copied into the
version's qa/ folder (qa/final-* for --final), replacing the previous run's. A scanner that crashes, lacks a
dependency or writes no report is not assessed (skip, with the reason), never an earlier result.

For a project it also updates status.json: the readiness line (a final check's result is shown with the file it
checked), what needs the person, and blind spots; a final check with a failure sets the check stage back to now. The
check stage marked done means the checks ran, not that they passed or that a person accepted the file. checks.json
records the checked file's sha256. The rendered files are never changed; --json naming any input is refused (exit 2)
with the input untouched. It measures files; it does not watch or listen, judge story or taste, or verify claims
(film_check.py does that for kit films).

Exit 0 when nothing failed or needs a look (person items and items not assessed may remain), 1 when something failed
or needs a look, 2 when it cannot run. --verify: 0 current, 1 an input or tool changed, 2 cannot run (no such file,
or a checks file written before inputs were recorded).
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEP = ' ' + chr(183) + ' '
DEFAULT_LOUDNESS = None
DEFAULT_SPEECH_MODEL = 'small'
READING_RULES = {'invalid timing', 'lines', 'line length', 'overlap', 'minimum duration', 'maximum duration', 'cps',
                 'orphan', 'gap'}
WORD_PROMPTS = {'spelled differently from the words', 'contraction differs from the words', 'spoken but not captioned',
                'speech with no caption', 'apparent offset from estimated word times: listen'}
QA_FILES = ('qc.json', 'flash_scan.json', 'blank_scan.json', 'captions-rules.json', 'captions-edit.json',
            'captions-speech.json', 'speech-words.json', 'captions-check.json', 'captions-contrast.json',
            'titles-contrast.json', 'technical.json')
TITLE_CONTRAST = 3.0
# A suggested title colour or plate aims this far above the floor, so a re-encode does not tip it back under.
SUGGEST_MARGIN = 1.1
DROPOUT_DB = -80
DROPOUT_S = 0.08
# EBU R128's absolute gate: ebur128 reports this for digital silence and for sound too quiet to measure.
SILENCE_LUFS = -70.0
# A quick edit's frames are compared with its source's as grey thumbnails. Measured on the first-cut example's one
# scene, as the best correlation with the source frames around each of eight samples: faithful re-encodes down to
# 30 kb/s at 160 pixels wide, a GIF, VP9 and MPEG-4 at 0.995 or more; another passage of that scene at 0.53 or less; a
# passage one second off, in a shot with little movement, at 0.83 or more, which is too close to tell. A thumbnail that
# varies by less than PICTURE_FLAT grey levels has too little detail to correlate.
THUMBNAIL = (64, 36)
PICTURE_SAMPLES = 8
PICTURE_SAME = 0.9
PICTURE_OTHER = 0.6
PICTURE_FLAT = 3.0
PICTURE_SHAPE = 0.04
# sync_check.py holds both sounds in memory, at about 0.4 MB a second each.
AUDIO_COMPARE_S = 900
# The first frame is read at this size; it is one colour when no channel spans more than FLAT_SPAN code values.
FIRST_FRAME_SIZE = (96, 54)
FLAT_SPAN = 12
FIRST_FRAME_REACH_S = 10.0
MODEL_SIZES = {'base': 'about 150 MB', 'small': 'about 460 MB', 'large-v3-turbo': 'about 1.6 GB'}
IDENTITY_NOTE = ("the transcript's identity is not verified; bind it to the source with map.py run PROJECT "
                 "--alias ALIAS, or after checking use map.py confirm-words PROJECT ALIAS --note TEXT")


def load_project_module():
    """project.py from this folder (paths, status, versions, readiness)."""
    spec = importlib.util.spec_from_file_location('lf_project', HERE / 'project.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_project_module()
INVOKED = set()


def run_script(name, *args):
    """Run a sibling script; return (exit code, combined output). The script is recorded as one this run invoked."""
    INVOKED.add(name)
    result = subprocess.run([sys.executable, '-I', str(HERE / name), *map(str, args)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    return result.returncode, (result.stdout + result.stderr).strip()


def load_captions_module(name):
    """captions.py from this folder as a module (for its contrast measurements), recorded as invoked."""
    INVOKED.add('captions.py')
    spec = importlib.util.spec_from_file_location(name, HERE / 'captions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ffmpeg_version():
    """FFmpeg's version line ('ffmpeg version 7.1 ...'), or None when FFmpeg is not found."""
    return P.ffmpeg_version()


def package_version(name):
    """An installed package's version without importing it, or None."""
    return P.package_version(name)


def tools_record(model=None):
    """Record media tools, relevant packages, the speech model and invoked scripts including imported helpers."""
    scripts = {}
    names = {'check.py', 'project.py'} | INVOKED
    if names & {'qc_file.py', 'transcribe.py'}:
        names.add('render_common.py')
    if 'tempo_map.py' in names:
        names.add('sound_io.py')
    if 'delivery_check.py' in names:
        names.update(('with_lock.py', 'setup.py'))
    for name in sorted(names):
        path = HERE / name
        scripts[name] = P.file_sha256(path) if path.is_file() else None
    whisper = None
    if 'transcribe.py' in INVOKED:
        whisper = {'version': package_version('faster-whisper'), 'model': model}
    packages = {name: P.package_version(name) for name in sorted(P.required_packages(names))}
    return {'skill_version': P.skill_version(), 'python': platform.python_version(), 'ffmpeg': ffmpeg_version(),
            'ffprobe': P.ffprobe_version(), 'packages': packages, 'faster_whisper': whisper, 'scripts': scripts}


def tool_changes(recorded):
    """Tools that differ now from those a result recorded: [{'tool', 'was', 'now'}]."""
    return P.tool_changes(recorded)


def why_not_run(name, code, output):
    """Why a script produced no report, and how to fix it."""
    # The scripts' own message names the package, the Python it is missing from and the setup command: keep it whole.
    named = re.search(r'^.* is missing from Python .*\. Fix: .*$', output, re.MULTILINE)
    if named:
        return f'{name} could not run: {named.group(0).strip()}'
    missing = re.search(r"No module named '([\w.]+)'", output)
    if missing:
        return f"{name} could not run: {P.dependency_message(missing.group(1).split('.')[0])}"
    # "moov atom not found" is a damaged file named by a tool that is plainly there, so the tools are looked for.
    tools = all(shutil.which(os.environ.get(tool.upper()) or tool) for tool in ('ffmpeg', 'ffprobe'))
    if not tools and re.search(r'ffmpeg|ffprobe', output, re.IGNORECASE) and re.search(
            r'not found|no such file|cannot find', output, re.IGNORECASE):
        return f'{name} could not run: FFmpeg was not found; install FFmpeg (ffmpeg and ffprobe on PATH)'
    last = output.strip().splitlines()[-1][-160:] if output.strip() else 'no output'
    return f'{name} could not run (exit {code}): {last}; run it on its own to see why'


def run_report(name, args, out):
    """Run a scanner that writes a JSON report to `out`, a path in this run's fresh folder: (report, None) when this
    run wrote a readable report and exited 0 or 1, else (None, why it did not run and how to fix it)."""
    code, output = run_script(name, *args)
    if code in (0, 1) and out.is_file():
        try:
            report = json.loads(out.read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            return None, f'{name} wrote a report that cannot be read ({error})'
        if isinstance(report, dict):
            return report, None
    return None, why_not_run(name, code, output)


def item(key, label, state, detail='', at=None):
    """One checks.json item."""
    return {'id': key, 'label': label, 'state': state, 'detail': detail, 'at': at}


SPEC_REMEDIES = {
    'faststart': 'move the index to the front without re-encoding: '
                 'ffmpeg -i IN.mp4 -c copy -movflags +faststart OUT.mp4',
    'color_tags': 'when the picture already is BT.709, tag it without re-encoding: ffmpeg -i IN.mp4 -c copy -bsf:v '
                  'h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1 OUT.mp4; '
                  'otherwise convert it (references/finishing.md section 3)',
    'vcodec': 're-encode for the web: ffmpeg -i IN -c:v libx264 -crf 18 -pix_fmt yuv420p -c:a aac '
              '-movflags +faststart OUT.mp4',
    'pix_fmt': 're-encode with -pix_fmt yuv420p, which phones and browsers play',
}


def spec_item(qc, basis=''):
    """The file's specification as one line, failing on any spec check that failed; `basis` says what it was checked
    against, and each failure a newcomer is likely to meet carries its one-line remedy."""
    video = qc.get('video') or {}
    duration = qc.get('container', {}).get('duration_s') or video.get('duration_s')
    parts = [f"{video.get('width')}x{video.get('height')}"]
    if isinstance(duration, (int, float)):
        parts.append(f'{duration:.1f} s')
    parts.append(str(video.get('codec', '?')).upper().replace('H264', 'H.264'))
    failed = {name: check for name, check in (qc.get('checks') or {}).items()
              if not check.get('pass') and name != 'true_peak_after_lossy_reencode'}
    against = f'checked against {basis}' if basis else ''
    if not failed:
        return item('spec', SEP.join(parts), 'pass', against)
    detail = '; '.join(f"{name}: expected {check.get('expected')}, got {check.get('actual')}"
                       + (f" (fix: {SPEC_REMEDIES[name]})" if name in SPEC_REMEDIES else '')
                       for name, check in failed.items())
    return item('spec', SEP.join(parts), 'fail', (against + '; ' if against else '') + detail)


def number(value):
    """A measured number, or None."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def true_peak_item(qc):
    """True peak after a lossy re-encode. When the re-encode could not be measured it is not run (or fails when the
    original peak alone is already too high), and the original is never shown as a re-encode measurement."""
    lossy = number(((qc.get('checks') or {}).get('true_peak_after_lossy_reencode') or {}).get('actual'))
    original = number((qc.get('loudness') or {}).get('true_peak_dbtp'))
    if lossy is not None:
        label = f'True peak {lossy:.1f} dBTP after a lossy re-encode'
        if lossy > -1.0:
            return item('true_peak', label, 'fail', "above -1 dBTP: a platform's encoder can clip it")
        if original is not None and original > -1.0:
            # The file as delivered is what most players decode; a quieter re-encode does not excuse it.
            return item('true_peak', f'True peak {original:.1f} dBTP in the file itself', 'fail',
                        f'above -1 dBTP before any re-encode ({lossy:.1f} dBTP after one)')
        return item('true_peak', label, 'pass')
    diagnostic = (qc.get('lossy_reencode') or {}).get('error') or 'the re-encode gave no true-peak reading'
    if original is not None and original > -1.0:
        return item('true_peak', f'True peak {original:.1f} dBTP before re-encode', 'fail',
                    f'already above -1 dBTP; the re-encode could not be measured: {diagnostic}')
    known = f'; the original file measured {original:.1f} dBTP (not a re-encode measurement)' if original is not None \
        else ''
    return item('true_peak', 'True peak after a lossy re-encode: not measured', 'skip',
                f'the re-encode could not be measured: {diagnostic}{known}; check that FFmpeg has an AAC encoder')


def loudness_items(qc, target, final, has_audio):
    """Measure loudness; compare it only with a target the person supplied."""
    if not has_audio:
        return [item('loudness', 'Loudness', 'skip', 'no sound')]
    loud = qc.get('loudness') or {}
    lufs = number(loud.get('integrated_lufs'))
    if lufs is None:
        loudness = item('loudness', 'Loudness', 'skip', 'not measured: ' + str(loud.get('error') or 'no reading'))
    else:
        label = f'{lufs:.1f} LUFS' + (f' (target {target:g})' if target is not None else '')
        if target is not None and abs(lufs - target) > 1.0:
            loudness = item('loudness', label, 'look', f'{abs(lufs - target):.1f} LU from the target')
        elif target is None and (lufs > -9 or lufs < -35):
            loudness = item('loudness', label, 'look', 'outside the broad -35 to -9 LUFS screening range; listen')
        else:
            loudness = item('loudness', label, 'pass', 'measured; no target specified' if target is None else '')
    if not final:
        loudness['detail'] = (loudness['detail'] + '; ' if loudness['detail'] else '') + 'preview, not mastered'
    return [loudness, true_peak_item(qc)] if final else [loudness]


def audio_speed(edit, row):
    """The speed assemble.py plays a sound item at: that of a picture item from the same source over its range."""
    for clip in edit.get('picture') or []:
        if (clip.get('src') == row.get('src') and float(clip['in']) < float(row['out'])
                and float(row['in']) < float(clip['out'])):
            return float(clip.get('speed', 1)) or 1.0
    return 1.0


def sound_past_picture(folder, frames):
    """How far a version's last sound runs past its picture's last frame, from its edit.json and frame count, as
    (seconds, sound item, sound end, picture end, frame rate), or None when it does not or cannot be read."""
    edit = P.load_json(Path(folder) / 'edit.json', None) if folder else None
    if not isinstance(edit, dict) or not isinstance(frames, int) or frames <= 0:
        return None
    try:
        rate = float(Fraction(str(edit.get('fps'))))
        ends = [(float(row['at']) + (float(row['out']) - float(row['in'])) / audio_speed(edit, row), row)
                for row in edit.get('audio') or []]
    except (TypeError, ValueError, KeyError, ZeroDivisionError):
        return None
    if not ends or rate <= 0:
        return None
    end, row = max(ends, key=lambda pair: pair[0])
    picture = frames / rate
    return (end - picture, row, end, picture, rate) if end - picture > 0.0005 else None


def cut_short_text(overrun):
    """The cause and remedy for a last sound that runs past the picture's last frame."""
    over, row, end, picture, rate = overrun
    return (f"the last sound ({row.get('src')} {float(row['in']):.2f}-{float(row['out']):.2f} s, placed at "
            f"{float(row['at']):.3f} s) ends at {end:.3f} s, {over * 1000:.0f} ms after the picture's last frame "
            f"({picture:.3f} s at {rate:g} fps), so its fade-out was cut short. The film's length is not a whole "
            f"number of frames (a change of 0.80 s at 24 fps moves the picture 19 frames, 0.792 s, but the sound "
            f"0.800 s): make each change whole frames (multiples of {1 / rate:.4f} s), end the sound earlier or hold "
            f"the picture; cut.py check warns before rendering")


def edges_item(qc, has_audio, overrun=None):
    """Clicks at the start and a cut-off tail, from qc_file.py's warnings, with the cause named for a tail: the last
    sound still playing when the picture ends, and by how much when the version's edit shows it (`overrun`, from
    sound_past_picture)."""
    if not has_audio:
        return None
    measurements = qc.get('audio_edges') or {}
    if measurements.get('measured') is False:
        return item('edges', 'Sound edges', 'skip', 'could not decode the start and end of the audio')
    edges = measurements.get('notes') or []
    if not edges:
        return item('edges', 'Sound boundaries near silence', 'pass', 'listen for clicks and truncated tails')
    tail = [note for note in edges if note.startswith('sound ends')]
    details = [note for note in edges if not note.startswith('sound ends')]
    if tail and overrun:
        details.append(cut_short_text(overrun))
    elif tail:
        details.append('the last sound is still playing when the picture ends (the file ends away from silence): end '
                       'the sound earlier so it fades out before the last frame, or hold the picture until it has; '
                       'listen for a click or cut-off tail')
    label = 'Last sound cut short' if tail and overrun else 'Sound ends abruptly' if tail else 'Sound edges'
    return item('edges', label, 'look', '; '.join(details))


def audio_streams_item(qc):
    """Which of several sound streams was measured, and the others by level; None for a file with one. A default stream
    with no sound while another has it is what a viewer would get: silence."""
    rows = qc.get('audio_streams') or []
    played = next((row for row in rows if row.get('default')), None)
    if len(rows) < 2 or played is None:
        return None

    def described(row):
        level = 'not measured' if row.get('peak_db') is None else f"peak {row['peak_db']:.1f} dB"
        if P.stream_is_silent(row):
            level = 'digitally silent'
        return f"stream {row['index']} ({level})"

    others = [row for row in rows if row is not played]
    named = ', '.join(described(row) for row in others)
    sounding = [row for row in others if row.get('peak_db') is not None and not P.stream_is_silent(row)]
    if P.stream_is_silent(played) and sounding:
        return item('audio_streams', f"Players use sound stream {played['index']} by default, and it is silent", 'look',
                    f'also in the file: {named}. The sound checks here read the default stream; a player plays it. '
                    f'Flag the stream with the sound as the default (ffmpeg -i IN -map 0 -c copy -disposition:a:'
                    f'{rows.index(played)} 0 -disposition:a:{rows.index(sounding[0])} default OUT), or remove the '
                    'silent one')
    return item('audio_streams', f"Sound measured on stream {played['index']}, which players use by default", 'pass',
                f'{described(played)}; also in the file, not measured by the sound checks here: {named}')


def dropout_item(video, has_audio, selector='0:a:0'):
    """Holes of digital silence inside the film's sound, where a listener hears the room vanish. Produced sources
    carry them at their own edit points (a NASA programme had exact zeros for 0.56 s inside an answer), and each of
    four agent cuts tested kept at least one. Silence at the very start, and after the last sound, is left to the
    edges item."""
    if not has_audio:
        return None
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        return item('dropouts', 'Holes in the sound', 'skip', 'FFmpeg or ffprobe not found')
    probe = subprocess.run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)],
                           capture_output=True, text=True)
    result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-i', str(video), '-map', selector, '-af',
                             f'silencedetect=noise={DROPOUT_DB}dB:d={DROPOUT_S}', '-f', 'null', '-'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        duration = None
    if result.returncode or duration is None:
        return item('dropouts', 'Holes in the sound', 'skip', 'could not decode the sound')
    starts = [float(value) for value in re.findall(r'silence_start: (-?[\d.]+)', result.stderr)]
    ends = [float(value) for value in re.findall(r'silence_end: (-?[\d.]+)', result.stderr)]
    ends += [duration] * (len(starts) - len(ends))
    holes = [(start, end) for start, end in zip(starts, ends) if start > 0.05 and end < duration - 0.05]
    if not holes:
        return item('dropouts', 'No holes in the sound', 'pass',
                    f'no digital silence of {DROPOUT_S:g} s or more inside the film')
    listed = ', '.join(f'{P.format_time(start)} ({end - start:.2f} s)' for start, end in holes[:8])
    more = f' and {len(holes) - 8} more (every hole is listed in the record)' if len(holes) > 8 else ''
    found = item('dropouts', f'{len(holes)} hole(s) in the sound', 'look',
                 f'digital silence at {listed}{more}: the room tone drops out. Fill each with room tone from a quiet '
                 f'moment of the same source (a ~ music line under it), or move the edge past it; a silence you '
                 f'designed can stay', holes[0][0])
    # The detail names eight; the record keeps every hole, so a long list can be read back and checked one by one.
    found['holes'] = [[round(start, 3), round(end, 3)] for start, end in holes]
    return found


def flash_definite(row):
    """A window flagged by the percentile measure or the red measure, or by an older report that does not say
    which detector counted. Same-pixel pattern detections alone are not definite: a handheld tilt across a bright
    wall with dark window frames (an ordinary interview) counted 30 reversals in a second with no luminance change."""
    if not isinstance(row, dict):
        return True
    classic = number(row.get('classic_max_per_s'))
    return classic is None or classic > 6 or (number(row.get('red_max_per_s')) or 0) > 6


def flash_item(report):
    """Report a conservative flash screen without presenting it as certification. Percentile and red flashes fail;
    pattern-only detections are a look a person must decide, since camera movement over fine detail triggers them."""
    flagged = report.get('flagged') or []
    if not flagged:
        return item('flash', 'No candidate flashes found', 'pass',
                    'screen only; details and motion can be missed; not WCAG certification')
    definite = [row for row in flagged if flash_definite(row)]
    if not definite:
        first = flagged[0]
        at = first.get('general_at_s') if isinstance(first, dict) else None
        return item('flash', 'Possible flashing pattern, camera movement or moving shapes', 'look',
                    f'{len(flagged)} window(s) where a pattern detector counted more than three reversals in a '
                    'second, or swings that no opposite swing reverses in the same pixels did (shapes sliding or '
                    'morphing); camera movement over fine detail also does this. Watch the moment at normal speed: a '
                    'flashing pattern fails WCAG 2.3.1. Not WCAG certification', at)
    first = definite[0]
    at = None
    if isinstance(first, dict):
        # A definite failure is a classic or red count over the limit: name its own moment (older reports carry
        # only the general time, which the pattern detector may have set).
        candidates = [number(first.get('classic_at_s', first.get('general_at_s')))
                      if (number(first.get('classic_max_per_s')) or 0) > 6 else None,
                      number(first.get('red_at_s')) if (number(first.get('red_max_per_s')) or 0) > 6 else None]
        candidates = [value for value in candidates if value is not None]
        at = min(candidates) if candidates else first.get('general_at_s')
        if at is None:
            at = first.get('red_at_s')
    return item('flash', 'Potential flash above screen limit', 'fail',
                f'{len(definite)} window(s); inspect, including possible motion; not WCAG certification', at)


def frame_rate(video):
    """The video stream's frame rate (avg_frame_rate, else r_frame_rate), or None."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        return None
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                             'stream=avg_frame_rate,r_frame_rate', '-of', 'csv=p=0', str(video)],
                            capture_output=True, text=True)
    for value in result.stdout.strip().split(','):
        try:
            rate = Fraction(value.strip())
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            return float(rate)
    return None


def flat_colour(frame):
    """The frame's colour as '#rrggbb' when it is one colour (no channel spans more than FLAT_SPAN), else None."""
    channels = [frame[offset::3] for offset in range(3)]
    if any(max(channel) - min(channel) > FLAT_SPAN for channel in channels):
        return None
    return '#' + ''.join('%02x' % round(sum(channel) / len(channel)) for channel in channels)


def colour_name(code):
    """Black, white or the colour code, for a label."""
    level = sum(int(code[index:index + 2], 16) for index in (1, 3, 5)) / 3
    return 'black' if level < 28 else 'white' if level > 228 else f'a single colour ({code})'


def first_frames(video, rate):
    """(colour of frame 0 or None, index of the first frame that is not one colour or None) within the first
    FIRST_FRAME_REACH_S seconds, decoding small and stopping at the first frame with a picture."""
    width, height = FIRST_FRAME_SIZE
    size = width * height * 3
    command = [shutil.which('ffmpeg'), '-v', 'error', '-nostdin', '-i', str(video), '-map', '0:v:0', '-t',
               f'{FIRST_FRAME_REACH_S:g}', '-vf', f'scale={width}:{height}:flags=area,format=rgb24', '-f', 'rawvideo',
               '-']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    first, shown, index = None, None, 0
    try:
        while True:
            frame = process.stdout.read(size)
            if len(frame) < size:
                break
            colour = flat_colour(frame)
            if index == 0:
                first = colour or ''
            if colour is None:
                shown = index
                break
            index += 1
    finally:
        process.kill()
        process.wait()
    return first, shown


def first_frame_item(video, declaration=None):
    """Frame 0 becomes the thumbnail and the autoplay frame on most feeds: a look when it is black, white or one
    colour, with the time the picture first shows something; a designed fade in from the start is named as the
    cause."""
    if not shutil.which('ffmpeg'):
        return item('first_frame', 'First frame', 'skip', 'FFmpeg not found; look at frame 0')
    rate = frame_rate(video)
    first, shown = first_frames(video, rate)
    if first is None:
        return item('first_frame', 'First frame', 'skip', 'no picture could be decoded; look at frame 0')
    if not first:
        return item('first_frame', 'First frame shows a picture', 'pass', 'frame 0 is not a single colour')
    if shown is None:
        when = f'nothing but one colour in the first {FIRST_FRAME_REACH_S:g} s'
    elif rate:
        when = f'the picture first shows something at {P.format_time(shown / rate)} (frame {shown})'
    else:
        when = f'the picture first shows something at frame {shown}'
    fades = [row for row in (declaration or {}).get('designed') or [] if isinstance(row, dict)
             and row.get('kind') == 'fade' and number(row.get('start')) is not None and row['start'] <= 0.001]
    if fades:
        cause = (f'the cause is the designed fade in ({P.format_time(0)}-{P.format_time(float(fades[0]["end"]))}); '
                 'keep it if the feed shows a cover you set, or start on the picture')
    else:
        cause = 'start on a frame that shows the subject, or set a cover frame where the platform allows one'
    return item('first_frame', f'First frame is {colour_name(first)}', 'look',
                f'it becomes the thumbnail and the autoplay frame on most feeds; {when}; {cause}', 0.0)


def blank_item(report):
    """Near-empty frames outside designed ranges."""
    all_runs = report.get('runs') or []
    runs = [run for run in all_runs if not run.get('declared')]
    if not runs:
        detail = f'{len(all_runs)} designed near-empty stretch(es) declared' if all_runs else ''
        return item('blank', 'No undeclared near-empty frames', 'pass', detail)
    first = runs[0]
    at = first.get('start_s', first.get('start')) if isinstance(first, dict) else None
    return item('blank', f'{len(runs)} near-empty stretch(es)', 'look', 'designed holds can be declared', at)


def mono_item(qc):
    """Report the measured loss after the stereo mix is folded to mono."""
    audio = qc.get('audio') or []
    if not audio or (audio[0].get('channels') or 0) != 2:
        return item('mono', 'Mono compatibility', 'skip', 'this fold-down check requires stereo audio')
    drop = number((qc.get('mono_fold_down') or {}).get('drop_lu'))
    if drop is None:
        return item('mono', 'Mono compatibility', 'skip', 'fold-down loudness unavailable; inspect in mono')
    # Ordinary wide stereo can lose about 3 LU without phase cancellation; leave headroom.
    # This whole-program level is a prompt to listen, not proof that every stem survives.
    state = 'fail' if drop >= 20 else 'look' if drop > 4.5 else 'pass'
    direction = 'quieter' if drop > 0 else 'louder' if drop < 0 else 'unchanged'
    label = 'Mono fold-down unchanged' if not drop else f'Mono fold-down {abs(drop):.1f} LU {direction}'
    return item('mono', label, state,
                'compare dialogue and music in mono; this is a whole-program measurement')


def bars_item(measurement, allowed):
    """Only stable, sampled dark borders are a crop candidate."""
    crop = measurement.get('crop') or {}
    width, height = crop.get('width'), crop.get('height')
    rect, samples = crop.get('crop'), crop.get('samples', 0)
    matching = crop.get('matching', samples)
    if not width or not height or not rect or samples < 3 or matching < samples * .6:
        return item('bars', 'Black borders', 'skip', 'no stable crop in at least three samples; inspect the frame')
    removed = max((width - rect[0]) / width, (height - rect[1]) / height)
    if removed < .04:
        return item('bars', 'No stable black borders detected', 'pass', f'{samples} sampled frames')
    detail = f'candidate crop {rect[0]}:{rect[1]}:{rect[2]}:{rect[3]} in {matching}/{samples} samples'
    if allowed:
        return item('bars', 'Black borders declared', 'pass', detail)
    if not crop.get('bars_confirmed'):
        return item('bars', 'Black borders', 'skip', detail + '; ' +
                    str(crop.get('verification') or 'check uniform edges across shots'))
    return item('bars', 'Possible black borders', 'look', detail + '; ' + crop['verification'] +
                '; declare intentional bars or inspect')


def interlace_item(qc, measurement):
    """Interlacing from idet's single-frame verdicts. Its multi-frame tally carries one guess across the frames it
    cannot decide, and on progressive film with fine detail (rooftops, a test pattern) it called seconds at a time
    interlaced; fine detail also gives both field orders, where real interlacing gives one."""
    stats = measurement.get('idet') or {}
    single = stats.get('single') or stats
    tff, bff = single.get('tff', 0), single.get('bff', 0)
    progressive = single.get('progressive', 0)
    decided = tff + bff + progressive
    detail = (f'idet single-frame: {tff} top, {bff} bottom, {progressive} progressive, '
              f'{single.get("undetermined", 0)} undecided')
    if decided < 10:
        return item('interlace', 'Interlacing', 'skip',
                    detail + '; too few frames decided; inspect fields on motion')
    interlaced = tff + bff
    if interlaced >= 10 and interlaced >= .3 * decided and max(tff, bff) >= .9 * interlaced:
        order = 'top' if tff >= bff else 'bottom'
        return item('interlace', f'Possible interlaced picture ({order} field first)', 'look',
                    detail + '; inspect moving edges for combing')
    if interlaced >= 10 and interlaced >= .3 * decided:
        # Fine detail in a progressive picture gives both orders, but so does an edit joining interlaced clips of
        # different field orders: the counts cannot tell them apart.
        return item('interlace', 'Possible interlaced picture (both field orders)', 'look',
                    detail + '; fine detail in a progressive picture also does this; inspect moving edges')
    return item('interlace', 'No interlacing detected', 'pass', detail)


def undeclared_freezes(ranges, declaration):
    """Subtract intentional holds and cards, retaining uncovered candidate intervals."""
    intentional = list(declaration.get('holds') or [])
    intentional += [entry for entry in declaration.get('designed') or []
                    if entry.get('kind') in ('hold', 'pause', 'title_card', 'still')]
    covered = []
    for row in intentional:
        if isinstance(row, dict):
            start, end = row.get('start'), row.get('end')
        else:
            start, end = row[:2]
        if number(start) is not None and number(end) is not None:
            covered.append((start, end))
    out = []
    for start, end in ranges:
        if number(start) is None or number(end) is None:
            continue
        pieces = [(start, end)]
        for low, high in covered:
            next_pieces = []
            for a, b in pieces:
                if high <= a or low >= b:
                    next_pieces.append((a, b))
                else:
                    if a < low:
                        next_pieces.append((a, low))
                    if high < b:
                        next_pieces.append((high, b))
            pieces = next_pieces
        out.extend((a, b) for a, b in pieces if b - a >= .25)
    return out


def freeze_item(measurement, declaration):
    """A static picture is a review prompt, not proof that a file is faulty."""
    if 'frozen' not in measurement:
        return item('freeze', 'Frozen picture', 'skip', 'freeze detector did not run')
    runs = undeclared_freezes(measurement['frozen'], declaration)
    if runs:
        return item('freeze', f'{len(runs)} possible undeclared freeze(s)', 'look',
                    'inspect the picture; stationary shots can also trigger this detector', runs[0][0])
    return item('freeze', 'No undeclared frozen picture detected', 'pass', 'detector uses a downscaled picture')


def color_range_item(qc, measurement):
    """BRNG measures samples outside limited-range code values, not creative intent."""
    tag = (qc.get('video') or {}).get('color_range')
    values = measurement.get('range') or {}
    count, maximum = values.get('samples', 0), number(values.get('max_brng'))
    if tag not in ('tv', 'mpeg'):
        return item('color_range', 'Colour range', 'skip',
                    f'range tag is {tag or "missing"}; limited-range BRNG cannot establish its correctness')
    if count < 3 or maximum is None:
        return item('color_range', 'Colour range', 'skip', 'fewer than three picture samples; inspect the levels')
    state = 'look' if maximum > .01 else 'pass'
    detail = f'maximum {maximum * 100:.2f}% outside limited range in {count} one-per-second samples'
    return item('color_range', 'Limited-range picture samples', state, detail)


def audio_integrity_item(qc, measurement, final=True):
    """DC and sample peaks are warnings about the decoded sound, not a listening test. A preview is not mastered:
    its AAC can overshoot full scale on a loud source (Tears of Steel's battle reached +0.5 dBFS through a -1 dBFS
    limiter), so there a peak at or above 0 dBFS is a look; on a final file it fails."""
    if not qc.get('audio'):
        return item('audio_integrity', 'Sound DC and clipping', 'skip', 'no audio')
    channels = measurement.get('audio') or []
    offsets = [abs(row['dc_offset']) for row in channels if number(row.get('dc_offset')) is not None]
    peaks = [row['peak_dbfs'] for row in channels if number(row.get('peak_dbfs')) is not None]
    if not offsets or not peaks:
        return item('audio_integrity', 'Sound DC and clipping', 'skip',
                    'audio statistics unavailable or silent; inspect the decoded sound')
    dc, peak = max(offsets), max(peaks)
    label = f'Sound peak {peak:.2f} dBFS; DC {dc:.4f}'
    if peak >= 0 and not final:
        return item('audio_integrity', label, 'look',
                    'preview, not mastered: its sound reaches full scale, so listen for distortion; the delivered '
                    'master (cut.py render --final --master) limits the true peak')
    state = 'fail' if peak >= 0 else 'look' if dc > .01 else 'pass'
    return item('audio_integrity', label, state,
                'sample peak at or above 0 dBFS fails; DC above 0.01 prompts inspection')


def technical_items(qc, declaration, bars_allowed=False, final=True):
    """Convert raw shared technical measurements into bounded, actionable verdicts."""
    measured = qc.get('technical') or {}
    if measured.get('error'):
        why = measured['error'] + '; run qc_file.py --technical to diagnose'
        keys = ('bars', 'interlace', 'freeze', 'color_range', 'audio_integrity')
        return [mono_item(qc)] + [item(key, key.replace('_', ' ').title(), 'skip', why) for key in keys]
    return [mono_item(qc), bars_item(measured, bars_allowed), interlace_item(qc, measured),
            freeze_item(measured, declaration), color_range_item(qc, measured),
            audio_integrity_item(qc, measured, final)]


def counted(rows):
    """'2 cps, 1 gap': rows counted by rule. A rule whose rows name words counts captions (or places) and words
    apart, since one caption can hold several: 'caption words not in the dialogue: 8 captions, 9 words'."""
    groups = {}
    for row in rows:
        groups.setdefault(row['rule'], []).append(row)
    parts = []
    for rule, group in sorted(groups.items()):
        words = sum(len(row['words']) for row in group if isinstance(row.get('words'), list))
        if not words:
            parts.append(f'{len(group)} {rule}')
            continue
        unit = 'caption' if all(row.get('cue') for row in group) else 'place'
        parts.append(f"{rule}: {len(group)} {unit}{'s' if len(group) != 1 else ''}, "
                     f"{words} word{'s' if words != 1 else ''}")
    return ', '.join(parts)


def examples(rows, limit=3):
    """The first few flagged captions and their words: 'caption 4: sold, house'; speech no caption carries by its
    time: 'no caption at 0:02.30: danger, ahead'."""
    shown = []
    for row in rows[:limit]:
        if isinstance(row.get('offset_s'), (int, float)) and not row.get('cue'):
            shown.append(f"the captions look {row['offset_s']:+.2f} s off estimated word times: listen")
            continue
        words = row.get('words') or row.get('caption_words') or [row.get('caption', '')]
        where = f"caption {row['cue']}" if row.get('cue') else f"no caption at {P.format_time(row.get('start') or 0)}"
        shown.append(f"{where}: {', '.join(str(word) for word in words)}")
    more = f' and {len(rows) - limit} more' if len(rows) > limit else ''
    return '; '.join(shown) + more


def first_moment(rows):
    """The edit time of the first flagged caption, or None."""
    times = [row['start'] for row in rows if isinstance(row.get('start'), (int, float))]
    return min(times) if times else None


def word_rows(report):
    """A word comparison's findings and the review prompts about words (timing prompts are listed, not judged)."""
    findings = [row for row in report.get('findings') or [] if row.get('rule') not in READING_RULES]
    prompts = [row for row in report.get('review') or [] if row.get('rule') in WORD_PROMPTS]
    timing = [row for row in report.get('review') or [] if row.get('rule') not in READING_RULES | WORD_PROMPTS
              and row.get('cue')]
    return findings, prompts, timing


def measured_sound(fresh):
    """(whether this run measured sound in the checked file, its integrated loudness or None): qc_file.py's report in
    this run's folder. Silence is only ever a measurement: a level this run did not get counts as sound, so nothing
    is excused by a measurement that is missing."""
    try:
        report = P.load_json(Path(fresh) / 'qc.json', None)
    except (OSError, ValueError):
        report = None
    loudness = report.get('loudness') if isinstance(report, dict) else None
    if not isinstance(loudness, dict) or loudness.get('error'):
        return True, None
    level = number(loudness.get('integrated_lufs'))
    return level is None or level > SILENCE_LUFS, level


def rules_item(srt, fresh, profile=None, sound=False, required=None):
    """Caption reading rules: line length, lines and overlaps fail; reading speed, duration and gaps are looks. With a
    house style (`profile`), captions.py check --profile applies its limits and reviewed exceptions. A file with no
    captions breaks no rule, so on a film with `sound` it is a look, or a failure when captions are `required`."""
    args = ['check', srt] + (['--profile', profile] if profile else []) + ['--json', fresh / 'captions-rules.json']
    report, why = run_report('captions.py', args, fresh / 'captions-rules.json')
    if report is None:
        return item('captions_rules', 'Caption reading rules', 'skip', why)
    findings, review, cues = report.get('findings') or [], report.get('review') or [], report.get('cues', 0)
    style = f' (house style {Path(profile).name})' if profile else ''
    if not cues and not findings and sound:
        detail = (f'{Path(srt).name} holds no captions and this film has sound, so a viewer who needs them gets '
                  'nothing: ')
        if required:
            entry = item('captions_rules', 'Captions required, but the caption file is empty', 'fail',
                         detail + 'give the sidecar that has the captions')
        else:
            entry = item('captions_rules', 'The caption file is empty', 'look',
                         detail + 'give the sidecar that has the captions, or, when the film is delivered without '
                         'them, leave it out ("captions_required": false for --file, captions: none in film.md)')
        entry['empty'] = True
        return entry
    if findings:
        return item('captions_rules', f'Caption reading rules{style}: {len(findings)} to fix', 'fail',
                    counted(findings))
    if review:
        return item('captions_rules', f'{cues} captions{SEP}{len(review)} reading prompts to look at{style}', 'look',
                    counted(review))
    return item('captions_rules', f'{cues} captions follow the reading rules{style}', 'pass')


LINES_BASIS = 'the kept words in lines.json'


def edit_item(srt, lines, fresh, basis=LINES_BASIS, missing=None):
    """Captions follow the edit: the captions against edit-time words (a version's lines.json, or the words
    exchange.py placed on an editor's timeline), named by `basis`. It finds words cut but still captioned; it compares
    text with text, not with the sound. `missing` says why there are no edit-time words and how to supply them."""
    if lines is None or not Path(lines).is_file():
        why = missing or (f'no edit-time words: {Path(lines).parent.name}/lines.json is missing (cut.py render writes '
                          'it)' if lines is not None else 'no edit-time words were given')
        return item('captions_edit', 'Captions follow the edit', 'skip', why)
    report, why = run_report('captions.py', ['check', srt, '--words', lines, '--json', fresh / 'captions-edit.json'],
                             fresh / 'captions-edit.json')
    if report is None:
        return item('captions_edit', 'Captions follow the edit', 'skip', why)
    findings, prompts, _ = word_rows(report)
    cues = report.get('cues', 0)
    if findings:
        flagged = len({row.get('cue') for row in findings})
        return item('captions_edit', f'Captions do not follow the edit: {flagged} of {cues} captions', 'fail',
                    f'{counted(findings)}, against {basis}: {examples(findings)}', first_moment(findings))
    if prompts:
        return item('captions_edit', f'Captions and the edit: {len(prompts)} to look at', 'look',
                    f'{counted(prompts)}: {examples(prompts)}; against {basis}', first_moment(prompts))
    if not cues:
        return item('captions_edit', 'Captions follow the edit', 'skip',
                    f'{Path(srt).name} holds no captions, so there is nothing to compare with {basis}')
    edit_kind = 'the paper edit' if basis == LINES_BASIS else 'the edit'
    return item('captions_edit', 'Captions follow the edit', 'pass',
                f'{cues} captions against {basis}: {edit_kind}, not the sound')


def speech_settings(root, with_source=False):
    """The transcription model and language the project's sources were transcribed with (small and auto-detect when
    none says); with `with_source`, also the map transcript they came from (None when none says)."""
    for path in sorted((Path(root) / 'map').glob('*/words.json')) if root else []:
        try:
            data = P.load_json(path, {}) or {}
        except (OSError, ValueError):
            continue
        engine = str(data.get('engine') or '')
        if engine.startswith('faster-whisper '):
            found = engine.split(' ', 1)[1].strip() or DEFAULT_SPEECH_MODEL, data.get('language')
            return found + (path,) if with_source else found
    return (DEFAULT_SPEECH_MODEL, None, None) if with_source else (DEFAULT_SPEECH_MODEL, None)


def transcription_failure(model, video, output):
    """Why the checked file could not be transcribed, and how to fix it."""
    if re.search(r"No module named '?faster_whisper", output):
        return P.dependency_message('faster_whisper') + ' (then rerun check.py)'
    if 'onnxruntime' in output:
        return ('faster-whisper is installed without onnxruntime, which its voice detector needs: '
                + P.dependency_message('onnxruntime') + ' (then rerun check.py)')
    if re.search(r'LocalEntryNotFound|snapshot|local_files_only|offline|not found in the cache', output,
                 re.IGNORECASE):
        size = MODEL_SIZES.get(model, 'public weights')
        command = P.python_command([HERE / 'transcribe.py', video, '--model', model, '--download', '--out',
                                    'words.json'])
        return (f"the faster-whisper {model} model is not downloaded yet ({size}); with the person's yes, download "
                f'it once with {command}, then rerun check.py')
    return why_not_run('transcribe.py', 1, output)


def speech_engine_missing():
    """Why the checked file cannot be transcribed here ('' when faster-whisper is importable)."""
    if importlib.util.find_spec('faster_whisper') is None:
        return P.dependency_message('faster_whisper') + ' (then rerun check.py)'
    return ''


NO_SPEECH = 'no speech was heard'


def coverage_note(report):
    """What the speech comparison examined, or None when the report does not say (then no match is claimed)."""
    coverage = (report.get('timing_screen') or {}).get('coverage')
    if not isinstance(coverage, dict) or not isinstance(coverage.get('words'), int):
        return None
    if coverage['words'] == 0:
        return NO_SPEECH
    return f"every one of the {coverage['words']} words heard is in a caption"


def speech_item(video, srt, fresh, model, language):
    """Captions match the speech: the captions against a transcript of the checked file's own audio, every word heard
    checked against the whole caption timeline. Differences and speech no caption carries are looks (a transcript can
    mishear); this is the only item that compares captions with what is said."""
    label = 'Captions match the speech'
    # A skipped comparison depends on the engine's absence as well as a completed one depends on its version.
    INVOKED.add('transcribe.py')
    missing = speech_engine_missing()
    if missing:
        return item('captions_speech', label, 'skip', missing)
    words = fresh / 'speech-words.json'
    args = [video, '--engine', 'faster-whisper', '--model', model, '--no-download', '--out', words]
    code, output = run_script('transcribe.py', *args, *(['--language', language] if language else []))
    if code != 0 or not words.is_file():
        return item('captions_speech', label, 'skip', transcription_failure(model, video, output))
    return speech_compare(srt, words, fresh, f'a faster-whisper {model} transcript of {Path(video).name}')


def speech_compare(srt, words, fresh, source):
    """The captions against a transcript of the checked file's speech (`words`, described by `source`): differences
    and speech no caption carries are looks; it passes only when every word heard is in a caption."""
    label = 'Captions match the speech'
    report, why = run_report('captions.py', ['check', srt, '--words', words, '--json', fresh / 'captions-speech.json'],
                             fresh / 'captions-speech.json')
    if report is None:
        return item('captions_speech', label, 'skip', why)
    findings, prompts, timing = word_rows(report)
    cues = report.get('cues', 0)
    transcript = P.load_json(words, {}) or {}
    if isinstance(transcript, dict) and transcript.get('voice_detection') == 'off':
        source += ' (voice detection was off; install onnxruntime and inspect the transcript)'
    if findings:
        flagged = len({row.get('cue') for row in findings if row.get('cue')}) or len(findings)
        return item('captions_speech', f'Captions and speech differ: {flagged} of {cues} captions', 'look',
                    f'{counted(findings)}: {examples(findings)}; against {source}, which can mishear: listen to '
                    'these', first_moment(findings))
    if prompts:
        return item('captions_speech', f'Captions and speech: {len(prompts)} to look at', 'look',
                    f'{counted(prompts)}: {examples(prompts)}; against {source}', first_moment(prompts))
    covered = coverage_note(report)
    if covered is None:
        return item('captions_speech', 'Captions and speech: coverage not reported', 'look',
                    f'captions.py did not say which words it checked against {source}; compare them by listening')
    timing_note = f'; timing prompts: {counted(timing)}' if timing else ''
    if covered == NO_SPEECH:
        sound, level = measured_sound(fresh)
        if sound:
            measured = f'measures {level:.1f} LUFS' if level is not None else 'was not measured as silence'
            return item('captions_speech', label, 'skip',
                        f'{source} holds no words, but the sound {measured}, so speech may have been missed: listen, '
                        'and give a transcript that has the speech')
        covered = NO_SPEECH + ' (the sound measures as silence)'
    return item('captions_speech', label, 'pass', f'{cues} captions against {source}; {covered}{timing_note}')


def transcript_of(path, sha256):
    """Whether a supplied transcript is of the file with this SHA-256: ('this', note), ('other', why) or ('unbound',
    why), from the media it records (project.transcript_media)."""
    try:
        data = P.load_json(path, None)
    except (OSError, ValueError) as error:
        raise ValueError(f'--speech-words {path} cannot be read: {error}') from None
    media = P.transcript_media(data)
    if media is None:
        return 'unbound', 'cannot confirm this transcript is of this export (it records no media it was made from)'
    if media['sha256'] != sha256:
        return 'other', (f'the transcript {Path(path).name} was made from other media (SHA-256 '
                         f"{media['sha256'][:12]}), not this export ({sha256[:12]}), so it is never used as the speech "
                         'of this export: transcribe this export (transcribe.py EXPORT --out words.json) and give that '
                         'with --speech-words')
    return 'this', f'made from this export (SHA-256 {sha256[:12]})'


def supplied_speech_item(srt, words, fresh, sha256):
    """Captions match the speech against a transcript the person supplied (--speech-words): used only when it records
    that it was made from this file; one of another file is refused, and one that records no media is at most a
    look."""
    provenance, note = transcript_of(words, sha256)
    if provenance == 'other':
        return item('captions_speech', 'Captions match the speech', 'skip', note)
    found = speech_compare(srt, words, fresh, f'the supplied transcript {Path(words).name}')
    if provenance == 'unbound' and found['state'] in ('pass', 'look'):
        if found['state'] == 'pass':
            found['label'] = 'Captions match an unconfirmed transcript'
        found['state'] = 'look'
        found['detail'] = note + '; ' + found['detail']
    return found


def caption_contrast_item(folder, video, fresh):
    """Recheck saved caption masks on the actual file, including its final encode."""
    manifest = P.load_json(folder / 'manifest.json', {}) or {}
    if 'burn' not in (manifest.get('captions') or []):
        return None
    report = P.load_json(folder / 'caption-burn.json', {}) or {}
    overlays = report.get('overlays') or []
    samples = [sample for overlay in overlays for sample in (overlay.get('contrast') or {}).get('samples', [])]
    ffmpeg = shutil.which('ffmpeg')
    if not samples or not ffmpeg:
        return item('captions_contrast', 'Burned-caption contrast', 'skip',
                    'no caption masks or FFmpeg; render the version again to sample its burned captions')
    captions = load_captions_module('lf_caption_contrast')
    measured = []
    for sample in samples:
        moment = sample.get('time_s')
        mask = sample.get('mask_png_b64')
        ratio = captions.contrast_from_mask(ffmpeg, video, moment, mask) if isinstance(moment, (int, float)) else None
        measured.append({'time_s': moment, 'ratio': ratio})
    P.save_json(fresh / 'captions-contrast.json', {'samples': measured,
                'method': 'decoded delivery frame and timed caption mask',
                'note': 'Sampled local contrast is not a full legibility or accessibility approval.'})
    usable = [sample for sample in measured if sample['ratio'] is not None]
    if not usable:
        return item('captions_contrast', 'Burned-caption contrast', 'skip',
                    'all timed contrast samples were inconclusive; inspect the captions on the delivered file')
    worst = min(usable, key=lambda sample: sample['ratio'])
    detail = f"{len(usable)} of {len(samples)} samples; inspect the full video at normal speed"
    if worst['ratio'] < 4.5 or len(usable) != len(samples):
        return item('captions_contrast', f"Caption contrast {worst['ratio']:.1f}:1", 'look', detail, worst['time_s'])
    return item('captions_contrast', f"Caption contrast {worst['ratio']:.1f}:1", 'pass', detail, worst['time_s'])


def title_contrast_item(folder, video, fresh):
    """Each title's letters against the picture just around them, at the title's midpoint on the actual file. Titles
    are set large, so the floor is 3:1 (WCAG's minimum for large text): a name in white over white hair or a bright
    sky passed every other check before this one."""
    edit = P.load_json(folder / 'edit.json', {}) or {}
    sources = edit.get('sources') if isinstance(edit.get('sources'), dict) else {}
    titles = [overlay for overlay in edit.get('overlays') or [] if isinstance(overlay, dict)
              and overlay.get('kind') == 'image' and str(overlay.get('src', '')).startswith('title-')
              and all(isinstance(overlay.get(key), (int, float)) for key in ('from', 'to'))]
    if not titles:
        return None
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return item('titles_contrast', 'Title contrast', 'skip', 'FFmpeg not found; inspect each title on the file')
    captions = load_captions_module('lf_title_contrast')
    measured = []
    for overlay in titles:
        path = folder / str((sources.get(overlay['src']) or {}).get('file') or '')
        moment = round((overlay['from'] + overlay['to']) / 2, 4)
        try:
            mask = captions.title_contrast_mask(path) if path.is_file() else None
        except (OSError, ValueError):
            mask = None
        parts = captions.contrast_parts(ffmpeg, video, moment, mask) if mask else None
        ratio = round(ratio_of(*parts), 2) if parts else None
        sample = {'title': overlay['src'], 'time_s': moment, 'ratio': ratio}
        if parts:
            sample.update(colour=title_colour(path), ground=round(parts[1], 5))
        measured.append(sample)
    P.save_json(fresh / 'titles-contrast.json', {'samples': measured,
                'method': "each title's opaque letters against the pixels around them, at its midpoint",
                'note': 'Sampled local contrast is not a full legibility or accessibility approval.'})
    usable = [sample for sample in measured if sample['ratio'] is not None]
    if not usable:
        return item('titles_contrast', 'Title contrast', 'skip',
                    'no title could be measured (full-frame cards are not); inspect each title on the file')
    worst = min(usable, key=lambda sample: sample['ratio'])
    detail = f'{len(usable)} of {len(measured)} titles measured against the picture around their letters'
    low = [sample for sample in usable if sample['ratio'] < TITLE_CONTRAST]
    if low:
        rows = []
        for sample in low:
            fix = contrast_suggestion(sample)
            rows.append(f"{P.format_time(sample['time_s'])} ({sample['ratio']:.1f}:1"
                        + (f'; passes with {fix}' if fix else '') + ')')
            sample['suggestion'] = fix or None
        P.save_json(fresh / 'titles-contrast.json', {'samples': measured, 'threshold': TITLE_CONTRAST,
                    'method': "each title's opaque letters against the pixels around them, at its midpoint",
                    'note': 'Sampled local contrast is not a full legibility or accessibility approval.'})
        return item('titles_contrast', f"Title contrast {worst['ratio']:.1f}:1", 'look',
                    f'below 3:1 at {"; ".join(rows)}: move the title to a plainer or darker part of the frame, give '
                    f'it a plate, or change its colour; {detail}', worst['time_s'])
    return item('titles_contrast', f"Title contrast {worst['ratio']:.1f}:1", 'pass', detail, worst['time_s'])


def wcag_luminance(rgb):
    """WCAG relative luminance of one sRGB colour (0-255 channels)."""
    channels = [value / 255 for value in rgb]
    linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def ratio_of(first, second):
    """WCAG contrast ratio of two luminances."""
    return (max(first, second) + .05) / (min(first, second) + .05)


def title_colour(path):
    """The colour of a rendered title's opaque letters (their mean), or None."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            pixels = list(image.convert('RGBA').getdata())
    except (ImportError, OSError, ValueError):
        return None
    letters = [pixel[:3] for pixel in pixels if pixel[3] >= 240]
    if not letters:
        return None
    return tuple(round(sum(pixel[channel] for pixel in letters) / len(letters)) for channel in range(3))


def nearest_passing_colour(colour, ground, target):
    """The colour nearest `colour` (mixed toward white or toward black, whichever needs less) whose contrast with a
    ground of luminance `ground` reaches `target`: (hex, ratio), or None when neither end reaches it."""
    found = []
    for end in ((255, 255, 255), (0, 0, 0)):
        for step in range(101):
            mixed = tuple(round(a + (b - a) * step / 100) for a, b in zip(colour, end))
            ratio = ratio_of(wcag_luminance(mixed), ground)
            if ratio >= target:
                found.append((step, '#%02x%02x%02x' % mixed, round(ratio, 1)))
                break
    if not found:
        return None
    _, code, ratio = min(found)
    return code, ratio


def plate_for(colour, ground, target):
    """The opacity (in 5% steps) of a black plate behind the letters that brings a ground of luminance `ground` to
    `target` against `colour`, with the ratio it gives: (percent, ratio), or None when even an opaque plate does not.
    The plate darkens the encoded values, so the ground's luminance falls by about the 2.2 power of what shows."""
    letters = wcag_luminance(colour)
    for percent in range(0, 101, 5):
        darker = ground * (1 - percent / 100) ** 2.2
        if letters > darker and ratio_of(letters, darker) >= target:
            return percent, round(ratio_of(letters, darker), 1)
    return None


def contrast_suggestion(sample, threshold=TITLE_CONTRAST):
    """What would make one low-contrast title pass, from its measured ground: the nearest colour that reaches the
    threshold (with a margin) and a black plate that does, each with its ratio against that ground."""
    colour, ground = sample.get('colour'), sample.get('ground')
    if colour is None or ground is None:
        return ''
    target = threshold * SUGGEST_MARGIN
    parts = []
    nearest = nearest_passing_colour(colour, ground, target)
    if nearest:
        parts.append(f'colour {nearest[0]} ({nearest[1]:.1f}:1)')
    plate = plate_for(colour, ground, target)
    if plate and plate[0]:
        parts.append(f'a black plate at {plate[0]}% behind the letters ({plate[1]:.1f}:1)')
    return ' or '.join(parts)


def with_note(entry, note):
    """An item with a note about its inputs added to its detail."""
    if note:
        entry['detail'] = (entry['detail'] + '; ' if entry['detail'] else '') + note
    return entry


def speech_skip_or_item(video, srt, fresh, speech, has_audio, how=''):
    """Captions match the speech by transcribing the checked file, or the reason it is not assessed."""
    if not has_audio:
        return item('captions_speech', 'Captions match the speech', 'skip', 'no sound to transcribe')
    if not speech:
        return item('captions_speech', 'Captions match the speech', 'skip',
                    'not run (--no-speech); run check.py without it to compare the captions with the audio' + how)
    model, language = speech
    return speech_item(video, srt, fresh, model, language)


def caption_items(folder, video, fresh, speech, has_audio, captions=None, note='', profile=None):
    """The three caption items (reading rules, follow the edit, match the speech) for a version with captions: its
    own captions.srt, or `captions`, the sidecar delivered with a final. `note` says which file was checked."""
    srt = Path(captions) if captions else folder / 'captions.srt'
    sound = has_audio and measured_sound(fresh)[0]
    if captions is None and (not srt.is_file() or not P.read_text(srt).strip()):
        # The version's own empty file: nothing to compare, but a film with sound that did not say captions: none has
        # captions a viewer will not get.
        manifest = P.load_json(folder / 'manifest.json', {}) or {}
        wanted = manifest['captions'] if 'captions' in manifest else (
            front_matter(folder / 'film.md').get('captions', 'srt').lower() != 'none')
        if not srt.is_file() or not wanted or not sound:
            return []
        return [with_note(rules_item(srt, fresh, profile, sound), note)]
    items = [with_note(rules_item(srt, fresh, profile, sound), note),
             with_note(edit_item(srt, folder / 'lines.json', fresh), note)]
    contrast = caption_contrast_item(folder, video, fresh)
    if contrast is not None:
        items.append(contrast)
    items.append(with_note(speech_skip_or_item(video, srt, fresh, speech, has_audio), note))
    return items


SUPPLY_TIMELINE = ('give --timeline XML (Premiere Pro: File > Export > Final Cut Pro XML) with --project DIR or '
                   '--source-words FILE, or --edit-words FILE made by exchange.py words')


def stale_sources(project):
    """The project's sources whose transcript was made from other media: {alias: reason} (project.transcript_state)."""
    try:
        index = P.load_json(Path(project) / 'map' / 'sources.json', {}) or {}
    except (OSError, ValueError):
        return {}
    stale = {}
    for source in (index.get('sources') or []) if isinstance(index, dict) else []:
        alias = source.get('alias') if isinstance(source, dict) else None
        path = Path(project) / 'map' / str(alias) / 'words.json'
        if not alias or not path.is_file():
            continue
        try:
            state, reason = P.transcript_state(source, P.load_json(path, {}))
        except (OSError, ValueError):
            continue
        if state == 'stale':
            stale[alias] = reason
    return stale


def timeline_item(result, origin, stale=None):
    """The editor's timeline as exchange.py words followed it: clips not mapped, clips without a transcript and clips
    whose transcript is stale (made from other media) are a look with counts, since captions over them are not
    checked against the edit; a disabled track or enabled tracks not read are named too."""
    coverage = result.get('coverage') if isinstance(result.get('coverage'), dict) else {}
    not_mapped = result.get('not_mapped') or coverage.get('not_mapped') or []
    unmatched = result.get('unmatched') or coverage.get('unmatched') or []
    stale_rows = [row for row in unmatched if 'stale' in str(row.get('why', '')).lower()]
    missing = [row for row in unmatched if row not in stale_rows]
    stale_clips = {row.get('clip') for row in stale_rows}
    stale_clips |= {row.get('clip') for row in result.get('stale') or [] if isinstance(row, dict)}
    for match in result.get('matches') or []:
        if match.get('source') in (stale or {}):
            stale_clips |= set(match.get('clips') or [])
    stale_clips.discard(None)
    skipped = result.get('skipped') or coverage.get('skipped') or []
    clips = coverage.get('clips') - len(skipped) if isinstance(coverage.get('clips'), int) else None
    track = coverage.get('track', 1)
    problems = []
    if not_mapped:
        problems.append(f"{len(not_mapped)} not mapped ({not_mapped[0].get('why', 'unsupported')})")
    if missing:
        problems.append(f"{len(missing)} without a transcript ({missing[0].get('why', 'no transcript')})")
    if stale_clips:
        why = next(iter((stale or {}).values()), None) or (stale_rows[0].get('why') if stale_rows else 'stale')
        problems.append(f'{len(stale_clips)} with a stale transcript ({why})')
    unverified = [row for row in result.get('matches') or [] if isinstance(row, dict)
                  and (str(row.get('by', '')).startswith('file name')
                       or 'transcript does not record the media' in str(row.get('by', '')))]
    if unverified:
        problems.append(f'{len(unverified)} file(s): {IDENTITY_NOTE}')
    if coverage.get('track_enabled') is False:
        problems.append(f'audio track {track} is disabled, so its clips do not play')
    unread = coverage.get('enabled_audio_not_read') or []
    if unread:
        problems.append('enabled audio tracks not read: ' + ', '.join(f"{row.get('track')} ({row.get('clips')} clips)"
                                                                      for row in unread))
    placed = len(result.get('words') or [])
    total = f'{clips} clips' if isinstance(clips, int) else 'the clips'
    origin += f' ({len(skipped)} disabled clip(s) skipped)' if skipped else ''
    if problems:
        followed = len(not_mapped) + len(missing) + len(stale_clips)
        label = (f'Timeline: {followed} of {total} not followed' if followed
                 else f'Timeline: {total} on audio track {track}, '
                      + ('identity not verified' if unverified else 'with tracks left out'))
        return item('timeline', label, 'look', f"{'; '.join(problems)}; {placed} words placed from {origin}: "
                    'captions over clips not followed are not checked against the edit')
    return item('timeline', f'Timeline: {total} on audio track {track}, each with a transcript', 'pass',
                f'{placed} words placed from {origin}')


def timeline_words(plan, fresh):
    """Edit-time words for the export: (words file or None, timeline item, why there are none). From --timeline
    through exchange.py words, or from --edit-words (its coverage, when exchange.py made it)."""
    if plan.get('timeline'):
        out = fresh / 'edit-words.json'
        args = ['words', plan['timeline']]
        args += ['--project', plan['project']] if plan.get('project') else []
        for words in plan.get('source_words') or []:
            args += ['--words', words]
        for pair in plan.get('map') or []:
            args += ['--map', pair]
        args += ['--track', plan['track']] if plan.get('track') else []
        result, why = run_report('exchange.py', args + ['--json', out], out)
        name = Path(plan['timeline']).name
        if result is None:
            return None, item('timeline', 'Timeline', 'skip', why), 'no edit-time words: ' + why
        stale = stale_sources(plan['project']) if plan.get('project') else {}
        return out, timeline_item(result, 'the timeline ' + name, stale), None
    if plan.get('edit_words'):
        path = Path(plan['edit_words'])
        try:
            result = P.load_json(path, {}) or {}
        except (OSError, ValueError) as error:
            raise ValueError(f'--edit-words {path} cannot be read: {error}') from None
        if isinstance(result, dict) and ('not_mapped' in result or 'coverage' in result):
            return path, timeline_item(result, 'the edit-time words ' + path.name), None
        return path, item('timeline', 'Timeline', 'skip',
                          f'{path.name} does not record which clips it followed (exchange.py words writes that); '
                          + SUPPLY_TIMELINE), None
    return None, item('timeline', 'Timeline', 'skip', 'no timeline was given: ' + SUPPLY_TIMELINE), \
        'no edit-time words: ' + SUPPLY_TIMELINE


def file_caption_items(plan, video, fresh, has_audio):
    """Caption and timeline items for --file: reading rules, captions follow the edit (against the timeline's words),
    captions match the speech (against a transcript of this export) and the timeline itself. A family this run cannot
    assess is a skip saying why and how to supply it, including captions when the export has sound and none were
    given (unless the delivery settings say captions are not required)."""
    edit_words, timeline, missing = timeline_words(plan, fresh)
    items = []
    captions = plan.get('captions')
    if not captions:
        required = plan.get('captions_required')
        if required:
            items.append(item('captions', 'Captions required, but no caption file given', 'fail',
                              'the delivery settings require captions: give the delivered sidecar with --captions FILE '
                              '(SRT, WebVTT or caption JSON); burned-in captions are not read here'))
        elif required is None and has_audio:
            items.append(item('captions', 'Captions', 'skip',
                              'the export has sound and no caption file was given: give the delivered sidecar with '
                              '--captions FILE (SRT, WebVTT or caption JSON), or set "captions_required": false in '
                              '--delivery when the film is delivered without captions'))
        # A plain file has no edit to follow: the timeline row belongs to an editor's export, so it shows only when
        # something about the edit was given.
        edited = any(plan.get(key) for key in ('timeline', 'project', 'source_words', 'edit_words'))
        return items + ([timeline] if edited else [])
    basis = (f"the timeline's words ({Path(plan['timeline']).name} through exchange.py words)" if plan.get('timeline')
             else f'the edit-time words in {Path(edit_words).name}' if edit_words else '')
    edit = edit_item(captions, edit_words, fresh, basis, missing)
    if IDENTITY_NOTE in timeline.get('detail', ''):
        if edit['state'] in ('pass', 'fail'):
            if edit['state'] == 'fail':
                edit['label'] = 'Captions and the edit: transcript identity not verified'
            edit['state'] = 'look'
        edit['detail'] += '; ' + IDENTITY_NOTE
    items += [rules_item(captions, fresh, plan.get('profile'), has_audio and measured_sound(fresh)[0],
                         plan.get('captions_required')), edit]
    if plan.get('speech_words') and has_audio:
        items.append(supplied_speech_item(captions, plan['speech_words'], fresh, plan['sha256']))
    else:
        items.append(speech_skip_or_item(video, captions, fresh, plan.get('speech'), has_audio,
                                         ', or give --speech-words FILE, a transcript of this export'))
    return items + [timeline]


def not_assessed(items):
    """Label every item that was not assessed so it can never read as passed: 'Not assessed: <what>'."""
    for entry in items:
        if entry['state'] == 'skip' and not entry['label'].startswith('Not assessed'):
            label = re.sub(r':\s*not measured$', '', entry['label'])
            label = label[:1].lower() + label[1:] if label[1:2].islower() else label
            entry['label'] = 'Not assessed: ' + label
    return items


def person_items(reviewed, has_audio, has_captions):
    """What only a person can judge; an entry recorded in status.json's reviewed counts as passed."""
    rows = [('watched_muted', 'Watched by you, muted')]
    if has_audio:
        rows.append(('heard', 'Heard by you, with sound'))
    if has_captions:
        rows.append(('names', 'Names and numbers in captions checked by you'))
    result = []
    for key, label in rows:
        record = (reviewed or {}).get(key)
        if record:
            who = record.get('by', 'a person') if isinstance(record, dict) else 'a person'
            result.append(item(key, label.replace('by you', f'by {who}'), 'pass'))
        else:
            result.append(item(key, label, 'you'))
    return result


def context_items(frame, cold, file_hash):
    """Report each frame field and a hash-bound cold read separately."""
    frame = frame if isinstance(frame, dict) else {}
    states = frame.get('state') if isinstance(frame.get('state'), dict) else {}
    waiver = frame.get('waived') if isinstance(frame.get('waived'), dict) else {}
    result = []
    for key in ('what', 'audience', 'why', 'knows_by'):
        value = frame.get(key)
        if key == 'knows_by':
            present = isinstance(value, list) and bool(value) and all(
                isinstance(row, dict) and number(row.get('s')) is not None and math.isfinite(row['s']) and row['s'] >= 0 and
                isinstance(row.get('channel'), str) and bool(row['channel'].strip()) for row in value)
        else:
            present = isinstance(value, str) and bool(value.strip())
        state = states.get(key, 'missing')
        if state == 'waived' and isinstance(waiver.get('reason'), str) and waiver['reason'].strip():
            entry = item('context_' + key, 'Context: ' + key, 'pass', 'waived: ' + waiver['reason'])
        elif present and state == 'confirmed':
            entry = item('context_' + key, 'Context: ' + key, 'pass', 'confirmed')
        else:
            detail = 'missing or incomplete' if not present else str(state)
            entry = item('context_' + key, 'Context: ' + key, 'unconfirmed', detail)
        entry['group'] = 'context'
        result.append(entry)
    if not isinstance(cold, dict) or cold.get('state') not in ('matched', 'mismatched') or not cold.get('by'):
        entry = item('context_cold', 'Not assessed: cold read', 'skip', 'no named cold read recorded')
    elif not file_hash or cold.get('file_sha256') != file_hash:
        entry = item('context_cold', 'Not assessed: cold read', 'skip', 'record is not for this file')
    else:
        entry = item('context_cold', 'Cold read', 'pass' if cold['state'] == 'matched' else 'look',
                     f"{cold['state']}; assessed by {cold['by']}; file {file_hash}")
    entry['group'] = 'context'
    result.append(entry)
    return result


def binding_item(identity):
    """Show the binding recorded in a version without claiming its freshness was checked."""
    identity = identity if isinstance(identity, dict) else {}
    binding = identity.get('binding')
    reason = identity.get('binding_reason') or identity.get('override_reason') or identity.get('unverified_reason') \
        or identity.get('decision') or identity.get('reason')
    reasons = identity.get('binding_reasons')
    if isinstance(reasons, list):
        values = ([str(reason)] if reason else []) + [str(value) for value in reasons if value]
        reason = '; '.join(dict.fromkeys(values)) or None
    if binding in ('receipt', 'plan-bound'):
        entry = item('sync_binding', 'Recorded binding', 'pass', str(binding) + '; cue freshness is checked separately')
    elif binding == 'screened':
        entry = item('sync_binding', 'Recorded binding', 'look', 'screened: no render receipt')
    elif binding in ('overridden', 'unverified'):
        entry = item('sync_binding', 'Recorded binding', 'look', f'{binding}: {reason or "reason not recorded"}')
    else:
        entry = item('sync_binding', 'Not assessed: binding', 'skip', 'no recognized binding recorded')
    for key in ('render_trace', 'cues_provenance', 'receipt'):
        if identity.get(key) is not None:
            entry['detail'] += f'; {key}: {identity[key]}'
    entry['group'] = 'sync'
    return entry


def cue_contract_items(data, freshness, required=False):
    """Report cue identity and turn decisions without treating plans as bound."""
    if data is None:
        entry = item('sync_cues', 'Cue list' if required else 'Not assessed: cue list',
                     'fail' if required else 'skip', 'required cue list missing' if required else 'no cue list')
        entry['group'] = 'sync'
        return [entry]
    if freshness == 'stale':
        entry = item('sync_cues', 'Cue list', 'fail', 'stale: re-export')
        entry['group'] = 'sync'
        return [entry]
    if freshness == 'unbound':
        entry = item('sync_cues', 'Not assessed: cue list', 'skip',
                     'plan is not yet bound to a picture; open item: register the master before delivery')
        entry['group'] = 'sync'
        return [entry]
    state = 'pass' if freshness == 'fresh' else 'look'
    entry = item('sync_cues', 'Cue list', state, str(freshness or 'freshness not established'))
    entry['group'] = 'sync'
    events = data.get('events', []) if isinstance(data, dict) else []
    missing = [str(event.get('id', '?')) for event in events if isinstance(event, dict)
               and event.get('scale') == 'turn' and not str(event.get('decision') or '').strip()]
    turns = [event for event in events if isinstance(event, dict) and event.get('scale') == 'turn']
    fps = number(data.get('fps')) if isinstance(data, dict) else None

    def turn_time(turn):
        at = number(turn.get('t'))
        frame = number(turn.get('frame'))
        return at if at is not None else frame / fps if frame is not None and fps and fps > 0 else None

    sections = data.get('sections', []) if isinstance(data, dict) else []
    for section in sections[1:] if isinstance(sections, list) else []:
        if not isinstance(section, dict) or section.get('decision'):
            continue
        at = number(section.get('a'))
        if at is not None and not any(turn_time(turn) is not None and abs(turn_time(turn) - at) < 1e-6
                                      for turn in turns):
            missing.append('section ' + str(section.get('id', '?')))
    decision = item('sync_turn_decisions', 'Turn decisions', 'look' if missing else 'pass',
                    'missing: ' + ', '.join(missing) if missing else f'{len(turns)} turn decisions recorded')
    decision['group'] = 'sync'
    return [entry, decision]


def sync_measurement_items(measurements):
    """Keep picture and sound measures separate, including their unassessed parts."""
    data = measurements if isinstance(measurements, dict) else {}
    entries = []

    def add(key, label, state, detail, measurement=None, at=None):
        row = item(key, label, state, detail, at)
        row['group'] = 'sync'
        if measurement is not None:
            row['measurement'] = measurement
        entries.append(row)

    frames = data.get('frame_change_at_cue') or {}
    frame_rows = frames.get('rows') or []
    if not frame_rows:
        add('sync_frame_0', 'Not assessed: frame change at cue', 'skip',
            frames.get('reason') or 'no cue frame was measured')
    for index, row in enumerate(frame_rows):
        state = {'change': 'pass', 'look': 'look'}.get(row.get('state'), 'skip')
        label = ('Not assessed: ' if state == 'skip' else '') + 'Frame change at cue ' + str(row.get('id', index))
        detail = row.get('reason') or ('a change occurred; its meaning needs a person' if state == 'pass' else
                                      'no qualifying frame change at this cue')
        add('sync_frame_' + str(index), label, state, detail, row, row.get('t'))

    sound = data.get('sound_follows_list') or {}
    summary = sound.get('summary') or {}
    definite = ('missing', 'LATE', 'EARLY', 'UNEXPECTED SOUND', 'outside audio', 'RESIDUAL')
    failures = [row for row in sound.get('rows', []) if row.get('status') in definite
                and row.get('sound') != 'optional']
    if failures:
        state = 'look'
    elif sound.get('state') == 'measured':
        state = 'look' if summary.get('failures') else 'pass'
    else:
        state = 'skip'
    label = ('Not assessed: ' if state == 'skip' else '') + 'Sound follows the list'
    detail = sound.get('reason') or json.dumps(summary, ensure_ascii=False)
    add('sync_sound_follows_list', label, state, detail, sound)

    leads = data.get('turn_leads') or []
    if leads:
        add('sync_turn_leads', 'Turn leads measured', 'pass',
            f'{len(leads)} measured; compare each with its declared lead', leads)
    else:
        add('sync_turn_leads', 'Not assessed: turn leads', 'skip', 'no turn lead was measured')
    for index, row in enumerate(data.get('follow') or []):
        assessed = row.get('state') == 'screening'
        label = ('Follow screen (uncalibrated null) ' if assessed else 'Not assessed: follow screen ') + str(row.get('id', index))
        detail = row.get('reason') or json.dumps({key: row.get(key) for key in
            ('state', 'best_r', 'lag_s', 'n', 'seed', 'null_iterations', 'null_p95', 'null_spread', 'null_note')},
            ensure_ascii=False)
        add('sync_follow_' + str(index), label, 'pass' if assessed else 'skip', detail, row)
    for index, row in enumerate(data.get('silence') or []):
        add('sync_silence_' + str(index), 'Not assessed: silence scope ' + str(row.get('id', index)), 'skip',
            row.get('reason') or 'full audio level does not establish bus scope or allowed tails', row,
            row.get('start_s'))
    return entries


def version_schedule_path(folder, name):
    """A version's timing file must resolve within that version."""
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise ValueError('the version timing file must be a relative path')
    root = Path(folder).resolve()
    path = (root / name).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError('the version timing file resolves outside the version') from None
    return path


def version_picture_items(folder, video, identity, cue_list):
    """Compare the version's actual picture packets and schedule with its manifest."""
    folder, video = Path(folder), Path(video)
    master = folder / 'preview.mp4'
    expected = identity.get('picture_sha256')
    timing = identity.get('picture_timing') or {}
    label, state, detail = 'Not assessed: version picture identity', 'skip', 'no picture identity recorded'
    actual = None
    if expected and master.is_file():
        try:
            actual = cue_list.picture_identity(master)
            if actual['sha256'] != expected:
                label, state, detail = 'Version picture identity', 'fail', 'picture packets differ from the manifest'
            elif not timing.get('pts_file') or not actual.get('schedule'):
                detail = 'picture packets match; the recorded or actual frame schedule is unavailable'
            else:
                schedule_path = version_schedule_path(folder, timing['pts_file'])
                recorded = cue_list.read_schedule(schedule_path, timing.get('pts_sha256'))
                if recorded is None:
                    detail = 'picture packets match; the recorded frame schedule is missing'
                else:
                    change = cue_list.compare_schedules(recorded, actual['schedule'], timing.get('fps_exact'))
                    label, state = 'Version picture packets and timing', 'fail' if change else 'pass'
                    detail = change or 'packet hash and presentation schedule match the manifest'
        except ValueError as error:
            if str(error).startswith('stale'):
                label, state, detail = 'Version picture identity', 'fail', str(error)
            else:
                label, state, detail = 'Not assessed: version picture identity', 'skip', str(error)
        except (OSError, RuntimeError, KeyError) as error:
            label, state, detail = 'Not assessed: version picture identity', 'skip', str(error)
    row = item('sync_picture_identity', label, state, detail)
    row['group'] = 'sync'
    rows = [row]
    geometry = identity.get('geometry') or identity.get('picture_geometry')
    if not isinstance(geometry, dict) or not geometry:
        row = item('sync_picture_geometry', 'Not assessed: version display geometry', 'skip',
                   'the manifest records no geometry for comparison')
    elif actual is None or not actual.get('geometry'):
        row = item('sync_picture_geometry', 'Not assessed: version display geometry', 'skip',
                   'the actual master display geometry could not be read')
    else:
        status, reason = cue_list.geometry_compare(geometry, actual.get('geometry'))
        result = {'equal': 'pass', 'changed': 'fail', 'unverified': 'look'}.get(status, 'skip')
        row = item('sync_picture_geometry', 'Version display geometry', result,
                   reason or 'display geometry matches the manifest')
    row['group'] = 'sync'
    rows.append(row)
    if actual is not None and master.is_file() and not P.same_file(video, master):
        try:
            delivered = cue_list.picture_identity(video)
            if delivered['sha256'] != actual['sha256']:
                state, detail = 'look', 'delivered picture packets differ; a re-encode or edit needs picture review'
            elif not actual.get('schedule') or not delivered.get('schedule'):
                state, detail = 'skip', 'a picture schedule is unavailable'
            elif not actual.get('geometry') or not delivered.get('geometry'):
                state, detail = 'skip', 'a display geometry is unavailable'
            else:
                change = cue_list.compare_schedules(actual['schedule'], delivered['schedule'], timing.get('fps_exact'))
                status, reason = cue_list.geometry_compare(actual.get('geometry'), delivered.get('geometry'))
                if change or status == 'changed':
                    state, detail = 'fail', change or reason
                elif status == 'unverified':
                    state, detail = 'look', reason
                else:
                    state, detail = 'pass', 'picture packets, timing and display geometry match the version master'
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            state, detail = 'skip', str(error)
        row = item('sync_delivered_picture', ('Not assessed: ' if state == 'skip' else '') +
                   'delivered picture against master', state, detail)
        row['group'] = 'sync'
        rows.append(row)
    return rows


def mux_origin_item(master, video, cue_list, report):
    """Compare picture movement with audio movement on the container clock."""
    def result(state, detail, measurement=None):
        label = ('Not assessed: ' if state == 'skip' else '') + 'picture-to-audio mux offset'
        row = item('sync_mux_origin', label, state, detail)
        row['group'] = 'sync'
        if measurement is not None:
            row['measurement'] = measurement
        return row

    summary = (report or {}).get('summary') or {}
    verdict = summary.get('verdict', '')
    if verdict != 'consistent with the reference within tolerance' and not verdict.startswith('constant offset'):
        return result('skip', 'audio transport could not be aligned to the version master')
    try:
        reference = cue_list.picture_identity(master)
        delivered = cue_list.picture_identity(video)
        first, second = reference.get('schedule'), delivered.get('schedule')
        if not first or not second or not first.get('pts_us') or not second.get('pts_us'):
            return result('skip', 'picture packet timestamps are unavailable')

        def audio_start(path):
            stream = next((row for row in probe_media(path).get('streams', [])
                           if row.get('codec_type') == 'audio'), None)
            if stream is None:
                raise ValueError('an audio stream is missing')
            value = float(stream['start_time'])
            if not math.isfinite(value):
                raise ValueError('audio stream origin is not finite')
            return value

        picture_shift_ms = cue_list.schedule_shift_us(first, second) / 1000
        audio_timestamp_shift_ms = (audio_start(video) - audio_start(master)) * 1000
        audio_content_shift_ms = float(summary['median_lag_ms'])
        if not math.isfinite(audio_content_shift_ms):
            raise ValueError('audio content offset is unavailable')
        difference_ms = picture_shift_ms - audio_timestamp_shift_ms - audio_content_shift_ms
        tolerance_ms = cue_list.tolerance_us(first.get('fps_exact')) / 1000
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, StopIteration) as error:
        return result('skip', str(error) or 'stream timing is unavailable')
    state = 'pass' if abs(difference_ms) <= tolerance_ms else 'fail'
    measurement = {'picture_shift_ms': round(picture_shift_ms, 3),
                   'audio_timestamp_shift_ms': round(audio_timestamp_shift_ms, 3),
                   'audio_content_shift_ms': round(audio_content_shift_ms, 3),
                   'relative_shift_ms': round(difference_ms, 3), 'tolerance_ms': round(tolerance_ms, 3)}
    return result(state, f'picture relative to sound moved {difference_ms:+.3f} ms; '
                  f'tolerance {tolerance_ms:.3f} ms', measurement)


def version_receipt_item(folder, manifest):
    """Check a receipt only when its bytes are recorded inside the version."""
    identity = manifest.get('identity') if isinstance(manifest.get('identity'), dict) else {}
    source = identity.get('source') if isinstance(identity.get('source'), dict) else {}
    name = identity.get('receipt')
    if not name:
        return None
    state, detail = 'skip', 'the receipt path is not bound to bytes in the version'
    files = manifest.get('files') if isinstance(manifest.get('files'), dict) else {}
    try:
        path = version_schedule_path(folder, name)
        expected = files.get(Path(name).as_posix())
        if expected:
            state = 'fail'
            if not path.is_file():
                state, detail = 'fail', 'the recorded receipt is missing or its bytes changed'
            else:
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != expected:
                    raise ValueError('stale: the recorded receipt bytes changed')
                receipt = json.loads(content.decode('utf-8-sig'))
                if not isinstance(receipt, dict):
                    state, detail = 'fail', 'the recorded receipt is not a JSON object'
                else:
                    comparisons = [('source_fingerprint', source.get('sha256')),
                                   ('snapshot_sha256', source.get('snapshot_sha256')),
                                   ('cues_sha256', identity.get('cues_sha256')),
                                   ('picture_sha256', identity.get('picture_sha256')),
                                   ('render_trace', identity.get('render_trace')),
                                   ('binding', identity.get('binding'))]
                    mismatch = [key for key, value in comparisons if value is not None
                                and key in receipt and receipt[key] != value]
                    missing = [key for key, value in comparisons[:5] if value is not None and key not in receipt]
                    if mismatch:
                        state, detail = 'fail', 'receipt differs from the version: ' + ', '.join(mismatch)
                    elif missing:
                        state, detail = 'look', 'receipt lacks fields for comparison: ' + ', '.join(missing)
                    else:
                        state, detail = 'pass', 'recorded receipt bytes and available identity fields match'
    except (OSError, ValueError, TypeError) as error:
        detail = (str(error) or detail) if state == 'fail' else 'the receipt is outside the version or its path is invalid'
    row = item('sync_receipt', ('Not assessed: ' if state == 'skip' else '') + 'render receipt', state, detail)
    row['group'] = 'sync'
    return row


def attached_bus_names(files, role):
    """The attached copies of a mixer bus recorded in the version's files map."""
    if role not in ('music', 'effects', 'bed'):
        return []
    pattern = re.compile(r'^stems/attached-' + re.escape(role) + r'(?:-\d+)?\.wav$')
    return sorted(name for name in files if isinstance(name, str) and pattern.fullmatch(name))


def retained_stem_name(name):
    """A retained stem name must stay inside the version's stems folder."""
    return (isinstance(name, str) and name not in ('', '.', '..') and '/' not in name and '\\' not in name
            and ':' not in name
            and not Path(name).is_absolute())


def attached_mix_report(folder, mix, files):
    """Read the report only when its bytes match the version and the mix record."""
    report_path = version_schedule_path(folder, 'attached-mix-report.json')
    expected = mix.get('report_sha256')
    if not expected or files.get('attached-mix-report.json') != expected or not report_path.is_file():
        raise ValueError('the attached mixer report is missing or its hash differs')
    content = report_path.read_bytes()
    if hashlib.sha256(content).hexdigest() != expected:
        raise ValueError('the attached mixer report is missing or its hash differs')
    report = json.loads(content.decode('utf-8-sig'))
    if not isinstance(report, dict) or report.get('exit_code') != 0:
        raise ValueError('the attached mixer report is invalid or did not pass')
    return report


def conform_evidence(identity, mix_report, verify_media=True):
    """Assess a conform using the mixer report's hash-indexed input paths."""
    refs = []
    if not isinstance(mix_report, dict):
        return 'skip', 'no verified mixer report provides conform inputs', refs
    inputs = mix_report.get('inputs') if isinstance(mix_report.get('inputs'), dict) else {}
    conform_hash, bed_hash = inputs.get('conform'), inputs.get('music')
    if not conform_hash:
        return 'skip', 'the mixer report records no conform report', refs
    files = inputs.get('files') if isinstance(inputs.get('files'), dict) else {}

    def paths_for(role, expected):
        paths = []
        if not isinstance(expected, str) or not expected:
            return paths
        for raw, value in files.items():
            if not isinstance(raw, str) or value != expected:
                continue
            path = Path(raw)
            if path.is_absolute():
                paths.append(path)
                refs.append((role, path))
        return paths

    def match(paths, expected, label, content=False):
        if not paths:
            return None, 'skip', f'the mixer report records no {label} path'
        mismatch = False
        for path in paths:
            try:
                if not path.is_file():
                    continue
                value = path.read_bytes() if content else None
                digest = hashlib.sha256(value).hexdigest() if content else P.file_sha256(path)
                if digest == expected:
                    return value if content else path, None, None
                mismatch = True
            except (OSError, ValueError):
                continue
        if mismatch:
            return None, 'fail', f'the {label} bytes differ from the mixer report'
        return None, 'skip', f'the recorded {label} path is unavailable'

    report_paths = paths_for('conform_report', conform_hash)
    bed_paths = paths_for('conform_bed', bed_hash)
    content, state, detail = match(report_paths, conform_hash, 'conform report', content=True)
    if state:
        return state, detail, refs
    try:
        conform = json.loads(content.decode('utf-8-sig'))
    except (ValueError, UnicodeError):
        return 'fail', 'the conform report is not readable JSON', refs
    if not isinstance(conform, dict):
        return 'fail', 'the conform report is not a JSON object', refs
    source_hash = conform.get('music_sha256')
    source_paths = paths_for('conform_source', source_hash)
    if not verify_media:
        return 'skip', 'conform input paths recorded', refs
    if identity.get('conform_sha256') and identity['conform_sha256'] != conform_hash:
        return 'fail', 'the version and mixer name different conform reports', refs
    if conform.get('binding') != 'bound' or not identity.get('cues_sha256') \
            or conform.get('cues_sha256') != identity.get('cues_sha256') \
            or inputs.get('cues') != identity.get('cues_sha256'):
        return 'fail', 'the conform and mixer do not bind the version cue list', refs
    if not bed_hash or conform.get('bed_sha256') != bed_hash or not source_hash:
        return 'fail', 'the conform and mixer do not bind the same source and bed', refs
    for paths, expected, label in ((bed_paths, bed_hash, 'conformed bed'),
                                   (source_paths, source_hash, 'source music')):
        _, state, detail = match(paths, expected, label)
        if state:
            return state, detail, refs
    return 'pass', 'conform report, cue list, source music and bed match recorded hashes; unheard', refs


def version_mix_items(folder, manifest):
    """Verify the attached mixer report and the copied buses and retained stems when present."""
    folder = Path(folder)
    identity = manifest.get('identity') if isinstance(manifest.get('identity'), dict) else {}
    mix = identity.get('mix') if isinstance(identity.get('mix'), dict) else manifest.get('mix')
    files = manifest.get('files') if isinstance(manifest.get('files'), dict) else {}

    def row(key, state, detail):
        result = item('sync_' + key, ('Not assessed: ' if state == 'skip' else '') + key, state, detail)
        result['group'] = 'sync'
        return result

    if not isinstance(mix, dict):
        return [row('mix', 'skip', 'no mixer report and media are bound here'),
                row('masking', 'skip', 'no bound masking decisions were supplied')], None
    if not isinstance(mix.get('buses'), dict) or not isinstance(mix.get('stems'), dict):
        return [row('mix', 'skip', 'the version records mix hashes but no report and sound paths to verify'),
                row('masking', 'skip', 'the registered mixer report path is not bound')], None
    try:
        if isinstance(manifest.get('mix'), dict) and manifest['mix'] != mix:
            raise ValueError('the two mix records differ')
        report = attached_mix_report(folder, mix, files)
        inputs = report.get('inputs') if isinstance(report.get('inputs'), dict) else {}
        outputs = report.get('outputs') if isinstance(report.get('outputs'), dict) else {}
        cue_hash = mix.get('cues_sha256')
        if not cue_hash or cue_hash != identity.get('cues_sha256') or inputs.get('cues') != cue_hash:
            raise ValueError('the mixer report and version do not bind the same cue list')
        if not mix['buses']:
            raise ValueError('the attached mix records no processed buses')
        for role, expected in mix['buses'].items():
            names = attached_bus_names(files, role)
            candidates = [name for name in names if files.get(name) == expected]
            if not expected or outputs.get(role + '.wav') != expected or not candidates:
                raise ValueError(f'the {role} bus is not bound by the report and version')
            paths = [version_schedule_path(folder, name) for name in candidates]
            if not any(path.is_file() and P.file_sha256(path) == expected for path in paths):
                raise ValueError(f'the attached {role} bus is missing or its hash differs')
        for name, entry in mix['stems'].items():
            if not retained_stem_name(name) or not isinstance(entry, dict):
                raise ValueError('a retained stem record is invalid')
            rel = 'stems/' + name + '.wav'
            expected = entry.get('sha256')
            path = version_schedule_path(folder, rel)
            if not expected or files.get(rel) != expected or not path.is_file() \
                    or P.file_sha256(path) != expected:
                raise ValueError(f'the retained stem {name} is missing or its hash differs')
        dialogue = mix['stems'].get('dialogue')
        if not isinstance(dialogue, dict) or not mix.get('voice_reference') \
                or mix['voice_reference'] != dialogue.get('sha256'):
            raise ValueError('the voice reference differs from the retained dialogue stem')
        voices = inputs.get('voice')
        if not isinstance(voices, list) or len(voices) != 1 or not isinstance(voices[0], dict) \
                or voices[0].get('sha256') != mix['voice_reference'] \
                or voices[0].get('at_s') != 0 or voices[0].get('gain_db') != 0:
            raise ValueError('the mixer report does not bind the retained dialogue at its original time and gain')
    except (OSError, ValueError, TypeError) as error:
        return [row('mix', 'fail', str(error)),
                row('masking', 'skip', 'the attached mixer report and media could not be verified')], None
    mix_row = row('mix', 'pass', f"report, {len(mix['buses'])} buses and {len(mix['stems'])} retained stems "
                  'match their recorded hashes and cue list; unheard')
    pairs = report.get('masking')
    if not isinstance(pairs, list):
        masking = row('masking', 'skip', 'the bound mixer report has no masking candidates list')
    elif pairs:
        names = [', '.join(str(value) for value in pair.get('ids', []))
                 if isinstance(pair, dict) and isinstance(pair.get('ids'), list) else 'unnamed pair' for pair in pairs]
        masking = row('masking', 'look', 'candidate pairs: ' + '; '.join(names) + '; a person must listen')
    else:
        masking = row('masking', 'pass', 'no masking candidates recorded; a person must listen')
    return [mix_row, masking], report


def project_sync_items(folder, video, manifest, required=False):
    """Check a version's cue identity, then attach distinct listening measures."""
    folder, video = Path(folder), Path(video)
    identity = manifest.get('identity') if isinstance(manifest.get('identity'), dict) else {}
    source_expected = identity.get('cues_sha256')
    registered_name = identity.get('cues') if identity.get('registered') is True else None
    files = manifest.get('files') if isinstance(manifest.get('files'), dict) else {}
    path_error = None
    if registered_name in ('cues.json', 'edit-cues.json'):
        # Registration may rewrite the stored list's picture path or bind a plan. The source hash is retained in
        # identity; the version's files map records the bytes of its own copy.
        expected = files.get(registered_name)
        try:
            candidates = [version_schedule_path(folder, registered_name)]
        except (OSError, ValueError) as error:
            candidates, path_error = [], str(error)
    else:
        expected = source_expected
        candidates = [folder / 'cues.json', folder / 'edit-cues.json']
    present = [path for path in candidates if path.is_file()]
    matched = [path for path in present if expected and P.file_sha256(path) == expected]
    selected = matched[0] if matched else present[0] if len(present) == 1 else None
    rows, transcript = [], None
    INVOKED.add('cue_list.py')
    spec = importlib.util.spec_from_file_location('lf_check_cue_list', HERE / 'cue_list.py')
    cue_list = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cue_list)
    rows += version_picture_items(folder, video, identity, cue_list)
    data, state = None, None
    if path_error:
        entry = item('sync_cues', 'Cue list', 'fail', path_error)
        entry['group'] = 'sync'
        rows.append(entry)
    elif expected and present and not matched:
        state = 'stale'
        data = {}
    elif len(present) > 1 and not matched:
        entry = item('sync_cues', 'Cue list', 'look', 'more than one cue list; the version does not select one')
        entry['group'] = 'sync'
        rows.append(entry)
    elif selected:
        try:
            listed = cue_list.check(selected, owner=folder)
            if expected and listed.sha256 != expected:
                raise ValueError('stale: cue-list bytes changed during the check; re-export')
            provenance = identity.get('cues_provenance')
            if listed.version == 'v2' and provenance and provenance != listed.provenance:
                raise ValueError('stale: cue provenance differs from the version manifest; re-export')
            if listed.version == 'v1':
                validator_spec = importlib.util.spec_from_file_location('lf_check_cue_onsets', HERE / 'cue_onsets.py')
                validator = importlib.util.module_from_spec(validator_spec)
                validator_spec.loader.exec_module(validator)
                INVOKED.add('cue_onsets.py')
                _, _, problems = validator.validate(listed.doc)
                if problems:
                    raise ValueError('the legacy cue list cannot be checked: ' + '; '.join(problems))
            data = dict(listed.doc) if isinstance(listed.doc, dict) else {'events': listed.events}
            if listed.fps is not None:
                data['fps'] = listed.fps
            state = listed.state
            if state == 'fresh' and (not expected or not source_expected):
                state = 'unverified: the version records no cue-list hash'
            contract = cue_contract_items(data, state, required)
            contract[0]['detail'] = listed.message if state == listed.state else state
            rows += contract
        except (OSError, ValueError, RuntimeError) as error:
            entry = item('sync_cues', 'Cue list', 'fail', str(error))
            entry['group'] = 'sync'
            rows.append(entry)
    else:
        rows += cue_contract_items(None, None, required or bool(source_expected))
    if state == 'stale' and not any(row['id'] == 'sync_cues' for row in rows):
        contract = cue_contract_items(data, state, required)
        contract[0]['detail'] = 'stale: the cue-list bytes differ from the version; re-export'
        rows += contract

    if selected and state not in (None, 'stale', 'unbound'):
        code, output = run_script('listen.py', 'sync', video, '--cues', selected, '--owner', folder, '--json')
        try:
            measured = json.loads(output) if code == 0 else None
        except ValueError:
            measured = None
        if isinstance(measured, dict):
            rows += sync_measurement_items(measured)
            INVOKED.add('cue_onsets.py')
        else:
            row = item('sync_measurements', 'Not assessed: cue measurements', 'skip',
                       why_not_run('listen.py sync', code, output))
            row['group'] = 'sync'
            rows.append(row)
    else:
        row = item('sync_measurements', 'Not assessed: cue measurements', 'skip',
                   'no fresh or readable bound cue list')
        row['group'] = 'sync'
        rows.append(row)

    code, output = run_script('listen.py', 'transcript', video, '--json')
    try:
        transcript = json.loads(output) if code == 0 else None
    except ValueError:
        transcript = None
    if isinstance(transcript, dict):
        row = item('sync_transcript', 'Listening transcript measured', 'pass',
                   f"{len(transcript.get('events') or [])} onsets and "
                   f"{len(transcript.get('sections') or [])} level changes; a person must listen")
        INVOKED.add('tempo_map.py')
    else:
        row = item('sync_transcript', 'Not assessed: listening transcript', 'skip',
                   why_not_run('listen.py transcript', code, output))
    row['group'] = 'sync'
    rows.append(row)

    master = folder / 'preview.mp4'
    report = None
    if master.is_file() and not P.same_file(video, master):
        with tempfile.TemporaryDirectory(prefix='lf-check-master-') as temp:
            report_path = Path(temp) / 'sync.json'
            report, why = run_report('sync_check.py', [video, master, '--json', report_path], report_path)
        verdict = (report or {}).get('summary', {}).get('verdict', '')
        if verdict == 'consistent with the reference within tolerance':
            state = 'pass'
        elif not report or verdict.startswith('inconclusive'):
            state = 'skip'
        else:
            state = 'look'
        row = item('sync_master', ('Not assessed: ' if state == 'skip' else '') + 'Transport against version master',
                   state, verdict or why or 'transport not established')
        if report:
            row['measurement'] = report
    else:
        row = item('sync_master', 'Not assessed: transport against master', 'skip',
                   'the checked file is the version master; no independent master supplied')
    row['group'] = 'sync'
    rows.append(row)
    if master.is_file() and not P.same_file(video, master):
        rows.append(mux_origin_item(master, video, cue_list, report))
    else:
        row = item('sync_mux_origin', 'Not assessed: picture-to-audio mux offset', 'skip',
                   'the checked file is the version master; no independent master supplied')
        row['group'] = 'sync'
        rows.append(row)
    receipt = version_receipt_item(folder, manifest)
    if receipt is not None:
        rows.append(receipt)
    mix_rows, mix_report = version_mix_items(folder, manifest)
    cue_row = next((entry for entry in rows if entry['id'] == 'sync_cues'), None)
    cue_state = cue_row.get('state') if cue_row else 'skip'
    if mix_rows[0]['state'] == 'pass' and cue_state != 'pass':
        mix_state = 'fail' if cue_state == 'fail' else 'skip'
        mix_rows[0] = item('sync_mix', ('Not assessed: ' if mix_state == 'skip' else '') + 'mix', mix_state,
                           'the version cue list is not fresh, so the attached mix is not bound')
        mix_rows[0]['group'] = 'sync'
        mix_rows[1] = item('sync_masking', 'Not assessed: masking', 'skip',
                           'the attached mix is not bound to a fresh cue list')
        mix_rows[1]['group'] = 'sync'
    conform_state, detail, _ = conform_evidence(identity, mix_report)
    if conform_state == 'pass' and cue_state != 'pass':
        conform_state = 'fail' if cue_state == 'fail' else 'skip'
        detail = 'the version cue list is not fresh, so the conform is not bound'
    row = item('sync_conform', ('Not assessed: ' if conform_state == 'skip' else '') + 'conform',
               conform_state, detail)
    row['group'] = 'sync'
    rows.append(row)
    rows += mix_rows
    return rows, transcript


def summarise(items):
    """Counts per state."""
    summary = {state: 0 for state in ('pass', 'look', 'fail', 'you', 'skip', 'unconfirmed')}
    for entry in items:
        summary[entry['state']] += 1
    return summary


def publish(fresh, qa, prefix):
    """Copy this run's raw outputs into qa/ and remove the previous run's outputs that this run did not produce."""
    qa.mkdir(parents=True, exist_ok=True)
    for name in QA_FILES:
        made, kept = fresh / name, qa / (prefix + name)
        if made.is_file():
            shutil.copyfile(made, kept)
        elif kept.is_file():
            kept.unlink()


def scan_items(video, fresh, declared=None):
    """Flashing and near-empty frames, each from a report this run wrote."""
    items = []
    for name, builder in (('flash_scan.py', flash_item), ('blank_scan.py', blank_item)):
        out = fresh / name.replace('.py', '.json')
        args = [video, '--json', out]
        if name == 'blank_scan.py' and declared:
            args += ['--ignore', declared]
        report, why = run_report(name, args, out)
        key = name.replace('_scan.py', '')
        items.append(builder(report) if report is not None else item(key, name, 'skip', why))
    return items


def has_audio_stream(video):
    """Whether the file has a sound stream. When ffprobe cannot answer, assume it does, so qc_file.py runs the sound
    checks and reports why they failed instead of them being left out."""
    ffprobe = shutil.which('ffprobe')
    if ffprobe is None:
        return True
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                             '-of', 'csv=p=0', str(video)], capture_output=True, text=True)
    return result.returncode != 0 or bool(result.stdout.strip())


def run_checks(video, qa=None, spec=None, duration=None, final=False, target=DEFAULT_LOUDNESS, reviewed=None,
               captions_folder=None, speech=None, expected_frames=None, bars_allowed=False, vcodec='h264',
               pix_fmt='yuv420p', color='bt709', captions_check=None, fps=None, duration_independent=False,
               faststart=True):
    """Run the checks for one file in a fresh folder and return the checks.json content; with `qa`, this run's raw
    outputs replace the previous run's there. `speech` is (model, language) to compare captions with the audio.
    `captions_check(video, fresh, has_audio)` returns the caption items when given (--file and a final's sidecar);
    otherwise a project version's own captions are checked. Items not assessed are labelled so."""
    if target is not None and not math.isfinite(target):
        raise ValueError('loudness target must be finite')
    with tempfile.TemporaryDirectory(prefix='lf-check-') as name:
        fresh = Path(name)
        qc_args = [video, '--json', fresh / 'qc.json', '--technical']
        for option, value in (('--vcodec', vcodec), ('--pix-fmt', pix_fmt), ('--color', color)):
            if value:
                qc_args += [option, value]
        if spec:
            qc_args += ['--spec', spec]
        if fps:
            qc_args += ['--fps', str(fps)]
        if expected_frames is None and duration is not None and spec and '@' in spec and not duration_independent:
            expected_frames = round(Fraction(str(duration)) * Fraction(spec.rsplit('@', 1)[1]))
        if expected_frames is not None:
            qc_args += ['--frames', str(expected_frames)]
        if duration is not None and (duration_independent or expected_frames is None):
            qc_args += ['--duration', f'{duration:.6f}']
        if final:
            # The re-encode true peak needs sound; a silent final has nothing to clip.
            if has_audio_stream(video):
                qc_args.append('--lossy-check')
            if faststart:
                qc_args.append('--faststart')
        qc, why = run_report('qc_file.py', qc_args, fresh / 'qc.json')
        if qc is None:
            raise RuntimeError(why)
        has_audio = bool(qc.get('audio'))
        basis = ', '.join(part for part in (
            spec and f'{spec}', vcodec and f'{vcodec.upper().replace("H264", "H.264")}', pix_fmt,
            color and f'{color.upper()} tags', 'fast start' if final and faststart else '') if part)
        basis += ' (the web defaults unless --delivery or the flags name another)' if final and not spec and faststart else ''
        items = [spec_item(qc, basis)] + loudness_items(qc, target, final, has_audio)
        streams = audio_streams_item(qc)
        if streams:
            items.append(streams)
        declaration = P.load_json(captions_folder / 'declared.json', {}) if captions_folder else {}
        items.append(first_frame_item(video, declaration))
        edges = edges_item(qc, has_audio, sound_past_picture(captions_folder, expected_frames))
        if edges:
            items.append(edges)
        dropouts = dropout_item(video, has_audio, qc.get('audio_selector', '0:a:0'))
        if dropouts:
            items.append(dropouts)
        P.save_json(fresh / 'technical.json', qc.get('technical') or {})
        items += technical_items(qc, declaration or {}, bars_allowed, final)
        items += scan_items(video, fresh, (declaration or {}).get('ignore'))
        if captions_check is not None:
            captions = captions_check(video, fresh, has_audio)
        else:
            captions = caption_items(captions_folder, video, fresh, speech, has_audio) if captions_folder else []
        items += captions
        titles = title_contrast_item(captions_folder, video, fresh) if captions_folder else None
        if titles:
            items.append(titles)
        items += person_items(reviewed, has_audio, any(entry['id'] == 'captions_rules' and not entry.get('empty')
                                                       for entry in captions))
        if qa is not None:
            publish(fresh, Path(qa), 'final-' if final else '')
    not_assessed(items)
    return {'version': 1, 'file': str(video), 'final': final, 'items': items, 'summary': summarise(items)}


def front_matter(path):
    """The simple key: value pairs of a film.md front matter block."""
    if not path.is_file():
        return {}
    lines = P.read_text(path).splitlines()
    if not lines or lines[0].strip() != '---':
        return {}
    values = {}
    for line in lines[1:]:
        if line.strip() == '---':
            break
        if ':' in line:
            key, value = line.split(':', 1)
            values[key.strip()] = value.split('#', 1)[0].strip()
    return values


def split_inline(text):
    """Split a flow-style YAML value without splitting quoted or nested commas."""
    result, start, depth, quote, escaped = [], 0, 0, None, False
    for i, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == '\\' and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char in '[{':
            depth += 1
        elif char in ']}':
            depth -= 1
        elif char == ',' and depth == 0:
            result.append(text[start:i].strip())
            start = i + 1
        if depth < 0:
            raise ValueError('unbalanced frame value')
    if quote or depth:
        raise ValueError('unbalanced frame value')
    result.append(text[start:].strip())
    return result


def frame_scalar(text):
    text = text.strip()
    quote, escaped = None, False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == '\\' and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == '#' and (index == 0 or text[index - 1].isspace()):
            text = text[:index].rstrip()
            break
    if not text or text in ('null', 'Null', 'NULL', '~'):
        return None
    if text.startswith('{') and text.endswith('}'):
        result = {}
        for part in split_inline(text[1:-1]):
            if not part or ':' not in part:
                raise ValueError('invalid frame map')
            key, value = part.split(':', 1)
            key = key.strip()
            if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', key) or key in result:
                raise ValueError('invalid or repeated frame key')
            result[key] = frame_scalar(value)
        return result
    if text.startswith('[') and text.endswith(']'):
        return [frame_scalar(part) for part in split_inline(text[1:-1])] if text[1:-1].strip() else []
    if text.startswith('"'):
        return json.loads(text)
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1].replace("''", "'")
    if text[0] in '|>&*!':
        raise ValueError('unsupported frame scalar')
    if re.fullmatch(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)', text):
        return float(text)
    return text


def project_path_name(path):
    """Read only the top-level path declaration from film.md."""
    path = Path(path)
    if not path.is_file():
        return None
    lines = P.read_text(path).splitlines()
    if not lines or lines[0].strip() != '---':
        return None
    values = []
    for line in lines[1:]:
        if line.strip() == '---':
            break
        match = re.match(r'^path\s*:\s*(.*)$', line)
        if match:
            try:
                values.append(frame_scalar(match.group(1)))
            except ValueError:
                return None
    return values[0] if len(values) == 1 and isinstance(values[0], str) else None


def read_frame(path):
    """Read the frame subset of front matter, leaving unsupported forms unconfirmed."""
    path = Path(path)
    if not path.is_file():
        return {}
    lines = P.read_text(path).splitlines()
    if not lines or lines[0].strip() != '---':
        return {}
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == '---')
        matches = [i for i in range(1, end) if re.match(r'^frame\s*:', lines[i])]
        if len(matches) != 1:
            return {}
        first = matches[0]
        inline = lines[first].split(':', 1)[1].strip()
        if inline:
            parsed = frame_scalar(inline)
            return parsed if isinstance(parsed, dict) else {}
        frame, key, indent = {}, None, None
        for line in lines[first + 1:end]:
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            prefix = len(line) - len(line.lstrip(' '))
            if prefix == 0:
                break
            if '\t' in line[:prefix + 1]:
                raise ValueError('tabs in frame indentation')
            if indent is None:
                indent = prefix
            content = line.strip()
            if prefix == indent:
                if ':' not in content:
                    raise ValueError('invalid frame entry')
                key, value = content.split(':', 1)
                key = key.strip()
                if key in frame:
                    raise ValueError('repeated frame entry')
                frame[key] = frame_scalar(value) if value.strip() else ([] if key == 'knows_by' else {})
            elif prefix > indent and key in ('state', 'waived', 'cold_read', 'knows_by'):
                if key == 'knows_by':
                    if content.startswith('- '):
                        frame[key].append({})
                        content = content[2:].strip()
                    if not frame[key] or not isinstance(frame[key][-1], dict):
                        raise ValueError('invalid knows_by entry')
                    target = frame[key][-1]
                else:
                    target = frame[key]
                if not isinstance(target, dict) or ':' not in content:
                    raise ValueError('invalid nested frame entry')
                child, value = content.split(':', 1)
                child = child.strip()
                if child in target:
                    raise ValueError('repeated nested frame entry')
                target[child] = frame_scalar(value)
            else:
                raise ValueError('unsupported frame indentation')
        return frame
    except (ValueError, StopIteration, TypeError, json.JSONDecodeError):
        return {}


VERSION_INPUTS = (('lines', 'lines.json'), ('edit', 'edit.json'), ('film', 'film.md'), ('declared', 'declared.json'),
                  ('manifest', 'manifest.json'), ('caption_burn', 'caption-burn.json'), ('cues', 'cues.json'),
                  ('edit_cues', 'edit-cues.json'), ('picture_timing', 'picture-timing.json'))


def project_path(root, path):
    """A path as the project's checks record it: relative to the project folder, or absolute when outside it."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(Path(path).resolve())


def check_tool_inputs():
    """Scripts, interpreter and media tools that must never become a check output."""
    paths = list(HERE.glob('*.py')) + [HERE.parent / 'SKILL.md', sys.executable]
    paths += [path for path in (shutil.which('ffmpeg'), shutil.which('ffprobe')) if path]
    return paths


def title_assets(folder):
    """The resolved image files read by the version's title-contrast check, including absent files."""
    edit = P.load_json(folder / 'edit.json', {}) or {}
    sources = edit.get('sources') if isinstance(edit.get('sources'), dict) else {}
    paths = []
    for overlay in edit.get('overlays') or []:
        if not isinstance(overlay, dict) or overlay.get('kind') != 'image':
            continue
        name = overlay.get('src')
        if not isinstance(name, str) or not name.startswith('title-'):
            continue
        if not all(isinstance(overlay.get(key), (int, float)) for key in ('from', 'to')):
            continue
        source = sources.get(name) or {}
        file = source.get('file') if isinstance(source, dict) else None
        if isinstance(file, str) and file:
            path = folder / file
            if not any(P.same_file(path, other) for other in paths):
                paths.append(path)
    return paths


def cue_related_inputs(root, folder):
    """Record cue references and schedules a project check may read."""
    spec = importlib.util.spec_from_file_location('lf_check_inputs_cue_list', HERE / 'cue_list.py')
    cue_list = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cue_list)
    INVOKED.add('cue_list.py')
    found = []
    for path in (folder / 'cues.json', folder / 'edit-cues.json'):
        if not path.is_file():
            continue
        try:
            listed = cue_list.check(path, owner=folder)
        except (OSError, ValueError, RuntimeError):
            continue
        picture = listed.picture if isinstance(listed.picture, dict) else {}
        timing = picture.get('timing') if isinstance(picture.get('timing'), dict) else {}
        entries = [('cue_schedule', timing.get('pts_file'))]
        events = listed.events if isinstance(listed.events, list) else []
        entries += [('cue_reference', event.get('ref')) for event in events if isinstance(event, dict)]
        for role, name in entries:
            if not isinstance(name, str) or not name:
                continue
            reference = Path(name)
            if not reference.is_absolute():
                reference = path.parent / reference
            if not any(P.same_file(reference, prior) for _, prior in found):
                found.append((role, reference))
    return [P.input_row(role, path, project_path(root, path)) for role, path in found]


def hdr_items(manifest):
    """A look for each version made from HDR sources: the tone map changes how highlights read."""
    names = [row.get('alias', '?') for row in manifest.get('hdr_sources') or [] if isinstance(row, dict)]
    if not names:
        return []
    return [item('hdr_source', 'HDR source converted to SDR', 'look',
                 f"{', '.join(names)}: compare the highlights with the original")]


def project_inputs(root, folder, video, digest, final, captions, speech, profile=None, manifest=None):
    """The inputs a project check depends on: the checked file, the captions checked, the version's lines.json,
    edit.json, film.md, declared.json, manifest.json and caption-burn.json (recorded as absent when missing, so adding
    one expires the result), title assets, the map transcript candidates and listing used for speech settings, and
    the spatial layers the edit draws."""
    rows = [P.input_row('final' if final else 'preview', video, project_path(root, video), digest),
            P.input_row('captions', captions, project_path(root, captions))]
    rows += [P.input_row(role, folder / name, project_path(root, folder / name)) for role, name in VERSION_INPUTS]
    rows += cue_related_inputs(root, folder)
    identity = (manifest or {}).get('identity') or {}
    files = (manifest or {}).get('files') or {}
    if not isinstance(files, dict):
        files = {}
    receipt = identity.get('receipt') if isinstance(identity, dict) else None
    if receipt:
        try:
            path = version_schedule_path(folder, receipt)
            rows.append(P.input_row('render_receipt', path, project_path(root, path)))
        except (OSError, ValueError):
            pass
    mix = identity.get('mix') if isinstance(identity, dict) else None
    if not isinstance(mix, dict):
        mix = (manifest or {}).get('mix')
    if isinstance(mix, dict) and isinstance(mix.get('buses'), dict) and isinstance(mix.get('stems'), dict):
        try:
            report = version_schedule_path(folder, 'attached-mix-report.json')
            rows.append(P.input_row('mix_report', report, project_path(root, report)))
        except (OSError, ValueError):
            pass
        for role in mix['buses']:
            for name in attached_bus_names(files, role):
                try:
                    path = version_schedule_path(folder, name)
                    rows.append(P.input_row('mix_bus', path, project_path(root, path)))
                except (OSError, ValueError):
                    pass
        for name in mix['stems']:
            if retained_stem_name(name):
                try:
                    path = version_schedule_path(folder, 'stems/' + name + '.wav')
                    rows.append(P.input_row('mix_stem', path, project_path(root, path)))
                except (OSError, ValueError):
                    pass
        try:
            report_data = attached_mix_report(folder, mix, files)
            _, _, refs = conform_evidence(identity if isinstance(identity, dict) else {}, report_data,
                                           verify_media=False)
            for role, path in refs:
                rows.append(P.input_row(role, path, project_path(root, path)))
        except (OSError, ValueError, TypeError):
            pass
    timing = identity.get('picture_timing') if isinstance(identity, dict) else None
    if isinstance(timing, dict) and timing.get('pts_file'):
        try:
            schedule = version_schedule_path(folder, timing['pts_file'])
            if not P.same_file(schedule, folder / 'picture-timing.json'):
                rows.append(P.input_row('picture_timing', schedule, project_path(root, schedule)))
        except ValueError:
            pass
    rows += [P.input_row('title_asset', path, project_path(root, path)) for path in title_assets(folder)]
    if final:
        master = folder / 'preview.mp4'
        rows.append(P.input_row('version_master', master, project_path(root, master)))
    if speech:
        map_folder = Path(root) / 'map'
        rows.append(P.transcript_listing_row(map_folder, project_path(root, map_folder)))
        rows += [P.input_row('map_transcript', path, project_path(root, path))
                 for path in sorted(map_folder.glob('*/words.json'))]
    if profile:
        rows.append(P.input_row('caption_profile', profile, project_path(root, profile)))
    rows += layer_inputs(root, folder)
    return rows


def layer_inputs(root, folder):
    """The layer files a version's edit draws (pin, behind, blur), so --verify notices a layer made again."""
    edit = P.load_json(folder / 'edit.json', {}) or {}
    overlays = edit.get('overlays', []) if isinstance(edit, dict) else []
    keys = ('pin', 'behind', 'region')
    if not any(isinstance(overlay, dict) and any(isinstance(overlay.get(key), dict) for key in keys)
               for overlay in overlays):
        return []
    spec = importlib.util.spec_from_file_location('lf_spatial_inputs', HERE / 'spatial.py')
    spatial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spatial)
    INVOKED.add('spatial.py')
    return [P.input_row(role, path, project_path(root, path)) for role, path in spatial.layer_files(edit, folder)]


def project_caption_note(root, srt, given, final):
    """Which caption file a project check read, said in each caption item."""
    name = project_path(root, srt) if not Path(project_path(root, srt)).is_absolute() else Path(srt).name
    if given:
        return f'captions checked: {name}, the sidecar given with --captions'
    if final:
        return (f"captions checked: {name}, the version's own, not a sidecar delivered with this final; give "
                '--captions FILE to check the one delivered')
    return f"captions checked: {name}, the version's own"


def stress_item(video):
    """Attach a delivery stress screen, or say why it was not assessed."""
    with tempfile.TemporaryDirectory(prefix='lf-stress-') as temporary:
        folder = Path(temporary) / 'delivery'
        code, output = run_script('delivery_check.py', video, folder)
        try:
            report = P.load_json(folder / 'report.json', None)
        except (OSError, ValueError):
            report = None
    if code or not isinstance(report, dict):
        entry = item('stress_delivery', 'Not assessed: delivery stress', 'skip',
                     'delivery check could not run: ' + output[-400:])
    elif report.get('state') != 'measured':
        entry = item('stress_delivery', 'Not assessed: delivery stress', 'skip',
                     report.get('reason') or 'delivery metrics unavailable')
        entry['measurement'] = report
    else:
        entry = item('stress_delivery', 'Delivery stress screen', 'look',
                     f"{report.get('frames_checked')} frames measured; inspect CAMBI and VMAF worst windows")
        entry['measurement'] = report
    entry['group'] = 'stress'
    return entry


def check_project(root, version=None, final_file=None, speech=True, target=None, captions=None, profile=None,
                  stress=False):
    """Check a version (or a final file) of a project; write checks.json and update the status. With `captions`, the
    caption items check that sidecar (the one delivered with a final) instead of the version's captions.srt."""
    INVOKED.clear()
    version = version or P.current_version(root)
    if not version:
        raise ValueError('no rendered version to check; render one first: cut.py render PROJECT')
    folder = root / 'cuts' / version
    manifest = P.load_json(folder / 'manifest.json', {}) or {}
    settings = front_matter(folder / 'film.md')
    if target is None and settings.get('loudness'):
        target = float(settings['loudness'])
    video = Path(final_file) if final_file else folder / 'preview.mp4'
    if not video.is_file():
        raise ValueError(f'no file to check: {video}')
    if captions and not Path(captions).is_file():
        raise ValueError(f'no caption file: {captions}')
    if profile and not Path(profile).is_file():
        raise ValueError(f'no caption profile: {profile}')
    spec = None
    dimensions = manifest.get('size') if final_file else manifest.get('preview_size') or manifest.get('size')
    if dimensions:
        width, height = dimensions
        spec = f"{width}x{height}@{manifest.get('fps', settings.get('fps', '30'))}"
    # A person's review counts only for the file it was recorded against.
    entry = ((P.read_status(root).get('reviewed') or {}).get(version)) or {}
    digest = P.file_sha256(video)
    reviewed = P.reviews_for(entry, digest, digest == P.preview_sha256(root, version))
    model, language = speech_settings(root)
    srt = Path(captions) if captions else folder / 'captions.srt'
    inputs = project_inputs(root, folder, video, digest, bool(final_file), srt, speech, profile, manifest)
    frame_path = folder / 'film.md' if (folder / 'film.md').is_file() else root / 'film.md'
    if frame_path == root / 'film.md':
        inputs.append(P.input_row('context_frame', frame_path, project_path(root, frame_path)))
    previous = P.load_json(folder / ('checks-final.json' if final_file else 'checks.json'), {}) or {}
    prefix = 'final-' if final_file else ''
    outputs = [folder / 'qa' / (prefix + name) for name in QA_FILES]
    outputs += [folder / 'checks.json', folder / 'checks-final.json', root / 'status.json']
    P.refuse_overwriting_inputs(outputs, [P.locate_input(row['path'], [root]) for row in inputs] + check_tool_inputs(),
                                project=root)
    note = project_caption_note(root, srt, bool(captions), bool(final_file))
    speech_pair = (model, language) if speech else None

    def caption_check(checked, fresh, has_audio):
        return caption_items(folder, checked, fresh, speech_pair, has_audio, captions, note, profile)

    checks = run_checks(video, folder / 'qa', spec, manifest.get('duration_s'), bool(final_file), target, reviewed,
                        folder, speech_pair, manifest.get('frames'),
                        settings.get('bars', '').lower() in ('allow', 'allowed', 'yes', 'true'),
                        captions_check=caption_check)
    cold = previous.get('cold_read') if isinstance(previous, dict) else None
    if final_file and not cold:
        preview_checks = P.load_json(folder / 'checks.json', {}) or {}
        cold = preview_checks.get('cold_read') if isinstance(preview_checks, dict) else None
    checks['items'] += context_items(read_frame(frame_path), cold, digest)
    checks['items'].append(binding_item(manifest.get('identity')))
    checks['items'] += hdr_items(manifest)
    sync_items, transcript = project_sync_items(folder, video, manifest,
                                                required=project_path_name(frame_path) in ('create', 'insert', 'sound'))
    checks['items'] += sync_items
    if stress:
        checks['items'].append(stress_item(video))
    if transcript is not None:
        checks['listening_transcript'] = transcript
    checks['summary'] = summarise(checks['items'])
    if cold:
        checks['cold_read'] = cold
    try:
        checks['file'] = Path(video).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        checks['file'] = Path(video).name
    checks['sha256'] = digest
    checks['inputs_base'] = 'project'
    checks['inputs'] = inputs
    checks['tools'] = tools_record(model)
    P.save_json(folder / ('checks-final.json' if final_file else 'checks.json'), checks)
    needs = [entry['label'] for entry in checks['items'] if entry['state'] == 'you']
    blind = [entry['label'] + ': ' + entry['detail'] for entry in checks['items'] if entry['state'] == 'skip']
    # A failed final is not finished checking, even when an earlier check completed the stage. The stage records
    # that the checks ran; whether they passed is in checks.json, and acceptance is a person's approved record.
    stages = {'check': 'now' if final_file and checks['summary'].get('fail') else 'done'}
    P.update_status(root, stages=stages, needs_you=needs, blind_spots=blind)
    P.update_status(root, line=P.status_line(root))
    return checks


DELIVERY_KEYS = {'size': 'WIDTHxHEIGHT or [WIDTH, HEIGHT]', 'fps': 'frame rate (24, 23.976 or 24000/1001)',
                 'frames': 'expected frame count', 'duration_s': 'expected duration in seconds',
                 'loudness': 'integrated loudness target in LUFS', 'vcodec': 'video codec (h264)',
                 'pix_fmt': 'pixel format (yuv420p)', 'color': 'colour tags (bt709)',
                 'captions_required': 'true or false', 'allow_bars': 'true when black borders are intended'}
DELIVERY_ALIASES = {'frame_rate': 'fps', 'duration': 'duration_s', 'loudness_lufs': 'loudness', 'codec': 'vcodec',
                    'pixel_format': 'pix_fmt', 'colour': 'color'}


def delivery_settings(path):
    """The expected delivery settings from a JSON file ({"size": "1920x1080", "fps": "24000/1001", "loudness": -16,
    "captions_required": true, ...}); a key it does not know is refused so a typo is never silently ignored. Keys
    beginning with '_' and 'name' or 'notes' are comments."""
    data = P.load_json(path, None)
    if not isinstance(data, dict):
        raise ValueError(f'--delivery {path}: expected a JSON object of settings')
    settings = {}
    for key, value in data.items():
        if key.startswith('_') or key in ('name', 'notes'):
            continue
        name = DELIVERY_ALIASES.get(key, key)
        if name not in DELIVERY_KEYS:
            known = ', '.join(f'{known} ({meaning})' for known, meaning in DELIVERY_KEYS.items())
            raise ValueError(f'--delivery {path}: unknown setting {key!r}; the settings are {known}')
        settings[name] = value
    size = settings.get('size')
    if isinstance(size, (list, tuple)) and len(size) == 2:
        size = f'{size[0]}x{size[1]}'
    if size is not None and not re.fullmatch(r'\d+x\d+', str(size)):
        raise ValueError(f'--delivery {path}: size must be WIDTHxHEIGHT or [WIDTH, HEIGHT], not {settings["size"]!r}')
    try:
        fps = str(settings['fps']) if settings.get('fps') is not None else None
        if fps is not None:
            Fraction(fps)
        out = {'size': size, 'fps': fps,
               'frames': int(settings['frames']) if settings.get('frames') is not None else None,
               'duration_s': float(settings['duration_s']) if settings.get('duration_s') is not None else None,
               'loudness': float(settings['loudness']) if settings.get('loudness') is not None else None}
    except (TypeError, ValueError, ZeroDivisionError) as error:
        raise ValueError(f'--delivery {path}: {error}') from None
    for key in ('captions_required', 'allow_bars'):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError(f'--delivery {path}: {key} must be true or false')
        out[key] = settings.get(key)
    for key in ('vcodec', 'pix_fmt', 'color'):
        out[key] = str(settings[key]) if settings.get(key) is not None else None
    return out


def file_settings(args):
    """The expected settings for --file: each flag given, else the delivery settings, else the defaults."""
    wanted = delivery_settings(args.delivery) if args.delivery else {}
    spec = args.spec or wanted.get('size')
    fps = None if args.spec and '@' in args.spec else wanted.get('fps')
    duration = args.duration if args.duration is not None else wanted.get('duration_s')
    frames = wanted.get('frames')
    gif = args.edit == 'convert' and Path(args.file).suffix.lower() == '.gif'
    return {'spec': spec, 'fps': fps, 'duration': duration, 'frames': frames,
            'target': args.loudness if args.loudness is not None else wanted.get('loudness'),
            'vcodec': args.vcodec or wanted.get('vcodec') or ('gif' if gif else 'h264'),
            'pix_fmt': args.pix_fmt or wanted.get('pix_fmt') or (None if gif else 'yuv420p'),
            'color': args.color or wanted.get('color') or (None if gif else 'bt709'),
            'faststart': not gif, 'bars': bool(args.allow_bars or wanted.get('allow_bars')),
            'captions_required': wanted.get('captions_required')}


def timeline_media(path):
    """The local file URLs exchange.py can read from this timeline, including absent media."""
    spec = importlib.util.spec_from_file_location('lf_exchange_inputs', HERE / 'exchange.py')
    exchange = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exchange)
    INVOKED.add('exchange.py')
    try:
        files = exchange.file_table(exchange.ET.parse(path).getroot())
    except (OSError, ValueError, exchange.ET.ParseError):
        return []
    result = []
    for entry in files.values():
        local = exchange.local_path(entry.get('url'))
        if local and not any(P.same_file(local, other) for other in result):
            result.append(local)
    return result


def file_inputs(args):
    """The inputs a --file check depends on, as (role, path), in order."""
    rows = [('export', args.file)]
    export = Path(args.file)
    rows.append(('cold_read', export.parent / (export.stem + '.grade') / 'cold' / 'checks.json'))
    if args.against:
        rows.append(('reference', args.against))
    rows += [(role, value) for role, value in (('captions', args.captions), ('timeline', args.timeline),
                                               ('edit_words', args.edit_words), ('speech_words', args.speech_words),
                                               ('delivery', args.delivery), ('caption_profile', args.caption_profile))
             if value]
    rows += [('source_words', path) for path in args.source_words or []]
    if args.timeline and args.timeline_project:
        project = Path(args.timeline_project)
        rows.append(('map_sources', str(project / 'map' / 'sources.json')))
        rows += [('source_words', str(path)) for path in sorted((project / 'map').glob('*/words.json'))]
        rows.append(('map_transcript_listing', str(project / 'map')))
    if args.timeline:
        rows += [('timeline_media', str(path)) for path in timeline_media(args.timeline)]
    if args.timeline and args.timeline_project:
        index = P.load_json(Path(args.timeline_project) / 'map' / 'sources.json', {}) or {}
        for source in index.get('sources', []) if isinstance(index, dict) else []:
            if not isinstance(source, dict) or not isinstance(source.get('path'), str) or not source['path']:
                continue
            path = Path(source['path'])
            path = path if path.is_absolute() else Path(args.timeline_project) / path
            if not any(P.same_file(path, previous) for _, previous in rows):
                rows.append(('source_media', str(path)))
    return rows


def validate_file_args(args):
    """Refuse --file options that cannot work together, before anything runs."""
    if bool(args.against) != bool(args.edit):
        raise ValueError('--against and --edit must be given together')
    if args.timeline and args.edit_words:
        raise ValueError('give --timeline (with --project or --source-words) or --edit-words, not both')
    if args.timeline and not (args.timeline_project or args.source_words):
        raise ValueError('--timeline needs the source transcripts: --project DIR (its map) or --source-words FILE')
    if (args.timeline_project or args.source_words or args.map or args.track) and not args.timeline:
        raise ValueError('--project, --source-words, --map and --track go with --timeline XML')
    for role, path in file_inputs(args):
        if role not in ('map_sources', 'source_words', 'timeline_media', 'source_media', 'map_transcript_listing',
                        'cold_read') \
                and not Path(path).is_file():
            raise ValueError(f'no {role.replace("_", " ")} file: {path}')
    if args.timeline_project and not (Path(args.timeline_project) / 'map' / 'sources.json').is_file():
        raise ValueError(f'--project {args.timeline_project} has no map/sources.json; is it a project folder?')
    for path in args.source_words or []:
        if not Path(path).is_file():
            raise ValueError(f'no source words file: {path}')


def probe_media(path):
    """Read streams and duration from the media being compared."""
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ValueError('ffprobe is required for an edit comparison')
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('cannot probe edit input: ' + result.stderr[-400:])
    return json.loads(result.stdout)


def edit_kind(value):
    name, sep, rest = value.partition(':')
    if name in ('trim', 'speed'):
        try:
            values = [float(part) for part in rest.split(',')]
        except ValueError:
            raise ValueError('invalid numeric edit parameters') from None
        if not sep or not all(math.isfinite(v) for v in values):
            raise ValueError('invalid numeric edit parameters')
        if name == 'trim' and (len(values) != 2 or values[0] < 0 or values[1] <= values[0]):
            raise ValueError('trim needs trim:A,B with 0 <= A < B')
        if name == 'speed' and (len(values) != 1 or values[0] <= 0):
            raise ValueError('speed needs a positive duration factor: speed:X')
        return name, values
    if sep or name not in ('reframe', 'convert', 'extract-audio', 'captions', 'compress'):
        raise ValueError('edit must be trim:A,B, speed:X, reframe, convert, extract-audio, captions or compress')
    return name, []


def edit_metadata_items(source, output, kind):
    """Compare the stated edit's duration, stream layout and audio origin."""
    name, values = edit_kind(kind)
    src, dst = source.get('streams', []), output.get('streams', [])

    def stream(rows, which):
        return next((row for row in rows if row.get('codec_type') == which), None)

    def duration(data, rows):
        video = stream(rows, 'video')
        for value in ((video or {}).get('duration'), data.get('format', {}).get('duration')):
            try:
                value = float(value)
                if math.isfinite(value) and value > 0:
                    return value
            except (ValueError, TypeError):
                pass
        return None

    before, after = duration(source, src), duration(output, dst)
    try:
        rate = float(Fraction((stream(dst, 'video') or stream(src, 'video') or {}).get('avg_frame_rate', '0/1')))
        tolerance = 1 / rate if rate > 0 else None
    except (ValueError, ZeroDivisionError):
        tolerance = None
    expected = None
    if before is not None:
        expected = values[1] - values[0] if name == 'trim' else before * values[0] if name == 'speed' else before
        if name == 'trim' and values[1] > before + (tolerance or 0):
            raise ValueError('trim end is beyond the source duration')
    if before is None or after is None or expected is None or tolerance is None:
        rows = [item('edit_duration', 'Not assessed: edit duration', 'skip', 'duration or frame rate unavailable')]
    else:
        rows = [item('edit_duration', 'Edit duration', 'pass' if abs(after - expected) <= tolerance else 'fail',
                     f'expected {expected:.6f} s, found {after:.6f} s; tolerance {tolerance:.6f} s')]
    if name == 'extract-audio':
        good = stream(dst, 'video') is None and stream(dst, 'audio') is not None
        rows.append(item('edit_streams', 'Extracted audio streams', 'pass' if good else 'fail',
                         'audio present and no video' if good else 'requires audio and no video'))
    elif name in ('trim', 'speed', 'reframe', 'convert', 'captions', 'compress'):
        counts = lambda rows: {key: sum(row.get('codec_type') == key for row in rows)
                               for key in ('video', 'audio', 'subtitle')}
        old, new = counts(src), counts(dst)
        formats = str(output.get('format', {}).get('format_name', '')).split(',')
        expected = {'video': 1, 'audio': 0, 'subtitle': 0} if name == 'convert' and 'gif' in formats else old
        rows.append(item('edit_streams', 'Edit stream counts', 'pass' if expected == new else 'fail',
                         f'source {old}, expected {expected}, output {new}'))
    if name == 'trim':
        old_audio, new_audio = stream(src, 'audio'), stream(dst, 'audio')
        old_video, new_video = stream(src, 'video'), stream(dst, 'video')
        if bool(old_audio) != bool(new_audio):
            rows.append(item('edit_audio_offset', 'Trim audio timestamp offset', 'fail', 'audio stream changed'))
        elif old_audio is None:
            rows.append(item('edit_audio_offset', 'Not assessed: trim audio offset', 'skip', 'no audio stream'))
        else:
            try:
                old = float(old_audio['start_time']) - float(old_video['start_time'])
                new = float(new_audio['start_time']) - float(new_video['start_time'])
                if not all(math.isfinite(v) for v in (old, new)) or tolerance is None:
                    raise ValueError
                rows.append(item('edit_audio_offset', 'Trim audio timestamp offset',
                                 'pass' if abs(old - new) <= tolerance else 'fail',
                                 f'source {old:.6f} s, output {new:.6f} s'))
            except (KeyError, TypeError, ValueError):
                rows.append(item('edit_audio_offset', 'Not assessed: trim audio offset', 'skip',
                                 'stream start times unavailable'))
    return rows


def packet_signature(path, selector):
    """Return a stream's packet hash and presentation schedule."""
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('FFmpeg and ffprobe are required')
    hashed = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:' + selector,
                             '-c', 'copy', '-f', 'hash', '-hash', 'sha256', '-'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    timed = subprocess.run([ffprobe, '-v', 'error', '-select_streams', selector, '-show_packets',
                            '-show_entries', 'packet=pts_time,duration_time', '-of', 'json', str(path)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    if hashed.returncode or timed.returncode:
        raise ValueError('cannot read stream packets')
    rows = json.loads(timed.stdout).get('packets', [])
    if not rows or any('pts_time' not in row or 'duration_time' not in row for row in rows):
        raise ValueError('stream packet timestamps are unavailable')
    times = [(float(row['pts_time']), float(row['duration_time'])) for row in rows]
    if not all(math.isfinite(x) for row in times for x in row):
        raise ValueError('stream packet timestamps are not finite')
    return hashed.stdout.strip(), times


def signatures_match(first, second, tolerance=.001):
    hash_a, times_a = first
    hash_b, times_b = second
    return hash_a == hash_b and len(times_a) == len(times_b) and all(
        abs(a - b) <= tolerance for pair_a, pair_b in zip(times_a, times_b) for a, b in zip(pair_a, pair_b))


def thumbnails(path, moment, count=1):
    """Frames from a time on as grey thumbnails ([] when nothing decodes there). This small, re-encoding and scaling
    change little, and a detail a low bitrate loses barely counts."""
    ffmpeg = shutil.which('ffmpeg')
    width, height = THUMBNAIL
    result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-ss', f'{max(0.0, moment):.4f}', '-i', str(path),
                             '-map', '0:v:0', '-frames:v', str(count), '-vf',
                             f'scale={width}:{height}:flags=area,format=gray', '-f', 'rawvideo', '-'],
                            capture_output=True)
    size = width * height
    return [result.stdout[start:start + size] for start in range(0, len(result.stdout) - size + 1, size)]


def level_and_spread(picture):
    """A thumbnail's mean grey level and its standard deviation."""
    mean = sum(picture) / len(picture)
    return mean, math.sqrt(sum((value - mean) ** 2 for value in picture) / len(picture))


def picture_verdict(frame, candidates):
    """One sampled frame against the source frames it may show: 'same', 'other', 'between', or 'flat' when neither has
    the detail to tell. A flat frame where the source has detail, or the reverse, is another picture."""
    level, spread = level_and_spread(frame)
    best = -1.0
    for candidate in candidates:
        other_level, other_spread = level_and_spread(candidate)
        if spread < PICTURE_FLAT or other_spread < PICTURE_FLAT:
            if max(spread, other_spread) > 3 * PICTURE_FLAT or abs(level - other_level) > 12 * PICTURE_FLAT:
                continue
            return 'flat'
        best = max(best, sum((a - level) * (b - other_level) for a, b in zip(frame, candidate))
                   / (len(frame) * spread * other_spread))
    return 'same' if best >= PICTURE_SAME else 'other' if best < PICTURE_OTHER else 'between'


def media_seconds(data):
    """A probed file's length: its first video stream's, else the container's; None when neither says."""
    video = next((row for row in data.get('streams', []) if row.get('codec_type') == 'video'), {})
    for value in (video.get('duration'), (data.get('format') or {}).get('duration')):
        try:
            if math.isfinite(float(value)) and float(value) > 0:
                return float(value)
        except (TypeError, ValueError):
            pass
    return None


def frame_seconds(data):
    """How long one frame of a probed file's first video stream lasts, or None."""
    video = next((row for row in data.get('streams', []) if row.get('codec_type') == 'video'), {})
    try:
        rate = Fraction(str(video.get('avg_frame_rate')))
        return float(1 / rate) if rate > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def audio_position(data):
    """Which of a probed file's audio streams a player plays by default, counted among its audio streams."""
    rows = [row for row in data.get('streams', []) if row.get('codec_type') == 'audio']
    played = P.default_audio_stream(rows)
    return rows.index(played) if played else 0


def frame_shape(data):
    """A probed file's first video stream as width over height, or None."""
    video = next((row for row in data.get('streams', []) if row.get('codec_type') == 'video'), {})
    try:
        return float(video['width']) / float(video['height'])
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def picture_content_item(reference, output, source, destination, when, what):
    """Sampled frames of the output against the source frames the edit says they show (`when` turns an output time
    into a source time; `what` names them). Confident disagreement fails, a mixed result is a look, and too little
    detail to tell is not assessed."""
    label = 'Not assessed: content of the picture'
    seconds = media_seconds(destination)
    if not shutil.which('ffmpeg'):
        return item('edit_picture', label, 'skip', 'FFmpeg is required')
    if not seconds:
        return item('edit_picture', label, 'skip', 'the output has no length to sample')
    shapes = frame_shape(source), frame_shape(destination)
    if all(shapes) and abs(shapes[1] / shapes[0] - 1) > PICTURE_SHAPE:
        # A trim that also reframes, say: its frames show part of the source's, so they cannot be matched whole.
        return item('edit_picture', label, 'skip', f'the frame changed shape, from {shapes[0]:.3f} to {shapes[1]:.3f}, '
                    'so its frames cannot be matched with the whole source; look at the framing')
    source_frame = frame_seconds(source) or .04
    reach = max(source_frame, (frame_seconds(destination) or source_frame) * (when(1.0) - when(0.0)))
    count = min(12, math.ceil(2 * reach / source_frame) + 1)
    verdicts = []
    for number in range(PICTURE_SAMPLES):
        moment = (number + .5) / PICTURE_SAMPLES * seconds
        frame, candidates = thumbnails(output, moment), thumbnails(reference, when(moment) - reach, count)
        verdicts.append((moment, picture_verdict(frame[0], candidates) if frame and candidates else 'flat'))
    other = [moment for moment, verdict in verdicts if verdict == 'other']
    same = sum(verdict == 'same' for _, verdict in verdicts)
    informative = PICTURE_SAMPLES - sum(verdict == 'flat' for _, verdict in verdicts)
    counted = f'{PICTURE_SAMPLES} frames sampled against {what}'
    if informative < 3:
        return item('edit_picture', label, 'skip', f'too little to compare: {counted}, and {informative} had the '
                    'detail to tell them apart; look at the picture')
    if len(other) >= max(2, math.ceil(informative / 2)):
        return item('edit_picture', 'Picture content', 'fail', f'{len(other)} of {informative} comparable frames do '
                    f'not match: {counted}; first at {P.format_time(other[0])}', other[0])
    if other or same * 4 < informative * 3:
        return item('edit_picture', 'Picture content', 'look', f'{same} of {informative} comparable frames match and '
                    f'{len(other)} do not: {counted}; look at them', other[0] if other else None)
    return item('edit_picture', 'Picture content', 'pass',
                f'{same} of {informative} comparable frames match: {counted}')


def sync_state(summary):
    """What sync_check.py's comparison of sound with its source says: (state, detail): the same, measurably not, or too
    little to tell. Most windows silent where the source has sound is measurably not, though transport cannot say."""
    verdict = summary.get('verdict', '')
    silent, windows = summary.get('windows_delivered_silent') or 0, summary.get('windows') or 0
    if verdict == 'consistent with the reference within tolerance':
        return 'pass', verdict
    if silent >= max(2, math.ceil(2 * windows / 3)):
        return 'fail', (f'content differs: the output is silent in {silent} of {windows} windows where the source has '
                        'sound')
    if verdict.startswith(('constant offset', 'lag changes', 'content differs')):
        return 'fail', verdict
    return 'skip', verdict or 'audio comparison inconclusive'


def audio_content_item(reference, output, source, destination):
    """The whole of the output's sound against the source's, tolerant of re-encoding; a source too long to hold both in
    memory, or with several streams to choose from, is not compared."""
    label = 'Not assessed: content of the sound'

    def audio(data):
        return [row for row in data.get('streams', []) if row.get('codec_type') == 'audio']

    if not audio(destination):
        return item('edit_audio', label, 'skip', 'the output has no sound stream to compare')
    if not audio(source):
        return item('edit_audio', label, 'skip', 'the source has no sound stream to compare with')
    if len(audio(source)) > 1 or len(audio(destination)) > 1:
        return item('edit_audio', label, 'skip', 'several sound streams: compare the one that matters with '
                    'sync_check.py by hand')
    longest = max(media_seconds(source) or 0, media_seconds(destination) or 0)
    if longest > AUDIO_COMPARE_S:
        return item('edit_audio', label, 'skip', f'{longest / 60:.0f} minutes is too long to compare here: compare a '
                    'passage with sync_check.py by hand')
    seconds = media_seconds(destination) or 0
    if seconds < 1:
        return item('edit_audio', label, 'skip', 'the sound is too short to compare')
    tolerance_ms = 1000 * (frame_seconds(source) or .04)
    with tempfile.TemporaryDirectory(prefix='lf-edit-sound-') as temp:
        report_path = Path(temp) / 'sync.json'
        report, why = run_report('sync_check.py', [output, reference, '--window', f'{min(3.0, seconds / 4):g}',
                                                   '--max-lag-ms', f'{min(500.0, seconds * 100):g}', '--tolerance-ms',
                                                   f'{tolerance_ms:g}', '--json', report_path], report_path)
    if report is None:
        return item('edit_audio', label, 'skip', why)
    state, detail = sync_state(report.get('summary') or {})
    row = item('edit_audio', label if state == 'skip' else 'Sound content', state,
               detail + '; compared with the source')
    row['measurement'] = report.get('summary')
    return row


def edit_content_items(reference, output, kind, source, destination):
    """Compare what the declared edit promises to keep, where that is cheap, and say where it is not compared."""
    kind, values = edit_kind(kind)
    if kind == 'trim':
        start, end = values
        return (trim_audio_content_items(reference, output, values, source, destination)
                + [picture_content_item(reference, output, source, destination, lambda moment: start + moment,
                                        f'the source from {P.format_time(start)} to {P.format_time(end)}')])
    if kind == 'speed':
        factor = values[0]
        return [picture_content_item(reference, output, source, destination, lambda moment: moment / factor,
                                     f'the source at {factor:g} times its length'),
                item('edit_audio', 'Not assessed: content of the sound', 'skip',
                     'a speed change rewrites the waveform, so it is not compared; listen to it')]
    if kind == 'extract-audio':
        return [audio_content_item(reference, output, source, destination)]
    if kind in ('convert', 'compress'):
        return [picture_content_item(reference, output, source, destination, lambda moment: moment, 'the source'),
                audio_content_item(reference, output, source, destination)]
    old, new = source.get('streams', []), destination.get('streams', [])
    selected = ('audio',) if kind == 'reframe' else ('video', 'audio')
    items = []
    for media in selected:
        src_count = sum(row.get('codec_type') == media for row in old)
        dst_count = sum(row.get('codec_type') == media for row in new)
        if src_count != dst_count:
            items.append(item('edit_' + media, 'Edit ' + media + ' content', 'fail', 'stream count changed'))
            continue
        if not src_count:
            items.append(item('edit_' + media, 'Not assessed: edit ' + media + ' content', 'skip', 'no stream'))
            continue
        try:
            signatures = [(packet_signature(reference, f'{media[0]}:{i}'),
                           packet_signature(output, f'{media[0]}:{i}')) for i in range(src_count)]
        except (OSError, ValueError, json.JSONDecodeError) as error:
            items.append(item('edit_' + media, 'Not assessed: edit ' + media + ' content', 'skip', str(error)))
            continue
        if all(signatures_match(a, b) for a, b in signatures):
            items.append(item('edit_' + media, 'Edit ' + media + ' content', 'pass',
                              'packet hashes and presentation timestamps match'))
            continue
        if kind == 'captions' or media != 'audio' or src_count != 1:
            items.append(item('edit_' + media, 'Edit ' + media + ' content', 'fail',
                              'packet hash or presentation timestamps changed'))
            continue
        with tempfile.TemporaryDirectory(prefix='lf-edit-audio-') as temp:
            report_path = Path(temp) / 'sync.json'
            report, why = run_report('sync_check.py', [output, reference, '--window', '0.5', '--max-lag-ms', '100',
                                                      '--outside', '0,0', '--json', report_path], report_path)
        if report is None:
            items.append(item('edit_audio', 'Not assessed: edit audio content', 'skip', why))
            continue
        verdict = report.get('outside', {}).get('verdict', '')
        overall = report.get('summary', {}).get('verdict', '')
        if verdict == 'unchanged within tolerance' and overall == 'consistent with the reference within tolerance':
            state = 'pass'
        elif verdict == 'changed outside the passage':
            state = 'fail'
        elif overall.startswith('content differs'):
            state, verdict = 'fail', overall
        else:
            state = 'skip'
        label = 'Not assessed: edit audio content' if state == 'skip' else 'Edit audio content'
        items.append(item('edit_audio', label, state, verdict or 'audio comparison inconclusive'))
    if kind == 'reframe':
        items.append(item('edit_picture', 'Not assessed: content of the picture', 'skip',
                          'a reframe crops and moves the picture, so its frames cannot be matched with the whole '
                          'source; look at the framing'))
    return items


def trim_audio_content_items(reference, output, bounds, source, destination):
    """Compare the trimmed source sound with the delivered sound's transport and content."""
    def result(state, detail, measurement=None):
        label = ('Not assessed: ' if state == 'skip' else '') + 'Trim audio content offset'
        if detail.startswith('content differs'):
            label = 'Trim audio content'
        row = item('edit_trim_content_offset', label, state, detail)
        if measurement is not None:
            row['measurement'] = measurement
        return [row]

    def stream(data, kind):
        return next((row for row in data.get('streams', []) if row.get('codec_type') == kind), None)

    src_audio, dst_audio = stream(source, 'audio'), stream(destination, 'audio')
    if not src_audio and not dst_audio:
        return result('skip', 'no audio stream')
    if not src_audio or not dst_audio:
        return result('fail', 'audio stream changed')
    try:
        rate = float(Fraction((stream(destination, 'video') or stream(source, 'video') or {})['avg_frame_rate']))
        if not math.isfinite(rate) or rate <= 0:
            raise ValueError
        tolerance_ms = 1000 / rate
        for data, audio in ((source, src_audio), (destination, dst_audio)):
            video = stream(data, 'video')
            audio_start, video_start = float(audio['start_time']), float(video['start_time'])
            if not all(math.isfinite(value) for value in (audio_start, video_start)):
                raise ValueError
            if abs(audio_start - video_start) * 1000 > tolerance_ms:
                return result('skip', 'nonzero stream origin needs a timestamp-aware audio comparison')
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return result('skip', 'frame rate or stream origin is unavailable')
    duration = bounds[1] - bounds[0]
    max_lag_ms = min(500, duration * 200)
    if duration < .5 or max_lag_ms <= tolerance_ms:
        return result('skip', 'the trimmed passage is too short for an audio offset comparison')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        return result('skip', 'FFmpeg is required')
    with tempfile.TemporaryDirectory(prefix='lf-trim-audio-') as temp:
        clipped, report_path = Path(temp) / 'reference.wav', Path(temp) / 'sync.json'
        selector = f"0:a:{audio_position(source)}"
        command = [ffmpeg, '-v', 'error', '-nostdin', '-i', str(reference), '-ss', str(bounds[0]),
                   '-t', str(duration), '-map', selector, '-ac', '2', '-ar', '48000',
                   '-c:a', 'pcm_s16le', str(clipped)]
        try:
            run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        except OSError as error:
            return result('skip', 'cannot decode the source passage: ' + str(error))
        if run.returncode:
            return result('skip', 'cannot decode the source passage: ' + run.stderr.strip()[-200:])
        report, why = run_report('sync_check.py', [output, clipped, '--window', str(min(.5, duration / 4)),
            '--max-lag-ms', str(max_lag_ms), '--tolerance-ms', str(tolerance_ms), '--json', report_path], report_path)
    if report is None:
        return result('skip', why or 'audio comparison could not run')
    summary = report.get('summary') or {}
    state, verdict = sync_state(summary)
    return result(state, verdict +
                  '; compared sampled audio with the declared source passage', summary)


def check_file(args):
    """Check an editor's export as delivered (--file): its spec, sound and picture, and with the inputs given its
    captions, the timeline's words and a transcript of its speech. Returns checks.json content with its inputs and
    tools recorded; --json naming any input is refused before anything runs."""
    INVOKED.clear()
    validate_file_args(args)
    named = file_inputs(args)
    P.refuse_overwriting_inputs([args.json], [path for _, path in named] + check_tool_inputs(),
                                guard_versions=True)
    wanted = file_settings(args)
    video = Path(args.file)
    digest = P.file_sha256(video)
    inputs = [P.transcript_listing_row(path, str(Path(path).resolve())) if role == 'map_transcript_listing' else
              P.input_row(role, path, str(Path(path).resolve()), digest if role == 'export' else None)
              for role, path in named]
    project = Path(args.timeline_project) if args.timeline_project else None
    model, language = speech_settings(project) if project else (DEFAULT_SPEECH_MODEL, None)
    plan = {'captions': args.captions, 'timeline': args.timeline, 'project': args.timeline_project,
            'source_words': args.source_words, 'map': args.map, 'track': args.track, 'edit_words': args.edit_words,
            'speech_words': args.speech_words, 'profile': args.caption_profile, 'sha256': digest,
            'speech': None if args.no_speech else (model, language),
            'captions_required': wanted['captions_required']}

    def caption_check(checked, fresh, has_audio):
        return file_caption_items(plan, checked, fresh, has_audio)

    kind = edit_kind(args.edit)[0] if args.edit else None
    if kind == 'extract-audio':
        checks = {'version': 1, 'file': str(video), 'final': True,
                  'items': [item('audio_technical', 'Not assessed: audio technical checks', 'skip',
                                 'audio-only export'), item('heard', 'Heard by you, with sound', 'you')], 'summary': {}}
    else:
        checks = run_checks(video, None, wanted['spec'], wanted['duration'], True, wanted['target'],
                            expected_frames=wanted['frames'], bars_allowed=wanted['bars'], vcodec=wanted['vcodec'],
                            pix_fmt=wanted['pix_fmt'], color=wanted['color'], captions_check=caption_check,
                            fps=wanted['fps'], duration_independent=True, faststart=wanted['faststart'])
    if args.against:
        source, destination = probe_media(args.against), probe_media(video)
        checks['items'] += edit_metadata_items(source, destination, args.edit)
        checks['items'] += edit_content_items(args.against, video, args.edit, source, destination)
    cold_path = video.parent / (video.stem + '.grade') / 'cold' / 'checks.json'
    cold_record = P.load_json(cold_path, {}) or {}
    checks['items'] += context_items({}, cold_record.get('cold_read'), digest)
    sync = item('sync_cues', 'Not assessed: sync', 'skip', 'no cue list supplied')
    sync['group'] = 'sync'
    checks['items'].append(sync)
    if getattr(args, 'stress', False):
        checks['items'].append(stress_item(video))
    checks['summary'] = summarise(checks['items'])
    checks['sha256'] = digest
    checks['inputs_base'] = 'given'
    checks['inputs'] = inputs
    checks['tools'] = tools_record(model)
    if args.json:
        P.save_json(args.json, checks)
    return checks


def verify(path):
    """Re-hash a checks file's recorded inputs and tools: (exit code, lines). 0 when all are current, 1 when an input
    or tool changed (each listed), 2 when it cannot say (unreadable, or written before inputs were recorded)."""
    try:
        checks = P.load_json(path, None)
    except (OSError, ValueError, RecursionError):
        return 2, [f'cannot verify: {path} cannot be read as a checks file']
    if not isinstance(checks, dict):
        return 2, [f'cannot verify: {path} is not a checks file']
    rows = checks.get('inputs')
    if not P.valid_input_rows(rows):
        return 2, [f'cannot verify: {path} records no inputs (it was written before check.py recorded them); run '
                   'check.py again to get a result that can be verified, or its input rows are malformed']
    if not P.valid_tools(checks.get('tools')):
        return 2, [f'cannot verify: {path} records missing or malformed tools; run check.py again']
    if checks.get('inputs_base') == 'project':
        root = P.find_project(Path(path).resolve().parent)
        if root is None:
            return 2, [f'cannot verify: {path} is not inside its recorded project']
        bases = [root]
    else:
        if any(not Path(row['path']).is_absolute() for row in rows):
            return 2, [f'cannot verify: {path} has relative inputs without a recorded project; run check.py again']
        bases = []
    try:
        changes = P.input_changes(rows, bases, thorough=True)
        tools = tool_changes(checks['tools'])
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
        return 2, [f'cannot verify: {path}: {error}']
    lines = [f"  input {row['role']} {row['path']}: {row['change']}" for row in changes]
    for row in tools:
        was, now = row['was'], row['now']
        if isinstance(was, str) and re.fullmatch(r'[0-9a-f]{64}', was or ''):
            was = was[:12]
        if isinstance(now, str) and re.fullmatch(r'[0-9a-f]{64}', now or ''):
            now = now[:12]
        lines.append(f"  tool {row['tool']}: {was} -> {now}")
    if changes or tools:
        return 1, [f'changed: {len(changes)} input(s) and {len(tools)} tool(s) differ from when {Path(path).name} '
                   'was written; run check.py again'] + lines
    return 0, [f'current: all {len(rows)} recorded inputs' + ' and the tools'
               + f' match {Path(path).name}'] + lines


def print_checks(checks):
    """One line per item, then the readiness line."""
    marks = {'pass': 'ok  ', 'look': 'LOOK', 'fail': 'FAIL', 'you': 'you ', 'skip': 'skip',
             'unconfirmed': 'unconfirmed'}
    for entry in checks['items']:
        detail = f"  ({entry['detail']})" if entry['detail'] else ''
        at = f" at {P.format_time(entry['at'])}" if isinstance(entry.get('at'), (int, float)) else ''
        print(f"  {marks[entry['state']]}  {entry['label']}{at}{detail}")
    line = P.readiness(checks['summary'])
    if checks['summary'].get('unconfirmed'):
        line += f"; {checks['summary']['unconfirmed']} unconfirmed"
    print(line)


def add_file_arguments(parser):
    """The --file options: the export, what it should be, and the editor's inputs to check it against."""
    parser.add_argument('--file', help="check one video file, such as an editor's export, outside a project")
    parser.add_argument('--against', help='the file before this edit')
    parser.add_argument('--edit', help='trim:A,B, speed:X (duration factor), reframe, convert, extract-audio, '
                                       'captions or compress')
    parser.add_argument('--spec', help='expected WIDTHxHEIGHT[@FPS] for --file')
    parser.add_argument('--duration', type=float, help='expected duration in seconds for --file')
    parser.add_argument('--allow-bars', action='store_true', help='the black borders in --file are intentional')
    parser.add_argument('--vcodec', help='expected video codec for --file (default h264)')
    parser.add_argument('--pix-fmt', help='expected pixel format for --file (default yuv420p)')
    parser.add_argument('--color', help='expected colour primaries, transfer and matrix tag for --file (default bt709)')
    parser.add_argument('--delivery', help='expected delivery settings as JSON (--file); flags override it')
    parser.add_argument('--captions', help='the caption sidecar delivered with the file (SRT, WebVTT or caption JSON)')
    parser.add_argument('--caption-profile', help='a house style for captions.py check --profile')
    parser.add_argument('--timeline', help="the editor's timeline as Final Cut Pro 7 XML (--file)")
    parser.add_argument('--project', dest='timeline_project',
                        help='with --timeline: a project folder whose map holds the source transcripts')
    parser.add_argument('--source-words', action='extend', nargs='+', metavar='FILE',
                        help='with --timeline: source transcripts (words.json), passed to exchange.py words')
    parser.add_argument('--map', action='append', default=[], metavar='FILE=ALIAS',
                        help='with --timeline: use transcript ALIAS for timeline file FILE (exchange.py words)')
    parser.add_argument('--track', type=int, help='with --timeline: the audio track to read (default 1)')
    parser.add_argument('--edit-words', help='edit-time words already made by exchange.py words (--file)')
    parser.add_argument('--speech-words', help='a transcript of this export (transcribe.py words.json) (--file)')
    parser.add_argument('--json', help='write checks.json here (--file mode); never over an input')


FILE_ONLY = ('spec', 'duration', 'allow_bars', 'vcodec', 'pix_fmt', 'color', 'delivery', 'timeline', 'against', 'edit',
             'timeline_project', 'source_words', 'map', 'track', 'edit_words', 'speech_words', 'json')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project', nargs='?', help='project folder (or any folder inside it)')
    parser.add_argument('--version', help='version to check (default: the current one)')
    parser.add_argument('--final', help='a final file to check instead of the preview, with loudness and true peak')
    parser.add_argument('--no-speech', action='store_true',
                        help='do not transcribe the audio to compare the captions with the speech')
    parser.add_argument('--target', '--loudness', dest='loudness', type=float, default=None,
                        help='optional integrated loudness target in LUFS')
    parser.add_argument('--verify', metavar='CHECKS.json',
                        help='re-hash the inputs and tools a checks file recorded: current (0) or what changed (1)')
    parser.add_argument('--strict', action='store_true', help='treat unconfirmed or unassessed context and sync as looks')
    parser.add_argument('--stress', action='store_true', help='screen delivery and a low-bitrate proxy')
    add_file_arguments(parser)
    args = parser.parse_args()
    P.safe_output()
    try:
        if args.verify:
            code, lines = verify(args.verify)
            print('\n'.join(lines))
            return code
        if args.file:
            checks = check_file(args)
        else:
            given = [name for name in FILE_ONLY if getattr(args, name) not in (None, False, [])]
            if given:
                flags = ', '.join('--' + name.replace('timeline_project', 'project').replace('_', '-')
                                  for name in given)
                raise ValueError(f'{flags} go with --file EXPORT; a project is checked with check.py PROJECT')
            root = P.find_project(args.project or '.')
            if root is None:
                raise ValueError('no project folder here; give one, or use --file for a single video')
            checks = check_project(root, args.version, args.final, not args.no_speech, args.loudness, args.captions,
                                   args.caption_profile, args.stress)
        print_checks(checks)
        summary = checks['summary']
        strict_items = any(entry.get('group') in ('context', 'sync') and
                           entry['state'] in ('unconfirmed', 'skip') for entry in checks['items'])
        return 1 if summary['fail'] or summary['look'] or (args.strict and strict_items) else 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
