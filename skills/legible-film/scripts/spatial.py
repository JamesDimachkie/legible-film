#!/usr/bin/env python3
"""Spatial layers: tracks and mattes stored as files on a source's own clock (references/spatial.md).

  python spatial.py show LAYER.json [--project PROJECT] [--json]
  python spatial.py check LAYER.json [--project PROJECT] [--verify] [--json]

A layer is a JSON sidecar (spatial/NAME.json in a project, or beside an output for a quick edit) bound to one source
file and video stream: the file's size and SHA-256 (the map's registered values when the source is in the map),
the absolute ffprobe index of its video stream, its displayed frame size (after rotation and pixel aspect) and the
presentation origin its times are measured from. `times` holds the exact decoded presentation time of every layer
frame on the clock assemble.py uses; a track's frames and a matte's FFV1 frames are matched to them by order.

show prints what a layer is: its kind, source, time range, method, measured quality, and whether it is current.
check also decodes the source's frame times in the layer's range and compares them with the layer's: exit 1 when
the layer is stale (its source changed, another video stream, another displayed size, or a proxy), when its data
file is missing or changed, when frames are missing or out of order, or when a frame does not match the source's
displayed frame size. --verify hashes the source and data files instead of trusting the recorded size and the map's
SHA-256 (a multi-gigabyte source is never rehashed without it).

The module is also the shared reader and writer other scripts import: read_layer, write_layer, bind_source,
layer_state, frame_index, match_frame, FrameReader (streams matte frames in order, never a whole clip in memory),
write_frames and homography.

What this does not prove: that a track follows the right surface or that a matte separates the right subject. A
current layer matches its source's bytes and clock; look at the frames it draws (frame_sheet.py) before trusting it.
Needs numpy and FFmpeg/ffprobe. Exit codes: 0 nothing to report, 1 something to inspect, 2 could not run.
"""
import argparse
import bisect
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_sibling(name):
    """Load a sibling script as a module, the way the other 2.0 scripts load project.py."""
    spec = importlib.util.spec_from_file_location('lf_spatial_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


project = load_sibling('project')
try:
    import numpy as np
except ImportError as missing:
    print(project.dependency_message(missing.name or 'numpy'), file=sys.stderr)
    sys.exit(2)

VERSION = 1
KINDS = ('track', 'matte', 'depth')
DRAWN_KINDS = ('track', 'matte')
STATES = ('key', 'tracked', 'lost')
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*$')
PIXEL_FORMATS = {'matte': ('gray', np.dtype('u1')), 'depth': ('gray16le', np.dtype('<u2'))}
SHA256 = re.compile(r'[0-9a-f]{64}$')
TIME_SLACK = 1e-4  # seconds: decoded times printed by different readers agree to well within this


# ----------------------------------------------------------------------------------------------- tools

def find_tool(name):
    """FFmpeg or ffprobe from the environment override or PATH, or None."""
    return load_sibling('render_common').find_tool(name)


def run_probe(command):
    """Run ffprobe and parse its JSON, raising ValueError with its message on failure."""
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=1800)
    if result.returncode:
        raise ValueError('ffprobe failed: ' + result.stderr.strip()[-400:])
    return json.loads(result.stdout or '{}')


def probe_video(path, ffprobe=None):
    """The first moving-picture stream of a file as layers bind to it: {'video_stream': absolute ffprobe index,
    'frame_size': [w, h] displayed (after rotation and pixel aspect), 'display': rotation, sample aspect and coded
    size, 'origin_s': the format start time assemble.py subtracts}."""
    ffprobe = ffprobe or find_tool('ffprobe')
    if not ffprobe:
        raise ValueError('ffprobe is required to read a source video stream')
    facts = run_probe([ffprobe, '-v', 'error', '-show_streams', '-show_entries', 'format=start_time', '-of', 'json',
                       str(path)])
    streams = [row for row in facts.get('streams', []) if row.get('codec_type') == 'video'
               and not (row.get('disposition') or {}).get('attached_pic')]
    if not streams:
        raise ValueError(f'{path} has no moving picture')
    stream = streams[0]
    geometry = load_sibling('render_common').display_geometry(stream)
    start = (facts.get('format') or {}).get('start_time')
    origin = float(start) if start not in (None, 'N/A') else 0.0
    return {'video_stream': int(stream['index']), 'frame_size': [geometry['width'], geometry['height']],
            'display': {'rotation_degrees': geometry['rotation_degrees'],
                        'sample_aspect_ratio': geometry['sample_aspect_ratio'],
                        'coded_size': [geometry['coded_width'], geometry['coded_height']]},
            'origin_s': origin}


