#!/usr/bin/env python3
"""Shared local render primitives. Not a film quality judgement.

Used by film_render.py and motion_blur.py; needs numpy, Pillow and FFmpeg.
This module has no standalone operation. --help documents it; exit 0.
"""
import argparse
import bisect
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import http.server
import socketserver

try:
    import numpy as np
    from PIL import Image, ImageFilter
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

COLOUR = ('scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,'
          'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv')
LUT = np.arange(256, dtype=np.float32) / 255
LUT = np.where(LUT <= 0.04045, LUT / 12.92, ((LUT + 0.055) / 1.055) ** 2.4)
# H.264 Table A-1 MaxBR (kbit/s), MaxCPB (kbit), before the High-profile 1.25 factor.
H264_VBV = {
    '1.0': (64, 175), '1b': (128, 350), '1.1': (192, 500),
    '1.2': (384, 1000), '1.3': (768, 2000), '2.0': (2000, 2000),
    '2.1': (4000, 4000), '2.2': (4000, 4000), '3.0': (10000, 10000),
    '3.1': (14000, 14000), '3.2': (20000, 20000), '4.0': (20000, 25000),
    '4.1': (50000, 62500), '4.2': (50000, 62500), '5.0': (135000, 135000),
    '5.1': (240000, 240000), '5.2': (240000, 240000), '6.0': (240000, 240000),
    '6.1': (480000, 480000), '6.2': (800000, 800000)}


class LocalServer(http.server.ThreadingHTTPServer):
    """A loopback HTTP server that binds without HTTPServer's reverse-DNS lookup of its own host
    (socket.getfqdn), which can take tens of seconds on macOS."""

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    return candidate if candidate and (os.path.isfile(candidate) or shutil.which(candidate)) else (
        None if candidate else shutil.which(name))


def overlay_probe(filename):
    """How a moving overlay reads a video, shared by cut.py check and assemble.py: its first video stream's size,
    frame rate (r_frame_rate, a Fraction), pixel format, whether it has transparency, and whether that needs the libvpx
    decoder (FFmpeg reports VP9 with alpha as yuv420p plus an alpha_mode tag). ValueError when it cannot be read."""
    ffprobe = find_tool('ffprobe')
    if not ffprobe:
        raise ValueError('ffprobe is required to read a moving overlay')
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                             'stream=width,height,pix_fmt,r_frame_rate,codec_name:stream_tags=alpha_mode', '-of',
                             'json', str(filename)], capture_output=True, text=True, encoding='utf-8', errors='replace')
    streams = json.loads(result.stdout or '{}').get('streams') if not result.returncode else None
    if not streams:
        raise ValueError(f'cannot read the moving overlay {Path(filename).name}: {result.stderr.strip()[-300:]}')
    stream = streams[0]
    pixels = stream.get('pix_fmt', '')
    tags = {key.lower(): value for key, value in (stream.get('tags') or {}).items()}
    vp9 = stream.get('codec_name') == 'vp9' and str(tags.get('alpha_mode')) == '1'
    alpha = vp9 or bool(re.search(r'(rgba|bgra|argb|abgr|gbrap|yuva|^ya)', pixels))
    return {'size': (int(stream['width']), int(stream['height'])), 'pix_fmt': pixels, 'vp9': vp9, 'alpha': alpha,
            'rate': Fraction(str(stream.get('r_frame_rate', '0/1')))}


