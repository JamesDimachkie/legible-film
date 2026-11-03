#!/usr/bin/env python3
"""Measure the delay between a delivered file's audio and the approved master mix.

Muxing, re-encoding, limiter look-ahead or an editor's handles can shift audio against the
picture. This decodes both soundtracks and cross-correlates several separated windows of real
content (not silence). A constant lag across windows is a transport offset; lags that change
across the film are drift or an edit; weak or ambiguous correlation is inconclusive.
For steadily changing lag, short low-pass probes propose an affine time map, then
full-length rate-adjusted windows validate it. A supported fit reports rate_ratio
(delivered playback rate / reference rate), time_scale = 1 / rate_ratio, and offset
at reference time zero: delivered_time = time_scale * reference_time + offset_s.
For example, audio slowed with asetrate=48000*0.99 has rate_ratio ~0.99 and needs
speed ~1.01010101. The printed command uses asetrate then aresample (changes pitch),
resets timestamps, removes the fitted offset after rate correction, and pads/trims
to the measured picture duration, never -shortest. It writes a new file; it is not
applied automatically. Prefer reconforming the approved master if pitch must stay
unchanged; atempo=time_scale preserves pitch for a true tempo error, but is not the
inverse of a sample-clock error. Recheck every window after any repair and listen.
Fits need >=3 confident windows, >=80% coverage, monotonic lag, and residuals within
max(--tolerance-ms, 1 ms). Nonlinear drift or edits get no global rate repair.
The probe search covers time scales 0.95-1.05; larger rate errors are inconclusive.
Existing window time_s is its start; fit_time_s is the reference energy centroid
where its lag applies. Confident original windows can seed the fit when the short
probes fall in silence, as with sparse effects.
The original table and JSON windows remain unchanged; drift_fit.windows adds the
validated rate-adjusted measurements. The original verdict and exit code remain.
The fit uses decoded sample clocks, as the original lag check does; an independent
container start-time discontinuity or edit must be resolved before using the recipe.

  python sync_check.py deliver/film.mp4 audio/master.wav
  python sync_check.py film.mp4 master.wav --windows 8 --window 4 --tolerance-ms 2 --json qa/sync.json

It compares the delivered soundtrack with the mix you approved. It does not show that a sound
lands on its picture event; check that against the cue list (cue_onsets.py) and by watching.
Needs numpy and FFmpeg; ffprobe is also needed to print a picture-duration repair.
Exit code 0 nothing to fix (consistent lag within tolerance), 1 inspect or fix
(offset/drift/inconclusive), 2 could not run.
"""

import argparse
import importlib.util
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

_project_spec = importlib.util.spec_from_file_location(
    'lf_project', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py'))
project = importlib.util.module_from_spec(_project_spec)
_project_spec.loader.exec_module(project)
try:
    import numpy as np
except ImportError as missing:
    print(project.dependency_message(missing.name or 'numpy'), file=sys.stderr)
    sys.exit(2)

RATE = 48000
CORRELATION_FLOOR_DBFS = -90.0
CORRELATION_FLOOR_RMS = 10 ** (CORRELATION_FLOOR_DBFS / 20)


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def leading_priming(ffprobe, path):
    """Encoder priming a decode must drop: samples, at the stream's own rate, that sit before its time zero.

    FFmpeg 6.1 keeps an AAC encoder's priming in a Matroska decode and marks it only by a negative start time in whole
    milliseconds, so a player skips it and a plain decode does not. FFmpeg 9.0 drops it itself and reports a start of
    zero, as MP4's edit list does. FFmpeg 5.1's muxer marks nothing, so its file plays the priming and is late.
    """
    if not ffprobe:
        return 0
    probe = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                            'stream=sample_rate,initial_padding,start_time', '-of', 'json', str(path)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        stream = json.loads(probe.stdout)['streams'][0]
        rate, start = int(stream['sample_rate']), float(stream['start_time'])
        padding = int(stream.get('initial_padding') or 0)
    except (ValueError, TypeError, KeyError, IndexError):
        return 0
    if probe.returncode or rate <= 0 or padding <= 0 or not start < 0:
        return 0
    return padding if abs(start + padding / rate) <= .002 else 0


def decode(ffmpeg, path, stream, skip=0):
    trim = ['-af', f'atrim=start_sample={skip}'] if skip else []
    r = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', path, '-map', stream, *trim, '-ac', '1',
                        '-ar', str(RATE), '-f', 'f32le', '-'], capture_output=True, check=False)
    if r.returncode:
        reason = (r.stderr.decode(errors='replace').strip().splitlines() or ['?'])[-1]
        print(f'sync_check.py: could not decode audio from {path}: {reason}', file=sys.stderr)
        raise SystemExit(2)
    return np.frombuffer(r.stdout, np.float32).astype(np.float64)


