#!/usr/bin/env python3
"""Build, check or burn captions from a common timed source.

  captions.py build words.json --out captions [--profile house.json]
  captions.py check captions.srt [--words words.json] [--profile house.json] [--strict]
  captions.py burn picture.mp4 captions.json --out captioned.mp4 [--size 360x640] [--safe L,T,R,B] [--avoid X,Y,W,H]

Build writes SRT, WebVTT and word-timed JSON. Input JSON is a WhisperX-style
segments object, a list of timed words, or timed lines with start, end and text.
Timed-line word times are estimates, apportioned by character count, and must be
reviewed against speech. Build preserves long-pause boundaries and reports any soft rule it relaxes; it never
returns an empty successful build for timed words. Burn defaults to a translucent plate, reports
cue sizes and sampled decoded contrast, and preserves the decoded input frame count. It converts HDR to BT.709 SDR,
normalizes display geometry and uses libass or Pillow Raqm for complex shaping. Check the language with a fluent
reader. The burned screen estimates
text edges and contrast from frame changes; motion
can confound it and results need inspection. The timing screen uses word timings
when supplied or a
band-limited audio envelope otherwise. Neither identifies speech or proves alignment.

Check sorts what it finds into two lists. Findings are errors: invalid or overlapping
times, too many or too long lines, and, given --words, caption words not among the words
under the caption (cut from the dialogue but left on screen), a caption over no matching
speech, a measured whole-file offset, and no caption events over dialogue. Three matched captions with measured
first and last word edges are needed for an offset finding. An apparent offset supported only by estimated edges
is a listening prompt; either kind can be allowed for in matching and its basis is reported. What --words compares
against is what the words file holds, and the report says which (timing_screen.words_from): a transcript
of the delivered audio (transcribe.py) compares captions against that transcript, which can mishear; edit-time words
(a version's lines.json, or exchange.py words in the shared
{"version": 1, "words": [...]} schema) show the captions follow the edit. Words written
differently but said the same match: numbers in digits or words (2 / two, 25 / twenty five,
$1,200 / twelve hundred dollars), contractions and their expansions, case, punctuation and
hyphenation. Review prompts are measurements for a person to judge, never reasons to merge
or retime automatically: reading speed, duration, single-word lines, gaps under the
limit, words spoken but not captioned, a word spelled differently from the words (Jon /
John), and when a caption enters and leaves against the speech, in seconds. Short captions
are often intentional.

The default limits are 20 characters/s, 42 characters/line, two lines, 0.8-7 s, 0.04 s between events and a
0.25 s timing margin. A --profile JSON file may contain a limits object with cps, line_length, lines, min_duration,
max_duration, gap and margin, and an exceptions list. Each exception names a rule, the reviewed caption's start and
end in seconds and its text, a note and the reviewer. It applies only while that caption is unchanged and identifies
exactly one cue; an edited caption, an ambiguous entry or one without text and end stays open for review. Every
result in the report carries a fingerprint of the caption and the result's measurements; an exception that copies it
also reopens when the result changes, as a timing result does when the word basis changes. For example:
  {"limits": {"gap": 0}, "exceptions": [{"rule": "minimum duration", "start": 1.2, "end": 1.5,
    "text": "Go", "fingerprint": "3f9a...", "note": "intentional fragment", "reviewer": "Editor"}]}
Flags override profile limits. Accepted exceptions retain the original finding or prompt and reviewer note; unused
exceptions prompt review. The report records the profile path and SHA-256 and effective limits. Output paths cannot
name inputs, including through links.

Check reports complete only when no finding or unresolved prompt remains, a word basis was supplied, and every
dialogue word in that basis, including fillers, was matched. Complete does not prove that the basis heard all speech
or that a person reviewed the captions. Exit 0 when there are no findings (review prompts may be listed), 1 for
findings; with --strict, check exits 1 whenever incomplete. Exit 2 when unable to run or an output would replace
an input.
"""
import argparse
import base64
import bisect
import collections
import difflib
import fractions
import functools
import hashlib
import html
import importlib.util
import io
import itertools
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
from types import SimpleNamespace
from pathlib import Path

spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
except ImportError as error:
    name = 'PIL' if error.name and (error.name == 'PIL' or error.name.startswith('PIL.')) else 'numpy'
    print(project.dependency_message(name), file=sys.stderr)
    sys.exit(2)


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
    if not content.strip():
        return []
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
    if not cues and not content.strip().startswith('WEBVTT'):
        raise ValueError('no caption events')
    return cues


def word_items(data):
    """The timed words in any word file this skill reads, and what they were timed against: the shared edit-time
    word schema ({"version": 1, "words": [...]}, exchange.py words), a version's lines.json (each spoken line's kept
    words; picture lines and cut words carry no speech), a transcript (words.json), exchange.py's earlier
    {"occurrences": [...]}, cues with word timings, WhisperX segments or a plain list."""
    if isinstance(data, dict) and isinstance(data.get('lines'), list) and (
            'film_version' in data or any(isinstance(line, dict) and 'kind' in line for line in data['lines'])):
        return [word for line in data['lines'] if isinstance(line, dict) for word in line.get('words') or []], \
            'edit-time words: the paper edit\'s kept words (lines.json)'
    if isinstance(data, dict) and 'occurrences' in data and 'words' not in data:
        return data['occurrences'], 'edit-time words placed through a timeline (exchange.py)'
    if isinstance(data, dict) and 'timeline' in data and 'words' in data:
        return data['words'], 'edit-time words placed through a timeline (exchange.py)'
    if isinstance(data, dict) and data.get('engine') and 'words' in data:
        return data['words'], f"a transcript ({data['engine']})"
    return read_json_items(data), 'word timings'


def read_words(path):
    """Timed words for check --words as rows with start, end and text (empty rows kept, to be counted), and a phrase
    saying what they were timed against. SRT and WebVTT files are read as timed lines."""
    if not str(path).lower().endswith('.json'):
        return read_input(path), 'timed lines (' + Path(path).suffix.lstrip('.').upper() + ')'
    content = Path(path).read_text(encoding='utf-8-sig')
    items, basis = word_items(json.loads(content))
    rows = []
    for item in items:
        row = dict(item)
        row['start'] = float(item['start'])
        row['end'] = float(item['end'])
        # The words' text: exchange.py's earlier rows used `word` for the transcript word's ID, so text comes first.
        row['text'] = plain_text(str(item.get('text', item.get('word', ''))))
        rows.append(row)
    return rows, basis


def split_timed_lines(items, gap=0, overlap=False, _nested=False):
    """Estimate word boundaries within timed lines and preserve actual word timings. With `overlap`, words of
    different speakers may overlap in time; they are returned in time order."""
    result = []
    estimated = False
    for item in items:
        if item.get('words'):
            nested, was_estimated = split_timed_lines(item['words'], gap, overlap, _nested=True)
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
        # Every other field of a word (its transcript ID, speaker, confidence, an estimated mark) travels with it.
        fields = {key: value for key, value in item.items() if key not in ('word', 'words', 'text', 'start', 'end')}
        if math.isfinite(start) and start >= 0 and end == start:
            end = start + .02
            fields['estimated'] = True
            fields['_zero_repaired'] = True
            estimated = True
        if len(parts) == 1:
            result.append(dict(fields, text=parts[0], start=start, end=end))
            estimated = estimated or bool(fields.get('estimated'))
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
            # Pieces of one timed line share its fields; with an ID, `part` numbers them from 1.
            piece = dict(fields, text=part, start=left, end=right, estimated=True)
            if 'id' in fields:
                piece['part'] = part_index + 1
            result.append(piece)
    if overlap:
        result.sort(key=lambda word: (word['start'], word['end']))
    else:
        for index, word in enumerate(result):
            if not word.get('_zero_repaired'):
                continue
            lower = result[index - 1]['end'] if index else 0.0
            upper = result[index + 1]['start'] if index + 1 < len(result) else math.inf
            if word['end'] > upper and upper - lower >= .02:
                word['start'] = max(lower, min(word['start'], upper - .02))
                word['end'] = word['start'] + .02
    for index, word in enumerate(result):
        start, end = word['start'], word['end']
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f'invalid word timing for {word["text"]!r}: {start:g} to {end:g}')
        if index and not overlap and start < result[index - 1]['end'] - 1e-8:
            previous = result[index - 1]
            repaired = word.get('_zero_repaired') or previous.get('_zero_repaired')
            if not repaired or start < previous['start'] - 1e-8:
                raise ValueError(f'word timings overlap or are unordered at {word["text"]!r}')
    if not _nested:
        for word in result:
            word.pop('_zero_repaired', None)
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


def line_layout(words, limit, max_lines=2):
    """Choose a legal one- or two-line layout, favouring phrase breaks."""
    texts = [word['text'] for word in words]
    text = ' '.join(texts)
    if len(text) <= limit:
        return text
    if max_lines == 1:
        return None
    candidates = []
    for index in range(2, len(words) - 1):
        if protected_break(words, index):
            continue
        left = ' '.join(texts[:index])
        right = ' '.join(texts[index:])
        if len(left) <= limit and len(right) <= limit:
            candidates.append((break_score(words, index), -abs(len(left) - len(right)), left + '\n' + right))
    if candidates or max_lines == 2:
        return max(candidates)[2] if candidates else None
    # For larger house limits, keep the same phrase-break scoring while considering additional lines.
    @functools.lru_cache(maxsize=None)
    def layout(start, remaining):
        tail = ' '.join(texts[start:])
        if len(tail) <= limit:
            return 0, [tail]
        if remaining <= 1:
            return None
        choices = []
        for end in range(start + 2, len(words) - 1):
            line = ' '.join(texts[start:end])
            if len(line) > limit:
                break
            if protected_break(words, end):
                continue
            following = layout(end, remaining - 1)
            if following:
                choices.append((break_score(words, end) + following[0], [line] + following[1]))
        return max(choices, key=lambda choice: choice[0]) if choices else None

    found = layout(0, max_lines)
    return '\n'.join(found[1]) if found else None


def required_caption_break(words, index, pause_gap):
    """Keep a long pause or a known source/speaker change between caption cues."""
    if index <= 0 or index >= len(words):
        return True
    left, right = words[index - 1], words[index]
    if right['start'] - left['end'] >= pause_gap:
        return True
    for field in ('source', 'speaker'):
        if left.get(field) is not None and right.get(field) is not None and left[field] != right[field]:
            return True
    return False


def segment(words, args, diagnose=True):
    """Find the highest-scoring feasible layout using a Pareto frontier of end times."""
    count = len(words)
    frontiers = [[] for _ in range(count + 1)]
    frontiers[0] = [(0.0, 0, None)]
    blockers = set()
    pause_gap = getattr(args, 'pause_gap', .6)
    for start_index in range(count):
        for prior_end, score, previous in frontiers[start_index]:
            for end_index in range(start_index + 1, count + 1):
                if end_index > start_index + 1 and required_caption_break(words, end_index - 1, pause_gap):
                    break
                group = words[start_index:end_index]
                max_lines = getattr(args, 'lines', 2)
                text = line_layout(group, args.line_length, max_lines)
                if not text:
                    blockers.add('line length or line-count limit')
                    if sum(len(word['text']) for word in group) + len(group) - 1 > max_lines * (args.line_length + 1):
                        break
                    continue
                isolated = (required_caption_break(words, start_index, pause_gap)
                            and required_caption_break(words, end_index, pause_gap))
                if len(group) == 1 and count > 1 and not isolated and not getattr(args, 'allow_orphans', False):
                    blockers.add('orphan word')
                    continue
                if (not getattr(args, 'allow_protected', False) and end_index < count
                        and not required_caption_break(words, end_index, pause_gap)
                        and protected_break(words, end_index)):
                    blockers.add('protected name, number or noun phrase')
                    continue
                gap = args.gap if previous else 0
                earliest = math.ceil((prior_end + gap) * 1000 - 1e-8) / 1000
                first_speech = group[0]['start']
                if start_index:
                    pause_before = first_speech - words[start_index - 1]['end']
                    if pause_before >= pause_gap:
                        earliest = max(earliest, math.ceil((first_speech - min(.2, pause_before / 3)) * 1000) / 1000)
                # SRT and VTT use milliseconds; permit at most one millisecond of quantisation at a word edge.
                if earliest > first_speech + .001 + 1e-9:
                    blockers.add('minimum gap')
                    continue
                needed = max(args.min_duration, len(text.replace('\n', ' ')) / args.cps)
                end = math.ceil(max(group[-1]['end'], earliest + needed) * 1000 - 1e-8) / 1000
                if end_index < count:
                    pause_after = words[end_index]['start'] - group[-1]['end']
                    if pause_after >= pause_gap and end > group[-1]['end'] + min(.2, pause_after / 3) + 1e-9:
                        blockers.add('caption extends into a long pause')
                        continue
                # The latest start with this earliest feasible end avoids needless anticipation.
                start = math.floor(min(first_speech, end - needed) * 1000 + 1e-8) / 1000
                if start < earliest - 1e-9:
                    if earliest - start <= .001 + 1e-9:
                        start = earliest
                    else:
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
                           ('characters per line or line-count limit', 'line_length', 1000000),
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
        errors = [('lines', len(lines) > getattr(args, 'lines', 2)),
                  ('line length', any(len(line) > args.line_length for line in lines))]
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


