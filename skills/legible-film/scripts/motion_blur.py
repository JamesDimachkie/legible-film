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
filter-graph tags. --lossless gives RGB FFV1/Matroska (.mkv). No audio. Decode to a
temporary disk-backed array, not a RAM-sized film; default one FFmpeg thread. Needs
numpy, Pillow, FFmpeg/ffprobe (PATH, env FFMPEG/FFPROBE, or explicit flags).
Cannot recover real trajectories, occlusions or details absent from the source, nor
judge playback. Exit 0 complete, 1 incomplete decoded/rendered frames, 2 could not run.
"""
import argparse
import bisect
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('lf_render_common', HERE / 'render_common.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


class DiskFrames:
    """One cached frame, bounded RAM, and no mapped-file lock during Windows cleanup."""
    def __init__(self, path, w, h):
        self.path, self.w, self.h = path, w, h
        self.index, self.cached = None, None

    def __getitem__(self, index):
        if index != self.index:
            size = self.w * self.h * 3
            with open(self.path, 'rb') as source:
                source.seek(index * size)
                data = source.read(size)
            if len(data) != size:
                raise RuntimeError('temporary source frame is incomplete')
            self.cached = np.frombuffer(data, np.uint8).reshape(self.h, self.w, 3)
            self.index = index
        return self.cached


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('input')
    p.add_argument('--out', required=True)
    p.add_argument('--fps', type=float, required=True)
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
        print(f'free memory: {C.free_memory() / 1024**2:.0f} MiB; one decoder/encoder, disk-backed frames', flush=True)
        sequence = bool(re.search(r'%0?\d*d', a.input))
        input_options = []
        if sequence:
            if a.input_fps is None:
                raise ValueError('PNG sequences require --input-fps')
            input_options = ['-framerate', str(a.input_fps), '-start_number', str(a.start_number)]
        elif a.input_fps is not None:
            raise ValueError('--input-fps is for numbered sequences; video uses its recorded timestamps')
        r = subprocess.run([ffprobe, '-v', 'error', *input_options, '-select_streams', 'v:0',
                            '-show_streams', '-show_frames', '-show_entries',
                            'stream=width,height,avg_frame_rate:frame=best_effort_timestamp_time,duration_time,pkt_duration_time',
                            '-of', 'json', a.input], capture_output=True, text=True)
        if r.returncode:
            raise ValueError('cannot probe input: ' + r.stderr[-1000:])
        meta = json.loads(r.stdout)
        stream = meta['streams'][0]
        w, h = stream['width'], stream['height']
        rows = meta['frames']
        clock = [float(x['best_effort_timestamp_time']) for x in rows]
        if len(clock) < 2:
            raise ValueError('at least two input frames required')
        intervals = np.diff(clock)
        dt = float(np.median(intervals))
        # Container millisecond quantisation is allowed, but a genuinely retimed frame is not.
        num, den = stream['avg_frame_rate'].split('/')
        rate = float(num) / float(den) if float(den) else 1 / dt
        if rate <= 0:
            rate = 1 / dt
        if abs(clock[0]) > .0011 or np.any(intervals <= 0) or np.max(np.abs(intervals - 1 / rate)) > max(.0011, .03 / rate):
            raise ValueError('input must start at zero and have regular timing; conform VFR explicitly first')
        ratio = rate / a.fps
        if ratio < 2 - 1e-4 or abs(ratio - round(ratio)) > 1e-4:
            raise ValueError('source rate must be an integer multiple >=2 of output fps')
        duration = clock[-1] + float(rows[-1].get('duration_time', rows[-1].get('pkt_duration_time', 1 / rate)))
        count = int(math.floor(duration * a.fps + 1e-6))
        if count < 1:
            raise ValueError('source is shorter than one output frame')
        info = json.loads(Path(a.cuts_json).read_text(encoding='utf-8')) if a.cuts_json else {}
        cuts = sorted(set(info.get('cuts', []) + ([float(x) for x in a.cuts.split(',')] if a.cuts else [])))
        smears = list(info.get('smears', []))
        if a.smear:
            for s in a.smear.split(','):
                m = re.fullmatch(r'(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)', s)
                if not m:
                    raise ValueError('smear must look like 3.1-3.3:3')
                smears.append([float(x) for x in m.groups()])
        timeline = {'width': w, 'height': h, 'fps': a.fps, 'duration': count / a.fps,
                    'frames': count, 'cuts': cuts, 'smears': smears, 'fast': info.get('fast', [])}
        C.validate_timeline(timeline)
        # List all source timestamps per shot. Nearest-time lookup is restricted to this slice.
        shot_bounds = [0.0] + cuts + [duration]
        shot_ids = [(bisect.bisect_left(clock, lo - 1e-9), bisect.bisect_left(clock, hi - 1e-9))
                    for lo, hi in zip(shot_bounds, shot_bounds[1:])]
        if any(lo == hi for lo, hi in shot_ids):
            raise ValueError('a shot has no source samples; render the source at a higher rate')
        output.parent.mkdir(parents=True, exist_ok=True)
        scratch_bytes = len(clock) * w * h * 3
        print(f'raw scratch estimate: {scratch_bytes / 1024**3:.3f} GiB for {len(clock)} source frames', flush=True)
        if shutil.disk_usage(output.parent).free < scratch_bytes * 1.1 + 16 * 1024**2:
            raise ValueError('insufficient free disk for the decoded high-rate source')
        with tempfile.TemporaryDirectory(prefix='lf-blur-', dir=output.parent) as tmp:
            raw = Path(tmp) / 'source.rgb'
            r = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-threads', '1', *input_options, '-i', a.input,
                                '-map', '0:v:0', '-fps_mode', 'passthrough', '-pix_fmt', 'rgb24',
                                '-threads', '1', '-f', 'rawvideo', str(raw)], capture_output=True, text=True)
            if r.returncode or raw.stat().st_size != len(clock) * w * h * 3:
                print('motion_blur.py: source decode incomplete: ' + r.stderr[-1000:], file=sys.stderr)
                return 1
            source = DiskFrames(raw, w, h)
            intermediate = Path(tmp) / ('blur.mkv' if a.lossless else 'blur.mp4')
            encoder = C.Encoder(ffmpeg, intermediate, w, h, a.fps, a.crf, a.level, lossless=a.lossless)
            maximum_error = 0.0
            for k in range(count):
                t = k / a.fps
                times = C.sample_times(t, a.fps, count / a.fps, cuts, smears, timeline['fast'],
                                       a.shutter, 2 * round(ratio), a.max_samples)
                shot = bisect.bisect_right(cuts, t)
                low, high = shot_ids[shot]
                avg = np.zeros((h, w, 3), dtype=np.float32)
                for ts in times:
                    idx = min(max(bisect.bisect_left(clock, ts), low), high - 1)
                    # Timestamp text is commonly rounded to microseconds. Resolve midpoint
                    # ties towards the later sample consistently, rather than duplicating
                    # samples because of tiny decimal/binary rounding differences.
                    if idx > low and abs(clock[idx-1] - ts) + 1e-6 < abs(clock[idx] - ts):
                        idx -= 1
                    maximum_error = max(maximum_error, abs(clock[idx] - ts))
                    rgb = source[idx]
                    avg += C.linear(rgb) if a.blend == 'linear' else rgb.astype(np.float32) / 255
                avg /= len(times)
                encoder.write(C.finish(avg, k, a.blend, dither=not a.no_dither))
            encoder.close()
            encoder = None
            del rgb
            del source
            decoded = C.decoded_count(ffprobe, intermediate)
            if decoded != count:
                print(f'motion_blur.py: missing frames: {decoded}/{count}', file=sys.stderr)
                return 1
            manifest = {'settings': vars(a), 'source_frames': len(clock), 'source_fps': rate,
                        'base_samples': 2 * round(ratio),
                        'output_frames': count, 'timeline': timeline,
                        'max_source_sample_error_s': maximum_error,
                        'temporal_limit': 'nearest source sample in the same shot; source-grid quantisation remains',
                        'output_sha256': C.sha256(intermediate), 'ffmpeg': C.version(ffmpeg),
                        'wall_s': round(time.perf_counter() - started, 3), 'audio': 'intentionally absent'}
            intermediate.replace(output)
            report_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(f'{len(clock)} source frames at {rate:g} fps -> {count} frames at {a.fps:g} fps; '
              f'nearest-source error <= {maximum_error * 1000:.3f} ms; {output}')
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, ZeroDivisionError, TypeError) as exc:
        print('motion_blur.py: could not run: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        if encoder:
            encoder.abort()


if __name__ == '__main__':
    sys.exit(main())
