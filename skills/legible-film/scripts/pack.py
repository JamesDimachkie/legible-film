#!/usr/bin/env python3
"""Double-blind relative lineup packs (EYES.md) for legible-film create and cut outputs.

  python pack.py FILM [--against REF.mp4 ...] [--k 5] [--k-alone 10]
                      [--ref-first N --ref-last M] [--keys T1,...]
                      [--out DIR] [--reads DIR] [--alone-reads DIR] [--json]
  python pack.py record PACK_KEY --lineup-a FILE --lineup-b FILE
                        [--fault-finder FILE] [--family-a NAME] [--family-b NAME]
                        [--yardstick LETTER_OR_STEM] [--out FILE] [--json]

Creates a blinded review bundle under a neutral random folder in --reads (no film name,
version, or label in any path or image):
  lineup/A ... lineup/D   standardised 2 fps story sheets (4 cols x 440 px) +
                          native-fps 1-second motion sheets for the K busiest windows
  alone/                  ours alone: story sheets, K_alone motion sheets, 5 full-size rest keys

With --against, alone/ goes into a folder of its own (a neutral random folder under --alone-reads, by default
READS-alone beside the --reads root), never under the readers' root: its unlettered sheets of ours matched one
letter byte for byte. The key file
(pack-N-KEY.txt + pack-N-key.json) and reader briefs are written outside the pack under --out so readers only
ever see the pack folder. `record` validates two cross-family vision
readers against the unblinded key and writes blind-pack.json for check.py and evals.
Exit 0 on success, 2 on error.
"""
import argparse
import hashlib
import importlib.util
import json
import math
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

# Output is set up before anything can print, a failed import's message included: UTF-8 to a pipe or a file, a
# stand-in character on a console that cannot show one (as project.safe_output does).
if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _piped = not _stream.isatty()
            _stream.reconfigure(**({'encoding': 'utf-8'} if _piped else {}), errors='replace')


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
AMATEUR_TIERS = {'beginner', 'hobbyist'}
READING_TIERS = ('beginner', 'hobbyist', 'freelance', 'studio')
READING_DIMENSIONS = ('pacing', 'visual_clutter', 'callout_placement')
# A model family is its vendor: "Claude" and "claude-opus-4-1" had been taken for two independent readers. Product
# names count too (GPT-6.1 Sol and Terra are OpenAI's, Carbon is Gemini in Antigravity), and a name not here is no
# family: "Sol" had stood for a vendor of its own beside "gpt-6.1-sol".
VENDOR_WORDS = {
    'anthropic': 'anthropic', 'claude': 'anthropic', 'opus': 'anthropic', 'sonnet': 'anthropic',
    'haiku': 'anthropic', 'fable': 'anthropic',
    'openai': 'openai', 'gpt': 'openai', 'chatgpt': 'openai', 'codex': 'openai', 'o1': 'openai', 'o3': 'openai',
    'o4': 'openai', 'sol': 'openai', 'terra': 'openai',
    'google': 'google', 'gemini': 'google', 'gemma': 'google', 'deepmind': 'google', 'bard': 'google',
    'palm': 'google', 'carbon': 'google', 'antigravity': 'google',
    'meta': 'meta', 'llama': 'meta',
    'mistral': 'mistral', 'mixtral': 'mistral', 'codestral': 'mistral',
    'xai': 'xai', 'grok': 'xai',
}
VENDORS = ('anthropic', 'openai', 'google', 'meta', 'mistral', 'xai')
# The one reading a line-up reader gives: the brief shows it, pack.py record --help prints it, references/eyes.md
# quotes it, and read_response accepts it and nothing else.
READING_SHAPE = '''\
Answer with one JSON object and nothing else (it may sit in one fenced code block). This example is for a
line-up of two films, A and B; yours has an entry for every letter in your line-up:

{
  "model_family": "anthropic",
  "overall_ranking": ["B", "A"],
  "films": {
    "A": {"tier": "hobbyist", "pacing": 6, "visual_clutter": 7, "callout_placement": 5,
          "strongest": "the title lands on the beat", "weakest": "the callout covers the chart",
          "tells": "every move eases the same way"},
    "B": {"tier": "studio", "pacing": 9, "visual_clutter": 8, "callout_placement": 9,
          "strongest": "each cut lands on a change", "weakest": "the end card holds too long",
          "tells": "type sits on one baseline grid"}
  },
  "steals": ["hold the last frame for a beat before the cut"]
}

- model_family: your model's vendor: anthropic, openai, google, meta, mistral or xai.
- overall_ranking: every line-up letter once, best crafted first.
- films: one object per line-up letter. tier is one of beginner, hobbyist, freelance or studio. pacing,
  visual_clutter (10 is cleanest) and callout_placement are numbers from 1 to 10.
- strongest, weakest and tells (text, in each film) and steals (a list of concrete craft choices worth keeping)
  are for the people who read the results: pack.py record does not check them, and any of them may be left out.
'''


