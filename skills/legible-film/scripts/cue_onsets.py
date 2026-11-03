#!/usr/bin/env python3
"""Measure where sounds start against the cue list: the clock, checked on audio.

For each cue in cues.json, find the strongest sound onset near its intended sound time and report
the offset in milliseconds. A turn also reports the offset from its picture time. Cues marked
"silent" are checked for unexpected new sounds instead. Disabled
spotted events (enabled: false) are withheld; silent cues remain checked.
The cue list
itself is linted first (sounds stacked on one instant, required cues inside a silent window).

  python cue_onsets.py audio/effects_stem.wav cues.json
  python cue_onsets.py deliver/film.mp4 cues.json --chance 200 --json qa/cues.json
  python cue_onsets.py mix.wav cues.json --reference click=sfx/click.wav
  python cue_onsets.py mix.wav old-cues.json --reference click=sfx/click.wav --expect-absent

cues.json (times in seconds on the film clock; "frame" plus a top-level "fps" also works):
  {"fps": 30, "events": [
     {"id": "send-click", "t": 3.0, "sound": "required", "sync": "attack", "tolerance_ms": 20},
     {"id": "whoosh-in", "t": 5.2, "sound": "required", "sync": "apex"},
     {"id": "read-hold", "t": 7.0, "sound": "silent", "window_ms": 600}]}
  sound: required | silent | optional (optional cues are reported, never failed)
  sync:  attack (where the sound starts) | apex (its loudest instant, e.g. a whoosh) | end (audible end)
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
Reference matching measures each zero-mean candidate directly, excludes windows below -140 dBFS of varying
energy, and bounds correlation to [-1, 1]. second_best is the best usable window at least one reference length or
2 ms, whichever is greater, from the winner; competitor_exclusion_s records that distance. A null second_best or
margin means there was no such competitor. Overlapping occurrences inside that distance are not ruled out.
Distinct competing peaks are inconclusive, not proof of absence. Very long references and search windows take
more computation.
Reference attack is the first sample, apex is the maximum absolute sample, and end is the last
sample; trim the isolated file to the intended audible boundaries. Relative ref paths are relative
to the cue file. --expect-absent checks only referenced cues. Inconclusive results exit 1.
An output report cannot name the audio, cue file or any reference, including through a link. Needs numpy and FFmpeg.
Exit code 0 when every cue that is not optional checks out; 1 when a
required cue is missed or off tolerance, a silent cue has a new sound, or such a cue lies outside
the audio; 2 when the cue list is invalid or the audio cannot be read.
"""

import argparse
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
_cue_spec = importlib.util.spec_from_file_location('lf_cue_list', Path(__file__).with_name('cue_list.py'))
cue_list = importlib.util.module_from_spec(_cue_spec)
_cue_spec.loader.exec_module(cue_list)
try:
    import numpy as np
except ImportError as missing:
    print(project.dependency_message(missing.name or 'numpy'), file=sys.stderr)
    sys.exit(2)

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
    if x.ndim == 1:
        frames = np.lib.stride_tricks.as_strided(x, shape=(n, FRAME),
                                                  strides=(x.strides[0] * HOP, x.strides[0]), writeable=False)
        rms = np.sqrt(np.einsum('ij,ij->i', frames, frames) / FRAME)
    else:
        frames = np.lib.stride_tricks.as_strided(x, shape=(n, FRAME, x.shape[1]),
                                                  strides=(x.strides[0] * HOP, x.strides[0], x.strides[1]),
                                                  writeable=False)
        rms = np.sqrt(np.einsum('ijk,ijk->i', frames, frames) / (FRAME * x.shape[1]))
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

    def end(self, lo, hi):
        """A qualifying energy fall, stamped at the end, not the RMS window end.

        Search the corresponding forward-window indices. An end needs audible
        energy before the fall; silence throughout cannot count as a found end.
        A gradual decay has a threshold-dependent audible end.
        """
        env = np.pad(self.env, (0, LAG + 8), constant_values=-240.0)
        a, b = max(3, lo + LAG), min(len(env) - 1, hi + LAG)
        if b < a:
            return False, lo, 0.0
        fall = env[a - 3:b - 2] - env[a:b + 1]
        audible = env[a - 3:b - 2] >= self.floor_db
        # A temporary notch inside a sound is not its audible end. Require a
        # quiet run after the candidate (at least 5 ms where available).
        quiet_after = np.array([len(env[k:min(len(env), k + 8)]) >= 5 and
                                np.max(env[k:min(len(env), k + 8)]) < self.floor_db
                                for k in range(a, b + 1)])
        hits = np.flatnonzero((fall >= self.rise_db) & audible & quiet_after)
        if not hits.size:
            k = int(np.argmax(fall))
            return False, a + k - LAG, float(fall[k])
        k = int(hits[np.argmax(fall[hits])])
        # A fall into padding is the file endpoint: stamp the last original
        # window's right edge and keep the index valid for level reporting.
        frame = len(self.env) - 1 if a + k >= len(self.env) else a + k - LAG
        return True, frame, float(fall[k])


