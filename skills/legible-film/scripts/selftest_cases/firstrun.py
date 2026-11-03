"""Known-answer checks for first-run setup and download consent."""
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock


def load(path, name):
    """Load one sibling script without relying on the current directory."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_firstrun_cases(tool, record, j, scripts_dir):
    """Check a clean interpreter, optional features and model-download consent."""
    scripts = Path(scripts_dir)
    setup = load(scripts / 'setup.py', 'firstrun_setup')
    project = load(scripts / 'project.py', 'firstrun_project')
    fresh = Path(j('fresh-no-pip'))
    subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(fresh)], check=True,
                   capture_output=True)
    fresh_py = fresh / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    for name, args in (('map.py', ['--help']), ('captions.py', ['--help']), ('selftest.py', ['--quick']),
                       ('flash_scan.py', ['--help']), ('blank_scan.py', ['--help'])):
        result = subprocess.run([str(fresh_py), '-I', str(scripts / name), *args], capture_output=True, text=True)
        text = result.stdout + result.stderr
        record('firstrun: ' + name + ' explains missing numpy without a traceback',
               result.returncode == 2 and 'numpy' in text
               and str(fresh_py).replace('\\', '/') in text.replace('\\', '/')
               and '--install core' in text and 'Traceback' not in text, text[-700:])
    crashed = []
    for script in sorted(scripts.glob('*.py')):
        result = subprocess.run([str(fresh_py), '-I', str(script), '--help'], capture_output=True)
        try:
            text = (result.stdout + result.stderr).decode('utf-8')
        except UnicodeDecodeError as error:
            crashed.append(f'{script.name}: piped help is not UTF-8 ({error.reason} at byte {error.start})')
            continue
        if 'Traceback' in text or result.returncode not in (0, 2) or (
                result.returncode == 2 and '--install core' not in text):
            crashed.append(f'{script.name} exit {result.returncode}: {text.strip().splitlines()[-1:]}')
    record('firstrun: every script answers --help without numpy or Pillow, or names the setup command; none crashes',
           not crashed, '; '.join(crashed)[:900])
    blocker = ("import importlib.abc, runpy, sys\n"
               "class Block(importlib.abc.MetaPathFinder):\n"
               " def find_spec(self, name, path=None, target=None):\n"
               "  if name == 'PIL' or name.startswith('PIL.'): raise ModuleNotFoundError(name, name=name)\n"
               "sys.meta_path.insert(0, Block())\n"
               "sys.argv = [sys.argv[1], '--help']\n"
               "runpy.run_path(sys.argv[0], run_name='__main__')\n")
    for name in ('map.py', 'captions.py', 'frame_sheet.py'):
        result = subprocess.run([sys.executable, '-I', '-c', blocker, str(scripts / name)], capture_output=True,
                                text=True)
        text = result.stdout + result.stderr
        record('firstrun: ' + name + ' explains missing Pillow without a traceback',
               result.returncode == 2 and 'Pillow' in text and '--install core' in text
               and 'Traceback' not in text, text[-700:])
    env = dict(os.environ)
    env['PATH'] = str(Path(j('empty-search-path')))
    result = subprocess.run([sys.executable, '-I', str(scripts / 'selftest.py'), '--smoke'], env=env,
                            capture_output=True, text=True)
    output = result.stdout + result.stderr
    record('firstrun: smoke names the missing FFmpeg and its fix', result.returncode == 2
           and 'ffmpeg is missing' in output and 'Fix:' in output, output[-700:])
    result = subprocess.run([str(fresh_py), '-I', str(scripts / 'setup.py'), '--install', 'core', '--json'],
                            stdin=subprocess.DEVNULL, capture_output=True, text=True)
    try:
        refused = result.returncode == 2 and 'Not installed' in json.loads(result.stdout).get('error', '')
    except ValueError:
        refused = False
    record('firstrun: core installation asks for consent', refused, result.stdout + result.stderr)
    isolated = dict(os.environ)
    isolated['LOCALAPPDATA'] = str(Path(j('unconfigured-user')))
    isolated['XDG_DATA_HOME'] = str(Path(j('unconfigured-user')))
    result = subprocess.run([str(fresh_py), '-I', str(scripts / 'setup.py')], env=isolated,
                            capture_output=True, text=True)
    output = result.stdout + result.stderr
    expected = project.python_command([scripts / 'setup.py', '--install', 'core'], fresh_py).count('--install core')
    record('firstrun: setup prints one core repair per missing package',
           result.returncode == 1 and output.count('--install core') == 2 * expected, output[-1000:])
    fake_stdlib = Path(j('fake-stdlib'))
    fake_stdlib.mkdir(exist_ok=True)
    (fake_stdlib / 'EXTERNALLY-MANAGED').write_text('[externally-managed]\n', encoding='utf-8')
    detector = getattr(setup, 'externally_managed', None)
    detected = bool(detector and detector(fake_stdlib, 'system', 'system')
                    and not detector(fake_stdlib, 'venv', 'system'))
    record('firstrun: external management applies to the base Python, not a venv', detected)
    for label, managed, pip in (('externally managed', True, True), ('without pip', False, False)):
        target = Path(j('mock-' + label.replace(' ', '-'))) / ('Scripts/python.exe' if os.name == 'nt'
                                                                 else 'bin/python')
        calls = []

        def make_environment(command, **kwargs):
            calls.append(command)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
            return subprocess.CompletedProcess(command, 0)

        def pip_probe(exe):
            return pip if str(exe) == sys.executable else True
        with mock.patch.object(setup, 'dedicated_python', return_value=target), \
                mock.patch.object(setup, 'externally_managed', return_value=managed), \
                mock.patch.object(setup, 'has_pip', side_effect=pip_probe), \
                mock.patch.object(setup.subprocess, 'run', side_effect=make_environment):
            chosen = setup.selected_python(create=True)
        record('firstrun: ' + label + ' selects a dedicated environment',
               chosen == target and len(calls) == 1 and 'venv' in calls[0], str(calls))
    missing_venv = Path(j('mock-no-venv')) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    with mock.patch.object(setup, 'dedicated_python', return_value=missing_venv), \
            mock.patch.object(setup, 'externally_managed', return_value=True), \
            mock.patch.object(setup.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'venv')):
        try:
            setup.selected_python(create=True)
            missing_fix = ''
        except ValueError as error:
            missing_fix = str(error)
    record('firstrun: missing venv or ensurepip names python3-venv', 'python3-venv' in missing_fix, missing_fix)
    target = Path(j('selected-python'))
    with mock.patch.object(setup.subprocess, 'run') as installed, mock.patch.object(sys, 'stderr', new=io.StringIO()):
        setup.install_faces(True, target)
        face_cmd = installed.call_args.args[0]
        setup.install_transcription(True, target)
        commands_used = [call.args[0] for call in installed.call_args_list[1:]]
    record('firstrun: optional installations use the selected interpreter',
           face_cmd[0] == str(target) and len(commands_used) == 2
           and all(command[0] == str(target) for command in commands_used), str((face_cmd, commands_used)))
    versions = {'ffmpeg': 'ffmpeg version 9.0', 'ffprobe': 'ffprobe version 9.0'}
    encoders = {'libx264': True, 'aac': True}
    filters = {'ass': False, 'zscale': False, 'whisper': False}
    with mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), \
            mock.patch.object(setup, 'module_available', return_value=True), \
            mock.patch.object(setup, 'cached_models', return_value=['small']), \
            mock.patch.object(setup, 'kit_doctor', return_value={}):
        groups = setup.inspect()
    states = setup.summary(groups)
    record('firstrun: optional libass and zscale do not block basic editing',
           setup.exit_code(states) == 0, str(states))
    with mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), \
            mock.patch.object(setup, 'module_available', return_value=False), \
            mock.patch.object(setup, 'kit_doctor', return_value={}), \
            mock.patch.object(setup.shutil, 'which', side_effect=lambda name: 'node' if name == 'node' else None), \
            mock.patch.object(setup, 'run', return_value='v20.0.0'):
        groups = setup.inspect()
    kit = {row['label']: row for row in groups['Film kit (optional)']}
    record('firstrun: Node is probed even when the Python kit doctor cannot run',
           kit['Node']['state'] == 'ready' and 'v20' in kit['Node']['detail'], str(kit['Node']))
    # The fix installs Playwright into the per-user data folder wherever the person runs it from: the home folder
    # (where the data folder lies below the working folder) as well as a project or a CI checkout.
    def playwright_prefix(fix):
        found = re.search(r'--prefix "?([^"\s]+)', fix.replace('\\', '/'))
        return os.path.normcase(os.path.normpath(found.group(1))) if found else None

    wanted = os.path.normcase(os.path.normpath(str(setup.data_home() / 'playwright')))
    record('firstrun: Playwright fix uses the per-user data directory',
           playwright_prefix(kit['Playwright']['fix']) == wanted and '--install kit' in kit['Playwright']['fix'],
           kit['Playwright']['fix'])
    here = os.getcwd()
    try:
        os.chdir(Path.home())
        with mock.patch.object(setup, 'ffmpeg_features', return_value=(versions, encoders, filters)), \
                mock.patch.object(setup, 'module_available', return_value=False), \
                mock.patch.object(setup, 'kit_doctor', return_value={}), \
                mock.patch.object(setup.shutil, 'which', side_effect=lambda name: 'node' if name == 'node' else None), \
                mock.patch.object(setup, 'run', return_value='v20.0.0'):
            from_home ={row['label']: row for row in setup.inspect()['Film kit (optional)']}
    finally:
        os.chdir(here)
    record('firstrun: Playwright fix uses the per-user data directory when run from the home folder',
           playwright_prefix(from_home['Playwright']['fix']) == wanted, from_home['Playwright']['fix'])
    with mock.patch.object(setup, 'data_home', return_value=Path(j('cash $space'))), \
            mock.patch.object(setup, 'kit_doctor', return_value={}):
        kit = {row['label']: row for row in setup.inspect()['Film kit (optional)']}
    playwright = kit['Playwright']['fix']
    quoted = ('Git Bash:' in playwright and '`$space' in playwright) if os.name == 'nt' else "'" in playwright
    record('firstrun: Playwright fix preserves a dollar sign in the user-data path', quoted, playwright)
    linux_fix = setup.old_ffmpeg_fix('Linux')
    record('firstrun: old Ubuntu FFmpeg gets a usable upgrade direction',
           '22.04' in linux_fix and '4.4' in linux_fix and '5.1' in linux_fix
           and 'apt install ffmpeg' not in linux_fix, linux_fix)
    command = getattr(project, 'python_command', None)
    commands = command(['C:/skill folder/setup.py', '--install', 'core'],
                       python='C:/Python space/python.exe', system='Windows') if command else ''
    record('firstrun: spaces get separate PowerShell and cmd/Git Bash commands',
           'PowerShell:' in commands and 'cmd' in commands and '& "C:/Python space/python.exe"' in commands,
           commands)
    special = command(['--prompt', r'Keep\this'], python='C:/Python $USER/python.exe', system='Windows')
    record('firstrun: shell-special paths and literal prompt backslashes are preserved',
           'Git Bash:' in special and 'cmd:' in special and '`$USER' in special
           and "'C:/Python $USER/python.exe'" in special and r'Keep\this' in special, special)
    transcribe = load(scripts / 'transcribe.py', 'firstrun_transcribe')
    calls = []
    download_command = getattr(transcribe, 'download_command', None)
    command = download_command([r'C:\plain\source.mp4', '--out', r'C:\plain\words.json', '--prompt',
                                r'Keep\this'], python='C:/Python/python.exe', system='Windows') \
        if download_command else ''
    record('firstrun: transcription retry normalizes paths and preserves literal prompt text',
           'C:/plain/source.mp4' in command and 'C:/plain/words.json' in command
           and '"C:/plain/source.mp4"' not in command and r'Keep\this' in command, command)

    with mock.patch.dict(sys.modules, {'faster_whisper': None}):
        try:
            transcribe.faster(types.SimpleNamespace())
        except ValueError as exc:
            missing_engine = str(exc)
    record('firstrun: missing faster-whisper names its Python and install command',
           'faster-whisper' in missing_engine and sys.executable in missing_engine
           and '--install transcription' in missing_engine, missing_engine)

    class LocalEntryNotFoundError(Exception):
        """Stand in for the cache library's missing-entry error."""

    def model(*args, **kwargs):
        calls.append(kwargs['local_files_only'])
        if kwargs['local_files_only']:
            raise LocalEntryNotFoundError('not cached')
        raise RuntimeError('unexpected download')

    args = types.SimpleNamespace(model='small', model_dir=None, no_download=False, download=False)
    with mock.patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=model)}):
        try:
            transcribe.faster(args)
        except Exception as exc:
            error = str(exc)
    record('firstrun: missing weights do not download without permission', calls == [True]
           and '--download' in error and '460' in error, str((calls, error)))
    calls.clear()
    args.no_download = True
    args.download = True
    with mock.patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=model)}):
        try:
            transcribe.faster(args)
        except LocalEntryNotFoundError:
            pass
    record('firstrun: explicit no-download always prevents a remote lookup', calls == [True], str(calls))
    mapper = load(scripts / 'map.py', 'firstrun_map')
    with mock.patch.object(sys, 'argv', ['map.py', 'run', str(Path(j('unused-project'))), '--download']), \
            mock.patch.object(mapper, 'run') as mapped:
        code = mapper.main()
    record('firstrun: map forwards explicit download permission', code == 0 and mapped.call_args.args[-1] is True,
           str(mapped.call_args))
    for script, option in (('map.py', '--download'), ('transcribe.py', '--download'), ('selftest.py', '--smoke')):
        code, output = tool(script, 'run', '--help') if script == 'map.py' else tool(script, '--help')
        record('firstrun: ' + script + ' exposes ' + option, code == 0 and option in output, output[-500:])