def display_geometry(stream):
    """Describe the square-pixel canvas after FFmpeg's right-angle autorotation."""
    coded_width, coded_height = int(stream['width']), int(stream['height'])
    if coded_width <= 0 or coded_height <= 0:
        raise ValueError('invalid coded picture dimensions')
    raw_sar = stream.get('sample_aspect_ratio')
    assumed = raw_sar in (None, '', 'N/A', '0:1', '0/1', '0:0', '0/0')
    try:
        sar = Fraction(str(raw_sar).replace(':', '/')) if not assumed else Fraction(1)
    except (ValueError, ZeroDivisionError) as error:
        raise ValueError('invalid sample aspect ratio: ' + str(raw_sar)) from error
    if sar <= 0:
        raise ValueError('sample aspect ratio must be positive')
    tag = (stream.get('tags') or {}).get('rotate')
    rotations = [] if tag is None else [float(tag)]
    for side in stream.get('side_data_list', []):
        if side.get('rotation') is not None:
            rotations.append(float(side['rotation']))
        matrix = side.get('displaymatrix')
        if matrix:
            try:
                rows = [[int(number) for number in row.split(':', 1)[1].split()]
                        for row in matrix.splitlines() if ':' in row]
                a, b = rows[0][:2]
                c, d = rows[1][:2]
                magnitude = max(abs(a), abs(b), abs(c), abs(d))
                if (not magnitude or a * d - b * c <= 0 or abs(a * c + b * d) > magnitude * magnitude * .001
                        or abs((a * a + b * b) - (c * c + d * d)) > magnitude * magnitude * .001):
                    raise ValueError('mirrored or non-orthogonal display matrix')
            except (IndexError, TypeError, ValueError) as error:
                raise ValueError('unsupported display matrix; normalize the source before editing') from error
    if any(not math.isfinite(value) for value in rotations):
        raise ValueError('non-finite display rotation')
    rounded = [round(value / 90) * 90 % 360 for value in rotations]
    if any(abs(value / 90 - round(value / 90)) > .001 for value in rotations) or len(set(rounded)) > 1:
        raise ValueError('unsupported or conflicting display rotation; normalize the source before editing')
    rotation = rounded[-1] if rounded else 0
    square_width = max(2, round(coded_width * float(sar) / 2) * 2)
    square_height = max(2, round(coded_height / 2) * 2)
    width, height = ((square_height, square_width) if rotation % 180 else (square_width, square_height))
    if max(width, height) > 65536:
        raise ValueError('display dimensions are too large after applying sample aspect ratio')
    return {'width': width, 'height': height, 'coded_width': coded_width, 'coded_height': coded_height,
            'sample_aspect_ratio': str(sar), 'sar_assumed_square': assumed, 'rotation_degrees': rotation,
            'coordinate_space': 'autorotated square pixels', 'geometry_version': 1}


def source_seek_safe(filename):
    """Avoid random seeks through MP4 edit lists that splice or delay presentation."""
    try:
        with open(filename, 'rb') as source:
            source.seek(0, os.SEEK_END)
            length = source.tell()
            source.seek(0)
            header = source.read(8)
            if len(header) < 8:
                return False
            kind = header[4:8]
            mp4 = kind in (b'ftyp', b'moov', b'mdat', b'free', b'wide', b'skip', b'moof', b'styp', b'sidx')
            if not mp4:
                return os.path.splitext(str(filename))[1].lower() not in ('.mp4', '.m4v', '.mov', '.m4a', '.3gp')

            def boxes(start, end):
                while start + 8 <= end:
                    source.seek(start)
                    size, typ = struct.unpack('>I4s', source.read(8))
                    head = 8
                    if size == 1:
                        size = struct.unpack('>Q', source.read(8))[0]
                        head = 16
                    elif size == 0:
                        size = end - start
                    if size < head or start + size > end:
                        raise ValueError('invalid movie box')
                    yield typ, start + head, start + size
                    start += size
                if start != end:
                    raise ValueError('truncated movie box')

            movies = [(a, b) for typ, a, b in boxes(0, length) if typ == b'moov']
            if len(movies) != 1:
                return False
            for typ, start, end in boxes(*movies[0]):
                if typ in (b'cmov', b'mvex'):
                    return False
                if typ != b'trak':
                    continue
                for child, a, b in boxes(start, end):
                    if child != b'edts':
                        continue
                    for edit, c, d in boxes(a, b):
                        if edit != b'elst':
                            continue
                        source.seek(c)
                        raw = source.read(8)
                        if len(raw) != 8 or raw[0] not in (0, 1):
                            return False
                        count = struct.unpack('>I', raw[4:])[0]
                        size = 20 if raw[0] else 12
                        if count != 1 or c + 8 + count * size > d:
                            return False
                        if count:
                            entry = source.read(size)
                            media_time = struct.unpack_from('>q' if raw[0] else '>i', entry,
                                                            8 if raw[0] else 4)[0]
                            rate = struct.unpack_from('>hh', entry, size - 4)
                            if media_time < 0 or rate != (1, 0):
                                return False
            return True
    except (OSError, ValueError, struct.error, OverflowError):
        return False


# A stream's header and its decoded frames differ by a frame or two in a healthy file: decoding has stopped short only
# when it falls more than this, and more than two and a half frames, before where it was expected to end.
END_SLACK_S = 0.1


def decoded_short(expected, decoded, frame=0.0):
    """Whether decoding stopped measurably before `expected`."""
    return expected - decoded > max(END_SLACK_S, 2.5 * frame)


