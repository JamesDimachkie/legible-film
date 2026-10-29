#!/usr/bin/env python3
"""Place a cue list's takes by their own sync points and report the resulting mix.

  python mix_cues.py cues.json palette.json --out-dir stems --duration 24
  python mix_cues.py cues.json palette.json --out-dir stems --gain-to-lufs -18

Takes rotate per role unless variant is given (zero-based take index). Paths in
the palette are relative to that palette. Event sync overrides the role's sync;
when they differ or points_s is absent, the take's requested point is measured.
Silent window_ms spans that far either side of t, clamped to the output. A
silent cue means no new sound: an audible take starting inside fails; an earlier
take ringing into the window is informational, with peak and RMS in dBFS.
Audible means above -60 dBFS per sample. Tail RMS includes the whole clamped
window, including its quiet samples; levels include any final linear gain. Presence
uses the isolated effect versus the ducked music over 150 ms after its sync.
Bands are broad FFT power bands; they locate masking candidates, not audibility.
No gain normalisation by default. --gain-to-lufs applies one linear gain to all
stems only if the measured true peak would remain <= -1 dBTP. No limiter on that legacy path.

Version 2 supports non-recursive role/event layers, a looping bed, and --master
none|social|web|broadcast (palette master.preset is used unless overridden).
Absent a preset, no mastering is applied, including for version 1 palettes.
Master targets are -14/-16/-23 LUFS: plain gain followed by a 5 ms look-ahead
safety limiter (-1.5 dBTP, 100 ms release), using 4x windowed-sinc true-peak
estimates. More than 4 dB reduction is refused: rebalance the mix. The written
mix is checked after AAC 128k; > -1 dBTP fails. Stems share the same gain
envelope and reconstruct the mix. Disabled spotted events are withheld.
Writes stereo 24-bit effects.wav, music.wav, bed.wav, mix.wav and mix-report.json. Needs
numpy and FFmpeg. Exit 0 required cues placed and no new takes in silent windows; 1 missing
required events, broken silence, clipping or refused gain; 2 could not run.
Measurements do not decide what sounds right. Every output is unheard.
"""
import argparse
import importlib.util
import math
import sys
import tempfile
from pathlib import Path
import numpy as np

_spec = importlib.util.spec_from_file_location('sound_io', Path(__file__).with_name('sound_io.py'))
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)


def numeric(obj, key, default=0, minimum=None):
    v = obj.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f'{key} must be a finite number')
    if minimum is not None and v < minimum:
        raise ValueError(f'{key} must be >= {minimum}')
    return float(v)


def sync_point(x, kind, rate):
    mono = x.mean(axis=1).astype(np.float64)
    if kind == 'attack':
        hits = np.flatnonzero(np.max(np.abs(x), axis=1) > max(.001, np.max(np.abs(x)) * .01))
        return float(hits[0] / rate) if len(hits) else 0
    if kind == 'end':
        hits = np.flatnonzero(np.max(np.abs(x), axis=1) > .001)
        return float((hits[-1] + 1) / rate) if len(hits) else len(x) / rate
    width = min(len(mono), max(1, round(.005 * rate)))
    cs = np.concatenate(([0.], np.cumsum(mono ** 2)))
    hop = max(1, round(.001 * rate))
    return (int(np.argmax((cs[width:] - cs[:-width])[::hop])) * hop + width) / rate


def duck_envelope(length, rate, dips):
    """Merge smooth cosine dips by maximum attenuation, never step gain."""
    dbs = np.zeros(length, np.float32)
    for sync, end, amount in dips:
        # Ramp 30 ms before sync, hold through body, recover over 250 ms.
        a, b = max(0, round((sync - .030) * rate)), max(0, round(sync * rate))
        c, d = max(b, round(end * rate)), round((end + .250) * rate)
        a, b, c, d = [min(length, v) for v in (a, b, c, d)]
        if b > a:
            u = np.linspace(0, 1, b - a, endpoint=False)
            dbs[a:b] = np.maximum(dbs[a:b], amount * .5 * (1 - np.cos(np.pi * u)))
        dbs[b:c] = np.maximum(dbs[b:c], amount)
        if d > c:
            u = np.linspace(0, 1, d - c, endpoint=True)
            dbs[c:d] = np.maximum(dbs[c:d], amount * .5 * (1 + np.cos(np.pi * u)))
    return np.power(10., -dbs / 20).astype(np.float32)