def decode_stereo(ffmpeg, path, skip=0):
    """Decode both channels for content comparison after transport alignment."""
    trim = ['-af', f'atrim=start_sample={skip}'] if skip else []
    r = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', path, '-map', '0:a:0', *trim, '-ac', '2',
                        '-ar', str(RATE), '-f', 'f32le', '-'], capture_output=True, check=False)
    if r.returncode:
        reason = (r.stderr.decode(errors='replace').strip().splitlines() or ['?'])[-1]
        raise ValueError(f'could not decode audio from {path}: {reason}')
    values = np.frombuffer(r.stdout, np.float32)
    if len(values) % 2:
        raise ValueError('decoded audio has an incomplete sample')
    return values.reshape(-1, 2)


def exact_aac_reencode(ffmpeg, ffprobe, reference, delivered):
    """Prove a delivered AAC decode matches a local re-encode of the reference."""
    if not ffprobe:
        return None
    probe = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                            'stream=codec_name,bit_rate:format=format_name,bit_rate', '-of', 'json', str(delivered)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        metadata = json.loads(probe.stdout)
        stream = metadata['streams'][0]
    except (ValueError, TypeError, KeyError, IndexError):
        return None
    if probe.returncode or stream.get('codec_name') != 'aac':
        return None
    format_info = metadata.get('format') or {}
    try:
        bitrate = int(stream.get('bit_rate') or format_info.get('bit_rate') or 0)
    except (ValueError, TypeError):
        bitrate = 0
    standards = (32000, 48000, 64000, 80000, 96000, 112000, 128000, 160000, 192000, 224000,
                 256000, 320000, 384000, 512000)
    # The reported average need not equal the encoder's requested bit rate,
    # especially for short or sparse material. Try nearby standard settings and
    # 128k; only an identical decoded hash can establish the exception.
    candidates = sorted(standards, key=lambda value: abs(value - bitrate))[:3] if bitrate > 0 else []
    if 128000 not in candidates:
        candidates.append(128000)
    # Matroska and MP4 handle AAC priming/padding differently on decode.
    extension = 'mka' if 'matroska' in (format_info.get('format_name') or '').split(',') else 'm4a'
    with tempfile.TemporaryDirectory(prefix='lf-sync-codec-') as temp:
        def decoded_hash(path):
            result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a:0',
                                     '-ac', '2', '-ar', str(RATE), '-c:a', 'pcm_f32le',
                                     '-f', 'hash', '-hash', 'sha256', '-'], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace')
            return result.stdout.strip() if result.returncode == 0 else None

        actual = decoded_hash(delivered)
        if not actual:
            return None
        for chosen in candidates:
            encoded = os.path.join(temp, f'reference-{chosen}.{extension}')
            made = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', str(reference), '-map', '0:a:0',
                                   '-c:a', 'aac', '-b:a', str(chosen), encoded], capture_output=True)
            if not made.returncode and decoded_hash(encoded) == actual:
                return {'method': 'identical decoded audio after a local AAC re-encode of the full reference',
                        'bitrate_bps': chosen, 'decoded_sha256': actual}
    return None


def aac_frame_samples(ffprobe, path):
    """One AAC frame expressed at the comparison's decoded sample rate."""
    if not ffprobe:
        return 0
    probe = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                            'stream=codec_name,sample_rate', '-of', 'json', str(path)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        stream = json.loads(probe.stdout)['streams'][0]
        rate = int(stream['sample_rate'])
    except (ValueError, TypeError, KeyError, IndexError):
        return 0
    if probe.returncode or stream.get('codec_name') != 'aac' or rate <= 0:
        return 0
    return math.ceil(1024 * RATE / rate)


def outside_span(value):
    try:
        a, b = (float(x) for x in value.split(','))
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a <= b):
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError('use two finite times A,B with 0 <= A <= B')
    return a, b


def level_db(samples):
    return 20 * math.log10(max(float(np.sqrt(np.mean(np.square(samples, dtype=np.float64)))), 1e-8))


