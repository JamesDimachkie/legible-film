#!/usr/bin/env python3
"""Check what Legible Film can do on this machine.

  python setup.py [--json] [--check-updates] [--install core|transcription|faces|spatial|kit|ear] [--download] [--yes]

Checks local tools and cached models; it does not prove a film is good or launch Chromium.
Updates are checked only on request. Installation downloads public software, at the versions constraints.txt names,
into the virtual environment this Python is in, otherwise into a per-user environment; it never changes a shared
Python. Model weights download only with --download: the small transcription model (about 460 MB) with --install
transcription, the subject model (about 26 MB) with --install spatial. --install ear names its weights' size and asks
before it fetches them. Spatial and local transcription are limited without their model.
Exit 0 when editing and checking video is ready (with --install, when the installed capability is ready too),
1 when either is limited or missing, 2 if setup cannot run. Optional capabilities are reported; they do not change
the exit code.
"""
import argparse
import ctypes
import importlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('lf_project', HERE / 'project.py')
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
CONSTRAINTS = HERE / 'constraints.txt'
# The exact film kit package, which also fixes the Chromium build; CI's kit job reads this line.
PLAYWRIGHT_CORE = '1.64.1'
MODEL_MB = 460
REQUIRED = ('Edit and check video', 'Skill')
FFMPEG_MINIMUM = (5, 1)
INSTALLS = {'core': 'Edit and check video', 'transcription': 'Local transcription',
            'faces': 'Scorecard (optional)', 'spatial': 'Spatial (optional)', 'kit': 'Film kit (optional)',
            'ear': 'Machine'}
# What each optional group is for, so a person fixes only what their job needs.
JOBS = {'Local transcription': 'transcripts made on this machine (an imported transcript needs none)',
        'Film kit (optional)': 'designed films, teasers and animated inserts made with the kit',
        'Scorecard (optional)': 'automatic crops that follow faces, and face checks in the scorecard',
        'Spatial (optional)': 'tracking, pinned graphics, titles behind a person and tracked blur',
        'Machine': 'speed: with little free memory, long transcriptions and renders run slower, not wrongly'}
SPATIAL_MODEL = 'modnet.onnx'
SPATIAL_SHA256 = '07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9'
SPATIAL_URL = ('https://huggingface.co/Xenova/modnet/resolve/'
               'fa2fa546052fba4c08921230a26cc69a333fca12/onnx/model.onnx')
SPATIAL_MB = 26
EAR_MODELS = ('laion/larger_clap_general', 'MIT/ast-finetuned-audioset-10-10-0.4593')
SCRIPTS = ('assemble.py blank_scan.py captions.py check.py compare_versions.py cue_list.py cue_onsets.py '
           'delivery_check.py dialogue_io.py '
           'exchange.py film_capture.mjs film_check.py film_render.py flash_scan.py frame_sheet.py '
           'kit_selftest.py lineup.py listen.py look.py make_film.py make_sound_kit.py map.py matte.py mix_cues.py motion_blur.py motion_scan.py '
           'new_film.py onion_frames.py project.py qc_file.py reframe.py region_check.py render_common.py '
           'screen.py selftest.py setup.py sound_check.py sound_io.py sound_library.py spatial.py spot_cues.py '
           'strip.py sync_check.py taste.py tempo_map.py tighten.py track.py transcribe.py transcript_cut.py '
           'voice_clean.py with_lock.py constraints.txt').split()


def command_fix(kind, system=None):
    """Return the platform's manual installation command."""
    system = system or platform.system()
    commands = {
        'Windows': ('winget install --id Gyan.FFmpeg -e', 'winget install --id OpenJS.NodeJS.LTS -e'),
        'Darwin': ('brew install ffmpeg', 'brew install node'),
        'Linux': ('sudo apt update && sudo apt install ffmpeg', 'sudo apt update && sudo apt install nodejs npm'),
    }
    if system not in commands:
        return 'Install a supported build for your operating system; see https://ffmpeg.org/download.html'
    command = commands[system][0 if kind == 'ffmpeg' else 1]
    if system in ('Windows', 'Darwin'):
        command += '\n    After installation, open a new terminal or restart the agent to refresh PATH.'
    return command


def data_home():
    """The user's data directory; the dedicated environment is never placed in the working folder."""
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'legible-film'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'legible-film'