def band_powers(x, rate):
    bands = ((20, 150), (150, 500), (500, 2000), (2000, 6500), (6500, rate / 2))
    if not len(x):
        return np.zeros(len(bands)), bands
    # Sum channel power; antiphase stereo must not disappear in this diagnostic.
    power = np.sum(np.abs(np.fft.rfft(x.astype(np.float64) * np.hanning(len(x))[:, None], axis=0)) ** 2, axis=1)
    f = np.fft.rfftfreq(len(x), 1 / rate)
    return np.array([power[(f >= lo) & (f < hi)].sum() for lo, hi in bands]), bands



def loop_bed(ffmpeg, palette, root, duration, rate):
    """Overlap-add a loop with equal-power seams; preserve the film's sample count."""
    length = round(duration * rate)
    out = np.zeros((length, 2), np.float32)
    bs = palette.get('bed')
    if bs is None:
        return out, {'enabled': False}
    if not isinstance(bs, dict) or bs.get('role') not in palette['roles']:
        raise ValueError('bed needs a role present in the palette')
    rs = palette['roles'][bs['role']]
    if not isinstance(rs, dict) or rs.get('loop') is not True or not rs.get('takes'):
        raise ValueError('bed role needs loop: true and at least one take')
    start = numeric(bs, 'from_s', 0, 0)
    stop = duration if bs.get('to_s') is None else numeric(bs, 'to_s', minimum=0)
    if not start < stop <= duration or start >= duration:
        raise ValueError('bed must satisfy 0 <= from_s < to_s <= film duration')
    x = io.decode(ffmpeg, root / rs['takes'][0], rate)
    cross = round(numeric(rs, 'crossfade_ms', 400, 0) * rate / 1000)
    if cross < 2 or cross * 2 > len(x):
        raise ValueError('bed crossfade must be >= 2 samples and <= half the take')
    x *= 10 ** ((numeric(rs, 'gain_db') + numeric(bs, 'gain_db')) / 20)
    a, b = round(start * rate), round(stop * rate)
    bed = np.zeros((b - a, 2), np.float32)
    step, joins = len(x) - cross, []
    u = np.linspace(0, np.pi / 2, cross)
    # The first take begins unfaded; subsequent takes fade in while the previous
    # one fades out. Only fades needed by a real successor are applied.
    for pos in range(0, len(bed), step):
        take = x.copy()
        if pos:
            take[:cross] *= np.sin(u)[:, None]
            joins.append((a + pos) / rate)
        if pos + step < len(bed):
            take[-cross:] *= np.cos(u)[:, None]
        n = min(len(take), len(bed) - pos)
        bed[pos:pos + n] += take[:n]
    for key, reverse, default in (('fade_in_ms', False, 300), ('fade_out_ms', True, 600)):
        n = min(len(bed), round(numeric(bs, key, default, 0) * rate / 1000))
        if n:
            env = np.sin(np.linspace(0, np.pi / 2, n)) ** 2
            if reverse:
                bed[-n:] *= env[::-1, None]
            else:
                bed[:n] *= env[:, None]
    out[a:b] = bed
    return out, {'enabled': True, 'role': bs['role'], 'from_s': start, 'to_s': stop,
                 'crossfade_ms': cross / rate * 1000, 'loop_starts_s': joins,
                 'take': str(root / rs['takes'][0])}


def true_peak_estimates(x):
    """Per-sample maximum over 4 sinc-interpolated phases, linked across channels.

    65-tap Hann-windowed sinc, normalised at DC; zero padding at file edges.
    No FFT periodic boundary and no scipy dependency. Final FFmpeg/AAC metering
    is independent of this safety estimate.
    """
    peaks = np.max(np.abs(x), axis=1).astype(np.float64)
    k = np.arange(-32, 33, dtype=np.float64)
    for phase in (.25, .5, .75):
        h = np.sinc(k + phase) * (.5 + .5 * np.cos(np.pi * (k + phase) / 33))
        h /= h.sum()
        for channel in range(x.shape[1]):
            y = np.convolve(np.pad(x[:, channel], (32, 32)), h, mode='valid')
            np.maximum(peaks, np.abs(y), out=peaks)
    return peaks