def compare_outside(ref, delivered, span, lag_samples, window_ms=50, margin_db=20, aac_tail_samples=0):
    """Compare aligned windows outside the allowed interval.

    The empirical floor is estimated from the quietest residual windows. It is
    a measurement limit, not a guarantee about the codec or inaudible changes.
    """
    size = max(1, round(window_ms * RATE / 1000))
    if span[1] > len(ref) / RATE:
        raise ValueError('the allowed passage extends beyond the reference audio')
    limit = max(0, min(len(ref), len(delivered) - lag_samples))
    start = min(len(ref), max(0, -lag_samples))
    delivered_end = len(delivered) - lag_samples
    difference = abs(delivered_end - len(ref))
    padded_tail = bool(limit > start and aac_tail_samples and 0 < difference < aac_tail_samples)
    extent = max(len(ref), delivered_end) if padded_tail else limit
    bounds = [(start, min(extent, round(span[0] * RATE))),
              (max(start, round(span[1] * RATE)), extent)]
    rows = []

    def missing(left, right, reason):
        for a, b in ((left, min(right, round(span[0] * RATE))),
                     (max(left, round(span[1] * RATE)), right)):
            if b > a:
                rows.append({'start_s': a / RATE, 'end_s': b / RATE,
                             'state': 'not assessed', 'reason': reason})

    missing(0, start, 'no aligned delivered audio')
    if not padded_tail:
        missing(limit, len(ref), 'no aligned delivered audio')
        if delivered_end > len(ref):
            missing(len(ref), delivered_end, 'no aligned reference audio')
    if lag_samples > 0:
        rows.append({'start_s': -lag_samples / RATE, 'end_s': 0.0,
                     'state': 'not assessed', 'reason': 'delivered audio precedes the reference'})
    for left, right in bounds:
        if 0 < right - left < size:
            rows.append({'start_s': left / RATE, 'end_s': right / RATE, 'state': 'not assessed',
                         'reason': 'shorter than one analysis window'})
            continue
        pos = left
        while pos < right:
            end = min(right, pos + size)
            if right - end < size:
                end = right
            x = ref[pos:min(end, len(ref))].astype(np.float64)
            y = delivered[pos + lag_samples:min(end + lag_samples, len(delivered))].astype(np.float64)
            length = end - pos
            row = {'start_s': pos / RATE, 'end_s': end / RATE}
            if len(x) < length:
                row['reference_zero_pad_samples'] = length - len(x)
                x = np.pad(x, ((0, length - len(x)),) + ((0, 0),) * (x.ndim - 1))
            if len(y) < length:
                row['delivered_zero_pad_samples'] = length - len(y)
                y = np.pad(y, ((0, length - len(y)),) + ((0, 0),) * (y.ndim - 1))
            row.update(reference_dbfs=level_db(x), residual_dbfs=level_db(y - x))
            rows.append(row)
            pos = end
    residuals = [r['residual_dbfs'] for r in rows if 'residual_dbfs' in r]
    floor = max(-90.0, float(np.percentile(residuals, 10)) + 6) if residuals else None
    for row in rows:
        if 'reference_dbfs' not in row:
            continue
        relative_limit = row['reference_dbfs'] - margin_db
        row['detection_limit_dbfs'] = max(floor, relative_limit)
        if row['reference_dbfs'] <= floor:
            row.update(state='not assessed', reason='reference is at or below the estimated residual floor')
        elif row['residual_dbfs'] >= relative_limit and row['residual_dbfs'] >= floor:
            row['state'] = 'changed'
        elif floor > relative_limit:
            row.update(state='not assessed', reason='the estimated residual floor exceeds the relative limit')
        else:
            row['state'] = 'unchanged within tolerance'
    changed = [r for r in rows if r['state'] == 'changed']
    unassessed = [r for r in rows if r['state'] == 'not assessed']
    if changed:
        verdict = 'changed outside the passage'
    elif not rows or unassessed:
        verdict = 'inconclusive: outside passage not fully assessed'
    else:
        verdict = 'unchanged within tolerance'
    limit_note = ('The floor is an estimate from the quietest residual windows, not a codec guarantee. '
                  'Each window reports the quietest residual it can flag.')
    if padded_tail:
        limit_note += ' A trailing difference shorter than an AAC frame is zero-padded in the last window.'
    return {'verdict': verdict, 'window_ms': window_ms, 'margin_db': margin_db,
            'estimated_residual_floor_dbfs': floor, 'assessed_windows': len(rows) - len(unassessed),
            'not_assessed_windows': len(unassessed), 'changed': changed, 'windows': rows,
            'limit': limit_note}


