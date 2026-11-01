#!/usr/bin/env python3
"""Read and write a Legible Film project folder (references/project.md): paths, status, versions, aliases, times.

  python project.py init PROJECT [--title TITLE] [--film FILE]
                                                   create the layout and a status.json; --film starts the project
                                                   from that paper edit, and changes nothing when the folder
                                                   already has a different film.md
  python project.py status [PROJECT] [--json]      print the one-line status the agent posts in chat
  python project.py stage PROJECT STAGE now|done|waiting [--note TEXT]
                                                   record progress or a wait for the person
  python project.py review PROJECT KIND [--version vNNN] [--file FILE]
                                                   record a person's review of a file (KIND: watched_muted, heard,
                                                   names or approved); the version's preview unless --file

A review records the reviewed file's SHA-256 and counts only for a file with the same content: watching the preview
never passes a different final file. Record a review only when the person says they did it.

A checks file (checks.json, checks-final.json) records the inputs its result depends on (path, sha256, bytes,
mtime_ns). Status compares a file's byte count and modification time first, hashing only when its time differs and
its size matches. A change preserving both size and time can escape status; check.py --verify hashes recorded files.
Status also compares transcript listings and tool versions and hashes. Recording a review and showing a final
acceptance always hash the file. A detected change reads "out of date (... changed): run check.py again" and old
results do not count. A checks file written before inputs were recorded reads as before, marked "inputs not recorded".

Four things are kept apart; status --json prints them as separate fields:
  progress    {stage, stages, stage_notes, running}: a stage marked done means its work ran, not that its checks
              passed or that a person accepted it;
  checks      {preview, final}: each {file, sha256, final, state (current, out_of_date or inputs_not_recorded),
              changed [{role, path, change}], summary (null when out of date), open_reviews, approved} or null;
  review      {open: person checks no review covers yet, notes_open: [{id, t, text}] screening notes still open};
  acceptance  {preview, final}: a person's `approved` record for that file's SHA-256, or null.
It also carries `line`, the one-line status, and `current`, the version.

The other scripts import this module rather than reading the files themselves, so the layout lives in one place.
Writes are atomic (a temporary file, then a rename): a page or agent reading at the same moment never sees half a
file. Exit 0 on success, 2 when it cannot run.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STAGES = ('map', 'plan', 'cut', 'check', 'screen', 'revise', 'deliver')
STATES = ('todo', 'now', 'done', 'skipped', 'waiting')
ROLE_PREFIX = {'interview': 'int', 'broll': 'broll', 'screen': 'screen', 'music': 'music', 'sfx': 'sfx', 'vo': 'vo',
               'still': 'still', 'other': 'src'}
MARKERS = ('film.md', 'status.json', 'map', 'cuts')
VERSION_NAME = re.compile(r'v(\d{3,})$')


def python_command(args, python=None, system=None):
    """Format a command for the interpreter and the shells available on its operating system."""
    system = system or platform.system()
    parts = [str(python or sys.executable), *map(str, args)]
    if system != 'Windows':
        return ' '.join(shlex.quote(part) for part in parts)
    parts = [parts[0].replace('\\', '/')] + [str(arg).replace('\\', '/') if isinstance(arg, os.PathLike) else str(arg)
                                                for arg in args]
    if all(re.fullmatch(r'[A-Za-z0-9_./:=+,-]+', part) for part in parts):
        return ' '.join(parts)

    def quoted(part):
        return '"' + part.replace('"', '\\"') + '"' if not re.fullmatch(r'[A-Za-z0-9_./:=+,-]+', part) else part

    def powershell_part(part):
        if re.fullmatch(r'[A-Za-z0-9_./:=+,-]+', part):
            return part
        escaped = part.replace('`', '``').replace('$', '`$').replace('"', '`"')
        return '"' + escaped + '"'

    regular = ' '.join(quoted(part) for part in parts)
    powershell = ' '.join(powershell_part(part) for part in parts)
    if powershell.startswith('"'):
        powershell = '& ' + powershell
    if any(re.search(r'[$`"]', part) for part in parts):
        bash = ' '.join(shlex.quote(part) for part in parts)
        return 'PowerShell: ' + powershell + '\n    cmd: ' + regular + '\n    Git Bash: ' + bash
    return 'PowerShell: ' + powershell + '\n    cmd or Git Bash: ' + regular


def missing_package(error):
    """Say which package is missing from this Python and the setup command that installs it; return exit code 2.
    Scripts call it from the guard round their numpy and Pillow imports, so one run before setup names the fix
    instead of failing with a traceback."""
    print(dependency_message(getattr(error, 'name', None) or 'numpy'), file=sys.stderr)
    return 2


def dependency_message(name, python=None, context=None):
    """Name a missing package, its interpreter and the matching setup command."""
    module = name.split('.')[0]
    package, option = {'PIL': ('Pillow', 'core'), 'numpy': ('numpy', 'core'),
                       'faster_whisper': ('faster-whisper', 'transcription'),
                       'onnxruntime': ('onnxruntime', 'transcription'), 'cv2': ('opencv-python', 'spatial'),
                       'modnet': ('MODNet model', 'spatial')}.get(module, (module, None))
    if module == 'onnxruntime' and context == 'spatial':
        option = 'spatial'
    executable = str(python or sys.executable)
    if option is None:
        command = python_command(['-m', 'pip', 'install', package], executable)
        return f'{package} is missing from Python {executable}. Fix: {command}'
    arguments = [Path(__file__).with_name('setup.py'), '--install', option]
    if module == 'modnet':
        arguments.append('--download')
    command = python_command(arguments, executable)
    return f'{package} is missing from Python {executable}. Fix: {command}'


def now():
    """The current UTC time as an ISO 8601 string with a Z suffix, to the second."""
    stamp = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return stamp.isoformat().replace('+00:00', 'Z')


def safe_output():
    """Print any character: UTF-8 when output goes to a pipe or file (an agent reading it), and a stand-in
    character on a console whose legacy code page cannot show it."""
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, 'reconfigure'):
            continue
        if stream.isatty():
            stream.reconfigure(errors='replace')
        else:
            stream.reconfigure(encoding='utf-8', errors='replace')


def find_project(start='.'):
    """The nearest folder at or above `start` that holds film.md, status.json, map/ or cuts/; None if there is none.

    A rendered version (cuts/vNNN) keeps its own film.md, so version folders are passed over."""
    folder = Path(start).resolve()
    if folder.is_file():
        folder = folder.parent
    for candidate in (folder, *folder.parents):
        if candidate.parent.name == 'cuts' and VERSION_NAME.match(candidate.name):
            continue
        if any((candidate / marker).exists() for marker in MARKERS):
            return candidate
    return None


def read_text(path):
    """Text from a file written by any common tool: UTF-8 with or without a byte-order mark, or UTF-16 with one.

    On Windows a read can fail for a moment while another process renames a new copy into place; retry for a second."""
    deadline = time.monotonic() + 1.0
    while True:
        try:
            raw = Path(path).read_bytes()
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    return raw.decode('utf-8-sig')


def load_json(path, default=None):
    """A JSON file's content, or `default` when the file does not exist."""
    path = Path(path)
    if not path.is_file():
        return default
    return json.loads(read_text(path))


