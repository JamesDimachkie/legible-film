#!/usr/bin/env python3
"""Create a draft, word-timed transcript locally.

  python transcribe.py AUDIO --engine import --import-file transcript.srt --out words.json
  python transcribe.py AUDIO --project PROJECT --alias int_01 [--quality fast|balanced|best] [--download]

Faster-whisper checks the local cache first; --download permits missing public weights: base ~150 MB, small ~460 MB,
turbo ~1.6 GB. When onnxruntime is missing, the local draft runs without voice detection and discloses that fact.
On one 35 s synthetic sample FFmpeg base.en had 18.95% WER after time sorting; faster-whisper base had 0%.
--quality fast uses base, balanced uses small, best uses large-v3-turbo; --model overrides quality.
FFmpeg word times are estimated; its lower accuracy needs review. --no-download explicitly stays offline.
Every transcript records the input file's SHA-256, byte count and selected audio stream, including imports. The
input must remain unchanged during transcription, and the output cannot replace the media or imported transcript.
A matching media record establishes file identity, not that a draft accurately represents the speech.
An imported transcript keeps its speaker labels. Word-timed JSON from WhisperX, Deepgram, AssemblyAI, Rev, Amazon
Transcribe, ElevenLabs Scribe and Google Speech-to-Text is read by its shape, and a WebVTT cue's <v Name> names its
words. These are the formats' documented shapes, not a guarantee of any service's output today. Labels are drafts until
a person reads them. Word times far past the media's end are read as milliseconds, and it says so.
Exit 0 on success, 2 when it cannot run.
"""
import argparse
from fractions import Fraction
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)


def other_streams_note(path, stream):
    """What to try when a stream gave no words and the file has others: their levels and --stream, or ''."""
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)], capture_output=True,
                            text=True)
    streams = json.loads(result.stdout or '{}').get('streams', []) if not result.returncode else []
    if sum(row.get('codec_type') == 'audio' for row in streams) < 2 or not shutil.which('ffmpeg'):
        return ''
    levels = project.audio_stream_levels(path, streams)
    others = [f"stream {index} (peak {level['peak_db']:.1f} dB)" if level['peak_db'] is not None else f'stream {index}'
              for index, level in levels.items() if index != stream]
    return (f"no words from audio stream {stream}; this file also has {', '.join(others)}: choose one with --stream "
            'INDEX') if others else ''


def audio_stream_info(facts, requested=None):
    """Choose one absolute audio stream index and its zero-based presentation metadata."""
    streams = [stream for stream in facts.get('streams', []) if stream.get('codec_type') == 'audio']
    if requested is not None:
        stream = next((item for item in streams if item.get('index') == requested), None)
        if stream is None:
            raise ValueError(f'audio stream {requested} does not exist')
    else:
        stream = project.default_audio_stream(streams)
    if stream is None:
        return None
    try:
        origin = float(facts.get('format', {}).get('start_time', 0))
        if not math.isfinite(origin):
            raise ValueError('invalid origin')
    except (TypeError, ValueError):
        origin = 0.0
    try:
        start = float(stream.get('start_time', origin)) - origin
        if not math.isfinite(start):
            raise ValueError('invalid stream start')
    except (TypeError, ValueError):
        start = None
    return {'index': int(stream['index']), 'language': (stream.get('tags') or {}).get('language'),
            'layout': stream.get('channel_layout'), 'channels': stream.get('channels'),
            'rate': int(stream['sample_rate']), 'start_s': start, 'origin_s': origin}


def probe_audio(path, requested=None, ffprobe='ffprobe'):
    """Probe and choose the audio stream without relying on FFmpeg's automatic mapping."""
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError('ffprobe could not read audio: ' + (result.stderr.strip() or str(path)))
    try:
        facts = json.loads(result.stdout)
        chosen = audio_stream_info(facts, requested)
    except ValueError as error:
        raise ValueError(f'{error} in {path}') from error
    if chosen is None:
        raise ValueError(f'no audio stream a:0 in {path}')
    selected = next(row for row in facts.get('streams', []) if row.get('index') == chosen['index'])
    chosen['time_base'] = selected.get('time_base')
    return chosen


