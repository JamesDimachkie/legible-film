#!/usr/bin/env python3
"""Run one foreground command under a heavy-job lock file, so heavy jobs on one machine take turns.

  python evals/with_lock.py --lock PATH -- python evals/build_fixtures.py CACHE FIXTURES

Checks available physical RAM, creates the lock exclusively and removes it only
if it still contains this process's unique marker. Waits in the foreground for
the lock and for at least 1000 MiB free; a lock older than 45 minutes is reported,
never removed. A low-memory wait stops after 20 minutes. No network is used.
Exit with the child status, or 2 when the command cannot start safely.
"""
import argparse
import ctypes
import datetime
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path


class MemoryStatus(ctypes.Structure):
    """Windows GlobalMemoryStatusEx structure."""
    _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong),
                ('total_phys', ctypes.c_ulonglong), ('avail_phys', ctypes.c_ulonglong),
                ('total_page', ctypes.c_ulonglong), ('avail_page', ctypes.c_ulonglong),
                ('total_virtual', ctypes.c_ulonglong), ('avail_virtual', ctypes.c_ulonglong),
                ('avail_extended', ctypes.c_ulonglong)]


def free_memory_mib():
    """Return available physical memory without an optional package."""
    if os.name == 'nt':
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError('GlobalMemoryStatusEx failed')
        return status.avail_phys / 1024 / 1024
    path = Path('/proc/meminfo')
    if path.is_file():
        for line in path.read_text(encoding='ascii').splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1024
    raise OSError('cannot determine available physical memory')


def main():
    """Acquire the lock, run the requested child and release only our own lock."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command and args.command[0] == '--' else args.command
    if not command:
        parser.error('a foreground command is required after --')
    marker = f'lane-evals2 {datetime.datetime.now().isoformat()} {uuid.uuid4()}\n'
    waiting_for_memory = None
    try:
        while True:
            available = free_memory_mib()
            if available < 1000:
                waiting_for_memory = waiting_for_memory or time.monotonic()
                if time.monotonic() - waiting_for_memory >= 20 * 60:
                    raise RuntimeError(f'available memory remained below 1000 MiB: {available:.0f} MiB')
                print(f'Waiting 60s for RAM: {available:.0f} MiB available', flush=True)
                time.sleep(60)
                continue
            waiting_for_memory = None
            try:
                with args.lock.open('x', encoding='utf-8', newline='\n') as handle:
                    handle.write(marker)
                break
            except FileExistsError:
                try:
                    age = time.time() - args.lock.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > 45 * 60:
                    raise RuntimeError(f'existing lock is {age / 60:.1f} minutes old; not removing it')
                print(f'Waiting 60s for the lock; age {age / 60:.1f} minutes', flush=True)
                time.sleep(60)
        try:
            print(f'Acquired lock with {available:.0f} MiB free', flush=True)
            return subprocess.run(command).returncode
        finally:
            if args.lock.is_file() and args.lock.read_text(encoding='utf-8') == marker:
                args.lock.unlink()
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
