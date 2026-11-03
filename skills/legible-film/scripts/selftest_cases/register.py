"""Register a master (SPEC §9): project.py add-version on every binding route, film_render.py --cues receipts and the
entries make_film.py appends, the render's network block, custody and pruning. Pages are made here: a small page on
the kit's __lf contract that ships its font (so it can bind receipt), its CRLF copy, and variants. Engine renders run
through a Node stub (it writes a test picture with FFmpeg; it stands in for HyperFrames and for Tesseract's returned
master) so add-version's checks are exercised without an engine; one real HyperFrames render of testpages/labels/
runs when hyperframes 0.8.209 is already in the npx cache. Needs Node, Playwright and Chromium for the kit renders;
a missing piece is a counted skip. The pinned-GSAP page needs one fetch from jsDelivr."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent.parent
HYPERFRAMES = 'hyperframes@0.8.209'

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>register fixture</title>
<style>@font-face { font-family: "Fixture"; src: url("font.woff2") format("woff2"); }
html, body { margin: 0; width: 320px; height: 180px; overflow: hidden; background: #000; font-family: "Fixture"; color: #fff; }
#bar { position: absolute; top: 40px; left: 0; width: 20px; height: 100px; background: #fff; }
#label { position: absolute; left: 10px; top: 8px; font-size: 18px; }</style>
@@HEAD@@</head><body><div id="bar"></div><div id="label">register</div>
<script>
const CUT = @@CUT@@;
window.__lf = {
  ready: document.fonts.ready,
  info: () => ({title: 'register fixture', width: 320, height: 180, fps: 30, duration: 2, frames: 60, cuts: [CUT],
    sections: [{id: 'a', a: 0, b: CUT, clock: 'action'}, {id: 'b', a: CUT, b: 2, clock: 'music'}],
    cues: [{id: 'cut', t: CUT, scale: 'turn', sound: 'required', sync: 'attack', role: 'hit', picture: 'the cut',
            decision: 'the hit lands on the cut', tolerance_ms: 17},
           {id: 'tick', t: 1.5, scale: 'contact', sound: 'required', sync: 'attack', role: 'tick', tolerance_ms: 17}]}),
  frame: t => {},
  seek: t => {
    document.body.style.background = t < CUT ? '#000' : '#204060';
    document.getElementById('bar').style.transform = 'translateX(' + (20 + t * 120) + 'px)';
  }
};
</script></body></html>
"""

STUB = r"""import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
const [page, out, ...flags] = process.argv.slice(2);
const value = f => flags.includes(f) ? flags[flags.indexOf(f) + 1] : null;
if (value('--edit-live')) fs.appendFileSync(value('--edit-live'), '\n<!-- edited during the render -->\n');
if (value('--fetch')) { try { await fetch(value('--fetch')); } catch (e) { console.error('fetch refused: ' + (e.cause?.code || e.message)); } }
if (value('--browser')) {
  const pw = createRequire(import.meta.url)(process.env.LF_PLAYWRIGHT_MODULE);
  const b = await pw.chromium.launch({executablePath: value('--browser')});
  const p = await b.newPage();
  try { await p.goto(value('--goto'), {timeout: 15000}); } catch (e) { console.error('goto refused: ' + e.message.split('\n')[0]); }
  await b.close();
}
if (!fs.existsSync(path.join(page, 'index.html'))) { console.error('stub: no page at ' + page); process.exit(3); }
const r = spawnSync('ffmpeg', ['-hide_banner', '-v', 'error', '-nostdin', '-y', '-f', 'lavfi', '-i',
  'testsrc2=size=320x180:rate=30:duration=2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', out], {stdio: 'inherit'});
if (r.status) process.exit(r.status);
console.log(`stub render ${page} -> ${out}`);
"""


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ffmpeg(*args):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y', *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stderr[-300:]


def make_page(folder, cut=1.0, head='', crlf=False):
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    text = PAGE.replace('@@HEAD@@', head).replace('@@CUT@@', repr(cut))
    data = text.encode('utf-8')
    (folder / 'index.html').write_bytes(data.replace(b'\n', b'\r\n') if crlf else data)
    shutil.copyfile(SKILL / 'assets' / 'fonts' / 'Inter-Latin-400.woff2', folder / 'font.woff2')
    return folder


def wav(path, seconds=2.0):
    ok, err = ffmpeg('-f', 'lavfi', '-i', f'sine=frequency=330:duration={seconds}', '-ar', '48000', '-ac', '2', path)
    return ok


