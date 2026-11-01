#!/usr/bin/env python3
"""Grade one evaluation run against independently held fixture answers.

  python evals/grade_task.py TASK --run RUN_DIR --fixtures FIXTURE_DIR --out grade.json
  python evals/grade_task.py TASK --run RUN_DIR --fixtures FIXTURE_DIR --skill-check

The deterministic checks are bounded proxies. Publisher captions are not verified
transcripts; matching audio excerpts cannot prove every word survived; dimensions
and independent review remain not_run until evidence is supplied. Grade results
are pass, fail or inconclusive; an unavailable check never counts as a pass.
--skill-check runs check.py on the delivered file, so run it as one heavy job at
a time. Exit 0 for pass, 1 for fail or inconclusive,
2 for an invalid invocation or unavailable task definition.
"""
import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
PROJECT_PATH = HERE.parent / 'skills' / 'legible-film' / 'scripts' / 'project.py'
SPEC = importlib.util.spec_from_file_location('eval_project', PROJECT_PATH)
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def tasks():
    """Return the catalogue keyed by stable task ID."""
    data = P.load_json(HERE / 'tasks.json')
    return {task['id']: task for task in data['tasks']}


def under(root, relative):
    """Resolve a supplied relative path without escaping its own directory."""
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'path escapes its directory: {relative}')
    return path


def check_result(name, state, detail, **fields):
    """Represent every result, including an explicit reason for missing evidence."""
    return {'id': name, 'state': state, 'detail': detail, **fields}


def probe(path):
    """Read container and stream properties; never infer quality from a probe."""
    command = ['ffprobe', '-v', 'error', '-show_entries',
               'stream=codec_type,width,height:format=duration', '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('ffprobe could not read the delivered file: ' + result.stderr[-500:])
    data = json.loads(result.stdout)
    picture = next((row for row in data.get('streams', []) if row.get('codec_type') == 'video'), None)
    if not picture:
        raise ValueError('no video stream')
    return {'duration': float(data['format']['duration']), 'width': int(picture['width']),
            'height': int(picture['height']),
            'audio': any(row.get('codec_type') == 'audio' for row in data.get('streams', []))}


def video(rule, workspace):
    """Check actual delivered dimensions and duration."""
    path = under(workspace, rule['path'])
    if not path.is_file():
        return 'fail', f'missing {rule["path"]}'
    info = probe(path)
    low, high = rule['duration']
    duration_ok = low <= info['duration'] <= high
    aspect = info['width'] / info['height']
    ratio_ok = 'aspect' not in rule or abs(aspect - rule['aspect']) <= 0.01
    audio_ok = not rule.get('audio_required') or info['audio']
    return ('pass' if duration_ok and ratio_ok and audio_ok else 'fail'), f'probe={info}; aspect={aspect:.4f}'


def timestamp(value):
    """Parse an SRT timestamp into seconds."""
    match = re.fullmatch(r'(\d+):(\d{2}):(\d{2})[,.](\d{3})', value.strip())
    if not match:
        raise ValueError(f'invalid caption timestamp: {value}')
    hours, minutes, seconds, millis = map(int, match.groups())
    if minutes > 59 or seconds > 59:
        raise ValueError(f'invalid caption timestamp: {value}')
    return hours * 3600 + minutes * 60 + seconds + millis / 1000


def read_srt(path):
    """Read cues without assuming the delivered cue boundaries match the reference."""
    text = P.read_text(path).replace('\r\n', '\n').replace('\r', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if '-->' in line), None)
        if timing is None:
            raise ValueError('caption block has no timing line')
        start_text, end_text = lines[timing].split('-->', 1)
        start = timestamp(start_text)
        end = timestamp(end_text.strip().split()[0])
        if end <= start or (cues and start < cues[-1]['start']):
            raise ValueError('caption timing is invalid or out of order')
        caption = ' '.join(lines[timing + 1:]).lower().replace('\u2019', "'")
        words = re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?", caption)
        if not words:
            raise ValueError('empty caption')
        cues.append({'start': start, 'end': end, 'words': words})
    if not cues:
        raise ValueError('no captions')
    return cues


