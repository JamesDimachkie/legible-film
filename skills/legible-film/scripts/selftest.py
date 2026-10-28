#!/usr/bin/env python3
"""Self-test: build synthetic media with known answers and check every script against them.

Run it once after installing, and after changing any script:

  python selftest.py            # about a minute; writes only to a temporary folder
  python selftest.py --keep DIR # keep the generated media and reports in DIR

Each case states what it proves. A pass shows the scripts measure these synthetic answers on this
machine's FFmpeg and Python; it says nothing about any real film. Needs numpy, Pillow and FFmpeg
with libx264 and the native AAC encoder. Exit code 0 when every case passes.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
RESULTS = []


def record(name, ok, detail=''):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  [{detail}]' if detail else ''), flush=True)


def tool(script, *args, cwd=None):
    r = subprocess.run([PY, '-I', os.path.join(HERE, script), *map(str, args)], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def ff(*args, stdin=None):
    cmd = ['ffmpeg', '-hide_banner', '-v', 'error', '-y'] + (['-nostdin'] if stdin is None else [])
    r = subprocess.run(cmd + list(args), input=stdin, capture_output=True)
    if r.returncode:
        raise RuntimeError('ffmpeg failed: ' + r.stderr.decode(errors='replace')[-400:])


TAG709 = 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,' \
         'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv'


def encode_frames(path, frames, fps, extra=()):
    """Encode an iterable of HxWx3 uint8 arrays to H.264 with correct BT.709 conversion and tags."""
    frames = list(frames)
    h, w = frames[0].shape[:2]
    data = b''.join(f.tobytes() for f in frames)
    ff('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{w}x{h}', '-r', str(fps), '-i', '-', '-vf', TAG709,
       '-c:v', 'libx264', '-crf', '12', *extra, path, stdin=data)


def write_wav(path, samples, rate=48000):
    ff('-f', 'f32le', '-ar', str(rate), '-ac', '1', '-i', '-', '-c:a', 'pcm_s16le', path,
       stdin=samples.astype('float32').tobytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--keep', help='keep generated files in this folder')
    a = ap.parse_args()
    missing = [t for t in ('ffmpeg', 'ffprobe') if not shutil.which(t)]
    try:
        import numpy as np
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        print(f'missing Python package: {exc.name}. pip install numpy Pillow')
        return 2
    if missing:
        print('missing on PATH: ' + ', '.join(missing))
        return 2
    work = os.path.abspath(a.keep) if a.keep else tempfile.mkdtemp(prefix='video-skill-selftest-')
    os.makedirs(work, exist_ok=True)
    j = lambda *p: os.path.join(work, *p)  # noqa: E731
    rng = np.random.default_rng(7)

    # 0. Every script documents itself and answers --help.
    scripts = sorted(f for f in os.listdir(HERE) if f.endswith('.py') and f != 'selftest.py')
    bad = [s for s in scripts if tool(s, '--help')[0] != 0]
    record('every script answers --help', not bad, ', '.join(bad) or f'{len(scripts)} scripts')

    # 1. A well-formed file passes the spec checks.
    clicks = [0.5, 1.25, 2.0, 2.9, 3.4]
    rate, dur = 48000, 4.0
    audio = (rng.standard_normal(int(rate * dur)) * 10 ** (-48 / 20))
    for t in clicks:
        k = int(t * rate)
        n = int(0.03 * rate)
        audio[k:k + n] += rng.standard_normal(n) * np.exp(-np.arange(n) / (0.006 * rate)) * 0.5
    write_wav(j('master.wav'), audio)
    ff('-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=4', '-i', j('master.wav'), '-map', '0:v',
       '-map', '1:a', '-vf', TAG709, '-c:v', 'libx264', '-crf', '18', '-c:a', 'aac', '-b:a', '256k', '-ac', '2',
       '-movflags', '+faststart', j('good.mp4'))
    code, out = tool('qc_file.py', j('good.mp4'), '--spec', '640x360@30', '--duration', 4, '--frames', 120,
                     '--pix-fmt', 'yuv420p', '--color', 'bt709', '--audio', 'required', '--sample-rate', 48000,
                     '--faststart', '--lossy-check', '--detect', '--json', j('good.json'))
    record('qc_file: a correct file passes its spec', code == 0, out.strip().splitlines()[0][:90])
    rep = json.load(open(j('good.json'), encoding='utf-8'))
    record('qc_file: measures loudness and true peak', rep['loudness'].get('integrated_lufs') is not None
           and rep['loudness'].get('true_peak_dbtp') is not None,
           f"{rep['loudness'].get('integrated_lufs')} LUFS, {rep['loudness'].get('true_peak_dbtp')} dBTP")

    # 2. Missing colour tags fail the check; output options alone may not tag on current FFmpeg.
    ff('-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
       j('untagged.mp4'))
    code, _ = tool('qc_file.py', j('untagged.mp4'), '--color', 'bt709')
    record('qc_file: an untagged file fails --color bt709', code == 1)
    ff('-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
       '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', j('opts_only.mp4'))
    code, _ = tool('qc_file.py', j('opts_only.mp4'), '--color', 'bt709')
    print('info  output options alone ' + ('did NOT fully tag BT.709 on this FFmpeg (use setparams)' if code
                                           else 'tagged BT.709 on this FFmpeg'))

    # 3. A brand colour survives the BT.709 route and shifts on the default route.
    src = 'color=c=0x3080C0:s=128x72:d=0.5:r=10,format=rgb24'
    ff('-f', 'lavfi', '-i', src, '-vf', TAG709, '-c:v', 'libx264', '-qp', '0', j('patch_709.mp4'))
    ff('-f', 'lavfi', '-i', src, '-vf', 'format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:'
       'colorspace=bt709:range=tv', '-c:v', 'libx264', '-qp', '0', j('patch_mismatch.mp4'))
    ok709, out709 = tool('qc_file.py', j('patch_709.mp4'), '--color-patch', '0.1@32,16,64,40=#3080C0')
    bad709, outbad = tool('qc_file.py', j('patch_mismatch.mp4'), '--color-patch', '0.1@32,16,64,40=#3080C0')
    record('qc_file: colour patch passes the BT.709 route and fails a BT.601/709 mismatch',
           ok709 == 0 and bad709 == 1,
           next((line.strip() for line in outbad.splitlines() if 'color_patch' in line), ''))

    # 4. Frame sheets select exact frames.
    code, out = tool('frame_sheet.py', j('good.mp4'), '--around', '1.0', '--span', 0.5, '--rate', 20,
                     '--out', j('sheet.png'), '--keep-frames', j('frames'))
    kept = sorted(os.listdir(j('frames'))) if os.path.isdir(j('frames')) else []
    record('frame_sheet: window sheet with exact frame labels', code == 0 and os.path.isfile(j('sheet.png'))
           and kept and kept[0].startswith('frame-000022-at-0.733s'), kept[0] if kept else out[-120:])

    # 5. Onion skin.
    if len(kept) >= 2:
        code, _ = tool('onion_frames.py', '--out', j('onion.png'), j('frames', kept[0]), j('frames', kept[1]))
        record('onion_frames: blends two frames', code == 0 and os.path.isfile(j('onion.png')))

    # 6. Blank run in the middle of a film.
    ff('-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=30:duration=3', '-vf',
       "drawbox=x=0:y=0:w=iw:h=ih:color=gray@1:t=fill:enable='between(t,1.5,2.0)'", '-c:v', 'libx264', '-crf', '18',
       '-pix_fmt', 'yuv420p', j('blank.mp4'))
    code, out = tool('blank_scan.py', j('blank.mp4'), '--json', j('blank.json'))
    runs = json.load(open(j('blank.json'), encoding='utf-8'))['runs']
    record('blank_scan: finds the flat 1.5-2.0 s run', code == 1 and runs and abs(runs[0]['start_s'] - 1.5) < 0.05,
           f"{runs[0]['start_s']}-{runs[0]['end_s']} s" if runs else out[-120:])
    code, _ = tool('blank_scan.py', j('blank.mp4'), '--ignore', '1.4-2.1')
    record('blank_scan: a declared range is not flagged', code == 0)

    # 7. Motion: one-frame intrusion and a repeated frame inside motion.
    def square_frame(i, w=320, h=180):
        f = np.full((h, w, 3), 40, np.uint8)
        x = 10 + 4 * i
        f[70:110, x:x + 40] = (230, 230, 230)
        return f
    frames = [square_frame(i) for i in range(60)]
    frames[30] = np.full_like(frames[30], 200)   # a stray frame between two matching neighbours
    frames[30][70:110, 130:170] = 0
    frames[29] = square_frame(29)
    frames[31] = square_frame(29)                 # neighbours of the intrusion match each other
    frames[45] = frames[44].copy()                # a repeated frame inside motion
    encode_frames(j('motion.mp4'), frames, 30)
    code, out = tool('motion_scan.py', j('motion.mp4'), '--json', j('motion.json'))
    m = json.load(open(j('motion.json'), encoding='utf-8'))
    ghost = [g['frame'] for g in m['one_frame_intrusions']]
    stut = [s['frame'] for s in m['stutter_frames']]
    record('motion_scan: finds the one-frame intrusion at frame 30', 30 in ghost, f'intrusions {ghost}')
    record('motion_scan: finds the repeated frame at 45', 45 in stut, f'repeats {stut}')

    # 8. Loop seam: a seamless circle and a broken one.
    def circle(i, n=60, w=240, h=136):
        f = np.full((h, w, 3), 30, np.uint8)
        ang = 2 * np.pi * i / n
        cx, cy = int(w / 2 + 50 * np.cos(ang)), int(h / 2 + 40 * np.sin(ang))
        f[cy - 10:cy + 10, cx - 10:cx + 10] = (240, 200, 40)
        return f
    encode_frames(j('loop_ok.mp4'), [circle(i) for i in range(60)], 30)
    encode_frames(j('loop_bad.mp4'), [circle(i) for i in range(45)], 30)
    ok_code, _ = tool('motion_scan.py', j('loop_ok.mp4'), '--loop')
    bad_code, out = tool('motion_scan.py', j('loop_bad.mp4'), '--loop')
    record('motion_scan: loop seam passes a cycle and fails a cut-short loop', ok_code == 0 and bad_code == 1,
           next((line.strip() for line in out.splitlines() if 'seam' in line), ''))

    # 9. Audio delay against the master.
    ff('-i', j('good.mp4'), '-map', '0:v', '-map', '0:a', '-c:v', 'copy', '-af', 'adelay=40|40', '-c:a', 'aac',
       '-b:a', '256k', j('delayed.mp4'))
    code, out = tool('sync_check.py', j('good.mp4'), j('master.wav'), '--window', 0.8, '--max-lag-ms', 200,
                     '--json', j('sync_good.json'))
    s_good = json.load(open(j('sync_good.json'), encoding='utf-8'))['summary']
    record('sync_check: an in-sync mux measures ~0 ms', code == 0, f"median {s_good['median_lag_ms']} ms")
    code, out = tool('sync_check.py', j('delayed.mp4'), j('master.wav'), '--window', 0.8, '--max-lag-ms', 200,
                     '--json', j('sync_delay.json'))
    s_del = json.load(open(j('sync_delay.json'), encoding='utf-8'))['summary']
    record('sync_check: measures a 40 ms delay', code == 1 and s_del['median_lag_ms'] is not None
           and abs(s_del['median_lag_ms'] - 40) <= 1.5, f"median {s_del['median_lag_ms']} ms")

    # 10. Cue onsets: on cue, late, quiet as intended, and an unexpected sound.
    cues = {'fps': 30, 'events': [
        {'id': 'c1', 't': 0.5, 'sound': 'required'},
        {'id': 'c2', 't': 1.25, 'sound': 'required'},
        {'id': 'c3-late', 't': 2.85, 'sound': 'required', 'tolerance_ms': 20},
        {'id': 'quiet', 't': 1.65, 'sound': 'silent', 'window_ms': 300},
        {'id': 'not-quiet', 't': 3.4, 'sound': 'silent', 'window_ms': 100}]}
    with open(j('cues.json'), 'w', encoding='utf-8') as fh:
        json.dump(cues, fh)
    code, out = tool('cue_onsets.py', j('master.wav'), j('cues.json'), '--json', j('cue_report.json'))
    rows = {r['id']: r for r in json.load(open(j('cue_report.json'), encoding='utf-8'))['rows']}
    record('cue_onsets: clicks on cue within 3 ms', rows['c1']['status'] == 'on cue' and abs(rows['c1']['offset_ms']) <= 3
           and rows['c2']['status'] == 'on cue', f"c1 {rows['c1'].get('offset_ms')} ms, c2 {rows['c2'].get('offset_ms')} ms")
    record('cue_onsets: a cue 50 ms early in the list reads LATE', rows['c3-late']['status'] == 'LATE'
           and abs(rows['c3-late']['offset_ms'] - 50) <= 3, f"{rows['c3-late'].get('offset_ms')} ms")
    record('cue_onsets: silent cues distinguish quiet from a new sound',
           rows['quiet']['status'] == 'quiet as intended' and rows['not-quiet']['status'] == 'UNEXPECTED SOUND')

    code, out = tool('cue_onsets.py', j('master.wav'), j('cues.json'), '--chance', 100, '--json', j('cue_chance.json'))
    ch = json.load(open(j('cue_chance.json'), encoding='utf-8'))['summary'].get('chance', {})
    record('cue_onsets: sparse clicks beat the chance baseline', ch.get('verdict') == 'above chance',
           f"hit rate {json.load(open(j('cue_chance.json'), encoding='utf-8'))['summary']['hit_rate']} vs chance p95 "
           f"{ch.get('p95_hit_rate')}")
    dense = rng.standard_normal(int(rate * 4)) * 0.05
    for k in range(0, len(dense), int(0.09 * rate)):  # a click every 90 ms: onsets everywhere
        dense[k:k + 240] += 0.6
    write_wav(j('dense.wav'), dense)
    with open(j('cues_dense.json'), 'w', encoding='utf-8') as fh:
        json.dump({'events': [{'id': f'd{i}', 't': t, 'sound': 'required'} for i, t in enumerate((0.7, 1.4, 2.1, 2.8, 3.3))]}, fh)
    code, out = tool('cue_onsets.py', j('dense.wav'), j('cues_dense.json'), '--chance', 100, '--json', j('cue_dense.json'))
    chd = json.load(open(j('cue_dense.json'), encoding='utf-8'))['summary'].get('chance', {})
    record('cue_onsets: dense audio is reported as inconclusive against chance',
           str(chd.get('verdict', '')).startswith('inconclusive'), chd.get('verdict', out[-120:]))
    with open(j('cues_lint.json'), 'w', encoding='utf-8') as fh:
        json.dump({'events': [{'id': 'a', 't': 0.5}, {'id': 'b', 't': 0.52}, {'id': 'hush', 't': 1.25, 'sound': 'silent',
                                                                            'window_ms': 400}, {'id': 'c', 't': 1.3}]}, fh)
    code, out = tool('cue_onsets.py', j('master.wav'), j('cues_lint.json'), '--json', j('cue_lint.json'))
    lint_notes = json.load(open(j('cue_lint.json'), encoding='utf-8'))['lint']
    record('cue_onsets: lints stacked cues and a sound planned inside a silence',
           any('ms apart' in x for x in lint_notes) and any('inside silent window' in x for x in lint_notes),
           f'{len(lint_notes)} lint note(s)')

    # 10b. Audio edges and mono fold-down.
    edge = rng.standard_normal(int(rate * 2)) * 0.05
    edge[:96] = 0.9                                      # full level on the first samples: a click
    stereo = np.stack([edge, -edge], axis=1)              # anti-phase: vanishes in mono
    ff('-f', 'f32le', '-ar', str(rate), '-ac', '2', '-i', '-', '-c:a', 'pcm_s16le', j('edges.wav'),
       stdin=stereo.astype('float32').tobytes())
    ff('-f', 'lavfi', '-i', 'color=c=gray:s=320x180:d=2:r=30', '-i', j('edges.wav'), '-map', '0:v', '-map', '1:a',
       '-vf', TAG709, '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', '-shortest', j('edges.mp4'))
    code, out = tool('qc_file.py', j('edges.mp4'), '--json', j('edges.json'))
    rep = json.load(open(j('edges.json'), encoding='utf-8'))
    record('qc_file: flags sound at level on the first samples',
           (rep['audio_edges']['head_first_5ms_peak_dbfs'] or -999) > -40,
           f"first 5 ms peak {rep['audio_edges']['head_first_5ms_peak_dbfs']} dBFS")
    record('qc_file: flags out-of-phase stereo through the mono fold-down',
           (rep['mono_fold_down']['drop_lu'] or 0) > 3, f"drop {rep['mono_fold_down']['drop_lu']} LU")

    # 10c. Holds and first motion.
    still = [square_frame(10)] * 60
    encode_frames(j('hold.mp4'), [square_frame(i) for i in range(20)] + still + [square_frame(i) for i in range(20, 40)], 30)
    code, out = tool('motion_scan.py', j('hold.mp4'), '--json', j('hold.json'))
    hm = json.load(open(j('hold.json'), encoding='utf-8'))
    record('motion_scan: lists a two-second hold and the first motion',
           any(abs(h['seconds'] - 2.0) <= 0.1 for h in hm['holds']) and hm['first_motion_s'] is not None
           and hm['first_motion_s'] <= 0.05, f"holds {[(h['start_s'], h['seconds']) for h in hm['holds']]}")

    # 11. Change proof between two versions.
    ff('-i', j('good.mp4'), '-vf', "drawbox=x=40:y=40:w=200:h=60:color=red@1:t=fill:enable='between(t,1.0,1.5)'",
       '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', j('v2.mp4'))
    ff('-i', j('good.mp4'), '-an', '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', j('v1.mp4'))
    code, out = tool('compare_versions.py', j('v2.mp4'), j('v1.mp4'), '--json', j('change.json'))
    ch = json.load(open(j('change.json'), encoding='utf-8'))
    run0 = ch['changed_runs'][0] if ch['changed_runs'] else None
    record('compare_versions: locates the 1.0-1.5 s change', code == 1 and run0 and abs(run0['start_s'] - 1.0) < 0.05
           and abs(run0['end_s'] - 1.5) < 0.05, f"{run0['start_s']}-{run0['end_s']} s" if run0 else out[-120:])
    code, _ = tool('compare_versions.py', j('v2.mp4'), j('v1.mp4'), '--expect', '0.9-1.6')
    record('compare_versions: an expected change passes', code == 0)

    # 12. Flash screen golden cases (synthetic 60 fps clips with known answers).
    W, H, FPS, SEC = 320, 180, 60, 3

    def blink(period, on_frames, on_rgb, off_rgb=(0, 0, 0), box=None):
        def fn(i):
            f = np.zeros((H, W, 3), np.uint8)
            f[:] = off_rgb
            if i % period < on_frames:
                if box is None:
                    f[:] = on_rgb
                else:
                    x, y, w, h = box
                    f[y:y + h, x:x + w] = on_rgb
            return f
        return fn

    cases = [
        ('A_fullframe_4Hz_white', blink(15, 7, (255, 255, 255)), True),
        ('B_fullframe_2Hz_white', blink(30, 15, (255, 255, 255)), False),
        ('C_small_square_5Hz', blink(12, 6, (255, 255, 255), box=(10, 10, 14, 14)), False),
        ('D_large_square_5Hz', blink(12, 6, (255, 255, 255), box=(0, 0, 60, 34)), True),
        ('E_red_5Hz', blink(12, 6, (255, 0, 0)), True),
        ('F_slow_fade', lambda i: np.full((H, W, 3), int(255 * i / (FPS * SEC)), np.uint8), False),
        ('G_grey_flicker_small_amplitude', blink(12, 6, (40, 40, 40), off_rgb=(30, 30, 30)), False),
        ('H_square_15pct_of_window_5Hz', blink(12, 6, (255, 255, 255), box=(20, 15, 40, 23)), False),
        ('I_bright_bg_dark_flash_5Hz', blink(12, 6, (20, 20, 20), off_rgb=(230, 230, 230)), True),
        ('J_dim_12pct_fullframe_5Hz', blink(12, 6, (130, 130, 130), off_rgb=(90, 90, 90)), True),
        ('K_dim_7.6pct_fullframe_5Hz', blink(12, 6, (110, 110, 110), off_rgb=(80, 80, 80)), False),
    ]
    flash_ok = True
    for name, fn, expect in cases:
        path = j(f'flash_{name}.mp4')
        data = b''.join(fn(i).astype(np.uint8).tobytes() for i in range(FPS * SEC))
        ff('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264',
           '-crf', '12', '-pix_fmt', 'yuv420p', path, stdin=data)
        code, out = tool('flash_scan.py', path)
        good = (code == 1) == expect
        flash_ok &= good
        if not good:
            record(f'flash_scan golden case {name}', False, out.strip()[-160:])
    record('flash_scan: all 11 golden cases', flash_ok)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f'\n{passed}/{len(RESULTS)} checks passed. Files: {work}' if a.keep else
          f'\n{passed}/{len(RESULTS)} checks passed.')
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if passed == len(RESULTS) else 1


if __name__ == '__main__':
    sys.exit(main())