# ----------------------------------------------------------------------------------------------- the map

def map_rows(root):
    """map/sources.json rows by alias ({} without a project or map)."""
    if not root:
        return {}
    data = project.load_json(Path(root) / 'map' / 'sources.json', {}) or {}
    rows = data.get('sources') if isinstance(data, dict) else None
    return {row['alias']: row for row in rows or [] if isinstance(row, dict) and row.get('alias')}


def map_path(root, row):
    """A map row's file path."""
    path = Path(row['path'])
    return path if path.is_absolute() else Path(root) / path


def map_row_for(root, path):
    """The map row whose file is `path`, or None."""
    for row in map_rows(root).values():
        if isinstance(row.get('path'), str) and project.same_file(map_path(root, row), path):
            return row
    return None


def relative_file(path, base):
    """A path as a sidecar records it: relative to the sidecar's folder, absolute on another drive."""
    try:
        return Path(os.path.relpath(Path(path).resolve(), Path(base).resolve())).as_posix()
    except ValueError:
        return Path(path).resolve().as_posix()


def bind_source(source, sidecar_dir, root=None, verify=False, ffprobe=None):
    """The `source` block and displayed frame size for a layer made from `source`: (source_block, frame_size).

    A file in the project's map is bound by its alias and the map's registered byte count and SHA-256 (the file's
    current size must still match; --verify rehashes it). A file outside a map is hashed once, here."""
    source = Path(source).resolve()
    if not source.is_file():
        raise ValueError(f'no source file {source}')
    row = map_row_for(root, source) if root else None
    size = source.stat().st_size
    if row:
        if row.get('bytes') != size or not SHA256.match(str(row.get('sha256'))):
            raise ValueError(f"{row['alias']} changed since it was mapped ({size} bytes, the map has "
                             f"{row.get('bytes')}); map it again (map.py run PROJECT) before making a layer")
        digest = row['sha256']
        if verify and project.file_sha256(source) != digest:
            raise ValueError(f"{row['alias']} changed since it was mapped (its SHA-256 differs); map it again")
    else:
        digest = project.file_sha256(source)
    video = probe_video(source, ffprobe)
    block = {'alias': row['alias'] if row else None, 'file': relative_file(source, sidecar_dir), 'size': size,
             'sha256': digest, 'video_stream': video['video_stream'], 'origin_s': video['origin_s'],
             'display': video['display']}
    return block, video['frame_size']


# ----------------------------------------------------------------------------------------------- the sidecar

