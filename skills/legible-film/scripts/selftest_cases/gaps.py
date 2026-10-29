#!/usr/bin/env python3
"""Known-answer region-presence and audio-rate cases loaded by selftest.py.

Integration: add 'gaps' to CASE_MODULES; selftest.py calls
run_gaps_cases(tool, record, j, scripts_dir) with its existing helpers.

  python -I scripts/selftest_cases/gaps.py --scripts scripts --keep work/gaps-cases

Original synthetic media only. Needs numpy, Pillow, FFmpeg and ffprobe. Exit 0
nothing to fix (all cases pass), 1 inspect or fix, 2 could not run. These cases
prove synthetic measurements and the measured repair, not any real film's quality,
readability, semantic correctness or normal-speed viewing/listening approval.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def run_gaps_cases(tool, record, j, scripts_dir):
    spec = importlib.util.spec_from_file_location('gaps_sync', Path(scripts_dir) / 'sync_check.py')
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    ffmpeg = sync.find_tool('ffmpeg')

    def ff(*args, data=None):
        r = subprocess.run([ffmpeg, '-v', 'error', '-y', *map(str, args)], input=data, capture_output=True)
        if r.returncode:
            raise RuntimeError(r.stderr.decode(errors='replace')[-800:])

    def report(name):
        return json.loads(Path(j(name)).read_text(encoding='utf-8'))

    width, height = 240, 136
    region = (20, 80, 200, 44)
    good = Image.new('RGB', (width, height), (22, 22, 22))
    draw = ImageDraw.Draw(good)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((26, 90), 'QUALIFIED ONLY', fill=(235, 235, 235), font=font)
    good = np.asarray(good)
    absent = np.full_like(good, 22)
    Image.fromarray(good[80:124, 20:220]).save(j('gaps-reference.png'))

    def video(name, frames, crf=28):
        ff('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}', '-r', '30', '-i', '-',
           '-an', '-c:v', 'libx264', '-crf', crf, '-pix_fmt', 'yuv420p', j(name),
           data=b''.join(f.tobytes() for f in frames))

    video('gaps-drop.mp4', [good] * 45 + [absent] * 15)
    video('gaps-present.mp4', [good] * 60)
    common = ('--region', ','.join(map(str, region)), '--interval', '0-2')
    code, text = tool('region_check.py', j('gaps-drop.mp4'), *common, '--reference', j('gaps-reference.png'),
                      '--json', j('gaps-drop.json'))
    r = report('gaps-drop.json')
    record('region_check: catches exactly the last 15 dropped frames (45-59)',
           code == 1 and r['failing_frames'] == list(range(45, 60)) and not r['survives_whole_interval'],
           str(r['failing_frames']))
    runs = r['failing_runs']
    record('region_check: dropout displays from 1.5 to 2.0 s, end exclusive',
           len(runs) == 1 and abs(runs[0]['start_s'] - 1.5) < 1e-6 and abs(runs[0]['end_s'] - 2) < 1e-6,
           str(runs))
    record('region_check: reports every frame and both measures', r['frames_checked'] == 60 and
           len(r['frames']) == 60 and all('structure' in f and 'ink_retention' in f for f in r['frames']))
    code, text = tool('region_check.py', j('gaps-present.mp4'), *common, '--reference', j('gaps-reference.png'),
                      '--json', j('gaps-present.json'))
    present = report('gaps-present.json')
    record('region_check: a fully present region survives CRF 28 encoding',
           code == 0 and present['survives_whole_interval'] and not present['failing_frames'],
           f"minimum score {min(f['score'] for f in present['frames'])}")
    code, _ = tool('region_check.py', j('gaps-drop.mp4'), *common, '--reference-time', .5,
                   '--json', j('gaps-time.json'))
    record('region_check: known-good time in the same video catches the same frames',
           code == 1 and report('gaps-time.json')['failing_frames'] == list(range(45, 60)))
    code, _ = tool('region_check.py', j('gaps-drop.mp4'), '--region',
                   ','.join(str(v / s) for v, s in zip(region, (width, height, width, height))),
                   '--fractions', '--interval', '0,2', '--reference-video', j('gaps-present.mp4'),
                   '--reference-time', .5, '--json', j('gaps-fraction.json'))
    record('region_check: fractional coordinates and another reference video agree',
           code == 1 and report('gaps-fraction.json')['failing_frames'] == list(range(45, 60)))
    # Same frame indices with a slow final half: timing must come from PTS.
    ff('-i', j('gaps-drop.mp4'), '-vf', "setpts='if(lt(N,45),N/(30*TB),(1.5+(N-45)/10)/TB)'",
       '-fps_mode', 'vfr', '-c:v', 'ffv1', j('gaps-vfr.mkv'))
    code, _ = tool('region_check.py', j('gaps-vfr.mkv'), '--region', '20,80,200,44', '--interval', '1.55-2.9',
                   '--reference-time', .5, '--json', j('gaps-vfr.json'))
    vfr = report('gaps-vfr.json')
    record('region_check: VFR includes the frame already displayed at interval start',
           code == 1 and vfr['frames'][0]['frame'] == 45 and abs(vfr['frames'][0]['time_s'] - 1.5) < .001 and
           vfr['failing_frames'] == list(range(45, 59)) and abs(vfr['failing_runs'][0]['end_s'] - 2.9) < .001,
           str(vfr['failing_runs']))
    bad = []
    Image.new('RGB', (200, 44), 'black').save(j('gaps-flat.png'))
    for label, args in (
            ('missing input', [j('gaps-missing.mp4'), *common, '--reference-time', .5]),
            ('uncovered interval', [j('gaps-drop.mp4'), '--region', '20,80,200,44', '--interval', '0-3', '--reference-time', .5]),
            ('flat reference', [j('gaps-drop.mp4'), *common, '--reference', j('gaps-flat.png')]),
            ('bad region', [j('gaps-drop.mp4'), '--region', '20,80,400,44', '--interval', '0-2', '--reference-time', .5]),
            ('NaN threshold', [j('gaps-drop.mp4'), *common, '--reference-time', .5, '--threshold', 'nan']),
            ('bad reference time', [j('gaps-drop.mp4'), *common, '--reference-time', 3]),
            ('unwritable output', [j('gaps-drop.mp4'), *common, '--reference-time', .5, '--json', j('gaps-reference.png', 'x.json')])):
        if tool('region_check.py', *args)[0] != 2:
            bad.append(label)
    record('region_check: seven uncheckable inputs/options/outputs return 2', not bad, ', '.join(bad) or '7 cases')
    video('gaps-single-drop.mp4', [good] * 30 + [absent] + [good] * 29)
    code, _ = tool('region_check.py', j('gaps-single-drop.mp4'), *common, '--reference-time', .5,
                   '--json', j('gaps-single-drop.json'))
    record('region_check: one missing interior frame is enough to fail',
           code == 1 and report('gaps-single-drop.json')['failing_frames'] == [30])

    # Original seeded, band-limited, non-repeating signal. A sample-rate change
    # stretches every part of it, rather than planting isolated shifted clicks.
    rate, duration = 48000, 24
    rng = np.random.default_rng(90210)
    noise = rng.standard_normal(rate * (duration + 2))
    u = np.arange(-32, 33)
    kernel = np.sinc(2 * 4500 / rate * u) * np.hanning(len(u))
    kernel /= kernel.sum()
    audio = np.convolve(noise, kernel, 'same') * .22
    ff('-f', 'f32le', '-ar', rate, '-ac', '1', '-i', '-', '-c:a', 'pcm_f32le', j('gaps-master.wav'),
       data=audio.astype('float32').tobytes())
    ff('-f', 'lavfi', '-i', f'color=c=gray:s=160x90:r=30:d={duration}', '-c:v', 'libx264',
       '-pix_fmt', 'yuv420p', j('gaps-picture.mp4'))

    def drifting(name, ratio, offset=0, master='gaps-master.wav'):
        filters = f'asetrate={rate}*{ratio},aresample={rate}'
        if offset > 0:
            filters += f',adelay={round(offset * rate)}S:all=1'
        elif offset < 0:
            filters += f',atrim=start={-offset},asetpts=PTS-STARTPTS'
        ff('-i', j('gaps-picture.mp4'), '-i', j(master), '-map', '0:v:0', '-map', '1:a:0',
           '-c:v', 'copy', '-af', filters, '-t', duration, '-c:a', 'pcm_f32le', j(name))

    def check_drift(name, ratio, offset, master='gaps-master.wav'):
        drifting(name, ratio, offset, master)
        output = name + '.json'
        code, text = tool('sync_check.py', j(name), j(master), '--windows', 8,
                          '--json', j(output))
        if not Path(j(output)).is_file():
            raise RuntimeError(f'sync_check {name} exited {code} without a report: {text[-500:]}')
        result = report(output)
        fit = result.get('drift_fit', {})
        record(f'sync_check: {ratio:g} rate ratio within .0005, offset within 1 ms ({offset:+g} s)',
               code == 1 and abs(fit.get('rate_ratio', 0) - ratio) <= .0005 and
               abs(fit.get('offset_s', 999) - offset) <= .001,
               str({k: v for k, v in fit.items() if k != 'windows'}))
        recipe = result.get('repair', {})
        record(f'sync_check: {ratio:g} prints exact duration-bound repair and preserves original windows',
               bool(recipe.get('argv')) and recipe.get('command', 'MISSING') in text and
               'asetrate=' in recipe.get('audio_filter', '') and 'aresample=' in recipe.get('audio_filter', '') and
               'asetpts=' in recipe.get('audio_filter', '') and 'apad' in recipe.get('audio_filter', '') and
               'atrim=duration=24.' in recipe.get('audio_filter', '') and '-shortest' not in recipe.get('argv', []) and
               len(result.get('original_windows', [])) == 8, recipe.get('command', str(recipe)))
        if recipe.get('argv'):
            applied = subprocess.run(recipe['argv'], capture_output=True)
            if applied.returncode:
                raise RuntimeError(applied.stderr.decode(errors='replace')[-800:])
            code, text = tool('sync_check.py', recipe['output'], j(master), '--windows', 8,
                              '--tolerance-ms', 5, '--json', j(name + '-repaired.json'))
            repaired = report(name + '-repaired.json')
            record(f'sync_check: {ratio:g} printed repair brings every window within 5 ms',
                   code == 0 and len(repaired['windows']) == 8 and
                   all(abs(r['lag_ms']) <= 5 and r['correlation'] >= .8 and not r['ambiguous']
                       for r in repaired['windows']),
                   str([(r['time_s'], r['lag_ms'], r['correlation']) for r in repaired['windows']]))
            p = subprocess.run([sync.find_tool('ffprobe'), '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                '-show_entries', 'stream=nb_read_frames,duration', '-of', 'json', recipe['output']],
                               capture_output=True, text=True)
            picture = json.loads(p.stdout)['streams'][0]
            record(f'sync_check: {ratio:g} repair preserves all 720 picture frames and 24 s',
                   picture['nb_read_frames'] == '720' and abs(float(picture['duration']) - 24) < .001)
        return result

    check_drift('gaps-slow.mkv', .99, 0)
    check_drift('gaps-slow-offset.mkv', .99, .043)
    check_drift('gaps-fast-offset.mkv', 1.01, -.037)
    # Every short probe lands in silence. The original confident window lags
    # must still yield a rate fit, using each sound's energy centroid.
    sparse = np.zeros_like(audio)
    for at in np.arange(1, duration + 2, 3):
        start, count = round(at * rate), round(.015 * rate)
        sparse[start:start + count] = 3 * audio[start:start + count] * np.hanning(count)
    ff('-f', 'f32le', '-ar', rate, '-ac', '1', '-i', '-', '-c:a', 'pcm_f32le', j('gaps-sparse-master.wav'),
       data=sparse.astype('float32').tobytes())
    sparse_result = check_drift('gaps-sparse.mkv', .99, 0, 'gaps-sparse-master.wav')
    record('sync_check: sparse effects already have confident original windows; fit adds evidence',
           sparse_result['summary']['confident_windows'] == 8 and 'drift_fit' in sparse_result and
           sparse_result['windows'] == sparse_result.get('original_windows'))
    # A discontinuous edit must not produce a single clock-rate command.
    t = np.arange(len(audio)) / rate
    edited = np.interp(t - np.where(t < 12, .015, .180), t, audio, left=0, right=0)
    ff('-f', 'f32le', '-ar', rate, '-ac', '1', '-i', '-', '-c:a', 'pcm_f32le', j('gaps-edit.wav'),
       data=edited.astype('float32').tobytes())
    code, _ = tool('sync_check.py', j('gaps-edit.wav'), j('gaps-master.wav'), '--windows', 8,
                   '--json', j('gaps-edit.json'))
    result = report('gaps-edit.json')
    record('sync_check: a step edit is flagged without a global rate repair',
           code == 1 and 'drift_fit' not in result and 'repair' not in result)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--scripts', required=True)
    p.add_argument('--keep', required=True)
    a = p.parse_args()
    root = Path(a.keep).resolve()
    root.mkdir(parents=True, exist_ok=True)
    results = []

    def record(name, ok, detail=''):
        results.append(bool(ok))
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  [{detail}]' if detail else ''), flush=True)

    def tool(script, *args):
        r = subprocess.run([sys.executable, '-I', str(Path(a.scripts).resolve() / script), *map(str, args)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        return r.returncode, r.stdout + r.stderr

    if not all(shutil.which(t) for t in ('ffmpeg', 'ffprobe')):
        print('FFmpeg and ffprobe required', file=sys.stderr)
        return 2
    try:
        run_gaps_cases(tool, record, lambda *parts: str(root.joinpath(*parts)), a.scripts)
    except Exception as exc:
        record('gaps cases ran to the end', False, repr(exc))
    print(f'{sum(results)}/{len(results)} checks passed. Files: {root}')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
