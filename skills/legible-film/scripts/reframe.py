#!/usr/bin/env python3
"""Propose or inspect a crop path and make a sheet of crop windows.

  python reframe.py source.mp4 --aspect 9:16 --auto --out path.json --sheet crop.png
  python reframe.py source.mp4 --aspect 1:1 --path path.json --sheet check.png

The measured region is sustained motion and detail, not a semantic subject detector.
Flags and sheets need review; they do not prove that the intended subject is visible.
Needs numpy, Pillow, FFmpeg and ffprobe. Exit 0 for no flags, 1 for flags, 2 on error.
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motion_scan import Frames
from render_common import find_tool


def probe(ffprobe, source):
    """Return the displayed dimensions, accounting for rotation metadata."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json', source]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('ffprobe: ' + result.stderr[-500:])
    stream = json.loads(result.stdout)['streams'][0]
    width = int(stream['width'])
    height = int(stream['height'])
    rotation = int(float(stream.get('tags', {}).get('rotate', 0)))
    for item in stream.get('side_data_list', []):
        rotation = int(float(item.get('rotation', rotation)))
    return (height, width) if rotation % 180 else (width, height)


def bounds(width, height, aspect, zoom=1):
    """Return crop width and height as fractions of the source frame."""
    if not math.isfinite(zoom) or zoom < 1 or aspect <= 0:
        raise ValueError('zoom must be at least 1 and aspect must be positive')
    crop_width = min(width, height * aspect) / zoom
    return crop_width / width, crop_width / aspect / height


def position(path, time):
    """Interpolate keys without overshoot, with zero velocity at every key."""
    if time <= path[0][0]:
        return path[0][1], path[0][2]
    for left, right in zip(path, path[1:]):
        if time <= right[0]:
            fraction = (time - left[0]) / (right[0] - left[0])
            fraction = fraction * fraction * (3 - 2 * fraction)
            return tuple(left[i] + (right[i] - left[i]) * fraction for i in (1, 2))
    return path[-1][1], path[-1][2]


def region(score):
    """Return a robust bounding box of the weighted motion/detail region."""
    total = float(score.sum())
    if total <= 0:
        return [0.5, 0.5, 0.5, 0.5]
    height, width = score.shape
    # Weighted percentiles reject isolated noise while retaining a measured extent.
    x = np.cumsum(score.sum(axis=0)) / total
    y = np.cumsum(score.sum(axis=1)) / total
    return [float(np.searchsorted(x, .02) / width), float(np.searchsorted(y, .02) / height),
            float((np.searchsorted(x, .98) + 1) / width), float((np.searchsorted(y, .98) + 1) / height)]


def analyse(ffmpeg, source, width, height, start=None, end=None):
    """Decode the requested frames and retain only bounded sheet samples."""
    filters = f'scale={width}:{height},format=rgb24'
    options = None
    if start is not None and end is not None:
        filters = f'trim=start={start}:end={end},' + filters
        options = ['-ss', str(max(0.0, start - 1.0)), '-copyts']
    reader = Frames(ffmpeg, source, filters, width * height * 3, options)
    subjects = []
    samples = []
    stride = 1
    previous = None
    energy = None
    for index, raw in enumerate(reader):
        image = np.frombuffer(raw, np.uint8).reshape(height, width, 3).copy()
        grey = image.astype(np.float32).mean(axis=2)
        dy, dx = np.gradient(grey)
        detail = np.sqrt(dx * dx + dy * dy)
        motion = np.abs(grey - previous) if previous is not None else np.zeros_like(grey)
        energy = motion if energy is None else .85 * energy + .15 * motion
        score = np.maximum(energy - 2, 0) + .15 * detail
        score[score < max(2, float(np.percentile(score, 75)))] = 0
        subjects.append(region(score))
        if index % stride == 0:
            samples.append((index, image))
        if len(samples) > 12:
            stride *= 2
            samples = [sample for sample in samples if sample[0] % stride == 0]
        previous = grey
    times = reader.times(len(subjects))
    return times, subjects, samples


def validate_path(path):
    """Check finite keys and increasing timestamps."""
    if not isinstance(path, list) or not path:
        raise ValueError('path must be a non-empty list')
    path = [[float(value) for value in key] for key in path]
    if any(len(key) != 3 or not all(math.isfinite(value) for value in key) for key in path):
        raise ValueError('path keys must be finite [time, x, y]')
    if any(right[0] <= left[0] for left, right in zip(path, path[1:])):
        raise ValueError('path times must be strictly increasing')
    return path