def audio_window_command(path, stream, start, end, rate=16000, sample_format='f32le', channels=1, ffmpeg='ffmpeg',
                         pad=True):
    """Decode a source-clock window, inserting silence when the selected stream starts late. It also pads to the
    window's end; with pad=False the output stops where the sound does, so its length measures the stream's real end."""
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end and rate > 0):
        raise ValueError('invalid audio window')
    info = probe_audio(path, stream)
    if info['start_s'] is None:
        raise ValueError(f"cannot establish audio stream {info['index']} start time in {path}")
    length = round((end - start) * rate)
    offset = info['origin_s']
    first = round(start * rate)
    filters = (f'asetpts=PTS-({offset:.9f})/TB,aresample={rate}:async=1:first_pts=0,'
               f'atrim=start_sample={first}:end_sample={first + length},asetpts=PTS-STARTPTS')
    if pad:
        filters += f',apad=whole_len={length},atrim=end_sample={length}'
    options = ['-copyts']
    try:
        tick = Fraction(str(info['time_base']))
        sample_clock = 0 < tick <= Fraction(1, info['rate'])
    except (ValueError, TypeError, ZeroDivisionError):
        sample_clock = False
    if start > 5 and sample_clock:
        spec = importlib.util.spec_from_file_location('lf_audio_seek_policy',
                                                      Path(__file__).with_name('render_common.py'))
        common = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(common)
        if common.source_seek_safe(path):
            seek = start - 5
            options.extend(['-ss', f'{seek:.9f}', '-t', f'{end - seek + 1:.9f}'])
    return [ffmpeg, '-v', 'error', '-nostdin', *options, '-i', str(path),
            '-map', f"0:{info['index']}", '-vn', '-af', filters, '-ac', str(channels), '-ar', str(rate),
            '-f', sample_format, 'pipe:1']


def decode_audio_window(path, stream, start, end, rate=16000):
    """Return mono float samples on the source clock; failures are never treated as silence."""
    import numpy as np
    command = audio_window_command(path, stream, start, end, rate)
    result = subprocess.run(command, capture_output=True, timeout=600)
    if result.returncode:
        raise ValueError('audio window decode failed: ' + result.stderr.decode(errors='replace')[-500:])
    samples = np.frombuffer(result.stdout, dtype='<f4')
    if len(samples) != round((end - start) * rate):
        raise ValueError('audio window decode returned the wrong number of samples')
    return samples


def merge_speech(segments, gap=.3):
    """Sorted [start, end] speech segments with gaps shorter than `gap` seconds joined (chunk edges split them)."""
    merged = []
    for start, end in sorted((float(a), float(b)) for a, b in segments if b > a):
        if merged and start - merged[-1][1] < gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [[round(a, 3), round(b, 3)] for a, b in merged]


