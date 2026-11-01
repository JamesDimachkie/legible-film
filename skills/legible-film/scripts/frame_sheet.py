#!/usr/bin/env python3
"""Contact sheets of decoded frames, labelled with their presentation times.

Use it to look at a film you cannot play: an overview of the whole cut, dense windows
around transitions, or chosen moments at the size a viewer will see them.

  python frame_sheet.py film.mp4 --every 0.5 --out qa/overview.png          # whole film, 2 frames a second
  python frame_sheet.py film.mp4 --around 12.0,19.5 --span 1.6 --rate 20 --out qa/joins.png
  python frame_sheet.py film.mp4 --at 2.0,7.5,11.0 --width 384 --out qa/phone.png   # phone-feed width
  python frame_sheet.py film.mp4 --frames 118-124 --width 960 --out qa/f118.png    # consecutive frames
  python frame_sheet.py insert.mp4 --at 4.20,4.45 --words map/int_01/words.json --offset 300f --out qa/cues.png

--words labels each tile with the word being spoken at that moment on the words' own clock, so a picture made to
land on speech can be inspected against the transcript's timing: decoded time plus --offset (seconds, or frames with
an f suffix at the video's own rate; an insert that starts at source frame 300 takes 300f). It reads a transcript
(map/ALIAS/words.json, transcribe.py's output) or edit-time words (exchange.py words): a list of words, or
{"words": [...]}, each with text (or word), start and end. It labels sheets, not --single frames, and --offset
needs --words. Transcript word times are approximate (often a tenth of a second or more), and a sheet shows
instants: put tiles at the cue times with --at, and leave whether a moment lands on its word to a person listening
at normal speed.

--at and --around seek near each requested window and read the decoded presentation times. --every
and --frames read the whole time sequence. A time picks the last frame at or before it, including
for variable-rate video; times before the first or after the last pick the nearest endpoint. Labels
give the decoded time on the file clock, rounded to microseconds; ~ marks a rounded value. A frame
number appears only after a whole-file read. Tiles are scaled to --width (a 1920-wide film shown
384 px wide is at one-fifth scale). Labels sit above each tile, never on the picture. Needs Pillow
and FFmpeg. Exit code 0 when the sheet is written, 2 on error.
Use --max-width and --max-height to paginate without shrinking tiles; --single writes
individual timestamped PNGs. Budgets too small for one labelled tile exit 2.
A sheet shows selected instants; it does not show motion between them, rhythm or sound.
"""

import argparse
import bisect
from collections import deque
import hashlib
import importlib.util
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from fractions import Fraction

PTS = re.compile(r'\bpts:\s*(-?\d+)\s+pts_time:\s*(-?\d+(?:\.\d+)?(?:e[-+]?\d+)?)')
TIME_BASE = re.compile(r'config in time_base:\s*(\d+)\s*/\s*(\d+)')
SHOW_FRAME = re.compile(r'\bn:\s*\d+\s+pts:')
SEEK_MARGIN = Fraction(2)

_project_spec = importlib.util.spec_from_file_location(
    'lf_project', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py'))
project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(project)
try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print(project.dependency_message('PIL'), file=sys.stderr)
    sys.exit(2)


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


def showinfo_line(line, time_base):
    """Read FFmpeg's selection time and exact rational presentation time from one showinfo line."""
    match = TIME_BASE.search(line)
    if match:
        time_base = Fraction(int(match.group(1)), int(match.group(2)))
    match = PTS.search(line)
    if match and time_base is not None:
        return time_base, (float(match.group(2)), int(match.group(1)) * time_base)
    return time_base, None


def frame_times(ffmpeg, path):
    """Read all frame times; use integer timestamps for selection and labels."""
    r = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', path, '-map', '0:v:0',
                        '-vf', 'scale=32:-2,showinfo', *passthrough(ffmpeg), '-f', 'null', '-'],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    pts = []
    time_base = None
    for line in r.stderr.splitlines():
        if 'showinfo' in line:
            time_base, frame = showinfo_line(line, time_base)
            if frame is not None:
                pts.append(frame)
            elif SHOW_FRAME.search(line):
                fail('ffmpeg did not report a presentation time for a decoded frame')
    if r.returncode or not pts:
        fail('ffmpeg could not decode the video: ' + (r.stderr.strip().splitlines() or ['?'])[-1])
    return pts


