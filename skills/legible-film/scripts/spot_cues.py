#!/usr/bin/env python3
"""Spot picture cues into gestures without overwriting the picture's cue list.

  python spot_cues.py cues.json --out-dir audio --edits edits.json
  python spot_cues.py cues.json --palette palette.json --json spotting-report.json

Writes cues.spotted.json and spotting.csv (default: beside the input). Every
input event remains, with a spotting note and enabled flag. Disabled events are
withheld by mix_cues and cue_onsets. Silent cues and reading holds stay silent.
Reading holds use sound: silent, reading_hold: true or kind: reading-hold.

Starting rules: audible events <60 ms from the first event of a cluster become
one gesture. Strongest means largest strength (when given), otherwise gain_db;
ties prefer required, then earlier input. Different roles become event layers;
identical roles are dropped. Sync stays at the strongest event's picture time.
Adjacent identical-role gestures <120 ms form a run: keep the first synced and
at most one additional event as optional texture; withhold the remaining run.
In any rolling half-open second [t,t+1), allow two layers of one role and five
in all (including the main take). Palette role layers count when --palette is
given. An excess optional gesture becomes a disabled choice, never audible by default.
A required or hero event is never dropped or demoted by this rule: it is kept, and the
conflict is a look that names it and its neighbours in the crowded second (exit 1), so
the person decides; --edits removes it. A v1 event without sound is required.
The first event is favoured by time; edits may deliberately exceed these limits.
A declared run is kept whole: an event with run: true, or a contact whose span names a
follow event with run: true, is never merged, thinned or withheld by these rules (it still
counts toward the density of other events). A v2 follow span is an annotation and a v2
silence span is silent: neither is a take.

Edits apply LAST by id: {"id": "keep"|"drop"|{"action":"keep", "role":"tap",
"gain_db":-3}}; a top-level {"edits":{...}} also works. keep restores even a
merged/thinned event and removes its former merged layer; drop withholds it.
role and gain (alias gain_db) change that event, including a merged layer.
Silent cues cannot be made audible. Unknown ids/actions are errors.

Needs numpy and FFmpeg only through shared sound_io (spotting itself uses no
audio or network). Exit 0 spotted; 1 reserved for review warnings; 2 could not
run. Decisions are starting points for listening, not a verdict. Unheard.
"""
import argparse
import copy
import csv
import importlib.util
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

_spec = importlib.util.spec_from_file_location('sound_io', Path(__file__).with_name('sound_io.py'))
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)
_project_spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(project)
_cue_spec = importlib.util.spec_from_file_location('lf_cue_list', Path(__file__).with_name('cue_list.py'))
cue_list = importlib.util.module_from_spec(_cue_spec)
_cue_spec.loader.exec_module(cue_list)


