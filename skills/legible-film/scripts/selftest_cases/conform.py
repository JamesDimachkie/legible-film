"""Known-answer tests for music conforming."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import wave

import numpy as np


def run_conform_cases(tool, record, j, scripts_dir):
    root = Path(j('conform-cases'))
    root.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('lf_conform_cases', Path(scripts_dir) / 'conform.py')
    conform = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conform)
    rate = 48000
    t = np.arange(rate * 12) / rate
    signal = np.zeros(len(t), dtype=np.float32)
    for start in range(0, len(signal), rate // 2):
        n = min(480, len(signal) - start)
        signal[start:start+n] = .2 * np.sin(2 * np.pi * 1000 * np.arange(n) / rate) * np.hanning(n)
    source = root / 'source.wav'
    with wave.open(str(source), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes((signal * 32767).astype('<i2').tobytes())
    mapping = root / 'map.json'
    mapping.write_text(json.dumps({'sections': [{'id': 'whole', 'a': 0, 'b': 12, 'take_start': 0}]}),
                       encoding='utf-8')
    output, report_path = root / 'bed.wav', root / 'conform.json'
    def decode(path):
        return np.frombuffer(subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '2',
                                                      '-ar', str(rate), '-f', 'f32le', '-']), dtype='<f4')
    code, output_text = tool('conform.py', source, '--map', mapping, '--out', output, '--report', report_path)
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    record('conform: unbound identity writes a hashed bed and report',
           code == 0 and report.get('binding') == 'unbound' and output.exists()
           and report.get('map_sha256') == digest(mapping) and report.get('music_sha256') == digest(source)
           and report.get('bed_sha256') == digest(output), output_text[-300:])
    # A rejected output must not alter an existing version, or write the other output first.
    for holder, version in (('own', root / 'cuts' / 'v001'),
                            ('other', root / 'other-project' / 'cuts' / 'v002')):
        version.mkdir(parents=True)
        (version / 'manifest.json').write_text('{}', encoding='utf-8')
        for role in ('bed', 'report'):
            protected = version / ('bed.wav' if role == 'bed' else 'qa/conform.json')
            protected.parent.mkdir(parents=True, exist_ok=True)
            protected.write_bytes(b'version bytes must not change')
            outside = root / f'{holder}-{role}-outside' / ('report.json' if role == 'bed' else 'bed.wav')
            bed = protected if role == 'bed' else outside
            report_out = protected if role == 'report' else outside
            code, text = tool('conform.py', source, '--map', mapping, '--out', bed, '--report', report_out)
            record(f'conform: {holder} version {role} is refused before either output is written',
                   code == 2 and 'inside the version' in text
                   and protected.read_bytes() == b'version bytes must not change' and not outside.exists(),
                   f'exit {code}; {text[-250:]}')
    if output.exists():
        original, conformed = decode(source), decode(output)
        record('conform: no-edit map is sample-identical within 24-bit quantization',
               len(original) == len(conformed) and np.max(np.abs(original-conformed)) < 2e-7,
               f'lengths {len(original)}, {len(conformed)}')
    else:
        record('conform: no-edit map is sample-identical within 24-bit quantization', False, 'no output')
    # This fixture is checked by the shared 'cue_list' reader against its page.
    fixture = Path(scripts_dir) / 'testpages' / 'identity' / 'cues.json'
    bound_map = root / 'bound-map.json'
    bound_map.write_text(json.dumps({'cues_sha256': digest(fixture), 'sections': [
        {'id': 'open', 'take_start': 0}, {'id': 'mark', 'take_start': 1},
        {'id': 'hold', 'take_start': 2.5}]}), encoding='utf-8')
    code, text = tool('conform.py', source, '--map', bound_map, '--cues', fixture,
                      '--out', output, '--report', report_path)
    bound_report = json.loads(report_path.read_text(encoding='utf-8')) if code == 0 else {}
    record('conform: a fresh v2 list supplies bound section times and byte hashes',
           code == 0 and bound_report.get('binding') == 'bound'
           and bound_report.get('cues_sha256') == digest(fixture)
           and bound_report.get('map_sha256') == digest(bound_map)
           and bound_report.get('duration_s') == 3, text[-300:])
    if code == 0:
        palette = root / 'bound-palette.json'
        palette.write_text(json.dumps({'version': 2, 'music': {'file': source.name},
                                       'roles': {'impact': {'takes': [source.name], 'sync': 'attack',
                                                            'points_s': [0]}}}), encoding='utf-8')
        mix_code, mix_text = tool('mix_cues.py', fixture, palette, '--out-dir', root / 'bound-mix',
                                  '--duration', 3, '--master', 'none', '--music', output,
                                  '--conform', report_path)
        record('conform: its v2-bound bed is accepted by the mixer', mix_code == 0, mix_text[-300:])
    plan = root / 'plan.json'
    plan.write_text(json.dumps({'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None},
                                'sections': [{'id': 'one', 'a': 0, 'b': 1, 'clock': 'music'}],
                                'events': []}), encoding='utf-8')
    bound_map.write_text(json.dumps({'cues_sha256': digest(plan),
                                     'sections': [{'id': 'one', 'take_start': 0}]}), encoding='utf-8')
    code, text = tool('conform.py', source, '--map', bound_map, '--cues', plan,
                      '--out', root / 'plan-bed.wav', '--report', root / 'plan-report.json')
    record('conform: the shared reader refuses an unbound plan',
           code == 2 and 'unbound plan' in text and not (root / 'plan-bed.wav').exists(), text[-300:])
    legacy = root / 'legacy.json'
    legacy.write_text(json.dumps({'version': 'v1', 'events': [],
                                  'sections': [{'id': 'one', 'a': 0, 'b': 1}]}), encoding='utf-8')
    bound_map.write_text(json.dumps({'cues_sha256': digest(legacy),
                                     'sections': [{'id': 'one', 'take_start': 0}]}), encoding='utf-8')
    code, text = tool('conform.py', source, '--map', bound_map, '--cues', legacy,
                      '--out', root / 'legacy-bed.wav', '--report', root / 'legacy-report.json')
    record('conform: v1 does not invent sections outside the shared reader view',
           code == 2 and 'section not found' in text, text[-300:])
    mapping.write_text(json.dumps({'sections': [{'id': 'first', 'a': 0, 'b': 6, 'take_start': 0},
                                                {'id': 'second', 'a': 6, 'b': 12, 'take_start': 6,
                                                 'gain_db': -6}]}), encoding='utf-8')
    code, output_text = tool('conform.py', source, '--map', mapping, '--out', output, '--report', report_path)
    if code == 0:
        x = decode(output).reshape(-1, 2)
        left = np.sqrt(np.mean(x[rate:rate*5].astype(np.float64)**2))
        right = np.sqrt(np.mean(x[rate*7:rate*11].astype(np.float64)**2))
        delta = 20*np.log10(right/left)
    else:
        delta = 999
    record('conform: section gain is applied once', code == 0 and abs(delta + 6) < .1, str(delta)+output_text[-150:])
    tempo_path = root / 'tempo.json'
    tempo_path.write_text(json.dumps({'offset_s': 0, 'bar_s': 2, 'period_s': .5}), encoding='utf-8')
    mapping.write_text(json.dumps({'sections': [{'id': f's{i}', 'a': i*4, 'b': (i+1)*4,
                                                 'take_start': 0} for i in range(3)]}), encoding='utf-8')
    code, output_text = tool('conform.py', source, '--map', mapping, '--out', output, '--report', report_path,
                             '--tempo', tempo_path, '--snap', 'bar')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    seams = report.get('seams') or []
    rendered = decode(output).reshape(-1, 2) if code == 0 else np.zeros((1, 2))
    downbeat_errors = []
    for second in range(0, 12, 2):
        expected = second * rate
        lo, hi = max(0, expected - rate // 100), min(len(rendered), expected + rate // 100)
        hits = np.flatnonzero(np.max(np.abs(rendered[lo:hi]), axis=1) > .001)
        downbeat_errors.append((lo + int(hits[0]) - expected) * 1000 / rate if len(hits) else 999)
    record('conform: 120 BPM loop has quiet seams and aligned downbeats',
           code == 0 and len(seams) == 2 and all(row['discontinuity_dbfs'] < -60
                                                and abs(row['bar_line_error_ms']) < 5 for row in seams)
           and max(map(abs, downbeat_errors)) < 5 and len(report.get('low_band_bars', [])) == 6,
           str((seams, downbeat_errors))+output_text[-150:])
    low_t = np.arange(rate * 5) / rate
    low = np.repeat((.1 * np.sin(2*np.pi*60*low_t))[:, None], 2, axis=1).astype(np.float32)
    low_bars = conform.measurements(low, [], {'bar_s': 2, 'offset_s': 0})
    record('conform: a partial bar at the same level has no false low-band drop',
           len(low_bars) == 3 and abs(low_bars[0]['low_band_db'] + 23.0103) < .02
           and abs(low_bars[-1]['contrast_db']) < .2, str(low_bars))
    bad = root / 'bad-source.wav'
    with wave.open(str(bad), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes((np.r_[np.zeros(rate), np.full(rate, .5)] * 32767).astype('<i2').tobytes())
    mapping.write_text(json.dumps({'sections': [{'id': 'a', 'a': 0, 'b': 1, 'take_start': 0},
                                                {'id': 'b', 'a': 1, 'b': 2, 'take_start': 1}]}), encoding='utf-8')
    code, output_text = tool('conform.py', bad, '--map', mapping, '--out', output, '--report', report_path,
                             '--xfade-ms', 0)
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('conform: a planted hard splice is flagged', code == 0 and (report.get('seams') or [{}])[0].get('look'),
           str(report.get('seams')) + output_text[-150:])
    tone = root / 'tone.wav'
    with wave.open(str(tone), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes((.1 * np.sin(2*np.pi*60*np.arange(rate*2)/rate) * 32767).astype('<i2').tobytes())
    mapping.write_text(json.dumps({'sections': [{'id': 'one', 'a': 0, 'b': 2, 'take_start': 0}]}),
                       encoding='utf-8')
    original = decode(tone).reshape(-1, 2)
    def level(audio, a, b):
        return float(np.sqrt(np.mean(audio[round(a*rate):round(b*rate)].astype(np.float64)**2)))
    mapping.write_text(json.dumps({'sections': [{'id': 'a', 'a': 0, 'b': 1, 'take_start': 0},
                                                {'id': 'b', 'a': 1, 'b': 2, 'take_start': 1,
                                                 'gain_db': -.01}]}), encoding='utf-8')
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path)
    joined = decode(output).reshape(-1, 2) if code == 0 else np.ones_like(original)
    overshoot = float(np.max(np.abs(joined[round(.96*rate):round(1.04*rate)]))) / float(np.max(np.abs(original)))
    record('conform: a continuous source with changed gain does not boost at the join',
           code == 0 and overshoot <= 1.001, str(overshoot)+text[-100:])
    mapping.write_text(json.dumps({'sections': [{'id': 'one', 'a': 0, 'b': 2, 'take_start': 0,
                                                 'edits': [{'at': 0, 'take_start': 0},
                                                           {'at': 1, 'take_start': .5}]}]}),
                       encoding='utf-8')
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path)
    edited = json.loads(report_path.read_text(encoding='utf-8')) if code == 0 else {}
    record('conform: a section can contain multiple edits',
           code == 0 and len(edited.get('seams', [])) == 1 and edited['seams'][0]['at_s'] == 1
           and edited.get('duration_s') == 2, text[-100:])
    mapping.write_text(json.dumps({'sections': [{'id': 'one', 'a': 0, 'b': 2, 'take_start': 0}]}),
                       encoding='utf-8')
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path,
                      '--bass-cut', '.5,1.5,180')
    filtered = decode(output).reshape(-1, 2) if code == 0 else original
    cut_db = 20*np.log10(max(level(filtered, .8, 1.2), 1e-12)/level(original, .8, 1.2))
    record('conform: bass cut attenuates low frequency in its window', code == 0 and cut_db < -25, str(cut_db)+text[-100:])
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path,
                      '--lift', '.5,1.5,-6')
    lifted = decode(output).reshape(-1, 2) if code == 0 else original
    lift_db = 20*np.log10(level(lifted, .8, 1.2)/level(original, .8, 1.2))
    record('conform: lift gain applies once in its window', code == 0 and abs(lift_db + 6) < .1, str(lift_db)+text[-100:])
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path,
                      '--tape-stop', '1,.413')
    stopped = decode(output).reshape(-1, 2) if code == 0 else original
    record('conform: tape stop falls toward silence', code == 0 and level(stopped, 1.35, 1.39) < .2*level(original, 1.35, 1.39), text[-100:])
    edge = round(1.413 * rate)
    jump = float(np.max(np.abs(stopped[edge] - stopped[edge-1])))
    record('conform: tape stop resumes without a hard step', code == 0 and jump < .001, str(jump))
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path,
                      '--tail', '1,.15,-6')
    tailed = decode(output).reshape(-1, 2) if code == 0 else original
    record('conform: requested tail changes the audio after its start',
           code == 0 and level(tailed-original, 1.1, 1.5) > .001, text[-100:])
    mapping.write_text(json.dumps({'sections': [{'id': 'one', 'a': 0, 'b': 2.05, 'take_start': 0}]}),
                       encoding='utf-8')
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path)
    record('conform: an insufficient take is refused by default', code == 2 and 'ends before' in text, text[-100:])
    code, text = tool('conform.py', tone, '--map', mapping, '--out', output, '--report', report_path,
                      '--source-edge', 'hold')
    held = json.loads(report_path.read_text(encoding='utf-8')) if code == 0 else {}
    record('conform: explicit source-edge hold is recorded',
           code == 0 and held.get('source_edge') == 'hold' and held.get('held_source_samples', 0) >= round(.05*rate),
           text[-100:] + str(held.get('held_source_samples')))
    original_cues = {'sections': [{'id': 'one', 'a': 0, 'b': 1}]}
    changed_cues = {'sections': [{'id': 'one', 'a': 0, 'b': 1.1}]}
    cue_hash = hashlib.sha256(json.dumps(original_cues).encode()).hexdigest()
    changed_hash = hashlib.sha256(json.dumps(changed_cues).encode()).hexdigest()
    bound = {'cues_sha256': cue_hash, 'sections': [{'id': 'one', 'take_start': 0}]}
    bound_sections, _ = conform.resolve_sections(bound, original_cues, cue_hash, None, 'none', 40)
    try:
        conform.resolve_sections(bound, changed_cues, changed_hash, None, 'none', 40)
        stale_refused = False
    except ValueError as error:
        stale_refused = 'stale map' in str(error)
    record('conform: moving a section under its id refuses the old map',
           bound_sections[0]['b'] == 1 and stale_refused, 'hash and bound lookup')
    code, output_text = tool('conform.py', source, '--map', mapping, '--out', source, '--report', report_path)
    record('conform: an input cannot be used as the output', code == 2 and 'input' in output_text.lower(),
           output_text[-200:])


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as temp:
        results = []
        def tool(name, *args):
            p = subprocess.run([sys.executable, str(Path(__file__).parents[1] / name), *map(str, args)],
                               capture_output=True, text=True)
            return p.returncode, p.stdout + p.stderr
        def record(name, ok, detail):
            results.append(ok)
            print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ': ' + detail))
        run_conform_cases(tool, record, lambda name: str(Path(temp) / name), Path(__file__).parents[1])
        sys.exit(0 if all(results) else 1)
