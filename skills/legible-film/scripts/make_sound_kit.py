#!/usr/bin/env python3
"""Synthesize a seeded, sample-free starter palette and optional timing music.

  python make_sound_kit.py --out audio --seed 7
  python make_sound_kit.py --out audio --temp-bpm 150 --bars 16 --drop-bar 9 --stop-bar 15 --key A

48 kHz stereo 24-bit WAV; one-shots peak-normalised to -3 dBFS (keys vary
slightly). The manifest records hashes, generated sync points and measurements.
Music bars are one-based; beat 0 is sample 0. The stop is exclusive: a 20 ms
fade finishes at stop_s. No samples or third-party material are used. This is
a starter palette and temp track for timing/animatics, not a listening verdict
or legal advice. A person must listen, decide suitability and decide if it ships.
Needs numpy and FFmpeg. Exit 0 generated; 2 could not run.
"""
import argparse
import hashlib
import importlib.util
import math
import sys
from pathlib import Path
import numpy as np

_spec = importlib.util.spec_from_file_location('sound_io', Path(__file__).with_name('sound_io.py'))
io = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(io)
RATE = 48000
ROLES = ('impact', 'impact_big', 'hit', 'whoosh', 'whoosh_big', 'tick', 'pop', 'key', 'riser', 'logo_hit', 'glitch')
MEANINGS = ('a word lands', 'a large reveal lands', 'a contact', 'a transition', 'a large transition',
            'a small selection', 'a rounded confirmation', 'a mechanical key accent', 'anticipation into a cut',
            'the identity settles', 'a brief designed interruption')


def noise(rng, n, low, high):
    z = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1 / RATE)
    # Smooth shoulders and a broad upper-mid reduction, never a resonant notch.
    shape = (1 - np.exp(-(f / max(low, 1)) ** 4)) * np.exp(-(f / high) ** 4)
    shape *= 1 - .7 * np.exp(-.5 * ((f - 4700) / 1500) ** 2)
    x = np.fft.irfft(np.fft.rfft(z) * shape, n)
    return x / max(float(np.std(x)), 1e-10)


def finish(x, fade_in=.001, fade_out=.015, peak_db=-3):
    if x.ndim == 1:
        x = np.column_stack((x, x))
    env = np.ones(len(x))
    ni, no = min(len(x), round(fade_in * RATE)), min(len(x), round(fade_out * RATE))
    if ni:
        env[:ni] *= np.sin(np.linspace(0, np.pi / 2, ni)) ** 2
    if no:
        env[-no:] *= np.sin(np.linspace(np.pi / 2, 0, no)) ** 2
    x = x * env[:, None]
    # Remove DC without destroying the zero-valued boundaries.
    x -= env[:, None] * (x.mean(axis=0) / max(env.mean(), 1e-10))
    x *= 10 ** (peak_db / 20) / max(float(np.max(np.abs(x))), 1e-10)
    return x.astype(np.float32)


