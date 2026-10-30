#!/usr/bin/env python3
"""Build, check or burn captions from a common timed source.

  captions.py build words.json --out captions
  captions.py check captions.srt [--audio speech.wav | --words words.json] [--burned captioned.mp4]
  captions.py burn picture.mp4 captions.json --out captioned.mp4 [--size 360x640] [--safe L,T,R,B] [--avoid X,Y,W,H]

Build writes SRT, WebVTT and word-timed JSON. Input JSON is a WhisperX-style
segments object, a list of timed words, or timed lines with start, end and text.
Timed-line word times are estimates, apportioned by character count, and must be
reviewed against speech. The burned screen estimates text edges and contrast from frame changes; motion
can confound it and results need inspection. The timing screen uses word timings
when supplied or a
band-limited audio envelope otherwise. Neither identifies speech or proves alignment.

Check sorts what it finds into two lists. Findings are errors: invalid or overlapping
times, too many or too long lines, and, given --words (a word-timed transcript of the
current audio), caption words no longer spoken under the caption (cut from the dialogue but left
on screen), a caption over no matching speech, and a whole file offset from the
dialogue. Review prompts are measurements for a person to judge, never reasons to merge
or retime automatically: reading speed, duration, single-word lines, gaps under the
limit, words spoken but not captioned, and when a caption enters and leaves against the
speech, in seconds. Short captions are often intentional.

The default limits are 20 characters/s, 42 characters/line, two lines, 0.8-7 s,
and 0.04 s between events. Use --cps 17 for children's captions. Exit 0 when
there are no findings (review prompts may be listed), 1 for findings, 2 when unable
to run.
"""
import argparse
import bisect
import collections
import difflib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ARTICLES = {'a', 'an', 'the', 'this', 'that', 'these', 'those', 'each', 'every', 'some', 'our', 'your'}
CONNECTORS = {'and', 'but', 'or', 'yet', 'so', 'because', 'although', 'while', 'when', 'if', 'as',
              'of', 'to', 'in', 'on', 'at', 'for', 'from', 'with', 'by', 'about', 'into', 'over', 'under'}
UNITS = {'gb', 'mb', 'kb', 'tb', 'fps', 'hz', 'khz', 'mhz', 'ms', 's', 'seconds', 'minutes', 'hours',
         'days', 'weeks', 'months', 'years', 'percent', 'kg', 'g', 'km', 'm', 'px', 'pixels', 'lu', 'db'}
ADJECTIVES = {'new', 'old', 'small', 'large', 'short', 'long', 'high', 'low', 'first', 'last', 'other',
              'good', 'great', 'best', 'real', 'whole', 'same', 'next', 'local', 'public', 'simple',
              'readable', 'synthetic', 'careful', 'carefully', 'red', 'blue', 'green', 'black', 'white',
              'orange', 'yellow', 'quick', 'slow', 'bright', 'dark', 'warm', 'cold', 'strong', 'weak'}


def find_tool(name, explicit=None):
    """Find an explicitly supplied executable, environment override or PATH tool."""
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if os.path.isfile(candidate) or shutil.which(candidate) else None
    return shutil.which(name)


def timestamp(value, vtt=False):
    """Format seconds to the millisecond sidecar timebase."""
    ms = round(value * 1000)
    hours, ms = divmod(ms, 3600000)
    minutes, ms = divmod(ms, 60000)
    seconds, ms = divmod(ms, 1000)
    return '%02d:%02d:%02d%s%03d' % (hours, minutes, seconds, '.' if vtt else ',', ms)


def parse_timestamp(value):
    """Parse an SRT or WebVTT timestamp."""
    parts = value.strip().replace(',', '.').split(':')
    if len(parts) == 2:
        parts.insert(0, '0')
    if len(parts) != 3:
        raise ValueError('invalid timestamp: ' + value)
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def read_json_items(data):
    """Flatten supported transcript and caption JSON objects."""
    if isinstance(data, dict) and 'cues' in data:
        return data['cues']
    if isinstance(data, dict) and 'segments' in data:
        return [word for segment in data['segments'] for word in (segment.get('words') or [segment])]
    if isinstance(data, dict):
        return data.get('words', data.get('lines', []))
    if isinstance(data, list):
        return data
    raise ValueError('expected timed items')


MARKUP = re.compile(r'<[^<>\n]{1,200}>|\{\\[^{}\n]{0,200}\}')


def plain_text(text):
    """Caption text as a viewer reads it: SRT and WebVTT styling and voice tags (<font color=...>, <i>, <v Name>,
    <00:00:01.000>), ASS overrides ({\\an8}) and HTML entities removed, so they count neither as words nor as
    characters."""
    return html.unescape(MARKUP.sub('', text)).strip()


def read_input(path):
    """Read a JSON transcript or SRT/WebVTT events."""
    content = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    if str(path).lower().endswith('.json'):
        result = []
        for item in read_json_items(json.loads(content)):
            cue = dict(item)
            cue['start'] = float(item['start'])
            cue['end'] = float(item['end'])
            cue['text'] = plain_text(str(item.get('word', item.get('text', ''))))
            result.append(cue)
        return result
    cues = []
    for block in re.split(r'\n\s*\n', content.strip()):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION')):
            continue
        index = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if index is None:
            raise ValueError('caption block has no timing line')
        start, end = lines[index].split('-->', 1)
        cues.append({'start': parse_timestamp(start), 'end': parse_timestamp(end.strip().split()[0]),
                     'text': plain_text('\n'.join(lines[index + 1:]))})
    if not cues:
        raise ValueError('no caption events')
    return cues


