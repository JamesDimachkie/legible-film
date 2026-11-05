"""Known-answer cases for check.py: the right checks for the file, plain states, and the project status."""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

TAGS = 'h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1'


def make_video(path, source, seconds=3, audio=True):
    """A small tagged H.264 file from an FFmpeg source, with a tone that fades in and out."""
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'{source}:d={seconds}']
    if audio:
        command += ['-f', 'lavfi', '-i', f'sine=f=440:d={seconds}', '-af',
                    f'afade=t=in:d=0.05,afade=t=out:st={seconds - 0.5}:d=0.2,volume=0.3']
    # A soft progressive pattern avoids comb-like synthetic edges; limit values leave encoding headroom.
    video_filter = "gblur=sigma=2,lut=y='clip(val,20,230)':u='clip(val,20,235)':v='clip(val,20,235)'"
    command += ['-vf', video_filter, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS]
    if audio:
        command += ['-c:a', 'aac', '-shortest']
    command += ['-movflags', '+faststart', str(path)]
    subprocess.run(command, check=True)


def states(report):
    """A map from item id to state."""
    return {entry['id']: entry['state'] for entry in report['items']}


def check_reviews_bound_to_file(record, j, scripts_dir):
    """A person's review counts only for the file it was recorded against; a failed final shows in the status line
    with its file and leaves the check stage open. The scanners are stubbed: this proves the bookkeeping only."""
    import hashlib
    check, why = load_module(scripts_dir, 'check')
    if check is None:
        record('check: person reviews are bound to the reviewed file', False, why)
        return
    root = Path(j('reviews-bound'))
    check.P.init(root)
    folder = root / 'cuts' / 'v001'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'film.md').write_text('---\nsize: 640x360\nfps: 30\n---\n', encoding='utf-8')
    (folder / 'preview.mp4').write_bytes(b'the preview the person watched')
    check.P.save_json(folder / 'manifest.json', {'version': 'v001', 'preview_size': [640, 360], 'size': [640, 360],
                                                 'fps': '30', 'duration_s': 1, 'frames': 30, 'files': {
                                                     'preview.mp4': hashlib.sha256(
                                                         b'the preview the person watched').hexdigest()}})
    final = root / 'deliver' / 'final.mp4'
    final.write_bytes(b'a different final nobody watched')
    check.P.set_current(root, 'v001')
    check.P.record_review(root, 'v001', 'watched_muted')
    check.P.update_status(root, reviewed={'v001': dict(check.P.read_status(root)['reviewed']['v001'],
                                                       heard={'by': 'person', 'at': '2026-10-01T00:00:00Z'})})

    def stub(video, qa, spec, duration, final, target, reviewed, *rest, **options):
        rows = [check.item('spec', 'Spec', 'fail' if final else 'pass', 'stub')]
        rows += check.person_items(reviewed, True, False)
        return {'version': 1, 'file': str(video), 'final': final, 'items': rows, 'summary': check.summarise(rows)}

    check.run_checks = stub
    preview = {row['id']: row['state'] for row in check.check_project(root, 'v001', None, False)['items']}
    finals = {row['id']: row['state'] for row in check.check_project(root, 'v001', final, False)['items']}
    record('check: a preview review (hashed or older) passes the preview but never a different final file',
           all(preview.get(key) == state for key, state in
               {'spec': 'pass', 'watched_muted': 'pass', 'heard': 'pass'}.items())
           and all(finals.get(key) == state for key, state in
                   {'spec': 'fail', 'watched_muted': 'you', 'heard': 'you'}.items()), f'{preview} {finals}')
    line, stage = check.P.status_line(root), check.P.read_status(root)['stages']['check']
    record('check: the status line shows a failed final with its file, and the check stage is not done',
           'final deliver/final.mp4 checked' in line and '1 failed' in line and stage == 'now', f'{line} {stage}')
    check.P.record_review(root, 'v001', 'watched_muted', final)
    finals = {row['id']: row['state'] for row in check.check_project(root, 'v001', final, False)['items']}
    record('check: a review recorded against the final file counts for it', finals.get('watched_muted') == 'pass'
           and finals.get('heard') == 'you', str(finals))


