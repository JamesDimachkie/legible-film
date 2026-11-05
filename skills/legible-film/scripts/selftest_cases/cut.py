"""Known-answer cases for cut.py: the paper edit compiled, checked, rendered, versioned and compared.

Synthetic sources: a picture with a burned binary frame counter and a colour patch naming the source, tones standing
in for words (each word its own frequency) and a matching words.json. On Windows a further case speaks real sentences
with System.Speech, jitters the transcript's word edges the way a transcriber does, and checks that every cut lands
in a measured pause without clipping a kept word or keeping a removed one; elsewhere it prints a SKIP line.
These prove the compiler's arithmetic and placement on known answers, not that any real cut sounds right.
"""
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

WIDTH, HEIGHT, FPS = 320, 180, 25
RATE = 48000
WORDS = [('alpha', 0.50, 0.90), ('bravo', 1.10, 1.50), ('charlie', 1.80, 2.20), ('delta', 2.50, 2.90),
         ('echo', 3.20, 3.60), ('foxtrot', 3.90, 4.30), ('golf', 6.50, 6.90), ('hotel', 7.20, 7.60),
         ('india', 7.90, 8.30), ('juliet', 8.60, 9.00)]
PATCHES = {'int': (40, 90, 200), 'broll': (220, 120, 30)}


def frequency(index):
    """The tone that stands in for word `index`."""
    return 400 + 150 * index


def ffmpeg(*args, data=None):
    """Run one FFmpeg fixture command and raise on failure."""
    result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', *map(str, args)], input=data,
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-800:])


def counter_frames(count, patch, background=(60, 70, 80)):
    """Raw RGB frames with a nine-bit burned counter and a colour patch that names the source."""
    frames = []
    for number in range(count):
        image = Image.new('RGB', (WIDTH, HEIGHT), background)
        draw = ImageDraw.Draw(image)
        for bit in range(9):
            draw.rectangle((8 + bit * 18, 8, 22 + bit * 18, 22), fill='white' if number & (1 << bit) else 'black')
        draw.rectangle((240, 40, 300, 90), fill=patch)
        frames.append(np.asarray(image).tobytes())
    return b''.join(frames)


def read_counter(frame):
    """The burned counter of one decoded frame."""
    return sum(1 << bit for bit in range(9) if float(frame[15, 15 + bit * 18].mean()) > 128)


def patch_of(frame):
    """Which source a frame shows, from its colour patch."""
    colour = frame[60:70, 265:275].reshape(-1, 3).mean(axis=0)
    return min(PATCHES, key=lambda name: float(np.abs(colour - np.array(PATCHES[name])).sum()))


def write_wav(path, samples, rate=RATE):
    """Mono 16-bit WAV."""
    pcm = np.int16(np.clip(samples, -1, 1) * 32767)
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())


def tone_words(seconds):
    """Low noise with one ramped tone per word."""
    rng = np.random.default_rng(7)
    samples = rng.normal(0, 0.001, int(seconds * RATE))
    for index, (_, start, end) in enumerate(WORDS):
        if end > seconds:
            continue
        a, b = int(start * RATE), int(end * RATE)
        t = np.arange(b - a) / RATE
        ramp = np.minimum(1, np.minimum(t, t[::-1]) / 0.005)
        samples[a:b] += 0.3 * np.sin(2 * np.pi * frequency(index) * t) * ramp
    return samples


def make_source(folder, name, seconds, patch, rate=FPS, audio=True):
    """A counter video (FFV1 in Matroska) with tone words or no sound."""
    count = int(round(seconds * float(Fraction(str(rate)))))
    path = Path(folder) / f'{name}.mkv'
    args = ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(rate), '-i', 'pipe:0']
    if audio:
        wav = Path(folder) / f'{name}.wav'
        write_wav(wav, tone_words(seconds))
        args += ['-i', str(wav), '-map', '0:v', '-map', '1:a', '-c:a', 'pcm_s16le']
    args += ['-c:v', 'ffv1', str(path)]
    ffmpeg(*args, data=counter_frames(count, patch))
    return path


def source_row(alias, role, path, seconds, rate='25/1', audio=True, video=True):
    """One map/sources.json row."""
    return {'alias': alias, 'role': role, 'path': path, 'sha256': hashlib.sha256(alias.encode()).hexdigest(),
            'bytes': 0, 'duration_s': seconds,
            'video': {'width': WIDTH, 'height': HEIGHT, 'fps': rate} if video else None,
            'audio': {'channels': 1, 'rate': RATE} if audio else None,
            'mapped': {'words': audio, 'shots': False, 'audio': False}}


def write_words(root, alias, words):
    """map/<alias>/words.json from (text, start, end[, estimated]) rows."""
    rows = [{'id': f'{alias}-w{number + 1:06d}', 'text': row[0], 'start': row[1], 'end': row[2], 'p': 0.99,
             'speaker': None, 'estimated': bool(row[3]) if len(row) > 3 else False}
            for number, row in enumerate(words)]
    folder = Path(root) / 'map' / alias
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'words.json').write_text(json.dumps({'version': 1, 'source': alias, 'engine': 'fixture',
                                                   'language': 'en', 'draft': False, 'words': rows}),
                                       encoding='utf-8')


def make_project(root, media):
    """A project with int_01 (counter, tone words) and broll_01 (counter, silent)."""
    root = Path(root)
    (root / 'map').mkdir(parents=True, exist_ok=True)
    (root / 'media').mkdir(exist_ok=True)
    for name in ('int_01.mkv', 'broll_01.mkv'):
        shutil.copy2(Path(media) / name, root / 'media' / name)
    sources = [source_row('int_01', 'interview', 'media/int_01.mkv', 12.0),
               source_row('broll_01', 'broll', 'media/broll_01.mkv', 6.0, audio=False)]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': sources}), encoding='utf-8')
    write_words(root, 'int_01', [(text, start, end) for text, start, end in WORDS])
    return root


FILM = """---
title: Cut case
size: 320x180
fps: 25
target: 6
captions: srt, vtt
---
Notes like this line never render.
## One
> int_01 0:00.30-0:04.50 alpha bravo ~~charlie delta~~ echo foxtrot
  ~ title "Hello" 1.0 lower +0.2
## Two
> int_01 0:06.30-0:09.20 golf hotel india juliet
  ~ broll_01 0:01.00-0:02.20 +0.5 the van
"""


def decode_video(path):
    """Every frame of a small video as RGB."""
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=width,height', '-of', 'csv=p=0', str(path)], capture_output=True, text=True)
    width, height = map(int, probe.stdout.strip().split(','))
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                            capture_output=True)
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, height, width, 3)


def decode_audio(path):
    """A file's sound as mono float samples at 48 kHz."""
    result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', str(RATE),
                             '-f', 'f32le', '-'], capture_output=True)
    return np.frombuffer(result.stdout, np.float32)


def tone_track(samples, freq):
    """The amplitude of one frequency over time: (times, amplitudes) every 10 ms over 40 ms windows."""
    size, hop = 2048, 480
    window = np.hanning(size)
    times, values = [], []
    for start in range(0, max(0, len(samples) - size), hop):
        chunk = samples[start:start + size] * window
        t = np.arange(size) / RATE
        value = abs(np.dot(chunk, np.exp(-2j * np.pi * freq * t))) * 2 / window.sum()
        times.append((start + size / 2) / RATE)
        values.append(value)
    return np.array(times), np.array(values)


def word_present(samples, freq, start, end):
    """The smallest amplitude of a tone well inside an edit-time span."""
    times, values = tone_track(samples, freq)
    inside = values[(times >= start + 0.05) & (times <= end - 0.05)]
    return float(inside.min()) if len(inside) else 0.0


def tone_peak(samples, freq, outside=()):
    """The largest amplitude of a tone anywhere (optionally outside some spans)."""
    times, values = tone_track(samples, freq)
    keep = np.ones(len(times), bool)
    for start, end in outside:
        keep &= ~((times >= start - 0.06) & (times <= end + 0.06))
    return float(values[keep].max()) if keep.any() else 0.0


def tree_hashes(folder):
    """{relative path: sha256} for every file under a folder."""
    return {path.relative_to(folder).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(folder).rglob('*')) if path.is_file()}


def check_diff_source_and_settings(tool, record, j):
    """A changed picture source or output setting is a change, in the text and in --json."""
    root = Path(j('diff-settings'))
    film = '---\ntitle: Montage\nsize: {size}\nfps: 30\ncaptions: none\n---\n- {alias} 0:00-0:03 The same view\n'
    for name, size, alias, final in (('v001', '1280x720', 'broll_01', False), ('v002', '1280x720', 'broll_02', False),
                                     ('v003', '720x1280', 'broll_01', True)):
        folder = root / 'cuts' / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'film.md').write_text(film.format(size=size, alias=alias), encoding='utf-8')
        (folder / 'manifest.json').write_text(json.dumps({'version': name, 'duration_s': 3.0, 'final': final}),
                                              encoding='utf-8')
    (root / 'film.md').write_text(film.format(size='1280x720', alias='broll_01'), encoding='utf-8')
    code, text = tool('cut.py', 'diff', root, 'v001', 'v002')
    _, output = tool('cut.py', 'diff', root, 'v001', 'v002', '--json')
    try:
        report = json.loads(output[output.index('{'):])
    except ValueError:
        report = {}
    changed = (report.get('lines') or {}).get('changed') or []
    record('cut: diff reports a line whose picture source changed',
           code == 0 and 'no change' not in text and len(changed) == 1 and 'broll_02' in changed[0].get('to', ''),
           text[-400:])
    code, text = tool('cut.py', 'diff', root, 'v001', 'v003')
    _, output = tool('cut.py', 'diff', root, 'v001', 'v003', '--json')
    try:
        report = json.loads(output[output.index('{'):])
    except ValueError:
        report = {}
    settings = {row['setting']: (row['from'], row['to']) for row in report.get('settings', [])}
    record('cut: diff reports changed output settings in text and --json',
           settings.get('size') == ('1280x720', '720x1280') and settings.get('render') == ('preview', 'final')
           and 'size 1280x720 -> 720x1280' in text and not (report.get('lines') or {}).get('changed'), text[-400:])


def check_diff_modifiers(tool, record, j):
    """Changed sound, dissolve, lead and crop modifiers are visible in both diff formats."""
    root = Path(j('diff-modifiers'))
    header = '---\ntitle: Modifiers\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
    old = ['- broll_01 0:00-0:02 sound View', '- broll_01 0:03-0:05 sound View',
           '- broll_01 0:06-0:08 sound View', '- broll_01 0:09-0:11 sound View']
    new = ['- broll_01 0:00-0:02 sound -6dB View', '- broll_01 0:03-0:05 sound View {dissolve 1.0}',
           '- broll_01 0:06-0:08 sound View {lead 0.5}', '- broll_01 0:09-0:11 sound View {crop 0.25,0.5}']
    for name, lines in (('v001', old), ('v002', new)):
        folder = root / 'cuts' / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'film.md').write_text(header + '\n'.join(lines) + '\n', encoding='utf-8')
    (root / 'film.md').write_text(header + '\n'.join(new) + '\n', encoding='utf-8')
    code, text = tool('cut.py', 'diff', root, 'v001', 'v002')
    _, output = tool('cut.py', 'diff', root, 'v001', 'v002', '--json')
    try:
        changes = json.loads(output[output.index('{'):])['lines']['changed']
    except (ValueError, KeyError):
        changes = []
    labels = ('-6dB', 'dissolve', 'lead', 'crop')
    record('cut: diff identifies changed sound, dissolve, lead and crop modifiers in text and JSON',
           code == 0 and len(changes) == 4 and all(row['from'] != row['to'] for row in changes)
           and all(label in text and label in json.dumps(changes) for label in labels), text[-1200:])
    since, since_text = tool('cut.py', 'diff', root, 'v001')
    _, since_json = tool('cut.py', 'diff', root, 'v001', '--json')
    same, same_text = tool('cut.py', 'diff', root, 'v002')
    try:
        working = json.loads(since_json[since_json.index('{'):])
    except ValueError:
        working = {}
    film = (root / 'film.md').read_text(encoding='utf-8')
    (root / 'film.md').write_text(film.replace('fps: 25', 'fps: nonsense'), encoding='utf-8')
    broken, broken_text = tool('cut.py', 'diff', root, 'v002')
    (root / 'film.md').write_text(film, encoding='utf-8')
    record('cut: diff against a working film.md with an error says so and exits 1, never "no change"',
           broken == 1 and 'error' in broken_text and 'line' in broken_text, broken_text[-400:])
    record('cut: diff with one version shows what the working film.md changed since that render, and nothing when '
           'it matches',
           since == 0 and same == 0 and 'not rendered' in since_text and working.get('to') == 'working'
           and len((working.get('lines') or {}).get('changed') or []) == 4 and 'lines: no change' in same_text,
           since_text[-600:] + same_text[-300:])