def word_positions(cues):
    """Approximate word locations within cues, never a word-edge alignment."""
    result = []
    for cue in cues:
        span = cue['end'] - cue['start']
        for number, word in enumerate(cue['words']):
            midpoint = cue['start'] + span * (number + 0.5) / len(cue['words'])
            result.append((word, midpoint))
    return result


def caption_comparison(rule, workspace, fixtures):
    """Compare words and coarse timings to publisher captions, with declared limits."""
    path = under(workspace, rule['path'])
    reference = under(fixtures / 'references', rule['reference'])
    if not path.is_file():
        return 'fail', f'missing {rule["path"]}'
    if not reference.is_file():
        return 'not_run', f'missing grader reference {rule["reference"]}'
    try:
        expected = word_positions(read_srt(reference))
    except (OSError, ValueError) as error:
        return 'not_run', f'invalid grader reference: {error}'
    actual = word_positions(read_srt(path))
    left = [word for word, _ in expected]
    right = [word for word, _ in actual]
    matcher = difflib.SequenceMatcher(a=left, b=right, autojunk=False)
    edits = 0
    offsets = []
    for operation, a, b, c, d in matcher.get_opcodes():
        if operation == 'equal':
            offsets.extend(abs(expected[i][1] - actual[c + i - a][1]) for i in range(a, b))
        else:
            edits += max(b - a, d - c)
    mismatch = edits / max(1, len(left))
    timing = float(np.median(offsets)) if offsets else float('inf')
    passed = mismatch == 0 and timing <= 0.8
    detail = (f'publisher-reference token mismatch {mismatch:.3f}; median cue-based time error {timing:.3f}s; '
              'not independently checked speech or word-edge timing')
    return ('pass' if passed else 'fail'), detail


def audio_samples(path):
    """Decode mono 8 kHz samples for a bounded excerpt-matching proxy."""
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-i', str(path), '-vn', '-ac', '1', '-ar', '8000',
               '-t', '120', '-f', 'f32le', 'pipe:1']
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise ValueError('audio decode failed: ' + result.stderr.decode(errors='replace')[-400:])
    return np.frombuffer(result.stdout, dtype='<f4').astype(np.float64)


def correlations(signal, template):
    """Normalized zero-mean cross-correlation over all candidate offsets."""
    if len(template) < 100 or len(signal) < len(template):
        return np.array([])
    target = template - template.mean()
    energy = float(np.dot(target, target))
    if energy < 1e-8:
        return np.array([])
    size = 1 << (len(signal) + len(target) - 2).bit_length()
    convolution = np.fft.irfft(np.fft.rfft(signal, size) * np.fft.rfft(target[::-1], size), size)
    dots = convolution[len(target) - 1:len(signal)]
    sums = np.concatenate(([0.0], np.cumsum(signal)))
    squares = np.concatenate(([0.0], np.cumsum(signal * signal)))
    window_sum = sums[len(target):] - sums[:-len(target)]
    window_power = squares[len(target):] - squares[:-len(target)] - window_sum ** 2 / len(target)
    denominator = np.sqrt(np.maximum(window_power * energy, 1e-20))
    return np.clip(dots / denominator, 0, 1)


def peak_correlation(signal, template):
    """Return the strongest correlation, or zero for an unusable excerpt."""
    values = correlations(signal, template)
    return float(np.max(values)) if len(values) else 0.0


def audio_chunks(rule, workspace, fixtures):
    """Detect a few unchanged excerpts from source in delivered audio."""
    delivered = under(workspace, rule['path'])
    source = under(fixtures / 'inputs', rule['source'])
    if not delivered.is_file():
        return 'fail', f'missing {rule["path"]}'
    if not source.is_file():
        return 'not_run', f'missing grader source {rule["source"]}'
    try:
        original = audio_samples(source)
    except (OSError, ValueError) as error:
        return 'not_run', f'cannot decode grader source: {error}'
    output = audio_samples(delivered)
    correlations = []
    for start, end in rule['intervals']:
        snippet = original[round(start * 8000):round(end * 8000)]
        correlations.append(peak_correlation(output, snippet))
    passed = all(value >= 0.30 for value in correlations)
    detail = f'normalized excerpt correlations {[round(value, 3) for value in correlations]}; not a word-loss proof'
    return ('pass' if passed else 'fail'), detail


