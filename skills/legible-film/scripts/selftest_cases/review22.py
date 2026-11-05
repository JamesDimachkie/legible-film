"""Known-answer cases for what an independent review of 2.2 found: sound comparisons that half match, the track a player
really plays, line-ups and speaker labels kept past what they were measured on, near silence, a missing tail of a few
frames, and an explicitly required empty caption file.

The speech is the first-cut example (Tears of Steel, CC BY). Without the example these print a SKIP line.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def load(scripts_dir, name):
    spec = importlib.util.spec_from_file_location('review22_' + name, os.path.join(scripts_dir, name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ffmpeg(*args):
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-nostdin', *map(str, args)], check=True, stdin=subprocess.DEVNULL,
                   timeout=300)


def script(scripts_dir, name, *args):
    done = subprocess.run([sys.executable, '-I', os.path.join(scripts_dir, name + '.py'), *map(str, args)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    return done.returncode, done.stdout + done.stderr


def state_of(output, label):
    """The printed state of a check item: ok, LOOK, FAIL, skip, you, or None when it is not listed."""
    found = re.search(r'^\s*(ok|LOOK|FAIL|skip|you)\s+(?:Not assessed: )?' + re.escape(label), output,
                      re.MULTILINE | re.IGNORECASE)
    return found.group(1) if found else None


def check_mixed_sound(record, j, scripts_dir, example):
    """Half the output is the source and half is other sound: never a pass."""
    root = Path(j('review22-mixed'))
    root.mkdir(parents=True, exist_ok=True)
    mixed = root / 'mixed.wav'
    ffmpeg('-i', example, '-f', 'lavfi', '-t', 12, '-i', 'anoisesrc=a=0.3:r=48000:seed=7', '-filter_complex',
           '[0:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:11.25,asetpts=N/SR/TB[a];'
           '[1:a]aformat=channel_layouts=stereo[n];[a][n]concat=n=2:v=0:a=1[out]', '-map', '[out]',
           mixed)
    _, output = script(scripts_dir, 'check', '--file', mixed, '--against', example, '--edit', 'extract-audio')
    state = state_of(output, 'Sound content')
    record('review22: half the sound from elsewhere is not called the same', state in ('LOOK', 'FAIL'), output[-500:])
    right = root / 'right.wav'
    ffmpeg('-i', example, '-vn', '-ar', 48000, '-ac', 2, right)
    _, output = script(scripts_dir, 'check', '--file', right, '--against', example, '--edit', 'extract-audio')
    record('review22: the source\'s own sound still passes', state_of(output, 'Sound content') == 'ok', output[-500:])


def check_played_track(record, j, scripts_dir, example):
    """A trim whose first track matches but whose default track, the one a player plays, is other sound."""
    root = Path(j('review22-track'))
    root.mkdir(parents=True, exist_ok=True)
    trim = root / 'trim.mp4'
    ffmpeg('-ss', 2, '-t', 6, '-i', example, '-f', 'lavfi', '-t', 6, '-i', 'anoisesrc=a=0.3:r=48000:seed=9',
           '-map', '0:v', '-map', '0:a', '-map', '1:a', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
           '-disposition:a:0', '0', '-disposition:a:1', 'default', trim)
    _, output = script(scripts_dir, 'check', '--file', trim, '--against', example, '--edit', 'trim:2,8')
    record('review22: a trim is compared on the track a player plays',
           state_of(output, 'Trim audio content offset') != 'ok', output[-600:])


def check_caption_remux(record, j, scripts_dir):
    """A remux to Matroska moves every stream together on some FFmpeg versions; only moving one is a change."""
    root = Path(j('review22-remux'))
    root.mkdir(parents=True, exist_ok=True)
    source, same, moved = root / 'source.mp4', root / 'same.mkv', root / 'moved.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=d=2:s=320x180:r=24', '-f', 'lavfi', '-i', 'sine=f=440:d=2', '-c:v', 'libx264',
           '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', source)
    ffmpeg('-i', source, '-c', 'copy', same)
    ffmpeg('-i', source, '-itsoffset', .2, '-i', source, '-map', '0:v', '-map', '1:a', '-c', 'copy', moved)
    _, output = script(scripts_dir, 'check', '--file', same, '--against', source, '--edit', 'captions')
    record('review22: a captions remux that moves every stream together keeps its content',
           state_of(output, 'Edit video content') == 'ok' and state_of(output, 'Edit audio content') == 'ok',
           output[-500:])
    _, output = script(scripts_dir, 'check', '--file', moved, '--against', source, '--edit', 'captions')
    record('review22: sound moved against the picture is never called unchanged',
           state_of(output, 'Edit audio content') in ('FAIL', 'skip'), output[-500:])


def lined_up_project(j, scripts_dir, example, name):
    """A camera with two sound streams, the second a second later, and two mics that start 0.7 s into the talk."""
    root = Path(j(name))
    media = Path(j(name + '-media'))
    media.mkdir(parents=True, exist_ok=True)
    camera = media / 'cam.mkv'
    ffmpeg('-i', example, '-itsoffset', 1, '-i', example, '-map', '0:v', '-map', '0:a', '-map', '1:a',
           '-c:v', 'copy', '-c:a', 'aac', camera)
    mics = []
    for number, gain in ((1, -3), (2, -9)):
        mic = media / f'mic{number}.wav'
        ffmpeg('-ss', .7, '-i', example, '-vn', '-af', f'volume={gain}dB,aresample=44100', mic)
        mics.append(mic)
    film = media / 'film.md'
    film.write_text('---\ntitle: T\nsize: 320x134\nfps: 24\ncaptions: none\n---\n\n## A\n'
                    '- cam_01 0:02.00-0:04.00 sound Start\n', encoding='utf-8')
    script(scripts_dir, 'project', 'init', root, '--title', 'T', '--film', film)
    script(scripts_dir, 'map', 'add', root, camera, '--role', 'camera')
    for mic in mics:
        script(scripts_dir, 'map', 'add', root, mic, '--role', 'mic')
    script(scripts_dir, 'map', 'run', root, '--words', 'skip')
    return root


def check_reference_stream(record, j, scripts_dir, example):
    """The reference's sound stream changes and one mic is lined up again: the other mic's old row must not survive."""
    root = lined_up_project(j, scripts_dir, example, 'review22-stream')
    lineup = load(scripts_dir, 'lineup')
    lineup.sync_project(root, 'cam_01', None)
    rows = lineup.registered(root)
    streams = (rows['cam_01'].get('audio_streams') or {}).get('streams') or []
    current = rows['cam_01']['audio']['index']
    other = next((row['index'] for row in streams if row['index'] != current), current + 1)
    script(scripts_dir, 'map', 'run', root, '--alias', 'cam_01', '--stream', other, '--words', 'skip')
    lineup.sync_project(root, 'cam_01', ['mic_01'])
    reason = lineup.Lineup(root).problem('mic_02')
    record('review22: a line-up measured against another reference stream is not kept', bool(reason), repr(reason))


def check_relative_drift(record, j, scripts_dir, example):
    """A camera drifts against a reference mic: the mic has no drift of its own, and the line must still say so."""
    root = lined_up_project(j, scripts_dir, example, 'review22-drift')
    lineup = load(scripts_dir, 'lineup')
    lineup.sync_project(root, 'mic_01', None)
    path = root / 'map' / 'sync.json'
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['sources']['cam_01']['drift_s'] = 0.2
    path.write_text(json.dumps(saved), encoding='utf-8')
    code, output = script(scripts_dir, 'map', 'sync', root, '--check')
    record('review22: sync --check does not exit clean over a drift it prints', code == 1 and 'DRIFT' in output,
           f'{code} {output[-300:]}')
    film = root / 'film.md'
    film.write_text(film.read_text(encoding='utf-8').replace('- cam_01 0:02.00-0:04.00 sound Start',
                                                             '- cam_01 0:02.00-0:04.00 Start {sound mic_01}'),
                    encoding='utf-8')
    _, output = script(scripts_dir, 'cut', 'check', root)
    record('review22: a drifting camera over a reference mic is named', 'cam_01 drifts' in output, output[-400:])


def check_stale_labels(record, j, scripts_dir, example, words):
    """Speaker labels measured from the mics, then a mic's offset is changed by hand."""
    root = lined_up_project(j, scripts_dir, example, 'review22-labels')
    script(scripts_dir, 'map', 'run', root, '--alias', 'cam_01', '--words', 'import:' + str(words), '--rebuild')
    lineup = load(scripts_dir, 'lineup')
    lineup.sync_project(root, 'cam_01', None)
    code, output = script(scripts_dir, 'map', 'speakers', root, 'cam_01', '--mic', 'mic_01=Ana', '--mic', 'mic_02=Ben')
    if code not in (0, 1):
        record('review22: speaker labels could be made for the staleness case', False, output[-400:])
        return
    _, before = script(scripts_dir, 'map', 'sync', root, '--check')
    script(scripts_dir, 'map', 'sync', root, '--set', 'mic_01=2.5', '--note', 'test')
    code, after = script(scripts_dir, 'map', 'sync', root, '--check')
    record('review22: speaker labels are named stale when their mic moves',
           'stale' not in before.replace('stale: ', '') and 'speaker labels' in after and code == 1, after[-400:])


