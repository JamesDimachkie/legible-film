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
import json
import math
import os
import shlex
import shutil
import subprocess
import sys

try:
    import numpy as np
except ImportError:  # pragma: no cover
    sys.exit('sync_check.py needs numpy: pip install numpy')

RATE = 48000


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def decode(ffmpeg, path, stream):
    r = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', path, '-map', stream, '-ac', '1', '-ar', str(RATE),
                        '-f', 'f32le', '-'], capture_output=True, check=False)
    if r.returncode:
        reason = (r.stderr.decode(errors='replace').strip().splitlines() or ['?'])[-1]
        print(f'sync_check.py: could not decode audio from {path}: {reason}', file=sys.stderr)
        raise SystemExit(2)
    return np.frombuffer(r.stdout, np.float32).astype(np.float64)


def xcorr(ref, seg):
    """Normalised cross-correlation of ref against every offset inside seg (len(seg) >= len(ref))."""
    n = len(seg) + len(ref)
    size = 1 << (n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(seg, size) * np.conj(np.fft.rfft(ref, size)), size)[:len(seg) - len(ref) + 1]
    csum = np.concatenate([[0.0], np.cumsum(seg ** 2)])
    energy = np.sqrt(np.maximum(csum[len(ref):] - csum[:-len(ref)], 0.0))
    denom = energy * np.sqrt((ref ** 2).sum()) + 1e-12
    return corr / denom


def peak_lag(c, rate):
    best = int(np.argmax(c))
    peak = float(c[best])
    masked = c.copy()
    guard = max(1, round(.002 * rate))
    masked[max(0, best - guard):best + guard + 1] = -1
    second = float(masked.max())
    delta = 0.0
    if 0 < best < len(c) - 1:
        denom = c[best - 1] - 2 * peak + c[best + 1]
        if denom < -1e-12:
            delta = float(np.clip(.5 * (c[best - 1] - c[best + 1]) / denom, -.5, .5))
    return best + delta, peak, second