def check_unmeasured_cuts(tool, record, j):
    """Cuts placed without a usable audio measurement are listed as tight and unmeasured, never as clean."""
    rate = 16000
    times = np.arange(rate * 2) / rate
    words = [('alpha', .4, .6), ('remove', .9, 1.1), ('omega', 1.4, 1.6)]
    results = {}
    for name, steady in (('steady', True), ('paused', False)):
        root = Path(j(f'unmeasured-{name}'))
        (root / 'map').mkdir(parents=True, exist_ok=True)
        voiced = np.ones(len(times), bool)
        if not steady:
            voiced = np.zeros(len(times), bool)
            for _, start, end in words:
                voiced |= (times >= start) & (times < end)
        write_wav(root / 'voice.wav', np.where(voiced, .15 * np.sin(2 * np.pi * 440 * times), 0), rate)
        row = source_row('vo_01', 'vo', 'voice.wav', 2.0, audio=True, video=False)
        row['audio'] = {'index': 0, 'channels': 1, 'rate': rate}
        (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
        write_words(root, 'vo_01', words)
        (root / 'film.md').write_text('---\nsize: 320x180\nfps: 25\ncaptions: srt\n---\n'
                                      '> vo_01 0:00.20-0:01.80 alpha omega\n', encoding='utf-8')
        _, output = tool('cut.py', 'check', root, '--json')
        try:
            report = json.loads(output[output.index('{'):])
        except ValueError:
            report = {}
        line = next(iter(report.get('lines') or []), {})
        messages = ' '.join(item['message'] for item in report.get('problems', []))
        results[name] = (line.get('unmeasured_cuts'), line.get('tight_cuts'), messages)
    unmeasured, tight, messages = results['steady']
    record('cut: cuts in audio that cannot separate speech from pause are listed as tight and unmeasured',
           bool(unmeasured) and set(unmeasured) <= set(tight or []) and 'not measured' in messages, str(results))
    unmeasured, tight, messages = results['paused']
    record('cut: measured pauses are not called unmeasured', not unmeasured and 'not measured' not in messages,
           str(results))


def check_render_lock(record, j, scripts_dir):
    """Two renders of one project take turns from version number to publication; one that cannot get the lock in
    time stops, names the holder and leaves the running render's staging folder alone."""
    import threading
    spec = importlib.util.spec_from_file_location('cut_render_lock_case', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    root = Path(j('render-lock'))
    cut.project.init(root)
    names, kept, errors = [], [], []

    def staged_render(root, *args):
        """Stands in for the render: allocate, stage, work a moment, publish."""
        name = cut.project.next_version(root)
        staging, work = cut.staging_paths(root, name)
        staging.mkdir()
        (staging / 'film.md').write_text(name, encoding='utf-8')
        time.sleep(.6)
        kept.append((staging / 'film.md').is_file())
        os.replace(staging, root / 'cuts' / name)
        names.append(name)
        return name, [], {}

    cut.render_locked = staged_render

    def render():
        try:
            cut.render_version(root, None, None, None, None, None, '')
        except Exception as error:  # recorded below
            errors.append(repr(error))

    threads = [threading.Thread(target=render) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    record('cut: two renders of one project take different versions and keep each other\'s staging',
           sorted(names) == ['v001', 'v002'] and kept == [True, True] and not errors, f'{names} {kept} {errors}')
    holder = ('import importlib.util,sys,time; s=importlib.util.spec_from_file_location("p",sys.argv[1]); '
              'p=importlib.util.module_from_spec(s); s.loader.exec_module(p)\n'
              'with p.file_lock(sys.argv[2]):\n    time.sleep(4)')
    other = subprocess.Popen([sys.executable, '-c', holder, str(Path(scripts_dir) / 'project.py'),
                              str(root / 'cuts' / 'render')])
    running = root / 'cuts' / '.v003.partial'
    running.mkdir()
    for _ in range(100):
        if (root / 'cuts' / '.render.lock').exists():
            break
        time.sleep(.05)
    cut.RENDER_WAIT = 1
    try:
        cut.render_version(root, None, None, None, None, None, '')
        outcome = 'rendered while another render held the lock'
    except Exception as error:  # the expected RuntimeError, or whatever went wrong instead
        outcome = repr(error)
    other.wait(timeout=30)
    record('cut: a render waits a bounded time for another render, then names it and removes nothing',
           'another render of this project (process' in outcome and running.is_dir(), outcome)


def check_source_on_another_drive(record, j, scripts_dir):
    """A source on another Windows drive than the project has no relative path; edit.json keeps it absolute and the
    renderer still finds it (the quickstart failed in CI with the clone on D: and the project on C:)."""
    def load(name):
        spec = importlib.util.spec_from_file_location(f'lf_drive_{name}', Path(scripts_dir) / f'{name}.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    cut, assemble = load('cut'), load('assemble')
    folder = Path(j('cut-other-drive'))
    (folder / 'cuts' / 'v001').mkdir(parents=True, exist_ok=True)
    source = folder / 'clip.mp4'
    source.write_bytes(b'not media')
    near = cut.relative_source(folder / 'cuts' / 'v001', source)

    def other_drive(path, start=None):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")

    real = cut.os.path.relpath
    cut.os.path.relpath = other_drive
    try:
        far = cut.relative_source(folder / 'cuts' / 'v001', source)
    finally:
        cut.os.path.relpath = real
    found = assemble.source_path(folder / 'cuts' / 'v001', {'src_01': {'file': far}}, 'src_01')
    record('cut: a source on another drive is kept as an absolute path that the renderer resolves',
           near == '../../clip.mp4' and Path(far).is_absolute() and Path(found) == source.resolve(),
           str((near, far, found)))


def check_moving_overlay(tool, record, j):
    """~ over draws a video with transparency over a line, frame for frame at the film's rate; the picture shows
    where it is clear. A different rate, a video without transparency and an image are refused."""
    root, media = Path(j('over-project')), Path(j('over-media'))
    media.mkdir(parents=True, exist_ok=True)
    ffmpeg('-f', 'lavfi', '-i', 'color=c=0x808080:s=320x180:r=25:d=2', '-pix_fmt', 'yuv420p', str(media / 'grey.mp4'))
    frames = media / 'frames'
    frames.mkdir(exist_ok=True)
    for number in range(25):
        image = Image.new('RGBA', (320, 180), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((20, 20, 99, 99), fill=(220, 30, 30, 255) if number % 2 == 0
                                        else (30, 30, 220, 255))
        image.save(frames / f'f{number:03d}.png')
    for name, rate in (('over.mov', '25'), ('over-24.mov', '24')):
        ffmpeg('-framerate', rate, '-i', str(frames / 'f%03d.png'), '-c:v', 'png', '-pix_fmt', 'rgba', str(media / name))
    ffmpeg('-framerate', '25', '-i', str(frames / 'f%03d.png'), '-pix_fmt', 'yuv420p', str(media / 'opaque.mp4'))
    Image.new('RGB', (320, 180), (200, 200, 0)).save(media / 'logo.png')
    badge = Image.new('RGBA', (320, 180), (0, 0, 0, 0))
    ImageDraw.Draw(badge).rectangle((200, 120, 299, 169), fill=(250, 200, 40, 255))
    badge.save(media / 'badge.png')
    small = Image.new('RGBA', (80, 40), (0, 0, 0, 0))
    ImageDraw.Draw(small).rectangle((10, 10, 69, 29), fill=(250, 200, 40, 255))
    small.save(media / 'small.png')
    tool('project.py', 'init', root)
    for name in ('grey.mp4', 'over.mov', 'over-24.mov', 'opaque.mp4'):
        tool('map.py', 'add', root, media / name, '--role', 'broll')
    for name in ('logo.png', 'badge.png', 'small.png'):
        tool('map.py', 'add', root, media / name, '--role', 'still')
    tool('map.py', 'run', root, '--words', 'skip')
    head = '---\ntitle: over\nsize: 320x180\nfps: 25\ncaptions: none\n---\n- broll_01 0:00-0:02 Grey\n'
    (root / 'film.md').write_text(head + '  ~ over broll_02 +0.4\n', encoding='utf-8')
    code, output = tool('cut.py', 'render', root, '--final')
    video = sorted((root / 'cuts').glob('v*/final*.mp4')) or sorted((root / 'cuts').glob('v*/preview.mp4'))
    picture = decode_video(video[-1]) if video else np.zeros((0, 180, 320, 3), np.uint8)
    square = [tuple(int(v) for v in frame[60, 60]) for frame in picture]
    expected = [None] * 10 + [(220, 30, 30) if n % 2 == 0 else (30, 30, 220) for n in range(25)] + [None] * 15
    matches = len(square) == 50 and all(
        (abs(np.array(seen) - (128, 128, 128)).max() <= 6) if want is None else (abs(np.array(seen) - want).max() <= 24)
        for seen, want in zip(square, expected))
    clear = all(abs(picture[n][150, 250].astype(int) - 128).max() <= 6 for n in range(len(picture)))
    record('cut: ~ over draws a transparent video frame for frame from its start, and the picture shows where it is '
           'clear', code in (0, 1) and matches and clear, output[-300:] + str(square[8:14]) + str(square[33:37]))
    declared = json.loads(video[-1].with_name('declared.json').read_text(encoding='utf-8')) if video else {}
    record('cut: the footage under a ~ over graphic is not declared a designed still, so the freeze and blank checks '
           'still see it', bool(video) and not declared.get('designed') and not declared.get('ignore'), str(declared))
    results = {}
    for name, line in (('rate', '  ~ over broll_03\n'), ('image', '  ~ over still_01 1.0\n'),
                       ('opaque', '  ~ over broll_04\n'), ('small', '  ~ over still_03 1.0\n')):
        (root / 'film.md').write_text(head + line, encoding='utf-8')
        results[name] = tool('cut.py', 'check', root)
    record('cut: check refuses a ~ over graphic at another frame rate, an opaque image, and a video without '
           'transparency', results['rate'][0] == 1 and 'runs at 24 fps' in results['rate'][1]
           and results['image'][0] == 1 and 'has no transparency' in results['image'][1]
           and results['opaque'][0] == 1 and 'has no transparency (yuv420p)' in results['opaque'][1],
           ' | '.join(f'{name}: {code} {text[-200:]}' for name, (code, text) in results.items()))
    record('cut: check warns when a ~ over graphic is smaller than the film or another shape, and names the film size',
           "80x40 and the film 320x180; ~ over draws it full frame, scaled to the film's width" in results['small'][1]
           and 'export it at 320x180' in results['small'][1], results['small'][1][-300:])
    # A PNG with transparency: ~ over draws it over the picture; ~ still replaces the picture, its clear areas showing
    # the background colour (they once showed black, whatever the background).
    head = head.replace('captions: none\n', 'captions: none\nbackground: "#204060"\n')
    seen = {}
    for name, line in (('over', '  ~ over still_02 1.0 +0.4\n'), ('still', '  ~ still still_02 1.0 +0.4\n')):
        (root / 'film.md').write_text(head + line, encoding='utf-8')
        checked = tool('cut.py', 'check', root)
        code, output = tool('cut.py', 'render', root, '--final')
        video = sorted((root / 'cuts').glob('v*/preview.mp4'))
        picture = decode_video(video[-1]) if video else np.zeros((0, 180, 320, 3), np.uint8)
        seen[name] = (checked, code, [(tuple(int(v) for v in frame[60, 60]), tuple(int(v) for v in frame[150, 250]))
                                      for frame in picture])

    def near(pixel, want, slack=8):
        return abs(np.array(pixel) - want).max() <= slack

    over, still = seen['over'][2], seen['still'][2]
    record('cut: ~ over draws a transparent PNG over the picture, which shows where the PNG is clear',
           len(over) == 50 and all(near(clear, 128) for clear, _ in over)
           and all(near(mark, (250, 200, 40), 24) for _, mark in over[18:28])
           and all(near(mark, 128) for _, mark in over[:9] + over[36:]), str(seen['over'][:2])[-300:] + str(over[::6]))
    record('cut: a transparent PNG as ~ still warns, and its clear areas show the background colour',
           'has clear areas' in seen['still'][0][1] and len(still) == 50
           and all(near(clear, (32, 64, 96)) and near(mark, (250, 200, 40), 24) for clear, mark in still[12:33]),
           str(seen['still'][:2])[-300:] + str(still[::6]))


def check_overlay_formats(record, j, scripts_dir):
    """Moving overlays from editors and browsers: ProRes 4444 tagged BT.709, and VP9 with alpha (which FFmpeg reports as
    yuv420p plus an alpha_mode tag), decode with their colours and their transparency."""
    spec = importlib.util.spec_from_file_location('cut_case_overlay_formats', Path(scripts_dir) / 'assemble.py')
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    frames = Path(j('over-media', 'frames'))
    files = {'prores': Path(j('over-media', 'over-4444.mov')), 'vp9': Path(j('over-media', 'over-vp9.webm'))}
    ffmpeg('-framerate', '25', '-i', str(frames / 'f%03d.png'), '-vf',
           'scale=out_color_matrix=bt709:out_range=tv,format=yuva444p10le,setparams=colorspace=bt709:range=tv',
           '-c:v', 'prores_ks', '-profile:v', '4444', str(files['prores']))
    ffmpeg('-framerate', '25', '-i', str(frames / 'f%03d.png'), '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p',
           '-b:v', '0', '-crf', '20', str(files['vp9']))
    found = {}
    for name, path in files.items():
        overlay = assemble.MovingOverlay(path, 320, {'w': 1.0}, 25)
        first, second = overlay.frame(0), overlay.frame(1)
        found[name] = (first.getpixel((60, 60)), first.getpixel((250, 150)), second.getpixel((60, 60)))
        overlay.close()
    record('cut: ProRes 4444 and VP9 overlays keep their colours and their transparency',
           all(max(abs(a - b) for a, b in zip(red, (220, 30, 30, 255))) <= 4 and clear[3] == 0
               and max(abs(a - b) for a, b in zip(blue, (30, 30, 220, 255))) <= 4
               for red, clear, blue in found.values()), str(found))


def check_audio_without_duration(record, j, scripts_dir):
    """A source whose sound records no duration at all (a WebM written as a stream) is measured from its packets.
    The stream index was overwritten by the probe's dictionary, so that last fallback crashed a real final render."""
    spec = importlib.util.spec_from_file_location('case_audio_rate', os.path.join(scripts_dir, 'assemble.py'))
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    path = Path(j('audio-without-duration.webm'))
    with open(path, 'wb') as out:
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'sine=f=440:d=2.5', '-c:a', 'libopus', '-f',
                        'webm', 'pipe:1'], stdout=out, check=True)
    try:
        rate, start, end = assemble.audio_rate(shutil.which('ffprobe') or 'ffprobe', str(path))
        ok, detail = rate == 48000 and abs(start) < 0.01 and abs(end - 2.5) < 0.05, str((rate, start, end))
    except Exception as exc:  # the regression raised here
        ok, detail = False, repr(exc)[:200]
    record('cut: a sound stream with no recorded duration is measured from its packets', ok, detail)


def run_cut_cases(tool, record, j, scripts_dir):
    """Cut by deleting words, cutaways, titles, captions, versions, diff, check errors, NTSC rate, real speech."""
    check_audio_without_duration(record, j, scripts_dir)
    check_moving_overlay(tool, record, j)
    check_overlay_formats(record, j, scripts_dir)
    check_source_on_another_drive(record, j, scripts_dir)
    polish_cut_cases(tool, record, j, scripts_dir)
    polish_timing_to_cut_case(tool, record, j, scripts_dir)
    polish_cut_description_case(record, scripts_dir)
    polish_contiguous_audio_case(record, j, scripts_dir)
    check_render_lock(record, j, scripts_dir)
    check_diff_source_and_settings(tool, record, j)
    check_diff_modifiers(tool, record, j)
    check_stale_transcript(tool, record, j)
    check_unmeasured_cuts(tool, record, j)
    check_craft2_units(record, j, scripts_dir)
    check_hold_overlays(record, j, scripts_dir)
    check_craft2_master_warning_boundaries(record, scripts_dir)
    check_craft2_adjacent_and_pin(record, j, scripts_dir)
    check_craft2_frame_identity(tool, record, j)
    media = Path(j('cut-media'))
    media.mkdir(parents=True, exist_ok=True)
    make_source(media, 'int_01', 12.0, PATCHES['int'])
    make_source(media, 'broll_01', 6.0, PATCHES['broll'], audio=False)
    check_sound_past_picture(tool, record, j, media)
    check_caption_ends_with_film(tool, record, j, media)
    root = make_project(j('cut-project'), media)
    (root / 'film.md').write_text(FILM, encoding='utf-8')
    paper_code, _ = tool('grade.py', 'paper', root)
    paper = (root / 'grade' / 'paper.md').read_text(encoding='utf-8') if (root / 'grade' / 'paper.md').exists() else ''
    record('cut: the paper review does not report every cut as unmeasured (it skips audio by design)',
           paper_code in (0, 1) and paper and 'pauses were not measured' not in paper
           and 'cut.py check measures them in the audio' in paper, paper[-400:])
    code, output = tool('cut.py', 'check', root, '--json')
    try:
        checked = json.loads(output[output.index('{'):])
    except ValueError:
        checked = {}
    record('cut: check passes a valid paper edit and estimates its length',
           code == 0 and checked.get('errors') == 0 and abs(checked.get('duration_s', 0) - 5.7) < 0.02,
           output[-400:])
    code, output = tool('cut.py', 'render', root, '--label', 'first')
    version = root / 'cuts' / 'v001'
    record('cut: render writes v001 and points cuts/current at it',
           code in (0, 1) and (version / 'preview.mp4').is_file()
           and (root / 'cuts' / 'current').read_text().strip() == 'v001', output[-600:])
    if not (version / 'preview.mp4').is_file():
        record('cut: remaining render cases', False, 'v001 did not render')
        return
    check_first_render(record, root, version)
    check_versions_and_diff(tool, record, root, version)
    check_errors(tool, record, j, media)
    check_guards(tool, record, j, media, scripts_dir)
    check_ntsc(tool, record, j)
    check_every_line_kind(tool, record, j, media)
    check_proxied_spoken(tool, record, j)
    check_designed_ranges(tool, record, j)
    check_title_bounds(tool, record, j)
    check_late_audio_clock(tool, record, j)
    check_pinned_captions(tool, record, j)
    check_paper_caption_pause(tool, record, j)
    check_measured_pause(tool, record, j)
    check_tight_cut_times(tool, record, j)
    check_world_vfr_edit(tool, record, j)
    check_ordinary_starts_in_cut(tool, record, j)
    check_burn_without_speech(tool, record, j)
    check_order_and_feed(record, scripts_dir)
    check_join_notes(record, scripts_dir)
    check_continuous_picture(record, scripts_dir)
    check_opening_mid_sentence(record, scripts_dir)
    check_no_beat_after(record, scripts_dir)
    check_picture_slivers(tool, record, j)
    check_direction(tool, record, j)
    check_render_job_pid(record, j, scripts_dir)
    check_relaxed_caption_note(record, j, scripts_dir)
    check_source_changed_mid_render(record, j, scripts_dir)
    check_crop_in_braces(record, scripts_dir)
    check_caption_length_by_shape(record, scripts_dir)
    check_edge_under_music(record, scripts_dir)
    check_diff_detail(tool, record, j)
    check_dialogue_master(tool, record, j)
    check_craft2_wide_master(record, j, scripts_dir)
    check_ntsc_audio_tail(tool, record, j)
    check_draft(tool, record, root)
    run_joins_cases(tool, record, j)
    run_lowend_cases(tool, record, j)
    check_real_speech(tool, record, j)


def check_picture_slivers(tool, record, j):
    """A picture range that starts just before a source shot change shows a flash of the other shot; every one of four
    real cuts had one (a stray face, a transition graphic). check names it with the time to move the edge to; a range
    inside one shot, and an edge blended by a dissolve, stay quiet."""
    root = Path(j('cut-slivers')).resolve()
    (root / 'map' / 'broll_01').mkdir(parents=True, exist_ok=True)
    clip = root / 'clip.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=3', '-c:v', 'libx264', '-threads', '1', clip)
    rows = [source_row('broll_01', 'broll', str(clip), 3.0, rate='10/1', audio=False)]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    (root / 'map' / 'broll_01' / 'shots.json').write_text(json.dumps({'version': 1, 'source': 'broll_01', 'shots': [
        {'start': 0.0, 'end': 1.0}, {'start': 1.0, 'end': 3.0}]}), encoding='utf-8')
    head = '---\ntitle: Slivers\nsize: 320x180\nfps: 10\n---\n'
    results = {}
    for name, body in (('edge', '- broll_01 0:00.80-0:02.00 starts 0.2 s before the change\n'),
                       ('clean', '- broll_01 0:01.00-0:02.00 inside one shot\n'),
                       ('between', '- broll_01 0:01.00-0:02.00 one shot\n- broll_01 0:02.50-0:02.80 a glimpse\n'
                                   '- broll_01 0:01.20-0:02.20 the same shot again\n'),
                       ('blended', '- broll_01 0:00.00-0:00.90 first shot\n'
                                   '- broll_01 0:00.80-0:02.00 dissolve 0.3 second shot\n')):
        (root / 'film.md').write_text(head + body, encoding='utf-8')
        results[name] = tool('cut.py', 'check', root)[1]
    record('cut: check names a flash of another shot at a range edge, with the shot change to move it to',
           'another shot shows at 0:00.00' in results['edge'] and 'at or after 0:01.00' in results['edge'],
           results['edge'][-400:])
    record('cut: check names a picture shown for under half a second between others',
           'only 0.30 s of this picture' in results['between'], results['between'][-400:])
    record('cut: a range inside one shot, or an edge a dissolve blends, is not called a flash',
           'flash frame' not in results['clean'] and 'flash frame' not in results['blended'],
           results['clean'][-300:] + results['blended'][-300:])


def check_order_and_feed(record, scripts_dir):
    """An interview line said long before the line it follows is named (an interview cut merged a 1995 phone call and
    the 2006 Nobel morning that way); lines in order, a short step back and b-roll are not. Burned captions on a
    landscape frame for a phone feed are named with their size there; a 9:16 frame, or an audience that names no
    feed, is not."""
    spec = importlib.util.spec_from_file_location('order_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)

    class Sources:
        sources = {'int_01': {'role': 'interview'}, 'broll_01': {'role': 'broll'}}

    def warnings(lines):
        problems = cutter.Problems()
        cutter.out_of_order({'lines': lines}, Sources(), problems)
        return [item['message'] for item in problems.items]

    def spoken(line, start, alias, low, high):
        return {'line': line, 'kind': 'spoken', 'start': start, 'source': alias, 'range': [low, high]}

    backward = warnings([spoken(5, 0, 'int_01', 760, 763), spoken(6, 3, 'int_01', 624, 630)])
    forward = warnings([spoken(5, 0, 'int_01', 400, 404), spoken(6, 4, 'int_01', 529, 532)])
    small = warnings([spoken(5, 0, 'int_01', 400, 404), spoken(6, 4, 'int_01', 390, 395)])
    broll = warnings([spoken(5, 0, 'broll_01', 760, 763), spoken(6, 3, 'broll_01', 624, 630)])
    record('cut: an interview line said long before the line it follows is named; in order, a short step back and '
           'b-roll are not',
           len(backward) == 1 and '2:19.00 before' in backward[0] and not forward and not small and not broll,
           str((backward, forward, small, broll)))

    def feed(size, audience, captions=('burn', 'srt')):
        problems = cutter.Problems()
        cutter.feed_captions({'size': size, 'audience': audience, 'captions': set(captions)}, problems)
        return [item['message'] for item in problems.items]

    wide = feed((1920, 1080), 'people scrolling a phone feed, muted')
    tall = feed((1080, 1920), 'people scrolling a phone feed, muted')
    player = feed((1920, 1080), 'visitors to the museum website')
    unburned = feed((1920, 1080), 'people scrolling a phone feed', ('srt',))
    record('cut: burned captions on a landscape frame for a phone feed are named with their size there',
           len(wide) == 1 and 'about 10 px' in wide[0] and not tall and not player and not unburned,
           str((wide, tall, player, unburned)))


def check_join_notes(record, scripts_dir):
    """A join between passages with no note between its lines is named; a note, a montage section, a line that
    continues the same passage, and a short clip are not."""
    spec = importlib.util.spec_from_file_location('join_notes_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)

    def line(number, start, source, low, high, section='Story'):
        return {'line': number, 'kind': 'spoken', 'start': start, 'source': source, 'range': [low, high],
                'section': section}

    def warnings(lines, notes, duration=40.0):
        problems = cutter.Problems()
        cutter.join_notes({'segments': [1], 'duration': duration, 'lines': lines}, [{'line': n} for n in notes],
                          problems)
        return [item['message'] for item in problems.items]

    jump = [line(10, 0, 'int_01', 100, 104), line(12, 4, 'int_01', 300, 305)]
    missing = warnings(jump, [])
    noted = warnings(jump, [11])
    montage = warnings([line(10, 0, 'int_01', 100, 104, 'Montage'), line(12, 4, 'int_01', 300, 305, 'Montage')], [])
    continuing = warnings([line(10, 0, 'int_01', 100, 104), line(12, 4, 'int_01', 104.2, 108)], [])
    short = warnings(jump, [], duration=15.0)
    record('cut: a join between passages without a note saying what links it is named; a note, a montage, a '
           'continuing passage and a short clip are not',
           len(missing) == 1 and 'from line 10' in missing[0] and not noted and not montage and not continuing
           and not short, str((missing, noted, montage, continuing, short)))


def check_continuous_picture(record, scripts_dir):
    """Two segments that continue one shot with the same framing are one picture: no flash is named for the short
    second piece. A short piece of the same shot reframed is still named."""
    spec = importlib.util.spec_from_file_location('continuous_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    first = {'key': 'int_01', 's0': 10.0, 't0': 0.0, 't1': 2.0, 'speed': 1.0, 'line': 5, 'frame': {'fit': 'cover'}}
    continuing = {'key': 'int_01', 's0': 12.0, 't0': 2.0, 't1': 2.13, 'speed': 1.0, 'line': 6,
                  'frame': {'fit': 'cover'}}
    reframed = dict(continuing, frame={'fit': 'cover', 'zoom': 1.3})
    joined = cutter.continuous_pictures([first, continuing])
    apart = cutter.continuous_pictures([first, reframed])
    record('cut: a shot continued across two segments with the same framing is one picture, not a flash frame',
           len(joined) == 1 and joined[0]['t1'] == 2.13 and len(apart) == 2, str((joined, apart)))


def check_opening_mid_sentence(record, scripts_dir):
    """A film whose first word continues a sentence is named; a sentence start, or a word after a pause, is not."""
    spec = importlib.util.spec_from_file_location('opening_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    source = [{'id': 'int_01-w1', 'text': 'Okay,', 'start': 1.0, 'end': 1.3},
              {'id': 'int_01-w2', 'text': 'boss,', 'start': 1.35, 'end': 1.6},
              {'id': 'int_01-w3', 'text': 'my', 'start': 1.65, 'end': 1.8},
              {'id': 'int_01-w4', 'text': 'failed.', 'start': 1.8, 'end': 2.2},
              {'id': 'int_01-w5', 'text': 'So', 'start': 2.3, 'end': 2.5},
              {'id': 'int_01-w6', 'text': 'and', 'start': 3.5, 'end': 3.7}]

    class Sources:
        def words(self, alias):
            return source

    def warnings(first_id):
        plan = {'lines': [{'line': 7, 'kind': 'spoken', 'start': 0.0, 'source': 'int_01',
                           'words': [{'id': first_id, 'text': 'x', 'start': 0.0, 'end': 0.2}]}]}
        problems = cutter.Problems()
        cutter.opening_mid_sentence(plan, Sources(), problems)
        return [item['message'] for item in problems.items]

    clipped, sentence, paused, first = warnings('int_01-w3'), warnings('int_01-w5'), warnings('int_01-w6'), \
        warnings('int_01-w1')
    record('cut: a film that opens mid-sentence is named; a sentence start, a word after a pause and the first word '
           'are not',
           len(clipped) == 1 and '"boss, my"' in clipped[0] and not sentence and not paused and not first,
           str((clipped, sentence, paused, first)))


def check_no_beat_after(record, scripts_dir):
    """A question answered with almost no pause where the source paused is named; a statement, a real beat, a source
    that answered at once and a change of source are not."""
    spec = importlib.util.spec_from_file_location('beat_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    source = {'src_01': [{'id': 'w1', 'text': 'hand?', 'start': 33.86, 'end': 34.26},
                         {'id': 'w2', 'text': 'Alright,', 'start': 37.54, 'end': 37.82},
                         {'id': 'w3', 'text': 'quick?', 'start': 40.0, 'end': 40.3},
                         {'id': 'w4', 'text': 'Yes.', 'start': 40.5, 'end': 40.7},
                         {'id': 'w5', 'text': 'hand.', 'start': 50.0, 'end': 50.3},
                         {'id': 'w6', 'text': 'So', 'start': 53.0, 'end': 53.2}]}

    class Sources:
        def words(self, alias):
            return source.get(alias, [])

    def warnings(last, first, gap, second_source='src_01'):
        lines = [{'line': 5, 'kind': 'spoken', 'start': 0.0, 'source': 'src_01',
                  'words': [{'id': last, 'text': next(w['text'] for w in source['src_01'] if w['id'] == last),
                             'start': 9.5, 'end': 9.9}]},
                 {'line': 8, 'kind': 'spoken', 'start': 10.1, 'source': second_source,
                  'words': [{'id': first, 'text': 'x', 'start': 9.9 + gap, 'end': 10.5}]}]
        problems = cutter.Problems()
        cutter.no_beat_after({'lines': lines}, Sources(), problems)
        return [item['message'] for item in problems.items]

    clipped = warnings('w1', 'w2', 0.33)
    statement = warnings('w5', 'w6', 0.3)
    breathing = warnings('w1', 'w2', 0.8)
    immediate = warnings('w3', 'w4', 0.2)
    elsewhere = warnings('w1', 'w2', 0.33, 'int_01')
    record('cut: a question answered with almost no pause where the source paused is named; a statement, a real '
           'beat, an immediate answer in the source and a change of source are not',
           len(clipped) == 1 and '0.33 s after "hand?"' in clipped[0] and '3.3 s' in clipped[0]
           and not statement and not breathing and not immediate and not elsewhere,
           str((clipped, statement, breathing, immediate, elsewhere)))


def check_burn_without_speech(tool, record, j):
    """A montage asking for burned captions renders: with no spoken words there is nothing to burn, and the
    render said so only by failing at its end."""
    root = Path(j('cut-burn-montage')).resolve()
    (root / 'map').mkdir(parents=True, exist_ok=True)
    clip = root / 'clip.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=2', '-c:v', 'libx264', '-threads', '1', clip)
    rows = [source_row('broll_01', 'broll', str(clip), 2.0, rate='10/1', audio=False)]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    (root / 'film.md').write_text('---\ntitle: Montage\nsize: 320x180\nfps: 10\ncaptions: burn, srt\n---\n'
                                  '- broll_01 0:00.00-0:01.00 fixture\n', encoding='utf-8')
    check_code, check_output = tool('cut.py', 'check', root)
    code, output = tool('cut.py', 'render', root)
    record('cut: burned captions on a film with no speech render without a burn, and say why',
           check_code in (0, 1) and 'nothing to caption' in check_output and code in (0, 1)
           and (root / 'cuts' / 'v001' / 'preview.mp4').exists() and 'nothing was burned' in output,
           check_output[-200:] + output[-300:])
    # A film that asks for no captions has nothing to report about them: the render is clean (exit 0, no note).
    quiet = Path(j('cut-captions-none')).resolve()
    (quiet / 'map').mkdir(parents=True, exist_ok=True)
    (quiet / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    (quiet / 'film.md').write_text('---\ntitle: Montage\nsize: 320x180\nfps: 10\ncaptions: none\n---\n'
                                   '- broll_01 0:00.00-0:01.00 fixture\n', encoding='utf-8')
    none_code, none_output = tool('cut.py', 'render', quiet)
    record('cut: a film with captions: none and no speech renders clean, without a caption note',
           none_code == 0 and (quiet / 'cuts' / 'v001' / 'preview.mp4').exists() and 'caption' not in none_output,
           f'exit {none_code}: ' + none_output[-300:])


def check_stale_transcript(tool, record, j):
    """A spoken line on a source whose transcript was made from other media is an error until it is transcribed
    again or confirmed; a transcript made from the registered file passes."""
    root = Path(j('cut-stale-words')).resolve()
    (root / 'map').mkdir(parents=True, exist_ok=True)
    row = source_row('int_01', 'interview', 'media/int_01.mkv', 12.0)
    row['audio']['index'] = 1
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [(text, start, end) for text, start, end in WORDS])
    (root / 'film.md').write_text('---\ntitle: Stale\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
                                  '> int_01 0:00.30-0:04.50 alpha bravo charlie delta echo foxtrot\n', encoding='utf-8')
    path = root / 'map' / 'int_01' / 'words.json'
    results = []
    for digest in ('b' * 64, row['sha256']):
        data = json.loads(path.read_text(encoding='utf-8'))
        data['media'] = {'sha256': digest, 'bytes': 0, 'audio_stream': 1}
        path.write_text(json.dumps(data), encoding='utf-8')
        results.append(tool('cut.py', 'check', root, '--no-audio'))
    (stale_code, stale_out), (fresh_code, fresh_out) = results
    record('cut: check refuses a spoken line whose transcript was made from other media, naming both remedies',
           stale_code != 0 and 'other media' in stale_out and 'confirm-words' in stale_out
           and '--retranscribe int_01' in stale_out and 'confirm-words' not in fresh_out,
           stale_out[-400:] + fresh_out[-200:])
    # The file itself replaced after mapping: the map's record still matches the transcript, the file does not.
    (root / 'media').mkdir(exist_ok=True)
    (root / 'media' / 'int_01.mkv').write_bytes(b'x' * 64)
    row['bytes'] = 100
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    moved_code, moved_out = tool('cut.py', 'check', root, '--no-audio')
    draft_code, draft_out = tool('cut.py', 'draft', root, '--select', 'int_01:"alpha bravo"', '--force')
    record('cut: a source file replaced after mapping makes its words stale in check and draft, before any re-map',
           moved_code != 0 and 'changed since it was mapped' in moved_out and 'map.py run' in moved_out
           and draft_code != 0 and 'changed since it was mapped' in draft_out, moved_out[-400:] + draft_out[-300:])
    # The same replaced file used only for its picture or as music, with no spoken line to notice it.
    film = root / 'film.md'
    film.write_text('---\ntitle: Stale\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
                    '- int_01 0:00.50-0:02.00 The room\n- music int_01 0:00-0:03 -18dB\n- pause 1.0\n',
                    encoding='utf-8')
    picture_code, picture_out = tool('cut.py', 'check', root, '--no-audio')
    record('cut: a picture or music line on a source replaced after mapping is an error too, not only spoken lines',
           picture_code != 0 and picture_out.count('changed since it was mapped') >= 2 and 'map.py run' in picture_out,
           picture_out[-500:])


def check_edge_under_music(record, scripts_dir):
    """A written line edge clear of words stays near where it was written when music fills the gap to the next word
    (a cold run's edge moved up to 7.3 s into unrelated shots); quiet within reach is still used."""
    spec = importlib.util.spec_from_file_location('edge_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)

    class Loud:
        """Music everywhere: nothing is quiet."""
        reliable = True

        def quiet_at(self, moment):
            return False

        def quiet_runs(self, low, high):
            return []

        def dip_near(self, moment, low, high):
            return moment

    class QuietAt(Loud):
        """One quiet stretch 0.2 s after the written edge."""

        def quiet_runs(self, low, high):
            return [(max(low, 10.6), min(high, 10.9))] if low < 10.9 and high > 10.6 else []

    words = [{'text': 'kept', 'start': 9.0, 'end': 10.0}, {'text': 'later', 'start': 17.4, 'end': 17.8}]
    loud = cutter.line_edge(words, 0, 10.4, 'after', Loud(), 0.2)
    near = cutter.line_edge(words, 0, 10.4, 'after', QuietAt(), 0.2)
    record('cut: a line edge under music stays where it was written (tight), or moves only to quiet within reach',
           loud == (10.4, True, False) and abs(near[0] - 10.6) < 1e-6 and near[1:] == (False, True),
           f'loud={loud}; near={near}')


def check_caption_length_by_shape(record, scripts_dir):
    """Caption lines are shorter in a tall frame, so burned text keeps its size."""
    spec = importlib.util.spec_from_file_location('caption_length_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    lengths = {shape: cutter.caption_line_length(shape) for shape in ((1920, 1080), (1080, 1080), (1080, 1350),
                                                                     (1080, 1920), (540, 960))}
    record('cut: caption lines are 42 characters in landscape and square, fewer in tall frames',
           lengths[(1920, 1080)] == 42 and lengths[(1080, 1080)] == 42 and 30 <= lengths[(1080, 1350)] < 42
           and 22 <= lengths[(1080, 1920)] <= 28 and lengths[(540, 960)] == lengths[(1080, 1920)], str(lengths))


def check_crop_in_braces(record, scripts_dir):
    """A spoken line takes a crop position in braces, as paper-edit.md documents; a cold agent found it refused."""
    spec = importlib.util.spec_from_file_location('crop_brace_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    results = {}
    for text in ('crop 0.66,0.5', 'crop 0.66, 0.5', 'zoom 1.2, crop 0.3,0.5, dissolve 0.25'):
        problems, mods = cutter.Problems(), {}
        cutter.parse_brace_mods(text, cutter.ALLOWED['spoken'], 'spoken', 1, problems, mods)
        results[text] = (mods.get('crop'), problems.count('error'), mods.get('zoom'), mods.get('join'))
    record('cut: a crop position in braces on a spoken line is read as one value',
           results['crop 0.66,0.5'][:2] == ((0.66, 0.5), 0) and results['crop 0.66, 0.5'][:2] == ((0.66, 0.5), 0)
           and results['zoom 1.2, crop 0.3,0.5, dissolve 0.25'][0] == (0.3, 0.5)
           and results['zoom 1.2, crop 0.3,0.5, dissolve 0.25'][1] == 0, str(results))


def check_source_changed_mid_render(record, j, scripts_dir):
    """A source file that changes while a version renders (same size, new bytes) publishes nothing: the version would
    otherwise record the identity of the file that was checked, not the one that was read."""
    spec = importlib.util.spec_from_file_location('render_change_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    root = Path(j('cut-changed-mid-render')).resolve()
    (root / 'map').mkdir(parents=True, exist_ok=True)
    clip = root / 'clip.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=3', '-c:v', 'libx264', '-threads', '1', clip)
    rows = [source_row('broll_01', 'broll', str(clip), 3.0, rate='10/1', audio=False)]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    (root / 'film.md').write_text('---\ntitle: Changed\nsize: 160x90\nfps: 10\ncaptions: none\n---\n'
                                  '- broll_01 0:00.00-0:02.00 The pattern\n', encoding='utf-8')
    original = cutter.run_assemble

    def touched(*args, **kwargs):
        stat = clip.stat()
        os.utime(clip, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5 * 10 ** 9))
        return original(*args, **kwargs)

    cutter.run_assemble = touched
    try:
        cutter.run_render(cutter.argument_parser().parse_args(['render', str(root)]))
        outcome = 'rendered'
    except RuntimeError as error:
        outcome = str(error)
    record('cut: a source that changes while a version renders publishes nothing and says so',
           'changed while this version rendered' in outcome and not (root / 'cuts' / 'v001').exists(), outcome[:300])


def check_relaxed_caption_note(record, j, scripts_dir):
    """Captions that fit the normal reading limits say nothing about relaxed limits; captions that need them say so
    once."""
    spec = importlib.util.spec_from_file_location('relaxed_note_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    captions = cutter.load_sibling('captions')
    folder = Path(j('cut-relaxed-note'))
    folder.mkdir(parents=True, exist_ok=True)
    calm = [{'id': f'w{n}', 'text': text, 'start': n * 0.5, 'end': n * 0.5 + 0.4}
            for n, text in enumerate('we built the tool we needed in six weeks'.split())]
    rushed = [{'id': f'r{n}', 'text': text, 'start': n * 0.09, 'end': n * 0.09 + 0.08}
              for n, text in enumerate(('extraordinarily complicated '
                                        'circumstances necessitated unprecedented collaboration ' * 3).split())]
    calm_notes, rushed_notes = [], []
    cutter.build_group(captions, calm, folder / 'calm', calm_notes)
    cutter.build_group(captions, rushed, folder / 'rushed', rushed_notes)
    cutter.build_group(captions, rushed, folder / 'rushed-again', rushed_notes)
    relaxed = 'some captions needed relaxed limits (30 characters/s, 0.4 s minimum); review them'
    record('cut: a caption note about relaxed limits appears only when they were used, and once',
           relaxed not in calm_notes and rushed_notes.count(relaxed) <= 1, str((calm_notes, rushed_notes)))


def check_render_job_pid(record, j, scripts_dir):
    """A render's running entry names its process, and a dead one is dropped from the status line."""
    spec = importlib.util.spec_from_file_location('render_job_case', os.path.join(scripts_dir, 'cut.py'))
    cutter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cutter)
    root = cutter.project.init(Path(j('cut-render-pid')), 'Render job')
    cutter.Job(root, 'v001').update(.4)
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    entry = (status.get('running') or [{}])[0]
    dead = dict(entry, pid=2147483646)
    record('cut: a render job records its process, so a killed render is not shown as running',
           entry.get('pid') == os.getpid() and cutter.project.live_running([entry]) == [entry]
           and cutter.project.live_running([dead]) == [], str(status.get('running')))


def check_direction(tool, record, j):
    """A cut longer than a short clip must say who it is for, what they leave with and its story; check prints the
    story, and grade.py paper puts the direction in front of the reviewer."""
    root = Path(j('cut-direction')).resolve()
    (root / 'map').mkdir(parents=True, exist_ok=True)
    clip = root / 'clip.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=30', '-c:v', 'libx264', '-threads', '1', clip)
    rows = [source_row('broll_01', 'broll', str(clip), 30.0, rate='10/1', audio=False)]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    head = '---\ntitle: Direction\nsize: 160x90\nfps: 10\ncaptions: none\n'
    body = '---\n## Opening\n- broll_01 0:00.00-0:12.00 one\n## Ending\n- broll_01 0:12.00-0:25.00 two\n'
    (root / 'film.md').write_text(head + body, encoding='utf-8')
    code, without = tool('cut.py', 'check', root, '--no-audio')
    direction = ('audience: people who have never seen it\ntakeaway: They see the pattern change.\n'
                 'story: A test pattern starts plain and ends transformed.\n')
    (root / 'film.md').write_text(head + direction + body, encoding='utf-8')
    code_with, stated = tool('cut.py', 'check', root, '--no-audio')
    paper_code, _ = tool('grade.py', 'paper', root)
    paper = (root / 'grade' / 'paper.md').read_text(encoding='utf-8') if (root / 'grade' / 'paper.md').exists() else ''
    record('cut: a cut without a stated audience, takeaway and story is warned about; a stated story is printed',
           code == 0 and 'does not state its audience, takeaway, story' in without
           and code_with == 0 and 'does not state' not in stated
           and 'story: A test pattern starts plain and ends transformed.' in stated,
           without[-300:] + stated[-300:])
    blank = 'audience: "  "\ntakeaway: \'  \'\nstory: "   "\n'
    (root / 'film.md').write_text(head + blank + body, encoding='utf-8')
    blank_code, blank_out = tool('cut.py', 'check', root, '--no-audio')
    colon = ('audience: people on a train: phones, no sound\ntakeaway: They say "that is the one".\n'
             'story: Plain: then "transformed".\n')
    (root / 'film.md').write_text(head + colon + body, encoding='utf-8')
    colon_code, colon_out = tool('cut.py', 'check', root, '--no-audio')
    record('cut: a direction of blank space is still missing; colons and quotation marks in one are kept',
           blank_code == 0 and 'does not state its audience, takeaway, story' in blank_out
           and colon_code == 0 and 'does not state' not in colon_out
           and 'story: Plain: then "transformed".' in colon_out, blank_out[-200:] + colon_out[-200:])
    (root / 'film.md').write_text(head + direction + '---\n', encoding='utf-8')
    draft_code, draft_out = tool('cut.py', 'draft', root, '--select', 'broll_01:0-12', '--select', 'broll_01:12-25')
    drafted = (root / 'film.md').read_text(encoding='utf-8')
    record('cut: draft fills a film.md that has only its direction, and keeps the direction',
           draft_code == 0 and 'story: A test pattern starts plain and ends transformed.' in drafted
           and 'audience: people who have never seen it' in drafted and '- broll_01 0:00' in drafted,
           draft_out[-200:] + drafted[:300])
    record('cut: the paper review puts the stated direction in front of the reviewer',
           paper_code in (0, 1) and 'Story: A test pattern starts plain and ends transformed.' in paper
           and 'Takeaway: They see the pattern change.' in paper, paper[:400])


def check_ordinary_starts_in_cut(tool, record, j):
    """Preview and final accept common zero-in-point files and show the linear first frames."""
    media = Path(j('cut-ordinary-media')).resolve()
    media.mkdir(parents=True, exist_ok=True)
    original = media / 'original.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=3', '-f', 'lavfi', '-i',
           'sine=frequency=440:sample_rate=48000:duration=3', '-c:v', 'libx264', '-threads', '1',
           '-g', '20', '-c:a', 'aac', original)
    trimmed = media / 'trimmed.mp4'
    ffmpeg('-ss', '1.2', '-i', original, '-c', 'copy', trimmed)
    late = media / 'late.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=10:d=2', '-f', 'lavfi', '-i',
           'sine=frequency=440:sample_rate=48000:duration=2', '-filter_complex', '[0:v]setpts=PTS+0.1/TB[v]',
           '-map', '[v]', '-map', '1:a', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac',
           '-fps_mode', 'passthrough', late)
    transport = media / 'origin.ts'
    ffmpeg('-i', original, '-c', 'copy', '-output_ts_offset', '10', '-f', 'mpegts', transport)
    sources = (trimmed, late, transport)
    references = []
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('ordinary_start_assembler', scripts / 'assemble.py')
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)
    for source in sources:
        stream, _, width, height = assembler.probe_source('ffprobe', str(source))
        vf, _, _ = assembler.colour_filter(stream, int(stream['width']), int(stream['height']))
        vf += f',scale={width}:{height}:flags=lanczos,setsar=1'
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-vf', vf, '-frames:v', '1',
                                  '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True)
        references.append(np.frombuffer(decoded.stdout, np.uint8).reshape(180, 320, 3))
    for mode in ('preview', 'final'):
        root = Path(j('cut-ordinary-' + mode)).resolve()
        (root / 'map').mkdir(parents=True, exist_ok=True)
        rows = [source_row(f'broll_{index + 1:02d}', 'broll', str(source), 1.5, rate='10/1', audio=False)
                for index, source in enumerate(sources)]
        (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
        film = ('---\ntitle: Ordinary starts\nsize: 320x180\nfps: 10\n---\n' + ''.join(
            f'- broll_{index + 1:02d} 0:00.00-0:00.50 fixture\n' for index in range(len(sources))))
        (root / 'film.md').write_text(film, encoding='utf-8')
        options = ['--final'] if mode == 'final' else []
        code, output = tool('cut.py', 'render', root, *options)
        picture = root / 'cuts' / 'v001' / 'preview.mp4'
        if code in (0, 1) and picture.exists():
            frames = decode_video(picture)
            errors = [float(np.mean(np.abs(frames[index * 5].astype(int) - reference.astype(int))))
                      for index, reference in enumerate(references)] if len(frames) >= 15 else []
        else:
            errors = []
        record('cut: ' + mode + ' accepts trim, delayed video and transport stream at zero',
               len(errors) == 3 and max(errors) < 12, f'first-frame mean RGB errors={errors}; {output[-300:]}')


def check_sound_past_picture(tool, record, j, media):
    """check warns, before rendering, when the film is a fifth of a frame past a whole frame and its last sound runs
    to the end (the picture can round down and cut that sound's fade-out short); a whole-frame film, or one whose
    last line fades out, is not warned."""
    found = {}
    for name, end, mods in (('short', '0:03.008', ''), ('whole', '0:03.00', ''),
                            ('faded', '0:03.008', ' fade out 0.5')):
        root = make_project(j('cut-sound-past-' + name), media)
        (root / 'film.md').write_text('---\ntitle: Sound past picture\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
                                      f'- broll_01 0:00.50-0:01.50 The van\n'
                                      f'- int_01 0:01.00-{end} sound{mods} The room\n', encoding='utf-8')
        code, output = tool('cut.py', 'check', root, '--json')
        try:
            problems = json.loads(output[output.index('{'):]).get('problems', [])
        except ValueError:
            problems = []
        found[name] = [item for item in problems if 'of a frame past' in item.get('message', '')]
    short = found['short'][0] if found['short'] else {}
    record('cut: check warns when the last sound runs past the frame the picture can end on, with the remedy',
           short.get('severity') == 'warning' and short.get('line') == 8 and '75 frames at 25 fps' in short['message']
           and 'cut the last 8 ms' in short['message'] and '0.008 s shorter' in short.get('suggestion', '')
           and 'whole number of frames' in short.get('suggestion', ''), str(found))
    record('cut: a whole-frame film, or one that fades out with its picture, gets no such warning',
           not found['whole'] and not found['faded'], str(found))


def check_caption_ends_with_film(tool, record, j, media):
    """A caption's minimum reading time must not carry it past the film's last frame: a sidecar is read beside the
    film, and a cue past its end is a caption no viewer sees the end of."""
    root = make_project(j('cut-caption-end'), media)
    (root / 'film.md').write_text('---\ntitle: Short word\nsize: 320x180\nfps: 25\ncaptions: srt\n---\n'
                                  '> int_01 0:00.45-0:00.95 alpha\n', encoding='utf-8')
    code, output = tool('cut.py', 'render', root)
    version = root / 'cuts' / 'v001'
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8')) if (
        version / 'manifest.json').is_file() else {}
    cues = (json.loads((version / 'captions.json').read_text(encoding='utf-8')) if (
        version / 'captions.json').is_file() else {}).get('cues', [])
    length = manifest.get('duration_s', 0)
    srt = (version / 'captions.srt').read_text(encoding='utf-8') if (version / 'captions.srt').is_file() else ''
    stamp = srt.split('-->')[1].split()[0] if '-->' in srt else ''
    written = sum(float(part) * unit for part, unit in zip(stamp.replace(',', '.').split(':'), (3600, 60, 1))) \
        if stamp else float('inf')
    record('cut: a short last word keeps its caption inside the film, in the sidecar and its JSON',
           code in (0, 1) and length > 0 and len(cues) == 1 and float(cues[0]['end']) <= length + 1e-6
           and written <= length + 1e-6 and 'alpha' in srt,
           f'film {length}; cue {cues}; srt end {stamp}; {output[-200:]}')


