#!/usr/bin/env python3
"""Propose or inspect a crop path and make a sheet of crop windows.

  python reframe.py source.mp4 --aspect 9:16 --auto --out path.json --sheet crop.png [--start S] [--end S]
  python reframe.py source.mp4 --aspect 1:1 --path path.json --sheet check.png

The automatic path follows the largest detected frontal face when OpenCV is available; otherwise it follows
sustained motion and detail. Face detection can miss people or detect things that are not faces. It is not speaker
or identity detection. The path applies a deadband, smoothing and a speed limit. Start and end are source-clock
seconds; end is exclusive. A path it writes is marked
"clock": "source" and assemble.py converts it to the clip's time; a path written by hand counts seconds from --start.
Flags and sheets need review; they do not prove that the intended subject is visible.
Needs numpy, Pillow, FFmpeg and ffprobe. Optional face detection: pip install "opencv-python>=4.8,<5".
Exit 0 for no flags, 1 for flags, 2 on error.
"""
import argparse
import importlib.util
import json
import math
import os
import subprocess
import sys

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motion_scan import Frames
from render_common import display_geometry, find_tool, presentation_frame_before

_project_spec = importlib.util.spec_from_file_location(
    'lf_project', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py'))
project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(project)

FACE_SAMPLE_FRAMES = 5
FACE_MAX_AGE = .5
MAX_AUTO_ZOOM = 2.0


def make_face_detector():
    """Load OpenCV's local frontal-face cascade, or return a reason to use the fallback."""
    try:
        import cv2
    except (ImportError, OSError) as error:
        return None, 'OpenCV unavailable: ' + str(error)
    directory = getattr(getattr(cv2, 'data', None), 'haarcascades', None)
    model = os.path.join(directory or '', 'haarcascade_frontalface_default.xml')
    if not os.path.isfile(model):
        return None, 'OpenCV bundled frontal-face cascade unavailable'
    try:
        classifier = cv2.CascadeClassifier(model)
        if classifier.empty():
            return None, 'OpenCV could not load its frontal-face cascade'
    except (cv2.error, OSError) as error:
        return None, 'OpenCV could not load its frontal-face cascade: ' + str(error)

    def detect(image):
        """Return normalized left, top, right, bottom boxes for one RGB frame."""
        try:
            grey = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            boxes = classifier.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=4, minSize=(18, 18))
        except cv2.error as error:
            raise ValueError('OpenCV face detection failed: ' + str(error)) from error
        height, width = image.shape[:2]
        return [[float(x / width), float(y / height), float((x + w) / width), float((y + h) / height)]
                for x, y, w, h in boxes]

    return detect, ''