def picture_goes_on(ffprobe, filename, origin, moment):
    """Whether the video stream still has a packet after a source time. A gap in a variable-rate source goes on; the
    end of the picture does not. Reads packets, not frames, so a long source costs a demux and no decode."""
    command = [ffprobe, '-v', 'quiet', '-select_streams', 'v:0', '-show_entries', 'packet=pts_time', '-of', 'csv=p=0']
    if source_seek_safe(filename):
        command[3:3] = ['-read_intervals', f'{origin + moment:.9f}']
    try:
        result = subprocess.run(command + [str(filename)], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=1800)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError('packet scan did not finish within 1800 seconds') from error
    values = (line.strip(' ,') for line in result.stdout.splitlines())
    return any(value.replace('.', '', 1).isdigit() and float(value) - origin > moment + 1e-6 for value in values)


def presentation_frame_before(ffprobe, filename, origin, moment, through=None, return_seek=False):
    """Find the covering frame, checking only selected frames for decoder error flags. A time past the last frame's
    display is covered by nothing, however many frames come before it."""
    limit = max(1.0, moment + 1.0, (through if through is not None else moment) + 1.0)
    seek = max(0.0, moment - 5.0) if source_seek_safe(filename) else 0.0
    while True:
        interval = (f'{origin + seek:.9f}' if seek else '') + f'%{origin + limit:.9f}'
        command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-read_intervals', interval,
                   '-show_frames', '-show_entries',
                   'frame=best_effort_timestamp_time,decode_error_flags,duration_time,pkt_duration_time',
                   '-of', 'json', str(filename)]
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=1800)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError('frame timestamp scan did not finish within 1800 seconds') from error
        if result.returncode:
            raise ValueError('video decoder failed while resolving presentation frames: '
                             + result.stderr.strip()[-500:])
        try:
            rows = [frame for frame in json.loads(result.stdout).get('frames', [])
                    if 'best_effort_timestamp_time' in frame]
            frames = [(float(frame['best_effort_timestamp_time']) - origin, int(frame.get('decode_error_flags', 0)))
                      for frame in rows]
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            raise ValueError('invalid frame timestamp or decoder error flags') from error
        frames = [(time, flags) for time, flags in frames if math.isfinite(time)]
        earlier = [time for time, _ in frames if time <= moment + 1e-6]
        if not earlier and seek:
            seek = 0.0
            continue
        if earlier:
            selected = max(earlier)
            if selected == frames[-1][0]:
                last = rows[-1]
                try:
                    held = float(last.get('duration_time', last.get('pkt_duration_time', 0)))
                except (TypeError, ValueError):
                    held = 0.0
                reach = selected + max(held, selected - frames[-2][0] if len(frames) > 1 else 0.0)
                if moment >= reach - 1e-6 and not picture_goes_on(ffprobe, filename, origin, moment):
                    raise ValueError(f'no picture frame covers source time {moment:.6f} in {filename}: the picture '
                                     f'ends at {reach:.6f} s; choose an earlier in-point')
        elif frames and 0 <= frames[0][0] - moment <= .5 + 1e-6:
            selected = frames[0][0]
        else:
            raise ValueError(f'no picture frame covers source time {moment:.6f} in {filename}; '
                             'choose a later in-point or normalize the source')
        end = through if through is not None else moment + 1e-6
        if any(flags and (abs(time - selected) <= 1e-6 or selected <= time < end) for time, flags in frames):
            raise ValueError('video decoder reported a damaged frame in the requested picture range')
        # FFmpeg's accurate input seek may discard frames before the seek time.
        seek = max(0.0, min(seek, selected - 2.0))
        return (selected, seek) if return_seek else selected


