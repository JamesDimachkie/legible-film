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
  check;
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
  faster-whisper it is not assessed and says how to install it;
- title contrast, when the version has titles: each title's letters against the picture around them at its midpoint
  (a look below 3:1, naming for each low title the nearest colour and the black plate that would reach 3.3:1 against
  the ground measured there, with their ratios); full-frame cards are not measured;
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
import importlib.util
import json
import math
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
PACKAGES = {'PIL': 'Pillow', 'cv2': 'opencv-python', 'faster_whisper': 'faster-whisper'}
QA_FILES = ('qc.json', 'flash_scan.json', 'blank_scan.json', 'captions-rules.json', 'captions-edit.json',
            'captions-speech.json', 'speech-words.json', 'captions-check.json', 'captions-contrast.json',
            'titles-contrast.json', 'technical.json')
TITLE_CONTRAST = 3.0
# A suggested title colour or plate aims this far above the floor, so a re-encode does not tip it back under.
SUGGEST_MARGIN = 1.1
DROPOUT_DB = -80
DROPOUT_S = 0.08
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
        module = missing.group(1).split('.')[0]
        if module in ('PIL', 'numpy', 'faster_whisper', 'onnxruntime'):
            return f'{name} could not run: {P.dependency_message(module)}'
        return (f'{name} could not run: the Python module {module} is missing; install it: '
                f'pip install {PACKAGES.get(module, module)}')
    if re.search(r'ffmpeg|ffprobe', output, re.IGNORECASE) and re.search(r'not found|no such file|cannot find',
                                                                          output, re.IGNORECASE):
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


