"""Synthetic footage editing integration checks. These do not judge perceptual quality."""
import importlib.util
import json
import math
import os
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def ffmpeg(*args, data=None):
    """Run one FFmpeg fixture render and report its failure."""
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', *map(str, args)]
    result = subprocess.run(command, input=data, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-1000:])


def video_frames(path, width, height):
    """Decode all frames of a small synthetic video as RGB."""
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-fps_mode', 'passthrough', '-f', 'rawvideo',
                             '-pix_fmt', 'rgb24', '-'], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width, 3)


def linear_assembly_frames(path, width, height, scripts_dir):
    """Decode linearly with the same colour conversion used for assembled output."""
    spec = importlib.util.spec_from_file_location('footage_reference_assembler', Path(scripts_dir) / 'assemble.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stream, _, source_width, source_height = module.probe_source('ffprobe', str(path))
    vf, _, _ = module.colour_filter(stream, int(stream['width']), int(stream['height']))
    vf += f',scale={source_width}:{source_height}:flags=lanczos,setsar=1'
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vf', vf, '-fps_mode', 'passthrough',
                             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True)
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width, 3)


def write_edit(path, edit):
    """Write one independent version 1 edit fixture."""
    Path(path).write_text(json.dumps(edit), encoding='utf-8')


def fixture(j):
    """Build a burned counter, fixed brand patch, tone and two transient markers."""
    width, height, fps, count = 160, 90, 10, 40
    frames = []
    for number in range(count):
        image = Image.new('RGB', (width, height), (60, 70, 80))
        draw = ImageDraw.Draw(image)
        draw.text((10, 10), str(number), fill='white')
        # Binary counter is a readable burned index with robust independently checked cells.
        for bit in range(6):
            colour = 'white' if number & (1 << bit) else 'black'
            draw.rectangle((10 + bit * 15, 28, 20 + bit * 15, 40), fill=colour)
        draw.rectangle((112, 55, 150, 85), fill=(48, 128, 192))
        frames.append(np.asarray(image).tobytes())
    rate = 48000
    samples = .12 * np.sin(2 * np.pi * 440 * np.arange(rate * 4) / rate)
    for time in (1.7, 1.9):
        start = round(time * rate)
        samples[start:start + 240] += .6 * np.hanning(480)[:240]
    pcm = np.int16(np.clip(samples, -1, 1) * 32767)
    with wave.open(j('footage-audio.wav'), 'wb') as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(pcm.tobytes())
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', fps,
           '-i', 'pipe:0', '-i', j('footage-audio.wav'), '-map', '0:v', '-map', '1:a',
           '-c:v', 'ffv1', '-c:a', 'pcm_s16le', j('footage-source.mkv'), data=b''.join(frames))
    return width, height, fps


def counter(frame):
    """Read the six independently sampled cells of the burned binary counter."""
    return sum((1 << bit) for bit in range(6) if float(frame[34, 15 + bit * 15].mean()) > 128)


def assemble(tool, j, name, edit):
    """Run the assembler in a dedicated output directory for one fixture."""
    directory = Path(j(name))
    directory.mkdir(exist_ok=True)
    path = directory / 'edit.json'
    write_edit(path, edit)
    code, output = tool('assemble.py', path, '--out', directory / 'picture.mp4',
                        '--json', directory / 'report.json')
    return code, output, directory


def write_part(path, delay, length, frequency):
    """A stereo 48 kHz part: silence for `delay` seconds, then a tone for `length` seconds."""
    rate = 48000
    samples = np.zeros((round((delay + length) * rate), 2))
    tone = 0.2 * np.sin(2 * np.pi * frequency * np.arange(len(samples) - round(delay * rate)) / rate)
    samples[round(delay * rate):] = tone[:, None]
    with wave.open(str(path), 'wb') as file:
        file.setnchannels(2)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(np.int16(samples * 32767).tobytes())


def check_track_mix(record, j, scripts_dir):
    """assemble.py's track mix ends every time at exactly the film's length. Its earlier graph (amix, then an endless
    apad and atrim) hung FFmpeg 9.0 in about one run in nine while writing silence without end; 40 runs with a 10 s
    limit each would miss that less than once in a hundred suites, and a hang can only cost one 10 s limit."""
    spec = importlib.util.spec_from_file_location('footage_assemble', os.path.join(scripts_dir, 'assemble.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parts = []
    for number, (delay, length, frequency) in enumerate(((0, 1.35, 440), (1.35, 1.45, 660), (2.8, 3.4, 880))):
        parts.append(j(f'footage-mix-{number}.wav'))
        write_part(parts[-1], delay, length, frequency)
    total, out = 5.72, j('footage-mix.wav')
    lengths, failure, started = set(), '', time.time()
    for _ in range(40):
        try:
            module.mix_track('ffmpeg', parts, total, out, seconds=10)
        except RuntimeError as error:
            failure = str(error)[-200:]
            break
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                                'stream=duration_ts', '-of', 'csv=p=0', str(out)], capture_output=True, text=True)
        if probe.stdout.strip().isdigit():
            lengths.add(int(probe.stdout.strip()))
    record("footage: track mixes always finish, padded or trimmed to exactly the film's length (40 runs)",
           not failure and lengths == {round(total * 48000)},
           f'{failure or "no hang"}; lengths {sorted(lengths)}; {time.time() - started:.1f} s')


