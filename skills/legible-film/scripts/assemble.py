#!/usr/bin/env python3
"""Assemble an edit.json into a BT.709 H.264 picture, stems, cues and declarations.

  python assemble.py edit.json --out picture.mp4 --json report.json
  python assemble.py edit.json --out picture.mp4 --spool-gib 4

Snaps are measured on source presentation timestamps and audio sample clocks. The
spool limit bounds temporary RGB storage. Output measurements do not prove a film
has been watched, heard, approved, or cleared for use. Needs numpy, Pillow, FFmpeg
and ffprobe. declared.json contains an ignore string of designed holds and dips
for blank_scan.py and motion_scan.py --ignore, never flash_scan.py. Exit 0 on
completion, 1 when review notes remain, 2 on error.
"""
import argparse
import bisect
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

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motion_scan import Frames
from render_common import Encoder, exact_rate, find_tool
from reframe import bounds, position, probe, analyse, propose, validate_path

CAPTIONS = Path(__file__).with_name('captions.py')


def run(command):
    """Run a process and raise a useful error on failure."""
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('command failed: ' + result.stderr[-1200:])
    return result


def write_json(path, data):
    """Write UTF-8 JSON with explicit indentation."""
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=2)


def nearest(times, value):
    """Choose the nearest decoded timestamp, breaking ties towards the earlier frame."""
    index = bisect.bisect_left(times, value)
    return min((max(0, index - 1), min(index, len(times) - 1)), key=lambda i: abs(times[i] - value))


def source_path(root, sources, name):
    """Resolve a source key or a path relative to edit.json."""
    entry = sources.get(name, name)
    filename = entry['file'] if isinstance(entry, dict) else entry
    return str((root / filename).resolve())


