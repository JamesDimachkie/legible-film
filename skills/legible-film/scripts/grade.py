#!/usr/bin/env python3
"""Make an evidence-led scorecard and a packet for a reviewer.

  python grade.py PROJECT [--version vNNN]
  python grade.py --file FILE [--platform P] [--kind K] [--brief brief.md] [--words W | --no-transcribe]
  python grade.py merge PROJECT judged.json [--version vNNN]
  python grade.py merge judged.json --file FILE
  python grade.py scores PROJECT [--version vNNN]
  python grade.py paper PROJECT [--judged paper-judged.json]
  python grade.py hooks PROJECT [--alias A] [--all]
  python grade.py thumbs FILE|PROJECT [--version vNNN]
  python grade.py review PROJECT [--version vNNN]

A project version's card is cuts/vNNN/scorecard.json with its packet in cuts/vNNN/grade/.
A loose file's card is NAME.scorecard.json beside it, with its packet in NAME.grade/.
review builds cuts/vNNN/review/ for an independent editor; it does not score the cut.
A loose file's words come from --words (word JSON, SRT or WebVTT), else from a local
faster-whisper small transcript of its own audio when installed (setup.py --install
transcription --download; cached; nothing uploaded), else the card says there is no transcript.

Numbers from frames, transcripts and sound are diagnostics, not scores of taste or
proof of accessibility. Scores require cited reviewer evidence and remain subject
to a person's normal-speed viewing and listening. Each dimension states what its
score has been tested against (references/grading.md, Validation); no score is
calibrated against viewers. Nothing is uploaded.
Exit 0 on success, 1 when a scorecard needs review, 2 when it cannot run.
"""
import argparse
import base64
import bisect
import gzip
import hashlib
import html
import importlib.util
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('lf_project', HERE / 'project.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)

DIMENSIONS = (
    ('hook', 'content', 'Hook'),
    ('structure', 'content', 'Structure'),
    ('pacing', 'content', 'Pacing'),
    ('emotion', 'content', 'Emotion'),
    ('cta', 'content', 'Ending and next step'),
    ('thumbnail', 'picture', 'Cover'),
    ('visual_pacing', 'picture', 'Cut rhythm'),
    ('text', 'picture', 'Text and captions'),
    ('image', 'picture', 'Lighting and image'),
    ('composition', 'picture', 'Framing'),
    ('voice', 'sound', 'Voice'),
    ('sound_design', 'sound', 'Music and effects'),
    ('mix', 'sound', 'Mix'),
    ('platform_fit', 'delivery', 'Platform fit'),
    ('access', 'delivery', 'Accessibility'),
)
DIMENSION_IDS = {item[0] for item in DIMENSIONS}
CONFIDENCE = ('low', 'medium', 'high')
VALIDATION_NOTE = ('Scores are reviewer judgments, provisional even where tested: a passed degradation test shows a '
                   'gross defect moves the score, not that the numbers agree with viewers. No score is calibrated '
                   'against viewers; see references/grading.md, Validation.')
SPEECH_MODEL = 'small'
SILENCE_LUFS = -120.0
# The unversioned paper identity from this lane's original 2.0 snapshot.
LEGACY_PAPER_RUBRIC = 'b64f2f90e30544988bd2f22f11ca74ba72cc987c918d4764653d36a44ef1b8bc'
PAUSE_PROMPT_LU = 15
FLASH_STEP = 40
find_spec = importlib.util.find_spec
VALIDATION_LABELS = {'passed_degradation_test': 'Passed a blind degradation test',
                     'partly_passed': 'Passed a blind degradation test on one of two cuts',
                     'correlated_with_human_ratings': 'Correlated with human ratings',
                     'unvalidated': 'Not validated'}
BLIND = 'Blind A/B pairs on two real cuts, one independent reviewer (2026-10-30): '
UNTESTED = 'subtle defects, agreement with viewers, other reviewers; the reviewer made the degradations.'
VALIDATION = {
    'hook': {'state': 'passed_degradation_test', 'not_tested': UNTESTED,
             'tested': BLIND + 'a greeting or a bland shot before the promise dropped it 4 and 3, at most 1 '
                               'elsewhere.'},
    'structure': {'state': 'passed_degradation_test', 'not_tested': UNTESTED,
                  'tested': BLIND + 'a shuffled middle dropped it 3 and 4, at most 2 elsewhere.'},
    'pacing': {'state': 'partly_passed', 'not_tested': UNTESTED,
               'tested': BLIND + 'dead air after each sentence dropped it 3 (interview); slowed middle shots of the '
                                 'wordless montage dropped it only 2.'},
    'emotion': {'state': 'unvalidated', 'not_tested': 'any change a reviewer cannot see or read.',
                'tested': BLIND + 'a contradicting music bed moved it 0 and 1: tone is not audible in the packet.'},
    'cta': {'state': 'passed_degradation_test', 'not_tested': UNTESTED,
            'tested': BLIND + 'an ending cut mid-thought dropped it 6 and 5, at most 2 elsewhere.'},
    'thumbnail': {'state': 'unvalidated', 'not_tested': 'click-through or any viewer response.',
                  'tested': BLIND + 'a blurred first second dropped it only 2; it also follows image and framing '
                                    'defects by design.'},
    'visual_pacing': {'state': 'partly_passed', 'not_tested': UNTESTED,
                      'tested': BLIND + 'jump-cut toggling dropped it 4 (interview); erratic montage shot lengths '
                                        'dropped it 4 but moved pacing 3.'},
    'text': {'state': 'partly_passed', 'not_tested': UNTESTED,
             'tested': BLIND + 'a faint, tiny title dropped it 5 (montage); captions shown for half their time dropped '
                               'it 5 but moved access 3 (ownership since clarified, not retested).'},
    'image': {'state': 'passed_degradation_test',
              'not_tested': 'subtle grading, noise or focus defects; agreement with viewers (the blur measure '
                            'correlates only moderately: Spearman -0.51 with KoNViD-1k viewer scores).',
              'tested': BLIND + 'two stops under dropped it 4 in both cuts; the cover followed by 2.'},
    'composition': {'state': 'partly_passed', 'not_tested': UNTESTED,
                    'tested': BLIND + 'subjects cropped out dropped it 4 in both cuts; the cover followed by 2 '
                                      '(montage) and 3 (interview).'},
    'voice': {'state': 'unvalidated',
              'not_tested': 'the judged score against listeners; its speech_vs_pause measure correlates with '
                            "listeners' noisiness ratings (Spearman 0.69, NISQA) and drives only a listen prompt.",
              'tested': BLIND + 'noise under the voice dropped it only 2, mix moved 2.'},
    'sound_design': {'state': 'partly_passed', 'not_tested': 'taste, fit or anything audible only by listening.',
                     'tested': BLIND + 'music stopping 12 s early dropped it 3 (montage); added chimes under the '
                                       'interview were invisible in the packet.'},
    'mix': {'state': 'partly_passed', 'not_tested': UNTESTED,
            'tested': BLIND + 'an 8 dB level step with overs dropped it 4 (montage); music raised over the voice '
                              'dropped it 4 but moved voice and music 3 (ownership since clarified, not retested).'},
    'platform_fit': {'state': 'unvalidated', 'not_tested': 'current platform rules, safe zones, muted viewing.',
                     'tested': BLIND + 'a windowboxed vertical rendition dropped it 5 in both cuts, but text '
                                       'followed by 3.'},
    'access': {'state': 'partly_passed', 'not_tested': 'specialist flash or caption-quality testing; ' + UNTESTED,
               'tested': BLIND + 'a full-frame strobe dropped it 6 (montage); wrong caption words dropped it 5 but '
                                 'moved text 5 (ownership since clarified, not retested).'},
}


def sibling(name):
    """Load a sibling with its usual project-local imports."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    spec = importlib.util.spec_from_file_location('lf_grade_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    """Identify the actual file without holding it in memory."""
    result = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def command(args):
    """Run a local tool and retain its error rather than silently accepting partial output."""
    result = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError(f'{Path(args[0]).name} failed: {result.stderr[-900:]}')
    return result.stdout


def probe(path):
    """Read duration and streams from the actual file."""
    raw = command(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)])
    data = json.loads(raw)
    video = next((stream for stream in data.get('streams', []) if stream.get('codec_type') == 'video'), None)
    if not video or not video.get('width') or not video.get('height'):
        raise ValueError('file has no readable video stream')
    durations = [data.get('format', {}).get('duration'), video.get('duration')]
    duration = next((float(value) for value in durations if value not in (None, 'N/A')), 0.0)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError('file has no finite positive duration')
    rotation = int(float(video.get('tags', {}).get('rotate', 0)))
    for side in video.get('side_data_list', []):
        if 'rotation' in side:
            rotation = int(float(side['rotation']))
    width = int(video['width'])
    height = int(video['height'])
    if rotation % 180:
        width, height = height, width
    audio = next((stream for stream in data.get('streams', []) if stream.get('codec_type') == 'audio'), None)
    return {
        'duration_s': duration,
        'width': width,
        'height': height,
        'fps': video.get('avg_frame_rate'),
        'audio': bool(audio),
        'audio_channels': audio.get('channels') if audio else None,
        'pixel_format': video.get('pix_fmt'),
        'color_range': video.get('color_range'),
    }


def entries(path, keys):
    """Read a list from an optional project artifact."""
    data = P.load_json(path, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    return []


def timed_words(lines, caption_words):
    """Keep words on the edit clock, preferring the compiled paper edit."""
    words = []
    for line in lines:
        words.extend(line.get('words') or [])
    if not words:
        words = caption_words
    result = []
    for word in words:
        try:
            start = float(word['start'])
            end = float(word['end'])
            text = str(word.get('text', word.get('word', ''))).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if text and math.isfinite(start) and math.isfinite(end) and 0 <= start <= end:
            result.append({'start': start, 'end': end, 'text': text, 'id': word.get('id')})
    return sorted(result, key=lambda word: (word['start'], word['end']))


def read_cues(cut):
    """Read sidecar caption cues; word JSON alone does not say how long a cue was displayed."""
    if not cut or not (cut / 'captions.srt').is_file():
        return []
    if not P.read_text(cut / 'captions.srt').strip():
        return []
    captions = sibling('captions')
    return captions.read_input(str(cut / 'captions.srt'))


NO_TRANSCRIPT_NEXT = ("Give --words FILE (word JSON, SRT or WebVTT on this file's clock), or install faster-whisper "
                      'and its model (setup.py --install transcription --download) and grade again to transcribe '
                      'locally.')


def transcription_failure(output):
    """Say why local transcription did not run and how to fix it."""
    if re.search(r"No module named '?faster_whisper", output):
        return P.dependency_message('faster_whisper')
    if 'onnxruntime' in output:
        return 'faster-whisper needs onnxruntime for its voice detector: ' + P.dependency_message('onnxruntime')
    if re.search(r'LocalEntryNotFound|snapshot|local_files_only|offline|not found in the cache', output,
                 re.IGNORECASE):
        return (f'the faster-whisper {SPEECH_MODEL} model (about 460 MB) is not downloaded; with your yes, download '
                f'it once with ' + P.python_command([HERE / 'transcribe.py', 'FILE', '--model', SPEECH_MODEL,
                                                     '--download', '--out', 'words.json']))
    last = output.strip().splitlines()[-1][-200:] if output.strip() else 'no output'
    return 'transcribe.py could not run: ' + last


def imported_transcript(path, duration):
    """Read an existing transcript; caption cues give evenly spread, estimated word times."""
    source = Path(path)
    if not source.is_file():
        raise ValueError('--words file does not exist: ' + str(source))
    rows = [row for row in sibling('transcribe').read_import(str(source)) if isinstance(row, dict)]
    words = [word for word in timed_words([], rows) if word['start'] < duration]
    if not words:
        raise ValueError('--words file has no timed words inside this file: ' + str(source))
    estimated = source.suffix.lower() in ('.srt', '.vtt') or any(row.get('estimated') for row in rows)
    note = "Imported words; their accuracy and timing were not checked against this file's audio."
    if estimated:
        note += ' Cue text is spread evenly across each cue, so word times are estimates.'
    return words, {'state': 'imported', 'engine': 'imported', 'source': source.name, 'draft': True,
                   'estimated_times': bool(estimated), 'word_count': len(words), 'note': note}


def local_transcript(video, grade_folder, media_hash, has_audio, allowed):
    """Transcribe a loose file's own audio locally with faster-whisper, reusing a cached draft."""
    if not has_audio:
        return [], {'state': 'not_applicable', 'reason': 'The file has no audio stream, so there are no words.',
                    'next': ''}
    if not allowed:
        return [], {'state': 'not_run', 'next': NO_TRANSCRIPT_NEXT,
                    'reason': 'No transcript: transcription was turned off (--no-transcribe) and no --words file '
                              'was given.'}
    target = Path(grade_folder) / f'words-{media_hash[:16]}-{SPEECH_MODEL}.json'
    info = {'state': 'transcribed', 'engine': f'faster-whisper {SPEECH_MODEL}', 'source': target.name,
            'draft': True, 'estimated_times': False,
            'note': "Draft transcript of this file's own audio, made locally; words and times can be wrong."}
    cached = P.load_json(target, None) if target.is_file() else None
    if isinstance(cached, dict) and isinstance(cached.get('words'), list):
        words = timed_words([], cached['words'])
        return words, dict(info, reused=True, language=cached.get('language'), word_count=len(words))
    if find_spec('faster_whisper') is None:
        return [], {'state': 'not_available',
                    'reason': 'No transcript: faster-whisper is not installed for this Python and no --words file '
                              'was given.',
                    'next': P.dependency_message('faster_whisper') + f' (add --download for the {SPEECH_MODEL} model, '
                            'about 460 MB, with your yes), or give --words FILE.'}
    print(f'transcript: transcribing locally with faster-whisper {SPEECH_MODEL} (draft)', flush=True)
    Path(grade_folder).mkdir(parents=True, exist_ok=True)
    args = [sys.executable, '-I', str(HERE / 'transcribe.py'), str(Path(video).resolve()), '--engine',
            'faster-whisper', '--model', SPEECH_MODEL, '--no-download', '--out', str(target)]
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    data = P.load_json(target, None) if target.is_file() else None
    if result.returncode or not isinstance(data, dict) or not isinstance(data.get('words'), list):
        reason = transcription_failure(result.stdout + result.stderr)
        return [], {'state': 'failed', 'reason': f'No transcript: {reason}.',
                    'next': 'Fix that and grade again, or give --words FILE.'}
    words = timed_words([], data['words'])
    return words, dict(info, reused=False, language=data.get('language'), word_count=len(words))


def project_transcript(lines, words):
    """Say where a version's edit-timed words came from."""
    if any(line.get('words') for line in lines if isinstance(line, dict)):
        return {'state': 'paper_edit', 'engine': 'compiled paper edit', 'source': 'lines.json', 'draft': True,
                'word_count': len(words),
                'note': "The mapped source transcript's words placed on the edit clock; not a transcript of this "
                        "render's audio."}
    if words:
        return {'state': 'captions', 'engine': 'version captions', 'source': 'captions.json', 'draft': True,
                'word_count': len(words), 'note': "Words from the version's caption file."}
    return {'state': 'not_available', 'reason': 'No transcript: the version has no edit-timed words in lines.json '
                                                'or captions.json.',
            'next': 'Compile the paper edit with mapped words (cut.py), or grade the rendered file with --file.'}


def transcript_coverage(info, words, duration):
    """Add how much of the film the words cover; flag a transcript too sparse to trust as speech."""
    spoken = sum(end - start for start, end in speech_spans(words))
    rate = 60 * len(words) / duration if duration > 0 else 0.0
    sparse = bool(words) and (len(words) < 5 or rate < 10)
    info = dict(info, speech_s=round(spoken, 2), words_per_minute=round(rate, 1), sparse=sparse)
    if sparse:
        info['note'] = (f"{info.get('note', '')} Only {len(words)} words in {duration:.1f} s: over music or "
                        'silence a transcriber can invent words; treat them as speech only after listening.').strip()
    return info


def transcript_line(info):
    """One printed line that says plainly what the reviewer has to read."""
    count = info.get('word_count', 0)
    if info['state'] == 'transcribed':
        verb = 'reused draft' if info.get('reused') else 'transcribed locally'
        return f"transcript: {verb} ({info['engine']}): {count} words"
    if info['state'] == 'imported':
        return f"transcript: imported from {info['source']}: {count} words"
    if info['state'] in ('paper_edit', 'captions'):
        return f"transcript: {info['engine']}: {count} words"
    return f"transcript: none. {info.get('reason', '')} {info.get('next', '')}".rstrip()


def brief_fields(path):
    """Read simple brief fields without pretending that prose was parsed as YAML."""
    if not path or not path.is_file():
        return {}, ''
    text = P.read_text(path)
    fields = {}
    for line in text.splitlines():
        match = re.match(r'^\s*(?:[-*]\s*)?(premise|angle|audience|platform|kind|style)\s*:\s*(.+?)\s*$',
                         line, re.IGNORECASE)
        if match:
            fields[match.group(1).lower()] = match.group(2).strip(' "\'')
    return fields, text


def project_cut(target, version=None):
    """Resolve a project and an existing version with project.py's naming rules."""
    root = P.find_project(target)
    if root is None:
        raise ValueError('no project folder at or above ' + str(target))
    chosen = version or P.current_version(root)
    if not chosen or not P.VERSION_NAME.fullmatch(chosen):
        raise ValueError('no valid rendered version; render first or use grade.py paper')
    cut = root / 'cuts' / chosen
    if not cut.is_dir() or not (cut / 'preview.mp4').is_file():
        raise ValueError('version has no preview.mp4: ' + chosen)
    return root, chosen, cut


def font(size):
    """Choose a legible system font for packet sheets."""
    for name in ('C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if Path(name).is_file():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def atomic_image(path, image):
    """Write an image atomically beside its destination."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(suffix=path.suffix, dir=str(path.parent))
    os.close(handle)
    try:
        image.save(temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def analysis_size(width, height):
    """Fit a small analysis frame without letterbox pixels contaminating measurements."""
    scale = min(160 / width, 90 / height, 1)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def face_samples(frames):
    """Use OpenCV's bundled cascade when installed; a non-detection never proves no face."""
    try:
        import cv2
    except ImportError:
        return {'state': 'not_run',
                'reason': 'Optional OpenCV missing: ' + P.python_command([HERE / 'setup.py', '--install', 'faces']),
                'note': 'No face inference; inspect the frames.'}
    directory = getattr(getattr(cv2, 'data', None), 'haarcascades', None)
    model = Path(directory or '') / 'haarcascade_frontalface_default.xml'
    if not model.is_file():
        return {'state': 'not_run', 'reason': 'OpenCV bundled face cascade not available',
                'note': 'No face inference; inspect the frames.'}
    classifier = cv2.CascadeClassifier(str(model))
    if classifier.empty():
        return {'state': 'not_run', 'reason': 'OpenCV could not load its bundled cascade',
                'note': 'No face inference; inspect the frames.'}
    for frame in frames:
        pixels = np.asarray(frame['image'])
        height, width = pixels.shape[:2]
        grey = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
        faces = classifier.detectMultiScale(grey, scaleFactor=1.1, minNeighbors=4, minSize=(18, 18))
        frame['faces'] = [[round(float(x / width), 4), round(float(y / height), 4),
                           round(float(w / width), 4), round(float(h / height), 4)] for x, y, w, h in faces]
    return {'state': 'sampled', 'method': 'OpenCV bundled Haar frontal-face cascade on reduced frames',
            'note': 'False positives and missed or non-frontal faces are possible; inspect each frame.'}


def ffmpeg_capabilities():
    """Name the installed filters and version without depending on a particular FFmpeg build."""
    version = command(['ffmpeg', '-version']).splitlines()[0]
    listing = command(['ffmpeg', '-hide_banner', '-filters'])
    filters = set()
    for line in listing.splitlines():
        fields = line.split()
        if len(fields) >= 3 and re.fullmatch(r'[TSC.]{2,3}', fields[0]):
            filters.add(fields[1])
    return version, filters


def face_signature():
    """Include the optional detector and its installed cascade in the cache identity."""
    try:
        import cv2
        folder = getattr(getattr(cv2, 'data', None), 'haarcascades', None)
        model = Path(folder or '') / 'haarcascade_frontalface_default.xml'
        if model.is_file():
            return {'opencv': cv2.__version__, 'cascade_sha256': digest(model)}
    except (ImportError, OSError):
        pass
    return {'opencv': None, 'cascade_sha256': None}


def metadata_rows(path, kind):
    """Stream FFmpeg's printed frame metadata without holding a film's frames in memory."""
    if not path.is_file():
        return
    current = None
    with path.open(encoding='utf-8', errors='replace') as source:
        for line in source:
            match = re.match(r'^frame:\s*(\d+)\s+pts:\s*(-?\d+)\s+pts_time:\s*(\S+)', line)
            if match:
                if current is not None:
                    yield current
                try:
                    moment = float(match.group(3))
                except ValueError:
                    moment = None
                if moment is not None and not math.isfinite(moment):
                    moment = None
                current = {'type': kind, 'frame': int(match.group(1)), 'pts': int(match.group(2)),
                           'pts_time': moment, 'values': {}}
            elif current is not None and '=' in line:
                key, value = line.strip().split('=', 1)
                try:
                    number = float(value)
                    value = number if math.isfinite(number) else None
                except ValueError:
                    pass
                current['values'][key] = value
    if current is not None:
        yield current


def ffmpeg_graph(facts, filters, step, width, height):
    """Build a single decode graph; optional filters are recorded when unavailable."""
    if not {'signalstats', 'metadata'}.issubset(filters):
        return None, []
    names = ['signalstats=stat=tout+brng']
    requested = ['scdet', 'siti', 'entropy', 'blurdetect', 'blockdetect']
    names.extend(name for name in requested if name in filters)
    if 'cropdetect' in filters:
        names.append('cropdetect=round=2:reset=1:skip=0')
    if 'freezedetect' in filters:
        names.append('freezedetect')
    names.extend(['metadata=mode=print:file=video.txt', f'fps=1/{step:.9f}',
                  f'scale={width}:{height}', 'format=rgb24'])
    graph = '[0:v:0]' + ','.join(names) + '[v]'
    used = ['signalstats'] + [name for name in requested if name in filters]
    used += [name for name in ('cropdetect', 'freezedetect') if name in filters]
    if facts['audio'] and {'ebur128', 'astats', 'ametadata'}.issubset(filters):
        # Only astats measures that FFmpeg 5.1 (the oldest supported release) knows; Peak_count covers clipping counts.
        audio = ['ebur128=metadata=1', 'astats=metadata=1:reset=1:'
                 'measure_perchannel=DC_offset+Peak_level+RMS_level+Min_level+Max_level+Peak_count:'
                 'measure_overall=DC_offset+Peak_level+RMS_level+Peak_count+Number_of_samples']
        used.extend(['ebur128', 'astats'])
        if facts.get('audio_channels') == 2 and 'aphasemeter' in filters:
            audio.append('aphasemeter=video=0')
            used.append('aphasemeter')
        audio.append('ametadata=mode=print:file=audio.txt')
        graph += ';[0:a:0]' + ','.join(audio) + '[a]'
    return graph, used


def decode_with_metadata(video, facts, filters):
    """Decode each stream once for metadata and bounded visual samples."""
    step = max(0.25, facts['duration_s'] / 80)
    width, height = analysis_size(facts['width'], facts['height'])
    graph, used = ffmpeg_graph(facts, filters, step, width, height)
    if graph is None:
        raise ValueError('FFmpeg lacks signalstats or metadata')
    temporary = tempfile.TemporaryDirectory(prefix='lf-grade-')
    folder = Path(temporary.name)
    source = str(Path(video).resolve())
    args = ['ffmpeg', '-v', 'error', '-threads', '1', '-filter_complex_threads', '1', '-i', source,
            '-filter_complex', graph, '-map', '[v]', '-fps_mode', 'passthrough', '-f', 'rawvideo', 'pipe:1']
    if '[a]' in graph:
        args.extend(['-map', '[a]', '-f', 'null', os.devnull])
    samples = []
    try:
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=errors, cwd=folder)
            size = width * height * 3
            while True:
                payload = bytearray()
                while len(payload) < size:
                    part = process.stdout.read(size - len(payload))
                    if not part:
                        break
                    payload.extend(part)
                if not payload:
                    break
                if len(payload) != size:
                    raise ValueError('FFmpeg returned a partial sample frame')
                image = Image.frombytes('RGB', (width, height), bytes(payload))
                samples.append({'t': round(min(len(samples) * step, facts['duration_s']), 3), 'image': image})
            process.stdout.close()
            code = process.wait()
            errors.seek(0)
            diagnostic = errors.read().decode('utf-8', 'replace').strip()
            if code or diagnostic:
                raise ValueError('FFmpeg analysis failed or reported a decode error: ' + diagnostic[-800:])
        if not samples or not (folder / 'video.txt').is_file():
            raise ValueError('FFmpeg produced no samples or video metadata')
        return temporary, samples, step, used
    except BaseException:
        temporary.cleanup()
        raise


def add_shot(shots, start, end, first, last, totals):
    """Close one candidate shot with its mean luma and saturation where measured."""
    count = totals['count']
    shots.append({'start_s': round(start, 4), 'end_s': round(end, 4), 'first_frame': first, 'last_frame': last,
                  'mean_y': round(totals['y'] / count, 3) if count else None,
                  'mean_saturation': round(totals['sat'] / count, 3) if count else None})


def flash_screen(changes, step):
    """The most large whole-frame brightness changes inside any one second, and when it starts."""
    worst = 0
    worst_t = None
    for index, moment in enumerate(changes):
        count = bisect.bisect_left(changes, moment + 1.0) - index
        if count > worst:
            worst, worst_t = count, moment
    return {'threshold_8bit': FLASH_STEP, 'changes': len(changes), 'max_in_1s': worst, 'max_in_1s_t': worst_t,
            'note': f'Frame-to-frame changes of average luma above {FLASH_STEP} (8-bit code values, scaled to the '
                    'bit depth). A whole-frame screen: it misses local flashes and red flashes and is not a '
                    'photosensitivity test.'}


def bit_depth(facts):
    """Luma bit depth from the pixel format name (yuv420p10le is 10); 8 when the name gives none."""
    match = re.search(r'p(\d+)', str(facts.get('pixel_format') or ''))
    return int(match.group(1)) if match else 8


def collect_video(rows, samples, duration, depth=8):
    """Summarize candidate cuts and match each contact-sheet sample to nearby frame metadata."""
    step = FLASH_STEP * 2 ** (depth - 8)
    previous_y = None
    changes = []
    sample_times = [frame['t'] for frame in samples]
    best = [math.inf] * len(samples)
    shots = []
    totals = {'count': 0, 'y': 0.0, 'sat': 0.0}
    start = 0.0
    first = 0
    last = 0
    count = 0
    for row in rows:
        count += 1
        time = row['pts_time']
        values = row['values']
        if time is None:
            continue
        index = bisect.bisect_left(sample_times, time)
        for position in (index - 1, index):
            if 0 <= position < len(samples) and abs(time - sample_times[position]) < best[position]:
                best[position] = abs(time - sample_times[position])
                samples[position]['source_frame'] = row['frame']
                samples[position]['source_pts_time'] = time
                samples[position]['metadata'] = dict(values)
        score = values.get('lavfi.scd.score')
        if finite_number(score) and score >= 10 and row['frame'] > first:
            add_shot(shots, start, max(start, time), first, last, totals)
            start = max(0.0, time)
            first = row['frame']
            totals = {'count': 0, 'y': 0.0, 'sat': 0.0}
        y = values.get('lavfi.signalstats.YAVG')
        sat = values.get('lavfi.signalstats.SATAVG')
        if finite_number(y):
            if previous_y is not None and abs(y - previous_y) > step:
                changes.append(time)
            previous_y = y
        if finite_number(y) and finite_number(sat):
            totals['count'] += 1
            totals['y'] += y
            totals['sat'] += sat
        last = row['frame']
    if count:
        add_shot(shots, start, max(start, duration), first, last, totals)
    return {'frame_count': count, 'shots': shots, 'cut_threshold': 10, 'flash_screen': flash_screen(changes, step),
            'note': 'scdet candidates are not verified edits; flashes can trigger them and cuts can be missed.'}


def collect_audio(rows, facts):
    """Summarize per-channel peaks, DC offset, loudness and stereo phase without downmixing."""
    count = 0
    max_peak = None
    max_peak_time = None
    max_dc = None
    minimum_phase = None
    minimum_phase_time = None
    momentary = []
    for row in rows:
        count += 1
        values = row['values']
        peak = values.get('lavfi.astats.Overall.Peak_level')
        dc = values.get('lavfi.astats.Overall.DC_offset')
        phase = values.get('lavfi.aphasemeter.phase')
        loud = values.get('lavfi.r128.M')
        if finite_number(peak):
            if max_peak is None or peak > max_peak:
                max_peak = peak
                max_peak_time = row['pts_time']
        if finite_number(dc):
            max_dc = abs(dc) if max_dc is None else max(max_dc, abs(dc))
        if finite_number(phase) and finite_number(peak) and peak > -60:
            if minimum_phase is None or phase < minimum_phase:
                minimum_phase = phase
                minimum_phase_time = row['pts_time']
        if finite_number(loud) and row['pts_time'] is not None:
            momentary.append({'t': row['pts_time'], 'lufs': loud})
        elif ('lavfi.r128.M' in values and loud is None and row['pts_time'] is not None
              and values.get('lavfi.astats.Overall.Peak_level', 0) is None):
            momentary.append({'t': row['pts_time'], 'lufs': SILENCE_LUFS})
    phase_note = ('Measured on stereo above -60 dBFS sample peak; this local silence screen is not an audibility test. '
                  'Negative correlation can indicate mono loss.')
    if facts.get('audio_channels') != 2:
        phase_note = 'Not measured: input is not exactly stereo.'
    next_step = None
    if facts['audio'] and not count:
        next_step = 'Install FFmpeg ebur128, astats and ametadata filters, then rerun the grade.'
    return {'present': facts['audio'], 'frame_count': count, 'max_sample_peak_dbfs': max_peak,
            'max_sample_peak_t': max_peak_time, 'max_abs_dc_offset': max_dc,
            'min_stereo_phase': minimum_phase, 'min_stereo_phase_t': minimum_phase_time, 'phase_note': phase_note,
            'momentary_lufs': momentary, 'next': next_step,
            'note': 'Mixed audio only; startup loudness windows are incomplete, and peaks are not true peak. '
                    f'Digital silence (no sample above zero) is recorded at {SILENCE_LUFS:.0f} LUFS.'}


def sample_metrics(samples):
    """Use native-frame FFmpeg metadata as thumbnail context, not a click score."""
    keys = {'y_avg': 'lavfi.signalstats.YAVG', 'y_low': 'lavfi.signalstats.YLOW',
            'y_high': 'lavfi.signalstats.YHIGH', 'saturation': 'lavfi.signalstats.SATAVG',
            'broadcast_outside_share': 'lavfi.signalstats.BRNG', 'blur': 'lavfi.blur',
            'blockiness': 'lavfi.block', 'spatial_information': 'lavfi.siti.si',
            'temporal_information': 'lavfi.siti.ti'}
    for frame in samples:
        metadata = frame.pop('metadata', {})
        frame['metrics'] = {key: metadata.get(source) for key, source in keys.items()}


def png_base64(image):
    """Encode one bounded sample for the reusable cache."""
    data = io.BytesIO()
    image.save(data, format='PNG')
    return base64.b64encode(data.getvalue()).decode('ascii')


def cache_key(video_hash, facts, version, filters):
    """A cache depends on the input, decoder, filter set, detector and analysis configuration."""
    return {'media_sha256': video_hash, 'ffmpeg': version, 'filters': sorted(filters), 'pipeline': 1,
            'script_sha256': digest(HERE / 'grade.py'),
            'duration_s': facts['duration_s'], 'width': facts['width'], 'height': facts['height'],
            'audio_channels': facts.get('audio_channels'), 'face_detector': face_signature()}


def read_frame_cache(path, expected):
    """Load a complete matching cache, streaming past per-frame data; otherwise return None."""
    if not path.is_file():
        return None
    header = None
    footer = None
    samples = []
    content_hash = hashlib.sha256()
    video_count = 0
    audio_count = 0
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                if row.get('type') != 'footer':
                    content_hash.update(line.encode('utf-8'))
                if row.get('type') == 'header':
                    header = row
                elif row.get('type') == 'video':
                    video_count += 1
                elif row.get('type') == 'audio':
                    audio_count += 1
                elif row.get('type') == 'sample':
                    payload = base64.b64decode(row.pop('png'))
                    row['image'] = Image.open(io.BytesIO(payload)).convert('RGB')
                    row.pop('type')
                    samples.append(row)
                elif row.get('type') == 'footer':
                    footer = row
        if not header or header.get('key') != expected or not footer or not footer.get('complete') or not samples:
            return None
        if (footer.get('content_sha256') != content_hash.hexdigest()
                or footer.get('video', {}).get('frame_count') != video_count
                or footer.get('audio', {}).get('frame_count') != audio_count):
            return None
        return samples, header['step_s'], header['faces'], footer['video'], footer['audio'], header['used_filters']
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def write_frame_cache(path, key, samples, step, faces, used, folder, facts):
    """Write one compact JSON Lines gzip file with every video/audio frame and bounded still samples."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.frames-', suffix='.gz', dir=str(path.parent))
    os.close(handle)
    try:
        with gzip.open(temporary, 'wt', encoding='utf-8', newline='\n') as output:
            content_hash = hashlib.sha256()
            def write(row, checksum=True):
                line = json.dumps(row, separators=(',', ':'), allow_nan=False) + '\n'
                output.write(line)
                if checksum:
                    content_hash.update(line.encode('utf-8'))
            write({'type': 'header', 'version': 1, 'key': key, 'step_s': step, 'faces': faces,
                   'used_filters': used, 'source_pixel_format': facts['pixel_format'],
                   'source_color_range': facts['color_range'],
                   'note': 'Filter metadata is in FFmpeg negotiated format; inspect code values in context.'})
            def video_rows():
                for row in metadata_rows(folder / 'video.txt', 'video'):
                    write(row)
                    yield row
            video_summary = collect_video(video_rows(), samples, facts['duration_s'], bit_depth(facts))
            def audio_rows():
                for row in metadata_rows(folder / 'audio.txt', 'audio'):
                    write(row)
                    yield row
            audio_summary = collect_audio(audio_rows(), facts)
            sample_metrics(samples)
            for sample in samples:
                row = {key: value for key, value in sample.items() if key != 'image'}
                row.update({'type': 'sample', 'png': png_base64(sample['image'])})
                write(row)
            write({'type': 'footer', 'complete': True, 'video': video_summary, 'audio': audio_summary,
                   'content_sha256': content_hash.hexdigest()}, checksum=False)
        os.replace(temporary, path)
        return video_summary, audio_summary
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def cached_measurements(video, facts, media_hash, grade_folder):
    """Reuse measurements when identity matches; otherwise make a complete atomic sidecar."""
    version, filters = ffmpeg_capabilities()
    key = cache_key(media_hash, facts, version, filters)
    path = grade_folder / 'frames.jsonl.gz'
    existing = read_frame_cache(path, key)
    if existing:
        return (*existing, path, True)
    temporary, samples, step, used = decode_with_metadata(video, facts, filters)
    try:
        faces = face_samples(samples)
        video_summary, audio_summary = write_frame_cache(path, key, samples, step, faces, used,
                                                         Path(temporary.name), facts)
    finally:
        temporary.cleanup()
    return samples, step, faces, video_summary, audio_summary, used, path, False


def make_scopes(video, grade_folder, summary, media_hash, filters):
    """Render waveform and vectorscope images for representative candidate-shot frames."""
    if not {'waveform', 'vectorscope'}.issubset(filters):
        return {'state': 'not_run', 'reason': 'FFmpeg lacks waveform or vectorscope',
                'next': 'Install an FFmpeg build with both filters and rerun the grade.'}
    shots = summary['shots']
    selected = shots[:400]
    if not selected:
        return {'state': 'not_run', 'reason': 'No decoded candidate shots',
                'next': 'Check that the video decodes and regenerate the frame sidecar.'}
    indices = [(row['first_frame'] + row['last_frame']) // 2 for row in selected]
    identity = hashlib.sha256(json.dumps([media_hash, indices, 'scope-v2']).encode('utf-8')).hexdigest()[:20]
    destination = grade_folder / ('scopes-' + identity)
    index_path = destination / 'index.json'
    existing = P.load_json(index_path, None)
    if isinstance(existing, dict) and existing.get('media_sha256') == media_hash:
        files = [destination / item[kind] for item in existing.get('shots', []) for kind in ('waveform', 'vectorscope')]
        if files and all(path.is_file() for path in files):
            return {'state': 'available', 'folder': destination, 'shots': len(selected),
                    'of_candidate_shots': len(shots), 'sampled': len(shots) > len(selected), 'cached': True}
    stage = Path(tempfile.mkdtemp(prefix='.scopes-', dir=str(grade_folder)))
    try:
        expression = '+'.join(f'eq(n,{number})' for number in indices)
        graph = (f"[0:v:0]select='{expression}',scale=320:-2,format=yuv444p,split=2[w][c];"
                 '[w]waveform=graticule=green,format=rgb24[wave];'
                 '[c]vectorscope=mode=color3:graticule=color,format=rgb24[vector]')
        args = ['ffmpeg', '-v', 'error', '-threads', '1', '-filter_complex_threads', '1', '-i', str(video),
                '-filter_complex', graph, '-map', '[wave]', '-fps_mode', 'passthrough', '-start_number', '0',
                str(stage / 'wave-%04d.png'), '-map', '[vector]', '-fps_mode', 'passthrough', '-start_number', '0',
                str(stage / 'vector-%04d.png')]
        result = subprocess.run(args, capture_output=True, encoding='utf-8', errors='replace')
        entries_found = []
        for number, shot in enumerate(selected):
            waveform = f'wave-{number:04d}.png'
            vectorscope = f'vector-{number:04d}.png'
            if not (stage / waveform).is_file() or not (stage / vectorscope).is_file():
                return {'state': 'not_run', 'reason': 'Scope output missing: ' + result.stderr[-2000:],
                        'next': 'Run FFmpeg waveform and vectorscope on the affected frames.'}
            entries_found.append({'start_s': shot['start_s'], 'end_s': shot['end_s'], 'frame': indices[number],
                                  'waveform': waveform, 'vectorscope': vectorscope})
        if result.returncode:
            return {'state': 'not_run', 'reason': result.stderr[-500:],
                    'next': 'Run FFmpeg waveform and vectorscope on the affected frames.'}
        P.save_json(stage / 'index.json', {'version': 1, 'media_sha256': media_hash, 'shots': entries_found,
                                          'candidate_shots': len(shots), 'note':
                                          'Downscaled representative frames; scdet candidates need inspection.'})
        if destination.exists():
            return {'state': 'not_run', 'reason': 'Scope cache exists but is incomplete',
                    'next': 'Move the incomplete scope cache aside and regenerate it.'}
        stage.rename(destination)
        return {'state': 'available', 'folder': destination, 'shots': len(selected),
                'of_candidate_shots': len(shots), 'sampled': len(shots) > len(selected), 'cached': False}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def section_facts(lines):
    """Collect section intervals from the compiled lines, including the paper line numbers."""
    result = []
    for line in lines:
        name = str(line.get('section') or '(unsectioned)')
        if not isinstance(line.get('start'), (int, float)) or not isinstance(line.get('end'), (int, float)):
            continue
        if result and result[-1]['name'] == name:
            result[-1]['end'] = max(result[-1]['end'], float(line['end']))
            result[-1]['lines'].append(line.get('line'))
        else:
            result.append({'name': name, 'start': float(line['start']), 'end': float(line['end']),
                           'lines': [line.get('line')]})
    return result


def caption_facts(cues, duration):
    """Measure sidecar cue timing, not burned text, accuracy, contrast or reading comprehension."""
    result = []
    for cue in cues:
        start = float(cue['start'])
        end = float(cue['end'])
        text = str(cue.get('text', ''))
        count = len(text.split())
        rate = round(60 * count / (end - start), 1) if end > start else None
        result.append({'start': start, 'end': end, 'words': count, 'wpm': rate,
                       'outside_film': start < 0 or end > duration or end <= start,
                       'review': bool(rate is not None and rate > 180)})
    return result


def timeline_facts(lines, words, cues, duration, checks):
    """Summarize what the existing edit-clock data can and cannot establish."""
    gaps = []
    if words:
        gaps.append((0.0, max(0.0, words[0]['start'])))
        gaps.extend((left['end'], right['start']) for left, right in zip(words, words[1:]))
        gaps.append((words[-1]['end'], duration))
    valid_gaps = [(a, b) for a, b in gaps if 0 <= a <= b <= duration]
    longest = max(valid_gaps, key=lambda item: item[1] - item[0]) if valid_gaps else None
    return {
        'first_word_s': words[0]['start'] if words else None,
        'word_count': len(words),
        'word_rate_over_film_wpm': round(len(words) * 60 / duration, 1) if words else None,
        'longest_word_gap': {'start': longest[0], 'end': longest[1]} if longest else None,
        'sections': section_facts(lines),
        'caption_cues': caption_facts(cues, duration),
        'checks': checks.get('items', []) if isinstance(checks, dict) else [],
        'note': 'Word gaps are not silence; draft words and sidecars require verification against the delivery.',
    }


def visual_facts(frames, step, faces):
    """Summarize sampled pixel evidence without treating it as an image-quality score."""
    fields = ('y_low', 'y_avg', 'y_high', 'saturation', 'broadcast_outside_share', 'blur', 'blockiness',
              'spatial_information', 'temporal_information')
    result = {'sample_interval_s': round(step, 4), 'sample_count': len(frames), 'faces': faces,
              'note': 'FFmpeg metadata at nearby sampled frames; not colour accuracy or click prediction.'}
    for field in fields:
        values = [frame['metrics'].get(field) for frame in frames if finite_number(frame['metrics'].get(field))]
        result[field + '_median'] = round(float(np.median(values)), 4) if values else None
    result['samples'] = [{'t': frame['t'], **frame['metrics'], 'faces': frame.get('faces')}
                         for frame in frames]
    return result


def candidate_frames(frames, count=12):
    """Pick varied moments with observable detail; this does not predict attention or clicks."""
    chosen = []
    buckets = min(count, len(frames))
    for index in range(buckets):
        left = index * len(frames) // buckets
        right = (index + 1) * len(frames) // buckets
        pool = frames[left:right]
        def interest(frame):
            metrics = frame['metrics']
            low = metrics.get('y_low') or 0
            high = metrics.get('y_high') or 0
            detail = metrics.get('spatial_information') or 0
            face = max((box[2] * box[3] for box in frame.get('faces', [])), default=0)
            return detail + 0.25 * max(0, high - low) + 10 * face
        winner = max(pool, key=interest)
        chosen.append(winner)
    return chosen


def contact_sheet(frames, path, title, width=168):
    """Save a labelled sheet with no text covering the images."""
    columns = 4
    tile_height = 138
    rows = math.ceil(len(frames) / columns)
    result = Image.new('RGB', (columns * 210, rows * tile_height + 46), '#f3f1ed')
    draw = ImageDraw.Draw(result)
    draw.text((10, 10), title, fill='#222222', font=font(17))
    for index, frame in enumerate(frames):
        image = frame['image'].copy()
        image.thumbnail((width, 100), Image.Resampling.LANCZOS)
        left = (index % columns) * 210 + 10
        top = (index // columns) * tile_height + 46
        result.paste(image, (left, top))
        draw.text((left, top + 103), f"~{frame['t']:.2f}s", fill='#222222', font=font(14))
    atomic_image(path, result)


def write_thumbs(frames, out, source_hash, duration, faces):
    """Write candidate evidence and a sheet, preserving the limits of the selection heuristic."""
    out.mkdir(parents=True, exist_ok=True)
    chosen = candidate_frames(frames)
    contact_sheet(chosen, out / 'thumbs.jpg', 'Cover candidates - inspect at feed size')
    data = {'version': 1, 'media_sha256': source_hash, 'duration_s': duration,
            'selection': 'one frame per time bin, using detail, contrast and any detected face; not click prediction',
            'face_detector': faces,
            'time_basis': 'approximate sample grid; use frame_sheet.py for exact presentation timestamps',
            'candidates': [{'t': frame['t'], 'metrics': frame['metrics'], 'detected_faces': frame.get('faces')}
                           for frame in chosen]}
    P.save_json(out / 'thumbs.json', data)
    return data


def opening_sheet(video, duration, packet):
    """Use frame_sheet.py's presentation timestamps for a dense opening, or record the failure."""
    stop = min(5.0, duration)
    times = [round(number / 10, 2) for number in range(math.ceil(stop * 10)) if number / 10 < duration]
    target = packet / 'opening.png'
    args = [sys.executable, '-I', str(HERE / 'frame_sheet.py'), str(video), '--at',
            ','.join(str(time) for time in times), '--width', '200', '--cols', '5', '--out', str(target)]
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode or not target.is_file():
        return {'state': 'not_run', 'reason': (result.stderr + result.stdout)[-500:],
                'next': 'Run frame_sheet.py at the opening times on the delivered file.'}
    return {'state': 'available', 'path': 'opening.png', 'sample_rate_hz': 10, 'end_s': stop,
            'note': 'Presentation-time-labelled sampled stills, not playback.'}


def detail_sheet(video, facts, packet, count=8):
    """Exact frames at a readable size, so text, focus, noise and framing can be inspected."""
    duration = facts['duration_s']
    times = [round(duration * (index + 0.5) / count, 2) for index in range(count)]
    landscape = facts['width'] >= facts['height']
    width = min(640 if landscape else 360, facts['width'])
    target = packet / 'detail.png'
    args = [sys.executable, '-I', str(HERE / 'frame_sheet.py'), str(video), '--at', ','.join(map(str, times)),
            '--width', str(width), '--cols', '2' if landscape else '4', '--out', str(target)]
    result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode or not target.is_file():
        return {'state': 'not_run', 'reason': (result.stderr + result.stdout)[-500:],
                'next': 'Run frame_sheet.py at these times on the delivered file.', 'times': times}
    return {'state': 'available', 'path': 'detail.png', 'times': times, 'tile_width': width,
            'source_width': facts['width'],
            'note': 'Exact frames at the middle of eight equal parts of the film, up to 640 px wide (360 px for '
                    'portrait), for reading text and checking focus, noise and framing. Not playback.'}


def speech_spans(words, join=0.25):
    """Merge word intervals separated by less than `join` seconds into spoken phrases."""
    spans = []
    for word in words:
        if spans and word['start'] - spans[-1][1] < join:
            spans[-1][1] = max(spans[-1][1], word['end'])
        else:
            spans.append([word['start'], word['end']])
    return spans


def speech_pause_levels(momentary, words, duration, window=0.4, floor=-70.0):
    """Compare momentary loudness inside spoken phrases with loudness in the pauses between them."""
    if not words:
        return {'state': 'not_run', 'reason': 'No timed words, so speech and pauses cannot be told apart.'}
    spans = speech_spans(words)
    starts = [span[0] for span in spans]
    speech = []
    pause = []
    for row in momentary or []:
        moment = row.get('t')
        value = row.get('lufs')
        if not finite_number(moment) or not finite_number(value) or moment < window or moment > duration:
            continue
        begin = moment - window
        index = bisect.bisect_right(starts, begin) - 1
        if index >= 0 and spans[index][1] >= moment:
            speech.append(max(floor, value))
        elif (index < 0 or spans[index][1] <= begin) and (index + 1 >= len(spans) or spans[index + 1][0] >= moment):
            pause.append(max(floor, value))
    times = sorted(row['t'] for row in momentary or [] if finite_number(row.get('t')))
    spacing = float(np.median(np.diff(times))) if len(times) > 1 else 0.0
    result = {'speech_windows': len(speech), 'pause_windows': len(pause), 'floor_lufs': floor,
              'speech_window_s': round(len(speech) * spacing, 2), 'pause_window_s': round(len(pause) * spacing, 2),
              'note': 'Momentary loudness (400 ms) wholly inside spoken phrases versus wholly inside pauses. '
                      'Background noise, music or room tone raises the pause level; it does not say which. '
                      'Not a noise floor, intelligibility or voice-quality score; word times are drafts.'}
    if result['speech_window_s'] < 0.5 or result['pause_window_s'] < 0.5:
        return dict(result, state='not_enough_pauses',
                    reason='Less than half a second of 400 ms windows wholly inside phrases or pauses to compare.')
    speech_level = float(np.median(speech))
    pause_level = float(np.median(pause))
    return dict(result, state='measured', speech_lufs=round(speech_level, 1), pause_lufs=round(pause_level, 1),
                speech_minus_pause_lu=round(speech_level - pause_level, 1))


def sound_sheet(audio, words, duration, packet):
    """Draw momentary loudness over time with spoken words shaded, for reviewers who cannot listen."""
    rows = [(row['t'], max(-70.0, row['lufs'])) for row in audio.get('momentary_lufs') or []
            if finite_number(row.get('t')) and finite_number(row.get('lufs'))]
    if not rows or duration <= 0:
        return {'state': 'not_run', 'reason': 'No momentary loudness was measured.',
                'next': 'Check that the file has audio and FFmpeg has ebur128.'}
    width, height, left, top, bottom = 1200, 300, 64, 34, 36
    plot_w = width - left - 16
    plot_h = height - top - bottom
    image = Image.new('RGB', (width, height), '#ffffff')
    draw = ImageDraw.Draw(image)
    def x_at(moment):
        return left + plot_w * min(max(moment / duration, 0), 1)
    def y_at(level):
        return top + plot_h * (min(max(level, -70.0), 0.0) / -70.0)
    for start, end in speech_spans(words):
        draw.rectangle([x_at(start), top, x_at(end), top + plot_h], fill='#dbe8f6')
    for level in range(0, -71, -10):
        draw.line([left, y_at(level), left + plot_w, y_at(level)], fill='#d9d9d9')
        draw.text((6, y_at(level) - 8), f'{level}', fill='#444444', font=font(13))
    step = max(1, round(duration / 12))
    for second in range(0, int(duration) + 1, step):
        draw.text((x_at(second) - 6, top + plot_h + 6), f'{second}s', fill='#444444', font=font(13))
    draw.line([(x_at(moment), y_at(level)) for moment, level in rows], fill='#1f4e79', width=2)
    peak_time = audio.get('max_sample_peak_t')
    if finite_number(peak_time):
        draw.line([x_at(peak_time), top, x_at(peak_time), top + plot_h], fill='#b3261e', width=1)
    draw.text((left, 8), 'Momentary loudness (LUFS, 400 ms); blue bands: transcribed words; red line: highest '
              'sample peak. Measured, not heard.', fill='#222222', font=font(14))
    atomic_image(packet / 'sound.png', image)
    return {'state': 'available', 'path': 'sound.png',
            'note': 'A picture of measured loudness against the transcript; it does not show what the sounds are.'}


def transcript_text(words, info=None):
    """Make a readable, edit-timed transcript without promoting draft words to verified captions."""
    info = info or {}
    lines = ['# Edit-timed transcript', '']
    if info.get('state') in ('transcribed', 'imported', 'paper_edit', 'captions'):
        lines.append(f"Source: {info.get('engine')} ({info.get('source')}). {info.get('note', '')}")
    lines.extend(['Words may be draft. Times are seconds on the edit clock.', ''])
    for word in words:
        lines.append(f"{word['start']:.3f}-{word['end']:.3f}  {word['text']}")
    if not words:
        reason = info.get('reason') or 'No transcript: no edit-timed words were available.'
        lines.append(f"{reason} {info.get('next', '')}".rstrip())
        lines.append('Without words, hook, structure, pacing and ending can be judged only from pictures and sound '
                     'measurements; say so in any score.')
    return '\n'.join(lines) + '\n'


def packet_instructions():
    """Give a reviewer a concrete, portable evidence and merge protocol."""
    return '''# Grading packet

Read grading.md and the brief. This packet is local and may contain private material.
Inspect opening.png, overview.jpg, thumbs.jpg, detail.png, sound.png, any strip/ images,
transcript.md, timeline.json, measurements.json and scopes/index.json when available.
detail.png has exact frames at a readable size: read burned captions and titles there and compare
them with transcript.md. sound.png draws measured loudness against the transcribed words; a hard
stop, a level jump or a raised floor in the pauses is visible there, but not what the sound is.
transcript.md says where its words came from. A sparse transcript (a few words over music) may be
invented by the transcriber; do not score speech from it. The complete streaming per-frame data is
in frames.jsonl.gz, keyed to the media hash. Scope images use downscaled representative frames
of automatically detected candidate shots; a missed cut gets no separate scope. Use the brief,
platform, kind and declared style to interpret them.
The opening sheet samples ten instants per second for its stated window; it is not a video.
Transcripts and captions can be wrong. A mixed audio envelope is not listening, speech isolation,
noise floor or intelligibility. Check the actual file and request a person's viewing and listening.

Copy judged.json to a different file. Fill judge, independent and judge_provenance (model_family,
model, and same_family_as_cut_maker true/false or null when unknown). Each dimension has
id, integer score 0-10, confidence low/medium/high, evidence and an optional fix. A scored item
needs at least one evidence item: {"t": 0.0, "end": 1.0, "kind": "frame", "ref": "opening.png",
"note": "what is visible and why it matters"}. Other kinds: transcript, measurement, check, brief,
person. For transcript evidence include an exact quote from transcript.md inside that time range.
Use a packet file as ref. Times are edit seconds and must be inside the file. A fix has text and
may have line and gain (an estimated 0-10 point gain, not a measured result). Cite paper lines when
known. Do not assign a score when you lack evidence; leave the item out. A person's own score comes
from the Screening Room's project-root scores.json; the reviewer must not invent a person rating.

Keep media_sha256 and packet_id unchanged. Run `grade.py merge PROJECT filled.json`, or
`grade.py merge filled.json --file FILE` for a standalone file. A different reviewer should judge
independently when available. A self-judgment is low confidence. Stills and
transcript alone cannot establish how motion, music, mix or voice sound at normal speed.
Scores are provisional until the required independent degradation and human-rating evaluations pass.
'''


def copy_strips(cut, packet):
    """Reuse existing strips when present; do not imply they were generated when absent."""
    strips = sorted((cut / 'strip').glob('strip-*')) if cut else []
    strips = [path for path in strips if path.suffix.lower() in ('.png', '.jpg', '.jpeg') and path.is_file()]
    if not strips:
        return {'state': 'not_available', 'next': 'Run strip.py on the version for screening strips.'}
    destination = packet / 'strip'
    destination.mkdir(parents=True, exist_ok=True)
    for path in strips:
        shutil.copy2(path, destination / path.name)
    return {'state': 'available', 'paths': ['strip/' + path.name for path in strips]}


def packet_id(media_hash, lines, words, cues, checks, brief, measurements, files, context):
    """Bind a rating to the media, evidence, brief, code and rubric used to make the packet."""
    value = {'media_sha256': media_hash, 'lines': lines, 'words': words, 'cues': cues, 'checks': checks,
             'brief': brief, 'measurements': measurements, 'script_sha256': digest(HERE / 'grade.py'),
             'rubric_sha256': digest(HERE.parent / 'references' / 'grading.md'), 'evidence_files': files,
             'context': context}
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def base_dimensions(audio_present):
    """Every dimension starts waiting or explicitly not applicable, never at a guessed zero."""
    result = []
    for key, group, label in DIMENSIONS:
        no_audio = not audio_present and key in ('voice', 'sound_design', 'mix')
        reason = 'No audio stream; intentional silence is possible.' if no_audio else 'Waiting for supported judgment.'
        result.append({'id': key, 'group': group, 'label': label, 'score': None, 'basis': None,
                       'confidence': None, 'status': 'not_scored' if no_audio else 'waiting',
                       'reason': reason, 'measures': {}, 'evidence': [], 'assessments': []})
    return result


def make_packet(video, cut, packet, lines, words, cues, checks, brief, media_hash, facts, frames, step, audio,
                context, faces, ffmpeg_info, scopes, cache_path, transcript):
    """Collect the actual inputs and local evidence needed for an independent review."""
    packet.mkdir(parents=True, exist_ok=True)
    timeline = timeline_facts(lines, words, cues, facts['duration_s'], checks)
    timeline['transcript'] = transcript
    visual = visual_facts(frames, step, faces)
    measurements = {'visual': visual, 'audio': audio, 'timeline': timeline, 'ffmpeg': ffmpeg_info}
    write_thumbs(frames, packet, media_hash, facts['duration_s'], faces)
    contact_sheet(frames[::max(1, len(frames) // 32)], packet / 'overview.jpg', 'Overview - sampled instants')
    opening = opening_sheet(video, facts['duration_s'], packet)
    detail = detail_sheet(video, facts, packet)
    sound = sound_sheet(audio, words, facts['duration_s'], packet) if facts['audio'] else {
        'state': 'not_applicable', 'reason': 'No audio stream.'}
    strips = copy_strips(cut, packet)
    if scopes.get('state') == 'available':
        shutil.copytree(scopes['folder'], packet / 'scopes')
    try:
        os.link(cache_path, packet / 'frames.jsonl.gz')
    except OSError:
        shutil.copy2(cache_path, packet / 'frames.jsonl.gz')
    P.save_json(packet / 'timeline.json', {'lines': lines, 'words': words, 'caption_cues': cues})
    P.save_json(packet / 'measurements.json', measurements)
    P.write_atomic(packet / 'transcript.md', transcript_text(words, transcript))
    P.write_atomic(packet / 'brief.md', brief or 'No brief supplied. Ask for audience, purpose, platform and style.\n')
    P.write_atomic(packet / 'instructions.md', packet_instructions())
    P.write_atomic(packet / 'grading.md', P.read_text(HERE.parent / 'references' / 'grading.md'))
    evidence_files = {}
    for path in sorted(packet.rglob('*')):
        if path.is_file() and path.name not in ('packet.json', 'judged.json'):
            evidence_files[path.relative_to(packet).as_posix()] = digest(path)
    identity = packet_id(media_hash, lines, words, cues, checks, brief, measurements, evidence_files, context)
    info = {'version': 1, 'packet_id': identity, 'media_sha256': media_hash, 'duration_s': facts['duration_s'],
            'opening': opening, 'detail': detail, 'sound': sound, 'transcript': transcript, 'strips': strips,
            'scopes': {key: value for key, value in scopes.items() if key != 'folder'},
            'context': context, 'evidence_files': evidence_files, 'limits': [
                'Still frames do not establish playback or listening quality.',
                'Transcript and caption accuracy need a person to check the delivered audio.',
                'Automated diagnostics are not quality scores or release approval.']}
    P.save_json(packet / 'packet.json', info)
    judged = packet / 'judged.json'
    if not judged.exists():
        P.save_json(judged, {'version': 1, 'packet_id': identity, 'media_sha256': media_hash, 'judge': '',
                             'independent': False, 'judge_provenance': {'model_family': '', 'model': '',
                                                                        'same_family_as_cut_maker': None},
                             'dimensions': []})
    return identity, measurements, info


def dimension_measures(dimensions, facts, measurements):
    """Attach the relevant narrow signals to each dimension, with their scope visible."""
    timeline = measurements['timeline']
    visual = measurements['visual']
    audio = measurements['audio']
    by_id = {row['id']: row for row in dimensions}
    words_state = (timeline.get('transcript') or {}).get('state')
    by_id['hook']['measures'] = {'first_word_s': timeline['first_word_s'], 'transcript': words_state}
    by_id['structure']['measures'] = {'sections': timeline['sections'], 'transcript': words_state}
    by_id['pacing']['measures'] = {'word_count': timeline['word_count'],
                                   'word_rate_over_film_wpm': timeline['word_rate_over_film_wpm'],
                                   'longest_word_gap': timeline['longest_word_gap'], 'transcript': words_state}
    by_id['cta']['measures'] = {'sections': timeline['sections'], 'transcript': words_state}
    by_id['thumbnail']['measures'] = {'sample_count': visual['sample_count'], 'face_detection': visual['faces']}
    native = measurements['ffmpeg']['video']
    by_id['visual_pacing']['measures'] = {'sample_interval_s': visual['sample_interval_s'],
                                         'candidate_shots': native['shots'],
                                         'note': native['note']}
    by_id['text']['measures'] = {'caption_cues': timeline['caption_cues'],
                                 'note': 'Sidecar cue timing only; rendered text was not detected.'}
    by_id['image']['measures'] = {key: value for key, value in visual.items() if key != 'samples'}
    by_id['composition']['measures'] = {'face_detection': visual['faces'], 'subject_detection': 'not run',
                                        'black_border_candidates': 'see cropdetect in frames.jsonl.gz'}
    for key in ('voice', 'sound_design', 'mix'):
        by_id[key]['measures'] = {key: value for key, value in audio.items()
                                  if key not in ('rms_dbfs', 'momentary_lufs')}
    by_id['platform_fit']['measures'] = {'width': facts['width'], 'height': facts['height'],
                                         'duration_s': facts['duration_s']}
    by_id['access']['measures'] = {'checks': timeline['checks'], 'caption_cue_count': len(timeline['caption_cues'])}


def review_prompts(measurements):
    """Name concrete observations to inspect without turning screening thresholds into judgments."""
    result = []
    timeline = measurements['timeline']
    for cue in timeline['caption_cues']:
        if cue['review']:
            result.append({'dimension': 'text', 't': cue['start'], 'end': cue['end'],
                           'text': f"Sidecar cue is {cue['wpm']} words/min; inspect the actual reading window.",
                           'next': 'Check accuracy and legibility, then extend the hold or reduce competing content.'})
    audio = measurements['audio']
    peak = audio.get('max_sample_peak_dbfs')
    if finite_number(peak) and peak > -0.1:
        result.append({'dimension': 'mix', 't': audio.get('max_sample_peak_t'),
                       'text': f'Sample peak reached {peak:.2f} dBFS; near-full-scale is not proof of clipping.',
                       'next': 'Inspect the decoded waveform and listen; check true peak on the delivery.'})
    phase = audio.get('min_stereo_phase')
    if finite_number(phase) and phase < -0.8:
        result.append({'dimension': 'mix', 't': audio.get('min_stereo_phase_t'),
                       'text': f'Stereo phase reached {phase:.2f}; negative phase can cause mono cancellation.',
                       'next': 'Compare the same interval in stereo and a mono fold-down.'})
    levels = audio.get('speech_vs_pause') or {}
    if levels.get('state') == 'measured' and levels['speech_minus_pause_lu'] < PAUSE_PROMPT_LU:
        result.append({'dimension': 'voice', 't': None,
                       'text': f"Speech is only {levels['speech_minus_pause_lu']:.1f} LU above the pauses: noise, room "
                               'or a music bed fills them. In public phone-speech ratings (NISQA), most recordings '
                               f'below {PAUSE_PROMPT_LU} LU were rated noticeably noisy.',
                       'next': 'Listen to a pause: if it is noise, clean the dialogue; if it is a deliberate bed, '
                               'check that the words stay clear.'})
    screen = (measurements.get('ffmpeg', {}).get('video') or {}).get('flash_screen') or {}
    if (screen.get('max_in_1s') or 0) >= 6:
        result.append({'dimension': 'access', 't': screen.get('max_in_1s_t'),
                       'text': f"{screen['max_in_1s']} large whole-frame brightness changes within one second: "
                               'possible flashing; this screen is not a photosensitivity test.',
                       'next': 'Run check.py (or flash_scan.py) on the file and remove or soften the flashes if they '
                               'fail.'})
    for check in timeline['checks']:
        if check.get('state') in ('fail', 'look'):
            dimension = {'spec': 'platform_fit', 'loudness': 'mix', 'edges': 'mix',
                         'flash': 'access', 'blank': 'image', 'captions': 'text'}.get(check.get('id'), 'access')
            result.append({'dimension': dimension, 't': check.get('at'),
                           'text': f"Check {check.get('id', '?')}: {check.get('state')} - {check.get('detail', '')}",
                           'next': 'Inspect this check on the delivered file and decide the cause.'})
    return result


def summarize(card):
    """Calculate a clearly labeled average of only the dimensions with supported scores."""
    rows = [row for row in card['dimensions'] if row.get('score') is not None]
    scores = [row['score'] for row in rows]
    card['overall'] = {'score': round(sum(scores) * 10 / len(scores), 1) if scores else None,
                       'scored': len(scores), 'of': len(DIMENSIONS),
                       'weights': 'equal among scored dimensions; uncalibrated',
                       'note': 'Person scores take precedence. A partial average changes with coverage or basis.'}
    card['groups'] = {}
    for group in ('content', 'picture', 'sound', 'delivery'):
        values = [row['score'] for row in rows if row['group'] == group]
        card['groups'][group] = round(sum(values) / len(values), 2) if values else None
    card['not_scored'] = [{'id': row['id'], 'reason': row['reason']} for row in card['dimensions']
                          if row['status'] == 'not_scored']
    fixes = []
    for row in rows:
        fix = row.get('fix')
        if fix:
            fixes.append({'dimension': row['id'], 'text': fix['text'], 'line': fix.get('line'),
                          't': (row.get('fix_source') or {}).get('t'), 'gain': fix.get('gain'),
                          'proposed_by': (row.get('fix_source') or {}).get('judged_by'),
                          'gain_basis': 'reviewer estimate, not a measured improvement'})
    card['fixes'] = sorted(fixes, key=lambda item: (item['gain'] is None, -(item['gain'] or 0)))


def parent_change(root, card, manifest):
    """Compare matching dimensions and expose changes in coverage or basis."""
    parent = manifest.get('parent') if isinstance(manifest, dict) else None
    if not parent or not P.VERSION_NAME.fullmatch(str(parent)):
        return None
    old = P.load_json(root / 'cuts' / parent / 'scorecard.json', None)
    if not isinstance(old, dict):
        return {'version': parent, 'state': 'not_scored'}
    before = {row['id']: row for row in old.get('dimensions', [])}
    after = {row['id']: row for row in card['dimensions']}
    changed = {}
    for key, current in after.items():
        previous = before.get(key, {})
        if previous.get('score') != current.get('score'):
            changed[key] = [previous.get('score'), current.get('score')]
    old_set = {(row.get('id'), row.get('basis')) for row in before.values() if row.get('score') is not None}
    new_set = {(row.get('id'), row.get('basis')) for row in after.values() if row.get('score') is not None}
    return {'version': parent, 'overall': (old.get('overall') or {}).get('score'), 'changed': changed,
            'comparable_coverage_and_basis': bool(old_set and old_set == new_set)}


def esc(value):
    """Escape data before putting it into the standalone HTML."""
    return html.escape(str(value), quote=True)


def provenance_text(provenance):
    """Describe attributed model details without inventing the cut maker's family."""
    if not isinstance(provenance, dict):
        return ''
    same = provenance.get('same_family_as_cut_maker')
    relationship = 'unknown' if same is None else ('yes' if same else 'no')
    return (f"Model: {provenance.get('model') or 'not recorded'}; family: "
            f"{provenance.get('model_family') or 'not recorded'}; same family as cut maker: {relationship}.")


def render_html(card):
    """Make a portable card with evidence, uncertainty, fixes and parent comparison."""
    overall = card['overall']
    title = f"{overall['score']}/100" if overall['score'] is not None else 'Waiting for review'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width,initial-scale=1">',
             '<title>Legible Film scorecard</title><style>',
             'body{font:16px/1.55 system-ui,sans-serif;background:#f5f3ef;color:#202124;margin:0}',
             'main{max-width:960px;margin:auto;padding:2rem 1rem 4rem}h1,h2,h3{line-height:1.2}',
             '.hero,.item{background:#fff;border:1px solid #ddd7cc;border-radius:12px;padding:1rem;margin:1rem 0}',
             '.meta{color:#5c5b57}.score{font-size:1.45rem;font-weight:700}.badge{font-size:.9rem}',
             'ul{padding-left:1.4rem}code{overflow-wrap:anywhere}details{margin-top:.5rem}</style><main>',
             '<h1>Scorecard</h1>', f'<div class="hero"><div class="score">{esc(title)}</div>',
             f'<p>{overall["scored"]}/{overall["of"]} dimensions scored. {esc(overall["note"])}</p>',
             f'<p class="meta">{esc(card.get("validation", {}).get("reason", VALIDATION_NOTE))}</p>',
             '<p class="meta">A tool for the maker, not delivery approval. Playback and listening remain open.</p>',
             '<p class="meta">A person\'s recorded score takes precedence; reviewer assessments remain below.</p>',
             f'<p>{esc(card.get("platform") or "Platform unspecified")} / '
             f'{esc(card.get("kind") or "kind unspecified")} / {card["duration_s"]:.2f}s</p></div>']
    for group in ('content', 'picture', 'sound', 'delivery'):
        parts.append(f'<h2>{esc(group.title())}</h2>')
        for row in card['dimensions']:
            if row['group'] != group:
                continue
            score = 'Waiting' if row['status'] == 'waiting' else 'Not scored'
            if row['score'] is not None:
                score = str(row['score']) + '/10'
            parts.append(f'<section class="item"><h3>{esc(row["label"])}: {esc(score)}</h3>')
            state = VALIDATION_LABELS.get(row.get('validation'), 'Not validated')
            parts.append(f'<p class="meta">Validation: {esc(state)}. {esc(row.get("validation_detail", ""))}</p>')
            if row['score'] is None:
                parts.append(f'<p class="meta">{esc(row.get("reason", ""))}</p>')
            else:
                parts.append(f'<p class="badge">{esc(row["basis"])} / {esc(row["confidence"])} confidence / '
                             f'{esc(row.get("judged_by", ""))}</p>')
                if row.get('judge_provenance'):
                    parts.append(f'<p class="meta">{esc(provenance_text(row["judge_provenance"]))}</p>')
                parts.append('<ul>')
                for item in row['evidence']:
                    time = f'{item["t"]:.2f}s' if finite_number(item.get('t')) else 'Whole cut'
                    end = f'-{item["end"]:.2f}s' if finite_number(item.get('end')) else ''
                    quote = f' Quote: "{esc(item["quote"])}"' if item.get('quote') else ''
                    parts.append(f'<li>{esc(time)}{end}: {esc(item["note"])}{quote} '
                                 f'[{esc(item.get("ref", ""))}]</li>')
                parts.append('</ul>')
            if row.get('fix'):
                parts.append(f'<p><strong>Possible fix:</strong> {esc(row["fix"]["text"])}</p>')
            if row.get('measures'):
                parts.append('<details><summary>Measured context</summary><pre style="white-space:pre-wrap">'
                             + esc(json.dumps(row['measures'], ensure_ascii=False, indent=1)) + '</pre></details>')
            if len(row.get('assessments', [])) > 1:
                parts.append('<details><summary>All assessments</summary><ul>')
                for rating in row['assessments']:
                    parts.append(f'<li>{esc(rating["basis"])}: {rating["score"]}/10, '
                                 f'{esc(rating["judged_by"])}, {esc(rating["confidence"])} confidence. '
                                 f'{esc(provenance_text(rating.get("judge_provenance")))}<ul>')
                    for evidence in rating['evidence']:
                        moment = f'{evidence["t"]:.2f}s' if finite_number(evidence.get('t')) else 'Whole cut'
                        parts.append(f'<li>{esc(moment)}: {esc(evidence["note"])} '
                                     f'[{esc(evidence.get("ref", ""))}]</li>')
                    parts.append('</ul></li>')
                parts.append('</ul></details>')
            parts.append('</section>')
    parts.append('<h2>Suggested fixes</h2><ol>')
    for fix in card['fixes']:
        gain = '' if fix['gain'] is None else f' (estimated gain {fix["gain"]}; not measured)'
        moment = '' if not finite_number(fix.get('t')) else f' at {fix["t"]:.2f}s'
        parts.append(f'<li>{esc(fix["text"])}{esc(moment)}{esc(gain)}</li>')
    if not card['fixes']:
        parts.append('<li>None supported yet.</li>')
    parts.append('</ol><h2>Measurements to inspect</h2><ul>')
    for prompt in card.get('review_prompts', []):
        at = '' if prompt.get('t') is None else f" at {prompt['t']:.2f}s"
        parts.append(f'<li>{esc(prompt["text"])}{esc(at)} {esc(prompt["next"])}</li>')
    if not card.get('review_prompts'):
        parts.append('<li>No threshold-based prompts; review the available evidence.</li>')
    parts.append('</ul><h2>Change from parent</h2>')
    parts.append('<pre style="white-space:pre-wrap">' + esc(json.dumps(card.get('parent'), indent=1)) + '</pre>')
    parts.append('</main></html>\n')
    return ''.join(parts)


def apply_validation(card):
    """Attach what each dimension's score has and has not been tested against."""
    counts = {}
    for row in card['dimensions']:
        entry = VALIDATION[row['id']]
        row['validation'] = entry['state']
        row['validation_detail'] = f"Tested: {entry['tested']} Not tested: {entry['not_tested']}"
        counts[entry['state']] = counts.get(entry['state'], 0) + 1
    passed = counts.get('passed_degradation_test', 0) + counts.get('partly_passed', 0)
    card['validation'] = {'state': 'partial' if passed else 'unvalidated', 'by_state': counts,
                          'reason': VALIDATION_NOTE, 'table': 'references/grading.md, Validation'}


def save_card(paths, card):
    """Write both card formats atomically, with each dimension's validation state."""
    apply_validation(card)
    summarize(card)
    P.save_json(paths[0], card)
    P.write_atomic(paths[1], render_html(card))


def caption_words(cut):
    """Flatten word-timed caption cues when compiled lines have no words."""
    if not cut:
        return []
    cues = entries(cut / 'captions.json', ('cues', 'words', 'captions', 'items'))
    words = []
    for cue in cues:
        if isinstance(cue, dict):
            words.extend(cue.get('words') or [cue])
    return words


def replace_packet(video, cut, grade, lines, words, cues, checks, brief, media_hash, facts, frames, step, audio,
                   context, faces, ffmpeg_info, scopes, cache_path, transcript):
    """Build a fresh packet before archiving the old one, including any unfinished reviewer work."""
    grade.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.packet-', dir=str(grade)))
    try:
        result = make_packet(video, cut, temporary, lines, words, cues, checks, brief, media_hash, facts, frames,
                             step, audio, context, faces, ffmpeg_info, scopes, cache_path, transcript)
        current = grade / 'packet'
        if current.exists():
            name = P.now().replace(':', '').replace('-', '')
            archive = grade / ('packet-previous-' + name)
            number = 1
            while archive.exists():
                archive = grade / ('packet-previous-' + name + '-' + str(number))
                number += 1
            current.rename(archive)
        temporary.rename(current)
        return result
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def card_paths(video, cut, file_mode):
    """Where a card and its grade folder live: per version in a project, per file beside a loose file."""
    if file_mode:
        base = video.parent / video.stem
        return (Path(str(base) + '.scorecard.json'), Path(str(base) + '.scorecard.html'),
                Path(str(base) + '.grade'))
    return cut / 'scorecard.json', cut / 'scorecard.html', cut / 'grade'


def grade_video(target, version, file_arg, platform, kind, brief_arg, words_arg=None, transcribe=True):
    """Measure the selected file, prepare a reviewer packet and write a scorecard."""
    root = None
    cut = None
    manifest = {}
    if file_arg:
        video = Path(file_arg).resolve()
        selected = None
        brief_path = Path(brief_arg).resolve() if brief_arg else None
    else:
        if words_arg:
            raise ValueError("--words is for --file; a version's words come from its lines.json")
        root, selected, cut = project_cut(target or '.', version)
        video = cut / 'preview.mp4'
        brief_path = Path(brief_arg).resolve() if brief_arg else root / 'brief.md'
        manifest = P.load_json(cut / 'manifest.json', {}) or {}
    if not video.is_file():
        raise ValueError('file does not exist: ' + str(video))
    if brief_arg and not brief_path.is_file():
        raise ValueError('brief does not exist: ' + str(brief_path))
    card_json, card_html, grade_folder = card_paths(video, cut, bool(file_arg))
    P.refuse_overwriting_inputs([card_json, card_html], [video, brief_path, words_arg])
    fields, brief = brief_fields(brief_path)
    facts = probe(video)
    source_hash = digest(video)
    lines = entries(cut / 'lines.json', ('lines', 'items')) if cut else []
    if file_arg and words_arg:
        words, transcript = imported_transcript(words_arg, facts['duration_s'])
    elif file_arg:
        words, transcript = local_transcript(video, grade_folder, source_hash, facts['audio'], transcribe)
    else:
        words = timed_words(lines, caption_words(cut))
        transcript = project_transcript(lines, words)
    transcript = transcript_coverage(transcript, words, facts['duration_s'])
    print(transcript_line(transcript), flush=True)
    transcript.pop('reused', None)
    cues = read_cues(cut)
    checks = P.load_json(cut / 'checks.json', {}) if cut else {}
    grade_folder.mkdir(parents=True, exist_ok=True)
    frames, step, faces, native_video, audio, used, cache_path, reused = cached_measurements(
        video, facts, source_hash, grade_folder)
    if transcript.get('sparse'):
        levels = {'state': 'not_run', 'reason': 'The transcript has too few words to trust as speech.'}
    else:
        levels = speech_pause_levels(audio.get('momentary_lufs'), words, facts['duration_s'])
    audio = dict(audio, speech_vs_pause=levels)
    _, filters = ffmpeg_capabilities()
    scopes = make_scopes(video, grade_folder, native_video, source_hash, filters)
    if digest(video) != source_hash:
        raise ValueError('video changed during analysis; grade the stable file again')
    ffmpeg_info = {'sidecar': 'frames.jsonl.gz', 'sidecar_sha256': digest(cache_path),
                   'filters': used, 'video': native_video,
                   'note': 'FFmpeg metadata is measurement evidence, not a craft score or proof of accessibility.'}
    context = {'platform': platform or fields.get('platform'), 'kind': kind or fields.get('kind'),
               'brief_fields': fields}
    identity, measurements, packet = replace_packet(video, cut, grade_folder, lines, words, cues, checks, brief,
                                                     source_hash, facts, frames, step, audio, context, faces,
                                                     ffmpeg_info, scopes, cache_path, transcript)
    dimensions = base_dimensions(facts['audio'])
    dimension_measures(dimensions, facts, measurements)
    old = P.load_json(card_json, None)
    if isinstance(old, dict) and old.get('packet_id') == identity:
        prior = {row['id']: row for row in old.get('dimensions', [])}
        for row in dimensions:
            existing = prior.get(row['id']) or {}
            if existing.get('assessments'):
                row['assessments'] = existing['assessments']
                choose_assessment(row)
    elif isinstance(old, dict):
        previous = grade_folder / ('scorecard-previous-' + str(old.get('packet_id', 'unknown'))[:16] + '.json')
        if not previous.exists():
            P.save_json(previous, old)
    file_label = video.relative_to(root).as_posix() if root else video.name
    packet_label = (grade_folder.name if file_arg else 'grade') + '/packet'
    card = {'version': 1, 'file': file_label, 'media_sha256': source_hash, 'packet_id': identity,
            'film_version': selected, 'platform': platform or fields.get('platform'),
            'kind': kind or fields.get('kind'), 'brief_fields': fields, 'duration_s': facts['duration_s'],
            'graded': P.now(), 'skill_version': P.skill_version(), 'transcript': transcript,
            'dimensions': dimensions, 'packet': packet_label, 'packet_limits': packet['limits'],
            'packet_evidence_sha256': evidence_hash(packet['evidence_files']),
            'review_prompts': review_prompts(measurements), 'parent': None}
    if root:
        sync_person_scores(root, selected, dimensions)
    summarize(card)
    if root:
        card['parent'] = parent_change(root, card, manifest)
    save_card((card_json, card_html), card)
    print(f'scorecard: {card_json}')
    print(f"review packet: {grade_folder / 'packet'}")
    print('Per-frame evidence: ' + ('reused' if reused else 'measured') + f' {cache_path}')
    print(f"{card['overall']['scored']}/{len(DIMENSIONS)} dimensions scored; playback and listening remain open")
    return 1 if card['overall']['scored'] < len(DIMENSIONS) else 0


def finite_number(value):
    """Whether a value is a finite, non-boolean JSON number."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def evidence_hash(files):
    """Digest a packet's manifest so changed evidence cannot be merged under the old identity."""
    raw = json.dumps(files, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def verify_packet_files(packet, info, card):
    """Ensure the packet still contains the evidence used when its scorecard was made."""
    files = info.get('evidence_files')
    if not isinstance(files, dict) or evidence_hash(files) != card.get('packet_evidence_sha256'):
        raise ValueError('packet evidence manifest changed; regenerate and review the packet')
    for name, expected in files.items():
        if digest(validate_reference(packet, name)) != expected:
            raise ValueError('packet evidence changed: ' + name)


def tokens(text):
    """Normalize case and punctuation only for checking a transcript quotation."""
    return re.findall(r'\w+', str(text).casefold(), flags=re.UNICODE)


def validate_quote(quote, start, end, words):
    """A quoted word sequence must occur in the cited edit-time interval."""
    available = []
    for word in words:
        overlap = word['start'] <= start < word['end'] if start == end else word['end'] > start and word['start'] < end
        if overlap:
            available.extend(tokens(word['text']))
    wanted = tokens(quote)
    if not wanted:
        return False
    return any(available[index:index + len(wanted)] == wanted
               for index in range(len(available) - len(wanted) + 1))


def validate_reference(packet, ref):
    """Accept only an existing packet file and reject absolute paths, traversal and symlink escape."""
    if not isinstance(ref, str) or not ref.strip() or Path(ref).is_absolute():
        raise ValueError('evidence ref must name a file in the packet')
    candidate = (packet / ref).resolve()
    try:
        candidate.relative_to(packet.resolve())
    except ValueError:
        raise ValueError('evidence ref escapes the packet') from None
    if not candidate.is_file():
        raise ValueError('evidence ref not found in packet: ' + ref)
    return candidate


def validate_evidence(items, packet, duration, words, opening, evidence_files):
    """Reject missing, out-of-film, unreferenced and falsely quoted evidence."""
    if not isinstance(items, list) or not items:
        raise ValueError('every score needs evidence')
    clean = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each evidence item must be an object')
        start = item.get('t')
        end = item.get('end', start)
        valid_time = finite_number(start) and finite_number(end) and 0 <= start < duration and start <= end <= duration
        if not valid_time:
            raise ValueError('evidence time must be inside the film')
        note = item.get('note')
        if not isinstance(note, str) or not note.strip():
            raise ValueError('evidence needs a non-empty observation')
        kind = item.get('kind')
        if kind not in ('frame', 'transcript', 'measurement', 'check', 'brief', 'person'):
            raise ValueError('evidence needs a recognized kind')
        ref = item.get('ref')
        reference = validate_reference(packet, ref)
        if ref not in evidence_files:
            raise ValueError('evidence ref was not part of the reviewed packet: ' + ref)
        if kind == 'frame' and reference.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
            raise ValueError('frame evidence must reference a packet image')
        if kind == 'transcript' and ref not in ('transcript.md', 'timeline.json'):
            raise ValueError('transcript evidence must reference the edit-timed transcript')
        if ref == 'opening.png' and (opening.get('state') != 'available' or end > opening.get('end_s', 0)):
            raise ValueError('opening sheet does not cover the cited time')
        quote = item.get('quote')
        if kind == 'transcript' and (not isinstance(quote, str) or not validate_quote(quote, start, end, words)):
            raise ValueError('transcript quote does not match words in the cited interval')
        if quote is not None and kind != 'transcript':
            raise ValueError('quote requires transcript evidence; describe visible text in the note')
        clean.append({'t': float(start), 'end': float(end), 'kind': kind, 'ref': ref,
                      'note': note.strip(), **({'quote': quote} if quote is not None else {})})
    return clean


def validate_fix(fix, lines):
    """Validate optional reviewer estimates and paper line references."""
    if fix is None:
        return None
    if not isinstance(fix, dict) or not isinstance(fix.get('text'), str) or not fix['text'].strip():
        raise ValueError('fix needs non-empty text')
    line = fix.get('line')
    known = {row.get('line') for row in lines if isinstance(row, dict)}
    if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line not in known):
        raise ValueError('fix line is not in the compiled paper edit')
    gain = fix.get('gain')
    if gain is not None and (not finite_number(gain) or not 0 <= gain <= 10):
        raise ValueError('fix gain must be an estimate from 0 to 10')
    return {'text': fix['text'].strip(), 'line': line, 'gain': gain}


def validate_judge_provenance(value):
    """Require the reviewer to identify its model and report the maker-family relationship."""
    if not isinstance(value, dict):
        raise ValueError('judgment needs judge_provenance with model_family, model and same_family_as_cut_maker')
    family = value.get('model_family')
    model = value.get('model')
    if not isinstance(family, str) or not family.strip() or not isinstance(model, str) or not model.strip():
        raise ValueError('judge_provenance needs a non-empty model_family and model')
    if 'same_family_as_cut_maker' not in value or value['same_family_as_cut_maker'] not in (True, False, None):
        raise ValueError('same_family_as_cut_maker must be true, false or null when unknown')
    same = value['same_family_as_cut_maker']
    if same is not None and type(same) is not bool:
        raise ValueError('same_family_as_cut_maker must be true, false or null when unknown')
    return {'model_family': family.strip(), 'model': model.strip(), 'same_family_as_cut_maker': same}


def choose_assessment(row):
    """Show a person's latest rating first, then independent and self-judgments."""
    ratings = row['assessments']
    if not ratings:
        no_audio = row['id'] in ('voice', 'sound_design', 'mix') and row.get('measures', {}).get('present') is False
        row.update({'score': None, 'basis': None, 'confidence': None, 'evidence': [], 'judged_by': None,
                    'judge_provenance': None, 'independent': None,
                    'fix': None, 'fix_source': None, 'status': 'not_scored' if no_audio else 'waiting',
                    'reason': 'No audio stream; intentional silence is possible.' if no_audio
                    else 'Waiting for supported judgment.'})
        return
    for rating in ratings:
        if rating.get('basis') == 'judged' and not rating.get('judge_provenance'):
            rating['judge_provenance'] = {'model_family': None, 'model': None, 'same_family_as_cut_maker': None}
            rating['provenance_status'] = 'not_recorded'
            rating['confidence'] = 'low'
    def priority(pair):
        index, rating = pair
        rank = 2 if rating['basis'] == 'person' else (1 if rating['independent'] else 0)
        return rank, index
    selected = max(enumerate(ratings), key=priority)[1]
    keys = ('score', 'basis', 'confidence', 'evidence', 'judged_by', 'judge_provenance', 'independent')
    row.update({key: selected.get(key) for key in keys})
    with_fixes = [(i, rating) for i, rating in enumerate(ratings) if rating.get('fix')]
    proposer = max(with_fixes, key=priority)[1] if with_fixes else None
    row['fix'] = proposer.get('fix') if proposer else None
    first = (proposer.get('evidence') or [{}])[0] if proposer else {}
    row['fix_source'] = {'t': first.get('t'), 'judged_by': proposer.get('judged_by')} if proposer else None
    row['status'] = 'scored'
    row['reason'] = ''


def sync_person_scores(root, version, dimensions):
    """Read the room's ratings without writing them or inventing their evidence."""
    path = root / 'scores.json'
    document = P.load_json(path, None) if path.is_file() else {'version': 1, 'scores': {}}
    if not isinstance(document, dict) or type(document.get('version')) is not int or document['version'] != 1:
        raise ValueError('scores.json must have version 1 and a scores object')
    versions = document.get('scores')
    if not isinstance(versions, dict):
        raise ValueError('scores.json scores must be an object')
    scores = versions.get(version, {})
    if not isinstance(scores, dict):
        raise ValueError('scores.json entry for ' + version + ' must be an object')
    by_id = {row['id']: row for row in dimensions}
    for key, value in scores.items():
        if key not in by_id or not isinstance(value, dict):
            raise ValueError('scores.json has an unknown dimension or invalid entry: ' + str(key))
        score = value.get('score')
        at = value.get('at')
        if type(score) is not int or not 0 <= score <= 10 or value.get('by') != 'person':
            raise ValueError('scores.json ' + key + ' needs a person score from 0 to 10')
        if not isinstance(at, str) or not at.strip():
            raise ValueError('scores.json ' + key + ' needs an at timestamp')
    for row in dimensions:
        row['assessments'] = [item for item in row.get('assessments', [])
                              if item.get('source') != 'scores.json' and item.get('basis') != 'person']
        value = scores.get(row['id'])
        if value is not None:
            evidence = {'t': None, 'end': None, 'kind': 'person', 'ref': 'scores.json',
                        'note': 'Person recorded a whole-cut score; viewing and listening are not implied.',
                        'at': value['at']}
            row['assessments'].append({'score': value['score'], 'basis': 'person', 'confidence': 'low',
                                       'evidence': [evidence], 'judged_by': 'person', 'independent': False,
                                       'fix': None, 'source': 'scores.json', 'at': value['at']})
        choose_assessment(row)


def refresh_person_scores(target, version):
    """Refresh the persisted card without decoding video or modifying the room's scores."""
    root, selected, cut = project_cut(target, version)
    paths = card_paths(cut / 'preview.mp4', cut, False)
    card = P.load_json(paths[0], None)
    packet = paths[2] / 'packet'
    info = P.load_json(packet / 'packet.json', None)
    if not isinstance(card, dict) or not isinstance(info, dict):
        raise ValueError('scorecard or packet is missing; run grade.py PROJECT first')
    actual = digest(cut / 'preview.mp4')
    if card.get('film_version') != selected or card.get('media_sha256') != actual:
        raise ValueError('scorecard does not match this video; run grade.py PROJECT again')
    if info.get('media_sha256') != actual or info.get('packet_id') != card.get('packet_id'):
        raise ValueError('scorecard and packet do not match; run grade.py PROJECT again')
    verify_packet_files(packet, info, card)
    sync_person_scores(root, selected, card['dimensions'])
    summarize(card)
    card['parent'] = parent_change(root, card, P.load_json(cut / 'manifest.json', {}) or {})
    save_card(paths[:2], card)
    print(f"refreshed {selected} from scores.json; {card['overall']['scored']}/15 dimensions scored")
    return 1 if card['overall']['scored'] < len(DIMENSIONS) else 0


def merge_judgment(target, version, path, file_arg=None):
    """Validate the complete submission before changing either scorecard file."""
    root = None
    if file_arg:
        video = Path(file_arg).resolve()
        if not video.is_file():
            raise ValueError('file does not exist: ' + str(video))
        cut = None
        selected = video.name
    else:
        root, selected, cut = project_cut(target, version)
        video = cut / 'preview.mp4'
    paths = card_paths(video, cut, bool(file_arg))
    P.refuse_overwriting_inputs(paths[:2], [path, video])
    card = P.load_json(paths[0], None)
    packet = paths[2] / 'packet'
    info = P.load_json(packet / 'packet.json', None)
    judgment = P.load_json(path, None)
    if not isinstance(card, dict) or not isinstance(info, dict) or not isinstance(judgment, dict):
        raise ValueError('scorecard, packet or judgment JSON is missing or invalid')
    actual = digest(video)
    if any(value != actual for value in (card.get('media_sha256'), info.get('media_sha256'),
                                          judgment.get('media_sha256'))):
        raise ValueError('judgment, packet and actual video must have the same media hash')
    if judgment.get('packet_id') != card.get('packet_id') or info.get('packet_id') != card.get('packet_id'):
        raise ValueError('judgment was made from a different or stale packet')
    verify_packet_files(packet, info, card)
    judge = judgment.get('judge')
    independent = judgment.get('independent')
    if not isinstance(judge, str) or not judge.strip() or not isinstance(independent, bool):
        raise ValueError('give the reviewer name and independent true or false')
    provenance = validate_judge_provenance(judgment.get('judge_provenance'))
    raw = judgment.get('dimensions')
    if not isinstance(raw, list) or not raw:
        raise ValueError('judgment has no scored dimensions')
    timeline = P.load_json(packet / 'timeline.json', {})
    words = timeline.get('words', [])
    lines = timeline.get('lines', [])
    seen = set()
    validated = []
    for item in raw:
        if not isinstance(item, dict) or item.get('id') not in DIMENSION_IDS:
            raise ValueError('unknown or missing dimension id')
        key = item['id']
        if key in seen:
            raise ValueError('duplicate dimension in one judgment: ' + key)
        seen.add(key)
        score = item.get('score')
        if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 10:
            raise ValueError(key + ': score must be an integer from 0 to 10')
        basis = item.get('basis', 'judged')
        confidence = item.get('confidence')
        if basis != 'judged' or confidence not in CONFIDENCE:
            raise ValueError(key + ': merge accepts judged ratings only; person scores come from scores.json')
        if not independent or provenance['same_family_as_cut_maker'] is None or key in ('voice', 'sound_design', 'mix'):
            confidence = 'low'
        elif confidence == 'high':
            confidence = 'medium'
        evidence = validate_evidence(item.get('evidence'), packet, card['duration_s'], words, info['opening'],
                                     info['evidence_files'])
        fix = validate_fix(item.get('fix'), lines)
        validated.append((key, {'score': score, 'basis': basis, 'confidence': confidence, 'evidence': evidence,
                                 'judged_by': judge.strip(), 'independent': independent, 'fix': fix,
                                 'judge_provenance': provenance, 'packet_id': card['packet_id'], 'at': P.now()}))
    by_id = {row['id']: row for row in card['dimensions']}
    for key, rating in validated:
        by_id[key].setdefault('assessments', []).append(rating)
        choose_assessment(by_id[key])
    if root:
        sync_person_scores(root, selected, card['dimensions'])
    summarize(card)
    if root:
        card['parent'] = parent_change(root, card, P.load_json(cut / 'manifest.json', {}) or {})
    save_card(paths[:2], card)
    print(f"merged {len(validated)} assessments into {selected}; {card['overall']['scored']}/15 dimensions scored")
    return 1 if card['overall']['scored'] < len(DIMENSIONS) else 0


def merge_paper(result, judgment, words):
    """Validate a paper review against the exact compiled edit before accepting it."""
    if not isinstance(judgment, dict) or judgment.get('paper_id') != result['paper_id']:
        raise ValueError('paper judgment does not match this compiled edit and brief')
    judge = judgment.get('judge')
    independent = judgment.get('independent')
    if not isinstance(judge, str) or not judge.strip() or not isinstance(independent, bool):
        raise ValueError('paper judgment needs a reviewer name and independent true or false')
    provenance = validate_judge_provenance(judgment.get('judge_provenance'))
    raw = judgment.get('dimensions')
    if not isinstance(raw, list) or not raw:
        raise ValueError('paper judgment has no dimensions')
    allowed = {row['id'] for row in result['dimensions']}
    validated = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or item.get('id') not in allowed or item['id'] in seen:
            raise ValueError('each paper judgment dimension needs "id" set once to one of: '
                             + ', '.join(sorted(allowed)))
        key = item['id']
        seen.add(key)
        score = item.get('score')
        if type(score) is not int or not 0 <= score <= 10 or item.get('confidence') not in CONFIDENCE:
            raise ValueError(key + ': give a score from 0 to 10 and a valid confidence')
        evidence = item.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(key + ': paper judgment needs quoted transcript evidence')
        clean = []
        for observation in evidence:
            if not isinstance(observation, dict):
                raise ValueError(key + ': invalid paper evidence')
            start = observation.get('t')
            end = observation.get('end', start)
            valid = finite_number(start) and finite_number(end) and 0 <= start < result['duration_estimate_s']
            if not valid or not start <= end <= result['duration_estimate_s']:
                raise ValueError(key + ': paper evidence time is outside the estimated cut')
            quote = observation.get('quote')
            note = observation.get('note')
            if not isinstance(note, str) or not note.strip() or not isinstance(quote, str):
                raise ValueError(key + ': paper evidence needs a quote and an observation')
            if not validate_quote(quote, start, end, words):
                raise ValueError(key + ': quote does not match words in the cited interval')
            clean.append({'t': float(start), 'end': float(end), 'kind': 'transcript', 'ref': 'paper.md',
                          'quote': quote, 'note': note.strip()})
        confidence = 'low' if not independent or provenance['same_family_as_cut_maker'] is None else (
            min(item['confidence'], 'medium', key=CONFIDENCE.index))
        validated.append((key, {'score': score, 'basis': 'judged', 'confidence': confidence,
                                 'judged_by': judge.strip(), 'independent': independent, 'evidence': clean,
                                 'judge_provenance': provenance,
                                 'fix': validate_fix(item.get('fix'), result['lines']), 'at': P.now()}))
    rows = {row['id']: row for row in result['dimensions']}
    for key, rating in validated:
        rows[key].setdefault('assessments', []).append(rating)
        choose_assessment(rows[key])


def paper_identity(settings, entries, lines, brief):
    """Hash the compiled edit and its direction without physical line numbers or reader notes."""
    numbers = {row['line']: index for index, row in enumerate(entries) if 'line' in row}

    def normalized(value, key=None):
        if isinstance(value, dict):
            return {name: normalized(item, name) for name, item in value.items()
                    if name not in ('placed', 'parent_line', 'tight_cuts', 'unmeasured_cuts', 'unmeasured_why')}
        if isinstance(value, (list, tuple)):
            return [normalized(item, key) for item in value]
        if key == 'line' and type(value) is int:
            return numbers.get(value, value)
        if key == 'over' and type(value) is int:
            return numbers.get(value, value)
        return value

    identity_settings = dict(settings)
    if 'caption_breaks' in identity_settings:
        identity_settings['caption_breaks'] = [{'word': row['word']} for row in identity_settings['caption_breaks']]
    identity = {'version': 2, 'settings': normalized(identity_settings), 'entries': normalized(entries),
                'lines': normalized(lines), 'brief': brief}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def paper_has_judgments(paper):
    """Whether a saved paper result contains at least one recorded assessment."""
    return isinstance(paper, dict) and any(row.get('assessments') for row in paper.get('dimensions', [])
                                           if isinstance(row, dict))


def archive_paper(folder, paper):
    """Keep each distinct recorded result without replacing an earlier judgment."""
    if not paper_has_judgments(paper):
        return
    content = json.dumps(paper, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    name = hashlib.sha256(content).hexdigest() + '.json'
    path = folder / 'paper-history' / name
    if not path.exists():
        P.save_json(path, paper)


def restore_paper(result, previous):
    """Carry matching judgments forward and remap fix line references after note insertion."""
    old_lines = previous.get('lines') or []
    new_lines = result.get('lines') or []
    numbers = {old.get('line'): new.get('line') for old, new in zip(old_lines, new_lines)}
    rows = {row.get('id'): row for row in previous.get('dimensions', []) if isinstance(row, dict)}
    for row in result['dimensions']:
        assessments = json.loads(json.dumps((rows.get(row['id']) or {}).get('assessments', [])))
        for assessment in assessments:
            fix = assessment.get('fix')
            if isinstance(fix, dict) and fix.get('line') in numbers:
                fix['line'] = numbers[fix['line']]
        row['assessments'] = assessments
        choose_assessment(row)


def matching_paper_history(folder, identity):
    """Find the most recently archived result for this exact compiled edit."""
    history = folder / 'paper-history'
    if not history.is_dir():
        return None
    paths = sorted(history.glob('*.json'), key=lambda path: path.stat().st_mtime_ns, reverse=True)
    for path in paths:
        try:
            previous = P.load_json(path, None)
        except (OSError, ValueError):
            continue
        if isinstance(previous, dict) and previous.get('paper_id') == identity:
            return previous
    return None


def stale_paper_history(folder, identity):
    """Check whether a recorded assessment belongs to a different compiled edit."""
    history = folder / 'paper-history'
    if not history.is_dir():
        return False
    for path in history.glob('*.json'):
        try:
            saved = P.load_json(path, None)
        except (OSError, ValueError):
            continue
        if paper_has_judgments(saved) and saved.get('paper_id') != identity:
            return True
    return False


def legacy_paper_matches(previous, current, folder, cutter, root, brief, source_map):
    """Migrate a legacy assessment only when its original edit, brief and old rubric can all be verified."""
    if not paper_has_judgments(previous) or previous.get('paper_identity_version') is not None:
        return False
    try:
        original_id = {'film': previous['film_md_sha256'], 'settings': previous['settings'],
                       'lines': previous['lines'], 'problems': previous['problems'],
                       'brief': brief, 'rubric': LEGACY_PAPER_RUBRIC}
        encoded = json.dumps(original_id, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if hashlib.sha256(encoded).hexdigest() != previous.get('paper_id'):
            return False
        paper = P.read_text(folder / 'paper.md')
        prefix = '## The paper edit\n\nEvery line, picture, title and note as written in film.md:\n\n```markdown\n'
        suffix = '\n```\n\n## Sections\n'
        if prefix not in paper or suffix not in paper:
            return False
        old_text = paper.split(prefix, 1)[1].rsplit(suffix, 1)[0]
        verified = False
        for ending in ('', '\n', '\n\n', '\r\n', '\r\n\r\n'):
            value = old_text + ending
            encodings = (value.encode('utf-8'), value.encode('utf-8-sig'), value.encode('utf-16'),
                         b'\xfe\xff' + value.encode('utf-16-be'))
            if any(hashlib.sha256(raw).hexdigest() == previous['film_md_sha256'] for raw in encodings):
                verified = True
                break
        if not verified:
            return False
        problems = cutter.Problems()
        _, old_entries = cutter.parse_film(old_text, problems, set(source_map.sources), root)
        identity = paper_identity(previous['settings'], old_entries, previous['lines'], brief)
        return identity == current['paper_id']
    except (OSError, ValueError, TypeError, KeyError):
        return False


def paper_grade(target, judged=None):
    """Compile the paper edit without rendering, retaining compiler errors and estimated timing."""
    root = P.find_project(target)
    if root is None:
        raise ValueError('no project folder at or above ' + str(target))
    P.refuse_overwriting_inputs([root / 'grade' / 'paper.json', root / 'grade' / 'paper.md'], [judged])
    cutter = sibling('cut')
    text, settings, entries_found, plan, problems, source_map = cutter.analyse(root, measure=False)
    # The paper review skips the audio by design, so every cut would read "not measured"; cut.py check measures
    # them, and the limitations below say so once.
    problems.items = [problem for problem in problems.items
                      if 'pauses were not measured' not in problem.get('message', '')]
    del text
    lines = plan.get('lines', [])
    words = timed_words(lines, [])
    duration = float(plan.get('duration') or 0)
    summary = timeline_facts(lines, words, [], duration, {}) if duration > 0 else {}
    grades = [{'id': key, 'score': None, 'status': 'waiting', 'assessments': [],
               'reason': 'A reviewer must judge the paper edit against its stated direction '
                         '(audience, takeaway, story) and the brief.'}
              for key in ('hook', 'structure', 'pacing', 'cta')]
    safe_settings = dict(settings)
    if safe_settings.get('fps') is not None:
        safe_settings['fps'] = str(safe_settings['fps'])
    if isinstance(safe_settings.get('captions'), set):
        safe_settings['captions'] = sorted(safe_settings['captions'])
    result = {'version': 1, 'film_md_sha256': digest(root / 'film.md'), 'duration_estimate_s': duration,
              'settings': safe_settings, 'dimensions': grades, 'timeline': summary, 'lines': lines,
              'problems': problems.items, 'validation': {'state': 'unvalidated', 'reason': VALIDATION_NOTE},
              'limitations': ['No picture or sound rendered; durations use transcript boundaries, not measured pauses.',
                              'Section names are labels, not proof of structure or payoff.']}
    out = root / 'grade'
    fields, brief = brief_fields(root / 'brief.md')
    result['paper_id'] = paper_identity(safe_settings, entries_found, lines, brief)
    result['paper_identity_version'] = 2
    result['brief_fields'] = fields
    previous = P.load_json(out / 'paper.json', None)
    match = previous if isinstance(previous, dict) and previous.get('paper_id') == result['paper_id'] else None
    if match is None and legacy_paper_matches(previous, result, out, cutter, root, brief, source_map):
        match = previous
    mismatch = paper_has_judgments(previous) and previous.get('paper_id') != result['paper_id'] and match is None
    if match is None:
        match = matching_paper_history(out, result['paper_id'])
    if match:
        restore_paper(result, match)
    if judged:
        merge_paper(result, P.load_json(judged, None), words)
    if mismatch:
        archive_paper(out, previous)
    template = out / ('paper-judged-template-' + result['paper_id'][:16] + '.json')
    if not template.exists():
        P.save_json(template, {'version': 1, 'paper_id': result['paper_id'], 'judge': '',
                               'independent': False, 'judge_provenance': {'model_family': '', 'model': '',
                                                                          'same_family_as_cut_maker': None},
                               'dimensions': []})
    P.save_json(out / 'paper.json', result)
    direction = [f"- {label}: {settings.get(key) or 'not stated'}" for key, label in
                 (('story', 'Story'), ('audience', 'Audience'), ('takeaway', 'Takeaway'))]
    parts = ['# Paper edit review', '', '## Direction (judge the edit against this)', ''] + direction + [
             '', f'Estimated duration: {duration:.2f} s (before measured audio cuts).',
             '', 'No picture or sound has been rendered. Word times are estimates, and cut points are placed '
             'from transcript times here: cut.py check measures them in the audio.', VALIDATION_NOTE,
             '', '## Scores', '']
    for row in result['dimensions']:
        parts.append(f"- {row['id']}: {row['score']}/10 ({row['basis']}, {row['confidence']})"
                     if row['score'] is not None else f"- {row['id']}: waiting for evidence")
        for item in row.get('evidence', []):
            parts.append(f"  - {item['t']:.2f}-{item['end']:.2f}s: {item['quote']} - {item['note']}")
    parts.extend(['', '## The paper edit', '', 'Every line, picture, title and note as written in film.md:', '',
                  '```markdown', P.read_text(root / 'film.md').rstrip(), '```'])
    parts.extend(['', '## Sections', ''])
    for section in summary.get('sections', []):
        line_numbers = ', '.join(str(number) for number in section['lines'] if number is not None)
        parts.append(f"- {section['name']}: {section['start']:.2f}-{section['end']:.2f} s; "
                     f'film.md lines {line_numbers}')
    parts.extend(['', '## Timed words', '', transcript_text(words), '', '## Compiler findings', ''])
    for problem in problems.items:
        parts.append(f"- film.md:{problem['line']}: {problem['severity']}: {problem['message']}")
    if not problems.items:
        parts.append('- None reported by the paper-edit compiler.')
    P.write_atomic(out / 'paper.md', '\n'.join(parts) + '\n')
    print(f'paper review: {out / "paper.md"}')
    print(f'Reviewer template: {template}')
    if mismatch or stale_paper_history(out, result['paper_id']):
        print('Some recorded reviews no longer match the current edit; preserved in grade/paper-history/.')
    count = sum(row['score'] is not None for row in result['dimensions'])
    print(f'{count}/4 script dimensions scored; the paper edit has not been rendered.')
    return 1 if count < len(grades) else 0


def sentence_groups(words):
    """Split mapped words at explicit sentence punctuation; never claim unpunctuated fragments are sentences."""
    groups = []
    current = []
    for index, word in enumerate(words):
        current.append((index, word))
        if re.search(r'[.!?][\"\')\]]*$', word['text']):
            groups.append((current, True))
            current = []
        elif len(current) >= 60:
            groups.append((current, False))
            current = []
    if current:
        groups.append((current, False))
    return groups


def quiet_between(audio, start, end):
    """Return the longest mapped quiet interval between word edges, or unknown without an audio map."""
    if not isinstance(audio, dict) or not isinstance(audio.get('silences'), list):
        return None
    overlaps = []
    for interval in audio['silences']:
        try:
            left = max(start, float(interval['start']))
            right = min(end, float(interval['end']))
        except (KeyError, ValueError, TypeError):
            continue
        overlaps.append(max(0.0, right - left))
    return round(max(overlaps, default=0.0), 3)


def source_hash_state(root, source):
    """Tell a reader when the mapped transcript's source no longer matches its registered hash."""
    expected = source.get('sha256')
    source_path = source.get('path')
    if not expected or not source_path:
        return 'unknown: no registered source hash or path'
    source_path = Path(source_path)
    if not source_path.is_absolute():
        source_path = root / source_path
    if not source_path.is_file():
        return 'unknown: source is unavailable'
    return 'matched' if digest(source_path) == expected else 'mismatch: remap before using these candidates'


def hooks(target, alias, show_all=False):
    """Find structurally complete opening candidates and show how their boundaries were measured."""
    root = P.find_project(target)
    if root is None:
        raise ValueError('no project folder at or above ' + str(target))
    index = P.load_json(root / 'map' / 'sources.json', {})
    sources = index.get('sources', []) if isinstance(index, dict) else []
    if alias and not any(source.get('alias') == alias for source in sources):
        raise ValueError('unknown alias: ' + alias)
    candidates = []
    skipped = []
    for source in sources:
        name = source.get('alias')
        if not name or (alias and name != alias):
            continue
        transcript = P.load_json(root / 'map' / name / 'words.json', None)
        if not isinstance(transcript, dict) or not isinstance(transcript.get('words'), list):
            skipped.append({'alias': name, 'reason': 'no mapped words'})
            continue
        words = timed_words([], transcript['words'])
        audio = P.load_json(root / 'map' / name / 'audio.json', None)
        source_state = source_hash_state(root, source)
        for group, complete in sentence_groups(words):
            first_index, first = group[0]
            last_index, last = group[-1]
            if not complete or len(group) < 3:
                continue
            before = words[first_index - 1]['end'] if first_index else 0.0
            after = words[last_index + 1]['start'] if last_index + 1 < len(words) else float(
                source.get('duration_s') or last['end'])
            text = ' '.join(word['text'] for _, word in group)
            if text.rstrip().endswith('?'):
                reason = 'Complete punctuated question; review whether it promises something relevant.'
            else:
                reason = 'Complete punctuated statement; review whether it stands alone and makes a useful promise.'
            length = round(last['end'] - first['start'], 3)
            quiet_after = quiet_between(audio, last['end'], after)
            first_token = re.sub(r'[^a-z]', '', str(first['text']).lower())
            standalone = first_token not in {'and', 'but', 'so', 'because', 'then', 'it', 'this', 'that',
                                             'they', 'he', 'she', 'these', 'those'}
            short = length <= 8 and len(group) <= 20
            clean_pause = quiet_after is not None and quiet_after >= .12
            why = [('short' if short else 'longer'), ('no obvious dependent opening' if standalone
                                                      else 'may depend on the previous sentence'),
                   ('mapped quiet after' if clean_pause else 'no measured quiet after' if quiet_after is not None
                    else 'quiet after not measured')]
            candidates.append({'alias': name, 'start': first['start'], 'end': last['end'],
                               'spoken_length_s': length, 'text': text,
                               'word_gap_before_s': round(max(0.0, first['start'] - before), 3),
                               'word_gap_after_s': round(max(0.0, after - last['end']), 3),
                               'quiet_before_s': quiet_between(audio, before, first['start']),
                               'quiet_after_s': quiet_after,
                               'rank_factors': {'short': short, 'standalone_heuristic': standalone,
                                                'mapped_quiet_after': clean_pause},
                               'reason': '; '.join(why) + '. ' + reason, 'source_hash': source_state,
                               'transcript_draft': transcript.get('draft', True)})
    def ranking(row):
        factors = row['rank_factors']
        return (-sum(factors.values()), -int(factors['standalone_heuristic']), -int(factors['short']),
                -int(factors['mapped_quiet_after']), row['spoken_length_s'], row['alias'], row['start'])
    candidates.sort(key=ranking)
    count = len(candidates)
    if not show_all:
        candidates = candidates[:5]
    result = {'version': 1, 'candidates': candidates, 'total_candidates': count, 'show_all': show_all,
              'skipped': skipped,
              'limits': ['Ranking is a structural heuristic, not a judgment of story or predicted retention.',
                         'A pronoun or conjunction is only a cue; self-containment needs a reader.',
                         'Word gaps are not silence. Mapped quiet intervals use map.py thresholds and need listening.',
                         'A quiet interval does not by itself prove the edit will sound clean.']}
    out = root / 'grade'
    P.save_json(out / 'hooks.json', result)
    report = ['# Candidate openings', '', *result['limits'], '']
    for row in candidates:
        report.extend([f"## {row['alias']} {row['start']:.2f}-{row['end']:.2f}", '', row['text'], '',
                       f"Spoken: {row['spoken_length_s']:.2f}s. Word gaps before/after: "
                       f"{row['word_gap_before_s']:.2f}s / {row['word_gap_after_s']:.2f}s. "
                       f"Mapped quiet before/after: {row['quiet_before_s']}s / {row['quiet_after_s']}s.",
                       row['reason'],
                       f"Source: {row['source_hash']}; transcript draft: {row['transcript_draft']}.", ''])
    if not candidates:
        report.append('No complete punctuated candidate found; inspect the transcript and import punctuation '
                      'if needed.')
    P.write_atomic(out / 'hooks.md', '\n'.join(report) + '\n')
    print(f'{len(candidates)} of {count} ranked structural candidates: {out / "hooks.md"}'
          + ('' if show_all or count <= 5 else ' (use --all to show every candidate)'))
    for rank, row in enumerate(candidates, 1):
        print(f"{rank}. {row['alias']} {row['start']:.2f}-{row['end']:.2f}s: {row['text']}")
        print('   ' + row['reason'])
    return 1


def thumbs(target, version):
    """Suggest inspectable frame candidates for either a version or an external video."""
    path = Path(target).resolve()
    if path.is_file() and path.suffix.lower() != '.md':
        video = path
        out = card_paths(path, None, True)[2]
    else:
        _, _, cut = project_cut(target, version)
        video = cut / 'preview.mp4'
        out = cut / 'grade'
    facts = probe(video)
    media_hash = digest(video)
    frames, _, faces, _, _, _, _, _ = cached_measurements(video, facts, media_hash, out)
    result = write_thumbs(frames, out, media_hash, facts['duration_s'], faces)
    print(f"{len(result['candidates'])} cover candidates: {out / 'thumbs.jpg'}")
    return 1


def review_read_json(path, missing):
    """Read optional evidence without disguising a missing or unreadable artifact."""
    try:
        data = P.load_json(path, None)
    except (OSError, ValueError) as error:
        missing.append(f'{path.name} is unreadable: {error}')
        return None
    if data is None:
        missing.append(f'{path.name} is missing')
    return data


def review_rows(data, key):
    """Return a named list from a compiled artifact, or an empty list."""
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict) and isinstance(data.get(key), list):
        return [row for row in data[key] if isinstance(row, dict)]
    return []


def review_number(value, default=None):
    """Accept only finite numeric timeline values."""
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


def review_picture(edit):
    """Place the actual edit's picture clips on the film clock, including overlap and speed."""
    result = []
    for item in review_rows(edit, 'picture'):
        start = review_number(item.get('in'))
        end = review_number(item.get('out'))
        speed = review_number(item.get('speed', 1))
        if start is None or end is None or not speed or speed < 0 or end <= start:
            continue
        join = item.get('join') if isinstance(item.get('join'), dict) else {}
        overlap = review_number(join.get('dur'), 0) if join.get('kind', 'cut') != 'cut' else 0
        previous = result[-1] if result else None
        at = previous['at'] + previous['length'] - max(0, overlap) if previous else 0
        result.append({'source': str(item.get('src') or 'unknown'), 'in': start, 'out': end,
                       'at': at, 'length': (end - start) / speed, 'speed': speed,
                       'join': str(join.get('kind', 'cut')), 'overlap': max(0, overlap)})
    return result


def review_speech(edit, lines):
    """Use rendered dialogue intervals, with compiled spoken runs as a fallback."""
    items = [item for item in review_rows(edit, 'audio') if item.get('track') == 'dialogue']
    if not items:
        for line in lines:
            if line.get('kind') != 'spoken':
                continue
            runs = line.get('runs') or []
            if not runs and isinstance(line.get('range'), list) and len(line['range']) == 2:
                runs = [{'in': line['range'][0], 'out': line['range'][1], 'at': line.get('start')}]
            items.extend(dict(run, src=line.get('source')) for run in runs if isinstance(run, dict))
    result = []
    for item in items:
        start = review_number(item.get('in'))
        end = review_number(item.get('out'))
        at = review_number(item.get('at'))
        speed = review_number(item.get('speed', 1))
        if start is None or end is None or at is None or not speed or speed < 0 or end <= start:
            continue
        result.append({'source': str(item.get('src') or 'unknown'), 'in': start, 'out': end,
                       'at': at, 'length': (end - start) / speed, 'speed': speed})
    return sorted(result, key=lambda row: row['at'])


def review_picture_at(picture, at, before=False):
    """Find the underlying shot on one side of an edit-time boundary."""
    time = at - 1e-6 if before else at + 1e-6
    matches = [clip for clip in picture if clip['at'] <= time < clip['at'] + clip['length']]
    return matches[-1] if matches else None


def review_shot_maps(root, picture, missing):
    """Read optional current source scene maps, which are candidates rather than proof of picture cuts."""
    data = review_read_json(root / 'map' / 'sources.json', missing)
    known = {str(row.get('alias')) for row in review_rows(data, 'sources') if row.get('alias')}
    aliases = sorted({clip['source'] for clip in picture if clip['source'] in known})
    maps = {}
    for alias in aliases:
        if not re.fullmatch(r'[A-Za-z0-9_]+', alias):
            missing.append(f'{alias}: invalid source alias; scene map unavailable')
            continue
        path = root / 'map' / alias / 'shots.json'
        if not path.is_file():
            missing.append(f'map/{alias}/shots.json is missing; source scene changes are not mapped')
            continue
        try:
            data = P.load_json(path)
        except (OSError, ValueError) as error:
            missing.append(f'map/{alias}/shots.json is unreadable: {error}')
            continue
        if not isinstance(data, dict) or not isinstance(data.get('shots'), list):
            missing.append(f'map/{alias}/shots.json has no readable shot list')
            continue
        if data.get('source') not in (None, alias):
            missing.append(f'map/{alias}/shots.json names a different source; scene candidates were not used')
            continue
        times = [review_number(shot.get('start')) for shot in data['shots'] if isinstance(shot, dict)]
        maps[alias] = sorted(set(time for time in times if time is not None and time > 0))
        if data.get('sampled'):
            missing.append(f'map/{alias}/shots.json is sampled; source scene changes may be absent')
    return maps


def review_split_picture(picture, shot_maps):
    """Split source ranges at mapped scene candidates to describe the shots on each side."""
    segments = []
    candidates = []
    for clip in picture:
        boundaries = [clip['in']]
        boundaries.extend(time for time in shot_maps.get(clip['source'], [])
                          if clip['in'] + 0.001 < time < clip['out'] - 0.001)
        boundaries.append(clip['out'])
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
            at = clip['at'] + (start - clip['in']) / clip['speed']
            segment = dict(clip, **{'in': start, 'out': end, 'at': at,
                                    'length': (end - start) / clip['speed']})
            segments.append(segment)
            if index:
                candidates.append((at, clip['source'], start))
    return segments, candidates


def review_events(edit, lines, duration, shot_maps=None):
    """Collect timeline joins and labelled source-map candidates without conflating picture and speech."""
    clips = review_picture(edit)
    picture, candidates = review_split_picture(clips, shot_maps or {})
    speech = review_speech(edit, lines)
    events = []
    for left, right in zip(clips, clips[1:]):
        at = right['at']
        events.append({'at': at, 'kind': 'picture', 'before': review_picture_at(picture, at, True) or left,
                       'after': review_picture_at(picture, at) or right,
                       'detail': right['join']})
    for at, alias, source_time in candidates:
        events.append({'at': at, 'kind': 'picture', 'before': review_picture_at(picture, at, True),
                       'after': review_picture_at(picture, at),
                       'detail': f'mapped scene-change candidate: {alias} {P.format_time(source_time)} (unverified)'})
    for overlay in review_rows(edit, 'overlays'):
        if overlay.get('kind') not in ('image', 'video'):
            continue
        for key, action in (('from', 'appears'), ('to', 'ends')):
            at = review_number(overlay.get(key))
            if at is not None and 0 < at < duration:
                events.append({'at': at, 'kind': 'picture', 'before': review_picture_at(picture, at, True),
                               'after': review_picture_at(picture, at),
                               'detail': f"overlay {overlay.get('src', 'unknown')} {action}"})
    for left, right in zip(speech, speech[1:]):
        gap = right['at'] - (left['at'] + left['length'])
        discontinuous = left['source'] != right['source'] or abs(right['in'] - left['out']) > 0.001
        if discontinuous or abs(gap) > 0.001:
            detail = 'source change' if left['source'] != right['source'] else 'skip or pause in source'
            events.append({'at': right['at'], 'kind': 'speech', 'before': left, 'after': right,
                           'detail': detail})
    return sorted((event for event in events if 0 < event['at'] < duration), key=lambda row: row['at']), picture


def review_groups(events):
    """Merge successive joins less than 0.4 seconds apart, retaining every original time."""
    groups = []
    for event in events:
        if groups and event['at'] - groups[-1][-1]['at'] < 0.4 - 1e-9:
            groups[-1].append(event)
        else:
            groups.append([event])
    return groups


def review_side(clip, at, before):
    """Name a source, its source time, and the corresponding shot or passage length."""
    if clip is None:
        return 'none or unavailable'
    position = min(clip['out'], max(clip['in'], clip['in'] + (at - clip['at']) * clip['speed']))
    return f"{clip['source']} {P.format_time(position)} (length {clip['length']:.2f} s)"


def review_join_text(groups, picture, missing):
    """Describe every join and both sides, including all members of merged rows."""
    output = ['Timeline joins and unverified source-map scene-change candidates; '
              'shot lengths include any transition overlap.', '']
    if not groups:
        output.append('No joins were found in the available timeline.')
    for number, group in enumerate(groups, 1):
        times = ', '.join(P.format_time(event['at']) for event in group)
        kinds = sorted({event['kind'] for event in group})
        output.append(f'Row {number}: {times} ({" and ".join(kinds)})')
        for event in group:
            at = event['at']
            output.append(f"  {P.format_time(at)} {event['kind']}: {event['detail']}")
            output.append('    before: ' + review_side(event['before'], at, True))
            output.append('    after:  ' + review_side(event['after'], at, False))
            if event['kind'] == 'speech':
                output.append('    picture before: ' + review_side(review_picture_at(picture, at, True), at, True))
                output.append('    picture after:  ' + review_side(review_picture_at(picture, at), at, False))
        output.append('')
    if missing:
        output.extend(['Missing timeline evidence:', *['- ' + item for item in missing], ''])
    return '\n'.join(output) + '\n'


def review_word_line(spoken, time, word):
    """Find the spoken line covering a word, using its alias to disambiguate overlapping lines."""
    candidates = []
    for index, line in enumerate(spoken):
        start = review_number(line.get('start'), 0)
        end = review_number(line.get('end'), start)
        if start <= time < end:
            candidates.append(index)
    word_id = str(word.get('id') or '')
    preferred = [index for index in candidates if word_id.startswith(str(spoken[index].get('source')) + '-w')]
    return (preferred or candidates or [None])[0]


def review_cue_line(spoken, start, end):
    """Place an untimed-word cue by overlap and flag source attribution across multiple lines."""
    matches = []
    for index, line in enumerate(spoken):
        a = review_number(line.get('start'), 0)
        b = review_number(line.get('end'), a)
        overlap = min(end, b) - max(start, a)
        if overlap > 0:
            matches.append((overlap, index))
    if not matches:
        return None, False
    return max(matches, key=lambda row: row[0])[1], len(matches) > 1


def review_line_header(line):
    """Name the paper-edit range and the actual kept source runs for a spoken line."""
    start = review_number(line.get('start'), 0)
    end = review_number(line.get('end'), start)
    span = line.get('range')
    source_range = 'source range unavailable'
    if isinstance(span, (tuple, list)) and len(span) == 2:
        a = review_number(span[0])
        b = review_number(span[1])
        if a is not None and b is not None and min(a, b) >= 0:
            source_range = f'source {P.format_time(a)}-{P.format_time(b)}'
    header = [f"[{P.format_time(max(0, start))}-{P.format_time(max(0, end))}] "
              f"{line.get('source', 'source unavailable')} | {source_range}"]
    runs = []
    for run in line.get('runs') or []:
        if not isinstance(run, dict):
            continue
        a = review_number(run.get('in'))
        b = review_number(run.get('out'))
        at = review_number(run.get('at'))
        if a is not None and b is not None and at is not None and min(a, b, at) >= 0:
            runs.append(f'{P.format_time(a)}-{P.format_time(b)} at film {P.format_time(at)}')
    if runs:
        header.append('  Rendered source runs: ' + '; '.join(runs))
    return header


def review_transcript(lines, captions, missing):
    """List timed speech in film order, including words with no matched line and source context."""
    spoken = sorted((line for line in lines if line.get('kind') == 'spoken'),
                    key=lambda row: review_number(row.get('start'), 0))
    cues = review_rows(captions, 'cues') or review_rows(captions, 'words')
    output = ["Transcript on the film clock. Source ranges refer to the version's paper edit.", '']
    fragments = []
    assigned = set()
    for cue in cues:
        cue_start = review_number(cue.get('start'))
        cue_end = review_number(cue.get('end'))
        if cue_start is None or cue_end is None:
            continue
        words = [word for word in (cue.get('words') or []) if isinstance(word, dict)]
        if not words:
            text = str(cue.get('text', cue.get('word', ''))).strip().replace('\n', ' ')
            if text:
                index, uncertain = review_cue_line(spoken, cue_start, cue_end)
                if uncertain:
                    text += ' (cue spans multiple source lines; attribution estimated)'
                fragments.append({'at': cue_start, 'start': cue_start, 'end': cue_end, 'line': index, 'text': text})
                if index is not None:
                    assigned.add(index)
            continue
        current = None
        for word in sorted(words, key=lambda item: review_number(item.get('start'), cue_start)):
            text = str(word.get('text', word.get('word', ''))).strip()
            if not text:
                continue
            at = review_number(word.get('start'), cue_start)
            index = review_word_line(spoken, at, word)
            if current is None or current['line'] != index:
                current = {'at': at, 'start': cue_start, 'end': cue_end, 'line': index, 'text': text}
                fragments.append(current)
            else:
                current['text'] += ' ' + text
            if index is not None:
                assigned.add(index)
    for index, line in enumerate(spoken):
        if index in assigned:
            continue
        words = [word for word in (line.get('words') or []) if isinstance(word, dict)]
        start = review_number(line.get('start'), 0)
        end = review_number(line.get('end'), start)
        if words:
            a = review_number(words[0].get('start'), start)
            b = review_number(words[-1].get('end'), end)
            text = ' '.join(str(word.get('text', '')).strip() for word in words) + ' (kept words)'
        else:
            a, b = start, end
            text = 'No caption or kept words available for this line.'
        fragments.append({'at': a, 'start': a, 'end': b, 'line': index, 'text': text})
    last_line = object()
    for fragment in sorted(fragments, key=lambda row: row['at']):
        index = fragment['line']
        if index != last_line:
            if output[-1]:
                output.append('')
            if index is None:
                output.append('Source line and range unavailable:')
            else:
                output.extend(review_line_header(spoken[index]))
            last_line = index
        start = P.format_time(max(0, fragment['start']))
        end = P.format_time(max(0, fragment['end']))
        output.append(f"  [{start}-{end}] {fragment['text']}")
    if not spoken and not cues:
        output.append('No speech or timed transcript is available in the version.')
    if missing:
        output.extend(['', 'Missing transcript evidence:', *['- ' + item for item in missing]])
    return '\n'.join(output).rstrip() + '\n'


def review_cut_check(root, film):
    """Run cut.py check on the immutable version text while retaining the project's real map and paths."""
    if not film.is_file():
        return 'cut.py check not run: the version film.md is missing.\n'
    runner = (
        'import importlib.util,sys; from pathlib import Path; '
        's=importlib.util.spec_from_file_location("lf_review_cut",sys.argv[1]); '
        'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
        'read=m.project.read_text; target=(Path(sys.argv[2])/"film.md").resolve(); '
        'version=Path(sys.argv[3]); '
        'm.project.read_text=lambda p: read(version if Path(p).resolve()==target else p); '
        'sys.argv=[sys.argv[1],"check",sys.argv[2]]; sys.exit(m.main())'
    )
    result = subprocess.run([sys.executable, '-I', '-c', runner, str(HERE / 'cut.py'), str(root), str(film)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    selected = []
    keep = False
    for line in (result.stdout + result.stderr).splitlines():
        if re.match(r'^film\.md:\d+: (warning|error): ', line):
            selected.append(line)
            keep = True
        elif keep and line.startswith('  '):
            selected.append(line)
        else:
            keep = False
    if result.returncode == 2:
        selected.extend(line for line in result.stderr.splitlines() if line not in selected)
    if not selected:
        selected.append('No warnings or errors reported.' if result.returncode == 0 else 'No details reported.')
    heading = (f'cut.py check on the version film.md (exit {result.returncode}); it recompiles the edit, '
               'so its times may differ from the rendered version:\n')
    return heading + '\n'.join(selected) + '\n'


def review_checks(checks, root, film, missing):
    """Keep every non-pass check and the verbatim warnings from the version's paper edit."""
    output = ['Non-pass items from checks.json:']
    items = review_rows(checks, 'items')
    found = [item for item in items if item.get('state') != 'pass']
    if not found:
        output.append('None reported.' if isinstance(checks, dict) else 'Unavailable.')
    for item in found:
        at = review_number(item.get('at'))
        time = P.format_time(at) if at is not None and at >= 0 else 'time unavailable'
        output.append(f"[{time}] {item.get('state', 'state unavailable')} | "
                      f"{item.get('id', 'unknown')} | {item.get('label', '')} | {item.get('detail', '')}")
        extras = {key: value for key, value in item.items() if key not in ('at', 'state', 'id', 'label', 'detail')}
        if extras:
            output.append('  ' + json.dumps(extras, ensure_ascii=False))
    output.extend(['', review_cut_check(root, film).rstrip()])
    if missing:
        output.extend(['', 'Missing checks evidence:', *['- ' + item for item in missing]])
    return '\n'.join(output) + '\n'


def review_direction(film):
    """The direction the editor intended, for direction.md: kept out of the brief so the reviewer's first impression
    is a viewer's, not the editor's (a reviewer reading one file met the intended story before the film)."""
    direction = {}
    film_text = P.read_text(film) if film.is_file() else ''
    if film.is_file():
        cut = sibling('cut')
        direction, _ = cut.parse_film(film_text, cut.Problems())
    output = ['# The direction the editor intended', '',
              'Read only after writing your first impression in notes/first-impression.md.', '']
    for key in ('audience', 'takeaway', 'story'):
        fallback = 'not in front matter; see version film.md below' if film_text else 'version film.md unavailable'
        output.append(f'{key}: {direction.get(key) or fallback}')
    if film_text and any(not direction.get(key) for key in ('audience', 'takeaway', 'story')):
        output.extend(['', '## Version film.md: direction may also appear in prose or notes', '', film_text.rstrip()])
    return '\n'.join(output) + '\n'


def review_brief(root, film, lines):
    """Copy the editor brief and list the source transcripts; the direction is in direction.md."""
    template = HERE.parent / 'assets' / 'templates' / 'cut-review-brief.md'
    text = (P.read_text(template).rstrip() if template.is_file()
            else 'Missing template: assets/templates/cut-review-brief.md')
    output = [text, '', 'The direction the editor intended is in `direction.md`: open it only after writing your first '
              'impression.']
    sources = review_read_json(root / 'map' / 'sources.json', [])
    aliases = {str(row.get('alias')) for row in review_rows(sources, 'sources') if row.get('alias')}
    aliases.update(str(line['source']) for line in lines if line.get('source'))
    output.extend(['', 'Source transcripts:'])
    for alias in sorted(aliases):
        if not re.fullmatch(r'[A-Za-z0-9_]+', alias):
            output.append(f'- {alias}: invalid alias; transcript path unavailable')
            continue
        path = root / 'map' / alias / 'transcript.md'
        output.append(f'- {path}' + ('' if path.is_file() else ' (missing)'))
    if not aliases:
        output.append('- No source aliases available.')
    return '\n'.join(output) + '\n'


def review_sheet(video, out, arguments):
    """Ask frame_sheet.py to decode and label the requested instants."""
    result = subprocess.run([sys.executable, '-I', str(HERE / 'frame_sheet.py'), str(video), '--out', str(out),
                             '--width', '240', *arguments], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError('frame_sheet.py failed: ' + (result.stderr or result.stdout).strip()[-1000:])


def review_placeholder(path, message):
    """Make a clear sheet placeholder when there is no picture or no join."""
    image = Image.new('RGB', (960, 100), (28, 28, 30))
    ImageDraw.Draw(image).text((20, 30), message, fill='white', font=font(20))
    image.save(path)


def review_frame_time(name):
    """The decoded time in a frame_sheet frame's file name, or None. Inexact times are written with a leading ~
    (frame-tile-001-at-~2.268933s.png); reading only exact ones dropped most frames of a 29.97 fps film, and each
    join row then showed the nearest frame it had, which a reviewer saw as stale frames."""
    match = re.search(r'-at-~?(-?\d+(?:\.\d+)?)s\.png$', name)
    return float(match.group(1)) if match else None


def review_sample_times(group):
    """Sample a merged row at ten per second, covering half a second around every member."""
    first = group[0]['at'] - 0.5
    last = group[-1]['at'] + 0.5
    count = int(math.ceil((last - first) * 10 - 1e-7))
    return [max(0.0, first + number / 10) for number in range(count + 1)]


def review_row_title(group, number, draw, typeface, width):
    """Wrap every join time into the row heading, identifying map-only candidates."""
    pieces = []
    for item in group:
        kind = 'mapped candidate' if item['detail'].startswith('mapped scene-change candidate') else item['kind']
        pieces.append(f"{P.format_time(item['at'])} {kind}")
    result = []
    line = f'Row {number}: '
    for piece in pieces:
        addition = (', ' if not line.endswith(': ') else '') + piece
        if draw.textlength(line + addition, font=typeface) > width and not line.endswith(': '):
            result.append(line)
            line = piece
        else:
            line += addition
    result.append(line)
    return result


def review_join_sheets(video, packet, groups):
    """Use frame_sheet's individual decoded frames to preserve one independently labelled row per join."""
    if not groups:
        review_placeholder(packet / 'joins.png', 'No timeline joins found.')
        return
    page = 0
    for start in range(0, len(groups), 6):
        batch = groups[start:start + 6]
        samples = [review_sample_times(group) for group in batch]
        times = sorted(set(round(t, 6) for row in samples for t in row))
        if len(times) > 600:
            raise ValueError('a join page needs more than 600 frames; too many closely spaced joins')
        with tempfile.TemporaryDirectory(prefix='.join-frames-', dir=str(packet)) as temporary:
            scratch = Path(temporary)
            review_sheet(video, scratch / 'frame.png', ['--at', ','.join(f'{t:.6f}' for t in times), '--single'])
            extracted = []
            for path in scratch.iterdir():
                stamp = review_frame_time(path.name)
                if stamp is not None:
                    extracted.append((stamp, path))
            extracted.sort()
            if not extracted:
                raise ValueError('frame_sheet.py wrote no join frames')
            clock = [item[0] for item in extracted]
            with Image.open(extracted[0][1]) as first:
                tile_width, tile_height = first.size
            pad, label = 6, 20
            width = pad + max(len(row) for row in samples) * (tile_width + pad)
            measure = ImageDraw.Draw(Image.new('RGB', (1, 1)))
            typeface = font(18)
            titles = [review_row_title(group, start + number + 1, measure, typeface, width - 2 * pad)
                      for number, group in enumerate(batch)]
            heading = 26 * max(len(lines) for lines in titles)
            row_height = heading + label + tile_height + pad
            image = Image.new('RGB', (width, pad + len(batch) * row_height), (28, 28, 30))
            draw = ImageDraw.Draw(image)
            for row_number, wanted in enumerate(samples):
                y = pad + row_number * row_height
                for title_number, title in enumerate(titles[row_number]):
                    draw.text((pad, y + title_number * 26), title, font=typeface, fill='white')
                for column, requested in enumerate(wanted):
                    index = min(max(bisect.bisect_right(clock, requested + 0.0005) - 1, 0), len(clock) - 1)
                    actual, path = extracted[index]
                    x = pad + column * (tile_width + pad)
                    draw.text((x, y + heading), f'{actual:.3f}s', font=font(14), fill='white')
                    with Image.open(path) as tile:
                        image.paste(tile, (x, y + heading + label))
            page += 1
            name = 'joins.png' if page == 1 else f'joins-{page}.png'
            image.save(packet / name)


def review_images(video, packet, duration, groups, missing):
    """Write overview, opening, ending and join sheets, or explicit picture placeholders."""
    if not video.is_file():
        for name in ('overview.png', 'opening.png', 'ending.png', 'joins.png'):
            review_placeholder(packet / name, 'Picture unavailable: preview.mp4 is missing.')
        return
    try:
        facts = probe(video)
    except (ValueError, json.JSONDecodeError) as error:
        missing.append(f'picture unavailable: {error}')
        for name in ('overview.png', 'opening.png', 'ending.png', 'joins.png'):
            review_placeholder(packet / name, 'Picture unavailable; see README.txt.')
        return
    duration = facts['duration_s']
    if duration <= 600:
        review_sheet(video, packet / 'overview.png', ['--every', '1'])
    else:
        for number, start in enumerate(range(0, math.ceil(duration), 64), 1):
            times = range(start, min(start + 64, math.ceil(duration)))
            name = 'overview.png' if number == 1 else f'overview-{number}.png'
            review_sheet(video, packet / name, ['--at', ','.join(str(t) for t in times)])
    opening = [min(duration, number / 10) for number in range(30)]
    ending = [max(0, duration - 3 + number / 10) for number in range(30)]
    for name, values in (('opening.png', opening), ('ending.png', ending)):
        review_sheet(video, packet / name, ['--at', ','.join(f'{value:.6f}' for value in values)])
    review_join_sheets(video, packet, groups)


def review_captions(cut, captions, missing):
    """Fall back to the version's timed SRT or VTT when word-timed caption JSON is unavailable or empty."""
    if review_rows(captions, 'cues') or review_rows(captions, 'words'):
        return captions
    for name in ('captions.srt', 'captions.vtt'):
        path = cut / name
        if not path.is_file():
            continue
        try:
            cues = sibling('captions').read_input(str(path))
        except (OSError, ValueError) as error:
            missing.append(f'{name} is unreadable or empty: {error}')
            continue
        if cues:
            return {'cues': cues}
    return captions


def review_packet(target, version):
    """Build a replacement editor packet without changing the rendered version or grading it."""
    root = P.find_project(target)
    if root is None:
        raise ValueError('no project folder at or above ' + str(target))
    chosen = version or P.current_version(root)
    if not chosen or not P.VERSION_NAME.fullmatch(chosen) or not (root / 'cuts' / chosen).is_dir():
        raise ValueError('no such rendered version: ' + str(chosen))
    cut = root / 'cuts' / chosen
    missing = []
    lines_data = review_read_json(cut / 'lines.json', missing)
    edit = review_read_json(cut / 'edit.json', missing)
    captions = review_read_json(cut / 'captions.json', missing)
    captions = review_captions(cut, captions, missing)
    checks = review_read_json(cut / 'checks.json', missing)
    manifest = review_read_json(cut / 'manifest.json', missing)
    lines = review_rows(lines_data, 'lines')
    if isinstance(edit, dict) and isinstance(edit.get('picture'), list) and not edit['picture']:
        missing.append('edit.json contains no picture clips')
    duration = review_number((manifest or {}).get('duration_s')) if isinstance(manifest, dict) else None
    if isinstance(lines_data, dict):
        timeline_duration = review_number(lines_data.get('duration_s'))
        if timeline_duration and timeline_duration > 0:
            duration = min(duration, timeline_duration) if duration and duration > 0 else timeline_duration
    video = cut / 'preview.mp4'
    if not video.is_file():
        missing.append('preview.mp4 is missing; film.mp4 and decoded pictures are unavailable')
    else:
        try:
            actual_duration = probe(video)['duration_s']
            duration = min(duration, actual_duration) if duration and duration > 0 else actual_duration
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    duration = duration or max([review_number(line.get('end'), 0) for line in lines] + [0])
    shot_maps = review_shot_maps(root, review_picture(edit), missing)
    events, picture = review_events(edit, lines, duration, shot_maps)
    groups = review_groups(events)
    with P.file_lock(cut / 'review'):
        staging = Path(tempfile.mkdtemp(prefix='.review-', dir=str(cut)))
        backup = None
        try:
            if video.is_file():
                shutil.copy2(video, staging / 'film.mp4')
            review_images(video, staging, duration, groups, missing)
            P.write_atomic(staging / 'transcript.txt', review_transcript(lines, captions, missing))
            P.write_atomic(staging / 'joins.txt', review_join_text(groups, picture, missing))
            P.write_atomic(staging / 'checks.txt', review_checks(checks, root, cut / 'film.md', missing))
            P.write_atomic(staging / 'brief.md', review_brief(root, cut / 'film.md', lines))
            P.write_atomic(staging / 'direction.md', review_direction(cut / 'film.md'))
            readme = ('film.mp4 is the version preview; overview.png and numbered pages sample the film once per '
                      'second; opening.png and ending.png sample the first and last three seconds; joins.png and '
                      'numbered pages show one labelled row per merged timeline join; transcript.txt gives timed '
                      'speech and source context; joins.txt describes both sides and shot lengths; checks.txt '
                      'contains non-pass checks and paper-edit warnings; brief.md holds the review brief and the '
                      'source transcript paths; direction.md holds the editor\'s intended direction, to read only '
                      'after writing a first impression. Sheets '
                      'cannot show motion between sampled frames, rhythm, or sound: play the film and listen. '
                      'Scene-change candidates come from current source maps and may be stale or incomplete; '
                      'they are not proof that every visible cut has been found. '
                      'A decoded frame may be repeated for several sample times. Missing evidence: '
                      + ('; '.join(missing) if missing else 'none detected') + '.\n')
            P.write_atomic(staging / 'README.txt', readme)
            destination = cut / 'review'
            if destination.exists():
                backup = Path(tempfile.mkdtemp(prefix='.review-old-', dir=str(cut)))
                backup.rmdir()
                os.replace(destination, backup)
            try:
                os.replace(staging, destination)
            except OSError:
                if backup is not None:
                    os.replace(backup, destination)
                    backup = None
                raise
            if backup is not None:
                shutil.rmtree(backup)
            print(destination)
            return 0
        finally:
            if staging.exists():
                shutil.rmtree(staging)


def record_cold(checks_path, video, assessment, project=None):
    """Record a named independent assessment against the exact file assessed."""
    if not isinstance(assessment, dict) or assessment.get('state') not in ('matched', 'mismatched'):
        raise ValueError('cold assessment state must be matched or mismatched')
    who = assessment.get('by')
    answer = assessment.get('answer')
    if not isinstance(who, str) or not who.strip() or not isinstance(answer, dict):
        raise ValueError('cold assessment needs the reader and three answers')
    if any(not isinstance(answer.get(key), str) or not answer[key].strip() for key in ('what', 'audience', 'why')):
        raise ValueError('cold assessment needs what, audience and why answers')
    actual = digest(video)
    if assessment.get('file_sha256') != actual:
        raise ValueError('cold assessment does not name the current file hash')
    checks = P.load_json(checks_path, {})
    if not isinstance(checks, dict):
        raise ValueError('checks.json must contain an object')
    checks['cold_read'] = {'state': assessment['state'], 'by': who.strip(), 'answer': answer,
                           'file_sha256': actual, 'method': assessment.get('method', 'cold packet'),
                           'label': 'assessed by ' + who.strip()}
    P.refuse_overwriting_inputs([checks_path], [video], project=project, guard_versions=True)
    P.save_json(checks_path, checks)
    return checks['cold_read']


def cold_packet(target, file_arg, version, seconds, words_arg, do_record, assessment_path):
    """Build a brief-free opening packet and optionally record a supplied assessment."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('--seconds must be a positive finite number')
    if bool(target) == bool(file_arg):
        raise ValueError('use grade.py cold PROJECT or grade.py cold --file FILE')
    if file_arg:
        video = Path(file_arg).resolve()
        root, cut = None, None
        packet_base = video.parent / (video.stem + '.grade') / 'cold'
        checks_path = packet_base / 'checks.json'
    else:
        root, chosen, cut = project_cut(target, version)
        video = cut / 'preview.mp4'
        packet_base = root / 'grade' / 'cold' / chosen
        checks_path = cut / 'checks.json'
    if not video.is_file():
        raise ValueError('cold read file does not exist')
    facts = probe(video)
    duration = min(seconds, facts['duration_s'])
    file_hash = digest(video)
    inputs = [video] + ([words_arg] if words_arg else [])
    if cut:
        inputs += [cut / 'captions.json', cut / 'captions.srt']
    if do_record and assessment_path:
        inputs.append(assessment_path)
    outputs = [packet_base / '.cold-packet'] + ([checks_path] if do_record else [])
    P.refuse_overwriting_inputs(outputs, inputs, project=root, guard_versions=True)
    packet_base.mkdir(parents=True, exist_ok=True)
    packet = Path(tempfile.mkdtemp(prefix='packet-', dir=str(packet_base)))
    outputs = [packet / name for name in ('frames.png', 'words.txt', 'prompt.txt', 'packet.json')]
    P.refuse_overwriting_inputs(outputs, inputs, project=root, guard_versions=True)
    times = [round(i * .5, 3) for i in range(math.ceil(duration * 2)) if i * .5 < duration]
    review_sheet(video, packet / 'frames.png', ['--at', ','.join(map(str, times)), '--cols', '5'])
    if digest(video) != file_hash:
        raise ValueError('the file changed while the cold packet was built')
    if words_arg:
        words, _ = imported_transcript(words_arg, duration)
    elif cut:
        words = timed_words([], caption_words(cut) or read_cues(cut))
    else:
        words = []
    lines = [f"{row['start']:.2f}s {row['text']}" for row in words if row['start'] < duration]
    P.write_atomic(packet / 'words.txt', '\n'.join(lines) + ('\n' if lines else 'No supplied words.\n'))
    P.write_atomic(packet / 'prompt.txt', 'Read the frames and words without a brief. Answer:\n'
                   '1. What is this?\n2. For whom is it?\n3. Why should they care?\n'
                   'A sampled packet cannot show motion or sound.\n')
    P.save_json(packet / 'packet.json', {'file_sha256': file_hash, 'seconds': duration,
                                         'sample_interval_s': .5, 'words_available': bool(lines)})
    print(f'Cold packet: {packet}')
    print('Ask a fresh reader what this is, for whom, and why they should care.')
    print(f'File SHA-256: {file_hash}')
    if do_record:
        if assessment_path:
            assessment = P.load_json(assessment_path, None)
        elif not sys.stdin.isatty():
            assessment = json.load(sys.stdin)
        else:
            by = input('Reader or model: ').strip()
            answer = {key: input(prompt).strip() for key, prompt in
                      (('what', 'What is this? '), ('audience', 'For whom? '), ('why', 'Why care? '))}
            assessment = {'by': by, 'answer': answer, 'state': input('Matched or mismatched? ').strip(),
                          'file_sha256': file_hash}
        result = record_cold(checks_path, video, assessment, project=root)
        print(f"{result['state']} ({result['label']})")
    return 0


def subcommand_help(command, argv):
    """Show precise usage and output files for the three reviewer-facing subcommands."""
    descriptions = {
        'paper': ('Compile the paper edit without rendering. Writes grade/paper.json, grade/paper.md, '
                  'a judged template, and preserves earlier judgments in grade/paper-history/.'),
        'hooks': ('Rank structural opening candidates. Writes grade/hooks.json and grade/hooks.md; '
                  'the ranking is not a prediction of audience response.'),
        'review': ('Build an independent reviewer packet in cuts/vNNN/review/; it does not score the cut.'),
    }
    parser = argparse.ArgumentParser(prog='grade.py ' + command, description=descriptions[command],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project', help='project folder')
    if command == 'paper':
        parser.add_argument('--judged', help='filled reviewer JSON for this paper_id')
        parser.epilog = ('Judged JSON shape:\\n'
                         '  {"version": 1, "paper_id": "...", "judge": "name", "independent": true,\\n'
                         '   "judge_provenance": {"model_family": "...", "model": "...",\\n'
                         '                        "same_family_as_cut_maker": false},\\n'
                         '   "dimensions": [{"id": "hook", "score": 6, "confidence": "medium",\\n'
                         '     "evidence": [{"t": 0.1, "end": 1.0, "quote": "words", "note": "..."}],\\n'
                         '     "fix": {"text": "...", "line": 12, "gain": 1}}]}\\n'
                         'Dimensions: hook, structure, pacing, cta. Confidence: low, medium, high. '
                         'Fix is optional; times are estimated film seconds.')
    if command == 'hooks':
        parser.add_argument('--alias', help='limit to one mapped source')
        parser.add_argument('--all', action='store_true', help='show all candidates, not only the top five')
    if command == 'review':
        parser.add_argument('--version', help='rendered version (default: current)')
    parser.parse_args(argv)


def main(argv=None):
    """Dispatch project, file and subcommand forms without conflating an error with an unscored result."""
    P.safe_output()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ('paper', 'hooks', 'review') and any(arg in ('-h', '--help') for arg in argv[1:]):
        subcommand_help(argv[0], argv[1:])
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('target', nargs='?', help='project, or merge/scores/paper/hooks/thumbs/review subcommand')
    parser.add_argument('extra', nargs='*')
    parser.add_argument('--file', help='standalone video file')
    parser.add_argument('--version', help='rendered version (default: current)')
    parser.add_argument('--platform', help='declared destination')
    parser.add_argument('--kind', help='kind of video')
    parser.add_argument('--brief', help='brief Markdown')
    parser.add_argument('--alias', help='mapped source for hooks')
    parser.add_argument('--judged', help='paper reviewer submission')
    parser.add_argument('--all', action='store_true', help='with hooks: show all ranked candidates')
    parser.add_argument('--words', help="with --file: an existing transcript (word JSON, SRT or WebVTT) on the "
                                        "file's clock")
    parser.add_argument('--no-transcribe', action='store_true',
                        help='with --file: do not transcribe the audio locally when no --words is given')
    parser.add_argument('--seconds', type=float, default=5.0, help='opening duration for cold read')
    parser.add_argument('--record', action='store_true', help='record a supplied cold-read assessment')
    parser.add_argument('--assessment', help='cold-read assessment JSON with answers, reader, state and file hash')
    args = parser.parse_args(argv)
    try:
        if args.target == 'cold':
            if len(args.extra) > 1 or (args.extra and args.file) or (args.assessment and not args.record):
                raise ValueError('use grade.py cold PROJECT or --file FILE [--seconds N] [--record]')
            return cold_packet(args.extra[0] if args.extra else None, args.file, args.version, args.seconds,
                               args.words, args.record, args.assessment)
        if args.record or args.assessment or args.seconds != 5.0:
            raise ValueError('--record, --assessment and --seconds are for grade.py cold')
        if args.all and args.target != 'hooks':
            raise ValueError('--all is for grade.py hooks PROJECT')
        if args.judged and args.target != 'paper':
            raise ValueError('--judged is for grade.py paper PROJECT')
        if (args.words or args.no_transcribe) and not args.file:
            raise ValueError('--words and --no-transcribe are for grade.py --file FILE')
        if args.target == 'review':
            if len(args.extra) != 1 or args.file:
                raise ValueError('use grade.py review PROJECT [--version vNNN]')
            return review_packet(args.extra[0], args.version)
        if args.target == 'merge':
            if args.file:
                if len(args.extra) != 1 or args.version:
                    raise ValueError('use grade.py merge judged.json --file FILE')
                return merge_judgment(None, None, args.extra[0], args.file)
            if len(args.extra) != 2:
                raise ValueError('use grade.py merge PROJECT judged.json')
            return merge_judgment(args.extra[0], args.version, args.extra[1])
        if args.target == 'scores':
            if len(args.extra) != 1 or args.file:
                raise ValueError('use grade.py scores PROJECT [--version vNNN]')
            return refresh_person_scores(args.extra[0], args.version)
        if args.target in ('paper', 'hooks', 'thumbs'):
            if len(args.extra) != 1 or args.file:
                raise ValueError(f'use grade.py {args.target} PROJECT')
            if args.target == 'paper':
                return paper_grade(args.extra[0], args.judged)
            if args.target == 'hooks':
                return hooks(args.extra[0], args.alias, args.all)
            return thumbs(args.extra[0], args.version)
        if args.extra or (args.file and args.target):
            raise ValueError('give one project or --file FILE')
        return grade_video(args.target, args.version, args.file, args.platform, args.kind, args.brief,
                           args.words, not args.no_transcribe)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, json.JSONDecodeError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
