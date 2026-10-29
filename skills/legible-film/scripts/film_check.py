#!/usr/bin/env python3
"""Preflight a kit film before rendering: truth, contrast, reading windows, predicted flashing,
regular patterns, per-element motion and a determinism lint, with the exports the render and QC
steps read.

Serves FILM (a folder made by new_film.py) on 127.0.0.1, loads it headless at the given size, and
runs window.__lf.info() and window.__lf.analyse(). It then searches the film, its blocks and the
kit runtime for anything that would make a frame depend on the wall clock or the network (Date,
performance.now, Math.random, setTimeout, setInterval, requestAnimationFrame, CSS transition,
animation or @keyframes, fetch, XMLHttpRequest, WebSocket, remote URLs); a line carrying the marker
"lf-lint-ok" with a reason is accepted. It also reports any page request after __lf.ready.

  python film_check.py films/launch
  python film_check.py films/launch --size 1080x1920 --json qa/preflight.json
  python film_check.py films/launch --size 1920x1080 --res 720

--res N is the delivered short side when the render scales the frame (film_render.py --res): the
layout stays at --size, and the output-pixel criteria (type size, the large-text contrast rule, dither
cells, still resolution) are judged on the delivered raster.

Writes, in FILM: cues.json (the skill's cue format, exported from the picture's own source),
reading.json (every registered text's in, readStart, readEnd, out, need, size, colour, ground and
contrast), captions.srt and captions.vtt (when the film has captions), qa/declared.json (designed
cuts, rests and flashes as --ignore ranges for the QC scripts) and qa/preflight.json (or --json).

What it does not prove: these are measurements of the page's own state, not of the delivered file.
It cannot see encoding, banding, judder or whether anything reads at speed; flash and pattern
predictions draw the ground, flashes, plates, tracked nodes and the type itself, so flash_scan.py
must still run on the render. Reading windows follow the film's reading rule (default 15
characters per second plus 0.3 s; captions 20 per second), which is a floor, not comprehension.

Needs Node 18+ and Playwright with a Chromium build. It uses film_capture.mjs when that worker is
beside this script (or given with --capture); otherwise a small bundled runner, which finds
playwright or playwright-core from --playwright, LF_PLAYWRIGHT_MODULE or the working directory, and
Chromium from --browser, LF_CHROMIUM or LOCALAPPDATA/ms-playwright. No browser download.
Exit codes: 0 no errors and no lint hits; 1 errors, lint hits or requests after ready to fix;
2 the check could not run.
"""

import argparse
import functools
import glob
import http.server
import json
import mimetypes
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading

VERSION = '1.0'
LINT = [
    (r'\bDate\b', 'Date (wall clock)'),
    (r'performance\s*\.\s*now', 'performance.now (wall clock)'),
    (r'Math\s*\.\s*random', 'Math.random (unseeded randomness)'),
    (r'\bsetTimeout\b', 'setTimeout (wall-clock timer)'),
    (r'\bsetInterval\b', 'setInterval (wall-clock timer)'),
    (r'\brequestAnimationFrame\b', 'requestAnimationFrame (a loop that advances state)'),
    (r'(?<![\w-])transition\s*:', 'CSS transition'),
    (r'(?<![\w-])animation(-name)?\s*:', 'CSS animation'),
    (r'@keyframes', 'CSS @keyframes'),
    (r'\bfetch\s*\(', 'fetch (network)'),
    (r'XMLHttpRequest|\bnew\s+WebSocket\b|\bEventSource\b', 'network request'),
    (r'https?://(?!127\.0\.0\.1|localhost|www\.w3\.org/2000/svg)[\w.-]+\.[a-z]{2,}', 'remote URL'),
]

