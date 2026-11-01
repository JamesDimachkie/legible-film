#!/usr/bin/env python3
"""Conservative screen for flashing (WCAG 2.3.1 general and red flash) in a rendered video.

WCAG 2.3.1 fails content that flashes more than three times in any one second when the flashing
area exceeds the general or red flash thresholds. This script flags intervals to inspect. It is
not a Harding FPA, IRIS or PEAT pass, which some broadcasters and platforms require.

Method. Decode at reduced size and examine overlapping windows one third of the frame wide and
high. WCAG's area criterion is a quarter of a 10-degree visual field. This screen uses each
window as a conservative approximation, but cannot know the display size or viewing distance.
Area and point sampling are both screened so downscaling does not average away fine patterns.
A classic transition requires at least 25% of a window's pixels to change together in the same
direction between two images. The quarter-area boundary is included to avoid rounding it away:
  - for general flashes, each counted pixel must change by at least 0.10 relative luminance,
    and its darker endpoint must be below 0.80;
  - for red flashes, saturated-red amount (R-G-B)*320 must change by at least 20 for each counted
    pixel. Saturated red has R/(R+G+B) >= 0.8.
Opposite swings are counted separately. If at least a quarter changes in each direction at once,
the general swing is ambiguous: it is retained as a pattern candidate, not a definite classic
swing. Pattern detectors also track mixed-direction pixel reversals and abrupt area changes.
A unique, close translation is compensated for the pattern detectors; ambiguous motion can still
be flagged. Scaling or point sampling can miss or exaggerate fine detail or threshold-area changes;
pixels that change in different directions or move between samples may remain ambiguous. This is
a screen for review, not a guarantee that all dangerous flashes have been detected.
A flash is a pair of opposing transitions, so a window with more than six transitions inside one
second (more than three flashes) is flagged.

Every frame is decoded once, without duplication or dropping, and timed by its own presentation
timestamp, so variable frame timing (screen recordings, GIFs) is screened on the clock it plays on.

  python flash_scan.py film.mp4
  python flash_scan.py film.mp4 --json qa/flash.json

The golden cases in selftest.py (synthetic clips with known answers) exercise this logic.
Needs numpy and FFmpeg. Exit code 0 when no window is flagged, 1 when any window is flagged,
2 when the file cannot be screened.
"""

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from fractions import Fraction

_project_spec = importlib.util.spec_from_file_location(
    'lf_project', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py'))
project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(project)
try:
    import numpy as np
except ImportError:
    print(project.dependency_message('numpy'), file=sys.stderr)
    sys.exit(2)

PTS = re.compile(r'pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')
PTS_TICKS = re.compile(r'\bpts:\s*(-?\d+)\s+pts_time:')
TIME_BASE = re.compile(r'config in time_base:\s*(\d+)/(\d+)')
DUR = re.compile(r'duration_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def failure(e):
    """One line saying why a step failed."""
    if isinstance(e, subprocess.CalledProcessError):
        tail = (e.stderr or '').strip().splitlines()
        return tail[-1] if tail else f'{os.path.basename(str(e.cmd[0]))} exited with {e.returncode}'
    return str(e)


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

    def __init__(self, ffmpeg, path, vf, frame_bytes, start=None, end=None):
        window = (['-ss', f'{start:.6f}'] if start else []) + (
            ['-t', f'{end - (start or 0.0):.6f}'] if end is not None else [])
        cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', *window, '-i', path, '-map', '0:v:0',
               '-vf', vf + ',showinfo', *passthrough(ffmpeg), '-f', 'rawvideo', 'pipe:1']
        self.size, self.pts, self.dur, self.log = frame_bytes, [], [], []
        self.time_base = None
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.reader = threading.Thread(target=self._read_log, daemon=True)
        self.reader.start()

    def _read_log(self):
        for raw in self.proc.stderr:
            line = raw.decode('utf-8', 'replace').strip()
            config = TIME_BASE.search(line) if 'showinfo' in line else None
            if config:
                self.time_base = Fraction(int(config.group(1)), int(config.group(2)))
            m = PTS.search(line) if 'showinfo' in line else None
            if m:
                ticks = PTS_TICKS.search(line)
                if ticks and self.time_base is not None:
                    self.pts.append(float(int(ticks.group(1)) * self.time_base))
                else:
                    self.log.append('showinfo did not supply a frame PTS and time base')
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


def timing(times):
    """('constant' or 'variable', the typical frame interval in seconds)."""
    steps = np.diff(times) if len(times) > 1 else np.zeros(1)
    typical = float(np.median(steps))
    variable = len(times) > 2 and typical > 0 and float(steps.max() - steps.min()) > 0.25 * typical
    return ('variable' if variable else 'constant'), typical


def probe(ffprobe, path):
    out = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,avg_frame_rate,r_frame_rate', '-of', 'json', path],
                         capture_output=True, text=True, check=True).stdout
    streams = json.loads(out).get('streams') or []
    if not streams:
        raise RuntimeError('no video stream')
    s = streams[0]
    for key in ('avg_frame_rate', 'r_frame_rate'):
        num, _, den = s.get(key, '0/0').partition('/')
        if float(den or 1) and float(num):
            return int(s['width']), int(s['height']), float(num) / float(den or 1)
    raise RuntimeError('could not read the frame rate')


