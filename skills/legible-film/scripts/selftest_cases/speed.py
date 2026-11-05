"""Known-answer cases for the plain-cut path and the phone-footage notes.

Each picture case burns a nine-bit frame counter into real footage (the first-cut example, or a test pattern where the
example is not installed), renders the same film through FFmpeg's picture and through every frame in Python, and reads
which frame each output shows. These prove that both paths choose the same source frames and that their pictures and
sound agree on these sources, not that a real cut looks right.
"""
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

WIDTH, HEIGHT = 320, 180
BIT, FIRST = 18, 8
# The two pictures differ by a resampler and by one RGB round trip: a whole-frame mean above this is another picture.
SAME_PICTURE = 3.0
BT709_ENCODE = ('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '10', '-pix_fmt', 'yuv420p', '-colorspace', 'bt709',
                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv')
FRONT = ('---\ntitle: Speed\naudience: a test\ntakeaway: the paths agree\nstory: one cut, two paths\n'
         'size: {size}\nfps: {fps}\ncaptions: {captions}\n---\n')


def load(scripts_dir, name):
    """Load one of the skill's scripts as a module."""
    spec = importlib.util.spec_from_file_location(f'speed_{name}', Path(scripts_dir) / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ffmpeg(*args, data=None):
    """Run one FFmpeg fixture command and raise on failure."""
    result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', *map(str, args)], input=data,
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-800:])


def picture_input(scripts_dir, rate):
    """FFmpeg input options for moving footage: the example clip when it is installed, else a test pattern."""
    example = Path(scripts_dir).parents[2] / 'examples' / 'first-cut' / 'tears-of-steel-bridge.mp4'
    if example.is_file():
        return ['-stream_loop', '1', '-i', example, '-vf',
                f'scale=-2:{HEIGHT}:flags=lanczos,crop={WIDTH}:{HEIGHT},fps={rate},format=rgb24']
    return ['-f', 'lavfi', '-i', f'testsrc2=s={WIDTH}x{HEIGHT}:r={rate}', '-vf', 'format=rgb24']


def counted_frames(scripts_dir, count, rate):
    """Raw RGB frames of moving footage, each with its number burned in as nine white or black squares."""
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-nostdin', *map(str, picture_input(scripts_dir, rate)),
               '-frames:v', str(count), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(command, capture_output=True, check=True).stdout
    size = WIDTH * HEIGHT * 3
    frames = []
    for number in range(count):
        image = Image.frombytes('RGB', (WIDTH, HEIGHT), raw[number * size:(number + 1) * size])
        draw = ImageDraw.Draw(image)
        for bit in range(9):
            left = FIRST + bit * BIT
            draw.rectangle((left, FIRST, left + 14, FIRST + 14), fill='white' if number & (1 << bit) else 'black')
        frames.append(image.tobytes())
    return b''.join(frames)


def tone(seconds):
    """FFmpeg input options for a tone that changes every half second, so a misplaced stretch of sound shows."""
    return ['-f', 'lavfi', '-i', f"aevalsrc='0.2*sin(2*PI*(300+80*floor(2*t))*t)':s=48000:d={seconds}"]


def counted_source(scripts_dir, path, seconds=6, rate=30, picture='', encode=(), audio=()):
    """A counted source file: `picture` filters its frames, `encode` replaces its video encoder options."""
    count = int(seconds * rate)
    # Unless `encode` says otherwise the file is tagged BT.709 throughout, the picture the plain path keeps in YUV.
    filters = 'scale=640:360:flags=neighbor' + (',' + picture if picture else '')
    if not encode:
        filters += ',scale=out_color_matrix=bt709:out_range=tv,format=yuv420p'
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', rate, '-i', 'pipe:0',
           *(audio or tone(seconds)), '-map', '0:v', '-map', '1:a', '-vf', filters,
           *(encode or BT709_ENCODE),
           '-c:a', 'aac', '-b:a', '128k', '-shortest', path, data=counted_frames(scripts_dir, count, rate))