def write_text_lf(path, text):
    """Write UTF-8 text with LF line endings on every platform (Path.write_text would write CRLF on Windows)."""
    with open(path, 'w', encoding='utf-8', newline='\n') as file:
        file.write(text)


def write_sidecars(cues, prefix):
    """Write matching millisecond SRT and WebVTT plus word timings, with LF line endings."""
    for extension in ('srt', 'vtt'):
        lines = ['WEBVTT\n'] if extension == 'vtt' else []
        for index, cue in enumerate(cues, 1):
            timing = timestamp(cue['start'], extension == 'vtt')
            timing += ' --> ' + timestamp(cue['end'], extension == 'vtt')
            lines.extend([str(index), timing, cue['text'], ''])
        write_text_lf(prefix + '.' + extension, '\n'.join(lines) + '\n')
    write_text_lf(prefix + '.json', json.dumps({'cues': cues}, indent=2))


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


# Equivalent ways of writing the same speech, so a caption is never reported as unspoken for writing "2" where the
# transcript says "two", or "can't" where it says "cannot"; and only those: a sign, a decimal point, a separator, an
# accent or a contraction that may change the meaning is kept, as a finding or a review prompt.
APOSTROPHES = str.maketrans({'\u2019': "'", '\u2018': "'", '\u02bc': "'", '\u2032': "'"})
SPOKEN_TOKEN = re.compile(
    r"(?:(?<![^\s(\[{\"'])([-\u2212]))?([$\xa3\u20ac])?"
    r"(?:(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?|(?<![\w.])(\.\d+))(%|(?:st|nd|rd|th)(?![^\W_]))?"
    r"|(?<=\d)([-\u2013\u2014/:])(?=[$\xa3\u20ac]?\d)"
    r"|[^\W\d_]+(?:['-][^\W\d_]+)*")
SEPARATORS = {'-': '-', '\u2013': '-', '\u2014': '-', '/': '/', ':': ':'}
CURRENCY = {'$': 'dollars', '\xa3': 'pounds', '\u20ac': 'euros'}
SMALL_NUMBERS = {name: value for value, name in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen '
    'eighteen nineteen'.split())}
TENS_NUMBERS = {name: 10 * value for value, name in enumerate(
    'twenty thirty forty fifty sixty seventy eighty ninety'.split(), 2)}
SCALE_NUMBERS = {'thousand': 10 ** 3, 'million': 10 ** 6, 'billion': 10 ** 9, 'trillion': 10 ** 12}
ODD_ORDINALS = {'first': 'one', 'second': 'two', 'third': 'three', 'fifth': 'five', 'eighth': 'eight',
                'ninth': 'nine', 'twelfth': 'twelve'}
WHOLE_CONTRACTIONS = {"can't": ('can', 'not'), 'cannot': ('can', 'not'), "won't": ('will', 'not'),
                      "shan't": ('shall', 'not'), 'gonna': ('going', 'to'), 'wanna': ('want', 'to'),
                      'gotta': ('got', 'to'), 'kinda': ('kind', 'of'), 'sorta': ('sort', 'of'), 'ok': ('okay',)}
CONTRACTION_ENDINGS = {"'m": 'am', "'re": 'are', "'ve": 'have', "'ll": 'will', "'d": "'d", "'s": "'s"}
# What "'s" and "'d" can stand for: the usual readings match; a reading that changes the tense or the meaning of the
# sentence ("we'd" for "we did") is a review prompt.
CERTAIN_ENDINGS = {"'s": ('is', 'has', 'us'), "'d": ('would', 'had')}
UNCERTAIN_ENDINGS = {"'s": ('does',), "'d": ('did',)}
SEPARATOR_WORDS = {'-': ('to',)}
FILLERS = {'um', 'uh', 'uhm', 'erm', 'er', 'hmm', 'mm', 'mhm'}
BRITISH_ENDINGS = (('isation', 'ization'), ('ise', 'ize'), ('ising', 'izing'), ('ised', 'ized'), ('yse', 'yze'),
                   ('our', 'or'), ('ours', 'ors'), ('tre', 'ter'), ('tres', 'ters'), ('ogue', 'og'), ('ence', 'ense'),
                   ('lled', 'led'), ('lling', 'ling'))
SPELLING_PAIRS = {('grey', 'gray'), ('aluminium', 'aluminum'), ('programme', 'program'), ('cheque', 'check'),
                  ('tyre', 'tire'), ('kerb', 'curb'), ('plough', 'plow'), ('doughnut', 'donut')}


def fold(text):
    """Case and compatibility forms folded and apostrophe shapes made one, accents kept (they are compared apart)."""
    return unicodedata.normalize('NFKC', text.casefold().translate(APOSTROPHES))


def plain_letters(text):
    """Text with its accents removed, for matching (an accent difference is reported separately)."""
    return ''.join(char for char in unicodedata.normalize('NFKD', text) if not unicodedata.combining(char))


def expand_contraction(token):
    """A word with its contraction expanded where the expansion is certain ("can't" -> can not, "we'll" -> we will);
    "'s" and "'d" stay as they are, since they stand for more than one word."""
    if token in WHOLE_CONTRACTIONS:
        return list(WHOLE_CONTRACTIONS[token])
    if token.endswith("n't") and len(token) > 3:
        return [token[:-3], 'not']
    if "'" in token:
        base, tail = token.rsplit("'", 1)
        if "'" + tail in CONTRACTION_ENDINGS and base:
            return [base.replace("'", ''), CONTRACTION_ENDINGS["'" + tail]]
        return [token.replace("'", '')]
    return [token]


def number_text(digits, decimals):
    """A written number as one canonical string: thousands separators and trailing decimal zeros removed; a decimal
    point is kept (.5 is 0.5, never 5)."""
    whole = str(int((digits or '0').replace(',', '')))
    fraction = (decimals or '').rstrip('0').rstrip('.')
    return whole + fraction


def unit(text, owner, raw, kind='word', marked=None, currency=None):
    """One comparable unit: its text for matching, its text with accents (`marked`), the owners (word indexes or
    the caption) and raw tokens it came from, and its kind (word, number or separator)."""
    return {'unit': text, 'marked': text if marked is None else marked, 'owners': [owner], 'raws': [raw],
            'kind': kind, 'currency': currency}


def number_units(match, owner, raw):
    """The units of a written number: a sign as 'minus', the number (ordinal, decimal or whole), then 'percent'."""
    units = [unit('minus', owner, raw)] if match.group(1) else []
    suffix = match.group(6) or ''
    if match.group(5):
        number = number_text('0', match.group(5))
    else:
        number = number_text(match.group(3), match.group(4))
        if suffix in ('st', 'nd', 'rd', 'th') and not match.group(4):
            number += 'th'
    units.append(unit(number, owner, raw, 'number', currency=match.group(2)))
    if suffix == '%':
        units.append(unit('percent', owner, raw))
    return units


def piece_units(text, owner, counter):
    """The comparable units of one piece of dialogue, before number words are joined. Each raw token is (sequence
    number, text); the parts of one hyphenated word share it."""
    units = []
    spoken = SPEAKER_LABEL.sub(' ', NON_DIALOGUE.sub(' ', text))
    for match in SPOKEN_TOKEN.finditer(fold(spoken)):
        raw = (next(counter), match.group(0))
        if match.group(3) or match.group(5):
            units.extend(number_units(match, owner, raw))
        elif match.group(7):
            units.append(unit(SEPARATORS[match.group(7)], owner, raw, 'separator'))
        else:
            for part in match.group(0).split('-'):
                for word in expand_contraction(part):
                    if word:
                        units.append(unit(plain_letters(word), owner, raw, marked=word))
    return units


def cardinal(word):
    """The cardinal number word an ordinal is written from (fourth -> four, twentieth -> twenty), else None."""
    if word in ODD_ORDINALS:
        return ODD_ORDINALS[word]
    if word.endswith('ieth') and word[:-4] + 'y' in TENS_NUMBERS:
        return word[:-4] + 'y'
    if word.endswith('th') and (word[:-2] in SMALL_NUMBERS or word[:-2] in SCALE_NUMBERS or word[:-2] == 'hundred'):
        return word[:-2]
    return None


def plain_number(word):
    """A written number unit (12, 4.5) as a Fraction, else None."""
    if re.fullmatch(r'\d+(?:\.\d+)?', word):
        return fractions.Fraction(word)
    return None


def spoken_decimals(units, index):
    """The digits spoken after 'point' at units[index] ('point five' -> '5'), and the index after them."""
    digits = ''
    if index + 1 < len(units) and units[index] == 'point' and SMALL_NUMBERS.get(units[index + 1], 10) < 10:
        index += 1
        while index < len(units) and SMALL_NUMBERS.get(units[index], 10) < 10:
            digits += str(SMALL_NUMBERS[units[index]])
            index += 1
    return digits, index


def read_number(units, start):
    """The number spelled in words from units[start] ('twenty five' -> '25', 'twenty first' -> '21th', 'a hundred',
    'four point five', 'point five'): (canonical unit, end index), or None when no number starts there."""
    total, group, last, index, end, ordinal = 0, 0, None, start, start, False
    while index < len(units) and not ordinal:
        word = units[index]
        name = cardinal(word) or word
        following = units[index + 1] if index + 1 < len(units) else ''
        following = cardinal(following) or following
        small = SMALL_NUMBERS.get(name)
        if small is not None and (last in (None, 'hundred', 'scale', 'and') or (last == 'tens' and 0 < small < 10)):
            group += small
            last = 'small' if small < 10 else 'teen'
        elif name in TENS_NUMBERS and last in (None, 'hundred', 'scale', 'and'):
            group += TENS_NUMBERS[name]
            last = 'tens'
        elif name == 'hundred' and last in ('small', 'teen', 'a', 'digit') and group < 100:
            group = (group or 1) * 100
            last = 'hundred'
        elif name in SCALE_NUMBERS and last in ('small', 'teen', 'tens', 'hundred', 'a', 'digit'):
            total += (group or 1) * SCALE_NUMBERS[name]
            group = 0
            last = 'scale'
        elif word == 'and' and last in ('hundred', 'scale') and (following in SMALL_NUMBERS
                                                                  or following in TENS_NUMBERS):
            last = 'and'
            index += 1
            continue
        elif index == start and word == 'a' and (following == 'hundred' or following in SCALE_NUMBERS):
            last = 'a'
            index += 1
            continue
        elif index == start and plain_number(word) is not None and (following == 'hundred'
                                                                     or following in SCALE_NUMBERS):
            group = plain_number(word)
            last = 'digit'
        else:
            break
        ordinal = name != word
        index += 1
        end = index
    if end == start:
        digits, after = spoken_decimals(units, start)
        return (number_text('0', '.' + digits), after) if digits else None
    value = fractions.Fraction(total) + fractions.Fraction(group)
    if ordinal:
        return f'{int(value)}th', end
    if value.denominator != 1:
        return format(float(value), 'g'), end
    digits, end = spoken_decimals(units, end)
    return number_text(str(value.numerator), '.' + digits if digits else ''), end