def audio_repeat(rule, workspace, fixtures):
    """Find separate occurrences of a known false-start excerpt in the delivered audio."""
    delivered = under(workspace, rule['path'])
    source = under(fixtures / 'inputs', rule['source'])
    if not delivered.is_file():
        return 'fail', f'missing {rule["path"]}'
    if not source.is_file():
        return 'not_run', f'missing grader source {rule["source"]}'
    try:
        original = audio_samples(source)
    except (OSError, ValueError) as error:
        return 'not_run', f'cannot decode grader source: {error}'
    output = audio_samples(delivered)
    start, end = rule['interval']
    sample = original[round(start * 8000):round(end * 8000)]
    values = correlations(output, sample)
    candidates = np.flatnonzero(values >= rule.get('threshold', 0.45))
    positions = []
    for index in candidates[np.argsort(values[candidates])[::-1]]:
        if all(abs(int(index) - other) >= 6400 for other in positions):
            positions.append(int(index))
    positions.sort()
    count = len(positions)
    if count == 0:
        return 'not_run', 'the false-start reference excerpt was not detected; inspect alignment and audio'
    detail = f'{count} excerpt occurrences at {[round(index / 8000, 3) for index in positions]}s; proxy only'
    return ('fail' if count > 1 else 'pass'), detail


def screen_states(rule, workspace, fixtures):
    """Compare a few output frames with the three known tutorial interface states."""
    video_path = under(workspace, rule['path'])
    if not video_path.is_file():
        return 'fail', f'missing {rule["path"]}'
    templates = []
    for name in rule['references']:
        reference = under(fixtures / 'references', name)
        if not reference.is_file():
            return 'not_run', f'missing screen reference {name}'
        with Image.open(reference) as image:
            templates.append(np.asarray(image.convert('RGB').resize((160, 90)), dtype=np.float32))
    actual = []
    scores = []
    for moment in rule['samples_s']:
        command = ['ffmpeg', '-hide_banner', '-v', 'error', '-ss', str(moment), '-i', str(video_path),
                   '-frames:v', '1', '-vf', 'scale=160:90', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
        result = subprocess.run(command, capture_output=True)
        if result.returncode or len(result.stdout) != 160 * 90 * 3:
            raise ValueError(f'cannot decode tutorial frame at {moment}s')
        frame = np.frombuffer(result.stdout, np.uint8).reshape(90, 160, 3).astype(np.float32)
        errors = [float(np.mean((frame - template) ** 2)) for template in templates]
        best = int(np.argmin(errors))
        actual.append(best)
        scores.append(round(errors[best], 2))
    expected = list(range(len(rule['samples_s'])))
    passed = actual == expected and all(value < 300 for value in scores)
    detail = f'states={actual}, expected={expected}, mean pixel errors={scores}; sampled frames only'
    return ('pass' if passed else 'fail'), detail


def cursor_presence(rule, workspace):
    """Check the planted red tutorial pointer at sampled frames, not arbitrary pointers."""
    path = under(workspace, rule['path'])
    if not path.is_file():
        return 'fail', f'missing {rule["path"]}'
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-i', str(path), '-t', '90', '-an',
               '-vf', 'fps=2,scale=90:160', '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1']
    result = subprocess.run(command, capture_output=True)
    frame_size = 90 * 160 * 3
    if result.returncode or not result.stdout or len(result.stdout) % frame_size:
        raise ValueError('cannot decode sampled tutorial frames')
    frames = np.frombuffer(result.stdout, np.uint8).reshape(-1, 160, 90, 3).astype(np.int16)
    red = ((frames[:, :, :, 0] > 150) & (frames[:, :, :, 0] > frames[:, :, :, 1] * 1.4) &
           (frames[:, :, :, 0] > frames[:, :, :, 2] * 1.4))
    counts = np.sum(red, axis=(1, 2))
    missing = np.flatnonzero(counts < 2)
    detail = f'planted red pointer absent in {len(missing)}/{len(frames)} sampled frames; colour proxy only'
    return ('fail' if len(missing) else 'pass'), detail