def facts(path):
    """ffprobe's streams and format for a file."""
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def project(root, source, film, words=None):
    """A project folder holding one source (alias src_01) and a film.md; returns its folder."""
    root = Path(root)
    (root / 'map').mkdir(parents=True, exist_ok=True)
    (root / 'media').mkdir(exist_ok=True)
    media = root / 'media' / Path(source).name
    shutil.copy2(source, media)
    info = facts(media)
    video = next(row for row in info['streams'] if row['codec_type'] == 'video')
    audio = next((row for row in info['streams'] if row['codec_type'] == 'audio'), None)
    row = {'alias': 'src_01', 'role': 'other', 'path': 'media/' + media.name,
           'sha256': hashlib.sha256(media.read_bytes()).hexdigest(), 'bytes': media.stat().st_size,
           'duration_s': float(info['format']['duration']),
           'video': {'width': video['width'], 'height': video['height'], 'fps': video['r_frame_rate']},
           'audio': {'channels': audio['channels'], 'rate': int(audio['sample_rate']), 'index': audio['index']}
           if audio else None, 'mapped': {'words': bool(words), 'shots': False, 'audio': False}}
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    if words:
        rows = [{'id': f'src_01-w{number + 1:06d}', 'text': word[0], 'start': word[1], 'end': word[2], 'p': 0.99,
                 'speaker': None, 'estimated': False} for number, word in enumerate(words)]
        (root / 'map' / 'src_01').mkdir(exist_ok=True)
        (root / 'map' / 'src_01' / 'words.json').write_text(json.dumps(
            {'version': 1, 'source': 'src_01', 'engine': 'fixture', 'language': 'en', 'draft': False, 'words': rows}),
            encoding='utf-8')
    (root / 'film.md').write_text(film, encoding='utf-8')
    return root


def frames_of(video):
    """Every encoded frame of a video as an HxWx3 array stack."""
    stream = next(row for row in facts(video)['streams'] if row['codec_type'] == 'video')
    width, height = stream['width'], stream['height']
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:v:0', '-fps_mode', 'passthrough',
                          '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, height, width, 3)


def counters(frames):
    """The number burned into each frame of a film at the counted source's shape."""
    return [sum(1 << bit for bit in range(9) if float(frame[15, 15 + bit * BIT].mean()) > 128) for frame in frames]


def difference(first, second):
    """The largest whole-frame mean absolute difference between two equal stacks, in 8-bit levels."""
    if len(first) != len(second) or not len(first) or first.shape != second.shape:
        return float('inf')
    return max(float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) for a, b in zip(first, second))


def sound_hash(video):
    """The SHA-256 of a file's first audio stream's packets."""
    result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-i', str(video), '-map', '0:a:0', '-c', 'copy',
                             '-f', 'hash', '-hash', 'sha256', '-'], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def render(tool, root, *args):
    """Render the next version; returns (exit code, output, version folder, manifest)."""
    versions = sorted(Path(root, 'cuts').glob('v[0-9]*')) if Path(root, 'cuts').is_dir() else []
    code, output = tool('cut.py', 'render', root, *args)
    folder = Path(root) / 'cuts' / f'v{len(versions) + 1:03d}'
    manifest = folder / 'manifest.json'
    return code, output, folder, json.loads(manifest.read_text(encoding='utf-8')) if manifest.is_file() else {}


def path_of(manifest):
    """Which picture path a version's manifest says ran."""
    return (manifest.get('picture_path') or {}).get('path')


def compare_paths(tool, record, name, root, expected=None, sound=True, limit=SAME_PICTURE):
    """Render one film through FFmpeg's picture (final and preview) and through every frame; the shown frames, the
    pictures and the sound must agree."""
    code_a, out_a, fast, fast_manifest = render(tool, root, '--final')
    code_b, out_b, slow, slow_manifest = render(tool, root, '--final', '--every-frame')
    code_c, out_c, small, small_manifest = render(tool, root)
    if not all(folder.joinpath('preview.mp4').is_file() for folder in (fast, slow, small)):
        record(f'speed: {name} renders through both paths', False, (out_a + out_b + out_c)[-500:])
        return None
    first, second = frames_of(fast / 'preview.mp4'), frames_of(slow / 'preview.mp4')
    preview = frames_of(small / 'preview.mp4')
    shown, reference, previewed = counters(first), counters(second), counters(preview)
    record(f'speed: {name} ran through the path each version says',
           path_of(fast_manifest) == 'ffmpeg' and path_of(small_manifest) == 'ffmpeg'
           and path_of(slow_manifest) == 'every-frame' and code_a in (0, 1) and code_b in (0, 1) and code_c in (0, 1),
           f'{path_of(fast_manifest)}, {path_of(small_manifest)}, {path_of(slow_manifest)}')
    target = expected if expected is not None else reference
    wrong = [(index, a, b) for index, (a, b) in enumerate(zip(shown, target)) if a != b]
    record(f'speed: {name} shows the same source frames on both paths, final and preview',
           shown == reference == previewed and shown == target and len(shown) > 0,
           f'{len(shown)}/{len(reference)}/{len(previewed)} frames; first differences {wrong[:4]}')
    gap = difference(first, second)
    record(f'speed: {name} pictures agree within {limit:g} levels', gap <= limit, f'worst frame differs by {gap:.2f}')
    if sound:
        same = sound_hash(fast / 'preview.mp4') == sound_hash(slow / 'preview.mp4')
        stems = sorted(path.name for path in (fast / 'stems').glob('*.wav'))
        same_stems = bool(stems) and all(
            hashlib.sha256((fast / 'stems' / name).read_bytes()).digest()
            == hashlib.sha256((slow / 'stems' / name).read_bytes()).digest() for name in stems)
        record(f'speed: {name} sound is placed the same on both paths', same and same_stems, f'stems {stems}')
    return fast, slow, fast_manifest