def write_atomic(path, text):
    """Write text with LF line endings by writing a temporary file beside it and renaming it into place."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        deadline = time.monotonic() + 1.0
        while True:
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def save_json(path, data):
    """Write JSON atomically, indented, keeping non-ASCII characters readable."""
    write_atomic(path, json.dumps(data, indent=1, ensure_ascii=False) + '\n')


def process_alive(pid):
    """Whether a process with this ID is running (never signals it; os.kill(pid, 0) would end it on Windows)."""
    if pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = ctypes.c_ulong()
            if not kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError, OSError):
        return False
    return True


def _lock_holder(lock):
    """The lock file's content and its holder's process ID (0 when unreadable)."""
    try:
        text = lock.read_text(encoding='ascii', errors='replace')
    except (FileNotFoundError, PermissionError):
        return None, 0
    pid = text.split()[0] if text.split() else ''
    return text, int(pid) if pid.isdigit() else 0


def _break_stale(lock, stale):
    """Remove a lock whose holder has exited; True when it was removed. A lock whose holder is confirmed alive is
    never removed, however old (a render holds its lock for as long as it runs); one with no readable holder is
    removed once older than `stale` seconds (at most 30).

    The content is read again just before removal, so a lock another waiter has meanwhile taken is left alone."""
    text, pid = _lock_holder(lock)
    if text is None:
        return False
    try:
        age = time.time() - lock.stat().st_mtime
    except (FileNotFoundError, PermissionError):
        return False
    if pid and process_alive(pid):
        return False
    if not pid and age <= max(2.0, min(stale, 30)):
        return False
    again, _ = _lock_holder(lock)
    if again != text:
        return False
    try:
        lock.unlink()
    except (FileNotFoundError, PermissionError):
        return False
    return True


@contextlib.contextmanager
def file_lock(path, timeout=30, stale=300):
    """Serialize cross-process updates to a file. A lock left by a process that has exited is broken at once; one
    whose holder still runs is never broken: after `timeout` seconds the wait ends with a TimeoutError naming the
    holder's process ID."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name('.' + path.name + '.lock')
    token = f'{os.getpid()} {os.urandom(8).hex()}'
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except (FileExistsError, PermissionError):
            if _break_stale(lock, stale):
                continue
            if time.monotonic() >= deadline:
                _, pid = _lock_holder(lock)
                if pid and process_alive(pid):
                    raise TimeoutError(f'timed out after {timeout:g} s waiting for {lock}: process {pid} holds it '
                                       'and is still running') from None
                raise TimeoutError(f'timed out waiting for {lock}; if no Legible Film command is running, '
                                   'it is safe to delete') from None
            time.sleep(0.05)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            stream.write(token)
        yield
    finally:
        for _ in range(20):
            try:
                if _lock_holder(lock)[0] == token:
                    lock.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.05)


def append_jsonl(path, record):
    """Append one JSON object as one line (decisions.jsonl is never rewritten)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        with open(path, 'a', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')


def default_status(title=''):
    """A status for a new project: nothing done yet."""
    return {'version': 1, 'title': title, 'skill_version': skill_version(), 'updated': now(), 'stage': 'map',
            'stages': {stage: 'todo' for stage in STAGES}, 'current': None, 'line': 'started', 'running': [],
            'needs_you': [], 'blind_spots': []}


def skill_version():
    """The skill's version from SKILL.md's front matter, or 'unknown'."""
    skill = Path(__file__).resolve().parent.parent / 'SKILL.md'
    try:
        match = re.search(r'^\s*version:\s*"?([^"\n]+)"?\s*$', skill.read_text(encoding='utf-8'), re.MULTILINE)
    except OSError:
        return 'unknown'
    return match.group(1).strip() if match else 'unknown'


def live_running(jobs):
    """Exclude jobs with a known dead PID; preserve legacy jobs and unrecognised PIDs."""
    if not isinstance(jobs, list):
        return jobs
    active = []
    for job in jobs:
        pid = job.get('pid') if isinstance(job, dict) else None
        if type(pid) is int and 0 < pid <= 2147483647 and not process_alive(pid):
            continue
        active.append(job)
    return active


def read_status(project):
    """The project's status, or a fresh one when status.json does not exist yet."""
    status = load_json(Path(project) / 'status.json', None)
    if not isinstance(status, dict):
        return default_status(Path(project).name)
    if 'running' in status:
        before = status['running']
        status['running'] = live_running(before)
        removed = [job for job in before if job not in status['running']] if isinstance(before, list) else []
        if (any(isinstance(job, dict) and str(job.get('job', '')).startswith('map ') for job in removed)
                and status.get('stage') == 'map'
                and status.get('line') == 'mapping sources'
                and not any(isinstance(job, dict) and str(job.get('job', '')).startswith('map ')
                            for job in status['running'])):
            status['line'] = 'map interrupted; inspect or rerun'
    return status