def check_proxied_spoken(tool, record, j):
    """A preview proxy for a spoken source must keep the original source's sound."""
    root = Path(j('cut-proxy-spoken'))
    media = root / 'media'
    media.mkdir(parents=True, exist_ok=True)
    source = media / 'int_01.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=960x540:r=25:d=2', '-f', 'lavfi',
           '-i', 'sine=frequency=440:sample_rate=48000:duration=2', '-c:v', 'libx264', '-threads', '2',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', source)
    (root / 'map').mkdir(exist_ok=True)
    row = source_row('int_01', 'interview', 'media/int_01.mp4', 2.0)
    row['video'] = {'width': 960, 'height': 540, 'fps': '25/1'}
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .3, .65), ('bravo', .8, 1.2)])
    (root / 'film.md').write_text('---\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
                                   '> int_01 0:00.20-0:01.40 alpha bravo\n', encoding='utf-8')
    code, output = tool('cut.py', 'render', root)
    preview = root / 'cuts' / 'v001' / 'preview.mp4'
    manifest_path = preview.parent / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    pcm = decode_audio(preview) if preview.exists() else np.array([])
    record('cut: a proxied spoken source renders with its original sound',
           code in (0, 1) and manifest.get('proxies') == ['int_01'] and pcm.size > 0
           and float(np.max(np.abs(pcm))) > .01, output[-500:])
    proxies = list((root / 'cuts' / '.cache').glob('*.mp4'))
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_assemble_proxy', scripts / 'assemble.py')
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    error = ''
    if proxies:
        try:
            assemble.audio_rate('ffprobe', str(proxies[0]))
        except ValueError as exc:
            error = str(exc)
    record('cut: a missing audio stream error names its file and stream',
           bool(proxies) and proxies[0].name in error and 'a:0' in error, error)