# ----------------------------------------------------------------------------------------------- eligibility

def check_eligibility(record, scripts_dir):
    """Whether a plan can take FFmpeg's picture comes from one rule, and anything it does not know stays per frame."""
    assemble = load(scripts_dir, 'assemble')
    item = {'src': 'a', 'in': 0, 'out': 1, 'fit': 'cover', 'crop': {'path': [[0, .5, .5]]}}
    plain = {'version': 1, 'size': [64, 64], 'fps': 10, 'sources': {'a': {'file': 'a.mp4'}}, 'picture': [item],
             'audio': [], 'overlays': []}
    clip = {'file': 'a.mp4', 'mode': 'nearest', 'kind': 'cut', 'overlap': 0, 'hold_previous': False, 'fit': 'cover',
            'crop': [[0, .5, .5]], 'zoom': 1, 'crop_info': {}, 'sw': 64, 'sh': 64, 'at': 0, 'duration': 1,
            'time_tick': 1e-5, 'speed': 1, 'background': 'black'}
    sources = {'a.mp4': {'field_order': 'progressive'}}

    def reason(edit=None, clips=None, properties=None):
        return assemble.plain_cut_reason(edit or plain, clips or [clip], properties or sources, 10)

    record('speed: a plain cut can take FFmpeg picture', reason() == '', reason())
    record('speed: burned captions alone leave a cut plain', reason(dict(plain, overlays=[{'kind': 'captions'}])) == '')
    stays = {
        'a dissolve': dict(clips=[clip, dict(clip, at=1, kind='dissolve', overlap=.25)]),
        'a dip': dict(clips=[clip, dict(clip, at=1, kind='dip', overlap=.25)]),
        'a held frame': dict(clips=[clip, dict(clip, at=1, hold_previous=True)]),
        'a blended retime': dict(clips=[dict(clip, mode='blend')]),
        'a motion retime': dict(clips=[dict(clip, mode='motion')]),
        'a moving crop': dict(clips=[dict(clip, crop=[[0, .2, .5], [1, .8, .5]])]),
        'an automatic crop': dict(clips=[dict(clip, crop_info={'method_spans': []})]),
        'a coloured letterbox': dict(clips=[dict(clip, fit='contain', background='#102030')]),
        'an interlaced source': dict(properties={'a.mp4': {'field_order': 'tt'}}),
        'an image overlay': dict(edit=dict(plain, overlays=[{'kind': 'image', 'src': 'a', 'from': 0, 'to': 1}])),
        'a moving overlay': dict(edit=dict(plain, overlays=[{'kind': 'video', 'src': 'a', 'from': 0, 'to': 1}])),
        'a blur': dict(edit=dict(plain, overlays=[{'kind': 'blur', 'from': 0, 'to': 1}])),
        'an overlay kind added later': dict(edit=dict(plain, overlays=[{'kind': 'lower-third'}])),
        'a picture key added later': dict(edit=dict(plain, picture=[dict(item, angle='cam-2')])),
        'an edit key added later': dict(edit=dict(plain, recordings=[{'group': 'stage'}])),
        'a gap in the picture': dict(clips=[clip, dict(clip, at=3)])}
    for name, case in stays.items():
        why = reason(**case)
        record(f'speed: {name} stays on the every-frame path', bool(why), why)
    native = {'coded_width': 1920, 'coded_height': 1080, 'source_pixel_format': 'yuv420p', 'source_range': 'tv',
              'source_matrix': 'bt709', 'source_transfer': 'bt709', 'source_primaries': 'bt709'}
    others = {'BT.601': dict(source_matrix='smpte170m'), 'full range': dict(source_range='pc'),
              '10-bit': dict(source_pixel_format='yuv420p10le'), 'HLG': dict(source_transfer='arib-std-b67'),
              'a small untagged file, read as BT.601': dict(coded_width=640, coded_height=360, source_matrix='unknown')}
    record('speed: only 8-bit limited-range BT.709 stays in YUV',
           assemble.native_709(native) and assemble.native_709(dict(native, source_matrix='unknown'))
           and not any(assemble.native_709(dict(native, **change)) for change in others.values()))


def check_shared_encoder_default(record, scripts_dir):
    """Film and motion renders run several encoders at once, so only assemble.py asks for more threads."""
    common = load(scripts_dir, 'render_common')
    default = common.h264_args(320, 180, 30)
    asked = common.h264_args(320, 180, 30, threads=4)
    record('speed: the shared H.264 options still default to one thread, and take a count when asked',
           default[default.index('-threads') + 1] == '1' and asked[asked.index('-threads') + 1] == '4', str(asked))


