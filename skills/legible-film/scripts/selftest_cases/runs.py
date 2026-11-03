"""Declared runs (SPEC §9): spot_cues.py and the kit engine keep every event of a run the picture means (run: true),
and without it keep today's merge (under 120 ms the first event and one texture accent)."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path


def load_cue_list(scripts_dir):
    spec = importlib.util.spec_from_file_location('selftest_runs_cue_list', Path(scripts_dir) / 'cue_list.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamps(run=None, span=False):
    events = [{'id': f'k{i}', 't': round(1 + i * 0.08, 6), 'role': 'key', 'sync': 'attack'} for i in range(6)]
    if run == 'event':
        for ev in events:
            ev['run'] = True
    if span:
        for ev in events:
            ev.update(scale='contact', span='type-run')
        events.append({'id': 'type-run', 't': 1.0, 't_end': 1.5, 'scale': 'follow', 'role': 'key', 'run': True,
                       'intent': 'key density follows the typing'})
    return events


def kept(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return sum(1 for ev in data['events'] if ev['id'] != 'type-run' and ev.get('enabled', True)
               and ev.get('sound') != 'silent' and ev.get('scale') != 'follow')


def run_runs_cases(tool, record, j, scripts_dir, skip=None):
    root = Path(j('runs-cases'))
    root.mkdir(parents=True, exist_ok=True)
    cue_list = load_cue_list(scripts_dir)
    cases = {'run on each event (v1 list)': ({'fps': 60, 'events': stamps('event')}, 6),
             'contacts in a follow span with run: true (v2 list)': (None, 6),
             'no run: today\'s merge': ({'fps': 60, 'events': stamps()}, 2)}
    picture = {'kind': 'picture', 'sha256': '0' * 64, 'geometry': None, 'timing': {'untimed': True}}
    cases['contacts in a follow span with run: true (v2 list)'] = (
        {'version': 'v2', 'clock': 'seconds from the first frame of the film', 'fps': 60, 'picture': picture,
         'sections': [], 'events': stamps(span=True)}, 6)
    for name, (doc, want) in cases.items():
        folder = root / str(abs(hash(name)))
        folder.mkdir(exist_ok=True)
        (folder / 'cues.json').write_text(json.dumps(doc), encoding='utf-8')
        readable = cue_list.check(folder / 'cues.json').state in ('unversioned', 'unverified')
        code, out = tool('spot_cues.py', folder / 'cues.json', '--out-dir', folder / 'out')
        got = kept(folder / 'out' / 'cues.spotted.json') if (folder / 'out' / 'cues.spotted.json').is_file() else None
        record(f'runs: spot_cues keeps {want} of 6 stamps, {name}', readable and code == 0 and got == want,
               f'exit {code}, kept {got}; ' + out.strip()[-200:])
    # The density rule never drops or demotes a required or hero event: it keeps it and reports a look that names
    # it and its neighbours, so the person decides (--edits removes it). An optional event is still thinned.
    dense = root / 'dense'
    dense.mkdir(exist_ok=True)
    events = [{'id': 'hit-1', 't': 1.0, 'role': 'hit', 'sync': 'attack'},
              {'id': 'hit-2', 't': 1.3, 'role': 'hit', 'sync': 'attack', 'sound': 'required'},
              {'id': 'drop', 't': 1.6, 'role': 'hit', 'sync': 'attack', 'sound': 'required', 'hero': True,
               'decision': 'the drop lands on the burst'},
              {'id': 'spare', 't': 1.8, 'role': 'hit', 'sync': 'attack', 'sound': 'optional'}]
    (dense / 'cues.json').write_text(json.dumps({'fps': 24, 'events': events}), encoding='utf-8')
    code, out = tool('spot_cues.py', dense / 'cues.json', '--out-dir', dense / 'out')
    spotted = dense / 'out' / 'cues.spotted.json'
    rows = {e['id']: e for e in json.loads(spotted.read_text(encoding='utf-8'))['events']} if spotted.is_file() else {}
    looks = json.loads(spotted.read_text(encoding='utf-8')).get('spotting', {}).get('looks', []) if spotted.is_file() else []
    drop = rows.get('drop', {})
    record('runs: a required hero event the density rule would thin is kept, required and enabled',
           drop.get('enabled') is True and drop.get('sound') == 'required', str(drop))
    record('runs: ... with a look naming the event and its conflicting neighbours (exit 1, a review warning)',
           code == 1 and any(l.get('id') == 'drop' and {'hit-1', 'hit-2'} <= set(l.get('neighbours', [])) for l in looks)
           and 'drop' in out and 'hit-1' in out and '--edits' in out, out.strip()[-300:])
    record('runs: an optional event in the same second is still thinned',
           rows.get('spare', {}).get('enabled') is False and rows['spare'].get('sound') == 'optional', str(rows.get('spare')))
    (dense / 'edits.json').write_text(json.dumps({'drop': 'drop'}), encoding='utf-8')
    code, out = tool('spot_cues.py', dense / 'cues.json', '--out-dir', dense / 'edited', '--edits', dense / 'edits.json')
    edited = dense / 'edited' / 'cues.spotted.json'
    gone = {e['id']: e for e in json.loads(edited.read_text(encoding='utf-8'))['events']}.get('drop', {}) if edited.is_file() else {}
    record('runs: --edits still removes it when the person decides', gone.get('enabled') is False, str(gone))

    page = root / 'page'
    page.mkdir(exist_ok=True)
    (page / 'index.html').write_bytes(b'<!doctype html><title>spotted</title>\n')
    frozen = cue_list.freeze(page, offline=True)
    lists = root / 'lists'
    lists.mkdir(exist_ok=True)
    doc = {'version': 'v2', 'clock': 'seconds from the first frame of the film', 'fps': 60,
           'picture': {'kind': 'page', 'path': '../page/', 'sha256': frozen['fingerprint'],
                       'snapshot_sha256': frozen['snapshot_sha256'], 'source_files': frozen['source_files']},
           'sections': [], 'events': [dict(e, scale='contact') for e in stamps('event')]}
    (lists / 'cues.json').write_text(json.dumps(doc), encoding='utf-8')
    code, out = tool('spot_cues.py', lists / 'cues.json', '--out-dir', root / 'elsewhere' / 'qa')
    spotted = root / 'elsewhere' / 'qa' / 'cues.spotted.json'
    state = cue_list.check(spotted) if spotted.is_file() else None
    record('runs: a page list spotted into another folder still reads fresh (conform reads the spotted list)',
           code == 0 and state is not None and state.state == 'fresh', state.message if state else out[-200:])
    node = shutil.which('node')
    if not node:
        if skip:
            skip('runs: kit engine tidyCues', 'Node is not on PATH', 2)
        else:
            print('SKIP  runs: kit engine tidyCues (Node is not on PATH)')
        return
    engine = (Path(scripts_dir).parent / 'assets' / 'kit' / 'lf' / 'engine.js').resolve().as_uri()
    probe = ("import {tidyCues} from '" + engine + "';"
             "const mk=run=>({fps:60,warn(){},reg:{cues:Array.from({length:6},(_,i)=>({id:'k'+i,t:1+i*0.08,"
             "sound:'required',role:'key',sync:'attack',...(run?{run:true}:{})}))}});"
             "const out={};for(const run of [true,false]){const f=mk(run);tidyCues(f);out[run]=f.reg.cues.length;}"
             "console.log(JSON.stringify(out));")
    r = subprocess.run([node, '--input-type=module', '-e', probe], capture_output=True, text=True)
    try:
        counts = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        counts = {}
    record('runs: the kit engine keeps 6 of 6 declared run stamps', counts.get('true') == 6, r.stdout + r.stderr[-200:])
    record('runs: the kit engine merges an undeclared run as before (3 of 6 at 80 ms)', counts.get('false') == 3,
           r.stdout + r.stderr[-200:])