def check_designed_ranges(tool, record, j):
    """Fades, pauses, holds and cards are marked on the film clock."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_cut_ranges', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    plan = {'duration': 8.0, 'fades': {'in': 1.0, 'out': .5},
            'lines': [{'kind': 'pause', 'start': 2.0, 'end': 3.0, 'hold': True},
                      {'kind': 'title', 'start': 4.0, 'end': 5.0, 'card': True}]}
    if not hasattr(cut, 'declared_ranges'):
        record('cut: designed fades, holds and title cards are declared', False,
               'the edit currently writes holds=[] and has no other designed ranges')
        return
    ranges = cut.declared_ranges(plan)
    pairs = {(row['kind'], row['start'], row['end']) for row in ranges}
    expected = {('fade', 0.0, 1.0), ('fade', 7.5, 8.0), ('hold', 2.0, 3.0), ('title_card', 4.0, 5.0)}
    record('cut: designed fades, holds and title cards are declared', pairs == expected, str(ranges))


def check_title_bounds(tool, record, j):
    """Overlong title ink cannot leave the safe box; missing requested fonts are reported."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_cut_title', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    settings = {'font': 'sans'}
    path = Path(j('title-too-wide.png'))
    error = ''
    try:
        cut.make_title(path, (320, 180), ['W' * 90], 'center', settings)
    except ValueError as exc:
        error = str(exc)
    record('cut: an unbreakable title that exceeds the safe box is reported',
           bool(error) and ('fit' in error or 'safe' in error), error or 'title was painted without an error')
    result = None
    if hasattr(cut, 'title_font_info'):
        result = cut.title_font_info({'font': str(Path(j('missing-face.ttf')))})
    record('cut: a missing requested title font names the actual fallback',
           isinstance(result, dict) and result.get('fallback') and result.get('actual'), str(result))


def check_late_audio_clock(tool, record, j):
    """A stream starting late keeps its leading silence on the source clock."""
    root = Path(j('late-audio-clock'))
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'late.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'color=s=160x90:r=25:d=2', '-itsoffset', '0.8', '-f', 'lavfi', '-i',
           r'aevalsrc=if(lt(t\,0.25)\,0\,0.6*sin(2*PI*440*t)):s=8000:d=1.2',
           '-map', '0:v', '-map', '1:a', '-c:v', 'ffv1', '-c:a', 'pcm_s16le', source)
    (root / 'map').mkdir(exist_ok=True)
    row = source_row('int_01', 'interview', 'late.mkv', 2.0)
    row['audio'] = {'index': 1, 'channels': 1, 'rate': 8000}
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_cut_late', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    envelope = cut.Envelopes(cut.SourceMap(root), 'ffmpeg').get('int_01', .2, 1.6)
    active = np.flatnonzero(envelope.db > -35) if envelope is not None else []
    onset = float(envelope.times[active[0]]) if len(active) else None
    record('cut: a late audio stream is measured on the source presentation clock',
           onset is not None and abs(onset - 1.05) < .03, f'measured onset {onset}; expected 1.05')


def check_pinned_captions(tool, record, j):
    """A caption boundary anchored before a word stays attached or reports a removed word."""
    root = Path(j('pinned-caption'))
    (root / 'map').mkdir(parents=True, exist_ok=True)
    source = root / 'source.wav'
    write_wav(source, np.zeros(48000))
    row = source_row('int_01', 'interview', 'source.wav', 1.0, video=False)
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .1, .3), ('bravo', .35, .55), ('charlie', .6, .8)])
    film = ('---\nsize: 320x180\nfps: 25\ncaptions: srt\n---\n'
            '> int_01 0:00-0:01 alpha bravo charlie\n'
            '- caption break before int_01-w000003\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_cut_pins', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    try:
        _, _, _, plan, problems, _ = cut.analyse(root, measure=False)
        groups = cut.caption_groups(plan['words'], {'int_01-w000003'})
        ok = problems.count('error') == 0 and [[w['text'] for w in group] for group in groups] == \
            [['alpha', 'bravo'], ['charlie']]
    except (TypeError, KeyError, ValueError) as exc:
        ok = False
        groups = str(exc)
    record('cut: a pinned caption boundary starts at its anchored word', ok, str(groups))
    version = root / 'version'
    work = root / 'caption-work'
    version.mkdir(exist_ok=True)
    work.mkdir(exist_ok=True)
    notes = []
    try:
        cut.build_captions(plan, version, work, notes)
        cues = json.loads((version / 'captions.json').read_text(encoding='utf-8'))['cues']
        valid = len(cues) == 2 and cues[0]['end'] <= cues[1]['start'] \
            and cues[1]['words'][0]['id'] == 'int_01-w000003'
    except (OSError, ValueError, KeyError) as exc:
        valid = False
        cues = str(exc)
    record('cut: pinned caption sidecars retain the boundary without overlapping timings', valid, str(cues))
    (root / 'film.md').write_text(film.replace('alpha bravo charlie', 'alpha bravo'), encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--no-audio')
    record('cut: a pinned boundary reports when its anchored word was cut',
           code == 1 and 'int_01-w000003' in output and 'caption' in output.lower(), output[-500:])


def check_first_render(record, root, version):
    """Picture, sound, cutaway, title, captions and status for v001."""
    lines = json.loads((version / 'lines.json').read_text(encoding='utf-8'))['lines']
    spoken = [line for line in lines if line['kind'] == 'spoken']
    first = spoken[0]
    record('cut: the cut falls in the pauses around the removed words (lines.json runs)',
           len(first['runs']) == 2 and 1.50 < first['runs'][0]['out'] < 1.80 and 2.90 < first['runs'][1]['in'] < 3.20
           and len(first['jump_cuts']) == 1, json.dumps(first['runs']))
    frames = decode_video(version / 'preview.mp4')
    counters = [read_counter(frame) for frame in frames]
    patches = [patch_of(frame) for frame in frames]
    cut_at = first['runs'][1]['at']
    first_in, second_in = first['runs'][0]['in'], first['runs'][1]['in']
    expected = []
    for number in range(len(frames)):
        t = number / FPS
        if t < cut_at:
            expected.append(round((first_in + t) * FPS))
        elif t < first['end']:
            expected.append(round((second_in + t - cut_at) * FPS))
        else:
            expected.append(round((spoken[1]['runs'][0]['in'] + t - spoken[1]['start']) * FPS))
    talking = [number for number, patch in enumerate(patches) if patch == 'int']
    worst = max(abs(counters[number] - expected[number]) for number in talking)
    removed = [counters[number] for number in talking if 1.70 * FPS < counters[number] < 3.00 * FPS]
    record('cut: the frame counter shows the kept spans, a jump at the cut and no removed frames',
           worst <= 1 and not removed and len(frames) == math.ceil(5.7 * FPS - 1e-9),
           f'worst {worst}; removed {removed[:5]}; frames {len(frames)}')
    audio = decode_audio(version / 'preview.mp4')
    edit_spans = {}
    for line in spoken:
        for word in line['words']:
            edit_spans[word['text']] = (word['start'], word['end'])
    kept = {name: word_present(audio, frequency(index), *edit_spans[name])
            for index, (name, _, _) in enumerate(WORDS) if name in edit_spans}
    gone = {name: tone_peak(audio, frequency(index)) for index, (name, _, _) in enumerate(WORDS)
            if name in ('charlie', 'delta')}
    strays = {name: tone_peak(audio, frequency(index), [edit_spans[name]])
              for index, (name, _, _) in enumerate(WORDS) if name in edit_spans}
    record('cut: the removed words\' tones are absent and every kept word sounds where lines.json says',
           len(kept) == 8 and min(kept.values()) > 0.15 and max(gone.values()) < 0.02 and max(strays.values()) < 0.03,
           f'kept {kept}; removed {gone}; strays {strays}')
    cutaway = next(line for line in lines if line['kind'] == 'cutaway')
    under = [patches[number] for number in range(len(frames))
             if cutaway['start'] + 0.05 < number / FPS < cutaway['end'] - 0.05]
    beside = [patches[number] for number in range(len(frames))
              if spoken[1]['start'] + 0.05 < number / FPS < cutaway['start'] - 0.05]
    hotel = word_present(audio, frequency(7), *edit_spans['hotel'])
    record('cut: a cutaway covers the picture while the line\'s sound continues under it',
           cutaway.get('over') == spoken[1]['line'] and cutaway.get('source') == 'broll_01'
           and abs(cutaway['start'] - (spoken[1]['start'] + 0.5)) < 1e-3 and under and set(under) == {'broll'}
           and beside and set(beside) == {'int'} and hotel > 0.15
           and cutaway['start'] < edit_spans['hotel'][0] and edit_spans['hotel'][1] < cutaway['end'],
           f'cutaway {cutaway}; under {set(under)}; hotel {hotel:.3f}')
    title = next(line for line in lines if line['kind'] == 'title')

    def bright(frame):
        return int((frame[110:176].min(axis=2) > 200).sum())

    inside = [bright(frames[number]) for number in range(len(frames)) if title['start'] + 0.3 < number / FPS <
              title['end'] - 0.3]
    outside = [bright(frames[number]) for number in range(len(frames)) if number / FPS < title['start'] - 0.05
               or number / FPS > title['end'] + 0.05]
    record('cut: the title overlay is on its frames and nowhere else',
           abs(title['start'] - 0.2) < 1e-3 and abs(title['end'] - 1.2) < 1e-3 and min(inside) > 30
           and max(outside) < 3, f'title {title}; inside {min(inside) if inside else None}; '
           f'outside {max(outside) if outside else None}')
    captions = json.loads((version / 'captions.json').read_text(encoding='utf-8'))
    caption_words = [word for cue in captions['cues'] for word in cue['words']]
    line_words = [word for line in spoken for word in line['words']]
    ids = [word.get('id') for word in caption_words]
    expected_ids = [f'int_01-w{number:06d}' for number in (1, 2, 5, 6, 7, 8, 9, 10)]
    times_match = all(abs(a['start'] - b['start']) < 0.002 and abs(a['end'] - b['end']) < 0.002
                      for a, b in zip(caption_words, line_words))
    alpha_ok = abs(line_words[0]['start'] - (0.50 - first_in)) < 0.002
    srt = (version / 'captions.srt').read_bytes()
    record('cut: captions carry the kept words\' IDs and edit times (srt and vtt alongside, LF endings)',
           ids == expected_ids and times_match and alpha_ok and b'\r\n' not in srt and srt.strip()
           and (version / 'captions.vtt').read_text(encoding='utf-8').startswith('WEBVTT'),
           f'ids {ids}; times {times_match}; alpha {line_words[0]}')
    strip_record = json.loads((version / 'strip' / 'strip.json').read_text(encoding='utf-8')) if (
        version / 'strip' / 'strip.json').exists() else {}
    record('cut: the strip made at render time shows the version\'s timed words',
           strip_record.get('words') == len(caption_words) and len(caption_words) > 0, str(strip_record))
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
    files_ok = all(hashlib.sha256((version / name).read_bytes()).hexdigest() == digest
                   for name, digest in manifest['files'].items())
    streams = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,duration', '-of', 'csv=p=0',
                              str(version / 'preview.mp4')], capture_output=True, text=True).stdout.split()
    lengths = {row.split(',')[0]: float(row.split(',')[1]) for row in streams if row.count(',') == 1}
    whole = math.ceil(5.7 * FPS - 1e-9) / FPS
    record('cut: status marks cut done and check next; the manifest hashes every file; sound and picture end together',
           status['stages']['plan'] == 'done' and status['stages']['cut'] == 'done'
           and status['stages']['check'] == 'now' and status['current'] == 'v001'
           and not status.get('running') and manifest['version'] == 'v001' and manifest['parent'] is None
           and manifest['label'] == 'first' and files_ok and 'preview.mp4' in manifest['files']
           and abs(manifest['duration_s'] - whole) < 1e-3 and abs(lengths.get('audio', 0) - whole) < 1 / FPS
           and abs(lengths.get('video', 0) - whole) < 1 / FPS, json.dumps(status)[:300] + str(lengths))
    mapped = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources']
    used = manifest.get('sources') or {}
    record('cut: the manifest records each source it was cut from as mapped then (bytes, SHA-256, transcript hash)',
           bool(used) and all(row['alias'] not in used or (used[row['alias']]['sha256'] == row.get('sha256')
                                                           and used[row['alias']]['bytes'] == row.get('bytes'))
                              for row in mapped)
           and any(entry.get('words_sha256') for entry in used.values()), json.dumps(used)[:400])


def check_versions_and_diff(tool, record, root, version):
    """A second render makes v002 and leaves v001 byte-identical; diff reports the change."""
    before = tree_hashes(version)
    stale = root / 'cuts' / '.v001.work'
    stale.mkdir()
    (stale / 'left-by-a-stopped-render.wav').write_bytes(b'0' * 1024)
    film = (root / 'film.md').read_text(encoding='utf-8')
    film = film.replace('golf hotel india juliet', 'golf hotel juliet').replace('"Hello"', '"Hello there"')
    (root / 'film.md').write_text(film, encoding='utf-8')
    notes = {'version': 1, 'notes': [{'id': 'n1', 'version': 'v001', 't': 1.0, 'text': 'too abrupt', 'status': 'open',
                                      'resolved_in': None, 'reply': None},
                                     {'id': 'n2', 'version': 'v001', 't': 2.0, 'text': 'louder', 'status': 'done',
                                      'resolved_in': 'v001', 'reply': 'Raised.'}]}
    notes_text = json.dumps(notes)
    (root / 'notes.json').write_text(notes_text, encoding='utf-8')
    code, output = tool('cut.py', 'render', root, '--label', 'tighter', '--resolves', 'n1,n2,n9')
    second = root / 'cuts' / 'v002'
    manifest = json.loads((second / 'manifest.json').read_text(encoding='utf-8')) if second.is_dir() else {}
    leftovers = [path.name for path in (root / 'cuts').iterdir() if path.name.startswith('.v')]
    record('cut: rendering again makes v002, leaves v001 byte-identical and clears stale staging folders',
           code in (0, 1) and second.is_dir() and tree_hashes(version) == before and manifest.get('parent') == 'v001'
           and not leftovers and manifest.get('notes_resolved') == ['n1', 'n2', 'n9']
           and (root / 'cuts' / 'current').read_text().strip() == 'v002', output[-400:])
    commands = [line.strip() for line in output.splitlines() if 'screen.py' in line and ' resolve ' in line]
    record('cut: render --resolves prints the screen.py resolve command for a note still open, and closes nothing',
           len(commands) == 1 and ' n1 --in v002 --reply ' in commands[0] and f'"{root.resolve()}"' in commands[0]
           and 'only recorded' in output and 'n9, which is not in notes.json' in output
           and (root / 'notes.json').read_text(encoding='utf-8') == notes_text, output[-600:])
    _, helped = tool('cut.py', 'render', '--help')
    helped = ' '.join(helped.split())
    record('cut: render help says --resolves only records notes and names screen.py resolve',
           'only recorded in manifest.json' in helped and 'screen.py resolve PROJECT NOTE' in helped, helped)
    code, output = tool('cut.py', 'diff', root, 'v001', 'v002', '--json')
    try:
        report = json.loads(output[output.index('{'):])
    except ValueError:
        report = {}
    cut_ids = [word['id'] for word in report.get('words', {}).get('cut', [])]
    changed = report.get('lines', {}).get('changed', [])
    record('cut: diff reports the changed lines, the word cut, the shorter duration and the new captions',
           code == 0 and cut_ids == ['int_01-w000009'] and len(changed) == 2
           and report['duration']['change_s'] < -0.3 and report['captions']['changed']
           and not report['words']['restored'] and 'india' in report.get('summary', ''), output[-600:])