def check_fixed_cost(record, j, scripts_dir):
    """Planning asks ffprobe about a source once, however many lines use it, and its timestamp pass does no colour."""
    assemble = load(scripts_dir, 'assemble')
    root = Path(j('speed-plan'))
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'a.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=6', '-c:v', 'libx264', '-preset', 'ultrafast', source)
    edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': start, 'out': start + 1} for start in range(5)]}
    asked, scans = [], []
    real_run, real_frames = assemble.run, assemble.Frames

    def counted(command, *args, **kwargs):
        if 'ffprobe' in Path(command[0]).name:
            asked.append(command)
        return real_run(command, *args, **kwargs)

    class Scan(real_frames):
        def __init__(self, ffmpeg_path, path, vf, size, options=None, timestamps_only=False):
            if timestamps_only:
                scans.append((vf, list(options or [])))
            super().__init__(ffmpeg_path, path, vf, size, options, timestamps_only)

    assemble.run, assemble.Frames = counted, Scan
    try:
        assemble.conform('ffmpeg', 'ffprobe', edit, root, root, 1 << 30, [])
    finally:
        assemble.run, assemble.Frames = real_run, real_frames
    many = [command for command in asked if '-show_streams' in command or '-show_format' in command]
    record('speed: planning five lines of one source probes its header no more than for one line',
           len(many) <= 3, f'{len(many)} header probes in {len(asked)} ffprobe runs')
    record('speed: the timestamp pass does no colour or scaling',
           len(scans) == 5 and not any('rgb24' in vf or 'scale=' in vf or 'colorspace' in vf for vf, _ in scans),
           scans[0][0] if scans else 'no scan')


# ----------------------------------------------------------------------------------------------- the same frames

def expected_held(times, cuts, rate):
    """For each output frame, the last source frame at or before its source time: the rule both paths must keep."""
    shown = []
    at = Fraction(0)
    for start, stop in cuts:
        count = round((stop - start) * rate)
        for number in range(count):
            moment = float(start + Fraction(number, 1) / rate)
            shown.append(max(index for index, value in enumerate(times) if value <= moment + 1e-4))
        at += stop - start
    return shown


def check_plain_paths(tool, record, j, scripts_dir):
    """A plain cut of a clean source, which of the two paths ran, and that the printed output says so."""
    source = Path(j('speed-clean.mp4'))
    counted_source(scripts_dir, source, seconds=4)
    film = FRONT.format(size='320x180', fps=30, captions='none') + (
        '- src_01 0:00.30-0:01.30 first {sound}\n- src_01 0:02.00-0:03.00 second {sound}\n')
    root = project(j('speed-clean'), source, film)
    expected = list(range(9, 39)) + list(range(60, 90))
    compared = compare_paths(tool, record, 'a clean source', root, expected)
    code, output = tool('cut.py', 'render', root, '--final')
    record('speed: the printed output names the path', code in (0, 1) and 'picture: FFmpeg' in output, output[-300:])
    code, output = tool('cut.py', 'render', root, '--final', '--every-frame')
    record('speed: the printed output says when every frame was asked for',
           code in (0, 1) and 'picture: every frame' in output and 'asked for' in output, output[-300:])
    if compared:
        report = json.loads((compared[0] / 'assemble-report.json').read_text(encoding='utf-8'))
        record('speed: the assembly report names the path too', report.get('picture_path', {}).get('path') == 'ffmpeg')
    film = FRONT.format(size='320x180', fps=30, captions='none') + (
        '- src_01 0:00.30-0:01.30 first {sound}\n- src_01 0:02.00-0:03.00 second {dissolve 0.2}\n')
    joined = project(j('speed-dissolve'), source, film)
    code, output, _, manifest = render(tool, joined, '--final')
    record('speed: a dissolve says it took the every-frame path and why',
           path_of(manifest) == 'every-frame' and 'dissolve' in (manifest.get('picture_path') or {}).get('reason', '')
           and 'picture: every frame' in output, str(manifest.get('picture_path')))


