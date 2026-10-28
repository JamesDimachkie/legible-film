#!/usr/bin/env python3
"""Find runs of near-empty frames (little edge detail) in a rendered film.

Catches what ffmpeg's blackdetect misses: flat colour fields, a frame whose only content is a
thin line, a scene that failed to draw. Each frame is scaled to 320x180 grey; its detail is the
mean absolute horizontal plus vertical gradient. Frames below --relative x the film's median
detail (default 0.35), or at or below --floor whatever the median (default 0.25, so a render that
is blank throughout is still caught), are near-empty; runs of at least --min-frames are listed
with their times. Times are each frame's own presentation time, so variable frame timing (screen
recordings, GIFs) is reported on the clock it plays on.

  python blank_scan.py film.mp4
  python blank_scan.py film.mp4 --min-frames 2 --ignore 0-0.5,31.8-32 --json qa/blank.json

Designed fades, breaths and wipes will appear: declare them with --ignore (seconds) and inspect
every other run at full size against the last approved export. The measure is brightness
structure after downscaling, not intent: a near-threshold fade can flip between two encodes of
the same picture. Needs numpy and FFmpeg. Exit code 0 when no run lies outside --ignore, 1 when
one does, 2 when the file cannot be scanned.
"""

import argparse
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
    sys.exit('blank_scan.py needs numpy: pip install numpy')

W, H = 320, 180
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


def declared_rate(ffprobe, path):
    """The stream's declared average frame rate, or None when it cannot be read."""
    if not ffprobe:
        return None
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=avg_frame_rate',
                        '-of', 'csv=p=0', path], capture_output=True, text=True)
    num, _, den = r.stdout.strip().partition('/')
    try:
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


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
    p.add_argument('--min-frames', type=int, default=4)
    p.add_argument('--relative', type=float, default=0.35, help='threshold as a fraction of the median detail')
    p.add_argument('--floor', type=float, default=0.25,
                   help='detail at or below this is near-empty whatever the median (0-255 gradient scale)')
    p.add_argument('--ignore', help='designed low-detail ranges in seconds, e.g. 0-0.5,12.1-12.4')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe', help='used only to read the declared frame rate; timing comes from ffmpeg')
    a = p.parse_args()
    try:
        ignore = parse_ranges(a.ignore)
    except ValueError as e:
        p.error(f'--ignore: {e}')
    ffmpeg = find_tool('ffmpeg', a.ffmpeg)
    if not ffmpeg:
        print('ffmpeg is required (PATH, FFMPEG, or --ffmpeg)', file=sys.stderr)
        return 2
    if not os.path.isfile(a.video):
        print(f'blank_scan.py: not a file: {a.video}', file=sys.stderr)
        return 2
    frames = Frames(ffmpeg, a.video, f'scale={W}:{H}:flags=area,format=gray', W * H)
    detail = []
    for buf in frames:
        f = np.frombuffer(buf, np.uint8).reshape(H, W).astype(np.float32)
        detail.append(float(np.abs(np.diff(f, axis=1)).mean() + np.abs(np.diff(f, axis=0)).mean()))
    try:
        times = frames.times(len(detail))
    except RuntimeError as e:
        print(f'blank_scan.py: cannot scan {a.video}: {e}', file=sys.stderr)
        return 2
    d = np.array(detail)
    steps = np.diff(times) if len(times) > 1 else np.zeros(1)
    typical = float(np.median(steps))
    variable = len(times) > 2 and typical > 0 and float(steps.max() - steps.min()) > 0.25 * typical
    # With constant timing, report the stream's declared rate; otherwise the average over the whole run (not one
    # interval: millisecond timestamps alternate 33 and 34 ms at 30 fps).
    span = times[-1] - times[0]
    fps = round((len(times) - 1) / span, 2) if span > 0 else 0.0
    declared_fps = declared_rate(find_tool('ffprobe', a.ffprobe), a.video)
    if declared_fps and not variable:
        fps = round(declared_fps, 3)
    median = float(np.median(d))
    threshold = max(median * a.relative, a.floor)
    near_empty = (d < threshold) | (d <= a.floor)
    runs, i = [], 0
    while i < len(d):
        if near_empty[i]:
            j = i
            while j < len(d) and near_empty[j]:
                j += 1
            if j - i >= a.min_frames:
                start, end = times[i], times[j - 1]
                declared = any(s - 1e-6 <= start and end <= e + 1e-6 for s, e in ignore)
                runs.append({'start_s': round(start, 3), 'end_s': round(end, 3), 'frames': j - i,
                             'min_detail': round(float(d[i:j].min()), 3), 'declared': declared})
            i = j
        else:
            i += 1
    flagged = [r for r in runs if not r['declared']]
    result = {'video': a.video, 'frames': len(d), 'fps': fps,
              'frame_timing': 'variable' if variable else 'constant', 'median_detail': round(median, 3),
              'threshold': round(threshold, 3), 'runs': runs,
              'verdict': f'{len(flagged)} undeclared near-empty run(s) to inspect' if flagged else 'none outside declared ranges'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(result, fh, indent=1)
    rate = f'{fps:g} fps' if not variable else f'about {fps:.3g} fps (variable frame timing)'
    print(f'{os.path.basename(a.video)}: {len(d)} frames at {rate}; median detail {median:.2f}; '
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