def propose(times, subjects, crop_width, crop_height, max_rate):
    """Follow the measured box with a bounded smoothstep centre speed."""
    path = []
    centre = np.array([.5, .5])
    last = times[0]
    for time, box in zip(times, subjects):
        target = np.array([(box[0] + box[2]) / 2, (box[1] + box[3]) / 2])
        target[0] = np.clip(target[0], crop_width / 2, 1 - crop_width / 2)
        target[1] = np.clip(target[1], crop_height / 2, 1 - crop_height / 2)
        delta = target - centre
        distance = float(np.linalg.norm(delta))
        # Smoothstep's peak derivative is 1.5, so reserve that factor in each segment.
        limit = max_rate * max(0, time - last) / 1.5
        if distance:
            centre = centre + delta * min(1, limit / distance)
        path.append([time, float(centre[0]), float(centre[1])])
        last = time
    return path


def check(times, subjects, path, crop_width, crop_height):
    """Flag measured bounds outside the crop and crop windows outside the source."""
    flags = []
    for time, box in zip(times, subjects):
        cx, cy = position(path, time)
        window = [cx - crop_width / 2, cy - crop_height / 2,
                  cx + crop_width / 2, cy + crop_height / 2]
        outside = window[0] < 0 or window[1] < 0 or window[2] > 1 or window[3] > 1
        subject_out = (box[0] < window[0] or box[1] < window[1]
                       or box[2] > window[2] or box[3] > window[3])
        if outside or subject_out:
            flags.append({'t': time, 'crop_out': outside, 'subject_out': subject_out, 'subject_bounds': box})
    return flags


def max_path_rate(path):
    """Measure the exact peak rate of the smoothstep segments."""
    return max((1.5 * math.hypot(right[1] - left[1], right[2] - left[2]) / (right[0] - left[0])
                for left, right in zip(path, path[1:])), default=0.0)


def sheet(samples, times, path, crop_width, crop_height, filename):
    """Write evenly spaced decoded samples with their crop rectangles."""
    height, width = samples[0][1].shape[:2]
    tile_height = height + 24
    canvas = Image.new('RGB', (width * 3, tile_height * math.ceil(len(samples) / 3)), 'white')
    draw = ImageDraw.Draw(canvas)
    for number, (index, frame) in enumerate(samples):
        x = number % 3 * width
        y = number // 3 * tile_height
        canvas.paste(Image.fromarray(frame), (x, y))
        cx, cy = position(path, times[index])
        box = (x + (cx - crop_width / 2) * width, y + (cy - crop_height / 2) * height,
               x + (cx + crop_width / 2) * width, y + (cy + crop_height / 2) * height)
        draw.rectangle(box, outline='red', width=2)
        draw.text((x + 4, y + height + 3), f'{times[index]:.3f} s', fill='black')
    canvas.save(filename)


def main():
    """Read options, propose or check a path, and write the inspection report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source')
    parser.add_argument('--aspect', required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--auto', action='store_true')
    group.add_argument('--path')
    parser.add_argument('--out', default='reframe-path.json')
    parser.add_argument('--sheet', default='reframe-sheet.png')
    parser.add_argument('--json', dest='report')
    parser.add_argument('--max-rate', type=float, default=.2, help='maximum centre movement per second')
    args = parser.parse_args()
    try:
        ffmpeg = find_tool('ffmpeg')
        ffprobe = find_tool('ffprobe')
        if not ffmpeg or not ffprobe:
            raise ValueError('FFmpeg and ffprobe are required')
        x, y = (float(value) for value in args.aspect.split(':'))
        if x <= 0 or y <= 0 or not math.isfinite(args.max_rate) or args.max_rate <= 0:
            raise ValueError('aspect and max-rate must be positive')
        source_width, source_height = probe(ffprobe, args.source)
        width = 320
        height = max(2, round(source_height / source_width * width / 2) * 2)
        crop_width, crop_height = bounds(width, height, x / y)
        times, subjects, samples = analyse(ffmpeg, args.source, width, height)
        if args.path:
            with open(args.path, encoding='utf-8') as file:
                data = json.load(file)
            path = validate_path(data.get('path', data) if isinstance(data, dict) else data)
        else:
            path = propose(times, subjects, crop_width, crop_height, args.max_rate)
            with open(args.out, 'w', encoding='utf-8') as file:
                json.dump({'version': 1, 'path': path, 'zoom': 1.0}, file, indent=2)
        flags = check(times, subjects, path, crop_width, crop_height)
        measured_rate = max_path_rate(path)
        sheet(samples, times, path, crop_width, crop_height, args.sheet)
        report = {'source': args.source, 'aspect': args.aspect, 'max_rate': args.max_rate,
                  'measured_max_rate': measured_rate, 'frames': len(times), 'flags': flags,
                  'path': path, 'sheet': args.sheet, 'method': 'sustained motion and detail bounds, not recognition'}
        if args.report:
            with open(args.report, 'w', encoding='utf-8') as file:
                json.dump(report, file, indent=2)
        print(f'{len(times)} frames; {len(flags)} flagged; peak rate {measured_rate:.4f}; sheet {args.sheet}')
        return 1 if flags or measured_rate > args.max_rate + 1e-9 else 0
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, TypeError) as error:
        print(f'reframe: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
