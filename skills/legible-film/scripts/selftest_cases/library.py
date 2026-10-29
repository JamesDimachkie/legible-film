#!/usr/bin/env python3
"""Known-answer library cases loaded by selftest.py, or runnable standalone.

selftest.py calls run_library_cases(tool, record, j, HERE). Run alone with:
  python -I scripts/selftest_cases/library.py --scripts scripts --keep work/library-tests

Synthetic evidence only: shape, ranking, licence exclusion, hashes, mixer
compatibility and measured sync. No network, playback or quality verdict.
Exit 0 all passed, 1 any failure, 2 could not run.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import numpy as np


def run_library_cases(tool, record, j, scripts_dir):
    def load(name):
        spec = importlib.util.spec_from_file_location(name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    lib, io = load('sound_library'), load('sound_io')
    ffmpeg = io.find_tool('ffmpeg')
    root = Path(j('library-input')); root.mkdir(parents=True, exist_ok=True)
    rate = 48000
    def save(name, y, licensed=True):
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        io.write_wav(ffmpeg, folder / (name + '.wav'), np.column_stack((y, y)), rate)
        if licensed:
            io.save_json(folder / 'licence.json', {'licence': 'CC0 1.0', 'source_url': 'synthetic:test',
                                                  'attribution': 'Synthetic fixture: ' + name, 'date': '2026-10-28'})
    # Separate analytic envelopes, not the production generator under test.
    t = np.arange(round(.55 * rate)) / rate
    impact = .45 * np.sin(2 * np.pi * 160 * t) * np.exp(-np.maximum(t - .025, 0) / .065) * (t >= .025)
    save('IMPCT_sharp', impact)
    save('IMPCT_sharp_variant', impact * .8)
    t = np.arange(rate) / rate
    whoosh = .35 * np.sin(2 * np.pi * 2100 * t) * np.sin(np.pi * t) ** 5
    save('WHSH_soft', whoosh)
    t = np.arange(round(1.2 * rate)) / rate
    riser = .35 * np.sin(2 * np.pi * 700 * t) * (t / 1.2) ** 2
    save('riser_clean', riser)
    t = np.arange(round(.09 * rate)) / rate
    tick = .35 * np.sin(2 * np.pi * 6500 * t) * np.exp(-np.maximum(t - .015, 0) / .005) * (t >= .015)
    save('tick_bright', tick)
    save('IMPCT_too_long', np.tile(impact, 30))
    save('customdroid', tick, False)
    save('silence', np.zeros(rate))
    # Source-channel/rate preservation and side-energy measurement.
    stereo_dir = root / 'wide'; stereo_dir.mkdir(exist_ok=True)
    z = .1 * np.sin(2 * np.pi * 1000 * np.arange(16000 * 4) / 16000)
    io.write_wav(ffmpeg, j('wide-source.wav'), np.column_stack((z, -z)), 16000)
    io.run([ffmpeg, '-v', 'error', '-y', '-i', j('wide-source.wav'), '-c:a', 'flac', str(stereo_dir / 'wide.flac')])
    io.save_json(stereo_dir / 'licence.json', {'licence': 'CC0 1.0'})
    report_path = j('library.json')
    code, text = tool('sound_library.py', 'index', root, '--out', report_path)
    record('sound_library: index valid files exit 0', code == 0, text.strip()[:200])
    library = json.loads(Path(report_path).read_text())
    rows = {Path(r['path']).stem: r for r in library['files']}
    sharp, soft, rise = rows['IMPCT_sharp'], rows['WHSH_soft'], rows['riser_clean']
    record('sound_library: UCS tags expanded', 'impact' in sharp['tags'] and 'whoosh' in soft['tags'])
    record('sound_library: durations and native metadata', abs(sharp['duration_s'] - .55) < 1 / rate
           and rows['wide']['channels'] == 2 and rows['wide']['sample_rate'] == 16000)
    record('sound_library: sharp impact rise and decaying tail', sharp['attack_rise_s'] < .01
           and sharp['tail_energy_ratio'] < .1, str((sharp['attack_rise_s'], sharp['tail_energy_ratio'])))
    record('sound_library: whoosh central apex and soft rise', .45 < soft['points_s']['apex'] < .55
           and soft['attack_rise_s'] > sharp['attack_rise_s'], str(soft['points_s']))
    record('sound_library: riser energy and clean terminal end', rise['riser_shape'] > .8
           and rise['end_clean'] and abs(rise['points_s']['end'] - 1.2) <= .002, str(rise['points_s']))
    record('sound_library: spectrum distinguishes low impact and bright tick', sharp['energy_shares']['low'] > .9
           and rows['tick_bright']['energy_shares']['high'] > .9
           and rows['tick_bright']['spectral_centroid_hz'] > 6000)
    record('sound_library: channel energy survives antiphase; width near one', rows['wide']['stereo_width'] > .99
           and 950 < rows['wide']['spectral_centroid_hz'] < 1050)
    record('sound_library: real ST LUFS only for >=3 seconds', soft['short_term_lufs']['max'] is None
           and rows['wide']['short_term_lufs']['max'] is not None and sharp['integrated_lufs'] is not None)
    record('sound_library: unlicensed file retained, marked', not rows['customdroid']['licensed'])
    neutral = [dict(r, tags=[]) for r in (sharp, soft, rise, rows['tick_bright'])]
    shape_winners = []
    for role, sync in (('impact', 'attack'), ('whoosh', 'apex'), ('riser', 'end'), ('tick', 'attack')):
        scores = [(lib.candidate_score(r, role, [{'sync': sync, 'next_s': 3, 'previous_s': 3}])[0], i)
                  for i, r in enumerate(neutral)]
        shape_winners.append(max((score, i) for score, i in scores if score is not None)[1])
    record('sound_library: measured shape ranks correctly without filename tags', shape_winners == [0, 1, 2, 3], str(shape_winners))
    # Fixture sync includes attack/apex/end, and repeat variants.
    cues = {'duration': 9, 'events': [
        {'id': 'impact-1', 't': 1, 'role': 'impact', 'sync': 'attack'},
        {'id': 'whoosh-1', 't': 3, 'role': 'whoosh', 'sync': 'apex'},
        {'id': 'riser-1', 't': 5, 'role': 'riser', 'sync': 'end'},
        {'id': 'tick-1', 't': 6, 'role': 'tick', 'sync': 'attack'},
        {'id': 'impact-2', 't': 7, 'role': 'impact', 'sync': 'attack'}]}
    for ev in cues['events']:
        ev.update(sound='required', tolerance_ms=2, window_ms=150)
    io.save_json(j('library-cues.json'), cues)
    palette_path = j('library-palette.json')
    code, text = tool('sound_library.py', 'pick', j('library-cues.json'), report_path, '--out', palette_path, '--takes', 3)
    record('sound_library: pick fills known roles exit 0', code == 0, text.strip()[:250])
    palette = json.loads(Path(palette_path).read_text())
    expected = {'impact': 'IMPCT_sharp', 'whoosh': 'WHSH_soft', 'riser': 'riser_clean', 'tick': 'tick_bright'}
    record('sound_library: shape/tag ranking chooses correct files, rejects long take',
           all(Path(palette['roles'][role]['take_records'][0]['source_file']).stem.startswith(name)
               for role, name in expected.items()) and
           all('too_long' not in r['source_file'] for rs in palette['roles'].values() for r in rs['take_records']))
    hashes, family, matched = True, True, True
    for role, rs in palette['roles'].items():
        hashes &= all(lib.sha256(Path(palette_path).parent / p) == h for p, h in zip(rs['takes'], rs['sha256']))
        family &= len({r['source_sha256'] for r in rs['take_records']}) == len(rs['takes'])
        values = [r['matched_level'] for r in rs['take_records']]
        matched &= max(values) - min(values) < .2
    record('sound_library: materialised take hashes and distinct source takes', hashes and family)
    record('sound_library: variants level matched without mixer changes', matched and len(palette['roles']['impact']['takes']) == 2)
    code, text = tool('mix_cues.py', j('library-cues.json'), palette_path, '--out-dir', j('library-mix'))
    record('sound_library: existing mixer accepts palette and places every event', code == 0, text.strip()[:150])
    code, text = tool('cue_onsets.py', j('library-mix', 'effects.wav'), j('library-cues.json'), '--json', j('library-sync.json'))
    measured = json.loads(Path(j('library-sync.json')).read_text())
    record('sound_library: delivered stem attack/apex/end all within 2 ms', code == 0 and
           len(measured['rows']) == len(cues['events']) and all(abs(r.get('offset_ms', 99)) <= 2 for r in measured['rows']),
           str([(r['id'], r.get('offset_ms'), r['status']) for r in measured['rows']]))
    record('sound_library: prints delivery credits', bool(palette['attributions']))
    # Determinism includes byte-identical PCM and metadata (no timestamps).
    original = Path(palette_path).read_bytes()
    code, _ = tool('sound_library.py', 'pick', j('library-cues.json'), report_path, '--out', palette_path, '--takes', 3)
    record('sound_library: seed reproduces palette bytes', code == 0 and Path(palette_path).read_bytes() == original)
    io.save_json(j('custom-cues.json'), {'events': [{'t': 1, 'role': 'customdroid'}]})
    code, _ = tool('sound_library.py', 'pick', j('custom-cues.json'), report_path, '--out', j('blocked-palette.json'))
    blocked = json.loads(Path(j('blocked-palette.json')).read_text())
    record('sound_library: unlicensed exclusion exit 1 with reason', code == 1 and not blocked['roles'] and
           blocked['missing_roles'][0]['rejections']['no licence information'] == 1)
    code, _ = tool('sound_library.py', 'pick', j('custom-cues.json'), report_path, '--allow-unlicensed', '--out', j('override-palette.json'))
    override = json.loads(Path(j('override-palette.json')).read_text())
    record('sound_library: override explicit, disclosed, exit 1', code == 1 and bool(override['roles']) and bool(override['warnings']))
    # CSV, nearest-folder evidence and per-file overrides have deterministic precedence.
    csv_path = Path(j('licences.csv'))
    csv_path.write_text('path,licence,source_url,attribution,date\ncustom*/*.wav,CC BY 4.0,synthetic:test,Fixture author,2026-10-28\n', encoding='utf-8')
    found = lib.licence_for(root / 'customdroid' / 'customdroid.wav', root, lib.licences_csv(csv_path), csv_path)
    record('sound_library: CSV globs and attribution', found['licensed'] and found['attribution'] == 'Fixture author')
    io.save_json(str(root / 'customdroid' / 'customdroid.wav') + '.licence.json', {'licence': 'CC0 1.0'})
    found = lib.licence_for(root / 'customdroid' / 'customdroid.wav', root, [], None)
    record('sound_library: per-file licence sidecar', found['licensed'] and found['licence'] == 'CC0 1.0')
    text_folder = root / 'text-grant'; text_folder.mkdir(exist_ok=True)
    (text_folder / 'LICENCE.txt').write_text('Permission to use this synthetic fixture in films.', encoding='utf-8')
    found = lib.licence_for(text_folder / 'not-needed.wav', root, [], None)
    record('sound_library: folder LICENCE.txt evidence', found['licensed'] and 'Permission' in found['licence'])
    # Exercise the actual make_film sound path without doing another picture render.
    make = load('make_film')
    a = SimpleNamespace(name=None, res='1080', resume=True, ffmpeg=None, ffprobe=None, node=None,
                        playwright=None, browser=None, drop_beat=None)
    m = make.Make(a, Path(j('make-film')), Path(j('make-library')), [(320, 180)])
    m.sound_mode = 'library:' + str(root)
    sound = m.sound({'frames': 270, 'fps': 30}, Path(j('library-cues.json')))
    record('make_film: library folder indexed, picked and mixed without changing mixer', sound['exit'] == 0 and
           not sound['missing_roles'] and (m.out / 'library/library.json').is_file())
    m.old_steps = dict(m.state['steps'])
    sound = m.sound({'frames': 270, 'fps': 30}, Path(j('library-cues.json')))
    record('make_film: library index reused with intact hashes', m.state['steps']['sound library index']['resumed'])
    grant_path = root / 'WHSH_soft/licence.json'
    grant = json.loads(grant_path.read_text()); grant['attribution'] = 'Changed credit'
    io.save_json(grant_path, grant)
    m.old_steps = dict(m.state['steps'])
    sound = m.sound({'frames': 270, 'fps': 30}, Path(j('library-cues.json')))
    record('make_film: licence edit invalidates library index', not m.state['steps']['sound library index']['resumed'] and
           'Changed credit' in json.loads(Path(sound['palette']).read_text())['attributions'])
    bad = root / 'broken.wav'; bad.write_bytes(b'not audio')
    code, _ = tool('sound_library.py', 'index', root, '--out', j('partial-index.json'))
    record('sound_library: decode error preserved, partial index exit 1', code == 1 and
           len(json.loads(Path(j('partial-index.json')).read_text())['errors']) == 1)
    # No actual network: mock API failure still exercises main's exit/report path.
    old_fetch = lib.fetch
    lib.fetch = lambda *args: (_ for _ in ()).throw(OSError('synthetic API unreachable'))
    old_argv = sys.argv
    sys.argv = ['sound_library.py', 'search', 'whoosh', '--openverse', '--out', j('no-network'),
                '--rate-state', j('mock-rate.json'), '--json', j('network-error.json')]
    try:
        code = lib.main()
    finally:
        lib.fetch = old_fetch; sys.argv = old_argv
    record('sound_library: unreachable API exit 2 and reason', code == 2 and
           'synthetic API unreachable' in json.loads(Path(j('network-error.json')).read_text())['error'])
    # Mock network bytes exercise the real strict licence gate and decoder.
    calls = []
    def fake_fetch(url, limit):
        calls.append(url)
        if '/v1/audio/' in url:
            return json.dumps({'results': [dict(id=c, license=c, license_version='1.0' if c == 'cc0' else '4.0',
                  duration=550, url='https://example.org/' + c, title='Fixture', creator='Fixture author',
                  foreign_landing_url='https://example.org/source') for c in ('by-nc', 'by-nd', 'by-sa', 'cc0', 'by')]}).encode()
        return (root / 'IMPCT_sharp/IMPCT_sharp.wav').read_bytes()
    lib.fetch = fake_fetch
    try:
        fetched = lib.search_openverse(SimpleNamespace(ffmpeg=None, ffprobe=None, openverse=True, max=5,
                  out=j('mock-downloads'), rate_state=j('mock-fetch-rate.json'), query='impact', licence=None))
    finally:
        lib.fetch = old_fetch
    record('sound_library: downloader rejects NC/ND/SA before fetching bytes', len(fetched['downloaded']) == 2 and
           len(fetched['rejected']) == 3 and len(calls) == 3 and fetched['exit_code'] == 1)
    record('sound_library: downloaded licence records ready for index', all(
           Path(r['file']).with_name('licence.json').is_file() and r['creator'] == 'Fixture author' and r['date'] and
           r['licence'] in ('CC0 1.0', 'CC BY 4.0') for r in fetched['downloaded']))
    rate_path = Path(j('exhausted-rate.json'))
    io.save_json(rate_path, [lib.time.time()] * 5)
    refused = False
    try:
        lib.reserve_request(rate_path)
    except ValueError as exc:
        refused = 'budget exhausted' in str(exc)
    record('sound_library: persistent anonymous rate budget enforced', refused)
    for args in (('index', j('gone-dir')), ('pick', j('gone.json'), report_path),
                 ('pick', j('library-cues.json'), report_path, '--takes', 0),
                 ('search', 'whoosh', '--openverse', '--max', 21),
                 ('index', root, '--ffmpeg', j('no-ffmpeg'))):
        code, _ = tool('sound_library.py', *args)
        record('sound_library: invalid input/tools exit 2 ' + str(args[0:2]), code == 2)
    source = (Path(scripts_dir) / 'sound_library.py').read_text(encoding='utf-8')
    ast.parse(source, feature_version=(3, 9))
    record('sound_library: Python 3.9 grammar', True)
    print('SKIP  Openverse live network cases: optional, offline selftest; run bounded real trial separately.', flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
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
        run_library_cases(tool, record, lambda *parts: str(root.joinpath(*parts)), scripts)
    except Exception as exc:
        record('runner completed', False, repr(exc))
    (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    passed = sum(r['ok'] for r in results)
    print(f'{passed}/{len(results)} checks passed.')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