def check_hard_sources(tool, record, j, scripts_dir, skip):
    """Variable frame rate, rotated, late-audio and non-square-pixel sources: same frames, same picture, same sound."""
    film = FRONT.format(size='320x180', fps=30, captions='none') + (
        '- src_01 0:00.50-0:01.50 first {sound}\n- src_01 0:02.50-0:03.50 second {sound}\n')
    on_grid = list(range(15, 45)) + list(range(75, 105))

    # Three uneven intervals repeating: 25, 40 and 35 ms, so frames fall between and on the output frames.
    vfr = Path(j('speed-vfr.mp4'))
    counted_source(scripts_dir, vfr, seconds=6, picture=r"setpts='(floor(N/3)*0.1+if(eq(mod(N,3),0),0,if(eq(mod(N,3),1),"
                   r"0.025,0.065)))/TB'",
                   encode=(*BT709_ENCODE, '-fps_mode', 'vfr', '-video_track_timescale', '90000'))
    pts = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=pts_time',
                          '-of', 'csv=p=0', str(vfr)], capture_output=True, text=True, check=True).stdout.split()
    times = sorted(float(value.strip(' ,')) for value in pts if value.strip(' ,'))
    origin = times[0]
    times = [value - origin for value in times]
    expected = expected_held(times, ((Fraction(1, 2), Fraction(3, 2)), (Fraction(5, 2), Fraction(7, 2))), 30)
    compare_paths(tool, record, 'a variable-frame-rate source', project(j('speed-vfr'), vfr, film), expected)

    rotated = Path(j('speed-rotated.mp4'))
    upright = Path(j('speed-rotated-coded.mp4'))
    counted_source(scripts_dir, upright, seconds=4, picture='transpose=clock')
    try:
        ffmpeg('-display_rotation', '90', '-i', upright, '-c', 'copy', rotated)
    except RuntimeError as error:
        skip('speed: a rotated source', f'this FFmpeg cannot write a display rotation: {str(error)[-80:]}', 4)
    else:
        compare_paths(tool, record, 'a rotated source', project(j('speed-rotated'), rotated, film), on_grid)

    late = Path(j('speed-late.mp4'))
    counted_source(scripts_dir, late, seconds=5, audio=['-itsoffset', '0.75', *tone(5)])
    compare_paths(tool, record, 'a source whose sound starts late', project(j('speed-late'), late, film), on_grid)

    wide = Path(j('speed-anamorphic.mp4'))
    counted_source(scripts_dir, wide, seconds=4, picture='scale=480:360:flags=neighbor,setsar=4/3')
    compare_paths(tool, record, 'a non-square-pixel source', project(j('speed-anamorphic'), wide, film), on_grid)


def small_edit(root, source):
    """An edit.json for assemble.py: two lines of a counted source, the second from past its first second."""
    edit = {'version': 1, 'size': [WIDTH, HEIGHT], 'fps': 30, 'sources': {'a': {'file': str(source)}},
            'picture': [{'src': 'a', 'in': .5, 'out': 1.0}, {'src': 'a', 'in': 3.5, 'out': 4.0}]}
    path = Path(root) / 'edit.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(edit), encoding='utf-8')
    return edit, path


def check_failures(record, j, scripts_dir):
    """A seeked playback failure restarts linearly with the same frames, and a failed FFmpeg picture falls back."""
    source = Path(j('speed-failures.mp4'))
    counted_source(scripts_dir, source, seconds=5)
    assemble = load(scripts_dir, 'assemble')
    edit, path = small_edit(j('speed-failures'), source)
    root = path.parent
    notes = []
    cache, properties, _ = assemble.conform('ffmpeg', 'ffprobe', edit, root, root, 1 << 30, notes)
    clips = assemble.plan_picture(edit, root, cache, 'ffmpeg', 'ffprobe', root, notes)[0]
    total = clips[-1]['at'] + clips[-1]['duration']
    real_frames = assemble.Frames
    failures = []

    class FailPlaybackOnce(real_frames):
        """The second clip's seeked playback stops after three frames, once."""

        def __init__(self, ffmpeg_path, filename, vf, size, options=None, timestamps_only=False):
            super().__init__(ffmpeg_path, filename, vf, size, options, timestamps_only)
            self.fail = not timestamps_only and '-ss' in (options or []) and not failures

        def __iter__(self):
            for number, raw in enumerate(super().__iter__()):
                if self.fail and number == 3:
                    self.proc.kill()
                    self.proc.stdout.close()
                    self.proc.wait()
                    self.reader.join()
                    failures.append(True)
                    return
                yield raw

        def times(self, count):
            if failures and self.fail:
                raise RuntimeError('injected seeked playback failure')
            return super().times(count)

    picture = root / 'retried.mp4'
    assemble.Frames = FailPlaybackOnce
    try:
        count = assemble.render_plain_with_retry('ffmpeg', clips, WIDTH, HEIGHT, 30, total, str(picture))
    finally:
        assemble.Frames = real_frames
    shown = counters(frames_of(picture))
    expected = list(range(15, 30)) + list(range(105, 120))
    record('speed: a failed seeked clip restarts linearly and shows the same frames',
           len(failures) == 1 and count == 30 and shown == expected, f'{len(failures)} failures, shown {shown[:4]}')

    def broken(*args, **kwargs):
        raise RuntimeError('a filter this FFmpeg does not have')

    edit, path = small_edit(j('speed-fallback'), source)
    arguments, real_path = sys.argv, assemble.render_plain_with_retry
    sys.argv = ['assemble.py', str(path), '--out', str(path.parent / 'picture.mp4')]
    assemble.render_plain_with_retry = broken
    try:
        code = assemble.main()
    finally:
        sys.argv, assemble.render_plain_with_retry = arguments, real_path
    report = json.loads((path.parent / 'assemble-report.json').read_text(encoding='utf-8'))
    ran = report.get('picture_path') or {}
    record('speed: a failed FFmpeg picture falls back to every frame and says why',
           code in (0, 1) and ran.get('path') == 'every-frame' and 'does not have' in ran.get('reason', '')
           and counters(frames_of(path.parent / 'picture.mp4')) == expected, str(ran))