def update_status(project, **fields):
    """Merge `fields` into status.json (stages merge key by key), stamp the time and write it atomically."""
    with file_lock(Path(project) / 'status.json'):
        return _update_status(project, fields)


def _update_status(project, fields):
    """Update status while the caller holds its lock."""
    status = read_status(project)
    stages = fields.pop('stages', None)
    status.update(fields)
    if stages:
        unknown = [stage for stage, state in stages.items() if stage not in STAGES or state not in STATES]
        if unknown:
            raise ValueError(f'unknown stage or state: {unknown}')
        status.setdefault('stages', {}).update(stages)
    status['updated'] = now()
    save_json(Path(project) / 'status.json', status)
    return status


def set_stage(project, stage, line=None, back=False):
    """Move forward, or with back=True go back and reset the stages after it.

    Moving to the next stage completes the one left behind; jumping over stages (opening the room while mapping)
    leaves the unfinished stage to do. A call naming an earlier stage without back=True changes nothing, so mapping
    a new source or rebuilding the room during Revise never moves the project backwards."""
    if stage not in STAGES:
        raise ValueError(f'unknown stage: {stage}')
    with file_lock(Path(project) / 'status.json'):
        status = read_status(project)
        current = status.get('stage', 'map')
        if current in STAGES and STAGES.index(stage) < STAGES.index(current) and not back:
            return status
        if not back and (status.get('stages') or {}).get(stage) == 'waiting':
            return status
        stages = dict(status.get('stages') or {})
        for name, state in stages.items():
            if name not in STAGES:
                continue
            if back and STAGES.index(name) > STAGES.index(stage):
                stages[name] = 'todo'
            elif state == 'now' and name != stage:
                next_step = STAGES.index(stage) == STAGES.index(name) + 1
                stages[name] = 'done' if next_step and not back else 'todo'
        stages[stage] = 'now'
        extra = {'line': line} if line else {}
        return _update_status(project, dict(stage=stage, stages=stages, **extra))


def change_stage(project, stage, state, note=None):
    """Set an explicit stage state without silently completing a wait for a person."""
    if stage not in STAGES or state not in ('now', 'done', 'waiting'):
        raise ValueError('unknown stage or state')
    with file_lock(Path(project) / 'status.json'):
        status = read_status(project)
        current = status.get('stage', 'map')
        earlier = current in STAGES and STAGES.index(stage) < STAGES.index(current)
        if earlier and state != 'done':
            raise ValueError('cannot move to an earlier stage without an explicit reset')
        stages = dict(status.get('stages') or {})
        if not earlier and current != stage and stages.get(current) == 'now':
            stages[current] = 'done' if STAGES.index(stage) == STAGES.index(current) + 1 else 'todo'
        stages[stage] = state
        notes = dict(status.get('stage_notes') or {})
        if note:
            notes[stage] = note
        else:
            notes.pop(stage, None)
        fields = {'stages': stages, 'stage_notes': notes}
        if not earlier:
            fields['stage'] = stage
        return _update_status(project, fields)


WAITING_MARK = '; waiting for person: '


def waiting_status(status, line):
    """Append all stages that still need a person's decision, replacing any list a saved line already carries."""
    line = line.split(WAITING_MARK)[0]
    waiting = []
    for stage in STAGES:
        if (status.get('stages') or {}).get(stage) == 'waiting':
            note = (status.get('stage_notes') or {}).get(stage)
            waiting.append(stage + (': ' + str(note) if note else ''))
    return line + (WAITING_MARK + ', '.join(waiting) if waiting else '')


def versions(project):
    """The project's version folders in order: ['v001', 'v002', ...]."""
    cuts = Path(project) / 'cuts'
    if not cuts.is_dir():
        return []
    names = [p.name for p in cuts.iterdir() if p.is_dir() and VERSION_NAME.match(p.name)]
    return sorted(names, key=lambda name: int(VERSION_NAME.match(name).group(1)))


def current_version(project):
    """The version named in cuts/current, else the newest version, else None."""
    pointer = Path(project) / 'cuts' / 'current'
    if pointer.is_file():
        name = read_text(pointer).strip()
        if VERSION_NAME.match(name) and (Path(project) / 'cuts' / name).is_dir():
            return name
    names = versions(project)
    return names[-1] if names else None


def next_version(project):
    """The name for the next version folder (v001 for the first)."""
    names = versions(project)
    number = int(VERSION_NAME.match(names[-1]).group(1)) + 1 if names else 1
    return f'v{number:03d}'


def set_current(project, name):
    """Point cuts/current at an existing version and record it in the status."""
    if not VERSION_NAME.match(name) or not (Path(project) / 'cuts' / name).is_dir():
        raise ValueError(f'no such version: {name}')
    write_atomic(Path(project) / 'cuts' / 'current', name + '\n')
    update_status(project, current=name)


def new_alias(role, taken):
    """The next free alias for a role (int_01, broll_02, ...): never derived from a file name."""
    if role not in ROLE_PREFIX:
        raise ValueError(f'unknown role {role!r}; use one of {sorted(ROLE_PREFIX)}')
    prefix = ROLE_PREFIX[role]
    number = 1
    while f'{prefix}_{number:02d}' in taken:
        number += 1
    return f'{prefix}_{number:02d}'