def check_audio_fidelity(tool, record, j):
    """Unretimed impulses keep their samples; overlapping parts retain float headroom."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_audio_fidelity', scripts / 'assemble.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = Path(j('audio-fidelity'))
    root.mkdir(parents=True, exist_ok=True)
    rate = 48000
    samples = np.zeros(rate * 2, dtype=np.float32)
    for moment in (.75, 1.25, 1.75):
        samples[round(moment * rate):round(moment * rate) + 960] = .5
    source = root / 'pulses.wav'
    with wave.open(str(source), 'wb') as file:
        file.setparams((2, 2, rate, len(samples), 'NONE', 'not compressed'))
        file.writeframes(np.int16(np.repeat(samples[:, None], 2, axis=1) * 32767).tobytes())
    edit = {'sources': {'a': {'file': str(source)}}, 'audio': [
        {'src': 'a', 'track': 'dialogue', 'in': .5, 'out': 1.8, 'at': 0, 'fade_ms': 0}]}
    clip = {'src': 'a', 'speed': 1, 'start': .5, 'stop': 1.8}
    module.render_audio('ffmpeg', 'ffprobe', edit, root, [clip], 1.3, root, root, [])

    def decoded(path):
        proc = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '2', '-ar', str(rate),
                               '-f', 'f32le', '-'], capture_output=True, check=True)
        return np.frombuffer(proc.stdout, '<f4').reshape(-1, 2)[:, 0]

    part = decoded(root / 'audio-0.wav')
    mask = np.abs(part) > .3
    starts = np.flatnonzero(mask & ~np.concatenate(([False], mask[:-1]))) / rate
    expected = np.array([.25, .75, 1.25])
    record('footage: 1x audio preserves pulse positions and the trimmed sample count',
           len(part) == round(1.3 * rate) and len(starts) == 3 and np.max(np.abs(starts - expected)) < .001,
           f'part samples {len(part)}, pulse starts {starts.tolist()}')
    tone = .75 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
    with wave.open(str(source), 'wb') as file:
        file.setparams((2, 2, rate, len(tone), 'NONE', 'not compressed'))
        file.writeframes(np.int16(np.repeat(tone[:, None], 2, axis=1) * 32767).tobytes())
    edit['audio'] = [{'src': 'a', 'track': 'dialogue', 'in': 0, 'out': 1, 'at': 0, 'fade_ms': 0}] * 2
    clip.update(start=0, stop=1)
    module.render_audio('ffmpeg', 'ffprobe', edit, root, [clip], 1, root, root, [])
    mixed = decoded(root / 'dialogue.wav')
    peak = float(np.max(np.abs(mixed))) if len(mixed) else 0
    record('footage: overlapping 0.75-peak tones retain headroom in the mixed stem',
           len(mixed) == rate and 1.48 < peak < 1.52, f'mixed peak {peak:.4f}')


def check_audio_retimes(tool, record, j):
    """Measure actual event locations and pre-padding lengths for two real retimes."""
    spec = importlib.util.spec_from_file_location('case_audio_retimes',
                                                 Path(__file__).resolve().parent.parent / 'assemble.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = Path(j('audio-retimes'))
    root.mkdir(parents=True, exist_ok=True)
    rate = 48000
    original = np.zeros(rate * 3, dtype=np.float32)
    events = np.array([.5, 1.25, 2.0, 2.65])
    for moment in events:
        original[round(moment * rate):round(moment * rate) + 2400] = .5
    source = root / 'source.wav'
    with wave.open(str(source), 'wb') as handle:
        handle.setparams((1, 2, rate, len(original), 'NONE', 'not compressed'))
        handle.writeframes(np.int16(original * 32767).tobytes())
    for speed in (.5, 1.5):
        folder = root / str(speed)
        folder.mkdir(exist_ok=True)
        edit = {'sources': {'a': {'file': str(source)}}, 'audio': [
            {'src': 'a', 'track': 'dialogue', 'in': 0, 'out': 3, 'at': 0, 'fade_ms': 0}]}
        clip = {'src': 'a', 'speed': speed, 'start': 0, 'stop': 3}
        notes = []
        snaps = module.render_audio('ffmpeg', 'ffprobe', edit, root, [clip], 3 / speed, folder, folder, notes)
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder / 'audio-0.wav'),
                                 '-ac', '1', '-f', 'f32le', '-'], capture_output=True, check=True)
        samples = np.frombuffer(result.stdout, '<f4')
        hits = np.flatnonzero(np.abs(samples) > .2) / rate
        starts = hits[np.r_[True, np.diff(hits) > .08]] if len(hits) else np.array([])
        error = float(np.max(np.abs(starts - events / speed))) if len(starts) == len(events) else float('inf')
        duration = next((row for row in snaps if row['point'] == 'retime duration'), {})
        visible = any('transients can move' in note for note in notes)
        record(f'footage: {speed:g}x audio retime measures length and four event positions',
               error < .06 and abs(duration.get('actual_duration_s', 0) - len(samples) / rate) < .001
               and visible, f'event error={error:.4f}s; part={len(samples) / rate:.4f}s; notes={notes}')


def check_nonzero_origin(tool, record, j):
    """Picture and audio source times are relative to a container with start timestamp 5 s."""
    source = Path(j('offset-source.mkv'))
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=2', '-f', 'lavfi', '-i',
           r'aevalsrc=if(lt(t\,0.25)\,0\,0.5*sin(2*PI*440*t)):s=48000:d=2',
           '-map', '0:v', '-map', '1:a', '-c:v', 'ffv1', '-threads', '1', '-c:a', 'pcm_s16le',
           '-output_ts_offset', '5', source)
    edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': 0, 'out': 1}],
            'audio': [{'src': 'a', 'track': 'speech', 'in': 0, 'out': 1, 'at': 0, 'fade_ms': 0}]}
    code, output, directory = assemble(tool, j, 'offset-edit', edit)
    picture = directory / 'picture.mp4'
    stem = directory / 'speech.wav'
    frames = video_frames(picture, 160, 90) if picture.exists() else np.array([])
    onset = None
    if stem.exists():
        pcm = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(stem), '-ac', '1', '-ar', '48000',
                              '-f', 'f32le', '-'], capture_output=True, check=True).stdout
        hits = np.flatnonzero(np.abs(np.frombuffer(pcm, '<f4')) > .05)
        onset = float(hits[0] / 48000) if len(hits) else None
    record('footage: nonzero container origin preserves picture frames and audio time',
           code in (0, 1) and len(frames) == 10 and onset is not None and abs(onset - .25) < .02,
           f'code={code}; frames={len(frames)}; onset={onset}; {output[-300:]}')
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_origin_transcribe', scripts / 'transcribe.py')
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    length = transcribe.duration(source)
    record('footage: nonzero-origin source duration is measured from presentation bounds',
           abs(length - 2.0) < .02, f'duration {length}; expected 2.0')


def check_frame_grid_tiling(tool, record, j):
    """Three 64-frame clips tile exactly on the 24 fps output clock."""
    source = Path(j('24fps-source.mp4'))
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=24:d=3', '-c:v', 'libx264', '-threads', '1', '-bf', '0',
           '-video_track_timescale', '12288', source)
    clip = {'src': 'a', 'in': 0, 'out': 2.666667}
    edit = {'version': 1, 'size': [160, 90], 'fps': 24, 'sources': {'a': {'file': str(source)}},
            'picture': [dict(clip), dict(clip), dict(clip)]}
    code, output, directory = assemble(tool, j, 'grid-edit', edit)
    report_path = directory / 'report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('footage: three adjacent 24 fps segments tile without an extra or missing frame',
           code in (0, 1) and report.get('frames') == 192, f'frames={report.get("frames")}; {output[-300:]}')


def check_frame_grid_arithmetic(tool, record, j):
    """The total and every half-open clip interval use the same rational output grid."""
    import importlib.util
    from fractions import Fraction
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('assemble_grid_case', scripts / 'assemble.py')
    assemble_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble_module)
    examples = [
        ('24 fps', Fraction(24, 1), [2.666667, 5.333334, 8.000001], 192),
        ('30000/1001 fps', Fraction(30000, 1001), [23.790434], 713),
    ]
    for name, rate, ends, expected in examples:
        clips = []
        start = 0.0
        for end in ends:
            clips.append({'at': start, 'duration': end - start, 'speed': 1, 'time_tick': 1e-6})
            start = end
        intervals = assemble_module.clip_frame_intervals(clips, rate)
        count = assemble_module.output_frame_count(ends[-1], rate, clips)
        coverage = [sum(low <= frame < high for _, low, high in intervals) for frame in range(count)]
        record('footage: ' + name + ' rounded edges tile on the output frame grid',
               count == expected and all(value == 1 for value in coverage),
               f'count={count}; intervals={[(a, b) for _, a, b in intervals]}')
    rate = Fraction(30000, 1001)
    boundary = float(Fraction(713, 1) / rate) + .005
    clips = [{'at': 0, 'duration': boundary, 'speed': 1, 'time_tick': 1e-6},
             {'at': boundary, 'duration': 1, 'speed': 1, 'time_tick': 1e-6}]
    intervals = assemble_module.clip_frame_intervals(clips, rate)
    record('footage: a real subframe gap to the next cut retains the outgoing frame',
           intervals[0][1] <= 713 < intervals[0][2] and intervals[1][1] == 714,
           str([(a, b) for _, a, b in intervals]))


def check_reframe_stability(tool, record, j):
    """Small box jitter holds still, while real movement still produces a bounded path."""
    import importlib.util
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('reframe_stability_case', scripts / 'reframe.py')
    reframe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reframe)
    times = [i / 10 for i in range(100)]
    boxes = [[.5 + (.006 if i % 2 else -.006), .4, .7 + (.006 if i % 2 else -.006), .6]
             for i in range(100)]
    path = reframe.propose(times, boxes, .4, .8, .2)
    extent = max(row[1] for row in path) - min(row[1] for row in path)
    record('footage: reframe deadband holds a jittering static subject still', extent < 1e-9, str(extent))
    moving = [[.25 + i * .002, .4, .45 + i * .002, .6] for i in range(100)]
    path = reframe.propose(times, moving, .4, .8, .2)
    record('footage: smoothed reframe follows movement within its speed limit',
           path[-1][1] - path[0][1] > .1 and reframe.max_path_rate(path) <= .2 + 1e-9,
           f'start={path[0][1]}, end={path[-1][1]}, rate={reframe.max_path_rate(path)}')
    source = Path(j('reframe-range.y4m'))
    with source.open('wb') as handle:
        handle.write(b'YUV4MPEG2 W160 H90 F10:1 Ip A1:1 C420jpeg\n')
        for index in range(50):
            handle.write(b'FRAME\n' + bytes([16 + index]) * (160 * 90) + bytes([128]) * (160 * 90 // 2))
    decoded, _, _ = reframe.analyse('ffmpeg', str(source), 160, 90, 1, 2)
    record('footage: reframe range uses source times and excludes the end',
           len(decoded) == 10 and abs(decoded[0] - 1) < .001 and abs(decoded[-1] - 1.9) < .001,
           str((len(decoded), decoded[0], decoded[-1])))


def check_vfr_hold(tool, record, j):
    """A hold begins on the exact output frame shown before it, even on irregular source PTS."""
    images = []
    for number in range(10):
        image = Image.new('RGB', (160, 90), (60, 70, 80))
        draw = ImageDraw.Draw(image)
        for bit in range(6):
            draw.rectangle((10 + bit * 15, 28, 20 + bit * 15, 40),
                           fill='white' if number & (1 << bit) else 'black')
        images.append(np.asarray(image).tobytes())
    source = Path(j('vfr-hold.mkv'))
    timing = r'setpts=if(lt(N\,2)\,N/(10*TB)\,if(lt(N\,4)\,(0.4+(N-2)*0.1)/TB\,(0.9+(N-4)*0.1)/TB))'
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x90', '-r', '10', '-i', '-',
           '-vf', timing, '-fps_mode', 'vfr', '-c:v', 'ffv1', '-threads', '1', source, data=b''.join(images))
    edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': 0, 'out': .9},
                        {'src': 'a', 'in': 0, 'out': .5, 'hold_previous': True}]}
    code, output, directory = assemble(tool, j, 'vfr-hold-edit', edit)
    picture = directory / 'picture.mp4'
    frames = video_frames(picture, 160, 90) if picture.exists() else []
    values = [counter(frame) for frame in frames] if len(frames) else []
    difference = int(np.max(np.abs(frames[8].astype(int) - frames[9].astype(int)))) if len(frames) >= 10 else None
    record('footage: a hold freezes the last frame actually shown from VFR footage',
           code in (0, 1) and len(values) >= 10 and values[8] == values[9] and difference <= 3,
           f'{values}; max pixel delta {difference}; {output[-200:]}')


def check_rounded_showinfo_time(tool, record, j, scripts_dir):
    """A covering frame whose printed time is rounded is still found. In a 90 kHz time base frame 302 of a 30 fps
    source is at 10.0666667 s; FFmpeg 5.1's showinfo prints 10.0667, 33 us late, more than one 11 us tick."""
    images = []
    for number in range(330):
        image = Image.new('RGB', (160, 90), (60, 70, 80))
        draw = ImageDraw.Draw(image)
        for bit in range(6):
            draw.rectangle((10 + bit * 15, 28, 20 + bit * 15, 40),
                           fill='white' if number % 64 & (1 << bit) else 'black')
        images.append(np.asarray(image).tobytes())
    source = Path(j('rounded-time.mp4'))
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x90', '-r', '30', '-i', '-', '-c:v', 'libx264',
           '-qp', '0', '-pix_fmt', 'yuv420p', '-threads', '1', '-video_track_timescale', '90000', source,
           data=b''.join(images))
    spec = importlib.util.spec_from_file_location('rounded_time_frames', Path(scripts_dir) / 'motion_scan.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reader = module.Frames('ffmpeg', str(source), 'trim=start=10.066:end=10.2,format=gray', 160 * 90,
                           ['-copyts', '-ss', '8'])
    count = sum(1 for _ in reader)
    times = reader.times(count)
    record('footage: frame times come from exact PTS, not the rounded printed time',
           abs(times[0] - 906000 / 90000) < 1e-9, repr(times[:2]))
    edit = {'version': 1, 'size': [160, 90], 'fps': 30, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': 10.08, 'out': 10.4}]}
    code, output, directory = assemble(tool, j, 'rounded-time-edit', edit)
    picture = directory / 'picture.mp4'
    values = [counter(frame) for frame in video_frames(picture, 160, 90)] if picture.exists() else []
    record('footage: a later in-point keeps its covering frame when showinfo rounds its time',
           code in (0, 1) and values[:1] == [302 % 64], f'{values[:4]}; {output[-300:]}')


def check_face_aware_crops(record, j, scripts_dir):
    """Use injected rectangles to check automatic framing without needing a face or OpenCV."""
    scripts = Path(scripts_dir)
    spec = importlib.util.spec_from_file_location('face_reframe_case', scripts / 'reframe.py')
    reframe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reframe)
    left = [.08, .12, .16, .22]
    right = [.65, .12, .81, .24]
    data = {'samples': [{'t': 0.0, 'boxes': [left, right]}]}
    targets, methods = reframe.face_targets([0.0], [[.5, .5, .5, .5]], data, .3, .6)
    head_centre = (right[1] + right[3]) / 2
    output_y = (head_centre - (targets[0][1] - .3)) / .6
    record('footage: automatic crop selects the largest detected face without speaker claims',
           methods == ['detected face'] and abs(targets[0][0] - .73) < 1e-9, str((targets, methods)))
    record('footage: automatic face aim leaves headroom for a head-and-shoulders frame',
           abs(output_y - .25) < 1e-9, f'face centre at {output_y:.4f} of crop height')
    findings = reframe.face_review(data['samples'], [[0.0, .73, .33]], .3, .6)
    record('footage: separated detected people are flagged instead of silently framed between',
           [row['kind'] for row in findings] == ['people_do_not_fit'], str(findings))
    close = [[.35, .1, .43, .2], [.54, .1, .60, .2]]
    near = {'samples': [{'t': 0.0, 'boxes': close}]}
    target, _ = reframe.face_targets([0.0], [[.5, .5, .5, .5]], near, .3, .6)
    centre = target[0][:2]
    record('footage: automatic crop retains both detected faces when one window fits',
           not reframe.face_review(near['samples'], [[0.0, *centre]], .3, .6), str(centre))
    huge = {'samples': [{'t': 0.0, 'boxes': [[.1, .1, .5, .3]]}]}
    huge_flags = reframe.face_review(huge['samples'], [[0.0, .3, .5]], .3, 1.0)
    record('footage: a detected face too large for the crop gets a review finding',
           [row['kind'] for row in huge_flags] == ['face_too_large'], str(huge_flags))
    moving = {'samples': [{'t': 1.0, 'boxes': [[.7, .2, .8, .3]]}]}
    clipped = reframe.face_review(moving['samples'], [[0.0, .3, .5], [1.0, .35, .5]], .3, 1.0)
    record('footage: a face clipped by a rate-limited crop is flagged',
           [row['kind'] for row in clipped] == ['face_outside_crop'], str(clipped))

    source = Path(j('face-injection.y4m'))
    with source.open('wb') as handle:
        handle.write(b'YUV4MPEG2 W160 H90 F10:1 Ip A1:1 C420jpeg\n')
        for _ in range(10):
            handle.write(b'FRAME\n' + bytes([80]) * (160 * 90) + bytes([128]) * (160 * 90 // 2))
    existing = sys.modules.get('cv2')
    was_present = 'cv2' in sys.modules
    sys.modules['cv2'] = None
    try:
        missing = {}
        clock, motion, _ = reframe.analyse('ffmpeg', str(source), 160, 90, 0, 1, missing)
    finally:
        if was_present:
            sys.modules['cv2'] = existing
        else:
            del sys.modules['cv2']
    fallback, fallback_methods = reframe.face_targets(clock, motion, missing, .3, 1.0)
    record('footage: missing OpenCV uses the original motion-and-detail targets',
           missing['state'] == 'not_run' and 'OpenCV unavailable' in missing['reason']
           and fallback == motion and set(fallback_methods) == {'motion and detail'}, str(missing))
    calls = []

    def injected(image):
        """Return a face on the first sample, then no face on the second."""
        calls.append(image.shape)
        return [right] if len(calls) == 1 else []

    original = reframe.make_face_detector
    reframe.make_face_detector = lambda: (injected, '')
    try:
        faces = {}
        clock, motion, _ = reframe.analyse('ffmpeg', str(source), 160, 90, 0, 1, faces)
    finally:
        reframe.make_face_detector = original
    _, methods = reframe.face_targets(clock, motion, faces, .3, 1.0)
    record('footage: injected face samples fall back when a later sample finds no face',
           len(calls) == 2 and methods[:5] == ['detected face'] * 5
           and methods[5:] == ['motion and detail'] * 5, str(methods))

    spec = importlib.util.spec_from_file_location('face_assembler_case', scripts / 'assemble.py')
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)
    heights = {0.0: .10, 2.0: .20, 4.0: .10, 6.0: .10}

    def fake_analysis(ffmpeg, source, width, height, start, end, faces):
        """Supply known face heights to the actual multi-clip assembly planner."""
        face_height = heights[start]
        boxes = [[.45, .15, .53, .15 + face_height]]
        samples = [{'index': i, 't': start + i * .2, 'boxes': boxes} for i in range(3)]
        faces.update({'state': 'sampled', 'reason': '', 'samples': samples})
        return [start + i * .2 for i in range(5)], [[.5, .5, .5, .5]] * 5, []

    assembler.analyse = fake_analysis
    items = [{'src': 'm', 'in': start, 'out': start + 1, 'crop': {'path': 'auto'}}
             for start in heights]
    items[2]['crop']['zoom'] = 1.0
    items[3]['crop']['zoom'] = 1.5
    edit = {'size': [90, 160], 'sources': {'m': {'file': str(source)}}, 'picture': items}
    cache = {i: ('unused', 1600, 900, [start, start + .5], start + 1, .001, start + 1)
             for i, start in enumerate(heights)}
    notes = []
    clips, _, _, _, _ = assembler.plan_picture(edit, Path(j('.')), cache, 'ffmpeg', 'ffprobe', j('.'), notes)
    zooms = [clip['zoom'] for clip in clips]
    record('footage: automatic face size matches across lines of the same source',
           abs(zooms[0] * .10 - zooms[1] * .20) < 1e-9 and abs(zooms[0] - 2) < 1e-9, str(zooms))
    sporadic = {'samples': [{'boxes': [right]}, {'boxes': []}, {'boxes': []}, {'boxes': []}]}
    record('footage: sporadic face detections cannot set an automatic matching zoom',
           reframe.face_height(sporadic) is None, str(sporadic))
    record('footage: explicit zoom 1.0 and 1.5 both override automatic size matching',
           zooms[2:] == [1.0, 1.5] and clips[2]['crop_info']['zoom_source'] == 'explicit', str(zooms))
    record('footage: each automatic clip records its framing method in version notes',
           len([note for note in notes if 'detected face' in note]) == 4, str(notes))
    note = assembler.crop_review_notes('m', 30.0, 60.0, 2.0, [{'t': 1.0, 'kind': 'people_do_not_fit'}])[0]
    record('footage: face-fit review note names edit and source times and a remedy',
           '0:31.00' in note and '1:02.00' in note and 'letterbox' in note, note)

    def fake_two_people(ffmpeg, source, width, height, start, end, faces):
        """Inject two face boxes that cannot share a vertical crop."""
        samples = [{'index': i, 't': start + i * .5, 'boxes': [left, right]} for i in range(2)]
        faces.update({'state': 'sampled', 'reason': '', 'samples': samples})
        return [start, start + .5], [[.5, .5, .5, .5]] * 2, []

    assembler.analyse = fake_two_people
    two_edit = {'size': [90, 160], 'sources': {'m': {'file': str(source)}},
                'picture': [{'src': 'm', 'in': 5, 'out': 6, 'crop': {'path': 'auto'}}]}
    two_cache = {0: ('unused', 1600, 900, [5, 5.5], 6, .001, 6)}
    two_notes = []
    assembler.plan_picture(two_edit, Path(j('.')), two_cache, 'ffmpeg', 'ffprobe', j('.'), two_notes)
    record('footage: assembler emits a timecoded two-person crop review note',
           any('edit 0:00.00' in text and 'source 0:05.00' in text and 'do not fit' in text
               and 'letterbox' in text for text in two_notes), str(two_notes))

    spec = importlib.util.spec_from_file_location('face_cut_case', scripts / 'cut.py')
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    settings = {'crop': (.5, .5), 'fit': 'cover', 'background': 'black'}
    built = []
    for mods in ({'crop': 'auto'}, {'crop': 'auto', 'zoom': 1.0}, {'crop': 'auto', 'zoom': 1.5}):
        frame = cutter.framing({'mods': mods}, settings)
        segment = {'t0': 0, 't1': 1, 'key': 'm', 's0': 0, 'speed': 1, 'join': None, 'frame': frame,
                   'grid': (10, 0), 'limit': None, 'line': 1}
        built.append(cutter.picture_items({'segments': [segment], 'assets': {}}, settings,
                                          cutter.Problems())[0][0]['crop'])
    record('footage: paper edit preserves the difference between omitted zoom and explicit zoom 1.0',
           'zoom' not in built[0] and built[1]['zoom'] == 1.0 and built[2]['zoom'] == 1.5, str(built))


def check_transcript_io(tool, record, j):
    """Transcription output is consumable by transcript_cut and inputs are protected from either output."""
    import contextlib
    import hashlib
    import importlib.util
    import io
    import os
    import sys
    import wave
    from unittest.mock import patch

    root = Path(j('identity-transcript-io'))
    root.mkdir(exist_ok=True)
    source = root / 'source.wav'
    with wave.open(str(source), 'wb') as handle:
        handle.setparams((1, 2, 8000, 8000, 'NONE', 'not compressed'))
        handle.writeframes(b'\x01\x00' * 8000)
    srt = root / 'source.srt'
    srt.write_text('1\n00:00:00,100 --> 00:00:00,300\nalpha\n', encoding='utf-8')
    words = root / 'words.json'
    code, output = tool('transcribe.py', source, '--engine', 'import', '--import-file', srt, '--out', words)
    data = json.loads(words.read_text(encoding='utf-8')) if words.exists() else {}
    media = data.get('media') or {}
    record('footage: imported transcription binds the actual media bytes, size and audio stream',
           code == 0 and media.get('sha256') == hashlib.sha256(source.read_bytes()).hexdigest()
           and media.get('bytes') == source.stat().st_size and media.get('audio_stream') == 0,
           str(media) + output)
    selects = root / 'selects.txt'
    selects.write_text('"alpha"\n', encoding='utf-8')
    edit = root / 'edit.json'
    report = root / 'report.json'
    cut_code, cut_out = tool('transcript_cut.py', words, '--selects', selects, '--source', source,
                             '--out', edit, '--json', report)
    selected_edit = json.loads(edit.read_text(encoding='utf-8')) if edit.is_file() else {}
    record('footage: transcript_cut consumes transcribe.py text rows',
           cut_code == 0 and (selected_edit.get('sources', {}).get('a') or {}).get('audio_stream') == 0, cut_out)
    replaced = root / 'replacement.wav'
    with wave.open(str(replaced), 'wb') as handle:
        handle.setparams((1, 2, 8000, 8000, 'NONE', 'not compressed'))
        handle.writeframes(b'\x02\x00' * 8000)
    stale_edit = root / 'stale-edit.json'
    stale_code, stale_out = tool('transcript_cut.py', words, '--selects', selects, '--source', replaced,
                                 '--out', stale_edit)
    record('footage: transcript_cut refuses a transcript bound to different media',
           stale_code == 2 and not stale_edit.exists() and 'stale' in stale_out.lower(), stale_out)
    multistream = root / 'two-streams.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=300:d=1',
                    '-f', 'lavfi', '-i', r'aevalsrc=if(between(t\,0.1\,0.3)\,0.5*sin(2*PI*440*t)\,0):s=8000:d=1',
                    '-map', '0:a', '-map', '1:a', '-c:a', 'pcm_s16le', str(multistream)],
                   check=True, capture_output=True)
    multi_words = root / 'two-streams.json'
    transcribed, transcript_out = tool('transcribe.py', multistream, '--engine', 'import', '--import-file', srt,
                                       '--stream', '1', '--out', multi_words)
    multi_edit = root / 'two-streams-edit.json'
    multi_code, multi_out = tool('transcript_cut.py', multi_words, '--selects', selects, '--source', multistream,
                                 '--audio', multistream, '--handle', '.05', '--out', multi_edit)
    selected = json.loads(multi_edit.read_text(encoding='utf-8')) if multi_edit.exists() else {}
    record('footage: transcript_cut measures and selects the transcript\'s non-default audio stream',
           transcribed == multi_code == 0 and (selected.get('sources', {}).get('a') or {}).get('audio_stream') == 1,
           transcript_out + multi_out)
    spec = importlib.util.spec_from_file_location('identity_transcribe_race', Path(__file__).parent.parent /
                                                  'transcribe.py')
    transcriber = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcriber)
    read_import = transcriber.read_import
    initial_bytes = source.read_bytes()

    def replace_while_reading(path):
        rows = read_import(path)
        source.write_bytes(replaced.read_bytes())
        return rows

    race_output = root / 'changed-during-transcription.json'
    argv = ['transcribe.py', str(source), '--engine', 'import', '--import-file', str(srt), '--out', str(race_output)]
    stderr = io.StringIO()
    try:
        with patch.object(sys, 'argv', argv), \
                patch.object(transcriber, 'read_import', side_effect=replace_while_reading), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(stderr):
            race_code = transcriber.main()
    finally:
        source.write_bytes(initial_bytes)
    record('footage: media changing during transcription cannot produce a bound transcript',
           race_code == 2 and not race_output.exists() and 'changed during transcription' in stderr.getvalue(),
           stderr.getvalue())
    # When both forms are present, text is the authoritative spelling.
    both = root / 'both.json'
    both.write_text(json.dumps({'words': [{'text': 'alpha', 'word': 'other', 'start': .1, 'end': .3}]}),
                    encoding='utf-8')
    both_code, both_out = tool('transcript_cut.py', both, '--selects', selects, '--source', source,
                               '--out', root / 'both-edit.json')
    record('footage: transcript_cut prefers text when a row also has word', both_code == 0, both_out)

    original_audio, original_srt = source.read_bytes(), srt.read_bytes()
    same_code, same_out = tool('transcribe.py', source, '--engine', 'import', '--import-file', srt,
                               '--out', source)
    same = same_code == 2 and source.read_bytes() == original_audio and 'input' in same_out.lower()
    source.write_bytes(original_audio)
    folder = root / 'spelling'
    folder.mkdir(exist_ok=True)
    alt_code, alt_out = tool('transcribe.py', source, '--engine', 'import', '--import-file', srt,
                             '--out', folder / '..' / srt.name)
    alternate = alt_code == 2 and srt.read_bytes() == original_srt and 'input' in alt_out.lower()
    srt.write_bytes(original_srt)
    link = root / 'source-link.wav'
    try:
        os.link(source, link)
    except OSError as error:
        print(f'SKIP  transcribe hard-link protection: {error}')
        linked = True
    else:
        link_code, link_out = tool('transcribe.py', source, '--engine', 'import', '--import-file', srt,
                                   '--out', link)
        linked = link_code == 2 and source.read_bytes() == original_audio and 'input' in link_out.lower()
    record('footage: transcribe protects media and import inputs from path and hard-link outputs',
           same and alternate and linked, same_out + alt_out)

    shots = root / 'shots.json'
    shots.write_text('[]', encoding='utf-8')
    legacy = root / 'legacy.json'
    legacy.write_text(json.dumps({'words': [{'word': 'alpha', 'start': .1, 'end': .3}]}), encoding='utf-8')
    protected = [legacy, selects, source, shots]
    snapshots = {str(path): path.read_bytes() for path in protected}
    outcomes = []
    for number, target in enumerate(protected):
        args = [legacy, '--selects', selects, '--source', source, '--shots', shots,
                '--out', root / f'protected-{number}.json', '--json', target]
        result, detail = tool('transcript_cut.py', *args)
        outcomes.append((target.name, result, target.read_bytes() == snapshots[str(target)], detail))
        target.write_bytes(snapshots[str(target)])
    # The optional audio input may be a different path to the same source bytes.
    audio = root / 'audio.wav'
    audio.write_bytes(original_audio)
    audio_code, audio_out = tool('transcript_cut.py', legacy, '--selects', selects, '--source', source,
                                 '--audio', audio, '--out', root / 'audio-edit.json', '--json', audio)
    record('footage: transcript_cut report refuses all five input paths before writing',
           all(code == 2 and intact and 'input' in detail.lower() for _, code, intact, detail in outcomes)
           and audio_code == 2 and audio.read_bytes() == original_audio and 'input' in audio_out.lower(),
           str(outcomes) + audio_out)
    legacy_copy = legacy.read_bytes()
    cut_link = root / 'legacy-link.json'
    try:
        os.link(legacy, cut_link)
    except OSError as error:
        print(f'SKIP  transcript_cut hard-link protection: {error}')
        protected_link = True
    else:
        link_code, link_out = tool('transcript_cut.py', legacy, '--selects', selects, '--source', source,
                                   '--out', cut_link)
        protected_link = link_code == 2 and legacy.read_bytes() == legacy_copy and 'input' in link_out.lower()
    both_code, both_out = tool('transcript_cut.py', legacy, '--selects', selects, '--source', source,
                               '--out', legacy)
    record('footage: transcript_cut output refuses its transcript by path and hard link',
           protected_link and both_code == 2 and legacy.read_bytes() == legacy_copy, both_out)