def check_errors(tool, record, j, media):
    """check reports each kind of error with its line number."""
    root = make_project(j('cut-errors'), media)
    (root / 'film.md').write_text('\n'.join([
        '---', 'size: 320x180', 'fps: 25', '---',
        '> int_01 garbage words here',
        '- broll_09 0:01.00-0:02.00 an alias that does not exist',
        '> int_01 0:06.30-0:19.00 golf hotel',
        '> int_01 0:00.30-0:04.50 alpha bravo charly',
        '- bullet notes like this one are fine', '']), encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--json')
    try:
        report = json.loads(output[output.index('{'):])
    except ValueError:
        report = {'problems': []}
    errors = {item['line']: item for item in report['problems'] if item['severity'] == 'error'}
    record('cut: check reports bad grammar, an unknown alias, an out-of-range time and an unmatched word by line',
           code == 1 and set(errors) == {5, 6, 7, 8} and 'range' in errors[5]['message']
           and 'broll_09' in errors[6]['message'] and 'broll_01' in errors[6]['suggestion']
           and '0:12.00' in errors[7]['message'] and 'charly' in errors[8]['message']
           and 'charlie' in errors[8]['suggestion'], json.dumps(errors)[:900])
    code, output = tool('cut.py', 'render', root)
    json_code, json_output = tool('cut.py', 'render', root, '--json')
    try:
        blocked = json.loads(json_output[json_output.index('{'):])
    except ValueError:
        blocked = {}
    record('cut: render refuses a paper edit with errors with exit 2 (it could not run), and --json says it was blocked',
           code == 2 and not (root / 'cuts' / 'v001').exists() and 'not rendered' in output
           and json_code == 2 and blocked.get('status') == 'blocked' and blocked.get('version') is None
           and any(item['severity'] == 'error' for item in blocked.get('problems', [])), output[-300:])


def check_guards(tool, record, j, media, scripts_dir):
    """A malformed range cannot produce a huge file: implausible lines are refused, and a runaway writer is stopped."""
    root = make_project(j('cut-guards'), media)
    sources = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))
    for source in sources['sources']:
        source['duration_s'] = 0
    (root / 'map' / 'sources.json').write_text(json.dumps(sources), encoding='utf-8')
    film = '\n'.join(['---', 'size: 320x180', 'fps: 25', 'target: 6', '---',
                      '> int_01 0:00.30-0:04.50 alpha bravo charlie delta echo foxtrot',
                      '- broll_01 0:00.00-5:00:00.00 five hours typed for five seconds',
                      '- broll_01 0:01.00-0:02.00 x0.001 a thousand times slower',
                      '- pause 50000', ''])
    (root / 'film.md').write_text(film, encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--json')
    try:
        report = json.loads(output[output.index('{'):])
    except ValueError:
        report = {'problems': []}
    errors = sorted({item['line'] for item in report['problems'] if item['severity'] == 'error'})
    render_code, render_output = tool('cut.py', 'render', root)
    sizes = [path.stat().st_size for path in root.rglob('*') if path.is_file()]
    (root / 'film.md').write_text(film.replace('target: 6\n', ''), encoding='utf-8')
    _, untargeted = tool('cut.py', 'check', root, '--json')
    try:
        loose = sorted({item['line'] for item in json.loads(untargeted[untargeted.index('{'):])['problems']
                        if item['severity'] == 'error'})
    except ValueError:
        loose = None
    record('cut: implausibly long lines (4x the target, or 3 hours) are refused before anything renders',
           code == 1 and errors == [7, 8, 9] and render_code == 2 and not (root / 'cuts' / 'v001').exists()
           and max(sizes) < 5 * 1024 ** 2 and sum(sizes) < 20 * 1024 ** 2 and loose == [6, 8],
           f'errors {errors}; loose {loose}; largest {max(sizes)}; {render_output[-300:]}')
    spec = importlib.util.spec_from_file_location('lf_cut_guard', os.path.join(scripts_dir, 'cut.py'))
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    folder = Path(j('cut-runaway'))
    folder.mkdir(exist_ok=True)
    endless = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-re', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
               '-f', 'wav', str(folder / 'endless.wav')]
    began = time.time()
    try:
        cut.watch(endless, folder, 120, 1024 ** 2, lambda elapsed: None)
        stopped = ''
    except RuntimeError as error:
        stopped = str(error)
    written = (folder / 'endless.wav').stat().st_size if (folder / 'endless.wav').exists() else 0
    record('cut: the render watchdog stops a process that writes without end',
           'wrote' in stopped and written < 4 * 1024 ** 2 and time.time() - began < 60,
           f'{stopped!r}; {written} bytes; {time.time() - began:.1f} s')
    shutil.rmtree(folder, ignore_errors=True)


def check_ntsc(tool, record, j):
    """fps 30000/1001 renders at exactly that rate."""
    folder = Path(j('cut-ntsc'))
    (folder / 'media').mkdir(parents=True, exist_ok=True)
    make_source(folder / 'media', 'int_01', 6.0, PATCHES['int'], rate='30000/1001')
    (folder / 'map').mkdir(exist_ok=True)
    sources = [source_row('int_01', 'interview', 'media/int_01.mkv', 6.0, rate='30000/1001')]
    (folder / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': sources}), encoding='utf-8')
    write_words(folder, 'int_01', [row for row in WORDS if row[2] < 6.0])
    (folder / 'film.md').write_text('---\nsize: 320x180\nfps: 30000/1001\ncaptions: none\n---\n'
                                    '> int_01 0:00.30-0:04.50 alpha bravo charlie delta echo foxtrot\n',
                                    encoding='utf-8')
    code, output = tool('cut.py', 'render', folder, '--final')
    preview = folder / 'cuts' / 'v001' / 'preview.mp4'
    rates = ''
    if preview.is_file():
        rates = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=r_frame_rate,avg_frame_rate', '-of', 'csv=p=0', str(preview)],
                               capture_output=True, text=True).stdout.strip()
    manifest = json.loads((folder / 'cuts' / 'v001' / 'manifest.json').read_text()) if preview.is_file() else {}
    record('cut: fps 30000/1001 renders at exactly 30000/1001', rates == '30000/1001,30000/1001'
           and manifest.get('fps') == '30000/1001' and (folder / 'cuts' / 'v001' / 'stems').is_dir(),
           f'{rates}; {output[-300:]}')


SINK = """---
title: Every line kind
size: 640x360
fps: 25
captions: burn, srt, plate
music: -20dB, fade 0.5
max_pause: 0.5
background: #101418
---
- music music_01 0:00-0:30
## A
> int_01 0:00.30-0:04.50 alpha bravo ~~charlie delta~~ echo foxtrot {fade in 0.5, zoom 1.2}
  ~ still still_01 1.0 +0.5
- broll_02 0:00.50-0:02.00 x1.5 dissolve 0.3 a large source, sped up
- still still_01 1.5 fit contain dip 0.3
- pause 0.5
- pause 0.4 hold
- title "Chapter two" "the end" 1.5 center card
## B
> int_01 0:03.10-0:07.00 echo foxtrot golf
  ~ int_01 0:10.00-0:11.00 sound -12dB
  ~ title "Lower third" "role" 1.2 lower +0.3
> vo_01 0:00.30-0:04.50 alpha bravo charlie delta echo foxtrot
  ~ broll_01 0:00.00-0:02.00
- broll_01 0:03.00-0:04.00 crop auto {fade out 0.5}
"""


def check_every_line_kind(tool, record, j, media):
    """Music, fades, zoom, a still cutaway, a sped 1080p source (via a proxy), dissolve, dip, both pauses, a title
    card, a lower third, nat sound, an audio-only voice-over, max_pause and burned captions in one render."""
    root = make_project(j('cut-every'), media)
    folder = root / 'media'
    write_wav(folder / 'vo_01.wav', tone_words(5.0))
    write_wav(folder / 'music_01.wav', 0.2 * np.sin(2 * np.pi * 220 * np.arange(30 * RATE) / RATE))
    still = Image.new('RGB', (400, 300), (30, 160, 90))
    ImageDraw.Draw(still).ellipse((100, 50, 300, 250), fill=(240, 240, 60))
    still.save(folder / 'still_01.png')
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=1920x1080:r=25:d=2.5', '-c:v', 'libx264', '-crf', '18', '-pix_fmt',
           'yuv420p', folder / 'broll_02.mp4')
    sources = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources']
    sources += [source_row('vo_01', 'vo', 'media/vo_01.wav', 5.0, video=False),
                source_row('music_01', 'music', 'media/music_01.wav', 30.0, video=False),
                dict(source_row('still_01', 'still', 'media/still_01.png', 0.04, audio=False),
                     video={'width': 400, 'height': 300, 'fps': '25/1'}),
                dict(source_row('broll_02', 'broll', 'media/broll_02.mp4', 2.5, audio=False),
                     video={'width': 1920, 'height': 1080, 'fps': '25/1'})]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': sources}), encoding='utf-8')
    write_words(root, 'vo_01', [row for row in WORDS if row[2] < 5.0])
    (root / 'film.md').write_text(SINK, encoding='utf-8')
    code, output = tool('cut.py', 'render', root)
    version = root / 'cuts' / 'v001'
    if not (version / 'preview.mp4').is_file():
        record('cut: every line kind renders in one film', False, output[-800:])
        return
    lines = json.loads((version / 'lines.json').read_text(encoding='utf-8'))['lines']
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
    kinds = sorted({line['kind'] for line in lines})
    pauses = [line for line in lines if line['kind'] == 'pause']
    shortened = next(line for line in lines if line['kind'] == 'spoken' and line['range'][0] == 3.1)
    frames = decode_video(version / 'preview.mp4')

    def luma(number):
        return float(frames[min(number, len(frames) - 1)].mean())

    voice = next(line for line in lines if line['kind'] == 'spoken' and line['source'] == 'vo_01')
    bare = frames[int((voice['end'] - 0.3) * FPS)][100:200, 100:200].reshape(-1, 3).mean(axis=0)
    captions = json.loads((version / 'captions.json').read_text(encoding='utf-8'))['cues']
    mixed = [cue['text'] for cue in captions if len({str(word.get('id')).split('-w')[0] for word in cue['words']}) > 1]
    music = word_present(decode_audio(version / 'preview.mp4'), 220, 3.0, 6.0)
    record('cut: every line kind renders in one film (fades, still, proxy, joins, pauses, card, voice-over, music)',
           code in (0, 1) and kinds == ['cutaway', 'music', 'pause', 'picture', 'spoken', 'still', 'title']
           and len(pauses) == 2 and pauses[1]['hold'] and manifest['proxies'] == ['broll_02']
           and len(shortened['runs']) == 2 and shortened['end'] - shortened['start'] < 2.6
           and luma(0) < 0.5 * luma(FPS) and luma(len(frames) - 1) < 0.5 * luma(len(frames) - 20)
           and abs(bare - np.array([16, 20, 24])).max() < 12 and captions and not mixed and 0.01 < music < 0.04,
           f'kinds {kinds}; proxies {manifest.get("proxies")}; shortened {shortened.get("runs")}; '
           f'luma {luma(0):.0f}/{luma(FPS):.0f}; bare {bare}; mixed {mixed}; music {music:.3f}; {output[-300:]}')


def check_draft(tool, record, root):
    """draft finds phrases in the transcript and writes a paper edit that checks clean."""
    folder = root.parent / 'cut-draft'
    shutil.copytree(root / 'map', folder / 'map')
    shutil.copytree(root / 'media', folder / 'media')
    code, output = tool('cut.py', 'draft', folder, '--select', 'int_01:"bravo charlie"', '--select',
                        'int_01:"hotel india juliet"')
    film = (folder / 'film.md').read_text(encoding='utf-8') if (folder / 'film.md').is_file() else ''
    check_code, check_output = tool('cut.py', 'check', folder)
    record('cut: draft writes spoken lines for the selected phrases and the result checks clean',
           code == 0 and '> int_01 0:01.' in film and 'bravo charlie' in film and 'hotel india juliet' in film
           and check_code == 0, output[-200:] + check_output[-300:])
    record('cut: draft defaults to sidecars without burning',
           'captions: srt, vtt' in film and 'captions: burn' not in film, film[:200])
    code, output = tool('cut.py', 'draft', folder, '--select', 'int_01:bravo', '--captions', 'burn,srt', '--force')
    film = (folder / 'film.md').read_text(encoding='utf-8')
    record('cut: draft can request a burned caption', code == 0 and 'captions: burn, srt' in film, output[-200:])


def check_measured_pause(tool, record, j):
    """Transcript edges can hide a long pause that is plainly present in the sound."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_pause_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    rate = 16000
    times = np.arange(rate * 3) / rate
    samples = np.zeros(len(times))
    voiced = ((times >= .1) & (times < .8)) | ((times >= 2.3) & (times < 2.9))
    samples[voiced] = 15000 * np.sin(2 * np.pi * 440 * times[voiced])
    envelope = cut.Envelope(samples.astype('int16'), rate, 0)
    words = [{'text': 'One', 'start': .1, 'end': 1.3, 'index': 0},
             {'text': 'Two', 'start': 1.8, 'end': 2.9, 'index': 1}]
    entry = {'start': 0, 'end': 3, 'line': 1}
    problems = cut.Problems()
    runs = cut.spoken_runs(entry, words, [0, 1], envelope, {'max_pause': .8, 'pad': .2}, problems)
    quiet = envelope.quiet_runs(.1, 2.9)[0]
    kept = (runs[0]['out'] - quiet[0] + quiet[1] - runs[1]['in']) if len(runs) == 2 else 99
    record('cut: max_pause measures actual silence despite inaccurate transcript edges',
           len(runs) == 2 and abs(kept - .8) < .02, f'runs={runs}, kept silence={kept}')
    problems = cut.Problems()
    cut.spoken_runs(entry, words, [0, 1], None, {'max_pause': .8, 'pad': .2}, problems)
    record('cut: unmeasured max_pause is disclosed',
           any('could not be measured' in row['message'] for row in problems.items), str(problems.items))


def check_paper_caption_pause(tool, record, j):
    """Paper-edit groups must not fill the pause after being built separately."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_caption_pause_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    folder = Path(j('paper-caption-pause'))
    work = folder / 'work'
    work.mkdir(parents=True, exist_ok=True)
    words = [{'id': 'int_01-w000001', 'text': 'Yes', 'start': .1, 'end': .2},
             {'id': 'int_01-w000002', 'text': 'No', 'start': 1.0, 'end': 1.1}]
    notes = []
    cut.build_captions({'words': words}, folder, work, notes)
    cues = json.loads((folder / 'captions.json').read_text(encoding='utf-8'))['cues']
    record('cut: caption sidecars leave the middle of a long pause blank',
           len(cues) == 2 and cues[0]['end'] <= .4 and cues[1]['start'] >= .8
           and any('long pause' in note for note in notes), str(cues))


def check_tight_cut_times(tool, record, j):
    """The first and last frame are not cuts; real tight joins have film-clock times."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_tight_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    rows = [{'line': 9, 'kind': 'spoken', 'tight_cuts': [0, 1.5, 3]},
            {'line': 10, 'kind': 'spoken', 'tight_cuts': [1.5]}]
    problems = cut.Problems()
    cut.report_tight_cuts(rows, 3, problems)
    message = problems.items[0]['message'] if problems.items else ''
    record('cut: only actual tight cuts are reported with their time',
           rows[0]['tight_cuts'] == [1.5] and len(problems.items) == 1
           and '0:01.50' in message and '0:00.00' not in message, message)


def check_diff_detail(tool, record, j):
    """Long lines, word provenance and an unchanged-duration shift remain visible."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_diff_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    text = 'word ' * 20 + 'the end'
    entry = {'kind': 'spoken', 'alias': 'int_01', 'start': 0, 'end': 3, 'text': text}
    description = cut.describe(entry)
    old = {'cues': [{'start': 5, 'end': 7, 'text': 'unchanged'}]}
    new = {'cues': [{'start': 3, 'end': 5, 'text': 'unchanged'}]}
    comparison = cut.compare_captions(old, new)
    lines = {'lines': [{'line': 8, 'source': 'int_01', 'words': [{'id': 'w1', 'text': 'word'}]}]}
    grouped = cut.word_changes_by_line(lines, [{'id': 'w1', 'text': 'word'}], 'cut')
    record('cut: diff keeps full lines and groups word cuts by source line',
           text in description and grouped[0]['line'] == 8 and grouped[0]['cut'][0]['id'] == 'w1', description)
    record('cut: unchanged-duration captions shifted by earlier cuts are moved',
           comparison['moved'] == 1 and comparison['retimed'] == 0, str(comparison))


def check_dialogue_master(tool, record, j):
    """Measure the mixed delivery and its re-encode, including a forced loudnorm fallback."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_master_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    folder = Path(j('dialogue-master'))
    folder.mkdir(parents=True, exist_ok=True)
    t = np.arange(4 * RATE) / RATE
    dialogue = folder / 'dialogue.wav'
    music = folder / 'music.wav'
    write_wav(dialogue, .75 * np.sin(2 * np.pi * 440 * t))
    write_wav(music, .75 * np.sin(2 * np.pi * 440 * t))
    mixed = folder / 'mixed.wav'
    cut.mix_for_master('ffmpeg', [dialogue, music], 4, {}, mixed)
    peak = float(np.abs(decode_audio(mixed)).max())
    record('cut: dialogue master sums float stems before limiting', peak > 1.45, f'mixed peak={peak}')
    normalized = folder / 'normalized.wav'
    first, second = cut.loudnorm_passes('ffmpeg', mixed, normalized, -16)
    picture = folder / 'picture.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=4', '-c:v', 'libx264', '-threads', '1',
           '-pix_fmt', 'yuv420p', picture)
    delivered = folder / 'delivery.mp4'
    cut.mux_master('ffmpeg', picture, normalized, 4, 40, delivered)
    report = cut.measure_master('ffmpeg', 'ffprobe', delivered, 'youtube', -16, 'synthetic', first, second)
    record('cut: both loudnorm passes and the actual mode are reported',
           'input_i' in report['first_pass'] and 'output_i' in report['second_pass']
           and report['actual_mode'] in ('linear', 'dynamic'), str(report['actual_mode']))
    record('cut: mastered AAC and a simulated re-encode are metered at 48 kHz',
           int(report['delivery_stream']['sample_rate']) == 48000
           and report['delivered_aac'].get('integrated_lufs') is not None
           and report['delivered_aac'].get('true_peak_dbtp') is not None
           and report['simulated_aac_reencode'].get('true_peak_dbtp') is not None, str(report))
    transient = .004 * np.sin(2 * np.pi * 440 * t)
    transient[2 * RATE:2 * RATE + 48] += np.hanning(48) * .95
    source = folder / 'transient.wav'
    write_wav(source, transient)
    measured, actual = cut.loudnorm_passes('ffmpeg', source, folder / 'transient-master.wav', -14)
    forced = {'actual_mode': actual.get('normalization_type'), 'target_lufs': -14,
              'requested_true_peak_dbtp': -1.5, 'delivered_aac': {'integrated_lufs': -14, 'true_peak_dbtp': -2},
              'simulated_aac_reencode': {'true_peak_dbtp': -2}}
    notes = cut.master_warnings(forced)
    record('cut: a forced dynamic loudnorm fallback is visible',
           actual.get('normalization_type') == 'dynamic' and any('dynamic' in note for note in notes),
           f'mode={actual.get("normalization_type")}; notes={notes}; input={measured.get("input_tp")}')


def check_ntsc_audio_tail(tool, record, j):
    """The video frame cap must not stop AAC before the planned sample boundary."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_ntsc_audio_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    folder = Path(j('ntsc-audio-tail'))
    folder.mkdir(parents=True, exist_ok=True)
    rate = Fraction(30000, 1001)
    frames = 713
    length = float(Fraction(frames, 1) / rate)
    count = round(length * RATE)
    audio = folder / 'sound.wav'
    t = np.arange(count) / RATE
    write_wav(audio, .2 * np.sin(2 * np.pi * 440 * t))
    picture = folder / 'picture.mp4'
    ffmpeg('-f', 'lavfi', '-i', f'color=black:s=160x90:r=30000/1001:d={length:.9f}',
           '-frames:v', frames, '-c:v', 'libx264', '-threads', 1, '-pix_fmt', 'yuv420p', picture)
    delivery = folder / 'delivery.mp4'
    cut.mux_master('ffmpeg', picture, audio, length, frames, delivery)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                            'stream=codec_type,nb_frames,duration_ts,time_base', '-of', 'json', str(delivery)],
                           capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)['streams']
    video = next(row for row in streams if row['codec_type'] == 'video')
    sound = next(row for row in streams if row['codec_type'] == 'audio')
    measured = float(Fraction(sound['duration_ts']) * Fraction(sound['time_base'])) * RATE
    record('cut: NTSC mux preserves all picture frames and the audio tail',
           int(video['nb_frames']) == frames and abs(measured - count) <= RATE / 1000,
           f'frames={video["nb_frames"]}, audio samples={measured:.0f}, expected={count}')


# ----------------------------------------------------------------------------------------------- real speech

SPEECH = ('First, we tried everything we could find. That did not work at all. Then we asked the crew what they '
          'needed. They had a lot of ideas. So we built the tool ourselves.')
SPEECH_SCRIPT = r"""
param([string]$Text, [string]$Out, [string]$Json)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = 0
$events = New-Object System.Collections.ArrayList
$null = Register-ObjectEvent -InputObject $s -EventName SpeakProgress -SourceIdentifier lfsp -Action {
  [void]$events.Add(@{t=$EventArgs.AudioPosition.TotalSeconds; c=$EventArgs.CharacterPosition;
                      n=$EventArgs.CharacterCount}) }
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000,
  [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($Out, $fmt)
$s.Speak($Text)
$s.SetOutputToNull()
Start-Sleep -Milliseconds 400
Unregister-Event lfsp
$events | ConvertTo-Json | Set-Content -Encoding UTF8 $Json
"""