def dedicated_python():
    """Return the executable in the one per-user environment, whether or not it exists yet."""
    return data_home() / 'venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def has_pip(python):
    """Check pip in the actual target interpreter, including venvs created without pip."""
    try:
        result = subprocess.run([str(python), '-I', '-m', 'pip', '--version'], capture_output=True, timeout=15)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def selected_python(create=False):
    """An active virtual environment that can take installs (or, to run scripts, already has the core packages), then
    the dedicated interpreter, created when needed. A base interpreter is never installed into, however writable:
    other work may share it."""
    dedicated = dedicated_python()
    purelib = Path(sysconfig.get_path('purelib'))
    existing = purelib
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    if sys.prefix != sys.base_prefix and (has_pip(sys.executable) and os.access(existing, os.W_OK) if create
                                          else imports_core(sys.executable)):
        return Path(sys.executable)
    if dedicated.is_file():
        if create and not has_pip(dedicated):
            fix = project.python_command(['-m', 'ensurepip', '--upgrade'], dedicated)
            raise ValueError('The dedicated environment has no pip. On Debian or Ubuntu install python3-venv '
                             '(sudo apt install python3-venv), then run: ' + fix)
        return dedicated
    if not create:
        return Path(sys.executable)
    try:
        subprocess.run([sys.executable, '-I', '-m', 'venv', str(dedicated.parent.parent)],
                       check=True, stdout=sys.stderr, stderr=sys.stderr)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError('Could not create a Python environment with pip. On Debian or Ubuntu install '
                         'python3-venv (sudo apt install python3-venv), then run this command again.') from error
    if not dedicated.is_file() or not has_pip(dedicated):
        raise ValueError('The new environment has no pip. On Debian or Ubuntu install python3-venv '
                         '(sudo apt install python3-venv), then run this command again.')
    return dedicated


def winget_link(name):
    """Find a WinGet link even if this process inherited an old PATH."""
    if os.name != 'nt' or not os.environ.get('LOCALAPPDATA'):
        return None
    candidate = Path(os.environ['LOCALAPPDATA']) / 'Microsoft' / 'WinGet' / 'Links' / (name + '.exe')
    return candidate if candidate.is_file() else None


def old_ffmpeg_fix(system=None):
    """Do not suggest reinstalling a distribution package that is known to be too old."""
    system = system or platform.system()
    if system == 'Linux':
        return ('Ubuntu 22.04 commonly supplies FFmpeg 4.4; Debian 11 supplies 4.3. '
                'Upgrade to a release with FFmpeg 5.1 or later, or install a current build from '
                'https://ffmpeg.org/download.html and put it first on PATH.')
    if system == 'Darwin':
        return ('brew upgrade ffmpeg\n    FFmpeg 5.1 or later is required. After installation, open a new terminal '
                'or restart the agent.')
    if system == 'Windows':
        return command_fix('ffmpeg', system) + '\n    FFmpeg 5.1 or later is required.'
    return 'Install FFmpeg 5.1 or later from https://ffmpeg.org/download.html.'


def run(args, timeout=2):
    """Run a short local probe, returning its output or an empty string."""
    try:
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=timeout)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


_IMPORTS = {}


def module_available(name):
    """Whether the scripts can import a dependency, native libraries included. They run each other isolated
    (python -I), which hides packages installed only for this user, so the probe imports the same way."""
    if name not in _IMPORTS:
        try:
            result = subprocess.run([sys.executable, '-I', '-c', f'import {name}'], capture_output=True, timeout=180)
            _IMPORTS[name] = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _IMPORTS[name] = False
    return _IMPORTS[name]


def user_site_only(name):
    """A package this Python imports only from the user's own site-packages, which isolated runs cannot see."""
    if module_available(name):
        return False
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def unseen(name):
    """The words for a package installed only for this user, or ''."""
    return (' (it is installed for this user only, where the scripts, which run isolated with python -I, cannot see '
            'it; the install command puts it where they can)') if user_site_only(name) else ''


def ffmpeg_release(version_line):
    """The (major, minor) release in an `ffmpeg -version` first line; None for a development build or no match."""
    match = re.search(r'version\s+n?(\d+)\.(\d+)', version_line or '')
    return (int(match.group(1)), int(match.group(2))) if match else None