def interlaced(ffprobe, path):
    """True when the stream or its first frames are flagged interlaced: then each field is its own image in time."""
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-read_intervals', '%+#30',
                        '-show_entries', 'stream=field_order:frame=interlaced_frame', '-of', 'json', path],
                       capture_output=True, text=True)
    data = json.loads(r.stdout or '{}') if r.returncode == 0 else {}
    order = ((data.get('streams') or [{}])[0]).get('field_order', '')
    return order in ('tt', 'bb', 'tb', 'bt') or any(f.get('interlaced_frame') == 1 for f in data.get('frames', []))


def linear(c8):
    c = c8.astype(np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


class CoherentZig:
    """Count directional swings only when enough corresponding pixels change together."""

    def __init__(self, threshold=.10, area=.25, darker_below=.80, ambiguous_patterns=True):
        self.threshold = threshold
        self.area = area
        self.darker_below = darker_below
        self.ambiguous_patterns = ambiguous_patterns
        self.pivot = None
        self.extreme = None
        self.extreme_time = None
        self.direction = 0
        self.ends = []
        self.ambiguous_ends = []

    def changed(self, earlier, later, direction):
        """Whether at least the required fraction changed in one direction."""
        changed = (later - earlier) * direction >= self.threshold
        if self.darker_below is not None:
            changed &= np.minimum(earlier, later) < self.darker_below
        return np.count_nonzero(changed) >= self.area * earlier.size

    def push(self, when, values, motion=None):
        image = np.asarray(values, dtype=np.float32)
        pixels = image.ravel()
        if self.pivot is None:
            self.pivot = pixels.copy()
            self.extreme = pixels.copy()
            self.extreme_time = when
            return
        if motion is not None and image.ndim == 2:
            self.pivot = translated(self.pivot.reshape(image.shape), motion, image).ravel()
            self.extreme = translated(self.extreme.reshape(image.shape), motion, image).ravel()
        if not self.direction:
            for direction in (1, -1):
                if self.changed(self.pivot, pixels, direction):
                    self.direction = direction
                    self.extreme = pixels.copy()
                    self.extreme_time = when
                    break
            return
        if self.changed(self.extreme, pixels, -self.direction):
            self.record_extreme()
            self.pivot = self.extreme
            self.extreme = pixels.copy()
            self.extreme_time = when
            self.direction = -self.direction
        elif ((float(np.mean(pixels)) - float(np.mean(self.extreme))) * self.direction > 0 and
              self.changed(self.pivot, pixels, self.direction)):
            # Refine the extreme without shifting the first threshold-crossing time.
            self.extreme = pixels.copy()

    def finish(self):
        if self.direction:
            self.record_extreme()

    def record_extreme(self):
        """Keep simultaneous large opposite changes for pattern review."""
        if not self.changed(self.pivot, self.extreme, self.direction):
            return
        ambiguous = self.ambiguous_patterns and self.changed(self.pivot, self.extreme, -self.direction)
        (self.ambiguous_ends if ambiguous else self.ends).append(self.extreme_time)


class RedZig(CoherentZig):
    """Count changes in saturated-red amount across a coherent area."""

    def __init__(self, threshold=20.0, area=.25):
        super().__init__(threshold=threshold, area=area, darker_below=None, ambiguous_patterns=False)


def translated(values, motion, fill):
    """Move old pixels into the new frame, filling newly exposed edges from the current image."""
    dy, dx = motion
    height, width = values.shape
    out = fill.copy()
    y0, y1 = max(0, dy), min(height, height + dy)
    x0, x1 = max(0, dx), min(width, width + dx)
    if y1 > y0 and x1 > x0:
        out[y0:y1, x0:x1] = values[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


def unique_translation(previous, current):
    """A unique, high-confidence translation only; periodic or changing images remain candidates."""
    height, width = previous.shape
    first = np.fft.rfft2(previous - np.mean(previous))
    autocorrelation = np.fft.irfft2(first * np.conj(first), s=previous.shape).real
    zero = float(autocorrelation[0, 0])
    if zero <= 1e-9:
        return None
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            autocorrelation[dy % height, dx % width] = 0
    if float(np.max(autocorrelation)) >= .5 * zero:
        return None
    second = np.fft.rfft2(current - np.mean(current))
    cross = second * np.conj(first)
    correlation = np.fft.irfft2(cross / np.maximum(np.abs(cross), 1e-9), s=previous.shape).real
    peak_y, peak_x = np.unravel_index(np.argmax(correlation), correlation.shape)
    peak = float(correlation[peak_y, peak_x])
    rest = correlation.copy()
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            rest[(peak_y + dy) % height, (peak_x + dx) % width] = 0
    runner_up = float(np.max(rest))
    dy = int(peak_y if peak_y <= height // 2 else peak_y - height)
    dx = int(peak_x if peak_x <= width // 2 else peak_x - width)
    if (not (dx or dy) or abs(dx) > width // 6 or abs(dy) > height // 6 or peak < .12 or
            peak < 2 * max(runner_up, 1e-9)):
        return None
    aligned = translated(previous, (dy, dx), current)
    residual = float(np.mean(np.abs(aligned - current)))
    unaligned = float(np.mean(np.abs(previous - current)))
    return (dy, dx) if residual < .025 and residual < unaligned * .25 else None


class GeneralZig:
    """Count opposite luminance swings in the same pixels, rather than a passing textured pan."""

    def __init__(self, threshold=.10, area=.25):
        self.threshold = threshold
        self.area = area
        self.pivot = None
        self.extreme = None
        self.extreme_time = None
        self.ends = []

    def changed(self, earlier, later):
        """Pixels with a WCAG-sized swing and a dark enough endpoint."""
        return (np.abs(later - earlier) >= self.threshold) & (np.minimum(earlier, later) < .80)

    def push(self, when, values, motion=None):
        image = np.asarray(values, dtype=np.float32)
        pixels = image.ravel()
        if self.pivot is None:
            self.pivot = pixels.copy()
            return
        if motion is not None and image.ndim == 2:
            self.pivot = translated(self.pivot.reshape(image.shape), motion, image).ravel()
            if self.extreme is not None:
                self.extreme = translated(self.extreme.reshape(image.shape), motion, image).ravel()
        if self.extreme is None:
            if np.count_nonzero(self.changed(self.pivot, pixels)) >= self.area * pixels.size:
                self.extreme = pixels.copy()
                self.extreme_time = when
            return
        forward = self.extreme - self.pivot
        backward = pixels - self.extreme
        reversals = (self.changed(self.pivot, self.extreme) & self.changed(self.extreme, pixels) &
                     (forward * backward < 0))
        if np.count_nonzero(reversals) >= self.area * pixels.size:
            self.ends.append(self.extreme_time)
            self.pivot = self.extreme
            self.extreme = pixels.copy()
            self.extreme_time = when
        elif np.abs(pixels - self.pivot).sum() > np.abs(self.extreme - self.pivot).sum():
            # Refine the extreme but keep when the transition first crossed its threshold.
            # Codec noise during a held picture must not move an event later.
            self.extreme = pixels.copy()

    def finish(self):
        if self.extreme is not None:
            self.ends.append(self.extreme_time)


class AreaTransitions:
    """Count opposing abrupt area swings even when the changed pixels move slightly."""

    def __init__(self, threshold=.10, area=.25, overlap=.12):
        self.threshold = threshold
        self.area = area
        self.overlap = overlap
        self.previous = None
        self.event_delta = None
        self.event_mask = None
        self.event_time = None
        self.chain = False
        self.ends = []

    def push(self, when, values, motion=None):
        """Track only large changes, and count them when a meaningful area reverses."""
        image = np.asarray(values, dtype=np.float32)
        if self.previous is None:
            self.previous = image.copy()
            return
        old = translated(self.previous, motion, image) if motion is not None else self.previous
        if motion is not None and self.event_delta is not None:
            empty = np.zeros_like(image)
            self.event_delta = translated(self.event_delta, motion, empty)
            self.event_mask = translated(self.event_mask.astype(np.float32), motion, empty) > .5
        delta = image - old
        changed = (np.abs(delta) >= self.threshold) & (np.minimum(image, old) < .80)
        if np.count_nonzero(changed) >= self.area * changed.size:
            if self.event_delta is not None:
                reversal = changed & self.event_mask & (delta * self.event_delta < 0)
                if np.count_nonzero(reversal) >= self.overlap * changed.size:
                    if not self.chain:
                        self.ends.append(self.event_time)
                    self.ends.append(when)
                    self.chain = True
                else:
                    self.chain = False
            self.event_delta = delta
            self.event_mask = changed
            self.event_time = when
        self.previous = image.copy()

    def finish(self):
        """Both ends of every confirmed pair were already recorded."""


def busiest_second(ends, tolerance=1e-5):
    best, at, j = 0, None, 0
    ends = sorted(ends)
    for i in range(len(ends)):
        while ends[i] - ends[j] >= 1.0 - tolerance:
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
    ap.add_argument('--start', type=float, help='screen from this source time in seconds (times stay on the source '
                                                'clock), to check a shot before building a cut around it')
    ap.add_argument('--end', type=float, help='stop at this source time in seconds')
    a = ap.parse_args()
    try:
        project.refuse_overwriting_inputs([a.json], [a.video])
    except ValueError as error:
        print(f'flash_scan.py: cannot run: {error}', file=sys.stderr)
        return 2
    if (a.start is not None and (a.start < 0 or a.start != a.start)) or (
            a.end is not None and (a.end != a.end or a.end <= (a.start or 0.0))):
        print('--start must be 0 or more and --end after it', file=sys.stderr)
        return 2
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)', file=sys.stderr)
        return 2
    try:
        return screen(a, ffmpeg, ffprobe)
    except (subprocess.CalledProcessError, RuntimeError, OSError, ValueError, KeyError) as e:
        print(f'flash_scan.py: cannot screen {a.video}: {failure(e)}', file=sys.stderr)
        return 2


def screen(a, ffmpeg, ffprobe):
    w0, h0, fps = probe(ffprobe, a.video)
    fields = interlaced(ffprobe, a.video)
    W = a.width - a.width % 2
    H = max(6, int(round(W * h0 / w0 / 2.0)) * 2)
    # Interlaced pictures are shown one field at a time, so a flash can live between the two fields of one frame.
    field_filter = 'separatefields,' if fields else ''
    vf = (field_filter + f'split=2[area][point];[area]scale={W}:{H}:flags=area[a];'
          f'[point]scale={W}:{H}:flags=neighbor[b];[a][b]hstack=inputs=2,format=rgb24')
    frames = Frames(ffmpeg, a.video, vf, W * 2 * H * 3, getattr(a, 'start', None), getattr(a, 'end', None))
    ww, wh = W // 3, H // 3
    xs = sorted({x for x in range(0, W - ww + 1, max(1, W // 6))} | {W - ww})
    ys = sorted({y for y in range(0, H - wh + 1, max(1, H // 6))} | {H - wh})
    wins = [(x + mode * W, y) for mode in range(2) for y in ys for x in xs]
    n = 0
    classic_zigs = [CoherentZig() for _ in wins]
    candidate_zigs = [CoherentZig() for _ in wins]
    red_zigs = [RedZig() for _ in wins]
    general_zigs = [GeneralZig() for _ in wins]
    area_zigs = [AreaTransitions() for _ in wins]
    previous_luma = None
    for buf in frames:
        lin = linear(np.frombuffer(buf, np.uint8).reshape(H, W * 2, 3))
        Y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
        motion = unique_translation(previous_luma, Y[:, :W]) if previous_luma is not None else None
        previous_luma = Y[:, :W].copy()
        s = lin.sum(axis=2) + 1e-9
        red = np.where(lin[..., 0] / s >= 0.8, np.maximum(0.0, (lin[..., 0] - lin[..., 1] - lin[..., 2]) * 320.0), 0.0)
        for classic, candidate, red_detector, general_detector, area_detector, (x, y) in zip(
                classic_zigs, candidate_zigs, red_zigs, general_zigs, area_zigs, wins):
            classic.push(n, Y[y:y + wh, x:x + ww])
            candidate.push(n, Y[y:y + wh, x:x + ww], motion)
            red_detector.push(n, red[y:y + wh, x:x + ww])
            general_detector.push(n, Y[y:y + wh, x:x + ww], motion)
            area_detector.push(n, Y[y:y + wh, x:x + ww], motion)
        n += 1
    offset = getattr(a, 'start', None) or 0.0
    times = [t + offset for t in frames.times(n)]
    clock, step = timing(times)
    rows, flagged = [], []
    for k, (x, y) in enumerate(wins):
        for z in (classic_zigs[k], candidate_zigs[k], red_zigs[k], general_zigs[k]):
            z.finish()
        classic = busiest_second([times[index] for index in classic_zigs[k].ends], 1e-9)
        patterns = [busiest_second([times[index] for index in detector.ends], 1e-9)
                    for detector in (general_zigs[k], area_zigs[k])]
        if candidate_zigs[k].ambiguous_ends:
            candidate_ends = candidate_zigs[k].ends + candidate_zigs[k].ambiguous_ends
            patterns.append(busiest_second([times[index] for index in candidate_ends], 1e-9))
        pattern = max(patterns, key=lambda result: result[0])
        g = max((classic, pattern), key=lambda result: result[0])
        r = busiest_second([times[index] for index in red_zigs[k].ends], 1e-9)
        # Pattern detectors also fire on movement over fine detail; check.py makes those a look.
        row = {'window': [x % W, y, ww, wh], 'sampling': 'area' if x < W else 'point',
               'general_max_per_s': g[0], 'general_at_s': g[1],
               'classic_max_per_s': classic[0], 'classic_at_s': classic[1],
               'pattern_max_per_s': pattern[0], 'pattern_at_s': pattern[1],
               'red_max_per_s': r[0], 'red_at_s': r[1]}
        rows.append(row)
        if g[0] > 6 or r[0] > 6:
            flagged.append(row)
    gb = max(rows, key=lambda r: r['general_max_per_s'])
    rb = max(rows, key=lambda r: r['red_max_per_s'])
    duration = frames.end() - times[0]
    res = {'video': a.video, 'frames': n, 'fps': fps, 'frame_timing': clock, 'duration_s': round(duration, 3),
           'screened_as': 'fields of an interlaced picture' if fields else 'frames',
           'scan_size': [W, H], 'windows': len(wins),
           'busiest_general': {'transitions_in_1s': gb['general_max_per_s'], 'at_s': gb['general_at_s'],
                               'window': gb['window']},
           'busiest_red': {'transitions_in_1s': rb['red_max_per_s'], 'at_s': rb['red_at_s'], 'window': rb['window']},
           'flagged': flagged, 'verdict': 'FLAGGED' if flagged else 'no candidate flash sequences',
           'limit': 'Screening only; not a Harding FPA, IRIS or PEAT certification.'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, indent=1)
    g, r = res['busiest_general'], res['busiest_red']
    per_s = f'{n / duration:.3g}' if duration > 0 else '?'
    if fields:
        head = f'{n} fields, {per_s} a second (interlaced, screened field by field)'
    elif clock == 'constant':
        head = f'{n} frames at {fps:g} fps'
    else:
        head = f'{n} frames at {per_s} fps on average (variable frame timing)'
    print(f"{os.path.basename(a.video)}: {head}; busiest second: general {g['transitions_in_1s']} "
          f"transitions (at {g['at_s']} s), red {r['transitions_in_1s']} (at {r['at_s']} s); {res['verdict']}")
    return 1 if flagged else 0


if __name__ == '__main__':
    sys.exit(main())
