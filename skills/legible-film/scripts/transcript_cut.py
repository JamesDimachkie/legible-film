#!/usr/bin/env python3
"""Build picture and dialogue edit items from a timed transcript and selects.

  transcript_cut.py transcript.json --selects selects.txt --source interview.mp4 --out edit.json

Use one zero-based inclusive range (0-4) or quoted phrase per line. Phrases
match ignoring case and punctuation. Repeats choose the next occurrence after
the previous select; append @2 to a phrase to choose its second occurrence.
--shots accepts a JSON list of shot boundary times, or motion_scan.py's JSON
report containing cuts[].time_s. Without shot boundaries, same-shot status is
unknown. --audio measures silence; otherwise word gaps are estimated silence.
The assembler still must snap to picture presentation timestamps and verify the
snap does not enter a word. Exit 0 clean, 1 findings, 2 unable to run.
"""
import argparse
import bisect
from fractions import Fraction
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def find_tool(name, explicit=None):
    """Find an explicit executable, environment override or PATH tool."""
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if os.path.isfile(candidate) or shutil.which(candidate) else None
    return shutil.which(name)


def words_from(data):
    """Read and validate nonoverlapping timed words."""
    if isinstance(data, list):
        words = data
    elif isinstance(data, dict) and 'segments' in data:
        words = [word for segment in data['segments'] for word in segment.get('words', [])]
    elif isinstance(data, dict):
        words = data.get('words', [])
    else:
        words = []
    result = []
    for word in words:
        start, end = float(word['start']), float(word['end'])
        text = str(word['word']).strip()
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or not text:
            raise ValueError('invalid word timing or text')
        if result and start < result[-1]['end']:
            raise ValueError('overlapping or unordered word timings')
        result.append(dict(word, start=start, end=end, word=text))
    if not result:
        raise ValueError('no timed words')
    return result


def tokens(text):
    """Normalise case and punctuation for phrase matching."""
    return re.findall(r'[^\W_]+', text.casefold(), re.UNICODE)