def is_number(value):
    """A finite int or float (not a bool)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_corners(corners):
    """Four [x, y] pairs of finite numbers."""
    return (isinstance(corners, list) and len(corners) == 4
            and all(isinstance(pair, list) and len(pair) == 2 and all(map(is_number, pair)) for pair in corners))


def validate_track_frames(layer, problems):
    """A track's frames: one per time, each tracked or key frame with a region (corners) or a point, lost frames
    with neither, error_px measured where a frame was fitted."""
    frames = layer.get('frames')
    if not isinstance(frames, list) or len(frames) != len(layer.get('times') or []):
        problems.append('a track needs one entry in frames for each time in times')
        return
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict) or frame.get('state') not in STATES:
            problems.append(f'frame {index}: state must be key, tracked or lost')
            continue
        if 't' in frame:
            problems.append(f'frame {index}: a frame takes its time from times[{index}]; remove "t"')
        shape = [key for key in ('corners', 'point') if frame.get(key) is not None]
        if frame['state'] == 'lost':
            if shape:
                problems.append(f'frame {index}: a lost frame carries no corners or point')
            continue
        if len(shape) != 1:
            problems.append(f'frame {index}: a {frame["state"]} frame needs corners or a point')
        elif shape[0] == 'corners' and not valid_corners(frame['corners']):
            problems.append(f'frame {index}: corners must be four [x, y] pairs')
        elif shape[0] == 'point' and not (isinstance(frame['point'], list) and len(frame['point']) == 2
                                          and all(map(is_number, frame['point']))):
            problems.append(f'frame {index}: point must be [x, y]')
        if frame.get('error_px') is not None and (not is_number(frame['error_px']) or frame['error_px'] < 0):
            problems.append(f'frame {index}: error_px must be a non-negative number')
    shapes = {('corners' if frame.get('corners') is not None else 'point') for frame in frames
              if isinstance(frame, dict) and frame.get('state') != 'lost'}
    if len(shapes) > 1:
        problems.append('a track is either a region (corners) or a point, not both')


def validate(layer):
    """Every way a sidecar breaks the contract, as plain sentences ([] when it is valid)."""
    problems = []
    if not isinstance(layer, dict):
        return ['a layer sidecar is a JSON object']
    if layer.get('version') != VERSION:
        problems.append(f'version must be {VERSION}')
    kind = layer.get('kind')
    if kind not in KINDS:
        problems.append('kind must be track, matte or depth')
    elif kind == 'depth':
        problems.append('depth layers are reserved for a later version')
    source = layer.get('source')
    if not isinstance(source, dict):
        problems.append('source must name the file the layer was made from')
    else:
        if 'stream' in source:
            problems.append('source.stream is ambiguous; the video stream is source.video_stream')
        if not isinstance(source.get('file'), str) or not source['file']:
            problems.append('source.file is missing')
        if not isinstance(source.get('size'), int) or source['size'] <= 0:
            problems.append('source.size must be the file size in bytes')
        if not SHA256.match(str(source.get('sha256'))):
            problems.append('source.sha256 must be the file\'s SHA-256')
        if not isinstance(source.get('video_stream'), int) or source['video_stream'] < 0:
            problems.append('source.video_stream must be the absolute ffprobe index of the video stream')
        if source.get('origin_s') is not None and not is_number(source['origin_s']):
            problems.append('source.origin_s must be a number of seconds')
    size = layer.get('frame_size')
    if not (isinstance(size, list) and len(size) == 2 and all(isinstance(v, int) and v > 0 for v in size)):
        problems.append('frame_size must be [width, height] of the displayed frame')
    if layer.get('clock') != 'source':
        problems.append('clock must be "source"')
    times = layer.get('times')
    if not isinstance(times, list) or not times or not all(map(is_number, times)):
        problems.append('times must list each frame\'s source presentation time')
    elif any(later <= earlier for earlier, later in zip(times, times[1:])):
        problems.append('times must increase strictly (frames out of order or repeated)')
    if kind == 'track':
        if not problems or isinstance(times, list):
            validate_track_frames(layer, problems)
        if layer.get('data') is not None:
            problems.append('a track keeps its frames inline; it has no data file')
    elif kind == 'matte':
        if not isinstance(layer.get('data'), str) or not layer['data']:
            problems.append('a matte names its FFV1 data file in data')
        if not SHA256.match(str(layer.get('data_sha256'))):
            problems.append('data_sha256 must be the data file\'s SHA-256')
        if not isinstance(layer.get('data_frames'), int) or (isinstance(times, list)
                                                              and layer.get('data_frames') != len(times)):
            problems.append('data_frames must equal the number of times')
    if not isinstance(layer.get('method'), dict) or not layer['method'].get('tool'):
        problems.append('method must say which tool made the layer')
    if layer.get('quality') is not None and not isinstance(layer['quality'], dict):
        problems.append('quality must be an object of named measurements')
    return problems


def read_layer(path):
    """A sidecar's content, validated; ValueError naming every problem."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f'no layer sidecar {path}')
    try:
        layer = json.loads(project.read_text(path))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f'{path} is not readable JSON: {error}') from error
    problems = validate(layer)
    if problems:
        raise ValueError(f'{path.name}: ' + '; '.join(problems))
    return layer


