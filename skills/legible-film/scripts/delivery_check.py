#!/usr/bin/env python3
"""Screen delivered video and a low-bitrate proxy with CAMBI and VMAF.

The proxy is not a platform's actual encode. Measurements locate windows to inspect; they do not grade a film.
"""
import argparse
import contextlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

try:
    import numpy as np
except ImportError as missing:
    import runpy
    sys.exit(runpy.run_path(str(Path(__file__).with_name('project.py')))['missing_package'](missing))

HERE = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location('lf_delivery_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def has_libvmaf(ffmpeg):
    try:
        result = subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=30)
        return result.returncode == 0 and bool(re.search(r'\blibvmaf\b', result.stdout))
    except (OSError, subprocess.TimeoutExpired):
        return False


def output_guard(film, out, master=None):
    """Reject aliases and immutable version paths before making any output."""
    path = Path(out)
    sibling('project').refuse_overwriting_inputs([path, path / 'report.json', path / 'delivered.json'],
                                                 [film, master, __file__], guard_versions=True)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('output directory must be new or empty')


def probe_video(ffprobe, film):
    run = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-count_packets',
                          '-show_entries', 'stream=width,height,r_frame_rate,nb_read_packets,duration:'
                                           'format=duration', '-of', 'json', str(film)],
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    if run.returncode:
        raise ValueError('ffprobe could not read video: ' + run.stderr[-500:])
    data = json.loads(run.stdout)
    streams = data.get('streams') or []
    if not streams:
        raise ValueError('the input has no video stream')
    source = streams[0]
    fps = float(Fraction(source['r_frame_rate']))
    duration = 0.0
    for candidate in (source.get('duration'), data.get('format', {}).get('duration')):
        try:
            duration = float(candidate)
            if math.isfinite(duration) and duration > 0:
                break
        except (TypeError, ValueError):
            pass
    frames = int(source.get('nb_read_packets') or 0)
    if not math.isfinite(fps) or fps <= 0 or not math.isfinite(duration) or duration <= 0 or frames < 1:
        raise ValueError('video frame rate, duration or packet count is unavailable')
    if abs(frames - round(duration * fps)) > 1:
        raise ValueError('the video does not have a constant frame schedule; windows cannot be compared')
    return {'width': int(source['width']), 'height': int(source['height']), 'fps': fps,
            'duration_s': duration, 'frames': frames}


def command(ffmpeg, args, cwd):
    run = subprocess.run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-xerror', *map(str, args)],
                         cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if run.returncode:
        raise ValueError('FFmpeg delivery analysis failed: ' + run.stderr[-1200:])


def metrics(path, keys, want):
    frames = json.loads(Path(path).read_text(encoding='utf-8')).get('frames') or []
    if abs(len(frames) - want) > 1:
        raise ValueError(f'analysis covered {len(frames)} frames but expected {want}')
    result = {}
    for key in keys:
        values = np.asarray([row.get('metrics', {}).get(key, np.nan) for row in frames], dtype=float)
        if not len(values) or not np.isfinite(values).all():
            raise ValueError(f'{key} is missing on one or more frames')
        result[key] = values
    return result


def describe(values, high=True):
    return {'mean': round(float(np.mean(values)), 3), 'min': round(float(np.min(values)), 3),
            'max': round(float(np.max(values)), 3),
            'p95' if high else 'p5': round(float(np.percentile(values, 95 if high else 5)), 3)}


def windows(values, fps, seconds, top, high=True, start=0):
    count = max(1, round(fps * seconds))
    if len(values) < count:
        count = len(values)
    means = np.convolve(values, np.ones(count) / count, mode='valid')
    ranked = np.argsort(-means if high else means)
    chosen = []
    for first in ranked:
        first = int(first)
        if all(abs(first - other) >= count for other in chosen):
            chosen.append(first)
        if len(chosen) == top:
            break
    rows = []
    for first in chosen:
        part = values[first:first + count]
        peak = first + int(np.argmax(part) if high else np.argmin(part))
        rows.append({'start_s': round(start + first / fps, 4), 'end_s': round(start + (first + count) / fps, 4),
                     'mean': round(float(means[first]), 3), 'peak': round(float(values[peak]), 3),
                     'peak_s': round(start + peak / fps, 4)})
    return rows