def check_srgb_graphics(record, j, scripts_dir):
    """A graphics render tagged sRGB (as Cavalry's and other PNG pipelines are) keeps its values: converting the
    curve through linear light had turned a title's RGB 16 background into 6 and mid grey 128 into about 113."""
    spec = importlib.util.spec_from_file_location('footage_srgb_assembler', Path(scripts_dir) / 'assemble.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = Path(j('srgb-graphics.mp4'))
    graph = 'color=c=0x101014:s=320x180:r=25:d=1,drawbox=x=160:y=0:w=160:h=180:color=0x808080:t=fill'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', graph, '-vf',
                    'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,'
                    'setparams=color_trc=iec61966-2-1:color_primaries=bt709:colorspace=bt709:range=tv',
                    '-c:v', 'libx264', '-crf', '8', str(source)], check=True, capture_output=True)
    stream, _, width, height = module.probe_source('ffprobe', str(source))
    vf, _, conversion = module.colour_filter(stream, int(stream['width']), int(stream['height']))
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-vf', vf, '-frames:v', '1', '-f', 'rawvideo',
                             '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True)
    frame = np.frombuffer(result.stdout, np.uint8).reshape(height, width, 3).astype(int)
    dark, grey = frame[90, 40], frame[90, 240]
    record('footage: an sRGB-tagged graphics render keeps its values (dark and mid grey within 4 levels)',
           stream.get('color_transfer') == 'iec61966-2-1' and abs(dark - [16, 16, 20]).max() <= 4
           and abs(grey - [128, 128, 128]).max() <= 4 and 'sRGB values kept' in conversion,
           f'{conversion}; dark {dark.tolist()}, grey {grey.tolist()}')


