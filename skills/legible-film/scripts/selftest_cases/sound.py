#!/usr/bin/env python3
"""Known-answer sound cases loaded by selftest.py, or runnable standalone.

selftest.py loads selftest_cases/sound.py and calls
run_sound_cases(tool, record, j, HERE), using its existing helpers and results.
Run this module from the skill directory with:

  python -I scripts/selftest_cases/sound.py --scripts scripts --keep work/sound-tests

Needs numpy and FFmpeg. These tests measure synthetic answers, never sound quality.
Exit 0 all passed, 1 any failure, 2 could not run.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import numpy as np


def run_sound_cases(tool, record, j, scripts_dir):
    def load(name):
        spec = importlib.util.spec_from_file_location(name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    io, mixer = load('sound_io'), load('mix_cues')
    ffmpeg = io.find_tool('ffmpeg')
    rate = 16000
    def synthetic(bpm, phase=.137, beats=100, drift=0):
        period = 60 / bpm
        periods = np.full(beats, period)
        periods[:beats // 2] *= 1 - drift / 2
        periods[beats // 2:] *= 1 + drift / 2
        times = phase + np.r_[0, np.cumsum(periods[:-1])]
        x = np.zeros(round((times[-1] + period) * rate), np.float32)
        u = np.arange(round(.080 * rate)) / rate
        pulse = (np.sin(2 * np.pi * 90 * u) + .6 * np.sin(2 * np.pi * 180 * u)) * np.exp(-u / .018)
        pulse[:8] *= np.linspace(0, 1, 8)
        drop = 8 * 4
        for i, t in enumerate(times):
            k = round(t * rate)
            gain = (.7 if i % 4 == 0 else .35) * (.20 if i < drop else .8)
            x[k:k + len(pulse)] += pulse * gain
        return np.column_stack((x, x)), float(times[drop]), phase
    for bpm, phase in ((172., .137), (150., .0), (120., .811)):
        x, drop, expected_phase = synthetic(bpm, phase)
        path, report = j(f'known-{bpm:g}.wav'), j(f'known-{bpm:g}.json')
        io.write_wav(ffmpeg, path, x, rate)
        code, text = tool('beat_grid.py', path, '--bpm', bpm, '--drop-at-beat', 32, '--json', report)
        r = json.loads(Path(report).read_text())
        record(f'beat_grid: {bpm:g} BPM within .05', abs(r['bpm'] - bpm) < .05, f"{r['bpm']:.6f}; exit {code}")
        record(f'beat_grid: {bpm:g} phase/downbeat within 3 ms', abs(r['offset_s'] - expected_phase) <= .003,
               f"{r['offset_s']:.6f} vs {expected_phase}")
        record(f'beat_grid: {bpm:g} right drop bar', bool(r['drops']) and abs(r['drops'][0]['music_s'] - drop) < .003
               and r['drops'][0]['film_beat'] == 32, str(r['drops'][:1]))
        record(f'beat_grid: {bpm:g} consistent grid exit 0', code == 0, str(r['flags']))
    # No prior: demonstrates the global AC/search path, not just prior recovery.
    code, _ = tool('beat_grid.py', j('known-172.wav'), '--json', j('no-prior.json'))
    r = json.loads(Path(j('no-prior.json')).read_text())
    record('beat_grid: unknown tempo recovered without prior', abs(r['bpm'] - 172) < .05 and code == 0, str(r['bpm']))
    code, _ = tool('beat_grid.py', j('known-172.wav'), '--bpm', 172, '--drop-at-beat', 64, '--json', j('negative-offset.json'))
    r = json.loads(Path(j('negative-offset.json')).read_text())
    record('beat_grid: negative suggested trim disclosed', r['suggested_offset_negative'] and r['suggested_offset_s'] < 0
           and abs(r['drop_alignment_error_ms']) < 1, str(r['suggested_offset_s']))
    x, _, _ = synthetic(150, .137, beats=320, drift=.0015)
    io.write_wav(ffmpeg, j('drift.wav'), x, rate)
    code, _ = tool('beat_grid.py', j('drift.wav'), '--bpm', 150, '--json', j('drift.json'))
    r = json.loads(Path(j('drift.json')).read_text())
    record('beat_grid: .15% period change flagged', code == 1 and r['drift_ms'] is not None and abs(r['drift_ms']) > 150,
           f"{r['drift_ms']} ms; {r['bpm']} BPM")
    record('beat_grid: drift global mean tempo within .05 BPM', abs(r['bpm'] - 150) < .05, str(r['bpm']))
    record('beat_grid: drifting track first downbeat within 3 ms', abs(r['offset_s'] - .137) <= .003, str(r['offset_s']))
    drift_drop = .137 + 32 * .4 * (1 - .0015 / 2)
    record('beat_grid: drifting track right measured drop/downbeat', bool(r['drops']) and
           abs(r['drops'][0]['music_s'] - drift_drop) <= .003 and r['drops'][0]['film_beat'] == 32,
           str(r['drops'][:1]))
    # A window with one tempo must recover that local tempo, not whole-track mean.
    code, _ = tool('beat_grid.py', j('drift.wav'), '--bpm', 150, '--start', 70, '--window', 45, '--json', j('window.json'))
    r = json.loads(Path(j('window.json')).read_text())
    record('beat_grid: fits requested window independently', abs(r['bpm'] - 150 / 1.00075) < .05 and code == 0,
           f"{r['bpm']}; {r['flags']}")
    code, text = tool('make_sound_kit.py', '--out', j('kit'), '--seed', 91, '--temp-bpm', 150)
    record('make_sound_kit: generates all 11 roles and temp track', code == 0, text.strip())
    palette_path = Path(j('kit', 'palette.json'))
    palette = json.loads(palette_path.read_text())
    import hashlib
    import wave
    hashes_ok, peaks_ok, edges_ok, dc_ok, spectra_ok, format_ok = True, True, True, True, True, True
    for role in palette['roles'].values():
        for index, relative in enumerate(role['takes']):
            path = palette_path.parent / relative
            with wave.open(str(path), 'rb') as wav:
                format_ok &= wav.getnchannels() == 2 and wav.getsampwidth() == 3 and wav.getframerate() == 48000
            hashes_ok &= hashlib.sha256(path.read_bytes()).hexdigest() == role['sha256'][index]
            x = io.decode(ffmpeg, path)
            peaks_ok &= -4.3 <= io.db(np.max(np.abs(x))) <= -2.99
            edges_ok &= np.max(np.abs(x[[0, -1]])) < 2e-6
            dc_ok &= np.max(np.abs(x.mean(axis=0))) < 1e-6
            spectra_ok &= role['measurements'][index]['upper_mid_max_20hz_in_400hz_share'] < .45
    record('make_sound_kit: 33 take hashes match', hashes_ok)
    record('make_sound_kit: all 33 takes stereo 48 kHz 24-bit PCM', format_ok)
    record('make_sound_kit: peak levels as stated', peaks_ok)
    record('make_sound_kit: zero-valued edges and no DC', edges_ok and dc_ok)
    record('make_sound_kit: upper-mid narrow-band screen', spectra_ok)
    key = palette['roles']['key']
    record('make_sound_kit: key variants differ in samples and levels', len(set(key['sha256'])) == 3 and
           len(set(round(v['peak_dbfs'], 1) for v in key['measurements'])) == 3)
    code, _ = tool('make_sound_kit.py', '--out', j('subset'), '--seed', 91, '--roles', 'key')
    subset = json.loads(Path(j('subset', 'palette.json')).read_text())
    record('make_sound_kit: seeded subset reproduces identical takes', code == 0 and
           subset['roles']['key']['sha256'] == key['sha256'] and len(subset['roles']) == 1)
    music = j('kit', palette['music']['file'])
    beatmap = json.loads(Path(music).with_suffix('.json').read_text())
    record('make_sound_kit: temp true peak <= -1 dBTP', beatmap['measurements']['true_peak_dbtp'] <= -1,
           str(beatmap['measurements']))
    audio = io.decode(ffmpeg, music)
    record('make_sound_kit: sample-exact stop with silence after', np.max(np.abs(audio[round(beatmap['stop_s'] * 48000):])) == 0)
    code, _ = tool('beat_grid.py', music, '--bpm', 150, '--window', beatmap['stop_s'], '--json', j('temp-grid.json'))
    r = json.loads(Path(j('temp-grid.json')).read_text())
    record('beat_grid: generated temp tempo within .02 BPM', abs(r['bpm'] - 150) < .02, str(r['bpm']))
    record('beat_grid: generated temp phase within 2 ms', abs(r['offset_s']) <= .002, str(r['offset_s']))
    record('beat_grid: generated temp drop bar 9', bool(r['drops']) and abs(r['drops'][0]['music_s'] - beatmap['drop_s']) < .003,
           str(r['drops'][:1]))
    kit_events = []
    for i, (role, rs) in enumerate(palette['roles'].items()):
        kit_events.append({'id': role, 't': (i + 1) * 3., 'role': role, 'sync': rs['sync'],
                           'variant': 0, 'sound': 'required', 'tolerance_ms': 2})
    io.save_json(j('kit-cues.json'), {'duration': 36, 'events': kit_events})
    code, _ = tool('mix_cues.py', j('kit-cues.json'), palette_path, '--out-dir', j('kit-mix'), '--no-music')
    record('mix_cues: generated palette integrates without missing roles', code == 0)
    code, _ = tool('cue_onsets.py', j('kit-mix', 'effects.wav'), j('kit-cues.json'), '--json', j('kit-onsets.json'))
    kr = json.loads(Path(j('kit-onsets.json')).read_text())['rows']
    record('cue_onsets: generated role syncs within 2 ms', code == 0 and all(abs(row.get('offset_ms', 999)) <= 2 for row in kr),
           str([(row['id'], row.get('offset_ms'), row['status']) for row in kr]))
    # S1: a silent window may extend past a file edge; only its in-file
    # portion is checked. A key well inside the output leaves both edges quiet.
    io.save_json(j('edge-silence-cues.json'), {'duration': 3, 'events': [
        {'id': 'cold-open', 't': .05, 'sound': 'silent'},
        {'id': 'key', 't': 1, 'role': 'key', 'sound': 'required'},
        {'id': 'quiet-tail', 't': 2.95, 'sound': 'silent'}]})
    code, _ = tool('mix_cues.py', j('edge-silence-cues.json'), palette_path,
                   '--out-dir', j('edge-silence-mix'), '--no-music')
    edge_report = json.loads(Path(j('edge-silence-mix', 'mix-report.json')).read_text())
    record('mix_cues: silent windows crossing output edges are clamped', code == 0 and
           not edge_report['silent_window_violations'] and not edge_report['silent_windows_outside_output'],
           f"exit {code}; outside {edge_report['silent_windows_outside_output']}")
    # S2: the exclusive end of the riser and the file coincide; a detector
    # must not require real samples after the file to report this endpoint.
    io.save_json(j('file-end-cues.json'), {'duration': 3, 'events': [
        {'id': 'riser-at-end', 't': 3, 'role': 'riser', 'sync': 'end',
         'sound': 'required', 'tolerance_ms': 2}]})
    mix_code, _ = tool('mix_cues.py', j('file-end-cues.json'), palette_path,
                       '--out-dir', j('file-end-mix'), '--no-music')
    code, _ = tool('cue_onsets.py', j('file-end-mix', 'effects.wav'), j('file-end-cues.json'),
                   '--json', j('file-end-onsets.json'))
    last = json.loads(Path(j('file-end-onsets.json')).read_text())['rows'][0]
    record('cue_onsets: end-sync at the audio endpoint is on cue', mix_code == 0 and code == 0 and
           last['status'] == 'on cue' and abs(last.get('offset_ms', 999)) <= 2,
           f"mix exit {mix_code}; {last['status']}, offset {last.get('offset_ms')} ms")
    io.write_wav(ffmpeg, j('silence.wav'), np.zeros((rate * 4, 2), np.float32), rate)
    code, _ = tool('beat_grid.py', j('silence.wav'), '--json', j('silence-grid.json'))
    record('beat_grid: silence is weak/inconclusive, exit 1', code == 1)
    # Sync fixtures with exact attack, apex and end. Independent waveforms make
    # placement checks independent of the generator's own manifest calculations.
    rate = 48000
    u = np.arange(24000) / rate
    attack = np.sin(2 * np.pi * 800 * u) * np.exp(-u / .015)
    attack[:24] *= np.linspace(0, 1, 24)
    apex = np.sin(2 * np.pi * 800 * u) * np.exp(-.5 * ((u - .250) / .045) ** 2)
    end = np.sin(2 * np.pi * 800 * u) * .2
    end[:240] *= np.linspace(0, 1, 240)
    end[-1344:] *= np.linspace(1, 0, 1344)
    rp = {'version': 1, 'rate': rate, 'roles': {}}
    # cue_onsets stamps a forward 5 ms RMS window at its right edge; the
    # centred Gaussian's apex is therefore stamped at .253 s on its 1 ms grid.
    for role, x, point in (('attack', attack, 0), ('apex', apex, .253), ('end', end, .5)):
        io.write_wav(ffmpeg, j(role + '.wav'), np.column_stack((x, x)) * .35)
        rp['roles'][role] = {'takes': [role + '.wav'], 'sync': role, 'points_s': [point], 'gain_db': 0}
    bed = np.column_stack((np.sin(2 * np.pi * 170 * np.arange(6 * rate) / rate),) * 2) * .08
    io.write_wav(ffmpeg, j('bed.wav'), bed)
    rp['music'] = {'file': 'bed.wav', 'gain_db': -3, 'stop_s': 5.5, 'fade_in_ms': 10, 'fade_out_ms': 20}
    io.save_json(j('palette.json'), rp)
    cues = {'duration': 6, 'events': [{'id': r, 't': t, 'role': r, 'sync': r, 'sound': 'required',
                                     'tolerance_ms': 2, 'duck_db': 4, 'gain_db': -2, 'variant': 0}
                                    for r, t in (('attack', 1), ('apex', 2), ('end', 3))] +
            [{'id': 'quiet', 't': 4, 'sound': 'silent', 'window_ms': 200}]}
    io.save_json(j('cues.json'), cues)
    code, text = tool('mix_cues.py', j('cues.json'), j('palette.json'), '--out-dir', j('mix'))
    record('mix_cues: places required events; clean silent window; exit 0', code == 0, text.strip())
    code, _ = tool('cue_onsets.py', j('mix', 'effects.wav'), j('cues.json'), '--json', j('onsets.json'))
    rows = json.loads(Path(j('onsets.json')).read_text())['rows']
    for row in rows[:3]:
        record(f"mix_cues/cue_onsets: {row['sync']} within 2 ms", row['status'] == 'on cue' and abs(row['offset_ms']) <= 2,
               f"{row.get('offset_ms')} ms; {row['status']}")
    record('cue_onsets: accepts end and all optional fields', code == 0)
    envelope = mixer.duck_envelope(6 * rate, rate, [(1, 1.3, 4)])
    record('mix_cues: duck ramp continuous with known hold/recovery', float(np.max(np.abs(np.diff(envelope)))) < .001 and
           abs(envelope[rate] - 10 ** (-4 / 20)) < 1e-6 and envelope[2 * rate] == 1)
    r = json.loads(Path(j('mix', 'mix-report.json')).read_text())
    record('mix_cues: presence and true peak/loudness reported', len(r['presence']) == 3 and
           r['mix']['true_peak_dbtp'] is not None and r['mix']['integrated_lufs'] is not None)
    cues['events'].append({'id': 'unavailable', 't': 4.8, 'role': 'absent', 'sound': 'required'})
    io.save_json(j('missing.json'), cues)
    code, _ = tool('mix_cues.py', j('missing.json'), j('palette.json'), '--out-dir', j('missing'))
    r = json.loads(Path(j('missing', 'mix-report.json')).read_text())
    record('mix_cues: required missing role is disclosed; exit 1', code == 1 and r['missing_roles'][0]['role'] == 'absent')
    cues['events'][-1]['sound'] = 'optional'
    io.save_json(j('optional.json'), cues)
    code, _ = tool('mix_cues.py', j('optional.json'), j('palette.json'), '--out-dir', j('optional'))
    record('mix_cues: optional missing role disclosed without failure', code == 0)
    cues['events'] = cues['events'][:3] + [{'id': 'bad-silence', 't': 1.05, 'sound': 'silent', 'window_ms': 20}]
    io.save_json(j('broken.json'), cues)
    code, _ = tool('mix_cues.py', j('broken.json'), j('palette.json'), '--out-dir', j('broken'))
    r = json.loads(Path(j('broken', 'mix-report.json')).read_text())
    tails = r.get('silent_window_tails', [])
    expected_tail = io.decode(ffmpeg, j('attack.wav'))[1440:3360] * 10 ** (-2 / 20)
    record('mix_cues: earlier decay in silent window passes with peak and RMS', code == 0 and
           not r['silent_window_violations'] and len(tails) == 1 and tails[0]['take_event_id'] == 'attack' and
           tails[0]['window_s'] == [1.03, 1.07] and
           abs(tails[0]['peak_dbfs'] - io.db(np.max(np.abs(expected_tail)))) < .001 and
           abs(tails[0]['rms_dbfs'] - io.level(expected_tail)) < .001,
           f'exit {code}; tails {tails}')
    cues['events'][-1]['t'] = 1.
    io.save_json(j('starts-inside.json'), cues)
    code, _ = tool('mix_cues.py', j('starts-inside.json'), j('palette.json'), '--out-dir', j('starts-inside'))
    r = json.loads(Path(j('starts-inside', 'mix-report.json')).read_text())
    record('mix_cues: take starting inside silent window fails; exit 1', code == 1 and
           len(r['silent_window_violations']) == 1 and r['silent_window_violations'][0]['take_event_id'] == 'attack',
           f"exit {code}; violations {r['silent_window_violations']}")
    code, _ = tool('mix_cues.py', j('cues.json'), j('palette.json'), '--out-dir', j('refused'), '--gain-to-lufs', 0)
    r = json.loads(Path(j('refused', 'mix-report.json')).read_text())
    record('mix_cues: unsafe linear normalisation refused; exit 1', code == 1 and bool(r['gain_refused']) and r['gain_applied_db'] == 0)
    code, _ = tool('mix_cues.py', j('cues.json'), j('palette.json'), '--out-dir', j('gained'), '--gain-to-lufs', -35)
    r = json.loads(Path(j('gained', 'mix-report.json')).read_text())
    record('mix_cues: safe plain gain reaches requested loudness', code == 0 and abs(r['mix']['integrated_lufs'] + 35) <= .2)
    for script, args in (('beat_grid.py', [j('gone.wav')]), ('make_sound_kit.py', ['--out', j('bad-kit'), '--stop-bar', 2, '--temp-bpm', 150]),
                         ('mix_cues.py', [j('gone.json'), j('palette.json'), '--out-dir', j('gone-mix')])):
        code, _ = tool(script, *args)
        record(script + ': cannot run returns 2', code == 2)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scripts', required=True)
    p.add_argument('--keep', required=True)
    a = p.parse_args()
    root = Path(a.keep).resolve(); root.mkdir(parents=True, exist_ok=True)
    scripts = Path(a.scripts).resolve()
    results = []
    def record(name, ok, detail=''):
        results.append({'name': name, 'ok': bool(ok), 'detail': detail})
        print(('PASS' if ok else 'FAIL') + '  ' + name + (f' [{detail}]' if detail else ''), flush=True)
    def tool(script, *args):
        r = subprocess.run([sys.executable, '-I', '-B', str(scripts / script), *map(str, args)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        return r.returncode, r.stdout + r.stderr
    try:
        run_sound_cases(tool, record, lambda *parts: str(root.joinpath(*parts)), scripts)
    except Exception as exc:
        record('runner completed', False, repr(exc))
    Path(root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    passed = sum(r['ok'] for r in results)
    print(f'{passed}/{len(results)} checks passed.')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
