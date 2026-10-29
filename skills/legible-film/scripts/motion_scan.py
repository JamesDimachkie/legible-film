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
  python motion_scan.py footage.mp4 --footage --json qa/footage.json
  python motion_scan.py film.mp4 --ignore 4.0-4.2,12.5-13.0
  python motion_scan.py film.mp4 --start 0 --end 20 --max-still-share .4 --max-still .6

Pace also reports the share of pixels changing by more than --change-level (24),
still frames below --still-area (.015), PTS-timed still stretches, change events per
10 s (frames where at least --cut-area (.5) of the picture changes, with changes no
more than two frames apart merged into one event, so a whip or a flash counts once),
mean-grey flips and per-second profiles. Optional pace gates subtract --ignore
ranges exactly. --crop W:H:X:Y precedes analysis scaling; --bpm/--beat-offset label
zero-based beats. Shares exclude the first frame (no preceding comparison). Frame
indices are local to the selected window; times stay on the film clock. With --footage,
the repeated-frame gate uses exact native decoded-frame hashes;
near-holds remain information. Moving area is the union of pixels changing above
--change-level at analysis size. Below 5%, whole-frame pace is unreliable; the
region bounding box is also measured, and pace gates are inconclusive. Pace gates
are the film's chosen contract, not a general quality standard.

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
import math
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
    """Find an explicitly named tool, environment override or PATH executable."""
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

    def __init__(self, ffmpeg, path, vf, frame_bytes, input_options=None):
        cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', *(input_options or []), '-i', path, '-map', '0:v:0',
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


def pace_profile(times, until, areas, means, cuts, args, ignore):
    """Changes belong to the arriving frame. First frame has no predecessor and is excluded.

    Shares count compared frames; stretch lengths use PTS display intervals. Ignore ranges are
    half-open, subtracted exactly (including partial overlaps) for gates, never for the raw report.
    """
    n = len(times)
    end = min(until[-1], args.end) if args.end is not None else until[-1]
    still = np.asarray(areas) < args.still_area
    still[0] = False

    def subtract(s, e):
        pieces = [(s, e)]
        for lo, hi in sorted(ignore):
            pieces = [(x, y) for a, b in pieces for x, y in
                      ((a, min(b, lo)), (max(a, hi), b)) if y > x]
        return pieces

    def stretches(intervals):
        merged = []
        for s, e in intervals:
            if merged and s <= merged[-1][1] + 1e-6:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        return merged

    raw = stretches([(times[i], min(until[i], end)) for i in range(1, n) if still[i]])
    gate_runs = stretches([piece for s, e in raw for piece in subtract(s, e)])
    runs = []
    for s, e in raw:
        if e - s + 1e-6 < args.still_min:
            continue
        pieces = subtract(s, e)
        declared_s = (e - s) - sum(y - x for x, y in pieces)
        row = {'start_s': round(s, 6), 'end_s': round(e, 6), 'seconds': round(e - s, 6),
               'declared': declared_s > 1e-6, 'fully_declared': not pieces,
               'undeclared_segments': [[round(x, 6), round(y, 6)] for x, y in pieces]}
        if args.bpm is not None:
            row['beat'] = round((s - args.beat_offset) * args.bpm / 60, 6)
        runs.append(row)
    # A frame partially covered by an ignore range contributes only its remaining fraction.
    weights = [sum(y - x for x, y in subtract(times[i], min(until[i], end))) /
               max(1e-12, min(until[i], end) - times[i]) for i in range(1, n)]
    denom = sum(weights)
    gate_share = sum(w for i, w in enumerate(weights, 1) if still[i]) / denom if denom else 0.0
    longest = max((e - s for s, e in raw), default=0.0)
    gate_longest = max((e - s for s, e in gate_runs), default=0.0)
    profile = []
    for sec in range(math.floor(times[0]), math.ceil(end)):
        ids = [i for i in range(1, n) if sec <= times[i] < sec + 1]
        if ids:
            profile.append({'start_s': sec, 'frames': len(ids),
                            'still_share': round(float(still[ids].mean()), 6),
                            'median_change_area': round(float(np.median(np.asarray(areas)[ids])), 6)})
    flips = [{'frame': i, 'time_s': round(times[i], 6), 'mean_change': round(abs(means[i] - means[i-1]), 3)}
             for i in range(1, n) if abs(means[i] - means[i-1]) > 40]
    # Change events: frames where most of the picture is replaced at once. Consecutive or near-consecutive
    # frames (a whip's blurred frames, a flash in and out) are one event, not several.
    events = []
    for i in range(1, n):
        if areas[i] >= args.cut_area:
            if events and i - events[-1][-1] <= 2:
                events[-1].append(i)
            else:
                events.append([i])
    span = max(1e-12, end - times[0])
    return {'still_share': round(float(still[1:].mean()), 6), 'still_stretches': runs,
            'longest_still_s': round(longest, 6),
            'change_events': [{'start_s': round(times[e[0]], 6), 'frames': len(e)} for e in events],
            'change_events_per_10s': round(len(events) * 10 / span, 6),
            'cuts_per_10s': round(len(cuts) * 10 / span, 6),
            'flips': flips, 'median_change_area': round(float(np.median(areas[1:])), 6),
            'per_second': profile, 'change_area': [None] + [round(x, 6) for x in areas[1:]],
            'gate_still_share': round(gate_share, 6), 'gate_longest_still_s': round(gate_longest, 6),
            'window_s': [times[0], end], 'compared_frames': n - 1,
            'first_frame': 'excluded: no preceding frame in the analysis window',
            'thresholds': {'change_level': args.change_level, 'still_area': args.still_area, 'cut_area': args.cut_area}}



