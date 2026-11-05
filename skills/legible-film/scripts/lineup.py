#!/usr/bin/env python3
"""Line up recordings of one conversation from their sound, and name who speaks from per-person microphones.

Run through map.py, which owns the commands:

  python map.py sync PROJECT [--reference ALIAS] [--alias ALIAS ...] [--json FILE]
  python map.py sync PROJECT --check
  python map.py sync PROJECT --set ALIAS=SECONDS --note TEXT
  python map.py speakers PROJECT ALIAS --mic mic_01=Ana --mic mic_02=Ben [--margin DB]
  python map.py speakers PROJECT ALIAS --shared --speakers N [--download]
  python map.py speakers PROJECT ALIAS --rename OLD=NEW

sync finds where each source sits against one reference from the sound alone, with no clap: short stretches of each
source are searched for across the reference, and the offset that wins is then tested on fresh windows spread over the
overlap. It reports the offset, a confidence (the share of testable windows that agree, scaled down when their peaks
are weak) and the drift between the start and the end of the overlap, and saves them in map/sync.json bound to each
source's SHA-256 and sound stream. A changed source makes its row stale, a changed reference makes every row stale, and
every reader refuses a stale row. Low confidence, no overlap, two offsets that fit about equally or too little sound is
a look with its reason and is never applied; a person who has listened can set an offset with --set and a note.
Measured drift above one frame is reported and makes the command exit 1; a line in film.md uses the offset at its own
place in the recording, so the line itself stays in sync, and the sound and picture are never resampled.

speakers compares level across lined-up microphones for each word of a source's transcript. Each mic is first scaled to
its own speech (its loudest moments, then the median level of the words it clearly won), so a hot mic does not win by
gain; the mic that is clearly loudest over a word names its speaker, and a word with no clear winner keeps no label.
Labels are drafts until a person reads them, like transcripts.

speakers --shared is for one track that holds everyone. It groups the transcript's words into stretches of unbroken
talk, turns each into a voice embedding on this machine (SpeechBrain's ECAPA-TDNN, Apache-2.0, in a pinned ONNX
conversion run by onnxruntime; about 84 MB, downloaded only with --download), clusters them into the N speakers you name
and names them Speaker 1, Speaker 2 in order of appearance. A stretch too short to embed, or about as near two speakers
as one, keeps no label. The model is never given audio from outside this machine and sends nothing out. It cannot count
the speakers, tell who a person is, or see a speaker change inside a stretch, so it is weakest at quick exchanges.

What this cannot establish: the sound's arrival time is what lines up, not the moment of speech, and sound takes about
3 ms per metre, so a distant camera sits a few milliseconds behind a lavalier and by a different amount for each
speaker. A confident offset says two recordings hold the same sound, not that a picture is in sync with its own sound;
a camera whose picture and sound are already apart stays apart. A level comparison cannot tell who a person is, only
which mic heard them loudest: open mics in a small room, a shared table or a person leaning into another's mic will
mislabel words. Exit codes belong to map.py.
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

HERE = Path(__file__).resolve().parent


def load_sibling(name):
    """Load a sibling script as a module."""
    spec = importlib.util.spec_from_file_location('lf_lineup_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


project = load_sibling('project')
transcribe = load_sibling('transcribe')

SYNC_FILE = Path('map') / 'sync.json'
# Roles lined up unless named: recordings of the conversation. B-roll, screens, music, effects and stills are not.
CONVERSATION_ROLES = ('camera', 'mic', 'interview', 'vo', 'other')
RATE = 8000  # samples per second for the tested windows; one sample is 0.125 ms
SEARCH_RATE = 2000  # samples per second for the search across the reference
SEARCH_DECIMATE = RATE // SEARCH_RATE
SEARCH_BAND = (120.0, 900.0)  # Hz: where speech carries the most in a room and on a camera's microphone
TEST_BAND = (150.0, 3400.0)
# The stretch of a source searched for across the reference. A short one keeps a clock's drift under a millisecond
# inside it (at 100 parts per million), and a long one gathers more evidence where only another person's faint voice
# connects two mics, so the long one is tried when the short one finds nothing that holds.
PROBE_LENGTHS = (10.0, 30.0)
PROBE_MIN_S = 3.0
PROBES = 16
CANDIDATES = 3  # offsets tested on windows, best first, before giving up on a search
WINDOW_S = 8.0  # one tested window; long enough for a few words on each side of a pause
WINDOWS_MAX = 24
WINDOW_REACH = 0.04  # seconds around the search's answer a tested window may land
SEARCH_Z = 7.0  # a searched stretch counts when its peak stands this far out of its correlation's noise
TEST_Z = 6.0  # a tested window agrees only with a peak this strong
STRONG_Z = 10.0  # the median peak at which confidence stops being scaled down
MIN_CONFIDENCE = 0.6
MIN_WON = 0.25  # the share of the searched stretches an offset covers that must have found it
GAP_WINDOWS = 3  # this many test windows in a row that disagree mean one offset does not hold everywhere
MIN_AGREED = 2
MIN_DRIFT_SPAN_S = 60.0  # shorter overlaps cannot tell a drift from the windows' own scatter
DRIFT_LIMIT = 0.002  # 2000 parts per million: more than this between two recordings is not drift
SAME_OFFSET_S = 0.05
QUIET_DB = 40.0  # a window this far below its source's loudest second holds nothing to compare
# Speakers.
LEVEL_RATE = 16000
LEVEL_HOP_S = 0.01
LEVEL_BAND = (100.0, 4000.0)
OWN_PERCENTILE = 99.0  # a mic's own speech is about its loudest one percent of frames
FLOOR_PERCENTILE = 10.0
MARGIN_DB = 6.0  # how far the loudest mic must stand above the next, after each is scaled to its own speech
ACTIVE_DB = 10.0  # the loudest mic must stand this far above its own floor over the word


def fast_length(count):
    """The next power of two: every window here pads to one so the transforms stay quick."""
    return 1 << max(1, math.ceil(math.log2(max(2, count))))


def gcc(first, second, count, mask):
    """Generalized cross-correlation with phase weighting: a peak at k means `first`, moved k samples later, lines up
    with `second`. Weighting by phase alone is what lets a close mic and a distant one, whose tones differ, agree."""
    cross = second * np.conj(first)
    size = np.abs(cross)
    return np.fft.irfft(cross / (size + size.mean() * 1e-3 + 1e-20) * mask, count)


def band(rate, count, limits):
    """A mask over a real FFT's bins that keeps a band of frequencies."""
    freqs = np.fft.rfftfreq(count, 1 / rate)
    return ((freqs >= limits[0]) & (freqs <= limits[1])).astype(np.float64)


def noise_of(corr):
    """The correlation's noise level: robust to its peaks, from a sample of its values."""
    return float(np.median(np.abs(corr[::7]))) * 1.4826 + 1e-20


