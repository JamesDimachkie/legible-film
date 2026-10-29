"""Synthetic footage editing integration checks. These do not judge perceptual quality."""
import json
import math
import subprocess
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
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo',
                             '-pix_fmt', 'rgb24', '-'], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
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


def run_footage_cases(tool, record, j, scripts_dir):
    """Exercise exact picture and sound answers on small synthetic sources."""
    width, height, fps = fixture(j)
    source = j('footage-source.mkv')
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
    # Half-speed audio must retain its tone frequency and picture duration.
    slow = dict(base, picture=[{'src': 'a', 'in': .2, 'out': 1.2, 'speed': .5}],
                audio=[{'track': 'tone', 'src': 'a', 'in': .2, 'out': 1.2, 'at': 0}])
    code, output, slow_dir = assemble(tool, j, 'footage-slow', slow)
    if code in (0, 1) and (slow_dir / 'tone.wav').exists():
        with wave.open(str(slow_dir / 'tone.wav'), 'rb') as file:
            rate = file.getframerate()
            signal = np.frombuffer(file.readframes(file.getnframes()), np.int16).reshape(-1, 2)[:, 0]
        window = signal[round(.2 * rate):round(1.7 * rate)].astype(float)
        spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
        frequency = np.fft.rfftfreq(len(window), 1 / rate)[int(np.argmax(spectrum))]
        slow_frames = video_frames(slow_dir / 'picture.mp4', width, height)
        record('footage: half-speed duration and pitch', len(slow_frames) == 20 and abs(frequency - 440) < 3,
               f'{len(slow_frames)} frames; {frequency:.2f} Hz')
    else:
        record('footage: half-speed duration and pitch', False, output[-200:])
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
    # A deliberately uneven source makes .69 s select the .7 s decoded timestamp.
    vfr = j('footage-vfr.mkv')
    ffmpeg('-i', source, '-an', '-vf', "setpts='if(lt(N,5),N/(10*TB),(.5+(N-5)/5)/TB)'",
           '-fps_mode', 'vfr', '-c:v', 'ffv1', vfr)
    vfr_edit = dict(base, sources={'a': {'file': vfr}}, picture=[{'src': 'a', 'in': .69, 'out': 1.29}])
    code, output, vfr_dir = assemble(tool, j, 'footage-vfr-cut', vfr_edit)
    if code in (0, 1):
        report = json.loads((vfr_dir / 'report.json').read_text(encoding='utf-8'))
        values = [snap['snapped'] for snap in report['snaps']]
        found = counter(video_frames(vfr_dir / 'picture.mp4', width, height)[0])
        record('footage: VFR cut uses decoded frame timestamps',
               len(values) == 2 and abs(values[0] - .7) < .001 and abs(values[1] - 1.3) < .001
               and found == 6, f'snaps {values}; first counter {found}')
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