def speak(folder):
    """Synthesize SPEECH with System.Speech: (samples at 16 kHz, word starts as [(text, start)]) or None."""
    shell = shutil.which('powershell') or shutil.which('powershell.exe')
    if os.name != 'nt' or not shell:
        return None
    script = Path(folder) / 'speak.ps1'
    script.write_text(SPEECH_SCRIPT, encoding='utf-8')
    wav, events = Path(folder) / 'speech.wav', Path(folder) / 'speech-words.json'
    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Text', SPEECH,
                             '-Out', str(wav), '-Json', str(events)], capture_output=True, text=True, timeout=120)
    if result.returncode or not wav.is_file() or not events.is_file():
        return None
    with wave.open(str(wav), 'rb') as handle:
        samples = np.frombuffer(handle.readframes(handle.getnframes()), np.int16).astype(np.float64) / 32768
    rows = json.loads(events.read_text(encoding='utf-8-sig'))
    rows = sorted(rows if isinstance(rows, list) else [rows], key=lambda row: row['c'])
    starts = [(SPEECH[row['c']:row['c'] + row['n']], float(row['t']), SPEECH[row['c'] + row['n']:].lstrip()[:1] == '.')
              for row in rows]
    return samples, starts


def true_extents(samples, starts, rate=16000):
    """Each word's measured extent: from its synthesizer start to the last sound before the next word."""
    level = np.convolve(samples ** 2, np.ones(160) / 160, mode='same')
    loud = 10 * np.log10(level + 1e-12) > -50
    extents = []
    for number, (text, start, _) in enumerate(starts):
        limit = starts[number + 1][1] if number + 1 < len(starts) else len(samples) / rate
        a, b = int(start * rate), int(limit * rate)
        hits = np.nonzero(loud[a:b])[0]
        end = (a + hits[-1]) / rate if len(hits) else start + 0.05
        first = (a + hits[0]) / rate if len(hits) else start
        extents.append((text, first, end))
    return extents


def add_room(samples, extents, rate=16000):
    """Room noise under everything and a breath (soft filtered noise) before 'Then' and 'So'."""
    rng = np.random.default_rng(11)
    out = samples + rng.normal(0, 0.0015, len(samples))
    for text, start, _ in extents:
        if text in ('Then', 'So'):
            length = int(0.22 * rate)
            breath = np.convolve(rng.normal(0, 1, length), np.ones(8) / 8, mode='same') * np.hanning(length) * 0.02
            begin = int((start - 0.30) * rate)
            out[begin:begin + length] += breath
    return out


def check_real_speech(tool, record, j):
    """Spoken sentences, a jittered transcript, and cuts that must land in real pauses."""
    folder = Path(j('cut-speech'))
    folder.mkdir(parents=True, exist_ok=True)
    spoken = speak(folder)
    if spoken is None:
        print('SKIP  cut: realistic speech needs Windows System.Speech (PowerShell)')
        return
    samples, starts = spoken
    extents = true_extents(samples, starts)
    noisy = add_room(samples, extents)
    root = folder / 'project'
    (root / 'media').mkdir(parents=True, exist_ok=True)
    write_wav(root / 'media' / 'vo_01.wav', noisy, 16000)
    duration = len(noisy) / 16000
    (root / 'map').mkdir(exist_ok=True)
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [
        source_row('vo_01', 'vo', 'media/vo_01.wav', duration, video=False)]}), encoding='utf-8')
    rng = np.random.default_rng(3)
    jittered = []
    previous = 0.0
    for text, start, end in extents:
        # A transcriber's edges are off by tens of milliseconds but keep the words in order without overlap.
        a = max(previous, start + rng.uniform(-0.06, 0.06))
        b = max(a + 0.05, end + rng.uniform(-0.06, 0.06))
        jittered.append((text, round(a, 3), round(b, 3), rng.uniform() < 0.3))
        previous = b
    write_words(root, 'vo_01', jittered)
    texts = [text for text, _, _ in extents]
    sentences, current = [], []
    for number, text in enumerate(texts):
        current.append(number)
        if starts[number][2]:
            sentences.append(current)
            current = []
    kept_sentences = (0, 2, 4)
    kept = [number for index in kept_sentences for number in sentences[index]]
    words = ' '.join(texts[number] for number in kept)
    first_start = extents[0][1] + 0.05
    last_end = extents[-1][2] + 0.25
    (root / 'film.md').write_text(f'---\nsize: 320x180\nfps: 25\n---\n'
                                  f'> vo_01 {first_start:.2f}-{last_end:.2f} {words}\n', encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--json')
    try:
        report = json.loads(output[output.index('{'):])
        runs = report['lines'][0]['runs']
    except (ValueError, KeyError, IndexError):
        record('cut: real speech compiles', False, output[-500:])
        return
    level = 10 * np.log10(np.convolve(noisy ** 2, np.ones(80) / 80, mode='same') + 1e-12)
    floor = np.percentile(level, 5)
    quiet = level < floor + 12

    def quiet_at(moment):
        index = int(moment * 16000)
        return bool(quiet[max(0, index - 80):index + 80].all())

    kept_set = set(kept)
    clipped = [texts[n] for n in kept if not any(r['in'] <= extents[n][1] - 0.005 and extents[n][2] + 0.005
                                                 <= r['out'] for r in runs)]
    leaked = [texts[n] for n in range(len(texts)) if n not in kept_set
              and any(r['in'] < extents[n][2] and extents[n][1] < r['out'] for r in runs)]
    noisy_cuts = [round(moment, 3) for r in runs for moment in (r['in'], r['out']) if not quiet_at(moment)]
    breaths = []
    for text, start, _ in extents:
        if text in ('Then', 'So'):
            breaths.append((start - 0.30, start - 0.08))
    in_breath = [round(m, 3) for r in runs for m in (r['in'], r['out']) if any(a < m < b for a, b in breaths)]
    record('cut: on synthesized speech with a jittered transcript, every cut lands in a measured pause, keeps every '
           'kept word whole, drops every removed word and avoids breaths',
           code == 0 and len(runs) == 3 and not clipped and not leaked and not noisy_cuts and not in_breath,
           f'runs {runs}; clipped {clipped}; leaked {leaked}; noisy {noisy_cuts}; breath {in_breath}')


def check_world_vfr_edit(tool, record, j):
    """Every cut, late pulse, word, caption and manifest follows a complete VFR paper edit."""
    root = Path(j('vfr-paper-project')).resolve()
    media = root / 'media'
    media.mkdir(parents=True, exist_ok=True)
    signal = np.zeros(RATE * 2, dtype=np.float32)
    source_markers = [.1, .5, 1.0, 1.5]
    for moment in source_markers:
        signal[round(moment * RATE):round((moment + .02) * RATE)] = .7
    wav = media / 'pulses.wav'
    write_wav(wav, signal)
    source = media / 'int_01.mkv'
    select = r'select=eq(n\,0)+eq(n\,1)+eq(n\,4)+eq(n\,5)+eq(n\,6)+eq(n\,9)+eq(n\,10)'
    select += r'+eq(n\,11)+eq(n\,14)+eq(n\,15)+eq(n\,16)+eq(n\,19)'
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', '10', '-i', 'pipe:0',
           '-i', wav, '-map', '0:v', '-map', '1:a', '-vf', select, '-fps_mode', 'passthrough',
           '-c:v', 'ffv1', '-threads', '1', '-c:a', 'pcm_s16le', source,
           data=counter_frames(20, PATCHES['int']))
    (root / 'map').mkdir(exist_ok=True)
    rows = [source_row('int_01', 'interview', 'media/int_01.mkv', 2, rate='10/1')]
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .1, .12), ('bravo', .5, .52),
                                 ('charlie', 1.0, 1.02), ('delta', 1.5, 1.52)])
    film = ('---\ntitle: VFR case\nsize: 320x180\nfps: 10\ncaptions: burn, srt, vtt\n---\n'
            '> int_01 0:00.00-0:00.30 alpha\n> int_01 0:00.40-0:00.70 bravo\n'
            '> int_01 0:00.90-0:01.20 charlie\n> int_01 0:01.40-0:01.70 delta\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    code, output = tool('cut.py', 'render', root)
    version = root / 'cuts' / 'v001'
    preview = version / 'preview.mp4'
    if code not in (0, 1) or not preview.is_file():
        record('cut: complete VFR edit keeps decoded picture, audio, words and captions aligned', False, output[-500:])
        return
    frames = decode_video(preview)
    counters = [read_counter(frame) for frame in frames]
    expected = [0, 1, 1, 4, 5, 6, 9, 10, 11, 14, 15, 16]
    samples = decode_audio(preview)
    hits = np.flatnonzero(np.abs(samples) > .1)
    starts = hits[np.r_[True, np.diff(hits) > RATE * .08]] / RATE if len(hits) else np.array([])
    expected_markers = np.array([.1, .4, .7, 1.0])
    audio_error = (float(np.max(np.abs(starts - expected_markers)))
                   if len(starts) == len(expected_markers) else float('inf'))
    lines = json.loads((version / 'lines.json').read_text(encoding='utf-8'))
    starts_lines = [line['start'] for line in lines['lines'] if line.get('kind') == 'spoken']
    words = [word for line in lines['lines'] for word in line.get('words', [])]
    captions = json.loads((version / 'captions.json').read_text(encoding='utf-8'))
    caption_words = [word for cue in captions.get('cues', []) for word in cue.get('words', [])]
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
    word_times = [word['start'] for word in words]
    caption_times = [word['start'] for word in caption_words]
    aligned = (len(word_times) == 4 and len(caption_times) == 4 and np.allclose(word_times, caption_times, atol=.001)
               and np.allclose(word_times, expected_markers, atol=.005))
    record('cut: complete VFR edit keeps decoded picture, audio, words and captions aligned',
           counters == expected and audio_error < .03 and np.allclose(starts_lines, [0, .3, .6, .9], atol=.001)
           and aligned and abs(manifest['duration_s'] - 1.2) < .001,
           f'counters={counters}; audio={starts.tolist()}; lines={starts_lines}; word={word_times}; '
           f'caption={caption_times}; duration={manifest.get("duration_s")}')


def check_craft2_units(record, j, scripts_dir):
    """Frame identity, a composited hold, and pauses interrupted by a breath."""
    def load(name):
        spec = importlib.util.spec_from_file_location('craft2_' + name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    assemble = load('assemble')
    cut = load('cut')
    raw = Path(j('craft2-counter.rgb'))
    raw.write_bytes(b''.join(bytes((i, i, i)) for i in range(100)))
    for fps in (Fraction(30000, 1001), Fraction(24), Fraction(25)):
        points = [round(float(Fraction(i, 1) / fps), 3) for i in range(100)]
        wrong = []
        for anchor in (3, 9, 10, 17):
            clip = {'mode': 'nearest', 'start': points[anchor], 'at': 0, 'speed': 1, 'times': points,
                    'raw': str(raw), 'time_tick': .001, 'sw': 1, 'sh': 1, 'fit': 'contain', 'background': 'black'}
            clip['_matching_grid'] = assemble.source_grid_matches(clip, fps)
            with raw.open('rb') as reader:
                got = [assemble.render_clip(clip, float(Fraction(i, 1) / fps), {str(raw): reader}, 1, 1)
                       .getpixel((0, 0))[0] for i in range(60)]
            wrong.extend((anchor, i, value, i + anchor) for i, value in enumerate(got) if value != i + anchor)
        record(f'cut: millisecond PTS retains each frame at {fps}', not wrong, str(wrong[:6]))

    off_grid = {'mode': 'nearest', 'start': .0392, 'at': 0, 'speed': 1, 'times': [0, .04, .08],
                'raw': str(raw), 'time_tick': .001, 'sw': 1, 'sh': 1, 'fit': 'contain', 'background': 'black'}
    with raw.open('rb') as reader:
        shown = assemble.render_clip(off_grid, 0, {str(raw): reader}, 1, 1).getpixel((0, 0))[0]
    record('cut: an off-grid in-point keeps its covering frame', shown == 0, str(shown))
    vfr = dict(off_grid, start=.04, times=[0, .04, .083, .12, .159])
    vfr['_matching_grid'] = assemble.source_grid_matches(vfr, Fraction(25))
    with raw.open('rb') as reader:
        shown = assemble.render_clip(vfr, .0422, {str(raw): reader}, 1, 1).getpixel((0, 0))[0]
    record('cut: a VFR boundary keeps the covering frame', not vfr['_matching_grid'] and shown == 1,
           f'grid={vfr["_matching_grid"]}, frame={shown}')

    class Sink:
        frames = []

        def __init__(self, *args):
            Sink.frames = []

        def write(self, frame):
            Sink.frames.append(np.asarray(frame).copy())

        def close(self):
            pass

        def abort(self):
            pass

    assemble.Encoder = Sink
    assemble.render_clip = lambda *args: Image.new('RGB', (4, 4), 'white')
    clips = [dict(at=0, duration=1, raw=str(raw), mode='nearest', time_tick=.001, speed=1,
                  times=[0, 1], start=0),
             dict(at=1, duration=2, raw=str(raw), mode='nearest', time_tick=.001, speed=1,
                  hold_previous=True, times=[0, 1], start=0)]
    overlay = Image.new('RGBA', (4, 4), (0, 0, 0, 128))
    assemble.render_picture('unused', clips, [(overlay, {}, 0, 3, 0)], 4, 4, 1, 3, 'unused')
    values = [int(frame[0, 0, 0]) for frame in Sink.frames]
    record('cut: hold composites an active overlay once', len(set(values)) == 1, str(values))

    rate = 16000
    t = np.arange(rate * 3) / rate
    rng = np.random.default_rng(3)
    samples = np.zeros(len(t))
    voiced = ((t >= .1) & (t < .8)) | ((t >= 2.3) & (t < 2.9))
    samples[voiced] = 15000 * np.sin(2 * np.pi * 440 * t[voiced])
    breath = (t >= 1.48) & (t < 1.63)
    samples[breath] = rng.normal(0, 1500, breath.sum())
    env = cut.Envelope(np.clip(samples, -32767, 32767).astype('int16'), rate, 0)
    words = [{'text': 'One', 'start': .1, 'end': .8, 'index': 0},
             {'text': 'Two', 'start': 2.3, 'end': 2.9, 'index': 1}]
    problems = cut.Problems()
    runs = cut.spoken_runs({'start': 0, 'end': 3, 'line': 1}, words, [0, 1], env,
                           {'max_pause': .5, 'pad': .2}, problems)
    kept = runs[0]['out'] - .8 + 2.3 - runs[1]['in'] if len(runs) == 2 else 1.5
    warning = any('max_pause' in p['message'] for p in problems.items)
    record('cut: breath in a pause is trimmed to the limit or warns', kept <= .51 or warning,
           f'{kept:.3f} seconds; {problems.items}')
    record('cut: removing an audible breath prompts a listen', warning, str(problems.items))

    class NoQuiet:
        reliable = True

        def quiet_runs(self, start, end):
            return []

        def quiet_at(self, moment):
            return True

    blocked = cut.Problems()
    cut.spoken_runs({'start': 0, 'end': 3, 'line': 1}, words, [0, 1], NoQuiet(),
                    {'max_pause': .5, 'pad': .2}, blocked)
    timed_warning = any('max_pause' in row['message'] and '0:00.80' in row['message'] for row in blocked.items)
    record('cut: an untrimmable pause warns with its time', timed_warning, str(blocked.items))
    declarations = cut.declared_ranges({'duration': 2, 'lines': [{'kind': 'still', 'start': 0, 'end': 2}]})
    record('cut: a still is declared', any(row['kind'] == 'still' for row in declarations), str(declarations))


def check_craft2_adjacent_and_pin(record, j, scripts_dir):
    """Adjacent speech uses each source instant once; a stale line must not misreport a caption pin."""
    root = Path(j('craft2-adjacent'))
    (root / 'map').mkdir(parents=True, exist_ok=True)
    (root / 'source.mkv').touch()
    row = source_row('int_01', 'interview', 'source.mkv', 2.0, rate='25/1')
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .1, .5), ('bravo', 1.3, 1.7)])
    film = ('---\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
            '> int_01 0:00.00-0:00.80 alpha\n'
            '> int_01 0:00.70-0:02.00 bravo\n'
            '- caption break before int_01-w000002\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('craft2_cut_adjacent', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    _, settings, _, plan, problems, _ = cut.analyse(root, measure=False)
    audio = plan['audio']
    picture, _ = cut.picture_items(plan, settings, problems)
    ok = len(audio) == 2 and len(picture) == 2 and audio[0]['out'] <= audio[1]['in'] \
        and picture[0]['out'] <= picture[1]['in']
    record('cut: adjacent speech does not replay source time', ok, f'audio={audio} picture={picture}')

    words_path = root / 'map' / 'int_01' / 'words.json'
    data = json.loads(words_path.read_text(encoding='utf-8'))
    data['words'][1]['text'] = 'corrected'
    words_path.write_text(json.dumps(data), encoding='utf-8')
    _, _, _, _, problems, _ = cut.analyse(root, measure=False)
    messages = [item['message'] for item in problems.items if item['severity'] == 'error']
    ok = any('bravo' in message for message in messages) and not any('caption break word' in msg for msg in messages)
    record('cut: a stale line does not falsely report its pinned word cut', ok, str(messages))


def decode_identity_video(path):
    """Decode every encoded frame once, without a second frame-rate conversion."""
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=width,height', '-of', 'csv=p=0', str(path)],
                           capture_output=True, text=True, check=True)
    width, height = map(int, probe.stdout.strip().split(','))
    frames = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0',
                             '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                            capture_output=True, check=True)
    return np.frombuffer(frames.stdout, np.uint8).reshape(-1, height, width, 3)


