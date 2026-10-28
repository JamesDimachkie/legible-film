#!/usr/bin/env python3
"""Measure where sounds start against the cue list: the clock, checked on audio.

For each cue in cues.json, find the strongest sound onset near the cue time and report the offset
in milliseconds. Cues marked "silent" are checked for unexpected new sounds instead. The cue list
itself is linted first (sounds stacked on one instant, required cues inside a silent window).

  python cue_onsets.py audio/effects_stem.wav cues.json
  python cue_onsets.py deliver/film.mp4 cues.json --chance 200 --json qa/cues.json

cues.json (times in seconds on the film clock; "frame" plus a top-level "fps" also works):
  {"fps": 30, "events": [
     {"id": "send-click", "t": 3.0, "sound": "required", "sync": "attack", "tolerance_ms": 20},
     {"id": "whoosh-in", "t": 5.2, "sound": "required", "sync": "apex"},
     {"id": "read-hold", "t": 7.0, "sound": "silent", "window_ms": 600}]}
  sound: required | silent | optional (optional cues are reported, never failed)
  sync:  attack (where the sound starts) | apex (its loudest instant, e.g. a whoosh)
  window_ms: how far either side of t to look (t 7.0 with window_ms 600 checks 6.4-7.6 s)
  tolerance_ms: the largest offset that still counts as on cue
A cue list that cannot be checked as written (no time, an unknown sound or sync, a window or
tolerance that is not a positive number) is rejected before any audio is read.

Run it on an effects stem when you have one. In a full mix, music has so many onsets that a cue
can "hit" by luck: --chance N re-runs the measurement at N sets of random cue times and reports
how often chance alone lands within tolerance. A hit rate no better than chance is inconclusive.
Each result carries the rise in dB that identified it; a weak rise is reported as weak, not as an
error. This measures audio timing against the list; whether the list matches the picture, and
whether the sound feels right, still need a person watching and listening.
Needs numpy and FFmpeg. Exit code 0 when every cue that is not optional checks out; 1 when a
required cue is missed or off tolerance, a silent cue has a new sound, or such a cue lies outside
the audio; 2 when the cue list is invalid or the audio cannot be read.
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit('cue_onsets.py needs numpy: pip install numpy')

RATE = 48000
HOP = 48            # 1 ms
FRAME = 240         # 5 ms RMS window
LAG = FRAME // HOP  # a new sound first shows at the window's end: stamp frame k at (k + LAG) ms


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def envelope_db(x):
    n = max(0, (len(x) - FRAME) // HOP + 1)
    if n == 0:
        return np.zeros(0)
    csum = np.concatenate([[0.0], np.cumsum(x * x)])
    starts = np.arange(n) * HOP
    rms = np.sqrt((csum[starts + FRAME] - csum[starts]) / FRAME)
    return 20 * np.log10(rms + 1e-9)


class Signal:
    def __init__(self, x, rise_db, floor_db):
        self.env = envelope_db(x)
        self.rise = np.zeros_like(self.env)
        self.rise[3:] = self.env[3:] - self.env[:-3]
        self.rise_db, self.floor_db = rise_db, floor_db

    def window(self, t, win):
        k0 = int(round(t * 1000)) - LAG
        return k0, max(3, k0 - int(win)), min(len(self.env) - 1, k0 + int(win))

    def strongest_new_sound(self, lo, hi):
        seg_rise, seg_env = self.rise[lo:hi + 1], self.env[lo:hi + 1]
        hits = np.nonzero((seg_rise >= self.rise_db) & (seg_env >= self.floor_db))[0]
        return None if not hits.size else lo + int(hits[np.argmax(seg_rise[hits])])

    def attack(self, lo, hi):
        """(found, frame, strength): the steepest qualifying rise, stepped back to where it starts."""
        k = self.strongest_new_sound(lo, hi)
        found = k is not None
        if not found:
            k = lo + int(np.argmax(self.rise[lo:hi + 1]))
        strength = float(self.rise[k])
        background = float(np.median(self.env[lo:hi + 1]))
        start = k
        while start - 1 >= lo and k - (start - 1) <= 5 and self.env[start - 1] > background + 3.0:
            start -= 1
        return found, start, strength

    def apex(self, lo, hi):
        seg = self.env[lo:hi + 1]
        k = lo + int(np.argmax(seg))
        return seg.max() >= self.floor_db, k, float(self.env[k] - np.median(seg))


def cue_time(ev, fps):
    if 't' in ev:
        return float(ev['t'])
    if 'frame' in ev and fps:
        return float(ev['frame']) / float(fps)
    return None


def number(x, positive=False):
    ok = isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
    return ok and (x > 0 if positive else x >= 0)


def finite(text):
    """argparse type: a finite number."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{text!r} is not a number')
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f'{text!r} is not a finite number')
    return value


def positive(text):
    """argparse type: a finite number above zero."""
    value = finite(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f'{text!r} must be above zero')
    return value


