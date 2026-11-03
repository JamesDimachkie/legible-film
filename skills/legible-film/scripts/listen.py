#!/usr/bin/env python3
"""Measure sound and its relation to picture. Human listening remains separate."""

import argparse
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
except ImportError as missing:
    import runpy
    project_file = Path(__file__).with_name('project.py')
    sys.exit(runpy.run_path(str(project_file))['missing_package'](missing))

HERE = Path(__file__).resolve().parent
RATE = 48000
# 10th to 90th percentiles from earshot's launch profile (Leon Lin, MIT; see NOTICE).
PROFILE = {
    'integrated_lufs': [-19.32, -9.16], 'true_peak_dbtp': [-0.26, 1.52],
    'lra_lu': [2.66, 9.08], 'side_to_mid_db': [-11.8, -5.78],
    'correlation': [0.58, 0.864], 'sub': [-12.36, -4.58], 'low': [-5.92, -2.34],
    'lowmid': [-16.38, -3.2], 'mid': [-15.92, -10.68], 'presence': [-30.24, -13.52],
    'air': [-31.86, -14.74],
}
SHORT_SPAN = 'span under 2 s'  # a follow span shorter than this is not screened, and says so
BANDS = {'sub': (20, 60), 'low': (60, 250), 'lowmid': (250, 1000),
         'mid': (1000, 4000), 'presence': (4000, 8000), 'air': (8000, 16000), 'top': (16000, 24000)}