def check_craft2_frame_identity(tool, record, j):
    """Each counter is known before encoding, in both preview and final for nine source clocks."""
    selections = [(9, 41), (58, 86), (20, 48)]
    expected = [number for first, end in selections for number in range(first, end)]
    for rate in (Fraction(30000, 1001), Fraction(24), Fraction(25)):
        for container in ('mp4', 'webm', 'mkv'):
            root = Path(j(f'identity-{rate.numerator}-{rate.denominator}-{container}'))
            media = root / 'media'
            media.mkdir(parents=True, exist_ok=True)
            source = media / ('broll_01.' + container)
            count = round(4 * float(rate))
            codec = {'mp4': ['-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv420p', '-threads', '2'],
                     'webm': ['-c:v', 'libvpx-vp9', '-lossless', '1', '-threads', '2'],
                     'mkv': ['-c:v', 'ffv1']}[container]
            ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(rate),
                   '-i', 'pipe:0', '-vf', 'scale=640:360:flags=neighbor', *codec, source,
                   data=counter_frames(count, PATCHES['broll']))
            (root / 'map').mkdir(exist_ok=True)
            row = source_row('broll_01', 'broll', 'media/' + source.name, 4.0, rate=str(rate), audio=False)
            row['video'] = {'width': 640, 'height': 360, 'fps': str(rate)}
            (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row]}),
                                                       encoding='utf-8')
            lines = ['---', 'title: Frame identity', 'size: 320x180', f'fps: {rate}', 'captions: none', '---']
            for first, end in selections:
                start_time = float(Fraction(first, 1) / rate)
                end_time = float(Fraction(end, 1) / rate)
                lines.append(f'- broll_01 0:{start_time:09.6f}-0:{end_time:09.6f} counter')
            (root / 'film.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            for final in (False, True):
                args = ('--final',) if final else ()
                code, output = tool('cut.py', 'render', root, *args)
                number = 2 if final else 1
                version = root / 'cuts' / f'v{number:03d}'
                video = version / 'preview.mp4'
                got = [read_counter(frame) for frame in decode_identity_video(video)] if video.is_file() else []
                manifest_file = version / 'manifest.json'
                manifest = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.is_file() else {}
                proxy = final or 'broll_01' in manifest.get('proxies', [])
                wrong = [(i, a, b) for i, (a, b) in enumerate(zip(got, expected)) if a != b]
                ok = code in (0, 1) and proxy and got == expected
                label = 'final' if final else 'preview proxy'
                record(f'cut: every {container} frame at {rate} in {label}', ok,
                       f'frames={len(got)}/{len(expected)} proxy={proxy} wrong={wrong[:4]} {output[-300:]}')


def check_craft2_wide_master(record, j, scripts_dir):
    """Wide-range speech-like audio that meets the peak ceiling needs gain, not compression."""
    spec = importlib.util.spec_from_file_location('craft2_master', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    rate = 48000
    time = np.arange(40 * rate) / rate
    level = np.where((time // 6) % 2 == 0, .24, .04)
    syllables = .35 + .65 * (.5 + .5 * np.sin(2 * np.pi * 3.1 * time))
    signal = level * syllables * (np.sin(2 * np.pi * 220 * time) + .4 * np.sin(2 * np.pi * 440 * time))
    source, output = Path(j('craft2-wide-master.wav')), Path(j('craft2-wide-normalized.wav'))
    write_wav(source, signal, rate)
    try:
        before, after = cut.loudnorm_passes('ffmpeg', source, output, -16)
        input_range = float(before['input_lra'])
        output_range = float(after['output_lra'])
        mode = after['normalization_type'].lower()
        ok = input_range > 11 and mode == 'linear' and abs(output_range - input_range) <= 1
        detail = f'input LRA={input_range}, output LRA={output_range}, mode={mode}'
    except (ValueError, RuntimeError, KeyError) as error:
        ok, detail = False, str(error)
    record('cut: wide-range dialogue stays linear when gain fits the ceiling', ok, detail)


def check_hold_overlays(record, j, scripts_dir):
    """A fade and a title ending at a hold are applied to the live base, once per frame."""
    spec = importlib.util.spec_from_file_location('craft2_hold_overlays', Path(scripts_dir) / 'assemble.py')
    assemble = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assemble)
    raw = Path(j('craft2-hold-source.rgb'))
    raw.write_bytes(bytes([255, 255, 255]))

    class Sink:
        frames = []

        def __init__(self, *args):
            Sink.frames = []

        def write(self, frame):
            Sink.frames.append(np.asarray(frame).copy())

        def close(self):
            pass

        def abort(self):
            pass

    assemble.Encoder = Sink
    assemble.render_clip = lambda *args: Image.new('RGB', (4, 4), 'white')
    clips = [dict(at=0, duration=1, raw=str(raw), mode='nearest', time_tick=.001, speed=1,
                  times=[0, .25], start=0),
             dict(at=1, duration=2, raw=str(raw), mode='nearest', time_tick=.001, speed=1,
                  hold_previous=True, times=[0, .25], start=0)]
    layer = Image.new('RGBA', (4, 4), (0, 0, 0, 128))
    assemble.render_picture('unused', clips, [(layer, {}, 0, 3, 1.5)], 4, 4, 4, 3, 'unused')
    levels = [int(frame[0, 0, 0]) for frame in Sink.frames]
    expected = [255 - round(128 * max(0, min(1, (i / 4) / 1.5, (3 - i / 4) / 1.5))) for i in range(12)]
    record('cut: a fade spanning a hold has one live opacity',
           len(levels) == len(expected) and all(abs(a - b) <= 1 for a, b in zip(levels, expected)),
           f'{levels} versus {expected}')
    assemble.render_picture('unused', clips, [(layer, {}, 0, 3, 0)], 4, 4, 4, 3, 'unused')
    levels = [int(frame[0, 0, 0]) for frame in Sink.frames]
    record('cut: a title spanning a hold is drawn once',
           len(levels) == 12 and all(level == 127 for level in levels), str(levels))
    assemble.render_picture('unused', clips, [(layer, {}, 0, 1, 0)], 4, 4, 4, 3, 'unused')
    levels = [int(frame[0, 0, 0]) for frame in Sink.frames]
    record('cut: a title ending at a hold is not frozen into it',
           levels[3] == 127 and all(level == 255 for level in levels[4:]), str(levels))


def check_craft2_master_warning_boundaries(record, scripts_dir):
    """A one-decimal AAC meter at the tolerance boundary still prompts review."""
    spec = importlib.util.spec_from_file_location('craft2_master_warning', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    for loudness, expected in ((-15.5, True), (-16.5, True), (-15.6, False), (-16.4, False)):
        report = {'actual_mode': 'linear', 'target_lufs': -16, 'target_tolerance_lu': .5,
                  'requested_true_peak_dbtp': -1.5,
                  'delivered_aac': {'integrated_lufs': loudness, 'true_peak_dbtp': -3},
                  'simulated_aac_reencode': {'true_peak_dbtp': -3}}
        warnings = cut.master_warnings(report)
        found = any('delivered AAC measured' in warning for warning in warnings)
        record(f'cut: delivered AAC {loudness:g} LUFS boundary warning', found == expected, str(warnings))


# ----------------------------------------------------------------------------------------------- joins

JOIN_WORDS = [(0.5, 0.9), (1.2, 1.6), (2.0, 2.4), (4.0, 4.4), (4.8, 5.2), (5.6, 6.0)]
# Each source: a quiet steady bed tone that names it, and six word tones of its own.
BEDS = {'int_01': (150, 400, 'a'), 'int_02': (3000, 1000, 'b'), 'int_03': (5000, 1600, 'c')}
BED_LEVEL = 0.02

JOIN_FILM = """---
title: Joins case
size: 320x180
fps: 25
captions: srt
---
## One
> int_01 0:00.30-0:02.70 a0 a1 a2{tail}
> int_02 0:00.30-0:02.70 b0 b1 b2
> int_03 0:03.40-0:06.50 c3 c4 c5{lead}
> int_02 0:03.40-0:06.30 b3 b4 b5{dissolve}
"""


def bed_source(folder, alias, seconds=8.0):
    """A counter video whose sound is a bed tone under six word tones; returns its words.json rows."""
    bed, base, letter = BEDS[alias]
    times = np.arange(int(seconds * RATE)) / RATE
    samples = BED_LEVEL * np.sin(2 * np.pi * bed * times)
    rows = []
    for index, (start, end) in enumerate(JOIN_WORDS):
        a, b = int(start * RATE), int(end * RATE)
        t = np.arange(b - a) / RATE
        ramp = np.minimum(1, np.minimum(t, t[::-1]) / 0.005)
        samples[a:b] += 0.3 * np.sin(2 * np.pi * (base + 100 * index) * t) * ramp
        rows.append((f'{letter}{index}', start, end))
    wav = Path(folder) / f'{alias}.wav'
    write_wav(wav, samples)
    path = Path(folder) / f'{alias}.mkv'
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', 'pipe:0',
           '-f', 'wav', '-i', wav,
           '-map', '0:v', '-map', '1:a', '-c:a', 'pcm_s16le', '-c:v', 'ffv1', path,
           data=counter_frames(int(seconds * FPS), PATCHES['int']))
    return rows


def join_project(root, media):
    """A project with the three bed sources."""
    root = Path(root)
    (root / 'media').mkdir(parents=True, exist_ok=True)
    rows = []
    for alias in BEDS:
        shutil.copy2(Path(media) / f'{alias}.mkv', root / 'media' / f'{alias}.mkv')
        rows.append(source_row(alias, 'interview', f'media/{alias}.mkv', 8.0))
    (root / 'map').mkdir(exist_ok=True)
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    for alias in BEDS:
        write_words(root, alias, json.loads((Path(media) / f'{alias}.words.json').read_text(encoding='utf-8')))
    return root


def checked(tool, root):
    """cut.py check --json as a dict ({} when it did not print one), and the exit code."""
    code, output = tool('cut.py', 'check', root, '--json')
    try:
        return json.loads(output[output.index('{'):]), code, output
    except ValueError:
        return {}, code, output


def amplitude_at(samples, freq, moment):
    """The amplitude of a tone at one moment (the 43 ms analysis window nearest it)."""
    times, values = tone_track(samples, freq)
    return float(values[int(np.argmin(abs(times - moment)))])


def run_joins_cases(tool, record, j):
    """tail, lead and a dissolve's crossfade heard in the rendered sound; the join report's numbers on tones of
    known level; abrupt-sound and busy-cutting warnings firing and not firing; a lead the source cannot supply."""
    media = Path(j('joins-media'))
    media.mkdir(parents=True, exist_ok=True)
    for alias in BEDS:
        rows = bed_source(media, alias)
        (media / f'{alias}.words.json').write_text(json.dumps(rows), encoding='utf-8')
    plain = join_project(j('joins-plain'), media)
    (plain / 'film.md').write_text(JOIN_FILM.format(tail='', lead='', dissolve=''), encoding='utf-8')
    before, _, output = checked(tool, plain)
    abrupt = [row for row in before.get('joins', []) if row['abrupt']]
    record('cut: unbridged joins between different sound worlds are warned about, with time and suggestion',
           len(before.get('joins', [])) == 3 and len(abrupt) == 3 and all('tone' in row['change'] for row in abrupt)
           and sum('the sound changes abruptly at' in row['message'] and 'tail or lead' in row['suggestion']
                   for row in before.get('problems', [])) == 3, output[-1500:])
    carried = join_project(j('joins-carried'), media)
    (carried / 'film.md').write_text(JOIN_FILM.format(tail=' {tail 1.0}', lead=' {lead 0.8}',
                                                      dissolve=' {dissolve 0.6}'), encoding='utf-8')
    after, _, output = checked(tool, carried)
    record('cut: tail, lead and dissolve bridge their joins, so no abrupt sound is reported',
           [row['bridged'] for row in after.get('joins', [])] == [['tail 1.00 s'], ['lead 0.80 s'],
                                                                   ['dissolve 0.60 s']]
           and not any(row['abrupt'] for row in after.get('joins', []))
           and not any('abruptly' in row['message'] for row in after.get('problems', [])), output[-1500:])
    words_before = [line.get('words') for line in before.get('lines', []) if line['kind'] == 'spoken']
    words_after = [line.get('words') for line in after.get('lines', []) if line['kind'] == 'spoken']
    record('cut: tail, lead and dissolve leave every kept word at the same film time',
           words_before and words_before == words_after, f'{words_before} vs {words_after}')
    check_carried_render(tool, record, carried)
    check_known_levels(tool, record, j)
    check_busy_cutting(tool, record, j)
    check_busy_freeze(tool, record, j)


def run_lowend_cases(tool, record, j):
    """A low-frequency-only change, an equal bed, and the same change with a real lead."""
    root = Path(j('joins-lowend'))
    media = root / 'media'
    media.mkdir(parents=True, exist_ok=True)
    times = np.arange(12 * RATE) / RATE
    bass = np.where((times < 2.5) | (times >= 8), 0.08, 0.01)
    samples = 0.1 * np.sin(2 * np.pi * 1000 * times) + bass * np.sin(2 * np.pi * 60 * times)
    wav = media / 'bass.wav'
    write_wav(wav, samples)
    video = media / 'bass.mkv'
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', 'pipe:0',
           '-i', wav, '-map', '0:v', '-map', '1:a', '-c:a', 'pcm_s16le', '-c:v', 'ffv1', video,
           data=counter_frames(12 * FPS, PATCHES['broll']))
    bass = np.where((times < 2.5) | ((times >= 5) & (times < 8)), 0.08, 0.05)
    treble = np.where(times < 5, 0.03, 0.3)
    dominant_wav = media / 'dominant.wav'
    write_wav(dominant_wav, treble * np.sin(2 * np.pi * 1000 * times) + bass * np.sin(2 * np.pi * 60 * times))
    ffmpeg('-i', video, '-i', dominant_wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'pcm_s16le',
           media / 'dominant.mkv')
    background = 0.03 * np.sin(2 * np.pi * 1000 * times) + 0.04 * np.sin(2 * np.pi * 60 * times)
    background *= np.where(times >= 9.4, 4, 1)
    speech = np.where((times >= 3) & (times < 3.25), 0.3 * np.sin(2 * np.pi * 2200 * times), 0)
    transient_wav = media / 'transient.wav'
    write_wav(transient_wav, background + speech)
    ffmpeg('-i', video, '-i', transient_wav, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'pcm_s16le',
           media / 'transient.mkv')
    (root / 'map').mkdir(exist_ok=True)
    row = dict(source_row('bass_01', 'broll', 'media/bass.mkv', 12.0), mapped={'words': False})
    other = dict(source_row('bass_02', 'broll', 'media/dominant.mkv', 12.0), mapped={'words': False})
    transient = dict(source_row('bass_03', 'broll', 'media/transient.mkv', 12.0), mapped={'words': False})
    music = dict(source_row('music_01', 'music', 'media/bass.mkv', 12.0), mapped={'words': False})
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [row, other, transient, music]}),
                                                encoding='utf-8')
    (root / 'map' / 'bass_03').mkdir(exist_ok=True)
    activity = {'speech_activity': {'segments': [[3.0, 3.25]]}}
    (root / 'map' / 'bass_03' / 'audio.json').write_text(json.dumps(activity), encoding='utf-8')
    film = ('---\ntitle: Bass\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
            '- bass_01 0:00.50-0:02.00 sound Loud low end\n'
            '- bass_01 0:03.00-0:04.50 sound Quiet low end\n'
            '- bass_01 0:06.00-0:07.50 sound Equal low end\n'
            '- bass_01 0:09.00-0:10.50 sound Loud again {lead 0.5}\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    report, _, output = checked(tool, root)
    joins = report.get('joins', [])
    first = joins[0] if len(joins) == 3 else {}
    low = first.get('from', {}).get('low_db')
    quiet = first.get('to', {}).get('low_db')
    warning = [item for item in report.get('problems', []) if 'low' in item.get('message', '').lower()]
    record('cut: a low-end-only change is measured and warned at an unbridged join',
           low is not None and quiet is not None and abs(low + 25) < 1 and abs(quiet + 43) < 1
           and first.get('abrupt') and 'low' in (first.get('change') or '') and bool(warning), output[-1500:])
    same = joins[1] if len(joins) == 3 else {}
    record('cut: equal low end is measured and is not flagged',
           abs(same.get('low_jump_db', 100)) < 1 and not same.get('abrupt', True), output[-1500:])
    bridged = joins[2] if len(joins) == 3 else {}
    record('cut: a lead bridges a large low-end change without an abrupt warning',
           abs(bridged.get('low_jump_db', 0)) > 10 and bool(bridged.get('bridged'))
           and not bridged.get('abrupt', True), output[-1500:])
    for name, updated in (
            ('short lead', film.replace('{lead 0.5}', '{lead 0.3}')),
            ('lead just under 0.5 s', film.replace('{lead 0.5}', '{lead 0.49}')),
            ('short tail', film.replace('sound Equal low end\n', 'sound Equal low end {tail 0.3}\n')
             .replace(' {lead 0.5}', ''))):
        (root / 'film.md').write_text(updated, encoding='utf-8')
        short_report, _, output = checked(tool, root)
        short_joins = short_report.get('joins', [])
        short = short_joins[2] if len(short_joins) == 3 else {}
        record(f'cut: a {name} does not hide a large low-end change',
               abs(short.get('low_jump_db', 0)) > 10 and bool(short.get('bridged'))
               and short.get('abrupt') and 'low end' in (short.get('abrupt_change') or short.get('change') or ''),
               output[-1500:])
    for name, updated in (
            ('0.5 s tail', film.replace('sound Equal low end\n', 'sound Equal low end {tail 0.5}\n')
             .replace(' {lead 0.5}', '')),
            ('short dissolve', film.replace('{lead 0.5}', '{dissolve 0.3}')),
            ('music bed', film.replace('---\n- bass_01', '---\n- music music_01 0:00-0:12 -18dB\n- bass_01', 1)
             .replace('{lead 0.5}', '{lead 0.3}'))):
        (root / 'film.md').write_text(updated, encoding='utf-8')
        carried_report, _, output = checked(tool, root)
        carried_joins = carried_report.get('joins', [])
        carried = carried_joins[2] if len(carried_joins) == 3 else {}
        record(f'cut: a {name} still bridges a large low-end change',
               abs(carried.get('low_jump_db', 0)) > 10 and bool(carried.get('low_bridged'))
               and not carried.get('abrupt', True), output[-1500:])
    (root / 'film.md').write_text(film.replace('sound Quiet low end', 'sound +3dB Quiet low end'), encoding='utf-8')
    raised, _, output = checked(tool, root)
    raised_joins = raised.get('joins', [])
    side = raised_joins[0]['to'] if raised_joins else {}
    record('cut: a sound modifier changes both low-end measurements by its gain',
           abs(side.get('low_db', 0) + 40) < 1 and abs(side.get('near_low_db', 0) + 40) < 1, output[-1500:])
    dominant_film = film.replace('bass_01', 'bass_02').replace(' {lead 0.5}', '')
    (root / 'film.md').write_text(dominant_film, encoding='utf-8')
    dominant, _, output = checked(tool, root)
    rows = dominant.get('joins', [])
    bass_heavy = rows[0] if len(rows) == 3 else {}
    treble_heavy = rows[2] if len(rows) == 3 else {}
    record('cut: a smaller low-end jump is warned when the near-join sound is bass-dominant',
           bass_heavy.get('abrupt') and 'low end' in (bass_heavy.get('change') or '')
           and 3.5 <= abs(bass_heavy.get('near_low_jump_db', 0)) < 6, output[-1500:])
    record('cut: the same smaller bass jump under louder high frequencies is not flagged',
           3.5 <= abs(treble_heavy.get('near_low_jump_db', 0)) < 6
           and not treble_heavy.get('abrupt', True), output[-1500:])
    short_film = dominant_film.replace('sound Quiet low end\n', 'sound Quiet low end {lead 0.3}\n')
    (root / 'film.md').write_text(short_film, encoding='utf-8')
    short_report, _, output = checked(tool, root)
    short_joins = short_report.get('joins', [])
    small = short_joins[0] if len(short_joins) == 3 else {}
    record('cut: a short lead still bridges a smaller bass-dominant change',
           3.5 <= abs(small.get('near_low_jump_db', 0)) < 6 and bool(small.get('bridged'))
           and not small.get('abrupt', True), output[-1500:])
    (root / 'film.md').write_text(film.replace('bass_01', 'bass_03').replace(' {lead 0.5}', ''), encoding='utf-8')
    transient_report, _, output = checked(tool, root)
    rows = transient_report.get('joins', [])
    speech_join = rows[0] if len(rows) == 3 else {}
    later_join = rows[2] if len(rows) == 3 else {}
    near_before = later_join.get('from', {}).get('near_bed_db', 0)
    near_after = later_join.get('to', {}).get('near_bed_db', 100)
    record('cut: a level jump is warned even when the background is steady',
           abs(speech_join.get('jump_db', 0)) >= 6 and abs(speech_join.get('bed_jump_db', 100)) < 1
           and speech_join.get('abrupt') and 'level' in (speech_join.get('change') or ''), output[-1500:])
    record('cut: a large background jump is warned even when the near edges match',
           abs(later_join.get('bed_jump_db', 0)) >= 6 and abs(later_join.get('low_jump_db', 0)) >= 6
           and abs(near_after - near_before) < 1 and later_join.get('abrupt')
           and 'background' in (later_join.get('change') or ''), output[-1500:])
    normal_bridge = film.replace('bass_01', 'bass_03').replace(' {lead 0.5}', '')
    normal_bridge = normal_bridge.replace('sound Quiet low end\n', 'sound Quiet low end {lead 0.3}\n')
    (root / 'film.md').write_text(normal_bridge, encoding='utf-8')
    normal_report, _, output = checked(tool, root)
    rows = normal_report.get('joins', [])
    normal = rows[0] if len(rows) == 3 else {}
    record('cut: a short lead still bridges an ordinary level-only jump',
           'level' in (normal.get('change') or '') and bool(normal.get('bridged'))
           and 'low end' not in (normal.get('change') or '') and not normal.get('abrupt', True), output[-1500:])
    check_lowend_speech_mask(record)


def check_lowend_speech_mask(record):
    """Speech-masked frames cannot supply a near-join bass measurement."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('cut_lowend_mask_case', scripts / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    rate = 16000
    times = np.arange(2 * rate) / rate
    amplitudes = np.where(times < 0.4, 0.08, 0.01)
    samples = amplitudes * np.sin(2 * np.pi * 60 * times)
    mask = times < 0.4
    first = cut.sound_facts(samples, rate, True, mask)
    last = cut.sound_facts(samples, rate, False, mask)
    record('cut: masked speech cannot supply a near-join low-end measurement',
           'near_low_db' not in first and abs(first.get('low_db', 0) + 43) < 1
           and abs(last.get('near_low_db', 0) + 43) < 1, str((first, last)))


def check_carried_render(tool, record, root):
    """Render the carried joins and hear each one in the preview's sound."""
    _, output = tool('cut.py', 'render', root)
    version = root / 'cuts' / 'v001'
    if not (version / 'preview.mp4').is_file():
        record('cut: tail, lead and dissolve render', False, output[-800:])
        return
    data = json.loads((version / 'lines.json').read_text(encoding='utf-8'))
    spoken = [line for line in data['lines'] if line['kind'] == 'spoken']
    samples = decode_audio(version / 'preview.mp4')
    join_1, join_2 = spoken[1]['start'], spoken[2]['start']
    tail = [amplitude_at(samples, 150, join_1 + offset) / BED_LEVEL for offset in (-0.4, 0.25, 0.5, 1.2)]
    record('cut: a tail runs the line\'s sound on under the next line, fading out over its seconds',
           spoken[0].get('sound_carry') == {'tail': 1.0} and tail[0] > .85 and .6 < tail[1] < .9
           and .35 < tail[2] < .65 and tail[3] < .1, f'{tail} {spoken[0].get("sound_carry")}')
    lead = [amplitude_at(samples, 5000, join_2 + offset) / BED_LEVEL for offset in (-0.95, -0.4, 0.4)]
    under = amplitude_at(samples, 3000, join_2 - 0.4) / BED_LEVEL
    record('cut: a lead starts the line\'s sound before its picture, fading in under the line before',
           spoken[2].get('sound_carry') == {'lead': 0.8} and lead[0] < .1 and .35 < lead[1] < .65 and lead[2] > .85
           and under > .85, f'lead={lead} under={under} {spoken[2].get("sound_carry")}')
    start, end = (spoken[3].get('sound_carry') or {}).get('crossfade', [0, 0])
    points = [start + (end - start) * share for share in (.25, .5, .75)]
    pairs = [(amplitude_at(samples, 5000, t) / BED_LEVEL, amplitude_at(samples, 3000, t) / BED_LEVEL) for t in points]
    power = [x * x + y * y for x, y in pairs]
    outside = (amplitude_at(samples, 3000, start - 0.12) / BED_LEVEL,
               amplitude_at(samples, 5000, end + 0.12) / BED_LEVEL)
    record('cut: a dissolve crossfades the two lines\' sound with equal power over its seconds, clear of the words',
           abs(end - start - 0.6) < .01 and abs(start - spoken[3]['start']) < .1 and .55 < pairs[1][0] < .85
           and .55 < pairs[1][1] < .85 and all(.75 < value < 1.25 for value in power) and max(outside) < .15,
           f'window={start}-{end} pairs={pairs} power={power} outside={outside}')
    heard = []
    for line in spoken:
        base = BEDS[line['source']][1]
        for word in line['words']:
            index = int(word['text'][1:])
            heard.append(word_present(samples, base + 100 * index, word['start'], word['end']))
    record('cut: every kept word sounds at its lines.json time after the sound is carried',
           len(heard) == 12 and min(heard) > .15, str([round(value, 3) for value in heard]))
    joins = data.get('joins') or []
    record('cut: render records the join report in lines.json',
           len(joins) == 3 and all(row['bridged'] and not row['abrupt'] for row in joins)
           and all('level_db' in row['from'] and 'bed_db' in row['to'] for row in joins)
           and 'picture_changes' in data and 'busy_cutting' in data, json.dumps(joins)[:1200])
    record('cut: lines.json keeps measured low-end levels and their change',
           any('low_db' in row['from'] and 'low_db' in row['to'] and 'low_jump_db' in row for row in joins),
           json.dumps(joins)[:1200])


def level_project(root):
    """lvl_01: 1100 Hz at -20 dBFS (0-4 s), 1100 Hz at -32 dBFS (4-8 s), 4400 Hz at -20 dBFS (8-12 s), no speech;
    mus_01: a steady music bed. Both have no transcript, so the meter treats all of their sound as background."""
    root = Path(root)
    (root / 'media').mkdir(parents=True, exist_ok=True)
    times = np.arange(12 * RATE) / RATE
    amplitude = np.where(times < 4, 10 ** (-20 / 20), 10 ** (-32 / 20)) * math.sqrt(2)
    amplitude[times >= 8] = 10 ** (-20 / 20) * math.sqrt(2)
    freq = np.where(times < 8, 1100, 4400)
    write_wav(root / 'media' / 'lvl_01.wav', amplitude * np.sin(2 * np.pi * freq * times))
    ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', 'pipe:0',
           '-f', 'wav',
           '-i', root / 'media' / 'lvl_01.wav', '-map', '0:v', '-map', '1:a', '-c:a', 'pcm_s16le', '-c:v', 'ffv1',
           root / 'media' / 'lvl_01.mkv', data=counter_frames(12 * FPS, PATCHES['broll']))
    write_wav(root / 'media' / 'mus_01.wav', 0.1 * np.sin(2 * np.pi * 330 * np.arange(20 * RATE) / RATE))
    rows = [dict(source_row('lvl_01', 'broll', 'media/lvl_01.mkv', 12.0), mapped={'words': False}),
            dict(source_row('mus_01', 'music', 'media/mus_01.wav', 20.0, video=False), mapped={'words': False})]
    (root / 'map').mkdir(exist_ok=True)
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': rows}), encoding='utf-8')
    return root


