"""cue_list.py: the loader's states, the page, picture and paper identities, file_digest and freeze (SPEC §6, §9
"Loader and fingerprint"). Synthetic fixtures only; the page fixture is scripts/testpages/identity/, kept byte-exact
in Git (.gitattributes -text) so a Windows and a Linux checkout give the same fingerprint."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

V1_TEMPLATE = {   # assets/templates/cues.json as 2.0.0 shipped it
    "clock": "seconds from the first frame of the film", "fps": 60, "version": "v1",
    "exported_from": "the timing source the picture code reads",
    "fields": "t: seconds; sound: required, silent or optional; sync: attack or apex; tolerance_ms: largest offset "
              "still on cue; window_ms: how far either side of t to check (t 6.0 with window_ms 800 checks 5.2-6.8 s)",
    "events": [
        {"id": "send-contact", "t": 3.0, "picture": "the send button is pressed", "sound": "required",
         "sync": "attack", "tolerance_ms": 17},
        {"id": "whip-to-result", "t": 5.2, "picture": "camera whip at its peak velocity", "sound": "required",
         "sync": "apex", "tolerance_ms": 25},
        {"id": "result-read", "t": 6.0, "picture": "the result is read", "sound": "silent", "window_ms": 800},
        {"id": "logo-lock", "t": 9.5, "picture": "the mark locks", "sound": "optional", "sync": "attack"}]}


def load_cue_list(scripts_dir):
    spec = importlib.util.spec_from_file_location('selftest_cue_list', Path(scripts_dir) / 'cue_list.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, indent=1) + '\n').encode('utf-8'))
    return path


def crlf_copy(source, target):
    """A copy whose text files have CRLF line endings, as a Windows checkout without -text could make them."""
    shutil.copytree(source, target)
    for path in Path(target).rglob('*'):
        if path.is_file() and path.suffix in ('.html', '.css', '.js', '.svg', '.json'):
            path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))


def outcome(cl, function, *args, **kwargs):
    """(state or 'error', message) for a check or load call."""
    try:
        listed = function(*args, **kwargs)
        return listed.state, listed.message
    except cl.CueListError as error:
        return 'error', str(error)


def ffmpeg(*args):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y', *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr[-300:]


def run_identity_cases(tool, record, j, scripts_dir, skip=None):
    cl = load_cue_list(scripts_dir)
    root = Path(j('identity-cases'))
    root.mkdir(parents=True, exist_ok=True)
    loader_cases(cl, record, root)
    page_cases(cl, record, root, Path(scripts_dir))
    freeze_cases(cl, record, root, Path(scripts_dir))
    freeze_fix_cases(cl, tool, record, root, Path(scripts_dir), skip)
    video_cases(cl, record, root, skip)
    paper_cases(cl, record, root)
    code, output = tool('cue_list.py', Path(scripts_dir) / 'testpages' / 'identity' / 'cues.json', '--json')
    record('cue_list: the CLI reports the fixture list fresh and exits 0',
           code == 0 and '"state": "fresh"' in output, output[-200:])


def loader_cases(cl, record, root):
    template = write(root / 'v1-template.json', V1_TEMPLATE)
    listed = cl.check(template)
    record('cue_list: the 2.0 v1 template reads as unversioned with its events and fps unchanged',
           listed.state == 'unversioned' and listed.events == V1_TEMPLATE['events'] and listed.fps == 60.0
           and listed.scale(listed.events[0]) == 'contact', listed.message)
    record('cue_list: a v1 silent cue\'s window_ms is a span either side of t; an audible cue keeps its window',
           listed.silence_span(V1_TEMPLATE['events'][2]) == (5.2, 6.8)
           and listed.onset_window_ms({'t': 1, 'window_ms': 300}, 120) == 300.0
           and listed.onset_window_ms(V1_TEMPLATE['events'][0], 120) == 120, str(listed.silence_span(V1_TEMPLATE['events'][2])))
    shapes = {'bare list': [{'id': 'a', 't': 1}], 'no version': {'events': [{'id': 'a', 'frame': 30}], 'fps': 30},
              'numeric 1': {'version': 1, 'events': []}}
    states = {name: cl.check(write(root / f'v1-{i}.json', data)).state for i, (name, data) in enumerate(shapes.items())}
    record('cue_list: every v1 shape (a bare list, no version, version 1) reads as unversioned',
           set(states.values()) == {'unversioned'}, str(states))
    bad = {'version v3': {'version': 'v3', 'events': []},
           'hashless v2 page': {'version': 'v2', 'picture': {'kind': 'page', 'path': '.'}, 'events': []},
           'v2 event without scale': {'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None},
                                      'events': [{'id': 'a', 't': 1}]},
           'v2 event with window_ms': {'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None},
                                       'events': [{'id': 'a', 't': 1, 'scale': 'contact', 'window_ms': 80}]},
           'v2 silence without t_end': {'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None},
                                        'events': [{'id': 'a', 't': 1, 'scale': 'silence'}]},
           'held without a decision': {'version': 'v2', 'picture': {'kind': 'plan', 'sha256': None},
                                       'events': [{'id': 'a', 't': 1, 'scale': 'contact', 'picture': 'held'}]}}
    results = {name: outcome(cl, cl.check, write(root / f'bad-{i}.json', data))
               for i, (name, data) in enumerate(bad.items())}
    record('cue_list: version v3, a hashless non-plan v2 and malformed v2 events are errors, never legacy',
           all(state == 'error' for state, _ in results.values()) and 'v3' in results['version v3'][1]
           and 'only an unbound plan' in results['hashless v2 page'][1], str(results)[:400])
    plan = write(root / 'plan.json', {'version': 'v2', 'fps': '24000/1001', 'picture': {'kind': 'plan', 'sha256': None},
                                      'sections': [{'id': 'a', 'a': 0, 'b': 2, 'clock': 'action'}],
                                      'events': [{'id': 'turn', 't': 1, 'scale': 'turn', 'section': 'a'}]})
    refused = outcome(cl, cl.load, plan)
    allowed = outcome(cl, cl.load, plan, allow_plan=True)
    record('cue_list: an unbound plan is refused by load() and accepted only with allow_plan (add-version)',
           cl.check(plan).state == 'unbound' and refused == ('error', cl.UNBOUND_MESSAGE)
           and allowed[0] == 'unbound', f'{refused} {allowed}')
    base = {'version': 'v2', 'events': [], 'picture': {'kind': 'picture', 'path': 'missing.mp4', 'sha256': 'a' * 64}}
    kinds = {name: outcome(cl, cl.check, write(root / f'provenance-{name}.json', dict(base, **extra)))
             for name, extra in (('absent', {}), ('observed', {'provenance': 'observed'}),
                                 ('plan-bound', {'provenance': 'plan-bound'}), ('unknown', {'provenance': 'guessed'}),
                                 ('plan on a picture', {'provenance': 'plan'}))}
    read = {name: cl.check(root / f'provenance-{name}.json').provenance for name in ('absent', 'observed', 'plan-bound')}
    record('cue_list: provenance is exported by default, observed or plan-bound when stated, plan for a plan list; an '
           'unknown value or a plan provenance on a picture is an error',
           read == {'absent': 'exported', 'observed': 'observed', 'plan-bound': 'plan-bound'}
           and cl.check(plan).provenance == 'plan' and kinds['unknown'][0] == 'error'
           and kinds['plan on a picture'][0] == 'error', f'{read} {kinds}'[:300])
    listed = cl.check(plan)
    ntsc = cl.parse_rate(29.97)
    record('cue_list: a rational fps reaches readers as a float with fps_exact; 29.97 means 30000/1001',
           abs(listed.fps - 24000 / 1001) < 1e-12 and listed.fps_exact == '24000/1001'
           and cl.rate_text(ntsc) == '30000/1001', f'{listed.fps} {listed.fps_exact} {ntsc}')
    unresolved = write(root / 'nowhere.json', {'version': 'v2', 'events': [],
                                               'picture': {'kind': 'picture', 'path': 'missing.mp4', 'sha256': 'a' * 64}})
    record('cue_list: a list whose owner cannot be resolved reads unverified (a look), and an explicit missing owner '
           'is an error', cl.check(unresolved).state == 'unverified'
           and outcome(cl, cl.check, unresolved, root / 'gone')[0] == 'error', cl.check(unresolved).message)
    rules = cl.IgnoreRules('drafts/\n*.psd\n!keep.psd\n/top.txt\nassets/**/raw\n')
    cases = {('drafts/a.html', False): True, ('x/drafts/b.js', False): True, ('a.psd', False): True,
             ('keep.psd', False): False, ('top.txt', False): True, ('sub/top.txt', False): False,
             ('assets/a/b/raw', True): True, ('index.html', False): False}
    wrong = [k for k, v in cases.items() if rules.ignored(*k) != v]
    record('cue_list: .hyperframesignore follows gitignore rules (folders, globs, negation, anchoring, **)',
           not wrong, str(wrong))


def page_cases(cl, record, root, scripts_dir):
    fixture = scripts_dir / 'testpages' / 'identity'
    committed = json.loads((fixture / 'cues.json').read_text(encoding='utf-8'))
    fingerprint = cl.page_fingerprint(fixture)
    record('cue_list: the page fixture\'s fingerprint equals its committed list on this system (Linux and Windows '
           'run the same check)', fingerprint == committed['picture']['sha256'],
           f"{fingerprint[:16]} vs {committed['picture']['sha256'][:16]}")
    record('cue_list: the committed fixture list is fresh against the page it names',
           cl.check(fixture / 'cues.json').state == 'fresh', cl.check(fixture / 'cues.json').message)
    crlf = root / 'identity-crlf'
    crlf_copy(fixture, crlf)
    text = fixture / 'index.html'
    record('cue_list: file_digest reads CRLF as LF in text files; exact bytes still differ',
           cl.file_digest(text) == cl.file_digest(crlf / 'index.html')
           and cl.sha256_file(text) != cl.sha256_file(crlf / 'index.html')
           and cl.file_digest(fixture / 'assets' / 'dot.png') == cl.sha256_file(fixture / 'assets' / 'dot.png'))
    record('cue_list: a CRLF copy of the page has the same fingerprint', cl.page_fingerprint(crlf) == fingerprint)
    state, message = outcome(cl, cl.check, fixture / 'cues.json', crlf)
    record('cue_list: the LF list is stale against the CRLF copy, with the line-endings message',
           state == 'stale' and message.startswith(cl.LINE_ENDINGS_MESSAGE), message)
    loaded = outcome(cl, cl.load, fixture / 'cues.json', crlf)
    record('cue_list: load() refuses that stale list', loaded[0] == 'error' and 'line endings' in loaded[1], loaded[1])
    # What an engine and the skill write beside a page must not change its identity.
    busy = root / 'identity-busy'
    shutil.copytree(fixture, busy)
    writes = {'.hyperframes/artifacts/snapshots/frame-0001.png': b'png', '.hyperframes/history.json': b'{}',
              'snapshots/frame.png': b'x', 'renders/identity_2026-11-01_17-40-00.mp4': b'\x00' * 64,
              'audio/graph.json': b'{}', 'audio/mix/mix.wav': b'RIFF', 'qa/checks.json': b'{}', '.DS_Store': b'x',
              '.visual.js': b'x', '.hf-tmp/a': b'x', 'node_modules/gsap/index.js': b'x', 'dist/a.js': b'x',
              'coverage/a': b'x', 'drafts/old.html': b'<p>', 'art.psd': b'8BPS', 'captions.srt': b'1',
              'palette.json': b'{}', 'reading.json': b'{}', 'sound-edits.json': b'{}'}
    for rel, data in writes.items():
        (busy / rel).parent.mkdir(parents=True, exist_ok=True)
        (busy / rel).write_bytes(data)
    cl.freeze(busy)
    state, message = outcome(cl, cl.check, fixture / 'cues.json', busy)
    record('cue_list: the list stays fresh after engine snapshots, a default-output render, writes under audio/ and '
           'qa/, a freeze, ignored files and dot entries', state == 'fresh', message)
    (busy / 'extra.js').write_text('// added\n', encoding='utf-8')
    added = outcome(cl, cl.check, fixture / 'cues.json', busy)
    (busy / 'extra.js').unlink()
    (busy / 'style.css').unlink()
    removed = outcome(cl, cl.check, fixture / 'cues.json', busy)
    record('cue_list: an added or a removed unexcluded file makes the list stale, naming the file',
           added[0] == 'stale' and 'extra.js' in added[1] and removed[0] == 'stale' and 'style.css' in removed[1],
           f'{added[1][:120]} | {removed[1][:120]}')


def freeze_cases(cl, record, root, scripts_dir):
    fixture = scripts_dir / 'testpages' / 'identity'
    page = root / 'freeze-page'
    shutil.copytree(fixture, page)
    (page / 'audio').mkdir()
    (page / 'audio' / 'graph.json').write_text('{}', encoding='utf-8')
    (page / '.visual.js').write_text('//', encoding='utf-8')
    before = cl.page_fingerprint(page)
    first = cl.freeze(page)
    second = cl.freeze(page)
    copy = page / first['copy']
    record('cue_list: freeze keeps one copy per snapshot, the same page freezing to the same snapshot, and leaves the '
           'live fingerprint unchanged', first['snapshot_sha256'] == second['snapshot_sha256'] and copy.is_dir()
           and cl.page_fingerprint(page) == before == first['fingerprint'], first['snapshot_sha256'][:16])
    held = sorted(p.relative_to(copy).as_posix() for p in copy.rglob('*') if p.is_file())
    record('cue_list: the frozen copy holds only the fingerprinted files (no audio/graph.json, no .visual.js) and its '
           'record', held == sorted(first['source_files']) + [cl.FROZEN_RECORD] or
           sorted(held) == sorted(list(first['source_files']) + [cl.FROZEN_RECORD]), str(held))
    record('cue_list: the kept copy verifies against frozen_files and snapshot_sha256',
           not cl.verify_frozen(copy, first['frozen_files'], first['snapshot_sha256'])
           and cl.snapshot_hash(first['frozen_files']) == first['snapshot_sha256'])
    target = copy / 'style.css'
    original = target.read_bytes()
    target.write_bytes(original.replace(b'\n', b'\r\n'))
    crlf_only = cl.verify_frozen(copy, first['frozen_files'], first['snapshot_sha256'])
    target.write_bytes(original + b'/* changed */')
    changed = cl.verify_frozen(copy, first['frozen_files'], first['snapshot_sha256'])
    target.write_bytes(original)
    record('cue_list: a changed byte in the kept copy, and a change to its line endings alone, are both caught',
           crlf_only == ['changed since export: style.css'] and changed == ['changed since export: style.css'],
           f'{crlf_only} {changed}')
    twin = root / 'freeze-twin'
    crlf_copy(fixture, twin)
    other = cl.freeze(twin)
    record('cue_list: two copies differing only in line endings share a fingerprint and get two snapshots',
           other['fingerprint'] == first['fingerprint'] and other['snapshot_sha256'] != first['snapshot_sha256'])
    # Network and outside references: a pinned URL is vendored and hashed; gsap@3 and ../ make the binding unverified.
    net = root / 'freeze-net' / 'page'
    net.mkdir(parents=True)
    pinned = 'https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js'
    (net / 'index.html').write_text(f'<!doctype html><script src="{pinned}"></script>\n'
                                    '<a href="https://example.com/about">about</a>\n', encoding='utf-8')
    fetched = []

    def fetch(url):
        fetched.append(url)
        return b'/* gsap 3.14.2 stand-in */\n'

    record_pinned = cl.freeze(net, fetch=fetch)
    frozen_html = (net / record_pinned['copy'] / 'index.html').read_text(encoding='utf-8')
    vendored = record_pinned['vendored'][0] if record_pinned['vendored'] else {}
    record('cue_list: a pinned URL is fetched once, kept at a fixed local path, rewritten in the copy, hashed into '
           'the fingerprint; a followed link is not a load', fetched == [pinned] and vendored.get('url') == pinned
           and vendored.get('path', '?') in frozen_html and pinned not in frozen_html
           and record_pinned['binding'] == 'closed'
           and record_pinned['fingerprint'] == cl.page_fingerprint(net, {pinned: vendored.get('sha256')})
           and record_pinned['fingerprint'] != cl.page_fingerprint(net), str(record_pinned['reasons']))
    loose = root / 'freeze-loose' / 'page'
    loose.mkdir(parents=True)
    (loose.parent / 'shared.js').write_text('// shared\n', encoding='utf-8')
    (loose / 'index.html').write_text('<!doctype html><script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.js">'
                                      '</script><script src="../shared.js"></script>\n', encoding='utf-8')
    record_loose = cl.freeze(loose, fetch=fetch)
    copied = loose / record_loose['copy']
    html = (copied / 'index.html').read_text(encoding='utf-8')
    record('cue_list: gsap@3 (unpinned) and ../shared.js bind unverified; the outside file is copied under _outside/ '
           'and the reference rewritten', record_loose['binding'] == 'unverified' and record_loose['unpinned']
           and (copied / '_outside' / '_up' / 'shared.js').is_file() and '../shared.js' not in html
           and '_outside/_up/shared.js' in html, str(record_loose['reasons']))


def load_browser(scripts_dir):
    spec = importlib.util.spec_from_file_location('selftest_identity_browser',
                                                  Path(scripts_dir) / 'selftest_cases' / '_browser.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def freeze_fix_cases(cl, tool, record, root, scripts_dir, skip):
    """BUILD-DECISIONS rows 27, 28, 29 and 31: in-page ../ references, pre-rewrite digests, engine writes in the copy,
    and reference positions."""
    # Row 27: the kit's blocks/*.js import ../lf/*.js, which stays inside the page; it is kept in place.
    film = root / 'kit-film'
    code, output = tool('new_film.py', film)
    if code not in (0, 1) or not (film / 'film.js').is_file():
        record('cue_list: a kit film for the freeze cases was made', False, output[-200:])
        return
    kit = cl.freeze(film)
    copy = film / kit['copy']
    outside = sorted(p.relative_to(copy).as_posix() for p in copy.rglob('*') if '_outside' in p.parts)
    blocks = sorted((film / 'blocks').glob('*.js'))
    unchanged = all((copy / 'blocks' / b.name).read_bytes() == b.read_bytes() for b in blocks)
    record('cue_list: freeze keeps a kit film\'s in-page ../ imports (blocks/ to ../lf/) in place: nothing under '
           '_outside/, the modules byte for byte, the binding closed',
           not outside and blocks and unchanged and kit['binding'] == 'closed' and not kit['outside'],
           f"{outside[:3]} {kit['reasons']}")
    found = load_browser(scripts_dir).discover()
    if found['missing']:
        reason = 'film_check.py on the frozen copy needs ' + found['missing']
        if skip:
            skip('cue_list: the frozen kit copy loads and checks in Chromium', reason)
        else:
            print(f'SKIP  cue_list: the frozen kit copy loads and checks in Chromium ({reason})')
    else:
        checked = root / 'kit-film-frozen-check'
        shutil.copytree(copy, checked)
        code, output = tool('film_check.py', checked, '--size', '240x240', '--playwright', found['module'],
                            '--browser', found['chrome'])
        record('cue_list: the frozen kit copy loads and checks in Chromium (its modules resolve inside the copy)',
               code in (0, 1) and (checked / 'cues.json').is_file(), f'exit {code}: {output.strip()[-300:]}')
    excluded = root / 'excluded-ref'
    (excluded / 'sub').mkdir(parents=True)
    (excluded / 'audio').mkdir()
    (excluded / 'audio' / 'tone.js').write_bytes(b'// excluded\n')
    (excluded / 'sub' / 'main.js').write_bytes(b"import '../audio/tone.js';\n")
    (excluded / 'index.html').write_bytes(b'<!doctype html><script type="module" src="sub/main.js"></script>\n')
    held_out = cl.freeze(excluded)
    record('cue_list: a ../ reference to a file inside the page that the identity excludes binds unverified and is '
           'never copied under _outside/', held_out['binding'] == 'unverified' and not held_out['outside']
           and any('excludes' in reason for reason in held_out['reasons']), str(held_out['reasons']))
    # Row 28: each file's pre-rewrite file_digest is in the record, and rebuilds the fingerprint without the page.
    digests = kit.get('source_digests') or {}
    record('cue_list: the freeze record holds each file\'s pre-rewrite file_digest, and they rebuild the fingerprint',
           digests == {rel: cl.file_digest(film / rel) for rel in kit['source_files']}
           and cl.fingerprint_from_digests(digests) == kit['fingerprint'], f'{len(digests)} digests')
    twin = root / 'kit-film-crlf'
    crlf_copy(film, twin)
    shutil.rmtree(twin / cl.FROZEN_DIR, ignore_errors=True)
    twin_record = cl.freeze(twin)
    record('cue_list: a CRLF copy\'s recorded digests equal the LF page\'s and rebuild the same fingerprint',
           twin_record.get('source_digests') == digests and twin_record['fingerprint'] == kit['fingerprint']
           and twin_record['snapshot_sha256'] != kit['snapshot_sha256'])
    # Row 29: an engine writes .hyperframes/ into the project it renders; the copy still verifies.
    engine = root / 'engine-copy'
    shutil.copytree(copy, engine)
    (engine / '.hyperframes' / 'artifacts').mkdir(parents=True)
    (engine / '.hyperframes' / 'history.json').write_bytes(b'{}')
    (engine / '.hf-tmp').mkdir()
    (engine / '.hf-tmp' / 'frame.png').write_bytes(b'x')
    clean = cl.verify_frozen(engine, kit['frozen_files'], kit['snapshot_sha256'])
    (engine / 'extra.js').write_bytes(b'// added\n')
    added = cl.verify_frozen(engine, kit['frozen_files'], kit['snapshot_sha256'])
    record('cue_list: verify_frozen skips top-level dot entries an engine writes (.hyperframes/) and its own record, '
           'and still catches an added file', clean == [] and added == ['not in the snapshot: extra.js'],
           f'{clean} {added}')
    # Row 31: only reference positions count; a URL in a data string is not a reference.
    data = root / 'data-urls'
    data.mkdir()
    (data / 'index.html').write_bytes(b'<!doctype html><p data-href="https://example.com/p">x</p>'
                                      b'<script src="app.js"></script>\n')
    (data / 'app.js').write_bytes(b'const sources = ["https://example.com/a.json", \'https://cdn.example.org/x.png\'];\n'
                                  b'const link = `see https://example.net/docs`;\n')
    (data / 'facts.json').write_bytes(b'{"site": "https://example.com", "logo": "https://example.com/logo.svg"}\n')
    plain = cl.freeze(data, fetch=lambda url: b'')
    record('cue_list: URLs in data strings (a JS array, a template string, a JSON file, a data- attribute) are not '
           'references, so the page binds closed', plain['binding'] == 'closed' and not plain['unpinned'],
           str(plain['reasons']))
    loads = root / 'reference-urls'
    loads.mkdir()
    (loads / 'index.html').write_bytes(
        b'<!doctype html><link rel="stylesheet" href="style.css">'
        b'<img srcset="https://a.example/1.png 1x, https://a.example/2.png 2x" src="local.png">'
        b'<video poster="https://a.example/p.jpg"></video>'
        b'<style>.x{background:url("https://a.example/inline.png")}</style>'
        b'<script type="module" src="main.js"></script>\n')
    (loads / 'style.css').write_bytes(b'@import "https://fonts.example/x.css";\n.b{background:url(https://a.example/bg.png)}\n')
    (loads / 'main.js').write_bytes(b"import x from 'https://esm.example/m.js';\n"
                                    b'export { y } from "https://esm.example/n.js";\n'
                                    b"const later = () => import('https://esm.example/dyn.js');\n")
    (loads / 'local.png').write_bytes(b'png')
    positions = cl.freeze(loads, fetch=lambda url: b'')
    wanted = {'https://a.example/1.png', 'https://a.example/2.png', 'https://a.example/p.jpg',
              'https://a.example/inline.png', 'https://fonts.example/x.css', 'https://a.example/bg.png',
              'https://esm.example/m.js', 'https://esm.example/n.js', 'https://esm.example/dyn.js'}
    record('cue_list: URLs in reference positions are found: srcset, poster, CSS url() and @import, JS import, '
           'export ... from and dynamic import()', set(positions['unpinned']) == wanted
           and positions['binding'] == 'unverified', str(sorted(set(positions['unpinned']) ^ wanted)))


def make_video(path):
    return ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24000/1001:duration=2', '-f', 'lavfi', '-i',
                  'sine=frequency=440:duration=2', '-c:v', 'libx264', '-bf', '2', '-g', '12', '-pix_fmt', 'yuv420p',
                  '-c:a', 'aac', '-shortest', path)


def picture_list(cl, folder, video, name='cues.json'):
    """A v2 list bound to a video, its schedule kept beside it as picture-timing.json."""
    found = cl.fingerprint('picture', video)
    timing = found['timing']
    if found['schedule'] is not None:
        cl.write_schedule(found['schedule'], folder / 'picture-timing.json')
    return write(folder / name, {'version': 'v2', 'fps': found['timing'].get('fps_exact', 24),
                                 'picture': {'kind': 'picture', 'path': Path(video).name, 'sha256': found['sha256'],
                                             'geometry': found['geometry'], 'timing': timing},
                                 'sections': [], 'events': [{'id': 'a', 't': 0.5, 'scale': 'contact'}]})


def video_cases(cl, record, root, skip):
    folder = root / 'video'
    folder.mkdir()
    master = folder / 'master.mp4'
    ok, err = make_video(master)
    if not ok:
        record('cue_list: video fixture made', False, err)
        return
    listed = picture_list(cl, folder, master)
    record('cue_list: a list bound to a video is fresh against it', cl.check(listed).state == 'fresh',
           cl.check(listed).message)
    remuxes = {}
    for ext in ('mov', 'mkv'):
        target = folder / f'remux.{ext}'
        ffmpeg('-i', master, '-c', 'copy', target)
        remuxes[ext] = outcome(cl, cl.check, listed, target)
    record('cue_list: remuxed MP4 to MOV and to MKV, the picture keeps its identity (MKV\'s millisecond times pass)',
           all(state == 'fresh' for state, _ in remuxes.values()), str(remuxes))
    ffmpeg('-itsoffset', '0.5', '-i', master, '-c', 'copy', folder / 'shifted.mkv')
    shifted = outcome(cl, cl.check, listed, folder / 'shifted.mkv')
    record('cue_list: a remux that shifts the whole picture by 0.5 s keeps its identity (the sync group reports a '
           'shift)', shifted[0] == 'fresh', shifted[1])
    ffmpeg('-itsscale', '2', '-i', master, '-c', 'copy', folder / 'scaled.mp4')
    scaled = outcome(cl, cl.check, listed, folder / 'scaled.mp4')
    record('cue_list: ffmpeg -itsscale 2 -c copy (same packets, new timing) is stale', scaled[0] == 'stale'
           and 'timing' in scaled[1], scaled[1])
    moved_ok, moved_err = ffmpeg('-i', master, '-c', 'copy', '-bsf:v', 'setts=pts=if(eq(N\\,10)\\,PTS+1001\\,PTS)',
                                 folder / 'moved.mkv')
    moved = outcome(cl, cl.check, listed, folder / 'moved.mkv') if moved_ok else ('error', moved_err)
    record('cue_list: one interior frame moved by a frame interval (setts) is stale', moved[0] == 'stale', moved[1])
    ffmpeg('-i', master, '-f', 'lavfi', '-i', 'sine=frequency=880:duration=2', '-map', '0:v', '-map', '1:a',
           '-c:v', 'copy', '-c:a', 'aac', '-shortest', folder / 'resound.mp4')
    resound = outcome(cl, cl.check, listed, folder / 'resound.mp4')
    record('cue_list: a new soundtrack leaves the picture fresh', resound[0] == 'fresh', resound[1])
    raw_folder = folder / 'raw'
    raw_folder.mkdir()
    ffmpeg('-i', master, '-c', 'copy', '-an', '-bsf:v', 'h264_mp4toannexb', raw_folder / 'raw.h264')
    raw = outcome(cl, cl.check, picture_list(cl, raw_folder, raw_folder / 'raw.h264'))
    record('cue_list: a stream without packet timestamps reads unverified (untimed)',
           raw[0] == 'unverified' and 'untimed' in raw[1], raw[1])
    flips = {}
    for name, options in (('hflip', ['-display_hflip']), ('hvflip', ['-display_hflip', '-display_vflip']),
                          ('rot180', ['-display_rotation', '180']), ('rot10', ['-display_rotation', '10'])):
        target = folder / f'{name}.mp4'
        made, _ = ffmpeg(*options, '-i', master, '-c', 'copy', target)
        flips[name] = target if made else None
    if not all(flips.values()):
        reason = 'this FFmpeg has no -display_rotation or -display_hflip (FFmpeg 6.0 or later)'
        if skip:
            skip('cue_list: display transforms (flip refused, flip pair equals a half turn, 10 degrees unverified)',
                 reason, 3)
        else:
            print(f'SKIP  cue_list: display transforms ({reason})')
        return
    hflip = outcome(cl, cl.check, listed, flips['hflip'])
    record('cue_list: a horizontally flipped remux is stale', hflip[0] == 'stale' and 'transform' in hflip[1], hflip[1])
    version = folder / 'cuts' / 'v001'
    version.mkdir(parents=True)
    found = cl.fingerprint('picture', master)
    cl.write_schedule(found['schedule'], version / 'picture-timing.json')

    def against_version(geometry):
        write(version / 'manifest.json', {'version': 'v001', 'identity': {
            'picture_sha256': found['sha256'], 'picture_timing': cl.timing_block(found['schedule']),
            'geometry': geometry}})
        return outcome(cl, cl.check, listed, version)
    same = against_version(found['geometry'])
    flipped = against_version(cl.fingerprint('picture', flips['hflip'])['geometry'])
    record('cue_list: against a version, the same packets and schedule are fresh and a flipped display is stale',
           same[0] == 'fresh' and flipped[0] == 'stale' and 'transform' in flipped[1], f'{same} | {flipped[1][:100]}')
    pair = cl.fingerprint('picture', flips['hvflip'])['geometry']
    half = cl.fingerprint('picture', flips['rot180'])['geometry']
    record('cue_list: a horizontal plus a vertical flip compares equal to a half turn',
           cl.geometry_compare(pair, half)[0] == 'equal' and pair['transform'] == {'rotate': 180, 'hflip': False},
           str(pair['transform']))
    tilted_folder = folder / 'tilted'
    tilted_folder.mkdir()
    shutil.copyfile(flips['rot10'], tilted_folder / 'rot10.mp4')
    tilted = outcome(cl, cl.check, picture_list(cl, tilted_folder, tilted_folder / 'rot10.mp4'))
    straight = outcome(cl, cl.check, listed, flips['rot10'])
    record('cue_list: a 10 degree display rotation is compared exactly: unverified against itself, stale against 0',
           tilted[0] == 'unverified' and straight[0] == 'stale', f'{tilted[1][:100]} | {straight[1][:100]}')


def paper_cases(cl, record, root):
    project = root / 'paper-project'
    version = project / 'cuts' / 'v001'
    version.mkdir(parents=True)
    sources = {'int_01': {'path': 'source.mp4', 'bytes': 10, 'sha256': 'b' * 64, 'video_stream': 0,
                          'audio_stream': 1, 'words_sha256': 'c' * 64}}
    write(version / 'manifest.json', {'version': 'v001', 'film_md_sha256': 'd' * 64, 'sources': sources})
    identity = dict(cl.paper_identity('d' * 64, sources), path='.')
    listed = write(version / 'edit-cues.json', {'version': 'v2', 'fps': 15, 'picture': identity, 'sections': [],
                                                'events': [{'id': 'join-1', 't': 1.0, 'scale': 'contact'}]})
    fresh = outcome(cl, cl.check, listed)
    with_owner = outcome(cl, cl.check, listed, version)
    write(version / 'manifest.json', {'version': 'v001', 'film_md_sha256': 'd' * 64,
                                      'sources': dict(sources, int_01=dict(sources['int_01'], sha256='e' * 64))})
    remapped = outcome(cl, cl.check, listed)
    record('cue_list: a paper list is fresh against its version (film.md and sources) and stale when a source was '
           're-mapped', fresh[0] == 'fresh' and with_owner[0] == 'fresh' and remapped[0] == 'stale',
           f'{fresh} {remapped[1][:80]}')
