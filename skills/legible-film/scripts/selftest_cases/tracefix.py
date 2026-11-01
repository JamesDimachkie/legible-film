"""Known-answer regressions for the tracefix tools."""

import contextlib
import bisect
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import wave
from fractions import Fraction
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image


def write_wav(path, data, rate):
    """Write a mono PCM fixture without another tool."""
    samples = (np.clip(data, -1, 1) * 32767).astype('<i2')
    with wave.open(path, 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        wav.writeframes(samples.tobytes())


def make_frame_fixture(path, kind):
    """Make a small deterministic source with actual changes in picture and presentation time."""
    ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'ffmpeg'
    command = [ffmpeg, '-v', 'error', '-y']
    if kind in ('offset', 'aac-offset', 'precision'):
        offset = '480' if kind == 'precision' else '2'
        rate = '30' if kind == 'precision' else '10'
        audio = 'aac' if kind == 'aac-offset' else 'pcm_s16le'
        command += ['-f', 'lavfi', '-i', 'anullsrc=channel_layout=mono:sample_rate=8000:duration=1',
                    '-itsoffset', offset, '-f', 'lavfi', '-i', f'testsrc2=s=128x72:r={rate}:d=2',
                    '-map', '1:v', '-map', '0:a', '-c:a', audio]
    else:
        command += ['-f', 'lavfi', '-i', 'testsrc2=s=128x72:r=10:d=3']
        if kind == 'vfr':
            expression = "settb=1/1000,setpts='if(lt(N,10),N*100+floor(N/3)*65,9000+(N-10)*170)'"
            command += ['-vf', expression, '-enc_time_base', '1/1000']
    command += ['-fps_mode', 'passthrough', '-c:v', 'libx264', '-g', '30', '-threads', '1',
                '-pix_fmt', 'yuv420p', str(path)]
    subprocess.run(command, check=True, capture_output=True)


def fixture_clock(path):
    """Independently read frame ticks on the FFmpeg-normalized file clock."""
    ffprobe = os.environ.get('FFPROBE') or shutil.which('ffprobe') or 'ffprobe'
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_frames', '-show_entries',
               'frame=best_effort_timestamp:stream=time_base:format=start_time', '-of', 'json', str(path)]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    probe = json.loads(result.stdout)
    start = Fraction(probe['format']['start_time'])
    tick = Fraction(probe['streams'][0]['time_base'])
    return [int(frame['best_effort_timestamp']) * tick - start for frame in probe['frames']]


def sheet_pixels(folder, windowed):
    """Read retained pictures in sheet order, using only filenames written by the current call."""
    def order(path):
        pattern = r'^frame-tile-(\d+)-at-' if windowed else r'^frame-(\d+)-at-'
        match = re.search(pattern, path.name)
        return int(match.group(1)) if match else -1

    paths = sorted(folder.glob('frame-*.png'), key=order)
    if any(order(path) < 0 for path in paths):
        raise ValueError('unexpected retained-frame filename')
    return [Image.open(path).tobytes() for path in paths], paths


def check_window(tool, j, source, name, clock, mode, argument, times):
    """Compare selected full-resolution pixels with the whole-file index path."""
    full_dir = Path(j(name + '-whole'))
    part_dir = Path(j(name + '-window'))
    full_code, full_out = tool('frame_sheet.py', source, '--frames', f'0-{len(clock) - 1}', '--width', '96',
                               '--keep-frames', full_dir, '--out', j(name + '-whole.png'))
    part_code, part_out = tool('frame_sheet.py', source, mode + '=' + argument, '--width', '96',
                               '--keep-frames', part_dir, '--out', j(name + '-window.png'))
    full, _ = sheet_pixels(full_dir, False) if full_dir.exists() else ([], [])
    selected, names = sheet_pixels(part_dir, True) if part_dir.exists() else ([], [])
    indices = sorted({min(max(bisect.bisect_right(clock, time) - 1, 0), len(clock) - 1) for time in times})
    expected = [full[index] for index in indices] if len(full) == len(clock) else []
    ok = full_code == 0 and part_code == 0 and bool(expected) and selected == expected
    detail = f'expected indices={indices}; got={len(selected)}; {full_out[-150:]} {part_out[-150:]}'
    return ok, detail, names


