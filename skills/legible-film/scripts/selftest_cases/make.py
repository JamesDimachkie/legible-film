#!/usr/bin/env python3
"""Known-answer cases for make_film.py, standalone or called from selftest.py.

Integration: add 'make' to CASE_MODULES in selftest.py; it calls
run_make_cases(tool, record, j, HERE). The runner uses the existing tool(), record() and j().

  python make.py --scripts skills/legible-film/scripts --keep work/make-cases
  python make.py --scripts scripts --keep work/make-cases --playwright node_modules/playwright-core

Builds tiny original __lf pages (320x180 and 180x320, 30 fps, 3 s) and runs make_film.py
end to end: the doctor finding a missing tool, a silent and a draft-sound run whose audio
and picture lengths match exactly, a declared cut that is not in the picture, sizes that
export different cue lists, --resume skipping a finished render, and the exit codes.
One Chromium at a time. Missing Node, Playwright or Chromium (or too little free memory
for a render) prints 'skipped: <reason>' and records nothing. Needs numpy, Pillow, FFmpeg,
Node, Playwright, Chromium and film_check.py beside make_film.py. Exit 0 all passed (or
skipped), 1 any failure. These synthetic films prove the pipeline, not any film's quality.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

# One page, parameterised per case. Frame-pure: every pixel is a function of t.
PAGE = """<!doctype html>
<meta charset="utf-8">
<title>make_film synthetic film</title>
<style>
* {box-sizing:border-box} html,body {margin:0;overflow:hidden}
#stage {position:absolute;inset:0;overflow:hidden}
#bar {position:absolute;top:0;height:100%;width:12%;will-change:transform}
#word {position:absolute;left:6%;top:8%;font:bold 28px monospace;letter-spacing:2px}
#grid {position:absolute;left:0;right:0;bottom:6%;height:8%;
       background:repeating-linear-gradient(90deg,#888 0 6px,transparent 6px 14px)}
</style>
<div id="stage"><div id="word">HELLO</div><div id="bar"></div><div id="grid"></div></div>
<script>
const P=__PARAMS__;
const q=new URLSearchParams(location.search), width=Number(q.get('w')||320), height=Number(q.get('h')||180);
document.documentElement.style.width=width+'px';document.documentElement.style.height=height+'px';
const shift=(P.cueShift&&width<height)?P.cueShift:0;
window.__lf={
  ready:document.fonts.ready,
  info:()=>({title:'make_film synthetic film',width,height,fps:30,duration:3,frames:90,
    beat:{bpm:120,offset:0},cuts:P.cuts,smears:[],fast:[],rests:[[2.6,3,'end hold']],flashes:[],
    music:{stop:2.9},pace:{max_still_share:.9,max_still:2},
    cues:[{id:'swing',t:.8,role:'whoosh',sound:'required',sync:'apex',tolerance_ms:25,picture:'the bar passes centre'},
          {id:'cut',t:1.5+shift,role:'impact',sound:'required',sync:'attack',tolerance_ms:17,picture:'the light shot arrives'}],
    captions:[{t0:.3,t1:1.4,words:[['Hello',.3],['there',.7]]}],
    texts:[{id:'hello',role:'headline',string:'HELLO',readStart:.4},{id:'after',role:'headline',string:'HELLO',readStart:1.8}],
    warnings:[]}),
  frame:t=>{},
  seek:t=>{
    const light=t>=1.5, flip=P.flip!==null&&t>=P.flip&&t<1.5;
    document.querySelector('#stage').style.background=light?'#e8e4dc':flip?'#9a9a9a':'#101418';
    document.querySelector('#word').style.color=light?'#101418':'#f3f1ea';
    const bar=document.querySelector('#bar');
    bar.style.background=light?'#2a5d8f':'#f3f1ea';
    bar.style.transform=`translate3d(${(10+t*90)*width/320}px,0,0)`;
  },
  analyse:()=>({texts:[],errors:[],warnings:[]})
};
window.__lf.seek(0);
</script>
"""


def run_make_cases(tool, record, j, scripts_dir):
    scripts_dir = Path(scripts_dir)

    def load(path):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def film(name, cuts, flip=None, cue_shift=0):
        folder = Path(j('make-films', name))
        folder.mkdir(parents=True, exist_ok=True)
        params = json.dumps({'cuts': cuts, 'flip': flip, 'cueShift': cue_shift})
        (folder / 'index.html').write_text(PAGE.replace('__PARAMS__', params), encoding='utf-8')
        return folder

    def lengths(path):
        """Decoded video frames and audio samples of a delivered file (None when a stream is absent)."""
        frames = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                                 'stream=nb_read_frames', '-of', 'csv=p=0', str(path)], capture_output=True, text=True)
        audio = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index',
                                '-of', 'csv=p=0', str(path)], capture_output=True, text=True).stdout.strip()
        samples = None
        if audio:
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:a:0', '-ac', '1',
                                  '-ar', '48000', '-f', 's16le', '-'], capture_output=True).stdout
            samples = len(raw) // 2
        return int(frames.stdout.strip() or 0), samples

    code, _ = tool('make_film.py', '--doctor', '--sizes', '320x180,180x320', '--json', j('make-doctor.json'))
    rows = load(j('make-doctor.json')).get('doctor', [])
    browser = [r for r in rows if r['name'] in ('Node', 'Playwright', 'Chromium') and not r['ok']]
    if browser:
        print('skipped: make_film cases need ' + '; '.join(f"{r['name']} ({r['detail']})" for r in browser), flush=True)
        return
    memory = next((r for r in rows if r['name'] == 'free memory'), {'ok': False, 'detail': 'not measured'})
    if not memory['ok']:
        print('skipped: make_film cases need memory for one small render: ' + memory['detail'], flush=True)
        return
    if not (scripts_dir / 'film_check.py').is_file():
        print('skipped: make_film cases need film_check.py beside make_film.py', flush=True)
        return
    record('make_film: doctor reports ready with every tool present', code == 0,
           '; '.join(r['name'] for r in rows if not r['ok']))

    # 1. The doctor names a missing tool and its fix; exit 1.
    code, out = tool('make_film.py', '--doctor', '--sizes', '320x180', '--node', j('no-such-node.exe'),
                     '--ffmpeg', j('no-such-ffmpeg.exe'))
    record('make_film: doctor detects missing Node and FFmpeg, prints fixes, exit 1',
           code == 1 and 'MISSING  Node' in out and 'MISSING  FFmpeg' in out and out.count('fix: ') >= 2,
           f'exit {code}')

    # 2. Could not run: exit 2 for a folder that is not a film, and for a run with a missing tool.
    code, _ = tool('make_film.py', j('make-films', 'nowhere'), '--sizes', '320x180')
    record('make_film: a missing film folder is exit 2', code == 2, f'exit {code}')
    clean = film('clean', [1.5])
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--node', j('no-such-node.exe'),
                     '--out', j('make-out', 'no-node'))
    record('make_film: a full run with Node missing is exit 2 and names the fix',
           code == 2 and 'Node' in out and 'fix:' in out, f'exit {code}')

    # 3. A silent deliverable: no audio stream, the picture's exact length; every check passes.
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'silent'), '--json', j('make-silent.json'))
    s = load(j('make-silent.json'))
    deliverable = Path(j('make-out', 'silent', 'deliver', 'clean_320x180.mp4'))
    frames, samples = lengths(deliverable) if deliverable.is_file() else (0, 'missing')
    record('make_film: silent run exits 0 with every check passing', code == 0 and not s.get('findings'),
           f"exit {code}; {[f['detail'] for f in s.get('findings', [])][:3]}")
    record('make_film: silent deliverable has no audio stream and exactly 90 frames (3.000 s)',
           frames == 90 and samples is None, f'{frames} frames; audio {samples}')
    report = Path(j('make-out', 'silent', 'deliver', 'delivery-report.md'))
    text = report.read_text(encoding='utf-8') if report.is_file() else ''
    record('make_film: silent report says unwatched and audio intentionally absent, nothing posted',
           '**unwatched**' in text and 'audio intentionally absent' in text and 'unheard' not in text
           and 'Nothing has been posted' in text and 'WEAKEST POINT' in text)

    # 4. A draft soundtrack in two aspect ratios: audio exactly as long as the picture, labelled draft.
    code, out = tool('make_film.py', clean, '--sizes', '320x180,180x320', '--samples', 2,
                     '--out', j('make-out', 'draft'), '--json', j('make-draft.json'))
    d = load(j('make-draft.json'))
    record('make_film: draft run in two aspect ratios exits 0', code == 0 and d.get('sound') == 'draft',
           f"exit {code}; {[f['check'] + ': ' + f['detail'] for f in d.get('findings', [])][:4]}")
    for name in ('clean_320x180.mp4', 'clean_180x320.mp4'):
        path = Path(j('make-out', 'draft', 'deliver', name))
        frames, samples = lengths(path) if path.is_file() else (0, None)
        record(f'make_film: {name} audio length equals picture length exactly (90 frames, 144000 samples)',
               frames == 90 and samples == 144000, f'{frames} frames; {samples} samples at 48 kHz')
        manifest = load(str(path) + '.manifest.json')
        record(f'make_film: {name} manifest hash matches the file and says unheard (draft)',
               bool(manifest) and path.is_file() and manifest.get('sha256') == __import__('hashlib').sha256(
                   path.read_bytes()).hexdigest() and 'draft' in manifest.get('status', {}).get('sound', ''))
    palette = load(j('make-films', 'clean', 'audio', 'draft', 'palette-film.json'))
    music = palette.get('music', {})
    record('make_film: draft temp track placed on the film beat grid and stopped at info.music.stop',
           music.get('at_s') == 0 and music.get('offset_s') == 0 and music.get('stop_s') == 2.9 and 'draft' in palette,
           str({k: music.get(k) for k in ('at_s', 'offset_s', 'stop_s')}))
    text = Path(j('make-out', 'draft', 'deliver', 'delivery-report.md')).read_text(encoding='utf-8') \
        if Path(j('make-out', 'draft', 'deliver', 'delivery-report.md')).is_file() else ''
    record('make_film: draft report says unwatched, unheard and draft; weakest point left marked',
           text.count('**unwatched**') >= 3 and '**unheard** (draft soundtrack' in text and 'WEAKEST POINT' in text
           and 'Nothing has been posted' in text)
    listed = sorted(p.name for p in Path(j('make-out', 'draft', 'deliver')).iterdir()) \
        if Path(j('make-out', 'draft', 'deliver')).is_dir() else []
    record('make_film: deliver/ holds only deliverables, manifests, captions and the report',
           listed == ['clean.srt', 'clean.vtt', 'clean_180x320.mp4', 'clean_180x320.mp4.manifest.json',
                      'clean_320x180.mp4', 'clean_320x180.mp4.manifest.json', 'delivery-report.md'], str(listed))

    # 5. --resume skips finished renders: no new render file, the old one untouched.
    renders = Path(j('make-out', 'draft', 'renders'))
    before = {p.name: p.stat().st_mtime_ns for p in renders.iterdir()} if renders.is_dir() else {}
    code, out = tool('make_film.py', clean, '--sizes', '320x180,180x320', '--samples', 2,
                     '--out', j('make-out', 'draft'), '--resume', '--json', j('make-resume.json'))
    r = load(j('make-resume.json'))
    after = {p.name: p.stat().st_mtime_ns for p in renders.iterdir()} if renders.is_dir() else {}
    record('make_film: --resume skips both finished renders and leaves them untouched',
           code == 0 and {'render 320x180', 'render 180x320'} <= set(r.get('resumed', [])) and before == after
           and len(before) == 4, f"exit {code}; resumed {r.get('resumed')}")
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--samples', 2, '--preview',
                     '--out', j('make-out', 'draft'), '--resume', '--json', j('make-resume-2.json'))
    r = load(j('make-resume-2.json'))
    record('make_film: --resume re-renders when a setting changes, without overwriting',
           code == 0 and 'render 320x180' not in r.get('resumed', []) and
           all(Path(renders, n).stat().st_mtime_ns == t for n, t in before.items()) and
           (renders / 'clean_320x180-preview.mp4').is_file(), f"exit {code}")

    # 6. A declared cut that never happens, and a big change nobody declared: exit 1, both listed.
    missing = film('missing', [1.5, 2.2], flip=.6)
    code, out = tool('make_film.py', missing, '--sizes', '320x180', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'missing'), '--json', j('make-missing.json'))
    m = load(j('make-missing.json'))
    details = ' | '.join(f['detail'] for f in m.get('findings', []))
    record('make_film: a declared cut missing from the render is reported; exit 1',
           code == 1 and 'declared cut 2.200 s not found' in details, f'exit {code}; {details[:200]}')
    record('make_film: an undeclared large change is reported', 'undeclared large change at 0.600 s' in details,
           details[:200])
    record('make_film: the cut that is there is found', 'declared cut 1.500' not in details)

    # 7. One timeline means one cue list: sizes that export different cues stop the run; exit 1.
    split = film('split', [1.5], cue_shift=.1)
    code, out = tool('make_film.py', split, '--sizes', '320x180,180x320', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'split'))
    record('make_film: different cue lists across sizes stop the run before rendering; exit 1',
           code == 1 and 'different cue lists' in out and not Path(j('make-out', 'split', 'renders')).exists(),
           f'exit {code}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--scripts', required=True)
    p.add_argument('--keep', required=True)
    p.add_argument('--playwright', help='sets LF_PLAYWRIGHT_MODULE for the runs')
    a = p.parse_args()
    if a.playwright:
        os.environ['LF_PLAYWRIGHT_MODULE'] = str(Path(a.playwright).resolve())
    root = Path(a.keep).resolve()
    root.mkdir(parents=True, exist_ok=True)
    scripts = Path(a.scripts).resolve()
    results = []

    def record(name, ok, detail=''):
        results.append({'name': name, 'ok': bool(ok), 'detail': detail})
        print(('PASS' if ok else 'FAIL') + '  ' + name + (f' [{detail}]' if detail else ''), flush=True)

    def tool(script, *args):
        r = subprocess.run([sys.executable, '-I', '-B', str(scripts / script), *map(str, args)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        return r.returncode, r.stdout + r.stderr
    try:
        run_make_cases(tool, record, lambda *parts: str(root.joinpath(*parts)), scripts)
    except Exception as exc:
        record('make cases ran to the end', False, repr(exc)[:300])
    (root / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    passed = sum(r['ok'] for r in results)
    print(f'{passed}/{len(results)} checks passed.')
    return 0 if passed == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