def safety_limiter(x, rate):
    """Linked gain: 1 ms controls, 5 ms anticipatory ramp, 100 ms release."""
    hop = max(1, round(rate * .001))
    peaks = true_peak_estimates(x)
    count = (len(x) + hop - 1) // hop
    blocks = np.pad(peaks, (0, count * hop - len(x))).reshape(count, hop).max(axis=1)
    required = np.minimum(0., 20 * np.log10(10 ** (-1.5 / 20) / np.maximum(blocks, 1e-12)))
    # Include both neighbouring blocks so interpolation can never release above
    # either block's requirement. Anticipate each reduction over five controls.
    controls = np.minimum(required, np.r_[required[1:], required[-1]])
    for shift in range(1, 6):
        controls[:-shift] = np.minimum(controls[:-shift], required[shift:] * (1 - shift / 6))
    release = math.exp(-hop / (rate * .100))
    for i in range(1, count):
        controls[i] = min(controls[i], controls[i - 1] * release)
    envelope = 10 ** (np.interp(np.arange(len(x)), np.arange(count) * hop, controls) / 20)
    # Re-estimate after modulation. This small static safety correction also
    # covers interpolation-filter ringing caused by the changing envelope.
    peak = float(true_peak_estimates(x * envelope[:, None]).max())
    correction = min(1., 10 ** (-1.5 / 20) / max(peak, 1e-12))
    envelope *= correction
    return envelope.astype(np.float32), float(-20 * np.log10(max(float(envelope.min()), 1e-12)))


