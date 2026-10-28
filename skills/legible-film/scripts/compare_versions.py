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
Frames are aligned by index; an inserted or removed frame shifts everything after it (use
--offset-frames or compare windows separately). Needs FFmpeg. Exit code 1 when a change is found
outside --expect ranges, 2 on error.
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
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def stream_info(ffprobe, path):
    out = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,avg_frame_rate', '-of', 'json', path],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    return int(s['width']), int(s['height']), Fraction(s['avg_frame_rate'])


def parse_ranges(text):
    out = []
    for part in (text or '').split(','):
        if part.strip():
            a, _, b = part.partition('-')
            out.append((float(a), float(b)))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('new')
    p.add_argument('baseline')
    p.add_argument('--drop-db', type=float, default=6.0, help='flag frames this far below the median PSNR')
    p.add_argument('--floor-db', type=float, default=30.0, help='always flag frames below this PSNR')
    p.add_argument('--expect', help='ranges (seconds, in NEW) where a change is intended, e.g. 19-21.5')
    p.add_argument('--offset-frames', type=int, default=0,
                   help='positive: drop this many frames from the start of NEW; negative: from BASELINE')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)', file=sys.stderr)
        return 2
    nw, nh, nfps = stream_info(ffprobe, a.new)
    bw, bh, bfps = stream_info(ffprobe, a.baseline)
    if (nw, nh) != (bw, bh):
        print(f'sizes differ ({nw}x{nh} vs {bw}x{bh}); compare renditions of the same size', file=sys.stderr)
        return 2
    if nfps != bfps:
        print(f'warning: frame rates differ ({nfps} vs {bfps}); frames are compared by index', file=sys.stderr)
    trim_new = f'trim=start_frame={a.offset_frames},setpts=PTS-STARTPTS,' if a.offset_frames > 0 else ''
    trim_base = f'trim=start_frame={-a.offset_frames},setpts=PTS-STARTPTS,' if a.offset_frames < 0 else ''
    graph = f'[0:v]{trim_new}format=yuv420p[n];[1:v]{trim_base}format=yuv420p[b];[n][b]psnr=stats_file=psnr.log'
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
    for line in lines:
        m = re.search(r'psnr_avg:(\S+)', line)
        if m:
            v = m.group(1)
            values.append(99.0 if v == 'inf' else float(v))
    if not values:
        print('no frames were compared', file=sys.stderr)
        return 2
    fps = float(nfps)
    finite = [v for v in values if v < 99.0]
    median = statistics.median(values)
    threshold = max(min(median - a.drop_db, 99.0), a.floor_db) if finite else a.floor_db
    expect = parse_ranges(a.expect)
    offset_t = max(a.offset_frames, 0) / fps
    runs, i = [], 0
    while i < len(values):
        if values[i] < threshold:
            j = i
            while j < len(values) and values[j] < threshold:
                j += 1
            start, end = i / fps + offset_t, (j - 1) / fps + offset_t
            inside = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in expect)
            runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': j - i,
                         'min_psnr_db': round(min(values[i:j]), 2), 'expected': inside})
            i = j
        else:
            i += 1
    unexpected = [r for r in runs if not r['expected']]
    identical = sum(1 for v in values if v >= 99.0)
    result = {'new': a.new, 'baseline': a.baseline, 'frames_compared': len(values),
              'identical_frames': identical, 'median_psnr_db': round(median, 2),
              'min_psnr_db': round(min(values), 2), 'threshold_db': round(threshold, 2), 'changed_runs': runs,
              'verdict': (f'{len(unexpected)} change(s) outside the expected ranges' if unexpected
                          else 'changes only where expected' if runs else 'no change above the threshold'),
              'limit': 'Locates differences; does not prove a small change is absent or that meaning survived.'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1)
    print(f"{os.path.basename(a.new)} vs {os.path.basename(a.baseline)}: {len(values)} frames; median "
          f"{result['median_psnr_db']} dB, min {result['min_psnr_db']} dB, {identical} identical; threshold "
          f"{result['threshold_db']} dB")
    for r in runs:
        print(f"  {'expected' if r['expected'] else 'UNEXPECTED'} change {r['start_s']:.3f}-{r['end_s']:.3f} s "
              f"({r['frames']} frames, min {r['min_psnr_db']} dB)")
    print('  ' + result['verdict'])
    return 1 if unexpected else 0


if __name__ == '__main__':
    sys.exit(main())
