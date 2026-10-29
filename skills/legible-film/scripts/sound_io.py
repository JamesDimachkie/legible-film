#!/usr/bin/env python3
"""Shared local audio I/O for the Legible Film sound tools.

Needs numpy and FFmpeg. No network or audio playback. Exit 0 for --help.
The other tools load this sibling by its explicit path, including under Python -I.
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
from pathlib import Path
import numpy as np


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def finite(text):
    value = float(text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError('must be finite')
    return value


def positive(text):
    value = finite(text)
    if value <= 0:
        raise argparse.ArgumentTypeError('must be above zero')
    return value


def run(cmd, data=None):
    r = subprocess.run(cmd, input=data, capture_output=True)
    if r.returncode:
        raise ValueError(r.stderr.decode(errors='replace')[-600:])
    return r


def decode(ffmpeg, path, rate=48000, channels=2, start=0, duration=None):
    cmd = [ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a:0']
    if start:
        cmd += ['-ss', str(start)]
    if duration is not None:
        cmd += ['-t', str(duration)]
    r = run(cmd + ['-ac', str(channels), '-ar', str(rate), '-f', 'f32le', '-'])
    x = np.frombuffer(r.stdout, dtype='<f4').reshape(-1, channels).copy()
    if not len(x) or not np.isfinite(x).all():
        raise ValueError('audio is empty or contains non-finite samples')
    return x


def write_wav(ffmpeg, path, x, rate=48000, floating=False):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    run([ffmpeg, '-v', 'error', '-y', '-f', 'f32le', '-ar', str(rate), '-ac', str(x.shape[1]),
         '-i', '-', '-c:a', 'pcm_f32le' if floating else 'pcm_s24le',
         '-map_metadata', '-1', '-bitexact', str(path)],
        np.asarray(x, dtype='<f4').tobytes())


def db(value):
    return 20 * math.log10(max(float(value), 1e-12))


def level(x):
    return db(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2))) if len(x) else -240.0


def meter(ffmpeg, path, rate=48000):
    raw = isinstance(path, np.ndarray)
    input_args = (['-f', 'f32le', '-ar', str(rate), '-ac', str(path.shape[1]), '-i', '-'] if raw
                  else ['-nostdin', '-i', str(path)])
    r = run([ffmpeg, '-hide_banner'] + input_args + ['-vn', '-af', 'ebur128=peak=true', '-f', 'null', '-'],
            np.asarray(path, dtype='<f4').tobytes() if raw else None)
    text = r.stderr.decode(errors='replace').split('Summary:')[-1]
    def last(pattern):
        hits = re.findall(pattern, text)
        if not hits:
            raise ValueError('FFmpeg did not report a loudness/true-peak summary')
        value = float(hits[-1])
        return value if math.isfinite(value) else None
    return {'integrated_lufs': last(r'I:\s*([-+\w.]+) LUFS'),
            'true_peak_dbtp': last(r'Peak:\s*([-+\w.]+) dBFS')}


def save_json(path, result):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