def speech_activity(path, stream, length, chunk=600.0):
    """Speech segments from the Silero voice-activity model that faster-whisper bundles, decoded at 16 kHz in
    ten-minute chunks so memory stays bounded; None when the model cannot load. Music and noise rarely trigger it, so
    it replaces the speech-band energy heuristic for finding speech no transcript word covers. Measured on a
    three-minute interview with six deleted word spans: the same spans found as the heuristic (6 of 6 dry, 5 of 6
    under a music bed) with no other prompts, where the heuristic also prompted on 93% of a music-only track."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except (ImportError, AttributeError):
        return None
    options = VadOptions(min_silence_duration_ms=300, speech_pad_ms=100)
    found = []
    start = 0.0
    while start < length:
        end = min(length, start + chunk)
        try:
            samples = decode_audio_window(path, stream, start, end, rate=16000)
            rows = get_speech_timestamps(samples, options)
        except (ImportError, OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            return None
        found += [[start + row['start'] / 16000, start + row['end'] / 16000] for row in rows]
        start = end
    return {'method': 'Silero voice-activity model (faster-whisper)', 'segments': merge_speech(found)}


LOW_CONFIDENCE = 0.2


def transcript_review(words, audio):
    """Find review candidates without changing any transcript word or claiming to detect speech."""
    prompts = []
    truncated = False
    tokens = [re.sub(r'[^\w]+', '', str(word.get('text', '')).casefold()) for word in words]
    index = 4
    while index + 4 <= len(tokens):
        phrase = tokens[index:index + 4]
        if all(phrase) and phrase == tokens[index - 4:index]:
            first = index - 4
            prompts.append({'kind': 'repeated_phrase', 'start': float(words[index]['start']),
                            'end': float(words[index + 3]['end']),
                            'word_ids': [word.get('id') for word in words[index:index + 4]],
                            'earlier_start': float(words[first]['start']),
                            'detail': 'Back-to-back four-word phrase: listen to both; repetition may be real.'})
            index += 4
        else:
            index += 1
        if len(prompts) >= 100:
            truncated = True
            break
    # Words the model was unsure of: on a film with a score, names it invented ("Thom" for another word) had
    # confidence 0.00 to 0.19, while the median word was 0.98.
    unsure = []
    for word in words:
        confidence = word.get('p')
        if isinstance(confidence, (int, float)) and confidence < LOW_CONFIDENCE:
            if unsure and float(word.get('start', 0)) - unsure[-1]['end'] <= 1.0:
                unsure[-1]['end'] = float(word.get('end', word.get('start', 0)))
                unsure[-1]['word_ids'].append(word.get('id'))
            else:
                unsure.append({'kind': 'low_confidence', 'start': float(word.get('start', 0)),
                               'end': float(word.get('end', word.get('start', 0))), 'word_ids': [word.get('id')],
                               'detail': 'The transcriber was unsure of these words: listen, and check names and '
                                         'numbers first.'})
    prompts.extend(unsure[:100])
    band = (audio or {}).get('speech_band_db') or {}
    levels = band.get('values')
    step = band.get('step_s')
    if not isinstance(levels, list) or not levels or not isinstance(step, (int, float)) or step <= 0:
        note = 'Review prompts are fallible and never delete words.'
        if truncated:
            note += ' Prompt limit reached; inspect the full transcript manually.'
        return {'version': 1, 'prompts': prompts, 'truncated': truncated,
                'energy_check': 'unavailable: run map.py run to measure audio', 'note': note}
    for word in words:
        start = float(word.get('start', 0))
        end = float(word.get('end', start))
        first = max(0, int(max(0.0, start - .15) / step))
        last = min(len(levels), int(math.ceil((end + .15) / step)))
        window = levels[first:last]
        if window and max(window) < -50:
            prompts.append({'kind': 'word_in_low_energy', 'start': start, 'end': end,
                            'word_ids': [word.get('id')],
                            'detail': 'Little speech-band energy near this word: listen; quiet speech can be missed.'})
        if len(prompts) >= 200:
            truncated = True
            break
    intervals = sorted((max(0.0, float(word.get('start', 0)) - .2), float(word.get('end', 0)) + .2)
                       for word in words)
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    activity = (audio or {}).get('speech_activity')
    if isinstance(activity, dict) and isinstance(activity.get('segments'), list):
        for segment in activity['segments']:
            cursor, end = float(segment[0]), float(segment[1])
            for covered_start, covered_end in merged:
                if covered_end <= cursor or covered_start >= end:
                    continue
                if covered_start - cursor >= 1.0:
                    prompts.append({'kind': 'uncovered_speech', 'start': round(cursor, 3),
                                    'end': round(covered_start, 3), 'word_ids': [],
                                    'detail': 'Speech heard by a voice-activity model with no transcript words: '
                                              'listen for omitted speech; singing can also trigger this.'})
                cursor = max(cursor, covered_end)
                if cursor >= end:
                    break
            if end - cursor >= 1.0:
                prompts.append({'kind': 'uncovered_speech', 'start': round(cursor, 3), 'end': round(end, 3),
                                'word_ids': [],
                                'detail': 'Speech heard by a voice-activity model with no transcript words: '
                                          'listen for omitted speech; singing can also trigger this.'})
            if len(prompts) >= 300:
                truncated = True
                break
        note = 'Review prompts are fallible and never delete words.'
        if truncated:
            note += ' Prompt limit reached; inspect the full transcript manually.'
        return {'version': 1, 'prompts': prompts, 'truncated': truncated,
                'energy_check': activity.get('method', 'voice-activity model') + '; quiet speech can be missed',
                'note': note}
    active = []
    interval_index = 0
    for index, level in enumerate(levels):
        start, end = index * step, (index + 1) * step
        while interval_index < len(merged) and merged[interval_index][1] <= start:
            interval_index += 1
        covered = interval_index < len(merged) and merged[interval_index][0] < end
        active.append(float(level) > -42 and not covered)
    begin = None
    for index in range(len(active) + 1):
        if index < len(active) and active[index]:
            if begin is None:
                begin = index
        elif begin is not None:
            if (index - begin) * step >= 1.0:
                prompts.append({'kind': 'uncovered_energy', 'start': round(begin * step, 3),
                                'end': round(index * step, 3), 'word_ids': [],
                                'detail': 'Speech-band audio without transcript words: listen for omitted speech; '
                                          'music or noise can also trigger this.'})
            begin = None
        if len(prompts) >= 300:
            truncated = True
            break
    note = 'Review prompts are fallible and never delete words.'
    if truncated:
        note += ' Prompt limit reached; inspect the full transcript manually.'
    return {'version': 1, 'prompts': prompts, 'truncated': truncated,
            'energy_check': 'speech-band RMS heuristic; not speech recognition', 'note': note}


def split_segment(text, start, end, speaker=None):
    """Spread segment text uniformly over its interval; edges are estimates."""
    tokens = text.split()
    return [{'text': word, 'start': start + (end - start) * i / len(tokens),
             'end': start + (end - start) * (i + 1) / len(tokens), 'speaker': speaker, 'estimated': True}
            for i, word in enumerate(tokens)]


def seconds_of(value):
    """A time from an imported transcript as seconds: a number, or text like '1.500s'."""
    return float(str(value).strip().rstrip('s') or 0)


def deepgram_rows(results):
    """Deepgram: results.channels[].alternatives[0].words, with a speaker when diarized and a channel when not."""
    channels = results.get('channels') or []
    rows = []
    for number, channel in enumerate(channels):
        for word in ((channel.get('alternatives') or [{}])[0].get('words') or []):
            speaker = word.get('speaker', f'channel {number}' if len(channels) > 1 else None)
            rows.append({'text': word.get('punctuated_word', word.get('word', '')), 'start': word.get('start'),
                         'end': word.get('end'), 'p': word.get('confidence'), 'speaker': speaker})
    return sorted(rows, key=lambda row: float(row['start'] or 0))


def amazon_rows(results):
    """Amazon Transcribe: results.items, a speaker on each item or in a separate speaker_labels list, and punctuation as
    its own item with no time."""
    speakers = {}
    for segment in (results.get('speaker_labels') or {}).get('segments') or []:
        for item in segment.get('items') or []:
            speakers[str(item.get('start_time'))] = item.get('speaker_label', segment.get('speaker_label'))
    rows = []
    for item in results.get('items') or []:
        best = (item.get('alternatives') or [{}])[0]
        if item.get('type') == 'punctuation':
            if rows:
                rows[-1]['text'] += str(best.get('content', ''))
            continue
        rows.append({'text': str(best.get('content', '')), 'start': float(item['start_time']),
                     'end': float(item['end_time']), 'p': float(best.get('confidence') or 0),
                     'speaker': item.get('speaker_label', speakers.get(str(item.get('start_time'))))})
    return rows


def google_rows(results):
    """Google Speech-to-Text: with diarization the last result repeats every word with its tag; else words by result."""
    groups = [(result.get('alternatives') or [{}])[0].get('words') or [] for result in results]
    tagged = [words for words in groups if any('speakerTag' in word or 'speakerLabel' in word for word in words)]
    words = tagged[-1] if tagged else [word for group in groups for word in group]
    return [{'text': word.get('word', ''), 'start': seconds_of(word.get('startTime', word.get('startOffset', 0))),
             'end': seconds_of(word.get('endTime', word.get('endOffset', 0))), 'p': word.get('confidence'),
             'speaker': word.get('speakerLabel', word.get('speakerTag'))} for word in words]


def rev_rows(monologues):
    """Rev: monologues[].elements, a word with its times and punctuation as its own element."""
    rows = []
    for monologue in monologues:
        for element in monologue.get('elements') or []:
            if element.get('type') == 'text':
                rows.append({'text': element.get('value', ''), 'start': element.get('ts'), 'end': element.get('end_ts'),
                             'p': element.get('confidence'), 'speaker': monologue.get('speaker')})
            elif rows and str(element.get('value', '')).strip():
                rows[-1]['text'] += str(element['value']).strip()
    return rows


def service_rows(data):
    """Word rows from the word-timed formats whose shape is not this skill's own, or None for any other shape."""
    if not isinstance(data, dict):
        return None
    results = data.get('results')
    if isinstance(results, dict) and isinstance(results.get('channels'), list):
        return deepgram_rows(results)
    if isinstance(results, dict) and isinstance(results.get('items'), list):
        return amazon_rows(results)
    if isinstance(results, list) and any(isinstance(row, dict) and 'alternatives' in row for row in results):
        return google_rows(results)
    if isinstance(data.get('monologues'), list):
        return rev_rows(data['monologues'])
    words = data.get('words')
    if isinstance(words, list) and any(isinstance(row, dict) and 'speaker_id' in row for row in words):
        # ElevenLabs Scribe: spacing and sound events sit among the words.
        return [dict(row, speaker=row.get('speaker_id')) for row in words if row.get('type', 'word') == 'word']
    if isinstance(words, list) and 'audio_duration' in data:
        # AssemblyAI gives milliseconds, and the file says how long the audio was in seconds.
        last = max((float(row.get('end') or 0) for row in words), default=0.0)
        if last > float(data['audio_duration'] or 0) * 2:
            return [dict(row, start=float(row['start']) / 1000, end=float(row['end']) / 1000) for row in words]
    return None