def merged(entries, text, kind):
    """One unit standing for several (a number spelled in words): owners and raw tokens combined, in order."""
    owners, raws = [], []
    for entry in entries:
        owners.extend(owner for owner in entry['owners'] if owner not in owners)
        raws.extend(entry['raws'])
    return {'unit': text, 'marked': text, 'owners': owners, 'raws': raws, 'kind': kind, 'currency': None}


def units_of(pieces):
    """Comparable spoken units from (text, owner) pieces, in order: sound descriptions, music symbols and speaker
    labels removed; case and punctuation folded (accents kept apart); hyphenated words split; certain contractions
    expanded; numbers written in words, across pieces, turned to digits; a sign kept as 'minus' ('negative' before a
    number too). Each unit is a dict: unit, marked, owners, raws, kind."""
    counter = itertools.count()
    stream = [entry for text, owner in pieces for entry in piece_units(text, owner, counter)]
    words = [entry['unit'] if entry['kind'] != 'separator' else '' for entry in stream]
    result = []
    index = 0
    while index < len(stream):
        found = read_number(words, index) if stream[index]['kind'] == 'word' or (
            stream[index]['kind'] == 'number' and index + 1 < len(words)) else None
        if found:
            entries, end = stream[index:found[1]], found[1]
            result.append(merged(entries, found[0], 'number'))
            currency = next((entry['currency'] for entry in entries if entry['currency']), None)
        else:
            entries, end = stream[index:index + 1], index + 1
            result.append(dict(stream[index]))
            currency = stream[index]['currency']
        if currency:
            result.append(merged(entries, CURRENCY[currency], 'word'))
        index = end
    for position, entry in enumerate(result[:-1]):
        if entry['unit'] == 'negative' and result[position + 1]['kind'] == 'number':
            entry['unit'] = entry['marked'] = 'minus'
    return result


def skeleton(word):
    """A word's consonants as they sound: first letter kept, later vowels and h, w, y dropped, doubles collapsed,
    and c, ph, ck, q, z written as they are said."""
    word = re.sub(r'c(?=[eiy])', 's', word.replace('ph', 'f').replace('ck', 'k').replace('q', 'k'))
    word = word.replace('c', 'k').replace('z', 's')
    kept = word[:1] + re.sub(r'[aeiouyhw]', '', word[1:])
    return re.sub(r'(.)\1+', r'\1', kept)


def american(word):
    """A British spelling written the American way (colour -> color, theatre -> theater), for comparison only."""
    for british, us in BRITISH_ENDINGS:
        if word.endswith(british) and len(word) > len(british) + 2:
            return word[:-len(british)] + us
    return word.replace('ae', 'e').replace('oe', 'e') if len(word) > 5 else word


def spelled_alike(first, second):
    """Whether two words differ only in spelling (Jon / John, colour / color, Mohammed / Muhammad): the same
    sounding consonants and either the same vowels, a British and American pair, or a long word with a small edit.
    Short words with a different vowel (cats / cuts) are different words."""
    if first == second or not first.isalpha() or not second.isalpha() or max(len(first), len(second)) < 4:
        return False
    if (first, second) in SPELLING_PAIRS or (second, first) in SPELLING_PAIRS or american(first) == american(second):
        return True
    if skeleton(first) != skeleton(second):
        return False
    vowels = (re.sub(r'[^aeiou]', '', first[1:]), re.sub(r'[^aeiou]', '', second[1:]))
    if vowels[0] == vowels[1]:
        return True
    return min(len(first), len(second)) >= 7 and difflib.SequenceMatcher(None, first, second).ratio() >= 0.7


def pair_kind(caption, spoken):
    """How two units relate: 'same', 'contraction' (an ending whose reading changes the meaning) or None."""
    a, b = caption['unit'], spoken['unit']
    if a == b:
        return 'same'
    for one, other in ((a, b), (b, a)):
        if other in CERTAIN_ENDINGS.get(one, ()) or other in SEPARATOR_WORDS.get(one, ()):
            return 'same'
        if other in UNCERTAIN_ENDINGS.get(one, ()):
            return 'contraction'
    return None


def one_word(entries):
    """Whether units all come from one written word (one hyphenated word, or one number)."""
    return len({raw[0] for entry in entries for raw in entry['raws']}) == 1


def joined_kind(caption, spoken):
    """Runs that spell the same letters or digits when joined: 'same' for a hyphenated word written whole (e-mail /
    email) or a year in pairs (1984 / nineteen eighty four), 'spelling' for words joined or split without a hyphen or
    with an apostrophe dropped (every day / everyday, its / it's), None when they differ. Separators stay in the join,
    so 1-2 never joins to 12."""
    text = [''.join(entry['unit'] for entry in run) for run in (caption, spoken)]
    longer = caption if len(caption) > len(spoken) else spoken
    if text[0] == text[1]:
        if all(entry['kind'] == 'number' for entry in caption + spoken):
            return 'same' if all(re.fullmatch(r'\d\d', entry['unit']) for entry in longer) else None
        if all(entry['kind'] == 'word' for entry in caption + spoken):
            return 'same' if one_word(longer) else 'spelling'
        return None
    if text[0].replace("'", '') == text[1].replace("'", '') and all(entry['kind'] == 'word' for entry in caption
                                                                     + spoken):
        return 'spelling'
    return None


def same_words(caption, spoken):
    """How two runs of units relate: 'same' (the same words written differently), 'contraction' (an ending whose
    reading changes the meaning), 'spelling' (a difference only in spelling, joining or accents), or None."""
    if len(caption) == len(spoken):
        kinds = [pair_kind(a, b) for a, b in zip(caption, spoken)]
        if None not in kinds:
            return 'contraction' if 'contraction' in kinds else 'same'
    joined = joined_kind(caption, spoken)
    if joined:
        return joined
    if len(caption) == 1 and len(spoken) == 1 and spelled_alike(caption[0]['unit'], spoken[0]['unit']):
        return 'spelling'
    return None


def align_replaced(caption, spoken, span=4):
    """Caption units against the spoken units an exact match left unpaired, in order: (caption start, caption end,
    spoken start, spoken end, kind) for each run that says the same words, differs only in spelling, or uses a
    contraction that may change the meaning."""
    pairs = []
    position, cursor = 0, 0
    while position < len(caption):
        best = None
        for length in range(1, min(span, len(caption) - position) + 1):
            for start in range(cursor, len(spoken)):
                for size in range(1, min(span, len(spoken) - start) + 1):
                    kind = same_words(caption[position:position + length], spoken[start:start + size])
                    rank = (kind != 'same', start, -length)
                    if kind and (best is None or rank < best[0]):
                        best = (rank, length, start, size, kind)
        if best is None:
            position += 1
            continue
        _, length, start, size, kind = best
        pairs.append((position, position + length, start, start + size, kind))
        position, cursor = position + length, start + size
    return pairs


def match_units(wanted, near):
    """Caption units against spoken units, one to one and in order: (caption positions matched, owners of the spoken
    units used, review pairs as (rule, caption units, spoken units)). Equal units whose accents differ, spelling-only
    differences and meaning-changing contractions are matched and returned for review."""
    caption, spoken = [entry['unit'] for entry in wanted], [entry['unit'] for entry in near]
    hit, owners, prompts = set(), [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, caption, spoken, autojunk=False).get_opcodes():
        if tag == 'equal':
            hit.update(range(i1, i2))
            owners.extend(owner for entry in near[j1:j2] for owner in entry['owners'])
            for a, b in zip(wanted[i1:i2], near[j1:j2]):
                if a['marked'] != b['marked']:
                    prompts.append(('spelled differently from the words', [a], [b]))
        elif tag == 'replace':
            for a, b, c, d, kind in align_replaced(wanted[i1:i2], near[j1:j2]):
                hit.update(range(i1 + a, i1 + b))
                owners.extend(owner for entry in near[j1 + c:j1 + d] for owner in entry['owners'])
                if kind == 'spelling':
                    prompts.append(('spelled differently from the words', wanted[i1 + a:i1 + b], near[j1 + c:j1 + d]))
                elif kind == 'contraction':
                    prompts.append(('contraction differs from the words', wanted[i1 + a:i1 + b], near[j1 + c:j1 + d]))
    return hit, owners, prompts


def raw_words(units):
    """The caption's own words behind some units, each raw token once: numbers as written (-10, .5), other words as
    dialogue tokens."""
    seen = {}
    for entry in units:
        for sequence, raw in entry['raws']:
            seen.setdefault(sequence, raw)
    result = []
    for _, raw in sorted(seen.items()):
        result.extend([raw] if re.search(r'\d', raw) else tokens_of(raw))
    return result


def middle(values):
    """The median of a non-empty list."""
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def ordered_offsets(cues, words, lookahead=2000, measured_only=False, matches=None):
    """Start and end offsets (speech minus caption) of the captions found in order as complete word sequences, each
    searched at most `lookahead` units past the previous match. With measured_only, retain a match only when both
    its first and last word edges are measured; skipped matches still advance the ordered cursor."""
    spoken = units_of([(word['text'], index) for index, word in enumerate(words)])
    tokens = [entry['unit'] for entry in spoken]
    positions = {}
    for position, token in enumerate(tokens):
        positions.setdefault(token, []).append(position)
    cursor = 0
    starts = []
    ends = []
    for number, cue in enumerate(cues):
        target = [entry['unit'] for entry in units_of([(cue['text'], 0)])]
        if not target:
            continue
        candidates = positions.get(target[0], [])
        k = bisect.bisect_left(candidates, cursor)
        while k < len(candidates) and candidates[k] < cursor + lookahead:
            found = candidates[k]
            if tokens[found:found + len(target)] == target:
                first = words[spoken[found]['owners'][0]]
                last = words[spoken[found + len(target) - 1]['owners'][-1]]
                measured = not (first.get('estimated') or last.get('estimated'))
                start_offset = first['start'] - float(cue['start'])
                end_offset = last['end'] - float(cue['end'])
                if matches is not None:
                    matches.append((number, start_offset, end_offset, measured))
                if not measured_only or measured:
                    starts.append(start_offset)
                    ends.append(end_offset)
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
                                ('leaves before the speech ends', last - end, 1),
                                ('outlasts the speech', end - last, 1)):
        if measured[edge] and seconds > margin + 1e-8:
            review.append({'cue': number, 'rule': rule, 'difference_s': round(seconds, 4)})
    return review


def is_dialogue(text):
    """Whether a transcript word is speech a caption should carry: not a sound description and not a filler."""
    tokens = dialogue_tokens(text)
    return bool(tokens) and not all(token in FILLERS for token in tokens)


def uncaptioned_speech(words, used, spans, gap=1.0):
    """Every dialogue word no caption matched: those inside a caption's time, by caption ({number: [indexes]}), and
    runs of the rest (between captions or outside them all), as review prompts with their times."""
    starts = [span[0] for span in spans]
    inside, runs = {}, []
    for index, word in enumerate(words):
        if index in used or not is_dialogue(word['text']):
            continue
        position = bisect.bisect_right(starts, word['start']) - 1
        if position >= 0 and word['end'] <= spans[position][1] + 1e-9:
            inside.setdefault(position + 1, []).append(index)
        elif runs and word['start'] - words[runs[-1][-1]]['end'] < gap:
            runs[-1].append(index)
        else:
            runs.append([index])
    prompts = [{'rule': 'speech with no caption', 'start': round(words[run[0]]['start'], 3),
                'end': round(words[run[-1]]['end'], 3), 'words': [words[index]['text'] for index in run]}
               for run in runs]
    return inside, prompts