def check_small_helpers(record, j, scripts_dir):
    project = load(scripts_dir, 'project')
    quiet = project.stream_is_silent({'peak_db': -80.77})
    silent = project.stream_is_silent({'peak_db': -91.0})
    record('review22: three least-significant bits are quiet, not digital silence', not quiet and silent,
           f'{quiet} {silent}')

    root = Path(j('review22-required'))
    root.mkdir(parents=True, exist_ok=True)
    video = root / 'silent.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=d=2:s=320x180:r=24', '-c:v', 'libx264', '-preset', 'ultrafast',
           '-pix_fmt', 'yuv420p', video)
    (root / 'empty.srt').write_text('', encoding='utf-8')
    (root / 'delivery.json').write_text(json.dumps({'captions_required': True}), encoding='utf-8')
    _, output = script(scripts_dir, 'check', '--file', video, '--captions', root / 'empty.srt', '--delivery',
                       root / 'delivery.json')
    record('review22: an empty caption file fails when captions are required, sound or none',
           state_of(output, 'Captions required') == 'FAIL', output[-500:])

    # A few frames short of the header, inside the slack: the render may hold them, and must say so.
    clip = root / 'short.mov'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=d=2:s=320x180:r=30', '-c:v', 'mjpeg', '-q:v', 3, '-movflags', '+faststart', clip)
    data = clip.read_bytes()
    clip.write_bytes(data[:len(data) - round(2.2 * len(data) / 60)])
    film = root / 'film.md'
    film.write_text('---\ntitle: T\nsize: 320x180\nfps: 30\ncaptions: none\n---\n\n## A\n'
                    '- src_01 0:00.00-0:02.00 All of it\n', encoding='utf-8')
    project_root = root / 'P'
    script(scripts_dir, 'project', 'init', project_root, '--title', 'T', '--film', film)
    script(scripts_dir, 'map', 'add', project_root, clip, '--role', 'other')
    script(scripts_dir, 'map', 'run', project_root, '--alias', 'src_01', '--words', 'skip')
    code, output = script(scripts_dir, 'cut', 'render', project_root)
    report = project_root / 'cuts' / 'v001' / 'assemble-report.json'
    notes = report.read_text(encoding='utf-8') if report.is_file() else ''
    record('review22: a held tail inside the slack is said, not silent',
           'last frame' in output + notes or code == 2, f'{code} {output[-300:]}')

    setup = load(scripts_dir, 'setup')
    saved = setup.sys.prefix, setup.sys.base_prefix, setup.dedicated_python, setup.has_pip, setup.imports_core
    try:
        setup.sys.prefix, setup.sys.base_prefix = 'active-venv', 'base-python'
        setup.dedicated_python = lambda: Path(sys.executable)
        setup.has_pip = lambda python: True
        setup.imports_core = lambda python: True
        other = Path(j('review22-dedicated-python'))
        other.write_text('', encoding='utf-8')
        setup.dedicated_python = lambda: other
        chosen = setup.selected_python(create=True)
    finally:
        setup.sys.prefix, setup.sys.base_prefix, setup.dedicated_python, setup.has_pip, setup.imports_core = saved
    record('review22: an active environment comes before the per-user one, as the docs say',
           str(chosen) == sys.executable, str(chosen))
    run = setup.subprocess.run

    def failing(*args, **kwargs):
        raise setup.subprocess.CalledProcessError(1, 'pip')
    try:
        setup.subprocess.run = failing
        try:
            setup.pip_install(sys.executable, ['nothing'])
            message = ''
        except ValueError as error:
            message = str(error)
    finally:
        setup.subprocess.run = run
    record('review22: a Python with no tested build is told which ones have one', 'Python 3.9' in message, message)


def run_review22_cases(tool, record, j, scripts_dir):
    """What an independent review of 2.2 found."""
    check_small_helpers(record, j, scripts_dir)
    check_caption_remux(record, j, scripts_dir)
    examples = Path(scripts_dir).resolve().parents[2] / 'examples' / 'first-cut'
    example, words = examples / 'tears-of-steel-bridge.mp4', examples / 'tears-of-steel-bridge.words.json'
    if not example.is_file():
        print('SKIP  review22: the first-cut example is not here (it is in a clone, not an installed copy)')
        return
    check_mixed_sound(record, j, scripts_dir, example)
    check_played_track(record, j, scripts_dir, example)
    check_reference_stream(record, j, scripts_dir, example)
    check_relative_drift(record, j, scripts_dir, example)
    check_stale_labels(record, j, scripts_dir, example, words)