def ffmpeg_features():
    """Find executable versions and exact encoder and filter names."""
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    versions = {name: (run([path, '-version']).splitlines() or [''])[0] if path else ''
                for name, path in (('ffmpeg', ffmpeg), ('ffprobe', ffprobe))}
    encoders = run([ffmpeg, '-hide_banner', '-encoders']) if ffmpeg else ''
    filters = run([ffmpeg, '-hide_banner', '-filters']) if ffmpeg else ''
    names = lambda text: {parts[1] for line in text.splitlines() if len(parts := line.split()) > 1}
    return versions, {name: name in names(encoders) for name in ('libx264', 'aac')}, {
        name: name in names(filters) for name in ('ass', 'zscale', 'whisper')}


def cached_models():
    """Find complete faster-whisper snapshots in the configured Hugging Face cache."""
    root = Path(os.environ.get('HF_HUB_CACHE') or
                Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub')
    found = []
    for folder in root.glob('models--Systran--faster-whisper-*'):
        snapshots = folder / 'snapshots'
        for snap in snapshots.glob('*'):
            if all((snap / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json')):
                found.append(folder.name.replace('models--Systran--faster-whisper-', '', 1))
                break
    return sorted(set(found))


def ear_cache():
    """Keep listening models in the skill's per-user model cache."""
    return data_home() / 'models' / 'ear'


def ear_models_cached():
    """Find a locally complete snapshot for each listening model without loading it."""
    found = []
    for model in EAR_MODELS:
        snapshots = ear_cache() / ('models--' + model.replace('/', '--')) / 'snapshots'
        complete = any((p / 'config.json').is_file() and (p / 'preprocessor_config.json').is_file()
                       and ((p / 'model.safetensors').is_file() or (p / 'pytorch_model.bin').is_file())
                       for p in snapshots.glob('*') if p.is_dir())
        if complete:
            found.append(model)
    return found


def ear_packages_available():
    """Check package presence without importing or loading the models."""
    try:
        return all(importlib.util.find_spec(name) is not None for name in ('torch', 'transformers'))
    except (ImportError, ValueError):
        return False


def ear_ready():
    return ear_packages_available() and len(ear_models_cached()) == len(EAR_MODELS)


def free_memory():
    """Return available physical bytes, or None if the platform does not expose it."""
    try:
        if os.name == 'nt':
            class Memory(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                    (key, ctypes.c_ulonglong) for key in ('total', 'available', 'page', 'free_page',
                                                           'virtual', 'free_virtual', 'extended')]
            value = Memory()
            value.length = ctypes.sizeof(value)
            return value.available if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)) else None
        if sys.platform == 'darwin':
            output = run(['vm_stat'])
            page = re.search(r'page size of (\d+) bytes', output)
            counts = re.findall(r'Pages (?:free|inactive|speculative):\s*(\d+)\.', output)
            return int(page.group(1)) * sum(map(int, counts)) if page and counts else None
        for line in Path('/proc/meminfo').read_text(encoding='utf-8').splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, AttributeError):
        pass
    return None


def kit_doctor():
    """Use make_film's own doctor and bound the probe's runtime."""
    try:
        result = subprocess.run([sys.executable, str(HERE / 'make_film.py'), '--doctor'], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=5)
        rows = {}
        for line in result.stdout.splitlines():
            match = re.match(r'^(ok\s+|MISSING)\s+(Node|Playwright|Chromium):\s*(.*)', line)
            if match:
                rows[match.group(2)] = (match.group(1).strip() == 'ok', match.group(3))
        return rows
    except (OSError, subprocess.TimeoutExpired):
        return {}


def latest_release(version):
    """Make the single opt-in HTTPS request and compare numeric release versions."""
    url = 'https://api.github.com/repos/JamesDimachkie/legible-film/releases/latest'
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json',
                                                   'User-Agent': 'legible-film-setup'})
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            release = json.load(response)
        tag = release['tag_name']
        current = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', version)
        newer = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', tag)
        if not current or not newer:
            return None, 'Cannot compare release version ' + str(tag)
        return tuple(map(int, newer.groups())) > tuple(map(int, current.groups())), str(tag)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, 'Update check failed: ' + str(exc)


