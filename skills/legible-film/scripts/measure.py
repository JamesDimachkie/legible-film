#!/usr/bin/env python3
"""Measure visual & audio rhythm for cut/insert profiling and compare/pin against references.

  python measure.py VIDEO --out DIR [--from START] [--to END] [--fps FPS] [--json]
  python measure.py compare SOURCE_DIR OTHER_DIR --as rebuild|refill [--beats A.json B.json] [--out FILE] [--json]
  python measure.py pin PROJECT REF.mp4 [--k 5] [--out DIR] [--json]

Measures hold durations, event density, occupancy, edge detail, ink bands, easing curve fit,
camera/scene vs flat-sheet motion, vignette tendency, and audio-onset sync lift. Works with
OpenCV when installed or falls back cleanly to pure NumPy + Pillow.
Exit 0 on success (on-rhythm), 1 when compare detects off-rhythm metrics, 2 on error.
"""
import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

try:
    import cv2
except ImportError:
    cv2 = None

HERE = Path(__file__).resolve().parent
VERSION = 7
AW, AH = 320, 180
LOOK_W, LOOK_H = 640, 360
MOVE_THRESH = 0.35
MIN_HOLD_S = 0.10
READ_HOLD_S = 0.25
STILL_THRESH = 0.05
MOVE_FIT_MAX_S = 3.0
SYNC_TOL_S = 0.12
LINEAR_RATIO = 0.75
FPS_CAP = 30.0
POINTS = 24
DARKER_CORNER = 0.90
LIT_MIDDLE = 0.02
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0

REFILL_TOLERANCE = {
    'events_per_10s': 2.0,
    'median_hold_s': 0.35,
    'median_move_s': 0.12,
    'drift': 0.008,
    'occupancy': 0.18,
    'occupancy_spread': 0.15,
    'detail': 0.04,
    'bands': 1.2,
    'largest_band': 0.18,
    'ease_fit': 0.20,
    'follows_speed': 0.25,
    'scene_move': 0.25,
    'sheet_move': 0.15,
    'dark_corners': 0.15,
    'sync_rate': 0.20,
}

_BEZIER_CACHE = None


def _load_sibling(name):
    spec = importlib.util.spec_from_file_location('lf_meas_' + name, HERE / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


project = _load_sibling('project')
render_common = _load_sibling('render_common')


def _find_tool(name):
    path = render_common.find_tool(name)
    if not path:
        raise ValueError(f'{name} is required on PATH')
    return path


def probe_video(path):
    ffprobe = _find_tool('ffprobe')
    cmd = [
        ffprobe, '-v', 'error', '-show_entries',
        'stream=codec_type,width,height,r_frame_rate,nb_frames:format=duration',
        '-of', 'json', str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                         creationflags=NO_WINDOW)
    if res.returncode:
        raise ValueError(f'{path}: ffprobe failed ({res.stderr.strip()[-200:]})')
    data = json.loads(res.stdout or '{}')
    streams = data.get('streams') or []
    vid = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not vid:
        raise ValueError(f'{path}: no video stream found')
    has_audio = any(s.get('codec_type') == 'audio' for s in streams)
    fps = float(Fraction(str(vid.get('r_frame_rate') or '30/1')))
    dur = float((data.get('format') or {}).get('duration') or 0)
    if dur <= 0 and fps > 0 and vid.get('nb_frames'):
        dur = int(vid['nb_frames']) / fps
    return {
        'w': int(vid['width']), 'h': int(vid['height']), 'size': [int(vid['width']), int(vid['height'])],
        'fps': fps, 'duration': dur, 'audio': has_audio,
    }


def _to_gray(rgb):
    if cv2 is not None:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    return (0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]).astype(np.uint8)


def _edge_density(gray):
    if cv2 is not None:
        return float((cv2.Canny(gray, 60, 160) > 0).mean())
    g = gray.astype(np.float32)
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    # both gradients over the same interior, (h-2) x (w-2): they had been cut to (h-1) x (w-2) and (h-2) x (w-1), and
    # without OpenCV every frame raised "operands could not be broadcast together"
    gx = np.abs(g[1:-1, 2:] - g[1:-1, :-2])
    gy = np.abs(g[2:, 1:-1] - g[:-2, 1:-1])
    mag = gx + gy
    return float((mag > 28.0).mean())


