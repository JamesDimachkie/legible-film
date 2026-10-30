#!/usr/bin/env python3
"""Cut-aware motion blur from a high-rate video or numbered PNG sequence, with no engine dependency.

  python motion_blur.py render240.mkv --fps 60 --shutter 180 --cuts 1.25,4.0 --out film.mp4
  python motion_blur.py frames/%06d.png --input-fps 240 --fps 60 --smear 3.1-3.3:3 --out film.mp4
  python motion_blur.py render240.mp4 --cuts-json info.json --fps 60 --out film.mp4

PNG sequences need --input-fps and may need --start-number (default 0). Videos use
decoded presentation timestamps, must have regular timing and start at zero; reject
VFR rather than silently invent timing. The source rate must be an integer multiple
of delivery rate and at least 2x. Renders centred sub-frame exposures, slides at cuts,
and increases sample count in smear/fast windows. Base midpoint count is twice the
source/delivery rate ratio, so exposure edges do not all land on source-grid ties.
Source frames are instantaneous
samples: select nearest available time inside the SAME shot, never interpolate across
a cut. Nearest-time error is normally at most half a source interval, but clamping
at a shot edge can increase it; the manifest reports the measured maximum. More
source samples improve accuracy. A cut list must match the source; no cut inference.

Linear-light float32 averaging by default; --blend gamma for encoded-value averaging.
H.264 High slow CRF14, explicit level, closed GOP, faststart, BT.709 conversion and
filter-graph tags. --lossless gives RGB FFV1/Matroska (.mkv). No audio. One sequential
RGB decode through a pipe; no decoded-frame scratch file. The timestamp-validation
probe streams its metadata too. Let E be the largest shutter exposure including
smears, and g_min/g_max the smallest/largest input PTS interval. The retained RGB
window is bounded by ceil((2*E + 2*g_max + 4 microseconds)/g_min) + 2 frames, plus
one in-flight frame and fixed-size blend/codec buffers. The bound depends on shutter,
rate and smear, never film length; normal shutters use a few to a few dozen frames.
Prints this bound in frames/MiB and the observed cache peak. Default one FFmpeg thread. Needs
numpy, Pillow, FFmpeg/ffprobe (PATH, env FFMPEG/FFPROBE, or explicit flags).
Cannot recover real trajectories, occlusions or details absent from the source, nor
judge playback. Exit 0 complete, 1 incomplete decoded/rendered frames, 2 could not run.
"""
import argparse
import bisect
from collections import Counter, deque
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('lf_render_common', HERE / 'render_common.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


class DecodeFailure(RuntimeError):
    pass


def timestamp_probe(ffprobe, input_options, path, cuts, declared_rate):
    """Validate the original decoded PTS rules without retaining a per-frame list.

    ffprobe prints PTS to microseconds. A histogram of integer-microsecond intervals
    supplies the median fallback rate; it contains at most one entry per distinct
    timestamp interval, not one per frame. Codec diagnostics are bounded as well.
    """
    proc = subprocess.Popen([ffprobe, '-v', 'error', *input_options, '-select_streams', 'v:0',
        '-show_frames', '-show_entries',
        'frame=best_effort_timestamp_time,duration_time,pkt_duration_time',
        '-of', 'compact=p=0:nk=0', path], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace')
    errors = deque(maxlen=8)
    def read_errors():
        for line in proc.stderr:
            errors.append(line.strip())
    reader = threading.Thread(target=read_errors, daemon=True)
    reader.start()
    count, first, previous, last_duration = 0, None, None, None
    gaps, minimum, maximum = Counter(), math.inf, 0.0
    clock_hash = hashlib.sha256()
    shots = [0] * (len(cuts) + 1)
    try:
        for line in proc.stdout:
            fields = dict(part.split('=', 1) for part in line.strip().split('|') if '=' in part)
            if 'best_effort_timestamp_time' not in fields:
                continue  # optional side-data rows are not video frames
            t = float(fields['best_effort_timestamp_time'])
            if not math.isfinite(t):
                raise ValueError('source has a non-finite presentation timestamp')
            if previous is not None:
                gap = t - previous
                if gap <= 0:
                    raise ValueError('input must start at zero and have regular timing; conform VFR explicitly first')
                if declared_rate > 0 and abs(gap - 1 / declared_rate) > max(.0011, .03 / declared_rate):
                    raise ValueError('input must start at zero and have regular timing; conform VFR explicitly first')
                minimum, maximum = min(minimum, gap), max(maximum, gap)
                gaps[round(gap * 1000000)] += 1
            else:
                first = t
            previous = t
            last_duration = fields.get('duration_time', fields.get('pkt_duration_time'))
            if last_duration == 'N/A':
                last_duration = None
            clock_hash.update(struct.pack('<d', t))
            # This matches the old bisect_left(clock, cut - 1e-9) shot slices.
            shots[bisect.bisect_right(cuts, t + 1e-9)] += 1
            count += 1
        proc.wait()
        reader.join()
        if proc.returncode:
            raise ValueError('cannot probe input: ' + '\n'.join(errors)[-1000:])
        if count < 2:
            raise ValueError('at least two input frames required')
        positions = ((count - 2) // 2, (count - 1) // 2)
        values, seen = [], 0
        for value, frequency in sorted(gaps.items()):
            for position in positions:
                if seen <= position < seen + frequency:
                    values.append(value / 1000000)
            seen += frequency
        return {'count': count, 'first': first, 'last': previous, 'last_duration': last_duration,
                'median_gap': sum(values) / 2, 'min_gap': minimum, 'max_gap': maximum,
                'clock_sha256': clock_hash.hexdigest(), 'shots': shots}
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait()
        proc.stdout.close()
        reader.join()
        proc.stderr.close()


class StreamFrames:
    """Sequential RGB decode, bounded PTS queue and a cut/seek-safe rolling window."""
    TIMEBASE = re.compile(r'config in time_base:\s*(\d+)/(\d+)')
    FRAME = re.compile(r'\bn:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:')

    def __init__(self, ffmpeg, input_options, path, w, h, expected, bound):
        self.w, self.h, self.expected, self.bound = w, h, expected, bound
        self.cache, self.log = deque(), deque(maxlen=8)
        self.metadata = queue.Queue(maxsize=2)
        self.stop = threading.Event()
        self.error = None
        self.floor, self.last_time = -math.inf, -math.inf
        self.count, self.peak, self.eof = 0, 0, False
        self.clock_hash = hashlib.sha256()
        # Integer pts + time_base avoid showinfo's rounded pts_time display. -copyts
        # preserves the same film origin as ffprobe, including small nonzero starts.
        self.proc = subprocess.Popen([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-copyts',
            '-threads', '1', *input_options, '-i', path, '-map', '0:v:0',
            '-vf', 'showinfo=checksum=0', '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24',
            '-threads', '1', '-f', 'rawvideo', 'pipe:1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.reader = threading.Thread(target=self._read_log, daemon=True)
        self.reader.start()

    def _put(self, item):
        while not self.stop.is_set():
            try:
                self.metadata.put(item, timeout=.05)
                return
            except queue.Full:
                pass

    def _read_log(self):
        tb = None
        try:
            for raw in self.proc.stderr:
                line = raw.decode('utf-8', 'replace').strip()
                match = self.TIMEBASE.search(line)
                if match:
                    tb = int(match.group(1)) / int(match.group(2))
                match = self.FRAME.search(line)
                if match:
                    if tb is None:
                        raise DecodeFailure('decoder supplied a frame without its time base')
                    # Match ffprobe's fixed-six-decimal timestamp strings, including ties.
                    t = float(format(int(match.group(2)) * tb, '.6f'))
                    self._put((int(match.group(1)), t))
                elif line and 'showinfo' not in line:
                    self.log.append(line)
        except Exception as exc:
            self.error = exc

    def set_floor(self, t):
        self.floor = t
        while self.cache and self.cache[0][1] < t:
            self.cache.popleft()

    def _read_one(self):
        if self.eof:
            return False
        frame = np.empty((self.h, self.w, 3), dtype=np.uint8)
        view = memoryview(frame).cast('B')
        pos = 0
        while pos < len(view):
            got = self.proc.stdout.readinto(view[pos:])
            if not got:
                if pos:
                    raise DecodeFailure('source decode ended inside an RGB frame')
                self.eof = True
                return False
            pos += got
        while True:
            try:
                index, t = self.metadata.get(timeout=.1)
                break
            except queue.Empty:
                if self.error or not self.reader.is_alive():
                    raise DecodeFailure('could not read the decoded frame timestamp: ' + str(self.error or '\n'.join(self.log)))
        if index != self.count:
            raise DecodeFailure('decoder frame/timestamp sequence is incomplete')
        self.clock_hash.update(struct.pack('<d', t))
        self.count += 1
        self.last_time = t
        if t >= self.floor:
            self.cache.append((index, t, frame))
            self.peak = max(self.peak, len(self.cache))
            if len(self.cache) > self.bound:
                raise DecodeFailure('internal source-window bound exceeded')
        return True

    def nearest(self, t, left, right):
        while self.last_time < t and self._read_one():
            pass
        frames = [f for f in self.cache if left - 1e-9 <= f[1] < right - 1e-9]
        if not frames:
            raise DecodeFailure('no retained source sample inside this shot')
        times = [f[1] for f in frames]
        index = min(bisect.bisect_left(times, t), len(times) - 1)
        if index > 0 and abs(times[index - 1] - t) + 1e-6 < abs(times[index] - t):
            index -= 1
        return frames[index][2], abs(times[index] - t)

    def finish(self):
        # Decode the remaining tail as well: incomplete input must not be a clean pass.
        self.set_floor(math.inf)
        while self._read_one():
            pass
        self.proc.wait()
        self.reader.join()
        if (self.proc.returncode or self.error or self.count != self.expected['count'] or
                self.clock_hash.hexdigest() != self.expected['clock_sha256']):
            raise DecodeFailure('source decode incomplete or presentation timestamps changed: ' +
                                '\n'.join(self.log)[-1000:])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stop.set()
        if self.proc.poll() is None:
            self.proc.terminate()  # only this decoder PID, owned by this instance
        self.proc.wait()
        self.reader.join()
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.cache.clear()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('input')
    p.add_argument('--out', required=True)
    p.add_argument('--fps', type=lambda v: float(C.exact_rate(v)), required=True,
                   help='output frame rate: 60, 29.97 or 30000/1001 (a decimal NTSC rate means the exact one)')
    p.add_argument('--input-fps', type=float, help='required for PNG sequences')
    p.add_argument('--start-number', type=int, default=0)
    p.add_argument('--cuts', help='comma-separated cut times in seconds')
    p.add_argument('--cuts-json', help='__lf.info JSON (cuts, smears and fast windows)')
    p.add_argument('--smear', help='START-END:FACTOR, repeated with commas')
    p.add_argument('--shutter', type=float, default=180)
    p.add_argument('--max-samples', type=int, default=256)
    p.add_argument('--blend', choices=('linear', 'gamma'), default='linear')
    p.add_argument('--crf', type=float, default=14)
    p.add_argument('--level')
    p.add_argument('--lossless', action='store_true')
    p.add_argument('--no-dither', action='store_true')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    p.add_argument('--json', help='write measurement/manifest JSON (default OUT.manifest.json)')
    a = p.parse_args()
    if (not math.isfinite(a.fps) or a.fps <= 0 or not math.isfinite(a.shutter) or a.shutter < 0 or
            a.max_samples < 1 or not math.isfinite(a.crf) or not 0 <= a.crf <= 51 or a.start_number < 0):
        p.error('invalid rate, shutter, sample limit, CRF or start number')
    if a.input_fps is not None and (not math.isfinite(a.input_fps) or a.input_fps <= 0):
        p.error('--input-fps must be positive and finite')
    ffmpeg, ffprobe = C.find_tool('ffmpeg', a.ffmpeg), C.find_tool('ffprobe', a.ffprobe)
    if not ffmpeg or not ffprobe:
        print('motion_blur.py: FFmpeg and ffprobe are required', file=sys.stderr)
        return 2
    output = Path(a.out).resolve()
    report_path = Path(a.json or str(output) + '.manifest.json')
    if output.exists() or report_path.exists():
        print('motion_blur.py: output and manifest must be new paths', file=sys.stderr)
        return 2
    if a.lossless and output.suffix.lower() != '.mkv':
        p.error('--lossless needs .mkv (RGB FFV1/Matroska)')
    started = time.perf_counter()
    encoder = None
    try:
        avail = C.free_memory()
        print((f'free memory: {avail / 1024**2:.0f} MiB' if avail is not None else
               'guard could not measure memory') + '; one decoder/encoder, bounded streaming frames', flush=True)
        sequence = bool(re.search(r'%0?\d*d', a.input))
        input_options = []
        if sequence:
            if a.input_fps is None:
                raise ValueError('PNG sequences require --input-fps')
            input_options = ['-framerate', str(a.input_fps), '-start_number', str(a.start_number)]
        elif a.input_fps is not None:
            raise ValueError('--input-fps is for numbered sequences; video uses its recorded timestamps')
        info = json.loads(Path(a.cuts_json).read_text(encoding='utf-8')) if a.cuts_json else {}
        cuts = sorted(set(info.get('cuts', []) + ([float(x) for x in a.cuts.split(',')] if a.cuts else [])))
        smears = list(info.get('smears', []))
        if a.smear:
            for s in a.smear.split(','):
                m = re.fullmatch(r'(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)', s)
                if not m:
                    raise ValueError('smear must look like 3.1-3.3:3')
                smears.append([float(x) for x in m.groups()])
        r = subprocess.run([ffprobe, '-v', 'error', *input_options, '-select_streams', 'v:0',
                            '-show_streams', '-show_entries', 'stream=width,height,avg_frame_rate',
                            '-of', 'json', a.input], capture_output=True, text=True)
        if r.returncode:
            raise ValueError('cannot probe input: ' + r.stderr[-1000:])
        meta = json.loads(r.stdout)
        stream = meta['streams'][0]
        w, h = stream['width'], stream['height']
        num, den = stream['avg_frame_rate'].split('/')
        declared_rate = float(num) / float(den) if float(den) else 0
        probe = timestamp_probe(ffprobe, input_options, a.input, cuts, declared_rate)
        dt = probe['median_gap']
        # Container millisecond quantisation is allowed, but a genuinely retimed frame is not.
        rate = declared_rate or 1 / dt
        if rate <= 0:
            rate = 1 / dt
        if abs(probe['first']) > .0011 or max(abs(probe['min_gap'] - 1 / rate), abs(probe['max_gap'] - 1 / rate)) > max(.0011, .03 / rate):
            raise ValueError('input must start at zero and have regular timing; conform VFR explicitly first')
        ratio = rate / a.fps
        if ratio < 2 - 1e-4 or abs(ratio - round(ratio)) > 1e-4:
            raise ValueError('source rate must be an integer multiple >=2 of output fps')
        duration = probe['last'] + (float(probe['last_duration']) if probe['last_duration'] is not None else 1 / rate)
        count = int(math.floor(duration * a.fps + 1e-6))
        if count < 1:
            raise ValueError('source is shorter than one output frame')
        timeline = {'width': w, 'height': h, 'fps': a.fps, 'duration': count / a.fps,
                    'frames': count, 'cuts': cuts, 'smears': smears, 'fast': info.get('fast', [])}
        C.validate_timeline(timeline)
        shot_bounds = [0.0] + cuts + [duration]
        if not all(probe['shots']):
            raise ValueError('a shot has no source samples; render the source at a higher rate')
        exposure = a.shutter / 360 / a.fps * max([1.0] + [row[2] for row in smears])
        if not math.isfinite(exposure):
            raise ValueError('shutter/smear exposure is too large')
        bound = math.ceil((2 * exposure + 2 * probe['max_gap'] + 4e-6) / probe['min_gap']) + 2
        print(f'source RGB window bound: {bound} frames ({bound * w * h * 3 / 1024**2:.3f} MiB), '
              'plus one in-flight frame and fixed blend/codec buffers; independent of film length', flush=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='lf-blur-', dir=output.parent) as tmp:
            intermediate = Path(tmp) / ('blur.mkv' if a.lossless else 'blur.mp4')
            with StreamFrames(ffmpeg, input_options, a.input, w, h, probe, bound) as source:
                try:
                    encoder = C.Encoder(ffmpeg, intermediate, w, h, a.fps, a.crf, a.level, lossless=a.lossless)
                    maximum_error = 0.0
                    for k in range(count):
                        t = k / a.fps
                        # Future smear onsets can move sample times backwards. Find the
                        # earliest pending sample within 2*E of now; anything later than
                        # that horizon cannot beat this frame's first sample (<= t+E).
                        # This drops old pixels promptly when a large smear has passed,
                        # instead of retaining the global worst-case exposure everywhere.
                        future = range(k, min(count, k + math.ceil(2 * exposure * a.fps) + 2))
                        earliest = min(C.sample_times(j / a.fps, a.fps, count / a.fps, cuts,
                            smears, timeline['fast'], a.shutter, 2 * round(ratio), a.max_samples)[0]
                            for j in future)
                        source.set_floor(earliest - probe['max_gap'] - 2e-6)
                        times = C.sample_times(t, a.fps, count / a.fps, cuts, smears, timeline['fast'],
                                               a.shutter, 2 * round(ratio), a.max_samples)
                        shot = bisect.bisect_right(cuts, t)
                        avg = np.zeros((h, w, 3), dtype=np.float32)
                        for ts in times:
                            rgb, error = source.nearest(ts, shot_bounds[shot], shot_bounds[shot + 1])
                            maximum_error = max(maximum_error, error)
                            avg += C.linear(rgb) if a.blend == 'linear' else rgb.astype(np.float32) / 255
                            del rgb
                        avg /= len(times)
                        encoder.write(C.finish(avg, k, a.blend, dither=not a.no_dither))
                    source.finish()
                    encoder.close()
                    encoder = None
                    print(f'source RGB window observed peak: {source.peak}/{bound} frames '
                          f'({source.peak * w * h * 3 / 1024**2:.3f} MiB); decoded {source.count} frames', flush=True)
                finally:
                    if encoder:
                        encoder.abort()
                        encoder = None
            decoded = C.decoded_count(ffprobe, intermediate)
            if decoded != count:
                print(f'motion_blur.py: missing frames: {decoded}/{count}', file=sys.stderr)
                return 1
            manifest = {'settings': vars(a), 'source_frames': probe['count'], 'source_fps': rate,
                        'base_samples': 2 * round(ratio),
                        'output_frames': count, 'timeline': timeline,
                        'max_source_sample_error_s': maximum_error,
                        'temporal_limit': 'nearest source sample in the same shot; source-grid quantisation remains',
                        'output_sha256': C.sha256(intermediate), 'ffmpeg': C.version(ffmpeg),
                        'wall_s': round(time.perf_counter() - started, 3), 'audio': 'intentionally absent'}
            intermediate.replace(output)
            report_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'{probe["count"]} source frames at {rate:g} fps -> {count} frames at {a.fps:g} fps; '
              f'nearest-source error <= {maximum_error * 1000:.3f} ms; {output}')
        return 0
    except DecodeFailure as exc:
        print('motion_blur.py: source decode incomplete: ' + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, ZeroDivisionError, TypeError) as exc:
        print('motion_blur.py: could not run: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        if encoder:
            encoder.abort()


if __name__ == '__main__':
    sys.exit(main())