def sibling(name):
    spec = importlib.util.spec_from_file_location('lf_listen_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_cues(path, owner=None):
    """Use the shared loader and its normalized scale and freshness state."""
    listed = sibling('cue_list').load(path, owner=owner)
    if listed.version == 'v1':
        _, _, problems = sibling('cue_onsets').validate(listed.doc)
        if problems:
            raise ValueError('the legacy cue list cannot be checked: ' + '; '.join(problems))
    if not isinstance(listed.events, list):
        raise ValueError('the cue list needs an events list')
    events = []
    for original in listed.events:
        if not isinstance(original, dict):
            raise ValueError('a cue is not an object')
        event = dict(original, scale=listed.scale(original))
        if 't' not in event and 'frame' in event and listed.fps:
            event['t'] = float(event['frame']) / listed.fps
        span = listed.silence_span(original)
        if span is not None and listed.version == 'v1':
            event.update(scale='silence', t=span[0], t_end=span[1])
        events.append(event)
    data = dict(listed.doc) if isinstance(listed.doc, dict) else {}
    data.update(events=events, sections=listed.sections, fps=listed.fps, fps_exact=listed.fps_exact)
    return data, listed.message


def decode_audio(path, rate=RATE, channels=2, ffmpeg=None):
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('FFmpeg is required')
    command = [ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a:0',
               '-ar', str(rate), '-ac', str(channels), '-f', 'f32le', '-']
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise ValueError('cannot decode audio: ' + result.stderr.decode(errors='replace').strip()[-400:])
    values = np.frombuffer(result.stdout, dtype='<f4')
    if not len(values) or len(values) % channels or not np.isfinite(values).all():
        raise ValueError('audio is empty or invalid')
    return values.reshape(-1, channels)


def loudness(path, ffmpeg=None):
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    if not ffmpeg:
        raise ValueError('FFmpeg is required')
    command = [ffmpeg, '-hide_banner', '-nostats', '-nostdin', '-i', str(path), '-map', '0:a:0',
               '-af', 'loudnorm=I=-16:LRA=11:TP=-1:print_format=json', '-f', 'null', '-']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('loudness measurement failed: ' + result.stderr[-400:])
    matches = re.findall(r'\{[^{}]*"input_i"[^{}]*\}', result.stderr, re.DOTALL)
    if not matches:
        raise ValueError('FFmpeg did not return loudness measurements')
    data = json.loads(matches[-1])

    def value(key):
        try:
            number = float(data[key])
            return number if math.isfinite(number) else None
        except (KeyError, TypeError, ValueError):
            return None

    return {'integrated_lufs': value('input_i'), 'true_peak_dbtp': value('input_tp'),
            'lra_lu': value('input_lra')}


def spectrum(samples):
    samples = np.asarray(samples, dtype=np.float64)
    count = min(len(samples), 8192)
    if count < 128:
        return {}
    step = max(1, count // 2)
    starts = range(0, len(samples) - count + 1, step)
    power = np.zeros(count // 2 + 1, dtype=np.float64)
    for start in starts:
        segment = samples[start:start + count] * np.hanning(count)[:, None]
        power += np.sum(np.abs(np.fft.rfft(segment, axis=0)) ** 2, axis=1)
    freqs = np.fft.rfftfreq(count, 1 / RATE)
    total = float(power.sum())
    if total <= 1e-20:
        return {}
    return {key: round(10 * math.log10(max(float(power[(freqs >= lo) & (freqs < hi)].sum()) / total, 1e-12)), 2)
            for key, (lo, hi) in BANDS.items()}


def measure(path, samples=None, ffmpeg=None):
    samples = decode_audio(path, ffmpeg=ffmpeg) if samples is None else samples
    meters = loudness(path, ffmpeg=ffmpeg)
    mid = (samples[:, 0].astype(np.float64) + samples[:, 1]) / 2
    side = (samples[:, 0].astype(np.float64) - samples[:, 1]) / 2
    mid_rms = float(np.sqrt(np.mean(mid ** 2)))
    side_rms = float(np.sqrt(np.mean(side ** 2)))
    width = 20 * math.log10(side_rms / mid_rms) if mid_rms > 1e-10 and side_rms > 1e-10 else None
    corr = float(np.corrcoef(samples[:, 0], samples[:, 1])[0, 1]) if all(
        np.std(samples[:, index]) > 1e-10 for index in (0, 1)) else None
    bands = spectrum(samples)
    duration = len(samples) / RATE
    if duration < 6 or meters['integrated_lufs'] is None:
        meters['lra_lu'] = None
    return {'file': str(path), 'duration_s': duration, 'measurements': dict(meters,
            side_to_mid_db=round(width, 2) if width is not None else None,
            correlation=round(corr, 3) if corr is not None else None,
            spectrum_db=bands, sub_20_60_hz_percent=round(100 * 10 ** (bands['sub'] / 10), 3)
            if 'sub' in bands else None), 'reference': {'label': 'seven launch films (n = 7)',
            'range': '10th to 90th percentile', 'values': PROFILE},
            'limit': 'Ranges describe seven launch films and are not a score. Sub share covers 20 to 60 Hz. '
                     'Spectrum uses stereo power; the reference spectrum uses a mono mixdown.'}


def section_changes(samples):
    """Report sustained level changes of at least 8 dB."""
    channels = np.asarray(samples, dtype=np.float32)
    hop, size = 240, 480
    if len(channels) < RATE:
        return []
    padded = np.pad(channels, ((size // 2, size // 2), (0, 0)), mode='reflect')
    count = (len(padded) - size) // hop + 1
    rms = np.empty(count, dtype=np.float64)
    for start in range(0, count, 1024):
        stop = min(count, start + 1024)
        indices = np.arange(start, stop)[:, None] * hop + np.arange(size)
        rms[start:stop] = np.sqrt(np.mean(padded[indices] ** 2, axis=(1, 2)))
    db = 20 * np.log10(np.maximum(rms, 1e-5))
    width = 80
    prefix = np.r_[0., np.cumsum(np.pad(db, (width, width), mode='edge'))]
    before = (prefix[width + np.arange(count) + 1] - prefix[np.arange(count)]) / (width + 1)
    after = (prefix[2 * width + np.arange(count) + 1] - prefix[width + np.arange(count)]) / (width + 1)
    jump = after - before
    result, index = [], max(width, 100)
    while index < count - width:
        if abs(jump[index]) >= 8:
            chosen = index + int(np.argmax(np.abs(jump[index:index + width])))
            result.append({'t': chosen * hop / RATE, 'change_db': round(float(jump[chosen]), 2),
                           'method': '400 ms mean log RMS before and after'})
            index = chosen + width
        else:
            index += 1
    return result


def transcript(path, detail='normal'):
    samples = decode_audio(path)
    tempo = sibling('tempo_map')
    channels = decode_audio(path, rate=tempo.RATE, channels=2)
    detected = []
    for channel in range(channels.shape[1]):
        times, weights, _, _ = tempo.attacks(channels[:, channel])
        detected.extend((float(t), float(weight)) for t, weight in zip(times, weights))
    kept = []
    for time, weight in sorted(detected, key=lambda pair: pair[1], reverse=True):
        if all(abs(time - other[0]) > .045 for other in kept):
            kept.append((time, weight))
    mono = np.mean(channels, axis=1)
    channel_power = np.mean(channels.astype(np.float64) ** 2, axis=0)
    mono_power = float(np.mean(mono.astype(np.float64) ** 2))
    if mono_power < .25 * float(np.mean(channel_power)):
        choice = int(np.argmax(channel_power))
        mono = channels[:, choice]
        beat_signal = ('left' if choice == 0 else 'right') + ' channel; mono mix cancels'
    else:
        beat_signal = 'mono mix'
    grid, grid_code = tempo.analyse(mono)
    return {'file': str(path), 'duration_s': len(samples) / RATE, 'detail': detail,
            'events': [{'t': round(t, 3), 'strength': round(weight, 3), 'kind': 'onset'}
                       for t, weight in sorted(kept)], 'sections': section_changes(samples),
            'beat_grid': grid, 'beat_grid_status': 'measured' if grid_code == 0 else 'inconclusive',
            'beat_grid_signal': beat_signal,
            'detail_scope': 'Timing measurements do not vary with --detail. Model tags are not included.',
            'picture_sync': 'not assessed: no picture or cue list supplied',
            'limit': 'Events are measured onsets, not identified sounds. A person must listen.'}


def sheet(path, out, cues=None):
    """Draw one time-aligned PNG of the sound, its measured events and optional cues."""
    from PIL import Image, ImageDraw, ImageFont
    project = sibling('project')
    project.refuse_overwriting_inputs([out], [path, cues, __file__], guard_versions=True)
    destination = Path(out)
    if destination.suffix.lower() != '.png':
        raise ValueError('sheet output must be a PNG')
    if destination.exists():
        raise ValueError('sheet output already exists; choose a new path')
    data, freshness = load_cues(cues) if cues else ({'events': []}, 'no cue list')
    samples = decode_audio(path)
    timeline = transcript(path)
    duration = len(samples) / RATE
    width, height, left, right = 1600, 760, 110, 1550
    panel = Image.new('RGB', (width, height), '#f8f8f5')
    draw = ImageDraw.Draw(panel)
    try:
        font = ImageFont.truetype('DejaVuSans.ttf', 16)
        title = ImageFont.truetype('DejaVuSans.ttf', 22)
    except OSError:
        font = title = ImageFont.load_default()

    def x(t):
        return int(left + (right - left) * min(1.0, max(0.0, t / max(duration, 1e-9))))

    draw.text((left, 18), 'Sound sheet: ' + Path(path).name, fill='#18232b', font=title)
    draw.text((left, 52), f'{duration:.2f} s  |  {len(timeline["events"])} onsets  |  '
              'Measurements only. A person must listen.', fill='#42545d', font=font)
    lanes = [('events', 100, 150), ('spectrum', 175, 420), ('waveform', 445, 555),
             ('sections', 580, 630), ('beats / cues', 655, 705)]
    for label, top, bottom in lanes:
        draw.text((8, top + 8), label, fill='#34444b', font=font)
        draw.rectangle((left, top, right, bottom), outline='#aebac0', width=1)
    for event in timeline['events']:
        xx = x(event['t'])
        draw.line((xx, 112, xx, 145), fill='#df6d35', width=2)
    draw.text((left + 8, 103), 'orange: measured onset', fill='#6c4d3b', font=font)

    # Average stereo power in short Hann windows. Opposite-phase channels do not cancel.
    columns, fft_size = right - left, 2048
    centers = np.linspace(0, max(0, len(samples) - 1), columns, dtype=int)
    padded = np.pad(samples, ((fft_size // 2, fft_size // 2), (0, 0)))
    window = np.hanning(fft_size).astype(np.float32)
    frequencies = np.fft.rfftfreq(fft_size, 1 / RATE)
    bins = np.clip(np.searchsorted(frequencies, np.geomspace(30, 16000, 245)), 0, len(frequencies) - 1)
    levels = np.empty((len(bins), columns), dtype=np.float32)
    for start in range(0, columns, 64):
        points = centers[start:start + 64, None] + np.arange(fft_size)[None, :]
        powers = np.sum(np.abs(np.fft.rfft(padded[points] * window[None, :, None], axis=1)) ** 2, axis=2)
        levels[:, start:start + len(points)] = (10 * np.log10(np.maximum(powers[:, bins], 1e-12))).T
    maximum = max(float(np.max(levels)), -40.0)
    intensity = np.clip((levels - maximum + 75) / 75, 0, 1)
    image = np.zeros((*intensity.shape, 3), dtype=np.uint8)
    image[:, :, 0] = (255 * np.clip(intensity * 1.7, 0, 1)).astype(np.uint8)
    image[:, :, 1] = (220 * np.clip((intensity - .3) * 1.7, 0, 1)).astype(np.uint8)
    image[:, :, 2] = (130 * np.clip((intensity - .65) * 2.8, 0, 1)).astype(np.uint8)
    panel.paste(Image.fromarray(np.flipud(image), 'RGB'), (left, 175))
    draw = ImageDraw.Draw(panel)
    power = np.max(np.abs(samples), axis=1)
    indices = np.linspace(0, len(power), columns + 1).astype(int)
    for col in range(columns):
        lo, hi = indices[col], max(indices[col] + 1, indices[col + 1])
        peak = min(1.0, float(np.max(power[lo:hi]))) if lo < len(power) else 0.0
        half = int(48 * peak)
        draw.line((left + col, 500 - half, left + col, 500 + half), fill='#345c80')
    for section in timeline['sections']:
        xx = x(section['t'])
        draw.line((xx, 590, xx, 625), fill='#ad4840', width=2)
    grid = timeline.get('beat_grid') or {}
    for beat in grid.get('downbeats') or []:
        if isinstance(beat, (int, float)) and 0 <= beat <= duration:
            xx = x(beat)
            draw.line((xx, 660, xx, 677), fill='#34444b', width=2)
    for event in data.get('events') or []:
        t = event.get('t')
        if isinstance(t, (int, float)) and 0 <= t <= duration:
            xx = x(t)
            draw.polygon(((xx - 5, 685), (xx + 5, 685), (xx, 697)), fill='#316a62')
    for tick in range(0, 7):
        t = duration * tick / 6
        xx = x(t)
        draw.line((xx, 706, xx, 712), fill='#34444b')
        draw.text((xx - 12, 716), f'{t:.1f}s', fill='#34444b', font=font)
    draw.text((left, 737), 'Green: cues; dark ticks: candidate downbeats. ' + freshness,
              fill='#42545d', font=font)
    destination.parent.mkdir(parents=True, exist_ok=True)
    panel.save(destination, format='PNG')
    return {'png': str(destination.resolve()), 'duration_s': duration, 'events': len(timeline['events']),
            'cues': len(data.get('events') or []), 'cue_freshness': freshness,
            'limit': 'A visual screen; sound remains unheard.'}


def require_model_memory(probe=None):
    """Refuse a model load unless at least 3 GiB of free memory is known to be available."""
    free = (probe or sibling('setup').free_memory)()
    if free is None or free < 3 * 1024 ** 3:
        found = 'unknown' if free is None else f'{free / 1024 ** 3:.2f} GiB'
        raise ValueError(f'listening models need at least 3 GiB free; available memory is {found}')


LABEL_PROMPTS = ('a fast air whoosh', 'a rising sweep', 'a cinematic impact', 'a keyboard typing',
                 'a mouse click', 'a notification beep', 'footsteps', 'paper rustling',
                 'a musical note', 'drums', 'a person speaking', 'ambient background sound')


def mono_for_labels(samples):
    """Use one channel when a mono fold would cancel audible stereo."""
    samples = np.asarray(samples, dtype=np.float32)
    mono = samples.mean(axis=1)
    channel_power = np.mean(samples.astype(np.float64) ** 2, axis=0)
    if float(np.mean(mono.astype(np.float64) ** 2)) < .25 * float(np.mean(channel_power)):
        mono = samples[:, int(np.argmax(channel_power))]
    return mono


def label_excerpt(samples, rate, time):
    lo = max(0, round((time - .15) * rate))
    hi = min(len(samples), round((time + 1.0) * rate))
    result = samples[lo:hi]
    return np.pad(result, (0, max(0, round(.1 * rate) - len(result))))


def clap_hints(samples, events, cache):
    """Rank a small vocabulary locally. Cosines are hints, not probabilities."""
    import torch
    from transformers import ClapModel, ClapProcessor
    torch.set_num_threads(2)
    model_id = sibling('setup').EAR_MODELS[0]
    model = ClapModel.from_pretrained(model_id, cache_dir=str(cache), local_files_only=True).eval()
    processor = ClapProcessor.from_pretrained(model_id, cache_dir=str(cache), local_files_only=True)
    texts = processor(text=list(LABEL_PROMPTS), return_tensors='pt', padding=True)
    with torch.inference_mode():
        vectors = model.get_text_features(**texts)
        vectors = getattr(vectors, 'pooler_output', vectors)
        vectors = torch.nn.functional.normalize(vectors.float(), dim=-1)
        result = []
        for event in events:
            segment = label_excerpt(samples, RATE, event['t'])
            inputs = processor(audio=segment, sampling_rate=RATE, return_tensors='pt')
            audio = model.get_audio_features(**inputs)
            audio = getattr(audio, 'pooler_output', audio)
            scores = (torch.nn.functional.normalize(audio.float(), dim=-1) @ vectors.T)[0]
            order = torch.argsort(scores, descending=True)[:3].tolist()
            result.append([{'label': LABEL_PROMPTS[i], 'cosine': round(float(scores[i]), 4)} for i in order])
    return result


def ast_hints(samples, events, cache):
    """Return local AudioSet class scores as hints."""
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification
    torch.set_num_threads(2)
    model_id = sibling('setup').EAR_MODELS[1]
    model = ASTForAudioClassification.from_pretrained(model_id, cache_dir=str(cache), local_files_only=True).eval()
    extractor = ASTFeatureExtractor.from_pretrained(model_id, cache_dir=str(cache), local_files_only=True)
    result = []
    with torch.inference_mode():
        for event in events:
            segment = label_excerpt(samples, 16000, event['t'])
            inputs = extractor(segment, sampling_rate=16000, return_tensors='pt')
            scores = torch.sigmoid(model(**inputs).logits.float())[0]
            order = torch.argsort(scores, descending=True)[:3].tolist()
            result.append([{'label': model.config.id2label[i], 'score': round(float(scores[i]), 4)} for i in order])
    return result


def labels(path, events_path=None):
    """Label transcript events with local-only CLAP and AST models."""
    import gc
    setup = sibling('setup')
    install = 'python ' + str(HERE / 'setup.py') + ' --install ear'
    if not all(importlib.util.find_spec(name) is not None for name in ('torch', 'transformers')) \
            or len(setup.ear_models_cached()) != len(setup.EAR_MODELS):
        raise ValueError('local listening packages or weights are missing; run ' + install)
    require_model_memory(setup.free_memory)
    lock = sibling('with_lock')
    try:
        with lock.HeavyLock(label='listen-labels', say=lambda *a, **kw: print(*a, file=sys.stderr, **kw)):
            require_model_memory(setup.free_memory)
            if events_path:
                raw = json.loads(Path(events_path).read_text(encoding='utf-8'))
                if not isinstance(raw, dict) or not isinstance(raw.get('events'), list):
                    raise ValueError('--events needs a listen transcript with an events list')
                stated = raw.get('file')
                if stated and not sibling('project').same_file(stated, path):
                    raise ValueError('the event transcript names a different file')
                events, binding = raw['events'], 'path only; transcript bytes are not bound to media'
            else:
                events, binding = transcript(path)['events'], 'measured from this file'
            samples = mono_for_labels(decode_audio(path))
            duration = len(samples) / RATE
            for event in events:
                t = event.get('t') if isinstance(event, dict) else None
                if not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 <= t <= duration:
                    raise ValueError('each event needs a finite time within the sound')
            if not events:
                return {'file': str(path), 'events': [], 'events_binding': binding,
                        'limit': 'No events to label. A person must listen.'}
            clap = clap_hints(samples, events, setup.ear_cache())
            del samples
            gc.collect()
            require_model_memory(setup.free_memory)
            samples = mono_for_labels(decode_audio(path, rate=16000))
            ast = ast_hints(samples, events, setup.ear_cache())
            return {'file': str(path), 'events_binding': binding,
                    'events': [dict(event, clap_hints=c, ast_hints=a) for event, c, a in zip(events, clap, ast)],
                    'models': list(setup.EAR_MODELS),
                    'limit': 'CLAP cosines and AST scores are local model hints, not sound identification. '
                             'A person must listen.'}
    except lock.LockTimeout as error:
        raise ValueError('listening model lock: ' + str(error)) from None
    except (ImportError, OSError) as error:
        raise ValueError('local listening models could not load: ' + str(error) + '; run ' + install) from None


def audio_activity(samples):
    """Measure 5 ms spectral flux in the full mix and three frequency bands."""
    channels = np.asarray(samples, dtype=np.float32)
    fft_size, hop = 1024, 240
    if len(channels) < fft_size:
        raise ValueError('audio is too short to measure activity')
    padded = np.pad(channels, ((fft_size // 2, fft_size // 2), (0, 0)), mode='reflect')
    count = (len(padded) - fft_size) // hop + 1
    window = np.hanning(fft_size).astype(np.float32)
    frequencies = np.fft.rfftfreq(fft_size, 1 / RATE)
    maximum = 0.0
    for start in range(0, count, 512):
        indices = np.arange(start, min(count, start + 512))[:, None] * hop + np.arange(fft_size)
        spectrum = np.fft.rfft(padded[indices] * window[None, :, None], axis=1)
        magnitude = np.sqrt(np.mean(np.abs(spectrum) ** 2, axis=2))
        maximum = max(maximum, float(np.max(magnitude)))
    if maximum <= 1e-12:
        return {'times': np.arange(count) * hop / RATE, 'coverage_end_s': len(channels) / RATE,
                'bands': {name: np.zeros(count) for name in ('all', 'low', 'mid', 'high')}}
    band_freqs = {'low': (30, 200), 'mid': (200, 2000), 'high': (2000, 16000)}
    flux = {name: np.zeros(count, dtype=np.float32) for name in ('all', 'low', 'mid', 'high')}
    previous = None
    for start in range(0, count, 512):
        stop = min(count, start + 512)
        indices = np.arange(start, stop)[:, None] * hop + np.arange(fft_size)
        spectrum = np.fft.rfft(padded[indices] * window[None, :, None], axis=1)
        magnitude = np.sqrt(np.mean(np.abs(spectrum) ** 2, axis=2))
        logarithm = np.log1p(100 * magnitude / maximum)
        first = logarithm[:1] if previous is None else previous[None, :]
        change = np.maximum(0, logarithm - np.vstack((first, logarithm[:-1])))
        flux['all'][start:stop] = change.sum(axis=1)
        for name, (low, high) in band_freqs.items():
            flux[name][start:stop] = change[:, (frequencies >= low) & (frequencies < high)].sum(axis=1)
        previous = logarithm[-1]
    rms_pad = np.pad(channels, ((240, 240), (0, 0)), mode='reflect')
    rms_count = (len(rms_pad) - 480) // hop + 1
    count = min(count, rms_count)
    rms = np.empty(count, dtype=np.float32)
    for start in range(0, count, 1024):
        stop = min(count, start + 1024)
        indices = np.arange(start, stop)[:, None] * hop + np.arange(480)
        rms[start:stop] = np.sqrt(np.mean(rms_pad[indices] ** 2, axis=(1, 2)))
    levels = 20 * np.log10(np.maximum(rms, 10 ** (-55 / 20)))
    rise = np.zeros(count, dtype=np.float32)
    rise[2:] = np.maximum(0, levels[2:] - levels[:-2])
    full = flux['all'][:count]
    flux['all'] = full / max(float(np.percentile(full, 99.5)), 1e-12) + \
        rise / max(float(np.percentile(rise, 99.5)), 1e-12)
    return {'times': np.arange(count) * hop / RATE, 'coverage_end_s': len(channels) / RATE,
            'bands': {name: values[:count] for name, values in flux.items()}}


def moving_mean(values, radius=5):
    padded = np.pad(values, (radius, radius), mode='edge')
    total = np.r_[0., np.cumsum(padded, dtype=np.float64)]
    width = 2 * radius + 1
    return (total[width:] - total[:-width]) / width


def remove_cuts(motion, scene):
    """Replace cut frames and their successors with nearby motion medians."""
    original = np.asarray(motion, dtype=float)
    cleaned = original.copy()
    for index in np.flatnonzero(np.asarray(scene) > .3):
        for j in (index, index + 1):
            if j >= len(cleaned):
                continue
            left, right = max(0, j - 4), min(len(cleaned), j + 5)
            neighbors = [original[k] for k in range(left, right) if k not in (index, index + 1)]
            if neighbors:
                cleaned[j] = float(np.median(neighbors))
    return cleaned


def frame_screens(times, differences, events):
    """Screen for a frame change at turns and contacts, not its meaning."""
    times = np.asarray(times, dtype=float)
    differences = np.asarray(differences, dtype=float)
    if len(times) != len(differences):
        raise ValueError('frame times and differences do not match')
    rows = []
    for event in events:
        scale = event.get('scale', 'contact')
        if scale not in ('contact', 'turn'):
            continue
        at = float(event['t'])
        row = {'id': event.get('id'), 't': at, 'scale': scale}
        picture = event.get('picture')
        if picture in ('none', 'held'):
            row.update(state='skipped', reason='picture: ' + picture)
        elif len(times) < 2 or at < times[0] or at > times[-1]:
            row.update(state='not assessed', reason='cue is outside measured picture')
        else:
            near = int(np.argmin(np.abs(times - at)))
            first, last = max(1, near - 1), min(len(times), near + 2)
            window = differences[(times >= at - .5) & (times <= at + .5)]
            if first >= last or not len(window):
                row.update(state='not assessed', reason='no neighbouring frames')
            else:
                index = first + int(np.argmax(differences[first:last]))
                change, median = float(differences[index]), float(np.median(window))
                row.update(state='change' if change > 3 * median and change > 0 else 'look',
                           observed_t=float(times[index]), difference=change, surrounding_median=median,
                           threshold=3 * median)
        rows.append(row)
    return rows


def picture_candidates(picture):
    """Propose unconfirmed picture changes from measured frame differences."""
    times = np.asarray(picture['times'], dtype=float)
    values = np.asarray(picture['differences'], dtype=float)
    if len(values) < 3 or len(times) != len(values):
        return []
    grid = np.asarray(picture.get('grid', values[:, None]), dtype=float)
    if grid.ndim != 2 or len(grid) != len(values):
        raise ValueError('picture grid and frame times do not match')
    fps = 1 / float(np.median(np.diff(times)))
    activity = np.max(grid, axis=1)
    lookback = max(1, round(.1 * fps))
    flux = np.zeros(len(activity))
    for index in range(1, len(activity)):
        flux[index] = max(0, activity[index] - float(np.mean(activity[max(0, index - lookback):index])))
    normal = (flux - flux.min()) / (np.ptp(flux) + 1e-12)
    peak_radius, mean_radius = max(1, round(.06 * fps)), max(1, round(.15 * fps))
    wait = max(1, round(.08 * fps))
    indices, previous = {}, -wait
    for index, value in enumerate(normal):
        maximum = np.max(normal[max(0, index - peak_radius):min(len(normal), index + peak_radius + 1)])
        average = np.mean(normal[max(0, index - mean_radius):min(len(normal), index + mean_radius + 1)])
        if value > 0 and value == maximum and value >= average + .07 and index - previous >= wait:
            indices[index] = 'motion'
            previous = index
    scene = np.asarray(picture.get('scene', np.zeros(len(values))), dtype=float)
    for index in np.flatnonzero(scene > .3):
        left, right = max(0, index - 1), min(len(scene), index + 2)
        index = left + int(np.argmax(scene[left:right]))
        for near in [near for near in indices if abs(near - index) <= 1]:
            del indices[near]
        indices[index] = 'cut candidate'
    return [{'t': float(times[index]), 'difference': float(values[index]), 'kind': indices[index],
             'state': 'unconfirmed'} for index in sorted(indices)]


def coincidence(first, second, tolerance, duration, seed=0, iterations=200):
    """Compare event coincidence with circularly shifted event times."""
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    if not all(math.isfinite(x) for x in (tolerance, duration)) or tolerance <= 0 or duration <= 0 or \
            seed < 0 or iterations < 1 or not np.isfinite(first).all() or not np.isfinite(second).all():
        raise ValueError('invalid coincidence inputs')
    result = {'n': len(first), 'seed': seed, 'iterations': iterations, 'tolerance_s': tolerance}
    if len(first) == 0 or len(second) == 0 or duration <= 2:
        return dict(result, state='inconclusive', reason='too few events or duration for a shift null')

    def fraction(a, b):
        b = np.sort(b)
        position = np.searchsorted(b, a)
        left = b[np.clip(position - 1, 0, len(b) - 1)]
        right = b[np.clip(position, 0, len(b) - 1)]
        return float(np.mean(np.minimum(np.abs(a - left), np.abs(a - right)) <= tolerance))

    observed = fraction(first, second)
    random = np.random.default_rng(seed)
    null = [fraction(first, (second + shift) % duration)
            for shift in random.uniform(1, duration - 1, iterations)]
    p95 = float(np.percentile(null, 95))
    return dict(result, state='above shifted chance' if observed > p95 else 'not distinguishable',
                observed=round(observed, 4), chance_mean=round(float(np.mean(null)), 4),
                chance_p95=round(p95, 4), spread=[round(float(min(null)), 4), round(float(max(null)), 4)],
                limit='Event coincidence does not identify the intended picture change or sound.')


def picture_alignment(events, picture, offset=0):
    """Locate measured audio onsets relative to unconfirmed picture candidates."""
    candidates = picture_candidates(picture)
    rows = []
    for event in events:
        at = float(event['t']) + offset
        if not candidates:
            rows.append({'audio_t': float(event['t']), 'picture_t': None, 'offset_ms': None,
                         'state': 'not assessed'})
            continue
        closest = min(candidates, key=lambda candidate: abs(candidate['t'] - at))
        rows.append({'audio_t': float(event['t']), 'picture_t': closest['t'],
                     'offset_ms': round((at - closest['t']) * 1000, 2), 'state': 'candidate'})
    duration = float(picture.get('coverage_end_s', picture['times'][-1])) if len(picture['times']) else 0
    valid = [float(event['t']) + offset for event in events if 0 <= float(event['t']) + offset <= duration]
    frame = float(np.median(np.diff(picture['times']))) if len(picture['times']) > 1 else None
    chance = coincidence(valid, [candidate['t'] for candidate in candidates], frame, duration) \
        if frame and duration > 0 else {'state': 'inconclusive', 'reason': 'picture timing unavailable'}
    return {'state': 'measured' if candidates else 'not assessed', 'events': rows, 'candidates': candidates,
            'coincidence': chance,
            'time_map': f'picture time = audio time + {offset:g} s',
            'limit': 'Frame-difference candidates are not confirmed cuts or intended picture events.'}


def has_video(path):
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ValueError('ffprobe is required')
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=index',
                             '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('cannot inspect video streams: ' + result.stderr[-300:])
    return bool(result.stdout.strip())


def audio_origin(path):
    """Return the first audio stream's container start when it is recorded."""
    command = [shutil.which('ffprobe'), '-v', 'error', '-select_streams', 'a:0', '-show_entries',
               'stream=start_time', '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        value = float(json.loads(result.stdout)['streams'][0]['start_time'])
        return value if result.returncode == 0 and math.isfinite(value) else None
    except (ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None


def video_activity(path):
    """Read decoded frame differences on their presentation clock."""
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('FFmpeg and ffprobe are required for picture measurements')
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_frames', '-show_entries',
               'frame=best_effort_timestamp_time,duration_time,pkt_duration_time', '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('cannot probe picture timestamps: ' + result.stderr[-300:])
    frames = json.loads(result.stdout).get('frames', [])
    try:
        pts = np.array([float(frame['best_effort_timestamp_time']) for frame in frames], dtype=float)
    except (KeyError, ValueError, TypeError):
        raise ValueError('picture frame timestamps are unavailable') from None
    if len(pts) < 2 or not np.isfinite(pts).all() or np.any(np.diff(pts) <= 0):
        raise ValueError('picture presentation timestamps are incomplete or non-monotonic')
    command = [ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:v:0',
               '-vf', 'scale=96:64:flags=area,format=gray', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    previous, differences, grids = None, [], []
    frame_size = 96 * 64
    while True:
        data = bytearray()
        while len(data) < frame_size:
            part = process.stdout.read(frame_size - len(data))
            if not part:
                break
            data.extend(part)
        if not data:
            break
        if len(data) != frame_size:
            process.stdout.close()
            process.wait()
            raise ValueError('picture decode ended in a partial frame')
        frame = np.frombuffer(data, dtype=np.uint8).astype(np.int16).reshape(64, 96)
        delta = np.abs(frame - previous) / 255 if previous is not None else np.zeros((64, 96))
        differences.append(float(np.mean(delta)))
        grids.append(delta.reshape(4, 16, 4, 24).mean(axis=(1, 3)).reshape(16))
        previous = frame
    error = process.stderr.read().decode(errors='replace').strip()
    code = process.wait()
    if code or len(differences) != len(pts):
        raise ValueError(f'picture decode did not match its presentation timestamps: {error[-200:]}')
    differences = np.asarray(differences)
    tail = frames[-1].get('duration_time', frames[-1].get('pkt_duration_time'))
    try:
        tail = float(tail)
        if not math.isfinite(tail) or tail <= 0:
            raise ValueError
    except (ValueError, TypeError):
        tail = 0.0
    return {'times': pts - pts[0], 'origin_s': float(pts[0]), 'coverage_end_s': float(pts[-1] - pts[0] + tail),
            'differences': differences, 'grid': np.asarray(grids),
            'scene': differences, 'method': '96x64 grey frame differences; scene proxy at 0.3'}


def span_measurements(events, picture, activity, offset=0, seed=0, iterations=200):
    """Measure follow spans on the shared picture clock."""
    rows = []
    for event in events:
        if event.get('scale') != 'follow':
            continue
        start, end = float(event['t']), float(event.get('t_end', event['t']))
        row = {'id': event.get('id'), 'start_s': start, 'end_s': end, 'state': 'inconclusive',
               'n': 0, 'seed': seed, 'null_iterations': iterations, 'null_spread': None,
               'null_note': 'Uncalibrated circular-shift null; screening only.'}
        if end - start < 2:
            row.update(state='not assessed', reason=SHORT_SPAN + f' ({end - start:.2f} s); the follow screen needs 2 s '
                       'of picture and sound, so judge this span by the frame change at its cues and by listening')
        elif picture is None or activity is None:
            row.update(reason='picture or audio unavailable')
        elif (start < picture['times'][0] or end > picture.get('coverage_end_s', picture['times'][-1]) or
              start - offset < activity['times'][0] or end - offset > activity.get('coverage_end_s', activity['times'][-1])):
            row.update(reason='span extends beyond measured picture or audio')
        else:
            grid = np.arange(start, end, .05)
            motion = remove_cuts(picture['differences'], picture['scene'])
            motion = np.interp(grid, picture['times'], motion)
            bands = {name: np.interp(grid - offset, activity['times'], moving_mean(values))
                     for name, values in activity['bands'].items()}
            row.update(follow_coupling(motion, bands, seed=seed, iterations=iterations))
        rows.append(row)
    return rows


def has_audio(path):
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ValueError('ffprobe is required')
    result = subprocess.run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=index',
                             '-of', 'csv=p=0', str(path)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('cannot inspect audio streams: ' + result.stderr[-300:])
    return bool(result.stdout.strip())


def sync_measure(audio, cues, spec, video=None, offset=None, iterations=200, seed=0, candidates=False,
                 source_kind=None, owner=None):
    """Measure picture changes and sound; a cue list is optional for discovery."""
    if iterations < 1 or seed < 0 or (offset is not None and not math.isfinite(offset)):
        raise ValueError('null iterations must be positive, seed nonnegative and offset finite')
    events = spec.get('events', [])
    if not isinstance(events, list):
        raise ValueError('cue events are not a list')
    if not Path(audio).is_file() or (video is not None and not Path(video).is_file()):
        raise ValueError('audio or picture file does not exist')
    picture_path = video or (audio if has_video(audio) else None)
    picture = video_activity(picture_path) if picture_path else None
    if offset is not None:
        time_offset, map_note = offset, 'supplied'
    elif video:
        time_offset, map_note = 0.0, 'assumed zero for separate audio'
    elif picture:
        origin = audio_origin(audio)
        time_offset, map_note = (origin - picture['origin_s'], 'container start times') if origin is not None \
            else (None, 'audio start time unknown')
    else:
        time_offset, map_note = 0.0, 'no picture supplied'
    audio_available = has_audio(audio)
    role = 'picture only; no audio stream' if not audio_available else \
        ('full mix' if source_kind == 'full-mix' else source_kind) if source_kind else \
        'full mix' if picture_path and Path(audio).resolve() == Path(picture_path).resolve() else \
        'separate audio; stem or full mix unconfirmed'
    measured = {'audio': str(audio), 'picture': str(picture_path) if picture_path else None,
                'source': role, 'audio_to_picture_offset_s': time_offset, 'time_map': map_note,
                'frame_change_at_cue': {'state': 'not assessed', 'rows': [],
                                        'limit': 'A detected change does not identify its intended meaning.'},
                'sound_follows_list': {'state': 'not assessed', 'rows': []}, 'turn_leads': [],
                'follow': [], 'silence': [], 'seed': seed, 'null_iterations': iterations}
    if picture is not None:
        rows = frame_screens(picture['times'], picture['differences'], events)
        measured['frame_change_at_cue'].update(state='measured' if rows else 'not assessed', rows=rows, n=len(rows))
        if candidates:
            measured['candidates'] = picture_candidates(picture)
    elif candidates:
        measured['candidates'] = []
    samples = None
    activity = None
    if audio_available:
        samples = decode_audio(audio)
        activity = audio_activity(samples) if len(samples) >= 1024 else None
    if cues is None:
        measured['sound_follows_list']['reason'] = 'no cue list supplied'
    elif samples is not None and time_offset is not None:
        with tempfile.TemporaryDirectory(prefix='lf-listen-sync-') as directory:
            output = Path(directory) / 'onsets.json'
            command = [sys.executable, '-I', str(HERE / 'cue_onsets.py'), str(audio), str(cues),
                       '--scale', 'all', '--chance', str(iterations), '--seed', str(seed),
                       '--offset', str(time_offset), '--json', str(output)]
            if owner is not None:
                command += ['--owner', str(owner)]
            run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
            report = json.loads(output.read_text(encoding='utf-8')) if output.is_file() else None
        if run.returncode in (0, 1) and isinstance(report, dict):
            chance = report.get('summary', {}).get('chance', {})
            state = 'inconclusive' if str(chance.get('verdict', '')).startswith(('inconclusive', 'not run')) \
                else 'measured' if report.get('summary', {}).get('hit_rate') is not None else 'not assessed'
            measured['sound_follows_list'] = {'state': state, 'rows': report.get('rows', []),
                                              'summary': report.get('summary', {}),
                                              'limit': report.get('limit')}
            measured['turn_leads'] = [{'id': row.get('id'), 'declared_ms': row.get('lead_ms', 0),
                                       'measured_ms': round((row['onset_s'] + time_offset - row['picture_t']) * 1000, 2),
                                       'residual_ms': row.get('offset_ms'), 'status': row.get('status')}
                                      for row in report.get('rows', [])
                                      if row.get('scale') == 'turn' and 'lead_ms' in row and
                                      'picture_t' in row and 'onset_s' in row]
        else:
            measured['sound_follows_list']['reason'] = 'cue_onsets could not assess: ' + (run.stderr or run.stdout)[-400:]
    if time_offset is None:
        measured['follow'] = [{'id': event.get('id'), 'verdict': 'inconclusive', 'reason': map_note}
                              for event in events if event.get('scale') == 'follow']
    else:
        measured['follow'] = span_measurements(events, picture, activity, time_offset, seed, iterations)
    for event in events:
        if event.get('scale') != 'silence':
            continue
        start = float(event['t'])
        end = float(event.get('t_end', start))
        row = {'id': event.get('id'), 'start_s': start, 'end_s': end, 'scope': event.get('scope')}
        if samples is None or time_offset is None or start - time_offset < 0 or end - time_offset > len(samples) / RATE:
            row.update(state='inconclusive', reason='audio does not cover the span')
        else:
            segment = samples[round((start - time_offset) * RATE):round((end - time_offset) * RATE)]
            if len(segment):
                rms = float(np.sqrt(np.mean(segment.astype(np.float64) ** 2)))
                row.update(state='measured', rms_dbfs=20 * math.log10(max(rms, 1e-8)),
                           limit='Full audio level does not prove which bus or tail was silent.')
            else:
                row.update(state='inconclusive', reason='empty span')
        measured['silence'].append(row)
    return measured


def smooth(values, count):
    weights = np.hanning(count + 2)[1:-1]
    return np.convolve(values, weights / weights.sum(), mode='same')


def correlation(a, b, lag):
    if lag > 0:
        a, b = a[:-lag], b[lag:]
    elif lag < 0:
        a, b = a[-lag:], b[:lag]
    if len(a) < 3:
        return None
    a, b = a - np.mean(a), b - np.mean(b)
    denominator = math.sqrt(float(np.dot(a, a) * np.dot(b, b)))
    return float(np.dot(a, b) / denominator) if denominator > 1e-20 else None


def periodic(values, minimum_lag):
    """Return true when an almost exact repeat makes circular shifts uninformative."""
    scale = float(np.std(values))
    if scale < 1e-10:
        return False
    for lag in range(minimum_lag, len(values) // 2 + 1):
        r = correlation(values, values, lag)
        difference = float(np.sqrt(np.mean((values[:-lag] - values[lag:]) ** 2)))
        if r is not None and r >= 0.98 and difference <= .2 * scale:
            return True
    return False


def follow_coupling(motion, bands, step=0.05, seed=0, iterations=200):
    """Search the same bands and lags in the observation and each circular shift."""
    result = {'state': 'inconclusive', 'n': len(motion), 'seed': seed,
              'null_iterations': iterations, 'step_s': step, 'null_spread': None,
              'null_note': 'Uncalibrated circular-shift null; screening only.'}
    if not math.isfinite(step) or step <= 0 or iterations < 1:
        raise ValueError('step and null iterations must be positive')
    motion = np.asarray(motion, dtype=float)
    if len(motion) * step < 2:
        result.update(state='not assessed', reason=SHORT_SPAN)
        return result
    if not np.all(np.isfinite(motion)) or np.std(motion) < 1e-10:
        result['reason'] = 'missing or constant picture motion'
        return result
    count = max(1, round(.25 / step))
    motion = smooth(motion, count)
    periodic_lag = max(2, round(1 / step))
    if periodic(motion, periodic_lag):
        result['reason'] = 'periodic picture motion'
        return result
    usable = {}
    for name, values in bands.items():
        values = np.asarray(values, dtype=float)
        if len(values) == len(motion) and np.all(np.isfinite(values)) and np.std(values) >= 1e-10:
            values = smooth(values, count)
            if not periodic(values, periodic_lag):
                usable[name] = values
    if not usable:
        result['reason'] = 'missing, constant or periodic audio activity'
        return result
    maxlag = round(.5 / step)
    lags = range(-maxlag, maxlag + 1)
    minshift = min(round(2 / step), max(maxlag + count + 1, len(motion) // 4))
    shifts = np.arange(minshift, len(motion) - minshift + 1)
    if not len(shifts):
        result['reason'] = 'span has no independent circular shift'
        return result

    def best_for(shift):
        candidates = []
        for name, values in usable.items():
            shifted = np.roll(values, shift) if shift else values
            for lag in lags:
                value = correlation(motion, shifted, lag)
                if value is not None:
                    candidates.append((value, name, lag))
        return max(candidates) if candidates else None

    observed = best_for(0)
    if observed is None:
        result['reason'] = 'no finite correlations'
        return result
    rng = np.random.default_rng(seed)
    scores = [best_for(int(shift))[0] for shift in rng.choice(shifts, size=iterations, replace=True)]
    p95 = float(np.percentile(scores, 95))
    result.update(state='screening',
                  best_r=round(observed[0], 4), band=observed[1], lag_s=round(observed[2] * step, 4),
                  null_p95=round(p95, 4), null_mean=round(float(np.mean(scores)), 4),
                  null_spread=[round(float(np.min(scores)), 4), round(float(np.max(scores)), 4)],
                  bands=list(usable), lag_range_s=[-.5, .5], smoothing_s=.25,
                  limit='Correlation describes activity, not sound quality or a listener\'s experience. '
                        'The shifted null can be anti-conservative on short nonstationary signals.')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    meter = sub.add_parser('measure', help='measure loudness, spectrum and width')
    meter.add_argument('file')
    meter.add_argument('--json', action='store_true')
    words = sub.add_parser('transcript', help='list measured sound events and level changes')
    words.add_argument('file')
    words.add_argument('--cues')
    words.add_argument('--owner', help='page, picture or version whose identity the cue list describes')
    words.add_argument('--video')
    words.add_argument('--detail', choices=('low', 'normal', 'high'), default='normal',
                       help='timing measurements are the same at each setting; model tags are not included')
    words.add_argument('--json', action='store_true')
    picture = sub.add_parser('sheet', help='write an annotated sound sheet PNG')
    picture.add_argument('file')
    picture.add_argument('--out', required=True)
    picture.add_argument('--cues')
    picture.add_argument('--json', action='store_true')
    tags = sub.add_parser('labels', help='label measured events with local models as hints')
    tags.add_argument('file')
    tags.add_argument('--events', help='a listen.py transcript JSON')
    tags.add_argument('--json', action='store_true')
    sync = sub.add_parser('sync', help='compare picture and sound with the cue list')
    sync.add_argument('file')
    sync.add_argument('--cues', help='required unless --candidates is given')
    sync.add_argument('--owner', help='page, picture or version whose identity the cue list describes')
    sync.add_argument('--video')
    sync.add_argument('--offset', type=float, help='picture time = audio time + this offset')
    sync.add_argument('--null', type=int, default=200, help='number of circular shifts')
    sync.add_argument('--seed', type=int, default=0)
    sync.add_argument('--candidates', action='store_true')
    sync.add_argument('--source-kind', choices=('stem', 'full-mix'),
                      help='declare whether separate audio is a stem or a full mix')
    sync.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'measure':
            result = measure(args.file)
        elif args.command == 'sheet':
            result = sheet(args.file, args.out, args.cues)
        elif args.command == 'labels':
            result = labels(args.file, args.events)
        elif args.command == 'sync':
            if args.offset is not None and not args.video:
                raise ValueError('--offset needs --video')
            if not args.cues and not args.candidates:
                raise ValueError('--cues is required unless --candidates is given')
            if args.owner and not args.cues:
                raise ValueError('--owner needs --cues')
            if args.cues:
                data, freshness = load_cues(args.cues, args.owner)
            else:
                data, freshness = {'events': []}, 'not applicable: candidate discovery without a cue list'
            result = sync_measure(args.file, args.cues, data, args.video, args.offset, args.null,
                                  args.seed, args.candidates, args.source_kind, args.owner)
            result['cue_freshness'] = freshness
        else:
            result = transcript(args.file, args.detail)
        if args.command == 'transcript':
            if args.owner and not args.cues:
                raise ValueError('--owner needs --cues')
            if args.cues:
                data, freshness = load_cues(args.cues, args.owner)
                result['cue_sync'] = sync_measure(args.file, args.cues, data, args.video, owner=args.owner)
                result['cue_sync']['cue_freshness'] = freshness
            picture_path = args.video or (args.file if has_video(args.file) else None)
            if picture_path:
                picture = video_activity(picture_path)
                if args.video:
                    result['picture_sync'] = picture_alignment(result['events'], picture)
                    result['picture_sync']['time_map'] += ' (assumed; transcript has no offset option)'
                else:
                    origin = audio_origin(args.file)
                    result['picture_sync'] = (picture_alignment(result['events'], picture, origin - picture['origin_s'])
                                              if origin is not None else
                                              {'state': 'not assessed', 'reason': 'audio start time is unknown'})
        if args.json:
            print(json.dumps(result, indent=1, allow_nan=False))
        elif args.command == 'measure':
            print(f"{args.file}: seven launch films (n = 7), 10th to 90th percentile")
            for key, value in result['measurements'].items():
                if key == 'spectrum_db':
                    for band, level in value.items():
                        print(f"  {band} band (dB): {level}; reference {PROFILE.get(band, 'not available')}")
                elif key == 'sub_20_60_hz_percent':
                    low, high = PROFILE['sub']
                    print(f"  {key}: {value}; reference {[round(100 * 10 ** (v / 10), 2) for v in (low, high)]}")
                else:
                    print(f"  {key}: {value}; reference {PROFILE.get(key, 'not available')}")
            print(result['limit'])
        elif args.command == 'sheet':
            print(f"Sound sheet: {result['png']} ({result['events']} onsets, {result['cues']} cues). "+
                  result['limit'])
        elif args.command == 'labels':
            print(f"{args.file}: {len(result['events'])} events. {result['limit']}")
            for event in result['events']:
                print(f"  {event['t']:.3f} s: CLAP {event['clap_hints']}; AST {event['ast_hints']}")
        elif args.command == 'transcript':
            print(f"{args.file}: {len(result['events'])} onsets; {len(result['sections'])} level changes")
            for event in result['events']:
                print(f"  {event['t']:.3f} s: onset")
            for section in result['sections']:
                print(f"  {section['t']:.3f} s: level change {section['change_db']:+g} dB")
            print(result['picture_sync'])
            if args.cues:
                print('  cue sync: ' + json.dumps(result['cue_sync'], ensure_ascii=False))
            print(result['detail_scope'])
            print(result['limit'])
        else:
            print(f"{args.file}: {result['source']}; cue freshness: {result['cue_freshness']}")
            print('  frame change at cue: ' + json.dumps(result['frame_change_at_cue'], ensure_ascii=False))
            print('  sound follows the list: ' + json.dumps(result['sound_follows_list'], ensure_ascii=False))
            print('  turn leads: ' + json.dumps(result['turn_leads'], ensure_ascii=False))
            if not result['follow']:
                print('  follow: no follow span in the list')
            for row in result['follow']:
                state = row.get('state') or row.get('verdict')
                if state == 'screening':
                    print(f"  follow {row.get('id')}: " + json.dumps(row, ensure_ascii=False))
                else:
                    print(f"  follow {row.get('id')}: {state}: {row.get('reason') or 'no reason recorded'}")
            print('  silence: ' + json.dumps(result['silence'], ensure_ascii=False))
            if args.candidates:
                print('  candidates: ' + json.dumps(result.get('candidates', []), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f'listen.py: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
