"""Synthetic known-answer cases for grade.py."""
import hashlib
import gzip
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np


def load_module(scripts_dir):
    """Load the tool without invoking its command-line entry point."""
    spec = importlib.util.spec_from_file_location('lf_grade_cases', Path(scripts_dir) / 'grade.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path, value):
    """Write a test input in the isolated test directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1) + '\n', encoding='utf-8')


def audio_fixture(path, amplitude):
    """Create synthetic PCM with a known peak and no person's speech."""
    samples = [round(32767 * max(-1, min(1, amplitude * math.sin(index * 2 * math.pi * 200 / 16000))))
               for index in range(16000)]
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(np.asarray(samples, dtype='<i2').tobytes())


def stereo_fixture(path, opposite):
    """Write the same sinusoid in both channels, or cancel it exactly when folded to mono."""
    phase = np.arange(16000) * (2 * np.pi * 440 / 16000)
    left = np.asarray(np.sin(phase) * 12000, dtype='<i2')
    right = -left if opposite else left
    both = np.column_stack((left, right)).astype('<i2')
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(both.tobytes())


def stereo_movie(path, wav):
    """Mux the synthetic stereo tone with a small generated picture."""
    args = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=1',
            '-i', str(wav), '-shortest', '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', '-y', str(path)]
    return subprocess.run(args, capture_output=True, text=True)


def rating(identity, media, evidence, score=5, basis='judged', judge='self', independent=False):
    """Make a single judgment for merge tests."""
    return {'version': 1, 'packet_id': identity, 'media_sha256': media, 'judge': judge,
            'independent': independent, 'judge_provenance': {'model_family': 'synthetic-family',
                                                            'model': 'synthetic-model',
                                                            'same_family_as_cut_maker': True},
            'dimensions': [{'id': 'hook', 'score': score, 'basis': basis,
                            'confidence': 'high', 'evidence': evidence}]}


FFMPEG_51_ASTATS = {'DC_offset', 'Min_level', 'Max_level', 'Min_difference', 'Max_difference', 'Mean_difference',
                    'RMS_difference', 'Peak_level', 'RMS_level', 'RMS_peak', 'RMS_trough', 'Crest_factor',
                    'Flat_factor', 'Peak_count', 'Bit_depth', 'Dynamic_range', 'Zero_crossings',
                    'Zero_crossings_rate', 'Noise_floor', 'Noise_floor_count', 'Entropy', 'Number_of_samples',
                    'Number_of_NaNs', 'Number_of_Infs', 'Number_of_denormals'}


def oldest_ffmpeg_case(record, grade):
    """The analysis graph must run on the oldest supported FFmpeg (5.1): astats measures are named per release."""
    filters = {'signalstats', 'metadata', 'ebur128', 'astats', 'ametadata', 'aphasemeter'}
    graph, _ = grade.ffmpeg_graph({'audio': True, 'audio_channels': 2}, filters, 0.5, 160, 90)
    asked = set()
    for flags in re.findall(r'measure_(?:perchannel|overall)=([A-Za-z_+]+)', graph or ''):
        asked.update(flags.split('+'))
    record('grade: the analysis graph asks astats only for measures FFmpeg 5.1 has',
           bool(asked) and asked <= FFMPEG_51_ASTATS, str(sorted(asked - FFMPEG_51_ASTATS)))


def check_review_reads_every_frame(record, j, scripts_dir, grade):
    """Every frame frame_sheet writes for a 29.97 fps film, where most times are inexact (~), is read by the review
    packet; reading only exact times showed stale frames in join rows."""
    import sys
    folder = Path(j('review-ntsc'))
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / 'ntsc.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=30000/1001:d=2',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True)
    frames = folder / 'frames'
    frames.mkdir(exist_ok=True)
    times = [round(0.5 + step / 10, 6) for step in range(11)]
    subprocess.run([sys.executable, '-I', str(Path(scripts_dir) / 'frame_sheet.py'), str(video), '--at',
                    ','.join(f'{t:.6f}' for t in times), '--single', '--out', str(frames / 'frame.png')],
                   check=True, capture_output=True)
    names = [path.name for path in frames.iterdir() if path.suffix == '.png']
    stamps = [grade.review_frame_time(name) for name in names]
    record('grade review: every frame frame_sheet writes at 29.97 fps is read, inexact times included',
           len(names) >= 10 and all(stamp is not None for stamp in stamps) and any('~' in name for name in names)
           and grade.review_frame_time('frame-tile-001-at-~2.268933s.png') == 2.268933
           and grade.review_frame_time('frame-000022-at-0.733s.png') == 0.733, str(names[:4]))