def inspect(check_updates=False):
    """Return capability states and actionable details without changing the machine."""
    groups = {}

    def add(group, state, label, detail, fix=None, required=True):
        groups.setdefault(group, []).append({'state': state, 'label': label, 'detail': detail, 'fix': fix,
                                             'required': required})

    def setup_command(option):
        """Format this interpreter's install command for the current shell."""
        return project.python_command([HERE / 'setup.py', '--install', option])
    add('Edit and check video', 'ready' if sys.version_info >= (3, 9) else 'missing', 'Python',
        platform.python_version() + ' at ' + sys.executable + ' (run every script with this one)',
        'Install Python 3.9 or newer and run setup with it.')
    for name, package in (('numpy', 'numpy'), ('PIL', 'Pillow')):
        ok = module_available(name)
        add('Edit and check video', 'ready' if ok else 'missing', package,
            'importable' if ok else project.dependency_message(name) + unseen(name), setup_command('core'))
    versions, encoders, filters = ffmpeg_features()
    for name, version in versions.items():
        release = ffmpeg_release(version)
        if not version:
            link = winget_link(name)
            detail = 'needed to process or inspect video'
            if link:
                detail += f'; found {link}, but not on PATH: open a new terminal or restart the agent'
            fix = ('Open a new terminal or restart the agent to refresh PATH.' if link else command_fix('ffmpeg'))
            add('Edit and check video', 'missing', name, detail, fix)
        elif release and release < FFMPEG_MINIMUM:
            add('Edit and check video', 'limited', name, version + f' is older than {FFMPEG_MINIMUM[0]}.'
                f'{FFMPEG_MINIMUM[1]}, which the scripts need (frame timing, blur and compression measures)',
                old_ffmpeg_fix())
        else:
            add('Edit and check video', 'ready', name, version, command_fix('ffmpeg'))
    for name, purpose in (('libx264', 'H.264 video export'), ('aac', 'AAC audio export')):
        ok = encoders[name]
        add('Edit and check video', 'ready' if ok else 'limited', name,
            'encoder available' if ok else 'missing; limits ' + purpose + '; a build with ' + name + ' is needed',
            command_fix('ffmpeg'))
    for name, label, purpose in (('ass', 'libass', 'burning captions'), ('zscale', 'zscale', 'HDR to SDR')):
        ok = filters[name]
        add('Edit and check video', 'ready' if ok else 'limited', label,
            'filter available' if ok else 'missing; limits ' + purpose + '; a build with ' + label + ' is needed',
            command_fix('ffmpeg'), required=False)
    models = cached_models()
    package = module_available('faster_whisper')
    detector = module_available('onnxruntime')
    faster = package and detector
    fallback = filters['whisper']
    trans_state = 'ready' if faster and 'small' in models else 'limited' if fallback or package else 'missing'
    model_note = '' if 'small' in models else f'; the small model (about {MODEL_MB} MB) downloads only with --download'
    trans_fix = setup_command('transcription') if 'small' in models else project.python_command(
        [HERE / 'setup.py', '--install', 'transcription', '--download'])
    if faster:
        state = 'importable'
    elif package:
        state = ('importable; transcription works without voice detection. The voice-activity model needs '
                 'onnxruntime; map review prompts fall back to a speech-band energy heuristic' + unseen('onnxruntime'))
    else:
        state = 'not importable' + unseen('faster_whisper')
    add('Local transcription', trans_state, 'faster-whisper',
        state + '; cached models: ' + (', '.join(models) or 'none') + '; default: small' + model_note, trans_fix)
    if fallback and trans_state == 'ready':
        add('Local transcription', 'ready', 'FFmpeg whisper',
            'filter present; a less accurate fallback, used only with a GGML model file (--ggml-model PATH)',
            command_fix('ffmpeg'))
    elif fallback:
        add('Local transcription', 'limited', 'FFmpeg whisper',
            'filter present, but it transcribes only with a GGML model file you supply (map.py run --engine ffmpeg '
            '--ggml-model PATH); faster-whisper needs no model file of yours', trans_fix)
    elif trans_state == 'ready':
        add('Local transcription', 'ready', 'FFmpeg whisper',
            'filter missing; not needed while faster-whisper is ready', command_fix('ffmpeg'))
    else:
        add('Local transcription', 'limited', 'FFmpeg whisper',
            'filter missing; no FFmpeg transcription fallback; a build with whisper is needed', command_fix('ffmpeg'))
    cache = Path(os.environ.get('HF_HUB_CACHE') or
                 Path(os.environ.get('HF_HOME', Path.home() / '.cache' / 'huggingface')) / 'hub')
    existing = cache
    while not existing.exists() and existing.parent != existing:
        existing = existing.parent
    disk = shutil.disk_usage(existing).free
    add('Local transcription', 'ready' if disk >= MODEL_MB * 1000000 else 'limited', 'Model disk space',
        f'{disk / 1e9:.1f} GB free on model cache drive; small download is about {MODEL_MB} MB',
        'Free at least 1 GB on the model cache drive before downloading.')
    rows = kit_doctor()
    node_path = shutil.which('node')
    node_version = run([node_path, '--version']).strip() if node_path else ''
    major = re.match(r'v?(\d+)\.', node_version)
    if major and int(major.group(1)) < 18:
        rows['Node'] = (False, f'{node_version} is older than the kit needs (18 or later)')
    elif node_version:
        rows['Node'] = (True, node_version)
    elif not rows.get('Node', (False, ''))[0]:
        link = winget_link('node')
        rows['Node'] = (False, f'found {link}; open a new terminal or restart the agent' if link else 'not on PATH')
    # The film kit looks for playwright-core here by itself, so installing it is the whole fix.
    package_dir = data_home() / 'playwright'
    for name in ('Node', 'Playwright', 'Chromium'):
        ok, detail = rows.get(name, (False, 'doctor did not return this check'))
        node_fix = ('Open a new terminal or restart the agent to refresh PATH.'
                    if not node_path and winget_link('node') else command_fix('node'))
        playwright = project.python_command(['install', '--save-exact', '--prefix', package_dir,
                                             'playwright-core@' + PLAYWRIGHT_CORE], 'npm')
        chromium = project.python_command(['--prefix', package_dir, 'playwright-core', 'install', 'chromium'], 'npx')
        fix = {'Node': node_fix,
               'Playwright': f"{setup_command('kit')} (or by hand: {playwright})",
               'Chromium': f"{setup_command('kit')} (or by hand: {chromium})"}[name]
        add('Film kit (optional)', 'ready' if ok else 'missing', name, detail, fix)
    faces = module_available('cv2')
    add('Scorecard (optional)', 'ready' if faces else 'missing', 'OpenCV face detection',
        'importable; auto crop and scorecard can sample frontal faces, but can miss people; inspect the frames'
        if faces else 'not importable; auto crop uses motion and detail, and scorecard has no face detection'
        + unseen('cv2'),
        setup_command('faces'))
    ort = module_available('onnxruntime')
    model = data_home() / 'models' / SPATIAL_MODEL
    model_ok = model.is_file() and project.file_sha256(model) == SPATIAL_SHA256
    add('Spatial (optional)', 'ready' if faces else 'missing', 'OpenCV',
        'importable; shared with face detection' if faces else 'not importable; needed for tracking',
        setup_command('spatial'))
    add('Spatial (optional)', 'ready' if ort else 'missing', 'onnxruntime',
        'importable for CPU subject matting' if ort else 'not importable; subject matting is unavailable'
        + unseen('onnxruntime'),
        setup_command('spatial'))
    model_fix = project.python_command([HERE / 'setup.py', '--install', 'spatial', '--download'])
    add('Spatial (optional)', 'ready' if model_ok else 'missing', 'MODNet model',
        'pinned model cached' if model_ok else 'missing or hash mismatch; key, luma and difference still work',
        model_fix)
    ear_packages = ear_packages_available()
    ear_models = ear_models_cached()
    add('Machine', 'ready' if ear_packages else 'missing', 'Listening labels: CLAP and AST packages',
        'installed' if ear_packages else 'torch or transformers missing; no model was loaded',
        setup_command('ear'), required=False)
    add('Machine', 'ready' if len(ear_models) == len(EAR_MODELS) else 'missing',
        'Listening labels: local model weights', 'cached: ' + (', '.join(ear_models) or 'none'),
        setup_command('ear'), required=False)
    memory = free_memory()
    add('Machine', 'ready' if memory is not None and memory >= 4 * 1024 ** 3 else 'limited', 'Free memory',
        f'{memory / 1024 ** 3:.1f} GB available' if memory is not None else 'could not determine available memory',
        'Close other applications before long transcriptions; low memory can make them slow.')
    add('Machine', 'ready' if disk >= 1024 ** 3 else 'limited', 'Free disk',
        f'{disk / 1e9:.1f} GB on model cache drive',
        'Free at least 1 GB on the working drive.')
    skill = project.read_text(HERE.parent / 'SKILL.md')
    match = re.search(r'^\s+version:\s*["\']?([^"\'\s]+)', skill, re.MULTILINE)
    version = match.group(1) if match else 'unknown'
    add('Skill', 'ready' if match else 'limited', 'Version', version, 'Restore SKILL.md with version metadata.')
    missing = [name for name in SCRIPTS if not (HERE / name).is_file()]
    add('Skill', 'missing' if missing else 'ready', 'Scripts', ', '.join(missing) if missing else 'all present',
        'Reinstall the complete skill.')
    if check_updates:
        newer, detail = latest_release(version)
        add('Skill', 'limited' if newer is None or newer else 'ready', 'Updates', detail,
            'Review the latest release at https://github.com/JamesDimachkie/legible-film/releases/latest')
    return groups


