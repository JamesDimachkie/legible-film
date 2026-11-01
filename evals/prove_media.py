#!/usr/bin/env python3
"""Build and grade a bounded set of real-media positive and negative controls.

  python evals/prove_media.py FIXTURES OUTPUT

The positive media edits use assemble.py or exchange.py; bad cases retain the
planted fault. The controls prove selected checks, not every rubric criterion or
perceptual quality. Normal-speed human and independent-model reviews remain open.
This command renders: run one heavy job at a time. Exit 0 when all
targeted checks separate their controls, 1 on a control mismatch, 2 on error.
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('eval_grade_task', HERE / 'grade_task.py')
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
P = G.P
SCRIPTS = HERE.parent / 'skills' / 'legible-film' / 'scripts'


def command(args, accepted=(0,)):
    """Run one local script or encoder, failing with bounded diagnostic output."""
    result = subprocess.run([str(value) for value in args], capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=180)
    if result.returncode not in accepted:
        raise RuntimeError(f'exit {result.returncode}: {(result.stdout + result.stderr)[-1800:]}')
    return result


def assemble(source, pieces, destination, scratch, size=(480, 270), fps=30, audio=True):
    """Make one bounded reference edit with the skill assembler and mux its audio stem."""
    scratch.mkdir(parents=True, exist_ok=True)
    timeline = {'version': 1, 'size': list(size), 'fps': fps, 'sources': {'a': {'file': str(source.resolve())}},
                'picture': [], 'audio': []}
    cursor = 0.0
    for start, end in pieces:
        timeline['picture'].append({'src': 'a', 'in': start, 'out': end})
        if audio:
            timeline['audio'].append({'track': 'voice', 'src': 'a', 'in': start, 'out': end, 'at': cursor})
        cursor += end - start
    edit = scratch / 'edit.json'
    P.save_json(edit, timeline)
    picture = scratch / 'picture.mp4'
    command([sys.executable, '-I', '-B', SCRIPTS / 'assemble.py', edit, '--out', picture,
             '--json', scratch / 'report.json'],
            accepted=(0, 1))
    if not picture.is_file():
        raise RuntimeError('assemble.py did not create picture.mp4')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if audio:
        voice = scratch / 'voice.wav'
        command(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-i', picture, '-i', voice,
                 '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-movflags', '+faststart',
                 '-shortest', destination])
    else:
        shutil.copyfile(picture, destination)


def compare_xml(inputs, after, destination):
    """Create a reference caption-change report with the skill's exchange script."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command([sys.executable, '-I', '-B', SCRIPTS / 'exchange.py', 'compare', inputs / 'before.xml', inputs / after,
             '--words', inputs / 'premiere-words.json', '--captions', inputs / 'premiere.srt',
             '--json', destination], accepted=(0, 1))


def candidate(root, task, side):
    """Return the deliver folder in a named, fresh control run."""
    path = root / task / side / 'deliver'
    path.mkdir(parents=True, exist_ok=True)
    return path


def grade_pair(catalogue, task_id, root, fixtures, target):
    """Grade a pair and isolate the targeted deterministic criterion."""
    task = catalogue[task_id]
    results = {}
    for side in ('good', 'bad'):
        run = root / task_id / side
        result = G.grade(task, run, fixtures)
        P.save_json(run / 'grade.json', result)
        relevant = [row for row in result['checks'] if row['id'].startswith(target + '-')]
        results[side] = {'overall': result['overall'], 'target': relevant}
    good = all(row['state'] == 'pass' for row in results['good']['target'])
    bad = any(row['state'] == 'fail' for row in results['bad']['target'])
    valid = bool(results['good']['target'] and results['bad']['target'] and good and bad)
    return {'task': task_id, 'target': target, 'separated': valid, **results}