def has_filter(ffmpeg, name):
    """Check the filters available in this FFmpeg build."""
    result = subprocess.run([ffmpeg, '-hide_banner', '-filters'], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('cannot inspect FFmpeg filters')
    return name in set(re.findall(r'^\s*[TSC.]{2,3}\s+(\S+)', result.stdout, re.MULTILINE))


def colour_filter(stream, width, height):
    """Build a source-aware SDR conversion and describe every assumption."""
    matrix = stream.get('color_space', 'unknown')
    transfer = stream.get('color_transfer', 'unknown')
    primaries = stream.get('color_primaries', 'unknown')
    field = stream.get('field_order', 'unknown')
    assumed = []
    fallback = 'smpte170m' if width <= 1024 and height <= 576 else 'bt709'
    if matrix in ('unknown', 'unspecified', 'reserved', None):
        matrix = fallback
        assumed.append('matrix assumed ' + matrix + ' from source size')
    if transfer in ('unknown', 'unspecified', 'reserved', None):
        transfer = fallback
        assumed.append('transfer assumed ' + transfer + ' from source size')
    if primaries in ('unknown', 'unspecified', 'reserved', None):
        primaries = fallback
        assumed.append('primaries assumed ' + primaries + ' from source size')
    filters = []
    if field not in ('unknown', 'progressive', None):
        filters.append('bwdif=mode=send_frame:parity=auto:deint=all')
    # Explicit tags supply zscale's input interpretation even for untagged files.
    if matrix != 'gbr':
        filters.append(f'setparams=colorspace={matrix}:color_trc={transfer}:color_primaries={primaries}')
    hdr = transfer in ('smpte2084', 'arib-std-b67')
    if hdr:
        filters.extend(['zscale=t=linear:npl=100', 'format=gbrpf32le', 'zscale=p=bt709',
                        'tonemap=tonemap=hable:desat=0', 'zscale=t=bt709:m=bt709:r=tv', 'format=yuv420p'])
        conversion = 'HDR to BT.709 SDR: zscale linear, Hable tone map and BT.709 output'
    elif matrix == 'gbr':
        conversion = 'RGB decoded directly; output encoded as BT.709'
    else:
        filters.extend(['format=yuv444p', 'colorspace=all=bt709:range=tv',
                        'scale=out_color_matrix=bt709:out_range=tv'])
        conversion = f'{matrix}/{transfer}/{primaries} converted to BT.709'
    filters.append('format=rgb24')
    return ','.join(filters), assumed, conversion


def probe_source(ffprobe, filename):
    """Read stream metadata and count decoded frames before reserving disk."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0',
               '-show_streams', '-of', 'json', filename]
    stream = json.loads(run(command).stdout)['streams'][0]
    count = 0
    width, height = probe(ffprobe, filename)
    return stream, count, width, height


def conform(ffmpeg, ffprobe, edit, root, temp, spool_limit):
    """Seek and spool only each requested picture range, with a one-second handle."""
    cache = {}
    properties = {}
    required = 0
    for number, item in enumerate(edit['picture']):
        filename = source_path(root, edit['sources'], item['src'])
        stream, _, width, height = probe_source(ffprobe, filename)
        if stream.get('color_transfer') in ('smpte2084', 'arib-std-b67') and not has_filter(ffmpeg, 'zscale'):
            raise RuntimeError('this FFmpeg build lacks zscale; HDR conversion needs a build with libzimg')
        vf, assumptions, conversion = colour_filter(stream, width, height)
        start = max(0.0, float(item['in']) - 1.0)
        stop = float(item['out']) + 1.0
        if stop <= start:
            raise ValueError('invalid picture range')
        rawpath = os.path.join(temp, f'source-{number}.rgb')
        reader = Frames(ffmpeg, filename, f'trim=start={start}:end={stop},' + vf,
                        width * height * 3, ['-ss', str(start), '-copyts'])
        count = 0
        with open(rawpath, 'wb') as output:
            for raw in reader:
                required += len(raw)
                if required > spool_limit or shutil.disk_usage(temp).free < len(raw) + 256 * 1024 * 1024:
                    reader.proc.kill()
                    reader.proc.wait()
                    reader.reader.join()
                    reader.proc.stdout.close()
                    raise ValueError('RGB spool exceeds limit or disk reserve')
                output.write(raw)
                count += 1
        times = reader.times(count)
        end = reader.end()
        if end <= times[-1]:
            raise ValueError('cannot determine final decoded frame duration: ' + filename)
        intervals = np.diff(times)
        variable = bool(len(intervals) > 1 and np.max(intervals) - np.min(intervals) > .0001)
        rotation = float(stream.get('tags', {}).get('rotate', 0))
        for side_data in stream.get('side_data_list', []):
            rotation = float(side_data.get('rotation', rotation))
        properties[filename] = {'width': width, 'height': height, 'source_matrix': stream.get('color_space'),
                                'source_transfer': stream.get('color_transfer'),
                                'source_primaries': stream.get('color_primaries'),
                                'field_order': stream.get('field_order'), 'variable_timing': variable,
                                'rotation_degrees': rotation, 'rotation_conversion': 'FFmpeg autorotation',
                                'conversion': conversion, 'assumptions': assumptions, 'filter': vf,
                                'time_base': stream.get('time_base', '0/1')}
        numerator, denominator = stream.get('time_base', '0/1').split('/')
        tick = float(numerator) / float(denominator)
        cache[number] = (rawpath, width, height, times, end, tick)
    return cache, properties, required


def plan_picture(edit, root, cache, ffmpeg, ffprobe, temp):
    """Snap picture edits, place joins, and resolve crop paths on the edit clock."""
    clips = []
    snaps = []
    cues = []
    cuts = []
    dissolves = []
    width, height = edit['size']
    for number, item in enumerate(edit['picture']):
        name = item['src']
        filename = source_path(root, edit['sources'], name)
        rawpath, sw, sh, times, end, tick = cache[number]
        boundaries = times + [end]
        first = nearest(boundaries, float(item['in']))
        last = nearest(boundaries, float(item['out']))
        if first >= last or first >= len(times):
            raise ValueError('empty snapped picture range for ' + name)
        speed = float(item.get('speed', 1))
        mode = item.get('retime', 'nearest')
        if not math.isfinite(speed) or speed <= 0 or mode not in ('nearest', 'blend', 'motion'):
            raise ValueError('invalid picture speed or retime mode')
        duration = (boundaries[last] - boundaries[first]) / speed
        join = item.get('join', {'kind': 'cut'})
        kind = join.get('kind', 'cut')
        overlap = float(join.get('dur', 0)) if kind != 'cut' else 0
        if kind not in ('cut', 'dissolve', 'dip') or overlap < 0:
            raise ValueError('invalid join')
        if overlap and (not clips or overlap > min(duration, clips[-1]['duration'])):
            raise ValueError('invalid overlap duration')
        at = clips[-1]['at'] + clips[-1]['duration'] - overlap if clips else 0
        if len(clips) > 1 and at < clips[-2]['at'] + clips[-2]['duration']:
            raise ValueError('three-way joins are not supported')
        if clips:
            cuts.append(at)
            # A join is a candidate sound moment, withheld unless the edit asks for it: most footage cuts are silent.
            cues.append({'id': f'join-{len(clips)}', 't': at, 'sound': 'optional',
                         'role': join.get('role', 'whoosh'), 'sync': 'attack',
                         'enabled': bool(join.get('sound', False))})
            if kind == 'dissolve':
                dissolves.append({'start': at, 'end': at + overlap})
        for point, requested, actual in (('in', item['in'], boundaries[first]),
                                         ('out', item['out'], boundaries[last])):
            snaps.append({'src': name, 'point': point, 'requested': requested,
                          'snapped': actual, 'delta': actual - float(requested), 'clock': 'video PTS'})
        crop = item.get('crop', {})
        path = crop.get('path', [[0, .5, .5]])
        if path == 'auto':
            analysis_width = 320
            analysis_height = max(2, round(sh / sw * analysis_width / 2) * 2)
            crop_width, crop_height = bounds(sw, sh, width / height, float(crop.get('zoom', 1)))
            clock, subjects, _ = analyse(ffmpeg, filename, analysis_width, analysis_height,
                                         boundaries[first], boundaries[last])
            selected = [(t, box) for t, box in zip(clock, subjects) if boundaries[first] <= t < boundaries[last]]
            if not selected:
                raise ValueError('no frames for automatic crop')
            local_times = [(t - boundaries[first]) / speed for t, _ in selected]
            path = propose(local_times, [box for _, box in selected], crop_width, crop_height, .2)
        elif isinstance(path, str):
            with open(root / path, encoding='utf-8') as file:
                loaded = json.load(file)
            path = loaded.get('path', loaded) if isinstance(loaded, dict) else loaded
        path = validate_path(path)
        fit = item.get('fit', 'cover')
        if fit not in ('cover', 'contain'):
            raise ValueError('invalid fit')
        clips.append({'src': name, 'file': filename, 'raw': rawpath, 'sw': sw, 'sh': sh, 'times': times,
                      'start': boundaries[first], 'stop': boundaries[last], 'duration': duration, 'at': at,
                      'speed': speed, 'mode': mode, 'kind': kind, 'overlap': overlap,
                      'colour': join.get('color', 'black'), 'crop': path, 'zoom': float(crop.get('zoom', 1)),
                      'fit': fit, 'background': item.get('background', 'black'), 'time_tick': tick})
    return clips, snaps, cues, cuts, dissolves


def audio_packet_end(ffprobe, filename):
    """Find the last audio packet's end without retaining the packet list."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_packets',
               '-show_entries', 'packet=pts_time,duration_time', '-of', 'csv=p=0', filename]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace')
    end = None
    for line in proc.stdout:
        values = line.strip().split(',')
        try:
            timestamp, duration = float(values[0]), float(values[1])
        except (ValueError, IndexError):
            continue
        if math.isfinite(timestamp) and math.isfinite(duration) and duration > 0:
            end = max(end if end is not None else -math.inf, timestamp + duration)
    proc.stdout.close()
    error = proc.stderr.read()
    if proc.wait() or end is None:
        raise ValueError('cannot determine audio stream end: ' + (error.strip() or filename))
    return end


