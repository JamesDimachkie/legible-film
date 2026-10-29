#!/usr/bin/env python3
"""Take a kit film from preflight to delivered, checked files in one command.

  python make_film.py films/atlasfold
  python make_film.py films/atlasfold --sizes 1920x1080,1080x1920 --samples 4 --out atlasfold-make
  python make_film.py films/atlasfold --preview --sound none --sizes 1920x1080
  python make_film.py films/atlasfold --sound audio/palette.json --resume
  python make_film.py films/atlasfold --sound library:licensed-sounds
  python make_film.py films/orbit --sizes 1080x1080 --res 720 --loop --web --sound none
  python make_film.py --doctor

FILM is a kit project (index.html beside film.js, as new_film.py makes it). A template film
inside the kit (assets/kit/films/NAME, a film.js with no index.html) is first copied with the
kit into OUT/project/NAME, refreshed on every run; edit the template, not the copy.

Steps, in order, each logged to OUT/logs and recorded in OUT/make-state.json:
  1. doctor: numpy, Pillow, FFmpeg/ffprobe (libx264, AAC), Node 18+, Playwright and
     Chromium found the way film_capture.mjs finds them, free memory and disk. Missing
     pieces print the one command that fixes them. Also runs before every make.
  2. preflight: film_check.py per size into OUT/qa/WxH/; stops on errors unless --force.
     The sizes must export one cue list and one set of cuts (one timeline), or the run
     stops. Rests, smears, flashes, seams and changes follow each size's layout: they
     are reported per size and each size is checked against its own.
  3. sound (SOUND-DESIGN.md): none (no audio stream), a palette (--sound PATH, or
     FILM/palette.json or FILM/audio/palette.json), draft, or library:FOLDER.
     Draft: make_sound_kit.py (palette version 2: layers, sub, air, a looping bed) into
     FILM/audio/draft/ with a temp track at info.beat.bpm, beat 0 on the film's beat 0
     (info.beat.offset), the drop on info.music.drop (seconds) or info.music.drop_beat,
     else --drop-beat N (a zero-based film beat), else none; the music stops at
     info.music.stop (on a bar line the kit's rhythm stops there and its ring-out plays).
     library:FOLDER is hybrid: sound_library.py indexes and picks licensed takes for every
     role it can fill; the draft fills the rest and the layer roles (sub, air, bed); one
     version 2 palette records each role's source, licence and attribution, and the
     attribution lines are printed. Spotting: spot_cues.py turns the exported cue list
     into qa/cues.spotted.json and qa/spotting.csv (FILM/sound-edits.json applied last);
     the mix, cue_onsets.py and sound_check.py all use the spotted list. mix_cues.py
     builds effects, music, bed and mix in OUT/sound/ with --master (default social;
     web, broadcast, none), its safety limiter checked after an AAC re-encode.
     Listening pair (library sound only): the draft-only mix too, and deliver/listen/A.mp4
     and B.mp4 (same picture, the two mixes, loudness-matched within 0.5 LU, randomised;
     the key in qa/listen-key.json) with questions.md for the listener.
  4. render: film_render.py per size (--size, --res, --samples, --preview) into
     OUT/renders/, never overwriting a file. --res N is the output's short side (720 makes
     1280x720 from 1920x1080 and 720x1280 from 1080x1920); without it each output is the
     size given. A size whose output would have an odd side is refused before anything
     runs, with the nearest --res that works. With --web the render is lossless (RGB
     FFV1) and the H.264 picture is encoded from it with film_render.py's settings.
  5. mux: video copied, AAC-LC 48 kHz 256 kbps, apad and -t at the picture's exact
     duration, fast start; never -shortest. A silent deliverable is the render itself.
  6. QC per size into OUT/qa/WxH/: qc_file.py, flash_scan.py, blank_scan.py and
     motion_scan.py with the declared ranges (and info.pace as taste guides when declared:
     max_still_share, max_still, start, end; with --loop or info.loop, --loop, so the
     last-to-first seam is measured on every deliverable), cue_onsets.py on the effects stem,
     sync_check.py against mix.wav, sound_check.py with the spotted cue list (each warning
     is a listening candidate to inspect), frame_sheet.py (an overview; one sheet per declared
     cut, 480 px tiles, so memory stays bounded; essential texts at 384 px at their
     readStart), and the declared-cut check: every info.cuts entry must show as a large
     change (motion_scan's change-area or step-cut measure) within one frame of the first
     frame of its arriving shot, except cuts listed in info.seams (seamless joins, already
     the next shot); large changes outside declared cuts, seams, smears, flashes and
     info.changes (designed flips, fills and bursts: a time, or [t0, t1, label]) are
     listed too.
  7. deliver: OUT/deliver/ holds only the deliverables, a manifest each, caption
     sidecars and delivery-report.md (filled from assets/templates/delivery-report.md).
     With --web each size also gets NAME_WxH.webm (VP9 CRF 32, BT.709 matrix and tags,
     Opus 128 kbps when there is sound) encoded from the lossless render, never from the
     H.264 file, and NAME_WxH-poster.png (frame 0 of the lossless render). Each WebM is
     checked: VP9, its frame count, BT.709 tags, and its decoded frame 0 against the poster.

OUT defaults to FILM's sibling folder FILM-make (for a template, NAME-make in the current
folder). Without --resume a previous run's
deliver/, sound/ and qa/ move to OUT/previous/<stamp>/ (nothing is deleted). --resume
skips any step whose outputs exist with their recorded hashes and whose inputs are
unchanged: the picture source (the film folder except qa/, audio/, palette.json and the
preflight exports), the cue list, the mix, the settings and the tools' own hashes.

It measures and reports; it does not watch or listen. Every film it makes is reported
unwatched and its sound unheard (a draft soundtrack says so); the weakest point is left
as a marked line for the agent to write after looking at the sheets; nothing is posted.
A cut between two similar shots can fall below the change measures and be listed as
not found: declare it in info.seams if it is seamless, else inspect its joins sheet. Needs Python 3.9+, numpy, Pillow, FFmpeg and
ffprobe with libx264 and the AAC encoder, Node 18+, Playwright, Chromium, and the
skill's scripts beside this one (film_check.py, film_render.py, the QC tools).
Exit 0 no gate or inspection finding; 1 something needs inspection (each item listed) or the
doctor found something missing (--doctor alone); 2 could not run.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
VERSION = '1.2.2'
EXPORTS = ('cues.json', 'reading.json', 'captions.srt', 'captions.vtt')
SKIP_TOP = {'qa', 'audio', '.git', 'node_modules', '__pycache__'}
SHARED = ('fps', 'duration', 'frames', 'cuts', 'beat', 'music', 'cues')
PER_SIZE = ('rests', 'smears', 'fast', 'flashes', 'seams', 'changes')
LAYER_ROLES = ('sub', 'air', 'bed')   # always synthesised in a hybrid palette
SHEET_TILE = 480   # long side of a cut-sheet tile; one frame_sheet.py call per cut keeps memory bounded
FLAG = re.compile(r'FAIL|INSPECT|flag|inconclusive|drift|offset|miss|near-empty|look at|outside', re.I)
QC_TOOLS = ('qc_file.py', 'flash_scan.py', 'blank_scan.py', 'motion_scan.py', 'cue_onsets.py', 'sync_check.py',
            'frame_sheet.py', 'sound_check.py')
NODE_PROBE = r"""
import fs from 'node:fs'; import path from 'node:path'; import os from 'node:os';
import {createRequire} from 'node:module';
const [capture, pwArg, browserArg] = process.argv.slice(1);
const out = {};
function load(req, name) {
  const api = req(name); const where = req.resolve(name); let dir = path.dirname(where); let version = 'unknown';
  for (let i = 0; i < 5; i++) {
    const pkg = path.join(dir, 'package.json');
    if (fs.existsSync(pkg)) { const meta = JSON.parse(fs.readFileSync(pkg, 'utf8'));
      if (['playwright', 'playwright-core'].includes(meta.name)) { version = meta.version; break; } }
    dir = path.dirname(dir);
  }
  return {api, version, where};
}
let pw = null;
try {
  const explicit = pwArg || process.env.LF_PLAYWRIGHT_MODULE;
  if (explicit) pw = load(createRequire(capture), path.resolve(explicit));
  else outer: for (const root of [path.join(process.cwd(), 'package.json'), capture]) {
    const req = createRequire(root);
    for (const name of ['playwright', 'playwright-core']) {
      try { pw = load(req, name); break outer; } catch (e) { if (e.code !== 'MODULE_NOT_FOUND') throw e; }
    }
  }
  out.playwright = pw ? {ok: true, version: pw.version, path: pw.where} : {ok: false, error: 'Playwright missing'};
} catch (e) { out.playwright = {ok: false, error: e.code === 'MODULE_NOT_FOUND' ? 'cannot load the explicit package path' : e.message}; }
try {
  const explicit = browserArg || process.env.LF_CHROMIUM;
  let exe = null;
  if (explicit) { if (!fs.existsSync(explicit)) throw Error('Chromium executable missing: ' + explicit); exe = explicit; }
  else if (!pw) throw Error('not looked for: Playwright missing');
  else if (fs.existsSync(pw.api.chromium.executablePath())) exe = pw.api.chromium.executablePath();
  else {
    const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), '.cache'), 'ms-playwright');
    const builds = fs.existsSync(cache) ? fs.readdirSync(cache).filter(x => /^chromium-\d+$/.test(x))
      .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1])) : [];
    outer2: for (const build of builds) for (const e of ['chrome-win64/chrome.exe', 'chrome-win/chrome.exe', 'chrome-linux/chrome', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium']) {
      const p = path.join(cache, build, e); if (fs.existsSync(p)) { exe = p; break outer2; }
    }
    if (!exe) throw Error('Chromium missing in ' + cache);
  }
  out.chromium = {ok: true, path: exe};
} catch (e) { out.chromium = {ok: false, error: e.message}; }
console.log(JSON.stringify(out));
"""
TEMPLATE = """# Delivery report

- Project and version:
- File, size and SHA-256:
- Spec: duration, dimensions, frame rate, codec and pixel format, colour tags, audio:
- Inputs: source commit or frozen-copy hashes, tool versions, render settings:

## What changed from the previous version

## What was checked
- Spec, decode and colour tags (`qc_file.py`):
- Loudness, true peak before and after a lossy re-encode, head and tail, mono fold-down:
- Flashing (`flash_scan.py`), blank frames (`blank_scan.py`), motion (`motion_scan.py`):
- Frames: overview, every transition, viewing size, full-resolution moments:
- Sound against the cue list (`cue_onsets.py`); delivered audio against the master (`sync_check.py`):
- Change proof against the baseline (`compare_versions.py`), cue list and audio hashes:
- Claims and strings against `facts.json`; the independent claims check:
- Asset rights (`assets.csv`):

## Not checked, and why

## Who has watched and listened

## The weakest remaining point