def native_hashes(ffmpeg, path, start, end):
    """Hash each decoded frame without scaling or colour conversion."""
    trim = f'trim=start={start}' + (f':end={end}' if end is not None else '')
    cmd = [ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', path, '-map', '0:v:0',
           '-vf', trim, *passthrough(ffmpeg), '-f', 'framemd5', '-']
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError('native frame hashing failed: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
    return [line.split(',')[-1].strip() for line in r.stdout.splitlines() if line and not line.startswith('#')]


def region_profile(ffmpeg, path, filters, width, height, box, change_level):
    """Measure per-frame change and mean inside the moving area's bounding box."""
    frames = Frames(ffmpeg, path, ','.join(filters), width * height)
    x0, y0, x1, y1 = box
    previous = None
    areas = [0.0]
    steps = [0.0]
    means = []
    for buf in frames:
        frame = np.frombuffer(buf, np.uint8).reshape(height, width)[y0:y1, x0:x1].astype(np.int16)
        means.append(float(frame.mean()))
        if previous is not None:
            difference = np.abs(frame - previous)
            areas.append(float((difference > change_level).mean()))
            steps.append(float(difference.mean()))
        previous = frame
    frames.times(len(means))
    return areas, means, steps

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
    p.add_argument('--footage', action='store_true',
                   help='gate only exact native decoded duplicates; report near-holds')
    p.add_argument('--loop', action='store_true', help='also check the last-to-first seam')
    p.add_argument('--seam-ratio', type=float, default=1.5, help='seam may be this many times the typical end step')
    p.add_argument('--ignore', help='designed ranges in seconds, e.g. 3.9-4.2,10-11')
    p.add_argument('--change-level', type=float, default=24, help='grey change must exceed this (0-255)')
    p.add_argument('--still-area', type=float, default=0.015, help='still when changed area is below this share')
    p.add_argument('--still-min', type=float, default=0.3, help='minimum pace stretch to list, seconds')
    p.add_argument('--cut-area', type=float, default=0.5,
                   help='share of the picture changing at once that counts as a change event')
    p.add_argument('--bpm', type=float, help='report zero-based beat at each still stretch start')
    p.add_argument('--beat-offset', type=float, default=0, help='film time of beat zero')
    p.add_argument('--start', type=float, default=0, help='first film time included, seconds')
    p.add_argument('--end', type=float, help='end of half-open analysis window, seconds')
    p.add_argument('--crop', help='analyse region W:H:X:Y in source pixels, before scaling')
    p.add_argument('--max-still-share', type=float, help='pace gate on undeclared compared frames')
    p.add_argument('--max-still', type=float, help='pace gate on longest undeclared stretch, seconds')
    p.add_argument('--json')
    p.add_argument('--csv', help='write the per-frame profile')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    for key in ('change_level', 'still_area', 'still_min', 'bpm', 'beat_offset', 'start', 'end',
                'max_still_share', 'max_still'):
        v = getattr(a, key)
        if v is not None and not math.isfinite(v):
            p.error('--' + key.replace('_', '-') + ' must be finite')
    if (a.width < 2 or not 0 <= a.change_level <= 255 or not 0 <= a.still_area <= 1 or not 0 < a.cut_area <= 1 or
            a.still_min < 0 or a.start < 0 or (a.end is not None and a.end <= a.start) or
            (a.bpm is not None and a.bpm <= 0) or
            (a.max_still_share is not None and not 0 <= a.max_still_share <= 1) or
            (a.max_still is not None and a.max_still < 0)):
        p.error('invalid pace threshold, width or analysis window')
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
    crop = None
    if a.crop:
        if not re.fullmatch(r'\d+:\d+:\d+:\d+', a.crop):
            p.error('--crop needs W:H:X:Y in source pixels')
        crop = [int(x) for x in a.crop.split(':')]
        cw, ch, cx, cy = crop
        if cw < 2 or ch < 2 or cx + cw > info['width'] or cy + ch > info['height']:
            p.error('--crop lies outside the picture')
    W = a.width - a.width % 2
    H = max(2, int(round(W * (crop[1] / crop[0] if crop else info['height'] / info['width']) / 2.0)) * 2)
    filters = [f'trim=start={a.start}' + (f':end={a.end}' if a.end is not None else '')]
    if crop:
        filters.append('crop=' + a.crop + ':exact=1')
    filters.append(f'scale={W}:{H}:flags=area,format=gray')
    frames = Frames(ffmpeg, a.video, ','.join(filters), W * H)
    first = prev = prev2 = None
    step, skip = [0.0], [0.0]  # step[n]: n vs n-1; skip[n]: n+1 vs n-1, stored at n
    n = 0
    areas, means = [0.0], []
    moving_mask = np.zeros((H, W), dtype=bool)
    for buf in frames:
        f = np.frombuffer(buf, np.uint8).reshape(H, W).astype(np.int16)
        means.append(float(f.mean()))
        if first is None:
            first = f
        if prev is not None:
            step.append(float(np.abs(f - prev).mean()))
            changed = np.abs(f - prev) > a.change_level
            moving_mask |= changed
            areas.append(float(changed.mean()))
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
    near_holds = []
    if a.footage:
        try:
            hashes = native_hashes(ffmpeg, a.video, a.start, a.end)
        except RuntimeError as e:
            print(f'motion_scan.py: {e}', file=sys.stderr)
            return 2
        if len(hashes) != n:
            print('motion_scan.py: native duplicate check has a different frame count', file=sys.stderr)
            return 2
        near_holds = [row for row in stutter if hashes[row['frame']] != hashes[row['frame'] - 1]]
        stutter = [row for row in stutter if hashes[row['frame']] == hashes[row['frame'] - 1]]
    ghost_ids = {x['frame'] for x in ghosts}
    cuts = [c for c in cuts if c['frame'] - 1 not in ghost_ids]
    moving = int((d > a.move).sum())
    undeclared_stutter = [s for s in stutter if not s['declared']]
    share = len(undeclared_stutter) / moving if moving else 0.0
    result = {'video': a.video, 'frames': n, 'fps': fps, 'frame_timing': 'variable' if variable else 'constant',
              'analysis_size': [W, H], 'median_step': round(float(np.median(d[1:])), 3), 'moving_frames': moving,
              'cuts': cuts, 'one_frame_intrusions': ghosts, 'stutter_frames': stutter,
              'stutter_share_of_motion': round(share, 4)}
    if a.footage:
        result['near_holds'] = near_holds
        result['duplicate_tolerance'] = 'exact native decoded frame hash'
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
    result['pace'] = pace_profile(times, shown_until, areas, means, cuts, a, ignore)
    pace = result['pace']
    fraction = float(moving_mask.mean())
    pace['moving_area_fraction'] = round(fraction, 6)
    small = 0 < fraction < 0.05
    if small:
        ys, xs = np.nonzero(moving_mask)
        box = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        try:
            region_areas, region_means, region_steps = region_profile(
                ffmpeg, a.video, filters, W, H, box, a.change_level)
        except RuntimeError as e:
            print(f'motion_scan.py: {e}', file=sys.stderr)
            return 2
        if len(region_means) != n:
            print('motion_scan.py: moving-region scan has a different frame count', file=sys.stderr)
            return 2
        pace['moving_region_bbox'] = box
        region_cuts = [{'frame': i} for i in range(1, n) if region_steps[i] > a.cut]
        pace['moving_region'] = pace_profile(times, shown_until, region_areas, region_means, region_cuts, a, ignore)
        pace['moving_region']['moving_frames'] = sum(step > a.move for step in region_steps[1:])
        pace['interpretation'] = ('Moving area below 5%: whole-frame still share and pace are unreliable; '
                                  'pace contracts are inconclusive.')
    pace['gates'] = {}
    if a.max_still_share is not None:
        passed = None if small else pace['gate_still_share'] <= a.max_still_share + 1e-6
        pace['gates']['max_still_share'] = {'pass': passed, 'limit': a.max_still_share,
                                          'actual': pace['gate_still_share']}
        failed = failed or passed is not True
    if a.max_still is not None:
        passed = None if small else pace['gate_longest_still_s'] <= a.max_still + 1e-6
        pace['gates']['max_still'] = {'pass': passed, 'limit': a.max_still,
                                    'actual': pace['gate_longest_still_s']}
        failed = failed or passed is not True
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
            w.writerow(['frame', 'time_s', 'step_from_previous', 'next_vs_previous', 'change_area', 'pace_still'])
            for i in range(n):
                w.writerow([i, round(times[i], 4), round(d[i], 4), round(g[i], 4),
                            round(areas[i], 6) if i else '', bool(areas[i] < a.still_area) if i else ''])
    rate = f'{fps:g} fps' if not variable else f'about {fps:.3g} fps (variable frame timing)'
    print(f"{os.path.basename(a.video)}: {n} frames at {rate}; median step {result['median_step']}; "
          f"{moving} moving frames")
    print(f"  cuts: {[c['time_s'] for c in cuts] or 'none'}")
    print(f"  moving area anywhere in clip: {fraction:.3%} of analysis frame")
    if small:
        region = pace['moving_region']
        print('  ' + pace['interpretation'])
        print(f"  moving region {pace['moving_region_bbox']}: {region['moving_frames']} moving frames; "
              f"still {region['still_share']:.2%}; "
              f"longest {region['longest_still_s']:.3f} s; "
              f"change events/10 s {region['change_events_per_10s']:.2f}; "
              f"median changed area {region['median_change_area']:.3%}")
    print(f"  pace: still {pace['still_share']:.2%}; longest {pace['longest_still_s']:.3f} s; "
          f"change events/10 s {pace['change_events_per_10s']:.2f} "
          f"(step-detector cuts/10 s {pace['cuts_per_10s']:.2f}); "
          f"flips {len(pace['flips'])}; "
          f"median changed area {pace['median_change_area']:.3%}")
    print(f"  pace gates excluding declared ranges: still {pace['gate_still_share']:.2%}; "
          f"longest {pace['gate_longest_still_s']:.3f} s")
    for name, gate in pace['gates'].items():
        status = 'INCONCLUSIVE' if gate['pass'] is None else 'PASS' if gate['pass'] else 'FAIL'
        print(f"  {status} pace {name}: {gate['actual']} <= {gate['limit']}")
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
    if a.footage:
        print(f'  near-holds (information): {len(near_holds)}')
    if a.loop:
        s = result['loop_seam']
        print(f"  loop seam: step {s['step']} vs typical end step {s['typical_end_step']} "
              f"(limit {s['limit']}): {'pass' if s['pass'] else 'FAIL'}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
