"""Small, local media I/O shared by the fixture author and independent grader.

No model, network, renderer under test, or Legible Film code is imported.
Frames stream through pipes; an entire movie is never kept in RAM.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
RATE = 48000
FPS = 30


def local_output(path):
    p = Path(path).resolve()
    if not p.is_relative_to(HERE):
        raise ValueError(f"Write target must be inside {HERE}: {p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def dump(path, obj):
    local_output(path).write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def read_json(path):
    def bad(value):
        raise ValueError(f"Non-finite JSON value: {value}")
    def unique(pairs):
        d = {}
        for k, v in pairs:
            if k in d:
                raise ValueError(f"Duplicate JSON key: {k}")
            d[k] = v
        return d
    p = Path(path)
    if p.stat().st_size > 2_000_000:
        raise ValueError("JSON is larger than 2 MB")
    return json.loads(p.read_text(encoding="utf-8-sig"), parse_constant=bad, object_pairs_hook=unique)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd(args, timeout=120, binary=False):
    proc = subprocess.run(args, capture_output=True, timeout=timeout,
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    if proc.returncode:
        raise RuntimeError(f"{args[0]} exit {proc.returncode}: {proc.stderr.decode(errors='replace')[-2500:]}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", errors="replace")


def probe(path):
    data = json.loads(cmd(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                           "-of", "json", str(path)]))
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            if s["width"] * s["height"] > 1280 * 720 or max(s["width"], s["height"]) > 1280:
                raise ValueError("Video exceeds the evaluation's 720p resource limit")
    if float(data.get("format", {}).get("duration", 0)) > 30:
        raise ValueError("Video exceeds the evaluation's 30 s decode limit")
    return data


def video_stream(path):
    return next(s for s in probe(path)["streams"] if s["codec_type"] == "video")


def frames(path):
    s = video_stream(path)
    w, h = s["width"], s["height"]
    args = ["ffmpeg", "-v", "error", "-threads", "1", "-i", str(path), "-map", "0:v:0",
            "-an", "-sn", "-fps_mode", "passthrough", "-threads", "1", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "pipe:1"]
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    count = 0
    try:
        while True:
            data = p.stdout.read(w * h * 3)
            if not data:
                break
            if len(data) != w * h * 3:
                raise ValueError("Partial decoded frame")
            count += 1
            if count > 900:
                raise ValueError("Too many frames")
            yield np.frombuffer(data, np.uint8).reshape(h, w, 3)
        err = p.stderr.read().decode(errors="replace")
        if p.wait(timeout=30):
            raise RuntimeError(f"Decode failed: {err[-1500:]}")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stdout.close()
        p.stderr.close()


def pts(path):
    rows = json.loads(cmd(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
                           "-show_entries", "frame=best_effort_timestamp_time", "-of", "json", str(path)]))["frames"]
    return np.array([float(r["best_effort_timestamp_time"]) for r in rows])


def pcm(path):
    # Do not invent a mono downmix that could hide a changed stereo channel.
    data = cmd(["ffmpeg", "-v", "error", "-threads", "1", "-i", str(path), "-map", "0:a:0",
                "-vn", "-ar", str(RATE), "-ac", "2", "-f", "s16le", "pipe:1"], binary=True)
    return np.frombuffer(data, "<i2").reshape(-1, 2)


def wav(path, samples):
    a = np.asarray(samples)
    if a.ndim == 1:
        a = np.column_stack([a, a])
    if a.dtype != np.int16:
        a = np.rint(np.clip(a, -1, 1) * 32767).astype("<i2")
    with wave.open(str(local_output(path)), "wb") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(a.astype("<i2").tobytes())


def encode(path, sequence, size, audio=None, lossless=False, wrong_matrix=False):
    pth = local_output(path)
    w, h = size
    args = ["ffmpeg", "-v", "error", "-y", "-threads", "1", "-filter_threads", "1",
            "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{w}x{h}",
            "-framerate", "30", "-i", "pipe:0"]
    if audio:
        args += ["-i", str(audio)]
    args += ["-map", "0:v:0"]
    if audio:
        args += ["-map", "1:a:0"]
    if lossless:
        args += ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "bgr0"]
    else:
        matrix = "bt601" if wrong_matrix else "bt709"
        vf = (f"scale=in_range=pc:out_range=tv:out_color_matrix={matrix},format=yuv420p,"
              "setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
        args += ["-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "15",
                 "-x264-params", "threads=1:lookahead-threads=1:scenecut=0", "-g", "30",
                 "-color_range", "tv", "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    if audio:
        args += ["-c:a", "pcm_s16le"] if pth.suffix.lower() in (".mkv", ".mov") else ["-c:a", "aac", "-b:a", "192k"]
    if pth.suffix.lower() in (".mp4", ".mov"):
        args += ["-movflags", "+faststart"]
    args += ["-threads", "1", "-map_metadata", "-1", "-fflags", "+bitexact", str(pth)]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        for frame in sequence:
            a = np.asarray(frame, dtype=np.uint8)
            if a.shape != (h, w, 3):
                raise ValueError(f"Unexpected frame size {a.shape}")
            p.stdin.write(a.tobytes())
        p.stdin.close()
        err = p.stderr.read().decode(errors="replace")
        if p.wait(timeout=120):
            raise RuntimeError(f"Encode failed: {err[-2500:]}")
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        p.stderr.close()


# Original block-letter drawings. No system font or third-party graphic is copied.
# Each glyph is five columns by seven rows; cell strokes are part of the fixture.
GLYPHS = {
    "A":"01110/10001/10001/11111/10001/10001/10001", "B":"11110/10001/10001/11110/10001/10001/11110",
    "C":"01111/10000/10000/10000/10000/10000/01111", "D":"11110/10001/10001/10001/10001/10001/11110",
    "E":"11111/10000/10000/11110/10000/10000/11111", "F":"11111/10000/10000/11110/10000/10000/10000",
    "G":"01111/10000/10000/10111/10001/10001/01111", "H":"10001/10001/10001/11111/10001/10001/10001",
    "I":"11111/00100/00100/00100/00100/00100/11111", "J":"00111/00010/00010/00010/10010/10010/01100",
    "K":"10001/10010/10100/11000/10100/10010/10001", "L":"10000/10000/10000/10000/10000/10000/11111",
    "M":"10001/11011/10101/10101/10001/10001/10001", "N":"10001/11001/10101/10011/10001/10001/10001",
    "O":"01110/10001/10001/10001/10001/10001/01110", "P":"11110/10001/10001/11110/10000/10000/10000",
    "Q":"01110/10001/10001/10001/10101/10010/01101", "R":"11110/10001/10001/11110/10100/10010/10001",
    "S":"01111/10000/10000/01110/00001/00001/11110", "T":"11111/00100/00100/00100/00100/00100/00100",
    "U":"10001/10001/10001/10001/10001/10001/01110", "V":"10001/10001/10001/10001/10001/01010/00100",
    "W":"10001/10001/10001/10101/10101/10101/01010", "X":"10001/10001/01010/00100/01010/10001/10001",
    "Y":"10001/10001/01010/00100/00100/00100/00100", "Z":"11111/00001/00010/00100/01000/10000/11111",
    "0":"01110/10001/10011/10101/11001/10001/01110", "1":"00100/01100/00100/00100/00100/00100/01110",
    "2":"01110/10001/00001/00010/00100/01000/11111", "3":"11110/00001/00001/01110/00001/00001/11110",
    "4":"00010/00110/01010/10010/11111/00010/00010", "5":"11111/10000/10000/11110/00001/00001/11110",
    "6":"01110/10000/10000/11110/10001/10001/01110", "7":"11111/00001/00010/00100/01000/01000/01000",
    "8":"01110/10001/10001/01110/10001/10001/01110", "9":"01110/10001/10001/01111/00001/00001/01110",
    ".":"00000/00000/00000/00000/00000/00110/00110", ":":"00000/00110/00110/00000/00110/00110/00000",
    "/":"00001/00001/00010/00100/01000/10000/10000", "-":"00000/00000/00000/11111/00000/00000/00000",
    "%":"11001/11010/00100/00100/01000/10110/00110", " ":"00000/00000/00000/00000/00000/00000/00000",
}


def lettering(image, text, xy, scale=3, colour=(238, 242, 246)):
    d = ImageDraw.Draw(image)
    x, y = xy
    for ch in text.upper():
        for row, bits in enumerate(GLYPHS[ch].split("/")):
            for col, bit in enumerate(bits):
                if bit == "1":
                    d.rectangle((x + col * scale, y + row * scale,
                                 x + (col + 1) * scale - 1, y + (row + 1) * scale - 1), fill=colour)
        x += 6 * scale


def tile(text, size=(288, 40), scale=2):
    im = Image.new("RGB", size, (18, 24, 32))
    lettering(im, text, (8, (size[1] - 7 * scale) // 2), scale)
    return im


def versions():
    import sys
    import PIL
    return {"python": sys.version, "numpy": np.__version__, "Pillow": PIL.__version__,
            "ffmpeg": cmd(["ffmpeg", "-version"]).splitlines()[0],
            "ffprobe": cmd(["ffprobe", "-version"]).splitlines()[0]}
