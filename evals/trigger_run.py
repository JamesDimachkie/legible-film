#!/usr/bin/env python3
"""Measure whether a SKILL.md triggers, and which path it takes, in fresh agent sessions.

  python evals/trigger_run.py trigger --variant old=OLD_SKILL_DIR --variant new=NEW_SKILL_DIR
      --reps 2 --out evals/results/RUN --work SCRATCH [--workers 3] [--budget 360]
  python evals/trigger_run.py routing --cases evals/reshape-routing.json --variant old=BASELINE_SKILL_DIR
      [--variant new=CANDIDATE_SKILL_DIR] --reps 3 --host claude|codex --out OUT --work SCRATCH
      [--only P01,H1,...] [--sets dev,heldout] [--heldout PATH] [--workers 2] [--min-free-gib 2]
  python evals/trigger_run.py rescore --out OUT --cases evals/reshape-routing.json --variant old=BASELINE_SKILL_DIR
      [--work SCRATCH]
  python evals/trigger_run.py summary --out OUT [--cases evals/reshape-routing.json]

trigger: for every query in evals/trigger-queries.json, each variant and each repetition, starts a fresh
`claude -p` session in a temporary project whose only skill is the variant under .claude/skills/legible-film/
(its SKILL.md and references/), with project settings only, no MCP servers, read-only tools (Skill, Read, Glob,
Grep), at most three turns and no saved session. A query counts as loaded when the session's stream JSON shows a
Skill tool call for legible-film or a Read of its SKILL.md; the session is stopped (by its own PID) as soon as it
does. Every stream is kept under OUT/runs/trigger/. Pass: the last variant loads at least as often as the first
on should-trigger queries and no more often on should-not-trigger ones.

routing (plan mode): for each case in the cases file (development prompts, the sealed held-out prompts, route
checks), each variant and each repetition, --workers sessions at a time (2), each starting once --min-free-gib (2)
is free. Sessions are planning runs, one agent CLI process each with every heavy step denied, so they take no
heavy-job lock. Each gets a fresh scratch project holding the whole variant skill folder and the case's stub media;
Write and Edit allowed only inside the project; Bash allowed, with every build, spend, network, install and heavy
step denied and logged (the patterns are frozen in the cases file); at most the cases file's turn_limit turns over
the session (codex_turn_limit steps on Codex, which counts every command);
one scripted person reply when the agent's first exchange ends with a question. The prompt carries the cases
file's routing ask. Scoring (evals/routing_score.py) reads the session stream, not the answer: the route, the
skill files read before the first action and their words, the first question and the frame, forbidden and required
reads and runs, and attempts. Route checks 16-20 (--sets route) run on a candidate only (a skill with paths/): their
project fixtures are built in the scratch project with the variant's own scripts, and evals/route_checks.py scores
what section 13 states for each, beside the frozen scorer. Claude runs through `claude -p` with project settings
only, no MCP servers and a
PreToolUse guard hook in the project. Codex runs through `codex exec --json` on the person's normal Codex home and
login, isolated only by per-run `-c` overrides (plugins, apps, memories, MCP servers and every installed user skill
disabled; the variant staged in the project's .agents/skills); Codex has no per-tool deny hook, so attempts are read
from the trace's command events and the session is stopped at the first build, spend or heavy attempt. Held-out prompts
are read at run time from outside the repository and refused unless their SHA-256 matches evals/heldout.sha256;
the rows and summaries keep no prompt or answer text, only the raw transcripts under OUT do.

summary: writes OUT/summary.json and OUT/summary.md from what is recorded: triggering, and for routing, per run,
per prompt and per path, with infrastructure errors and unscored sessions listed and never counted as passes.

Runs already recorded are skipped, so a stopped run resumes where it left off. Local paths (the temporary project,
the home folder) are replaced by <PROJECT> and <HOME> in everything kept. The sessions use the signed-in Claude
account or the person's Codex login and hosted inference: the prompts and the skill text go to the model provider.
It does not prove how the skill behaves with other skills installed or on later turns; the frame and money checks
are keyword evidence for a person to audit.

Exit codes: 0 every recorded comparison passes, 1 a comparison fails or runs are missing, 2 could not run.
"""
import argparse
import concurrent.futures
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import routing_score  # noqa: E402
import route_checks  # noqa: E402

QUERIES = HERE / 'trigger-queries.json'
SKILL_NAME = 'legible-film'
TOOLS_TRIGGER = 'Skill,Read,Glob,Grep'
TOOLS_PLAN = 'Skill,Read,Glob,Grep,Write,Edit,Bash'
TIMEOUT = 180
PLAN_TIMEOUT = 900
GUARD_MARK = '[legible-film eval harness]'
LOCK = threading.Lock()
FIXTURES = threading.Lock()
IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.pytest_cache', 'node_modules')


def parse_variants(items):
    """Turn NAME=SKILL_DIR arguments into an ordered list of (name, Path)."""
    out = []
    for item in items:
        name, _, path = item.partition('=')
        folder = Path(path)
        if not name or not (folder / 'SKILL.md').is_file():
            raise ValueError(f'--variant needs NAME=SKILL_DIR with a SKILL.md: {item}')
        out.append((name, folder.resolve()))
    return out


def stage_project(work, name, folder):
    """A temporary project holding only this variant of the skill; returns its path."""
    project = Path(work) / 'projects' / name
    skill = project / '.claude' / 'skills' / SKILL_NAME
    if skill.exists():
        shutil.rmtree(skill)
    skill.mkdir(parents=True)
    shutil.copy2(folder / 'SKILL.md', skill / 'SKILL.md')
    if (folder / 'references').is_dir():
        shutil.copytree(folder / 'references', skill / 'references')
    return project


def loads_skill(event):
    """True when a stream-JSON event is a Skill call for the skill or a Read of its SKILL.md."""
    if event.get('type') != 'assistant':
        return False
    for part in event.get('message', {}).get('content', []):
        if part.get('type') != 'tool_use':
            continue
        args = part.get('input') or {}
        if part.get('name') == 'Skill' and str(args.get('skill', '')).split(':')[-1] == SKILL_NAME:
            return True
        path = str(args.get('file_path', '')).replace('\\', '/')
        if part.get('name') == 'Read' and path.endswith(SKILL_NAME + '/SKILL.md'):
            return True
    return False


def path_forms(folder):
    """The spellings of a Windows or POSIX path that appear in stream JSON and text, longest first."""
    plain = str(folder)
    slash = plain.replace('\\', '/')
    forms = {plain, slash, plain.replace('\\', '\\\\'), re.sub(r'[^A-Za-z0-9]', '-', plain)}
    if len(plain) > 2 and plain[1] == ':':
        forms.add('/' + plain[0].lower() + slash[2:])
    forms |= {f[:1].lower() + f[1:] for f in list(forms)} | {f[:1].upper() + f[1:] for f in list(forms)}
    return sorted(forms, key=len, reverse=True)


