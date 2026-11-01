#!/usr/bin/env python3
"""Locate where the picture changed between two renders of a film (revision change proof).

Computes per-frame PSNR between NEW and BASELINE with ffmpeg and lists the frame ranges that
fall well below the film's own typical value. Use it after a requested change to confirm the
change landed where intended and nothing else moved.

  python compare_versions.py renders/v15.mp4 renders/v14.mp4
  python compare_versions.py v15.mp4 v14.mp4 --expect 19.0-21.5 --json qa/change.json
  python compare_versions.py v15.mp4 v14.mp4 --offset-frames 12   # v15 has 12 extra frames at the start
  python compare_versions.py v15.mp4 v14.mp4 --offset-frames 18 --offset-at 10.1   # 18 frames added at 10.1 s
  python compare_versions.py v15.mp4 v14.mp4 --offset-frames -6 --offset-at 4.5    # 6 frames removed at 4.5 s

Two renders of the same source are rarely bit-identical after a lossy encode, so "unchanged"
means "within this pipeline's normal range" (one HTML-render pipeline measured about 42-45 dB on
unchanged windows; establish yours). PSNR averages the whole frame: a small text change can move
it only a little, so inspect the changed moment and every important text at full size as well. To say where to
look, each changed range names the cell of a 4x4 grid that changed most in its worst frame (with that cell's own
PSNR, which a small change moves far more than the whole frame's) and the box, in NEW's pixels, around the parts of
the frame that differ by 4 grey levels or more on average (changed_runs[].region in --json; the first 20 ranges).
The box spans every changed part, so two separate changes give one box around both.
Frames are paired by index, whatever each file's own timing; an inserted or removed frame shifts
everything after it. --offset-frames N with --offset-at SECONDS says where: N frames were added to NEW
(positive) or removed from it (negative) at that time, given in NEW's seconds (the same as the
baseline's before the change). Frames before that point pair directly and frames after it pair
shifted by N; the added frames, or the point where frames were removed, are reported as a change
(pass it with --expect when intended). The time need not be frame-exact: within a second of it the
point moves to the frame where small grey thumbnails of the two renders match best on both sides
(encoder ripple is tolerated; frames that differ are not), and the output says when it moved, so
check that it landed where the change was made. Without --offset-at the offset applies at the start, as
before: the first N frames of NEW (or of BASELINE when negative) are dropped unreported. Reported
times are NEW's own presentation times. When one render has more frames than the other after any
offset, the frames without a counterpart are reported as a change at the end, never as identical.
For the strongest change proof when the pipeline can re-render, compare lossless intermediates
(or renders made with -qp 0) with --lossless-proof. This flag asserts that both inputs are
lossless; it does not verify their provenance. Native decoded frame hashes give exact ranges.
Needs FFmpeg and ffprobe. Exit code 0 when changes fall only inside --expect ranges, 1 when a change is found
outside them, 2 on error.
"""

import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from fractions import Fraction

