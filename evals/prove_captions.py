#!/usr/bin/env python3
"""Test caption-reference checks on skill-built sidecars and targeted bad controls.

  python evals/prove_captions.py FIXTURES OUTPUT

This imports unverified NASA publisher cues and builds each cue separately with
the skill. It is a narrow comparison against those cues, not a verified transcript
or a complete gold film. The 50-character line limit is an explicit workaround for
the builder rejecting the provided phrase at its default. Exit 0 for separated
controls, 1 for a mismatch, 2 on error.
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
CAPTION_SPEC = importlib.util.spec_from_file_location('eval_skill_captions', SCRIPTS / 'captions.py')
CAPTIONS = importlib.util.module_from_spec(CAPTION_SPEC)
CAPTION_SPEC.loader.exec_module(CAPTIONS)


def call(args):
    """Run one skill script and surface a bounded failure message."""
    result = subprocess.run([sys.executable, '-I', '-B', *map(str, args)], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError((result.stdout + result.stderr)[-1600:])


def build(reference, audio, deliver, scratch):
    """Import each publisher cue and build matching SRT and VTT with the skill."""
    scratch.mkdir(parents=True, exist_ok=True)
    deliver.mkdir(parents=True, exist_ok=True)
    words_path = scratch / 'words.json'
    call([SCRIPTS / 'transcribe.py', audio, '--engine', 'import', '--import-file', reference, '--out', words_path])
    words = P.load_json(words_path)['words']
    cues = G.read_srt(reference)
    assembled = []
    for index, cue in enumerate(cues, 1):
        selected = [row for row in words if cue['start'] <= row['start'] < cue['end']]
        source = scratch / f'cue-{index}.json'
        P.save_json(source, {'words': selected})
        prefix = scratch / f'cue-{index}'
        call([SCRIPTS / 'captions.py', 'build', source, '--out', prefix, '--gap', '0', '--line-length', '50'])
        assembled.extend(P.load_json(prefix.with_suffix('.json'))['cues'])
    CAPTIONS.write_sidecars(assembled, str(deliver / 'captions'))


def main():
    """Build two controls and grade a wrong name and a wrong audio offset."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fixtures', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        root = args.output / 'controls'
        specs = [('captions-basic', 'interview.srt', 'interview.mp4'),
                 ('captions-offset', 'interview-offset.srt', 'interview-offset.mp4')]
        for task, ref, video in specs:
            build(args.fixtures / 'references' / ref, args.fixtures / 'inputs' / video,
                  root / task / 'good' / 'deliver', args.output / 'build' / task)
        first = root / 'captions-basic' / 'good' / 'deliver'
        bad = root / 'captions-basic' / 'bad' / 'deliver'
        bad.mkdir(parents=True, exist_ok=True)
        text = P.read_text(first / 'captions.srt').replace('Mather', 'Miller')
        P.write_atomic(bad / 'captions.srt', text)
        shutil.copyfile(first / 'captions.vtt', bad / 'captions.vtt')
        bad = root / 'captions-offset' / 'bad' / 'deliver'
        bad.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(first / 'captions.srt', bad / 'captions.srt')
        shutil.copyfile(first / 'captions.vtt', bad / 'captions.vtt')
        results = []
        for task, _, _ in specs:
            pair = {}
            for side in ('good', 'bad'):
                run = root / task / side
                result = G.grade(G.tasks()[task], run, args.fixtures)
                P.save_json(run / 'grade.json', result)
                pair[side] = next(row for row in result['checks'] if row['id'].startswith('captions-'))
            results.append({'task': task, 'good': pair['good'], 'bad': pair['bad'],
                            'separated': pair['good']['state'] == 'pass' and pair['bad']['state'] == 'fail'})
        report = {'controls': results, 'passed': sum(item['separated'] for item in results),
                  'failed': sum(not item['separated'] for item in results),
                  'scope': 'publisher-reference comparison only; all timings remain unverified'}
        P.save_json(args.output / 'proof.json', report)
        print(json.dumps(report, indent=2))
        return 1 if report['failed'] else 0
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