def run_grade_cases(tool, record, j, scripts_dir):
    """Exercise measured signals, abstention, external files, project paths and evidence validation."""
    polish_grade_cases(tool, record, j)
    polish_legacy_paper_cases(tool, record, j)
    grade = load_module(scripts_dir)
    check_review_reads_every_frame(record, j, scripts_dir, grade)
    oldest_ffmpeg_case(record, grade)
    review_packet_cases(tool, record, j, scripts_dir, grade)
    run_loose_file_cases(tool, record, j, scripts_dir, grade)
    long_cue = [{'start': 0.0, 'end': 3.0, 'text': 'a clear and readable example caption'}]
    short_cue = [{'start': 0.0, 'end': 0.5, 'text': 'a clear and readable example caption'}]
    good_caption = grade.caption_facts(long_cue, 3)[0]
    bad_caption = grade.caption_facts(short_cue, 3)[0]
    record('grade: shorter identical caption raises timed reading rate and requests review',
           good_caption['wpm'] == 120 and bad_caption['wpm'] == 720
           and not good_caption['review'] and bad_caption['review'], str([good_caption, bad_caption]))
    audio_dir = Path(j('grade-audio'))
    audio_dir.mkdir(parents=True, exist_ok=True)
    normal = audio_dir / 'normal.wav'
    clipped = audio_dir / 'clipped.wav'
    audio_fixture(normal, 0.25)
    audio_fixture(clipped, 2.0)
    peak_values = []
    picture_values = []
    for wav in (normal, clipped):
        movie = audio_dir / (wav.stem + '.mkv')
        made = stereo_movie(movie, wav)
        if made.returncode:
            break
        result = grade.cached_measurements(movie, grade.probe(movie), grade.digest(movie), audio_dir / wav.stem)
        peak_values.append(result[4]['max_sample_peak_dbfs'])
        picture_values.append(result[0][0]['metrics']['y_avg'])
    record('grade: clipped synthetic PCM raises the measured peak without changing the picture',
           len(peak_values) == 2 and all(value is not None for value in peak_values + picture_values)
           and peak_values[1] > peak_values[0] + 8 and abs(picture_values[1] - picture_values[0]) < 1,
           str({'peaks_dbfs': peak_values, 'picture_y': picture_values}))
    prompts = grade.review_prompts({'timeline': {'caption_cues': [bad_caption],
                                                 'checks': [{'id': 'spec', 'state': 'fail', 'detail': 'size'}]},
                                    'audio': {'max_sample_peak_dbfs': 0.0, 'max_sample_peak_t': 1.0,
                                              'min_stereo_phase': -1.0, 'min_stereo_phase_t': 1.5}})
    record('grade: threshold and failed-check prompts name a diagnostic and the right dimension',
           [row['dimension'] for row in prompts] == ['text', 'mix', 'mix', 'platform_fit']
           and all(row['next'] for row in prompts), str(prompts))

    external = Path(j('grade-external'))
    external.mkdir(parents=True, exist_ok=True)
    media = external / 'synthetic.mp4'
    command = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=2',
               '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=2', '-shortest',
               '-c:v', 'mpeg4', '-c:a', 'aac', '-y', str(media)]
    made = subprocess.run(command, capture_output=True, text=True)
    record('grade: synthetic video fixture renders', made.returncode == 0, made.stderr[-500:])
    if made.returncode:
        return
    code, output = tool('grade.py', '--file', media, '--platform', 'web', '--kind', 'synthetic', '--no-transcribe')
    card_path = external / 'synthetic.scorecard.json'
    record('grade: --file outside a project writes both cards and a local packet',
           code == 1 and card_path.is_file() and (external / 'synthetic.scorecard.html').is_file()
           and (external / 'synthetic.grade' / 'packet' / 'packet.json').is_file(), output[-500:])
    if not card_path.is_file():
        return
    card = json.loads(card_path.read_text(encoding='utf-8'))
    record('grade: missing judgment stays waiting, never zero or an invented overall',
           card['overall']['scored'] == 0 and card['overall']['score'] is None
           and card['validation']['state'] in ('partial', 'unvalidated')
           and all(row['score'] is None and row['validation'] == grade.VALIDATION[row['id']]['state']
                   for row in card['dimensions']), str(card['overall']))
    cache = external / 'synthetic.grade' / 'frames.jsonl.gz'
    with gzip.open(cache, 'rt', encoding='utf-8') as stream:
        cached_rows = [json.loads(line) for line in stream]
    videos = [row for row in cached_rows if row.get('type') == 'video']
    audios = [row for row in cached_rows if row.get('type') == 'audio']
    footer = cached_rows[-1]
    record('grade: one-pass cache retains every synthetic frame and native FFmpeg timestamps',
           len(videos) == 20 and videos[0]['pts_time'] == 0 and abs(videos[-1]['pts_time'] - 1.9) < 0.001
           and 'lavfi.signalstats.YAVG' in videos[0]['values'] and footer['video']['frame_count'] == 20,
           str(footer.get('video', {})))
    record('grade: mixed audio has per-frame loudness and peak metadata without a mono phase claim',
           bool(audios) and 'lavfi.r128.M' in audios[0]['values']
           and footer['audio']['min_stereo_phase'] is None, str(footer.get('audio', {})))
    original_cache = cache.read_bytes()
    measured = grade.cached_measurements(media, grade.probe(media), grade.digest(media), external / 'synthetic.grade')
    record('grade: matching complete cache is reused without changing its bytes',
           measured[-1] is True and cache.read_bytes() == original_cache)
    dark = external / 'darkened.mp4'
    command = ['ffmpeg', '-v', 'error', '-i', str(media), '-vf', 'eq=brightness=-0.45',
               '-c:v', 'mpeg4', '-c:a', 'copy', '-y', str(dark)]
    made = subprocess.run(command, capture_output=True, text=True)
    if made.returncode:
        record('grade: darkening lowers FFmpeg luma while copied audio stays stable', False, made.stderr[-500:])
    else:
        dimmed = grade.cached_measurements(dark, grade.probe(dark), grade.digest(dark), external / 'dark-grade')
        before = measured[0][0]['metrics']['y_avg']
        after = dimmed[0][0]['metrics']['y_avg']
        audio_before = measured[4]['max_sample_peak_dbfs']
        audio_after = dimmed[4]['max_sample_peak_dbfs']
        record('grade: darkening lowers FFmpeg luma while copied audio stays stable',
               before > after + 20 and abs(audio_before - audio_after) < 0.1,
               str({'luma': [before, after], 'peaks_dbfs': [audio_before, audio_after]}))
    changed_rows = list(cached_rows)
    altered = dict(videos[0])
    altered['values'] = dict(altered['values'])
    altered['values']['lavfi.signalstats.YAVG'] = 1.0
    changed_rows[changed_rows.index(videos[0])] = altered
    payload = ''.join(json.dumps(row, separators=(',', ':')) + '\n' for row in changed_rows).encode('utf-8')
    cache.write_bytes(gzip.compress(payload))
    record('grade: corrupted cache content fails its checksum',
           grade.read_frame_cache(cache, cached_rows[0]['key']) is None)
    cache.write_bytes(original_cache)
    info = json.loads((external / 'synthetic.grade' / 'packet' / 'packet.json').read_text(encoding='utf-8'))
    _, available = grade.ffmpeg_capabilities()
    if {'waveform', 'vectorscope'}.issubset(available):
        scopes = external / 'synthetic.grade' / 'packet' / 'scopes' / 'index.json'
        record('grade: detected shot has indexed waveform and vectorscope pictures',
               info['scopes']['state'] == 'available' and scopes.is_file()
               and len(json.loads(scopes.read_text(encoding='utf-8'))['shots']) > 0, str(info['scopes']))
    else:
        print('NOT RUN  grade: waveform and vectorscope filters not installed', flush=True)
    code, output = tool('grade.py', '--file', media, '--platform', 'web', '--kind', 'synthetic', '--no-transcribe')
    rerun = json.loads(card_path.read_text(encoding='utf-8'))
    record('grade: unchanged evidence keeps the packet identity on a cached rerun',
           code == 1 and rerun['packet_id'] == card['packet_id'] and 'reused' in output, output[-400:])
    outside_review = external / 'review.json'
    outside_evidence = [{'t': 0, 'end': 0.1, 'kind': 'frame', 'ref': 'opening.png',
                         'note': 'The opening has a visible synthetic pattern.'}]
    outside_judgment = rating(card['packet_id'], card['media_sha256'], outside_evidence, independent=True)
    outside_judgment['judge_provenance']['same_family_as_cut_maker'] = None
    write_json(outside_review, outside_judgment)
    code, output = tool('grade.py', 'merge', outside_review, '--file', media)
    merged = json.loads(card_path.read_text(encoding='utf-8'))
    record('grade: standalone files keep model provenance and mark unknown family relationship low confidence',
           code == 1 and merged['dimensions'][0]['score'] == 5
           and merged['dimensions'][0]['basis'] == 'judged' and merged['dimensions'][0]['confidence'] == 'low'
           and merged['dimensions'][0]['judge_provenance']['same_family_as_cut_maker'] is None
           and merged['media_sha256'] == grade.digest(media), output[-400:])
    if 'aphasemeter' in available:
        phase_values = []
        for opposite in (False, True):
            name = 'opposite' if opposite else 'aligned'
            wav = audio_dir / (name + '.wav')
            movie = audio_dir / (name + '.mkv')
            stereo_fixture(wav, opposite)
            made = stereo_movie(movie, wav)
            if made.returncode:
                phase_values.append(None)
                continue
            result = grade.cached_measurements(movie, grade.probe(movie), grade.digest(movie), audio_dir / name)
            phase_values.append(result[4]['min_stereo_phase'])
        record('grade: stereo phase distinguishes aligned and cancelling channels',
               all(value is not None for value in phase_values)
               and phase_values[0] > 0.9 and phase_values[1] < -0.9, str(phase_values))
    else:
        print('NOT RUN  grade: aphasemeter filter not installed', flush=True)

    root = Path(j('grade-project'))
    cut = root / 'cuts' / 'v001'
    cut.mkdir(parents=True, exist_ok=True)
    shutil.copy2(media, cut / 'preview.mp4')
    (root / 'cuts' / 'current').write_text('v001\n', encoding='utf-8')
    word_data = [{'text': 'The', 'start': 0.2, 'end': 0.35, 'id': 'int_01-w1'},
                 {'text': 'sky', 'start': 0.4, 'end': 0.55, 'id': 'int_01-w2'},
                 {'text': 'is', 'start': 0.6, 'end': 0.7, 'id': 'int_01-w3'},
                 {'text': 'clear.', 'start': 0.75, 'end': 1.0, 'id': 'int_01-w4'}]
    line = {'line': 6, 'section': 'Hook', 'kind': 'spoken', 'start': 0.2, 'end': 1.0, 'words': word_data}
    write_json(cut / 'lines.json', {'version': 1, 'lines': [line]})
    write_json(cut / 'manifest.json', {'version': 'v001', 'parent': None})
    (cut / 'captions.srt').write_text('1\n00:00:00,200 --> 00:00:01,500\nThe sky is clear.\n', encoding='utf-8')
    (root / 'film.md').write_text('---\nsize: 160x90\nfps: 10\n---\n## Hook\n'
                                  '> int_01 0:00.20-0:01.00 The sky is clear.\n', encoding='utf-8')
    media_hash = hashlib.sha256(media.read_bytes()).hexdigest()
    source = {'alias': 'int_01', 'role': 'interview', 'path': str(media), 'sha256': media_hash,
              'duration_s': 2.0, 'video': {'width': 160, 'height': 90, 'fps': '10'},
              'audio': {'channels': 1, 'rate': 16000}}
    write_json(root / 'map' / 'sources.json', {'version': 1, 'sources': [source]})
    write_json(root / 'map' / 'int_01' / 'words.json', {'draft': True, 'words': word_data})
    write_json(root / 'map' / 'int_01' / 'audio.json', {'silences': [{'start': 0, 'end': 0.15},
                                                                       {'start': 1.05, 'end': 1.9}]})
    scores_path = root / 'scores.json'
    write_json(scores_path, {'version': 1, 'scores': {'v001': {'cta': {'score': 3, 'by': 'person',
                                                                       'at': '2026-10-29T12:00:00Z'}}}})
    source_scores = scores_path.read_bytes()
    code, output = tool('grade.py', root)
    project_card = cut / 'scorecard.json'
    record('grade: project grade uses edit-timed words, captions and the version path',
           code == 1 and project_card.is_file(), output[-500:])
    if not project_card.is_file():
        return
    card = json.loads(project_card.read_text(encoding='utf-8'))
    original_video = (cut / 'preview.mp4').read_bytes()
    original_card = project_card.read_bytes()
    try:
        (cut / 'preview.mp4').write_bytes(original_video + b'changed')
        code, output = tool('grade.py', 'scores', root)
        record('grade: score refresh refuses a changed file hash without changing the card',
               code == 2 and project_card.read_bytes() == original_card, output[-400:])
    finally:
        (cut / 'preview.mp4').write_bytes(original_video)
    cta = next(row for row in card['dimensions'] if row['id'] == 'cta')
    record('grade: initial grade reads the room score without changing scores.json',
           cta['score'] == 3 and cta['basis'] == 'person' and scores_path.read_bytes() == source_scores,
           str(cta))
    write_json(scores_path, {'version': 1, 'scores': {'v001': {}}})
    code, output = tool('grade.py', 'scores', root)
    refreshed = json.loads(project_card.read_text(encoding='utf-8'))
    cta = next(row for row in refreshed['dimensions'] if row['id'] == 'cta')
    record('grade: removing a person score restores an unscored dimension',
           code == 1 and cta['score'] is None and cta['status'] == 'waiting', output[-400:])
    record('grade: sidecar timing and opening word are visible as measurements',
           card['dimensions'][0]['measures']['first_word_s'] == 0.2
           and card['dimensions'][7]['measures']['caption_cues'][0]['words'] == 4, str(card['dimensions'][0]))

    item = {'t': 0.2, 'end': 1.0, 'kind': 'transcript', 'ref': 'transcript.md',
            'note': 'The opening states the subject.', 'quote': 'The sky is clear'}
    submission = Path(j('grade-judgment.json'))
    template = rating(card['packet_id'], card['media_sha256'], [item])
    template['dimensions'][0]['fix'] = {'text': 'Try another opening.', 'line': 6, 'gain': 2}
    invalid_provenance = dict(template)
    invalid_provenance.pop('judge_provenance')
    write_json(submission, invalid_provenance)
    original = project_card.read_bytes()
    code, output = tool('grade.py', 'merge', root, submission)
    record('grade: merge refuses a judgment without structured model provenance',
           code == 2 and project_card.read_bytes() == original, output[-400:])
    invalid_provenance = dict(template, judge_provenance={'model_family': 'family', 'model': 'model',
                                                          'same_family_as_cut_maker': 'false'})
    write_json(submission, invalid_provenance)
    code, output = tool('grade.py', 'merge', root, submission)
    record('grade: merge refuses a non-boolean family relationship',
           code == 2 and project_card.read_bytes() == original, output[-400:])
    for label, evidence in [('no evidence', []),
                            ('time outside film', [dict(item, t=3.0, end=3.5)]),
                            ('invented quote', [dict(item, quote='an invented phrase')]),
                            ('quote at a non-overlapping word boundary', [dict(item, t=0.35, end=0.4, quote='The')]),
                            ('outside packet', [dict(item, ref='../scorecard.json')])]:
        write_json(submission, rating(card['packet_id'], card['media_sha256'], evidence))
        original = project_card.read_bytes()
        code, output = tool('grade.py', 'merge', root, submission)
        record('grade: merge refuses ' + label + ' without changing the card',
               code == 2 and project_card.read_bytes() == original, output[-400:])
    write_json(submission, template)
    code, output = tool('grade.py', 'merge', root, submission)
    updated = json.loads(project_card.read_text(encoding='utf-8'))
    hook = updated['dimensions'][0]
    record('grade: valid self-judgment merges with low confidence and quoted evidence',
           code == 1 and hook['score'] == 5 and hook['basis'] == 'judged'
           and hook['confidence'] == 'low' and hook['evidence'][0]['quote'] == item['quote']
           and hook['judge_provenance']['model_family'] == 'synthetic-family'
           and hook['judge_provenance']['model'] == 'synthetic-model'
           and hook['judge_provenance']['same_family_as_cut_maker'] is True, output[-400:])
    write_json(submission, rating(card['packet_id'], card['media_sha256'], [item], score=7,
                                  basis='person', judge='person', independent=False))
    original = project_card.read_bytes()
    code, output = tool('grade.py', 'merge', root, submission)
    record('grade: merge refuses a fabricated person rating',
           code == 2 and project_card.read_bytes() == original, output[-400:])
    write_json(scores_path, {'version': 1, 'scores': {'v001': {'hook': {'score': 7, 'by': 'person',
                                                                        'at': '2026-10-29T12:00:00Z'}}}})
    source_scores = scores_path.read_bytes()
    code, output = tool('grade.py', 'scores', root)
    updated = json.loads(project_card.read_text(encoding='utf-8'))
    hook = updated['dimensions'][0]
    record('grade: room rating takes precedence and retains the judgment and its attributed fix',
           code == 1 and hook['score'] == 7 and hook['basis'] == 'person'
           and updated['overall']['score'] == 70 and len(hook['assessments']) == 2
           and hook['assessments'][0]['judge_provenance']['model'] == 'synthetic-model'
           and hook['evidence'][0]['t'] is None and hook['fix_source']['judged_by'] == 'self'
           and hook['fix_source']['t'] == 0.2 and scores_path.read_bytes() == source_scores, output[-400:])
    write_json(scores_path, {'version': 1, 'scores': {'v001': {'hook': {'score': 2, 'by': 'person',
                                                                        'at': '2026-10-29T12:01:00Z'}}}})
    code, output = tool('grade.py', 'scores', root)
    updated = json.loads(project_card.read_text(encoding='utf-8'))
    hook = updated['dimensions'][0]
    record('grade: a changed room score replaces only the room assessment',
           code == 1 and hook['score'] == 2 and len(hook['assessments']) == 2
           and any(assessment['score'] == 5 for assessment in hook['assessments']), output[-400:])
    write_json(scores_path, {'version': 1, 'scores': {'v001': {}}})
    code, output = tool('grade.py', 'scores', root)
    updated = json.loads(project_card.read_text(encoding='utf-8'))
    hook = updated['dimensions'][0]
    record('grade: removing a room score restores the prior reviewer rating',
           code == 1 and hook['score'] == 5 and hook['basis'] == 'judged'
           and len(hook['assessments']) == 1, output[-400:])
    write_json(scores_path, {'version': 1, 'scores': {'v001': {'hook': {'score': True, 'by': 'person',
                                                                        'at': '2026-10-29T12:02:00Z'}}}})
    original = project_card.read_bytes()
    code, output = tool('grade.py', 'scores', root)
    record('grade: invalid room scores are rejected without changing the card',
           code == 2 and project_card.read_bytes() == original, output[-400:])
    write_json(scores_path, {'version': 1, 'scores': {'v001': {'hook': {'score': 7, 'by': 'person',
                                                                        'at': '2026-10-29T12:03:00Z'}}}})
    write_json(submission, template)
    code, output = tool('grade.py', 'merge', root, submission)
    updated = json.loads(project_card.read_text(encoding='utf-8'))
    hook = updated['dimensions'][0]
    record('grade: merging a review also refreshes the room score',
           code == 1 and hook['score'] == 7 and hook['basis'] == 'person'
           and len(hook['assessments']) == 3, output[-400:])
    packet_transcript = cut / 'grade' / 'packet' / 'transcript.md'
    saved = packet_transcript.read_bytes()
    packet_transcript.write_bytes(saved + b'changed')
    write_json(submission, template)
    original = project_card.read_bytes()
    code, output = tool('grade.py', 'merge', root, submission)
    record('grade: merge refuses a packet changed after grading',
           code == 2 and project_card.read_bytes() == original, output[-400:])
    packet_transcript.write_bytes(saved)
    code, output = tool('grade.py', 'hooks', root, '--alias', 'int_01')
    hooks = json.loads((root / 'grade' / 'hooks.json').read_text(encoding='utf-8'))
    record('grade: hooks report spoken length and mapped quiet boundaries',
           code == 1 and len(hooks['candidates']) == 1 and hooks['candidates'][0]['spoken_length_s'] == 0.8
           and hooks['candidates'][0]['quiet_before_s'] == 0.15
           and hooks['candidates'][0]['source_hash'] == 'matched', output[-400:])
    code, output = tool('grade.py', 'paper', root)
    paper = root / 'grade' / 'paper.json'
    paper_data = json.loads(paper.read_text(encoding='utf-8')) if paper.is_file() else {}
    record('grade: paper compiles without rendering and waits for four judgments',
           code == 1 and len(paper_data.get('dimensions', [])) == 4 and paper_data.get('duration_estimate_s', 0) > 0
           and not any(item['severity'] == 'error' for item in paper_data.get('problems', [])), output[-400:])
    paper_words = grade.timed_words(paper_data['lines'], [])
    paper_judgment = {'version': 1, 'paper_id': paper_data['paper_id'], 'judge': 'self', 'independent': False,
                      'judge_provenance': {'model_family': 'synthetic-family', 'model': 'synthetic-model',
                                           'same_family_as_cut_maker': True},
                      'dimensions': [{'id': 'hook', 'score': 6, 'confidence': 'high',
                                      'evidence': [{'t': paper_words[0]['start'], 'end': paper_words[1]['end'],
                                                    'quote': 'The sky', 'note': 'The opening states the subject.'}]}]}
    paper_input = Path(j('grade-paper-judgment.json'))
    write_json(paper_input, paper_judgment)
    code, output = tool('grade.py', 'paper', root, '--judged', paper_input)
    reviewed = json.loads(paper.read_text(encoding='utf-8'))
    record('grade: paper review stores a supported score without rendering',
           code == 1 and reviewed['dimensions'][0]['score'] == 6
           and reviewed['dimensions'][0]['confidence'] == 'low'
           and reviewed['dimensions'][0]['evidence'][0]['quote'] == 'The sky', output[-400:])
    paper_judgment['paper_id'] = 'stale'
    write_json(paper_input, paper_judgment)
    original = paper.read_bytes()
    code, output = tool('grade.py', 'paper', root, '--judged', paper_input)
    record('grade: paper review rejects a stale edit without changing its scores',
           code == 2 and paper.read_bytes() == original, output[-400:])
    code, output = tool('grade.py', 'thumbs', media)
    record('grade: thumbs writes a sheet and does not claim click prediction',
           code == 1 and (external / 'synthetic.grade' / 'thumbs.jpg').is_file()
           and 'not click prediction' in json.loads((external / 'synthetic.grade' / 'thumbs.json')
                                                    .read_text())['selection'],
           output[-400:])