def run_footage_cases(tool, record, j, scripts_dir):
    """Exercise exact picture and sound answers on small synthetic sources."""
    check_srgb_graphics(record, j, scripts_dir)
    check_transcript_io(tool, record, j)
    check_rounded_showinfo_time(tool, record, j, scripts_dir)
    check_frame_scan_errors(record, scripts_dir)
    check_seek_policy_atoms(record, j, scripts_dir)
    check_audio_fidelity(tool, record, j)
    check_audio_retimes(tool, record, j)
    check_nonzero_origin(tool, record, j)
    check_frame_grid_tiling(tool, record, j)
    check_frame_grid_arithmetic(tool, record, j)
    check_reframe_stability(tool, record, j)
    check_face_aware_crops(record, j, scripts_dir)
    check_vfr_hold(tool, record, j)
    check_world_geometry(tool, record, j, scripts_dir)
    check_world_vfr(tool, record, j, scripts_dir)
    check_edit_list_matrix(tool, record, j, scripts_dir)
    check_ordinary_starts(tool, record, j, scripts_dir)
    check_seeked_audio_window(record, j, scripts_dir)
    check_world_retimes(tool, record, j, scripts_dir)
    width, height, fps = fixture(j)
    source = j('footage-source.mkv')
    check_picture_out_clamp(tool, record, j, source)
    check_decoded_end_clamp(tool, record, j)
    base = {'version': 1, 'size': [width, height], 'fps': fps, 'sources': {'a': {'file': source}}}
    edit = dict(base, picture=[{'src': 'a', 'in': .5, 'out': 1.5},
                               {'src': 'a', 'in': 2, 'out': 3}],
                audio=[{'track': 'jcut', 'src': 'a', 'in': 1.8, 'out': 2.2, 'at': .8},
                       {'track': 'lcut', 'src': 'a', 'in': .50001, 'out': 1.8, 'at': 0}])
    code, output, directory = assemble(tool, j, 'footage-cut', edit)
    picture = directory / 'picture.mp4'
    record('footage: cut edit renders', code in (0, 1) and picture.exists(), output[-200:])
    if not picture.exists():
        record('footage: required cases completed', False, 'cut fixture did not render')
        return
    frames = video_frames(picture, width, height)
    counters = [counter(frame) for frame in frames]
    expected = list(range(5, 15)) + list(range(20, 30))
    record('footage: burned counters prove every frame across both cuts', counters == expected,
           f'actual {counters}; expected {expected}')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=color_space,color_transfer,color_primaries', '-of', 'json', str(picture)],
                           capture_output=True, text=True)
    tags = json.loads(probe.stdout)['streams'][0]
    patch = frames[0, 65:75, 120:140].mean(axis=(0, 1))
    record('footage: BT.709 tags and brand patch survive',
           all(tags.get(key) == 'bt709' for key in ('color_space', 'color_transfer', 'color_primaries'))
           and np.max(np.abs(patch - [48, 128, 192])) <= 12, f'tags {tags}; RGB {patch.round(1).tolist()}')
    snap_report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    audio_snaps = [row for row in snap_report['snaps'] if row.get('clock') == 'audio sample']
    record('footage: audio boundaries snap to the sample clock',
           len(audio_snaps) == 4 and any(abs(row['requested'] - .50001) < 1e-9
           and abs(row['snapped'] - .5) < 1e-9 for row in audio_snaps), str(audio_snaps))
    for track, time in (('jcut', .9), ('lcut', 1.2)):
        cue = directory / (track + '-cue.json')
        cue.write_text(json.dumps({'events': [{'id': track, 't': time, 'sound': 'required',
                                               'tolerance_ms': 20, 'window_ms': 80}]}), encoding='utf-8')
        report = directory / (track + '-cue-report.json')
        status, details = tool('cue_onsets.py', directory / (track + '.wav'), cue, '--json', report)
        record(f'footage: {track} onset lands at {time}s', status == 0, details[-180:])
    # Clip starts are sums of floating-point durations: 1.6 - 0.2 is 1.4000000000000001, so without a tolerance the
    # frame at 1.4 s would still show the outgoing clip's out frame (16) instead of the incoming clip's first (20).
    edge = dict(base, picture=[{'src': 'a', 'in': .2, 'out': 1.6}, {'src': 'a', 'in': 2, 'out': 3}])
    code, output, edge_dir = assemble(tool, j, 'footage-edge', edge)
    edge_counters = ([counter(frame) for frame in video_frames(edge_dir / 'picture.mp4', width, height)]
                     if code in (0, 1) else [])
    record('footage: the frame on a cut shows the incoming shot despite floating-point clip starts',
           edge_counters == list(range(2, 16)) + list(range(20, 30)), f'{edge_counters}; {output[-200:]}')
    check_track_mix(record, j, scripts_dir)
    # Half-speed audio must retain its tone frequency and picture duration.
    slow = dict(base, picture=[{'src': 'a', 'in': .2, 'out': 1.2, 'speed': .5}],
                audio=[{'track': 'tone', 'src': 'a', 'in': .2, 'out': 1.2, 'at': 0}])
    code, output, slow_dir = assemble(tool, j, 'footage-slow', slow)
    if code in (0, 1) and (slow_dir / 'tone.wav').exists():
        rate = 48000
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(slow_dir / 'tone.wav'),
                                  '-f', 'f32le', '-'], capture_output=True, check=True)
        signal = np.frombuffer(decoded.stdout, '<f4').reshape(-1, 2)[:, 0]
        window = signal[round(.2 * rate):round(1.7 * rate)].astype(float)
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
        frequency = np.fft.rfftfreq(len(window), 1 / rate)[int(np.argmax(spectrum))]
        slow_frames = video_frames(slow_dir / 'picture.mp4', width, height)
        record('footage: half-speed duration and pitch', len(slow_frames) == 20 and abs(frequency - 440) < 3,
               f'{len(slow_frames)} frames; {frequency:.2f} Hz')
    else:
        record('footage: half-speed duration and pitch', False, output[-200:])
    # A decimal NTSC rate means the exact one: an editing application reads 2997/100 as a non-standard rate.
    rates = []
    for name, value in (('footage-ntsc-decimal', 29.97), ('footage-ntsc-fraction', '30000/1001')):
        code, output, ntsc_dir = assemble(tool, j, name, dict(base, fps=value,
                                                               picture=[{'src': 'a', 'in': .5, 'out': 1.5}]))
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=r_frame_rate', '-of', 'json', str(ntsc_dir / 'picture.mp4')],
                               capture_output=True, text=True)
        stream = (json.loads(probe.stdout or '{}').get('streams') or [{}])[0]
        cues = ntsc_dir / 'edit-cues.json'
        cue_fps = json.loads(cues.read_text(encoding='utf-8')).get('fps') if cues.exists() else None
        rates.append((code, stream.get('r_frame_rate'), cue_fps))
    record('footage: 29.97 and 30000/1001 both render at exactly 30000/1001, with a numeric cue-list rate',
           all(code in (0, 1) and rate == '30000/1001' and isinstance(cue, float)
               and abs(cue - 30000 / 1001) < 1e-9 for code, rate, cue in rates), str(rates))
    motion = dict(base, picture=[{'src': 'a', 'in': .2, 'out': 1.2, 'speed': .5, 'retime': 'motion'}])
    code, output, motion_dir = assemble(tool, j, 'footage-motion', motion)
    if code in (0, 1):
        motion_frames = video_frames(motion_dir / 'picture.mp4', width, height)
        tail_step = float(np.abs(motion_frames[-3].astype(int) - motion_frames[-4].astype(int)).mean())
        record('footage: motion retime preserves duration and motion through the tail',
               len(motion_frames) == 20 and tail_step > .2,
               f'{len(motion_frames)} frames; penultimate motion {tail_step:.3f}')
    else:
        record('footage: motion retime renders the requested duration', False, output[-200:])
    # Both sources have the same constant background; a double fade would dim it.
    dissolve = dict(base, picture=[{'src': 'a', 'in': .2, 'out': 1.2},
                                    {'src': 'a', 'in': 2, 'out': 3,
                                     'join': {'kind': 'dissolve', 'dur': .5}}])
    code, output, dissolve_dir = assemble(tool, j, 'footage-dissolve', dissolve)
    if code in (0, 1):
        dissolved = video_frames(dissolve_dir / 'picture.mp4', width, height)
        levels = dissolved[5:10, 70, 20].astype(int)
        outgoing = dissolved[4, 70, 20].astype(int)
        incoming = dissolved[10, 70, 20].astype(int)
        floor = np.minimum(outgoing, incoming)
        record('footage: dissolve does not darken below both sources',
               bool(np.all(levels >= floor - 2)), f'floor {floor.tolist()}; overlap {levels.tolist()}')
    else:
        record('footage: dissolve does not darken below both sources', False, output[-200:])
    # A deliberately uneven source keeps the frame that is showing at .69 s.
    vfr = j('footage-vfr.mkv')
    ffmpeg('-i', source, '-an', '-vf', "setpts='if(lt(N,5),N/(10*TB),(.5+(N-5)/5)/TB)'",
           '-fps_mode', 'vfr', '-c:v', 'ffv1', vfr)
    vfr_edit = dict(base, sources={'a': {'file': vfr}}, picture=[{'src': 'a', 'in': .69, 'out': 1.29}])
    code, output, vfr_dir = assemble(tool, j, 'footage-vfr-cut', vfr_edit)
    if code in (0, 1):
        report = json.loads((vfr_dir / 'report.json').read_text(encoding='utf-8'))
        values = [snap['snapped'] for snap in report['snaps']]
        covering = [snap.get('covering_frame_pts') for snap in report['snaps']]
        found = counter(video_frames(vfr_dir / 'picture.mp4', width, height)[0])
        record('footage: VFR cut retains the source frame showing at the requested time',
               len(values) == 2 and abs(values[0] - .69) < .001 and abs(values[1] - 1.29) < .001
               and abs(covering[0] - .5) < .001 and found == 5,
               f'boundaries {values}; covering frames {covering}; first counter {found}')
    else:
        record('footage: VFR cut uses decoded frame timestamps', False, output[-200:])
    # A small white subject moves across a wide frame; its centre is known at every source time.
    moving = []
    path = []
    for index in range(20):
        image = Image.new('RGB', (320, 180), 'black')
        x = 70 + index * 4
        ImageDraw.Draw(image).rectangle((x, 70, x + 20, 110), fill='white')
        moving.append(np.asarray(image).tobytes())
        path.append([index / 10, (x + 10) / 320, .5])
    moving_source = j('footage-moving.mkv')
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '320x180', '-r', 10, '-i', 'pipe:0',
           '-c:v', 'ffv1', moving_source, data=b''.join(moving))
    moving_edit = {'version': 1, 'size': [90, 160], 'fps': 10, 'sources': {'m': {'file': moving_source}},
                   'picture': [{'src': 'm', 'in': 0, 'out': 2, 'crop': {'path': path}}]}
    code, output, moving_dir = assemble(tool, j, 'footage-moving-edit', moving_edit)
    if code in (0, 1):
        views = video_frames(moving_dir / 'picture.mp4', 90, 160)
        bright = [(frame.mean(axis=2) > 150).sum() for frame in views]
        record('footage: crop path keeps the moving subject in 9:16',
               len(bright) == 20 and min(bright) > 400, f'min subject area {min(bright)} pixels')
    else:
        record('footage: crop path keeps the moving subject in 9:16', False, output[-200:])
    fixed = Path(j('footage-fixed-path.json'))
    fixed.write_text(json.dumps({'path': [[0, .25, .5], [2, .25, .5]]}), encoding='utf-8')
    flag_report = j('footage-flags.json')
    code, output = tool('reframe.py', moving_source, '--aspect', '9:16', '--path', fixed,
                        '--sheet', j('footage-flags.png'), '--json', flag_report)
    flags = json.loads(Path(flag_report).read_text(encoding='utf-8'))['flags'] if Path(flag_report).exists() else []
    record('footage: reframe flags subject bounds leaving the crop',
           code == 1 and any(row['subject_out'] for row in flags), f'{len(flags)} flags; {output[-100:]}')
    auto_report = j('footage-auto-report.json')
    code, output = tool('reframe.py', moving_source, '--aspect', '9:16', '--auto', '--max-rate', '.2',
                        '--out', j('footage-auto-path.json'), '--sheet', j('footage-auto.png'),
                        '--json', auto_report)
    result = json.loads(Path(auto_report).read_text(encoding='utf-8')) if Path(auto_report).exists() else {}
    record('footage: automatic crop path respects maximum rate',
           code in (0, 1) and result.get('measured_max_rate', 1) <= .20000001,
           f"peak rate {result.get('measured_max_rate')}")
    # reframe.py writes source-clock times; an edit that loads its file counts from the clip's in-point.
    late_path = Path(j('footage-late-path.json'))
    code, output = tool('reframe.py', moving_source, '--aspect', '9:16', '--auto', '--start', 1, '--end', 2,
                        '--out', late_path, '--sheet', j('footage-late.png'))
    late_edit = {'version': 1, 'size': [90, 160], 'fps': 10, 'sources': {'m': {'file': moving_source}},
                 'picture': [{'src': 'm', 'in': 1, 'out': 2, 'crop': {'path': str(late_path)}}]}
    code, output, late_dir = assemble(tool, j, 'footage-late-edit', late_edit)
    late_report = late_dir / 'report.json'
    keys = (json.loads(late_report.read_text(encoding='utf-8'))['crops'][0]['path']
            if code in (0, 1) and late_report.exists() else [[None]])
    written = json.loads(late_path.read_text(encoding='utf-8'))['path'] if late_path.exists() else [[None]]
    views = video_frames(late_dir / 'picture.mp4', 90, 160) if code in (0, 1) else []
    bright = [(frame.mean(axis=2) > 150).sum() for frame in views]
    record('footage: a crop path reframe.py wrote from --start plays from the clip in-point',
           None not in (keys[0][0], written[0][0]) and abs(written[0][0] - 1) < .001 and abs(keys[0][0]) < .001
           and len(bright) == 10 and min(bright) > 400,
           f'written {written[0]}; used {keys[0]}; subject areas {bright}; {output[-200:]}')
    # Synthetic HLG-coded levels exercise the actual HDR conversion chain and tags.
    filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace')
    import re
    available = set(re.findall(r'^\s*[TSC.]{2,3}\s+(\S+)', filters.stdout, re.MULTILINE))
    if filters.returncode:
        raise RuntimeError('cannot inspect FFmpeg filters')
    if 'zscale' not in available:
        print('SKIP  footage: HLG this FFmpeg build lacks zscale; HDR conversion needs a build with libzimg')
        return
    hlg = j('footage-hlg.mp4')
    ffmpeg('-f', 'lavfi', '-i', 'color=c=gray:s=160x90:r=10:d=1', '-vf',
           'setparams=colorspace=bt2020nc:color_trc=arib-std-b67:color_primaries=bt2020',
           '-c:v', 'libx264', '-threads', 1, hlg)
    hlg_edit = dict(base, sources={'a': {'file': hlg}}, picture=[{'src': 'a', 'in': 0, 'out': 1}])
    code, output, hlg_dir = assemble(tool, j, 'footage-hlg-edit', hlg_edit)
    if code in (0, 1):
        report = json.loads((hlg_dir / 'report.json').read_text(encoding='utf-8'))
        converted = next(iter(report['sources'].values()))
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=color_space,color_transfer,color_primaries', '-of', 'json',
                                str(hlg_dir / 'picture.mp4')], capture_output=True, text=True)
        tags = json.loads(probe.stdout)['streams'][0]
        reference_filter = ('zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,'
                            'tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,'
                            'format=yuv420p,format=rgb24')
        command = ['ffmpeg', '-v', 'error', '-i', hlg, '-vf', reference_filter,
                   '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
        reference = subprocess.run(command, capture_output=True)
        reference_rgb = np.frombuffer(reference.stdout, np.uint8).reshape(height, width, 3)[45, 80]
        actual_rgb = video_frames(hlg_dir / 'picture.mp4', width, height)[0, 45, 80]
        delta = np.max(np.abs(actual_rgb.astype(int) - reference_rgb.astype(int)))
        record('footage: HLG is tone-mapped and tagged BT.709',
               reference.returncode == 0 and delta <= 6 and 'Hable' in converted['conversion']
               and all(tags.get(k) == 'bt709' for k in ('color_space', 'color_transfer', 'color_primaries')),
               f'tags {tags}; output {actual_rgb.tolist()}; reference {reference_rgb.tolist()}')
    else:
        record('footage: HLG is tone-mapped and tagged BT.709', False, output[-200:])


def picture_facts(path):
    """Probe the video stream of one synthetic output."""
    result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_streams',
                             '-of', 'json', str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)['streams'][0]