def scrub(text, project):
    """Replace the temporary project and the home folder with placeholders in text that will be kept."""
    for folder, label in ((Path(project).resolve(), '<PROJECT>'), (Path.home(), '<HOME>')):
        for form in path_forms(folder):
            text = text.replace(form, label)
    return text


def run_session(project, prompt, tools, raw_path, stop_on_load):
    """Run one fresh `claude -p` session; keep its stream; return what it showed."""
    exe = shutil.which('claude')
    if not exe:
        raise RuntimeError('claude is not on PATH')
    cmd = [exe, '-p', prompt, '--output-format', 'stream-json', '--verbose', '--setting-sources', 'project',
           '--strict-mcp-config', '--max-turns', '3', '--tools', tools, '--no-session-persistence']
    started = time.time()
    proc = subprocess.Popen(cmd, cwd=project, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace')
    timer = threading.Timer(TIMEOUT, proc.kill)
    timer.start()
    loaded = False
    model = None
    text = []
    lines = []
    try:
        for line in proc.stdout:
            lines.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'system' and event.get('subtype') == 'init':
                model = event.get('model')
            if event.get('type') == 'assistant':
                text += [p.get('text', '') for p in event['message'].get('content', []) if p.get('type') == 'text']
            if loads_skill(event):
                loaded = True
                if stop_on_load:
                    proc.kill()
                    break
    finally:
        timer.cancel()
        proc.wait()
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(scrub(''.join(lines), project), encoding='utf-8', newline='\n')
    timed_out = time.time() - started >= TIMEOUT and not loaded
    return {'loaded': loaded, 'model': model, 'text': scrub('\n'.join(text), project),
            'seconds': round(time.time() - started, 1), 'timed_out': timed_out}


def record(path, row):
    """Append one JSON row to a results file, one writer at a time."""
    with LOCK:
        with open(path, 'a', encoding='utf-8', newline='\n') as fh:
            fh.write(json.dumps(row) + '\n')


def done_keys(path):
    """Keys of the runs already recorded in a results file."""
    if not path.exists():
        return set()
    return {json.loads(line)['key'] for line in path.read_text(encoding='utf-8').splitlines() if line.strip()}


def trigger_jobs(variants, reps):
    """Every (variant, kind, index, query, rep) to run for triggering."""
    spec = json.loads(QUERIES.read_text(encoding='utf-8'))
    jobs = []
    for rep in range(1, reps + 1):
        for name, _ in variants:
            for kind in ('should_trigger', 'should_not_trigger'):
                for i, query in enumerate(spec[kind]):
                    jobs.append((name, kind, i, query, rep))
    return jobs


def run_trigger(args, variants):
    """Run the triggering sessions not yet recorded, within the time budget."""
    out = Path(args.out) / 'runs' / 'trigger'
    out.mkdir(parents=True, exist_ok=True)
    results = Path(args.out) / 'trigger-results.jsonl'
    projects = {name: stage_project(args.work, name, folder) for name, folder in variants}
    seen = done_keys(results)
    deadline = time.time() + args.budget

    def one(job):
        name, kind, i, query, rep = job
        key = f'{name}/{kind}/{i:02d}/r{rep}'
        if key in seen or time.time() > deadline:
            return None
        raw = out / f'{name}-{kind}-{i:02d}-r{rep}.jsonl'
        got = run_session(projects[name], query, TOOLS_TRIGGER, raw, stop_on_load=True)
        row = {'key': key, 'variant': name, 'kind': kind, 'index': i, 'query': query, 'rep': rep,
               'loaded': got['loaded'], 'model': got['model'], 'seconds': got['seconds'],
               'timed_out': got['timed_out'], 'raw': raw.relative_to(Path(args.out)).as_posix()}
        record(results, row)
        print(f"{key}: {'loaded' if got['loaded'] else 'not loaded'} ({got['seconds']} s)", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers or 3) as pool:
        list(pool.map(one, trigger_jobs(variants, args.reps)))


# ================================================================ routing: cases, held-outs, fixtures

def load_cases(path, heldout_path, sets, only):
    """The frozen spec and the cases to run, held-outs merged in from outside the repository."""
    spec = json.loads(Path(path).read_text(encoding='utf-8'))
    cases = []
    if 'dev' in sets:
        cases += spec['cases']
    if 'heldout' in sets:
        cases += heldout_cases(spec, heldout_path)
    if 'route' in sets:
        cases += spec['route_checks']
    if only:
        wanted = set(only.split(','))
        cases = [c for c in cases if c['id'] in wanted or str(c['n']) in wanted]
    return spec, cases


def heldout_cases(spec, heldout_path):
    """Held-out cases with their prompts, refused unless the file's SHA-256 matches the sealed hash."""
    info = spec['heldout']
    path = Path(heldout_path) if heldout_path else (HERE.parent / info['path_from_repository']).resolve()
    if not path.is_file():
        raise ValueError(f'the held-out prompts are not at {path}; give --heldout PATH or leave out --sets heldout')
    sealed = (HERE.parent / info['sha256_file']).read_text(encoding='utf-8').split()[0]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != sealed:
        raise ValueError(f'the held-out file hashes to {actual}, not the sealed {sealed}')
    prompts = {row['id']: row['prompt'] for row in json.loads(path.read_text(encoding='utf-8'))}
    out = []
    for case in info['cases']:
        if case['id'] not in prompts:
            raise ValueError(f"the held-out file has no {case['id']}")
        out.append(dict(case, set='heldout', prompt=prompts[case['id']], reply=info['reply'], fixtures=[]))
    return out


def ffmpeg(*args):
    """Run FFmpeg quietly; raise with its message on failure."""
    exe = shutil.which('ffmpeg')
    if not exe:
        raise RuntimeError('ffmpeg is not on PATH; the stub media cannot be built')
    done = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-y', *args], capture_output=True, text=True)
    if done.returncode:
        raise RuntimeError(f'ffmpeg failed: {done.stderr.strip()[:300]}')


def build_fixture(name, spec, cache):
    """Build one stub media or timeline file into the cache once; return its path."""
    out = Path(cache) / name
    if out.is_file() and out.stat().st_size:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    kind = spec['kind']
    seconds = spec.get('seconds', 10)
    size = spec.get('size', '640x360')
    fps = spec.get('fps', 25)
    video = ['-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={fps}:duration={seconds}']
    encode = ['-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '32', '-pix_fmt', 'yuv420p', '-threads', '2']
    if kind == 'video':
        ffmpeg(*video, *encode, '-an', str(out))
    elif kind == 'av':
        if spec.get('gaps'):
            expr = '0.25*sin(2*PI*220*t)*lt(mod(t\\,9)\\,6)'
        elif spec.get('drop_at'):
            d = spec['drop_at']
            expr = (f'if(lt(t\\,{d})\\,0.15*sin(2*PI*(200+25*t)*t)\\,'
                    f'0.5*sin(2*PI*55*t)+0.2*sin(2*PI*110*t)*lt(mod(t\\,0.5)\\,0.1))')
        else:
            expr = '0.2*sin(2*PI*330*t)*(0.6+0.4*sin(2*PI*0.5*t))'
        audio = ['-f', 'lavfi', '-i', f'aevalsrc={expr}:s=48000:d={seconds}']
        ffmpeg(*video, *audio, *encode, '-c:a', 'aac', '-b:a', '64k', '-shortest', str(out))
    elif kind == 'xmeml':
        write_xmeml(out, spec['source'], spec['spans_s'])
    elif kind == 'srt':
        write_srt(out, spec['seconds'], spec['cues'])
    else:
        raise ValueError(f'unknown fixture kind {kind} for {name}')
    return out


def write_xmeml(path, source, spans_s, fps=30):
    """A minimal Final Cut Pro 7 XML sequence of one source, video and audio, spans in seconds."""
    spans = [(int(a * fps), int(b * fps)) for a, b in spans_s]

    def text(parent, tag, value):
        node = ET.SubElement(parent, tag)
        node.text = str(value)
        return node

    def rate(parent):
        node = ET.SubElement(parent, 'rate')
        text(node, 'timebase', fps)
        text(node, 'ntsc', 'FALSE')

    root = ET.Element('xmeml', {'version': '4'})
    sequence = ET.SubElement(root, 'sequence', {'id': 'sequence-1'})
    text(sequence, 'name', path.stem)
    text(sequence, 'duration', sum(b - a for a, b in spans))
    rate(sequence)
    media = ET.SubElement(sequence, 'media')
    for kind in ('video', 'audio'):
        track = ET.SubElement(ET.SubElement(media, kind), 'track')
        cursor = 0
        for number, (start, end) in enumerate(spans):
            clip = ET.SubElement(track, 'clipitem', {'id': f'{kind}-clip-{number}'})
            text(clip, 'name', source)
            text(clip, 'enabled', 'TRUE')
            rate(clip)
            text(clip, 'start', cursor)
            text(clip, 'end', cursor + end - start)
            text(clip, 'in', start)
            text(clip, 'out', end)
            reference = ET.SubElement(clip, 'file', {'id': 'source-file'})
            if kind == 'video' and number == 0:
                text(reference, 'name', source)
                text(reference, 'pathurl', f'file://localhost/{source}')
                rate(reference)
            cursor += end - start
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def write_srt(path, seconds, cues):
    """Evenly spaced placeholder captions."""
    step = seconds / cues

    def stamp(t):
        ms = int(round(t * 1000))
        return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'

    rows = [f'{i + 1}\n{stamp(i * step)} --> {stamp((i + 1) * step - 0.1)}\nCaption line {i + 1}.\n'
            for i in range(cues)]
    Path(path).write_text('\n'.join(rows), encoding='utf-8', newline='\n')


# ================================================================ routing: the memory floor

def free_mib():
    """Available physical memory in MiB (Windows GlobalMemoryStatusEx, Linux MemAvailable, macOS vm_stat)."""
    if os.name == 'nt':
        import ctypes

        class Status(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (key, ctypes.c_ulonglong) for key in ('total', 'avail', 'page', 'free_page', 'virtual',
                                                       'free_virtual', 'extended')]
        status = Status()
        status.length = ctypes.sizeof(status)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            raise OSError('GlobalMemoryStatusEx failed')
        return status.avail / 1024 / 1024
    meminfo = Path('/proc/meminfo')
    if meminfo.is_file():
        for line in meminfo.read_text(encoding='ascii').splitlines():
            if line.startswith('MemAvailable:'):
                return int(line.split()[1]) / 1024
    output = subprocess.run(['vm_stat'], capture_output=True, text=True).stdout
    page = re.search(r'page size of (\d+) bytes', output)
    counts = re.findall(r'Pages (?:free|inactive|speculative):\s*(\d+)\.', output)
    if page and counts:
        return int(page.group(1)) * sum(map(int, counts)) / 1024 / 1024
    raise OSError('cannot determine available physical memory')


class MemoryWait(Exception):
    """Free memory stayed below the floor for --wait-min minutes; nothing is recorded for the session."""


def wait_for_memory(min_free_gib, wait_minutes=0, said=None):
    """Wait until free memory is at or above the floor and return the MiB free then. Routing sessions are planning
    runs (one agent CLI process each, every heavy step denied), so they take no heavy-job lock; this floor is all they
    wait for. wait_minutes 0 waits on."""
    floor = min_free_gib * 1024
    limit = wait_minutes * 60 or float('inf')
    low_since, last = None, 0
    while True:
        free = free_mib()
        if free >= floor:
            return round(free)
        low_since = low_since or time.monotonic()
        if time.monotonic() - low_since >= limit:
            raise MemoryWait(f'free memory stayed below {floor:.0f} MiB ({free:.0f} MiB)')
        if time.monotonic() - last > 300:
            print(f'  waiting for memory: {free:.0f} MiB free, need {floor:.0f}', flush=True)
            last = time.monotonic()
        time.sleep(20)


# ================================================================ routing: the guard hook (Claude)

def guard(args):
    """PreToolUse hook: deny and log build, spend, network, install and heavy steps, and writes outside."""
    data = json.loads(sys.stdin.read() or '{}')
    spec = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    tool, tool_input = data.get('tool_name'), data.get('tool_input') or {}
    project = Path(args.project).resolve()
    classes = []
    if tool == 'Bash':
        classes = routing_score.classify(str(tool_input.get('command', '')), spec['actions']['classes'])
    elif tool in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
        target = Path(str(tool_input.get('file_path') or tool_input.get('notebook_path') or ''))
        target = (project / target if not target.is_absolute() else target).resolve()
        inside = project == target or project in target.parents
        if not inside or (project / '.claude') in target.parents:
            classes = ['outside']
    decision = 'deny' if classes else 'allow'
    row = {'time': time.time(), 'tool': tool, 'tool_use_id': data.get('tool_use_id'), 'decision': decision,
           'classes': classes, 'input': json.dumps(tool_input)[:600]}
    with open(args.log, 'a', encoding='utf-8', newline='\n') as fh:
        fh.write(json.dumps(row) + '\n')
    if classes:
        reason = (f"{GUARD_MARK} Not run: this step is outside what this session may do ({', '.join(classes)}). "
                  'Say what you would run and why instead.')
        print(json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                                 'permissionDecisionReason': reason}}))
    return 0