def mix(a):
    ffmpeg = io.find_tool('ffmpeg', a.ffmpeg)
    if not ffmpeg:
        raise ValueError('FFmpeg is required (PATH, FFMPEG, or --ffmpeg)')
    if a.rate < 8000 or a.rate > 192000:
        raise ValueError('rate must be 8000..192000')
    spec = __import__('json').loads(Path(a.cues).read_text(encoding='utf-8'))
    palette = __import__('json').loads(Path(a.palette).read_text(encoding='utf-8'))
    if not isinstance(palette, dict):
        raise ValueError('palette must be an object')
    events = spec.get('events') if isinstance(spec, dict) else spec
    if not isinstance(events, list):
        raise ValueError('cues must contain an events list')
    roles = palette.get('roles', {})
    if not isinstance(roles, dict):
        raise ValueError('palette roles must be an object')
    version = palette.get('version', 1)
    if isinstance(version, bool) or version not in (1, 2):
        raise ValueError('palette version must be 1 or 2')
    master_spec = palette.get('master', {}) if version == 2 else {}
    if not isinstance(master_spec, dict):
        raise ValueError('palette master must be an object')
    preset = a.master if a.master is not None else master_spec.get('preset', 'none')
    if preset not in ('none', 'social', 'web', 'broadcast'):
        raise ValueError('unknown master preset')
    if preset != 'none' and a.gain_to_lufs is not None:
        raise ValueError('--gain-to-lufs and mastering cannot be combined')
    root = Path(a.palette).resolve().parent
    placed, missing, silence, dips, warnings = [], [], [], [], []
    cache, rotation, timed = {}, {}, []
    expanded = []
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise ValueError(f'event {i} is not an object')
        if not isinstance(ev.get('enabled', True), bool):
            raise ValueError('event enabled must be boolean')
        if not ev.get('enabled', True) and ev.get('sound') != 'silent':
            continue
        expanded.append((i, ev))
        if version != 2 or ev.get('sound') == 'silent':
            continue
        rs = roles.get(ev.get('role'), {})
        if not isinstance(rs, dict):
            raise ValueError('role must be an object')
        if not isinstance(rs.get('layers', []), list) or not isinstance(ev.get('layers', []), list):
            raise ValueError('layers must be a list')
        layers = rs.get('layers', []) + ev.get('layers', [])
        for k, layer in enumerate(layers):
            if not isinstance(layer, dict) or not isinstance(layer.get('role'), str):
                raise ValueError('each layer needs a role')
            child = {key: ev[key] for key in ('t', 'frame', 'sound') if key in ev}
            child.update(id=ev.get('id', i), role=layer['role'],
                         gain_db=numeric(ev, 'gain_db') + numeric(layer, 'gain_db'),
                         _layer=k, _parent=ev.get('id', i))
            if 'variant' in layer:
                child['variant'] = layer['variant']
            expanded.append((i, child))
    for i, ev in expanded:
        if not isinstance(ev, dict):
            raise ValueError(f'event {i} is not an object')
        if 't' in ev:
            t = numeric(ev, 't', minimum=0)
        elif 'frame' in ev and isinstance(spec, dict):
            fps = numeric(spec, 'fps', minimum=.001)
            t = numeric(ev, 'frame', minimum=0) / fps
        else:
            raise ValueError(f'event {i} needs t or frame and fps')
        kind = ev.get('sound', 'required')
        if kind not in ('required', 'optional', 'silent'):
            raise ValueError(f'event {i} has an unknown sound kind')
        timed.append((t, ev))
        if kind == 'silent':
            silence.append((t, ev, numeric(ev, 'window_ms', 120, .001) / 1000))
            continue
        role = ev.get('role')
        row = {'id': ev.get('id', i), 'role': role, 't': t, 'sound': kind}
        if '_layer' in ev:
            row.update(parent_id=ev['_parent'], layer_index=ev['_layer'])
        if not isinstance(role, str) or role not in roles:
            missing.append(dict(row, reason='role missing from palette'))
            continue
        rs = roles[role]
        if not isinstance(rs, dict):
            raise ValueError(f'palette role {role} must be an object')
        takes = rs.get('takes', [])
        if not isinstance(takes, list) or not takes:
            missing.append(dict(row, reason='role has no takes'))
            continue
        explicit = ev.get('variant')
        if explicit is not None and (isinstance(explicit, bool) or not isinstance(explicit, int) or not 0 <= explicit < len(takes)):
            raise ValueError(f"event {row['id']} variant must be a zero-based take index")
        first = explicit if explicit is not None else rotation.get(role, 0) % len(takes)
        indices = [first] if explicit is not None else [(first + k) % len(takes) for k in range(len(takes))]
        x, errors = None, []
        for index in indices:
            try:
                path = root / takes[index]
                if path not in cache:
                    cache[path] = io.decode(ffmpeg, path, a.rate)
                x = cache[path]
                break
            except (OSError, ValueError, TypeError) as exc:
                errors.append(str(exc))
        if x is None:
            missing.append(dict(row, reason='no readable take', errors=errors))
            continue
        if explicit is None:
            rotation[role] = index + 1
        sync = ev.get('sync', rs.get('sync', 'attack'))
        if sync not in ('attack', 'apex', 'end'):
            raise ValueError(f"event {row['id']} has unknown sync")
        points = rs.get('points_s', [])
        if sync == rs.get('sync', 'attack') and isinstance(points, list) and len(points) > index:
            point = numeric({'point': points[index]}, 'point', minimum=0)
            if point > len(x) / a.rate:
                raise ValueError('sync point lies beyond the take')
            point_source = 'manifest'
        else:
            point, point_source = sync_point(x, sync, a.rate), 'measured'
        gain = numeric(rs, 'gain_db') + numeric(ev, 'gain_db')
        audio = x * 10 ** (gain / 20)
        start = round((t - point) * a.rate)
        row.update(variant=index, file=str(path), sync=sync, point_s=point, point_source=point_source,
                   start_s=start / a.rate, gain_db=gain, duration_s=len(x) / a.rate,
                   placed_sync_s=(start + round(point * a.rate)) / a.rate)
        if errors:
            warnings.append({'id': row['id'], 'unreadable_rotated_takes': errors})
        placed.append((row, audio, start))
        amount = numeric(ev, 'duck_db', a.duck_default_db, minimum=0)
        if amount:
            dip_start = min(t, start / a.rate) if sync == 'end' else t
            dips.append((dip_start, max(t + .050, (start + len(x)) / a.rate), amount))
    longest = max((len(x) / a.rate for _, x, _ in placed), default=0)
    duration = a.duration if a.duration is not None else (spec.get('duration') if isinstance(spec, dict) else None)
    if duration is None:
        duration = max((t for t, _ in timed), default=0) + longest
    duration = numeric({'duration': duration}, 'duration', minimum=1 / a.rate)
    length = round(duration * a.rate)
    effects = np.zeros((length, 2), np.float32)
    audible_ranges = []
    for row, x, start in placed:
        lo, hi = max(0, start), min(length, start + len(x))
        row['trimmed_head_s'] = max(0, -start) / a.rate
        row['trimmed_tail_s'] = max(0, start + len(x) - length) / a.rate
        row['sync_in_output'] = 0 <= row['t'] < duration or (row['sync'] == 'end' and row['t'] == duration)
        if hi > lo:
            effects[lo:hi] += x[lo - start:hi - start]
        hits = np.flatnonzero(np.max(np.abs(x), axis=1) > .001)
        audible_ranges.append((start + int(hits[0]), start + int(hits[-1]) + 1) if len(hits) else (0, 0))
    silent_violations = []
    silent_tails = []
    silent_outside = []
    for t, ev, half in silence:
        if t + half <= 0 or t - half >= duration:
            silent_outside.append(ev.get('id'))
        a0 = min(length, max(0, round((t - half) * a.rate)))
        b0 = min(length, max(0, round((t + half) * a.rate)))
        for (row, x, start), (a1, b1) in zip(placed, audible_ranges):
            lo, hi = max(a0, a1, start), min(b0, b1, start + len(x))
            if hi > lo and np.max(np.abs(x[lo - start:hi - start])) > .001:
                detail = {'silent_id': ev.get('id'), 'take_event_id': row['id'],
                          'overlap_s': [lo / a.rate, hi / a.rate]}
                if 'layer_index' in row:
                    detail['layer_index'] = row['layer_index']
                if a0 <= start < b0:
                    silent_violations.append(detail)
                else:
                    segment = x[max(a0, start) - start:min(b0, start + len(x)) - start]
                    rms = np.sqrt(np.sum(segment.astype(np.float64) ** 2) / ((b0 - a0) * x.shape[1]))
                    detail.update(window_s=[a0 / a.rate, b0 / a.rate],
                                  peak_dbfs=io.db(np.max(np.abs(segment))), rms_dbfs=io.db(rms))
                    silent_tails.append(detail)
    music = np.zeros_like(effects)
    ms = palette.get('music', {})
    if ms is None:
        ms = {}
    if not isinstance(ms, dict):
        raise ValueError('palette music must be an object')
    music_file = a.music or ms.get('file')
    if music_file and not a.no_music:
        path = Path(a.music).resolve() if a.music else root / music_file
        offset, at = numeric(ms, 'offset_s', minimum=0), numeric(ms, 'at_s', minimum=0)
        stop = numeric(ms, 'stop_s', duration, minimum=0)
        stop = min(duration, stop)
        if stop <= at:
            raise ValueError('music stop_s must be after at_s')
        x = io.decode(ffmpeg, path, a.rate, 2, offset, stop - at)
        lo = round(at * a.rate)
        count = min(len(x), length - lo, round(stop * a.rate) - lo)
        x = x[:count] * 10 ** (numeric(ms, 'gain_db') / 20)
        ni = min(count, round(numeric(ms, 'fade_in_ms', 10, minimum=0) * a.rate / 1000))
        no = min(count, round(numeric(ms, 'fade_out_ms', 20, minimum=0) * a.rate / 1000))
        if ni:
            x[:ni] *= np.linspace(0, 1, ni)[:, None]
        if no:
            x[-no:] *= np.linspace(1, 0, no)[:, None]
        music[lo:lo + count] = x
    bed, bed_report = loop_bed(ffmpeg, palette, root, duration, a.rate) if version == 2 else (
        np.zeros_like(effects), {'enabled': False})
    duck = duck_envelope(length, a.rate, dips)
    music *= duck[:, None]
    presence, listening = [], []
    for row, audio, start in placed:
        lo, hi = max(0, round(row['t'] * a.rate)), min(length, round((row['t'] + .15) * a.rate))
        if hi <= lo:
            continue
        isolated = np.zeros((hi - lo, 2), np.float32)
        a0, b0 = max(lo, start), min(hi, start + len(audio))
        if b0 > a0:
            isolated[a0 - lo:b0 - lo] = audio[a0 - start:b0 - start]
        ep, bands = band_powers(isolated, a.rate)
        mp, _ = band_powers(music[lo:hi], a.rate)
        band = int(np.argmax(ep))
        effect_db, music_db = io.level(isolated), io.level(music[lo:hi])
        has_body = float(np.max(np.abs(isolated))) > .001
        ratio = 10 * math.log10(max(ep[band], 1e-24) / max(mp[band], 1e-24))
        pr = {'id': row['id'], 'window_s': [lo / a.rate, hi / a.rate], 'effect_dbfs_rms': effect_db,
              'music_dbfs_rms': music_db, 'overall_difference_db': effect_db - music_db,
              'strongest_band_hz': bands[band], 'band_difference_db': ratio,
              'post_sync_body': has_body, 'listening_check': has_body and (effect_db < music_db or ratio < 0)}
        if not has_body:
            pr['note'] = 'no post-sync body (expected for end-sync); presence inconclusive in this window'
        presence.append(pr)
        if pr['listening_check']:
            listening.append(row['id'])
    mix_audio = effects + music + bed
    before = io.meter(ffmpeg, mix_audio, a.rate)
    applied_gain, refused = 0., None
    mastering = {'preset': preset, 'max_gain_reduction_db': 0., 'refused': None}
    if a.gain_to_lufs is not None:
        if before['integrated_lufs'] is None or before['true_peak_dbtp'] is None or np.max(np.abs(mix_audio)) < 1e-10:
            refused = 'cannot normalise silence or unmeasurable audio'
        else:
            requested = a.gain_to_lufs - before['integrated_lufs']
            if before['true_peak_dbtp'] + requested > -1:
                refused = f'linear gain {requested:.3f} dB would exceed -1 dBTP'
            else:
                applied_gain = requested
                gain = 10 ** (applied_gain / 20)
                effects *= gain; music *= gain; bed *= gain; mix_audio *= gain
    if preset != 'none':
        target = {'social': -14., 'web': -16., 'broadcast': -23.}[preset]
        mastering['target_lufs'] = target
        if before['integrated_lufs'] is None or np.max(np.abs(mix_audio)) < 1e-10:
            refused = 'cannot master silence or unmeasurable audio; rebalance the mix'
        else:
            requested = target - before['integrated_lufs']
            candidate = mix_audio * 10 ** (requested / 20)
            envelope, reduction = safety_limiter(candidate, a.rate)
            mastering.update(max_gain_reduction_db=reduction, ceiling_dbtp=-1.5,
                             lookahead_ms=5, release_ms=100, oversample=4)
            if reduction > 4. + 1e-6:
                refused = f'{reduction:.3f} dB limiting exceeds 4 dB; rebalance the mix before mastering'
            else:
                applied_gain = requested
                shared = envelope[:, None] * 10 ** (requested / 20)
                effects *= shared; music *= shared; bed *= shared
                mix_audio = effects + music + bed
        mastering['refused'] = refused
    for tail in silent_tails:
        # Recompute from the isolated take through the same master envelope;
        # adding plain gain alone would overstate a tail under the limiter.
        a0, b0 = [round(t * a.rate) for t in tail['window_s']]
        for row, audio, start in placed:
            if row['id'] == tail['take_event_id'] and row.get('layer_index') == tail.get('layer_index'):
                lo, hi = max(a0, start), min(b0, start + len(audio))
                segment = audio[lo - start:hi - start] * 10 ** (applied_gain / 20)
                if preset != 'none' and mastering['refused'] is None:
                    segment = segment * envelope[lo:hi, None]
                tail['peak_dbfs'] = io.db(np.max(np.abs(segment)))
                tail['rms_dbfs'] = io.db(np.sqrt(np.sum(segment.astype(np.float64) ** 2) / ((b0 - a0) * 2)))
                break
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, x in (('effects', effects), ('music', music), ('bed', bed), ('mix', mix_audio)):
        io.write_wav(ffmpeg, out / (name + '.wav'), x, a.rate)
    measured = io.meter(ffmpeg, out / 'mix.wav')
    if preset != 'none' and not refused:
        with tempfile.TemporaryDirectory(prefix='lf-master-', dir=str(out)) as tmp:
            encoded = Path(tmp) / 'reencode.m4a'
            io.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(out / 'mix.wav'),
                    '-map', '0:a:0', '-c:a', 'aac', '-b:a', '128k', str(encoded)])
            lossy = io.meter(ffmpeg, encoded)
        mastering['aac_128k'] = lossy
        mastering['aac_pass'] = lossy['true_peak_dbtp'] is not None and lossy['true_peak_dbtp'] <= -1.
        mastering['target_error_lu'] = measured['integrated_lufs'] - mastering['target_lufs']
        if not mastering['aac_pass']:
            refused = 'AAC 128k true peak exceeds -1 dBTP; rebalance the mix and rebuild'
        elif abs(mastering['target_error_lu']) > .5:
            refused = 'limiting moved loudness more than 0.5 LU from target; rebalance the mix'
        mastering['refused'] = refused
    # A stem can clip even when cancelled by another stem in the mix.
    clipping = any(float(np.max(np.abs(x))) >= 1 for x in (effects, music, bed, mix_audio))
    if clipping:
        warnings.append('float sum or stem reaches 0 dBFS; 24-bit output may clip; lower gains and rebuild')
    sorted_events = sorted((r for r, _, _ in placed if 'parent_id' not in r), key=lambda r: r['t'])
    stacked = [{'ids': [r['id'], s['id']], 'distance_ms': (s['t'] - r['t']) * 1000}
               for i, r in enumerate(sorted_events) for s in sorted_events[i + 1:] if (s['t'] - r['t']) < .015]
    failed = [r['id'] for r, _, _ in placed if r['sound'] == 'required' and not r['sync_in_output']]
    bad = (any(r['sound'] == 'required' for r in missing) or bool(silent_violations) or bool(silent_outside)
           or bool(failed) or bool(refused) or clipping)
    event_rows = [r for r, _, _ in placed if 'parent_id' not in r]
    for row in event_rows:
        row['layers'] = [r for r, _, _ in placed if r.get('parent_id') == row['id']]
    report = {'mastering': mastering, 'bed': bed_report, 'rate': a.rate, 'duration_s': duration, 'events_placed': event_rows,
              'missing_roles': missing, 'required_sync_outside_output': failed, 'silent_window_violations': silent_violations,
              'stacked_events': stacked, 'presence': presence, 'listening_check_candidates': listening,
              'silent_windows_outside_output': silent_outside,
              'silent_window_tails': silent_tails,
              'mix': dict(measured, peak_dbfs=io.db(np.max(np.abs(mix_audio))),
                          decoded_peak_dbfs=io.db(np.max(np.abs(io.decode(ffmpeg, out / 'mix.wav', a.rate))))),
              'float_mix_before_gain': before, 'gain_applied_db': applied_gain, 'gain_refused': refused,
              'edges': {'first_sample_peak_dbfs': io.db(np.max(np.abs(mix_audio[0]))),
                        'head_5ms_peak_dbfs': io.db(np.max(np.abs(mix_audio[:max(1, round(.005 * a.rate))]))),
                        'tail_5ms_peak_dbfs': io.db(np.max(np.abs(mix_audio[-max(1, round(.005 * a.rate)):]))),
                        'last_sample_peak_dbfs': io.db(np.max(np.abs(mix_audio[-1]))),
                        'event_at_zero': any(r['t'] == 0 for r, _, _ in placed)},
              'ducking': {'dips': len(dips), 'minimum_gain': float(duck.min()),
                          'max_adjacent_gain_change': float(np.max(np.abs(np.diff(duck)))) if len(duck) > 1 else 0},
              'warnings': warnings, 'exit_code': 1 if bad else 0,
              'limit': 'Placement and measurements only; every unavailable role is disclosed. Unheard.'}
    io.save_json(out / 'mix-report.json', report)
    if a.json:
        io.save_json(a.json, report)
    print(f"Placed {len(placed)} events; missing {len(missing)}; silence violations {len(silent_violations)}; "
          f"tails in silent windows {len(silent_tails)} (information); "
          f"peak {report['mix']['peak_dbfs']:.2f} dBFS, true peak {measured['true_peak_dbtp']} dBTP, "
          f"{measured['integrated_lufs']} LUFS. Unheard.")
    if refused:
        print('  refused: ' + refused)
    return report['exit_code']


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('cues'); p.add_argument('palette')
    p.add_argument('--duration', type=io.positive)
    p.add_argument('--out-dir', required=True)
    p.add_argument('--no-music', action='store_true')
    p.add_argument('--music')
    p.add_argument('--rate', type=int, default=48000)
    p.add_argument('--duck-default-db', type=io.finite, default=0)
    p.add_argument('--gain-to-lufs', type=io.finite)
    p.add_argument('--master', choices=('none', 'social', 'web', 'broadcast'))
    p.add_argument('--json'); p.add_argument('--ffmpeg')
    a = p.parse_args()
    try:
        if a.duck_default_db < 0:
            raise ValueError('duck-default-db must be >= 0')
        return mix(a)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, UnicodeError) as exc:
        print('mix_cues.py: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