def parse_time(text):
    """Seconds from 'ss.ss', 'm:ss.ss' or 'h:mm:ss.ss'."""
    text = str(text).strip()
    if not re.fullmatch(r'\d+(?::\d{1,2}){0,2}(?:\.\d+)?', text):
        raise ValueError(f'not a time: {text!r}')
    seconds = 0.0
    for part in text.split(':'):
        seconds = seconds * 60 + float(part)
    return seconds


def format_time(seconds, places=2):
    """'m:ss.ss', or 'h:mm:ss.ss' from an hour, for a non-negative number of seconds."""
    if seconds < 0:
        raise ValueError('time must be non-negative')
    scale = 10 ** places
    total = round(seconds * scale)
    whole, fraction = divmod(total, scale)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    tail = f'.{fraction:0{places}d}' if places else ''
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}{tail}'
    return f'{minutes}:{secs:02d}{tail}'


def readiness(summary):
    """A plain sentence from a checks summary: '11 checks pass · 1 to look at · 2 need you · 3 not assessed'.

    A summary that checked_summary marked out of date reads as out of date, naming what changed, with no count of
    passes; one whose inputs were never recorded says so. Checks not assessed are never counted as passing."""
    counts = summary or {}
    if counts.get('out_of_date'):
        return 'out of date (' + changes_text(counts['out_of_date']) + '): run check.py again'
    parts = []
    if counts.get('fail'):
        parts.append(f"{counts['fail']} failed")
    parts.append(f"{counts.get('pass', 0)} check{'s' if counts.get('pass', 0) != 1 else ''} pass")
    if counts.get('look'):
        parts.append(f"{counts['look']} to look at")
    if counts.get('you'):
        parts.append(f"{counts['you']} need you")
    if counts.get('skip'):
        parts.append(f"{counts['skip']} not assessed")
    if counts.get('inputs_recorded') is False:
        parts.append('inputs not recorded')
    return ' · '.join(parts)


def input_row(role, path, shown=None, sha256=None):
    """One checks.json `inputs` row for a file a result depends on: role, the path as given (or `shown`), sha256
    (hashed unless already known), bytes and mtime_ns; sha256 and bytes are None for a file that does not exist
    (adding it later changes the result)."""
    path = Path(path)
    row = {'role': role, 'path': str(shown if shown is not None else path), 'sha256': None, 'bytes': None,
           'mtime_ns': None}
    if path.is_file():
        stat = path.stat()
        row.update(sha256=sha256 or file_sha256(path), bytes=stat.st_size, mtime_ns=stat.st_mtime_ns)
    return row


def transcript_listing_row(path, shown=None):
    """Fingerprint the paths considered when choosing a map transcript, including an empty or absent map."""
    path = Path(path)
    row = {'role': 'map_transcript_listing', 'path': str(shown if shown is not None else path), 'sha256': None,
           'bytes': None, 'mtime_ns': None}
    if path.is_dir():
        names = sorted(candidate.relative_to(path).as_posix() for candidate in path.glob('*/words.json'))
        encoded = json.dumps(names, ensure_ascii=True, separators=(',', ':')).encode('ascii')
        row.update(sha256=hashlib.sha256(encoded).hexdigest(), bytes=len(encoded), mtime_ns=path.stat().st_mtime_ns)
    return row


def locate_input(path, bases):
    """The file an inputs row names: an absolute path as it is; a relative one against each base folder in turn (the
    first that exists), else against the first base."""
    given = Path(str(path))
    if given.is_absolute() or not bases:
        return given
    candidates = [Path(base) / given for base in bases]
    return next((candidate for candidate in candidates if candidate.exists()), candidates[0])


def input_changes(rows, bases, thorough=False):
    """What changed among recorded inputs: [{'role', 'path', 'change'}]. The byte count and modification time are
    compared first; a file is hashed only when they differ, so reading status stays fast on a large final. With
    `thorough`, every file whose size matches is hashed (check.py --verify). Transcript listings are always compared."""
    changes = []
    for row in rows:
        if not isinstance(row, dict) or not row.get('path'):
            continue
        path = locate_input(row['path'], bases)
        recorded = row.get('sha256')
        if row.get('role') == 'map_transcript_listing':
            current = transcript_listing_row(path)
            if current['sha256'] != recorded:
                change = ('added' if recorded is None else 'missing' if current['sha256'] is None else
                          'content changed')
                changes.append({'role': row.get('role'), 'path': row['path'], 'change': change})
            continue
        exists = path.is_file()
        if not exists and recorded is None:
            continue
        change = None
        if not exists:
            change = 'missing'
        elif recorded is None:
            change = 'added'
        else:
            stat = path.stat()
            if stat.st_size != row.get('bytes'):
                change = 'content changed'
            elif (thorough or stat.st_mtime_ns != row.get('mtime_ns')) and file_sha256(path) != recorded:
                change = 'content changed'
        if change:
            changes.append({'role': row.get('role'), 'path': row['path'], 'change': change})
    return changes


def valid_input_rows(rows):
    """Whether inputs are nonempty, well-formed fingerprints, including explicit absent-file records."""
    if not isinstance(rows, list) or not rows:
        return False
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('role'), str) or not row['role'].strip():
            return False
        if not isinstance(row.get('path'), str) or not row['path'].strip() or '\0' in row['path']:
            return False
        if not all(key in row for key in ('sha256', 'bytes', 'mtime_ns')):
            return False
        digest, size, stamp = row['sha256'], row['bytes'], row['mtime_ns']
        if digest is None:
            if size is not None or stamp is not None:
                return False
        elif not (isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest)
                  and type(size) is int and size >= 0 and type(stamp) is int):
            return False
    return True


