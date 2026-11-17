#!/usr/bin/env python3
"""Double-blind relative lineup packs (EYES.md) for legible-film create and cut outputs.

  python pack.py FILM [--against REF.mp4 ...] [--k 5] [--k-alone 10]
                      [--ref-first N --ref-last M] [--keys T1,...]
                      [--out DIR] [--reads DIR] [--json]
  python pack.py record PACK_KEY --lineup-a FILE --lineup-b FILE
                        [--fault-finder FILE] [--family-a NAME] [--family-b NAME]
                        [--yardstick LETTER_OR_STEM] [--out FILE] [--json]

Creates a blinded review bundle under a neutral random folder in --reads (no film name,
version, or label in any path or image):
  lineup/A ... lineup/D   standardised 2 fps story sheets (4 cols x 440 px) +
                          native-fps 1-second motion sheets for the K busiest windows
  alone/                  ours alone: story sheets, K_alone motion sheets, 5 full-size rest keys

The key file (pack-N-KEY.txt + pack-N-key.json) and reader briefs are written outside the pack
under --out so readers only ever see the pack folder. `record` validates two cross-family vision
readers against the unblinded key and writes blind-pack.json for check.py and evals.
Exit 0 on success, 2 on error.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import random
import re
import secrets
import shutil
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
LETTERS = 'ABCDEF'
STORY_W, STORY_COLS, STORY_ROWS, STORY_FPS, STORY_STRIP = 440, 4, 5, 2, 24
MOVE_K, MOVE_COLS, MOVE_ROWS, MOVE_W, MOVE_STRIP = 5, 6, 10, 320, 18
ALONE_K = 10
NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0
AMATEUR_TIERS = {'beginner', 'hobbyist', 'skilled hobbyist'}


def _load_sibling(name):
    spec = importlib.util.spec_from_file_location('lf_pack_' + name, HERE / f'{name}.py')
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


def default_reads_root():
    env = os.environ.get('LF_READS') or os.environ.get('VD_READS')
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / 'legible-film-reads'


def probe_video(video):
    ffprobe = _find_tool('ffprobe')
    cmd = [
        ffprobe, '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,r_frame_rate,nb_frames:format=duration',
        '-of', 'json', str(video),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                         creationflags=NO_WINDOW)
    if res.returncode:
        raise ValueError(f'{video}: ffprobe failed ({res.stderr.strip()[-200:]})')
    data = json.loads(res.stdout or '{}')
    streams = data.get('streams') or []
    if not streams:
        raise ValueError(f'{video}: no video stream found')
    st = streams[0]
    w, h = int(st['width']), int(st['height'])
    fps = float(Fraction(str(st.get('r_frame_rate') or '30/1')))
    dur = float((data.get('format') or {}).get('duration') or 0)
    if dur <= 0 and fps > 0 and st.get('nb_frames'):
        dur = int(st['nb_frames']) / fps
    return {'width': w, 'height': h, 'fps': fps, 'duration': dur, 'aspect': w / max(1, h)}


def _font(px):
    try:
        return ImageFont.load_default(size=px)
    except TypeError:
        return ImageFont.load_default()


def _edge_score(gray):
    """Fast edge energy estimate using OpenCV Canny when present, else numpy gradients."""
    if cv2 is not None:
        edges = cv2.Canny(gray, 40, 120)
        return float(np.mean(edges > 0))
    gx = np.abs(np.diff(gray.astype(np.int16), axis=1))
    gy = np.abs(np.diff(gray.astype(np.int16), axis=0))
    return float(((gx[:, :-1] if gx.shape[1] > 1 else gx).mean() +
                  (gy[:-1, :] if gy.shape[0] > 1 else gy).mean()) / 255.0)


def scan_motion_scores(video, w=320, h=180):
    """Per-frame change series Combining luminance diff and edge detail."""
    ffmpeg = _find_tool('ffmpeg')
    cmd = [ffmpeg, '-v', 'error', '-i', str(video), '-vf', f'scale={w}:{h}',
           '-f', 'rawvideo', '-pix_fmt', 'gray', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    frame_bytes = w * h
    count = len(raw) // frame_bytes
    if count < 2:
        return np.zeros(0, dtype=np.float32)
    prev = None
    diffs = np.zeros(count - 1, dtype=np.float32)
    for idx in range(count):
        arr = np.frombuffer(raw, dtype=np.uint8, count=frame_bytes, offset=idx * frame_bytes).reshape(h, w)
        if prev is not None:
            mad = float(np.abs(arr.astype(np.int16) - prev.astype(np.int16)).mean())
            diffs[idx - 1] = mad * (0.5 + _edge_score(arr))
        prev = arr
    return diffs


def scan_windows(video, fps, k, win=1.0, spans=None):
    """Pick the K busiest non-overlapping 1-second windows in time order."""
    scores = scan_motion_scores(video)
    n = max(1, int(round(win * fps)))
    if not len(scores) or k <= 0:
        return []
    if len(scores) < n:
        return [0.0]
    rolling = np.convolve(scores, np.ones(n, dtype=np.float64), mode='valid')
    if spans:
        keep = np.zeros(len(rolling), dtype=bool)
        for a, b in spans:
            i0 = max(0, int(np.ceil(a * fps)))
            i1 = max(i0 + 1, int(np.floor(b * fps)) - n + 1)
            keep[i0:min(len(keep), i1)] = True
        rolling[~keep] = -1.0
    picks = []
    for _ in range(k):
        best = int(np.argmax(rolling))
        if rolling[best] <= 0:
            break
        picks.append(best)
        rolling[max(0, best - n):best + n] = -1.0
    if not picks:
        picks = [0]
    return sorted(round(i / fps, 3) for i in picks)


def rest_times(video, dur, fps, n=5):
    """Pick N full-size key timestamps anchored in the quietest holds across N equal segments."""
    diffs = scan_motion_scores(video)
    if len(diffs) < 2:
        return [round(dur * (i + 0.5) / max(1, n), 3) for i in range(n)]
    thresh = max(0.35, float(np.percentile(diffs, 33)))
    quiet = diffs <= thresh
    out = []
    for k in range(n):
        a = int(len(diffs) * k / n)
        b = max(a + 1, int(len(diffs) * (k + 1) / n))
        best, i = None, a
        while i < b:
            if not quiet[i]:
                i += 1
                continue
            j = i
            while j < b and quiet[j]:
                j += 1
            if best is None or (j - i) > (best[1] - best[0]):
                best = (i, j)
            i = j
        frame = (best[0] + best[1]) // 2 if best else a + int(np.argmin(diffs[a:b]))
        out.append(round(min(max(0.0, frame / max(1.0, fps)), max(0.0, dur - 0.02)), 3))
    return out


def _pad_vf(tw, th, target_aspect):
    """Build an ffmpeg scale+pad chain to match a shared aspect ratio with neutral black bars."""
    cur_aspect = tw / max(1, th)
    if abs(cur_aspect - target_aspect) <= 0.02:
        return f'scale={tw}:{th}'
    if cur_aspect > target_aspect:
        canvas_h = max(2, int(round(tw / target_aspect / 2) * 2))
        return f'scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:black'
    canvas_w = max(2, int(round(th * target_aspect / 2) * 2))
    return f'scale={canvas_w}:{th}:force_original_aspect_ratio=decrease,pad={canvas_w}:{th}:(ow-iw)/2:(oh-ih)/2:black'


def render_story_sheets(video, out_dir, start=0.0, length=None, target_aspect=None, target_fps=None, first=1):
    """Write story-NN.jpg from number FIRST on, at 2 fps, 4 cols, 440 px wide tiles with 24 px top timestamp band.
    A second span into the same folder starts after the first span's sheets: each began at 01, so a reference's
    ending overwrote its beginning."""
    ffmpeg = _find_tool('ffmpeg')
    info = probe_video(video)
    asp = target_aspect or info['aspect']
    tile_w = STORY_W
    tile_h = max(2, int(round(tile_w / asp / 2) * 2))
    src_h = max(2, int(round(tile_w / info['aspect'] / 2) * 2))
    vf_bits = [f'fps={STORY_FPS}', f'scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease',
               f'pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2:black']
    if abs(info['aspect'] - asp) <= 0.02:
        vf_bits = [f'fps={STORY_FPS}', f'scale={tile_w}:{tile_h}']
    cmd = [ffmpeg, '-v', 'error', '-ss', f'{start:.3f}', '-i', str(video)]
    if length is not None:
        cmd += ['-t', f'{length:.3f}']
    cmd += ['-vf', ','.join(vf_bits), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    frame_bytes = tile_w * tile_h * 3
    count = len(raw) // frame_bytes
    items = [(start + idx / STORY_FPS,
              Image.frombytes('RGB', (tile_w, tile_h), raw[idx * frame_bytes:(idx + 1) * frame_bytes]))
             for idx in range(count)]
    out_dir.mkdir(parents=True, exist_ok=True)
    font = _font(15)
    per = STORY_COLS * STORY_ROWS
    written = 0
    for s in range(0, max(1, len(items)), per):
        chunk = items[s:s + per]
        if not chunk:
            break
        rows_n = (len(chunk) + STORY_COLS - 1) // STORY_COLS
        sheet = Image.new('RGB', (tile_w * STORY_COLS, (tile_h + STORY_STRIP) * rows_n), (18, 18, 18))
        draw = ImageDraw.Draw(sheet)
        for k, (t, im) in enumerate(chunk):
            x = (k % STORY_COLS) * tile_w
            y = (k // STORY_COLS) * (tile_h + STORY_STRIP)
            sheet.paste(im, (x, y + STORY_STRIP))
            draw.rectangle((x, y, x + tile_w - 1, y + STORY_STRIP - 1), fill=(0, 0, 0))
            draw.text((x + 8, y + 3), f'{t:05.2f}s', fill=(255, 255, 255), font=font)
        written += 1
        sheet.save(out_dir / f'story-{first + written - 1:02d}.jpg', quality=90)
    return written


def render_move_sheet(video, start, end, out_path, target_aspect=None, target_fps=None):
    """Render every native (or standardized) frame in [start, end] on a stamped grid."""
    ffmpeg = _find_tool('ffmpeg')
    info = probe_video(video)
    fps = target_fps or info['fps']
    asp = target_aspect or info['aspect']
    tile_w = MOVE_W
    tile_h = max(2, int(round(tile_w / asp / 2) * 2))
    vf_bits = []
    if target_fps and abs(info['fps'] - target_fps) > 1.0:
        vf_bits.append(f'fps={target_fps:.3f}')
    if abs(info['aspect'] - asp) <= 0.02:
        vf_bits.append(f'scale={tile_w}:{tile_h}')
    else:
        vf_bits.append(f'scale={tile_w}:{tile_h}:force_original_aspect_ratio=decrease')
        vf_bits.append(f'pad={tile_w}:{tile_h}:(ow-iw)/2:(oh-ih)/2:black')
    span = max(0.05, end - start)
    cmd = [ffmpeg, '-v', 'error', '-ss', f'{start:.4f}', '-t', f'{span:.4f}', '-i', str(video),
           '-vf', ','.join(vf_bits), '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    raw = subprocess.run(cmd, capture_output=True, check=True, creationflags=NO_WINDOW).stdout
    frame_bytes = tile_w * tile_h * 3
    count = len(raw) // frame_bytes
    if count == 0:
        return 0
    max_tiles = MOVE_COLS * MOVE_ROWS
    count = min(count, max_tiles)
    rows_n = (count + MOVE_COLS - 1) // MOVE_COLS
    sheet = Image.new('RGB', (tile_w * MOVE_COLS, (tile_h + MOVE_STRIP) * rows_n), (22, 22, 22))
    draw = ImageDraw.Draw(sheet)
    font = _font(12)
    base_idx = int(round(start * fps))
    for k in range(count):
        im = Image.frombytes('RGB', (tile_w, tile_h), raw[k * frame_bytes:(k + 1) * frame_bytes])
        t = start + k / max(1.0, fps)
        x = (k % MOVE_COLS) * tile_w
        y = (k // MOVE_COLS) * (tile_h + MOVE_STRIP)
        sheet.paste(im, (x, y + MOVE_STRIP))
        draw.rectangle((x, y, x + tile_w - 1, y + MOVE_STRIP - 1), fill=(0, 0, 0))
        draw.text((x + 4, y + 2), f'#{base_idx + k:04d}  {t:06.3f}s', fill=(255, 232, 102), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=88)
    return count


def extract_keys(video, times, out_dir):
    """Extract full-size rest keys key-1.png .. key-N.png in out_dir."""
    ffmpeg = _find_tool('ffmpeg')
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for idx, t in enumerate(times, 1):
        target = out_dir / f'key-{idx}.png'
        cmd = [ffmpeg, '-v', 'error', '-y', '-ss', f'{t:.3f}', '-i', str(video), '-frames:v', '1', str(target)]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                             creationflags=NO_WINDOW)
        if res.returncode or not target.is_file():
            raise ValueError(f'failed to extract key frame at {t:.2f} s: {res.stderr.strip()[-200:]}')
        made.append(target.name)
    return made


def deal(n_pack, count, before=None):
    """Deterministic per-(pack, count) shuffle where ours never repeats its letter from pack n_pack - 1."""
    if count > len(LETTERS):
        raise ValueError(f'lineup supports at most {len(LETTERS)} films, got {count}')
    order = list(LETTERS[:count])
    prev = None
    for n in range(1, n_pack + 1):
        rng = random.Random(f'pack {n} of {count}')
        order = list(LETTERS[:count])
        rng.shuffle(order)
        avoid = before if n == n_pack and before is not None else (prev[0] if prev else None)
        if avoid is not None and count > 1 and order[0] == avoid:
            j = 1 + rng.randrange(count - 1)
            order[0], order[j] = order[j], order[0]
        prev = order
    return order


def ours_before(out_root, n_pack):
    """Previous ours letter from pack-(n-1)-key.json or pack-(n-1)-KEY.txt."""
    for n in range(n_pack - 1, 0, -1):
        jf = Path(out_root) / f'pack-{n}-key.json'
        if jf.is_file():
            try:
                data = json.loads(jf.read_text(encoding='utf-8'))
                if data.get('ours_letter'):
                    return data['ours_letter']
            except (OSError, ValueError):
                pass
        tf = Path(out_root) / f'pack-{n}-KEY.txt'
        if tf.is_file():
            for line in tf.read_text(encoding='utf-8', errors='replace').splitlines():
                if line.startswith('lineup/') and ' = ours' in line:
                    return line[len('lineup/'):].split(' ', 1)[0]
    return None


def _spans_of(dur, first=None, last=None):
    if first is None and last is None:
        return None
    out = [(0.0, min(dur, first))] if first else []
    if last:
        out.append((max(first or 0.0, dur - last), dur))
    return out


def _render_briefs(out_root, n_pack, pack, film_info, letter_count, k, k_alone):
    """Write ready-to-send blind reader briefs outside the pack."""
    lineup_brief = '\n'.join([
        f'You are a reader in a blind comparison of {letter_count} short films. '
        'This is a read-only task: do not edit, create or delete any file, network or subagents.',
        '',
        f'Open every image inside {pack / "lineup"} (folders A..{LETTERS[letter_count - 1]}).',
        'Each folder holds story-01.jpg (2 fps) and move-1..K.jpg (every native frame of the K busiest seconds).',
        'You cannot hear the films; judge picture and motion only.',
        '',
        'Answer in JSON (or labeled Markdown matching these headings):',
        '1. overall_ranking: ordered list of letters, best crafted first.',
        '2. For each letter: tier (beginner | hobbyist | freelance | studio), pacing (1-10), '
        'visual_clutter (1-10, 10=cleanest), callout_placement (1-10), strongest, weakest, and tells.',
        '3. steals: concrete craft choices worth keeping.',
    ]) + '\n'
    alone_brief = '\n'.join([
        f'You are the fault-finder for one {film_info["duration"]:.1f}s film ({film_info["fps"]:g} fps). '
        'This is a read-only task: find faults, praise is not needed.',
        '',
        f'Open every image inside {pack / "alone"}: story-01.jpg (2 fps), '
        f'move-1..{k_alone}.jpg (every frame of the {k_alone} busiest seconds), and key-1..5.png (full size).',
        '',
        'Answer:',
        '1. In two sentences from picture alone: what it presents and claims.',
        '2. Step-by-step tellback of what happens.',
        '3. Faults most damaging first (sheet, frame/time, broken text, overlaps, dead holds, seam flashes).',
        '4. Tier guess (beginner | hobbyist | freelance | studio) and the main tell.',
    ]) + '\n'
    lb_path = out_root / f'pack-{n_pack}-brief-lineup.txt'
    ab_path = out_root / f'pack-{n_pack}-brief-alone.txt'
    project.write_atomic(lb_path, lineup_brief)
    project.write_atomic(ab_path, alone_brief)
    return lb_path, ab_path


def make_pack(film, against, out_root, ref_first=None, ref_last=None, key_times=None,
              k=MOVE_K, k_alone=ALONE_K, reads_root=None):
    """Build a blind lineup + alone pack under a neutral random folder in reads_root."""
    film = Path(film).resolve()
    against = [Path(r).resolve() for r in (against or [])]
    if not film.is_file():
        raise ValueError(f'no such film: {film}')
    for r in against:
        if not r.is_file():
            raise ValueError(f'no such reference film: {r}')
    if len(against) > len(LETTERS) - 1:
        raise ValueError(f'at most {len(LETTERS) - 1} --against films supported, got {len(against)}')

    out_root = Path(out_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    n_pack = 1
    while (out_root / f'pack-{n_pack}-KEY.txt').exists() or (out_root / f'pack-{n_pack}-key.json').exists():
        n_pack += 1

    reads = Path(reads_root) if reads_root else default_reads_root()
    reads.mkdir(parents=True, exist_ok=True)
    pack = reads / f'r-{secrets.token_hex(6)}'
    while pack.exists():
        pack = reads / f'r-{secrets.token_hex(6)}'
    pack.mkdir(parents=True)

    film_sha = project.file_sha256(film)
    all_videos = [film, *against]
    probes = {v: probe_video(v) for v in all_videos}
    aspects = [probes[v]['aspect'] for v in all_videos]
    rates = [probes[v]['fps'] for v in all_videos]
    std_aspect = aspects[0] if max(aspects) - min(aspects) <= 0.02 else round(sum(aspects) / len(aspects), 4)
    std_fps = None if max(rates) - min(rates) <= 1.0 else max(rates)

    prev_ours = ours_before(out_root, n_pack)
    letters_meta = {}
    ours_letter = None
    yardstick_letters = []

    if against:
        dealt = deal(n_pack, 1 + len(against), prev_ours)
        ours_letter = dealt[0]
        for idx, vid in enumerate(all_videos):
            letter = dealt[idx]
            role = 'ours' if idx == 0 else f'against_{idx}'
            if idx > 0:
                yardstick_letters.append(letter)
            info = probes[vid]
            spans = None if idx == 0 else _spans_of(info['duration'], ref_first, ref_last)
            ldir = pack / 'lineup' / letter
            if spans:
                story_n = 0
                for a, b in spans:
                    story_n += render_story_sheets(vid, ldir, start=a, length=b - a,
                                                   target_aspect=std_aspect, target_fps=std_fps, first=story_n + 1)
            else:
                story_n = render_story_sheets(vid, ldir, target_aspect=std_aspect, target_fps=std_fps)
            starts = scan_windows(vid, info['fps'], k, spans=spans)
            for m_i, st_t in enumerate(starts, 1):
                render_move_sheet(vid, st_t, min(st_t + 1.0, info['duration']),
                                  ldir / f'move-{m_i}.jpg', target_aspect=std_aspect, target_fps=std_fps)
            letters_meta[letter] = {
                'letter': letter,
                'role': role,
                'stem': vid.stem,
                'path': str(vid),
                'sha256': project.file_sha256(vid),
                'story_sheets': story_n,
                'windows': starts,
            }

    # Alone folder for ours: 2 fps story, k_alone motion sheets, 5 full-size rest keys.
    f_info = probes[film]
    alone_dir = pack / 'alone'
    alone_story_n = render_story_sheets(film, alone_dir, target_aspect=f_info['aspect'])
    alone_starts = scan_windows(film, f_info['fps'], k_alone)
    for m_i, st_t in enumerate(alone_starts, 1):
        render_move_sheet(film, st_t, min(st_t + 1.0, f_info['duration']), alone_dir / f'move-{m_i}.jpg')
    k_times = list(key_times) if key_times else rest_times(film, f_info['duration'], f_info['fps'], n=5)
    key_files = extract_keys(film, k_times, alone_dir)

    key_txt = out_root / f'pack-{n_pack}-KEY.txt'
    lines = [
        f'pack-{n_pack}, made from {film.name}' + (f' against {", ".join(r.name for r in against)}' if against else ' alone'),
        f'the pack: {pack}',
        f'film_sha256: {film_sha}',
    ]
    for letter in sorted(letters_meta):
        row = letters_meta[letter]
        role_txt = 'ours' if row['role'] == 'ours' else row['role'].replace('_', ' ')
        w_txt = ', '.join(f'{t:.2f}' for t in row['windows']) or 'none'
        lines.append(
            f"lineup/{letter} = {role_txt}: {Path(row['path']).name} ({row['path']}); "
            f"{row['story_sheets']} story sheet(s); stretches from {w_txt} s"
        )
    lines.append(
        f"alone/ = ours: {alone_story_n} story sheet(s); "
        f"stretches from {', '.join(f'{t:.2f}' for t in alone_starts) or 'none'} s; "
        f"keys {', '.join(key_files)} at {', '.join(f'{t:.2f}' for t in k_times)} s"
    )
    project.write_atomic(key_txt, '\n'.join(lines) + '\n')

    key_json_path = out_root / f'pack-{n_pack}-key.json'
    key_payload = {
        'version': 1,
        'pack_number': n_pack,
        'pack_dir': str(pack),
        'film_path': str(film),
        'film_sha256': film_sha,
        'previous_ours_letter': prev_ours,
        'ours_letter': ours_letter,
        'yardstick_letters': yardstick_letters,
        'letters': letters_meta,
        'alone': {
            'dir': str(alone_dir),
            'story_sheets': alone_story_n,
            'windows': alone_starts,
            'key_times': k_times,
            'key_files': key_files,
        },
        'standardized': {'aspect': std_aspect, 'fps': std_fps},
    }
    project.save_json(key_json_path, key_payload)
    lb_path, ab_path = _render_briefs(out_root, n_pack, pack, f_info, max(1, len(letters_meta)), k, k_alone)
    key_payload['key_txt'] = str(key_txt)
    key_payload['key_json'] = str(key_json_path)
    key_payload['brief_lineup'] = str(lb_path)
    key_payload['brief_alone'] = str(ab_path)
    return key_payload


def _load_key(key_path):
    p = Path(key_path)
    if not p.is_file():
        raise ValueError(f'no such key file: {p}')
    if p.suffix.lower() == '.json':
        return json.loads(p.read_text(encoding='utf-8'))
    cand = p.with_name(p.name.replace('-KEY.txt', '-key.json'))
    if cand.is_file():
        return json.loads(cand.read_text(encoding='utf-8'))
    raise ValueError(f'expected pack-N-key.json beside {p}')


def _parse_reader_response(path, family_override=None, known_letters=()):
    raw = Path(path).read_text(encoding='utf-8', errors='replace')
    stripped = raw.strip()
    if stripped.startswith('{'):
        data = json.loads(stripped)
        fam = family_override or data.get('model_family') or data.get('family') or ''
        ranking = [str(x).strip().upper() for x in (data.get('overall_ranking') or data.get('ranking') or []) if str(x).strip()]
        films = {}
        for k, v in (data.get('films') or {}).items():
            lk = str(k).strip().upper()
            films[lk] = dict(v) if isinstance(v, dict) else {'note': str(v)}
        steals = list(data.get('steals') or [])
        return {'model_family': str(fam).strip().lower(), 'ranking': ranking, 'films': films, 'steals': steals}

    fam = family_override or ''
    m_fam = re.search(r'^model[_\s-]*family\s*:\s*(.+)$', raw, re.MULTILINE | re.IGNORECASE)
    if not fam and m_fam:
        fam = m_fam.group(1).strip().lower()
    ranking = []
    m_rk = re.search(r'(?:overall_ranking|ranking)\s*[:\-]\s*([A-F](?:\s*[,>]\s*[A-F])+)', raw, re.IGNORECASE)
    if m_rk:
        ranking = [x.strip().upper() for x in re.split(r'[,>]', m_rk.group(1)) if x.strip()]
    else:
        for line in raw.splitlines():
            m = re.match(r'^\s*(?:\d+[\.\)]|-)\s*(?:lineup/)?([A-F])\b', line)
            if m and m.group(1) not in ranking:
                ranking.append(m.group(1))
    films = {}
    for letter in known_letters or ranking:
        block_re = re.compile(rf'\b{letter}\b[^\n]*?(beginner|skilled hobbyist|hobbyist|freelance(?: motion designer)?|professional studio|studio)', re.IGNORECASE)
        tier = None
        mb = block_re.search(raw)
        if mb:
            t = mb.group(1).lower()
            if 'beginner' in t:
                tier = 'beginner'
            elif 'hobbyist' in t:
                tier = 'hobbyist'
            elif 'freelance' in t:
                tier = 'freelance'
            elif 'studio' in t:
                tier = 'studio'
        films[letter] = {'tier': tier}
    return {'model_family': fam, 'ranking': ranking, 'films': films, 'steals': []}


def record_readings(key_path, lineup_a, lineup_b, fault_finder=None, family_a=None, family_b=None,
                    yardstick=None, out=None):
    """Validate two cross-family blind lineup readings against key_path and write blind-pack.json."""
    key = _load_key(key_path)
    ours = key.get('ours_letter')
    letters = key.get('letters') or {}
    if not ours or not letters:
        raise ValueError('key file does not describe a blind lineup (use --against when calling pack.py)')

    y_letter = None
    if yardstick:
        yu = yardstick.strip().upper()
        if yu in letters and yu != ours:
            y_letter = yu
        else:
            for l, info in letters.items():
                if l != ours and yardstick.lower() in info.get('stem', '').lower():
                    y_letter = l
                    break
        if not y_letter:
            raise ValueError(f'yardstick {yardstick!r} did not match any --against film in the lineup')
    else:
        ys = [l for l in (key.get('yardstick_letters') or list(letters)) if l != ours]
        y_letter = ys[0] if ys else None

    ra = _parse_reader_response(lineup_a, family_a, known_letters=letters.keys())
    rb = _parse_reader_response(lineup_b, family_b, known_letters=letters.keys())
    # a family named two ways ("Claude", "claude opus") is one family; empty is none
    fa = (ra['model_family'] or '').strip().lower().split()[0] if (ra['model_family'] or '').strip() else ''
    fb = (rb['model_family'] or '').strip().lower().split()[0] if (rb['model_family'] or '').strip() else ''
    cross_family = bool(fa and fb and fa != fb)

    def eval_reader(r):
        rk = r['ranking']
        ours_pos = rk.index(ours) + 1 if ours in rk else None
        y_pos = rk.index(y_letter) + 1 if y_letter and y_letter in rk else None
        ours_info = r['films'].get(ours) or {}
        y_info = (r['films'].get(y_letter) or {}) if y_letter else {}
        tier = str(ours_info.get('tier') or '').lower()
        below_y = bool(ours_pos and y_pos and ours_pos > y_pos)
        dims = {}
        for d in ('pacing', 'visual_clutter', 'callout_placement'):
            ov = ours_info.get(d)
            yv = y_info.get(d)
            dims[d] = {'ours': ov, 'yardstick': yv}
            if isinstance(ov, (int, float)) and isinstance(yv, (int, float)) and ov < yv:
                below_y = True
        return {
            'model_family': r['model_family'] or None,
            'ours_rank': ours_pos,
            'yardstick_rank': y_pos,
            'ours_tier': tier or None,
            'amateur_flag': tier in AMATEUR_TIERS,
            'below_yardstick': below_y,
            'dimensions': dims,
            'steals': r.get('steals') or [],
        }

    ea, eb = eval_reader(ra), eval_reader(rb)
    both_amateur = ea['amateur_flag'] and eb['amateur_flag']
    both_below = ea['below_yardstick'] and eb['below_yardstick']

    reasons = []
    # a reading counts only when it is one: every letter ranked once, a tier for ours from the brief's four, and each
    # dimension a number from 1 to 10. Two responses holding nothing but a model family had passed, with no ranking
    for name, r, e in (('reader A', ra, ea), ('reader B', rb, eb)):
        rk = r['ranking'] or []
        if sorted(rk) != sorted(letters) or len(set(rk)) != len(rk):
            reasons.append(f'{name} did not rank every film once ({rk or "no ranking"})')
        if e['ours_tier'] not in ('beginner', 'hobbyist', 'skilled hobbyist', 'freelance', 'studio'):
            reasons.append(f'{name} gave ours no tier the brief names ({e["ours_tier"] or "none"})')
        for d, v in e['dimensions'].items():
            if not (isinstance(v['ours'], (int, float)) and 1 <= v['ours'] <= 10):
                reasons.append(f'{name} scored ours no {d} from 1 to 10 ({v["ours"]!r})')
    if not cross_family:
        reasons.append(f'readers are not cross-family ({fa or "missing"} vs {fb or "missing"})')
    if both_amateur:
        reasons.append(f'both lineup readers flagged ours as beginner/hobbyist ({ea["ours_tier"]}, {eb["ours_tier"]})')
    if both_below:
        reasons.append(f'both lineup readers ranked ours below yardstick {y_letter}')

    ff_summary = None
    if fault_finder and Path(fault_finder).is_file():
        ff_raw = Path(fault_finder).read_text(encoding='utf-8', errors='replace').strip()
        ff_summary = {'file': str(fault_finder), 'excerpt': ff_raw[:600]}

    dim_avg = {}
    for d in ('pacing', 'visual_clutter', 'callout_placement'):
        vals = [e['dimensions'][d]['ours'] for e in (ea, eb) if isinstance(e['dimensions'][d]['ours'], (int, float))]
        dim_avg[d] = round(sum(vals) / len(vals), 2) if vals else None

    result = {
        'version': 1,
        'tool': 'pack.py record',
        'pack_number': key.get('pack_number'),
        'pack_dir': key.get('pack_dir'),
        'film_path': key.get('film_path'),
        'film_sha256': key.get('film_sha256'),
        'ours_letter': ours,
        'yardstick_letter': y_letter,
        'yardstick_stem': (letters.get(y_letter) or {}).get('stem') if y_letter else None,
        'cross_family': cross_family,
        'families': [fa or None, fb or None],
        'readers': {'a': ea, 'b': eb},
        'dimension_averages': dim_avg,
        'both_flagged_amateur': both_amateur,
        'both_below_yardstick': both_below,
        'steals': list(dict.fromkeys([*ea['steals'], *eb['steals']])),
        'fault_finder': ff_summary,
        'status': 'pass' if not reasons else 'look',   # every reason, an incomplete reading's too, keeps it from passing
        'reasons': reasons,
    }
    out_path = Path(out) if out else Path(key_path).parent / 'blind-pack.json'
    project.save_json(out_path, result)
    result['out'] = str(out_path)
    return result


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    project.safe_output()
    try:
        if args and args[0] == 'record':
            ap = argparse.ArgumentParser(prog='pack.py record',
                                         description='Record two cross-family blind lineup readings against a key.')
            ap.add_argument('key', help='pack-N-key.json or pack-N-KEY.txt')
            ap.add_argument('--lineup-a', required=True, help='first lineup reader JSON or text')
            ap.add_argument('--lineup-b', required=True, help='second lineup reader JSON or text')
            ap.add_argument('--fault-finder', help='optional fault-finder reading text/JSON')
            ap.add_argument('--family-a', help='model family for reader A (e.g. anthropic, google, openai)')
            ap.add_argument('--family-b', help='model family for reader B (must differ from family-a)')
            ap.add_argument('--yardstick', help='yardstick letter or film stem (default first --against film)')
            ap.add_argument('--out', help='where to write blind-pack.json')
            ap.add_argument('--json', action='store_true')
            a = ap.parse_args(args[1:])
            res = record_readings(a.key, a.lineup_a, a.lineup_b, a.fault_finder,
                                  a.family_a, a.family_b, a.yardstick, a.out)
            if a.json:
                print(json.dumps(res, indent=1))
            else:
                print(f"blind-pack {res['status']}: ours={res['ours_letter']} vs {res['yardstick_letter']}, "
                      f"cross_family={res['cross_family']} -> {res['out']}")
                for r in res['reasons']:
                    print(f'  look: {r}')
            return 0

        ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0],
                                     formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
        ap.add_argument('film', help='rendered video file (e.g. cuts/v001/preview.mp4)')
        ap.add_argument('--against', action='append', metavar='REF',
                        help='reference or yardstick cut (1..5 films) for the blind lineup')
        ap.add_argument('--k', type=int, default=MOVE_K, help=f'busiest 1s stretches per lineup film (default {MOVE_K})')
        ap.add_argument('--k-alone', type=int, default=ALONE_K, help=f'busiest 1s stretches in alone/ (default {ALONE_K})')
        ap.add_argument('--ref-first', type=float, help='sample only first N s of each --against film')
        ap.add_argument('--ref-last', type=float, help='sample only last M s of each --against film')
        ap.add_argument('--keys', help='comma-separated timestamps in seconds for the 5 full-size rest keys')
        ap.add_argument('--out', help='folder outside the pack where pack-N-KEY.txt and briefs go (default alongside FILM)')
        ap.add_argument('--reads', help='neutral root folder where blinded packs are created')
        ap.add_argument('--json', action='store_true')
        a = ap.parse_args(args)
        film = Path(a.film).resolve()
        out_root = Path(a.out) if a.out else (film.parent / 'qa' if film.parent.name.startswith('v') else film.parent)
        key_times = [float(x) for x in a.keys.split(',')] if a.keys else None
        payload = make_pack(film, a.against or [], out_root, a.ref_first, a.ref_last,
                            key_times, k=a.k, k_alone=a.k_alone, reads_root=a.reads)
        if a.json:
            print(json.dumps(payload, indent=1))
        else:
            print(f"pack-{payload['pack_number']}: {payload['pack_dir']}")
            print(f"key (never give to readers): {payload['key_txt']}")
        return 0
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as err:
        print(f'pack.py: {err}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