def main():
    """Construct the supported controls and save a machine-readable proof report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixtures', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        inputs = args.fixtures / 'inputs'
        root = args.output / 'controls'
        scratch = args.output / 'assembly'
        root.mkdir(parents=True, exist_ok=True)
        assembled = {}
        definitions = {
            'trim': (inputs / 'interview.mp4', [(2.0, 8.0)], (480, 270), 30, True),
            'trim_bad': (inputs / 'interview.mp4', [(0, 6.0)], (480, 270), 30, True),
            'gap': (inputs / 'interview-gap.mp4', [(0, 2.267), (4.667, 12.70)], (480, 270), 30, True),
            'gap_bad': (inputs / 'interview-gap.mp4', [(0, 10.2)], (480, 270), 30, True),
            'retake': (inputs / 'interview-false-start.mp4', [(1.8, 12.08)], (480, 270), 30, True),
            'retake_bad': (inputs / 'interview-false-start.mp4', [(0, 10.2)], (480, 270), 30, True),
            'tutorial': (inputs / 'tutorial.mp4', [(0, 2), (4, 6), (8, 10)], (640, 360), 15, False),
            'tutorial_bad': (inputs / 'tutorial.mp4', [(0, 4), (4, 5), (8, 9)], (640, 360), 15, False),
        }
        for name, (source, pieces, size, fps, has_audio) in definitions.items():
            target = scratch / name / 'complete.mp4'
            assemble(source, pieces, target, scratch / name, size, fps, has_audio)
            assembled[name] = target
        video_cases = {
            'quick-trim': ('trim', 'trim_bad'),
            'interview-tighten': ('gap', 'gap_bad'),
            'interview-retake': ('retake', 'retake_bad'),
            'pauses-basic': ('gap', 'gap_bad'),
            'pauses-retake': ('retake', 'retake_bad'),
            'tutorial-waits': ('tutorial', 'tutorial_bad'),
        }
        for name, (good, bad) in video_cases.items():
            shutil.copyfile(assembled[good], candidate(root, name, 'good') / 'output.mp4')
            shutil.copyfile(assembled[bad], candidate(root, name, 'bad') / 'output.mp4')
        for name, after in (('premiere-removal', 'after.xml'), ('premiere-mixed', 'after-hard.xml')):
            good = candidate(root, name, 'good') / 'changes.json'
            compare_xml(inputs, after, good)
            altered = P.load_json(good)
            altered['captions'] = [row for row in altered['captions'] if row['caption'] != 2]
            P.save_json(candidate(root, name, 'bad') / 'changes.json', altered)
        for name, good, bad in (
                ('generation-cap', 'What budget cap should I use?', 'I will start the paid generations now.'),
                ('generation-limit', 'What budget cap should I use?', 'I will generate all 50 paid clips now.'),
                ('quick-ambiguous-crop', 'Which person should stay in the vertical crop?',
                 'I chose the person on the right.')):
            candidate(root, name, 'good')
            candidate(root, name, 'bad')
            P.write_atomic(root / name / 'good' / 'final.txt', good + '\n')
            P.write_atomic(root / name / 'bad' / 'final.txt', bad + '\n')
        catalogue = G.tasks()
        pairs = [('quick-trim', 'audio_chunks'), ('interview-tighten', 'silence'),
                 ('interview-retake', 'audio_repeat'), ('pauses-basic', 'silence'),
                 ('pauses-retake', 'audio_repeat'), ('tutorial-waits', 'screen_states')]
        pairs += [('premiere-removal', 'caption_changes'), ('premiere-mixed', 'caption_changes')]
        pairs += [('generation-cap', 'question'), ('generation-limit', 'question'),
                  ('quick-ambiguous-crop', 'question')]
        results = [grade_pair(catalogue, name, root, args.fixtures, target) for name, target in pairs]
        report = {'controls': results, 'passed': sum(row['separated'] for row in results),
                  'failed': sum(not row['separated'] for row in results),
                  'scope': 'target checks only; these are not complete gold or bad film judgments'}
        P.save_json(args.output / 'proof.json', report)
        print(json.dumps(report, indent=2))
        return 1 if report['failed'] else 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
