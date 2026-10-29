#!/usr/bin/env python3
"""Locate where the picture changed between two renders of a film (revision change proof).

Computes per-frame PSNR between NEW and BASELINE with ffmpeg and lists the frame ranges that
fall well below the film's own typical value. Use it after a requested change to confirm the
change landed where intended and nothing else moved.

  python compare_versions.py renders/v15.mp4 renders/v14.mp4
  python compare_versions.py v15.mp4 v14.mp4 --expect 19.0-21.5 --json qa/change.json
  python compare_versions.py v15.mp4 v14.mp4 --offset-frames 12   # v15 has 12 extra frames at the start

Two renders of the same source are rarely bit-identical after a lossy encode, so "unchanged"
means "within this pipeline's normal range" (one HTML-render pipeline measured about 42-45 dB on
unchanged windows; establish yours). PSNR averages the whole frame: a small text change can move
it only a little, so inspect the changed moment and every important text at full size as well.
Frames are paired by index, whatever each file's own timing; an inserted or removed frame shifts
everything after it (use --offset-frames or compare windows separately). Reported times are NEW's
own presentation times. When one render has more frames than the other,
the frames without a counterpart are reported as a change at the end, never as identical.
For the strongest change proof when the pipeline can re-render, compare lossless intermediates
(or renders made with -qp 0) with --lossless-proof. This flag asserts that both inputs are
lossless; it does not verify their provenance. Native decoded frame hashes give exact ranges.
Needs FFmpeg and ffprobe. Exit code 0 when changes fall only inside --expect ranges, 1 when a change is found
outside them, 2 on error.
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
from fractions import Fraction


def find_tool(name, explicit=None):
    """Find an explicitly named tool, environment override or PATH executable."""
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


PTS = re.compile(r'pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')


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


def frame_times(ffmpeg, path):
    """Every decoded frame's time on the film clock, from a small fast decode; raises RuntimeError when unreadable."""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', path, '-map', '0:v:0',
                        '-vf', 'scale=32:-2,showinfo', *passthrough(ffmpeg), '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    pts = [float(m.group(1)) for line in r.stderr.splitlines() if 'showinfo' in line
           for m in [PTS.search(line)] if m]
    if r.returncode or not pts:
        raise RuntimeError(f'cannot decode {path}: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
    return pts


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


def frame_ranges(exact, target, offset, times):
    """Group matching frames into inclusive frame and presentation-time ranges."""
    runs = []
    i = 0
    while i < len(exact):
        if exact[i] != target:
            i += 1
            continue
        end = i + 1
        while end < len(exact) and exact[end] == target:
            end += 1
        runs.append({'start_frame': offset + i, 'end_frame': offset + end - 1,
                     'start_s': times[offset + i], 'end_s': times[offset + end - 1]})
        i = end
    return runs

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('new')
    p.add_argument('baseline')
    p.add_argument('--drop-db', type=float, default=6.0, help='flag frames this far below the median PSNR')
    p.add_argument('--floor-db', type=float, default=30.0, help='always flag frames below this PSNR')
    p.add_argument('--expect', help='ranges (seconds, in NEW) where a change is intended, e.g. 19-21.5')
    p.add_argument('--offset-frames', type=int, default=0,
                   help='positive: drop this many frames from the start of NEW; negative: from BASELINE')
    p.add_argument('--lossless-proof', action='store_true',
                   help='assert both inputs are lossless and compare exact decoded frames')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
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
        new_times = frame_times(ffmpeg, a.new)
        base_times = frame_times(ffmpeg, a.baseline)
    except RuntimeError as e:
        print(f'compare_versions.py: {e}', file=sys.stderr)
        return 2
    if (nw, nh) != (bw, bh):
        print(f'sizes differ ({nw}x{nh} vs {bw}x{bh}); compare renditions of the same size', file=sys.stderr)
        return 2
    if nfps != bfps:
        print(f'warning: frame rates differ ({nfps} vs {bfps}); frames are compared by index', file=sys.stderr)
    skip_new, skip_base = max(a.offset_frames, 0), max(-a.offset_frames, 0)
    new_left, base_left = len(new_times) - skip_new, len(base_times) - skip_base
    if new_left <= 0 or base_left <= 0:
        print('compare_versions.py: --offset-frames leaves no frames to compare', file=sys.stderr)
        return 2
    # Both inputs get the same frame-index clock, so frame i of NEW meets frame i of BASELINE whatever the files'
    # own timing; shortest=1 stops at the shorter render instead of repeating its last frame.
    index_clock = 'setpts=N/(30*TB)'
    trim_new = f'trim=start_frame={skip_new},' if skip_new else ''
    trim_base = f'trim=start_frame={skip_base},' if skip_base else ''
    graph = (f'[0:v]{trim_new}{index_clock},format=yuv420p[n];[1:v]{trim_base}{index_clock},format=yuv420p[b];'
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
               and not any(lo - 1e-6 <= new_times[skip_new + i] <= hi + 1e-6 for lo, hi in expect)]
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
        exact = [new_hashes[skip_new + i] == base_hashes[skip_base + i] for i in range(pairs)]
        method = 'exact native decoded-frame hashes; inputs asserted lossless'


    def at(i):  # NEW's own time for compared pair i
        return new_times[skip_new + i]

    runs, i = [], 0
    while i < len(values):
        if (not exact[i]) if a.lossless_proof else (values[i] < threshold):
            j = i
            while j < len(values) and ((not exact[j]) if a.lossless_proof else (values[j] < threshold)):
                j += 1
            start, end = at(i), at(j - 1)
            inside = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in expect)
            runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': j - i,
                         'min_psnr_db': round(min(values[i:j]), 2), 'expected': inside})
            i = j
        else:
            i += 1
    # Frames with no counterpart: a missing or added tail is a change, whatever the PSNR of the pairs.
    extra = new_left - base_left
    if extra > 0:
        start, end = at(pairs), new_times[-1]
    elif extra < 0:  # where NEW ends; the baseline's remaining frames are timed on its own clock
        start = new_times[-1] + (new_times[-1] - new_times[-2] if len(new_times) > 1 else 1 / float(nfps))
        end = start + (base_times[-1] - base_times[skip_base + pairs - 1])
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
    result['per_frame_psnr'] = [{'frame': skip_new + i, 'pts': new_times[skip_new + i],
                                 'psnr': 'inf' if psnr_exact[i] else values[i]}
                                for i in range(pairs)]
    if a.lossless_proof:
        result['lossless_proof'] = {'assertion': 'both inputs are lossless',
                                    'identical_ranges': frame_ranges(exact, True, skip_new, new_times),
                                    'changed_ranges': frame_ranges(exact, False, skip_new, new_times)}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1)
    print(f"{os.path.basename(a.new)} vs {os.path.basename(a.baseline)}: {len(values)} frames; median "
          f"{result['median_psnr_db']} dB, min {result['min_psnr_db']} dB, {identical} identical; threshold "
          f"{result['threshold_db']} dB")
    print('  threshold method: ' + method)
    if a.lossless_proof:
        print('  exact frame ranges: ' + str(result['lossless_proof']))
    for r in runs:
        what = r['unmatched'] if 'unmatched' in r else f"min {r['min_psnr_db']} dB"
        print(f"  {'expected' if r['expected'] else 'UNEXPECTED'} change {r['start_s']:.3f}-{r['end_s']:.3f} s "
              f"({r['frames']} frames, {what})")
    print('  ' + result['verdict'])
    return 1 if unexpected else 0


if __name__ == '__main__':
    sys.exit(main())