def validate(spec):
    """(events, fps, problems): every reason the cue list cannot be checked as written."""
    events = spec.get('events') if isinstance(spec, dict) else spec
    fps = spec.get('fps') if isinstance(spec, dict) else None
    if not isinstance(events, list) or not events:
        return [], None, ['the cue file needs a non-empty "events" list']
    problems = []
    if fps is not None and not number(fps, positive=True):
        problems.append(f'"fps" must be a positive number, not {fps!r}')
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            problems.append(f'event {i} is not an object')
            continue
        cue_id = ev.get('id', i)
        if isinstance(cue_id, bool) or not isinstance(cue_id, (str, int, float)):
            problems.append(f'event {i}: id must be text or a number, not {cue_id!r}')
            continue
        name = f'cue {cue_id!r}'
        if ev.get('sound', 'required') not in ('required', 'silent', 'optional'):
            problems.append(f"{name}: sound must be required, silent or optional, not {ev.get('sound')!r}")
        if ev.get('sync', 'attack') not in ('attack', 'apex'):
            problems.append(f"{name}: sync must be attack or apex, not {ev.get('sync')!r}")
        if 't' in ev:
            if not number(ev['t']):
                problems.append(f"{name}: t must be a time in seconds, 0 or more, not {ev['t']!r}")
        elif 'frame' in ev:
            if not number(ev['frame']):
                problems.append(f"{name}: frame must be a frame number, 0 or more, not {ev['frame']!r}")
            elif not fps:
                problems.append(f'{name}: "frame" needs a top-level "fps"')
        else:
            problems.append(f'{name} has no time: give "t" in seconds, or "frame" with a top-level "fps"')
        for key in ('tolerance_ms', 'window_ms'):
            if key in ev and not number(ev[key], positive=True):
                problems.append(f'{name}: {key} must be a positive number of milliseconds, not {ev[key]!r}')
    return events, fps, problems


