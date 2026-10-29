#!/usr/bin/env python3
"""Synthesize a seeded, sample-free starter palette and optional timing music.

  python make_sound_kit.py --out audio --seed 7
  python make_sound_kit.py --out audio --temp-bpm 150 --bars 16 --drop-bar 9 --stop-bar 15 --key A

48 kHz stereo 24-bit WAV; one-shots peak-normalised to -3 dBFS (keys vary
slightly). The manifest records hashes, generated sync points and measurements.
Palette version 2 includes non-recursive composite layers and an equal-power
crossfaded loop bed. Music bars are one-based; beat 0 is sample 0. At stop_s
the rhythm stops over 20 ms and a pad/noise ring-out continues to tail_end_s.
The music manifest keeps that tail. Decoded-file measurements include energy
bands, 300 Hz-8 kHz phone-band LU loss and a narrow-resonance screen. These
are reasons to listen, not sound-quality verdicts. No samples or third-party material are used. This is
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
ROLES = ('impact', 'impact_big', 'hit', 'whoosh', 'whoosh_big', 'tick', 'pop', 'key', 'riser', 'logo_hit', 'glitch',
         'sub', 'air', 'bed', 'boom')
MEANINGS = ('a word lands', 'a large reveal lands', 'a contact', 'a transition', 'a large transition',
            'a small selection', 'a rounded confirmation', 'a mechanical key accent', 'anticipation into a cut',
            'the identity settles', 'a brief designed interruption', 'low-end weight under a hit',
            'a bright transient on top', 'continuous room tone or air under the film', 'a large reveal lands')
LAYERS = {'impact': [{'role': 'sub', 'gain_db': -6}, {'role': 'air', 'gain_db': -14}],
          'impact_big': [{'role': 'sub', 'gain_db': -3}, {'role': 'air', 'gain_db': -12}],
          'boom': [{'role': 'sub', 'gain_db': -3}, {'role': 'air', 'gain_db': -12}],
          'whoosh_big': [{'role': 'sub', 'gain_db': -16}, {'role': 'air', 'gain_db': -16}]}


def noise(rng, n, low, high):
    z = rng.standard_normal(n)
    f = np.fft.rfftfreq(n, 1 / RATE)
    # Broad, smooth shoulders, without a resonant filter or a blanket treble cut.
    shape = (1 - np.exp(-(f / max(low, 1)) ** 4)) * np.exp(-(f / high) ** 4)
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
                 'riser': 2.2, 'logo_hit': 2.4, 'glitch': .24,
                 'sub': .48, 'air': .08, 'bed': 6., 'boom': 1.1}
    duration = durations[role] * (1 + (variant - 1) * .025)
    t = np.arange(round(duration * RATE)) / RATE
    pitch = 1 + (variant - 1) * .025
    n = len(t)
    sync, point, fade_out = 'attack', 0.0, .015
    if role == 'bed':
        # FFT-shaped noise is a periodic, band-limited cycle, not a faded
        # one-shot. The manifest asks the mixer for 400 ms equal-power overlaps.
        mid = noise(rng, n, 300, 10500)
        side = noise(rng, n, 500, 9500) * .12
        x = finish(np.column_stack((mid + side, mid - side)), 0, 0)
        return x, 'attack', 0.
    if role == 'sub':
        f = (46 + 70 * np.exp(-t / .018)) * pitch
        x = np.sin(np.cumsum(2 * np.pi * f / RATE)) * np.exp(-t / .095)
    elif role in ('impact', 'impact_big', 'logo_hit', 'boom'):
        big = role != 'impact'
        freq = (65 if big else 115) + 100 * np.exp(-t / .025)
        phase = np.cumsum(2 * np.pi * freq * pitch / RATE)
        # Harmonics, especially 4/6/8 for the large body, carry pitch on a phone.
        body = (.25 * np.sin(phase) + .4 * np.sin(4 * phase) + .28 * np.sin(6 * phase) +
                .16 * np.sin(8 * phase)) * np.exp(-t / (.22 if big else .12))
        transient = noise(rng, n, 1700, 10500) * np.exp(-t / .015) * .85
        tail = noise(rng, n, 500, 8500) * (1 - np.exp(-t / .008)) * np.exp(-t / .22) * .10
        if role == 'logo_hit':
            tail += (.18 * np.sin(2 * np.pi * 660 * pitch * t) + .12 * np.sin(2 * np.pi * 990 * pitch * t)) * np.exp(-t / .65)
            tail += .09 * noise(rng, n, 1800, 10000) * np.exp(-t / .6)
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
        a = noise(rng, n, 300, 2000)
        b = noise(rng, n, 1800, 6500)
        c = noise(rng, n, 5000, 11500)
        y = ((1 - sweep) * a + .30 * b + .85 * sweep * c) * amp
        pan = .15 * np.sin(2 * np.pi * (u - .25))
        x = np.column_stack((y * np.sqrt(1 - pan), y * np.sqrt(1 + pan)))
    elif role == 'pop':
        f = 180 * pitch + 250 * np.exp(-t / .01)
        phase = np.cumsum(2 * np.pi * f / RATE)
        x = (.45 * np.sin(phase) + .32 * np.sin(3 * phase) + .2 * np.sin(5 * phase)) * np.exp(-t / .025)
        x += .65 * noise(rng, n, 2200, 10500) * np.exp(-t / .008)
    elif role == 'key':
        x = noise(rng, n, 650, 10500) * (np.exp(-t / .006) + .3 * np.exp(-((t - .018) / .004) ** 2))
        x += (.22 * np.sin(2 * np.pi * 920 * pitch * t) + .1 * np.sin(2 * np.pi * 1840 * pitch * t)) * np.exp(-t / .012)
    elif role == 'glitch':
        x = noise(rng, n, 400, 10500) * np.exp(-t / .07)
        x *= .3 + .7 * np.sin(2 * np.pi * 38 * pitch * t) ** 4
        x += .14 * np.sin(2 * np.pi * 430 * pitch * t) * np.exp(-t / .08)
    elif role == 'air':
        x = noise(rng, n, 2500, 12000) * np.exp(-t / .012)
    else:
        x = noise(rng, n, 1200 if role == 'hit' else 2800, 11000) * np.exp(-t / (.012 if role == 'hit' else .005))
        x += .18 * np.sin(2 * np.pi * 1500 * pitch * t) * np.exp(-t / .012)
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
    # Sum channel power so stereo anti-phase content cannot hide in the measure.
    power = np.sum(np.abs(np.fft.rfft(x.astype(np.float64), axis=0)) ** 2, axis=1)
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    upper = power[(f >= 3000) & (f <= 6500)]
    # A diagnostic only: ratio of the strongest 20 Hz bin group to its
    # surrounding 400 Hz band. A person judges any audible resonance.
    worst = 0.
    width = RATE // 2
    padded = np.pad(x, ((width // 2, width // 2), (0, 0)))
    freq = np.fft.rfftfreq(width, 1 / RATE)
    centres = np.arange(3000, 6501, 10)
    bounds = [np.searchsorted(freq, centres + edge) for edge in (-200, -10, 10, 200)]
    for start in range(0, len(x), width // 2):
        segment = padded[start:start + width] * np.hanning(width)[:, None]
        p = np.sum(np.abs(np.fft.rfft(segment, axis=0)) ** 2, axis=1)
        cs = np.r_[0., np.cumsum(p)]
        narrow, wide = cs[bounds[2]] - cs[bounds[1]], cs[bounds[3]] - cs[bounds[0]]
        good = wide > max(float(p.sum()) * 1e-7, 1e-18)
        if good.any():
            worst = max(worst, float(np.max(narrow[good] / wide[good])))
    return {'peak_dbfs': io.db(np.max(np.abs(x))), 'dc': x.mean(axis=0).tolist(),
            'head_sample_peak': float(np.max(np.abs(x[0]))), 'tail_sample_peak': float(np.max(np.abs(x[-1]))),
            'upper_mid_energy_share': float(upper.sum() / max(power.sum(), 1e-20)),
            'above_2khz_share': float(power[f >= 2000].sum() / max(power.sum(), 1e-20)),
            'above_6khz_share': float(power[f >= 6000].sum() / max(power.sum(), 1e-20)),
            'below_250hz_share': float(power[f < 250].sum() / max(power.sum(), 1e-20)),
            'upper_mid_max_20hz_in_400hz_share': worst}


def phone_report(ffmpeg, x):
    """BS.1770 integrated loss through 2-pole 300 Hz / 8 kHz filters.

    Pad short takes to 600 ms so the 400 ms meter has a measurable block.
    Identical padding is used on both paths; no gain matching or normalisation.
    """
    padded = np.pad(x, ((0, max(0, round(.6 * RATE) - len(x))), (0, 0)))
    full = io.meter(ffmpeg, padded)['integrated_lufs']
    r = io.run([ffmpeg, '-v', 'error', '-f', 'f32le', '-ar', str(RATE), '-ac', '2', '-i', '-',
                '-af', 'highpass=f=300,lowpass=f=8000', '-f', 'f32le', '-'], padded.astype('<f4').tobytes())
    band = np.frombuffer(r.stdout, '<f4').reshape(-1, 2)
    phone = io.meter(ffmpeg, band)['integrated_lufs']
    return {'integrated_lufs': full, 'phone_band_lufs': phone,
            'phone_loss_lu': full - phone if full is not None and phone is not None else None}


def temp_track(bpm, bars, drop_bar, stop_bar, key, seed):
    period = 60 / bpm
    stop_s = (stop_bar - 1) * 4 * period
    duration = max(bars * 4 * period, stop_s + 1.6)
    n = round(duration * RATE)
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
    t = np.arange(round(.25 * RATE)) / RATE
    phase = np.cumsum(2 * np.pi * (52 + 95 * np.exp(-t / .013)) / RATE)
    kick = finish((np.sin(phase) + .35 * np.sin(4 * phase)) * np.exp(-t / .065) +
                  .8 * noise(rng, len(t), 2200, 10000) * np.exp(-t / .004),
                  fade_in=.0003, peak_db=-8)
    snare = finish(noise(rng, len(t), 1000, 8500) * np.exp(-t / .038) +
                   .2 * np.sin(2 * np.pi * 360 * t) * np.exp(-t / .025), peak_db=-10)
    h = np.arange(round(.055 * RATE)) / RATE
    hat = finish(noise(rng, len(h), 6000, 12000) * np.exp(-h / .011), peak_db=-15)
    oh = np.arange(round(.21 * RATE)) / RATE
    open_hat = finish(noise(rng, len(oh), 6000, 12000) * np.exp(-oh / .07), peak_db=-19)
    def intro_filter(y):
        f = np.fft.rfftfreq(len(y), 1 / RATE)
        z = np.fft.irfft(np.fft.rfft(y, axis=0) * np.exp(-(f / 5500) ** 4)[:, None], len(y), axis=0)
        edge = min(round(.001 * RATE), len(z) // 2)
        z[:edge] *= np.linspace(0, 1, edge)[:, None]
        z[-edge:] *= np.linspace(1, 0, edge)[:, None]
        return z.astype(np.float32)
    intro_snare, intro_hat = intro_filter(snare), intro_filter(hat)
    b = np.arange(round(period * .8 * RATE)) / RATE
    bass = finish((.22 * np.sin(2 * np.pi * root * b) + .26 * np.sin(4 * np.pi * root * b) +
                   .38 * np.sin(12 * np.pi * root * b) + .30 * np.sin(16 * np.pi * root * b) +
                   .18 * np.sin(24 * np.pi * root * b)) * np.exp(-b / .14), peak_db=-14)
    stop = round(stop_s * RATE)
    times = np.arange(stop) / RATE
    drop_s = (drop_bar - 1) * 4 * period
    # A mid-range pad and air run from bar 1, so the intro has no inter-hit holes.
    pad = sum(np.sin(2 * np.pi * root * 8 * 2 ** (semitone / 12) * times + .3 * i)
              for i, semitone in enumerate((0, 3, 7))) / 3
    pad += .16 * np.sin(2 * np.pi * root * 16 * times)
    pad *= np.where(times < drop_s, .06, .08)
    pad += noise(rng, stop, 600, 10000) * .006
    pad *= np.minimum(times / .010, 1)
    # Four dB of smooth kick-triggered sidechain on the harmonic bed. No steps.
    sidechain = np.ones(stop, np.float32)
    for beat in range((stop_bar - 1) * 4):
        a = round(beat * period * RATE)
        count = min(round(min(.22, period * .65) * RATE), stop - a)
        u = np.linspace(0, 1, count)
        depth = np.where(u < .025, .5 * (1 - np.cos(np.pi * u / .025)),
                         .5 * (1 + np.cos(np.pi * (u - .025) / .975)))
        sidechain[a:a + count] *= 10 ** (-4 * depth / 20)
    harmonic = np.zeros_like(x)
    harmonic[:stop] = np.column_stack((pad, pad))
    for beat in range((stop_bar - 1) * 4):
        bar = beat // 4 + 1
        full = bar >= drop_bar
        # A pronounced downbeat accent supplies a known bar phase.
        add(kick, beat * period, (1 if full else .55) * (1.65 if beat % 4 == 0 else .75))
        if beat % 4 in (1, 3):
            add(snare if full else intro_snare, beat * period, 1 if full else .30)
        add(hat if full else intro_hat, beat * period, 1 if full else .42)
        add(open_hat if full and beat % 4 == 3 else hat if full else intro_hat,
            (beat + .5) * period, .8 if full else .3)
        if full:
            k = round(beat * period * RATE)
            count = min(len(bass), stop - k)
            harmonic[k:k + count] += bass[:count] * .7
    harmonic[:stop] *= sidechain[:, None]
    x += harmonic
    riser, _, _ = one_shot('riser', rng)
    riser_length = round(4 * period * RATE)
    # Interpolation is used only for this noise riser, not pitched one-shots.
    r = np.column_stack([np.interp(np.linspace(0, len(riser) - 1, riser_length), np.arange(len(riser)), riser[:, c])
                         for c in range(2)])
    add(r, (drop_bar - 2) * 4 * period, .06)
    fade = min(round(.020 * RATE), stop)
    x[stop - fade:stop] *= np.linspace(1, 0, fade)[:, None]
    x[stop:] = 0
    # The rhythmic stop is exact; a separate original pad/air tail carries it
    # through the ending. It starts from zero and fades to the final sample.
    tail_t = np.arange(n - stop) / RATE
    tail = (.14 * np.sin(2 * np.pi * root * 8 * tail_t) +
            .10 * np.sin(2 * np.pi * root * 12 * tail_t) +
            .08 * np.sin(2 * np.pi * root * 16 * tail_t) +
            .04 * noise(rng, len(tail_t), 1300, 10500))
    tail *= .52 * np.exp(-tail_t / 2.2) * np.minimum(tail_t / .008, 1)
    end_fade = min(len(tail), round(.15 * RATE))
    tail[-end_fade:] *= np.linspace(1, 0, end_fade)
    x[stop:] = np.column_stack((tail, tail))
    x *= 10 ** (-2 / 20) / max(float(np.max(np.abs(x))), 1e-10)
    return x, {'bpm': bpm, 'beat0_s': 0, 'drop_s': (drop_bar - 1) * 4 * period,
               'stop_s': stop / RATE, 'tail_end_s': n / RATE, 'bars': bars, 'drop_bar': drop_bar, 'stop_bar': stop_bar,
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
        palette = {'version': 2, 'rate': RATE, 'seed': a.seed, 'roles': {}, 'status': 'unheard',
                   'master': {'preset': 'social'}}
        selected = set(a.roles)
        for role in a.roles:
            selected.update(layer['role'] for layer in LAYERS.get(role, []))
        for role in (r for r in ROLES if r in selected):
            takes, points, hashes, measurements = [], [], [], []
            role_index = ROLES.index(role)
            for variant in range(3):
                rng = np.random.default_rng(np.random.SeedSequence([a.seed, role_index, variant]))
                x, sync, point = one_shot(role, rng, variant)
                relative = f'bed/room_{variant + 1}.wav' if role == 'bed' else f'sfx/{role}_{variant + 1}.wav'
                io.write_wav(ffmpeg, root / relative, x)
                decoded = io.decode(ffmpeg, root / relative)
                takes.append(relative); points.append(point)
                hashes.append(hashlib.sha256((root / relative).read_bytes()).hexdigest())
                measurements.append(dict(spectrum_report(decoded), **phone_report(ffmpeg, decoded)))
            palette['roles'][role] = {'takes': takes, 'sha256': hashes, 'sync': sync, 'points_s': points,
                                      'meaning': MEANINGS[role_index],
                                      'gain_db': {'key': -5, 'sub': -6, 'air': -12, 'bed': -42}.get(role, -6),
                                      'source': 'make_sound_kit.py (synthesised; no third-party material)',
                                      'licence': 'generated for this project',
                                      'attribution': 'Original procedural synthesis; no third-party samples.',
                                      'measurements': measurements}
            if role in LAYERS:
                palette['roles'][role]['layers'] = LAYERS[role]
            if role == 'bed':
                palette['roles'][role].update(loop=True, crossfade_ms=400)
                palette['bed'] = {'role': 'bed', 'from_s': 0., 'to_s': None,
                                  'fade_in_ms': 300, 'fade_out_ms': 600}
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
            decoded = io.decode(ffmpeg, target)
            measured.update(spectrum_report(decoded))
            measured.update(phone_report(ffmpeg, decoded))
            intro_end = round(min(beat_map['drop_s'], 16 * 60 / a.temp_bpm) * RATE)
            drop_start = round(beat_map['drop_s'] * RATE)
            drop_end = min(round(beat_map['stop_s'] * RATE), drop_start + round(16 * 60 / a.temp_bpm * RATE))
            measured['intro_lufs'] = phone_report(ffmpeg, decoded[:intro_end])['integrated_lufs']
            measured['drop_lufs'] = phone_report(ffmpeg, decoded[drop_start:drop_end])['integrated_lufs']
            measured['intro_minus_drop_lu'] = measured['intro_lufs'] - measured['drop_lufs']
            stop = round(beat_map['stop_s'] * RATE)
            measured['ringout_first_second_lufs'] = phone_report(ffmpeg, decoded[stop:stop + RATE])['integrated_lufs']
            measured['ending_last_tenth_lufs'] = phone_report(ffmpeg, decoded[round(len(decoded) * .9):])['integrated_lufs']
            beat_map['measurements'] = measured
            io.save_json(target.with_suffix('.json'), beat_map)
            palette['music'] = {'file': relative, 'offset_s': 0, 'at_s': 0, 'stop_s': beat_map['tail_end_s'],
                                'rhythmic_stop_s': beat_map['stop_s'],
                                'fade_in_ms': 0, 'fade_out_ms': 100, 'gain_db': -6,
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