def collect_showinfo(pipe, frames, errors):
    """Drain stderr while raw frames are read, so neither FFmpeg pipe can block the other."""
    time_base = None
    try:
        for data in iter(pipe.readline, b''):
            line = data.decode('utf-8', 'replace')
            errors.append(line.strip())
            if 'showinfo' in line:
                time_base, frame = showinfo_line(line, time_base)
                if frame is not None:
                    frames.put(frame)
                elif SHOW_FRAME.search(line):
                    frames.put(None)
    finally:
        frames.put(None)


def window_groups(times):
    """Merge requested points whose decode margins are close enough to share a pass."""
    groups = []
    for time in sorted(times):
        if groups and time - groups[-1][-1] <= 2 * SEEK_MARGIN:
            groups[-1].append(time)
        else:
            groups.append([time])
    return groups


def read_window(ffmpeg, path, seek, times, width, height, accept):
    """Deliver selected frames as they are known, or request an earlier seek when the first is missing."""
    cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats']
    if seek > 0:
        cmd += ['-ss', f'{float(seek):.9f}']
    cmd += ['-copyts', '-start_at_zero', '-i', path, '-map', '0:v:0',
            '-vf', f'scale={width}:{height}:flags=lanczos,showinfo', *passthrough(ffmpeg),
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']
    metadata = queue.Queue()
    errors = deque(maxlen=30)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    reader = threading.Thread(target=collect_showinfo, args=(proc.stderr, metadata, errors), daemon=True)
    reader.start()
    size = width * height * 3
    selected = 0
    previous = None
    done = False
    retry = False
    missing_metadata = False
    aborted = False
    try:
        while True:
            pixels = proc.stdout.read(size)
            if len(pixels) != size:
                break
            stamp = metadata.get()
            if stamp is None:
                missing_metadata = True
                break
            current = (stamp[0], stamp[1], pixels)
            if previous is None and current[1] > times[0] and seek > 0:
                retry = True
                break
            while selected < len(times) and current[1] > times[selected]:
                accept(previous or current)
                selected += 1
            if selected == len(times):
                done = True
                break
            previous = current
    except BaseException:
        aborted = True
        raise
    finally:
        proc.stdout.close()
        if (done or retry or missing_metadata or aborted) and proc.poll() is None:
            proc.kill()
        proc.wait()
        reader.join()
        proc.stderr.close()
    if missing_metadata:
        fail('ffmpeg did not report a presentation time for a decoded frame')
    if not done and not retry and proc.returncode:
        if seek > 0 and previous is None and not selected:
            return False
        fail('ffmpeg could not decode the video: ' + (list(errors) or ['?'])[-1])
    if retry or previous is None and not selected:
        return False
    if selected < len(times):
        accept(previous)
    return True


def window_frames(ffmpeg, path, times, size, tile_size, keep_frames):
    """Decode merged windows, backing up until the first requested frame can be identified."""
    results = []
    seen = set()

    def accept(frame):
        """Save a selected full frame once and retain only its small sheet tile."""
        _, stamp, pixels = frame
        key = (stamp, hashlib.sha256(pixels).digest())
        if key in seen:
            return
        seen.add(key)
        if len(results) >= 600:
            fail('more than 600 frames requested; narrow the selection')
        results.append(frame_tile(None, stamp, pixels, size, tile_size, keep_frames, len(results) + 1))

    for group in window_groups(times):
        margin = SEEK_MARGIN
        while True:
            seek = max(Fraction(0), group[0] - margin)
            if read_window(ffmpeg, path, seek, group, size[0], size[1], accept):
                break
            if seek == 0:
                fail('ffmpeg could not decode a frame for the requested time')
            margin *= 2
    results.sort(key=lambda frame: frame[1])
    return results


def timestamp_text(stamp):
    """Display the decoded time to microseconds, marking a rounded rational time with ~."""
    micros = round(stamp * 1000000)
    sign = '-' if micros < 0 else ''
    seconds, fraction = divmod(abs(micros), 1000000)
    value = f'{sign}{seconds}.{fraction:06d}'.rstrip('0').rstrip('.')
    return ('~' if stamp != Fraction(micros, 1000000) else '') + value + 's'


def frame_filename(number, stamp, tile):
    """Name an exact index when known; otherwise use a sheet tile number, not a guessed index."""
    time = timestamp_text(stamp)
    if number is None:
        return f'frame-tile-{tile:03d}-at-{time}.png'
    return f'frame-{number:06d}-at-{time}.png'


def frame_tile(number, stamp, pixels, size, tile_size, keep_frames, tile):
    """Save the full-size frame when requested and keep only the smaller sheet image in memory."""
    frame = Image.frombytes('RGB', size, pixels)
    if keep_frames:
        path = os.path.join(keep_frames, frame_filename(number, stamp, tile))
        refuse_inputs([path], INPUTS)
        frame.save(path)
    if size != tile_size:
        frame = frame.resize(tile_size, Image.LANCZOS)
    return number, stamp, frame


def frame_label(number, stamp):
    """Describe a tile without claiming an unknown global frame index."""
    time = timestamp_text(stamp)
    return f'{time}  frame' if number is None else f'{time}  #{number}'


def wrap_label(label, font, width):
    """Keep every label inside its tile, including when a narrow tile needs several lines."""
    canvas = ImageDraw.Draw(Image.new('L', (1, 1)))

    def fits(text):
        return canvas.textbbox((0, 0), text, font=font)[2] <= width

    if fits(label):
        return [label]
    lines = []
    line = ''
    for word in label.split():
        candidate = f'{line} {word}' if line else word
        if fits(candidate):
            line = candidate
            continue
        if line:
            lines.append(line)
            line = ''
        for char in word:
            if not fits(char):
                fail('width is too small to display a frame label')
            if line and not fits(line + char):
                lines.append(line)
                line = ''
            line += char
    if line:
        lines.append(line)
    return lines


def fail(message):
    print(f'frame_sheet.py: {message}', file=sys.stderr)
    sys.exit(2)


INPUTS = []  # every file this run reads (the video and --words), set once in main


def refuse_inputs(outputs, inputs):
    """Exit 2 before writing when an output path names a file being read."""
    try:
        project.refuse_overwriting_inputs(outputs, inputs)
    except ValueError as error:
        fail(str(error))


def parse_list(text):
    return [Fraction(x.strip()) for x in text.split(',') if x.strip()]


def read_words(path):
    """Timed words from a transcript or edit-time words file, sorted by start: [(start, end, text)]."""
    try:
        with open(path, 'rb') as stream:
            data = json.loads(stream.read().decode('utf-8-sig'))
    except (OSError, ValueError) as error:
        fail(f'cannot read --words {path}: {error}')
    rows = data.get('words') if isinstance(data, dict) else data
    words = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = str(row.get('text', row.get('word', ''))).strip()
        try:
            start, end = float(row['start']), float(row['end'])
        except (KeyError, TypeError, ValueError):
            continue
        if text and math.isfinite(start) and math.isfinite(end) and end >= start:
            words.append((start, end, text))
    if not words:
        fail(f'--words {path} holds no timed words (a list, or {{"words": [...]}}, with text, start and end)')
    return sorted(words)


def parse_offset(text, fps):
    """--offset as seconds, or as frames with an f suffix at the video's rate: a Fraction of seconds."""
    value = str(text).strip()
    try:
        if value.lower().endswith('f'):
            if not fps:
                fail('--offset in frames needs a video with a known frame rate; give seconds instead')
            return Fraction(int(value[:-1])) / fps
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        fail(f'--offset takes seconds (12.5) or frames with an f suffix (300f), not {text!r}')


def spoken_at(words, moment):
    """What is being said at a moment on the words' clock: the word, or the words either side of a gap."""
    starts = [word[0] for word in words]
    position = bisect.bisect_right(starts, moment) - 1
    clock = f'@{float(moment):.2f}s'
    if position >= 0 and moment < words[position][1]:
        return f'{clock} "{words[position][2]}"'
    before = f'"{words[position][2]}"' if position >= 0 else 'start'
    after = f'"{words[position + 1][2]}"' if position + 1 < len(words) else 'end'
    return f'{clock} between {before} and {after}'


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
    p.add_argument('--words', help='label each tile with the word being spoken then (a transcript or edit-time words)')
    p.add_argument('--offset', default='0', help='--words clock minus the video clock: seconds, or frames as 300f')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    INPUTS[:] = [a.video, a.words]
    refuse_inputs([a.out], INPUTS)

    if (a.width <= 0 or a.per_sheet <= 0 or a.cols < 0 or
            any(v is not None and v <= 0 for v in (a.max_width, a.max_height))):
        p.error('width, per-sheet and budgets must be positive; cols must be nonnegative')
    if a.offset != '0' and not a.words:
        p.error('--offset sets the clock of --words; give --words too')
    if a.words and a.single:
        p.error('--words labels a sheet; --single writes unlabelled frames, so leave one of them out')
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        fail('ffmpeg and ffprobe are required (PATH, FFMPEG/FFPROBE, or --ffmpeg/--ffprobe)')
    try:
        at = parse_list(a.at or a.around or '0')
    except (ValueError, ZeroDivisionError):
        p.error('--at and --around take comma-separated seconds, e.g. 2.0,7.5')
    if a.around and (not math.isfinite(a.span) or not math.isfinite(a.rate) or a.span <= 0 or a.rate <= 0):
        p.error('--span and --rate need positive finite numbers')
    if a.every is not None and (not math.isfinite(a.every) or a.every <= 0):
        p.error('--every needs a positive number of seconds')
    w0, h0, fps = probe(ffprobe, a.video)
    words = read_words(a.words) if a.words else None
    offset = parse_offset(a.offset, fps) if a.words else Fraction(0)
    tw = a.width
    th = max(2, int(round(tw * h0 / w0)))
    sw, sh = (w0 - w0 % 2, h0 - h0 % 2) if a.keep_frames else (tw, th)
    if a.keep_frames:
        os.makedirs(a.keep_frames, exist_ok=True)
    if a.at or a.around:
        times = at
        if a.around:
            span = Fraction(str(a.span))
            rate = Fraction(str(a.rate))
            count = max(1, int(span * rate))
            times = [center - span / 2 + Fraction(k) / rate for center in at for k in range(count + 1)]
        if not times:
            fail('no frames selected')
        frames = window_frames(ffmpeg, a.video, times, (sw, sh), (tw, th), a.keep_frames)
    else:
        clock = frame_times(ffmpeg, a.video)
        total = len(clock)
        selection_clock = [frame[1] for frame in clock]

        def index(t):
            """The last frame whose decoded presentation time is not after t."""
            return min(max(bisect.bisect_right(selection_clock, t) - 1, 0), total - 1)

        if a.every is not None:
            step = Fraction(str(a.every))
            wanted = [index(k * step) for k in range(int(selection_clock[-1] / step) + 1)]
        else:
            match = re.fullmatch(r'\s*(\d+)\s*-\s*(\d+)\s*', a.frames)
            if not match:
                p.error('--frames needs A-B')
            wanted = list(range(int(match.group(1)), min(int(match.group(2)), total - 1) + 1))
        wanted = sorted(set(wanted))
        if not wanted:
            fail(f'no frames selected (the film has {total} frames)')
        if len(wanted) > 600:
            fail(f'{len(wanted)} frames requested; narrow the selection (limit 600)')
        # Stream pixels once, retaining selected indices without a large FFmpeg select expression.
        cmd = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-v', 'error', '-i', a.video, '-map', '0:v:0',
               '-vf', f'scale={sw}:{sh}:flags=lanczos', *passthrough(ffmpeg), '-f', 'rawvideo',
               '-pix_fmt', 'rgb24', 'pipe:1']
        want, last, frames, n = set(wanted), wanted[-1], [], 0
        size = sw * sh * 3
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errors)
            try:
                while n <= last:
                    buf = proc.stdout.read(size)
                    if len(buf) < size:
                        break
                    if n in want:
                        frames.append(frame_tile(n, clock[n][1], buf, (sw, sh), (tw, th),
                                                 a.keep_frames, len(frames) + 1))
                    n += 1
            finally:
                finished = n > last
                proc.stdout.close()
                if finished and proc.poll() is None:
                    proc.kill()
                proc.wait()
            if not finished and proc.returncode:
                errors.seek(0)
                lines = errors.read().decode('utf-8', 'replace').strip().splitlines()
                fail('ffmpeg failed: ' + (lines or ['?'])[-1])
        if len(frames) != len(wanted):
            fail(f'asked for {len(wanted)} frames but decoded {len(frames)}')

    if len(frames) > 600:
        fail(f'{len(frames)} frames requested; narrow the selection (limit 600)')
    tiles = frames
    cols = a.cols or max(1, min(len(tiles), 8 if tw <= 400 else 4))
    font = label_font(max(11, min(18, tw // 22)))
    pad, label_h = 6, max(16, min(24, tw // 16))
    label_lines = []
    line_step = max(10, font.getbbox('0123456789sf#~')[3] + 1)
    if not a.single:
        label_lines = [wrap_label(frame_label(n, t), font, tw - 4)
                       + (wrap_label(spoken_at(words, t + offset), font, tw - 4) if words else [])
                       for n, t, _ in tiles]
        label_h = max(label_h, 2 + line_step * max(len(lines) for lines in label_lines))
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
        paths = [f'{base}-{frame_filename(n, t, tile)}' for tile, (n, t, _) in enumerate(tiles, 1)]
        refuse_inputs(paths, INPUTS)
        for path, (_, _, im) in zip(paths, tiles):
            im.save(path)
            outputs.append(path)
        print(f'{len(outputs)} individual frames -> ' + ', '.join(outputs))
        return
    pages = [a.out if s == 0 else f'{base}-{s // page_size + 1}{ext or ".png"}'
             for s in range(0, len(tiles), page_size)]
    refuse_inputs(pages, INPUTS)
    for s in range(0, len(tiles), page_size):
        chunk = tiles[s:s + page_size]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new('RGB', (cols * (tw + pad) + pad, rows * (th + label_h + pad) + pad), (28, 28, 30))
        draw = ImageDraw.Draw(sheet)
        for i, (n, t, im) in enumerate(chunk):
            x = pad + (i % cols) * (tw + pad)
            y = pad + (i // cols) * (th + label_h + pad)
            for line_number, line in enumerate(label_lines[s + i]):
                draw.text((x + 2, y + 1 + line_number * line_step), line, fill=(235, 235, 235), font=font)
            sheet.paste(im, (x, y + label_h))
        path = pages[s // page_size]
        sheet.save(path)
        outputs.append(path)
    rate = f'{float(fps):g} fps' if fps else 'unknown frame rate'
    print(f'{len(tiles)} frames from {os.path.basename(a.video)} ({w0}x{h0} @ {rate}) '
          f'as {tw}x{th} tiles -> ' + ', '.join(outputs))


if __name__ == '__main__':
    main()
