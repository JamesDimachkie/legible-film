#!/usr/bin/env python3
"""Deterministic QC of a delivered video file: the checks a script can settle.

Runs ffprobe and ffmpeg on the exact file you will deliver and reports:
  - container and stream metadata, compared with an expected spec;
  - a full decode of every video and audio stream (errors, decoded frame count, decoded length);
  - pixel format, colour tags, sample aspect ratio, rotation and MP4 fast start;
  - integrated loudness, loudness range and true peak (ITU-R BS.1770, via ffmpeg's ebur128);
  - with --lossy-check, the true peak after an AAC re-encode like the one a platform makes;
  - with --detect, candidate black, frozen and silent intervals to inspect.

It does not judge picture, motion, sound quality, legibility, flashing (use flash_scan.py),
claims or rights. Measurements describe the file; they are not a verdict on the film.

Examples:
  python qc_file.py film.mp4
  python qc_file.py film.mp4 --spec 1920x1080@60 --duration 32 --pix-fmt yuv420p --color bt709 \\
      --audio required --sample-rate 48000 --max-true-peak -1 --lossy-check --detect --json qc.json

Exit codes: 0 every requested check passed (or none was requested), 1 a check failed,
2 the file could not be read or a tool is missing.
"""

import argparse
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from fractions import Fraction


def find_tool(name, explicit=None):
    candidate = explicit or os.environ.get(name.upper())
    if candidate:
        return candidate if (os.path.isfile(candidate) or shutil.which(candidate)) else None
    return shutil.which(name)


def run(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, check=False)


def as_fraction(value):
    try:
        f = Fraction(str(value))
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def as_float(value):
    try:
        f = float(value)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def mp4_faststart(path):
    """True when the moov box precedes mdat (playback can start before the download ends)."""
    order = []
    try:
        with open(path, 'rb') as fh:
            size_total = os.fstat(fh.fileno()).st_size
            pos = 0
            for _ in range(64):
                if pos + 8 > size_total:
                    break
                fh.seek(pos)
                header = fh.read(8)
                size, kind = struct.unpack('>I4s', header)
                if size == 1:
                    size = struct.unpack('>Q', fh.read(8))[0]
                elif size == 0:
                    size = size_total - pos
                kind = kind.decode('latin-1')
                if kind in ('moov', 'mdat'):
                    order.append(kind)
                if size < 8:
                    break
                pos += size
    except OSError:
        return None
    if 'moov' not in order or 'mdat' not in order:
        return None
    return order.index('moov') < order.index('mdat')


def rotation_of(stream):
    for side in stream.get('side_data_list', []) or []:
        if 'rotation' in side:
            return as_float(side['rotation'])
    return as_float((stream.get('tags') or {}).get('rotate'))


def decode_all(ffmpeg, path):
    """Decode every video and audio stream; return errors, decoded video frames and decoded length."""
    base = [ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-v', 'error', '-progress', 'pipe:1', '-i', path,
            '-map', '0:v?', '-map', '0:a?']
    result = run(base + ['-fps_mode', 'passthrough', '-f', 'null', '-'])
    if result.returncode and 'fps_mode' in result.stderr:  # ffmpeg older than 5.1
        result = run(base + ['-vsync', 'passthrough', '-f', 'null', '-'])
    frames, out_us = None, None
    for line in result.stdout.splitlines():
        key, _, value = line.partition('=')
        if key == 'frame':
            frames = int(value) if value.strip().isdigit() else frames
        elif key in ('out_time_us', 'out_time_ms'):  # both are microseconds in ffmpeg
            out_us = as_float(value) if value.strip() not in ('N/A', '') else out_us
    errors = [line for line in result.stderr.splitlines() if line.strip()]
    return {'ok': result.returncode == 0 and not errors, 'returncode': result.returncode,
            'errors': errors[:20], 'error_count': len(errors), 'decoded_video_frames': frames,
            'decoded_length_s': round(out_us / 1e6, 6) if out_us else None}