def check_missing_tool_claim(record, j, scripts_dir):
    """A file FFmpeg cannot read is not a missing FFmpeg: that is said only when FFmpeg really cannot be found."""
    module, error = load_module(scripts_dir, 'check')
    if module is None:
        record('check: "moov atom not found" is not called a missing FFmpeg', False, error)
        return
    damaged = ('ffprobe failed: [mov,mp4,m4a,3gp,3g2,mj2 @ 000] moov atom not found\n'
               'nomoov.mp4: Invalid data found when processing input')
    present = module.why_not_run('qc_file.py', 2, damaged)
    original = module.shutil.which
    module.shutil.which = lambda name, *args, **options: None
    try:
        absent = module.why_not_run('qc_file.py', 2, 'ffmpeg: not found')
    finally:
        module.shutil.which = original
    record('check: "moov atom not found" is not called a missing FFmpeg, and a missing FFmpeg still is',
           'was not found' not in present and 'Invalid data' in present and 'FFmpeg was not found' in absent,
           present + ' | ' + absent)
    folder = Path(j('check-no-moov'))
    folder.mkdir(parents=True, exist_ok=True)
    broken = folder / 'no-moov.mp4'
    broken.write_bytes(bytes.fromhex('00000018') + b'ftypisom' + bytes(4000))
    done = subprocess.run([sys.executable, '-I', str(Path(scripts_dir) / 'check.py'), '--file', str(broken)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    record('check: a file with no index exits 2 and does not ask for FFmpeg to be installed',
           done.returncode == 2 and 'install FFmpeg' not in done.stderr and 'could not run' in done.stderr,
           done.stderr[-300:])


def check_empty_captions(tool, record, j, scripts_dir):
    """An empty sidecar on a file with sound is never ok, and a transcript with no words of measurable sound is not
    assessed, never "no speech was heard"."""
    spec = importlib.util.spec_from_file_location('lf_project_empty', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    folder = Path(j('check-empty-captions'))
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / 'export.mp4'
    make_video(video, 'testsrc2=s=320x180:r=30')
    empty, words = folder / 'empty.srt', folder / 'words.json'
    empty.write_bytes(b'')
    words.write_text(json.dumps({'words': [], 'media': {'sha256': file_sha(video)}}), encoding='utf-8')

    def checked(name, path=video, *extra):
        out = folder / (name + '.json')
        code, output = tool('check.py', '--file', path, '--captions', empty, '--speech-words', words, *extra,
                            '--json', out)
        return code, by_id(checks_at(out)), output

    code, found, output = checked('plain')
    rules, speech = found.get('captions_rules', {}), found.get('captions_speech', {})
    record('check: an empty sidecar on a file with sound is a look, not "0 captions follow the reading rules"',
           code == 1 and rules.get('state') == 'look' and 'empty' in rules.get('label', '')
           and 'empty.srt' in rules.get('detail', ''), str(rules) + output[-300:])
    record('check: a transcript with no words of measurable sound is not assessed, never "no speech was heard"',
           speech.get('state') == 'skip' and speech.get('label', '').startswith('Not assessed')
           and 'no speech was heard' not in output and 'LUFS' in speech.get('detail', ''), str(speech))
    record('check: an empty sidecar does not read as following the edit, or ask a person to check its names',
           found.get('captions_edit', {}).get('state') == 'skip' and 'names' not in found,
           str(found.get('captions_edit')))
    required = folder / 'delivery.json'
    required.write_text(json.dumps({'captions_required': True}), encoding='utf-8')
    code, found, output = checked('required', video, '--delivery', str(required))
    record('check: an empty sidecar fails when the delivery settings require captions',
           code == 1 and found.get('captions_rules', {}).get('state') == 'fail'
           and 'required' in found.get('captions_rules', {}).get('label', ''), str(found.get('captions_rules')))
    empty.write_text('  \n\n', encoding='utf-8')
    _, found, _ = checked('blank')
    record('check: a sidecar of blank lines is an empty sidecar',
           found.get('captions_rules', {}).get('state') == 'look', str(found.get('captions_rules')))
    silent = folder / 'silent.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=2', '-f', 'lavfi',
                    '-i', 'anullsrc=r=48000:cl=stereo', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac', str(silent)], check=True)
    words.write_text(json.dumps({'words': [], 'media': {'sha256': file_sha(silent)}}), encoding='utf-8')
    empty.write_bytes(b'')
    _, found, _ = checked('silent', silent)
    speech = found.get('captions_speech', {})
    record('check: on sound that measures as silence, no words and no captions are measured facts, not gaps',
           found.get('captions_rules', {}).get('state') == 'pass' and speech.get('state') == 'pass'
           and 'no speech was heard' in speech.get('detail', '') and 'silence' in speech.get('detail', ''), str(speech))

    root, version = make_version(project, j('check-empty-project'), '')
    code, output = tool('check.py', root, '--no-speech')
    found = read_checks(version)
    record('check: a project version with sound and an empty captions.srt is a look',
           code == 1 and found.get('captions_rules', {}).get('state') == 'look'
           and 'captions.srt' in found.get('captions_rules', {}).get('detail', ''),
           str(found.get('captions_rules')) + output[-300:])
    film = version / 'film.md'
    film.write_text(film.read_text(encoding='utf-8').replace('fps: 30', 'fps: 30\ncaptions: none'), encoding='utf-8')
    code, output = tool('check.py', root, '--no-speech')
    record('check: a film that says captions: none has no caption items', 'captions_rules' not in read_checks(version),
           str(read_checks(version).get('captions_rules')) + output[-200:])
    final = version / 'final-empty.srt'
    final.write_bytes(b'')
    code, output = tool('check.py', root, '--final', version / 'preview.mp4', '--captions', final, '--no-speech')
    found = read_checks(version, 'checks-final.json')
    record('check: a project final with an empty sidecar is a look, not a pass',
           found.get('captions_rules', {}).get('state') == 'look', str(found.get('captions_rules')) + output[-300:])
    speech = speech_with(scripts_dir, j('check-empty-no-words'), '1\n00:00:00,000 --> 00:00:01,500\nHello there\n', [])
    record('check: captions over a transcript with no words are a look, not a match',
           speech.get('state') == 'look', str(speech))
    code, output = tool('captions.py', 'check', empty, '--words', words, '--strict')
    record('captions: --strict does not call an empty file against no words complete',
           code == 1 and '"complete": false' in output, output[-300:])


def edit_source(folder):
    """20 s whose every 1.5 s of picture and sound is unlike the rest: random blocks that drift, and noise bands whose
    level changes every fifth of a second. A wrong passage cannot pass for the right one by chance."""
    import numpy as np
    import wave
    folder = Path(folder)
    rng = np.random.default_rng(22)
    width, height, rate, seconds = 320, 180, 12, 20
    frames = bytearray()
    for shot in range(int(seconds / 1.5) + 1):
        blocks = rng.integers(30, 225, (9, 16, 3), dtype=np.uint8)
        picture = np.repeat(np.repeat(blocks, 20, axis=0), 20, axis=1)
        for number in range(18):
            frames += np.roll(picture, number, axis=1).tobytes()
    frames = bytes(frames[:width * height * 3 * rate * seconds])
    samples = np.zeros(48000 * seconds)
    for start in range(0, len(samples), 9600):
        noise = rng.normal(0, 1, 9600)
        spectrum = np.fft.rfft(noise)
        low, high = sorted(rng.integers(20, 2400, 2))
        spectrum[:low] = 0
        spectrum[high + 200:] = 0
        burst = np.fft.irfft(spectrum, n=9600)
        samples[start:start + 9600] = burst / (np.abs(burst).max() + 1e-9) * rng.uniform(.05, .5)
    wav = folder / 'source.wav'
    with wave.open(str(wav), 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes((samples * 32767).astype('<i2').tobytes())
    source = folder / 'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{width}x{height}',
                    '-r', str(rate), '-i', '-', '-i', str(wav), '-map', '0:v', '-map', '1:a', '-c:v', 'libx264',
                    '-crf', '16', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac', '-b:a', '192k', '-movflags',
                    '+faststart', str(source)], input=frames, check=True, capture_output=True)
    return source, wav


def check_edit_content(tool, record, j):
    """A quick edit is compared with its source where that is cheap, tolerant of re-encoding and scaling: confident
    disagreement is a fail, too little to compare is not assessed, and an edit kind that cannot be compared says so."""
    folder = Path(j('check-edit-content'))
    folder.mkdir(parents=True, exist_ok=True)
    source, wav = edit_source(folder)

    def make(name, *args):
        path = folder / name
        subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args), str(path)], check=True, capture_output=True)
        return path

    def checked(path, edit):
        out = folder / (Path(path).stem + '-' + edit.split(':')[0] + '.json')
        code, output = tool('check.py', '--file', path, '--against', source, '--edit', edit, '--no-speech',
                            '--json', out)
        return code, by_id(checks_at(out)), output

    tone = make('wrong.wav', '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000:duration=20')
    code, found, output = checked(tone, 'extract-audio')
    record('quick edits: a tone passed off as the extracted audio fails, naming what it compared',
           code == 1 and found.get('edit_audio', {}).get('state') == 'fail'
           and 'differs' in found['edit_audio']['detail'], str(found.get('edit_audio')) + output[-200:])
    silent = make('silent.wav', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '20')
    code, found, output = checked(silent, 'extract-audio')
    record('quick edits: silence passed off as the extracted audio fails',
           found.get('edit_audio', {}).get('state') == 'fail', str(found.get('edit_audio')))
    other = make('other.wav', '-ss', 5, '-i', wav, '-af', 'apad', '-t', '20')
    code, found, output = checked(other, 'extract-audio')
    record('quick edits: another passage passed off as the extracted audio fails',
           found.get('edit_audio', {}).get('state') == 'fail', str(found.get('edit_audio')))
    for name, *options in (('right.m4a', '-c:a', 'aac', '-b:a', '128k'), ('right.wav', '-c:a', 'pcm_s16le'),
                           ('right-low.m4a', '-ac', '1', '-c:a', 'aac', '-b:a', '24k')):
        right = make(name, '-i', source, '-vn', *options)
        code, found, output = checked(right, 'extract-audio')
        wanted = ('pass', 'skip') if 'low' in name else ('pass',)
        record(f'quick edits (control): the real audio, {name}, raises no false alarm in extract-audio',
               found.get('edit_audio', {}).get('state') in wanted, str(found.get('edit_audio')) + output[-200:])

    def clip(name, picture, sound, *options):
        """6 s of output, with its picture and sound from the given source times."""
        return make(name, '-ss', picture, '-t', 6, '-i', source, '-ss', sound, '-t', 6, '-i', source,
                    '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p',
                    '-bsf:v', TAGS, '-c:a', 'aac', *options)

    code, found, output = checked(clip('trim-right.mp4', 2, 2), 'trim:2,8')
    record('quick edits (control): a correct trim passes on picture and sound',
           found.get('edit_picture', {}).get('state') == 'pass'
           and found.get('edit_trim_content_offset', {}).get('state') == 'pass',
           str(found.get('edit_picture')) + str(found.get('edit_trim_content_offset')))
    low = make('trim-low.mp4', '-ss', 2, '-t', 6, '-i', source, '-vf', 'scale=160:-2,fps=8', '-c:v', 'libx264', '-b:v',
               '40k', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-ac', '1', '-c:a', 'aac', '-b:a', '24k')
    code, found, output = checked(low, 'trim:2,8')
    record('quick edits (control): a correct trim scaled and re-encoded at a low bitrate raises no false alarm',
           found.get('edit_picture', {}).get('state') == 'pass'
           and found.get('edit_trim_content_offset', {}).get('state') in ('pass', 'skip'),
           str(found.get('edit_picture')) + str(found.get('edit_trim_content_offset')))
    code, found, output = checked(clip('trim-wrong-picture.mp4', 10, 2), 'trim:2,8')
    record('quick edits: the right sound over picture from 10-16 s fails on the picture, naming the frames',
           code == 1 and found.get('edit_picture', {}).get('state') == 'fail'
           and found.get('edit_trim_content_offset', {}).get('state') == 'pass'
           and 'do not match' in found['edit_picture']['detail'], str(found.get('edit_picture')))
    code, found, output = checked(clip('trim-wrong-both.mp4', 10, 10), 'trim:2,8')
    sound = found.get('edit_trim_content_offset', {})
    record('quick edits: picture and sound both from 10-16 s fail on both, not "too few confident windows"',
           code == 1 and found.get('edit_picture', {}).get('state') == 'fail' and sound.get('state') == 'fail'
           and 'differs' in sound.get('detail', '') and 'too few' not in sound.get('detail', ''), str(sound))
    code, found, output = checked(clip('trim-offset.mp4', 2, 2.15), 'trim:2,8')
    record('quick edits: a real offset is still called an offset, not different content',
           found.get('edit_trim_content_offset', {}).get('state') == 'fail'
           and 'offset' in found.get('edit_trim_content_offset', {}).get('detail', ''),
           str(found.get('edit_trim_content_offset')))
    shaped = make('trim-reframed.mp4', '-ss', 2, '-t', 6, '-i', source, '-vf', 'crop=101:180', '-c:v', 'libx264',
                  '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac')
    code, found, output = checked(shaped, 'trim:2,8')
    record('quick edits (control): a trim that also reframes is not assessed on its picture, never a false alarm',
           found.get('edit_picture', {}).get('state') == 'skip'
           and found['edit_picture']['label'].startswith('Not assessed: content'), str(found.get('edit_picture')))
    black = make('black.mp4', '-f', 'lavfi', '-i', 'color=black:s=320x180:r=12:d=20', '-f', 'lavfi', '-i',
                 'sine=frequency=440:sample_rate=48000:duration=20', '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                 '-bsf:v', TAGS, '-c:a', 'aac', '-shortest', '-movflags', '+faststart')
    flat = make('black-trim.mp4', '-ss', 2, '-t', 6, '-i', black, '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-bsf:v', TAGS, '-c:a', 'aac')
    out = folder / 'flat.json'
    code, output = tool('check.py', '--file', flat, '--against', black, '--edit', 'trim:2,8', '--no-speech',
                        '--json', out)
    found = by_id(checks_at(out))
    record('quick edits: flat picture and a steady tone are too little to compare: not assessed, never fail',
           found.get('edit_picture', {}).get('state') == 'skip'
           and found['edit_picture']['label'].startswith('Not assessed: content')
           and found.get('edit_trim_content_offset', {}).get('state') == 'skip',
           str(found.get('edit_picture')) + str(found.get('edit_trim_content_offset')))
    detail = make('detail-over-flat.mp4', '-ss', 10, '-t', 6, '-i', source, '-map', '0:v:0', '-c:v', 'libx264',
                  '-pix_fmt', 'yuv420p', '-bsf:v', TAGS)
    out = folder / 'detail-flat.json'
    tool('check.py', '--file', detail, '--against', black, '--edit', 'trim:2,8', '--no-speech', '--json', out)
    record('quick edits: a picture where its source is flat black fails',
           by_id(checks_at(out)).get('edit_picture', {}).get('state') == 'fail',
           str(by_id(checks_at(out)).get('edit_picture')))

    fast = make('speed.mp4', '-i', source, '-filter_complex', '[0:v]setpts=0.5*PTS[v];[0:a]atempo=2[a]', '-map', '[v]',
                '-map', '[a]', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac')
    code, found, output = checked(fast, 'speed:0.5')
    record('quick edits (control): a correct speed change passes on the picture, and says the sound was not compared',
           found.get('edit_picture', {}).get('state') == 'pass' and found.get('edit_audio', {}).get('state') == 'skip'
           and found['edit_audio']['label'].startswith('Not assessed: content'), str(found.get('edit_audio')))
    wrong_fast = make('speed-wrong.mp4', '-ss', 4, '-i', source, '-filter_complex',
                      '[0:v]setpts=0.5*PTS[v];[0:a]atempo=2[a]', '-map', '[v]', '-map', '[a]', '-t', 10, '-c:v',
                      'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac')
    code, found, output = checked(wrong_fast, 'speed:0.5')
    record('quick edits: a speed change from the wrong place fails on the picture',
           found.get('edit_picture', {}).get('state') == 'fail', str(found.get('edit_picture')))

    small = make('compress.mp4', '-i', source, '-vf', 'scale=200:-2', '-c:v', 'libx264', '-b:v', '60k', '-pix_fmt',
                 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac', '-b:a', '32k', '-movflags', '+faststart')
    code, found, output = checked(small, 'compress')
    record('quick edits (control): a correct compress at a low bitrate raises no false alarm on picture or sound',
           found.get('edit_picture', {}).get('state') == 'pass'
           and found.get('edit_audio', {}).get('state') in ('pass', 'skip'),
           str(found.get('edit_picture')) + str(found.get('edit_audio')))
    other = make('compress-wrong.mp4', '-ss', 5, '-i', source, '-vf', 'tpad=stop_mode=clone:stop_duration=5', '-af',
                 'apad', '-t', 20, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac')
    code, found, output = checked(other, 'compress')
    record('quick edits: a compress of the wrong passage fails on picture and sound',
           found.get('edit_picture', {}).get('state') == 'fail' and found.get('edit_audio', {}).get('state') == 'fail',
           str(found.get('edit_picture')) + str(found.get('edit_audio')))
    converted = make('convert.mkv', '-i', source, '-c:v', 'mpeg4', '-q:v', '12', '-c:a', 'aac')
    code, found, output = checked(converted, 'convert')
    record('quick edits (control): a correct convert passes on picture and sound',
           found.get('edit_picture', {}).get('state') == 'pass' and found.get('edit_audio', {}).get('state') == 'pass',
           str(found.get('edit_picture')) + str(found.get('edit_audio')))
    gif = make('convert.gif', '-i', source, '-an', '-vf', 'fps=8,scale=160:-1')
    code, found, output = checked(gif, 'convert')
    record('quick edits (control): a correct GIF passes on picture, and says it carries no sound to compare',
           found.get('edit_picture', {}).get('state') == 'pass' and found.get('edit_audio', {}).get('state') == 'skip'
           and found['edit_audio']['label'].startswith('Not assessed: content'),
           str(found.get('edit_picture')) + str(found.get('edit_audio')))
    reframed = make('reframe.mp4', '-i', source, '-vf', 'crop=101:180,scale=406:720', '-c:v', 'libx264', '-pix_fmt',
                    'yuv420p', '-bsf:v', TAGS, '-c:a', 'copy')
    code, found, output = checked(reframed, 'reframe')
    record('quick edits: a reframe keeps its sound compared and says plainly the picture was not',
           found.get('edit_audio', {}).get('state') == 'pass' and found.get('edit_picture', {}).get('state') == 'skip'
           and 'Not assessed: content' in output, str(found.get('edit_picture')) + str(found.get('edit_audio')))
    code, found, output = checked(make('captions.mkv', '-i', source, '-c', 'copy'), 'captions')
    record('quick edits: a captions edit compares its packets, as content that must not change',
           found.get('edit_video', {}).get('state') == 'pass' and found.get('edit_audio', {}).get('state') == 'pass',
           str(found.get('edit_video')))


def check_default_audio_stream(tool, record, j):
    """check.py measures the stream a player plays by default and names the others; a silent default with sound in
    another stream is a look."""
    folder = Path(j('check-audio-streams'))
    folder.mkdir(parents=True, exist_ok=True)

    def source(name, default):
        path = folder / name
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=3', '-f', 'lavfi',
                        '-i', 'anullsrc=r=48000:cl=stereo', '-f', 'lavfi',
                        '-i', 'sine=frequency=440:sample_rate=48000:duration=3', '-map', '0:v', '-map', '1:a',
                        '-map', '2:a', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                        '-disposition:a:0', 'default' if default == 0 else '0',
                        '-disposition:a:1', 'default' if default == 1 else '0', str(path)],
                       check=True, capture_output=True)
        return path

    second = source('default-second.mkv', 1)
    code, output = tool('check.py', '--file', second, '--no-speech', '--json', folder / 'second.json')
    found = by_id(checks_at(folder / 'second.json'))
    level = found.get('loudness', {})
    streams = found.get('audio_streams', {})
    record('check: the stream a player plays by default is the one measured when it is not the first',
           'LUFS' in level.get('label', '') and '-70' not in level.get('label', '')
           and streams.get('state') == 'pass' and 'stream 2' in streams.get('label', '')
           and 'stream 1' in streams.get('detail', ''), str(level) + str(streams) + output[-200:])
    first = source('default-first.mkv', 0)
    code, output = tool('check.py', '--file', first, '--no-speech', '--json', folder / 'first.json')
    found = by_id(checks_at(folder / 'first.json'))
    streams = found.get('audio_streams', {})
    record('check: a silent default stream with sound in another is a look that names both',
           code == 1 and streams.get('state') == 'look' and 'stream 1' in streams.get('label', '')
           and 'stream 2' in streams.get('detail', ''), str(streams) + output[-200:])
    plain = folder / 'plain.mp4'
    make_video(plain, 'testsrc2=s=320x180:r=30')
    code, output = tool('check.py', '--file', plain, '--no-speech', '--json', folder / 'plain.json')
    record('check: one sound stream gets no stream item',
           'audio_streams' not in by_id(checks_at(folder / 'plain.json')), output[-200:])


def run_check_cases(tool, record, j, scripts_dir):
    """Clean and flashing files, a project version with captions, person reviews and exit codes."""
    check_reviews_bound_to_file(record, j, scripts_dir)
    check_missing_tool_claim(record, j, scripts_dir)
    check_default_audio_stream(tool, record, j)
    check_edit_content(tool, record, j)
    check_empty_captions(tool, record, j, scripts_dir)
    check_craft2_units(record, scripts_dir)
    check_craft2_pattern_battery(tool, record, j)
    check_craft2_fine_pattern(tool, record, j)
    check_craft2_red_patterns(tool, record, j)
    check_craft2_moving_flash_media(tool, record, j)
    clean = Path(j('check-clean.mp4'))
    make_video(clean, 'testsrc2=s=320x180:r=30')
    code, output = tool('check.py', '--file', clean, '--spec', '320x180@30', '--duration', 3, '--loudness', -30,
                        '--json', j('check-clean.json'))
    report = json.loads(Path(j('check-clean.json')).read_text(encoding='utf-8'))
    found = states(report)
    record('check: a clean tagged file passes spec, edges, flashing and blank frames; a person still needs to look',
           found.get('spec') == 'pass' and found.get('edges') == 'pass' and found.get('flash') == 'pass'
           and found.get('blank') == 'pass' and found.get('watched_muted') == 'you' and found.get('heard') == 'you',
           str(found) + ' ' + output[-200:])
    record('check: loudness is measured on a final file and compared with its target',
           found.get('loudness') in ('pass', 'look') and 'LUFS' in next(e['label'] for e in report['items']
                                                                     if e['id'] == 'loudness'), str(report['items'][1]))
    # A range of a longer source is screened on the source's clock: 3 s still, then 2 s of 5 Hz flashing.
    ranged = Path(j('check-flash-range.mp4'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    "color=c=gray:s=320x180:r=30:d=5,geq=lum='if(gte(T\\,3)\\,255*mod(floor(N/3)\\,2)\\,128)'"
                    ":cb=128:cr=128", '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(ranged)], check=True)
    calm_code, _ = tool('flash_scan.py', ranged, '--end', 2.5, '--json', j('flash-range-calm.json'))
    hit_code, _ = tool('flash_scan.py', ranged, '--start', 2.5, '--json', j('flash-range-hit.json'))
    hit = json.loads(Path(j('flash-range-hit.json')).read_text(encoding='utf-8')) if Path(
        j('flash-range-hit.json')).exists() else {}
    at = (hit.get('busiest_general') or {}).get('at_s')
    record('check: flash_scan screens part of a source and reports source times',
           calm_code == 0 and hit_code == 1 and isinstance(at, (int, float)) and at >= 2.9,
           f'{calm_code} {hit_code} {at}')
    flashing = Path(j('check-flash.mp4'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    "color=c=black:s=320x180:r=30:d=3,geq=lum='255*mod(floor(N/3),2)':cb=128:cr=128",
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, str(flashing)], check=True)
    code, output = tool('check.py', '--file', flashing, '--json', j('check-flash.json'))
    report = json.loads(Path(j('check-flash.json')).read_text(encoding='utf-8'))
    found = states(report)
    record('check: a 5 Hz full-frame flash fails, and a silent file asks nobody to listen',
           code == 1 and found.get('flash') == 'fail' and 'heard' not in found and found.get('loudness') == 'skip',
           str(found))
    spec_detail = next((e.get('detail') or '' for e in report['items'] if e['id'] == 'spec'), None)
    record('check: a silent final is not failed for lacking sound to re-encode; true peak is asked of files with sound',
           spec_detail is not None and 'audio_checks_runnable' not in spec_detail and 'true_peak' not in found,
           str(spec_detail))
    spec = importlib.util.spec_from_file_location('lf_project_check', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    root = project.init(Path(j('check-project')), 'Check case')
    folder = root / 'cuts' / 'v001'
    folder.mkdir(parents=True)
    make_video(folder / 'preview.mp4', 'testsrc2=s=320x180:r=30')
    project.save_json(folder / 'manifest.json', {'version': 'v001', 'parent': None, 'duration_s': 3.0,
                                                 'size': [320, 180], 'fps': '30'})
    (folder / 'film.md').write_text('---\ntitle: Check case\nsize: 320x180\nfps: 30\n---\n', encoding='utf-8')
    (folder / 'captions.srt').write_text('1\n00:00:00,500 --> 00:00:02,500\nHello there\n', encoding='utf-8')
    write_lines(project, folder, [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    project.set_current(root, 'v001')
    code, output = tool('check.py', root, '--no-speech')
    report = json.loads((folder / 'checks.json').read_text(encoding='utf-8'))
    found = states(report)
    status = project.read_status(root)
    record('check: a version is checked with its captions, and the status names what needs the person',
           code == 0 and found.get('captions_edit') == 'pass' and found.get('captions_rules') == 'pass'
           and found.get('captions_speech') == 'skip' and found.get('loudness') == 'pass'
           and found.get('names') == 'you' and status['stages']['check'] == 'done'
           and 'Watched by you, muted' in status['needs_you'] and status['line'].startswith('v1 checked'),
           str(found) + ' ' + str(status.get('line')) + ' ' + output[-200:])
    record('check: rendered files are untouched; raw outputs go to the version qa folder',
           (folder / 'qa' / 'qc.json').is_file() and not (folder / 'qc.json').exists())
    project.update_status(root, reviewed={'v001': {'watched_muted': {'by': 'Sam', 'at': project.now()}}})
    code, output = tool('check.py', root, '--no-speech')
    report = json.loads((folder / 'checks.json').read_text(encoding='utf-8'))
    watched = next(entry for entry in report['items'] if entry['id'] == 'watched_muted')
    record('check: a review the person recorded counts as passed, with their name',
           watched['state'] == 'pass' and 'Sam' in watched['label'], str(watched))
    record('check: checks.json names the file relative to the project, never by its absolute path',
           not Path(report['file']).is_absolute() and report['file'].startswith('cuts/'), report['file'])
    code, output = tool('check.py', j('no-project-here'))
    record('check: no project and no file is an error that says what to do', code == 2 and '--file' in output,
           output[-200:])
    run_check_proof_cases(tool, record, j, scripts_dir)
    run_check_coverage_cases(tool, record, j, scripts_dir)
    check_edge_and_target(tool, record, j)
    check_red_transition_area(tool, record, j)
    check_declaration_forwarding(tool, record, j)
    check_title_contrast(record, j)
    check_first_frame(tool, record, j)
    check_word_counts(record)
    check_dropouts(record, j)
    check_technical_findings(tool, record, j)
    check_technical_media(tool, record, j)
    check_vad_disclosure(tool, record, j)
    check_last_sound_cut_short(tool, record, j, scripts_dir)
    run_native_cases(tool, record, j, scripts_dir)
    run_fix2_check_cases(tool, record, j, scripts_dir)
    run_fix2_qa_tool_alias_case(record, j, scripts_dir)
    run_fix2_speech_input_cases(record, j, scripts_dir)
    run_fix2_tool_dependency_cases(record, j, scripts_dir)


def check_last_sound_cut_short(tool, record, j, scripts_dir):
    """A film 0.2 of a frame past 48 frames at 24 fps whose last sound fades out over 15 ms, ending 8 ms after the
    picture's last frame, muxed the way cut.py does (sound cut where the picture ends): the end is named with its
    cause and remedy. The same film made whole frames passes, and a file with no edit to read is still told what an
    abrupt end means."""
    spec = importlib.util.spec_from_file_location('lf_project_cut_short', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    found = {}
    for name, sound in (('short', 2.0 + 0.2 / 24), ('whole', 2.0)):
        root = project.init(Path(j('cut-short-' + name)), 'Cut short case')
        folder = root / 'cuts' / 'v001'
        folder.mkdir(parents=True, exist_ok=True)
        stem = Path(j('cut-short-' + name + '.wav'))
        tone = (f'sine=f=440:r=48000:d={sound:.6f},volume=0.3,afade=t=in:d=0.015,'
                f'afade=t=out:st={sound - 0.015:.6f}:d=0.015')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', tone, '-c:a', 'pcm_s16le', str(stem)],
                       check=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=24:d=2',
                        '-i', str(stem), '-filter_complex', '[1:a]apad[mix]', '-map', '0:v', '-map', '[mix]',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS, '-c:a', 'aac', '-b:a', '192k',
                        '-ar', '48000', '-ac', '2', '-movflags', '+faststart', '-t', '2.000000',
                        str(folder / 'preview.mp4')], check=True)
        project.save_json(folder / 'manifest.json', {'version': 'v001', 'parent': None, 'size': [320, 180],
                                                     'fps': '24', 'duration_s': 2.0, 'frames': 48})
        clip = {'src': 'tone', 'in': 0.0, 'out': round(sound, 6)}
        project.save_json(folder / 'edit.json', {'version': 1, 'size': [320, 180], 'fps': '24', 'picture': [clip],
                                                 'audio': [dict(clip, track='nat', at=0.0, fade_ms=15)]})
        (folder / 'film.md').write_text('---\ntitle: Cut short case\nsize: 320x180\nfps: 24\n---\n', encoding='utf-8')
        project.set_current(root, 'v001')
        tool('check.py', root, '--no-speech')
        found[name] = read_checks(folder).get('edges', {})
    short = found['short']
    record('check: a last sound cut 8 ms before its fade-out ends names the cause and the remedy',
           short.get('state') == 'look' and short.get('label') == 'Last sound cut short'
           and "8 ms after the picture's last frame" in short.get('detail', '')
           and 'whole frames' in short.get('detail', '') and 'end the sound earlier' in short.get('detail', ''),
           str(found))
    record('check: the same film made a whole number of frames ends in silence and passes',
           found['whole'].get('state') == 'pass', str(found['whole']))
    report = Path(j('cut-short-file.json'))
    tool('check.py', '--file', Path(j('cut-short-short')) / 'cuts' / 'v001' / 'preview.mp4', '--json', report)
    edges = next((entry for entry in (json.loads(report.read_text(encoding='utf-8')) if report.is_file() else
                                      {}).get('items', []) if entry['id'] == 'edges'), {})
    record('check: without an edit to read, an abrupt end is still named as sound playing when the picture ends',
           edges.get('label') == 'Sound ends abruptly' and 'still playing when the picture ends' in
           edges.get('detail', '') and 'hold the picture' in edges.get('detail', ''), str(edges))


def check_edge_and_target(tool, record, j):
    """Faded and hard PCM boundaries, plus loudness with and without a requested target."""
    check_zero_phase_edge(record, j)
    check_audio_ends_early(record, j)
    import wave
    import numpy as np
    scripts = Path(__file__).resolve().parent.parent
    modules = {}
    for name in ('qc_file', 'check'):
        spec = importlib.util.spec_from_file_location('case_' + name, scripts / (name + '.py'))
        modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modules[name])
    rate = 48000
    signal = .7 * np.cos(2 * np.pi * 440 * np.arange(rate) / rate)
    faded = signal.copy()
    faded[:720] *= np.arange(720) / 720
    faded[-720:] *= np.arange(720, 0, -1) / 720
    reports = {}
    for name, samples in (('fade', faded), ('hard', signal)):
        path = Path(j('edge-' + name + '.wav'))
        with wave.open(str(path), 'wb') as handle:
            handle.setparams((1, 2, rate, len(samples), 'NONE', 'not compressed'))
            handle.writeframes((samples * 32767).astype('<i2').tobytes())
        reports[name] = modules['qc_file'].audio_edges('ffmpeg', str(path), 1)
    record('check: 15 ms fades pass while discontinuous hard boundaries prompt a listen',
           not reports['fade']['notes'] and len(reports['hard']['notes']) == 2, str(reports))
    try:
        measured = modules['check'].loudness_items({'loudness': {'integrated_lufs': -23}}, None, True, True)[0]
        requested = modules['check'].loudness_items({'loudness': {'integrated_lufs': -23}}, -14, True, True)[0]
        ok = measured['state'] == 'pass' and 'target' not in measured['label'] and requested['state'] == 'look'
    except (TypeError, ValueError) as error:
        ok = False
        measured = str(error)
    record('check: loudness is compared only when a target is named', ok, str(measured))


def check_red_transition_area(tool, record, j):
    """A barely moving red edge is not a full-area red flash; a large red reversal is."""
    import numpy as np
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_flash', scripts / 'flash_scan.py')
    flash = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(flash)
    if not hasattr(flash, 'RedZig'):
        record('check: red flash requires a large area to change, not a percentile crossing', False,
               'the existing red statistic jumps when an edge crosses the percentile')
        return
    events = {}
    for name, counts in (('jitter', (2590, 2610)), ('large_flash', (0, 3000)), ('small_flash', (0, 1000))):
        detector = flash.RedZig()
        for frame in range(60):
            pixels = np.zeros(10000, dtype=np.float32)
            pixels[:counts[frame % 2]] = 320
            detector.push(frame, pixels)
        detector.finish()
        events[name] = len(detector.ends)
    record('check: red flash requires a large area to change, not a percentile crossing',
           events['jitter'] == 0 and events['small_flash'] == 0 and events['large_flash'] > 6, str(events))


def check_dropouts(record, j):
    """A hole of digital silence inside the sound is named with its time; room tone under a pause, and silence after
    the last sound, are not holes."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_dropouts', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    folder = Path(j('dropouts'))
    folder.mkdir(parents=True, exist_ok=True)
    tone = '0.1*sin(2*PI*440*t)'
    sounds = {'hole': f'if(between(t,1,1.3),0,{tone})',
              'room': f'if(between(t,1,1.3),0.001*sin(2*PI*97*t),{tone})',
              'tail': f'if(gt(t,2.5),0,{tone})'}
    states = {}
    for name, expression in sounds.items():
        video = folder / (name + '.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=gray:s=64x64:r=10:d=3',
                        '-f', 'lavfi', '-i', f"aevalsrc='{expression}':s=48000:d=3", '-c:v', 'libx264',
                        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video)], check=True)
        states[name] = check.dropout_item(video, True)
    record('check: a hole of digital silence inside the sound is named with its time; room tone and a silent tail '
           'are not holes',
           states['hole']['state'] == 'look' and '0:01.0' in states['hole']['detail']
           and len(states['hole'].get('holes', [])) == 1 and abs(states['hole']['holes'][0][0] - 1.0) < 0.05
           and states['room']['state'] == 'pass' and states['tail']['state'] == 'pass', str(states))


def check_title_contrast(record, j):
    """A white title over a pale picture is named with its time; the same title over a dark picture passes; a
    full-frame card is not measured. An agent caught a white title on cream paper by eye after every check passed."""
    from PIL import Image, ImageDraw
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_titles', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    folder = Path(j('title-contrast'))
    (folder / 'titles').mkdir(parents=True, exist_ok=True)
    title = Image.new('RGBA', (320, 180), (0, 0, 0, 0))
    draw = ImageDraw.Draw(title)
    for x in range(60, 260, 40):
        draw.rectangle((x, 40, x + 24, 70), fill=(255, 255, 255, 255))
    title.save(folder / 'titles' / 'title-01.png')
    Image.new('RGBA', (320, 180), (20, 20, 20, 255)).save(folder / 'titles' / 'title-02.png')
    edit = {'sources': {'title-01': {'file': 'titles/title-01.png'}, 'title-02': {'file': 'titles/title-02.png'}},
            'overlays': [{'kind': 'image', 'src': 'title-01', 'from': 0.5, 'to': 1.5, 'x': 0, 'y': 0, 'w': 1.0}]}
    (folder / 'edit.json').write_text(json.dumps(edit), encoding='utf-8')
    states = {}
    for name, colour in (('pale', '0xF0EAD6'), ('dark', '0x202838')):
        video = folder / (name + '.mp4')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={colour}:s=320x180:r=10:d=2',
                        '-i', str(folder / 'titles' / 'title-01.png'), '-filter_complex', 'overlay',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
        fresh = folder / ('fresh-' + name)
        fresh.mkdir(exist_ok=True)
        states[name] = check.title_contrast_item(folder, video, fresh)
    edit['overlays'] = [{'kind': 'image', 'src': 'title-02', 'from': 0.5, 'to': 1.5, 'x': 0, 'y': 0, 'w': 1.0}]
    (folder / 'edit.json').write_text(json.dumps(edit), encoding='utf-8')
    card = check.title_contrast_item(folder, folder / 'dark.mp4', folder / 'fresh-dark')
    record('check: a white title over a pale picture is named with its time; over a dark one it passes; a card is '
           'not measured',
           states['pale']['state'] == 'look' and '0:01.00' in states['pale']['detail']
           and states['dark']['state'] == 'pass' and card['state'] == 'skip', str((states, card)))
    check_title_suggestion(record, check, folder, states['pale'])


def check_title_suggestion(record, check, folder, low):
    """The low title's suggested colour and black plate each pass when rendered over the same pale picture."""
    from PIL import Image
    import re
    found = re.search(r'colour (#[0-9a-f]{6}) \(([\d.]+):1\) or a black plate at (\d+)% behind the letters',
                      low.get('detail', ''))
    if not found:
        record('check: a low title names a colour and a plate that pass, and each does when rendered', False,
               low.get('detail', ''))
        return
    colour, plate = found.group(1), int(found.group(3))
    rgb = tuple(int(colour[index:index + 2], 16) for index in (1, 3, 5))
    title = Image.open(folder / 'titles' / 'title-01.png').convert('RGBA')
    pixels = [(rgb + (255,)) if pixel[3] >= 240 else pixel for pixel in title.getdata()]
    recoloured = Image.new('RGBA', title.size)
    recoloured.putdata(pixels)
    recoloured.save(folder / 'titles' / 'title-03.png')
    edit = {'sources': {'title-01': {'file': 'titles/title-01.png'}, 'title-03': {'file': 'titles/title-03.png'}},
            'overlays': [{'kind': 'image', 'src': 'title-03', 'from': 0.5, 'to': 1.5, 'x': 0, 'y': 0, 'w': 1.0}]}
    (folder / 'edit.json').write_text(json.dumps(edit), encoding='utf-8')
    runs = {'colour': ('title-03', '[0:v][1:v]overlay'),
            'plate': ('title-01', f'[0:v]drawbox=x=40:y=20:w=240:h=70:color=black@{plate / 100:.2f}:t=fill[p];'
                                  '[p][1:v]overlay')}
    after = {}
    for name, (src, graph) in runs.items():
        edit['overlays'][0]['src'] = src
        (folder / 'edit.json').write_text(json.dumps(edit), encoding='utf-8')
        video = folder / f'suggested-{name}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0xF0EAD6:s=320x180:r=10:d=2',
                        '-i', str(folder / 'titles' / f'{src}.png'), '-filter_complex', graph,
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
        fresh = folder / f'fresh-suggested-{name}'
        fresh.mkdir(exist_ok=True)
        after[name] = check.title_contrast_item(folder, video, fresh)
    record('check: a low title names a colour and a plate that pass, and each does when rendered',
           all(entry['state'] == 'pass' for entry in after.values()) and 0 < plate < 100
           and rgb[0] == rgb[1] == rgb[2] and float(found.group(2)) < 4.5, f'{low["detail"]} -> {after}')


def check_first_frame(tool, record, j):
    """Frame 0 black, or one colour, is a look with the time the picture first shows something; a picture from frame
    0 passes; a designed fade in from the start is named as the cause; check.py --file reports it."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_first_frame', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    folder = Path(j('first-frame'))
    folder.mkdir(parents=True, exist_ok=True)
    picture = 'testsrc2=s=160x90:r=25:d=1.5'
    graphs = {'black': f'color=c=black:s=160x90:r=25:d=0.48[a];{picture}[b];[a][b]concat=n=2:v=1',
              'blue': f'color=c=0x3366cc:s=160x90:r=25:d=0.4[a];{picture}[b];[a][b]concat=n=2:v=1',
              'picture': picture,
              'fade': f'{picture},fade=t=in:st=0:d=0.5'}
    states = {}
    for name, graph in graphs.items():
        video = folder / f'{name}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-filter_complex', graph + '[v]', '-map', '[v]',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
        states[name] = check.first_frame_item(video)
    designed = check.first_frame_item(folder / 'fade.mp4', {'designed': [{'kind': 'fade', 'start': 0.0, 'end': 0.5}]})
    record('check: a black first frame is a look with the time the picture first shows something',
           states['black']['state'] == 'look' and states['black']['label'] == 'First frame is black'
           and '0:00.48 (frame 12)' in states['black']['detail'] and states['black']['at'] == 0.0, str(states['black']))
    record('check: a first frame of one colour names the colour; a picture from frame 0 passes',
           states['blue']['state'] == 'look' and 'single colour (#3' in states['blue']['label']
           and '0:00.40' in states['blue']['detail'] and states['picture']['state'] == 'pass',
           str((states['blue'], states['picture'])))
    record('check: a designed fade in from black is named as the cause of the empty first frame',
           states['fade']['state'] == 'look' and 'designed fade in' not in states['fade']['detail']
           and designed['state'] == 'look'
           and 'the cause is the designed fade in (0:00.00-0:00.50)' in designed['detail'],
           str((states['fade'], designed)))
    code, output = tool('check.py', '--file', folder / 'black.mp4', '--spec', '160x90@25')
    record('check: check.py --file reports an empty first frame', code == 1 and 'First frame is black' in output,
           output[-800:])


def check_word_counts(record):
    """A summary counts flagged captions and their words apart (an editor's report read '8 caption words' for eight
    captions holding nine words)."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_word_counts', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    rows = [{'rule': 'caption words not in the dialogue', 'cue': n, 'words': ['um', 'so'] if n == 3 else ['um']}
            for n in range(1, 9)]
    speech = [{'rule': 'speech with no caption', 'start': 2.0, 'words': ['danger', 'ahead']}]
    plain = [{'rule': 'cps', 'cue': 1}, {'rule': 'cps', 'cue': 2}, {'rule': 'gap', 'cue': 2}]
    found = (check.counted(rows), check.counted(speech), check.counted(plain))
    record('check: a summary counts flagged captions and their words separately',
           found == ('caption words not in the dialogue: 8 captions, 9 words',
                     'speech with no caption: 1 place, 2 words', '2 cps, 1 gap'), str(found))


def check_declaration_forwarding(tool, record, j):
    """Only the near-empty scanner receives the designed low-detail ranges."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_declarations', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    calls = []

    def fake_report(name, args, out):
        calls.append((name, args))
        if name == 'blank_scan.py':
            return {'runs': [{'start_s': .2, 'end_s': .4, 'declared': True}]}, ''
        return {'flagged': [], 'busiest_general': {}, 'busiest_red': {}}, ''

    check.run_report = fake_report
    items = check.scan_items('video.mp4', Path(j('declarations')), '0.000-0.500,2.000-3.000')
    blank = next(args for name, args in calls if name == 'blank_scan.py')
    flash = next(args for name, args in calls if name == 'flash_scan.py')
    record('check: near-empty scan receives declared ranges and flash scan still sees them',
           '--ignore' in blank and blank[blank.index('--ignore') + 1] == '0.000-0.500,2.000-3.000'
           and '--ignore' not in flash and next(row for row in items if row['id'] == 'blank')['state'] == 'pass',
           str(calls))


# ----------------------------------------------------------------------------------------------- proof of each check

SPOKEN = 'We built the tool ourselves in six weeks.'
SPEAK_SCRIPT = r"""
param([string]$Text, [string]$Out)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = -1
$s.SetOutputToWaveFile($Out)
$s.Speak($Text)
$s.SetOutputToNull()
"""


def write_lines(project, folder, words, film_version='v001'):
    """A version's lines.json: one spoken line with these (text, start, end) words and a picture line whose
    description must never count as speech."""
    kept = [{'id': f'int_01-w{number:06d}', 'text': text, 'start': start, 'end': end}
            for number, (text, start, end) in enumerate(words, 1)]
    end = max((word['end'] for word in kept), default=0.0)
    lines = [{'line': 6, 'section': '', 'kind': 'spoken', 'source': 'int_01', 'start': 0.0, 'end': end,
              'words': kept},
             {'line': 7, 'section': '', 'kind': 'picture', 'source': 'broll_01', 'start': end, 'end': end + 1.0,
              'text': 'Crew unloading the van'}]
    project.save_json(folder / 'lines.json', {'version': 1, 'film_version': film_version, 'duration_s': end + 1.0,
                                              'lines': lines})


def make_version(project, root, captions, words=None, audio=None):
    """A project with one version ready to check: preview.mp4 (a tone, or the given audio), captions.srt and, with
    words, lines.json."""
    root = project.init(Path(root), 'Proof case')
    folder = root / 'cuts' / 'v001'
    folder.mkdir(parents=True, exist_ok=True)
    if audio:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-i',
                        str(audio), '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-bsf:v', TAGS,
                        '-c:a', 'aac', '-movflags', '+faststart', str(folder / 'preview.mp4')], check=True)
    else:
        make_video(folder / 'preview.mp4', 'testsrc2=s=320x180:r=30')
    project.save_json(folder / 'manifest.json', {'version': 'v001', 'parent': None, 'size': [320, 180],
                                                 'fps': '30'})
    (folder / 'film.md').write_text('---\ntitle: Proof case\nsize: 320x180\nfps: 30\n---\n', encoding='utf-8')
    if captions is not None:
        (folder / 'captions.srt').write_text(captions, encoding='utf-8')
    if words is not None:
        write_lines(project, folder, words)
    project.set_current(root, 'v001')
    return root, folder


def read_checks(folder, name='checks.json'):
    """checks.json as a map from id to item ({} when it was not written)."""
    path = Path(folder) / name
    if not path.is_file():
        return {}
    return {entry['id']: entry for entry in json.loads(path.read_text(encoding='utf-8'))['items']}


def copy_scripts(scripts_dir, destination):
    """A private copy of the scripts folder, so a case can break one scanner without touching the real one."""
    destination = Path(destination)
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(scripts_dir, destination, ignore=shutil.ignore_patterns('selftest_cases', '__pycache__',
                                                                            'testpages', '*.mjs'))
    return destination


def run_copy(folder, script, *args):
    """Run a script from a private copy: (exit code, combined output)."""
    result = subprocess.run([sys.executable, '-I', str(Path(folder) / script), *map(str, args)], capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    return result.returncode, result.stdout + result.stderr


def load_module(scripts_dir, name):
    """A script loaded as a module, or (None, the error) when it cannot load."""
    try:
        spec = importlib.util.spec_from_file_location('lf_proof_' + name, os.path.join(scripts_dir, name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, ''
    except Exception as error:  # a broken script is a failed case, reported with its error
        return None, repr(error)


def speech_ready():
    """Why the real-speech case cannot run here ('' when it can): faster-whisper, a cached small model, and Windows
    speech synthesis for the synthetic voice."""
    if importlib.util.find_spec('faster_whisper') is None:
        return 'faster-whisper is not installed (setup.py --install transcription)'
    if os.name != 'nt' or not (shutil.which('powershell') or shutil.which('powershell.exe')):
        return 'the synthetic voice needs Windows speech synthesis (System.Speech)'
    try:
        from faster_whisper.utils import download_model
        download_model('small', local_files_only=True)
    except Exception:  # not cached: the case never downloads weights
        return 'the faster-whisper small model is not downloaded'
    return ''


def speak(folder, text):
    """A WAV of `text` from Windows speech synthesis, or None."""
    shell = shutil.which('powershell') or shutil.which('powershell.exe')
    Path(folder).mkdir(parents=True, exist_ok=True)
    script, wav = Path(folder) / 'speak.ps1', Path(folder) / 'speech.wav'
    script.write_text(SPEAK_SCRIPT, encoding='utf-8')
    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Text', text,
                             '-Out', str(wav)], capture_output=True, text=True, timeout=120)
    return wav if result.returncode == 0 and wav.is_file() else None


def run_check_proof_cases(tool, record, j, scripts_dir):
    """Each check proves it ran now: no reused reports, captions split by what they were compared with, a true peak
    that was not measured is not run, and the speech check runs on the rendered audio or says how to enable it."""
    spec = importlib.util.spec_from_file_location('lf_project_proof', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)

    copy = copy_scripts(scripts_dir, j('check-copy'))
    root, folder = make_version(project, j('check-stale'), None)
    run_copy(copy, 'check.py', root)
    first = read_checks(folder)
    (copy / 'flash_scan.py').write_text('import sys\nprint("Traceback (most recent call last):\\n'
                                        'ModuleNotFoundError: No module named \'numpy\'", file=sys.stderr)\n'
                                        'sys.exit(1)\n', encoding='utf-8')
    code, output = run_copy(copy, 'check.py', root)
    flash = read_checks(folder).get('flash', {})
    record('check: a scanner that crashes after an earlier pass is not run, says how to fix it, and leaves no old '
           'report in qa', first.get('flash', {}).get('state') == 'pass' and flash.get('state') == 'skip'
           and 'numpy is missing from Python' in flash.get('detail', '')
           and '--install core' in flash.get('detail', '') and not (folder / 'qa' / 'flash_scan.json').exists(),
           str(flash) + ' ' + output[-300:])

    tone, tone_folder = make_version(project, j('check-unspoken'),
                                     '1\n00:00:00,500 --> 00:00:02,500\nThis was never spoken\n')
    sidecar_words = [{'text': text, 'start': 0.5 + 0.5 * number, 'end': 0.9 + 0.5 * number}
                     for number, text in enumerate('This was never spoken'.split())]
    project.save_json(tone_folder / 'captions.json', {'cues': [{'start': 0.5, 'end': 2.5, 'text': 'This was never '
                                                                'spoken', 'words': sidecar_words}]})
    code, output = tool('check.py', tone)
    found = read_checks(tone_folder)
    passed = [key for key in ('captions', 'captions_edit', 'captions_speech')
              if found.get(key, {}).get('state') == 'pass']
    record('check: captions over a tone never pass as matching words: no edit-time words is not run, and the '
           'speech check does not pass', not passed and found.get('captions_edit', {}).get('state') == 'skip'
           and found.get('captions_speech', {}).get('state') in ('skip', 'look')
           and found.get('captions_rules', {}).get('state') == 'pass',
           str({key: (entry['state'], entry['detail'][:80]) for key, entry in found.items()}) + output[-200:])

    stale, stale_folder = make_version(project, j('check-stale-caption'),
                                       '1\n00:00:00,500 --> 00:00:02,500\nHello there\n\n'
                                       '2\n00:00:02,600 --> 00:00:03,400\nCrew unloading\n',
                                       [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    code, output = tool('check.py', stale, '--no-speech')
    found = read_checks(stale_folder)
    edit = found.get('captions_edit', {})
    record('check: a caption over words the edit cut fails "follow the edit"; a picture description is not speech',
           code == 1 and edit.get('state') == 'fail' and 'edit' in edit.get('label', '').lower()
           and found.get('captions_speech', {}).get('state') == 'skip', str(edit) + output[-200:])

    copy_speech = copy_scripts(scripts_dir, j('check-copy-speech'))
    (copy_speech / 'transcribe.py').write_text('import sys\nprint("cannot run: No module named \'faster_whisper\'",'
                                               ' file=sys.stderr)\nsys.exit(2)\n', encoding='utf-8')
    hello, hello_folder = make_version(project, j('check-no-engine'),
                                       '1\n00:00:00,500 --> 00:00:02,500\nHello there\n',
                                       [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    code, output = run_copy(copy_speech, 'check.py', hello)
    speech = read_checks(hello_folder).get('captions_speech', {})
    record('check: without faster-whisper the speech check is not run and gives the install line',
           speech.get('state') == 'skip' and '--install transcription' in speech.get('detail', ''),
           str(speech) + output[-200:])

    module, error = load_module(scripts_dir, 'check')
    failed_lossy = {'loudness': {'integrated_lufs': -14.0, 'true_peak_dbtp': -2.0},
                    'lossy_reencode': {'error': 'Unknown encoder aac'},
                    'checks': {'true_peak_after_lossy_reencode': {'pass': False, 'expected': '<= 0.0 dBTP',
                                                                  'actual': None}}}
    try:
        items = {entry['id']: entry for entry in module.loudness_items(failed_lossy, -14.0, True, True)}
        hot_original = dict(failed_lossy, loudness={'integrated_lufs': -14.0, 'true_peak_dbtp': -0.5})
        hot = {entry['id']: entry for entry in module.loudness_items(hot_original, -14.0, True, True)}
        measured = dict(failed_lossy, checks={'true_peak_after_lossy_reencode': {'actual': -3.2}})
        good = {entry['id']: entry for entry in module.loudness_items(measured, -14.0, True, True)}
        peak, hot_peak, good_peak = items['true_peak'], hot['true_peak'], good['true_peak']
        ok = (peak['state'] == 'skip' and 'Unknown encoder aac' in peak['detail']
              and 'dBTP after' not in peak['label'] and items['loudness']['state'] == 'pass'
              and hot_peak['state'] == 'fail' and 'before' in hot_peak['label'] and good_peak['state'] == 'pass'
              and 'after' in good_peak['label'])
        detail = str((peak, hot_peak, good_peak))
    except Exception as problem:  # the function is missing or broken: a failed case
        ok, detail = False, repr(problem) + ' ' + error
    record('check: a true peak not measured after re-encode is not run (or fails on the original), never shown as '
           're-encoded', ok, detail)

    empty = project.init(Path(j('check-no-version')), 'Empty')
    code, output = tool('check.py', empty)
    help_code, help_text = tool('cut.py', '--help')
    record('check: with nothing rendered it names the real command to render', code == 2 and 'cut.py render' in output
           and help_code == 0 and 'render' in help_text and 'diff' in help_text, output[-200:])

    reason = speech_ready()
    wav = None if reason else speak(j('check-speech'), SPOKEN)
    if reason or wav is None:
        print('SKIP  check: captions against a transcript of real speech: ' + (reason or 'speech synthesis failed'),
              flush=True)
        return
    said, said_folder = make_version(project, j('check-said'), '1\n00:00:00,000 --> 00:00:03,500\n' + SPOKEN + '\n',
                                     audio=wav)
    code, output = tool('check.py', said)
    match = read_checks(said_folder).get('captions_speech', {})
    wrong, wrong_folder = make_version(project, j('check-unsaid'), '1\n00:00:00,000 --> 00:00:03,500\n'
                                       'We sold the house ourselves in nine weeks.\n', audio=wav)
    code, output = tool('check.py', wrong)
    differ = read_checks(wrong_folder).get('captions_speech', {})
    record('check: captions are compared with a transcript of the rendered audio: matching words pass, unsaid words '
           'are a look', match.get('state') == 'pass' and 'speech' in match.get('label', '').lower()
           and differ.get('state') == 'look', str(match) + ' ' + str(differ) + output[-200:])


# ----------------------------------------------------------------------------------------------- speech coverage

def speech_with(scripts_dir, folder, captions, rows):
    """check.py's speech item with a controlled transcript in place of faster-whisper (the caption comparison itself
    is real): the item, or an error item when check.py cannot be driven this way."""
    module, error = load_module(scripts_dir, 'check')
    if module is None:
        return {'state': 'error', 'label': '', 'detail': error}
    original = module.run_script

    def transcribe(script, *args):
        if script != 'transcribe.py':
            return original(script, *args)
        values = [str(value) for value in args]
        Path(values[values.index('--out') + 1]).write_text(json.dumps(
            {'version': 1, 'engine': 'faster-whisper small', 'words': rows}), encoding='utf-8')
        return 0, ''

    module.run_script = transcribe
    module.speech_engine_missing = lambda: ''
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    srt = folder / 'captions.srt'
    srt.write_text(captions, encoding='utf-8')
    try:
        return module.speech_item(folder / 'preview.mp4', srt, folder, 'small', 'en')
    except Exception as problem:  # a broken item is a failed case, reported with its error
        return {'state': 'error', 'label': '', 'detail': repr(problem)}


def run_check_coverage_cases(tool, record, j, scripts_dir):
    """'Captions match the speech' only after every word heard has been checked against the whole caption timeline;
    a changed sign is a difference; kept words with no caption are a look in 'follow the edit'."""
    spec = importlib.util.spec_from_file_location('lf_project_coverage', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    one = '1\n00:00:00,000 --> 00:00:01,500\n'
    left_out = speech_with(scripts_dir, j('check-cover-omitted'), one + 'Hello there\n', [
        {'text': 'Hello', 'start': 0.1, 'end': 0.4}, {'text': 'there', 'start': 0.45, 'end': 0.8},
        {'text': 'danger', 'start': 2.3, 'end': 2.8}])
    complete = speech_with(scripts_dir, j('check-cover-complete'), one + 'Hello there\n', [
        {'text': 'Hello', 'start': 0.1, 'end': 0.4}, {'text': 'there', 'start': 0.45, 'end': 0.8}])
    record('check: speech the captions leave out is a look, never "match the speech"; a full match says it checked '
           'every word', left_out.get('state') == 'look' and 'danger' in left_out.get('detail', '')
           and complete.get('state') == 'pass' and 'every one of the 2 words' in complete.get('detail', ''),
           str(left_out) + ' ' + str(complete))
    sign = speech_with(scripts_dir, j('check-cover-sign'), one + 'It is -10\n', [
        {'text': 'It', 'start': 0.1, 'end': 0.25}, {'text': 'is', 'start': 0.3, 'end': 0.45},
        {'text': '10', 'start': 0.5, 'end': 1.1}])
    record('check: a caption that says -10 over speech that says 10 differs from the speech',
           sign.get('state') == 'look', str(sign))

    root, folder = make_version(project, j('check-cover-edit'), '1\n00:00:00,500 --> 00:00:02,400\nHello there\n',
                                [('Hello', 0.5, 1.0), ('there', 1.1, 2.0), ('again', 2.6, 2.95)])
    code, output = tool('check.py', root, '--no-speech')
    edit = read_checks(folder).get('captions_edit', {})
    record('check: a kept word that no caption shows is a look in "follow the edit", named with its time',
           code == 1 and edit.get('state') == 'look' and 'again' in edit.get('detail', '')
           and isinstance(edit.get('at'), (int, float)), str(edit) + output[-200:])

    reason = speech_ready()
    wav = None if reason else speak(j('check-cover-speech'), SPOKEN)
    if reason or wav is None:
        print('SKIP  check: captions that leave out real speech: ' + (reason or 'speech synthesis failed'), flush=True)
        return
    short, short_folder = make_version(project, j('check-cover-short'), '1\n00:00:00,000 --> 00:00:00,500\nWe built\n',
                                       audio=wav)
    code, output = tool('check.py', short)
    speech = read_checks(short_folder).get('captions_speech', {})
    record('check: captions that leave out most of the real speech are a look, not "match the speech"',
           speech.get('state') == 'look' and 'no caption' in speech.get('detail', ''), str(speech) + output[-200:])
def check_technical_findings(tool, record, j):
    """Known answers for the technical scorecard, including inconclusive inputs."""
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_technical', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    peaks = check.true_peak_item({'checks': {'true_peak_after_lossy_reencode': {'actual': -1.3}},
                                  'loudness': {'true_peak_dbtp': 0.2}})
    record('check: a final whose own true peak is over -1 dBTP fails even when a re-encode measures lower',
           peaks['state'] == 'fail' and '0.2' in peaks['label'], str(peaks))
    cases = [
        ('mono', 'mono', 'fail'),
        ('bars', 'bars', 'look'),
        ('interlaced', 'interlace', 'look'),
        # Measured on real files: the slow pan is interlaced b-roll most frames of which idet could not decide; the
        # tally case is progressive film detail its running tally called interlaced; mixed orders cannot be told
        # from clips of different field orders, so they ask for a look.
        ('interlaced slow pan', 'interlace', 'look'),
        ('interlace tally only', 'interlace', 'skip'),
        ('interlace mixed orders', 'interlace', 'look'),
        ('freeze', 'freeze', 'look'),
        ('range', 'color_range', 'look'),
        ('dc', 'audio_integrity', 'look'),
        ('clip', 'audio_integrity', 'fail'),
        ('clip in a preview', 'audio_integrity', 'look'),
    ]
    for name, key, expected in cases:
        if not hasattr(check, 'technical_items'):
            record('check: technical ' + name, False, 'no technical check is emitted')
            continue
        fixture = {
            'video': {'color_range': 'tv', 'field_order': 'progressive'},
            'audio': [{'channels': 2}],
            'mono_fold_down': {'drop_lu': 0},
            'technical': {'crop': {'width': 160, 'height': 90, 'crop': [160, 90, 0, 0], 'samples': 10},
                          'idet': {'tff': 0, 'bff': 0, 'progressive': 90, 'undetermined': 0},
                          'frozen': [], 'range': {'samples': 10, 'max_brng': 0},
                          'audio': [{'dc_offset': 0, 'peak_dbfs': -3}]},
        }
        if name == 'mono':
            fixture['mono_fold_down']['drop_lu'] = 40
        elif name == 'bars':
            fixture['technical']['crop']['crop'] = [160, 60, 0, 15]
            fixture['technical']['crop']['bars_confirmed'] = True
            fixture['technical']['crop']['verification'] = 'uniform edges across shots'
        elif name == 'interlaced':
            fixture['technical']['idet'] = {'tff': 90, 'bff': 0, 'progressive': 0, 'undetermined': 0}
        elif name == 'interlaced slow pan':
            fixture['technical']['idet'] = {'tff': 167, 'bff': 0, 'progressive': 0, 'undetermined': 72,
                                            'single': {'tff': 44, 'bff': 0, 'progressive': 0, 'undetermined': 195}}
        elif name == 'interlace tally only':
            fixture['technical']['idet'] = {'tff': 14, 'bff': 129, 'progressive': 0, 'undetermined': 2,
                                            'single': {'tff': 1, 'bff': 3, 'progressive': 2, 'undetermined': 139}}
        elif name == 'interlace mixed orders':
            fixture['technical']['idet'] = {'tff': 49, 'bff': 30, 'progressive': 11, 'undetermined': 0,
                                            'single': {'tff': 46, 'bff': 33, 'progressive': 11, 'undetermined': 0}}
        elif name == 'freeze':
            fixture['technical']['frozen'] = [[1, 3]]
        elif name == 'range':
            fixture['technical']['range']['max_brng'] = .1
        elif name == 'dc':
            fixture['technical']['audio'][0]['dc_offset'] = .05
        else:
            fixture['technical']['audio'][0]['peak_dbfs'] = 0.1
        found = {row['id']: row for row in check.technical_items(fixture, {}, final=name != 'clip in a preview')}
        row = found.get(key, {})
        record('check: technical ' + name, row.get('state') == expected, str(row))


def check_technical_media(tool, record, j):
    """Decode synthetic pixels and sound; no model, encoder or network is needed."""
    import wave
    import numpy as np
    scripts = Path(__file__).resolve().parent.parent
    modules = {}
    for name in ('qc_file', 'check'):
        spec = importlib.util.spec_from_file_location('case_media_' + name, scripts / (name + '.py'))
        modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modules[name])
    qc, check = modules['qc_file'], modules['check']
    width, height, rate = 160, 90, 10
    x = np.arange(width)[None, :]
    measurements = {}
    for kind in ('bars', 'interlace', 'freeze', 'range'):
        path = Path(j('technical-' + kind + '.y4m'))
        with path.open('wb') as handle:
            field = 'It' if kind == 'interlace' else 'Ip'
            header = f'YUV4MPEG2 W{width} H{height} F{rate}:1 {field} A1:1 C420jpeg\n'
            handle.write(header.encode('ascii'))
            for frame in range(50):
                if kind == 'interlace':
                    top = np.where((x + frame * 5) % 60 < 30, 220, 32)
                    bottom = np.where((x + frame * 5 + 8) % 60 < 30, 220, 32)
                    pixels = np.tile(top.astype('uint8'), (height, 1))
                    pixels[1::2] = np.tile(bottom.astype('uint8'), (height // 2, 1))
                elif kind == 'freeze':
                    pixels = np.tile(np.where((x + min(frame, 15) * 3) % 70 < 35, 200, 40), (height, 1))
                elif kind == 'range':
                    pixels = np.tile(np.where((x + frame) % 80 < 40, 5, 250), (height, 1))
                else:
                    pixels = np.tile(45 + ((x + frame * 3) % 80) * 2, (height, 1))
                    if frame >= 25:
                        pixels = 250 - pixels
                    pixels[:15] = 16
                    pixels[-15:] = 16
                handle.write(b'FRAME\n')
                handle.write(pixels.astype('uint8').tobytes())
                handle.write(bytes([128]) * (width * height // 2))
        measurements[kind] = qc.technical_measurements('ffmpeg', str(path), False, width, height, 5.0)
    report = {'video': {'color_range': 'tv'}, 'audio': []}
    for kind, key in (('bars', 'bars'), ('interlace', 'interlace'), ('freeze', 'freeze'),
                      ('range', 'color_range')):
        report['technical'] = measurements[kind]
        found = {row['id']: row for row in check.technical_items(report, {})}
        record('check: decoded synthetic ' + kind, found[key]['state'] == 'look', str(found[key]))
    report['technical'] = measurements['freeze']
    found = {row['id']: row for row in check.technical_items(
        report, {'holds': [{'start': 1.5, 'end': 5.0}]})}
    record('check: a declared synthetic hold is excluded from freeze prompts',
           found['freeze']['state'] == 'pass', str(found['freeze']))
    audio = Path(j('technical-phase.wav'))
    samples = np.arange(240000)
    signal = (24000 * np.sin(2 * np.pi * 440 * samples / 48000)).astype('<i2')
    stereo = np.column_stack((signal, -signal)).astype('<i2')
    with wave.open(str(audio), 'wb') as handle:
        handle.setparams((2, 2, 48000, len(samples), 'NONE', 'not compressed'))
        handle.writeframes(stereo.tobytes())
    muxed = Path(j('technical-phase.avi'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', j('technical-bars.y4m'), '-i', str(audio),
                    '-map', '0:v', '-map', '1:a', '-c', 'copy', str(muxed)], check=True)
    full = qc.loudness('ffmpeg', str(muxed)).get('integrated_lufs')
    mono = qc.loudness('ffmpeg', str(muxed), pre_filter=
                       'pan=stereo|c0=0.5*c0+0.5*c1|c1=0.5*c0+0.5*c1').get('integrated_lufs')
    measured = qc.technical_measurements('ffmpeg', str(muxed), True, width, height, 5.0)
    report = {'video': {}, 'audio': [{'channels': 2}], 'technical': measured,
              'mono_fold_down': {'drop_lu': full - mono if full is not None and mono is not None else None}}
    found = {row['id']: row for row in check.technical_items(report, {})}
    record('check: decoded opposite-phase stereo fails mono compatibility',
           found['mono']['state'] == 'fail', str(found['mono']))
    record('check: decoded sound statistics reach the scorecard',
           found['audio_integrity']['state'] == 'pass', str(found['audio_integrity']))
    for kind in ('dc', 'clip'):
        shifted = np.column_stack((signal + 5000, signal + 5000)).astype('<i2')
        if kind == 'clip':
            shifted[1000, 0] = -32768
        audio = Path(j('technical-' + kind + '.wav'))
        with wave.open(str(audio), 'wb') as handle:
            handle.setparams((2, 2, 48000, len(samples), 'NONE', 'not compressed'))
            handle.writeframes(shifted.tobytes())
        muxed = Path(j('technical-' + kind + '.avi'))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', j('technical-bars.y4m'), '-i', str(audio),
                        '-map', '0:v', '-map', '1:a', '-c', 'copy', str(muxed)], check=True)
        report['technical'] = qc.technical_measurements('ffmpeg', str(muxed), True, width, height, 5.0)
        found = {row['id']: row for row in check.technical_items(report, {})}
        expected = 'look' if kind == 'dc' else 'fail'
        record('check: decoded synthetic ' + kind, found['audio_integrity']['state'] == expected,
               str(found['audio_integrity']))


def check_vad_disclosure(tool, record, j):
    """A check using a no-VAD transcript does not hide that limitation."""
    from unittest.mock import patch
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_check_vad', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    folder = Path(j('check-vad'))
    folder.mkdir(parents=True, exist_ok=True)

    def fake_transcribe(name, *args):
        words = Path(args[args.index('--out') + 1])
        words.write_text(json.dumps({'voice_detection': 'off', 'words': []}), encoding='utf-8')
        return 0, 'voice detection off'

    with patch.object(check.importlib.util, 'find_spec', return_value=True), \
            patch.object(check, 'run_script', side_effect=fake_transcribe), \
            patch.object(check, 'run_report', return_value=({'findings': [], 'review': [], 'cues': 1}, None)):
        result = check.speech_item('video.mp4', 'captions.srt', folder, 'base', None)
    record('check: transcript comparison discloses when voice detection was off',
           'voice detection was off' in result['detail'] and 'onnxruntime' in result['detail'], str(result))


def check_craft2_units(record, scripts_dir):
    """Known boundaries and untargeted loudness reporting."""
    check = load_module(scripts_dir, 'check')[0]
    flash = load_module(scripts_dir, 'flash_scan')[0]
    cases = [(-5, 'look'), (-40, 'look'), (-16, 'pass')]
    got = [check.loudness_items({'loudness': {'integrated_lufs': value}}, None, False, True)[0]['state']
           for value, _ in cases]
    record('check: extreme untargeted loudness asks for a look', got == [expected for _, expected in cases], str(got))
    clean_flash = check.flash_item({'flagged': []})
    record('check: a clear flash screen is not described as WCAG certification',
           clean_flash['state'] == 'pass' and 'candidate' in clean_flash['label']
           and 'not WCAG certification' in clean_flash['detail'], str(clean_flash))
    red_flash = check.flash_item({'flagged': [{'general_at_s': 1, 'general_max_per_s': 5,
                                             'red_at_s': 3.2, 'red_max_per_s': 8}]})
    record('check: red-only flash retains its location and remains a safety finding',
           red_flash['state'] == 'fail' and red_flash['at'] == 3.2
           and 'Potential' in red_flash['label'], str(red_flash))
    pattern = check.flash_item({'flagged': [{'general_at_s': 5.9, 'general_max_per_s': 30, 'classic_max_per_s': 2,
                                             'pattern_max_per_s': 30, 'red_at_s': None, 'red_max_per_s': 0}]})
    classic = check.flash_item({'flagged': [{'general_at_s': 1.0, 'general_max_per_s': 10, 'classic_max_per_s': 10,
                                             'pattern_max_per_s': 10, 'red_at_s': None, 'red_max_per_s': 0}]})
    record('check: a pattern-only detection is a look a person decides; a percentile flash still fails',
           pattern['state'] == 'look' and pattern['at'] == 5.9 and 'WCAG 2.3.1' in pattern['detail']
           and classic['state'] == 'fail', str(pattern) + str(classic))
    mono = check.mono_item({'audio': [{'channels': 2}], 'mono_fold_down': {'drop_lu': 3.3}})
    record('check: ordinary wide stereo does not prompt for mono', mono['state'] == 'pass', str(mono))
    mono_cases = [(-.2, 'pass', '0.2 LU louder'), (0, 'pass', 'unchanged'),
                  (4.5, 'pass', '4.5 LU quieter'), (4.6, 'look', '4.6 LU quieter'),
                  (20, 'fail', '20.0 LU quieter')]
    for drop, state, label in mono_cases:
        result = check.mono_item({'audio': [{'channels': 2}], 'mono_fold_down': {'drop_lu': drop}})
        record(f'check: mono change {drop:g} has an accurate label and state',
               result['state'] == state and label in result['label'], str(result))
    crop = {'width': 640, 'height': 360, 'crop': [200, 300, 220, 60], 'samples': 6, 'matching': 6,
            'bars_confirmed': False, 'verification': 'no shot change'}
    bars = check.bars_item({'crop': crop}, False)
    record('check: dark backdrop is not presented as persistent bars', bars['state'] != 'look', str(bars))
    still = check.undeclared_freezes([[0, 2]], {'designed': [{'kind': 'still', 'start': 0, 'end': 2}]})
    record('check: declared still excludes designed freeze', not still, str(still))
    import numpy as np
    detector = flash.GeneralZig()
    for tick, value in ((0, 0), (5, .7), (9, .8), (10, 0)):
        detector.push(tick, np.full((4, 4), value, dtype=np.float32))
    record('check: codec noise does not delay a pattern transition', detector.ends == [5],
           str(detector.ends))
    # A red swing counts once its reversal in the same pixels is resolved (finish); it keeps its first crossing time.
    detector = flash.RedZig()
    for tick, value in ((0, 0), (5, 224), (9, 256), (10, 0)):
        detector.push(tick / 100, np.full((4, 4), value, dtype=np.float32))
    detector.finish()
    record('check: codec noise does not delay a red transition', detector.ends[:1] == [.05],
           str(detector.ends))
    checker = (np.indices((32, 64)).sum(axis=0) % 2).astype(np.float32)
    for rate in (3, 3.1, 5, 10):
        detector = flash.GeneralZig()
        for frame in range(90):
            blend = (1 + math.cos(2 * math.pi * rate * frame / 30)) / 2
            image = checker * blend + (1 - checker) * (1 - blend)
            detector.push(frame / 30, image)
        detector.finish()
        count = flash.busiest_second(detector.ends)[0]
        record(f'check: gradual checker reversals at {rate} Hz', (count > 6) == (rate > 3), str(count))
    pattern = np.concatenate((np.zeros(20), np.ones(20), np.full(60, .25))).astype(np.float32)
    opposite = np.concatenate((np.ones(20), np.zeros(20), np.full(60, .25))).astype(np.float32)
    detector = flash.GeneralZig()
    for index in range(12):
        detector.push(index / 10, pattern if index % 2 else opposite)
    detector.finish()
    record('check: mixed-direction reversals count their combined area', len(detector.ends) > 6,
           str(detector.ends))
    if hasattr(flash, 'unique_translation'):
        rng = np.random.default_rng(99)
        texture = rng.random((36, 64), dtype=np.float32)
        previous = None
        detector = flash.GeneralZig()
        for index in range(30):
            frame = np.roll(texture, index * 3, axis=1)
            motion = flash.unique_translation(previous, frame) if previous is not None else None
            detector.push(index / 30, frame, motion)
            previous = frame
        detector.finish()
        motion_count = flash.busiest_second(detector.ends)[0]
    else:
        motion_count = 99
    record('check: uniquely translating texture is not a flash', motion_count <= 6, str(motion_count))
    texture = np.random.default_rng(12).random((36, 64), dtype=np.float32)
    previous = None
    detector = flash.GeneralZig()
    for index in range(60):
        frame = np.roll(texture, index * 3, axis=1)
        if (index // 3) % 2:
            frame = 1 - frame
        motion = flash.unique_translation(previous, frame) if previous is not None else None
        detector.push(index / 30, frame, motion)
        previous = frame
    detector.finish()
    moving_flash = flash.busiest_second(detector.ends)[0]
    record('check: a flashing image remains flagged while it moves', moving_flash > 6, str(moving_flash))
    # A threshold-sized flashing overlay can stay fixed while its background pans.
    # Motion compensation of the whole window must not carry the overlay away.
    background = np.random.default_rng(67).random((160, 192), dtype=np.float32) * .15
    yy, xx = np.indices((16, 28))
    tiny = ((xx // 2 + yy // 2) % 2).astype(np.float32)
    detector = flash.GeneralZig()
    previous = None
    for index in range(90):
        position = index * 1.25
        whole = int(position)
        fraction = position - whole
        image = ((1 - fraction) * np.roll(background, -whole, axis=0)[:80] +
                 fraction * np.roll(background, -whole - 1, axis=0)[:80]).copy()
        image[31:47, 82:110] = tiny if (index // 3) % 2 == 0 else 1 - tiny
        motion = flash.unique_translation(previous, image) if previous is not None else None
        detector.push(index / 30, image[26:52, 64:128], motion)
        previous = image
    detector.finish()
    count = flash.busiest_second(detector.ends)[0]
    record('check: a small checker flash remains visible over moving texture', count > 6, str(count))
    # A checker that changes phase while moving can have slightly different changed pixels on each swing.
    background = np.random.default_rng(67).random((160, 192), dtype=np.float32) * .15
    yy, xx = np.indices((16, 28))
    checker = ((xx // 4 + yy // 4) % 2).astype(np.float32)
    detector = flash.AreaTransitions()
    previous, previous_phase = None, None
    direct = []
    for index in range(90):
        position = index * .65
        whole = int(position)
        fraction = position - whole
        image = ((1 - fraction) * np.roll(background, -whole, axis=0)[:80] +
                 fraction * np.roll(background, -whole - 1, axis=0)[:80]).copy()
        left = 82 + round(2 * math.sin(index * 2 * math.pi / 90))
        phase = int(index / 30 * 10) % 2
        image[31:47, left:left + 28] = checker if phase == 0 else 1 - checker
        if previous is not None and phase != previous_phase:
            old, new = previous[26:52, 64:128], image[26:52, 64:128]
            changed = (np.abs(old - new) >= .10) & (np.minimum(old, new) < .80)
            if np.count_nonzero(changed) >= .26 * changed.size:
                direct.append(index / 30)
        motion = flash.unique_translation(previous, image) if previous is not None else None
        detector.push(index / 30, image[26:52, 64:128], motion)
        previous, previous_phase = image, phase
    detector.finish()
    observed = flash.busiest_second(detector.ends)[0]
    expected = flash.busiest_second(direct)[0]
    record('check: moving checker flash above the area threshold is detected',
           expected > 6 and observed > 6, f'direct={expected} detector={observed}')
    # A changing flash mask need not repeat an identical set of pixels on every swing.
    for speed in (.35, .65, 1.25):
        rng = np.random.default_rng(123)
        background = rng.random((160, 192), dtype=np.float32) * .15
        pattern = np.zeros((16, 48), dtype=np.float32)
        detector = flash.AreaTransitions()
        previous, previous_phase = None, None
        direct = []
        for index in range(90):
            position = index * speed
            whole = int(position)
            fraction = position - whole
            image = ((1 - fraction) * np.roll(background, -whole, axis=0)[:80] +
                     fraction * np.roll(background, -whole - 1, axis=0)[:80]).copy()
            phase = int(index / 30 * 10)
            if phase != previous_phase:
                selected = np.zeros(pattern.size, dtype=bool)
                selected[rng.choice(pattern.size, 614, replace=False)] = True
                pattern.ravel()[selected] = 1 - pattern.ravel()[selected]
            image[31:47, 72:120] = pattern * .11
            if previous is not None and phase != previous_phase:
                old, new = previous[26:52, 64:128], image[26:52, 64:128]
                changed = (np.abs(old - new) >= .10) & (np.minimum(old, new) < .80)
                if np.count_nonzero(changed) >= .26 * changed.size:
                    direct.append(index / 30)
            motion = flash.unique_translation(previous, image) if previous is not None else None
            detector.push(index / 30, image[26:52, 64:128], motion)
            previous, previous_phase = image, phase
        detector.finish()
        observed = flash.busiest_second(detector.ends)[0]
        expected = flash.busiest_second(direct)[0]
        record(f'check: changing low-contrast flash over moving background {speed:g}',
               expected > 6 and observed > 6, f'direct={expected} detector={observed}')
    yy, xx = np.mgrid[0:108, 0:192]
    periodic = ((xx // 12 + yy // 12) % 2).astype(np.float32)
    periodic[2:8, 2:10] = np.random.default_rng(5).random((6, 8))
    alternate = np.roll(periodic, 12, axis=1)
    detector = flash.GeneralZig()
    previous = None
    for index in range(12):
        frame = periodic if index % 2 else alternate
        motion = flash.unique_translation(previous, frame) if previous is not None else None
        detector.push(index / 10, frame, motion)
        previous = frame
    detector.finish()
    record('check: a periodic reversal with a unique marker remains a flash candidate',
           len(detector.ends) > 6, str(detector.ends))
    transitions = [round(i / 6, 6) for i in range(13)]
    busiest = flash.busiest_second(transitions)
    record('check: exactly three flashes per second stays within the limit', busiest[0] <= 6, str(busiest))


def check_zero_phase_edge(record, j):
    """A hard tone that crosses zero at the last sample is still a hard audio ending."""
    import wave
    import numpy as np
    qc = load_module(Path(__file__).resolve().parent.parent, 'qc_file')[0]
    rate = 48000
    index = np.arange(rate)
    signal = .7 * np.sin(2 * np.pi * 440 * (index - (rate - 1)) / rate)
    path = Path(j('edge-zero-phase.wav'))
    with wave.open(str(path), 'wb') as handle:
        handle.setparams((1, 2, rate, len(signal), 'NONE', 'not compressed'))
        handle.writeframes((signal * 32767).astype('<i2').tobytes())
    result = qc.audio_edges('ffmpeg', str(path), 1)
    record('check: zero-crossing hard audio tail prompts a listen',
           any('ends away' in text for text in result['notes']), str(result))


def check_craft2_pattern_battery(tool, record, j):
    """Flash patterns at the threshold and above, on lossless and lossy encoded pictures."""
    import numpy as np
    width, height, fps, seconds = 192, 108, 30, 3
    yy, xx = np.mgrid[0:height, 0:width]
    rng = np.random.default_rng(104)
    texture = rng.integers(0, 256, (height, width), dtype=np.uint8)
    cases = []
    for rate in (3, 3.1, 5, 10):
        cases.append(('full', 1, rate, 'white', rate > 3))
        cases.append(('full', 1, rate, 'red', rate > 3))
        for cells in (4, 8, 16):
            cases.append(('checker', cells, rate, 'white', rate > 3))
        for cells in (6, 10, 20):
            cases.append(('bars', cells, rate, 'white', rate > 3))
    cases.extend([('area', 15, 5, 'white', False), ('area', 50, 5, 'white', True),
                  ('moving', 1, 0, 'white', False), ('text', 1, 0, 'white', False)])
    root = Path(j('pattern-battery'))
    root.mkdir(parents=True, exist_ok=True)
    for codec in ('ffv1', 'h264'):
        for number, (kind, cells, rate, colour, expected) in enumerate(cases):
            path = root / (f'{codec}-{number:02d}.' + ('mkv' if codec == 'ffv1' else 'mp4'))
            if kind == 'checker':
                pattern = ((xx * cells // width + yy * cells // height) % 2 == 0)
            elif kind == 'bars':
                pattern = (xx * cells // width) % 2 == 0
            elif kind == 'area':
                fraction = cells / 1000
                w = round(width * math.sqrt(fraction))
                h = round(height * math.sqrt(fraction))
                pattern = (abs(xx - width / 2) < w / 2) & (abs(yy - height / 2) < h / 2)
            else:
                pattern = np.ones((height, width), dtype=bool)
            images = []
            for frame in range(fps * seconds):
                if kind == 'moving':
                    grey = np.roll(texture, frame * 4, axis=1)
                    image = np.repeat(grey[:, :, None], 3, axis=2)
                elif kind == 'text':
                    image = np.zeros((height, width, 3), dtype=np.uint8)
                    start = (frame * 3) % (width + 80) - 80
                    for offset in (0, 30, 60):
                        x0, x1 = max(0, start + offset), min(width, start + offset + 16)
                        if x1 > x0:
                            image[35:73, x0:x1] = 255
                else:
                    phase = math.floor(frame / fps * 2 * rate + 1e-9) % 2 == 0
                    mask = pattern if phase else (~pattern if kind in ('checker', 'bars') else
                                                  np.zeros_like(pattern))
                    image = np.zeros((height, width, 3), dtype=np.uint8)
                    image[mask] = (255, 0, 0) if colour == 'red' else (255, 255, 255)
                images.append(image.tobytes())
            encoding = (['-c:v', 'ffv1', '-pix_fmt', 'bgr0'] if codec == 'ffv1' else
                        ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p'])
            command = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s',
                       f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0', *encoding, str(path)]
            encoded = subprocess.run(command, input=b''.join(images), capture_output=True)
            if encoded.returncode:
                record(f'check: {codec} {kind} {cells} {colour} {rate} Hz', False,
                       encoded.stderr.decode(errors='replace')[-300:])
                continue
            report = root / f'{codec}-{number:02d}.json'
            code, output = tool('flash_scan.py', path, '--json', report)
            data = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
            general = data.get('busiest_general', {}).get('transitions_in_1s', 0)
            red = data.get('busiest_red', {}).get('transitions_in_1s', 0)
            right_channel = not expected or (red > 6 if colour == 'red' else general > 6)
            record(f'check: {codec} {kind} {cells} {colour} {rate} Hz',
                   code == (1 if expected else 0) and right_channel,
                   f'expected={expected}, code={code}, general={general}, red={red}; {output[-200:]}')


def check_audio_ends_early(record, j):
    """A soundtrack ending before video still has its own boundary examined."""
    import wave
    import numpy as np
    qc = load_module(Path(__file__).resolve().parent.parent, 'qc_file')[0]
    video, audio, path = (Path(j('edge-early-video.y4m')), Path(j('edge-early-audio.wav')),
                          Path(j('edge-early-audio.avi')))
    width, height, rate = 64, 36, 48000
    frame = bytes([16]) * (width * height) + bytes([128]) * (width * height // 2)
    with video.open('wb') as handle:
        handle.write(f'YUV4MPEG2 W{width} H{height} F25:1 Ip A1:1 C420jpeg\n'.encode('ascii'))
        for _ in range(50):
            handle.write(b'FRAME\n' + frame)
    samples = (22000 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)).astype('<i2')
    with wave.open(str(audio), 'wb') as handle:
        handle.setparams((1, 2, rate, len(samples), 'NONE', 'not compressed'))
        handle.writeframes(samples.tobytes())
    command = ['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-i', str(audio),
               '-map', '0:v', '-map', '1:a', '-c', 'copy', str(path)]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        record('check: audio ending early still has a measured edge', False,
               result.stderr.decode(errors='replace')[-300:])
        return
    decoded_end = qc.loudness('ffmpeg', str(path)).get('decoded_audio_length_s')
    measurement = qc.audio_edges('ffmpeg', str(path), 1, decoded_end)
    record('check: audio ending early still has a measured edge',
           measurement.get('measured') and any('ends away' in text for text in measurement['notes']),
           str(measurement))


def check_craft2_fine_pattern(tool, record, j):
    """A one-source-pixel checkerboard must survive analysis-size reduction."""
    import numpy as np
    width, height, fps = 384, 216, 30
    yy, xx = np.mgrid[0:height, 0:width]
    checker = ((xx + yy) % 2 * 255).astype('uint8')
    first = np.repeat(checker[:, :, None], 3, axis=2).tobytes()
    second = np.repeat((255 - checker)[:, :, None], 3, axis=2).tobytes()
    raw = b''.join(first if (frame // 3) % 2 == 0 else second for frame in range(90))
    for codec in ('ffv1', 'h264'):
        path = Path(j('fine-pattern.' + ('mkv' if codec == 'ffv1' else 'mp4')))
        encoding = (['-c:v', 'ffv1', '-pix_fmt', 'bgr0'] if codec == 'ffv1' else
                    ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p'])
        result = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                 '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0', *encoding, str(path)],
                                input=raw, capture_output=True)
        if result.returncode:
            record('check: fine checkerboard ' + codec, False, result.stderr.decode(errors='replace')[-200:])
            continue
        code, output = tool('flash_scan.py', path)
        record('check: fine checkerboard ' + codec, code == 1, output[-200:])


def check_craft2_red_patterns(tool, record, j):
    """Patterned saturated red at and above three flashes, in both encoded families."""
    import numpy as np
    width, height, fps = 192, 108, 30
    yy, xx = np.mgrid[0:height, 0:width]
    root = Path(j('red-patterns'))
    root.mkdir(parents=True, exist_ok=True)
    for codec in ('ffv1', 'h264'):
        for kind, cells in (('checker', 4), ('bars', 6)):
            if kind == 'checker':
                pattern = (xx * cells // width + yy * cells // height) % 2 == 0
            else:
                pattern = (xx * cells // width) % 2 == 0
            for rate in (3, 3.1):
                images = []
                for frame in range(90):
                    phase = math.floor(frame / fps * 2 * rate + 1e-9) % 2 == 0
                    mask = pattern if phase else ~pattern
                    image = np.zeros((height, width, 3), dtype=np.uint8)
                    image[mask] = (255, 0, 0)
                    images.append(image.tobytes())
                path = root / (f'{codec}-{kind}-{rate}.' + ('mkv' if codec == 'ffv1' else 'mp4'))
                encoding = (['-c:v', 'ffv1', '-pix_fmt', 'bgr0'] if codec == 'ffv1' else
                            ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p'])
                result = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                         '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0', *encoding,
                                         str(path)], input=b''.join(images), capture_output=True)
                name = f'check: {codec} red {kind} {cells} at {rate} Hz'
                if result.returncode:
                    record(name, False, result.stderr.decode(errors='replace')[-300:])
                    continue
                report = path.with_suffix('.json')
                code, output = tool('flash_scan.py', path, '--json', report)
                data = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
                red = data.get('busiest_red', {}).get('transitions_in_1s', 0)
                expected = rate > 3
                record(name, code == (1 if expected else 0) and (red > 6) == expected,
                       f'expected={expected} code={code} red={red}; {output[-200:]}')


def check_craft2_moving_flash_media(tool, record, j):
    """A threshold-area checker flashes while both it and its background move."""
    import numpy as np
    width, height, fps = 192, 80, 30
    rng = np.random.default_rng(67)
    background = rng.random((160, width), dtype=np.float32) * .15
    yy, xx = np.indices((16, 28))
    checker = ((xx // 4 + yy // 4) % 2).astype(np.float32)
    folder = Path(j('moving-flash-media'))
    folder.mkdir(parents=True, exist_ok=True)
    for codec in ('ffv1', 'h264'):
        for rate in (3.1, 5):
            images = []
            for frame in range(90):
                position = frame * .65
                whole, fraction = int(position), position - int(position)
                luminance = ((1 - fraction) * np.roll(background, -whole, axis=0)[:height] +
                             fraction * np.roll(background, -whole - 1, axis=0)[:height]).copy()
                left = 82 + round(2 * math.sin(frame * 2 * math.pi / 90))
                phase = math.floor(frame / fps * 2 * rate + 1e-9) % 2
                luminance[31:47, left:left + 28] = (checker if phase == 0 else 1 - checker) * .20
                rgb = np.where(luminance <= .0031308, 12.92 * luminance,
                               1.055 * np.power(luminance, 1 / 2.4) - .055)
                encoded = np.clip(np.rint(rgb * 255), 0, 255).astype(np.uint8)
                images.append(np.repeat(encoded[:, :, None], 3, axis=2).tobytes())
            path = folder / (f'{codec}-{rate}.' + ('mkv' if codec == 'ffv1' else 'mp4'))
            encoding = (['-c:v', 'ffv1', '-pix_fmt', 'bgr0'] if codec == 'ffv1' else
                        ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p'])
            result = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                                     '-s', f'{width}x{height}', '-r', str(fps), '-i', 'pipe:0', *encoding,
                                     str(path)], input=b''.join(images), capture_output=True)
            name = f'check: {codec} moving threshold-area checker {rate} Hz'
            if result.returncode:
                record(name, False, result.stderr.decode(errors='replace')[-300:])
                continue
            report = path.with_suffix('.json')
            code, output = tool('flash_scan.py', path, '--json', report)
            data = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
            general = data.get('busiest_general', {}).get('transitions_in_1s', 0)
            record(name, code == 1 and general > 6,
                   f'expected=True code={code} general={general}; {output[-200:]}')


# ------------------------------------------------------------------------------- an editor's export, checked as is

NATIVE_WORDS = [('We', 1.2), ('kept', 1.5), ('this', 1.9), ('part', 2.3), ('the', 5.0), ('old', 5.3), ('line', 5.6),
                ('and', 10.4), ('this', 10.8), ('ending', 11.3)]
NATIVE_SRT = ('1\n00:00:00,100 --> 00:00:01,500\nWe kept this part\n\n'
              '2\n00:00:03,000 --> 00:00:05,000\nthe old line\n')


def fcp7_clip(number, start, end, source_in, source_out, extra=''):
    """One dialogue clip of interview.mov at 25 fps: sequence frames start-end from source frames in-out."""
    return (f'<clipitem id="clip-{number}"><name>take {number}</name><enabled>TRUE</enabled><start>{start}</start>'
            f'<end>{end}</end><in>{source_in}</in><out>{source_out}</out><file id="interview"/>{extra}</clipitem>')


def fcp7_timeline(clips, frames):
    """A Final Cut Pro 7 XML sequence at 25 fps whose first audio track holds `clips`; the file is described by a
    disabled clip first, the way Premiere writes a file's details once."""
    described = ('<clipitem id="described"><name>file</name><enabled>FALSE</enabled><start>900</start><end>901</end>'
                 '<in>0</in><out>1</out><file id="interview"><name>interview.mov</name>'
                 '<pathurl>file://localhost/media/interview.mov</pathurl><rate><timebase>25</timebase>'
                 '<ntsc>FALSE</ntsc></rate></file></clipitem>')
    return ('<?xml version="1.0"?><xmeml version="4"><sequence><name>edit</name>'
            f'<duration>{frames}</duration><rate><timebase>25</timebase><ntsc>FALSE</ntsc></rate>'
            '<media><video><track/></video><audio><track>' + described + ''.join(clips)
            + '</track></audio></media></sequence></xmeml>')


def native_export(folder):
    """An editor's revision as delivered: export.mp4 (6 s of picture and tone), the timeline that made it (two clips:
    source 1-4 s, then source 10-13 s), the source transcript and a caption sidecar left from an earlier revision
    (its second caption is a line the timeline no longer uses)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    make_video(folder / 'export.mp4', 'testsrc2=s=320x180:r=25', seconds=6)
    (folder / 'edit.xml').write_text(fcp7_timeline([fcp7_clip(1, 0, 75, 25, 100), fcp7_clip(2, 75, 150, 250, 325)],
                                                   150), encoding='utf-8')
    words = [{'id': f'int_01-w{number:06d}', 'text': text, 'start': start, 'end': start + 0.3}
             for number, (text, start) in enumerate(NATIVE_WORDS, 1)]
    (folder / 'source-words.json').write_text(json.dumps({'sources': [{'id': 'int_01',
                                                                       'media_reference': 'interview.mov',
                                                                       'words': words}]}), encoding='utf-8')
    (folder / 'export.srt').write_text(NATIVE_SRT, encoding='utf-8')
    return folder


def checks_at(path):
    """A checks.json written by check.py --json, or {} when it was not written."""
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def by_id(checks):
    """A checks file's items by id."""
    return {entry['id']: entry for entry in checks.get('items') or []}


def file_sha(path):
    """The SHA-256 of a file."""
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_native_cases(tool, record, j, scripts_dir):
    """check.py --file as an editor's assistant: the delivered sidecar against the timeline's words and a transcript
    of the export, families not assessed said so, inputs and tools recorded and verified, and no report over an
    input."""
    folder = native_export(j('native'))
    export, srt, xml, words = (folder / name for name in ('export.mp4', 'export.srt', 'edit.xml', 'source-words.json'))
    out = folder / 'checks.json'
    code, output = tool('check.py', '--file', export, '--captions', srt, '--timeline', xml, '--source-words', words,
                        '--no-speech', '--json', out)
    checks = checks_at(out)
    found = by_id(checks)
    edit, timeline = found.get('captions_edit', {}), found.get('timeline', {})
    record('native: a caption mismatch against unverified timeline words is a look with its evidence',
           code == 1 and edit.get('state') == 'look' and 'the old line' in edit.get('detail', '')
           and 'edit.xml' in edit.get('detail', '') and found.get('captions_rules', {}).get('state') == 'pass'
           and 'not verified' in edit.get('detail', '') and 'map.py confirm-words' in edit.get('detail', '')
           and timeline.get('state') == 'look' and '2 clips' in timeline.get('label', ''),
           str({key: (row['state'], row['label']) for key, row in found.items()}) + output[-300:])
    inputs = checks.get('inputs') or []
    roles = [row.get('role') for row in inputs]
    by_role = {row.get('role'): row for row in inputs}
    complete = all(isinstance(by_role.get(role, {}).get('sha256'), str)
                   and isinstance(by_role.get(role, {}).get('bytes'), int)
                   for role in ('export', 'captions', 'timeline', 'source_words'))
    tools = checks.get('tools') or {}
    scripts = tools.get('scripts') or {}
    record('native: the result names every input (role, absolute path, SHA-256, bytes) and the tools that made it',
           roles == ['export', 'cold_read', 'captions', 'timeline', 'source_words', 'timeline_media']
           and all(by_role[role].get('sha256') is None and by_role[role].get('bytes') is None
                   for role in ('cold_read', 'timeline_media')) and complete
           and by_role['captions']['path'] == str(srt.resolve())
           and by_role['export']['sha256'] == checks.get('sha256')
           and str(tools.get('ffmpeg', '')).startswith('ffmpeg version') and tools.get('python')
           and tools.get('skill_version') and {'check.py', 'project.py', 'exchange.py', 'captions.py',
                                               'qc_file.py'} <= set(scripts)
           and scripts.get('exchange.py') == file_sha(Path(scripts_dir) / 'exchange.py')
           and tools.get('faster_whisper') is None, str(checks.get('inputs')) + ' ' + str(tools)[:300])

    code, output = tool('check.py', '--verify', out)
    current = code == 0 and output.startswith('current')
    srt.write_text(NATIVE_SRT.replace('the old line', 'the new line'), encoding='utf-8')
    code, changed = tool('check.py', '--verify', out)
    # check.py records resolved paths: on Windows a short (8.3) temporary folder comes back in its long form.
    named = str(srt) in changed or str(srt.resolve()) in changed
    record('native: --verify says current, then names a caption file changed since the check (exit 1)',
           current and code == 1 and 'captions' in changed and named and 'content changed' in changed,
           output[-200:] + ' | ' + changed[-300:])
    srt.write_text(NATIVE_SRT, encoding='utf-8')
    code, output = tool('check.py', '--verify', folder / 'no-such.json')
    legacy = folder / 'legacy-checks.json'
    legacy.write_text(json.dumps({'version': 1, 'items': [], 'summary': {}}), encoding='utf-8')
    legacy_code, legacy_output = tool('check.py', '--verify', legacy)
    record('native: --verify cannot run (exit 2) on a missing file or one written before inputs were recorded',
           code == 2 and legacy_code == 2 and 'records no inputs' in legacy_output, output[-200:] + legacy_output)

    plain_out = folder / 'plain.json'
    code, output = tool('check.py', '--file', export, '--json', plain_out)
    plain = by_id(checks_at(plain_out))
    skips = [row for row in plain.values() if row['state'] == 'skip']
    edited_out = folder / 'plain-captions.json'
    tool('check.py', '--file', export, '--captions', srt, '--no-speech', '--json', edited_out)
    edited = by_id(checks_at(edited_out))
    record('native: a check this run does not assess reads "Not assessed" with how to supply it, never as passed; '
           'a plain file has no timeline row, an export with captions does',
           plain.get('captions', {}).get('state') == 'skip'
           and plain['captions']['label'].startswith('Not assessed')
           and '--captions FILE' in plain['captions'].get('detail', '')
           and 'timeline' not in plain
           and edited.get('timeline', {}).get('label', '').startswith('Not assessed')
           and '--timeline' in edited['timeline'].get('detail', '')
           and all(row['label'].startswith('Not assessed') for row in skips)
           and 'not assessed' in output.splitlines()[-1] and 'not run' not in output.splitlines()[-1],
           str({key: (row['state'], row['label']) for key, row in plain.items()}) + output[-200:]
           + str(edited.get('timeline')))

    delivery = folder / 'delivery.json'
    delivery.write_text(json.dumps({'size': '640x360', 'fps': 25, 'captions_required': False}), encoding='utf-8')
    code, output = tool('check.py', '--file', export, '--delivery', delivery, '--json', folder / 'delivery-a.json')
    first = by_id(checks_at(folder / 'delivery-a.json'))
    delivery.write_text(json.dumps({'captions_required': True}), encoding='utf-8')
    tool('check.py', '--file', export, '--delivery', delivery, '--spec', '320x180@25', '--json',
         folder / 'delivery-b.json')
    second = by_id(checks_at(folder / 'delivery-b.json'))
    delivery.write_text(json.dumps({'size': '320x180', 'loudnes': -16}), encoding='utf-8')
    typo_code, typo = tool('check.py', '--file', export, '--delivery', delivery)
    record('native: delivery settings set the expected spec and whether captions are required; flags override them; '
           'an unknown setting is refused', first.get('spec', {}).get('state') == 'fail' and 'captions' not in first
           and second.get('spec', {}).get('state') == 'pass' and second.get('captions', {}).get('state') == 'fail'
           and typo_code == 2 and 'loudnes' in typo,
           str((first.get('spec'), sorted(first), second.get('spec'), second.get('captions'))) + typo[-200:])

    other = folder / 'other-words.json'
    spoken = [{'text': text, 'start': start, 'end': start + 0.3}
              for text, start in (('We', 0.2), ('kept', 0.5), ('this', 0.8), ('part', 1.1))]
    other.write_text(json.dumps({'version': 1, 'media': {'sha256': 'b' * 64, 'audio_stream': 1},
                                 'words': spoken}), encoding='utf-8')
    code, output = tool('check.py', '--file', export, '--captions', srt, '--speech-words', other, '--json',
                        folder / 'speech-other.json')
    refused = by_id(checks_at(folder / 'speech-other.json')).get('captions_speech', {})
    unbound_path = folder / 'unbound-words.json'
    unbound_path.write_text(json.dumps({'version': 1, 'words': spoken}), encoding='utf-8')
    tool('check.py', '--file', export, '--captions', srt, '--speech-words', unbound_path, '--json',
         folder / 'speech-unbound.json')
    unbound = by_id(checks_at(folder / 'speech-unbound.json')).get('captions_speech', {})
    mine = folder / 'export-words.json'
    one_caption = folder / 'one.srt'
    one_caption.write_text('1\n00:00:00,100 --> 00:00:01,500\nWe kept this part\n', encoding='utf-8')
    mine.write_text(json.dumps({'version': 1, 'media': {'sha256': file_sha(export), 'audio_stream': 1},
                                'words': spoken}), encoding='utf-8')
    tool('check.py', '--file', export, '--captions', one_caption, '--speech-words', mine, '--json',
         folder / 'speech-mine.json')
    matched = by_id(checks_at(folder / 'speech-mine.json')).get('captions_speech', {})
    record('native: a speech transcript of another file is never used; one that records no media is a look; one of '
           'this export is compared', refused.get('state') == 'skip' and refused['label'].startswith('Not assessed')
           and 'other media' in refused.get('detail', '') and unbound.get('state') == 'look'
           and 'cannot confirm this transcript is of this export' in unbound.get('detail', '')
           and matched.get('state') == 'pass', str((refused, unbound, matched)))

    before = srt.read_bytes()
    code, output = tool('check.py', '--file', export, '--captions', srt, '--no-speech', '--json', srt)
    words_before = words.read_bytes()
    words_code, words_output = tool('check.py', '--file', export, '--timeline', xml, '--source-words', words,
                                    '--json', folder / '.' / 'source-words.json')
    record('native: --json naming an input exits 2 and leaves the input untouched',
           code == 2 and srt.read_bytes() == before and 'is the input' in output and words_code == 2
           and words.read_bytes() == words_before, output[-200:] + words_output[-200:])

    speed = folder / 'speed.xml'
    speed.write_text(fcp7_timeline([fcp7_clip(1, 0, 75, 25, 100), fcp7_clip(
        2, 75, 150, 250, 400, '<filter><effect><effectid>timeremap</effectid></effect></filter>')], 150),
        encoding='utf-8')
    tool('exchange.py', 'words', speed, '--words', words, '--json', folder / 'speed-words.json')
    code, output = tool('check.py', '--file', export, '--captions', srt, '--edit-words', folder / 'speed-words.json',
                        '--no-speech', '--json', folder / 'speed-checks.json')
    slowed = by_id(checks_at(folder / 'speed-checks.json'))
    look = slowed.get('timeline', {})
    record('native: a clip the timeline reader cannot follow (a speed change) is a timeline look with counts; '
           '--edit-words from exchange.py works the same', look.get('state') == 'look'
           and '1 not mapped' in look.get('detail', '') and '1 of 2 clips' in look.get('label', '')
           and slowed.get('captions_edit', {}).get('state') == 'look', str(look) + output[-200:])
    run_native_project_cases(tool, record, j, scripts_dir)


def run_native_project_cases(tool, record, j, scripts_dir):
    """The project route records its inputs, expires its status when one changes and checks a final with the
    sidecar delivered with it."""
    spec = importlib.util.spec_from_file_location('lf_project_native', os.path.join(scripts_dir, 'project.py'))
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    root, folder = make_version(project, j('native-project'), '1\n00:00:00,500 --> 00:00:02,500\nHello there\n',
                                [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    code, output = tool('check.py', root, '--no-speech')
    checks = json.loads((folder / 'checks.json').read_text(encoding='utf-8'))
    roles = {row['role']: row for row in checks.get('inputs') or []}
    first = project.status_line(root)
    record('native: a project check records the preview, captions.srt, lines.json, edit.json, film.md, '
           'declared.json and manifest.json (absent ones as absent), relative to the project',
           checks.get('inputs_base') == 'project' and roles.get('preview', {}).get('path') == 'cuts/v001/preview.mp4'
           and roles.get('captions', {}).get('sha256') and roles.get('lines', {}).get('sha256')
           and roles.get('edit', {}).get('sha256') is None and roles.get('declared', {}).get('sha256') is None
           and roles.get('film', {}).get('sha256') and roles.get('manifest', {}).get('sha256')
           and "the version's own" in by_id(checks).get('captions_rules', {}).get('detail', '')
           and 'out of date' not in first, str(checks.get('inputs')) + first)
    (folder / 'captions.srt').write_text('1\n00:00:00,500 --> 00:00:02,500\nHello their\n', encoding='utf-8')
    after_captions = project.status_line(root)
    code, saved = tool('project.py', 'status', root)
    tool('check.py', root, '--no-speech')
    again = project.status_line(root)
    lines = json.loads((folder / 'lines.json').read_text(encoding='utf-8'))
    lines['lines'][0]['words'][0]['text'] = 'Hullo'
    (folder / 'lines.json').write_text(json.dumps(lines), encoding='utf-8')
    after_lines = project.status_line(root)
    record('native: the status reads out of date, naming the file, after captions.srt or lines.json changes, and '
           'current again after check.py runs', 'out of date' in after_captions
           and 'cuts/v001/captions.srt changed' in after_captions and 'pass' not in after_captions
           and 'out of date' in saved and 'out of date' not in again and 'pass' in again
           and 'cuts/v001/lines.json changed' in after_lines, ' | '.join((after_captions, saved, again, after_lines)))
    (folder / 'captions.srt').write_text('1\n00:00:00,500 --> 00:00:02,500\nHello there\n', encoding='utf-8')
    write_lines(project, folder, [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    tool('check.py', root, '--no-speech')
    final = root / 'deliver' / 'final.mp4'
    final.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(folder / 'preview.mp4', final)
    sidecar = root / 'deliver' / 'final.srt'
    sidecar.write_text('1\n00:00:00,500 --> 00:00:02,500\nHello there\n\n2\n00:00:02,600 --> 00:00:02,900\n'
                       'Crew unloading the van today\n', encoding='utf-8')
    code, output = tool('check.py', root, '--final', final, '--captions', sidecar, '--no-speech')
    given = json.loads((folder / 'checks-final.json').read_text(encoding='utf-8'))
    edit = by_id(given).get('captions_edit', {})
    sidecar_row = next((row for row in given.get('inputs') or [] if row['role'] == 'captions'), {})
    code, output = tool('check.py', root, '--final', final, '--no-speech')
    own = json.loads((folder / 'checks-final.json').read_text(encoding='utf-8'))
    own_row = next((row for row in own.get('inputs') or [] if row['role'] == 'captions'), {})
    record('native: --final --captions checks the delivered sidecar; without it the items say they checked the '
           "version's captions.srt, which is in the inputs", edit.get('state') == 'fail'
           and 'deliver/final.srt' in edit.get('detail', '') and sidecar_row.get('path') == 'deliver/final.srt'
           and by_id(own).get('captions_edit', {}).get('state') == 'pass'
           and "not a sidecar delivered with this final" in by_id(own)['captions_edit'].get('detail', '')
           and own_row.get('path') == 'cuts/v001/captions.srt',
           str((edit, sidecar_row, own_row)) + output[-200:])
    code, output = tool('check.py', root, '--timeline', folder / 'lines.json')
    record('native: --file options given to a project check are refused with the reason',
           code == 2 and '--timeline' in output and '--file' in output, output[-200:])


def run_fix2_check_cases(tool, record, j, scripts_dir):
    """Reproduce input custody, provenance, delivery and verification failures on a small synthetic export."""
    folder = Path(j('fix2-check')).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    media = folder / 'interview.mov'
    make_video(media, 'testsrc2=s=320x180:r=25', seconds=2)
    export = folder / 'export.mp4'
    shutil.copyfile(media, export)
    xml = folder / 'edit.xml'
    xml.write_text(fcp7_timeline([fcp7_clip(1, 0, 50, 0, 50)], 50).replace(
        'file://localhost/media/interview.mov', media.as_uri()), encoding='utf-8')
    words = folder / 'words.json'
    transcript = {'sources': [{'id': 'int_01', 'media_reference': 'interview.mov',
                               'media': {'sha256': file_sha(media), 'audio_stream': 1},
                               'words': [{'id': 'w1', 'text': 'Hello', 'start': 0.5, 'end': 0.9}]}]}
    words.write_text(json.dumps(transcript), encoding='utf-8')
    captions = folder / 'export.srt'
    captions.write_text('1\n00:00:00,300 --> 00:00:01,500\nHello\n', encoding='utf-8')
    args = ['--file', export, '--timeline', xml, '--source-words', words, '--no-speech']
    original = media.read_bytes()
    code, output = tool('check.py', *args, '--json', media)
    guarded = media.read_bytes() == original
    record('fix2-1a: timeline media cannot be overwritten by the checks report',
           code == 2 and guarded and 'is the input' in output,
           f'exit {code}; unchanged {guarded}; {output[-300:]}')
    media.write_bytes(original)
    checks_path = folder / 'timeline-checks.json'
    tool('check.py', *args, '--json', checks_path)
    checks = checks_at(checks_path)
    media_rows = [row for row in checks.get('inputs', []) if row.get('role') == 'timeline_media']
    media.write_bytes(original + b'changed')
    code, output = tool('check.py', '--verify', checks_path)
    record('fix2-1b: changing referenced timeline media expires a recorded check',
           len(media_rows) == 1 and media_rows[0].get('sha256') == file_sha(export)
           and code == 1 and 'interview.mov' in output,
           f'rows {media_rows}; exit {code}; {output[-300:]}')
    media.write_bytes(original)

    left, right = folder / 'left', folder / 'right'
    left.mkdir(exist_ok=True)
    right.mkdir(exist_ok=True)
    shutil.copyfile(export, left / 'same.mp4')
    shutil.copyfile(export, right / 'same.mp4')
    relative_report = left / 'relative.json'
    command = [sys.executable, '-I', str(Path(scripts_dir) / 'check.py'), '--file', 'same.mp4',
               '--no-speech', '--json', str(relative_report)]
    subprocess.run(command, cwd=left, capture_output=True, text=True, encoding='utf-8', errors='replace')
    recorded = checks_at(relative_report).get('inputs', [{}])[0].get('path', '')
    (left / 'same.mp4').write_bytes(original + b'changed')
    result = subprocess.run([sys.executable, '-I', str(Path(scripts_dir) / 'check.py'), '--verify',
                             str(relative_report)], cwd=right, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    record('fix2-4: verify uses the original absolute input, not a namesake in the caller folder',
           Path(recorded).is_absolute() and result.returncode == 1 and 'content changed' in result.stdout,
           f'path {recorded}; exit {result.returncode}; {result.stdout[-300:]}{result.stderr[-200:]}')

    transcript['sources'][0].pop('media')
    words.write_text(json.dumps(transcript), encoding='utf-8')
    unbound_path = folder / 'unbound.json'
    tool('check.py', *args, '--captions', captions, '--json', unbound_path)
    unbound = by_id(checks_at(unbound_path))
    timeline, edit = unbound.get('timeline', {}), unbound.get('captions_edit', {})
    advice = ' '.join((timeline.get('detail', ''), edit.get('detail', '')))
    record('fix2-5: unbound or name-only timeline words make both comparisons a look with binding advice',
           timeline.get('state') == 'look' and edit.get('state') == 'look'
           and 'not verified' in advice and 'map.py run' in advice and 'map.py confirm-words' in advice,
           str((timeline, edit)))

    delivery = folder / 'delivery.json'
    delivery.write_text(json.dumps({'fps': 30}), encoding='utf-8')
    fps_report = folder / 'fps.json'
    tool('check.py', '--file', export, '--delivery', delivery, '--no-speech', '--json', fps_report)
    fps = by_id(checks_at(fps_report)).get('spec', {})
    delivery.write_text(json.dumps({'frames': 999}), encoding='utf-8')
    frames_report = folder / 'frames.json'
    tool('check.py', '--file', export, '--delivery', delivery, '--spec', '320x180@25', '--no-speech',
         '--json', frames_report)
    frames = by_id(checks_at(frames_report)).get('spec', {})
    record('fix2-6a: a delivery frame rate is checked without a delivery size',
           fps.get('state') == 'fail' and 'fps' in fps.get('detail', ''), str(fps))
    record('fix2-6b: delivery frame count is checked when --spec is supplied',
           frames.get('state') == 'fail' and 'frames' in frames.get('detail', ''), str(frames))

    empty = folder / 'empty-inputs.json'
    empty.write_text(json.dumps({'inputs': []}), encoding='utf-8')
    empty_code, empty_output = tool('check.py', '--verify', empty)
    bad = checks_at(checks_path)
    bad['tools']['scripts'] = ['check.py']
    malformed = folder / 'bad-tools.json'
    malformed.write_text(json.dumps(bad), encoding='utf-8')
    bad_code, bad_output = tool('check.py', '--verify', malformed)
    record('fix2-10: empty inputs and malformed tool shapes cannot verify, with no traceback',
           empty_code == 2 and bad_code == 2 and 'cannot verify' in empty_output.lower()
           and 'cannot verify' in bad_output.lower() and 'Traceback' not in bad_output,
           f'empty {empty_code} {empty_output[-180:]}; tools {bad_code} {bad_output[-250:]}')

    spec = importlib.util.spec_from_file_location('lf_fix2_project', Path(scripts_dir) / 'project.py')
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    root, version = make_version(project, j('fix2-project'),
                                 '1\n00:00:00,500 --> 00:00:02,500\nHello there\n',
                                 [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    qa = version / 'qa'
    qa.mkdir(exist_ok=True)
    profile = qa / 'captions-speech.json'
    profile.write_text('{}', encoding='utf-8')
    before = profile.read_bytes()
    code, output = tool('check.py', root, '--caption-profile', profile, '--no-speech')
    unchanged = profile.is_file() and profile.read_bytes() == before
    record('fix2-2: a profile at a QA publication path is refused before it can be removed',
           code == 2 and unchanged and 'is the input' in output,
           f'exit {code}; unchanged {unchanged}; {output[-300:]}')

    from PIL import Image, ImageDraw
    title = version / 'title.png'
    image = Image.new('RGBA', (80, 40), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((20, 10, 60, 30), fill=(255, 255, 255, 255))
    image.save(title)
    project.save_json(version / 'edit.json', {'sources': {'title-1': {'file': 'title.png'}},
                                             'overlays': [{'kind': 'image', 'src': 'title-1',
                                                           'from': 0.5, 'to': 1.5}]})
    tool('check.py', root, '--no-speech')
    title_check = project.load_json(version / 'checks.json')
    rows = [row for row in title_check.get('inputs', []) if row.get('role') == 'title_asset']
    title.unlink()
    code, output = tool('check.py', '--verify', version / 'checks.json')
    line = project.status_line(root)
    record('fix2-8: a title image read by contrast is recorded and its removal expires checks',
           len(rows) == 1 and rows[0].get('sha256') and code == 1 and 'title.png' in output
           and 'out of date' in line, f'rows {rows}; exit {code}; {output[-250:]}; {line}')


def run_fix2_qa_tool_alias_case(record, j, scripts_dir):
    """A QA output hard-linked to a tool is refused before any scanner publishes over that tool."""
    folder = Path(j('fix2-qa-tool')).resolve()
    scripts = folder / 'scripts'
    scripts.mkdir(parents=True, exist_ok=True)
    for source in Path(scripts_dir).glob('*.py'):
        shutil.copyfile(source, scripts / source.name)
    spec = importlib.util.spec_from_file_location('lf_fix2_qa_project', scripts / 'project.py')
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    root, version = make_version(project, folder / 'project',
                                 '1\n00:00:00,500 --> 00:00:02,500\nHello there\n',
                                 [('Hello', 0.5, 1.0), ('there', 1.1, 2.4)])
    qa = version / 'qa'
    qa.mkdir(exist_ok=True)
    script = scripts / 'check.py'
    before = script.read_bytes()
    try:
        os.link(script, qa / 'qc.json')
    except OSError as error:
        print(f'SKIP  fix2: hard-link QA guard ({error})')
        return
    code, output = run_copy(scripts, 'check.py', root, '--no-speech')
    unchanged = script.read_bytes() == before
    record('fix2: QA cannot overwrite a script through a hard link',
           code == 2 and unchanged and 'is the input' in output,
           f'exit {code}; unchanged {unchanged}; {output[-250:]}')


def run_fix2_speech_input_cases(record, j, scripts_dir):
    """Changes to transcript model-selection candidates and their listing expire a check."""
    check, why = load_module(scripts_dir, 'check')
    if check is None:
        record('fix2: speech-selection inputs are recorded', False, why)
        return
    root = check.P.init(Path(j('fix2-speech-inputs')).resolve())
    folder = root / 'cuts' / 'v001'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'preview.mp4').write_bytes(b'synthetic preview')
    (folder / 'film.md').write_text('---\ntitle: Test\n---\n', encoding='utf-8')
    check.P.save_json(folder / 'manifest.json', {'version': 'v001'})
    check.P.set_current(root, 'v001')
    for alias, engine in (('a', 'imported'), ('b', 'faster-whisper small')):
        path = root / 'map' / alias / 'words.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        check.P.save_json(path, {'engine': engine, 'words': []})
    check.P.save_json(root / 'map' / 'sources.json', {'sources': [{'alias': 'a'}, {'alias': 'b'}]})
    (root / 'map' / 'aa').mkdir(exist_ok=True)

    def stub(*args, **kwargs):
        result = check.item('speech', args[8][0], 'pass')
        return {'version': 1, 'items': [result], 'summary': check.summarise([result])}

    check.run_checks = stub
    checks = check.check_project(root, 'v001', speech=True)
    before = check.speech_settings(root)
    check.P.save_json(root / 'map' / 'a' / 'words.json', {'engine': 'faster-whisper large', 'words': []})
    after = check.speech_settings(root)
    fresh = check.P.checks_freshness(root, checks)
    code, lines = check.verify(folder / 'checks.json')
    record('fix2: a changed earlier transcript used to select the speech model expires checks',
           before[0] == 'small' and after[0] == 'large' and fresh[0] == 'out_of_date'
           and code == 1, str((before, after, fresh, code, lines)))
    check.P.save_json(root / 'map' / 'a' / 'words.json', {'engine': 'imported', 'words': []})
    checks = check.check_project(root, 'v001', speech=True)
    check.P.save_json(root / 'map' / 'aa' / 'words.json', {'engine': 'faster-whisper medium', 'words': []})
    fresh = check.P.checks_freshness(root, checks)
    code, lines = check.verify(folder / 'checks.json')
    record('fix2: adding a transcript candidate to an existing map folder expires checks',
           check.speech_settings(root)[0] == 'medium' and fresh[0] == 'out_of_date'
           and code == 1, str((fresh, code, lines)))


def run_fix2_tool_dependency_cases(record, j, scripts_dir):
    """The probe, imported scripts and package versions that change measurements expire results."""
    from unittest.mock import patch
    folder = Path(j('fix2-tool-dependencies')).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('check.py', 'project.py', 'qc_file.py', 'blank_scan.py', 'render_common.py', 'transcribe.py'):
        shutil.copyfile(Path(scripts_dir) / name, folder / name)
    check, why = load_module(folder, 'check')
    if check is None:
        record('fix2: tool dependencies are recorded', False, why)
        return
    check.INVOKED.update(('qc_file.py', 'blank_scan.py'))
    recorded = check.tools_record()
    with (folder / 'render_common.py').open('a', encoding='utf-8') as stream:
        stream.write('\n# Synthetic dependency change\n')
    changes = check.tool_changes(recorded)
    record('fix2: changing a script imported by a scanner expires the tool record',
           any(row.get('tool') == 'render_common.py' for row in changes), str(changes))
    with patch.object(check.P, 'ffprobe_version', return_value='ffprobe version before', create=True):
        recorded = check.tools_record()
    with patch.object(check.P, 'ffprobe_version', return_value='ffprobe version after', create=True):
        changes = check.tool_changes(recorded)
    record('fix2: changing FFprobe expires the tool record',
           recorded.get('ffprobe') == 'ffprobe version before'
           and any(row.get('tool') == 'ffprobe' for row in changes), str((recorded, changes))[-800:])

    def version(name):
        return '1.0' if name == 'numpy' else None

    with patch.object(check.P, 'package_version', side_effect=version, create=True):
        recorded = check.tools_record()
    with patch.object(check.P, 'package_version', return_value=None, create=True):
        changes = check.tool_changes(recorded)
    record('fix2: changing a package used by the scanners expires the tool record',
           recorded.get('packages', {}).get('numpy') == '1.0'
           and any(row.get('tool') == 'package numpy' for row in changes), str((recorded, changes))[-800:])
    check.INVOKED.clear()
    with patch.object(check, 'speech_engine_missing', return_value='not installed'):
        speech = check.speech_item('video', 'captions', folder, 'small', None)
    with patch.object(check.P, 'package_version', return_value=None, create=True):
        recorded = check.tools_record('small')

    def installed(name):
        return '1.0' if name == 'faster-whisper' else None

    with patch.object(check.P, 'package_version', side_effect=installed, create=True):
        changes = check.tool_changes(recorded)
    record('fix2: installing a previously missing speech engine expires its skipped check',
           speech.get('state') == 'skip' and isinstance(recorded.get('faster_whisper'), dict)
           and any(row.get('tool') == 'faster-whisper' for row in changes), str((recorded, changes))[-800:])
