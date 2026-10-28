#!/usr/bin/env python3
"""Find runs of near-empty frames (little edge detail) in a rendered film.

Catches what ffmpeg's blackdetect misses: flat colour fields, a frame whose only content is a
thin line, a scene that failed to draw. Each frame is scaled to 320x180 grey; its detail is the
mean absolute horizontal plus vertical gradient. Frames below --relative x the film's median
detail (default 0.35) are near-empty; runs of at least --min-frames are listed with their times.

  python blank_scan.py film.mp4
  python blank_scan.py film.mp4 --min-frames 2 --ignore 0-0.5,31.8-32 --json qa/blank.json

Designed fades, breaths and wipes will appear: declare them with --ignore (seconds) and inspect
every other run at full size against the last approved export. The measure is brightness
structure after downscaling, not intent: a near-threshold fade can flip between two encodes of
the same picture. Needs numpy and FFmpeg. Exit code 1 when a run outside --ignore is found.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit('blank_scan.py needs numpy: pip install numpy')

W, H = 320, 180


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def parse_ranges(text):
    out = []
    for part in (text or '').split(','):
        if part.strip():
            a, _, b = part.partition('-')
            out.append((float(a), float(b)))
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video')
    p.add_argument('--min-frames', type=int, default=4)
    p.add_argument('--relative', type=float, default=0.35, help='threshold as a fraction of the median detail')
    p.add_argument('--ignore', help='designed low-detail ranges in seconds, e.g. 0-0.5,12.1-12.4')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        sys.exit('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)')
    rate = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                           'stream=avg_frame_rate', '-of', 'csv=p=0', a.video],
                          capture_output=True, text=True, check=True).stdout.strip()
    fps = float(Fraction(rate))
    proc = subprocess.Popen([ffmpeg, '-v', 'error', '-nostdin', '-i', a.video, '-vf',
                             f'scale={W}:{H}:flags=area,format=gray', '-f', 'rawvideo', 'pipe:1'],
                            stdout=subprocess.PIPE)
    detail = []
    size = W * H
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(H, W).astype(np.float32)
        detail.append(float(np.abs(np.diff(f, axis=1)).mean() + np.abs(np.diff(f, axis=0)).mean()))
    proc.wait()
    if proc.returncode or not detail:
        sys.exit('ffmpeg could not decode the video')
    d = np.array(detail)
    median = float(np.median(d))
    threshold = median * a.relative
    ignore = parse_ranges(a.ignore)
    runs, i = [], 0
    while i < len(d):
        if d[i] < threshold:
            j = i
            while j < len(d) and d[j] < threshold:
                j += 1
            if j - i >= a.min_frames:
                start, end = i / fps, (j - 1) / fps
                declared = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in ignore)
                runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': j - i,
                             'min_detail': round(float(d[i:j].min()), 3), 'declared': declared})
            i = j
        else:
            i += 1
    flagged = [r for r in runs if not r['declared']]
    result = {'video': a.video, 'frames': len(d), 'fps': fps, 'median_detail': round(median, 3),
              'threshold': round(threshold, 3), 'runs': runs,
              'verdict': f'{len(flagged)} undeclared near-empty run(s) to inspect' if flagged else 'none outside declared ranges'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1)
    print(f'{os.path.basename(a.video)}: {len(d)} frames at {fps:g} fps; median detail {median:.2f}; '
          f'threshold {threshold:.2f}')
    for r in runs:
        tag = 'declared' if r['declared'] else 'INSPECT'
        print(f"  {tag:8s} near-empty {r['start_s']:7.3f}-{r['end_s']:7.3f} s ({r['frames']} frames, "
              f"min detail {r['min_detail']})")
    if not runs:
        print(f'  no near-empty runs of {a.min_frames} frames or more')
    return 1 if flagged else 0


if __name__ == '__main__':
    sys.exit(main())
