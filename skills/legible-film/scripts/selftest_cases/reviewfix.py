"""Regressions for review findings in the footage and dialogue tools."""
import importlib.util
import json
import time
import wave
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw


def run_reviewfix_cases(tool, record, j, scripts_dir):
    """Test known frame selection and caption segmentation failures."""
    spec = importlib.util.spec_from_file_location('review_footage', Path(scripts_dir) / 'selftest_cases/footage.py')
    footage = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(footage)
    for fps in (25, 30):
        frames = []
        for number in range(fps * 2):
            image = Image.new('RGB', (160, 90), (60, 70, 80))
            draw = ImageDraw.Draw(image)
            for bit in range(6):
                draw.rectangle((10 + bit * 15, 28, 20 + bit * 15, 40),
                               fill='white' if number & (1 << bit) else 'black')
            frames.append(np.asarray(image).tobytes())
        source = j('review-counter-%d.mkv' % fps)
        footage.ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x90', '-r', fps,
                       '-i', 'pipe:0', '-c:v', 'ffv1', source, data=b''.join(frames))
        edit = {'version': 1, 'size': [160, 90], 'fps': fps, 'sources': {'a': {'file': source}},
                'picture': [{'src': 'a', 'in': .5, 'out': 1.5}]}
        code, out, directory = footage.assemble(tool, j, 'review-counter-%d' % fps, edit)
        if (directory / 'picture.mp4').exists():
            actual = [footage.counter(frame) for frame in footage.video_frames(directory / 'picture.mp4', 160, 90)]
            expected = list(range(12, 37)) if fps == 25 else list(range(15, 45))
            record('reviewfix: %d fps no repeated or dropped frames' % fps, actual == expected, str(actual))
        else:
            record('reviewfix: %d fps no repeated or dropped frames' % fps, False, out[-300:])
    spec = importlib.util.spec_from_file_location('review_captions', Path(scripts_dir) / 'captions.py')
    captions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(captions)
    vocabulary = 'the team started with a simple question about how planning works and what people need'.split()
    words = [{'text': vocabulary[i % len(vocabulary)], 'start': i * .32, 'end': i * .32 + .25}
             for i in range(800)]
    args = SimpleNamespace(cps=20, line_length=42, min_duration=.8, max_duration=7, gap=.04)
    started = time.monotonic()
    cues = captions.segment(words, args)
    elapsed = time.monotonic() - started
    record('reviewfix: 800 words segment in seconds', elapsed < 5 and sum(len(c['words']) for c in cues) == 800,
           '%.3f s' % elapsed)
    source = {'events': [{'id': 'one', 't': 1, 'sound': 'required'},
                         {'id': 'two', 't': 2, 'sound': 'required'}]}
    Path(j('review-cues.json')).write_text(json.dumps(source), encoding='utf-8')
    code, out = tool('cue_onsets.py', j('trace-cleared.wav'), j('review-cues.json'),
                     '--reference', 'one=' + j('trace-ref.wav'), '--expect-absent',
                     '--json', j('review-cue-report.json'))
    report = json.loads(Path(j('review-cue-report.json')).read_text(encoding='utf-8')) if code != 2 else {}
    record('reviewfix: absence checks only referenced cues', code == 0 and report.get('not_checked') == ['two'],
           out[-200:])
    # The compact source is 120 seconds long, while the edit uses only one second.
    long_source = j('review-long.mkv')
    footage.ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=120', '-c:v', 'ffv1', long_source)
    edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': long_source}},
            'picture': [{'src': 'a', 'in': 10, 'out': 11}]}
    code, out, directory = footage.assemble(tool, j, 'review-long-edit', edit)
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8')) if code in (0, 1) else {}
    record('reviewfix: two-minute source uses range-sized spool', code == 0 and
           report.get('source_spool_bytes', 10 ** 9) < 5 * 1024 * 1024, out[-200:])

    # Request an audio out beyond the four-second synthetic source.
    source = j('footage-source.mkv')
    edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': source}},
            'picture': [{'src': 'a', 'in': 2.5, 'out': 5}],
            'audio': [{'src': 'a', 'track': 'dialogue', 'in': 2.5, 'out': 5, 'at': 0}],
            'holds': [{'start': .1, 'end': .3}]}
    code, out, directory = footage.assemble(tool, j, 'review-clamped', edit)
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8')) if code in (0, 1) else {}
    audio = [row for row in report.get('snaps', []) if row.get('clock') == 'audio sample']
    declared = json.loads((directory / 'declared.json').read_text(encoding='utf-8')) if code in (0, 1) else {}
    fade_ok = False
    stem = directory / 'dialogue.wav'
    if stem.exists():
        with wave.open(str(stem), 'rb') as file:
            samples = np.frombuffer(file.readframes(file.getnframes()), '<i2').reshape(-1, file.getnchannels())
        tail = np.sqrt(np.mean(samples[-240:].astype(np.float64) ** 2))
        before = np.sqrt(np.mean(samples[-4800:-2400].astype(np.float64) ** 2))
        fade_ok = tail < before * .3
    record('reviewfix: audio out clamps, fades and requests review', code == 1 and len(audio) == 2 and
           abs(audio[1]['snapped'] - 4) <= 1 / 48000 and bool(report.get('notes')) and fade_ok, out[-200:])
    record('reviewfix: declared hold is an ignore string', declared.get('ignore') == '0.100-0.300', str(declared))
    short_audio = j('review-short-audio.mkv')
    footage.ffmpeg('-f', 'lavfi', '-i', 'color=gray:s=160x90:r=10:d=4', '-f', 'lavfi', '-i',
                   'sine=frequency=440:sample_rate=48000:duration=1', '-map', '0:v', '-map', '1:a',
                   '-c:v', 'ffv1', '-c:a', 'pcm_s16le', short_audio)
    short_edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': short_audio}},
                  'picture': [{'src': 'a', 'in': 0, 'out': 3}],
                  'audio': [{'src': 'a', 'track': 'dialogue', 'in': 0, 'out': 3, 'at': 0}]}
    short_code, short_out, short_dir = footage.assemble(tool, j, 'review-short-audio-edit', short_edit)
    short_report = json.loads((short_dir / 'report.json').read_text(encoding='utf-8')) if short_code == 1 else {}
    audio_points = [row for row in short_report.get('snaps', []) if row.get('clock') == 'audio sample']
    record('reviewfix: audio end uses stream timing when duration metadata is missing',
           short_code == 1 and len(audio_points) == 2 and abs(audio_points[1]['snapped'] - 1) <= 1 / 48000,
           short_out[-200:])
    dip_edit = {'version': 1, 'size': [160, 90], 'fps': 10, 'sources': {'a': {'file': source}},
                'picture': [{'src': 'a', 'in': 0, 'out': 1},
                            {'src': 'a', 'in': 1, 'out': 2, 'join': {'kind': 'dip', 'dur': .2}}]}
    dip_code, dip_out, dip_dir = footage.assemble(tool, j, 'review-dip', dip_edit)
    dip = json.loads((dip_dir / 'declared.json').read_text(encoding='utf-8')) if dip_code in (0, 1) else {}
    record('reviewfix: declared dip is an ignore string', dip.get('ignore') == '0.800-1.000', dip_out[-200:])

    # A late audio stream contains the click at presentation time 1.5 seconds.
    rate = 48000
    samples = .05 * np.sin(2 * np.pi * 440 * np.arange(rate * 2) / rate)
    samples[rate // 2:rate // 2 + 240] += .8 * np.hanning(480)[:240]
    with wave.open(j('review-late-audio.wav'), 'wb') as file:
        file.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        file.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    late = j('review-late.mp4')
    footage.ffmpeg('-f', 'lavfi', '-i', 'color=gray:s=160x90:r=30:d=3', '-itsoffset', '1',
                   '-i', j('review-late-audio.wav'), '-map', '0:v', '-map', '1:a',
                   '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', late)
    cue = {'events': [{'id': 'click', 't': 1.5, 'sound': 'required', 'window_ms': 100, 'tolerance_ms': 20}]}
    Path(j('review-late-cue.json')).write_text(json.dumps(cue), encoding='utf-8')
    code, out = tool('cue_onsets.py', late, j('review-late-cue.json'))
    record('reviewfix: late stream uses film clock without reference', code == 0 and 'on cue' in out, out[-200:])
    edit = {'version': 1, 'size': [160, 90], 'fps': 30, 'sources': {'a': {'file': late}},
            'picture': [{'src': 'a', 'in': 1.4, 'out': 1.9}],
            'audio': [{'src': 'a', 'track': 'dialogue', 'in': 1.4, 'out': 1.9, 'at': 0}]}
    code, out, directory = footage.assemble(tool, j, 'review-late-edit', edit)
    cue['events'][0]['t'] = .1
    Path(j('review-late-stem-cue.json')).write_text(json.dumps(cue), encoding='utf-8')
    if (directory / 'dialogue.wav').exists():
        stem_code, stem_out = tool('cue_onsets.py', directory / 'dialogue.wav', j('review-late-stem-cue.json'))
    else:
        stem_code, stem_out = 2, out
    record('reviewfix: assembled late stream aligns with picture', stem_code == 0 and 'on cue' in stem_out,
           stem_out[-200:])

    tiny = j('review-tiny.mkv')
    tiny_frames = []
    for index in range(60):
        image = np.zeros((90, 160, 3), dtype=np.uint8)
        image[40:44, index:index + 4] = 255
        tiny_frames.append(image.tobytes())
    footage.ffmpeg('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '160x90', '-r', '30',
                   '-i', 'pipe:0', '-c:v', 'ffv1', tiny, data=b''.join(tiny_frames))
    code, out = tool('motion_scan.py', tiny, '--max-still-share', '.1', '--max-still', '.5')
    record('reviewfix: inconclusive pace gate exits one', code == 1 and 'INCONCLUSIVE' in out, out[-250:])

    caption_source = Path(j('review-many.srt'))
    lines = []
    for index in range(300):
        start = index * 10
        end = start + 9
        lines.extend([str(index + 1), '00:00:%02d,%03d --> 00:00:%02d,%03d' %
                      (start // 1000, start % 1000, end // 1000, end % 1000), 'Two words', ''])
    caption_source.write_text('\n'.join(lines), encoding='utf-8')
    code, out = tool('captions.py', 'burn', j('footage-source.mkv'), caption_source,
                     '--out', j('review-many.mp4'))
    record('reviewfix: 300 caption states use one overlay stream', code == 0 and Path(j('review-many.mp4')).exists(),
           out[-200:])
    # Sustained phrases with deep syllable gaps must keep one measured duck depth.
    rate = 48000
    clock = np.arange(rate * 6) / rate
    random = np.random.default_rng(3)
    voice = np.zeros(len(clock))
    for start, end in ((.5, 2.5), (3.5, 5.5)):
        mask = (clock >= start) & (clock < end)
        syllable = .5 * (1 - np.cos(2 * np.pi * 4 * (clock[mask] - start)))
        envelope = 10 ** (-25 / 20) + (1 - 10 ** (-25 / 20)) * syllable ** 2
        voice[mask] = .2 * envelope * random.standard_normal(mask.sum())
    music = .1 * np.sin(2 * np.pi * 220 * clock) + .05 * np.sin(2 * np.pi * 330 * clock)
    for name, samples in (('review-voice.wav', voice), ('review-music.wav', music)):
        with wave.open(j(name), 'wb') as file:
            file.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            file.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    Path(j('review-mix-cues.json')).write_text(json.dumps({'duration': 6, 'events': []}), encoding='utf-8')
    palette = {'version': 2, 'roles': {},
               'music': {'file': 'review-music.wav', 'fade_in_ms': 0, 'fade_out_ms': 0},
               'voice': {'file': 'review-voice.wav', 'at_s': 0, 'gain_db': 0}}
    Path(j('review-palette.json')).write_text(json.dumps(palette), encoding='utf-8')
    code, out = tool('mix_cues.py', j('review-mix-cues.json'), j('review-palette.json'),
                     '--out-dir', j('review-mix'))
    path = Path(j('review-mix', 'mix-report.json'))
    report = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    phrases = report.get('voice', {}).get('phrases', [])
    record('reviewfix: syllabic phrases achieve requested separation within 1 LU',
           code == 0 and len(phrases) == 2 and all(abs(row['separation_lu'] - 10) <= 1 for row in phrases),
           str(phrases))

    long_voice = j('review-voice-long.wav')
    footage.ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=400:sample_rate=48000:duration=120',
                   '-c:a', 'pcm_s16le', long_voice)
    code, out = tool('voice_clean.py', long_voice, '--out', j('review-voice-clean.wav'),
                     '--json', j('review-voice-clean.json'))
    record('reviewfix: two-minute voice processes through bounded blocks',
           code in (0, 1) and Path(j('review-voice-clean.wav')).exists(), out[-200:])

    long_video = j('review-ten-minutes.mp4')
    footage.ffmpeg('-f', 'lavfi', '-i', 'color=gray:s=160x90:r=2:d=600', '-c:v', 'libx264',
                   '-preset', 'ultrafast', long_video)
    highlights = []
    for index in range(300):
        start = index * 2.0
        words = [{'text': word, 'start': start + k, 'end': start + k + 1}
                 for k, word in enumerate(('one', 'two'))]
        highlights.append({'start': start, 'end': start + 2, 'text': 'one two', 'words': words})
    Path(j('review-highlight.json')).write_text(json.dumps({'cues': highlights}), encoding='utf-8')
    code, out = tool('captions.py', 'burn', long_video, j('review-highlight.json'), '--highlight',
                     '--out', j('review-highlight.mp4'))
    record('reviewfix: ten-minute 300-caption highlighting renders',
           code == 0 and Path(j('review-highlight.mp4')).exists(), out[-200:])
