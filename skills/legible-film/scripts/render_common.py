#!/usr/bin/env python3
"""Shared local render primitives. Not a film quality judgement.

Used by film_render.py and motion_blur.py; needs numpy, Pillow and FFmpeg.
This module has no standalone operation. --help documents it; exit 0.
"""
import argparse
import bisect
import ctypes
from fractions import Fraction
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageFilter

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


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    return candidate if candidate and (os.path.isfile(candidate) or shutil.which(candidate)) else (
        None if candidate else shutil.which(name))


def free_memory():
    if os.name == 'nt':
        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (x, ctypes.c_ulonglong) for x in ('total', 'avail', 'page', 'availpage', 'virtual', 'availvirtual', 'ext')]
        status = Status()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError('cannot measure free physical memory')
        return status.avail
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, ValueError, OSError):
        return None


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


class Encoder:
    def __init__(self, ffmpeg, path, w, h, fps, crf=14, level=None, preview=False, lossless=False):
        self.log = tempfile.TemporaryFile()
        rate = Fraction(fps).limit_denominator(1001)
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
        if self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait()
        if not self.proc.stdin.closed:
            self.proc.stdin.close()
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