def free_memory():
    """Available physical bytes, measured once for the whole skill in setup.py (Windows, macOS's vm_stat, Linux's
    MemAvailable), or None where the system does not say."""
    spec = importlib.util.spec_from_file_location('lf_common_setup', Path(__file__).with_name('setup.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.free_memory()


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def version(exe):
    r = subprocess.run([exe, '-version'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return (r.stdout or r.stderr).splitlines()[0]


def sample_times(t, fps, duration, cuts=(), smears=(), fast=(), shutter=180, samples=4, maximum=32):
    factor = max([1.0] + [float(f) for a, b, f in smears if a <= t < b])
    count = min(maximum, max(samples, math.ceil(samples * factor),
                             max([1] + [int(n) for a, b, n in fast if a <= t < b])))
    if count == 1 or shutter == 0:
        return [t]
    exposure = shutter / 360 / fps * factor
    lo, hi = max(0.0, t - exposure / 2), min(duration, t + exposure / 2)
    # bisect_right makes a frame exactly at a cut belong to the arriving shot.
    i = bisect.bisect_right(cuts, t)
    left, right = cuts[i-1] if i else 0.0, cuts[i] if i < len(cuts) else duration
    length = min(hi - lo, right - left)
    lo = max(left, min(lo, right - length))
    return [lo + (k + 0.5) * length / count for k in range(count)]


def validate_timeline(info):
    for key in ('width', 'height', 'fps', 'duration', 'frames'):
        v = info.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v <= 0:
            raise ValueError('invalid info.' + key)
    if any(int(info[k]) != info[k] for k in ('width', 'height', 'frames')):
        raise ValueError('dimensions and frames must be integers')
    if abs(info['frames'] - math.floor(info['duration'] * info['fps'] + 0.5)) > 0:
        raise ValueError('info.frames must equal round(duration * fps)')
    cuts = info.get('cuts', [])
    if cuts != sorted(set(cuts)) or any(not math.isfinite(c) or not 0 < c < info['duration'] for c in cuts):
        raise ValueError('cuts must be sorted, unique and inside the film')
    for key in ('smears', 'fast'):
        for row in info.get(key, []):
            if (len(row) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in row)
                    or not 0 <= row[0] < row[1] <= info['duration'] or row[2] < 1
                    or (key == 'fast' and int(row[2]) != row[2])):
                raise ValueError('invalid info.' + key)


def linear(rgb):
    return LUT[rgb]


def finish(avg, index, blend='linear', bloom=0, threshold=0.8, radii=(3, 12), grain=0, dither=True):
    """avg is float32 in [0,1]. Grain is Gaussian RMS in encoded 8-bit levels, shared by RGB.

    Bloom uses a quarter-size linear-light highlight mask, two Gaussian lobes, and additive RGB.
    Only its low-resolution blur masks are 8-bit; the accumulation stays float32.
    """
    if blend == 'gamma' and bloom:
        avg = np.where(avg <= .04045, avg / 12.92, ((avg + .055) / 1.055) ** 2.4).astype(np.float32)
    if bloom:
        h, w = avg.shape[:2]
        small = np.stack([np.asarray(Image.fromarray(avg[:, :, c]).resize(
            (max(1, w // 4), max(1, h // 4)), Image.Resampling.BOX)) for c in range(3)], axis=2)
        lum = small @ np.array([.2126, .7152, .0722], np.float32)
        small *= np.maximum(lum - threshold, 0)[:, :, None] / np.maximum(lum[:, :, None], 1e-8)
        for c in range(3):
            mask = Image.fromarray(np.uint8(np.clip(small[:, :, c] * 255, 0, 255)))
            glow = sum(np.asarray(mask.filter(ImageFilter.GaussianBlur(r)).resize(
                (w, h), Image.Resampling.BILINEAR), dtype=np.float32) for r in radii) / (2 * 255)
            avg[:, :, c] += bloom * glow
    if blend == 'linear' or bloom:
        avg = np.where(avg <= .0031308, avg * 12.92, 1.055 * np.maximum(avg, 0) ** (1 / 2.4) - .055)
    avg *= 255
    rng = np.random.default_rng(index)
    if grain:
        avg += rng.normal(0, grain, avg.shape[:2]).astype(np.float32)[:, :, None]
    elif dither:
        avg += rng.uniform(-.5, .5, avg.shape[:2]).astype(np.float32)[:, :, None]
    return np.clip(np.floor(avg + .5), 0, 255).astype(np.uint8)


def auto_level(w, h, fps):
    # H.264 frame size and macroblocks/second, including portrait shapes.
    mb = math.ceil(w / 16) * math.ceil(h / 16)
    for level, size, rate in [('3.0', 1620, 40500), ('3.1', 3600, 108000),
                              ('3.2', 5120, 216000), ('4.0', 8192, 245760),
                              ('4.2', 8704, 522240), ('5.0', 22080, 589824),
                              ('5.1', 36864, 983040), ('5.2', 36864, 2073600),
                              ('6.0', 139264, 4177920), ('6.1', 139264, 8355840), ('6.2', 139264, 16711680)]:
        if mb <= size and mb * fps <= rate:
            return level
    raise ValueError('size/rate exceeds supported H.264 levels')


def h264_args(w, h, fps, crf=14, level=None, preview=False):
    """FFmpeg output options for the delivery H.264 encode from RGB input: BT.709 matrix and tags, High
    profile, an explicit level with its VBV limits, closed two-second GOPs and fast start."""
    if w % 2 or h % 2:
        raise ValueError(f'H.264 4:2:0 needs even dimensions, not {w}x{h}')
    level = str(level or auto_level(w, h, fps))
    key = level.lower()
    if key != '1b':
        number = float(key)
        key = f'{number / 10 if number >= 10 else number:.1f}'
    if key not in H264_VBV:
        raise ValueError('unsupported H.264 level: ' + level)
    maxrate, bufsize = H264_VBV[key]
    return ['-vf', COLOUR, '-c:v', 'libx264', '-profile:v', 'high', '-preset',
            'veryfast' if preview else 'slow', '-crf', str(crf), '-level:v', level,
            '-maxrate', str(maxrate * 1250), '-bufsize', str(bufsize * 1250),
            '-g', str(max(1, round(fps * 2))), '-flags', '+cgop', '-x264-params', 'open-gop=0',
            '-threads', '1', '-movflags', '+faststart', '-f', 'mp4']


def output_size(w, h, res=None):
    """The encoded size for a CSS size: --res is the output's short side (720 gives 1280x720 from
    1920x1080 and 720x1280 from 1080x1920); without it the size is the one given."""
    if not res:
        return w, h
    scale = res / min(w, h)
    return round(w * scale), round(h * scale)


def even_res_near(w, h, res):
    """The nearest --res that gives even sides for this size, or None within 64 lines."""
    for step in range(1, 65):
        for cand in (res - step, res + step):
            if cand >= 2 and all(side % 2 == 0 for side in output_size(w, h, cand)):
                return cand
    return None


NTSC_BASES = (24, 30, 48, 60, 120)


def exact_rate(value):
    """A frame rate as an exact fraction. A fraction ("30000/1001", or a Fraction) or an integer is kept as given. A
    decimal (29.97, "29.97" or 29.97002997) within 0.005 of an NTSC rate (23.976 or 23.98, 29.97, 47.952, 59.94,
    119.88) means that rate, never the decimal itself, whose stream rate (2997/100) an editing application reads as
    non-standard; other decimals keep their value."""
    try:
        if isinstance(value, str):
            text = value.strip()
            rate = Fraction(text)
            decimal = '/' not in text
        else:
            # A float's shortest repr is the decimal it was written as (29.97, not its binary approximation).
            rate = Fraction(repr(float(value))) if isinstance(value, float) else Fraction(value)
            decimal = isinstance(value, float)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        raise ValueError(f'not a frame rate: {value!r}')
    if not 0 < rate < 1000:
        raise ValueError(f'frame rate must be positive and below 1000: {value!r}')
    if decimal:
        for base in NTSC_BASES:
            ntsc = Fraction(base * 1000, 1001)
            if abs(rate - ntsc) < Fraction(5, 1000):
                return ntsc
    return rate


class Encoder:
    def __init__(self, ffmpeg, path, w, h, fps, crf=14, level=None, preview=False, lossless=False):
        self.log = tempfile.TemporaryFile()
        rate = exact_rate(fps)
        cmd = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{w}x{h}', '-r', f'{rate.numerator}/{rate.denominator}', '-i', 'pipe:0', '-an']
        if lossless:
            # FFV1 in Matroska preserves all RGB bytes (no YUV subsampling or matrix round-trip).
            cmd += ['-c:v', 'ffv1', '-level', '3', '-pix_fmt', 'bgr0', '-threads', '1', '-f', 'matroska']
        else:
            cmd += h264_args(w, h, fps, crf, level, preview)
        self.command = cmd + [str(path)]
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)

    def write(self, rgb):
        try:
            self.proc.stdin.write(rgb.tobytes())
        except BrokenPipeError:
            self.close()
            raise RuntimeError('encoder pipe closed')

    def close(self):
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
        code = self.proc.wait()
        self.log.seek(0)
        message = self.log.read().decode('utf-8', 'replace')
        self.log.close()
        if code:
            raise RuntimeError('FFmpeg encode failed: ' + message[-1500:])

    def abort(self):
        # Close stdin first: on Linux and macOS, FFmpeg blocked reading a pipe can outlive SIGTERM, and an
        # unbounded wait then hangs the caller (Windows' terminate is a hard kill, which hid this).
        if not self.proc.stdin.closed:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if not self.log.closed:
            self.log.close()


def decoded_count(ffprobe, path):
    r = subprocess.run([ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                        '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(path)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError('output could not be decoded: ' + r.stderr[-500:])
    return int(json.loads(r.stdout)['streams'][0]['nb_read_frames'])


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
