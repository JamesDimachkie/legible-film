#!/usr/bin/env python3
"""Conservative screen for flashing (WCAG 2.3.1 general and red flash) in a rendered video.

WCAG 2.3.1 fails content that flashes more than three times in any one second when the flashing
area exceeds the general or red flash thresholds. This script flags intervals to inspect. It is
not a Harding FPA, IRIS or PEAT pass, which some broadcasters and platforms require.

Method. Decode at reduced size and examine overlapping windows one third of the frame wide and
high (WCAG's estimate of a 10-degree field on a desktop display; on a phone the whole video spans
roughly 10 degrees, so these smaller windows are the stricter choice). In each window the 74th and
26th percentiles of relative luminance move only when more than about a quarter of the window
changes together, so small bright objects don't count. Each percentile is tracked with a reversal
(zigzag) threshold:
  - a general-flash transition is a swing of at least 0.10 relative luminance whose darker end is
    below 0.80;
  - a red-flash transition is a swing of at least 20 in the saturated-red amount (R-G-B)*320,
    counted where R/(R+G+B) >= 0.8 (the WCAG 2.0 red-flash formula; WCAG 2.2 keeps the
    "saturated red" ratio).
A flash is a pair of opposing transitions, so a window with more than six transitions inside one
second (more than three flashes) is flagged.

  python flash_scan.py film.mp4
  python flash_scan.py film.mp4 --json qa/flash.json

The golden cases in selftest.py (eleven synthetic clips with known answers) exercise this logic.
Needs numpy and FFmpeg. Exit code 1 when any window is flagged, 2 on error.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit('flash_scan.py needs numpy: pip install numpy')


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def probe(ffprobe, path):
    out = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,avg_frame_rate,r_frame_rate', '-of', 'json', path],
                         capture_output=True, text=True, check=True).stdout
    s = json.loads(out)['streams'][0]
    for key in ('avg_frame_rate', 'r_frame_rate'):
        num, _, den = s.get(key, '0/0').partition('/')
        if float(den or 1) and float(num):
            return int(s['width']), int(s['height']), float(num) / float(den or 1)
    raise SystemExit('could not read the frame rate')


def linear(c8):
    c = c8.astype(np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


class Zig:
    """Swings between confirmed pivots, each at least thr; consecutive swings alternate direction."""

    def __init__(self, thr, darker_below=None):
        self.thr, self.darker_below = thr, darker_below
        self.p = self.e = None
        self.e_t = 0.0
        self.d = 0
        self.ends = []  # end time of each counted transition

    def _count(self, a, b, t):
        if abs(b - a) >= self.thr and (self.darker_below is None or min(a, b) < self.darker_below):
            self.ends.append(t)

    def push(self, t, v):
        if self.p is None:
            self.p = self.e = v
            self.e_t = t
            return
        if self.d == 0:
            if v - self.p >= self.thr:
                self.d, self.e, self.e_t = 1, v, t
            elif self.p - v >= self.thr:
                self.d, self.e, self.e_t = -1, v, t
            return
        if (self.d == 1 and v > self.e) or (self.d == -1 and v < self.e):
            self.e, self.e_t = v, t
        elif abs(self.e - v) >= self.thr:
            self._count(self.p, self.e, self.e_t)
            self.p, self.e, self.e_t, self.d = self.e, v, t, -self.d

    def finish(self):
        if self.d != 0:
            self._count(self.p, self.e, self.e_t)


def busiest_second(ends):
    best, at, j = 0, None, 0
    ends = sorted(ends)
    for i in range(len(ends)):
        while ends[i] - ends[j] >= 1.0:
            j += 1
        if i - j + 1 > best:
            best, at = i - j + 1, round(ends[j], 3)
    return best, at


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('video')
    ap.add_argument('--width', type=int, default=192, help='analysis width in pixels')
    ap.add_argument('--json')
    ap.add_argument('--ffmpeg')
    ap.add_argument('--ffprobe')
    a = ap.parse_args()
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)', file=sys.stderr)
        return 2
    w0, h0, fps = probe(ffprobe, a.video)
    W = a.width - a.width % 2
    H = max(6, int(round(W * h0 / w0 / 2.0)) * 2)
    proc = subprocess.Popen([ffmpeg, '-v', 'error', '-nostdin', '-i', a.video, '-vf', f'scale={W}:{H}:flags=area',
                             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    ww, wh = W // 3, H // 3
    xs = sorted({x for x in range(0, W - ww + 1, max(1, W // 6))} | {W - ww})
    ys = sorted({y for y in range(0, H - wh + 1, max(1, H // 6))} | {H - wh})
    wins = [(x, y) for y in ys for x in xs]
    npx = ww * wh
    k26, k74 = int(0.26 * (npx - 1)), int(0.74 * (npx - 1))
    zig = {(k, s): Zig(0.10, darker_below=0.80) for k in range(len(wins)) for s in ('hi', 'lo')}
    rzig = {k: Zig(20.0) for k in range(len(wins))}
    n, size = 0, W * H * 3
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        lin = linear(np.frombuffer(buf, np.uint8).reshape(H, W, 3))
        Y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
        s = lin.sum(axis=2) + 1e-9
        red = np.where(lin[..., 0] / s >= 0.8, np.maximum(0.0, (lin[..., 0] - lin[..., 1] - lin[..., 2]) * 320.0), 0.0)
        t = n / fps
        for k, (x, y) in enumerate(wins):
            q = np.partition(Y[y:y + wh, x:x + ww].ravel(), [k26, k74])
            zig[(k, 'hi')].push(t, float(q[k74]))
            zig[(k, 'lo')].push(t, float(q[k26]))
            rzig[k].push(t, float(np.partition(red[y:y + wh, x:x + ww].ravel(), k74)[k74]))
        n += 1
    proc.wait()
    if proc.returncode or n == 0:
        print('ffmpeg could not decode the video', file=sys.stderr)
        return 2
    rows, flagged = [], []
    for k, (x, y) in enumerate(wins):
        for z in (zig[(k, 'hi')], zig[(k, 'lo')], rzig[k]):
            z.finish()
        g = max((busiest_second(zig[(k, s)].ends) for s in ('hi', 'lo')), key=lambda b: b[0])
        r = busiest_second(rzig[k].ends)
        row = {'window': [x, y, ww, wh], 'general_max_per_s': g[0], 'general_at_s': g[1],
               'red_max_per_s': r[0], 'red_at_s': r[1]}
        rows.append(row)
        if g[0] > 6 or r[0] > 6:
            flagged.append(row)
    gb = max(rows, key=lambda r: r['general_max_per_s'])
    rb = max(rows, key=lambda r: r['red_max_per_s'])
    res = {'video': a.video, 'frames': n, 'fps': fps, 'scan_size': [W, H], 'windows': len(wins),
           'busiest_general': {'transitions_in_1s': gb['general_max_per_s'], 'at_s': gb['general_at_s'], 'window': gb['window']},
           'busiest_red': {'transitions_in_1s': rb['red_max_per_s'], 'at_s': rb['red_at_s'], 'window': rb['window']},
           'flagged': flagged, 'verdict': 'FLAGGED' if flagged else 'no candidate flash sequences',
           'limit': 'Screening only; not a Harding FPA, IRIS or PEAT certification.'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, indent=1)
    g, r = res['busiest_general'], res['busiest_red']
    print(f"{os.path.basename(a.video)}: {n} frames at {fps:g} fps; busiest second: general {g['transitions_in_1s']} "
          f"transitions (at {g['at_s']} s), red {r['transitions_in_1s']} (at {r['at_s']} s); {res['verdict']}")
    return 1 if flagged else 0


if __name__ == '__main__':
    sys.exit(main())
