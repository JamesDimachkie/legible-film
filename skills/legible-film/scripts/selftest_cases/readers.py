"""Every cue reader goes through cue_list.py (SPEC §9 "Readers by test"): a grep finds the readers, each reader
refuses a stale list, an unbound plan and an unknown version, and the rational-rate and silence-span example passes
through every reader. A rendered paper version carries edit-cues.json v2 and its manifest identity."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PATTERN = re.compile(r'cues\.json|edit-cues\.json|read_cues|--cues')
IMPORTS = re.compile(r'''import\s+cue_list|['"]cue_list(?:\.py)?['"]''')
# A module that names a cue list without loading one through cue_list.py, with the reason it may.
ALLOWED = {
    'cue_list.py': 'the loader itself',
    'grade.py': 'its read_cues reads caption cues (captions.json), not a timing cue list',
    'film_capture.mjs': 'a writer, not a reader: Node cannot import cue_list.py, so it takes the page fingerprint, '
                        'source_files and the snapshot from cue_list.py freeze and never loads a list',
    'selftest_cases/captions.py': 'fixture writer', 'selftest_cases/chain.py': 'fixture writer',
    'selftest_cases/cues.py': 'fixture writer', 'selftest_cases/dialogue.py': 'fixture writer',
    'selftest_cases/dialogue_baseline.txt': 'expected output text of the dialogue cases, not code',
    'selftest_cases/footage.py': 'fixture writer', 'selftest_cases/library.py': 'fixture writer',
    'selftest_cases/make.py': 'fixture writer', 'selftest_cases/outputs.py': 'fixture writer',
    'selftest_cases/reviewfix.py': 'fixture writer', 'selftest_cases/sound.py': 'fixture writer',
    'selftest_cases/tracefix.py': 'fixture writer',
}
READERS = ('assemble.py', 'cue_onsets.py', 'cut.py', 'film_check.py', 'make_film.py', 'mix_cues.py', 'selftest.py',
           'sound_check.py', 'sound_library.py', 'spot_cues.py')


def load_cue_list(scripts_dir):
    spec = importlib.util.spec_from_file_location('selftest_readers_cue_list', Path(scripts_dir) / 'cue_list.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, indent=1) + '\n').encode('utf-8'))
    return path


def ffmpeg(*args):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y', *map(str, args)],
                       capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(r.stderr[-300:])


def run_readers_cases(tool, record, j, scripts_dir, skip=None):
    scripts = Path(scripts_dir)
    cl = load_cue_list(scripts)
    grep_case(record, scripts)
    root = Path(j('readers-cases'))
    root.mkdir(parents=True, exist_ok=True)
    example_cases(tool, record, cl, root)
    paper_render_case(tool, record, cl, root)


def grep_case(record, scripts):
    hits, unloaded = {}, []
    for path in sorted(scripts.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or 'testpages' in path.parts:
            continue
        if path.suffix not in ('.py', '.mjs', '.js', '.txt'):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        if not PATTERN.search(text):
            continue
        rel = path.relative_to(scripts).as_posix()
        hits[rel] = bool(IMPORTS.search(text))
        if not hits[rel] and rel not in ALLOWED:
            unloaded.append(rel)
    missing = [name for name in READERS if not hits.get(name)]
    record('readers: every script that names a cue list loads it through cue_list.py or is allowlisted with a reason',
           not unloaded and not missing, f'not through cue_list: {unloaded}; readers without it: {missing}; '
           f'{len(hits)} files hit')


def example(owner_rel, picture):
    """SPEC §6's example list (roles from the synthesised kit), bound to `picture`."""
    return {'version': 'v2', 'clock': 'seconds from the first frame of the film', 'fps': '24000/1001',
            'exported_from': 'selftest readers case', 'picture': dict(picture, path=owner_rel),
            'sections': [{'id': 'open', 'a': 0.0, 'b': 1.0, 'clock': 'speech', 'label': 'what this is'},
                         {'id': 'drop', 'a': 1.0, 'b': 3.0, 'clock': 'music', 'gain_db': {'effects': 0}},
                         {'id': 'hold', 'a': 3.0, 'b': 3.6, 'clock': 'silence'}],
            'events': [
                {'id': 'drop-in', 't': 1.0, 'scale': 'turn', 'sync': 'attack', 'lead_ms': -83, 'section': 'drop',
                 'sound': 'required', 'role': 'impact', 'hero': True, 'decision': 'the hit leads the cut by two frames',
                 'picture': 'cut from black to the wordmark', 'x': 0.0, 'y': -0.2, 'pan': 'x', 'pitch_st': 0,
                 'gain_db': 0, 'tolerance_ms': 17},
                {'id': 'type-run', 't': 1.5, 't_end': 2.4, 'scale': 'follow', 'section': 'drop', 'role': 'key',
                 'run': True, 'intent': 'key density follows the typing', 'picture': 'the line types itself'},
                {'id': 'tap-3', 't': 2.6, 'scale': 'contact', 'sync': 'apex', 'sound': 'optional', 'role': 'tap',
                 'span': 'type-run'},
                {'id': 'breath', 't': 3.0, 't_end': 3.6, 'scale': 'silence', 'sound': 'silent', 'scope': 'new',
                 'decision': 'the ending breathes'}]}


