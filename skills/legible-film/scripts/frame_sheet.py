#!/usr/bin/env python3
"""Contact sheets of exact frames, each labelled with its timestamp and frame number.

Use it to look at a film you cannot play: an overview of the whole cut, dense windows
around transitions, or chosen moments at the size a viewer will see them.

  python frame_sheet.py film.mp4 --every 0.5 --out qa/overview.png          # whole film, 2 frames a second
  python frame_sheet.py film.mp4 --around 12.0,19.5 --span 1.6 --rate 20 --out qa/joins.png
  python frame_sheet.py film.mp4 --at 2.0,7.5,11.0 --width 384 --out qa/phone.png   # phone-feed width
  python frame_sheet.py film.mp4 --frames 118-124 --width 960 --out qa/f118.png    # consecutive frames

Frames are selected by index in one decode pass, and every label shows the frame's decoded
presentation time, so a label never claims a time the frame does not have. Tiles are scaled to
--width (the viewing-size check: a 1920-wide film shown 384 px wide is at one-fifth scale).
Labels sit above each tile, never on the picture. Needs Pillow and FFmpeg.
A sheet shows selected instants; it does not show motion between them, rhythm or sound.
"""

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover
    sys.exit('frame_sheet.py needs Pillow: pip install Pillow')


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def probe(ffprobe, path):
    out = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                          'stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration',
                          '-of', 'json', path], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    s = data['streams'][0]
    fps = None
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            value = Fraction(s.get(key, '0/0'))
            if value > 0:
                fps = value
                break
        except (ValueError, ZeroDivisionError):
            continue
    duration = None
    for value in (s.get('duration'), data.get('format', {}).get('duration')):
        try:
            duration = float(value)
            break
        except (TypeError, ValueError):
            continue
    frames = int(s['nb_frames']) if str(s.get('nb_frames', '')).isdigit() else None
    if frames is None and fps and duration:
        frames = int(round(duration * float(fps)))
    return int(s['width']), int(s['height']), fps, duration, frames


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
    p.add_argument('--cols', type=int, default=0, help='tiles per row; default picks one')
    p.add_argument('--per-sheet', type=int, default=64)
    p.add_argument('--keep-frames', help='also save each full-size frame into this folder')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()

    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        sys.exit('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)')
    w0, h0, fps, duration, total = probe(ffprobe, a.video)
    if not fps or not total:
        sys.exit('could not read the frame rate or length')
    rate = float(fps)

    def index(t):
        return min(max(int(round(t * rate)), 0), total - 1)

    if a.every:
        step = max(1, int(round(a.every * rate)))
        wanted = list(range(0, total, step))
    elif a.at:
        wanted = [index(t) for t in parse_list(a.at)]
    elif a.around:
        wanted = []
        for c in parse_list(a.around):
            n = max(1, int(math.floor(a.span * a.rate)))
            wanted += [index(c - a.span / 2 + k / a.rate) for k in range(n + 1)]
    else:
        m = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', a.frames)
        if not m:
            p.error('--frames needs A-B')
        wanted = list(range(int(m.group(1)), min(int(m.group(2)), total - 1) + 1))
    wanted = sorted(set(wanted))
    if not wanted:
        sys.exit('no frames selected')
    if len(wanted) > 600:
        sys.exit(f'{len(wanted)} frames requested; narrow the selection (limit 600)')

    with tempfile.TemporaryDirectory() as tmp:
        if a.every:
            select = f'not(mod(n\\,{wanted[1] - wanted[0] if len(wanted) > 1 else 1}))'
        else:
            select = '+'.join(f'eq(n\\,{n})' for n in wanted)
        vf = f"select='{select}',showinfo"
        cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', a.video, '-vf', vf,
               '-fps_mode', 'passthrough', os.path.join(tmp, 'f_%05d.png')]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode and 'fps_mode' in r.stderr:  # ffmpeg older than 5.1
            cmd[cmd.index('-fps_mode')] = '-vsync'
            r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode:
            sys.exit('ffmpeg failed: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
        times = [float(t) for t in re.findall(r'pts_time:\s*(-?[\d.]+)', r.stderr)]
        files = sorted(f for f in os.listdir(tmp) if f.startswith('f_'))
        if a.keep_frames:
            os.makedirs(a.keep_frames, exist_ok=True)
        tiles = []
        tw = a.width
        th = max(2, int(round(tw * h0 / w0)))
        for i, name in enumerate(files):
            n = wanted[i] if i < len(wanted) else None
            t = times[i] if i < len(times) else (n / rate if n is not None else float('nan'))
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
    outputs = []
    base, ext = os.path.splitext(a.out)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    for s in range(0, len(tiles), a.per_sheet):
        chunk = tiles[s:s + a.per_sheet]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), (28, 28, 30))
        draw = ImageDraw.Draw(sheet)
        for i, (n, t, im) in enumerate(chunk):
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + label_h + pad)
            draw.text((x + 2, y + 1), f'{t:.3f}s  #{n}', fill=(235, 235, 235), font=font)
            sheet.paste(im, (x, y + label_h))
        path = a.out if s == 0 else f'{base}-{s // a.per_sheet + 1}{ext or ".png"}'
        sheet.save(path)
        outputs.append(path)
    print(f'{len(tiles)} frames from {os.path.basename(a.video)} ({w0}x{h0} @ {float(fps):g} fps) '
          f'as {tw}x{th} tiles -> ' + ', '.join(outputs))


if __name__ == '__main__':
    main()