def review_packet_cases(tool, record, j, scripts_dir, grade):
    """Render a two-source known-answer edit and inspect the independent-review packet."""
    fixture_path = Path(scripts_dir) / 'selftest_cases' / 'cut.py'
    spec = importlib.util.spec_from_file_location('review_cut_fixtures', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    media = Path(j('review-media'))
    media.mkdir(parents=True, exist_ok=True)
    fixture.make_source(media, 'int_01', 12, fixture.PATCHES['int'])
    fixture.make_source(media, 'int_02', 12, fixture.PATCHES['broll'])
    root = Path(j('review-project'))
    (root / 'map').mkdir(parents=True, exist_ok=True)
    (root / 'media').mkdir(exist_ok=True)
    sources = []
    for alias in ('int_01', 'int_02'):
        shutil.copy2(media / (alias + '.mkv'), root / 'media' / (alias + '.mkv'))
        sources.append(fixture.source_row(alias, 'interview', 'media/' + alias + '.mkv', 12))
        fixture.write_words(root, alias, fixture.WORDS)
    write_json(root / 'map' / 'sources.json', {'version': 1, 'sources': sources})
    film = ('---\ntitle: Review case\nsize: 320x180\nfps: 25\ntarget: 45\ncaptions: srt, vtt\n'
            'audience: reviewers\ntakeaway: test the packet\nstory: two source passages\n---\n'
            '## First\n> int_01 0:00.30-0:04.50 alpha bravo ~~charlie delta~~ echo foxtrot\n'
            '  ~ int_02 0:01.00-0:01.20 +0.35 short cutaway\n'
            '  ~ int_02 0:02.00-0:02.80 +2.00 long cutaway\n'
            '## Second\n> int_02 0:06.30-0:09.20 golf hotel india juliet\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    check_code, check_output = tool('cut.py', 'check', root)
    warning_lines = [line for line in check_output.splitlines() if ': warning: ' in line]
    code, output = tool('cut.py', 'render', root)
    cut = root / 'cuts' / 'v001'
    exists = (cut / 'preview.mp4').is_file()
    record('grade review: two-source synthetic project renders with cut.py', code in (0, 1) and exists,
           output[-1200:])
    if not exists:
        return
    rendered_edit = json.loads((cut / 'edit.json').read_text(encoding='utf-8'))
    first_clip = rendered_edit['picture'][0]
    candidate = (first_clip['in'] + first_clip['out']) / 2
    write_json(root / 'map' / 'int_01' / 'shots.json',
               {'source': 'int_01', 'sampled': False, 'shots': [{'start': 0}, {'start': candidate}]})
    # The planted shot change alters what cut.py check reports (busy cutting and flash frames count source shots), so
    # the warnings the packet must carry verbatim are the ones after it.
    check_code, check_output = tool('cut.py', 'check', root)
    warning_lines = [line for line in check_output.splitlines() if ': warning: ' in line]
    write_json(cut / 'checks.json', {'version': 1, 'items': [
        {'id': 'known', 'state': 'look', 'label': 'planted warning', 'detail': 'inspect this', 'at': 2.5},
        {'id': 'fine', 'state': 'pass', 'label': 'do not include'}]})
    (root / 'film.md').write_text(film.replace('target: 45', 'target: 6'), encoding='utf-8')
    code, output = tool('grade.py', 'review', root, '--version', 'v001')
    packet = cut / 'review'
    expected_files = ('film.mp4', 'overview.png', 'opening.png', 'ending.png', 'joins.png', 'transcript.txt',
                      'joins.txt', 'checks.txt', 'brief.md', 'README.txt')
    # Compare resolved paths: a Windows runner's temp folder can be reached by its short 8.3 name (RUNNER~1) while
    # the script prints the long one.
    printed = {os.path.normcase(os.path.realpath(line.strip())) for line in output.splitlines() if line.strip()}
    record('grade review: packet has every requested file and prints its path', code == 0
           and all((packet / name).is_file() for name in expected_files)
           and os.path.normcase(os.path.realpath(str(packet))) in printed, output[-1200:])
    if not (packet / 'joins.txt').is_file():
        return
    lines = json.loads((cut / 'lines.json').read_text(encoding='utf-8'))['lines']
    edit = json.loads((cut / 'edit.json').read_text(encoding='utf-8'))
    manifest = json.loads((cut / 'manifest.json').read_text(encoding='utf-8'))
    events, _ = grade.review_events(edit, lines, manifest['duration_s'])
    groups = grade.review_groups(events)
    spoken = [line for line in lines if line['kind'] == 'spoken']
    cutaways = [line for line in lines if line['kind'] == 'cutaway']
    def has_event(at, kind):
        return any(event['kind'] == kind and abs(event['at'] - at) < .002 for event in events)
    skip = spoken[0].get('audio_cuts') or []
    source_change = any(event['kind'] == 'speech' and event['before']['source'] == 'int_01'
                        and event['after']['source'] == 'int_02' for event in events)
    boundaries = len(cutaways) == 2 and all(has_event(line[edge], 'picture') for line in cutaways
                                             for edge in ('start', 'end'))
    merged = any(len([event for event in group if event['kind'] == 'picture']) >= 2
                 and len(cutaways) == 2 and abs(group[0]['at'] - cutaways[0]['start']) < .002
                 and any(abs(event['at'] - cutaways[0]['end']) < .002 for event in group) for group in groups)
    joins = (packet / 'joins.txt').read_text(encoding='utf-8')
    record('grade review: source-map scene changes inside a rendered clip are labelled as unverified candidates',
           f"mapped scene-change candidate: int_01 {grade.P.format_time(candidate)} (unverified)" in joins,
           joins[-1200:])
    every_time = all(grade.P.format_time(event['at']) in joins for event in events)
    record('grade review: source change, source skip, cutaway in/out and merged pair are all listed',
           source_change and bool(skip) and all(has_event(at, 'speech') for at in skip) and boundaries and merged
           and every_time, str({'skip': skip, 'cutaways': cutaways, 'events': events}))
    captions = json.loads((cut / 'captions.json').read_text(encoding='utf-8'))['cues']
    transcript = (packet / 'transcript.txt').read_text(encoding='utf-8')
    cue_times = all(f"[{grade.P.format_time(cue['start'])}-{grade.P.format_time(cue['end'])}]" in transcript
                    for cue in captions)
    record('grade review: transcript uses caption times and identifies each spoken source and range',
           bool(captions) and cue_times and 'int_01 | source' in transcript and 'int_02 | source' in transcript
           and 'Rendered source runs:' in transcript,
           transcript[-1200:])
    checks = (packet / 'checks.txt').read_text(encoding='utf-8')
    record('grade review: non-pass item and verbatim version-specific cut warnings survive',
           check_code == 0 and bool(warning_lines) and all(line in checks for line in warning_lines)
           and 'planted warning' in checks and '0:02.50' in checks and 'do not include' not in checks, checks[-1200:])
    brief = (packet / 'brief.md').read_text(encoding='utf-8')
    direction = (packet / 'direction.md').read_text(encoding='utf-8')
    record('grade review: the brief lists source transcripts and keeps the direction in its own file',
           'direction.md' in brief and 'audience: reviewers' not in brief and 'int_01' in brief
           and 'transcript.md' in brief and 'Read only after writing your first impression' in direction
           and 'audience: reviewers' in direction and 'takeaway: test the packet' in direction
           and 'story: two source passages' in direction, brief[-600:] + direction[-600:])
    (packet / 'obsolete.txt').write_text('old packet', encoding='utf-8')
    code, output = tool('grade.py', 'review', root, '--version', 'v001')
    record('grade review: rebuilding replaces the prior packet', code == 0 and not (packet / 'obsolete.txt').exists(),
           output[-600:])
    silent = root / 'cuts' / 'v002'
    silent.mkdir()
    shutil.copy2(cut / 'preview.mp4', silent / 'preview.mp4')
    duration = manifest['duration_s']
    timeline_end = duration - .2
    write_json(silent / 'manifest.json', {'version': 'v002', 'duration_s': duration})
    write_json(silent / 'lines.json', {'duration_s': timeline_end, 'lines': [
        {'line': 1, 'kind': 'picture', 'source': 'int_01', 'start': 0, 'end': timeline_end,
         'range': [0, timeline_end]}]})
    write_json(silent / 'edit.json', {'picture': [{'src': 'int_01', 'in': 0, 'out': timeline_end}], 'audio': [],
                                      'overlays': [{'kind': 'image', 'src': 'title-test', 'from': .1,
                                                    'to': timeline_end}]})
    write_json(silent / 'captions.json', {'cues': []})
    write_json(silent / 'checks.json', {'items': []})
    (silent / 'film.md').write_text('---\nsize: 320x180\nfps: 25\ncaptions: none\n---\n'
                                    'For newcomers, the story is a single picture.\n'
                                    '- int_01 0:00.00-0:03.00\n', encoding='utf-8')
    code, output = tool('grade.py', 'review', root, '--version', 'v002')
    transcript = silent / 'review' / 'transcript.txt'
    record('grade review: a version without speech gets a packet that says so', code == 0 and transcript.is_file()
           and 'No speech or timed transcript' in transcript.read_text(encoding='utf-8'), output[-1000:])
    silent_joins = (silent / 'review' / 'joins.txt').read_text(encoding='utf-8') if code == 0 else output
    record('grade review: an overlay ending at the timeline end is not listed as an interior join',
           code == 0 and 'overlay title-test appears' in silent_joins
           and 'overlay title-test ends' not in silent_joins, silent_joins[-1000:])
    silent_brief = (silent / 'review' / 'direction.md').read_text(encoding='utf-8') if code == 0 else output
    record('grade review: direction written as prose is kept in direction.md after the first-impression prompt',
           code == 0 and 'For newcomers, the story is a single picture.' in silent_brief
           and silent_brief.index('Read only after writing your first impression')
           < silent_brief.index('For newcomers, the story is a single picture.'), silent_brief[-1000:])
    empty = root / 'cuts' / 'v003'
    empty.mkdir()
    write_json(empty / 'edit.json', {'picture': [], 'audio': []})
    code, output = tool('grade.py', 'review', root, '--version', 'v003')
    readme = empty / 'review' / 'README.txt'
    record('grade review: missing preview and other version files are disclosed in a written packet',
           code == 0 and readme.is_file() and 'preview.mp4 is missing' in readme.read_text(encoding='utf-8')
           and 'no picture clips' in readme.read_text(encoding='utf-8')
           and (empty / 'review' / 'overview.png').is_file(), output[-1000:])
    srt_version = root / 'cuts' / 'v004'
    srt_version.mkdir()
    for name in ('preview.mp4', 'film.md', 'edit.json', 'lines.json', 'manifest.json', 'captions.srt'):
        shutil.copy2(cut / name, srt_version / name)
    code, output = tool('grade.py', 'review', root, '--version', 'v004')
    srt_transcript = srt_version / 'review' / 'transcript.txt'
    transcript = srt_transcript.read_text(encoding='utf-8') if srt_transcript.is_file() else output
    record('grade review: SRT supplies timed speech when caption JSON is missing', code == 0
           and 'alpha' in transcript.lower() and 'captions.json is missing' in transcript
           and f"[{grade.P.format_time(captions[0]['start'])}-{grade.P.format_time(captions[0]['end'])}]"
           in transcript, transcript[-1000:])
    review_edge_cases(record, grade)


def review_edge_cases(record, grade):
    """Known-answer timing for merged joins, source changes and partially unassigned caption cues."""
    edit = {'picture': [{'src': 'int_01', 'in': 0, 'out': 2},
                        {'src': 'int_02', 'in': 1, 'out': 1.2},
                        {'src': 'int_01', 'in': 2, 'out': 4}],
            'audio': [{'track': 'dialogue', 'src': 'int_01', 'in': 0, 'out': 2, 'at': 0},
                      {'track': 'dialogue', 'src': 'int_01', 'in': 5, 'out': 7, 'at': 2},
                      {'track': 'dialogue', 'src': 'int_02', 'in': 1, 'out': 2, 'at': 4}]}
    events, _ = grade.review_events(edit, [], 5)
    pairs = [(round(row['at'], 2), row['kind']) for row in events]
    groups = grade.review_groups(events)
    record('grade review: independently specified join times and merged rows are exact',
           pairs == [(2, 'picture'), (2, 'speech'), (2.2, 'picture'), (4, 'speech')]
           and [len(group) for group in groups] == [3, 1], str((pairs, groups)))
    moving = dict(edit, overlays=[{'kind': 'video', 'src': 'broll_02', 'from': 0.5, 'to': 1.5}])
    landed = [event['detail'] for event in grade.review_events(moving, [], 5)[0] if 'overlay' in event['detail']]
    record('grade review: a moving graphic (~ over) lands and leaves in the review packet',
           landed == ['overlay broll_02 appears', 'overlay broll_02 ends'], str(landed))
    events, _ = grade.review_events(edit, [], 5, {'int_01': [.5]})
    mapped = [event for event in events if 'mapped scene-change candidate' in event['detail']]
    record('grade review: mapped source cuts retain their film time and the surrounding shot lengths',
           len(mapped) == 1 and abs(mapped[0]['at'] - .5) < 1e-6
           and abs(mapped[0]['before']['length'] - .5) < 1e-6
           and abs(mapped[0]['after']['length'] - 1.5) < 1e-6, str(mapped))
    lines = [{'kind': 'spoken', 'source': 'int_01', 'start': .2, 'end': 1, 'range': [0, 1]},
             {'kind': 'spoken', 'source': 'int_02', 'start': 1, 'end': 2, 'range': [2, 3]}]
    captions = {'cues': [{'start': 0, 'end': 2.4, 'words': [
        {'text': 'Early', 'start': .1, 'end': .15}, {'text': 'Alpha', 'start': .3, 'end': .5},
        {'text': 'Bravo', 'start': 1.1, 'end': 1.3}, {'text': 'Orphan', 'start': 2.1, 'end': 2.2}]}]}
    transcript = grade.review_transcript(lines, captions, [])
    record('grade review: a cue spanning lines retains every word, including words without a source line',
           all(word in transcript for word in ('Early', 'Alpha', 'Bravo', 'Orphan'))
           and transcript.index('Early') < transcript.index('Alpha') < transcript.index('Bravo')
           < transcript.index('Orphan') and 'source line and range unavailable' in transcript.lower(), transcript)
    index, uncertain = grade.review_cue_line(lines, .9, 1.6)
    record('grade review: a caption without word times uses maximum line overlap and flags ambiguity',
           index == 1 and uncertain, str((index, uncertain)))


SPEAK = r"""
param([string]$Text, [string]$Out)
Add-Type -AssemblyName System.Speech
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice.Rate = -1
$voice.SetOutputToWaveFile($Out)
$voice.Speak($Text)
$voice.SetOutputToNull()
"""


def speech_ready():
    """Why local transcription cannot be exercised here, or '' when it can (never downloads weights)."""
    if importlib.util.find_spec('faster_whisper') is None:
        return 'faster-whisper is not installed (setup.py --install transcription)'
    if importlib.util.find_spec('onnxruntime') is None:
        return 'faster-whisper is installed without onnxruntime (setup.py --install transcription)'
    if os.name != 'nt' or not (shutil.which('powershell') or shutil.which('powershell.exe')):
        return 'the synthetic voice needs Windows speech synthesis (System.Speech)'
    try:
        from faster_whisper.utils import download_model
        download_model('small', local_files_only=True)
    except Exception:
        return 'the faster-whisper small model is not downloaded'
    return ''


def synthetic_speech(folder, text):
    """A WAV of synthetic speech from Windows System.Speech, or None."""
    shell = shutil.which('powershell') or shutil.which('powershell.exe')
    folder.mkdir(parents=True, exist_ok=True)
    script = folder / 'speak.ps1'
    wav = folder / 'speech.wav'
    script.write_text(SPEAK, encoding='utf-8')
    result = subprocess.run([shell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Text', text,
                             '-Out', str(wav)], capture_output=True, text=True, timeout=120)
    return wav if result.returncode == 0 and wav.is_file() else None


def picture_with(path, wav, size='160x90', pattern='testsrc2'):
    """Mux a generated picture with a WAV so the file has the WAV's duration."""
    args = ['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'{pattern}=size={size}:rate=10', '-i', str(wav),
            '-shortest', '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', '-y', str(path)]
    return subprocess.run(args, capture_output=True, text=True)


def bursts_fixture(path, noise_dbfs=None):
    """Four 0.6 s tone bursts standing in for words, with silent pauses or broadband noise under everything."""
    rate = 16000
    time = np.arange(rate * 7) / rate
    signal = np.zeros_like(time)
    for start in (0.5, 2.0, 3.5, 5.0):
        inside = (time >= start) & (time < start + 0.6)
        signal[inside] = 0.3 * np.sin(2 * np.pi * 300 * time[inside])
    if noise_dbfs is not None:
        noise = np.random.default_rng(7).standard_normal(len(time))
        noise *= 10 ** (noise_dbfs / 20) / np.sqrt(np.mean(noise ** 2))
        signal = signal + noise
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(np.asarray(np.clip(signal, -1, 1) * 32767, dtype='<i2').tobytes())


def loose_card(folder, stem):
    """Read the per-file card of a loose file, or None."""
    path = folder / (stem + '.scorecard.json')
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def dimension(card, key):
    """One dimension row of a card, or an empty dict."""
    return next((row for row in (card or {}).get('dimensions', []) if row['id'] == key), {})


def loose_pair(folder):
    """Two different synthetic loose files in one folder."""
    first = folder / 'first.mp4'
    second = folder / 'second.mp4'
    for path, pattern in ((first, 'testsrc2'), (second, 'smptebars')):
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'{pattern}=size=160x90:rate=10:duration=2',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=2', '-shortest',
                        '-c:v', 'mpeg4', '-c:a', 'aac', '-y', str(path)], capture_output=True, text=True)
    return first, second