def cue_time(ev, fps):
    if 't' in ev:
        return float(ev['t'])
    if 'frame' in ev and fps:
        return float(ev['frame']) / float(fps)
    return None


def audio_time(ev, fps, offset=0):
    """Map a picture cue onto the decoded audio clock."""
    value = cue_time(ev, fps)
    if value is None:
        return None
    lead = float(ev.get('lead_ms', 0)) / 1000 if ev.get('scale') == 'turn' else 0
    return value + lead - offset


def picture_offset_ms(row, picture_t, offset):
    """Measure a found turn on the picture clock."""
    return round((row['onset_s'] + offset - picture_t) * 1000, 3)


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
        if not isinstance(ev.get('enabled', True), bool):
            problems.append(f'{name}: enabled must be boolean')
        if ev.get('sound', 'required') not in ('required', 'silent', 'optional', 'absent'):
            problems.append(f"{name}: sound must be required, silent, optional or absent, not {ev.get('sound')!r}")
        if ev.get('sync', 'attack') not in ('attack', 'apex', 'end'):
            problems.append(f"{name}: sync must be attack, apex or end, not {ev.get('sync')!r}")
        if ev.get('scale', 'contact') not in ('contact', 'turn', 'follow', 'silence'):
            problems.append(f"{name}: unknown scale {ev.get('scale')!r}")
        if 'lead_ms' in ev and (not isinstance(ev['lead_ms'], (int, float)) or
                                isinstance(ev['lead_ms'], bool) or not math.isfinite(ev['lead_ms'])):
            problems.append(f"{name}: lead_ms must be a finite number")
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
        if 'ref' in ev and (not isinstance(ev['ref'], str) or not ev['ref']):
            problems.append(f'{name}: ref must be a nonempty path')
        for key in ('tolerance_ms', 'window_ms'):
            if key in ev and not number(ev[key], positive=True):
                problems.append(f'{name}: {key} must be a positive number of milliseconds, not {ev[key]!r}')
    return events, fps, problems


def lint(events, fps, duration_s, stack_ms, offset=0):
    """Problems in the plan itself, before any audio is judged."""
    notes, seen = [], set()
    timed = [(audio_time(ev, fps, offset), ev) for ev in events]
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


