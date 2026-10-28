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

Every frame is decoded once and timed by its own presentation timestamp. With variable frame
timing (screen recordings, GIFs) a hold can be stored as one long frame rather than repeated
frames, so it shows as a long interval in the --csv profile, not as stutter.
Thresholds are heuristics on the 0-255 grey scale; tune them on your own renders and declare
designed holds, freezes and flashes with --ignore (seconds). Every flag is a candidate: inspect it
with frame_sheet.py --frames A-B before changing anything. The profile cannot judge whether a move
feels right at speed. Needs numpy and FFmpeg. Exit code 0 when nothing fails, 1 when an undeclared
intrusion, excess stutter or a failing loop seam is found, 2 when the file cannot be read or has fewer
than three frames.
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit('motion_scan.py needs numpy: pip install numpy')

PTS = re.compile(r'pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')
DUR = re.compile(r'duration_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def passthrough(ffmpeg):
    """Frame-exact output: -fps_mode passthrough (FFmpeg 5.1 and later), -vsync passthrough before it."""
    try:
        head = subprocess.run([ffmpeg, '-hide_banner', '-version'], capture_output=True, text=True).stdout
    except OSError:
        head = ''
    m = re.search(r'version n?(\d+)\.(\d+)', head)
    old = m is not None and (int(m.group(1)), int(m.group(2))) < (5, 1)
    return ['-vsync' if old else '-fps_mode', 'passthrough']


class Frames:
    """Each decoded frame of the first video stream, once and in order, with its presentation time."""

    def __init__(self, ffmpeg, path, vf, frame_bytes):
        cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', path, '-map', '0:v:0',
               '-vf', vf + ',showinfo', *passthrough(ffmpeg), '-f', 'rawvideo', 'pipe:1']
        self.size, self.pts, self.dur, self.log = frame_bytes, [], [], []
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.reader = threading.Thread(target=self._read_log, daemon=True)
        self.reader.start()

    def _read_log(self):
        for raw in self.proc.stderr:
            line = raw.decode('utf-8', 'replace').strip()
            m = PTS.search(line) if 'showinfo' in line else None
            if m:
                self.pts.append(float(m.group(1)))
                d = DUR.search(line)
                self.dur.append(float(d.group(1)) if d else None)
            elif line:
                self.log = self.log[-4:] + [line]

    def __iter__(self):
        while True:
            buf = self.proc.stdout.read(self.size)
            if len(buf) < self.size:
                break
            yield buf
        self.proc.stdout.close()
        self.proc.wait()
        self.reader.join()

    def times(self, count):
        """Each frame's time on the film clock: seconds from the start of the file, as FFmpeg reads it."""
        if self.proc.returncode or count == 0:
            raise RuntimeError('ffmpeg could not decode the video' + (f': {self.log[-1]}' if self.log else ''))
        if len(self.pts) != count:
            raise RuntimeError(f'decoded {count} frames but read {len(self.pts)} timestamps')
        return list(self.pts)

    def end(self):
        """When the last frame stops showing: its own recorded duration, else the interval before it."""
        last = self.dur[-1] if self.dur else None
        if last and last > 0:
            return self.pts[-1] + last
        return self.pts[-1] + (self.pts[-1] - self.pts[-2] if len(self.pts) > 1 else 0.0)


