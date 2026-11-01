#!/usr/bin/env python3
"""Measure whether a SKILL.md triggers, and where it routes, in fresh Claude Code sessions.

  python evals/trigger_run.py trigger --variant old=OLD_SKILL_DIR --variant new=NEW_SKILL_DIR
      --reps 2 --out evals/results/RUN --work SCRATCH [--workers 3] [--budget 360]
  python evals/trigger_run.py routing --variant old=OLD_SKILL_DIR --variant new=NEW_SKILL_DIR
      --reps 2 --out evals/results/RUN --work SCRATCH
  python evals/trigger_run.py summary --out evals/results/RUN

trigger: for every query in evals/trigger-queries.json, each variant and each repetition, starts a fresh
`claude -p` session in a temporary project whose only skill is the variant under .claude/skills/legible-film/
(its SKILL.md and references/), with project settings only, no MCP servers, read-only tools (Skill, Read, Glob,
Grep), at most three turns and no saved session. A query counts as loaded when the session's stream JSON shows a
Skill tool call for legible-film or a Read of its SKILL.md; the session is stopped (by its own PID) as soon as it
does. Every stream is kept under OUT/runs/trigger/.

routing: asks a fresh session, for each of four fixed requests, which commands it would run first and which
reference it would read, without running anything (the Skill tool only). The transcript and answer are kept under
OUT/runs/routing/; each answer is scored against the expected first command and reference for that request.

summary: writes OUT/summary.json and OUT/summary.md from what is recorded. Pass for triggering: the last variant
loads at least as often as the first on should-trigger queries and no more often on should-not-trigger ones.

Runs already recorded are skipped, so a run stopped by --budget (seconds before no new session starts) resumes
where it left off. Local paths (the temporary project, the home folder) are replaced by <PROJECT> and <HOME> in
everything kept. The sessions use the signed-in Claude account and hosted inference: the queries and the skill
text go to the model provider. It does not prove how the skill behaves with other skills installed, under other
harnesses or models, or on later turns of a conversation; the routing score matches names in the answer and is
not a judgement of the plan.

Exit codes: 0 every recorded comparison passes, 1 a comparison fails or runs are missing, 2 could not run.
"""
import argparse
import concurrent.futures
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
QUERIES = HERE / 'trigger-queries.json'
SKILL_NAME = 'legible-film'
TOOLS_TRIGGER = 'Skill,Read,Glob,Grep'
TIMEOUT = 180
ROUTING = [
    {
        'id': 'quick-916',
        'request': 'Trim the first 4 seconds off clip.mp4 and make a 9:16 version of it.',
        'commands': ['ffprobe', 'ffmpeg', 'reframe.py'],
        'forbidden': ['project.py init', 'map.py'],
        'references': ['recipes.md'],
    },
    {
        'id': 'interview-story',
        'request': 'Cut a 60-second story from interview.mp4 (a 40-minute interview).',
        'commands': ['project.py init', 'map.py add', 'setup.py'],
        'forbidden': [],
        'references': ['loop.md', 'finding-the-story.md', 'recipes.md', 'project.md', 'paper-edit.md'],
    },
    {
        'id': 'check-youtube',
        'request': 'Check this exported file, final.mp4, before I upload it to YouTube.',
        'commands': ['check.py --file', 'qc_file.py', 'grade.py --file', 'setup.py'],
        'forbidden': ['project.py init'],
        'references': ['qc.md', 'formats.md'],
    },
    {
        'id': 'premiere-stale',
        'request': ('An editor sent two Premiere exports of the same sequence (v1.xml with v1.mp4 and v1.srt, then '
                    'v2.xml with v2.mp4). Follow them and say which captions are stale.'),
        'commands': ['exchange.py compare', 'exchange.py read', 'map.py add', 'setup.py'],
        'forbidden': [],
        'references': ['recipes.md'],
    },
]
ROUTING_ASK = ('\n\nUse the legible-film skill. Do not run, read or create anything beyond loading the skill. '
               'Answer in a few lines: (1) the first commands you would run, in order, and (2) which file or '
               'files in the skill\'s references/ folder you would read first, and when.')
LOCK = threading.Lock()


def parse_variants(items):
    """Turn NAME=SKILL_DIR arguments into an ordered list of (name, Path)."""
    out = []
    for item in items:
        name, _, path = item.partition('=')
        folder = Path(path)
        if not name or not (folder / 'SKILL.md').is_file():
            raise ValueError(f'--variant needs NAME=SKILL_DIR with a SKILL.md: {item}')
        out.append((name, folder))
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

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(one, trigger_jobs(variants, args.reps)))


def score_routing(case, answer):
    """Match an answer's first command and references against what the request expects."""
    low = answer.lower()
    hits = [(low.find(c.lower()), c) for c in case['commands'] if c.lower() in low]
    first = min(hits)[1] if hits else None
    refs = sorted(set(re.findall(r'([a-z][a-z-]*\.md)', low)) - {'skill.md'})
    return {'first_expected_command': first,
            'command_ok': bool(hits),
            'forbidden_named': [f for f in case['forbidden'] if f.lower() in low],
            'references_named': refs,
            'reference_ok': any(r in refs for r in case['references'])}