## Publication status
Nothing has been posted, uploaded or sent. (Change this line only when the person has done so.)
"""


class CouldNotRun(Exception):
    pass


class Stopped(Exception):
    pass


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def save_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def parse_size(text):
    m = re.fullmatch(r'(\d+)[xX](\d+)', text.strip())
    if not m or min(int(x) for x in m.groups()) < 2:
        raise ValueError(f'size {text!r} must be WxH, at least 2 pixels per side')
    return int(m.group(1)), int(m.group(2))


def fix_for(what):
    plat = sys.platform
    pick = lambda win, mac, linux: win if plat.startswith('win') else mac if plat == 'darwin' else linux  # noqa: E731
    return {
        'ffmpeg': pick('winget install Gyan.FFmpeg', 'brew install ffmpeg', 'sudo apt install ffmpeg'),
        'node': pick('winget install OpenJS.NodeJS.LTS', 'brew install node', 'sudo apt install nodejs npm'),
        'playwright': f'npm install --prefix "{os.getcwd()}" playwright-core   (or set LF_PLAYWRIGHT_MODULE / --playwright)',
        'chromium': 'npx playwright-core install chromium   (or set LF_CHROMIUM / --browser to a Chromium executable)',
    }[what]


_COMMON = []


def render_common():
    """film_render.py's shared module (output sizes, the H.264 settings), loaded once."""
    if not _COMMON:
        spec = importlib.util.spec_from_file_location('lf_render_common', HERE / 'render_common.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _COMMON.append(module)
    return _COMMON[0]


def template_kit(film):
    """The kit folder when FILM is a template inside it (kit/films/NAME with film.js), else None."""
    kit = film.parent.parent
    if film.parent.name != 'films' or not (film / 'film.js').is_file():
        return None
    if not (kit / 'index.html').is_file() or not (kit / 'lf').is_dir():
        return None
    return kit


def stage_template(film, kit, out):
    """Copy the kit and a template film into OUT/project/NAME (overwriting the copy each run)."""
    project = out / 'project' / film.name
    project.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns('__pycache__', '.*')
    for part in ('index.html', 'lf', 'blocks', 'fonts'):
        src = kit / part
        if src.is_dir():
            shutil.copytree(src, project / part, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(src, project / part)
    for src in film.iterdir():
        if src.name in SKIP_TOP or src.name.startswith('.'):
            continue
        if src.is_dir():
            shutil.copytree(src, project / src.name, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(src, project / src.name)
    return project


def doctor(a, sizes, need_aac=True):
    """Return rows of {name, ok, detail, fix}; never raises for a missing piece."""
    rows = []

    def add(name, ok, detail, fix=None):
        rows.append({'name': name, 'ok': bool(ok), 'detail': detail, 'fix': None if ok else fix})

    for module, package in (('numpy', 'numpy'), ('PIL', 'Pillow')):
        try:
            m = importlib.import_module(module)
            add(package, True, getattr(m, '__version__', 'installed'))
        except ImportError:
            add(package, False, f'not importable by {sys.executable}', f'"{sys.executable}" -m pip install {package}')
    ffmpeg, ffprobe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    for name, exe in (('FFmpeg', ffmpeg), ('ffprobe', ffprobe)):
        if not exe:
            add(name, False, 'not found (PATH, ' + name.upper() + ' or --' + name.lower() + ')', fix_for('ffmpeg'))
            continue
        try:
            r = subprocess.run([exe, '-version'], capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=60)
            add(name, r.returncode == 0, (r.stdout.splitlines() or ['?'])[0], fix_for('ffmpeg'))
        except (OSError, subprocess.TimeoutExpired) as exc:
            add(name, False, f'does not run: {exc}', fix_for('ffmpeg'))
    if ffmpeg:
        try:
            r = subprocess.run([ffmpeg, '-hide_banner', '-encoders'], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=60)
            names = {line.split()[1] for line in r.stdout.splitlines() if len(line.split()) > 1}
        except (OSError, subprocess.TimeoutExpired):
            names = set()
        add('FFmpeg libx264', 'libx264' in names, 'encoder present' if 'libx264' in names else 'encoder missing',
            fix_for('ffmpeg') + '   (a build with libx264)')
        if need_aac:
            add('FFmpeg AAC', 'aac' in names, 'native encoder present' if 'aac' in names else 'encoder missing',
                fix_for('ffmpeg'))
    node = find_tool('node', a.node)
    if not node:
        add('Node', False, 'not found (PATH, NODE or --node)', fix_for('node'))
    else:
        try:
            v = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=60).stdout.strip()
            major = int(re.match(r'v?(\d+)', v).group(1))
            add('Node', major >= 18, v + ('' if major >= 18 else ' (18 or newer needed)'), fix_for('node'))
        except (OSError, AttributeError, ValueError, subprocess.TimeoutExpired) as exc:
            add('Node', False, f'does not run: {exc}', fix_for('node'))
            node = None
    if node:
        capture = HERE / 'film_capture.mjs'
        try:
            r = subprocess.run([node, '--input-type=module', '-e', NODE_PROBE, str(capture), a.playwright or '',
                                a.browser or ''], capture_output=True, text=True, encoding='utf-8', errors='replace',
                               timeout=120)
            probe = json.loads(r.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            probe = {'playwright': {'ok': False, 'error': f'probe failed: {exc}'},
                     'chromium': {'ok': False, 'error': 'not looked for'}}
        p, c = probe['playwright'], probe['chromium']
        add('Playwright', p['ok'], f"{p.get('version')} at {p.get('path')}" if p['ok'] else p['error'],
            fix_for('playwright'))
        add('Chromium', c['ok'], (c['path'] + ' (found, not launched)') if c['ok'] else c['error'], fix_for('chromium'))
    else:
        add('Playwright', False, 'not looked for: Node missing', fix_for('playwright'))
        add('Chromium', False, 'not looked for: Node missing', fix_for('chromium'))
    if not (HERE / 'film_capture.mjs').is_file() or not (HERE / 'film_render.py').is_file():
        add('skill scripts', False, f'film_capture.mjs or film_render.py missing beside {Path(__file__).name}',
            'reinstall the skill so its scripts/ folder is complete')
    try:
        free = free_memory()
        dims = [render_common().output_size(w, h, a.res) for w, h in sizes]
        need = max((560 * 1024 ** 2 + w * h * 100) + 192 * 1024 ** 2 for w, h in dims)
        big = max(sizes, key=lambda s: s[0] * s[1])
        add('free memory', free >= need, f'{free / 1024 ** 2:.0f} MiB free; one render worker at {big[0]}x{big[1]} '
            f'needs about {need / 1024 ** 2:.0f} MiB (film_render.py estimate)',
            'close other programs or rendering jobs, or use a lower --res')
    except RuntimeError as exc:
        add('free memory', False, str(exc), 'check free memory yourself, then run film_render.py with --force')
    probe_dir = Path(a.out).resolve() if a.out else Path.cwd()
    while not probe_dir.exists() and probe_dir != probe_dir.parent:
        probe_dir = probe_dir.parent
    free_disk = shutil.disk_usage(probe_dir).free
    add('free disk', free_disk >= 1024 ** 3, f'{free_disk / 1024 ** 3:.1f} GiB free at {probe_dir}',
        'free at least 1 GiB there, or choose --out on another drive')
    return rows


def free_memory():
    if os.name == 'nt':
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (x, ctypes.c_ulonglong) for x in ('total', 'avail', 'page', 'availpage', 'virtual', 'availvirtual', 'ext')]
        status = Status()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise RuntimeError('cannot measure free physical memory')
        return status.avail
    try:
        return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (AttributeError, ValueError, OSError):
        raise RuntimeError('cannot measure free physical memory')


def seam_times(rows):
    """info.seams: seconds, [t, label...] rows or {t} objects -> sorted times."""
    out = []
    for row in rows or []:
        t = row.get('t') if isinstance(row, dict) else row[0] if isinstance(row, (list, tuple)) and row else row
        if isinstance(t, (int, float)) and math.isfinite(t):
            out.append(float(t))
    return sorted(out)


def change_ranges(rows, fps):
    """info.changes: a time t (one frame either side), [t0, t1, label?], [t, label] or {t} / {t0, t1}."""
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            row = [row['t0'], row['t1']] if 't0' in row and 't1' in row else [row.get('t')]
        elif not isinstance(row, (list, tuple)):
            row = [row]
        nums = [float(x) for x in row[:2] if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if len(nums) == 2 and nums[1] >= nums[0]:
            out.append((nums[0] - 1 / fps, nums[1] + 1 / fps))
        elif nums:
            out.append((nums[0] - 1 / fps, nums[0] + 1 / fps))
    return out


def listen_for(name, report):
    """One sound_check.py warning as a finding with its numbers."""
    c = (report.get('checks') or {}).get(name) or (report.get(name) if isinstance(report.get(name), dict) else {})
    text = {
        'phone_band_loss': lambda: f"phone-band loss {c.get('loss_lu', 0):.1f} LU (starting point "
                                   f"{c.get('starting_point_lu')} LU): much of the sound may vanish on a phone",
        'above_2khz': lambda: f"{100 * c.get('energy_share', 0):.1f}% of the energy above 2 kHz (starting point "
                              f"{100 * (c.get('starting_point_share') or 0):.0f}%): may sound dull",
        'digital_silence': lambda: 'digital silence inside the film: ' + ', '.join(
            '{:.3f}-{:.3f} s'.format(*(float(v) for v in (
                [g.get('from_s', g.get('start_s')), g.get('to_s', g.get('end_s'))] if isinstance(g, dict) else g[:2])))
            for g in c.get('gaps', [])[:6]),
        'crest_factor': lambda: f"crest factor {c.get('db', 0):.1f} dB (starting points {c.get('starting_points_db')}): "
                                'peaks far above the body, or squashed',
        'ending': lambda: f"the last 10% is {c.get('difference_lu', 0):+.1f} LU against the body: does the ending land?",
        'layers_per_second': lambda: f"{len(c.get('windows', []))} second(s) with more layers than the starting "
                                     'points: is it cluttered?',
    }.get(name)
    try:
        return 'listen for: ' + (text() if text else f'{name}: {json.dumps(c)[:200]}')
    except (TypeError, ValueError):
        return f'listen for: {name}'


def sound_check_summary(report):
    checks = report.get('checks') or {}
    loud = report.get('loudness') or {}
    phone = checks.get('phone_band_loss', {})
    upper = checks.get('above_2khz', {})
    crest = checks.get('crest_factor', {})
    return [f"{loud.get('integrated_lufs')} LUFS, phone-band loss {phone.get('loss_lu', float('nan')):.1f} LU, "
            f"{100 * upper.get('energy_share', float('nan')):.1f}% above 2 kHz, crest {crest.get('db', float('nan')):.1f} dB, "
            f"{len((checks.get('digital_silence') or {}).get('gaps', []))} digital-silence gap(s); "
            f"listening candidates: {', '.join(report.get('warnings', [])) or 'none'}"]


def sound_state(sound, plain=False):
    mode = sound.get('mode')
    b = (lambda x: x) if plain else (lambda x: f'**{x}**')  # noqa: E731
    if mode == 'none':
        return ('intentionally absent (no audio stream)' if plain else
                'audio intentionally absent; no audio stream, verified by qc_file.py --audio none')
    if mode == 'draft':
        return b('unheard') + (' (draft soundtrack)' if plain else ' (draft soundtrack: synthesised by '
                                'make_sound_kit.py; not for release until a person listens and decides)')
    if mode == 'hybrid':
        return b('unheard') + (' (hybrid: library takes and synthesised draft; listening pair awaits answers)' if plain
                               else ' (hybrid: licensed library takes with the synthesised draft for the other roles; '
                               'the listening pair in deliver/listen/ waits for a person to answer questions.md)')
    return b('unheard')


def rights_line(sound):
    sources = sound.get('sources') or {}
    library = sorted({str(x) for s in sources.values() if s.get('origin') == 'library'
                      for x in (s.get('licence') or [])})
    synth = [r for r, s in sources.items() if 'synthesised' in str(s.get('origin'))]
    parts = []
    if library:
        parts.append(f"{sum(1 for s in sources.values() if s.get('origin') == 'library')} role(s) from the library "
                     f"under {', '.join(library)} (licence evidence as supplied, not independent clearance)")
    if synth:
        parts.append(f'{len(synth)} role(s) synthesised by make_sound_kit.py (generated for this project, no '
                     'third-party material)')
    other = [r for r, s in sources.items() if s.get('origin') not in ('library',) and r not in synth]
    if other:
        parts.append(f'{len(other)} role(s) from a supplied palette: check its licences')
    return '; '.join(parts) + '; attribution lines in the Sound chain section' if parts else 'no sources recorded'


def cut_sheets(py, video, cuts, size, fps, folder, span=1.6):
    """One frame_sheet.py call per cut, tiles SHEET_TILE px on the long side: bounded memory at any film length.

    A single call with every cut built one FFmpeg select expression of about 33 terms per cut; at ten cuts on a
    1440-frame film FFmpeg failed with 'Cannot allocate memory' while about 3.8 GB were free.
    py(label, script, *args) -> (exit code, text). Returns (status, summary lines, flags, sheet paths)."""
    w, h = size
    tile = SHEET_TILE if w >= h else max(2, round(SHEET_TILE * w / h / 2) * 2)
    folder = Path(folder)
    for old in folder.glob('joins*.png'):
        old.unlink()   # this step's own earlier output; a stale sheet must not pass for a fresh one
    sheets, failed = [], []
    for k, c in enumerate(cuts, 1):
        out = folder / f'joins-{k:02d}-{c:.3f}s.png'
        code, text = py(f'sheet_cut-{k:02d}', 'frame_sheet.py', video, '--around', f'{c:.6f}', '--span', span,
                        '--rate', min(20, fps), '--width', tile, '--per-sheet', 64, '--out', out)
        if code:
            failed.append(f'cut {c:.3f} s: ' + ((text.strip().splitlines() or ['?'])[-1])[:200])
        sheets += sorted(folder.glob(f'joins-{k:02d}-*.png'))
    summary = [f'{len(cuts) - len(failed)} of {len(cuts)} cut sheets made, one per cut, {tile} px tiles, '
               f'{span} s at {min(20, fps):g} frames/s around each cut']
    return ('could not run' if failed else 'pass'), summary + failed, failed, [str(s) for s in sheets]


def cue_digest(path):
    """Hash a cue list's content, ignoring the note of which size exported it (the events are the same)."""
    data = load_json(path, None)
    if not isinstance(data, dict):
        return None
    data = {k: v for k, v in data.items() if k != 'exported_from'}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode('utf-8')).hexdigest()


def same_cues(provenance, cues_path):
    """Whether the current cue list is the one the reused picture was rendered against."""
    if provenance.get('cues_digest'):
        return provenance['cues_digest'] == cue_digest(cues_path)
    recorded = provenance.get('cues_sha256')
    if recorded == sha256(cues_path):
        return True
    # A 1.2.1 make recorded the frozen film folder's cues.json (the last size exported). The film folder holds the
    # same export again when its cue content still matches the delivered cue list.
    film_file = Path(provenance.get('cues_film_file', ''))
    return (film_file.is_file() and recorded == sha256(film_file)
            and cue_digest(film_file) == cue_digest(cues_path))


class Make:
    def __init__(self, a, film, out, sizes):
        self.a, self.film, self.out, self.sizes = a, film, out, sizes
        self.name = a.name or film.name
        self.state_path = out / 'make-state.json'
        old = load_json(self.state_path, {}) if a.resume or a.sound_only else {}
        self.old_steps = old.get('steps', {}) if isinstance(old, dict) else {}
        # --sound-only keeps the earlier render and QC steps, so a refused or partial run never erases the
        # record a later --sound-only or --resume depends on; the steps it reruns overwrite their own entries.
        self.state = {'version': 1, 'film': str(film), 'steps': dict(self.old_steps) if a.sound_only else {}}
        self.findings, self.not_checked, self.notes, self.log = [], [], [], []
        self.taste = []
        self.size_notes = {}
        self.loop, self.webs = bool(a.loop), {}
        self.stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.env = dict(os.environ)
        for key, value in (('FFMPEG', a.ffmpeg), ('FFPROBE', a.ffprobe), ('NODE', a.node),
                           ('LF_PLAYWRIGHT_MODULE', a.playwright), ('LF_CHROMIUM', a.browser)):
            if value:
                self.env[key] = str(Path(value).resolve()) if Path(value).exists() else value
        self.C = render_common()
        spec = importlib.util.spec_from_file_location('lf_sound_io', HERE / 'sound_io.py')
        self.io = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.io)

    # --- plumbing -------------------------------------------------------------------------
    def run(self, label, cmd, cwd=None):
        cmd = [str(c) for c in cmd]
        started = time.perf_counter()
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', cwd=cwd, env=self.env)
        text = r.stdout + r.stderr
        logs = self.out / 'logs'
        logs.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', label)
        (logs / (safe + '.log')).write_text(' '.join(cmd) + f'\n\nexit {r.returncode} after '
                                            f'{time.perf_counter() - started:.1f} s\n\n' + text, encoding='utf-8')
        self.log.append({'step': label, 'exit': r.returncode, 'seconds': round(time.perf_counter() - started, 2)})
        return r.returncode, text

    def py(self, label, script, *args):
        if not (HERE / script).is_file():
            raise CouldNotRun(f'{script} is missing beside make_film.py')
        return self.run(label, [sys.executable, '-I', HERE / script, *args])

    def step(self, name, inputs, run):
        """Run a step unless --resume finds its outputs intact and its inputs unchanged."""
        key = digest(inputs)
        prev = self.old_steps.get(name)
        if (self.a.resume and prev and prev.get('key') == key and prev.get('outputs') and
                all(Path(p).is_file() and sha256(p) == h for p, h in prev['outputs'].items())):
            self.state['steps'][name] = dict(prev, resumed=True)
            print(f'  {name}: skipped (outputs intact, inputs unchanged)', flush=True)
            self.save_state()
            return prev['result']
        result, outputs = run()
        self.state['steps'][name] = {'key': key, 'inputs': inputs, 'result': result, 'resumed': False,
                                     'outputs': {str(p): sha256(p) for p in outputs if Path(p).is_file()}}
        self.save_state()
        return result

    def save_state(self):
        save_json(self.state_path, self.state)

    def set_aside(self, path):
        path = Path(path)
        if not path.exists():
            return None
        target = self.out / 'previous' / self.stamp / path.relative_to(self.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(target))
        return target

    def need_memory(self, what, mib=512):
        free = free_memory()
        if free < mib * 1024 ** 2:
            raise CouldNotRun(f'{free / 1024 ** 2:.0f} MiB free, under {mib} MiB, before {what}; close other jobs and retry')

    def finding(self, size, check, detail):
        self.findings.append({'size': size, 'check': check, 'detail': detail})

    def tool_hashes(self, *names):
        return {n: sha256(HERE / n) if (HERE / n).is_file() else None for n in names}

    def picture_source(self):
        files = {}
        for root, dirs, names in os.walk(self.film):
            rel = Path(root).relative_to(self.film)
            dirs[:] = sorted(d for d in dirs if not (rel == Path('.') and d in SKIP_TOP))
            for n in sorted(names):
                r = (rel / n).as_posix()
                if rel == Path('.') and (n in EXPORTS or n in ('palette.json', 'sound-edits.json')):
                    continue
                files[r] = sha256(Path(root) / n)
        return {'sha256': digest(files), 'files': len(files)}

    def prior_provenance(self):
        """Recover verified 1.2.1 render and QC records when the new sidecar is absent."""
        state = load_json(self.state_path, {}) or {}
        steps = state.get('steps', {})
        renders = {}
        source_hash = None
        cue_hash = None
        for size in self.sizes:
            label = self.label(size)
            render_step = steps.get(f'render {label}', {})
            result = render_step.get('result', {})
            frozen = result.get('frozen_sha256') or {}
            picture_files = {name: value for name, value in frozen.items()
                             if name.split('/')[0] not in SKIP_TOP and
                             name not in EXPORTS and name not in ('palette.json', 'sound-edits.json')}
            path = result.get('path')
            expected = render_step.get('outputs', {}).get(path)
            qc = steps.get(f'qc {label}', {}).get('result')
            if not picture_files or not path or not expected or not qc or not frozen.get('cues.json'):
                return {}
            this_source = digest(picture_files)
            if source_hash not in (None, this_source) or cue_hash not in (None, frozen['cues.json']):
                return {}
            source_hash, cue_hash = this_source, frozen['cues.json']
            master = result.get('master')
            output = render_step.get('inputs', {}).get('output', '')
            if not re.fullmatch(r'\d+x\d+', output):
                return {}
            renders[label] = {'path': path, 'sha256': expected, 'output_size': [int(n) for n in output.split('x')],
                              'master': master, 'master_sha256': render_step.get('outputs', {}).get(master),
                              'result': result, 'qc': qc}
        return {'source_sha256': source_hash, 'cues_sha256': cue_hash,
                'cues_film_file': str(self.film / 'cues.json'), 'renders': renders}

    def out_dims(self, size):
        """The encoded size for a CSS size (film_render.py's rule: --res is the short side)."""
        return self.C.output_size(size[0], size[1], self.a.res)

    @staticmethod
    def label(size):
        return f'{size[0]}x{size[1]}'

    # --- steps ----------------------------------------------------------------------------
    def preflight(self, size, source):
        label = self.label(size)
        qa = self.out / 'qa' / label

        def go():
            qa.mkdir(parents=True, exist_ok=True)
            self.need_memory('preflight')
            started = time.time() - 2
            code, text = self.py(f'preflight-{label}', 'film_check.py', self.film, '--size', label,
                                 '--json', qa / 'preflight.json')
            if code == 2:
                raise CouldNotRun(f'film_check.py could not run at {label}: ' + text.strip()[-600:])
            outputs = []
            for name in EXPORTS:
                src = self.film / name
                if src.is_file() and src.stat().st_mtime >= started:
                    shutil.copyfile(src, qa / name)
                    outputs.append(qa / name)
            declared = self.film / 'qa' / 'declared.json'
            if declared.is_file() and declared.stat().st_mtime >= started:
                shutil.copyfile(declared, qa / 'declared.json')
                outputs.append(qa / 'declared.json')
            if not (qa / 'preflight.json').is_file() and (self.film / 'qa' / 'preflight.json').is_file():
                shutil.copyfile(self.film / 'qa' / 'preflight.json', qa / 'preflight.json')
            if not (qa / 'cues.json').is_file():
                raise CouldNotRun(f'film_check.py did not write cues.json at {label}')
            outputs.append(qa / 'preflight.json')
            report = load_json(qa / 'preflight.json', {}) or {}
            errors = report.get('errors', []) if isinstance(report, dict) else []
            warnings = report.get('warnings', []) if isinstance(report, dict) else []
            return {'exit': code, 'errors': [str(e) for e in errors][:50], 'warnings': [str(w) for w in warnings][:50],
                    'summary': (text.strip().splitlines() or [''])[-1][:300]}, outputs
        return self.step(f'preflight {label}', {'source': source['sha256'], 'size': label,
                                                'tool': self.tool_hashes('film_check.py', 'film_capture.mjs')}, go)

    def capture_info(self, size, source):
        label = self.label(size)
        path = self.out / 'qa' / 'info.json'

        def go():
            pre = load_json(self.out / 'qa' / label / 'preflight.json', {}) or {}
            info = pre.get('info') if isinstance(pre, dict) else None
            if not (isinstance(info, dict) and all(k in info for k in ('fps', 'duration', 'frames'))):
                info = self.page_info(label)
            save_json(path, info)
            return {'path': str(path)}, [path]
        self.step('info', {'source': source['sha256'], 'size': label,
                           'tool': self.tool_hashes('film_capture.mjs')}, go)
        return load_json(path)

    def page_info(self, label):
        import functools
        import http.server
        import threading

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        self.need_memory('reading the film info')
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(self.film)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            node = find_tool('node', self.a.node)
            url = f'http://127.0.0.1:{server.server_port}/index.html?render'
            code, text = self.run('info', [node, HERE / 'film_capture.mjs', 'info', url, '--size', label])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        if code:
            raise CouldNotRun('film_capture.mjs info failed: ' + text.strip()[-600:])
        info = json.loads(text.strip().splitlines()[-1])
        self.C.validate_timeline(info)
        return info

    # --- sound chain: kit, spot, source, master (SOUND-DESIGN.md) -------------------------------
    def library_palette(self, library, cues_path):
        """Index a licensed local library (resumable) and pick takes for the spotted cues; return its palette."""
        folder = Path(library).resolve()
        if not folder.is_dir():
            raise CouldNotRun('sound library folder missing: ' + str(folder))
        if folder == self.out.resolve() or folder in self.out.resolve().parents:
            raise CouldNotRun('sound library must not contain the make output folder')
        out = self.out / 'library'
        out.mkdir(parents=True, exist_ok=True)
        index = out / 'library.json'
        # Hash audio and licence evidence, not mtimes, so --resume notices edits.
        suffixes = {'.wav', '.flac', '.aiff', '.aif', '.mp3', '.ogg'}
        inputs = {str(p.relative_to(folder)): sha256(p) for p in sorted(folder.rglob('*'))
                  if p.is_file() and not p.is_symlink() and
                  (p.suffix.lower() in suffixes or p.name in ('LICENCE.txt', 'licence.json') or
                   p.name.endswith('.licence.json'))}
        inputs.update(tools=self.tool_hashes('sound_library.py', 'sound_io.py', 'cue_onsets.py'))

        def do_index():
            code, message = self.py('library-index', 'sound_library.py', 'index', folder, '--out', index)
            if code == 2:
                raise CouldNotRun('sound library index: ' + message.strip()[-600:])
            return {'exit': code}, [index]
        indexed = self.step('sound library index', inputs, do_index)
        if indexed.get('exit') == 1:
            self.finding('sound', 'sound_library.py', 'some library files could not be indexed; see library/library.json')
        palette = out / 'palette.json'
        code, message = self.py('library-pick', 'sound_library.py', 'pick', cues_path, index, '--out', palette)
        if code == 2:
            raise CouldNotRun('sound library pick: ' + message.strip()[-600:])
        return palette

    def hybrid_palette(self, draft_path, library_path):
        """One version 2 palette: library takes for every role the library filled, the synthesised draft for the
        rest and for the layer roles (sub, air, bed). Each role names its source, licence and attribution."""
        draft, library = load_json(draft_path, {}), load_json(library_path, {}) or {}
        target = Path(library_path).parent / 'palette-hybrid.json'

        def moved(path, base):
            source = (Path(base).parent / path).resolve()
            try:
                return Path(os.path.relpath(source, target.parent.resolve())).as_posix()
            except ValueError:   # another drive on Windows: keep it absolute
                return str(source)
        palette = {k: v for k, v in draft.items() if k not in ('roles', 'music')}
        palette.update(version=2, roles={}, sources={}, draft=draft.get('draft'))
        if draft.get('music'):
            palette['music'] = dict(draft['music'], file=moved(draft['music']['file'], draft_path))
        picked = {r: v for r, v in (library.get('roles') or {}).items() if v.get('takes')}
        missing = {m.get('role'): m for m in library.get('missing_roles', [])}
        for role in sorted(set(draft.get('roles', {})) | set(picked)):
            if role in picked and role not in LAYER_ROLES:
                take = dict(picked[role], takes=[moved(t, library_path) for t in picked[role]['takes']])
                take['take_records'] = [dict(record, file=moved(record['file'], library_path))
                                        for record in picked[role].get('take_records', [])]
                if draft.get('roles', {}).get(role, {}).get('layers'):
                    take['layers'] = draft['roles'][role]['layers']   # recorded transient over synthesised weight
                palette['roles'][role] = take
                palette['sources'][role] = {'origin': 'library', 'licence': sorted(set(take.get('licence') or [])),
                                            'attribution': sorted(set(take.get('attribution') or [])),
                                            'source': sorted(set(take.get('source') or []))}
            else:
                take = dict(draft['roles'][role], takes=[moved(t, draft_path) for t in draft['roles'][role]['takes']])
                palette['roles'][role] = take
                if role in LAYER_ROLES:
                    why = 'layer role, always synthesised'
                elif role in missing:
                    why = 'library could not fill it: ' + json.dumps(missing[role].get('rejections') or
                                                                     missing[role].get('reason'))
                else:
                    why = 'not asked of the library (no cue uses it)'
                palette['sources'][role] = {'origin': 'draft (synthesised)', 'licence': [take.get('licence')],
                                            'attribution': [take.get('attribution')], 'why': why}
        lines = list(library.get('attributions', []))
        if any(s['origin'] != 'library' for s in palette['sources'].values()):
            lines.append('Synthesised draft sounds: make_sound_kit.py, original procedural synthesis, '
                         'no third-party samples.')
        palette['attributions'] = lines
        palette['library_warnings'] = library.get('warnings', [])
        save_json(target, palette)
        return target

    def spot(self, cues_path, palette):
        """spot_cues.py over the exported cue list, applying FILM/sound-edits.json last when present."""
        qa = self.out / 'qa'
        edits = self.film / 'sound-edits.json'
        spotted = qa / 'cues.spotted.json'

        def go():
            qa.mkdir(parents=True, exist_ok=True)
            args = [cues_path, '--out-dir', qa, '--json', qa / 'spotting.json']
            if palette:
                args += ['--palette', palette]
            if edits.is_file():
                args += ['--edits', edits]
            code, text = self.py('spotting', 'spot_cues.py', *args)
            if code == 2:
                raise CouldNotRun('spot_cues.py could not run: ' + text.strip()[-600:])
            events = (load_json(spotted, {}) or {}).get('events', [])

            def notes(e):
                return ' | '.join(e.get('spotting') or [])
            dropped = [e for e in events if not e.get('enabled', True) and
                       re.search(r'edit applied last.*drop', notes(e))]
            merged = [e for e in events if e.get('merged_into') and e not in dropped]
            thinned = [e for e in events if not e.get('enabled', True) and e not in dropped and e not in merged]
            edited = [e for e in events if 'edit applied last' in notes(e) and e not in dropped]
            return {'exit': code, 'edits': str(edits) if edits.is_file() else None, 'events': len(events),
                    'audible': sum(1 for e in events if e.get('enabled', True) and e.get('sound') != 'silent'),
                    'merged': [f"{e['id']} into {e['merged_into']}" for e in merged],
                    'thinned': [f"{e['id']}: {notes(e)}" for e in thinned],
                    'dropped': [f"{e['id']} (edit)" for e in dropped],
                    'edited': [f"{e['id']}: {notes(e)}" for e in edited],
                    'texture': [e['id'] for e in events if e.get('enabled', True) and e.get('texture')],
                    'summary': (text.strip().splitlines() or [''])[0][:300]}, [spotted, qa / 'spotting.csv']
        result = self.step('spotting', {'cues': sha256(cues_path),
                                        'palette': self.palette_hashes(palette) if palette else None,
                                        'edits': sha256(edits) if edits.is_file() else None,
                                        'tool': self.tool_hashes('spot_cues.py')}, go)
        if result.get('exit') == 1:
            self.finding('sound', 'spot_cues.py', 'spotting left review warnings: see qa/spotting.csv')
        return spotted, result

    def draft_kit(self, info, duration):
        """make_sound_kit.py (palette version 2) into FILM/audio/draft, placed on the film's clock; resumable."""
        kit = self.film / 'audio' / 'draft'

        def go():
            notes = []
            path = self.draft_palette(info, duration, notes)
            return {'palette': str(path), 'notes': notes}, [path, kit / 'palette.json']
        return self.step('sound kit', {'duration': duration, 'beat': info.get('beat'), 'music': info.get('music'),
                                       'drop_beat': self.a.drop_beat, 'master': getattr(self.a, 'master', None),
                                       'tools': self.tool_hashes('make_sound_kit.py', 'sound_io.py')}, go)

    def mix(self, name, palette, cues, stems, duration, master):
        def go():
            stems.mkdir(parents=True, exist_ok=True)
            code, text = self.py(name.replace(' ', '-'), 'mix_cues.py', cues, palette, '--out-dir', stems,
                                 '--duration', f'{duration:.6f}', '--master', master,
                                 '--json', stems / 'mix-report.json')
            if code == 2:
                raise CouldNotRun('mix_cues.py could not run: ' + text.strip()[-600:])
            report = load_json(stems / 'mix-report.json', {}) or {}
            outputs = [stems / n for n in ('effects.wav', 'music.wav', 'bed.wav', 'mix.wav', 'mix-report.json')]
            return {'exit': code, 'mix': report.get('mix', {}), 'mastering': report.get('mastering', {}),
                    'missing_roles': report.get('missing_roles', []),
                    'silent_window_violations': report.get('silent_window_violations', []),
                    'listening_check_candidates': report.get('listening_check_candidates', []),
                    'warnings': report.get('warnings', []), 'summary': (text.strip().splitlines() or [''])[0][:300],
                    'mix_sha256': sha256(stems / 'mix.wav') if (stems / 'mix.wav').is_file() else None}, outputs
        return self.step(name, {'palette': str(palette), 'files': self.palette_hashes(palette), 'cues': sha256(cues),
                                'duration': duration, 'master': master,
                                'tools': self.tool_hashes('mix_cues.py', 'sound_io.py')}, go)

    def sound(self, info, cues_path):
        mode = self.sound_mode
        if mode == 'none':
            self.state['steps']['sound'] = {'result': {'mode': 'none'}, 'resumed': False}
            return {'mode': 'none'}
        duration = info['frames'] / info['fps']
        master = getattr(self.a, 'master', None) or 'social'
        library = mode[len('library:'):] if mode.startswith('library:') else None
        kit = self.draft_kit(info, duration) if (mode == 'draft' or library) else None
        draft = Path(kit['palette']) if kit else None
        given = None if (mode == 'draft' or library) else Path(mode)
        spotted, spotting = self.spot(cues_path, given or draft)
        if library:
            palette = self.hybrid_palette(draft, self.library_palette(library, spotted))
        else:
            palette = given or draft
        result = dict(self.mix('sound', palette, spotted, self.out / 'sound', duration, master))
        p = load_json(palette, {}) or {}
        sources = p.get('sources') or {
            r: {'origin': 'draft (synthesised)' if mode == 'draft' else 'supplied palette',
                'licence': v.get('licence'), 'attribution': v.get('attribution')} for r, v in p.get('roles', {}).items()}
        lines = p.get('attributions') or sorted({x for s in sources.values() for x in (
            [s['attribution']] if isinstance(s.get('attribution'), str) else s.get('attribution') or []) if x})
        result.update(mode='hybrid' if library else 'draft' if mode == 'draft' else 'palette', palette=str(palette),
                      master=master, spotted=str(spotted), spotting=spotting, notes=(kit or {}).get('notes', []),
                      attributions=lines, sources=sources)
        for line in lines:
            print('  sound attribution: ' + line, flush=True)
        self.mix_findings(result, self.out / 'sound', 'mix_cues.py')
        if library:
            # The listening pair's other half: the same spotted cues on the draft palette alone.
            other = self.mix('sound draft-only', draft, spotted, self.out / 'sound-draft', duration, master)
            result['draft_mix'] = other
            self.mix_findings(other, self.out / 'sound-draft', 'mix_cues.py (draft-only listening mix)')
        return result

    def mix_findings(self, result, stems, label):
        if result.get('exit') != 1:
            return
        report = load_json(stems / 'mix-report.json', {}) or {}
        said = [f"required role {m.get('role')} missing for {m.get('id')}" for m in report.get('missing_roles', [])
                if m.get('sound') == 'required']
        said += [f"{v.get('take_event_id')} sounds inside silent window {v.get('silent_id')} "
                 f"({v['overlap_s'][0]:.3f}-{v['overlap_s'][1]:.3f} s)" for v in report.get('silent_window_violations', [])]
        said += [f'required sync outside the film: {x}' for x in report.get('required_sync_outside_output', [])]
        said += report.get('warnings', [])
        if report.get('gain_refused'):
            said.append(f"mastering or gain refused: {report['gain_refused']}")
        mastering = report.get('mastering') or {}
        short = mastering.get('short_of_target')
        if short and not mastering.get('refused'):
            # Safely quieter than the destination. Within 1 LU is delivery tolerance and only reported (the report's
            # master line carries it); further short is a reason to listen and perhaps add a bed, like sound_check's.
            gap = float(mastering.get('shortfall_lu') or 0)
            if gap > 1.0:
                said.append(f"listen for: the master reached {mastering.get('reached_lufs')} LUFS, {gap:.1f} LU under "
                            f"the {mastering.get('preset')} target (limited by "
                            f"{mastering.get('limited_by', 'the limiter cap')}); {short.get('reason', '')}")
            elif not said:
                return
        for detail in said or [f'the mixer exited 1: see {stems.name}/mix-report.json']:
            self.finding('sound', label, detail)

    @staticmethod
    def palette_hashes(path):
        path = Path(path)
        files = {'palette': sha256(path)}
        palette = load_json(path, {}) or {}
        for role in (palette.get('roles') or {}).values():
            for take in role.get('takes', []):
                p = path.parent / take
                files[take] = sha256(p) if p.is_file() else None
        music = (palette.get('music') or {}).get('file')
        if music:
            p = path.parent / music
            files[music] = sha256(p) if p.is_file() else None
        return files

    def draft_palette(self, info, duration, notes):
        kit = self.film / 'audio' / 'draft'
        args = ['--out', kit, '--seed', 7]
        beat = info.get('beat') or None
        music = info.get('music') or {}
        at = skip = 0.0
        ring = False
        if beat and beat.get('bpm'):
            bpm, offset = float(beat['bpm']), float(beat.get('offset') or 0)
            at, skip = max(0.0, offset), max(0.0, -offset)
            bar_s = 4 * 60 / bpm
            bars_needed = max(1, math.ceil((duration - at + skip) / bar_s - 1e-9))
            drop_t = music.get('drop')
            if drop_t is None and music.get('drop_beat') is not None:
                drop_t = offset + float(music['drop_beat']) * 60 / bpm
            if drop_t is None and self.a.drop_beat is not None:
                drop_t = offset + self.a.drop_beat * 60 / bpm
            drop_bar = None
            if drop_t is not None:
                exact = (float(drop_t) - offset) * bpm / 60 / 4 + 1
                drop_bar = max(2, round(exact))
                if abs(exact - round(exact)) > 1e-6:
                    notes.append(f'drop at {float(drop_t):.3f} s is not on a bar line; the temp track drops on bar '
                                 f'{drop_bar} ({offset + (drop_bar - 1) * bar_s:.3f} s)')
                if drop_bar > bars_needed:
                    notes.append(f'drop at {float(drop_t):.3f} s lies after the film ends; no drop in the draft')
                    drop_bar = None
            if drop_bar is None:
                # No drop: put the generator's drop (and the riser before it) after the film's end.
                bars = bars_needed + 2
                drop_bar = bars
            else:
                bars = bars_needed
            stop_bar = bars + 1
            if music.get('stop') is not None:
                exact = (float(music['stop']) - offset) * bpm / 60 / 4 + 1
                if abs(exact - round(exact)) < 1e-6 and drop_bar < round(exact) <= bars + 1:
                    # On a bar line: the kit's own rhythmic stop lands there and its ring-out plays on.
                    stop_bar, ring = round(exact), True
            args += ['--temp-bpm', f'{bpm:g}', '--bars', bars, '--drop-bar', drop_bar, '--stop-bar', stop_bar]
            notes.append(f'temp track {bpm:g} BPM, {bars} bars, beat 0 at film {offset:.3f} s')
        else:
            notes.append('the film declares no beat: draft effects only, no temp track')
        code, text = self.py('sound-kit', 'make_sound_kit.py', *args)
        if code:
            raise CouldNotRun('make_sound_kit.py could not run: ' + text.strip()[-600:])
        palette = load_json(kit / 'palette.json')
        if palette.get('music'):
            stop = music.get('stop')
            if ring:
                stop = min(duration, at + float(palette['music']['stop_s']) - skip)
                notes.append(f"rhythm stops at {float(music['stop']):.3f} s (info.music.stop, a bar line); "
                             f'the ring-out plays to {stop:.3f} s')
            else:
                stop = min(float(stop), duration) if stop is not None else duration
                if music.get('stop') is not None:
                    notes.append(f'music stops at {stop:.3f} s (info.music.stop)')
            palette['music'].update({'at_s': round(at, 6), 'offset_s': round(skip, 6), 'stop_s': round(stop, 6)})
            palette['music']['label'] = (palette['music'].get('label', '') + " Placed by make_film.py: its beat 0 on "
                                         "the film's beat 0; stops at " + f'{stop:.3f} s.').strip()
        palette['draft'] = ('draft soundtrack from make_sound_kit.py: synthesised, unheard; '
                            'not for release until a person listens')
        if getattr(self.a, 'master', None):
            palette['master'] = {'preset': self.a.master}
        target = kit / 'palette-film.json'
        save_json(target, palette)
        return target

    def render(self, size, info, source):
        label = self.label(size)
        w, h = self.out_dims(size)
        renders = self.out / 'renders'

        def go():
            renders.mkdir(parents=True, exist_ok=True)
            base = f'{self.name}_{w}x{h}' + ('-preview' if self.a.preview else '')
            target, n = renders / (base + '.mp4'), 1
            while any(Path(str(x) + tail).exists() for x in (target, target.with_suffix('.mkv'))
                      for tail in ('', '.manifest.json')):
                n += 1
                target = renders / f'{base}-{n}.mp4'
            master = target.with_suffix('.mkv') if self.a.web else None
            args = [self.film, '--out', master or target, '--size', label, '--samples', self.a.samples]
            args += ['--res', self.a.res] if self.a.res else []
            args += ['--preview'] if self.a.preview else []
            args += ['--lossless'] if master else []
            code, text = self.py(f'render-{label}', 'film_render.py', *args)
            if code == 2:
                raise CouldNotRun(f'film_render.py could not run at {label}: ' + text.strip()[-600:])
            if code:
                return {'exit': code, 'error': text.strip()[-600:]}, []
            outputs = [target, Path(str(target) + '.manifest.json')]
            if master:
                self.encode_h264(label, master, target, w, h)
                outputs += [master, Path(str(master) + '.manifest.json')]
            manifest = load_json(str(target) + '.manifest.json', {})
            return {'exit': 0, 'path': str(target), 'manifest': str(target) + '.manifest.json',
                    'master': str(master) if master else None,
                    'frames': manifest.get('decoded_frames'), 'versions': manifest.get('versions', {}),
                    'frozen_sha256': manifest.get('frozen_sha256', {}), 'info': manifest.get('info', {}),
                    'summary': (text.strip().splitlines() or [''])[-1][:300]}, outputs
        result = self.step(f'render {label}', {'source': source['sha256'], 'size': label, 'res': self.a.res,
                                               'output': f'{w}x{h}', 'web': self.a.web,
                                               'samples': self.a.samples, 'preview': self.a.preview,
                                               'tools': self.tool_hashes('film_render.py', 'film_capture.mjs',
                                                                         'render_common.py')}, go)
        if result.get('exit'):
            self.finding(label, 'film_render.py', 'render failed: ' + result.get('error', '')[-300:])
            return None
        other = result.get('info', {})
        # One timeline: the clock, the cuts and everything the shared soundtrack follows must agree. Reading rests,
        # smears, flashes, seams and changes follow each size's layout, so they are reported per size, not failed.
        differ = [k for k in SHARED if other.get(k) != info.get(k)]
        if differ:
            self.finding(label, 'one timeline', 'the page reports a different ' + ', '.join(differ) + ' at this size')
        own = [k for k in PER_SIZE if (other.get(k) or []) != (info.get(k) or [])]
        if own:
            self.size_notes[label] = (', '.join(own) + f' differ from {self.label(self.sizes[0])} (they follow this '
                                      'size\'s layout; reported, not failed)')
        return result

    def encode_h264(self, label, master, target, w, h):
        """The delivery H.264 picture from the lossless render, with film_render.py's own settings."""
        ffmpeg = find_tool('ffmpeg', self.a.ffmpeg)
        fps = load_json(str(master) + '.manifest.json', {}).get('info', {}).get('fps', 60)
        options = self.C.h264_args(w, h, fps, preview=self.a.preview)
        code, text = self.run(f'h264-{label}', [ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-n',
                                                '-i', master, '-an', *options, target])
        if code:
            raise CouldNotRun(f'H.264 encode from the lossless render failed ({label}): ' + text.strip()[-600:])
        manifest = load_json(str(master) + '.manifest.json', {})
        manifest.update(output=str(target), output_sha256=sha256(target),
                        decoded_frames=self.C.decoded_count(find_tool('ffprobe', self.a.ffprobe), target),
                        derived_from={'path': str(master), 'sha256': sha256(master),
                                      'encode': 'ffmpeg ' + ' '.join(map(str, options))})
        save_json(str(target) + '.manifest.json', manifest)

    def probe_dims(self, path):
        """The encoded size of a file as WxH, read back with ffprobe (what was made, not what was asked)."""
        r = subprocess.run([find_tool('ffprobe', self.a.ffprobe), '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height', '-of', 'csv=p=0:s=x', str(path)],
                           capture_output=True, text=True)
        return r.stdout.strip() or None

    def web(self, size, render, sound, info):
        """A VP9 WebM from the lossless render (never from the H.264 file) and a poster from its frame 0."""
        label = self.label(size)
        w, h = self.out_dims(size)
        deliver = self.out / 'deliver'
        webm = deliver / f'{self.name}_{w}x{h}.webm'
        poster = deliver / f'{self.name}_{w}x{h}-poster.png'
        if getattr(self.a, 'sound_only', False):
            n = 2
            while webm.exists() or poster.exists():
                webm = deliver / f'{self.name}_{w}x{h}-{n}.webm'
                poster = deliver / f'{self.name}_{w}x{h}-{n}-poster.png'
                n += 1
        frames = render.get('frames') or info['frames']
        duration = frames / info['fps']
        mix = self.out / 'sound' / 'mix.wav'
        silent = sound['mode'] == 'none'
        inputs = {'master': sha256(render['master']), 'mix': None if silent else sound.get('mix_sha256'),
                  'duration': duration, 'tool': self.tool_hashes('make_film.py', 'render_common.py')}

        def go():
            ffmpeg = find_tool('ffmpeg', self.a.ffmpeg)
            deliver.mkdir(parents=True, exist_ok=True)
            if getattr(self.a, 'sound_only', False):
                prior = self.picture_provenance['renders'][label]['web']
                audio = ['-an'] if silent else ['-i', mix, '-map', '0:v:0', '-map', '1:a:0', '-af', 'apad',
                                               '-c:a', 'libopus', '-b:a', '128k', '-ar', '48000']
                code, text = self.run(f'webm-{label}', [ffmpeg, '-v', 'error', '-nostdin', '-n', '-i',
                                      prior['webm'], *audio, '-c:v', 'copy', '-t', f'{duration:.6f}', webm])
                if code:
                    raise CouldNotRun(f'WebM mux failed ({label}): ' + text.strip()[-600:])
                shutil.copyfile(prior['poster'], poster)
                return self.web_check(label, webm, poster, frames, (w, h), silent), [webm, poster]
            for x in (webm, poster):
                self.set_aside(x)
            audio = ['-an'] if silent else ['-i', mix, '-map', '0:v:0', '-map', '1:a:0', '-af', 'apad',
                                           '-c:a', 'libopus', '-b:a', '128k', '-ar', '48000']
            code, text = self.run(f'webm-{label}', [
                ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-n', '-i', render['master'], *audio,
                '-vf', self.C.COLOUR, '-c:v', 'libvpx-vp9', '-crf', '32', '-b:v', '0', '-row-mt', '1',
                '-deadline', 'good', '-cpu-used', '2', '-threads', '2', '-g', str(max(1, round(info['fps'] * 2))),
                '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv',
                '-t', f'{duration:.6f}', webm])
            if code:
                raise CouldNotRun(f'WebM encode failed ({label}): ' + text.strip()[-600:])
            code, text = self.run(f'poster-{label}', [
                ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-n', '-i', render['master'],
                '-frames:v', '1', '-pix_fmt', 'rgb24', poster])
            if code:
                raise CouldNotRun(f'poster failed ({label}): ' + text.strip()[-600:])
            return self.web_check(label, webm, poster, frames, (w, h), silent), [webm, poster]
        result = self.step(f'web {label}', inputs, go)
        for detail in result.get('problems', []):
            self.finding(label, 'web', detail)
        return result

    def web_check(self, label, webm, poster, frames, dims, silent):
        """VP9, the frame count, BT.709 tags, the audio stream, and the WebM's frame 0 against the poster."""
        import numpy as np
        from PIL import Image
        ffprobe, ffmpeg = find_tool('ffprobe', self.a.ffprobe), find_tool('ffmpeg', self.a.ffmpeg)
        r = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(webm)],
                           capture_output=True, text=True)
        streams = json.loads(r.stdout or '{}').get('streams', []) if not r.returncode else []
        video = next((s for s in streams if s.get('codec_type') == 'video'), {})
        audio = [s.get('codec_name') for s in streams if s.get('codec_type') == 'audio']
        decoded = self.C.decoded_count(ffprobe, webm)
        tags = [video.get(k) for k in ('color_primaries', 'color_transfer', 'color_space')]
        w, h = dims
        raw = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-i', str(webm), '-frames:v', '1', '-vf',
                              'scale=in_color_matrix=bt709:in_range=tv,format=rgb24', '-f', 'rawvideo', '-'],
                             capture_output=True).stdout
        with Image.open(poster) as im:
            still = np.asarray(im.convert('RGB'), dtype=np.float32)
        first = np.frombuffer(raw, np.uint8).astype(np.float32)
        diff = float(np.abs(first.reshape(h, w, 3) - still).mean()) if first.size == w * h * 3 else None
        problems = []
        if video.get('codec_name') != 'vp9':
            problems.append(f"{webm.name}: video codec {video.get('codec_name')}, not vp9")
        if decoded != frames:
            problems.append(f'{webm.name}: {decoded} frames decoded, the picture has {frames}')
        if tags != ['bt709', 'bt709', 'bt709']:
            problems.append(f'{webm.name}: colour tags {"/".join(map(str, tags))}, not bt709')
        if (audio == []) != silent or (audio and audio != ['opus']):
            problems.append(f'{webm.name}: audio streams {audio or "none"}')
        if still.shape[:2] != (h, w):
            problems.append(f'{poster.name}: {still.shape[1]}x{still.shape[0]}, not {w}x{h}')
        if diff is None or diff > 3.0:
            problems.append(f'{webm.name}: frame 0 differs from the poster by {diff} levels on average (more than 3)')
        return {'webm': str(webm), 'poster': str(poster), 'frames': decoded, 'codec': video.get('codec_name'),
                'tags': tags, 'audio': audio or 'none', 'bytes': webm.stat().st_size,
                'frame0_vs_poster_mean_abs': None if diff is None else round(diff, 3), 'problems': problems,
                'status': 'inspect' if problems else 'pass'}

    def mux(self, size, render, sound, info):
        label = self.label(size)
        w, h = self.out_dims(size)
        deliver = self.out / 'deliver'
        target = deliver / f'{self.name}_{w}x{h}.mp4'
        if getattr(self.a, 'sound_only', False):
            n = 2
            while target.exists() or Path(str(target) + '.manifest.json').exists():
                target = deliver / f'{self.name}_{w}x{h}-{n}.mp4'
                n += 1
        frames = render.get('frames') or info['frames']
        duration = frames / info['fps']
        mix = self.out / 'sound' / 'mix.wav'
        inputs = {'render': sha256(render['path']), 'mix': sound.get('mix_sha256'), 'duration': duration}

        def go():
            deliver.mkdir(parents=True, exist_ok=True)
            self.set_aside(target)
            if sound['mode'] == 'none':
                shutil.copyfile(render['path'], target)
                return {'audio': 'intentionally absent', 'duration': duration, 'path': str(target)}, [target]
            self.mux_audio(f'mux-{label}', render['path'], mix, target, duration)
            return {'audio': 'AAC-LC 48 kHz 256 kbps', 'duration': duration, 'path': str(target)}, [target]
        return self.step(f'mux {label}', inputs, go)

    def mux_audio(self, label, picture, wav, target, duration, gain_db=0.0):
        """Video copied; AAC-LC 48 kHz 256 kbps; apad and -t at the picture's exact duration; never -shortest."""
        ffmpeg = find_tool('ffmpeg', self.a.ffmpeg)
        audio = (f'volume={gain_db:.4f}dB,' if abs(gain_db) > 1e-6 else '') + 'apad'
        code, text = self.run(label, [
            ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-n', '-i', picture, '-i', wav,
            '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-af', audio, '-c:a', 'aac', '-profile:a', 'aac_low',
            '-ar', '48000', '-b:a', '256k', '-t', f'{duration:.6f}', '-movflags', '+faststart', target])
        if code:
            raise CouldNotRun(f'mux failed ({label}): ' + text.strip()[-600:])

    def listen_pair(self, size, render, sound, info):
        """Same picture, the delivered (hybrid) mix and the draft-only mix, loudness-matched, randomised as A and B."""
        import random
        listen = self.out / 'deliver' / 'listen'
        duration = (render.get('frames') or info['frames']) / info['fps']
        mixes = {'hybrid': self.out / 'sound' / 'mix.wav', 'draft': self.out / 'sound-draft' / 'mix.wav'}
        inputs = {'render': sha256(render['path']), 'mixes': {k: sha256(v) for k, v in mixes.items()},
                  'duration': duration}

        def go():
            listen.mkdir(parents=True, exist_ok=True)
            ffmpeg = find_tool('ffmpeg', self.a.ffmpeg)
            level = {k: self.io.meter(ffmpeg, v) for k, v in mixes.items()}
            if None in (level['hybrid']['integrated_lufs'], level['draft']['integrated_lufs']):
                raise CouldNotRun('the listening mixes could not be measured (silence?)')
            # Plain gain on the draft-only mix: a quieter version tends to be heard as worse just for being quieter.
            gain = level['hybrid']['integrated_lufs'] - level['draft']['integrated_lufs']
            order = ['hybrid', 'draft']
            random.SystemRandom().shuffle(order)
            files = {}
            for letter, which in zip('AB', order):
                files[letter] = listen / f'{letter}.mp4'
                self.set_aside(files[letter])
                self.mux_audio(f'listen-{letter}', render['path'], mixes[which], files[letter], duration,
                               gain if which == 'draft' else 0.0)
            measured = {k: self.io.meter(ffmpeg, f) for k, f in files.items()}
            difference = abs(measured['A']['integrated_lufs'] - measured['B']['integrated_lufs'])
            key = {'A': order[0], 'B': order[1], 'duration_s': round(duration, 6),
                   'meaning': {'hybrid': 'library takes with the synthesised draft for the rest (the delivered mix)',
                               'draft': 'the synthesised draft palette alone, same spotted cues and master'},
                   'picture': render['path'], 'size': self.label(size),
                   'gain_applied_to_draft_db': round(gain, 3),
                   'integrated_lufs': {k: v['integrated_lufs'] for k, v in measured.items()},
                   'true_peak_dbtp': {k: v['true_peak_dbtp'] for k, v in measured.items()},
                   'difference_lu': round(difference, 3), 'matched_within_0_5_lu': difference <= 0.5,
                   'sha256': {k: sha256(f) for k, f in files.items()},
                   'note': 'Keep this key from the listener until their answers are recorded.'}
            save_json(self.out / 'qa' / 'listen-key.json', key)
            (listen / 'questions.md').write_text(self.listen_questions(key, sound), encoding='utf-8')
            return key, [files['A'], files['B'], listen / 'questions.md', self.out / 'qa' / 'listen-key.json']
        key = self.step('listening pair', inputs, go)
        if not key['matched_within_0_5_lu']:
            self.finding('sound', 'listening pair', f"A and B differ by {key['difference_lu']} LU (more than 0.5)")
        for letter, peak in key['true_peak_dbtp'].items():
            if peak is not None and peak > -1.0:
                self.finding('sound', 'listening pair', f'{letter}.mp4 true peak {peak} dBTP after loudness matching')
        return key

    def listen_questions(self, key, sound):
        events = [e for e in (load_json(sound['spotted'], {}) or {}).get('events', [])
                  if e.get('enabled', True) and e.get('sound') != 'silent']
        hits = ', '.join(f"{e['t']:.2f} s" for e in events if e.get('role') in ('impact', 'boom', 'tap', 'sting'))
        moves = ', '.join(f"{e['t']:.2f} s" for e in events if e.get('role') in ('whoosh', 'sweep'))
        return '\n'.join([
            '# Listening pair: A and B', '',
            f"`A.mp4` and `B.mp4` are the same picture ({key['size']}) with two different soundtracks, matched in "
            f"loudness (they differ by {key['difference_lu']} LU). Which is which is written down elsewhere; please "
            'answer before anyone tells you.', '',
            'Play each one through at normal speed, at the same volume: once on a phone speaker and once on '
            'headphones. Then answer, naming the moment (in seconds) where you can:', '',
            '1. Which hits feel weightier, A or B?' + (f' (hits at {hits})' if hits else ''),
            '2. In which version do the whooshes feel like the camera moving, rather than a sound laid on top?'
            + (f' (whooshes at {moves})' if moves else ''),
            f"3. Does the opening (the first {min(3.0, key.get('duration_s', 12) / 4):g} s) hold your attention "
            'in A? In B?',
            '4. Is anything harsh, piercing, clicky or jarring in either? Where?',
            '5. Does the ending land in A? In B? Does the sound finish with the picture?',
            '6. Which would you ship: A, B or neither? Why?', '',
            'Send back your name, the date, the devices you used and your answers. Until then the sound is '
            'unheard.', ''])

    def declared_ranges(self, qa, info):
        fps = info['fps']
        ranges = []
        declared = load_json(qa / 'declared.json')
        if isinstance(declared, dict):
            text = declared.get('ignore')
            if isinstance(text, str) and text.strip():
                for part in text.split(','):
                    lo, _, hi = part.partition('-')
                    ranges.append((float(lo), float(hi)))
            elif isinstance(text, list):
                ranges += [(float(r[0]), float(r[1])) for r in text]
            source = declared
        else:
            source = info
        for c in source.get('cuts', []) or []:
            c = float(c[0] if isinstance(c, (list, tuple)) else c)
            ranges.append((max(0.0, c - 1 / fps), c + 1 / fps))
        for key in ('rests', 'flashes'):
            for row in source.get(key, []) or []:
                if isinstance(row, dict):
                    row = [row.get('t0', row.get('start')), row.get('t1', row.get('end'))]
                if row and len(row) >= 2 and row[0] is not None:
                    ranges.append((float(row[0]), float(row[1])))
        ranges += [(max(0.0, lo), hi) for lo, hi in change_ranges(info.get('changes'), fps)]
        merged = []
        for lo, hi in sorted(ranges):
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        return merged

    def qc(self, size, deliverable, sound, info, cues_path):
        label = self.label(size)
        w, h = self.out_dims(size)
        qa = self.out / 'qa' / label
        path = deliverable['path']
        fps, frames = info['fps'], info['frames']
        duration = frames / fps
        has_sound = sound['mode'] != 'none'
        inputs = {'file': sha256(path), 'cues': sha256(cues_path), 'mix': sound.get('mix_sha256'),
                  'spotted': sha256(sound['spotted']) if sound.get('spotted') else None,
                  'palette': self.palette_hashes(sound['palette']) if sound.get('palette') else None,
                  'declared': sha256(qa / 'declared.json') if (qa / 'declared.json').is_file() else None,
                  'reading': sha256(qa / 'reading.json') if (qa / 'reading.json').is_file() else None,
                  'info': {k: info.get(k) for k in ('fps', 'frames', 'cuts', 'smears', 'rests', 'flashes', 'pace', 'beat',
                                                    'seams', 'changes')}, 'loop': self.loop,
                  'tools': self.tool_hashes(*QC_TOOLS, 'make_film.py')}

        def go():
            checks, outputs = {}, []

            def tool(name, script, *args, json_path=None):
                code, text = self.py(f'{name}-{label}', script, *args)
                status = {0: 'pass', 1: 'inspect'}.get(code, 'could not run')
                lines = [x.strip() for x in text.strip().splitlines() if x.strip()]
                checks[name] = {'tool': script, 'exit': code, 'status': status, 'summary': lines[:12],
                                'flags': [x for x in lines if FLAG.search(x) and
                                          not x.lower().startswith('declared')][:8] if code else [],
                                'json': str(json_path) if json_path else None}
                if json_path and Path(json_path).is_file():
                    outputs.append(Path(json_path))
                return code
            ignore = self.declared_ranges(qa, info)
            ignore_arg = ','.join(f'{lo:.6f}-{hi:.6f}' for lo, hi in ignore)
            spec = ['--spec', f'{w}x{h}@{fps:g}', '--duration', f'{duration:.6f}', '--frames', frames, '--vcodec', 'h264',
                    '--pix-fmt', 'yuv420p', '--color', 'bt709', '--faststart', '--detect',
                    '--max-level', self.C.auto_level(w, h, fps)]
            if has_sound:
                spec += ['--audio', 'required', '--acodec', 'aac', '--sample-rate', 48000, '--lossy-check',
                         '--av-length-tolerance', f'{0.5 / fps:.6f}']
            else:
                spec += ['--audio', 'none']
            tool('qc_file', 'qc_file.py', path, *spec, '--json', qa / 'qc.json', json_path=qa / 'qc.json')
            tool('flash_scan', 'flash_scan.py', path, '--json', qa / 'flash.json', json_path=qa / 'flash.json')
            tool('blank_scan', 'blank_scan.py', path, *(['--ignore', ignore_arg] if ignore else []),
                 '--json', qa / 'blank.json', json_path=qa / 'blank.json')
            beat = info.get('beat') or {}
            beat_args = ['--bpm', beat['bpm'], '--beat-offset', beat.get('offset') or 0] if beat.get('bpm') else []
            loop = ['--loop'] if self.loop else []
            tool('motion_scan', 'motion_scan.py', path, *(['--ignore', ignore_arg] if ignore else []), *beat_args,
                 *loop, '--json', qa / 'motion.json', '--csv', qa / 'motion.csv', json_path=qa / 'motion.json')
            outputs.append(qa / 'motion.csv')
            if self.loop:
                checks['loop_seam'] = self.loop_seam(qa / 'motion.json')
            pace = info.get('pace') or info.get('pace_contract')
            if isinstance(pace, dict) and any(pace.get(k) is not None for k in
                                              ('max_still_share', 'max_still', 'start', 'end')):
                args = []
                for key, flag in (('start', '--start'), ('end', '--end'), ('max_still_share', '--max-still-share'),
                                  ('max_still', '--max-still')):
                    if pace.get(key) is not None:
                        args += [flag, pace[key]]
                tool('pace', 'motion_scan.py', path, *(['--ignore', ignore_arg] if ignore else []), *beat_args, *args,
                     '--json', qa / 'pace.json', json_path=qa / 'pace.json')
                # This run exists for its gates; intrusions and stutter are motion_scan's to report.
                gates = ((load_json(qa / 'pace.json', {}) or {}).get('pace') or {}).get('gates', {})
                if checks['pace']['status'] != 'could not run':
                    failed = [f"pace {k}: measured {g['actual']}, target {g['limit']} "
                              f"(interval {pace.get('start', 0)} to {pace.get('end', 'film end')} s)"
                              for k, g in gates.items() if g['pass'] is not True]
                    checks['pace'].update(status='look at' if failed else 'pass', flags=failed,
                                          summary=[f"pace {k}: {g['actual']} <= {g['limit']}: "
                                                   f"{'pass' if g['pass'] else 'FAIL'}" for k, g in gates.items()])
            cut = self.cut_check(qa, info)
            checks['declared_cuts'] = cut
            save_json(qa / 'cut-check.json', cut)
            outputs.append(qa / 'cut-check.json')
            if has_sound:
                max_lag = min(500.0, 50.0 * duration)
                window = min(3.0, 0.4 * duration)
                tool('sync_check', 'sync_check.py', path, self.out / 'sound' / 'mix.wav', '--window', f'{window:.3f}',
                     '--max-lag-ms', f'{max_lag:.1f}', '--json', qa / 'sync.json', json_path=qa / 'sync.json')
                # The delivered file's sound against the spotted cue list: reasons to listen, never a verdict.
                tool('sound_check', 'sound_check.py', path, '--cues', sound['spotted'], '--palette', sound['palette'],
                     '--json', qa / 'sound-check.json', json_path=qa / 'sound-check.json')
                report = load_json(qa / 'sound-check.json', {}) or {}
                if checks['sound_check']['status'] != 'could not run':
                    checks['sound_check']['flags'] = [listen_for(n, report) for n in report.get('warnings', [])]
                    checks['sound_check']['summary'] = sound_check_summary(report)
            sheets = []
            every = 0.5 if duration <= 60 else round(duration / 120, 3)
            tool('sheet_overview', 'frame_sheet.py', path, '--every', every, '--out', qa / 'overview.png')
            sheets.append(qa / 'overview.png')
            cuts = [float(c) for c in info.get('cuts', [])]
            if cuts:
                status, summary, failed, made_sheets = cut_sheets(
                    lambda name, script, *args: self.py(f'{name}-{label}', script, *args), path, cuts, (w, h), fps, qa)
                checks['sheet_cuts'] = {'tool': 'frame_sheet.py', 'status': status, 'summary': summary,
                                        'flags': failed, 'sheets': made_sheets}
            else:
                checks['sheet_cuts'] = {'status': 'not run', 'summary': ['the film declares no cuts']}
            texts = self.essential_texts(qa)
            if texts:
                tool('sheet_texts', 'frame_sheet.py', path, '--at', ','.join(f'{t:.6f}' for t in texts),
                     '--width', 384, '--out', qa / 'phone.png')
                sheets.append(qa / 'phone.png')
            else:
                checks['sheet_texts'] = {'status': 'not run',
                                         'summary': ['no essential text with a readStart in reading.json']}
            made = sorted(str(p) for p in qa.glob('*.png'))
            outputs += [Path(p) for p in made]
            return {'checks': checks, 'sheets': made, 'ignore': ignore}, outputs
        result = self.step(f'qc {label}', inputs, go)
        if 'pace' not in result['checks']:
            self.not_checked.append(f'{label}: pace guides (the film declares no pace contract in info.pace)')
        for name, c in result['checks'].items():
            if c.get('status') == 'look at':
                self.taste.extend(f'{label}: {detail}' for detail in c.get('flags', []))
            elif c.get('status') == 'inspect':
                for detail in (c.get('details') or c.get('flags') or c.get('summary', [])[-3:])[:8]:
                    self.finding(label, name, detail[:300])
            elif c.get('status') == 'could not run':
                self.finding(label, name, 'could not run: ' + ' '.join(c.get('summary', [])[-2:])[:300])
                self.not_checked.append(f'{label}: {name} (the tool could not run; see logs/)')
        return result

    @staticmethod
    def loop_seam(path):
        """The last-to-first seam that motion_scan.py --loop measured, as a check of its own."""
        s = (load_json(path, {}) or {}).get('loop_seam')
        if not isinstance(s, dict):
            return {'tool': 'motion_scan.py --loop', 'status': 'could not run',
                    'summary': ['no loop_seam in motion.json']}
        ok = bool(s.get('pass'))
        line = (f"loop seam: step {s.get('step')} vs typical end step {s.get('typical_end_step')} "
                f"(limit {s.get('limit')}): {'pass' if ok else 'FAIL'}")
        return {'tool': 'motion_scan.py --loop', 'status': 'pass' if ok else 'inspect', 'summary': [line],
                'flags': [] if ok else [line], 'seam': s}

    def essential_texts(self, qa):
        reading = load_json(qa / 'reading.json')
        rows = reading.get('texts', []) if isinstance(reading, dict) else reading if isinstance(reading, list) else []
        times = set()
        for row in rows:
            if not isinstance(row, dict) or row.get('role') == 'texture':
                continue
            t = row.get('readStart', row.get('read_start'))
            if isinstance(t, (int, float)) and math.isfinite(t):
                times.add(round(float(t), 6))
        return sorted(times)

    def cut_check(self, qa, info):
        fps = info['fps']
        motion = load_json(qa / 'motion.json')
        try:
            lines = (qa / 'motion.csv').read_text(encoding='utf-8').splitlines()[1:]
        except OSError:
            lines = []
        if not motion or not lines:
            return {'status': 'could not run', 'summary': ['motion_scan.py results are missing']}
        thresholds = (motion.get('pace') or {}).get('thresholds', {})
        cut_area = thresholds.get('cut_area', 0.5)
        rows = []
        for line in lines:
            f, t, step, _, area, _ = (line.split(',') + [''] * 6)[:6]
            rows.append((int(f), float(t), float(step), float(area) if area else 0.0))
        step_cut = 20.0
        big = [r for r in rows[1:] if r[3] >= cut_area or r[2] > step_cut]
        frame = 1 / fps
        declared = [float(c) for c in info.get('cuts', [])]
        seams = seam_times(info.get('seams'))
        changes = change_ranges(info.get('changes'), fps)
        is_seam = lambda c: any(abs(c - s) <= frame / 2 for s in seams)  # noqa: E731
        found, missing, skipped = [], [], []
        for c in declared:
            arrive = math.ceil(c * fps - 1e-6) / fps
            hits = [r for r in big if abs(r[1] - arrive) <= frame + 1e-4]
            if hits:
                best = max(hits, key=lambda r: r[3])
                found.append({'cut_s': c, 'frame': best[0], 'time_s': round(best[1], 6), 'seam': is_seam(c),
                              'offset_frames': round((best[1] - arrive) * fps, 3), 'change_area': best[3],
                              'step': best[2]})
            elif is_seam(c):
                # A seamless join (a dive, a shrink) is already the next shot: no change is expected.
                skipped.append(c)
            else:
                near = [r for r in rows[1:] if abs(r[1] - arrive) <= frame + 1e-4]
                peak = max(near, key=lambda r: r[3]) if near else None
                missing.append({'cut_s': c, 'expected_frame_s': round(arrive, 6),
                                'largest_change_area_nearby': peak[3] if peak else None,
                                'largest_step_nearby': peak[2] if peak else None})
        declared = sorted(set(declared) | set(seams))
        windows = [(float(a), float(b)) for a, b, *_ in (info.get('smears') or [])]
        windows += [(float(r[0]), float(r[1])) for r in (info.get('flashes') or []) if len(r) >= 2]
        windows += changes
        events = []
        for r in big:
            if events and r[0] - events[-1][-1][0] <= 2:
                events[-1].append(r)
            else:
                events.append([r])
        undeclared = []
        for e in events:
            near_cut = any(abs(r[1] - math.ceil(c * fps - 1e-6) / fps) <= frame + 1e-4 for r in e for c in declared)
            inside = any(a - frame <= r[1] <= b + frame for r in e for a, b in windows)
            if not near_cut and not inside:
                undeclared.append({'start_s': round(e[0][1], 6), 'frames': len(e),
                                   'max_change_area': max(r[3] for r in e), 'max_step': max(r[2] for r in e)})
        details = ([f"declared cut {m['cut_s']:.3f} s not found within one frame of {m['expected_frame_s']:.3f} s "
                    f"(largest change area nearby {m['largest_change_area_nearby']})" for m in missing] +
                   [f"undeclared large change at {u['start_s']:.3f} s ({u['frames']} frame(s), change area "
                    f"{u['max_change_area']:.3f})" for u in undeclared])
        cuts = len(info.get('cuts', []))
        return {'status': 'inspect' if details else 'pass', 'tool': 'make_film.py', 'declared': cuts,
                'found': found, 'missing': missing, 'seams_skipped': skipped, 'seams': seams,
                'changes_declared': [[round(a, 6), round(b, 6)] for a, b in changes],
                'undeclared_large_changes': undeclared, 'details': details,
                'summary': [f'{len(found)} of {cuts} declared cuts found within one frame'
                            + (f'; {len(skipped)} seamless join(s) not expected to show' if skipped else '')
                            + (f'; {len(changes)} designed change(s) declared' if changes else '')
                            + f'; {len(undeclared)} undeclared large change(s)'],
                'method': f'a large change is a frame with change area >= {cut_area} or a step > {step_cut} '
                          '(motion_scan.py measures); a declared cut c is found when one lies within one frame of '
                          'the first frame at or after c; cuts listed in info.seams are not required to show; '
                          'large changes within one frame of a cut or seam, or inside a smear, flash or '
                          'info.changes range (one frame either side), are declared'}

    def sound_only_qc(self, size, delivered, sound, info, previous):
        """Reuse picture checks and rerun the delivered file's specification and audio checks."""
        label = self.label(size)
        qa = self.out / 'qa' / label
        checks = dict(previous['checks'])
        w, h = self.out_dims(size)
        fps = info['fps']
        duration = info['frames'] / fps
        spec = ['--spec', f'{w}x{h}@{fps:g}', '--duration', f'{duration:.6f}', '--frames', info['frames'],
                '--vcodec', 'h264', '--pix-fmt', 'yuv420p', '--color', 'bt709', '--faststart', '--detect',
                '--max-level', self.C.auto_level(w, h, fps)]
        if sound['mode'] == 'none':
            spec += ['--audio', 'none']
        else:
            spec += ['--audio', 'required', '--acodec', 'aac', '--sample-rate', 48000, '--lossy-check',
                     '--av-length-tolerance', f'{0.5 / fps:.6f}']
        commands = [('qc_file', 'qc_file.py', [delivered['path'], *spec], 'qc.json')]
        if sound['mode'] != 'none':
            commands += [('sync_check', 'sync_check.py', [delivered['path'], self.out / 'sound' / 'mix.wav',
                         '--window', f'{min(3.0, 0.4 * duration):.3f}', '--max-lag-ms',
                         f'{min(500.0, 50.0 * duration):.1f}'], 'sync.json'),
                         ('sound_check', 'sound_check.py', [delivered['path'], '--cues', sound['spotted'],
                          '--palette', sound['palette']], 'sound-check.json')]
        else:
            checks.pop('sync_check', None)
            checks.pop('sound_check', None)
        for name, script, args, filename in commands:
            path = qa / filename
            code, text = self.py(f'{name}-{label}', script, *args, '--json', path)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            checks[name] = {'tool': script, 'exit': code, 'status': {0: 'pass', 1: 'inspect'}.get(code,
                            'could not run'), 'summary': lines[:12], 'flags': [], 'json': str(path)}
            if name == 'sound_check' and code != 2:
                report = load_json(path, {}) or {}
                checks[name]['flags'] = [listen_for(n, report) for n in report.get('warnings', [])]
                checks[name]['summary'] = sound_check_summary(report)
            elif code:
                checks[name]['flags'] = [line for line in lines if FLAG.search(line)][:8]
        for name, check in checks.items():
            if check.get('status') == 'look at':
                self.taste.extend(f'{label}: {detail}' for detail in check.get('flags', []))
            elif check.get('status') in ('inspect', 'could not run'):
                details = check.get('details') or check.get('flags') or check.get('summary', [])[-3:]
                for detail in details[:8]:
                    self.finding(label, name, detail[:300])
        return {'checks': checks, 'sheets': previous.get('sheets', []), 'ignore': previous.get('ignore', [])}

    def cue_onsets(self, sound, cues_path):
        if sound['mode'] == 'none':
            return None
        spotted = Path(sound.get('spotted') or cues_path)
        events = (load_json(spotted, {}) or {}).get('events', [])
        if not events:
            self.not_checked.append('sound on cue (cue_onsets.py): the cue list has no events')
            return {'status': 'not run', 'summary': ['the cue list has no events']}

        def go():
            path = self.out / 'qa' / 'cue-onsets.json'
            code, text = self.py('cue-onsets', 'cue_onsets.py', self.out / 'sound' / 'effects.wav', spotted,
                                 '--json', path)
            status = {0: 'pass', 1: 'inspect'}.get(code, 'could not run')
            return {'tool': 'cue_onsets.py', 'exit': code, 'status': status, 'json': str(path),
                    'summary': [x for x in text.strip().splitlines() if x.strip()][:12]}, [path]
        result = self.step('cue onsets', {'effects': sha256(self.out / 'sound' / 'effects.wav'),
                                          'cues': sha256(spotted), 'tool': self.tool_hashes('cue_onsets.py')}, go)
        if result['status'] == 'could not run':
            self.finding('sound', 'cue_onsets', ' '.join(result['summary'][:3])[:300])
        else:
            report = load_json(result['json'], {}) or {}
            if not isinstance(report.get('rows'), list):
                self.finding('sound', 'cue_onsets', 'could not read the cue-onset results')
                result['status'] = 'could not run'
                return result
            findings_before = len(self.findings)
            taste_before = len(self.taste)
            self.taste.extend('cue spacing: ' + note for note in report.get('lint', []) if ' ms apart:' in note)
            for row in report.get('rows', []):
                status = row.get('status')
                if status in ('EARLY', 'LATE'):
                    self.taste.append(f"cue {row.get('id')}: offset {row.get('offset_ms')} ms; "
                                      f"target within {row.get('tolerance_ms')} ms")
                elif row.get('sound') == 'required' and status in ('missing', 'outside audio', 'inconclusive'):
                    self.finding('sound', 'cue_onsets', f"cue {row.get('id')}: {status}")
                elif status in ('UNEXPECTED SOUND', 'RESIDUAL'):
                    self.finding('sound', 'cue_onsets', f"cue {row.get('id')}: {status}")
            result['status'] = ('inspect' if len(self.findings) > findings_before else
                                'look at' if len(self.taste) > taste_before else 'pass')
        return result

    # --- delivery -------------------------------------------------------------------------
    def deliver(self, info, source, sound, renders, delivered, qcs, onsets, cues_path):
        deliver = self.out / 'deliver'
        deliver.mkdir(parents=True, exist_ok=True)
        keep = {Path(d['path']).name for d in delivered.values()}
        for web in self.webs.values():
            keep |= {Path(web['webm']).name, Path(web['poster']).name}
        captions = []
        first = self.out / 'qa' / self.label(self.sizes[0])
        for ext in ('srt', 'vtt'):
            src = first / f'captions.{ext}'
            if src.is_file() and src.read_text(encoding='utf-8', errors='replace').strip():
                dst = deliver / f'{self.name}.{ext}'
                if not dst.is_file() or sha256(dst) != sha256(src):
                    self.set_aside(dst)
                    shutil.copyfile(src, dst)
                captions.append(dst)
                keep.add(dst.name)
        keep |= {n + '.manifest.json' for n in keep} | {'delivery-report.md'}
        if sound.get('listen'):
            keep.add('listen')
        if not getattr(self.a, 'sound_only', False):
            for p in deliver.iterdir():
                if p.name not in keep:
                    self.set_aside(p)
        manifests = {}
        draft = sound['mode'] == 'draft'
        for label, d in delivered.items():
            path = Path(d['path'])
            r = renders[label]
            m = {'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha256(path),
                 'made_by': f'make_film.py (Legible Film {VERSION})',
                 'settings': {'size': label, 'output_size': self.probe_dims(path),
                              'res': self.a.res or 'none (the size given)',
                              'samples': 1 if self.a.preview else self.a.samples,
                              'preview': self.a.preview, 'shutter': 180, 'encode': 'film_render.py defaults '
                              '(H.264 High, CRF 14, BT.709 matrix and tags, closed GOP, fast start)',
                              'audio': d['audio'], 'mux': None if sound['mode'] == 'none' else
                              'video stream copied; AAC-LC 48 kHz 256 kbps; apad; -t ' + f"{d['duration']:.6f} s; +faststart"},
                 'sources': {'picture_source_sha256': source['sha256'], 'render': r['path'],
                             'render_sha256': sha256(r['path']) if Path(r['path']).is_file() else None,
                             'picture_reused': bool(getattr(self.a, 'sound_only', False)),
                             'frozen_copy_sha256': r.get('frozen_sha256', {}),
                             'cues_sha256': sha256(cues_path), 'mix_sha256': sound.get('mix_sha256'),
                             'palette': sound.get('palette')},
                 'versions': r.get('versions', {}), 'captions': [c.name for c in captions],
                 'status': {'watched': 'unwatched', 'sound': sound_state(sound, plain=True),
                            'published': 'nothing posted, uploaded or sent'}}
            save_json(str(path) + '.manifest.json', m)
            manifests[label] = m
            web = self.webs.get(label)
            if web:
                for kind in ('webm', 'poster'):
                    f = Path(web[kind])
                    save_json(str(f) + '.manifest.json', {
                        'file': f.name, 'bytes': f.stat().st_size, 'sha256': sha256(f),
                        'made_by': f'make_film.py (Legible Film {VERSION})',
                        'from': {'lossless_render': r.get('master'), 'sha256': sha256(r['master']),
                                 'picture_reused': bool(getattr(self.a, 'sound_only', False))},
                        'settings': {'size': label, 'output_size': m['settings']['output_size'],
                                     'encode': 'VP9 CRF 32, BT.709 matrix and tags, Opus 128 kbps when there is sound'
                                     if kind == 'webm' else 'frame 0 of the lossless render, RGB PNG'},
                        'checks': {k: web.get(k) for k in ('frames', 'codec', 'tags', 'audio',
                                                           'frame0_vs_poster_mean_abs', 'status')},
                        'status': m['status']})
        report = self.report(info, source, sound, renders, delivered, qcs, onsets, manifests, captions)
        (deliver / 'delivery-report.md').write_text(report, encoding='utf-8')
        return manifests

    def report(self, info, source, sound, renders, delivered, qcs, onsets, manifests, captions):
        draft, silent = sound['mode'] in ('draft', 'hybrid'), sound['mode'] == 'none'
        sound_status = sound_state(sound)
        files = [f'{m["file"]}: {m["bytes"] / 1e6:.6f} MB, SHA-256 `{m["sha256"]}`' for m in manifests.values()]
        for web in self.webs.values():
            files += [f'{Path(web[k]).name}: {Path(web[k]).stat().st_size / 1e6:.6f} MB, SHA-256 '
                      f'`{sha256(web[k])}`' for k in ('webm', 'poster')]
        files += [f'{c.name}: caption sidecar, SHA-256 `{sha256(c)}`' for c in captions]

        def check(label, name):
            c = (qcs.get(label) or {}).get('checks', {}).get(name)
            return c or {'status': 'not run', 'summary': []}

        def qcj(label):
            return load_json(self.out / 'qa' / label / 'qc.json', {}) or {}
        specs, loud, scans, frames, sync, spec_lines = [], [], [], [], [], []
        for label in delivered:
            q = qcj(label)
            v = q.get('video', {})
            dec = q.get('decode') or {}
            au = q.get('audio') or []
            audio = (f"{au[0]['codec']} {au[0]['sample_rate']} Hz {au[0]['channels']} ch" if au else 'no audio stream')
            specs.append(f"{label}: {dec.get('decoded_length_s')} s, {dec.get('decoded_video_frames')} frames, "
                         f"{v.get('width')}x{v.get('height')} @ {v.get('fps')} fps, {v.get('codec')} level "
                         f"{v.get('level_display')} {v.get('pix_fmt')}, colour {v.get('color_primaries')}/"
                         f"{v.get('color_transfer')}/{v.get('color_space')}, audio: {audio}")
            failed = [k for k, c in (q.get('checks') or {}).items() if not c.get('pass')]
            qf = check(label, 'qc_file')
            specs_line = (f"{label}: {qf['status']}" + (f" (failed: {', '.join(failed)})" if failed else
                          f" ({len(q.get('checks') or {})} checks passed)" if qf['status'] == 'pass' else ''))
            spec_lines.append(specs_line)
            if not silent:
                lv, lossy, e, mono = q.get('loudness', {}), q.get('lossy_reencode', {}), q.get('audio_edges', {}), q.get('mono_fold_down', {})
                db = lambda x: 'silent' if x is None else f'{x} dBFS'  # noqa: E731
                loud.append(f"{label}: {lv.get('integrated_lufs')} LUFS integrated, LRA {lv.get('loudness_range_lu')} LU, "
                                         f"true peak {lv.get('true_peak_dbtp')} dBTP, after AAC re-encode "
                                         f"{lossy.get('true_peak_dbtp')} dBTP; head 5 ms peak "
                                         f"{db(e.get('head_first_5ms_peak_dbfs'))}, tail 10 ms peak "
                                         f"{db(e.get('tail_last_10ms_peak_dbfs'))}; mono fold-down "
                                         f"{mono.get('drop_lu')} LU below stereo; audio minus video "
                                         f"{q.get('audio_minus_video_s')} s")
            cut = check(label, 'declared_cuts')
            pace = check(label, 'pace')
            scans.append(f"{label}: flash {check(label, 'flash_scan')['status']}, blank "
                         f"{check(label, 'blank_scan')['status']}, motion {check(label, 'motion_scan')['status']}, "
                         f"pace {pace['status']}" + (f" ({'; '.join(pace['summary'][-3:])})" if pace['summary'] else '')
                         + f"; declared cuts in the render: {cut['status']} ({'; '.join(cut.get('summary', []))})")
            for d in cut.get('details', []):
                scans.append(f'{label}: {d}')
            seam = check(label, 'loop_seam')
            if self.loop:
                scans.append(f"{label}: {'; '.join(seam['summary']) or 'loop seam not measured'}")
            web = self.webs.get(label)
            if web:
                scans.append(f"{label}: WebM {web['status']}: {Path(web['webm']).name}, {web['codec']}, "
                             f"{web['frames']} frames, tags {'/'.join(map(str, web['tags']))}, audio {web['audio']}, frame 0 against "
                             f"the poster {web['frame0_vs_poster_mean_abs']} levels")
            if label in self.size_notes:
                scans.append(f'{label}: {self.size_notes[label]}')
            sheets = [Path(s).name for s in (qcs.get(label) or {}).get('sheets', [])]
            joins = [s for s in sheets if s.startswith('joins')]
            named = [f'`qa/{label}/{s}`' for s in sheets if not s.startswith('joins')]
            if joins:
                named.append(f'`qa/{label}/joins-*.png` ({len(joins)} sheet(s), one per cut)')
            frames.append(f"{label}: sheets made, not yet looked at: " + (', '.join(named) or 'none') +
                          '; full-resolution moments not made (choose the changed and busiest moments)')
            if not silent:
                sc = check(label, 'sync_check')
                sync.append(f"{label}: sync_check.py {sc['status']}: " + (sc['summary'][0] if sc['summary'] else ''))
        pre = []
        for size in self.sizes:
            p = self.state['steps'].get(f'preflight {self.label(size)}', {}).get('result', {})
            pre.append(f"{self.label(size)}: exit {p.get('exit')}, {len(p.get('errors', []))} error(s), "
                       f"{len(p.get('warnings', []))} warning(s)")
        if silent:
            onset_line = 'not run: silent deliverable'
        elif onsets:
            onset_line = f"cue_onsets.py on the effects stem: {onsets['status']}" + (
                f" ({onsets['summary'][0]})" if onsets.get('summary') else '')
        else:
            onset_line = 'not run'
        r0 = next(iter(renders.values()))
        versions = r0.get('versions', {})
        short = lambda v: re.sub(r'^(ffmpeg|ffprobe) version ', '', str(v).split(' Copyright')[0].split(' (')[0])  # noqa: E731
        tools = ', '.join(f'{k} {short(v)}' for k, v in versions.items())
        fills = {
            'Project and version': f"{info.get('title', self.name)} ({self.name}); film folder `{self.film}`; made "
                                   f"{datetime.date.today().isoformat()} by make_film.py (Legible Film {VERSION}). "
                                   f"Status: **unwatched**; {'' if silent else 'sound '}{sound_status}.",
            'File, size and SHA-256': files,
            'Spec: duration, dimensions, frame rate, codec and pixel format, colour tags, audio': specs,
            'Inputs: source commit or frozen-copy hashes, tool versions, render settings': [
                f"picture source SHA-256 `{source['sha256']}` over {source['files']} file(s) (the film folder except "
                "qa/, audio/, palette.json and the preflight exports); each render's frozen-copy hashes are in its "
                "manifest",
                f"cue list SHA-256 `{sha256(self.out / 'cues.json')}`" + (
                    f"; mix SHA-256 `{sound.get('mix_sha256')}`" if not silent else '; no mix (silent)'),
                'render: output ' + ', '.join(f'{self.label(s)} as {self.label(self.out_dims(s))}' for s in self.sizes)
                + f" (--res {self.a.res or 'not given'}), " + ('preview (one sample per frame, no motion blur; not a delivery '
                                                  'master)' if self.a.preview else f'{self.a.samples} samples per '
                                                  'frame, 180-degree shutter, cut-aware motion blur'),
                f'tools: {tools}'],
            'Spec, decode and colour tags (`qc_file.py`)': spec_lines,
            'Loudness, true peak before and after a lossy re-encode, head and tail, mono fold-down':
                'not applicable: audio intentionally absent' if silent else loud,
            'Flashing (`flash_scan.py`), blank frames (`blank_scan.py`), motion (`motion_scan.py`)': scans,
            'Frames: overview, every transition, viewing size, full-resolution moments': frames,
            'Sound against the cue list (`cue_onsets.py`); delivered audio against the master (`sync_check.py`)':
                [onset_line] + (sync or ['sync_check.py not run: silent deliverable']),
            'Change proof against the baseline (`compare_versions.py`), cue list and audio hashes':
                'not run: make_film.py has no baseline; on a revision run compare_versions.py against the approved '
                'export and compare the cue list and decoded audio hashes',
            'Claims and strings against `facts.json`; the independent claims check':
                ['film_check.py preflight (facts, contrast, reading windows, predicted flashing): ' + '; '.join(pre),
                 'the independent claims check: not done (needs a reviewer reading every string against today\'s sources)'],
            'Asset rights (`assets.csv`)': ('picture assets not checked by make_film.py' + (
                '; assets.csv present, not verified' if (self.film / 'assets.csv').is_file() else
                '; no assets.csv in the film folder') + ('; sound: ' + rights_line(sound) if not silent else '')),
        }
        inspect = [f"{f['size']}: {f['check']}: {f['detail']}" for f in self.findings]
        not_checked = [
            'motion at normal playback speed, rhythm and whether transitions read (needs a person watching)',
            'how the sound sounds, balance and whether hits feel right (needs a person listening)' if not silent else
            'sound: none by design',
            'comprehension, taste and brand fit (needs people)',
            'full-resolution moments (frame_sheet.py --width at the changed and busiest moments) and brand colour '
            'patches (no patch declared to make_film.py)',
            'the sheets themselves: make_film.py makes them and does not look at them'] + self.not_checked
        sections = {
            'What changed from the previous version': [self.previous_note()],
            'Not checked, and why': not_checked,
            'Who has watched and listened': [f"{m['file']}: **unwatched**; {'' if silent else 'sound '}{sound_status}" for m in manifests.values()],
            'The weakest remaining point': ['<!-- WEAKEST POINT: the agent writes this after looking at the sheets in '
                                            'qa/ (overview, joins, phone); make_film.py cannot judge it. -->',
                                            'WEAKEST POINT: not yet written.'],
        }
        template_path = HERE.parent / 'assets' / 'templates' / 'delivery-report.md'
        template = template_path.read_text(encoding='utf-8') if template_path.is_file() else TEMPLATE
        out, lines, i = [], template.splitlines(), 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r'^- (.+?):\s*$', line)
            if m:
                value = fills.get(m.group(1), 'not filled by make_film.py')
                if isinstance(value, list):
                    out.append(f'- {m.group(1)}:')
                    out += [f'  - {v}' for v in value]
                else:
                    out.append(f'- {m.group(1)}: {value}')
            elif line.startswith('## ') and line[3:].strip() in sections:
                out.append(line)
                # Drop the template's parenthetical guidance under the heading; the filled lines replace it.
                if i + 1 < len(lines) and lines[i + 1].startswith('('):
                    i += 1
                    while not lines[i].rstrip().endswith(')') and i + 1 < len(lines):
                        i += 1
                out += [f'- {v}' if not v.startswith(('<!--', 'WEAKEST')) else v for v in sections[line[3:].strip()]]
                out.append('')
            else:
                out.append(line)
            i += 1
        text = re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).rstrip() + '\n'
        chain = [] if silent else ['', '## Sound chain', ''] + [
            (f'  - {x.strip()}' if x.startswith('  ') else f'- {x}') for x in self.sound_chain(sound, qcs)]
        taste = ['', "## Taste checks (numbers to look and listen at; a person's approval overrides them)", '']
        taste += [f'- {x}' for x in self.taste] or ['- No taste checks flagged.']
        head = chain + taste + ['', '## Items to inspect', ''] + ([f'- {x}' for x in inspect] or
                                                  ['- None from the automated checks. The checks measure files; they '
                                                   'do not watch or listen.']) + ['']
        anchor = '\n## Not checked, and why'
        return text.replace(anchor, '\n'.join(head) + anchor, 1) if anchor in text else text + '\n'.join(head)

    def sound_chain(self, sound, qcs):
        """The chain's numbers: spotting, sources and licences, mastering, sound_check, the listening pair."""
        def few(items, n=8):
            return '; '.join(items[:n]) + (f'; and {len(items) - n} more' if len(items) > n else '') if items else 'none'
        sp = sound.get('spotting') or {}
        lines = [f"Spotting (`spot_cues.py`, `qa/spotting.csv`): {sp.get('events')} cue events, {sp.get('audible')} audible "
                 f"after spotting" + (f"; edits applied last from `{Path(sp['edits']).name}`" if sp.get('edits') else
                                      '; no sound-edits.json'),
                 f"  merged into gestures: {few(sp.get('merged', []))}",
                 f"  thinned (withheld or optional): {few(sp.get('thinned', []))}",
                 f"  dropped by edits: {few(sp.get('dropped', []))}"]
        if sp.get('edited'):
            lines.append(f"  changed by edits: {few(sp['edited'])}")
        sources = sound.get('sources') or {}
        groups = {}
        for role, src in sorted(sources.items()):
            lic = ', '.join(str(x) for x in (src.get('licence') if isinstance(src.get('licence'), list)
                                              else [src.get('licence')]) if x)
            groups.setdefault(f"{src.get('origin')} ({lic or 'licence not stated'})", []).append(role)
        lines.append('Sources: ' + ('; '.join(f'{k}: {", ".join(v)}' for k, v in groups.items()) or 'none recorded'))
        why = [f'{r}: {s["why"]}' for r, s in sorted(sources.items()) if s.get('why') and 'layer role' not in s['why']
               and 'not asked' not in s['why']]
        if why:
            lines.append('  synthesised because the library could not fill them: ' + few(why, 6))
        lines.append('Attribution lines: ' + (' | '.join(sound.get('attributions') or []) or 'none'))

        def mastered(name, r):
            m, mix = r.get('mastering') or {}, r.get('mix') or {}
            aac = (m.get('aac_128k') or {}).get('true_peak_dbtp')
            text = (f"{name}: preset {m.get('preset', sound.get('master'))}, integrated {mix.get('integrated_lufs')} LUFS"
                    + (f" (target {m['target_lufs']})" if m.get('target_lufs') is not None else '')
                    + f", largest gain reduction {m.get('max_gain_reduction_db', 0) or 0:.2f} dB, true peak "
                    f"{mix.get('true_peak_dbtp')} dBTP, after an AAC 128 kbps re-encode "
                    + (f'{aac} dBTP' if aac is not None else 'not measured'))
            if m.get('short_of_target'):
                text += (f"; short of target by {m.get('shortfall_lu', 0):.1f} LU"
                         f" (limited by {m.get('limited_by', 'the limiter cap')})")
            return text + (f"; REFUSED: {m['refused']}" if m.get('refused') else '')
        lines.append(mastered('Master (`mix_cues.py`)', sound))
        if sound.get('draft_mix'):
            lines.append(mastered('Draft-only listening mix', sound['draft_mix']))
        for label, q in qcs.items():
            c = (q.get('checks') or {}).get('sound_check') or {}
            lines.append(f"`sound_check.py` {label}: {c.get('status', 'not run')}: " +
                         ('; '.join(c.get('summary') or []) or '') +
                         (' — ' + '; '.join(c.get('flags')) if c.get('flags') else ''))
        listen = sound.get('listen')
        if listen:
            lines.append(f"Listening pair: `deliver/listen/A.mp4` and `B.mp4` ({listen['size']}, loudness "
                         f"{listen['integrated_lufs']['A']} and {listen['integrated_lufs']['B']} LUFS, difference "
                         f"{listen['difference_lu']} LU, randomised; key in `qa/listen-key.json`); questions in "
                         '`deliver/listen/questions.md`. Unheard until a person answers them.')
        return lines

    def previous_note(self):
        if getattr(self.a, 'sound_only', False):
            return ('Sound only: the picture is the earlier make\'s render (its hashes verified, the video stream '
                    'copied), and its flash, blank, motion, pace, cut and sheet checks are carried over; the spec, '
                    'sync and sound checks ran on these files. The earlier deliverables stay beside them in deliver/; '
                    'describe what changed in the sound (make_film.py cannot know the intent of a change).')
        prev = self.out / 'previous' / self.stamp
        if prev.exists():
            return (f'A previous delivery in this folder was set aside in `previous/{self.stamp}/`. Describe what '
                    'changed, with timestamps (make_film.py cannot know the intent of a change).')
        return 'No previous delivery in this output folder; no baseline compared.'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('film', nargs='?', help='film folder (a kit project with index.html, or a template in the kit)')
    p.add_argument('--sizes', default='1920x1080,1080x1920', help='comma-separated CSS sizes WxH, one timeline')
    p.add_argument('--res', type=int, help="output short side in pixels: 720 makes 1280x720 from 1920x1080 and "
                   '720x1280 from 1080x1920; default each output is the size given')
    p.add_argument('--loop', action='store_true', help="the film loops: measure the last-to-first seam on every "
                   "deliverable (motion_scan.py --loop); on by itself when the film's info.loop is true")
    p.add_argument('--web', action='store_true', help='also a VP9 WebM per size, encoded from a lossless render, '
                   'and a poster PNG from frame 0')
    p.add_argument('--preview', action='store_true', help='sharp one-sample render, not a delivery master')
    p.add_argument('--samples', type=int, default=4)
    p.add_argument('--sound', help='draft, none, library:FOLDER or a palette.json path; default the film\'s palette, else draft')
    p.add_argument('--master', choices=('social', 'web', 'broadcast', 'none'), default='social',
                   help='mastering preset passed to mix_cues.py (social -14, web -16, broadcast -23 LUFS)')
    p.add_argument('--drop-beat', type=float, help='zero-based film beat for the draft drop, if the film declares none')
    p.add_argument('--out', help='output folder; default FILM-make beside the film folder')
    p.add_argument('--name', help='deliverable base name; default the film folder name')
    p.add_argument('--resume', action='store_true', help='skip steps whose outputs and inputs are unchanged')
    p.add_argument('--sound-only', action='store_true', help='reuse verified renders from the previous make')
    p.add_argument('--force', action='store_true', help='continue past preflight errors')
    p.add_argument('--doctor', action='store_true', help='check the environment only; exit 0 ready, 1 missing')
    p.add_argument('--json', help='write the run summary here')
    p.add_argument('--node')
    p.add_argument('--playwright')
    p.add_argument('--browser')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    if a.sound_only:
        a.resume = False
    try:
        sizes = [parse_size(s) for s in a.sizes.split(',') if s.strip()]
        if not sizes or len(set(sizes)) != len(sizes):
            raise ValueError('--sizes needs distinct WxH sizes')
    except ValueError as exc:
        p.error(str(exc))
    if a.samples < 1 or (a.drop_beat is not None and (not math.isfinite(a.drop_beat) or a.drop_beat < 0)):
        p.error('--samples must be at least 1 and --drop-beat a non-negative beat')
    if a.res is not None and a.res < 2:
        p.error('--res is the output short side in pixels, at least 2')
    for w, h in sizes:
        out_w, out_h = render_common().output_size(w, h, a.res)
        if out_w % 2 or out_h % 2:
            near = render_common().even_res_near(w, h, a.res or min(w, h))
            hint = f"; --res {near} gives {'x'.join(map(str, render_common().output_size(w, h, near)))}" if near else ''
            p.error(f"{w}x{h}" + (f' at --res {a.res}' if a.res else '') +
                    f' gives {out_w}x{out_h}: H.264 4:2:0 needs even sides{hint}')
    if a.name and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', a.name):
        p.error('--name may use letters, digits, dot, dash and underscore')
    summary = {'tool': 'make_film.py', 'version': VERSION, 'exit_code': 2}

    def finish(code, extra=None):
        summary.update(extra or {}, exit_code=code)
        if a.json:
            save_json(a.json, summary)
        return code
    wants_sound = a.sound != 'none'
    rows = doctor(a, sizes, need_aac=wants_sound)
    summary['doctor'] = rows
    missing = [r for r in rows if not r['ok']]
    if a.doctor:
        for r in rows:
            print(f"{'ok     ' if r['ok'] else 'MISSING'}  {r['name']}: {r['detail']}" +
                  (f"\n         fix: {r['fix']}" if r['fix'] else ''))
        print('ready' if not missing else f'{len(missing)} missing: ' + ', '.join(r['name'] for r in missing))
        return finish(1 if missing else 0)
    if not a.film:
        p.error('give a film folder, or --doctor')
    if missing:
        print('make_film.py: could not run; the environment is missing:', file=sys.stderr)
        for r in missing:
            print(f"  {r['name']}: {r['detail']}\n    fix: {r['fix']}", file=sys.stderr)
        return finish(2, {'error': 'environment incomplete'})
    film = Path(a.film).resolve()
    kit = None if (film / 'index.html').is_file() else template_kit(film)
    default_out = (Path.cwd() if kit else film.parent) / (film.name + '-make')
    out = Path(a.out).resolve() if a.out else default_out
    if kit:
        film = stage_template(film, kit, out)
        print(f'make_film.py: {Path(a.film).name} is a template in the kit; made the project {film}', flush=True)
    if not (film / 'index.html').is_file():
        print(f'make_film.py: could not run: {film} has no index.html (a kit film folder; start one with '
              'new_film.py)', file=sys.stderr)
        return finish(2, {'error': 'not a film folder'})
    if out == film or film in out.parents:
        print('make_film.py: could not run: --out must be outside the film folder (renders copy that folder)',
              file=sys.stderr)
        return finish(2, {'error': 'output inside the film folder'})
    if a.sound in (None, 'draft', 'none'):
        own = next((x for x in (film / 'palette.json', film / 'audio' / 'palette.json') if x.is_file()), None)
        sound_mode = a.sound or (str(own) if own else 'draft')
    elif a.sound.startswith('library:'):
        library = Path(a.sound[len('library:'):]).resolve()
        if not library.is_dir():
            print(f'make_film.py: could not run: library {library} not found', file=sys.stderr)
            return finish(2, {'error': 'sound library missing'})
        sound_mode = 'library:' + str(library)
    else:
        sound_mode = str(Path(a.sound).resolve())
        if not Path(sound_mode).is_file():
            print(f'make_film.py: could not run: palette {a.sound} not found', file=sys.stderr)
            return finish(2, {'error': 'palette missing'})
    try:
        out.mkdir(parents=True, exist_ok=True)
        m = Make(a, film, out, sizes)
        m.sound_mode = sound_mode
        provenance_path = out / 'picture-provenance.json'
        provenance = (load_json(provenance_path, {}) or m.prior_provenance()) if a.sound_only else {}
        m.picture_provenance = provenance
        if a.sound_only and not provenance:
            raise CouldNotRun('sound-only needs verified picture and QC records from a previous make in --out')
        if not a.resume and not a.sound_only:
            for name in ('deliver', 'sound', 'qa', 'cues.json'):
                m.set_aside(out / name)
        print(f'make_film.py: {film.name} -> {out}', flush=True)
        source = m.picture_source()
        if a.sound_only and provenance.get('source_sha256') != source['sha256']:
            raise CouldNotRun('sound-only refused: picture source hash changed since the render')
        cue_lists, declared_cuts, stopped = {}, {}, []
        for size in sizes:
            r = m.preflight(size, source)
            label = m.label(size)
            print(f'  preflight {label}: exit {r["exit"]}, {len(r["errors"])} error(s), {len(r["warnings"])} warning(s)',
                  flush=True)
            if r['exit'] == 1:
                for e in r['errors'][:10] or [r['summary']]:
                    m.finding(label, 'film_check.py', e)
                stopped.append(label)
            cue_lists[label] = load_json(out / 'qa' / label / 'cues.json', {})
            declared = load_json(out / 'qa' / label / 'declared.json')
            if isinstance(declared, dict) and isinstance(declared.get('cuts'), list):
                declared_cuts[label] = [float(c[0] if isinstance(c, (list, tuple)) else c) for c in declared['cuts']]
        if stopped and not a.force:
            raise Stopped('preflight found errors at ' + ', '.join(stopped) + '; fix them, or pass --force')
        events = {k: json.dumps((v or {}).get('events'), sort_keys=True) for k, v in cue_lists.items()}
        if len(set(events.values())) > 1:
            raise Stopped('the sizes export different cue lists (one timeline must mean one cue list): ' +
                          ', '.join(events))
        if len({json.dumps(v) for v in declared_cuts.values()}) > 1:
            raise Stopped('the sizes declare different cuts (one timeline must mean one set of cuts): ' +
                          '; '.join(f'{k}: {v}' for k, v in declared_cuts.items()))
        cues_path = out / 'cues.json'
        first = out / 'qa' / m.label(sizes[0]) / 'cues.json'
        if not cues_path.is_file() or sha256(cues_path) != sha256(first):
            shutil.copyfile(first, cues_path)
        info = m.capture_info(sizes[0], source)
        if a.sound_only:
            if not same_cues(provenance, cues_path):
                raise CouldNotRun('sound-only refused: the cue list changed since the render; run a full make')
            for size in sizes:
                label = m.label(size)
                r = provenance.get('renders', {}).get(label, {})
                path = Path(r.get('path', ''))
                if (not path.is_file() or sha256(path) != r.get('sha256') or
                        r.get('output_size') != list(m.out_dims(size))):
                    raise CouldNotRun(f'sound-only refused: render missing or changed for {label}')
                if a.web:
                    master = Path(r.get('master') or '')
                    if not master.is_file() or sha256(master) != r.get('master_sha256'):
                        raise CouldNotRun(f'sound-only refused: lossless render missing or changed for {label}')
                    for kind in ('webm', 'poster'):
                        web = r.get('web') or {}
                        path = Path(web.get(kind) or '')
                        if not path.is_file() or sha256(path) != web.get(kind + '_sha256'):
                            raise CouldNotRun(f'sound-only refused: previous {kind} missing or changed for {label}')
                if not r.get('qc'):
                    raise CouldNotRun(f'sound-only refused: picture QC is missing for {label}')
        m.loop = bool(a.loop or info.get('loop'))
        if m.loop:
            print('  loop: the seam is measured on every deliverable (motion_scan.py --loop)', flush=True)
        sound = m.sound(info, cues_path)
        print(f"  sound: {sound['mode']}" + (f" ({'; '.join(sound.get('notes', []))})" if sound.get('notes') else ''),
              flush=True)
        renders, delivered, qcs = {}, {}, {}
        for size in sizes:
            label = m.label(size)
            r = provenance['renders'][label]['result'] if a.sound_only else m.render(size, info, source)
            if not r:
                continue
            renders[label] = r
            print(f'  render {label}: {Path(r["path"]).name}' +
                  (f'; {m.size_notes[label]}' if label in m.size_notes else ''), flush=True)
            delivered[label] = m.mux(size, r, sound, info)
            if a.web:
                m.webs[label] = m.web(size, r, sound, info)
                print(f"  web {label}: {Path(m.webs[label]['webm']).name}, {Path(m.webs[label]['poster']).name}: "
                      f"{m.webs[label]['status']}", flush=True)
            if sound['mode'] == 'hybrid' and 'listen' not in sound:
                sound['listen'] = m.listen_pair(size, r, sound, info)
        onsets = m.cue_onsets(sound, cues_path)
        for size in sizes:
            label = m.label(size)
            if label in delivered:
                own = dict(info, **{k: renders[label].get('info', {}).get(k) for k in PER_SIZE})
                if a.sound_only:
                    qcs[label] = m.sound_only_qc(size, delivered[label], sound, own, provenance['renders'][label]['qc'])
                else:
                    qcs[label] = m.qc(size, delivered[label], sound, own, cues_path)
                states = ', '.join(f"{k} {c.get('status')}" for k, c in qcs[label]['checks'].items())
                print(f'  qc {label}: {states}', flush=True)
        if not delivered:
            raise Stopped('no size rendered; nothing to deliver')
        if not a.sound_only:
            provenance = {'source_sha256': source['sha256'], 'cues_sha256': sha256(cues_path),
                          'cues_digest': cue_digest(cues_path), 'renders': {}}
            for size in sizes:
                label = m.label(size)
                if label in renders:
                    r = renders[label]
                    provenance['renders'][label] = {'path': r['path'], 'sha256': sha256(r['path']),
                                                     'output_size': list(m.out_dims(size)),
                                                     'master': r.get('master'),
                                                     'master_sha256': sha256(r['master']) if r.get('master') else None,
                                                     'result': r, 'qc': qcs[label]}
                    if label in m.webs:
                        web = m.webs[label]
                        provenance['renders'][label]['web'] = {
                            kind: web[kind] for kind in ('webm', 'poster')}
                        provenance['renders'][label]['web'].update({
                            kind + '_sha256': sha256(web[kind]) for kind in ('webm', 'poster')})
            save_json(provenance_path, provenance)
        manifests = m.deliver(info, source, sound, renders, delivered, qcs, onsets, cues_path)
        code = 1 if m.findings else 0
        status = 'unwatched; ' + ('audio intentionally absent' if sound['mode'] == 'none' else
                                  'sound ' + sound_state(sound, plain=True))
        print(f"  delivered: {', '.join(x['file'] for x in manifests.values())} in {out / 'deliver'}")
        print(f'  status: {status}; nothing posted. Weakest point: write it in deliver/delivery-report.md after '
              'looking at the sheets in qa/.')
        for f in m.findings:
            print(f"  INSPECT {f['size']}: {f['check']}: {f['detail']}")
        print(f'exit {code}: ' + (f'{len(m.findings)} item(s) need inspection' if code else 'no gate findings'))
        m.save_state()
        return finish(code, {'film': str(film), 'out': str(out), 'sound': sound['mode'], 'preview': a.preview,
                             'status': status, 'deliverables': manifests, 'findings': m.findings,
                             'not_checked': m.not_checked, 'steps': m.log,
                             'resumed': [k for k, v in m.state['steps'].items() if v.get('resumed')],
                             'report': str(out / 'deliver' / 'delivery-report.md')})
    except Stopped as exc:
        print(f'make_film.py: stopped: {exc}', file=sys.stderr)
        for f in m.findings:
            print(f"  INSPECT {f['size']}: {f['check']}: {f['detail']}", file=sys.stderr)
        m.save_state()
        return finish(1, {'error': str(exc), 'findings': m.findings, 'steps': m.log})
    except (CouldNotRun, OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f'make_film.py: could not run: {exc}', file=sys.stderr)
        return finish(2, {'error': str(exc)})


if __name__ == '__main__':
    sys.exit(main())
