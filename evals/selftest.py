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
    routing_cases(record, root)
    summary = {'passed': len(passes), 'failed': len(failures), 'not_run': 0, 'passes': passes, 'failures': failures}
    G.P.save_json(root / 'selftest-results.json', summary)
    print(f'{len(passes)} passed, {len(failures)} failed, 0 not run; {root}')
    return 1 if failures else 0


def routing_cases(record, root):
    """The reshape routing scorer and plan-mode guard on synthetic streams, against the frozen 2.0.0 skill files
    (fixtures/legible-film-2.0.0.json; no paths/, so the 2.0.0 map), not the live skill the reshape rewrites."""
    import subprocess
    rs = load('routing_score')
    spec = json.loads((HERE / 'reshape-routing.json').read_text(encoding='utf-8'))
    frozen = json.loads((HERE / 'fixtures' / 'legible-film-2.0.0.json').read_text(encoding='utf-8'))
    skill = root / '2.0.0' / 'legible-film'
    for rel, text in frozen['files'].items():
        (skill / rel).parent.mkdir(parents=True, exist_ok=True)
        (skill / rel).write_text(text, encoding='utf-8', newline='\n')
    base = str(skill).replace('\\', '/') + '/'
    case = {c['id']: c for c in spec['cases']}

    def asst(mid, *parts):
        return json.dumps({'type': 'assistant', 'message': {'id': mid, 'content': list(parts)}})

    def use(i, name, args):
        return {'type': 'tool_use', 'id': i, 'name': name, 'input': args}

    def said(text):
        return {'type': 'text', 'text': text}

    end = json.dumps({'type': 'result', 'subtype': 'success'})
    load_skill = asst('m1', use('t1', 'Skill', {'skill': 'legible-film'}))
    partial = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'references/recipes.md', 'offset': 16,
                                                         'limit': 30})),
               asst('m3', use('t3', 'Bash', {'command': 'python scripts/cut.py render P'})),
               asst('m4', said('Should I keep the centre? Who is the audience?')), end]
    score = rs.score_session(rs.claude_events(partial, {'t3': True}), case['P07'], spec, skill)
    record('routing: a partial recipes.md read routes by its section; build attempt and frame question counted',
           score['route'] == 'quick' and score['right'] and score['build_attempts'] == 1 and
           any(f['hit'] == 'asked a frame question' for f in score['forbidden']) and
           [r['file'] for r in score['reads_before_action']] == ['SKILL.md', 'references/recipes.md'], score['route'])
    top = rs.heading_at(skill, 'references/recipes.md', 1, 90)
    lines = (skill / 'references' / 'recipes.md').read_text(encoding='utf-8').splitlines()
    target = next(i for i, line in enumerate(lines) if line == '## Launch film or kinetic type') + 1
    lead = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'references/recipes.md',
                                                      'offset': target - 5, 'limit': 60})), end]
    score = rs.score_session(rs.claude_events(lead, {}), case['P02'], spec, skill)
    record('routing: a partial read that starts a few lines above a heading routes by that heading; '
           'a read of the top of the file is on no recipe',
           score['route'] == 'create' and top is None, score['route_evidence'])
    filtered = [json.dumps({'type': 'item.completed', 'item': {
                    'type': 'command_execution', 'exit_code': 0,
                    'command': 'Get-Content .agents/skills/legible-film/SKILL.md'}}),
                json.dumps({'type': 'item.completed', 'item': {
                    'type': 'command_execution', 'exit_code': 0,
                    'command': "Get-Content .agents/skills/legible-film/references/recipes.md | Select-String "
                               "-Pattern '^## Graphics over footage' -Context 0,20 | Select-Object -First 1"}})]
    score = rs.score_session(rs.codex_events(filtered), case['P04'], spec, skill)
    record('routing: a filtered read of one recipe routes by it and counts only its lines',
           score['route'] == 'insert' and score['reads_before_action'][1]['words'] < 1000, score['route_evidence'])
    grep = [load_skill, asst('m2', use('t2', 'Grep', {'pattern': '^## Tighten a talking head', 'output_mode': 'content',
                                                      'path': base + 'references/recipes.md', '-A': 60})), end]
    score = rs.score_session(rs.claude_events(grep, {}), case['P05'], spec, skill)
    record('routing: a Grep that shows one recipe with lines after it is a read of that recipe',
           score['route'] == 'cut' and score['reads_before_action'][1]['words'] < 1500, score['route_evidence'])
    record('routing: tighten.py is a heavy step the guard denies; asking a script for --help never is',
           'heavy' in rs.classify('python scripts/tighten.py recording.mp4', spec['actions']['classes']) and
           rs.classify('cat a.js; $PY scripts/make_film.py --help | head -80; tsrct --help',
                       spec['actions']['classes']) == [])
    record('routing: reading, listing or searching for a script or a service is never an attempt',
           rs.classify('env | grep -iE "api_key|fal|replicate|suno" | sed "s/=.*//"; ls scripts/make_film.py; '
                       'sed -n 1,40p scripts/mix_cues.py', spec['actions']['classes']) == [] and
           rs.classify('python scripts/mix_cues.py P', spec['actions']['classes']) == ['build'] and
           rs.classify('curl -s https://api.elevenlabs.io/v1/x | grep id', spec['actions']['classes']) ==
           ['spend', 'network'])
    ranged = [load_skill, asst('m2', use('t2', 'Bash', {'command': (
        "S=.claude/skills/legible-film; sed -n 1,15p $S/references/recipes.md; "
        f"sed -n {target},{target + 22}p $S/references/recipes.md")})), end]
    score = rs.score_session(rs.claude_events(ranged, {}), case['P01'], spec, skill)
    record('routing: a read of the preamble shows no recipe; the next ranged read of recipes.md does',
           score['route'] == 'create', score['route_evidence'])
    inside = [load_skill, asst('m2', use('t2', 'Bash', {'command': (
        'cd "C:/p/.claude/skills/legible-film/references" && sed -n 1,15p recipes.md && '
        f'sed -n {target},{target + 22}p recipes.md && cat kit.md')})), end]
    score = rs.score_session(rs.claude_events(inside, {}), case['P01'], spec, skill)
    record('routing: bare file names read after cd into the skill folder are skill reads',
           score['route'] == 'create' and [r['file'] for r in score['reads_before_action']] ==
           ['SKILL.md', 'references/recipes.md', 'references/recipes.md', 'references/kit.md'],
           score['route_evidence'])
    bare_grep = [load_skill, asst('m2', use('t2', 'Grep', {'pattern': 'Assisting an editor in Premiere',
                                                           'output_mode': 'content', '-A': 50,
                                                           'path': base + 'references/recipes.md'})),
                 asst('m3', use('t3', 'Bash', {'command': 'python scripts/map.py add P a.mp4 --role interview'})),
                 end]
    score = rs.score_session(rs.claude_events(bare_grep, {}), case['P09'], spec, skill)
    record('routing: a Grep for a recipe heading without its ## is a read of that recipe',
           score['route'] == 'editor', score['route_evidence'])
    def codex_cmd(command):
        return json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution', 'exit_code': 0,
                                                              'command': command}})

    skill_line = codex_cmd('cat .agents/skills/legible-film/SKILL.md')
    spliced = codex_cmd('"C:\\\\Tools\\\\pwsh.exe" -Command \'$f=\'"\'"\'.agents/skills/legible-film/references/'
                        'recipes.md\'"\'"\'; $t=Get-Content $f; $t | Select-String \'"\'"\'^## Graphics over footage'
                        '\'"\'"\' -Context 0,12\'')
    score = rs.score_session(rs.codex_events([skill_line, spliced]), case['P04'], spec, skill)
    record('routing: a POSIX-quoted pwsh wrapper with spliced quotes and a $variable path is decoded and read',
           score['route'] == 'insert', score['route_evidence'])
    nested = codex_cmd("bash -lc 'pwsh -Command \"Get-Content .agents/skills/legible-film/references/recipes.md "
                       "| Select-String -Pattern ''^## Captions only'' \"'")
    score = rs.score_session(rs.codex_events([skill_line, nested]), case['P07'], spec, skill)
    record('routing: a shell inside a shell is unwrapped, and a Select-String for a heading without -Context is a '
           'read of that recipe', score['route'] == 'quick', score['route_evidence'])
    alternation = codex_cmd("rg -n -A 40 '^## Music or lyric video|^## Generated clips' "
                            ".agents/skills/legible-film/references/recipes.md")
    score = rs.score_session(rs.codex_events([skill_line, alternation]), case['P03'], spec, skill)
    record('routing: an rg with context lines and an alternation of headings reads the first heading',
           score['route'] == 'create', score['route_evidence'])
    arrayed = codex_cmd('$lines = gc .agents/skills/legible-film/references/recipes.md; $lines[226..250]')
    score = rs.score_session(rs.codex_events([skill_line, arrayed]), case['P04'], spec, skill)
    record('routing: a literal index range on a loaded file is a ranged read (0-based)',
           score['route'] == 'insert' and score['reads_before_action'][1]['first'] == 227, score['route_evidence'])
    classes = spec['actions']['classes']
    record('routing: an environment check (--doctor) and a loop header that lists script names are not attempts; '
           'a loop body that renders is',
           rs.classify('"$PY" scripts/kit_tool.py --doctor 2>&1 | tail -5', classes) == [] and
           rs.classify('"$PY" scripts/make_film.py --doctor 2>&1', classes) == [] and
           rs.classify('for f in cut.py mix_cues.py; do python scripts/$f --help | head -3; done', classes) == [] and
           rs.classify('for f in a b; do python scripts/cut.py render P; done', classes) == ['build'])
    halted = [skill_line, json.dumps({'type': 'item.started', 'item': {'id': 'x9', 'type': 'command_execution',
                                                                      'command': 'python scripts/make_film.py P'}})]
    score = rs.score_session(rs.codex_events(halted), case['P05'], spec, skill)
    record('routing: a Codex command that started and was stopped before completing is recorded as an attempt',
           score['build_attempts'] == 1 and any(f['hit'].startswith('ran make_film.py') for f in score['forbidden']),
           score['attempts'])
    record('routing: a PowerShell if whose test and body only read is a look; with a script run it is not',
           rs.is_look('if (Test-Path notes.md) { Get-Content notes.md }') and
           not rs.is_look('if (Test-Path a.mp4) { python scripts/cut.py render P }'))
    diagnose = [skill_line, codex_cmd('Get-Content .agents/skills/legible-film/references/recipes.md -TotalCount 40'),
                codex_cmd('python .agents/skills/legible-film/scripts/setup.py'),
                codex_cmd("Get-Content .agents/skills/legible-film/references/recipes.md | Select-String "
                          "'^## Screen-recorded tutorial' -Context 0,9")]
    score = rs.score_session(rs.codex_events(diagnose), case['P05'], spec, skill)
    record('routing: a read of the top of recipes.md is on no recipe, and setup.py does not end the search for '
           'the first recipe read', score['route'] == 'cut' and 'Screen-recorded tutorial' in score['route_evidence'],
           score['route_evidence'])
    whole = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'references/recipes.md'})),
             asst('m3', said('Following Animated insert over a recording.')), end]
    score = rs.score_session(rs.claude_events(whole, {}), case['P04'], spec, skill)
    record('routing: a whole recipes.md read routes by the recipe the agent names after it',
           score['route'] == 'insert' and score['right'], score['route_evidence'])
    bare = [load_skill, asst('m2', said('Which file?')), end]
    score = rs.score_session(rs.claude_events(bare, {}), case['P10'], spec, skill)
    record('routing: a loaded skill with no path-mapped read is unscored, never a pass',
           score['route'] is None and not score['scored'] and score['right'] is None)
    never = [asst('m1', said('I can do that without a skill.')), end]
    score = rs.score_session(rs.claude_events(never, {}), case['P01'], spec, skill)
    record('routing: a session that never loads the skill routes to no-skill and is wrong for a skill prompt',
           score['route'] == 'no-skill' and score['right'] is False)
    words = rs.words_in(skill, 'SKILL.md') + rs.words_in(skill, 'references/loop.md')
    record('routing: words are whitespace-separated, SKILL.md plus loop.md counted whole', words > 4000, words)
    classes = spec['actions']['classes']
    record('routing: map.py run is heavy unless words are skipped; render and npx are denied',
           rs.classify('python map.py run P', classes) == ['heavy'] and
           rs.classify('python map.py run P --words skip', classes) == [] and
           'build' in rs.classify('npx hyperframes render', classes))
    codex = [json.dumps({'type': 'item.completed', 'item': {
                 'type': 'command_execution', 'exit_code': 0,
                 'command': '"pwsh.exe" -Command \'Get-Content -Raw .agents/skills/legible-film/SKILL.md\''}}),
             json.dumps({'type': 'item.completed', 'item': {
                 'type': 'command_execution', 'exit_code': 0,
                 'command': '"pwsh.exe" -Command "Get-Content .agents/skills/legible-film/references/sound.md"'}}),
             json.dumps({'type': 'turn.completed'})]
    score = rs.score_session(rs.codex_events(codex), case['P06'], spec, skill)
    record('routing: a Codex trace loads the skill and routes from its shell reads',
           score['skill_loaded'] and score['route'] == 'sound', score['route_evidence'])
    tr = load('trigger_run')
    record('routing sessions take no heavy-job lock: a met memory floor returns at once with the MiB free',
           tr.wait_for_memory(0) >= 0 and not hasattr(tr, 'HeavyLock'))
    route_check_cases(record, root, rs, spec, asst, use, said, end)
    project = root / 'guard-project'
    project.mkdir()
    log = root / 'guard.jsonl'
    decisions = []
    for tool, args in (('Bash', {'command': 'python scripts/cut.py render P'}), ('Bash', {'command': 'ffprobe a.mp4'}),
                       ('Write', {'file_path': str(root / 'outside.md'), 'content': 'x'}),
                       ('Write', {'file_path': str(project / 'film.md'), 'content': 'x'})):
        done = subprocess.run([sys.executable, '-I', str(HERE / 'trigger_run.py'), 'guard', '--cases',
                               str(HERE / 'reshape-routing.json'), '--project', str(project), '--log', str(log)],
                              input=json.dumps({'tool_name': tool, 'tool_input': args}), capture_output=True,
                              text=True)
        decisions.append('deny' if '"deny"' in done.stdout else 'allow')
    record('routing guard: denies a render and a write outside the project; allows a probe and a write inside',
           decisions == ['deny', 'allow', 'deny', 'allow'], decisions)


