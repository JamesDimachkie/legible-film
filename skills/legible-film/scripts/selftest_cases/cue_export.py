"""Cue export (SPEC §9): film_capture.mjs cues on testpages/labels/ (a HyperFrames project) and on pages made from it
here, and the kit's export through film_check.py. Needs Node, Playwright and Chromium (found as the kit finds them)
and, for the fixture's pinned GSAP, one fetch from jsDelivr by cue_list.py freeze; without them the area is a
counted skip. The HyperFrames check runs when hyperframes 0.8.209 is already in the npx cache (no download); it
leaves HyperFrames' own warm browser, which exits after five minutes."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parent / 'testpages' / 'labels'
HYPERFRAMES = 'hyperframes@0.8.209'


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def page_copy(dst, fps=None, html=None, block=None):
    """A copy of the labels fixture; fps replaces the root's data-fps; html and block edit index.html."""
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(FIXTURE, dst)
    index = dst / 'index.html'
    text = index.read_text(encoding='utf-8')
    if fps:
        text = text.replace('data-fps="24000/1001"', f'data-fps="{fps}"')
    for old, new in (html or {}).items():
        assert old in text, old
        text = text.replace(old, new)
    if block:
        start = text.index('<script type="application/json" id="lf-cues">') + len('<script type="application/json" id="lf-cues">')
        end = text.index('</script>', start)
        data = json.loads(text[start:end])
        block(data)
        text = text[:start] + '\n' + json.dumps(data, indent=1) + '\n' + text[end:]
    index.write_bytes(text.encode('utf-8'))
    return dst


LABELS = "  tl.set({}, {}, 8);\n  window.__timelines['main'] = tl;"


def add_label(name, seconds):
    return {LABELS: f"  tl.addLabel('{name}', F({seconds}));\n" + LABELS}