def rotated_fixture(source, destination, rotation):
    """Set the sole video track's MP4 display matrix without version-specific FFmpeg options."""
    data = bytearray(source.read_bytes())

    def box(parent, kind):
        start, end = parent
        while start + 8 <= end:
            size, name = struct.unpack_from('>I4s', data, start)
            if size < 8 or start + size > end:
                raise ValueError('invalid synthetic MP4 box')
            if name == kind:
                return start + 8, start + size
            start += size
        raise ValueError('synthetic MP4 lacks ' + kind.decode('ascii'))

    track = box(box((0, len(data)), b'moov'), b'trak')
    start, _ = box(track, b'tkhd')
    offset = start + (52 if data[start] == 1 else 40)
    one, fixed = 65536, 1 << 30
    a, b, c, d = {90: (0, -one, one, 0), 180: (-one, 0, 0, -one),
                  270: (0, one, -one, 0)}[rotation]
    struct.pack_into('>9i', data, offset, a, b, 0, c, d, 0, 0, 0, fixed)
    destination.write_bytes(data)


def check_world_geometry(tool, record, j, scripts_dir):
    """Rotation, square-pixel proxy and anamorphic contain/cover have known display shapes."""
    root = Path(j('world-geometry')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    base = root / 'phone.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=1', '-c:v', 'libx264', '-threads', '1', base)
    caption = root / 'caption.srt'
    caption.write_text('1\n00:00:00,000 --> 00:00:00,800\nTest\n', encoding='utf-8')
    sources = {}
    for rotation in (0, 90, 180, 270):
        source = base if not rotation else root / f'phone-{rotation}.mp4'
        if rotation:
            rotated_fixture(base, source, rotation)
        sources[rotation] = source
        expected = (180, 320) if rotation in (90, 270) else (320, 180)
        project = root / f'project-{rotation}'
        code, output = tool('map.py', 'add', project, source, '--role', 'broll')
        index = project / 'map' / 'sources.json'
        video = json.loads(index.read_text(encoding='utf-8'))['sources'][0]['video'] if index.exists() else {}
        burned = root / f'burn-{rotation}.mp4'
        report = root / f'burn-{rotation}.json'
        burn_code, burn_output = tool('captions.py', 'burn', source, caption, '--out', burned, '--json', report)
        result = picture_facts(burned) if burned.is_file() else {}
        data = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
        side = result.get('side_data_list') or []
        ok = (code == 0 and burn_code in (0, 1) and (video.get('width'), video.get('height')) == expected
              and video.get('rotation_degrees') == rotation and video.get('coded_width') == 320
              and (result.get('width'), result.get('height')) == expected
              and result.get('sample_aspect_ratio') in ('1:1', '1/1')
              and not any('rotation' in item for item in side)
              and data.get('source_geometry', {}).get('coordinate_space') == 'autorotated square pixels')
        record(f'footage: {rotation}-degree phone map and caption burn use display geometry', ok,
               f'map={video}; output={result}; {output[-100:]} {burn_output[-100:]}')
    spec = importlib.util.spec_from_file_location('wave2_cut', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)

    class FakeMap:
        """A source map whose old dimensions must not override the real display matrix."""
        sources = {'v': {'sha256': 'a' * 64}}

        def size(self, _):
            return 320, 180

        def path(self, _):
            return sources[90]

        def duration(self, _):
            return 1.0

        def fps(self, _):
            return 10

    proxies = cut.plan_proxies({'picture': [{'src': 'v'}]}, {'fps': 10}, FakeMap(), (40, 70), root,
                               'ffmpeg', lambda _: None)
    proxy = picture_facts(proxies['v']['file']) if 'v' in proxies else {}
    record('footage: portrait proxy bakes rotation and square pixels once',
           proxy.get('height', 0) > proxy.get('width', 0)
           and proxy.get('sample_aspect_ratio') in ('1:1', '1/1')
           and not any('rotation' in item for item in proxy.get('side_data_list', [])), str(proxy))
    anamorphic = root / 'anamorphic.mkv'
    square = root / 'square.mkv'
    for path, sar in ((anamorphic, 2), (square, 1)):
        ffmpeg('-f', 'lavfi', '-i',
               f'color=black:s=160x120:r=10:d=1,drawbox=x=40:y=30:w=80:h=60:color=white:t=fill,setsar={sar}',
               '-c:v', 'ffv1', '-threads', '1', path)
    for name, source, size, fit, expected in (
            ('world-contain', anamorphic, [160, 120], 'contain', [40, 45, 119, 74]),
            ('world-cover', anamorphic, [160, 120], 'cover', [0, 30, 159, 89]),
            ('world-upscale', square, [320, 240], 'contain', [80, 60, 239, 179])):
        edit = {'version': 1, 'fps': 10, 'size': size, 'sources': {'v': str(source)},
                'picture': [{'src': 'v', 'in': 0, 'out': .8, 'fit': fit}]}
        code, output, directory = assemble(tool, j, name, edit)
        image = video_frames(directory / 'picture.mp4', *size)[0] if code in (0, 1) else None
        bbox = None
        if image is not None:
            y, x = np.where(image.min(axis=2) > 180)
            if len(x):
                bbox = [int(x.min()), int(y.min()), int(x.max()), int(y.max())]
        record(f'footage: {name} fits in square-pixel display space', bbox == expected,
               f'actual={bbox}, expected={expected}; {output[-200:]}')