def split_timed_lines(items, gap=0, overlap=False):
    """Estimate word boundaries within timed lines and preserve actual word timings. With `overlap`, words of
    different speakers may overlap in time; they are returned in time order."""
    result = []
    estimated = False
    for item in items:
        if item.get('words'):
            nested, was_estimated = split_timed_lines(item['words'], gap, overlap)
            result.extend(nested)
            estimated = estimated or was_estimated
            continue
        text = str(item.get('text', item.get('word', ''))).strip()
        parts = text.split()
        if not parts:
            # An empty row (a stretch the transcriber returned no word for) is evidence of a gap, not speech.
            continue
        start = float(item['start'])
        end = float(item['end'])
        if len(parts) == 1:
            # A word whose times the transcript marks as estimated keeps the mark: its edges are not measured.
            result.append({'text': parts[0], 'start': start, 'end': end,
                           **({'estimated': True} if item.get('estimated') else {})})
            continue
        estimated = True
        total = sum(len(part) for part in parts)
        offset = 0
        for part_index, part in enumerate(parts):
            left = start + (end - start) * offset / total
            offset += len(part)
            right = start + (end - start) * offset / total
            if part_index < len(parts) - 1:
                right -= min(gap + .002, (right - left) / 4)
            result.append({'text': part, 'start': left, 'end': right, 'estimated': True})
    if overlap:
        result.sort(key=lambda word: (word['start'], word['end']))
    for index, word in enumerate(result):
        start, end = word['start'], word['end']
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError('invalid word timing')
        if index and not overlap and start < result[index - 1]['end'] - 1e-8:
            raise ValueError('word timings overlap or are unordered')
    return result, estimated


def bare(word):
    """Remove surrounding punctuation for linguistic heuristics."""
    return word.strip('.,!?;:()[]{}\"\'').casefold()


def capitalised(word):
    """Identify a capitalised token with letters."""
    word = word.lstrip('"\'([{')
    return bool(word and word[0].isupper() and any(char.isalpha() for char in word))


def protected_break(words, index):
    """Guard likely names, number phrases and noun modifiers at a word boundary."""
    if index <= 0 or index >= len(words):
        return False
    previous = words[index - 1]['text']
    current = words[index]['text']
    prev = bare(previous)
    cur = bare(current)
    if prev in ARTICLES or prev in ADJECTIVES or prev.endswith(('ous', 'ive', 'able', 'ible', 'ful', 'less')):
        return True
    if capitalised(previous) and capitalised(current) and prev not in ARTICLES and not re.search(r'[.!?]$', previous):
        return True
    if re.search(r'\d', previous) and (cur in UNITS or cur in {'a', 'per', '%'}):
        return True
    if index >= 2 and prev in {'a', 'per'} and re.search(r'\d', words[index - 2]['text']):
        return True
    return False


def break_score(words, index):
    """Rank sentence, clause and connector breaks, in that order."""
    if index == len(words):
        return 0
    previous = words[index - 1]['text']
    following = bare(words[index]['text'])
    if re.search(r'[.!?]["\']?$', previous):
        return 100
    if re.search(r'[,;:]["\']?$', previous):
        return 60
    if following in CONNECTORS:
        return 30
    return 0


def line_layout(words, limit):
    """Choose a legal one- or two-line layout, favouring phrase breaks."""
    texts = [word['text'] for word in words]
    text = ' '.join(texts)
    if len(text) <= limit:
        return text
    candidates = []
    for index in range(2, len(words) - 1):
        if protected_break(words, index):
            continue
        left = ' '.join(texts[:index])
        right = ' '.join(texts[index:])
        if len(left) <= limit and len(right) <= limit:
            candidates.append((break_score(words, index), -abs(len(left) - len(right)), left + '\n' + right))
    return max(candidates)[2] if candidates else None


def segment(words, args, diagnose=True):
    """Find the highest-scoring feasible layout using a Pareto frontier of end times."""
    count = len(words)
    frontiers = [[] for _ in range(count + 1)]
    frontiers[0] = [(0.0, 0, None)]
    blockers = set()
    for start_index in range(count):
        for prior_end, score, previous in frontiers[start_index]:
            for end_index in range(start_index + 1, count + 1):
                group = words[start_index:end_index]
                text = line_layout(group, args.line_length)
                if not text:
                    blockers.add('line length or two-line limit')
                    if sum(len(word['text']) for word in group) + len(group) - 1 > 2 * args.line_length + 1:
                        break
                    continue
                if len(group) == 1 and count > 1:
                    blockers.add('orphan word')
                    continue
                if end_index < count and protected_break(words, end_index):
                    blockers.add('protected name, number or noun phrase')
                    continue
                gap = args.gap if previous else 0
                earliest = math.ceil((prior_end + gap) * 1000 - 1e-8) / 1000
                first_speech = group[0]['start']
                if earliest > first_speech + 1e-9:
                    blockers.add('minimum gap')
                    continue
                needed = max(args.min_duration, len(text.replace('\n', ' ')) / args.cps)
                end = math.ceil(max(group[-1]['end'], earliest + needed) * 1000 - 1e-8) / 1000
                # The latest start with this earliest feasible end avoids needless anticipation.
                start = math.floor(min(first_speech, end - needed) * 1000 + 1e-8) / 1000
                if start < earliest - 1e-9:
                    blockers.add('minimum duration or characters per second')
                    continue
                if end - start > args.max_duration + 1e-9:
                    blockers.add('maximum duration')
                    if group[-1]['end'] - first_speech > args.max_duration + 1e-9:
                        break
                    continue
                cue = {'start': start, 'end': end, 'text': text, 'words': group}
                candidate = (end, score + break_score(words, end_index) - 1, (cue, previous))
                frontier = frontiers[end_index]
                if any(old_end <= end + 1e-9 and old_score >= candidate[1]
                       for old_end, old_score, _ in frontier):
                    continue
                frontiers[end_index] = [old for old in frontier
                                        if not (end <= old[0] + 1e-9 and candidate[1] >= old[1])]
                frontiers[end_index].append(candidate)
    if not frontiers[count]:
        text = ' '.join(word['text'] for word in words)
        if diagnose:
            relaxations = [('characters per second', 'cps', 1e9),
                           ('characters per line or two lines', 'line_length', 1000000),
                           ('minimum duration', 'min_duration', .001),
                           ('maximum duration', 'max_duration', 1e9),
                           ('minimum gap', 'gap', 0)]
            decisive = []
            for label, field, value in relaxations:
                trial = SimpleNamespace(**vars(args))
                setattr(trial, field, value)
                try:
                    segment(words, trial, diagnose=False)
                    decisive.append(label)
                except SegmentationError:
                    pass
            if decisive:
                raise SegmentationError('constraint preventing segmentation: ' + ', '.join(decisive), text)
        raise SegmentationError('interacting constraints: ' + ', '.join(sorted(blockers)), text)
    node = max(frontiers[count], key=lambda state: (state[1], -state[0]))[2]
    cues = []
    while node is not None:
        cue, node = node
        cues.append(cue)
    return list(reversed(cues))


