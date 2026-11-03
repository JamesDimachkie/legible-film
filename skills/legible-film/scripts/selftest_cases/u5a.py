"""Known-answer cases for the listening and checking lane."""

import contextlib
import io
import json
import importlib.util
import os
import subprocess
import sys
from types import SimpleNamespace
import wave

import numpy as np


def write_audio(path, samples, rate=48000):
    data = np.clip(samples * 32767, -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(data.tobytes())


def run_u5a_cases(tool, record, j, scripts_dir):
    """Exercise content between transport samples and a quiet changed word."""
    rate = 48000
    random = np.random.default_rng(715)
    reference = random.normal(0, 0.05, 8 * rate)
    quiet = slice(3 * rate, round(3.2 * rate))
    reference[quiet] = random.normal(0, 10 ** (-35 / 20), quiet.stop - quiet.start)
    changed = reference.copy()
    changed[quiet] = random.normal(0, 10 ** (-35 / 20), quiet.stop - quiet.start)
    write_audio(j('u5a-reference.wav'), reference)
    write_audio(j('u5a-changed.wav'), changed)
    report = j('u5a-outside.json')
    code, output = tool('sync_check.py', j('u5a-changed.wav'), j('u5a-reference.wav'),
                        '--outside', '5,6', '--json', report)
    data = json.load(open(report, encoding='utf-8')) if os.path.exists(report) else {}
    outside = data.get('outside', {})
    changed_rows = outside.get('changed', [])
    record('outside: a quiet changed word between transport windows is found',
           code == 1 and any(3 <= row['start_s'] < 3.2 for row in changed_rows), output[-200:])
    spec = importlib.util.spec_from_file_location('u5a_sync', os.path.join(scripts_dir, 'sync_check.py'))
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    stereo = np.column_stack((reference, reference))
    same = sync.compare_outside(stereo, stereo.copy(), (5, 6), 0)
    truncated = sync.compare_outside(stereo, stereo[:-rate], (5, 6), 0)
    quiet_stereo = stereo.copy()
    quiet_stereo[-rate:] = 0
    quiet = sync.compare_outside(quiet_stereo, quiet_stereo, (5, 6), 0)
    record('outside: identical, silent and truncated content are distinguished',
           same['verdict'] == 'unchanged within tolerance'
           and 'inconclusive' in truncated['verdict'] and 'inconclusive' in quiet['verdict'],
           f"same={same['verdict']}, truncated={truncated['verdict']}, quiet={quiet['verdict']}")
    changed_everywhere = sync.compare_outside(stereo, .8 * stereo, (5, 6), 0)
    record('outside: a widespread change cannot be hidden by its own residual floor',
           changed_everywhere['verdict'] != 'unchanged within tolerance', str(changed_everywhere['verdict']))
    write_audio(j('u5a-silent.wav'), np.zeros(rate))
    path = j('u5a-silent-outside.json')
    code, output = tool('sync_check.py', j('u5a-silent.wav'), j('u5a-silent.wav'),
                        '--outside', '.2,.5', '--json', path)
    result = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
    record('outside: short silent material is inconclusive',
           code == 1 and 'inconclusive' in result.get('outside', {}).get('verdict', ''), output[-160:])

    source = os.path.join(scripts_dir, 'listen.py')
    help_run = subprocess.run([sys.executable, '-I', '-S', source, '--help'], capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    help_output = help_run.stdout + help_run.stderr
    record('listen: missing NumPy gives a setup command without a traceback',
           (help_run.returncode == 0 or (help_run.returncode == 2 and 'setup.py' in help_output))
           and 'Traceback' not in help_output, help_output[-250:])
    if not os.path.isfile(source):
        record('listen: matched lag and band null with inconclusive signals', False, 'listen.py is missing')
        return
    spec = importlib.util.spec_from_file_location('u5a_listen', source)
    listen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(listen)
    points = random.normal(size=60)
    curve = np.interp(np.arange(240), np.arange(0, 240, 4), points)
    linked = listen.follow_coupling(curve, {'mid': curve.copy()}, seed=10, iterations=200)
    saved_load, saved_sync = listen.load_cues, listen.sync_measure
    try:
        listen.load_cues = lambda *args: ({'events': []}, 'fresh')
        listen.sync_measure = lambda *args, **kwargs: {
            'source': 'full mix', 'frame_change_at_cue': {}, 'sound_follows_list': {},
            'turn_leads': [], 'follow': [linked], 'silence': []}
        outputs = []
        for extra in ([], ['--json']):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = listen.main(['sync', 'fixture.wav', '--cues', 'fixture.json', '--seed', '10'] + extra)
            outputs.append((code, output.getvalue()))
    finally:
        listen.load_cues, listen.sync_measure = saved_load, saved_sync
    record('listen sync: follow output is an uncalibrated screen with n, seed and spread',
           all(code == 0 and 'uncalibrated' in output.lower() and 'screen' in output.lower()
               and 'p_value' not in output.lower() and 'significant' not in output.lower()
               and 'coupled' not in output.lower() and 'not distinguishable' not in output.lower()
               for code, output in outputs)
           and linked.get('n') == 240 and linked.get('seed') == 10
           and len(linked.get('null_spread', [])) == 2, str(outputs))
    unrelated = [listen.follow_coupling(curve, {'mid': random.normal(size=len(curve))},
                                        seed=10, iterations=200) for _ in range(10)]
    flat = listen.follow_coupling(curve, {'mid': np.zeros(len(curve))}, seed=10, iterations=200)
    short = listen.follow_coupling(curve[:20], {'mid': curve[:20]}, seed=10, iterations=200)
    periodic = np.sin(np.arange(240) * 2 * np.pi / 40)
    repeating = listen.follow_coupling(periodic, {'mid': periodic}, seed=10, iterations=200)
    trend = np.linspace(0, 1, len(curve))
    trending = listen.follow_coupling(trend, {'mid': trend}, seed=10, iterations=200)
    record('listen: matched lag and band null with inconclusive signals',
           linked['state'] == 'screening' and linked['best_r'] > 0.9
           and linked['null_p95'] < linked['best_r']
           and unrelated[1]['best_r'] <= unrelated[1]['null_p95']
           and flat['state'] == repeating['state'] == 'inconclusive'
           and short['state'] == 'not assessed' and short.get('reason') == 'span under 2 s',
           f"linked={linked}, unrelated={[row['best_r'] for row in unrelated]}, "
           f"flat={flat}, short={short}, periodic={repeating}")
    record('listen: a rising trend is not treated as a periodic signal',
           trending['state'] == 'screening', str(trending))
    motion_rng = np.random.default_rng(777)
    motion = np.interp(np.arange(240), np.arange(0, 240, 4), motion_rng.normal(size=60))
    offset = listen.follow_coupling(motion, {'mid': np.r_[np.zeros(6), motion[:-6]]}, seed=10, iterations=200)
    counter = listen.follow_coupling(motion, {'mid': -motion}, seed=10, iterations=200)
    shuffled = listen.follow_coupling(motion, {'mid': np.roll(motion, 50)}, seed=10, iterations=200)
    single = listen.follow_coupling(motion, {'mid': motion}, seed=10, iterations=200)
    multi = listen.follow_coupling(motion, {'mid': motion, 'high': motion_rng.normal(size=240)},
                                   seed=10, iterations=200)
    record('listen: offset, counterpoint and circular-shift controls',
           offset['best_r'] > .9 and abs(offset['lag_s'] - .3) <= .05
           and counter['best_r'] <= counter['null_p95'] and shuffled['best_r'] <= shuffled['null_p95']
           and multi['null_p95'] >= single['null_p95'],
           f"offset={offset}, counter={counter}, shuffled={shuffled}, multi={multi}")
    if not hasattr(listen, 'frame_screens'):
        record('listen: cue frame-change screen and intentional holds', False, 'frame_screens missing')
    else:
        times = np.arange(90) / 30
        differences = np.zeros(90)
        differences[30] = .5
        frames = listen.frame_screens(times, differences, [
            {'id': 'cut', 't': 1., 'scale': 'turn'},
            {'id': 'still', 't': 2., 'scale': 'contact'},
            {'id': 'held', 't': 2., 'scale': 'contact', 'picture': 'held'},
            {'id': 'sound-only', 't': 2., 'scale': 'contact', 'picture': 'none'}])
        record('listen: cue frame-change screen and intentional holds',
               [row['state'] for row in frames] == ['change', 'look', 'skipped', 'skipped'], str(frames))
    if not hasattr(listen, 'picture_alignment'):
        record('listen transcript: onset to picture candidate uses the supplied time map', False,
               'picture_alignment missing')
    else:
        times = np.arange(90) / 30
        differences = np.zeros(90)
        differences[30] = .5
        aligned = listen.picture_alignment([{'t': .5}], {'times': times, 'differences': differences}, offset=.5)
        record('listen transcript: onset to picture candidate uses the supplied time map',
               len(aligned['events']) == 1 and abs(aligned['events'][0]['offset_ms']) < 1, str(aligned))
        local_grid = np.full((90, 16), .1)
        local_grid[30, 0] = .9
        local = listen.picture_candidates({'times': times, 'differences': np.full(90, .1), 'grid': local_grid,
                                           'scene': np.zeros(90)})
        record('listen: a local picture change can be a candidate',
               any(abs(row['t'] - 1) < .001 for row in local), str(local))
    original_helpers = (listen.transcript, listen.load_cues, listen.sync_measure, listen.video_activity,
                        listen.picture_alignment)
    try:
        listen.transcript = lambda path, detail: {'events': [], 'sections': [],
                                                  'picture_sync': 'not assessed', 'limit': 'fixture'}
        listen.load_cues = lambda path, owner=None: ({'events': []}, 'fresh')
        listen.sync_measure = lambda *args, **kwargs: {'frame_change_at_cue': {'state': 'measured'}}
        listen.video_activity = lambda path: {'times': np.arange(4)}
        listen.picture_alignment = lambda events, picture, offset=0: {'state': 'measured', 'time_map': 'fixture'}
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            code = listen.main(['transcript', 'fixture.wav', '--cues', 'fixture.json', '--video', 'fixture.mp4', '--json'])
        transcript_result = json.loads(captured.getvalue())
    finally:
        (listen.transcript, listen.load_cues, listen.sync_measure, listen.video_activity,
         listen.picture_alignment) = original_helpers
    record('listen transcript: cut sync remains present when a cue list is also supplied',
           code == 0 and isinstance(transcript_result.get('picture_sync'), dict)
           and transcript_result['picture_sync'].get('state') == 'measured'
           and 'cue_sync' in transcript_result, str(transcript_result))
    if not hasattr(listen, 'coincidence'):
        record('listen: onset-to-picture coincidence includes a seeded chance distribution', False,
               'coincidence missing')
    else:
        sample_times = np.array([.4, 1.7, 3.25, 5.13, 7.3])
        measured = listen.coincidence(sample_times, sample_times + .01, .03, 9, seed=7, iterations=500)
        record('listen: onset-to-picture coincidence includes a seeded chance distribution',
               measured['n'] == 5 and measured['observed'] == 1 and measured['chance_p95'] < 1
               and measured['seed'] == 7 and len(measured['spread']) == 2, str(measured))

    sample = random.normal(0, .0002, 8 * rate)
    sample[4 * rate:] += random.normal(0, .01, 4 * rate)
    targets = [1.0, 2.0, 3.0, 5.0, 6.0, 7.0]
    for target in targets:
        start = int(target * rate)
        sample[start:start + 4800] += random.normal(0, .4, 4800) * np.exp(-np.arange(4800) / 300)
    write_audio(j('u5a-events.wav'), sample)
    code, output = tool('listen.py', 'sync', j('u5a-events.wav'), '--candidates', '--json')
    try:
        candidate_data = json.loads(output)
    except ValueError:
        candidate_data = {}
    record('listen sync: candidate discovery needs no cue list',
           code == 0 and isinstance(candidate_data.get('candidates'), list)
           and candidate_data.get('frame_change_at_cue', {}).get('state') == 'not assessed'
           and candidate_data.get('sound_follows_list', {}).get('state') == 'not assessed', output[-250:])
    code, output = tool('listen.py', 'sync', j('u5a-events.wav'), '--json')
    record('listen sync: a cue list is required outside candidate discovery', code == 2, output[-200:])
    code, output = tool('listen.py', 'transcript', j('u5a-events.wav'), '--json')
    try:
        data = json.loads(output)
    except ValueError:
        data = {}
    events = [row['t'] for row in data.get('events', [])]
    sections = data.get('sections', [])
    record('listen transcript: known attacks within 10 ms and a level change',
           code == 0 and all(any(abs(t - target) <= .01 for t in events) for target in targets)
           and any(abs(row['t'] - 4) <= .3 for row in sections), output[-300:])
    stereo = np.column_stack((sample, -sample))
    stereo_path = j('u5a-antiphase.wav')
    with wave.open(str(stereo_path), 'wb') as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(np.clip(stereo * 32767, -32768, 32767).astype('<i2').tobytes())
    code, output = tool('listen.py', 'transcript', stereo_path, '--json')
    try:
        stereo_data = json.loads(output)
    except ValueError:
        stereo_data = {}
    stereo_events = [row['t'] for row in stereo_data.get('events', [])]
    activity = listen.audio_activity(stereo)
    record('listen: stereo phase cancellation does not erase attacks, changes or activity',
           code == 0 and all(any(abs(t - target) <= .01 for t in stereo_events) for target in targets)
           and any(abs(row['t'] - 4) <= .3 for row in stereo_data.get('sections', []))
           and float(np.max(activity['bands']['all'])) > 0, output[-200:])
    code, output = tool('listen.py', 'measure', j('u5a-events.wav'), '--json')
    try:
        meters = json.loads(output)
    except ValueError:
        meters = {}
    t = np.arange(rate) / rate
    tone = np.sin(2 * np.pi * 40 * t) * .2
    opposite = listen.spectrum(np.column_stack((tone, -tone)))
    figures = meters.get('measurements', {})
    record('listen measure: loudness, peak, spectrum and seven-film ranges',
           code == 0 and figures.get('integrated_lufs') is not None and figures.get('true_peak_dbtp') is not None
           and bool(figures.get('spectrum_db')) and meters.get('reference', {}).get('label') == 'seven launch films (n = 7)'
           and opposite.get('sub', -100) > -1, f"meters={figures}, antiphase sub={opposite.get('sub')}")
    write_audio(j('u5a-long-silent.wav'), np.zeros(8 * rate))
    code, output = tool('listen.py', 'measure', j('u5a-long-silent.wav'), '--json')
    try:
        silent = json.loads(output).get('measurements', {})
    except ValueError:
        silent = {}
    record('listen measure: silence is not assigned a loudness range',
           code == 0 and silent.get('integrated_lufs') is None and silent.get('lra_lu') is None
           and not silent.get('spectrum_db'), str(silent))

    cue_file = j('u5a-cues.json')
    with open(cue_file, 'w', encoding='utf-8') as stream:
        json.dump({'version': 'v2', 'fps': 30, 'picture': {'kind': 'picture', 'sha256': '0' * 64},
                   'events': [
            {'id': 'contact', 't': 1., 'scale': 'contact', 'sound': 'required'},
            {'id': 'turn', 't': 2., 'scale': 'turn', 'lead_ms': 100, 'sound': 'required'},
            {'id': 'follow', 't': 3., 't_end': 5., 'scale': 'follow'}]}, stream)
    audio = np.zeros(4 * rate)
    for at in (1., 2.1):
        i = round(at * rate)
        audio[i:i + 1500] = random.normal(0, .35, 1500) * np.exp(-np.arange(1500) / 200)
    write_audio(j('u5a-cues.wav'), audio)
    stereo_report = j('u5a-stereo-onsets.json')
    code, output = tool('cue_onsets.py', stereo_path, cue_file, '--json', stereo_report)
    stereo_rows = json.load(open(stereo_report, encoding='utf-8')).get('rows', []) if os.path.exists(stereo_report) else []
    record('cue onsets: opposite-phase stereo keeps the audible contact',
           code == 0 and len(stereo_rows) == 1 and stereo_rows[0].get('status') == 'on cue', output[-250:])
    reference_path = j('u5a-antiphase-reference.wav')
    write_audio(reference_path, sample[rate:rate + 2400])
    absence_report = j('u5a-antiphase-absence.json')
    code, output = tool('cue_onsets.py', stereo_path, cue_file, '--reference', 'contact=' + reference_path,
                        '--expect-absent', '--json', absence_report)
    absence_rows = json.load(open(absence_report, encoding='utf-8')).get('rows', []) if os.path.exists(absence_report) else []
    record('cue onsets: cancelled mono cannot falsely pass a reference absence check',
           code == 1 and len(absence_rows) == 1 and absence_rows[0].get('status') == 'inconclusive', output[-250:])
    loader_spec = importlib.util.spec_from_file_location('u5a_cue_list', os.path.join(scripts_dir, 'cue_list.py'))
    loader = importlib.util.module_from_spec(loader_spec)
    loader_spec.loader.exec_module(loader)
    listed = loader.load(cue_file)
    code, output = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', cue_file, '--null', '20', '--json')
    try:
        loaded_sync = json.loads(output)
    except ValueError:
        loaded_sync = {}
    record('listen sync: the shared cue loader returns its document and freshness',
           listed.state == 'unverified' and code == 0
           and loaded_sync.get('cue_freshness', '').startswith('unverified')
           and len(loaded_sync.get('turn_leads', [])) == 1, output[-300:])
    short_file = j('u5a-short-follow.json')
    with open(short_file, 'w', encoding='utf-8') as stream:
        json.dump({'version': 'v2', 'fps': 30, 'picture': {'kind': 'picture', 'sha256': '0' * 64},
                   'events': [{'id': 'brief-flight', 't': 2.5, 't_end': 3.6, 'scale': 'follow'}]}, stream)
    code, output = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', short_file, '--null', '20', '--json')
    try:
        short_rows = json.loads(output).get('follow', [])
    except ValueError:
        short_rows = []
    human_code, human = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', short_file, '--null', '20')
    record('listen sync: a follow span under 2 s reads not assessed, with its length, never silence',
           code == 0 and human_code == 0 and len(short_rows) == 1
           and short_rows[0].get('state') == 'not assessed'
           and short_rows[0].get('reason', '').startswith('span under 2 s (1.10 s)')
           and 'follow brief-flight: not assessed: span under 2 s' in human, f'{short_rows}; {human[-300:]}')
    plan_file = j('u5a-plan.json')
    with open(plan_file, 'w', encoding='utf-8') as stream:
        json.dump({'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None}, 'events': []}, stream)
    code, output = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', plan_file, '--json')
    record('listen sync: an unbound plan is refused by the shared loader',
           code == 2 and 'unbound plan' in output, output[-250:])
    bad_v1 = j('u5a-bad-v1.json')
    with open(bad_v1, 'w', encoding='utf-8') as stream:
        json.dump({'events': [{'id': 'turn', 'frame': 30}]}, stream)
    code, output = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', bad_v1, '--json')
    record('listen sync: an invalid legacy frame cue is refused',
           code == 2 and 'frame' in output and 'fps' in output and 'Traceback' not in output, output[-250:])
    owner = j('u5a-owner', 'cuts', 'v001')
    os.makedirs(owner, exist_ok=True)
    owner_manifest = os.path.join(owner, 'manifest.json')
    owner_cues = os.path.join(owner, 'edit-cues.json')
    identity = loader.paper_identity('a' * 64, {})
    owner_data = {'version': 'v2', 'fps': 30, 'picture': identity,
                  'events': [{'id': 'contact', 't': 1., 'scale': 'contact', 'sound': 'required'}]}
    with open(owner_cues, 'w', encoding='utf-8') as stream:
        json.dump(owner_data, stream)
    with open(owner_manifest, 'w', encoding='utf-8') as stream:
        json.dump({'film_md_sha256': 'a' * 64, 'sources': {}}, stream)
    code, output = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', owner_cues,
                        '--owner', owner, '--null', '20', '--json')
    try:
        owner_result = json.loads(output)
    except ValueError:
        owner_result = {}
    fresh_owner = code == 0 and owner_result.get('cue_freshness') == 'fresh'
    with open(owner_manifest, 'w', encoding='utf-8') as stream:
        json.dump({'film_md_sha256': 'b' * 64, 'sources': {}}, stream)
    code, output = tool('listen.py', 'sync', j('u5a-cues.wav'), '--cues', owner_cues,
                        '--owner', owner, '--json')
    record('listen sync: explicit version owner selects fresh or stale identity',
           fresh_owner and code == 2 and 'stale' in output, f'fresh={fresh_owner}, stale={output[-180:]}')
    found = {}
    for scale in ('contact', 'turn', 'all'):
        path = j('u5a-scale-' + scale + '.json')
        code, output = tool('cue_onsets.py', j('u5a-cues.wav'), cue_file, '--scale', scale, '--json', path)
        data = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
        found[scale] = (code, data.get('rows', []), output[-150:])
    record('cue onsets: scale selection ignores spans and applies the turn offset',
           [r['id'] for r in found['contact'][1]] == ['contact']
           and [r['id'] for r in found['turn'][1]] == ['turn']
           and abs(found['turn'][1][0]['t'] - 2.1) < .001
           and [r['id'] for r in found['all'][1]] == ['contact', 'turn'], str(found))
    offset_audio = np.zeros(4 * rate)
    offset_audio[rate // 2:rate // 2 + 1500] = random.normal(0, .35, 1500) * np.exp(-np.arange(1500) / 200)
    write_audio(j('u5a-offset.wav'), offset_audio)
    path = j('u5a-offset.json')
    code, output = tool('cue_onsets.py', j('u5a-offset.wav'), cue_file, '--offset', '.5', '--json', path)
    result = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
    rows = result.get('rows', [])
    record('cue onsets: stem offset maps the cue from picture time to audio time',
           code == 0 and len(rows) == 1 and abs(rows[0]['t'] - .5) < .001
           and abs(rows[0]['picture_t'] - 1) < .001, output[-160:])
    if not hasattr(listen, 'sync_measure'):
        record('listen sync: separated measures and missing picture are explicit', False, 'sync_measure missing')
    else:
        cue_data = json.load(open(cue_file, encoding='utf-8'))
        result = listen.sync_measure(j('u5a-cues.wav'), cue_file, cue_data, iterations=20, seed=3)
        record('listen sync: separated measures and missing picture are explicit',
               result['frame_change_at_cue']['state'] == 'not assessed'
               and result['sound_follows_list']['state'] in ('measured', 'inconclusive')
               and result['follow'][0]['state'] == 'inconclusive'
               and [row['id'] for row in result['turn_leads']] == ['turn'], str(result)[-500:])

    spec = importlib.util.spec_from_file_location('u5a_grade', os.path.join(scripts_dir, 'grade.py'))
    grade = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grade)
    record_file = j('u5a-cold-checks.json')
    media = j('u5a-events.wav')
    if not hasattr(grade, 'record_cold'):
        record('cold read: record matched or mismatched with the assessed file hash', False, 'record_cold missing')
    else:
        answer = {'what': 'a synthetic film', 'audience': 'test readers', 'why': 'a known-answer fixture'}
        rows = []
        for state in ('mismatched', 'matched'):
            grade.record_cold(record_file, media, {'state': state, 'by': 'synthetic reader',
                                                    'answer': answer, 'file_sha256': grade.digest(media)})
            rows.append(json.load(open(record_file, encoding='utf-8'))['cold_read'])
        record('cold read: record matched or mismatched with the assessed file hash',
               [row['state'] for row in rows] == ['mismatched', 'matched']
               and all(row['by'] == 'synthetic reader' and row['file_sha256'] == grade.digest(media)
                       for row in rows) and 'confirmed' not in json.dumps(rows), str(rows))
    cold_media = j('u5a-cold-video.mp4')
    with open(cold_media, 'wb') as stream:
        stream.write(b'synthetic media')
    cold_base = os.path.join(j(''), 'u5a-cold-video.grade', 'cold')
    os.makedirs(cold_base, exist_ok=True)
    sentinel = os.path.join(cold_base, 'frames.png')
    with open(sentinel, 'wb') as stream:
        stream.write(b'preserve existing packet')
    old_probe, old_sheet = grade.probe, grade.review_sheet
    try:
        grade.probe = lambda video: {'duration_s': 3}
        grade.review_sheet = lambda video, out, arguments: out.write_bytes(b'fixture frames')
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                grade.cold_packet(None, cold_media, None, 3, None, False, None)
    finally:
        grade.probe, grade.review_sheet = old_probe, old_sheet
    packet_dirs = [name for name in os.listdir(cold_base)
                   if os.path.isfile(os.path.join(cold_base, name, 'packet.json'))]
    with open(sentinel, 'rb') as stream:
        preserved = stream.read() == b'preserve existing packet'
    record('cold read: repeated packets preserve previous files',
           preserved and len(packet_dirs) == 2, f'preserved={preserved}, packets={packet_dirs}')
    project_root = j('u5a-cold-project')
    version_folder = os.path.join(project_root, 'cuts', 'v001')
    os.makedirs(version_folder, exist_ok=True)
    with open(os.path.join(version_folder, 'manifest.json'), 'w', encoding='utf-8') as stream:
        json.dump({}, stream)
    version_media = os.path.join(version_folder, 'preview.mp4')
    with open(version_media, 'wb') as stream:
        stream.write(b'version fixture')
    assessment = {'state': 'matched', 'by': 'synthetic reader', 'answer': answer,
                  'file_sha256': grade.digest(version_media)}
    try:
        grade.record_cold(os.path.join(version_folder, 'checks.json'), version_media, assessment,
                          project=project_root)
        project_recorded = True
    except (ValueError, TypeError):
        project_recorded = False
    old_probe = grade.probe
    try:
        grade.probe = lambda video: {'duration_s': 3}
        try:
            grade.cold_packet(None, version_media, None, 3, None, False, None)
            refused = False
        except ValueError as error:
            refused = 'immutable' in str(error) and not os.path.exists(os.path.join(version_folder, 'preview.grade'))
    finally:
        grade.probe = old_probe
    record('cold read: version QA is scoped and loose-file packets cannot write inside versions',
           project_recorded and refused, f'project_recorded={project_recorded}, refused={refused}')

    spec = importlib.util.spec_from_file_location('u5a_check', os.path.join(scripts_dir, 'check.py'))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    previously_invoked = set(check.INVOKED)
    try:
        check.INVOKED.add('tempo_map.py')
        tools_recorded = check.tools_record()
    finally:
        check.INVOKED.clear()
        check.INVOKED.update(previously_invoked)
    record('check: listening tool provenance includes tempo_map dependencies',
           bool(tools_recorded.get('scripts', {}).get('sound_io.py')), str(tools_recorded.get('scripts', {})))
    illegal_report = os.path.join(version_folder, 'not-qa.json')
    code, output = tool('check.py', '--file', version_media, '--no-speech', '--json', illegal_report)
    record('check: loose-file reports cannot write inside an immutable version',
           code == 2 and 'immutable' in output and not os.path.exists(illegal_report), output[-250:])
    if not hasattr(check, 'project_sync_items'):
        record('sync: project uses the shared owner, cue hash and listening measurements', False,
               'project_sync_items missing')
    else:
        video = os.path.join(owner, 'preview.mp4')
        with open(video, 'wb') as stream:
            stream.write(b'synthetic picture')
        manifest = {'film_md_sha256': 'a' * 64, 'sources': {},
                    'identity': {'cues_sha256': check.P.file_sha256(owner_cues), 'binding': 'receipt'}}
        with open(owner_manifest, 'w', encoding='utf-8') as stream:
            json.dump(manifest, stream)
        calls, old_run = [], check.run_script
        def fake_run(script, *args):
            calls.append((script, args))
            if script == 'listen.py' and args[0] == 'sync':
                return 0, json.dumps({'frame_change_at_cue': {'rows': [
                    {'id': 'contact', 't': 1, 'state': 'change'}]},
                    'sound_follows_list': {'state': 'measured', 'rows': [], 'summary': {'failures': 0}},
                    'turn_leads': [], 'follow': [], 'silence': []})
            if script == 'listen.py' and args[0] == 'transcript':
                return 0, json.dumps({'events': [], 'sections': [], 'beat_grid_status': 'inconclusive'})
            return 2, 'not available in this fixture'
        try:
            check.run_script = fake_run
            items, transcript = check.project_sync_items(owner, video, manifest, required=True)
            good = {row['id']: row for row in items}
            manifest['identity']['cues_sha256'] = '0' * 64
            stale, _ = check.project_sync_items(owner, video, manifest, required=True)
        finally:
            check.run_script = old_run
        record('sync: project uses the shared owner, cue hash and listening measurements',
               good.get('sync_cues', {}).get('state') == 'pass'
               and good.get('sync_frame_0', {}).get('state') == 'pass'
               and good.get('sync_sound_follows_list', {}).get('state') == 'pass'
               and isinstance(transcript, dict)
               and next(row for row in stale if row['id'] == 'sync_cues')['state'] == 'fail',
               f'good={good}; stale={stale}; calls={calls}')
        duplicate = os.path.join(owner, 'cues.json')
        with open(owner_cues, 'rb') as stream:
            duplicate_bytes = stream.read()
        with open(duplicate, 'wb') as stream:
            stream.write(duplicate_bytes)
        manifest['identity']['cues_sha256'] = check.P.file_sha256(owner_cues)
        try:
            check.run_script = fake_run
            duplicates, _ = check.project_sync_items(owner, video, manifest, required=True)
        finally:
            check.run_script = old_run
            os.remove(duplicate)
        record('sync: two byte-identical cue names do not create an ambiguous identity',
               next(row for row in duplicates if row['id'] == 'sync_cues')['state'] == 'pass', str(duplicates))
        old_hash = check.P.file_sha256
        manifest['identity']['cues_sha256'] = '0' * 64
        try:
            check.P.file_sha256 = lambda path: '0' * 64 if check.P.same_file(path, owner_cues) else old_hash(path)
            check.run_script = fake_run
            raced, _ = check.project_sync_items(owner, video, manifest, required=True)
        finally:
            check.P.file_sha256, check.run_script = old_hash, old_run
        record('sync: the loaded cue bytes must still match the selected manifest hash',
               next(row for row in raced if row['id'] == 'sync_cues')['state'] == 'fail', str(raced))
        with open(bad_v1, encoding='utf-8') as stream:
            invalid = json.load(stream)
        with open(owner_cues, 'w', encoding='utf-8') as stream:
            json.dump(invalid, stream)
        manifest['identity']['cues_sha256'] = check.P.file_sha256(owner_cues)
        try:
            check.run_script = fake_run
            invalid_items, _ = check.project_sync_items(owner, video, manifest, required=True)
        finally:
            check.run_script = old_run
        record('sync: a malformed legacy list is not counted as a valid project cue list',
               next(row for row in invalid_items if row['id'] == 'sync_cues')['state'] == 'fail', str(invalid_items))
        with open(owner_cues, 'w', encoding='utf-8') as stream:
            json.dump(owner_data, stream)
        reference = os.path.join(owner, 'event-reference.wav')
        with open(reference, 'wb') as stream:
            stream.write(b'synthetic reference')
        owner_data['events'][0]['ref'] = 'event-reference.wav'
        with open(owner_cues, 'w', encoding='utf-8') as stream:
            json.dump(owner_data, stream)
        manifest['identity']['cues_sha256'] = check.P.file_sha256(owner_cues)
        with open(owner_manifest, 'w', encoding='utf-8') as stream:
            json.dump(manifest, stream)
        root = os.path.dirname(os.path.dirname(owner))
        inputs = check.project_inputs(check.Path(root), check.Path(owner), check.Path(video),
                                      check.P.file_sha256(video), False,
                                      check.Path(owner) / 'captions.srt', False, manifest=manifest)
        reference_recorded = any(row.get('role') == 'cue_reference'
                                 and row.get('sha256') == check.P.file_sha256(reference) for row in inputs)
        with open(reference, 'wb') as stream:
            stream.write(b'changed synthetic reference')
        changed_inputs = check.P.input_changes(inputs, [root], thorough=True)
        record('sync: reference audio read by a cue is recorded as a check input',
               reference_recorded and any(row.get('role') == 'cue_reference' for row in changed_inputs),
               str(changed_inputs))
    if not hasattr(check, 'version_picture_items'):
        record('sync: actual master packets and timing are checked against the manifest', False,
               'version_picture_items missing')
    else:
        class PictureFixture:
            current_hash = 'a' * 64
            timing_changed = False
            schedule_corrupt = False
            def picture_identity(self, path):
                return {'sha256': self.current_hash, 'schedule': {'fixture': 'actual'}, 'geometry': {}}
            def read_schedule(self, path, expected):
                if self.schedule_corrupt:
                    raise ValueError('stale: schedule hash differs')
                return {'fixture': 'recorded'}
            def compare_schedules(self, expected, actual, fps=None):
                return 'one frame changed' if self.timing_changed else ''
            def geometry_compare(self, expected, actual):
                return 'equal', ''
        fake = PictureFixture()
        picture_manifest = {'picture_sha256': 'a' * 64, 'picture_timing':
                            {'pts_file': 'picture-timing.json', 'pts_sha256': 'b' * 64, 'fps_exact': '30'}}
        picture_ok = check.version_picture_items(owner, video, picture_manifest, fake)
        fake.current_hash = 'c' * 64
        picture_changed = check.version_picture_items(owner, video, picture_manifest, fake)
        fake.current_hash = 'a' * 64
        fake.timing_changed = True
        timing_changed = check.version_picture_items(owner, video, picture_manifest, fake)
        fake.timing_changed, fake.schedule_corrupt = False, True
        corrupt = check.version_picture_items(owner, video, picture_manifest, fake)
        record('sync: actual master packets and timing are checked against the manifest',
               picture_ok[0]['state'] == 'pass' and picture_changed[0]['state'] == 'fail'
               and timing_changed[0]['state'] == corrupt[0]['state'] == 'fail',
               f'ok={picture_ok}, packets={picture_changed}, timing={timing_changed}, corrupt={corrupt}')
        fake.schedule_corrupt = False
        picture_manifest['picture_geometry'] = {'width': 96}
        geometry = check.version_picture_items(owner, video, picture_manifest, fake)
        picture_manifest['picture_timing']['pts_file'] = '../outside.json'
        outside = check.version_picture_items(owner, video, picture_manifest, fake)
        record('sync: missing geometry and an outside schedule never count as verified',
               geometry[1]['state'] == 'skip' and outside[0]['state'] == 'skip',
               f'geometry={geometry}, outside={outside}')
    if not hasattr(check, 'project_path_name'):
        record('sync: the declared top-level path is read even when quoted', False, 'project_path_name missing')
    else:
        path_file = j('u5a-path-film.md')
        with open(path_file, 'w', encoding='utf-8') as stream:
            stream.write('---\npath: "create" # owner\nframe:\n  path: assumed\n---\n')
        record('sync: the declared top-level path is read even when quoted',
               check.project_path_name(path_file) == 'create', str(check.project_path_name(path_file)))
    if not hasattr(check, 'context_items'):
        record('context: missing fields are explicitly unconfirmed', False, 'context_items missing')
    else:
        entries = check.context_items({}, None, None)
        record('context: missing fields are explicitly unconfirmed',
               sum(row['state'] == 'unconfirmed' for row in entries) == 4
               and any(row['state'] == 'skip' for row in entries), str(entries))
        path = j('u5a-film.md')
        with open(path, 'w', encoding='utf-8') as stream:
            stream.write('---\npath: create\nframe:\n  what: "a test film"\n  audience: "editors"\n'
                         '  why: "see the result"\n  knows_by: [{s: 3, what: "the point", channel: "type"}]\n'
                         '  state: {what: confirmed, audience: confirmed, why: confirmed, knows_by: confirmed}\n'
                         '  waived: null\n---\n')
        if not hasattr(check, 'read_frame'):
            record('context: confirmed nested frame is read from film.md', False, 'read_frame missing')
        else:
            entries = check.context_items(check.read_frame(path), None, None)
            record('context: confirmed nested frame is read from film.md',
                   [row['state'] for row in entries] == ['pass', 'pass', 'pass', 'pass', 'skip'], str(entries))
    if not hasattr(check, 'edit_metadata_items'):
        record('quick edits: trim and speed duration invariants', False, 'edit_metadata_items missing')
    else:
        def media(duration):
            return {'format': {'duration': str(duration)}, 'streams': [
                {'codec_type': 'video', 'avg_frame_rate': '30/1', 'start_time': '0'},
                {'codec_type': 'audio', 'start_time': '0'}]}
        trim = check.edit_metadata_items(media(4), media(2), 'trim:1,3')
        speed = check.edit_metadata_items(media(4), media(2), 'speed:0.5')
        record('quick edits: trim and speed duration invariants',
               all(row['state'] == 'pass' for row in trim + speed), f'trim={trim}; speed={speed}')
        gif = {'format': {'duration': '4', 'format_name': 'gif'},
               'streams': [{'codec_type': 'video', 'avg_frame_rate': '30/1', 'start_time': '0'}]}
        converted = check.edit_metadata_items(media(4), gif, 'convert')
        record('quick edits: conversion to a video-only GIF allows the destination stream layout',
               next(row for row in converted if row['id'] == 'edit_streams')['state'] == 'pass', str(converted))
        gif_args = SimpleNamespace(file='out.gif', edit='convert', delivery=None, spec=None, duration=None,
                                   loudness=None, vcodec=None, pix_fmt=None, color=None, allow_bars=False)
        wanted = check.file_settings(gif_args)
        record('quick edits: GIF checks do not impose MP4 web defaults',
               wanted['vcodec'] == 'gif' and wanted['pix_fmt'] is None and wanted['color'] is None
               and wanted.get('faststart') is False, str(wanted))
        trim_ref = random.normal(0, .12, 8 * rate)
        trim_expected = trim_ref[rate:7 * rate]
        trim_late = np.r_[np.zeros(round(.15 * rate)), trim_expected[:-round(.15 * rate)]]
        write_audio(j('u5a-trim-source.wav'), trim_ref)
        write_audio(j('u5a-trim-good.wav'), trim_expected)
        write_audio(j('u5a-trim-late.wav'), trim_late)
        write_audio(j('u5a-trim-silent.wav'), np.zeros(len(trim_expected)))
        content = []
        for filename in ('u5a-trim-good.wav', 'u5a-trim-late.wav', 'u5a-trim-silent.wav'):
            rows = check.edit_content_items(j('u5a-trim-source.wav'), j(filename), 'trim:1,7', media(8), media(6))
            content.append(next((row['state'] for row in rows if row['id'] == 'edit_trim_content_offset'), None))
        record('quick edits: trim detects shifted audio and cannot pass silent content',
               content == ['pass', 'fail', 'skip'], str(content))
    if not hasattr(check, 'binding_item'):
        record('sync: binding states and reasons remain visible', False, 'binding_item missing')
    else:
        bindings = [check.binding_item({'binding': name, 'reason': 'test reason'})
                    for name in ('receipt', 'plan-bound', 'screened', 'overridden', 'unverified')]
        record('sync: binding states and reasons remain visible',
               [row['state'] for row in bindings] == ['pass', 'pass', 'look', 'look', 'look']
               and 'test reason' in bindings[3]['detail'] and 'test reason' in bindings[4]['detail'], str(bindings))
    mux_unknown = check.mux_origin_item('master', 'delivered', None,
                                        {'summary': {'verdict': 'inconclusive: too few confident windows'}})
    record('sync: an unaligned soundtrack does not pass the picture-to-audio origin check',
           mux_unknown['state'] == 'skip', str(mux_unknown))
    if not hasattr(check, 'cue_contract_items'):
        record('sync: required, stale, unbound and undecided cues have distinct states', False,
               'cue_contract_items missing')
    else:
        missing = check.cue_contract_items(None, None, required=True)
        stale = check.cue_contract_items({'events': []}, 'stale', required=True)
        plan = check.cue_contract_items({'picture': {'kind': 'plan'}, 'events': []}, 'unbound', required=True)
        undecided = check.cue_contract_items({'events': [{'id': 'turn', 't': 1, 'scale': 'turn'}]},
                                            'fresh', required=True)
        record('sync: required, stale, unbound and undecided cues have distinct states',
               missing[0]['state'] == 'fail' and stale[0]['state'] == 'fail' and plan[0]['state'] == 'skip'
               and 'open item' in plan[0]['detail'] and 'register the master' in plan[0]['detail']
               and any(row['state'] == 'look' for row in undecided),
               f'missing={missing}, stale={stale}, plan={plan}, undecided={undecided}')
        framed = check.cue_contract_items({'fps': 30, 'sections': [{'id': 'one', 'a': 0, 'b': 1},
                                                                    {'id': 'two', 'a': 1, 'b': 2}],
            'events': [{'id': 'turn', 'frame': 30, 'scale': 'turn', 'decision': 'move'}]}, 'fresh')
        record('sync: a frame-number turn satisfies its section decision',
               next(row for row in framed if row['id'] == 'sync_turn_decisions')['state'] == 'pass', str(framed))
    if not hasattr(check, 'sync_measurement_items'):
        record('sync: separate frame and sound measures preserve inconclusive states', False,
               'sync_measurement_items missing')
    else:
        measurements = {'frame_change_at_cue': {'state': 'measured', 'rows': [
            {'id': 'changed', 'state': 'change', 't': 1},
            {'id': 'still', 'state': 'look', 't': 2},
            {'id': 'held', 'state': 'skipped', 'reason': 'picture: held', 't': 3},
            {'id': 'outside', 'state': 'not assessed', 'reason': 'outside', 't': 8}]},
            'sound_follows_list': {'state': 'inconclusive', 'summary': {'failures': 0}},
            'turn_leads': [{'id': 'changed', 'measured_ms': -80, 'status': 'on cue'}],
            'follow': [{'id': 'moving', 'state': 'screening', 'best_r': .94, 'n': 100, 'seed': 5,
                        'null_spread': [0, .6], 'null_note': 'Uncalibrated circular-shift null; screening only.'},
                       {'id': 'short', 'state': 'inconclusive', 'reason': 'under 2 seconds'}]}
        entries = check.sync_measurement_items(measurements)
        frames = [row for row in entries if row['id'].startswith('sync_frame_')]
        sound = next(row for row in entries if row['id'] == 'sync_sound_follows_list')
        follows = [row for row in entries if row['id'].startswith('sync_follow_')]
        record('sync: separate frame and sound measures preserve inconclusive states',
               [row['state'] for row in frames] == ['pass', 'look', 'skip', 'skip']
               and sound['state'] == 'skip' and [row['state'] for row in follows] == ['pass', 'skip']
               and follows[0].get('measurement', {}).get('seed') == 5,
               str(entries))
    run_u5_binding_cases(record, j, scripts_dir)
    run_u5_conform_cases(record, j, scripts_dir)


def run_u5_binding_cases(record, j, scripts_dir):
    """Exercise the version fields written by registration and attach-mix."""
    import hashlib
    from pathlib import Path

    spec = importlib.util.spec_from_file_location('u5_binding_check', Path(scripts_dir) / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    root = Path(j('u5-binding-project'))
    folder = root / 'cuts' / 'v001'
    folder.mkdir(parents=True)
    video = folder / 'preview.mp4'
    video.write_bytes(b'synthetic picture')
    cues = folder / 'cues.json'
    doc = {'version': 'v2', 'fps': '30/1', 'provenance': 'exported',
           'picture': {'kind': 'page', 'path': '../../film/', 'sha256': 'a' * 64,
                       'snapshot_sha256': 'b' * 64, 'source_files': {'index.html': 'c' * 64}},
           'sections': [], 'events': []}
    cues.write_text(json.dumps(doc), encoding='utf-8')
    cue_sha = hashlib.sha256(cues.read_bytes()).hexdigest()
    identity = {'registered': True, 'source': {'kind': 'page', 'sha256': 'a' * 64,
                                               'snapshot_sha256': 'b' * 64, 'path': 'film/'},
                'cues': 'cues.json', 'cues_sha256': 'd' * 64, 'cues_provenance': 'exported',
                'binding': 'unverified', 'binding_reasons': ['render not closed'],
                'render_trace': 'none', 'receipt': 'receipt.json', 'receipt_entry': None,
                'picture_sha256': 'f' * 64, 'picture_timing': None,
                'geometry': {'width': 96, 'height': 64, 'coded_width': 96, 'coded_height': 64,
                             'sar': '1:1', 'display_width': 96, 'display_height': 64,
                             'matrix': [65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824],
                             'transform': {'rotate': 0, 'flip_h': False, 'flip_v': False}, 'crop': None},
                'conform_sha256': None, 'mix': None, 'screen': None}
    manifest = {'version': 'v001', 'parent': None, 'created': '2026-01-01', 'label': '', 'duration_s': 1.0,
                'frames': 30, 'size': [96, 64], 'preview_size': [96, 64], 'fps': '30/1',
                'film_md_sha256': 'e' * 64, 'files': {'cues.json': cue_sha}, 'sources': {},
                'notes_resolved': [], 'title': '', 'final': False, 'skill_version': '2.1.0', 'captions': [],
                'registered_from': str(video), 'identity': identity}
    (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    original_run, original_picture = check.run_script, check.version_picture_items
    check.run_script = lambda script, *args: (0, json.dumps({'events': [], 'sections': []}))
    check.version_picture_items = lambda *args: []
    try:
        rows, _ = check.project_sync_items(folder, video, manifest, required=True)
        by_id = {row['id']: row for row in rows}
        cues.write_text(json.dumps(dict(doc, events=[{'id': 'changed', 't': 1, 'scale': 'contact'}])),
                        encoding='utf-8')
        changed, _ = check.project_sync_items(folder, video, manifest, required=True)
        changed = {row['id']: row for row in changed}
        cues.write_text(json.dumps(doc), encoding='utf-8')
        record('sync: a registered cue copy uses its version hash and rejects changed bytes',
               by_id.get('sync_cues', {}).get('state') == 'pass'
               and changed.get('sync_cues', {}).get('state') == 'fail', str((by_id, changed)))

        identity['cues_provenance'] = 'observed'
        wrong, _ = check.project_sync_items(folder, video, manifest, required=True)
        record('sync: registered cue provenance must match the stored list',
               by_id.get('sync_cues', {}).get('state') == 'pass'
               and next(row for row in wrong if row['id'] == 'sync_cues')['state'] == 'fail', str(wrong))
        identity['cues_provenance'] = 'exported'
        binding = check.binding_item(identity)
        record('sync: binding prints U3 reasons, trace, provenance and receipt',
               binding['state'] == 'look' and all(value in binding['detail'] for value in
               ('render not closed', 'none', 'exported', 'receipt.json')), str(binding))
        override = check.binding_item(dict(identity, binding='overridden', decision='older picture accepted',
                                           binding_reasons=['no render receipt']))
        record('sync: overridden binding shows both decision and reasons',
               all(value in override['detail'] for value in ('older picture accepted', 'no render receipt')),
               str(override))

        receipt = folder / 'receipt.json'
        receipt.write_text(json.dumps({'source_fingerprint': 'a' * 64, 'snapshot_sha256': 'b' * 64,
                                       'cues_sha256': 'd' * 64, 'render_trace': 'none',
                                       'binding': 'unverified', 'picture_sha256': 'f' * 64}), encoding='utf-8')
        manifest['files']['receipt.json'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        with_receipt, _ = check.project_sync_items(folder, video, manifest, required=True)
        receipt.write_text('{}', encoding='utf-8')
        bad_receipt, _ = check.project_sync_items(folder, video, manifest, required=True)
        good_receipt = next((r for r in with_receipt if r['id'] == 'sync_receipt'), {})
        bad_receipt = next((r for r in bad_receipt if r['id'] == 'sync_receipt'), {})
        record('sync: a stored render receipt is fingerprinted and changed bytes fail',
               good_receipt.get('state') == 'pass' and bad_receipt.get('state') == 'fail',
               str((good_receipt, bad_receipt)))
        receipt.write_text(json.dumps({'source_fingerprint': 'a' * 64, 'snapshot_sha256': 'b' * 64,
                                       'cues_sha256': 'd' * 64, 'render_trace': 'none',
                                       'binding': 'unverified', 'picture_sha256': 'e' * 64}), encoding='utf-8')
        manifest['files']['receipt.json'] = hashlib.sha256(receipt.read_bytes()).hexdigest()
        wrong_picture, _ = check.project_sync_items(folder, video, manifest, required=True)
        wrong_picture = next((r for r in wrong_picture if r['id'] == 'sync_receipt'), {})
        record('sync: a receipt for a different picture fails even when its file hash matches',
               wrong_picture.get('state') == 'fail' and 'picture_sha256' in wrong_picture.get('detail', ''),
               str(wrong_picture))

        stems = folder / 'stems'
        stems.mkdir()
        bus, voice = stems / 'attached-effects.wav', stems / 'dialogue.wav'
        bus.write_bytes(b'processed bus')
        voice.write_bytes(b'retained dialogue')
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        mix_report = folder / 'attached-mix-report.json'
        mix_report.write_text(json.dumps({'exit_code': 0, 'inputs': {'cues': cue_sha,
                                          'voice': [{'sha256': digest(voice), 'at_s': 0, 'gain_db': 0}]},
                                          'outputs': {'effects.wav': digest(bus)},
                                          'masking': [{'ids': ['hit', 'tap']}]}), encoding='utf-8')
        mix = {'report_sha256': digest(mix_report), 'cues_sha256': cue_sha,
               'buses': {'effects': digest(bus)},
               'stems': {'dialogue': {'from': 'v000', 'sha256': digest(voice), 'role': 'dialogue'}},
               'replaced': [], 'voice_reference': digest(voice)}
        identity.update(registered=False, cues_sha256=cue_sha, mix=mix)
        manifest['mix'] = mix
        manifest['files'].update({'attached-mix-report.json': digest(mix_report),
                                  'stems/attached-effects.wav': digest(bus), 'stems/dialogue.wav': digest(voice)})
        (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        good, _ = check.project_sync_items(folder, video, manifest, required=True)
        good = {row['id']: row for row in good}
        cues.write_text('{"changed": true}', encoding='utf-8')
        stale_cues, _ = check.project_sync_items(folder, video, manifest, required=True)
        stale_cues = {row['id']: row for row in stale_cues}
        cues.write_text(json.dumps(doc), encoding='utf-8')
        record('sync: a stale cue list cannot leave an attached mix marked as bound',
               stale_cues.get('sync_cues', {}).get('state') == 'fail'
               and stale_cues.get('sync_mix', {}).get('state') == 'fail'
               and stale_cues.get('sync_masking', {}).get('state') == 'skip', str(stale_cues))
        inputs = check.project_inputs(root, folder, video, digest(video), False, folder / 'captions.srt', False,
                                      manifest=manifest)
        report_bytes = mix_report.read_bytes()
        altered = json.loads(report_bytes)
        altered['inputs']['voice'][0]['sha256'] = 'e' * 64
        mix_report.write_text(json.dumps(altered), encoding='utf-8')
        original_report_hash = mix['report_sha256']
        mix['report_sha256'] = digest(mix_report)
        manifest['files']['attached-mix-report.json'] = mix['report_sha256']
        wrong_voice, _ = check.project_sync_items(folder, video, manifest, required=True)
        record('sync: the report voice reference must match the retained dialogue',
               next(r for r in wrong_voice if r['id'] == 'sync_mix')['state'] == 'fail', str(wrong_voice))
        mix_report.write_bytes(report_bytes)
        mix['report_sha256'] = original_report_hash
        manifest['files']['attached-mix-report.json'] = original_report_hash
        top_level = dict(manifest, identity=dict(identity))
        top_level['identity'].pop('mix')
        top_inputs = check.project_inputs(root, folder, video, digest(video), False, folder / 'captions.srt', False,
                                          manifest=top_level)
        record('sync: a top-level mix record fingerprints its report and media',
               {'mix_report', 'mix_bus', 'mix_stem'} <= {row.get('role') for row in top_inputs}, str(top_inputs))
        bus.write_bytes(b'changed bus')
        stale, _ = check.project_sync_items(folder, video, manifest, required=True)
        stale = {row['id']: row for row in stale}
        changes = check.P.input_changes(inputs, [root], thorough=True)
        record('sync: attached mixer report, buses and retained stems are bound and fingerprinted',
               good.get('sync_mix', {}).get('state') == 'pass'
               and stale.get('sync_mix', {}).get('state') == 'fail'
               and any(row.get('role') == 'mix_bus' for row in changes), str((good, stale, changes)))
        bus.write_bytes(b'processed bus')
        voice.write_bytes(b'changed dialogue')
        stale_voice, _ = check.project_sync_items(folder, video, manifest, required=True)
        voice_changes = check.P.input_changes(inputs, [root], thorough=True)
        voice.write_bytes(b'retained dialogue')
        mix_report.write_text('{}', encoding='utf-8')
        stale_report, _ = check.project_sync_items(folder, video, manifest, required=True)
        report_changes = check.P.input_changes(inputs, [root], thorough=True)
        record('sync: changed retained dialogue and report cannot reuse a passing mix check',
               next(r for r in stale_voice if r['id'] == 'sync_mix')['state'] == 'fail'
               and next(r for r in stale_report if r['id'] == 'sync_mix')['state'] == 'fail'
               and any(row.get('role') == 'mix_stem' for row in voice_changes)
               and any(row.get('role') == 'mix_report' for row in report_changes),
               str((stale_voice, stale_report, voice_changes, report_changes)))
        record('sync: retained stem names cannot contain a drive prefix or escape',
               not any(check.retained_stem_name(name) for name in ('C:outside', '../outside', 'a\\b')),
               'unsafe retained stem name accepted')
        record('sync: masking candidates are named as listening looks',
               good.get('sync_masking', {}).get('state') == 'look'
               and 'hit' in good['sync_masking']['detail'] and 'tap' in good['sync_masking']['detail'], str(good))
        identity['mix'] = {'report_sha256': '1' * 64, 'sound_sha256': '2' * 64}
        manifest.pop('mix')
        missing, _ = check.project_sync_items(folder, video, manifest, required=True)
        missing = {row['id']: row for row in missing}
        record('sync: registered mix hashes without paths do not count as verified',
               missing.get('sync_mix', {}).get('state') == 'skip'
               and 'path' in missing['sync_mix']['detail'].lower(), str(missing))
    finally:
        check.run_script, check.version_picture_items = original_run, original_picture

    class PictureFixture:
        def picture_identity(self, path):
            return {'sha256': 'a' * 64, 'schedule': {'fixture': 'actual'}, 'geometry': {'width': 96}}
        def read_schedule(self, path, expected):
            return {'fixture': 'recorded'}
        def compare_schedules(self, expected, actual, fps=None):
            return ''
        def geometry_compare(self, expected, actual):
            return ('equal', '') if expected == actual else ('changed', 'display changed')
    geometry = check.version_picture_items(folder, video, {'picture_sha256': 'a' * 64,
        'geometry': {'width': 96}, 'picture_timing': {'pts_file': 'picture-timing.json', 'pts_sha256': 'b' * 64}},
        PictureFixture())
    record('sync: U3 geometry is compared against the actual master', geometry[1]['state'] == 'pass', str(geometry))


def run_u5_conform_cases(record, j, scripts_dir):
    """Use the paper identity and mixer records actually written by attach-mix."""
    import hashlib
    from pathlib import Path

    scripts = Path(scripts_dir)
    def module(name):
        spec = importlib.util.spec_from_file_location('u5_conform_' + name, scripts / (name + '.py'))
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result

    check, cue_list = module('check'), module('cue_list')
    root = Path(j('u5-conform-project'))
    folder = root / 'cuts' / 'v002'
    sound, stems = root / 'sound', folder / 'stems'
    sound.mkdir(parents=True)
    stems.mkdir(parents=True)
    video, film = folder / 'preview.mp4', folder / 'film.md'
    video.write_bytes(b'synthetic picture')
    film.write_text('---\ntitle: Synthetic\n---\n', encoding='utf-8')
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    film_sha = digest(film)
    paper = cue_list.paper_identity(film_sha, {})
    cue_path = folder / 'edit-cues.json'
    cue_path.write_text(json.dumps({'version': 'v2', 'fps': '30/1', 'provenance': 'exported',
                                    'picture': {'kind': 'paper', 'sha256': paper['sha256'],
                                                'film_md_sha256': film_sha, 'sources': {}},
                                    'sections': [], 'events': []}), encoding='utf-8')
    cue_sha = digest(cue_path)
    original, bed, conform = sound / 'source.wav', sound / 'conformed.wav', sound / 'conform-report.json'
    original.write_bytes(b'original music')
    bed.write_bytes(b'conformed music')
    conform_doc = {'binding': 'bound', 'cues_sha256': cue_sha, 'map_sha256': 'a' * 64,
                   'music_sha256': digest(original), 'tempo_sha256': None, 'bed_sha256': digest(bed),
                   'sections': [], 'seams': [], 'low_band_bars': [], 'rate': 48000,
                   'duration_s': 1.0, 'source_edge': 'refuse', 'held_source_samples': 0,
                   'processing': {}, 'bar_line_error_basis': 'source grid', 'limit': 'Unheard.'}
    conform.write_text(json.dumps(conform_doc), encoding='utf-8')
    bus, voice = stems / 'attached-music.wav', stems / 'dialogue.wav'
    bus.write_bytes(b'processed bus')
    voice.write_bytes(b'retained dialogue')
    files = {str(path.resolve()): digest(path) for path in (cue_path, original, bed, conform)}
    report_doc = {'exit_code': 0, 'inputs': {'cues': cue_sha, 'cues_path': str(cue_path.resolve()),
                                             'palette': 'b' * 64, 'files': files, 'music': digest(bed),
                                             'conform': digest(conform),
                                             'voice': [{'sha256': digest(voice), 'at_s': 0, 'gain_db': 0}]},
                  'outputs': {'music.wav': digest(bus)}, 'masking': [{'ids': ['hit', 'tap']}],
                  'music_binding': 'verified'}
    report = folder / 'attached-mix-report.json'
    report.write_text(json.dumps(report_doc), encoding='utf-8')
    mix = {'report_sha256': digest(report), 'cues_sha256': cue_sha, 'buses': {'music': digest(bus)},
           'stems': {'dialogue': {'from': 'v001', 'sha256': digest(voice), 'role': 'dialogue'}},
           'replaced': [], 'voice_reference': digest(voice), 'fades': 'v001', 'master': 'v001'}
    identity = {'source': {'kind': 'paper', 'path': 'film.md', 'sha256': paper['sha256'],
                           'film_md_sha256': film_sha},
                'picture_sha256': digest(video), 'picture_timing': None, 'binding': 'receipt', 'receipt': None,
                'cues_sha256': cue_sha, 'cues_provenance': 'exported', 'conform_sha256': None,
                'mix': mix, 'registered': False}
    manifest = {'version': 'v002', 'parent': 'v001', 'created': '2026-01-01', 'label': '', 'duration_s': 1.0,
                'frames': 30, 'size': [96, 64], 'fps': '30/1', 'film_md_sha256': film_sha,
                'files': {'preview.mp4': digest(video), 'film.md': film_sha, 'edit-cues.json': cue_sha,
                          'attached-mix-report.json': digest(report), 'stems/attached-music.wav': digest(bus),
                          'stems/dialogue.wav': digest(voice)}, 'sources': {}, 'notes_resolved': [], 'title': '',
                'preview_size': [96, 64], 'final': True, 'skill_version': '2.1.0', 'captions': [],
                'proxies': [], 'render_seconds': 1.0, 'audio_processing': {'intermediate': '48 kHz stereo float PCM',
                    'preview_mix': 'summed without normalization; limiter at -1 dBFS before AAC'},
                'audio_master': None, 'title_font': None, 'sync_max_offset_s': None, 'notes': [],
                'identity': identity, 'mix': mix}
    manifest_path = folder / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    previous_run, previous_picture = check.run_script, check.version_picture_items
    check.run_script = lambda script, *args: (0, json.dumps({'events': [], 'sections': []}))
    check.version_picture_items = lambda *args: []
    try:
        def check_rows():
            rows, _ = check.project_sync_items(folder, video, manifest, required=True)
            return {row['id']: row for row in rows}

        def inputs():
            return check.project_inputs(root, folder, video, digest(video), False, folder / 'captions.srt', False,
                                        manifest=manifest)

        good = check_rows()
        recorded = inputs()
        roles = {row.get('role') for row in recorded}
        record('sync: an attached mix binds the conform report, source, bed and cue list',
               good.get('sync_cues', {}).get('state') == 'pass'
               and good.get('sync_mix', {}).get('state') == 'pass'
               and good.get('sync_conform', {}).get('state') == 'pass'
               and good.get('sync_masking', {}).get('state') == 'look', str(good))
        record('sync: conform report, source and bed are check inputs',
               {'conform_report', 'conform_source', 'conform_bed'} <= roles, str(recorded))
        bed.write_bytes(b'changed conformed music')
        changed = check_rows()
        changes = check.P.input_changes(recorded, [root], thorough=True)
        record('sync: changed conformed media fails and expires the check',
               changed.get('sync_conform', {}).get('state') == 'fail'
               and any(row.get('role') == 'conform_bed' for row in changes), str((changed, changes)))
        bed.write_bytes(b'conformed music')
        original_hash = check.P.file_sha256
        def unreadable(path):
            # The report records resolved paths; a Windows temp folder can be an 8.3 short name (RUNNER~1).
            if Path(path).resolve() == bed.resolve():
                raise PermissionError('synthetic unreadable bed')
            return original_hash(path)
        try:
            check.P.file_sha256 = unreadable
            inaccessible = check_rows()
        finally:
            check.P.file_sha256 = original_hash
        record('sync: an unreadable conformed bed is not assessed',
               inaccessible.get('sync_conform', {}).get('state') == 'skip'
               and 'unavailable' in inaccessible['sync_conform']['detail'], str(inaccessible))
        original.write_bytes(b'changed source music')
        changed = check_rows()
        changes = check.P.input_changes(recorded, [root], thorough=True)
        record('sync: changed conform source fails and expires the check',
               changed.get('sync_conform', {}).get('state') == 'fail'
               and any(row.get('role') == 'conform_source' for row in changes), str((changed, changes)))
        original.write_bytes(b'original music')
        conform_bytes = conform.read_bytes()
        conform.write_text('{}', encoding='utf-8')
        changed = check_rows()
        changes = check.P.input_changes(recorded, [root], thorough=True)
        record('sync: changed conform report fails and expires the check',
               changed.get('sync_conform', {}).get('state') == 'fail'
               and any(row.get('role') == 'conform_report' for row in changes), str((changed, changes)))
        conform.write_bytes(conform_bytes)
        identity['conform_sha256'] = 'e' * 64
        wrong_identity = check_rows()
        record('sync: a conflicting manifest conform hash fails',
               wrong_identity.get('sync_conform', {}).get('state') == 'fail', str(wrong_identity))
        identity['conform_sha256'] = None

        conform_doc['cues_sha256'] = 'c' * 64
        conform.write_text(json.dumps(conform_doc), encoding='utf-8')
        report_doc['inputs']['conform'] = digest(conform)
        report_doc['inputs']['files'][str(conform.resolve())] = digest(conform)
        report.write_text(json.dumps(report_doc), encoding='utf-8')
        mix['report_sha256'] = digest(report)
        manifest['files']['attached-mix-report.json'] = digest(report)
        wrong_cue = check_rows()
        record('sync: a conform bound to different cues fails even when its file hash matches',
               wrong_cue.get('sync_conform', {}).get('state') == 'fail', str(wrong_cue))
        conform.write_bytes(conform_bytes)
        report_doc['inputs']['conform'] = digest(conform)
        report_doc['inputs']['files'][str(conform.resolve())] = digest(conform)

        missing_path = sound / 'moved-conform-report.json'
        report_doc['inputs']['files'].pop(str(conform.resolve()))
        report_doc['inputs']['files'][str(missing_path.resolve())] = digest(conform)
        report.write_text(json.dumps(report_doc), encoding='utf-8')
        mix['report_sha256'] = digest(report)
        manifest['files']['attached-mix-report.json'] = digest(report)
        manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
        missing = check_rows()
        missing_inputs = inputs()
        missing_path.write_bytes(conform.read_bytes())
        changes = check.P.input_changes(missing_inputs, [root], thorough=True)
        record('sync: a moved conform report is not assessed until its recorded path exists',
               missing.get('sync_conform', {}).get('state') == 'skip'
               and any(row.get('role') == 'conform_report' for row in changes)
               and check_rows().get('sync_conform', {}).get('state') == 'pass', str((missing, changes)))
    finally:
        check.run_script, check.version_picture_items = previous_run, previous_picture
