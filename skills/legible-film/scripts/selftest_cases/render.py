#!/usr/bin/env python3
"""Synthetic known-answer cases for the render tools.

  python selftest_render_cases.py --scripts scripts --keep work/render-cases

Integration: place beside selftest.py (or import with importlib) and call
run_cases(HERE, work, record) from selftest.main before its final totals. Existing
selftest.py is not replaced. Standalone default scripts is ./scripts beside this file.
Needs numpy, Pillow, FFmpeg. No Node. Exit 0 all passed, 1 a test failed, 2 could not run.
These synthetic checks do not judge any real film or normal-speed motion.
"""
import argparse
import contextlib
from fractions import Fraction
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True

import numpy as np
from PIL import Image


def run_cases(scripts, work, record):
    scripts, work = Path(scripts), Path(work)
    work.mkdir(parents=True, exist_ok=True)

    def j(name):
        return str(work / name)

    def tool(name, *args):
        r = subprocess.run([sys.executable, '-I', str(scripts / name), *map(str, args)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        return r.returncode, r.stdout + r.stderr

    def ff(*args, data=None):
        r = subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)], input=data, capture_output=True)
        if r.returncode:
            raise RuntimeError(r.stderr.decode('utf-8', 'replace')[-1500:])

    def encode(name, frames, fps=30):
        h, w = frames[0].shape[:2]
        ff('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-r', fps, '-i', '-',
           '-c:v', 'ffv1', '-pix_fmt', 'bgr0', '-threads', 1, j(name), data=b''.join(x.tobytes() for x in frames))

    frames = []
    for k in range(60):
        f = np.full((180, 320, 3), 0 if k < 30 else 180, np.uint8)
        if 15 <= k < 30 or k >= 45:
            x = ((k % 15) * 8 + 30)
            f[:, x:x+16] = 255 if k < 30 else 0
        frames.append(f)
    encode('pace.mkv', frames)
    code, out = tool('motion_scan.py', j('pace.mkv'), '--json', j('pace.json'), '--bpm', 120)
    pace = json.loads(Path(j('pace.json')).read_text())['pace']
    record('pace: 28 of 59 compared frames still, two 14-frame stretches',
           abs(pace['still_share'] - 28/59) < 1e-6 and len(pace['still_stretches']) == 2 and
           abs(pace['longest_still_s'] - 14/30) < .001,
           f"share {pace['still_share']}; longest {pace['longest_still_s']}")
    window = pace['window_s'][1] - pace['window_s'][0]
    record('pace: one known cut / 2 seconds and zero-based beat',
           abs(window - 2) <= .0011 and len(pace['change_events']) == 1
           and abs(pace['cuts_per_10s'] - 10 / window) < .000001
           and abs(pace['still_stretches'][1]['beat'] - 2.066666) < .001,
           f"window={window}; rate={pace['cuts_per_10s']}; beat={pace['still_stretches'][1]['beat']}")
    code, _ = tool('motion_scan.py', j('pace.mkv'), '--max-still', .4)
    record('pace: undeclared 0.467-second stretch fails 0.4-second gate', code == 1)
    code, _ = tool('motion_scan.py', j('pace.mkv'), '--ignore', '0-0.6,1-1.6', '--max-still', .01,
                   '--max-still-share', .01)
    record('pace: declared still ranges excluded from both gates', code == 0)
    code, _ = tool('motion_scan.py', j('pace.mkv'), '--ignore', '0-0.6,1.2-1.4', '--max-still', .2)
    record('pace: partially declared hold is split at exact boundaries', code == 0)
    cropped = []
    for i in range(60):
        f = np.zeros((180,320,3),np.uint8)
        f[90:] = 255 if i % 2 else 0
        cropped.append(f)
    encode('crop.mkv', cropped)
    code, _ = tool('motion_scan.py', j('crop.mkv'), '--crop', '320:90:0:0', '--start', .4, '--end', 1.4,
                   '--json', j('crop.json'), '--still-min', .1)
    crop = json.loads(Path(j('crop.json')).read_text())
    record('pace: crop removes flashing caption; PTS window preserved',
           crop['pace']['still_share'] == 1 and abs(crop['pace']['window_s'][0] - .4) < .001 and
           abs(crop['pace']['longest_still_s'] - 29/30) < .001,
           str(crop['pace']['window_s']))

    ff('-f','lavfi','-i','testsrc2=s=320x180:r=30:d=0.2','-c:v','libx264','-threads',1,
       '-level:v','4.2',j('level.mp4'))
    ok, _ = tool('qc_file.py', j('level.mp4'), '--max-level', 4.2, '--json', j('level.json'))
    fail, _ = tool('qc_file.py', j('level.mp4'), '--max-level', 4.1)
    report = json.loads(Path(j('level.json')).read_text())
    record('qc_file: H.264 4.2 passes 4.2 and fails 4.1',
           ok == 0 and fail == 1 and report['video']['level'] == 42)
    size = Path(j('level.mp4')).stat().st_size / 1000000
    ok, _ = tool('qc_file.py', j('level.mp4'), '--max-size-mb', size + .000001)
    fail, _ = tool('qc_file.py', j('level.mp4'), '--max-size-mb', size - .000001)
    record('qc_file: decimal MB gate straddles actual byte size', ok == 0 and fail == 1, f'{size} MB')
    fail, _ = tool('qc_file.py', j('pace.mkv'), '--max-level', 5.2)
    record('qc_file: requested level on unsupported codec fails visibly', fail == 1)
    ff('-f','lavfi','-i','testsrc2=s=160x96:r=30:d=0.1','-c:v','libx265','-preset','ultrafast',
       '-x265-params','level-idc=4.1:pools=1:frame-threads=1:log-level=error',j('hevc.mp4'))
    ok, _ = tool('qc_file.py', j('hevc.mp4'), '--max-level', 4.1)
    fail, _ = tool('qc_file.py', j('hevc.mp4'), '--max-level', 4.0)
    record('qc_file: HEVC raw level_idc is normalised (/30)', ok == 0 and fail == 1)

    # A 2px bar travels 480 px/s: ideal support width is 2+4=6px (180 degrees),
    # or 2+8=10px (360 degrees). This fixture aligns the source grid with pixel edges.
    rate, fps, w, h = 240, 60, 320, 32
    seq = work / 'bar'
    seq.mkdir(exist_ok=True)
    for i in range(120):
        f = np.zeros((h,w,3),np.uint8)
        x = 20 + i*2
        f[:,x:x+2] = 255
        Image.fromarray(f).save(seq / f'{i:04d}.png')
    outputs = {}
    for shutter in (180,360):
        code, out = tool('motion_blur.py', str(seq / '%04d.png'), '--input-fps', rate, '--fps', fps,
            '--shutter', shutter, '--lossless', '--no-dither', '--out', j(f'blur{shutter}.mkv'))
        record(f'motion_blur: {shutter}-degree sequence renders', code == 0, out[-180:] if code else '')
        r = subprocess.run(['ffmpeg','-v','error','-i',j(f'blur{shutter}.mkv'),'-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True)
        f = np.frombuffer(r.stdout,np.uint8).reshape(-1,h,w,3)
        outputs[shutter] = f
        width = int(np.count_nonzero(f[15,h//2,:,0]))
        record(f'motion_blur: {shutter}-degree blur support has known width',
               width == (6 if shutter == 180 else 10), f'{width}px (source grid 2px)')
        srgb=f[15,h//2,:,0]/255
        energy = np.where(srgb<=.04045,srgb/12.92,((srgb+.055)/1.055)**2.4).sum()
        record(f'motion_blur: linear bright-streak energy retained ({shutter})', abs(energy - 2) < .08, f'{energy:.4f} pixel-white units')
    encode('bar240.mkv',[np.asarray(Image.open(seq / f'{i:04d}.png')) for i in range(120)], rate)
    code, out = tool('motion_blur.py', j('bar240.mkv'), '--fps',60,'--out',j('video-blur.mkv'),'--lossless')
    record('motion_blur: timestamped 240fps video input renders', code == 0, out[-200:] if code else '')
    spec = importlib.util.spec_from_file_location('blur_memory_case',scripts/'motion_blur.py')
    blur = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(blur)
    # Literal N/A duration must take the same last-frame fallback as an absent field.
    rows = 'best_effort_timestamp_time=0|duration_time=N/A\nbest_effort_timestamp_time=0.004167|duration_time=N/A\n'
    probe_process = SimpleNamespace(stdout=io.StringIO(rows),stderr=io.StringIO(''),returncode=0,
                                    wait=lambda: 0,poll=lambda: 0)
    with patch.object(blur.subprocess,'Popen',return_value=probe_process):
        probe = blur.timestamp_probe('ffprobe',[],'unused',[],240)
    record('motion_blur: ffprobe N/A duration is missing',probe['last_duration'] is None)
    real_probe = blur.timestamp_probe
    def missing_duration(*args):
        result = real_probe(*args)
        result['last_duration'] = None
        return result
    stdout = io.StringIO()
    argv = ['motion_blur.py',j('bar240.mkv'),'--fps','60','--out',j('unknown-memory.mkv'),'--lossless']
    with patch.object(blur.C,'free_memory',return_value=None), patch.object(blur,'timestamp_probe',missing_duration), \
            patch.object(sys,'argv',argv), contextlib.redirect_stdout(stdout):
        code = blur.main()
    manifest = json.loads(Path(j('unknown-memory.mkv.manifest.json')).read_text()) if code == 0 else {}
    record('motion_blur: unknown memory proceeds visibly; missing duration falls back to source rate',
           code == 0 and 'guard could not measure memory' in stdout.getvalue() and manifest.get('output_frames') == 30)
    cuts = []
    for i in range(120):
        f = np.zeros((h,w,3),np.uint8)
        if i < 60:
            f[:,20+i*2:22+i*2,0] = 255
        else:
            f[:,:,2] = 255
        cuts.append(f)
    encode('cut240.mkv',cuts,rate)
    Path(j('cutinfo.json')).write_text(json.dumps({'cuts':[.25],'smears':[[.2,.25,3]]}))
    code, out = tool('motion_blur.py', j('cut240.mkv'),'--fps',60,'--cuts-json',j('cutinfo.json'),
        '--out',j('cut-blur.mkv'),'--lossless','--no-dither','--shutter',360)
    r = subprocess.run(['ffmpeg','-v','error','-i',j('cut-blur.mkv'),'-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True)
    f = np.frombuffer(r.stdout,np.uint8).reshape(-1,h,w,3)
    record('motion_blur: no double exposure at a cut', code == 0 and not f[14,:,:,2].any() and not f[15,:,:,0].any() and np.all(f[15,:,:,2]==255))
    support = np.count_nonzero(f[14,h//2,:,0])
    record('motion_blur: last pre-cut whip frame keeps blur',support > 2, f'{support}px vs sharp 2px')
    # Force exposure to straddle the cut at a frame just before it (360 degrees + 3x).
    spec = importlib.util.spec_from_file_location('render_primitives',scripts/'render_common.py')
    c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(c)
    from fractions import Fraction
    ntsc = {29.97: Fraction(30000, 1001), '30000/1001': Fraction(30000, 1001), 23.976: Fraction(24000, 1001),
            '23.98': Fraction(24000, 1001), 59.94: Fraction(60000, 1001), 25: Fraction(25), 30: Fraction(30),
            12.5: Fraction(25, 2), Fraction(2997, 100): Fraction(2997, 100), '2997/100': Fraction(2997, 100),
            12.34567: Fraction(1234567, 100000)}
    record('exact_rate: decimal NTSC rates mean the exact fraction; explicit fractions and other rates are kept',
           all(c.exact_rate(value) == want for value, want in ntsc.items()),
           str({str(value): str(c.exact_rate(value)) for value in ntsc}))
    refused = []
    for value in (0, -30, 'abc', '1/0', float('nan'), float('inf'), None):
        try:
            c.exact_rate(value)
        except ValueError:
            refused.append(value)
    record('exact_rate: refuses zero, negative, non-numeric and non-finite rates', len(refused) == 7, str(refused))
    available = c.free_memory()
    record('memory guard: measured free memory is a positive int, macOS included',
           type(available) is int and available > 0, str(available))
    # The one probe lives in setup.py (render_common and make_film call it); a system that cannot say is None.
    spec = importlib.util.spec_from_file_location('render_memory_setup', scripts/'setup.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    for error in (ValueError,AttributeError,OSError):
        class Unreadable:
            def __init__(self, *_args, error=error):
                self.error = error

            def read_text(self, *_args, **_kwargs):
                raise self.error('memory measurement unavailable')
        with patch.object(setup,'os',SimpleNamespace(name='posix')), patch.object(setup.sys,'platform','linux'), \
                patch.object(setup,'Path',Unreadable):
            record(f'memory guard: {error.__name__} means unmeasurable',setup.free_memory() is None)
    for w,h,fps,expected in [(720,480,30,'3.0'),(1280,720,30,'3.1'),(1280,720,60,'3.2'),
                              (1920,1080,30,'4.0'),(1920,1080,60,'4.2'),(3840,2160,60,'5.2')]:
        actual = c.auto_level(w,h,fps)
        record(f'encoder level: {w}x{h}@{fps} selects {expected}',actual == expected,actual)
    limits = [(None,25000000,31250000),('3.0',12500000,12500000),('3.1',17500000,17500000),
              ('3.2',25000000,25000000),('4.1',62500000,78125000),('4.2',62500000,78125000),
              ('5.0',168750000,168750000),('5.1',300000000,300000000),('5.2',300000000,300000000),
              ('6.0',300000000,300000000),('6.1',600000000,600000000),('6.2',1000000000,1000000000)]
    capped = []
    for level,maxrate,bufsize in limits:
        with patch.object(c.subprocess,'Popen'):
            encoder = c.Encoder('ffmpeg',j('command-only.mp4'),1920,1080,30,level=level)
        command = encoder.command
        capped.append(command[command.index('-maxrate')+1] == str(maxrate) and
                      command[command.index('-bufsize')+1] == str(bufsize) and
                      command[command.index('-crf')+1] == '14')
        encoder.log.close()
    record('encoder VBV: auto and explicit levels use High-profile MaxBR/MaxCPB; CRF stays 14',all(capped))
    # Independent random RGB frames stress default CRF 14 at 1080p30. Stream them
    # one at a time; do not retain a raw clip or all decoded frames in memory.
    path = j('entropy1080p30.mp4')
    encoder = c.Encoder('ffmpeg',path,1920,1080,30)
    rng = np.random.default_rng(73)
    try:
        for _ in range(30):
            encoder.write(rng.integers(0,256,(1080,1920,3),dtype=np.uint8))
        encoder.close()
    except BaseException:
        encoder.abort()
        raise
    r = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_packets','-show_streams',
                        '-show_entries','stream=width,height,profile,level,avg_frame_rate,time_base,bit_rate:packet=dts,size',
                        '-of','json',path],capture_output=True,text=True,check=True)
    data = json.loads(r.stdout)
    stream = data['streams'][0]
    packets = [(int(p['dts'])*Fraction(stream['time_base']),int(p['size'])*8) for p in data['packets']]
    # Prefill the CPB (initial delay CPB/MaxBR); feed at no more than MaxBR,
    # pausing while full. Remove each access unit at DTS, not presentation time.
    # Table A-1 High profile, level 4.0: MaxBR=25 Mbit/s, MaxCPB=31.25 Mbit.
    maxrate,capacity = 25000000,31250000
    fullness = minimum = Fraction(capacity)
    previous = packets[0][0]
    monotonic,trace = True,[]
    for dts,bits in packets:
        monotonic = monotonic and dts >= previous
        fullness = min(capacity,fullness+maxrate*(dts-previous))-bits
        minimum = min(minimum,fullness)
        trace.append({'dts_s':float(dts),'bits':bits,'buffer_bits':float(fullness)})
        previous = dts
    peak = max(sum(bits for dts,bits in packets if start <= dts < start+1) for start,_ in packets)
    Path(j('entropy-vbv.json')).write_text(json.dumps({'stream':stream,'command':encoder.command,
        'maxrate_bits_per_s':maxrate,'capacity_bits':capacity,'initial_fullness_bits':capacity,
        'minimum_fullness_bits':float(minimum),'peak_one_second_bits':peak,'packets':trace},indent=2),encoding='utf-8')
    record('encoder VBV: high-entropy default 1080p30 never underflows level 4.0 CPB',
           stream['profile'] == 'High' and stream['level'] == 40 and stream['width'] == 1920 and
           stream['height'] == 1080 and stream['avg_frame_rate'] == '30/1' and len(packets) == 30 and
           monotonic and minimum >= 0,
           f'min buffer {float(minimum):.0f}/{capacity} bits; peak 1s {peak} bits (information only)')
    # A decimal NTSC rate means the exact one; 2997/100 would read as a non-standard rate in an editing application.
    for index,(fps,expected) in enumerate([(29.97,'30000/1001'),(30000/1001,'30000/1001'),(25,'25/1')]):
        path = j(f'fraction-{index}-{expected.replace("/","-")}.mp4')
        encoder = c.Encoder('ffmpeg',path,32,32,fps)
        for _ in range(3):
            encoder.write(np.zeros((32,32,3),np.uint8))
        encoder.close()
        rate = encoder.command[encoder.command.index('-r')+1]
        r = subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                            'stream=avg_frame_rate','-of','json',path],capture_output=True,text=True)
        actual = json.loads(r.stdout)['streams'][0]['avg_frame_rate']
        record(f'encoder rate: {fps} uses explicit {expected}',rate == expected and actual == expected)
    spec = importlib.util.spec_from_file_location('kit_skip_cases',scripts/'kit_selftest.py')
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    for dependency,message in [('Node','Node is missing'),('Playwright','Playwright missing'),
                               ('Chromium','Chromium executable missing')]:
        outcomes = []
        for require in (False,True):
            stdout = io.StringIO()
            argv = ['kit_selftest.py','--keep',j(f'skip-{dependency}-{require}')] + (['--require'] if require else [])
            result = SimpleNamespace(returncode=2,stdout='',stderr=message)
            with patch.object(sys,'argv',argv), contextlib.redirect_stdout(stdout), \
                    patch.object(kit.shutil,'which',return_value=None if dependency == 'Node' else 'node'), \
                    patch.object(kit.subprocess,'run',return_value=result):
                outcomes.append(kit.main() == (2 if require else 0) and 'skipped:' in stdout.getvalue())
        record(f'kit dependencies: missing {dependency} skips normally and exits 2 with --require',all(outcomes))
    times = c.sample_times(14/60,60,.5,[.25],[[.2,.25,3]],[],360,4,32)
    record('scheduler: pre-cut exposure slides, keeps full 50ms span',max(times)<.25 and abs((times[-1]-times[0])*len(times)/(len(times)-1)-.05)<1e-9)
    rgb = np.zeros((8,8,3),np.float32)+.2
    a = c.finish(rgb.copy(),7,grain=1.5)
    b = c.finish(rgb.copy(),7,grain=1.5)
    record('finish: deterministic global grain',np.array_equal(a,b) and np.std(a)>0)
    bright = np.zeros((64,64,3),np.float32);bright[24:40,24:40]=1
    a = c.finish(bright.copy(),0,bloom=1,dither=False)
    record('finish: linear bloom adds light outside highlight',bool(a[20,32].max()>a[0,0].max()) and a[32,32].max()==255)


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--scripts',default=str(Path(__file__).resolve().parent/'scripts'))
    p.add_argument('--keep')
    a=p.parse_args()
    results=[]
    def record(name,ok,detail=''):
        results.append(bool(ok))
        print(f'{"PASS" if ok else "FAIL"}  {name}'+(f'  [{detail}]' if detail else ''),flush=True)
    root=Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix='lf-render-cases-'))
    try:
        run_cases(a.scripts,root,record)
        print(f'{sum(results)}/{len(results)} checks passed.')
        return 0 if all(results) else 1
    except Exception as exc:
        print('selftest_render_cases.py: could not run: '+str(exc),file=sys.stderr)
        return 2
    finally:
        if not a.keep:
            shutil.rmtree(root,ignore_errors=True)


if __name__=='__main__':
    sys.exit(main())


def run_render_cases(tool, record, j, scripts_dir):
    """Entry point for selftest.py: the same cases, in a folder of their own."""
    run_cases(scripts_dir, j('render-cases'), record)
    change_events_case(tool, record, j)
    check_grapheme_render(tool, record, j)
    check_determinism_probe(tool, record, j)
    check_wave2_preflight(tool, record, j, scripts_dir)
    check_round2_preflight(record, scripts_dir)


def playwright_core():
    """playwright-core beside the Playwright that LF_PLAYWRIGHT_MODULE names (as the Screening Room cases use it)."""
    module = os.environ.get('LF_PLAYWRIGHT_MODULE')
    return Path(module).parent / 'playwright-core' if module else Path('no-playwright-module')


def check_grapheme_render(tool, record, j):
    """Compare settled kit text with unsplit text in the local Chromium render path."""
    from PIL import ImageChops, ImageFilter
    root = Path(j('kit-graphemes'))
    root.mkdir(parents=True, exist_ok=True)
    package = playwright_core()
    cache = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright'
    browsers = sorted(cache.glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    if not package.exists() or not browsers or not shutil.which('node'):
        print('SKIP  kit graphemes: LF_PLAYWRIGHT_MODULE, Node or Chromium is unavailable')
        return
    kit = Path(__file__).resolve().parent.parent.parent / 'assets' / 'kit' / 'lf'
    html = root / 'text.html'
    document = '''<!doctype html><html><body style="background:white;margin:20px">
<div id="stage" style="position:relative;height:100px"></div>
<div style="position:relative;height:100px"><div id="reference"></div></div>
<script type="module">
import {Node} from NODE_MODULE;
import {textNode, styleCss} from TEXT_MODULE;
window.makeText = (text, direction) => {
  const stage = document.getElementById('stage'); stage.innerHTML = '';
  const root = new Node({el:stage});
  const style = {string:text, font:'Arial', size:48, weight:400, anchor:[0,0], direction};
  const node = textNode(root, style); node.flush();
  const ref = document.getElementById('reference');
  ref.style.cssText = styleCss(style) + ';position:absolute;left:0;top:0;transform-origin:0 0;'
    + 'color:black;transform:' + node.el.style.transform;
  ref.dir = direction; ref.textContent = '';
  if (direction === 'ltr') {
    const word = document.createElement('span'); word.style.display = 'inline-block';
    word.textContent = text; ref.appendChild(word);
  } else { ref.textContent = text; }
  return {letters:node.letters.map(element => element.textContent), text:node.front.textContent};
};
window.ready = true;
</script></body></html>'''
    document = document.replace('NODE_MODULE', json.dumps((kit / 'node.js').as_uri()))
    document = document.replace('TEXT_MODULE', json.dumps((kit / 'text.js').as_uri()))
    html.write_text(document, encoding='utf-8')
    script = r'''const { chromium } = require(PACKAGE);
const { pathToFileURL } = require('node:url');
(async () => {
  const browser = await chromium.launch({executablePath:BROWSER, args:['--allow-file-access-from-files']});
  try {
    const page = await browser.newPage({viewport:{width:1000,height:300}});
    await page.route(/^https?:/, route => route.abort());
    await page.goto(pathToFileURL(HTML).href);
    await page.waitForFunction(() => window.ready === true);
    const cases = [['emoji','\u{1f469}\u200d\u{1f4bb}','ltr'],
                   ['accent','e\u0301','ltr'], ['arabic','\u0645\u0631\u062d\u0628\u0627 OpenAI','rtl']];
    const out = [];
    for (const [name,text,dir] of cases) {
      const value = await page.evaluate(([text,dir]) => window.makeText(text,dir), [text,dir]);
      await page.locator('#stage .lf-node').screenshot({path:DIR + '/' + name + '-kit.png'});
      await page.locator('#reference').screenshot({path:DIR + '/' + name + '-reference.png'});
      out.push({name,original:text,...value});
    }
    process.stdout.write(JSON.stringify(out));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(2); });'''
    for key, value in ({'PACKAGE': str(package), 'BROWSER': str(browsers[-1]),
                        'HTML': str(html), 'DIR': str(root)}.items()):
        script = script.replace(key, json.dumps(value))
    js = root / 'probe.cjs'
    js.write_text(script, encoding='utf-8')
    result = subprocess.run(['node', str(js)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                            timeout=90)
    if result.returncode:
        record('kit: graphemes and joined text match unsplit settled frames', False, result.stderr[-500:])
        return
    rows = json.loads(result.stdout)
    details = []
    for row in rows:
        with Image.open(root / (row['name'] + '-kit.png')) as kit_image, \
                Image.open(root / (row['name'] + '-reference.png')) as reference:
            exact = kit_image.size == reference.size and ImageChops.difference(kit_image, reference).getbbox() is None
            same = False
            if kit_image.size == reference.size:
                a = kit_image.convert('L').point(lambda value: 255 if value < 230 else 0)
                b = reference.convert('L').point(lambda value: 255 if value < 230 else 0)
                # Chromium can move antialiased edges by a pixel when a bidi run crosses span boundaries.
                missing = ImageChops.subtract(a, b.filter(ImageFilter.MaxFilter(3))).getbbox()
                extra = ImageChops.subtract(b, a.filter(ImageFilter.MaxFilter(3))).getbbox()
                same = missing is None and extra is None
        details.append((row['name'], same, exact, len(row['letters']), row['text'] == row['original']))
    ok = all(same and count == (2 if name == 'arabic' else 1) and intact
             for name, same, exact, count, intact in details)
    record('kit: graphemes and joined text match unsplit settled frames', ok, str(details))


def check_determinism_probe(tool, record, j):
    """Offline pages with pure and history-dependent frames give different probe results."""
    package = playwright_core()
    cache = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright'
    browsers = sorted(cache.glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    if not package.exists() or not browsers or not shutil.which('node'):
        print('SKIP  determinism probe: LF_PLAYWRIGHT_MODULE, Node or Chromium is unavailable')
        return
    root = Path(j('determinism-probe'))
    for kind in ('pure', 'stateful'):
        folder = root / kind
        folder.mkdir(parents=True, exist_ok=True)
        page = '''<!doctype html><html><body style="margin:0"><script>
let count = 0;
window.__lf = {ready:Promise.resolve(), info:() => ({title:'probe', width:160, height:90, fps:10, frames:10,
duration:1}), analyse:() => ({errors:[],warnings:[],texts:[]}), frame:() => {}, seek:(t) => {
const n = MODE; document.body.style.background = `rgb(${n}, ${n}, ${n})`;
}};
</script></body></html>'''
        page = page.replace('MODE', 'Math.round(t * 200)' if kind == 'pure' else '(++count * 23) % 255')
        (folder / 'index.html').write_text(page, encoding='utf-8')
        report = folder / 'result.json'
        code, output = tool('film_check.py', folder, '--size', '160x90', '--file-only', '--determinism',
                            '--playwright', package, '--browser', browsers[-1], '--json', report)
        data = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
        result = data.get('determinism') or {}
        if kind == 'pure':
            record('kit: deterministic frame probe passes a pure local page',
                   code == 0 and result.get('status') == 'same', output[-400:])
        else:
            differences = result.get('differences') or []
            record('kit: deterministic frame probe names history-dependent times',
                   code == 1 and result.get('status') == 'different'
                   and any(isinstance(row.get('time_s'), (int, float)) for row in differences), output[-400:])


def change_events_case(tool, record, j):
    """Pace change events: a hard cut counts once, and a three-frame whip counts once, not three times."""
    import numpy as np
    folder = j('render-cases', 'events')
    os.makedirs(folder, exist_ok=True)
    w, h, fps = 160, 90, 30
    colours = {'a': (20, 24, 32), 'b': (236, 232, 222), 'c': (230, 90, 40)}
    plan = ['a'] * 30 + ['b'] * 30 + ['a'] * 29 + ['w1', 'w2', 'w3'] + ['c'] * 28 + ['b'] * 30 + ['a'] * 30
    frames = []
    for name in plan:
        f = np.zeros((h, w, 3), np.uint8)
        if name.startswith('w'):  # each whip frame differs from its neighbours by far more than 24 grey levels
            f[:] = (200, 200, 200) if name in ('w1', 'w3') else (60, 60, 60)
        else:
            f[:] = colours[name]
        frames.append(f)
    path = os.path.join(folder, 'events.mp4')
    cmd = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}',
           '-r', str(fps), '-i', '-', '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
           '-c:v', 'libx264', '-crf', '12', path]
    subprocess.run(cmd, input=b''.join(f.tobytes() for f in frames), check=True, capture_output=True)
    out_json = os.path.join(folder, 'events.json')
    code, text = tool('motion_scan.py', path, '--json', out_json)
    try:
        pace = json.load(open(out_json, encoding='utf-8'))['pace']
        events = pace['change_events']
    except (OSError, ValueError, KeyError) as exc:
        record('motion_scan pace: change events merge a whip and count each cut once', False, repr(exc))
        return
    starts = [round(e['start_s'], 2) for e in events]
    # the whip's three frames and its landing are four changed frames, one event
    ok = len(events) == 5 and events[2]['frames'] == 4 and starts == [1.0, 2.0, 2.97, 4.0, 5.0]
    record('motion_scan pace: change events merge a whip and count each cut once', ok,
           f"{len(events)} events at {starts}; {pace['change_events_per_10s']:.2f} per 10 s")


def check_wave2_preflight(tool, record, j, scripts_dir):
    """A missing-filter list names every affected capability."""
    import re
    spec = importlib.util.spec_from_file_location('wave2_selftest', Path(scripts_dir) / 'selftest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    real_run = subprocess.run
    filters = real_run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, check=True)
    removed = set(module.FILTER_LIMITS)

    def remaining():
        return '\n'.join(line for line in filters.stdout.splitlines()
                         if not ((match := re.match(r'^\s*[TSC.]{2,3}\s+(\S+)', line))
                                 and match.group(1) in removed))

    def fake_run(command, *args, **kwargs):
        if '-filters' in command:
            return SimpleNamespace(returncode=0, stdout=remaining(), stderr='')
        return real_run(command, *args, **kwargs)

    with patch.object(module.subprocess, 'run', side_effect=fake_run):
        try:
            module.environment()
            message = ''
        except RuntimeError as error:
            message = str(error)
    record('render: quick preflight names missing filters and the capabilities they limit',
           all(name in message and limit in message for name, limit in module.FILTER_LIMITS.items()), message)
    removed = set(module.OPTIONAL_FILTERS)
    with patch.object(module.subprocess, 'run', side_effect=fake_run):
        identity = module.environment()
    limitations = {item['filter']: item['limitation'] for item in identity['filter_limitations']}
    record('render: optional missing filters report limitations without blocking other work',
           limitations == {name: module.FILTER_LIMITS[name] for name in removed}, str(limitations))


def check_round2_preflight(record, scripts_dir):
    """The filters used by picture, burn and map are reported with their feature limitations."""
    spec = importlib.util.spec_from_file_location('round2_selftest', Path(scripts_dir) / 'selftest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    needed = {'colorspace', 'tonemap', 'bwdif', 'minterpolate', 'tpad', 'setsar', 'volume', 'pad', 'fade',
              'overlay', 'scdet', 'loop', 'ametadata', 'aphasemeter', 'waveform', 'vectorscope', 'siti',
              'entropy', 'blurdetect', 'blockdetect', 'afftdn', 'deesser', 'acompressor', 'whisper'}
    missing = needed - set(module.FILTERS)
    unnamed = {name for name in needed if not module.FILTER_LIMITS.get(name)}
    record('render: preflight covers picture, caption, scene and retime filters',
           not missing and not unnamed, f'missing={missing}; undescribed={unnamed}')
    record('render: an absent fixture-only LUT does not block editing',
           'lut' in module.OPTIONAL_FILTERS and 'fixture' in module.FILTER_LIMITS['lut'],
           str(module.OPTIONAL_FILTERS))
    optional = {'filter_limitations': [{'filter': 'whisper', 'limitation': module.FILTER_LIMITS['whisper']}]}
    with patch.object(module, 'environment', return_value=optional), patch.object(sys, 'argv', ['selftest', '--quick']):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = module.main()
    record('render: quick probe passes with a limited note for an optional missing filter',
           result == 0 and 'LIMITED' in output.getvalue() and 'whisper' in output.getvalue(), output.getvalue())
    with patch.object(module, 'environment', side_effect=RuntimeError('missing required filter scale')), \
            patch.object(sys, 'argv', ['selftest', '--quick']):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = module.main()
    record('render: quick probe fails for a required missing filter',
           result == 2 and 'scale' in output.getvalue(), output.getvalue())
