#!/usr/bin/env python3
"""Run one heavy command at a time on this machine: wait for the shared lock file and for free memory, then run it.

  python with_lock.py -- python make_film.py film/ --out deliver/
  python with_lock.py --min-free-gib 1 -- python selftest.py --smoke
  python with_lock.py [--lock PATH] [--min-free-gib 3] [--wait-min 20] [--poll-s 20] -- CMD ...

The lock file defaults to heavy.lock in the per-user data folder setup.py names (on Windows under LOCALAPPDATA, on
Linux and macOS under XDG_DATA_HOME or ~/.local/share), the file the eval runner and earlier heavy jobs take, so
every heavy job on the machine takes turns. Free memory is measured as setup.py measures it (Windows
GlobalMemoryStatusEx, macOS vm_stat, Linux MemAvailable). The lock is created exclusively and holds a unique marker;
only the process whose marker it holds removes it. A lock older than 45 minutes is reported, never removed. The
waits for the lock and for memory share one limit, --wait-min; when it runs out nothing runs and the exit is 2.
The lock is re-entrant down the process tree: the holder passes LF_HEAVY_LOCK and LF_HEAVY_LOCK_MARKER to its
children, and a descendant asking for the same lock while that marker still holds it proceeds at once (a heavy step
inside the full self-test, which already holds the lock, never waits for its own parent).
No network is used. Exit with the command's own status, or 2 when it could not start.
"""
import argparse
import datetime
import importlib.util
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
STALE_MINUTES = 45
ENV_PATH, ENV_MARKER = 'LF_HEAVY_LOCK', 'LF_HEAVY_LOCK_MARKER'


def _setup():
    spec = importlib.util.spec_from_file_location('lf_setup_lock', HERE / 'setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_lock():
    """heavy.lock in the per-user data folder (setup.data_home())."""
    return _setup().data_home() / 'heavy.lock'


def free_bytes():
    """Available physical memory in bytes, or None when the system does not say."""
    return _setup().free_memory()


class LockTimeout(Exception):
    """The lock or the memory did not come within the wait."""


class HeavyLock:
    """The shared heavy-job lock: wait for it and for free memory, hold it, release only our own."""

    def __init__(self, path=None, min_free_gib=3.0, wait_min=20.0, poll_s=20.0, probe=None, say=print,
                 label='with_lock'):
        self.path = Path(path) if path else default_lock()
        self.min_bytes = float(min_free_gib) * 1024 ** 3
        self.wait_s = float(wait_min) * 60
        self.poll_s = max(0.05, float(poll_s))
        self.probe = probe or free_bytes
        self.say = say
        self.marker = f'{label} {os.getpid()} {datetime.datetime.now().isoformat()} {uuid.uuid4()}\n'
        self.free_at_start = None
        self.held = False
        self.inherited = False
        self._saved_env = None

    def held_by_ancestor(self):
        """Whether an ancestor holds this lock: the inherited LF_HEAVY_LOCK names this file and its marker is still
        the one in the file (environment variables pass only to descendants)."""
        named, marker = os.environ.get(ENV_PATH), os.environ.get(ENV_MARKER)
        if not named or not marker:
            return False
        try:
            same = os.path.normcase(os.path.abspath(named)) == os.path.normcase(os.path.abspath(self.path))
            return same and self.path.read_text(encoding='utf-8').strip() == marker
        except OSError:
            return False

    def child_env(self):
        """The environment that tells a child process this lock is held by its ancestor."""
        return dict(os.environ, **{ENV_PATH: str(os.path.abspath(self.path)), ENV_MARKER: self.marker.strip()})

    def acquire(self):
        if self.held_by_ancestor():
            self.inherited = True
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.wait_s
        said = {}
        while True:
            free = self.probe() if self.min_bytes > 0 else None
            if self.min_bytes > 0 and free is not None and free < self.min_bytes:
                reason = (f'free memory {free / 1024 ** 3:.2f} GiB is under {self.min_bytes / 1024 ** 3:.2f} GiB')
                if time.monotonic() >= deadline:
                    raise LockTimeout(f'waited {self.wait_s / 60:g} min; {reason}')
                if said.get('memory', 0) + 300 < time.monotonic():
                    self.say(f'waiting: {reason}', flush=True)
                    said['memory'] = time.monotonic()
                time.sleep(self.poll_s)
                continue
            try:
                with self.path.open('x', encoding='utf-8', newline='\n') as handle:
                    handle.write(self.marker)
                self.held = True
                self.free_at_start = free
                # Children of this process (and of a library caller) inherit the lock.
                self._saved_env = {k: os.environ.get(k) for k in (ENV_PATH, ENV_MARKER)}
                os.environ.update({ENV_PATH: str(os.path.abspath(self.path)), ENV_MARKER: self.marker.strip()})
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                    holder = self.path.read_text(encoding='utf-8', errors='replace').strip()
                except FileNotFoundError:
                    continue
                if age > STALE_MINUTES * 60 and not said.get('stale'):
                    self.say(f'the lock {self.path} is {age / 60:.0f} minutes old ({holder}); it is never removed '
                             'here: if its job is gone, the person removes it', flush=True)
                    said['stale'] = True
                if time.monotonic() >= deadline:
                    raise LockTimeout(f'waited {self.wait_s / 60:g} min for the lock {self.path} ({holder})')
                if said.get('lock', 0) + 300 < time.monotonic():
                    self.say(f'waiting for the lock {self.path} ({holder}, {age / 60:.1f} min old)', flush=True)
                    said['lock'] = time.monotonic()
                time.sleep(self.poll_s)

    def release(self):
        """Remove the lock only when it still holds this process's marker; an inherited lock is left to its owner."""
        try:
            if self.held and self.path.is_file() and self.path.read_text(encoding='utf-8') == self.marker:
                self.path.unlink()
        except OSError:
            pass
        if self._saved_env is not None:
            for key, value in self._saved_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            self._saved_env = None
        self.held = False
        self.inherited = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()
        return False


def main(argv=None, probe=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lock', help='lock file (default: heavy.lock in the per-user data folder)')
    p.add_argument('--min-free-gib', type=float, default=3.0, help='free memory to wait for (default 3)')
    p.add_argument('--wait-min', type=float, default=20.0, help='longest wait for the lock and memory (default 20)')
    p.add_argument('--poll-s', type=float, default=20.0, help='seconds between checks (default 20)')
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args(argv)
    command = a.command[1:] if a.command and a.command[0] == '--' else a.command
    if not command:
        p.error('give the command after --')
    if a.min_free_gib < 0 or a.wait_min < 0:
        p.error('--min-free-gib and --wait-min cannot be negative')
    lock = HeavyLock(a.lock, a.min_free_gib, a.wait_min, a.poll_s, probe=probe)
    try:
        lock.acquire()
    except LockTimeout as error:
        print(f'with_lock.py: {error}; nothing ran', file=sys.stderr)
        return 2
    except OSError as error:
        print(f'with_lock.py: cannot take the lock {lock.path}: {error}', file=sys.stderr)
        return 2
    try:
        free = '' if lock.free_at_start is None else f' with {lock.free_at_start / 1024 ** 3:.1f} GiB free'
        held = 'inside the lock its parent holds' if lock.inherited else 'holding'
        print(f'with_lock.py: {held} {lock.path}{free}', flush=True)
        try:
            return subprocess.run(command, env=lock.child_env() if lock.held else None).returncode
        except OSError as error:
            print(f'with_lock.py: cannot run {command[0]}: {error}', file=sys.stderr)
            return 2
    finally:
        lock.release()


if __name__ == '__main__':
    sys.exit(main())
