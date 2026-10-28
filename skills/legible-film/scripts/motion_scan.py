#!/usr/bin/env python3
"""Frame-difference profile of a rendered video: cuts, one-frame intrusions, stutter and loop seams.

For every frame it measures how much the picture changed from the previous frame (mean absolute
difference of 8-bit grey at analysis size). From that profile it lists:
  - cuts: large single steps (check each against the edit you intended);
  - one-frame intrusions ("ghost" frames): a frame that differs from both neighbours while the
    neighbours match each other (a blank, a flash, a mis-rendered or leftover frame);
  - stutter: a repeated frame inside continuous motion (a duplicate where the picture should move);
  - with --loop, the seam: the step from the last frame back to the first, compared with the
    typical step near the ends.

  python motion_scan.py film.mp4
  python motion_scan.py loop.mp4 --loop --json qa/motion.json --csv qa/motion.csv
  python motion_scan.py film.mp4 --ignore 4.0-4.2,12.5-13.0

Thresholds are heuristics on the 0-255 grey scale; tune them on your own renders and declare
designed holds, freezes and flashes with --ignore (seconds). Every flag is a candidate: inspect it
with frame_sheet.py --frames A-B before changing anything. The profile cannot judge whether a move
feels right at speed. Needs numpy and FFmpeg. Exit code 1 when an undeclared intrusion, excess
stutter or a failing loop seam is found.
"""

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit('motion_scan.py needs numpy: pip install numpy')


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
    p.add_argument('--width', type=int, default=320, help='analysis width')
    p.add_argument('--move', type=float, default=0.4, help='a step above this counts as motion')
    p.add_argument('--still', type=float, default=0.02, help='a step below this counts as a repeated frame')
    p.add_argument('--cut', type=float, default=20.0, help='a step above this counts as a cut')
    p.add_argument('--max-stutter', type=float, default=0.01, help='allowed share of repeated frames inside motion')
    p.add_argument('--hold-level', type=float, default=0.1, help='a step below this counts as held')
    p.add_argument('--hold-seconds', type=float, default=1.5, help='report held stretches at least this long')
    p.add_argument('--loop', action='store_true', help='also check the last-to-first seam')
    p.add_argument('--seam-ratio', type=float, default=1.5, help='seam may be this many times the typical end step')
    p.add_argument('--ignore', help='designed ranges in seconds, e.g. 3.9-4.2,10-11')
    p.add_argument('--json')
    p.add_argument('--csv', help='write the per-frame profile')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)', file=sys.stderr)
        return 2
    info = json.loads(subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                      'stream=width,height,avg_frame_rate', '-of', 'json', a.video],
                                     capture_output=True, text=True, check=True).stdout)['streams'][0]
    fps = float(Fraction(info['avg_frame_rate']))
    W = a.width - a.width % 2
    H = max(2, int(round(W * info['height'] / info['width'] / 2.0)) * 2)
    proc = subprocess.Popen([ffmpeg, '-v', 'error', '-nostdin', '-i', a.video, '-vf',
                             f'scale={W}:{H}:flags=area,format=gray', '-f', 'rawvideo', 'pipe:1'],
                            stdout=subprocess.PIPE)
    size = W * H
    first = prev = prev2 = None
    step, skip = [0.0], [0.0]  # step[n]: n vs n-1; skip[n]: n+1 vs n-1, stored at n
    n = 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        f = np.frombuffer(buf, np.uint8).reshape(H, W).astype(np.int16)
        if first is None:
            first = f
        if prev is not None:
            step.append(float(np.abs(f - prev).mean()))
        if prev2 is not None:
            skip.append(float(np.abs(f - prev2).mean()))
        prev2, prev = prev, f
        n += 1
    proc.wait()
    if proc.returncode or n < 3:
        print('ffmpeg could not decode enough frames', file=sys.stderr)
        return 2
    last = prev
    skip.append(0.0)
    d = np.array(step)
    g = np.array(skip[:n])
    ignore = parse_ranges(a.ignore)

    def declared(i):
        t = i / fps
        return any(s - 1e-6 <= t <= e + 1e-6 for s, e in ignore)

    cuts, ghosts, stutter = [], [], []
    for i in range(1, n):
        nxt = d[i + 1] if i + 1 < n else 0.0
        smallest = min(d[i], nxt)
        if (i + 1 < n and d[i] > a.move * 5 and nxt > a.move * 5 and g[i] < 0.5 * smallest):
            ghosts.append({'frame': i, 'time_s': round(i / fps, 3), 'step_in': round(d[i], 2),
                           'step_out': round(nxt, 2), 'neighbours_differ': round(g[i], 2), 'declared': declared(i)})
        elif d[i] > a.cut:
            cuts.append({'frame': i, 'time_s': round(i / fps, 3), 'step': round(d[i], 2)})
        # A repeated frame decodes nearly, not exactly, identical under B-frames: compare with its neighbours.
        if i + 1 < n and d[i - 1] > a.move and nxt > a.move and d[i] < max(a.still, 0.15 * min(d[i - 1], nxt)):
            stutter.append({'frame': i, 'time_s': round(i / fps, 3), 'declared': declared(i)})
    ghost_ids = {x['frame'] for x in ghosts}
    cuts = [c for c in cuts if c['frame'] - 1 not in ghost_ids]
    moving = int((d > a.move).sum())
    undeclared_stutter = [s for s in stutter if not s['declared']]
    share = len(undeclared_stutter) / moving if moving else 0.0
    result = {'video': a.video, 'frames': n, 'fps': fps, 'analysis_size': [W, H],
              'median_step': round(float(np.median(d[1:])), 3), 'moving_frames': moving,
              'cuts': cuts, 'one_frame_intrusions': ghosts, 'stutter_frames': stutter,
              'stutter_share_of_motion': round(share, 4)}
    # Holds and energy: descriptions to look at, not verdicts. A held stretch can be a designed
    # reading hold, a freeze on a silence, or a stall; only a look at speed tells which.
    held = d < a.hold_level
    held[0] = False
    holds, i = [], 1
    while i < n:
        if held[i]:
            j = i
            while j < n and held[j]:
                j += 1
            if (j - i) / fps >= a.hold_seconds:
                holds.append({'start_s': round((i - 1) / fps, 3), 'end_s': round((j - 1) / fps, 3),
                              'seconds': round((j - i + 1) / fps, 2), 'declared': declared(i)})
            i = j
        else:
            i += 1
    moving_idx = np.nonzero(d > a.move)[0]
    quiet = d[1:] < 0.5
    longest, run = 0, 0
    for q in quiet:
        run = run + 1 if q else 0
        longest = max(longest, run)
    result['first_motion_s'] = round(int(moving_idx[0]) / fps, 3) if moving_idx.size else None
    result['holds'] = holds
    result['energy'] = {'median_step': round(float(np.median(d[1:])), 3),
                        'p90_step': round(float(np.percentile(d[1:], 90)), 3),
                        'quiet_share': round(float(quiet.mean()), 3),
                        'longest_quiet_s': round(longest / fps, 2)}
    failed = bool([x for x in ghosts if not x['declared']]) or share > a.max_stutter
    if a.loop:
        seam = float(np.abs(first - last).mean())
        ends = np.concatenate([d[1:11], d[-10:]])
        ends = ends[ends > a.still]
        typical = float(np.median(ends)) if ends.size else 0.0
        limit = max(a.seam_ratio * typical, a.move)
        result['loop_seam'] = {'step': round(seam, 3), 'typical_end_step': round(typical, 3),
                               'limit': round(limit, 3), 'pass': seam <= limit}
        failed = failed or seam > limit
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1)
    if a.csv:
        with open(a.csv, 'w', newline='', encoding='utf-8') as fh:
            w = csv.writer(fh)
            w.writerow(['frame', 'time_s', 'step_from_previous', 'next_vs_previous'])
            for i in range(n):
                w.writerow([i, round(i / fps, 4), round(d[i], 4), round(g[i], 4)])
    print(f"{os.path.basename(a.video)}: {n} frames at {fps:g} fps; median step {result['median_step']}; "
          f"{moving} moving frames")
    print(f"  cuts: {[c['time_s'] for c in cuts] or 'none'}")
    e = result['energy']
    print(f"  first motion at {result['first_motion_s']} s; quiet frames {e['quiet_share']:.0%}; "
          f"longest quiet stretch {e['longest_quiet_s']} s; p90 step {e['p90_step']}")
    for h in result['holds']:
        print(f"  {'declared' if h['declared'] else 'look at'} hold {h['start_s']}-{h['end_s']} s "
              f"({h['seconds']} s): alive, intended, or stalled?")
    for x in ghosts:
        print(f"  {'declared' if x['declared'] else 'INSPECT'} one-frame intrusion at frame {x['frame']} "
              f"({x['time_s']} s): in {x['step_in']}, out {x['step_out']}, neighbours differ {x['neighbours_differ']}")
    print(f"  repeated frames inside motion: {len(undeclared_stutter)} undeclared "
          f"({share:.2%} of moving frames; limit {a.max_stutter:.0%})"
          + (f" at {[s['time_s'] for s in undeclared_stutter[:12]]}" if undeclared_stutter else ''))
    if a.loop:
        s = result['loop_seam']
        print(f"  loop seam: step {s['step']} vs typical end step {s['typical_end_step']} "
              f"(limit {s['limit']}): {'pass' if s['pass'] else 'FAIL'}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