def dropout_item(video, has_audio):
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
    result = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-i', str(video), '-map', '0:a:0', '-af',
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
    more = f' and {len(holes) - 8} more' if len(holes) > 8 else ''
    return item('dropouts', f'{len(holes)} hole(s) in the sound', 'look',
                f'digital silence at {listed}{more}: the room tone drops out. Fill each with room tone from a quiet '
                f'moment of the same source (a ~ music line under it), or move the edge past it; a silence you '
                f'designed can stay', holes[0][0])


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
        return item('flash', 'Possible flashing pattern, or camera movement', 'look',
                    f'{len(flagged)} window(s) where a pattern detector counted more than three reversals in a '
                    'second; camera movement over fine detail also does this. Watch the moment at normal speed: a '
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


def rules_item(srt, fresh, profile=None):
    """Caption reading rules: line length, lines and overlaps fail; reading speed, duration and gaps are looks. With a
    house style (`profile`), captions.py check --profile applies its limits and reviewed exceptions."""
    args = ['check', srt] + (['--profile', profile] if profile else []) + ['--json', fresh / 'captions-rules.json']
    report, why = run_report('captions.py', args, fresh / 'captions-rules.json')
    if report is None:
        return item('captions_rules', 'Caption reading rules', 'skip', why)
    findings, review, cues = report.get('findings') or [], report.get('review') or [], report.get('cues', 0)
    style = f' (house style {Path(profile).name})' if profile else ''
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


def coverage_note(report):
    """What the speech comparison examined, or None when the report does not say (then no match is claimed)."""
    coverage = (report.get('timing_screen') or {}).get('coverage')
    if not isinstance(coverage, dict) or not isinstance(coverage.get('words'), int):
        return None
    if coverage['words'] == 0:
        return 'no speech was heard'
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
    if captions is None and (not srt.is_file() or not P.read_text(srt).strip()):
        return []
    items = [with_note(rules_item(srt, fresh, profile), note),
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
    items += [rules_item(captions, fresh, plan.get('profile')), edit]
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


def summarise(items):
    """Counts per state."""
    summary = {state: 0 for state in ('pass', 'look', 'fail', 'you', 'skip')}
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
               pix_fmt='yuv420p', color='bt709', captions_check=None, fps=None, duration_independent=False):
    """Run the checks for one file in a fresh folder and return the checks.json content; with `qa`, this run's raw
    outputs replace the previous run's there. `speech` is (model, language) to compare captions with the audio.
    `captions_check(video, fresh, has_audio)` returns the caption items when given (--file and a final's sidecar);
    otherwise a project version's own captions are checked. Items not assessed are labelled so."""
    if target is not None and not math.isfinite(target):
        raise ValueError('loudness target must be finite')
    with tempfile.TemporaryDirectory(prefix='lf-check-') as name:
        fresh = Path(name)
        qc_args = [video, '--json', fresh / 'qc.json', '--vcodec', vcodec, '--pix-fmt', pix_fmt, '--color', color,
                   '--technical']
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
            qc_args += ['--lossy-check', '--faststart'] if has_audio_stream(video) else ['--faststart']
        qc, why = run_report('qc_file.py', qc_args, fresh / 'qc.json')
        if qc is None:
            raise RuntimeError(why)
        has_audio = bool(qc.get('audio'))
        basis = ', '.join(part for part in (
            spec and f'{spec}', f'{vcodec.upper().replace("H264", "H.264")}', pix_fmt, f'{color.upper()} tags',
            'fast start' if final else '') if part)
        basis += ' (the web defaults unless --delivery or the flags name another)' if final and not spec else ''
        items = [spec_item(qc, basis)] + loudness_items(qc, target, final, has_audio)
        declaration = P.load_json(captions_folder / 'declared.json', {}) if captions_folder else {}
        items.append(first_frame_item(video, declaration))
        edges = edges_item(qc, has_audio, sound_past_picture(captions_folder, expected_frames))
        if edges:
            items.append(edges)
        dropouts = dropout_item(video, has_audio)
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
        items += person_items(reviewed, has_audio, any(entry['id'] == 'captions_rules' for entry in captions))
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


VERSION_INPUTS = (('lines', 'lines.json'), ('edit', 'edit.json'), ('film', 'film.md'), ('declared', 'declared.json'),
                  ('manifest', 'manifest.json'), ('caption_burn', 'caption-burn.json'))


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


def project_inputs(root, folder, video, digest, final, captions, speech, profile=None):
    """The inputs a project check depends on: the checked file, the captions checked, the version's lines.json,
    edit.json, film.md, declared.json, manifest.json and caption-burn.json (recorded as absent when missing, so adding
    one expires the result), title assets, the map transcript candidates and listing used for speech settings, and
    the spatial layers the edit draws."""
    rows = [P.input_row('final' if final else 'preview', video, project_path(root, video), digest),
            P.input_row('captions', captions, project_path(root, captions))]
    rows += [P.input_row(role, folder / name, project_path(root, folder / name)) for role, name in VERSION_INPUTS]
    rows += [P.input_row('title_asset', path, project_path(root, path)) for path in title_assets(folder)]
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


def check_project(root, version=None, final_file=None, speech=True, target=None, captions=None, profile=None):
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
    inputs = project_inputs(root, folder, video, digest, bool(final_file), srt, speech, profile)
    prefix = 'final-' if final_file else ''
    outputs = [folder / 'qa' / (prefix + name) for name in QA_FILES]
    outputs += [folder / 'checks.json', folder / 'checks-final.json', root / 'status.json']
    P.refuse_overwriting_inputs(outputs, [P.locate_input(row['path'], [root]) for row in inputs] + check_tool_inputs())
    note = project_caption_note(root, srt, bool(captions), bool(final_file))
    speech_pair = (model, language) if speech else None

    def caption_check(checked, fresh, has_audio):
        return caption_items(folder, checked, fresh, speech_pair, has_audio, captions, note, profile)

    checks = run_checks(video, folder / 'qa', spec, manifest.get('duration_s'), bool(final_file), target, reviewed,
                        folder, speech_pair, manifest.get('frames'),
                        settings.get('bars', '').lower() in ('allow', 'allowed', 'yes', 'true'),
                        captions_check=caption_check)
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
    return {'spec': spec, 'fps': fps, 'duration': duration, 'frames': frames,
            'target': args.loudness if args.loudness is not None else wanted.get('loudness'),
            'vcodec': args.vcodec or wanted.get('vcodec') or 'h264',
            'pix_fmt': args.pix_fmt or wanted.get('pix_fmt') or 'yuv420p',
            'color': args.color or wanted.get('color') or 'bt709',
            'bars': bool(args.allow_bars or wanted.get('allow_bars')),
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
    if args.timeline and args.edit_words:
        raise ValueError('give --timeline (with --project or --source-words) or --edit-words, not both')
    if args.timeline and not (args.timeline_project or args.source_words):
        raise ValueError('--timeline needs the source transcripts: --project DIR (its map) or --source-words FILE')
    if (args.timeline_project or args.source_words or args.map or args.track) and not args.timeline:
        raise ValueError('--project, --source-words, --map and --track go with --timeline XML')
    for role, path in file_inputs(args):
        if role not in ('map_sources', 'source_words', 'timeline_media', 'source_media', 'map_transcript_listing') \
                and not Path(path).is_file():
            raise ValueError(f'no {role.replace("_", " ")} file: {path}')
    if args.timeline_project and not (Path(args.timeline_project) / 'map' / 'sources.json').is_file():
        raise ValueError(f'--project {args.timeline_project} has no map/sources.json; is it a project folder?')
    for path in args.source_words or []:
        if not Path(path).is_file():
            raise ValueError(f'no source words file: {path}')


def check_file(args):
    """Check an editor's export as delivered (--file): its spec, sound and picture, and with the inputs given its
    captions, the timeline's words and a transcript of its speech. Returns checks.json content with its inputs and
    tools recorded; --json naming any input is refused before anything runs."""
    INVOKED.clear()
    validate_file_args(args)
    named = file_inputs(args)
    P.refuse_overwriting_inputs([args.json], [path for _, path in named] + check_tool_inputs())
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

    checks = run_checks(video, None, wanted['spec'], wanted['duration'], True, wanted['target'],
                        expected_frames=wanted['frames'], bars_allowed=wanted['bars'], vcodec=wanted['vcodec'],
                        pix_fmt=wanted['pix_fmt'], color=wanted['color'], captions_check=caption_check,
                        fps=wanted['fps'], duration_independent=True)
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
    marks = {'pass': 'ok  ', 'look': 'LOOK', 'fail': 'FAIL', 'you': 'you ', 'skip': 'skip'}
    for entry in checks['items']:
        detail = f"  ({entry['detail']})" if entry['detail'] else ''
        at = f" at {P.format_time(entry['at'])}" if isinstance(entry.get('at'), (int, float)) else ''
        print(f"  {marks[entry['state']]}  {entry['label']}{at}{detail}")
    print(P.readiness(checks['summary']))


def add_file_arguments(parser):
    """The --file options: the export, what it should be, and the editor's inputs to check it against."""
    parser.add_argument('--file', help="check one video file, such as an editor's export, outside a project")
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


FILE_ONLY = ('spec', 'duration', 'allow_bars', 'vcodec', 'pix_fmt', 'color', 'delivery', 'timeline',
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
                                   args.caption_profile)
        print_checks(checks)
        summary = checks['summary']
        return 1 if summary['fail'] or summary['look'] else 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