def write_layer(path, layer):
    """Validate and write a sidecar atomically, stamping when it was made."""
    layer = dict(layer)
    layer.setdefault('made', project.now())
    problems = validate(layer)
    if problems:
        raise ValueError('refusing to write an invalid layer: ' + '; '.join(problems))
    project.save_json(path, layer)
    return layer


def sidecar_path(root, name):
    """Where a named layer lives in a project."""
    if not NAME.match(str(name)):
        raise ValueError(f'a layer name is lowercase letters, digits and hyphens, not {name!r}')
    return Path(root) / 'spatial' / f'{name}.json'


def data_path(path, layer):
    """A matte's data file, beside its sidecar."""
    return Path(path).parent / layer['data']


def source_path(path, layer, root=None):
    """The file a layer's source block names: the map's path for its alias in a project, else its recorded file."""
    rows = map_rows(root)
    alias = layer['source'].get('alias')
    if alias and alias in rows and isinstance(rows[alias].get('path'), str):
        return map_path(root, rows[alias])
    recorded = Path(layer['source']['file'])
    return recorded if recorded.is_absolute() else Path(path).parent / recorded


def sha256_of(path):
    """SHA-256 of a file's bytes."""
    return project.file_sha256(path)


def file_digest(path):
    """SHA-256 of a sidecar or data file, or None when it does not exist."""
    path = Path(path)
    return sha256_of(path) if path.is_file() else None


# ----------------------------------------------------------------------------------------------- binding

def layer_state(path, layer, root=None, verify=False, ffprobe=None, probe=True):
    """Whether a layer fits its source as it is now: {'state': 'current' | 'stale' | 'missing', 'reasons': [...],
    'source_file': path}. Stale: the source's bytes, video stream, displayed size or origin differ from what the
    layer was made from, or it was made from a proxy, or the matte's data changed (its SHA-256, always compared).
    The map's registered size and SHA-256 are trusted (the file's current size is always compared); verify also
    rehashes the source."""
    reasons = []
    source = layer['source']
    file = source_path(path, layer, root)
    if not file.is_file():
        return {'state': 'missing', 'reasons': [f'the source file is missing ({file})'], 'source_file': file}
    rows = map_rows(root)
    row = rows.get(source.get('alias')) if source.get('alias') else None
    size = file.stat().st_size
    if row:
        if row.get('sha256') != source['sha256'] or row.get('bytes') != source['size']:
            reasons.append(f"{source['alias']} was mapped again from other media since the layer was made")
        if row.get('bytes') != size:
            reasons.append(f"{source['alias']} changed since it was mapped ({size} bytes, the map has "
                           f"{row.get('bytes')})")
    elif size != source['size']:
        reasons.append(f'the source file changed ({size} bytes; the layer was made from {source["size"]})')
    if verify and not reasons and sha256_of(file) != source['sha256']:
        reasons.append('the source file changed (its SHA-256 differs from the one the layer was made from)')
    if (layer.get('method') or {}).get('proxy'):
        reasons.append('the layer was made from a proxy, not the source')
    if probe:
        try:
            video = probe_video(file, ffprobe)
        except ValueError as error:
            reasons.append(str(error))
        else:
            if video['video_stream'] != source['video_stream']:
                reasons.append(f"the layer was made from video stream {source['video_stream']}; the source's "
                               f"picture is stream {video['video_stream']}")
            if list(layer['frame_size']) != video['frame_size']:
                reasons.append(f"the layer is {layer['frame_size'][0]}x{layer['frame_size'][1]}; the source shows "
                               f"{video['frame_size'][0]}x{video['frame_size'][1]}")
            origin = source.get('origin_s')
            if origin is not None and abs(origin - video['origin_s']) > TIME_SLACK:
                reasons.append(f'the source clock starts at {video["origin_s"]:.6f} s; the layer was measured from '
                               f'{origin:.6f} s')
    if layer['kind'] == 'matte':
        data = data_path(path, layer)
        if not data.is_file():
            reasons.append(f'the matte data file is missing ({data.name})')
        elif sha256_of(data) != layer['data_sha256']:
            # Always, not only with verify: a blur or a title behind someone draws from these frames, and a matte
            # replaced by another valid one (an empty one) would otherwise blur nothing and report every frame drawn.
            reasons.append('the matte data file changed since the layer was written')
    return {'state': 'stale' if reasons else 'current', 'reasons': reasons, 'source_file': file}