def one_shot(role, rng, variant=0):
    durations = {'impact': .6, 'impact_big': 1.1, 'hit': .18, 'whoosh': .64,
                 'whoosh_big': 1.1, 'tick': .07, 'pop': .16, 'key': .11,
                 'riser': 2.2, 'logo_hit': 2.4, 'glitch': .24}
    duration = durations[role] * (1 + (variant - 1) * .025)
    t = np.arange(round(duration * RATE)) / RATE
    pitch = 1 + (variant - 1) * .025
    n = len(t)
    sync, point, fade_out = 'attack', 0.0, .015
    if role in ('impact', 'impact_big', 'logo_hit'):
        big = role != 'impact'
        freq = (48 if big else 75) + 110 * np.exp(-t / .025)
        body = np.sin(np.cumsum(2 * np.pi * freq * pitch / RATE)) * np.exp(-t / (.26 if big else .14))
        transient = noise(rng, n, 300, 2300) * np.exp(-t / .012) * .32
        tail = noise(rng, n, 300, 2100) * (1 - np.exp(-t / .01)) * np.exp(-t / .3) * .06
        if role == 'logo_hit':
            tail += (.10 * np.sin(2 * np.pi * 660 * pitch * t) + .07 * np.sin(2 * np.pi * 990 * pitch * t)) * np.exp(-t / .38)
        x = body + transient + tail
    elif role.startswith('whoosh') or role == 'riser':
        u = t / duration
        if role == 'riser':
            amp = (.06 + .94 * u ** 1.5)
            sync, point, fade_out = 'end', n / RATE, .028
            sweep = u
        else:
            amp = np.sin(np.pi * u) ** 3
            sync, point = 'apex', duration / 2
            sweep = np.sin(np.pi * u)
        # Crossfade overlapping bands: a moving broad noise centre, no sharp
        # time-varying filter coefficients and no periodic FFT loop splice.
        a = noise(rng, n, 100, 700)
        b = noise(rng, n, 600, 2600)
        y = ((1 - sweep) * a + sweep * b) * amp
        pan = .15 * np.sin(2 * np.pi * (u - .25))
        x = np.column_stack((y * np.sqrt(1 - pan), y * np.sqrt(1 + pan)))
    elif role == 'pop':
        f = 180 * pitch + 250 * np.exp(-t / .01)
        x = np.sin(np.cumsum(2 * np.pi * f / RATE)) * np.exp(-t / .022)
    elif role == 'key':
        x = noise(rng, n, 350, 2400) * (np.exp(-t / .006) + .3 * np.exp(-((t - .018) / .004) ** 2))
        x += .22 * np.sin(2 * np.pi * 920 * pitch * t) * np.exp(-t / .012)
    elif role == 'glitch':
        x = noise(rng, n, 200, 2400) * np.exp(-t / .07)
        x *= .3 + .7 * np.sin(2 * np.pi * 38 * pitch * t) ** 4
        x += .14 * np.sin(2 * np.pi * 430 * pitch * t) * np.exp(-t / .08)
    else:
        x = noise(rng, n, 400, 2500) * np.exp(-t / (.009 if role == 'hit' else .004))
        x += .25 * np.sin(2 * np.pi * 1300 * pitch * t) * np.exp(-t / .008)
    x = finish(x, fade_out=fade_out, peak_db=-3 - (.6 * variant if role == 'key' else 0))
    if sync == 'apex':
        # Place the actual 5 ms energy apex, not a geometric envelope guess.
        mono = x.mean(axis=1).astype(np.float64)
        sq = np.concatenate(([0.], np.cumsum(mono ** 2)))
        energy = (sq[240:] - sq[:-240])[::48]
        # Match cue_onsets' existing 1 ms / forward 5 ms RMS convention:
        # its apex timestamp is the RIGHT edge of the loudest RMS window.
        point = (int(np.argmax(energy)) * 48 + 240) / RATE
    return x, sync, point


def spectrum_report(x):
    y = x.mean(axis=1)
    power = np.abs(np.fft.rfft(y)) ** 2
    f = np.fft.rfftfreq(len(y), 1 / RATE)
    upper = power[(f >= 3000) & (f <= 6500)]
    # A diagnostic only: ratio of the strongest 20 Hz bin group to its
    # surrounding 400 Hz band. A person judges any audible resonance.
    worst = 0.
    for centre in np.arange(3000, 6501, 100):
        narrow = power[np.abs(f - centre) < 10].sum()
        wide = power[np.abs(f - centre) < 200].sum()
        worst = max(worst, float(narrow / max(wide, 1e-20)))
    return {'peak_dbfs': io.db(np.max(np.abs(x))), 'dc': x.mean(axis=0).tolist(),
            'head_sample_peak': float(np.max(np.abs(x[0]))), 'tail_sample_peak': float(np.max(np.abs(x[-1]))),
            'upper_mid_energy_share': float(upper.sum() / max(power.sum(), 1e-20)),
            'upper_mid_max_20hz_in_400hz_share': worst}