RUNNER = r"""
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
const [url, W, H, mod, exe] = process.argv.slice(2);
const req = createRequire(path.join(process.cwd(), 'x.js'));
let pw;
const tries = mod ? [path.resolve(mod, 'index.mjs'), path.resolve(mod)] : [];
for (const m of ['playwright', 'playwright-core']) { try { tries.push(req.resolve(m)); } catch (e) {} }
for (const t of tries) { try { pw = await import(pathToFileURL(t).href); break; } catch (e) {} }
if (!pw) { console.log(JSON.stringify({ error: 'Playwright is not installed (npm i playwright-core, or pass --playwright)' })); process.exit(2); }
const chromium = pw.chromium || pw.default?.chromium;
let browser;
const out = { console: [], requests_after_ready: [] };
const timer = setTimeout(async () => { out.error = 'timed out'; console.log(JSON.stringify(out)); try { await browser?.close(); } catch (e) {} process.exit(2); }, 280000);
try {
  browser = await chromium.launch({ executablePath: exe || undefined, args: ['--force-color-profile=srgb'] });
  const ctx = await browser.newContext({ viewport: { width: +W, height: +H }, deviceScaleFactor: 1, serviceWorkers: 'block' });
  const page = await ctx.newPage();
  let ready = false;
  page.on('request', r => { if (ready) out.requests_after_ready.push(r.url()); });
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') out.console.push(`${m.type()}: ${m.text()}`); });
  page.on('pageerror', e => out.console.push(`pageerror: ${e.message}`));
  await page.goto(url);
  await page.waitForFunction(() => !!window.__lf, null, { timeout: 30000 });
  await page.evaluate(() => window.__lf.ready);
  ready = true;
  out.info = await page.evaluate(() => window.__lf.info());
  out.analysis = await page.evaluate(() => window.__lf.analyse ? window.__lf.analyse() : null);
} catch (e) { out.error = String(e && e.message || e); }
finally { clearTimeout(timer); try { await browser?.close(); } catch (e) {} }
console.log(JSON.stringify(out));
process.exit(out.error ? 2 : 0);
"""


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def find_chromium(explicit=None):
    if explicit or os.environ.get('LF_CHROMIUM'):
        return explicit or os.environ.get('LF_CHROMIUM')
    base = os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'ms-playwright')
    pats = ['chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell*', 'chromium-*/chrome-*/chrome', 'chromium-*/chrome-*/chrome.exe',
            os.path.join(os.path.expanduser('~'), '.cache', 'ms-playwright', 'chromium_headless_shell-*', '*', 'chrome-headless-shell')]
    found = []
    for p in pats:
        found += [f for f in glob.glob(os.path.join(base, p) if not os.path.isabs(p) else p) if os.path.isfile(f)]
    def rev(f):
        m = re.search(r'-(\d+)[\\/]', f)
        return int(m.group(1)) if m else 0
    return max(found, key=rev) if found else None


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()


def serve(folder):
    mimetypes.add_type('text/javascript', '.js')
    mimetypes.add_type('text/javascript', '.mjs')
    mimetypes.add_type('font/woff2', '.woff2')
    handler = functools.partial(Quiet, directory=folder)
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def lint(folder):
    files = [os.path.join(folder, 'film.js'), os.path.join(folder, 'index.html')]
    for sub in ('blocks', 'lf'):
        files += sorted(glob.glob(os.path.join(folder, sub, '*.js')))
    files += sorted(glob.glob(os.path.join(folder, '*.css')))
    hits = []
    for f in files:
        if not os.path.isfile(f):
            continue
        with open(f, encoding='utf-8', errors='replace') as fh:
            for n, line in enumerate(fh, 1):
                if 'lf-lint-ok' in line:
                    continue
                code = re.sub(r'//.*$', '', line) if f.endswith('.js') else line
                code = re.sub(r'/\*.*?\*/', '', code)
                if f.endswith('.js') and code.lstrip().startswith('*'):
                    continue
                for pat, what in LINT:
                    if re.search(pat, code):
                        hits.append({'file': os.path.relpath(f, folder).replace('\\', '/'), 'line': n, 'what': what, 'text': line.strip()[:160]})
    return hits