_project_spec = importlib.util.spec_from_file_location(
    'lf_project', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py'))
project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(project)


def find_tool(name, explicit=None):
    """Find an explicitly named tool, environment override or PATH executable."""
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


PTS = re.compile(r'pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')
# Two thumbnails count as the same picture when their grey levels differ by at most this much on average: encoder
# ripple around an edit (about 45 dB PSNR on a teaser's previews) stays near 1 level, a different frame far above it.
SAME_THUMB_LEVELS = 3.0
# Where a changed run changed most: its worst frame pair is read in grey at REGION_WIDTH pixels wide, named by the
# cell of a 4x4 grid that changed most, and boxed by the cells of a finer 32-wide grid whose mean difference is at
# least BOX_LEVELS grey levels (encoder ripple between lossy renders stays near 1-2 levels).
REGION_WIDTH = 320
BOX_LEVELS = 4.0
ROW_NAMES = ('top', 'upper middle', 'lower middle', 'bottom')
COLUMN_NAMES = ('left', 'centre-left', 'centre-right', 'right')


def stream_info(ffprobe, path):
    """(width, height, declared frame rate); raises RuntimeError when unreadable."""
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,avg_frame_rate', '-of', 'json', path], capture_output=True, text=True)
    streams = json.loads(r.stdout or '{}').get('streams') if r.returncode == 0 else None
    if not streams:
        raise RuntimeError(f'cannot read {path}: ' + (r.stderr.strip().splitlines() or ['no video stream'])[-1])
    s = streams[0]
    return int(s['width']), int(s['height']), Fraction(s['avg_frame_rate'])


def passthrough(ffmpeg):
    """Frame-exact output: -fps_mode passthrough (FFmpeg 5.1 and later), -vsync passthrough before it."""
    try:
        head = subprocess.run([ffmpeg, '-hide_banner', '-version'], capture_output=True, text=True).stdout
    except OSError:
        head = ''
    m = re.search(r'version n?(\d+)\.(\d+)', head)
    old = m is not None and (int(m.group(1)), int(m.group(2))) < (5, 1)
    return ['-vsync' if old else '-fps_mode', 'passthrough']


def frame_times(ffmpeg, path, thumbnails=False):
    """Every decoded frame's time on the film clock, from a small fast decode, and with `thumbnails` each frame's
    32-pixel-wide grey thumbnail as bytes (None when they cannot be split per frame); raises RuntimeError when
    unreadable."""
    chain, output = ('scale=32:-2,showinfo,format=gray', 'rawvideo') if thumbnails else ('scale=32:-2,showinfo', 'null')
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', path, '-map', '0:v:0',
                        '-vf', chain, *passthrough(ffmpeg), '-f', output, '-'], capture_output=True)
    log = r.stderr.decode('utf-8', 'replace')
    pts = [float(m.group(1)) for line in log.splitlines() if 'showinfo' in line
           for m in [PTS.search(line)] if m]
    if r.returncode or not pts:
        raise RuntimeError(f'cannot decode {path}: ' + (log.strip().splitlines() or ['?'])[-1])
    size = len(r.stdout) // len(pts)
    if not thumbnails or not size or size * len(pts) != len(r.stdout):
        return pts, [None] * len(pts)
    return pts, [r.stdout[i * size:(i + 1) * size] for i in range(len(pts))]


def parse_ranges(text):
    """'19-21.5,30-31' -> [(19.0, 21.5), (30.0, 31.0)]; raises ValueError naming the bad part."""
    out = []
    for part in (text or '').split(','):
        if part.strip():
            m = re.fullmatch(r'\s*(\d+(?:\.\d*)?)\s*-\s*(\d+(?:\.\d*)?)\s*', part)
            if not m or float(m.group(1)) > float(m.group(2)):
                raise ValueError(f'{part.strip()!r} is not a range START-END in seconds, e.g. 19-21.5')
            out.append((float(m.group(1)), float(m.group(2))))
    return out




def pixel_format(ffprobe, path):
    """Read the decoded pixel format for an exact comparison."""
    cmd = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=pix_fmt', '-of', 'json', path]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    streams = json.loads(result.stdout or '{}').get('streams', []) if result.returncode == 0 else []
    if not streams or not streams[0].get('pix_fmt'):
        raise RuntimeError('cannot read native decoded pixel format')
    return streams[0]['pix_fmt']