SUMMARY = {
    'integrated_lufs': re.compile(r'I:\s+(-?[\d.]+|-inf)\s+LUFS'),
    'loudness_range_lu': re.compile(r'LRA:\s+(-?[\d.]+)\s+LU\b'),
    'true_peak_dbtp': re.compile(r'True peak:\s*\n\s*Peak:\s+(-?[\d.]+|-inf)\s+dBFS'),
}


def loudness(ffmpeg, path, stream='0:a:0', pre_filter=''):
    chain = (pre_filter + ',' if pre_filter else '') + 'ebur128=peak=true:framelog=quiet'
    result = run([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-progress', 'pipe:1', '-i', path,
                  '-map', stream, '-af', chain, '-f', 'null', '-'])
    if result.returncode:
        return {'error': (result.stderr.strip().splitlines() or ['ffmpeg failed'])[-1]}
    tail = result.stderr[result.stderr.rfind('Summary:'):]
    out = {}
    for key, pattern in SUMMARY.items():
        match = pattern.search(tail)
        value = match.group(1) if match else None
        out[key] = None if value in (None, '-inf') else float(value)
    out_us = None
    for line in result.stdout.splitlines():
        key, _, value = line.partition('=')
        if key in ('out_time_us', 'out_time_ms') and value.strip() not in ('N/A', ''):
            out_us = as_float(value)
    out['decoded_audio_length_s'] = round(out_us / 1e6, 6) if out_us else None
    return out


def pcm_levels(ffmpeg, path, start_args, seconds, channels=1):
    """Peak and RMS (dBFS) of a short stretch over all channels (no downmix, which can cancel
    out-of-phase content), decoded to 16-bit PCM; stdlib only."""
    from array import array
    channels = max(1, int(channels or 1))
    result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', *start_args, '-i', path, '-map', '0:a:0',
                             '-t', str(seconds), '-ac', str(channels), '-ar', '48000', '-f', 's16le', '-'],
                            capture_output=True, check=False)
    samples = array('h')
    samples.frombytes(result.stdout[:len(result.stdout) // 2 * 2])
    if sys.byteorder == 'big':
        samples.byteswap()
    if not samples:
        return None

    def db(x):
        return round(20 * math.log10(x / 32768.0), 1) if x > 0 else None

    first5 = samples[:240 * channels]
    last10 = samples[-480 * channels:]
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    return {'peak_dbfs': db(max(abs(min(samples)), max(samples))), 'rms_dbfs': db(rms),
            'first_5ms_peak_dbfs': db(max(abs(min(first5)), max(first5))),
            'last_10ms_peak_dbfs': db(max(abs(min(last10)), max(last10)))}


def audio_edges(ffmpeg, path, channels):
    """Levels at the head and tail: a sound at full level on sample 0, or a tail cut mid-sound, clicks."""
    head = pcm_levels(ffmpeg, path, [], 0.05, channels)
    tail = pcm_levels(ffmpeg, path, ['-sseof', '-0.05'], 0.05, channels)
    out = {'head_first_5ms_peak_dbfs': head and head['first_5ms_peak_dbfs'],
           'head_50ms_rms_dbfs': head and head['rms_dbfs'],
           'tail_50ms_rms_dbfs': tail and tail['rms_dbfs'],
           'tail_last_10ms_peak_dbfs': tail and tail['last_10ms_peak_dbfs']}
    notes = []
    if out['head_first_5ms_peak_dbfs'] is not None and out['head_first_5ms_peak_dbfs'] > -40:
        notes.append('sound at level in the first 5 ms: a click unless a hit is designed for frame 0')
    if out['tail_last_10ms_peak_dbfs'] is not None and out['tail_last_10ms_peak_dbfs'] > -60:
        notes.append('the last 10 ms is not near silence: check for a cut-off tail unless the ending is a designed hard stop')
    out['notes'] = notes
    return out


def lossy_true_peak(ffmpeg, path, bitrate):
    with tempfile.TemporaryDirectory() as tmp:
        encoded = os.path.join(tmp, 'reencode.m4a')
        result = run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', path, '-map', '0:a:0',
                      '-c:a', 'aac', '-b:a', bitrate, encoded])
        if result.returncode:
            return {'error': (result.stderr.strip().splitlines() or ['encode failed'])[-1]}
        measured = loudness(ffmpeg, encoded)
    return {'bitrate': bitrate, 'true_peak_dbtp': measured.get('true_peak_dbtp'),
            'integrated_lufs': measured.get('integrated_lufs')}


