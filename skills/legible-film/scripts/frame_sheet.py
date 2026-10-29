#!/usr/bin/env python3
"""Contact sheets of exact frames, each labelled with its timestamp and frame number.

Use it to look at a film you cannot play: an overview of the whole cut, dense windows
around transitions, or chosen moments at the size a viewer will see them.

  python frame_sheet.py film.mp4 --every 0.5 --out qa/overview.png          # whole film, 2 frames a second
  python frame_sheet.py film.mp4 --around 12.0,19.5 --span 1.6 --rate 20 --out qa/joins.png
  python frame_sheet.py film.mp4 --at 2.0,7.5,11.0 --width 384 --out qa/phone.png   # phone-feed width
  python frame_sheet.py film.mp4 --frames 118-124 --width 960 --out qa/f118.png    # consecutive frames

A quick first pass reads every frame's presentation time, so a time picks the frame on screen at
that moment even when frame timing varies (screen recordings, GIFs); frames are then extracted by
index, and every label shows the frame's decoded time from the start of the film, so a label never
claims a time the frame does not have. Tiles are scaled to --width (the viewing-size check: a
1920-wide film shown 384 px wide is at one-fifth scale). Labels sit above each tile, never on the
picture. Needs Pillow and FFmpeg. Exit code 0 when the sheet is written, 2 on error.
Use --max-width and --max-height to paginate without shrinking tiles; --single writes
individual timestamped PNGs. Budgets too small for one labelled tile exit 2.
A sheet shows selected instants; it does not show motion between them, rhythm or sound.
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
from fractions import Fraction

PTS = re.compile(r'pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    sys.exit('frame_sheet.py needs Pillow: pip install Pillow')


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


def probe(ffprobe, path):
    """(width, height, nominal frame rate or None); exits 2 when the file has no readable video."""
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,avg_frame_rate,r_frame_rate', '-of', 'json', path],
                       capture_output=True, text=True)
    streams = json.loads(r.stdout or '{}').get('streams') if r.returncode == 0 else None
    if not streams:
        fail(f'cannot read {path}: ' + (r.stderr.strip().splitlines() or ['no video stream'])[-1])
    s = streams[0]
    fps = None
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            value = Fraction(s.get(key, '0/0'))
            if value > 0:
                fps = value
                break
        except (ValueError, ZeroDivisionError):
            continue
    return int(s['width']), int(s['height']), fps


def frame_times(ffmpeg, path):
    """Every decoded frame's time on the film clock (seconds from the start of the file), from a small fast decode."""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', path, '-map', '0:v:0',
                        '-vf', 'scale=32:-2,showinfo', *passthrough(ffmpeg), '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    pts = [float(m.group(1)) for line in r.stderr.splitlines() if 'showinfo' in line
           for m in [PTS.search(line)] if m]
    if r.returncode or not pts:
        fail('ffmpeg could not decode the video: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
    return pts


def fail(message):
    print(f'frame_sheet.py: {message}', file=sys.stderr)
    sys.exit(2)


def parse_list(text):
    return [float(x) for x in text.split(',') if x.strip()]


def label_font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('video')
    p.add_argument('--out', required=True, help='output PNG; several sheets get -2, -3 ... suffixes')
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--every', type=float, help='one frame every N seconds')
    mode.add_argument('--at', help='comma-separated times in seconds')
    mode.add_argument('--around', help='comma-separated centre times; see --span and --rate')
    mode.add_argument('--frames', help='frame range A-B (0-based, inclusive), e.g. 118-124')
    p.add_argument('--span', type=float, default=1.6, help='window length in seconds for --around')
    p.add_argument('--rate', type=float, default=20.0, help='frames per second sampled inside each --around window')
    p.add_argument('--width', type=int, default=320, help='tile width in pixels (384 approximates a phone feed)')
    p.add_argument('--cols', type=int, default=0,
                   help='tiles per row; default up to 8 for tiles 400 px wide or less, otherwise up to 4')
    p.add_argument('--per-sheet', type=int, default=64)
    p.add_argument('--max-width', type=int, help='maximum sheet width in pixels')
    p.add_argument('--max-height', type=int, help='maximum sheet height in pixels')
    p.add_argument('--single', action='store_true', help='write timestamped individual PNGs at tile width')
    p.add_argument('--keep-frames', help='also save each full-size frame into this folder')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()

    if (a.width <= 0 or a.per_sheet <= 0 or a.cols < 0 or
            any(v is not None and v <= 0 for v in (a.max_width, a.max_height))):
        p.error('width, per-sheet and budgets must be positive; cols must be nonnegative')
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        fail('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)')
    try:
        at = parse_list(a.at or a.around or '0')
    except ValueError:
        p.error('--at and --around take comma-separated seconds, e.g. 2.0,7.5')
    w0, h0, fps = probe(ffprobe, a.video)
    clock = frame_times(ffmpeg, a.video)
    total = len(clock)

    def index(t):
        """The frame on screen at time t: the last one whose presentation time is not after t."""
        return min(max(bisect.bisect_right(clock, t + 1e-6) - 1, 0), total - 1)

    if a.every is not None:
        if not math.isfinite(a.every) or a.every <= 0:
            p.error('--every needs a positive number of seconds')
        wanted = [index(k * a.every) for k in range(int(clock[-1] / a.every) + 1)]
    elif a.at:
        wanted = [index(t) for t in at]
    elif a.around:
        wanted = []
        for c in at:
            n = max(1, int(math.floor(a.span * a.rate)))
            wanted += [index(c - a.span / 2 + k / a.rate) for k in range(n + 1)]
    else:
        m = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', a.frames)
        if not m:
            p.error('--frames needs A-B')
        wanted = list(range(int(m.group(1)), min(int(m.group(2)), total - 1) + 1))
    wanted = sorted(set(wanted))
    if not wanted:
        fail(f'no frames selected (the film has {total} frames)')
    if len(wanted) > 600:
        fail(f'{len(wanted)} frames requested; narrow the selection (limit 600)')

    with tempfile.TemporaryDirectory() as tmp:
        select = '+'.join(f'eq(n\\,{n})' for n in wanted)
        vf = f"select='{select}',showinfo"
        cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', a.video, '-map', '0:v:0', '-vf', vf,
               *passthrough(ffmpeg), os.path.join(tmp, 'f_%05d.png')]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            fail('ffmpeg failed: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
        files = sorted(f for f in os.listdir(tmp) if f.startswith('f_'))
        times = [clock[n] for n in wanted]
        if a.keep_frames:
            os.makedirs(a.keep_frames, exist_ok=True)
        tiles = []
        tw = a.width
        th = max(2, int(round(tw * h0 / w0)))
        for i, name in enumerate(files):
            n = wanted[i] if i < len(wanted) else None
            t = times[i] if i < len(times) else float('nan')
            with Image.open(os.path.join(tmp, name)) as im:
                frame = im.convert('RGB')
            if a.keep_frames:
                frame.save(os.path.join(a.keep_frames, f'frame-{n:06d}-at-{t:.3f}s.png'))
            tiles.append((n, t, frame.resize((tw, th), Image.LANCZOS)))
            frame.close()

    if len(tiles) != len(wanted):
        print(f'warning: asked for {len(wanted)} frames, decoded {len(tiles)}; labels use decoded times',
              file=sys.stderr)
    cols = a.cols or max(1, min(len(tiles), 8 if tw <= 400 else 4))
    font = label_font(max(11, min(18, tw // 22)))
    pad, label_h = 6, max(16, min(24, tw // 16))
    if a.max_width is not None:
        fit = (a.max_width - pad) // (tw + pad)
        if fit < 1:
            fail('max-width cannot fit one tile')
        cols = min(cols, fit)
    page_size = a.per_sheet
    if a.max_height is not None:
        fit = (a.max_height - pad) // (th + label_h + pad)
        if fit < 1:
            fail('max-height cannot fit one labelled tile')
        page_size = min(page_size, fit * cols)
    outputs = []
    base, ext = os.path.splitext(a.out)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    if a.single:
        for n, t, im in tiles:
            path = f'{base}-frame-{n:06d}-at-{t:.3f}s.png'
            im.save(path)
            outputs.append(path)
        print(f'{len(outputs)} individual frames -> ' + ', '.join(outputs))
        return
    for s in range(0, len(tiles), page_size):
        chunk = tiles[s:s + page_size]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), (28, 28, 30))
        draw = ImageDraw.Draw(sheet)
        for i, (n, t, im) in enumerate(chunk):
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + label_h + pad)
            draw.text((x + 2, y + 1), f'{t:.3f}s  #{n}', fill=(235, 235, 235), font=font)
            sheet.paste(im, (x, y + label_h))
        path = a.out if s == 0 else f'{base}-{s // page_size + 1}{ext or ".png"}'
        sheet.save(path)
        outputs.append(path)
    rate = f'{float(fps):g} fps' if fps else 'unknown frame rate'
    print(f'{len(tiles)} frames from {os.path.basename(a.video)} ({w0}x{h0} @ {rate}) '
          f'as {tw}x{th} tiles -> ' + ', '.join(outputs))


if __name__ == '__main__':
    main()