def unaligned_outside(args, ref, delivered, reason):
    """Preserve an inconclusive comparison when transport cannot be measured."""
    verdict = 'inconclusive: ' + reason
    out = {'delivered': args.delivered, 'reference': args.reference, 'rate': RATE,
           'summary': {'verdict': verdict, 'windows': 0, 'confident_windows': 0,
                       'delivered_length_s': len(delivered) / RATE, 'reference_length_s': len(ref) / RATE},
           'windows': [], 'outside': {'verdict': verdict, 'changed': [], 'windows': [],
                                      'not_assessed_windows': None, 'estimated_residual_floor_dbfs': None,
                                      'limit': 'No aligned windows; the detection limit is not established.'},
           'limit': 'Transport alignment and outside audio content were not established.'}
    if args.json:
        with open(args.json, 'w', encoding='utf-8') as stream:
            json.dump(out, stream, indent=1)
    print(verdict + '; outside content not assessed; detection limit not established')
    return 1


def xcorr(ref, seg):
    """Correlate each usable candidate, without subtracting cumulative energies."""
    width = len(ref)
    count = len(seg) - width + 1
    scores = np.full(count, np.nan)
    reference_power = float(np.dot(ref, ref))
    floor_power = width * CORRELATION_FLOOR_RMS ** 2
    if not np.isfinite(reference_power) or reference_power < floor_power:
        return scores

    # A window spans at most two width-sized blocks. Add its left suffix and
    # right prefix, so loud earlier samples cannot cancel a quiet local energy.
    squared = np.square(seg, dtype=np.float64)
    power = np.empty(count)
    for start in range(0, count, width):
        length = min(width, count - start)
        suffix = np.cumsum(squared[start:start + width][::-1])[::-1]
        power[start:start + length] = suffix[:length]
        if length > 1:
            power[start + 1:start + length] += np.cumsum(squared[start + width:start + width + length - 1])
    usable = np.isfinite(power) & (power >= floor_power)
    if not np.any(usable):
        return scores
    n = len(seg) + width
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(ref, size)), size)[:count]
    values = corr[usable] / np.sqrt(power[usable] * reference_power)
    scores[usable] = np.clip(values, -1.0, 1.0)
    return scores


def peak_lag(c, rate):
    if not np.any(np.isfinite(c)):
        return None, None, None
    best = int(np.nanargmax(c))
    peak = float(c[best])
    masked = c.copy()
    guard = max(1, round(.002 * rate))
    masked[max(0, best - guard):best + guard + 1] = np.nan
    second = float(np.nanmax(masked)) if np.any(np.isfinite(masked)) else -1.0
    delta = 0.0
    if 0 < best < len(c) - 1 and np.isfinite(c[best - 1]) and np.isfinite(c[best + 1]):
        denom = c[best - 1] - 2 * peak + c[best + 1]
        if denom < -1e-12:
            delta = float(np.clip(.5 * (c[best - 1] - c[best + 1]) / denom, -.5, .5))
    return best + delta, peak, second


def fit_rows(rows, tolerance_ms, min_corr):
    good = [r for r in rows if r['correlation'] is not None and r['correlation'] >= min_corr and not r['ambiguous']]
    if len(good) < max(3, math.ceil(.8 * len(rows))):
        return None
    t = np.array([r['fit_time_s'] for r in good])
    lag = np.array([r['lag_ms'] / 1000 for r in good])
    if np.ptp(t) <= 0:
        return None
    slope, offset = np.polyfit(t, lag, 1)
    residual = float(np.max(np.abs(lag - (slope * t + offset))) * 1000)
    allowance = max(tolerance_ms, 1.0)
    if residual > allowance or not .95 <= 1 + slope <= 1.05:
        return None
    # A step or reversal must not masquerade as a sample-clock error.
    differences = np.diff(lag) * (1 if slope >= 0 else -1)
    if np.any(differences < -allowance / 1000):
        return None
    return {'rate_ratio': float(1 / (1 + slope)), 'time_scale': float(1 + slope),
            'offset_s': float(offset), 'offset_ms': float(offset * 1000),
            'max_residual_ms': residual, 'confident_windows': len(good)}


