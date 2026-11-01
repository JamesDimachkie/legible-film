"""Known-answer cases for the shared output guard: no script writes a report or output over a file it reads.

Each case names one of a script's inputs as an output (a --json report, an --out file, an output folder whose
generated files would replace an input, or a default path derived from an input). The script must exit 2 before it
writes anything, say which output is which input, and leave every input byte-for-byte unchanged. A few cases spell the
path another way (./sub/../x, a case difference where the file system ignores case) or use a hard link.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def make_media(folder):
    """A one-second 160x90 clip with sound, a one-second tone, two frames and small JSON inputs; their paths."""
    folder.mkdir(parents=True, exist_ok=True)
    clip, tone, base = folder / 'clip.mp4', folder / 'tone.wav', folder / 'base.mp4'
    frame_a, frame_b = folder / 'a.png', folder / 'b.png'
    ffmpeg = ['ffmpeg', '-v', 'error', '-nostdin', '-y']
    subprocess.run(ffmpeg + ['-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=1', '-f', 'lavfi',
                             '-i', 'sine=frequency=440:duration=1:sample_rate=48000', '-c:v', 'libx264',
                             '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(clip)], check=True)
    shutil.copyfile(clip, base)
    subprocess.run(ffmpeg + ['-f', 'lavfi', '-i', 'sine=frequency=330:duration=1:sample_rate=48000', '-ac', '2',
                             str(tone)], check=True)
    for path, start in ((frame_a, 0), (frame_b, 0.5)):
        subprocess.run(ffmpeg + ['-ss', str(start), '-i', str(clip), '-frames:v', '1', str(path)], check=True)
    cues = folder / 'cues.json'
    cues.write_text(json.dumps({'fps': 10, 'events': [{'id': 'c1', 't': 0.2, 'role': 'tick'}]}), encoding='utf-8')
    shutil.copyfile(cues, folder / 'cues.spotted.json')
    shutil.copyfile(tone, folder / 'music.wav')
    (folder / 'palette.json').write_text(json.dumps({'version': 2, 'roles': {}, 'music': {'file': 'music.wav'}}),
                                         encoding='utf-8')
    (folder / 'edit.json').write_text(json.dumps({'version': 1, 'size': [160, 90], 'fps': 10,
                                                  'sources': {'a': 'clip.mp4'},
                                                  'picture': [{'src': 'a', 'in': 0, 'out': 1}]}), encoding='utf-8')
    (folder / 'cuts.json').write_text('{"cuts": []}', encoding='utf-8')
    (folder / 'clip.scorecard.json').write_text('[]', encoding='utf-8')
    (folder / 'library.json').write_text(json.dumps({'version': 1, 'root': 'lib', 'files': []}), encoding='utf-8')
    (folder / 'lib').mkdir(exist_ok=True)
    shutil.copyfile(tone, folder / 'lib' / 'tick.wav')
    (folder / 'licences.csv').write_text('path,licence\n*.wav,CC0 1.0\n', encoding='utf-8')
    (folder / 'strips').mkdir(exist_ok=True)
    shutil.copyfile(clip, folder / 'strips' / 'strip-01.jpg')
    film = folder / 'film'
    film.mkdir(exist_ok=True)
    (film / 'index.html').write_text('<!doctype html><title>case</title>\n', encoding='utf-8')
    (film / 'film.js').write_text('window.FILM = {size: [160, 90], fps: 10};\n', encoding='utf-8')
    started = folder / 'started'
    started.mkdir(exist_ok=True)
    (started / 'film.js').write_text('// my film\n', encoding='utf-8')


def cases(f):
    """(script, arguments, the input the output names, other inputs, files that must not appear)."""
    clip, tone = f / 'clip.mp4', f / 'tone.wav'
    return [
        ('assemble.py', [f / 'edit.json', '--out', clip], clip, [f / 'edit.json'], []),
        ('blank_scan.py', [clip, '--json', clip], clip, [], []),
        ('compare_versions.py', [clip, f / 'base.mp4', '--json', f / 'base.mp4'], f / 'base.mp4', [clip], []),
        ('film_check.py', [f / 'film', '--json', f / 'film' / 'film.js'], f / 'film' / 'film.js',
         [f / 'film' / 'index.html'], []),
        ('flash_scan.py', [clip, '--json', clip], clip, [], []),
        ('frame_sheet.py', [clip, '--every', 0.5, '--out', clip], clip, [], []),
        ('grade.py', ['--file', clip, '--words', f / 'clip.scorecard.json'], f / 'clip.scorecard.json', [clip], []),
        ('grade.py', ['merge', f / 'clip.scorecard.json', '--file', clip], f / 'clip.scorecard.json', [clip], []),
        ('make_film.py', [f / 'film', '--json', f / 'film' / 'film.js'], f / 'film' / 'film.js',
         [f / 'film' / 'index.html'], []),
        ('mix_cues.py', [f / 'cues.json', f / 'palette.json', '--out-dir', f], f / 'music.wav',
         [f / 'cues.json', f / 'palette.json'], [f / 'mix.wav']),
        ('motion_blur.py', [clip, '--out', f / 'blurred.mp4', '--fps', 10, '--cuts-json', f / 'cuts.json',
                            '--json', f / 'cuts.json'], f / 'cuts.json', [clip], [f / 'blurred.mp4']),
        ('motion_scan.py', [clip, '--csv', clip], clip, [], []),
        ('new_film.py', [f / 'started', '--json', f / 'started' / 'film.js'], f / 'started' / 'film.js', [],
         [f / 'started' / 'index.html']),
        ('onion_frames.py', ['--out', f / 'a.png', f / 'a.png', f / 'b.png'], f / 'a.png', [f / 'b.png'], []),
        ('qc_file.py', [clip, '--json', clip], clip, [], []),
        ('reframe.py', [clip, '--aspect', '9:16', '--auto', '--sheet', clip, '--out', f / 'path.json'], clip, [],
         [f / 'path.json']),
        ('region_check.py', [clip, '--region', '0,0,16,16', '--interval', '0-0.5', '--reference-time', 0.1,
                             '--json', clip], clip, [], []),
        ('sound_check.py', [tone, '--palette', f / 'palette.json', '--json', f / 'palette.json'],
         f / 'palette.json', [tone], []),
        ('sound_library.py', ['index', f / 'lib', '--licences', f / 'licences.csv', '--json', f / 'licences.csv'],
         f / 'licences.csv', [f / 'lib' / 'tick.wav'], [f / 'lib' / 'library.json']),
        ('sound_library.py', ['pick', f / 'cues.json', f / 'library.json', '--out', f / 'library.json'],
         f / 'library.json', [f / 'cues.json'], []),
        ('spot_cues.py', [f / 'cues.spotted.json'], f / 'cues.spotted.json', [], [f / 'spotting.csv']),
        ('strip.py', ['--video', f / 'strips' / 'strip-01.jpg', '--out', f / 'strips'], f / 'strips' / 'strip-01.jpg',
         [], [f / 'strips' / 'strip.json']),
        ('sync_check.py', [clip, tone, '--json', tone], tone, [clip], []),
        ('tempo_map.py', [tone, '--json', tone], tone, [], []),
        ('voice_clean.py', [tone, '--out', f / 'clean.wav', '--json', tone], tone, [], [f / 'clean.wav']),
    ]


def digest(path):
    """The SHA-256 of a file, or None when it is missing."""
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def refused(tool, script, args, named, others, absent):
    """Run one case: (passed, detail). Passing means exit 2, a message naming the input, and nothing changed."""
    watched = [named] + list(others)
    before = [digest(path) for path in watched]
    code, output = tool(script, *args)
    after = [digest(path) for path in watched]
    message = 'is the input' in output and Path(named).name in output
    unchanged = before == after and None not in before
    created = [str(path) for path in absent if Path(path).exists()]
    ok = code == 2 and message and unchanged and not created
    return ok, f'exit {code}; message {message}; unchanged {unchanged}; created {created}; {output.strip()[-300:]}'


def spelling_cases(tool, record, f):
    """Another spelling of the input, a case difference and a hard link are refused like the plain path."""
    clip, tone = f / 'clip.mp4', f / 'tone.wav'
    dotted = str(f / 'sub' / '..' / '.' / 'clip.mp4')
    ok, detail = refused(tool, 'qc_file.py', [clip, '--json', dotted], clip, [], [])
    record('outputs: qc_file.py refuses ./sub/../clip.mp4 as the report for clip.mp4', ok, detail)
    upper = f / 'CLIP.MP4'
    if upper.exists():
        ok, detail = refused(tool, 'blank_scan.py', [clip, '--json', upper], clip, [], [])
        record('outputs: blank_scan.py refuses CLIP.MP4 as the report where the file system ignores case', ok, detail)
    links = [(tone, f / 'tone-link.wav', 'sound_check.py', [tone, '--json', f / 'tone-link.wav'], tone),
             (clip, f / 'clip-link.mp4', 'frame_sheet.py', [clip, '--every', 0.5, '--out', f / 'clip-link.mp4'],
              clip)]
    for source, link, script, args, named in links:
        try:
            os.link(source, link)
        except (OSError, NotImplementedError, AttributeError):
            continue
        ok, detail = refused(tool, script, args, named, [], [])
        record(f'outputs: {script} refuses a hard link to its input as an output', ok, detail)
    ok, detail = refused(tool, 'spot_cues.py', [f / 'cues.json', '--out-dir', f / 'sub' / '..', '--json',
                                                f / 'cues.json'], f / 'cues.json', [], [])
    record('outputs: spot_cues.py refuses its cue list as the --json report', ok, detail)


def control_cases(tool, record, f):
    """A report beside the input, not over it, is still written."""
    report = f / 'qc-report.json'
    code, output = tool('qc_file.py', f / 'clip.mp4', '--json', report)
    record('outputs: qc_file.py still writes a report that names no input', code in (0, 1) and report.is_file(),
           f'exit {code}; {output.strip()[-200:]}')
    report = f / 'tempo.json'
    code, output = tool('tempo_map.py', f / 'tone.wav', '--json', report)
    record('outputs: tempo_map.py still writes a report that names no input', code in (0, 1) and report.is_file(),
           f'exit {code}; {output.strip()[-200:]}')


def run_outputs_cases(tool, record, j, scripts_dir):
    """One refusal per script that reads and writes files, plus spellings, hard links and controls."""
    run_fix2_output_cases(tool, record, j)
    folder = Path(j('outputs-case'))
    make_media(folder)
    for script, args, named, others, absent in cases(folder):
        ok, detail = refused(tool, script, args, named, others, absent)
        label = script + (f' {args[0]}' if str(args[0]) in ('merge', 'index', 'pick') else '')
        record(f'outputs: {label} refuses {Path(named).name} as an output', ok, detail)
    spelling_cases(tool, record, folder)
    control_cases(tool, record, folder)
    selftest_destination_cases(tool, record, folder)


def selftest_destination_cases(tool, record, folder):
    """selftest.py writes its report only to a new file or over an earlier report, and keeps files only in a new or
    empty folder."""
    victim = folder / 'precious.mp4'
    victim.write_bytes(b'not a report')
    code, output = tool('selftest.py', '--quick', '--no-cache', '--json', victim)
    report = folder / 'selftest-report.json'
    first, _ = tool('selftest.py', '--quick', '--no-cache', '--json', report)
    again, _ = tool('selftest.py', '--quick', '--no-cache', '--json', report)
    busy = folder / 'busy'
    busy.mkdir(exist_ok=True)
    (busy / 'keep.txt').write_text('mine', encoding='utf-8')
    keep_code, keep_output = tool('selftest.py', '--quick', '--no-cache', '--keep', busy)
    record('outputs: selftest.py never writes its report over another file, or its files into a full folder',
           code == 2 and victim.read_bytes() == b'not a report' and first == 0 and again == 0
           and keep_code == 2 and (busy / 'keep.txt').read_text(encoding='utf-8') == 'mine',
           f'{code} {first} {again} {keep_code}: {output[-200:]} {keep_output[-200:]}')


def run_fix2_output_cases(tool, record, j):
    """A palette's music, voice and role takes remain inputs even when preflight fails."""
    folder = Path(j('fix2-palette'))
    folder.mkdir(parents=True, exist_ok=True)
    film = folder / 'film'
    film.mkdir(exist_ok=True)
    (film / 'index.html').write_text('<title>fixture</title>', encoding='utf-8')
    music, voice, take = (folder / name for name in ('music.wav', 'voice.wav', 'take.wav'))
    for path in (music, voice, take):
        path.write_bytes(b'synthetic sound input')
    palette = folder / 'palette.json'
    contents = {'version': 2, 'music': {'file': 'music.wav'}, 'voice': [{'file': 'voice.wav'}],
                'roles': {'tick': {'takes': ['take.wav']}}}
    palette.write_text(json.dumps(contents), encoding='utf-8')
    for label, path in (('music', music), ('voice', voice), ('take', take)):
        before = path.read_bytes()
        code, output = tool('make_film.py', film, '--sound', palette, '--doctor', '--ffmpeg',
                            folder / 'not-ffmpeg', '--json', path)
        unchanged = path.read_bytes() == before
        record(f'fix2-11: make refuses a report over palette {label}',
               code == 2 and unchanged and 'is the input' in output,
               f'exit {code}; unchanged {unchanged}; {output[-250:]}')
        path.write_bytes(before)
    contents['music']['file'] = '../music.wav'
    (film / 'palette.json').write_text(json.dumps(contents), encoding='utf-8')
    before = music.read_bytes()
    code, output = tool('make_film.py', film, '--doctor', '--ffmpeg', folder / 'not-ffmpeg', '--json', music)
    unchanged = music.read_bytes() == before
    record('fix2-11: make guards media named by the film default palette',
           code == 2 and unchanged and 'is the input' in output,
           f'exit {code}; unchanged {unchanged}; {output[-250:]}')