LEVEL_FILM = """---
title: Levels case
size: 320x180
fps: 25
captions: none
---
{music}- lvl_01 0:01.00-0:03.00 sound Loud tone
- lvl_01 0:05.00-0:07.00 sound Quiet tone, 12 dB down
- lvl_01 0:05.00-0:07.00 sound +3dB Quiet tone raised 3 dB
- lvl_01 0:09.00-0:11.00 sound High tone at the first level
- lvl_01 0:00.20-0:02.00 sound {{lead 0.5}}
- lvl_01 0:09.00-0:11.00 Silent shot
"""


def check_known_levels(tool, record, j):
    """The join report's numbers on tones of known level and pitch, and which joins it calls abrupt."""
    root = level_project(j('joins-levels'))
    (root / 'film.md').write_text(LEVEL_FILM.format(music=''), encoding='utf-8')
    report, _, output = checked(tool, root)
    joins = report.get('joins', [])
    if len(joins) != 5:
        record('cut: the join report measures tones of known level', False, output[-1500:])
        return
    first = joins[0]
    record('cut: the join report measures tones of known level (-20 and -32 dBFS: a -12 dB jump at 1100 Hz)',
           abs(first['from']['level_db'] + 20) < .5 and abs(first['to']['level_db'] + 32) < .5
           and abs(first['jump_db'] + 12) < .5 and abs(first['bed_jump_db'] + 12) < .5
           and abs(first['from']['centroid_hz'] - 1100) < 60 and abs(first['to']['centroid_hz'] - 1100) < 60
           and first['tone_change_db'] < 2 and abs(first['shots'][0] - 2) < .05, json.dumps(first))
    pitch = joins[2]
    record('cut: the join report applies a line\'s gain and sees a change of pitch (1100 to 4400 Hz)',
           abs(joins[1]['jump_db'] - 3) < .5 and abs(pitch['to']['centroid_hz'] - 4400) < 150
           and 3.6 < pitch['centroid_ratio'] < 4.4 and pitch['tone_change_db'] >= 10, json.dumps(joins[1:3]))
    record('cut: abrupt joins are a 12 dB drop and a new pitch; a 3 dB step, a lead and a cut to silence are not',
           [row['abrupt'] for row in joins] == [True, False, True, False, False]
           and joins[3]['bridged'] == ['lead 0.20 s'] and joins[4]['to'].get('sound') is False, output[-1500:])
    short = [row for row in report.get('problems', []) if 'lead shortened to 0.20 s' in row['message']]
    record('cut: a lead the source cannot supply is shortened to the sound there is, and says so',
           len(short) == 1 and 'only 0.20 s of sound before 0:00.20' in short[0]['message']
           and [line.get('sound_carry') for line in report['lines']][4] == {'lead': 0.2}, output[-1500:])
    (root / 'film.md').write_text(LEVEL_FILM.format(music='- music mus_01 0:00-0:20 -18dB\n'), encoding='utf-8')
    bedded, _, output = checked(tool, root)
    joins = bedded.get('joins', [])
    record('cut: a music bed under a join bridges it',
           len(joins) == 5 and 'music bed mus_01' in joins[0]['bridged'] and not any(row['abrupt'] for row in joins),
           output[-1500:])
    errors = LEVEL_FILM.format(music='').replace('Silent shot', '{tail 0.5}').replace(
        'Quiet tone, 12 dB down', '{dissolve 0.5}').replace('sound Loud tone', 'sound {tail 0.5}')
    (root / 'film.md').write_text(errors, encoding='utf-8')
    report, code, output = checked(tool, root)
    messages = ' | '.join(row['message'] for row in report.get('problems', []) if row['severity'] == 'error')
    record('cut: tail on a silent picture line, and a dissolve with a tail on one join, are errors',
           code == 1 and 'this picture line is silent' in messages and 'a dissolve and a tail or lead' in messages,
           messages or output[-800:])


BUSY_FILM = """---
title: Busy case
size: 320x180
fps: 25
captions: none
---
## Run
- lvl_01 0:01.00-0:01.80 one
- lvl_01 0:02.00-0:02.80 two
- lvl_01 0:03.00-0:03.80 three
- lvl_01 0:04.00-0:04.80 four
## Battle montage
- lvl_01 0:05.00-0:05.80 five
- lvl_01 0:06.00-0:06.80 six
- lvl_01 0:07.00-0:07.80 seven
- lvl_01 0:03.00-0:03.80 eight
## Hold
- lvl_01 0:09.00-0:11.00 a source with two shot changes of its own
- lvl_01 0:01.00-0:04.00 a long shot
"""


def check_busy_cutting(tool, record, j):
    """Three picture changes in three seconds are reported outside a montage section, including a source's own
    shot changes; inside a section named montage they are not."""
    root = level_project(j('joins-busy'))
    (root / 'map' / 'lvl_01').mkdir(parents=True, exist_ok=True)
    (root / 'map' / 'lvl_01' / 'shots.json').write_text(json.dumps({'version': 1, 'source': 'lvl_01', 'shots': [
        {'start': 0.0, 'end': 9.5}, {'start': 9.5, 'end': 10.5}, {'start': 10.5, 'end': 12.0}]}), encoding='utf-8')
    (root / 'film.md').write_text(BUSY_FILM, encoding='utf-8')
    report, _, output = checked(tool, root)
    busy = report.get('busy_cutting', [])
    kinds = [change['kind'] for change in report.get('picture_changes', [])]
    warned = [row for row in report.get('problems', []) if 'picture changes in' in row['message']]
    record('cut: busy cutting outside a montage section is warned about; a montage section is left alone',
           len(busy) == 2 and busy[0]['line'] == 9 and busy[0]['changes'] == 3
           and abs(busy[0]['start'] - 0.8) < .01 and abs(busy[0]['end'] - 2.4) < .01
           and busy[1]['line'] == 18 and busy[1]['changes'] == 4 and len(warned) == 2
           and kinds.count('source shot') == 2 and len(kinds) == 11, output[-1500:])


FREEZE_FILM = """---
title: Freeze case
size: 320x180
fps: 25
captions: none
---
## Run
- lvl_01 0:01.00-0:01.80 one
- still lvl_01 0:05.00 0.8 the next shot freezes
- lvl_01 0:05.00-0:05.80 and runs on from the frozen frame
- pause 0.8 hold
- lvl_01 0:05.80-0:06.60 and runs on again after the hold
- still lvl_01 0:09.00 0.8 a frame of another moment
"""


def check_busy_freeze(tool, record, j):
    """A freeze (still ALIAS TIME, or pause N hold) and the same source running on from the frozen frame are one
    picture event: only the cut into the freeze and the cut to another moment count, so no busy cutting."""
    root = level_project(j('joins-freeze'))
    (root / 'film.md').write_text(FREEZE_FILM, encoding='utf-8')
    report, _, output = checked(tool, root)
    changes = [(round(change['at'], 2), change['line']) for change in report.get('picture_changes', [])]
    record('cut: a freeze followed by the same shot running on is one picture event, not busy cutting',
           changes == [(0.8, 9), (4.0, 13)] and not report.get('busy_cutting')
           and not any('picture changes in' in row['message'] for row in report.get('problems', [])),
           f'{changes} {output[-800:]}')


def polish_cut_cases(tool, record, j, scripts_dir):
    """Check contiguous speech, corrected timing, crop guidance, and redirected UTF-8 JSON."""
    root = Path(j('polish-cut'))
    (root / 'map').mkdir(parents=True, exist_ok=True)
    (root / 'source.mkv').touch()
    row = source_row('int_01', 'interview', 'source.mkv', 2.0, rate='25/1')
    (root / 'map' / 'sources.json').write_text(json.dumps({'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .1, .5), ('bravo', 1.3, 1.7)])
    film = ('---\ntitle: Caf\u00e9 \u4e16\u754c\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
            '## Caf\u00e9 \u4e16\u754c\n> int_01 0:00.00-0:00.80 alpha\n> int_01 0:00.80-0:02.00 bravo\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    spec = importlib.util.spec_from_file_location('polish_cut', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    _, _, _, plan, problems, _ = cut.analyse(root, measure=False)
    boundary = plan['lines'][0]['end'] if plan['lines'] else None
    marked = [x for row in plan['lines'] for x in row.get('tight_cuts', []) if abs(x - boundary) < .001]
    sound = plan['audio']
    record('cut: contiguous speech has no tight warning and does not skip or replay source time',
           len(sound) == 2 and abs(sound[0]['out'] - sound[1]['in']) < .00001
           and sound[0].get('fade_out_ms') == 0 and sound[1].get('fade_in_ms') == 0
           and not marked and not any('not measured' in x['message'] for x in problems.items),
           str((sound, marked, problems.items)))
    fine_film = film.replace('0:00.80', '0:00.80321')
    (root / 'film.md').write_text(fine_film, encoding='utf-8')
    _, _, _, fine_plan, fine_problems, _ = cut.analyse(root, measure=False)
    fine_boundary = fine_plan['lines'][0]['end']
    fine_marked = [at for row in fine_plan['lines'] for at in row.get('tight_cuts', [])
                   if abs(at - fine_boundary) < .001]
    record('cut: continuous boundary is suppressed after edit-time rounding',
           not fine_marked and not any('not measured' in item['message'] for item in fine_problems.items),
           str((fine_marked, fine_problems.items)))
    class NoQuiet:
        reliable = True
        def quiet_at(self, at):
            return False
        def quiet_runs(self, low, high):
            return []
    class EnvelopeSource:
        def get(self, alias, start, end):
            return NoQuiet()
    measured_problems = cut.Problems()
    source_map = cut.SourceMap(root)
    settings, entries = cut.parse_film(film, measured_problems, set(source_map.sources), root)
    cut.Compiler(settings, entries, source_map, EnvelopeSource(), measured_problems).run()
    record('cut: a measured loud but continuous source boundary is not called a tight cut',
           not any('no audible pause' in item['message'] for item in measured_problems.items),
           str(measured_problems.items))
    changed = film.replace('0:00.80-0:02.00 bravo', '0:01.00-0:02.00 bravo')
    (root / 'film.md').write_text(changed, encoding='utf-8')
    _, _, _, plan, problems, _ = cut.analyse(root, measure=False)
    record('cut: a noncontiguous unmeasured join still warns',
           any('not measured' in x['message'] for x in problems.items), str(problems.items))
    write_words(root, 'int_01', [('alpha', .1, .3), ('remove', .4, .6), ('bravo', 1.3, 1.7)])
    (root / 'film.md').write_text(film, encoding='utf-8')
    _, _, _, _, removed_problems, _ = cut.analyse(root, measure=False)
    record('cut: contiguous written ranges still warn when a boundary word was removed',
           any('not measured' in item['message'] for item in removed_problems.items), str(removed_problems.items))
    write_words(root, 'int_01', [('alpha', .1, .5), ('bravo', 1.3, 1.7)])
    (root / 'film.md').write_text(film.replace('alpha\n', 'alpha {crop 0.58}\n'), encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--json', '--no-audio')
    record('cut: one-number crop error shows the x,y form',
           code == 1 and ('x,y' in output or '0.58,0.5' in output), output[-800:])
    (root / 'film.md').write_text(film, encoding='utf-8')
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'cp1252'
    proc = subprocess.run([sys.executable, str(Path(scripts_dir) / 'cut.py'), 'check', str(root),
                           '--json', '--no-audio'], capture_output=True, env=env)
    try:
        decoded = json.loads(proc.stdout.decode('utf-8'))
        good = proc.returncode == 0 and decoded['lines'][0]['section'] == 'Caf\u00e9 \u4e16\u754c'
    except (UnicodeDecodeError, ValueError):
        good = False
    record('cut: redirected JSON is UTF-8 even under a legacy Python output encoding', good, str(proc.stderr[-400:]))


def polish_timing_to_cut_case(tool, record, j, scripts_dir):
    """The compiler uses corrected source-word edges in its edit-time word output."""
    root = Path(j('polish-timing-cut'))
    (root / 'map').mkdir(parents=True, exist_ok=True)
    (root / 'source.mkv').touch()
    row = source_row('int_01', 'interview', 'source.mkv', 2.0, rate='25/1')
    (root / 'map' / 'sources.json').write_text(json.dumps({'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .1, .5), ('bravo', 1.3, 1.7)])
    (root / 'film.md').write_text('---\nsize: 320x180\nfps: 25\n---\n'
                                  '> int_01 0:00.00-0:02.00 alpha bravo\n', encoding='utf-8')
    code, output = tool('map.py', 'fix', root, 'int_01-w000001', '--start', '0.2', '--end', '0.55')
    check_code, report = tool('cut.py', 'check', root, '--json', '--no-audio')
    try:
        words = json.loads(report)['lines'][0]['words']
        valid = words[0]['start'] == .2 and words[0]['end'] == .55
    except (ValueError, KeyError, IndexError):
        valid = False
    record('cut: corrected source word timing reaches the compiled edit',
           code == 0 and check_code == 0 and valid, output + report[-400:])


def polish_cut_description_case(record, scripts_dir):
    """Every cut warning identifies its edge and nearby kept words."""
    spec = importlib.util.spec_from_file_location('polish_cut_descriptions', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    rows = [{'line': 8, 'kind': 'spoken', 'start': 0, 'end': .8,
             'words': [{'text': 'before', 'start': .2, 'end': .6}], 'tight_cuts': []},
            {'line': 9, 'kind': 'spoken', 'start': 1, 'end': 4,
             'words': [{'text': 'alpha', 'start': 1.2, 'end': 1.4},
                       {'text': 'bravo', 'start': 2.5, 'end': 2.7}],
             'tight_cuts': [1, 2, 4], 'unmeasured_cuts': [1, 2]},
            {'line': 10, 'kind': 'spoken', 'start': 4.2, 'end': 5,
             'words': [{'text': 'after', 'start': 4.3, 'end': 4.6}], 'tight_cuts': []}]
    problems = cut.Problems()
    cut.report_tight_cuts(rows, 5, problems)
    messages = [item['message'] for item in problems.items]
    expected = [('the start of this line at 0:01.00', "'before'", "'alpha'"),
                ('a cut inside the line at 0:02.00', "'alpha'", "'bravo'"),
                ('the end of this line at 0:04.00', "'bravo'", "'after'")]
    ok = len(messages) == 3 and all(all(part in msg for part in parts)
                                    for msg, parts in zip(messages, expected))
    record('cut: tight and unmeasured warnings name each edge and adjacent words', ok, str(messages))


def polish_contiguous_audio_case(record, j, scripts_dir):
    """Compare decoded audio across a contiguous split with the same unsplit source passage."""
    root = Path(j('polish-continuous-audio'))
    (root / 'map').mkdir(parents=True, exist_ok=True)
    source = root / 'source.wav'
    times = np.arange(RATE * 2) / RATE
    write_wav(source, .3 * np.sin(2 * np.pi * 431 * times))
    row = source_row('int_01', 'interview', 'source.wav', 2, audio=True, video=False)
    row['audio']['index'] = 0
    (root / 'map' / 'sources.json').write_text(json.dumps({'sources': [row]}), encoding='utf-8')
    write_words(root, 'int_01', [('alpha', .1, .5), ('bravo', 1.3, 1.7)])
    cut_spec = importlib.util.spec_from_file_location('polish_audio_cut', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(cut_spec)
    cut_spec.loader.exec_module(cut)
    assemble_spec = importlib.util.spec_from_file_location('polish_audio_assemble', Path(scripts_dir) / 'assemble.py')
    assemble = importlib.util.module_from_spec(assemble_spec)
    assemble_spec.loader.exec_module(assemble)
    header = '---\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
    films = [header + '> int_01 0:00.00-0:02.00 alpha bravo\n',
             header + '> int_01 0:00.00-0:00.80 alpha\n> int_01 0:00.80-0:02.00 bravo\n']
    decoded = []
    for index, film in enumerate(films):
        (root / 'film.md').write_text(film, encoding='utf-8')
        _, _, _, plan, problems, _ = cut.analyse(root, measure=False)
        folder = root / ('audio-' + str(index))
        temp = folder / 'temp'
        temp.mkdir(parents=True)
        edit = {'audio': plan['audio'], 'sources': {'int_01': {'file': str(source), 'audio_stream': 0}}}
        assemble.render_audio('ffmpeg', 'ffprobe', edit, root, [], plan['duration'], temp, folder, [])
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder / 'dialogue.wav'), '-f', 'f32le',
                                 '-ac', '2', '-ar', str(RATE), '-'], capture_output=True, check=True)
        decoded.append(np.frombuffer(result.stdout, dtype='<f4').reshape(-1, 2))
    center = int(.8 * RATE)
    first, second = (audio[center - 1200:center + 1200] for audio in decoded)
    difference = float(np.max(np.abs(first - second))) if first.shape == second.shape else float('inf')
    record('cut: decoded continuous split matches unsplit audio around the boundary',
           difference < 1e-5, f'max absolute sample difference={difference:.8f}')
