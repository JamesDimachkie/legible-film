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
given. Excess gestures become disabled optional choices, never audible by default.
The first event is favoured by time; edits may deliberately exceed these limits.

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
import sys
from collections import Counter
from pathlib import Path

_spec = importlib.util.spec_from_file_location('sound_io', Path(__file__).with_name('sound_io.py'))
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)


def finite(value, name, minimum=None):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    if minimum is not None and value < minimum:
        raise ValueError(name + ' is too small')
    return float(value)


def read_cues(path):
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    events = spec.get('events') if isinstance(spec, dict) else spec
    if not isinstance(events, list):
        raise ValueError('cues need an events list')
    fps = spec.get('fps') if isinstance(spec, dict) else None
    if fps is not None and finite(fps, 'fps', 0) <= 0:
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
    return ev.get('sound') == 'silent' or ev.get('reading_hold') is True or ev.get('kind') == 'reading-hold'


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
    for ev in events:
        ev['spotting'] = []
        ev.setdefault('enabled', True)
        if silent(ev):
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
            winner = max(group, key=lambda e: (e.get('strength', e.get('gain_db', 0)),
                                              e.get('sound', 'required') == 'required', -events.index(e)))
            winner['spotting'].append('gesture: strongest event kept at its picture time (<60 ms cluster)')
            present = set(layer_roles(winner, roles))
            for ev in group:
                if ev is winner:
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
    for role in sorted({e['role'] for e in events if active(e)}):
        rows = sorted((e for e in events if active(e) and e['role'] == role), key=lambda e: time_of(e, fps))
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
    accepted = []
    for ev in sorted((e for e in events if active(e)), key=lambda e: time_of(e, fps)):
        if density(accepted + [ev], fps, roles):
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
    for ev in events:
        if not ev['spotting']:
            ev['spotting'].append('kept unchanged' if active(ev) else 'kept withheld as supplied')
    result = spec if isinstance(spec, dict) else {}
    result['events'] = events
    result['spotting'] = {'merge_ms': 60, 'run_ms': 120, 'max_per_role_per_second': 2,
                          'max_layers_per_second': 5, 'edits_applied_last': True,
                          'density_after_edits': density(events, fps, roles),
                          'palette_layers_counted': bool(roles), 'status': 'unheard'}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('cues'); p.add_argument('--out-dir'); p.add_argument('--edits')
    p.add_argument('--palette'); p.add_argument('--json')
    a = p.parse_args()
    try:
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
        out = Path(a.out_dir) if a.out_dir else Path(a.cues).resolve().parent
        io.save_json(out / 'cues.spotted.json', result)
        with (out / 'spotting.csv').open('w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(('id', 't', 'role', 'sound', 'enabled', 'layers', 'explanation'))
            for ev in events:
                writer.writerow((ev['id'], time_of(ev, fps), ev.get('role', ''), ev.get('sound', 'required'),
                                 ev['enabled'], json.dumps(ev.get('layers', [])), '; '.join(ev['spotting'])))
        if a.json:
            io.save_json(a.json, result)
        print(f'Spotted {len(events)} events; {sum(active(e) for e in events)} audible gestures; '
              f'{len(result["spotting"]["density_after_edits"])} dense windows after edits. Unheard.')
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print('spot_cues.py: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
