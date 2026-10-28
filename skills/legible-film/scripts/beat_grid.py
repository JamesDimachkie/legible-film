#!/usr/bin/env python3
"""Measure attack timing, tempo, downbeats, loudness rises and within-window drift.

  python beat_grid.py music.wav --bpm 174 --start 0 --window 48 --json grid.json
  python beat_grid.py music.wav --drop-at-beat 32

--bpm is a narrow tempo prior, not a forced result. Times are seconds in the input
track; film beats are zero-based from offset_s. A suggested offset is a track trim:
drop_time - N * period, snapped to the closest measured downbeat. Negative means
pre-roll/silence is needed. Drops are loudness rises, not musical interpretation.
This measures timing, not whether music fits a film. Swing and tempo changes are
reported as residual and drift, not modelled. A constant grid is only a local fit.
Needs numpy and FFmpeg. Exit 0 clear consistent grid; 1 weak, ambiguous, residual
or drift beyond tolerance; 2 could not run. No audio is written.
"""
import argparse
import importlib.util
import math
import sys
from pathlib import Path
import numpy as np

_spec = importlib.util.spec_from_file_location('sound_io', Path(__file__).with_name('sound_io.py'))
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)
RATE, HOP, FRAME = 16000, 16, 256


def attacks(x):
    """Log spectral flux, chunked STFT; refine isolated peaks to waveform attacks.

    The STFT proposes attacks, never bass-energy phase. The 1 ms waveform edge
    refinement avoids assigning a centred FFT window's look-ahead to the beat.
    """
    padded = np.pad(x, (FRAME // 2, FRAME // 2))
    n = len(x) // HOP
    if n < 2:
        return np.zeros(0), np.zeros(0), np.zeros(0), np.zeros(0)
    full, low = np.zeros(n), np.zeros(n)
    prev = np.zeros(FRAME // 2 + 1)
    window = np.hanning(FRAME)
    freqs = np.fft.rfftfreq(FRAME, 1 / RATE)
    for a in range(0, n, 1024):
        b = min(n, a + 1024)
        starts = np.arange(a, b) * HOP
        frames = padded[starts[:, None] + np.arange(FRAME)] * window
        mag = np.log1p(20 * np.abs(np.fft.rfft(frames, axis=1)))
        delta = np.maximum(mag - np.vstack((prev, mag[:-1])), 0)
        full[a:b] = np.mean(delta, axis=1)
        low[a:b] = np.mean(delta[:, (freqs >= 35) & (freqs <= 250)], axis=1)
        prev = mag[-1]
    full /= max(float(np.percentile(full, 99)), 1e-10)
    low /= max(float(np.percentile(low, 99)), 1e-10)
    env = np.minimum(full, 4) * .55 + np.minimum(low, 4) * .45
    peaks = np.flatnonzero((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) &
                           (env[1:-1] > max(.12, float(np.percentile(env, 75)) * 1.4))) + 1
    # A track may start on the attack itself; its first flux frame compares
    # against silence and must participate in non-max suppression too.
    if n > 1 and env[0] > .12 and env[0] >= env[1]:
        peaks = np.r_[0, peaks]
    # Non-max suppression: retain the strongest candidate within 45 ms.
    keep = []
    blocked = np.zeros(n, dtype=bool)
    for k in peaks[np.argsort(env[peaks])[::-1]]:
        if not blocked[k]:
            keep.append(int(k))
            blocked[max(0, k - 45):k + 46] = True
    rms = np.sqrt(np.mean(x[:n * HOP].reshape(n, HOP).astype(np.float64) ** 2, axis=1))
    ts, weights, kicks = [], [], []
    for k in sorted(keep):
        lo, hi = max(0, k - 16), min(n, k + 13)
        seg = rms[lo:hi]
        peak = lo + int(np.argmax(seg))
        floor = float(np.min(seg))
        threshold = floor + .10 * (float(rms[peak]) - floor)
        edge = peak
        while edge > lo and rms[edge - 1] > threshold:
            edge -= 1
        # Dense material has no isolated quiet edge: keep spectral timing there.
        isolated = floor < .25 * max(float(rms[peak]), 1e-10)
        ts.append(edge / 1000 if isolated else k / 1000)
        weights.append(float(env[k]))
        kicks.append(float(low[k]))
    return np.array(ts), np.array(weights), np.array(kicks), env


def grid_score(times, weights, duration, bpm, width=.010):
    period = 60 / bpm
    bins = max(32, int(round(period * 1000)))
    phases = np.mod(times, period) / period * bins
    hist = np.bincount(np.floor(phases).astype(int) % bins, weights=weights, minlength=bins)
    radius = max(1, int(width * 1000))
    smoothed = sum(np.roll(hist, k) * math.exp(-.5 * (k / (radius / 2)) ** 2)
                   for k in range(-radius, radius + 1))
    phase = (int(np.argmax(smoothed)) + .5) / bins * period
    distance = np.abs((times - phase + period / 2) % period - period / 2)
    near = distance < width * 2
    if not near.any():
        return 0.0, phase
    # Recall penalises half tempo; coverage penalises double tempo.
    response = np.exp(-.5 * (distance / width) ** 2)
    recall = float(np.sum(weights * response) / max(weights.sum(), 1e-10))
    indices = np.round((times[near] - phase) / period).astype(int)
    strongest = {}
    for i, w in zip(indices, weights[near] * response[near]):
        strongest[i] = max(strongest.get(i, 0), float(w))
    count = max(1, int(duration / period))
    coverage = min(1.0, len(strongest) / count)
    return math.sqrt(max(0, recall * coverage)), phase


def fit(times, weights, duration, prior=None, bounds=None):
    if len(times) < 6:
        raise ValueError('fewer than six strong attacks: no measurable beat grid')
    if bounds:
        lo, hi = bounds
    else:
        lo, hi = (max(60, prior * .97), min(200, prior * 1.03)) if prior else (60, 200)
    # Autocorrelation proposes local tempo candidates, alongside a coarse global
    # search. The prior keeps a requested tempo from slipping to a subdivision.
    length = max(1, int(duration * 200) + 1)
    train = np.zeros(length)
    np.add.at(train, np.minimum((times * 200).astype(int), length - 1), weights)
    size = 1 << (2 * length - 1).bit_length()
    spectrum = np.fft.rfft(train, size)
    ac = np.fft.irfft(spectrum * np.conj(spectrum), size)[:length]
    lags = np.arange(max(1, int(12000 / hi)), min(length - 1, int(12000 / lo)) + 1)
    proposals = [12000 / k for k in lags[np.argsort(ac[lags])[-12:]]] if len(lags) else []
    candidates = list(np.arange(lo, hi + .001, .20)) + [p for p in proposals if lo <= p <= hi]
    if prior and lo <= prior <= hi:
        candidates.append(prior)
    def evaluate(bpm):
        score, phase = grid_score(times, weights, duration, bpm)
        penalty = math.exp(-.5 * ((bpm / prior - 1) / .02) ** 2) if prior else 1
        return score * penalty, score, phase, bpm
    winners = sorted((evaluate(p) for p in candidates), reverse=True)[:6]
    fine = []
    for _, _, _, p in winners:
        fine.extend(np.arange(max(lo, p - .22), min(hi, p + .22) + .0001, .004))
    _, score, phase, bpm = max((evaluate(p) for p in fine), default=winners[0])
    period = 60 / bpm
    # Robust least-squares fit of period AND phase against nearest attacks.
    for _ in range(4):
        grid = np.arange(phase, duration, period)
        picks, numbers, strengths = [], [], []
        for i, t in enumerate(grid):
            near = np.flatnonzero(np.abs(times - t) < min(.045, period / 8))
            if near.size:
                j = near[np.argmax(weights[near] * np.exp(-.5 * ((times[near] - t) / .015) ** 2))]
                picks.append(times[j]); numbers.append(i); strengths.append(weights[j])
        if len(picks) < 4:
            break
        coef = np.polyfit(numbers, picks, 1, w=np.sqrt(strengths))
        residual = np.asarray(picks) - np.polyval(coef, numbers)
        good = np.abs(residual) < max(.004, float(np.median(np.abs(residual))) * 3)
        if good.sum() >= 4:
            coef = np.polyfit(np.asarray(numbers)[good], np.asarray(picks)[good], 1,
                             w=np.sqrt(np.asarray(strengths)[good]))
        if lo <= 60 / coef[0] <= hi:
            period, phase = float(coef[0]), float(coef[1])
        else:
            break
    phase %= period
    if period - phase < 1e-7:
        phase = 0.0
    score, _ = grid_score(times, weights, duration, 60 / period)
    return period, phase, score


def analyse(x, start=0, bpm=None, beats_per_bar=4, drop_at_beat=None, tolerance_ms=15):
    duration = len(x) / RATE
    times, weights, kicks, env = attacks(x)
    if len(times) < 6:
        result = {'bpm': None, 'period_s': None, 'offset_s': None, 'downbeats': [], 'bar_s': None,
                  'drops': [], 'grid_strength': 0, 'residual_ms': {'median': None, 'p90': None, 'missing_beats': None},
                  'drift_ms': None, 'alternatives': [], 'duration_s': duration, 'start_s': start,
                  'film_beats_available': 0, 'flags': ['fewer than six strong attacks: no measurable grid'],
                  'limit': 'Timing only; too little attack evidence to estimate tempo. Unheard.'}
        if drop_at_beat is not None:
            result.update(suggested_offset_s=None, suggested_offset_negative=False)
        return result, 1
    period, phase, strength = fit(times, weights, duration, bpm)
    grid = np.arange(phase, duration, period)
    kick_scores = []
    for slot in range(beats_per_bar):
        vals = []
        for t in grid[slot::beats_per_bar]:
            near = np.abs(times - t) < period / 8
            vals.append(float(np.max(kicks[near])) if near.any() else 0)
        kick_scores.append(float(np.mean(vals)) if vals else 0)
    slot = int(np.argmax(kick_scores))
    projected_down = grid[slot::beats_per_bar]
    # Report measured downbeat attacks, not an extrapolated early beat in
    # leading silence. With drift, the global least-squares intercept need not
    # coincide with the first attack: retain both anchors explicitly.
    measured_down = []
    for t in projected_down:
        near = np.flatnonzero((np.abs(times - t) < period / 4) & (weights > .10))
        if near.size:
            j = near[np.argmax(kicks[near] * np.exp(-.5 * ((times[near] - t) / .035) ** 2))]
            measured_down.append(float(times[j]))
    offset = float(measured_down[0] if measured_down else projected_down[0])
    down = np.array(measured_down)
    # The reported residual belongs to the usable constant grid anchored at
    # offset_s; it must not quietly use a different regression intercept.
    grid = np.arange(offset, duration, period)
    residuals, missing = [], 0
    for t in grid:
        distances = np.abs(times - t)
        near = distances[distances <= period / 4]
        if near.size:
            residuals.append(float(near.min()) * 1000)
        else:
            missing += 1
    halves = []
    for a, b in ((0, duration / 2), (duration / 2, duration)):
        mask = (times >= a) & (times < b)
        try:
            p, _, _ = fit(times[mask] - a, weights[mask], b - a, 60 / period,
                          (60 / period * .985, 60 / period * 1.015))
            halves.append(p)
        except ValueError:
            halves.append(None)
    drift = ((halves[1] - halves[0]) / period * duration * 1000
             if all(p is not None for p in halves) else None)
    bar = period * beats_per_bar
    drops = []
    for t in down:
        if t < bar or t + bar > duration:
            continue
        before = x[max(0, int((t - bar) * RATE)):int(t * RATE)]
        after = x[int(t * RATE):min(len(x), int((t + 2 * bar) * RATE))]
        rise = io.level(after) - io.level(before)
        if rise > 1:
            drops.append({'music_s': round(start + float(t), 6),
                          'film_beat': round((t - offset) / period), 'rise_db': round(rise, 3)})
    drops.sort(key=lambda d: d['rise_db'], reverse=True)
    alternatives = []
    for name, factor in (('half', .5), ('double', 2), ('two_thirds', 2 / 3)):
        score, _ = grid_score(times, weights, duration, 60 / period * factor)
        alternatives.append({'tempo': name, 'bpm': 60 / period * factor, 'score': round(score, 4)})
    median = float(np.median(residuals)) if residuals else None
    p90 = float(np.percentile(residuals, 90)) if residuals else None
    reasons = []
    if strength < .45 or missing > len(grid) * .2:
        reasons.append('weak grid or too many beats without a strong onset')
    if p90 is None or p90 > tolerance_ms:
        reasons.append('onset residual exceeds tolerance')
    if drift is None or abs(drift) > tolerance_ms:
        reasons.append('drift exceeds tolerance or could not be measured')
    if any(v['score'] >= strength * .9 for v in alternatives):
        reasons.append('alternative tempo within 10%: ambiguous')
    result = {'bpm': 60 / period, 'period_s': period, 'offset_s': start + offset, 'fit_phase_s': start + phase,
              'downbeats': [round(start + float(t), 6) for t in down[:16]], 'bar_s': bar,
              'drops': drops, 'grid_strength': round(strength, 4),
              'residual_ms': {'median': median, 'p90': p90, 'missing_beats': missing},
              'drift_ms': drift, 'half_periods_s': halves, 'alternatives': alternatives,
              'duration_s': duration, 'start_s': start,
              'film_beats_available': max(0, int((duration - offset) / period)),
              'kick_slot_scores': kick_scores, 'flags': reasons,
              'limit': 'Timing only; downbeat and drop are attack/loudness hypotheses. Unheard.'}
    if drop_at_beat is not None:
        suggested = None
        if drops:
            target = drops[0]['music_s'] - drop_at_beat * period
            extrapolated = target < start + offset or target > start + float(down[-1])
            if extrapolated:
                index = round((target - (start + offset)) / bar)
                suggested = start + offset + index * bar
            else:
                suggested = start + float(down[np.argmin(np.abs(start + down - target))])
            result['suggested_offset_extrapolated'] = extrapolated
            result['drop_alignment_error_ms'] = (drops[0]['music_s'] - suggested - drop_at_beat * period) * 1000
            if abs(result['drop_alignment_error_ms']) > tolerance_ms:
                reasons.append('requested drop beat cannot align after downbeat snapping')
        result['suggested_offset_s'] = suggested
        result['suggested_offset_negative'] = suggested is not None and suggested < 0
        if not drops:
            reasons.append('no measurable drop for requested alignment')
    return result, 1 if reasons else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('music')
    p.add_argument('--bpm', type=io.positive)
    p.add_argument('--start', type=io.finite, default=0)
    p.add_argument('--window', type=io.positive)
    p.add_argument('--beats-per-bar', type=int, default=4)
    p.add_argument('--drop-at-beat', type=int)
    p.add_argument('--tolerance-ms', type=io.positive, default=15)
    p.add_argument('--json')
    p.add_argument('--ffmpeg')
    a = p.parse_args()
    try:
        ffmpeg = io.find_tool('ffmpeg', a.ffmpeg)
        if not ffmpeg or a.start < 0 or a.beats_per_bar < 1 or (a.bpm and not 60 <= a.bpm <= 200):
            raise ValueError('need FFmpeg, start >= 0, beats-per-bar >= 1 and BPM in 60..200')
        x = io.decode(ffmpeg, a.music, RATE, 1, a.start, a.window)[:, 0]
        result, code = analyse(x, a.start, a.bpm, a.beats_per_bar, a.drop_at_beat, a.tolerance_ms)
        if a.json:
            io.save_json(a.json, result)
        tempo = f"{result['bpm']:.5f}" if result['bpm'] is not None else 'unknown'
        phase = f"{result['offset_s']:.6f}" if result['offset_s'] is not None else 'unknown'
        print(f"{Path(a.music).name}: {tempo} BPM, downbeat {phase} s; "
              f"strength {result['grid_strength']}; residual {result['residual_ms']}; drift {result['drift_ms']} ms")
        if 'suggested_offset_s' in result:
            print(f"  suggested trim {result['suggested_offset_s']} s; negative={result['suggested_offset_negative']}")
        for flag in result['flags']:
            print('  inspect: ' + flag)
        return code
    except (OSError, ValueError, IndexError) as exc:
        print('beat_grid.py: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