def relative_path_case(record, grade, first, folder):
    """Measurement must not depend on the temporary working folder FFmpeg runs in."""
    try:
        relative = Path(os.path.relpath(first))
    except ValueError:
        print('NOT RUN  grade: relative path case needs the work folder on the current drive', flush=True)
        return
    try:
        measured = grade.cached_measurements(relative, grade.probe(relative), grade.digest(relative),
                                             folder / 'relative-grade')
        ok = measured[3]['frame_count'] == 20
        detail = str(measured[3]['frame_count'])
    except Exception as error:
        ok = False
        detail = str(error)[-300:]
    record('grade: measurement accepts a relative video path', ok, detail)


def transcript_cases(tool, record, grade, folder, first):
    """No transcript is stated plainly; --words imports words or cues; a quoted review merges."""
    card = loose_card(folder, 'first') or {}
    transcript = card.get('transcript') or {}
    packet_text = folder / 'first.grade' / 'packet' / 'transcript.md'
    note = packet_text.read_text(encoding='utf-8') if packet_text.is_file() else ''
    record('grade: a loose file without a transcript says so and how to get one',
           transcript.get('state') == 'not_run' and '--words' in transcript.get('next', '')
           and dimension(card, 'hook').get('measures', {}).get('transcript') == 'not_run'
           and 'No transcript' in note and '--words' in note, str(transcript))
    grade.find_spec = lambda name: None
    try:
        missing = grade.local_transcript(first, folder / 'first.grade', grade.digest(first), True, True)
    finally:
        grade.find_spec = importlib.util.find_spec
    record('grade: without faster-whisper the transcript is not available and names the install',
           missing[0] == [] and missing[1]['state'] == 'not_available'
           and '--install transcription' in missing[1]['next'], str(missing[1]))
    words = [{'text': 'The', 'start': 0.2, 'end': 0.35}, {'text': 'sky', 'start': 0.4, 'end': 0.55},
             {'text': 'is', 'start': 0.6, 'end': 0.7}, {'text': 'clear.', 'start': 0.75, 'end': 1.0}]
    words_file = folder / 'first-words.json'
    write_json(words_file, {'words': words})
    code, output = tool('grade.py', '--file', first, '--words', words_file)
    card = loose_card(folder, 'first') or {}
    note = packet_text.read_text(encoding='utf-8') if packet_text.is_file() else ''
    record('grade: --words puts the timed words of a loose file in its packet and measures',
           code == 1 and (card.get('transcript') or {}).get('state') == 'imported'
           and dimension(card, 'hook').get('measures', {}).get('first_word_s') == 0.2 and '0.200-0.350  The' in note,
           output[-400:])
    review = folder / 'first-review.json'
    evidence = [{'t': 0.2, 'end': 1.0, 'kind': 'transcript', 'ref': 'transcript.md', 'quote': 'The sky is clear',
                 'note': 'The opening states the subject.'}]
    write_json(review, rating(card.get('packet_id'), card.get('media_sha256'), evidence, independent=True))
    code, output = tool('grade.py', 'merge', review, '--file', first)
    hook = dimension(loose_card(folder, 'first'), 'hook')
    record('grade: a quoted review of a loose file merges into its own card',
           code == 1 and hook.get('score') == 5 and hook.get('evidence', [{}])[0].get('quote') == 'The sky is clear',
           output[-400:])
    cues = folder / 'first.srt'
    cues.write_text('1\n00:00:00,200 --> 00:00:01,000\nThe sky is clear.\n', encoding='utf-8')
    code, output = tool('grade.py', '--file', first, '--words', cues)
    transcript = (loose_card(folder, 'first') or {}).get('transcript') or {}
    record('grade: --words accepts caption cues and marks their word times as estimates',
           code == 1 and transcript.get('state') == 'imported' and transcript.get('estimated_times') is True,
           output[-400:])
    code, output = tool('grade.py', '--file', first, '--words', folder / 'missing.json')
    record('grade: a missing --words file is an error, not a silent empty transcript',
           code == 2 and 'words' in output.lower(), output[-300:])