def finite(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    if minimum is not None and value < minimum:
        raise ValueError(name + ' is too small')
    return float(value)


def read_cues(path, loaded=None, prog='spot_cues.py'):
    """(document, events, fps) through cue_list.load: a stale list or an unbound plan is refused there, a v1 or an
    unverifiable list is read with its look printed, and a v2 rational fps arrives as a float."""
    listed = loaded or cue_list.load_for(prog, path)
    spec = listed.doc
    events = spec.get('events') if isinstance(spec, dict) else spec
    if not isinstance(events, list):
        raise ValueError('cues need an events list')
    fps = spec.get('fps') if isinstance(spec, dict) else None
    if listed.version == 'v2':
        fps = listed.fps
    elif fps is not None and finite(fps, 'fps', 0) <= 0:
        raise ValueError('fps must be positive')
    ids = set()
    for i, ev in enumerate(events):
        if not isinstance(ev, dict) or 'id' not in ev or isinstance(ev['id'], bool) or not isinstance(ev['id'], (str, int)):
            raise ValueError('every event needs a text/integer id')
        key = str(ev['id'])
        if key in ids:
            raise ValueError('event ids must be unique')
        ids.add(key)
        if 't' in ev:
            finite(ev['t'], 't', 0)
        elif 'frame' in ev and fps:
            finite(ev['frame'], 'frame', 0)
        else:
            raise ValueError('event needs t or frame and fps')
        if ev.get('sound', 'required') not in ('required', 'optional', 'silent'):
            raise ValueError('unknown sound kind')
        if ev.get('sync', 'attack') not in ('attack', 'apex', 'end'):
            raise ValueError('unknown sync point')
        if not isinstance(ev.get('enabled', True), bool):
            raise ValueError('enabled must be boolean')
        for name in ('gain_db', 'strength', 'window_ms', 'tolerance_ms'):
            if name in ev:
                value = finite(ev[name], name)
                if name.endswith('_ms') and value <= 0:
                    raise ValueError(name + ' must be positive')
        if not silent(ev) and (not isinstance(ev.get('role'), str) or not ev['role']):
            raise ValueError('audible event needs a role')
        layer_roles(ev, {})  # validate explicit layer structure
    return copy.deepcopy(spec), copy.deepcopy(events), fps


def silent(ev):
    return (ev.get('sound') == 'silent' or ev.get('reading_hold') is True or ev.get('kind') == 'reading-hold'
            or ev.get('scale') in ('follow', 'silence'))


def run_members(events):
    """The ids of events in a declared run: run: true itself, or a contact whose span is a follow with run: true."""
    runs = {str(ev['id']) for ev in events if ev.get('run') is True}
    return {str(ev['id']) for ev in events
            if str(ev['id']) in runs or (ev.get('span') is not None and str(ev.get('span')) in runs)}


def time_of(ev, fps):
    return ev['t'] if 't' in ev else ev['frame'] / fps


def active(ev):
    return ev.get('enabled', True) and not silent(ev)


def layer_roles(ev, roles):
    rs = roles.get(ev.get('role'), {})
    if not isinstance(rs, dict):
        raise ValueError('palette role must be an object')
    names = [ev.get('role')]
    for layers in (rs.get('layers', []), ev.get('layers', [])):
        if not isinstance(layers, list):
            raise ValueError('layers must be a list')
        for layer in layers:
            if not isinstance(layer, dict) or not isinstance(layer.get('role'), str):
                raise ValueError('each layer needs a role')
            if 'gain_db' in layer:
                finite(layer['gain_db'], 'layer gain_db')
            names.append(layer['role'])
    return names


def density(events, fps, roles):
    """Every violating rolling one-second window, counting non-recursive layers."""
    timed = sorted((time_of(ev, fps), i, ev) for i, ev in enumerate(events) if active(ev))
    windows = []
    right = 0
    counts = Counter()
    for left, (start, _, ev) in enumerate(timed):
        while right < len(timed) and timed[right][0] < start + 1 - 1e-9:
            counts.update(layer_roles(timed[right][2], roles))
            right += 1
        total = sum(counts.values())
        if total > 5 or any(n > 2 for n in counts.values()):
            windows.append({'from_s': start, 'to_s': start + 1, 'layers': total,
                            'by_role': dict(counts), 'ids': [e['id'] for _, _, e in timed[left:right]]})
        counts.subtract(layer_roles(ev, roles))
        counts += Counter()  # remove zero entries
    return windows


def spot(spec, events, fps, roles, edits):
    original = {str(ev['id']): copy.deepcopy(ev) for ev in events}
    kept_run = run_members(events)

    def in_run(ev):
        return str(ev['id']) in kept_run

    for ev in events:
        ev['spotting'] = []
        ev.setdefault('enabled', True)
        if ev.get('scale') == 'follow':
            ev['spotting'].append('follow span: an annotation, not a take' +
                                  ('; its contacts are a declared run, kept whole' if ev.get('run') is True else ''))
        elif ev.get('scale') == 'silence':
            ev.update(enabled=True)
            ev['spotting'].append('silence span: no take')
        elif silent(ev):
            ev.update(sound='silent', enabled=True)
            ev['spotting'].append('kept silent: reading hold or declared silent cue')
    audible = sorted((ev for ev in events if active(ev)), key=lambda e: time_of(e, fps))
    i = 0
    while i < len(audible):
        j = i + 1
        while j < len(audible) and time_of(audible[j], fps) - time_of(audible[i], fps) < .060 - 1e-9:
            j += 1
        group = audible[i:j]
        if len(group) > 1:
            winner = max(group, key=lambda e: (in_run(e), e.get('strength', e.get('gain_db', 0)),
                                              e.get('sound', 'required') == 'required', -events.index(e)))
            winner['spotting'].append('gesture: strongest event kept at its picture time (<60 ms cluster)')
            present = set(layer_roles(winner, roles))
            for ev in group:
                if ev is winner:
                    continue
                if in_run(ev):
                    ev['spotting'].append('declared run: kept inside a <60 ms cluster')
                    continue
                ev.update(enabled=False, sound='optional', merged_into=winner['id'])
                if ev['role'] not in present:
                    # Mixer adds the winner's event gain to each layer. Preserve
                    # this source event's original gain when converting it.
                    winner.setdefault('layers', []).append({'role': ev['role'], 'source_id': ev['id'],
                        'gain_db': ev.get('gain_db', 0) - winner.get('gain_db', 0)})
                    present.add(ev['role'])
                    ev['spotting'].append('merged as a layer of ' + str(winner['id']))
                else:
                    ev['spotting'].append('dropped duplicate role from gesture ' + str(winner['id']))
        i = j
    # Runs are per role; unrelated interleaved roles do not break a typing run.
    for ev in events:
        if in_run(ev) and active(ev):
            ev['spotting'].append('declared run: every event kept (run: true)')
    for role in sorted({e['role'] for e in events if active(e) and not in_run(e)}):
        rows = sorted((e for e in events if active(e) and not in_run(e) and e['role'] == role),
                      key=lambda e: time_of(e, fps))
        i = 0
        while i < len(rows):
            j = i + 1
            while j < len(rows) and time_of(rows[j], fps) - time_of(rows[j - 1], fps) < .120 - 1e-9:
                j += 1
            if j - i > 1:
                rows[i]['spotting'].append('run: first event kept synced (<120 ms adjacent gaps)')
                rows[i + 1].update(sound='optional', texture=True)
                rows[i + 1]['spotting'].append('run: one optional texture accent kept')
                for ev in rows[i + 2:j]:
                    ev.update(sound='optional', enabled=False)
                    ev['spotting'].append('run: withheld after the first and one texture accent')
            i = j
    accepted, looks = [], []
    for ev in sorted((e for e in events if active(e)), key=lambda e: time_of(e, fps)):
        if in_run(ev):
            accepted.append(ev)
            continue
        windows = density(accepted + [ev], fps, roles)
        if windows and (ev.get('hero') is True or ev.get('sound', 'required') == 'required'):
            # A required or hero event is the person's call: keep it and say what it crowds.
            mine = [w for w in windows if str(ev['id']) in {str(i) for i in w['ids']}] or windows
            neighbours = sorted({str(i) for w in mine for i in w['ids']} - {str(ev['id'])})
            why = 'hero' if ev.get('hero') is True else 'required'
            ev['spotting'].append(f'density: kept ({why}); its rolling second exceeds 2 of one role or 5 total layers '
                                  f'with {", ".join(neighbours)}: a look, decide with --edits')
            looks.append({'id': ev['id'], 't': time_of(ev, fps), 'role': ev.get('role'), 'why': why,
                          'neighbours': neighbours,
                          'windows': [{k: w[k] for k in ('from_s', 'to_s', 'layers', 'by_role')} for w in mine]})
            accepted.append(ev)
        elif windows:
            ev.update(sound='optional', enabled=False)
            ev['spotting'].append('density: withheld optional choice; rolling second exceeds 2 of one role or 5 total layers')
        else:
            accepted.append(ev)
    by_id = {str(e['id']): e for e in events}
    if not isinstance(edits, dict):
        raise ValueError('edits must be an object keyed by event id')
    for key, change in edits.items():
        if str(key) not in by_id:
            raise ValueError('unknown edit id: ' + str(key))
        ev = by_id[str(key)]
        if isinstance(change, str):
            change = {'action': change}
        if not isinstance(change, dict) or set(change) - {'action', 'keep', 'drop', 'role', 'gain', 'gain_db'}:
            raise ValueError('edit needs keep/drop, role or gain')
        action = change.get('action')
        if 'keep' in change:
            if change['keep'] is not True or action:
                raise ValueError('keep edit must be true, without a second action')
            action = 'keep'
        if 'drop' in change:
            if change['drop'] is not True or action:
                raise ValueError('drop edit must be true, without a second action')
            action = 'drop'
        if action not in (None, 'keep', 'drop'):
            raise ValueError('unknown edit action')
        parent = by_id.get(str(ev.get('merged_into')))
        if parent and action in ('keep', 'drop'):
            parent['layers'] = [l for l in parent.get('layers', []) if l.get('source_id') != ev['id']]
            parent['spotting'].append('edit removed merged layer ' + str(ev['id']))
        if action == 'keep':
            ev['enabled'] = True
            ev['sound'] = original[str(key)].get('sound', 'required')
            ev.pop('merged_into', None)
        elif action == 'drop':
            ev.update(enabled=False, sound='optional')
        if 'role' in change:
            if not isinstance(change['role'], str) or not change['role']:
                raise ValueError('edited role must be non-empty text')
            ev['role'] = change['role']
        if 'gain' in change and 'gain_db' in change:
            raise ValueError('choose gain or gain_db, not both')
        gain = change.get('gain_db', change.get('gain'))
        if gain is not None:
            ev['gain_db'] = finite(gain, 'edited gain')
        if parent and action is None:
            for layer in parent.get('layers', []):
                if layer.get('source_id') == ev['id']:
                    layer.update(role=ev['role'], gain_db=ev.get('gain_db', 0) - parent.get('gain_db', 0))
        if silent(original[str(key)]):
            ev.update(sound='silent', enabled=True)
        ev['spotting'].append('edit applied last: ' + json.dumps(change, sort_keys=True))
    decided = {str(key) for key in edits}   # an edit on a kept event is the person's decision: no longer a look
    looks = [look for look in looks if str(look['id']) not in decided]
    for ev in events:
        if not ev['spotting']:
            ev['spotting'].append('kept unchanged' if active(ev) else 'kept withheld as supplied')
    result = spec if isinstance(spec, dict) else {}
    result['events'] = events
    result['spotting'] = {'merge_ms': 60, 'run_ms': 120, 'max_per_role_per_second': 2,
                          'max_layers_per_second': 5, 'edits_applied_last': True,
                          'density_after_edits': density(events, fps, roles), 'looks': looks,
                          'palette_layers_counted': bool(roles), 'status': 'unheard'}
    return result


def rebase(doc, source_dir, out_dir):
    """Re-express a v2 list's picture path (and a picture list's frame schedule) from the folder the spotted list is
    written to, so it still resolves its owner there: conform and the mixer read the spotted list."""
    picture = doc.get('picture') if isinstance(doc, dict) else None
    if not isinstance(picture, dict) or source_dir == out_dir:
        return
    def moved(rel, folder=False):
        target = Path(rel) if os.path.isabs(rel) else source_dir / rel
        try:
            text = os.path.relpath(target, out_dir).replace(os.sep, '/')
        except ValueError:   # another drive
            text = target.as_posix()
        return text.rstrip('/') + '/' if folder else text
    if isinstance(picture.get('path'), str) and picture['path']:
        picture['path'] = moved(picture['path'], picture['path'].endswith('/'))
    timing = picture.get('timing')
    if isinstance(timing, dict) and isinstance(timing.get('pts_file'), str):
        timing['pts_file'] = moved(timing['pts_file'])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('cues'); p.add_argument('--out-dir'); p.add_argument('--edits')
    p.add_argument('--palette'); p.add_argument('--json')
    a = p.parse_args()
    try:
        out = Path(a.out_dir) if a.out_dir else Path(a.cues).resolve().parent
        project.refuse_overwriting_inputs([out / 'cues.spotted.json', out / 'spotting.csv', a.json],
                                          [a.cues, a.edits, a.palette])
        spec, events, fps = read_cues(a.cues)
        palette = json.loads(Path(a.palette).read_text(encoding='utf-8')) if a.palette else {}
        if not isinstance(palette, dict):
            raise ValueError('palette must be an object')
        roles = palette.get('roles', {})
        if not isinstance(roles, dict):
            raise ValueError('palette roles must be an object')
        roles = io.current_roles(roles)
        io.current_events(events)
        edits = json.loads(Path(a.edits).read_text(encoding='utf-8')) if a.edits else {}
        if isinstance(edits, dict) and 'edits' in edits:
            edits = edits['edits']
        result = spot(spec, events, fps, roles, edits)
        rebase(result, Path(a.cues).resolve().parent, out.resolve())
        io.save_json(out / 'cues.spotted.json', result)
        with (out / 'spotting.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(('id', 't', 'role', 'sound', 'enabled', 'layers', 'explanation'))
            for ev in events:
                writer.writerow((ev['id'], time_of(ev, fps), ev.get('role', ''), ev.get('sound', 'required'),
                                 ev['enabled'], json.dumps(ev.get('layers', [])), '; '.join(ev['spotting'])))
        if a.json:
            io.save_json(a.json, result)
        looks = result['spotting'].get('looks', [])
        for look in looks:
            print(f"look: {look['why']} event {look['id']} at {look['t']:.3f} s kept: its rolling second is crowded with "
                  f"{', '.join(look['neighbours'])}; drop one with --edits if the person decides")
        print(f'Spotted {len(events)} events; {sum(active(e) for e in events)} audible gestures; '
              f'{len(result["spotting"]["density_after_edits"])} dense windows after edits. Unheard.')
        return 1 if looks else 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print('spot_cues.py: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