def _is_num(value):
    """A finite number, not a boolean. A whole number is never converted to a float: a JSON integer of 401 digits had
    raised OverflowError here before its range was checked."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return isinstance(value, int) or math.isfinite(value)


def _shown(value):
    """VALUE as a reason quotes it: its repr, cut short when it is long."""
    text = repr(value)
    return text if len(text) <= 40 else f'{text[:24]}... ({len(text)} characters)'


def family_of(name):
    """The vendor a reader's model family names ('' for none): 'Claude', 'claude-opus-4-1' and 'Anthropic' are one
    family. A name no word of which is known is no family, so it cannot make a pair cross-family until the vendor
    is named (an unknown name had stood for itself, and "Sol" passed beside "gpt-6.1-sol")."""
    words = [w for w in re.split(r'[^a-z0-9]+', str(name or '').lower()) if w]
    for word in words:
        letters = re.match(r'[a-z]*', word).group(0)
        if word in VENDOR_WORDS or letters in VENDOR_WORDS:
            return VENDOR_WORDS.get(word) or VENDOR_WORDS[letters]
    return ''


def reading_problems(data):
    """What keeps a blind-pack.json from showing two complete readings from two model families ([] when it does): the
    line-up letters with ours among them, each reader ranking every letter once, giving ours a tier and scoring ours on
    every dimension from 1 to 10, and two vendors. The report's own status and cross_family were taken on trust: one
    holding only the film hash, cross_family true and status pass had passed with no reader in it (a review's finding)."""
    letters = data.get('letters')
    readers = data.get('readers') if isinstance(data.get('readers'), dict) else {}
    problems = []
    # a hand-edited report may hold anything: letters and rankings that are not lists of text are refused, not sorted
    # or hashed (a {} letter or a [1, "B"] ranking had raised TypeError through check.py)
    if (not isinstance(letters, list) or not all(isinstance(x, str) for x in letters) or len(letters) < 2
            or data.get('ours_letter') not in letters):
        problems.append('no line-up letters with ours among them (a report from pack.py record 2.3.1 or later)')
        letters = []
    elif len(set(letters)) != len(letters):
        # ["A", "A"] is one film shown twice, not a line-up: a ranking of A, A had passed as every letter once
        problems.append(f'the line-up letters repeat ({", ".join(map(str, letters))})')
        letters = []
    elif data.get('yardstick_letter') not in letters or data.get('yardstick_letter') == data.get('ours_letter'):
        problems.append('no yardstick letter in the line-up besides ours')
    families = []
    for key in ('a', 'b'):
        reader = readers.get(key)
        if not isinstance(reader, dict):
            problems.append(f'no reader {key}')
            continue
        ranking = reader.get('ranking')
        if (not isinstance(ranking, list) or not all(isinstance(x, str) for x in ranking) or not letters
                or sorted(ranking) != sorted(letters)):
            problems.append(f'reader {key} did not rank every letter once')
        if reader.get('ours_tier') not in READING_TIERS:
            problems.append(f'reader {key} gave ours no tier')
        dims = reader.get('dimensions') if isinstance(reader.get('dimensions'), dict) else {}
        for name in READING_DIMENSIONS:
            value = (dims.get(name) or {}).get('ours') if isinstance(dims.get(name), dict) else None
            if not _is_num(value) or not 1 <= value <= 10:
                problems.append(f'reader {key} scored ours no {name} from 1 to 10')
        families.append(family_of(reader.get('model_family')))
    if len(families) == 2 and (not all(families) or families[0] == families[1]):
        named = [readers[k].get('model_family') for k in ('a', 'b')]
        accepted = ', '.join(VENDORS)
        problems.append(f'the readers are not from two model families ({families[0] or "unknown"} and '
                        f'{families[1] or "unknown"}' +
                        ''.join(f'; name the vendor of {n!r} ({accepted})' for n, f in zip(named, families) if not f)
                        + ')')
    return problems


def reading_verdict(data):
    """Why two complete readings (reading_problems is []) do not pass ours ([] when they do), worked out from the
    readings themselves as record_readings does: both readers put ours in an amateur tier, or both put it below the
    yardstick (ranked under it, or scored under it on a dimension). check.py and the grader had taken the report's
    own status, so a report reading "pass" over two "beginner" readings ranking ours last had passed."""
    readers = data.get('readers') if isinstance(data.get('readers'), dict) else {}
    ours, yard = data.get('ours_letter'), data.get('yardstick_letter')
    amateur, below = [], []
    for key in ('a', 'b'):
        reader = readers.get(key) if isinstance(readers.get(key), dict) else {}
        ranking = reader.get('ranking') if isinstance(reader.get('ranking'), list) else []
        amateur.append(reader.get('ours_tier') in AMATEUR_TIERS)
        under = ours in ranking and yard in ranking and ranking.index(ours) > ranking.index(yard)
        dims = reader.get('dimensions') if isinstance(reader.get('dimensions'), dict) else {}
        for name in READING_DIMENSIONS:
            row = dims.get(name) if isinstance(dims.get(name), dict) else {}
            mine, theirs = row.get('ours'), row.get('yardstick')
            if _is_num(mine) and _is_num(theirs) and mine < theirs:
                under = True
        below.append(under)
    reasons = []
    if all(amateur):
        reasons.append('both line-up readers put ours in a beginner or hobbyist tier')
    if all(below):
        reasons.append(f'both line-up readers put ours below yardstick {yard}')
    return reasons


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


def _render_briefs(out_root, n_pack, pack, film_info, letter_count, k, k_alone, alone_dir=None):
    """Write ready-to-send blind reader briefs outside the pack."""
    lineup_brief = '\n'.join([
        f'You are a reader in a blind comparison of {letter_count} short films. '
        'This is a read-only task: do not edit, create or delete any file, network or subagents.',
        '',
        f'Open every image inside {pack / "lineup"} (folders A..{LETTERS[letter_count - 1]}).',
        'Each folder holds story-01.jpg (2 fps) and move-1..K.jpg (every native frame of the K busiest seconds).',
        'You cannot hear the films; judge picture and motion only.',
        '',
        READING_SHAPE,
    ])
    alone_brief = '\n'.join([
        f'You are the fault-finder for one {film_info["duration"]:.1f}s film ({film_info["fps"]:g} fps). '
        'This is a read-only task: find faults, praise is not needed.',
        '',
        f'Open every image inside {alone_dir or pack / "alone"}: story-01.jpg (2 fps), '
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


def _resolve_alone_reads(reads, alone_root=None, _resolved=None):
    """Validate and resolve the separate alone/ root outside READS when a lineup is present."""
    r_root = _resolved[0] if _resolved else Path(reads).resolve()
    if r_root.parent == r_root:
        if not r_root.drive:
            raise ValueError(f"the readers' root {reads} is the filesystem root (/), which holds every path, so "
                             'alone/ cannot sit outside it: give --reads a subfolder')
        if not alone_root:
            raise ValueError(f"the readers' root {reads} is a drive root, so alone/ has no folder beside it: give "
                             '--reads a folder, or --alone-reads DIR on another drive')
    alone_reads = Path(alone_root) if alone_root else r_root.parent / f'{r_root.name}-alone'
    a_root = _resolved[1] if _resolved else alone_reads.resolve()
    if a_root == r_root or r_root in a_root.parents or a_root in r_root.parents:
        raise ValueError(f"--alone-reads {alone_reads} must be outside the readers' root {reads} (and not hold it)")
    return alone_reads


def make_pack(film, against, out_root, ref_first=None, ref_last=None, key_times=None,
              k=MOVE_K, k_alone=ALONE_K, reads_root=None, alone_root=None):
    """Build a blind lineup + alone pack under a neutral random folder in reads_root; with a lineup, the alone pack
    goes into a random folder of its own (in alone_root, else reads_root), never beside the lineup."""
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
    alone_reads = _resolve_alone_reads(reads, alone_root) if against else None
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
    if against:
        alone_reads.mkdir(parents=True, exist_ok=True)
        alone_pack = alone_reads / f'r-{secrets.token_hex(6)}'
        while alone_pack.exists() or alone_pack == pack:
            alone_pack = alone_reads / f'r-{secrets.token_hex(6)}'
        alone_dir = alone_pack / 'alone'
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
        f"alone ({alone_dir}) = ours: {alone_story_n} story sheet(s); "
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
    lb_path, ab_path = _render_briefs(out_root, n_pack, pack, f_info, max(1, len(letters_meta)), k, k_alone,
                                      alone_dir)
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


def _unique_object(pairs):
    """A JSON object that names no key twice: two values for one key (two readings of film A) are a contradiction,
    and JSON had kept the last one without a word."""
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f'it gives {key!r} twice')
        seen[key] = value
    return seen


def _not_json(name):
    """NaN, Infinity and -Infinity, which Python's decoder accepts and JSON does not: refused wherever they stand (in
    an unknown extra field they had passed)."""
    raise ValueError(f'it holds {name}, which is not JSON')


def _response_object(text):
    """(the JSON object a reader's response holds, None) or (None, what is wrong): the whole text when it parses as a
    JSON object, or else the one fenced block in it. A prose or Markdown reading is not read. The whole text had been
    taken as the only candidate whenever it began with "{", so prose such as "{My notes}" before a valid fenced
    block refused the reading."""
    def parse(source):
        try:
            found = json.loads(source, object_pairs_hook=_unique_object, parse_constant=_not_json)
        except ValueError as error:
            return None, f'its JSON does not parse ({error})'
        return (found, None) if isinstance(found, dict) else (None, 'its JSON is not an object')
    stripped = text.strip()
    whole, whole_wrong = parse(stripped)
    if whole is not None:
        return whole, None
    blocks = re.findall(r'^[ \t]*```[^\n]*\n(.*?)\n[ \t]*```[ \t]*$', text, re.DOTALL | re.MULTILINE)
    if len(blocks) > 1:
        return None, f'it holds {len(blocks)} fenced blocks, not one'
    if blocks:
        return parse(blocks[0].strip())
    return None, whole_wrong if stripped.startswith(('{', '[')) else 'it holds no JSON object'


def read_response(path, letters, family=None):
    """A line-up reader's response as {'model_family', 'ranking', 'films', 'steals', 'problems'}: the JSON object
    READING_SHAPE shows, and nothing else. PROBLEMS says what keeps it from being a complete reading of the line-up
    LETTERS, each with what to ask the reader for; a response with problems reads as no ranking, tier or score. A
    Markdown reader had accepted contradictory and invalid readings as complete and refused valid ones."""
    letters = sorted(letters)
    listed = ', '.join(letters)
    ask = 'ask the reader for the JSON object the brief shows'
    empty = {'model_family': str(family or '').strip().lower(), 'ranking': [], 'films': {}, 'steals': []}
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        return {**empty, 'problems': [f'its response cannot be read ({error})']}
    # a reading is UTF-8, with or without a byte-order mark: a UTF-16 file had been refused as holding no JSON object
    try:
        text = raw.decode('utf-8-sig')
        if raw.startswith((b'\xff\xfe', b'\xfe\xff')) or '\x00' in text:
            raise UnicodeDecodeError('utf-8', raw, 0, 1, 'a UTF-16 or UTF-32 file')
    except UnicodeDecodeError:
        return {**empty, 'problems': ['it is not UTF-8 text: ask the reader to save the reading as UTF-8 (a byte-order '
                                      'mark is fine)']}
    # Windows (CRLF) and old Mac (CR) line ends read as LF, as reading the file as text had done: decoding the bytes
    # strictly had kept them, and a fenced reading saved on Windows was refused as holding no JSON object
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    data, wrong = _response_object(text)
    if wrong:
        return {**empty, 'problems': [f'{wrong}: {ask}, and nothing else (pack.py record --help prints it); a reader '
                                      'who cannot be asked again is replaced by a new reader of the same lineup/ '
                                      'folder, given the same brief']}
    problems = []
    named = data.get('model_family')
    if not family and not (isinstance(named, str) and named.strip()):
        problems.append(f'it names no model_family: {ask}, or pass --family-a/--family-b ({", ".join(VENDORS)})')
    ranking = data.get('overall_ranking')
    if not isinstance(ranking, list) or not all(isinstance(x, str) for x in ranking):
        problems.append(f'its overall_ranking is not a list of letters: {ask}, with every line-up letter ({listed}) once')
    else:
        unknown = [x for x in ranking if x not in letters]
        twice = sorted({x for x in ranking if ranking.count(x) > 1})
        missing = [x for x in letters if x not in ranking]
        if unknown or twice or missing:
            what = '; '.join(filter(None, (
                unknown and f'names {", ".join(unknown)}, not in the line-up',
                twice and f'repeats {", ".join(twice)}', missing and f'leaves out {", ".join(missing)}')))
            problems.append(f'its overall_ranking {what}: ask the reader to rank every line-up letter ({listed}) once')
    films = data.get('films')
    if not isinstance(films, dict):
        problems.append(f'it has no films object keyed by letter: {ask}, with an entry for each of {listed}')
        films = {}
    for key in films:
        if key not in letters:
            problems.append(f'its films name {key!r}, not in the line-up ({listed}): ask the reader to read only '
                            'the line-up letters')
    for letter in letters:
        entry = films.get(letter)
        if not isinstance(entry, dict):
            if isinstance(data.get('films'), dict):
                problems.append(f'its films hold no entry for {letter}: ask the reader for one')
            continue
        if entry.get('tier') not in READING_TIERS:
            problems.append(f'its tier for {letter} is {entry.get("tier")!r}: ask the reader for one of '
                            f'{", ".join(READING_TIERS)}')
        for name in READING_DIMENSIONS:
            value = entry.get(name)
            if not _is_num(value) or not 1 <= value <= 10:
                problems.append(f'its {name} for {letter} is {_shown(value)}: ask the reader for a number from 1 '
                                'to 10')
    # strongest, weakest, tells and steals are free text the tool does not check (READING_SHAPE says so): steals keeps
    # the entries that are text, for the report
    steals = [x for x in data['steals'] if isinstance(x, str)] if isinstance(data.get('steals'), list) else []
    if problems:
        return {**empty, 'model_family': str(family or (named if isinstance(named, str) else '')).strip().lower(),
                'problems': problems}
    return {'model_family': str(family or named).strip().lower(), 'ranking': list(ranking),
            'films': {letter: films[letter] for letter in letters}, 'steals': list(steals), 'problems': []}


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

    ra = read_response(lineup_a, letters, family_a)
    rb = read_response(lineup_b, letters, family_b)
    # a family is its vendor, however it is written ("Claude", "claude-opus-4-1"); empty is none
    fa, fb = family_of(ra['model_family']), family_of(rb['model_family'])
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
            if _is_num(ov) and _is_num(yv) and ov < yv:
                below_y = True
        return {
            'model_family': r['model_family'] or None,
            'ranking': list(rk),   # kept so a grader can check the reading was complete, not take status on trust
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
        if r['problems']:
            reasons.extend(f"{name}'s reading is incomplete: {problem}" for problem in r['problems'])
            continue
        rk = r['ranking'] or []
        if sorted(rk) != sorted(letters) or len(set(rk)) != len(rk):
            reasons.append(f'{name} did not rank every film once ({rk or "no ranking"})')
        if e['ours_tier'] not in READING_TIERS:
            reasons.append(f'{name} gave ours no tier the brief names ({e["ours_tier"] or "none"})')
        for d, v in e['dimensions'].items():
            if not (_is_num(v['ours']) and 1 <= v['ours'] <= 10):
                reasons.append(f'{name} scored ours no {d} from 1 to 10 ({v["ours"]!r})')
    if not cross_family:
        accepted = ', '.join(VENDORS)
        hints = []
        for r, f, flag_val in ((ra, fa, family_a), (rb, fb, family_b)):
            if f:
                continue
            if flag_val:
                hints.append(f'; unknown vendor {r["model_family"]!r} (accepted vendors: {accepted})')
            elif r['model_family']:
                hints.append(f'; name the vendor of {r["model_family"]!r} with --family-a/--family-b ({accepted})')
            else:
                hints.append(f'; pass --family-a and --family-b ({accepted})')
        reasons.append(f'readers are not cross-family ({fa or "unknown"} vs {fb or "unknown"})' +
                       ''.join(dict.fromkeys(hints)))
    if both_amateur:
        reasons.append(f'both lineup readers flagged ours as beginner/hobbyist ({ea["ours_tier"]}, {eb["ours_tier"]})')
    if both_below:
        reasons.append(f'both lineup readers ranked ours below yardstick {y_letter}')

    ff_summary = None
    if fault_finder and Path(fault_finder).is_file():
        ff_raw = Path(fault_finder).read_text(encoding='utf-8-sig', errors='replace').strip()
        ff_summary = {'file': str(fault_finder), 'excerpt': ff_raw[:600]}

    dim_avg = {}
    for d in ('pacing', 'visual_clutter', 'callout_placement'):
        vals = [e['dimensions'][d]['ours'] for e in (ea, eb) if _is_num(e['dimensions'][d]['ours'])]
        dim_avg[d] = round(sum(vals) / len(vals), 2) if vals else None

    result = {
        'version': 1,
        'tool': 'pack.py record',
        'pack_number': key.get('pack_number'),
        'pack_dir': key.get('pack_dir'),
        'film_path': key.get('film_path'),
        'film_sha256': key.get('film_sha256'),
        'ours_letter': ours,
        'letters': sorted(letters),
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
                                         description='Record two cross-family blind lineup readings against a key. '
                                                     'Each reading is the JSON object the brief asks for, in a '
                                                     'UTF-8 file (a byte-order mark is fine):',
                                         epilog=READING_SHAPE, formatter_class=argparse.RawDescriptionHelpFormatter)
            ap.add_argument('key', help='pack-N-key.json or pack-N-KEY.txt')
            ap.add_argument('--lineup-a', required=True, help="first line-up reader's response (the JSON object below)")
            ap.add_argument('--lineup-b', required=True, help="second line-up reader's response (the JSON object below)")
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
        ap.add_argument('--alone-reads', help='root folder for the alone pack when there is a lineup, outside --reads '
                                              '(default: READS-alone beside the --reads root)')
        ap.add_argument('--json', action='store_true')
        a = ap.parse_args(args)
        film = Path(a.film).resolve()
        out_root = Path(a.out) if a.out else (film.parent / 'qa' if film.parent.name.startswith('v') else film.parent)
        key_times = [float(x) for x in a.keys.split(',')] if a.keys else None
        payload = make_pack(film, a.against or [], out_root, a.ref_first, a.ref_last,
                            key_times, k=a.k, k_alone=a.k_alone, reads_root=a.reads, alone_root=a.alone_reads)
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