# ================================================================ routing: sessions

def session_paths(work, out, host, variant, case_id, rep):
    """The scratch project and the kept-record folder of one session."""
    tail = Path(host) / variant / case_id / f'r{rep}'
    return Path(work) / 'sessions' / tail / 'project', Path(out) / 'routing' / tail


def stage_session(project, host, skill_dir, fixtures, spec, cache, guard_cmd=None):
    """A fresh scratch project: the whole variant skill, the case's stub media and, for Claude, the guard hook."""
    if project.exists():
        shutil.rmtree(project)
    project.mkdir(parents=True)
    skills_root = project / ('.claude' if host == 'claude' else '.agents') / 'skills'
    shutil.copytree(skill_dir, skills_root / SKILL_NAME, ignore=IGNORE)
    for name in fixtures:
        with FIXTURES:
            built = build_fixture(name, spec['fixtures'][name], cache)
        shutil.copy2(built, project / name)
    if guard_cmd:
        hooks = {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': guard_cmd}]}]}}
        (project / '.claude' / 'settings.json').write_text(json.dumps(hooks, indent=2), encoding='utf-8')
    return skills_root / SKILL_NAME


def user_message(text):
    """One stream-json user message for `claude -p --input-format stream-json`."""
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': text}}) + '\n'


def run_claude_plan(project, prompt, reply, turn_limit, timeout):
    """One plan-mode Claude session: the prompt, then at most one scripted reply. Returns raw lines and notes."""
    exe = shutil.which('claude')
    if not exe:
        raise RuntimeError('claude is not on PATH')
    cmd = [exe, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
           '--setting-sources', 'project', '--strict-mcp-config', '--max-turns', str(turn_limit), '--tools',
           TOOLS_PLAN, '--allowedTools', TOOLS_PLAN, '--permission-mode', 'acceptEdits',
           '--no-session-persistence']
    err = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
    proc = subprocess.Popen(cmd, cwd=project, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=err, text=True, encoding='utf-8', errors='replace')
    notes = {'stopped': None, 'model': None, 'version': None, 'stderr': ''}
    timer = threading.Timer(timeout, lambda: (notes.update(stopped='timeout'), proc.kill()))
    timer.start()
    lines, ids, results, last_text = [], [], 0, ''
    try:
        proc.stdin.write(user_message(prompt))
        proc.stdin.flush()
        for line in proc.stdout:
            lines.append(line)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get('type')
            if kind == 'system' and event.get('subtype') == 'init':
                notes['model'] = event.get('model')
                notes['version'] = event.get('claude_code_version')
                notes['init_skills'] = event.get('skills')
                notes['init_tools'] = event.get('tools')
                notes['init_mcp'] = event.get('mcp_servers')
                notes['init_plugins'] = event.get('plugins')
            elif kind == 'assistant':
                message = event.get('message', {})
                if message.get('id') not in ids:
                    ids.append(message.get('id'))
                    if len(ids) > turn_limit:
                        notes['stopped'] = 'turn limit'
                        proc.kill()
                        break
                texts = [p.get('text', '') for p in message.get('content', []) if p.get('type') == 'text']
                if any(t.strip() for t in texts):
                    last_text = texts[-1]
            elif kind == 'result':
                results += 1
                ask = '?' in last_text and event.get('subtype') == 'success' and len(ids) < turn_limit
                if results == 1 and ask and reply:
                    lines.append(json.dumps({'type': 'harness_reply', 'text': reply}) + '\n')
                    proc.stdin.write(user_message(reply))
                    proc.stdin.flush()
                    last_text = ''
                else:
                    proc.stdin.close()
    except (OSError, ValueError) as exc:
        notes['stopped'] = notes['stopped'] or f'pipe: {exc}'
    finally:
        timer.cancel()
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()
        err.seek(0)
        notes['stderr'] = err.read()[-2000:]
        err.close()
    notes['turns'] = len(ids)
    notes['results'] = results
    return lines, notes


def codex_command():
    """The codex CLI as node plus its npm package's codex.js (a stray codex.exe beside the shim can be stale)."""
    node = shutil.which('node')
    appdata = os.environ.get('APPDATA', '')
    script = Path(appdata) / 'npm' / 'node_modules' / '@openai' / 'codex' / 'bin' / 'codex.js'
    if node and script.is_file():
        return [node, str(script)]
    exe = shutil.which('codex')
    if not exe:
        raise RuntimeError('codex is not on PATH')
    return [exe]


def codex_overrides():
    """Per-run `-c` overrides: no plugins, apps, memories, MCP servers or web search; every user skill disabled."""
    home = Path.home()
    codex_home = Path(os.environ.get('CODEX_HOME') or home / '.codex')
    skills = sorted(glob.glob(str(home / '.agents' / 'skills' / '*' / 'SKILL.md')) +
                    glob.glob(str(codex_home / 'skills' / '*' / 'SKILL.md')) +
                    glob.glob(str(codex_home / 'skills' / '.system' / '*' / 'SKILL.md')))
    entries = ', '.join("{path='%s', enabled=false}" % os.path.normpath(p) for p in skills)
    features = ['plugins', 'apps', 'remote_plugin', 'image_generation', 'browser_use', 'browser_use_external',
                'computer_use', 'in_app_browser', 'multi_agent', 'memories', 'tool_suggest',
                'skill_mcp_dependency_install', 'goals']
    over = [f'features.{f}=false' for f in features]
    over += ['mcp_servers={}', 'memories.use_memories=false', 'memories.generate_memories=false',
             'web_search="disabled"', f'skills.config=[{entries}]']
    args = []
    for item in over:
        args += ['-c', item]
    return args, len(skills)


def run_codex_plan(project, prompt, reply, turn_limit, timeout, classes, failing):
    """One Codex session through `codex exec --json`, then at most one scripted reply through `exec resume`."""
    base = codex_command()
    overrides, disabled = codex_overrides()
    notes = {'stopped': None, 'model': None, 'skills_disabled': disabled, 'stderr': ''}
    lines, state = [], {'turns': 0, 'thread': None, 'last_text': ''}
    deadline = time.time() + timeout

    def one(cmd):
        err = tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace')
        proc = subprocess.Popen(cmd, cwd=project, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=err, text=True, encoding='utf-8', errors='replace')
        timer = threading.Timer(max(deadline - time.time(), 1), lambda: (notes.update(stopped='timeout'),
                                                                         proc.kill()))
        timer.start()
        try:
            for line in proc.stdout:
                lines.append(line)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                item = event.get('item') or {}
                if event.get('type') == 'thread.started':
                    state['thread'] = event.get('thread_id')
                if event.get('type') == 'item.started' and item.get('type') == 'command_execution':
                    found = routing_score.classify(routing_score.unwrap(item.get('command', '')), classes)
                    if set(found) & (set(failing) | {'heavy'}):
                        notes['stopped'] = f"stopped at a {', '.join(found)} attempt"
                        proc.kill()
                        break
                if event.get('type') == 'item.completed':
                    if item.get('type') in ('command_execution', 'file_change', 'mcp_tool_call', 'web_search'):
                        state['turns'] += 1
                        if state['turns'] > turn_limit:
                            notes['stopped'] = 'turn limit'
                            proc.kill()
                            break
                    if item.get('type') == 'agent_message':
                        state['last_text'] = item.get('text', '')
        finally:
            timer.cancel()
            try:
                proc.kill()
            except OSError:
                pass
            proc.wait()
            err.seek(0)
            notes['stderr'] += err.read()[-1500:]
            err.close()
        return proc.returncode

    first = base + ['exec', '--json', '--skip-git-repo-check', '-C', str(project)] + overrides + [prompt]
    notes['exit'] = one(first)
    if (not notes['stopped'] and reply and state['thread'] and '?' in state['last_text']
            and state['turns'] < turn_limit):
        lines.append(json.dumps({'type': 'harness_reply', 'text': reply}) + '\n')
        resume = base + ['exec', 'resume', '--json', '--skip-git-repo-check'] + overrides + [state['thread'], reply]
        notes['exit_resume'] = one(resume)
    notes['turns'] = state['turns']
    return lines, notes


def denied_ids(lines):
    """Tool-use ids whose result is the guard's denial."""
    out = {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') != 'user':
            continue
        for part in event.get('message', {}).get('content', []) or []:
            if isinstance(part, dict) and part.get('type') == 'tool_result' and GUARD_MARK in json.dumps(part):
                out[part.get('tool_use_id')] = True
    return out


def parse_lines(lines):
    """The JSON events among raw stream lines."""
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def infra_error(host, notes, lines):
    """An infrastructure error that makes a session unusable, or None."""
    events = parse_lines(lines)
    if host == 'claude':
        results = [e for e in events if e.get('type') == 'result']
        if not any(e.get('type') == 'assistant' for e in events):
            return f"no assistant turn ({notes.get('stopped') or 'no output'}): {notes.get('stderr', '')[-300:]}"
        if results and results[0].get('is_error') and results[0].get('subtype') not in ('error_max_turns',):
            return f"session error: {results[0].get('subtype')} {str(results[0].get('result', ''))[:200]}"
        if not results and notes.get('stopped') == 'timeout':
            return 'timed out before the first exchange ended'
        return None
    if not any(e.get('type') == 'item.completed' for e in events):
        return f"no completed item (exit {notes.get('exit')}): {notes.get('stderr', '')[-300:]}"
    if any(e.get('type') == 'turn.failed' for e in events) and not any(e.get('type') == 'turn.completed'
                                                                       for e in events):
        bad = next(e for e in events if e.get('type') == 'turn.failed')
        return f'session error: {json.dumps(bad)[:300]}'
    return None


def run_routing(args, variants):
    """Run every plan-mode session not yet recorded, --workers at a time (no heavy-job lock; a free-memory floor)."""
    spec, cases = load_cases(args.cases, args.heldout, args.sets.split(','), args.only)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = out / 'routing-results.jsonl'
    seen = {r['key'] for r in latest_rows(read_rows(results)) if not (args.retry_errors and r.get('error'))}
    cache = Path(args.work) / 'fixtures'
    turn_limit = args.turn_limit or (spec.get('codex_turn_limit', spec['turn_limit']) if args.host == 'codex'
                                     else spec['turn_limit'])
    if shutil.which('tsrct'):
        print('note: tsrct is on PATH; route check 16 assumes it is not', flush=True)
    jobs = [(rep, name, folder, case) for rep in range(1, args.reps + 1) for name, folder in variants
            for case in cases if f"{args.host}/{name}/{case['id']}/r{rep}" not in seen and
            (case.get('set') != 'route' or route_checks.applies(folder))]
    skipped = sorted({name for name, folder in variants if not route_checks.applies(folder)})
    if skipped and any(case.get('set') == 'route' for case in cases):
        print(f"route checks 16-20 run on a candidate only; not run for {', '.join(skipped)}", flush=True)
    stop = threading.Event()

    def one(job):
        if not stop.is_set():
            try:
                run_one_session(args, spec, cache, out, results, turn_limit, *job)
            except MemoryWait as exc:
                stop.set()
                print(f'stopping: {exc}; run again to resume', flush=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers or 2) as pool:
        list(pool.map(one, jobs))
    if stop.is_set():
        raise RuntimeError('stopped while waiting for memory; recorded sessions are kept')


def run_one_session(args, spec, cache, out, results, turn_limit, rep, name, folder, case):
    """Stage, run, score and record one session."""
    key = f"{args.host}/{name}/{case['id']}/r{rep}"
    project, keep = session_paths(args.work, out, args.host, name, case['id'], rep)
    keep.mkdir(parents=True, exist_ok=True)
    guard_log = keep / 'guard.jsonl'
    if guard_log.exists():
        guard_log.unlink()
    row = {'key': key, 'host': args.host, 'variant': name, 'case': case['id'], 'n': case['n'],
           'set': case.get('set'), 'rep': rep, 'expected': case['expected'], 'turn_limit': turn_limit,
           'started': time.time()}
    try:
        fixture = None
        if case.get('set') == 'route' and route_checks.environment(case):
            raise RuntimeError(route_checks.environment(case))
        guard_cmd = None
        if args.host == 'claude':
            slash = [str(p).replace('\\', '/') for p in (sys.executable, Path(__file__).resolve(),
                                                          Path(args.cases).resolve(), project.resolve(),
                                                          guard_log.resolve())]
            guard_cmd = '"{}" "{}" guard --cases "{}" --project "{}" --log "{}"'.format(*slash)
        skill_dir = stage_session(project, args.host, folder, case.get('fixtures', []), spec, cache, guard_cmd)
        if case.get('project_fixture'):
            fixture = route_checks.build_fixture(case['project_fixture'], project, skill_dir)
            row['fixture'] = fixture
        prompt = case['prompt'] + spec['routing_ask']
        row['free_mib_at_start'] = wait_for_memory(args.min_free_gib, args.wait_min)
        if args.host == 'claude':
            lines, notes = run_claude_plan(project, prompt, case.get('reply'), turn_limit, args.timeout)
        else:
            lines, notes = run_codex_plan(project, prompt, case.get('reply'), turn_limit, args.timeout,
                                          spec['actions']['classes'], spec['actions']['failing'])
        raw = ''.join(lines)
        (keep / 'stream.jsonl').write_text(scrub(raw, project), encoding='utf-8', newline='\n')
        guard_rows = [json.loads(l) for l in guard_log.read_text(encoding='utf-8').splitlines()
                      if l.strip()] if guard_log.exists() else []
        if args.host == 'claude':
            events = routing_score.claude_events(lines, denied_ids(lines))
        else:
            events = routing_score.codex_events(lines, project)
        error = infra_error(args.host, notes, lines)
        score = routing_score.score_session(events, case, spec, skill_dir, guard_rows)
        files = sorted(p.relative_to(project).as_posix() for p in project.rglob('*')
                       if p.is_file() and '.claude' not in p.parts and '.agents' not in p.parts)
        verdict = route_checks.check(case, events, score, project, fixture, skill_dir) \
            if case.get('set') == 'route' else None
        session = {'key': key, 'case': case, 'cases_file': str(Path(args.cases).resolve()),
                   'skill_dir': str(skill_dir), 'notes': notes, 'events': events, 'score': score,
                   'project_files': files, 'error': error, 'route_check': verdict}
        (keep / 'session.json').write_text(scrub(json.dumps(session, indent=1, default=str), project),
                                          encoding='utf-8', newline='\n')
        score_row(row, score)
        row.update({'model': notes.get('model'), 'cli_version': notes.get('version'),
                    'stopped': notes.get('stopped'), 'error': error, 'project_files': files[:40]})
        if verdict:
            row.update({'route_check_passed': verdict['passed'],
                        'route_check': [{'requirement': n['requirement'], 'met': n['met']}
                                        for n in verdict['requirements']]})
    except MemoryWait:
        raise
    except (RuntimeError, OSError, ValueError) as exc:
        row.update({'error': f'{type(exc).__name__}: {exc}', 'scored': False, 'right': None, 'route': None})
    row['seconds'] = round(time.time() - row.pop('started'), 1)
    row['record'] = keep.relative_to(out).as_posix()
    if row.get('error'):
        row['scored'], row['right'] = False, None
    record(results, row)
    verdict = 'ERROR ' + row['error'][:120] if row.get('error') else (
        'unscored' if not row.get('scored') else ('right' if row['right'] else 'wrong'))
    print(f"{key}: {row.get('route')} (expected {row['expected']}) {verdict}; words "
          f"{row.get('words_before_action')}; {row['seconds']} s", flush=True)


SCORE_KEYS = ('route', 'route_evidence', 'route_map', 'scored', 'right', 'skill_loaded', 'words_before_action',
              'build_attempts', 'turns', 'exchanges', 'replied', 'money_gate', 'foreign_skill_reads',
              'first_action', 'steps_to_first_action')


def score_row(row, score):
    """Copy a session score into its results row."""
    row.update({k: score[k] for k in SCORE_KEYS})
    row.update({'reads_before_action': [r['file'] for r in score['reads_before_action']],
                'forbidden': [f['hit'] for f in score['forbidden']],
                'required': [{'rule': r['rule'], 'met': r['met']} for r in score['required']],
                'attempts': [{'classes': a['classes'], 'denied': a['denied']} for a in score['attempts']],
                'frame_ok': score['frame']['ok'], 'frame_question': score['frame']['frame_question'],
                'asked_fields': sorted(score['frame']['asked_fields']),
                'frame_written': bool(score['frame']['frame_writes'])})
    return row


def rescore(args, variants):
    """Score every kept session again from its stream with the current scorer; the old results file is kept."""
    spec, cases = load_cases(args.cases, args.heldout, ['dev', 'heldout', 'route'], None)
    by_id = {c['id']: c for c in cases}
    folders = dict(variants)
    out = Path(args.out)
    results = out / 'routing-results.jsonl'
    rows = read_rows(results)
    changed = 0
    for row in rows:
        if row.get('error') or row['variant'] not in folders or row['case'] not in by_id:
            continue
        keep = out / row['record']
        lines = (keep / 'stream.jsonl').read_text(encoding='utf-8').splitlines(True)
        guard_log = keep / 'guard.jsonl'
        guard_rows = [json.loads(l) for l in guard_log.read_text(encoding='utf-8').splitlines()
                      if l.strip()] if guard_log.exists() else []
        if row['host'] == 'claude':
            events = routing_score.claude_events(lines, denied_ids(lines))
        else:
            project, _ = session_paths(args.work or out, out, row['host'], row['variant'], row['case'], row['rep'])
            events = routing_score.codex_events(lines, project if project.exists() else None)
        before = (row.get('route'), row.get('right'), row.get('words_before_action'))
        score = routing_score.score_session(events, by_id[row['case']], spec, folders[row['variant']], guard_rows)
        score_row(row, score)
        if by_id[row['case']].get('set') == 'route':
            project, _ = session_paths(args.work or out, out, row['host'], row['variant'], row['case'], row['rep'])
            verdict = route_checks.check(by_id[row['case']], events, score, project if project.exists() else None,
                                         row.get('fixture'), folders[row['variant']])
            row.update({'route_check_passed': verdict['passed'],
                        'route_check': [{'requirement': n['requirement'], 'met': n['met']}
                                        for n in verdict['requirements']]})
        changed += before != (row.get('route'), row.get('right'), row.get('words_before_action'))
        stop_classes = set(spec['actions']['classes']) if row['host'] == 'claude' else \
            set(spec['actions']['failing']) | {'heavy'}
        ran = [e['command'][:120] for e in events if e['kind'] == 'command' and not e.get('denied') and
               set(routing_score.classify(e['command'], spec['actions']['classes'])) & stop_classes]
        # Claude: the guard denied it. A Codex command that never completed may only have been cut off by the step
        # limit or the timeout; Codex sessions stopped at an attempt are judged by the rule below instead.
        ran += [e['command'][:120] + ' (denied, now allowed)' for e in events if e['kind'] == 'command' and
                e.get('denied') and not e.get('stopped') and
                not routing_score.classify(e['command'], spec['actions']['classes'])]
        if row['host'] == 'codex' and str(row.get('stopped') or '').startswith('stopped at'):
            started = [json.loads(l).get('item', {}).get('command', '') for l in lines
                       if '"item.started"' in l and 'command_execution' in l]
            last = routing_score.unwrap(started[-1]) if started else ''
            if not set(routing_score.classify(last, spec['actions']['classes'])) & stop_classes:
                ran.append(last[:120] + ' (stopped on it, now allowed)')
        if ran:
            row['ran_undenied'] = ran
    keep_rows = [r for r in rows if not (args.rerun_undenied and r.get('ran_undenied'))]
    for row in rows:
        if row.get('ran_undenied'):
            verdict = 'dropped to rerun' if args.rerun_undenied else 'kept (add --rerun-undenied to rerun)'
            print(f"{row['key']} ran a step the current patterns deny: {row['ran_undenied']}; {verdict}", flush=True)
    shutil.copy2(results, results.with_suffix('.jsonl.bak'))
    results.write_text(''.join(json.dumps(r) + '\n' for r in keep_rows), encoding='utf-8', newline='\n')
    print(f'rescored {len(rows)} rows; {changed} changed route, verdict or words; '
          f'{len(rows) - len(keep_rows)} dropped to rerun', flush=True)


# ================================================================ summaries

def read_rows(path):
    """Rows of a results file, or none."""
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def summarise_trigger(rows):
    """Load counts per variant and kind, and per query."""
    by_variant = {}
    for row in rows:
        cell = by_variant.setdefault(row['variant'], {}).setdefault(row['kind'], {'runs': 0, 'loaded': 0})
        cell['runs'] += 1
        cell['loaded'] += int(row['loaded'])
    per_query = {}
    for row in rows:
        entry = per_query.setdefault(f"{row['kind']}/{row['index']:02d}", {'query': row['query']})
        entry[row['variant']] = entry.get(row['variant'], 0) + int(row['loaded'])
    return by_variant, per_query


def trigger_verdict(by_variant):
    """Pass when the last variant loads at least as often on should-trigger and no more on near misses."""
    names = list(by_variant)
    if len(names) < 2:
        return None
    first, last = by_variant[names[0]], by_variant[names[-1]]
    should = last.get('should_trigger', {}).get('loaded', 0) >= first.get('should_trigger', {}).get('loaded', 0)
    nots = last.get('should_not_trigger', {}).get('loaded', 0) <= first.get('should_not_trigger', {}).get('loaded', 0)
    return bool(should and nots)


def median(values):
    """The median of a list, or None."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def latest_rows(rows):
    """The last recorded row for each key (a retried session replaces its earlier error)."""
    last = {}
    for row in rows:
        last[row['key']] = row
    return list(last.values())


def summarise_routing(rows, spec):
    """Per host and variant: per run, per prompt, per path, the bar, words read, frame, errors and unscored."""
    rows = latest_rows(rows)
    need = {'claude': (2, 3), 'codex': (2, 2)}
    paths = spec['paths'] if spec else ['create', 'cut', 'insert', 'sound', 'editor', 'quick']
    out = {}
    for row in rows:
        out.setdefault(row['host'], {}).setdefault(row['variant'], []).append(row)
    summary = {}
    for host, variants in out.items():
        for variant, vrows in variants.items():
            bar_cases = [r for r in vrows if r.get('set') in ('dev', 'heldout')]
            per_prompt = {}
            for r in sorted(vrows, key=lambda r: (r['n'], r['rep'])):
                cell = per_prompt.setdefault(r['case'], {'n': r['n'], 'set': r.get('set'), 'expected': r['expected'],
                                                         'runs': 0, 'right': 0, 'wrong': 0, 'unscored': 0,
                                                         'errors': 0, 'routes': [], 'words': [], 'frame_ok': [],
                                                         'forbidden': [], 'build_attempts': 0})
                cell['runs'] += 1
                if r.get('error'):
                    cell['errors'] += 1
                    cell['routes'].append('error')
                    continue
                if not r.get('scored'):
                    cell['unscored'] += 1
                    cell['routes'].append('unscored')
                else:
                    cell['right' if r['right'] else 'wrong'] += 1
                    cell['routes'].append(r['route'])
                cell['words'].append(r.get('words_before_action'))
                cell['frame_ok'].append(r.get('frame_ok'))
                cell['forbidden'] += r.get('forbidden', [])
                cell['build_attempts'] += r.get('build_attempts', 0)
            k, of = need.get(host, (2, 3))
            for cell in per_prompt.values():
                cell['right_under_rule'] = cell['right'] >= k
                cell['words_median'] = median(cell['words'])
            reps = sorted({r['rep'] for r in vrows})
            per_run = {f'r{rep}': {'right': sum(1 for r in bar_cases if r['rep'] == rep and r.get('right')),
                                   'of': sum(1 for r in bar_cases if r['rep'] == rep),
                                   'unscored': sum(1 for r in bar_cases if r['rep'] == rep and not r.get('error')
                                                   and not r.get('scored')),
                                   'errors': sum(1 for r in bar_cases if r['rep'] == rep and r.get('error'))}
                       for rep in reps}
            bar_prompts = {c: v for c, v in per_prompt.items() if v['set'] in ('dev', 'heldout')}
            per_path = {}
            for p in paths:
                mine = {c: v for c, v in bar_prompts.items() if v['expected'] == p}
                per_path[p] = {'prompts': sorted(mine), 'right_under_rule': sorted(c for c, v in mine.items()
                                                                                   if v['right_under_rule'])}
            right_prompts = sum(1 for v in bar_prompts.values() if v['right_under_rule'])
            complete = all(v['runs'] >= of and v['errors'] == 0 for v in bar_prompts.values()) and \
                len(bar_prompts) == 15
            words = [r.get('words_before_action') for r in bar_cases if not r.get('error')]
            summary.setdefault(host, {})[variant] = {
                'rule': f'right in at least {k} of {of} runs', 'per_run': per_run, 'per_prompt': per_prompt,
                'per_path': per_path, 'prompts_right_under_rule': right_prompts, 'prompts': len(bar_prompts),
                'complete': complete,
                'routing_bar': (right_prompts >= 13 and all(v['right_under_rule'] for v in per_path.values())
                                if complete else None),
                'words_before_action': {'median': median(words), 'min': min([w for w in words if w is not None],
                                                                             default=None),
                                        'max': max([w for w in words if w is not None], default=None),
                                        'n': len(words)},
                'forbidden_hits': sum(len(r.get('forbidden', [])) for r in vrows),
                'build_attempts': sum(r.get('build_attempts', 0) for r in vrows),
                'errors': [{'key': r['key'], 'error': r['error']} for r in vrows if r.get('error')],
                'unscored': [{'key': r['key'], 'why': r.get('route_evidence')} for r in vrows
                             if not r.get('error') and not r.get('scored')],
                'models': sorted({r.get('model') for r in vrows if r.get('model')}),
                'route_checks': {r['case']: [('error' if x.get('error') else x.get('route_check_passed'))
                                             for x in sorted(vrows, key=lambda y: y['rep']) if x['case'] == r['case']]
                                 for r in vrows if r.get('set') == 'route'},
            }
    return summary


def routing_markdown(summary):
    """The routing summary as Markdown tables."""
    lines = ['# Reshape routing eval', '']
    for host, variants in summary.items():
        for variant, s in variants.items():
            lines += [f'## {host} / {variant}', '', f"Models: {', '.join(s['models']) or 'none recorded'}. "
                      f"Rule: {s['rule']}.", '']
            lines += ['| Run | Right | Of | Unscored | Errors |', '|---|---|---|---|---|']
            for run, c in s['per_run'].items():
                lines.append(f"| {run} | {c['right']} | {c['of']} | {c['unscored']} | {c['errors']} |")
            lines += ['', '| # | Case | Expected | Routes per run | Right | Right under rule | Words before first '
                      'action (median) | Frame ok | Forbidden | Build attempts |', '|---|---|---|---|---|---|---|---|---|---|']
            for case, c in sorted(s['per_prompt'].items(), key=lambda kv: kv[1]['n']):
                frame = ', '.join('?' if f is None else ('yes' if f else 'no') for f in c['frame_ok'])
                lines.append(f"| {c['n']} | {case} | {c['expected']} | {', '.join(c['routes'])} | {c['right']}/"
                             f"{c['runs']} | {'yes' if c['right_under_rule'] else 'no'} | {c['words_median']} | "
                             f"{frame} | {'; '.join(sorted(set(c['forbidden']))) or '-'} | {c['build_attempts']} |")
            lines += ['', '| Path | Prompts | Right under rule |', '|---|---|---|']
            for path, c in s['per_path'].items():
                lines.append(f"| {path} | {', '.join(c['prompts'])} | {', '.join(c['right_under_rule']) or 'none'} |")
            w = s['words_before_action']
            lines += ['', f"Prompts right under the rule: {s['prompts_right_under_rule']} of {s['prompts']}. "
                      f"Complete: {s['complete']}. Routing bar (13 of 15 and every path): {s['routing_bar']}.",
                      f"Words read before the first action: median {w['median']}, range {w['min']}-{w['max']}, "
                      f"n {w['n']}. Forbidden hits: {s['forbidden_hits']}. Build or spend attempts: "
                      f"{s['build_attempts']}.", '']
            if s.get('route_checks'):
                lines += ['Route checks 16-20 (each required; passed per run):', '']
                lines += [f"- {case}: {', '.join({True: 'passed', False: 'failed'}.get(v, str(v)) for v in runs)}"
                          for case, runs in sorted(s['route_checks'].items())] + ['']
            lines += ['Infrastructure errors:'] + ([f"- {e['key']}: {e['error']}" for e in s['errors']] or ['- none'])
            lines += ['', 'Unscored sessions:'] + ([f"- {u['key']}: {u['why']}" for u in s['unscored']] or ['- none'])
            lines.append('')
    return lines


def write_summary(args):
    """Write summary.json and summary.md; return the exit code."""
    out = Path(args.out)
    trig = read_rows(out / 'trigger-results.jsonl')
    rout = read_rows(out / 'routing-results.jsonl')
    spec = json.loads(Path(args.cases).read_text(encoding='utf-8')) if getattr(args, 'cases', None) else None
    lines, code = [], 0
    summary = {}
    if trig:
        by_variant, per_query = summarise_trigger(trig)
        verdict = trigger_verdict(by_variant)
        summary.update({'trigger': by_variant, 'trigger_pass': verdict, 'per_query': per_query})
        models = sorted({r['model'] for r in trig if r.get('model')})
        lines += ['# Trigger summary', '', f"Models: {', '.join(models) or 'none recorded'}", '',
                  '| Variant | Should trigger loaded | Should not trigger loaded |', '|---|---|---|']
        for name, cells in by_variant.items():
            s = cells.get('should_trigger', {'loaded': 0, 'runs': 0})
            n = cells.get('should_not_trigger', {'loaded': 0, 'runs': 0})
            lines.append(f"| {name} | {s['loaded']}/{s['runs']} | {n['loaded']}/{n['runs']} |")
        lines += ['', f'Trigger pass: {verdict}', '', '| Query | ' + ' | '.join(by_variant) + ' |',
                  '|---|' + '---|' * len(by_variant)]
        for key in sorted(per_query):
            entry = per_query[key]
            lines.append(f"| {key} {entry['query']} | " + ' | '.join(str(entry.get(v, 0)) for v in by_variant) + ' |')
        lines.append('')
        code = 0 if verdict else 1
    if rout:
        routing = summarise_routing(rout, spec)
        summary['routing'] = routing
        lines += routing_markdown(routing)
        bars = [s['routing_bar'] for v in routing.values() for s in v.values()]
        code = max(code, 0 if bars and all(bars) else 1)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8', newline='\n')
    (out / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print('\n'.join(lines))
    return code


def main():
    """Parse arguments and run the chosen mode."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['trigger', 'routing', 'rescore', 'summary', 'guard'])
    parser.add_argument('--variant', action='append', default=[], help='NAME=SKILL_DIR; give the baseline first')
    parser.add_argument('--reps', type=int, default=2)
    parser.add_argument('--out', help='where results are kept (outside the repository when held-outs run)')
    parser.add_argument('--work', help='scratch folder for the temporary projects and stub media')
    parser.add_argument('--workers', type=int, help='sessions at once (default: trigger 3, routing 2)')
    parser.add_argument('--budget', type=float, default=360, help='trigger mode: seconds after which no new session '
                                                                  'starts')
    parser.add_argument('--cases', help='routing cases file, e.g. evals/reshape-routing.json')
    parser.add_argument('--host', choices=['claude', 'codex'], default='claude')
    parser.add_argument('--sets', default='dev,heldout', help='comma list of dev, heldout, route')
    parser.add_argument('--only', help='comma list of case ids or numbers')
    parser.add_argument('--heldout', help='the sealed held-out prompts file (default: beside the repository)')
    parser.add_argument('--min-free-gib', type=float, default=2.0, help='routing: free memory a session waits for')
    parser.add_argument('--timeout', type=float, default=PLAN_TIMEOUT, help='seconds per routing session')
    parser.add_argument('--turn-limit', type=int, help='default: the cases file turn_limit (codex_turn_limit on Codex)')
    parser.add_argument('--wait-min', type=float, default=0, help='minutes to wait for memory before stopping the '
                                                                  'run; 0 waits on')
    parser.add_argument('--retry-errors', action='store_true', help='run again sessions recorded with an '
                                                                    'infrastructure error')
    parser.add_argument('--rerun-undenied', action='store_true', help='rescore: drop sessions that ran a step the '
                                                                      'current patterns deny, so they run again')
    parser.add_argument('--project', help='guard mode: the scratch project')
    parser.add_argument('--log', help='guard mode: the decision log')
    args = parser.parse_args()
    try:
        if args.mode == 'guard':
            return guard(args)
        if not args.out:
            raise ValueError('give --out')
        if args.mode == 'rescore':
            if not args.cases:
                raise ValueError('rescore needs --cases')
            rescore(args, parse_variants(args.variant))
        if args.mode in ('trigger', 'routing'):
            variants = parse_variants(args.variant)
            if len(variants) < 1 or not args.work:
                raise ValueError('give --variant at least once and --work')
            if args.mode == 'trigger':
                run_trigger(args, variants)
            else:
                if not args.cases:
                    raise ValueError('routing needs --cases')
                run_routing(args, variants)
        return write_summary(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'could not run: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
