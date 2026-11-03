"""Known-answer cases for the optional listening and delivery tools."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np


def module(scripts_dir, name):
    spec = importlib.util.spec_from_file_location('u5b_' + name, Path(scripts_dir) / (name + '.py'))
    found = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(found)
    return found


def run_u5b_cases(tool, record, j, scripts_dir, skip):
    rate = 48000
    sound = Path(j('u5b-tone.wav'))
    signal = (0.2 * np.sin(2 * np.pi * 440 * np.arange(3 * rate) / rate) * 32767).astype('<i2')
    with wave.open(str(sound), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(signal.tobytes())

    png = Path(j('u5b-sheet.png'))
    code, output = tool('listen.py', 'sheet', sound, '--out', png)
    try:
        from PIL import Image
        with Image.open(png) as image:
            size, valid = image.size, image.format == 'PNG'
    except (OSError, ImportError):
        size, valid = (), False
    record('listen sheet: a short soundtrack produces one readable PNG',
           code == 0 and valid and size[0] >= 1000 and size[1] >= 400, output[-500:])
    before = sound.read_bytes()
    code, output = tool('listen.py', 'sheet', sound, '--out', sound)
    record('listen sheet: an output alias is refused before the input is changed',
           code == 2 and 'input' in output.lower() and sound.read_bytes() == before, output[-300:])
    version = Path(j('u5b-project', 'cuts', 'v001'))
    version.mkdir(parents=True)
    (version / 'manifest.json').write_text('{}', encoding='utf-8')
    code, output = tool('listen.py', 'sheet', sound, '--out', version / 'sheet.png')
    record('listen sheet: immutable version folders are refused',
           code == 2 and not (version / 'sheet.png').exists() and 'immutable' in output, output[-300:])

    listen = module(scripts_dir, 'listen')
    if not hasattr(listen, 'require_model_memory'):
        record('listen labels: below 3 GiB is refused before model loading', False, 'memory gate missing')
    else:
        rejected = []
        for free in (None, int(2.99 * 1024 ** 3)):
            try:
                listen.require_model_memory(lambda: free)
                rejected.append(False)
            except ValueError:
                rejected.append(True)
        record('listen labels: below 3 GiB is refused before model loading',
               all(rejected) and listen.require_model_memory(lambda: 3 * 1024 ** 3) is None, str(rejected))
        called = []
        original_sibling, original_find, original_clap, original_ast = (
            listen.sibling, listen.importlib.util.find_spec, listen.clap_hints, listen.ast_hints)
        fake_setup = SimpleNamespace(ear_models_cached=lambda: ['clap', 'ast'], EAR_MODELS=('clap', 'ast'),
                                     free_memory=lambda: 2 * 1024 ** 3, ear_cache=lambda: Path(j('cache')))
        try:
            listen.sibling = lambda name: fake_setup if name == 'setup' else original_sibling(name)
            listen.importlib.util.find_spec = lambda name: object()
            listen.clap_hints = listen.ast_hints = lambda *args: called.append('loaded')
            try:
                listen.labels(sound)
                denied = False
            except ValueError as error:
                denied = '3 GiB' in str(error)
        finally:
            listen.sibling, listen.importlib.util.find_spec = original_sibling, original_find
            listen.clap_hints, listen.ast_hints = original_clap, original_ast
        record('listen labels: the low-memory gate runs before either model', denied and not called, str(called))

        events = Path(j('u5b-events.json'))
        events.write_text(json.dumps({'file': str(sound), 'events': [{'t': .4, 'kind': 'onset'}]}), encoding='utf-8')
        fake_setup.free_memory = lambda: 4 * 1024 ** 3
        fake_lock = SimpleNamespace(HeavyLock=lambda **kwargs: contextlib.nullcontext(), LockTimeout=TimeoutError)
        old_decode = listen.decode_audio
        try:
            listen.sibling = lambda name: fake_setup if name == 'setup' else fake_lock if name == 'with_lock' \
                else original_sibling(name)
            listen.importlib.util.find_spec = lambda name: object()
            listen.clap_hints = lambda samples, rows, cache: [[{'label': 'clap hint', 'cosine': .2}]]
            listen.ast_hints = lambda samples, rows, cache: [[{'label': 'ast hint', 'score': .3}]]
            listen.decode_audio = lambda path, rate=48000, channels=2, **kwargs: np.ones((rate, 2), np.float32)
            hints = listen.labels(sound, events)
        finally:
            listen.sibling, listen.importlib.util.find_spec = original_sibling, original_find
            listen.clap_hints, listen.ast_hints, listen.decode_audio = original_clap, original_ast, old_decode
        record('listen labels: both local model results are described as hints',
               hints['events'][0]['clap_hints'][0]['label'] == 'clap hint'
               and hints['events'][0]['ast_hints'][0]['label'] == 'ast hint'
               and 'hint' in hints['limit'] and 'not bound' in hints['events_binding'], str(hints))

        # Tiny fake model APIs test offline-only loading and the shape of returned hints.
        class Tensor:
            def __init__(self, values): self.values = np.asarray(values)
            def float(self): return self
            @property
            def T(self): return Tensor(self.values.T)
            def __matmul__(self, other): return Tensor(self.values @ other.values)
            def __getitem__(self, key): return Tensor(self.values[key])
            def __float__(self): return float(self.values)
            def tolist(self): return self.values.tolist()
        fake_torch, fake_transformers, loaded = ModuleType('torch'), ModuleType('transformers'), []
        fake_torch.set_num_threads = lambda n: None
        fake_torch.inference_mode = contextlib.nullcontext
        fake_torch.nn = SimpleNamespace(functional=SimpleNamespace(
            normalize=lambda t, dim: Tensor(t.values / np.maximum(np.linalg.norm(t.values, axis=dim, keepdims=True), 1e-9))))
        fake_torch.argsort = lambda t, descending=False: Tensor(np.argsort(-t.values if descending else t.values))
        fake_torch.sigmoid = lambda t: Tensor(1 / (1 + np.exp(-t.values)))
        class Factory:
            def __init__(self, kind): self.kind = kind
            def from_pretrained(self, name, **kwargs):
                loaded.append((self.kind, name, kwargs))
                if self.kind == 'clap_model':
                    return SimpleNamespace(eval=lambda: SimpleNamespace(
                        get_text_features=lambda **kw: Tensor(np.eye(len(listen.LABEL_PROMPTS))),
                        get_audio_features=lambda **kw: Tensor(np.eye(len(listen.LABEL_PROMPTS))[:1])))
                if self.kind == 'ast_model':
                    class AstModel:
                        config = SimpleNamespace(id2label={0: 'speech', 1: 'music', 2: 'click'})
                        def eval(self): return self
                        def __call__(self, **kwargs): return SimpleNamespace(logits=Tensor([[1., 0., -1.]]))
                    return AstModel()
                return lambda *args, **kwargs: {'input': 1}
        for name, kind in (('ClapModel', 'clap_model'), ('ClapProcessor', 'clap_processor'),
                           ('ASTForAudioClassification', 'ast_model'), ('ASTFeatureExtractor', 'ast_processor')):
            setattr(fake_transformers, name, Factory(kind))
        saved_modules = {name: sys.modules.get(name) for name in ('torch', 'transformers')}
        try:
            sys.modules['torch'], sys.modules['transformers'] = fake_torch, fake_transformers
            listen.sibling = lambda name: fake_setup if name == 'setup' else original_sibling(name)
            clap = listen.clap_hints(np.ones(rate, np.float32), [{'t': .2}], Path(j('cache')))
            ast = listen.ast_hints(np.ones(16000, np.float32), [{'t': .2}], Path(j('cache')))
        finally:
            listen.sibling = original_sibling
            for name, old in saved_modules.items():
                if old is None: sys.modules.pop(name, None)
                else: sys.modules[name] = old
        record('listen labels: model APIs are local-only and return scored hints',
               len(loaded) == 4 and all(row[2].get('local_files_only') is True for row in loaded)
               and clap[0][0]['label'] == listen.LABEL_PROMPTS[0] and ast[0][0]['label'] == 'speech',
               str((loaded, clap, ast)))

    env = dict(os.environ, LOCALAPPDATA=j('u5b-empty-cache'), XDG_DATA_HOME=j('u5b-empty-cache'))
    missing = subprocess.run([sys.executable, '-I', str(Path(scripts_dir) / 'listen.py'), 'labels', str(sound)],
                             capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    record('listen labels: missing weights name the installer without a traceback',
           missing.returncode == 2 and '--install ear' in missing.stderr and 'Traceback' not in missing.stderr,
           missing.stderr[-300:])

    setup = module(scripts_dir, 'setup')
    if not hasattr(setup, 'install_ear'):
        record('setup ear: size and consent precede all downloads', False, 'ear installer missing')
    else:
        calls, stderr = [], io.StringIO()
        old_run, old_consent = setup.subprocess.run, setup.consent
        try:
            setup.subprocess.run = lambda *args, **kwargs: calls.append(args)
            def deny(question, yes):
                raise ValueError('consent denied')
            setup.consent = deny
            with contextlib.redirect_stderr(stderr):
                try:
                    setup.install_ear(False, sys.executable)
                except ValueError:
                    pass
        finally:
            setup.subprocess.run, setup.consent = old_run, old_consent
        record('setup ear: size and consent precede all downloads',
               not calls and '1.4' in stderr.getvalue() and 'GB' in stderr.getvalue(), stderr.getvalue())
        old_run, old_consent = setup.subprocess.run, setup.consent
        calls = []
        try:
            setup.subprocess.run = lambda args, **kwargs: calls.append(args)
            setup.consent = lambda question, yes: None
            with contextlib.redirect_stderr(io.StringIO()):
                setup.install_ear(True, sys.executable)
        finally:
            setup.subprocess.run, setup.consent = old_run, old_consent
        record('setup ear: public CPU installs and model downloads are explicit and unauthenticated',
               len(calls) == 3 and '--isolated' in calls[0] and '--isolated' in calls[1]
               and 'https://download.pytorch.org/whl/cpu' in calls[0]
               and 'https://pypi.org/simple' in calls[1]
               and any('token=False' in value for value in calls[2]), str(calls))
        old_ready = setup.ear_ready
        try:
            states = {name: 'ready' for name in setup.REQUIRED}
            setup.ear_ready = lambda: False
            missing_code = setup.exit_code(states, 'ear')
            setup.ear_ready = lambda: True
            ready_code = setup.exit_code(states, 'ear')
        finally:
            setup.ear_ready = old_ready
        record('setup ear: install status depends on local packages and weights',
               missing_code == 1 and ready_code == 0, str((missing_code, ready_code)))
    no_input = subprocess.run([sys.executable, '-I', str(Path(scripts_dir) / 'setup.py'), '--install', 'ear'],
                              input='', capture_output=True, text=True,
                              encoding='utf-8', errors='replace')
    code, output = no_input.returncode, no_input.stdout + no_input.stderr
    record('setup ear: noninteractive install refuses without prior consent',
           code == 2 and '1.4 GB' in output and 'agree' in output.lower(), output[-400:])

    sound_report = Path(j('u5b-sound.json'))
    code, output = tool('sound_check.py', sound, '--json', sound_report)
    measured = json.loads(sound_report.read_text(encoding='utf-8')) if sound_report.exists() else {}
    record('sound check: listening measurements and seven-film reference are included',
           code in (0, 1) and measured.get('listening_measurements', {}).get('integrated_lufs') is not None
           and measured.get('listening_reference', {}).get('label') == 'seven launch films (n = 7)', output[-300:])

    delivery_path = Path(scripts_dir) / 'delivery_check.py'
    if not delivery_path.is_file():
        record('delivery stress: absent libvmaf is not assessed', False, 'delivery_check.py missing')
    else:
        help_run = subprocess.run([sys.executable, '-I', '-S', str(delivery_path), '--help'],
                                  capture_output=True, text=True, encoding='utf-8', errors='replace')
        help_output = help_run.stdout + help_run.stderr
        record('delivery stress: missing NumPy gives setup guidance without a traceback',
               (help_run.returncode == 0 or (help_run.returncode == 2 and 'setup.py' in help_output))
               and 'Traceback' not in help_output, help_output[-300:])
        delivery = module(scripts_dir, 'delivery_check')
        if not hasattr(delivery, 'delivery_report'):
            record('delivery stress: absent libvmaf is not assessed', False, 'delivery_report missing')
        else:
            old = delivery.has_libvmaf
            try:
                delivery.has_libvmaf = lambda ffmpeg: False
                report = delivery.delivery_report(sound, Path(j('u5b-no-vmaf')), ffmpeg='ffmpeg')
            finally:
                delivery.has_libvmaf = old
            record('delivery stress: absent libvmaf is not assessed',
                   report.get('state') == 'not assessed' and 'libvmaf' in report.get('reason', ''), str(report))
            try:
                delivery.output_guard(sound, version / 'stress')
                allowed = True
            except ValueError:
                allowed = False
            try:
                delivery.output_guard(sound, sound)
                alias_allowed = True
            except ValueError:
                alias_allowed = False
            record('delivery stress: version and input aliases are refused before writes',
                   not allowed and not alias_allowed and not (version / 'stress').exists(), '')

            check = module(scripts_dir, 'check')
            original_run = check.run_script
            def fake_report(state):
                def run(name, video, folder):
                    Path(folder).mkdir(parents=True)
                    result = {'state': state, 'frames_checked': 10, 'reason': 'FFmpeg lacks libvmaf'}
                    (Path(folder) / 'report.json').write_text(json.dumps(result), encoding='utf-8')
                    return 0, ''
                return run
            try:
                check.run_script = fake_report('measured')
                found = check.stress_item(sound)
                check.run_script = fake_report('not assessed')
                absent = check.stress_item(sound)
            finally:
                check.run_script = original_run
            record('check stress: measured screens prompt review and missing metrics are not assessed',
                   found['state'] == 'look' and found['group'] == 'stress' and absent['state'] == 'skip'
                   and 'libvmaf' in absent['detail'], str((found, absent)))

            ffmpeg = shutil.which('ffmpeg')
            available = bool(ffmpeg and delivery.has_libvmaf(ffmpeg))
            flat_fixture = Path(j('u5b-flat.mkv'))
            if not available:
                skip('delivery gradient and flat fixtures', 'FFmpeg lacks libvmaf')
            else:
                results = []
                for name, expression in (('gradient', '16+20*X/W'), ('flat', '16')):
                    fixture = Path(j('u5b-' + name + '.mkv'))
                    command = [ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                               f"nullsrc=s=640x360:r=10:d=1,geq=lum='{expression}':cb=128:cr=128",
                               '-c:v', 'ffv1', str(fixture)]
                    subprocess.run(command, check=True, capture_output=True)
                    results.append(delivery.delivery_report(fixture, Path(j('u5b-' + name + '-delivery')),
                                                           sims=['320x180@256k']))
                dark, flat = results
                record('delivery stress: a dark gradient is flagged and a flat frame is not',
                       bool(dark['banding_candidates']) and not flat['banding_candidates']
                       and dark['frames_checked'] == flat['frames_checked'] == 10
                       and dark['simulations'][0]['frames_checked'] == 10
                       and dark['simulations'][0]['vmaf']['mean'] is not None,
                       str({'dark': dark['cambi'], 'flat': flat['cambi']}))
                changing = Path(j('u5b-changing.mkv'))
                shutil.copyfile(flat_fixture, changing)
                original_command = delivery.command
                def change_during_analysis(*args):
                    original_command(*args)
                    with changing.open('ab') as stream:
                        stream.write(b'changed during check')
                try:
                    delivery.command = change_during_analysis
                    try:
                        delivery.delivery_report(changing, Path(j('u5b-changing-delivery')), sims=['none'])
                        refused = False
                    except ValueError as error:
                        refused = 'changed during' in str(error)
                finally:
                    delivery.command = original_command
                record('delivery stress: changed input bytes cannot yield a completed report', refused, '')
            if not (os.environ.get('LF_HEAVY_LOCK') or os.environ.get('CI')):
                skip('check --stress CLI', 'run in the locked full selftest or CI')
            elif not ffmpeg:
                skip('check --stress CLI', 'FFmpeg is unavailable')
            else:
                if not flat_fixture.exists():
                    subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i',
                                    'color=black:s=640x360:r=10:d=1', '-c:v', 'ffv1', str(flat_fixture)],
                                   check=True, capture_output=True)
                report_file = Path(j('u5b-stress-check.json'))
                code, output = tool('check.py', '--file', flat_fixture, '--stress', '--no-speech',
                                    '--json', report_file)
                checks = json.loads(report_file.read_text(encoding='utf-8')) if report_file.exists() else {}
                item = next((row for row in checks.get('items', []) if row['id'] == 'stress_delivery'), {})
                record('check --stress CLI: the delivery result is attached to the check',
                       code in (0, 1) and item.get('state') == ('look' if available else 'skip')
                       and item.get('group') == 'stress'
                       and 'delivery_check.py' in checks.get('tools', {}).get('scripts', {}),
                       str(item) + output[-400:])