# ----------------------------------------------------------------------------------------------- time

def frame_interval(times, index):
    """The local frame interval at `index`: to the next frame, or from the previous for the last one."""
    if len(times) < 2:
        return None
    if index + 1 < len(times):
        return times[index + 1] - times[index]
    return times[index] - times[index - 1]


def frame_index(times, moment):
    """The layer frame for a source time: the last frame at or before it, within half a (local) frame; None
    before the first frame or more than half a frame after the last. A single-frame layer answers only its time."""
    position = bisect.bisect_right(times, moment + TIME_SLACK) - 1
    if position < 0:
        return None
    interval = frame_interval(times, position)
    if interval is None:
        return position if abs(moment - times[position]) <= TIME_SLACK else None
    if position == len(times) - 1 and moment - times[position] > interval / 2 + TIME_SLACK:
        return None
    return position


def match_frame(times, selected, tolerance=None):
    """The layer frame for the source frame the renderer selected (its decoded time): the frame with that time, or
    None. `tolerance` (default a quarter of the local frame interval, at least TIME_SLACK) absorbs rounding between
    readers and proxies; it is never wide enough to reach a neighbouring frame."""
    position = bisect.bisect_left(times, selected)
    best = None
    for index in (position - 1, position):
        if 0 <= index < len(times) and (best is None or abs(times[index] - selected) < abs(times[best] - selected)):
            best = index
    if best is None:
        return None
    interval = frame_interval(times, best)
    limit = tolerance if tolerance is not None else max(TIME_SLACK, (interval or 0.0) / 4)
    return best if abs(times[best] - selected) <= limit else None


