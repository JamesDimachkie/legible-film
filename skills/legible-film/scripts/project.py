#!/usr/bin/env python3
"""Read and write a Legible Film project folder (references/project.md): paths, status, versions, aliases, times.

  python project.py init PROJECT [--title TITLE] [--film FILE] [--path PATH --timeline OWNER [--page DIR]]
                                                   create the layout and a status.json; --film starts the project
                                                   from that paper edit, and changes nothing when the folder
                                                   already has a different film.md; --path, --timeline and --page
                                                   write the project record into film.md's front matter
  python project.py status [PROJECT] [--json]      print the one-line status the agent posts in chat
  python project.py stage PROJECT STAGE now|done|waiting [--note TEXT]
                                                   record progress or a wait for the person
  python project.py review PROJECT KIND [--version vNNN] [--file FILE]
                                                   record a person's review of a file (KIND: watched_muted, heard,
                                                   names or approved); the version's preview unless --file

The project record (SPEC section 6) is film.md's front matter: path (create, cut, insert, sound, editor or quick),
timeline (page, paper, editor, picture, file or tesseract), page (the page folder when a page owns the timeline) and
frame (what, audience, why, knows_by with a state each: confirmed, assumed, missing or waived; waived with a reason;
cold_read). init writes it with every frame field missing unless --what, --audience or --why supply one, which then
reads as assumed until the person confirms it; edit the states in film.md. status prints
"timeline: page · context: 2 confirmed, 2 assumed" before the line, and status.json and status --json carry
timeline, path and context. check.py reads the frame from here.

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
    """The project's status, or a fresh one when status.json does not exist yet. An unreadable status.json (a write
    lost when a drive dropped can leave it the right size and full of zero bytes) is copied aside once as
    status.json.unreadable and replaced by a status rebuilt from cuts/current, which says what happened."""
    path = Path(project) / 'status.json'
    try:
        status = load_json(path, None)
    except (ValueError, UnicodeDecodeError):
        aside = path.with_name('status.json.unreadable')
        if not aside.exists():
            shutil.copy2(path, aside)
        status = default_status(Path(project).name)
        current = current_version(project)
        if current:
            status.update(current=current, stage='check',
                          stages={**status['stages'], 'map': 'done', 'plan': 'done', 'cut': 'done', 'check': 'now'})
        status['line'] = (f'status.json was unreadable and was rebuilt from the versions; the old file is kept as '
                          f'{aside.name}')
        return status
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


VERSION_QA_FILES = ('checks.json', 'checks-final.json')


def version_folder(path):
    """(version folder, path inside it) for a path inside cuts/vNNN holding manifest.json, through links, junctions
    and case; (None, None) otherwise."""
    for candidate in (Path(os.path.realpath(path)), Path(os.path.abspath(path))):
        for folder in [candidate] + list(candidate.parents):
            named = folder.parent.name.lower() == 'cuts' and VERSION_NAME.match(folder.name.lower())
            if named and (folder / 'manifest.json').is_file():
                return folder, candidate.relative_to(folder).as_posix()
    return None, None


def refuse_writing_versions(outputs, project=None):
    """Raise ValueError for an output inside a version folder: versions are immutable. The one exception is the QA
    files check.py writes there (qa/*, checks.json, checks-final.json), and only when `project` is the root that
    holds that version; a write under another project's version, or through a link into one, is refused."""
    root = os.path.normcase(os.path.realpath(project)) if project else None
    for output in outputs:
        if not output:
            continue
        folder, inside = version_folder(output)
        if folder is None:
            continue
        qa = inside.lower().startswith('qa/') or inside.lower() in VERSION_QA_FILES
        holder = os.path.normcase(os.path.realpath(folder.parent.parent))
        if qa and root and holder == root:
            continue
        raise ValueError(f'{output} is inside the version {folder}; versions are immutable: write it outside, or '
                         f'register a new version')


def refuse_overwriting_inputs(outputs, inputs, project=None, guard_versions=None):
    """Raise ValueError when an output path names an input (the same path, or a link to the same file), so a report
    never replaces the file it reports on. Empty entries are ignored.

    With `project` given (or guard_versions=True), outputs inside a version folder are refused too
    (refuse_writing_versions): only check.py's QA files, under the project root that holds the version, may be
    written there. Callers that write into versions by design keep the default."""
    for output in outputs:
        for given in inputs:
            if output and given and same_file(output, given):
                raise ValueError(f'the output {output} is the input {given}; write it to another file')
    if guard_versions or (guard_versions is None and project is not None):
        refuse_writing_versions(outputs, project)


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
    record = project_record(project)
    return {'version': 1, 'project': Path(project).name, 'line': status_line(project), 'current': version,
            'timeline': record.get('timeline'), 'path': record.get('path'),
            'context': frame_context(record.get('frame')),
            'progress': {'stage': status.get('stage'), 'stages': status.get('stages') or {},
                         'stage_notes': status.get('stage_notes') or {},
                         'running': status.get('running') or []},
            'checks': {'preview': checks, 'final': final},
            'review': {'open': opened, 'notes_open': open_notes(project, version) if version else []},
            'acceptance': {'preview': preview, 'final': (final or {}).get('approved')}}


def status_line(project, version=None):
    """The one-line status, after the project record's timeline and context when the project has a record."""
    line = _status_line(project, version)
    prefix = record_prefix(project)
    if prefix and not line.startswith(prefix):
        return prefix + ' \u00b7 ' + line
    return line


def _status_line(project, version=None):
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


def refresh_record_status(project):
    """Copy the record's timeline, path and context into status.json when they changed."""
    record = project_record(project)
    if not record.get('timeline') and not record.get('frame'):
        return
    fields = {'timeline': record.get('timeline'), 'path': record.get('path'),
              'context': frame_context(record.get('frame'))}
    status = read_status(project)
    if any(status.get(k) != v for k, v in fields.items()):
        update_status(project, **fields)


def record_only(path):
    """Whether a film.md holds nothing but a project record (no body, no other setting)."""
    try:
        text = read_text(path)
    except OSError:
        return False
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return False
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if end is None or any(line.strip() for line in lines[end + 1:]):
        return False
    tops = [re.match(r'([A-Za-z_][\w-]*):', line).group(1) for line in lines[1:end]
            if re.match(r'[A-Za-z_][\w-]*:', line)]
    return all(top in RECORD_KEYS for top in tops)


def init(project, title='', film=None, path=None, timeline=None, page=None, what=None, audience=None, why=None):
    """Create the layout (map/, cuts/, screening/, deliver/) and a status.json; keeps anything already there. With
    film, the project starts from that paper edit; a different film.md already there stops it before any change."""
    project = Path(project)
    target = project / 'film.md'
    paper = Path(film).read_text(encoding='utf-8') if film is not None else None
    record = project_record(project) if target.is_file() else {}
    if paper is not None and target.exists() and record_only(target):
        target.unlink()   # a record-only film.md: the paper edit comes in and the record is put back on top
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
    if path or timeline or page or what or audience or why or any(record.values()):
        if path is not None and path not in PATHS:
            raise ValueError(f'--path must be one of {", ".join(PATHS)}')
        if timeline is not None and timeline not in TIMELINES:
            raise ValueError(f'--timeline must be one of {", ".join(TIMELINES)}')
        current = project_record(project)
        merged = {k: record.get(k) or current.get(k) for k in RECORD_KEYS}
        frame = merged.get('frame') if isinstance(merged.get('frame'), dict) else empty_frame()
        for key, value in (('what', what), ('audience', audience), ('why', why)):
            if value:
                frame[key] = value
                frame.setdefault('state', {})[key] = 'assumed'
        merged.update(path=path or merged.get('path'), timeline=timeline or merged.get('timeline'),
                      page=(page.rstrip('/\\') + '/') if page else merged.get('page'), frame=frame)
        write_record(project, merged)
        refresh_record_status(project)
    return project


# ================================================================ the project record (film.md front matter)

PATHS = ('create', 'cut', 'insert', 'sound', 'editor', 'quick')
TIMELINES = ('page', 'paper', 'editor', 'picture', 'file', 'tesseract')
FRAME_FIELDS = ('what', 'audience', 'why', 'knows_by')
FRAME_STATES = ('confirmed', 'assumed', 'missing', 'waived')
RECORD_KEYS = ('path', 'timeline', 'page', 'frame')


def _strip_comment(text):
    """A value without a trailing # comment outside quotes."""
    quote = None
    for i, ch in enumerate(text):
        if quote:
            if ch == '\\' and quote == '"':
                continue
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == '#' and (i == 0 or text[i - 1] in ' \t'):
            return text[:i].rstrip()
    return text.rstrip()


class _Flow:
    """A reader for one YAML flow value: {a: b}, [x, y], quoted or plain scalars."""

    def __init__(self, text):
        self.text, self.i = text, 0

    def space(self):
        while self.i < len(self.text) and self.text[self.i] in ' \t':
            self.i += 1

    def value(self, stops=''):
        self.space()
        if self.i >= len(self.text):
            return None
        ch = self.text[self.i]
        if ch == '{':
            self.i += 1
            out = {}
            while True:
                self.space()
                if self.text[self.i:self.i + 1] == '}':
                    self.i += 1
                    return out
                key = self.value(':,}')
                self.space()
                if self.text[self.i:self.i + 1] != ':':
                    raise ValueError(f'a flow mapping needs key: value near {self.text[self.i:self.i + 20]!r}')
                self.i += 1
                out[str(key)] = self.value(',}')
                self.space()
                if self.text[self.i:self.i + 1] == ',':
                    self.i += 1
        if ch == '[':
            self.i += 1
            out = []
            while True:
                self.space()
                if self.text[self.i:self.i + 1] == ']':
                    self.i += 1
                    return out
                out.append(self.value(',]'))
                self.space()
                if self.text[self.i:self.i + 1] == ',':
                    self.i += 1
        if ch == '"':
            end = self.i + 1
            while end < len(self.text) and (self.text[end] != '"' or self.text[end - 1] == '\\'):
                end += 1
            raw = self.text[self.i:end + 1]
            self.i = end + 1
            return json.loads(raw)
        if ch == "'":
            end = self.text.index("'", self.i + 1)
            raw = self.text[self.i + 1:end]
            self.i = end + 1
            return raw
        start = self.i
        while self.i < len(self.text) and self.text[self.i] not in (stops or '\n'):
            self.i += 1
        return _scalar(self.text[start:self.i].strip())


def _scalar(text):
    if text in ('', '~', 'null', 'Null', 'NULL'):
        return None
    if text in ('true', 'True'):
        return True
    if text in ('false', 'False'):
        return False
    if re.fullmatch(r'-?\d+', text):
        return int(text)
    if re.fullmatch(r'-?\d+\.\d*', text):
        return float(text)
    return text


def parse_front_matter(text):
    """film.md's front matter as nested values: `key: value` lines, a key with an indented block under it, flow
    mappings and lists ({a: b}, [{s: 3, ...}]), quoted strings, comments. ({}, []) without front matter."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}
    block = []
    for line in lines[1:]:
        if line.strip() == '---':
            break
        block.append(line)

    def parse(rows, indent):
        out, i = {}, 0
        while i < len(rows):
            line = rows[i]
            if not line.strip() or line.lstrip().startswith('#'):
                i += 1
                continue
            depth = len(line) - len(line.lstrip(' '))
            key, sep, rest = line.strip().partition(':')
            if not sep:
                raise ValueError(f'front matter line is not "key: value": {line.strip()}')
            rest = _strip_comment(rest.strip())
            if rest:
                out[key.strip()] = _Flow(rest).value()
                i += 1
                continue
            child = []
            i += 1
            while i < len(rows) and (not rows[i].strip() or len(rows[i]) - len(rows[i].lstrip(' ')) > depth):
                child.append(rows[i])
                i += 1
            out[key.strip()] = parse(child, depth + 1) if any(r.strip() for r in child) else None
        return out

    return parse(block, 0)


def _yaml(value):
    """One value in the flow form parse_front_matter reads (JSON strings are YAML strings)."""
    if isinstance(value, dict):
        return '{' + ', '.join(f'{k}: {_yaml(v)}' for k, v in value.items()) + '}'
    if isinstance(value, list):
        return '[' + ', '.join(_yaml(v) for v in value) + ']'
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(str(value), ensure_ascii=False)


def empty_frame(what=None, audience=None, why=None):
    """The frame fields, each missing until supplied; a value supplied here is assumed until the person confirms."""
    values = {'what': what, 'audience': audience, 'why': why}
    return {**values, 'knows_by': [],
            'state': {**{k: ('assumed' if v else 'missing') for k, v in values.items()}, 'knows_by': 'missing'},
            'waived': None, 'cold_read': {'state': 'not-run'}}


def record_lines(record):
    """The project record as front-matter lines: path, timeline, page and the frame block."""
    lines = []
    for key in ('path', 'timeline', 'page'):
        if record.get(key):
            lines.append(f'{key}: {record[key]}')
    frame = record.get('frame')
    if isinstance(frame, dict):
        lines.append('frame:')
        for key in ('what', 'audience', 'why', 'knows_by', 'state', 'waived', 'cold_read'):
            if key in frame:
                lines.append(f'  {key}: {_yaml(frame[key])}')
    return lines


def write_record(project, record):
    """Put the record into film.md's front matter, replacing any earlier record keys and keeping every other line
    (a paper edit's settings and its body stay as they are). Creates a front-matter-only film.md when there is none."""
    path = Path(project) / 'film.md'
    text = read_text(path) if path.is_file() else ''
    lines = text.splitlines()
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if end is None:
            raise ValueError(f'{path}: the front matter is not closed')
        kept, skipping = [], False
        for line in lines[1:end]:
            top = re.match(r'([A-Za-z_][\w-]*):', line)
            if top and not line.startswith((' ', '\t')):
                skipping = top.group(1) in RECORD_KEYS
            if not skipping:
                kept.append(line)
        body = lines[end + 1:]
    else:
        kept, body = [], lines
    out = ['---'] + record_lines(record) + kept + ['---'] + body
    write_atomic(path, '\n'.join(out) + '\n')


def project_record(project):
    """{path, timeline, page, frame} from film.md's front matter; None for each key the record does not hold."""
    path = Path(project) / 'film.md'
    try:
        fields = parse_front_matter(read_text(path)) if path.is_file() else {}
    except (ValueError, json.JSONDecodeError):
        fields = {}
    return {key: fields.get(key) for key in RECORD_KEYS}


def frame_context(frame):
    """The frame's states counted: {'fields': {field: state}, 'confirmed': n, 'assumed': n, 'missing': n,
    'waived': reason or None, 'cold_read': state}; None when the project has no frame."""
    if not isinstance(frame, dict):
        return None
    given = frame.get('state') if isinstance(frame.get('state'), dict) else {}
    fields = {}
    for key in FRAME_FIELDS:
        state = given.get(key)
        if state not in FRAME_STATES:
            state = 'missing' if not frame.get(key) else 'assumed'
        fields[key] = state
    waived = frame.get('waived')
    reason = (waived.get('reason') if isinstance(waived, dict) else waived) if waived else None
    cold = frame.get('cold_read') if isinstance(frame.get('cold_read'), dict) else {}
    counts = {s: sum(1 for v in fields.values() if v == s) for s in FRAME_STATES}
    return {'fields': fields, **counts, 'waived': reason, 'cold_read': cold.get('state') or 'not-run'}


def context_text(context):
    """'context: 2 confirmed, 2 assumed' (zero counts left out), 'context: waived', or 'context: missing'."""
    if context is None:
        return 'context: missing'
    if context.get('waived'):
        return 'context: waived'
    parts = [f'{context[s]} {s}' for s in ('confirmed', 'assumed', 'missing') if context.get(s)]
    return 'context: ' + (', '.join(parts) or 'missing')


def record_prefix(project):
    """'timeline: page · context: 2 confirmed, 2 assumed' for a project with a record; '' without one."""
    record = project_record(project)
    if not record.get('timeline') and not record.get('frame'):
        return ''
    return f"timeline: {record.get('timeline') or 'not set'} · {context_text(frame_context(record.get('frame')))}"


# ================================================================ registering a master (add-version)

ADD_VERSION_HELP = """Register a master rendered outside cut.py as an immutable version, bound to its cue list.

  python project.py add-version PROJECT --cues film/cues.json --render "npx hyperframes render {page} -o {out}" \\
      --file renders/v1.mp4 [--sound audio/mix/mix.wav]
  python project.py add-version PROJECT --cues film/cues.json --file renders/film_1920x1080.mp4 \\
      --receipt renders/film_1920x1080.mp4.manifest.json
  python project.py add-version PROJECT --cues film/cues.json --file master.mp4 [--accept-older "reason"]
  python project.py add-version PROJECT --cues plan.json --file returned.mp4      (a plan list: bound here)

Copies the master as cuts/vNNN/preview.mp4 without re-encoding (a remux to MP4 when it is another container), and
writes a front-matter-only film.md, picture-timing.json, the list (cues.json, its page path re-expressed from the
version) and manifest.json with its identity, so check.py, screen.py, grade.py and compare_versions.py read it like
any version. The binding says how the master is tied to its source:

  receipt     --render: CMD must name {page} and {out}. The kept frozen copy the list names
              (PAGE/.lf-frozen/<snapshot_sha256>/) must hold exactly its recorded files, byte for byte, and the live
              page must still equal the list's source_files. CMD runs under with_lock.py with {page} the kept copy
              and {out} OUT (under PAGE/renders/ or outside the page), with outbound network blocked: every Node
              process gets render_block.cjs, every browser it launches goes through a local refusing proxy, npm and
              npx run offline (a cached engine resolves; npx with an uncached package fails), and other programs get
              the proxy variables. OUT counts only when CMD exits 0, OUT is newer than the
              start and CMD's output names it. The page is checked again after the render. render_trace: blocked,
              or none (binding unverified) when no Node process ran under the block.
              --receipt R: a kit render's OUTPUT.manifest.json (film_render.py --cues). Its fingerprint, snapshot
              and per-file byte hashes must match the list and the kept copy; its pre-rewrite digests must rebuild
              its fingerprint; the master's picture stream, geometry and frame schedule must match one of its
              entries (the file delivered, never the lossless intermediate).
              A picture list (observed anchors): the master's picture stream and schedule equal the list's.
  screened    neither: the master is newer than every page file the fingerprint covers.
  overridden  older, accepted by --accept-older "reason" (recorded in decisions.jsonl).
  unverified  the binding cannot be checked: the export or the render was not shown closed, the receipt lacks
              pre-rewrite digests or lf1 digests or is not traced, or a display transform is not a quarter turn
              or flip. Registered, never counted as receipt.
  plan-bound  a plan list: each turn is screened for a frame change on the decoded master (a turn with none is
              a look), and a bound copy (kind picture) is written.

A mismatch is refused, never registered. --sound WAV muxes WAV onto the master with the picture stream copied
(audio padded, -t at the picture's length, never -shortest), only when the mixer's mix-report.json (beside WAV, or
--mix-report) lists WAV's hash among its outputs and the list's hash among its inputs; manifest mix records both.
The manifest's cues_provenance copies the list's provenance (exported or observed; plan-bound for a bound plan).
A new picture marks open notes on earlier versions. --stems DIR copies stems into cuts/vNNN/stems/. Inside a job that already holds the heavy
lock (the full self-test under with_lock.py), the render takes it as already held.
Exit 0 registered; 1 registered with a look (unverified, a turn with no frame change); 2 refused.
"""

PRUNE_HELP = """Remove kept frozen copies (PAGE/.lf-frozen/<snapshot>/) that no cue list and no version names."""


def _sibling(name):
    """A sibling script loaded as a module (cue_list, with_lock), once."""
    key = 'lf_' + name + '_for_project'
    if key not in sys.modules:
        import importlib.util
        spec = importlib.util.spec_from_file_location(key, Path(__file__).with_name(name + '.py'))
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return sys.modules[key]


class Refused(ValueError):
    """add-version refuses the registration (exit 2)."""


def front_matter_block(text):
    """(fields, raw lines) of a film.md front matter: top-level `key: value` scalars only."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return {}, []
    raw = []
    for line in lines[1:]:
        if line.strip() == '---':
            break
        raw.append(line)
    fields = {}
    for line in raw:
        m = re.match(r'([A-Za-z_][\w-]*):\s*(.*?)\s*(?:#.*)?$', line)
        if m and not line.startswith((' ', '\t')):
            fields[m.group(1)] = m.group(2).strip('"\'')
    return fields, raw


def _sink_server():
    """A local proxy that records every request and refuses it: the browser side of the render block."""
    import socketserver
    import threading

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                self.request.settimeout(5)
                data = b''
                while b'\r\n' not in data and len(data) < 8192:
                    chunk = self.request.recv(2048)
                    if not chunk:
                        break
                    data += chunk
                line = data.split(b'\r\n', 1)[0].decode('latin-1', 'replace').strip()
                if line:
                    self.server.seen.append(line[:300])
                self.request.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = Server(('127.0.0.1', 0), Handler)
    server.seen = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _quote(path):
    return '"' + str(path) + '"' if os.name == 'nt' else shlex.quote(str(path))


def _names_output(text, out, given):
    """Whether a command's output names OUT: its absolute path, the path as given, or the path from here."""
    norm = (lambda s: s.replace('\\', '/').lower()) if os.name == 'nt' else (lambda s: s.replace('\\', '/'))
    hay = norm(text)
    forms = {norm(str(Path(out).resolve())), norm(given)}
    try:
        forms.add(norm(os.path.relpath(Path(out).resolve(), Path.cwd())))
    except ValueError:
        pass
    return any(f and f in hay for f in forms)


def _copy_changes(cl, problems, frozen_files):
    """verify_frozen's problems without the files an engine writes into the project it renders under a top-level
    entry the page identity excludes (renders/, snapshots/, dist/, coverage/); verify_frozen skips dot entries."""
    tops = {rel.split('/', 1)[0] for rel in frozen_files}
    kept = []
    for problem in problems:
        extra = re.match(r'not in the snapshot: (.+)$', problem)
        if extra:
            top = extra.group(1).split('/', 1)[0]
            if top not in tops and cl.excluded_top(top, '/' in extra.group(1)):
                continue
        kept.append(problem)
    return kept


def _live(cl_module, cues, page, during=False):
    """Refuse unless the live page's exact files still equal the list's source_files."""
    state = cl_module.check(cues, owner=page)
    if state.state == 'stale':
        if during:
            raise Refused('the page changed during the render; re-export and render again (' + state.message + ')')
        message = state.message
        if 'line endings' not in message:
            message = 'the page changed since export; re-export (' + message + ')'
        raise Refused(message)
    return state


def _hashes_in(value):
    """Every SHA-256 a mixer report records under a key, whatever its shape."""
    found = set()
    if isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value):
        found.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            found |= _hashes_in(v)
    elif isinstance(value, list):
        for v in value:
            found |= _hashes_in(v)
    return found


def _mix_binding(wav, report_path, cues_sha256):
    report_path = Path(report_path) if report_path else Path(wav).with_name('mix-report.json')
    if not report_path.is_file():
        raise Refused(f'--sound needs the mixer report {report_path} (or give --mix-report)')
    report = load_json(report_path, {}) or {}
    sound_sha = file_sha256(wav)
    if sound_sha not in _hashes_in(report.get('outputs')):
        raise Refused(f'{wav} is not among the outputs {report_path.name} records; remix, or name its report')
    if cues_sha256 not in _hashes_in(report.get('inputs')):
        raise Refused(f'{report_path.name} was mixed from another cue list; remix against this list')
    return {'report_sha256': file_sha256(report_path), 'sound_sha256': sound_sha, 'report': str(report_path)}


def _ffmpeg():
    tool = shutil.which(os.environ.get('FFMPEG') or 'ffmpeg')
    if not tool:
        raise Refused('FFmpeg is needed to register a master')
    return tool


def _mux(master, wav, target, seconds):
    """Video copied; AAC-LC 48 kHz 256 kbps; apad and -t at the picture's exact length; never -shortest."""
    r = subprocess.run([_ffmpeg(), '-hide_banner', '-v', 'error', '-nostdin', '-n', '-i', str(master), '-i', str(wav),
                        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-af', 'apad', '-c:a', 'aac',
                        '-profile:a', 'aac_low', '-ar', '48000', '-b:a', '256k', '-t', f'{seconds:.6f}',
                        '-movflags', '+faststart', '-movie_timescale', '48000', str(target)],
                       capture_output=True, text=True)
    if r.returncode:
        raise Refused('the mux failed: ' + r.stderr.strip()[-400:])


def _remux_mp4(master, target):
    r = subprocess.run([_ffmpeg(), '-hide_banner', '-v', 'error', '-nostdin', '-n', '-i', str(master), '-map', '0',
                        '-c', 'copy', '-movflags', '+faststart', str(target)], capture_output=True, text=True)
    if r.returncode:
        raise Refused('could not copy the master into an MP4 without re-encoding: ' + r.stderr.strip()[-400:])


def _same_picture(cl, a, b):
    """'' when two identities are the same picture (packets, display, schedule), else the difference."""
    if a['sha256'] != b['sha256']:
        return 'the picture stream differs (packet hash)'
    state, reason = cl.geometry_compare(a['geometry'], b['geometry'])
    if state == 'changed':
        return reason
    if a['schedule'] and b['schedule']:
        return cl.compare_schedules(a['schedule'], b['schedule'], a.get('fps_exact'))
    return ''


def screen_turns(master, schedule, events):
    """The §8 screen at each turn: the decoded master's frame-to-frame difference within one frame of t against
    three times the median difference over the surrounding second. [{id, t, frame, change, median, changed}]."""
    import numpy as np
    turns = [ev for ev in events if ev.get('scale') == 'turn' and ev.get('picture') not in ('none', 'held')]
    if not turns:
        return []
    width = 160
    probe = subprocess.run([shutil.which('ffprobe') or 'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_entries', 'stream=width,height', '-of', 'csv=p=0', str(master)],
                           capture_output=True, text=True).stdout.strip().split(',')
    w0, h0 = int(probe[0]), int(probe[1])
    height = max(2, int(round(h0 * width / w0 / 2)) * 2)
    raw = subprocess.run([_ffmpeg(), '-v', 'error', '-nostdin', '-i', str(master), '-map', '0:v:0',
                          '-vf', f'scale={width}:{height},format=gray', '-fps_mode', 'passthrough',
                          '-f', 'rawvideo', '-'], capture_output=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, height, width).astype(np.float32)
    diffs = np.zeros(len(frames))
    diffs[1:] = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    pts = np.array(schedule['pts_us'], dtype=np.float64) / 1e6 if schedule else np.arange(len(frames)) / 30
    fps = len(pts) / max(1e-9, (pts[-1] - pts[0])) if len(pts) > 1 else 30
    half = max(1, int(round(fps / 2)))
    out = []
    for ev in turns:
        k = int(np.argmin(np.abs(pts[:len(frames)] - float(ev['t']))))
        near = diffs[max(1, k - 1):min(len(diffs), k + 2)]
        change = float(near.max()) if len(near) else 0.0
        window = diffs[max(1, k - half):min(len(diffs), k + half + 1)]
        median = float(np.median(window)) if len(window) else 0.0
        out.append({'id': ev['id'], 't': ev['t'], 'frame': k, 'change': round(change, 4), 'median': round(median, 4),
                    'changed': bool(change > 3 * median and change > 0.5)})
    return out


def run_render(cmd, copy_dir, out, min_free_gib, wait_min):
    """Run an engine CMD with {page} and {out} filled, under the heavy lock, with outbound network blocked."""
    lock_module = _sibling('with_lock')
    lock = lock_module.HeavyLock(min_free_gib=min_free_gib, wait_min=wait_min, label='add-version')
    filled = cmd.replace('{page}', _quote(copy_dir)).replace('{out}', _quote(out))
    sink = _sink_server()
    handle, name = tempfile.mkstemp(prefix='lf-block-', suffix='.jsonl')
    os.close(handle)
    log = Path(name)
    try:
        lock.acquire()   # inside a job that already holds it (the full self-test), it proceeds at once
    except lock_module.LockTimeout as error:
        sink.shutdown()
        sink.server_close()
        log.unlink(missing_ok=True)
        raise Refused(f'the render did not start: {error}') from None
    env = lock.child_env() if lock.held else dict(os.environ)
    preload = Path(__file__).with_name('render_block.cjs').resolve().as_posix()
    env['NODE_OPTIONS'] = f'--require "{preload}"' + (' ' + env['NODE_OPTIONS'] if env.get('NODE_OPTIONS') else '')
    url = f'http://127.0.0.1:{sink.server_address[1]}'
    for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
        env[key] = url
    env['NO_PROXY'] = env['no_proxy'] = 'localhost,127.0.0.1,::1'
    env.update(LF_BLOCK_PROXY=url, LF_BLOCK_LOG=str(log), HF_CLI_TELEMETRY_DISABLED='1', DO_NOT_TRACK='1')
    # npm and npx run offline: a cached engine resolves from the cache, one that is not cached fails, and no
    # registry lookup reaches the block (npm stops on the sink's refusal, where it would fall back offline).
    env.update(npm_config_offline='true', npm_config_update_notifier='false', npm_config_audit='false',
               npm_config_fund='false')
    held = 'inherited from the job that holds it' if lock.inherited else str(lock.path)
    try:
        started = time.time()
        stamp = now()
        try:
            r = subprocess.run(filled, shell=True, env=env, capture_output=True, text=True, encoding='utf-8',
                               errors='replace')
        finally:
            lock.release()
        rows = []
        for line in log.read_text(encoding='utf-8', errors='replace').splitlines() if log.is_file() else []:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return {'returncode': r.returncode, 'output': (r.stdout or '') + (r.stderr or ''), 'started': started,
                'started_at': stamp, 'ended_at': now(), 'filled': filled, 'lock': held,
                'nodes': sum(1 for x in rows if x.get('event') == 'node'),
                'browsers': [x.get('exe') for x in rows if x.get('event') == 'browser'],
                'refused': [f"{x.get('host')}:{x.get('port')}" for x in rows if x.get('event') == 'refused'],
                'proxied': list(sink.seen)}
    finally:
        sink.shutdown()
        sink.server_close()
        log.unlink(missing_ok=True)


def _receipt_binding(cl, listed, receipt_path, record, master_id):
    """(binding, reasons, entry) for a kit receipt; raises Refused on any mismatch."""
    receipt = load_json(receipt_path, None)
    if not isinstance(receipt, dict) or not all(k in receipt for k in ('source_fingerprint', 'frozen', 'entries')):
        return None, [f'{Path(receipt_path).name} is not a receipt (no source_fingerprint, frozen files or entries): '
                      'falls to the screen'], None
    picture = listed.picture
    if receipt['source_fingerprint'] != picture['sha256']:
        raise Refused('the receipt fingerprint is not the list\'s page fingerprint')
    if receipt.get('snapshot_sha256') != picture['snapshot_sha256']:
        raise Refused('the receipt was rendered from another snapshot than the list names')
    frozen = receipt['frozen']
    byte_hashes = {rel: (row.get('sha256') if isinstance(row, dict) else row) for rel, row in frozen.items()}
    if cl.snapshot_hash(byte_hashes) != picture['snapshot_sha256']:
        raise Refused('the receipt\'s per-file byte hashes do not rebuild the list\'s snapshot (a different file set '
                      'or different bytes)')
    if record is None:
        raise Refused(f"the kept copy {cl.FROZEN_DIR}/{picture['snapshot_sha256']} is missing, so the receipt's files "
                      'cannot be checked; export again')
    if byte_hashes != record['frozen_files']:
        raise Refused('the receipt\'s frozen files differ from the kept copy\'s')
    reasons = list(receipt.get('binding_reasons') or [])
    digests = receipt.get('source_digests')
    if receipt.get('digest') != cl.DIGEST:
        reasons.append(f"the receipt uses digest {receipt.get('digest')!r}, not {cl.DIGEST}")
    elif not all(isinstance(row, dict) and row.get('file_digest') for row in frozen.values()):
        reasons.append('the receipt holds byte hashes only (no file_digest per frozen file)')
    if not isinstance(digests, dict) or not digests:
        reasons.append('the receipt lacks the page\'s pre-rewrite file digests')
    else:
        vendored = {v['url']: v['sha256'] for v in receipt.get('vendored') or []}
        rebuilt = cl.fingerprint_from_digests(digests, vendored)
        if rebuilt != receipt['source_fingerprint']:
            raise Refused('the receipt\'s per-file digests do not reproduce its fingerprint')
    if receipt.get('render_trace') != 'traced':
        reasons.append(f"the render was not traced (render_trace {receipt.get('render_trace')!r})")
    entry = next((e for e in receipt['entries'] if e.get('picture_sha256') == master_id['sha256']), None)
    if entry is None:
        raise Refused('the master\'s picture stream is not one the receipt recorded (each step that writes a picture '
                      'appends its own entry; a muxed master binds through its picture-stream hash)')
    state, reason = cl.geometry_compare(entry.get('geometry'), master_id['geometry'])
    if state == 'changed':
        raise Refused(f'the master displays differently from the render ({reason})')
    if state == 'unverified':
        reasons.append(reason)
    if entry.get('schedule') and master_id['schedule']:
        difference = cl.compare_schedules(entry['schedule'], master_id['schedule'], entry.get('fps_exact'))
        if difference:
            raise Refused(f'the master\'s frame timing differs from the render ({difference})')
    else:
        reasons.append('a frame schedule is missing, so timing cannot be compared')
    return ('unverified' if reasons else 'receipt'), reasons, dict(entry, receipt=str(receipt_path))


def add_version(args):
    """project.py add-version: returns the exit code; raises Refused for a registration it will not make."""
    cl = _sibling('cue_list')
    root = Path(args.project)
    if not any((root / m).exists() for m in MARKERS):
        init(root)
    root = root.resolve()
    film_fields, film_raw = front_matter_block(read_text(root / 'film.md')) if (root / 'film.md').is_file() else ({}, [])
    master = Path(args.file) if args.file else None
    if args.render and not ('{page}' in args.render and '{out}' in args.render):
        raise Refused('--render CMD must name {page} and {out}: an engine\'s default output is a timestamped file that '
                      'cannot be told apart from an older render')
    if args.render and args.receipt:
        raise Refused('give --render or --receipt, not both')
    if master is None:
        raise Refused('--file MASTER (or OUT with --render) is required')
    try:
        listed = cl.check(args.cues)
    except cl.CueListError as error:
        raise Refused(str(error)) from None
    kind = listed.kind if listed.version == 'v2' else None
    if kind not in ('page', 'picture', 'plan'):
        raise Refused('add-version registers against a v2 page, picture or plan list' +
                      (' (a paper version is registered by cut.py render)' if kind == 'paper' else ''))
    provenance = getattr(listed, 'provenance', None) or listed.doc.get('provenance', 'exported')
    reasons, notes, screen, receipt_rows, render_trace, entry, mix = [], [], [], None, None, None, None
    page = record = None
    if kind == 'page':
        page = Path(args.page) if args.page else (root / film_fields['page']) if film_fields.get('page') else             Path(listed.owner or '')
        if not str(page) or not page.is_dir():
            raise Refused('the page folder is not found: give --page DIR or page: in film.md')
        page = page.resolve()
        state = _live(cl, args.cues, page)
        if state.state == 'unverified':
            reasons.append(state.message)
        if listed.doc.get('binding') == 'unverified':
            reasons += [f'export: {r}' for r in listed.doc.get('binding_reasons') or ['not shown closed']]
        snapshot = listed.picture['snapshot_sha256']
        record = cl.frozen_record(page, snapshot)
    elif args.render or args.receipt:
        raise Refused('--render and --receipt bind a page list; a picture or plan list binds by the master itself')
    project_inputs = [args.cues, args.sound, args.receipt, args.mix_report] + ([] if args.render else [master])
    refuse_overwriting_inputs([root / 'cuts' / next_version(root)], [x for x in project_inputs if x], project=root)
    work = Path(tempfile.mkdtemp(prefix='.tmp-add-', dir=str(root / 'cuts')))
    try:
        if args.render:
            out = master.resolve()
            if (out == page or page in out.parents) and not ((page / 'renders') in out.parents):
                raise Refused('OUT must be under the page\'s renders/ or outside the page')
            refuse_writing_versions([out], root)
            if out.exists():
                raise Refused(f'{out} already exists: name a new OUT so an older render cannot be taken for this one')
            if record is None:
                raise Refused(f'the kept copy {cl.FROZEN_DIR}/{snapshot} the list names is missing; export again')
            copy_dir = page / cl.FROZEN_DIR / snapshot
            problems = _copy_changes(cl, cl.verify_frozen(copy_dir, record['frozen_files'], snapshot),
                                     record['frozen_files'])
            if problems:
                raise Refused('the kept copy differs from the export snapshot (' + '; '.join(problems[:5]) +
                              '); export again')
            out.parent.mkdir(parents=True, exist_ok=True)
            ran = run_render(args.render, copy_dir, out, args.min_free_gib, args.wait_min)
            if ran['returncode']:
                raise Refused(f"the render command exited {ran['returncode']}: " + ran['output'].strip()[-600:])
            if not out.is_file() or out.stat().st_mtime < ran['started'] - 1:
                raise Refused(f'the render command did not write {out}')
            if not _names_output(ran['output'], out, str(master)):
                raise Refused(f'the render command\'s output does not name {out}, so it cannot be shown to be this '
                              'render\'s file')
            _live(cl, args.cues, page, during=True)
            after = _copy_changes(cl, cl.verify_frozen(copy_dir, record['frozen_files'], snapshot),
                                  record['frozen_files'])
            if after:
                raise Refused('the kept copy changed during the render (' + '; '.join(after[:5]) + ')')
            render_trace = 'blocked' if ran['nodes'] else 'none'
            if render_trace == 'none':
                reasons.append('no Node process ran under the network block, so the render was neither traced nor '
                               'blocked (render_trace: none)')
            for attempt in ran['refused'] + ran['proxied']:
                reasons.append(f'the render tried to reach the network (blocked): {attempt}')
            receipt_rows = {'command': args.render, 'ran': ran['filled'], 'source_fingerprint': listed.picture['sha256'],
                            'snapshot_sha256': snapshot, 'cues_sha256': listed.sha256, 'digest': cl.DIGEST,
                            'frozen': {rel: {'sha256': sha, 'file_digest': cl.file_digest(copy_dir / rel)}
                                       for rel, sha in record['frozen_files'].items()},
                            'output': str(out), 'output_sha256': file_sha256(out),
                            'started': ran['started_at'], 'ended': ran['ended_at'], 'render_trace': render_trace,
                            'block': {'mechanism': 'render_block.cjs in NODE_OPTIONS: Node sockets off loopback '
                                                   'refused; each browser Node launches gets --proxy-server to a '
                                                   'local refusing sink and a host-resolver rule; HTTP(S)_PROXY and '
                                                   'ALL_PROXY for other programs',
                                      'node_processes': ran['nodes'], 'browsers': ran['browsers'],
                                      'refused': ran['refused'], 'proxied': ran['proxied']},
                            'lock': ran['lock']}
        picture_file = master.resolve()
        if not picture_file.is_file():
            raise Refused(f'no master at {picture_file}')
        picture_id = cl.picture_identity(picture_file)
        if args.sound:
            mix = _mix_binding(args.sound, args.mix_report, listed.sha256)
            if picture_id['schedule'] is None:
                raise Refused('the master\'s picture has no timestamps, so the sound cannot be muxed to its length')
            seconds = (picture_id['schedule']['visible_end_us'] - picture_id['schedule']['visible_start_us']) / 1e6
            muxed = work / 'muxed.mp4'
            _mux(picture_file, args.sound, muxed, seconds)
            muxed_id = cl.picture_identity(muxed)
            if muxed_id['sha256'] != picture_id['sha256']:
                raise Refused('the mux changed the picture stream')
            picture_file, picture_id = muxed, muxed_id
        if receipt_rows is not None:
            receipt_rows.update(picture_sha256=picture_id['sha256'], geometry=picture_id['geometry'],
                                pts_sha256=cl.schedule_sha256(picture_id['schedule']) if picture_id['schedule'] else None)
            if mix:
                receipt_rows['sound'] = mix
        if picture_id['geometry'].get('transform') is None:
            reasons.append('the display transform is not a quarter turn or flip, so it is compared exactly')
        if picture_id['untimed']:
            reasons.append('untimed: the picture stream carries no packet timestamps')
        binding = None
        if kind == 'page' and args.render:
            binding = 'unverified' if reasons else 'receipt'
        elif kind == 'page' and args.receipt:
            binding, extra, entry = _receipt_binding(cl, listed, args.receipt, record, picture_id)
            reasons += extra
            if binding == 'receipt' and reasons:
                binding = 'unverified'
            render_trace = (load_json(args.receipt, {}) or {}).get('render_trace')
        if kind == 'page' and binding is None:
            newest = max(((page / rel).stat().st_mtime for rel in cl.page_files(page)), default=0)
            if master.stat().st_mtime > newest:
                binding = 'screened'
            elif args.accept_older:
                binding = 'overridden'
            else:
                raise Refused('the master is older than the page it should show (a file changed after it was '
                              'rendered); render again, or pass --accept-older "reason" to record the decision')
        if kind == 'picture':
            state = cl.check(args.cues, owner=picture_file)
            if state.state == 'stale':
                raise Refused('the master is not the list\'s picture: ' + state.message)
            reasons += state.reasons
            binding = 'receipt' if state.state == 'fresh' and not reasons else 'unverified'
        if binding in ('receipt', 'screened', 'overridden') and picture_id['geometry'].get('transform') is None:
            binding = 'unverified'   # a display transform other than quarter turns and flips cannot be checked
        if kind == 'plan':
            screen = screen_turns(picture_file, picture_id['schedule'], listed.events)
            binding = 'plan-bound'
            for row in screen:
                if not row['changed']:
                    notes.append(f"look: no frame change at turn {row['id']} ({row['t']} s, frame {row['frame']})")
        with file_lock(root / 'cuts' / 'versions'):
            name = next_version(root)
            parent = current_version(root)
            staging = work / name
            staging.mkdir()
            preview = staging / 'preview.mp4'
            if picture_file.suffix.lower() == '.mp4':
                shutil.copyfile(picture_file, preview)
            else:
                _remux_mp4(picture_file, preview)
            preview_id = cl.picture_identity(preview)
            difference = _same_picture(cl, picture_id, preview_id)
            if difference:
                raise Refused('copying the master into the version changed its picture: ' + difference)
            if preview_id['schedule'] is not None:
                cl.write_schedule(preview_id['schedule'], staging / 'picture-timing.json')
            fields = dict(film_fields)
            timeline = {'page': 'page', 'picture': 'picture', 'plan': fields.get('timeline') or 'tesseract'}[kind]
            lines = [line for line in film_raw if not re.match(r'(timeline|page|registered|version):', line)]
            lines = [f'timeline: {fields.get("timeline") or timeline}'] + (
                [f'page: {os.path.relpath(page, root).replace(os.sep, "/")}/'] if page else []) + lines
            lines += [f'version: {name}', 'registered: true']
            (staging / 'film.md').write_bytes(('---\n' + '\n'.join(lines) + '\n---\n').encode('utf-8'))
            doc = json.loads(json.dumps(listed.doc))
            if kind == 'page':
                doc['picture']['path'] = os.path.relpath(page, root / 'cuts' / name).replace(os.sep, '/') + '/'
            elif kind == 'picture':
                timing = (doc['picture'].get('timing') or {})
                if timing.get('pts_file'):
                    shutil.copyfile(Path(args.cues).resolve().parent / timing['pts_file'], staging / timing['pts_file'])
                doc['picture']['path'] = 'preview.mp4'
            else:
                doc['picture'] = {'kind': 'picture', 'path': 'preview.mp4', 'sha256': preview_id['sha256'],
                                  'geometry': preview_id['geometry'],
                                  'timing': cl.timing_block(preview_id['schedule'])}
                doc['provenance'] = provenance = 'plan-bound'   # the bound copy is kind picture
                doc['bound'] = {'from': 'plan', 'by': 'project.py add-version', 'screen': screen}
            save_json(staging / 'cues.json', doc)
            if receipt_rows is not None:
                receipt_rows['binding'] = binding
                receipt_rows['binding_reasons'] = reasons
                save_json(staging / 'receipt.json', receipt_rows)
            if args.stems:
                (staging / 'stems').mkdir()
                for stem in sorted(Path(args.stems).glob('*.wav')):
                    shutil.copyfile(stem, staging / 'stems' / stem.name)
            if page:
                source = {'kind': 'page', 'path': os.path.relpath(page, root).replace(os.sep, '/') + '/',
                          'sha256': listed.picture['sha256'], 'snapshot_sha256': listed.picture['snapshot_sha256']}
            elif kind == 'picture':
                source = {'kind': 'picture', 'sha256': listed.picture['sha256']}
            else:
                source = {'kind': 'plan', 'sha256': None}
            identity = {'source': source, 'picture_sha256': preview_id['sha256'],
                        'picture_timing': cl.timing_block(preview_id['schedule']),
                        'geometry': preview_id['geometry'], 'binding': binding, 'binding_reasons': reasons,
                        'render_trace': render_trace,
                        'receipt': 'receipt.json' if receipt_rows is not None else (str(Path(args.receipt).resolve())
                                                                                     if args.receipt else None),
                        'receipt_entry': {k: entry[k] for k in ('step', 'file', 'picture_sha256', 'pts_sha256')}
                                         if entry else None,
                        'cues': 'cues.json', 'cues_sha256': listed.sha256, 'cues_provenance': provenance,
                        'conform_sha256': None,
                        'mix': {k: mix[k] for k in ('report_sha256', 'sound_sha256')} if mix else None,
                        'screen': screen or None, 'registered': True}
            if args.accept_older and binding == 'overridden':
                identity['decision'] = args.accept_older
            shape = preview_id['geometry']
            schedule = preview_id['schedule']
            seconds = (schedule['visible_end_us'] - schedule['visible_start_us']) / 1e6 if schedule else None
            film_md = (staging / 'film.md').read_bytes()
            files = {p.relative_to(staging).as_posix(): file_sha256(p) for p in sorted(staging.rglob('*')) if p.is_file()}
            manifest = {'version': name, 'parent': parent, 'created': now(), 'label': args.label or '',
                        'duration_s': round(seconds, 4) if seconds is not None else None,
                        'frames': schedule['frames'] if schedule else None,
                        'size': [shape['display_width'], shape['display_height']],
                        'preview_size': [shape['display_width'], shape['display_height']],
                        'fps': preview_id['fps_exact'], 'film_md_sha256': hashlib.sha256(film_md).hexdigest(),
                        'files': files, 'sources': {}, 'notes_resolved': [], 'title': read_status(root).get('title', ''),
                        'final': False, 'skill_version': skill_version(), 'captions': [],
                        'registered_from': str(Path(args.file).resolve()), 'identity': identity}
            save_json(staging / 'manifest.json', manifest)
            os.replace(staging, root / 'cuts' / name)
        if args.accept_older and binding == 'overridden':
            append_jsonl(root / 'decisions.jsonl', {'at': now(), 'kind': 'accept-older', 'version': name,
                                                     'reason': args.accept_older, 'by': 'person'})
        earlier = load_json(root / 'notes.json', None)
        if isinstance(earlier, dict) and isinstance(earlier.get('notes'), list):
            with file_lock(root / 'notes.json'):
                data = load_json(root / 'notes.json', {'version': 1, 'notes': []})
                touched = False
                for note in data.get('notes', []):
                    if note.get('status') == 'open' and note.get('version') not in (None, name):
                        other = load_json(root / 'cuts' / str(note['version']) / 'manifest.json', {}) or {}
                        if ((other.get('identity') or {}).get('picture_sha256') != preview_id['sha256']
                                and not note.get('on_earlier_version')):
                            note['on_earlier_version'] = True
                            note['earlier_than'] = name
                            touched = True
                if touched:
                    save_json(root / 'notes.json', data)
        set_current(root, name)
        update_status(root, line=status_line(root))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f'registered {name}: binding {binding}' + (f', render_trace {render_trace}' if render_trace else '') +
          f'; picture {preview_id["sha256"][:12]}; cues {listed.sha256[:12]} ({provenance})')
    for reason in reasons:
        print(f'  unverified: {reason}' if binding == 'unverified' else f'  note: {reason}')
    for line in notes:
        print('  ' + line)
    return 1 if binding == 'unverified' or notes else 0


def prune_frozen(project, page=None, dry_run=False):
    """Remove kept copies no cue list and no version names; return the removed (or, dry, the removable) paths."""
    cl = _sibling('cue_list')
    root = Path(project).resolve()
    fields, _ = front_matter_block(read_text(root / 'film.md')) if (root / 'film.md').is_file() else ({}, [])
    pages = [Path(page).resolve()] if page else ([(root / fields['page']).resolve()] if fields.get('page') else [])
    named = set()
    for manifest in (root / 'cuts').glob('v*/manifest.json'):
        snap = ((load_json(manifest, {}) or {}).get('identity') or {}).get('source', {}).get('snapshot_sha256')
        if snap:
            named.add(snap)
    for top in [root] + pages:
        for path in top.rglob('*.json'):
            if cl.FROZEN_DIR in path.parts or 'node_modules' in path.parts:
                continue
            data = load_json(path, None)
            if isinstance(data, dict) and isinstance(data.get('picture'), dict):
                snap = data['picture'].get('snapshot_sha256')
                if isinstance(snap, str):
                    named.add(snap)
    removed = []
    for folder in pages:
        for kept in sorted((folder / cl.FROZEN_DIR).glob('*')) if (folder / cl.FROZEN_DIR).is_dir() else []:
            if kept.is_dir() and kept.name not in named and not kept.name.startswith('.tmp-'):
                removed.append(kept)
                if not dry_run:
                    shutil.rmtree(kept)
    return removed


def main():
    safe_output()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('init', help='create the layout and a status.json')
    create.add_argument('project')
    create.add_argument('--title', default='')
    create.add_argument('--film', help='start the project from this paper edit (refused when a different film.md '
                                       'is already there)')
    create.add_argument('--path', choices=PATHS, help='the path that owns the project (writes the project record)')
    create.add_argument('--timeline', choices=TIMELINES, help='what owns the timeline (writes the project record)')
    create.add_argument('--page', help='the page folder, when a page owns the timeline')
    create.add_argument('--what', help='the frame: what this is (assumed until the person confirms it)')
    create.add_argument('--audience', help='the frame: who watches it, where (assumed until confirmed)')
    create.add_argument('--why', help='the frame: why they care (assumed until confirmed)')
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
    add = sub.add_parser('add-version', help='register a master rendered outside cut.py, bound to its cue list',
                         description=ADD_VERSION_HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    add.add_argument('project')
    add.add_argument('--cues', required=True, help='the cue list (v2: page, picture or plan)')
    add.add_argument('--file', required=True, help='the master; with --render, the OUT the command writes')
    add.add_argument('--render', metavar='CMD', help='the engine command, naming {page} and {out}')
    add.add_argument('--sound', metavar='WAV', help='the mixer output to mux onto the master, picture copied')
    add.add_argument('--mix-report', help='the mixer report (default: mix-report.json beside WAV)')
    add.add_argument('--page', metavar='DIR', help="the page folder (default: film.md page:, else the list's path)")
    add.add_argument('--receipt', metavar='R', help="a kit render's OUTPUT.manifest.json")
    add.add_argument('--accept-older', metavar='REASON', help='register a master older than its page, as a decision')
    add.add_argument('--label', help='a label for the version')
    add.add_argument('--stems', metavar='DIR', help='stems to keep in cuts/vNNN/stems/')
    add.add_argument('--min-free-gib', type=float, default=3.0, help='free memory the render waits for (default 3)')
    add.add_argument('--wait-min', type=float, default=20.0, help='longest wait for the lock and memory (default 20)')
    prune = sub.add_parser('prune-frozen', help='remove kept frozen copies no cue list and no version names',
                           description=PRUNE_HELP)
    prune.add_argument('project')
    prune.add_argument('--page', metavar='DIR', help='the page folder (default: film.md page:)')
    prune.add_argument('--dry-run', action='store_true', help='list what would be removed')
    args = parser.parse_args()
    try:
        if args.command == 'init':
            existing = read_status(args.project) if (Path(args.project) / 'status.json').is_file() else None
            folder = init(args.project, args.title, args.film, args.path, args.timeline, args.page, args.what,
                          args.audience, args.why)
            if existing is None:
                print(f'project ready: {folder}')
            else:
                kept = existing.get('title') or ''
                changed = f'; its title stays "{kept}"' if args.title and args.title != kept else ''
                print(f'already a project, kept as it was: {folder}{changed}')
            return 0
        if args.command == 'add-version':
            try:
                return add_version(args)
            except Refused as error:
                print('refused: ' + str(error), file=sys.stderr)
                return 2
        if args.command == 'prune-frozen':
            removed = prune_frozen(args.project, args.page, args.dry_run)
            verb = 'would remove' if args.dry_run else 'removed'
            print(f'{verb} {len(removed)} kept cop' + ('y' if len(removed) == 1 else 'ies') +
                  ''.join(f'\n  {path}' for path in removed))
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
        refresh_record_status(folder)
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