def lint(events, fps, duration_s, stack_ms):
    """Problems in the plan itself, before any audio is judged."""
    notes, seen = [], set()
    timed = [(cue_time(ev, fps), ev) for ev in events]
    for t, ev in timed:
        if ev.get('id') in seen:
            notes.append(f"duplicate id {ev.get('id')}")
        seen.add(ev.get('id'))
        if t is not None and t > duration_s:
            notes.append(f"cue {ev.get('id')} at {t:.3f} s is after the audio ends ({duration_s:.3f} s)")
    required = sorted(((t, ev) for t, ev in timed if t is not None and ev.get('sound', 'required') == 'required'),
                      key=lambda item: item[0])
    for (t1, e1), (t2, e2) in zip(required, required[1:]):
        if (t2 - t1) * 1000 < stack_ms:
            notes.append(f"{e1.get('id')} and {e2.get('id')} are {round((t2 - t1) * 1000)} ms apart: "
                         'decide whether they are one gesture')
    for ts, es in timed:
        if ts is None or es.get('sound') != 'silent':
            continue
        half = float(es.get('window_ms', 120)) / 1000
        for tr, er in required:
            if abs(tr - ts) <= half:
                notes.append(f"required {er.get('id')} falls inside silent window {es.get('id')}")
    return notes


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('audio', help='a stem, a mix, or a video file with audio')
    p.add_argument('cues')
    p.add_argument('--window-ms', type=positive, default=120.0, help='search this far either side of each cue')
    p.add_argument('--tolerance-ms', type=positive, default=25.0, help='default for cues without tolerance_ms')
    p.add_argument('--rise-db', type=finite, default=9.0, help='a rise this large over 3 ms counts as an onset')
    p.add_argument('--floor-db', type=finite, default=-55.0, help='ignore onsets quieter than this (dBFS RMS)')
    p.add_argument('--stack-ms', type=finite, default=50.0, help='lint: required cues closer than this')
    p.add_argument('--chance', type=int, default=0, help='random cue sets for a chance baseline (e.g. 200)')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    a = p.parse_args()
    ffmpeg = find_tool('ffmpeg', a.ffmpeg)
    if not ffmpeg:
        print('ffmpeg is required (PATH, FFMPEG, or --ffmpeg)', file=sys.stderr)
        return 2
    try:
        with open(a.cues, encoding='utf-8') as fh:
            spec = json.load(fh)
    except OSError as e:
        print(f'cue_onsets.py: cannot read cue file {a.cues}: {e.strerror or e}', file=sys.stderr)
        return 2
    except UnicodeError:
        print(f'cue_onsets.py: cannot read cue file {a.cues}: it is not UTF-8 text', file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f'cue_onsets.py: cannot read cue file {a.cues}: invalid JSON at line {e.lineno}, column {e.colno}',
              file=sys.stderr)
        return 2
    events, fps, problems = validate(spec)
    if problems:
        print(f'cue_onsets.py: {a.cues} cannot be checked as written:', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 2
    r = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', a.audio, '-map', '0:a:0', '-ac', '1', '-ar', str(RATE),
                        '-f', 'f32le', '-'], capture_output=True, check=False)
    if r.returncode:
        print('could not decode audio: ' + r.stderr.decode(errors='replace').strip()[-200:], file=sys.stderr)
        return 2
    x = np.frombuffer(r.stdout, np.float32).astype(np.float64)
    sig = Signal(x, a.rise_db, a.floor_db)
    duration = len(x) / RATE
    notes = lint(events, fps, duration, a.stack_ms)

    rows = []
    for ev in events:
        t = cue_time(ev, fps)
        kind, sync = ev.get('sound', 'required'), ev.get('sync', 'attack')
        tol = float(ev.get('tolerance_ms', a.tolerance_ms))
        win = float(ev.get('window_ms', a.window_ms))
        k0, lo, hi = sig.window(t, win)
        row = {'id': ev.get('id'), 't': round(t, 4), 'sound': kind, 'sync': sync}
        if hi <= lo:
            row['status'] = 'outside audio'
            rows.append(row)
            continue
        if kind == 'silent':
            k = sig.strongest_new_sound(lo, hi)
            if k is None:
                row['status'] = 'quiet as intended'
            else:
                row.update(status='UNEXPECTED SOUND', onset_s=round((k + LAG) / 1000, 4),
                           rise_db=round(float(sig.rise[k]), 1), level_db=round(float(sig.env[k]), 1))
            rows.append(row)
            continue
        found, k, strength = sig.apex(lo, hi) if sync == 'apex' else sig.attack(lo, hi)
        offset = k - k0  # milliseconds, because HOP is 1 ms
        row.update(onset_s=round((k + LAG) / 1000, 4), offset_ms=offset, strength_db=round(strength, 1),
                   level_db=round(float(sig.env[k]), 1), tolerance_ms=tol)
        if not found:
            row['status'] = 'missing' if kind == 'required' else 'none found'
        elif abs(offset) <= tol:
            row['status'] = 'on cue'
        else:
            row['status'] = 'LATE' if offset > 0 else 'EARLY'
        if found and sync == 'attack' and strength < a.rise_db + 3:
            row['confidence'] = 'weak'
        rows.append(row)

    measured = [r['offset_ms'] for r in rows if r.get('status') in ('on cue', 'LATE', 'EARLY')]
    scored = [r for r in rows if r['sound'] == 'required' and r['sync'] == 'attack' and 'offset_ms' in r]
    hit_rate = sum(1 for r in scored if r['status'] == 'on cue') / len(scored) if scored else None
    summary = {'cues': len(rows), 'measured': len(measured),
               'median_offset_ms': float(np.median(measured)) if measured else None,
               'spread_ms': (max(measured) - min(measured)) if measured else None,
               'hit_rate': round(hit_rate, 3) if hit_rate is not None else None,
               'failures': sum(1 for r in rows if r.get('status') in ('missing', 'LATE', 'EARLY', 'UNEXPECTED SOUND',
                                                                     'outside audio') and r['sound'] != 'optional')}
    if a.chance and scored:
        rng = np.random.default_rng(0)
        margin = a.window_ms / 1000 + 0.01
        rates = []
        for _ in range(a.chance):
            hits = 0
            for row in scored:
                t = float(rng.uniform(margin, max(margin, duration - margin)))
                k0, lo, hi = sig.window(t, a.window_ms)
                found, k, _ = sig.attack(lo, hi)
                hits += found and abs(k - k0) <= row['tolerance_ms']
            rates.append(hits / len(scored))
        p95 = float(np.percentile(rates, 95))
        summary['chance'] = {'sets': a.chance, 'mean_hit_rate': round(float(np.mean(rates)), 3),
                             'p95_hit_rate': round(p95, 3),
                             'verdict': ('above chance' if hit_rate > p95 else
                                         'inconclusive: no better than random cue times in this audio')}
    out = {'audio': a.audio, 'cues': a.cues, 'lint': notes, 'summary': summary, 'rows': rows,
           'limit': 'Audio timing against the cue list; not a judgement of picture sync or of the sound.'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=1)
    print(f"{os.path.basename(a.audio)} against {os.path.basename(a.cues)}: {summary['measured']} onsets measured; "
          f"median offset {summary['median_offset_ms']} ms; spread {summary['spread_ms']} ms; "
          f"hit rate {summary['hit_rate']}; {summary['failures']} failure(s)")
    for note in notes:
        print(f'  lint: {note}')
    if 'chance' in summary:
        c = summary['chance']
        print(f"  chance baseline over {c['sets']} random cue sets: mean {c['mean_hit_rate']}, "
              f"95th percentile {c['p95_hit_rate']} -> {c['verdict']}")
    for row in rows:
        detail = (f"offset {row['offset_ms']:+d} ms (tol {row['tolerance_ms']:g}), strength {row['strength_db']} dB"
                  if 'offset_ms' in row else (f"onset at {row['onset_s']} s, rise {row['rise_db']} dB"
                                              if 'onset_s' in row else ''))
        print(f"  {str(row['id']):20s} {row['t']:8.3f} s  {row['sound']:8s} {row.get('status', ''):18s} {detail}"
              + ('  (weak)' if row.get('confidence') == 'weak' else ''))
    return 1 if summary['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