def parse_ranges(text):
    """'0-0.5,12.1-12.4' -> [(0.0, 0.5), (12.1, 12.4)]; raises ValueError naming the bad part."""
    out = []
    for part in (text or '').split(','):
        if part.strip():
            m = re.fullmatch(r'\s*(\d+(?:\.\d*)?)\s*-\s*(\d+(?:\.\d*)?)\s*', part)
            if not m or float(m.group(1)) > float(m.group(2)):
                raise ValueError(f'{part.strip()!r} is not a range START-END in seconds, e.g. 12.1-12.4')
            out.append((float(m.group(1)), float(m.group(2))))
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
    try:
        ignore = parse_ranges(a.ignore)
    except ValueError as e:
        p.error(f'--ignore: {e}')
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)', file=sys.stderr)
        return 2
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,avg_frame_rate', '-of', 'json', a.video], capture_output=True, text=True)
    streams = json.loads(r.stdout or '{}').get('streams') if r.returncode == 0 else None
    if not streams:
        reason = (r.stderr.strip().splitlines() or ['no video stream'])[-1]
        print(f'motion_scan.py: cannot read {a.video}: {reason}', file=sys.stderr)
        return 2
    info = streams[0]
    W = a.width - a.width % 2
    H = max(2, int(round(W * info['height'] / info['width'] / 2.0)) * 2)
    frames = Frames(ffmpeg, a.video, f'scale={W}:{H}:flags=area,format=gray', W * H)
    first = prev = prev2 = None
    step, skip = [0.0], [0.0]  # step[n]: n vs n-1; skip[n]: n+1 vs n-1, stored at n
    n = 0
    for buf in frames:
        f = np.frombuffer(buf, np.uint8).reshape(H, W).astype(np.int16)
        if first is None:
            first = f
        if prev is not None:
            step.append(float(np.abs(f - prev).mean()))
        if prev2 is not None:
            skip.append(float(np.abs(f - prev2).mean()))
        prev2, prev = prev, f
        n += 1
    try:
        times = frames.times(n)
    except RuntimeError as e:
        print(f'motion_scan.py: cannot scan {a.video}: {e}', file=sys.stderr)
        return 2
    if n < 3:
        print(f'motion_scan.py: {a.video} has {n} frame(s); at least 3 are needed', file=sys.stderr)
        return 2
    last = prev
    skip.append(0.0)
    d = np.array(step)
    g = np.array(skip[:n])
    intervals = np.diff(times)
    typical = float(np.median(intervals))
    variable = typical > 0 and float(intervals.max() - intervals.min()) > 0.25 * typical
    # With constant timing, report the stream's declared rate; otherwise the average over the whole run (not one
    # interval: millisecond timestamps alternate 33 and 34 ms at 30 fps).
    fps = round((n - 1) / (times[-1] - times[0]), 2) if times[-1] > times[0] else 0.0
    num, _, den = str(info.get('avg_frame_rate', '0/1')).partition('/')
    try:
        declared_fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        declared_fps = 0.0
    if declared_fps > 0 and not variable:
        fps = round(declared_fps, 3)
    shown_until = list(times[1:]) + [frames.end()]  # when each frame gives way to the next

    def declared(i):
        t = times[i]
        return any(s - 1e-6 <= t <= e + 1e-6 for s, e in ignore)

    cuts, ghosts, stutter = [], [], []
    for i in range(1, n):
        nxt = d[i + 1] if i + 1 < n else 0.0
        smallest = min(d[i], nxt)
        if (i + 1 < n and d[i] > a.move * 5 and nxt > a.move * 5 and g[i] < 0.5 * smallest):
            ghosts.append({'frame': i, 'time_s': round(times[i], 3), 'step_in': round(d[i], 2),
                           'step_out': round(nxt, 2), 'neighbours_differ': round(g[i], 2), 'declared': declared(i)})
        elif d[i] > a.cut:
            cuts.append({'frame': i, 'time_s': round(times[i], 3), 'step': round(d[i], 2)})
        # A repeated frame decodes nearly, not exactly, identical under B-frames: compare with its neighbours.
        if i + 1 < n and d[i - 1] > a.move and nxt > a.move and d[i] < max(a.still, 0.15 * min(d[i - 1], nxt)):
            stutter.append({'frame': i, 'time_s': round(times[i], 3), 'declared': declared(i)})
    ghost_ids = {x['frame'] for x in ghosts}
    cuts = [c for c in cuts if c['frame'] - 1 not in ghost_ids]
    moving = int((d > a.move).sum())
    undeclared_stutter = [s for s in stutter if not s['declared']]
    share = len(undeclared_stutter) / moving if moving else 0.0
    result = {'video': a.video, 'frames': n, 'fps': fps, 'frame_timing': 'variable' if variable else 'constant',
              'analysis_size': [W, H], 'median_step': round(float(np.median(d[1:])), 3), 'moving_frames': moving,
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
            if times[j - 1] - times[i - 1] >= a.hold_seconds - 1e-6:
                holds.append({'start_s': round(times[i - 1], 3), 'end_s': round(times[j - 1], 3),
                              'seconds': round(shown_until[j - 1] - times[i - 1], 2), 'declared': declared(i)})
            i = j
        else:
            i += 1
    moving_idx = np.nonzero(d > a.move)[0]
    quiet = d < 0.5
    quiet[0] = False
    longest, start = 0.0, None
    for k in range(1, n):
        if quiet[k]:
            start = k if start is None else start
            longest = max(longest, times[k] - times[start - 1])
        else:
            start = None
    result['first_motion_s'] = round(times[int(moving_idx[0])], 3) if moving_idx.size else None
    result['holds'] = holds
    result['energy'] = {'median_step': round(float(np.median(d[1:])), 3),
                        'p90_step': round(float(np.percentile(d[1:], 90)), 3),
                        'quiet_share': round(float(quiet[1:].mean()), 3),
                        'longest_quiet_s': round(longest, 2)}
    failed = bool([x for x in ghosts if not x['declared']]) or share > a.max_stutter
    if a.loop:
        seam = float(np.abs(first - last).mean())
        ends = np.concatenate([d[1:11], d[-10:]])
        ends = ends[ends > a.still]
        typical_end = float(np.median(ends)) if ends.size else 0.0
        limit = max(a.seam_ratio * typical_end, a.move)
        result['loop_seam'] = {'step': round(seam, 3), 'typical_end_step': round(typical_end, 3),
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
                w.writerow([i, round(times[i], 4), round(d[i], 4), round(g[i], 4)])
    rate = f'{fps:g} fps' if not variable else f'about {fps:.3g} fps (variable frame timing)'
    print(f"{os.path.basename(a.video)}: {n} frames at {rate}; median step {result['median_step']}; "
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
