#!/usr/bin/env python3
"""Make a source-clock matte layer for a project or quick edit.

  python matte.py SOURCE --name NAME [--project PROJECT | --out DIR] --method key|luma|difference|subject
  python matte.py SOURCE --name NAME --out DIR --method key --color 0,255,0 --tolerance 35 --softness 15
  python matte.py SOURCE --name NAME --out DIR --method difference --plate clean.png --preview sheet.png

SOURCE is a registered alias with --project, otherwise a local video. Without --out, files go beside the source.
Times are source seconds or m:ss.ss.
The sidecar maps every lossless gray frame to its decoded presentation time; the container itself is indexed at
25 fps. With --from, the frame covering the in-point is included. The endpoint is exclusive. The simple keys
do not remove colour spill. A subject model can be consistently wrong or miss people; inspect the preview.
Flicker is a heuristic, not a quality or accuracy verdict. Exit 0 on completion, 1 when measured issues need
inspection, and 2 when the matte could not be made. No media is uploaded.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from motion_scan import Frames
from render_common import display_geometry, presentation_frame_before
import assemble

spec = importlib.util.spec_from_file_location('lf_matte_project', HERE / 'project.py')
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)

MODEL_NAME = 'modnet.onnx'
MODEL_SHA256 = '07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9'
MODEL_URL = ('https://huggingface.co/Xenova/modnet/resolve/'
             'fa2fa546052fba4c08921230a26cc69a333fca12/onnx/model.onnx')
MODEL_CARD = 'https://huggingface.co/Xenova/modnet'
CODE_LICENCE = 'https://github.com/ZHKKKe/MODNet/blob/master/LICENSE'
FLICKER_MEAN_LIMIT = 0.08
FLICKER_PAIR_LIMIT = 0.25


def setup_module():
    """Use the existing setup cache location without creating it."""
    module_spec = importlib.util.spec_from_file_location('lf_matte_setup', HERE / 'setup.py')
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def parse_colour(value):
    """Parse RGB as a hex colour or three decimal byte values."""
    if re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))
    try:
        parts = tuple(int(item) for item in value.split(','))
    except ValueError as error:
        raise ValueError('colour must be #RRGGBB or R,G,B') from error
    if len(parts) != 3 or any(item < 0 or item > 255 for item in parts):
        raise ValueError('colour must be #RRGGBB or R,G,B with values 0-255')
    return parts


def source_info(source, root):
    """Resolve a mapped alias or a quick-edit path and bind it to actual bytes."""
    row = None
    if root is not None:
        rows = project.load_json(root / 'map' / 'sources.json', {}).get('sources', [])
        matches = [item for item in rows if item.get('alias') == source]
        if len(matches) != 1:
            raise ValueError('SOURCE must name exactly one registered project alias')
        row = matches[0]
        path = Path(row['path'])
        if not path.is_absolute():
            path = root / path
    else:
        path = Path(source)
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError('source is not a file: ' + str(path))
    before = path.stat()
    size = before.st_size
    digest = project.file_sha256(path)
    after = path.stat()
    if after.st_size != size or after.st_mtime_ns != before.st_mtime_ns:
        raise ValueError('source changed while it was being fingerprinted')
    if row and (row.get('bytes') != size or row.get('sha256') != digest):
        raise ValueError('registered source changed since mapping; relink or remap it before making a layer')
    return path, row, size, digest, before.st_mtime_ns


def probe(ffprobe, path):
    """Use the renderer's first video stream and displayed square-pixel geometry."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-show_format',
               '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('ffprobe failed: ' + result.stderr[-500:])
    facts = json.loads(result.stdout)
    streams = facts.get('streams', [])
    if not streams or streams[0].get('disposition', {}).get('attached_pic'):
        raise ValueError('the renderer first video stream is missing or attached art; normalize the source')
    stream = streams[0]
    return stream, display_geometry(stream)


def soft_threshold(values, threshold, softness):
    """Return a feathered 0-1 foreground above the requested threshold."""
    if softness == 0:
        return (values > threshold).astype(np.float32)
    return np.clip((values - threshold) / softness, 0.0, 1.0)