def check_word_timing(cues, words, margin, reach=.5, coverage=None, offset_details=None):
    """Compare each caption with the words spoken under it in a word-timed transcript of the current audio.

    Each caption is matched, in order and one word to one caption, against the words overlapping it (or within
    `reach` seconds of it). A caption word not spoken there is stale (cut from the dialogue, left on screen); a
    caption matching nothing there is false or misplaced, even when the same words are spoken further away. A whole
    file offset (starts and ends of the captions found in order shifted together, by over 0.5 s) is reported once and
    allowed for when matching. Sound descriptions ([laughs], music symbols) are left for review. Words written
    differently but said the same (numbers in digits or words, certain contractions and their expansions, case,
    punctuation, hyphenation) match; a sign, decimal point or separator that differs (-10 / 10, .5 / 5, 1-2 / 12) does
    not. A word that differs only in spelling or accents (Jon / John, Jose / Jos\xe9), words joined differently
    (every day / everyday) and a contraction whose reading changes the meaning ("we'd" for "we did") are review
    prompts. Every transcript word is then checked against the whole caption timeline: dialogue no caption carries,
    inside a caption's time or between and outside them, is a review prompt with its time (fillers such as "um" are
    left out). Entrances and exits are review prompts, measured against the actual speech. With a `coverage` dict,
    it is filled with the counts: words, matched, inside captions but not captioned, outside every caption."""
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
    matches = []
    ordered_offsets(cues, words, matches=matches)
    measured_matches = [match for match in matches if match[3]]
    estimated_matches = [match for match in matches if not match[3]]

    def consistent_offset(rows):
        """A shared start and end displacement supported by at least three matched captions."""
        if len(rows) < 3:
            return None
        early = middle([row[1] for row in rows])
        late = middle([row[2] for row in rows])
        if abs(early) > .5 and abs(late) > .5 and early * late > 0 and abs(early - late) <= .25:
            return early
        return None

    shift = consistent_offset(measured_matches)
    basis = 'measured' if shift is not None else None
    scope = 'whole file' if shift is not None else None
    if shift is not None:
        findings.append({'rule': 'captions offset from the dialogue', 'offset_s': round(-shift, 3)})
    elif len(measured_matches) < 3 and estimated_matches:
        shift = consistent_offset(matches)
        if shift is not None:
            basis = 'estimated'
            scope = 'whole file'
    elif estimated_matches:
        shift = consistent_offset(estimated_matches)
        if shift is not None:
            basis = 'estimated'
            scope = 'estimated captions'
    shifts = [0.0] * len(cues)
    if basis == 'estimated':
        review.append({'rule': 'apparent offset from estimated word times: listen',
                       'offset_s': round(-shift, 3), 'scope': scope})
    if shift is not None and scope == 'whole file':
        shifts = [shift] * len(cues)
    elif shift is not None:
        for number, start_offset, end_offset, measured in estimated_matches:
            if abs(start_offset - shift) <= .25 and abs(end_offset - shift) <= .25:
                shifts[number] = shift
    if offset_details is not None:
        offset_details.update({'offset_basis': basis, 'offset_scope': scope,
                               'offset_s': round(-shift, 3) if shift is not None else None})
    if not cues and any(dialogue_tokens(word['text']) for word in words):
        findings.append({'rule': 'no captions for dialogue'})
    regions = []
    used = set()
    unmeasured = []
    for number, cue in enumerate(cues, 1):
        start, end = float(cue['start']) + shifts[number - 1], float(cue['end']) + shifts[number - 1]
        moment = round(float(cue['start']), 3)
        wanted = units_of([(cue['text'], number)])
        if not wanted:
            review.append({'cue': number, 'rule': 'not dialogue: check by listening', 'caption': cue['text']})
            regions.append(None)
            continue
        near = units_of([(words[index]['text'], index) for index in around(start - reach, end + reach)
                         if index not in used])
        hit, matched, prompts = match_units(wanted, near)
        if not hit:
            spoken = [words[index]['text'] for index in around(start, end)]
            rule = 'caption does not match the dialogue' if spoken else 'caption over no matching speech'
            finding = {'cue': number, 'rule': rule, 'caption': cue['text'], 'start': moment}
            findings.append({**finding, **({'spoken': ' '.join(spoken)} if spoken else {})})
            regions.append(None)
            continue
        stale = raw_words([entry for k, entry in enumerate(wanted) if k not in hit and entry['kind'] != 'separator'])
        if stale:
            findings.append({'cue': number, 'rule': 'caption words not in the dialogue', 'words': stale,
                             'caption': cue['text'], 'start': moment})
        for rule, caption_units, spoken_units in prompts:
            owners = dict.fromkeys(owner for entry in spoken_units for owner in entry['owners'])
            review.append({'cue': number, 'rule': rule, 'start': moment, 'caption_words': raw_words(caption_units),
                           'spoken_words': [words[owner]['text'] for owner in owners]})
        used.update(matched)
        first = min(matched, key=lambda index: words[index]['start'])
        last = max(matched, key=lambda index: words[index]['end'])
        region = (words[first]['start'], words[last]['end'])
        regions.append(region)
        measured = (not words[first].get('estimated'), not words[last].get('estimated'))
        if not all(measured):
            unmeasured.append(number)
        review.extend(entrance_and_exit(number, cue, region, margin, measured))
    spans = sorted((float(cue['start']) + shifts[number - 1], float(cue['end']) + shifts[number - 1], number)
                   for number, cue in enumerate(cues, 1))
    inside, outside = uncaptioned_speech(words, used, [(span[0], span[1]) for span in spans])
    for position, indexes in sorted(inside.items()):
        review.append({'cue': spans[position - 1][2], 'rule': 'spoken but not captioned',
                       'start': round(words[indexes[0]]['start'], 3), 'words': [words[i]['text'] for i in indexes]})
    review.extend(outside)
    if unmeasured:
        review.append({'rule': 'entrances or exits not measured: estimated word times', 'cues': unmeasured})
    if coverage is not None:
        dialogue = sum(1 for word in words if is_dialogue(word['text']))
        all_dialogue = [index for index, word in enumerate(words) if dialogue_tokens(word['text'])]
        coverage.update({'words': dialogue, 'matched': sum(1 for index in used if is_dialogue(words[index]['text'])),
                         'inside_captions_not_captioned': sum(len(indexes) for indexes in inside.values()),
                         'outside_captions': sum(len(prompt['words']) for prompt in outside),
                         'all_dialogue_words': len(all_dialogue),
                         'all_dialogue_matched': sum(1 for index in all_dialogue if index in used)})
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


def decoded_frame_count(ffprobe, path):
    """Count decoded input frames so overlay EOF cannot add or drop a frame."""
    result = subprocess.run([ffprobe, '-v', 'error', '-threads', '8', '-select_streams', 'v:0', '-count_frames',
                             '-show_entries', 'stream=nb_read_frames', '-of', 'json', path],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('cannot count input video frames: ' + result.stderr[-500:])
    streams = json.loads(result.stdout).get('streams') or []
    value = (streams[0] if streams else {}).get('nb_read_frames')
    if not str(value).isdigit() or int(value) < 1:
        raise ValueError('cannot count input video frames')
    return int(value)


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
        if not Path(path).is_file():
            raise ValueError(f'font not found: {path}; pass an existing font file with --font')
        try:
            ImageFont.truetype(path, 24)
        except OSError as error:
            raise ValueError(f'cannot load font {path}; pass a supported font file with --font') from error
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


def caption_font(path, size, weight=700):
    """Use the intended weight on variable fonts and the requested fixed face otherwise."""
    font = ImageFont.truetype(path, size)
    try:
        axes = font.get_variation_axes()
        values = []
        for axis in axes:
            name = axis['name'].decode() if isinstance(axis['name'], bytes) else str(axis['name'])
            value = max(axis['minimum'], min(axis['maximum'], weight)) if 'weight' in name.lower() else axis['default']
            values.append(value)
        font.set_variation_by_axes(values)
    except (OSError, AttributeError, KeyError):
        pass
    return font


def caption_font_description(path):
    """Describe the loaded face and whether its weight axis was set."""
    font = caption_font(path, 24)
    try:
        axes = font.get_variation_axes()
        has_weight = any('weight' in str(axis['name']).lower() for axis in axes)
    except (OSError, AttributeError, KeyError):
        has_weight = False
    return {'requested_weight': 700, 'variable_weight_used': 700 if has_weight else None,
            'face': list(font.getname()) if hasattr(font, 'getname') else None}


def complex_shaping_needed(text):
    """Detect bidirectional, combining and common context-shaped scripts."""
    ranges = ((0x0900, 0x0fff), (0x1000, 0x109f), (0x1780, 0x17ff), (0x1a00, 0x1cff),
              (0xa800, 0xabff), (0x11000, 0x11fff))
    for char in text:
        code = ord(char)
        if (unicodedata.bidirectional(char) in ('R', 'AL', 'AN') or unicodedata.category(char) in ('Mn', 'Me')
                or code in (0x200c, 0x200d) or any(first <= code <= last for first, last in ranges)):
            return True
    return False


@functools.lru_cache(maxsize=32)
def font_codepoints(path):
    """Read Unicode cmap coverage from a TrueType/OpenType face, without requiring a font package."""
    data = Path(path).read_bytes()
    if data[:4] in (b'wOFF', b'wOF2'):
        try:
            brotli = importlib.util.find_spec('brotli') or importlib.util.find_spec('brotlicffi')
            if data[:4] == b'wOF2' and not brotli:
                raise ImportError('WOFF2 coverage requires Brotli')
            from fontTools.ttLib import TTFont
            font = TTFont(path, fontNumber=0, lazy=True)
            try:
                return set((font.getBestCmap() or {}).keys())
            finally:
                font.close()
        except Exception as error:
            raise ValueError('cannot inspect compressed font coverage; choose a TTF or OTF font') from error
    try:
        offset = struct.unpack_from('>I', data, 12)[0] if data[:4] == b'ttcf' else 0
        count = struct.unpack_from('>H', data, offset + 4)[0]
        tables = {}
        for index in range(count):
            tag, _, table_offset, length = struct.unpack_from('>4sIII', data, offset + 12 + 16 * index)
            tables[tag] = (table_offset, length)
        cmap, length = tables[b'cmap']
        if cmap + length > len(data):
            raise ValueError('font cmap is truncated')
        count = struct.unpack_from('>H', data, cmap + 2)[0]
        found = set()
        for index in range(count):
            platform, encoding, relative = struct.unpack_from('>HHI', data, cmap + 4 + 8 * index)
            if platform != 0 and not (platform == 3 and encoding in (1, 10)):
                continue
            table = cmap + relative
            kind = struct.unpack_from('>H', data, table)[0]
            if kind in (12, 13):
                groups = struct.unpack_from('>I', data, table + 12)[0]
                if groups > 200000:
                    raise ValueError('font cmap has too many groups')
                for group in range(groups):
                    first, last, glyph = struct.unpack_from('>III', data, table + 16 + 12 * group)
                    if last > 0x10ffff or last < first:
                        raise ValueError('invalid font cmap group')
                    if glyph or kind == 12:
                        found.update(range(first + (glyph == 0), last + 1))
            elif kind == 4:
                segments = struct.unpack_from('>H', data, table + 6)[0] // 2
                end_pos = table + 14
                start_pos = end_pos + 2 * segments + 2
                delta_pos = start_pos + 2 * segments
                range_pos = delta_pos + 2 * segments
                for segment in range(segments):
                    end = struct.unpack_from('>H', data, end_pos + 2 * segment)[0]
                    start = struct.unpack_from('>H', data, start_pos + 2 * segment)[0]
                    delta = struct.unpack_from('>h', data, delta_pos + 2 * segment)[0]
                    distance = struct.unpack_from('>H', data, range_pos + 2 * segment)[0]
                    for code in range(start, min(end, 0xfffe) + 1):
                        if distance:
                            address = range_pos + 2 * segment + distance + 2 * (code - start)
                            glyph = struct.unpack_from('>H', data, address)[0]
                            glyph = (glyph + delta) & 0xffff if glyph else 0
                        else:
                            glyph = (code + delta) & 0xffff
                        if glyph:
                            found.add(code)
        if not found:
            raise ValueError('no Unicode cmap')
        return found
    except (KeyError, struct.error, OverflowError) as error:
        raise ValueError('cannot inspect this font; choose a valid TTF or OTF font') from error


def missing_glyphs(path, text):
    """List required characters absent from the selected face's Unicode cmap."""
    covered = font_codepoints(path)
    wanted = {ord(char) for char in text if not char.isspace() and unicodedata.category(char) not in ('Cc', 'Cf')}
    return sorted(wanted - covered)


def basic_font_coverage(path, text):
    """Use cmap when possible; label the fallback comparison with the missing-glyph image."""
    try:
        return missing_glyphs(path, text), 'Unicode cmap'
    except ValueError:
        font = caption_font(path, 32)
        notdef = font.getmask('\U0010ffff')
        signature = (notdef.size, bytes(notdef))
        absent = []
        for char in set(text):
            if char.isspace() or unicodedata.category(char) in ('Cc', 'Cf'):
                continue
            glyph = font.getmask(char)
            if (glyph.size, bytes(glyph)) == signature:
                absent.append(ord(char))
        return sorted(absent), 'Pillow missing-glyph image heuristic; cmap unavailable'


def bundled_caption_fonts():
    """Return the licensed script faces shipped with the skill."""
    root = Path(__file__).resolve().parent.parent / 'assets' / 'kit' / 'fonts'
    return [root / ('NotoSans' + name + '-Bold.ttf') for name in ('Arabic', 'Hebrew', 'Thai', 'Devanagari')]


BACKSLASH = chr(92)
SCRIPT_RANGES = {'Arabic': ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)),
                 'Hebrew': ((0x0590, 0x05FF), (0xFB1D, 0xFB4F)), 'Thai': ((0x0E00, 0x0E7F),),
                 'Devanagari': ((0x0900, 0x097F), (0xA8E0, 0xA8FF))}