def run_register_cases(tool, record, j, scripts_dir, skip=None):
    def skipped(name, reason, count):
        if skip:
            skip(name, reason, count)
        else:
            print(f'SKIP  {name} ({reason})' + (f' [{count} checks]' if count > 1 else ''))

    scripts = Path(scripts_dir)
    # Run directly (LF_SELFTEST_DIRECT=1), the cases that take the heavy lock are a counted skip: they run in the full
    # selftest under with_lock, where add-version inherits the lock its ancestor holds.
    direct = os.environ.get('LF_SELFTEST_DIRECT') == '1'
    cl = _module('selftest_register_cue_list', scripts / 'cue_list.py')
    make = _module('selftest_register_make', scripts / 'make_film.py')
    browser = _module('selftest_register_browser', HERE / '_browser.py').discover()
    root = Path(j('register-cases'))
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    if browser['missing'] or not shutil.which('ffmpeg'):
        skipped('register', browser['missing'] or 'FFmpeg is not on PATH', 40)
        return
    os.environ['LF_PLAYWRIGHT_MODULE'] = str(browser['core'])
    pw = ['--browser', browser['chrome'], '--playwright', browser['core']]
    stub = root / 'stub_render.mjs'
    stub.write_text(STUB, encoding='utf-8')

    def check_page(page):
        code, text = tool('film_check.py', page, '--size', '320x180', *pw)
        doc = json.loads((page / 'cues.json').read_text(encoding='utf-8')) if (page / 'cues.json').is_file() else None
        return code, text, doc

    def render(page, out, *extra, cues=True):
        args = [page, '--out', out, '--samples', 1, '--preview', *pw, *extra]
        if cues:
            args += ['--cues', page / 'cues.json']
        return tool('film_render.py', *args)

    def add(project, *args):
        return tool('project.py', 'add-version', project, *args)

    def manifest(project, version):
        return json.loads((project / 'cuts' / version / 'manifest.json').read_text(encoding='utf-8'))

    def stub_cmd(*flags):
        return 'node ' + f'"{stub}"' + ' {page} {out} ' + ' '.join(f'"{f}"' if ' ' in str(f) else str(f) for f in flags)

    # The kit route: film_check exports, film_render renders the kept copy, add-version --receipt registers.
    page = make_page(root / 'page')
    code, text, listed = check_page(page)
    if code == 2 or listed is None:
        record('register: film_check.py exports the fixture page', False, text[-300:])
        return
    record('register: film_check.py exports the fixture page through the freeze, binding closed',
           listed.get('binding') == 'closed' and listed.get('provenance') == 'exported', str(listed.get('binding_reasons')))
    r1 = root / 'renders' / 'r1.mp4'
    r1.parent.mkdir()
    code, text = render(page, r1)
    receipt = json.loads(Path(str(r1) + '.manifest.json').read_text(encoding='utf-8')) if code == 0 else {}
    record('register: film_render.py --cues renders the kept copy and writes the receipt fields',
           code == 0 and receipt.get('source_fingerprint') == listed['picture']['sha256']
           and receipt.get('snapshot_sha256') == listed['picture']['snapshot_sha256'] and receipt.get('digest') == 'lf1'
           and receipt.get('render_trace') == 'traced' and receipt.get('source_digests')
           and all(row.get('file_digest') for row in receipt.get('frozen', {}).values())
           and receipt.get('picture_sha256') == cl.picture_identity(r1)['sha256'], text[-300:])
    project = root / 'project'
    code, text = add(project, '--cues', page / 'cues.json', '--file', r1, '--receipt', str(r1) + '.manifest.json')
    m = manifest(project, 'v001') if code == 0 else {}
    identity = m.get('identity') or {}
    record('register: a kit film exported by film_check, rendered by film_render from the kept copy and registered binds '
           'receipt (render_trace traced)',
           code == 0 and identity.get('binding') == 'receipt' and identity.get('render_trace') == 'traced'
           and identity.get('cues_provenance') == 'exported'
           and identity.get('source', {}).get('snapshot_sha256') == listed['picture']['snapshot_sha256'], text[-300:])
    version = project / 'cuts' / 'v001'
    state = cl.check(version / 'cues.json') if (version / 'cues.json').is_file() else None
    record('register: the version holds preview.mp4, film.md, picture-timing.json and a list fresh against it',
           all((version / n).is_file() for n in ('preview.mp4', 'film.md', 'picture-timing.json', 'manifest.json'))
           and state and state.state == 'fresh', state.message if state else 'no list')
    ran = {name: tool(*args) for name, args in (('check', ('check.py', project, '--no-speech')),
                                                 ('screen', ('screen.py', 'build', project)),
                                                 ('grade', ('grade.py', project)))}
    record('register: a registered version screens, checks and grades without map.py or cut.py',
           all(code in (0, 1) for code, _ in ran.values()) and (version / 'checks.json').is_file()
           and (project / 'screening' / 'index.html').is_file(),
           '; '.join(f'{k} {c}: {t.strip().splitlines()[-1] if t.strip() else ""}' for k, (c, t) in ran.items())[:400])

    # A muxed master binds through its picture-stream hash; remuxes and display changes.
    sound = root / 'tone.wav'
    wav(sound)
    muxed = root / 'renders' / 'muxed.mp4'
    ffmpeg('-i', r1, '-i', sound, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-t', 2, muxed)
    code, text = add(project, '--cues', page / 'cues.json', '--file', muxed, '--receipt', str(r1) + '.manifest.json')
    record('register: a kit receipt binds a muxed master through the picture-stream hash',
           code == 0 and manifest(project, 'v002')['identity']['binding'] == 'receipt', text[-300:])
    mkv = root / 'renders' / 'remux.mkv'
    ffmpeg('-i', r1, '-c', 'copy', mkv)
    code, text = add(project, '--cues', page / 'cues.json', '--file', mkv, '--receipt', str(r1) + '.manifest.json')
    record('register: an MP4 to MKV remux of the master registers against its receipt',
           code == 0 and manifest(project, 'v003')['identity']['binding'] == 'receipt', text[-300:])
    flipped = root / 'renders' / 'hflip.mp4'
    made, _ = ffmpeg('-display_hflip', '-i', r1, '-c', 'copy', flipped)
    rot10 = root / 'renders' / 'rot10.mp4'
    made10, _ = ffmpeg('-display_rotation', '10', '-i', r1, '-c', 'copy', rot10)
    rotm10 = root / 'renders' / 'rotm10.mp4'
    ffmpeg('-display_rotation', '-10', '-i', r1, '-c', 'copy', rotm10)
    rot90 = root / 'renders' / 'rot90.mp4'
    ffmpeg('-display_rotation', '90', '-i', r1, '-c', 'copy', rot90)
    if made and made10:
        code, text = add(project, '--cues', page / 'cues.json', '--file', flipped, '--receipt', str(r1) + '.manifest.json')
        record('register: a horizontally flipped remux of the master is refused against its receipt',
               code == 2 and 'display' in text, text[-300:])
        geo = {n: cl.picture_identity(p)['geometry'] for n, p in (('r1', r1), ('rot10', rot10), ('rotm10', rotm10),
                                                                   ('rot90', rot90))}
        record('register: 10 and -10 degree rotations compare unequal to 0 and to 90 degrees',
               all(cl.geometry_compare(geo[a], geo[b])[0] == 'changed' for a in ('rot10', 'rotm10') for b in ('r1', 'rot90')),
               str({k: v['transform'] for k, v in geo.items()}))
        outcomes = []
        for tilted in (rot10, rotm10):
            fresh = root / 'renders' / f'{tilted.stem}-screened.mp4'
            shutil.copyfile(tilted, fresh)
            code, text = add(project, '--cues', page / 'cues.json', '--file', fresh)
            outcomes.append((code, text))
        names = sorted(p.name for p in (project / 'cuts').glob('v[0-9]*'))
        record('register: a 10 and a -10 degree display rotation each register unverified',
               all(c == 1 for c, _ in outcomes) and all(manifest(project, n)['identity']['binding'] == 'unverified'
                                                       for n in names[-2:]), ' | '.join(t[-160:] for _, t in outcomes))
    else:
        skipped('register: display transforms', 'this FFmpeg has no -display_rotation or -display_hflip', 3)
    scaled = root / 'renders' / 'itsscale.mp4'
    ffmpeg('-itsscale', '2', '-i', r1, '-c', 'copy', scaled)
    moved = root / 'renders' / 'setts.mkv'
    ffmpeg('-i', r1, '-c', 'copy', '-bsf:v', 'setts=pts=if(eq(N\\,10)\\,PTS+512\\,PTS)', moved)
    last = root / 'renders' / 'last-frame.mkv'
    ffmpeg('-i', r1, '-c', 'copy', '-bsf:v', 'setts=duration=if(eq(N\\,59)\\,DURATION*3\\,DURATION)', last)
    refusals = {}
    for name, target in (('itsscale', scaled), ('setts', moved), ('final-frame', last)):
        code, text = add(project, '--cues', page / 'cues.json', '--file', target, '--receipt', str(r1) + '.manifest.json')
        refusals[name] = (code, text.strip().splitlines()[-1] if text.strip() else '')
    record('register: a master retimed after its render (itsscale, one frame moved by setts, a longer final frame) is '
           'refused against its receipt', all(c == 2 and 'timing' in t for c, t in refusals.values()), str(refusals)[:400])

    # Receipts that are not whole.
    rec = json.loads(Path(str(r1) + '.manifest.json').read_text(encoding='utf-8'))
    bad = dict(rec, source_digests=dict(rec['source_digests'], **{'index.html': '0' * 64}))
    (root / 'bad-digests.json').write_text(json.dumps(bad), encoding='utf-8')
    code, text = add(project, '--cues', page / 'cues.json', '--file', r1, '--receipt', root / 'bad-digests.json')
    record('register: a kit receipt whose per-file digests do not reproduce its fingerprint is refused',
           code == 2 and 'reproduce' in text, text[-200:])
    bytes_only = dict(rec, frozen={k: {'sha256': v['sha256']} for k, v in rec['frozen'].items()})
    (root / 'bytes-only.json').write_text(json.dumps(bytes_only), encoding='utf-8')
    code, text = add(project, '--cues', page / 'cues.json', '--file', r1, '--receipt', root / 'bytes-only.json')
    newest = sorted(p.name for p in (project / 'cuts').glob('v[0-9]*'))[-1]
    record('register: a kit receipt carrying byte hashes only registers as unverified',
           code == 1 and manifest(project, newest)['identity']['binding'] == 'unverified' and 'byte hashes' in text,
           text[-200:])

    # --web: a lossless render, its H.264 encode and mux, and a WebM rendition with its own entry.
    lossless = root / 'renders' / 'master.mkv'
    code, text = render(page, lossless, '--lossless')
    h264 = root / 'renders' / 'master-h264.mp4'
    ok, _ = ffmpeg('-i', lossless, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '18', h264)
    if code == 0 and ok:
        man = json.loads(Path(str(lossless) + '.manifest.json').read_text(encoding='utf-8'))
        man['entries'].append(make.picture_entry('make_film.py encode_h264', h264))
        Path(str(h264) + '.manifest.json').write_text(json.dumps(man), encoding='utf-8')
        delivered = root / 'renders' / 'master-delivered.mp4'
        ffmpeg('-i', h264, '-i', sound, '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-t', 2, delivered)
        Path(str(delivered) + '.manifest.json').write_text(json.dumps(
            make.receipt_for(str(h264) + '.manifest.json', 'make_film.py mux_audio', delivered)), encoding='utf-8')
        code, text = add(project, '--cues', page / 'cues.json', '--file', delivered, '--receipt', str(delivered) + '.manifest.json')
        newest = sorted(p.name for p in (project / 'cuts').glob('v[0-9]*'))[-1]
        record('register: a --web kit master (lossless render, H.264 encode, mux) registers with binding receipt',
               code == 0 and manifest(project, newest)['identity']['binding'] == 'receipt', text[-300:])
        webm = root / 'renders' / 'master.webm'
        ffmpeg('-i', lossless, '-c:v', 'libvpx-vp9', '-crf', '40', '-b:v', '0', '-deadline', 'realtime', webm)
        Path(str(webm) + '.manifest.json').write_text(json.dumps(
            make.receipt_for(str(lossless) + '.manifest.json', 'make_film.py webm', webm)), encoding='utf-8')
        own_code, own = add(project, '--cues', page / 'cues.json', '--file', webm, '--receipt', str(webm) + '.manifest.json')
        other_code, other = add(project, '--cues', page / 'cues.json', '--file', webm, '--receipt', str(h264) + '.manifest.json')
        record('register: a --web rendition binds through its own entry and not through the master\'s',
               own_code == 0 and other_code == 2 and 'not one the receipt recorded' in other, own[-160:] + ' | ' + other[-160:])
    else:
        record('register: the --web route renders a lossless master and encodes it', False, text[-300:])

    # Line endings: one fingerprint, two snapshots, each list bound to its own copy.
    crlf = make_page(root / 'page-crlf', crlf=True)
    code, text, crlf_list = check_page(crlf)
    record('register: two copies of one page differing only in line endings share a fingerprint and get two snapshots',
           crlf_list is not None and crlf_list['picture']['sha256'] == listed['picture']['sha256']
           and crlf_list['picture']['snapshot_sha256'] != listed['picture']['snapshot_sha256'], text[-200:])
    state = cl.check(page / 'cues.json', owner=crlf)
    record('register: the LF list is stale against the CRLF copy, with the line-endings message',
           state.state == 'stale' and 'line endings' in state.message, state.message)
    rc = root / 'renders' / 'crlf.mp4'
    code, text = render(crlf, rc)
    crlf_receipt = json.loads(Path(str(rc) + '.manifest.json').read_text(encoding='utf-8')) if code == 0 else {}
    project_crlf = root / 'project-crlf'
    code, text = add(project_crlf, '--cues', crlf / 'cues.json', '--file', rc, '--receipt', str(rc) + '.manifest.json')
    record('register: the CRLF copy exports its own list, renders from its own kept copy and binds receipt, its digests '
           'reproducing the shared fingerprint',
           code == 0 and manifest(project_crlf, 'v001')['identity']['binding'] == 'receipt'
           and crlf_receipt.get('source_fingerprint') == listed['picture']['sha256'], text[-300:])
    code, text = add(project_crlf, '--cues', page / 'cues.json', '--file', rc, '--receipt', str(rc) + '.manifest.json',
                     '--page', page)
    record('register: a list bound to one copy is refused against a render of the other', code == 2 and 'snapshot' in text,
           text[-200:])

    # The kept copy and the live page: closure, exclusions, changes before and during a render.
    extras = make_page(root / 'page-extras')
    (extras / 'audio').mkdir()
    (extras / 'audio' / 'graph.json').write_text('{}', encoding='utf-8')
    (extras / '.visual.js').write_text('// a dot file\n', encoding='utf-8')
    before = cl.page_fingerprint(extras)
    code, text, extras_list = check_page(extras)
    kept = extras / '.lf-frozen' / (extras_list or {}).get('picture', {}).get('snapshot_sha256', 'none')
    record('register: the frozen copy of a page holding audio/graph.json and .visual.js holds neither and fingerprints as '
           'the live page does', kept.is_dir() and not (kept / 'audio').exists() and not (kept / '.visual.js').exists()
           and extras_list['picture']['sha256'] == before == cl.page_fingerprint(extras), text[-200:])
    tamper = make_page(root / 'page-tamper')
    code, text, tamper_list = check_page(tamper)
    kept = tamper / '.lf-frozen' / tamper_list['picture']['snapshot_sha256']
    original = (kept / 'index.html').read_bytes()
    results = []
    for changed in (original.replace(b'register fixture', b'register fixturE', 1), original.replace(b'\n', b'\r\n')):
        (kept / 'index.html').write_bytes(changed)
        code_r, text_r = render(tamper, root / 'renders' / f'tamper-{len(results)}.mp4')
        code_a, text_a = add(root / 'project-tamper', '--cues', tamper / 'cues.json',
                             '--file', root / 'renders' / f'tamper-out-{len(results)}.mp4', '--render', stub_cmd())
        results.append((code_r, code_a, 'differs from the export snapshot' in text_r + text_a))
    (kept / 'index.html').write_bytes(original)
    record('register: a byte changed in the kept copy after export is refused before the render, and so is a change to '
           'line endings alone (film_render.py --cues and add-version --render)',
           all(r == 2 and a == 2 and said for r, a, said in results), str(results))

    # --render through the network block, with a stub engine.
    hf = make_page(root / 'page-render')
    code, text, render_list = check_page(hf)
    (hf / 'renders').mkdir()
    planted = hf / 'renders' / 'older.mp4'
    shutil.copyfile(r1, planted)
    project_render = root / 'project-render'
    code, text = add(project_render, '--cues', hf / 'cues.json', '--file', hf / 'renders' / 'v1.mp4', '--render',
                     'node "' + str(stub) + '" {out}')
    record('register: a CMD without {page} or {out} is refused', code == 2 and '{page}' in text, text[-200:])
    if direct:
        skipped('register: add-version --render through the network block',
                'it takes the heavy lock; these run inside the full selftest under with_lock (LF_SELFTEST_DIRECT=1)', 8)
    else:
        code, text = add(project_render, '--cues', hf / 'cues.json', '--file', hf / 'renders' / 'v1.mp4', '--render', stub_cmd())
        receipt_r = json.loads((project_render / 'cuts' / 'v001' / 'receipt.json').read_text(encoding='utf-8')) if code == 0 else {}
        record('register: --render with an older render planted in renders/ registers only OUT, binding receipt, '
               'render_trace blocked, receipt fingerprint and snapshot equal to the list\'s',
               code == 0 and manifest(project_render, 'v001')['identity']['binding'] == 'receipt'
               and receipt_r.get('render_trace') == 'blocked' and Path(receipt_r.get('output', '')).name == 'v1.mp4'
               and receipt_r.get('source_fingerprint') == render_list['picture']['sha256']
               and receipt_r.get('snapshot_sha256') == render_list['picture']['snapshot_sha256']
               and receipt_r.get('block', {}).get('node_processes', 0) >= 1, text[-300:])
        code, text = add(project_render, '--cues', hf / 'cues.json', '--file', hf / 'renders' / 'v2.mp4', '--render',
                         stub_cmd('--edit-live', hf / 'index.html'))
        record('register: a stub CMD that edits the live page before writing {out} is refused as changed during the render',
               code == 2 and 'during the render' in text, text[-200:])
        hf_fetch = make_page(root / 'page-fetch')
        check_page(hf_fetch)
        code, text = add(root / 'project-fetch', '--cues', hf_fetch / 'cues.json', '--file', root / 'renders' / 'fetch.mp4',
                         '--render', stub_cmd('--fetch', 'https://example.com/lf-during-render.json'))
        record('register: a render that fetches an outside URL (never at export) is caught by the block and binds unverified',
               code == 1 and manifest(root / 'project-fetch', 'v001')['identity']['binding'] == 'unverified'
               and 'the network (blocked): example.com:443' in text, text[-300:])
        code, text = add(root / 'project-fetch', '--cues', hf_fetch / 'cues.json', '--file', root / 'renders' / 'fetch-b.mp4',
                         '--render', stub_cmd('--browser', browser['chrome'], '--goto', 'https://example.com/lf-browser'))
        record('register: a browser the render launches goes through the refusing proxy: the request is recorded and the '
               'binding is unverified', code == 1 and 'CONNECT example.com:443' in text, text[-300:])
        isolated = root / 'isolated' / 'legible-film'
        shutil.copytree(SKILL, isolated, ignore=shutil.ignore_patterns('__pycache__'))
        iso_page = make_page(root / 'page-isolated')
        r = subprocess.run([sys.executable, '-I', str(isolated / 'scripts' / 'film_check.py'), iso_page, '--size', '320x180', *map(str, pw)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        r = subprocess.run([sys.executable, '-I', str(isolated / 'scripts' / 'project.py'), 'add-version', root / 'project-isolated',
                            '--cues', iso_page / 'cues.json', '--file', root / 'renders' / 'isolated.mp4', '--render', stub_cmd(),
                            ], capture_output=True, text=True, encoding='utf-8', errors='replace')
        record('register: --render runs from an isolated install (the skill folder copied alone, without evals/)',
               r.returncode == 0 and 'binding receipt' in r.stdout and not (isolated.parent.parent / 'evals').exists(),
               (r.stdout + r.stderr)[-300:])
        absolute = root / 'outside.png'
        ffmpeg('-f', 'lavfi', '-i', 'color=c=red:s=8x8', '-frames:v', '1', absolute)
        offline = make_page(root / 'page-absolute', head=f'<style>#label {{ background-image: url("{absolute.as_posix()}"); }}</style>\n')
        code, text, abs_list = check_page(offline)
        code, text = add(root / 'project-absolute', '--cues', offline / 'cues.json', '--file', root / 'renders' / 'absolute.mp4',
                         '--render', stub_cmd())
        record('register: a page that overlays a local image by absolute path outside the copy, rendered with network blocked, '
               'binds unverified', code == 1 and 'outside reference' in text, text[-300:])
        system = make_page(root / 'page-system-font')
        index = system / 'index.html'
        index.write_text(index.read_text(encoding='utf-8').replace('font-family: "Fixture";', 'font-family: Arial, sans-serif;'),
                         encoding='utf-8')
        check_page(system)
        code, text = add(root / 'project-system', '--cues', system / 'cues.json', '--file', root / 'renders' / 'system.mp4',
                         '--render', stub_cmd())
        record('register: a page that uses a system font binds unverified', code == 1 and 'system font' in text, text[-300:])

    # The screen when there is no receipt; a retime with the old master; sound bound to its list.
    retime = make_page(root / 'page-retime')
    code, text, first_list = check_page(retime)
    old = root / 'renders' / 'retime-old.mp4'
    render(retime, old)
    project_retime = root / 'project-retime'
    old_list = root / 'retime-v1-cues.json'
    make.copy_cue_list(retime / 'cues.json', old_list, retime)
    first_code, first_text = add(project_retime, '--cues', old_list, '--file', old, '--receipt', str(old) + '.manifest.json',
                                 '--page', retime)
    report = root / 'mix' / 'mix-report.json'
    report.parent.mkdir()
    shutil.copyfile(sound, report.parent / 'mix.wav')
    mix_sha = cl.sha256_file(report.parent / 'mix.wav')
    report.write_text(json.dumps({'inputs': {'cues': cl.sha256_file(old_list)}, 'outputs': {'mix.wav': mix_sha}}),
                      encoding='utf-8')
    time.sleep(1.1)
    make_page(retime, cut=1.2)
    check_page(retime)
    code, text = add(project_retime, '--cues', retime / 'cues.json', '--file', old)
    record('register: a retimed page with a fresh list and the old master is refused', code == 2 and 'older' in text, text[-200:])
    code, text = add(project_retime, '--cues', retime / 'cues.json', '--file', old, '--accept-older', 'the old cut is approved')
    decided = (project_retime / 'decisions.jsonl').read_text(encoding='utf-8') if (project_retime / 'decisions.jsonl').is_file() else ''
    record('register: ... and accepted only with a recorded reason (overridden)',
           first_code == 0 and code in (0, 1) and manifest(project_retime, 'v002')['identity']['binding'] == 'overridden'
           and 'the old cut is approved' in decided, first_text[-150:] + ' | ' + text[-200:])
    new = root / 'renders' / 'retime-new.mp4'
    render(retime, new)
    code, text = add(project_retime, '--cues', retime / 'cues.json', '--file', new, '--receipt', str(new) + '.manifest.json',
                     '--sound', report.parent / 'mix.wav')
    record('register: on the retimed page, --sound with the old mix is refused', code == 2 and 'another cue list' in text,
           text[-200:])
    report.write_text(json.dumps({'inputs': {'cues': cl.sha256_file(retime / 'cues.json')}, 'outputs': {'mix.wav': mix_sha}}),
                      encoding='utf-8')
    code, text = add(project_retime, '--cues', retime / 'cues.json', '--file', new, '--receipt', str(new) + '.manifest.json',
                     '--sound', report.parent / 'mix.wav')
    newest = sorted(p.name for p in (project_retime / 'cuts').glob('v[0-9]*'))[-1]
    identity = manifest(project_retime, newest)['identity'] if code == 0 else {}
    record('register: ... and the remixed one is accepted, the mix recorded and the picture stream copied',
           code == 0 and identity.get('binding') == 'receipt' and identity.get('mix', {}).get('sound_sha256') == mix_sha
           and identity.get('picture_sha256') == cl.picture_identity(new)['sha256'], text[-300:])
    state_old = cl.check(old_list, owner=project_retime / 'cuts' / newest)
    state_own = cl.check(old_list, owner=project_retime / 'cuts' / 'v001')
    record('register: the old list is refused for the new version and stays fresh against its own',
           state_old.state == 'stale' and state_own.state == 'fresh', state_old.message + ' | ' + state_own.message)
    notes = project_retime / 'notes.json'
    data = json.loads(notes.read_text(encoding='utf-8'))
    data['notes'].append({'id': 'n1', 'version': 'v001', 't': 0.5, 'text': 'the cut is late', 'status': 'open'})
    notes.write_text(json.dumps(data), encoding='utf-8')
    code, text = add(project_retime, '--cues', retime / 'cues.json', '--file', new, '--receipt', str(new) + '.manifest.json')
    marked = json.loads(notes.read_text(encoding='utf-8'))['notes'][0]
    record('register: a registration with a different picture marks earlier review notes on an earlier version',
           code == 0 and marked.get('on_earlier_version') is True, str(marked))

    # A plan list, bound on the returned master (a stub master stands in for Tesseract's).
    returned = root / 'returned.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'color=c=black:s=160x90:r=30:d=1', '-f', 'lavfi', '-i', 'color=c=white:s=160x90:r=30:d=1',
           '-filter_complex', '[0][1]concat=n=2:v=1[v]', '-map', '[v]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', returned)
    plan = {'version': 'v2', 'clock': 'seconds from the first frame of the film', 'fps': 30, 'provenance': 'plan',
            'picture': {'kind': 'plan', 'sha256': None},
            'sections': [{'id': 'a', 'a': 0, 'b': 1, 'clock': 'action'}, {'id': 'b', 'a': 1, 'b': 2, 'clock': 'music'}],
            'events': [{'id': 'cut', 't': 1.0, 'scale': 'turn', 'section': 'b', 'decision': 'the hit is the cut'},
                       {'id': 'moved', 't': 1.5, 'scale': 'turn', 'section': 'b', 'decision': 'planned at 1.5 s'}]}
    (root / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
    code, text = add(root / 'project-plan', '--cues', root / 'plan.json', '--file', returned)
    plan_version = root / 'project-plan' / 'cuts' / 'v001'
    bound = cl.check(plan_version / 'cues.json') if (plan_version / 'cues.json').is_file() else None
    record('register: a plan fixture with one moved turn is flagged, the other passes, and the bound copy is fresh',
           code == 1 and 'no frame change at turn moved' in text and 'turn cut' not in text
           and manifest(root / 'project-plan', 'v001')['identity']['binding'] == 'plan-bound'
           and manifest(root / 'project-plan', 'v001')['identity']['cues_provenance'] == 'plan-bound'
           and bound and bound.state == 'fresh', text[-300:] + (bound.message if bound else ''))

    # Custody and pruning.
    code_a, text_a = add(project, '--cues', page / 'cues.json', '--file', project / 'cuts' / 'v001' / 'again.mp4',
                         '--render', stub_cmd())
    custody = make_page(root / 'page-custody')
    check_page(custody)
    code_b, text_b = add(root / 'project-custody', '--cues', custody / 'cues.json', '--file', custody / 'inside.mp4',
                         '--render', stub_cmd())
    record('register: OUT inside a version, or inside the page outside renders/, is refused',
           code_a == 2 and code_b == 2 and 'renders/' in text_b, text_a[-150:] + ' | ' + text_b[-150:])
    stray = page / '.lf-frozen' / ('f' * 64)
    stray.mkdir()
    code, text = tool('project.py', 'prune-frozen', project, '--page', page)
    record('register: prune-frozen removes a kept copy no list or version names and keeps the named one',
           code == 0 and not stray.exists() and (page / '.lf-frozen' / listed['picture']['snapshot_sha256']).is_dir(),
           text[-200:])

    # The pinned-GSAP page by the kit route, and the kit's own starter film end to end.
    gsap = make_page(root / 'page-gsap', head='<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>\n')
    code, text, gsap_list = check_page(gsap)
    if gsap_list is None or gsap_list.get('binding') != 'closed':
        skipped('register: the pinned-GSAP page by the kit route', 'jsDelivr unreachable: ' + text[-120:], 1)
    else:
        rg = root / 'renders' / 'gsap.mp4'
        render(gsap, rg)
        code, text = add(root / 'project-gsap', '--cues', gsap / 'cues.json', '--file', rg, '--receipt', str(rg) + '.manifest.json')
        record('register: the pinned-GSAP page rendered by the kit route registers receipt with render_trace traced',
               code == 0 and manifest(root / 'project-gsap', 'v001')['identity']['render_trace'] == 'traced', text[-300:])
    kit = root / 'kit'
    tool('new_film.py', kit)
    code, text, kit_list = check_page(kit)
    rk = root / 'renders' / 'kit.mp4'
    code_r, text_r = render(kit, rk, '--size', '320x180') if kit_list else (2, text)
    code, text = add(root / 'project-kit', '--cues', kit / 'cues.json', '--file', rk, '--receipt', str(rk) + '.manifest.json') \
        if code_r == 0 else (2, text_r)
    record('register: the kit\'s starter film, exported by film_check and rendered by film_render, binds receipt',
           code == 0 and manifest(root / 'project-kit', 'v001')['identity']['binding'] == 'receipt', text[-300:])

    if direct:
        skipped('register: a real HyperFrames render of testpages/labels/ under the block',
                'a render: it runs inside the full selftest under with_lock (LF_SELFTEST_DIRECT=1)', 1)
        return
    hyperframes = shutil.which('npx')
    probe = subprocess.run([hyperframes, '--no-install', HYPERFRAMES, '--version'], capture_output=True, text=True,
                           shell=os.name == 'nt', timeout=120) if hyperframes else None
    if probe is None or probe.returncode:
        skipped('register: a real HyperFrames render of testpages/labels/ under the block', f'{HYPERFRAMES} is not in the npx cache', 1)
        return
    labels = root / 'labels'
    shutil.copytree(HERE.parent / 'testpages' / 'labels', labels)
    env = dict(os.environ, LF_PYTHON=sys.executable)
    subprocess.run([browser['node'], str(scripts / 'film_capture.mjs'), 'cues', str(labels), '--out', str(labels / 'cues.json'),
                    '--browser', str(browser['chrome'])], env=env, capture_output=True)
    (labels / 'renders').mkdir()
    shutil.copyfile(r1, labels / 'renders' / 'labels_older.mp4')
    index = labels / 'index.html'
    index.write_text(index.read_text(encoding='utf-8').replace("tl.addLabel('cue:tap-3', F(5));", "tl.addLabel('cue:tap-3', F(5.1));"),
                     encoding='utf-8')
    subprocess.run([browser['node'], str(scripts / 'film_capture.mjs'), 'cues', str(labels), '--out', str(labels / 'cues.json'),
                    '--browser', str(browser['chrome'])], env=env, capture_output=True)
    command = f'npx --no-install {HYPERFRAMES} render {{page}} -o {{out}} --workers 1 --quality draft'
    code, text = add(root / 'project-hf', '--cues', labels / 'cues.json', '--file', labels / 'renders' / 'v1.mp4', '--render', command)
    hf_receipt = json.loads((root / 'project-hf' / 'cuts' / 'v001' / 'receipt.json').read_text(encoding='utf-8')) if code in (0, 1) else {}
    record('register: a real HyperFrames render of the retimed testpages/labels/ under the block registers only OUT '
           '(binding receipt, render_trace blocked)',
           code == 0 and hf_receipt.get('binding') == 'receipt' and hf_receipt.get('render_trace') == 'blocked'
           and Path(hf_receipt.get('output', '')).name == 'v1.mp4', text[-400:])