def decode(path, stream, length):
    """A source's sound as 16-bit mono samples at RATE on the source's zero-based clock."""
    command = transcribe.audio_window_command(path, stream, 0.0, length, rate=RATE, sample_format='s16le', pad=False)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
    if result.returncode:
        raise ValueError(f'{path}: sound will not decode: ' + result.stderr.decode(errors='replace')[-300:])
    return np.frombuffer(result.stdout, dtype=np.int16)


def lowered(samples):
    """Samples at SEARCH_RATE: an averaging filter, then every fourth sample."""
    kernel = np.hanning(SEARCH_DECIMATE * 8 + 1)
    kernel /= kernel.sum()
    return np.convolve(samples.astype(np.float32), kernel.astype(np.float32), mode='same')[::SEARCH_DECIMATE]


def second_levels(samples):
    """The RMS level of each second, in dB: where a source has something to compare."""
    count = len(samples) // RATE
    if not count:
        return np.zeros(0, np.float64)
    power = np.array([np.mean(samples[index * RATE:(index + 1) * RATE].astype(np.float64) ** 2)
                      for index in range(count)])
    return 10 * np.log10(power + 1e-6)


def loudest_second(levels, low, high, length):
    """The start of the loudest stretch of `length` seconds inside [low, high] seconds."""
    first, last = int(low), max(int(low), int(high - length))
    if not len(levels) or first >= len(levels):
        return low
    width = max(1, int(length))
    scores = [float(np.mean(levels[start:start + width])) for start in range(first, min(last + 1, len(levels)))]
    return float(first + int(np.argmax(scores))) if scores else low