def gray_frames(path):
    """Decode a bounded two-frame-per-second grayscale sequence for source matching."""
    filters = 'fps=2,scale=64:36:force_original_aspect_ratio=decrease,pad=64:36:(ow-iw)/2:(oh-ih)/2'
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-i', str(path), '-t', '90', '-an', '-vf', filters,
               '-pix_fmt', 'gray', '-f', 'rawvideo', 'pipe:1']
    result = subprocess.run(command, capture_output=True)
    if result.returncode or not result.stdout or len(result.stdout) % (64 * 36):
        raise ValueError('cannot decode sampled picture frames')
    return np.frombuffer(result.stdout, np.uint8).reshape(-1, 36, 64).astype(np.float32)


def shot_sequence(rule, workspace, fixtures):
    """Identify source shots at sampled frames; uncertainty remains not_run."""
    output = under(workspace, rule['path'])
    if not output.is_file():
        return 'fail', f'missing {rule["path"]}'
    references = []
    for name in rule['sources']:
        source = under(fixtures / 'inputs', name)
        if not source.is_file():
            return 'not_run', f'missing source shot {name}'
        try:
            references.append(gray_frames(source))
        except (OSError, ValueError) as error:
            return 'not_run', f'cannot decode source shot {name}: {error}'
    samples = gray_frames(output)
    labels = []
    uncertain = 0
    for frame in samples:
        distances = [float(np.min(np.mean((group - frame) ** 2, axis=(1, 2)))) for group in references]
        order = np.argsort(distances)
        best, second = int(order[0]), int(order[1])
        if distances[best] > 1600 or distances[second] - distances[best] < 100:
            uncertain += 1
            continue
        if not labels or labels[-1] != best:
            labels.append(best)
    if not labels or uncertain > len(samples) / 4:
        return 'not_run', f'could not classify {uncertain}/{len(samples)} sampled frames; inspect shot identities'
    repeated = len(set(labels)) != len(labels)
    missing = sorted(set(range(len(references))) - set(labels))
    detail = f'sampled source sequence={labels}; repeated={repeated}; missing={missing}; uncertain={uncertain}'
    return ('fail' if repeated or missing else 'pass'), detail


def silence(rule, workspace):
    """Measure long near-silences; a low-level pause can still be missed."""
    path = under(workspace, rule['path'])
    if not path.is_file():
        return 'fail', f'missing {rule["path"]}'
    command = ['ffmpeg', '-hide_banner', '-i', str(path), '-af', 'silencedetect=n=-45dB:d=0.1',
               '-f', 'null', '-']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('silence scan failed: ' + result.stderr[-400:])
    lengths = [float(value) for value in re.findall(r'silence_duration: ([0-9.]+)', result.stderr)]
    longest = max(lengths, default=0.0)
    return ('pass' if longest <= rule['max_seconds'] else 'fail'), f'longest detected near-silence {longest:.3f}s'


def question(rule, response):
    """Screen whether the response asks one question mentioning the missing topic."""
    if not response.is_file():
        return 'not_run', 'no final response transcript was captured'
    text = P.read_text(response)
    count = text.count('?')
    topic = any(re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE) for word in rule['terms'])
    return ('pass' if count == 1 and topic else 'fail'), f'{count} question marks; topic mentioned={topic}'


def caption_changes(rule, workspace, fixtures):
    """Require every reference cue and its specific fate, rather than counting flags."""
    path = under(workspace, rule['path'])
    reference = under(fixtures / 'references', rule['reference'])
    if not path.is_file():
        return 'fail', f'missing {rule["path"]}'
    if not reference.is_file():
        return 'not_run', f'missing grader reference {rule["reference"]}'
    actual = P.load_json(path)
    if not isinstance(actual, dict) or not isinstance(actual.get('captions'), list):
        raise ValueError('delivered caption-change report must have a captions list')
    try:
        expected = P.load_json(reference)
        if not isinstance(expected, dict) or not isinstance(expected.get('captions'), list) or not expected['captions']:
            raise ValueError('reference has no captions')
    except (OSError, ValueError, TypeError, AttributeError) as error:
        return 'not_run', f'invalid grader reference: {error}'
    observed_rows = actual.get('captions', [])
    observed = {int(row['caption']): row for row in observed_rows}
    desired = {int(row['caption']): row for row in expected['captions']}
    if len(observed) != len(observed_rows):
        return 'fail', 'duplicate caption IDs in report'
    missing = {}
    for key, target in desired.items():
        actual_row = observed.get(key, {})
        if actual_row.get('status') != target['status']:
            missing[key] = f'expected {target["status"]}, got {actual_row.get("status")}'
        elif 'shift_s' in target:
            measured = actual_row.get('shift_s')
            if not isinstance(measured, (int, float)) or abs(measured - target['shift_s']) > 0.08:
                missing[key] = f'expected shift {target["shift_s"]:.3f}s, got {measured}'
        if 'cut_words' in target and actual_row.get('cut_words') != target['cut_words']:
            missing[key] = f'expected cut words {target["cut_words"]}, got {actual_row.get("cut_words")}'
    extra = sorted(set(observed) - set(desired))
    return ('pass' if not missing and not extra else 'fail'), f'missing or incorrect={missing}; extra={extra}'


