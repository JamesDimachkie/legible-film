#!/usr/bin/env python3
"""Compare a caption-reference candidate with an offline draft word transcript.

  python evals/check_alignment.py REFERENCE.srt DRAFT.json [--out alignment.json]

Matches words in order and compares draft word midpoints with cue-proportional
reference estimates. Neither system has checked the audio by listening; this
screen cannot establish correct words or exact word boundaries. Exit 0 when all
tokens match, 1 when they differ, 2 when the comparison cannot run.
"""
import argparse
import difflib
import importlib.util
import json
import re
import statistics
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('eval_grade_task', HERE / 'grade_task.py')
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)
P = G.P


def normalize(text):
    """Normalize a single draft word in the same way as the SRT reader."""
    value = str(text).lower().replace('\u2019', "'")
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", value)


def compare(reference, draft):
    """Align token sequences and expose timing spread without declaring ground truth."""
    expected = G.word_positions(G.read_srt(reference))
    data = P.load_json(draft)
    actual = []
    for row in data['words']:
        midpoint = (float(row['start']) + float(row['end'])) / 2
        actual.extend((token, midpoint) for token in normalize(row.get('text', row.get('word', ''))))
    matcher = difflib.SequenceMatcher(a=[item[0] for item in expected], b=[item[0] for item in actual],
                                      autojunk=False)
    offsets = []
    differences = []
    for operation, left, right, first, last in matcher.get_opcodes():
        if operation == 'equal':
            offsets.extend(abs(expected[index][1] - actual[first + index - left][1])
                           for index in range(left, right))
        else:
            differences.append({'operation': operation, 'reference': [row[0] for row in expected[left:right]],
                                'draft': [row[0] for row in actual[first:last]],
                                'reference_start_s': expected[left][1] if left < len(expected) else None})
    return {'reference_tokens': len(expected), 'draft_tokens': len(actual), 'matched_tokens': len(offsets),
            'differences': differences,
            'median_cue_to_draft_midpoint_difference_s': round(statistics.median(offsets), 3) if offsets else None,
            'max_cue_to_draft_midpoint_difference_s': round(max(offsets), 3) if offsets else None,
            'basis': 'unverified publisher cues vs offline ASR draft; cue-based word positions are estimates',
            'human_verified': False,
            'next': 'Listen to the recording; verify each word, names and the timing at every edit boundary.'}


def main():
    """Run and optionally save the alignment screen."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('reference', type=Path)
    parser.add_argument('draft', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        result = compare(args.reference, args.draft)
        if args.out:
            P.save_json(args.out, result)
        print(json.dumps(result, indent=2))
        return 1 if result['differences'] else 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
