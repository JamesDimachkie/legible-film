#!/usr/bin/env python3
"""Check that an approved text or static region survives its whole interval.

  python region_check.py film.mp4 --region 80,900,700,100 --interval 12-16 --reference qualifier.png
  python region_check.py film.mp4 --region .04,.83,.36,.10 --fractions --interval 12,16 --reference-time 13
  python region_check.py film.mp4 --region 80,900,700,100 --interval 12-16 --reference-video approved.mp4 --reference-time 13 --json qa/region.json

The interval is START-END (or START,END), seconds on the file's presentation clock,
end exclusive. Every decoded frame displayed during any part of it is checked,
including the frame already on screen at START. Frame numbers are zero based;
times come from each frame's own presentation timestamp, never frame number / fps.
Fractional x,y,w,h are relative to each video's size; PNGs must already be crops
of exactly the delivered region's pixel size. No registration, tracking or resizing.

Measure: reference ink is luminance >= --ink-contrast (40/255) away from the crop's
median background. Ink retention is the share of those pixels within --pixel-tolerance
(32/255) of their reference luminance. Structure is global SSIM over the ink bounding
box plus a two-pixel margin (C1=(.01*255)^2, C2=(.03*255)^2), clipped to [0,1].
The presence score is min(ink retention, structure); any score below --threshold
(default .95) fails. A flat reference or fewer than 16 ink pixels cannot be checked.
These are encoding-noise tolerances, not a readability standard. Use a tight region
for each required qualifier: a small lost word in a large crop can escape the threshold.
Intended motion, fades, background changes and occlusion may be flagged too.

Prints every frame's scores, failing frame numbers and contiguous displayed time
ranges, and whether the region survives. Presence only: not OCR, reading speed,
meaning, correct copy, colour fidelity or a person's viewing approval.
Needs numpy, Pillow, FFmpeg and ffprobe. Exit 0 nothing to fix, 1 inspect or fix
(one or more frames below threshold), 2 could not run or interval not fully covered.
"""

import argparse
import bisect
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import numpy as np
    from PIL import Image
except ImportError:  # pragma: no cover
    print('region_check.py needs numpy and Pillow: pip install numpy Pillow', file=sys.stderr)
    sys.exit(2)


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def passthrough(ffmpeg):
    head = subprocess.run([ffmpeg, '-hide_banner', '-version'], capture_output=True, text=True).stdout
    m = re.search(r'version n?(\d+)\.(\d+)', head)
    old = m is not None and (int(m.group(1)), int(m.group(2))) < (5, 1)
    return ['-vsync' if old else '-fps_mode', 'passthrough']


def probe(ffprobe, path):
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                        '-show_entries', 'stream=width,height,duration,start_time:format=start_time:'
                        'frame=pts_time,duration_time,pkt_duration_time', '-of', 'json', path],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    data = json.loads(r.stdout or '{}')
    if r.returncode or r.stderr.strip() or not data.get('streams') or not data.get('frames'):
        raise ValueError(f'cannot decode {path}: ' + (r.stderr.strip().splitlines() or ['no video frames'])[-1])
    stream = data['streams'][0]
    origin = float(data.get('format', {}).get('start_time', 0))
    clock = [float(f['pts_time']) - origin for f in data['frames']]
    if not all(math.isfinite(t) for t in clock) or any(b <= a for a, b in zip(clock, clock[1:])):
        raise ValueError('video needs finite, strictly increasing presentation timestamps')
    last = data['frames'][-1]
    duration = float(last.get('duration_time', last.get('pkt_duration_time', 0)))
    end = clock[-1] + duration
    if duration <= 0:
        end = float(stream.get('start_time', origin)) - origin + float(stream.get('duration', 0))
    if end <= clock[-1]:
        raise ValueError('cannot establish the last frame display duration')
    return int(stream['width']), int(stream['height']), clock, end