def automated(rule, workspace, response, fixtures):
    """Dispatch one deterministic check; unavailable references remain not_run."""
    method = rule['method']
    try:
        if method == 'exists':
            exists = under(workspace, rule['path']).is_file()
            return ('pass' if exists else 'fail'), f'{rule["path"]} exists={exists}'
        if method == 'video':
            return video(rule, workspace)
        if method == 'captions':
            return caption_comparison(rule, workspace, fixtures)
        if method == 'audio_chunks':
            return audio_chunks(rule, workspace, fixtures)
        if method == 'audio_repeat':
            return audio_repeat(rule, workspace, fixtures)
        if method == 'screen_states':
            return screen_states(rule, workspace, fixtures)
        if method == 'cursor_presence':
            return cursor_presence(rule, workspace)
        if method == 'shot_sequence':
            return shot_sequence(rule, workspace, fixtures)
        if method == 'silence':
            return silence(rule, workspace)
        if method == 'question':
            return question(rule, response)
        if method == 'caption_changes':
            return caption_changes(rule, workspace, fixtures)
        return 'not_run', f'no implementation for method {method}'
    except FileNotFoundError as error:
        return 'not_run', f'cannot run check: {error}'
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        return 'fail', f'invalid delivered evidence: {error}'
    except OSError as error:
        return 'not_run', f'cannot run check: {error}'


def skill_check(task, workspace, run, requested):
    """Run the skill's checker only when explicitly requested."""
    video_rule = next((row for row in task['automatic'] if row['method'] == 'video'), None)
    if not video_rule:
        return check_result('skill-check', 'not_run', 'no video deliverable in this task')
    path = under(workspace, video_rule['path'])
    if not requested:
        return check_result('skill-check', 'not_run', 'rerun with --skill-check under the heavy-job lock')
    if not path.is_file():
        return check_result('skill-check', 'fail', f'missing {video_rule["path"]}')
    output = run / 'skill-checks.json'
    script = PROJECT_PATH.parent / 'check.py'
    command = [sys.executable, '-I', '-B', str(script), '--file', str(path), '--json', str(output)]
    temporary = (run / 'check-scratch').resolve()
    temporary.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        environment[name] = str(temporary)
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                            env=environment)
    if not output.is_file():
        return check_result('skill-check', 'not_run', 'check.py produced no checks.json: ' + result.stderr[-300:])
    data = P.load_json(output)
    states = [row.get('state') for row in data.get('items', [])]
    if not states:
        return check_result('skill-check', 'not_run', 'checks.json contains no check items')
    if 'fail' in states:
        state = 'fail'
    elif 'look' in states:
        state = 'review'
    elif 'skip' in states or result.returncode == 2:
        state = 'not_run'
    else:
        state = 'pass'
    issues = [f'{row.get("id")}: {row.get("detail") or row.get("label")}' for row in data['items']
              if row.get('state') in ('fail', 'look', 'skip')]
    detail = f'check.py exit={result.returncode}; item states={states}'
    if issues:
        detail += '; ' + '; '.join(issues) + f'; next: inspect {output} and review the flagged items'
    return check_result('skill-check', state, detail)


def digest(path):
    """Hash a file when binding a review or scorecard to its exact evidence."""
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def inputs_unchanged(rule, run, workspace):
    """Compare the editor files with the runner's independently preserved inputs."""
    baseline = run / 'original-inputs'
    if not baseline.is_dir():
        return 'not_run', 'no pre-run input baseline exists'
    changed = []
    for name in rule['paths']:
        before = under(baseline, name)
        after = under(workspace, name)
        if not before.is_file() or not after.is_file() or digest(before) != digest(after):
            changed.append(name)
    return ('fail' if changed else 'pass'), f'editor files changed or missing: {changed}'


