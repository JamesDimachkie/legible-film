#!/usr/bin/env python3
"""Make a conservative dialogue-cleanup starting point for a listener.

  python voice_clean.py dialogue.wav --out dialogue-clean.wav --json clean.json

Uses FFmpeg highpass 80 Hz, afftdn (noise floor from the 10th percentile of
20 ms RMS windows, clamped to -80..-20 dBFS; reduction at most 6 dB), a mild
5-9 kHz de-esser, light compression, then level to -20 LUFS with gain limited
to +/-6 dB. Each step reports before and after noise floor, integrated LUFS,
true peak and 5-9 kHz to 200 Hz-5 kHz energy ratio. Spectral measurements use
overlapping windows, so they differ from the earlier whole-file FFT. Noise-floor estimates can
contain speech; inspect the source. Each candidate is refused if its 200 Hz-5
kHz energy falls by over --max-speech-loss-db (default 3 dB), relative to the
previous step; this energy guard cannot detect all speech damage. Refusal keeps
prior steps and exits 1. Output must be a new file; the input is never changed.
The result is a starting point, not an automatic fix. Listen to it. Unheard.
Needs numpy and FFmpeg. Exit 0 processed, 1 refused, 2 could not run.
"""

import argparse
import importlib.util
import math
import subprocess
import tempfile
import sys
from pathlib import Path
import numpy as np


def load(name):
    """Load a sibling module by its explicit path."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


io, dialogue = load("sound_io"), load("dialogue_io")
RATE = 48000


def measure_file(ffmpeg, path):
    """Measure fixed overlapping spectral windows and 20 ms RMS without loading the file."""
    command = [ffmpeg, '-v', 'error', '-nostdin', '-i', str(path), '-ac', '2', '-ar', str(RATE),
               '-f', 'f32le', '-']
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    hop = RATE // 2
    block_bytes = hop * 2 * 4
    previous = np.empty((0, 2), dtype=np.float32)
    powers = np.zeros(2, dtype=np.float64)
    rms = []
    peak = 0.0
    total = 0
    while True:
        raw = proc.stdout.read(block_bytes)
        if not raw:
            break
        if len(raw) % 8:
            raise ValueError('invalid decoded audio')
        block = np.frombuffer(raw, dtype='<f4').reshape(-1, 2)
        if not np.isfinite(block).all():
            raise ValueError('non-finite audio')
        total += len(block)
        peak = max(peak, float(np.max(np.abs(block))))
        env, _ = dialogue.frames(block, RATE)
        rms.extend(env.tolist())
        window = np.concatenate((previous, block))
        if len(window) >= 2:
            frequencies = np.fft.rfftfreq(len(window), 1 / RATE)
            spectrum = np.fft.rfft(window.astype(np.float64) * np.hanning(len(window))[:, None], axis=0)
            energy = np.sum(np.abs(spectrum) ** 2, axis=1)
            powers[0] += energy[(frequencies >= 200) & (frequencies < 5000)].sum()
            powers[1] += energy[(frequencies >= 5000) & (frequencies < 9000)].sum()
        previous = block.copy()
    proc.stdout.close()
    stderr = proc.stderr.read()
    code = proc.wait()
    if code or not total:
        raise ValueError('cannot decode audio: ' + stderr.decode(errors='replace')[-600:])
    return {'noise_floor_p10_dbfs': io.db(np.percentile(rms, 10)),
            'loudness': io.meter(ffmpeg, path, RATE),
            'sample_peak_dbfs': io.db(peak),
            'sibilance_to_body_db': float(10 * np.log10(max(powers[1], 1e-24) / max(powers[0], 1e-24))),
            'speech_power': float(powers[0]), 'peak': peak, 'samples': total}


def apply_file(ffmpeg, source, destination, graph):
    """Run one continuous FFmpeg filter to a temporary floating-point WAV."""
    io.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(source), '-ac', '2', '-ar', str(RATE),
            '-af', graph, '-c:a', 'pcm_f32le', str(destination)])


def public_metrics(metrics):
    """Remove internal guards from the report's measurements."""
    return {key: value for key, value in metrics.items() if key not in ('speech_power', 'peak', 'samples')}


def main():
    """Parse options, apply guarded steps and write a report."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input")
    p.add_argument("--out", required=True)
    p.add_argument("--max-speech-loss-db", type=io.positive, default=3)
    p.add_argument("--json")
    p.add_argument("--ffmpeg")
    a = p.parse_args()
    try:
        ffmpeg = io.find_tool("ffmpeg", a.ffmpeg)
        if not ffmpeg:
            raise ValueError("FFmpeg is required (PATH, FFMPEG, or --ffmpeg)")
        src, dst = Path(a.input).resolve(), Path(a.out).resolve()
        if src == dst or dst.exists() or (a.json and Path(a.json).resolve() in (src, dst)):
            raise ValueError("output must be a new file distinct from input and report")
        dst.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='voice-clean-', dir=dst.parent) as temp:
            current = Path(temp) / 'source.wav'
            io.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(src), '-ac', '2', '-ar', str(RATE),
                    '-c:a', 'pcm_f32le', str(current)])
            initial = measure_file(ffmpeg, current)
            nf = max(-80.0, min(-20.0, initial['noise_floor_p10_dbfs']))
            filters = [
                ('highpass', 'highpass=f=80:p=2'),
                ('noise_reduction', 'afftdn=nr=6:nf=%.3f:tn=0' % nf),
                ('de_ess', 'deesser=i=0.1:m=0.2:f=0.5:s=o'),
                ('compression', 'acompressor=threshold=0.125:ratio=1.5:attack=20:release=150:makeup=1'),
            ]
            rows = []
            refused = None
            before = initial
            for index, (name, graph) in enumerate(filters + [('final_level', None)]):
                if graph is None:
                    loud = before['loudness']['integrated_lufs']
                    if loud is None or loud <= -70:
                        refused = 'final level cannot be determined for silence'
                        break
                    gain = max(-6.0, min(6.0, -20.0 - loud))
                    graph = 'volume=%.6fdB' % gain
                candidate = Path(temp) / f'step-{index}.wav'
                apply_file(ffmpeg, current, candidate, graph)
                after = measure_file(ffmpeg, candidate)
                if after['samples'] != before['samples']:
                    raise ValueError('filter returned invalid audio length')
                loss = 10 * math.log10(max(before['speech_power'], 1e-30) / max(after['speech_power'], 1e-30))
                accepted = loss <= a.max_speech_loss_db
                rows.append({'step': name, 'filter': graph, 'before': public_metrics(before),
                             'after': public_metrics(after), 'speech_band_loss_db': loss, 'accepted': accepted})
                if not accepted:
                    refused = name + ' exceeded speech-band loss limit'
                    break
                current = candidate
                before = after
            if before['peak'] >= 1:
                refused = refused or 'output reaches 0 dBFS; lower the level and listen'
            io.run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', str(current), '-c:a', 'pcm_s24le',
                    '-map_metadata', '-1', '-bitexact', str(dst)])
        report = {
            "input": str(src),
            "output": str(dst),
            "noise_floor_used_dbfs": nf,
            "max_speech_loss_db_per_step": a.max_speech_loss_db,
            "steps": rows,
            "refused": refused,
            "exit_code": 1 if refused else 0,
            "limit": "A measured starting point; speech damage and intelligibility need listening. Unheard.",
        }
        if a.json:
            io.save_json(a.json, report)
        print("Voice cleanup: " + (refused or "steps applied") + ". Unheard.")
        return report["exit_code"]
    except (OSError, ValueError, TypeError, OverflowError, UnicodeError) as exc:
        print("voice_clean.py: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