def source_frame_times(path, start, end, origin, ffprobe=None):
    """Decoded presentation times of the source's first video stream within [start, end] on the layer clock (format
    start time subtracted), read with ffprobe the way render_common resolves covering frames."""
    ffprobe = ffprobe or find_tool('ffprobe')
    interval = f'{max(0.0, origin + start - 1.0):.6f}%{origin + end + 1.0:.6f}'
    facts = run_probe([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-read_intervals', interval,
                       '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(path)])
    times = []
    for frame in facts.get('frames', []):
        value = frame.get('best_effort_timestamp_time')
        if value not in (None, 'N/A'):
            moment = float(value) - origin
            if start - TIME_SLACK <= moment <= end + TIME_SLACK:
                times.append(moment)
    return sorted(set(round(value, 9) for value in times))


# ----------------------------------------------------------------------------------------------- frames

class FrameReader:
    """A matte's (or depth layer's) frames by index, decoded by FFmpeg in order through a pipe: one frame in memory
    at a time. Frames are matched to `times` by their order in the file (passthrough timing), never by the MKV's own
    timestamps. Asking for an earlier frame than the last restarts the decode."""

    def __init__(self, path, size, kind='matte', ffmpeg=None):
        self.path, self.size = Path(path), (int(size[0]), int(size[1]))
        self.pix_fmt, self.dtype = PIXEL_FORMATS[kind]
        self.frame_bytes = self.size[0] * self.size[1] * self.dtype.itemsize
        self.ffmpeg = ffmpeg or find_tool('ffmpeg')
        if not self.ffmpeg:
            raise ValueError('FFmpeg is required to read layer frames')
        self.proc = None
        self.position = -1
        self.current = None
        self.errors = []

    def _start(self):
        """(Re)start the decoder at the first frame."""
        self.close()
        command = [self.ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', str(self.path), '-map', '0:v:0',
                   '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', self.pix_fmt, 'pipe:1']
        self.proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.errors = []
        threading.Thread(target=self._drain, args=(self.proc,), daemon=True).start()
        self.position = -1
        self.current = None

    def _drain(self, proc):
        """Keep the decoder's error output from filling its pipe."""
        for line in proc.stderr:
            self.errors = self.errors[-3:] + [line.decode('utf-8', 'replace').strip()]

    def frame(self, index):
        """Frame `index` as a (height, width) array of the layer's sample type."""
        if index < 0:
            raise IndexError('negative layer frame')
        if self.proc is None or index < self.position:
            self._start()
        while self.position < index:
            raw = self.proc.stdout.read(self.frame_bytes)
            if len(raw) < self.frame_bytes:
                detail = f': {self.errors[-1]}' if self.errors else ''
                raise IndexError(f'{self.path.name} has no frame {index} (it ends after {self.position + 1}){detail}')
            self.position += 1
            if self.position == index:
                self.current = np.frombuffer(raw, dtype=self.dtype).reshape(self.size[1], self.size[0])
        return self.current

    def close(self):
        """Stop the decoder."""
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill()
            self.proc.stdout.close()
            self.proc.wait()
            self.proc = None


def write_frames(path, frames, size, kind='matte', ffmpeg=None):
    """Write frames (arrays of the layer's sample type, `size` = [w, h]) to an FFV1 MKV, streaming; returns the frame
    count. Values are stored exactly: gray for mattes (0 and 255 survive), gray16le for depth."""
    ffmpeg = ffmpeg or find_tool('ffmpeg')
    if not ffmpeg:
        raise ValueError('FFmpeg is required to write layer frames')
    pix_fmt, dtype = PIXEL_FORMATS[kind]
    width, height = int(size[0]), int(size[1])
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', pix_fmt, '-s',
               f'{width}x{height}', '-framerate', '25', '-i', 'pipe:0', '-map', '0:v:0', '-fps_mode', 'passthrough',
               '-c:v', 'ffv1', '-level', '3', '-pix_fmt', pix_fmt, '-color_range', 'pc', str(path)]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    count = 0
    try:
        for frame in frames:
            array = np.ascontiguousarray(frame, dtype=dtype)
            if array.shape != (height, width):
                raise ValueError(f'frame {count} is {array.shape[1]}x{array.shape[0]}, not {width}x{height}')
            proc.stdin.write(array.tobytes())
            count += 1
        proc.stdin.close()
        error = proc.stderr.read().decode('utf-8', 'replace')
        if proc.wait():
            raise ValueError('FFmpeg could not write layer frames: ' + error.strip()[-400:])
    except BaseException:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        raise
    return count


def count_frames(path, ffprobe=None):
    """The number of decoded frames in a data file."""
    ffprobe = ffprobe or find_tool('ffprobe')
    facts = run_probe([ffprobe, '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                       'stream=nb_read_frames,width,height', '-of', 'json', str(path)])
    streams = facts.get('streams') or []
    if not streams:
        raise ValueError(f'{path} has no video stream')
    return int(streams[0].get('nb_read_frames') or 0), (int(streams[0]['width']), int(streams[0]['height']))


def seal_data(path, layer):
    """Record a matte's data file identity in its sidecar fields: data_sha256 and data_frames."""
    data = data_path(path, layer)
    frames, _ = count_frames(data)
    return dict(layer, data_sha256=sha256_of(data), data_frames=frames)


# ----------------------------------------------------------------------------------------------- geometry

def homography(source, target):
    """The 3x3 homography taking four source points to four target points (numpy, no OpenCV)."""
    rows, values = [], []
    for (x, y), (u, v) in zip(source, target):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values.extend([u, v])
    solution = np.linalg.solve(np.asarray(rows, dtype=np.float64), np.asarray(values, dtype=np.float64))
    return np.append(solution, 1.0).reshape(3, 3)


def apply_homography(matrix, points):
    """Points (N x 2) through a 3x3 homography."""
    points = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    mapped = np.hstack([points, np.ones((len(points), 1))]) @ np.asarray(matrix, dtype=np.float64).T
    return mapped[:, :2] / mapped[:, 2:3]


def track_shape(layer):
    """'corners' for a region track, 'point' for a point track."""
    for frame in layer.get('frames', []):
        if frame.get('corners') is not None:
            return 'corners'
        if frame.get('point') is not None:
            return 'point'
    return 'corners'


def track_frame(layer, index):
    """A track frame's position in displayed source pixels: (corners 4x2 or None, point 2 or None, state)."""
    frame = layer['frames'][index]
    width, height = layer['frame_size']
    scale = np.array([width, height], dtype=np.float64)
    if frame['state'] == 'lost':
        return None, None, 'lost'
    if frame.get('corners') is not None:
        corners = np.asarray(frame['corners'], dtype=np.float64) * scale
        return corners, corners.mean(axis=0), frame['state']
    return None, np.asarray(frame['point'], dtype=np.float64) * scale, frame['state']


# ----------------------------------------------------------------------------------------------- versions

def overlay_layers(edit):
    """Every layer path an edit.json's overlays name (pin, behind, blur region), in order, without repeats."""
    found = []
    for overlay in edit.get('overlays', []) if isinstance(edit, dict) else []:
        if not isinstance(overlay, dict):
            continue
        for key in ('pin', 'behind', 'region'):
            value = overlay.get(key)
            layer = value.get('layer') if isinstance(value, dict) else None
            if isinstance(layer, str) and layer not in found:
                found.append(layer)
    return found


def layer_files(edit, base):
    """The files an edit's layers read, for a checks file's inputs: [(role, path)] for each sidecar and data file."""
    rows = []
    for name in overlay_layers(edit):
        path = (Path(base) / name).resolve()
        rows.append(('layer', path))
        try:
            layer = json.loads(project.read_text(path))
        except (OSError, ValueError):
            continue
        if isinstance(layer, dict) and isinstance(layer.get('data'), str):
            rows.append(('layer_data', path.parent / layer['data']))
    return rows


def layer_record(path, root=None):
    """What a version records about a layer it used: the sidecar's and data file's SHA-256, its kind, source and
    quality summary, so an old version can be explained after the layer is made again."""
    path = Path(path)
    record = {'sidecar': path.as_posix(), 'sidecar_sha256': file_digest(path)}
    try:
        layer = read_layer(path)
    except ValueError as error:
        record['problem'] = str(error)
        return record
    record.update({'kind': layer['kind'], 'source': {key: layer['source'].get(key) for key in
                                                     ('alias', 'size', 'sha256', 'video_stream')},
                   'range': [layer['times'][0], layer['times'][-1]], 'frames': len(layer['times']),
                   'method': layer['method'].get('tool'), 'made': layer.get('made')})
    if layer['kind'] == 'matte':
        record['data'] = layer['data']
        record['data_sha256'] = file_digest(data_path(path, layer))
    return record


# ----------------------------------------------------------------------------------------------- show and check

def track_summary(layer):
    """Counts of a track's frames by state."""
    counts = {state: 0 for state in STATES}
    for frame in layer['frames']:
        counts[frame['state']] += 1
    return counts


def describe(path, layer, state):
    """A layer as readable lines."""
    source = layer['source']
    times = layer['times']
    name = source.get('alias') or source['file']
    lines = [f"{Path(path).name}: {layer['kind']} of {name} (video stream {source['video_stream']}), "
             f"{layer['frame_size'][0]}x{layer['frame_size'][1]}",
             f'  range {project.format_time(max(0.0, times[0]), 3)} to {project.format_time(max(0.0, times[-1]), 3)}'
             f' source time, {len(times)} frames']
    method = layer['method']
    detail = ', '.join(f'{key} {method[key]}' for key in ('backend', 'model', 'licence') if method.get(key))
    lines.append(f"  made by {method['tool']}" + (f' ({detail})' if detail else '') + f" at {layer.get('made')}")
    if layer['kind'] == 'track':
        counts = track_summary(layer)
        lines.append(f"  {track_shape(layer)} track: {counts['key']} key, {counts['tracked']} tracked, "
                     f"{counts['lost']} lost")
    quality = {key: value for key, value in (layer.get('quality') or {}).items()
               if not isinstance(value, (dict, list)) and key != 'units'}
    if quality:
        lines.append('  measured: ' + ', '.join(f'{key} {value}' for key, value in quality.items()))
    for start, end in (layer.get('quality') or {}).get('lost_spans_s', [])[:5]:
        lines.append(f'  lost {start:.3f}-{end:.3f} s')
    if state['state'] == 'current':
        lines.append('  current: the source matches what the layer was made from')
    else:
        lines.append(f"  {state['state'].upper()}: " + '; '.join(state['reasons']))
    return lines


def check_layer(path, layer, root=None, verify=False):
    """Every problem that stops a layer being drawn, as sentences, plus information lines: (problems, info)."""
    state = layer_state(path, layer, root, verify)
    problems = list(state['reasons'])
    info = []
    if state['state'] == 'missing':
        return problems, info
    times = layer['times']
    origin = layer['source'].get('origin_s')
    origin = probe_video(state['source_file'])['origin_s'] if origin is None else origin
    decoded = source_frame_times(state['source_file'], times[0], times[-1], origin)
    unmatched = [value for value in decoded if match_frame(times, value) is None]
    extra = [value for value in times if match_frame(decoded, value) is None]
    if unmatched:
        shown = ', '.join(f'{value:.3f}' for value in unmatched[:5])
        problems.append(f'{len(unmatched)} source frames in the layer\'s range have no layer frame ({shown} s)')
    if extra:
        shown = ', '.join(f'{value:.3f}' for value in extra[:5])
        problems.append(f'{len(extra)} layer times match no source frame ({shown} s)')
    if layer['kind'] == 'matte' and data_path(path, layer).is_file():
        frames, size = count_frames(data_path(path, layer))
        if frames != len(times):
            problems.append(f'the data file has {frames} frames for {len(times)} times')
        if list(size) != list(layer['frame_size']):
            problems.append(f'the data frames are {size[0]}x{size[1]}, not the layer\'s '
                            f"{layer['frame_size'][0]}x{layer['frame_size'][1]}")
    if layer['kind'] == 'track':
        counts = track_summary(layer)
        if counts['lost']:
            info.append(f"{counts['lost']} of {len(times)} frames are lost: nothing is pinned there and a blur "
                        'over them stops the render')
    return problems, info


def main(argv=None):
    """spatial.py show | check."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('show', 'check'))
    parser.add_argument('layer')
    parser.add_argument('--project', help='the project folder (default: the one holding the layer, if any)')
    parser.add_argument('--verify', action='store_true', help='hash the source and data files')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    project.safe_output()
    try:
        path = Path(args.layer).resolve()
        layer = read_layer(path)
        root = Path(args.project).resolve() if args.project else project.find_project(path.parent)
        if args.command == 'show':
            state = layer_state(path, layer, root, args.verify)
            if args.json:
                print(json.dumps({'layer': str(path), 'kind': layer['kind'], 'source': layer['source'],
                                  'state': state['state'], 'reasons': state['reasons'],
                                  'range': [layer['times'][0], layer['times'][-1]], 'frames': len(layer['times']),
                                  'method': layer['method'], 'quality': layer.get('quality')}, indent=1))
            else:
                print('\n'.join(describe(path, layer, state)))
            return 0 if state['state'] == 'current' else 1
        problems, info = check_layer(path, layer, root, args.verify)
        if args.json:
            print(json.dumps({'layer': str(path), 'ok': not problems, 'problems': problems, 'info': info}, indent=1))
        else:
            for line in problems:
                print('problem: ' + line)
            for line in info:
                print('note: ' + line)
            print(f'{path.name}: ' + ('current; every source frame in its range has a layer frame' if not problems
                                      else f'{len(problems)} problem{"s" if len(problems) != 1 else ""}'))
        return 1 if problems else 0
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError) as error:
        print(f'spatial: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
