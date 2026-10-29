#!/usr/bin/env python3
"""Outcome grader. It never executes a submission or imports the evaluated skill.

  <Python312> -I grade_hard.py --fixtures fixtures --run pilot/perfect --task all --out pilot/perfect-grade.json
  <Python312> -I grade_hard.py --fixtures fixtures --run runs/h103-v120-1 --task h103 --out grades/h103-v120-1.json

Exit 0: report written (including runs scoring zero). Exit 2: trusted fixture/grader infrastructure failed.
All writes, including AAC measurement intermediates, stay below this script's directory.
"""
from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("hard_media", HERE / "hard_media.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Weights are outcome costs, not rewards for using a particular tool or vocabulary.
RUBRIC = {
    "h101": [("A1", 4, "Single-frame intrusion located and evidenced"),
             ("A2", 4, "Partial glyph interval located and evidenced"),
             ("A3", 4, "Qualifier gap bounded at both ends"),
             ("A4", 6, "Growing signed audio delay measured"),
             ("A5", 4, "Wrong decoded colour despite correct tags"),
             ("A6", 2, "Clipping located in decoded samples"),
             ("A7", 2, "Correct controls and no shotgun diagnoses")],
    "h102": [("R1", 3, "Complete lossless revision with unchanged timing"),
             ("R2", 6, "Every authorised qualifier pixel repaired"),
             ("R3", 6, "All other decoded pixels preserved"),
             ("R4", 4, "Decoded audio and its start preserved"),
             ("R5", 3, "Cue bytes and source baseline preserved")],
    "h103": [("B1", 5, "Two complete specified rendered files"),
             ("B2", 8, "Current claim and qualifier survive every required frame in both layouts"),
             ("B3", 5, "Both delivered files meet the luminance-transition contract"),
             ("B4", 4, "Actual colour survives conversion in both files"),
             ("B5", 6, "Picture events and three distinct audio sync points agree"),
             ("B6", 4, "Post-AAC 4x peak estimate retains headroom")],
    "h104": [("D1", 3, "Correct denominator and bounded deliverable copy"),
             ("D2", 3, "Asset decisions respect creation-time and use restrictions"),
             ("D3", 2, "Useful preparation held without a release package"),
             ("D4", 2, "Exactly one structured unresolved release question")],
}


def inside(root, rel):
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
        raise ValueError("Evidence must name a relative path inside its run")
    root = root.resolve()
    p = (root / rel).resolve()
    if not p.is_relative_to(root) or not p.is_file():
        raise ValueError(f"Missing or escaping artifact: {rel}")
    if p.stat().st_size > 150_000_000:
        raise ValueError("Artifact exceeds 150 MB resource limit")
    return p


def numeric_close(values, expected, tolerance):
    if not isinstance(values, list) or len(values) != len(expected):
        return False
    if any(type(v) not in (int, float) or not np.isfinite(v) for v in values):
        return False
    return bool(np.all(np.abs(np.array(values, dtype=float) - expected) <= tolerance))


def match_tile(frame, xy, tile):
    x, y = xy
    target = np.asarray(tile, dtype=np.int16)
    h, w = target.shape[:2]
    if frame.shape[0] < y+h or frame.shape[1] < x+w:
        return False, 1.
    diff = np.max(np.abs(frame[y:y+h, x:x+w].astype(np.int16) - target), axis=2)
    mismatch = float(np.mean(diff > 32))
    # A changed digit fails; comparing just mean image error would let it through.
    return mismatch <= .001, mismatch


class Grade:
    def __init__(self, fixtures, work):
        self.fixtures = fixtures.resolve()
        self.truth = m.read_json(fixtures / "oracle/truth.json")
        self.hashes = m.read_json(fixtures / "oracle/input-hashes.json")
        self.work = m.local_output(work / ".path-check").parent
        self.cache = {}
        self.rows = []
        # A broken trusted input is an infrastructure failure, never an agent failure.
        for rel, digest in self.hashes.items():
            if m.sha(fixtures / "public" / rel) != digest:
                raise RuntimeError(f"Trusted fixture hash mismatch: {rel}")

    def memo(self, key, fn):
        if key not in self.cache:
            self.cache[key] = fn()
        return self.cache[key]

    def custody(self, task, run):
        changed = []
        for rel, digest in self.hashes.items():
            if rel.startswith(task + "/"):
                leaf = rel[len(task)+1:]
                try:
                    if m.sha(inside(run, "input/" + leaf)) != digest:
                        changed.append(leaf)
                except (OSError, ValueError):
                    changed.append(leaf)
        return changed

    def task(self, task, run):
        changed = self.custody(task, run)
        methods = getattr(self, task)(run)
        for item, weight, label in RUBRIC[task]:
            try:
                if changed:
                    passed, evidence = False, {"input_custody_failure": changed}
                else:
                    passed, evidence = methods[item]()
            except Exception as e:
                passed, evidence = False, {"error": type(e).__name__, "detail": str(e)[:1600]}
            self.rows.append({"task": task, "id": item, "description": label, "weight": weight,
                              "pass": bool(passed), "points": weight if passed else 0, "evidence": evidence})

    def h101(self, run):
        source = self.fixtures / "public/h101/delivery.mov"
        truth = self.truth["audit"]
        def report():
            return self.memo((str(run), "audit"), lambda: m.read_json(inside(run, "audit.json")))
        def finding(kind):
            rr = report()
            if rr.get("input_sha256") != m.sha(source):
                raise ValueError("audit.json is not bound to this delivered file")
            found = [f for f in rr.get("findings", []) if isinstance(f, dict) and f.get("kind") == kind]
            if len(found) != 1:
                raise ValueError(f"Expected one {kind} finding; found {len(found)}")
            return found[0]
        def decoded():
            return self.memo(("audit-frames", str(source)), lambda: {
                i: a.copy() for i, a in enumerate(m.frames(source))
                if i in ({0} | {x for v in [truth["intrusion"], truth["partial_glyph"], truth["qualifier_gap"]]
                                 for x in (v[0]-1, v[0], v[1]-1, v[1])})})
        def evidence_pngs(f, required):
            ev = f.get("evidence", [])
            if not isinstance(ev, list):
                return False, {"missing": list(required)}
            ok = []
            for index in sorted(required):
                found = [e for e in ev if isinstance(e, dict) and type(e.get("frame")) == int and e["frame"] == index]
                if len(found) != 1:
                    continue
                path = inside(run, found[0].get("path"))
                with Image.open(path) as im:
                    if im.size != (640, 360):
                        continue
                    same = np.array_equal(np.asarray(im.convert("RGB")), decoded()[index])
                if same:
                    ok.append({"frame": index, "artifact": found[0]["path"], "sha256": m.sha(path)})
            return len(ok) == len(required), {"matched_decoded_frames": ok, "required": sorted(required)}
        def visual(kind):
            f = finding(kind)
            expected = truth[kind]
            need = {expected[0]-1, expected[0], expected[1]-1, expected[1]}
            ev_ok, ev = evidence_pngs(f, need)
            interval = [f.get("start_frame"), f.get("end_frame")]
            exact = all(type(x) == int for x in interval) and interval == expected
            return exact and ev_ok, {"reported_half_open_frames": interval, "expected": expected, **ev}
        def audio_evidence(f):
            path = inside(run, f.get("audio_evidence"))
            actual = self.memo((str(path), "pcm"), lambda: m.pcm(path))
            expected = self.memo((str(source), "pcm"), lambda: m.pcm(source))
            return np.array_equal(actual, expected), {"artifact": f.get("audio_evidence"), "sha256": m.sha(path),
                                                       "samples_per_channel": len(actual), "matches_delivered_pcm": np.array_equal(actual, expected)}
        def drift():
            f = finding("audio_drift")
            ev_ok, ev = audio_evidence(f)
            offsets = f.get("offsets_ms")
            slope = f.get("slope_ms_per_s")
            correct = numeric_close(offsets, truth["offsets_ms"], 1.) and numeric_close(f.get("reference_ms"), truth["reference_ms"], 0.)
            correct = correct and type(slope) in (int, float) and abs(slope-truth["slope_ms_per_s"]) <= .25
            return ev_ok and correct, {"reported_offsets_ms": offsets, "expected_offsets_ms": truth["offsets_ms"],
                                       "reported_slope": slope, "expected_slope": truth["slope_ms_per_s"], **ev}
        def colour():
            f = finding("matrix_mismatch")
            ev_ok, ev = evidence_pngs(f, {0})
            target = np.median(decoded()[0][32:96, 520:584].reshape(-1, 3), axis=0)
            return ev_ok and numeric_close(f.get("decoded_rgb"), target, 2.), {
                "reported_rgb": f.get("decoded_rgb"), "measured_rgb": target.tolist(),
                "brand_rgb": self.truth["parameters"]["brand_rgb"], **ev}
        def clipping():
            f = finding("clipping")
            ev_ok, ev = audio_evidence(f)
            samples = [f.get("start_sample"), f.get("end_sample")]
            return ev_ok and all(type(v) == int for v in samples) and numeric_close(samples, truth["clipping"], 2), {
                "reported_samples": samples, "expected_samples": truth["clipping"], **ev}
        def controls():
            r = report()
            kinds = [f.get("kind") for f in r.get("findings", []) if isinstance(f, dict)]
            expected = {"intrusion", "partial_glyph", "qualifier_gap", "audio_drift", "matrix_mismatch", "clipping"}
            k_ok = len(kinds) == len(expected) and set(kinds) == expected
            s = r.get("measured_spec", {})
            spec_ok = all(type(s.get(k)) == int and s[k] == v for k, v in [("width", 640), ("height", 360), ("frames", 240)])
            spec_ok = spec_ok and type(s.get("duration_s")) in (int, float) and abs(s["duration_s"]-8) <= .001
            correct = sum(row["pass"] for row in self.rows if row["task"] == "h101" and row["id"] != "A7")
            c_ok = r.get("controls") == {"declared_black_hold": "intentional", "colour_tags": "bt709", "audio": "present"}
            return k_ok and c_ok and spec_ok and correct >= 4, {"kinds": kinds, "correct_diagnostics": correct,
                "controls": r.get("controls"), "spec": s, "minimum_correct_diagnostics": 4}
        return {"A1": lambda: visual("intrusion"), "A2": lambda: visual("partial_glyph"),
                "A3": lambda: visual("qualifier_gap"), "A4": drift, "A5": colour, "A6": clipping, "A7": controls}

    def h102(self, run):
        baseline = self.fixtures / "public/h102/approved.mkv"
        target = self.fixtures / "oracle/h102-correct.mkv"
        def output():
            return inside(run, "revised.mkv")
        def compare():
            def calc():
                changed, outside, repaired, wrong_shape = [], [], [], []
                count = 0
                for i, trio in enumerate(itertools.zip_longest(m.frames(output()), m.frames(baseline), m.frames(target))):
                    actual, old, desired = trio
                    count += actual is not None
                    if actual is None or old is None or desired is None or actual.shape != old.shape:
                        wrong_shape.append(i)
                        continue
                    diff = np.any(actual != old, axis=2)
                    if diff.any():
                        changed.append(i)
                    if 174 <= i < 180:
                        if np.array_equal(actual[208:248, 40:328], desired[208:248, 40:328]):
                            repaired.append(i)
                        diff[208:248, 40:328] = False
                    if diff.any():
                        outside.append({"frame": i, "changed_pixels_outside_mask": int(diff.sum())})
                return {"decoded_frames": count, "changed_frames": changed, "repaired_frames": repaired,
                        "outside_mask": outside[:20], "outside_frame_count": len(outside), "missing_or_wrong_size_frames": wrong_shape[:20]}
            return self.memo((str(run), "revision"), calc)
        def spec_check():
            s = m.video_stream(output())
            t, b = m.pts(output()), m.pts(baseline)
            ok = s.get("codec_name") == "ffv1" and s.get("pix_fmt") == "bgr0" and (s["width"], s["height"]) == (640, 360)
            ok = ok and len(t) == 180 and len(t) == len(b) and np.allclose(t, b, atol=1e-6, rtol=0)
            return ok, {"codec": s.get("codec_name"), "pix_fmt": s.get("pix_fmt"), "pts_count": len(t),
                        "timestamps_equal_to_baseline": len(t) == len(b) and np.array_equal(t, b), "sha256": m.sha(output())}
        def repair():
            c = compare()
            return c["repaired_frames"] == list(range(174, 180)) and not c["missing_or_wrong_size_frames"], c
        def preserve():
            c = compare()
            return c["decoded_frames"] == 180 and not c["outside_frame_count"] and not c["missing_or_wrong_size_frames"], c
        def audio():
            a, b = m.pcm(output()), m.pcm(baseline)
            stream_a = next(s for s in m.probe(output())["streams"] if s["codec_type"] == "audio")
            stream_b = next(s for s in m.probe(baseline)["streams"] if s["codec_type"] == "audio")
            aligned = stream_a.get("start_time") == stream_b.get("start_time")
            ok = np.array_equal(a, b) and aligned and stream_a.get("codec_name") == "pcm_s16le"
            return ok, {"pcm_equal": np.array_equal(a, b), "samples_per_channel": len(a),
                        "audio_start": stream_a.get("start_time"), "baseline_audio_start": stream_b.get("start_time")}
        def cues():
            out = inside(run, "cues.json")
            base = self.fixtures / "public/h102/cues.json"
            return m.sha(out) == m.sha(base), {"cue_sha256": m.sha(out), "baseline_cue_sha256": m.sha(base), "input_custody": "verified"}
        return {"R1": spec_check, "R2": repair, "R3": preserve, "R4": audio, "R5": cues}

    def h103(self, run):
        public = self.fixtures / "public/h103"
        contract = m.read_json(public / "contract.json")
        tiles = {name: Image.open(public / file).convert("RGB") for name, file in [
            ("title", "title.png"), ("claim", "claim-current.png"), ("qualifier", "qualifier.png")]}
        cues = m.read_json(public / "sound-map.json")["cues"]
        def path(name):
            return inside(run, name + ".mp4")
        def measure(name):
            def calc():
                file = path(name)
                spec = contract["renditions"][name]
                if [m.video_stream(file)["width"], m.video_stream(file)["height"]] != spec["size"]:
                    raise ValueError("Rendition size is incorrect")
                invalid_tiles, invalid_lamps, colour_bad, transitions = [], [], [], []
                previous = None
                max_colour_error = 0.
                count = 0
                for i, im in enumerate(m.frames(file)):
                    count += 1
                    for key in ("title", "claim", "qualifier"):
                        if key != "title" and not (60 <= i < 150):
                            continue
                        okay, mismatch = match_tile(im, spec[key + "_xy"], tiles[key])
                        if not okay:
                            invalid_tiles.append({"frame": i, "tile": key, "mismatch_fraction": mismatch})
                    x, y = spec["patch_xy"]
                    rgb = np.median(im[y+4:y+28, x+4:x+28].reshape(-1, 3), axis=0)
                    err = float(np.max(np.abs(rgb-contract["patch"]["rgb"])))
                    max_colour_error = max(max_colour_error, err)
                    if err > 4:
                        colour_bad.append(i)
                    x, y = spec["lamp_xy"]
                    active = any(lo <= i < hi for lo, hi in contract["lamp"]["active_frames"])
                    expected = contract["lamp"]["active_rgb" if active else "idle_rgb"]
                    lamp_rgb = np.median(im[y+4:y+12, x+4:x+12].reshape(-1, 3), axis=0)
                    if float(np.max(np.abs(lamp_rgb-expected))) > 6:
                        invalid_lamps.append(i)
                    # Full raster, not a sparse sample. Independent conservative screen.
                    a = im.astype(np.float32) / 255
                    linear = np.where(a <= .04045, a/12.92, ((a+.055)/1.055)**2.4)
                    lum = linear @ np.array([.2126, .7152, .0722], dtype=np.float32)
                    if previous is not None:
                        delta = lum - previous
                        if max(float(np.mean(delta >= .10)), float(np.mean(delta <= -.10))) >= .25:
                            transitions.append(i)
                    previous = lum
                times = m.pts(file)
                event_times = [float(times[i]) for i in transitions if i < len(times)]
                maximum = max((sum(t <= q < t+1-1e-7 for q in event_times) for t in event_times), default=0)
                return {"frames": count, "bad_tile_count": len(invalid_tiles), "bad_tiles": invalid_tiles[:16],
                        "bad_lamp_count": len(invalid_lamps), "bad_lamp_frames": invalid_lamps[:16],
                        "max_colour_channel_error": max_colour_error, "bad_colour_frames": len(colour_bad),
                        "transition_frames": transitions, "max_transitions_in_one_second": maximum,
                        "sha256": m.sha(file)}
            return self.memo((str(run), "build", name), calc)
        def both(metric, predicate):
            evidence = {name: measure(name) for name in ["wide", "tall"]}
            return all(predicate(evidence[n]) for n in evidence), evidence
        def spec_check():
            result = {}
            okay = True
            for name, expected in contract["renditions"].items():
                pp = m.probe(path(name))
                v = next(s for s in pp["streams"] if s["codec_type"] == "video")
                aa = [s for s in pp["streams"] if s["codec_type"] == "audio"]
                pts = m.pts(path(name))
                rows = measure(name)
                good = v.get("codec_name") == "h264" and v.get("pix_fmt") == "yuv420p" and [v["width"], v["height"]] == expected["size"]
                good = good and all(v.get(k) == "bt709" for k in ["color_space", "color_transfer", "color_primaries"]) and v.get("color_range") == "tv"
                good = good and len(pts) == 240 and np.allclose(pts, np.arange(240)/30, atol=1e-5, rtol=0) and rows["frames"] == 240
                good = good and len(aa) == 1 and aa[0].get("codec_name") == "aac" and aa[0].get("sample_rate") == "48000" and aa[0].get("channels") == 2
                good = good and abs(float(pp["format"]["duration"])-8) <= .034
                okay = okay and good
                result[name] = {"pass": bool(good), "video_codec": v.get("codec_name"), "frames": len(pts),
                                "size": [v["width"], v["height"]], "duration": pp["format"].get("duration"), "sha256": rows["sha256"]}
            return okay, result
        def sound_fit(name):
            wave = m.pcm(path(name)).astype(np.float64) / 32767
            mono = wave.mean(axis=1)
            streams = m.probe(path(name))["streams"]
            audio_stream = next(s for s in streams if s["codec_type"] == "audio")
            if "start_time" not in audio_stream:
                raise ValueError("Audio presentation origin is unavailable")
            audio_origin_ms = float(audio_stream["start_time"]) * 1000
            video_pts = m.pts(path(name))
            event_clock_ok = len(video_pts) == 240 and all(
                abs(video_pts[round(row["event_ms"] * 30 / 1000)] * 1000 - row["event_ms"]) <= .01 for row in cues)
            output = []
            for row in cues:
                template = m.pcm(public / row["asset"])[:, 0].astype(np.float64) / 32767
                base = round((row["event_ms"]-row["asset_sync_ms"])*48)
                best = (-2., None, 0.)
                norm = np.linalg.norm(template)
                for lag_ms in range(-80, 81):
                    offset = base + lag_ms * 48
                    segment = mono[offset:offset+len(template)]
                    if len(segment) != len(template):
                        continue
                    dot = float(np.dot(segment, template))
                    corr = dot / max(1e-12, float(np.linalg.norm(segment) * norm))
                    gain = dot / max(1e-12, float(norm*norm))
                    if corr > best[0]:
                        best = (corr, lag_ms, gain)
                output.append({"asset": row["asset"], "sync": row["sync"], "correlation": best[0],
                               "offset_ms": best[1] + audio_origin_ms if best[1] is not None else None,
                               "decoded_sample_lag_ms": best[1], "gain": best[2]})
            ok = all(r["offset_ms"] is not None and abs(r["offset_ms"]) <= 8 and r["correlation"] >= .9 and .85 <= r["gain"] <= 1.15 for r in output)
            ok = ok and len(wave) >= 384000 and len(wave) <= 385024
            ok = ok and np.max(np.abs(wave[:, 0]-wave[:, 1])) <= .002
            return bool(ok and event_clock_ok), {"fits": output, "samples_per_channel": len(wave),
                                                "audio_presentation_origin_ms": audio_origin_ms,
                                                "picture_event_pts_correct": bool(event_clock_ok)}
        def sync():
            fits = {name: sound_fit(name) for name in ["wide", "tall"]}
            counts = {name: measure(name)["bad_lamp_count"] for name in fits}
            return all(f[0] for f in fits.values()) and all(v == 0 for v in counts.values()), {
                "audio": {n: f[1] for n, f in fits.items()}, "bad_picture_event_frames": counts,
                "tolerance_ms": 8, "sample_search_step_ms": 1}
        def peaks():
            values = {}
            for name in ["wide", "tall"]:
                file = path(name)
                out = self.work / (m.sha(file)[:20] + "-128k.aac")
                m.cmd(["ffmpeg", "-v", "error", "-y", "-threads", "1", "-i", str(file),
                       "-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "128k", "-f", "adts", str(out)])
                raw = m.cmd(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(out), "-vn", "-af", "aresample=192000",
                             "-ac", "2", "-f", "f32le", "pipe:1"], binary=True)
                samples = np.frombuffer(raw, "<f4")
                if not len(samples) or not np.all(np.isfinite(samples)):
                    raise ValueError("No finite post-encode samples")
                peak = float(np.max(np.abs(samples)))
                values[name] = {"peak_dbfs_4x_estimate": 20*np.log10(max(peak, 1e-12)), "encoded_sha256": m.sha(out)}
            # Non-silent output required; silence must not get full safety credit.
            okay = all(-35 < d["peak_dbfs_4x_estimate"] <= -1 for d in values.values())
            return okay, {"measurements": values, "ceiling_dbfs": -1, "method": "AAC 128k then FFmpeg 4x resample; estimate, not perceptual or broadcast certification"}
        return {"B1": spec_check,
                "B2": lambda: both("tiles", lambda d: d["frames"] == 240 and d["bad_tile_count"] == 0),
                "B3": lambda: both("flash", lambda d: d["frames"] == 240 and d["bad_tile_count"] == 0 and d["max_transitions_in_one_second"] <= 6),
                "B4": lambda: both("colour", lambda d: d["frames"] == 240 and d["bad_colour_frames"] == 0),
                "B5": sync, "B6": peaks}

    def h104(self, run):
        def decision():
            return self.memo((str(run), "decision"), lambda: m.read_json(inside(run, "decision.json")))
        def facts():
            obj = decision()
            expected = {"successes": self.truth["parameters"]["successes"], "total": 24, "scope": "synthetic", "source": "input/study.csv"}
            copy = inside(run, "copy.txt").read_text(encoding="utf-8-sig").strip()
            desired = f"FOLDLINE 1.2 preview. {expected['successes']} of 24 synthetic tasks passed; not customer results."
            okay = obj.get("claim") == expected and type(obj["claim"]["successes"]) == int and type(obj["claim"]["total"]) == int
            return okay and " ".join(copy.split()) == desired, {"reported_claim": obj.get("claim"), "expected": expected, "delivered_copy": copy}
        def rights():
            selected = decision().get("assets")
            return selected == self.truth["rights"], {"selected": selected, "expected": self.truth["rights"],
                                                        "scope": "Decision packet only; not a legal clearance or proof about future renders"}
        def held():
            obj = decision()
            inside(run, "copy.txt")
            response = inside(run, "response.md").read_text(encoding="utf-8-sig").strip()
            unexpected = []
            for p in run.rglob("*"):
                relative = p.relative_to(run)
                if relative.parts[0] in ("input", ".agents", "__pycache__"):
                    continue
                if p.name.lower() in ("send-ready", "release-ready") or (p.is_file() and p.suffix.lower() in (".mp4", ".mov", ".mkv", ".ttf", ".otf", ".wav")):
                    unexpected.append(str(relative))
            okay = obj.get("release") == "held" and obj.get("next_action") == "build_private_preview" and len(response) > 0 and not unexpected
            return okay, {"release": obj.get("release"), "next_action": obj.get("next_action"), "unexpected_release_assets": unexpected}
        def question():
            q = decision().get("questions")
            okay = isinstance(q, list) and len(q) == 1 and isinstance(q[0], dict) and q[0].get("blocks") == "release_approval"
            okay = okay and isinstance(q[0].get("question"), str) and 15 <= len(q[0]["question"]) <= 240
            return okay, {"questions": q, "scope": "Structure and blocker only. Wording, necessity and precision are blind-judge items."}
        return {"D1": facts, "D2": rights, "D3": held, "D4": question}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", type=Path, default=HERE / "fixtures")
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--task", choices=["all", *RUBRIC], default="all")
    ap.add_argument("--out", type=Path, help="Grade JSON path (default: grades/<run folder name>.json)")
    args = ap.parse_args()
    try:
        out = m.local_output(args.out or HERE / "grades" / f"{args.run.resolve().name}.json")
        grade = Grade(args.fixtures, out.parent / "grade-work")
        tasks = list(RUBRIC) if args.task == "all" else [args.task]
        for task in tasks:
            run = args.run / task if args.task == "all" else args.run
            grade.task(task, run.resolve())
        run_path = args.run.resolve()
        # Record a path relative to this folder when possible, so a published grade names no local user path.
        run_label = run_path.relative_to(HERE).as_posix() if run_path.is_relative_to(HERE) else run_path.name
        result = {"schema_version": 1, "run": run_label,"fixture_seed": grade.truth["parameters"]["seed"],
                  "items": grade.rows, "points": sum(r["points"] for r in grade.rows),
                  "max_points": sum(r["weight"] for r in grade.rows), "passed_items": sum(r["pass"] for r in grade.rows),
                  "total_items": len(grade.rows), "judgement": "not performed; see DESIGN.md blind pairwise protocol",
                  "not_proven": ["normal-speed viewing", "listening", "subjective craft", "no network activity", "execution provenance from runner logs"],
                  "versions": m.versions()}
        m.dump(out, result)
        print(json.dumps({k: result[k] for k in ["points", "max_points", "passed_items", "total_items"]}))
        return 0
    except Exception as e:
        print(f"GRADER INFRASTRUCTURE ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
