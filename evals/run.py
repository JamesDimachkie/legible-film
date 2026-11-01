#!/usr/bin/env python3
"""Stage and optionally run a fresh local video-editing evaluation.

  python evals/run.py TASK --fixtures FIXTURES --runs RUNS --runner codex --arm with
  python evals/run.py --kind interview --fixtures FIXTURES --runs RUNS --runner codex --arm with
  python evals/run.py --all --fixtures FIXTURES --runs RUNS --runner codex --arm with
  python evals/run.py --hash-skill EXPORTED_SKILL
  python evals/run.py TASK --fixtures FIXTURES --runs RUNS --runner claude --arm without --execute
  python evals/run.py TASK --fixtures FIXTURES --runs RUNS --runner codex --arm earlier
      --earlier-skill EXPORTED_SKILL --earlier-ref REF --earlier-sha256 TREE_HASH --execute

Staging is the default. A real agent may use hosted inference, access user settings,
or run tools. This script does not enforce network or billing isolation: use an
appropriate external sandbox and explicit authorization before --execute. Never
put credentials into a run folder. An earlier arm is a pre-exported, content-pinned
skill; the ref label is declared, not verified by a Git command. The explicit path
in the prompt is used because project-local Codex skill discovery is unverified.
Exit 0 for a successfully staged run or successful process, 1 for a process error,
2 for an invalid setup.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SKILL = HERE.parent / 'skills' / 'legible-film'
SPEC = importlib.util.spec_from_file_location('eval_grade_task', HERE / 'grade_task.py')
grade_task = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grade_task)
P = grade_task.P


def hash_file(path):
    """Return the SHA-256 of one file without loading it all at once."""
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def tree_hash(path):
    """Hash each relative path and file content to pin an exported skill tree."""
    digest = hashlib.sha256()
    files = sorted(item for item in path.rglob('*')
                   if item.is_file() and '__pycache__' not in item.parts and item.suffix != '.pyc')
    for item in files:
        relative = item.relative_to(path).as_posix()
        digest.update(relative.encode('utf-8') + b'\0' + hash_file(item).encode('ascii') + b'\n')
    return digest.hexdigest()


def inventory(root):
    """Track workspace file contents while excluding the installed skill copy."""
    result = {}
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[relative] = {'type': 'symlink', 'target': 'not read'}
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        if not path.is_file() or any(part in ('.claude', '.agents') for part in path.relative_to(root).parts):
            continue
        result[relative] = {'bytes': path.stat().st_size, 'sha256': hash_file(path)}
    return result


def prepare(task, fixtures, run, arm, runner, earlier_skill=None, earlier_ref=None, earlier_hash=None):
    """Copy only task inputs into an empty workspace and install a run-local skill if needed."""
    workspace = run / 'workspace'
    workspace.mkdir(parents=True, exist_ok=False)
    inputs = fixtures / 'inputs'
    for dest, source in task['inputs'].items():
        original = grade_task.under(inputs, source)
        target = grade_task.under(workspace, dest)
        if not original.is_file():
            raise ValueError(f'missing fixture input: {source}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        preserved = grade_task.under(run / 'original-inputs', dest)
        preserved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, preserved)
    prompt = task['request']
    skill_tree = None
    if arm in ('with', 'earlier'):
        skill_tree = SKILL if arm == 'with' else earlier_skill
        if not skill_tree or not skill_tree.is_dir() or not (skill_tree / 'SKILL.md').is_file():
            raise ValueError('the selected skill folder must contain SKILL.md')
        actual_hash = tree_hash(skill_tree)
        if arm == 'earlier' and (not earlier_ref or not earlier_hash or actual_hash != earlier_hash):
            raise ValueError(f'earlier arm needs a ref label and matching tree hash; actual tree={actual_hash}')
        skill_path = workspace / ('.claude' if runner == 'claude' else '.agents') / 'skills' / 'legible-film'
        shutil.copytree(skill_tree, skill_path, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        if tree_hash(skill_path) != actual_hash:
            raise ValueError('installed skill differs from the selected source tree')
        prompt += '\n\nUse the Legible Film skill: read ' + skill_path.relative_to(workspace).as_posix() + '/SKILL.md.'
    else:
        actual_hash = None
    before = inventory(workspace)
    metadata = {'version': 1, 'task': task['id'], 'kind': task['kind'], 'arm': arm, 'runner': runner,
                'skill_tree_sha256': actual_hash, 'earlier_ref_declared': earlier_ref if arm == 'earlier' else None,
                'skill_loading': ('explicit project-local path' if skill_tree else
                                  'none staged; ambient skills unverified'),
                'input_inventory': before, 'request': task['request'], 'prompt': prompt, 'state': 'staged',
                'network_isolation': 'not enforced', 'config_isolation': 'not independently verified'}
    P.save_json(run / 'run.json', metadata)
    return workspace, prompt, before, metadata


def cli(runner, prompt, workspace, turns):
    """Construct foreground commands without Git or settings changes."""
    if runner == 'claude':
        executable = shutil.which('claude.exe') or shutil.which('claude')
        if not executable:
            raise ValueError('claude executable not found')
        return [executable, '-p', prompt, '--output-format', 'stream-json', '--verbose', '--max-turns', str(turns),
                '--setting-sources', 'project', '--strict-mcp-config', '--no-session-persistence']
    executable = shutil.which('codex.exe') or shutil.which('codex')
    if not executable:
        raise ValueError('codex executable not found')
    return [executable, 'exec', '--json', '--skip-git-repo-check', '--ephemeral', '--ignore-user-config',
            '--sandbox', 'workspace-write', '-C', str(workspace), prompt]


def parse_events(path, runner):
    """Read stream JSONL without discarding the complete source transcript."""
    tools = {}
    turns = 0
    final = ''
    usage = None
    usage_events = []
    cost = None
    errors = []
    questions = []
    events_seen = 0

    def capture_questions(text):
        """Keep question-shaped snippets from assistant text as a review aid."""
        for line in str(text).splitlines():
            for match in re.findall(r'[^?]*\?', line):
                item = match.strip()
                if item and item not in questions:
                    questions.append(item)

    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            errors.append('non-JSON line in transcript')
            continue
        if not isinstance(event, dict):
            errors.append('non-object JSON line in transcript')
            continue
        events_seen += 1
        kind = event.get('type')
        if runner == 'claude' and kind == 'assistant':
            for part in event.get('message', {}).get('content', []):
                if part.get('type') == 'tool_use':
                    name = part.get('name', 'unknown')
                    tools[name] = tools.get(name, 0) + 1
                elif part.get('type') == 'text':
                    final = str(part.get('text') or '')
                    capture_questions(final)
        elif runner == 'claude' and kind == 'result':
            turns = event.get('num_turns')
            if event.get('result') is not None:
                final = str(event['result'])
            capture_questions(final)
            cost = event.get('total_cost_usd')
            usage = event.get('usage')
            if usage:
                usage_events.append(usage)
            if event.get('is_error') or str(event.get('subtype', '')).startswith('error'):
                errors.append(str(event.get('subtype') or 'Claude reported an error'))
        elif runner == 'codex' and kind == 'item.completed':
            item = event.get('item', {})
            item_type = item.get('type', '')
            if item_type == 'agent_message':
                final = str(item.get('text') or '')
                capture_questions(final)
            elif item_type in ('command_execution', 'file_change', 'mcp_tool_call', 'web_search'):
                tools[item_type] = tools.get(item_type, 0) + 1
        elif runner == 'codex' and kind == 'turn.completed':
            turns += 1
            usage = event.get('usage')
            if usage:
                usage_events.append(usage)
        elif kind in ('error', 'turn.failed'):
            errors.append(str(event.get('message') or event.get('error') or kind))
    if not events_seen:
        errors.append('no JSON events were captured')
    return {'turns': turns, 'tool_calls': sum(tools.values()), 'tools': tools, 'usage': usage,
            'usage_events': usage_events, 'cost_usd': cost, 'questions': questions,
            'question_marks_in_final': final.count('?'), 'final': final, 'errors': errors}


def run_command(command, workspace, transcript, error_file, timeout):
    """Run one foreground client and preserve stdout and stderr independently."""
    started = time.monotonic()
    temporary = (transcript.parent / 'temporary').resolve()
    temporary.mkdir(exist_ok=True)
    environment = dict(os.environ)
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        environment[name] = str(temporary)
    with transcript.open('w', encoding='utf-8', newline='\n') as out, error_file.open(
            'w', encoding='utf-8', newline='\n') as err:
        try:
            result = subprocess.run(command, cwd=workspace, stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                                    timeout=timeout, env=environment)
            return result.returncode, round(time.monotonic() - started, 3), False
        except subprocess.TimeoutExpired:
            return 124, round(time.monotonic() - started, 3), True


def run_one(task, args):
    """Stage one task and, if selected, run a single foreground client."""
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run = args.runs / (stamp + '-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True, exist_ok=False)
    workspace, prompt, before, metadata = prepare(task, args.fixtures, run, args.arm, args.runner,
                                                  args.earlier_skill, args.earlier_ref, args.earlier_sha256)
    metadata['producer_family'] = args.producer_family
    metadata['turn_limit'] = args.max_turns if args.runner == 'claude' else None
    P.save_json(run / 'run.json', metadata)
    if not args.execute:
        print(f'staged {run}; no agent started')
        return 0
    command = cli(args.runner, prompt, workspace, args.max_turns)
    code, elapsed, timeout = run_command(command, workspace, run / 'transcript.jsonl', run / 'stderr.txt',
                                         args.timeout)
    summary = parse_events(run / 'transcript.jsonl', args.runner)
    final = summary.pop('final')
    P.write_atomic(run / 'final.txt', final + '\n')
    after = inventory(workspace)
    changed = {name: info for name, info in after.items() if before.get(name) != info}
    removed = sorted(set(before) - set(after))
    deliverables = {rule['path']: after[rule['path']] for rule in task['automatic']
                    if rule.get('path') in after and rule.get('method') in
                    ('video', 'exists', 'captions', 'caption_changes')}
    metadata.update({'state': 'finished' if code == 0 and not timeout and not summary['errors'] else 'failed',
                     'exit_code': code,
                     'timeout': timeout, 'wall_seconds': elapsed, 'files_written_or_changed': changed,
                     'files_removed': removed, 'deliverables': deliverables, **summary})
    P.save_json(run / 'run.json', metadata)
    print(f'{metadata["state"]}: {run}; {elapsed}s; exit {code}')
    return 0 if metadata['state'] == 'finished' else 1


def main():
    """Stage or execute one task; never overwrite an existing run."""
    if len(sys.argv) == 3 and sys.argv[1] == '--hash-skill':
        skill_path = Path(sys.argv[2])
        if not (skill_path / 'SKILL.md').is_file():
            print('skill folder must contain SKILL.md', file=sys.stderr)
            return 2
        print(tree_hash(skill_path))
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('task', nargs='?')
    parser.add_argument('--kind')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--fixtures', required=True, type=Path)
    parser.add_argument('--runs', required=True, type=Path)
    parser.add_argument('--runner', choices=('claude', 'codex'), required=True)
    parser.add_argument('--arm', choices=('with', 'without', 'earlier'), required=True)
    parser.add_argument('--earlier-skill', type=Path)
    parser.add_argument('--earlier-ref')
    parser.add_argument('--earlier-sha256')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--max-turns', type=int, default=80)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--producer-family', help='record the actual producer family for independent judging')
    args = parser.parse_args()
    try:
        catalogue = grade_task.tasks()
        if sum(bool(value) for value in (args.task, args.kind, args.all)) != 1:
            raise ValueError('choose exactly one task, --kind or --all')
        if args.task:
            selected = [catalogue[args.task]]
        elif args.kind:
            selected = [task for task in catalogue.values() if task['kind'] == args.kind]
            if not selected:
                raise ValueError(f'unknown kind: {args.kind}')
        else:
            selected = list(catalogue.values())
        if args.max_turns <= 0 or args.timeout <= 0:
            raise ValueError('turn and timeout limits must be positive')
        codes = [run_one(task, args) for task in selected]
        return 1 if any(codes) else 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
