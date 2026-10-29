#!/usr/bin/env python3
"""Render a frozen local __lf film page to a silent picture with cut-aware motion blur.

  python film_render.py film-folder --out picture-v1.mp4
  python film_render.py film-folder --from 120 --to 179 --preview --out preview.mp4
  python film_render.py film-folder --samples 4 --shutter 180 --grain 1.5 --out picture.mp4
  python film_render.py film-folder --size 1080x1920

Ranges are inclusive output frame indices; sample times stay on the whole-film clock.
--size WxH passes w/h URL parameters and sets the CSS viewport, so the page recomposes.
With no --out, writes FOLDER_OUTPUTWIDTHxOUTPUTHEIGHT.mp4 (or .mkv) beside the film folder.
--res scales a 1920x1080 (or portrait) page by 720/1080, 1, or 2. Other page sizes use
the same relative scale. --lossless writes RGB FFV1/Matroska (use .mkv): no subsampling
or matrix round-trip. Default H.264 High, slow, CRF 14, explicit level, closed GOP,
BT.709 RGB-to-YUV conversion and filter-graph tags, fast start. No audio.

Copies the folder, serves only that copy on localhost, streams bounded PNG/JPEG samples,
accumulates float32 linear sRGB (or --blend gamma), optional linear bloom, deterministic
global grain in RMS 8-bit levels, then 8-bit quantisation. Grain-off uses deterministic
half-level uniform dither (measured gradient improvement; disable with --no-dither).
The manifest records frozen-copy SHA256s, settings, versions, count and output hash.
Defaults to one worker. The memory estimate is a conservative planning estimate, not a
reservation; --force overrides its guard. Needs numpy, Pillow, Node, Playwright and
Chromium (see film_capture.mjs --help), FFmpeg/ffprobe (PATH, env or explicit options).
No downloads. Cannot establish page purity, playback quality or display colour fidelity.
Exit 0 complete; 1 missing frames, page/console error or failed render; 2 could not run.
"""
import argparse
import concurrent.futures
import functools
import http.server
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('lf_render_common', HERE / 'render_common.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


class RenderFailure(RuntimeError):
    pass


class QuietServer(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def read_exact(stream, n):
    parts = []
    remaining = n
    while remaining:
        part = stream.read(remaining)
        if not part:
            raise RenderFailure('capture stream ended before its completion record')
        parts.append(part)
        remaining -= len(part)
    return b''.join(parts)


def read_record(stream):
    length = struct.unpack('>I', read_exact(stream, 4))[0]
    if length > 4 * 1024 * 1024:
        raise RenderFailure('invalid capture metadata length')
    meta = json.loads(read_exact(stream, length))
    size = struct.unpack('>I', read_exact(stream, 4))[0]
    if size > 100 * 1024 * 1024:
        raise RenderFailure('invalid capture image length')
    return meta, read_exact(stream, size)


def worker_command(a, command, url):
    cmd = [a.node, str(HERE / 'film_capture.mjs'), command, url]
    if a.playwright:
        cmd += ['--playwright', a.playwright]
    if a.browser:
        cmd += ['--browser', a.browser]
    if a.size:
        cmd += ['--size', a.size]
    return cmd


def render_part(a, url, info, start, end, path, scale):
    cmd = worker_command(a, 'frames', url) + [
        '--from', str(start), '--to', str(end), '--scale', str(scale), '--shutter', str(a.shutter),
        '--samples', str(1 if a.preview else a.samples), '--max-samples', str(1 if a.preview else a.max_samples),
        '--format', a.format, '--quality', str(a.quality)]
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log)
        encoder = None
        try:
            if read_exact(proc.stdout, 4) != b'LF01':
                raise RenderFailure('invalid capture stream magic')
            header, _ = read_record(proc.stdout)
            if header.get('kind') != 'info' or header['info'] != info:
                raise RenderFailure('page info changed between inspection and capture')
            w, h = round(info['width'] * scale), round(info['height'] * scale)
            encoder = C.Encoder(a.ffmpeg, path, w, h, info['fps'], a.crf, a.level, a.preview, a.lossless)
            k, j, count, sample_count, avg = start, 0, 0, 0, None
            while True:
                meta, data = read_record(proc.stdout)
                if meta.get('kind') == 'done':
                    if k != end + 1 or j or meta.get('frames') != count:
                        raise RenderFailure(f'capture missing frames: expected {end-start+1}, got {count}')
                    break
                if (meta.get('kind') != 'sample' or meta['frame'] != k or meta['sample'] != j or
                        not 1 <= meta['count'] <= a.max_samples):
                    raise RenderFailure('capture sample sequence is invalid')
                expected = C.sample_times(k / info['fps'], info['fps'], info['duration'], info.get('cuts', []),
                    info.get('smears', []), info.get('fast', []), a.shutter,
                    1 if a.preview else a.samples, 1 if a.preview else a.max_samples)
                if meta['count'] != len(expected) or abs(meta['time_s'] - expected[j]) > 1e-9:
                    raise RenderFailure('capture scheduler disagrees with renderer contract')
                with Image.open(io.BytesIO(data)) as im:
                    if im.size != (w, h):
                        raise RenderFailure(f'capture size {im.size}, expected {(w,h)}')
                    rgb = np.asarray(im.convert('RGB'))
                value = C.linear(rgb) if a.blend == 'linear' else rgb.astype(np.float32) / 255
                if j == 0:
                    avg = value
                else:
                    avg += value
                j += 1
                sample_count += 1
                if j == meta['count']:
                    avg /= j
                    encoder.write(C.finish(avg, k, a.blend, 0 if a.preview else a.bloom,
                        a.bloom_threshold, a.bloom_radii, 0 if a.preview else a.grain, not a.no_dither))
                    count += 1
                    k += 1
                    j = 0
            if proc.stdout.read(1):
                raise RenderFailure('trailing data after capture completion')
            proc.wait()
            if proc.returncode:
                raise RenderFailure('capture worker failed')
            encoder.close()
            encoder = None
            return {'from': start, 'to': end, 'frames': count, 'samples': sample_count,
                    'chromium': header['browser'], 'playwright': header['playwright'], 'executable': header['executable']}
        except Exception as exc:
            # Closing the bounded pipe makes Node handle EPIPE and close its browser, rather
            # than forcibly terminating Node and leaving Chromium behind on Windows.
            proc.stdout.close()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait()
            log.seek(0)
            detail = log.read().decode('utf-8', 'replace')
            raise RenderFailure(str(exc) + ('\n' + detail[-3000:] if detail else ''))
        finally:
            proc.stdout.close()
            if encoder:
                encoder.abort()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('folder')
    p.add_argument('--out', help='new output path; default FOLDER_WIDTHxHEIGHT beside the source folder')
    p.add_argument('--size', help='CSS layout size WxH, e.g. 1080x1920 or 1080x1080')
    p.add_argument('--page', default='index.html', help='relative local entry page, may include query parameters')
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--force', action='store_true', help='override memory estimate guard')
    p.add_argument('--res', choices=('720', '1080', '2160'), default='1080')
    p.add_argument('--from', dest='start', type=int, default=0)
    p.add_argument('--to', dest='end', type=int)
    p.add_argument('--shutter', type=float, default=180)
    p.add_argument('--samples', type=int, default=4)
    p.add_argument('--max-samples', type=int, default=32)
    p.add_argument('--blend', choices=('linear', 'gamma'), default='linear')
    p.add_argument('--bloom', type=float, default=0)
    p.add_argument('--bloom-threshold', type=float, default=.8)
    p.add_argument('--bloom-radii', type=float, nargs=2, default=(3, 12), metavar=('NEAR', 'FAR'))
    p.add_argument('--grain', type=float, default=0)
    p.add_argument('--no-dither', action='store_true')
    p.add_argument('--format', choices=('png', 'jpeg'), default='png', help='capture PNG is exact; JPEG is lossy')
    p.add_argument('--quality', type=int, default=92)
    p.add_argument('--crf', type=float, default=14)
    p.add_argument('--level')
    p.add_argument('--lossless', action='store_true')
    p.add_argument('--preview', action='store_true')
    p.add_argument('--node')
    p.add_argument('--playwright')
    p.add_argument('--browser')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    if a.size:
        import re
        size = re.fullmatch(r'(\d+)[xX](\d+)', a.size)
        if not size or min(int(x) for x in size.groups()) < 2:
            p.error('--size must be WxH, at least 2 pixels per side')
    if (a.workers < 1 or a.samples < 1 or a.max_samples < 1 or a.start < 0 or not 0 <= a.quality <= 100 or
            not all(math.isfinite(x) and x >= 0 for x in [a.shutter, a.bloom, a.bloom_threshold, a.grain, *a.bloom_radii])
            or not math.isfinite(a.crf) or not 0 <= a.crf <= 51):
        p.error('invalid workers, sample count, range, quality or finish settings')
    a.node = a.node or C.find_tool('node')
    a.ffmpeg, a.ffprobe = C.find_tool('ffmpeg', a.ffmpeg), C.find_tool('ffprobe', a.ffprobe)
    source = Path(a.folder).resolve()
    output = Path(a.out).resolve() if a.out else source.parent / (source.name + '_pending' + ('.mkv' if a.lossless else '.mp4'))
    if not all((a.node, a.ffmpeg, a.ffprobe)):
        print('film_render.py: Node, FFmpeg and ffprobe are required', file=sys.stderr)
        return 2
    if not source.is_dir() or (a.out and (output.exists() or Path(str(output) + '.manifest.json').exists())):
        print('film_render.py: source must be a folder and output/manifest must be new paths', file=sys.stderr)
        return 2
    if source == output.parent or source in output.parents:
        print('film_render.py: place output outside the source folder', file=sys.stderr)
        return 2
    if a.lossless and output.suffix.lower() != '.mkv':
        p.error('--lossless needs a .mkv output (RGB FFV1/Matroska)')
    started = time.perf_counter()
    server = thread = None
    try:
        avail = C.free_memory() if not a.force else None
        if avail is not None and avail < 512 * 1024 ** 2:
            raise ValueError('less than 512 MiB free for capture inspection; --force overrides')
        with tempfile.TemporaryDirectory(prefix='lf-render-', dir=output.parent if output.parent.is_dir() else None) as tmp:
            tmp = Path(tmp)
            frozen = tmp / 'frozen'
            # Reject symlinks: copy custody must never reach outside the named film folder.
            for root, dirs, files in os.walk(source, followlinks=False):
                if any((Path(root) / name).is_symlink() for name in dirs + files):
                    raise ValueError('source contains a symlink; replace it with a local asset before rendering')
            shutil.copytree(source, frozen)
            hashes = {f.relative_to(frozen).as_posix(): C.sha256(f) for f in sorted(frozen.rglob('*')) if f.is_file()}
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietServer, directory=str(frozen)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            if a.page.startswith(('/', '\\')) or '..' in a.page.split('?')[0].split('/') or '#' in a.page:
                raise ValueError('--page must stay inside the film folder')
            page = a.page + ('&' if '?' in a.page else '?') + 'render'
            url = f'http://127.0.0.1:{server.server_port}/{page}'
            r = subprocess.run(worker_command(a, 'info', url), capture_output=True, text=True, encoding='utf-8', errors='replace')
            if r.returncode:
                if any(x in r.stderr for x in ('page error:', 'console error:', 'page.evaluate:', 'forbidden page request:')):
                    raise RenderFailure(r.stderr)
                raise ValueError(r.stderr.strip())
            info = json.loads(r.stdout)
            C.validate_timeline(info)
            end = info['frames'] - 1 if a.end is None else a.end
            if not a.start <= end < info['frames']:
                raise ValueError('frame range outside the film')
            scale = int(a.res) / 1080
            w, h = round(info['width'] * scale), round(info['height'] * scale)
            if not a.out:
                output = source.parent / (f'{source.name}_{w}x{h}' + ('.mkv' if a.lossless else '.mp4'))
                if output.exists() or Path(str(output) + '.manifest.json').exists():
                    raise ValueError('default output or manifest already exists; choose a new --out path')
            if not a.lossless and (w % 2 or h % 2):
                raise ValueError('scaled dimensions must be even for H.264 4:2:0')
            avail = C.free_memory() if not a.force else None
            estimate = (560 * 1024 ** 2 + w * h * 100) * a.workers + 192 * 1024 ** 2
            print(f'memory estimate: {estimate / 1024**2:.0f} MiB for {a.workers} worker(s); '
                  + (f'free {avail / 1024**2:.0f} MiB' if avail is not None else 'guard overridden'), flush=True)
            if avail is not None and estimate > avail:
                raise ValueError('workers exceed estimated free memory; reduce workers/resolution or use --force')
            count = end - a.start + 1
            workers = min(a.workers, count)
            ranges = [(a.start + count * i // workers, a.start + count * (i + 1) // workers - 1) for i in range(workers)]
            parts = [tmp / f'part-{i:03d}{".mkv" if a.lossless else ".mp4"}' for i in range(workers)]
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(render_part, a, url, info, s, e, part, scale) for (s, e), part in zip(ranges, parts)]
                records = [f.result() for f in futures]
            concat = tmp / 'concat.txt'
            # Basenames avoid Windows drive-letter/quote escaping in concat syntax.
            concat.write_text(''.join("file '" + f.name + "'\n" for f in parts), encoding='utf-8')
            assembled = tmp / ('assembled.mkv' if a.lossless else 'assembled.mp4')
            cmd = [a.ffmpeg, '-v', 'error', '-nostdin', '-f', 'concat', '-safe', '0', '-i', str(concat), '-c', 'copy']
            if not a.lossless:
                cmd += ['-movflags', '+faststart']
            r = subprocess.run(cmd + [str(assembled)], capture_output=True, text=True)
            if r.returncode:
                raise RenderFailure('concat failed: ' + r.stderr[-1000:])
            decoded = C.decoded_count(a.ffprobe, assembled)
            if decoded != count:
                raise RenderFailure(f'frame count: expected {count}, decoded {decoded}')
            manifest = {'version': 1, 'source': str(source), 'frozen_sha256': hashes, 'info': info,
                        'output': str(output),
                        'tool_sha256': {name: C.sha256(HERE / name) for name in
                                        ('film_render.py', 'film_capture.mjs', 'render_common.py')},
                        'settings': vars(a), 'decoded_frames': decoded, 'parts': records,
                        'versions': {'python': sys.version, 'numpy': np.__version__,
                                     'playwright': records[0]['playwright'], 'chromium': records[0]['chromium'],
                                     'pillow': Image.__version__, 'ffmpeg': C.version(a.ffmpeg),
                                     'ffprobe': C.version(a.ffprobe),
                                     'node': subprocess.check_output([a.node, '--version'], text=True).strip()},
                        'output_sha256': C.sha256(assembled), 'wall_s': round(time.perf_counter() - started, 3),
                        'audio': 'intentionally absent', 'not_checked': 'normal-speed viewing; page purity; display appearance'}
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(assembled), str(output))
            Path(str(output) + '.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
            print(f'{decoded} frames -> {output}; {manifest["wall_s"]:.3f} s '
                  f'({decoded / manifest["wall_s"]:.3f} output frames/s); audio intentionally absent')
        return 0
    except RenderFailure as exc:
        print('film_render.py: ' + str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print('film_render.py: could not run: ' + str(exc), file=sys.stderr)
        return 2
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if thread:
            thread.join()


if __name__ == '__main__':
    sys.exit(main())