def srt_time(t):
    ms = int(round(t * 1000))
    return f'{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}'


def run_page(a, folder, w, h):
    httpd = serve(folder)
    port = httpd.server_address[1]
    url = f'http://127.0.0.1:{port}/index.html?render&w={w}&h={h}' + (f'&res={a.res}' if a.res else '')
    node = find_tool('node', a.node)
    if not node:
        httpd.shutdown()
        raise RuntimeError('Node is not on PATH (or pass --node)')
    capture = a.capture or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'film_capture.mjs')
    try:
        if os.path.isfile(capture):
            res = {}
            for cmd in ('info', 'analyse'):
                p = subprocess.run([node, capture, cmd, '--url', url, '--size', f'{w}x{h}'] + (['--browser', a.browser] if a.browser else []) + (['--playwright', a.playwright] if a.playwright else []),
                                   capture_output=True, text=True, timeout=300)
                if p.returncode != 0:
                    reason = (p.stderr.strip().splitlines() or ['?'])[-1]
                    if cmd == 'analyse' and 'not implemented' in reason:
                        res['analysis'] = None
                        continue
                    raise RuntimeError(f'film_capture.mjs {cmd} failed: ' + reason)
                res['info' if cmd == 'info' else 'analysis'] = json.loads(p.stdout)
            res['runner'] = 'film_capture.mjs'
            return res
        with tempfile.TemporaryDirectory() as td:
            script = os.path.join(td, 'lf_check_runner.mjs')
            with open(script, 'w', encoding='utf-8') as f:
                f.write(RUNNER)
            p = subprocess.run([node, script, url, str(w), str(h), a.playwright or os.environ.get('LF_PLAYWRIGHT_MODULE', ''), find_chromium(a.browser) or ''],
                               capture_output=True, text=True, timeout=300, cwd=os.getcwd())
            try:
                res = json.loads(p.stdout.strip().splitlines()[-1])
            except (ValueError, IndexError):
                raise RuntimeError('the page runner printed no result: ' + (p.stderr.strip()[-400:] or 'no output'))
            if res.get('error'):
                raise RuntimeError(res['error'] + ('; ' + '; '.join(res.get('console', [])[:3]) if res.get('console') else ''))
            res['runner'] = 'bundled runner'
            return res
    finally:
        httpd.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('film', help='the film folder (index.html, film.js, lf/, blocks/)')
    ap.add_argument('--size', default=None, help='WxH, for example 1080x1920 (default: the spec size)')
    ap.add_argument('--res', type=int, help='delivered short side in pixels when the render scales the frame '
                    '(film_render.py --res); output-pixel criteria are judged at that size')
    ap.add_argument('--json', help='where to write the preflight report (default FILM/qa/preflight.json)')
    ap.add_argument('--capture', help='path to film_capture.mjs (default: beside this script, if present)')
    ap.add_argument('--node')
    ap.add_argument('--browser', help='Chromium executable')
    ap.add_argument('--playwright', help='path to an installed playwright or playwright-core package')
    a = ap.parse_args()

    folder = os.path.abspath(a.film)
    if not os.path.isfile(os.path.join(folder, 'index.html')):
        print(f'film_check.py: {folder} is not a film folder (needs an index.html implementing window.__lf)', file=sys.stderr)
        return 2
    w, h = (1920, 1080)
    if a.size:
        m = re.fullmatch(r'(\d+)x(\d+)', a.size)
        if not m:
            print(f'film_check.py: --size must look like 1920x1080, not {a.size!r}', file=sys.stderr)
            return 2
        w, h = int(m.group(1)), int(m.group(2))
    elif os.path.isfile(os.path.join(folder, 'film.js')):
        with open(os.path.join(folder, 'film.js'), encoding='utf-8') as f:
            m = re.search(r'size:\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]', f.read())
        if m:
            w, h = int(m.group(1)), int(m.group(2))

    if a.res is not None and a.res < 2:
        print('film_check.py: --res is the delivered short side in pixels, at least 2', file=sys.stderr)
        return 2
    # film_render.py's rule: --res is the output's short side.
    out_size = (round(w * a.res / min(w, h)), round(h * a.res / min(w, h))) if a.res else (w, h)
    delivered = f' (delivered {out_size[0]}x{out_size[1]})' if a.res else ''
    try:
        res = run_page(a, folder, w, h)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        print(f'film_check.py: could not run the page at {w}x{h}: {e}', file=sys.stderr)
        return 2
    info, an = res.get('info') or {}, res.get('analysis')
    unanalysed = an is None
    an = an or {}
    hits = lint(folder)
    errors = list(an.get('errors', []))
    warnings = list(an.get('warnings', []))
    if unanalysed:
        warnings.append('the page has no __lf.analyse(): facts, contrast, reading windows, predicted flashing, motion '
                        'and patterns were not checked; the cue list, captions and declarations come from info()')
    late = res.get('requests_after_ready', [])
    for r in late[:10]:
        errors.append(f'network: request after __lf.ready: {r}')
    for c in res.get('console', [])[:10]:
        warnings.append(f'console {c}')
    for hit in hits:
        errors.append(f"lint: {hit['file']}:{hit['line']} {hit['what']}: {hit['text']}")

    qa = os.path.join(folder, 'qa')
    os.makedirs(qa, exist_ok=True)
    written = []

    def save(path, obj=None, text=None):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            if text is not None:
                f.write(text)
            else:
                json.dump(obj, f, indent=1)
        written.append(os.path.relpath(path, folder).replace('\\', '/') if path.startswith(folder) else path)

    fps = info.get('fps', 60)
    save(os.path.join(folder, 'cues.json'), {
        'clock': 'seconds from the first frame of the film', 'fps': fps, 'version': 'v1',
        'exported_from': f"film.js through window.__lf.info() by film_check.py {VERSION} at {w}x{h}",
        'fields': 't: seconds; sound: required, silent or optional; sync: attack, apex or end; tolerance_ms: largest offset still on cue; window_ms: how far either side of t to check; role: the sound palette role; gain_db, duck_db, variant: optional mix hints',
        'events': info.get('cues', []),
    })
    save(os.path.join(folder, 'reading.json'), {
        'size': f'{w}x{h}', **({'output_size': f'{out_size[0]}x{out_size[1]}'} if a.res else {}), 'fps': fps,
        'rule': 'need_s = base + characters / cps (claims, qualifiers, headlines, identities, interface text: '
                '15 cps + 0.3 s by default; captions 20 cps; texture exempt)',
        'texts': an.get('texts', []),
    })
    caps = info.get('captions') or []
    if caps:
        srt, vtt = [], ['WEBVTT', '']
        for i, c in enumerate(caps, 1):
            text = c.get('text') or ' '.join(x[0] for x in c.get('words', []))
            srt += [str(i), f"{srt_time(c['t0'])} --> {srt_time(c['t1'])}", text, '']
            vtt += [f"{srt_time(c['t0']).replace(',', '.')} --> {srt_time(c['t1']).replace(',', '.')}", text, '']
        save(os.path.join(folder, 'captions.srt'), text='\n'.join(srt))
        save(os.path.join(folder, 'captions.vtt'), text='\n'.join(vtt))
    rests, flashes, cuts = info.get('rests', []), info.get('flashes', []), info.get('cuts', [])
    blanks = info.get('blanks', [])
    save(os.path.join(qa, 'declared.json'), {
        'note': ('Designed events from the film itself, for the QC scripts. Pass "ignore" to --ignore (rests, flashes and '
                 'designed near-empty frames at seams). cuts are every hard cut (motion blur never samples across one); '
                 'seams are the cuts that are invisible by design (dives, shrinks), so a render shows no large '
                 'change there; changes are designed large changes that are not cuts (landings, fills, bursts, '
                 'ground flips), with their spans in change_windows. loop is true when the film is a loop.'),
        'ignore': ','.join(f'{r[0]:.3f}-{r[1]:.3f}' for r in sorted([*rests, *flashes, *blanks])),
        'cuts': cuts, 'seams': info.get('seams', []), 'changes': info.get('changes', []), 'change_windows': info.get('change_windows', []),
        'blanks': blanks, 'rests': rests, 'flashes': flashes, 'smears': info.get('smears', []), 'fast': info.get('fast', []),
        'music': info.get('music'), 'pace': info.get('pace'), 'loop': bool(info.get('loop')),
    })
    analysis = dict(an)
    report = {
        'tool': 'film_check.py', 'version': VERSION, 'film': folder, 'size': f'{w}x{h}', 'runner': res.get('runner'),
        **({'output_size': f'{out_size[0]}x{out_size[1]}', 'res': a.res} if a.res else {}),
        'errors': errors, 'warnings': warnings, 'lint': hits, 'requests_after_ready': late,
        'info': info, 'analysis': analysis, 'exports': written,
        'not_checked': ['the delivered file (render it and run the QC battery)', 'motion at playback speed', 'sound']
                       + (['facts, contrast, reading windows, predicted flashing, motion and patterns (no __lf.analyse())']
                          if unanalysed else []),
    }
    out = os.path.abspath(a.json) if a.json else os.path.join(qa, 'preflight.json')
    report['exports'] = written + [out]
    save(out, report)

    # Summary.
    fl = an.get('flash', {})
    texts = an.get('texts', [])
    print(f"{info.get('title', 'film')}: {w}x{h}{delivered}, {info.get('duration')} s, {info.get('frames')} frames "
          f"at {fps} fps ({res.get('runner')})")
    print(f"  texts: {len(texts)} registered, {sum(1 for x in texts if x.get('readStart') is not None)} reach a readable state")
    inc = fl.get('incomplete') or []
    unmodelled = ', '.join(x['id'] for x in inc[:6])
    print(f"  flash prediction: max {fl.get('max_transitions_in_1s')} opposing transitions in 1 s (limit 6), "
          f"red {fl.get('red_max_transitions_in_1s')}"
          + (f"; INCOMPLETE: {len(inc)} tracked node(s) paint what it cannot model ({unmodelled})" if inc else ''))
    mo = an.get('motion') or {}
    if mo:
        el = mo.get('elements', [])
        print(f"  motion: {len(el)} tracked elements, {sum(e.get('jumps', 0) for e in el)} jumps, {sum(e.get('fast_frames_unblurred', 0) for e in el)} unblurred fast frames, {len(mo.get('warnings', []))} motion warnings")
    pt = (an.get('patterns') or {}).get('items', [])
    if pt:
        print('  patterns: ' + ', '.join(f"{p['id']} {p['risk_frames']} risk frame(s)" for p in pt))
    lp = an.get('loop')
    if lp:
        print(f"  loop: the seam {'closes' if lp.get('closes') else 'does not close'} (frame 0 against the end: "
              f"{', '.join(lp.get('checked', []))}; {len(lp.get('differences', []))} difference(s))")
    print(f"  lint: {len(hits)} hit(s); requests after ready: {len(late)}")
    for e in errors[:20]:
        print(f'  ERROR {e}')
    if len(errors) > 20:
        print(f'  ... {len(errors) - 20} more errors in {out}')
    for wmsg in warnings[:12]:
        print(f'  warn  {wmsg}')
    if len(warnings) > 12:
        print(f'  ... {len(warnings) - 12} more warnings in {out}')
    print('  wrote ' + ', '.join(report['exports']))
    print(f"preflight {w}x{h}{delivered}: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
