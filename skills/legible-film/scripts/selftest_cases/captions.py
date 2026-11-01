"""Known-answer tests for transcript cuts and caption build, check and burn."""
import json
from pathlib import Path
import subprocess

import numpy as np


def check_burn_quality(tool, record, j, scripts_dir):
    """Measure caption-free pixels after standalone and assembled caption burns."""
    import importlib.util
    import re

    root = Path(j('caption-quality'))
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'source.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=s=640x360:r=15:d=1.2', '-vf', 'noise=alls=8:allf=t+u',
                    '-c:v', 'ffv1', '-threads', '1', str(source)], check=True, capture_output=True)
    srt = root / 'captions.srt'
    srt.write_text('1\n00:00:00,100 --> 00:00:01,000\nHello there\n', encoding='utf-8')
    edit = {'version': 1, 'fps': 15, 'size': [640, 360], 'sources': {'v': str(source)},
            'picture': [{'src': 'v', 'in': 0, 'out': 1.2}]}
    results = {}
    for label, overlays in (('plain', []), ('burned', [{'kind': 'captions', 'file': srt.name}]),
                            ('twice', [{'kind': 'captions', 'file': srt.name}] * 2)):
        edit_path = root / (label + '.json')
        edit_path.write_text(json.dumps({**edit, 'overlays': overlays}), encoding='utf-8')
        results[label] = tool('assemble.py', edit_path, '--out', root / (label + '.mp4'))
    default_code, default_out = tool('captions.py', 'burn', root / 'plain.mp4', srt,
                                     '--out', root / 'standalone.mp4', '--json', root / 'standalone-report.json')
    lossless_code, lossless_out = tool('captions.py', 'burn', root / 'plain.mp4', srt,
                                       '--crf', '0', '--out', root / 'lossless.mp4',
                                       '--json', root / 'lossless-report.json')

    def psnr(candidate):
        if not candidate.is_file() or not (root / 'plain.mp4').is_file():
            return 0.0
        graph = ('[0:v]crop=640:180:0:0,settb=AVTB,setpts=PTS-STARTPTS[a];'
                 '[1:v]crop=640:180:0:0,settb=AVTB,setpts=PTS-STARTPTS[b];[a][b]psnr')
        measured = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(candidate), '-i', str(root / 'plain.mp4'),
                                   '-lavfi', graph, '-f', 'null', '-'], capture_output=True, text=True)
        match = re.search(r'average:([0-9.]+|inf)', measured.stderr)
        return float(match.group(1)) if measured.returncode == 0 and match else 0.0

    one = psnr(root / 'burned.mp4')
    two = psnr(root / 'twice.mp4')
    standalone = psnr(root / 'standalone.mp4')
    lossless = psnr(root / 'lossless.mp4')
    print(f'caption-free top-half PSNR: assembled={one:.2f} dB, twice={two:.2f} dB, '
          f'standalone={standalone:.2f} dB, intermediate={lossless:.2f} dB')
    record('captions: assembly retains detail through one and two caption passes',
           all(results[key][0] in (0, 1) for key in results) and min(one, two) >= 45,
           str((one, two, {key: value[0] for key, value in results.items()})))
    record('captions: standalone default retains detail and lossless quality can be requested',
           default_code in (0, 1) and lossless_code in (0, 1) and standalone >= 45 and lossless >= 60,
           str((standalone, lossless, default_out[-200:], lossless_out[-200:])))
    standalone_path = root / 'standalone.mp4'
    lossless_path = root / 'lossless.mp4'
    sizes = [path.stat().st_size if path.is_file() else 0 for path in (standalone_path, lossless_path)]
    record('captions: standalone default is smaller than a lossless intermediate',
           0 < sizes[0] < sizes[1], str(sizes))
    reports = [json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {} for path in
               (root / 'standalone-report.json', root / 'lossless-report.json')]
    qualities = [report.get('video_crf') for report in reports]
    record('captions: burn reports the quality actually requested',
           qualities == [14, 0], str(qualities))
    streams = []
    timestamps = []
    for name in ('plain', 'burned', 'twice'):
        path = root / (name + '.mp4')
        probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                '-show_entries', 'stream=codec_name,level,avg_frame_rate,nb_read_frames,'
                                'color_space,color_transfer,color_primaries:frame=best_effort_timestamp_time',
                                '-of', 'json', str(path)], capture_output=True, text=True)
        data = json.loads(probe.stdout or '{}') if probe.returncode == 0 else {}
        streams.append((data.get('streams') or [{}])[0])
        timestamps.append([float(frame['best_effort_timestamp_time']) for frame in data.get('frames', [])
                           if 'best_effort_timestamp_time' in frame])
    record('captions: final encodes retain the frame grid, H.264 level and BT.709 tags',
           all(row.get('codec_name') == 'h264' and row.get('avg_frame_rate') == '15/1'
               and row.get('nb_read_frames') == '18' and row.get('level') == streams[0].get('level')
               and all(row.get(key) == 'bt709' for key in ('color_space', 'color_transfer', 'color_primaries'))
               for row in streams) and all(len(times) == 18 and all(abs(value - i / 15) < .001
               for i, value in enumerate(times)) for times in timestamps), str((streams, timestamps)))
    ntsc_edit = {**edit, 'fps': 29.97, 'picture': [{'src': 'v', 'in': 0, 'out': .6}],
                 'overlays': [{'kind': 'captions', 'file': srt.name}]}
    ntsc_edit_path = root / 'ntsc.json'
    ntsc_edit_path.write_text(json.dumps(ntsc_edit), encoding='utf-8')
    ntsc_code, ntsc_output = tool('assemble.py', ntsc_edit_path, '--out', root / 'ntsc.mp4')
    ntsc_probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=avg_frame_rate,nb_read_frames:'
                                 'frame=best_effort_timestamp_time', '-of', 'json', str(root / 'ntsc.mp4')],
                                capture_output=True, text=True)
    ntsc_data = json.loads(ntsc_probe.stdout or '{}') if ntsc_probe.returncode == 0 else {}
    ntsc_stream = (ntsc_data.get('streams') or [{}])[0]
    ntsc_times = [float(frame['best_effort_timestamp_time']) for frame in ntsc_data.get('frames', [])
                  if 'best_effort_timestamp_time' in frame]
    record('captions: final encode retains the 30000/1001 frame grid',
           ntsc_code in (0, 1) and ntsc_stream.get('avg_frame_rate') == '30000/1001'
           and ntsc_stream.get('nb_read_frames') == '18' and len(ntsc_times) == 18
           and all(abs(value - i * 1001 / 30000) < .001 for i, value in enumerate(ntsc_times)),
           str((ntsc_stream, ntsc_times, ntsc_output[-300:])))
    spec = importlib.util.spec_from_file_location('caption_frame_cap', Path(scripts_dir) / 'assemble.py')
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)
    try:
        assembler.cap_caption_encode('ffmpeg', root / 'plain.mp4', root / 'short-output.mp4', 640, 360, 15, 19)
        short_error = ''
    except ValueError as error:
        short_error = str(error)
    record('captions: final encoder refuses a missing input frame',
           '18 frames' in short_error and 'expected 19' in short_error, short_error)
    code, output = tool('captions.py', 'burn', '--help')
    record('captions: burn help states the standalone quality', code == 0 and '--crf' in output
           and '14' in output, output[-300:])


