#!/usr/bin/env python3
"""Test sampled source-shot identity against equal-duration montage controls.

  python evals/prove_montage.py FIXTURES OUTPUT

Uses real CC BY film shots and music, with assemble.py. The bad controls repeat
the first shot after a second shot while keeping duration and audio. These are
not annotated musical beats, validated endings or complete gold films. Rendering
requires the shared heavy-job lock. Exit 0 for separated controls, 1 for a
failed separation, 2 for an operational error.
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


def render(inputs, duration, sequence, destination, scratch):
    """Assemble three selected picture segments and a music stem."""
    scratch.mkdir(parents=True, exist_ok=True)
    sources = {name: {'file': str((inputs / f'shot-{name}.mp4').resolve())} for name in ('a', 'b', 'c')}
    sources['music'] = {'file': str((inputs / 'song.mp3').resolve())}
    lengths = (2.5, 2.5, 3.0) if duration == 8 else (3.0, 3.0, 3.0)
    edit = {'version': 1, 'size': [480, 200], 'fps': 24, 'sources': sources,
            'picture': [{'src': name, 'in': 0, 'out': length} for name, length in zip(sequence, lengths)],
            'audio': [{'track': 'music', 'src': 'music', 'in': 0, 'out': duration, 'at': 0}]}
    P.save_json(scratch / 'edit.json', edit)
    picture = scratch / 'picture.mp4'
    PROOF.command([sys.executable, '-I', '-B', PROOF.SCRIPTS / 'assemble.py', scratch / 'edit.json',
                   '--out', picture, '--json', scratch / 'report.json'], accepted=(0, 1))
    destination.parent.mkdir(parents=True, exist_ok=True)
    PROOF.command(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', picture, '-i', scratch / 'music.wav',
                   '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-movflags', '+faststart',
                   '-shortest', destination])


def main():
    """Render positive and repeated-shot controls and grade their shot sequence."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixtures', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        inputs = args.fixtures / 'inputs'
        root = args.output / 'controls'
        renders = {}
        for duration in (8, 9):
            for side, sequence in (('good', ('a', 'b', 'c')), ('bad', ('a', 'b', 'a'))):
                name = f'{duration}-{side}'
                output = args.output / 'assembly' / name / 'complete.mp4'
                render(inputs, duration, sequence, output, args.output / 'assembly' / name)
                renders[name] = output
        cases = [('montage-beats', 8), ('montage-ending', 9), ('music-visual', 8)]
        for task, duration in cases:
            for side in ('good', 'bad'):
                target = PROOF.candidate(root, task, side) / 'output.mp4'
                shutil.copyfile(renders[f'{duration}-{side}'], target)
        rows = [PROOF.grade_pair(G.tasks(), task, root, args.fixtures, 'shot_sequence') for task, _ in cases]
        report = {'controls': rows, 'passed': sum(row['separated'] for row in rows),
                  'failed': sum(not row['separated'] for row in rows),
                  'scope': 'sampled shot identity only; music and human review remain unassessed'}
        P.save_json(args.output / 'proof.json', report)
        print(json.dumps(report, indent=2))
        return 1 if report['failed'] else 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
