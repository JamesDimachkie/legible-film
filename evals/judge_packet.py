#!/usr/bin/env python3
"""Create a neutral, local packet for an independent reviewer.

  python evals/judge_packet.py TASK --run RUN --out NEW_PACKET_FOLDER
  python evals/judge_packet.py TASK --run RUN --out NEW_PACKET_FOLDER --sheets

The packet contains the request, task-specific rubric, inputs, deliverables and
their hashes, but no run metadata, arm name or tool transcript. It is not uploaded.
Text or media metadata can still reveal the arm; inspect before sending. A stills-
only model cannot satisfy a normal-speed human viewing or listening requirement.
--sheets renders sampled contact sheets: run one heavy job at a time.
Exit 0 on success, 2 on invalid input.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('eval_grade_task', HERE / 'grade_task.py')
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
P = G.P


def digest(path):
    """Hash a packet file without holding it all in memory."""
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def copy_file(source, destination, label):
    """Copy one item to a neutral name and record its content hash."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {'label': label, 'file': destination.parent.name + '/' + destination.name,
            'sha256': digest(destination)}


def packet(task, run, output, sheets=False):
    """Build a packet without the arm, model, skill instructions or execution trace."""
    workspace = run / 'workspace' if (run / 'workspace').is_dir() else run
    output.mkdir(parents=True, exist_ok=False)
    inputs = []
    for index, name in enumerate(task['inputs'], 1):
        originals = run / 'original-inputs'
        source = G.under(originals if originals.is_dir() else workspace, name)
        if not source.is_file():
            raise ValueError(f'missing original task input: {name}')
        target = output / 'inputs' / f'input-{index:02}{source.suffix.lower()}'
        inputs.append(copy_file(source, target, name))
    requested = []
    for rule in task['automatic']:
        name = rule.get('path')
        if name and name not in requested:
            requested.append(name)
    artifacts = []
    for index, name in enumerate(requested, 1):
        source = G.under(workspace, name)
        if source.is_file():
            target = output / 'artifacts' / f'artifact-{index:02}{source.suffix.lower()}'
            artifacts.append(copy_file(source, target, name))
    frames = []
    if sheets:
        for index, row in enumerate(artifacts, 1):
            source = G.under(output, row['file'])
            if source.suffix.lower() not in ('.mp4', '.mov', '.webm'):
                continue
            directory = output / 'sheets'
            directory.mkdir(exist_ok=True)
            sheet = directory / f'sheet-{index:02}.png'
            command = [sys.executable, '-I', '-B', str(HERE.parent / 'skills/legible-film/scripts/frame_sheet.py'),
                       str(source), '--every', '1', '--out', str(sheet), '--width', '240', '--per-sheet', '60']
            temporary = (output / 'temporary').resolve()
            temporary.mkdir(exist_ok=True)
            environment = dict(os.environ)
            for name in ('TEMP', 'TMP', 'TMPDIR'):
                environment[name] = str(temporary)
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                    env=environment)
            if result.returncode:
                raise ValueError('contact sheet failed: ' + (result.stderr + result.stdout)[-500:])
            for image in sorted(directory.glob(f'sheet-{index:02}*.png')):
                frames.append({'file': 'sheets/' + image.name, 'sha256': digest(image), 'source': row['label']})
    response = run / 'final.txt'
    if response.is_file():
        target = output / 'artifacts' / 'response.txt'
        artifacts.append(copy_file(response, target, 'response'))
    data = {'version': 1, 'packet_id': uuid.uuid4().hex, 'task': task['id'], 'request': task['request'],
            'inputs': inputs, 'artifacts': artifacts, 'sheets': frames, 'review_criteria': task['review'],
            'scorecard_dimensions': task['scorecard_dimensions'],
            'instructions': ['Use an independent model family or a person.',
                             'Give a state and specific evidence for each criterion.',
                             'Do not infer audio quality from frames or a person\'s approval from metrics.',
                             'Check names and metadata for arm identifiers before using this packet.']}
    P.save_json(output / 'packet.json', data)
    template = {'version': 1, 'packet_id': data['packet_id'], 'packet_sha256': digest(output / 'packet.json'),
                'reviewer': {'type': '', 'family': ''}, 'producer_family': '',
                'criteria': [{'id': item['id'], 'state': 'not_run', 'evidence': ''} for item in task['review']]}
    P.save_json(output / 'judgment-template.json', template)
    return data


def main():
    """Create a fresh packet directory; refuse to overwrite earlier evidence."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('task')
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--sheets', action='store_true')
    args = parser.parse_args()
    try:
        task = G.tasks()[args.task]
        if not args.run.is_dir():
            raise ValueError('run directory does not exist')
        data = packet(task, args.run, args.out, args.sheets)
        print(f'packet {data["packet_id"]} written to {args.out}; inspect for identifiers before review')
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