def frame_sheet_cases(tool, record, j, scripts_dir):
    """Check windowed pixels, endpoints, sparse gaps, timestamp precision and truthful labels."""
    fixtures = {}
    for kind in ('cfr', 'vfr', 'offset', 'aac-offset', 'precision'):
        extension = '.mov' if kind == 'precision' else '.mkv'
        source = Path(j('trace-' + kind + extension))
        make_frame_fixture(source, kind)
        fixtures[kind] = (source, fixture_clock(source))

    cfr, clock = fixtures['cfr']
    record('tracefix: CFR fixture has known 0.1-second presentation steps',
           clock == [Fraction(i, 10) for i in range(30)], str(clock[:5]))
    at = ['-1', '0', '0.1', '0.15', '1', '2.9', '3', '20']
    ok, detail, names = check_window(tool, j, cfr, 'trace-cfr-at', clock, '--at', ','.join(at),
                                     [Fraction(value) for value in at])
    record('tracefix: CFR at endpoints, between frames, before zero and past end matches whole pixels', ok, detail)
    record('tracefix: window filenames describe tile order without a guessed frame index',
           bool(names) and all(re.fullmatch(r'frame-tile-\d+-at-.+\.png', path.name) for path in names), str(names))
    around = [Fraction(1, 5) + Fraction(k, 20) for k in range(33)]
    ok, detail, _ = check_window(tool, j, cfr, 'trace-cfr-around', clock, '--around', '1', around)
    record('tracefix: CFR around includes its exact first and last frame and matches whole pixels', ok, detail)

    vfr, clock = fixtures['vfr']
    deltas = [b - a for a, b in zip(clock, clock[1:])]
    record('tracefix: VFR fixture has irregular presentation times and a long held frame',
           len(set(deltas)) > 2 and max(deltas) > 2 and clock[0] == 0, str(deltas))
    at = ['0', '0.1', '0.17', '1.3', '5', '8.99', '9', '9.08', '12.23', '100']
    ok, detail, names = check_window(tool, j, vfr, 'trace-vfr-at', clock, '--at', ','.join(at),
                                     [Fraction(value) for value in at])
    record('tracefix: VFR at seeks back over a long hold and matches whole pixels at boundaries', ok, detail)
    record('tracefix: retained window filenames sort in frame order across time digit boundaries',
           bool(names) and [path.name for path in names] == sorted(path.name for path in names), str(names))
    around = [Fraction(23, 5) + Fraction(k, 20) for k in range(33)]
    ok, detail, _ = check_window(tool, j, vfr, 'trace-vfr-around', clock, '--around', '5.4', around)
    record('tracefix: VFR window entirely inside a long hold returns the held frame', ok, detail)

    offset, clock = fixtures['offset']
    record('tracefix: fixture video starts at two seconds on a zero-start file clock',
           clock[0] == 2 and clock[-1] == Fraction(39, 10), str((clock[0], clock[-1])))
    at = ['0', '1.9', '2', '2.05', '2.1', '3.9', '4', '50']
    ok, detail, _ = check_window(tool, j, offset, 'trace-offset-at', clock, '--at', ','.join(at),
                                 [Fraction(value) for value in at])
    record('tracefix: nonzero first timestamp and out-of-range at points match whole pixels', ok, detail)
    around = [Fraction(7, 5) + Fraction(k, 20) for k in range(33)]
    ok, detail, _ = check_window(tool, j, offset, 'trace-offset-around', clock, '--around', '2.2', around)
    record('tracefix: a window beginning before the first timestamp matches whole pixels', ok, detail)

    shifted, clock = fixtures['aac-offset']
    points = [Fraction(0), clock[0], clock[0] + Fraction(1, 20), clock[1], clock[-1], clock[-1] + 8]
    values = [f'{float(point):.6f}' for point in points]
    ok, detail, _ = check_window(tool, j, shifted, 'trace-aac-offset-at', clock, '--at', ','.join(values), points)
    record('tracefix: delayed video with codec-dependent file start matches the whole-file clock', ok, detail)

    precise, clock = fixtures['precision']
    record('tracefix: high-offset fixture has an exact sub-millisecond frame boundary',
           clock[0] == 480 and clock[1] == Fraction(14401, 30), str(clock[:2]))
    at = ['480.033', '480.033333', '480.033334']
    ok, detail, _ = check_window(tool, j, precise, 'trace-precision-at', clock, '--at', ','.join(at),
                                 [Fraction(value) for value in at])
    record('tracefix: decoded tick, not rounded showinfo time, decides the boundary on both FFmpeg versions',
           ok and [bisect.bisect_right(clock, Fraction(t)) - 1 for t in at] == [0, 0, 1], detail)
    code, out = tool('frame_sheet.py', precise, '--every', '480.033', '--single', '--out', j('trace-precise.png'))
    names = list(Path(j('')).glob('trace-precise-frame-*.png'))
    record('tracefix: whole-file time sampling also uses exact ticks at the precision boundary',
           code == 0 and len(names) == 1 and 'frame-000000-' in names[0].name, out)

    spec = importlib.util.spec_from_file_location('trace_frame_sheet', os.path.join(scripts_dir, 'frame_sheet.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class CountingFrames(io.BytesIO):
        """Record how many raw pictures have been read from a fake decoder."""

        def __init__(self):
            super().__init__(b'\0' * 48)
            self.reads = 0

        def read(self, size=-1):
            self.reads += 1
            return super().read(size)

    class FakeDecoder:
        """Report four known presentation times while serving four tiny RGB pictures."""

        def __init__(self):
            self.stdout = CountingFrames()
            lines = ['[showinfo] config in time_base: 1/1']
            lines += [f'[showinfo] n: {n} pts: {n} pts_time:{n}' for n in range(4)]
            self.stderr = io.BytesIO(('\n'.join(lines) + '\n').encode('ascii'))
            self.returncode = 0

        def poll(self):
            return self.returncode

        def wait(self):
            return self.returncode

    decoder = FakeDecoder()
    accepted = []

    def accept_frame(frame):
        accepted.append((frame[1], decoder.stdout.reads))

    with patch.object(module.subprocess, 'Popen', return_value=decoder):
        with patch.object(module, 'passthrough', return_value=[]):
            completed = module.read_window('ffmpeg', 'fixture', 0, [Fraction(0), Fraction(1), Fraction(2)], 2, 2,
                                           accept_frame)
    record('tracefix: selected frames are delivered during decoding without retaining the full window',
           completed and accepted == [(Fraction(0), 2), (Fraction(1), 3), (Fraction(2), 4)], str(accepted))

    labels = []
    original_text = module.ImageDraw.ImageDraw.text

    def capture_text(draw, xy, text, *args, **kwargs):
        labels.append(text)
        return original_text(draw, xy, text, *args, **kwargs)

    with patch.object(module.ImageDraw.ImageDraw, 'text', capture_text), contextlib.redirect_stdout(io.StringIO()):
        for args in (['--at', '480.034'], ['--frames', '1-1']):
            with patch.object(sys, 'argv', ['frame_sheet.py', str(precise), *args, '--out', j('trace-label.png')]):
                module.main()
    record('tracefix: rendered labels show decoded rounded time and only known frame numbers',
           labels == ['~480.033333s  frame', '~480.033333s  #1'], str(labels))

    drawn = []

    def capture_narrow(draw, xy, text, *args, **kwargs):
        drawn.append((xy, text, draw.textbbox(xy, text, font=kwargs['font'])))
        return original_text(draw, xy, text, *args, **kwargs)

    narrow = Path(j('trace-narrow.png'))
    args = ['frame_sheet.py', str(precise), '--frames', '0-2', '--width', '40', '--cols', '3', '--out', str(narrow)]
    with patch.object(module.ImageDraw.ImageDraw, 'text', capture_narrow), contextlib.redirect_stdout(io.StringIO()):
        with patch.object(sys, 'argv', args):
            module.main()
    groups = {0: [], 1: [], 2: []}
    inside = True
    label_bottom = Image.open(narrow).height - 28
    for xy, text, bounds in drawn:
        column = (xy[0] - 8) // 46
        if column not in groups:
            inside = False
            continue
        groups[column].append(text)
        inside = inside and bounds[2] <= 6 + 46 * column + 40 and bounds[3] <= label_bottom
    expected = [module.frame_label(i, clock[i]).replace(' ', '') for i in range(3)]
    visible = [''.join(groups[i]).replace(' ', '') for i in range(3)]
    record('tracefix: narrow-tile labels wrap without clipping or crossing into another tile',
           inside and visible == expected, str((visible, expected, drawn)))


def run_tracefix_cases(tool, record, j, scripts_dir):
    """Exercise matching, cache controls, Windows text and bounded output."""
    rate = 48000
    rng = np.random.default_rng(481)
    ref = rng.normal(0, .25, 1200) * np.exp(-np.arange(1200) / 350)
    write_wav(j('trace-ref.wav'), ref, rate)
    bed = rng.normal(0, .012, rate * 3)
    mix = bed.copy()
    start = int(1.04 * rate)
    mix[start:start + len(ref)] += ref
    write_wav(j('trace-mix.wav'), mix, rate)
    cues = {'events': [{'id': 'click', 't': 1.0, 'tolerance_ms': 10,
                        'window_ms': 120, 'ref': 'trace-ref.wav'}]}
    Path(j('trace-cues.json')).write_text(json.dumps(cues), encoding='utf-8')

    def check(audio, *args):
        """Run the cue check and read its one row."""
        code, out = tool('cue_onsets.py', j(audio), j('trace-cues.json'), *args,
                         '--json', j('trace-report.json'))
        row = json.loads(Path(j('trace-report.json')).read_text(encoding='utf-8'))['rows'][0]
        return code, row, out

    code, row, _ = check('trace-mix.wav')
    record('tracefix: reference click in noise retains cue tolerance and finds +40 ms',
           code == 1 and row['status'] == 'LATE' and abs(row['offset_ms'] - 40) < 1
           and row['tolerance_ms'] == 10, str(row))
    dense = bed.copy()
    for pos in (int(.95 * rate), int(1.04 * rate), int(1.10 * rate)):
        dense[pos:pos + len(ref)] += ref
    write_wav(j('trace-dense.wav'), dense, rate)
    code, row, _ = check('trace-dense.wav')
    record('tracefix: repetitive reference overlap is inconclusive with next step',
           code == 1 and row['status'] == 'inconclusive' and bool(row.get('next')), str(row))
    code, row, _ = check('trace-mix.wav', '--expect-absent')
    record('tracefix: old window residual detected and level reported',
           code == 1 and row['status'] == 'RESIDUAL' and 'level_db' in row, str(row))
    write_wav(j('trace-cleared.wav'), np.zeros(rate * 3), rate)
    code, row, _ = check('trace-cleared.wav', '--expect-absent')
    record('tracefix: cleared old window passes', code == 0 and row['status'] == 'quiet as intended', str(row))
    for encoding in ('utf-8-sig', 'utf-16'):
        Path(j('trace-cues.json')).write_text(json.dumps(cues), encoding=encoding)
        code, row, _ = check('trace-mix.wav')
        record('tracefix: cue JSON loads ' + encoding, code == 1 and row['status'] == 'LATE')

    started = time.monotonic()
    code, out = tool('selftest.py', '--quick', '--no-cache')
    elapsed = time.monotonic() - started
    record('tracefix: quick dependency probe under 10 seconds', code == 0 and elapsed < 10, f'{elapsed:.2f} s')
    spec = importlib.util.spec_from_file_location('trace_selftest', os.path.join(scripts_dir, 'selftest.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cache = j('trace-cache.json')
    skips = module.skipped_cases('make', 'skipped: make_film cases need Playwright (missing)\n')
    declared = module.make_case_count()
    record('tracefix: make skip counts every declared make case and gives its reason',
           len(skips) == 1 and skips[0]['count'] == declared and declared > 0 and 'Playwright' in skips[0]['reason'],
           f'{declared} declared')
    fixture = {'environment': module.environment(), 'date': 'fixture', 'result': 'pass',
               'summary': {'passed': 3, 'failed': 0, 'skip_reasons': skips}}
    Path(cache).write_text(json.dumps(fixture), encoding='utf-8')
    report = j('trace-cache-report.json')
    code, out = tool('selftest.py', '--cache', cache, '--json', report)
    cached = json.loads(Path(report).read_text(encoding='utf-8'))
    record('tracefix: cache hit keeps skip counts and reasons visible in text and JSON',
           code == 0 and 'Cached full self-test result' in out and f'{declared} not run' in out.splitlines()[-1]
           and cached['passed'] == 3 and cached['failed'] == 0 and cached['skipped'] == declared
           and 'Playwright' in cached['skip_reasons'][0]['reason'])

    kit_spec = importlib.util.spec_from_file_location('trace_kit', os.path.join(scripts_dir, 'kit_selftest.py'))
    kit = importlib.util.module_from_spec(kit_spec)
    kit_spec.loader.exec_module(kit)
    outcomes = []
    for required in (False, True):
        output = io.StringIO()
        args = ['kit_selftest.py'] + (['--require'] if required else [])
        with patch.object(kit.shutil, 'which', return_value=None), patch.object(sys, 'argv', args):
            with contextlib.redirect_stdout(output):
                result = kit.main()
        outcomes.append(result == (2 if required else 0) and output.getvalue().splitlines()[-1] ==
                        'NOT RUN: Node is missing')
    record('tracefix: kit skip ends NOT RUN and --require exits 2', all(outcomes))

    # Stop at the first suite record: --force must reach it even with a matching cache.
    driver = '''import importlib.util, sys
spec = importlib.util.spec_from_file_location('test_module', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
def reached(*args, **kwargs):
    raise RuntimeError('FORCED_SUITE_REACHED')
m.tool = lambda *args, **kwargs: (0, '')
m.record = reached
sys.argv = [sys.argv[1], '--cache', sys.argv[2], '--force']
try:
    m.main()
except RuntimeError as exc:
    print(str(exc))
'''
    forced = subprocess.run([sys.executable, '-I', '-c', driver, os.path.join(scripts_dir, 'selftest.py'), cache],
                            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=10)
    record('tracefix: force bypasses a matching cache and starts the suite',
           forced.returncode == 0 and 'FORCED_SUITE_REACHED' in forced.stdout)
    good = Path(j('trace-good.mkv'))
    make_frame_fixture(good, 'cfr')
    code, out = tool('frame_sheet.py', good, '--frames', '0-4', '--width', '160', '--cols', '3',
                     '--max-width', '338', '--max-height', '240', '--out', j('trace-sheet.png'))
    paths = [Path(j('trace-sheet.png')), Path(j('trace-sheet-2.png'))]
    sizes = [Image.open(path).size for path in paths if path.exists()]
    record('tracefix: five tiles paginate at unchanged size inside pixel budget',
           code == 0 and len(sizes) == 2 and all(w <= 338 and h <= 240 for w, h in sizes)
           and sizes[0] == (338, 230), str(sizes) + ' ' + out[-100:])
    # One select expression per wanted frame failed on a 12-minute film ("Cannot allocate memory" at 368 frames).
    long_source = Path(j('trace-long.mp4'))
    ffmpeg = os.environ.get('FFMPEG') or shutil.which('ffmpeg') or 'ffmpeg'
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=120',
                    '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', str(long_source)], check=True)
    code, out = tool('frame_sheet.py', long_source, '--every', '0.25', '--width', '40', '--out',
                     j('trace-long-sheet.png'))
    record('tracefix: a sheet of 480 frames from a two-minute source is made in one pass',
           code == 0 and out.startswith('480 frames') and Path(j('trace-long-sheet.png')).exists(), out[-200:])
    code, _ = tool('frame_sheet.py', good, '--frames', '0-1', '--width', '160', '--single',
                   '--out', j('trace-single.png'))
    names = sorted(Path(j('')).glob('trace-single-frame-*.png'))
    record('tracefix: single frames carry timestamp in names',
           code == 0 and len(names) == 2 and '-at-' in names[0].name, str(names))
    frame_sheet_cases(tool, record, j, scripts_dir)
    frame_sheet_word_cases(tool, record, j, scripts_dir)


def frame_sheet_word_cases(tool, record, j, scripts_dir):
    """A sheet labels each tile with the word spoken then, on the words' clock: decoded time plus an offset given in
    seconds or in frames at the video's exact rate."""
    insert = j('trace-insert.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24000/1001',
                    '-t', '2', '-pix_fmt', 'yuv420p', insert], check=True)
    words = {'words': [{'text': 'moving', 'start': 22.5, 'end': 22.9},
                       {'text': 'together', 'start': 23.2, 'end': 23.8}]}
    Path(j('trace-insert-words.json')).write_text(json.dumps(words), encoding='utf-8')
    spec = importlib.util.spec_from_file_location('trace_words_sheet', os.path.join(scripts_dir, 'frame_sheet.py'))
    sheet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sheet)
    rows = sorted((w['start'], w['end'], w['text']) for w in words['words'])
    offset = sheet.parse_offset('538f', Fraction(24000, 1001))
    labels = [sheet.spoken_at(rows, Fraction(t) + offset) for t in ('0.1', '0.6', '1.0', '1.9')]
    record('tracefix: a frame offset converts at the exact NTSC rate and each moment names its word or its gap',
           offset == Fraction(538 * 1001, 24000) and '"moving"' in labels[0] and 'between "moving" and "together"'
           in labels[1] and '"together"' in labels[2] and 'between "together" and end' in labels[3], str(labels))
    code, out = tool('frame_sheet.py', insert, '--at', '0.1,1.0', '--words', j('trace-insert-words.json'),
                     '--offset', '538f', '--out', j('trace-insert-words.png'))
    bad, bad_out = tool('frame_sheet.py', insert, '--at', '0.1', '--words', j('trace-insert-words.json'),
                        '--offset', 'soon', '--out', j('trace-insert-bad.png'))
    Path(j('trace-empty-words.json')).write_text('{"words": []}', encoding='utf-8')
    empty, empty_out = tool('frame_sheet.py', insert, '--at', '0.1', '--words', j('trace-empty-words.json'),
                            '--out', j('trace-insert-empty.png'))
    record('tracefix: --words writes a labelled sheet; a bad offset or words file without words cannot run',
           code == 0 and Path(j('trace-insert-words.png')).is_file() and bad == 2 and 'offset' in bad_out
           and empty == 2 and 'no timed words' in empty_out, out + bad_out + empty_out)
    lone, lone_out = tool('frame_sheet.py', insert, '--at', '0.1', '--offset', '538f', '--out', j('trace-lone.png'))
    single, single_out = tool('frame_sheet.py', insert, '--at', '0.1', '--words', j('trace-insert-words.json'),
                              '--single', '--out', j('trace-single-words.png'))
    record('tracefix: --offset without --words, or --words with --single, is refused instead of silently unlabelled',
           lone == 2 and '--words' in lone_out and single == 2 and '--single' in single_out, lone_out + single_out)
    keep = Path(j('trace-keep'))
    keep.mkdir(exist_ok=True)
    named = keep / 'frame-000000-at-0s.png'
    named.write_text(json.dumps(words), encoding='utf-8')
    before = named.read_bytes()
    kept, kept_out = tool('frame_sheet.py', insert, '--frames', '0-0', '--words', named, '--keep-frames', keep,
                          '--out', j('trace-keep-sheet.png'))
    linked = Path(j('trace-linked-sheet.png'))
    try:
        os.link(j('trace-insert-words.json'), linked)
        link_code, link_out = tool('frame_sheet.py', insert, '--at', '0.1', '--words', j('trace-insert-words.json'),
                                   '--out', linked)
        link_ok = link_code == 2 and json.loads(Path(j('trace-insert-words.json')).read_text(encoding='utf-8'))
    except OSError:
        link_ok, link_out = True, 'hard links unsupported here'
    record('tracefix: a kept frame or a sheet never replaces the words file it reads, by name or through a hard link',
           kept == 2 and named.read_bytes() == before and bool(link_ok), kept_out + str(link_out))