def region_pixels(text, fractions, width, height):
    values = [float(v) for v in text.split(',')]
    if len(values) != 4 or not all(math.isfinite(v) for v in values):
        raise ValueError('--region needs finite x,y,w,h')
    if fractions:
        values = [v * scale for v, scale in zip(values, (width, height, width, height))]
    elif any(v != int(v) for v in values):
        raise ValueError('pixel regions need integers; use --fractions for relative coordinates')
    x, y, w, h = [int(round(v)) for v in values]
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError('--region is empty or outside the video')
    return x, y, w, h


def crops(ffmpeg, path, region, first, last):
    """Stream only the requested crops; verify byte count and decoder completion."""
    x, y, w, h = region
    graph = f"select='between(n,{first},{last})',crop={w}:{h}:{x}:{y}:exact=1,format=rgb24"
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen([ffmpeg, '-v', 'error', '-nostdin', '-i', path, '-map', '0:v:0',
                                 '-vf', graph, *passthrough(ffmpeg), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                stdout=subprocess.PIPE, stderr=log)
        try:
            for _ in range(last - first + 1):
                raw = proc.stdout.read(w * h * 3)
                if len(raw) != w * h * 3:
                    raise ValueError('incomplete crop decode; the check is unverified')
                yield np.asarray(Image.frombytes('RGB', (w, h), raw).convert('L'), dtype=np.float64)
            extra = proc.stdout.read()
            code = proc.wait()
            log.seek(0)
            errors = log.read().decode(errors='replace').strip()
            if code or extra or errors:
                raise ValueError('crop decode failed: ' + (errors.splitlines() or ['frame count mismatch'])[-1])
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.terminate()
                proc.wait()


def reference_ink(ref, contrast):
    ink = np.abs(ref - np.median(ref)) >= contrast
    yy, xx = np.where(ink)
    if len(xx) < 16:
        raise ValueError('reference has fewer than 16 high-contrast ink pixels; choose a tighter, contrasting crop')
    box = (slice(max(0, yy.min() - 2), min(ref.shape[0], yy.max() + 3)),
           slice(max(0, xx.min() - 2), min(ref.shape[1], xx.max() + 3)))
    return ink, box


def measure(ref, current, ink, box, tolerance):
    retained = float(np.mean(np.abs(current[ink] - ref[ink]) <= tolerance))
    a, b = ref[box], current[box]
    ma, mb = a.mean(), b.mean()
    va, vb = np.mean((a - ma) ** 2), np.mean((b - mb) ** 2)
    cov = np.mean((a - ma) * (b - mb))
    c1, c2 = (.01 * 255) ** 2, (.03 * 255) ** 2
    structure = float(np.clip(((2 * ma * mb + c1) * (2 * cov + c2)) /
                             ((ma * ma + mb * mb + c1) * (va + vb + c2)), 0, 1))
    return retained, structure, min(retained, structure)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video')
    p.add_argument('--region', required=True, help='x,y,w,h in pixels (or fractions with --fractions)')
    p.add_argument('--fractions', action='store_true')
    p.add_argument('--interval', required=True, help='START-END or START,END seconds, end exclusive')
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument('--reference', help='known-good PNG crop, exactly the region size')
    source.add_argument('--reference-time', type=float, help='known-good time in this video or --reference-video')
    p.add_argument('--reference-video')
    p.add_argument('--threshold', type=float, default=.95)
    p.add_argument('--ink-contrast', type=float, default=40)
    p.add_argument('--pixel-tolerance', type=float, default=32)
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    try:
        span = re.fullmatch(r'\s*(\d+(?:\.\d*)?|\.\d+)\s*[-,]\s*(\d+(?:\.\d*)?|\.\d+)\s*', a.interval)
        if not span:
            raise ValueError('--interval needs START-END seconds')
        start, end = map(float, span.groups())
        if not 0 <= start < end or not math.isfinite(end):
            raise ValueError('--interval needs 0 <= START < END')
        if not 0 < a.threshold <= 1 or not 0 < a.ink_contrast <= 255 or not 0 <= a.pixel_tolerance < 255:
            raise ValueError('invalid threshold, ink contrast or pixel tolerance')
        if a.reference_video and a.reference_time is None:
            raise ValueError('--reference-video needs --reference-time')
        ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
        if not ffmpeg or not ffprobe:
            raise ValueError('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)')
        w, h, clock, video_end = probe(ffprobe, a.video)
        region = region_pixels(a.region, a.fractions, w, h)
        if start < clock[0] - 1e-6 or end > video_end + 1e-6:
            raise ValueError('the video does not cover the whole approved interval')
        first = max(0, bisect.bisect_right(clock, start) - 1)
        last = bisect.bisect_left(clock, end) - 1
        if last < first:
            raise ValueError('no displayed frames overlap the requested interval')
        if a.reference:
            with Image.open(a.reference) as im:
                if im.format != 'PNG' or im.size != region[2:]:
                    raise ValueError('reference must be a PNG crop of exactly the region size')
                if im.convert('RGBA').getextrema()[-1] != (255, 255):
                    raise ValueError('reference PNG must be opaque')
                ref = np.asarray(im.convert('RGB').convert('L'), dtype=np.float64)
        else:
            rw, rh, rc, re_ = probe(ffprobe, a.reference_video or a.video)
            if not math.isfinite(a.reference_time) or not rc[0] <= a.reference_time < re_:
                raise ValueError('--reference-time is outside its video')
            rr = region_pixels(a.region, a.fractions, rw, rh)
            if rr[2:] != region[2:]:
                raise ValueError('reference region size differs; supply a same-size reference')
            ri = max(0, bisect.bisect_right(rc, a.reference_time) - 1)
            ref = list(crops(ffmpeg, a.reference_video or a.video, rr, ri, ri))[0]
        ink, box = reference_ink(ref, a.ink_contrast)
        rows = []
        for i, current in enumerate(crops(ffmpeg, a.video, region, first, last), first):
            retained, structural, score = measure(ref, current, ink, box, a.pixel_tolerance)
            rows.append({'frame': i, 'time_s': clock[i],
                         'display_start_s': max(start, clock[i]),
                         'display_end_s': min(end, clock[i + 1] if i + 1 < len(clock) else video_end),
                         'ink_retention': round(retained, 6), 'structure': round(structural, 6),
                         'score': round(score, 6), 'below_threshold': score < a.threshold})
        failed = [r for r in rows if r['below_threshold']]
        runs = []
        for r in failed:
            if runs and r['frame'] == runs[-1]['last_frame'] + 1:
                runs[-1].update(last_frame=r['frame'], end_s=r['display_end_s'], frames=runs[-1]['frames'] + 1)
            else:
                runs.append({'first_frame': r['frame'], 'last_frame': r['frame'], 'start_s': r['display_start_s'],
                             'end_s': r['display_end_s'], 'frames': 1})
        result = {'video': a.video, 'region': region, 'interval_s': [start, end],
                  'reference': a.reference or {'video': a.reference_video or a.video, 'time_s': a.reference_time},
                  'measure': 'min(reference ink retention, ink-box global SSIM)',
                  'threshold': a.threshold, 'pixel_tolerance': a.pixel_tolerance, 'ink_contrast': a.ink_contrast,
                  'ink_pixels': int(ink.sum()), 'frames_checked': len(rows), 'frames': rows,
                  'failing_frames': [r['frame'] for r in failed], 'failing_runs': runs,
                  'survives_whole_interval': not failed,
                  'limit': 'Static-region presence only; not reading speed, meaning or viewing approval.'}
        if a.json:
            with open(a.json, 'w', encoding='utf-8') as fh:
                json.dump(result, fh, indent=1)
        print(f"{os.path.basename(a.video)}: {len(rows)} frames; region "
              + ('survives its whole interval' if not failed else 'DROPS BELOW THRESHOLD'))
        for r in rows:
            print(f"  frame {r['frame']:6d}  {r['time_s']:10.6f} s  ink {r['ink_retention']:.4f}"
                  f"  structure {r['structure']:.4f}  score {r['score']:.4f}"
                  + ('  INSPECT' if r['below_threshold'] else ''))
        for r in runs:
            print(f"  INSPECT frames {r['first_frame']}-{r['last_frame']}: "
                  f"{r['start_s']:.6f}-{r['end_s']:.6f} s (end exclusive)")
        return 1 if failed else 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'region_check.py: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