def changes_text(changes, limit=4):
    """'cuts/v001/captions.srt changed, cuts/v001/lines.json missing': changed inputs in words."""
    words = {'content changed': 'changed', 'missing': 'missing', 'added': 'added since'}
    shown = [f"{Path(str(row.get('path'))).name if Path(str(row.get('path'))).is_absolute() else row.get('path')} "
             f"{words.get(row.get('change'), row.get('change'))}" for row in changes[:limit]]
    more = f' and {len(changes) - limit} more' if len(changes) > limit else ''
    return ', '.join(shown) + more


def checks_freshness(project, checks):
    """Compare input size and time, and recorded tools: (state, changes); unrecorded means no usable input record."""
    rows = checks.get('inputs') if isinstance(checks, dict) else None
    if not valid_input_rows(rows):
        return 'unrecorded', []
    changes = input_changes(rows, [project])
    if not valid_tools(checks.get('tools')):
        changes.append({'role': 'tool', 'path': 'tools', 'change': 'not recorded or invalid'})
    else:
        changes += [{'role': 'tool', 'path': row['tool'], 'change': 'content changed'}
                    for row in tool_changes(checks['tools'])]
    return ('out_of_date' if changes else 'current'), changes


REVIEW_KINDS = ('watched_muted', 'heard', 'names', 'approved')


def file_sha256(path):
    """The SHA-256 of a file's content."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def program_version(name):
    """A media tool's version line, or None when it cannot be read."""
    program = shutil.which(name)
    if not program:
        return None
    try:
        result = subprocess.run([program, '-version'], capture_output=True, text=True, encoding='utf-8',
                                errors='replace', timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.strip().splitlines()
    return lines[0].strip() if lines else None


def ffmpeg_version():
    """The installed FFmpeg version line."""
    return program_version('ffmpeg')


def ffprobe_version():
    """The installed FFprobe version line."""
    return program_version('ffprobe')


def package_version(name):
    """The installed package version, or None when it is unavailable."""
    try:
        import importlib.metadata as metadata
        return metadata.version(name)
    except Exception:
        return None


def required_packages(scripts):
    """Package versions that may affect the invoked scanners and transcript."""
    names = set(scripts)
    packages = set()
    if names & {'blank_scan.py', 'flash_scan.py', 'captions.py', 'transcribe.py', 'render_common.py'}:
        packages.add('numpy')
    if 'captions.py' in names:
        packages.add('Pillow')
    if 'transcribe.py' in names:
        packages.update(('ctranslate2', 'onnxruntime'))
    return packages


def valid_tools(recorded):
    """Whether a tool record identifies the environment and the scripts it needs to verify."""
    if not isinstance(recorded, dict):
        return False
    if not all(isinstance(recorded.get(key), str) and recorded[key]
               for key in ('skill_version', 'python', 'ffmpeg', 'ffprobe')):
        return False
    scripts = recorded.get('scripts')
    if not isinstance(scripts, dict) or not {'check.py', 'project.py'} <= set(scripts):
        return False
    for name, digest in scripts.items():
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.py', name):
            return False
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            return False
    if {'qc_file.py', 'transcribe.py'} & set(scripts) and 'render_common.py' not in scripts:
        return False
    packages = recorded.get('packages')
    if not isinstance(packages, dict) or not required_packages(scripts) <= set(packages):
        return False
    if any(not isinstance(name, str) or (value is not None and not isinstance(value, str))
           for name, value in packages.items()):
        return False
    whisper = recorded.get('faster_whisper')
    if whisper is not None:
        if not isinstance(whisper, dict) or not {'version', 'model'} <= set(whisper):
            return False
        if any(value is not None and not isinstance(value, str) for value in (whisper['version'], whisper['model'])):
            return False
    return 'faster_whisper' in recorded


def tool_changes(recorded):
    """Compare recorded tool versions and script hashes with this installation."""
    now = {'skill_version': skill_version(), 'python': platform.python_version(), 'ffmpeg': ffmpeg_version(),
           'ffprobe': ffprobe_version()}
    changes = [{'tool': key, 'was': recorded[key], 'now': value} for key, value in now.items()
               if recorded[key] != value]
    whisper = recorded.get('faster_whisper')
    if isinstance(whisper, dict) and whisper.get('version') != package_version('faster-whisper'):
        changes.append({'tool': 'faster-whisper', 'was': whisper.get('version'),
                        'now': package_version('faster-whisper')})
    for name, version in sorted(recorded['packages'].items()):
        current = package_version(name)
        if current != version:
            changes.append({'tool': 'package ' + name, 'was': version, 'now': current})
    for name, digest in sorted(recorded['scripts'].items()):
        path = Path(__file__).resolve().parent / name
        current = file_sha256(path) if path.is_file() else None
        if current != digest:
            changes.append({'tool': name, 'was': digest, 'now': current})
    return changes


def same_file(first, second):
    """Whether two paths name one file: the same path once resolved (case-folded where the system ignores case), or
    one existing file reached through a symbolic or hard link."""
    first, second = Path(first), Path(second)
    try:
        if first.exists() and second.exists() and os.path.samefile(first, second):
            return True
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


def refuse_overwriting_inputs(outputs, inputs):
    """Raise ValueError when an output path names an input (the same path, or a link to the same file), so a report
    never replaces the file it reports on. Empty entries are ignored."""
    for output in outputs:
        for given in inputs:
            if output and given and same_file(output, given):
                raise ValueError(f'the output {output} is the input {given}; write it to another file')


def transcript_media(data):
    """The media a transcript was made from, as its words.json records it: {'sha256', 'audio_stream', ...}, or None
    for a transcript written before transcripts recorded it."""
    media = data.get('media') if isinstance(data, dict) else None
    if isinstance(media, dict) and isinstance(media.get('sha256'), str):
        return media
    return None


def transcript_state(source, data):
    """Whether a source's transcript belongs to the source's current media: (state, reason). 'current': made from
    (or confirmed against) these bytes and this sound stream; 'stale': made from other bytes or another stream, until
    it is transcribed again or confirmed; 'unbound': an older transcript that does not say what it was made from."""
    media = transcript_media(data)
    if media is None:
        return 'unbound', 'the transcript does not record the media it was made from'
    if media['sha256'] != (source or {}).get('sha256'):
        return 'stale', (f"the transcript was made from other media (SHA-256 {media['sha256'][:12]}), not the source's "
                         f"current file ({str((source or {}).get('sha256'))[:12]})")
    stream = ((source or {}).get('audio') or {}).get('index')
    made = media.get('audio_stream')
    if stream is not None and made is not None and stream != made:
        return 'stale', f'the transcript was made from sound stream {made}, and the source now uses stream {stream}'
    if stream is None or made is None:
        return 'stale', ('the transcript or the source does not record which sound stream it is, so it cannot be '
                         'matched to the current stream')
    confirmation = media.get('confirmation') if isinstance(media.get('confirmation'), dict) else None
    if confirmation:
        return 'current', f"confirmed against the current file by {confirmation.get('by') or 'someone'}"
    return 'current', 'made from the current file'


def preview_identity(project, version, thorough=False):
    """The preview hash and whether its bytes differ from the rendered manifest; status may use recorded metadata."""
    folder = Path(project) / 'cuts' / version
    manifest = load_json(folder / 'manifest.json', {})
    known = (manifest.get('files') or {}).get('preview.mp4') if isinstance(manifest, dict) else None
    path = folder / 'preview.mp4'
    if not path.is_file():
        return None, bool(known)
    if not isinstance(known, str) or not re.fullmatch(r'[0-9a-f]{64}', known):
        return file_sha256(path), False
    if not thorough:
        checks = load_json(folder / 'checks.json', {}) or {}
        rows = checks.get('inputs', []) if isinstance(checks, dict) else []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict) or row.get('role') != 'preview' or row.get('sha256') != known:
                continue
            named = locate_input(row.get('path', ''), [project])
            if not same_file(named, path):
                continue
            stat = path.stat()
            if stat.st_size == row.get('bytes') and stat.st_mtime_ns == row.get('mtime_ns'):
                return known, False
            break
    actual = file_sha256(path)
    return (known, False) if actual == known else (None, True)