def example_cases(tool, record, cl, root):
    page = root / 'page'
    page.mkdir()
    (page / 'index.html').write_bytes(b'<!doctype html><title>readers</title>\n')
    found = cl.freeze(page)
    picture = {'kind': 'page', 'sha256': found['fingerprint'], 'snapshot_sha256': found['snapshot_sha256'],
               'source_files': found['source_files']}
    good = write(root / 'cues.json', example('page', picture))
    stale = write(root / 'stale' / 'cues.json', example('../page', dict(picture, source_files={'index.html': '0' * 64})))
    plan = write(root / 'plan' / 'cues.json', dict(example('.', {}), picture={'kind': 'plan', 'sha256': None}))
    future = write(root / 'future' / 'cues.json', dict(example('../page', picture), version='v3'))
    record('readers: the example list is fresh against its page', cl.check(good).state == 'fresh',
           cl.check(good).message)
    kit = root / 'kit'
    code, output = tool('make_sound_kit.py', '--out', kit, '--seed', 7, '--roles', 'impact', 'key', 'tap')
    palette = kit / 'palette.json'
    if code or not palette.is_file():
        record('readers: the synthesised palette for the reader cases was made', False, output[-300:])
        return
    audio = root / 'master.wav'
    ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=220:duration=4:sample_rate=48000', '-c:a', 'pcm_s16le', audio)
    code, output = tool('sound_library.py', 'index', kit, '--out', root / 'library.json')
    library_ok = code == 0

    def readers(cues, label):
        """Run each reader on one list: {reader: (exit code, output)}."""
        out = root / f'out-{label}'
        out.mkdir(exist_ok=True)
        results = {'spot_cues.py': tool('spot_cues.py', cues, '--out-dir', out / 'spot'),
                   'mix_cues.py': tool('mix_cues.py', cues, palette, '--out-dir', out / 'mix', '--duration', 4),
                   'cue_onsets.py': tool('cue_onsets.py', audio, cues, '--json', out / 'onsets.json'),
                   'sound_check.py': tool('sound_check.py', audio, '--cues', cues, '--palette', palette,
                                          '--json', out / 'sound.json')}
        if library_ok:
            results['sound_library.py'] = tool('sound_library.py', 'pick', cues, root / 'library.json', '--out',
                                               out / 'picked.json', '--allow-unlicensed', '--takes', 1)
        return results

    passed = readers(good, 'good')
    record('readers: the rational-rate and silence-span example passes through every reader',
           all(code in (0, 1) for code, _ in passed.values()) and len(passed) == 5,
           '; '.join(f'{name} {code}: {output.strip()[-160:]}' for name, (code, output) in passed.items()
                     if code not in (0, 1)) or ', '.join(passed))
    for label, cues, needle in (('stale', stale, 'stale'), ('plan', plan, 'unbound plan'),
                                ('future', future, 'unknown cue list version')):
        results = readers(cues, label)
        wrong = {name: (code, output.strip()[-160:]) for name, (code, output) in results.items()
                 if code != 2 or needle not in output}
        record(f'readers: every reader refuses {"a wrong hash (stale)" if label == "stale" else "an unbound plan" if label == "plan" else "version v3"}',
               not wrong and len(results) == 5, str(wrong)[:500])