def plate_image(args, source, ffmpeg, width, height, colour_filter):
    """Read a clean still or extract a source frame on the source clock."""
    if args.plate:
        with Image.open(args.plate) as image:
            rgb = np.array(image.convert('RGB'))
    elif args.plate_at is not None:
        at = project.parse_time(args.plate_at)
        if not math.isfinite(at) or at < 0:
            raise ValueError('--plate-at must be a nonnegative source time')
        command = [ffmpeg, '-v', 'error', '-ss', str(at), '-i', str(source), '-map', '0:v:0',
                   '-frames:v', '1', '-vf', colour_filter + f',scale={width}:{height}:flags=lanczos,setsar=1',
                   '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        result = subprocess.run(command, capture_output=True)
        if result.returncode or len(result.stdout) != width * height * 3:
            detail = result.stderr.decode('utf-8', 'replace')[-500:]
            raise ValueError('could not decode the clean plate frame: ' + detail)
        rgb = np.frombuffer(result.stdout, dtype=np.uint8).reshape(height, width, 3).copy()
    else:
        raise ValueError('difference needs --plate IMAGE or --plate-at SOURCE_TIME')
    if rgb.shape != (height, width, 3):
        raise ValueError('the clean plate must have the displayed dimensions of the source')
    return rgb


class Subject:
    """CPU MODNet with one pinned conversion; it is not an instance selector."""

    def __init__(self, model):
        try:
            import onnxruntime as ort
        except ImportError as error:
            raise ValueError(project.dependency_message('onnxruntime', context='spatial')) from error
        self.path = Path(model) if model else setup_module().data_home() / 'models' / MODEL_NAME
        if not self.path.is_file():
            raise ValueError(project.dependency_message(MODEL_NAME))
        if project.file_sha256(self.path) != MODEL_SHA256:
            raise ValueError('MODNet file does not match the pinned SHA-256: ' + str(self.path))
        options = ort.SessionOptions()
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(str(self.path), sess_options=options, providers=['CPUExecutionProvider'])
        self.input = self.session.get_inputs()[0].name

    def alpha(self, rgb):
        """Resize, normalize to [-1,1], infer, then resize the matte to display dimensions."""
        height, width = rgb.shape[:2]
        scale = 512.0 / min(width, height)
        model_width = max(32, int(width * scale) // 32 * 32)
        model_height = max(32, int(height * scale) // 32 * 32)
        image = Image.fromarray(rgb).resize((model_width, model_height), Image.Resampling.BILINEAR)
        values = np.asarray(image, dtype=np.float32) / 127.5 - 1.0
        tensor = np.ascontiguousarray(values.transpose(2, 0, 1)[None])
        result = self.session.run(None, {self.input: tensor})[0][0, 0]
        if not np.isfinite(result).all():
            raise ValueError('subject model produced non-finite alpha')
        matte = Image.fromarray(result.astype(np.float32)).resize((width, height), Image.Resampling.BILINEAR)
        return np.clip(np.asarray(matte), 0.0, 1.0)


def make_alpha(rgb, args, plate, subject, colour):
    """Compute a full-range foreground matte, with optional inversion."""
    values = rgb.astype(np.float32)
    if args.method == 'key':
        distance = np.sqrt(np.sum((values - np.array(colour, dtype=np.float32)) ** 2, axis=2))
        alpha = soft_threshold(distance, args.tolerance, args.softness)
    elif args.method == 'luma':
        luma = values[:, :, 0] * 0.2126 + values[:, :, 1] * 0.7152 + values[:, :, 2] * 0.0722
        alpha = soft_threshold(luma, args.threshold, args.softness)
    elif args.method == 'difference':
        distance = np.sqrt(np.sum((values - plate.astype(np.float32)) ** 2, axis=2))
        alpha = soft_threshold(distance, args.threshold, args.softness)
    else:
        alpha = subject.alpha(rgb)
    if args.invert:
        alpha = 1.0 - alpha
    return np.rint(alpha * 255.0).astype(np.uint8)


def preview_tile(rgb, alpha):
    """Make one small foreground composite on a checkerboard."""
    image = Image.fromarray(rgb)
    image.thumbnail((360, 203), Image.Resampling.LANCZOS)
    mask = Image.fromarray(alpha).resize(image.size, Image.Resampling.LANCZOS)
    x, y = np.indices((image.height, image.width))
    check = (((x // 12 + y // 12) % 2) * 55 + 150).astype(np.uint8)
    background = Image.fromarray(np.repeat(check[:, :, None], 3, axis=2), 'RGB')
    background.paste(image, mask=mask)
    return background


def save_preview(path, samples, times):
    """Save a time-labelled checkerboard contact sheet."""
    columns = min(3, len(samples))
    rows = (len(samples) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * 360, rows * 228), (32, 32, 32))
    draw = ImageDraw.Draw(sheet)
    for number, (index, tile) in enumerate(samples):
        x = number % columns * 360
        y = number // columns * 228
        sheet.paste(tile, (x, y))
        draw.text((x + 4, y + 207), f'frame {index}, source {times[index]:.3f} s', fill='white')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)


def quality_report(coverage, changes, empty, times):
    """Summarize alpha and source-still foreground flicker without claiming correctness."""
    intervals = np.diff(times)
    interval = float(np.median(intervals)) if len(intervals) else 0.0
    spans = []
    begin = None
    for index, value in enumerate(empty + [False]):
        if value and begin is None:
            begin = index
        if not value and begin is not None:
            spans.append({'start_frame': begin, 'end_frame': index - 1,
                          'duration_s': max(0.0, times[index - 1] - times[begin] + interval)})
            begin = None
    nonempty_changes = [value for value in changes if value is not None]
    flicker = float(np.mean(nonempty_changes)) if nonempty_changes else None
    max_pair = max(nonempty_changes) if nonempty_changes else None
    prolonged = any((span['end_frame'] - span['start_frame'] + 1 >= 3 and span['duration_s'] >= 0.25)
                    for span in spans)
    prolonged = prolonged or bool(empty and all(empty))
    issues = []
    if len(times) > 1 and not nonempty_changes:
        issues.append('flicker not assessed: no source-still foreground pixels')
    if prolonged:
        issues.append('empty matte throughout or for at least 3 frames and 0.25 seconds')
    if flicker is not None and (flicker > FLICKER_MEAN_LIMIT or max_pair > FLICKER_PAIR_LIMIT):
        issues.append('large alpha change in source-still foreground pixels')
    return {'coverage': {'min': float(np.min(coverage)), 'median': float(np.median(coverage)),
                         'max': float(np.max(coverage)), 'unit': 'mean alpha per frame, 0-1'},
            'empty_frames': [index for index, value in enumerate(empty) if value], 'empty_spans': spans,
            'empty_alpha_limit': 0.001, 'flicker': flicker, 'flicker_max_pair': max_pair,
            'flicker_pairs': len(nonempty_changes), 'flicker_unit': 'mean absolute alpha change, 0-1',
            'flicker_region': 'source RGB changes by at most 3 per channel; either alpha exceeds 8/255',
            'flicker_limits': {'mean': FLICKER_MEAN_LIMIT, 'pair': FLICKER_PAIR_LIMIT}, 'issues': issues}


def write_layer(ffmpeg, reader, destination, width, height, args, plate, subject, colour):
    """Write the frame-indexed FFV1 data and return timing and measured quality for the sidecar."""
    command = [ffmpeg, '-v', 'error', '-nostdin', '-y', '-f', 'rawvideo', '-pix_fmt', 'gray', '-s',
               f'{width}x{height}', '-r', '25', '-i', 'pipe:0', '-an', '-c:v', 'ffv1', '-pix_fmt', 'gray',
               '-color_range', 'pc', str(destination)]
    coverage = []
    changes = []
    empty = []
    samples = []
    stride = 1
    previous_rgb = None
    previous_alpha = None
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        try:
            for index, raw in enumerate(reader):
                rgb = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
                alpha = make_alpha(rgb, args, plate, subject, colour)
                process.stdin.write(alpha.tobytes())
                value = float(alpha.mean() / 255.0)
                coverage.append(value)
                empty.append(value <= 0.001)
                if previous_rgb is not None:
                    still = np.max(np.abs(rgb.astype(np.int16) - previous_rgb.astype(np.int16)), axis=2) <= 3
                    active = (alpha > 8) | (previous_alpha > 8)
                    region = still & active
                    if int(region.sum()) >= 16:
                        delta = np.abs(alpha.astype(np.int16) - previous_alpha.astype(np.int16))
                        changes.append(float(delta[region].mean() / 255.0))
                    else:
                        changes.append(None)
                previous_rgb = rgb.copy()
                previous_alpha = alpha
                if args.preview and index % stride == 0:
                    samples.append((index, preview_tile(rgb, alpha)))
                    if len(samples) > 12:
                        samples = samples[::2]
                        stride *= 2
            process.stdin.close()
            status = process.wait()
        except Exception:
            try:
                process.stdin.close()
            except OSError:
                pass
            process.wait()
            if reader.proc.poll() is None:
                reader.proc.terminate()
                reader.proc.wait()
            reader.reader.join()
            reader.proc.stdout.close()
            raise
        if status:
            errors.seek(0)
            raise RuntimeError('FFV1 encoder failed: ' + errors.read().decode('utf-8', 'replace')[-500:])
    times = reader.times(len(coverage))
    if any(not math.isfinite(t) for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('source presentation times are not finite and strictly increasing; normalize the source')
    if args.preview:
        save_preview(args.preview, samples, times)
    return times, quality_report(coverage, changes, empty, times)


def verify_data(ffprobe, path, width, height, count):
    """Check the actual lossless stream against the source-frame entries."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_streams',
               '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('could not verify matte data: ' + result.stderr[-500:])
    streams = json.loads(result.stdout).get('streams', [])
    if len(streams) != 1:
        raise ValueError('matte data has no video stream')
    video = streams[0]
    facts = (video.get('codec_name'), video.get('pix_fmt'), video.get('width'), video.get('height'),
             int(video.get('nb_read_frames', -1)))
    if facts != ('ffv1', 'gray', width, height, count):
        raise ValueError('matte data does not match source frame count, geometry, codec or gray format: ' + str(facts))


def main():
    """Validate arguments, produce the layer, and record provenance."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source')
    parser.add_argument('--name', required=True)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument('--project')
    destination.add_argument('--out')
    parser.add_argument('--from', dest='start', default='0')
    parser.add_argument('--to', dest='end')
    parser.add_argument('--method', required=True, choices=('key', 'luma', 'difference', 'subject'))
    parser.add_argument('--color', default='0,255,0')
    parser.add_argument('--tolerance', type=float, default=35.0)
    parser.add_argument('--threshold', type=float, default=25.0)
    parser.add_argument('--softness', type=float, default=15.0)
    parser.add_argument('--invert', action='store_true')
    parser.add_argument('--plate')
    parser.add_argument('--plate-at')
    parser.add_argument('--model')
    parser.add_argument('--box', help=argparse.SUPPRESS)
    parser.add_argument('--at', help=argparse.SUPPRESS)
    parser.add_argument('--preview')
    args = parser.parse_args()
    try:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', args.name):
            raise ValueError('--name must be a lowercase a-z, 0-9, hyphen slug')
        if args.box or args.at:
            raise ValueError('MODNet does not select a person by box or time; --box and --at are unsupported')
        if args.plate and args.plate_at:
            raise ValueError('choose one of --plate and --plate-at')
        for value in (args.tolerance, args.threshold, args.softness):
            if not math.isfinite(value) or value < 0 or value > 442:
                raise ValueError('threshold, tolerance, and softness must be finite values from 0 to 442')
        start = project.parse_time(args.start)
        end = project.parse_time(args.end) if args.end is not None else None
        if not math.isfinite(start) or start < 0 or (end is not None and (not math.isfinite(end) or end <= start)):
            raise ValueError('the source range must be finite, nonnegative, and end after its start')
        root = Path(args.project).resolve() if args.project else None
        source, row, size, digest, source_stamp = source_info(args.source, root)
        if root:
            folder = root / 'spatial'
        elif args.out:
            folder = Path(args.out).resolve()
        else:
            folder = source.parent
        data = folder / (args.name + '.matte.mkv')
        sidecar = folder / (args.name + '.json')
        outputs = [data, sidecar] + ([Path(args.preview)] if args.preview else [])
        if len({os.path.normcase(str(path.resolve())) for path in outputs}) != len(outputs):
            raise ValueError('data, sidecar and preview must be different paths')
        inputs = [source] + ([Path(args.plate)] if args.plate else []) + ([Path(args.model)] if args.model else [])
        project.refuse_overwriting_inputs(outputs, inputs)
        if data.exists() or sidecar.exists():
            raise ValueError('layer already exists; choose a new name')
        ffmpeg = shutil.which('ffmpeg')
        ffprobe = shutil.which('ffprobe')
        if not ffmpeg or not ffprobe:
            raise ValueError('ffmpeg and ffprobe are required on PATH')
        stream, geometry = probe(ffprobe, source)
        width, height = geometry['width'], geometry['height']
        if row and row.get('video') and (row['video'].get('width'), row['video'].get('height')) != (width, height):
            raise ValueError('registered source display size has changed; remap before making a layer')
        origin = assemble.source_origin(ffprobe, str(source))
        covering, seek = presentation_frame_before(ffprobe, str(source), origin, start, end, return_seek=True)
        stop = '' if end is None else f':end={origin + end:.9f}'
        clock = f'trim=start={origin + covering:.9f}{stop},setpts=PTS-({origin:.9f})/TB,'
        colour_filter, _, _ = assemble.colour_filter(stream, int(stream['width']), int(stream['height']))
        vf = clock + colour_filter + f',scale={width}:{height}:flags=lanczos,setsar=1'
        options = ['-copyts']
        if seek:
            options.extend(['-ss', f'{seek:.9f}'])
        if end is not None:
            options.extend(['-t', f'{end - seek + 1:.9f}'])
        colour = parse_colour(args.color)
        plate_binding = None
        if args.method == 'difference' and args.plate:
            plate_path = Path(args.plate).resolve(strict=True)
            plate_stat = plate_path.stat()
            plate_binding = {'path': str(plate_path), 'size': plate_stat.st_size,
                             'sha256': project.file_sha256(plate_path), 'mtime_ns': plate_stat.st_mtime_ns}
        plate = (plate_image(args, source, ffmpeg, width, height, colour_filter)
                 if args.method == 'difference' else None)
        subject = Subject(args.model) if args.method == 'subject' else None
        folder.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(prefix='.matte-', suffix='.mkv', dir=str(folder), delete=False)
        temporary.close()
        temporary_path = Path(temporary.name)
        try:
            reader = Frames(ffmpeg, str(source), vf, width * height * 3, options)
            times, quality = write_layer(ffmpeg, reader, temporary_path, width, height, args, plate, subject, colour)
            tick = 1e-5
            try:
                num, den = map(int, stream.get('time_base', '0/1').split('/'))
                tick = max(tick, num / den)
            except (ValueError, ZeroDivisionError):
                pass
            if abs(times[0] - covering) > tick:
                raise ValueError('decode did not include the covering frame; normalize the source')
            decoded_end = reader.end()
            if decoded_end <= start or (end is not None and end > decoded_end + max(tick, 0.001)):
                raise ValueError('requested range extends beyond the decoded picture')
            if source.stat().st_size != size or source.stat().st_mtime_ns != source_stamp:
                raise ValueError('source changed while the matte was being made')
            if plate_binding:
                plate_stat = Path(plate_binding['path']).stat()
                if (plate_stat.st_size != plate_binding['size']
                        or plate_stat.st_mtime_ns != plate_binding['mtime_ns']):
                    raise ValueError('clean plate changed while the matte was being made')
            verify_data(ffprobe, temporary_path, width, height, len(times))
            method = {'tool': 'matte.py', 'backend': 'modnet' if subject else args.method,
                      'params': {'color': list(colour), 'tolerance': args.tolerance, 'threshold': args.threshold,
                                 'softness': args.softness, 'invert': args.invert, 'plate': args.plate,
                                 'plate_at': args.plate_at, 'from': start, 'to': end}}
            if plate_binding:
                method['plate_file'] = plate_binding
            if subject:
                method.update({'model': MODEL_NAME, 'model_sha256': MODEL_SHA256, 'model_url': MODEL_URL,
                               'licence': 'Apache-2.0', 'licence_url': MODEL_CARD, 'code_licence': 'Apache-2.0',
                               'code_licence_url': CODE_LICENCE})
            else:
                method['licence'] = 'built-in'
                if args.method == 'key':
                    method['spill'] = 'keying does not remove colour spill'
            try:
                shown = os.path.relpath(str(source), str(folder))
            except ValueError:
                shown = str(source)
            binding = {'alias': row['alias'] if row else None, 'file': shown.replace('\\', '/'), 'size': size,
                       'sha256': digest, 'video_stream': int(stream['index']), 'origin_s': origin}
            layer = {'version': 1, 'kind': 'matte', 'source': binding, 'frame_size': [width, height],
                     'clock': 'source', 'times': times, 'data': data.name,
                     'data_sha256': project.file_sha256(temporary_path), 'data_frames': len(times),
                     'method': method, 'quality': quality, 'made': project.now()}
            os.replace(temporary_path, data)
            project.save_json(sidecar, layer)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        print('Matte: ' + str(data))
        print('Sidecar: ' + str(sidecar))
        print(f'Frames: {len(times)}; source {times[0]:.6f}-{times[-1]:.6f} s')
        for issue in quality['issues']:
            print('LOOK: ' + issue)
        return 1 if quality['issues'] else 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as error:
        print('Matte could not run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