def read_import(path):
    """Read word JSON or SRT/WebVTT cues, keeping speaker labels."""
    text = project.read_text(path)
    if Path(path).suffix.lower() == '.json':
        data = json.loads(text)
        known = service_rows(data)
        if known is not None:
            return known
        rows = data if isinstance(data, list) else data.get('words', data.get('segments', []))
        word_list = isinstance(data, list) or (isinstance(data, dict) and 'words' in data)
        result = []
        for row in rows:
            if row.get('words') is not None:
                # WhisperX names the segment's speaker, and a word it could not assign has none of its own.
                speaker = row.get('speaker')
                result.extend(word if speaker is None or word.get('speaker') is not None
                              else dict(word, speaker=speaker) for word in row['words'])
            elif 'word' in row or (word_list and 'text' in row):
                result.append(row)
            elif 'start' in row and 'end' in row:
                result.extend(split_segment(str(row.get('text', '')), float(row['start']), float(row['end']),
                                            row.get('speaker')))
        return result
    timestamp = r'(\d{1,2}:\d{2}(?::\d{2})?[.,]\d+)'
    pattern = timestamp + r'[ \t]*-->[ \t]*' + timestamp + r'[^\n]*'
    result = []
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    for block in re.split(r'\n[ \t]*\n', text):
        lines = block.split('\n')
        for index, line in enumerate(lines):
            match = re.fullmatch(pattern, line.strip())
            if match:
                start = project.parse_time(match.group(1).replace(',', '.'))
                end = project.parse_time(match.group(2).replace(',', '.'))
                voice = re.match(r'\s*<v(?:\.[^\s>]*)?\s+([^>]+)>', ' '.join(lines[index + 1:]))
                clean = re.sub(r'<[^>]*>', '', ' '.join(lines[index + 1:])).strip()
                result.extend(split_segment(clean, start, end, voice.group(1).strip() if voice else None))
                break
    return result