def fit_rows(rows, tolerance_ms, min_corr):
    good = [r for r in rows if r['correlation'] >= min_corr and not r['ambiguous']]
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
        best, peak, second = peak_lag(xcorr(template, delivered[left:right]), rate)
        power = template ** 2
        centre = float(np.sum(positions * power) / max(float(power.sum()), 1e-30)) / rate
        lag_s = (left + best - s) / rate + (scale - 1) * (centre - s / rate)
        rows.append({'time_s': round(start / RATE, 3), 'fit_time_s': centre,
                     'lag_samples': round(lag_s * RATE, 4), 'lag_ms': round(lag_s * 1000, 6),
                     'correlation': round(peak, 4), 'runner_up': round(second, 4),
                     'ambiguous': second > .95 * peak, 'rate_adjusted': True})
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
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe', help='optional, for the picture-duration repair recipe')
    a = p.parse_args()
    if (a.windows < 1 or not math.isfinite(a.window) or a.window <= 0 or
            not math.isfinite(a.max_lag_ms) or a.max_lag_ms <= 0 or
            not math.isfinite(a.tolerance_ms) or a.tolerance_ms < 0 or not 0 <= a.min_corr <= 1):
        p.error('windows, window and max lag must be positive; tolerance nonnegative; min correlation in [0,1]')
    ffmpeg = find_tool('ffmpeg', a.ffmpeg)
    if not ffmpeg:
        print('ffmpeg is required (PATH, FFMPEG, or --ffmpeg)', file=sys.stderr)
        return 2
    deliv = decode(ffmpeg, a.delivered, '0:a:0')
    ref = decode(ffmpeg, a.reference, '0:a:0')
    win, maxlag = int(a.window * RATE), int(a.max_lag_ms / 1000 * RATE)
    usable = min(len(ref), len(deliv)) - win - 2 * maxlag
    if usable <= 0:
        print('the audio is too short for these windows; reduce --window or --max-lag-ms', file=sys.stderr)
        return 2
    # Choose window starts where the reference has content, spread across the film.
    hop = int(0.25 * RATE)
    starts = np.arange(maxlag, maxlag + usable, hop)
    rms = np.array([np.sqrt(np.mean(ref[s:s + win] ** 2)) for s in starts])
    loud = starts[rms > max(10 ** (-45 / 20), 0.05 * rms.max())]
    if loud.size == 0:
        print('the reference is silent where windows could be taken', file=sys.stderr)
        return 2
    picks = loud[np.linspace(0, loud.size - 1, min(a.windows, loud.size)).round().astype(int)]
    rows = []
    for s in sorted(set(int(x) for x in picks)):
        r = ref[s:s + win]
        seg = deliv[s - maxlag:s + win + maxlag]
        c = xcorr(r, seg)
        best = int(np.argmax(c))
        peak = float(c[best])
        # runner-up outside +/- 2 ms of the best: repetitive music can correlate at a beat multiple
        guard = int(0.002 * RATE)
        masked = c.copy()
        masked[max(0, best - guard):best + guard + 1] = -1
        second = float(masked.max()) if masked.size else -1
        lag = best - maxlag
        rows.append({'time_s': round(s / RATE, 3), 'lag_samples': lag, 'lag_ms': round(lag / RATE * 1000, 3),
                     'correlation': round(peak, 4), 'runner_up': round(second, 4),
                     'ambiguous': second > 0.95 * peak})
    good = [r for r in rows if r['correlation'] >= a.min_corr and not r['ambiguous']]
    original_rows = rows
    fit = None
    if len(good) < len(rows) or (good and np.ptp([r['lag_ms'] for r in good]) > a.tolerance_ms):
        fit, adjusted = drift_fit(ref, deliv, picks, win, maxlag, a.tolerance_ms, a.min_corr, rows)
        if fit:
            fit['windows'] = adjusted
    lags = [r['lag_ms'] for r in good]
    summary = {'windows': len(rows), 'confident_windows': len(good),
               'median_lag_ms': round(float(np.median(lags)), 3) if lags else None,
               'spread_ms': round(max(lags) - min(lags), 3) if lags else None,
               'delivered_length_s': round(len(deliv) / RATE, 3), 'reference_length_s': round(len(ref) / RATE, 3)}
    if len(good) < max(2, len(rows) // 2):
        verdict, code = 'inconclusive: too few confident windows (silence, noise or repetitive material)', 1
    elif summary['spread_ms'] > a.tolerance_ms:
        verdict, code = 'lag changes across the film: drift or an edit between the two', 1
    elif abs(summary['median_lag_ms']) > a.tolerance_ms:
        verdict, code = f"constant offset of {summary['median_lag_ms']} ms (positive: delivered audio is late)", 1
    else:
        verdict, code = 'consistent with the reference within tolerance', 0
    summary['verdict'] = verdict
    if fit:
        summary.update(rate_ratio=fit['rate_ratio'], time_scale=fit['time_scale'], offset_at_zero_ms=fit['offset_ms'])
    out = {'delivered': a.delivered, 'reference': a.reference, 'rate': RATE, 'summary': summary, 'windows': rows,
           'limit': 'Transport delay against the approved mix only; not picture-event sync.'}
    if fit:
        out['original_windows'] = original_rows
        out['drift_fit'] = fit
        out['repair'] = repair_recipe(ffmpeg, find_tool('ffprobe', a.ffprobe), a.delivered, fit)
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=1)
    print(f"{os.path.basename(a.delivered)} vs {os.path.basename(a.reference)}: {verdict}")
    for r in rows:
        print(f"  {r['time_s']:8.2f} s  lag {r['lag_ms']:+8.3f} ms  corr {r['correlation']:.3f}"
              + ('  ambiguous' if r['ambiguous'] else ''))
    print(f"  lengths: delivered {summary['delivered_length_s']} s, reference {summary['reference_length_s']} s")
    if fit:
        print(f"  steady drift: rate ratio {fit['rate_ratio']:.9f}; repair speed {fit['time_scale']:.9f}; "
              f"offset at time zero {fit['offset_ms']:+.6f} ms; max fit residual {fit['max_residual_ms']:.6f} ms")
        for r in fit['windows']:
            print(f"  rate-adjusted window at {r['fit_time_s']:8.3f} s  lag {r['lag_ms']:+10.6f} ms"
                  f"  corr {r['correlation']:.3f}" + ('  ambiguous' if r['ambiguous'] else ''))
        print('  FFmpeg repair (sample-clock error; changes pitch; recheck every window and listen):')
        print('  ' + out['repair'].get('command', out['repair'].get('unavailable', 'unavailable')))
    return code


if __name__ == '__main__':
    sys.exit(main())
