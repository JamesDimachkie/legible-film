"""Offline cases for setup.py, including the actual local FFmpeg probe."""
import hashlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest import mock


def check_kit_install(record, setup, j):
    """--install kit needs Node first, installs playwright-core and Chromium where the kit looks, then starts Chromium
    once; on Linux a Chromium that will not start names the system-library command (no network: commands are recorded,
    not run)."""
    try:
        with mock.patch.object(setup.shutil, 'which', return_value=None):
            setup.install_kit(True)
        missing = ''
    except ValueError as error:
        missing = str(error)
    home = Path(j('kit-home'))
    target = str(home / 'playwright')

    def install(launches, system):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            failed = launches is False and command[1] == '-e'
            return subprocess.CompletedProcess(command, 1 if failed else 0, '', 'libnss3.so: cannot open' if failed
                                               else '')
        with mock.patch.object(setup.shutil, 'which', side_effect=lambda name: f'/usr/bin/{name}'), \
                mock.patch.object(setup, 'data_home', return_value=home), \
                mock.patch.object(setup.platform, 'system', return_value=system), \
                mock.patch.object(setup.subprocess, 'run', side_effect=run):
            try:
                setup.install_kit(True)
                return calls, ''
            except ValueError as error:
                return calls, str(error)
    calls, error = install(True, 'Windows')
    broken_calls, broken = install(False, 'Linux')
    record('setup: --install kit asks for Node first, installs playwright-core and Chromium where the kit looks, and '
           'starts Chromium once',
           'Node.js' in missing and not error and calls[:2] == [
               ['/usr/bin/npm', 'install', '--save-exact', '--prefix', target,
                'playwright-core@' + getattr(setup, 'PLAYWRIGHT_CORE', 'unpinned')],
               ['/usr/bin/npx', '--prefix', target, 'playwright-core', 'install', 'chromium']]
           and calls[2][:2] == ['/usr/bin/node', '-e'], missing + error + str(calls))
    record('setup: the kit pins playwright-core to one exact version, which also fixes the Chromium build',
           bool(re.fullmatch(r'\d+\.\d+\.\d+', getattr(setup, 'PLAYWRIGHT_CORE', ''))),
           str(getattr(setup, 'PLAYWRIGHT_CORE', None)))
    record('setup: on Linux, a Chromium that will not start names the reason and the system-library command',
           'did not start' in broken and 'libnss3' in broken and 'install-deps chromium' in broken
           and 'sudo' in broken, broken)


def check_job_routing(record, setup):
    """A limited optional group is named with the job it serves, so the person fixes only what their job needs."""
    def row(state):
        return [{'state': state, 'label': 'probe', 'detail': 'probe', 'fix': ''}]
    groups = {'Edit and check video': row('ready'), 'Local transcription': row('limited'),
              'Film kit (optional)': row('ready'), 'Skill': row('ready')}
    out = io.StringIO()
    with mock.patch.object(setup, 'inspect', return_value=groups), \
            mock.patch.object(setup, 'selected_python', return_value=Path(sys.executable)), \
            mock.patch.object(sys, 'argv', ['setup.py']), mock.patch('sys.stdout', out):
        setup.main()
    text = out.getvalue()
    record('setup: a limited optional group is named with the job it matters for; ready ones are not',
           'Fix only what your job needs. Local transcription matters only for transcripts made on this machine'
           in text and 'Film kit (optional) matters' not in text, text[:600])


def check_old_node(record, setup):
    """A Node older than the kit's minimum is missing, not ready, even when `node --version` answers."""
    real_run = setup.run

    def run(command, *args, **kwargs):
        if command and str(command[0]).lower().replace('\\', '/').split('/')[-1].startswith('node') \
                and '--version' in command:
            return 'v16.20.2\n'
        return real_run(command, *args, **kwargs)
    with mock.patch.object(setup, 'kit_doctor', return_value={}), mock.patch.object(setup, 'run', side_effect=run), \
            mock.patch.object(setup.shutil, 'which', side_effect=lambda name: '/usr/bin/node' if name == 'node'
                              else None):
        rows = setup.inspect().get('Film kit (optional)', [])
    node = next((row for row in rows if row['label'] == 'Node'), {})
    record('setup: a Node older than 18 is reported missing, with its version', node.get('state') == 'missing'
           and 'v16.20.2' in node.get('detail', '') and '18' in node.get('detail', ''), str(node))


