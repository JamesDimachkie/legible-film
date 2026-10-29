"""Synthetic dialogue cases; these do not qualify real speech or listening."""

import json
import os
import shutil
import wave
import numpy as np


def run_dialogue_cases(tool, record, j, scripts_dir):
    """Exercise the dialogue chain with known synthetic signals."""
    rate = 48000

    def wav(name, x):
        """Write a mono synthetic PCM fixture."""
        with wave.open(j(name), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((np.clip(x, -0.999, 0.999) * 32767).astype("<i2").tobytes())

    def dump(name, data):
        """Write a JSON fixture."""
        with open(j(name), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def read(name):
        """Read a JSON report."""
        with open(j(name), encoding="utf-8") as f:
            return json.load(f)

    t = np.arange(rate * 4) / rate
    voice = np.zeros(len(t))
    for a, b in ((0.5, 1.5), (2.2, 3.3)):
        m = (t >= a) & (t < b)
        voice[m] = 0.12 * np.sin(2 * np.pi * 500 * t[m])
    music = 0.16 * np.sin(2 * np.pi * 800 * t)
    wav("d_voice.wav", voice)
    wav("d_music.wav", music)
    dump("d_cues.json", {"duration": 4, "events": []})
    palette = {"version": 2, "roles": {}, "music": {"file": "d_music.wav", "fade_in_ms": 0, "fade_out_ms": 0}}
    dump("d_plain.json", palette)
    shutil.copyfile(os.path.join(scripts_dir, "selftest_cases", "dialogue_baseline.txt"), j("baseline_mix_cues.py"))
    shutil.copyfile(os.path.join(scripts_dir, "sound_io.py"), j("sound_io.py"))
    code, out = tool(j("baseline_mix_cues.py"), j("d_cues.json"), j("d_plain.json"), "--out-dir", j("baseline"))
    code2, out2 = tool("mix_cues.py", j("d_cues.json"), j("d_plain.json"), "--out-dir", j("plain"))
    same = code == code2 == 0 and all(
        open(j("baseline", n + ".wav"), "rb").read() == open(j("plain", n + ".wav"), "rb").read()
        for n in ("effects", "music", "bed", "mix")
    )
    record("dialogue: no-voice stems byte-identical to integrated baseline", same, out2[-160:] if not same else "")
    palette["voice"] = {"file": "d_voice.wav", "at_s": 0, "gain_db": 0}
    dump("d_palette.json", palette)
    code, out = tool("mix_cues.py", j("d_cues.json"), j("d_palette.json"), "--out-dir", j("d_mix"))
    r = read("d_mix/mix-report.json") if os.path.exists(j("d_mix", "mix-report.json")) else {}
    vr = r.get("voice", {})
    phrases = vr.get("phrases", [])
    record(
        "dialogue: every synthetic phrase reaches 10 LU within 1 LU",
        code == 0 and len(phrases) == 2 and all(abs(x["separation_lu"] - 10) <= 1 for x in phrases),
        str(phrases)[:200] or out[-200:],
    )
    record(
        "dialogue: duck gain ramps without steps",
        bool(vr) and 0 < vr["max_adjacent_gain_change"] < 0.002,
        str(vr.get("max_adjacent_gain_change")),
    )
    code, out = tool(
        "sound_check.py",
        j("d_mix", "mix.wav"),
        "--voice",
        j("d_mix", "voice.wav"),
        "--bed",
        j("d_mix", "music.wav"),
        "--json",
        j("d_clear.json"),
    )
    rows = read("d_clear.json")["voice"]["phrases"]
    record(
        "dialogue: checker passes clear phrases", len(rows) == 2 and not any(x["warn"] for x in rows), str(rows)[:200]
    )
    buried = music.copy()
    buried[t >= 2] *= 0.02
    wav("d_bed.wav", buried)
    code, out = tool(
        "sound_check.py",
        j("d_mix", "mix.wav"),
        "--voice",
        j("d_voice.wav"),
        "--bed",
        j("d_bed.wav"),
        "--json",
        j("d_buried.json"),
    )
    rows = read("d_buried.json")["voice"]["phrases"]
    record(
        "dialogue: checker flags buried phrase and passes clear phrase",
        len(rows) == 2 and rows[0]["warn"] and not rows[1]["warn"],
        str(rows)[:200],
    )
    rng = np.random.default_rng(29)
    noisy = rng.normal(0, 0.004, len(t))
    noisy[(t >= 1) & (t < 3)] += 0.12 * np.sin(2 * np.pi * 1000 * t[(t >= 1) & (t < 3)])
    wav("d_noisy.wav", noisy)
    code, out = tool("voice_clean.py", j("d_noisy.wav"), "--out", j("d_clean.wav"), "--json", j("d_clean.json"))
    report = read("d_clean.json") if os.path.exists(j("d_clean.json")) else {}
    steps = report.get("steps", [])
    if len(steps) == 5:
        reduction = steps[0]["before"]["noise_floor_p10_dbfs"] - steps[-1]["after"]["noise_floor_p10_dbfs"]
        # Remove the deliberate final gain to assess processing of the known tone.
        tone_loss = sum(step["speech_band_loss_db"] for step in steps[:-1])
    else:
        reduction = 0
        tone_loss = 100
    record(
        "dialogue: cleanup reduces output noise and preserves the speech-band tone",
        code == 0 and reduction >= 2 and abs(tone_loss) < 1,
        f"output noise reduction {reduction:.2f} dB; gain-adjusted speech-band loss {tone_loss:.2f} dB; {out[-120:]}",
    )
    # Three separated hits expose a sparse master independently of voice ducking.
    hit_time = np.arange(int(0.005 * rate)) / rate
    hit = 0.5 * np.sin(2 * np.pi * 1000 * hit_time) * np.sin(np.pi * hit_time / 0.005) ** 2
    wav("d_hit.wav", hit)
    sparse_cues = {
        "duration": 4,
        "events": [{"id": str(i), "t": at, "role": "hit"} for i, at in enumerate((0.5, 1.5, 2.5))],
    }
    sparse_palette = {
        "version": 2,
        "roles": {"hit": {"takes": ["d_hit.wav"], "sync": "attack", "points_s": [0]}},
        "master": {"preset": "social"},
    }
    dump("d_sparse_cues.json", sparse_cues)
    dump("d_sparse_palette.json", sparse_palette)
    code, out = tool("mix_cues.py", j("d_sparse_cues.json"), j("d_sparse_palette.json"), "--out-dir", j("d_sparse"))
    report = read("d_sparse/mix-report.json") if os.path.exists(j("d_sparse", "mix-report.json")) else {}
    master = report.get("mastering", {})
    short = master.get("short_of_target") or {}
    reached = master.get("reached_lufs")
    record(
        "dialogue: sparse social master reaches the 4 dB cap and reports shortfall",
        code == 1
        and reached is not None
        and abs(reached - (-24.5)) <= 0.5
        and master.get("status") == "short of target"
        and short.get("status") == "short of target"
        and master.get("target_lufs") == -14
        and master.get("shortfall_lu", 0) > 0
        and 3.9 <= master.get("max_gain_reduction_db", 0) <= 4
        and master.get("aac_pass") is True
        and report.get("gain_refused") is None,
        f"reached {reached} LUFS, master {master}, {out[-120:]}",
    )
    kit = j("d_transient_kit")
    kit_code, kit_out = tool(
        "make_sound_kit.py",
        "--out",
        kit,
        "--seed",
        7,
        "--temp-bpm",
        120,
        "--bars",
        4,
        "--drop-bar",
        4,
        "--stop-bar",
        5,
    )
    if kit_code == 0:
        palette = read("d_transient_kit/palette.json")
        palette["music"]["stop_s"] = 2.9
        dump("d_transient_kit/film-palette.json", palette)
        dump(
            "d_transient_cues.json",
            {
                "duration": 3,
                "events": [
                    {"id": "swing", "t": 0.8, "role": "whoosh", "sync": "apex"},
                    {"id": "cut", "t": 1.5, "role": "impact", "sync": "attack"},
                ],
            },
        )
        code, out = tool(
            "mix_cues.py",
            j("d_transient_cues.json"),
            j("d_transient_kit", "film-palette.json"),
            "--out-dir",
            j("d_transient_mix"),
        )
        report = read("d_transient_mix/mix-report.json")
        master = report["mastering"]
        ok = (
            code == 1
            and master.get("limited_by") == "aac_true_peak"
            and master.get("aac_iterations", 0) >= 1
            and master.get("aac_overshoot_db", 0) > 0
            and master["aac_128k"]["true_peak_dbtp"] <= -1
            and master["max_gain_reduction_db"] <= 4
            and master.get("refused") is None
            and report.get("gain_refused") is None
        )
        detail = str(master)
    else:
        ok = False
        detail = kit_out[-200:]
    record("dialogue: transient-heavy mix corrects the AAC peak", ok, detail)