def check_pause_and_still(tool, record, j, scripts_dir):
    """A pause and a freeze frame are generated clips, so they can be part of a plain cut."""
    source = Path(j('speed-pause.mp4'))
    counted_source(scripts_dir, source, seconds=4)
    film = FRONT.format(size='320x180', fps=30, captions='none') + (
        '- src_01 0:00.50-0:01.50 first {sound}\n- pause 0.5\n- still src_01 0:02.00 0.5 freeze\n'
        '- src_01 0:02.50-0:03.00 last {sound}\n')
    root = project(j('speed-pause'), source, film)
    compare_paths(tool, record, 'a pause and a freeze', root, sound=True)


def check_retime(tool, record, j, scripts_dir):
    """A nearest-frame speed change needs no pixel work, so it is plain and shows the same frames."""
    source = Path(j('speed-retime.mp4'))
    counted_source(scripts_dir, source, seconds=5)
    film = FRONT.format(size='320x180', fps=30, captions='none') + '- src_01 0:00.50-0:03.50 fast {x1.5 sound}\n'
    compare_paths(tool, record, 'a 1.5x line', project(j('speed-retime'), source, film), sound=False)


COLOUR_SOURCES = {
    # name: (encoder options after the filters, filters)
    'BT.709 tagged': (('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '8', '-pix_fmt', 'yuv420p', '-colorspace',
                       'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv'),
                      'scale=out_color_matrix=bt709:out_range=tv'),
    'BT.601 tagged': (('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '8', '-pix_fmt', 'yuv420p', '-colorspace',
                       'smpte170m', '-color_primaries', 'smpte170m', '-color_trc', 'smpte170m', '-color_range', 'tv'),
                      'scale=out_color_matrix=smpte170m:out_range=tv'),
    'full range': (('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '8', '-pix_fmt', 'yuvj420p', '-colorspace',
                    'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'pc'),
                   'scale=out_color_matrix=bt709:out_range=pc'),
    'untagged': (('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '8', '-pix_fmt', 'yuv420p'), ''),
    'RGB lossless': (('-c:v', 'ffv1',), ''),
    '10-bit': (('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '8', '-pix_fmt', 'yuv420p10le', '-colorspace',
                'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv'),
               'scale=out_color_matrix=bt709:out_range=tv')}


def check_colour(tool, record, j, scripts_dir, skip):
    """Every colour case reaches the same BT.709 picture on both paths."""
    film = FRONT.format(size='320x180', fps=30, captions='none') + '- src_01 0:00.50-0:01.50 first {sound}\n'
    for name, (encode, filters) in COLOUR_SOURCES.items():
        suffix = 'mkv' if 'ffv1' in encode else 'mp4'
        slug = name.lower().replace(' ', '-').replace('.', '')
        source = Path(j(f'speed-colour-{slug}.{suffix}'))
        counted_source(scripts_dir, source, seconds=2, picture=filters, encode=encode)
        compare_paths(tool, record, f'a {name} source', project(j(f'speed-colour-{slug}'), source, film),
                      list(range(15, 45)), sound=False)
    assemble = load(scripts_dir, 'assemble')
    if not assemble.has_filter('ffmpeg', 'zscale'):
        skip('speed: an HDR source', 'this FFmpeg build lacks zscale', 3)
        return
    source = Path(j('speed-colour-hlg.mp4'))
    counted_source(scripts_dir, source, seconds=2,
                   picture='scale=out_color_matrix=bt2020nc:out_range=tv,'
                           'setparams=colorspace=bt2020nc:color_trc=arib-std-b67:color_primaries=bt2020',
                   encode=('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '8', '-pix_fmt', 'yuv420p10le',
                           '-colorspace', 'bt2020nc', '-color_primaries', 'bt2020', '-color_trc', 'arib-std-b67',
                           '-color_range', 'tv'))
    compare_paths(tool, record, 'an HLG source', project(j('speed-colour-hlg'), source, film), list(range(15, 45)),
                  sound=False)


def check_framing(tool, record, j, scripts_dir):
    """Every fixed framing puts the same part of the source in the same place on both paths."""
    wide = Path(j('speed-framing.mp4'))
    counted_source(scripts_dir, wide, seconds=3)
    tall = Path(j('speed-framing-tall.mp4'))
    counted_source(scripts_dir, tall, seconds=3, picture='crop=202:360:0:0')
    cases = {'a zoomed line': (wide, '320x180', '{zoom 1.3 crop 0.4,0.6 sound}', 6.0),
             'a line cropped to an odd offset': (wide, '320x180', '{crop 0.37,0.5 zoom 1.25 sound}', 6.0),
             'a letterboxed line': (tall, '320x180', '{fit contain sound}', SAME_PICTURE),
             'a tall source cropped to its top': (tall, '320x180', '{crop top sound}', 6.0),
             'a wide source in a tall film': (wide, '180x320', '{crop left sound}', 6.0)}
    for name, (source, size, mods, limit) in cases.items():
        film = FRONT.format(size=size, fps=30, captions='none') + f'- src_01 0:00.50-0:01.50 first {mods}\n'
        slug = name.lower().replace(' ', '-')
        root = project(j(f'speed-{slug}'), source, film)
        code_a, out_a, fast, manifest_a = render(tool, root, '--final')
        code_b, out_b, slow, manifest_b = render(tool, root, '--final', '--every-frame')
        gap = difference(*(frames_of(folder / 'preview.mp4') for folder in (fast, slow))) \
            if (fast / 'preview.mp4').is_file() and (slow / 'preview.mp4').is_file() else float('inf')
        record(f'speed: {name} frames the same on both paths',
               path_of(manifest_a) == 'ffmpeg' and path_of(manifest_b) == 'every-frame' and gap <= limit,
               f'{path_of(manifest_a)} {path_of(manifest_b)} worst frame differs by {gap:.2f} {out_a[-200:]}')


def check_captions(tool, record, j, scripts_dir):
    """Burned captions composite over the plain path's picture exactly where the every-frame path puts them."""
    source = Path(j('speed-captions.mp4'))
    counted_source(scripts_dir, source, seconds=4)
    words = [('Every', .55, .85), ('frame', .9, 1.2), ('counts', 1.25, 1.6), ('when', 2.05, 2.3), ('it', 2.35, 2.5),
             ('burns', 2.55, 3.0)]
    film = FRONT.format(size='320x180', fps=30, captions='burn, srt') + (
        '> src_01 0:00.50-0:01.65 Every frame counts\n> src_01 0:02.00-0:03.05 when it burns\n')
    root = project(j('speed-captions'), source, film, words)
    compared = compare_paths(tool, record, 'a line with burned captions', root, limit=SAME_PICTURE)
    if not compared:
        return
    fast, slow, _ = compared
    boxes = [[row['box'] for row in json.loads((folder / 'caption-burn.json').read_text(encoding='utf-8'))
              ['overlays'][0]['rendered_boxes']] for folder in (fast, slow)]
    record('speed: burned captions land in the same boxes on both paths', boxes[0] == boxes[1] and bool(boxes[0]),
           str(boxes[0][:2]))
    first = (fast / 'captions.srt').read_text(encoding='utf-8')
    record('speed: the caption file is the same on both paths',
           first == (slow / 'captions.srt').read_text(encoding='utf-8') and 'Every' in first)


# ----------------------------------------------------------------------------------------------- phone footage

def check_hdr_note(tool, record, j, scripts_dir, skip):
    """An HDR source renders with a note, and check.py asks for a look at its highlights."""
    if not load(scripts_dir, 'assemble').has_filter('ffmpeg', 'zscale'):
        skip('speed: the HDR note', 'this FFmpeg build lacks zscale', 3)
        return
    source = Path(j('speed-hdr.mp4'))
    counted_source(scripts_dir, source, seconds=2,
                   picture='scale=out_color_matrix=bt2020nc:out_range=tv,'
                           'setparams=colorspace=bt2020nc:color_trc=arib-std-b67:color_primaries=bt2020',
                   encode=('-c:v', 'libx264', '-preset', 'veryfast', '-crf', '12', '-pix_fmt', 'yuv420p10le',
                           '-colorspace', 'bt2020nc', '-color_primaries', 'bt2020', '-color_trc', 'arib-std-b67',
                           '-color_range', 'tv'))
    film = FRONT.format(size='320x180', fps=30, captions='none') + '- src_01 0:00.50-0:01.50 first {sound}\n'
    root = project(j('speed-hdr'), source, film)
    code, output, folder, manifest = render(tool, root)
    record('speed: rendering an HDR source prints a note to compare the highlights',
           code == 1 and 'src_01' in output and 'HDR' in output and 'SDR' in output and 'highlights' in output,
           output[-400:])
    rows = manifest.get('hdr_sources') or []
    record('speed: the manifest records the HDR source', [row.get('alias') for row in rows] == ['src_01'], str(rows))
    code, output = tool('check.py', root)
    look = next((line for line in output.splitlines() if 'HDR' in line), '')
    record('speed: check.py shows a look for an HDR source', look.strip().startswith('LOOK') and 'highlights' in look,
           look or output[-300:])
    clean = Path(j('speed-sdr.mp4'))
    counted_source(scripts_dir, clean, seconds=2)
    root = project(j('speed-sdr'), clean, film)
    code, output, _, manifest = render(tool, root)
    code, checked = tool('check.py', root)
    record('speed: an SDR source says nothing about HDR',
           'HDR' not in output and not manifest.get('hdr_sources')
           and not any('HDR' in line for line in checked.splitlines()), output[-200:])


def check_cover_note(tool, record, j, scripts_dir):
    """Cover framing that discards a third or more of a source says so, naming the line and what keeps more of it."""
    tall = Path(j('speed-cover-tall.mp4'))
    counted_source(scripts_dir, tall, seconds=2, picture='crop=202:360:0:0')
    wide = Path(j('speed-cover-wide.mp4'))
    counted_source(scripts_dir, wide, seconds=2)
    four = Path(j('speed-cover-four.mp4'))
    counted_source(scripts_dir, four, seconds=2, picture='crop=480:360:0:0')

    def checked(name, source, line, size='320x180'):
        film = FRONT.format(size=size, fps=30, captions='none') + line + '\n'
        root = project(j(f'speed-cover-{name}'), source, film)
        code, output = tool('cut.py', 'check', root)
        return root, code, output

    root, code, output = checked('default', tall, '- src_01 0:00.25-0:01.25 phone clip {sound}')
    record('speed: check names the line and the options when cover discards the height',
           code == 0 and 'film.md:10:' in output and 'cover' in output and 'crop auto' in output
           and 'fit contain' in output and '68%' in output, output[-500:])
    code, output, _, manifest = render(tool, root, '--final')
    record('speed: render prints the same note and records it',
           'crop auto' in output and any('crop auto' in note for note in manifest.get('notes', [])), output[-300:])
    for name, source, line, size in (('same', wide, '- src_01 0:00.25-0:01.25 wide {sound}', '320x180'),
                                     ('four', four, '- src_01 0:00.25-0:01.25 four by three {sound}', '320x180'),
                                     ('contain', tall, '- src_01 0:00.25-0:01.25 kept {fit contain sound}', '320x180'),
                                     ('auto', tall, '- src_01 0:00.25-0:01.25 followed {crop auto sound}', '320x180')):
        _, code, output = checked(name, source, line, size)
        record(f'speed: no cover note for {name}', code == 0 and 'crop auto' not in output, output[-300:])
    _, code, output = checked('tall-film', wide, '- src_01 0:00.25-0:01.25 turned {sound}', '180x320')
    record('speed: a wide clip in a tall film gets the note too', 'discards' in output and 'width' in output,
           output[-300:])

    cut = load(scripts_dir, 'cut')
    face = [[.45, .05, .55, .15]]
    inside = [[.45, .45, .55, .55]]
    lost = cut.faces_outside_crop(lambda _: face, [(0.5, np.zeros((4, 4, 3), np.uint8))], (.5, .5), (1.0, .32))
    kept = cut.faces_outside_crop(lambda _: inside, [(0.5, np.zeros((4, 4, 3), np.uint8))], (.5, .5), (1.0, .32))
    record('speed: a face in the discarded part is found and a face in the kept part is not',
           lost == [0.5] and kept == [], f'{lost} {kept}')


def run_speed_cases(tool, record, j, scripts_dir, skip):
    """The plain-cut path, the fixed cost of planning, and the HDR and cover-framing notes."""
    check_eligibility(record, scripts_dir)
    check_shared_encoder_default(record, scripts_dir)
    check_fixed_cost(record, j, scripts_dir)
    check_failures(record, j, scripts_dir)
    check_plain_paths(tool, record, j, scripts_dir)
    check_pause_and_still(tool, record, j, scripts_dir)
    check_hard_sources(tool, record, j, scripts_dir, skip)
    check_retime(tool, record, j, scripts_dir)
    check_colour(tool, record, j, scripts_dir, skip)
    check_framing(tool, record, j, scripts_dir)
    check_captions(tool, record, j, scripts_dir)
    check_hdr_note(tool, record, j, scripts_dir, skip)
    check_cover_note(tool, record, j, scripts_dir)
