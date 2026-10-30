#!/usr/bin/env python3
"""Known-answer cases for make_film.py, standalone or called from selftest.py.

Integration: add 'make' to CASE_MODULES in selftest.py; it calls
run_make_cases(tool, record, j, HERE). The runner uses the existing tool(), record() and j().

  python make.py --scripts skills/legible-film/scripts --keep work/make-cases
  python make.py --scripts scripts --keep work/make-cases --playwright node_modules/playwright-core

Builds tiny original __lf pages (320x180 and 180x320, 30 fps, 3 s) and runs make_film.py
end to end: the doctor finding a missing tool, a silent and a draft-sound run whose audio
and picture lengths match exactly, a declared cut that is not in the picture, sizes that
export different cue lists or cuts (stopped) or different reading rests (reported, not
failed), info.seams and info.changes, --resume skipping a finished render, and the exit
codes; and the sound chain (spotting with sound-edits.json, the social master refused on a
sparse film, a hybrid library palette with its listening pair, sound_check.py warnings as
findings), and --resume in a copied output folder (every step runs again; nothing is written into
the original). It also builds 1440-frame 1920x1080 and 1080x1920 films with FFmpeg (no browser)
and makes a dozen cut sheets on each, one bounded frame_sheet.py call per cut. A small kit film
(new_film.py) proves film_check.py's blank-node and loop-seam errors and make_film.py's --loop,
--web (VP9 WebM from a lossless render, poster from frame 0, its own seam measured) and --res (the
output short side, odd sides refused). Small kit films reproduce review findings: a flashing
tracked panel the flash prediction must see (and an SVG it cannot model, reported as incomplete), a
square turned 90 degrees at a loop seam, transparent and alpha-zero fills that paint nothing, and
large-text contrast judged at the delivered size under --res.
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
const portrait=width<height, shift=(P.cueShift&&portrait)?P.cueShift:0;
window.__lf={
  ready:document.fonts.ready,
  info:()=>({title:'make_film synthetic film',width,height,fps:30,duration:3,frames:90,
    beat:{bpm:120,offset:0},cuts:P.cuts.map(c=>c+(portrait&&P.cutShift?P.cutShift:0)),smears:[],fast:[],
    rests:[[portrait?2.55:2.6,3,'end hold']],flashes:[],
    ...(P.seams?{seams:P.seams}:{}),...(P.changes?{changes:P.changes}:{}),
    music:{stop:2.9},pace:{max_still_share:.9,max_still:2},
    cues:[{id:'swing',t:.8,role:'whoosh',sound:'required',sync:'apex',tolerance_ms:25,picture:'the bar passes centre'},
          {id:'cut',t:1.5+shift,role:'impact',sound:'required',sync:'attack',tolerance_ms:17,picture:'the light shot arrives'}]
          .concat(P.extraCues||[]),
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

# A kit film for the loop, --web and --res cases: six dots turn once around the centre in 2 s; the
# camera holds. Variants break it on purpose: a seam that does not close, dots with no size, dots with
# a size but nothing to draw.
ORBIT = """export default function film(kit) {
  const { block } = kit;
  const Orbit = block('orbit', (ctx, o) => {
    ctx.ground(ctx.t0, ctx.colour('ink'));
    const len = ctx.time(o.len), r = ctx.u * 22, n = 6;
    const dots = Array.from({ length: n }, (_, i) => {
      const d = ctx.group.add(__ADD__)__FILL__;
      d.el.style.borderRadius = '50%';
      return ctx.track(d, `dot-${i + 1}`);
    });
    function update(t) {
      const p = (t - ctx.t0) / len;
      dots.forEach((d, i) => {
        const a = __ANGLE__;
        d.x = r * Math.cos(a); d.y = r * Math.sin(a);
      });
    }
    return { len, update, camera: () => ({ drift: false }) };
  });
  return { title: 'Orbit', size: [240, 240], fps: 30, loop: true, brand: '#3D7BFF', scenes: [Orbit({ len: 2 })] };
}
"""
ORBIT_PARTS = {
    'add': '{ name: `dot-${i + 1}`, w: ctx.u * 6, h: ctx.u * 6 }',
    'fill': '.rest({ fill: ctx.pal.accent })',
    'angle': '2 * Math.PI * (i / n + p)',
}


# The same project with a film written in 1.2.0's vocabulary.
LEGACY = """export default function film(kit) {
  const { Words } = kit;
  return { title: 'Old names', size: [240, 240], fps: 30, pace: { maxStill: 2, maxStillShare: 0.9 }, scenes: [
    Words({ shots: [{ text: 'OLD', style: 'slam', hit: 'punch', dur: 0.8 },
                    { text: 'NAMES', style: 'cut', dur: 0.8 }] }),
    Words({ enter: 'whipY', shots: [{ text: 'STILL RUN', hit: 'beat', dur: 1.2 }] }),
  ] };
}
"""


# A tracked white panel over black whose opacity flips eight times a second: the flash prediction must
# draw it. __BODY__ swaps the fill for an SVG inside the node, which the prediction cannot model.
FLASH = """export default function film(kit) {
  const Flash = kit.block('flash', ctx => {
    ctx.ground(ctx.t0, '#000000');
    const panel = ctx.track(ctx.group.add({ name: 'panel', w: ctx.W, h: ctx.H }), 'panel');
    __BODY__
    return { len: 2, camera: () => ({ drift: false }), update(t) { panel.opacity = Math.floor(t * 8) % 2 ? 0 : 1; } };
  });
  return { title: 'Flash', size: [240, 240], fps: 20, scenes: [Flash({ len: 2 })] };
}
"""
FLASH_SVG = ("panel.el.innerHTML = `<svg width=\"${ctx.W}\" height=\"${ctx.H}\">"
             "<rect width=\"${ctx.W}\" height=\"${ctx.H}\" fill=\"#ffffff\"/></svg>`;")

# A loop whose square, with a red top edge, turns __TURN__ degrees over its one second.
ROTATE = """export default function film(kit) {
  const Shape = kit.block('shape', ctx => {
    ctx.ground(ctx.t0, '#000000');
    const n = ctx.track(ctx.group.add({ name: 'shape', w: 60, h: 60 }).rest({ fill: '#ffffff' }), 'shape');
    n.el.style.borderTop = '12px solid red'; n.el.style.boxSizing = 'border-box';
    return { len: 1, camera: () => ({ drift: false }), update(t) { n.rot = __TURN__ * t; } };
  });
  return { title: 'Rotate', size: [240, 240], fps: 10, loop: true, scenes: [Shape({ len: 1 })] };
}
"""

# A tracked node whose only paint is __FILL__; __CHILD__ may give it a visible child.
BLANK = """export default function film(kit) {
  const Blank = kit.block('blank', ctx => {
    ctx.ground(ctx.t0, '#000000');
    const n = ctx.track(ctx.group.add({ name: 'blank', w: 80, h: 80 }).rest({ fill: '__FILL__' }), 'blank');
    __CHILD__
    return { len: 1, camera: () => ({ drift: false }), update() {} };
  });
  return { title: 'Blank', size: [240, 240], fps: 10, scenes: [Blank({ len: 1 })] };
}
"""

# 24 CSS px type at 3.66:1 on black: large text (3:1 needed) at 480x270, small (4.5:1) at --res 135.
LOW = """export default function film(kit) {
  const Low = kit.block('low', ctx => {
    ctx.ground(ctx.t0, '#000000');
    const word = ctx.textNode(ctx.group, { string: 'LOW', size: 24, weight: 400, color: '#666666' });
    ctx.text({ id: 'low', role: 'headline', string: 'LOW', nodes: [word], bg: () => '#000000' });
    return { len: 2, camera: () => ({ drift: false }), update() {} };
  });
  return { title: 'Low', size: [480, 270], fps: 10, scenes: [Low({ len: 2 })] };
}
"""


def orbit(**change):
    """The orbit film's source with any of its parts replaced."""
    parts = dict(ORBIT_PARTS, **change)
    return (ORBIT.replace('__ADD__', parts['add']).replace('__FILL__', parts['fill'])
            .replace('__ANGLE__', parts['angle']))


