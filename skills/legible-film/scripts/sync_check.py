#!/usr/bin/env python3
"""Measure the delay between a delivered file's audio and the approved master mix.

Muxing, re-encoding, limiter look-ahead or an editor's handles can shift audio against the
picture. This decodes both soundtracks and cross-correlates several separated windows of real
content (not silence). A constant lag across windows is a transport offset; lags that change
across the film are drift or an edit; weak or ambiguous correlation is inconclusive.

  python sync_check.py deliver/film.mp4 audio/master.wav
  python sync_check.py film.mp4 master.wav --windows 8 --window 4 --tolerance-ms 2 --json qa/sync.json

It compares the delivered soundtrack with the mix you approved. It does not show that a sound
lands on its picture event; check that against the cue list (cue_onsets.py) and by watching.
Needs numpy and FFmpeg. Exit code 0 consistent lag within tolerance, 1 offset/drift/inconclusive,
2 error.
"""

import argparse
import json
import os
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
    a = p.parse_args()
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
    out = {'delivered': a.delivered, 'reference': a.reference, 'rate': RATE, 'summary': summary, 'windows': rows,
           'limit': 'Transport delay against the approved mix only; not picture-event sync.'}
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as fh:
            json.dump(out, fh, indent=1)
    print(f"{os.path.basename(a.delivered)} vs {os.path.basename(a.reference)}: {verdict}")
    for r in rows:
        print(f"  {r['time_s']:8.2f} s  lag {r['lag_ms']:+8.3f} ms  corr {r['correlation']:.3f}"
              + ('  ambiguous' if r['ambiguous'] else ''))
    print(f"  lengths: delivered {summary['delivered_length_s']} s, reference {summary['reference_length_s']} s")
    return code


if __name__ == '__main__':
    sys.exit(main())