def local_transcription_case(tool, record, folder):
    """With faster-whisper and its small model cached, a loose file is transcribed locally and cached."""
    reason = speech_ready()
    if reason:
        print('NOT RUN  grade: local transcription of a loose file: ' + reason, flush=True)
        return
    spoken = synthetic_speech(folder / 'speech', 'The sky is clear tonight, and the stars are out.')
    movie = folder / 'spoken.mkv'
    made = picture_with(movie, spoken) if spoken else None
    if not made or made.returncode:
        print('NOT RUN  grade: local transcription of a loose file: speech synthesis failed', flush=True)
        return
    code, output = tool('grade.py', '--file', movie)
    card = loose_card(folder, 'spoken') or {}
    transcript = card.get('transcript') or {}
    text = folder / 'spoken.grade' / 'packet' / 'transcript.md'
    heard = text.read_text(encoding='utf-8').lower() if text.is_file() else ''
    record('grade: a loose file is transcribed locally with faster-whisper into its packet',
           code == 1 and transcript.get('state') == 'transcribed'
           and 'faster-whisper' in transcript.get('engine', '') and 'sky' in heard, output[-400:])
    again_code, again = tool('grade.py', '--file', movie)
    record('grade: a repeated grade reuses the cached transcript and keeps the packet identity',
           again_code == 1 and 'transcript: reused' in again
           and (loose_card(folder, 'spoken') or {}).get('packet_id') == card.get('packet_id'), again[-400:])