def source_duration(ffprobe, path):
    """Probe the actual source duration before placing its final cut."""
    command = [ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', path]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('source probe failed: ' + result.stderr[-500:])
    duration = float(json.loads(result.stdout)['format']['duration'])
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('source duration unavailable')
    return duration


def read_shots(path, duration):
    """Read explicit boundary times or motion_scan cut times."""
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if isinstance(data, dict):
        data = data.get('cuts')
    if not isinstance(data, list):
        raise ValueError('shot boundaries must be a list or motion_scan cuts report')
    values = [float(item['time_s'] if isinstance(item, dict) else item) for item in data]
    if any(not math.isfinite(value) or value < 0 or value > duration for value in values):
        raise ValueError('invalid shot boundary')
    return sorted(set(values))


def detect_silence(ffmpeg, path, threshold, duration):
    """Measure intervals below the supplied threshold with FFmpeg."""
    command = [ffmpeg, '-hide_banner', '-nostdin', '-i', path, '-af',
               'silencedetect=noise={}dB:d={}'.format(threshold, duration), '-f', 'null', '-']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('audio decode failed: ' + result.stderr[-500:])
    events = re.findall(r'silence_(start|end):\s*([\d.]+)', result.stderr)
    intervals = []
    start = None
    for kind, value in events:
        if kind == 'start':
            start = float(value)
        elif start is not None:
            intervals.append((start, float(value)))
            start = None
    if start is not None:
        intervals.append((start, float('inf')))
    return intervals


def resolve_selects(selects, words):
    """Choose requested or next phrase occurrences and report their indices."""
    flattened = []
    owners = []
    for index, word in enumerate(words):
        pieces = tokens(word['word'])
        flattened.extend(pieces)
        owners.extend([index] * len(pieces))
    selected = []
    missing = []
    previous_end = -1
    for select in selects:
        match = re.fullmatch(r'(\d+)\s*-\s*(\d+)', select)
        phrase = re.fullmatch(r'''(["'])(.*?)\1(?:\s*@\s*(\d+))?''', select)
        if match:
            start, end = map(int, match.groups())
            if start > end or end >= len(words):
                raise ValueError('invalid word range: ' + select)
            occurrence = None
            method = 'range'
        elif phrase:
            wanted = tokens(phrase.group(2))
            occurrences = [(owners[index], owners[index + len(wanted) - 1])
                           for index in range(len(flattened))
                           if wanted and flattened[index:index + len(wanted)] == wanted]
            requested = int(phrase.group(3)) if phrase.group(3) else None
            if requested is not None:
                choice = requested - 1
                method = 'explicit occurrence'
            else:
                choice = next((index for index, item in enumerate(occurrences) if item[0] > previous_end), -1)
                method = 'next after previous select'
            if choice < 0 or choice >= len(occurrences):
                missing.append(select)
                continue
            start, end = occurrences[choice]
            occurrence = choice + 1
        else:
            raise ValueError('select must be a quoted phrase or inclusive word range: ' + select)
        selected.append({'select': select, 'first_word': start, 'last_word': end,
                         'occurrence': occurrence, 'method': method})
        previous_end = end
    return selected, missing


def choose_boundary(left, right, desired, intervals, label, findings):
    """Choose the point nearest the desired handle within a word gap and silence."""
    if right < left:
        raise ValueError('no word gap at ' + label)
    if intervals is None:
        candidates = [(left, right)]
    else:
        candidates = [(max(left, start), min(right, end)) for start, end in intervals
                      if min(right, end) >= max(left, start)]
    if not candidates:
        findings.append('no measured silence in ' + label)
        return min(right, max(left, desired))
    return min((min(end, max(start, desired)) for start, end in candidates), key=lambda point: abs(point - desired))


def make_edit(words, selected, args, duration, silences, shots):
    """Build edit items and describe source joins and shot classification."""
    picture = []
    audio = []
    joins = []
    findings = []
    cursor = 0.0
    for select in selected:
        first, last = select['first_word'], select['last_word']
        before = words[first - 1]['end'] if first else 0
        after = words[last + 1]['start'] if last + 1 < len(words) else duration
        start = choose_boundary(before, words[first]['start'], words[first]['start'] - args.handle,
                                silences, 'before ' + select['select'], findings)
        end = choose_boundary(words[last]['end'], after, words[last]['end'] + args.handle,
                              silences, 'after ' + select['select'], findings)
        if end <= start:
            raise ValueError('empty selected cut: ' + select['select'])
        if picture:
            previous = picture[-1]
            gap = start - previous['out']
            # The outgoing frame precedes its out point; the incoming frame starts at its in point.
            earlier_shot = bisect.bisect_left(shots, previous['out']) if shots is not None else None
            later_shot = bisect.bisect_right(shots, start) if shots is not None else None
            same_shot = earlier_shot == later_shot if shots is not None else None
            joins.append({'at': cursor, 'source_gap_s': gap, 'same_shot': same_shot,
                          'jump_cut_candidate': same_shot and abs(gap) > 1e-6 if shots is not None else None})
        picture.append({'src': 'a', 'in': start, 'out': end, 'speed': 1.0, 'fit': 'cover',
                        'join': {'kind': 'cut'}, 'last_word': last})
        audio.append({'track': 'dialogue', 'src': 'a', 'in': start, 'out': end, 'at': cursor, 'fade_ms': 12})
        cursor += end - start
    for item in picture:
        del item['last_word']
    edit = {'version': 1, 'title': 'Transcript selects', 'size': args.output_size, 'fps': args.fps,
            'sources': {'a': {'file': args.source}}, 'picture': picture, 'audio': audio, 'overlays': [], 'cues': []}
    return edit, joins, findings, cursor


def frame_rate(text):
    """Keep a frame rate as written (30, 29.97 or 30000/1001) for edit.json; assemble.py reads it exactly."""
    try:
        value = Fraction(text.strip())
    except (ValueError, ZeroDivisionError):
        raise argparse.ArgumentTypeError(f'not a frame rate: {text}')
    if value <= 0:
        raise argparse.ArgumentTypeError('fps must be positive')
    if '/' in text:
        return text.strip()
    return int(value) if value.denominator == 1 else float(text)


def main():
    """Parse inputs, remove a stale output, and write a bounded edit and report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('transcript')
    parser.add_argument('--selects', required=True)
    parser.add_argument('--source', required=True, help='source file recorded in edit.json')
    parser.add_argument('--out', required=True)
    parser.add_argument('--audio', help='source audio for measured silence')
    parser.add_argument('--shots', help='JSON shot boundaries or motion_scan.py report')
    parser.add_argument('--handle', type=float, default=.15, help='desired seconds outside selected speech')
    parser.add_argument('--target', type=float, help='target duration in seconds')
    parser.add_argument('--size', default='1920x1080')
    parser.add_argument('--fps', type=frame_rate, default=30, help='30, 29.97 or 30000/1001')
    parser.add_argument('--silence-db', type=float, default=-35)
    parser.add_argument('--silence-duration', type=float, default=.02)
    parser.add_argument('--json', help='write report here')
    parser.add_argument('--ffmpeg')
    parser.add_argument('--ffprobe')
    args = parser.parse_args()
    try:
        output = Path(args.out).resolve()
        protected = [args.transcript, args.selects, args.source, args.audio, args.shots, args.json]
        if any(value and Path(value).resolve() == output for value in protected):
            raise ValueError('output must differ from input and report paths')
        if output.exists():
            output.unlink()
        if (not math.isfinite(args.handle) or args.handle < 0
                or not math.isfinite(args.silence_duration) or args.silence_duration <= 0):
            raise ValueError('handle must be nonnegative; silence duration must be positive')
        args.output_size = [int(value) for value in args.size.lower().split('x')]
        if len(args.output_size) != 2 or min(args.output_size) <= 0:
            raise ValueError('size must be WIDTHxHEIGHT')
        ffprobe = find_tool('ffprobe', args.ffprobe)
        if not ffprobe:
            raise ValueError('ffprobe not found')
        duration = source_duration(ffprobe, args.source)
        words = words_from(json.loads(Path(args.transcript).read_text(encoding='utf-8-sig')))
        if words[-1]['end'] > duration + 1e-6:
            raise ValueError('word timings extend beyond source duration')
        selects = [line.strip() for line in Path(args.selects).read_text(encoding='utf-8-sig').splitlines()
                   if line.strip() and not line.lstrip().startswith('#')]
        if not selects:
            raise ValueError('no selects')
        silences = None
        if args.audio:
            ffmpeg = find_tool('ffmpeg', args.ffmpeg)
            if not ffmpeg:
                raise ValueError('ffmpeg not found')
            silences = detect_silence(ffmpeg, args.audio, args.silence_db, args.silence_duration)
        shots = read_shots(args.shots, duration)
        selected, missing = resolve_selects(selects, words)
        edit, joins, findings, elapsed = make_edit(words, selected, args, duration, silences, shots)
        report = {'selected': selected, 'missing': missing, 'findings': findings, 'joins': joins,
                  'duration_s': elapsed, 'source_duration_s': duration, 'target_s': args.target,
                  'difference_s': None if args.target is None else elapsed - args.target,
                  'silence_basis': 'audio' if args.audio else 'word gaps',
                  'shot_basis': 'supplied boundaries' if shots is not None else 'unknown',
                  'frame_snap': 'not performed; assembler must verify snapped points remain outside words'}
        if selected and not findings and not missing:
            output.write_text(json.dumps(edit, indent=2), encoding='utf-8')
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        return 1 if missing or findings or any(join['jump_cut_candidate'] for join in joins) else 0
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
