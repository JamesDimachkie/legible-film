#!/usr/bin/env python3
"""Local Node-dependent capture/render contract tests, using original synthetic pages only.

  python kit_selftest.py --keep qa/kit-selftest
  python kit_selftest.py --playwright /path/to/node_modules/playwright-core

Runs one Chromium at a time, calibrates, checks info/analyse/stills, renders a small
whip/cut fixture, verifies frame count, no cross-cut mixing, pre-cut blur, frame-locked
state, frozen-source custody, BT.709 tags and a decoded brand patch via qc_file.py.
Needs numpy, Pillow, FFmpeg and Node/Playwright/Chromium. Missing Node, Playwright or
Chromium prints 'skipped: <reason>' and exits 0 (2 with --require); other missing tools are exit 2.
Exit 0 all passed (or explicit dependency skip), 1 a check failed, 2 could not run.
These synthetic checks do not establish a film's playback quality; audio is absent.
"""

import argparse
import functools
import http.server
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

import numpy as np

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--keep")
    p.add_argument("--playwright")
    p.add_argument("--browser")
    p.add_argument("--require", action="store_true", help="exit 2 instead of skipping missing Node/Playwright/Chromium")
    a = p.parse_args()
    node = shutil.which("node")
    if not node:
        reason = "Node is missing"
        print("skipped: " + reason)
        print("NOT RUN: " + reason)
        return 2 if a.require else 0
    opts = []
    if a.playwright:
        opts += ["--playwright", a.playwright]
    if a.browser:
        opts += ["--browser", a.browser]
    results = []

    def record(name, ok, detail=""):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)

    work = Path(a.keep).resolve() if a.keep else Path(tempfile.mkdtemp(prefix="lf-kit-selftest-"))
    work.mkdir(parents=True, exist_ok=True)
    server = None
    try:
        cmd = [node, str(HERE / "film_capture.mjs"), "calibrate", *opts]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode and any(
            x in r.stderr for x in ("Playwright missing", "Chromium missing", "Chromium executable missing")
        ):
            reason = " ".join(r.stderr.split())
            print("skipped: " + reason)
            print("NOT RUN: " + reason)
            return 2 if a.require else 0
        (work / "calibrate.json").write_text(r.stdout, encoding="utf-8")
        if r.returncode:
            record("capture calibration", False, r.stderr[-800:])
            return 1
        calibration = json.loads(r.stdout)
        record(
            "capture calibration: all pixel, paint, font and determinism checks",
            all(x["status"] == "PASS" for x in calibration["checks"]),
            f"{len(calibration['checks'])} checks",
        )
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            print("kit_selftest.py: FFmpeg/ffprobe required", file=sys.stderr)
            return 2
        film = work / "film"
        shutil.copytree(HERE / "testpages", film)
        handler = functools.partial(Quiet, directory=str(film))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/?render"

        def capture(command, *args):
            return subprocess.run(
                [node, str(HERE / "film_capture.mjs"), command, url, *opts, *map(str, args)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

        r = capture("info")
        info = json.loads(r.stdout) if not r.returncode else {}
        record("capture info matches page contract", r.returncode == 0 and info.get("frames") == 60)
        r = capture("analyse")
        record("capture analyse", r.returncode == 0 and json.loads(r.stdout).get("errors") == [])
        r = capture("stills", "--at", "0.1,b1", "--out", work / "stills")
        record(
            "capture stills: seconds and zero-based beats",
            r.returncode == 0 and len(list((work / "stills").glob("*.png"))) == 2,
        )
        base = [sys.executable, "-I", str(HERE / "film_render.py"), str(film), "--from", "23", "--to", "30", *opts]
        # Read the first progress line only after the frozen copy is already serving. Mutating
        # the live synthetic source now must have no effect on the frozen render.
        # Use the renderer's real memory guard. Its free_memory uses the same
        # GlobalMemoryStatusEx / sysconf measurement as make_film.py --doctor.
        proc = subprocess.Popen(
            base + ["--out", str(work / "cut.mkv"), "--lossless", "--no-dither", "--shutter", "360"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        first = proc.stdout.readline()
        source = film / "index.html"
        original = source.read_text(encoding="utf-8")
        source.write_text(original.replace("'#600000'", "'#000060'"), encoding="utf-8")
        out, err = proc.communicate()
        source.write_text(original, encoding="utf-8")
        record("render completed", proc.returncode == 0, (first + out + err)[-350:])
        record(
            "render uses the real memory guard",
            proc.returncode == 0 and "guard could not measure memory" not in first + out,
            first.strip(),
        )
        if proc.returncode:
            return 1
        manifest = json.loads((work / "cut.mkv.manifest.json").read_text())
        record(
            "render decoded frame count / source manifest",
            manifest["decoded_frames"] == 8 and "index.html" in manifest["frozen_sha256"],
        )

        def decode(path):
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-i", str(path), "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                capture_output=True,
            )
            if r.returncode:
                raise RuntimeError(r.stderr.decode()[-1000:])
            return np.frombuffer(r.stdout, np.uint8).reshape(-1, 180, 320, 3)

        f = decode(work / "cut.mkv")
        row = f[6, 100]
        record(
            "blur rule: pre-cut whip keeps exposure width",
            np.count_nonzero(row[:, 0]) > 16,
            f"{np.count_nonzero(row[:, 0])}px vs sharp 16px",
        )
        record(
            "blur rule: no cut double exposure",
            not np.any(row[:, 1] > row[:, 0]) and not np.any((f[7, 100, :, 0] > 100) & (f[7, 100, :, 1] > 100)),
        )
        record("frozen source resists live edit mid-render", np.array_equal(f[7, 100, 250], [96, 0, 0]))
        r = subprocess.run(
            base + ["--out", str(work / "sharp.mkv"), "--lossless", "--preview", "--no-dither"],
            capture_output=True,
            text=True,
        )
        sharp = decode(work / "sharp.mkv") if not r.returncode else None
        record(
            "frame-locked HUD agrees across sub-samples",
            sharp is not None and np.array_equal(f[:, :35, :60], sharp[:, :35, :60]),
        )
        r = subprocess.run(base + ["--out", str(work / "colour.mp4")], capture_output=True, text=True)
        record("H.264 render completed", r.returncode == 0, r.stderr[-300:] if r.returncode else "")
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "qc_file.py"),
                str(work / "colour.mp4"),
                "--color",
                "bt709",
                "--color-patch",
                "0@270,20,12,12=#3080C0",
                "--frames",
                "8",
                "--audio",
                "none",
                "--max-level",
                "4.2",
                "--faststart",
                "--json",
                str(work / "colour-qc.json"),
            ],
            capture_output=True,
            text=True,
        )
        record(
            "encoded frame count, colour tags, brand patch, level, faststart, absent audio",
            r.returncode == 0,
            r.stdout[-500:] if r.returncode else "",
        )
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "film_render.py"),
                str(film),
                "--page",
                "index.html?error",
                "--from",
                "8",
                "--to",
                "9",
                "--out",
                str(work / "error.mp4"),
                *opts,
            ],
            capture_output=True,
            text=True,
        )
        record("page seek error fails render with exit 1", r.returncode == 1 and "synthetic seek failure" in r.stderr)
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "film_render.py"),
                str(film),
                "--page",
                "index.html?console-error",
                "--from",
                "8",
                "--to",
                "9",
                "--out",
                str(work / "console-error.mp4"),
                *opts,
            ],
            capture_output=True,
            text=True,
        )
        record("console error fails render with exit 1", r.returncode == 1 and "synthetic console failure" in r.stderr)
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "film_render.py"),
                str(film),
                "--page",
                "index.html?ready-error",
                "--from",
                "8",
                "--to",
                "9",
                "--out",
                str(work / "ready-error.mp4"),
                *opts,
            ],
            capture_output=True,
            text=True,
        )
        record(
            "rejected page readiness fails render with exit 1",
            r.returncode == 1 and "synthetic ready failure" in r.stderr,
        )
        # Scheduler parity uses deliberately awkward cuts and multiple overlapping windows.
        script = (
            "import {sampleTimes} from "
            + json.dumps((HERE / "film_capture.mjs").as_uri())
            + "; const i={fps:60,duration:1,cuts:[.015,.499],smears:[[0,.6,3]],fast:[[.2,.7,19]]}; "
            + "console.log(JSON.stringify([0,.01,.015,.4833333333,.499,.9]"
            + ".map(t=>sampleTimes(t,i,360,4,32))));"
        )
        r = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True)
        import importlib.util

        spec = importlib.util.spec_from_file_location("render_common", HERE / "render_common.py")
        c = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(c)
        expected = [
            c.sample_times(t, 60, 1, [0.015, 0.499], [[0, 0.6, 3]], [[0.2, 0.7, 19]], 360, 4, 32)
            for t in [0, 0.01, 0.015, 0.4833333333, 0.499, 0.9]
        ]
        actual = json.loads(r.stdout) if not r.returncode else []
        record(
            "JS/Python shutter scheduler parity at cuts, edges, smears and fast windows",
            len(actual) == len(expected)
            and all(np.allclose(x, y, rtol=0, atol=1e-12) for x, y in zip(actual, expected)),
        )
        r = capture("info", "--size", "180x320")
        sized = json.loads(r.stdout) if not r.returncode else {}
        record(
            "capture --size changes info to portrait",
            r.returncode == 0 and (sized.get("width"), sized.get("height")) == (180, 320),
        )
        r = capture("analyse", "--size", "180x180")
        record(
            "capture --size sets square CSS viewport before loading",
            r.returncode == 0 and json.loads(r.stdout).get("viewport") == [180, 180],
        )
        r = capture("stills", "--size", "180x320", "--scale", "2", "--at", "0", "--out", work / "portrait-still")
        from PIL import Image

        pngs = list((work / "portrait-still").glob("*.png"))
        with Image.open(pngs[0]) as im:
            dimensions = im.size
        record("capture --size portrait still preserves device scale", r.returncode == 0 and dimensions == (360, 640))
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "film_render.py"),
                str(film),
                "--size",
                "1080x1920",
                "--from",
                "0",
                "--to",
                "1",
                "--preview",
                *opts,
            ],
            capture_output=True,
            text=True,
        )
        portrait = work / "film_1080x1920.mp4"
        check = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "qc_file.py"),
                str(portrait),
                "--spec",
                "1080x1920@60",
                "--frames",
                "2",
                "--color",
                "bt709",
                "--max-level",
                "4.2",
            ],
            capture_output=True,
            text=True,
        )
        record(
            "render --size portrait: default size name, encode dimensions, frame count and actual-size level",
            r.returncode == 0 and check.returncode == 0,
            (r.stderr + check.stdout)[-350:] if r.returncode or check.returncode else "",
        )
        r = subprocess.run(
            [
                sys.executable,
                "-I",
                str(HERE / "film_render.py"),
                str(film),
                "--size",
                "180x180",
                "--res",
                "720",
                "--from",
                "0",
                "--to",
                "1",
                "--preview",
                *opts,
            ],
            capture_output=True,
            text=True,
        )
        square = work / "film_120x120.mp4"
        check = subprocess.run(
            [sys.executable, "-I", str(HERE / "qc_file.py"), str(square), "--spec", "120x120@60", "--frames", "2"],
            capture_output=True,
            text=True,
        )
        record("render --size square: --res scales the film own size", r.returncode == 0 and check.returncode == 0)
        print(f"{sum(results)}/{len(results)} checks passed.")
        return 0 if all(results) else 1
    except Exception as exc:
        print("kit_selftest.py: could not run: " + str(exc), file=sys.stderr)
        return 2
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join()
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