class SegmentationError(Exception):
    """An input cannot be segmented without relaxing at least one rule."""

    def __init__(self, rule, text):
        super().__init__(rule + ': ' + text)
        self.rule = rule
        self.text = text


def validate(cues, args):
    """Caption rule breaks as findings (errors) and review prompts (measurements a person judges)."""
    findings = []
    review = []
    for index, cue in enumerate(cues):
        start, end = float(cue['start']), float(cue['end'])
        text = cue['text']
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            findings.append({'cue': index + 1, 'rule': 'invalid timing'})
            continue
        duration = end - start
        lines = text.split('\n')
        chars = len(' '.join(lines))
        errors = [('lines', len(lines) > 2), ('line length', any(len(line) > args.line_length for line in lines))]
        for rule, failed in errors:
            if failed:
                findings.append({'cue': index + 1, 'rule': rule})
        prompts = [('minimum duration', duration < args.min_duration - 1e-6, {'duration_s': round(duration, 3)}),
                   ('maximum duration', duration > args.max_duration + 1e-6, {'duration_s': round(duration, 3)}),
                   ('cps', chars / duration > args.cps + 1e-6, {'cps': round(chars / duration, 1)}),
                   ('orphan', len(lines) > 1 and any(len(line.split()) < 2 for line in lines), {})]
        for rule, flagged, measured in prompts:
            if flagged:
                review.append({'cue': index + 1, 'rule': rule, 'text': text, **measured})
        if index:
            gap = start - float(cues[index - 1]['end'])
            if gap < -1e-6:
                findings.append({'cue': index + 1, 'rule': 'overlap', 'gap_s': round(gap, 4)})
            elif gap < args.gap - 1e-6:
                review.append({'cue': index + 1, 'rule': 'gap', 'gap_s': round(gap, 4)})
    return findings, review


def write_sidecars(cues, prefix):
    """Write matching millisecond SRT and WebVTT plus word timings."""
    for extension in ('srt', 'vtt'):
        lines = ['WEBVTT\n'] if extension == 'vtt' else []
        for index, cue in enumerate(cues, 1):
            timing = timestamp(cue['start'], extension == 'vtt')
            timing += ' --> ' + timestamp(cue['end'], extension == 'vtt')
            lines.extend([str(index), timing, cue['text'], ''])
        Path(prefix + '.' + extension).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    Path(prefix + '.json').write_text(json.dumps({'cues': cues}, indent=2), encoding='utf-8')


