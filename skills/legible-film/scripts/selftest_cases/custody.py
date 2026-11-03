"""Custody (SPEC §9): an output never replaces an input, and a version folder (cuts/vNNN holding manifest.json) is
immutable except for check.py's QA files under the project that holds it. check.py on a real version is in the
readers cases, which render one."""
import importlib.util
import json
import os
import subprocess
from pathlib import Path


def load_project(scripts_dir):
    spec = importlib.util.spec_from_file_location('selftest_custody_project', Path(scripts_dir) / 'project.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def refused(module, outputs, inputs=(), **kwargs):
    try:
        module.refuse_overwriting_inputs(outputs, list(inputs), **kwargs)
        return ''
    except ValueError as error:
        return str(error) or 'refused'


def make_version(root):
    version = root / 'cuts' / 'v001'
    (version / 'qa').mkdir(parents=True)
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001'}), encoding='utf-8')
    (version / 'preview.mp4').write_bytes(b'\x00' * 16)
    return version


def link(target, alias):
    """A directory link (symbolic, or a junction on Windows without the symlink privilege); False when neither."""
    try:
        os.symlink(target, alias, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == 'nt':
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(target)], capture_output=True, text=True)
        return r.returncode == 0 and alias.exists()
    return False


def run_custody_cases(tool, record, j, scripts_dir, skip=None):
    lf = load_project(scripts_dir)
    base = Path(j('custody-cases'))
    root, other = base / 'project', base / 'other'
    version, foreign = make_version(root), make_version(other)
    preview = version / 'preview.mp4'
    qa = [version / 'qa' / 'qc.json', version / 'checks.json', version / 'checks-final.json', root / 'status.json']
    record('custody: check.py\'s QA files may be written into a version of the project that holds it',
           not refused(lf, qa, [preview], project=root), refused(lf, qa, [preview], project=root))
    record('custody: an output that is its input is refused, as before',
           'is the input' in refused(lf, [preview], [preview]) and
           'is the input' in refused(lf, [preview], [preview], guard_versions=True))
    inside = version / 'mix.wav'
    record('custody: a write inside cuts/v001 outside qa/ is refused for a project and for a standalone tool',
           'immutable' in refused(lf, [inside], project=root)
           and 'immutable' in refused(lf, [inside], guard_versions=True)
           and 'immutable' in refused(lf, [version / 'qa' / 'qc.json'], guard_versions=True))
    record('custody: a write into another project\'s cuts/v001, even its qa/, is refused',
           'immutable' in refused(lf, [foreign / 'qa' / 'qc.json'], project=root)
           and 'immutable' in refused(lf, [foreign / 'checks.json'], project=root))
    record('custody: a folder without manifest.json is not yet a version (a render still writes it)',
           not refused(lf, [root / 'cuts' / 'v002' / 'preview.mp4'], project=root))
    record('custody: callers that write into a version by design (no project, no guard) behave as in 2.0',
           not refused(lf, [version / 'scorecard.json'], [preview]))
    alias = base / 'alias'
    if link(foreign, alias):
        record('custody: a write through a link into another project\'s version is refused',
               'immutable' in refused(lf, [alias / 'qa' / 'qc.json'], project=root)
               and 'immutable' in refused(lf, [alias / 'checks.json'], project=root))
    elif skip:
        skip('custody: a write through a link into a version is refused', 'this system cannot make a directory link')
    else:
        print('SKIP  custody: a write through a link (this system cannot make a directory link)')
