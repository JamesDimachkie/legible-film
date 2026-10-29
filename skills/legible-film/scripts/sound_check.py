#!/usr/bin/env python3
"""Measure sound-chain listening candidates, never grade a film.

  python sound_check.py mix.wav --cues cues.spotted.json --palette palette.json --json check.json
  python sound_check.py mix.wav --stems effects.wav music.wav bed.wav --silent 2.0-2.4

Starting points (override after listening, not universal perceptual limits):
  phone-band loss >6 LU warns. Compare BS.1770 integrated loudness with a
    300 Hz high-pass / 8 kHz low-pass (two-pole Butterworth, 12 dB/octave each).
  energy above 2 kHz <5% warns. Sum stereo channel power without mono folding;
    1 s Hann windows, 50% overlap, DC excluded, upper endpoint Nyquist.
  digital silence >50 ms inside the film warns (all channels <=1e-8 linear).
    Runs touching sample 0 or the file end are edge silence, reported separately.
    --silent A-B and cues.silent_windows [{from_s,to_s}] declare quiet windows;
    silent/reading-hold cues declare t +/- window_ms (default 120 ms).
  rolling one-second [t,t+1) windows: >2 layers of one role or >5 total warns.
    Include the main take, explicit event layers and, with --palette, role layers;
    no recursion. Disabled spotted events do not count; enabled optionals do.
  crest factor <3 or >24 dB warns (sample peak minus whole-file stereo RMS).
  last 10% >1 LU louder than the preceding 90% warns. Use integrated loudness;
    if either section is <400 ms, use RMS and state that fallback in the report.

--voice and --bed (one or more aligned stems, or mix minus voice) report per-phrase
voice-to-bed BS.1770 integrated differences, flagging below 10 LU by default.
Short or unmeasurable phrases use an explicitly labelled RMS dB fallback.
Phrases use a 20 ms voice RMS envelope; threshold max(-50 dBFS, peak -35 dB),
merge gaps <=200 ms and reject segments <100 ms. Noise and quiet words can be
misidentified. A >6 dB phrase RMS spread or 100 ms peak 5-9 kHz to 200 Hz-5 kHz
energy ratio >-6 dB is a listening candidate, not intelligibility proof.

Optional stems get the same spectral/crest/loudness diagnostics, plus their
silence and ending measurements. Their warnings are labelled stem:<filename>;
sparse stems may intentionally trigger them. Missing cues/stems are explicitly
not checked. An unmeasurable comparison warns rather than becoming a pass.
Needs numpy and FFmpeg. No playback or network. Exit 0 no warnings, 1 any
listening candidate, 2 could not run. Every output is unheard.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path
import numpy as np


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


io, spotting, dialogue = load("sound_io"), load("spot_cues"), load("dialogue_io")
RATE = 48000


def runs(mask):
    edges = np.diff(np.r_[False, mask, False].astype(np.int8))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def upper_share(x, rate):
    total = upper = 0.0
    width = min(len(x), rate)
    hop = max(1, width // 2)
    f = np.fft.rfftfreq(width, 1 / rate)
    weights = np.full(len(f), 2.0)
    weights[0] = 0.0
    if width % 2 == 0:
        weights[-1] = 1.0
    starts = sorted(set(range(0, max(1, len(x) - width + 1), hop)) | {len(x) - width})
    for start in starts:
        segment = x[start : start + width].astype(np.float64)
        power = np.sum(np.abs(np.fft.rfft(segment * np.hanning(width)[:, None], axis=0)) ** 2, axis=1) * weights
        total += float(power.sum())
        upper += float(power[f > 2000].sum())
    return upper / total if total > 1e-20 else None


def measure(ffmpeg, path, a, windows):
    x = io.decode(ffmpeg, path, RATE)
    duration = len(x) / RATE
    measured = io.meter(ffmpeg, path)
    raw = io.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-af",
            "highpass=f=300:p=2,lowpass=f=8000:p=2",
            "-ac",
            "2",
            "-ar",
            str(RATE),
            "-f",
            "f32le",
            "-",
        ]
    ).stdout
    phone = np.frombuffer(raw, dtype="<f4").reshape(-1, 2)
    phone_meter = io.meter(ffmpeg, phone, RATE)
    has_energy = float(np.max(np.abs(x))) > 1e-8
    loss = (
        measured["integrated_lufs"] - phone_meter["integrated_lufs"]
        if measured["integrated_lufs"] is not None and phone_meter["integrated_lufs"] is not None and has_energy
        else None
    )
    share = upper_share(x, RATE)
    crest = io.db(np.max(np.abs(x))) - io.level(x) if has_energy else None
    quiet = np.max(np.abs(x), axis=1) <= 1e-8
    edge = [{"from_s": lo / RATE, "to_s": hi / RATE} for lo, hi in runs(quiet) if lo == 0 or hi == len(x)]
    eligible = quiet.copy()
    for lo, hi in runs(quiet):
        if lo == 0 or hi == len(x):
            eligible[lo:hi] = False
    for lo, hi in windows:
        eligible[max(0, round(lo * RATE)) : min(len(x), max(0, round(hi * RATE)))] = False
    gaps = [
        {"from_s": lo / RATE, "to_s": hi / RATE, "duration_ms": (hi - lo) / RATE * 1000}
        for lo, hi in runs(eligible)
        if (hi - lo) / RATE * 1000 > a.silence_ms + 1e-9
    ]
    split = min(len(x) - 1, max(1, round(0.9 * len(x))))
    body, ending = x[:split], x[split:]
    method = "integrated_lufs"
    if min(len(body), len(ending)) < 0.4 * RATE:
        body_loudness, end_loudness = io.level(body), io.level(ending)
        method = "rms_dbfs (section shorter than 400 ms)"
    else:
        body_loudness = io.meter(ffmpeg, body, RATE)["integrated_lufs"]
        end_loudness = io.meter(ffmpeg, ending, RATE)["integrated_lufs"]
    difference = (
        end_loudness - body_loudness if body_loudness is not None and end_loudness is not None and has_energy else None
    )
    checks = {
        "phone_band_loss": {
            "loss_lu": loss,
            "starting_point_lu": a.phone_loss_lu,
            "warn": loss is None or loss > a.phone_loss_lu,
        },
        "above_2khz": {
            "energy_share": share,
            "starting_point_share": a.min_upper_share,
            "warn": share is None or share < a.min_upper_share,
        },
        "digital_silence": {"gaps": gaps, "edge_silence": edge, "starting_point_ms": a.silence_ms, "warn": bool(gaps)},
        "crest_factor": {
            "db": crest,
            "starting_points_db": [a.min_crest_db, a.max_crest_db],
            "warn": crest is None or not a.min_crest_db <= crest <= a.max_crest_db,
        },
        "ending": {
            "body": body_loudness,
            "ending": end_loudness,
            "difference_lu": difference,
            "method": method,
            "from_s": split / RATE,
            "starting_point_lu": a.ending_lu,
            "warn": difference is None or difference > a.ending_lu,
        },
    }
    return {
        "file": str(path),
        "duration_s": duration,
        "loudness": measured,
        "phone_band": phone_meter,
        "checks": checks,
    }


def interval(text):
    try:
        lo, hi = map(float, text.split("-"))
        spotting.finite(lo, "silent start", 0)
        spotting.finite(hi, "silent end", 0)
        if hi <= lo:
            raise ValueError("end must be after start")
        return lo, hi
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use a finite non-negative A-B interval: " + str(exc))


def check_voice(ffmpeg, a):
    """Measure phrase separation and intelligibility proxies on aligned stems."""
    warnings = []
    voice = io.decode(ffmpeg, a.voice, RATE)
    beds = [io.decode(ffmpeg, path, RATE) for path in a.bed]
    if any(len(b) != len(voice) for b in beds):
        raise ValueError("voice and bed stems must have equal duration on the film clock")
    bed = np.sum(np.stack(beds).astype(np.float64), axis=0)
    regions, _, _ = dialogue.phrases(voice, RATE)
    rows = []
    for lo, hi in regions:
        vl, bl = dialogue.level(voice[lo:hi]), dialogue.level(bed[lo:hi])
        sep, method = dialogue.separation(io, ffmpeg, voice[lo:hi], bed[lo:hi], RATE)
        rows.append(
            {
                "from_s": lo / RATE,
                "to_s": hi / RATE,
                "voice_rms_dbfs": vl,
                "bed_rms_dbfs": bl,
                "separation_lu": sep,
                "method": method,
                "warn": sep < a.voice_separation_lu,
                "sibilance_to_body_db": dialogue.bands(voice[lo:hi], RATE),
            }
        )
    levels = [r["voice_rms_dbfs"] for r in rows]
    spread = max(levels) - min(levels) if len(levels) >= 2 else None
    # Peak proxy uses the maximum of 100 ms spectral windows per phrase.
    for row, (lo, hi) in zip(rows, regions):
        values = [
            dialogue.bands(voice[k : min(k + RATE // 10, hi)], RATE)
            for k in range(lo, hi, RATE // 10)
            if min(k + RATE // 10, hi) - k >= RATE // 20
        ]
        row["peak_sibilance_to_body_db"] = max(values) if values else None
        row["sibilance_listening_check"] = bool(values and max(values) > -6)
    voice_report = {
        "phrases": rows,
        "separation_starting_point_lu": a.voice_separation_lu,
        "method": "BS.1770 integrated per phrase when measurable; otherwise RMS dB fallback",
        "phrase_level_spread_db": spread,
        "steadiness_starting_point_db": 6,
        "steadiness_listening_check": spread is not None and spread > 6,
        "sibilance_starting_point_db": -6,
        "limit": "Envelope detection and spectral ratios are proxies; listen to each phrase.",
    }
    if not rows:
        warnings.append("voice:no_detected_phrases")
    if any(row["warn"] for row in rows):
        warnings.append("voice:separation")
    if voice_report["steadiness_listening_check"]:
        warnings.append("voice:steadiness")
    if any(row["sibilance_listening_check"] for row in rows):
        warnings.append("voice:sibilance")
    return voice_report, warnings


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mix")
    p.add_argument("--stems", nargs="+")
    p.add_argument("--cues")
    p.add_argument("--palette")
    p.add_argument("--voice")
    p.add_argument("--bed", nargs="+")
    p.add_argument("--voice-separation-lu", type=io.positive, default=10)
    p.add_argument("--silent", action="append", type=interval, default=[])
    p.add_argument("--phone-loss-lu", type=io.positive, default=6)
    p.add_argument("--min-upper-share", type=io.finite, default=0.05)
    p.add_argument("--silence-ms", type=io.positive, default=50)
    p.add_argument("--min-crest-db", type=io.finite, default=3)
    p.add_argument("--max-crest-db", type=io.finite, default=24)
    p.add_argument("--ending-lu", type=io.finite, default=1)
    p.add_argument("--json")
    p.add_argument("--ffmpeg")
    a = p.parse_args()
    try:
        ffmpeg = io.find_tool("ffmpeg", a.ffmpeg)
        if not ffmpeg:
            raise ValueError("FFmpeg is required (PATH, FFMPEG, or --ffmpeg)")
        if not 0 <= a.min_upper_share <= 1 or a.min_crest_db > a.max_crest_db or a.ending_lu < 0:
            raise ValueError("invalid diagnostic thresholds")
        if bool(a.voice) != bool(a.bed):
            raise ValueError("--voice and --bed must be supplied together")
        windows = list(a.silent)
        density = None
        palette = json.loads(Path(a.palette).read_text(encoding="utf-8")) if a.palette else {}
        if not isinstance(palette, dict):
            raise ValueError("palette must be an object")
        roles = palette.get("roles", {})
        if not isinstance(roles, dict):
            raise ValueError("palette roles must be an object")
        if a.cues:
            spec, events, fps = spotting.read_cues(a.cues)
            for ev in events:
                if spotting.silent(ev):
                    t, half = spotting.time_of(ev, fps), ev.get("window_ms", 120) / 1000
                    windows.append((max(0, t - half), t + half))
            for window in spec.get("silent_windows", []) if isinstance(spec, dict) else []:
                lo = spotting.finite(window["from_s"], "silent from_s", 0)
                hi = spotting.finite(window["to_s"], "silent to_s", 0)
                if hi <= lo:
                    raise ValueError("silent window end must follow start")
                windows.append((lo, hi))
            dense = spotting.density(events, fps, roles)
            density = {
                "windows": dense,
                "warn": bool(dense),
                "palette_layers_counted": bool(a.palette),
                "starting_points": {"per_role": 2, "total": 5, "window_s": 1},
            }
        report = measure(ffmpeg, a.mix, a, windows)
        report.update(
            layers_per_second=density,
            declared_silent_windows=windows,
            stems=[measure(ffmpeg, path, a, windows) for path in a.stems or []],
            not_checked=[
                name
                for name, given in (("cue density", a.cues), ("stems", a.stems), ("palette layers", a.palette))
                if not given
            ],
            limit="Measurements locate reasons to listen, never a verdict. Unheard.",
        )
        warnings = [name for name, row in report["checks"].items() if row["warn"]]
        if a.voice:
            report["voice"], voice_warnings = check_voice(ffmpeg, a)
            warnings.extend(voice_warnings)
        if density and density["warn"]:
            warnings.append("layers_per_second")
        for stem in report["stems"]:
            warnings.extend(
                "stem:" + Path(stem["file"]).name + ":" + name for name, row in stem["checks"].items() if row["warn"]
            )
        report.update(warnings=warnings, exit_code=1 if warnings else 0)
        if a.json:
            io.save_json(a.json, report)
        print(f"Sound check: {len(warnings)} listening candidates. Unheard.")
        for warning in warnings:
            print("  inspect: " + warning)
        return report["exit_code"]
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print("sound_check.py: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