def run_kit_cases(tool, record, j, load, lengths):
    """Blank tracked nodes and loop seams in film_check.py; --loop, --web and --res in make_film.py."""
    folder = j('make-films', 'orbit')
    code, out = tool('new_film.py', folder)
    film_js = Path(folder, 'film.js')
    if code not in (0, 1) or not film_js.is_file():
        record('kit cases: new_film.py makes a project', False, out[-200:])
        return

    def check(source, *args):
        film_js.write_text(source, encoding='utf-8')
        return tool('film_check.py', folder, *(args or ('--size', '240x240')))

    code, out = check(orbit())
    record('film_check: a loop whose tracked properties return to frame 0 passes and says the seam closes',
           code == 0 and 'loop: the seam closes' in out, f'exit {code}')
    code, out = check(orbit(angle='2 * Math.PI * (i + p) / n'))
    record('film_check: a loop seam that does not close is an error naming the elements; exit 1',
           code == 1 and 'loop: the seam does not close' in out and '"dot-1" box moved' in out, f'exit {code}')
    code, out = check(orbit(add='{ name: `dot-${i + 1}` }'))
    record('film_check: a tracked node with no size is an error naming the node and the block; exit 1',
           code == 1 and 'blank: tracked node "dot-1" (orbit, scene 1) is never visible: it has no size' in out,
           f'exit {code}')
    code, out = check(orbit(fill=''))
    record('film_check: a sized tracked node with nothing to draw is an error naming the node and the block',
           code == 1 and 'blank: tracked node "dot-1" (orbit, scene 1) paints nothing' in out, f'exit {code}')
    # A film written against 1.2.0's names still builds, with today's names in what it exports.
    code, out = check(LEGACY)
    declared = load(Path(folder, 'qa', 'declared.json'))
    roles = {e.get('role') for e in load(Path(folder, 'cues.json')).get('events', [])}
    labels = ' '.join(str(c[2]) for c in declared.get('change_windows', []))
    record('film_check: 1.2.0 names (Words, slam, punch, whipY) still run as Type, land, burst, whip-v',
           code == 0 and 'impact' in roles and 'burst' in labels and declared.get('pace', {}).get('max_still') == 2,
           f'exit {code}; roles {sorted(map(str, roles))}; {labels[:80]}')

    # Review finding 2: a tracked panel flashing over the ground is in the prediction; an SVG it cannot draw
    # makes the prediction say it is incomplete instead of reading as a clean zero.
    code, out = check(FLASH.replace('__BODY__', "panel.rest({ fill: '#ffffff' });"))
    record('film_check: a tracked full-frame panel flipping 8 times a second is predicted as flashing; exit 1',
           code == 1 and 'ERROR flash: ' in out and 'more than 3 flashes' in out and 'INCOMPLETE' not in out,
           next((x.strip() for x in out.splitlines() if 'flash prediction' in x), f'exit {code}'))
    code, out = check(FLASH.replace('__BODY__', FLASH_SVG))
    record('film_check: a tracked SVG the prediction cannot draw marks the flash prediction incomplete',
           'INCOMPLETE: 1 tracked node(s)' in out and 'the prediction is incomplete' in out and '"panel": an SVG' in out
           and 'paints nothing' not in out,
           next((x.strip() for x in out.splitlines() if 'flash prediction' in x), f'exit {code}'))
    # Review finding 3: a square turned 90 degrees fills the same box; the seam check compares its corners.
    code, out = check(ROTATE.replace('__TURN__', '90'))
    record('film_check: a loop whose square ends turned 90 degrees does not close; exit 1',
           code == 1 and '"shape" orientation: turned 90.0 deg' in out, f'exit {code}')
    code, out = check(ROTATE.replace('__TURN__', '360'))
    record('film_check: a loop whose square turns one whole revolution closes', code == 0 and 'the seam closes' in out,
           f'exit {code}')
    # Review finding 5: a transparent or alpha-zero fill is not paint; a visible filled child is.
    for fill in ('transparent', 'rgba(255, 255, 255, 0)'):
        code, out = check(BLANK.replace('__FILL__', fill).replace('__CHILD__', ''))
        record(f'film_check: a tracked node whose only fill is {fill} paints nothing; exit 1',
               code == 1 and 'blank: tracked node "blank" (blank, scene 1) paints nothing' in out, f'exit {code}')
    code, out = check(BLANK.replace('__FILL__', 'transparent').replace(
        '__CHILD__', "n.add({ w: 40, h: 40 }).rest({ fill: '#ffffff' });"))
    record('film_check: a transparent tracked node with a visible filled child paints',
           code == 0 and 'blank:' not in out, f'exit {code}')
    # Review finding 6: with --res the large-text rule is judged on the delivered raster, the layout kept.
    code, out = check(LOW, '--size', '480x270')
    record('film_check: 24 px type at 3.66:1 passes as large text at its CSS size',
           code == 0 and 'contrast:' not in out, f'exit {code}')
    code, out = check(LOW, '--size', '480x270', '--res', 135)
    reading = load(Path(folder, 'reading.json'))
    row = next(iter(reading.get('texts', [])), {})
    record('film_check: --res 135 judges the same type at 12 delivered px, where it needs 4.5:1; exit 1',
           code == 1 and 'needs 4.5:1 at 12 px in the 240x135 delivered raster' in out and 'delivered 240x135' in out
           and row.get('min_font_px') == 24 and row.get('min_output_px') == 12 and reading.get('size') == '480x270',
           f"exit {code}; {row.get('min_font_px')} -> {row.get('min_output_px')} px")
    film_js.write_text(orbit(), encoding='utf-8')

    # --res is the output short side; an odd side is refused before anything runs, with a --res that works.
    code, out = tool('make_film.py', folder, '--sizes', '1280x720', '--res', 721, '--sound', 'none')
    record('make_film: --res giving an odd side is refused with the nearest even --res; exit 2',
           code == 2 and 'gives 1282x721: H.264 4:2:0 needs even sides; --res 720 gives 1280x720' in out,
           f'exit {code}; {out.strip().splitlines()[-1:] if out.strip() else ""}')

    # The loop film: info.loop turns the seam check on; --web adds a WebM and a poster; --res 120 halves 240.
    out_dir = j('make-out', 'orbit')
    code, out = tool('make_film.py', folder, '--sizes', '240x240', '--res', 120, '--web', '--preview',
                     '--sound', 'none', '--out', out_dir, '--json', j('make-orbit.json'))
    s = load(j('make-orbit.json'))
    deliver = Path(out_dir, 'deliver')
    listed = sorted(p.name for p in deliver.iterdir()) if deliver.is_dir() else []
    record('make_film: a loop film with --web --res 120 exits 0 with every check passing',
           code == 0 and not s.get('findings'), f"exit {code}; {[f['detail'] for f in s.get('findings', [])][:3]}")
    record('make_film: --res 120 makes 120x120 from 240x240 and the manifest records the real size',
           'orbit_120x120.mp4' in listed and load(str(deliver / 'orbit_120x120.mp4') + '.manifest.json')
           .get('settings', {}).get('output_size') == '120x120' and lengths(deliver / 'orbit_120x120.mp4')[0] == 60,
           str(listed))
    motion = load(j('make-out', 'orbit', 'qa', '240x240', 'motion.json'))
    report_md = deliver / 'delivery-report.md'
    report = report_md.read_text(encoding='utf-8') if report_md.is_file() else ''
    record('make_film: info.loop runs motion_scan.py --loop and reports the seam',
           (motion.get('loop_seam') or {}).get('pass') is True and 'loop seam: step' in report
           and 'loop: the seam is measured' in out, str(motion.get('loop_seam')))
    web = load(str(deliver / 'orbit_120x120.webm') + '.manifest.json').get('checks', {})
    record('make_film: --web delivers a VP9 WebM from the lossless render (60 frames, BT.709 tags, no audio) and a '
           'poster matching its frame 0',
           {'orbit_120x120.webm', 'orbit_120x120-poster.png'} <= set(listed) and web.get('codec') == 'vp9'
           and web.get('frames') == 60 and web.get('tags') == ['bt709'] * 3 and web.get('audio') == 'none'
           and web.get('frame0_vs_poster_mean_abs') is not None and web['frame0_vs_poster_mean_abs'] <= 3
           and list(Path(out_dir, 'renders').glob('orbit_120x120-preview.mkv')), str(web))
    # Review finding 4: the WebM's own seam is measured (motion_scan.py --loop on the WebM) and reported.
    seam = load(j('make-out', 'orbit', 'qa', '240x240', 'motion-webm.json')).get('loop_seam') or {}
    log = Path(out_dir, 'logs', 'motion_scan_webm-240x240.log')
    record('make_film: --web --loop runs motion_scan.py --loop on the WebM and carries its seam into the manifest '
           'and the report',
           seam.get('pass') is True and log.is_file() and 'orbit_120x120.webm' in log.read_text(encoding='utf-8')
           and web.get('loop_seam') == 'pass' and 'orbit_120x120.webm: loop seam: step' in report
           and 'loop seam pass' in report, str(seam))
    # Review finding 6: the preflight is judged at the delivered size, its layout at the CSS size.
    pre = load(j('make-out', 'orbit', 'qa', '240x240', 'preflight.json'))
    record('make_film: with --res the preflight runs at the CSS size and judges type at the delivered size',
           pre.get('size') == '240x240' and pre.get('output_size') == '120x120', str(pre.get('output_size')))