def parse_sims(values):
    values = ['1280x720@2048k'] if values is None else values
    if 'none' in [v.lower() for v in values]:
        if len(values) != 1:
            raise ValueError('--sim none cannot be combined with other simulations')
        return []
    parsed = []
    for value in values:
        match = re.fullmatch(r'(\d+)x(\d+)@(\d+)([kKmM])', value)
        if not match:
            raise ValueError('use --sim WIDTHxHEIGHT@RATE, for example 1280x720@2048k')
        width, height, rate = map(int, match.group(1, 2, 3))
        rate *= 1000 if match.group(4).lower() == 'm' else 1
        if min(width, height, rate) <= 0 or width % 2 or height % 2:
            raise ValueError('simulation dimensions must be positive even numbers and bitrate positive')
        row = (width, height, rate)
        if row in parsed:
            raise ValueError('duplicate simulation')
        parsed.append(row)
    return parsed


def delivery_report(film, out, master=None, sims=None, start=0, duration=0, window=.5, top=5,
                    ffmpeg=None, ffprobe=None, threads=2):
    """Measure all frames of the selected interval and its optional proxy."""
    output_guard(film, out, master)
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    ffprobe = ffprobe or shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('FFmpeg and ffprobe are required')
    if not Path(film).is_file() or (master and not Path(master).is_file()):
        raise ValueError('the film and any supplied master must be existing files')
    if not all(math.isfinite(v) for v in (start, duration, window)) or start < 0 or duration < 0 \
            or window <= 0 or top < 1 or threads < 1:
        raise ValueError('start and duration must be non-negative; window, top and threads must be positive')
    simulations = parse_sims(sims)
    if not has_libvmaf(ffmpeg):
        return {'state': 'not assessed', 'reason': 'FFmpeg lacks libvmaf', 'frames_checked': 0,
                'limit': 'No delivery stress metrics were measured.'}
    film, out = Path(film).resolve(), Path(out).resolve()
    project = sibling('project')
    film_sha = project.file_sha256(film)
    master_sha = project.file_sha256(master) if master else None
    info = probe_video(ffprobe, film)
    if start >= info['duration_s'] or (duration and start + duration > info['duration_s'] + 1 / info['fps']):
        raise ValueError('the selected interval lies outside the film')
    span = min(duration or info['duration_s'] - start, info['duration_s'] - start)
    want = min(info['frames'] - round(start * info['fps']), round(span * info['fps']))
    if want < 1:
        raise ValueError('the selected interval has no frames')
    cut = (['-ss', f'{start:.6f}'] if start else []) + (['-t', f'{span:.6f}'] if duration else [])
    out.mkdir(parents=True, exist_ok=True)
    args = [*cut, '-i', film]
    if master:
        master = Path(master).resolve()
        ref = probe_video(ffprobe, master)
        if (ref['width'], ref['height']) != (info['width'], info['height']) \
                or abs(ref['fps'] - info['fps']) > 1e-6 \
                or ref['frames'] - round(start * ref['fps']) < want - 1:
            raise ValueError('the master must have matching dimensions, frame rate and coverage')
        args += [*cut, '-i', master]
        graph = '[0:v]setpts=PTS-STARTPTS[d];[1:v]setpts=PTS-STARTPTS[r];'
    else:
        graph = '[0:v]split[d][r];'
    graph += f"[d][r]libvmaf=feature='name=cambi':n_threads={threads}:log_fmt=json:log_path=delivered.json"
    command(ffmpeg, [*args, '-lavfi', graph, '-f', 'null', '-'], out)
    measured = metrics(out / 'delivered.json', ['cambi'] + (['vmaf'] if master else []), want)
    fps = info['fps']
    worst = windows(measured['cambi'], fps, window, top, start=start)
    version = subprocess.run([ffmpeg, '-version'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace').stdout.splitlines()
    report = {'state': 'measured', 'film': str(film), 'film_sha256': film_sha,
              'ffmpeg': version[0] if version else None, 'probe': info, 'start_s': start, 'duration_s': span,
              'frames_expected': want, 'frames_checked': len(measured['cambi']), 'window_s': window,
              'cambi': describe(measured['cambi']), 'worst_cambi': worst,
              'banding_candidates': [row for row in worst if row['mean'] >= .1],
              'candidate_limit': 'CAMBI window mean 0.1 is an unvalidated starting screen, not a quality threshold.',
              'master': None, 'simulations': [],
              'limit': 'Metrics locate review windows. The proxy is not the platform transcoder; '
                       'packet counts do not prove constant timestamp spacing; normal-speed viewing remains open.'}
    if master:
        report['master'] = {'path': str(master), 'sha256': master_sha,
                            'vmaf': describe(measured['vmaf'], False),
                            'worst_vmaf': windows(measured['vmaf'], fps, window, top, False, start)}
    for width, height, rate in simulations:
        tag = f'sim-{width}x{height}-{rate}k'
        target, metric_file = out / (tag + '.mp4'), out / (tag + '.json')
        sibling('project').refuse_overwriting_inputs([target, metric_file], [film, master, __file__],
                                                     guard_versions=True)
        command(ffmpeg, [*cut, '-i', film, '-map', '0:v:0', '-an', '-vf',
                         f'scale={width}:{height}:flags=bicubic', '-c:v', 'libx264', '-preset', 'medium',
                         '-b:v', f'{rate}k', '-maxrate', f'{round(rate * 1.5)}k', '-bufsize', f'{rate * 2}k',
                         '-pix_fmt', 'yuv420p', '-threads', '1', target.name], out)
        graph = (f'[0:v]scale={info["width"]}:{info["height"]}:flags=bicubic,setpts=PTS-STARTPTS[d];'
                 '[1:v]setpts=PTS-STARTPTS[r];'
                 f"[d][r]libvmaf=feature='name=cambi':n_threads={threads}:log_fmt=json:log_path={tag}.json")
        command(ffmpeg, ['-i', target.name, *cut, '-i', film, '-lavfi', graph, '-f', 'null', '-'], out)
        values = metrics(metric_file, ['cambi', 'vmaf'], want)
        worst_proxy = windows(values['cambi'], fps, window, top, start=start)
        report['simulations'].append({'size': [width, height], 'rate_kbps': rate,
            'sha256': project.file_sha256(target),
            'actual_kbps': round(target.stat().st_size * 8 / 1000 / span), 'frames_checked': len(values['vmaf']),
            'cambi': describe(values['cambi']), 'vmaf': describe(values['vmaf'], False),
            'worst_cambi': worst_proxy, 'banding_candidates': [row for row in worst_proxy if row['mean'] >= .1],
            'worst_vmaf': windows(values['vmaf'], fps, window, top, False, start)})
    if project.file_sha256(film) != film_sha or (master and project.file_sha256(master) != master_sha):
        raise ValueError('an input changed during the delivery check; no report was saved')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('film')
    p.add_argument('outdir')
    p.add_argument('--master')
    p.add_argument('--sim', action='append')
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--dur', type=float, default=0)
    p.add_argument('--window', type=float, default=.5)
    p.add_argument('--top', type=int, default=5)
    p.add_argument('--threads', type=int, default=2)
    a = p.parse_args(argv)
    try:
        output_guard(a.film, a.outdir, a.master)
        if not Path(a.film).is_file() or (a.master and not Path(a.master).is_file()):
            raise ValueError('the film and any supplied master must be existing files')
        if not all(math.isfinite(v) for v in (a.start, a.dur, a.window)) or a.start < 0 or a.dur < 0 \
                or a.window <= 0 or a.top < 1 or a.threads < 1:
            raise ValueError('start and duration must be non-negative; window, top and threads must be positive')
        parse_sims(a.sim)
        ffmpeg = shutil.which('ffmpeg')
        lock = sibling('with_lock')
        hold = (lock.HeavyLock(label='delivery-check', say=lambda *x, **kw: print(*x, file=sys.stderr, **kw))
                if ffmpeg and has_libvmaf(ffmpeg) else contextlib.nullcontext())
        with hold:
            report = delivery_report(a.film, a.outdir, a.master, a.sim, a.start, a.dur, a.window, a.top,
                                     ffmpeg=ffmpeg, threads=a.threads)
            out = Path(a.outdir)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, ZeroDivisionError, json.JSONDecodeError) as error:
        print('delivery_check.py: ' + str(error), file=sys.stderr)
        return 2
    except Exception as error:
        if error.__class__.__name__ == 'LockTimeout':
            print('delivery_check.py: lock: ' + str(error), file=sys.stderr)
            return 2
        raise


if __name__ == '__main__':
    sys.exit(main())