def audio_regions(ffmpeg, path):
    """Estimate speech-band activity from 20 ms RMS windows and a measured floor."""
    cmd = [ffmpeg, '-v', 'error', '-i', path, '-af', 'highpass=f=300,lowpass=f=3400',
           '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode:
        raise ValueError('audio decode failed: ' + result.stderr.decode(errors='replace')[-500:])
    samples = np.frombuffer(result.stdout, dtype='<f4')
    block = 320
    count = len(samples) // block
    if not count:
        raise ValueError('audio too short for timing screen')
    frames = samples[:count * block].reshape(count, block).astype(np.float64)
    envelope = np.sqrt(np.mean(frames * frames, axis=1))
    floor = float(np.percentile(envelope, 20))
    threshold = max(.001, floor * 2.5)
    active = envelope > threshold
    # Bridge only short envelope dropouts; long pauses remain separate regions.
    for index in range(1, len(active) - 1):
        if not active[index] and active[index - 1] and active[index + 1]:
            active[index] = True
    edges = np.diff(np.r_[False, active, False].astype(np.int8))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    regions = [(int(start) * .02, int(end) * .02) for start, end in zip(starts, ends) if end - start >= 2]
    return regions, {'noise_floor_rms': floor, 'threshold_rms': threshold, 'window_s': .02}


def timing_screen(cues, regions, margin):
    """Compare cues to overlapping candidate regions, not recognised speech: a caption over no activity is a
    finding; its entrance and exit against the activity are review prompts."""
    findings = []
    review = []
    matched = []
    for index, cue in enumerate(cues):
        start, end = float(cue['start']), float(cue['end'])
        overlaps = [region for region in regions if region[1] > start and region[0] < end]
        if not overlaps:
            findings.append({'cue': index + 1, 'rule': 'no timing region in caption'})
            matched.append(None)
            continue
        first = min(region[0] for region in overlaps)
        last = max(region[1] for region in overlaps)
        matched.append([first, last])
        if first - start > margin + 1e-8:
            review.append({'cue': index + 1, 'rule': 'starts before timing region',
                           'difference_s': round(first - start, 4)})
        if end - last > margin + 1e-8:
            review.append({'cue': index + 1, 'rule': 'outlasts timing region',
                           'difference_s': round(end - last, 4)})
    return findings, review, matched


NON_DIALOGUE = re.compile(r'\[[^\]]*\]|\([^)]*\)|[\u266a\u266b]+')
SPEAKER_LABEL = re.compile(r"^\s*(?:-\s*)?[A-Z][A-Z0-9 .'-]{0,30}:(?=\s)", re.MULTILINE)


def tokens_of(text):
    """Comparable word tokens: case-folded letters and digits."""
    return re.findall(r'[^\W_]+', text.casefold(), re.UNICODE)


def dialogue_tokens(text):
    """The spoken words of a caption or transcript word: sound descriptions in brackets or parentheses, music symbols
    and speaker labels (NAME:) removed."""
    return tokens_of(SPEAKER_LABEL.sub(' ', NON_DIALOGUE.sub(' ', text)))


def middle(values):
    """The median of a non-empty list."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def ordered_offsets(cues, words, lookahead=2000):
    """Start and end offsets (speech minus caption) of the captions found in order as complete word sequences, each
    searched at most `lookahead` tokens past the previous match."""
    tokens = []
    owners = []
    for index, word in enumerate(words):
        for token in dialogue_tokens(word['text']):
            tokens.append(token)
            owners.append(index)
    positions = {}
    for position, token in enumerate(tokens):
        positions.setdefault(token, []).append(position)
    cursor = 0
    starts = []
    ends = []
    for cue in cues:
        target = dialogue_tokens(cue['text'])
        if not target:
            continue
        candidates = positions.get(target[0], [])
        k = bisect.bisect_left(candidates, cursor)
        while k < len(candidates) and candidates[k] < cursor + lookahead:
            found = candidates[k]
            if tokens[found:found + len(target)] == target:
                starts.append(words[owners[found]]['start'] - float(cue['start']))
                ends.append(words[owners[found + len(target) - 1]]['end'] - float(cue['end']))
                cursor = found + len(target)
                break
            k += 1
    return starts, ends


def entrance_and_exit(number, cue, region, margin, measured=(True, True)):
    """Review prompts for a caption entering or leaving more than the margin away from its matched speech. An edge
    whose word time the transcript marks as estimated is not measured (`measured` is (entrance, exit))."""
    first, last = region
    start, end = float(cue['start']), float(cue['end'])
    review = []
    for rule, seconds, edge in (('enters before the speech', first - start, 0),
                                ('enters after the speech starts', start - first, 0),
                                ('leaves before the speech ends', last - end, 1), ('outlasts the speech', end - last, 1)):
        if measured[edge] and seconds > margin + 1e-8:
            review.append({'cue': number, 'rule': rule, 'difference_s': round(seconds, 4)})
    return review


def check_word_timing(cues, words, margin, reach=.5):
    """Compare each caption with the words spoken under it in a word-timed transcript of the current audio.

    Each caption is matched, in order and one word to one caption, against the words overlapping it (or within
    `reach` seconds of it). A caption word not spoken there is stale (cut from the dialogue, left on screen); a
    caption matching nothing there is false or misplaced, even when the same words are spoken further away. A whole
    file offset (starts and ends of the captions found in order shifted together, by over 0.5 s) is reported once and
    allowed for when matching. Sound descriptions ([laughs], music symbols) are left for review. Entrances, exits and
    words spoken but not captioned are review prompts, measured against the actual speech."""
    words = sorted(words, key=lambda word: (word['start'], word['end']))
    starts = [word['start'] for word in words]
    longest = max((word['end'] - word['start'] for word in words), default=0.0)

    def around(start, end):
        """Indexes of the words overlapping start..end, by bisection on the sorted starts."""
        low = bisect.bisect_left(starts, start - longest)
        high = bisect.bisect_left(starts, end)
        return [index for index in range(low, high) if words[index]['end'] > start]

    findings = []
    review = []
    shift = 0.0
    head, tail = ordered_offsets(cues, words)
    if len(head) >= 3:
        early, late = middle(head), middle(tail)
        if abs(early) > .5 and abs(late) > .5 and early * late > 0 and abs(early - late) <= .25:
            shift = early
            # Positive: the captions run late against the speech.
            findings.append({'rule': 'captions offset from the dialogue', 'offset_s': round(-shift, 3)})
    regions = []
    used = set()
    unmeasured = []
    for number, cue in enumerate(cues, 1):
        start, end = float(cue['start']) + shift, float(cue['end']) + shift
        wanted = dialogue_tokens(cue['text'])
        if not wanted:
            review.append({'cue': number, 'rule': 'not dialogue: check by listening', 'caption': cue['text']})
            regions.append(None)
            continue
        near = [(token, index) for index in around(start - reach, end + reach) if index not in used
                for token in dialogue_tokens(words[index]['text'])]
        matcher = difflib.SequenceMatcher(None, wanted, [token for token, _ in near], autojunk=False)
        hit = set()
        matched = []
        for block in matcher.get_matching_blocks():
            hit.update(range(block.a, block.a + block.size))
            matched.extend(near[block.b + k][1] for k in range(block.size))
        if not hit:
            spoken = [words[index]['text'] for index in around(start, end)]
            rule = 'caption does not match the dialogue' if spoken else 'caption over no matching speech'
            findings.append({'cue': number, 'rule': rule, 'caption': cue['text'],
                             **({'spoken': ' '.join(spoken)} if spoken else {})})
            regions.append(None)
            continue
        stale = [wanted[k] for k in range(len(wanted)) if k not in hit]
        if stale:
            findings.append({'cue': number, 'rule': 'caption words not in the dialogue', 'words': stale,
                             'caption': cue['text']})
        used.update(matched)
        first = min(matched, key=lambda index: words[index]['start'])
        last = max(matched, key=lambda index: words[index]['end'])
        region = (words[first]['start'], words[last]['end'])
        regions.append(region)
        measured = (not words[first].get('estimated'), not words[last].get('estimated'))
        if not all(measured):
            unmeasured.append(number)
        review.extend(entrance_and_exit(number, cue, region, margin, measured))
    for number, cue in enumerate(cues, 1):
        start, end = float(cue['start']) + shift, float(cue['end']) + shift
        missing = [words[index]['text'] for index in around(start, end) if index not in used
                   and words[index]['start'] >= start and words[index]['end'] <= end
                   and dialogue_tokens(words[index]['text'])]
        if missing:
            review.append({'cue': number, 'rule': 'spoken but not captioned', 'words': missing})
    if unmeasured:
        review.append({'rule': 'entrances or exits not measured: estimated word times', 'cues': unmeasured})
    return findings, review, regions


def probe_video(ffprobe, path):
    """Read output dimensions, duration and stream metadata."""
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('ffprobe failed: ' + result.stderr[-500:])
    info = json.loads(result.stdout)
    video = next((stream for stream in info['streams'] if stream.get('codec_type') == 'video'
                  and not stream.get('disposition', {}).get('attached_pic')), None)
    if not video:
        raise ValueError('no video stream')
    duration = float(info.get('format', {}).get('duration', 0))
    if duration <= 0:
        raise ValueError('video duration unavailable')
    return video, duration


def safe_rectangle(width, height, spec):
    """Calculate the caption-safe rectangle in output pixels."""
    default = '0.06,0.14,0.06,0.35' if height > width else '0.05,0.05,0.05,0.05'
    safe = [float(value) for value in (spec or default).split(',')]
    if (len(safe) != 4 or any(not math.isfinite(value) or value < 0 or value >= 1 for value in safe)
            or safe[0] + safe[2] >= 1 or safe[1] + safe[3] >= 1):
        raise ValueError('invalid safe area')
    return (math.ceil(width * safe[0]), math.ceil(height * safe[1]),
            math.floor(width * (1 - safe[2])), math.floor(height * (1 - safe[3])))


def caption_states(cues, highlight):
    """Expand a caption into timed states with an active word index."""
    states = []
    for cue in cues:
        start, end = float(cue['start']), float(cue['end'])
        if start < 0 or end <= start:
            raise ValueError('invalid caption timing')
        words = cue.get('words') or []
        if not highlight or not words:
            states.append((start, end, cue, None))
            continue
        expected = cue['text'].split()
        actual = [str(word.get('text', word.get('word', ''))).strip() for word in words]
        if expected != actual:
            raise ValueError('caption words do not match caption text for indexed highlighting')
        bounds = sorted({start, end} | {max(start, min(end, float(word[key])))
                                      for word in words for key in ('start', 'end')})
        for left, right in zip(bounds, bounds[1:]):
            if right <= left:
                continue
            midpoint = (left + right) / 2
            active = next((i for i, word in enumerate(words) if word['start'] <= midpoint < word['end']), None)
            states.append((left, right, cue, active))
    return states


def choose_font(path):
    """Choose an explicit or known system font."""
    if path:
        return path
    bundled = Path(__file__).resolve().parent.parent / 'assets' / 'kit' / 'fonts'
    candidates = [bundled / 'MonaSansVF.woff2', bundled / 'GeistMonoVF.woff2',
                  Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
                  Path('/System/Library/Fonts/Helvetica.ttc'),
                  Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
                  Path('/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'),
                  Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'arial.ttf']
    for item in candidates:
        if item.is_file():
            try:
                ImageFont.truetype(str(item), 24)
                return str(item)
            except OSError:
                continue
    raise ValueError('font not found or unsupported; pass --font')


def render_caption(width, height, safe, cue, active, font_path, requested_size, plate):
    """Render a full-frame alpha overlay with indexed word highlighting."""
    left, top, right, bottom = safe
    lines = cue['text'].split('\n')
    size = requested_size or max(12, round(height * .045))
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    while size >= 8:
        font = ImageFont.truetype(font_path, size)
        widths = [draw.textlength(line, font=font) for line in lines]
        bbox = font.getbbox('Ag')
        line_height = bbox[3] - bbox[1] + max(2, size // 4)
        if max(widths, default=0) + 16 <= right - left and line_height * len(lines) + 16 <= bottom - top:
            break
        size -= 1
    if size < 8:
        raise ValueError('caption cannot fit inside safe area')
    y = bottom - line_height * len(lines) - 8
    box = (left, y - 6, right - 1, bottom - 1)
    if plate:
        draw.rounded_rectangle(box, radius=4, fill=(0, 0, 0, 190))
    word_index = 0
    for line, line_width in zip(lines, widths):
        x = (left + right - line_width) / 2
        if active is None:
            draw.text((x, y), line, font=font, fill='white', stroke_width=1, stroke_fill='black')
        else:
            # Calculate each occurrence from its index and the advance of preceding text.
            prefix = ''
            for word in line.split():
                position = x + draw.textlength(prefix, font=font)
                colour = (255, 220, 64) if word_index == active else 'white'
                draw.text((position, y), word, font=font, fill=colour, stroke_width=1, stroke_fill='black')
                prefix += word + ' '
                word_index += 1
        y += line_height
    return canvas, list(box)



def avoid_boxes(specs, width, height):
    """Parse avoid rectangles in output pixels or fractions."""
    result = []
    for spec in specs:
        values = [float(value) for value in spec.split(',')]
        if len(values) != 4 or any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError('avoid boxes must be X,Y,W,H nonnegative numbers')
        if all(value <= 1 for value in values):
            values = [values[0] * width, values[1] * height, values[2] * width, values[3] * height]
        x, y, w, h = values
        if w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError('avoid box must fit the output frame')
        result.append((x, y, x + w, y + h))
    return result


def position_overlay(image, safe, boxes):
    """Move visible caption pixels to the nearest safe position outside avoid boxes."""
    bounds = image.getbbox()
    if bounds is None:
        raise ValueError('caption overlay is empty')
    left, top, right, bottom = bounds
    sl, st, sr, sb = safe
    xs = {left, sl, sr - (right - left)}
    ys = {top, st, sb - (bottom - top)}
    for x1, y1, x2, y2 in boxes:
        xs.update((math.floor(x1 - (right - left)), math.ceil(x2)))
        ys.update((math.floor(y1 - (bottom - top)), math.ceil(y2)))
    choices = []
    for x in xs:
        for y in ys:
            rect = (x, y, x + right - left, y + bottom - top)
            if rect[0] < sl or rect[1] < st or rect[2] > sr or rect[3] > sb:
                continue
            if any(rect[0] < box[2] and rect[2] > box[0] and rect[1] < box[3] and rect[3] > box[1]
                   for box in boxes):
                continue
            choices.append(((x - left) ** 2 + (y - top) ** 2, x, y, rect))
    if not choices:
        return image, list(bounds), True
    _, x, y, rect = min(choices)
    if (x, y) != (left, top):
        shifted = Image.new('RGBA', image.size, (0, 0, 0, 0))
        shifted.alpha_composite(image, (x - left, y - top))
        image = shifted
    return image, list(rect), False

def burn_video(args):
    """Overlay Pillow frames at input presentation timestamps and tag BT.709."""
    ffmpeg = find_tool('ffmpeg', args.ffmpeg)
    ffprobe = find_tool('ffprobe', args.ffprobe)
    if not ffmpeg or not ffprobe:
        raise ValueError('ffmpeg and ffprobe are required')
    video, duration = probe_video(ffprobe, args.video)
    if args.size:
        dimensions = args.size.lower().split('x')
        if len(dimensions) != 2:
            raise ValueError('--size must be WIDTHxHEIGHT')
        width, height = map(int, dimensions)
    else:
        width, height = int(video['width']), int(video['height'])
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError('output dimensions must be positive even numbers')
    safe = safe_rectangle(width, height, args.safe)
    cues = read_input(args.input)
    states = caption_states(cues, args.highlight)
    if not states:
        raise ValueError('no caption states')
    font = choose_font(args.font)
    avoids = avoid_boxes(args.avoid, width, height)
    findings = []
    boxes = []
    with tempfile.TemporaryDirectory(prefix='caption-burn-') as temp:
        rendered = []
        for index, (start, end, cue, active) in enumerate(states):
            image, box = render_caption(width, height, safe, cue, active, font, args.font_size, args.plate)
            image, box, conflict = position_overlay(image, safe, avoids)
            if conflict:
                findings.append({'rule': 'avoid conflict', 'start': start, 'end': end, 'chosen_box': box})
            state_path = os.path.join(temp, 'state%05d.png' % index)
            image.save(state_path)
            rendered.append((start, end, state_path))
            boxes.append({'start': start, 'end': end, 'box': box, 'active_word_index': active})
        boundaries = sorted({0.0, duration} | {max(0.0, min(duration, t))
                                               for start, end, _ in rendered for t in (start, end)})
        entries = []
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            if end <= start:
                continue
            image = Image.new('RGBA', (width, height))
            for left, right, state_path in rendered:
                if left <= start and right > start:
                    with Image.open(state_path) as overlay:
                        image.alpha_composite(overlay.convert('RGBA'))
            name = 'caption%05d.png' % index
            image.save(os.path.join(temp, name))
            entries.extend(["file '%s'" % name, 'option framerate 1000', 'duration %.9f' % (end - start)])
        entries.extend(["file '%s'" % name, 'option framerate 1000'])
        manifest = os.path.join(temp, 'captions.ffconcat')
        with open(manifest, 'w', encoding='utf-8') as file:
            file.write('ffconcat version 1.0\n' + '\n'.join(entries) + '\n')
        command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', os.path.abspath(args.video),
                   '-f', 'concat', '-safe', '0', '-i', manifest]
        graph = ('[0:v]scale=%d:%d:flags=lanczos[base];'
                 '[base][1:v]overlay=0:0:eof_action=repeat:shortest=0,'
                 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,'
                 'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[out]') % (width, height)
        command.extend(['-filter_complex', graph, '-map', '[out]', '-map', '0:a?',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-fps_mode', 'passthrough',
                        '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                        '-color_range', 'tv', '-c:a', 'aac', os.path.abspath(args.out)])
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise ValueError('ffmpeg burn failed: ' + result.stderr[-1000:])
    return {'findings': findings, 'safe_area_pixels': list(safe), 'avoid_boxes': avoids,
            'rendered_boxes': boxes, 'font': font,
            'timing': 'input presentation timestamps', 'note': 'Visual legibility requires human review.'}


def add_rules(parser):
    """Add the common caption reading constraints."""
    parser.add_argument('--cps', type=float, default=20)
    parser.add_argument('--line-length', type=int, default=42)
    parser.add_argument('--min-duration', type=float, default=.8)
    parser.add_argument('--max-duration', type=float, default=7)
    parser.add_argument('--gap', type=float, default=.04)
    parser.add_argument('--json', help='write the report here')


def argument_parser():
    """Define the build, check and assembler-compatible burn interfaces."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    build_parser = sub.add_parser('build', help='build matching sidecars')
    build_parser.add_argument('input')
    build_parser.add_argument('--out', required=True, help='output filename prefix')
    add_rules(build_parser)
    check_parser = sub.add_parser('check', help='check captions and optionally screen timing')
    check_parser.add_argument('input')
    check_parser.add_argument('--audio', help='audio for a speech-band envelope timing screen')
    check_parser.add_argument('--burned', help='compare caption edges and contrast in this video')
    check_parser.add_argument('--safe', help='caption region: left,top,right,bottom fractions')
    check_parser.add_argument('--ffprobe')
    check_parser.add_argument('--words', help='word-timed JSON, preferred over audio when both are supplied')
    check_parser.add_argument('--margin', type=float, default=.25, help='timing screen margin in seconds')
    check_parser.add_argument('--ffmpeg')
    add_rules(check_parser)
    burn = sub.add_parser('burn', help='burn captions using input presentation timestamps')
    burn.add_argument('video', help='input video')
    burn.add_argument('input', help='captions SRT, VTT or JSON')
    burn.add_argument('--out', required=True, help='output video')
    burn.add_argument('--size', help='output WIDTHxHEIGHT')
    burn.add_argument('--safe', help='left,top,right,bottom fractions; tall default 0.06,0.14,0.06,0.35')
    burn.add_argument('--avoid', action='append', default=[], help='avoid X,Y,W,H in pixels or fractions')
    burn.add_argument('--font')
    burn.add_argument('--font-size', type=int)
    burn.add_argument('--plate', action='store_true')
    burn.add_argument('--highlight', action='store_true', help='highlight current word by index when timings exist')
    burn.add_argument('--ffmpeg')
    burn.add_argument('--ffprobe')
    burn.add_argument('--json', help='write report here')
    return parser


def run_build(args):
    """Build three sidecars and report inferred line timings."""
    words, estimated = split_timed_lines(read_input(args.input), args.gap)
    if not words:
        raise ValueError('no timed words')
    try:
        cues = segment(words, args)
    except SegmentationError as error:
        return {'findings': [{'rule': error.rule, 'text': error.text}], 'cues': 0,
                'word_timings_estimated': estimated}
    findings, review = validate(cues, args)
    if not findings:
        write_sidecars(cues, args.out)
    return {'findings': findings, 'review': review, 'cues': len(cues), 'word_timings_estimated': estimated,
            'note': 'Estimated timings require review against speech.' if estimated else None}



def video_frames(ffmpeg, ffprobe, path, safe):
    """Decode a bounded caption region and its actual frame presentation times."""
    video, _ = probe_video(ffprobe, path)
    width, height = int(video['width']), int(video['height'])
    left, top, right, bottom = safe_rectangle(width, height, safe)
    # Even crop coordinates avoid chroma-subsampling rounding differences.
    left, top = left // 2 * 2, top // 2 * 2
    crop_width, crop_height = (right - left) // 2 * 2, (bottom - top) // 2 * 2
    out_width = min(320, crop_width)
    out_height = max(2, round(crop_height * out_width / crop_width))
    probe = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                            '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', path],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    if probe.returncode:
        raise ValueError('cannot probe frame presentation timestamps')
    times = [float(frame['best_effort_timestamp_time']) for frame in json.loads(probe.stdout)['frames']]
    vf = 'crop=%d:%d:%d:%d,scale=%d:%d' % (crop_width, crop_height, left, top, out_width, out_height)
    decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', path, '-map', '0:v:0', '-vf', vf,
                              '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                             capture_output=True)
    if decoded.returncode:
        raise ValueError('cannot decode burned video: ' + decoded.stderr.decode(errors='replace')[-400:])
    data = np.frombuffer(decoded.stdout, dtype=np.uint8)
    size = out_width * out_height * 3
    if len(data) != len(times) * size or not times:
        raise ValueError('decoded frames and presentation timestamps disagree')
    return data.reshape((-1, out_height, out_width, 3)), np.asarray(times), [left, top, right, bottom]


