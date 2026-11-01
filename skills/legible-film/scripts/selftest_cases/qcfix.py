"""Regression cases for deterministic revisions, footage holds and small-area motion."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

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


def check_display_geometry_and_silence(tool, record, j, scripts_dir):
    """QC compares the shown canvas and distinguishes silence from unavailable audio."""
    import importlib.util
    import struct

    base = Path(j('qc-geometry-base.mp4'))
    rotated = Path(j('qc-geometry-rotated.mp4'))
    wide = Path(j('qc-geometry-sar.mp4'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=2',
                    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', '2', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(base)], check=True, capture_output=True)
    data = bytearray(base.read_bytes())
    track = data.find(b'tkhd')
    if track < 0:
        raise RuntimeError('synthetic MP4 has no track header')
    matrix = track + (56 if data[track + 4] == 1 else 44)
    identity = (65536, 0, 0, 0, 65536, 0, 0, 0, 1073741824)
    if struct.unpack_from('>9i', data, matrix) != identity:
        raise RuntimeError('synthetic video track does not have an identity display matrix')
    struct.pack_into('>9i', data, matrix, 0, -65536, 0, 65536, 0, 0, 0, 0, 1073741824)
    rotated.write_bytes(data)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(base), '-vf', 'setsar=2', '-c:v', 'libx264',
                    '-c:a', 'copy', str(wide)], check=True, capture_output=True)
    for name, path, dims in (('rotated', rotated, (90, 160)), ('non-square pixels', wide, (320, 90))):
        report = Path(j('qc-geometry-' + name.replace(' ', '-') + '.json'))
        code, output = tool('qc_file.py', path, '--technical', '--spec', f'{dims[0]}x{dims[1]}', '--json', report)
        data = read(report) if report.is_file() else {}
        crop = data.get('technical', {}).get('crop', {})
        rect = crop.get('crop') or []
        inside = len(rect) == 4 and rect[0] + rect[2] <= dims[0] and rect[1] + rect[3] <= dims[1]
        checks = data.get('checks', {})
        record('qc_file: ' + name + ' uses displayed square-pixel geometry',
               code == 0 and crop.get('width') == dims[0] and crop.get('height') == dims[1] and inside
               and checks.get('width', {}).get('pass') and checks.get('height', {}).get('pass'),
               str((crop, checks, output[-200:])))
        if name == 'rotated':
            edges = [line for line in output.splitlines() if 'edges:' in line.lower()]
            record('qc_file: silent measured edges read as digital silence',
                   'digital silence' in output.lower() and 'None dBFS' not in output, str(edges))
    spec = importlib.util.spec_from_file_location('qc_silence_cases', Path(scripts_dir) / 'qc_file.py')
    qc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qc)
    formatter = getattr(qc, 'edge_level_text', lambda value, available: 'missing formatter')
    record('qc_file: unavailable edge is not called digital silence',
           formatter(None, False) == 'unavailable' and formatter(None, True) == 'digital silence (16-bit decode)'
           and formatter(-12.3, True) == '-12.3 dBFS', formatter(None, False))


def check_mid_film_offset(tool, record, j):
    """Six frames added at 1.0 s, and six removed there, are paired directly before that point and shifted after
    it; a time between frames moves to the frame where the pictures match; the start offset stays as it was."""
    rng = np.random.default_rng(611)
    base = [rng.integers(25, 230, (90, 160, 3), dtype=np.uint8) for _ in range(60)]
    added = [rng.integers(25, 230, (90, 160, 3), dtype=np.uint8) for _ in range(6)]
    encode(j('mid_base.mkv'), base, 'ffv1', ['-pix_fmt', 'bgr0'])
    encode(j('mid_added.mkv'), base[:30] + added + base[30:], 'ffv1', ['-pix_fmt', 'bgr0'])
    encode(j('mid_removed.mkv'), base[:30] + base[36:], 'ffv1', ['-pix_fmt', 'bgr0'])

    def compare(name, *options):
        out = j(name + '.json')
        if os.path.exists(out):
            os.remove(out)
        code, output = tool('compare_versions.py', *options, '--json', out)
        return code, output, read(out) if os.path.exists(out) else {}

    code, out, report = compare('mid_added', j('mid_added.mkv'), j('mid_base.mkv'), '--offset-frames', '6',
                                '--offset-at', '1.0')
    runs = report.get('changed_runs', [])
    record('compare_versions: frames added mid-film pair directly before 1.0 s and shifted after, the added frames '
           'reported', code == 1 and report.get('identical_frames') == 60 and len(runs) == 1
           and runs[0]['frames'] == 6 and abs(runs[0]['start_s'] - 1.0) < 1e-3
           and abs(runs[0]['end_s'] - 35 / 30) < 1e-3 and 'added' in runs[0].get('unmatched', ''), out[-400:])
    code, out, _ = compare('mid_added_expected', j('mid_added.mkv'), j('mid_base.mkv'), '--offset-frames', '6',
                           '--offset-at', '1.0', '--expect', '1-1.2')
    record('compare_versions: added frames named in --expect leave nothing unexpected', code == 0, out[-300:])
    code, out, report = compare('mid_snap', j('mid_added.mkv'), j('mid_base.mkv'), '--offset-frames', '6',
                                '--offset-at', '0.96')
    offset = report.get('offset', {})
    record('compare_versions: a stated time between frames moves to the frame where the pictures match',
           code == 1 and offset.get('stated_frame') == 29 and offset.get('at_frame') == 30 and offset.get('snapped')
           and report.get('identical_frames') == 60 and 'match best at frame 30' in out, out[-400:])
    code, out, report = compare('mid_removed', j('mid_removed.mkv'), j('mid_base.mkv'), '--offset-frames', '-6',
                                '--offset-at', '1.0')
    runs = report.get('changed_runs', [])
    record('compare_versions: frames removed mid-film pair around 1.0 s and the removal point is reported',
           code == 1 and report.get('identical_frames') == 54 and report.get('frames_compared') == 54
           and len(runs) == 1 and runs[0]['frames'] == 6 and runs[0]['start_s'] == runs[0]['end_s'] == 1.0
           and 'removed' in runs[0].get('unmatched', ''), out[-400:])
    code, out, report = compare('mid_exact', j('mid_added.mkv'), j('mid_base.mkv'), '--offset-frames', '6',
                                '--offset-at', '1.0', '--lossless-proof')
    proof = report.get('lossless_proof', {})
    same = [(row['start_frame'], row['end_frame']) for row in proof.get('identical_ranges', [])]
    record('compare_versions: lossless proof ranges split at a mid-film offset, in NEW frame numbers',
           same == [(0, 29), (36, 65)] and proof.get('changed_ranges') == [], str(proof)[:400])
    code, out, report = compare('mid_start', j('mid_added.mkv'), j('mid_base.mkv'), '--offset-frames', '6')
    rows = report.get('per_frame_psnr', [])
    record('compare_versions: without --offset-at the offset still drops frames from the start, unreported',
           code == 1 and 'offset' not in report and rows and rows[0]['frame'] == 6
           and not any('unmatched' in run for run in report.get('changed_runs', [])), out[-300:])
    code, out, _ = compare('mid_bad', j('mid_added.mkv'), j('mid_base.mkv'), '--offset-at', '1.0')
    record('compare_versions: --offset-at without --offset-frames cannot run', code == 2 and '--offset-at' in out,
           out[-200:])


def check_change_region(tool, record, j):
    """A lower-third bar changed in ten frames of a lossy render is located: the 4x4 cell that changed most is named
    (with that cell's own PSNR, below the whole frame's) and the changed area is boxed in NEW's pixels."""
    ramp = np.linspace(40, 200, 320, dtype=np.float64)
    base_frame = np.repeat(np.repeat(ramp[None, :, None], 180, axis=0), 3, axis=2).astype(np.uint8)
    edited = base_frame.copy()
    edited[140:160, 90:150] = (250, 240, 40)
    encode(j('region_base.mp4'), [base_frame] * 30, 'libx264', ['-crf', '16', '-pix_fmt', 'yuv420p'])
    encode(j('region_edit.mp4'), [base_frame] * 10 + [edited] * 10 + [base_frame] * 10, 'libx264',
           ['-crf', '16', '-pix_fmt', 'yuv420p'])
    out = j('region.json')
    code, output = tool('compare_versions.py', j('region_edit.mp4'), j('region_base.mp4'), '--json', out)
    runs = read(out).get('changed_runs', []) if os.path.exists(out) else []
    region = runs[0].get('region', {}) if len(runs) == 1 else {}
    box = region.get('box') or [0, 0, 0, 0]
    record('compare_versions: a changed range names the cell that changed most and boxes the changed area',
           code == 1 and region.get('cell') == 'bottom, centre-left'
           and all(abs(got - want) <= 10 for got, want in zip(box, (90, 140, 60, 20)))
           and region.get('cell_psnr_db', 99) < runs[0]['min_psnr_db']
           and 'most changed: bottom, centre-left' in output, output[-600:])


def run_qcfix_cases(tool, record, j, scripts_dir):
    """Exercise known frame ranges, duplicates and localised motion."""
    check_display_geometry_and_silence(tool, record, j, scripts_dir)
    check_mid_film_offset(tool, record, j)
    check_change_region(tool, record, j)
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