def audio_rate(ffprobe, filename):
    """Find the rate and audio stream bounds on FFmpeg's source presentation clock."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
               'stream=sample_rate,start_time,duration:stream_tags=DURATION:format=start_time',
               '-of', 'json', filename]
    probe_data = json.loads(run(command).stdout)
    stream = probe_data['streams'][0]
    rate = int(stream['sample_rate'])
    if rate <= 0:
        raise ValueError('invalid sample rate: ' + filename)
    origin = float(probe_data.get('format', {}).get('start_time', 0))
    start = float(stream.get('start_time', origin))
    duration = stream.get('duration')
    tag = stream.get('tags', {}).get('DURATION')
    if duration is not None:
        end = start + float(duration)
    elif tag:
        hours, minutes, seconds = tag.split(':')
        end = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    else:
        end = audio_packet_end(ffprobe, filename)
    return rate, start - origin, end - origin


def render_audio(ffmpeg, ffprobe, edit, root, clips, total, temp, output_dir, notes):
    """Render faded audio edits on independent sample clocks into track stems."""
    tracks = {}
    snaps = []
    for number, item in enumerate(edit.get('audio', [])):
        track = item['track']
        name = item['src']
        filename = source_path(root, edit['sources'], name)
        at = float(item.get('at', 0))
        rate, stream_start, source_end = audio_rate(ffprobe, filename)
        start = round(float(item['in']) * rate) / rate
        requested_end = round(float(item['out']) * rate) / rate
        end = min(requested_end, round(source_end * rate) / rate)
        if end < requested_end:
            notes.append(f'Audio {name} out clamped from {requested_end:.6f} to {end:.6f} s.')
        fade = float(item.get('fade_ms', 15)) / 1000
        if not track or any(char in track for char in ('/', '\\', ':')) or end <= start or fade < 0:
            raise ValueError('invalid audio item')
        for point, actual in (('in', start), ('out', end)):
            requested = float(item[point])
            snaps.append({'src': name, 'point': point, 'requested': requested, 'snapped': actual,
                          'delta': actual - requested, 'clock': 'audio sample', 'sample_rate': rate,
                          'stream_start_s': stream_start})
        speeds = {clip['speed'] for clip in clips if clip['src'] == name and start < clip['stop']
                  and end > clip['start']}
        if len(speeds) > 1:
            raise ValueError('ambiguous audio retime speed for ' + name)
        speed = next(iter(speeds), 1.0)
        duration = (end - start) / speed
        filters = ['aresample=async=1:first_pts=0',
                   f'atrim=start_sample={round(start * rate)}:end_sample={round(end * rate)}',
                   'asetpts=PTS-STARTPTS']
        remaining = speed
        while remaining > 2:
            filters.append('atempo=2')
            remaining /= 2
        while remaining < .5:
            filters.append('atempo=.5')
            remaining *= 2
        filters.extend([f'atempo={remaining}', f"volume={float(item.get('gain_db', 0))}dB", 'aresample=48000'])
        edge = min(fade, duration / 2)
        if edge:
            filters.extend([f'afade=t=in:st=0:d={edge}', f'afade=t=out:st={duration - edge}:d={edge}'])
        if at < 0:
            filters.extend([f'atrim=start={-at}', 'asetpts=PTS-STARTPTS'])
        elif at > 0:
            # Delay in samples avoids rounding the edit clock to milliseconds.
            filters.append(f'adelay={round(at * 48000)}S:all=1')
        part = os.path.join(temp, f'audio-{number}.wav')
        command = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', filename, '-vn',
                   '-af', ','.join(filters), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', part]
        run(command)
        tracks.setdefault(track, []).append(part)
    for track, parts in tracks.items():
        command = [ffmpeg, '-hide_banner', '-v', 'error', '-y']
        for part in parts:
            command.extend(['-i', part])
        inputs = ''.join(f'[{index}:a]' for index in range(len(parts)))
        graph = f'{inputs}amix=inputs={len(parts)}:duration=longest:normalize=0,apad,atrim=duration={total}[a]'
        command.extend(['-filter_complex', graph, '-map', '[a]', '-c:a', 'pcm_s16le',
                        str(output_dir / (track + '.wav'))])
        run(command)
    return snaps


def motion_retimes(ffmpeg, clips, properties, fps, temp, spool_limit, already_used):
    """Interpolate each motion-retimed clip before the final encoder starts."""
    requested = sum((math.ceil(clip['duration'] * fps) + 4) * clip['sw'] * clip['sh'] * 3
                    for clip in clips if clip['mode'] == 'motion')
    if already_used + requested > spool_limit or shutil.disk_usage(temp).free < requested + 256 * 1024 * 1024:
        raise ValueError('motion interpolation exceeds available RGB spool budget')
    for number, clip in enumerate(clips):
        if clip['mode'] != 'motion':
            continue
        path = os.path.join(temp, f'motion-{number}.rgb')
        # PTS retiming precedes interpolation so interpolation runs on the output clock.
        vf = (f"trim=start={clip['start']}:end={clip['stop']},"
              f"setpts=(PTS-STARTPTS)/{clip['speed']},tpad=stop_mode=clone:stop_duration=1,"
              f"minterpolate=fps={fps}:mi_mode=mci,trim=duration={clip['duration']},"
              + properties[clip['file']]['filter'])
        reader = Frames(ffmpeg, clip['file'], vf, clip['sw'] * clip['sh'] * 3,
                        ['-ss', str(max(0.0, clip['start'] - 1.0)), '-copyts'])
        count = 0
        with open(path, 'wb') as output:
            for raw in reader:
                output.write(raw)
                count += 1
                if count > math.ceil(clip['duration'] * fps) + 4:
                    raise RuntimeError('interpolated frames exceed disk reservation')
        times = reader.times(count)
        clip['motion_raw'] = path
        clip['motion_times'] = times


def prepare_overlays(edit, root, width, cues, notes):
    """Load image overlays and collect captions for a later burn pass."""
    images = []
    captions = []
    for overlay in edit.get('overlays', []):
        kind = overlay.get('kind')
        if kind == 'captions':
            if CAPTIONS.is_file():
                spec = importlib.util.spec_from_file_location('legible_captions', CAPTIONS)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # Read now so a malformed caption file fails before rendering; captions never become sound cues.
                module.read_input(root / overlay['file'])
                captions.append(overlay)
            else:
                notes.append('Captions skipped: captions.py is not present at ' + str(CAPTIONS))
            continue
        if kind != 'image':
            raise ValueError('unknown overlay kind')
        filename = source_path(root, edit['sources'], overlay['src'])
        image = Image.open(filename).convert('RGBA')
        ow = max(1, round(float(overlay['w']) * width))
        oh = max(1, round(image.height * ow / image.width))
        image = image.resize((ow, oh), Image.Resampling.LANCZOS)
        start = float(overlay['from'])
        end = float(overlay['to'])
        fade = float(overlay.get('fade_ms', 0)) / 1000
        if end <= start or fade < 0:
            raise ValueError('invalid overlay timing')
        cues.append({'id': f'overlay-{len(images)}', 't': start, 'sound': 'optional',
                     'role': overlay.get('role', 'pop'), 'sync': 'attack',
                     'enabled': bool(overlay.get('sound', False))})
        images.append((image, overlay, start, end, fade))
    return images, captions


def render_clip(clip, time, handles, width, height):
    """Sample, crop and scale one picture clip at an edit time."""
    if clip['mode'] == 'motion':
        sample_time = max(0, time - clip['at'])
        times = clip['motion_times']
        rawpath = clip['motion_raw']
    else:
        sample_time = clip['start'] + max(0, time - clip['at']) * clip['speed']
        times = clip['times']
        rawpath = clip['raw']
    precision = 0.5 * 10 ** (math.floor(math.log10(max(abs(sample_time), 1))) - 5)
    interval = times[1] - times[0] if len(times) > 1 else 1.0
    tolerance = min(interval * .1, max(1e-6, precision, clip['time_tick'] * .50001))
    index = max(0, min(len(times) - 1, bisect.bisect_right(times, sample_time + tolerance) - 1))

    def get_frame(frame_index):
        """Read a spooled frame by its PTS-selected index."""
        handle = handles[rawpath]
        size = clip['sw'] * clip['sh'] * 3
        handle.seek(frame_index * size)
        raw = handle.read(size)
        if len(raw) != size:
            raise RuntimeError('short decoded frame')
        return Image.frombytes('RGB', (clip['sw'], clip['sh']), raw)

    image = get_frame(index)
    if clip['mode'] == 'blend' and index + 1 < len(times) and times[index + 1] < clip['stop']:
        fraction = (sample_time - times[index]) / (times[index + 1] - times[index])
        image = Image.blend(image, get_frame(index + 1), max(0, min(1, fraction)))
    if clip['fit'] == 'contain':
        image.thumbnail((width, height), Image.Resampling.LANCZOS)
        canvas = Image.new('RGB', (width, height), clip['background'])
        canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
        return canvas
    cw, ch = bounds(clip['sw'], clip['sh'], width / height, clip['zoom'])
    cx, cy = position(clip['crop'], max(0, time - clip['at']))
    cx = min(1 - cw / 2, max(cw / 2, cx))
    cy = min(1 - ch / 2, max(ch / 2, cy))
    box = ((cx - cw / 2) * clip['sw'], (cy - ch / 2) * clip['sh'],
           (cx + cw / 2) * clip['sw'], (cy + ch / 2) * clip['sh'])
    return image.crop(box).resize((width, height), Image.Resampling.LANCZOS)


def render_picture(ffmpeg, clips, images, width, height, fps, total, output):
    """Composite picture and image overlays into the shared capped encoder."""
    rawpaths = {clip['raw'] for clip in clips} | {clip['motion_raw'] for clip in clips
                                                  if clip['mode'] == 'motion'}
    handles = {path: open(path, 'rb') for path in rawpaths}
    encoder = Encoder(ffmpeg, output, width, height, fps)
    count = math.ceil(total * fps - 1e-9)
    try:
        for number in range(count):
            time = number / float(fps)
            active = [clip for clip in clips if clip['at'] <= time < clip['at'] + clip['duration']]
            if not active:
                raise RuntimeError(f'gap in picture at {time:.6f}')
            image = render_clip(active[0], time, handles, width, height)
            for clip in active[1:]:
                incoming = render_clip(clip, time, handles, width, height)
                fraction = min(1, max(0, (time - clip['at']) / clip['overlap'])) if clip['overlap'] else 1
                if clip['kind'] == 'dissolve':
                    # The outgoing image stays opaque beneath the arriving image.
                    image = Image.blend(image, incoming, fraction)
                elif clip['kind'] == 'dip':
                    colour = Image.new('RGB', (width, height), clip['colour'])
                    if fraction < .5:
                        image = Image.blend(image, colour, fraction * 2)
                    else:
                        image = Image.blend(colour, incoming, (fraction - .5) * 2)
                else:
                    image = incoming
            for overlay, spec, start, end, fade in images:
                if start <= time < end:
                    opacity = min(1, (time - start) / fade, (end - time) / fade) if fade else 1
                    layer = overlay.copy()
                    layer.putalpha(layer.getchannel('A').point(lambda value: round(value * max(0, opacity))))
                    image.paste(layer, (round(float(spec.get('x', 0)) * width),
                                        round(float(spec.get('y', 0)) * height)), layer)
            encoder.write(np.asarray(image))
        encoder.close()
    except BaseException:
        encoder.abort()
        raise
    finally:
        for handle in handles.values():
            handle.close()
    return count


def caption_options(overlay):
    """Pass a captions overlay's placement and style fields to captions.py burn."""
    options = []
    for key, flag in (('safe', '--safe'), ('font', '--font'), ('font_size', '--font-size')):
        if key in overlay:
            value = overlay[key]
            options += [flag, ','.join(str(v) for v in value) if isinstance(value, list) else str(value)]
    for box in overlay.get('avoid', []):
        options += ['--avoid', ','.join(str(v) for v in box)]
    for key, flag in (('plate', '--plate'), ('highlight', '--highlight')):
        if overlay.get(key):
            options.append(flag)
    return options


