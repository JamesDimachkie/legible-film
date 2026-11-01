#!/usr/bin/env python3
"""Summarise graded runs by video kind, criterion and arm.

  python evals/report.py RUNS_DIR [--out report.md]

Only observed grades enter the denominator. Unknown or unrun checks are shown
separately, never counted as passes or failures. Scorecard and process means use
only reported values. This does not establish perceptual quality or statistical
significance. Exit 0 on success, 2 on invalid input.
"""
import argparse
import importlib.util
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('eval_grade_task', HERE / 'grade_task.py')
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
P = G.P


def load_runs(root):
    """Read run metadata and its optional grade, ignoring unrelated files."""
    result = []
    for path in sorted(root.rglob('run.json')):
        run = P.load_json(path)
        grade_path = path.parent / 'grade.json'
        grade = P.load_json(grade_path, None)
        result.append({'run': run, 'grade': grade, 'folder': path.parent})
    return result


def fraction(states):
    """Show the pass denominator, review prompts and unrun checks separately."""
    passed = states.count('pass')
    failed = states.count('fail')
    review = states.count('review')
    missing = len(states) - passed - failed - review
    return f'{passed}/{passed + failed}; {review} review, {missing} not run'


def average(values):
    """Round a mean, or return an explicit absence of measurements."""
    numbers = [value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool)]
    return f'{statistics.mean(numbers):.2f}' if numbers else 'not reported'


def recipe_location(task):
    """Resolve a task's recipe heading to its actual source line, when present."""
    path_part, _, anchor = task['recipe'].partition('#')
    path = HERE.parent / path_part
    if not path.is_file():
        return task['recipe']
    for number, line in enumerate(P.read_text(path).splitlines(), 1):
        if line.startswith('## '):
            slug = re.sub(r'[^a-z0-9 -]', '', line[3:].lower()).replace(' ', '-')
            if slug == anchor:
                return f'{path_part}:{number}'
    return task['recipe']


def summary(records, catalogue):
    """Write one table per kind plus process and evidence coverage."""
    by_kind = defaultdict(list)
    for item in records:
        by_kind[item['run'].get('kind', 'unknown')].append(item)
    output = ['# Legible Film evaluation report', '',
              'Review means measured and awaiting interpretation; not run includes unavailable checks and '
              'missing independent review. The denominator contains only pass and fail.', '']
    arms = ('with', 'without', 'earlier')
    for kind in sorted(by_kind):
        items = by_kind[kind]
        output.extend([f'## {kind}', '', '| Task and criterion | With | Without | Earlier |',
                       '|---|---:|---:|---:|'])
        grouped = defaultdict(lambda: defaultdict(list))
        for item in items:
            if not item['grade']:
                continue
            task_id = item['grade'].get('task', item['run'].get('task', '?'))
            arm = item['run'].get('arm', '?')
            for check in item['grade'].get('checks', []):
                grouped[(task_id, check['id'])][arm].append(check.get('state', 'not_run'))
        if not grouped:
            output.append('| No grades available | - | - | - |')
        for (task_id, criterion), values in sorted(grouped.items()):
            cells = [fraction(values[arm]) if values[arm] else 'no runs' for arm in arms]
            output.append(f'| {task_id}: {criterion} | ' + ' | '.join(cells) + ' |')
        output.extend(['', '| Arm | Runs | Mean seconds | Mean turns | Mean tool calls | Cost reported |',
                       '|---|---:|---:|---:|---:|---:|'])
        for arm in arms:
            members = [item['run'] for item in items if item['run'].get('arm') == arm and
                       item['run'].get('state') in ('finished', 'failed')]
            if not members:
                continue
            costs = [run['cost_usd'] for run in members if isinstance(run.get('cost_usd'), (int, float))]
            cost = f'${sum(costs):.4f}; {len(members) - len(costs)} unreported' if costs else 'not reported'
            cells = [arm, str(len(members)), average([run.get('wall_seconds') for run in members]),
                     average([run.get('turns') for run in members]),
                     average([run.get('tool_calls') for run in members]), cost]
            output.append('| ' + ' | '.join(cells) + ' |')
        output.extend(['', '| Scorecard dimension | With mean | Without mean | Earlier mean |',
                       '|---|---:|---:|---:|'])
        scores = defaultdict(lambda: defaultdict(list))
        for item in items:
            arm = item['run'].get('arm', '?')
            for check in (item['grade'] or {}).get('checks', []):
                if check['id'].startswith('scorecard:') and isinstance(check.get('score'), (int, float)):
                    scores[check['id']][arm].append(check['score'])
        if not scores:
            output.append('| No bound scores | - | - | - |')
        for name, values in sorted(scores.items()):
            output.append('| ' + name.removeprefix('scorecard:') + ' | ' +
                          ' | '.join(average(values[arm]) for arm in arms) + ' |')
        staged = sum(item['run'].get('state') == 'staged' for item in items)
        ungraded = sum(item['grade'] is None for item in items)
        output.extend(['', f'{staged} staged without execution; {ungraded} records have no grade.',
                       'Arm isolation and independent reviewer provenance must be checked in each run record.', ''])
        failures = []
        for item in items:
            grade = item['grade'] or {}
            task_id = grade.get('task')
            for check in grade.get('checks', []):
                if check.get('state') == 'fail':
                    location = recipe_location(catalogue[task_id]) if task_id in catalogue else 'recipe unknown'
                    failures.append(f'- {task_id}, {check["id"]}: {check.get("detail", "")}; '
                                    f'recipe to inspect: {location}')
        output.append('Failures to investigate:')
        output.append('')
        output.extend(failures or ['- None recorded; this does not imply unrun criteria passed.'])
        output.append('')
    if not by_kind:
        output.append('No run records found.')
    return '\n'.join(output) + '\n'


def main():
    """Render a Markdown report from a folder of run records."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('runs', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        if not args.runs.is_dir():
            raise ValueError('runs directory does not exist')
        text = summary(load_runs(args.runs), G.tasks())
        if args.out:
            P.write_atomic(args.out, text)
        else:
            print(text, end='')
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