def script_of(char):
    """The bundled script a character belongs to, or None for Latin, digits, spaces and punctuation."""
    code = ord(char)
    for name, ranges in SCRIPT_RANGES.items():
        if any(low <= code <= high for low, high in ranges):
            return name
    return None


def libass_size_factor(path):
    """The ASS Fontsize per pixel of em for this face. libass fits a face's OS/2 Windows ascent plus descent (its
    hhea or typographic height when those are zero) to Fontsize, so a face with tall metrics drew small letters:
    Noto Sans Arabic at 46% and Hebrew at 74% of the size asked for. 1.0 when the tables cannot be read."""
    try:
        data = Path(path).read_bytes()
        offset = struct.unpack_from('>I', data, 12)[0] if data[:4] == b'ttcf' else 0
        tables = {}
        for index in range(struct.unpack_from('>H', data, offset + 4)[0]):
            tag, _, table_offset, _ = struct.unpack_from('>4sIII', data, offset + 12 + 16 * index)
            tables[tag] = table_offset
        upem = struct.unpack_from('>H', data, tables[b'head'] + 18)[0]
        ascent, descent = struct.unpack_from('>hh', data, tables[b'hhea'] + 4)
        height = ascent - descent
        windows = 0
        if b'OS/2' in tables:
            typo_ascent, typo_descent = struct.unpack_from('>hh', data, tables[b'OS/2'] + 68)
            height = height or typo_ascent - typo_descent
            windows = sum(struct.unpack_from('>hh', data, tables[b'OS/2'] + 74))
        measured = windows if windows and height else height
        return measured / upem if upem and measured > 0 else 1.0
    except (OSError, KeyError, struct.error):
        return 1.0


def ass_font_runs(text, main_family, faces, scales=None, size=None):
    """Name the bundled face for each run of a script the main font lacks, as ASS font overrides.

    libass finds a face given through fontsdir by its family name on every platform, but on Linux its glyph fallback
    asks only the system's fontconfig, which does not know those faces, so a line mixing two scripts lost one of
    them. `faces` maps a script name to the family to use; letters of other scripts return to the main family;
    override blocks and line breaks pass through unchanged, and spaces, digits and punctuation stay in their run.
    With `scales` (family to libass_size_factor) and an em `size`, each switch also sets that face's Fontsize."""
    out, current, index = [], main_family, 0
    while index < len(text):
        char = text[index]
        if char == '{':
            end = text.find('}', index)
            end = len(text) - 1 if end < 0 else end
            out.append(text[index:end + 1])
            index = end + 1
            continue
        if char == BACKSLASH and text[index + 1:index + 2] in ('N', 'n', 'h'):
            out.append(text[index:index + 2])
            index += 2
            continue
        script = script_of(char)
        if script is not None or char.isalpha():
            wanted = faces.get(script, main_family) if script else main_family
            if wanted != current:
                fontsize = (BACKSLASH + 'fs%g' % round(size * scales.get(wanted, 1.0), 2)) if scales and size else ''
                out.append('{' + BACKSLASH + 'fn' + wanted + fontsize + '}')
                current = wanted
        out.append(char)
        index += 1
    return ''.join(out)


def caption_font_candidates(requested=None):
    """Try the requested face, bundled script faces, then common installed faces."""
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    return ([Path(requested)] if requested else []) + bundled_caption_fonts() + [
        windows / 'arial.ttf', windows / 'tahoma.ttf', windows / 'segoeui.ttf',
        windows / 'LeelawUI.ttf', windows / 'Nirmala.ttc', windows / 'seguiemj.ttf',
        windows / 'msyh.ttc', windows / 'msjh.ttc', windows / 'msgothic.ttc', windows / 'malgun.ttf',
        Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf'),
        Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'),
        Path('/System/Library/Fonts/Supplemental/Arial Unicode.ttf')]


def complex_font(requested, text):
    """Choose one face with verified coverage for an entire shaped cue."""
    candidates = [Path(requested)] if requested else caption_font_candidates()
    best = None
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            absent = missing_glyphs(candidate, text)
            ImageFont.truetype(str(candidate), 24)
        except (OSError, ValueError):
            continue
        if not absent:
            return str(candidate)
        if best is None or len(absent) < len(best):
            best = absent
    if best:
        codes = ', '.join('U+%04X' % code for code in best[:20])
        raise ValueError('font lacks glyphs ' + codes + '; pass --font with coverage for the whole caption')
    raise ValueError('no usable font with inspectable coverage; pass --font with a TTF or OTF face')


def fallback_shaping_font(requested, text):
    """Choose a primary face when installed faces jointly cover a cue for libass fallback."""
    faces = []
    remaining = None
    for candidate in caption_font_candidates(requested):
        if not candidate.is_file():
            continue
        try:
            absent = set(missing_glyphs(candidate, text))
            ImageFont.truetype(str(candidate), 24)
        except (OSError, ValueError):
            continue
        faces.append((len(absent), str(candidate), absent))
        remaining = absent if remaining is None else remaining & absent
    if not faces or remaining:
        codes = ', '.join('U+%04X' % code for code in sorted(remaining or [])[:20])
        raise ValueError('available fonts lack glyphs ' + codes + '; install a font or pass --font with coverage')
    _, face, absent = min(faces, key=lambda row: row[0])
    return face, sorted(absent)


def unresolved_libass_glyphs(log):
    """Distinguish a successful fallback selection from a missing rendered glyph."""
    lines = log.splitlines()
    for index, line in enumerate(lines):
        if 'fontselect: failed to find' in line.lower():
            return True
        if not re.search(r'Glyph 0x[0-9a-f]+ not found', line, re.IGNORECASE):
            continue
        if 'broken font? trying all charmaps' in line.lower():
            prior = [item for item in lines[:index] if 'fontselect:' in item.lower()
                     or re.search(r'Glyph 0x[0-9a-f]+ not found', item, re.IGNORECASE)]
            glyph = re.search(r'Glyph (0x[0-9a-f]+)', line, re.IGNORECASE).group(1).lower()
            if (len(prior) >= 2 and 'fontselect:' in prior[-1].lower() and '->' in prior[-1]
                    and '-> (null)' not in prior[-1].lower() and glyph in prior[-2].lower()
                    and 'selecting one more font' in prior[-2].lower()):
                continue
            return True
        if 'selecting one more font' not in line.lower():
            return True
        following = []
        for later in lines[index + 1:]:
            if re.search(r'Glyph 0x[0-9a-f]+ not found', later, re.IGNORECASE):
                break
            following.append(later)
        if not any('fontselect:' in later and '->' in later and '-> (null)' not in later.lower()
                   for later in following):
            return True
    return False