def frame_hashes(ffmpeg, path):
    """Return native decoded frame size and hash without converting the pixel format."""
    cmd = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', path, '-map', '0:v:0',
           *passthrough(ffmpeg), '-f', 'framemd5', '-']
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError('native frame hashing failed: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
    headers = tuple(line for line in r.stdout.splitlines() if line.startswith(('#format:', '#dimensions:', '#sar:')))
    return [(headers, tuple(line.split(',')[-2:])) for line in r.stdout.splitlines()
            if line and not line.startswith('#')]


def frame_ranges(exact, target, frame_of, times):
    """Group matching pairs into inclusive NEW frame and presentation-time ranges, split where an offset skips
    frames; frame_of maps a pair index to NEW's frame index."""
    runs = []
    i = 0
    while i < len(exact):
        if exact[i] != target:
            i += 1
            continue
        end = i + 1
        while end < len(exact) and exact[end] == target and frame_of(end) == frame_of(end - 1) + 1:
            end += 1
        runs.append({'start_frame': frame_of(i), 'end_frame': frame_of(end - 1),
                     'start_s': times[frame_of(i)], 'end_s': times[frame_of(end - 1)]})
        i = end
    return runs


def offset_index(times, at):
    """The frame whose presentation time is nearest a time in seconds (ties go to the later frame)."""
    return min(range(len(times)), key=lambda i: (abs(times[i] - at), -i))


def snap_offset(new_thumbs, base_thumbs, stated, skip_new, skip_base, window):
    """The offset frame within `window` frames of the stated one where the most thumbnail pairs show the same
    picture on both sides of it; the stated frame unless another does strictly better (ties keep the nearest)."""
    last = min(len(new_thumbs) - skip_new, len(base_thumbs) - skip_base)
    known = {}

    def same(i, j):
        if (i, j) not in known:
            first, second = new_thumbs[i], base_thumbs[j]
            known[i, j] = (first is not None and second is not None and len(first) == len(second)
                           and sum(abs(x - y) for x, y in zip(first, second)) <= SAME_THUMB_LEVELS * len(first))
        return known[i, j]

    def score(k):
        before = sum(same(i, i) for i in range(max(0, k - window), k))
        after = sum(same(i + skip_new, i + skip_base) for i in range(k, min(k + window, last)))
        return before + after

    best = max(range(max(0, stated - window), min(stated + window, last) + 1),
               key=lambda k: (score(k), -abs(k - stated)))
    return best if score(best) > score(stated) else stated


def kept_frames(skip):
    """FFmpeg select filter keeping every frame except `count` frames from frame `start`, or '' for none."""
    start, count = skip
    if not count:
        return ''
    if start == 0:
        return f'select=gte(n\\,{count}),'
    return f'select=lt(n\\,{start})+gte(n\\,{start + count}),'


def grey_frame(ffmpeg, path, index, width, height):
    """One decoded frame (by index) in grey at width x height, as bytes; None when it cannot be read."""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', path, '-map', '0:v:0', '-vf',
                        f'select=eq(n\\,{index}),scale={width}:{height}:flags=area,format=gray',
                        *passthrough(ffmpeg), '-frames:v', '1', '-f', 'rawvideo', '-'], capture_output=True)
    return r.stdout if r.returncode == 0 and len(r.stdout) == width * height else None


def cell_differences(first, second, width, height, columns, rows):
    """Mean absolute grey difference and mean squared difference of each cell of a columns x rows grid."""
    cells = []
    for row in range(rows):
        top, bottom = row * height // rows, (row + 1) * height // rows
        for column in range(columns):
            left, right = column * width // columns, (column + 1) * width // columns
            total = squares = 0
            for y in range(top, bottom):
                start = y * width
                for x in range(start + left, start + right):
                    difference = first[x] - second[x]
                    total += abs(difference)
                    squares += difference * difference
            count = max(1, (bottom - top) * (right - left))
            cells.append((row, column, total / count, squares / count))
    return cells


def change_region(ffmpeg, new, baseline, new_index, base_index, size):
    """Where in the frame one changed pair differs most: the 4x4 cell that changed most (its name, PSNR and mean
    difference) and the box around every finer cell that changed, in NEW's pixels; None when unreadable."""
    full_width, full_height = size
    width = min(REGION_WIDTH, full_width)
    height = max(2, round(width * full_height / full_width / 2) * 2)
    first = grey_frame(ffmpeg, new, new_index, width, height)
    second = grey_frame(ffmpeg, baseline, base_index, width, height)
    if first is None or second is None:
        return None
    row, column, mean, squares = max(cell_differences(first, second, width, height, 4, 4), key=lambda c: c[2])
    cell_psnr = 99.0 if squares == 0 else round(10 * math.log10(255 * 255 / squares), 2)
    region = {'cell': f'{ROW_NAMES[row]}, {COLUMN_NAMES[column]}', 'cell_row': row + 1, 'cell_column': column + 1,
              'cell_psnr_db': cell_psnr, 'cell_mean_levels': round(mean, 1)}
    fine_columns = 32
    fine_rows = max(1, round(fine_columns * height / width))
    changed = [(r, c) for r, c, level, _ in cell_differences(first, second, width, height, fine_columns, fine_rows)
               if level >= BOX_LEVELS]
    if changed:
        low_row, high_row = min(r for r, _ in changed), max(r for r, _ in changed) + 1
        low_col, high_col = min(c for _, c in changed), max(c for _, c in changed) + 1
        x0, x1 = low_col * full_width // fine_columns, high_col * full_width // fine_columns
        y0, y1 = low_row * full_height // fine_rows, high_row * full_height // fine_rows
        region['box'] = [x0, y0, x1 - x0, y1 - y0]
        region['box_share'] = round((x1 - x0) * (y1 - y0) / (full_width * full_height), 3)
    return region