def load_judgment(task, run, workspace, packet_dir, judgment_path):
    """Validate a neutral packet, the unchanged run artifacts and reviewer provenance."""
    if not packet_dir or not judgment_path:
        return {}, 'independent judgment not supplied'
    try:
        packet_file = packet_dir / 'packet.json'
        packet = P.load_json(packet_file)
        judgment = P.load_json(judgment_path)
        if packet['task'] != task['id'] or judgment['packet_id'] != packet['packet_id']:
            raise ValueError('task or packet ID does not match')
        if judgment['packet_sha256'] != digest(packet_file):
            raise ValueError('packet content changed after the judgment')
        if {row['label'] for row in packet['inputs']} != set(task['inputs']):
            raise ValueError('packet does not contain every original task input')
        originals = run / 'original-inputs'
        for row in packet['inputs']:
            original = under(originals if originals.is_dir() else workspace, row['label'])
            packet_copy = under(packet_dir, row['file'])
            if not original.is_file() or not packet_copy.is_file() or digest(original) != row['sha256']:
                raise ValueError(f'input changed or is missing: {row["label"]}')
            if digest(packet_copy) != row['sha256']:
                raise ValueError(f'packet input changed: {row["label"]}')
        for row in packet['artifacts']:
            original = run / 'final.txt' if row['label'] == 'response' else under(workspace, row['label'])
            packet_copy = under(packet_dir, row['file'])
            if not original.is_file() or not packet_copy.is_file() or digest(original) != row['sha256']:
                raise ValueError(f'artifact changed or is missing: {row["label"]}')
            if digest(packet_copy) != row['sha256']:
                raise ValueError(f'packet copy changed: {row["label"]}')
        for row in packet.get('sheets', []):
            sheet = under(packet_dir, row['file'])
            if not sheet.is_file() or digest(sheet) != row['sha256']:
                raise ValueError(f'packet contact sheet changed: {row["file"]}')
        reviewer = judgment.get('reviewer') or {}
        reviewer_type = reviewer.get('type')
        if reviewer_type not in ('human', 'model'):
            raise ValueError('reviewer type must be human or model')
        if reviewer_type == 'model':
            metadata = P.load_json(run / 'run.json', {})
            producer = metadata.get('producer_family')
            family = reviewer.get('family')
            if not producer or not family or producer.lower() == family.lower():
                raise ValueError('independent model families were not both recorded')
        rows = judgment.get('criteria', [])
        mapped = {row['id']: row for row in rows}
        if len(mapped) != len(rows):
            raise ValueError('duplicate review criterion')
        return {'rows': mapped, 'type': reviewer_type}, 'packet and artifact hashes verified'
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        return {}, f'judgment cannot be accepted: {error}'


def review_item(item, judgment, reason):
    """Accept a specific evidence-backed review, retaining human-only boundaries."""
    if item['id'] == 'no-spend':
        return check_result('review:no-spend', 'not_run',
                            'absence of paid or external calls needs an independent execution audit',
                            basis='execution audit')
    row = (judgment.get('rows') or {}).get(item['id'])
    if not row:
        return check_result('review:' + item['id'], 'not_run', item['description'] + '; ' + reason,
                            basis='independent review')
    state = row.get('state')
    evidence = str(row.get('evidence') or '').strip()
    human_only = item['id'] in ('normal-speed-review', 'publisher-verification')
    if state not in ('pass', 'fail') or len(evidence) < 15:
        return check_result('review:' + item['id'], 'not_run', 'missing state or specific evidence',
                            basis='independent review')
    if human_only and judgment.get('type') != 'human':
        return check_result('review:' + item['id'], 'not_run', 'requires human listening or viewing',
                            basis='independent review')
    return check_result('review:' + item['id'], state, evidence,
                        basis='person' if judgment.get('type') == 'human' else 'independent model')