def render_shaped_caption(ffmpeg, temp, width, height, safe, cue, active, font_path, requested_size, plate):
    """Paint a complete complex-script cue through libass and retain its alpha and placement."""
    text = cue['text']
    if any(char in text for char in '{}\\'):
        raise ValueError('complex-script caption contains ASS control characters; use plain text without braces or \\')
    font = ImageFont.truetype(font_path, 24)
    family = font.getname()[0]
    if ',' in family or '\n' in family:
        raise ValueError('font family name cannot be represented safely in ASS')
    words = list(re.finditer(r'\S+', text))
    if active is not None and 0 <= active < len(words):
        word = words[active]
        text = (text[:word.start()] + r'{\c&H40DCFF&}' + text[word.start():word.end()]
                + r'{\c&HFFFFFF&}' + text[word.end():])
    text = text.replace('\n', r'\N')
    left, top, right, bottom = safe
    intended = requested_size or max(12, round(height * .045))
    with tempfile.TemporaryDirectory(prefix='shape-', dir=temp) as folder:
        folder = Path(folder)
        shutil.copyfile(font_path, folder / ('font' + Path(font_path).suffix))
        # libass must be able to discover bundled fallback faces even when they are not installed system-wide.
        remaining = set(missing_glyphs(font_path, cue['text']))
        faces = {}
        scales = {family: libass_size_factor(font_path)}
        for candidate in bundled_caption_fonts():
            if not remaining or not candidate.is_file() or candidate.resolve() == Path(font_path).resolve():
                continue
            try:
                absent = set(missing_glyphs(candidate, cue['text']))
            except (OSError, ValueError):
                continue
            covered = remaining - absent
            if covered:
                shutil.copyfile(candidate, folder / candidate.name)
                remaining &= absent
                family_name = ImageFont.truetype(str(candidate), 12).getname()[0]
                scales[family_name] = libass_size_factor(candidate)
                for code in covered:
                    if script_of(chr(code)):
                        faces[script_of(chr(code))] = family_name
        chosen = None
        for size in range(intended, 7, -1):
            # `size` is the em in pixels, as on the Pillow path; libass takes it scaled by each face's metrics.
            line = ass_font_runs(text, family, faces, scales, size) if faces else text
            ass = ('[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nWrapStyle: 0\n'
                   '[V4+ Styles]\n'
                   'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,'
                   'Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,'
                   'Alignment,MarginL,MarginR,MarginV,Encoding\n'
                   'Style: Default,%s,%g,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,'
                   '1,0,0,2,%d,%d,%d,-1\n'
                   '[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
                   'Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,%s\n') % (
                       width, height, family, round(size * scales[family], 2), left, width - right,
                       height - bottom + 8, line)
            with open(folder / 'shape.ass', 'w', encoding='utf-8', newline='\n') as handle:
                handle.write(ass)
            command = [ffmpeg, '-hide_banner', '-loglevel', 'info', '-nostdin', '-f', 'lavfi',
                       '-i', f'color=black:s={width}x{height}:r=1:d=1', '-vf',
                       # Paint in RGB: on the default yuv420p frame a coloured highlight bled a pixel through chroma
                       # subsampling, which moved the measured ink box between highlight states.
                       'format=rgb24,ass=filename=shape.ass:fontsdir=.:shaping=complex', '-frames:v', '1',
                       '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
            result = subprocess.run(command, cwd=folder, capture_output=True)
            log = result.stderr.decode('utf-8', 'replace')
            if result.returncode or len(result.stdout) != width * height * 3:
                raise ValueError('libass caption shaping failed: ' + log[-800:])
            if 'HarfBuzz' not in log or '(COMPLEX)' not in log:
                raise ValueError('FFmpeg libass does not report HarfBuzz complex shaping; install a supported build')
            if unresolved_libass_glyphs(log):
                raise ValueError('libass could not find a required glyph in its selected font; choose another --font')
            rgb = np.frombuffer(result.stdout, np.uint8).reshape(height, width, 3).copy()
            mask = Image.fromarray(np.max(rgb, axis=2).astype(np.uint8), 'L')
            bounds = mask.getbbox()
            if bounds and bounds[0] >= left + 2 and bounds[1] >= top + 6 and bounds[2] <= right - 2 \
                    and bounds[3] <= bottom - 2:
                font_log = [line.strip() for line in log.splitlines() if 'fontselect:' in line]
                if not font_log:
                    raise ValueError('libass did not report its selected font; cannot verify caption glyph coverage')
                chosen = (size, rgb, mask, bounds, font_log)
                break
        if chosen is None:
            raise ValueError('complex-script caption cannot fit in the safe area; shorten it or widen the area')
        size, rgb, mask, bounds, font_log = chosen
        canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        pad = plate_padding(size)
        box = (max(left, bounds[0] - pad), max(top, bounds[1] - 6), min(right - 1, bounds[2] + pad), bottom - 1)
        if plate:
            draw.rounded_rectangle(box, radius=4, fill=(0, 0, 0, 190))
        outline = mask.filter(ImageFilter.MaxFilter(3))
        canvas.paste((0, 0, 0, 255), (0, 0), outline)
        alpha = np.maximum(np.asarray(mask, dtype=np.float32), 1.0)
        straight = np.clip(np.rint(rgb.astype(np.float32) * 255 / alpha[:, :, None]), 0, 255).astype(np.uint8)
        glyphs = Image.fromarray(straight, 'RGB').convert('RGBA')
        glyphs.putalpha(mask)
        canvas.alpha_composite(glyphs)
        primary_missing = missing_glyphs(font_path, cue['text'])
        layout = {'requested_size': intended, 'size': size, 'lines': cue['text'].split('\n'),
                  'sensitive_break': False, 'shaping': 'libass HarfBuzz complex',
                  'font_path': font_path, 'missing_glyphs': [], 'primary_font_missing_glyphs': primary_missing,
                  'coverage_method': ('libass fallback; checked missing-glyph log' if primary_missing
                                      else 'primary font Unicode cmap'),
                  'font_selection': font_log,
                  'font_selection_note': 'libass reports a selected face, not always its exact file path'}
        if 'broken font? trying all charmaps' in log.lower():
            layout['font_selection_note'] += '; libass retried alternate charmaps, inspect the rendered glyphs'
        return canvas, list(box), layout


def measured_caption_lines(draw, text, font, size, width, height):
    """Try the supplied lines and legal word breaks using the actual face and ink bounds."""
    original = text.split('\n')
    candidates = [(0, original, False)]
    if len(original) == 1:
        words = [{'text': word} for word in re.findall(r'\S+', text)]
        for index, match in enumerate(re.finditer(r'\s+', text), 1):
            if index >= len(words):
                continue
            lines = [text[:match.start()], text[match.end():]]
            if all(lines):
                sensitive = protected_break(words, index)
                candidates.append((break_score(words, index) - (1000 if sensitive else 0), lines, sensitive))
    stroke = max(1, round(size * .06))
    gap = max(2, size // 4)
    fits = []
    for score, lines, sensitive in candidates:
        boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=stroke) for line in lines]
        widths = [box[2] - box[0] for box in boxes]
        total = sum(box[3] - box[1] for box in boxes) + gap * (len(lines) - 1)
        if max(widths, default=0) + 16 <= width and total + 16 <= height:
            fits.append((len(lines) == len(original), score, -abs(widths[0] - widths[-1]),
                         lines, boxes, total, sensitive))
    return max(fits, key=lambda row: row[:3])[3:] if fits else None


def plate_padding(size):
    """Space between a caption's ink and its plate's sides: wide enough that the contrast sample around the letters
    stays on the plate."""
    return max(10, round(size * .5))


