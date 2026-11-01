"""Known answers for preferences and Flask import, using a synthetic project and short synthetic media.

The two version fixtures are cut.py check plans saved as lines.json, not rendered films. These tests establish
recording, arithmetic, scope and import behavior; they do not establish editing quality or human preference.
"""
import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image


def run_cli(scripts, name, *args):
    """Run the actual command without writing interpreter caches into the skill checkout."""
    result = subprocess.run([sys.executable, '-I', '-B', str(Path(scripts) / name), *map(str, args)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    return result.returncode, result.stdout + result.stderr


def paper(seconds):
    """A simple edit using a generated source and one intentionally controlled pause."""
    return ('---\ntitle: Synthetic taste\nsize: 160x90\nfps: 10\ncaptions: none\n---\n'
            '## One\n- src_01 0:00.00-0:01.00 first\n'
            f'- pause {seconds} hold\n- src_01 0:01.00-0:02.00 second\n')


def save_version(root, version, text, report):
    """Keep a version-shaped fixture with the actual compiler's edit-clock report."""
    folder = root / 'cuts' / version
    folder.mkdir(parents=True)
    (folder / 'film.md').write_text(text, encoding='utf-8')
    content = json.dumps(dict(report, film_version=version)).encode('utf-8')
    (folder / 'lines.json').write_bytes(content)
    manifest = {'version': version, 'duration_s': report['duration_s'],
                'files': {'lines.json': hashlib.sha256(content).hexdigest()}}
    (folder / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')


def run_taste_cases(tool, record, j, scripts_dir):
    """Exercise the public commands and the cut.py integration in an isolated synthetic project."""
    scripts = Path(scripts_dir)
    root = Path(j('taste-project'))
    profile = Path(j('taste-shared.md'))
    media = Path(j('taste-colour.mp4'))
    code, output = run_cli(scripts, 'project.py', 'init', root, '--title', 'Synthetic taste')
    if code:
        record('taste: synthetic project initializes', False, output)
        return
    video = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                            'color=c=blue:s=160x90:r=10:d=2', '-an', '-c:v', 'mpeg4', str(media)],
                           capture_output=True, text=True)
    mapped, map_output = run_cli(scripts, 'map.py', 'add', root, media, '--role', 'other')
    if video.returncode or mapped:
        record('taste: generated media registers in the project', False, video.stderr + map_output)
        return
    reports = []
    for name, seconds in (('v001', 0.25), ('v002', 0.75)):
        text = paper(seconds)
        (root / 'film.md').write_text(text, encoding='utf-8')
        code, output = run_cli(scripts, 'cut.py', 'check', root, '--no-audio', '--json')
        if code:
            record('taste: synthetic plans compile', False, output)
            return
        report = json.loads(output)
        reports.append(report)
        save_version(root, name, text, report)
    record('taste: two synthetic plans use the generated source and planted pause lengths',
           [round(next(row['end'] - row['start'] for row in report['lines'] if row['kind'] == 'pause'), 2)
            for report in reports] == [0.25, 0.75], str(reports))
    notes = {'version': 1, 'notes': [
        {'id': 'n1', 'version': 'v001', 't': 1.1, 'author': 'person', 'kind': 'note', 'text': 'Give it a beat.',
         'status': 'done', 'resolved_in': 'v002', 'reply': 'The pause was extended.'},
        {'id': 'n2', 'version': 'v001', 't': 1.1, 'author': 'person', 'kind': 'note', 'text': 'Another note.',
         'status': 'done', 'resolved_in': 'v002', 'reply': 'The pause was extended.'}]}
    (root / 'notes.json').write_text(json.dumps(notes), encoding='utf-8')
    (root / 'decisions.jsonl').write_text(json.dumps({'by': 'person', 'version': 'v001',
                                                     'decision': 'Keep the blue picture.'}) + '\n', encoding='utf-8')
    code, output = run_cli(scripts, 'taste.py', 'use', root, '--person', 'Alex', '--file', profile)
    record('taste: person and shared profile are bound', code == 0 and profile.name in output, output)
    measure = ('--measure', 'pause_duration', '--op', '>=', '--value', '0.5', '--unit', 's')
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Keep a half-second pause',
                           '--note', 'n1', '--change', 'Extended it in v002', *measure)
    initial, before = run_cli(scripts, 'taste.py', 'check', root, 'v001', '--json')
    record('taste: a proposed preference is film-specific and is never checked', code == 0 and initial == 0
           and 'p001' in output and json.loads(before)['preferences'] == [], output + before)
    code, output = run_cli(scripts, 'taste.py', 'confirm', root, 'p001', '--by', 'Alex',
                           '--words', 'Yes, just for this film.')
    shown, text = run_cli(scripts, 'taste.py', 'show', root, '--json')
    pref = json.loads(text)[0]
    record('taste: confirmation records the person, exact words, time, scope and evidence', code == shown == 0
           and pref['status'] == 'confirmed' and pref['scope'] == 'this film'
           and pref['decision']['by'] == 'Alex' and pref['decision']['words'] == 'Yes, just for this film.'
           and pref['decision']['at'] and pref['evidence'][0]['source'] == 'note:n1', output + text)
    bad, bad_text = run_cli(scripts, 'taste.py', 'check', root, 'v001', '--json')
    good, good_text = run_cli(scripts, 'taste.py', 'check', root, 'v002', '--json')
    bad_row = json.loads(bad_text)['preferences'][0]
    good_row = json.loads(good_text)['preferences'][0]
    record('taste: the planted short pause is a look and the longer pause passes', bad == 1 and good == 0
           and bad_row['state'] == 'look' and bad_row['moments'][0]['value'] == 0.25
           and bad_row['moments'][0]['at'] == 1 and good_row['state'] == 'pass'
           and good_row['moments'][0]['value'] == 0.75 and bad_row['evidence'], bad_text + good_text)
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Keep a half-second pause',
                           '--note', 'n2', '--change', 'Extended it in v002', *measure)
    shown, text = run_cli(scripts, 'taste.py', 'show', root, '--json')
    record('taste: a duplicate merges evidence without changing confirmation', code == shown == 0
           and 'merged p001' in output and len(json.loads(text)[0]['evidence']) == 2
           and json.loads(text)[0]['status'] == 'confirmed', output + text)
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Keep it below a tenth',
                           '--note', 'n2', '--change', 'A different candidate', '--measure', 'pause_duration',
                           '--op', '<=', '--value', '0.1', '--unit', 's')
    record('taste: incompatible numeric checks are shown as a contradiction, not resolved',
           code == 1 and 'contradiction' in output and 'p001' in output, output)
    decline, output = run_cli(scripts, 'taste.py', 'decline', root, 'p002', '--by', 'Alex',
                              '--words', 'No; keep the longer beat.')
    shown, text = run_cli(scripts, 'taste.py', 'show', root, '--json')
    pref = json.loads(text)[1]
    record('taste: decline preserves the person\'s words and leaves the item unchecked', decline == shown == 0
           and pref['status'] == 'declined' and pref['decision']['words'] == 'No; keep the longer beat.', output)
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Consider a clear story',
                           '--decision', '1', '--change', 'Kept the scene')
    confirmed, output2 = run_cli(scripts, 'taste.py', 'confirm', root, 'p003', '--by', 'Alex',
                                 '--words', 'Yes, across my films.', '--general')
    denied, output3 = run_cli(scripts, 'taste.py', 'confirm', root, 'p003', '--by', 'SomeoneElse',
                              '--words', 'Pretend I am Alex', '--general')
    record('taste: only the named person can confirm general scope and their words are retained',
           code == confirmed == 0 and denied == 2, output + output2 + output3)
    second = Path(j('taste-other-project'))
    run_cli(scripts, 'project.py', 'init', second)
    run_cli(scripts, 'taste.py', 'use', second, '--person', 'Alex', '--file', profile)
    code, output = run_cli(scripts, 'taste.py', 'show', second, '--confirmed', '--json')
    record('taste: a different film sees general direction but not film-specific preferences', code == 0
           and [row['id'] for row in json.loads(output)] == ['p003']
           and json.loads(output)[0]['decision']['words'] == 'Yes, across my films.', output)
    original_binding = (second / 'taste.json').read_bytes()
    code, output = run_cli(scripts, 'taste.py', 'use', second, '--person', 'DifferentPerson', '--file', profile)
    record('taste: a shared file for another person is refused without changing the binding', code == 2
           and (second / 'taste.json').read_bytes() == original_binding, output)
    other = Path(j('taste-person-name'))
    run_cli(scripts, 'project.py', 'init', other)
    code, output = run_cli(scripts, 'taste.py', 'use', other, '--person', 'Sam Lee',
                           '--file', Path(j('sam-profile.md')))
    record('taste: a person name may contain spaces', code == 0
           and json.loads((other / 'taste.json').read_text(encoding='utf-8'))['person'] == 'Sam Lee', output)
    binding_before = (other / 'taste.json').read_bytes()
    code, output = run_cli(scripts, 'taste.py', 'use', other, '--person', 'Sam Lee', '--file',
                           other / 'taste.json')
    record('taste: a profile cannot overwrite or deadlock the project binding',
           code == 2 and (other / 'taste.json').read_bytes() == binding_before, output)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('taste_test_default', scripts / 'taste.py')
        taste = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(taste)
        taste.setup.data_home = lambda: Path(j('synthetic-user-data'))
        default = taste.use(other, 'Sam Lee', None)
    finally:
        sys.dont_write_bytecode = previous
    record('taste: the default profile uses the existing per-user data home',
           default == Path(j('synthetic-user-data', 'preferences', 'Sam Lee.md')) and default.is_file(), str(default))
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Compare sound at joins',
                           '--note', 'n1', '--change', 'A later comparison', '--measure', 'join_level_change',
                           '--op', '<=', '--value', '3', '--unit', 'dB')
    run_cli(scripts, 'taste.py', 'confirm', root, 'p004', '--by', 'Alex', '--words', 'Yes for this film.')
    checked, output = run_cli(scripts, 'taste.py', 'check', root, 'v002', '--json')
    rows = json.loads(output)['preferences']
    record('taste: missing join sound measurement is not assessed, never passed', checked == 1
           and next(row for row in rows if row['id'] == 'p004')['state'] == 'not assessed', output)
    partial = json.loads(json.dumps(reports[1]))
    partial['joins'] = [{'at': 1, 'jump_db': -2}, {'at': 1.75}]
    save_version(root, 'v003', paper(0.75), partial)
    checked, output = run_cli(scripts, 'taste.py', 'check', root, 'v003', '--json')
    partial_row = next(row for row in json.loads(output)['preferences'] if row['id'] == 'p004')
    record('taste: a passing measurement cannot hide an unmeasured join', checked == 1
           and partial_row['state'] == 'not assessed' and '1 matching join' in partial_row['reason'], output)
    partial['joins'][0]['jump_db'] = 5
    save_version(root, 'v004', paper(0.75), partial)
    checked, output = run_cli(scripts, 'taste.py', 'check', root, 'v004', '--json')
    partial_row = next(row for row in json.loads(output)['preferences'] if row['id'] == 'p004')
    record('taste: a real look remains visible when another join is unmeasured', checked == 1
           and partial_row['state'] == 'look' and '1 matching join' in partial_row['reason'], output)
    (root / 'film.md').write_text(paper(0.25), encoding='utf-8')
    code, output = run_cli(scripts, 'cut.py', 'check', root, '--no-audio', '--json')
    report = json.loads(output)
    planned = next(row for row in report['preferences']['details'] if row['id'] == 'p001')
    record('taste: cut.py check reports preference looks without making them errors', code == 0
           and report['preferences']['confirmed'] == 3 and 'p001' in report['preferences']['looks']
           and report['errors'] == 0 and planned['moments'][0]['value'] == 0.25, output[-1000:])
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location('taste_test_cut', scripts / 'cut.py')
        cut = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cut)
        settings = {'size': (160, 90), 'fps_text': '10', 'title': 'Synthetic taste', 'captions': set()}
        args = SimpleNamespace(resolves='', label='', final=False)
        manifest = cut.write_manifest(root / 'cuts' / 'v001', 'v001', None, args, settings, (160, 90),
                                      paper(0.25), [], None, [], 0.1, root, 2.25, 23)
    finally:
        sys.dont_write_bytecode = previous
    record('taste: the version manifest carries the same non-gating preference summary',
           manifest['preferences']['confirmed'] == 3 and 'p001' in manifest['preferences']['looks']
           and 'p004' in manifest['preferences']['not_assessed']
           and 'taste.py check PROJECT v001' in manifest['preferences']['summary']
           and 'details' not in manifest['preferences'], str(manifest.get('preferences')))
    code, output = run_cli(scripts, 'taste.py', 'candidates', root, '--json')
    candidates = json.loads(output)
    note = next(row for row in candidates if row['source'] == 'note:n1')
    record('taste: candidates expose a note, resolution, measured changes and the whole-version diff', code == 0
           and note['text'] == 'Give it a beat.' and note['diff']['from'] == 'v001'
           and note['diff']['to'] == 'v002' and any(row['measure'] == 'pause_duration'
                                                    for row in note['before_measures'])
           and any(row['measure'] == 'pause_duration' for row in note['after_measures']), output[-1000:])
    flask = Path(j('flask-notes.json'))
    (root / 'review').mkdir(exist_ok=True)
    Image.new('RGB', (8, 8), (255, 0, 0)).save(root / 'review' / 'frame.png')
    flask.write_text(json.dumps([{'id': 'fb-1', 'time': 0.4, 'text': 'A drawn note', 'author': 'Sam',
                                  'version': 'v001', 'drawn_frame': 'review/frame.png'}]), encoding='utf-8')
    first, output = run_cli(scripts, 'screen.py', 'import-notes', root, flask, '--origin', 'flask')
    one = (root / 'notes.json').read_bytes()
    again, output2 = run_cli(scripts, 'screen.py', 'import-notes', root, flask, '--origin', 'flask')
    imported = json.loads(one)['notes'][-1]
    record('taste: Flask import preserves words, author, version, ID and drawing; reimport changes nothing',
           first == again == 0 and one == (root / 'notes.json').read_bytes() and imported['flask_id'] == 'fb-1'
           and imported['origin'] == 'flask' and imported['text'] == 'A drawn note'
           and imported['author'] == 'Sam' and imported['version'] == 'v001'
           and imported['drawn_frame'] == 'review/frame.png' and '1 already present' in output2, output + output2)
    profile_before = profile.read_bytes()
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Mistake another reviewer for Alex',
                           '--note', imported['id'], '--change', 'No change')
    listed, output2 = run_cli(scripts, 'taste.py', 'candidates', root, '--json')
    record('taste: another named reviewer\'s Flask note cannot become the bound person\'s preference',
           code == 2 and listed == 0 and profile.read_bytes() == profile_before
           and all(row['source'] != 'note:' + imported['id'] for row in json.loads(output2)), output)
    flask.write_text(json.dumps([{'id': 'fb-1', 'time': 0.4, 'text': 'Edited remotely', 'author': 'Sam',
                                  'version': 'v001', 'drawn_frame': 'review/frame.png'}]), encoding='utf-8')
    changed, output = run_cli(scripts, 'screen.py', 'import-notes', root, flask, '--origin', 'flask')
    record('taste: a changed Flask note is reported without replacing the existing record',
           changed == 1 and 'differ' in output and one == (root / 'notes.json').read_bytes(), output)
    flask.write_text(json.dumps([{'id': 'fb-2', 'time': 0.4, 'text': 'Outside image', 'author': 'Sam',
                                  'version': 'v001', 'drawn_frame': str(media)}]), encoding='utf-8')
    invalid, output = run_cli(scripts, 'screen.py', 'import-notes', root, flask, '--origin', 'flask')
    record('taste: an outside frame path is refused before a shared page can expose it',
           invalid == 2 and one == (root / 'notes.json').read_bytes(), output)
    flask.write_text(json.dumps([{'id': 'fb-2', 'time': 0.1, 'text': 'valid', 'author': 'Sam', 'version': 'v001'},
                                 {'id': 'fb-3', 'time': -1, 'text': 'invalid', 'author': 'Sam',
                                  'version': 'v001'}]), encoding='utf-8')
    bad, output = run_cli(scripts, 'screen.py', 'import-notes', root, flask, '--origin', 'flask')
    record('taste: an invalid Flask batch adds nothing', bad == 2 and one == (root / 'notes.json').read_bytes(), output)
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Leave this line a beat',
                           '--note', 'n1', '--change', 'Kept the beat', '--measure', 'pause_after_line',
                           '--op', '>=', '--value', '1', '--unit', 's', '--word', 'src_01-w000001')
    confirmed, output2 = run_cli(scripts, 'taste.py', 'confirm', root, 'p005', '--by', 'Alex',
                                 '--words', 'Yes, in general.', '--general')
    spoken = {'duration_s': 3, 'picture_changes': [], 'joins': [], 'busy_cutting': [], 'lines': [
        {'line': 1, 'kind': 'spoken', 'start': 0, 'end': 1,
         'words': [{'id': 'src_01-w000001', 'start': 0.2, 'end': 0.9}]},
        {'line': 2, 'kind': 'spoken', 'start': 1.2, 'end': 2,
         'words': [{'id': 'src_01-w000002', 'start': 1.2, 'end': 1.8}]}]}
    save_version(root, 'v005', paper(0.75), spoken)
    checked, output3 = run_cli(scripts, 'taste.py', 'check', root, 'v005', '--json')
    beat = next(row for row in json.loads(output3)['preferences'] if row['id'] == 'p005')
    record('taste: a word-anchored beat uses edit-time word edges at the matching moment',
           code == confirmed == 0 and checked == 1 and beat['state'] == 'look'
           and beat['moments'][0]['value'] == 0.3 and beat['moments'][0]['word'] == 'src_01-w000001',
           output + output2 + output3)
    save_version(second, 'v001', paper(0.75), spoken)
    checked, output = run_cli(scripts, 'taste.py', 'check', second, 'v001', '--json')
    beat = next(row for row in json.loads(output)['preferences'] if row['id'] == 'p005')
    record('taste: a general direction never reuses a word anchor in a different project', checked == 1
           and beat['state'] == 'not assessed' and 're-anchor' in beat['reason'], output)
    incomplete = json.loads(json.dumps(spoken))
    incomplete['lines'].insert(1, {'line': 3, 'kind': 'spoken', 'start': 1, 'end': 1.1, 'words': []})
    save_version(root, 'v006', paper(0.75), incomplete)
    checked, output = run_cli(scripts, 'taste.py', 'check', root, 'v006', '--json')
    beat = next(row for row in json.loads(output)['preferences'] if row['id'] == 'p005')
    record('taste: a missing intervening transcript cannot masquerade as a measured beat',
           beat['state'] == 'not assessed' and 'could not be measured' in beat['reason'], output)
    lines_path = root / 'cuts' / 'v002' / 'lines.json'
    original_lines = lines_path.read_bytes()
    lines_path.write_bytes(original_lines + b' ')
    code, output = run_cli(scripts, 'taste.py', 'check', root, 'v002', '--json')
    record('taste: changed version measurement data cannot silently pass',
           code == 2 and 'changed since the version was made' in output, output)
    lines_path.write_bytes(original_lines)
    valid = profile.read_text(encoding='utf-8')
    profile.write_text(valid.replace('- status:', '- broken:', 1), encoding='utf-8')
    malformed = profile.read_bytes()
    code, output = run_cli(scripts, 'taste.py', 'propose', root, '--statement', 'Do not overwrite malformed data',
                           '--note', 'n1', '--change', 'example')
    record('taste: malformed editable Markdown is rejected without being overwritten', code == 2
           and profile.read_bytes() == malformed, output)
    profile.write_text(valid, encoding='utf-8')
    templates = scripts.parent / 'assets' / 'templates'
    instructions = [(templates / name).read_text(encoding='utf-8')
                    for name in ('plan-review-brief.md', 'cut-review-brief.md')]
    record('taste: both review briefs read all confirmed preferences as material', all(
        'taste.py show PROJECT --confirmed' in item and 'unmeasurable' in item and 'instructions' in item
        for item in instructions))