def region_text(region):
    """A run's region for the printed report."""
    if not region:
        return ''
    text = (f"; most changed: {region['cell']} of a 4x4 grid ({region['cell_psnr_db']} dB there, frame at "
            f"{region['at_s']:.3f} s)")
    if 'box' in region:
        x, y, w, h = region['box']
        text += f'; changed area x {x}-{x + w}, y {y}-{y + h} px'
    return text


def pair_frame(skip):
    """Map a compared pair index to the frame index in one input, given the frames skipped in it."""
    start, count = skip
    return lambda i: i if i < start else i + count

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('new')
    p.add_argument('baseline')
    p.add_argument('--drop-db', type=float, default=6.0, help='flag frames this far below the median PSNR')
    p.add_argument('--floor-db', type=float, default=30.0, help='always flag frames below this PSNR')
    p.add_argument('--expect', help='ranges (seconds, in NEW) where a change is intended, e.g. 19-21.5')
    p.add_argument('--offset-frames', type=int, default=0,
                   help='frames NEW gained (positive) or lost (negative); at the start unless --offset-at')
    p.add_argument('--offset-at', type=float, metavar='SECONDS',
                   help="where the frames were added or removed, in NEW's seconds: earlier frames pair directly, "
                        'later ones shifted; the added frames or the removal point are reported as a change')
    p.add_argument('--lossless-proof', action='store_true',
                   help='assert both inputs are lossless and compare exact decoded frames')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    try:
        project.refuse_overwriting_inputs([a.json], [a.new, a.baseline])
    except ValueError as error:
        print(f'compare_versions.py: cannot run: {error}', file=sys.stderr)
        return 2
    try:
        expect = parse_ranges(a.expect)
    except ValueError as e:
        p.error(f'--expect: {e}')
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)', file=sys.stderr)
        return 2
    try:
        nw, nh, nfps = stream_info(ffprobe, a.new)
        bw, bh, bfps = stream_info(ffprobe, a.baseline)
        new_times, new_thumbs = frame_times(ffmpeg, a.new, a.offset_at is not None)
        base_times, base_thumbs = frame_times(ffmpeg, a.baseline, a.offset_at is not None)
    except RuntimeError as e:
        print(f'compare_versions.py: {e}', file=sys.stderr)
        return 2
    if (nw, nh) != (bw, bh):
        print(f'sizes differ ({nw}x{nh} vs {bw}x{bh}); compare renditions of the same size', file=sys.stderr)
        return 2
    if nfps != bfps:
        print(f'warning: frame rates differ ({nfps} vs {bfps}); frames are compared by index', file=sys.stderr)
    skip_new, skip_base = max(a.offset_frames, 0), max(-a.offset_frames, 0)
    at_frame = stated_frame = 0
    if a.offset_at is not None:
        if not a.offset_frames or a.offset_at < 0:
            print('compare_versions.py: --offset-at needs a non-zero --offset-frames and a time of 0 or more',
                  file=sys.stderr)
            return 2
        stated_frame = offset_index(new_times, a.offset_at)
        if stated_frame + skip_new > len(new_times) or stated_frame + skip_base > len(base_times):
            print(f'compare_versions.py: --offset-frames {a.offset_frames} at frame {stated_frame} '
                  f'({new_times[stated_frame]:.3f} s) runs past the end of a render', file=sys.stderr)
            return 2
        # A stated time is rarely frame-exact: move to the frame within a second where the thumbnails match on
        # both sides, as a person aligning frames by hand would.
        window = max(1, int(round(float(nfps)))) if nfps else 24
        at_frame = snap_offset(new_thumbs, base_thumbs, stated_frame, skip_new, skip_base, window)
    new_skip, base_skip = (at_frame, skip_new), (at_frame, skip_base)
    new_frame, base_frame = pair_frame(new_skip), pair_frame(base_skip)
    new_left, base_left = len(new_times) - skip_new, len(base_times) - skip_base
    if new_left <= 0 or base_left <= 0:
        print('compare_versions.py: --offset-frames leaves no frames to compare', file=sys.stderr)
        return 2
    # Both inputs get the same frame-index clock, so frame i of NEW meets frame i of BASELINE whatever the files'
    # own timing; shortest=1 stops at the shorter render instead of repeating its last frame.
    index_clock = 'setpts=N/(30*TB)'
    graph = (f'[0:v]{kept_frames(new_skip)}{index_clock},format=yuv420p[n];'
             f'[1:v]{kept_frames(base_skip)}{index_clock},format=yuv420p[b];'
             f'[n][b]psnr=stats_file=psnr.log:shortest=1')
    # Run inside a temporary folder with a relative stats_file name: a Windows drive-letter path's
    # colon is read as a filter-option separator ("Error parsing filterchain").
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', os.path.abspath(a.new),
                            '-i', os.path.abspath(a.baseline), '-lavfi', graph, '-f', 'null', '-'],
                           cwd=tmp, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            print('ffmpeg failed: ' + (r.stderr.strip().splitlines() or ['?'])[-1], file=sys.stderr)
            return 2
        with open(os.path.join(tmp, 'psnr.log'), encoding='utf-8') as fh:
            lines = fh.read().splitlines()
    values = []
    exact = []
    for line in lines:
        number = re.search(r'(?:^|\s)n:(\d+)', line)
        measurement = re.search(r'psnr_avg:(\S+)', line)
        if not number or not measurement or int(number.group(1)) - 1 != len(values):
            print('compare_versions.py: invalid or non-sequential PSNR frame log', file=sys.stderr)
            return 2
        value = measurement.group(1)
        exact.append(value == 'inf')
        values.append(99.0 if value == 'inf' else float(value))
    pairs = min(new_left, base_left)
    if len(values) != pairs:
        print(f'compare_versions.py: compared {len(values)} frame pairs but expected {pairs}; '
              'the change proof is incomplete', file=sys.stderr)
        return 2
    finite = [v for v, same in zip(values, exact) if not same]
    median = statistics.median(values)
    outside = [v for i, (v, same) in enumerate(zip(values, exact)) if not same
               and not any(lo - 1e-6 <= new_times[new_frame(i)] <= hi + 1e-6 for lo, hi in expect)]
    if sum(exact) > len(exact) / 2 and finite:
        candidate = min(55.0, statistics.median(outside) - a.drop_db) if outside else 55.0
        threshold = max(a.floor_db, candidate)
        method = 'identical majority: outside-expected non-identical median minus drop, capped at 55 dB'
    else:
        threshold = max(min(median - a.drop_db, 99.0), a.floor_db) if finite else a.floor_db
        method = 'overall median minus drop with floor' if finite else 'all compared frames identical: floor'
    psnr_exact = list(exact)
    if a.lossless_proof:
        try:
            if pixel_format(ffprobe, a.new) != pixel_format(ffprobe, a.baseline):
                raise RuntimeError('native decoded pixel formats differ; exact comparison unavailable')
            new_hashes = frame_hashes(ffmpeg, a.new)
            base_hashes = frame_hashes(ffmpeg, a.baseline)
        except RuntimeError as e:
            print(f'compare_versions.py: {e}', file=sys.stderr)
            return 2
        if len(new_hashes) != len(new_times) or len(base_hashes) != len(base_times):
            print('compare_versions.py: incomplete native frame hashes', file=sys.stderr)
            return 2
        if new_hashes[0][0] != base_hashes[0][0]:
            print('compare_versions.py: native decoded formats differ; exact comparison unavailable', file=sys.stderr)
            return 2
        exact = [new_hashes[new_frame(i)] == base_hashes[base_frame(i)] for i in range(pairs)]
        method = 'exact native decoded-frame hashes; inputs asserted lossless'


    def at(i):  # NEW's own time for compared pair i
        return new_times[new_frame(i)]

    def changed(i):  # whether compared pair i counts as changed
        return (not exact[i]) if a.lossless_proof else (values[i] < threshold)

    runs, i = [], 0
    while i < len(values):
        if changed(i):
            j = i + 1
            while j < len(values) and changed(j) and new_frame(j) == new_frame(j - 1) + 1:
                j += 1
            start, end = at(i), at(j - 1)
            inside = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in expect)
            runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': j - i,
                         'min_psnr_db': round(min(values[i:j]), 2), 'expected': inside,
                         '_worst': min(range(i, j), key=lambda k: values[k])})
            i = j
        else:
            i += 1
    for row in runs[:20]:
        worst = row.pop('_worst')
        region = change_region(ffmpeg, a.new, a.baseline, new_frame(worst), base_frame(worst), (nw, nh))
        if region:
            row['region'] = dict(region, at_s=round(at(worst), 3))
    for row in runs:
        row.pop('_worst', None)
    frame_s = new_times[-1] - new_times[-2] if len(new_times) > 1 else 1 / float(nfps)
    if a.offset_at is not None:
        # The offset itself is a change: NEW's added frames, or the point where the baseline's frames were cut.
        if skip_new:
            start, end = new_times[at_frame], new_times[at_frame + skip_new - 1]
            what = f'{skip_new} frames added to NEW'
        else:
            start = end = new_times[at_frame]
            what = (f'{skip_base} baseline frames removed here (baseline {base_times[at_frame]:.3f}-'
                    f'{base_times[at_frame + skip_base - 1]:.3f} s)')
        inside = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in expect)
        runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': skip_new or skip_base,
                     'min_psnr_db': None, 'expected': inside, 'unmatched': what})
        runs.sort(key=lambda row: row['start_s'])
    # Frames with no counterpart: a missing or added tail is a change, whatever the PSNR of the pairs.
    extra = new_left - base_left
    if extra > 0:
        start, end = at(pairs), new_times[-1]
    elif extra < 0:  # where NEW ends; the baseline's remaining frames are timed on its own clock
        start = new_times[-1] + frame_s
        end = start + (base_times[-1] - base_times[base_frame(pairs - 1)])
    if extra:
        inside = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in expect)
        runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': abs(extra),
                     'min_psnr_db': None, 'expected': inside,
                     'unmatched': ('NEW has frames the baseline lacks' if extra > 0
                                   else 'the baseline continues after NEW ends')})
    unexpected = [r for r in runs if not r['expected']]
    identical = sum(exact)
    result = {'new': a.new, 'baseline': a.baseline, 'frames_new': len(new_times), 'frames_baseline': len(base_times),
              'frames_compared': len(values),
              'identical_frames': identical, 'median_psnr_db': round(median, 2),
              'min_psnr_db': round(min(values), 2), 'threshold_db': round(threshold, 2), 'changed_runs': runs,
              'verdict': (f'{len(unexpected)} change(s) outside the expected ranges' if unexpected
                          else 'changes only where expected' if runs else 'no change above the threshold'),
              'limit': 'Locates differences; does not prove a small change is absent or that meaning survived.'}
    result['threshold_method'] = method
    if a.offset_at is not None:
        result['offset'] = {'frames': a.offset_frames, 'at_s': a.offset_at, 'stated_frame': stated_frame,
                            'at_frame': at_frame, 'at_frame_s': round(new_times[at_frame], 3),
                            'snapped': at_frame != stated_frame}
    result['per_frame_psnr'] = [{'frame': new_frame(i), 'pts': new_times[new_frame(i)],
                                 'psnr': 'inf' if psnr_exact[i] else values[i]}
                                for i in range(pairs)]
    if a.lossless_proof:
        result['lossless_proof'] = {'assertion': 'both inputs are lossless',
                                    'identical_ranges': frame_ranges(exact, True, new_frame, new_times),
                                    'changed_ranges': frame_ranges(exact, False, new_frame, new_times)}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1)
    print(f"{os.path.basename(a.new)} vs {os.path.basename(a.baseline)}: {len(values)} frames; median "
          f"{result['median_psnr_db']} dB, min {result['min_psnr_db']} dB, {identical} identical; threshold "
          f"{result['threshold_db']} dB")
    print('  threshold method: ' + method)
    if a.offset_at is not None:
        if at_frame != stated_frame:
            print(f'  --offset-at {a.offset_at:g} is nearest frame {stated_frame} ({new_times[stated_frame]:.3f} s); '
                  f'the pictures on both sides match best at frame {at_frame} ({new_times[at_frame]:.3f} s), '
                  'so the offset is placed there')
        print(f"  frames paired directly before NEW frame {at_frame} ({result['offset']['at_frame_s']:.3f} s) "
              f"and shifted by {a.offset_frames} after it")
    if a.lossless_proof:
        print('  exact frame ranges: ' + str(result['lossless_proof']))
    for r in runs:
        what = r['unmatched'] if 'unmatched' in r else f"min {r['min_psnr_db']} dB"
        print(f"  {'expected' if r['expected'] else 'UNEXPECTED'} change {r['start_s']:.3f}-{r['end_s']:.3f} s "
              f"({r['frames']} frames, {what}){region_text(r.get('region'))}")
    print('  ' + result['verdict'])
    return 1 if unexpected else 0


if __name__ == '__main__':
    sys.exit(main())