def normalize(rows, alias):
    """Drop blank rows and give every remaining word an alias-scoped ID."""
    words = []
    for row in rows:
        text = str(row.get('word', row.get('text', ''))).strip()
        if not text or row.get('start') is None or row.get('end') is None:
            continue
        speaker = row.get('speaker')
        word = {'id': f'{alias}-w{len(words) + 1:06d}', 'text': text, 'start': float(row['start']),
                'end': float(row['end']), 'speaker': None if speaker is None else str(speaker),
                'estimated': bool(row.get('estimated', False))}
        probability = row.get('probability', row.get('p', row.get('score')))
        if probability is not None:
            word['p'] = float(probability)
        words.append(word)
    return words


def from_milliseconds(rows, length):
    """Rows whose times run far past the media and fit it as milliseconds, read as milliseconds; (rows, whether so)."""
    last = max((float(row['end']) for row in rows if row.get('end') is not None), default=0.0)
    if last <= length * 1.5 + 5 or last / 1000 > length * 1.1 + 1:
        return rows, False
    return [dict(row, start=float(row['start']) / 1000, end=float(row['end']) / 1000)
            if row.get('start') is not None and row.get('end') is not None else row for row in rows], True


def presentation_duration(facts):
    """Use stream presentation ends where available, keeping container origins distinct from durations."""
    container = facts.get('format') or {}
    try:
        origin = float(container.get('start_time', 0))
    except (TypeError, ValueError):
        origin = 0.0
    ends = []
    for stream in facts.get('streams', []):
        if stream.get('codec_type') not in ('audio', 'video') or stream.get('disposition', {}).get('attached_pic'):
            continue
        try:
            start = float(stream.get('start_time', origin))
            length = float(stream['duration'])
            if math.isfinite(start) and math.isfinite(length) and length > 0:
                ends.append(start - origin + length)
                continue
        except (KeyError, TypeError, ValueError):
            pass
        tag = (stream.get('tags') or {}).get('DURATION')
        if tag and 'matroska' in container.get('format_name', ''):
            try:
                ends.append(project.parse_time(tag) - origin)
            except ValueError:
                pass
    if ends:
        return max(ends)
    value = container.get('duration')
    if value is None:
        raise ValueError('media duration is unavailable')
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError('media duration is invalid')
    return result


def duration(path):
    """Probe duration in zero-based presentation seconds."""
    if not shutil.which('ffprobe'):
        raise ValueError('ffprobe not found; install FFmpeg (including ffprobe) and add it to PATH')
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True)
    if result.returncode:
        raise ValueError('ffprobe: ' + (result.stderr.strip() or 'could not read media'))
    return presentation_duration(json.loads(result.stdout))


def audio_start(path, stream=None):
    """Find the selected audio stream's start on the input's zero-based clock."""
    start = probe_audio(path, stream)['start_s']
    if start is None:
        raise ValueError(f'cannot determine the selected audio stream start in {path}')
    return max(0.0, start)


def constrain_audio_start(rows, start):
    """Prevent ASR timestamps from claiming speech before the source audio begins."""
    result = []
    for source in rows:
        row = dict(source)
        if row.get('start') is not None and float(row['start']) < start:
            if row.get('end') is None or float(row['end']) <= start:
                raise ValueError('a recognized word falls entirely before audio starts; inspect the transcript')
            row['start'] = start
            row['estimated'] = True
        result.append(row)
    return result


