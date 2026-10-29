"""Known-answer regressions for the tracefix tools."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
import wave
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
    code, out = tool('frame_sheet.py', j('good.mp4'), '--frames', '0-4', '--width', '160', '--cols', '3',
                     '--max-width', '338', '--max-height', '240', '--out', j('trace-sheet.png'))
    paths = [Path(j('trace-sheet.png')), Path(j('trace-sheet-2.png'))]
    sizes = [Image.open(path).size for path in paths if path.exists()]
    record('tracefix: five tiles paginate at unchanged size inside pixel budget',
           code == 0 and len(sizes) == 2 and all(w <= 338 and h <= 240 for w, h in sizes)
           and sizes[0] == (338, 230), str(sizes) + ' ' + out[-100:])
    code, _ = tool('frame_sheet.py', j('good.mp4'), '--frames', '0-1', '--width', '160', '--single',
                   '--out', j('trace-single.png'))
    names = sorted(Path(j('')).glob('trace-single-frame-*.png'))
    record('tracefix: single frames carry timestamp in names',
           code == 0 and len(names) == 2 and '-at-' in names[0].name, str(names))