def _palette_kmeans(rgb, k=5):
    if cv2 is not None:
        small = cv2.resize(rgb, (80, 45), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
        cv2.setRNGSeed(0)
        _, labels, centres = cv2.kmeans(
            small, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0), 2, cv2.KMEANS_PP_CENTERS
        )
        shares = np.bincount(labels.ravel(), minlength=k) / max(1, len(labels))
    else:
        im = Image.fromarray(rgb).resize((80, 45), Image.Resampling.BILINEAR)
        small = np.asarray(im, dtype=np.float32).reshape(-1, 3)
        rng = np.random.default_rng(0)
        idx = rng.choice(len(small), size=min(k, len(small)), replace=False)
        centres = small[idx].copy()
        for _ in range(10):
            dists = np.linalg.norm(small[:, None, :] - centres[None, :, :], axis=2)
            labels = np.argmin(dists, axis=1)
            for c_i in range(len(centres)):
                pts = small[labels == c_i]
                if len(pts):
                    centres[c_i] = pts.mean(axis=0)
        shares = np.bincount(labels, minlength=len(centres)) / max(1, len(labels))
    rows = []
    for c, s in zip(centres, shares):
        hx = '#%02x%02x%02x' % tuple(int(np.clip(round(v), 0, 255)) for v in c)
        rows.append({'hex': hx, 'weight': round(float(s), 3)})
    return sorted(rows, key=lambda x: -x['weight'])