def burn_captions(captions, root, picture, temp):
    """Burn captions with captions.py after the picture is rendered, one overlay at a time."""
    current = picture
    for index, overlay in enumerate(captions):
        output = Path(temp) / f'caption-{index}.mp4'
        command = [sys.executable, '-I', str(CAPTIONS), 'burn', str(current), str(root / overlay['file']),
                   '--out', str(output)]
        command += caption_options(overlay)
        run(command)
        current = output
    return current


def cap_caption_encode(ffmpeg, source, destination, width, height, fps):
    """Restore the shared level-capped encode after the captions tool's burn pass."""
    reader = Frames(ffmpeg, str(source), 'format=rgb24', width * height * 3)
    encoder = Encoder(ffmpeg, destination, width, height, fps)
    count = 0
    try:
        for raw in reader:
            encoder.write(np.frombuffer(raw, np.uint8).reshape(height, width, 3))
            count += 1
        reader.times(count)
        encoder.close()
    except BaseException:
        encoder.abort()
        raise


def export(edit, out, report_path, temp, stage, picture, cues, cuts, dissolves, report):
    """Write sidecars in staging and move them to their final names after success."""
    # The cue list carries the exact rate as a number, which the sound tools read with float().
    write_json(stage / 'edit-cues.json', {'fps': float(exact_rate(edit['fps'])),
                                         'events': sorted(cues + edit.get('cues', []), key=lambda cue: cue['t'])})
    holds = edit.get('holds', [])
    dips = [{'start': clip['at'], 'end': clip['at'] + clip['overlap']}
            for clip in report.pop('_clips') if clip['kind'] == 'dip']
    ranges = sorted((float(x['start']), float(x['end'])) if isinstance(x, dict)
                    else (float(x[0]), float(x[1])) for x in holds + dips)
    ignore = ','.join(f'{start:.3f}-{end:.3f}' for start, end in ranges)
    write_json(stage / 'declared.json', {'cuts': cuts, 'holds': holds, 'dissolves': dissolves, 'ignore': ignore})
    write_json(stage / 'assemble-report.json', report)
    pairs = [(Path(picture), out)]
    for path in stage.iterdir():
        if path.name == 'assemble-report.json' and report_path:
            target = Path(report_path).resolve()
        else:
            target = out.parent / path.name
        pairs.append((path, target))
    if len({target for _, target in pairs}) != len(pairs):
        raise ValueError('output paths collide')
    backups = []
    installed = []
    try:
        for index, (_, target) in enumerate(pairs):
            if target.exists():
                backup = Path(temp) / f'previous-output-{index}'
                os.replace(target, backup)
                backups.append((backup, target))
        for source, target in pairs:
            os.replace(source, target)
            installed.append(target)
    except OSError:
        for target in installed:
            target.unlink(missing_ok=True)
        for backup, target in reversed(backups):
            os.replace(backup, target)
        raise