def vad_silence(path, point, length, stream=None):
    """Find a VAD-confirmed gap near a candidate silence."""
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    begin = max(0.0, point - 4.0)
    end = min(length, point + 4.0)
    samples = decode_audio_window(path, stream, begin, end, rate=16000)
    speech = get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=300))
    bounds = [(0, 0)] + [(row['start'], row['end']) for row in speech] + [(len(samples), len(samples))]
    gaps = [(left[1] / 16000 + begin, right[0] / 16000 + begin)
            for left, right in zip(bounds, bounds[1:]) if right[0] - left[1] >= 4800]
    if not gaps:
        return None
    gap = min(gaps, key=lambda pair: abs((pair[0] + pair[1]) / 2 - point))
    return (gap[0] + gap[1]) / 2


def audio_ranges(path, length, stream=None):
    """For very long audio, split near an hour only in a VAD-confirmed silence."""
    if length <= 7200:
        return [(0, length)]
    command = ['ffmpeg', '-hide_banner', '-nostdin', '-i', str(path)]
    if stream is not None:
        command += ['-map', f'0:{stream}']
    command += ['-af', 'silencedetect=noise=-35dB:d=0.5', '-f', 'null', '-']
    run = subprocess.run(command,
                         capture_output=True, text=True, check=True)
    events = re.findall(r'silence_(start|end):\s*(-?[\d.]+)', run.stderr)
    points = []
    silence_start = None
    for kind, value in events:
        moment = max(0.0, float(value))
        if kind == 'start':
            silence_start = moment
        elif silence_start is not None and moment >= silence_start:
            points.append((silence_start + moment) / 2)
            silence_start = None
    boundaries = [0.0]
    while length - boundaries[-1] > 7200:
        candidates = [p for p in points if boundaries[-1] + 60 < p <= boundaries[-1] + 7196]
        candidates.sort(key=lambda p: abs(p - (boundaries[-1] + 3600)))
        cut = None
        for candidate in candidates:
            cut = vad_silence(path, candidate, length, stream) if stream is not None else \
                vad_silence(path, candidate, length)
            if cut is not None and boundaries[-1] + 60 < cut <= boundaries[-1] + 7200:
                break
            cut = None
        if cut is None:
            raise ValueError('no VAD-confirmed silence within two hours; split at a verified silence and retry')
        boundaries.append(cut)
    boundaries.append(length)
    return list(zip(boundaries, boundaries[1:]))


def download_command(arguments, python=None, system=None):
    """Recreate the user's transcription command, preserving non-path values such as prompts."""
    path_options = {'--out', '--project', '--import-file', '--model-dir', '--ggml-model', '--model'}
    literals = {'--prompt', '--language', '--quality', '--engine', '--alias'}
    result = [Path(__file__)]
    for index, value in enumerate(arguments):
        previous = arguments[index - 1] if index else ''
        flag, separator, option_value = value.partition('=')
        if separator and flag in path_options:
            result.append(flag + '=' + option_value.replace('\\', '/'))
        elif (index == 0 and not value.startswith('-')) or previous in path_options:
            result.append(Path(value))
        elif previous not in literals and re.match(r'^(?:[A-Za-z]:[\\/]|\\\\)', value):
            result.append(Path(value))
        else:
            result.append(value)
    result.append('--download')
    return project.python_command(result, python=python, system=system)


