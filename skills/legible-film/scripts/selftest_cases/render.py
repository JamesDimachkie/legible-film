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
    if sys.platform != 'darwin':
        available = c.free_memory()
        record('memory guard: measured free memory is a positive int',type(available) is int and available > 0,
               str(available))
    for error in (ValueError,AttributeError,OSError):
        def unavailable(_name, error=error):
            raise error('memory measurement unavailable')
        with patch.object(c,'os',SimpleNamespace(name='posix',sysconf=unavailable)):
            record(f'memory guard: {error.__name__} means unmeasurable',c.free_memory() is None)
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
    for fps,expected in [(29.97,'2997/100'),(30000/1001,'30000/1001')]:
        path = j(f'fraction-{expected.replace("/","-")}.mp4')
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
