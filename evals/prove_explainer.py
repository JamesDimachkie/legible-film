#!/usr/bin/env python3
"""Test voice preservation in a real-media explainer and mixed explainer.

  python evals/prove_explainer.py FIXTURES OUTPUT

Assemble CC BY picture, a LibriVox voice excerpt and CC BY music with the skill.
The bad control keeps duration and music but omits the voice. The supplied draft
captions are machine-generated and unverified. Audio matches do not establish
intelligibility or an appropriate mix. It renders: run one heavy job at a time.
Exit 0 for separated controls, 1 for a mismatch, 2 on an operational error.
"""
import argparse
import copy
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


def estimated_boundaries(draft, output):
    """Give a zero-length draft word a bounded estimate by sharing neighboring spans."""
    data = copy.deepcopy(P.load_json(draft))
    words = data['words']
    changes = []
    for index, word in enumerate(words):
        if word['end'] > word['start']:
            continue
        if index == 0 or index == len(words) - 1:
            raise ValueError('cannot estimate an isolated zero-length edge')
        before, after = words[index - 1], words[index + 1]
        centre = float(word['start'])
        radius = min(.02, (before['end'] - before['start']) / 4, (after['end'] - after['start']) / 4)
        if radius <= 0 or before['end'] > centre or after['start'] < centre:
            raise ValueError('zero-length word has no usable neighboring spans')
        before['end'] = min(before['end'], centre - radius)
        after['start'] = max(after['start'], centre + radius)
        word['start'], word['end'] = centre - radius, centre + radius
        before['estimated'] = True
        word['estimated'] = True
        after['estimated'] = True
        changes.append({'word': word['text'], 'centre': centre, 'estimated_radius_s': radius})
    data['warning'] = 'Unverified draft; adjusted zero-length word edges are estimates, not measurements.'
    data['estimated_edge_adjustments'] = changes
    P.save_json(output, data)


def render(inputs, side, output, scratch):
    """Assemble four shots, narration and music, then keep or omit narration."""
    scratch.mkdir(parents=True, exist_ok=True)
    sources = {name: {'file': str((inputs / f'shot-{name}.mp4').resolve())} for name in ('a', 'b', 'c')}
    sources['voice'] = {'file': str((inputs / 'tale.mp3').resolve())}
    sources['music'] = {'file': str((inputs / 'song.mp3').resolve())}
    edit = {'version': 1, 'size': [480, 200], 'fps': 24, 'sources': sources,
            'picture': [{'src': name, 'in': 0, 'out': 3} for name in ('a', 'b', 'c', 'a')],
            'audio': [{'track': 'voice', 'src': 'voice', 'in': 0, 'out': 12, 'at': 0},
                      {'track': 'music', 'src': 'music', 'in': 0, 'out': 12, 'at': 0}]}
    P.save_json(scratch / 'edit.json', edit)
    picture = scratch / 'picture.mp4'
    PROOF.command([sys.executable, '-I', '-B', PROOF.SCRIPTS / 'assemble.py', scratch / 'edit.json',
                   '--out', picture, '--json', scratch / 'report.json'], accepted=(0, 1))
    output.parent.mkdir(parents=True, exist_ok=True)
    if side == 'good':
        graph = '[1:a][2:a]amix=inputs=2:weights=1 0.06:normalize=0:duration=first[a]'
        PROOF.command(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', picture, '-i', scratch / 'voice.wav',
                       '-i', scratch / 'music.wav', '-filter_complex', graph, '-map', '0:v:0', '-map', '[a]',
                       '-c:v', 'copy', '-c:a', 'aac', '-movflags', '+faststart', '-shortest', output])
    else:
        PROOF.command(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', picture, '-i', scratch / 'music.wav',
                       '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-movflags', '+faststart',
                       '-shortest', output])


def main():
    """Build controls and compare delivered speech with two source excerpts."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixtures', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        inputs = args.fixtures / 'inputs'
        draft = args.fixtures / 'references/tale-asr-draft.json'
        if not draft.is_file():
            raise ValueError('local ASR draft missing; it must be generated and labelled unverified')
        sidecars = args.output / 'caption-draft'
        sidecars.mkdir(parents=True, exist_ok=True)
        adjusted = sidecars / 'estimated-words.json'
        estimated_boundaries(draft, adjusted)
        PROOF.command([sys.executable, '-I', '-B', PROOF.SCRIPTS / 'captions.py', 'build', adjusted,
                       '--out', sidecars / 'captions', '--line-length', '50', '--gap', '0'])
        root = args.output / 'controls'
        renders = {}
        for side in ('good', 'bad'):
            path = args.output / 'assembly' / side / 'complete.mp4'
            render(inputs, side, path, args.output / 'assembly' / side)
            renders[side] = path
        tasks = ('explainer-voice', 'explainer-mix')
        for task in tasks:
            for side in ('good', 'bad'):
                deliver = PROOF.candidate(root, task, side)
                shutil.copyfile(renders[side], deliver / 'output.mp4')
                if task == 'explainer-mix':
                    shutil.copyfile(sidecars / 'captions.srt', deliver / 'captions.srt')
        rows = [PROOF.grade_pair(G.tasks(), task, root, args.fixtures, 'audio_chunks') for task in tasks]
        report = {'controls': rows, 'passed': sum(row['separated'] for row in rows),
                  'failed': sum(not row['separated'] for row in rows),
                  'scope': 'two source excerpts only; draft captions and mix quality need human review'}
        P.save_json(args.output / 'proof.json', report)
        print(json.dumps(report, indent=2))
        return 1 if report['failed'] else 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