def faster(args):
    """Transcribe whole audio, using silence boundaries only for files over two hours."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        missing = error.name.split('.')[0] if error.name else 'faster_whisper'
        if missing not in ('numpy', 'PIL', 'faster_whisper', 'onnxruntime'):
            missing = 'faster_whisper'
        raise ValueError(project.dependency_message(missing)) from error
    args.stream = getattr(args, 'stream', None)
    args.vad_disabled = getattr(args, 'vad_disabled', False)
    try:
        model = WhisperModel(args.model, device='cpu', compute_type='int8', download_root=args.model_dir,
                             local_files_only=True)
    except Exception as error:
        # Only a missing cache entry permits a download. A broken local model must remain an error.
        if error.__class__.__name__ != 'LocalEntryNotFoundError' or args.no_download:
            raise
        if not getattr(args, 'download', False):
            sizes = {'base': 'about 150 MB', 'base.en': 'about 150 MB', 'small': 'about 460 MB',
                     'small.en': 'about 460 MB', 'large-v3-turbo': 'about 1.6 GB'}
            size = sizes.get(args.model, 'size unknown')
            command = getattr(args, 'download_help_command', None) or download_command(sys.argv[1:])
            setup = project.python_command([Path(__file__).with_name('setup.py'), '--install', 'transcription',
                                            '--download'])
            raise ValueError(f'Model {args.model} is not cached ({size}). To allow its download, run: {command}\n'
                             f'For the default small model, or to install transcription too, run: {setup}') from error
        print('Downloading explicitly permitted model weights: ' + args.model, flush=True)
        model = WhisperModel(args.model, device='cpu', compute_type='int8', download_root=args.model_dir,
                             local_files_only=False)
    rows = []
    language = args.language
    total = duration(args.file)
    reported = [time.monotonic()]
    for start, end in audio_ranges(args.file, total, args.stream):
        samples = decode_audio_window(args.file, args.stream, start, end, rate=16000)

        def transcribe_chunk(use_vad):
            """Collect one chunk so a failed VAD attempt cannot leave duplicate partial words."""
            chunk = []
            segments, info = model.transcribe(samples, language=language, initial_prompt=args.prompt,
                                              word_timestamps=True, vad_filter=use_vad)
            for segment in segments:
                if time.monotonic() - reported[0] >= 15:
                    # A long source takes minutes on a busy machine (17 minutes took nearly 10 on a cold run).
                    reported[0] = time.monotonic()
                    print(f'transcribed {segment.end + start:.0f} of {total:.0f} s', file=sys.stderr, flush=True)
                for word in segment.words or []:
                    chunk.append({'word': word.word, 'start': word.start + start, 'end': word.end + start,
                                  'p': word.probability})
            return chunk, info.language

        try:
            chunk, detected = transcribe_chunk(not args.vad_disabled)
        except (ModuleNotFoundError, ImportError, RuntimeError) as error:
            missing_vad = importlib.util.find_spec('onnxruntime') is None
            if 'onnxruntime' not in str(error).lower() or not missing_vad or args.vad_disabled:
                raise
            args.vad_disabled = True
            print('Voice detection is off. ' + project.dependency_message('onnxruntime') +
                  '\nContinuing with a local no-VAD draft that needs review.', file=sys.stderr, flush=True)
            chunk, detected = transcribe_chunk(False)
        rows.extend(chunk)
        language = language or detected
    return rows, language


def ordered_words(rows):
    """Sort estimated words and trim overlapping times without discarding transcript text."""
    rows = sorted(rows, key=lambda row: (row['start'], row['end']))
    for left, right in zip(rows, rows[1:]):
        if left['end'] > right['start']:
            boundary = max(left['start'], right['start'])
            left['end'] = boundary
    return rows


def filter_transcribe(args):
    """Use the optional FFmpeg whisper filter, exporting SRT segment times."""
    if not args.ggml_model:
        raise ValueError('FFmpeg whisper needs --ggml-model PATH')
    if args.prompt:
        raise ValueError('FFmpeg whisper filter does not support --prompt')
    with tempfile.TemporaryDirectory() as tmp:
        model = Path(args.ggml_model).resolve()
        output = Path(tmp) / 'words.srt'
        def escape(path):
            return str(path).replace('\\', '/').replace(':', '\\:').replace("'", "\\'\\''")
        filt = (f"aresample=async=1:first_pts=0,whisper=model='{escape(model)}':"
                f"destination='{escape(output)}':format=srt:use_gpu=false")
        if args.language:
            filt += ':language=' + args.language
        info = probe_audio(args.file, args.stream)
        filt = f"asetpts=PTS-({info['origin_s']:.9f})/TB," + filt
        subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-copyts', '-i', str(args.file),
                        '-map', f"0:{info['index']}", '-af', filt,
                        '-f', 'null', '-'], check=True)
        return read_import(output), args.language


def refuse_existing_project_words(path, root, alias):
    """Keep a project transcript unless replacement goes through the deliberate map workflow."""
    if path.exists():
        raise ValueError(f'{alias}: existing transcript retained. To replace it deliberately, use '
                         f'map.py run "{root}" --alias {alias} --retranscribe {alias}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('file')
    parser.add_argument('--engine', choices=['faster-whisper', 'ffmpeg', 'import'])
    parser.add_argument('--import-file')
    parser.add_argument('--model')
    parser.add_argument('--quality', choices=['fast', 'balanced', 'best'], default='balanced')
    parser.add_argument('--model-dir')
    parser.add_argument('--ggml-model')
    downloads = parser.add_mutually_exclusive_group()
    downloads.add_argument('--no-download', action='store_true', help='explicitly refuse model downloads')
    downloads.add_argument('--download', action='store_true', help='permit downloading uncached model weights')
    parser.add_argument('--download-help-command', help=argparse.SUPPRESS)
    parser.add_argument('--language')
    parser.add_argument('--prompt')
    parser.add_argument('--project')
    parser.add_argument('--alias')
    parser.add_argument('--out')
    parser.add_argument('--stream', type=int, help='absolute audio stream index from ffprobe')
    args = parser.parse_args()
    try:
        if bool(args.project) != bool(args.alias) or (not args.project and not args.out):
            raise ValueError('use --project and --alias together, or --out')
        args.model = args.model or {'fast': 'base', 'balanced': 'small', 'best': 'large-v3-turbo'}[args.quality]
        alias = args.alias or 'src_01'
        out = Path(args.out) if args.out else Path(args.project) / 'map' / alias / 'words.json'
        project.refuse_overwriting_inputs([out], [args.file, args.import_file])
        if args.project and not args.out:
            refuse_existing_project_words(out, args.project, alias)
        media_hash = project.file_sha256(args.file)
        media_size = Path(args.file).stat().st_size
        length = duration(args.file)
        if args.project and args.stream is None:
            mapped = project.load_json(Path(args.project) / 'map' / 'sources.json', {})
            source = next((row for row in mapped.get('sources', []) if row.get('alias') == alias), {})
            args.stream = (source.get('audio') or {}).get('index')
        args.stream = probe_audio(args.file, args.stream)['index']
        args.vad_disabled = False
        engine = args.engine
        if engine != 'import' and not shutil.which('ffmpeg'):
            raise ValueError('ffmpeg not found; install FFmpeg and add it to PATH')
        if not engine:
            if importlib.util.find_spec('faster_whisper'):
                engine = 'faster-whisper'
            elif ' whisper ' in subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True,
                                                 text=True, check=True).stdout:
                engine = 'ffmpeg'
            else:
                raise ValueError(project.dependency_message('faster_whisper') + '\nOr import a transcript.')
        if args.project:
            index = project.load_json(Path(args.project) / 'map' / 'sources.json', {})
            if not any(s.get('alias') == alias for s in index.get('sources', [])):
                raise ValueError('alias is not registered')
        start = time.monotonic()
        if engine == 'import':
            if not args.import_file:
                raise ValueError('--engine import needs --import-file')
            rows, language = read_import(args.import_file), args.language
            rows, scaled = from_milliseconds(rows, length)
            if scaled:
                print(f'note: {Path(args.import_file).name} has word times far past the {length:.2f} s of media; read '
                      'them as milliseconds. Check a few words against the sound.')
        elif engine == 'ffmpeg':
            rows, language = filter_transcribe(args)
            rows = ordered_words(rows)
        else:
            rows, language = faster(args)
        if engine != 'import':
            rows = constrain_audio_start(rows, audio_start(args.file, args.stream))
        words = normalize(rows, alias)
        if not words:
            note = other_streams_note(args.file, args.stream)
            if note:
                print('note: ' + note, file=sys.stderr)
        name = engine + (' ' + args.model if engine == 'faster-whisper' else '')
        if project.file_sha256(args.file) != media_hash or Path(args.file).stat().st_size != media_size:
            raise ValueError('media changed during transcription; no transcript was written')
        result = {'version': 1, 'source': alias, 'engine': name, 'language': language,
                  'draft': True, 'audio_stream': args.stream,
                  'media': {'sha256': media_hash, 'bytes': media_size, 'audio_stream': args.stream},
                  'voice_detection': 'off' if args.vad_disabled else ('on' if engine == 'faster-whisper' else None),
                  'words': words}
        if engine == 'ffmpeg':
            result['warning'] = 'Estimated word timing; FFmpeg filter was less accurate in the synthetic check.'
        labelled = sum(1 for word in words if word['speaker'] is not None)
        if engine == 'import' and labelled:
            result['speaker_labels'] = {'method': 'imported', 'file': Path(args.import_file).name, 'draft': True,
                                        'at': project.now(), 'labelled_words': labelled,
                                        'unlabelled': len(words) - labelled,
                                        'note': 'Drafts until a person reads them, like the words.'}
        if args.project and not args.out:
            with project.file_lock(out):
                refuse_existing_project_words(out, args.project, alias)
                project.save_json(out, result)
        else:
            project.save_json(out, result)
        if args.project and not args.out:
            sources_path = Path(args.project) / 'map' / 'sources.json'
            with project.file_lock(sources_path):
                sources = project.load_json(sources_path, {'version': 1, 'sources': []})
                source = next((s for s in sources['sources'] if s['alias'] == alias), None)
                if source is None:
                    raise ValueError('alias is not registered')
                source.setdefault('mapped', {})['words'] = True
                project.save_json(sources_path, sources)
        elapsed = max(time.monotonic() - start, 0.001)
        if engine == 'import':
            print(f'imported {len(words)} words from {Path(args.import_file).name} for {length:.2f} s of media')
        else:
            print(f'duration {length:.2f}s, speed {length / elapsed:.2f}x, words {len(words)}')
        return 0
    except ImportError as error:
        name = error.name.split('.')[0] if error.name else ''
        print(project.dependency_message(name) if name in ('numpy', 'PIL', 'faster_whisper', 'onnxruntime')
              else 'cannot run: ' + str(error), file=sys.stderr)
        return 2
    except Exception as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
