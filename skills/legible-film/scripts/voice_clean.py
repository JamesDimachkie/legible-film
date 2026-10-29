#!/usr/bin/env python3
"""Make a conservative dialogue-cleanup starting point for a listener.

  python voice_clean.py dialogue.wav --out dialogue-clean.wav --json clean.json

Uses FFmpeg highpass 80 Hz, afftdn (noise floor from the 10th percentile of
20 ms RMS windows, clamped to -80..-20 dBFS; reduction at most 6 dB), a mild
5-9 kHz de-esser, light compression, then level to -20 LUFS with gain limited
to +/-6 dB. Each step reports before and after noise floor, integrated LUFS,
true peak and 5-9 kHz to 200 Hz-5 kHz energy ratio. Noise-floor estimates can
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


def speech_power(x):
    """Measure total energy in the speech band."""
    f = np.fft.rfftfreq(len(x), 1 / RATE)
    y = np.fft.rfft(x.astype(np.float64) * np.hanning(len(x))[:, None], axis=0)
    return float(np.sum(np.abs(y[(f >= 200) & (f < 5000)]) ** 2))


def metrics(ffmpeg, x):
    """Measure the cleanup step before or after processing."""
    env, _ = dialogue.frames(x, RATE)
    return {
        "noise_floor_p10_dbfs": io.db(np.percentile(env, 10)),
        "loudness": io.meter(ffmpeg, x, RATE),
        "sample_peak_dbfs": io.db(np.max(np.abs(x))),
        "sibilance_to_body_db": dialogue.bands(x, RATE),
    }


def apply(ffmpeg, x, graph):
    """Apply one FFmpeg filter to the decoded samples."""
    data = io.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-f",
            "f32le",
            "-ar",
            str(RATE),
            "-ac",
            "2",
            "-i",
            "-",
            "-af",
            graph,
            "-f",
            "f32le",
            "-",
        ],
        np.asarray(x, dtype="<f4").tobytes(),
    ).stdout
    y = np.frombuffer(data, dtype="<f4").reshape(-1, 2).copy()
    if len(y) != len(x) or not np.isfinite(y).all():
        raise ValueError("filter returned invalid audio length or samples")
    return y


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
        x = io.decode(ffmpeg, src, RATE)
        initial = metrics(ffmpeg, x)
        nf = max(-80.0, min(-20.0, initial["noise_floor_p10_dbfs"]))
        filters = [
            ("highpass", "highpass=f=80:p=2"),
            ("noise_reduction", "afftdn=nr=6:nf=%.3f:tn=0" % nf),
            ("de_ess", "deesser=i=0.1:m=0.2:f=0.5:s=o"),
            ("compression", "acompressor=threshold=0.125:ratio=1.5:attack=20:release=150:makeup=1"),
        ]
        rows = []
        refused = None
        for name, graph in filters + [("final_level", None)]:
            before = metrics(ffmpeg, x)
            if graph is None:
                loud = before["loudness"]["integrated_lufs"]
                if loud is None or loud <= -70:
                    refused = "final level cannot be determined for silence"
                    break
                gain = max(-6.0, min(6.0, -20.0 - loud))
                graph = "volume=%.6fdB" % gain
            y = apply(ffmpeg, x, graph)
            loss = 10 * math.log10(max(speech_power(x), 1e-30) / max(speech_power(y), 1e-30))
            after = metrics(ffmpeg, y)
            accepted = loss <= a.max_speech_loss_db
            rows.append(
                {
                    "step": name,
                    "filter": graph,
                    "before": before,
                    "after": after,
                    "speech_band_loss_db": loss,
                    "accepted": accepted,
                }
            )
            if not accepted:
                refused = name + " exceeded speech-band loss limit"
                break
            x = y
        if np.max(np.abs(x)) >= 1:
            refused = refused or "output reaches 0 dBFS; lower the level and listen"
        io.write_wav(ffmpeg, dst, x, RATE)
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