def paper_render_case(tool, record, cl, root):
    """A rendered paper version: edit-cues.json v2 with the paper fingerprint, manifest identity, and custody."""
    work = root / 'paper'
    work.mkdir()
    video, srt, project = work / 'source.mp4', work / 'source.srt', work / 'project'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=15:duration=2', '-f', 'lavfi', '-i',
           'sine=frequency=440:duration=2:sample_rate=48000', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
           '-shortest', video)
    srt.write_text('1\n00:00:00,300 --> 00:00:01,300\nHello world\n', encoding='utf-8')
    steps = [tool('map.py', 'add', project, video, '--role', 'interview'),
             tool('map.py', 'run', project, '--alias', 'int_01', '--words', 'import:' + str(srt))]
    (project / 'film.md').write_text('---\ntitle: Readers\nsize: 320x180\nfps: 15\ncaptions: srt\n---\n'
                                     '> int_01 0:00.20-0:01.60 Hello world\n', encoding='utf-8')
    steps.append(tool('cut.py', 'render', project))
    version = project / 'cuts' / 'v001'
    if any(code not in (0, 1) for code, _ in steps) or not (version / 'manifest.json').is_file():
        record('readers: a paper version renders for the identity case', False,
               ' | '.join(output.strip()[-200:] for _, output in steps))
        return
    listed = version / 'edit-cues.json'
    doc = json.loads(listed.read_text(encoding='utf-8'))
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
    identity = manifest.get('identity') or {}
    state = cl.check(listed).state
    record('readers: cut.py render writes edit-cues.json v2 with the paper fingerprint, fresh against its version',
           doc.get('version') == 'v2' and doc['picture']['kind'] == 'paper'
           and doc['picture']['film_md_sha256'] == manifest['film_md_sha256']
           and doc['picture']['sources'] == manifest['sources'] and state == 'fresh'
           and cl.check(listed, version).state == 'fresh', f"{doc.get('version')} {state}")
    timing = identity.get('picture_timing') or {}
    schedule = cl.read_schedule(version / 'picture-timing.json', timing.get('pts_sha256'))
    found = cl.picture_identity(version / 'preview.mp4')
    record('readers: the version manifest carries the identity block (paper source, picture packet hash and schedule, '
           'cue hash, binding receipt)', identity.get('binding') == 'receipt'
           and identity.get('source', {}).get('kind') == 'paper'
           and identity.get('picture_sha256') == found['sha256'] and schedule is not None
           and not cl.compare_schedules(schedule, found['schedule'])
           and identity.get('cues_sha256') == cl.sha256_file(listed) and 'picture-timing.json' in manifest['files']
           and doc.get('provenance') == 'exported' and identity.get('cues_provenance') == 'exported',
           json.dumps(identity)[:300])
    code, output = tool('spot_cues.py', listed, '--out-dir', work / 'spotted')
    record('readers: a rendered version\'s edit-cues.json reads through a cue reader', code == 0, output[-200:])
    code, output = tool('check.py', project, '--no-speech')
    qa = sorted(p.name for p in (version / 'qa').glob('*')) if (version / 'qa').is_dir() else []
    record('custody: check.py on a version writes its QA files into the version and records them',
           code in (0, 1) and qa and (version / 'checks.json').is_file(), f'exit {code}; {qa[:4]}; {output[-200:]}')