def run_routing(args, variants):
    """Ask each variant how it would start each routing request; keep transcripts and scores."""
    out = Path(args.out) / 'runs' / 'routing'
    out.mkdir(parents=True, exist_ok=True)
    results = Path(args.out) / 'routing-results.jsonl'
    projects = {name: stage_project(args.work, name, folder) for name, folder in variants}
    seen = done_keys(results)
    deadline = time.time() + args.budget
    jobs = [(name, case, rep) for rep in range(1, args.reps + 1) for name, _ in variants for case in ROUTING]

    def one(job):
        name, case, rep = job
        key = f"{name}/{case['id']}/r{rep}"
        if key in seen or time.time() > deadline:
            return None
        raw = out / f"{name}-{case['id']}-r{rep}.jsonl"
        got = run_session(projects[name], case['request'] + ROUTING_ASK, 'Skill', raw, stop_on_load=False)
        answer_path = out / f"{name}-{case['id']}-r{rep}.md"
        answer_path.parent.mkdir(parents=True, exist_ok=True)
        answer_path.write_text(f"# {key}\n\nRequest: {case['request']}\n\n{got['text']}\n", encoding='utf-8',
                               newline='\n')
        row = {'key': key, 'variant': name, 'case': case['id'], 'rep': rep, 'loaded': got['loaded'],
               'model': got['model'], 'seconds': got['seconds'], 'timed_out': got['timed_out'],
               'answer': answer_path.relative_to(Path(args.out)).as_posix()}
        row.update(score_routing(case, got['text']))
        record(results, row)
        print(f"{key}: command {row['first_expected_command']}, references {row['references_named']}", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(one, jobs))


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


def summarise_routing(rows):
    """Command and reference matches per variant and case."""
    out = {}
    for row in rows:
        cell = out.setdefault(row['variant'], {}).setdefault(row['case'], [])
        cell.append({'rep': row['rep'], 'command': row['first_expected_command'], 'command_ok': row['command_ok'],
                     'forbidden': row['forbidden_named'], 'references': row['references_named'],
                     'reference_ok': row['reference_ok']})
    return out


def trigger_verdict(by_variant):
    """Pass when the last variant loads at least as often on should-trigger and no more on near misses."""
    names = list(by_variant)
    if len(names) < 2:
        return None
    first, last = by_variant[names[0]], by_variant[names[-1]]
    should = last.get('should_trigger', {}).get('loaded', 0) >= first.get('should_trigger', {}).get('loaded', 0)
    nots = last.get('should_not_trigger', {}).get('loaded', 0) <= first.get('should_not_trigger', {}).get('loaded', 0)
    return bool(should and nots)


def write_summary(args):
    """Write summary.json and summary.md; return the exit code."""
    out = Path(args.out)
    trig = read_rows(out / 'trigger-results.jsonl')
    rout = read_rows(out / 'routing-results.jsonl')
    by_variant, per_query = summarise_trigger(trig)
    routing = summarise_routing(rout)
    verdict = trigger_verdict(by_variant)
    models = sorted({r['model'] for r in trig + rout if r.get('model')})
    summary = {'models': models, 'trigger': by_variant, 'trigger_pass': verdict, 'per_query': per_query,
               'routing': routing}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8', newline='\n')
    lines = ['# Trigger and routing summary', '', f"Models: {', '.join(models) or 'none recorded'}", '',
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
    lines += ['', '| Variant | Case | Rep | First expected command | Forbidden named | References named | Ref ok |',
              '|---|---|---|---|---|---|---|']
    for name, cases in routing.items():
        for case, reps in cases.items():
            for r in reps:
                lines.append(f"| {name} | {case} | {r['rep']} | {r['command']} | {', '.join(r['forbidden'])} | "
                             f"{', '.join(r['references'])} | {r['reference_ok']} |")
    (out / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    print('\n'.join(lines))
    complete_routing = all(r['command_ok'] and r['reference_ok'] and not r['forbidden'] for c in routing.values()
                           for reps in c.values() for r in reps)
    return 0 if verdict and complete_routing else 1


def main():
    """Parse arguments and run the chosen mode."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('mode', choices=['trigger', 'routing', 'summary'])
    parser.add_argument('--variant', action='append', default=[], help='NAME=SKILL_DIR; give the baseline first')
    parser.add_argument('--reps', type=int, default=2)
    parser.add_argument('--out', required=True)
    parser.add_argument('--work', help='scratch folder for the temporary projects')
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--budget', type=float, default=360, help='seconds after which no new session starts')
    args = parser.parse_args()
    try:
        if args.mode != 'summary':
            variants = parse_variants(args.variant)
            if len(variants) < 1 or not args.work:
                raise ValueError('give --variant at least once and --work')
            if args.mode == 'trigger':
                run_trigger(args, variants)
            else:
                run_routing(args, variants)
        return write_summary(args)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'could not run: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
