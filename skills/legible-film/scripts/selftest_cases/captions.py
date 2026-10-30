"""Known-answer tests for transcript cuts and caption build, check and burn."""
import json
from pathlib import Path
import subprocess

import numpy as np


def run_captions_cases(tool, record, j, scripts_dir):
    """Exercise reading constraints, timing screens and decoded picture pixels."""
    root = Path(j('captions-cases'))
    root.mkdir(parents=True, exist_ok=True)

    def save(name, value):
        path = root / name
        path.write_text(json.dumps(value, indent=2), encoding='utf-8')
        return path

    def load(name):
        return json.loads((root / name).read_text(encoding='utf-8'))

    def run_ff(*args, data=None):
        command = ['ffmpeg', '-v', 'error', '-y', *map(str, args)]
        result = subprocess.run(command, input=data, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace')[-600:])
        return result.stdout

    def report_check(name, text, expected, kind):
        path = root / (name + '.srt')
        path.write_text(text, encoding='utf-8')
        report = root / (name + '-report.json')
        code, output = tool('captions.py', 'check', path, '--json', report)
        rules = [item['rule'] for item in load(name + '-report.json')[kind]]
        # Findings are errors (exit 1); reading speed, duration and layout style are review prompts (exit 0).
        record(f'captions: reports {name} as {kind}', code == (1 if kind == 'findings' else 0)
               and expected in rules, str(rules))

    cases = [
        ('cps', '1\n00:00:00,000 --> 00:00:01,000\nA rather long caption indeed\n', 'cps', 'review'),
        ('line length', '1\n00:00:00,000 --> 00:00:05,000\n' + 'x' * 43 + '\n', 'line length', 'findings'),
        ('two lines', '1\n00:00:00,000 --> 00:00:03,000\none two\nthree four\nfive six\n', 'lines', 'findings'),
        ('minimum duration', '1\n00:00:00,000 --> 00:00:00,500\nHi\n', 'minimum duration', 'review'),
        ('maximum duration', '1\n00:00:00,000 --> 00:00:08,000\nTwo words\n', 'maximum duration', 'review'),
        ('gap', '1\n00:00:00,000 --> 00:00:01,000\nFirst words\n\n'
                '2\n00:00:00,900 --> 00:00:02,000\nNext words\n', 'overlap', 'findings'),
        ('orphan', '1\n00:00:00,000 --> 00:00:03,000\nOne\ntwo words\n', 'orphan', 'review'),
    ]
    for name, text, expected, kind in cases:
        report_check(name, text, expected, kind)

    sentence = ('Ada Lovelace Institute studies 4.5 GB and 120 fps, while the plan costs '
                '$1,200 a month and the new system supports careful research.')
    items = [{'word': word, 'start': index * .55, 'end': index * .55 + .35}
             for index, word in enumerate(sentence.split())]
    source = save('sentence.json', items)
    code, output = tool('captions.py', 'build', source, '--out', root / 'sentence',
                        '--json', root / 'sentence-report.json')
    if code == 0:
        cues = load('sentence.json')['cues']
        srt_code, _ = tool('captions.py', 'check', root / 'sentence.srt')
        vtt_code, _ = tool('captions.py', 'check', root / 'sentence.vtt')
        lines = [line for cue in cues for line in cue['text'].split('\n')]
        names = any('Ada Lovelace Institute' in line for line in lines)
        numbers = all(any(number in line for line in lines)
                      for number in ('4.5 GB', '120 fps', '$1,200 a month'))
        record('captions: long sentence obeys rules in matching formats', srt_code == 0 and vtt_code == 0
               and len(cues) > 1, output[-120:])
        record('captions: name stays whole', names, str(lines))
        record('captions: numbers and units stay whole', numbers, str(lines))
    else:
        record('captions: long sentence obeys rules in matching formats', False, output[-400:])
        record('captions: name stays whole', False, output[-200:])
        record('captions: numbers and units stay whole', False, output[-200:])

    line = save('timed-line.json', [{'text': sentence, 'start': 0, 'end': 15}])
    code, output = tool('captions.py', 'build', line, '--out', root / 'timed-line-out',
                        '--json', root / 'timed-line-report.json')
    result = load('timed-line-report.json')
    record('captions: splits long timed lines with disclosed estimates',
           code == 0 and result['word_timings_estimated'] and result['cues'] > 1, output[-200:])

    rate = 16000
    samples = np.random.default_rng(3).normal(0, .003, rate * 5).astype(np.float32)
    for start, end in ((1.0, 1.4), (1.5, 2.0)):
        times = np.arange(round((end - start) * rate)) / rate
        samples[round(start * rate):round(end * rate)] += (.15 * np.sin(2 * np.pi * 500 * times)).astype(np.float32)
    audio = root / 'noisy.wav'
    run_ff('-f', 'f32le', '-ar', rate, '-ac', 1, '-i', '-', '-c:a', 'pcm_s16le', audio, data=samples.tobytes())
    captions = root / 'audio-check.srt'
    captions.write_text('1\n00:00:00,500 --> 00:00:02,500\nHello there\n', encoding='utf-8')
    code, output = tool('captions.py', 'check', captions, '--audio', audio, '--margin', '.25',
                        '--json', root / 'audio-report.json')
    report = load('audio-report.json')
    rules = {finding['rule'] for finding in report['review']}
    record('captions: noisy speech-band timing screen prompts review of early and late', code == 0
           and {'starts before timing region', 'outlasts timing region'} <= rules
           and report['timing_screen']['basis'] == 'speech-band envelope', str(report['timing_screen']))
    timings = save('timings.json', [{'word': 'Hello', 'start': 1, 'end': 1.4},
                                   {'word': 'there', 'start': 1.5, 'end': 2}])
    code, output = tool('captions.py', 'check', captions, '--audio', audio, '--words', timings,
                        '--json', root / 'word-report.json')
    report = load('word-report.json')
    record('captions: word timings take precedence over audio', code == 0
           and report['timing_screen']['basis'] == 'word timings' and not report['findings']
           and {item['rule'] for item in report['review']} == {'enters before the speech', 'outlasts the speech'},
           str(report['review']))
    # Captions against the current dialogue (a word-timed transcript of the delivered audio). Shapes from a
    # professional's revisions: words cut from the audio but left in a caption, a caption over no speech, an
    # intentional one-word caption, and a caption entering late.
    spoken = save('dialogue.json', [
        {'word': 'It', 'start': 1.0, 'end': 1.15}, {'word': 'felt', 'start': 1.2, 'end': 1.45},
        {'word': 'easy.', 'start': 1.5, 'end': 1.9}, {'word': 'Physical?', 'start': 3.0, 'end': 3.5},
        {'word': 'Then', 'start': 6.0, 'end': 6.2}, {'word': 'we', 'start': 6.25, 'end': 6.35},
        {'word': 'moved', 'start': 6.4, 'end': 6.7}, {'word': 'on', 'start': 6.75, 'end': 6.95},
        {'word': 'right', 'start': 7.0, 'end': 7.3}, {'word': 'away.', 'start': 7.35, 'end': 7.8}])

    def srt(rows):
        """An SRT from (start, end, text) rows in seconds."""
        stamp = lambda s: '00:00:%02d,%03d' % (int(s), round((s - int(s)) * 1000))  # noqa: E731
        return ''.join('%d\n%s --> %s\n%s\n\n' % (n, stamp(a), stamp(b), text)
                       for n, (a, b, text) in enumerate(rows, 1))

    revised = root / 'revised.srt'
    revised.write_text(srt([(1.0, 2.4, 'It felt like nothing, easy.'), (3.0, 3.5, 'Physical?'), (4.5, 5.3, 'Oh.'),
                            (6.4, 8.0, 'Then we moved on right away.')]), encoding='utf-8')
    code, output = tool('captions.py', 'check', revised, '--words', spoken, '--json', root / 'revised-report.json')
    report = load('revised-report.json')
    found = {(item.get('cue'), item['rule']): item for item in report['findings']}
    prompts = {(item.get('cue'), item['rule']) for item in report['review']}
    record('captions: names the words cut from the dialogue but left in a caption',
           found.get((1, 'caption words not in the dialogue'), {}).get('words') == ['like', 'nothing'],
           str(report['findings']))
    record('captions: flags a caption over no matching speech', (3, 'caption over no matching speech') in found
           and code == 1, str(report['findings']))
    record('captions: a short caption and a late entrance are review prompts, not findings',
           {(2, 'minimum duration'), (4, 'enters after the speech starts')} <= prompts
           and not any(cue in (2, 4) for cue, _ in found), str(report['review']))
    late = root / 'late.srt'
    late.write_text(srt([(2.0, 2.9, 'It felt easy.'), (4.0, 4.5, 'Physical?'), (7.0, 8.0, 'Then we moved on'),
                         (8.0, 8.8, 'right away.')]), encoding='utf-8')
    code, output = tool('captions.py', 'check', late, '--words', spoken, '--json', root / 'late-report.json')
    report = load('late-report.json')
    record('captions: a whole file one second late is one offset finding, the words still matched',
           code == 1 and [item['rule'] for item in report['findings']] == ['captions offset from the dialogue']
           and report['findings'][0]['offset_s'] == 1.0, str(report['findings']))
    short = root / 'short-only.srt'
    short.write_text(srt([(3.0, 3.5, 'Physical?')]), encoding='utf-8')
    code, output = tool('captions.py', 'check', short, '--words', spoken, '--json', root / 'short-report.json')
    report = load('short-report.json')
    record('captions: an intentional one-word caption exits 0 with its duration as a review prompt',
           code == 0 and not report['findings']
           and [item['rule'] for item in report['review']] == ['minimum duration'], str(report))

    cut_words = [{'word': word, 'start': start, 'end': end, 'score': .99}
                 for word, start, end in [('Hello', 1, 1.4), ('there', 1.5, 2),
                                          ('Hello', 2.6, 3.0), ('there', 3.1, 3.5)]]
    # Add two further synthetic voiced intervals to the source.
    for start, end in ((2.6, 3.0), (3.1, 3.5)):
        times = np.arange(round((end - start) * rate)) / rate
        samples[round(start * rate):round(end * rate)] += (.15 * np.sin(2 * np.pi * 500 * times)).astype(np.float32)
    run_ff('-f', 'f32le', '-ar', rate, '-ac', 1, '-i', '-', '-c:a', 'pcm_s16le', audio, data=samples.tobytes())
    cut_input = save('cut-input.json', cut_words)
    shots = save('shots.json', {'cuts': []})
    selects = root / 'selects.txt'
    selects.write_text('"hello there"\n"HELLO, there"\n', encoding='utf-8')
    code, output = tool('transcript_cut.py', cut_input, '--selects', selects, '--source', audio,
                        '--audio', audio, '--shots', shots, '--out', root / 'edit.json',
                        '--json', root / 'cut-report.json')
    report = load('cut-report.json')
    edit = load('edit.json')
    boundaries = [item[key] for item in edit['picture'] for key in ('in', 'out')]
    outside = all(not any(word['start'] < point < word['end'] for word in cut_words) for point in boundaries)
    quiet = all(abs(samples[min(len(samples) - 1, round(point * rate))]) < .02 for point in boundaries)
    record('transcript cut: audio cuts in gaps and same-shot jump flagged', code == 1 and outside and quiet
           and report['joins'][0]['jump_cut_candidate'], str(report['joins']))
    # Reconstruct the dialogue stem from the edit and check known tone onsets on the edit clock.
    stem = np.concatenate([samples[round(item['in'] * rate):round(item['out'] * rate)]
                           for item in edit['audio']])
    expected_onsets = [edit['audio'][0]['at'] + cut_words[index]['start'] - edit['audio'][0]['in']
                       for index in (0, 1)]
    expected_onsets += [edit['audio'][1]['at'] + cut_words[index]['start'] - edit['audio'][1]['in']
                        for index in (2, 3)]
    measured_onsets = []
    for expected in expected_onsets:
        begin = max(0, round((expected - .02) * rate))
        end = min(len(stem), round((expected + .02) * rate))
        indices = np.flatnonzero(np.abs(stem[begin:end]) > .05)
        measured_onsets.append((begin + indices[0]) / rate if len(indices) else None)
    record('transcript cut: reconstructed stem retains tone onsets',
           all(measured is not None and abs(measured - expected) < .003
               for measured, expected in zip(measured_onsets, expected_onsets)), str(measured_onsets))
    record('transcript cut: repeated phrases resolve sequentially',
           [item['occurrence'] for item in report['selected']] == [1, 2], str(report['selected']))
    selects.write_text('"hello there" @2\n', encoding='utf-8')
    code, output = tool('transcript_cut.py', cut_input, '--selects', selects, '--source', audio,
                        '--out', root / 'edit.json', '--json', root / 'cut-report.json')
    report = load('cut-report.json')
    record('transcript cut: explicit occurrence and source duration', code == 0
           and report['selected'][0]['occurrence'] == 2 and report['source_duration_s'] == 5, output[-200:])
    selects.write_text('"not found"\n', encoding='utf-8')
    code, output = tool('transcript_cut.py', cut_input, '--selects', selects, '--source', audio,
                        '--out', root / 'edit.json', '--json', root / 'cut-report.json')
    record('transcript cut: missing phrase removes stale output', code == 1
           and not (root / 'edit.json').exists() and len(load('cut-report.json')['missing']) == 1, output[-100:])

    video = root / 'tall.mp4'
    run_ff('-f', 'lavfi', '-i', 'color=black:s=360x640:r=10:d=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', video)
    repeated = save('repeat.json', {'cues': [{'start': .5, 'end': 2.5, 'text': 'go go',
                                             'words': [{'text': 'go', 'start': .5, 'end': 1.3},
                                                       {'text': 'go', 'start': 1.3, 'end': 2.3}]}]})
    code, output = tool('captions.py', 'burn', video, repeated, '--out', root / 'burn.mp4', '--highlight',
                        '--json', root / 'burn-report.json')
    if code != 0:
        record('captions: tall burn timing and safe area', False, output[-500:])
        record('captions: repeated words highlight by index', False, output[-300:])
        record('captions: output colour tags', False, output[-300:])
        return
    decoded = run_ff('-i', root / 'burn.mp4', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-')
    frames = np.frombuffer(decoded, dtype=np.uint8).reshape((-1, 640, 360, 3))
    mask = frames.max(axis=3) > 40
    ys, xs = np.where(mask[8])
    area = load('burn-report.json')['safe_area_pixels']
    inside = (len(xs) > 0 and xs.min() >= area[0] and xs.max() < area[2]
              and ys.min() >= area[1] and ys.max() < area[3] and not mask[2].any() and not mask[27].any())
    record('captions: tall burn timing and safe area', inside, str(area))
    yellow = (frames[:, :, :, 0] > 100) & (frames[:, :, :, 1] > 90) & (frames[:, :, :, 2] < 100)
    x1 = np.where(yellow[8])[1]
    x2 = np.where(yellow[18])[1]
    record('captions: repeated words highlight by index', len(x1) > 0 and len(x2) > 0 and x2.mean() > x1.mean() + 5,
           'yellow x means: {} {}'.format(float(x1.mean()) if len(x1) else None, float(x2.mean()) if len(x2) else None))
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=color_space,color_transfer,color_primaries,color_range', '-of', 'json',
                            str(root / 'burn.mp4')], capture_output=True, text=True)
    tags = json.loads(probe.stdout)['streams'][0]
    record('captions: output colour tags', all(tags.get(key) == 'bt709' for key in
           ('color_space', 'color_transfer', 'color_primaries')) and tags.get('color_range') == 'tv', str(tags))

    vfr = root / 'variable.mp4'
    run_ff('-f', 'lavfi', '-i', 'color=black:s=320x180:r=10:d=2', '-vf',
           r'setpts=if(lt(N\,5)\,N/(10*TB)\,(0.5+(N-5)*0.2)/TB)', '-fps_mode', 'vfr',
           '-c:v', 'libx264', '-pix_fmt', 'yuv420p', vfr)
    vfr_caption = root / 'vfr.srt'
    vfr_caption.write_text('1\n00:00:01,000 --> 00:00:02,000\nTime correctly\n', encoding='utf-8')
    code, output = tool('captions.py', 'burn', vfr, vfr_caption, '--out', root / 'vfr-burn.mp4')
    if code != 0:
        record('captions: variable frame presentation times retained', False, output[-400:])
    else:
        def frame_times(path):
            result = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_frames',
                                     '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'json', str(path)],
                                    capture_output=True, text=True)
            return [float(frame['best_effort_timestamp_time']) for frame in json.loads(result.stdout)['frames']]
        original = frame_times(vfr)
        rendered = frame_times(root / 'vfr-burn.mp4')
        data = run_ff('-i', root / 'vfr-burn.mp4', '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt',
                      'rgb24', '-')
        frames = np.frombuffer(data, dtype=np.uint8).reshape((-1, 180, 320, 3))
        visible = frames.max(axis=(1, 2, 3)) > 40
        clock_ok = len(original) == len(rendered) and np.allclose(original, rendered, atol=.001)
        signs = [bool(value) == (1 <= time < 2) for time, value in zip(rendered, visible)]
        record('captions: variable frame presentation times retained', clock_ok and all(signs),
               'source {} output {}; caption at PTS 1-2 s'.format(len(original), len(rendered)))

    impossible = save('impossible.json', [{'word': 'x' * 50, 'start': 0, 'end': 3}])
    code, output = tool('captions.py', 'build', impossible, '--out', root / 'impossible',
                        '--json', root / 'impossible-report.json')
    finding = load('impossible-report.json')['findings'][0]
    record('captions: infeasible segmentation identifies binding line limit', code == 1
           and 'characters per line' in finding['rule'] and finding['text'] == 'x' * 50, str(finding))
    different_shots = save('different-shots.json', [2.2])
    selects.write_text('"hello there"\n"hello there"\n', encoding='utf-8')
    code, output = tool('transcript_cut.py', cut_input, '--selects', selects, '--source', audio,
                        '--shots', different_shots, '--out', root / 'different-edit.json',
                        '--json', root / 'different-report.json')
    join = load('different-report.json')['joins'][0]
    record('transcript cut: distinct shots are not jump cuts', code == 0 and join['same_shot'] is False
           and join['jump_cut_candidate'] is False, str(join))

    early_words = save('early-words.json', [{'word': 'lengthy', 'start': .5, 'end': .55},
                                            {'word': 'phrase', 'start': .56, 'end': .6},
                                            {'word': 'other', 'start': .9, 'end': .95},
                                            {'word': 'words', 'start': 1, 'end': 1.05}])
    code, output = tool('captions.py', 'build', early_words, '--out', root / 'early',
                        '--min-duration', '.4', '--max-duration', '.8', '--json', root / 'early-report.json')
    early_result = load('early-report.json')
    early_cues = load('early.json')['cues'] if code == 0 else []
    record('captions: feasible segmentation uses available time before speech',
           code == 0 and len(early_cues) == 2 and early_cues[0]['start'] < .5,
           str(early_result))

    phrase = 'We see the red car, and the blue boat.'
    adjective_words = save('adjective.json', [{'word': word, 'start': i * .55, 'end': i * .55 + .35}
                                              for i, word in enumerate(phrase.split())])
    code, output = tool('captions.py', 'build', adjective_words, '--out', root / 'adjective',
                        '--line-length', '20', '--json', root / 'adjective-report.json')
    lines = [line for cue in load('adjective.json')['cues'] for line in cue['text'].split('\n')] if code == 0 else []
    record('captions: adjective and noun examples stay together', code == 0
           and any('red car' in line for line in lines) and any('blue boat' in line for line in lines), str(lines))

    from PIL import Image, ImageDraw, ImageFont
    test_frames = []
    fonts = [Path(scripts_dir).parent / 'assets/kit/fonts/MonaSansVF.woff2',
             Path('/System/Library/Fonts/Supplemental/Arial.ttf'),
             Path('C:/Windows/Fonts/arial.ttf'), Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    font = None
    for font_path in fonts:
        if font_path.is_file():
            try:
                font = ImageFont.truetype(str(font_path), 24)
                break
            except OSError:
                continue
    if font is None:
        raise RuntimeError('synthetic burned caption test requires a loadable font')
    for index in range(30):
        frame = Image.new('RGB', (320, 180), (0, 0, 0))
        if 12 <= index < 22:
            ImageDraw.Draw(frame).text((75, 125), 'Dark caption', font=font, fill=(50, 50, 50))
        test_frames.append(np.asarray(frame).tobytes())
    dark_video = root / 'dark-shift.mp4'
    run_ff('-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', '320x180', '-r', 10, '-i', '-',
           '-vf', 'scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,'
           'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv',
           '-c:v', 'libx264', '-crf', 12, dark_video, data=b''.join(test_frames))
    dark_srt = root / 'dark.srt'
    dark_srt.write_text('1\n00:00:01,000 --> 00:00:02,000\nDark caption\n', encoding='utf-8')
    code, output = tool('captions.py', 'check', dark_srt, '--burned', dark_video,
                        '--json', root / 'burned-report.json')
    visual = load('burned-report.json')
    event = visual['burned_screen']['cues'][0]
    rules = {item['rule'] for item in visual['findings']}
    record('captions: burned timing detects a two-frame shift', code == 1
           and event.get('appearance_offset_frames') == 2 and event.get('disappearance_offset_frames') == 2,
           str(event))
    record('captions: dark-on-dark contrast is flagged', code == 1 and 'contrast below 4.5' in rules,
           str(event.get('worst_contrast')))
    code, output = tool('captions.py', 'burn', video, repeated, '--out', root / 'avoid.mp4',
                        '--avoid', '0,0.5,1,0.15', '--json', root / 'avoid-report.json')
    avoid = load('avoid-report.json') if (root / 'avoid-report.json').exists() else {}
    moved = avoid.get('rendered_boxes', [{}])[0].get('box', [])
    record('captions: avoid box moves text clear within safe area', code == 0 and len(moved) == 4
           and moved[3] <= 320 and moved[1] >= avoid['safe_area_pixels'][1], str(moved))
    code, output = tool('captions.py', 'burn', video, repeated, '--out', root / 'conflict.mp4',
                        '--avoid', '0,0,1,1', '--json', root / 'conflict-report.json')
    conflict = load('conflict-report.json') if (root / 'conflict-report.json').exists() else {}
    record('captions: impossible avoid box reports chosen conflict', code == 1
           and any(item['rule'] == 'avoid conflict' and item.get('chosen_box')
                   for item in conflict.get('findings', [])), str(conflict.get('findings')))

    code, output = tool('captions.py', 'check', repeated, '--burned', video,
                        '--json', root / 'missing-burn-report.json')
    missing = load('missing-burn-report.json')
    record('captions: absent burn is reported', code == 1 and any('missing' in item['rule']
           for item in missing['findings']), str(missing['findings']))
    code, output = tool('captions.py', 'check', repeated, '--burned', root / 'burn.mp4',
                        '--json', root / 'good-burn-report.json')
    good = load('good-burn-report.json')
    screen = good['burned_screen']['cues'][0]
    record('captions: aligned bright burn passes visual screen', code == 0
           and screen.get('worst_contrast', {}).get('ratio', 0) >= 4.5
           and screen.get('appearance_offset_frames') == 0 and screen.get('disappearance_offset_frames') == 0,
           str(screen))
