#!/usr/bin/env python3
"""Conform a music take to section bounds and record the input and output hashes.

Without --cues the map must give a and b for each section and is unbound.
Measurements are screens, not listening decisions. The output is unheard.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path

try:
    import numpy as np
except ImportError as missing:
    import runpy
    sys.exit(runpy.run_path(str(Path(__file__).with_name('project.py')))['missing_package'](missing))


def sibling(name):
    spec = importlib.util.spec_from_file_location('lf_' + name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


io = sibling('sound_io')
project = sibling('project')
RATE = 48000


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(name + ' must be a finite number')
    return float(value)


def parse_tuple(value, count, name):
    try:
        parts = [float(x) for x in value.split(',')]
    except ValueError:
        raise ValueError(name + ' needs comma-separated numbers') from None
    if len(parts) not in count or not all(math.isfinite(x) for x in parts):
        raise ValueError(name + ' needs comma-separated finite numbers')
    return parts


def filter_audio(ffmpeg, audio, chain):
    data = io.run([ffmpeg, '-v', 'error', '-nostdin', '-f', 'f32le', '-ar', str(RATE), '-ac', '2',
                   '-i', '-', '-af', chain, '-f', 'f32le', '-'],
                  np.asarray(audio, dtype='<f4').tobytes()).stdout
    out = np.frombuffer(data, dtype='<f4').reshape(-1, 2).copy()
    if len(out) != len(audio) or not np.isfinite(out).all():
        raise ValueError('filter changed the audio length or produced invalid samples')
    return out


def hp4(hz):
    return ','.join(f'highpass=f={hz}:p=2:t=q:w={q}' for q in (.541196100146197, 1.306562964876377))


def resolve_sections(mapping, cues, cues_hash, tempo, snap, xfade):
    sections = mapping.get('sections')
    if not isinstance(sections, list) or not sections:
        raise ValueError('map needs sections')
    if cues is None:
        if mapping.get('cues_sha256') is not None:
            raise ValueError('unbound map must not carry a cue hash')
        bounds = None
    else:
        if mapping.get('cues_sha256') != cues_hash:
            raise ValueError('stale map: the cue list changed; rebuild the map')
        bounds = {s['id']: s for s in cues.get('sections', [])}
    if snap != 'none':
        if not isinstance(tempo, dict):
            raise ValueError('--snap requires a tempo report')
        step = tempo.get('bar_s') if snap == 'bar' else tempo.get('period_s')
        step = number(step, 'tempo step')
        if step <= 0:
            raise ValueError('tempo step must be positive')
        phase = number(tempo.get('offset_s'), 'tempo offset')
    result, pieces, ids = [], [], set()
    previous_end = 0.0
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get('id'), str) or section['id'] in ids:
            raise ValueError('map sections need distinct ids')
        sid = section['id']
        ids.add(sid)
        if bounds is not None:
            if sid not in bounds:
                raise ValueError('map section not found in cues: ' + sid)
            if 'a' in section or 'b' in section:
                raise ValueError('bound map must take section bounds from the cue list')
            bound = bounds[sid]
        else:
            bound = section
        a, b = number(bound.get('a'), 'section a'), number(bound.get('b'), 'section b')
        if a < previous_end - 1e-9 or b <= a:
            raise ValueError('section bounds must be ordered, non-overlapping and positive')
        previous_end = b
        gain = number(section.get('gain_db', 0), 'gain_db')
        cross = number(section.get('xfade_ms', xfade), 'xfade_ms')
        if cross < 0:
            raise ValueError('xfade_ms must be non-negative')
        edits = section.get('edits') or [{'at': 0, 'take_start': section.get('take_start')}]
        if not isinstance(edits, list) or not edits:
            raise ValueError('edits must be a nonempty list')
        resolved = []
        for edit in edits:
            if not isinstance(edit, dict):
                raise ValueError('each edit must be an object')
            at = number(edit.get('at'), 'edit at')
            take = number(edit.get('take_start'), 'edit take_start')
            if at < 0 or at >= b - a or take < 0 or (resolved and at <= resolved[-1][0]):
                raise ValueError('edits must be ordered within the section and take_start must be non-negative')
            if snap != 'none':
                take = max(0.0, phase + round((take - phase) / step) * step)
            resolved.append((at, take))
        if resolved[0][0] != 0:
            raise ValueError('the first edit must start at section offset 0')
        result.append({'id': sid, 'a': a, 'b': b, 'gain_db': gain, 'xfade_ms': cross})
        for index, (at, take) in enumerate(resolved):
            end = a + (resolved[index + 1][0] if index + 1 < len(resolved) else b - a)
            pieces.append({'a': a + at, 'b': end, 'take_start': take, 'gain_db': gain,
                           'xfade_ms': cross, 'section': sid})
    return result, pieces


def assemble(source, pieces, source_edge):
    length = round(max(p['b'] for p in pieces) * RATE)
    out = np.zeros((length, 2), np.float32)
    seams, held_samples = [], 0
    for i, piece in enumerate(pieces):
        prev = pieces[i - 1] if i else None
        following = pieces[i + 1] if i + 1 < len(pieces) else None
        left = round(piece['xfade_ms'] * RATE / 1000) if prev and abs(prev['b'] - piece['a']) < 1e-9 else 0
        right = round(following['xfade_ms'] * RATE / 1000) if following and abs(following['a'] - piece['b']) < 1e-9 else 0
        left_continuous = bool(prev and abs(prev['take_start'] + prev['b'] - prev['a'] - piece['take_start']) < .5 / RATE)
        right_continuous = bool(following and abs(piece['take_start'] + piece['b'] - piece['a'] - following['take_start']) < .5 / RATE)
        # A continuous take with unchanged gain is an identity, not an equal-power boost.
        if left_continuous and prev['gain_db'] == piece['gain_db']:
            left = 0
        if right_continuous and following['gain_db'] == piece['gain_db']:
            right = 0
        lo = max(0, round(piece['a'] * RATE) - left)
        hi = min(length, round(piece['b'] * RATE) + right)
        sample = np.arange(lo, hi)
        idx = np.rint((piece['take_start'] + sample / RATE - piece['a']) * RATE).astype(np.int64)
        beyond = int(np.count_nonzero(idx >= len(source)))
        held_samples += beyond
        if beyond and source_edge != 'hold':
            raise ValueError('music take ends before the mapped section')
        idx = np.clip(idx, 0, len(source) - 1)
        env = np.ones(len(sample), np.float64)
        if left:
            phase = np.clip((sample - (piece['a'] * RATE - left)) / (2 * left), 0, 1)
            env *= phase if left_continuous else np.sin(phase * np.pi / 2)
        if right:
            phase = np.clip((sample - (piece['b'] * RATE - right)) / (2 * right), 0, 1)
            env *= 1 - phase if right_continuous else np.cos(phase * np.pi / 2)
        out[lo:hi] += source[idx] * (env * 10 ** (piece['gain_db'] / 20))[:, None]
        if prev and abs(prev['b'] - piece['a']) < 1e-9:
            seams.append({'at_s': piece['a'], 'from': prev['section'], 'to': piece['section'],
                          'take_start': piece['take_start'], 'xfade_ms': piece['xfade_ms']})
    return out, seams, held_samples


def effect_window(a, b, length, attack=.012, release=.006):
    t = np.arange(length) / RATE
    return np.clip((t - (a - attack)) / attack, 0, 1) * np.clip((b - t) / release, 0, 1)


def process(audio, args, ffmpeg):
    length = len(audio)
    if args.highpass_hz is not None:
        if not 0 < args.highpass_hz < RATE / 2:
            raise ValueError('highpass frequency must be inside the audio band')
        audio = filter_audio(ffmpeg, audio, f'highpass=f={args.highpass_hz}:p=2')
    for item in args.bass_cut:
        values = parse_tuple(item, (2, 3), 'bass-cut')
        a, b = values[:2]
        hz = values[2] if len(values) == 3 else 180
        if not 0 <= a < b <= length / RATE or not 0 < hz < RATE / 2:
            raise ValueError('invalid bass-cut window or frequency')
        lo, hi = max(0, round((a - .3) * RATE)), min(length, round((b + .05) * RATE))
        filtered = filter_audio(ffmpeg, audio[lo:hi], hp4(hz))
        t = np.arange(lo, hi) / RATE
        weight = np.clip((t - (a - .012)) / .012, 0, 1) * np.clip((b - t) / .006, 0, 1)
        audio[lo:hi] = audio[lo:hi] * (1 - weight[:, None]) + filtered * weight[:, None]
    for item in args.lift:
        a, b, db = parse_tuple(item, (3,), 'lift')
        if not 0 <= a < b <= length / RATE:
            raise ValueError('invalid lift window')
        weight = effect_window(a, b, length)
        audio *= (1 + weight[:, None] * (10 ** (db / 20) - 1)).astype(np.float32)
    for item in args.tape_stop:
        at, duration = parse_tuple(item, (2,), 'tape-stop')
        if at < 0 or duration <= 0 or at + duration > length / RATE:
            raise ValueError('invalid tape-stop window')
        lo, hi = round(at * RATE), round((at + duration) * RATE)
        u = np.linspace(0, 1, hi - lo, endpoint=False)
        pos = lo + (hi - lo) * (u - u * u / 2)
        for ch in range(2):
            audio[lo:hi, ch] = np.interp(pos, np.arange(length), audio[:, ch]) * (1 - u)
        recovery = min(length - hi, round(.01 * RATE))
        if recovery:
            audio[hi:hi + recovery] *= np.linspace(0, 1, recovery)[:, None]
    for item in args.tail:
        at, rt60, db = parse_tuple(item, (3,), 'tail')
        if not 0 <= at < length / RATE or rt60 <= 0:
            raise ValueError('invalid tail')
        n = int(RATE * min(5.0, rt60 * 1.3))
        t = np.arange(n) / RATE
        ir = np.random.default_rng(56).standard_normal((n, 2)) * (np.exp(-6.9 * t / rt60) * np.clip(t / .012, 0, 1))[:, None]
        # Second-order Butterworth bandpass at 180..6500 Hz, at the fixed 48 kHz rate.
        chain = ('biquad=b0=0.10625589984201027:b1=0.21251179968402054:b2=0.10625589984201027:'
                 'a1=-0.8928937174061541:a2=0.3260113985099475:precision=f64:transform=tdii,'
                 'biquad=b0=1:b1=-2:b2=1:a1=-1.9667459879563027:a2=0.9673203077482855:'
                 'precision=f64:transform=tdii')
        ir = filter_audio(ffmpeg, ir, chain).astype(np.float64)
        ir /= np.maximum(np.sqrt((ir ** 2).sum(axis=0, keepdims=True)), 1e-12)
        start = round(at * RATE)
        dry = audio[start:].astype(np.float64)
        size = 1 << (len(dry) + n - 2).bit_length()
        wet = np.stack([np.fft.irfft(np.fft.rfft(dry[:, ch], size) * np.fft.rfft(ir[:, ch], size), size)[:len(dry)]
                        for ch in range(2)], axis=1)
        window = min(len(dry), int(.6 * RATE))
        wet *= 10 ** (db / 20) * np.sqrt(np.mean(dry[:window] ** 2) / max(1e-12, np.mean(wet[:window] ** 2)))
        audio[start:] += wet.astype(np.float32)
    t = np.arange(length) / RATE
    if args.fade_in:
        audio *= np.clip(t / args.fade_in, 0, 1)[:, None]
    if args.fade_out:
        start, duration = parse_tuple(args.fade_out, (2,), 'fade-out')
        if start < 0 or duration <= 0:
            raise ValueError('invalid fade-out')
        audio *= (np.cos(np.clip((t - start) / duration, 0, 1) * np.pi / 2) ** 1.5)[:, None]
    return audio


def measurements(audio, seams, tempo):
    for seam in seams:
        n = round(seam['at_s'] * RATE)
        delta = float(np.max(np.abs(audio[n] - audio[n - 1]))) if 0 < n < len(audio) else 0
        seam['discontinuity_dbfs'] = io.db(delta)
        seam['look'] = seam['discontinuity_dbfs'] > -60
        if isinstance(tempo, dict) and tempo.get('bar_s') and tempo.get('offset_s') is not None:
            step, phase = float(tempo['bar_s']), float(tempo['offset_s'])
            seam['bar_line_error_ms'] = (seam['take_start'] - (phase + round((seam['take_start'] - phase) / step) * step)) * 1000
        else:
            seam['bar_line_error_ms'] = None
    bars = []
    if isinstance(tempo, dict) and tempo.get('bar_s'):
        bar = float(tempo['bar_s'])
        if bar > 0:
            for start in np.arange(0, len(audio) / RATE, bar):
                x = audio[round(start * RATE):min(len(audio), round((start + bar) * RATE))]
                if len(x) < 2:
                    continue
                f = np.fft.rfftfreq(len(x), 1 / RATE)
                window = np.hanning(len(x))
                spectrum = np.fft.rfft(x * window[:, None], axis=0)
                # Normalise for the bar's length, window energy and channel count.
                scale = len(x) * np.sum(window ** 2) * x.shape[1]
                low = float(2 * np.sum(np.abs(spectrum[(f >= 20) & (f < 150)]) ** 2) / max(scale, 1e-24))
                db = 10 * math.log10(max(low, 1e-24))
                bars.append({'a': float(start), 'b': min(float(start + bar), len(audio) / RATE), 'low_band_db': db,
                             'contrast_db': None if not bars else db - bars[-1]['low_band_db']})
    return bars


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('music')
    parser.add_argument('--map', required=True)
    parser.add_argument('--cues')
    parser.add_argument('--out', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--tempo')
    parser.add_argument('--snap', choices=('bar', 'beat', 'none'), default='none')
    parser.add_argument('--xfade-ms', type=float, default=40)
    parser.add_argument('--bass-cut', action='append', default=[])
    parser.add_argument('--tape-stop', action='append', default=[])
    parser.add_argument('--tail', action='append', default=[])
    parser.add_argument('--lift', action='append', default=[])
    parser.add_argument('--highpass-hz', type=float)
    parser.add_argument('--fade-in', type=float, default=0)
    parser.add_argument('--fade-out')
    parser.add_argument('--source-edge', choices=('refuse', 'hold'), default='refuse')
    args = parser.parse_args()
    try:
        if not math.isfinite(args.xfade_ms) or args.xfade_ms < 0 or not math.isfinite(args.fade_in) or args.fade_in < 0:
            raise ValueError('xfade and fade-in must be non-negative and finite')
        inputs = [args.music, args.map, args.cues, args.tempo]
        project.refuse_overwriting_inputs([args.out, args.report], inputs, guard_versions=True)
        if project.same_file(args.out, args.report):
            raise ValueError('bed and report must have different paths')
        input_hashes = {str(Path(path).resolve()): digest(path) for path in inputs if path}
        mapping = json.loads(Path(args.map).read_text(encoding='utf-8-sig'))
        if not isinstance(mapping, dict):
            raise ValueError('map must be an object')
        cues = None
        cues_hash = input_hashes[str(Path(args.cues).resolve())] if args.cues else None
        if args.cues:
            listed = sibling('cue_list').load_for('conform.py', args.cues)
            if listed.sha256 != cues_hash:
                raise ValueError('the cue list changed while it was loaded')
            cues = {'sections': listed.sections}
        tempo = json.loads(Path(args.tempo).read_text(encoding='utf-8-sig')) if args.tempo else None
        sections, pieces = resolve_sections(mapping, cues, cues_hash, tempo, args.snap, args.xfade_ms)
        ffmpeg = io.find_tool('ffmpeg')
        if not ffmpeg:
            raise ValueError('FFmpeg is required')
        source = io.decode(ffmpeg, args.music, RATE)
        audio, seams, held_samples = assemble(source, pieces, args.source_edge)
        audio = process(audio, args, ffmpeg)
        if not np.isfinite(audio).all():
            raise ValueError('conform produced non-finite audio')
        bars = measurements(audio, seams, tempo)
        if any(not Path(path).is_file() or digest(path) != value for path, value in input_hashes.items()):
            raise ValueError('a conform input changed during processing; rebuild it')
        io.write_wav(ffmpeg, args.out, audio, RATE, floating=True)
        if any(not Path(path).is_file() or digest(path) != value for path, value in input_hashes.items()):
            raise ValueError('a conform input changed while the bed was written; rebuild it')
        report = {'binding': 'bound' if args.cues else 'unbound', 'cues_sha256': cues_hash,
                  'map_sha256': input_hashes[str(Path(args.map).resolve())],
                  'music_sha256': input_hashes[str(Path(args.music).resolve())],
                  'tempo_sha256': input_hashes[str(Path(args.tempo).resolve())] if args.tempo else None,
                  'bed_sha256': digest(args.out), 'sections': sections, 'seams': seams,
                  'low_band_bars': bars, 'rate': RATE, 'duration_s': len(audio) / RATE,
                  'source_edge': args.source_edge, 'held_source_samples': held_samples,
                  'processing': {'snap': args.snap, 'xfade_ms': args.xfade_ms, 'bass_cut': args.bass_cut,
                                 'tape_stop': args.tape_stop, 'tail': args.tail, 'lift': args.lift,
                                 'highpass_hz': args.highpass_hz, 'fade_in': args.fade_in,
                                 'fade_out': args.fade_out},
                  'bar_line_error_basis': 'distance from the take start to the source tempo bar grid',
                  'limit': 'Seams and bar estimates are screens. Unheard.'}
        io.save_json(args.report, report)
        print(f"Conformed {len(sections)} sections; {sum(s['look'] for s in seams)} seam(s) to inspect. Unheard.")
        return 0
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError) as exc:
        print('conform: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