def probe(ffprobe, source):
    """Return the displayed dimensions, accounting for rotation metadata."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json', source]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('ffprobe: ' + result.stderr[-500:])
    stream = json.loads(result.stdout)['streams'][0]
    geometry = display_geometry(stream)
    return geometry['width'], geometry['height']


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


def analyse(ffmpeg, source, width, height, start=None, end=None, face_data=None):
    """Decode the range, measuring motion and optionally sampling faces, with bounded sheet images."""
    detector = None
    if face_data is not None:
        detector, reason = make_face_detector()
        face_data.update({'state': 'sampled' if detector else 'not_run', 'reason': reason, 'samples': []})
    filters = f'scale={width}:{height},setsar=1,format=rgb24'
    options = None
    if start is not None or end is not None:
        ffprobe = find_tool('ffprobe')
        if not ffprobe:
            raise ValueError('ffprobe is needed to establish the source presentation origin')
        command = [ffprobe, '-v', 'error', '-show_entries', 'format=start_time', '-of', 'json', str(source)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise ValueError('ffprobe could not establish the source presentation origin')
        raw_origin = (json.loads(result.stdout).get('format') or {}).get('start_time')
        origin = float(raw_origin) if raw_origin not in (None, 'N/A') else 0.0
        limits = []
        if start is not None:
            preceding = presentation_frame_before(ffprobe, source, origin, start, end)
            limits.append(f'start={origin + preceding}')
        if end is not None:
            limits.append(f'end={origin + end}')
        filters = 'trim=' + ':'.join(limits) + f',setpts=PTS-({origin:.9f})/TB,' + filters
        options = ['-copyts']
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
        if detector and (index % FACE_SAMPLE_FRAMES == 0 or float(motion.mean()) > 25):
            try:
                face_data['samples'].append({'index': index, 'boxes': detector(image)})
            except (ValueError, RuntimeError) as error:
                face_data.update({'state': 'not_run', 'reason': str(error), 'samples': []})
                detector = None
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
    if start is not None and times[0] < start:
        times[0] = start
    if any(later <= earlier for earlier, later in zip(times, times[1:])):
        raise ValueError('picture presentation timestamps are not strictly increasing; normalize the source')
    if face_data is not None:
        for sample in face_data['samples']:
            sample['t'] = times[sample['index']]
    return times, subjects, samples


def largest_face(boxes):
    """Choose the largest detected rectangle, without claiming identity or speech."""
    return max(boxes, key=lambda box: (box[2] - box[0]) * (box[3] - box[1]), default=None)


def padded_face(box):
    """Reserve a little room around a detected face to allow for detector jitter and headroom."""
    dx = (box[2] - box[0]) * .1
    dy = (box[3] - box[1]) * .1
    return [max(0, box[0] - dx), max(0, box[1] - dy),
            min(1, box[2] + dx), min(1, box[3] + dy)]


def feasible_centre(boxes, crop_width, crop_height):
    """Return the centre interval that contains every box, or None if no such crop exists."""
    left = max(crop_width / 2, max(box[2] - crop_width / 2 for box in boxes))
    right = min(1 - crop_width / 2, min(box[0] + crop_width / 2 for box in boxes))
    top = max(crop_height / 2, max(box[3] - crop_height / 2 for box in boxes))
    bottom = min(1 - crop_height / 2, min(box[1] + crop_height / 2 for box in boxes))
    if left > right + 1e-9 or top > bottom + 1e-9:
        return None
    return left, top, right, bottom


def face_targets(times, subjects, face_data, crop_width, crop_height):
    """Aim below the largest face, keeping all detected faces when they can fit together."""
    samples = face_data.get('samples', [])
    targets = []
    methods = []
    cursor = 0
    latest = None
    for time, subject in zip(times, subjects):
        while cursor < len(samples) and samples[cursor]['t'] <= time + 1e-9:
            latest = samples[cursor]
            cursor += 1
        boxes = latest['boxes'] if latest and time - latest['t'] <= FACE_MAX_AGE + 1e-9 else []
        face = largest_face(boxes)
        if face is None:
            targets.append(subject)
            methods.append('motion and detail')
            continue
        x = (face[0] + face[2]) / 2
        y = (face[1] + face[3]) / 2 + crop_height * .25
        interval = feasible_centre([padded_face(box) for box in boxes], crop_width, crop_height)
        if interval is None:
            interval = feasible_centre(boxes, crop_width, crop_height)
        if interval is None:
            interval = feasible_centre([padded_face(face)], crop_width, crop_height)
        if interval is None:
            interval = feasible_centre([face], crop_width, crop_height)
        if interval is not None:
            x = min(interval[2], max(interval[0], x))
            y = min(interval[3], max(interval[1], y))
        targets.append([x, y, x, y])
        methods.append('detected face')
    return targets, methods


def method_spans(times, methods, end=None):
    """Summarize the actual per-frame target method on its supplied clock."""
    spans = []
    for index, (time, method) in enumerate(zip(times, methods)):
        stop = times[index + 1] if index + 1 < len(times) else (end if end is not None else time)
        if spans and spans[-1]['method'] == method:
            spans[-1]['end_s'] = stop
        else:
            spans.append({'start_s': time, 'end_s': stop, 'method': method})
    return spans


def face_review(samples, path, crop_width, crop_height):
    """Identify sampled faces that cannot fit together or fall outside the actual smoothed path."""
    findings = []
    last = {}
    for sample in samples:
        boxes = sample['boxes']
        if not boxes:
            continue
        time = sample['t']
        face = largest_face(boxes)
        if feasible_centre([face], crop_width, crop_height) is None:
            kind = 'face_too_large'
        elif len(boxes) > 1 and feasible_centre(boxes, crop_width, crop_height) is None:
            kind = 'people_do_not_fit'
        else:
            cx, cy = position(path, time)
            window = (cx - crop_width / 2, cy - crop_height / 2,
                      cx + crop_width / 2, cy + crop_height / 2)
            clipped = any(box[0] < window[0] - 1e-6 or box[1] < window[1] - 1e-6
                          or box[2] > window[2] + 1e-6 or box[3] > window[3] + 1e-6 for box in boxes)
            kind = 'face_outside_crop' if clipped else None
        if kind and (kind not in last or time - last[kind] > 1):
            findings.append({'t': time, 'kind': kind, 'faces': boxes})
        if kind:
            last[kind] = time
    return findings


def face_height(face_data):
    """Return a median only when faces appear in at least half of two or more samples."""
    samples = face_data.get('samples', [])
    heights = []
    for sample in samples:
        face = largest_face(sample['boxes'])
        if face is not None:
            heights.append(face[3] - face[1])
    if len(heights) < 2 or len(heights) * 2 < len(samples):
        return None
    return float(np.median(heights))


def safe_face_zoom(face_data, crop_width, crop_height):
    """Bound automatic zoom so faces that fit at zoom 1 can still fit, with a small margin."""
    limit = MAX_AUTO_ZOOM
    for sample in face_data.get('samples', []):
        boxes = sample['boxes']
        if not boxes:
            continue
        selected = boxes if feasible_centre(boxes, crop_width, crop_height) is not None else [largest_face(boxes)]
        padded = [padded_face(box) for box in selected]
        if feasible_centre(padded, crop_width, crop_height) is not None:
            selected = padded
        width = max(box[2] for box in selected) - min(box[0] for box in selected)
        height = max(box[3] for box in selected) - min(box[1] for box in selected)
        if width > 0 and height > 0:
            limit = min(limit, crop_width / width, crop_height / height)
    return max(1.0, min(MAX_AUTO_ZOOM, limit * .99 if limit < MAX_AUTO_ZOOM else limit))


def consistent_zooms(analyses):
    """Match median face height across eligible clips of each source, within detected-face and zoom limits."""
    groups = {}
    for number, info in analyses.items():
        height = face_height(info['faces'])
        info['face_height'] = height
        if height is not None and not info['explicit_zoom']:
            groups.setdefault(info['source'], []).append((number, height))
    result = {}
    for rows in groups.values():
        target = max(height for _, height in rows)
        for number, height in rows:
            info = analyses[number]
            desired = target / height
            ceiling = safe_face_zoom(info['faces'], info['crop_width'], info['crop_height'])
            result[number] = {'zoom': min(desired, ceiling), 'target_face_height': target,
                              'constrained': desired > ceiling + 1e-6}
    return result


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


def propose(times, subjects, crop_width, crop_height, max_rate, deadband=.02, smoothing=.35):
    """Follow the measured box with a deadband, smoothing and bounded centre speed."""
    path = []
    targets = np.array([[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] for box in subjects])
    initial = [i for i, time in enumerate(times) if time <= times[0] + .5]
    centre = np.median(targets[initial], axis=0)
    centre[0] = np.clip(centre[0], crop_width / 2, 1 - crop_width / 2)
    centre[1] = np.clip(centre[1], crop_height / 2, 1 - crop_height / 2)
    filtered = centre.copy()
    last = times[0]
    for time, raw_target in zip(times, targets):
        elapsed = max(0, time - last)
        alpha = 1 - math.exp(-elapsed / smoothing) if smoothing else 1
        filtered += (raw_target - filtered) * alpha
        target = filtered.copy()
        target[0] = np.clip(target[0], crop_width / 2, 1 - crop_width / 2)
        target[1] = np.clip(target[1], crop_height / 2, 1 - crop_height / 2)
        delta = target - centre
        distance = float(np.linalg.norm(delta))
        # Smoothstep's peak derivative is 1.5, so reserve that factor in each segment.
        limit = max_rate * elapsed / 1.5
        if distance > deadband:
            centre = centre + delta * min(distance - deadband, limit) / distance
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
    parser.add_argument('--deadband', type=float, default=.02, help='ignore centre movement below this frame fraction')
    parser.add_argument('--smoothing', type=float, default=.35, help='target smoothing time in seconds')
    parser.add_argument('--start', type=float, help='analyse from this source time in seconds')
    parser.add_argument('--end', type=float, help='stop before this source time in seconds')
    args = parser.parse_args()
    try:
        project.refuse_overwriting_inputs([args.sheet, args.report] + ([] if args.path else [args.out]),
                                          [args.source, args.path])
        ffmpeg = find_tool('ffmpeg')
        ffprobe = find_tool('ffprobe')
        if not ffmpeg or not ffprobe:
            raise ValueError('FFmpeg and ffprobe are required')
        x, y = (float(value) for value in args.aspect.split(':'))
        if x <= 0 or y <= 0 or not math.isfinite(args.max_rate) or args.max_rate <= 0:
            raise ValueError('aspect and max-rate must be positive')
        if not math.isfinite(args.deadband) or not 0 <= args.deadband < .5:
            raise ValueError('deadband must be finite and between 0 and 0.5')
        if not math.isfinite(args.smoothing) or args.smoothing < 0:
            raise ValueError('smoothing must be finite and nonnegative')
        if (args.start is not None and (not math.isfinite(args.start) or args.start < 0)
                or args.end is not None and (not math.isfinite(args.end) or args.end <= (args.start or 0))):
            raise ValueError('start and end must be finite, nonnegative and in increasing order')
        source_width, source_height = probe(ffprobe, args.source)
        width = 320
        height = max(2, round(source_height / source_width * width / 2) * 2)
        crop_width, crop_height = bounds(width, height, x / y)
        faces = {}
        times, subjects, samples = analyse(ffmpeg, args.source, width, height, args.start, args.end, faces)
        targets, methods = face_targets(times, subjects, faces, crop_width, crop_height)
        if args.path:
            with open(args.path, encoding='utf-8') as file:
                data = json.load(file)
            path = validate_path(data.get('path', data) if isinstance(data, dict) else data)
            if not (isinstance(data, dict) and data.get('clock') == 'source'):
                # A path without a source clock counts from the clip's start, as edit.json's crop.path does.
                path = [[time + (args.start or 0), x, y] for time, x, y in path]
        else:
            path = propose(times, targets, crop_width, crop_height, args.max_rate, args.deadband, args.smoothing)
            with open(args.out, 'w', encoding='utf-8') as file:
                json.dump({'version': 1, 'clock': 'source', 'path': path, 'zoom': 1.0}, file, indent=2)
        motion_times = [time for time, method in zip(times, methods) if method == 'motion and detail']
        motion_boxes = [box for box, method in zip(subjects, methods) if method == 'motion and detail']
        flags = check(motion_times, motion_boxes, path, crop_width, crop_height)
        face_flags = face_review(faces['samples'], path, crop_width, crop_height)
        flags.extend(face_flags)
        measured_rate = max_path_rate(path)
        sheet(samples, times, path, crop_width, crop_height, args.sheet)
        report = {'source': args.source, 'aspect': args.aspect, 'max_rate': args.max_rate,
                  'start': args.start, 'end': args.end, 'deadband': args.deadband, 'smoothing_s': args.smoothing,
                  'measured_max_rate': measured_rate, 'frames': len(times), 'flags': flags,
                  'path': path, 'sheet': args.sheet, 'method': 'face when detected; otherwise motion and detail',
                  'method_spans': method_spans(times, methods, args.end), 'face_detection': faces}
        if args.report:
            with open(args.report, 'w', encoding='utf-8') as file:
                json.dump(report, file, indent=2)
        print(f'{len(times)} frames; {len(flags)} flagged; peak rate {measured_rate:.4f}; sheet {args.sheet}')
        print('Methods: ' + ', '.join(sorted(set(methods))) +
              (f"; {faces['reason']}" if faces.get('reason') else ''))
        descriptions = {'face_too_large': 'detected face cannot fit; widen the frame or letterbox',
                        'people_do_not_fit': 'detected people cannot fit together; cut between them or letterbox',
                        'face_outside_crop': 'detected face leaves the smoothed crop; adjust it or letterbox'}
        for flag in face_flags:
            print(f"FLAG {flag['t']:.2f} s: {descriptions[flag['kind']]}")
        return 1 if flags or measured_rate > args.max_rate + 1e-9 else 0
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, TypeError) as error:
        print(f'reframe: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