def render_caption(width, height, safe, cue, active, font_path, requested_size, plate, metadata=None):
    """Render each complete line once; highlighting changes its paint, not its geometry."""
    left, top, right, bottom = safe
    intended = requested_size or max(12, round(height * .045))
    size = intended
    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    layout = None
    while size >= 8:
        font = caption_font(font_path, size)
        layout = measured_caption_lines(draw, cue['text'], font, size, right - left, bottom - top)
        if layout:
            break
        size -= 1
    if not layout:
        raise ValueError(f"caption {cue['text']!r} cannot fit at 8 px in {right - left}x{bottom - top}; "
                         'use a wider safe area, a shorter caption, or a different font')
    lines, ink_boxes, total, sensitive = layout
    if metadata is not None:
        metadata.update({'requested_size': intended, 'size': size, 'lines': lines, 'sensitive_break': sensitive})
    y = bottom - total - 8
    # The plate hugs the text: a plate across the whole safe area under two words read as an overlong bar to a
    # person reviewing a cut.
    widest = max((ink[2] - ink[0] for ink in ink_boxes), default=0)
    pad = plate_padding(size)
    middle = (left + right) / 2
    box = (max(left, math.floor(middle - widest / 2 - pad)), y - 6,
           min(right - 1, math.ceil(middle + widest / 2 + pad)), bottom - 1)
    if plate:
        draw.rounded_rectangle(box, radius=4, fill=(0, 0, 0, 190))
    word_index = 0
    stroke = max(1, round(size * .06))
    for line, ink in zip(lines, ink_boxes):
        x = (left + right - (ink[2] - ink[0])) / 2 - ink[0]
        line_y = y - ink[1]
        draw.text((x, line_y), line, font=font, fill='white', stroke_width=stroke, stroke_fill='black')
        words = list(re.finditer(r'\S+', line))
        chosen = active - word_index if active is not None else -1
        if 0 <= chosen < len(words):
            if any(unicodedata.bidirectional(char) in ('R', 'AL', 'AN') for char in line):
                raise ValueError('indexed highlighting of bidirectional text is not supported; use whole captions')
            match = words[chosen]
            start = math.floor(x + draw.textlength(line[:match.start()], font=font))
            stop = math.ceil(x + draw.textlength(line[:match.end()], font=font))
            mask = Image.new('L', (width, height), 0)
            ImageDraw.Draw(mask).text((x, line_y), line, font=font, fill=255)
            restrict = Image.new('L', (width, height), 0)
            ImageDraw.Draw(restrict).rectangle((start, 0, stop, height), fill=255)
            from PIL import ImageChops
            mask = ImageChops.multiply(mask, restrict)
            canvas.paste((255, 220, 64, 255), (0, 0), mask)
        word_index += len(words)
        y += ink[3] - ink[1] + max(2, size // 4)
    return canvas, list(box)


def contrast_mask(overlay):
    """Separate solid text from nearby plate or footage pixels for a bounded contrast sample."""
    rgba = np.asarray(overlay.convert('RGBA'))
    foreground = ((rgba[:, :, 0] >= 240) & (rgba[:, :, 1] >= 200) & (rgba[:, :, 2] >= 30)
                  & (rgba[:, :, 3] >= 240))
    expanded = np.asarray(Image.fromarray((foreground * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(15))) > 0
    background = expanded & ~foreground & (rgba[:, :, 3] < 230)
    mask = np.zeros(foreground.shape, dtype=np.uint8)
    mask[background] = 128
    mask[foreground] = 255
    return Image.fromarray(mask, 'L')


def title_contrast_mask(path):
    """An encoded contrast mask for a rendered title image: its opaque letters against the pixels just around them,
    shadow included. Titles can be any colour, so the letters are found by opacity. None when there is nothing around
    the letters to compare with, as on a full-frame card."""
    with Image.open(path) as image:
        alpha = np.asarray(image.convert('RGBA'))[:, :, 3]
    text = alpha >= 240
    near = np.asarray(Image.fromarray((text * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(15))) > 0
    around = near & ~text & (alpha < 230)
    if np.count_nonzero(text) < 5 or np.count_nonzero(around) < 5:
        return None
    mask = np.zeros(alpha.shape, dtype=np.uint8)
    mask[around] = 128
    mask[text] = 255
    output = io.BytesIO()
    Image.fromarray(mask, 'L').save(output, format='PNG', optimize=True)
    return base64.b64encode(output.getvalue()).decode('ascii')


def contrast_from_mask(ffmpeg, video, time_s, encoded_mask):
    """Measure one decoded frame against a saved text mask; None means the sample was inconclusive."""
    parts = contrast_parts(ffmpeg, video, time_s, encoded_mask)
    if parts is None:
        return None
    fg, bg = parts
    return round((max(fg, bg) + .05) / (min(fg, bg) + .05), 2)


def contrast_parts(ffmpeg, video, time_s, encoded_mask):
    """The WCAG luminances (letters, ground) contrast_from_mask compares: the letters' 25th percentile and the
    ground's 75th, from one decoded frame; None when the sample is inconclusive."""
    try:
        mask_bytes = base64.b64decode(encoded_mask, validate=True)
        with Image.open(io.BytesIO(mask_bytes)) as image:
            mask = np.asarray(image.convert('L'))
        height, width = mask.shape
        if width <= 0 or height <= 0 or width * height > 3840 * 2160:
            return None
        result = subprocess.run([ffmpeg, '-v', 'error', '-ss', f'{time_s:.6f}', '-i', str(video),
                                 '-map', '0:v:0', '-frames:v', '1', '-vf', f'scale={width}:{height}',
                                 '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True)
        if result.returncode or len(result.stdout) != width * height * 3:
            return None
        frame = np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width, 3)
        foreground = mask == 255
        background = mask == 128
        if np.count_nonzero(foreground) < 5 or np.count_nonzero(background) < 5:
            return None
        fg = float(np.percentile(linear_luminance(frame[foreground]), 25))
        bg = float(np.percentile(linear_luminance(frame[background]), 75))
        return fg, bg
    except (ValueError, OSError, TypeError):
        return None


def sample_burn_contrast(ffmpeg, video, states):
    """Measure up to eight real burned frames and save masks for checking the final output."""
    count = len(states)
    indices = sorted({round(index * (count - 1) / min(count - 1, 7)) for index in range(min(count, 8))}) \
        if count > 1 else [0]
    samples = []
    for index in indices:
        start, end, path = states[index]
        with Image.open(path) as image:
            mask = contrast_mask(image)
        output = io.BytesIO()
        mask.save(output, format='PNG', optimize=True)
        encoded = base64.b64encode(output.getvalue()).decode('ascii')
        moment = (start + end) / 2
        ratio = contrast_from_mask(ffmpeg, video, moment, encoded)
        samples.append({'state': index + 1, 'time_s': round(moment, 4), 'ratio': ratio, 'mask_png_b64': encoded})
    ratios = [sample['ratio'] for sample in samples if sample['ratio'] is not None]
    return {'samples': samples, 'minimum_ratio': min(ratios) if ratios else None,
            'method': 'decoded frame, solid text and nearby non-text pixels; up to eight timed states',
            'note': 'A sample and local contrast estimate, not a full legibility or accessibility approval.'}



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
    """Convert to square-pixel BT.709, then overlay captions at presentation timestamps."""
    ffmpeg = find_tool('ffmpeg', args.ffmpeg)
    ffprobe = find_tool('ffprobe', args.ffprobe)
    if not ffmpeg or not ffprobe:
        raise ValueError('ffmpeg and ffprobe are required')
    video, duration = probe_video(ffprobe, args.video)
    common_spec = importlib.util.spec_from_file_location('lf_caption_render_common',
                                                        Path(__file__).with_name('render_common.py'))
    common = importlib.util.module_from_spec(common_spec)
    common_spec.loader.exec_module(common)
    geometry = common.display_geometry(video)
    assembler_spec = importlib.util.spec_from_file_location('lf_caption_assembler',
                                                           Path(__file__).with_name('assemble.py'))
    assembler = importlib.util.module_from_spec(assembler_spec)
    assembler_spec.loader.exec_module(assembler)
    colour, assumptions, conversion = assembler.colour_filter(video, int(video['width']), int(video['height']))
    if video.get('color_transfer') in ('smpte2084', 'arib-std-b67') and not assembler.has_filter(ffmpeg, 'zscale'):
        raise ValueError('HDR caption burn needs FFmpeg with zscale/libzimg; convert to SDR first')
    frames = decoded_frame_count(ffprobe, args.video)
    if args.size:
        dimensions = args.size.lower().split('x')
        if len(dimensions) != 2:
            raise ValueError('--size must be WIDTHxHEIGHT')
        width, height = map(int, dimensions)
    else:
        width, height = geometry['width'], geometry['height']
    if width <= 0 or height <= 0 or width % 2 or height % 2:
        raise ValueError('output dimensions must be positive even numbers')
    safe = safe_rectangle(width, height, args.safe)
    cues = read_input(args.input)
    states = caption_states(cues, args.highlight)
    if not states:
        raise ValueError('no caption states')
    font = choose_font(args.font)
    font_info = caption_font_description(font)
    from PIL import features
    pillow_raqm = bool(features.check('raqm'))
    complex_needed = any(complex_shaping_needed(cue['text']) for cue in cues)
    ass_available = assembler.has_filter(ffmpeg, 'ass')
    if complex_needed and not ass_available and not pillow_raqm:
        raise ValueError('complex-script captions need FFmpeg with libass or Pillow with Raqm, HarfBuzz and FriBidi')
    avoids = avoid_boxes(args.avoid, width, height)
    findings = []
    review = []
    boxes = []
    cue_numbers = {id(cue): number for number, cue in enumerate(cues, 1)}
    layouts = {}
    shaped_fonts = {}
    cue_fonts = {}
    coverage_methods = {}
    cue_shaping = {}
    font_fallbacks = {}
    with tempfile.TemporaryDirectory(prefix='caption-burn-') as temp:
        rendered = []
        for index, (start, end, cue, active) in enumerate(states):
            layout = {}
            cue_number = cue_numbers[id(cue)]
            if cue_number not in cue_fonts:
                absent, method = basic_font_coverage(font, cue['text'])
                needs_shaping = complex_shaping_needed(cue['text'])
                selected = font
                if absent or (needs_shaping and method != 'Unicode cmap'):
                    try:
                        selected = complex_font(None, cue['text'])
                    except ValueError:
                        if not ass_available:
                            raise ValueError('caption needs more than one font; install FFmpeg with libass or '
                                             'pass a font covering the whole caption')
                        selected, _ = fallback_shaping_font(font, cue['text'])
                        needs_shaping = True
                    font_fallbacks[cue_number] = absent
                    method = 'Unicode cmap'
                cue_fonts[cue_number] = selected
                cue_shaping[cue_number] = needs_shaping
                coverage_methods[cue_number] = method
            if cue_shaping[cue_number]:
                shaped_font = cue_fonts[cue_number]
                shaped_fonts[cue_number] = shaped_font
                if ass_available:
                    image, box, layout = render_shaped_caption(ffmpeg, temp, width, height, safe, cue, active,
                                                              shaped_font, args.font_size, args.plate)
                else:
                    image, box = render_caption(width, height, safe, cue, active, shaped_font,
                                                args.font_size, args.plate, metadata=layout)
                    layout.update({'shaping': 'Pillow Raqm', 'font_path': shaped_font, 'missing_glyphs': []})
            else:
                image, box = render_caption(width, height, safe, cue, active, cue_fonts[cue_number],
                                            args.font_size, args.plate,
                                            metadata=layout)
                layout.update({'font_path': cue_fonts[cue_number], 'missing_glyphs': [],
                               'coverage_method': coverage_methods[cue_number]})
            if cue_number not in layouts:
                layouts[cue_number] = {'cue': cue_number, 'text': cue['text'], **layout}
                if cue_number in font_fallbacks:
                    review.append({'rule': 'caption font fallback', 'cue': cue_number,
                                   'missing_from_preferred_font': font_fallbacks[cue_number],
                                   'font_path': cue_fonts[cue_number],
                                   'note': 'Inspect the rendered glyphs; emoji may be monochrome.'})
                if layout['sensitive_break']:
                    review.append({'rule': 'line break may split a phrase or name', 'cue': cue_number,
                                   'text': cue['text'], 'lines': layout['lines']})
                if layout['size'] != layout['requested_size']:
                    review.append({'rule': 'caption reduced to fit', 'cue': cue_number, 'text': cue['text'],
                                   'requested_size_px': layout['requested_size'], 'used_size_px': layout['size'],
                                   'choices': ['widen the safe area', 'choose a different font or line break',
                                               'shorten the approved caption']})
            image, box, conflict = position_overlay(image, safe, avoids)
            if conflict:
                findings.append({'rule': 'avoid conflict', 'start': start, 'end': end, 'chosen_box': box})
            state_path = os.path.join(temp, 'state%05d.png' % index)
            image.save(state_path)
            rendered.append((start, end, state_path))
            boxes.append({'cue': cue_number, 'start': start, 'end': end, 'box': box,
                          'active_word_index': active, 'font_size_px': layout['size']})
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
        unspecified = (None, 'unknown', 'unspecified', 'reserved')
        native_709 = (video.get('pix_fmt') == 'yuv420p' and video.get('color_range') in ('tv', 'mpeg')
                      and video.get('color_space') == 'bt709'
                      and all(video.get(key) in (*unspecified, 'bt709')
                              for key in ('color_transfer', 'color_primaries'))
                      and video.get('field_order') in (None, 'unknown', 'progressive')
                      and geometry['rotation_degrees'] == 0 and geometry['sample_aspect_ratio'] == '1'
                      and (width, height) == (int(video['width']), int(video['height'])))
        if native_709:
            # Keep the already-conformed picture in YUV; converting it to RGB and back blurs chroma everywhere.
            graph = ('[0:v]setsar=1[base];'
                     '[1:v]scale=out_color_matrix=bt709:out_range=tv,format=yuva420p[caption];'
                     '[base][caption]overlay=0:0:eof_action=repeat:format=yuv420,'
                     'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[out]')
            if any(video.get(key) in unspecified for key in ('color_transfer', 'color_primaries')):
                conversion = 'BT.709 matrix retained; untagged SDR transfer or primaries not converted'
            else:
                conversion = 'BT.709 limited-range picture retained without colour conversion'
        else:
            graph = ('[0:v]%s,scale=%d:%d:flags=lanczos,setsar=1[base];'
                     '[base][1:v]overlay=0:0:eof_action=repeat,'
                     'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,'
                     'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[out]') % (
                         colour, width, height)
        command.extend(['-filter_complex', graph, '-map', '[out]', '-map', '0:a?',
                        '-c:v', 'libx264', '-crf', str(getattr(args, 'crf', 14)), '-pix_fmt', 'yuv420p',
                        '-fps_mode', 'passthrough', '-frames:v', str(frames),
                        '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
                        '-color_range', 'tv', '-c:a', 'aac', os.path.abspath(args.out)])
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise ValueError('ffmpeg burn failed: ' + result.stderr[-1000:])
        output_frames = decoded_frame_count(ffprobe, args.out)
        if output_frames != frames:
            raise ValueError(f'caption burn returned {output_frames} frames; the input had {frames}')
        contrast = sample_burn_contrast(ffmpeg, args.out, rendered)
        if contrast['minimum_ratio'] is not None and contrast['minimum_ratio'] < 4.5:
            review.append({'rule': 'sampled caption contrast below 4.5', 'ratio': contrast['minimum_ratio']})
    note = ('A fluent reader should check the shaping, reading order and meaning; visual legibility needs review.'
            if shaped_fonts else 'Visual legibility requires human review.')
    return {'findings': findings, 'review': review, 'safe_area_pixels': list(safe), 'avoid_boxes': avoids,
            'rendered_boxes': boxes, 'cue_layouts': list(layouts.values()), 'font': font,
            'font_weight': font_info['variable_weight_used'], 'font_description': font_info,
            'plate': args.plate, 'contrast': contrast,
            'source_geometry': geometry, 'colour_conversion': conversion, 'colour_assumptions': assumptions,
            'shaping': {'pillow_raqm': pillow_raqm, 'complex_cues': sorted(shaped_fonts),
                        'renderer': ('libass with HarfBuzz' if ass_available else 'Pillow Raqm')
                        if shaped_fonts else 'Pillow'},
            'input_frames': frames, 'output_frames': output_frames, 'video_crf': getattr(args, 'crf', 14),
            'timing': 'input presentation timestamps', 'note': note}


def add_rules(parser):
    """Add the common caption reading constraints."""
    parser.add_argument('--cps', type=float)
    parser.add_argument('--line-length', type=int)
    parser.add_argument('--lines', type=int, help='maximum lines per caption')
    parser.add_argument('--min-duration', type=float)
    parser.add_argument('--max-duration', type=float)
    parser.add_argument('--gap', type=float)
    parser.add_argument('--profile', help='JSON house style and reviewed, caption-specific exceptions')
    parser.add_argument('--json', help='write the report here')


def argument_parser():
    """Define the build, check and assembler-compatible burn interfaces."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    build_parser = sub.add_parser('build', help='build matching sidecars')
    build_parser.add_argument('input')
    build_parser.add_argument('--out', required=True, help='output filename prefix')
    build_parser.add_argument('--pause-gap', type=float, default=.6,
                              help='start a new cue at pauses of this many seconds (default 0.6)')
    add_rules(build_parser)
    check_parser = sub.add_parser('check', help='check captions and optionally screen timing')
    check_parser.add_argument('input')
    check_parser.add_argument('--audio', help='audio for a speech-band envelope timing screen')
    check_parser.add_argument('--burned', help='compare caption edges and contrast in this video')
    check_parser.add_argument('--safe', help='caption region: left,top,right,bottom fractions')
    check_parser.add_argument('--ffprobe')
    check_parser.add_argument('--words', help='timed words: a transcript (words.json), the lines.json of a version '
                              'or exchange.py words; preferred over --audio')
    check_parser.add_argument('--margin', type=float, help='timing screen margin in seconds')
    check_parser.add_argument('--strict', action='store_true', help='exit 1 unless the word-based check is complete')
    check_parser.add_argument('--ffmpeg')
    add_rules(check_parser)
    burn = sub.add_parser('burn', help='burn captions using input presentation timestamps')
    burn.add_argument('video', help='input video')
    burn.add_argument('input', help='captions SRT, VTT or JSON')
    burn.add_argument('--out', required=True, help='output video')
    burn.add_argument('--crf', type=int, default=14, metavar='0-51',
                      help='H.264 quality, lower is better (default 14; 0 is lossless encoded YUV)')
    burn.add_argument('--size', help='output WIDTHxHEIGHT')
    burn.add_argument('--safe', help='left,top,right,bottom fractions; tall default 0.06,0.14,0.06,0.35')
    burn.add_argument('--avoid', action='append', default=[], help='avoid X,Y,W,H in pixels or fractions')
    burn.add_argument('--font')
    burn.add_argument('--font-size', type=int)
    plate = burn.add_mutually_exclusive_group()
    plate.add_argument('--plate', action='store_true', dest='plate', default=True,
                       help='use the default dark caption plate')
    plate.add_argument('--no-plate', action='store_false', dest='plate', help='omit the default caption plate')
    burn.add_argument('--highlight', action='store_true', help='highlight current word by index when timings exist')
    burn.add_argument('--ffmpeg')
    burn.add_argument('--ffprobe')
    burn.add_argument('--json', help='write report here')
    return parser


RULE_DEFAULTS = {'cps': 20, 'line_length': 42, 'lines': 2, 'min_duration': .8,
                 'max_duration': 7, 'gap': .04, 'margin': .25}


def configure_rules(args):
    """Read a house profile and apply explicit command-line overrides to its limits."""
    limits = dict(RULE_DEFAULTS)
    exceptions = []
    args.profile_info = None
    if args.profile:
        content = Path(args.profile).read_bytes()
        data = json.loads(content.decode('utf-8-sig'))
        if not isinstance(data, dict):
            raise ValueError('profile must be a JSON object')
        supplied = data.get('limits', {})
        exceptions = data.get('exceptions', [])
        if not isinstance(supplied, dict) or set(supplied) - set(limits):
            raise ValueError('profile limits must contain only recognised rule names')
        if not isinstance(exceptions, list):
            raise ValueError('profile exceptions must be a list')
        limits.update(supplied)
        args.profile_info = {'path': args.profile, 'sha256': hashlib.sha256(content).hexdigest()}
    for key in limits:
        value = getattr(args, key, None)
        if value is not None:
            limits[key] = value
    for key, value in limits.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('invalid rule limit: ' + key)
    if (not isinstance(limits['line_length'], int) or not isinstance(limits['lines'], int)
            or limits['line_length'] <= 0 or limits['lines'] <= 0 or limits['cps'] <= 0
            or limits['min_duration'] <= 0 or limits['max_duration'] < limits['min_duration']
            or limits['gap'] < 0 or limits['margin'] < 0):
        raise ValueError('invalid rule limits')
    for item in exceptions:
        if not isinstance(item, dict):
            raise ValueError('each profile exception must be an object')
        if any(not isinstance(item.get(key), str) or not item[key].strip() for key in ('rule', 'note', 'reviewer')):
            raise ValueError('each profile exception needs a rule, note and reviewer')
        start = item.get('start')
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
            raise ValueError('each profile exception needs a nonnegative start time')
        if 'text' in item and (not isinstance(item['text'], str) or not item['text'].strip()):
            raise ValueError('exception text, when supplied, must be nonempty')
        end = item.get('end')
        if 'end' in item and (isinstance(end, bool) or not isinstance(end, (int, float)) or not math.isfinite(end)
                              or end < start):
            raise ValueError('exception end, when supplied, must be a time at or after its start')
        if 'fingerprint' in item and (not isinstance(item['fingerprint'], str) or not item['fingerprint'].strip()):
            raise ValueError('exception fingerprint, when supplied, must be nonempty')
    for key, value in limits.items():
        setattr(args, key, value)
    args.rule_limits = limits
    args.exceptions = exceptions


def result_fingerprint(result, cue):
    """A short hash of what a reviewer saw: the caption's text and times and the result's own measurements."""
    seen = {'result': {key: value for key, value in result.items() if key not in ('cue', 'fingerprint')},
            'caption': [cue['text'], float(cue['start']), float(cue['end'])]}
    return hashlib.sha256(json.dumps(seen, sort_keys=True, default=str).encode('utf-8')).hexdigest()[:16]


def apply_exceptions(report, cues, args):
    """Move only exact, caption-specific reviewed rules to accepted; surface unused entries.

    An exception belongs to the caption it reviewed: its start, end and text must match, so a changed caption at the
    same start reopens it. With the result's fingerprint it also reopens when the result's measurements change (a
    new word basis, a moved boundary)."""
    used = set()
    accepted = []
    targets = []
    for exception in args.exceptions:
        if 'text' not in exception or 'end' not in exception:
            targets.append(None)
            continue
        targets.append([number for number, cue in enumerate(cues, 1)
                        if abs(float(cue['start']) - exception['start']) <= .000500001
                        and abs(float(cue['end']) - exception['end']) <= .000500001
                        and plain_text(exception['text']) == cue['text']])
    for group in ('findings', 'review'):
        for result in report.get(group, []):
            number = result.get('cue')
            if isinstance(number, int) and 1 <= number <= len(cues):
                result['fingerprint'] = result_fingerprint(result, cues[number - 1])
    for group in ('findings', 'review'):
        remaining = []
        for result in report.get(group, []):
            number = result.get('cue')
            cue = cues[number - 1] if isinstance(number, int) and 1 <= number <= len(cues) else None
            selected = None
            if cue is not None:
                for index, exception in enumerate(args.exceptions):
                    if (exception['rule'] == result['rule'] and targets[index] == [number]
                            and exception.get('fingerprint', result['fingerprint']) == result['fingerprint']):
                        selected = index
                        break
            if selected is None:
                remaining.append(result)
            else:
                exception = args.exceptions[selected]
                used.add(selected)
                accepted.append({**result, 'original_group': group, 'caption_start': float(cue['start']),
                                 'note': exception['note'], 'reviewer': exception['reviewer']})
        report[group] = remaining
    for index, exception in enumerate(args.exceptions):
        if index not in used:
            reason = ('names no caption text and end: copy them from the reviewed caption, so an edited caption '
                      'reopens it' if targets[index] is None else
                      'ambiguous caption identity' if len(targets[index]) > 1 else
                      'no matching caption (its text, start or end changed)' if not targets[index] else
                      'the result changed since it was reviewed (fingerprint)' if 'fingerprint' in exception
                      and any(item.get('rule') == exception['rule'] and item.get('cue') == targets[index][0]
                              for group in ('findings', 'review') for item in report.get(group, [])) else
                      'no matching rule result')
            report['review'].append({'rule': 'unused profile exception', 'reason': reason, 'exception': exception})
    report['accepted'] = accepted
    report['profile'] = args.profile_info
    report['limits'] = dict(args.rule_limits)


def protect_inputs(args):
    """Refuse any output alias of an input or another output before writing anything."""
    inputs = [getattr(args, name, None) for name in
              ('input', 'video', 'audio', 'words', 'burned', 'profile', 'font', 'ffmpeg', 'ffprobe')]
    if args.command == 'build':
        sidecars = [str(args.out) + '.' + suffix for suffix in ('srt', 'vtt', 'json')]
        outputs = sidecars + [args.json]
        project.refuse_overwriting_inputs([args.json], sidecars)
    elif args.command == 'burn':
        outputs = [args.out, args.json]
        project.refuse_overwriting_inputs([args.json], [args.out])
    else:
        outputs = [args.json]
    project.refuse_overwriting_inputs(outputs, inputs)


def segment_with_review(words, args):
    """Relax soft constraints in order, retaining required pause and source breaks."""
    trial = SimpleNamespace(**vars(args))
    changes = []
    try:
        return segment(words, trial, diagnose=False), changes
    except SegmentationError as error:
        last = error
    stages = [('minimum gap', 'gap', 0.0),
              ('minimum duration', 'min_duration', min(args.min_duration, .4)),
              ('reading speed', 'cps', max(args.cps, 30.0)),
              ('single-word cues', 'allow_orphans', True),
              ('protected phrase breaks', 'allow_protected', True),
              ('minimum duration', 'min_duration', min(args.min_duration, .001)),
              ('reading speed', 'cps', max(args.cps, 1000000.0)),
              ('maximum duration', 'max_duration', max(args.max_duration,
                                                       max(word['end'] - word['start'] for word in words) + .01)),
              ('line length for an unbreakable word', 'line_length',
               max(args.line_length, max(len(word['text']) for word in words)))]
    # Prefer a single changed rule over a stack of relaxations when either can solve the conflict.
    for label, field, value in stages:
        candidate = SimpleNamespace(**vars(args))
        if getattr(candidate, field, None) == value:
            continue
        setattr(candidate, field, value)
        try:
            cues = segment(words, candidate, diagnose=False)
            if cues:
                return cues, [{'rule': 'segmentation relaxation', 'constraint': label, 'allowed': value}]
        except SegmentationError as error:
            last = error
    for label, field, value in stages:
        if getattr(trial, field, None) == value:
            continue
        setattr(trial, field, value)
        changes.append({'rule': 'segmentation relaxation', 'constraint': label, 'allowed': value})
        try:
            cues = segment(words, trial, diagnose=False)
            if cues:
                return cues, changes
        except SegmentationError as error:
            last = error
    raise last


def run_build(args):
    """Build three sidecars and report any constraint relaxations and inferred timings."""
    protect_inputs(args)
    if not hasattr(args, 'rule_limits'):
        configure_rules(args)
    words, estimated = split_timed_lines(read_input(args.input), args.gap)
    if not words:
        raise ValueError('no timed words')
    try:
        cues, relaxed = segment_with_review(words, args)
    except SegmentationError as error:
        report = {'findings': [{'rule': error.rule, 'text': error.text}], 'review': [], 'cues': 0,
                  'word_timings_estimated': estimated}
        apply_exceptions(report, [], args)
        return report
    findings, review = validate(cues, args)
    review.extend(relaxed)
    if not cues:
        raise ValueError('caption segmentation returned no cues for timed words')
    if not any(row['rule'] in ('invalid timing', 'overlap', 'lines') for row in findings):
        write_sidecars(cues, args.out)
    report = {'findings': findings, 'review': review, 'cues': len(cues), 'word_timings_estimated': estimated,
              'note': 'Estimated timings require review against speech.' if estimated else None}
    apply_exceptions(report, cues, args)
    return report



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
    protect_inputs(args)
    if not hasattr(args, 'rule_limits'):
        configure_rules(args)
    cues = read_input(args.input)
    findings, review = validate(cues, args)
    report = {'findings': findings, 'review': review, 'cues': len(cues), 'timing_screen': {'basis': 'not requested'}}
    if args.words:
        rows, words_from = read_words(args.words)
        words, estimated = split_timed_lines(rows, overlap=True)
        coverage = {}
        offset_details = {}
        timing_findings, timing_review, regions = check_word_timing(cues, words, args.margin, coverage=coverage,
                                                                    offset_details=offset_details)
        report['timing_screen'] = {'basis': 'word timings', 'words_from': words_from, 'coverage': coverage,
                                   'margin_s': args.margin, 'regions': regions,
                                   'estimated_word_times': estimated or any(w.get('estimated') for w in words),
                                   'empty_rows_ignored': sum(1 for row in rows if not row['text']), **offset_details}
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
    apply_exceptions(report, cues, args)
    reasons = []
    if not cues:
        reasons.append('the file holds no captions')
    if report['findings']:
        reasons.append('findings remain')
    if report['review']:
        reasons.append('review prompts remain')
    if not args.words:
        reasons.append('no word basis was provided')
    elif not report['timing_screen']['coverage'].get('words'):
        reasons.append('the word basis holds no words')
    elif (report['timing_screen']['coverage']['all_dialogue_matched']
          != report['timing_screen']['coverage']['all_dialogue_words']):
        reasons.append('some dialogue words in the word basis are not captioned')
    report['complete'] = not reasons
    report['complete_reasons'] = reasons
    # One line per rule, so a pattern across a whole file reads as one thing.
    report['summary'] = {'findings': dict(collections.Counter(item['rule'] for item in report['findings'])),
                         'review': dict(collections.Counter(item['rule'] for item in report['review']))}
    return report


def main():
    """Run the selected command and return the shared script exit codes."""
    parser = argument_parser()
    args = parser.parse_args()
    try:
        protect_inputs(args)
        if args.command in ('build', 'check'):
            configure_rules(args)
        if args.command == 'build' and (not math.isfinite(args.pause_gap) or args.pause_gap <= 0):
            raise ValueError('--pause-gap must be a positive, finite number')
        if args.command == 'burn' and not 0 <= args.crf <= 51:
            raise ValueError('--crf must be between 0 and 51')
        if args.command == 'build':
            report = run_build(args)
        elif args.command == 'check':
            report = run_check(args)
        else:
            report = burn_video(args)
        if args.json:
            write_text_lf(args.json, json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        return 1 if report['findings'] or (args.command == 'check' and args.strict and not report['complete']) else 0
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