def preview_sha256(project, version):
    """The verified preview hash, or None if it is missing or changed since rendering."""
    return preview_identity(project, version)[0]


def review_applies(record, sha256, preview):
    """Whether a person's review record counts for a checked file: a record that names the reviewed file's SHA-256
    counts only for a file with that content; an older record without one counts only for the version's preview."""
    if not record:
        return False
    digest = record.get('sha256') if isinstance(record, dict) else None
    if digest:
        return digest == sha256
    return bool(preview)


def reviews_for(entry, sha256, preview):
    """The reviews in status.json reviewed[version] that count for one checked file: {kind: record}. Reviews of the
    preview sit under the kind; reviews of another file of the version sit under files[sha256][kind]."""
    entry = entry if isinstance(entry, dict) else {}
    found = {key: record for key, record in entry.items() if key != 'files' and review_applies(record, sha256, preview)}
    others = entry.get('files') if isinstance(entry.get('files'), dict) else {}
    for key, record in ((others.get(sha256) or {}) if sha256 else {}).items():
        if review_applies(record, sha256, preview):
            found.setdefault(key, record)
    return found


def record_review(project, version, kind, file=None, by='person'):
    """Record that a person reviewed a file of a version (the preview unless `file`): (record, already recorded)."""
    if not re.fullmatch(r'[a-z0-9_]{1,40}', str(kind)) or kind == 'files':
        raise ValueError(f'unknown review {kind!r}; for example one of {", ".join(REVIEW_KINDS)}')
    if not VERSION_NAME.match(version or '') or not (Path(project) / 'cuts' / version).is_dir():
        raise ValueError(f'no such version: {version}')
    path = Path(file) if file else Path(project) / 'cuts' / version / 'preview.mp4'
    if not path.is_file():
        raise ValueError(f'no file to record a review of: {path}')
    digest = file_sha256(path)
    preview, changed = preview_identity(project, version, thorough=True)
    preview_path = Path(project) / 'cuts' / version / 'preview.mp4'
    if changed and same_file(path, preview_path):
        raise ValueError('preview changed since it was rendered; render a new version before recording a review')
    try:
        name = path.resolve().relative_to(Path(project).resolve()).as_posix()
    except ValueError:
        name = path.name
    record = {'by': by, 'at': now(), 'file': name, 'sha256': digest}
    with file_lock(Path(project) / 'status.json'):
        status = read_status(project)
        entry = status.setdefault('reviewed', {}).setdefault(version, {})
        target = entry if digest == preview else entry.setdefault('files', {}).setdefault(digest, {})
        if review_applies(target.get(kind), digest, digest == preview):
            return target[kind], True
        target[kind] = record
        _update_status(project, {'reviewed': status['reviewed']})
    return record, False


