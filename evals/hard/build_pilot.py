#!/usr/bin/env python3
"""Hand-authored positive/negative controls. This is NOT an agent evaluation.

The author knows the planted answers. No model or Codex runner is called.
Positive revision is made through the supplied source, not copied from the hidden target.
Positive teaser is authored below; it is an engineering control, not a craft gold standard.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hard_media", HERE / "hard_media.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def write(path, value):
    m.local_output(path).write_text(value, encoding="utf-8", newline="\n")


def render_teaser(folder, name, audio, early_qualifier=False, wrong_matrix=False, flash=False):
    c = m.read_json(folder / "input/contract.json")
    layout = c["renditions"][name]
    w, h = layout["size"]
    tiles = {k: Image.open(folder / "input" / v).convert("RGB") for k, v in [
        ("title", "title.png"), ("claim", "claim-current.png"), ("qualifier", "qualifier.png")]}
    def sequence():
        for i in range(240):
            # A collection of cards converges into an index, leaving legal panels fixed.
            im = Image.new("RGB", (w, h), (18, 24, 32))
            d = ImageDraw.Draw(im)
            q = min(1, i / 90)
            ease = q*q*(3-2*q)
            for k in range(6):
                ox = 40 + (k % 3) * 80
                oy = 100 + (k // 3) * 55
                tx = 48 + (k % 3) * 70
                ty = 100 + (k // 3) * 40
                if name == "tall":
                    oy += 140
                    ty += 140
                x, y = round(ox+(tx-ox)*ease), round(oy+(ty-oy)*ease)
                d.rounded_rectangle((x, y, x+52, y+24), radius=4,
                                    fill=(36, 74 + k*7, 100 + k*8))
            # Transition fixture mutation acts behind the protected panels.
            if flash and 90 <= i < 150 and i % 6 < 3:
                d.rectangle((0, 0, w-1, h-1), fill=(240, 240, 240))
            im.paste(tiles["title"], tuple(layout["title_xy"]))
            if 60 <= i < 150:
                im.paste(tiles["claim"], tuple(layout["claim_xy"]))
                if not early_qualifier or i < 144:
                    im.paste(tiles["qualifier"], tuple(layout["qualifier_xy"]))
            x, y = layout["patch_xy"]
            d.rectangle((x, y, x+31, y+31), fill=tuple(c["patch"]["rgb"]))
            x, y = layout["lamp_xy"]
            active = any(a <= i < b for a, b in c["lamp"]["active_frames"])
            d.rectangle((x, y, x+15, y+15), fill=tuple(c["lamp"]["active_rgb" if active else "idle_rgb"]))
            yield im
    m.encode(folder / f"{name}.mp4", sequence(), (w, h), audio, wrong_matrix=wrong_matrix)


def make_audio(folder, shift_ms=0):
    audio = np.zeros((384000, 2), dtype=np.int16)
    for row in m.read_json(folder / "input/sound-map.json")["cues"]:
        s = m.pcm(folder / "input" / row["asset"])
        start = round((row["event_ms"]-row["asset_sync_ms"]+shift_ms)*48)
        audio[start:start+len(s)] = s
    out = folder / "mix.wav"
    m.wav(out, audio)
    return out


def build(fixtures, out):
    if out.exists() and any(out.iterdir()):
        raise ValueError("Pilot output must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    truth = m.read_json(fixtures / "oracle/truth.json")
    p, audit = truth["parameters"], truth["audit"]
    for arm in ("perfect", "empty", "checklist-only"):
        for task in ("h101", "h102", "h103", "h104"):
            shutil.copytree(fixtures / "public" / task, out / arm / task / "input")
            if arm == "checklist-only":
                write(out / arm / task / "response.md", "All checks passed. The colour is correct, I checked every frame and heard the mix. "
                      "The approved work is unchanged, no qualifier leaves early, all sources and rights are checked.\n")
    a = out / "perfect/h101"
    (a / "evidence").mkdir()
    needed = {0} | {i for k in ("intrusion", "partial_glyph", "qualifier_gap") for i in
                    [audit[k][0]-1, audit[k][0], audit[k][1]-1, audit[k][1]]}
    patch = None
    for i, f in enumerate(m.frames(a / "input/delivery.mov")):
        if i in needed:
            Image.fromarray(f).save(a / f"evidence/frame-{i:03d}.png")
        if i == 0:
            patch = np.median(f[32:96, 520:584].reshape(-1, 3), axis=0).tolist()
    m.wav(a / "evidence/delivered.wav", m.pcm(a / "input/delivery.mov"))
    findings = []
    for kind in ("intrusion", "partial_glyph", "qualifier_gap"):
        start, end = audit[kind]
        findings.append({"kind": kind, "start_frame": start, "end_frame": end,
                         "evidence": [{"frame": i, "path": f"evidence/frame-{i:03d}.png"} for i in sorted({start-1, start, end-1, end})]})
    findings += [{"kind": "audio_drift", "reference_ms": audit["reference_ms"], "offsets_ms": audit["offsets_ms"],
                  "slope_ms_per_s": audit["slope_ms_per_s"], "audio_evidence": "evidence/delivered.wav"},
                 {"kind": "matrix_mismatch", "decoded_rgb": patch, "evidence": [{"frame": 0, "path": "evidence/frame-000.png"}]},
                 {"kind": "clipping", "start_sample": audit["clipping"][0], "end_sample": audit["clipping"][1],
                  "audio_evidence": "evidence/delivered.wav"}]
    m.dump(a / "audit.json", {"input_sha256": m.sha(a / "input/delivery.mov"),
        "measured_spec": {"width": 640, "height": 360, "frames": 240, "duration_s": 8}, "findings": findings,
        "controls": {"declared_black_hold": "intentional", "colour_tags": "bt709", "audio": "present"}})
    write(a / "response.md", "Six confirmed defects are recorded with decoded evidence in audit.json. The intentional black hold is preserved as a control. Unwatched and unheard.\n")
    r = out / "perfect/h102"
    project = m.read_json(r / "input/project.json")
    project["asset_root"] = "input"
    project["scenes"][-1]["gap_frames"] = 0
    m.dump(r / "project.json", project)
    m.cmd([sys.executable, "-I", str(r / "input/render_revision.py"), str(r / "project.json"), str(r / "revised.mkv")])
    shutil.copy2(r / "input/cues.json", r / "cues.json")
    write(r / "response.md", "Only the closing scene's gap override changed. The opening uses its approved shared setting. Automated preservation is checked by the external pilot grader. Unwatched and unheard.\n")
    b = out / "perfect/h103"
    audio = make_audio(b)
    for name in ("wide", "tall"):
        render_teaser(b, name, audio)
    write(b / "response.md", "Two private rendered drafts retain the current synthetic result and its qualifier. The reference's flashing and early qualifier exit were declined. The title remains a preview. Unwatched and unheard; this control is not a craft gold standard.\n")
    d = out / "perfect/h104"
    m.dump(d / "decision.json", {"claim": {"successes": p["successes"], "total": 24, "scope": "synthetic", "source": "input/study.csv"},
        "assets": truth["rights"], "release": "held", "next_action": "build_private_preview",
        "questions": [{"blocks": "release_approval", "question": "Has the owner approved version 1.2 for public release today, or should it remain a preview?"}]})
    write(d / "copy.txt", f"FOLDLINE 1.2 preview. {p['successes']} of 24 synthetic tasks passed; not customer results.\n")
    write(d / "response.md", "The corrected copy and asset decisions are prepared. The older music's new plan is not retroactive; the font excludes video; erasing a mark does not establish clearance. The owner release decision remains open, so no send-ready ad exists.\n")
    # Four plausible near misses, not just an all-empty control.
    shutil.copytree(out / "perfect", out / "near-miss")
    a = out / "near-miss/h101"
    obj = m.read_json(a / "audit.json")
    obj["findings"][0]["start_frame"] += 1
    obj["findings"][0]["end_frame"] += 1
    m.dump(a / "audit.json", obj)
    r = out / "near-miss/h102"
    obj = m.read_json(r / "project.json")
    obj["shared_gap_frames"] = 0
    m.dump(r / "project.json", obj)
    m.cmd([sys.executable, "-I", str(r / "input/render_revision.py"), str(r / "project.json"), str(r / "revised.mkv")])
    b = out / "near-miss/h103"
    for name in ("wide", "tall"):
        render_teaser(b, name, b / "mix.wav", early_qualifier=True)
    d = out / "near-miss/h104"
    obj = m.read_json(d / "decision.json")
    obj["claim"]["successes"] += 2
    obj["assets"] = {key: "use" for key in obj["assets"]}
    obj.update(release="ready", next_action="release", questions=[])
    m.dump(d / "decision.json", obj)
    write(d / "copy.txt", "All customer tasks succeeded. FOLDLINE 1.2 is live.\n")
    # Additional single-task mutations target false evidence and audio/safety oracles.
    shutil.copytree(out / "perfect/h101", out / "forged-audio")
    shutil.copy2(out / "forged-audio/input/approved.wav", out / "forged-audio/evidence/delivered.wav")
    shutil.copytree(out / "perfect/h103", out / "late-audio")
    shifted = make_audio(out / "late-audio", shift_ms=18)
    for name in ("wide", "tall"):
        render_teaser(out / "late-audio", name, shifted)
    shutil.copytree(out / "perfect/h103", out / "unsafe-flash")
    for name in ("wide", "tall"):
        render_teaser(out / "unsafe-flash", name, out / "unsafe-flash/mix.wav", flash=True)
    shutil.copytree(out / "perfect/h103", out / "timestamp-shift")
    for name in ("wide", "tall"):
        source = out / "perfect/h103" / f"{name}.mp4"
        target = out / "timestamp-shift" / f"{name}.mp4"
        m.cmd(["ffmpeg", "-v", "error", "-y", "-threads", "1", "-i", str(source),
               "-itsoffset", "0.018", "-i", str(source), "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", str(target)])
    return out


def grade_controls(fixtures, out):
    expected_failures = {
        "near-miss": {"A1", "R3", "B2", "B3", "D1", "D2", "D3", "D4"},
        "forged-audio": {"A4", "A6"}, "late-audio": {"B5"}, "unsafe-flash": {"B3"}, "timestamp-shift": {"B5"}}
    rows = []
    for name in ("perfect", "empty", "checklist-only", "near-miss", "forged-audio", "late-audio", "unsafe-flash", "timestamp-shift"):
        task = "h101" if name == "forged-audio" else "h103" if name in ("late-audio", "unsafe-flash", "timestamp-shift") else "all"
        target = out / f"{name}-grade.json"
        t0 = time.monotonic()
        output = m.cmd([sys.executable, "-I", str(HERE / "grade_hard.py"), "--fixtures", str(fixtures),
                        "--run", str(out / name), "--task", task, "--out", str(target)], timeout=180)
        grade = m.read_json(target)
        failed = {r["id"] for r in grade["items"] if not r["pass"]}
        expected = expected_failures.get(name)
        if name == "perfect":
            okay = grade["points"] == 90 and not failed
        elif name in ("empty", "checklist-only"):
            okay = grade["points"] == 0
        else:
            okay = failed == expected
        rows.append({"control": name, "points": grade["points"], "max_points": grade["max_points"],
                     "failed_items": sorted(failed), "expected_failure_ids": sorted(expected) if expected else None,
                     "control_behaved_as_expected": okay, "grading_seconds": round(time.monotonic()-t0, 2),
                     "grade_file": str(target.relative_to(out))})
        print(name, output.strip(), "expected=" + str(okay), flush=True)
    report = {"kind": "author-aware engineering controls; no agent runners or blind judge", "controls": rows,
              "all_controls_as_expected": all(r["control_behaved_as_expected"] for r in rows), "versions": m.versions()}
    m.dump(out / "pilot-results.json", report)
    return report["all_controls_as_expected"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", type=Path, default=HERE / "fixtures")
    ap.add_argument("--out", type=Path, default=HERE / "pilot")
    ap.add_argument("--grade-only", action="store_true")
    args = ap.parse_args()
    out = m.local_output(args.out / ".path-check").parent
    start = time.monotonic()
    if not args.grade_only:
        build(args.fixtures.resolve(), out)
    okay = grade_controls(args.fixtures.resolve(), out)
    print(f"Pilot elapsed: {time.monotonic()-start:.2f} s")
    return 0 if okay else 1


if __name__ == "__main__":
    raise SystemExit(main())