def route_check_cases(record, root, rs, spec, asst, use, said, end):
    """Route checks 16-20 on stub streams against a small synthetic candidate skill; no session, no fixture build."""
    import xml.etree.ElementTree as ET
    rc = load('route_checks')
    cand = root / 'candidate' / 'legible-film'
    (cand / 'paths').mkdir(parents=True)
    (cand / 'references').mkdir()
    (cand / 'SKILL.md').write_text('---\nname: legible-film\n---\n# Synthetic candidate\nPick a path.\n', encoding='utf-8')
    for name in ('create', 'cut', 'insert', 'sound', 'editor', 'quick'):
        (cand / 'paths' / f'{name}.md').write_text(f'# {name}\nSteps for {name}.\n', encoding='utf-8')
    engines = ['# Engines', '', '## 1. Choose', 'pick one', ''] + [f'line {i}' for i in range(20)] + \
              ['', '## Tesseract', 'hand the build to its skills', 'the frame stays here', '', '## 6. Other', 'x']
    (cand / 'references' / 'engines.md').write_text('\n'.join(engines) + '\n', encoding='utf-8')
    tess = engines.index('## Tesseract') + 1
    base = str(cand).replace('\\', '/') + '/'
    cases = {c['id']: c for c in spec['route_checks']}
    load_skill = asst('m1', use('t1', 'Skill', {'skill': 'legible-film'}))

    def run(case_id, lines, project=None, fixture=None):
        events = rs.claude_events(lines, {u: True for u in ('tx',)})
        score = rs.score_session(events, cases[case_id], spec, cand)
        return rc.check(cases[case_id], events, score, project, fixture, cand)

    frame = 'audience: builders on X\ntakeaway: picture and sound on one clock\nwhere it plays: the feed\n'
    plan = json.dumps({'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None}, 'events': []})
    r16 = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'paths/create.md'})),
           asst('m3', use('t3', 'Read', {'file_path': base + 'references/engines.md', 'offset': tess - 3,
                                         'limit': 8})),
           asst('m4', use('t4', 'Write', {'file_path': 'C:/p/film.md', 'content': frame})),
           asst('m5', use('t5', 'Write', {'file_path': 'C:/p/film/plan.json', 'content': plan})),
           asst('m6', said('The frame and the plan list are written; the build hands off to Tesseract here.')), end]
    good = run('R16', r16)
    bad = run('R16', r16[:5] + [asst('m6', use('tx', 'Bash', {'command': 'tsrct new launch'})), end])
    record('route check 16: engines.md read over its Tesseract section, frame, plan list, stop at the hand-off; '
           'a tsrct attempt fails it', good['passed'] and not bad['passed'], [n for n in bad['requirements']
                                                                             if not n['met']])
    r17 = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'paths/quick.md'})),
           asst('m3', use('t3', 'Bash', {'command': 'python .claude/skills/legible-film/scripts/listen.py '
                                                    'transcript drop.mp4'})),
           asst('m4', said('Around 0:16 the level rises; these are hints from a measurement, not a listening.')),
           end]
    no_listen = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'paths/quick.md'})),
                 asst('m3', said('The level rises at the drop; these are hints.')), end]
    record('route check 17: quick, listen.py transcript run, hints called hints; without listen.py it fails',
           run('R17', r17)['passed'] and not run('R17', no_listen)['passed'])
    r18 = [load_skill, asst('m2', use('t2', 'Read', {'file_path': base + 'paths/quick.md'})),
           asst('m3', said('Captions written beside the file.')), end]
    triad = r18[:2] + [asst('m3', use('t3', 'Read', {'file_path': base + 'references/finding-the-story.md'})),
                       asst('m4', said('Captions written.')), end]
    record('route check 18: quick with no paper edit and no triad; reading finding-the-story.md fails it',
           run('R18', r18)['passed'] and not run('R18', triad)['passed'])
    r19 = [load_skill, asst('m2', use('t2', 'Bash', {'command': 'python .claude/skills/legible-film/scripts/'
                                                                'screen.py build .'})), end]
    with_cut = [load_skill, asst('m2', use('t2', 'Bash', {'command': 'python .claude/skills/legible-film/scripts/'
                                                                     'cut.py check .'})), end]
    record('route check 19: screen.py run and cut.py never; running cut.py fails it',
           run('R19', r19)['passed'] and not run('R19', with_cut)['passed'])
    project = root / 'r20-project'
    (project / 'handoff').mkdir(parents=True)
    fixture = {'kind': 'paper', 'version': 'v001', 'clips': 3, 'duration_s': 7.72}

    def handoff(path, clips, frames):
        seq = ET.Element('sequence')
        ET.SubElement(seq, 'duration').text = str(frames)
        rate = ET.SubElement(seq, 'rate')
        ET.SubElement(rate, 'timebase').text = '25'
        ET.SubElement(rate, 'ntsc').text = 'FALSE'
        track = ET.SubElement(ET.SubElement(ET.SubElement(seq, 'media'), 'video'), 'track')
        for i in range(clips):
            ET.SubElement(track, 'clipitem', {'id': f'c{i}'})
        root_xml = ET.Element('xmeml', {'version': '4'})
        root_xml.append(seq)
        ET.ElementTree(root_xml).write(path, encoding='utf-8', xml_declaration=True)

    handoff(project / 'handoff' / 'v001.xml', 3, 193)
    r20 = [load_skill, asst('m2', use('t2', 'Bash', {'command': 'python .claude/skills/legible-film/scripts/'
                                                                'exchange.py write . v001 --out handoff/v001.xml'})),
           end]
    good = run('R20', r20, project, fixture)
    handoff(project / 'handoff' / 'v001.xml', 2, 193)
    short = run('R20', r20, project, fixture)
    record('route check 20: exchange.py write, and its XML parses with the paper edit\'s clip count and duration; '
           'a missing clip fails it', good['passed'] and not short['passed'], good['requirements'][-1]['evidence'])
    record('route checks run on a candidate only (a skill with paths/)',
           rc.applies(cand) and not rc.applies(root / '2.0.0' / 'legible-film'))


if __name__ == '__main__':
    sys.exit(main())