def detail_and_sound_cases(tool, record, folder):
    """Readable stills for text and image detail; a level picture and speech-versus-pause levels for sound."""
    wide = folder / 'wide.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=10:duration=2',
                    '-c:v', 'mpeg4', '-q:v', '4', '-y', str(wide)], capture_output=True, text=True)
    code, output = tool('grade.py', '--file', wide, '--no-transcribe')
    info_path = folder / 'wide.grade' / 'packet' / 'packet.json'
    detail = (json.loads(info_path.read_text(encoding='utf-8')) if info_path.is_file() else {}).get('detail') or {}
    sheet = folder / 'wide.grade' / 'packet' / 'detail.png'
    width = 0
    if sheet.is_file():
        from PIL import Image
        with Image.open(sheet) as image:
            width = image.size[0]
    record('grade: the packet has readable detail stills, not only thumbnails',
           detail.get('state') == 'available' and detail.get('tile_width') == 640
           and len(detail.get('times', [])) >= 6 and width >= 1280, str(detail) + output[-300:])
    levels = []
    for name, noise in (('quiet', None), ('noisy', -32)):
        wav = folder / (name + '.wav')
        bursts_fixture(wav, noise)
        movie = folder / (name + '.mkv')
        picture_with(movie, wav)
        cue_words = folder / (name + '-words.json')
        write_json(cue_words, {'words': [{'text': 'word', 'start': start + half, 'end': start + half + 0.3}
                                         for start in (0.5, 2.0, 3.5, 5.0) for half in (0.0, 0.3)]})
        tool('grade.py', '--file', movie, '--words', cue_words)
        levels.append(dimension(loose_card(folder, name), 'voice').get('measures', {}).get('speech_vs_pause') or {})
    gaps = [row.get('speech_minus_pause_lu') for row in levels]
    record('grade: noise under the pauses lowers the measured speech-versus-pause level difference',
           all(finite(value) for value in gaps) and gaps[0] - gaps[1] > 10
           and (folder / 'noisy.grade' / 'packet' / 'sound.png').is_file(), str(levels))
    record('grade: digital silence stays in the loudness series at the floor instead of vanishing',
           levels[0].get('pause_lufs') == -70.0
           and levels[0].get('pause_windows', 0) >= 0.9 * levels[1].get('pause_windows', 1), str(levels))
    cutoff = folder / 'cutoff.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=4',
                    '-f', 'lavfi', '-i', 'anoisesrc=color=pink:amplitude=0.6:r=48000:d=2', '-f', 'lavfi', '-i',
                    'anullsrc=r=48000:cl=stereo:d=2', '-filter_complex',
                    '[1:a]aformat=channel_layouts=stereo[n];[n][2:a]concat=n=2:v=0:a=1[a]', '-map', '0:v', '-map',
                    '[a]', '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', '-y', str(cutoff)], capture_output=True, text=True)
    tool('grade.py', '--file', cutoff, '--no-transcribe')
    measured = folder / 'cutoff.grade' / 'packet' / 'measurements.json'
    series = json.loads(measured.read_text(encoding='utf-8'))['audio']['momentary_lufs'] if measured.is_file() else []
    tail = [row['lufs'] for row in series if row['t'] > 2.6]
    record('grade: a hard cut to digital silence after loud sound stays in the loudness series as silence',
           len(tail) >= 10 and all(value <= -70 for value in tail), f'{len(tail)} rows after the cut')
    sparse_words = folder / 'quiet-sparse.json'
    write_json(sparse_words, {'words': [{'text': 'You', 'start': 0.5, 'end': 1.1}]})
    tool('grade.py', '--file', folder / 'quiet.mkv', '--words', sparse_words)
    card = loose_card(folder, 'quiet') or {}
    levels = dimension(card, 'voice').get('measures', {}).get('speech_vs_pause') or {}
    record('grade: one word over a whole film is flagged as sparse and gives no speech-versus-pause number',
           (card.get('transcript') or {}).get('sparse') is True and levels.get('state') != 'measured'
           and 'speech_minus_pause_lu' not in levels, str(card.get('transcript')) + str(levels))
    voice_prompts = []
    for name, noise in (('hiss', -24), ('clean', None)):
        wav = folder / (name + '.wav')
        bursts_fixture(wav, noise)
        movie = folder / (name + '.mkv')
        picture_with(movie, wav)
        tool('grade.py', '--file', movie, '--words', folder / 'quiet-words.json')
        card = loose_card(folder, name) or {}
        voice_prompts.append([row for row in card.get('review_prompts', []) if row.get('dimension') == 'voice'])
    record('grade: background within 15 LU of the speech raises a listen prompt; a clean pause does not',
           len(voice_prompts[0]) == 1 and 'listen' in voice_prompts[0][0]['next'].lower() and not voice_prompts[1],
           str(voice_prompts))
    strobe = folder / 'strobe.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', "nullsrc=size=160x90:rate=10:duration=2,"
                    "geq=lum='if(mod(N,2),235,16)':cb=128:cr=128", '-c:v', 'mpeg4', '-q:v', '3', '-y', str(strobe)],
                   capture_output=True, text=True)
    steady = folder / 'steady.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10:duration=2',
                    '-c:v', 'mpeg4', '-y', str(steady)], capture_output=True, text=True)
    prompts = []
    for movie in (strobe, steady):
        tool('grade.py', '--file', movie, '--no-transcribe')
        card = loose_card(folder, movie.stem) or {}
        prompts.append([row for row in card.get('review_prompts', []) if row.get('dimension') == 'access'])
    record('grade: rapid full-frame luma reversals raise an access prompt; a steady picture does not',
           len(prompts[0]) == 1 and 'flash' in prompts[0][0]['text'].lower() and not prompts[1], str(prompts))


