"""with_lock.py: one heavy job per machine (SPEC §9 "Render lock"). The memory probe is stubbed, so no case needs a
machine with 3 GiB free; the shim case runs only in a checkout, where evals/ exists."""
import importlib.util
import io
import os
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


def load(scripts_dir, name):
    spec = importlib.util.spec_from_file_location('selftest_lock_' + name, Path(scripts_dir) / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def quiet(function, *args, **kwargs):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        result = function(*args, **kwargs)
    return result, out.getvalue() + err.getvalue()


def run_lock_cases(tool, record, j, scripts_dir, skip=None):
    lock_module = load(scripts_dir, 'with_lock')
    setup = load(scripts_dir, 'setup')
    folder = Path(j('lock-cases'))
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / 'heavy.lock'
    marker = folder / 'ran.txt'
    command = [sys.executable, '-c', f'open({str(marker)!r}, "w").write("ran")']
    low = lambda: 1 * 1024 ** 3  # noqa: E731  (1 GiB free)
    began = time.monotonic()
    code, output = quiet(lock_module.main, ['--lock', str(lock), '--wait-min', '0.005', '--poll-s', '0.05', '--',
                                            *command], probe=low)
    record('lock: with free memory stubbed under 3 GiB it waits, then exits 2 at the limit without running',
           code == 2 and not marker.exists() and time.monotonic() - began >= 0.25 and not lock.exists(), output[-200:])
    code, output = quiet(lock_module.main, ['--lock', str(lock), '--min-free-gib', '0.5', '--wait-min', '0.005',
                                            '--', *command], probe=low)
    record('lock: the same machine runs the job with --min-free-gib 0.5, and the lock is gone afterwards',
           code == 0 and marker.exists() and not lock.exists(), output[-200:])
    record('lock: the default lock is heavy.lock in the per-user data folder setup.py names',
           lock_module.default_lock() == setup.data_home() / 'heavy.lock', str(lock_module.default_lock()))
    holder = subprocess.Popen([sys.executable, str(Path(scripts_dir) / 'with_lock.py'), '--lock', str(lock),
                               '--min-free-gib', '0', '--', sys.executable, '-c', 'import time; time.sleep(4)'],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.monotonic() + 20
    while not lock.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    blocked = subprocess.run([sys.executable, str(Path(scripts_dir) / 'with_lock.py'), '--lock', str(lock),
                              '--min-free-gib', '0', '--wait-min', '0.01', '--poll-s', '0.1', '--', sys.executable,
                              '-c', 'pass'], capture_output=True, text=True)
    waited = subprocess.run([sys.executable, str(Path(scripts_dir) / 'with_lock.py'), '--lock', str(lock),
                             '--min-free-gib', '0', '--wait-min', '1', '--poll-s', '0.2', '--', sys.executable, '-c',
                             'print("second ran")'], capture_output=True, text=True)
    holder.wait(timeout=60)
    record('lock: a second instance waits for the first\'s lock (exit 2 when its wait runs out, runs once it is free)',
           blocked.returncode == 2 and 'waited' in blocked.stderr and waited.returncode == 0
           and 'second ran' in waited.stdout and not lock.exists(), blocked.stderr[-160:] + waited.stdout[-160:])
    mine = lock_module.HeavyLock(lock, 0, 0.01, 0.05, say=lambda *a, **k: None).acquire()
    lock.write_text('another owner\n', encoding='utf-8')
    mine.release()
    kept = lock.is_file() and lock.read_text(encoding='utf-8') == 'another owner\n'
    lock.unlink()
    record('lock: a lock is removed only by its owner', kept)
    # Re-entrance (BUILD-DECISIONS row 30): a heavy step inside a job that holds the lock does not wait for its parent.
    script = str(Path(scripts_dir) / 'with_lock.py')
    nested = subprocess.run([sys.executable, script, '--lock', str(lock), '--min-free-gib', '0', '--', sys.executable,
                             script, '--lock', str(lock), '--min-free-gib', '0', '--wait-min', '0.01', '--poll-s',
                             '0.1', '--', sys.executable, '-c', 'print("inner ran")'], capture_output=True, text=True,
                            timeout=120)
    record('lock: a job inside the lock its parent holds runs at once, and the lock is gone afterwards',
           nested.returncode == 0 and 'inner ran' in nested.stdout and 'inside the lock its parent holds' in nested.stdout
           and not lock.exists(), nested.stdout[-200:] + nested.stderr[-200:])
    lock.write_text('another owner\n', encoding='utf-8')
    stranger = lock_module.HeavyLock(lock, 0, 0.005, 0.05, say=lambda *a, **k: None)
    with mock.patch.dict(os.environ, {lock_module.ENV_PATH: str(lock), lock_module.ENV_MARKER: 'not the holder'}):
        try:
            stranger.acquire()
            waited_for_owner = False
        except lock_module.LockTimeout:
            waited_for_owner = True
    lock.unlink()
    record('lock: an inherited marker that no longer holds the lock does not count as holding it', waited_for_owner)
    vm_stat = ('Mach Virtual Memory Statistics: (page size of 16384 bytes)\nPages free:      1000.\n'
               'Pages active:   5000.\nPages inactive:  2000.\nPages speculative:  500.\n')
    with mock.patch.object(setup.os, 'name', 'posix'), mock.patch.object(setup.sys, 'platform', 'darwin'), \
            mock.patch.object(setup, 'run', return_value=vm_stat):
        found = setup.free_memory()
    record('lock: the macOS probe parses stubbed vm_stat output (free, inactive and speculative pages)',
           found == 16384 * 3500, str(found))
    shim = Path(scripts_dir).resolve().parents[2] / 'evals' / 'with_lock.py'
    if not shim.is_file():
        reason = 'an installed skill has no evals/ folder'
        if skip:
            skip('lock: evals/with_lock.py forwards its arguments', reason)
        else:
            print(f'SKIP  lock: evals/with_lock.py forwards its arguments ({reason})')
        return
    result = subprocess.run([sys.executable, str(shim), '--lock', str(lock), '--min-free-gib', '0', '--', sys.executable,
                             '-c', 'import sys; print("forwarded"); sys.exit(3)'], capture_output=True, text=True)
    record('lock: evals/with_lock.py forwards its arguments to the skill\'s with_lock.py',
           result.returncode == 3 and 'forwarded' in result.stdout and str(lock) in result.stdout
           and not lock.exists(), result.stdout[-200:] + result.stderr[-200:])
