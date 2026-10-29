"""Regression cases for deterministic revisions, footage holds and small-area motion."""

import hashlib
import json
import subprocess

import numpy as np


def encode(path, frames, codec, options=()):
    """Encode synthetic RGB frames in one foreground FFmpeg process."""
    height, width = frames[0].shape[:2]
    cmd = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s', f'{width}x{height}', '-r', '30', '-i', '-', '-c:v', codec, *options, path]
    result = subprocess.run(cmd, input=b''.join(frame.tobytes() for frame in frames), capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace')[-300:])


def read(path):
    """Read a JSON report."""
    with open(path, encoding='utf-8') as stream:
        return json.load(stream)


def run_qcfix_cases(tool, record, j, scripts_dir):
    """Exercise known frame ranges, duplicates and localised motion."""
    rng = np.random.default_rng(143)
    base = []
    changed = []
    for i in range(90):
        frame = rng.integers(25, 100, (90, 160, 3), dtype=np.uint8)
        base.append(frame)
        edit = frame.copy()
        if 30 <= i <= 49:
            edit[30:60, 45:115] = 240
        changed.append(edit)
    for label, frames in [('base', base), ('edit', changed)]:
        encode(j('q_' + label + '.mkv'), frames, 'ffv1', ['-pix_fmt', 'bgr0'])
        lossy_frames = [frame.copy() for frame in frames]
        if label == 'edit':
            # A small controlled outside difference models encoder ripple even when x264 emits none.
            for frame in lossy_frames[50:]:
                frame[0:8, 0:8] = np.minimum(frame[0:8, 0:8].astype(int) + 4, 255).astype(np.uint8)
        encode(j('q_' + label + '.mp4'), lossy_frames, 'libx264', ['-crf', '18', '-pix_fmt', 'yuv420p'])
    encode(j('q_base_again.mp4'), base, 'libx264', ['-crf', '18', '-pix_fmt', 'yuv420p'])
    with open(j('q_base.mp4'), 'rb') as first, open(j('q_base_again.mp4'), 'rb') as second:
        identical = hashlib.sha256(first.read()).digest() == hashlib.sha256(second.read()).digest()
    record('qcfix: unchanged lossy re-render is bit-identical', identical)
    code, out = tool('compare_versions.py', j('q_edit.mp4'), j('q_base.mp4'), '--expect', '1-1.6334',
                     '--json', j('q_lossy.json'))
    report = read(j('q_lossy.json'))
    outside_differs = any(row['psnr'] != 'inf' for row in report['per_frame_psnr'][50:])
    record('qcfix: deterministic re-render rejects encoder ripple outside edit', code == 0
           and outside_differs and bool(report['changed_runs'])
           and all(row['expected'] for row in report['changed_runs']), out[-180:])
    rows = report['per_frame_psnr']
    record('qcfix: PSNR frames use zero-based indices and presentation times', len(rows) == 90
           and rows[0]['frame'] == 0 and rows[30]['frame'] == 30 and abs(rows[30]['pts'] - 1) < 0.001)
    code, out = tool('compare_versions.py', j('q_edit.mkv'), j('q_base.mkv'), '--lossless-proof',
                     '--expect', '1-1.634', '--json', j('q_exact.json'))
    proof = read(j('q_exact.json'))['lossless_proof']
    spans = [(row['start_frame'], row['end_frame']) for row in proof['changed_ranges']]
    same = [(row['start_frame'], row['end_frame']) for row in proof['identical_ranges']]
    record('qcfix: lossless proof gives exact inclusive frame ranges', code == 0 and spans == [(30, 49)]
           and same == [(0, 29), (50, 89)], str(proof))
    frames = []
    for i in range(60):
        frame = np.full((90, 160, 3), 40, np.uint8)
        frame[20:70, 15 + i:55 + i] = 190
        frames.append(frame)
    frames[20] = frames[19].copy()
    frames[20][0, 0] += 1
    frames[40] = frames[39].copy()
    encode(j('q_footage.mkv'), frames, 'ffv1', ['-pix_fmt', 'bgr0'])
    code, out = tool('motion_scan.py', j('q_footage.mkv'), '--footage', '--json', j('q_footage.json'))
    report = read(j('q_footage.json'))
    ids = [row['frame'] for row in report['stutter_frames']]
    near = [row['frame'] for row in report['near_holds']]
    record('qcfix: footage near-hold is informational and exact duplicate fails', code == 1
           and 20 in near and 40 in ids and 20 not in ids, f'near {near}, duplicate {ids}')
    frames[40] = frames[41].copy()
    frames[40][0, 0] += 1
    encode(j('q_near.mkv'), frames, 'ffv1', ['-pix_fmt', 'bgr0'])
    code, out = tool('motion_scan.py', j('q_near.mkv'), '--footage', '--json', j('q_near.json'))
    report = read(j('q_near.json'))
    record('qcfix: footage two-frame near-holds pass', code == 0 and bool(report['near_holds']), out[-180:])
    dots = []
    for i in range(60):
        frame = np.zeros((180, 320, 3), np.uint8)
        x = 100 + i % 20
        frame[80:85, x:x + 5] = 255
        dots.append(frame)
    encode(j('q_dots.mkv'), dots, 'ffv1', ['-pix_fmt', 'bgr0'])
    code, out = tool('motion_scan.py', j('q_dots.mkv'), '--max-still-share', '0.1',
                     '--json', j('q_dots.json'))
    pace = read(j('q_dots.json'))['pace']
    record('qcfix: small moving area reports regional pace and inconclusive contract', code == 1
           and 0 < pace['moving_area_fraction'] < 0.05 and pace['moving_region']['still_share'] < 1
           and pace['gates']['max_still_share']['pass'] is None, out[-240:])