def detect(ffmpeg, path, has_audio, duration):
    video_chain = '[0:v:0]blackdetect=d=0.10:pic_th=0.98:pix_th=0.10,freezedetect=n=-60dB:d=0.50[v]'
    graph, maps = video_chain, ['-map', '[v]']
    if has_audio:
        graph += ';[0:a:0]silencedetect=n=-50dB:d=0.50[a]'
        maps += ['-map', '[a]']
    result = run([ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-i', path, '-filter_complex', graph] + maps
                 + ['-f', 'null', '-'])
    if result.returncode:
        return {'error': (result.stderr.strip().splitlines() or ['ffmpeg failed'])[-1]}
    text = result.stderr

    def pairs(start_key, end_key):
        starts = [float(v) for v in re.findall(start_key + r'\s*:?\s*(-?[\d.]+)', text)]
        ends = [float(v) for v in re.findall(end_key + r'\s*:?\s*(-?[\d.]+)', text)]
        out = []
        for i, start in enumerate(starts):
            end = ends[i] if i < len(ends) else duration
            out.append([round(start, 3), round(end, 3) if end is not None else None])
        return out

    return {'black': pairs('black_start', 'black_end'),
            'frozen': pairs('freeze_start', 'freeze_end'),
            'silent': pairs('silence_start', 'silence_end') if has_audio else [],
            'note': 'Candidates to inspect in context; designed holds, fades and pauses are expected.'}


PATCH = re.compile(r'\s*([\d.]+)\s*@\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*=\s*#?([0-9a-fA-F]{6})\s*')


def color_patch(ffmpeg, path, spec, tolerance):
    """Decode a flat region and compare its mean RGB with an expected colour."""
    match = PATCH.fullmatch(spec)
    if not match:
        return {'spec': spec, 'error': 'use T@X,Y,W,H=#RRGGBB, e.g. 2.0@100,80,40,40=#3080C0'}
    t, x, y, w, h = float(match.group(1)), *(int(match.group(i)) for i in range(2, 6))
    want = [int(match.group(6)[i:i + 2], 16) for i in (0, 2, 4)]
    result = subprocess.run([ffmpeg, '-v', 'error', '-nostdin', '-ss', str(t), '-i', path, '-frames:v', '1',
                             '-vf', f'crop={w}:{h}:{x}:{y},format=rgb24', '-f', 'rawvideo', '-'],
                            capture_output=True, check=False)
    data = result.stdout
    if result.returncode or len(data) < 3:
        return {'spec': spec, 'error': 'could not decode the region'}
    pixels = len(data) // 3
    got = [round(sum(data[c::3]) / pixels, 1) for c in range(3)]
    delta = max(abs(g - e) for g, e in zip(got, want))
    return {'spec': spec, 'expected_rgb': want, 'measured_rgb': got, 'max_channel_delta': round(delta, 1),
            'pass': delta <= tolerance}


def parse_spec(spec):
    match = re.fullmatch(r'\s*(\d+)\s*[xX]\s*(\d+)\s*(?:@\s*([\d./]+))?\s*', spec or '')
    if not match:
        raise ValueError('spec must look like 1920x1080 or 1920x1080@60')
    return int(match.group(1)), int(match.group(2)), match.group(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file')
    parser.add_argument('--spec', help='WIDTHxHEIGHT[@FPS], e.g. 1920x1080@60')
    parser.add_argument('--width', type=int)
    parser.add_argument('--height', type=int)
    parser.add_argument('--fps', help='expected frame rate, e.g. 60 or 30000/1001')
    parser.add_argument('--duration', type=float, help='expected duration in seconds')
    parser.add_argument('--duration-tolerance', type=float, help='seconds; default one frame, or 0.05 without --fps')
    parser.add_argument('--frames', type=int, help='expected decoded video frame count')
    parser.add_argument('--vcodec', help='expected video codec name, e.g. h264, hevc, prores')
    parser.add_argument('--pix-fmt', help='expected pixel format, e.g. yuv420p')
    parser.add_argument('--color', help='expected colour primaries, transfer and matrix tag, e.g. bt709')
    parser.add_argument('--audio', choices=('required', 'none', 'any'), default='any')
    parser.add_argument('--acodec', help='expected audio codec name, e.g. aac')
    parser.add_argument('--sample-rate', type=int)
    parser.add_argument('--channels', type=int)
    parser.add_argument('--max-true-peak', type=float, help='ceiling in dBTP for the file as delivered')
    parser.add_argument('--loudness', type=float, help='target integrated loudness in LUFS, only if the brief sets one')
    parser.add_argument('--loudness-tolerance', type=float, default=1.0)
    parser.add_argument('--av-length-tolerance', type=float, default=0.05,
                        help='allowed difference between decoded audio and video length, seconds')
    parser.add_argument('--lossy-check', action='store_true', help='also measure true peak after an AAC re-encode')
    parser.add_argument('--lossy-bitrate', default='128k')
    parser.add_argument('--max-lossy-true-peak', type=float, default=0.0,
                        help='ceiling in dBTP after the re-encode; default 0.0 (no overs)')
    parser.add_argument('--faststart', action='store_true', help='require moov before mdat (web playback)')
    parser.add_argument('--detect', action='store_true', help='list black, frozen and silent candidates')
    parser.add_argument('--color-patch', action='append', default=[],
                        help='T@X,Y,W,H=#RRGGBB: a flat region at time T that must decode to this colour '
                             '(repeatable); decoded with the file\'s own colour tags')
    parser.add_argument('--color-tolerance', type=float, default=6.0, help='max per-channel difference, 0-255')
    parser.add_argument('--skip-decode', action='store_true', help='skip the full decode (faster, weaker)')
    parser.add_argument('--json', help='write the full report here')
    parser.add_argument('--ffmpeg')
    parser.add_argument('--ffprobe')
    args = parser.parse_args()

    if args.spec:
        try:
            width, height, fps = parse_spec(args.spec)
        except ValueError as exc:
            parser.error(str(exc))
        args.width = args.width or width
        args.height = args.height or height
        args.fps = args.fps or fps
    if args.fps is not None and as_fraction(args.fps) is None:
        parser.error('--fps must be a positive number or fraction')
    if not os.path.isfile(args.file):
        print(f'not a file: {args.file}', file=sys.stderr)
        return 2
    ffprobe, ffmpeg = find_tool('ffprobe', args.ffprobe), find_tool('ffmpeg', args.ffmpeg)
    if not ffprobe or not ffmpeg:
        print('ffmpeg and ffprobe are required: install FFmpeg or pass --ffmpeg/--ffprobe', file=sys.stderr)
        return 2

    probe = run([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', args.file], timeout=120)
    if probe.returncode:
        print(f'ffprobe failed: {probe.stderr.strip()}', file=sys.stderr)
        return 2
    info = json.loads(probe.stdout or '{}')
    streams = info.get('streams', [])
    videos = [s for s in streams if s.get('codec_type') == 'video'
              and not (s.get('disposition') or {}).get('attached_pic')]
    audios = [s for s in streams if s.get('codec_type') == 'audio']
    if not videos:
        print('no video stream found', file=sys.stderr)
        return 2
    v = videos[0]
    fmt = info.get('format', {})
    avg = as_fraction(v.get('avg_frame_rate'))
    real = as_fraction(v.get('r_frame_rate'))
    fps = avg or real
    duration = as_float(v.get('duration')) or as_float(fmt.get('duration'))
    container = fmt.get('format_name', '')

    report = {
        'file': args.file,
        'container': {'format': container, 'duration_s': as_float(fmt.get('duration')),
                      'size_bytes': int(fmt['size']) if str(fmt.get('size', '')).isdigit() else None,
                      'bit_rate': as_float(fmt.get('bit_rate'))},
        'video': {'codec': v.get('codec_name'), 'profile': v.get('profile'), 'width': v.get('width'),
                  'height': v.get('height'), 'pix_fmt': v.get('pix_fmt'),
                  'sample_aspect_ratio': v.get('sample_aspect_ratio'),
                  'fps': str(fps) if fps else None, 'fps_float': round(float(fps), 6) if fps else None,
                  'variable_frame_rate_suspected': bool(avg and real and abs(float(avg - real)) > 0.001 * float(real)),
                  'frames_in_metadata': int(v['nb_frames']) if str(v.get('nb_frames', '')).isdigit() else None,
                  'duration_s': duration, 'rotation_deg': rotation_of(v),
                  'color_primaries': v.get('color_primaries'), 'color_transfer': v.get('color_transfer'),
                  'color_space': v.get('color_space'), 'color_range': v.get('color_range')},
        'audio': [{'codec': a.get('codec_name'), 'sample_rate': int(a['sample_rate']) if str(a.get('sample_rate', '')).isdigit() else None,
                   'channels': a.get('channels'), 'channel_layout': a.get('channel_layout'),
                   'duration_s': as_float(a.get('duration'))} for a in audios],
        'extra_video_streams': len(videos) - 1,
        'faststart': mp4_faststart(args.file) if any(k in container for k in ('mp4', 'mov')) else None,
    }
    if not args.skip_decode:
        report['decode'] = decode_all(ffmpeg, args.file)
    if audios:
        report['loudness'] = loudness(ffmpeg, args.file)
        report['audio_edges'] = audio_edges(ffmpeg, args.file, audios[0].get('channels'))
        if (audios[0].get('channels') or 0) >= 2:
            # Fold to mono and play it on both channels: a large loss against the stereo mix
            # suggests out-of-phase content that disappears on mono speakers.
            folded = loudness(ffmpeg, args.file, pre_filter='pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1')
            stereo_i, mono_i = report['loudness'].get('integrated_lufs'), folded.get('integrated_lufs')
            if stereo_i is not None and mono_i is None:
                drop = 99.0  # the fold-down measures as silence: fully out of phase
            else:
                drop = round(stereo_i - mono_i, 1) if None not in (stereo_i, mono_i) else None
            report['mono_fold_down'] = {'integrated_lufs': mono_i, 'drop_lu': drop}
        if args.lossy_check:
            report['lossy_reencode'] = lossy_true_peak(ffmpeg, args.file, args.lossy_bitrate)
    if args.detect:
        report['detect'] = detect(ffmpeg, args.file, bool(audios), duration)
    if args.color_patch:
        report['color_patches'] = [color_patch(ffmpeg, args.file, spec, args.color_tolerance)
                                   for spec in args.color_patch]

    checks = {}

    def check(name, passed, expected, actual):
        checks[name] = {'pass': bool(passed), 'expected': expected, 'actual': actual}

    if args.width is not None:
        check('width', v.get('width') == args.width, args.width, v.get('width'))
    if args.height is not None:
        check('height', v.get('height') == args.height, args.height, v.get('height'))
    if args.fps is not None:
        want = as_fraction(args.fps)
        check('fps', fps is not None and abs(float(fps - want)) < 0.001, str(want), str(fps) if fps else None)
    if args.duration is not None:
        tol = args.duration_tolerance
        if tol is None:
            want_fps = as_fraction(args.fps) or fps
            tol = float(1 / want_fps) if want_fps else 0.05
        measured = (report.get('decode') or {}).get('decoded_length_s') or duration
        check('duration', measured is not None and abs(measured - args.duration) <= tol + 1e-9,
              f'{args.duration} +/- {round(tol, 4)} s', measured)
    if args.frames is not None:
        if report.get('decode'):
            check('frames', report['decode']['decoded_video_frames'] == args.frames, args.frames,
                  report['decode']['decoded_video_frames'])
        else:  # --skip-decode: fall back to the container's count, which can be missing or wrong
            meta = report['video']['frames_in_metadata']
            check('frames_in_metadata', meta == args.frames, args.frames, meta)
    if args.vcodec:
        check('vcodec', v.get('codec_name') == args.vcodec, args.vcodec, v.get('codec_name'))
    if args.pix_fmt:
        check('pix_fmt', v.get('pix_fmt') == args.pix_fmt, args.pix_fmt, v.get('pix_fmt'))
    if args.color:
        tags = [v.get('color_primaries'), v.get('color_transfer'), v.get('color_space')]
        check('color_tags', all(t == args.color for t in tags), [args.color] * 3, tags)
    if args.audio == 'required':
        check('audio_present', bool(audios), True, bool(audios))
    elif args.audio == 'none':
        check('audio_absent', not audios, True, not audios)
    if audios:
        a = report['audio'][0]
        if args.acodec:
            check('acodec', a['codec'] == args.acodec, args.acodec, a['codec'])
        if args.sample_rate:
            check('sample_rate', a['sample_rate'] == args.sample_rate, args.sample_rate, a['sample_rate'])
        if args.channels:
            check('channels', a['channels'] == args.channels, args.channels, a['channels'])
        level = report.get('loudness', {})
        if args.max_true_peak is not None:
            tp = level.get('true_peak_dbtp')
            check('true_peak', tp is not None and tp <= args.max_true_peak, f'<= {args.max_true_peak} dBTP', tp)
        if args.loudness is not None:
            lufs = level.get('integrated_lufs')
            check('loudness', lufs is not None and abs(lufs - args.loudness) <= args.loudness_tolerance,
                  f'{args.loudness} +/- {args.loudness_tolerance} LUFS', lufs)
        if args.lossy_check:
            tp = report.get('lossy_reencode', {}).get('true_peak_dbtp')
            check('true_peak_after_lossy_reencode', tp is not None and tp <= args.max_lossy_true_peak,
                  f'<= {args.max_lossy_true_peak} dBTP after AAC {args.lossy_bitrate}', tp)
        video_len = (report.get('decode') or {}).get('decoded_length_s') or duration
        audio_len = level.get('decoded_audio_length_s')
        if video_len and audio_len and fps and report.get('decode'):
            video_only = report['decode']['decoded_video_frames']
            video_len = video_only / float(fps) if video_only else video_len
            diff = round(audio_len - video_len, 4)
            report['audio_minus_video_s'] = diff
            check('av_length', abs(diff) <= args.av_length_tolerance,
                  f'|audio - video| <= {args.av_length_tolerance} s', diff)
    for i, patch in enumerate(report.get('color_patches', []), start=1):
        if 'error' in patch:
            check(f'color_patch_{i}', False, patch['spec'], patch['error'])
        else:
            check(f'color_patch_{i}', patch['pass'],
                  f"#{''.join(f'{c:02X}' for c in patch['expected_rgb'])} +/- {args.color_tolerance}",
                  f"{patch['measured_rgb']} (max delta {patch['max_channel_delta']})")
    if args.faststart:
        check('faststart', report['faststart'] is True, True, report['faststart'])
    if report.get('decode') is not None:
        check('full_decode', report['decode']['ok'], 'no decode errors',
              f"{report['decode']['error_count']} error line(s)")

    warnings = []
    if report['video']['variable_frame_rate_suspected']:
        warnings.append('average and nominal frame rates differ: possibly variable frame rate')
    if report['video']['sample_aspect_ratio'] not in (None, '1:1', '0:1', 'N/A'):
        warnings.append(f"non-square pixels: sample aspect ratio {report['video']['sample_aspect_ratio']}")
    if report['video']['rotation_deg']:
        warnings.append(f"rotation metadata {report['video']['rotation_deg']} degrees: players may rotate it")
    if not report['video']['color_primaries'] or report['video']['color_primaries'] == 'unknown':
        warnings.append('colour primaries untagged: players will guess; tag them (e.g. bt709)')
    if report['video']['pix_fmt'] and report['video']['codec'] == 'h264' and report['video']['pix_fmt'] != 'yuv420p':
        warnings.append(f"H.264 in {report['video']['pix_fmt']}: many browsers and phones only play yuv420p")
    if report['extra_video_streams']:
        warnings.append(f"{report['extra_video_streams']} extra video stream(s)")
    if len(audios) > 1:
        warnings.append(f'{len(audios)} audio streams: confirm which one players will use')
    warnings += (report.get('audio_edges') or {}).get('notes', [])
    drop = (report.get('mono_fold_down') or {}).get('drop_lu')
    if drop is not None and drop > 3:
        warnings.append(f'mono fold-down is {drop} LU quieter than stereo: check for out-of-phase content')
    report['warnings'] = warnings
    report['checks'] = checks
    failed = [name for name, c in checks.items() if not c['pass']]
    report['checks_passed'] = (not failed) if checks else None
    report['not_checked'] = ('picture content, motion at playback speed, text legibility at viewing size, '
                             'flashing (flash_scan.py), how the sound sounds, sync to picture events, claims, rights')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as fh:
            json.dump(report, fh, indent=2)

    vid = report['video']
    print(f"{os.path.basename(args.file)}: {vid['codec']} {vid['width']}x{vid['height']} {vid['pix_fmt']} "
          f"@ {vid['fps']} fps, {duration if duration is None else round(duration, 3)} s; "
          f"colour {vid['color_primaries']}/{vid['color_transfer']}/{vid['color_space']}; "
          f"faststart {report['faststart']}")
    for a in report['audio']:
        print(f"  audio: {a['codec']} {a['sample_rate']} Hz, {a['channels']} ch")
    if 'decode' in report:
        d = report['decode']
        print(f"  decode: {'clean' if d['ok'] else 'ERRORS'}; {d['decoded_video_frames']} video frames; "
              f"{d['decoded_length_s']} s")
    if 'loudness' in report:
        lv = report['loudness']
        print(f"  loudness: {lv.get('integrated_lufs')} LUFS integrated, LRA {lv.get('loudness_range_lu')} LU, "
              f"true peak {lv.get('true_peak_dbtp')} dBTP")
    if 'audio_edges' in report:
        e = report['audio_edges']
        print(f"  edges: first 5 ms peak {e['head_first_5ms_peak_dbfs']} dBFS, last 10 ms peak "
              f"{e['tail_last_10ms_peak_dbfs']} dBFS, last 50 ms RMS {e['tail_50ms_rms_dbfs']} dBFS")
    if 'mono_fold_down' in report:
        print(f"  mono fold-down: {report['mono_fold_down']['integrated_lufs']} LUFS "
              f"({report['mono_fold_down']['drop_lu']} LU below stereo)")
    if 'lossy_reencode' in report:
        print(f"  after AAC {args.lossy_bitrate}: true peak {report['lossy_reencode'].get('true_peak_dbtp')} dBTP")
    if 'audio_minus_video_s' in report:
        print(f"  audio minus video length: {report['audio_minus_video_s']} s")
    if 'detect' in report and 'error' not in report['detect']:
        det = report['detect']
        print(f"  candidates: black {det['black']}, frozen {det['frozen']}, silent {det['silent']}")
    for w in warnings:
        print(f'  warning: {w}')
    for name, c in checks.items():
        print(f"  {'PASS' if c['pass'] else 'FAIL'} {name}: expected {c['expected']}, got {c['actual']}")
    print('  not checked: ' + report['not_checked'])
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