def check_world_vfr(tool, record, j, scripts_dir):
    """Compare every VFR cut and four audio markers, including the late marker, with decoded output."""
    root = Path(j('world-vfr')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    rate = 48000
    samples = np.zeros(rate * 2, dtype=np.float32)
    for moment in (.1, .5, 1.0, 1.5):
        samples[round(moment * rate):round((moment + .02) * rate)] = .7
    wav = root / 'source.wav'
    with wave.open(str(wav), 'wb') as handle:
        handle.setparams((1, 2, rate, len(samples), 'NONE', 'not compressed'))
        handle.writeframes(np.int16(samples * 32767).tobytes())
    source = root / 'vfr.mkv'
    select = r'select=eq(n\,0)+eq(n\,1)+eq(n\,4)+eq(n\,5)+eq(n\,6)+eq(n\,9)+eq(n\,10)'
    select += r'+eq(n\,11)+eq(n\,14)+eq(n\,15)+eq(n\,16)+eq(n\,19)'
    frames = []
    for number in range(20):
        image = Image.new('RGB', (160, 120), (60, 70, 80))
        draw = ImageDraw.Draw(image)
        for bit in range(6):
            colour = 'white' if number & (1 << bit) else 'black'
            draw.rectangle((10 + bit * 15, 28, 20 + bit * 15, 40), fill=colour)
        frames.append(np.asarray(image).tobytes())
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x120', '-r', '10', '-i', 'pipe:0',
           '-i', wav, '-map', '0:v', '-map', '1:a', '-vf', select, '-fps_mode', 'passthrough',
           '-c:v', 'ffv1', '-threads', '1', '-c:a', 'pcm_s16le', source, data=b''.join(frames))
    spans = [(0, .3), (.4, .7), (.9, 1.2), (1.4, 1.7)]
    picture = [{'src': 'v', 'in': start, 'out': end} for start, end in spans]
    audio = [{'track': 'speech', 'src': 'v', 'in': start, 'out': end, 'at': index * .3, 'fade_ms': 0}
             for index, (start, end) in enumerate(spans)]
    edit = {'version': 1, 'fps': 10, 'size': [160, 120], 'sources': {'v': str(source)},
            'picture': picture, 'audio': audio}
    code, output, directory = assemble(tool, j, 'world-vfr-edit', edit)
    if code not in (0, 1):
        record('footage: all VFR cuts and audio markers follow one edit clock', False, output[-400:])
        return
    source_frames = video_frames(source, 160, 120)
    rendered = video_frames(directory / 'picture.mp4', 160, 120)
    indices = [0, 1, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    expected_frames = [counter(source_frames[index]) for index in indices]
    actual_frames = [counter(frame) for frame in rendered]
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(directory / 'speech.wav'), '-ac', '1',
                             '-ar', str(rate), '-f', 'f32le', '-'], capture_output=True, check=True)
    audio_data = np.frombuffer(result.stdout, '<f4')
    hits = np.flatnonzero(np.abs(audio_data) > .3)
    starts = hits[np.r_[True, np.diff(hits) > rate * .08]] / rate if len(hits) else np.array([])
    expected = np.array([.1, .4, .7, 1.0])
    sync = float(np.max(np.abs(starts - expected))) if len(starts) == len(expected) else float('inf')
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    boundaries = [row['snapped'] for row in report['snaps'] if row['clock'] == 'source edit time']
    record('footage: all VFR cuts and audio markers follow one edit clock',
           actual_frames == expected_frames and sync < .005
           and np.allclose(boundaries, [value for pair in spans for value in pair]),
           f'frames={actual_frames}, expected={expected_frames}; marker starts={starts.tolist()}; '
           f'boundaries={boundaries}')
    sparse = root / 'sparse.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=1:d=5', '-vf',
           r'select=eq(n\,0)+eq(n\,3)+eq(n\,4)', '-fps_mode', 'passthrough', '-c:v', 'ffv1', '-threads', '1', sparse)
    edit = {'version': 1, 'fps': 10, 'size': [160, 120], 'sources': {'v': str(sparse)},
            'picture': [{'src': 'v', 'in': 2, 'out': 2.5}]}
    code, output, directory = assemble(tool, j, 'world-sparse-edit', edit)
    if code in (0, 1):
        actual = video_frames(directory / 'picture.mp4', 160, 120)
        first = linear_assembly_frames(sparse, 160, 120, scripts_dir)[0]
        error = float(np.max(np.mean(np.abs(actual.astype(int) - first.astype(int)), axis=(1, 2, 3))))
        report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
        covering = report['snaps'][0].get('covering_frame_pts')
        record('footage: sparse seek retains the frame already showing',
               len(actual) == 5 and error < 12 and abs(covering) < .001,
               f'frames={len(actual)}; error={error}; covering PTS={covering}')
    else:
        record('footage: sparse seek retains the frame already showing', False, output[-300:])
    path, sheet, report_path = root / 'sparse-path.json', root / 'sparse-sheet.png', root / 'sparse-report.json'
    code, output = tool('reframe.py', sparse, '--aspect', '9:16', '--auto', '--start', '2', '--end', '2.5',
                        '--out', path, '--sheet', sheet, '--json', report_path)
    data = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('footage: sparse reframe analysis retains the frame already showing at the in-point',
           code in (0, 1) and data.get('frames') == 1 and abs(data['path'][0][0] - 2) < .001,
           output[-300:] + str(data))


def movie_boxes(data):
    """Read the simple 32-bit MP4 boxes generated by this synthetic fixture."""
    offset = 0
    while offset < len(data):
        size, kind = struct.unpack_from('>I4s', data, offset)
        if size < 8 or offset + size > len(data):
            raise ValueError('invalid fixture box')
        yield kind, data[offset + 8:offset + size]
        offset += size


def movie_box(kind, payload):
    """Rebuild one fixture box with its adjusted size."""
    return struct.pack('>I4s', len(payload) + 8, kind) + payload


def movie_timescale(payload):
    """The timescale in a version-zero or version-one movie/media header."""
    return struct.unpack_from('>I', payload, 20 if payload[0] else 12)[0]


def two_entry_track(track, movie_rate):
    """Give one fixture track two presentation edits without changing its media data."""
    media = next(payload for kind, payload in movie_boxes(track) if kind == b'mdia')
    media_rate = movie_timescale(next(payload for kind, payload in movie_boxes(media) if kind == b'mdhd'))
    result = []
    for kind, payload in movie_boxes(track):
        if kind == b'edts':
            edits = []
            for edit_kind, data in movie_boxes(payload):
                if edit_kind == b'elst':
                    if data[0] != 0:
                        raise ValueError('fixture needs version-zero edit lists')
                    count = struct.unpack_from('>I', data, 4)[0]
                    entries = [struct.unpack_from('>Iihh', data, 8 + 12 * index) for index in range(count)]
                    original = next(entry for entry in entries if entry[1] >= 0)
                    data = data[:4] + struct.pack('>I', 2)
                    data += struct.pack('>Iihh', 2 * movie_rate, original[1], 1, 0)
                    data += struct.pack('>Iihh', 3 * movie_rate, original[1] + media_rate, 1, 0)
                edits.append(movie_box(edit_kind, data))
            payload = b''.join(edits)
        result.append(movie_box(kind, payload))
    return b''.join(result)


def make_two_entry_movie(source, destination):
    """Build a two-entry edit list after mdat, so original media offsets stay valid."""
    top = list(movie_boxes(Path(source).read_bytes()))
    kinds = [kind for kind, _ in top]
    if kinds.index(b'moov') < kinds.index(b'mdat'):
        raise ValueError('fixture moov must follow mdat')
    moov = next(payload for kind, payload in top if kind == b'moov')
    rate = movie_timescale(next(payload for kind, payload in movie_boxes(moov) if kind == b'mvhd'))
    changed = b''.join(movie_box(kind, two_entry_track(payload, rate) if kind == b'trak' else payload)
                       for kind, payload in movie_boxes(moov))
    Path(destination).write_bytes(b''.join(movie_box(kind, changed if kind == b'moov' else payload)
                                          for kind, payload in top))


def movie_edit_counts(path):
    """Return each synthetic track's declared edit-entry count."""
    moov = next(payload for kind, payload in movie_boxes(Path(path).read_bytes()) if kind == b'moov')
    counts = []
    for kind, track in movie_boxes(moov):
        if kind != b'trak':
            continue
        for child_kind, child in movie_boxes(track):
            if child_kind == b'edts':
                for edit_kind, edit in movie_boxes(child):
                    if edit_kind == b'elst':
                        counts.append(struct.unpack_from('>I', edit, 4)[0])
    return counts