def summary(groups):
    """Compute readiness: a missing part of an otherwise usable capability is limited."""
    result = {}
    for name, rows in groups.items():
        states = [row['state'] for row in rows if row.get('required', True)]
        result[name] = 'ready' if all(s == 'ready' for s in states) else (
            'missing' if all(s == 'missing' for s in states) else 'limited')
    return result


def exit_code(states, installed=None):
    """0 when the required capabilities (and the one just installed) are ready, otherwise 1."""
    if installed == 'ear':
        return 0 if all(states.get(name) == 'ready' for name in REQUIRED) and ear_ready() else 1
    judged = list(REQUIRED) + ([INSTALLS[installed]] if installed else [])
    return 0 if all(states.get(name) == 'ready' for name in judged) else 1


def consent(question, yes):
    """Go ahead only with the person's yes: --yes, or a typed yes at an interactive prompt."""
    if yes:
        return
    if not sys.stdin.isatty():
        raise ValueError('Not installed: person must agree; then pass --yes.')
    try:
        print(question + ' [y/N] ', end='', file=sys.stderr, flush=True)
        answer = input().strip().lower()
    except EOFError:
        answer = ''
    if answer not in ('y', 'yes'):
        raise ValueError('Not installed: consent was not given.')


def core_present():
    """Whether the Python setup would select already imports numpy and Pillow, so --install core has nothing to do."""
    if dedicated_python().is_file():
        return False
    return module_available('numpy') and module_available('PIL')


