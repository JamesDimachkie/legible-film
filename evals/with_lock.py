#!/usr/bin/env python3
"""Shim: run a command under the skill's heavy-job lock (skills/legible-film/scripts/with_lock.py).

  python evals/with_lock.py [--lock PATH] [--min-free-gib 3] [--wait-min 20] -- CMD ...

Every argument is forwarded unchanged. The lock defaults to heavy.lock in the per-user data folder, the file
evals/trigger_run.py takes, and the memory threshold to 3 GiB; a light eval job passes --min-free-gib 1.
Exit with the command's status, or 2 when it could not start.
"""
import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / 'skills' / 'legible-film' / 'scripts' / 'with_lock.py'

if __name__ == '__main__':
    if not TARGET.is_file():
        print(f'with_lock.py: the skill script is missing: {TARGET}', file=sys.stderr)
        sys.exit(2)
    sys.argv = [str(TARGET)] + sys.argv[1:]
    sys.exit(runpy.run_path(str(TARGET), run_name='lf_with_lock')['main']())