def run_cue_export_cases(tool, record, j, scripts_dir, skip=None):
    def skipped(name, reason, count):
        if skip:
            skip(name, reason, count)
        else:
            print(f'SKIP  {name} ({reason})' + (f' [{count} checks]' if count > 1 else ''))

    scripts = Path(scripts_dir)
    browser = _module('selftest_cue_export_browser', HERE / '_browser.py').discover()
    if browser['missing']:
        skipped('cue export', browser['missing'], 24)
        return
    cue_list = _module('selftest_cue_export_cue_list', scripts / 'cue_list.py')
    root = Path(j('cue-export-cases'))
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, LF_PYTHON=sys.executable, LF_PLAYWRIGHT_MODULE=str(browser['core']))

    def export(page, out=None, *extra):
        out = out or (Path(page) / 'cues.json')
        r = subprocess.run([browser['node'], str(scripts / 'film_capture.mjs'), 'cues', str(page), '--out', str(out),
                            '--browser', str(browser['chrome']), *map(str, extra)], capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=env, timeout=600)
        doc = json.loads(Path(out).read_text(encoding='utf-8')) if r.returncode in (0, 1) and Path(out).is_file() else None
        return r.returncode, (r.stdout + r.stderr).strip(), doc

    first = page_copy(root / 'labels-23976')
    code, text, doc = export(first, None, '--verify')
    if code == 2 and ('could not fetch' in text or 'gsap is not defined' in text or 'not vendored' in text):
        skipped('cue export', 'the fixture\'s pinned GSAP could not be fetched from jsDelivr: ' + text[-160:], 24)
        return
    events = {e['id']: e for e in (doc or {}).get('events', [])}
    sections = {s['id']: s for s in (doc or {}).get('sections', [])}

    def on_grid(doc, fps, expected):
        got = {e['id']: e for e in doc.get('events', [])}
        rows = []
        for name, seconds in expected.items():
            frame = round(seconds * fps)
            t = got.get(name.split(':')[0], {}).get('t_end' if name.endswith(':end') else 't')
            rows.append(t is not None and abs(t - frame / fps) < 1e-5 and round(t * fps) == frame)
        return all(rows), {k: got.get(k.split(':')[0], {}).get('t_end' if k.endswith(':end') else 't') for k in expected}

    grid = {'drop-in': 3, 'type-run': 4, 'type-run:end': 5.5, 'tap-3': 5, 'breath': 6, 'breath:end': 7.5}
    ok, seen = on_grid(doc or {}, 24000 / 1001, grid)
    record('cue export: labels exact to one frame at 24000/1001', code == 0 and ok and doc.get('fps') == '24000/1001',
           f'exit {code}; {seen}; {text[-200:]}')
    sixty = page_copy(root / 'labels-60', fps='60')
    code60, text60, doc60 = export(sixty)
    ok60, seen60 = on_grid(doc60 or {}, 60, grid)
    record('cue export: labels exact to one frame at 60', code60 == 0 and ok60 and doc60.get('fps') == 60,
           f'exit {code60}; {seen60}; {text60[-200:]}')
    turn = events.get('drop-in', {})
    record('cue export: a turn exports with its lead_ms, role and decision',
           turn.get('scale') == 'turn' and turn.get('lead_ms') == -83 and turn.get('role') == 'hit'
           and turn.get('decision') and turn.get('section') == 'drop' and -1 <= turn.get('x', 9) <= 1, str(turn))
    span = events.get('type-run', {})
    record('cue export: a follow span with both labels', span.get('scale') == 'follow' and span.get('t_end', 0) > span.get('t', 9)
           and span.get('run') is True and events.get('tap-3', {}).get('span') == 'type-run', str(span))
    record('cue export: section clocks', [sections.get(k, {}).get('clock') for k in ('open', 'drop', 'hold')] ==
           ['speech', 'music', 'silence'] and sections['hold'].get('decision'), str(sections))
    record('cue export: a nested composition with nonzero data-start exports at film time',
           abs(events.get('inner-pop', {}).get('t', 0) - 5.5) < 1e-6, str(events.get('inner-pop')))
    verify = ((doc or {}).get('export') or {}).get('verify') or {}
    record('cue export: --verify finds a frame change at every probed turn and contact',
           code == 0 and len(verify.get('probed', [])) == 3 and not verify.get('flagged'), str(verify)[:300])
    record('cue export: the pinned GSAP fixture is vendored and binds closed',
           (doc or {}).get('binding') == 'closed' and any('_vendor/' in r['path'] for r in doc['export']['requests'])
           and doc.get('provenance') == 'exported', str((doc or {}).get('binding_reasons')))
    state = cue_list.check(first / 'cues.json')
    record('cue export: the exported list reads fresh through cue_list', state.state == 'fresh', state.message)
    fps_before = cue_list.page_fingerprint(first)
    export(first)
    record('cue export: exporting leaves the live fingerprint unchanged (the kept copy sits in .lf-frozen/)',
           cue_list.page_fingerprint(first) == fps_before and (first / '.lf-frozen').is_dir(), fps_before[:12])
    (first / 'audio').mkdir(exist_ok=True)
    (first / 'audio' / 'graph.json').write_text('{}', encoding='utf-8')
    state = cue_list.check(first / 'cues.json')
    record('cue export: a write under audio/ leaves the list fresh', state.state == 'fresh', state.message)

    orphan = page_copy(root / 'orphan', html=add_label('cue:orphan', 2))
    code, text, _ = export(orphan)
    record('cue export: a label without an entry is exit 2 with its name', code == 2 and 'cue:orphan' in text, text[-200:])
    ghost = page_copy(root / 'ghost', block=lambda d: d['events'].update(ghost={'scale': 'contact', 'role': 'tap'}))
    code, text, _ = export(ghost)
    record('cue export: an entry without a label is exit 2 with its name', code == 2 and 'ghost' in text, text[-200:])
    nospan = page_copy(root / 'nospan', html={"  tl.addLabel('cue:type-run:end', F(5.5));\n": ''})
    code, text, _ = export(nospan)
    record('cue export: a span entry with no :end label is exit 2', code == 2 and 'type-run' in text, text[-200:])
    outside = page_copy(root / 'outside', html={"  tl.addLabel('section:open', 0);\n":
                                                 "  tl.addLabel('section:open', F(1));\n  tl.addLabel('cue:early', F(0.5));\n"},
                        block=lambda d: d['events'].update(early={'scale': 'contact', 'role': 'tap'}))
    code, text, _ = export(outside)
    record('cue export: a cue outside every section is exit 2 with its name',
           code == 2 and 'early' in text and 'outside every section' in text, text[-200:])

    still = {'scale': 'contact', 'role': 'tap'}
    planted = page_copy(root / 'still', html=add_label('cue:still-hit', 7.75),
                        block=lambda d: d['events'].update({'still-hit': dict(still)}))
    code, text, doc = export(planted, None, '--verify')
    flagged = [f['id'] for f in ((doc or {}).get('export') or {}).get('verify', {}).get('flagged', [])]
    record('cue export: a planted cue on a still frame is a look (exit 1)', code == 1 and flagged == ['still-hit'], text[-200:])
    held = page_copy(root / 'held', html=add_label('cue:still-hit', 7.75),
                     block=lambda d: d['events'].update({'still-hit': dict(still, picture='held',
                                                                           decision='the hit lands on the held card')}))
    code, text, doc = export(held, None, '--verify')
    listed = ((doc or {}).get('export') or {}).get('verify', {})
    record('cue export: the same cue declared held with a decision is listed, not flagged',
           code == 0 and [s['id'] for s in listed.get('skipped', [])] == ['still-hit'] and not listed.get('flagged'),
           text[-200:])
    bare = page_copy(root / 'held-bare', html=add_label('cue:still-hit', 7.75),
                     block=lambda d: d['events'].update({'still-hit': dict(still, picture='held')}))
    code, text, _ = export(bare, None, '--verify')
    record('cue export: held without a decision is exit 2', code == 2 and 'held' in text, text[-200:])

    loose = page_copy(root / 'gsap3', html={'gsap@3.14.2': 'gsap@3'})
    code, text, doc = export(loose)
    record('cue export: a page that loads gsap@3 exports as unverified',
           code == 0 and doc.get('binding') == 'unverified' and any('unpinned' in r for r in doc.get('binding_reasons', [])),
           text[-200:])
    runtime = page_copy(root / 'runtime-fetch', html={"window.__timelines = window.__timelines || {};\n(function () {":
        "window.__timelines = window.__timelines || {};\nfetch('https://' + 'example.com/lf-fixture.json').catch(() => {});\n(function () {"})
    code, text, doc = export(runtime)
    record('cue export: a page that fetches a URL from script at run time exports as unverified',
           code == 0 and doc.get('binding') == 'unverified' and any('left the copy' in r for r in doc.get('binding_reasons', [])),
           text[-200:])
    shared = root / 'shared-site'
    if shared.exists():
        shutil.rmtree(shared)
    shared.mkdir()
    (shared / 'shared.js').write_text('window.LF_SHARED_START = 0;\n', encoding='utf-8')
    up = page_copy(shared / 'page', html={'</head>': '<script src="../shared.js"></script>\n</head>',
                                          "tl.addLabel('section:open', 0);": "tl.addLabel('section:open', window.LF_SHARED_START);"})
    code, text, doc = export(up)
    record('cue export: a page that loads ../shared.js resolves it in the frozen copy and exports as unverified',
           code == 0 and doc.get('binding') == 'unverified' and any('outside reference' in r for r in doc.get('binding_reasons', []))
           and any(r['path'].startswith('/_outside/') and r['status'] == 200 for r in doc['export']['requests']),
           text[-200:])
    system = page_copy(root / 'system-font', html={'font-family: "Fixture Inter";': 'font-family: Arial, sans-serif;'})
    code, text, doc = export(system)
    record('cue export: text drawn in a system font exports as unverified',
           code == 0 and doc.get('binding') == 'unverified' and any('system font' in r for r in doc.get('binding_reasons', [])),
           text[-200:])

    # Closure covers what the render reads (BUILD-DECISIONS row 40): a file nothing loads is not scanned.
    readme = '<!doctype html><title>notes</title><script src="http://example.com/tracker.js"></script>\n' \
             '<link rel="stylesheet" href="http://example.com/theme.css">\n'
    beside = page_copy(root / 'unloaded-readme')
    (beside / 'notes').mkdir()
    (beside / 'notes' / 'README.html').write_text(readme, encoding='utf-8')
    code, text, doc = export(beside)
    unscanned = ((doc or {}).get('export') or {}).get('not_loaded_not_scanned', [])
    record('cue export: an unloaded HTML file with unpinned links beside a closed page binds closed, listed as not '
           'loaded, not scanned', code == 0 and doc.get('binding') == 'closed' and 'notes/README.html' in unscanned
           and 'notes/README.html' in doc['picture']['source_files'], str(doc.get('binding_reasons') if doc else text[-200:]))
    linked = page_copy(root / 'linked-readme', html={'</body>': '<iframe src="notes/README.html" hidden></iframe>\n</body>'})
    (linked / 'notes').mkdir()
    (linked / 'notes' / 'README.html').write_text(readme, encoding='utf-8')
    code, text, doc = export(linked)
    record('cue export: the same file linked from the page binds unverified',
           code == 0 and doc.get('binding') == 'unverified'
           and any('unpinned' in r and 'tracker.js' in r for r in doc.get('binding_reasons', [])), text[-300:])
    late = page_copy(root / 'runtime-loaded', html={"window.__timelines = window.__timelines || {};\n(function () {":
        "window.__timelines = window.__timelines || {};\n(function () { const s = document.createElement('script'); "
        "s.src = 'late/' + 'later.js'; document.head.appendChild(s); })();\n(function () {"})
    (late / 'late').mkdir()
    (late / 'late' / 'later.js').write_text('if (false) import("https://example.com/unpinned/later.js");\n', encoding='utf-8')
    code, text, doc = export(late)
    record('cue export: a file the page loads only at run time is scanned at export and its unpinned reference binds '
           'unverified', code == 0 and doc.get('binding') == 'unverified'
           and 'late/later.js' in doc['export']['scanned']['at_export']
           and any('loaded at run time' in r for r in doc.get('binding_reasons', [])), text[-300:])

    live = page_copy(root / 'live-edit')
    out = live / 'cues.json'
    proc = subprocess.Popen([browser['node'], str(scripts / 'film_capture.mjs'), 'cues', str(live), '--out', str(out),
                             '--browser', str(browser['chrome'])], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    deadline = time.time() + 120
    while time.time() < deadline and not any(p.is_dir() and not p.name.startswith('.tmp')
                                             for p in (live / '.lf-frozen').glob('*')):
        time.sleep(0.05)
    index = live / 'index.html'
    index.write_text(index.read_text(encoding='utf-8').replace("tl.addLabel('cue:drop-in', F(3));",
                                                               "tl.addLabel('cue:drop-in', F(3.5));"), encoding='utf-8')
    proc.communicate(timeout=300)
    doc = json.loads(out.read_text(encoding='utf-8')) if out.is_file() else {}
    t = next((e['t'] for e in doc.get('events', []) if e['id'] == 'drop-in'), None)
    state = cue_list.check(out) if out.is_file() else None
    record('cue export: an edit to the live page during export leaves the list as it was, and stale against the edit',
           proc.returncode == 0 and t is not None and abs(t - 3.003) < 1e-3 and state and state.state == 'stale',
           f'exit {proc.returncode}; drop-in {t}; {state.message if state else "no list"}')
    code, text, doc = export(page_copy(root / 'candidates'), root / 'candidates.json', '--candidates')
    peaks = [c['t'] for c in ((doc or {}).get('export') or {}).get('candidates', [])]
    scan = ((doc or {}).get('export') or {}).get('candidates_scan')
    record('cue export: --candidates lists the cut at the turn as an unconfirmed motion peak',
           code == 0 and any(abs(p - 3.0) <= 1 / 30 + 1e-6 for p in peaks) and (scan or {}).get('state') == 'found'
           and all(c['state'] == 'unconfirmed' for c in doc['export']['candidates']),
           f'exit {code}; peaks {str(peaks)[:120]}; scan {scan}; ' + text[-240:])
    # An empty candidate list always means a scan that ran: a page where nothing moves is inconclusive, and a
    # sample that fails is exit 2 naming it, with no list written.
    still = root / 'still-page'
    if still.exists():
        shutil.rmtree(still)
    still.mkdir()
    (still / 'index.html').write_bytes((
        '<!doctype html><html><body style="margin:0;width:320px;height:180px;background:#123">\n'
        '<div id="root" data-composition-id="main" data-start="0" data-duration="2" data-width="320" data-height="180">'
        'still</div>\n<script type="application/json" id="lf-cues">{"sections": {"all": {"clock": "action"}}, '
        '"events": {}}</script>\n<script>window.__timelines = window.__timelines || {}; window.__timelines["main"] = '
        '{labels: {"section:all": 0}, seek: function () {}, duration: function () { return 2; }};</script>\n'
        '</body></html>\n').encode('utf-8'))
    code, text, doc = export(still, root / 'still-candidates.json', '--candidates')
    scan = ((doc or {}).get('export') or {}).get('candidates_scan') or {}
    record('cue export: --candidates on a page where nothing moves is inconclusive (a look), never a bare empty list',
           code == 1 and scan.get('state') == 'inconclusive' and doc['export']['candidates'] == []
           and 'inconclusive' in text, f'exit {code}; {scan}; ' + text[-200:])
    failed_out = root / 'failed-candidates.json'
    r = subprocess.run([browser['node'], str(scripts / 'film_capture.mjs'), 'cues', str(still), '--out', str(failed_out),
                        '--browser', str(browser['chrome']), '--candidates'], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', env=dict(env, LF_FRAME_TIMEOUT_MS='1'), timeout=600)
    said = r.stdout + r.stderr
    record('cue export: a seek or capture that fails during --candidates is exit 2 naming the sample, and no list is '
           'written', r.returncode == 2 and '--candidates: the seek or capture of sample' in said and not failed_out.exists(),
           f'exit {r.returncode}; ' + said[-240:])

    custody = page_copy(root / 'custody')
    project = root / 'custody-project'
    version = project / 'cuts' / 'v001'
    (version / 'qa').mkdir(parents=True, exist_ok=True)
    (version / 'manifest.json').write_text('{"version": "v001"}', encoding='utf-8')
    refusals = []
    for target in (custody / 'index.html', version / 'cues.json', version / 'qa' / 'cues.json',
                   custody / '.lf-frozen' / 'x' / 'cues.json'):
        code, text, _ = export(custody, target)
        refusals.append(code == 2 and ('input' in text or 'version' in text or 'frozen' in text or 'page file' in text))
    record('cue export: the output may not alias an input, sit inside a version (qa/ too) or inside a kept copy',
           all(refusals), str(refusals))

    hyperframes = shutil.which('npx')
    probe = subprocess.run([hyperframes, '--no-install', HYPERFRAMES, '--version'], capture_output=True, text=True,
                           shell=os.name == 'nt', timeout=120) if hyperframes else None
    if probe is None or probe.returncode:
        skipped('cue export: npx hyperframes check on the fixture', f'{HYPERFRAMES} is not in the npx cache', 2)
    else:
        checked = page_copy(root / 'hf-check')
        export(checked)
        r = subprocess.run([hyperframes, '--no-install', HYPERFRAMES, 'check', str(checked), '--json'], capture_output=True,
                           text=True, encoding='utf-8', errors='replace', shell=os.name == 'nt', timeout=600,
                           env=dict(os.environ, HF_CLI_TELEMETRY_DISABLED='1'))
        try:
            report = json.loads(r.stdout[r.stdout.index('{'):])
        except ValueError:
            report = {}
        record('cue export: npx hyperframes check passes on the fixture', report.get('ok') is True, r.stdout[-300:] + r.stderr[-200:])
        state = cue_list.check(checked / 'cues.json')
        record('cue export: the list stays fresh after npx hyperframes check (it writes .hyperframes/)',
               state.state == 'fresh', state.message)

    kit = root / 'kit'
    if kit.exists():
        shutil.rmtree(kit)
    code, text = tool('new_film.py', kit)
    code, text = tool('film_check.py', kit, '--size', '640x360', '--browser', browser['chrome'], '--playwright', browser['core'])
    doc = json.loads((kit / 'cues.json').read_text(encoding='utf-8')) if (kit / 'cues.json').is_file() else {}
    state = cue_list.check(kit / 'cues.json') if (kit / 'cues.json').is_file() else None
    snap = (doc.get('picture') or {}).get('snapshot_sha256')
    record('cue export: film_check.py exports v2 through the freeze and keeps the copy',
           code == 0 and doc.get('version') == 'v2' and state and state.state == 'fresh' and snap
           and (kit / '.lf-frozen' / snap).is_dir() and doc.get('binding') == 'closed',
           f'exit {code}; {state.message if state else "no list"}; {doc.get("binding_reasons")}; ' + text[-200:])
    record('cue export: film_check.py warns when a kit film outside a project has no frame', 'has no frame' in text, text[-200:])
    film_js = kit / 'film.js'
    film_js.write_text(film_js.read_text(encoding='utf-8').replace(
        "    title: 'Northwind (starter)',",
        "    title: 'Northwind (starter)', frame: {what: 'a starter film', audience: 'testers', why: 'to check the frame', "
        "knows_by: [{s: 3, what: 'what this is', channel: 'type'}], state: {what: 'confirmed', audience: 'assumed'}},", 1),
        encoding='utf-8')
    code, text = tool('film_check.py', kit, '--size', '640x360', '--browser', browser['chrome'], '--playwright', browser['core'])
    preflight = json.loads((kit / 'qa' / 'preflight.json').read_text(encoding='utf-8')) if (kit / 'qa' / 'preflight.json').is_file() else {}
    frame = (preflight.get('info') or {}).get('frame') or {}
    lines = _module('selftest_cue_export_make', scripts / 'make_film.py').frame_lines(frame)
    record('cue export: the kit exposes spec.frame in info(), film_check.py stops warning, and make_film.py\'s report '
           'lines carry each field with its state',
           code in (0, 1) and frame.get('what') == 'a starter film' and 'has no frame' not in text
           and 'what: a starter film (confirmed)' in lines and 'audience: testers (assumed)' in lines
           and any(line.startswith('knows by 3 s') for line in lines), f'{frame}; {lines}; ' + text[-160:])