def temp_track(bpm, bars, drop_bar, stop_bar, key, seed):
    period = 60 / bpm
    n = round(bars * 4 * period * RATE)
    x = np.zeros((n, 2), np.float32)
    rng = np.random.default_rng(seed)
    notes = {'C': 0, 'C#': 1, 'DB': 1, 'D': 2, 'D#': 3, 'EB': 3, 'E': 4, 'F': 5,
             'F#': 6, 'GB': 6, 'G': 7, 'G#': 8, 'AB': 8, 'A': 9, 'A#': 10, 'BB': 10, 'B': 11}
    if key.upper() not in notes:
        raise ValueError('key must be a note such as A, C# or Bb')
    root = 440 * 2 ** ((notes[key.upper()] + 24 - 69) / 12)
    def add(y, seconds, gain=1):
        k = round(seconds * RATE)
        length = min(len(y), n - k)
        if length > 0:
            x[k:k + length] += y[:length] * gain
    t = np.arange(round(.23 * RATE)) / RATE
    kick = finish(np.sin(np.cumsum(2 * np.pi * (48 + 100 * np.exp(-t / .013)) / RATE)) * np.exp(-t / .065),
                  fade_in=.0003, peak_db=-8)
    snare = finish(noise(rng, len(t), 250, 2300) * np.exp(-t / .028), peak_db=-14)
    h = np.arange(round(.045 * RATE)) / RATE
    hat = finish(noise(rng, len(h), 1800, 7500) * np.exp(-h / .008), peak_db=-24)
    b = np.arange(round(period * .7 * RATE)) / RATE
    bass = finish((np.sin(2 * np.pi * root * b) + .2 * np.sin(4 * np.pi * root * b)) * np.exp(-b / .13), peak_db=-15)
    def filtered_intro(y):
        f = np.fft.rfftfreq(len(y), 1 / RATE)
        out = np.fft.irfft(np.fft.rfft(y, axis=0) * np.exp(-(f / 1300) ** 4)[:, None], len(y), axis=0)
        # Re-fade after the filter to suppress its boundary wrap.
        fade = min(round(.002 * RATE), len(out) // 2)
        out[:fade] *= np.linspace(0, 1, fade)[:, None]
        out[-fade:] *= np.linspace(1, 0, fade)[:, None]
        return out.astype(np.float32)
    intro_snare, intro_hat = filtered_intro(snare), filtered_intro(hat)
    for beat in range((stop_bar - 1) * 4):
        bar = beat // 4 + 1
        full = bar >= drop_bar
        # A pronounced downbeat accent supplies a known bar phase.
        add(kick, beat * period, (1 if full else .24) * (1.65 if beat % 4 == 0 else .75))
        if beat % 4 in (1, 3):
            add(snare if full else intro_snare, beat * period, 1 if full else .18)
        add(hat if full else intro_hat, beat * period, 1 if full else .18)
        add(hat if full else intro_hat, (beat + .5) * period, .65 if full else .1)
        if full:
            add(bass, beat * period, .7)
    riser, _, _ = one_shot('riser', rng)
    riser_length = round(4 * period * RATE)
    # Interpolation is used only for this noise riser, not pitched one-shots.
    r = np.column_stack([np.interp(np.linspace(0, len(riser) - 1, riser_length), np.arange(len(riser)), riser[:, c])
                         for c in range(2)])
    add(r, (drop_bar - 2) * 4 * period, .10)
    stop = round((stop_bar - 1) * 4 * period * RATE)
    fade = min(round(.020 * RATE), stop)
    x[stop - fade:stop] *= np.linspace(1, 0, fade)[:, None]
    x[stop:] = 0
    x *= 10 ** (-2 / 20) / max(float(np.max(np.abs(x))), 1e-10)
    return x, {'bpm': bpm, 'beat0_s': 0, 'drop_s': (drop_bar - 1) * 4 * period,
               'stop_s': stop / RATE, 'bars': bars, 'drop_bar': drop_bar, 'stop_bar': stop_bar,
               'key': key, 'label': 'Temp track for timing and animatics; unheard; a person decides whether it can ship.'}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--out', required=True)
    p.add_argument('--seed', type=int, default=7)
    p.add_argument('--roles', nargs='+', choices=ROLES, default=list(ROLES))
    p.add_argument('--temp-bpm', type=io.positive)
    p.add_argument('--bars', type=int, default=16)
    p.add_argument('--drop-bar', type=int, default=9)
    p.add_argument('--stop-bar', type=int, default=15)
    p.add_argument('--key', default='A')
    p.add_argument('--json', help='also write the palette report here')
    p.add_argument('--ffmpeg')
    a = p.parse_args()
    try:
        ffmpeg = io.find_tool('ffmpeg', a.ffmpeg)
        if not ffmpeg:
            raise ValueError('FFmpeg is required (PATH, FFMPEG, or --ffmpeg)')
        if a.temp_bpm and not (2 <= a.drop_bar < a.stop_bar <= a.bars + 1):
            raise ValueError('need 2 <= drop-bar < stop-bar <= bars + 1')
        root = Path(a.out)
        root.mkdir(parents=True, exist_ok=True)
        palette = {'version': 1, 'rate': RATE, 'seed': a.seed, 'roles': {}, 'status': 'unheard'}
        for role in a.roles:
            takes, points, hashes, measurements = [], [], [], []
            role_index = ROLES.index(role)
            for variant in range(3):
                rng = np.random.default_rng(np.random.SeedSequence([a.seed, role_index, variant]))
                x, sync, point = one_shot(role, rng, variant)
                relative = f'sfx/{role}_{variant + 1}.wav'
                io.write_wav(ffmpeg, root / relative, x)
                takes.append(relative); points.append(point)
                hashes.append(hashlib.sha256((root / relative).read_bytes()).hexdigest())
                measurements.append(spectrum_report(x))
            palette['roles'][role] = {'takes': takes, 'sha256': hashes, 'sync': sync, 'points_s': points,
                                      'meaning': MEANINGS[role_index], 'gain_db': -5 if role == 'key' else -3,
                                      'source': 'make_sound_kit.py (synthesised; no third-party material)',
                                      'licence': 'generated for this project', 'measurements': measurements}
        if a.temp_bpm:
            x, beat_map = temp_track(a.temp_bpm, a.bars, a.drop_bar, a.stop_bar, a.key, a.seed)
            relative = f'music/temp-{a.temp_bpm:g}bpm.wav'
            target = root / relative
            io.write_wav(ffmpeg, target, x)
            measured = io.meter(ffmpeg, target)
            if measured['true_peak_dbtp'] is None:
                raise ValueError('could not verify temp-track true peak')
            if measured['true_peak_dbtp'] > -1.1:
                x *= 10 ** ((-1.2 - measured['true_peak_dbtp']) / 20)
                io.write_wav(ffmpeg, target, x)
                measured = io.meter(ffmpeg, target)
            if measured['true_peak_dbtp'] > -1:
                raise ValueError('temp-track true peak still exceeds -1 dBTP')
            beat_map['measurements'] = measured
            io.save_json(target.with_suffix('.json'), beat_map)
            palette['music'] = {'file': relative, 'offset_s': 0, 'at_s': 0, 'stop_s': beat_map['stop_s'],
                                'fade_in_ms': 0, 'fade_out_ms': 20, 'gain_db': -6,
                                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                                'source': 'make_sound_kit.py (synthesised; no third-party material)',
                                'licence': 'generated for this project', 'label': beat_map['label']}
        io.save_json(root / 'palette.json', palette)
        if a.json:
            io.save_json(a.json, palette)
        print(f"Generated {sum(len(r['takes']) for r in palette['roles'].values())} takes in {root}; "
              f"temp music={'music' in palette}. Unheard: a person must listen.")
        return 0
    except (OSError, ValueError) as exc:
        print('make_sound_kit.py: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