def imports_core(python):
    """Whether this interpreter imports numpy and Pillow the way the scripts run."""
    return subprocess.run([str(python), '-I', '-c', 'import numpy, PIL'], capture_output=True).returncode == 0


def pip_install(python, packages, *options):
    """Install at the tested versions, from wheels: a version with no wheel here fails at once, not after a long
    source build that was never tested."""
    command = [str(python), '-I', '-m', 'pip', 'install', '-c', str(CONSTRAINTS), '--only-binary', ':all:', *packages,
               *options]
    try:
        subprocess.run(command, check=True, stdout=sys.stderr)
    except subprocess.CalledProcessError as error:
        raise ValueError(f"pip could not install {', '.join(packages)} at the versions in {CONSTRAINTS.name}; its "
                         'reason is above. No matching version means no tested build for this Python or system: '
                         'tested on Python 3.9 to 3.14. Run setup.py with one of those, from a virtual environment '
                         f'or after removing {dedicated_python().parent.parent}.'
                         ) from error


def install_core(python):
    """Install the two core packages in the selected interpreter."""
    pip_install(python, ['numpy', 'Pillow'])


def install_faces(yes, python=None):
    """Ask before installing OpenCV for automatic cropping and scorecard face detection."""
    print('Face detection for auto crop and scorecard: opencv-python is about 40 MB; '
          'no model weights are downloaded.', file=sys.stderr)
    consent('Install opencv-python?', yes)
    pip_install(python or sys.executable, ['opencv-python'])


def install_spatial(yes, python=None):
    """Install the same OpenCV distribution as faces plus ONNX Runtime."""
    print('Spatial packages: opencv-python and onnxruntime; model weights are a separate download.', file=sys.stderr)
    consent('Install spatial packages?', yes)
    pip_install(python or sys.executable, ['opencv-python', 'onnxruntime'])


def download_spatial(yes):
    """Download only the pinned public model into the per-user cache after consent."""
    print(f'MODNet model download: about {SPATIAL_MB} MB, Apache-2.0.', file=sys.stderr)
    consent('Download MODNet model?', yes)
    target = data_home() / 'models' / SPATIAL_MODEL
    if target.is_file() and project.file_sha256(target) == SPATIAL_SHA256:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = tempfile.NamedTemporaryFile(prefix='.modnet-', suffix='.onnx', dir=str(target.parent), delete=False)
    temporary.close()
    path = Path(temporary.name)
    try:
        urllib.request.urlretrieve(SPATIAL_URL, str(path))
        if project.file_sha256(path) != SPATIAL_SHA256:
            raise ValueError('downloaded MODNet SHA-256 does not match the pinned model')
        os.replace(path, target)
    finally:
        if path.exists():
            path.unlink()