def checked_summary(project, version, checks, entry):
    """A checks file's counts, with each person item a matching review has since covered no longer counted.

    The recorded inputs are revalidated first: when one changed, the summary carries `out_of_date` (the changes) and
    no counts, so an expired result is never read as passing; a checks file that records no inputs carries
    `inputs_recorded: False`."""
    state, changes = checks_freshness(project, checks)
    if state == 'out_of_date':
        return {'pass': 0, 'look': 0, 'fail': 0, 'you': 0, 'skip': 0, 'out_of_date': changes}
    summary = dict(checks.get('summary') or {})
    if checks.get('items'):
        digest = checks.get('sha256')
        preview_hash = preview_sha256(project, version)
        preview = preview_hash is not None and (digest == preview_hash or (digest is None and not checks.get('final')))
        applies = reviews_for(entry, digest, preview)
        if checks.get('final') and applies and not checked_final_matches(project, checks):
            applies = {}
        if not checks.get('final') and preview_hash is None:
            applies = {}
        summary = {key: 0 for key in ('pass', 'look', 'fail', 'you', 'skip')}
        for item in checks['items']:
            state_name = item.get('state')
            if state_name in summary and not (state_name == 'you' and applies.get(item.get('id'))):
                summary[state_name] += 1
    if state == 'unrecorded':
        summary['inputs_recorded'] = False
    return summary


def acceptance(project, version, entry, sha256=None):
    """A person's acceptance of one file of a version: the `approved` record that names its SHA-256 (the preview's
    when `sha256` is None; an older record without a hash counts for the preview only), or None."""
    files = entry.get('files') if isinstance(entry.get('files'), dict) else {}
    if not entry.get('approved') and not any(isinstance(row, dict) and row.get('approved') for row in files.values()):
        return None
    preview = preview_sha256(project, version)
    digest = sha256 or preview
    if not digest:
        return None
    record = reviews_for(entry, digest, digest == preview).get('approved')
    return record if record else None


def open_reviews(checks, applies):
    """The person items of a checks file that no matching review covers yet: [label]."""
    return [str(item.get('label') or item.get('id')) for item in (checks.get('items') or [])
            if isinstance(item, dict) and item.get('state') == 'you' and not applies.get(item.get('id'))]


def checked_final_matches(project, checks):
    """Hash the final actually named in its inputs before applying a review or acceptance."""
    digest = checks.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        return False
    rows = checks.get('inputs')
    paths = [row.get('path') for row in rows or [] if isinstance(row, dict) and row.get('role') == 'final']
    if not paths and checks.get('file'):
        paths = [checks['file']]
    if len(paths) != 1 or not isinstance(paths[0], str):
        return False
    path = locate_input(paths[0], [project])
    try:
        return path.is_file() and file_sha256(path) == digest
    except OSError:
        return False


def checks_report(project, version, name, entry):
    """One checks file as status --json reports it: the file checked, whether its result is current, what changed,
    its counts, the person items still open and the acceptance of the file it checked; None when it does not exist."""
    folder = Path(project) / 'cuts' / version
    try:
        checks = load_json(folder / name, None)
    except (OSError, ValueError):
        return {'file': None, 'state': 'unreadable', 'changed': [], 'summary': {}, 'open_reviews': []}
    if not isinstance(checks, dict):
        return None
    state, changes = checks_freshness(project, checks)
    digest = checks.get('sha256')
    preview_hash = preview_sha256(project, version)
    preview = preview_hash is not None and (digest == preview_hash or (digest is None and not checks.get('final')))
    applies = reviews_for(entry, digest, preview)
    if checks.get('final') and applies and not checked_final_matches(project, checks):
        applies = {}
    if not checks.get('final') and preview_hash is None:
        applies = {}
    summary = checked_summary(project, version, checks, entry)
    summary.pop('out_of_date', None)
    summary.pop('inputs_recorded', None)
    return {'file': checks.get('file'), 'sha256': digest, 'final': bool(checks.get('final')),
            'state': {'unrecorded': 'inputs_not_recorded'}.get(state, state), 'changed': changes,
            'summary': summary if state != 'out_of_date' else None, 'open_reviews': open_reviews(checks, applies),
            'approved': applies.get('approved') or None}


def open_notes(project, version):
    """The screening notes on a version that are still open: [{'id', 't', 'text'}]."""
    try:
        notes = load_json(Path(project) / 'notes.json', {}) or {}
    except (OSError, ValueError):
        return []
    rows = notes.get('notes') if isinstance(notes, dict) else None
    return [{'id': note.get('id'), 't': note.get('t'), 'text': note.get('text')} for note in rows or []
            if isinstance(note, dict) and note.get('version') == version and note.get('status', 'open') == 'open']


def status_report(project):
    """The status a reader gets, as four separate things that never stand in for each other: `progress` (stages: done
    means the work ran, not that it passed or was accepted), `checks` (the current version's preview and final
    checks: current, out_of_date or inputs_not_recorded, with what changed and their counts), `review` (person checks
    and screening notes still open) and `acceptance` (a person's approved record for the preview's SHA-256)."""
    status = read_status(project)
    version = current_version(project)
    entry = (status.get('reviewed') or {}).get(version) if version else None
    entry = entry if isinstance(entry, dict) else {}
    checks = checks_report(project, version, 'checks.json', entry) if version else None
    final = checks_report(project, version, 'checks-final.json', entry) if version else None
    preview = acceptance(project, version, entry) if version else None
    opened = []
    for report in (checks, final):
        for label in (report or {}).get('open_reviews') or []:
            if label not in opened:
                opened.append(label)
    return {'version': 1, 'project': Path(project).name, 'line': status_line(project), 'current': version,
            'progress': {'stage': status.get('stage'), 'stages': status.get('stages') or {},
                         'stage_notes': status.get('stage_notes') or {},
                         'running': status.get('running') or []},
            'checks': {'preview': checks, 'final': final},
            'review': {'open': opened, 'notes_open': open_notes(project, version) if version else []},
            'acceptance': {'preview': preview, 'final': (final or {}).get('approved')}}