def run_loose_file_cases(tool, record, j, scripts_dir, grade):
    """A loose file gets its own outputs, a transcript or a plain statement that it has none, readable stills,
    speech-versus-pause levels and per-dimension validation states."""
    folder = Path(j('grade-loose'))
    folder.mkdir(parents=True, exist_ok=True)
    first, second = loose_pair(folder)
    relative_path_case(record, grade, first, folder)
    outputs = [tool('grade.py', '--file', path, '--no-transcribe') for path in (first, second)]
    cards = [loose_card(folder, 'first'), loose_card(folder, 'second')]
    packets = [folder / (stem + '.grade') / 'packet' / 'packet.json' for stem in ('first', 'second')]
    record('grade: two loose files in one folder keep separate cards and packets',
           all(cards) and cards[0]['media_sha256'] == grade.digest(first)
           and cards[1]['media_sha256'] == grade.digest(second) and all(path.is_file() for path in packets)
           and json.loads(packets[0].read_text(encoding='utf-8'))['media_sha256'] == grade.digest(first),
           str([output[-300:] for _, output in outputs]))
    states = {row['id']: row.get('validation') for row in (cards[1] or {}).get('dimensions', [])}
    allowed = {'passed_degradation_test', 'partly_passed', 'correlated_with_human_ratings', 'unvalidated'}
    table = getattr(grade, 'VALIDATION', {})
    record('grade: each dimension states its validation and what it rests on',
           len(states) == 15 and set(states.values()) <= allowed
           and all(row.get('validation_detail') for row in (cards[1] or {}).get('dimensions', []))
           and all(states[key] == table.get(key, {}).get('state') for key in states)
           and 'Passed a blind degradation test' in (folder / 'second.scorecard.html').read_text(encoding='utf-8'),
           str(states))
    transcript_cases(tool, record, grade, folder, first)
    local_transcription_case(tool, record, folder)
    detail_and_sound_cases(tool, record, folder)


