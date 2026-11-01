"""Known-answer cases for project.py: the project-folder layout every 2.0 script shares."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
from pathlib import Path


def check_dead_running_job(record, j, scripts_dir):
    """Dead PIDs do not hide readiness; live and legacy jobs are retained."""
    spec = importlib.util.spec_from_file_location('project_dead_job', Path(scripts_dir) / 'project.py')
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    root = Path(j('dead-job-project'))
    project.init(root, 'Dead job')
    dead = {'job': 'map int_01', 'pid': 2147483647, 'progress': 0}
    live = {'job': 'map int_02', 'pid': os.getpid(), 'progress': .5}
    legacy = {'job': 'render v001', 'progress': .2}
    project.update_status(root, running=[dead, live, legacy])
    status = project.read_status(root)
    line = project.status_line(root)
    record('project: dead map PID is filtered while live and legacy jobs remain',
           status['running'] == [live, legacy] and line == 'map int_02 50%', str((status['running'], line)))


def check_shared_guards(record, j, project):
    """An output that names an input is refused (the same path, another spelling of it, a hard link); a transcript is
    current only for the media and sound stream it was made from."""
    folder = Path(j('guard-case'))
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / 'captions.srt'
    source.write_text('1\n00:00:00,000 --> 00:00:01,000\nhello\n', encoding='utf-8')
    refused = []
    spellings = [source, folder / '.' / 'captions.srt', folder / 'sub' / '..' / 'captions.srt']
    linked = folder / 'linked.srt'
    try:
        os.link(source, linked)
        spellings.append(linked)
    except (OSError, NotImplementedError, AttributeError):
        pass
    for spelling in spellings:
        try:
            project.refuse_overwriting_inputs([spelling], [None, source])
            refused.append(False)
        except ValueError:
            refused.append(True)
    try:
        project.refuse_overwriting_inputs([folder / 'report.json', None], [source])
        allowed = True
    except ValueError:
        allowed = False
    record('project: an output naming an input is refused, through any spelling or a hard link',
           all(refused) and allowed and len(refused) >= 3, str((refused, allowed)))
    source_row = {'sha256': 'a' * 64, 'audio': {'index': 1}}
    states = [project.transcript_state(source_row, data)[0] for data in (
        {'words': []},
        {'media': {'sha256': 'a' * 64, 'audio_stream': 1}},
        {'media': {'sha256': 'b' * 64, 'audio_stream': 1}},
        {'media': {'sha256': 'a' * 64, 'audio_stream': 2}},
        {'media': {'sha256': 'a' * 64}})]
    record('project: a transcript is current only for the bytes and stream it was made from',
           states == ['unbound', 'current', 'stale', 'stale', 'stale'], str(states))


def check_init_from_paper_edit(tool, record, j):
    """init --film starts a project from a paper edit, is safe to repeat, and never replaces a different film.md (the
    quickstart once copied the example's edit over whatever was there)."""
    paper = Path(j('init-film', 'example.md'))
    paper.parent.mkdir(parents=True, exist_ok=True)
    paper.write_text('# Example\n> src_01 0:01.00-0:02.00 hello\n', encoding='utf-8')
    fresh = Path(j('init-film', 'fresh'))
    first, _ = tool('project.py', 'init', fresh, '--film', paper)
    again, _ = tool('project.py', 'init', fresh, '--film', paper)
    theirs = Path(j('init-film', 'theirs'))
    theirs.mkdir(parents=True, exist_ok=True)
    (theirs / 'film.md').write_text('# My own edit\n', encoding='utf-8')
    refused, output = tool('project.py', 'init', theirs, '--film', paper)
    record('project: init --film starts from a paper edit, repeats safely, and refuses a different film.md before '
           'any change', first == 0 and again == 0
           and (fresh / 'film.md').read_text(encoding='utf-8') == paper.read_text(encoding='utf-8')
           and refused == 2 and (theirs / 'film.md').read_text(encoding='utf-8') == '# My own edit\n'
           and not (theirs / 'status.json').exists() and 'nothing was changed' in output, output[-200:])


def run_project_cases(tool, record, j, scripts_dir):
    """Layout, atomic status, versions, aliases, times and the chat status line."""
    check_init_from_paper_edit(tool, record, j)
    polish_stage_cases(tool, record, j)
    spec = importlib.util.spec_from_file_location('lf_project_cases', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    check_dead_running_job(record, j, scripts_dir)
    check_shared_guards(record, j, project)
    check_input_freshness(tool, record, j, project)
    check_status_fields(tool, record, j, project)
    run_fix2_project_cases(tool, record, j, project, scripts_dir)
    run_fix2_tool_freshness_case(record, j, scripts_dir)
    root = Path(j('project-case'))
    code, output = tool('project.py', 'init', root, '--title', 'Case film')
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('project: init lays out the folder and a status with every stage to do',
           code == 0 and all((root / name).is_dir() for name in ('map', 'cuts', 'screening', 'deliver'))
           and status['title'] == 'Case film' and set(status['stages'].values()) == {'todo'}, output[-200:])
    project.set_stage(root, 'map')
    project.set_stage(root, 'plan', line='planning the cut')
    project.set_stage(root, 'map')
    record('project: earlier work does not regress the stage', project.read_status(root)['stage'] == 'plan')
    stages = project.read_status(root)['stages']
    record('project: moving forward completes the stage it leaves',
           stages['map'] == 'done' and stages['plan'] == 'now' and stages['cut'] == 'todo', str(stages))
    project.set_stage(root, 'revise')
    project.set_stage(root, 'cut', back=True)
    stages = project.read_status(root)['stages']
    record('project: explicit backward move resets later stages', stages['cut'] == 'now'
           and all(stages[s] == 'todo' for s in ('check', 'screen', 'revise', 'deliver')), str(stages))
    worker = ('import importlib.util,sys; s=importlib.util.spec_from_file_location("p",sys.argv[1]); '
              'p=importlib.util.module_from_spec(s); s.loader.exec_module(p); '
              'p.update_status(sys.argv[2], **{sys.argv[3]: True})')
    workers = [subprocess.Popen([sys.executable, '-c', worker, str(Path(scripts_dir) / 'project.py'), str(root),
                                 'parallel_' + str(i)]) for i in range(12)]
    exits = [worker.wait(timeout=30) for worker in workers]
    status = project.read_status(root)
    record('project: concurrent processes preserve every status update', all(code == 0 for code in exits)
           and all(status.get('parallel_' + str(i)) is True for i in range(12)), str(exits))
    original_replace = project.os.replace
    calls = []
    def flaky_replace(source, destination):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError('reader temporarily holds destination')
        return original_replace(source, destination)
    with patch.object(project.os, 'replace', side_effect=flaky_replace):
        project.write_atomic(root / 'retry.txt', 'saved\n')
    record('project: atomic replacement retries temporary access denial', len(calls) == 3
           and (root / 'retry.txt').read_text(encoding='utf-8') == 'saved\n', str(len(calls)))
    holder = ('import importlib.util,os,sys; s=importlib.util.spec_from_file_location("p",sys.argv[1]); '
              'p=importlib.util.module_from_spec(s); s.loader.exec_module(p)\n'
              'with p.file_lock(sys.argv[2]):\n    os._exit(1)')
    subprocess.run([sys.executable, '-c', holder, str(Path(scripts_dir) / 'project.py'), str(root / 'notes.json')])
    started = time.monotonic()
    with project.file_lock(root / 'notes.json', timeout=5):
        waited = time.monotonic() - started
    record('project: a lock left by a process that died is broken at once', waited < 1, f'{waited:.2f} s')
    sleeper = subprocess.Popen([sys.executable, '-c', holder.replace('os._exit(1)', 'import time; time.sleep(2)'),
                                str(Path(scripts_dir) / 'project.py'), str(root / 'decisions.jsonl')])
    time.sleep(0.8)
    started = time.monotonic()
    with project.file_lock(root / 'decisions.jsonl', timeout=10):
        waited = time.monotonic() - started
    sleeper.wait(timeout=30)
    record('project: a lock whose holder still runs is waited for', waited > 0.5, f'{waited:.2f} s')
    sleeper = subprocess.Popen([sys.executable, '-c', holder.replace('os._exit(1)', 'import time; time.sleep(4)'),
                                str(Path(scripts_dir) / 'project.py'), str(root / 'aged.json')])
    lock = root / '.aged.json.lock'
    for _ in range(100):
        if lock.exists():
            break
        time.sleep(0.05)
    os.utime(lock, (time.time() - 3600, time.time() - 3600))
    try:
        with project.file_lock(root / 'aged.json', timeout=1):
            outcome = 'acquired while the holder ran'
    except TimeoutError as error:
        outcome = str(error)
    sleeper.wait(timeout=30)
    record('project: an old lock whose holder still runs is never broken; the wait names the holder',
           'holds it and is still running' in outcome, outcome)
    partial = Path(j('partial-version'))
    project.init(partial, 'Partial')
    (partial / 'cuts' / 'v001').mkdir(parents=True)
    project.save_json(partial / 'cuts' / 'v001' / 'manifest.json', {'version': 'v001'})
    record('project: an incomplete version folder is not reported as rendered',
           'rendered' not in project.status_line(partial), project.status_line(partial))
    leftovers = [name for name in os.listdir(root) if name.startswith('.status.json.')]
    record('project: status writes leave no temporary files behind', not leftovers, str(leftovers))
    try:
        project.update_status(root, stages={'plan': 'finished'})
        refused = False
    except ValueError:
        refused = True
    record('project: an unknown stage state is refused', refused)
    names = [project.next_version(root)]
    for name in ('v001', 'v002', 'v010'):
        (root / 'cuts' / name).mkdir()
        (root / 'cuts' / name / 'film.md').write_text('---\n---\n', encoding='utf-8')
        (root / 'cuts' / name / 'preview.mp4').write_bytes(b'')
        project.save_json(root / 'cuts' / name / 'manifest.json', {'version': name})
    names += [project.versions(root), project.current_version(root), project.next_version(root)]
    project.set_current(root, 'v002')
    names.append(project.current_version(root))
    record('project: versions sort by number, the next is one past the newest, current follows cuts/current',
           names == ['v001', ['v001', 'v002', 'v010'], 'v010', 'v011', 'v002'], str(names))
    (root / 'cuts' / 'v002' / 'checks.json').write_text(json.dumps(
        {'version': 1, 'items': [], 'summary': {'pass': 11, 'look': 1, 'fail': 0, 'you': 2, 'skip': 0}}),
        encoding='utf-8')
    line = project.status_line(root)
    record('project: the chat status line names the version and its readiness; a checks file written before inputs '
           'were recorded reads as before, marked so',
           line == 'v2 checked · 11 checks pass · 1 to look at · 2 need you · inputs not recorded', line)
    checks = {'items': [{'id': 'bad', 'state': 'fail'}], 'summary': {'pass': 99, 'fail': 0}}
    project.save_json(root / 'cuts' / 'v002' / 'checks.json', checks)
    project.update_status(root, reviewed={'v002': {'approved': {'by': 'person', 'at': project.now()}}})
    line = project.status_line(root)
    record('project: approval and a failed check are both visible', 'approved' in line and '1 failed' in line
           and 'ready' not in line and '99 checks pass' not in line, line)
    project.save_json(root / 'cuts' / 'v002' / 'checks-final.json', {
        'final': True, 'file': 'deliver/final.mp4', 'sha256': 'f' * 64,
        'items': [{'id': 'spec', 'state': 'fail'}, {'id': 'watched_muted', 'state': 'you'}]})
    project.update_status(root, reviewed={'v002': {'watched_muted': {'by': 'person', 'at': project.now()}}})
    line = project.status_line(root)
    record('project: the status line shows a final check with its file; an older preview review does not cover it',
           'final deliver/final.mp4 checked' in line and '1 failed' in line and '1 need you' in line, line)
    rules = [project.review_applies({'by': 'person'}, 'a' * 64, True),
             project.review_applies({'by': 'person'}, 'a' * 64, False),
             project.review_applies({'by': 'person', 'sha256': 'a' * 64}, 'a' * 64, False),
             project.review_applies({'by': 'person', 'sha256': 'a' * 64}, 'b' * 64, True)]
    record('project: a review counts for the file it names; one without a hash counts for the preview only',
           rules == [True, False, True, False], str(rules))
    (root / 'cuts' / 'v002' / 'checks-final.json').unlink()
    project.update_status(root, running=[{'job': 'render v011', 'progress': 0.4}])
    record('project: a running job takes over the status line', project.status_line(root) == 'render v011 40%',
           project.status_line(root))
    aliases = [project.new_alias('interview', {'int_01', 'int_02'}), project.new_alias('broll', set())]
    record('project: aliases are a role and a number, never a file name', aliases == ['int_03', 'broll_01'],
           str(aliases))
    times = [project.parse_time('12:03.40'), project.parse_time('1:02:03.5'), project.format_time(723.4),
             project.format_time(3723.5), project.format_time(0.004)]
    record('project: source times parse and format both ways',
           times == [723.4, 3723.5, '12:03.40', '1:02:03.50', '0:00.00'], str(times))
    bom = root / 'bom.json'
    bom.write_bytes(b'\xef\xbb\xbf' + json.dumps({'a': 1}).encode('utf-8'))
    utf16 = root / 'utf16.json'
    utf16.write_bytes(json.dumps({'b': 2}).encode('utf-16'))
    record('project: JSON from Windows tools loads (UTF-8 with a mark, UTF-16)',
           project.load_json(bom) == {'a': 1} and project.load_json(utf16) == {'b': 2})
    found = project.find_project(root / 'cuts' / 'v002')
    record('project: a project is found from any folder inside it', found == root.resolve(), str(found))


def polish_stage_cases(tool, record, j):
    """Stage commands keep waiting visible until explicitly resolved."""
    root = Path(j('polish-stages'))
    tool('project.py', 'init', root)
    code, output = tool('project.py', 'stage', root, 'plan', 'waiting', '--note', 'Agree the direction')
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    shown_code, shown = tool('project.py', 'status', root)
    record('project: stage waits for the person and status names the note',
           code == shown_code == 0 and status['stages']['plan'] == 'waiting'
           and 'waiting' in shown.lower() and 'plan' in shown.lower()
           and 'Agree the direction' in shown, output + shown)
    spec = importlib.util.spec_from_file_location('polish_wait_project', Path(__file__).resolve().parent.parent
                                                   / 'project.py')
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    project.set_stage(root, 'plan', line='another automatic planning call')
    after_auto = project.read_status(root)
    record('project: an automatic call cannot clear a stage waiting for a person',
           after_auto['stages']['plan'] == 'waiting', str(after_auto))
    moved, moved_output = tool('project.py', 'stage', root, 'cut', 'now')
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('project: advancing another stage never silently completes a wait',
           moved == 0 and status['stages']['plan'] == 'waiting' and 'waiting' in moved_output, moved_output)
    done, output = tool('project.py', 'stage', root, 'plan', 'done')
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('project: explicit done resolves an earlier waiting stage without going backwards',
           done == 0 and status['stages']['plan'] == 'done' and status['stage'] == 'cut', output)
    tool('project.py', 'stage', root, 'cut', 'waiting', '--note', 'Choose the ending')
    project.update_status(root, line=project.status_line(root))
    waiting_line = project.read_status(root)['line']
    tool('project.py', 'stage', root, 'cut', 'waiting', '--note', 'Choose the ending')
    repeated_line = project.read_status(root)['line']
    tool('project.py', 'stage', root, 'cut', 'done')
    done_line = project.read_status(root)['line']
    record('project: the saved status line drops a wait once the stage is done, and never repeats it',
           'Choose the ending' in waiting_line and repeated_line.count('waiting for person') == 1
           and 'waiting for person' not in done_line, str((waiting_line, repeated_line, done_line)))


def freshness_project(project, root):
    """A project with one complete version whose checks.json records its preview and captions as inputs."""
    project.init(root, 'Freshness')
    folder = root / 'cuts' / 'v001'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'film.md').write_text('---\ntitle: Freshness\n---\n', encoding='utf-8')
    (folder / 'preview.mp4').write_bytes(b'preview bytes')
    (folder / 'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n', encoding='utf-8')
    project.save_json(folder / 'manifest.json', {'version': 'v001'})
    project.set_current(root, 'v001')
    digest = project.file_sha256(folder / 'preview.mp4')
    inputs = [project.input_row('preview', folder / 'preview.mp4', 'cuts/v001/preview.mp4'),
              project.input_row('captions', folder / 'captions.srt', 'cuts/v001/captions.srt'),
              project.input_row('declared', folder / 'declared.json', 'cuts/v001/declared.json')]
    items = [{'id': 'spec', 'label': 'Spec', 'state': 'pass'},
             {'id': 'watched_muted', 'label': 'Watched by you, muted', 'state': 'you'}]
    spec = importlib.util.spec_from_file_location('lf_freshness_check', Path(project.__file__).with_name('check.py'))
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    project.save_json(folder / 'checks.json', {'version': 1, 'file': 'cuts/v001/preview.mp4', 'sha256': digest,
                                               'final': False, 'items': items,
                                               'summary': {'pass': 1, 'look': 0, 'fail': 0, 'you': 1, 'skip': 0},
                                               'inputs_base': 'project', 'inputs': inputs,
                                               'tools': check.tools_record()})
    return folder


def check_input_freshness(tool, record, j, project):
    """A checks file expires when a recorded input changes: compared by size and time first, hashed only when the
    size matches and the time differs; a touched file with the same content stays current; a file added since the
    check (declared.json) expires it too."""
    from unittest.mock import patch
    root = Path(j('freshness-project'))
    folder = freshness_project(project, root)
    first = project.status_line(root)
    real_hash = project.file_sha256

    def only_tool_hashes(path):
        try:
            Path(path).resolve().relative_to(root.resolve())
        except ValueError:
            return real_hash(path)
        raise AssertionError('hashed a project input')

    with patch.object(project, 'file_sha256', side_effect=only_tool_hashes):
        unchanged_without_hashing = project.checks_freshness(root, project.load_json(folder / 'checks.json'))[0]
    captions = folder / 'captions.srt'
    stamp = captions.stat().st_mtime_ns
    os.utime(captions, ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    touched = project.status_line(root)
    captions.write_text('1\n00:00:00,000 --> 00:00:01,000\nHallo\n', encoding='utf-8')
    os.utime(captions, ns=(stamp + 9_000_000_000, stamp + 9_000_000_000))
    same_size = project.status_line(root)
    captions.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello there\n', encoding='utf-8')
    with patch.object(project, 'file_sha256', side_effect=only_tool_hashes):
        resized = project.checks_freshness(root, project.load_json(folder / 'checks.json'))
    record('project: checks expire when an input changes (hashed only when its size matches and its time differs); '
           'a touched file with the same content stays current',
           'pass' in first and 'out of date' not in first and unchanged_without_hashing == 'current'
           and 'out of date' not in touched and 'out of date (cuts/v001/captions.srt changed)' in same_size
           and 'pass' not in same_size and resized[0] == 'out_of_date', str((first, touched, same_size, resized)))
    captions.write_text('1\n00:00:00,000 --> 00:00:01,000\nHello\n', encoding='utf-8')
    project.save_json(folder / 'declared.json', {'holds': []})
    added = project.status_line(root)
    (folder / 'declared.json').unlink()
    back = project.status_line(root)
    record('project: an input added since the check expires it; the same content again is current',
           'cuts/v001/declared.json added since' in added and 'out of date' not in back, str((added, back)))


def check_status_fields(tool, record, j, project):
    """status --json keeps progress, the current checks, open review items and acceptance apart: a stage marked done
    is never acceptance, and approval counts only for the file whose SHA-256 it names."""
    root = Path(j('fields-project'))
    folder = freshness_project(project, root)
    project.update_status(root, stages={'check': 'done', 'deliver': 'done'})
    code, output = tool('project.py', 'status', root, '--json')
    try:
        report = json.loads(output)
    except ValueError:
        report = {}
    checks = (report.get('checks') or {}).get('preview') or {}
    record('project: status --json prints progress, checks, review and acceptance as separate fields; a done stage '
           'is not acceptance', code == 0 and report.get('progress', {}).get('stages', {}).get('deliver') == 'done'
           and checks.get('state') == 'current' and checks.get('summary', {}).get('pass') == 1
           and report.get('review', {}).get('open') == ['Watched by you, muted']
           and report.get('acceptance') == {'preview': None, 'final': None}
           and 'approved' not in report.get('line', ''), output[-600:])
    project.record_review(root, 'v001', 'approved')
    final = root / 'deliver' / 'final.mp4'
    final.write_bytes(b'a final nobody approved')
    project.save_json(folder / 'checks-final.json', {
        'version': 1, 'final': True, 'file': 'deliver/final.mp4', 'sha256': project.file_sha256(final),
        'items': [{'id': 'spec', 'state': 'pass'}], 'summary': {'pass': 1},
        'inputs_base': 'project', 'inputs': [project.input_row('final', final, 'deliver/final.mp4')],
        'tools': project.load_json(folder / 'checks.json')['tools']})
    (folder / 'captions.srt').write_text('changed captions\n', encoding='utf-8')
    report = project.status_report(root)
    line = report['line']
    preview, final_checks = report['checks']['preview'], report['checks']['final']
    record('project: an approved preview is not an approved final; out-of-date checks report what changed and no '
           'counts', report['acceptance']['preview'] is not None and report['acceptance']['final'] is None
           and preview['state'] == 'out_of_date' and preview['summary'] is None
           and preview['changed'][0]['path'] == 'cuts/v001/captions.srt' and final_checks['state'] == 'current'
           and line.startswith('v1 checked {0} approved {0} out of date'.format(chr(183)))
           and 'final deliver/final.mp4 checked {} 1 check pass'.format(chr(183)) in line, json.dumps(report)[:700])


def run_fix2_project_cases(tool, record, j, project, scripts_dir):
    """Preview and final acceptance stay attached to the file actually reviewed."""
    root = Path(j('fix2-preview'))
    folder = freshness_project(project, root)
    preview = folder / 'preview.mp4'
    original = preview.read_bytes()
    digest = project.file_sha256(preview)
    project.save_json(folder / 'manifest.json', {'version': 'v001', 'files': {'preview.mp4': digest}})
    project.record_review(root, 'v001', 'approved')
    preview.write_bytes(b'a changed preview of different size')
    code, output = tool('project.py', 'status', root, '--json')
    report = json.loads(output) if code == 0 else {}
    record('fix2-3: a changed rendered preview has no acceptance or approved status',
           code == 0 and report.get('acceptance', {}).get('preview') is None
           and (report.get('checks', {}).get('preview') or {}).get('approved') is None
           and 'preview changed since it was rendered' in report.get('line', '')
           and 'approved' not in report.get('line', ''), output[-900:])

    preview.write_bytes(original)
    checks = project.load_json(folder / 'checks.json')
    checks['inputs'][0] = project.input_row('preview', preview, 'cuts/v001/preview.mp4')
    spec = importlib.util.spec_from_file_location('lf_fix2_check', Path(scripts_dir) / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    checks['tools'] = check.tools_record()
    project.save_json(folder / 'checks.json', checks)
    stamp = preview.stat().st_mtime_ns
    preview.write_bytes(b'X' + original[1:])
    os.utime(preview, ns=(stamp, stamp))
    fast = project.checks_freshness(root, checks)[0]
    verify_code, verify_output = tool('check.py', '--verify', folder / 'checks.json')
    review_code, review_output = tool('project.py', 'review', root, 'approved')
    record('fix2-7a: fast status is metadata-based, verify hashes, and review hashes a changed preview',
           fast == 'current' and verify_code == 1 and 'content changed' in verify_output
           and review_code == 2 and 'preview changed' in review_output.lower(),
           f'fast {fast}; verify {verify_code} {verify_output[-200:]}; review {review_code} {review_output[-200:]}')

    preview.write_bytes(original)
    final = root / 'deliver' / 'final.mp4'
    final.write_bytes(b'final content')
    final_hash = project.file_sha256(final)
    project.save_json(folder / 'checks-final.json', {
        'version': 1, 'final': True, 'file': 'deliver/final.mp4', 'sha256': final_hash,
        'items': [{'id': 'spec', 'state': 'pass'}], 'summary': {'pass': 1},
        'inputs_base': 'project', 'inputs': [project.input_row('final', final, 'deliver/final.mp4')],
        'tools': checks['tools']})
    project.record_review(root, 'v001', 'approved', final)
    stamp = final.stat().st_mtime_ns
    final.write_bytes(b'Final content')
    os.utime(final, ns=(stamp, stamp))
    report = project.status_report(root)
    record('fix2-7b: final acceptance rehashes even when size and modification time are preserved',
           report['checks']['final']['state'] == 'current' and report['acceptance']['final'] is None
           and 'final deliver/final.mp4 checked {} approved'.format(chr(183)) not in report['line'],
           json.dumps(report, ensure_ascii=True)[-900:])


def run_fix2_tool_freshness_case(record, j, scripts_dir):
    """A changed script must expire status as well as --verify, using private copies of the two scripts."""
    tools = Path(j('fix2-tool-copy'))
    tools.mkdir(parents=True, exist_ok=True)
    for name in ('project.py', 'check.py'):
        shutil.copyfile(Path(scripts_dir) / name, tools / name)
    spec = importlib.util.spec_from_file_location('lf_fix2_tool_project', tools / 'project.py')
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    spec = importlib.util.spec_from_file_location('lf_fix2_tool_check', tools / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    root = Path(j('fix2-tool-project'))
    folder = freshness_project(project, root)
    checks = project.load_json(folder / 'checks.json')
    checks.pop('tools', None)
    project.save_json(folder / 'checks.json', checks)
    missing = project.checks_freshness(root, checks)
    record('fix2: a check without recorded tools is not current in project status',
           missing[0] != 'current' and 'tools' in project.status_line(root).lower(), str(missing))
    checks['tools'] = check.tools_record()
    project.save_json(folder / 'checks.json', checks)
    before = project.checks_freshness(root, checks)
    with (tools / 'check.py').open('a', encoding='utf-8') as stream:
        stream.write('\n# Changed synthetic tool\n')
    after = project.checks_freshness(root, checks)
    record('fix2: changing a recorded script expires project check status',
           before[0] == 'current' and after[0] == 'out_of_date'
           and any('check.py' in str(row.get('path')) for row in after[1]), str((before, after)))