def check_missing_detector(record, setup):
    """An importable transcription engine remains usable without the optional VAD model."""
    versions = {'ffmpeg': 'ffmpeg version 9.0', 'ffprobe': 'ffprobe version 9.0'}
    encoders = {'libx264': True, 'aac': True}
    filters = {'ass': True, 'zscale': True, 'whisper': False}
    with mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), \
            mock.patch.object(setup, 'module_available', side_effect=lambda name: name != 'onnxruntime'), \
            mock.patch.object(setup, 'cached_models', return_value=['small']), \
            mock.patch.object(setup, 'kit_doctor', return_value={}):
        row = next(row for row in setup.inspect()['Local transcription'] if row['label'] == 'faster-whisper')
    text = row['detail'].lower()
    record('setup: missing VAD is limited while transcription remains usable', row['state'] == 'limited'
           and 'transcription' in text and 'energy' in text and 'onnxruntime' in text, str(row))


def check_spatial(record, setup, j, scripts_dir):
    """The optional group has precise fixes, consent, a shared OpenCV and a pinned download."""
    cache = Path(j('spatial-setup-cache'))
    versions = {'ffmpeg': 'ffmpeg version 9.0', 'ffprobe': 'ffprobe version 9.0'}
    encoders = {'libx264': True, 'aac': True}
    filters = {'ass': True, 'zscale': True, 'whisper': False}
    with mock.patch.object(setup, 'data_home', return_value=cache), \
            mock.patch.object(setup, 'module_available', side_effect=lambda name: name not in ('cv2', 'onnxruntime')), \
            mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), \
            mock.patch.object(setup, 'kit_doctor', return_value={}):
        rows = {row['label']: row for row in setup.inspect()['Spatial (optional)']}
    record('setup: spatial reports missing optional packages and model with the right fixes',
           all(rows[name]['state'] == 'missing' and '--install spatial' in rows[name]['fix'] for name in rows)
           and '--download' in rows['MODNet model']['fix'] and rows['MODNet model']['required'], str(rows))
    with mock.patch.object(setup, 'data_home', return_value=cache), \
            mock.patch.object(setup, 'module_available', return_value=True), \
            mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), \
            mock.patch.object(setup, 'kit_doctor', return_value={}):
        states = setup.summary(setup.inspect())
    ready = {name: 'ready' for name in setup.REQUIRED}
    record('setup: absent subject weights make spatial limited without limiting core editing',
           states['Spatial (optional)'] == 'limited'
           and setup.exit_code({**ready, 'Spatial (optional)': 'limited'}) == 0
           and setup.exit_code({**ready, 'Spatial (optional)': 'limited'}, 'spatial') == 1, str(states))
    with mock.patch.object(setup.subprocess, 'run') as pip:
        setup.install_spatial(True, 'example-python')
    args = pip.call_args.args[0]
    record('setup: spatial shares the faces OpenCV package and installs ONNX Runtime',
           'opencv-python' in args and 'onnxruntime' in args and 'opencv-python-headless' not in args,
           str(args))
    script = Path(scripts_dir) / 'setup.py'
    denied = subprocess.run([sys.executable, '-I', str(script), '--install', 'spatial', '--json'],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    orphan = subprocess.run([sys.executable, '-I', str(script), '--download', '--yes', '--json'],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    record('setup: spatial install requires consent and download requires the spatial group',
           denied.returncode == 2 and 'Not installed' in denied.stdout and orphan.returncode == 2
           and '--install spatial' in orphan.stdout, denied.stdout + orphan.stdout)
    payload = b'synthetic pinned weights'
    digest = hashlib.sha256(payload).hexdigest()

    def fake_download(url, name):
        Path(name).write_bytes(payload)

    with mock.patch.object(setup, 'data_home', return_value=cache), \
            mock.patch.object(setup, 'SPATIAL_SHA256', digest), \
            mock.patch.object(setup.urllib.request, 'urlretrieve', side_effect=fake_download) as request:
        setup.download_spatial(True)
        setup.download_spatial(True)
    model = cache / 'models' / setup.SPATIAL_MODEL
    record('setup: model download is cached per user, hash checked and not repeated',
           model.read_bytes() == payload and request.call_count == 1, str(model))
    bad_cache = Path(j('spatial-bad-cache'))
    with mock.patch.object(setup, 'data_home', return_value=bad_cache), \
            mock.patch.object(setup.urllib.request, 'urlretrieve', side_effect=fake_download):
        try:
            setup.download_spatial(True)
            rejected = False
        except ValueError:
            rejected = True
    record('setup: a model with the wrong digest is rejected and not cached', rejected
           and not (bad_cache / 'models' / setup.SPATIAL_MODEL).exists())
    trans_fix = setup.project.dependency_message('onnxruntime')
    spatial_fix = setup.project.dependency_message('onnxruntime', context='spatial')
    record('setup: ONNX Runtime suggests the matching install for each context',
           '--install transcription' in trans_fix and '--install spatial' in spatial_fix)
    message = setup.project.dependency_message('cv2') + setup.project.dependency_message('modnet.onnx')
    record('setup: missing OpenCV and model errors name the spatial install and download',
           message.count('--install spatial') == 2 and '--download' in message, message)


def constraint_lines(path):
    """[(name, version, marker)] from a constraints file; a line that is not an exact pin gives version None."""
    rows = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement, _, marker = line.partition(';')
        found = re.fullmatch(r'([A-Za-z0-9._-]+)==([A-Za-z0-9.+!-]+)', requirement.strip())
        rows.append((found.group(1).lower().replace('_', '-'), found.group(2), marker.strip()) if found
                    else (line, None, ''))
    return rows


def marker_holds(marker, python, system):
    """Whether a constraint's marker holds: python_version comparisons and sys_platform tests joined with `and`."""
    for clause in filter(None, (part.strip() for part in marker.split(' and '))):
        found = re.fullmatch(r'(python_version|sys_platform) (<|>=|==|!=) "([^"]+)"', clause)
        if not found:
            raise ValueError('a marker this check cannot read: ' + clause)
        if found.group(1) == 'sys_platform':
            same = system == found.group(3)
            if same != (found.group(2) == '=='):
                return False
            continue
        wanted = tuple(int(part) for part in found.group(3).split('.'))
        if not {'<': python < wanted, '>=': python >= wanted, '==': python == wanted,
                '!=': python != wanted}[found.group(2)]:
            return False
    return True


def check_constraints(record, setup, scripts_dir):
    """One file names one exact version of each package for each supported Python and system."""
    path = Path(scripts_dir) / 'constraints.txt'
    record('setup: the tested versions are one constraints file beside setup.py', path.is_file(), str(path))
    rows = constraint_lines(path) if path.is_file() else []
    loose = [name for name, version, _ in rows if version is None]
    record('setup: every constraint is an exact version', bool(rows) and not loose, ', '.join(loose))
    direct = ('numpy', 'pillow', 'opencv-python', 'opencv-python-headless', 'onnxruntime', 'faster-whisper', 'av',
              'ctranslate2', 'tokenizers', 'huggingface-hub', 'torch', 'transformers', 'safetensors', 'librosa',
              'soundfile', 'soxr')
    gaps = []
    try:
        for python in ((3, 9), (3, 10), (3, 11), (3, 12), (3, 13), (3, 14)):
            for system in ('win32', 'linux', 'darwin'):
                chosen = {}
                for name, version, marker in rows:
                    if version and marker_holds(marker, python, system):
                        chosen.setdefault(name, []).append(version)
                gaps += [f'{name} on {python} {system}: {chosen.get(name)}' for name in direct
                         if len(chosen.get(name, [])) != 1]
                gaps += [f'{name} on {python} {system}: {found}' for name, found in chosen.items() if len(found) > 1]
    except ValueError as error:
        gaps.append(str(error))
    record('setup: each package has exactly one version for each Python from 3.9 and each system',
           bool(rows) and not gaps, '; '.join(gaps)[:600])
    versions = {name: [version for other, version, _ in rows if other == name and version]
                for name in ('opencv-python', 'opencv-python-headless', 'av', 'faster-whisper')}
    major = lambda text: int(text.split('.')[0])  # noqa: E731
    record('setup: OpenCV stays below 5 and PyAV below 16, where faster-whisper 1.2.1 fails',
           bool(versions['opencv-python']) and versions['opencv-python'] == versions['opencv-python-headless']
           and all(major(v) == 4 for v in versions['opencv-python'])
           and bool(versions['av']) and all(major(v) < 16 for v in versions['av']), str(versions))
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, b'', b'')
    with mock.patch.object(setup.subprocess, 'run', side_effect=run), \
            mock.patch.object(sys, 'stderr', new=io.StringIO()):
        setup.install_core('example-python')
        setup.install_faces(True, 'example-python')
        setup.install_spatial(True, 'example-python')
        setup.install_transcription(True, 'example-python')
        setup.install_ear(True, 'example-python')
    pip = [command for command in calls if 'pip' in command]
    named = str(path)
    bare = [command for command in pip if '-c' not in command or command[command.index('-c') + 1] != named
            or ':all:' not in command]
    record('setup: every pip install in setup.py goes through the constraints file, wheels only',
           len(pip) >= 5 and not bare, str(bare or pip)[:900])
    named_parts = [part for command in pip for part in command[command.index('install') + 1:]
                   if not part.startswith(('-', 'http', ':')) and part != named]
    missing = sorted({part for part in named_parts if part.lower() not in {name for name, _, _ in rows}})
    record('setup: every package setup.py names has a pin, with no version beside it', bool(pip) and not missing,
           str(missing))
    with mock.patch.object(setup.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'pip')), \
            mock.patch.object(sys, 'stderr', new=io.StringIO()):
        try:
            setup.install_core('example-python')
            refused = ''
        except ValueError as error:
            refused = str(error)
    record('setup: a pinned version pip cannot install says so and names the file',
           'constraints.txt' in refused and 'numpy' in refused, refused)
    record('setup: a skill copy without the constraints file reports itself incomplete',
           'constraints.txt' in setup.SCRIPTS, str(setup.SCRIPTS[-3:]))


