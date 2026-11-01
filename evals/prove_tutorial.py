#!/usr/bin/env python3
"""Test the planted tutorial pointer on equal-duration vertical edits.

  python evals/prove_tutorial.py FIXTURES OUTPUT

Creates a contained view and a centre crop with assemble.py. The latter loses the
red synthetic pointer at some steps. This checks the planted colour only; text
legibility and instruction quality remain unjudged. It renders; run one heavy job at a time.
Exit 0 for separation, 1 for a mismatch, 2 on error.
"""
import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('eval_prove_media', HERE / 'prove_media.py')
PROOF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROOF)
P = PROOF.P
G = PROOF.G


def render(source, fit, output, scratch):
    """Assemble all three steps into a vertical frame with a fixed fit mode."""
    scratch.mkdir(parents=True, exist_ok=True)
    edit = {'version': 1, 'size': [270, 480], 'fps': 15, 'sources': {'a': {'file': str(source.resolve())}},
            'picture': [{'src': 'a', 'in': start, 'out': end, 'fit': fit}
                        for start, end in ((0, 2), (4, 6), (8, 10))]}
    P.save_json(scratch / 'edit.json', edit)
    picture = scratch / 'picture.mp4'
    PROOF.command([sys.executable, '-I', '-B', PROOF.SCRIPTS / 'assemble.py', scratch / 'edit.json',
                   '--out', picture, '--json', scratch / 'report.json'], accepted=(0, 1))
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(picture, output)


def main():
    """Render and grade two equal-duration vertical tutorial controls."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixtures', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        root = args.output / 'controls'
        for side, fit in (('good', 'contain'), ('bad', 'cover')):
            output = PROOF.candidate(root, 'tutorial-small', side) / 'output.mp4'
            render(args.fixtures / 'inputs/tutorial.mp4', fit, output, args.output / 'assembly' / side)
        row = PROOF.grade_pair(G.tasks(), 'tutorial-small', root, args.fixtures, 'cursor_presence')
        report = {'controls': [row], 'passed': int(row['separated']), 'failed': int(not row['separated']),
                  'scope': 'sampled synthetic pointer only; text readability remains unassessed'}
        P.save_json(args.output / 'proof.json', report)
        print(json.dumps(report, indent=2))
        return 0 if row['separated'] else 1
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