def check_plate_hugs_text(record, scripts_dir):
    """A short caption's plate is about as wide as its words plus padding, not the whole safe area; a long one still
    fits inside the safe area."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('plate_case', str(Path(scripts_dir) / 'captions.py'))
    captions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(captions)
    safe = (64, 300, 1216, 520)
    font = next(str(path) for path in captions.caption_font_candidates() if path.is_file())
    short, short_box = captions.render_caption(1280, 534, safe, {'text': 'Alright, fine.'}, None, font, None, True)[:2]
    long, long_box = captions.render_caption(1280, 534, safe, {'text': 'We need to know what made the spots in the '
                                                                       'early universe'}, None, font, None, True)[:2]
    alpha = short.getchannel('A')
    ink = short.convert('L').point(lambda value: 255 if value > 200 else 0).getbbox()
    width = short_box[2] - short_box[0]
    record('captions: a short caption\'s plate hugs its words; a long one stays inside the safe area',
           width < 0.5 * (safe[2] - safe[0]) and ink is not None and short_box[0] <= ink[0] - 8
           and short_box[2] >= ink[2] + 8 and long_box[0] >= safe[0] and long_box[2] <= safe[2]
           and long_box[2] - long_box[0] > width and alpha.getbbox()[0] >= short_box[0] - 1,
           str((short_box, ink, long_box)))


def check_caption_house_style(tool, record, j, scripts_dir):
    """Known answers for estimated timing, profile review, completeness and input custody."""
    import hashlib
    import importlib.util
    import os

    root = Path(j('caption-house-style'))
    root.mkdir(parents=True, exist_ok=True)

    def save(name, data):
        path = root / name
        path.write_text(json.dumps(data), encoding='utf-8')
        return path

    def check(name, source, *args):
        report = root / (name + '-report.json')
        code, output = tool('captions.py', 'check', source, *args, '--json', report)
        data = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
        return code, data, output

    def rules(report, group):
        return [item.get('rule') for item in report.get(group, [])]

    cues = [{'start': 2 * n, 'end': 2 * n + 1, 'text': text}
            for n, text in enumerate(('alpha', 'bravo', 'charlie'))]
    caption = save('offset-captions.json', {'cues': cues})
    words = [{'start': cue['start'] + 5, 'end': cue['end'] + 5, 'text': cue['text'], 'estimated': True}
             for cue in cues]
    estimated = save('offset-estimated.json', {'words': words})
    code, report, output = check('offset-estimated', caption, '--words', estimated)
    apparent = [item for item in report.get('review', []) if 'estimated' in item.get('rule', '')
                and item.get('offset_s') == -5]
    record('captions: estimated whole-file shift is a listening prompt, not a finding',
           code == 0 and not report.get('findings') and apparent
           and report.get('timing_screen', {}).get('offset_basis') == 'estimated'
           and report.get('timing_screen', {}).get('coverage', {}).get('matched') == 3, str(report) + output[-200:])
    measured = save('offset-measured.json', {'words': [{**word, 'estimated': False} for word in words]})
    code, report, output = check('offset-measured', caption, '--words', measured)
    offset = [item for item in report.get('findings', []) if item.get('rule') == 'captions offset from the dialogue']
    record('captions: three measured shifts produce a finding with its basis',
           code == 1 and len(offset) == 1 and offset[0].get('offset_s') == -5
           and report.get('timing_screen', {}).get('offset_basis') == 'measured', str(report) + output[-200:])
    mixed = save('offset-mixed.json', {'words': [{**word, 'estimated': n == 2} for n, word in enumerate(words)]})
    code, report, output = check('offset-mixed', caption, '--words', mixed)
    record('captions: fewer than three fully measured matches cannot prove an offset',
           code == 0 and 'captions offset from the dialogue' not in rules(report, 'findings')
           and report.get('timing_screen', {}).get('offset_basis') == 'estimated', str(report) + output[-200:])
    multi_cues = [{'start': 2 * n, 'end': 2 * n + 1, 'text': text + ' word'}
                  for n, text in enumerate(('alpha', 'bravo', 'charlie'))]
    multi_words = []
    for cue in multi_cues:
        multi_words.extend([{'text': cue['text'].split()[0], 'start': cue['start'] + 5,
                             'end': cue['start'] + 5.5, 'estimated': False},
                            {'text': 'word', 'start': cue['start'] + 5.5,
                             'end': cue['end'] + 5, 'estimated': True}])
    multi_caption = save('offset-one-estimated-edge.json', {'cues': multi_cues})
    multi_source = save('offset-one-estimated-edge-words.json', {'words': multi_words})
    code, report, output = check('offset-one-estimated-edge', multi_caption, '--words', multi_source)
    record('captions: a measured first edge cannot make an estimated last edge measured',
           code == 0 and not report.get('findings')
           and report.get('timing_screen', {}).get('offset_basis') == 'estimated', str(report) + output[-200:])
    mixed_cues = [{'start': 10 * n, 'end': 10 * n + 1, 'text': text}
                  for n, text in enumerate(('alpha', 'bravo', 'charlie', 'delta', 'echo', 'foxtrot'))]
    mixed_words = [{'start': cue['start'] + (5 if n >= 3 else 0),
                    'end': cue['end'] + (5 if n >= 3 else 0), 'text': cue['text'], 'estimated': n >= 3}
                   for n, cue in enumerate(mixed_cues)]
    mixed_captions = save('offset-estimated-subset.json', {'cues': mixed_cues})
    mixed_source = save('offset-estimated-subset-words.json', {'words': mixed_words})
    code, report, output = check('offset-estimated-subset', mixed_captions, '--words', mixed_source)
    record('captions: a shifted estimated subset does not displace aligned measured captions',
           code == 0 and not report.get('findings')
           and report.get('timing_screen', {}).get('offset_basis') == 'estimated'
           and report.get('timing_screen', {}).get('coverage', {}).get('matched') == 6
           and any(item.get('offset_s') == -5 for item in report.get('review', [])), str(report) + output[-200:])

    empty = save('empty.json', {'cues': []})
    code, report, output = check('empty', empty, '--words', measured)
    record('captions: an empty cue list over dialogue is a finding and incomplete',
           code == 1 and report.get('complete') is False and report.get('complete_reasons')
           and report.get('timing_screen', {}).get('coverage', {}).get('matched') == 0
           and rules(report, 'findings'), str(report) + output[-200:])
    empty_srt = root / 'empty.srt'
    empty_srt.write_text('', encoding='utf-8')
    code, report, output = check('empty-srt', empty_srt, '--words', measured)
    record('captions: an empty SRT over dialogue is checked as an empty cue list',
           code == 1 and report.get('complete') is False and report.get('cues') == 0, str(report) + output[-200:])
    short = save('short.json', {'cues': [{'start': 0, 'end': 1.5, 'text': 'Hello there'}]})
    spoken = save('short-words.json', {'words': [{'text': 'Hello', 'start': 0, 'end': .5},
                                                  {'text': 'there', 'start': .5, 'end': 1.5}]})
    code, report, output = check('complete', short, '--words', spoken, '--strict')
    record('captions: strict accepts complete word coverage without findings or prompts',
           code == 0 and report.get('complete') is True and not report.get('complete_reasons'), str(report) + output)
    with_filler = save('short-words-with-filler.json', {'words': [
        {'text': 'Hello', 'start': 0, 'end': .5}, {'text': 'there', 'start': .5, 'end': 1.5},
        {'text': 'um', 'start': 2, 'end': 2.2}]})
    code, report, output = check('uncaptioned-filler', short, '--words', with_filler, '--strict')
    coverage = report.get('timing_screen', {}).get('coverage', {})
    record('captions: an omitted filler keeps strict completeness false without changing legacy coverage',
           code == 1 and report.get('complete') is False and coverage.get('words') == 2
           and coverage.get('all_dialogue_words') == 3 and coverage.get('all_dialogue_matched') == 2,
           str(report) + output[-200:])
    with_filler_caption = save('short-with-filler.json', {'cues': [
        {'start': 0, 'end': 2.2, 'text': 'Hello there um'}]})
    code, report, output = check('captioned-filler', with_filler_caption, '--words', with_filler, '--strict')
    record('captions: a captioned filler permits strict completeness',
           code == 0 and report.get('complete') is True
           and report.get('timing_screen', {}).get('coverage', {}).get('all_dialogue_matched') == 3,
           str(report) + output[-200:])
    filler_only = save('filler-only.json', {'words': [{'text': 'um', 'start': 1, 'end': 1.5}]})
    code, report, output = check('empty-filler', empty, '--words', filler_only)
    record('captions: no captions over a filler-only word basis is still a finding',
           code == 1 and report.get('complete') is False and 'no captions for dialogue' in rules(report, 'findings'),
           str(report) + output[-200:])
    code, report, output = check('no-basis', short, '--strict')
    record('captions: strict rejects a missing word basis',
           code == 1 and report.get('complete') is False and report.get('complete_reasons'), str(report) + output)
    code, report, output = check('uncovered', short, '--words', measured, '--strict')
    record('captions: strict rejects uncovered words and reports why',
           code == 1 and report.get('complete') is False and report.get('complete_reasons'), str(report) + output)

    styled = root / 'styled.srt'
    styled.write_text('1\n00:00:00,000 --> 00:00:01,500\n'
                      '<font color="#ff0000"><i>Hello</i> <b>there</b></font>\n', encoding='utf-8')
    code, report, output = check('markup', styled, '--words', spoken, '--line-length', '11', '--cps', '8', '--strict')
    record('captions: speaker colour, italic and bold tags are neither words nor characters',
           code == 0 and report.get('complete') is True and not report.get('findings')
           and not report.get('review'), str(report) + output[-200:])

    house_cues = save('house.json', {'cues': [{'start': 0, 'end': .5, 'text': 'Short'},
                                              {'start': .5, 'end': 1.5, 'text': 'Next card'},
                                              {'start': 1.4, 'end': 2.4, 'text': 'Overlap now'}]})
    profile_data = {'limits': {'cps': 20, 'line_length': 42, 'lines': 2, 'min_duration': .8,
                               'max_duration': 7, 'gap': 0, 'margin': .25},
                    'exceptions': [{'rule': 'minimum duration', 'start': 0, 'end': .5, 'text': 'Short',
                                    'note': 'deliberate fragment', 'reviewer': 'Editor'},
                                   {'rule': 'overlap', 'start': 1.4, 'end': 2.4, 'text': 'Overlap now',
                                    'note': 'reviewed overlap', 'reviewer': 'Editor'},
                                   {'rule': 'cps', 'start': 9, 'note': 'old event', 'reviewer': 'Editor'}]}
    profile = save('house-profile.json', profile_data)
    code, report, output = check('house', house_cues, '--profile', profile)
    accepted = report.get('accepted', [])
    record('captions: reviewed exceptions retain findings, prompts, note and reviewer in accepted',
           code == 0 and {item.get('rule') for item in accepted} == {'minimum duration', 'overlap'}
           and all(item.get('note') and item.get('reviewer') for item in accepted)
           and 'overlap' not in rules(report, 'findings'), str(report) + output[-200:])
    record('captions: an unused reviewed exception remains a review prompt',
           'unused profile exception' in rules(report, 'review') and report.get('complete') is False,
           str(report) + output[-200:])
    metadata = report.get('profile', {}) or {}
    record('captions: profile path, content hash and effective limits are recorded',
           metadata.get('path') == str(profile)
           and metadata.get('sha256') == hashlib.sha256(profile.read_bytes()).hexdigest()
           and report.get('limits') == profile_data['limits'], str(report) + output[-200:])
    code, report, output = check('override', house_cues, '--profile', profile, '--gap', '.04')
    record('captions: command-line limits override profile limits',
           report.get('limits', {}).get('gap') == .04 and 'gap' in rules(report, 'review'), str(report) + output[-200:])
    unreviewed = save('unreviewed.json', {'limits': {'gap': 0}, 'exceptions': []})
    code, report, output = check('unreviewed', house_cues, '--profile', unreviewed)
    record('captions: an overlap remains a finding without an exact exception',
           code == 1 and 'overlap' in rules(report, 'findings'), str(report) + output[-200:])
    wrong_text = save('wrong-text.json', {'exceptions': [{'rule': 'overlap', 'start': 1.4, 'end': 2.4,
                                                            'text': 'different',
                                                            'note': 'old text', 'reviewer': 'Editor'}]})
    code, report, output = check('wrong-text', house_cues, '--profile', wrong_text)
    record('captions: an exception with changed text does not accept the overlap',
           code == 1 and 'overlap' in rules(report, 'findings')
           and 'unused profile exception' in rules(report, 'review'), str(report) + output[-200:])
    duplicate_start = save('duplicate-start.json', {'cues': [{'start': 0, 'end': .5, 'text': 'First'},
                                                             {'start': 0, 'end': .5, 'text': 'Second'}]})
    identical = save('identical-cues.json', {'cues': [{'start': 0, 'end': .5, 'text': 'First'},
                                                      {'start': 0, 'end': .5, 'text': 'First'}]})
    ambiguous_profile = save('ambiguous-exception.json', {'exceptions': [
        {'rule': 'minimum duration', 'start': 0, 'end': .5, 'text': 'First', 'note': 'one reviewed fragment',
         'reviewer': 'Editor'}]})
    code, report, output = check('ambiguous-exception', identical, '--profile', ambiguous_profile)
    record('captions: an exception cannot accept two identical captions with the same start',
           not report.get('accepted') and rules(report, 'review').count('minimum duration') == 2
           and 'unused profile exception' in rules(report, 'review'), str(report) + output[-200:])
    specific_profile = save('specific-exception.json', {'exceptions': [
        {'rule': 'minimum duration', 'start': 0, 'end': .5, 'text': 'First', 'note': 'reviewed',
         'reviewer': 'Editor'}]})
    code, report, output = check('specific-exception', duplicate_start, '--profile', specific_profile)
    record('captions: exception text disambiguates captions with the same start',
           len(report.get('accepted', [])) == 1 and report['accepted'][0].get('cue') == 1
           and rules(report, 'review').count('minimum duration') == 1, str(report) + output[-200:])
    # From an editor's test of 2.0: an exception keyed by rule and start alone accepted a different stale word
    # after the caption at that start was edited.
    stale_words = save('stale-words.json', {'words': [{'text': 'we', 'start': .2, 'end': .4},
                                                      {'text': 'found', 'start': .4, 'end': .6},
                                                      {'text': 'the', 'start': .6, 'end': .8},
                                                      {'text': 'folder', 'start': .8, 'end': 1.0}]})
    blue = save('blue.json', [{'start': 0, 'end': 1.0, 'text': 'we found the blue folder'}])
    red = save('red.json', [{'start': 0, 'end': 1.0, 'text': 'we found the red folder'}])
    loose = save('start-only.json', {'limits': {'cps': 100, 'min_duration': .1, 'gap': 0}, 'exceptions': [
        {'rule': 'caption words not in the dialogue', 'start': 0, 'note': 'reviewed blue', 'reviewer': 'test'}]})
    code, report, output = check('start-only', blue, '--words', stale_words, '--profile', loose, '--strict')
    unused = [item for item in report.get('review', []) if item.get('rule') == 'unused profile exception']
    record('captions: an exception without the caption text and end no longer applies, and says what to add',
           code == 1 and report.get('complete') is False and not report.get('accepted')
           and 'caption words not in the dialogue' in rules(report, 'findings')
           and unused and 'text and end' in unused[0].get('reason', ''), str(report) + output[-300:])
    finding = next((item for item in report.get('findings', [])
                    if item.get('rule') == 'caption words not in the dialogue'), {})
    bound = save('bound.json', {'limits': {'cps': 100, 'min_duration': .1, 'gap': 0}, 'exceptions': [
        {'rule': 'caption words not in the dialogue', 'start': 0, 'end': 1.0, 'text': 'we found the blue folder',
         'fingerprint': finding.get('fingerprint', 'missing'), 'note': 'reviewed blue', 'reviewer': 'test'}]})
    code, report, output = check('bound-blue', blue, '--words', stale_words, '--profile', bound, '--strict')
    record('captions: an exception naming the caption and its fingerprint accepts the reviewed result',
           code == 0 and report.get('complete') is True and len(report.get('accepted', [])) == 1
           and report['accepted'][0].get('fingerprint') == finding.get('fingerprint')
           and len(finding.get('fingerprint', '')) == 16, str(report) + output[-300:])
    code, report, output = check('bound-red', red, '--words', stale_words, '--profile', bound, '--strict')
    record('captions: the same exception reopens when the caption at that start is edited (blue to red)',
           code == 1 and report.get('complete') is False and not report.get('accepted')
           and 'caption words not in the dialogue' in rules(report, 'findings'), str(report) + output[-300:])
    changed_basis = save('changed-basis.json', {'words': [{'text': 'we', 'start': .2, 'end': .4},
                                                          {'text': 'found', 'start': .4, 'end': .6},
                                                          {'text': 'a', 'start': .6, 'end': .8},
                                                          {'text': 'folder', 'start': .8, 'end': 1.0}]})
    code, report, output = check('bound-basis', blue, '--words', changed_basis, '--profile', bound, '--strict')
    unused = [item for item in report.get('review', []) if item.get('rule') == 'unused profile exception']
    record('captions: a fingerprinted exception reopens when the word basis changes the result',
           code == 1 and not report.get('accepted') and unused
           and 'fingerprint' in unused[0].get('reason', ''), str(report) + output[-300:])
    one_line = save('one-line.json', {'limits': {'lines': 1}, 'exceptions': []})
    two_lines = save('two-lines.json', {'cues': [{'start': 0, 'end': 2, 'text': 'one line\nsecond line'}]})
    code, report, output = check('one-line', two_lines, '--profile', one_line)
    record('captions: a profile line-count limit is enforced',
           code == 1 and 'lines' in rules(report, 'findings'), str(report) + output[-200:])
    bad = save('bad-profile.json', {'limits': {'gap': -1}, 'exceptions': []})
    code, _, output = check('bad-profile', short, '--profile', bad)
    record('captions: invalid profile limits cannot silently weaken a check', code == 2, output[-200:])
    build_report = root / 'build-report.json'
    code, output = tool('captions.py', 'build', spoken, '--out', root / 'one-line-build', '--profile', one_line,
                        '--json', build_report)
    built = json.loads(build_report.read_text(encoding='utf-8')) if build_report.is_file() else {}
    generated = root / 'one-line-build.json'
    events = json.loads(generated.read_text(encoding='utf-8')).get('cues', []) if generated.is_file() else []
    record('captions: build applies and records the profile line-count limit',
           code == 0 and built.get('limits', {}).get('lines') == 1 and events
           and all('\n' not in cue['text'] for cue in events), str(built) + output[-200:])
    spec = importlib.util.spec_from_file_location('lf_caption_direct_build', Path(scripts_dir) / 'captions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    direct_args = module.argument_parser().parse_args(['build', str(spoken), '--out', str(root / 'direct-build')])
    direct = module.run_build(direct_args)
    record('captions: direct run_build callers retain the default rule limits',
           direct.get('cues', 0) > 0 and direct.get('limits', {}).get('gap') == .04
           and (root / 'direct-build.json').is_file(), str(direct))

    original = '1\n00:00:00,000 --> 00:00:01,000\nHello there\n'
    for name, alias in (('same', False), ('alternate spelling', True)):
        source = root / ('collision-' + name.replace(' ', '-') + '.srt')
        source.write_text(original, encoding='utf-8')
        target = str(root) + os.sep + '.' + os.sep + source.name if alias else str(source)
        code, output = tool('captions.py', 'check', source, '--json', target)
        record('captions: report refuses input collision (' + name + ')',
               code == 2 and source.read_text(encoding='utf-8') == original and 'input' in output.lower(),
               output[-200:])
    source = root / 'hardlink.srt'
    link = root / 'hardlink-report.json'
    source.write_text(original, encoding='utf-8')
    try:
        os.link(source, link)
        linked = True
    except OSError as error:
        linked = False
        print('SKIP  captions: hard-link collision (' + str(error) + ')')
    if linked:
        code, output = tool('captions.py', 'check', source, '--json', link)
        record('captions: report refuses a hard-linked input',
               code == 2 and source.read_text(encoding='utf-8') == original and 'input' in output.lower(),
               output[-200:])
    linked_words = save('linked-build-words.json', {'words': [{'text': 'Hello', 'start': 0, 'end': 1}]})
    linked_sidecar = root / 'linked-build.srt'
    try:
        os.link(linked_words, linked_sidecar)
        linked = True
    except OSError as error:
        linked = False
        print('SKIP  captions: hard-linked build output (' + str(error) + ')')
    if linked:
        before = linked_words.read_bytes()
        code, output = tool('captions.py', 'build', linked_words, '--out', root / 'linked-build')
        record('captions: build sidecar cannot replace a hard-linked word file',
               code == 2 and linked_words.read_bytes() == before and 'is the input' in output.lower(), output[-200:])
    for command, source_arg, output_flag in (('build', spoken, '--json'), ('check', short, '--json')):
        before = source_arg.read_bytes()
        args = ('--out', root / 'collision-build') if command == 'build' else ()
        code, output = tool('captions.py', command, source_arg, *args, output_flag, source_arg)
        record('captions: ' + command + ' report cannot replace its input',
               code == 2 and source_arg.read_bytes() == before, output[-200:])
    for flag, source_arg in (('--words', measured), ('--profile', profile), ('--audio', spoken), ('--burned', spoken)):
        before = source_arg.read_bytes()
        code, output = tool('captions.py', 'check', short, flag, source_arg, '--json', source_arg)
        record('captions: check report cannot replace ' + flag[2:] + ' input',
               code == 2 and source_arg.read_bytes() == before and 'is the input' in output.lower(), output[-200:])
    for output_flag, index in (('--out', 0), ('--out', 1), ('--json', 0), ('--json', 1)):
        video = root / ('dummy-' + output_flag[2:] + str(index) + '.mp4')
        text = root / ('dummy-' + output_flag[2:] + str(index) + '.srt')
        video.write_bytes(b'video input')
        text.write_text(original, encoding='utf-8')
        target = (video, text)[index]
        before = target.read_bytes()
        args = ('--out', target) if output_flag == '--out' else ('--out', root / 'unused.mp4', '--json', target)
        code, output = tool('captions.py', 'burn', video, text, *args)
        record('captions: burn ' + output_flag + ' cannot replace ' + ('video' if index == 0 else 'captions'),
               code == 2 and target.read_bytes() == before and 'is the input' in output.lower(), output[-200:])
    code, output = tool('captions.py', 'burn', root / 'dummy-out0.mp4', root / 'dummy-out0.srt',
                        '--out', root / 'same-output', '--json', root / 'same-output')
    record('captions: burn report cannot replace the output video',
           code == 2 and 'is the input' in output.lower(), output[-200:])


def run_captions_cases(tool, record, j, scripts_dir):
    check_plate_hugs_text(record, scripts_dir)
    """Exercise reading constraints, timing screens and decoded picture pixels."""
    check_caption_house_style(tool, record, j, scripts_dir)
    check_burn_quality(tool, record, j, scripts_dir)
    check_zero_length_word(tool, record, j)
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
    code, output = tool('captions.py', 'build', source, '--out', root / 'sentence-out',
                        '--json', root / 'sentence-report.json')
    if code == 0:
        cues = load('sentence-out.json')['cues']
        srt_code, _ = tool('captions.py', 'check', root / 'sentence-out.srt')
        vtt_code, _ = tool('captions.py', 'check', root / 'sentence-out.vtt')
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
    record('captions: an intentional one-word caption exits 0 with its duration as a review prompt; the speech '
           'around it that no caption carries is named',
           code == 0 and not report['findings'] and [item['rule'] for item in report['review']]
           == ['minimum duration', 'speech with no caption', 'speech with no caption'], str(report))
    # Cases from an independent review: nearby speech never clears a caption over silence; repeated words match
    # one to one, in order; intentional lead-ins are prompts, not a file offset; sound descriptions and speaker
    # labels are not dialogue; overlapping speakers load; a long file stays fast.
    import importlib.util
    import time
    spec = importlib.util.spec_from_file_location('lf_captions_review', Path(scripts_dir) / 'captions.py')
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)

    def word(text, start, end):
        return {'text': text, 'start': start, 'end': end}

    def caption(start, end, text):
        return {'start': start, 'end': end, 'text': text}
    found, _, _ = cap.check_word_timing([caption(1, 1.3, 'right')], [word('right', 0, .3)], .1)
    record('captions: a caption over silence is flagged though the same word is spoken nearby',
           [item['rule'] for item in found] == ['caption over no matching speech'], str(found))
    found, prompts, regions = cap.check_word_timing([caption(0, .4, 'right'), caption(2, 2.4, 'right')],
                                                    [word('right', 0, .3), word('right', 2, 2.3)], .1)
    record('captions: repeated words match one to one, in order', not found and regions == [(0, .3), (2, 2.3)],
           str(regions))
    speech = [word('one', 2, 2.5), word('two', 5, 5.5), word('three', 8, 8.5)]
    found, prompts, _ = cap.check_word_timing([caption(1, 2.5, 'one'), caption(4, 5.5, 'two'),
                                               caption(7, 8.5, 'three')], speech, .1)
    record('captions: intentional lead-ins are entrance prompts, not a file offset',
           not found and [item['rule'] for item in prompts] == ['enters before the speech'] * 3, str(prompts))
    found, prompts, _ = cap.check_word_timing(
        [caption(0, 1, '\u266a'), caption(2, 3, '[laughs]'), caption(4, 5, '[laughs] Yes'),
         caption(6, 7, 'DR. LEE: It works.')], [word('Yes', 4.2, 4.5), word('It', 6.1, 6.2), word('works.', 6.3, 6.7)],
        .5)
    record('captions: music, sound descriptions and speaker labels are not dialogue',
           not found and [(item['cue'], item['rule']) for item in prompts]
           == [(1, 'not dialogue: check by listening'), (2, 'not dialogue: check by listening')], str(prompts))
    overlapping = save('overlapping.json', [{'word': 'Hello', 'start': 1.0, 'end': 1.5},
                                            {'word': 'Hi', 'start': 1.2, 'end': 1.6}])
    both = root / 'overlapping.srt'
    both.write_text(srt([(1.0, 1.7, 'Hello'), (1.8, 2.2, 'Hi')]), encoding='utf-8')
    code, output = tool('captions.py', 'check', both, '--words', overlapping, '--json', root / 'overlap-report.json')
    report = load('overlap-report.json')
    record('captions: overlapping speakers load and match', code == 0 and not report['findings'], str(report))
    many = [word('right', k * 1.0, k * 1.0 + .3) for k in range(10000)]
    began = time.perf_counter()
    found, prompts, _ = cap.check_word_timing([caption(k * 1.0, k * 1.0 + .4, 'right') for k in range(10000)], many, .1)
    elapsed = time.perf_counter() - began
    record('captions: ten thousand captions check in under five seconds', not found and elapsed < 5,
           f'{elapsed:.2f} s')
    # Shapes from a professional's real export (synthetic text here): Premiere SRTs carry colour tags, transcripts
    # carry empty rows where the transcriber returned no word, and some word times are marked estimated.
    styled = root / 'styled.srt'
    styled.write_text(srt([(1.0, 2.0, '<font color="#ffffff">It felt easy &amp; quick.</font>'),
                           (3.0, 3.5, '<font color="#6ec8ff">Physical?</font>')]), encoding='utf-8')
    styled_words = save('styled-words.json', {'words': [
        {'word': 'It', 'start': 1.0, 'end': 1.15}, {'word': '', 'start': 1.15, 'end': 1.2},
        {'word': 'felt', 'start': 1.2, 'end': 1.45}, {'word': 'easy', 'start': 1.5, 'end': 1.7},
        {'word': 'quick.', 'start': 1.72, 'end': 1.95},
        {'word': 'Physical?', 'start': 2.5, 'end': 3.4, 'estimated': True}]})
    code, output = tool('captions.py', 'check', styled, '--words', styled_words, '--json', root / 'styled-report.json')
    report = load('styled-report.json')
    rules = {item['rule'] for item in report['findings']}
    record('captions: styling tags and entities are neither words nor characters',
           code == 0 and not rules and 'line length' not in report['summary']['findings'], str(report['findings']))
    record('captions: empty transcript rows are skipped and counted',
           report['timing_screen'].get('empty_rows_ignored') == 1, str(report['timing_screen'].get('empty_rows_ignored')))
    prompts = [(item.get('cue'), item['rule']) for item in report['review']]
    record('captions: an estimated word time is not measured as a caption entrance',
           (2, 'enters after the speech starts') not in prompts and any(
               item['rule'] == 'entrances or exits not measured: estimated word times' and item['cues'] == [2]
               for item in report['review']), str(report['review']))
    record('captions: the report summarises findings and review prompts by rule',
           report['summary']['review'].get('minimum duration') == 1, str(report['summary']))

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
    code, output = tool('captions.py', 'build', impossible, '--out', root / 'impossible-out',
                        '--json', root / 'impossible-report.json')
    finding = load('impossible-report.json')['findings'][0]
    long_cues = load('impossible-out.json')['cues'] if (root / 'impossible-out.json').exists() else []
    record('captions: an unbreakable word is retained with a line-length finding', code == 1
           and finding['rule'] == 'line length' and len(long_cues) == 1
           and long_cues[0]['text'] == 'x' * 50, str(finding))
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
    code, output = tool('captions.py', 'build', adjective_words, '--out', root / 'adjective-out',
                        '--line-length', '20', '--json', root / 'adjective-report.json')
    lines = [line for cue in load('adjective-out.json')['cues'] for line in cue['text'].split('\n')] if code == 0 else []
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

    # Word fields travel through build: transcript IDs and speakers reach captions.json; a timed line split into
    # estimated words gives each piece the line's ID and a part number.
    texts = ['Fields', 'travel', 'with', 'every', 'word', 'here']
    words = [{'id': f'int_01-w{number + 1:06d}', 'text': text, 'start': 0.5 + number * 0.4,
              'end': 0.8 + number * 0.4, 'speaker': 'S1', 'p': 0.9} for number, text in enumerate(texts)]
    words.append({'id': 'seg-7', 'text': 'and split lines too', 'start': 4.0, 'end': 5.6, 'speaker': 'S2'})
    code, output = tool('captions.py', 'build', save('fields-words.json', {'words': words}),
                        '--out', root / 'fields')
    built = [word for cue in load('fields.json').get('cues', []) for word in cue['words']] if code == 0 else []
    record('captions: build keeps each word\'s ID and other fields; split pieces carry the line\'s ID and a part',
           [word.get('id') for word in built] == [word['id'] for word in words[:6]] + ['seg-7'] * 4
           and [word.get('part') for word in built[6:]] == [1, 2, 3, 4]
           and all(word.get('speaker') == 'S1' and word.get('p') == 0.9 for word in built[:6])
           and all(word.get('speaker') == 'S2' and word.get('estimated') for word in built[6:]),
           output[-300:] + json.dumps(built)[:400])
    endings = [(root / f'fields.{extension}').read_bytes() for extension in ('srt', 'vtt', 'json')] if code == 0 else []
    record('captions: sidecars are written with LF line endings on every platform',
           len(endings) == 3 and all(b'\n' in data and b'\r' not in data for data in endings),
           str([data.count(b'\r') for data in endings]))
    run_captions_variant_cases(tool, record, j, scripts_dir)
    check_burn_output(tool, record, j)
    check_caption_craft(tool, record, j)
    check_caption_conflicts(tool, record, j)
    check_world_caption_shaping(tool, record, j, scripts_dir)
    check_bidi_uniscribe(record, j, scripts_dir)
    check_font_fallbacks_and_sdr(tool, record, j, scripts_dir)


# ----------------------------------------------------------------------------------------------- equivalent words

def run_captions_variant_cases(tool, record, j, scripts_dir):
    """Reliable equivalents (numbers, contractions, case, punctuation, hyphenation) match; a difference only in
    spelling is a review prompt; a different word is still a finding; check --words reads every edit-time shape."""
    root = Path(j('captions-variants'))
    root.mkdir(parents=True, exist_ok=True)

    def check(name, caption, spoken):
        """Check one caption (0.0-4.0 s) against spoken words spread over 0.2-3.8 s: (exit code, report)."""
        tokens = spoken.split()
        step = 3.6 / len(tokens)
        words = [{'word': token, 'start': round(0.2 + k * step, 3), 'end': round(0.2 + (k + 0.8) * step, 3)}
                 for k, token in enumerate(tokens)]
        (root / (name + '.json')).write_text(json.dumps({'words': words}), encoding='utf-8')
        (root / (name + '.srt')).write_text('1\n00:00:00,000 --> 00:00:04,000\n' + caption + '\n', encoding='utf-8')
        code, output = tool('captions.py', 'check', root / (name + '.srt'), '--words', root / (name + '.json'),
                            '--json', root / (name + '-report.json'))
        path = root / (name + '-report.json')
        return code, json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'output': output}

    pairs = [('digits', 'I have 2 cats.', 'I have two cats'),
             ('compound number', 'We waited 25 minutes.', 'we waited twenty five minutes'),
             ('hyphenated number', 'We waited twenty-five minutes.', 'we waited 25 minutes'),
             ('thousands', 'It costs $1,200.', 'it costs twelve hundred dollars'),
             ('year', 'Back in 1984.', 'back in nineteen eighty four'),
             ('decimal and percent', 'About 4.5% more.', 'about four point five percent more'),
             ('ordinal', 'The 21st time.', 'the twenty first time')]
    results = {name: check('number-' + name.replace(' ', '-'), caption, spoken) for name, caption, spoken in pairs}
    record('captions: numbers written as digits or words match (2, twenty five, $1,200, 1984, 4.5%, 21st)',
           all(code == 0 and not report.get('findings') for code, report in results.values()),
           str({name: report.get('findings', report.get('output')) for name, (code, report) in results.items()
                if code or report.get('findings')})[:600])

    pairs = [('cannot', "I can't go.", 'I cannot go'), ('has', "It's been a long day.", 'it has been a long day'),
             ('will', "We'll see.", 'we will see'), ('us', "Let's go.", 'let us go'),
             ('going to', "They're gonna win.", 'they are going to win'), ('not', "We do not know.", "we don't know")]
    results = {name: check('contraction-' + name.replace(' ', '-'), caption, spoken)
               for name, caption, spoken in pairs}
    record("captions: contractions and their expansions match (can't / cannot, it's / it has, let's / let us)",
           all(code == 0 and not report.get('findings') for code, report in results.values()),
           str({name: report.get('findings', report.get('output')) for name, (code, report) in results.items()
                if code or report.get('findings')})[:600])

    code, report = check('hyphenation', 'Re-enter the e-mail, OK? Well-known!', 'reenter the email okay well known')
    record('captions: case, punctuation and hyphenation match', code == 0 and not report.get('findings'),
           str(report.get('findings', report.get('output'))))

    code, report = check('spelling', 'Jon arrived in grey.', 'John arrived in gray')
    prompts = [item for item in report.get('review', []) if item['rule'] == 'spelled differently from the words']
    record('captions: a difference only in spelling is a review prompt with both spellings, not a finding',
           code == 0 and not report.get('findings') and prompts and prompts[0].get('cue') == 1
           and 'jon' in str(prompts).lower() and 'john' in str(prompts).lower(), str(report)[:500])

    code, report = check('different', 'I have three cats at night.', 'I have two cats at right')
    stale = [item for item in report.get('findings', []) if item['rule'] == 'caption words not in the dialogue']
    record('captions: a different word is still a finding (three for two, night for right), named as captioned',
           code == 1 and stale and stale[0]['words'] == ['three', 'night'], str(report.get('findings')))

    lines = {'version': 1, 'film_version': 'v002', 'duration_s': 5.0, 'lines': [
        {'line': 4, 'kind': 'spoken', 'source': 'int_01', 'start': 0.0, 'end': 2.0, 'text': 'Hello there',
         'words': [{'id': 'int_01-w000001', 'text': 'Hello', 'start': 0.2, 'end': 0.7},
                   {'id': 'int_01-w000002', 'text': 'there', 'start': 0.8, 'end': 1.6}]},
        {'line': 5, 'kind': 'picture', 'source': 'broll_01', 'start': 2.0, 'end': 5.0,
         'text': 'Crew unloading the van'}]}
    (root / 'lines.json').write_text(json.dumps(lines), encoding='utf-8')
    (root / 'lines.srt').write_text('1\n00:00:00,200 --> 00:00:01,700\nHello there\n\n'
                                    '2\n00:00:02,500 --> 00:00:04,500\nCrew unloading the van\n', encoding='utf-8')
    code, output = tool('captions.py', 'check', root / 'lines.srt', '--words', root / 'lines.json',
                        '--json', root / 'lines-report.json')
    path = root / 'lines-report.json'
    report = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    found = [(item.get('cue'), item['rule']) for item in report.get('findings', [])]
    record("captions: check --words reads a version's lines.json: kept words count, a picture description does not",
           code == 1 and found == [(2, 'caption over no matching speech')], str(found) + output[-200:])

    occurrences = {'timeline': 'cut.xml', 'occurrences': [
        {'id': 'c001:w1', 'word': 'w1', 'text': 'Hello', 'clip': 1, 'source': 'int_01', 'start': 0.2, 'end': 0.7,
         'split': False, 'estimated': False},
        {'id': 'c001:w2', 'word': 'w2', 'text': 'there', 'clip': 1, 'source': 'int_01', 'start': 0.8, 'end': 1.6,
         'split': False, 'estimated': False}]}
    (root / 'occurrences.json').write_text(json.dumps(occurrences), encoding='utf-8')
    (root / 'occurrences.srt').write_text('1\n00:00:00,200 --> 00:00:01,700\nHello there\n', encoding='utf-8')
    code, output = tool('captions.py', 'check', root / 'occurrences.srt', '--words', root / 'occurrences.json')
    record("captions: check --words still reads exchange.py's earlier occurrences shape", code == 0, output[-300:])
    run_captions_meaning_cases(tool, record, j, scripts_dir)


# ----------------------------------------------------------------------------------------------- meaning and coverage

def run_captions_meaning_cases(tool, record, j, scripts_dir):
    """Equivalences never hide a changed meaning (signs, decimal points, separators, 'd for did, joined words, accents)
    and every transcribed word is checked against the whole caption timeline, gaps included."""
    root = Path(j('captions-meaning'))
    root.mkdir(parents=True, exist_ok=True)

    def check(name, caption, spoken, end=4.0, rows=None):
        """Check one caption (0 s to `end`) against spoken words spread over 0.2-3.8 s: (exit code, report)."""
        if rows is None:
            tokens = spoken.split()
            step = 3.6 / len(tokens)
            rows = [{'word': token, 'start': round(0.2 + k * step, 3), 'end': round(0.2 + (k + 0.8) * step, 3)}
                    for k, token in enumerate(tokens)]
        (root / (name + '.json')).write_text(json.dumps({'words': rows}), encoding='utf-8')
        stamp = '00:00:%02d,%03d' % (int(end), round((end - int(end)) * 1000))
        (root / (name + '.srt')).write_text('1\n00:00:00,000 --> ' + stamp + '\n' + caption + '\n', encoding='utf-8')
        code, output = tool('captions.py', 'check', root / (name + '.srt'), '--words', root / (name + '.json'),
                            '--json', root / (name + '-report.json'))
        path = root / (name + '-report.json')
        return code, json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'output': output}

    def rules(report, kind):
        return [item['rule'] for item in report.get(kind, [])]

    word_prompts = {'spelled differently from the words', 'contraction differs from the words',
                    'spoken but not captioned', 'speech with no caption'}

    changed = {name: check('changed-' + name, caption, spoken) for name, caption, spoken in [
        ('sign', 'It is -10 degrees today.', 'It is 10 degrees today'),
        ('decimal', 'The value is .5 today.', 'The value is 5 today'),
        ('score', 'The score is 1-2 today.', 'The score is 12 today'),
        ('time', 'We meet at 3:30 today.', 'We meet at 330 today'),
        ('digits', 'Call 12 now.', 'call one two now')]}
    record('captions: a changed sign, decimal point or separator is a finding (-10/10, .5/5, 1-2/12, 3:30/330)',
           all(code == 1 and 'caption words not in the dialogue' in rules(report, 'findings')
               for code, report in changed.values()),
           str({name: (code, report.get('findings')) for name, (code, report) in changed.items()})[:700])

    same = {name: check('same-' + name, caption, spoken) for name, caption, spoken in [
        ('minus', 'It is -10 degrees.', 'it is minus ten degrees'),
        ('negative', 'It is -10 degrees.', 'it is negative ten degrees'),
        ('point', 'The value is .5 today.', 'the value is point five today'),
        ('range', 'Allow 10-15 minutes.', 'allow ten to fifteen minutes'),
        ('clock', 'We meet at 3:30 today.', 'we meet at three thirty today'),
        ('year', 'Back in 1984.', 'back in nineteen eighty four')]}
    record('captions: signs, decimals, ranges and times spoken the same way still match (minus ten, point five, ten '
           'to fifteen, three thirty, 1984)',
           all(code == 0 and not report.get('findings') and not set(rules(report, 'review')) & word_prompts
               for code, report in same.values()),
           str({name: (code, report.get('findings'), rules(report, 'review')) for name, (code, report) in same.items()
                if code or report.get('findings') or set(rules(report, 'review')) & word_prompts})[:700])

    did_code, did = check('contraction-did', "We'd really go today.", 'We did really go today')
    had_code, had = check('contraction-had', "We'd gone home.", 'we had gone home')
    has_code, has = check('contraction-has', "It's been long.", 'it has been long')
    record("captions: 'd for did is a review prompt, never a match; 'd for had and 's for has still match",
           did_code == 0 and not did.get('findings') and 'contraction differs from the words' in rules(did, 'review')
           and had_code == 0 and not had.get('findings') and 'contraction differs from the words' not in
           rules(had, 'review') and has_code == 0 and 'contraction differs from the words' not in rules(has, 'review'),
           str((did.get('findings'), rules(did, 'review'), rules(had, 'review'), rules(has, 'review'))))

    joined = {name: check('joined-' + name, caption, spoken) for name, caption, spoken in [
        ('every day', 'We train every day.', 'we train everyday'),
        ('apostrophe', "Its fine.", "it's fine")]}
    hyphen_code, hyphen = check('joined-hyphen', 'Send the e-mail.', 'send the email')
    record("captions: words joined without a hyphen or an apostrophe dropped are review prompts (every day / "
           "everyday, its / it's); a hyphen still matches",
           all(code == 0 and not report.get('findings') and 'spelled differently from the words' in
               rules(report, 'review') for code, report in joined.values())
           and hyphen_code == 0 and 'spelled differently from the words' not in rules(hyphen, 'review'),
           str({name: (report.get('findings'), rules(report, 'review')) for name, (code, report) in joined.items()})
           + str(rules(hyphen, 'review')))

    accent_code, accent = check('accent', 'His name is Jose.', 'his name is Jos\xe9')
    prompts = [item for item in accent.get('review', []) if item['rule'] == 'spelled differently from the words']
    record('captions: an accent difference is a review prompt with both spellings (Jose / Jos\\u00e9)',
           accent_code == 0 and not accent.get('findings') and prompts and 'jose' in str(prompts).lower(),
           str(accent)[:400])

    controls = {name: check('control-' + name, caption, spoken) for name, caption, spoken in [
        ('cats', 'The cats are here.', 'the cuts are here'), ('fifteen', 'We sold 15 units.', 'we sold 50 units'),
        ('jon', 'Jon is here today.', 'John is here today'), ('cheque', 'I wrote a cheque.', 'I wrote a check')]}
    record('captions: controls hold: cats / cuts and 15 / 50 are findings; Jon / John and cheque / check are spelling '
           'prompts', all(controls[name][0] == 1 for name in ('cats', 'fifteen'))
           and all(controls[name][0] == 0 and 'spelled differently from the words' in rules(controls[name][1], 'review')
                   for name in ('jon', 'cheque')),
           str({name: (code, report.get('findings'), rules(report, 'review')) for name, (code, report)
                in controls.items()})[:600])

    rows = [{'word': 'Hello', 'start': 0.1, 'end': 0.4}, {'word': 'there', 'start': 0.45, 'end': 0.8},
            {'word': 'um', 'start': 1.8, 'end': 1.9}, {'word': 'danger', 'start': 2.3, 'end': 2.8},
            {'word': 'ahead', 'start': 2.85, 'end': 3.2}]
    code, report = check('coverage', 'Hello there', None, end=1.5, rows=rows)
    outside = [item for item in report.get('review', []) if item['rule'] == 'speech with no caption']
    coverage = report.get('timing_screen', {}).get('coverage', {})
    record('captions: speech outside every caption is a review prompt with its time; a filler is not; coverage counts '
           'every word', outside and outside[0].get('words') == ['danger', 'ahead'] and outside[0].get('start') == 2.3
           and coverage.get('words') == 4 and coverage.get('outside_captions') == 2,
           str(report.get('review')) + ' ' + str(coverage))



def check_burn_output(tool, record, j):
    """White footage tests caption contrast and exact preservation of input frames."""
    import json
    import subprocess
    from pathlib import Path
    root = Path(j('burn-output'))
    root.mkdir(parents=True, exist_ok=True)
    video = root / 'white.mp4'
    caption = root / 'captions.json'
    output = root / 'burned.mp4'
    report_path = root / 'burn-report.json'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=white:s=320x180:r=10:d=2', '-c:v', 'libx264', '-threads', '2',
                    '-pix_fmt', 'yuv420p', str(video)], check=True)
    caption.write_text(json.dumps({'cues': [{'start': .2, 'end': 1.6, 'text': 'BOLD TEXT'}]}), encoding='utf-8')
    code, message = tool('captions.py', 'burn', video, caption, '--out', output, '--font-size', '24',
                         '--json', report_path)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0',
                            '-show_entries', 'stream=nb_read_frames', '-of', 'csv=p=0', str(output)],
                           capture_output=True, text=True) if output.exists() else None
    frames = int(probe.stdout.strip()) if probe and probe.stdout.strip().isdigit() else None
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('captions: burning preserves the exact input frame count', code in (0, 1) and frames == 20,
           f'frames={frames}; {message[-300:]}')
    contrast = report.get('contrast') or {}
    record('captions: default weight and plate provide measured contrast over white footage',
           report.get('font_weight') == 700 and report.get('plate') is True
           and contrast.get('samples') and contrast.get('minimum_ratio', 0) >= 4.5, str(report))
    import importlib.util
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('caption_check_module', scripts / 'check.py')
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    (root / 'manifest.json').write_text(json.dumps({'captions': ['burn']}), encoding='utf-8')
    (root / 'caption-burn.json').write_text(json.dumps({'overlays': [report]}), encoding='utf-8')
    item = check.caption_contrast_item(root, output, root)
    record('captions: check measures caption contrast on the decoded delivery',
           item['id'] == 'captions_contrast' and item['state'] == 'pass'
           and (root / 'captions-contrast.json').exists(), str(item))




def check_caption_craft(tool, record, j):
    """Pause boundaries, stable text geometry and measured layout on narrow frames."""
    import importlib.util
    import numpy as np
    from pathlib import Path
    from types import SimpleNamespace
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('caption_craft_case', scripts / 'captions.py')
    cap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cap)
    args = SimpleNamespace(line_length=42, gap=.04, cps=20, min_duration=.8, max_duration=7, pause_gap=.6)
    words = [{'text': text, 'start': start, 'end': end} for text, start, end in
             [('first', .1, .3), ('words', .31, .5), ('later', 4.7, 4.9)]]
    cues, relaxations = cap.segment_with_review(words, args)
    record('captions: long pause creates a boundary without forcing a singleton across it',
           len(cues) == 2 and cues[0]['text'] == 'first words' and cues[1]['text'] == 'later', str(cues))
    font = cap.choose_font(None)
    cue = {'text': 'A   B', 'start': 0, 'end': 2,
           'words': [{'text': 'A', 'start': .5, 'end': 1}, {'text': 'B', 'start': 1, 'end': 2}]}
    plain, _ = cap.render_caption(300, 300, (10, 10, 290, 290), cue, None, font, 30, False)
    active, _ = cap.render_caption(300, 300, (10, 10, 290, 290), cue, 0, font, 30, False)
    a = np.asarray(plain)
    b = np.asarray(active)
    right = np.arange(300)[None, :] > 150
    white_a = np.all(a[:, :, :3] > 230, axis=2) & (a[:, :, 3] > 100) & right
    white_b = np.all(b[:, :, :3] > 230, axis=2) & (b[:, :, 3] > 100) & right
    record('captions: highlighting preserves the other word and repeated spaces',
           white_a.any() and np.array_equal(white_a, white_b),
           str((np.where(white_a)[1].tolist()[:8], np.where(white_b)[1].tolist()[:8])))
    metadata = {}
    try:
        cap.render_caption(300, 300, (10, 10, 290, 290), {'text': 'WWWWWW WWWWWW'}, None, font, 30, False,
                           metadata=metadata)
        ok = metadata.get('size') == 30 and len(metadata.get('lines', [])) == 2
    except TypeError as error:
        ok = False
        metadata = {'error': str(error)}
    record('captions: legal measured line breaks preserve the requested size', ok, str(metadata))
    import json
    source = Path(j('estimated-input.json'))
    prefix = Path(j('estimated-output'))
    report_path = Path(j('estimated-report.json'))
    source.write_text(json.dumps({'words': [{'text': 'Hello', 'start': .1, 'end': 1.0, 'estimated': True}]}),
                      encoding='utf-8')
    code, output = tool('captions.py', 'build', source, '--out', prefix, '--json', report_path)
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('captions: the build summary preserves an existing estimated word flag',
           code == 0 and report.get('word_timings_estimated') is True and report.get('note'), str(report))



def check_caption_conflicts(tool, record, j):
    """Conflicting reading constraints retain every word or fail without an empty success."""
    text = ('One small step makes the next useful thing easier for every person using this tool '
            'and the whole team can now continue').split()
    words = [{'id': f'int_01-w{i:06d}', 'text': word, 'start': round(i * .2833, 4),
              'end': round((i + 1) * .2833, 4)} for i, word in enumerate(text)]
    source = Path(j('caption-conflict.json'))
    source.write_text(json.dumps({'words': words}), encoding='utf-8')
    prefix = Path(j('caption-conflict-out'))
    report = Path(j('caption-conflict-report.json'))
    code, output = tool('captions.py', 'build', source, '--out', prefix, '--line-length', 18, '--json', report)
    data = json.loads(report.read_text(encoding='utf-8'))
    cues = (json.loads(prefix.with_suffix('.json').read_text(encoding='utf-8'))['cues']
            if prefix.with_suffix('.json').exists() else [])
    ids = [word['id'] for cue in cues for word in cue['words']]
    record('captions: conflicting rules build nonempty captions with every word in order',
           code == 0 and ids == [word['id'] for word in words] and len(cues) > 1, output[-500:])
    record('captions: relaxed rules are explicit review prompts',
           any(row['rule'] == 'segmentation relaxation' for row in data['review']), str(data['review']))
    pause = Path(j('caption-pause-display.json'))
    pause.write_text(json.dumps([{'text': 'Yes', 'start': .1, 'end': .2},
                                 {'text': 'No', 'start': 1.0, 'end': 1.1}]), encoding='utf-8')
    pause_prefix = Path(j('caption-pause-display-out'))
    code, output = tool('captions.py', 'build', pause, '--out', pause_prefix)
    timed = json.loads(pause_prefix.with_suffix('.json').read_text(encoding='utf-8'))['cues']
    record('captions: long pauses have visible blank time between short cues',
           code == 0 and len(timed) == 2 and timed[0]['end'] <= .4 and timed[1]['start'] >= .8,
           str([(cue['start'], cue['end']) for cue in timed]))
    bad = Path(j('caption-overlap.json'))
    bad.write_text(json.dumps({'words': [{'text': 'First', 'start': 0, 'end': 1},
                                         {'text': 'Second', 'start': .5, 'end': 1.5}]}), encoding='utf-8')
    bad_prefix = Path(j('caption-overlap-output'))
    code, output = tool('captions.py', 'build', bad, '--out', bad_prefix)
    record('captions: impossible overlapping input fails without empty sidecars',
           code == 2 and not bad_prefix.with_suffix('.json').exists(), output[-300:])


def check_world_caption_shaping(tool, record, j, scripts_dir):
    """Verify shaped scripts, font coverage, title refusal and standalone HDR conversion."""
    import importlib.util
    import os
    import re
    import shutil
    from PIL import features
    root = Path(j('world-caption')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'black.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=black:s=320x180:r=10:d=1.2',
                    '-c:v', 'libx264', '-threads', '1', str(source)], check=True, capture_output=True)
    spec = importlib.util.spec_from_file_location('bundled_caption_faces', Path(scripts_dir) / 'captions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    samples = {'Arabic': '\u0645\u0631\u062d\u0628\u0627 Alex',
               'Hebrew': '\u05e9\u05dc\u05d5\u05dd',
               'Thai': '\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35',
               'Devanagari': '\u0928\u092e\u0938\u094d\u0924\u0947'}
    for name, text in samples.items():
        try:
            selected = Path(module.complex_font(None, text))
            missing = module.missing_glyphs(selected, text)
            covered = selected.name == 'NotoSans' + name + '-Bold.ttf' and not missing
            detail = f'face={selected.name}; missing={missing}'
        except (OSError, ValueError) as exc:
            covered, detail = False, str(exc)
        record('captions: bundled Noto ' + name + ' is selected and covers its script', covered, detail)
    from unittest.mock import patch
    for name, text in [('CJK', '\u4e16\u754c'), ('emoji', '\U0001f44d')]:
        try:
            with patch.object(module, 'caption_font_candidates', return_value=module.bundled_caption_fonts()):
                module.fallback_shaping_font(None, text)
        except ValueError as exc:
            message = str(exc)
            refused = '--font' in message and 'glyphs' in message
        else:
            message, refused = 'no error', False
        record('captions: uncovered ' + name + ' asks for a covered font', refused, message)
    filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, check=True)
    available = set(re.findall(r'^\s*[TSC.]{2,3}\s+(\S+)', filters.stdout, re.MULTILINE))
    if 'ass' not in available:
        print('SKIP  captions: per-script, reference, highlighting, missing-glyph/font and title cases '
              '(this suite needs the ass filter)')
        sample = root / 'fallback.srt'
        sample.write_text('1\n00:00:00,000 --> 00:00:01,000\n\u0645\u0631\u062d\u0628\u0627\n',
                          encoding='utf-8')
        code, output = tool('captions.py', 'burn', source, sample, '--out', root / 'fallback.mp4')
        if features.check('raqm'):
            record('captions: complex script can use Pillow Raqm without libass', code in (0, 1), output[-400:])
        else:
            record('captions: missing shaping engines produce an actionable error',
                   code == 2 and 'libass' in output and 'Raqm' in output, output[-400:])
        plain = root / 'plain.srt'
        plain.write_text('1\n00:00:00,000 --> 00:00:01,000\nTest\n', encoding='utf-8')
        plain_report = root / 'plain.json'
        tool('captions.py', 'burn', source, plain, '--out', root / 'plain.mp4', '--json', plain_report)
        arabic = json.loads(plain_report.read_text(encoding='utf-8')) if plain_report.exists() else {}
        check_world_caption_hdr(tool, record, root, available, arabic)
        return
    examples = {'arabic-latin': '\u0645\u0631\u062d\u0628\u0627 Alex',
                'hebrew': '\u05e9\u05dc\u05d5\u05dd',
                'thai': '\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35',
                'devanagari': '\u0928\u092e\u0938\u094d\u0924\u0947', 'combining': 'Cafe\u0301',
                'arabic-thai': samples['Arabic'] + ' ' + samples['Thai'],
                'hebrew-devanagari': samples['Hebrew'] + ' ' + samples['Devanagari']}
    reports = {}
    for name, text in examples.items():
        caption = root / (name + '.srt')
        caption.write_text('1\n00:00:00,000 --> 00:00:01,000\n' + text + '\n', encoding='utf-8')
        out = root / (name + '.mp4')
        report = root / (name + '.json')
        code, output = tool('captions.py', 'burn', source, caption, '--out', out, '--no-plate', '--json', report)
        data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
        reports[name] = data
        layout = (data.get('cue_layouts') or [{}])[0]
        safe = data.get('safe_area_pixels') or [0, 0, 0, 0]
        box = ((data.get('rendered_boxes') or [{}])[0]).get('box') or [-1] * 4
        record('captions: ' + name + ' is shaped with a covered font inside the safe area',
               code in (0, 1) and layout.get('shaping') == 'libass HarfBuzz complex'
               and layout.get('missing_glyphs') == [] and bool(layout.get('font_selection'))
               and safe[0] <= box[0] <= box[2] <= safe[2] and safe[1] <= box[1] <= box[3] <= safe[3]
               and data.get('input_frames') == data.get('output_frames'), output[-300:])
    # Every face libass selects for a mixed line must be one the script asked for by name, never a fallback it
    # found for itself: Windows and macOS found system Thai fonts and hid a run that named no face, which Linux's
    # fontconfig could not.
    import re
    for name in ('arabic-thai', 'hebrew-devanagari'):
        layout = ((reports.get(name) or {}).get('cue_layouts') or [{}])[0]
        pairs = re.findall(r'\(([^,()]+), \d+, \d+\) -> ([^,]+),', ' '.join(layout.get('font_selection') or []))
        asked = [(wanted, got) for wanted, got in pairs
                 if not re.sub(r'[^a-z]', '', got.lower()).startswith(re.sub(r'[^a-z]', '', wanted.lower()))]
        record('captions: ' + name + ' uses only the faces it names, with no system fallback',
               bool(pairs) and not asked, str(pairs))
    # A bundled Arabic face shaping a Thai run must name the bundled Thai face. captions.py prefers one installed
    # font covering the whole line (Tahoma on Windows), so the runs are exercised directly: without them Windows
    # fell back to a system Thai font and Linux found none.
    try:
        _, _, forced = module.render_shaped_caption(
            'ffmpeg', str(root), 320, 180, (16, 10, 304, 170), {'text': examples['arabic-thai'], 'start': 0, 'end': 1},
            None, str(module.bundled_caption_fonts()[0]), None, False)
        selection = ' '.join(forced.get('font_selection') or [])
    except ValueError as error:
        selection = 'error: ' + str(error)
    pairs = re.findall(r'\(([^,()]+), \d+, \d+\) -> ([^,]+),', selection)
    record('captions: a bundled Arabic face with a Thai run selects the bundled Thai face by name',
           ('Noto Sans Thai', 'NotoSansThai-Bold') in pairs and all(got.startswith('NotoSans') for _, got in pairs),
           selection[-400:])
    # libass fits a face's full Windows ascent plus descent to its Fontsize; at the same em the shaped caption's
    # letters must be as tall as Pillow draws them (Thai was 68% and Hebrew 81% before scaling; Arabic, at 44%, is
    # left out because Pillow's isolated letter forms are taller than joined text).
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    heights = {}
    for name, font in zip(('Hebrew', 'Thai'), module.bundled_caption_fonts()[1:3]):
        text = samples[name].split()[0]
        try:
            image, _, shaped = module.render_shaped_caption('ffmpeg', str(root), 640, 360, (32, 20, 608, 340),
                                                            {'text': text, 'start': 0, 'end': 1}, None, str(font), 40,
                                                            False)
            rows = np.where(np.asarray(image)[:, :, 3].max(axis=1) > 128)[0]
            ink = int(rows[-1] - rows[0] + 1) - 2 if len(rows) else 0
            box = ImageDraw.Draw(Image.new('L', (8, 8))).textbbox((0, 0), text,
                                                                 font=ImageFont.truetype(str(font), shaped['size']))
            heights[name] = (ink, box[3] - box[1])
        except ValueError as error:
            heights[name] = (0, str(error))
    record('captions: shaped letters are drawn at the size asked for, as tall as Pillow draws them',
           all(isinstance(want, int) and want and abs(got - want) <= .12 * want for got, want in heights.values()),
           str(heights))
    for name in ('Thai', 'Devanagari'):
        caption = root / (name.lower() + '.srt')
        report = root / (name + '-explicit.json')
        arabic_font = module.bundled_caption_fonts()[0]
        code, output = tool('captions.py', 'burn', source, caption, '--font', arabic_font,
                            '--out', root / (name + '-explicit.mp4'), '--json', report)
        data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
        layout = (data.get('cue_layouts') or [{}])[0]
        selected = Path(layout.get('font_path') or '').name
        record('captions: bundled ' + name + ' replaces an uncovered chosen face',
               code in (0, 1) and selected == 'NotoSans' + name + '-Bold.ttf', output[-300:])
    arabic = reports.get('arabic-latin') or {}
    layout = (arabic.get('cue_layouts') or [{}])[0]
    if layout.get('font_path'):
        from PIL import ImageFont
        font_name = ImageFont.truetype(layout['font_path'], 24).getname()[0]
        safe = arabic['safe_area_pixels']
        ass = ('[Script Info]\nScriptType: v4.00+\nPlayResX: 320\nPlayResY: 180\nWrapStyle: 0\n'
               '[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,'
               'BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,'
               'Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n'
               'Style: Default,%s,%g,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,'
               '1,0,0,2,%d,%d,%d,-1\n[Events]\n'
               'Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n'
               'Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,%s\n') % (
                   font_name, round(layout['size'] * module.libass_size_factor(layout['font_path']), 2),
                   safe[0], 320 - safe[2], 180 - safe[3] + 8,
                   examples['arabic-latin'])
        (root / 'reference.ass').write_text(ass, encoding='utf-8')
        reference_fonts = root / 'reference-fonts'
        reference_fonts.mkdir(exist_ok=True)
        shutil.copyfile(layout['font_path'], reference_fonts / Path(layout['font_path']).name)
        reference = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(source), '-vf',
                                    'ass=filename=reference.ass:fontsdir=reference-fonts:shaping=complex',
                                    '-frames:v', '1',
                                    '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], cwd=root, capture_output=True)
        decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(root / 'arabic-latin.mp4'),
                                  '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                 capture_output=True)
        if len(reference.stdout) == len(decoded.stdout) == 320 * 180 * 3:
            a = np.frombuffer(reference.stdout, np.uint8).reshape(180, 320, 3).max(axis=2) > 120
            b = np.frombuffer(decoded.stdout, np.uint8).reshape(180, 320, 3).max(axis=2) > 120
            union = np.count_nonzero(a | b)
            overlap = np.count_nonzero(a & b) / union if union else 0.0
        else:
            overlap = 0.0
        record('captions: Arabic and Latin glyph pixels agree with a separate libass render',
               reference.returncode == 0 and decoded.returncode == 0 and overlap > .75, f'mask overlap={overlap:.3f}')
    else:
        record('captions: Arabic and Latin glyph pixels agree with a separate libass render', False,
               'shaped Arabic render was not available')
    highlighted = root / 'highlighted.json'
    words = [{'text': '\u0645\u0631\u062d\u0628\u0627', 'start': 0, 'end': .5},
             {'text': 'Alex', 'start': .5, 'end': 1}]
    highlighted.write_text(json.dumps({'cues': [{'start': 0, 'end': 1, 'text': examples['arabic-latin'],
                                                  'words': words}]}), encoding='utf-8')
    highlight_video = root / 'highlighted.mp4'
    highlight_report = root / 'highlighted-report.json'
    code, output = tool('captions.py', 'burn', source, highlighted, '--out', highlight_video, '--no-plate',
                        '--highlight', '--json', highlight_report)
    data = json.loads(highlight_report.read_text(encoding='utf-8')) if highlight_report.exists() else {}
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(highlight_video), '-f', 'rawvideo',
                              '-pix_fmt', 'rgb24', '-'], capture_output=True) if highlight_video.exists() else None
    frames = (np.frombuffer(decoded.stdout, np.uint8).reshape(-1, 180, 320, 3)
              if decoded and len(decoded.stdout) % (180 * 320 * 3) == 0 else np.array([]))
    yellow = []
    centres = []
    for number in (2, 7):
        if len(frames) > number:
            frame = frames[number].astype(int)
            mask = ((frame[:, :, 0] - frame[:, :, 2] > 20) & (frame[:, :, 0] > 55)
                    & (frame[:, :, 1] > 50))
            xs = np.where(mask)[1]
            yellow.append(len(xs))
            centres.append(float(xs.mean()) if len(xs) else None)
    states = data.get('rendered_boxes') or []
    record('captions: default-size bidirectional highlighting follows word timing and placement',
           code in (0, 1) and len(yellow) == 2 and min(yellow) > 0 and None not in centres
           and centres[0] > centres[1] and len(states) == 2
           and states[0]['active_word_index'] == 0 and states[1]['active_word_index'] == 1
           and states[0]['box'] == states[1]['box'],
           f'coloured pixels={yellow}; centres={centres}; states={states}; {output[-200:]}')
    large = root / 'highlighted-large.mp4'
    large_code, large_output = tool('captions.py', 'burn', source, highlighted, '--out', large, '--no-plate',
                                    '--highlight', '--font-size', '24')
    large_decode = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(large), '-f', 'rawvideo',
                                   '-pix_fmt', 'rgb24', '-'], capture_output=True) if large.exists() else None
    large_frames = (np.frombuffer(large_decode.stdout, np.uint8).reshape(-1, 180, 320, 3)
                    if large_decode and len(large_decode.stdout) % (180 * 320 * 3) == 0 else np.array([]))
    strong = []
    for number in (2, 7):
        if len(large_frames) > number:
            frame = large_frames[number]
            strong.append(int(np.count_nonzero((frame[:, :, 0] > 170) & (frame[:, :, 1] > 130)
                                               & (frame[:, :, 2] < 150))))
    record('captions: bidirectional highlights retain saturated pixels at a readable test size',
           large_code in (0, 1) and len(strong) == 2 and min(strong) > 0,
           f'saturated pixels={strong}; {large_output[-200:]}')
    missing = root / 'missing.srt'
    missing.write_text('1\n00:00:00,000 --> 00:00:01,000\n\u0645\u0631\u062d\u0628\u0627 \U0010ffff\n',
                       encoding='utf-8')
    code, output = tool('captions.py', 'burn', source, missing, '--out', root / 'missing.mp4')
    record('captions: missing glyphs are reported instead of silently drawing tofu',
           code == 2 and 'U+10FFFF' in output, output[-500:])
    code, output = tool('captions.py', 'burn', source, root / 'arabic-latin.srt',
                        '--out', root / 'missing-font.mp4', '--font', root / 'absent.ttf')
    record('captions: a nonexistent explicit font gives an actionable error',
           code == 2 and 'font not found' in output and '--font' in output, output[-400:])
    cut_spec = importlib.util.spec_from_file_location('wave2_title_cut', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(cut_spec)
    cut_spec.loader.exec_module(cut)
    if not features.check('raqm'):
        try:
            cut.make_title(root / 'title.png', (320, 180), [examples['arabic-latin']], 'center', {})
            title_error = ''
        except ValueError as error:
            title_error = str(error)
        record('captions: complex title refuses an unshaped Pillow build',
               'complex-script titles need Pillow with Raqm' in title_error, title_error)
    else:
        record('captions: complex title has a Raqm shaping engine', True)
    check_world_caption_hdr(tool, record, root, available, arabic)


def check_world_caption_hdr(tool, record, root, available, arabic):
    """Check colour conversion even when the optional complex shaper is missing."""
    if 'zscale' not in available:
        print('SKIP  captions: PQ and HLG conversion needs FFmpeg with zscale/libzimg')
    for transfer in (('smpte2084', 'arib-std-b67') if 'zscale' in available else ()):
        hdr = root / (transfer + '.mkv')
        vf = ('format=yuv420p10le,setparams=colorspace=bt2020nc:color_trc=' + transfer
              + ':color_primaries=bt2020:range=tv')
        patches = ('color=gray:s=160x120:r=10:d=1.2,'
                   'drawbox=x=0:y=0:w=40:h=80:color=red:t=fill,'
                   'drawbox=x=40:y=0:w=40:h=80:color=0xe0ae8a:t=fill,'
                   'drawbox=x=120:y=0:w=40:h=80:color=blue:t=fill')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', patches,
                        '-vf', vf, '-c:v', 'ffv1', '-threads', '1', '-color_primaries', 'bt2020', '-color_trc',
                        transfer, '-colorspace', 'bt2020nc', '-color_range', 'tv', str(hdr)],
                       check=True, capture_output=True)
        caption = root / 'hdr.srt'
        caption.write_text('1\n00:00:00,000 --> 00:00:00,800\nTest\n', encoding='utf-8')
        burned = root / (transfer + '-burn.mp4')
        report = root / (transfer + '-burn.json')
        code, output = tool('captions.py', 'burn', hdr, caption, '--out', burned, '--json', report)
        edit = {'version': 1, 'fps': 10, 'size': [160, 120], 'sources': {'v': str(hdr)},
                'picture': [{'src': 'v', 'in': 0, 'out': 1}]}
        edit_path = root / (transfer + '-edit.json')
        edit_path.write_text(json.dumps(edit), encoding='utf-8')
        conformed = root / (transfer + '-assemble.mp4')
        assemble_code, assembled_output = tool('assemble.py', edit_path, '--out', conformed)
        pixels = []
        for path in (burned, conformed):
            if path.is_file():
                decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-frames:v', '1',
                                          '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True)
                if len(decoded.stdout) == 160 * 120 * 3:
                    frame = np.frombuffer(decoded.stdout, np.uint8).reshape(120, 160, 3)
                    pixels.append(np.array([frame[20, x] for x in (20, 60, 100, 140)]))
        data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
        delta = int(np.max(np.abs(pixels[0].astype(int) - pixels[1].astype(int)))) if len(pixels) == 2 else 999
        probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                'stream=color_space,color_transfer,color_primaries', '-of', 'json', str(burned)],
                               capture_output=True, text=True)
        tags = (json.loads(probe.stdout or '{}').get('streams') or [{}])[0]
        record('captions: ' + transfer + ' is converted to SDR before compositing',
               code in (0, 1) and assemble_code in (0, 1) and delta <= 8
               and all(tags.get(key) == 'bt709' for key in ('color_space', 'color_transfer', 'color_primaries'))
               and 'HDR to BT.709 SDR' in data.get('colour_conversion', ''),
               f'delta={delta}; pixels={[x.tolist() for x in pixels]}; {output[-120:]} {assembled_output[-120:]}')
    record('captions: missing colour tags are recorded as assumptions',
           bool(arabic.get('colour_assumptions')), str(arabic.get('colour_assumptions')))


def uniscribe_positions(text):
    """Get independent Windows text-order positions for the BMP fixture characters."""
    import ctypes
    from ctypes import wintypes
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    usp = ctypes.WinDLL('usp10', use_last_error=True)
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateFontW.argtypes = [ctypes.c_int] * 14 + [wintypes.LPCWSTR]
    gdi.CreateFontW.restype = wintypes.HANDLE
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi.SelectObject.restype = wintypes.HANDLE
    gdi.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    usp.ScriptStringAnalyse.argtypes = [wintypes.HDC, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wintypes.DWORD, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_void_p)]
    usp.ScriptStringAnalyse.restype = ctypes.c_long
    usp.ScriptStringCPtoX.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.BOOL, ctypes.POINTER(ctypes.c_int)]
    usp.ScriptStringCPtoX.restype = ctypes.c_long
    usp.ScriptStringFree.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    dc = gdi.CreateCompatibleDC(None)
    font = gdi.CreateFontW(-48, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 5, 0, 0, 'Arial')
    old = gdi.SelectObject(dc, font)
    analysis = ctypes.c_void_p()
    try:
        buffer = ctypes.create_unicode_buffer(text)
        code = usp.ScriptStringAnalyse(dc, ctypes.cast(buffer, ctypes.c_void_p), len(text), 0, -1,
                                       0x80 | 0x20 | 0x100, 0, None, None, None, None, None,
                                       ctypes.byref(analysis))
        if code:
            raise OSError('Uniscribe analysis failed: ' + str(code))
        positions = []
        for index in range(len(text)):
            left, right = ctypes.c_int(), ctypes.c_int()
            if (usp.ScriptStringCPtoX(analysis, index, False, ctypes.byref(left))
                    or usp.ScriptStringCPtoX(analysis, index, True, ctypes.byref(right))):
                raise OSError('Uniscribe character position failed')
            positions.append((left.value + right.value) / 2)
        return positions
    finally:
        if analysis.value:
            usp.ScriptStringFree(ctypes.byref(analysis))
        gdi.SelectObject(dc, old)
        gdi.DeleteObject(font)
        gdi.DeleteDC(dc)


def check_bidi_uniscribe(record, j, scripts_dir):
    """Compare highlighted word positions to Uniscribe, not to another libass render."""
    import importlib.util
    import os
    import re
    if os.name != 'nt':
        print('SKIP  captions: independent bidi-order reference needs Windows Uniscribe')
        return
    spec = importlib.util.spec_from_file_location('round2_caption_bidi', Path(scripts_dir) / 'captions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, check=True)
    if not re.search(r'^\s*[TSC.]{2,3}\s+ass\s', filters.stdout, re.MULTILINE):
        print('SKIP  captions: independent bidi-order comparison needs FFmpeg libass')
        return
    folder = Path(j('bidi-uniscribe'))
    folder.mkdir(parents=True, exist_ok=True)
    cases = [('\u0645\u0631\u062d\u0628\u0627 Alex', 0, 1),
             ('\u05e9\u05dc\u05d5\u05dd Alex', 0, 1),
             ('\u0645\u0631\u062d\u0628\u0627 \u064a\u0627 \u0635\u062f\u064a\u0642\u064a !', 2, 3)]
    for text, first, second in cases:
        try:
            spans = list(re.finditer(r'\S+', text))
            positions = uniscribe_positions(text)
            reference = [sum(positions[spans[i].start():spans[i].end()]) / len(spans[i].group())
                         for i in (first, second)]
            font = module.complex_font(None, text)
            observed = []
            for active in (first, second):
                image, _, _ = module.render_shaped_caption('ffmpeg', str(folder), 640, 360, (40, 30, 600, 340),
                                                         {'text': text}, active, font, 40, False)
                pixels = np.asarray(image)
                mask = ((pixels[:, :, 0] > 175) & (pixels[:, :, 1] > 140)
                        & (pixels[:, :, 2] < 150) & (pixels[:, :, 3] > 150))
                _, xs = np.where(mask)
                observed.append(float(np.mean(xs)) if len(xs) else None)
            ok = None not in observed and (observed[0] > observed[1]) == (reference[0] > reference[1])
            detail = f'Uniscribe={reference}; renderer={observed}'
        except (ValueError, RuntimeError, OSError) as error:
            ok, detail = False, str(error)
        record('captions: RTL word and punctuation order matches Windows Uniscribe ' + ascii(text), ok, detail)

    text = '\u0645\u0631\u062d\u0628\u0627 \u064a\u0627 \u0635\u062f\u064a\u0642\u064a!'
    try:
        font = module.complex_font(None, text)
        masks = []
        for value in (text, text[:-1]):
            image, _, _ = module.render_shaped_caption('ffmpeg', str(folder), 640, 360, (40, 30, 600, 340),
                                                       {'text': value}, None, font, 40, False)
            pixels = np.asarray(image)
            masks.append((pixels[:, :, :3].max(axis=2) > 100) & (pixels[:, :, 3] > 100))
        full, base = masks
        choices = []
        for delta in range(-80, 81):
            shifted = np.roll(base, delta, axis=1)
            if delta > 0:
                shifted[:, :delta] = False
            elif delta < 0:
                shifted[:, delta:] = False
            choices.append((int(np.count_nonzero(full & shifted)), delta, shifted))
        _, delta, shifted = max(choices, key=lambda row: row[0])
        xs = np.where(shifted)[1]
        left = int(np.count_nonzero(full[:, :xs.min()])) if len(xs) else 0
        right = int(np.count_nonzero(full[:, xs.max() + 1:])) if len(xs) else 0
        positions = uniscribe_positions(text)
        reference_left = positions[-1] < min(positions[:-1])
        ok = bool(left + right and (left > right) == reference_left)
        detail = f'Uniscribe left={reference_left}; extra pixels left/right={left}/{right}; alignment={delta}'
    except (ValueError, RuntimeError, OSError) as error:
        ok, detail = False, str(error)
    record('captions: attached RTL punctuation agrees with Windows Uniscribe', ok, detail)


def check_font_fallbacks_and_sdr(tool, record, j, scripts_dir):
    """Fallback faces and partially tagged colour are checked on decoded burns."""
    import importlib.util
    root = Path(j('round2-caption-fallback')).resolve()
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'source.mp4'
    patches = ('color=gray:s=320x180:r=10:d=1.2,'
               'drawbox=x=0:y=0:w=80:h=100:color=0xc03020:t=fill,'
               'drawbox=x=80:y=0:w=80:h=100:color=0x20a040:t=fill,'
               'drawbox=x=160:y=0:w=80:h=100:color=0x2040c0:t=fill,'
               'drawbox=x=240:y=0:w=80:h=100:color=0xf0f0f0:t=fill')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', patches, '-c:v', 'libx264', '-crf', '0',
                    '-threads', '1', '-colorspace', 'bt709', str(source)], capture_output=True, check=True)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                            'stream=color_space,color_transfer,color_primaries', '-of', 'json', str(source)],
                           capture_output=True, text=True, check=True)
    tags = (json.loads(probe.stdout).get('streams') or [{}])[0]
    partly_tagged = (tags.get('color_space') == 'bt709'
                     and tags.get('color_primaries') in (None, 'unknown', 'unspecified'))
    spec = importlib.util.spec_from_file_location('round2_caption_fonts', Path(scripts_dir) / 'captions.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found = ('Glyph 0x1F44D not found, selecting one more font for (Arial, 400, 0)\n'
             'fontselect: (Arial, 400, 0) -> SegoeUIEmoji, 0, SegoeUIEmoji')
    failed = ('Glyph 0x10FFFF not found, selecting one more font for (Arial, 400, 0)\n'
              'fontselect: failed to find any fallback with glyph 0x10FFFF for font: (Arial, 400, 0)')
    record('captions: libass fallback success and unresolved glyphs are distinguished',
           not module.unresolved_libass_glyphs(found) and module.unresolved_libass_glyphs(failed))
    retried = found + '\nGlyph 0x1F44D not found, broken font? Trying all charmaps'
    orphan = 'Glyph 0x1F44D not found, broken font? Trying all charmaps'
    record('captions: alternate-charmap retry requires a verified prior fallback selection',
           not module.unresolved_libass_glyphs(retried) and module.unresolved_libass_glyphs(orphan))
    import re
    available = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True, check=True)
    has_ass = bool(re.search(r'^\s*[TSC.]{2,3}\s+ass\s', available.stdout, re.MULTILINE))
    cases = [('emoji', 'Go \U0001f44d'), ('cjk', 'Hello \u4e16\u754c'),
             ('arabic-emoji', '\u0645\u0631\u062d\u0628\u0627 \U0001f44d'),
             ('cjk-emoji', '\u4e16\u754c \U0001f44d')]
    for name, text in cases:
        try:
            module.complex_font(None, text)
        except ValueError:
            try:
                module.fallback_shaping_font(None, text)
            except ValueError:
                print('SKIP  captions: ' + name + ' fallback needs installed fonts covering the fixture')
                continue
            if not has_ass:
                print('SKIP  captions: ' + name + ' mixed-font shaping needs FFmpeg libass')
                continue
        preferred_missing, _ = module.basic_font_coverage(module.choose_font(None), text)
        caption = root / (name + '.srt')
        caption.write_text('1\n00:00:00,200 --> 00:00:01,000\n' + text + '\n', encoding='utf-8')
        out = root / (name + '.mp4')
        report = root / (name + '.json')
        code, output = tool('captions.py', 'burn', source, caption, '--out', out, '--json', report)
        data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
        selected = (data.get('cue_layouts') or [{}])[0]
        record('captions: ' + name + ' uses a covered per-cue font and reports fallback',
               code in (0, 1) and selected.get('missing_glyphs') == []
               and (not preferred_missing or any(item.get('rule') == 'caption font fallback'
                                                  for item in data.get('review', []))),
               f'layout={selected}; {output[-250:]}')
    try:
        module.complex_font(None, 'Go \U0001f44d')
        module.complex_font(None, 'Hello \u4e16\u754c')
    except ValueError:
        print('SKIP  captions: per-cue fallback comparison needs both CJK and emoji fonts')
    else:
        multicap = root / 'multiple.srt'
        multicap.write_text('1\n00:00:00,000 --> 00:00:00,300\nHello\n\n'
                            '2\n00:00:00,300 --> 00:00:00,600\nHello \u4e16\u754c\n\n'
                            '3\n00:00:00,600 --> 00:00:01,000\nGo \U0001f44d\n', encoding='utf-8')
        multiout, multireport = root / 'multiple.mp4', root / 'multiple.json'
        multi_code, multi_output = tool('captions.py', 'burn', source, multicap, '--out', multiout,
                                        '--json', multireport)
        multi = json.loads(multireport.read_text(encoding='utf-8')) if multireport.exists() else {}
        layouts = multi.get('cue_layouts', [])
        record('captions: a CJK or emoji cue does not change the ordinary cue face or refuse the burn',
               multi_code in (0, 1) and len(layouts) == 3 and layouts[0].get('font_path') == module.choose_font(None),
               f'layouts={layouts}; {multi_output[-250:]}')
    caption = root / 'sdr.srt'
    caption.write_text('1\n00:00:00,400 --> 00:00:01,000\nHello\n', encoding='utf-8')
    out = root / 'sdr.mp4'
    report = root / 'sdr.json'
    code, output = tool('captions.py', 'burn', source, caption, '--out', out, '--json', report)
    data = json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
    # An independent transparent YUV overlay and the source pixels test the measured colour change.
    from PIL import Image
    blank, reference = root / 'transparent.png', root / 'sdr-reference.mp4'
    Image.new('RGBA', (320, 180), (0, 0, 0, 0)).save(blank)
    graph = ('[0:v]setsar=1[base];[1:v]scale=out_color_matrix=bt709:out_range=tv,format=yuva420p[caption];'
             '[base][caption]overlay=0:0:eof_action=repeat:format=yuv420,'
             'setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv[out]')
    ref = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(source), '-loop', '1', '-i', str(blank),
                          '-filter_complex', graph, '-map', '[out]', '-frames:v', '1', '-c:v', 'libx264',
                          '-pix_fmt', 'yuv420p', '-crf', '14', '-color_primaries', 'bt709', '-color_trc', 'bt709',
                          '-colorspace', 'bt709', '-color_range', 'tv', str(reference)], capture_output=True)
    values = []
    for path in (source, out, reference):
        result = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-frames:v', '1', '-pix_fmt', 'rgb24',
                                 '-f', 'rawvideo', '-'], capture_output=True)
        if len(result.stdout) == 320 * 180 * 3:
            frame = np.frombuffer(result.stdout, np.uint8).reshape(180, 320, 3)
            values.append(np.stack([frame[20:80, x:x + 50].mean(axis=(0, 1)) for x in (15, 95, 175, 255)]))
    source_delta = float(np.max(np.abs(values[0] - values[1]))) if len(values) == 3 else float('inf')
    reference_delta = float(np.max(np.abs(values[2] - values[1]))) if len(values) == 3 else float('inf')
    record('captions: partial SDR tags preserve source patch colours through a burn',
           code in (0, 1) and partly_tagged and ref.returncode == 0 and source_delta <= 2 and reference_delta <= 2
           and 'not converted' in data.get('colour_conversion', ''),
           f'tags={tags}; source delta={source_delta:.2f}; reference delta={reference_delta:.2f}; {output[-200:]}')
def check_zero_length_word(tool, record, j):
    """A zero-length recognizer word remains in the speech check as estimated timing."""
    root = Path(j('captions-zero-word'))
    root.mkdir(parents=True, exist_ok=True)
    words = root / 'words.json'
    words.write_text(json.dumps({'engine': 'faster-whisper', 'words': [
        {'id': 'w1', 'text': 'But', 'start': 1.0, 'end': 1.0}]}), encoding='utf-8')
    srt = root / 'captions.srt'
    srt.write_text('1\n00:00:00,500 --> 00:00:02,000\nBut\n', encoding='utf-8')
    report = root / 'report.json'
    code, output = tool('captions.py', 'check', srt, '--words', words, '--json', report)
    result = json.loads(report.read_text(encoding='utf-8')) if report.is_file() else {}
    timing = result.get('timing_screen', {})
    record('captions: zero-length word remains estimated and checked',
           code == 0 and timing.get('estimated_word_times') and timing.get('coverage', {}).get('words') == 1,
           output[-300:])
    joined = root / 'joined.json'
    joined.write_text(json.dumps({'engine': 'faster-whisper', 'words': [
        {'id': 'w1', 'text': 'But', 'start': .5, 'end': .5},
        {'id': 'w2', 'text': 'why', 'start': .5, 'end': 1.1}]}), encoding='utf-8')
    code, output = tool('captions.py', 'build', joined, '--out', root / 'joined-out')
    record('captions: a zero-length word can adjoin the next word',
           code == 0 and (root / 'joined-out.srt').is_file(), output[-300:])