def scaled_windows(ref, delivered, picks, win, maxlag, rate, scale):
    rows = []
    for start in picks:
        s = round(start * rate / RATE)
        n = round(win * rate / RATE)
        margin = round(maxlag * rate / RATE)
        count = max(2, round(n * scale))
        positions = s + np.arange(count) / scale
        left, right = max(0, s - margin), min(len(delivered), s + count + margin)
        if positions[-1] >= len(ref) or right - left < count:
            continue
        template = np.interp(positions, np.arange(len(ref)), ref)
        scores = xcorr(template, delivered[left:right])
        best, peak, second = peak_lag(scores, rate)
        power = template ** 2
        centre = float(np.sum(positions * power) / max(float(power.sum()), 1e-30)) / rate
        row = {'time_s': round(start / RATE, 3), 'fit_time_s': centre, 'rate_adjusted': True,
               'not_assessed_candidates': int(np.count_nonzero(~np.isfinite(scores)))}
        if peak is None:
            row.update(state='not assessed', reason='reference or all candidate windows are below the energy floor',
                       lag_samples=None, lag_ms=None, correlation=None, runner_up=None, ambiguous=False)
        else:
            lag_s = (left + best - s) / rate + (scale - 1) * (centre - s / rate)
            row.update(state='measured', lag_samples=round(lag_s * RATE, 4), lag_ms=round(lag_s * 1000, 6),
                       correlation=round(peak, 4), runner_up=round(second, 4), ambiguous=second > .95 * peak)
        rows.append(row)
    return rows