def check_hints(record, setup, scripts_dir):
    """Hints name setup.py, which installs through the constraints, instead of repeating a package or a version."""
    scripts = Path(scripts_dir)
    skill = scripts.parent
    files = [path for path in sorted(scripts.glob('*')) if path.suffix in ('.py', '.mjs', '.cjs')
             and path.name != 'setup.py']
    files += sorted((skill / 'references').glob('*.md')) + sorted((skill / 'paths').glob('*.md')) + [skill / 'SKILL.md']
    pattern = re.compile(r'\bpip3? install|[\'"]pip[\'"], [\'"]install|\bnpm (?:i|install) playwright'
                         r'|opencv-python(?:-headless|[<>=])')
    found = []
    for path in files:
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if pattern.search(line) and '.test(s)' not in line:   # a viewer's pattern for old reports, not a hint
                found.append(f'{path.name}:{number}')
    record('setup: no script or document repeats a pip package or version outside setup.py', not found,
           ', '.join(found)[:500])
    project = setup.project
    message = project.dependency_message('some_module')
    record('setup: a module setup.py does not install gets setup.py, not a loose pip command',
           'pip install' not in message and 'setup.py' in message, message)
    screen = (scripts / 'screen.py').read_text(encoding='utf-8')
    record('setup: the review page still turns an install hint into a plain sentence',
           bool(re.search(r"/[^/\n]*--install[^/\n]*/i\.test\(s\)\)return 'A check could not run", screen)), '')

    def load(name):
        spec = importlib.util.spec_from_file_location('lf_hints_' + name, scripts / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    card = load('grade')
    with mock.patch.dict(sys.modules, {'cv2': None}):
        faces = card.face_samples([])
    why = load('check').why_not_run('reframe.py', 1, "No module named 'cv2'")
    record('setup: a missing OpenCV names setup.py --install in the scorecard and in the check',
           '--install faces' in faces.get('reason', '') and '--install' in why and 'pip install' not in why,
           str(faces) + why)


def check_repository_pins(record, setup, scripts_dir):
    """In a clone: CI installs what users get, the newest-release workflow blocks nothing, CONTRIBUTING says how."""
    root = Path(scripts_dir).resolve().parents[2]
    workflow = root / '.github' / 'workflows' / 'ci.yml'
    if not workflow.is_file():
        print('skipped: the CI and CONTRIBUTING checks need a clone of the repository', flush=True)
        return
    ci = workflow.read_text(encoding='utf-8')
    constraint = 'pip install -c skills/legible-film/scripts/constraints.txt '
    loose = [line.strip() for line in ci.splitlines() if 'pip install' in line and constraint not in line
             and 'git+https://' not in line]
    record('setup: CI installs Python packages through the constraints file', not loose and constraint in ci,
           '; '.join(loose))
    record('setup: CI installs the playwright-core version setup.py pins',
           'PLAYWRIGHT_CORE' in ci and 'npm install "playwright-core@$' in ci and 'playwright@' not in ci, '')
    upstream = root / '.github' / 'workflows' / 'upstream.yml'
    text = upstream.read_text(encoding='utf-8') if upstream.is_file() else ''
    triggers = re.search(r'^on:\n((?:[ \t]+.*\n)+)', text, re.MULTILINE)
    events = re.findall(r'^  ([a-z_]+):', triggers.group(1), re.MULTILINE) if triggers else []
    used = re.findall(r'uses:\s*(\S+)', text)
    record('setup: the newest-release workflow runs weekly or by hand, reads only, and pins actions as CI does',
           sorted(events) == ['schedule', 'workflow_dispatch'] and re.search(r'^permissions:\n  contents: read$', text,
                                                                             re.MULTILINE) is not None
           and bool(used) and all(action in ci for action in used)
           and 'constraints.txt' not in text, str((events, used)))
    guide = (root / 'CONTRIBUTING.md').read_text(encoding='utf-8')
    record('setup: CONTRIBUTING gives the measured self-test time and how to move a pin',
           '16 to 32 minutes' in guide and '10 to 45' not in guide and 'constraints.txt' in guide
           and 'PLAYWRIGHT_CORE' in guide, '')


def run_setup_cases(tool, record, j, scripts_dir):
    """Check capability summaries, fixes, consent, updates and real FFmpeg features."""
    spec = importlib.util.spec_from_file_location('lf_setup_test', os.path.join(scripts_dir, 'setup.py'))
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    check_missing_detector(record, setup)
    check_spatial(record, setup, j, scripts_dir)
    check_kit_install(record, setup, j)
    check_old_node(record, setup)
    check_job_routing(record, setup)
    check_constraints(record, setup, scripts_dir)
    check_hints(record, setup, scripts_dir)
    check_repository_pins(record, setup, scripts_dir)
    expected = {'Windows': ('winget', 'Gyan.FFmpeg', 'OpenJS.NodeJS.LTS'),
                'Darwin': ('brew install', 'ffmpeg', 'node'),
                'Linux': ('apt install', 'ffmpeg', 'nodejs')}
    for system, parts in expected.items():
        commands = setup.command_fix('ffmpeg', system) + ' ' + setup.command_fix('node', system)
        record('setup: ' + system + ' commands', all(part in commands for part in parts), commands)
    with mock.patch.object(setup.shutil, 'which', return_value=None):
        versions, encoders, filters = setup.ffmpeg_features()
    record('setup: missing PATH executables are missing', not any(versions.values()) and not any(encoders.values())
           and not any(filters.values()), str((versions, encoders, filters)))
    sample = ' T.. scale V->V\n T.. zscale V->V\n'
    with mock.patch.object(setup.shutil, 'which', return_value='ffmpeg'), mock.patch.object(
            setup, 'run', side_effect=lambda args, timeout=2: sample if '-filters' in args else ''):
        _, _, filters = setup.ffmpeg_features()
    record('setup: missing whisper and libass filters are identified', filters == {
        'ass': False, 'zscale': True, 'whisper': False}, str(filters))
    failed = subprocess.CompletedProcess([], 1, b'', b'ModuleNotFoundError')
    setup._IMPORTS.pop('faster_whisper', None)
    with mock.patch.object(setup.subprocess, 'run', return_value=failed):
        record('setup: import errors are reported', not setup.module_available('faster_whisper'))
    setup._IMPORTS.pop('faster_whisper', None)
    # A package found only in the user's own site-packages imports here but not in the scripts' isolated runs.
    with mock.patch.object(setup.subprocess, 'run', return_value=failed), \
            mock.patch.object(setup.importlib, 'import_module', return_value=object()):
        hidden = setup.unseen('faster_whisper')
    setup._IMPORTS.pop('faster_whisper', None)
    record('setup: a package installed for this user only counts as missing, and says why',
           'installed for this user only' in hidden and 'python -I' in hidden, hidden)
    versions = {'ffmpeg': '', 'ffprobe': ''}
    encoders = {'libx264': False, 'aac': False}
    filters = {'ass': False, 'zscale': False, 'whisper': False}
    with mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), mock.patch.object(
            setup, 'module_available', side_effect=lambda name: name != 'faster_whisper'), mock.patch.object(
            setup, 'cached_models', return_value=[]), mock.patch.object(setup, 'kit_doctor', return_value={}):
        groups = setup.inspect()
    states = setup.summary(groups)
    gaps = {row['label']: row for rows in groups.values() for row in rows}
    record('setup: missing tools change capability summaries', states['Edit and check video'] != 'ready'
           and states['Local transcription'] != 'ready' and states['Film kit (optional)'] != 'ready', str(states))
    record('setup: named gaps explain limits and fixes', all(gaps[name]['fix'] for name in
           ('ffmpeg', 'libass', 'FFmpeg whisper', 'faster-whisper')), str(gaps))
    result = subprocess.run([sys.executable, '-I', str(Path(scripts_dir) / 'setup.py'), '--install',
                             'transcription', '--json'], stdin=subprocess.DEVNULL, capture_output=True, text=True)
    with mock.patch.object(setup, 'dedicated_python', return_value=Path(scripts_dir) / 'no-such-env' / 'python'):
        present = setup.core_present()
    with mock.patch.object(setup, 'dedicated_python', return_value=Path(setup.__file__)):
        dedicated = setup.core_present()
    record('setup: --install core has nothing to do when numpy and Pillow already import (no new environment), '
           'and defers to an existing per-user environment', present is True and dedicated is False,
           str((present, dedicated)))
    record('setup: noninteractive installation without consent refuses', result.returncode == 2
           and json.loads(result.stdout)['exit_code'] == 2 and 'Not installed' in result.stdout, result.stdout)
    releases = [setup.ffmpeg_release(line) for line in (
        'ffmpeg version 9.0.2-full_build-www.gyan.dev', 'ffmpeg version 4.4.2-0ubuntu0.22.04.1',
        'ffmpeg version n6.1.1', 'ffmpeg version N-118000-gabcdef', '')]
    with mock.patch.object(setup, 'ffmpeg_features', return_value=(
            {'ffmpeg': 'ffmpeg version 4.4.2-0ubuntu0.22.04.1', 'ffprobe': 'ffprobe version 4.4.2-0ubuntu0.22.04.1'},
            {'libx264': True, 'aac': True}, {'ass': True, 'zscale': True, 'whisper': False})):
        old_rows = {row['label']: row for row in setup.inspect()['Edit and check video']}
    record('setup: FFmpeg older than 5.1 is limited, with the version and a fix; development builds are accepted',
           releases == [(9, 0), (4, 4), (6, 1), None, None] and old_rows['ffmpeg']['state'] == 'limited'
           and '5.1' in old_rows['ffmpeg']['fix']
           and all('5.1' in setup.old_ffmpeg_fix(system) for system in ('Linux', 'Darwin', 'Windows', 'FreeBSD')),
           str((releases, old_rows.get('ffmpeg'))))
    ready = {name: 'ready' for name in setup.REQUIRED}
    record('setup: exit code judges required capabilities and the one installed',
           setup.exit_code({**ready, 'Film kit (optional)': 'missing'}) == 0
           and setup.exit_code({**ready, 'Local transcription': 'limited'}, 'transcription') == 1
           and setup.exit_code({**ready, 'Local transcription': 'ready'}, 'transcription') == 0
           and setup.exit_code({'Edit and check video': 'limited', 'Skill': 'ready'}) == 1, str(ready))
    with mock.patch.object(setup, 'module_available', return_value=True), mock.patch.object(
            setup, 'cached_models', return_value=['small']), mock.patch.object(
            setup, 'ffmpeg_features', return_value=({'ffmpeg': '9', 'ffprobe': '9'}, {'libx264': True, 'aac': True},
                                                    {'ass': True, 'zscale': True, 'whisper': False})):
        rows = {row['label']: row for row in setup.inspect()['Local transcription']}
    record('setup: a missing fallback does not limit ready transcription', rows['FFmpeg whisper']['state'] == 'ready',
           str(rows.get('FFmpeg whisper')))
    payload = json.dumps({'tag_name': 'v9.0.0'}).encode()
    response = io.BytesIO(payload)
    with mock.patch.object(setup.urllib.request, 'urlopen', return_value=response) as request:
        newer, tag = setup.latest_release('1.2.5')
    record('setup: update check uses one mocked request', newer and tag == 'v9.0.0'
           and request.call_count == 1, str((newer, tag)))
    with mock.patch.object(setup.urllib.request, 'urlopen', side_effect=AssertionError('network')):
        setup.inspect(False)
    record('setup: default inspection makes no update request', True)
    code, output = tool('setup.py', '--json')
    try:
        data = json.loads(output)
        ok = code in (0, 1) and code == data['exit_code'] and len(data['summary']) == 7
    except (ValueError, KeyError):
        ok = False
        data = {}
    record('setup: real machine returns valid capability JSON', ok, output[-500:])
    actual_versions, actual_encoders, actual_filters = setup.ffmpeg_features()
    rows = {row['label']: row for row in data.get('capabilities', {}).get('Edit and check video', [])}
    trans = {row['label']: row for row in data.get('capabilities', {}).get('Local transcription', [])}
    comparisons = [(rows.get(name, {}).get('state') == 'ready') == value for name, value in actual_encoders.items()]
    comparisons += [(rows.get(label, {}).get('state') == 'ready') == actual_filters[name]
                    for name, label in (('ass', 'libass'), ('zscale', 'zscale'))]
    fallback = trans.get('FFmpeg whisper', {})
    if actual_filters['whisper']:
        # The filter alone transcribes nothing: it needs a GGML model file, so it is ready only as a fallback.
        expected = 'ready' if trans.get('faster-whisper', {}).get('state') == 'ready' else 'limited'
        comparisons.append(fallback.get('state') == expected and 'GGML model file' in fallback.get('detail', ''))
    elif trans.get('faster-whisper', {}).get('state') == 'ready':
        comparisons.append(fallback.get('state') == 'ready' and 'filter missing' in fallback.get('detail', '')
                           and 'not needed' in fallback.get('detail', ''))
    else:
        comparisons.append(fallback.get('state') == 'limited' and 'filter missing' in fallback.get('detail', ''))
    record('setup: real output agrees with local FFmpeg probes', all(comparisons),
           str((actual_versions, actual_encoders, actual_filters)))