def scorecard_items(task, workspace, scorecard_path, run=None):
    """Read supported dimension IDs only when a card identifies and hashes its delivered file."""
    dimensions = task['scorecard_dimensions']
    if not dimensions:
        return []
    if not scorecard_path:
        return [check_result('scorecard:' + name, 'not_run', 'no bound scorecard supplied', basis='scorecard')
                for name in dimensions]
    try:
        card = P.load_json(scorecard_path)
        if not isinstance(card, dict):
            raise ValueError('scorecard must be a JSON object')
        declared = card.get('file')
        file_hash = card.get('file_sha256')
        video_rule = next(row for row in task['automatic'] if row['method'] == 'video')
        video = under(workspace, video_rule['path'])
        if not declared or under(workspace, declared) != video or file_hash != digest(video):
            raise ValueError('scorecard must name the delivered file and include its current file_sha256')
        scores = {row['id']: row for row in card.get('dimensions', [])}
    except (OSError, ValueError, TypeError, KeyError, StopIteration, json.JSONDecodeError) as error:
        return [check_result('scorecard:' + name, 'not_run', f'unbound or invalid scorecard: {error}',
                             basis='scorecard') for name in dimensions]
    results = []
    for name in dimensions:
        row = scores.get(name, {})
        value = row.get('score')
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 10:
            results.append(check_result('scorecard:' + name, 'not_run', 'dimension not scored', basis='scorecard'))
            continue
        evidence = row.get('evidence') or []
        valid_evidence = any(isinstance(entry, dict) and isinstance(entry.get('t'), (int, float)) and
                             entry['t'] >= 0 and str(entry.get('note') or '').strip() for entry in evidence)
        if row.get('basis') not in ('measured', 'judged', 'person') or not valid_evidence:
            results.append(check_result('scorecard:' + name, 'not_run', 'dimension has no time-linked evidence',
                                        basis='scorecard'))
            continue
        if row['basis'] == 'judged':
            metadata = P.load_json(run / 'run.json', {}) if run else {}
            producer = metadata.get('producer_family')
            reviewer = row.get('judge_family')
            if not producer or not reviewer or producer.lower() == reviewer.lower():
                results.append(check_result('scorecard:' + name, 'not_run',
                                            'independent judge and producer families are not recorded',
                                            basis='scorecard'))
                continue
        state = 'pass' if value >= 6 else 'fail'
        results.append(check_result('scorecard:' + name, state,
                                    f'{value}/10; provisional eval threshold 6; not a delivery gate',
                                    basis='scorecard', score=value))
    return results


def grade(task, run, fixtures, use_skill_check=False, packet_dir=None, judgment_path=None, scorecard_path=None):
    """Evaluate checks independently and preserve all missing-evidence states."""
    workspace = run / 'workspace' if (run / 'workspace').is_dir() else run
    response = run / 'final.txt'
    rows = []
    for index, rule in enumerate(task['automatic'], 1):
        if rule['method'] == 'inputs_unchanged':
            state, detail = inputs_unchanged(rule, run, workspace)
        else:
            state, detail = automated(rule, workspace, response, fixtures)
        rows.append(check_result(f'{rule["method"]}-{index}', state, detail, basis='deterministic'))
    if any(rule['method'] == 'video' for rule in task['automatic']):
        rows.append(skill_check(task, workspace, run, use_skill_check))
    rows.extend(scorecard_items(task, workspace, scorecard_path, run))
    judgment, reason = load_judgment(task, run, workspace, packet_dir, judgment_path)
    for item in task['review']:
        rows.append(review_item(item, judgment, reason))
    states = [row['state'] for row in rows]
    overall = 'fail' if 'fail' in states else ('inconclusive' if any(state != 'pass' for state in states) else 'pass')
    return {'version': 1, 'task': task['id'], 'kind': task['kind'], 'overall': overall, 'checks': rows}


def main():
    """Load one run and write an auditable per-criterion result."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('task')
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--fixtures', required=True, type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--skill-check', action='store_true')
    parser.add_argument('--packet', type=Path)
    parser.add_argument('--judgment', type=Path)
    parser.add_argument('--scorecard', type=Path)
    args = parser.parse_args()
    try:
        task = tasks()[args.task]
        if not args.run.is_dir() or not args.fixtures.is_dir():
            raise ValueError('run and fixture directories must exist')
        result = grade(task, args.run, args.fixtures, args.skill_check, args.packet, args.judgment, args.scorecard)
        if args.out:
            P.save_json(args.out, result)
        print(json.dumps(result, indent=2))
        return 0 if result['overall'] == 'pass' else 1
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