def status_line(project, version=None):
    """The one line the agent posts in chat: the current version and its readiness, or the stage in progress. A
    checks result whose recorded inputs changed reads as out of date, naming what changed; `approved` is shown only
    for an approval recorded against the checked file's content."""
    status = read_status(project)
    current = version or current_version(project)
    if current and version is None:
        complete = []
        for name in versions(project):
            folder = Path(project) / 'cuts' / name
            if all((folder / part).is_file() for part in ('film.md', 'manifest.json', 'preview.mp4')):
                try:
                    if isinstance(load_json(folder / 'manifest.json'), dict):
                        complete.append(name)
                except (OSError, ValueError):
                    continue
        if not complete:
            current = None
        elif current not in complete:
            current = complete[-1]
    running = status.get('running') or []
    if running:
        job = running[0]
        progress = job.get('progress')
        share = f' {round(progress * 100)}%' if isinstance(progress, (int, float)) else ''
        return waiting_status(status, f"{job.get('job', 'working')}{share}")
    if current:
        folder = Path(project) / 'cuts' / current
        checks = load_json(folder / 'checks.json', None)
        final = load_json(folder / 'checks-final.json', None)
        label = 'v' + str(int(VERSION_NAME.match(current).group(1)))
        entry = status.get('reviewed', {}).get(current, {}) or {}
        entry = entry if isinstance(entry, dict) else {}
        # Acceptance is a person's record for the checked file's content, never a stage marked done.
        approved = acceptance(project, current, entry)
        _, preview_changed = preview_identity(project, current)
        approval = 'approved \u00b7 ' if approved else ''
        parts = []
        if isinstance(checks, dict):
            parts.append(f"{label} checked \u00b7 {approval}"
                         f"{readiness(checked_summary(project, current, checks, entry))}")
        if isinstance(final, dict):
            # A final check describes another file; its result is shown with the file it checked.
            final_report = checks_report(project, current, 'checks-final.json', entry)
            final_approval = 'approved \u00b7 ' if final_report and final_report.get('approved') else ''
            text = (f"final {final.get('file') or 'file'} checked \u00b7 {final_approval}"
                    f"{readiness(checked_summary(project, current, final, entry))}")
            parts.append(text if parts else f'{label} {approval}{text}')
        if preview_changed:
            parts.insert(0, f'{label} preview changed since it was rendered')
        if parts:
            return waiting_status(status, '; '.join(parts))
        if approved:
            return waiting_status(status, f'{label} approved · not checked yet')
        return waiting_status(status, f'{label} rendered · not checked yet')
    return waiting_status(status, status.get('line') or f"stage: {status.get('stage', 'map')}")


def init(project, title='', film=None):
    """Create the layout (map/, cuts/, screening/, deliver/) and a status.json; keeps anything already there. With
    film, the project starts from that paper edit; a different film.md already there stops it before any change."""
    project = Path(project)
    target = project / 'film.md'
    paper = Path(film).read_text(encoding='utf-8') if film is not None else None
    if paper is not None and target.exists() and target.read_text(encoding='utf-8') != paper:
        raise ValueError(f'{target} already exists and differs from {film}; nothing was changed. Choose a new '
                         'project folder, or move that film.md away first')
    for folder in ('map', 'cuts', 'screening', 'deliver'):
        (project / folder).mkdir(parents=True, exist_ok=True)
    with file_lock(project / 'status.json'):
        if not (project / 'status.json').is_file():
            save_json(project / 'status.json', default_status(title or project.name))
    with file_lock(project / 'notes.json'):
        if not (project / 'notes.json').is_file():
            save_json(project / 'notes.json', {'version': 1, 'notes': []})
    if paper is not None and not target.exists():
        write_atomic(target, paper)
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('init', help='create the layout and a status.json')
    create.add_argument('project')
    create.add_argument('--title', default='')
    create.add_argument('--film', help='start the project from this paper edit (refused when a different film.md '
                                       'is already there)')
    show = sub.add_parser('status', help='print the one-line status (--json: progress, checks, review, acceptance)')
    show.add_argument('project', nargs='?', default='.')
    show.add_argument('--json', action='store_true', help='print the status as separate fields, as JSON')
    stage = sub.add_parser('stage', help='record a stage as now, done or waiting for the person')
    stage.add_argument('project')
    stage.add_argument('stage', choices=STAGES)
    stage.add_argument('state', choices=('now', 'done', 'waiting'))
    stage.add_argument('--note', help='why this stage is waiting or what changed')
    review = sub.add_parser('review', help="record a person's review of a file (only when they say they did it)")
    review.add_argument('project')
    review.add_argument('kind', choices=REVIEW_KINDS)
    review.add_argument('--version', help='the version reviewed (default: the current one)')
    review.add_argument('--file', help='the file reviewed, when it is not the version\'s preview (a final file)')
    args = parser.parse_args()
    safe_output()
    try:
        if args.command == 'init':
            existing = read_status(args.project) if (Path(args.project) / 'status.json').is_file() else None
            folder = init(args.project, args.title, args.film)
            if existing is None:
                print(f'project ready: {folder}')
            else:
                kept = existing.get('title') or ''
                changed = f'; its title stays "{kept}"' if args.title and args.title != kept else ''
                print(f'already a project, kept as it was: {folder}{changed}')
            return 0
        folder = find_project(args.project)
        if folder is None:
            raise ValueError(f'no project folder at or above {args.project}')
        if args.command == 'stage':
            change_stage(folder, args.stage, args.state, args.note)
            # The saved line is what the Screening Room shows: a stage marked done must stop reading as waiting.
            line = status_line(folder)
            update_status(folder, line=line)
            print(line)
            return 0
        if args.command == 'review':
            version = args.version or current_version(folder)
            record, already = record_review(folder, version, args.kind, args.file)
            state = 'was already recorded' if already else 'recorded'
            print(f"{args.kind} {state} for {record['file']} ({version})")
            update_status(folder, line=status_line(folder))
            return 0
        if args.json:
            print(json.dumps(status_report(folder), indent=1, ensure_ascii=False))
            return 0
        print(status_line(folder))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
