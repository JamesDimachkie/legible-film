#!/usr/bin/env python3
"""Take a kit film from preflight to delivered, checked files in one command.

  python make_film.py films/atlasfold
  python make_film.py films/atlasfold --sizes 1920x1080,1080x1920 --samples 4 --out atlasfold-make
  python make_film.py films/atlasfold --preview --sound none --sizes 1920x1080
  python make_film.py films/atlasfold --sound audio/palette.json --resume
  python make_film.py --doctor

Steps, in order, each logged to OUT/logs and recorded in OUT/make-state.json:
  1. doctor: numpy, Pillow, FFmpeg/ffprobe (libx264, AAC), Node 18+, Playwright and
     Chromium found the way film_capture.mjs finds them, free memory and disk. Missing
     pieces print the one command that fixes them. Also runs before every make.
  2. preflight: film_check.py per size into OUT/qa/WxH/; stops on errors unless --force.
     The sizes must export one cue list and one set of cuts (one timeline), or the run
     stops. Rests, smears, flashes, seams and changes follow each size's layout: they
     are reported per size and each size is checked against its own.
  3. sound: none (no audio stream), a palette (--sound PATH, or FILM/palette.json or
     FILM/audio/palette.json), or draft: make_sound_kit.py into FILM/audio/draft/ with a
     temp track at info.beat.bpm, beat 0 on the film's beat 0 (info.beat.offset), the
     drop on info.music.drop (seconds) or info.music.drop_beat, else --drop-beat N
     (a zero-based film beat), else none, and the music stopping at info.music.stop.
     mix_cues.py then builds effects.wav, music.wav and mix.wav in OUT/sound/.
  4. render: film_render.py per size (--size, --res, --samples, --preview) into
     OUT/renders/, never overwriting a file.
  5. mux: video copied, AAC-LC 48 kHz 256 kbps, apad and -t at the picture's exact
     duration, fast start; never -shortest. A silent deliverable is the render itself.
  6. QC per size into OUT/qa/WxH/: qc_file.py, flash_scan.py, blank_scan.py and
     motion_scan.py with the declared ranges (and info.pace as gates when declared:
     max_still_share, max_still, start, end), cue_onsets.py on the effects stem,
     sync_check.py against mix.wav, frame_sheet.py (an overview; one sheet per declared
     cut, 480 px tiles, so memory stays bounded; essential texts at 384 px at their
     readStart), and the declared-cut check: every info.cuts entry must show as a large
     change (motion_scan's change-area or step-cut measure) within one frame of the first
     frame of its arriving shot, except cuts listed in info.seams (seamless joins, already
     the next shot); large changes outside declared cuts, seams, smears, flashes and
     info.changes (designed flips, fills and punches: a time, or [t0, t1, label]) are
     listed too.
  7. deliver: OUT/deliver/ holds only the deliverables, a manifest each, caption
     sidecars and delivery-report.md (filled from assets/templates/delivery-report.md).

OUT defaults to FILM's sibling folder FILM-make. Without --resume a previous run's
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
Exit 0 every check passed; 1 something needs inspection (each item listed) or the
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
VERSION = '1.2.0'
EXPORTS = ('cues.json', 'reading.json', 'captions.srt', 'captions.vtt')
SKIP_TOP = {'qa', 'audio', '.git', 'node_modules', '__pycache__'}
SHARED = ('fps', 'duration', 'frames', 'cuts', 'beat', 'music', 'cues')
PER_SIZE = ('rests', 'smears', 'fast', 'flashes', 'seams', 'changes')
SHEET_TILE = 480   # long side of a cut-sheet tile; one frame_sheet.py call per cut keeps memory bounded
FLAG = re.compile(r'FAIL|INSPECT|flag|inconclusive|drift|offset|miss|near-empty|look at|outside', re.I)
QC_TOOLS = ('qc_file.py', 'flash_scan.py', 'blank_scan.py', 'motion_scan.py', 'cue_onsets.py', 'sync_check.py',
            'frame_sheet.py')
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
        scale = int(a.res) / 1080
        need = max((560 * 1024 ** 2 + round(w * scale) * round(h * scale) * 100) + 192 * 1024 ** 2 for w, h in sizes)
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


class Make:
    def __init__(self, a, film, out, sizes):
        self.a, self.film, self.out, self.sizes = a, film, out, sizes
        self.name = a.name or film.name
        self.scale = int(a.res) / 1080
        self.state_path = out / 'make-state.json'
        old = load_json(self.state_path, {}) if a.resume else {}
        self.old_steps = old.get('steps', {}) if isinstance(old, dict) else {}
        self.state = {'version': 1, 'film': str(film), 'steps': {}}
        self.findings, self.not_checked, self.notes, self.log = [], [], [], []
        self.size_notes = {}
        self.stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.env = dict(os.environ)
        for key, value in (('FFMPEG', a.ffmpeg), ('FFPROBE', a.ffprobe), ('NODE', a.node),
                           ('LF_PLAYWRIGHT_MODULE', a.playwright), ('LF_CHROMIUM', a.browser)):
            if value:
                self.env[key] = str(Path(value).resolve()) if Path(value).exists() else value
        spec = importlib.util.spec_from_file_location('lf_render_common', HERE / 'render_common.py')
        self.C = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.C)

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
                if rel == Path('.') and (n in EXPORTS or n == 'palette.json'):
                    continue
                files[r] = sha256(Path(root) / n)
        return {'sha256': digest(files), 'files': len(files)}

    def out_dims(self, size):
        return round(size[0] * self.scale), round(size[1] * self.scale)

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

    def sound(self, info, cues_path):
        mode = self.sound_mode
        if mode == 'none':
            self.state['steps']['sound'] = {'result': {'mode': 'none'}, 'resumed': False}
            return {'mode': 'none'}
        duration = info['frames'] / info['fps']
        cues_hash = sha256(cues_path)
        if mode == 'draft':
            inputs = {'mode': 'draft', 'cues': cues_hash, 'duration': duration, 'beat': info.get('beat'),
                      'music': info.get('music'), 'drop_beat': self.a.drop_beat,
                      'tools': self.tool_hashes('make_sound_kit.py', 'mix_cues.py', 'sound_io.py')}
        else:
            inputs = {'mode': 'palette', 'palette': str(mode), 'files': self.palette_hashes(mode), 'cues': cues_hash,
                      'duration': duration, 'tools': self.tool_hashes('mix_cues.py', 'sound_io.py')}
        stems = self.out / 'sound'

        def go():
            notes = []
            palette = Path(mode) if mode != 'draft' else self.draft_palette(info, duration, notes)
            stems.mkdir(parents=True, exist_ok=True)
            code, text = self.py('mix', 'mix_cues.py', cues_path, palette, '--out-dir', stems, '--duration',
                                 f'{duration:.6f}', '--json', stems / 'mix-report.json')
            if code == 2:
                raise CouldNotRun('mix_cues.py could not run: ' + text.strip()[-600:])
            report = load_json(stems / 'mix-report.json', {}) or {}
            outputs = [stems / n for n in ('effects.wav', 'music.wav', 'mix.wav', 'mix-report.json')]
            return {'mode': 'draft' if mode == 'draft' else 'palette', 'palette': str(palette), 'exit': code,
                    'notes': notes, 'mix': report.get('mix', {}), 'missing_roles': report.get('missing_roles', []),
                    'silent_window_violations': report.get('silent_window_violations', []),
                    'listening_check_candidates': report.get('listening_check_candidates', []),
                    'warnings': report.get('warnings', []), 'summary': (text.strip().splitlines() or [''])[-1][:300],
                    'mix_sha256': sha256(stems / 'mix.wav') if (stems / 'mix.wav').is_file() else None}, outputs
        result = self.step('sound', inputs, go)
        if result.get('exit') == 1:
            report = load_json(stems / 'mix-report.json', {}) or {}
            said = [f"required role {m.get('role')} missing for {m.get('id')}" for m in report.get('missing_roles', [])
                    if m.get('sound') == 'required']
            said += [f"{v.get('take_event_id')} sounds inside silent window {v.get('silent_id')} "
                     f"({v['overlap_s'][0]:.3f}-{v['overlap_s'][1]:.3f} s)" for v in report.get('silent_window_violations', [])]
            said += [f'required sync outside the film: {x}' for x in report.get('required_sync_outside_output', [])]
            said += report.get('warnings', []) + ([f"gain refused: {report['gain_refused']}"] if report.get('gain_refused') else [])
            for detail in said or ['the mixer exited 1: see sound/mix-report.json']:
                self.finding('sound', 'mix_cues.py', detail)
        return result

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
            args += ['--temp-bpm', f'{bpm:g}', '--bars', bars, '--drop-bar', drop_bar, '--stop-bar', bars + 1]
            notes.append(f'temp track {bpm:g} BPM, {bars} bars, beat 0 at film {offset:.3f} s')
        else:
            notes.append('the film declares no beat: draft effects only, no temp track')
        code, text = self.py('sound-kit', 'make_sound_kit.py', *args)
        if code:
            raise CouldNotRun('make_sound_kit.py could not run: ' + text.strip()[-600:])
        palette = load_json(kit / 'palette.json')
        if palette.get('music'):
            stop = music.get('stop')
            stop = min(float(stop), duration) if stop is not None else duration
            palette['music'].update({'at_s': round(at, 6), 'offset_s': round(skip, 6), 'stop_s': round(stop, 6)})
            palette['music']['label'] = (palette['music'].get('label', '') + ' Placed by make_film.py: its beat 0 on '
                                         'the film\'s beat 0; stops at ' + f'{stop:.3f} s.').strip()
            if music.get('stop') is not None:
                notes.append(f'music stops at {stop:.3f} s (info.music.stop)')
        palette['draft'] = 'draft soundtrack from make_sound_kit.py: synthesised, unheard; not for release until a person listens'
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
            while target.exists() or Path(str(target) + '.manifest.json').exists():
                n += 1
                target = renders / f'{base}-{n}.mp4'
            args = [self.film, '--out', target, '--size', label, '--res', self.a.res, '--samples', self.a.samples]
            if self.a.preview:
                args.append('--preview')
            code, text = self.py(f'render-{label}', 'film_render.py', *args)
            if code == 2:
                raise CouldNotRun(f'film_render.py could not run at {label}: ' + text.strip()[-600:])
            if code:
                return {'exit': code, 'error': text.strip()[-600:]}, []
            manifest = load_json(str(target) + '.manifest.json', {})
            return {'exit': 0, 'path': str(target), 'manifest': str(target) + '.manifest.json',
                    'frames': manifest.get('decoded_frames'), 'versions': manifest.get('versions', {}),
                    'frozen_sha256': manifest.get('frozen_sha256', {}), 'info': manifest.get('info', {}),
                    'summary': (text.strip().splitlines() or [''])[-1][:300]}, [target, Path(str(target) + '.manifest.json')]
        result = self.step(f'render {label}', {'source': source['sha256'], 'size': label, 'res': self.a.res,
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

    def mux(self, size, render, sound, info):
        label = self.label(size)
        w, h = self.out_dims(size)
        deliver = self.out / 'deliver'
        target = deliver / f'{self.name}_{w}x{h}.mp4'
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
            ffmpeg = find_tool('ffmpeg', self.a.ffmpeg)
            code, text = self.run(f'mux-{label}', [
                ffmpeg, '-hide_banner', '-v', 'error', '-nostdin', '-n', '-i', render['path'], '-i', mix,
                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-af', 'apad', '-c:a', 'aac', '-profile:a', 'aac_low',
                '-ar', '48000', '-b:a', '256k', '-t', f'{duration:.6f}', '-movflags', '+faststart', target])
            if code:
                raise CouldNotRun(f'mux failed at {label}: ' + text.strip()[-600:])
            return {'audio': 'AAC-LC 48 kHz 256 kbps', 'duration': duration, 'path': str(target)}, [target]
        return self.step(f'mux {label}', inputs, go)

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
                  'declared': sha256(qa / 'declared.json') if (qa / 'declared.json').is_file() else None,
                  'reading': sha256(qa / 'reading.json') if (qa / 'reading.json').is_file() else None,
                  'info': {k: info.get(k) for k in ('fps', 'frames', 'cuts', 'smears', 'rests', 'flashes', 'pace', 'beat',
                                                    'seams', 'changes')},
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
            tool('motion_scan', 'motion_scan.py', path, *(['--ignore', ignore_arg] if ignore else []), *beat_args,
                 '--json', qa / 'motion.json', '--csv', qa / 'motion.csv', json_path=qa / 'motion.json')
            outputs.append(qa / 'motion.csv')
            pace = info.get('pace') or info.get('pace_contract')
            if isinstance(pace, dict) and any(pace.get(k) is not None for k in ('max_still_share', 'max_still')):
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
                    failed = [f"pace {k}: {g['actual']} > {g['limit']}" for k, g in gates.items() if not g['pass']]
                    checks['pace'].update(status='inspect' if failed else 'pass', flags=failed,
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
            self.not_checked.append(f'{label}: pace gates (the film declares no pace contract in info.pace)')
        for name, c in result['checks'].items():
            if c.get('status') == 'inspect':
                for detail in (c.get('details') or c.get('flags') or c.get('summary', [])[-3:])[:8]:
                    self.finding(label, name, detail[:300])
            elif c.get('status') == 'could not run':
                self.finding(label, name, 'could not run: ' + ' '.join(c.get('summary', [])[-2:])[:300])
                self.not_checked.append(f'{label}: {name} (the tool could not run; see logs/)')
        return result

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
                # A seamless join (a dive through, a collapse) is already the next shot: no change is expected.
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

    def cue_onsets(self, sound, cues_path):
        if sound['mode'] == 'none':
            return None
        events = (load_json(cues_path, {}) or {}).get('events', [])
        if not events:
            self.not_checked.append('sound on cue (cue_onsets.py): the cue list has no events')
            return {'status': 'not run', 'summary': ['the cue list has no events']}

        def go():
            path = self.out / 'qa' / 'cue-onsets.json'
            code, text = self.py('cue-onsets', 'cue_onsets.py', self.out / 'sound' / 'effects.wav', cues_path,
                                 '--json', path)
            status = {0: 'pass', 1: 'inspect'}.get(code, 'could not run')
            return {'tool': 'cue_onsets.py', 'exit': code, 'status': status, 'json': str(path),
                    'summary': [x for x in text.strip().splitlines() if x.strip()][:12]}, [path]
        result = self.step('cue onsets', {'effects': sha256(self.out / 'sound' / 'effects.wav'),
                                          'cues': sha256(cues_path), 'tool': self.tool_hashes('cue_onsets.py')}, go)
        if result['status'] != 'pass':
            self.finding('sound', 'cue_onsets', ' '.join(result['summary'][:3])[:300])
        return result

    # --- delivery -------------------------------------------------------------------------
    def deliver(self, info, source, sound, renders, delivered, qcs, onsets, cues_path):
        deliver = self.out / 'deliver'
        deliver.mkdir(parents=True, exist_ok=True)
        keep = {Path(d['path']).name for d in delivered.values()}
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
                 'settings': {'size': label, 'res': self.a.res, 'samples': 1 if self.a.preview else self.a.samples,
                              'preview': self.a.preview, 'shutter': 180, 'encode': 'film_render.py defaults '
                              '(H.264 High, CRF 14, BT.709 matrix and tags, closed GOP, fast start)',
                              'audio': d['audio'], 'mux': None if sound['mode'] == 'none' else
                              'video stream copied; AAC-LC 48 kHz 256 kbps; apad; -t ' + f"{d['duration']:.6f} s; +faststart"},
                 'sources': {'picture_source_sha256': source['sha256'], 'render': r['path'],
                             'render_sha256': sha256(r['path']) if Path(r['path']).is_file() else None,
                             'frozen_copy_sha256': r.get('frozen_sha256', {}),
                             'cues_sha256': sha256(cues_path), 'mix_sha256': sound.get('mix_sha256'),
                             'palette': sound.get('palette')},
                 'versions': r.get('versions', {}), 'captions': [c.name for c in captions],
                 'status': {'watched': 'unwatched', 'sound': 'intentionally absent (no audio stream)' if
                            sound['mode'] == 'none' else 'unheard' + (' (draft soundtrack)' if draft else ''),
                            'published': 'nothing posted, uploaded or sent'}}
            save_json(str(path) + '.manifest.json', m)
            manifests[label] = m
        report = self.report(info, source, sound, renders, delivered, qcs, onsets, manifests, captions)
        (deliver / 'delivery-report.md').write_text(report, encoding='utf-8')
        return manifests

    def report(self, info, source, sound, renders, delivered, qcs, onsets, manifests, captions):
        draft, silent = sound['mode'] == 'draft', sound['mode'] == 'none'
        sound_status = ('audio intentionally absent; no audio stream, verified by qc_file.py --audio none' if silent else
                        '**unheard** (draft soundtrack: synthesised by make_sound_kit.py; not for release until a '
                        'person listens and decides)' if draft else '**unheard**')
        files = [f'{m["file"]}: {m["bytes"] / 1e6:.6f} MB, SHA-256 `{m["sha256"]}`' for m in manifests.values()]
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
                f"render: res {self.a.res}, " + ('preview (one sample per frame, no motion blur; not a delivery '
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
            'Asset rights (`assets.csv`)': ('not checked by make_film.py' + (
                '; the draft sound is synthesised by make_sound_kit.py (generated for this project, no third-party '
                'material)' if draft else '') + ('; assets.csv present, not verified' if
                                                 (self.film / 'assets.csv').is_file() else '; no assets.csv in the film folder')),
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
        head = ['', '## Items to inspect', ''] + ([f'- {x}' for x in inspect] or
                                                  ['- None from the automated checks. The checks measure files; they '
                                                   'do not watch or listen.']) + ['']
        anchor = '\n## Not checked, and why'
        return text.replace(anchor, '\n'.join(head) + anchor, 1) if anchor in text else text + '\n'.join(head)

    def previous_note(self):
        prev = self.out / 'previous' / self.stamp
        if prev.exists():
            return (f'A previous delivery in this folder was set aside in `previous/{self.stamp}/`. Describe what '
                    'changed, with timestamps (make_film.py cannot know the intent of a change).')
        return 'No previous delivery in this output folder; no baseline compared.'


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('film', nargs='?', help='film folder (a kit project with index.html)')
    p.add_argument('--sizes', default='1920x1080,1080x1920', help='comma-separated CSS sizes WxH, one timeline')
    p.add_argument('--res', choices=('720', '1080', '2160'), default='1080')
    p.add_argument('--preview', action='store_true', help='sharp one-sample render, not a delivery master')
    p.add_argument('--samples', type=int, default=4)
    p.add_argument('--sound', help='draft, none or a palette.json path; default the film\'s palette, else draft')
    p.add_argument('--drop-beat', type=float, help='zero-based film beat for the draft drop, if the film declares none')
    p.add_argument('--out', help='output folder; default FILM-make beside the film folder')
    p.add_argument('--name', help='deliverable base name; default the film folder name')
    p.add_argument('--resume', action='store_true', help='skip steps whose outputs and inputs are unchanged')
    p.add_argument('--force', action='store_true', help='continue past preflight errors')
    p.add_argument('--doctor', action='store_true', help='check the environment only; exit 0 ready, 1 missing')
    p.add_argument('--json', help='write the run summary here')
    p.add_argument('--node')
    p.add_argument('--playwright')
    p.add_argument('--browser')
    p.add_argument('--ffmpeg')
    p.add_argument('--ffprobe')
    a = p.parse_args()
    try:
        sizes = [parse_size(s) for s in a.sizes.split(',') if s.strip()]
        if not sizes or len(set(sizes)) != len(sizes):
            raise ValueError('--sizes needs distinct WxH sizes')
    except ValueError as exc:
        p.error(str(exc))
    if a.samples < 1 or (a.drop_beat is not None and (not math.isfinite(a.drop_beat) or a.drop_beat < 0)):
        p.error('--samples must be at least 1 and --drop-beat a non-negative beat')
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
    out = Path(a.out).resolve() if a.out else film.parent / (film.name + '-make')
    if not (film / 'index.html').is_file():
        print(f'make_film.py: could not run: {film} has no index.html (a kit film folder)', file=sys.stderr)
        return finish(2, {'error': 'not a film folder'})
    if out == film or film in out.parents:
        print('make_film.py: could not run: --out must be outside the film folder (renders copy that folder)',
              file=sys.stderr)
        return finish(2, {'error': 'output inside the film folder'})
    if a.sound in (None, 'draft', 'none'):
        own = next((x for x in (film / 'palette.json', film / 'audio' / 'palette.json') if x.is_file()), None)
        sound_mode = a.sound or (str(own) if own else 'draft')
    else:
        sound_mode = str(Path(a.sound).resolve())
        if not Path(sound_mode).is_file():
            print(f'make_film.py: could not run: palette {a.sound} not found', file=sys.stderr)
            return finish(2, {'error': 'palette missing'})
    try:
        out.mkdir(parents=True, exist_ok=True)
        m = Make(a, film, out, sizes)
        m.sound_mode = sound_mode
        if not a.resume:
            for name in ('deliver', 'sound', 'qa', 'cues.json'):
                m.set_aside(out / name)
        for size in sizes:
            w, h = m.out_dims(size)
            if w % 2 or h % 2:
                raise CouldNotRun(f'{m.label(size)} at --res {a.res} gives {w}x{h}; H.264 4:2:0 needs even sides')
        print(f'make_film.py: {film.name} -> {out}', flush=True)
        source = m.picture_source()
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
        sound = m.sound(info, cues_path)
        print(f"  sound: {sound['mode']}" + (f" ({'; '.join(sound.get('notes', []))})" if sound.get('notes') else ''),
              flush=True)
        renders, delivered, qcs = {}, {}, {}
        for size in sizes:
            label = m.label(size)
            r = m.render(size, info, source)
            if not r:
                continue
            renders[label] = r
            print(f'  render {label}: {Path(r["path"]).name}' +
                  (f'; {m.size_notes[label]}' if label in m.size_notes else ''), flush=True)
            delivered[label] = m.mux(size, r, sound, info)
        onsets = m.cue_onsets(sound, cues_path)
        for size in sizes:
            label = m.label(size)
            if label in delivered:
                own = dict(info, **{k: renders[label].get('info', {}).get(k) for k in PER_SIZE})
                qcs[label] = m.qc(size, delivered[label], sound, own, cues_path)
                states = ', '.join(f"{k} {c.get('status')}" for k, c in qcs[label]['checks'].items())
                print(f'  qc {label}: {states}', flush=True)
        if not delivered:
            raise Stopped('no size rendered; nothing to deliver')
        manifests = m.deliver(info, source, sound, renders, delivered, qcs, onsets, cues_path)
        code = 1 if m.findings else 0
        status = ('unwatched; ' + ('audio intentionally absent' if sound['mode'] == 'none' else
                                   'sound unheard' + (' (draft soundtrack)' if sound['mode'] == 'draft' else '')))
        print(f"  delivered: {', '.join(x['file'] for x in manifests.values())} in {out / 'deliver'}")
        print(f'  status: {status}; nothing posted. Weakest point: write it in deliver/delivery-report.md after '
              'looking at the sheets in qa/.')
        for f in m.findings:
            print(f"  INSPECT {f['size']}: {f['check']}: {f['detail']}")
        print(f'exit {code}: ' + (f'{len(m.findings)} item(s) need inspection' if code else 'every automated check passed'))
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