def search(reference_low, source_low, source_levels, wanted):
    """Search stretches of a source across the whole reference: each stretch's best offset, with its time and strength.
    Blocks of the reference are compared one at a time, so memory stays bounded however long the recordings are."""
    duration = len(source_low) / SEARCH_RATE
    length = max(min(wanted, duration / 4), min(PROBE_MIN_S, duration))
    probes = []
    slots = max(1, min(PROBES, int(duration // max(length, 1.0))))
    for slot in range(slots):
        low = slot * duration / slots
        high = (slot + 1) * duration / slots
        at = loudest_second(source_levels, low, high, length)
        probes.append(at)
    size = int(length * SEARCH_RATE)
    count = fast_length(size * 4)
    mask = band(SEARCH_RATE, count, SEARCH_BAND)
    transforms = []
    for at in probes:
        piece = source_low[int(at * SEARCH_RATE):int(at * SEARCH_RATE) + size].astype(np.float64)
        transforms.append(np.fft.rfft(piece - piece.mean(), count))
    best = [{'at': at, 'offset': None, 'z': 0.0, 'others': [], 'length': length} for at in probes]
    edge = size // 2
    for start in range(0, max(1, len(reference_low)), size):
        block = reference_low[start:start + size * 2].astype(np.float64)
        if len(block) < size // 4 or not block.any():
            continue
        block_f = np.fft.rfft(block - block.mean(), count)
        for row, piece_f in zip(best, transforms):
            corr = gcc(piece_f, block_f, count, mask)
            noise = noise_of(corr)
            forward = corr[:size * 2]
            back = corr[count - edge:]
            spot = int(np.argmax(forward))
            value = float(forward[spot])
            if len(back) and float(back.max()) > value:
                spot = int(np.argmax(back)) - edge
                value = float(back.max())
            z = value / noise
            offset = (start + spot) / SEARCH_RATE - row['at']
            if z > row['z']:
                if row['offset'] is not None and abs(row['offset'] - offset) > SAME_OFFSET_S:
                    row['others'].append({'offset': row['offset'], 'z': row['z']})
                row.update(offset=offset, z=z)
            elif z >= SEARCH_Z and abs((row['offset'] or 0.0) - offset) > SAME_OFFSET_S:
                row['others'].append({'offset': offset, 'z': z})
    return best


def choose_offsets(votes):
    """The offsets the stretches agree on, best first, each as a line through time (a drifting source's offset moves).
    Empty when no stretch stands out."""
    strong = [row for row in votes if row['offset'] is not None and row['z'] >= SEARCH_Z]
    def agrees(row, base):
        return abs(row['offset'] - base['offset']) <= SAME_OFFSET_S + DRIFT_LIMIT * abs(row['at'] - base['at'])
    choices = []
    remaining = list(strong)
    while remaining and len(choices) < CANDIDATES:
        base = max(remaining, key=lambda row: sum(other['z'] for other in remaining if agrees(other, row)))
        members = [row for row in remaining if agrees(row, base)]
        choices.append(offset_line(members, base, len(strong)))
        remaining = [row for row in remaining if not agrees(row, base)]
    return choices


def offset_line(members, base, strong):
    """One candidate offset: a line through the stretches that found it."""
    slope = 0.0
    if len(members) >= 2 and max(row['at'] for row in members) - min(row['at'] for row in members) >= MIN_DRIFT_SPAN_S:
        first, last = min(members, key=lambda row: row['at']), max(members, key=lambda row: row['at'])
        slope = (last['offset'] - first['offset']) / (last['at'] - first['at'])
    offsets = [row['offset'] - slope * row['at'] for row in members]
    return {'offset': float(np.median(offsets)), 'slope': float(slope), 'members': len(members), 'strong': strong,
            'member_at': [row['at'] for row in members]}


def inside_votes(votes, choice, length, total):
    """How many searched stretches the chosen offset places wholly inside the reference, and how many of those voted
    for it. A real overlap wins most of the stretches it covers; a chance match of a few words wins one."""
    def inside(row):
        first = row['at'] + choice['offset'] + choice['slope'] * row['at']
        return first >= 0 and first + length <= total
    covered = [row for row in votes if inside(row)]
    return len(covered), sum(1 for row in covered if row['at'] in choice['member_at'])


def test_windows(reference, source, reference_levels, source_levels, choice):
    """Test the chosen offset on fresh windows across the overlap, at full resolution: (rows, overlap on the source's
    clock, windows not testable because one side is too quiet)."""
    duration = len(source) / RATE
    total = len(reference) / RATE
    def place(moment):
        return moment + choice['offset'] + choice['slope'] * moment
    low = max(0.0, -choice['offset'])
    high = min(duration, (total - choice['offset']) / (1 + choice['slope']))
    if high - low < 1.0:
        return [], (low, high), 0
    # Windows that do not overlap: one stretch that happens to match must not count three times.
    slots = int(min(WINDOWS_MAX, max(3, (high - low) // 20)))
    width = min(WINDOW_S, (high - low) / slots)
    source_top = float(source_levels.max()) if len(source_levels) else 0.0
    reference_top = float(reference_levels.max()) if len(reference_levels) else 0.0
    rows, quiet = [], 0
    size = int(width * RATE)
    reach = int(WINDOW_REACH * RATE)
    count = fast_length(size + reach * 4)
    mask = band(RATE, count, TEST_BAND)
    for slot in range(slots):
        at = loudest_second(source_levels, low + slot * (high - low) / slots,
                            low + (slot + 1) * (high - low) / slots, width)
        at = float(min(max(low, at), high - width))
        piece = source[int(at * RATE):int(at * RATE) + size].astype(np.float64)
        first = int(round(place(at) * RATE)) - reach
        region = reference[max(0, first):first + size + reach * 2].astype(np.float64)
        if len(region) < size // 2 or len(piece) < size // 2:
            quiet += 1
            continue
        source_level = 10 * math.log10(float(np.mean(piece ** 2)) + 1e-6)
        reference_level = 10 * math.log10(float(np.mean(region ** 2)) + 1e-6)
        if (source_level < source_top - QUIET_DB or reference_level < reference_top - QUIET_DB
                or not piece.any() or not region.any()):
            quiet += 1
            continue
        corr = gcc(np.fft.rfft(piece - piece.mean(), count), np.fft.rfft(region - region.mean(), count), count, mask)
        noise = noise_of(corr)
        allowed = corr[:reach * 2 + 1]
        peak = int(np.argmax(allowed))
        before = corr[peak - 1] if peak > 0 else allowed[peak]
        after = corr[peak + 1] if peak + 1 < len(corr) else allowed[peak]
        bend = before - 2 * allowed[peak] + after
        shift = 0.5 * (before - after) / bend if bend < 0 else 0.0
        offset = (max(0, first) + peak + shift) / RATE - at
        rows.append({'at': round(at + width / 2, 3), 'offset': float(offset), 'z': float(allowed[peak]) / noise})
    return rows, (low, high), quiet


def failing_run(rows, agreed):
    """The stretch of a row of test windows that do not agree which suggests a gap or a restart, as (first time, last
    time), or None. Windows that fail here and there are a weak signal; several in a row at either end of the overlap,
    or a quarter of them in a row anywhere, mean one offset does not hold for the whole recording."""
    good = {id(row) for row in agreed}
    runs, current = [], []
    for row in rows:
        if id(row) in good:
            if current:
                runs.append(current)
            current = []
        else:
            current.append(row)
    if current:
        runs.append(current)
    for run in runs:
        at_end = run[0] is rows[0] or run[-1] is rows[-1]
        if len(run) >= max(GAP_WINDOWS, len(rows) // 4) or (at_end and len(run) >= GAP_WINDOWS):
            return run[0]['at'], run[-1]['at']
    return None


def fit_line(rows):
    """A robust line through (time, offset): median of the pairwise slopes, then the median intercept."""
    times = np.array([row['at'] for row in rows], np.float64)
    values = np.array([row['offset'] for row in rows], np.float64)
    if len(rows) >= 2 and times.max() - times.min() >= MIN_DRIFT_SPAN_S:
        pairs = [(values[j] - values[i]) / (times[j] - times[i]) for i in range(len(rows))
                 for j in range(i + 1, len(rows)) if times[j] - times[i] >= MIN_DRIFT_SPAN_S / 4]
        slope = float(np.median(pairs)) if pairs else 0.0
    else:
        slope = 0.0
    intercept = float(np.median(values - slope * times))
    spread = float(np.median(np.abs(values - slope * times - intercept))) * 1.4826
    return intercept, slope, spread


def line_up(reference, source):
    """Where `source` sits against `reference` (each 8 kHz 16-bit mono): a row for sync.json, without its identity."""
    source_levels, reference_levels = second_levels(source), second_levels(reference)
    if not len(source) or not source.any():
        return {'state': 'look', 'reason': 'the source has no sound to compare'}
    if not len(reference) or not reference.any():
        return {'state': 'look', 'reason': 'the reference has no sound to compare'}
    reference_low, source_low = lowered(reference), lowered(source)
    best = None
    for wanted in PROBE_LENGTHS:
        votes = search(reference_low, source_low, source_levels, wanted)
        choices = choose_offsets(votes)
        if not choices:
            strongest = max((row['z'] for row in votes), default=0.0)
            best = best or {'state': 'look', 'confidence': 0.0, 'search_z': round(strongest, 1),
                            'reason': f'no overlap found: none of {len(votes)} stretches of this source stands out '
                                      f'anywhere in the reference (best peak {strongest:.1f}, {SEARCH_Z:g} is needed)'}
        for choice in choices:
            row = test_offset(reference, source, reference_levels, source_levels, votes, choice)
            if row['state'] == 'lined-up':
                row = second_offset(row, choice, choices)
                return another_fits(row, reference, source, reference_levels, source_levels, votes, choice)
            if best is None or row.get('confidence', 0.0) > best.get('confidence', 0.0):
                best = row
        if len(source) / RATE < wanted * 2:
            break
    return best


def second_offset(row, choice, choices):
    """A row that holds, unless a second offset also has several stretches behind it: stretches rarely agree by chance,
    so that is a recording with a gap or a restart, right on one side of it and wrong on the other."""
    rival = next((other for other in choices if other is not choice and other['members'] >= 2), None)
    if rival is None:
        return row
    times = rival['member_at']
    return dict(row, state='look', second_offset_s=round(rival['offset'], 3),
                reason=f"most of the file fits {row['offset_s']:+.3f} s, but {rival['members']} stretches near "
                       f'{project.format_time(min(times))}-{project.format_time(max(times))} on this source\'s clock '
                       f"fit {rival['offset']:+.3f} s: one recording may have a gap or a restart. Split the file there "
                       'and line up each part, or listen')


def another_fits(row, reference, source, reference_levels, source_levels, votes, choice):
    """A row that holds, unless the strongest offset any stretch found elsewhere passes the same test: in a loop or a
    jingle many offsets fit, and nothing in the sound says which is right. Speech fails this test at any other offset,
    however strong a stray peak in a stretch looked."""
    if row['state'] != 'lined-up':
        return row
    rivals = sorted((vote for vote in votes if vote['offset'] is not None and vote['at'] not in choice['member_at']
                     and abs(vote['offset'] - choice['offset']) > SAME_OFFSET_S),
                    key=lambda vote: vote['z'], reverse=True)
    tried = []
    for vote in rivals:
        if any(abs(vote['offset'] - offset) <= SAME_OFFSET_S for offset in tried):
            continue
        tried.append(vote['offset'])
        rows = test_windows(reference, source, reference_levels, source_levels,
                            {'offset': vote['offset'], 'slope': 0.0})[0]
        passed = sum(1 for item in rows
                     if item['z'] >= TEST_Z and abs(item['offset'] - vote['offset']) <= WINDOW_REACH / 2)
        if len(rows) >= 2 and passed / len(rows) >= MIN_CONFIDENCE:
            return dict(row, state='look', second_offset_s=round(vote['offset'], 3),
                        reason=f"another offset fits as well ({vote['offset']:+.3f} s as well as "
                               f"{row['offset_s']:+.3f} s): the sound repeats (a loop, a jingle, a tone), so listen "
                               'and set the offset by hand')
        if len(tried) >= 2:
            break
    return row


def test_offset(reference, source, reference_levels, source_levels, votes, choice):
    """One candidate offset tested on windows across its overlap: a row for sync.json, without its identity."""
    covered, won = inside_votes(votes, choice, votes[0]['length'], len(reference) / RATE)
    rows, (low, high), quiet = test_windows(reference, source, reference_levels, source_levels, choice)
    if high - low < 1.0:
        return {'state': 'look', 'confidence': 0.0,
                'reason': 'the offset found leaves under a second of overlap, too little to test'}
    agreed = [row for row in rows if row['z'] >= TEST_Z]
    if agreed:
        centre = float(np.median([row['offset'] - choice['slope'] * row['at'] for row in agreed]))
        agreed = [row for row in agreed
                  if abs(row['offset'] - choice['slope'] * row['at'] - centre) <= WINDOW_REACH / 2]
    tested = len(rows)
    row = {'windows': {'tested': tested, 'agreed': len(agreed), 'too_quiet': quiet},
           'search': {'stretches': len(votes), 'agreeing': choice['members'], 'other': choice['strong']
                      - choice['members']}}
    if not tested or not agreed:
        return dict(row, state='look', confidence=0.0,
                    reason=('too little sound in the overlap to test the offset' if not tested else
                            f'the offset the search found fails all {tested} test windows'))
    intercept, slope, spread = fit_line(agreed)
    strength = float(np.median([item['z'] for item in agreed]))
    confidence = len(agreed) / tested * min(1.0, strength / STRONG_Z)
    span = max(item['at'] for item in agreed) - min(item['at'] for item in agreed)
    measured = span >= MIN_DRIFT_SPAN_S and abs(slope) <= DRIFT_LIMIT
    row.update(offset_s=round(intercept, 6), drift_per_s=round(slope if measured else 0.0, 9),
               drift_s=(round(slope * (high - low), 6) if measured else None),
               confidence=round(confidence, 3), strength=round(strength, 1), spread_ms=round(spread * 1000, 2),
               overlap_source_s=[round(low, 3), round(high, 3)],
               overlap_reference_s=[round(low + intercept + slope * low, 3), round(high + intercept + slope * high, 3)])
    row['search']['covered'] = covered
    gap = failing_run(rows, agreed)
    if gap and len(agreed) >= MIN_AGREED:
        return dict(row, state='look', reason=f'the offset holds through most of the overlap but not around '
                                              f'{project.format_time(gap[0])}-{project.format_time(gap[1])} on this '
                                              "source's clock: one recording may have a gap or a restart, or that "
                                              'stretch hears something else. Split the file there, or listen')
    if covered >= 2 and won / covered < MIN_WON:
        return dict(row, state='look', reason=f'only {won} of the {covered} searched stretches this offset covers '
                                              'found it, so a few words may match by chance: these recordings may not '
                                              'hold the same conversation')
    if confidence < MIN_CONFIDENCE or len(agreed) < min(MIN_AGREED, tested):
        return dict(row, state='look', reason=f'only {len(agreed)} of {tested} test windows agree '
                                              f'(median peak {strength:.1f}), so the recordings may not hold the '
                                              'same sound, or one has a gap or a restart')
    if abs(slope) > DRIFT_LIMIT:
        return dict(row, state='look', reason=f'the offset moves {slope * 1e6:.0f} parts per million, far past any '
                                              "clock's drift: one recording has a gap, or changes speed")
    return dict(row, state='lined-up')


# ----------------------------------------------------------------------------------------------- the saved record

def media_identity(path):
    """What a row of sync.json binds to."""
    stat = path.stat()
    return {'sha256': project.file_sha256(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def source_path(root, source):
    """A registered source's file."""
    path = Path(source['path'])
    return path if path.is_absolute() else Path(root) / path


def frame_seconds(sources):
    """One frame at the fastest frame rate among the sources, else at 30 frames per second."""
    from fractions import Fraction
    rates = []
    for source in sources:
        try:
            rate = Fraction(str((source.get('video') or {}).get('fps')))
        except (ValueError, ZeroDivisionError):
            continue
        if rate > 0:
            rates.append(float(rate))
    return 1 / max(rates) if rates else 1 / 30


def registered(root):
    """{alias: source row} from map/sources.json."""
    data = project.load_json(Path(root) / 'map' / 'sources.json', None)
    if not isinstance(data, dict) or not data.get('sources'):
        raise ValueError('no sources registered; run map.py add first')
    return {row['alias']: row for row in data['sources'] if row.get('alias')}


def choose_reference(sources, named, saved):
    """The clock everything is measured on: the one named, else the one already saved, else the longest source with
    picture and sound, else the longest with sound."""
    if named:
        if named not in sources:
            raise ValueError(f'unknown alias: {named}')
        if not sources[named].get('audio'):
            raise ValueError(f'{named} has no sound to line up against')
        return named
    if saved in sources and sources[saved].get('audio'):
        return saved
    usable = [row for row in sources.values() if row.get('audio') and row.get('role') in CONVERSATION_ROLES]
    if not usable:
        raise ValueError('no registered source has sound to line up')
    return max(usable, key=lambda row: (bool(row.get('video')), float(row.get('duration_s') or 0)))['alias']


def sync_project(root, reference=None, aliases=None):
    """Measure every source of the conversation against one reference and save the result. Returns the saved record."""
    root = Path(root).resolve()
    sources = registered(root)
    target = root / SYNC_FILE
    previous = project.load_json(target, None)
    previous = previous if isinstance(previous, dict) else {}
    chosen = choose_reference(sources, reference, previous.get('reference'))
    wanted = list(aliases) if aliases else [alias for alias, row in sources.items()
                                            if row.get('role') in CONVERSATION_ROLES and alias != chosen]
    for alias in wanted:
        if alias not in sources:
            raise ValueError(f'unknown alias: {alias}')
    if chosen in wanted:
        wanted.remove(chosen)
    row = sources[chosen]
    path = source_path(root, row)
    if not path.is_file():
        raise ValueError(f'{chosen}: the source file is missing ({path}); use map.py relink')
    stream = (row.get('audio') or {}).get('index')
    identity = media_identity(path)
    if identity['sha256'] != row.get('sha256'):
        raise ValueError(f'{chosen}: the file changed since it was mapped; map it again (map.py run) first')
    reference_samples = decode(path, stream, float(row.get('duration_s') or 0))
    same_reference = previous.get('reference') == chosen and previous.get('reference_sha256') == identity['sha256']
    record = {'version': 1, 'made': project.now(), 'reference': chosen, 'reference_sha256': identity['sha256'],
              'draft': True, 'frame_s': round(frame_seconds(sources.values()), 6),
              'sources': {chosen: {'state': 'reference', 'audio_stream': stream, 'offset_s': 0.0, 'drift_per_s': 0.0,
                                   **identity}}}
    if same_reference:
        for alias, saved in (previous.get('sources') or {}).items():
            if alias not in wanted and alias != chosen and alias in sources:
                record['sources'][alias] = saved
    for alias in wanted:
        source = sources[alias]
        path = source_path(root, source)
        if not path.is_file():
            raise ValueError(f'{alias}: the source file is missing ({path}); use map.py relink')
        identity = media_identity(path)
        if identity['sha256'] != source.get('sha256'):
            raise ValueError(f'{alias}: the file changed since it was mapped; map it again (map.py run) first')
        stream = (source.get('audio') or {}).get('index')
        if stream is None:
            found = {'state': 'look', 'reason': 'the source has no sound to line up'}
        else:
            found = line_up(reference_samples, decode(path, stream, float(source.get('duration_s') or 0)))
        record['sources'][alias] = dict(found, audio_stream=stream, **identity)
    with project.file_lock(target):
        project.save_json(target, record)
    return record


def set_by_hand(root, alias, offset, note, by='person'):
    """A person who has listened sets an offset: applied like a measured one, and recorded as theirs."""
    note = (note or '').strip()
    if not note:
        raise ValueError('--set needs a nonempty --note saying what was checked')
    root = Path(root).resolve()
    sources = registered(root)
    if alias not in sources:
        raise ValueError(f'unknown alias: {alias}')
    target = root / SYNC_FILE
    with project.file_lock(target):
        record = project.load_json(target, None)
        if not isinstance(record, dict) or not record.get('reference'):
            raise ValueError('nothing to set against yet; run map.py sync PROJECT first')
        if alias == record['reference']:
            raise ValueError(f'{alias} is the reference; every other source is measured against it')
        path = source_path(root, sources[alias])
        if not path.is_file():
            raise ValueError(f'{alias}: the source file is missing ({path}); use map.py relink')
        identity = media_identity(path)
        length = float(sources[alias].get('duration_s') or 0)
        total = float(sources[record['reference']].get('duration_s') or 0)
        record['sources'][alias] = {'state': 'set-by-hand', 'offset_s': float(offset), 'drift_per_s': 0.0,
                                    'drift_s': None, 'confidence': None, 'note': note, 'by': by, 'at': project.now(),
                                    'audio_stream': (sources[alias].get('audio') or {}).get('index'),
                                    'overlap_source_s': [round(max(0.0, -offset), 3),
                                                         round(min(length, total - offset), 3)], **identity}
        project.save_json(target, record)
    project.append_jsonl(root / 'decisions.jsonl', {
        'at': project.now(), 'by': by, 'category': 'sync', 'subject': alias,
        'decision': f'Set {alias} to {offset:+.3f} s against {record["reference"]}: {note}', 'rejected': [],
        'version': project.current_version(root)})


class Lineup:
    """The saved line-up as every reader uses it: why an alias cannot be used, and a time on one source's clock on
    another's. Hashes a file only when its size or time differ from the record's, so a copied project still reads."""

    def __init__(self, root, sources=None):
        self.root = Path(root)
        self.sources = sources if sources is not None else registered(root)
        self.record = project.load_json(self.root / SYNC_FILE, None)
        if not isinstance(self.record, dict) or not isinstance(self.record.get('sources'), dict):
            self.record = None
        self.cache = {}

    def row(self, alias):
        """The saved row of a source, or None."""
        return (self.record or {}).get('sources', {}).get(alias)

    def file_problem(self, alias, row):
        """How a source's file differs from the one its row was measured on ('' when it does not)."""
        if alias not in self.sources:
            return f'{alias} is no longer registered'
        path = source_path(self.root, self.sources[alias])
        if not path.is_file():
            return f'the file of {alias} is missing'
        stat = path.stat()
        if row.get('bytes') == stat.st_size and row.get('mtime_ns') == stat.st_mtime_ns:
            pass
        elif project.file_sha256(path) != row.get('sha256'):
            return f'the file of {alias} changed since it was lined up'
        stream = (self.sources[alias].get('audio') or {}).get('index')
        if stream != row.get('audio_stream'):
            return f'the sound stream of {alias} changed since it was lined up ({row.get("audio_stream")} to {stream})'
        return ''

    def problem(self, alias):
        """Why this source's line-up cannot be used ('' when it can). A look is not usable, and neither is a stale row
        or a row measured against a reference that changed."""
        if alias in self.cache:
            return self.cache[alias]
        reason = ''
        row = self.row(alias)
        if self.record is None:
            reason = 'the project has no line-up yet'
        elif row is None:
            reason = f'{alias} is not in the line-up'
        else:
            reference = self.record.get('reference')
            reason = self.file_problem(alias, row)
            if not reason and alias != reference:
                base = self.row(reference)
                if base is None or base.get('sha256') != self.record.get('reference_sha256'):
                    reason = f'the reference {reference} is not in the saved line-up'
                else:
                    reason = self.file_problem(reference, base)
                    if not reason and row.get('state') == 'look':
                        reason = f"its line-up is a look: {row.get('reason', 'low confidence')}"
        self.cache[alias] = reason
        return reason

    def usable(self, first, second):
        """Why two sources cannot be mapped onto each other ('' when they can)."""
        return self.problem(first) or self.problem(second)

    def to_reference(self, alias, moment):
        """A time on a source's clock on the reference's clock."""
        row = self.row(alias)
        return moment * (1 + float(row.get('drift_per_s') or 0)) + float(row.get('offset_s') or 0)

    def from_reference(self, alias, moment):
        """A time on the reference's clock on a source's clock."""
        row = self.row(alias)
        return (moment - float(row.get('offset_s') or 0)) / (1 + float(row.get('drift_per_s') or 0))

    def map_time(self, first, second, moment):
        """A time on `first`'s clock on `second`'s clock."""
        return self.from_reference(second, self.to_reference(first, moment))

    def drift_note(self, alias):
        """What to say about a source that drifts by more than a frame, or ''."""
        row = self.row(alias) or {}
        frame = float((self.record or {}).get('frame_s') or 1 / 30)
        drift = row.get('drift_s')
        if drift is None or abs(float(drift)) <= frame:
            return ''
        low, high = row.get('overlap_source_s') or (0, 0)
        return (f'{alias} drifts {float(drift) * 1000:+.1f} ms over {project.format_time(float(high) - float(low))} '
                f"against {self.record['reference']}, more than one frame ({frame * 1000:.1f} ms)")

    def used_record(self, aliases):
        """What a version records about the line-up it used."""
        rows = {}
        for alias in sorted(aliases):
            row = self.row(alias) or {}
            rows[alias] = {key: row.get(key) for key in ('state', 'offset_s', 'drift_per_s', 'drift_s', 'confidence',
                                                         'sha256') if key in row}
        return {'reference': (self.record or {}).get('reference'),
                'reference_sha256': (self.record or {}).get('reference_sha256'), 'sources': rows}


def sync_report(record):
    """One line per source: what a person needs to judge the line-up."""
    frame = float(record.get('frame_s') or 1 / 30)
    reference = record['reference']
    lines = [f'reference: {reference} (every offset below is where that source\'s 0:00 falls on its clock)']
    for alias, row in record['sources'].items():
        if alias == reference:
            continue
        state = row.get('state')
        if state == 'look':
            confidence = f" (confidence {row['confidence']:.2f})" if row.get('confidence') is not None else ''
            lines.append(f"{alias}: look, not applied{confidence}: {row.get('reason')}")
            continue
        if state == 'set-by-hand':
            lines.append(f"{alias}: {row['offset_s']:+.3f} s, set by hand: {row.get('note')}")
            continue
        drift = row.get('drift_s')
        low, high = row['overlap_source_s']
        windows = row.get('windows') or {}
        text = (f"{alias}: {row['offset_s']:+.3f} s against {reference}, confidence {row['confidence']:.2f} "
                f"({windows.get('agreed')} of {windows.get('tested')} windows agree, spread "
                f"{row.get('spread_ms', 0):.1f} ms), overlap {project.format_time(low)}-{project.format_time(high)}")
        if drift is None:
            text += f'; drift not measurable over {high - low:.1f} s'
        elif abs(drift) > frame:
            text += (f'; DRIFT {drift * 1000:+.1f} ms from the start to the end of the overlap, more than one frame '
                     f'({frame * 1000:.1f} ms): each line uses the offset at its own place, and a long unbroken take '
                     'moves against its picture')
        else:
            text += f'; drift {drift * 1000:+.1f} ms over the overlap, under one frame'
        lines.append(text)
    return lines


def check_report(root):
    """(lines, exit code) for map.py sync --check: the saved line-up as a reader sees it now, nothing measured."""
    root = Path(root).resolve()
    lineup = Lineup(root)
    if lineup.record is None:
        return ['the project has no line-up yet; run map.py sync PROJECT'], 1
    lines, code = sync_report(lineup.record), 0
    for alias, row in lineup.record['sources'].items():
        reason = lineup.problem(alias)
        if reason and row.get('state') != 'look':
            lines.append(f'{alias}: stale: {reason}; run map.py sync PROJECT again')
        code = 1 if reason else code
    return lines, code


# ----------------------------------------------------------------------------------------------- speakers

def speech_levels(path, stream, length):
    """A source's speech-band power every LEVEL_HOP_S, decoded in blocks so memory stays small whatever its length."""
    command = transcribe.audio_window_command(path, stream, 0.0, length, rate=LEVEL_RATE, sample_format='s16le',
                                              pad=False)
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    hop = int(LEVEL_RATE * LEVEL_HOP_S)
    block = hop * 100
    rows = []
    freqs = np.fft.rfftfreq(block, 1 / LEVEL_RATE)
    keep = (freqs >= LEVEL_BAND[0]) & (freqs <= LEVEL_BAND[1])
    while True:
        raw = process.stdout.read(block * 2)
        if not raw:
            break
        samples = np.frombuffer(raw[:len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
        if len(samples) < block:
            samples = np.pad(samples, (0, block - len(samples)))
        filtered = np.fft.irfft(np.fft.rfft(samples) * keep, block)
        rows.append((filtered[:len(filtered) // hop * hop].reshape(-1, hop) ** 2).mean(1).astype(np.float32))
    if process.wait():
        raise ValueError(f'{path}: sound will not decode')
    return np.concatenate(rows) if rows else np.zeros(0, np.float32)


class MicLevels:
    """One microphone's level track, scaled to its own speech and floor, with quick averages over any span."""

    def __init__(self, power):
        self.power = power
        self.total = np.concatenate([[0.0], np.cumsum(power.astype(np.float64))])
        positive = power[power > 0]
        self.db = 10 * np.log10(positive + 1e-12) if len(positive) else np.zeros(1)
        self.own = float(np.percentile(self.db, OWN_PERCENTILE))
        self.floor = float(np.percentile(self.db, FLOOR_PERCENTILE))

    def level(self, start, end):
        """The mean level in dB over a span of its own clock; None when the span is outside its sound."""
        first, last = int(round(start / LEVEL_HOP_S)), int(round(end / LEVEL_HOP_S))
        last = max(last, first + 1)
        if first < 0 or last > len(self.power):
            return None
        return 10 * math.log10((self.total[last] - self.total[first]) / (last - first) + 1e-12)


def word_winner(word_levels, margin):
    """Which mic names a word, from {mic: (level above its own speech, level above its own floor)}: the clearly loudest,
    else None. A mic that does not cover the word cannot be compared, so a word needs two that do."""
    usable = {mic: row for mic, row in word_levels.items() if row is not None}
    if len(usable) < 2:
        return None, None
    ranked = sorted(usable.items(), key=lambda pair: pair[1][0], reverse=True)
    top, second = ranked[0], ranked[1]
    gap = top[1][0] - second[1][0]
    if gap < margin or top[1][1] < ACTIVE_DB:
        return None, gap
    return top[0], gap


def trimmed(start, end):
    """A word's core: its edges are transcript estimates, and the neighbour's sound leaks in there."""
    length = max(0.0, end - start)
    trim = min(0.03, length * 0.2)
    return start + trim, end - trim


def word_levels(word, alias, lineup, levels):
    """Each mic's plain level over a word's core, or None where the mic does not cover it."""
    low, high = trimmed(float(word['start']), float(word['end']))
    return {mic: track.level(lineup.map_time(alias, mic, low), lineup.map_time(alias, mic, high))
            for mic, track in levels.items()}


def settle_own_levels(words, alias, lineup, levels, margin):
    """Scale each mic to the median level of the words it clearly won, a better measure of its own speech than its
    loudest moments: on two real meetings it labelled 3 to 25 points more words and got more of them right."""
    won = {mic: [] for mic in levels}
    for word in words:
        plain = word_levels(word, alias, lineup, levels)
        scaled = {mic: None if value is None else (value - levels[mic].own, value - levels[mic].floor)
                  for mic, value in plain.items()}
        winner, _ = word_winner(scaled, margin)
        if winner:
            won[winner].append(plain[winner])
    for mic, rows in won.items():
        if rows:
            levels[mic].own = float(np.median(rows))


def label_words(words, alias, lineup, levels, names, margin=MARGIN_DB):
    """Label each word in place by the mic clearly loudest over it, keeping labels a person gave. Returns the counts."""
    counts = {name: 0 for name in names.values()}
    unlabelled = kept = 0
    settle_own_levels(words, alias, lineup, levels, margin)
    for word in words:
        if word.get('speaker_by') == 'person':
            kept += 1
            if word.get('speaker') in counts:
                counts[word['speaker']] += 1
            continue
        measured = {mic: None if value is None else (value - levels[mic].own, value - levels[mic].floor)
                    for mic, value in word_levels(word, alias, lineup, levels).items()}
        winner, _ = word_winner(measured, margin)
        word['speaker'] = names[winner] if winner else None
        word.pop('speaker_by', None)
        if winner:
            word['speaker_by'] = 'mic-level'
            counts[names[winner]] += 1
        else:
            unlabelled += 1
    return {'labelled': counts, 'unlabelled': unlabelled, 'kept_from_a_person': kept}


def label_from_mics(root, alias, mics, margin=MARGIN_DB):
    """map.py speakers: read each lined-up mic's level, label the transcript's words, and refresh its record."""
    root = Path(root).resolve()
    sources = registered(root)
    if alias not in sources:
        raise ValueError(f'unknown alias: {alias}')
    if len(mics) < 2:
        raise ValueError('name at least two mics, one per person: --mic mic_01=Ana --mic mic_02=Ben')
    lineup = Lineup(root, sources)
    for mic in [alias] + [mic for mic in mics if mic != alias]:
        if mic not in sources:
            raise ValueError(f'unknown alias: {mic}')
        reason = lineup.problem(mic)
        if reason:
            raise ValueError(f'{mic} cannot be used: {reason}. Run map.py sync PROJECT, or set it by hand after '
                             'listening')
    path = root / 'map' / alias / 'words.json'
    if not path.is_file():
        raise ValueError(f'{alias} has no words.json; map or import its transcript first')
    levels = {}
    for mic in mics:
        source = sources[mic]
        levels[mic] = MicLevels(speech_levels(source_path(root, source), (source.get('audio') or {}).get('index'),
                                              float(source.get('duration_s') or 0)))
    with project.file_lock(path):
        data = project.load_json(path, None)
        if not isinstance(data, dict) or not isinstance(data.get('words'), list):
            raise ValueError(f'{path}: not a readable transcript')
        state, reason = project.transcript_state(sources[alias], data)
        if state == 'stale':
            raise ValueError(f'{alias} transcript is stale: {reason}; retranscribe or confirm it first')
        counts = label_words(data['words'], alias, lineup, levels, mics, margin)
        data['speaker_labels'] = {
            'method': 'mic-level', 'draft': True, 'at': project.now(), 'margin_db': margin,
            'mics': {mic: {'name': name, 'sha256': (lineup.row(mic) or {}).get('sha256')}
                     for mic, name in mics.items()},
            'note': 'Drafts until a person reads them: the loudest mic over a word, not an identification.', **counts}
        project.save_json(path, data)
    return counts


def rename_speaker(root, alias, renames):
    """Give speakers their names across a transcript (an imported transcript's 0 and 1, say)."""
    root = Path(root).resolve()
    path = root / 'map' / alias / 'words.json'
    if not path.is_file():
        raise ValueError(f'{alias} has no words.json')
    changed = 0
    with project.file_lock(path):
        data = project.load_json(path, None)
        for word in data.get('words', []):
            if word.get('speaker') is not None and str(word['speaker']) in renames:
                word['speaker'] = renames[str(word['speaker'])]
                changed += 1
        project.save_json(path, data)
    return changed


# ----------------------------------------------------------------------------------------------- one shared track

SHARED_REVISION = 'a9cb9321b07b4ee5b0ea47fdd25242d9cacd824a'
SHARED_URL = ('https://huggingface.co/vedk00/ecapa-voxceleb-speaker-embedding-onnx/resolve/'
              + SHARED_REVISION + '/model/')
SHARED_FILES = {'ecapa-speaker-v1.onnx': 'f46380bbaeddb929fb3a10ab63a4b1877a50e3d1e5fdd55a1b618d5651d3f64e',
                'fbank-80x201-f32.bin': '024e5073b7cfedee84408dc68dd6bafa02808fc786e67f1314e9c918297f5a63'}
SHARED_MB = 84
SHARED_RATE = 16000
GROUP_GAP_S = 0.25  # words closer than this are one stretch of talk
GROUP_LONGEST_S = 2.5  # long enough to embed well, short enough to rarely hold two speakers
GROUP_SHORTEST_S = 0.5  # shorter than this says little about a voice, and stays unlabelled
FIT_SHORTEST_S = 1.0  # the clusters are fitted on the stretches long enough to embed well
FIT_MOST = 1500  # stretches clustered, evenly sampled above this; the rest take their nearest centre
SHARED_MARGIN = 0.08  # how much nearer the best speaker's centre must be than the next (cosine similarity)


def model_folder():
    """Where the skill keeps pinned models (setup.py's per-user cache), created only when something is saved."""
    return load_sibling('setup').data_home() / 'models'


def shared_model(download):
    """The pinned model's files, fetched only with --download after their size is named. A file that does not match its
    SHA-256 is refused, wherever it came from."""
    folder = model_folder()
    missing = [name for name in SHARED_FILES if not (folder / name).is_file()]
    if missing and not download:
        raise ValueError(f'the speaker model is not on this machine. It is about {SHARED_MB} MB (SpeechBrain '
                         'ECAPA-TDNN, Apache-2.0, a pinned ONNX conversion) and downloads only when asked: add '
                         '--download. Nothing else leaves or enters this machine.')
    if missing:
        import tempfile
        import urllib.request
        print(f'Speaker model download: about {SHARED_MB} MB, Apache-2.0, into {folder}.', file=sys.stderr, flush=True)
        folder.mkdir(parents=True, exist_ok=True)
        for name in missing:
            handle, temporary = tempfile.mkstemp(prefix='.speaker-', dir=str(folder))
            os.close(handle)
            try:
                urllib.request.urlretrieve(SHARED_URL + name, temporary)
                if project.file_sha256(temporary) != SHARED_FILES[name]:
                    raise ValueError(f'the downloaded {name} does not match its pinned SHA-256')
                os.replace(temporary, folder / name)
            finally:
                Path(temporary).unlink(missing_ok=True)
    for name, digest in SHARED_FILES.items():
        if project.file_sha256(folder / name) != digest:
            raise ValueError(f'{folder / name} does not match its pinned SHA-256; delete it and add --download')
    return folder


class VoiceModel:
    """The pinned embedding model: 80 mel bands at 16 kHz, each stretch's mean removed, as the model was trained."""

    def __init__(self, folder):
        try:
            import onnxruntime as ort
        except ImportError as error:
            raise ValueError(project.dependency_message('onnxruntime', context='transcription')) from error
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(folder / 'ecapa-speaker-v1.onnx'), sess_options=options,
                                            providers=['CPUExecutionProvider'])
        self.names = [row.name for row in self.session.get_inputs()]
        self.table = np.fromfile(folder / 'fbank-80x201-f32.bin', dtype='<f4').reshape(201, 80)
        self.window = np.hamming(400).astype(np.float32)

    def __call__(self, samples):
        padded = np.pad(samples.astype(np.float32) / 32768.0, 200)
        count = 1 + (len(padded) - 400) // 160
        frames = np.stack([padded[index * 160:index * 160 + 400] * self.window for index in range(count)])
        bands = (np.abs(np.fft.rfft(frames, 400)) ** 2) @ self.table
        levels = 10 * np.log10(np.maximum(bands, 1e-10))
        levels = np.maximum(levels, levels.max() - 80)
        features = (levels - levels.mean(0, keepdims=True)).astype(np.float32)[None]
        vector = self.session.run(None, {self.names[0]: features, self.names[1]: np.array([1.0], np.float32)})[0]
        return vector.reshape(-1).astype(np.float64)


def word_groups(words):
    """Lists of indexes of words in unbroken talk, none longer than GROUP_LONGEST_S."""
    groups = []
    for index, word in enumerate(words):
        if groups and (float(word['start']) - float(words[groups[-1][-1]]['end']) < GROUP_GAP_S
                       and float(word['end']) - float(words[groups[-1][0]]['start']) <= GROUP_LONGEST_S):
            groups[-1].append(index)
        else:
            groups.append([index])
    return groups


def merge_nearest(vectors, count):
    """Average-linkage clustering by cosine similarity down to `count` clusters: a label for each vector."""
    similar = vectors @ vectors.T
    np.fill_diagonal(similar, -np.inf)
    sizes = np.ones(len(vectors))
    labels = np.arange(len(vectors))
    for _ in range(len(vectors) - count):
        first, second = np.unravel_index(np.argmax(similar), similar.shape)
        merged = (similar[first] * sizes[first] + similar[second] * sizes[second]) / (sizes[first] + sizes[second])
        similar[first], similar[:, first] = merged, merged
        similar[first, first] = -np.inf
        similar[second], similar[:, second] = -np.inf, -np.inf
        sizes[first] += sizes[second]
        labels[labels == second] = first
    return labels


def speaker_centres(vectors, count):
    """One centre per speaker: clusters merged bottom-up, then settled by a few rounds of nearest-centre assignment."""
    labels = merge_nearest(vectors, count)
    centres = np.stack([vectors[labels == label].mean(0) for label in sorted(set(labels))])
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    for _ in range(5):
        nearest = (vectors @ centres.T).argmax(1)
        centres = np.stack([vectors[nearest == row].mean(0) if (nearest == row).any() else centres[row]
                            for row in range(count)])
        centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    return centres


def label_shared(words, samples, embed, count, margin=SHARED_MARGIN):
    """Label words in place from one track, keeping labels a person gave. `samples` is the track at SHARED_RATE on the
    words' clock; `embed` turns samples into a vector. Returns the counts."""
    groups = word_groups(words)
    rows = []
    for group in groups:
        low, high = float(words[group[0]]['start']), float(words[group[-1]]['end'])
        if high - low < GROUP_SHORTEST_S:
            continue
        piece = samples[int(low * SHARED_RATE):int(high * SHARED_RATE)]
        if len(piece) < GROUP_SHORTEST_S * SHARED_RATE or not piece.any():
            continue
        vector = embed(piece)
        rows.append((group, high - low, vector / (np.linalg.norm(vector) + 1e-12)))
    if len(rows) < count:
        raise ValueError(f'only {len(rows)} stretches of talk are long enough to compare, for {count} speakers')
    vectors = np.stack([row[2] for row in rows])
    long_enough = [index for index, row in enumerate(rows) if row[1] >= FIT_SHORTEST_S]
    if len(long_enough) < count:
        long_enough = list(range(len(rows)))
    if len(long_enough) > FIT_MOST:
        long_enough = [long_enough[index * len(long_enough) // FIT_MOST] for index in range(FIT_MOST)]
    centres = speaker_centres(vectors[long_enough], count)
    similar = vectors @ centres.T
    order = np.sort(similar, axis=1)
    sure = order[:, -1] - order[:, -2] >= margin
    nearest = similar.argmax(1)
    names = {}
    labels = {}
    for (group, _, _), speaker, clear in zip(rows, nearest, sure):
        if clear:
            names.setdefault(int(speaker), f'Speaker {len(names) + 1}')
            for index in group:
                labels[index] = names[int(speaker)]
    counts = {name: 0 for name in names.values()}
    unlabelled = kept = 0
    for index, word in enumerate(words):
        if word.get('speaker_by') == 'person':
            kept += 1
            continue
        word['speaker'] = labels.get(index)
        word.pop('speaker_by', None)
        if word['speaker'] is None:
            unlabelled += 1
        else:
            word['speaker_by'] = 'shared-track'
            counts[word['speaker']] += 1
    return {'labelled': counts, 'unlabelled': unlabelled, 'kept_from_a_person': kept}


def label_from_shared(root, alias, count, download=False, margin=SHARED_MARGIN):
    """map.py speakers --shared: label a transcript from the one track it was made from."""
    root = Path(root).resolve()
    sources = registered(root)
    if alias not in sources:
        raise ValueError(f'unknown alias: {alias}')
    if not count or count < 2:
        raise ValueError('--shared needs --speakers N, how many people speak: it cannot count them')
    source = sources[alias]
    path = root / 'map' / alias / 'words.json'
    if not path.is_file():
        raise ValueError(f'{alias} has no words.json; map or import its transcript first')
    embed = VoiceModel(shared_model(download))
    media = source_path(root, source)
    length = float(source.get('duration_s') or 0)
    command = transcribe.audio_window_command(media, (source.get('audio') or {}).get('index'), 0.0, length,
                                              rate=SHARED_RATE, sample_format='s16le', pad=False)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True)
    if result.returncode:
        raise ValueError(f'{media}: sound will not decode')
    samples = np.frombuffer(result.stdout, dtype=np.int16)
    with project.file_lock(path):
        data = project.load_json(path, None)
        if not isinstance(data, dict) or not isinstance(data.get('words'), list):
            raise ValueError(f'{path}: not a readable transcript')
        state, reason = project.transcript_state(source, data)
        if state == 'stale':
            raise ValueError(f'{alias} transcript is stale: {reason}; retranscribe or confirm it first')
        counts = label_shared(data['words'], samples, embed, count, margin)
        data['speaker_labels'] = {
            'method': 'shared-track', 'draft': True, 'at': project.now(), 'speakers': count, 'margin': margin,
            'model': {'name': 'SpeechBrain ECAPA-TDNN, ONNX conversion', 'revision': SHARED_REVISION,
                      'sha256': SHARED_FILES['ecapa-speaker-v1.onnx'], 'licence': 'Apache-2.0'},
            'note': 'Drafts until a person reads them: voices compared on one track, not an identification.', **counts}
        project.save_json(path, data)
    return counts


def parse_pairs(rows, what):
    """{left: right} from NAME=VALUE arguments."""
    pairs = {}
    for row in rows or []:
        left, separator, right = str(row).partition('=')
        if not separator or not left.strip() or not right.strip():
            raise ValueError(f'{what} takes NAME=VALUE, for example {what} mic_01=Ana; found {row!r}')
        pairs[left.strip()] = right.strip()
    return pairs


def write_json_report(path, record):
    """--json: the saved record as a separate report."""
    Path(path).write_text(json.dumps(record, indent=1), encoding='utf-8')


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
