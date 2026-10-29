#!/usr/bin/env python3
"""Synthetic known-answer cases for the render lane.

  python selftest_render_cases.py --scripts scripts --keep work/render-cases

Integration: place beside selftest.py (or import with importlib) and call
run_cases(HERE, work, record) from selftest.main before its final totals. Existing
selftest.py is not replaced. Standalone default scripts is ./scripts beside this file.
Needs numpy, Pillow, FFmpeg. No Node. Exit 0 all passed, 1 a test failed, 2 could not run.
These synthetic checks do not judge any real film or normal-speed motion.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

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
    record('pace: one known cut / 2 seconds and zero-based beat',
           pace['cuts_per_10s'] == 5 and abs(pace['still_stretches'][1]['beat'] - 2.066666) < .001)
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