def install_kit(yes):
    """Install playwright-core and Chromium where the film kit looks for them; Node itself is the person's install."""
    npm, npx = shutil.which('npm'), shutil.which('npx')
    if not npm or not npx:
        raise ValueError('The film kit needs Node.js 18 or later with npm; install it first: ' + command_fix('node'))
    package_dir = data_home() / 'playwright'
    print(f'Film kit: playwright-core (about 10 MB) and Chromium (about 150 MB) into {package_dir}.', file=sys.stderr)
    consent('Install the film kit?', yes)
    package_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([npm, 'install', '--save-exact', '--prefix', str(package_dir), 'playwright-core@' + PLAYWRIGHT_CORE],
                   check=True, stdout=sys.stderr)
    subprocess.run([npx, '--prefix', str(package_dir), 'playwright-core', 'install', 'chromium'], check=True,
                   stdout=sys.stderr)
    # Installed is not the same as working: Chromium on Linux also needs system libraries the person installs.
    launch = ("const pw = require(process.argv[1]); pw.chromium.launch().then(b => b.close())"
              ".catch(e => { console.error(e.message.split('\\n')[0]); process.exit(1); });")
    started = subprocess.run([shutil.which('node') or 'node', '-e', launch,
                              str(package_dir / 'node_modules' / 'playwright-core')],
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
    if started.returncode:
        libraries = (f" On Linux it also needs system libraries: sudo {npx} --prefix {package_dir} playwright-core "
                     'install-deps chromium' if platform.system() == 'Linux' else '')
        raise ValueError('Chromium was installed but did not start: '
                         + (started.stderr.strip().splitlines() or ['no reason given'])[-1] + '.' + libraries)
    print('Chromium starts.', file=sys.stderr)


def install_transcription(yes, python=None):
    """Ask before installing the optional package; its model is a separate download."""
    print(f'Transcription packages: faster-whisper and onnxruntime. The small model is a separate download of about '
          f'{MODEL_MB} MB, only with --download.', file=sys.stderr)
    consent('Install faster-whisper?', yes)
    pip_install(python or sys.executable, ['faster-whisper', 'onnxruntime'])


def download_transcription(yes, python=None):
    """Download the default model into the Hugging Face cache after consent."""
    print(f'Small model download: about {MODEL_MB} MB.', file=sys.stderr)
    consent('Download the small model?', yes)
    subprocess.run([str(python or sys.executable), '-I', '-c',
                    "from faster_whisper.utils import download_model; download_model('small')"],
                   check=True, stdout=sys.stderr)


def ear_size():
    print('Listening labels: about 1.4 GB of CLAP and AST model weights, plus CPU PyTorch, transformers and '
          'audio packages; download sizes vary. CLAP is Apache-2.0; AST is BSD-3-Clause.', file=sys.stderr)


def install_ear_packages(python):
    """The CPU listening packages: PyTorch from its CPU index, the others from PyPI. pip 23.0, which older Pythons
    bring, rejects that index's metadata, so the constraints move it first."""
    pypi = ('--isolated', '--index-url', 'https://pypi.org/simple')
    pip_install(python, ['pip'], *pypi)
    pip_install(python, ['torch'], '--isolated', '--index-url', 'https://download.pytorch.org/whl/cpu')
    pip_install(python, ['transformers', 'huggingface-hub', 'safetensors', 'librosa', 'soundfile', 'soxr'], *pypi)


def install_ear(yes, python=None):
    """Install CPU dependencies and cache the two public models after consent."""
    ear_size()
    consent('Install CPU listening packages and download the model weights?', yes)
    python = str(python or sys.executable)
    install_ear_packages(python)
    code = ('import sys; from huggingface_hub import snapshot_download; '
            '[snapshot_download(repo_id=m, cache_dir=sys.argv[1], token=False) for m in sys.argv[2:]]')
    subprocess.run([python, '-I', '-c', code, str(ear_cache()), *EAR_MODELS], check=True, stdout=sys.stderr)


def main():
    """Parse options and print a concise summary before the details."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--json', action='store_true', help='print the report as JSON, with the Python to use')
    parser.add_argument('--check-updates', action='store_true', help='ask GitHub whether a newer release exists')
    parser.add_argument('--install', choices=['core', 'transcription', 'faces', 'spatial', 'kit', 'ear'],
                        help="install one group, with the person's yes (core: numpy and Pillow)")
    parser.add_argument('--download', action='store_true',
                        help=f'with --install transcription, also download the small model (about {MODEL_MB} MB); '
                             f'with --install spatial, the subject model (about {SPATIAL_MB} MB)')
    parser.add_argument('--report-installed', choices=['core', 'transcription', 'faces', 'spatial', 'kit', 'ear'],
                        help=argparse.SUPPRESS)
    parser.add_argument('--yes', action='store_true', help='install without asking (the person has already said yes)')
    args = parser.parse_args()
    try:
        if args.download and args.install not in ('transcription', 'spatial'):
            raise ValueError('--download requires --install transcription or --install spatial')
        if args.install == 'core' and core_present():
            # Nothing to install: a Python that refuses installs (Debian, Homebrew) may still have both.
            print('numpy and Pillow already import in this Python; nothing to install.', file=sys.stderr)
            args.install = None
        if args.install == 'kit':
            install_kit(args.yes)
            args.install, args.report_installed = None, 'kit'
        if args.install:
            if args.install == 'core':
                consent('Install numpy and Pillow?', args.yes)
            else:
                if args.install == 'ear':
                    ear_size()
                if args.install == 'spatial' and args.download:
                    print(f'MODNet download: about {SPATIAL_MB} MB.', file=sys.stderr)
                consent('Install ' + args.install + (f' and download the small model (about {MODEL_MB} MB)?'
                        if args.install == 'transcription' and args.download else
                        f' and download MODNet (about {SPATIAL_MB} MB)?'
                        if args.install == 'spatial' and args.download else '?'), args.yes)
            python = selected_python(create=True)
            if args.install != 'core' and not imports_core(python):
                # A new environment has neither, and setup then names it as the Python to run every script with.
                print('numpy and Pillow, which every script needs, go in too: this environment lacks them.',
                      file=sys.stderr)
                install_core(python)
            if args.install == 'core':
                install_core(python)
            elif args.install == 'transcription':
                install_transcription(True, python)
                if args.download:
                    download_transcription(True, python)
            elif args.install == 'spatial':
                install_spatial(True, python)
                if args.download:
                    download_spatial(True)
            elif args.install == 'ear':
                install_ear(True, python)
            else:
                install_faces(True, python)
        else:
            python = selected_python()
        if os.path.normcase(os.path.abspath(str(python))) != os.path.normcase(os.path.abspath(sys.executable)):
            command = [str(python), '-I', str(HERE / 'setup.py')]
            if args.json:
                command.append('--json')
            if args.check_updates:
                command.append('--check-updates')
            if args.install or args.report_installed:
                command.extend(['--report-installed', args.install or args.report_installed])
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
            if result.stderr:
                print(result.stderr, end='', file=sys.stderr)
            print(result.stdout, end='')
            return result.returncode
        importlib.invalidate_caches()
        groups = inspect(args.check_updates)
        states = summary(groups)
        code = exit_code(states, args.install or args.report_installed)
        if args.json:
            print(json.dumps({'python': sys.executable, 'editing_and_checking_ready':
                              all(states.get(name) == 'ready' for name in REQUIRED),
                              'summary': states, 'capabilities': groups, 'exit_code': code}, indent=2))
        else:
            print('Legible Film on this machine:')
            for name, state in states.items():
                print(f'  {name}: {state}')
            needed = [f'{name} matters only for {JOBS[name]}' for name, state in states.items()
                      if state != 'ready' and name in JOBS]
            if needed:
                print('Fix only what your job needs. ' + '; '.join(needed) + '.')
            for name, rows in groups.items():
                print('\n' + name + ':')
                for row in rows:
                    print(f"  {row['state']}: {row['label']} - {row['detail']}")
                    if row['state'] != 'ready' and row['fix'] and row['fix'] not in row['detail']:
                        print('    Fix: ' + row['fix'])
        return code
    except Exception as exc:
        if args.json:
            print(json.dumps({'python': str(selected_python()), 'editing_and_checking_ready': False,
                              'error': str(exc), 'exit_code': 2}))
        else:
            print('Setup could not run: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
