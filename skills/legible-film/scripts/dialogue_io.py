#!/usr/bin/env python3
"""Shared dialogue diagnostics. RMS levels approximate LU differences, not BS.1770 loudness.

Phrases use 20 ms stereo RMS, threshold max(-50 dBFS, peak minus 35 dB),
merge gaps up to 200 ms, and discard regions shorter than 100 ms. Background
noise or quiet speech can defeat this detector. All measurements need listening.
"""

import argparse
import numpy as np


def frames(x, rate, ms=20):
    """Measure stereo RMS in fixed-length windows."""
    n = max(1, round(rate * ms / 1000))
    count = (len(x) + n - 1) // n
    y = np.pad(x.astype(np.float64), ((0, count * n - len(x)), (0, 0)))
    return np.sqrt(np.mean(y.reshape(count, n, x.shape[1]) ** 2, axis=(1, 2))), n


def phrases(x, rate):
    """Find energy-based phrase intervals on the sample clock."""
    env, hop = frames(x, rate)
    if not len(env) or env.max() < 10 ** (-50 / 20):
        return [], env, hop
    active = env >= max(10 ** (-50 / 20), env.max() * 10 ** (-35 / 20))
    edges = np.diff(np.r_[False, active, False].astype(np.int8))
    raw = list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))
    merged = []
    for lo, hi in raw:
        if merged and (lo - merged[-1][1]) * hop <= 0.2 * rate:
            merged[-1] = (merged[-1][0], hi)
        else:
            merged.append((lo, hi))
    return [(lo * hop, min(len(x), hi * hop)) for lo, hi in merged if (hi - lo) * hop >= 0.1 * rate], env, hop


def level(x):
    """Return stereo RMS in dBFS."""
    return (
        float(20 * np.log10(max(1e-12, float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2))))))
        if len(x)
        else -240.0
    )


def separation(io, ffmpeg, voice, bed, rate):
    """Compare phrase loudness, falling back to RMS when needed."""
    # BS.1770 gating needs at least one 400 ms block and audible signals.
    if len(voice) >= 0.4 * rate and level(voice) > -65 and level(bed) > -65:
        v = io.meter(ffmpeg, voice, rate)["integrated_lufs"]
        b = io.meter(ffmpeg, bed, rate)["integrated_lufs"]
        if v is not None and b is not None and v > -70 and b > -70:
            return float(v - b), "integrated_lufs"
    return float(level(voice) - level(bed)), "rms_db_fallback"


def bands(x, rate):
    """Compare 5-9 kHz energy with the speech body."""
    if len(x) < 2:
        return None
    f = np.fft.rfftfreq(len(x), 1 / rate)
    p = np.sum(np.abs(np.fft.rfft(x.astype(np.float64) * np.hanning(len(x))[:, None], axis=0)) ** 2, axis=1)
    body, sib = p[(f >= 200) & (f < 5000)].sum(), p[(f >= 5000) & (f < 9000)].sum()
    return float(10 * np.log10(max(sib, 1e-24) / max(body, 1e-24)))


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
