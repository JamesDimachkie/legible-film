#!/usr/bin/env python3
"""Known-answer mixing, spotting and checking cases, loaded by selftest.py.

  python -I selftest_cases/chain.py --scripts scripts --keep work/chain-tests

Synthetic samples only. These cases prove placement and measured behaviours on
this machine, not listening quality. Exit 0 all pass, 1 failed, 2 cannot run.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import numpy as np


def run_chain_cases(tool, record, j, scripts_dir):
    spec = importlib.util.spec_from_file_location('chain_io', Path(scripts_dir) / 'sound_io.py')
    io = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(io)
    ffmpeg = io.find_tool('ffmpeg')
    rate = 48000
    root = Path(j('chain'))
    root.mkdir(parents=True, exist_ok=True)
    def path(*parts):
        return root.joinpath(*parts)
    def save(name, value):
        io.save_json(path(name), value)
        return path(name)
    def read(name):
        return json.loads(path(name).read_text(encoding='utf-8'))
    def wav(name, x):
        io.write_wav(ffmpeg, path(name), x, rate)
        return path(name)
    def mix(cues, palette, name, *args):
        return tool('mix_cues.py', cues, palette, '--out-dir', path(name), *args)

    # Three independently known sync points, differing channels and additive
    # gains. A forbidden nested ghost role proves that layers do not recurse.
    roles = {}
    for role, point, sync, channels in (
            ('tap', .01, 'attack', (.2, 0)), ('sub', .04, 'apex', (0, .3)), ('air', .07, 'end', (.1, .1))):
        x = np.zeros((4800, 2), np.float32)
        index = round(point * rate) - (1 if sync == 'end' else 0)
        x[index] = channels
        wav(role + '.wav', x)
        roles[role] = {'takes': [role + '.wav'], 'sync': sync, 'points_s': [point], 'gain_db': -2}
    roles['tap']['layers'] = [{'role': 'sub', 'gain_db': -3}, {'role': 'air', 'gain_db': -4}]
    roles['sub']['layers'] = [{'role': 'ghost'}]
    palette = save('layers-palette.json', {'version': 2, 'roles': roles})
    cues = save('layers-cues.json', {'duration': 2, 'events': [{'id': 'composite', 't': 1, 'role': 'tap', 'gain_db': -1}]})
    code, out = mix(cues, palette, 'layers')
    r = read('layers/mix-report.json')
    x = io.decode(ffmpeg, path('layers/effects.wav'))
    sample = rate
    expected = np.array([.2, 0]) * 10 ** (-3 / 20) + np.array([0, .3]) * 10 ** (-6 / 20)
    expected_air = np.array([.1, .1]) * 10 ** (-7 / 20)
    hits = np.flatnonzero(np.max(np.abs(x), axis=1) > 1e-5)
    record('chain: composite layers use their own sync within 2 ms, additive gains, no recursion',
           code == 0 and len(r['events_placed']) == 1 and len(r['events_placed'][0]['layers']) == 2 and
           len(hits) == 2 and np.max(np.abs(hits / rate - 1)) <= .002 and
           np.max(np.abs(x[sample] - expected)) < 1e-6 and np.max(np.abs(x[sample - 1] - expected_air)) < 1e-6,
           f'exit {code}, active sample offsets {(hits - sample).tolist()}')

    # Deliberately mismatched loop endpoints, so a naive repeat fails the stated
    # <0.0001 full-scale/sample bound. Check seams AND every sample in the bed.
    take = np.linspace(.02, .04, 24000, dtype=np.float32)
    wav('room.wav', np.column_stack((take, take)))
    bed_palette = save('bed-palette.json', {'version': 2, 'roles': {'room': {
        'takes': ['room.wav'], 'loop': True, 'crossfade_ms': 100, 'gain_db': 0}},
        'bed': {'role': 'room', 'from_s': 0, 'to_s': None, 'fade_in_ms': 30, 'fade_out_ms': 30}})
    empty = save('empty.json', {'duration': 3, 'events': []})
    code, out = mix(empty, bed_palette, 'bed')
    bed = io.decode(ffmpeg, path('bed/bed.wav'))
    bed_mix = io.decode(ffmpeg, path('bed/mix.wav'))
    r = read('bed/mix-report.json')
    step = float(np.max(np.abs(np.diff(bed, axis=0))))
    record('chain: equal-power bed covers film; no loop sample step above 0.0001 FS',
           code == 0 and len(bed) == 3 * rate and np.min(bed[48:-48]) > 0 and step < .0001 and
           len(r['bed']['loop_starts_s']) >= 5 and abs(bed[0, 0]) < 1e-7 and abs(bed[-1, 0]) < 1e-7 and
           np.max(np.abs(bed_mix - bed)) < 1e-7,
           f'{len(bed)/rate}s; max step {step:.8f}; {len(r["bed"]["loop_starts_s"])} joins')

    # Low-crest but spectrally broad deterministic source: each preset should
    # reach its measured LUFS target and pass an actual independent AAC encode.
    t = np.arange(6 * rate) / rate
    balanced = (.055 * np.sin(2 * np.pi * 700 * t) + .035 * np.sin(2 * np.pi * 3300 * t))
    stereo = np.column_stack((balanced, balanced)).astype(np.float32)
    wav('balanced.wav', stereo)
    music_palette = {'version': 2, 'roles': {}, 'music': {'file': 'balanced.wav', 'fade_in_ms': 0,
                     'fade_out_ms': 0}, 'master': {'preset': 'social'}}
    duration = save('six.json', {'duration': 6, 'events': []})
    palette = save('master-palette.json', music_palette)
    for preset, target in (('social', -14), ('web', -16), ('broadcast', -23)):
        args = () if preset == 'social' else ('--master', preset)
        code, out = mix(duration, palette, 'master-' + preset, *args)
        r = read('master-' + preset + '/mix-report.json')
        # Independent encode and meter, not only the mixer's JSON assertion.
        encoded = path('independent-' + preset + '.m4a')
        io.run([ffmpeg, '-v', 'error', '-y', '-i', str(path('master-' + preset, 'mix.wav')),
                '-c:a', 'aac', '-b:a', '128k', str(encoded)])
        m = io.meter(ffmpeg, encoded)
        record('chain: ' + preset + ' master within 0.5 LU and AAC 128k <= -1 dBTP',
               code == 0 and abs(r['mix']['integrated_lufs'] - target) <= .5 and
               m['true_peak_dbtp'] <= -1 and abs(m['integrated_lufs'] - target) <= .5 and
               r['mastering']['max_gain_reduction_db'] <= 4,
               f'exit {code}; {r["mix"]["integrated_lufs"]} LUFS; AAC {m["true_peak_dbtp"]} dBTP')
    code, _ = mix(duration, palette, 'master-none', '--master', 'none')
    r = read('master-none/mix-report.json')
    record('chain: --master none overrides palette; no gain by default', code == 0 and r['gain_applied_db'] == 0 and
           r['mastering']['preset'] == 'none')
    # Rare isolated impulses over quiet body: normalisation would require >4 dB
    # reduction. Apply the highest gain within the cap and report the shortfall.
    extreme = stereo * .05
    extreme[rate:rate + 10] = .9
    wav('extreme.wav', extreme)
    loud_palette = dict(music_palette, music=dict(music_palette['music'], file='extreme.wav'))
    palette = save('extreme-palette.json', loud_palette)
    code, out = mix(duration, palette, 'refused')
    r = read('refused/mix-report.json')
    master = r['mastering']
    record('chain: >4 dB request uses the cap and reports a shortfall, exit 1',
           code == 1 and master['max_gain_reduction_db'] <= 4 and
           master['short_of_target'] is not None and r['gain_refused'] is None and
           r['gain_applied_db'] > 0,
           f'{master["max_gain_reduction_db"]:.3f} dB; {out.strip()[-150:]}')

    # A safe transient fixture forces a nonzero limiter gain reduction and tests
    # shared stem reconstruction rather than exercising gain-only masters.
    pulse = stereo.copy()
    pulse[2 * rate:2 * rate + 48] += .25
    wav('limited.wav', pulse)
    palette = save('limited-palette.json', dict(music_palette, music=dict(music_palette['music'], file='limited.wav')))
    code, out = mix(duration, palette, 'limited')
    r = read('limited/mix-report.json')
    stem_sum = sum(io.decode(ffmpeg, path('limited', s + '.wav')) for s in ('effects', 'music', 'bed'))
    mixed = io.decode(ffmpeg, path('limited/mix.wav'))
    record('chain: light limiter engages and stems reconstruct mastered mix', code == 0 and
           0 < r['mastering']['max_gain_reduction_db'] <= 4 and np.max(np.abs(stem_sum - mixed)) < 5e-7,
           f'exit {code}; reduction {r["mastering"]["max_gain_reduction_db"]:.3f} dB')

    # Merge, run thinning, per-role cap and total cap live in separated seconds.
    events = [
        {'id': 'weak', 't': .5, 'role': 'air', 'gain_db': -8},
        {'id': 'strong', 't': .54, 'role': 'tap', 'gain_db': 0},
        {'id': 'quiet', 't': .52, 'sound': 'silent', 'window_ms': 5},
        {'id': 'read', 't': 1.5, 'role': 'hold', 'reading_hold': True}]
    events += [{'id': 'key' + str(i), 't': 2 + i * .1, 'role': 'key'} for i in range(5)]
    events += [{'id': 'same' + str(i), 't': 4 + i * .25, 'role': 'tick'} for i in range(3)]
    events += [{'id': 'total' + str(i), 't': 6 + i * .15, 'role': 'r' + str(i)} for i in range(6)]
    spot_source = save('spot-source.json', {'duration': 8, 'events': events})
    before = spot_source.read_bytes()
    code, out = tool('spot_cues.py', spot_source, '--out-dir', path('spot'))
    spotted = read('spot/cues.spotted.json')
    rows = {e['id']: e for e in spotted['events']}
    record('chain: spotting merges strongest, thins runs, caps roles/total and preserves silence', code == 0 and
           rows['strong']['enabled'] and not rows['weak']['enabled'] and rows['strong']['layers'][0]['role'] == 'air' and
           rows['quiet']['sound'] == 'silent' and rows['read']['sound'] == 'silent' and
           [rows['key' + str(i)]['enabled'] for i in range(5)] == [True, True, False, False, False] and
           rows['key1']['sound'] == 'optional' and rows['key1']['texture'] and not rows['same2']['enabled'] and
           not rows['total5']['enabled'] and rows['total5']['sound'] == 'optional' and
           all(e['spotting'] for e in spotted['events']) and path('spot/spotting.csv').is_file() and
           spot_source.read_bytes() == before, out.strip())
    edits = save('edits.json', {'weak': {'action': 'keep', 'role': 'sub', 'gain': -3}, 'key4': 'keep',
                               'total0': 'drop', 'quiet': {'action': 'keep', 'role': 'air'}})
    code, _ = tool('spot_cues.py', spot_source, '--out-dir', path('edited'), '--edits', edits)
    rows = {e['id']: e for e in read('edited/cues.spotted.json')['events']}
    record('chain: edits apply last, restore merged/thinned choices and retain silence', code == 0 and
           rows['weak']['enabled'] and rows['weak']['role'] == 'sub' and rows['weak']['gain_db'] == -3 and
           rows['strong']['layers'] == [] and rows['key4']['enabled'] and not rows['total0']['enabled'] and
           rows['quiet']['sound'] == 'silent')
    # A spotted file with all disabled optional roles and silent holds can be
    # consumed without missing required events or unknown sound kinds.
    blank = np.zeros_like(stereo)
    wav('quiet.wav', blank)
    onsets = save('onset-spot-source.json', {'events': [
        {'id': 'a', 't': 1, 'role': 'tap'}, {'id': 'b', 't': 1.03, 'role': 'tap'},
        {'id': 'hold', 't': 3, 'sound': 'silent'}]})
    tool('spot_cues.py', onsets, '--out-dir', path('onset-spot'))
    # Place the retained pulse at t=1 using the original role fixture.
    basic = save('basic.json', {'version': 2, 'roles': {'tap': roles['tap']}})
    basic_data = json.loads(basic.read_text()); basic_data['roles']['tap'].pop('layers'); io.save_json(basic, basic_data)
    code_mix, _ = mix(path('onset-spot/cues.spotted.json'), basic, 'onset-mix', '--duration', 6)
    code, out = tool('cue_onsets.py', path('onset-mix/effects.wav'), path('onset-spot/cues.spotted.json'),
                     '--json', path('onset-check.json'))
    record('chain: cue_onsets and mixer accept spotted cues and omit withheld choices',
           code_mix == 0 and code == 0 and len(read('onset-check.json')['rows']) == 2, out.strip()[:180])

    def check(name, x, *args):
        wav(name + '.wav', x)
        code, out = tool('sound_check.py', path(name + '.wav'), '--json', path(name + '-check.json'), *args)
        return code, read(name + '-check.json'), out
    code, r, out = check('balanced-check', stereo)
    record('chain: balanced synthetic mix has no sound-check warnings', code == 0 and not r['warnings'], str(r['warnings']))
    bass = .1 * np.sin(2 * np.pi * 80 * t)
    code, r, _ = check('bass', np.column_stack((bass, bass)))
    record('chain: bass-only mix warns phone loss and upper energy', code == 1 and
           r['checks']['phone_band_loss']['warn'] and r['checks']['above_2khz']['warn'],
           f'phone {r["checks"]["phone_band_loss"]["loss_lu"]} LU; upper {r["checks"]["above_2khz"]["energy_share"]}')
    gap = stereo.copy(); gap[2 * rate:round(2.2 * rate)] = 0
    code, r, _ = check('gap', gap)
    record('chain: digital mid-film gap >50 ms warns', code == 1 and r['checks']['digital_silence']['warn'] and
           abs(r['checks']['digital_silence']['gaps'][0]['duration_ms'] - 200) < .1)
    code, r, _ = check('declared-gap', gap, '--silent', '2-2.2')
    record('chain: declared silent window suppresses digital gap warning', code == 0 and not r['checks']['digital_silence']['warn'],
           str(r['warnings']))
    end = stereo.copy(); end[round(.9 * len(end)):] *= 2
    code, r, _ = check('loud-end', end)
    record('chain: ending louder than body warns', code == 1 and r['checks']['ending']['warn'] and
           r['checks']['ending']['difference_lu'] > 5, str(r['checks']['ending']))
    code, r, _ = check('dense-cues', stereo, '--cues', spot_source)
    record('chain: sound_check counts cue layers against rolling limits', code == 1 and r['layers_per_second']['warn'])
    code, r, _ = check('spotted-cues', stereo, '--cues', path('spot/cues.spotted.json'))
    record('chain: spotted list satisfies sound-check density limits', code == 0 and not r['layers_per_second']['warn'], str(r['warnings']))
    for script, args in (('spot_cues.py', [path('gone.json')]), ('sound_check.py', [path('gone.wav')])):
        code, _ = tool(script, *args)
        record('chain: ' + script + ' unreadable input returns 2', code == 2)
    # Exact boundaries are exclusive, and rolling windows must also catch
    # density across integer-second boundaries, not only in second buckets.
    boundaries = save('boundaries.json', {'events': [
        {'id': 'm0', 't': 0, 'role': 'a'}, {'id': 'm60', 't': .06, 'role': 'b'},
        {'id': 'r0', 't': 2, 'role': 'r'}, {'id': 'r120', 't': 2.12, 'role': 'r'},
        {'id': 'w0', 't': 4.8, 'role': 'w'}, {'id': 'w1', 't': 5.1, 'role': 'w'},
        {'id': 'w2', 't': 5.4, 'role': 'w'}, {'id': 'w3', 't': 5.8, 'role': 'w'}]})
    code, _ = tool('spot_cues.py', boundaries, '--out-dir', path('boundaries'))
    rows = {e['id']: e for e in read('boundaries/cues.spotted.json')['events']}
    record('chain: spotting boundaries at 60/120 ms and rolling one-second limits', code == 0 and
           rows['m0']['enabled'] and rows['m60']['enabled'] and not rows['m0'].get('layers') and
           rows['r120'].get('sound', 'required') == 'required' and not rows['w2']['enabled'] and rows['w3']['enabled'])
    # Three role layers plus three explicit layers exceed five even though
    # there is only one visible event. Omit nested role layers by contract.
    density_palette = save('density-palette.json', {'version': 2, 'roles': {'a': {
        'layers': [{'role': 'b'}, {'role': 'c'}]}, 'b': {'layers': [{'role': 'nested'}]}}})
    dense = save('layer-density.json', {'events': [{'id': 'layers', 't': 1, 'role': 'a',
        'layers': [{'role': 'd'}, {'role': 'e'}, {'role': 'f'}]}]})
    code, r, _ = check('palette-density', stereo, '--cues', dense, '--palette', density_palette)
    record('chain: sound_check includes non-recursive palette and event layers', code == 1 and
           r['layers_per_second']['windows'][0]['layers'] == 6 and
           'nested' not in r['layers_per_second']['windows'][0]['by_role'])
    code, _ = tool('spot_cues.py', dense, '--palette', density_palette, '--out-dir', path('layer-cap'))
    record('chain: spotting caps composite layers when palette supplied', code == 0 and
           not read('layer-cap/cues.spotted.json')['events'][0]['enabled'])
    bad_palette = save('invalid-palette.json', [])
    codes = [tool('spot_cues.py', spot_source, '--palette', bad_palette)[0],
             tool('sound_check.py', path('balanced.wav'), '--palette', bad_palette)[0],
             tool('spot_cues.py', spot_source, '--edits', save('unknown-edits.json', {'gone': 'keep'}))[0]]
    record('chain: malformed palette and unknown edit ids return 2', codes == [2, 2, 2], str(codes))
    compatible = []
    for script in ('mix_cues.py', 'cue_onsets.py', 'spot_cues.py', 'sound_check.py', 'selftest.py', 'selftest_cases/chain.py'):
        ast.parse((Path(scripts_dir) / script).read_text(encoding='utf-8'), feature_version=(3, 9))
        compatible.append(script)
    record('chain: changed files parse as Python 3.9', len(compatible) == 6)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--scripts', required=True); p.add_argument('--keep', required=True)
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
        run_chain_cases(tool, record, lambda *parts: str(root.joinpath(*parts)), scripts)
    except Exception as exc:
        record('chain cases ran to the end', False, repr(exc))
    (root / 'results.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(f'{sum(r["ok"] for r in results)}/{len(results)} checks passed.')
    return 0 if all(r['ok'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