def check_edit_list_matrix(tool, record, j, scripts_dir):
    """Compare the scripts' video and AAC selections against linear presentation decodes."""
    root = Path(j('edit-list-matrix')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    for mode in ('closed', 'open'):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=10:d=5', '-f', 'lavfi', '-i',
               'aevalsrc=0.25*sin(2*PI*(330+70*floor(t))*t):s=48000:d=5', '-map', '0:v', '-map', '1:a',
               '-c:v', 'libx264', '-threads', '1', '-g', '10', '-bf', '2', '-x264-params',
               f'open-gop={1 if mode == "open" else 0}:scenecut=0', '-c:a', 'aac', '-b:a', '128k',
               root / f'{mode}.mp4')
    make_two_entry_movie(root / 'closed.mp4', root / 'multiple.mp4')
    make_two_entry_movie(root / 'open.mp4', root / 'open-multiple.mp4')
    counts = {name: movie_edit_counts(root / (name + '.mp4')) for name in ('closed', 'multiple')}
    stream = picture_facts(root / 'open.mp4')
    packet = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_packets',
                             '-show_entries', 'packet=pts_time,side_data_list', '-of', 'json',
                             str(root / 'closed.mp4')], capture_output=True, text=True, check=True)
    packets = json.loads(packet.stdout).get('packets', [])
    priming = bool(packets and float(packets[0].get('pts_time', 0)) < 0)
    record('footage: edit-list matrix contains single and multiple edits, AAC priming and B-frames',
           counts['closed'] == [1, 1] and counts['multiple'] == [2, 2]
           and priming and stream.get('has_b_frames', 0) > 0,
           f'entry counts={counts}; priming={priming}; B-frames={stream.get("has_b_frames")}')
    common_spec = importlib.util.spec_from_file_location('round2_seek_policy', Path(scripts_dir) / 'render_common.py')
    common = importlib.util.module_from_spec(common_spec)
    common_spec.loader.exec_module(common)
    seek_policy = [common.source_seek_safe(root / (name + '.mp4'))
                   for name in ('closed', 'multiple', 'open-multiple')]
    record('footage: multiple MP4 edits use linear decode; a single edit may seek',
           seek_policy == [True, False, False], str(seek_policy))
    spec = importlib.util.spec_from_file_location('wave2_transcribe', Path(scripts_dir) / 'transcribe.py')
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    for name in ('closed', 'multiple', 'open'):
        source = root / (name + '.mp4')
        for moment in (1.85, 2.05, 3.0):
            end = moment + .25
            reference = ['ffmpeg', '-v', 'error', '-copyts', '-i', str(source), '-map', '0:a:0', '-af',
                         f'asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,atrim=start={moment}:end={end}',
                         '-ac', '1', '-ar', '48000', '-f', 'f32le', '-']
            left = subprocess.run(reference, capture_output=True, check=True).stdout
            right = subprocess.run(transcribe.audio_window_command(source, None, moment, end, rate=48000),
                                   capture_output=True, check=True).stdout
            a, b = np.frombuffer(left, '<f4'), np.frombuffer(right, '<f4')
            error = float(np.max(np.abs(a - b))) if len(a) == len(b) and len(a) else float('inf')
            record(f'footage: {name} AAC window {moment:g}s matches a linear decode', error < 1e-6,
                   f'samples={len(a)}/{len(b)}; max error={error}')
        times_result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                                       '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json',
                                       str(source)], capture_output=True, text=True, check=True)
        times = [float(frame['best_effort_timestamp_time'])
                 for frame in json.loads(times_result.stdout)['frames'] if 'best_effort_timestamp_time' in frame]
        reference_frames = linear_assembly_frames(source, 160, 120, scripts_dir)
        for moment in (1.9, 2.1):
            edit = {'version': 1, 'fps': 10, 'size': [160, 120], 'sources': {'v': str(source)},
                    'picture': [{'src': 'v', 'in': moment, 'out': moment + .3}]}
            code, output, directory = assemble(tool, j, f'edit-list-{name}-{moment}', edit)
            index = max((i for i, value in enumerate(times) if value <= moment + .0001), default=-1)
            if code in (0, 1) and index >= 0:
                actual = video_frames(directory / 'picture.mp4', 160, 120)[0]
                error = float(np.mean(np.abs(actual.astype(int) - reference_frames[index].astype(int))))
            else:
                error = float('inf')
            record(f'footage: {name} picture at {moment:g}s matches a linear frame', error < 12,
                   f'frame index={index}; mean RGB error={error}; {output[-150:]}')
    source = root / 'open-multiple.mp4'
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                            '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(source)],
                           capture_output=True, text=True, check=True)
    times = [float(frame['best_effort_timestamp_time']) for frame in json.loads(probe.stdout)['frames']
             if 'best_effort_timestamp_time' in frame]
    reference_frames = linear_assembly_frames(source, 160, 120, scripts_dir)
    for moment in (.5, 1.9, 2.1, 3.5):
        edit = {'version': 1, 'fps': 10, 'size': [160, 120], 'sources': {'v': str(source)},
                'picture': [{'src': 'v', 'in': moment, 'out': moment + .3}]}
        code, output, directory = assemble(tool, j, f'edit-list-open-multi-{moment}', edit)
        index = max((i for i, value in enumerate(times) if value <= moment + .0001), default=-1)
        if code in (0, 1) and index >= 0:
            actual = video_frames(directory / 'picture.mp4', 160, 120)[0]
            error = float(np.mean(np.abs(actual.astype(int) - reference_frames[index].astype(int))))
        else:
            error = float('inf')
        record(f'footage: open-GOP multi-edit frame at {moment:g}s matches linear decode', error < 12,
               f'frame index={index}; mean RGB error={error}; {output[-150:]}')


def check_frame_scan_errors(record, scripts_dir):
    """A discarded decoder log is not a selected-frame error; exits and frame flags still fail."""
    from types import SimpleNamespace
    from unittest.mock import patch
    spec = importlib.util.spec_from_file_location('frame_scan_round2', Path(scripts_dir) / 'render_common.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def scan(frames, exit_code=0, through=1):
        result = SimpleNamespace(returncode=exit_code, stderr='discarded packet decoder message',
                                 stdout=json.dumps({'frames': frames}))
        with patch.object(module, 'source_seek_safe', return_value=False), \
                patch.object(module.subprocess, 'run', return_value=result) as run:
            try:
                value = module.presentation_frame_before('ffprobe', 'fixture.mp4', 11.4, 0, through)
                status = ('ok', value)
            except ValueError as error:
                status = ('error', str(error))
        return status, run.call_args.args[0]

    def frame(time, flags=0):
        return {'best_effort_timestamp_time': str(time), 'decode_error_flags': flags}
    ok, command = scan([frame(11.3, 1), frame(11.4), frame(11.5)])
    bad, _ = scan([frame(11.4), frame(11.5, 1)])
    failed, _ = scan([frame(11.4)], 1)
    record('footage: discarded decode errors are ignored; selected errors and failed exits are refused',
           ok[0] == 'ok' and bad[0] == failed[0] == 'error'
           and '%13.400000000' in command,
           f'allowed={ok}; flagged={bad}; failed={failed}; interval={command[command.index("-read_intervals") + 1]}')
    held, _ = scan([frame(11.9)])
    too_late, _ = scan([frame(11.901)])
    damaged_hold, _ = scan([frame(11.9, 1)], through=.1)
    record('footage: first-frame hold allows 0.5 seconds but refuses a larger gap',
           held[0] == 'ok' and abs(held[1] - .5) < 1e-6 and too_late[0] == damaged_hold[0] == 'error',
           f'half second={held}; larger gap={too_late}; damaged held frame={damaged_hold}')


def check_seek_policy_atoms(record, j, scripts_dir):
    """Seek conservatively through empty, multiple and non-unit-rate MP4 edit lists."""
    spec = importlib.util.spec_from_file_location('round2_seek_atoms', Path(scripts_dir) / 'render_common.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = Path(j('seek-policy-atoms'))
    root.mkdir(parents=True, exist_ok=True)

    def box(kind, data):
        return struct.pack('>I4s', len(data) + 8, kind) + data

    fixtures = [('single', [(1000, 0, 1, 0)], True, 0), ('empty', [(1000, -1, 1, 0)], False, 0),
                ('multiple', [(1000, 0, 1, 0), (500, 500, 1, 0)], False, 0), ('none', [], False, 0),
                ('freeze', [(1000, 0, 0, 0)], False, 0), ('version-one', [(1000, 5, 1, 0)], True, 1)]
    results = {}
    for name, entries, expected, version in fixtures:
        payload = bytes([version, 0, 0, 0]) + struct.pack('>I', len(entries))
        for entry in entries:
            payload += struct.pack('>Qqhh' if version else '>Iihh', *entry)
        data = box(b'ftyp', b'isom') + box(b'moov', box(b'trak', box(b'edts', box(b'elst', payload))))
        path = root / (name + '.mp4')
        path.write_bytes(data)
        results[name] = module.source_seek_safe(path) == expected
    record('footage: seek policy handles single, empty, multiple and non-unit MP4 edits',
           all(results.values()), str(results))


def check_ordinary_starts(tool, record, j, scripts_dir):
    """First output frames match linear decodes for common MP4 and camcorder starts."""
    root = Path(j('ordinary-starts')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    original = root / 'original.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=10:d=4', '-f', 'lavfi', '-i',
           'sine=frequency=440:sample_rate=48000:duration=4', '-c:v', 'libx264', '-threads', '1',
           '-g', '20', '-c:a', 'aac', original)
    trimmed = root / 'trimmed.mp4'
    ffmpeg('-ss', '1.2', '-i', original, '-c', 'copy', trimmed)
    late = root / 'late.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=10:d=3', '-f', 'lavfi', '-i',
           'sine=frequency=440:sample_rate=48000:duration=3', '-filter_complex', '[0:v]setpts=PTS+0.1/TB[v]',
           '-map', '[v]', '-map', '1:a', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac',
           '-fps_mode', 'passthrough', late)
    transport = root / 'origin.ts'
    ffmpeg('-i', original, '-c', 'copy', '-output_ts_offset', '10', '-f', 'mpegts', transport)
    for name, source in (('trim', trimmed), ('late video', late), ('transport stream', transport)):
        reference = linear_assembly_frames(source, 160, 120, scripts_dir)
        edit = {'version': 1, 'fps': 10, 'size': [160, 120], 'sources': {'v': str(source)},
                'picture': [{'src': 'v', 'in': 0, 'out': .5}]}
        code, output, directory = assemble(tool, j, 'ordinary-' + name.replace(' ', '-'), edit)
        report_path = directory / 'report.json'
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        if code in (0, 1):
            actual = video_frames(directory / 'picture.mp4', 160, 120)[0]
            error = float(np.mean(np.abs(actual.astype(int) - reference[0].astype(int))))
        else:
            error = float('inf')
        has_note = any('held its first decoded frame' in note for note in report.get('notes', []))
        record('footage: ' + name + ' at zero matches the linear first frame',
               error < 12 and (name != 'late video' or has_note),
               f'mean RGB error={error}; hold note={has_note}; {output[-180:]}')


def check_decoded_end_clamp(tool, record, j):
    """An edit past where a damaged source decodes is shortened and reported, the same as one past its header, and
    its tail is never a frozen last frame; a line from cut.py is refused instead, and a declared in-point past the end
    is refused either way."""
    root = Path(j('decoded-end-clamp'))
    root.mkdir(parents=True, exist_ok=True)
    whole, short = root / 'whole.mp4', root / 'short.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=8', '-f', 'lavfi', '-i',
           'sine=frequency=440:sample_rate=48000:duration=8', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '10',
           '-c:a', 'aac', '-movflags', '+faststart', whole)
    data = whole.read_bytes()
    short.write_bytes(data[:int(len(data) * .6)])
    times = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', 'v:0', '-show_entries',
                            'frame=best_effort_timestamp_time', '-of', 'csv=p=0', str(short)],
                           capture_output=True, text=True).stdout.split()
    end = float(times[-1].strip(',')) + .1
    # The same frames with a truthful header, as a preview proxy of the damaged source has: the two must agree.
    honest = root / 'honest.mp4'
    ffmpeg('-i', short, '-map', '0:v:0', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', honest)
    start, stop = end - 1, end + 1
    results = {}
    for name, source in (('damaged', short), ('honest', honest)):
        edit = {'version': 1, 'fps': 10, 'size': [160, 90], 'sources': {'v': str(source)},
                'picture': [{'src': 'v', 'in': start, 'out': stop}]}
        code, output, directory = assemble(tool, j, 'decoded-end-' + name, edit)
        path = directory / 'report.json'
        report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        frames = video_frames(directory / 'picture.mp4', 160, 90) if code in (0, 1) else []
        changing = all(np.any(frames[number] != frames[number + 1]) for number in range(len(frames) - 1))
        results[name] = (code, round(report.get('duration_s', 0), 2),
                         any('Picture v out clamped' in note for note in report.get('notes', [])), changing)
    record('footage: past the decoded end the edit is shortened, reported and unfrozen, the same with a true header',
           results['damaged'] == results['honest'] and results['damaged'][0] == 1
           and abs(results['damaged'][1] - 1) < .11 and results['damaged'][2] and results['damaged'][3], str(results))
    edit = {'version': 1, 'fps': 10, 'size': [160, 90], 'sources': {'v': str(short)},
            'picture': [{'src': 'v', 'in': start, 'out': stop, 'line': 9}]}
    code, output, directory = assemble(tool, j, 'decoded-end-line', edit)
    record('footage: an item from a paper edit is refused with its film.md line instead of shortened',
           code == 2 and 'film.md line 9' in output and not (directory / 'picture.mp4').exists(), output[-300:])
    edit = {'version': 1, 'fps': 10, 'size': [160, 90], 'sources': {'v': str(short)},
            'picture': [{'src': 'v', 'in': end + 1, 'out': end + 2}]}
    code, output, directory = assemble(tool, j, 'decoded-end-in', edit)
    record('footage: an in-point past the decoded end is refused, not a frozen last frame',
           code == 2 and 'no picture frame covers' in output, output[-300:])
    edit = {'version': 1, 'fps': 10, 'size': [160, 90], 'sources': {'v': str(short)},
            'picture': [{'src': 'v', 'in': start, 'out': end}],
            'audio': [{'src': 'v', 'track': 'main', 'in': start, 'out': stop, 'at': 0}]}
    code, output, directory = assemble(tool, j, 'decoded-end-audio', edit)
    path = directory / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    record('footage: sound past where it decodes is reported, not silently padded',
           code == 1 and any('decodes only to' in note for note in report.get('notes', [])), str(report.get('notes')))
    held = root / 'held-gap.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=4', '-vf', "select='lt(n,10)+gte(n,30)',setpts='N*0.1/TB+"
           "if(gte(N,10),2/TB,0)'", '-fps_mode', 'vfr', '-c:v', 'ffv1', held)
    edit = {'version': 1, 'fps': 10, 'size': [160, 90], 'sources': {'v': str(held)},
            'picture': [{'src': 'v', 'in': .5, 'out': 2.5}]}
    code, output, directory = assemble(tool, j, 'decoded-end-gap', edit)
    path = directory / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    record('footage: a gap in a variable-rate source that goes on afterwards is not the end of its picture',
           code in (0, 1) and abs(report.get('duration_s', 0) - 2) < .11, output[-300:] + str(report.get('notes')))