def main():
    """Validate the edit, stage outputs and publish them only after rendering succeeds."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('edit')
    parser.add_argument('--out', required=True)
    parser.add_argument('--json')
    parser.add_argument('--spool-gib', type=float, default=8, help='maximum raw RGB spool, default 8 GiB')
    args = parser.parse_args()
    try:
        ffmpeg = find_tool('ffmpeg')
        ffprobe = find_tool('ffprobe')
        if not ffmpeg or not ffprobe:
            raise ValueError('FFmpeg and ffprobe are required')
        if not math.isfinite(args.spool_gib) or args.spool_gib <= 0:
            raise ValueError('spool-gib must be positive')
        edit_path = Path(args.edit).resolve()
        root = edit_path.parent
        edit = json.loads(edit_path.read_text(encoding='utf-8'))
        if edit.get('version') != 1 or not edit.get('picture'):
            raise ValueError('version 1 and at least one picture item are required')
        width, height = map(int, edit['size'])
        # A decimal NTSC rate (29.97) means 30000/1001; the encoders get the exact rate, the arithmetic a float.
        rate = exact_rate(edit['fps'])
        fps = float(rate)
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError('size must be positive and even')
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        filenames = {source_path(root, edit['sources'], item['src']) for item in edit['picture']}
        filenames.update(source_path(root, edit['sources'], item['src']) for item in edit.get('audio', []))
        targets = {out, out.parent / 'edit-cues.json', out.parent / 'declared.json'}
        targets.add(Path(args.json).resolve() if args.json else out.parent / 'assemble-report.json')
        targets.update(out.parent / (item['track'] + '.wav') for item in edit.get('audio', []))
        output_targets = targets
        if any(str(target) in filenames for target in output_targets) or edit_path in output_targets:
            raise ValueError('output must not overwrite an edit or source')
        picture_sources = {source_path(root, edit['sources'], item['src']) for item in edit['picture']}
        notes = []
        with tempfile.TemporaryDirectory(prefix='legible-footage-', dir=out.parent) as temp:
            stage = Path(temp) / 'stage'
            stage.mkdir()
            limit = int(args.spool_gib * 1024 ** 3)
            cache, properties, used = conform(ffmpeg, ffprobe, edit, root, temp, limit)
            clips, snaps, cues, cuts, dissolves = plan_picture(edit, root, cache, ffmpeg, ffprobe, temp)
            total = clips[-1]['at'] + clips[-1]['duration']
            if total <= 0:
                raise ValueError('zero duration')
            motion_retimes(ffmpeg, clips, properties, fps, temp, limit, used)
            images, captions = prepare_overlays(edit, root, width, cues, notes)
            picture = Path(temp) / 'picture.mp4'
            count = render_picture(ffmpeg, clips, images, width, height, rate, total, picture)
            if captions:
                captioned = burn_captions(captions, root, picture, temp)
                picture = Path(temp) / 'caption-capped.mp4'
                cap_caption_encode(ffmpeg, captioned, picture, width, height, rate)
                notes.append('Caption burn was encoded again with the shared level-capped encoder; review legibility.')
            snaps.extend(render_audio(ffmpeg, ffprobe, edit, root, clips, total, temp, stage, notes))
            report = {'duration_s': total, 'frames': count, 'snaps': snaps, 'sources': properties,
                      'spool_budget_bytes': limit, 'source_spool_bytes': used, '_clips': clips,
                      'retimes': [{'src': clip['src'], 'in': clip['start'], 'out': clip['stop'],
                                   'speed': clip['speed'], 'mode': clip['mode']}
                                  for clip in clips if clip['speed'] != 1],
                      'crops': [{'src': clip['src'], 'path': clip['crop'], 'fit': clip['fit'],
                                 'zoom': clip['zoom']} for clip in clips], 'notes': notes}
            export(edit, out, args.json, temp, stage, picture, cues, cuts, dissolves, report)
        print(f'Rendered {count} frames; {len(snaps)} snap points; {len(notes)} review notes.')
        for note in notes:
            print('NOTE: ' + note)
        return 1 if notes else 0
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, TypeError, OverflowError) as error:
        print(f'assemble: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