def _lit_middle(rgb):
    light = (_to_gray(rgb).astype(np.float32) / 255.0) ** 2.2
    h, w = light.shape
    mid = float(light[h // 3:2 * h // 3, w // 3:2 * w // 3].mean())
    a, b = max(1, h // 6), max(1, w // 6)
    corners = (light[:a, :b], light[:a, -b:], light[-a:, :b], light[-a:, -b:])
    return mid > LIT_MIDDLE and all(float(c.mean()) < DARKER_CORNER * mid for c in corners)


def _background(rgb):
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(int)
    keys = (border // 16) @ np.array([256, 16, 1])
    common = np.bincount(keys).argmax()
    return border[keys == common].mean(axis=0)


def _look_frame(rgb):
    mask = np.abs(rgb.astype(int) - _background(rgb)).max(axis=2) > 40
    rows = mask.mean(axis=1) > 0.004
    bands, start = [], None
    for y, on in enumerate(list(rows) + [False]):
        if on and start is None:
            start = y
        elif not on and start is not None:
            if y - start >= 2:
                bands.append((y - start) / rgb.shape[0])
            start = None
    ys, xs = np.nonzero(mask)
    if len(xs):
        box = [
            round(float(xs.min() / rgb.shape[1]), 3),
            round(float(ys.min() / rgb.shape[0]), 3),
            round(float(xs.max() / rgb.shape[1]), 3),
            round(float(ys.max() / rgb.shape[0]), 3),
        ]
    else:
        box = [0.0, 0.0, 0.0, 0.0]
    gray = _to_gray(rgb)
    if len(xs) >= 16:
        crop = gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        detail = _edge_density(crop)
    else:
        detail = _edge_density(gray)
    return {
        'occupancy': round(float(mask.mean()), 3),
        'detail': round(detail, 4),
        'bands': len(bands),
        'band_heights': [round(b, 3) for b in sorted(bands, reverse=True)[:6]],
        'largest_band': round(max(bands), 3) if bands else 0.0,
        'box': box,
    }


def _find_cuts(energy):
    if len(energy) < 3:
        return []
    med = float(np.median(energy))
    floor = max(8.0, med * 6.0)
    cuts = []
    for i in range(1, len(energy)):
        prev_e = energy[i - 1]
        next_e = energy[i + 1] if i + 1 < len(energy) else 0.0
        if energy[i] > floor and energy[i] > 2.5 * max(prev_e, next_e, 0.2):
            cuts.append(i)
    return cuts


def _segments(energy, fps):
    moving = list(energy > MOVE_THRESH)
    if len(moving) > 1:
        moving[0] = moving[1]
    runs, start = [], 0
    for i in range(1, len(moving) + 1):
        if i == len(moving) or moving[i] != moving[start]:
            runs.append(['move' if moving[start] else 'hold', start, i])
            start = i
    shortest = max(1, round(MIN_HOLD_S * fps))
    for r in runs:
        if r[0] == 'hold' and (r[2] - r[1]) < shortest and r[1] > 0 and r[2] < len(moving):
            r[0] = 'move'
    merged = []
    for r in runs:
        if merged and merged[-1][0] == r[0]:
            merged[-1][2] = r[2]
        else:
            merged.append(list(r))
    return merged


def _bezier_profiles():
    global _BEZIER_CACHE
    if _BEZIER_CACHE is None:
        presets = [
            ('snap', (0.2, 0.0, 0.0, 1.0)),
            ('smooth', (0.42, 0.0, 0.58, 1.0)),
            ('sharp', (0.4, 0.0, 0.2, 1.0)),
            ('OutExpo', (0.16, 1.0, 0.3, 1.0)),
            ('linear', (0.0, 0.0, 1.0, 1.0)),
        ]
        s = np.linspace(0, 1, 160)
        t_grid = np.linspace(0, 1, POINTS + 1)
        out = []
        for name, (x1, y1, x2, y2) in presets:
            bx = 3 * (1 - s) ** 2 * s * x1 + 3 * (1 - s) * s ** 2 * x2 + s ** 3
            by = 3 * (1 - s) ** 2 * s * y1 + 3 * (1 - s) * s ** 2 * y2 + s ** 3
            prog = np.interp(t_grid, bx, by)
            v = np.abs(np.diff(prog))
            v = v / max(float(v.max()), 1e-9)
            out.append((name, v))
        _BEZIER_CACHE = out
    return _BEZIER_CACHE


def _fit_ease(energy, a, b):
    e = np.asarray(energy[a + 1:b + 1], dtype=float)
    if len(e) < 4 or e.max() <= 0:
        return None
    prof = np.interp(np.linspace(0, len(e) - 1, POINTS), np.arange(len(e)), e)
    prof = prof / max(float(prof.max()), 1e-9)
    best_name, best_r2 = 'smooth', 0.0
    sst = float(np.sum((prof - prof.mean()) ** 2)) + 1e-9
    for name, ref_curve in _bezier_profiles():
        sse = float(np.sum((prof - ref_curve) ** 2))
        r2 = max(0.0, 1.0 - sse / sst)
        if r2 > best_r2:
            best_r2 = r2
            best_name = name
    peak = round(int(np.argmax(prof)) / max(1, POINTS - 1), 2)
    return {'curve': best_name, 'r2': round(best_r2, 3), 'peak': peak, 'profile': [round(float(x), 2) for x in prof]}


def _follows_speed(energy, energy2, a, b):
    steps = range(a + 1, min(b, len(energy) - 1))
    top = max(energy[a + 1:b + 1], default=0.0)
    ratios = [
        energy2[i + 1] / (energy[i] + energy[i + 1])
        for i in steps
        if energy[i] + energy[i + 1] > 0 and max(energy[i], energy[i + 1]) >= 0.8 * top
    ]
    return not ratios or float(np.median(ratios)) >= LINEAR_RATIO


def _motion_geometry(grays):
    """Estimate scene_move vs sheet_move share across sampled grayscale frames."""
    if len(grays) < 3:
        return 0.0, 0.0
    classes = [c for c in (_motion_class(a, b) for a, b in zip(grays[:-1], grays[1:])) if c]
    if not classes:
        return 0.0, 0.0
    return round(classes.count('scene') / len(classes), 3), round(classes.count('sheet') / len(classes), 3)


def _motion_class(a, b):
    """'still', 'scene' or 'sheet' for one pair of sampled grayscale frames, or None when it cannot be told: one pair at a
    time, so a film is classified as it streams past and no frame need be kept."""
    if cv2 is not None:
        cv2.setRNGSeed(0)
        classes = []
        for a, b in [(a, b)]:
            pts = cv2.goodFeaturesToTrack(a, maxCorners=300, qualityLevel=0.01, minDistance=7)
            if pts is None or len(pts) < 30:
                continue
            nxt, ok, _ = cv2.calcOpticalFlowPyrLK(a, b, pts, None, winSize=(21, 21), maxLevel=3)
            back, ok2, _ = cv2.calcOpticalFlowPyrLK(b, a, nxt, None, winSize=(21, 21), maxLevel=3)
            good = (ok.ravel() == 1) & (ok2.ravel() == 1) & (np.linalg.norm((back - pts).reshape(-1, 2), axis=1) < 1.0)
            p0, p1 = pts.reshape(-1, 2)[good], nxt.reshape(-1, 2)[good]
            if len(p0) < 25:
                continue
            mv = np.linalg.norm(p1 - p0, axis=1)
            if (mv > 0.6).mean() < 0.6 or float(np.median(mv)) < 0.8:
                classes.append('still')
                continue
            fit, _ = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=1.5)
            if fit is None:
                classes.append('scene')
                continue
            off = np.linalg.norm((fit[:, :2] @ p0.T).T + fit[:, 2] - p1, axis=1)
            classes.append('scene' if np.percentile(off, 75) >= 0.7 else 'sheet')
        return classes[0] if classes else None

    # Pure NumPy block-variance motion classification fallback when OpenCV is absent.
    classes = []
    for a, b in [(a, b)]:
        diff = np.abs(a.astype(np.float32) - b.astype(np.float32))
        if float(diff.mean()) < 1.0:
            classes.append('still')
            continue
        bh, bw = diff.shape[0] // 4, diff.shape[1] // 4
        if bh < 4 or bw < 4:
            continue
        blocks = diff[:bh * 4, :bw * 4].reshape(4, bh, 4, bw).mean(axis=(1, 3))
        if float(blocks.std()) > 0.45 * max(float(blocks.mean()), 1.0):
            classes.append('scene')
        else:
            classes.append('sheet')
    return classes[0] if classes else None


def measure_audio(path, duration):
    ffmpeg = _find_tool('ffmpeg')
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(path),
           '-vn', '-ac', '1', '-ar', '16000', '-f', 's16le', '-']
    p = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if p.returncode or not p.stdout:
        return None
    x = np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768.0
    hop = 160
    n = len(x) // hop
    if n < 20:
        return None
    rms = np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-10)
    level = 20.0 * np.log10(rms)
    flux = np.maximum(0.0, np.diff(level, prepend=level[0]))
    flux = np.convolve(flux, np.ones(3) / 3.0, mode='same')
    onsets = []
    for i in range(1, n - 1):
        lo, hi = max(0, i - 50), min(n, i + 50)
        local = flux[lo:hi]
        if flux[i] >= flux[i - 1] and flux[i] > flux[i + 1] and flux[i] > local.mean() + 2.0 * local.std() and level[i] > -50.0:
            if not onsets or i - onsets[-1] >= 5:
                onsets.append(i)
    tempo = None
    env = flux - flux.mean()
    if len(env) >= 40:
        ac = np.correlate(env, env, mode='full')[n - 1:]
        lags = np.arange(30, min(100, n - 1))
        if len(lags) and ac[0] > 0:
            best = lags[np.argmax(ac[lags])]
            strength = float(ac[best] / ac[0])
            if strength > 0.1:
                tempo = {'bpm': round(6000.0 / best, 1), 'strength': round(strength, 2)}
    return {
        'onsets': [round(i * hop / 16000.0, 3) for i in onsets],
        'tempo': tempo,
    }


def _sync_rate(events, onsets, duration, tolerance=SYNC_TOL_S, trials=200, seed=0):
    if not events or not onsets or duration <= 0:
        return None, None, None
    o = np.asarray(onsets, dtype=float)
    def hit_share(ts):
        return float(np.mean([np.min(np.abs(o - t)) <= tolerance for t in ts]))
    rate = hit_share(events)
    rng = np.random.default_rng(seed)
    chance = float(np.mean([hit_share((np.asarray(events) + rng.uniform(0, duration)) % duration) for _ in range(trials)]))
    lift = round(rate - chance, 3)
    return round(rate, 3), round(chance, 3), lift


def _render_beats_sheet(video, times, out_dir):
    if not times:
        return []
    ffmpeg = _find_tool('ffmpeg')
    tiles = []
    for t in times[:40]:
        cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-ss', f'{t:.3f}', '-i', str(video),
               '-frames:v', '1', '-vf', f'scale={AW}:{AH}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
        raw = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).stdout
        if len(raw) < AW * AH * 3:
            continue
        im = Image.frombytes('RGB', (AW, AH), raw[:AW * AH * 3])
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 78, 18), fill=(0, 0, 0))
        d.text((4, 2), f'{t:05.2f}s', fill=(255, 232, 102))
        tiles.append(im)
    if not tiles:
        return []
    cols = 5
    rows_n = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGB', (AW * cols, AH * rows_n), (32, 32, 32))
    for idx, im in enumerate(tiles):
        sheet.paste(im, ((idx % cols) * AW, (idx // cols) * AH))
    out_dir.mkdir(parents=True, exist_ok=True)
    name = 'beats-1.jpg'
    sheet.save(out_dir / name, quality=85)
    return [name]


KEEP_FRAMES = 600   # the most decoded pictures kept at once: evenly spaced stand-ins for a hold whose own frame cannot be read


def _stream_rgb_frames(video, fps, start=None, end=None, w=AW, h=AH):
    """Each decoded frame in turn, read from ffmpeg as it comes: the whole film was read into memory, and then kept
    twice (in colour and in grey), about 4 GB for ten minutes at 320 x 180 and 30 a second."""
    ffmpeg = _find_tool('ffmpeg')
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error']
    if start is not None:
        cmd += ['-ss', f'{start:.3f}']
    if end is not None:
        cmd += ['-t', f'{max(0.05, end - (start or 0.0)):.3f}']
    cmd += ['-i', str(video), '-vf', f'fps={fps:.3f},scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    fb = w * h * 3
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    try:
        while True:
            raw = proc.stdout.read(fb)
            if len(raw) < fb:
                break
            yield np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def _decode_rgb_frames(video, fps, start=None, end=None, w=AW, h=AH):
    ffmpeg = _find_tool('ffmpeg')
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error']
    if start is not None:
        cmd += ['-ss', f'{start:.3f}']
    if end is not None:
        cmd += ['-t', f'{max(0.05, end - (start or 0.0)):.3f}']
    cmd += ['-i', str(video), '-vf', f'fps={fps:.3f},scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    fb = w * h * 3
    count = len(raw) // fb
    return [np.frombuffer(raw, dtype=np.uint8, count=fb, offset=i * fb).reshape(h, w, 3) for i in range(count)]


def _grab_rgb(video, t, w=LOOK_W, h=LOOK_H):
    ffmpeg = _find_tool('ffmpeg')
    cmd = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-ss', f'{t:.3f}', '-i', str(video),
           '-frames:v', '1', '-vf', f'scale={w}:{h}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW).stdout
    if len(raw) < w * h * 3:
        return None
    return np.frombuffer(raw, dtype=np.uint8, count=w * h * 3).reshape(h, w, 3)


def measure_video(video, out_dir, start=None, end=None, fps=None):
    """Measure rhythm, holds, moves, look distributions, geometry, and sound sync for VIDEO."""
    video = Path(video).resolve()
    if not video.is_file():
        raise ValueError(f'no such video: {video}')
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    info = probe_video(video)
    an_fps = min(float(fps or info['fps'] or 30.0), FPS_CAP)
    offset = float(start or 0.0)
    stop = min(float(end), info['duration']) if end is not None else info['duration']
    dur = max(0.05, stop - offset)

    energy, energy2, lit, motion = [], [], [], []
    kept = {}                                      # frame index -> picture, at most KEEP_FRAMES, evenly spaced
    keep_every = max(1, int(dur * an_fps / KEEP_FRAMES) + 1)
    step = max(1, int(round(an_fps / 12.0)))        # the motion classes are sampled at about 12 a second, as before
    prev = prev2 = sampled = None
    n = 0
    for rgb in _stream_rgb_frames(video, an_fps, start=offset if start is not None else None,
                                  end=stop if end is not None else None):
        lit.append(_lit_middle(rgb))
        g = _to_gray(rgb)
        gf = g.astype(np.float32)
        energy.append(0.0 if prev is None else float(np.abs(gf - prev).mean()))
        energy2.append(0.0 if prev2 is None else float(np.abs(gf - prev2).mean()))
        prev2, prev = prev, gf
        if n % step == 0:
            if sampled is not None:
                c = _motion_class(sampled, g)
                if c:
                    motion.append(c)
            sampled = g
        if n % keep_every == 0:
            kept[n] = rgb.copy()
        n += 1
    if n == 0:
        raise ValueError(f'{video}: decoded 0 frames')

    def picture_near(i):
        return kept[min(kept, key=lambda k: abs(k - i))]
    energy_arr = np.asarray(energy, dtype=np.float32)
    energy2_arr = np.asarray(energy2, dtype=np.float32)

    cut_frames = _find_cuts(energy_arr)
    segs = _segments(energy_arr, an_fps)
    event_frames = []
    move_starts = {s[1] for idx, s in enumerate(segs) if s[0] == 'move' and idx > 0 and segs[idx - 1][0] == 'hold'}
    for e in sorted(set(cut_frames) | move_starts):
        if event_frames and (e - event_frames[-1]) <= 2:
            if e in cut_frames:
                event_frames[-1] = e
            continue
        event_frames.append(e)

    holds = []
    for kind, a, b in segs:
        if kind != 'hold':
            continue
        mid_t = offset + ((a + b) / 2.0) / an_fps
        sharp = _grab_rgb(video, mid_t)
        frame_rgb = sharp if sharp is not None else picture_near((a + b) // 2)
        lk = _look_frame(frame_rgb)
        holds.append({
            'start_s': round(offset + a / an_fps, 3),
            'end_s': round(offset + b / an_fps, 3),
            'duration_s': round((b - a) / an_fps, 3),
            'drift': round(float(np.median(energy_arr[a:b])), 4),
            **lk,
        })

    moves = []
    for kind, a, b in segs:
        if kind != 'move':
            continue
        d_s = (b - a) / an_fps
        if 0.10 <= d_s <= MOVE_FIT_MAX_S:
            fit = _fit_ease(energy_arr, a, b)
            if fit is not None:
                moves.append({
                    'start_s': round(offset + a / an_fps, 3),
                    'end_s': round(offset + b / an_fps, 3),
                    'duration_s': round(d_s, 3),
                    'peak': fit['peak'],
                    'curve': fit['curve'],
                    'ease_fit': fit['r2'],
                    'follows_speed': bool(_follows_speed(energy_arr, energy2_arr, a, b)),
                    'direction': 'in' if fit['peak'] <= 0.4 else 'out',
                })

    # Palette from representative frame(s).
    mid_rgb = picture_near(n // 2)
    palette = _palette_kmeans(mid_rgb, k=5)

    scene_move = round(motion.count('scene') / len(motion), 3) if len(motion) >= 2 else 0.0
    sheet_move = round(motion.count('sheet') / len(motion), 3) if len(motion) >= 2 else 0.0
    event_times = [round(offset + e / an_fps, 3) for e in event_frames]
    audio_info = measure_audio(video, info['duration']) if info['audio'] else None
    if audio_info:
        s_rate, s_chance, s_lift = _sync_rate(event_times, audio_info['onsets'], info['duration'])
        audio_info.update({'sync_rate': s_rate, 'sync_chance': s_chance, 'sync_lift': s_lift})
    else:
        s_rate, s_chance, s_lift = None, None, None

    hold_durs = [h['duration_s'] for h in holds]
    read_durs = [d for d in hold_durs if d >= READ_HOLD_S] or hold_durs
    move_durs = [round((b - a) / an_fps, 3) for kind, a, b in segs if kind == 'move']
    occ_vals = [h['occupancy'] for h in holds]
    occ_spread = round(float(np.percentile(occ_vals, 90) - np.percentile(occ_vals, 10)), 3) if occ_vals else 0.0

    def wmed(key):
        if not holds:
            return None
        w = np.maximum(1, (np.asarray(hold_durs) * 10).astype(int))
        return round(float(np.median(np.repeat([h[key] for h in holds], w))), 3)

    summary = {
        'events_per_10s': round(10.0 * len(event_times) / dur, 2),
        'median_hold_s': round(float(np.median(read_durs)), 3) if read_durs else 0.0,
        'median_move_s': round(float(np.median(move_durs)), 3) if move_durs else 0.0,
        'drift': wmed('drift') or 0.0,
        'move_share': round(float(np.mean(energy_arr > MOVE_THRESH)), 3),
        'occupancy': wmed('occupancy') or 0.0,
        'occupancy_spread': occ_spread,
        'detail': wmed('detail') or 0.0,
        'bands': wmed('bands') or 0.0,
        'largest_band': wmed('largest_band') or 0.0,
        'ease_fit': round(float(np.mean([m['ease_fit'] for m in moves])), 3) if moves else None,
        'follows_speed': round(float(np.mean([1.0 if m['follows_speed'] else 0.0 for m in moves])), 3) if moves else None,
        'scene_move': scene_move,
        'sheet_move': sheet_move,
        'dark_corners': round(float(np.mean(lit)), 3) if lit else 0.0,
        'tempo': audio_info['tempo']['bpm'] if audio_info and audio_info['tempo'] else None,
        'sync_rate': s_rate,
        'sync_chance': s_chance,
        'sync_lift': s_lift,
    }

    beat_times = event_times or [round(offset + min(0.1, dur / 2), 3)]
    sheets = _render_beats_sheet(video, beat_times, out_dir)
    result = {
        'version': VERSION,
        'video': str(video),
        'duration_s': round(dur, 3),
        'fps': round(info['fps'], 3),
        'analysed_fps': round(an_fps, 3),
        'size': info['size'],
        'summary': summary,
        'cuts': [round(offset + c / an_fps, 3) for c in cut_frames],
        'events': event_times,
        'holds': holds,
        'moves': moves,
        'palette': palette,
        'audio': audio_info,
        'sheets': sheets,
    }
    project.save_json(out_dir / 'measure.json', result)
    return result


def compare_dirs(source_dir, other_dir, mode='refill', beats=None):
    """Compare SOURCE_DIR/measure.json against OTHER_DIR/measure.json under rebuild or refill rules."""
    a = json.loads((Path(source_dir) / 'measure.json').read_text(encoding='utf-8'))
    b = json.loads((Path(other_dir) / 'measure.json').read_text(encoding='utf-8'))
    if a.get('version') != VERSION or b.get('version') != VERSION:
        raise ValueError(f'measure.json version mismatch (expected {VERSION})')

    rows = []
    if mode == 'rebuild':
        src_fps = float(a.get('fps') or a.get('analysed_fps') or 30.0)
        coarse = min(float(a.get('analysed_fps') or src_fps), float(b.get('analysed_fps') or src_fps))
        frame_tol = max(2.0 / max(1.0, src_fps), 1.0 / max(1.0, coarse)) + 1e-6
        ev_a, ev_b = sorted(a.get('events') or []), sorted(b.get('events') or [])
        i = j = 0
        matched, missing, extra = [], [], []
        while i < len(ev_a) and j < len(ev_b):
            if abs(ev_a[i] - ev_b[j]) <= frame_tol:
                matched.append((ev_a[i], ev_b[j]))
                i += 1
                j += 1
            elif ev_a[i] < ev_b[j]:
                missing.append(ev_a[i])
                i += 1
            else:
                extra.append(ev_b[j])
                j += 1
        missing.extend(ev_a[i:])
        extra.extend(ev_b[j:])
        rows.append({'metric': 'events_within_2_frames', 'source': len(ev_a), 'other': len(matched),
                     'delta': len(missing), 'tol': 0, 'status': 'ok' if not missing and len(extra) <= max(2, round(0.15 * len(ev_a))) else 'off'})
        for key in ('events_per_10s', 'median_hold_s', 'median_move_s', 'occupancy'):
            va, vb = a['summary'].get(key), b['summary'].get(key)
            if va is not None and vb is not None:
                tol = REFILL_TOLERANCE[key] * 0.5
                diff = round(abs(va - vb), 3)
                rows.append({'metric': key, 'source': va, 'other': vb, 'delta': diff, 'tol': round(tol, 3),
                             'status': 'ok' if diff <= tol else 'off'})
    else:
        for key, tol in REFILL_TOLERANCE.items():
            va = a['summary'].get(key)
            vb = b['summary'].get(key)
            if va is None and vb is None:
                continue
            if va is None or vb is None:
                # measured in one film and not the other (moves in one, none in the other) is a difference, not a pass
                rows.append({'metric': key, 'source': va, 'other': vb, 'delta': None, 'tol': tol, 'status': 'off'})
                continue
            diff = round(abs(float(va) - float(vb)), 4)
            rows.append({'metric': key, 'source': va, 'other': vb, 'delta': diff, 'tol': tol,
                         'status': 'ok' if diff <= tol else 'off'})
        if beats:
            ba = json.loads(Path(beats[0]).read_text(encoding='utf-8'))
            bb = json.loads(Path(beats[1]).read_text(encoding='utf-8'))
            rows.append({'metric': 'beat_count', 'source': len(ba), 'other': len(bb),
                         'delta': abs(len(ba) - len(bb)), 'tol': 1,
                         'status': 'ok' if abs(len(ba) - len(bb)) <= 1 else 'off'})

    off_metrics = [r['metric'] for r in rows if r['status'] == 'off']
    return {
        'mode': mode,
        'status': 'off-rhythm' if off_metrics else 'on-rhythm',
        'off_count': len(off_metrics),
        'off_metrics': off_metrics,
        'rows': rows,
    }


def _update_film_md_front(film_md_path, key, value):
    """Insert or update a YAML front-matter key in film.md without disturbing its body."""
    if not film_md_path.is_file():
        return False
    text = project.read_text(film_md_path)
    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != '---':
        return False
    end_idx = next((idx for idx in range(1, len(lines)) if lines[idx].strip() == '---'), None)
    if end_idx is None:
        return False
    front = lines[1:end_idx]
    body = lines[end_idx + 1:]
    new_line = f'{key}: {value}'
    replaced = False
    for idx, line in enumerate(front):
        if line.strip().startswith(f'{key}:'):
            front[idx] = new_line
            replaced = True
            break
    if not replaced:
        front.append(new_line)
    updated = '\n'.join(['---', *front, '---', *body]) + ('\n' if text.endswith('\n') else '')
    project.write_atomic(film_md_path, updated)
    return True


def pin_reference(proj_path, ref_video, k=5, out_dir=None):
    """Measure REF.mp4, extract refs/pin story/move/rest-key sheets, and write rhythm-pin.json."""
    proj = Path(proj_path).resolve()
    ref = Path(ref_video).resolve()
    if not ref.is_file():
        raise ValueError(f'no such reference video: {ref}')
    pin_dir = Path(out_dir).resolve() if out_dir else (proj / 'refs' / 'pin')
    meas_dir = pin_dir / 'measure'
    measured = measure_video(ref, meas_dir)

    pack = _load_sibling('pack')
    info = pack.probe_video(ref)
    pack.render_story_sheets(ref, pin_dir)
    move_starts = pack.scan_windows(ref, info['fps'], k)
    for idx, st in enumerate(move_starts, 1):
        pack.render_move_sheet(ref, st, min(st + 1.0, info['duration']), pin_dir / f'move-{idx}.jpg')
    key_t = pack.rest_times(ref, info['duration'], info['fps'], n=6)
    key_files = pack.extract_keys(ref, key_t, pin_dir)

    sm = measured['summary']
    med_hold = sm.get('median_hold_s') or 1.2
    ev10 = sm.get('events_per_10s') or 5.0
    pause_ms = max(180, min(650, int(round(med_hold * 240))))
    punch_every = round(max(1.2, med_hold * 1.5), 2)
    pin_payload = {
        'version': 1,
        'tool': 'measure.py pin',
        'project': str(proj),
        'ref_video': str(ref),
        'ref_sha256': project.file_sha256(ref),
        'pin_dir': str(pin_dir),
        'measure_json': str(meas_dir / 'measure.json'),
        'summary': sm,
        'tolerances': REFILL_TOLERANCE,
        'recommended_cut_settings': {
            'pause_target_ms': pause_ms,
            'pause_target_s': round(pause_ms / 1000.0, 3),
            'min_hold_s': round(max(0.25, med_hold * 0.5), 3),
            'max_hold_s': round(med_hold + REFILL_TOLERANCE['median_hold_s'], 3),
            'target_events_per_10s': ev10,
            'punch_every_s': punch_every,
            'insert_share_target': round(min(0.8, max(0.1, sm.get('move_share') or 0.3)), 3),
        },
        'sheets': {
            'move_windows': move_starts,
            'key_files': key_files,
            'key_times': key_t,
        },
    }
    pin_json_path = proj / 'rhythm-pin.json'
    project.save_json(pin_json_path, pin_payload)
    _update_film_md_front(proj / 'film.md', 'rhythm_pin', 'rhythm-pin.json')
    pin_payload['rhythm_pin'] = str(pin_json_path)
    return pin_payload


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    project.safe_output()
    try:
        if args and args[0] == 'compare':
            ap = argparse.ArgumentParser(prog='measure.py compare',
                                         description='Compare SOURCE_DIR against OTHER_DIR under rebuild or refill rules.')
            ap.add_argument('source', help='folder holding reference measure.json')
            ap.add_argument('other', help='folder holding candidate measure.json')
            ap.add_argument('--as', dest='mode', choices=('rebuild', 'refill'), default='refill')
            ap.add_argument('--beats', nargs=2, metavar=('SRC_BEATS', 'OTHER_BEATS'))
            ap.add_argument('--out', help='optional JSON report path')
            ap.add_argument('--json', action='store_true')
            a = ap.parse_args(args[1:])
            res = compare_dirs(a.source, a.other, a.mode, a.beats)
            if a.out:
                project.save_json(a.out, res)
            if a.json:
                print(json.dumps(res, indent=1))
            else:
                for r in res['rows']:
                    print(f"  {r['status']:3s} {r['metric']}: source {r['source']} vs other {r['other']} (delta {r['delta']}, tol {r['tol']})")
                print(f"{res['status']}: {res['off_count']} of {len(res['rows'])} off")
            return 1 if res['off_count'] else 0

        if args and args[0] == 'pin':
            ap = argparse.ArgumentParser(prog='measure.py pin',
                                         description='Pin a reference video rhythm profile and sheet bundle into PROJECT.')
            ap.add_argument('project', help='project folder')
            ap.add_argument('ref', help='reference MP4/MOV video')
            ap.add_argument('--k', type=int, default=5, help='number of busiest 1s motion sheets (default 5)')
            ap.add_argument('--out', help='sheet folder (default PROJECT/refs/pin)')
            ap.add_argument('--json', action='store_true')
            a = ap.parse_args(args[1:])
            res = pin_reference(a.project, a.ref, k=a.k, out_dir=a.out)
            if a.json:
                print(json.dumps(res, indent=1))
            else:
                sm = res['summary']
                rec = res['recommended_cut_settings']
                print(f"Pinned {Path(res['ref_video']).name} -> {res['rhythm_pin']}")
                print(f"  events/10s={sm['events_per_10s']}, median_hold={sm['median_hold_s']}s, recommended pause={rec['pause_target_s']}s, punch_every={rec['punch_every_s']}s")
            return 0

        ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
        ap.add_argument('video', help='video file to measure')
        ap.add_argument('--out', required=True, help='output directory for measure.json and beats-1.jpg')
        ap.add_argument('--from', dest='start', type=float, help='optional start time in seconds')
        ap.add_argument('--to', dest='end', type=float, help='optional end time in seconds')
        ap.add_argument('--fps', type=float, help='cap analysis frame rate')
        ap.add_argument('--json', action='store_true')
        a = ap.parse_args(args)
        res = measure_video(a.video, a.out, a.start, a.end, a.fps)
        if a.json:
            print(json.dumps(res, indent=1))
        else:
            sm = res['summary']
            print(f"{Path(res['video']).name}: {res['duration_s']}s @ {res['fps']}fps, "
                  f"{sm['events_per_10s']} events/10s, median hold {sm['median_hold_s']}s, move share {sm['move_share']:.0%}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as err:
        print(f'measure.py: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