def drift_fit(ref, delivered, picks, win, maxlag, tolerance_ms, min_corr, original_rows):
    # A 40 ms band-limited anchor tolerates a 1% rate error that decorrelates a
    # three-second waveform window. Long windows then refine and validate the map.
    # Start with the original confident measurements where possible. Their
    # energy centroids avoid treating a silent window centre as a sound anchor.
    direct = []
    for row, start in zip(original_rows, picks):
        power = ref[start:start + win] ** 2
        centre = (start + float(np.dot(np.arange(len(power)), power)) / max(float(power.sum()), 1e-30)) / RATE
        direct.append(dict(row, fit_time_s=centre))
    fit = fit_rows(direct, tolerance_ms, min_corr)
    if fit:
        span = abs(fit['time_scale'] - 1) * np.ptp([r['fit_time_s'] for r in direct]) * 1000
        if span > tolerance_ms:
            for _ in range(2):
                rows = scaled_windows(ref, delivered, picks, win, maxlag, RATE, fit['time_scale'])
                fit = fit_rows(rows, tolerance_ms, min_corr)
                if not fit or len(rows) != len(picks):
                    break
            if fit and len(rows) == len(picks):
                return fit, rows
    step, low_rate = 12, RATE // 12
    u = np.arange(-48, 49)
    kernel = np.sinc(2 * 1000 / RATE * u) * np.hanning(len(u))
    kernel /= kernel.sum()
    low_ref = np.convolve(ref, kernel, 'same')[::step]
    low_del = np.convolve(delivered, kernel, 'same')[::step]
    short = min(win, round(.04 * RATE))
    anchors = [s + (win - short) // 2 for s in picks]
    rows = scaled_windows(low_ref, low_del, anchors, short, maxlag, low_rate, 1.0)
    fit = fit_rows(rows, tolerance_ms, min_corr)
    if not fit or len(rows) != len(picks):
        return None, None
    for _ in range(3):
        rows = scaled_windows(low_ref, low_del, picks, win, maxlag, low_rate, fit['time_scale'])
        refined = fit_rows(rows, tolerance_ms, min_corr)
        if not refined or len(rows) != len(picks):
            return None, None
        fit = refined
    rows = scaled_windows(ref, delivered, picks, win, maxlag, RATE, fit['time_scale'])
    refined = fit_rows(rows, tolerance_ms, min_corr)
    if not refined or len(rows) != len(picks):
        return None, None
    # Report the fit of the native-rate validated lags; do not infer a repair from
    # the low-pass probes alone. Near-constant offsets stay on the original path.
    span_ms = abs(refined['time_scale'] - 1) * (rows[-1]['fit_time_s'] - rows[0]['fit_time_s']) * 1000
    if span_ms <= tolerance_ms:
        return None, None
    return refined, rows


def repair_recipe(ffmpeg, ffprobe, path, fit):
    """Executable argv as well as a quoted command; duration must come from picture."""
    if not ffprobe:
        return {'unavailable': 'ffprobe is required to establish the picture duration; no repair printed'}
    r = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_frames', '-show_entries',
                        'stream=start_time,duration:frame=best_effort_timestamp_time,duration_time,pkt_duration_time',
                        '-of', 'json', path], capture_output=True, text=True)
    try:
        data = json.loads(r.stdout or '{}')
        stream = data['streams'][0]
        frames = data.get('frames', [])
        if frames:
            last = frames[-1]
            tail = float(last.get('duration_time', last.get('pkt_duration_time', 0)))
            duration = float(last['best_effort_timestamp_time']) + tail - float(frames[0]['best_effort_timestamp_time'])
            if tail <= 0:
                duration = float(stream['duration'])
        else:
            duration = float(stream['duration'])
        if r.returncode or not math.isfinite(duration) or duration <= 0:
            raise ValueError('no finite picture duration')
        # This command resets audio to zero. A nonzero picture origin needs its
        # own timeline decision rather than an apparently exact global repair.
        if abs(float(stream.get('start_time', 0))) > .001:
            raise ValueError('nonzero picture start; resolve the container timeline first')
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return {'unavailable': f'could not establish a zero-origin picture duration: {exc}'}
    speed = fit['time_scale']
    corrected_offset = fit['offset_s'] / speed
    filters = f'aresample={RATE},asetrate={RATE}*{speed:.12f},aresample={RATE},asetpts=PTS-STARTPTS'
    if corrected_offset > 0:
        filters += f',atrim=start={corrected_offset:.9f},asetpts=PTS-STARTPTS'
    elif corrected_offset < 0:
        filters += f',adelay={round(-corrected_offset * RATE)}S:all=1'
    filters += f',apad,atrim=duration={duration:.9f},asetpts=N/SR/TB'
    output = os.path.splitext(path)[0] + '-rate-repaired.mp4'
    argv = [ffmpeg, '-nostdin', '-i', path, '-map', '0:v:0', '-map', '0:a:0', '-c:v', 'copy',
            '-af', filters, '-t', f'{duration:.9f}', '-c:a', 'aac', '-b:a', '256k', '-ar', str(RATE),
            '-movflags', '+faststart', output]
    if os.name == 'nt':
        command = '& ' + ' '.join("'" + v.replace("'", "''") + "'" for v in argv)
    else:
        command = shlex.join(argv)
    return {'audio_filter': filters, 'picture_duration_s': duration, 'argv': argv, 'command': command,
            'output': output, 'shell': 'PowerShell' if os.name == 'nt' else 'POSIX',
            'limit': 'Inverse sample-clock repair changes pitch; recheck sync and true peak, and listen.'}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('delivered')
    p.add_argument('reference', help='the approved master mix (WAV or any file with audio)')
    p.add_argument('--windows', type=int, default=6)
    p.add_argument('--window', type=float, default=3.0, help='window length in seconds')
    p.add_argument('--max-lag-ms', type=float, default=500.0)
    p.add_argument('--tolerance-ms', type=float, default=2.0, help='allowed lag and allowed spread between windows')
    p.add_argument('--min-corr', type=float, default=0.8)
    p.add_argument('--outside', type=outside_span, metavar='A,B',
                   help='compare all aligned audio outside the allowed passage')
    p.add_argument('--window-ms', type=float, default=50.0, help='outside comparison window in milliseconds')
    p.add_argument('--margin-db', type=float, default=20.0, help='outside residual margin below reference level')
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe', help='optional, for AAC frame sizing, priming before time zero and the '
                                     'picture-duration repair recipe')
    a = p.parse_args()
    try:
        project.refuse_overwriting_inputs([a.json], [a.delivered, a.reference])
    except ValueError as error:
        print(f'sync_check.py: cannot run: {error}', file=sys.stderr)
        return 2
    if (a.windows < 1 or not math.isfinite(a.window) or a.window < 1 / RATE or
            not math.isfinite(a.max_lag_ms) or a.max_lag_ms <= 0 or
            not math.isfinite(a.tolerance_ms) or a.tolerance_ms < 0 or not 0 <= a.min_corr <= 1 or
            not math.isfinite(a.window_ms) or a.window_ms <= 0 or
            not math.isfinite(a.margin_db) or a.margin_db <= 0):
        p.error('windows and max lag must be positive; window at least one sample; '
                'tolerance nonnegative; min correlation in [0,1]')
    ffmpeg = find_tool('ffmpeg', a.ffmpeg)
    if not ffmpeg:
        print('ffmpeg is required (PATH, FFMPEG, or --ffmpeg)', file=sys.stderr)
        return 2
    ffprobe = find_tool('ffprobe', a.ffprobe)
    deliv_skip, ref_skip = leading_priming(ffprobe, a.delivered), leading_priming(ffprobe, a.reference)
    deliv = decode(ffmpeg, a.delivered, '0:a:0', deliv_skip)
    ref = decode(ffmpeg, a.reference, '0:a:0', ref_skip)
    if a.outside and a.outside[1] > len(ref) / RATE:
        print('the allowed passage extends beyond the reference audio', file=sys.stderr)
        return 2
    win, maxlag = int(a.window * RATE), int(a.max_lag_ms / 1000 * RATE)
    usable = min(len(ref), len(deliv)) - win - 2 * maxlag
    if usable <= 0:
        if a.outside:
            return unaligned_outside(a, ref, deliv, 'audio is too short for transport windows')
        print('the audio is too short for these windows; reduce --window or --max-lag-ms', file=sys.stderr)
        return 2
    # Choose window starts where the reference has content, spread across the film.
    hop = int(0.25 * RATE)
    starts = np.arange(maxlag, maxlag + usable, hop)
    rms = np.array([np.sqrt(np.mean(ref[s:s + win] ** 2)) for s in starts])
    loud = starts[rms >= max(CORRELATION_FLOOR_RMS, 0.05 * rms.max())]
    candidates = loud if loud.size else starts
    picks = candidates[np.linspace(0, candidates.size - 1, min(a.windows, candidates.size)).round().astype(int)]
    rows = []
    for s in sorted(set(int(x) for x in picks)):
        r = ref[s:s + win]
        seg = deliv[s - maxlag:s + win + maxlag]
        c = xcorr(r, seg)
        row = {'time_s': round(s / RATE, 3), 'not_assessed_candidates': int(np.count_nonzero(~np.isfinite(c)))}
        if not np.any(np.isfinite(c)):
            row.update(state='not assessed', reason='reference or all candidate windows are below the energy floor',
                       lag_samples=None, lag_ms=None, correlation=None, runner_up=None, ambiguous=False)
        else:
            best = int(np.nanargmax(c))
            peak = float(c[best])
            # Repetitive music can correlate at a beat multiple.
            guard = int(0.002 * RATE)
            masked = c.copy()
            masked[max(0, best - guard):best + guard + 1] = np.nan
            second = float(np.nanmax(masked)) if np.any(np.isfinite(masked)) else -1.0
            lag = best - maxlag
            row.update(state='measured', lag_samples=lag, lag_ms=round(lag / RATE * 1000, 3),
                       correlation=round(peak, 4), runner_up=round(second, 4), ambiguous=second > .95 * peak)
        rows.append(row)
    good = [r for r in rows if r['correlation'] is not None and r['correlation'] >= a.min_corr and not r['ambiguous']]
    original_rows = rows
    fit = None
    if len(good) < len(rows) or (good and np.ptp([r['lag_ms'] for r in good]) > a.tolerance_ms):
        fit, adjusted = drift_fit(ref, deliv, picks, win, maxlag, a.tolerance_ms, a.min_corr, rows)
        if fit:
            fit['windows'] = adjusted
    lags = [r['lag_ms'] for r in good]
    summary = {'windows': len(rows), 'confident_windows': len(good),
               'not_assessed_windows': sum(r['state'] == 'not assessed' for r in rows),
               'correlation_floor_dbfs': CORRELATION_FLOOR_DBFS,
               'median_lag_ms': round(float(np.median(lags)), 3) if lags else None,
               'spread_ms': round(max(lags) - min(lags), 3) if lags else None,
               'delivered_length_s': round(len(deliv) / RATE, 3), 'reference_length_s': round(len(ref) / RATE, 3)}
    if len(good) < max(2, len(rows) // 2):
        verdict, code = 'inconclusive: too few confident windows (silence, noise or repetitive material)', 1
    elif summary['spread_ms'] > a.tolerance_ms:
        verdict, code = 'lag changes across the film: drift or an edit between the two', 1
    elif abs(summary['median_lag_ms']) > a.tolerance_ms:
        verdict, code = f"constant offset of {summary['median_lag_ms']} ms (positive: delivered audio is late)", 1
    elif summary['not_assessed_windows']:
        verdict, code = 'inconclusive: some transport windows are below the energy floor', 1
    else:
        verdict, code = 'consistent with the reference within tolerance', 0
    summary['verdict'] = verdict
    if fit:
        summary.update(rate_ratio=fit['rate_ratio'], time_scale=fit['time_scale'], offset_at_zero_ms=fit['offset_ms'])
    out = {'delivered': a.delivered, 'reference': a.reference, 'rate': RATE, 'summary': summary, 'windows': rows,
           'limit': 'Transport delay against the approved mix only; not picture-event sync.'}
    if a.outside:
        if len(good) < max(2, len(rows) // 2) or summary['spread_ms'] > a.tolerance_ms or fit:
            out['outside'] = {'verdict': 'inconclusive: transport alignment is not established',
                              'changed': [], 'not_assessed_windows': None}
        else:
            try:
                ref_stereo = decode_stereo(ffmpeg, a.reference, ref_skip)
                del_stereo = decode_stereo(ffmpeg, a.delivered, deliv_skip)
                lag_samples = round(summary['median_lag_ms'] * RATE / 1000)
                aac_tail = max(aac_frame_samples(ffprobe, a.delivered),
                               aac_frame_samples(ffprobe, a.reference))
                out['outside'] = compare_outside(ref_stereo, del_stereo, a.outside, lag_samples,
                                                 a.window_ms, a.margin_db, aac_tail)
                outside = out['outside']
                if outside['changed']:
                    proof = exact_aac_reencode(ffmpeg, ffprobe, a.reference, a.delivered)
                    if proof:
                        for row in outside['windows']:
                            if row['state'] != 'unchanged within tolerance':
                                row['window_state_before_codec_proof'] = row['state']
                                if row.get('reason'):
                                    row['window_reason_before_codec_proof'] = row['reason']
                                row.update(state='unchanged within tolerance',
                                           reason='the decoded audio matches the reference encoded locally')
                        outside.update(verdict='unchanged within tolerance', changed=[],
                                       assessed_windows=len(outside['windows']), not_assessed_windows=0,
                                       codec_proof=proof)
                        outside['limit'] += ' The AAC exception requires identical decoded audio from a local re-encode.'
            except ValueError as error:
                print(f'sync_check.py: {error}', file=sys.stderr)
                return 2
        if out['outside']['verdict'] != 'unchanged within tolerance':
            code = 1
    if fit:
        out['original_windows'] = original_rows
        out['drift_fit'] = fit
        out['repair'] = repair_recipe(ffmpeg, find_tool('ffprobe', a.ffprobe), a.delivered, fit)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=1)
    print(f"{os.path.basename(a.delivered)} vs {os.path.basename(a.reference)}: {verdict}")
    print(f'  reference and candidate windows below {CORRELATION_FLOOR_DBFS:g} dBFS RMS are not assessed')
    for r in rows:
        if r['state'] == 'not assessed':
            print(f"  {r['time_s']:8.2f} s  not assessed: {r['reason']}")
        else:
            print(f"  {r['time_s']:8.2f} s  lag {r['lag_ms']:+8.3f} ms  corr {r['correlation']:.3f}"
                  + ('  ambiguous' if r['ambiguous'] else '')
                  + (f"  {r['not_assessed_candidates']} candidates below floor" if r['not_assessed_candidates'] else ''))
    print(f"  lengths: delivered {summary['delivered_length_s']} s, reference {summary['reference_length_s']} s")
    if a.outside:
        outside = out['outside']
        print(f"  outside {a.outside[0]:g}-{a.outside[1]:g} s: {outside['verdict']}; "
              f"{len(outside['changed'])} changed windows; {outside['not_assessed_windows']} not assessed")
        if 'estimated_residual_floor_dbfs' in outside:
            print(f"  estimated residual floor {outside['estimated_residual_floor_dbfs']} dBFS; "
                  'per-window detection limits are in the JSON report')
    if fit:
        print(f"  steady drift: rate ratio {fit['rate_ratio']:.9f}; repair speed {fit['time_scale']:.9f}; "
              f"offset at time zero {fit['offset_ms']:+.6f} ms; max fit residual {fit['max_residual_ms']:.6f} ms")
        for r in fit['windows']:
            if r['state'] == 'not assessed':
                print(f"  rate-adjusted window at {r['fit_time_s']:8.3f} s  not assessed: {r['reason']}")
            else:
                print(f"  rate-adjusted window at {r['fit_time_s']:8.3f} s  lag {r['lag_ms']:+10.6f} ms"
                      f"  corr {r['correlation']:.3f}" + ('  ambiguous' if r['ambiguous'] else ''))
        print('  FFmpeg repair (sample-clock error; changes pitch; recheck every window and listen):')
        print('  ' + out['repair'].get('command', out['repair'].get('unavailable', 'unavailable')))
    return code


if __name__ == '__main__':
    sys.exit(main())