def reference_match(x, ref, t, sync, win, tol, absent, refpath):
    """Find a reference on the audio clock using locally normalised correlation."""
    # Compute each candidate from its own samples. Prefix sums and FFT roundoff after loud material can turn
    # silent windows into huge false correlations. Bound batch memory independently of reference duration.
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(ref)):
        raise ValueError('audio or reference contains non-finite samples')
    ref = ref - np.mean(ref)
    n = len(ref)
    energy = float(np.dot(ref, ref))
    if n < 2 or energy < 1e-12:
        raise ValueError('reference is silent or too short')
    point = 0 if sync == 'attack' else n - 1 if sync == 'end' else int(np.argmax(np.abs(ref)))
    lo = max(0, int(round((t - win / 1000) * RATE)) - point)
    hi = min(len(x) - n, int(round((t + win / 1000) * RATE)) - point)
    if hi < lo:
        raise ValueError('reference does not fit in the audio search window')
    seg = x[lo:hi + n]
    count = hi - lo + 1
    windows = np.lib.stride_tricks.as_strided(seg, shape=(count, n),
                                               strides=(seg.strides[0], seg.strides[0]), writeable=False)
    corr = np.full(count, np.nan)
    batch_size = max(1, min(256, (8 * 1024 * 1024) // (8 * n)))
    for start in range(0, count, batch_size):
        batch = windows[start:start + batch_size]
        centered = batch - np.mean(batch, axis=1, keepdims=True)
        power = np.einsum('ij,ij->i', centered, centered)
        numerator = np.einsum('ij,j->i', centered, ref)
        usable = power > n * 1e-14  # RMS above -140 dBFS after removing DC.
        values = np.full(len(batch), np.nan)
        values[usable] = np.clip(numerator[usable] / np.sqrt(power[usable] * energy), -1.0, 1.0)
        corr[start:start + len(batch)] = values
    if not np.any(np.isfinite(corr)):
        quiet = float(np.sqrt(np.mean(seg * seg))) < 10 ** (-55 / 20)
        status = ('quiet as intended' if absent else 'missing') if quiet else 'inconclusive'
        row = {'reference': refpath, 'correlation': None, 'second_best': None, 'margin': None,
               'status': status, 'reason': 'no candidate window has usable varying energy'}
        if status == 'inconclusive':
            row['next'] = f'Check the isolated effects stem and reference {refpath}; listen at {t:.3f} s.'
        return row
    best = int(np.nanargmax(corr))
    peak = float(corr[best])
    # Shifted copies that overlap the winning reference window can be the same sustained event. Compare a second
    # independent window, and expose the exclusion so an overlapping second sound is not claimed to be ruled out.
    guard = max(n, int(.002 * RATE))
    masked = corr.copy()
    masked[max(0, best - guard + 1):best + guard] = np.nan
    second = float(np.nanmax(masked)) if np.any(np.isfinite(masked)) else None
    margin = peak - second if second is not None else None
    offset = ((lo + best + point) / RATE - t) * 1000
    best_window = windows[best]
    gain = float(np.dot(best_window - np.mean(best_window), ref) / energy)
    level = 20 * math.log10(max(1e-12, abs(gain) * np.sqrt(energy / n)))
    row = dict(onset_s=round((lo + best + point) / RATE, 5), offset_ms=round(offset, 3),
               tolerance_ms=tol, correlation=round(peak, 4),
               second_best=round(second, 4) if second is not None else None,
               margin=round(margin, 4) if margin is not None else None,
               competitor_exclusion_s=round(guard / RATE, 5), level_db=round(level, 1), reference=refpath)
    if peak < .15 and float(np.sqrt(np.mean(seg * seg))) < 10 ** (-55 / 20):
        status = 'quiet as intended' if absent else 'missing'
        reason = 'search window is below -55 dBFS RMS'
    elif peak < .35:
        status, reason = 'inconclusive', 'weak reference correlation'
    elif second is not None and (margin < .05 or second > .95 * peak):
        status, reason = 'inconclusive', 'competing peaks or repetitive overlap'
    elif absent:
        status, reason = 'RESIDUAL', 'reference match remains in the old window'
    elif abs(offset) <= tol:
        status, reason = 'on cue', 'reference match within tolerance'
    else:
        status, reason = ('LATE' if offset > 0 else 'EARLY'), 'reference match outside tolerance'
    row.update(status=status, reason=reason)
    if status == 'inconclusive':
        row['next'] = f'Check the isolated effects stem and reference {refpath}; have a person listen at {t:.3f} s.'
    return row


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
    p.add_argument('--seed', type=int, default=0, help='random seed for the chance baseline')
    p.add_argument('--owner', help='page, picture or version whose identity the cue list describes')
    p.add_argument('--scale', choices=('contact', 'turn', 'all'), default='contact',
                   help='measure contact cues, turn cues, or both')
    p.add_argument('--offset', type=finite, default=0,
                   help='picture time = decoded audio time + this offset in seconds')
    p.add_argument('--reference', action='append', default=[], metavar='ID=FILE')
    p.add_argument('--expect-absent', action='store_true', help='check referenced cues for residual matches')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    a = p.parse_args()
    if a.chance < 0 or a.seed < 0:
        p.error('--chance and --seed cannot be negative')
    ffmpeg = find_tool('ffmpeg', a.ffmpeg)
    if not ffmpeg:
        print('ffmpeg is required (PATH, FFMPEG, or --ffmpeg)', file=sys.stderr)
        return 2
    # Every reader goes through cue_list: a stale list or an unbound plan is refused, a v1 list is read as it always
    # was (with its look printed), and a v2 rational fps arrives as a float.
    try:
        listed = cue_list.load_for('cue_onsets.py', a.cues, owner=a.owner)
    except (cue_list.CueListError, OSError) as e:
        print(f'cue_onsets.py: {e}', file=sys.stderr)
        return 2
    spec = listed.doc
    if listed.version == 'v2':
        spec = dict(spec, fps=listed.fps) if listed.fps is not None else {k: v for k, v in spec.items() if k != 'fps'}
    events, fps, problems = validate(spec)
    if problems:
        print(f'cue_onsets.py: {a.cues} cannot be checked as written:', file=sys.stderr)
        for problem in problems:
            print(f'  {problem}', file=sys.stderr)
        return 2
    legacy = listed.version == 'v1'
    if legacy:
        events = [dict(event, scale=listed.scale(event)) for event in events]
    selected = {'contact', 'turn'} if a.scale == 'all' else {a.scale}
    events = [ev for ev in events if
              (ev.get('scale', 'contact') in selected and ev.get('sound') != 'silent') or
              (legacy and ev.get('sound') == 'silent' and a.scale in ('contact', 'all'))]
    refs = {}
    for item in a.reference:
        if '=' not in item or not all(item.split('=', 1)):
            p.error('--reference needs ID=FILE')
        key, path = item.split('=', 1)
        refs[key] = path
    ids = {str(ev.get('id')) for ev in events}
    if set(refs) - ids:
        p.error('--reference names an unknown cue')
    for ev in events:
        if ev.get('sound') == 'absent' and not (str(ev.get('id')) in refs or ev.get('ref')):
            p.error('absence checks require a reference for every cue')
    ref_inputs = list(refs.values())
    for ev in events:
        if ev.get('ref'):
            path = ev['ref']
            directory = os.path.dirname(os.path.abspath(a.cues))
            ref_inputs.append(path if os.path.isabs(path) else os.path.join(directory, path))
    try:
        project.refuse_overwriting_inputs([a.json], [a.audio, a.cues, a.ffmpeg, *ref_inputs])
    except ValueError as error:
        print('cue_onsets.py: ' + str(error), file=sys.stderr)
        return 2
    events = [ev for ev in events if ev.get('enabled', True) or ev.get('sound') == 'silent']
    command = [ffmpeg, '-v', 'error', '-nostdin', '-i', a.audio, '-map', '0:a:0', '-ac', '2', '-ar', str(RATE)]
    command += ['-af', 'aresample=async=1:first_pts=0']
    r = subprocess.run(command + ['-f', 'f32le', '-'], capture_output=True, check=False)
    if r.returncode:
        print('could not decode audio: ' + r.stderr.decode(errors='replace').strip()[-200:], file=sys.stderr)
        return 2
    decoded = np.frombuffer(r.stdout, np.float32)
    if len(decoded) % 2:
        print('decoded audio has an incomplete stereo sample', file=sys.stderr)
        return 2
    channels = decoded.astype(np.float64).reshape(-1, 2)
    x = np.mean(channels, axis=1)
    sig = Signal(channels, a.rise_db, a.floor_db)
    duration = len(x) / RATE
    notes = lint(events, fps, duration, a.stack_ms, a.offset)

    not_checked = []
    rows = []
    for ev in events:
        if a.expect_absent and not (str(ev.get('id')) in refs or ev.get('ref')):
            not_checked.append(ev.get('id'))
            continue
        picture_t = cue_time(ev, fps)
        t = audio_time(ev, fps, a.offset)
        kind, sync = ev.get('sound', 'required'), ev.get('sync', 'attack')
        tol = float(ev.get('tolerance_ms', a.tolerance_ms))
        win = listed.onset_window_ms(ev, a.window_ms)
        k0, lo, hi = sig.window(t, win)
        row = {'id': ev.get('id'), 't': round(t, 4), 'scale': ev.get('scale', 'contact'),
               'sound': kind, 'sync': sync, 'window_ms': win}
        if ev.get('scale') == 'turn' or a.offset:
            row.update(picture_t=picture_t, lead_ms=ev.get('lead_ms', 0))
        if a.offset:
            row['audio_to_picture_offset_s'] = a.offset
        if hi <= lo:
            row['status'] = 'outside audio'
            rows.append(row)
            continue
        refpath = refs.get(str(ev.get('id'))) or ev.get('ref')
        if refpath:
            if str(ev.get('id')) not in refs and not os.path.isabs(refpath):
                refpath = os.path.join(os.path.dirname(os.path.abspath(a.cues)), refpath)
            rr = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', refpath, '-map', '0:a:0',
                                 '-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-'], capture_output=True)
            if rr.returncode:
                print('could not decode reference: ' + refpath, file=sys.stderr)
                return 2
            left, right = max(0, int((t - win / 1000) * RATE)), min(len(x), int((t + win / 1000) * RATE))
            channel_power = float(np.mean(channels[left:right] ** 2)) if right > left else 0.0
            mono_power = float(np.mean(x[left:right] ** 2)) if right > left else 0.0
            if channel_power > 1e-16 and mono_power < .01 * channel_power:
                row.update(reference=refpath, correlation=None, status='inconclusive',
                           reason='stereo channels cancel in the mono reference comparison',
                           next='Compare an isolated stem or listen to the stereo channels.')
                rows.append(row)
                continue
            try:
                row.update(reference_match(x, np.frombuffer(rr.stdout, np.float32).astype(np.float64),
                                           t, sync, win, tol, a.expect_absent or kind == 'absent', refpath))
            except ValueError as exc:
                print(f'cue_onsets.py: {ev.get("id")}: {exc}', file=sys.stderr)
                return 2
            if (ev.get('scale') == 'turn' and 'onset_s' in row and
                    row['status'] in ('on cue', 'LATE', 'EARLY', 'RESIDUAL')):
                row['picture_offset_ms'] = picture_offset_ms(row, picture_t, a.offset)
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
        found, k, strength = (sig.end(lo, hi) if sync == 'end' else
                              sig.apex(lo, hi) if sync == 'apex' else sig.attack(lo, hi))
        offset = k - k0  # milliseconds, because HOP is 1 ms
        row.update(onset_s=round((k + LAG) / 1000, 4), offset_ms=offset, strength_db=round(strength, 1),
                   level_db=round(float(sig.env[k]), 1), tolerance_ms=tol)
        if not found:
            row['status'] = 'missing' if kind == 'required' else 'none found'
        elif abs(offset) <= tol:
            row['status'] = 'on cue'
        else:
            row['status'] = 'LATE' if offset > 0 else 'EARLY'
        if found and ev.get('scale') == 'turn':
            row['picture_offset_ms'] = picture_offset_ms(row, picture_t, a.offset)
        if found and sync == 'attack' and strength < a.rise_db + 3:
            row['confidence'] = 'weak'
        rows.append(row)

    measured = [r['offset_ms'] for r in rows if r.get('status') in ('on cue', 'LATE', 'EARLY')]
    scored = [r for r in rows if r['sound'] == 'required' and r['sync'] == 'attack'
              and 'offset_ms' in r and 'reference' not in r]
    hit_rate = sum(1 for r in scored if r['status'] == 'on cue') / len(scored) if scored else None
    summary = {'cues': len(rows), 'measured': len(measured),
               'median_offset_ms': float(np.median(measured)) if measured else None,
               'spread_ms': (max(measured) - min(measured)) if measured else None,
               'hit_rate': round(hit_rate, 3) if hit_rate is not None else None,
               'failures': sum(1 for r in rows if r.get('status') in ('missing', 'LATE', 'EARLY', 'UNEXPECTED SOUND',
                                                                     'outside audio', 'RESIDUAL', 'inconclusive')
                               and r['sound'] != 'optional')}
    too_short = any(duration <= 2 * (row['window_ms'] / 1000 + .01) for row in scored)
    if a.chance and scored and too_short:
        summary['chance'] = {'sets': 0, 'seed': a.seed, 'mean_hit_rate': None, 'p95_hit_rate': None,
                             'verdict': 'not run: audio is too short for full random search windows'}
    elif a.chance and scored:
        rng = np.random.default_rng(a.seed)
        rates = []
        for _ in range(a.chance):
            hits = 0
            for row in scored:
                margin = row['window_ms'] / 1000 + 0.01
                t = float(rng.uniform(margin, duration - margin))
                k0, lo, hi = sig.window(t, row['window_ms'])
                if hi >= lo:
                    found, k, _ = sig.attack(lo, hi)
                    hits += found and abs(k - k0) <= row['tolerance_ms']
            rates.append(hits / len(scored))
        p95 = float(np.percentile(rates, 95))
        summary['chance'] = {'sets': a.chance, 'mean_hit_rate': round(float(np.mean(rates)), 3),
                             'p95_hit_rate': round(p95, 3),
                             'seed': a.seed, 'spread': [round(float(np.min(rates)), 3),
                                                       round(float(np.max(rates)), 3)],
                             'verdict': ('above chance' if hit_rate > p95 else
                                         'inconclusive: no better than random cue times in this audio')}
    if 'chance' in summary and summary['chance']['verdict'].startswith('inconclusive'):
        for row in scored:
            if 'reference' not in row:
                row['status'] = 'inconclusive'
                row['reason'] = 'hit rate no better than chance'
                row['next'] = f'Check the isolated effects stem or reference; have a person listen at {row["t"]:.3f} s.'
        failures = ('missing', 'LATE', 'EARLY', 'UNEXPECTED SOUND', 'outside audio', 'RESIDUAL', 'inconclusive')
        summary['failures'] = sum(1 for r in rows if r.get('status') in failures and r['sound'] != 'optional')
    out = {'audio': a.audio, 'cues': a.cues, 'lint': notes, 'summary': summary, 'rows': rows,
           'not_checked': not_checked,
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
        if 'offset_ms' in row and 'strength_db' in row:
            detail = (f"offset {row['offset_ms']:+d} ms (tol {row['tolerance_ms']:g}), "
                      f"strength {row['strength_db']} dB")
        elif 'offset_ms' in row:
            second = row['second_best']
            margin = row['margin']
            detail = (f"offset {row['offset_ms']:+g} ms (tol {row['tolerance_ms']:g}), "
                      f"correlation {row['correlation']:.4f}, "
                      f"second {f'{second:.4f}' if second is not None else 'none'}, "
                      f"margin {f'{margin:.4f}' if margin is not None else 'none'}, "
                      f"level {row['level_db']:.1f} dBFS")
        elif 'onset_s' in row:
            detail = f"onset at {row['onset_s']} s, rise {row['rise_db']} dB"
        else:
            detail = ''
        if 'picture_offset_ms' in row:
            detail += f", picture offset {row['picture_offset_ms']:+g} ms"
        print(f"  {str(row['id']):20s} {row['t']:8.3f} s  {row['sound']:8s} {row.get('status', ''):18s} {detail}"
              + ('  (weak)' if row.get('confidence') == 'weak' else '')
              + ('  ' + row['reason'] if row.get('reason') else '')
              + ('  next: ' + row['next'] if row.get('next') else ''))
    return 1 if summary['failures'] else 0


if __name__ == '__main__':
    sys.exit(main())