def run_make_cases(tool, record, j, scripts_dir):
    scripts_dir = Path(scripts_dir)

    def load(path):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def film(name, cuts, flip=None, cue_shift=0, cut_shift=0, seams=None, changes=None, extra_cues=None):
        folder = Path(j('make-films', name))
        folder.mkdir(parents=True, exist_ok=True)
        params = json.dumps({'cuts': cuts, 'flip': flip, 'cueShift': cue_shift, 'cutShift': cut_shift,
                             'seams': seams, 'changes': changes, 'extraCues': extra_cues or []})
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

    def video_hash(path):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-c:v', 'copy',
                                 '-f', 'hash', '-hash', 'sha256', '-'], capture_output=True, text=True)
        return result.stdout.strip() if result.returncode == 0 else None

    old_hash = video_hash(deliverable)
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--sound', 'draft', '--master', 'broadcast',
                     '--preview',
                     '--out', j('make-out', 'silent'), '--sound-only', '--json', j('make-sound-only.json'))
    revised = Path(j('make-out', 'silent', 'deliver', 'clean_320x180-2.mp4'))
    manifest = load(str(revised) + '.manifest.json')
    record('make_film: sound-only copies the encoded picture and versions the delivery',
           code == 0 and old_hash and old_hash == video_hash(revised) and deliverable.is_file()
           and manifest.get('sources', {}).get('picture_reused') is True, out[-300:])
    page = clean / 'index.html'
    original = page.read_bytes()
    try:
        page.write_bytes(original.replace(b"id:'swing',t:.8", b"id:'swing',t:.9"))
        code, out = tool('make_film.py', clean, '--sizes', '320x180', '--sound', 'draft', '--preview',
                         '--out', j('make-out', 'silent'), '--sound-only')
        record('make_film: sound-only refuses a changed cue source',
               code == 2 and 'picture source hash changed' in out, out[-300:])
        state = load(j('make-out', 'silent', 'make-state.json'))
        record('make_film: a refused sound-only run keeps the earlier render steps in make-state.json',
               'render 320x180' in state.get('steps', {}), sorted(state.get('steps', {}))[:6])
    finally:
        page.write_bytes(original)
    # Like --resume, --sound-only trusts only records written in its own output folder: a copy's records name the
    # original's renders, so the copy refuses and the original is left as it was.
    import shutil
    silent_copy = Path(j('make-out', 'silent-copy'))
    shutil.rmtree(silent_copy, ignore_errors=True)
    shutil.copytree(j('make-out', 'silent'), silent_copy)
    before = sorted(p.name for p in Path(j('make-out', 'silent', 'deliver')).iterdir())
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--sound', 'draft', '--preview',
                     '--out', silent_copy, '--sound-only')
    after = sorted(p.name for p in Path(j('make-out', 'silent', 'deliver')).iterdir())
    record('make_film: sound-only in a copied output folder refuses instead of reusing the original renders',
           code == 2 and 'copied or moved folder' in out and before == after, out[-300:])
    import importlib.util
    spec_mf = importlib.util.spec_from_file_location('lf_make_film_cues', os.path.join(scripts_dir, 'make_film.py'))
    mf = importlib.util.module_from_spec(spec_mf)
    spec_mf.loader.exec_module(mf)
    base_cues = {'fps': 30, 'exported_from': 'film_check.py at 320x180',
                 'events': [{'id': 'a', 't': 1.0, 'sound': 'required'}]}
    for name, data in (('cues-a.json', base_cues), ('cues-b.json', dict(base_cues, exported_from='at 180x320')),
                       ('cues-c.json', dict(base_cues, events=[{'id': 'a', 't': 1.1, 'sound': 'required'}]))):
        Path(j(name)).write_text(json.dumps(data), encoding='utf-8')
    record('make_film: sound-only compares cue content, not the note of which size exported it',
           mf.cue_digest(Path(j('cues-a.json'))) == mf.cue_digest(Path(j('cues-b.json')))
           and mf.cue_digest(Path(j('cues-a.json'))) != mf.cue_digest(Path(j('cues-c.json'))))

    pace_film = film('pace-miss', [1.5])
    pace_page = pace_film / 'index.html'
    pace_html = pace_page.read_text(encoding='utf-8').replace('max_still_share:.9', 'max_still_share:.001')
    pace_html = pace_html.replace('(10+t*90)', '(10+Math.min(t,.6)*90)')
    pace_page.write_text(pace_html, encoding='utf-8')
    code, out = tool('make_film.py', pace_film, '--sizes', '320x180', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'pace-miss'), '--json', j('make-pace.json'))
    pace_report = Path(j('make-out', 'pace-miss', 'deliver', 'delivery-report.md'))
    pace_text = pace_report.read_text(encoding='utf-8') if pace_report.is_file() else ''
    record('make_film: pace miss is a taste note and does not fail',
           code == 0 and 'Taste checks (numbers to look and listen at' in pace_text
           and 'pace max_still_share: measured' in pace_text, out[-300:])

    # 4. A draft soundtrack in two aspect ratios: audio exactly as long as the picture, labelled draft.
    code, out = tool('make_film.py', clean, '--sizes', '320x180,180x320', '--samples', 2, '--master', 'broadcast',
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
    record('make_film: reading rests that differ by size are reported per size, not failed',
           'rests differ from 320x180' in text and not any(f['check'] == 'one timeline' for f in d.get('findings', [])),
           next((x.strip() for x in text.splitlines() if 'rests differ' in x), 'no per-size line'))
    record('make_film: one sheet per declared cut', bool(list(Path(j('make-out', 'draft', 'qa', '320x180')).glob(
        'joins-01-1.500s.png'))))
    record('make_film: master numbers reported (broadcast -23 LUFS, gain reduction, true peak after AAC re-encode)',
           'Master (`mix_cues.py`): preset broadcast, integrated -23.0 LUFS (target -23.0), largest gain reduction' in text
           and 'after an AAC 128 kbps re-encode -' in text,
           next((x.strip() for x in text.splitlines() if 'Master (`mix_cues.py`)' in x), 'no master line')[:200])
    record('make_film: sound_check.py runs on every size with the spotted cue list',
           all(Path(j('make-out', 'draft', 'qa', size, 'sound-check.json')).is_file() for size in ('320x180', '180x320'))
           and text.count('`sound_check.py` ') == 2 and Path(j('make-out', 'draft', 'qa', 'spotting.csv')).is_file())
    record('make_film: deliver/ holds only deliverables, manifests, captions and the report',
           listed == ['clean.srt', 'clean.vtt', 'clean_180x320.mp4', 'clean_180x320.mp4.manifest.json',
                      'clean_320x180.mp4', 'clean_320x180.mp4.manifest.json', 'delivery-report.md'], str(listed))

    # 5. --resume skips finished renders: no new render file, the old one untouched.
    renders = Path(j('make-out', 'draft', 'renders'))
    before = {p.name: p.stat().st_mtime_ns for p in renders.iterdir()} if renders.is_dir() else {}
    code, out = tool('make_film.py', clean, '--sizes', '320x180,180x320', '--samples', 2, '--master', 'broadcast',
                     '--out', j('make-out', 'draft'), '--resume', '--json', j('make-resume.json'))
    r = load(j('make-resume.json'))
    after = {p.name: p.stat().st_mtime_ns for p in renders.iterdir()} if renders.is_dir() else {}
    record('make_film: --resume skips both finished renders and leaves them untouched',
           code == 0 and {'render 320x180', 'render 180x320'} <= set(r.get('resumed', [])) and before == after
           and len(before) == 4, f"exit {code}; resumed {r.get('resumed')}")
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--samples', 2, '--preview', '--master', 'broadcast',
                     '--out', j('make-out', 'draft'), '--resume', '--json', j('make-resume-2.json'))
    r = load(j('make-resume-2.json'))
    record('make_film: --resume re-renders when a setting changes, without overwriting',
           code == 0 and 'render 320x180' not in r.get('resumed', []) and
           all(Path(renders, n).stat().st_mtime_ns == t for n, t in before.items()) and
           (renders / 'clean_320x180-preview.mp4').is_file(), f"exit {code}")

    # 5b. What a change reruns. A picture-only edit (the cue list unchanged) re-renders both sizes and reuses the
    #     sound; a new master remixes and re-muxes and reuses both renders.
    base = ('--sizes', '320x180,180x320', '--samples', 2, '--out', j('make-out', 'draft'), '--resume')
    tool('make_film.py', clean, *base, '--master', 'broadcast')
    page = clean / 'index.html'
    original_page = page.read_bytes()
    try:
        page.write_bytes(original_page + b'<!-- a picture-only edit: the timeline and its cues are unchanged -->')
        code, out = tool('make_film.py', clean, *base, '--master', 'broadcast', '--json', j('make-resume-edit.json'))
        resumed = set(load(j('make-resume-edit.json')).get('resumed', []))
        record('make_film: --resume after a picture-only edit re-renders both sizes and reuses the sound',
               code == 0 and not {'render 320x180', 'render 180x320'} & resumed
               and {'spotting', 'sound kit', 'sound'} <= resumed, f'exit {code}; resumed {sorted(resumed)}')
        code, out = tool('make_film.py', clean, *base, '--master', 'web', '--json', j('make-resume-master.json'))
        resumed = set(load(j('make-resume-master.json')).get('resumed', []))
        record('make_film: --resume with a new master remixes and re-muxes, reusing both renders',
               code in (0, 1) and {'render 320x180', 'render 180x320'} <= resumed
               and not {'sound', 'mux 320x180', 'mux 180x320'} & resumed, f'exit {code}; resumed {sorted(resumed)}')
    finally:
        page.write_bytes(original_page)

    # 5c. A tool upgrade reruns the steps that use the tool and nothing else (in process, with stand-in outputs).
    import importlib.util
    from types import SimpleNamespace
    spec_env = importlib.util.spec_from_file_location('lf_make_film_env', os.path.join(scripts_dir, 'make_film.py'))
    make_env = importlib.util.module_from_spec(spec_env)
    spec_env.loader.exec_module(make_env)
    env_out = Path(j('make-env'))
    shutil.rmtree(env_out, ignore_errors=True)
    built = env_out / 'renders' / 'stand-in.bin'
    built.parent.mkdir(parents=True)
    built.write_bytes(b'stand-in output')
    runs = []

    def env_run(resume, versions):
        """One make over two steps, a render (FFmpeg and the browser) and spotting (Python only)."""
        a = SimpleNamespace(name=None, res=None, loop=False, web=False, resume=resume, ffmpeg=None, ffprobe=None,
                            node=None, playwright=None, browser=None, drop_beat=None)
        m = make_env.Make(a, clean, env_out, [(320, 180)])
        m.versions = versions
        runs.clear()
        for name in ('render 320x180', 'spotting'):
            m.step(name, {'source': 'unchanged'}, lambda name=name: (runs.append(name) or {'path': str(built)},
                                                                     [built]))
        return list(runs)
    first = {'FFmpeg': 'ffmpeg version 9.0.2', 'ffprobe': 'ffprobe version 9.0.2', 'Node': 'v24.20.0',
             'Playwright': '1.60.0', 'Chromium': 'chromium-1200'}
    upgraded = dict(first, FFmpeg='ffmpeg version 9.1')
    ran = [env_run(False, first), env_run(True, first), env_run(True, upgraded),
           env_run(True, dict(upgraded, ffprobe='ffprobe version 9.1'))]
    record('make_film: an FFmpeg or ffprobe upgrade reruns the render and reuses a step that uses neither',
           ran == [['render 320x180', 'spotting'], [], ['render 320x180'], ['render 320x180']], str(ran))
    record('make_film: the doctor rows give each tool its build, Chromium by path, size and time',
           make_env.environment_versions([{'name': 'FFmpeg', 'ok': True, 'detail': 'ffmpeg version 9.0.2'},
                                          {'name': 'Node', 'ok': False, 'detail': 'missing'},
                                          {'name': 'Chromium', 'ok': True,
                                           'detail': f'{built} (found, not launched)'}])
           == {'FFmpeg': 'ffmpeg version 9.0.2',
               'Chromium': f'{built} ({built.stat().st_size} bytes, modified {built.stat().st_mtime_ns})'}
           and make_env.step_tools('qc 180x320') == ('FFmpeg', 'ffprobe') and make_env.step_tools('sound kit') == ())

    # 5a. Review finding 1: --resume in a copy of an output folder must not trust the original's paths. The copy
    #     loses its deliverable; resuming there rebuilds it in the copy and never writes into the original.
    import hashlib
    import shutil
    original, copy = Path(j('make-out', 'silent')), Path(j('make-out', 'silent-copy'))
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(original, copy)
    (copy / 'deliver' / 'clean_320x180.mp4').unlink()

    def digests(folder):
        return {str(x.relative_to(folder)): hashlib.sha256(x.read_bytes()).hexdigest()
                for x in sorted(folder.rglob('*')) if x.is_file()}
    before = digests(original)
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--sound', 'none', '--preview',
                     '--out', copy, '--resume', '--json', j('make-copy-resume.json'))
    r = load(j('make-copy-resume.json'))
    state = load(copy / 'make-state.json')
    made = copy / 'deliver' / 'clean_320x180.mp4'
    manifest = load(str(made) + '.manifest.json')
    record('make_film: --resume in a copied output folder runs every step again and delivers into the copy',
           code == 0 and made.is_file() and manifest.get('sha256') == hashlib.sha256(made.read_bytes()).hexdigest()
           and not r.get('resumed') and 'every step runs again' in out
           and state.get('root') == str(copy.resolve()) and str(copy.resolve()) in out,
           f"exit {code}; resumed {r.get('resumed')}; {next((x for x in out.splitlines() if 'delivered' in x), '')}")
    record('make_film: --resume in the copy leaves the original output folder byte for byte',
           digests(original) == before, f'{len(before)} files')
    record('make_film: the state records outputs relative to the output folder',
           all(not Path(k).is_absolute() for st in state.get('steps', {}).values() for k in st.get('outputs', {})),
           str(sorted(state.get('steps', {}).get('mux 320x180', {}).get('outputs', {}))))
    made.unlink()
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--sound', 'none', '--preview',
                     '--out', copy, '--resume', '--json', j('make-copy-resume-2.json'))
    r = load(j('make-copy-resume-2.json'))
    record('make_film: --resume in the same folder keeps the render and rebuilds only the missing deliverable',
           code == 0 and made.is_file() and 'render 320x180' in r.get('resumed', [])
           and 'mux 320x180' not in r.get('resumed', []), f"exit {code}; resumed {r.get('resumed')}")

    # 5b. Spotting: clustered and repeated cues are merged and thinned; sound-edits.json drops one, applied last.
    #     The default social master on a sparse 3 s film cannot reach -14 LUFS within the limiter cap: it
    #     masters as loud as is safe and the report says how far short it lands.
    spotted = film('spotted', [1.5], extra_cues=[
        {'id': 'cut-tick', 't': 1.52, 'role': 'tick', 'sound': 'required', 'sync': 'attack'},
        {'id': 't1', 't': 2.0, 'role': 'tick', 'sound': 'required', 'sync': 'attack'},
        {'id': 't2', 't': 2.08, 'role': 'tick', 'sound': 'required', 'sync': 'attack'},
        {'id': 't3', 't': 2.16, 'role': 'tick', 'sound': 'required', 'sync': 'attack'}])
    (spotted / 'sound-edits.json').write_text(json.dumps({'swing': 'drop'}), encoding='utf-8')
    code, out = tool('make_film.py', spotted, '--sizes', '320x180', '--preview', '--out', j('make-out', 'spotted'),
                     '--json', j('make-spotted.json'))
    sp = load(j('make-spotted.json'))
    rpt = Path(j('make-out', 'spotted', 'deliver', 'delivery-report.md'))
    text = rpt.read_text(encoding='utf-8') if rpt.is_file() else ''
    mixlog = Path(j('make-out', 'spotted', 'logs', 'sound.log'))
    record('make_film: spotting merges, thins and applies edits; the mix uses cues.spotted.json',
           Path(j('make-out', 'spotted', 'qa', 'spotting.csv')).is_file() and 'cut-tick into cut' in text
           and 't2:' in text and 't3:' in text and 'dropped by edits: swing (edit)' in text
           and mixlog.is_file() and 'cues.spotted.json' in mixlog.read_text(encoding='utf-8'),
           next((x.strip() for x in text.splitlines() if 'merged into gestures' in x), 'no spotting lines')[:200])
    refused = [f for f in sp.get('findings', []) if 'refused' in f['detail']]
    master = load(j('make-out', 'spotted', 'sound', 'mix-report.json')).get('mastering', {})
    short = master.get('short_of_target')
    record('make_film: default social master reaches -14 LUFS, lands short of it AAC-safe and says so, or is refused',
           master.get('preset') == 'social' and (
               (bool(master.get('refused')) and bool(refused) and code == 1) or
               (not master.get('refused') and not short and abs(master.get('target_error_lu', 9)) <= .5
                and master.get('aac_pass')) or
               (not master.get('refused') and bool(short) and master.get('aac_pass')
                and master.get('max_gain_reduction_db', 9) <= 4.0 + 1e-6 and 'short of target by' in text
                and (master.get('shortfall_lu', 0) <= 1.0 or (code == 1 and any(
                    'LU under the social target' in f['detail'] for f in sp.get('findings', [])))))),
           f"exit {code}; refused: {master.get('refused')}; short: {bool(short)}; reached {master.get('reached_lufs')}"
           f" LUFS; largest gain reduction {master.get('max_gain_reduction_db')}")

    # 5c. Hybrid: a licensed library fills the roles it can, the draft the rest and sub/air/bed; one version 2
    #     palette with every role's source and licence; a loudness-matched, randomised listening pair.
    import numpy as np
    rate = 48000
    library = Path(j('make-library'))
    for name, y in (('WHSH_soft', .35 * np.sin(2 * np.pi * 2100 * np.arange(rate) / rate) *
                     np.sin(np.pi * np.arange(rate) / rate) ** 5),):
        folder = library / name
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(rate), '-ac', '2', '-i', '-',
                        '-c:a', 'pcm_s24le', str(folder / (name + '.wav'))],
                       input=np.column_stack((y, y)).astype('<f4').tobytes(), check=True)
        (folder / 'licence.json').write_text(json.dumps({'licence': 'CC0 1.0', 'source_url': 'synthetic:test',
                                                         'attribution': 'Synthetic fixture: ' + name}), encoding='utf-8')
    code, out = tool('make_film.py', clean, '--sizes', '320x180,180x320', '--preview', '--master', 'broadcast',
                     '--sound', 'library:' + str(library), '--out', j('make-out', 'hybrid'), '--json', j('make-hybrid.json'))
    h = load(j('make-hybrid.json'))
    hybrid = load(j('make-out', 'hybrid', 'library', 'palette-hybrid.json'))
    src = hybrid.get('sources', {})
    record('make_film: library:FOLDER is hybrid; exit 0', code == 0 and h.get('sound') == 'hybrid',
           f"exit {code}; {[f['check'] + ': ' + f['detail'] for f in h.get('findings', [])][:3]}")
    record('make_film: hybrid palette v2: whoosh from the library, impact and sub/air/bed synthesised, all licensed',
           hybrid.get('version') == 2 and src.get('whoosh', {}).get('origin') == 'library'
           and src.get('impact', {}).get('origin', '').startswith('draft')
           and all(src.get(r, {}).get('origin', '').startswith('draft') for r in ('sub', 'air', 'bed'))
           and all(s.get('licence') and s.get('attribution') for s in src.values()) and 'bed' in hybrid,
           str({r: src.get(r, {}).get('origin') for r in ('whoosh', 'impact', 'sub', 'air', 'bed')}))
    record('make_film: attribution lines printed', 'sound attribution: Synthetic fixture: WHSH_soft' in out)
    key = load(j('make-out', 'hybrid', 'qa', 'listen-key.json'))
    listen = Path(j('make-out', 'hybrid', 'deliver', 'listen'))
    pair = {k: lengths(listen / f'{k}.mp4') if (listen / f'{k}.mp4').is_file() else (0, None) for k in 'AB'}

    def picture_md5(path):
        r = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-map', '0:v:0', '-c', 'copy',
                            '-f', 'md5', '-'], capture_output=True, text=True)
        return r.stdout.strip()
    record('make_film: listening pair A/B: same picture, the two mixes, randomised and keyed outside deliver/',
           sorted([key.get('A'), key.get('B')]) == ['draft', 'hybrid'] and pair['A'] == pair['B'] == (90, 144000)
           and picture_md5(listen / 'A.mp4') == picture_md5(listen / 'B.mp4') != ''
           and not list(Path(j('make-out', 'hybrid', 'deliver')).rglob('*key*')), str(pair))
    record('make_film: listening pair loudness-matched within 0.5 LU', key.get('matched_within_0_5_lu') is True
           and abs(key['integrated_lufs']['A'] - key['integrated_lufs']['B']) <= .5, str(key.get('integrated_lufs')))
    questions = (listen / 'questions.md').read_text(encoding='utf-8') if (listen / 'questions.md').is_file() else ''
    record('make_film: questions.md asks about weight, camera-moving whooshes, the opening, harshness, the ending',
           all(w in questions for w in ('weightier', 'camera moving', 'opening', 'harsh', 'jarring', 'ending land')))
    text = Path(j('make-out', 'hybrid', 'deliver', 'delivery-report.md')).read_text(encoding='utf-8') \
        if Path(j('make-out', 'hybrid', 'deliver', 'delivery-report.md')).is_file() else ''
    record('make_film: hybrid report lists sources, licences, master numbers and the pending listening pair',
           '## Sound chain' in text and 'library (CC0 1.0): whoosh' in text and 'largest gain reduction' in text
           and 'Listening pair: `deliver/listen/A.mp4`' in text and 'waits for a person to answer questions.md' in text
           and 'Synthetic fixture: WHSH_soft' in text)

    # 5d. A supplied palette with no bed or music leaves digital silence between hits: sound_check.py warns,
    #     and its warning is a finding to listen for.
    sparse = Path(j('make-sparse'))
    sparse.mkdir(parents=True, exist_ok=True)
    t = np.arange(round(.12 * rate)) / rate
    burst = .4 * np.sin(2 * np.pi * 1200 * t) * np.exp(-t / .02)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(rate), '-ac', '2', '-i', '-',
                    '-c:a', 'pcm_s24le', str(sparse / 'burst.wav')],
                   input=np.column_stack((burst, burst)).astype('<f4').tobytes(), check=True)
    (sparse / 'palette.json').write_text(json.dumps({'version': 1, 'rate': rate, 'roles': {
        role: {'takes': ['burst.wav'], 'sync': sync, 'gain_db': 0, 'licence': 'generated for this test',
               'attribution': 'make cases'} for role, sync in (('impact', 'attack'), ('whoosh', 'apex'))}}),
        encoding='utf-8')
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--preview', '--master', 'none',
                     '--sound', sparse / 'palette.json', '--out', j('make-out', 'sparse'), '--json', j('make-sparse.json'))
    sc = load(j('make-out', 'sparse', 'qa', '320x180', 'sound-check.json'))
    heard = [f['detail'] for f in load(j('make-sparse.json')).get('findings', []) if f['check'] == 'sound_check']
    record('make_film: sound_check.py warnings become findings to listen for; exit 1',
           code == 1 and 'digital_silence' in sc.get('warnings', []) and
           any(d.startswith('listen for: digital silence') for d in heard), f'exit {code}; {heard[:2]}')

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

    # 7. Designed seams and changes: a seamless join need not show, a designed flip is not undeclared; exit 0.
    designed = film('designed', [1.5, 2.2], flip=.6, seams=[2.2], changes=[[.6, .7, 'ground flip']])
    code, out = tool('make_film.py', designed, '--sizes', '320x180', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'designed'), '--json', j('make-designed.json'))
    cut = load(j('make-out', 'designed', 'qa', '320x180', 'cut-check.json'))
    record('make_film: info.seams and info.changes accepted: seam skipped, designed change declared; exit 0',
           code == 0 and cut.get('seams_skipped') == [2.2] and not cut.get('missing') and
           not cut.get('undeclared_large_changes') and len(cut.get('changes_declared', [])) == 1,
           f"exit {code}; {cut.get('summary')}")

    # 8. Cut sheets stay bounded on a full-length film: 1440 frames, a dozen cuts, both aspect ratios.
    import importlib.util
    spec = importlib.util.spec_from_file_location('make_film_for_cases', scripts_dir / 'make_film.py')
    make_film = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_film)
    cuts = [round(1.2 + 1.8 * k, 3) for k in range(12)]
    for w, h in ((1920, 1080), (1080, 1920)):
        video = Path(j('make-sheets', f'long_{w}x{h}.mp4'))
        video.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-nostdin', '-f', 'lavfi', '-i',
                            f'testsrc2=s={w}x{h}:r=60:d=24', '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35',
                            '-pix_fmt', 'yuv420p', str(video)], capture_output=True, text=True)
        status, summary, failed, sheets = make_film.cut_sheets(
            lambda label, script, *args: tool(script, *args), video, cuts, (w, h), 60, video.parent / f'{w}x{h}')
        frames, _ = lengths(video) if not r.returncode else (0, None)
        record(f'make_film: 12 cut sheets on a 1440-frame {w}x{h} film, one bounded call per cut',
               frames == 1440 and status == 'pass' and len(sheets) == 12 and not failed,
               f'{frames} frames; {summary[0]}; {failed[:1]}')

    # 9. One timeline means one cue list and one set of cuts: sizes that differ stop the run; exit 1.
    split = film('split', [1.5], cue_shift=.1)
    code, out = tool('make_film.py', split, '--sizes', '320x180,180x320', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'split'))
    record('make_film: different cue lists across sizes stop the run before rendering; exit 1',
           code == 1 and 'different cue lists' in out and not Path(j('make-out', 'split', 'renders')).exists(),
           f'exit {code}')
    splitcuts = film('splitcuts', [1.5], cut_shift=.1)
    code, out = tool('make_film.py', splitcuts, '--sizes', '320x180,180x320', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'splitcuts'))
    record('make_film: different cuts across sizes stop the run before rendering; exit 1',
           code == 1 and 'different cuts' in out and not Path(j('make-out', 'splitcuts', 'renders')).exists(),
           f'exit {code}')

    # 10. Kit films: blank nodes and loop seams in the preflight; --loop, --web and --res in make_film.py.
    run_kit_cases(tool, record, j, load, lengths)
    code, out = tool('make_film.py', clean, '--sizes', '320x180', '--loop', '--web', '--sound', 'none', '--preview',
                     '--out', j('make-out', 'not-a-loop'), '--json', j('make-not-a-loop.json'))
    findings = load(j('make-not-a-loop.json')).get('findings', [])
    flags = [f['detail'] for f in findings if f['check'] == 'loop_seam']
    record('make_film: --loop on a film that does not loop reports the failing seam; exit 1',
           code == 1 and any('loop seam: step' in d and 'FAIL' in d for d in flags), f'exit {code}; {flags[:1]}')
    webm = [f['detail'] for f in findings if f['check'] == 'loop_seam_webm']
    web = load(j('make-out', 'not-a-loop', 'deliver', 'clean_320x180.webm.manifest.json')).get('checks', {})
    record('make_film: --loop --web reports the WebM\'s own failing seam and marks the WebM for inspection',
           any('clean_320x180.webm: loop seam: step' in d and 'FAIL' in d for d in webm)
           and web.get('loop_seam') == 'inspect' and web.get('status') == 'inspect', f'{webm[:1]}; {web.get("status")}')


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