def finite(value):
    """A finite number, not a boolean."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def polish_grade_cases(tool, record, j):
    """Paper judgments follow the compiled edit, and hook ranking states its limited basis."""
    root = Path(j('polish-grade'))
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    media = root / 'source.wav'
    media.write_bytes(b'synthetic')
    sha = hashlib.sha256(media.read_bytes()).hexdigest()
    source = {'alias': 'int_01', 'path': 'source.wav', 'role': 'interview', 'sha256': sha,
              'duration_s': 20, 'audio': {'index': 0}, 'video': None}
    write_json(root / 'map' / 'sources.json', {'sources': [source]})
    words = [{'id': 'int_01-w000001', 'text': 'The', 'start': .1, 'end': .3},
             {'id': 'int_01-w000002', 'text': 'sky', 'start': .4, 'end': .6},
             {'id': 'int_01-w000003', 'text': 'changed.', 'start': .7, 'end': .9}]
    write_json(folder / 'words.json', {'words': words})
    write_json(folder / 'audio.json', {'silences': [{'start': .9, 'end': 1.4}]})
    film = ('---\ntitle: Case\nsize: 320x180\nfps: 25\naudience: editors\n'
            'takeaway: the sky changed\nstory: a short example\n---\n## Opening\n'
            '> int_01 0:00.00-0:01.20 The sky changed.\nA note for the reader.\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    code, output = tool('grade.py', 'paper', root)
    path = root / 'grade' / 'paper.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if not data.get('lines'):
        record('grade: paper fixture compiled', False, output)
        return
    line = data['lines'][0]['line']
    judgment = {'version': 1, 'paper_id': data['paper_id'], 'judge': 'reviewer', 'independent': True,
                'judge_provenance': {'model_family': 'synthetic', 'model': 'fixture',
                                     'same_family_as_cut_maker': False},
                'dimensions': [{'id': 'hook', 'score': 6, 'confidence': 'medium',
                                'evidence': [{'t': .1, 'end': .6, 'quote': 'The sky', 'note': 'Clear.'}],
                                'fix': {'text': 'Review opening', 'line': line}}]}
    submission = root / 'judgment.json'
    write_json(submission, judgment)
    tool('grade.py', 'paper', root, '--judged', submission)
    with_note = film.replace('> int_01', 'Another reader note.\n> int_01')
    (root / 'film.md').write_text(with_note, encoding='utf-8')
    code, output = tool('grade.py', 'paper', root)
    after = json.loads(path.read_text(encoding='utf-8'))
    first = after['dimensions'][0]
    record('grade: note edits preserve review identity, score, and current fix line',
           after['paper_id'] == data['paper_id'] and first['score'] == 6
           and first['fix']['line'] == after['lines'][0]['line'], output)
    check_code, check_output = tool('cut.py', 'check', root, '--json', '--no-audio')
    try:
        checked = json.loads(check_output)
        physical = checked['lines'][0]['line']
        paper_text = (root / 'grade' / 'paper.md').read_text(encoding='utf-8')
        same = (after['timeline']['sections'][0]['lines'] == [physical]
                and 'film.md lines ' + str(physical) in paper_text)
    except (ValueError, KeyError, IndexError):
        same = False
    record('grade: paper section line numbers match cut check', check_code == 0 and same, check_output[-500:])
    (root / 'film.md').write_text(with_note.replace('audience: editors', 'audience: farmers'), encoding='utf-8')
    code, output = tool('grade.py', 'paper', root)
    newer = json.loads(path.read_text(encoding='utf-8'))
    history = root / 'grade' / 'paper-history'
    record('grade: changed direction preserves the old review and reports the mismatch',
           newer['paper_id'] != data['paper_id'] and newer['dimensions'][0]['score'] is None
           and history.is_dir() and bool(list(history.glob('*.json'))) and 'no longer match' in output.lower(),
           output)
    (root / 'film.md').write_text(with_note, encoding='utf-8')
    code, output = tool('grade.py', 'paper', root)
    restored = json.loads(path.read_text(encoding='utf-8'))
    record('grade: returning to an earlier paper edit restores its judgment',
           restored['paper_id'] == data['paper_id'] and restored['dimensions'][0]['score'] == 6, output)
    titles = with_note.replace('> int_01', '- title "First" 0.3\n- title "Second" 0.3\n> int_01')
    (root / 'film.md').write_text(titles, encoding='utf-8')
    tool('grade.py', 'paper', root)
    with_titles = json.loads(path.read_text(encoding='utf-8'))['paper_id']
    (root / 'film.md').write_text(titles.replace('"First"', '"Changed"'), encoding='utf-8')
    tool('grade.py', 'paper', root)
    changed_title = json.loads(path.read_text(encoding='utf-8'))['paper_id']
    (root / 'film.md').write_text(titles.replace('- title "First" 0.3\n- title "Second" 0.3',
                                                '- title "Second" 0.3\n- title "First" 0.3'), encoding='utf-8')
    tool('grade.py', 'paper', root)
    reordered = json.loads(path.read_text(encoding='utf-8'))['paper_id']
    (root / 'film.md').write_text(titles.replace('The sky changed.', 'The sky'), encoding='utf-8')
    tool('grade.py', 'paper', root)
    changed_words = json.loads(path.read_text(encoding='utf-8'))['paper_id']
    record('grade: title text, line order, and spoken words each change paper identity',
           len({with_titles, changed_title, reordered, changed_words}) == 4,
           str((with_titles, changed_title, reordered, changed_words)))
    for name in ('paper', 'hooks', 'review'):
        code, output = tool('grade.py', name, '--help')
        expected = {'paper': ('paper', 'judged', 'paper_id', 'dimensions'),
                    'hooks': ('hooks', 'alias', 'all'), 'review': ('review', 'version')}[name]
        record('grade: ' + name + ' help describes its own interface',
               code == 0 and all(term in output.lower() for term in expected), output[-800:])
    candidates = []
    silences = []
    for n in range(7):
        start = n * 2.0
        sentence = ['And', 'there', 'is', 'quite', 'a', 'long', 'story.'] if n < 6 else ['Costs', 'dropped', 'fast.']
        for k, word in enumerate(sentence):
            candidates.append({'id': 'int_01-w%06d' % (len(candidates) + 1), 'text': word,
                               'start': start + k * .15, 'end': start + k * .15 + .1})
        silences.append({'start': candidates[-1]['end'], 'end': start + 1.8})
    write_json(folder / 'words.json', {'words': candidates})
    write_json(folder / 'audio.json', {'silences': silences})
    code, output = tool('grade.py', 'hooks', root)
    hooks = json.loads((root / 'grade' / 'hooks.json').read_text(encoding='utf-8'))
    first = hooks.get('candidates', [{}])[0]
    record('grade: hooks ranks the short self-contained candidate with measured quiet first',
           first.get('text') == 'Costs dropped fast.' and 'quiet' in first.get('reason', '').lower()
           and len(hooks['candidates']) < 7 and 'Costs dropped fast.' in output
           and 'mapped quiet after' in output.lower(), output)
    code, output = tool('grade.py', 'hooks', root, '--all')
    hooks = json.loads((root / 'grade' / 'hooks.json').read_text(encoding='utf-8'))
    record('grade: hooks --all shows every candidate in rank order',
           code == 1 and len(hooks['candidates']) == 7
           and hooks['candidates'][0]['text'] == 'Costs dropped fast.'
           and output.count('And there is quite a long story.') == 6, output)


def polish_legacy_paper_cases(tool, record, j):
    """Keep verifiable original-format judgments after notes change, but reject changed film or brief."""
    root = Path(j('polish-legacy-paper'))
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    source = root / 'source.wav'
    source.write_bytes(b'synthetic')
    row = {'alias': 'int_01', 'path': 'source.wav', 'role': 'interview',
           'sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'duration_s': 3,
           'audio': {'index': 0}, 'video': None}
    write_json(root / 'map' / 'sources.json', {'sources': [row]})
    words = [{'id': 'int_01-w000001', 'text': 'The', 'start': .1, 'end': .3},
             {'id': 'int_01-w000002', 'text': 'sky', 'start': .4, 'end': .6},
             {'id': 'int_01-w000003', 'text': 'changed.', 'start': .7, 'end': .9}]
    write_json(folder / 'words.json', {'words': words})
    film = ('---\nsize: 320x180\nfps: 25\naudience: editors\n'
            'takeaway: the sky changed\nstory: an example\n---\n## Opening\n'
            '> int_01 0:00.00-0:01.20 The sky changed.\nA reader note.\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    tool('grade.py', 'paper', root)
    paper = root / 'grade' / 'paper.json'
    result = json.loads(paper.read_text(encoding='utf-8'))
    judgment = {'version': 1, 'paper_id': result['paper_id'], 'judge': 'reviewer', 'independent': True,
                'judge_provenance': {'model_family': 'synthetic', 'model': 'fixture',
                                     'same_family_as_cut_maker': False},
                'dimensions': [{'id': 'hook', 'score': 6, 'confidence': 'medium',
                                'evidence': [{'t': .1, 'end': .6, 'quote': 'The sky', 'note': 'Clear.'}],
                                'fix': {'text': 'Inspect', 'line': result['lines'][0]['line']}}]}
    submission = root / 'judgment.json'
    write_json(submission, judgment)
    tool('grade.py', 'paper', root, '--judged', submission)
    legacy = json.loads(paper.read_text(encoding='utf-8'))
    identity = {'film': legacy['film_md_sha256'], 'settings': legacy['settings'], 'lines': legacy['lines'],
                'problems': legacy['problems'], 'brief': '',
                'rubric': 'b64f2f90e30544988bd2f22f11ca74ba72cc987c918d4764653d36a44ef1b8bc'}
    legacy['paper_id'] = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                                  separators=(',', ':')).encode('utf-8')).hexdigest()
    legacy.pop('paper_identity_version', None)
    write_json(paper, legacy)
    different = Path(j('polish-legacy-changed'))
    brief = Path(j('polish-legacy-brief'))
    for path in (different, brief):
        shutil.copytree(root, path, ignore=shutil.ignore_patterns('__pycache__'))
    (root / 'film.md').write_text(film.replace('> int_01', 'Another note.\n> int_01'), encoding='utf-8')
    code, output = tool('grade.py', 'paper', root)
    migrated = json.loads(paper.read_text(encoding='utf-8'))
    dimension = migrated['dimensions'][0]
    record('grade: a verified legacy review survives a note edit and updates its fix line',
           code == 1 and dimension['score'] == 6 and dimension['fix']['line'] == migrated['lines'][0]['line']
           and 'no longer match' not in output.lower(), output)
    (different / 'film.md').write_text(film.replace('The sky changed.', 'The sky'), encoding='utf-8')
    code, output = tool('grade.py', 'paper', different)
    changed = json.loads((different / 'grade' / 'paper.json').read_text(encoding='utf-8'))
    record('grade: a changed compiled edit cannot inherit a legacy judgment',
           changed['dimensions'][0]['score'] is None and 'no longer match' in output.lower(), output)
    (brief / 'brief.md').write_text('Audience: a different audience\n', encoding='utf-8')
    code, output = tool('grade.py', 'paper', brief)
    changed = json.loads((brief / 'grade' / 'paper.json').read_text(encoding='utf-8'))
    record('grade: a changed brief cannot inherit a legacy judgment',
           changed['dimensions'][0]['score'] is None and 'no longer match' in output.lower(), output)