def check_picture_out_clamp(tool, record, j, source):
    """An out-point after the picture end shortens the edit with an explicit review note."""
    edit = {'version': 1, 'fps': 10, 'size': [160, 90], 'sources': {'v': str(source)},
            'picture': [{'src': 'v', 'in': 2.5, 'out': 5}],
            'audio': [{'src': 'v', 'track': 'dialogue', 'in': 2.5, 'out': 5, 'at': 0}],
            'holds': [{'start': .1, 'end': .3}]}
    code, output, directory = assemble(tool, j, 'picture-out-clamp', edit)
    path = directory / 'report.json'
    report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    points = [point for point in report.get('snaps', [])
              if point.get('clock') == 'source edit time' and point.get('point') == 'out']
    declared = directory / 'declared.json'
    holds = json.loads(declared.read_text(encoding='utf-8')).get('ignore') if declared.exists() else None
    record('footage: picture and audio ending past the source are clamped and held ranges survive',
           code == 1 and len(points) == 1 and points[0]['requested'] == 5
           and abs(points[0]['snapped'] - 4) < .001 and abs(report.get('duration_s', 0) - 1.5) < .001
           and any('Picture v out clamped' in note for note in report.get('notes', []))
           and holds == '0.100-0.300', f'points={points}; hold={holds}; {output[-250:]}')


def check_seeked_audio_window(record, j, scripts_dir):
    """A late AAC window must retain sample alignment and near-identical decoded amplitudes."""
    root = Path(j('seeked-audio')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'long-aac.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=96x64:r=10:d=12', '-f', 'lavfi', '-i',
           'aevalsrc=0.3*sin(2*PI*(300+10*floor(t))*t):s=48000:d=12', '-c:v', 'libx264', '-threads', '1',
           '-g', '20', '-c:a', 'aac', source)
    spec = importlib.util.spec_from_file_location('round2_audio_window', Path(scripts_dir) / 'transcribe.py')
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    command = transcribe.audio_window_command(source, None, 8.234, 8.734, rate=48000)
    linear = list(command)
    for flag in ('-ss', '-t'):
        if flag in linear:
            index = linear.index(flag)
            del linear[index:index + 2]
    a = subprocess.run(linear, capture_output=True, check=True).stdout
    b = subprocess.run(command, capture_output=True, check=True).stdout
    left, right = np.frombuffer(a, '<f4'), np.frombuffer(b, '<f4')
    error = float(np.max(np.abs(left - right))) if len(left) == len(right) and len(left) else float('inf')
    aligned = float(np.mean(np.abs(left - right))) if len(left) == len(right) and len(left) > 1 else float('inf')
    shifted = min(float(np.mean(np.abs(left[1:] - right[:-1]))),
                  float(np.mean(np.abs(left[:-1] - right[1:])))) if len(left) == len(right) and len(left) > 1 else 0
    record('footage: late seeked AAC window preserves source-clock sample alignment',
           '-ss' in command and len(left) == 24000 and error < 1 / (16 * 32768) and aligned < shifted / 1000,
           f'seeked={"-ss" in command}; samples={len(left)}/{len(right)}; max error={error}; '
           f'mean aligned/one-sample-shift={aligned}/{shifted}')
    late = root / 'late-aac.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=96x64:r=10:d=12', '-itsoffset', '1', '-f', 'lavfi', '-i',
           'aevalsrc=0.3*sin(2*PI*(350+10*floor(t))*t):s=48000:d=11', '-c:v', 'libx264', '-threads', '1',
           '-g', '20', '-c:a', 'aac', late)
    command = transcribe.audio_window_command(late, None, 8.234, 8.734, rate=48000)
    linear = list(command)
    for flag in ('-ss', '-t'):
        if flag in linear:
            index = linear.index(flag)
            del linear[index:index + 2]
    a = np.frombuffer(subprocess.run(linear, capture_output=True, check=True).stdout, '<f4')
    b = np.frombuffer(subprocess.run(command, capture_output=True, check=True).stdout, '<f4')
    error = float(np.max(np.abs(a - b))) if len(a) == len(b) and len(a) else float('inf')
    record('footage: late-starting AAC with an empty edit uses a sample-exact linear window',
           '-ss' not in command and len(a) == len(b) == 24000 and error == 0,
           f'seeked={"-ss" in command}; samples={len(a)}/{len(b)}; max error={error}')
    import re
    encoders = subprocess.run(['ffmpeg', '-hide_banner', '-encoders'], capture_output=True, text=True, check=True)
    if not re.search(r'^\s*A\S+\s+libopus\s', encoders.stdout, re.MULTILINE):
        print('SKIP  footage: coarse Opus clock case needs the optional libopus encoder')
        return
    webm = root / 'coarse-opus.webm'
    ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=533:sample_rate=48000:duration=12', '-c:a', 'libopus', webm)
    command = transcribe.audio_window_command(webm, None, 8.234, 8.734, rate=16000)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=start_time', '-of', 'json', str(webm)],
                           capture_output=True, text=True, check=True)
    origin = float(json.loads(probe.stdout)['format']['start_time'])
    reference = ['ffmpeg', '-v', 'error', '-copyts', '-i', str(webm), '-map', '0:a:0', '-vn', '-af',
                 f'asetpts=PTS-({origin:.9f})/TB,aresample=16000:async=1:first_pts=0,'
                 'atrim=start_sample=131744:end_sample=139744,'
                 'asetpts=PTS-STARTPTS,apad=whole_len=8000,atrim=end_sample=8000',
                 '-ac', '1', '-ar', '16000', '-f', 'f32le', '-']
    result = subprocess.run(command, capture_output=True, check=True).stdout
    expected = subprocess.run(reference, capture_output=True, check=True).stdout
    record('footage: coarse Opus timestamps keep the sample-exact linear window',
           '-ss' not in command and len(result) == 32000 and result == expected,
           f'origin={origin}; seeked={"-ss" in command}; output bytes={len(result)}')


def check_world_retimes(tool, record, j, scripts_dir):
    """Measure both rates, a tail event and the atempo fallback on a known-answer fixture."""
    from unittest.mock import patch
    spec = importlib.util.spec_from_file_location('wave2_retimes', Path(scripts_dir) / 'assemble.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = Path(j('world-retimes')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    events = np.array([.5, 1.25, 2.0, 2.65, 2.94])
    rubberband = module.has_filter('ffmpeg', 'rubberband')
    for rate in (44100, 48000):
        source = root / f'{rate}.wav'
        signal = np.zeros(rate * 3, dtype=np.float32)
        for moment in events:
            signal[round(moment * rate):round((moment + .05) * rate)] = .5
        with wave.open(str(source), 'wb') as handle:
            handle.setparams((1, 2, rate, len(signal), 'NONE', 'not compressed'))
            handle.writeframes(np.int16(signal * 32767).tobytes())
        for speed in (.5, 1.5):
            folder = root / f'{rate}-{speed}'
            folder.mkdir(exist_ok=True)
            edit = {'sources': {'a': {'file': str(source)}}, 'audio': [
                {'src': 'a', 'track': 'speech', 'in': 0, 'out': 3, 'at': 0, 'fade_ms': 0}]}
            clip = {'src': 'a', 'speed': speed, 'start': 0, 'stop': 3}
            if not rubberband:
                print(f'SKIP  footage: {rate} Hz at {speed:g}x frame-level retime: rubberband is unavailable')
                continue
            notes = []
            snaps = module.render_audio('ffmpeg', 'ffprobe', edit, root, [clip], 3 / speed,
                                        folder, folder, notes)
            decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder / 'audio-0.wav'),
                                      '-ac', '1', '-f', 'f32le', '-'], capture_output=True, check=True)
            data = np.frombuffer(decoded.stdout, '<f4')
            hits = np.flatnonzero(np.abs(data) > .2) / 48000
            starts = hits[np.r_[True, np.diff(hits) > .08]] if len(hits) else np.array([])
            error = float(np.max(np.abs(starts - events / speed))) if len(starts) == len(events) else float('inf')
            report = next(row for row in snaps if row['point'] == 'retime duration')
            tail = data[max(0, round((3 / speed - .05) * 48000)):]
            record(f'footage: {rate} Hz at {speed:g}x retains five events and the tail within a 60 fps frame',
                   report.get('stretcher') == 'rubberband' and error < 1 / 60
                   and abs(len(data) / 48000 - 3 / speed) < .002
                   and len(tail) > 0 and np.max(np.abs(tail)) > .05
                   and any('transients can move' in note for note in notes),
                   f'error={error}; starts={starts.tolist()}; tail peak={np.max(np.abs(tail)) if len(tail) else 0}; '
                   f'report={report}; notes={notes}')
    folder = root / 'fallback'
    folder.mkdir(exist_ok=True)
    notes = []
    with patch.object(module, 'has_filter', return_value=False):
        snaps = module.render_audio('ffmpeg', 'ffprobe', edit, root, [clip], 3 / speed, folder, folder, notes)
    report = next(row for row in snaps if row['point'] == 'retime duration')
    record('footage: unavailable rubberband falls back to atempo with a sync warning',
           report.get('stretcher') == 'atempo' and any('atempo' in note for note in notes), str(notes))
    folder = root / 'extreme'
    folder.mkdir(exist_ok=True)
    notes = []
    clip = {'src': 'a', 'speed': .25, 'start': 0, 'stop': 3}
    snaps = module.render_audio('ffmpeg', 'ffprobe', edit, root, [clip], 12, folder, folder, notes)
    report = next(row for row in snaps if row['point'] == 'retime duration')
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder / 'audio-0.wav'),
                              '-ac', '1', '-f', 'f32le', '-'], capture_output=True, check=True)
    data = np.frombuffer(decoded.stdout, '<f4')
    hits = np.flatnonzero(np.abs(data) > .2) / 48000
    starts = hits[np.r_[True, np.diff(hits) > .08]] if len(hits) else np.array([])
    shifts = (starts - events / .25).tolist() if len(starts) == len(events) else []
    record('footage: 0.25x retime explicitly warns that event shifts may exceed one frame',
           report.get('speed') == .25 and any('below 0.5x' in note and 'sync point' in note for note in notes),
           f'stretcher={report.get("stretcher")}; event shifts_s={shifts}; notes={notes}')
