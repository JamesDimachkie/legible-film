#!/usr/bin/env python3
"""Test the evaluation harness offline with known small counterexamples.

  python -I evals/selftest.py --work SCRATCH_DIR

The cases exercise catalogue shape, grader failure modes, staging, JSONL parsers,
neutral packets and report denominators. They are synthetic harness tests, not
real-media gold solutions, agent smoke runs, or proof of film quality.
Exit 0 if all cases pass, 1 if any fail, 2 for invalid setup.
"""
import argparse
import importlib.util
import json
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def load(name):
    """Load an eval module explicitly so this also works under Python -I."""
    spec = importlib.util.spec_from_file_location('eval_test_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


G = load('grade_task')
R = load('run')
J = load('judge_packet')
REPORT = load('report')
EXPLAINER = load('prove_explainer')
FETCH_SPEC = importlib.util.spec_from_file_location('eval_test_fetch', HERE / 'media' / 'fetch.py')
FETCH = importlib.util.module_from_spec(FETCH_SPEC)
FETCH_SPEC.loader.exec_module(FETCH)


def main():
    """Run deterministic harness tests in a newly created lane-local scratch folder."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--work', required=True, type=Path)
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='eval-selftest-', dir=str(args.work.resolve())))
    failures = []
    passes = []

    def record(name, ok, detail=''):
        """Keep failures and passes separately, with explicit evidence."""
        (passes if ok else failures).append({'name': name, 'detail': str(detail)})
        print(('PASS ' if ok else 'FAIL ') + name + (' - ' + str(detail) if detail else ''))

    catalogue = G.tasks()
    groups = {}
    for task in catalogue.values():
        groups.setdefault(task['kind'], set()).add(task['difficulty'])
    record('at least 25 unique tasks; everyday and hard per kind', len(catalogue) >= 25 and len(groups) >= 12 and
           all({'everyday', 'hard'}.issubset(values) for values in groups.values()), str(groups))
    allowed = {'exists', 'video', 'captions', 'audio_chunks', 'audio_repeat', 'screen_states', 'cursor_presence',
               'shot_sequence', 'silence', 'question', 'caption_changes', 'inputs_unchanged'}
    unknown = [(task['id'], rule['method']) for task in catalogue.values() for rule in task['automatic']
               if rule['method'] not in allowed]
    record('every declared automated method is implemented', not unknown, unknown)
    record('media fetch permits only approved HTTPS hostnames',
           FETCH.approved_url('https://svs.gsfc.nasa.gov/test') and
           not FETCH.approved_url('https://nasa.gov.example.test/file') and
           not FETCH.approved_url('http://svs.gsfc.nasa.gov/test'))

    fixtures = root / 'fixtures'
    references = fixtures / 'references'
    references.mkdir(parents=True)
    workspace = root / 'candidate'
    deliver = workspace / 'deliver'
    deliver.mkdir(parents=True)
    reference = '1\n00:00:00,000 --> 00:00:02,000\nNASA telescope begins\n'
    (references / 'ref.srt').write_text(reference, encoding='utf-8')
    (deliver / 'captions.srt').write_text(reference, encoding='utf-8')
    rule = {'path': 'deliver/captions.srt', 'reference': 'ref.srt'}
    state, detail = G.caption_comparison(rule, workspace, fixtures)
    record('caption reference matches itself', state == 'pass', detail)
    (deliver / 'captions.srt').write_text(reference.replace('telescope begins', 'rocket explodes'), encoding='utf-8')
    state, detail = G.caption_comparison(rule, workspace, fixtures)
    record('changed caption words fail', state == 'fail', detail)
    (deliver / 'captions.srt').write_text(reference.replace('NASA', 'NASC'), encoding='utf-8')
    state, detail = G.caption_comparison(rule, workspace, fixtures)
    record('a single changed name fails', state == 'fail', detail)
    (deliver / 'captions.srt').write_text(reference.replace('00:00:00,000', '00:00:02,000').replace(
        '00:00:02,000\nNASA', '00:00:04,000\nNASA'), encoding='utf-8')
    state, detail = G.caption_comparison(rule, workspace, fixtures)
    record('caption offset fails', state == 'fail', detail)
    (references / 'ref.srt').write_text('broken', encoding='utf-8')
    state, detail = G.caption_comparison(rule, workspace, fixtures)
    record('invalid grader reference is not blamed on the candidate', state == 'not_run', detail)
    draft_path = root / 'zero-draft.json'
    draft = {'words': [{'text': 'first', 'start': 0.1, 'end': 0.4},
                       {'text': 'for', 'start': 1.2, 'end': 1.2},
                       {'text': 'more', 'start': 1.2, 'end': 1.4}]}
    G.P.save_json(draft_path, draft)
    adjusted_path = root / 'estimated-draft.json'
    EXPLAINER.estimated_boundaries(draft_path, adjusted_path)
    adjusted = G.P.load_json(adjusted_path)
    record('zero-length draft words get a labelled estimate without changing the original',
           adjusted['words'][1]['end'] > adjusted['words'][1]['start'] and
           adjusted['words'][1]['estimated'] and G.P.load_json(draft_path) == draft)

    reference_changes = {'captions': [{'caption': 1, 'status': 'unchanged'},
                                      {'caption': 2, 'status': 'removed'},
                                      {'caption': 3, 'status': 'moved', 'shift_s': -2.0}]}
    (references / 'changes.json').write_text(json.dumps(reference_changes), encoding='utf-8')
    (deliver / 'changes.json').write_text(json.dumps(reference_changes), encoding='utf-8')
    changes = {'path': 'deliver/changes.json', 'reference': 'changes.json'}
    state, detail = G.caption_changes(changes, workspace, fixtures)
    record('all caption changes and shifts present', state == 'pass', detail)
    incomplete = {'captions': reference_changes['captions'][:2]}
    (deliver / 'changes.json').write_text(json.dumps(incomplete), encoding='utf-8')
    state, detail = G.caption_changes(changes, workspace, fixtures)
    record('missing caption change fails', state == 'fail', detail)
    wrong_shift = {'captions': [*reference_changes['captions'][:2],
                                {'caption': 3, 'status': 'moved', 'shift_s': -0.1}]}
    (deliver / 'changes.json').write_text(json.dumps(wrong_shift), encoding='utf-8')
    state, detail = G.caption_changes(changes, workspace, fixtures)
    record('incorrect caption shift fails', state == 'fail', detail)
    stale_reference = {'captions': [{'caption': 1, 'status': 'stale', 'cut_words': ['welcome', 'to']}]}
    (references / 'changes.json').write_text(json.dumps(stale_reference), encoding='utf-8')
    (deliver / 'changes.json').write_text(json.dumps({'captions': [{'caption': 1, 'status': 'stale'}]}),
                                           encoding='utf-8')
    state, detail = G.caption_changes(changes, workspace, fixtures)
    record('a stale caption report must identify the cut words', state == 'fail', detail)
    baseline = root / 'editor-run' / 'original-inputs'
    editor = root / 'editor-run' / 'workspace'
    baseline.mkdir(parents=True)
    editor.mkdir()
    (baseline / 'before.xml').write_text('original', encoding='utf-8')
    (editor / 'before.xml').write_text('original', encoding='utf-8')
    state, _ = G.inputs_unchanged({'paths': ['before.xml']}, root / 'editor-run', editor)
    (editor / 'before.xml').write_text('modified', encoding='utf-8')
    changed_state, _ = G.inputs_unchanged({'paths': ['before.xml']}, root / 'editor-run', editor)
    record('editor input changes are detected against the pre-run baseline', state == 'pass' and
           changed_state == 'fail')

    response = root / 'final.txt'
    response.write_text('What is the budget cap?', encoding='utf-8')
    state, detail = G.question({'terms': ['budget', 'cap']}, response)
    record('one budget question is detected', state == 'pass', detail)
    response.write_text('Starting the generation now.', encoding='utf-8')
    state, detail = G.question({'terms': ['budget', 'cap']}, response)
    record('no budget question fails', state == 'fail', detail)

    rng = np.random.default_rng(42)
    source = rng.normal(size=4096)
    candidate = np.concatenate([rng.normal(size=512), source * .3, rng.normal(size=512)])
    good = G.peak_correlation(candidate, source)
    wrong = G.peak_correlation(rng.normal(size=6144), source)
    record('audio matcher detects an offset, gain-scaled excerpt', good > .99, f'{good:.4f}')
    record('audio matcher rejects an unrelated signal', wrong < .30, f'{wrong:.4f}')

    try:
        G.under(workspace, '../escape')
        escaped = True
    except ValueError:
        escaped = False
    record('run paths cannot traverse out of the workspace', not escaped)

    task = catalogue['generation-cap']
    run = root / 'staged'
    stage, prompt, before, metadata = R.prepare(task, fixtures, run, 'with', 'codex')
    skill = stage / '.agents' / 'skills' / 'legible-film' / 'SKILL.md'
    record('with-skill arm installs only a run-local skill and points the prompt to it',
           skill.is_file() and '.agents/skills/legible-film/SKILL.md' in prompt and metadata['state'] == 'staged')
    empty_run = root / 'without'
    empty_stage, _, _, empty_meta = R.prepare(task, fixtures, empty_run, 'without', 'claude')
    record('without-skill arm installs no project skill', not (empty_stage / '.claude').exists() and
           'ambient skills unverified' in empty_meta['skill_loading'])
    pinned = R.tree_hash(R.SKILL)
    _, _, _, earlier = R.prepare(task, fixtures, root / 'earlier', 'earlier', 'codex', R.SKILL, 'test-ref', pinned)
    record('earlier arm pins the exported skill bytes and records the declared ref',
           earlier['skill_tree_sha256'] == pinned and earlier['earlier_ref_declared'] == 'test-ref')
    try:
        R.prepare(task, fixtures, root / 'wrong-hash', 'earlier', 'codex', R.SKILL, 'test-ref', '0' * 64)
        rejected = False
    except ValueError:
        rejected = True
    record('earlier arm rejects a mismatched skill tree hash', rejected)

    codex_events = [
        {'type': 'item.completed', 'item': {'type': 'command_execution'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'What is the budget cap?'}},
        {'type': 'turn.completed', 'usage': {'input_tokens': 9, 'output_tokens': 4}},
    ]
    transcript = root / 'codex.jsonl'
    transcript.write_text('\n'.join(json.dumps(row) for row in codex_events) + '\n', encoding='utf-8')
    parsed = R.parse_events(transcript, 'codex')
    record('Codex stream records turns, tools, usage and question', parsed['turns'] == 1 and
           parsed['tool_calls'] == 1 and parsed['usage']['input_tokens'] == 9 and
           parsed['question_marks_in_final'] == 1)
    claude_events = [
        {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Read'},
                                                      {'type': 'text', 'text': 'Budget?'}]}},
        {'type': 'result', 'num_turns': 2, 'total_cost_usd': 0.03, 'result': 'Budget?'},
    ]
    transcript.write_text('\n'.join(json.dumps(row) for row in claude_events) + '\n', encoding='utf-8')
    parsed = R.parse_events(transcript, 'claude')
    record('Claude stream records turns, tools and reported cost', parsed['turns'] == 2 and
           parsed['tool_calls'] == 1 and parsed['cost_usd'] == .03 and parsed['questions'] == ['Budget?'])
    transcript.write_text(json.dumps({'type': 'result', 'subtype': 'error_max_turns', 'is_error': True}) + '\n',
                          encoding='utf-8')
    parsed = R.parse_events(transcript, 'claude')
    record('an agent-reported error is not treated as a successful run', bool(parsed['errors']))

    (run / 'final.txt').write_text('What is the budget cap?', encoding='utf-8')
    packet = root / 'packet'
    packet_data = J.packet(task, run, packet)
    serialized = json.dumps(packet_data).lower()
    record('neutral judge packet excludes arm and tool metadata', 'with-skill' not in serialized and
           'codex' not in serialized and 'tool_calls' not in serialized and (packet / 'packet.json').is_file())
    result = G.grade(task, run, fixtures)
    record('unreviewed good answer remains inconclusive', result['overall'] == 'inconclusive', result['overall'])
    metadata = G.P.load_json(run / 'run.json')
    metadata['producer_family'] = 'openai'
    G.P.save_json(run / 'run.json', metadata)
    judgment = G.P.load_json(packet / 'judgment-template.json')
    judgment['reviewer'] = {'type': 'model', 'family': 'anthropic'}
    judgment['criteria'] = [
        {'id': 'question-quality', 'state': 'pass', 'evidence': 'The question asks for the missing budget cap.'},
        {'id': 'no-spend', 'state': 'pass', 'evidence': 'The response does not mention any external generation.'},
    ]
    G.P.save_json(packet / 'judgment.json', judgment)
    reviewed = G.grade(task, run, fixtures, packet_dir=packet, judgment_path=packet / 'judgment.json')
    states = {row['id']: row['state'] for row in reviewed['checks']}
    record('independent judgment cannot certify no spending without an execution audit',
           states.get('review:question-quality') == 'pass' and states.get('review:no-spend') == 'not_run', states)
    false_footage = G.grade(catalogue['generation-false-footage'], run, fixtures)
    record('unreviewed fabricated-footage request is not scored as a pass',
           false_footage['overall'] == 'inconclusive')
    (run / 'final.txt').write_text('Starting generation.', encoding='utf-8')
    result = G.grade(task, run, fixtures)
    record('failed automatic criterion makes the task fail', result['overall'] == 'fail', result['overall'])
    tampered = G.grade(task, run, fixtures, packet_dir=packet, judgment_path=packet / 'judgment.json')
    states = {row['id']: row['state'] for row in tampered['checks']}
    record('a judgment cannot attach to a changed artifact', states.get('review:question-quality') == 'not_run')
    record('report denominator separates review and not-run criteria',
           REPORT.fraction(['pass', 'fail', 'review', 'not_run']) == '1/2; 1 review, 1 not run')
    fake_video = deliver / 'output.mp4'
    fake_video.write_bytes(b'not a real video; hash-binding test only')
    card = {'file': 'deliver/output.mp4', 'file_sha256': G.digest(fake_video),
            'dimensions': [{'id': 'image', 'score': 7, 'basis': 'measured',
                            'evidence': [{'t': 0, 'note': 'A known test value.'}]}]}
    card_path = root / 'card.json'
    G.P.save_json(card_path, card)
    bound = G.scorecard_items(catalogue['quick-trim'], workspace, card_path)
    record('scorecard dimensions bind to the delivered file hash', bound[0]['state'] == 'pass')
    card['dimensions'][0]['basis'] = 'judged'
    card['dimensions'][0]['judge_family'] = 'openai'
    G.P.save_json(card_path, card)
    same_family = G.scorecard_items(catalogue['quick-trim'], workspace, card_path, run)
    card['dimensions'][0]['judge_family'] = 'anthropic'
    G.P.save_json(card_path, card)
    independent = G.scorecard_items(catalogue['quick-trim'], workspace, card_path, run)
    record('judged scorecard dimensions require a different recorded model family',
           same_family[0]['state'] == 'not_run' and independent[0]['state'] == 'pass')
    fake_video.write_bytes(b'a changed file')
    unbound = G.scorecard_items(catalogue['quick-trim'], workspace, card_path)
    record('a stale scorecard is not accepted', unbound[0]['state'] == 'not_run')

    fake = root / 'fake_agent.py'
    fake.write_text(
        "import json, pathlib, sys\n"
        "p = pathlib.Path('deliver'); p.mkdir(exist_ok=True)\n"
        "(p / 'note.txt').write_text('local test double', encoding='utf-8')\n"
        "client = sys.argv[1]\n"
        "if client == 'codex':\n"
        "    events = [{'type':'item.completed','item':{'type':'agent_message','text':'What is the budget cap?'}},"
        " {'type':'turn.completed','usage':{'input_tokens':5,'output_tokens':3}}]\n"
        "else:\n"
        "    events = [{'type':'result','num_turns':1,'result':'What is the budget cap?','total_cost_usd':0}]\n"
        "for event in events: print(json.dumps(event))\n", encoding='utf-8')
    original_cli = R.cli
    R.cli = lambda runner, prompt, workspace, turns: [sys.executable, '-I', str(fake), runner]
    mock_runs = root / 'mock-runs'
    for client in ('claude', 'codex'):
        args = Namespace(runs=mock_runs, fixtures=fixtures, arm='without', runner=client,
                         earlier_skill=None, earlier_ref=None, earlier_sha256=None, producer_family='mock',
                         max_turns=3, execute=True, timeout=30)
        code = R.run_one(task, args)
        candidates = [folder for folder in mock_runs.iterdir()
                      if G.P.load_json(folder / 'run.json')['runner'] == client]
        simulated = candidates[0]
        meta = G.P.load_json(simulated / 'run.json')
        graded = G.grade(task, simulated, fixtures)
        record(f'{client} local test-double run captures transcript, file, final answer and grade',
               code == 0 and (simulated / 'transcript.jsonl').is_file() and
               'deliver/note.txt' in meta['files_written_or_changed'] and
               graded['checks'][0]['state'] == 'pass' and graded['overall'] == 'inconclusive')
    R.cli = original_cli
    summary = {'passed': len(passes), 'failed': len(failures), 'not_run': 0, 'passes': passes, 'failures': failures}
    G.P.save_json(root / 'selftest-results.json', summary)
    print(f'{len(passes)} passed, {len(failures)} failed, 0 not run; {root}')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
