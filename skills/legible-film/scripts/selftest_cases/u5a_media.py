"""Media-level synthetic cases for listening and checks."""

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def run_u5a_media_cases(tool, record, j, scripts_dir, skip=None):
    """Exercise actual decoding, packets and audio comparisons under the suite lock."""
    folder = Path(j('u5a-media'))
    folder.mkdir(parents=True, exist_ok=True)

    def ffmpeg(*args):
        command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *map(str, args)]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError('synthetic media generation failed: ' + result.stderr[-300:])

    def report(path):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    picture = folder / 'motion.mp4'
    ffmpeg('-f', 'lavfi', '-i', "color=c=black:s=96x64:r=30:d=3,drawbox=x=0:y=0:w=iw:h=ih:"
           "color=white:t=fill:enable='gte(t,1)'", '-c:v', 'libx264', '-threads', '1', '-pix_fmt', 'yuv420p', picture)
    code, output = tool('listen.py', 'sync', picture, '--candidates', '--json')
    try:
        candidates = json.loads(output)
    except ValueError:
        candidates = {}
    record('listen sync: silent picture yields a motion candidate without cues',
           code == 0 and candidates.get('source') == 'picture only; no audio stream'
           and any(abs(row.get('t', -10) - 1) < .08 for row in candidates.get('candidates', []))
           and candidates.get('sound_follows_list', {}).get('state') == 'not assessed', output[-300:])

    cue_spec = importlib.util.spec_from_file_location('u5a_media_cue_list', Path(scripts_dir) / 'cue_list.py')
    cue_list = importlib.util.module_from_spec(cue_spec)
    cue_spec.loader.exec_module(cue_list)
    identity = cue_list.picture_identity(picture)
    schedule = folder / 'motion-timing.json'
    cue_list.write_schedule(identity['schedule'], schedule)
    cue_path = folder / 'cues.json'
    cue_path.write_text(json.dumps({'version': 'v2', 'fps': '30/1', 'picture':
        {'kind': 'picture', 'path': picture.name, 'sha256': identity['sha256'], 'geometry': identity['geometry'],
         'timing': cue_list.timing_block(identity['schedule'], schedule.name)},
        'events': [{'id': 'turn', 't': 1, 'scale': 'turn', 'sound': 'required',
                    'lead_ms': -100, 'decision': 'sound leads the picture'}]}), encoding='utf-8')
    stem = folder / 'offset-stem.wav'
    signal = np.zeros(3 * 48000)
    start = round(.65 * 48000)
    signal[start:start + 2400] = np.random.default_rng(42).normal(0, .4, 2400) * np.exp(-np.arange(2400) / 220)
    with wave.open(str(stem), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(np.clip(signal * 32767, -32768, 32767).astype('<i2').tobytes())
    code, output = tool('listen.py', 'sync', stem, '--video', picture, '--offset', '.25', '--cues', cue_path,
                        '--source-kind', 'stem', '--null', '50', '--seed', '3', '--json')
    try:
        synced = json.loads(output)
    except ValueError:
        synced = {}
    frame_rows = synced.get('frame_change_at_cue', {}).get('rows', [])
    lead_rows = synced.get('turn_leads', [])
    record('listen sync: a stem offset maps the picture cut and declared turn lead',
           code == 0 and synced.get('cue_freshness') == 'fresh' and synced.get('source') == 'stem'
           and len(frame_rows) == 1 and frame_rows[0].get('state') == 'change'
           and len(lead_rows) == 1 and abs(lead_rows[0].get('measured_ms', 999) + 100) <= 15, output[-350:])

    registered = folder / 'registered-project'
    code, output = tool('project.py', 'init', registered, '--path', 'sound', '--timeline', 'picture',
                        '--what', 'A synthetic motion test')
    if code == 0:
        code, output = tool('project.py', 'add-version', registered, '--cues', cue_path, '--file', picture)
    if code in (0, 1):
        code, output = tool('check.py', registered, '--no-speech')
    checked = report(registered / 'cuts' / 'v001' / 'checks.json')
    version = report(registered / 'cuts' / 'v001' / 'manifest.json')
    items = {row['id']: row for row in checked.get('items', [])}
    record('sync: a real registered picture checks its copied list, geometry and project frame',
           code in (0, 1) and items.get('sync_cues', {}).get('state') == 'pass'
           and items.get('sync_picture_geometry', {}).get('state') == 'pass'
           and items.get('context_what', {}).get('state') == 'unconfirmed'
           and version.get('identity', {}).get('cues_sha256') != version.get('files', {}).get('cues.json'),
           output[-500:] + str({key: items.get(key) for key in ('sync_cues', 'sync_picture_geometry', 'context_what')}))

    source = folder / 'conform-source.wav'
    tone = .08 * np.sin(2 * np.pi * 220 * np.arange(4 * 48000) / 48000)
    with wave.open(str(source), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes((tone * 32767).astype('<i2').tobytes())
    fixture = Path(scripts_dir) / 'testpages' / 'identity' / 'cues.json'
    fixture_sha = hashlib.sha256(fixture.read_bytes()).hexdigest()
    mapping, bed, conform = folder / 'conform-map.json', folder / 'conformed.wav', folder / 'conform-report.json'
    mapping.write_text(json.dumps({'cues_sha256': fixture_sha, 'sections': [
        {'id': 'open', 'take_start': 0}, {'id': 'mark', 'take_start': 1},
        {'id': 'hold', 'take_start': 2.5}]}), encoding='utf-8')
    code, output = tool('conform.py', source, '--map', mapping, '--cues', fixture,
                        '--out', bed, '--report', conform)
    if code == 0:
        palette = folder / 'conform-palette.json'
        palette.write_text(json.dumps({'version': 2, 'music': {'file': source.name},
            'voice': {'file': stem.name}, 'roles': {'impact': {'takes': [stem.name],
                                                               'sync': 'attack', 'points_s': [.65]}}}),
                           encoding='utf-8')
        code, output = tool('mix_cues.py', fixture, palette, '--out-dir', folder / 'conform-mix',
                            '--duration', 3, '--master', 'none', '--music', bed, '--conform', conform)
    mixer = report(folder / 'conform-mix' / 'mix-report.json')
    spec = importlib.util.spec_from_file_location('u5a_media_check', Path(scripts_dir) / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    conform_state, conform_detail, refs = check.conform_evidence({'cues_sha256': fixture_sha,
                                                                   'conform_sha256': None}, mixer)
    record('sync: a real short conform and mixer report binds the source and conformed bed',
           code == 0 and conform_state == 'pass'
           and {'conform_report', 'conform_source', 'conform_bed'} <= {role for role, _ in refs},
           output[-500:] + '; ' + conform_detail)

    rate, duration = 48000, 8
    t = np.arange(rate * duration) / rate
    envelope = .12 * (1 + .25 * np.sin(2 * np.pi * .7 * t))
    sample = envelope * (np.sin(2 * np.pi * (220 * t + 11 * t ** 2))
                         + .35 * np.sin(2 * np.pi * (440 * t + 3 * t ** 2))
                         + .15 * np.sin(2 * np.pi * (997 * t + 5 * t ** 2)))
    ref = folder / 'reference.wav'
    with wave.open(str(ref), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(np.clip(sample * 32767, -32768, 32767).astype('<i2').tobytes())
    remux, aac = folder / 'remux.mka', folder / 'encoded.m4a'
    ffmpeg('-i', ref, '-c:a', 'copy', remux)
    ffmpeg('-i', ref, '-c:a', 'aac', '-b:a', '128k', aac)
    results = []
    for name, delivered in (('remux', remux), ('AAC 128k', aac)):
        path = folder / (name.replace(' ', '-') + '.json')
        code, output = tool('sync_check.py', delivered, ref, '--outside', '0,0', '--window', '.5', '--json', path)
        data = report(path)
        verdict = data.get('outside', {}).get('verdict')
        outside = data.get('outside', {})
        results.append((name, code, verdict, outside.get('not_assessed_windows'),
                        outside.get('estimated_residual_floor_dbfs'), outside.get('changed', [])[:3]))
    record('outside: identical remux and AAC 128k comparison',
           all(code == 0 and verdict == 'unchanged within tolerance' for _, code, verdict, _, _, _ in results),
           str(results))
    changed_ref, changed_aac = folder / 'changed-reference.wav', folder / 'changed-encoded.m4a'
    changed_sample = sample.copy()
    changed_sample[3 * rate:round(3.2 * rate)] += np.random.default_rng(71).normal(0, .06, round(.2 * rate))
    with wave.open(str(changed_ref), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(np.clip(changed_sample * 32767, -32768, 32767).astype('<i2').tobytes())
    ffmpeg('-i', changed_ref, '-c:a', 'aac', '-b:a', '128k', changed_aac)
    changed_report = folder / 'changed-aac.json'
    code, output = tool('sync_check.py', changed_aac, ref, '--outside', '0,0', '--window', '0.5',
                        '--json', changed_report)
    changed_rows = report(changed_report).get('outside', {}).get('changed', [])
    record('outside: AAC re-encode does not hide a changed 200 ms passage',
           code == 1 and any(3 <= row['start_s'] < 3.2 for row in changed_rows), output[-300:])

    original, trimmed, sped = folder / 'original.mp4', folder / 'trim.mp4', folder / 'speed.mp4'
    late_trim = folder / 'trim-late.mp4'
    ffmpeg('-i', picture, '-i', ref, '-map', '0:v:0', '-map', '1:a:0', '-t', '3', '-c:v', 'copy',
           '-c:a', 'aac', original)
    ffmpeg('-i', original, '-ss', '0.5', '-t', '2', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', trimmed)
    ffmpeg('-i', original, '-ss', '0.5', '-t', '2', '-af', 'adelay=150:all=1', '-c:v', 'libx264',
           '-threads', '1', '-c:a', 'aac', late_trim)
    ffmpeg('-i', original, '-filter_complex', '[0:v]setpts=0.5*PTS[v];[0:a]atempo=2[a]',
           '-map', '[v]', '-map', '[a]', '-t', '1.5', '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', sped)
    edit_results = []
    for name, changed, edit in (('trim', trimmed, 'trim:.5,2.5'), ('speed', sped, 'speed:0.5')):
        path = folder / (name + '-checks.json')
        code, output = tool('check.py', '--file', changed, '--against', original, '--edit', edit,
                            '--no-speech', '--json', path)
        rows = {row['id']: row for row in report(path).get('items', [])}
        wanted = ('edit_duration', 'edit_streams', 'edit_audio_offset', 'edit_trim_content_offset') if name == 'trim' else (
            'edit_duration', 'edit_streams')
        edit_results.append((name, code, {key: rows.get(key, {}) for key in wanted}, output[-200:]))
    record('quick edits: actual trim and speed satisfy their duration and stream invariants',
           all(code in (0, 1) and all(row.get('state') == 'pass' for row in states.values())
               for _, code, states, _ in edit_results), str(edit_results))
    late_report = folder / 'trim-late-checks.json'
    code, output = tool('check.py', '--file', late_trim, '--against', original, '--edit', 'trim:.5,2.5',
                        '--no-speech', '--json', late_report)
    late_rows = {row['id']: row for row in report(late_report).get('items', [])}
    record('quick edits: actual trim catches audio shifted inside unchanged stream timestamps',
           code == 1 and late_rows.get('edit_trim_content_offset', {}).get('state') == 'fail',
           str(late_rows.get('edit_trim_content_offset')) + output[-200:])
    wrong_speed_report = folder / 'wrong-speed-checks.json'
    code, output = tool('check.py', '--file', original, '--against', original, '--edit', 'speed:0.5',
                        '--no-speech', '--json', wrong_speed_report)
    wrong_speed_rows = {row['id']: row for row in report(wrong_speed_report).get('items', [])}
    record('quick edits: a declared speed change rejects unchanged duration',
           code == 1 and wrong_speed_rows.get('edit_duration', {}).get('state') == 'fail',
           str(wrong_speed_rows.get('edit_duration')) + output[-200:])
    gif = folder / 'animation.gif'
    ffmpeg('-i', original, '-an', '-vf', 'fps=10', '-loop', '0', gif)
    gif_report = folder / 'gif-checks.json'
    code, output = tool('check.py', '--file', gif, '--against', original, '--edit', 'convert', '--no-speech',
                        '--json', gif_report)
    gif_rows = {row['id']: row for row in report(gif_report).get('items', [])}
    record('quick edits: an actual GIF is checked against its own destination',
           code in (0, 1) and all(gif_rows.get(key, {}).get('state') == 'pass'
                                  for key in ('spec', 'edit_duration', 'edit_streams')),
           f'code={code}; states={[(key, gif_rows.get(key)) for key in ("spec", "edit_duration", "edit_streams")]}; '
           + output[-200:])

    version = folder / 'registered' / 'cuts' / 'v001'
    version.mkdir(parents=True)
    master = version / 'preview.mp4'
    ffmpeg('-stream_loop', '-1', '-i', picture, '-i', ref, '-map', '0:v:0', '-map', '1:a:0', '-t', '8',
           '-c:v', 'copy', '-c:a', 'aac', master)
    identity = cue_list.picture_identity(master)
    cue_list.write_schedule(identity['schedule'], version / 'picture-timing.json')
    manifest = {'identity': {'picture_sha256': identity['sha256'],
                             'picture_timing': cue_list.timing_block(identity['schedule'])}}
    same_mux, shifted_mux = folder / 'same-mux.mp4', folder / 'shifted-video.mp4'
    shifted_both, remux = folder / 'shifted-both.mp4', folder / 'remux.mkv'
    shutil.copyfile(master, same_mux)
    ffmpeg('-itsoffset', '0.2', '-i', master, '-i', master, '-map', '0:v:0', '-map', '1:a:0', '-c', 'copy',
           shifted_mux)
    ffmpeg('-copyts', '-itsoffset', '0.2', '-i', master, '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy',
           shifted_both)
    ffmpeg('-i', master, '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', remux)
    check_spec = importlib.util.spec_from_file_location('u5a_media_check', Path(scripts_dir) / 'check.py')
    check = importlib.util.module_from_spec(check_spec)
    check_spec.loader.exec_module(check)
    mux_states = []
    for delivered in (same_mux, shifted_mux, shifted_both, remux):
        rows, _ = check.project_sync_items(version, delivered, manifest)
        mux_states.append(next((row for row in rows if row['id'] == 'sync_mux_origin'), None))
    record('sync: a video-only mux shift fails while whole-clock shifts and remuxes pass',
           [row.get('state') if row else None for row in mux_states] == ['pass', 'fail', 'pass', 'pass'],
           str(mux_states))

    brief = folder / 'brief.md'
    brief.write_text('SECRET-BRIEF-NOT-FOR-READER', encoding='utf-8')
    videos = []
    for name, title in (('contextless', ''), ('stated', 'WHAT: A TEST TOOL\nFOR: EDITORS\nWHY: SAVE TIME')):
        image = Image.new('RGB', (640, 360), color='black')
        ImageDraw.Draw(image).multiline_text((24, 24), title, fill='white', spacing=8)
        image_path = folder / (name + '.png')
        image.save(image_path)
        movie = folder / (name + '.mp4')
        ffmpeg('-loop', '1', '-framerate', '10', '-i', image_path, '-t', '3.2', '-c:v', 'libx264',
               '-threads', '1', '-pix_fmt', 'yuv420p', movie)
        videos.append(movie)
    cold_rows = []
    for movie, state in zip(videos, ('mismatched', 'matched')):
        digest = hashlib.sha256(movie.read_bytes()).hexdigest()
        assessment = folder / (movie.stem + '-assessment.json')
        assessment.write_text(json.dumps({'state': state, 'by': 'synthetic reader', 'file_sha256': digest,
                              'answer': {'what': 'a test tool', 'audience': 'editors', 'why': 'save time'}}),
                              encoding='utf-8')
        code, output = tool('grade.py', 'cold', '--file', movie, '--seconds', '3', '--record', '--assessment', assessment)
        base = movie.parent / (movie.stem + '.grade') / 'cold'
        checks = report(base / 'checks.json').get('cold_read', {})
        packets = list(base.glob('packet-*')) if base.is_dir() else []
        packet = packets[0] if len(packets) == 1 else base
        metadata = report(packet / 'packet.json')
        try:
            text = (packet / 'prompt.txt').read_text(encoding='utf-8') + (packet / 'words.txt').read_text(encoding='utf-8')
        except OSError:
            text = ''
        cold_rows.append((code == 0 and checks.get('state') == state and checks.get('file_sha256') == digest
                          and checks.get('by') == 'synthetic reader' and metadata.get('sample_interval_s') == .5
                          and (packet / 'frames.png').is_file() and 'SECRET-BRIEF' not in text
                          and 'confirmed' not in json.dumps(checks), output[-180:]))
    record('cold read: synthetic contextless and stated fixtures record hash-bound judgments',
           all(ok for ok, _ in cold_rows), str(cold_rows))
    run_review_sync_cases(tool, record, j, scripts_dir, skip)
    run_review_cold_cases(tool, record, j, scripts_dir)
    run_precision_cases(tool, record, j, scripts_dir)


def run_review_sync_cases(tool, record, j, scripts_dir, skip=None):
    """Test fractional windows and AAC padding with and without a real edit."""
    root = Path(j('u5-review-sync'))
    root.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('u5_review_sync', Path(scripts_dir) / 'sync_check.py')
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    rng = np.random.default_rng(41)
    length = 8 * sync.RATE + 1776
    signal = rng.normal(0, .08, (length, 2))
    fractional = sync.compare_outside(signal, signal.copy(), (1.1, 1.3), 0)
    small = sync.compare_outside(signal, signal.copy(), (.037, .1), 0)
    record('outside: a fractional remainder joins the final full window',
           fractional['verdict'] == 'unchanged within tolerance' and not fractional['not_assessed_windows']
           and abs(fractional['windows'][-1]['end_s'] - length / sync.RATE) < 1e-9,
           f"verdict={fractional['verdict']}; not_assessed={fractional['not_assessed_windows']}; "
           f"tail={fractional['windows'][-1]}")
    record('outside: an isolated sub-window passage stays not assessed',
           any(row.get('reason') == 'shorter than one analysis window' and row['start_s'] == 0
               for row in small['windows']), str(small['windows'][:2]))
    short_non_aac = sync.compare_outside(signal, signal[:-500], (1.1, 1.3), 0)
    record('outside: an unproven short non-AAC truncation stays not assessed',
           any(row.get('reason') == 'no aligned delivered audio' for row in short_non_aac['windows']),
           str(short_non_aac['windows'][:2]))

    for rate in (48000, 44100):
        n = round((8.037 if rate == 48000 else 8.03524) * rate)
        t = np.arange(n) / rate
        sample = .12 * (1 + .25 * np.sin(2 * np.pi * .7 * t)) * (
            np.sin(2 * np.pi * (220 * t + 11 * t ** 2))
            + .35 * np.sin(2 * np.pi * (440 * t + 3 * t ** 2))
            + .15 * np.sin(2 * np.pi * (997 * t + 5 * t ** 2)))
        sample += np.random.default_rng(44).normal(0, .08, n)
        sample[5 * rate:round(5.1 * rate)] = 0
        changed_sample = sample.copy()
        changed_sample[3 * rate:round(3.2 * rate)] += np.random.default_rng(71).normal(0, .08, round(.2 * rate))
        reference, edited = root / f'reference-{rate}.wav', root / f'edited-{rate}.wav'
        for path, values in ((reference, sample), (edited, changed_sample)):
            with wave.open(str(path), 'wb') as stream:
                stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                stream.writeframes(np.clip(values * 32767, -32768, 32767).astype('<i2').tobytes())
        pair = []
        for name, source in (('unchanged', reference), ('changed', edited)):
            encoded, output = root / f'{name}-{rate}.m4a', root / f'{name}-{rate}.json'
            encoded_run = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(source),
                                          '-c:a', 'aac', '-b:a', '128k', str(encoded)], capture_output=True)
            if encoded_run.returncode:
                pair.append({'name': name, 'error': encoded_run.stderr.decode(errors='replace')[-300:]})
                continue
            code, text = tool('sync_check.py', encoded, reference, '--outside', '1.1,1.3',
                              '--window', '.5', '--json', output)
            try:
                data = json.loads(output.read_text(encoding='utf-8')).get('outside', {})
            except (OSError, ValueError):
                data = {}
            delta = len(sync.decode_stereo('ffmpeg', encoded)) - len(sync.decode_stereo('ffmpeg', reference))
            changed = data.get('changed') or []
            pair.append({'name': name, 'code': code, 'verdict': data.get('verdict'),
                         'not_assessed': data.get('not_assessed_windows'), 'proof': bool(data.get('codec_proof')),
                         'proof_bitrate': (data.get('codec_proof') or {}).get('bitrate_bps'),
                         'changed_at_3s': any(row.get('start_s', -1) < 3.2 and row.get('end_s', -1) > 3
                                              for row in changed),
                         'decoded_tail_samples': delta, 'frame_samples': int(np.ceil(1024 * sync.RATE / rate)),
                         'detail': text[-180:]})
        ok = (len(pair) == 2 and pair[0].get('code') == 0
              and pair[0].get('verdict') == 'unchanged within tolerance' and pair[0].get('proof')
              and pair[0].get('proof_bitrate') == 128000 and pair[0].get('not_assessed') == 0
              and len(sync.decode_stereo('ffmpeg', reference)) % round(.05 * sync.RATE) != 0
              and pair[1].get('code') == 1 and pair[1].get('changed_at_3s') and not pair[1].get('proof'))
        record(f'outside: {rate} Hz fractional AAC matches and a real outside edit fails', ok, str(pair))
        padded, padded_json = root / f'padded-{rate}.mka', root / f'padded-{rate}.json'
        made = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(reference),
                               '-c:a', 'aac', '-b:a', '128k', str(padded)], capture_output=True)
        padded_code, padded_output = tool('sync_check.py', padded, reference, '--outside', '1.1,1.3',
                                          '--window', '.5', '--json', padded_json) if not made.returncode else (2, '')
        try:
            padded_full = json.loads(padded_json.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            padded_full = {}
        padded_report = padded_full.get('outside', {})
        ref_len = len(sync.decode_stereo('ffmpeg', reference))
        # FFmpeg 6.1 leaves the encoder's priming before a Matroska stream's time zero. The tool skips it, as a player
        # does, so what the decode holds beyond the reference here is the padding alone.
        priming = sync.leading_priming(sync.find_tool('ffprobe'), padded) if not made.returncode else 0
        pad_len = len(sync.decode_stereo('ffmpeg', padded, priming)) if not made.returncode else ref_len
        delta, frame = pad_len - ref_len, int(np.ceil(1024 * sync.RATE / rate))
        tails = [row for row in padded_report.get('windows', [])
                 if row.get('end_s', 0) >= max(ref_len, pad_len) / sync.RATE - 1e-9]
        if not made.returncode and not priming and delta >= frame:
            # FFmpeg 5.1's Matroska muxer marks no priming: the file plays it at time zero, one AAC frame late, so a
            # padding-only file cannot be made here. The tool must say it is late.
            lag = ((padded_full.get('summary') or {}).get('median_lag_ms') or 0) * sync.RATE / 1000
            record(f'outside: {rate} Hz Matroska priming played at time zero reads as one AAC frame late',
                   padded_code == 1 and 'constant offset' in padded_output and abs(lag - 1024 * sync.RATE / rate) <= 1,
                   f'lag={lag}; delta={delta}; frame={frame}; {padded_output[:160]}')
            (skip or (lambda name, reason: record(name, False, reason)))(
                f'outside: {rate} Hz AAC padding is covered by its last window',
                "this FFmpeg's Matroska muxer leaves AAC priming at time zero, so no padding-only file can be made")
        else:
            record(f'outside: {rate} Hz AAC padding is covered by its last window',
                   padded_code == 0 and padded_report.get('verdict') == 'unchanged within tolerance'
                   and bool(padded_report.get('codec_proof')) and 0 < delta < frame
                   and (rate != 44100 or delta > 1024) and len(tails) == 1 and 'reference_dbfs' in tails[0],
                   f'priming={priming}; delta={delta}; frame={frame}; tail={tails}; {padded_output[-160:]}')
        if rate == 48000:
            tail_source, tail_aac, tail_json = root / 'tail-edit.wav', root / 'tail-edit.mka', root / 'tail-edit.json'
            extra = np.random.default_rng(7).normal(0, .5, 200)
            with wave.open(str(tail_source), 'wb') as stream:
                stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                stream.writeframes(np.clip(np.r_[sample, extra] * 32767, -32768, 32767).astype('<i2').tobytes())
            made = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-y', '-i', str(tail_source),
                                   '-c:a', 'aac', '-b:a', '128k', str(tail_aac)], capture_output=True)
            tail_code, tail_output = tool('sync_check.py', tail_aac, reference, '--outside', '1.1,1.3',
                                          '--window', '.5', '--json', tail_json) if not made.returncode else (2, '')
            try:
                tail_report = json.loads(tail_json.read_text(encoding='utf-8')).get('outside', {})
            except (OSError, ValueError):
                tail_report = {}
            tail_rows = [row for row in tail_report.get('changed', []) if row.get('end_s', 0) > ref_len / sync.RATE]
            record('outside: audible audio added inside AAC padding still fails',
                   tail_code == 1 and tail_rows and not tail_report.get('codec_proof'),
                   str(tail_rows) + '; ' + tail_output[-160:])


def run_review_cold_cases(tool, record, j, scripts_dir):
    """Exercise a project cold record against the same and a different final."""
    root = Path(j('u5-review-cold'))
    root.mkdir(parents=True, exist_ok=True)
    project = root / 'project'
    code, output = tool('project.py', 'init', project)
    version = project / 'cuts' / 'v001'
    version.mkdir(parents=True, exist_ok=True)
    preview = version / 'preview.mp4'
    made = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-f', 'lavfi',
                           '-i', 'testsrc2=size=96x64:rate=10:duration=2', '-vf',
                           'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv',
                           '-c:v', 'libx264', '-threads', '1',
                           '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_primaries', 'bt709',
                           '-color_trc', 'bt709', '-movflags', '+faststart', str(preview)], capture_output=True)
    if code or made.returncode:
        record('cold read: project assessment reaches a byte-identical final', False,
               output[-300:] + made.stderr.decode(errors='replace')[-300:])
        return
    (version / 'film.md').write_text('---\ntitle: Synthetic\n---\n', encoding='utf-8')
    manifest = {'version': 'v001', 'duration_s': 2, 'frames': 20, 'size': [96, 64],
                'preview_size': [96, 64], 'fps': '10/1', 'sources': {}, 'files': {}}
    (version / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    digest = hashlib.sha256(preview.read_bytes()).hexdigest()
    assessment = root / 'assessment.json'
    assessment.write_text(json.dumps({'state': 'matched', 'by': 'synthetic reader', 'file_sha256': digest,
                          'answer': {'what': 'a test film', 'audience': 'editors', 'why': 'see the result'}}),
                          encoding='utf-8')
    grade_code, grade_output = tool('grade.py', 'cold', project, '--version', 'v001', '--seconds', '1',
                                    '--record', '--assessment', assessment)
    final = root / 'final.mp4'
    shutil.copyfile(preview, final)
    final_code, final_output = tool('check.py', project, '--version', 'v001', '--final', final, '--no-speech')
    final_path = version / 'checks-final.json'
    try:
        data = json.loads(final_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    cold = next((row for row in data.get('items', []) if row.get('id') == 'context_cold'), {})
    record('cold read: project assessment reaches a byte-identical final',
           grade_code == 0 and final_code in (0, 1) and cold.get('state') == 'pass'
           and not any(row.get('state') == 'fail' for row in data.get('items', []))
           and 'synthetic reader' in cold.get('detail', '') and data.get('cold_read', {}).get('file_sha256') == digest,
           f'grade={grade_code}; check={final_code}; cold={cold}; '
           + grade_output[-120:] + final_output[-120:])

    preview_path = version / 'checks.json'
    try:
        preview_checks = json.loads(preview_path.read_text(encoding='utf-8'))
        prior = preview_checks['cold_read']
        final_data = json.loads(final_path.read_text(encoding='utf-8'))
        final_data['cold_read'] = prior
        final_path.write_text(json.dumps(final_data), encoding='utf-8')
        preview_checks['cold_read'] = dict(prior, state='mismatched', by='different reader')
        preview_path.write_text(json.dumps(preview_checks), encoding='utf-8')
        preference_code, preference_output = tool('check.py', project, '--version', 'v001', '--final', final,
                                                  '--no-speech')
        final_data = json.loads(final_path.read_text(encoding='utf-8'))
        chosen = next((row for row in final_data.get('items', []) if row.get('id') == 'context_cold'), {})
    except (OSError, ValueError, KeyError):
        preference_code, preference_output, chosen = 2, '', {}
    record('cold read: an existing final assessment takes precedence',
           preference_code in (0, 1) and chosen.get('state') == 'pass'
           and not any(row.get('state') == 'fail' for row in final_data.get('items', []))
           and 'synthetic reader' in chosen.get('detail', ''), str(chosen) + preference_output[-100:])

    different = root / 'different-final.mp4'
    remux = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-i', str(preview),
                            '-c', 'copy', '-metadata', 'title=different final', '-movflags', '+faststart',
                            str(different)], capture_output=True)
    mismatch_code, mismatch_output = tool('check.py', project, '--version', 'v001', '--final', different, '--no-speech')
    try:
        data = json.loads(final_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    mismatch = next((row for row in data.get('items', []) if row.get('id') == 'context_cold'), {})
    record('cold read: an assessment does not pass a different final file',
           remux.returncode == 0 and hashlib.sha256(different.read_bytes()).hexdigest() != digest
           and mismatch_code in (0, 1) and mismatch.get('state') == 'skip'
           and not any(row.get('state') == 'fail' for row in data.get('items', [])), str(mismatch) + mismatch_output[-100:])


def run_precision_cases(tool, record, j, scripts_dir):
    """Test low-energy transport and intended turn timing."""
    root = Path(j('u5-precision'))
    root.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('u5_precision_sync', Path(scripts_dir) / 'sync_check.py')
    sync = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync)
    rng = np.random.default_rng(8826)
    n = 4096
    ref = rng.normal(0, .2, n)
    near_silence = -rng.normal(0, 1.5e-9, n)
    segment = np.r_[ref, near_silence, ref]
    correlations = sync.xcorr(ref, segment)
    direct = np.dot(ref, near_silence) / np.sqrt(np.dot(ref, ref) * np.dot(near_silence, near_silence))
    finite = correlations[np.isfinite(correlations)]
    peak = int(np.nanargmax(correlations)) if finite.size else None
    record('transport: near-silent candidates cannot win or exceed one',
           finite.size > 0 and np.max(np.abs(finite)) <= 1 and not np.isfinite(correlations[n])
           and peak in (0, 2 * n),
           f'quiet correlation={correlations[n]}; direct={direct}; '
           f'maximum={np.max(finite) if finite.size else None}; peak={peak}')
    quiet_ref = rng.normal(0, 1e-9, n)
    quiet_scores = sync.xcorr(quiet_ref, segment)
    above_floor = rng.normal(0, 1e-4, n)
    above_scores = sync.xcorr(ref, np.r_[ref, above_floor])
    above_direct = np.dot(ref, above_floor) / np.sqrt(np.dot(ref, ref) * np.dot(above_floor, above_floor))
    record('transport: the floor excludes quiet references but measures usable low energy',
           not np.any(np.isfinite(quiet_scores)) and np.isfinite(above_scores[n])
           and abs(above_scores[n] - above_direct) < 1e-6,
           f'quiet finite={np.isfinite(quiet_scores).sum()}; '
           f'above-floor={above_scores[n]}; direct={above_direct}')

    def wav(path, samples):
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            stream.writeframes(np.clip(samples * 32767, -32768, 32767).astype('<i2').tobytes())

    reference, silent, sync_report = root / 'reference.wav', root / 'silent.wav', root / 'transport.json'
    reference_samples = rng.normal(0, .08, 3 * 48000)
    wav(reference, reference_samples)
    wav(silent, np.zeros(3 * 48000))
    code, output = tool('sync_check.py', silent, reference, '--windows', '3', '--window', '.5',
                        '--max-lag-ms', '100', '--json', sync_report)
    try:
        data = json.loads(sync_report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    rows = data.get('windows', [])
    quiet_reference_report = root / 'quiet-reference.json'
    quiet_code, quiet_output = tool('sync_check.py', reference, silent, '--windows', '3', '--window', '.5',
                                    '--max-lag-ms', '100', '--json', quiet_reference_report)
    try:
        quiet_data = json.loads(quiet_reference_report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        quiet_data = {}
    quiet_rows = quiet_data.get('windows', [])
    partial, partial_report = root / 'partial.wav', root / 'partial.json'
    wav(partial, np.r_[reference_samples[:2 * 48000], np.zeros(48000)])
    partial_code, partial_output = tool('sync_check.py', partial, reference, '--windows', '3', '--window', '.5',
                                        '--max-lag-ms', '100', '--json', partial_report)
    try:
        partial_data = json.loads(partial_report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        partial_data = {}
    adjusted = sync.scaled_windows(reference_samples, np.zeros_like(reference_samples), [4800], 2400, 2400,
                                   48000, 1.0)
    record('transport: quiet delivered and reference windows are reported not assessed',
           code == 1 and 'inconclusive' in data.get('summary', {}).get('verdict', '')
           and data.get('summary', {}).get('correlation_floor_dbfs') == -90
           and len(rows) == 3 and all(row.get('state') == 'not assessed' and row.get('correlation') is None
                                       and row.get('lag_ms') is None for row in rows)
           and quiet_code == 1 and len(quiet_rows) == 3
           and all(row.get('state') == 'not assessed' and row.get('correlation') is None for row in quiet_rows)
           and partial_code == 1 and partial_data.get('summary', {}).get('confident_windows') == 2
           and partial_data.get('summary', {}).get('not_assessed_windows') == 1
           and 'inconclusive' in partial_data.get('summary', {}).get('verdict', '')
           and len(adjusted) == 1 and adjusted[0].get('state') == 'not assessed'
           and sync.fit_rows(adjusted, 2, .8) is None,
           f"delivered summary={data.get('summary')}; rows={rows}; reference code={quiet_code}; "
           f"reference rows={quiet_rows}; partial={partial_data.get('summary')}; adjusted={adjusted}; "
           f"{output[-80:]} {quiet_output[-80:]} {partial_output[-80:]}")

    rate = 48000
    cue_data = {'version': 'v2', 'fps': 30, 'picture': {'kind': 'picture', 'sha256': '0' * 64}, 'events': [
        {'id': 'early', 't': 1., 'scale': 'turn', 'lead_ms': -125, 'sound': 'required'},
        {'id': 'later', 't': 2., 'scale': 'turn', 'lead_ms': 50, 'sound': 'required'},
        {'id': 'fractional', 't': 3., 'scale': 'turn', 'lead_ms': 116.666667, 'sound': 'required'},
        {'id': 'off_intent', 't': 4., 'scale': 'turn', 'lead_ms': 100, 'sound': 'required'}]}
    samples = np.zeros(5 * rate)
    burst = rng.normal(0, .4, 1200) * np.exp(-np.arange(1200) / 200)
    for at in (.875, 2.05, 3.116667, 4.14):
        i = round(at * rate)
        samples[i:i + len(burst)] = burst
    audio, cues, onset_report = root / 'turns.wav', root / 'turns.json', root / 'onsets.json'
    wav(audio, samples)
    wav(root / 'burst.wav', burst)
    cues.write_text(json.dumps(cue_data), encoding='utf-8')
    code, output = tool('cue_onsets.py', audio, cues, '--scale', 'turn', '--json', onset_report)
    try:
        data = json.loads(onset_report.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    by_id = {row.get('id'): row for row in data.get('rows', [])}
    statuses = [by_id.get(name, {}).get('status') for name in ('early', 'later', 'fractional', 'off_intent')]
    record('cue onsets: positive and negative turn leads are judged against intent',
           code == 1 and statuses == ['on cue', 'on cue', 'on cue', 'LATE']
           and all(abs(by_id[name].get('offset_ms', 999)) <= 10 for name in ('early', 'later', 'fractional'))
           and 25 < by_id.get('off_intent', {}).get('offset_ms', 0) < 60,
           f'statuses={statuses}; rows={list(by_id.values())}; {output[-150:]}')
    shift = round(.2 * rate)
    shifted_audio, shifted_report = root / 'shifted-turns.wav', root / 'shifted-onsets.json'
    wav(shifted_audio, np.r_[samples[shift:], np.zeros(shift)])
    shifted_code, shifted_output = tool('cue_onsets.py', shifted_audio, cues, '--scale', 'turn', '--offset', '.2',
                                       '--json', shifted_report)
    try:
        shifted = {row.get('id'): row for row in json.loads(shifted_report.read_text(encoding='utf-8')).get('rows', [])}
    except (OSError, ValueError):
        shifted = {}
    record('cue onsets: picture-relative and intent-relative offsets remain separate',
           shifted_code == 1 and all(isinstance(by_id.get(name, {}).get('picture_offset_ms'), (int, float))
               and abs(by_id[name]['picture_offset_ms'] - by_id[name]['lead_ms'] - by_id[name]['offset_ms']) <= 1.1
               and isinstance(shifted.get(name, {}).get('picture_offset_ms'), (int, float))
               and abs(shifted[name]['picture_offset_ms'] - by_id[name]['picture_offset_ms']) <= 1.1
               for name in ('early', 'later', 'fractional', 'off_intent')),
           f'unshifted={list(by_id.values())}; shifted={list(shifted.values())}; {shifted_output[-120:]}')
    reference_report = root / 'reference-onset.json'
    ref_code, ref_output = tool('cue_onsets.py', shifted_audio, cues, '--scale', 'turn', '--offset', '.2',
                                '--reference', 'early=' + str(root / 'burst.wav'), '--json', reference_report)
    try:
        referenced = json.loads(reference_report.read_text(encoding='utf-8')).get('rows', [])
    except (OSError, ValueError):
        referenced = []
    early = next((row for row in referenced if row.get('id') == 'early'), {})
    record('cue onsets: reference matching retains the picture-relative lead',
           ref_code == 1 and early.get('status') == 'on cue' and isinstance(early.get('picture_offset_ms'), (int, float))
           and abs(early['picture_offset_ms'] + 125) < 3 and abs(early.get('offset_ms', 999)) < 3,
           f'early={early}; {ref_output[-150:]}')