def linear_luminance(rgb):
    """Convert decoded RGB to WCAG relative luminance."""
    values = np.asarray(rgb, dtype=np.float64) / 255
    values = np.where(values <= .04045, values / 12.92, ((values + .055) / 1.055) ** 2.4)
    return values @ np.array([.2126, .7152, .0722])


def contrast_screen(frames, times, start, end, mask):
    """Estimate text-to-neighbour contrast at each frame using an edge-derived mask."""
    padded = np.pad(mask, 2)
    dilated = np.zeros_like(mask, dtype=bool)
    for dy in range(5):
        for dx in range(5):
            dilated |= padded[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    ring = dilated & ~mask
    if np.count_nonzero(mask) < 3 or np.count_nonzero(ring) < 3:
        return None
    worst = None
    for index in range(start, end):
        lum = linear_luminance(frames[index])
        foreground = float(np.median(lum[mask]))
        background = float(np.median(lum[ring]))
        ratio = (max(foreground, background) + .05) / (min(foreground, background) + .05)
        if worst is None or ratio < worst['ratio']:
            worst = {'ratio': round(ratio, 3), 'frame': index, 'time_s': float(times[index])}
    return worst


def check_burned(cues, args):
    """Screen caption transitions and contrast; motion can confound pixel differences."""
    ffmpeg = find_tool('ffmpeg', args.ffmpeg)
    ffprobe = find_tool('ffprobe', args.ffprobe)
    if not ffmpeg or not ffprobe:
        raise ValueError('ffmpeg and ffprobe are required for burned checks')
    frames, times, region = video_frames(ffmpeg, ffprobe, args.burned, args.safe)
    differences = np.max(np.abs(frames[1:].astype(np.int16) - frames[:-1].astype(np.int16)), axis=3) > 10
    counts = differences.sum(axis=(1, 2))
    results = []
    findings = []
    for number, cue in enumerate(cues, 1):
        expected_in = int(np.searchsorted(times, cue['start'], side='left'))
        expected_out = int(np.searchsorted(times, cue['end'], side='left'))
        middle = (float(cue['start']) + float(cue['end'])) / 2
        start_candidates = [i for i in range(1, len(times)) if abs(times[i] - cue['start']) <= .5
                            and times[i] < middle and counts[i - 1] >= 3]
        end_candidates = [i for i in range(1, len(times)) if abs(times[i] - cue['end']) <= .5
                          and times[i] > middle and counts[i - 1] >= 3]
        start_candidates = sorted(start_candidates, key=lambda i: counts[i - 1], reverse=True)[:6]
        end_candidates = sorted(end_candidates, key=lambda i: counts[i - 1], reverse=True)[:6]
        pairs = [(int(np.count_nonzero(differences[a - 1] & differences[b - 1])), a, b)
                 for a in start_candidates for b in end_candidates if b > a]
        overlap, onset, offset = max(pairs, default=(0, 0, 0))
        if overlap < 3:
            findings.append({'cue': number, 'rule': 'caption missing or visually inconclusive'})
            results.append({'cue': number, 'status': 'missing or inconclusive'})
            continue
        mask = differences[onset - 1] & differences[offset - 1]
        if np.count_nonzero(mask) > mask.size * .25:
            findings.append({'cue': number, 'rule': 'visual timing inconclusive: substantial picture change'})
        entry = {'cue': number, 'status': 'detected', 'appearance_frame': onset,
                 'disappearance_frame': offset, 'appearance_offset_frames': onset - expected_in,
                 'disappearance_offset_frames': offset - expected_out,
                 'appearance_time_s': float(times[onset]), 'disappearance_time_s': float(times[offset])}
        for edge in ('appearance', 'disappearance'):
            if abs(entry[edge + '_offset_frames']) > 1:
                findings.append({'cue': number, 'rule': edge + ' offset over one frame',
                                 'offset_frames': entry[edge + '_offset_frames']})
        contrast = contrast_screen(frames, times, onset, offset, mask)
        entry['worst_contrast'] = contrast
        if contrast is None:
            findings.append({'cue': number, 'rule': 'contrast inconclusive'})
        elif contrast['ratio'] < 4.5:
            findings.append({'cue': number, 'rule': 'contrast below 4.5', **contrast})
        results.append(entry)
    return {'findings': findings, 'region_pixels': region, 'cues': results,
            'method': 'presentation-timed edge changes and local RGB luminance estimates',
            'note': 'Motion and changing backgrounds can confound text isolation; inspect these estimates.'}

def run_check(args):
    """Check rule breaks and a selected timing-screen basis."""
    cues = read_input(args.input)
    findings, review = validate(cues, args)
    report = {'findings': findings, 'review': review, 'cues': len(cues), 'timing_screen': {'basis': 'not requested'}}
    if args.words:
        rows = read_input(args.words)
        words, estimated = split_timed_lines(rows, overlap=True)
        timing_findings, timing_review, regions = check_word_timing(cues, words, args.margin)
        report['timing_screen'] = {'basis': 'word timings', 'margin_s': args.margin, 'regions': regions,
                                   'estimated_word_times': estimated or any(w.get('estimated') for w in words),
                                   'empty_rows_ignored': sum(1 for row in rows if not row['text'])}
        findings.extend(timing_findings)
        review.extend(timing_review)
    elif args.audio:
        ffmpeg = find_tool('ffmpeg', args.ffmpeg)
        if not ffmpeg:
            raise ValueError('ffmpeg not found')
        regions, measurement = audio_regions(ffmpeg, args.audio)
        timing_findings, timing_review, matched = timing_screen(cues, regions, args.margin)
        findings.extend(timing_findings)
        review.extend(timing_review)
        report['timing_screen'] = {'basis': 'speech-band envelope', 'margin_s': args.margin,
                                   'matched_regions': matched, 'measurement': measurement,
                                   'note': 'Activity is not recognised speech; inspect findings and audio.'}
    if args.burned:
        visual = check_burned(cues, args)
        findings.extend(visual.pop('findings'))
        report['burned_screen'] = visual
    # One line per rule, so a pattern across a whole file (captions placed back to back) reads as one thing.
    report['summary'] = {'findings': dict(collections.Counter(item['rule'] for item in findings)),
                         'review': dict(collections.Counter(item['rule'] for item in review))}
    return report


def main():
    """Run the selected command and return the shared script exit codes."""
    parser = argument_parser()
    args = parser.parse_args()
    try:
        if args.command in ('build', 'check'):
            values = (args.cps, args.min_duration, args.max_duration, args.gap)
            if (not all(math.isfinite(value) for value in values) or args.cps <= 0 or args.line_length <= 0
                    or args.min_duration <= 0 or args.max_duration < args.min_duration or args.gap < 0):
                raise ValueError('invalid rule limits')
        if args.command == 'check' and (not math.isfinite(args.margin) or args.margin < 0):
            raise ValueError('margin must be finite and nonnegative')
        if args.command == 'build':
            report = run_build(args)
        elif args.command == 'check':
            report = run_check(args)
        else:
            report = burn_video(args)
        if args.json:
            Path(args.json).write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report, indent=2))
        return 1 if report['findings'] else 0
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
