"""Known-answer cases for several recordings of one conversation: line-up, the paper edit over it, and speaker labels.

The speech is real: the words of the first-cut example (Tears of Steel, CC BY), each cut out on its transcript's word
times and shuffled into longer conversations whose two speakers are known, then laid into per-person mics and cameras
with known offsets, gains, room noise, sample rates and drift. The word order is new but the waveforms repeat, which is
harder on the line-up than real speech. These prove the arithmetic and the refusals on known answers, not how a real
room sounds: a mic's bleed here is the other voice turned down and low-passed, and nobody talks over anyone unless a
case says so. Without the example they print a SKIP line.
"""
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE = 48000
SPEAKERS = {'Celia': [(0, 4), (25, 38), (61, 65)], 'Thom': [(4, 25), (38, 61)]}
FRONT = ('---\ntitle: Two people\naudience: a test\ntakeaway: they line up\nstory: one talk, many recordings\n'
         'size: {size}\nfps: {fps}\ncaptions: {captions}\n---\n')


def load(scripts_dir, name, folder=None):
    """Load one of the skill's scripts (or a case module) as a module."""
    path = Path(scripts_dir) / (folder or '.') / f'{name}.py'
    spec = importlib.util.spec_from_file_location(f'speakers_{name}', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def example(scripts_dir):
    """(clip, transcript words) of the first-cut example, or None where it is not installed."""
    folder = Path(scripts_dir).parents[2] / 'examples' / 'first-cut'
    clip, words = folder / 'tears-of-steel-bridge.mp4', folder / 'tears-of-steel-bridge.words.json'
    return (clip, json.loads(words.read_text(encoding='utf-8'))['words']) if clip.is_file() and words.is_file() else None


def clip_samples(clip):
    """The example's sound, mono at RATE."""
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(clip), '-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype='<f4').astype(np.float64)


def conversation(samples, words, seed, seconds, overlap=0):
    """Real words in a new order, as two voices on one clock: ({speaker: samples}, words with times and true speakers).
    Each turn is a run of one speaker's words; `overlap` turns (one in every N) start before the last one has ended."""
    rng = np.random.default_rng(seed)
    pools = {name: [index for low, high in spans for index in range(low, high)] for name, spans in SPEAKERS.items()}
    length = int((seconds + 2) * RATE)
    voices = {name: np.zeros(length) for name in SPEAKERS}
    rows = []
    cursor = 0.3
    name = 'Celia'
    turn = 0
    while cursor < seconds:
        turn += 1
        count = int(rng.integers(3, 12))
        spoken = int(rng.integers(0, len(pools[name])))
        if overlap and turn % overlap == 0 and rows:
            cursor = max(0.3, cursor - 0.5)
        for step in range(count):
            word = words[pools[name][(spoken + step) % len(pools[name])]]
            low, high = int(word['start'] * RATE), int(word['end'] * RATE)
            piece = samples[low:high].copy()
            fade = min(len(piece) // 4, int(0.005 * RATE))
            if fade:
                ramp = np.linspace(0, 1, fade)
                piece[:fade] *= ramp
                piece[-fade:] *= ramp[::-1]
            first = int(cursor * RATE)
            if first + len(piece) >= length:
                break
            voices[name][first:first + len(piece)] += piece
            rows.append({'text': word['text'], 'start': round(cursor, 4),
                         'end': round(cursor + len(piece) / RATE, 4), 'true': name})
            cursor += len(piece) / RATE + float(rng.uniform(0.02, 0.09))
        cursor += float(rng.uniform(0.25, 0.8))
        name = 'Thom' if name == 'Celia' else 'Celia'
    return voices, sorted(rows, key=lambda row: row['start'])


def low_pass(samples, hz):
    """A gentle low-pass: how another person's voice reaches a close mic, roughly."""
    width = max(1, int(RATE / hz))
    return np.convolve(samples, np.ones(width) / width, mode='same')


def write_wav(path, samples, rate=RATE):
    """16-bit mono WAV, resampled through FFmpeg when `rate` is not RATE."""
    data = (np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes()
    if rate == RATE:
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            stream.writeframes(data)
        return
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 's16le', '-ar', str(RATE), '-ac', '1', '-i', 'pipe:0',
                    '-ar', str(rate), str(path)], input=data, check=True)


def mic(voices, own, seed, gain_db=0.0, bleed_db=-20.0, noise_db=-58.0):
    """One person's close mic: their voice, the other's voice turned down and duller, and room noise."""
    rng = np.random.default_rng(seed)
    own_voice = voices[own]
    other = sum(voice for name, voice in voices.items() if name != own)
    mixed = own_voice + 10 ** (bleed_db / 20) * low_pass(other, 2500)
    return 10 ** (gain_db / 20) * mixed + 10 ** (noise_db / 20) * rng.standard_normal(len(mixed))


def camera(voices, seed, gain_db=-8.0, noise_db=-48.0):
    """A camera's microphone: both voices, duller and with more room."""
    rng = np.random.default_rng(seed)
    mixed = low_pass(sum(voices.values()), 5000)
    return 10 ** (gain_db / 20) * mixed + 10 ** (noise_db / 20) * rng.standard_normal(len(mixed))


def late(samples, seconds):
    """A recording that starts `seconds` into the conversation."""
    return samples[int(seconds * RATE):]


def early(samples, seconds, seed=9):
    """A recording that started `seconds` before the conversation's clock: room noise first."""
    rng = np.random.default_rng(seed)
    return np.concatenate([10 ** (-60 / 20) * rng.standard_normal(int(seconds * RATE)), samples])


def drifted(samples, parts_per_million):
    """A recorder whose clock runs fast by this much: every sound lands later and later on its own clock."""
    count = int(len(samples) * (1 + parts_per_million / 1e6))
    return np.interp(np.arange(count) / (1 + parts_per_million / 1e6), np.arange(len(samples)), samples)


def new_project(tool, root, files):
    """A project with its files registered as (role, path) in order; returns {path name: alias}."""
    root = Path(root)
    shutil.rmtree(root, ignore_errors=True)
    tool('project.py', 'init', root)
    aliases = {}
    for role, path in files:
        code, output = tool('map.py', 'add', root, path, '--role', role)
        if code:
            raise RuntimeError(output)
        aliases[Path(path).name] = output.split()[-1]
    code, output = tool('map.py', 'run', root, '--words', 'skip')
    if code not in (0, 1):
        raise RuntimeError(output)
    return aliases


def saved(root):
    """The project's saved line-up."""
    return json.loads((Path(root) / 'map' / 'sync.json').read_text(encoding='utf-8'))


def write_words(root, alias, rows):
    """A word-timed transcript for a source, bound to its file as map.py binds one."""
    sources = json.loads((Path(root) / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources']
    source = next(row for row in sources if row['alias'] == alias)
    words = [{'id': f'{alias}-w{number + 1:06d}', 'text': row['text'], 'start': row['start'], 'end': row['end'],
              'speaker': row.get('speaker'), 'estimated': False} for number, row in enumerate(rows)]
    folder = Path(root) / 'map' / alias
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'words.json').write_text(json.dumps({
        'version': 1, 'source': alias, 'engine': 'fixture', 'language': 'en', 'draft': False,
        'audio_stream': source['audio']['index'],
        'media': {'sha256': source['sha256'], 'bytes': source['bytes'], 'audio_stream': source['audio']['index']},
        'words': words}), encoding='utf-8')


# ----------------------------------------------------------------------------------------------- line-up

def check_lineup(tool, record, j, scripts_dir, speech):
    """Offsets, confidence, drift, refusals and the binding to each file, on real speech with known answers."""
    samples, words = speech
    work = Path(j('speakers-sync'))
    work.mkdir(parents=True, exist_ok=True)
    voices, _ = conversation(samples, words, 11, 150)
    other_voices, _ = conversation(samples, words, 47, 150)
    files = {'cam.wav': camera(voices, 1),
             'mic_late.wav': late(mic(voices, 'Celia', 2, gain_db=-9, noise_db=-52), 7.25),
             'mic_early.wav': early(mic(voices, 'Thom', 3, gain_db=4), 3.5),
             'cam_late.wav': late(camera(voices, 4, gain_db=-14, noise_db=-44), 41.0),
             'drift.wav': drifted(mic(voices, 'Thom', 5), 500.0),
             'other.wav': mic(other_voices, 'Celia', 6)}
    for name, data in files.items():
        write_wav(work / name, data, 44100 if name == 'mic_late.wav' else 22050 if name == 'cam_late.wav' else RATE)
    # A repeating sound fits many offsets: a tone that loops, and a recording with no sound at all.
    tone = 0.2 * np.sin(2 * np.pi * 440 * np.arange(60 * RATE) / RATE) * (np.arange(60 * RATE) % RATE < RATE // 2)
    write_wav(work / 'loop.wav', tone)
    write_wav(work / 'silent.wav', np.zeros(30 * RATE))
    root = work / 'project'
    aliases = new_project(tool, root, [('camera', work / 'cam.wav'), ('mic', work / 'mic_late.wav'),
                                       ('mic', work / 'mic_early.wav'), ('camera', work / 'cam_late.wav'),
                                       ('mic', work / 'drift.wav'), ('other', work / 'other.wav'),
                                       ('other', work / 'loop.wav'), ('other', work / 'silent.wav')])
    code, output = tool('map.py', 'sync', root, '--reference', aliases['cam.wav'])
    record('speakers: map.py sync exits 1 and prints a look when something cannot be lined up',
           code == 1 and 'look' in output, f'exit {code}: {output[-400:]}')
    data = saved(root)
    rows = data['sources']
    def error_ms(name, truth):
        row = rows[aliases[name]]
        return abs(row['offset_s'] - truth) * 1000 if 'offset_s' in row else float('inf')
    late_error = error_ms('mic_late.wav', 7.25)
    record('speakers: a mic that starts late, at another rate and level, under room noise lines up within 2 ms',
           late_error <= 2 and rows[aliases['mic_late.wav']]['state'] == 'lined-up'
           and rows[aliases['mic_late.wav']]['confidence'] >= 0.6, f'{late_error:.2f} ms: {rows[aliases["mic_late.wav"]]}')
    early_error = error_ms('mic_early.wav', -3.5)
    record('speakers: a mic that started before the reference gets a negative offset within 2 ms', early_error <= 2,
           f'{early_error:.2f} ms: {rows[aliases["mic_early.wav"]].get("offset_s")}')
    camera_error = error_ms('cam_late.wav', 41.0)
    record('speakers: a noisy second camera at another rate lines up within 3 ms', camera_error <= 3,
           f'{camera_error:.2f} ms')
    drift = rows[aliases['drift.wav']]
    record('speakers: a clock 500 parts per million fast is measured as drift across the overlap',
           drift.get('state') == 'lined-up' and abs(abs(drift.get('drift_s') or 0) - 0.076) < 0.01, str(drift))
    record('speakers: drift over one frame is printed, not hidden', 'DRIFT' in output and aliases['drift.wav'] in output,
           output[-400:])
    from_end = load(scripts_dir, 'lineup').Lineup(root).map_time(aliases['cam.wav'], aliases['drift.wav'], 140.0)
    record('speakers: a drifting source maps to its right place late in the recording',
           abs(from_end - 140.0 * (1 + 500e-6)) < 0.004, f'{from_end:.4f} s')
    record('speakers: a recording of another conversation is a look and is not applied',
           rows[aliases['other.wav']]['state'] == 'look' and rows[aliases['other.wav']].get('reason'),
           str(rows[aliases['other.wav']]))
    record('speakers: a looping tone is a look with its reason', rows[aliases['loop.wav']]['state'] == 'look',
           str(rows[aliases['loop.wav']]))
    record('speakers: a silent recording is a look with its reason', rows[aliases['silent.wav']]['state'] == 'look',
           str(rows[aliases['silent.wav']]))
    cam = aliases['cam.wav']
    mic_alias = aliases['mic_late.wav']
    sources = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources']
    hashes = {row['alias']: row['sha256'] for row in sources}
    record('speakers: each saved row is bound to its file by SHA-256',
           all(rows[alias]['sha256'] == hashes[alias] for alias in rows) and data['reference_sha256'] == hashes[cam])
    lineup = load(scripts_dir, 'lineup')
    record('speakers: a current row can be used', lineup.Lineup(root).problem(mic_alias) == '',
           lineup.Lineup(root).problem(mic_alias))
    # The same size and a new time: the reader hashes and finds it the same; new bytes make it stale.
    media = work / 'mic_late.wav'
    original = media.read_bytes()
    media.write_bytes(original)
    record('speakers: a file rewritten with the same bytes stays current', lineup.Lineup(root).problem(mic_alias) == '')
    changed = bytearray(original)
    changed[len(changed) // 2] ^= 0xFF
    media.write_bytes(bytes(changed))
    reason = lineup.Lineup(root).problem(mic_alias)
    record('speakers: a changed source makes its row stale, at the same size', 'changed' in reason, reason)
    code, report = tool('map.py', 'sync', root, '--check')
    record('speakers: map.py sync --check names the stale row and exits 1', code == 1 and 'stale' in report,
           report[-300:])
    media.write_bytes(original)
    reference = work / 'cam.wav'
    original = reference.read_bytes()
    changed = bytearray(original)
    changed[len(changed) // 2] ^= 0xFF
    reference.write_bytes(bytes(changed))
    reason = lineup.Lineup(root).problem(mic_alias)
    record('speakers: a changed reference makes every row stale', 'changed' in reason and cam in reason, reason)
    reference.write_bytes(original)
    look = aliases['other.wav']
    reason = lineup.Lineup(root).problem(look)
    record('speakers: a look is refused with its reason', 'look' in reason, reason)
    code, report = tool('map.py', 'sync', root, '--set', f'{look}=1.5')
    record('speakers: an offset set by hand needs a note', code == 2 and 'note' in report, report[-200:])
    code, report = tool('map.py', 'sync', root, '--set', f'{look}=1.5', '--note', 'listened to the clap at 0:10')
    decisions = (root / 'decisions.jsonl').read_text(encoding='utf-8') if (root / 'decisions.jsonl').is_file() else ''
    row = saved(root)['sources'][look]
    record('speakers: a person can set an offset after listening, and it is recorded as theirs',
           code == 0 and row['state'] == 'set-by-hand' and lineup.Lineup(root).problem(look) == ''
           and 'clap' in decisions and row['offset_s'] == 1.5, report[-200:])


# ----------------------------------------------------------------------------------------------- the paper edit

def counted_camera(speed, scripts_dir, path, seconds, rate, audio_wav):
    """A camera file: a frame counter in its picture, this sound in its sound."""
    speed.counted_source(scripts_dir, path, seconds=seconds, rate=rate, audio=['-i', str(audio_wav)])


def correlate_at(first, second, reach):
    """The lag, in samples, at which `second` best matches `first`, searched within +-reach."""
    size = min(len(first), len(second))
    first, second = first[:size] - first[:size].mean(), second[:size] - second[:size].mean()
    count = 1 << int(np.ceil(np.log2(size * 2)))
    corr = np.fft.irfft(np.fft.rfft(second, count) * np.conj(np.fft.rfft(first, count)), count)
    window = np.concatenate([corr[-reach:], corr[:reach + 1]])
    return int(np.argmax(window)) - reach


def decoded(path, stream=None):
    """A file's sound, mono at RATE."""
    command = ['ffmpeg', '-v', 'error', '-i', str(path)]
    command += ['-map', f'0:{stream}'] if stream is not None else []
    raw = subprocess.run(command + ['-ac', '1', '-ar', str(RATE), '-f', 'f32le', '-'], capture_output=True,
                         check=True).stdout
    return np.frombuffer(raw, dtype='<f4').astype(np.float64)


def check_paper_edit(tool, record, j, scripts_dir, speech):
    """Grammar and refusals with line numbers, then a real render: picture exact at the offset through both picture
    paths, sound from a lined-up mic, cuts in the pauses of the sound used, captions and the hand-off."""
    samples, words = speech
    speed = load(scripts_dir, 'speed', 'selftest_cases')
    work = Path(j('speakers-edit'))
    work.mkdir(parents=True, exist_ok=True)
    voices, rows = conversation(samples, words, 21, 16)
    seconds, rate = 15, 30
    camera_a = camera(voices, 1)
    camera_b = late(camera(voices, 2, gain_db=-12, noise_db=-46), 1.2)
    write_wav(work / 'cam_a.wav', camera_a[:int(seconds * RATE)])
    write_wav(work / 'cam_b.wav', camera_b[:int((seconds - 1.2) * RATE)])
    write_wav(work / 'mic_a.wav', late(mic(voices, 'Celia', 3, gain_db=2), 0.5), 44100)
    write_wav(work / 'mic_b.wav', mic(voices, 'Thom', 4, gain_db=-3))
    counted_camera(speed, scripts_dir, work / 'cam_a.mp4', seconds, rate, work / 'cam_a.wav')
    counted_camera(speed, scripts_dir, work / 'cam_b.mp4', seconds - 1.2, rate, work / 'cam_b.wav')
    root = work / 'project'
    new_project(tool, root, [('camera', work / 'cam_a.mp4'), ('camera', work / 'cam_b.mp4'), ('mic', work / 'mic_a.wav'),
                             ('mic', work / 'mic_b.wav')])
    rows = [row for row in rows if row['end'] < seconds - 0.5]
    write_words(root, 'cam_01', rows)
    def film(body, size='320x180', captions='none', fps=rate):
        (root / 'film.md').write_text(FRONT.format(size=size, fps=fps, captions=captions) + body, encoding='utf-8')
    def problems():
        code, output = tool('cut.py', 'check', root, '--json')
        try:
            return code, json.loads(output[output.index('{'):])['problems']
        except ValueError:
            return code, [{'severity': 'error', 'line': 0, 'message': output[-300:]}]
    def message(found, text):
        return next((item for item in found if text in item['message']), None)
    pick = [row for row in rows if 2.0 < row['start'] < 11][:14]
    # A spoken line over the first words after the second camera and the mic have started.
    start, end = pick[0]['start'] - 0.1, pick[-1]['end'] + 0.1
    text = ' '.join(row['text'] for row in pick)
    line = f'> cam_01 {start:.2f}-{end:.2f} {text}'
    film(f'{line}\n  ~ cam_02 sync Reaction\n')
    code, found = problems()
    record('speakers: a synced cutaway without a line-up is an error on its line, naming the fix',
           code == 1 and any(item['severity'] == 'error' and item['line'] == 11 and 'sync' in item['suggestion']
                             for item in found), str(found)[-400:])
    code, output = tool('cut.py', 'render', root)
    record('speakers: a render without the line-up is blocked (exit 2)', code == 2, f'exit {code}: {output[-200:]}')
    film(f'{line} {{sound mic_01}}\n')
    code, found = problems()
    record('speakers: sound from a mic without a line-up is an error on its line',
           code == 1 and any(item['severity'] == 'error' and item['line'] == 10 for item in found), str(found)[-300:])
    code, output = tool('map.py', 'sync', root, '--reference', 'cam_01')
    data = saved(root)['sources']
    record('speakers: the cameras and mics of the render fixture line up',
           code == 0 and all(data[name]['state'] == 'lined-up' for name in ('cam_02', 'mic_01', 'mic_02')),
           output[-500:])
    truth = {'cam_02': 1.2, 'mic_01': 0.5, 'mic_02': 0.0}
    err = {name: abs(data[name].get('offset_s', 99) - value) * 1000 for name, value in truth.items()}
    record('speakers: those offsets are right within 3 ms on 15 s of speech', max(err.values()) <= 3, str(err))
    # Grammar: every refusal names its line.
    cases = [('~ cam_02 sync x1.5 Reaction', 'speed', 11),
             ('~ cam_02 sync sound Reaction', 'sound', 11),
             ('~ cam_09 sync Reaction', 'unknown source alias cam_09', 11),
             ('~ mic_01 sync Reaction', 'has no picture', 11)]
    for over, wanted, number in cases:
        film(f'{line}\n  {over}\n')
        code, found = problems()
        hit = message(found, wanted)
        record(f'speakers: "{over}" is refused on its line', code == 1 and hit is not None and hit['line'] == number
               and hit['severity'] == 'error', str(found)[-300:])
    film(f'- pause 1.0\n  ~ cam_02 sync\n{line}\n')
    code, found = problems()
    hit = message(found, 'sync')
    record('speakers: a synced cutaway needs a line with a source clock above it',
           code == 1 and hit is not None and hit['line'] == 11, str(found)[-300:])
    film('- cam_02 sync Reaction\n')
    code, found = problems()
    hit = message(found, 'sync')
    record('speakers: sync on a picture line is refused and says where it goes', code == 1 and hit is not None
           and hit['line'] == 10 and '~' in hit['suggestion'], str(found)[-300:])
    film(f'{line} {{sound mic_09}}\n')
    code, found = problems()
    record('speakers: sound from an unknown source is refused on its line',
           code == 1 and message(found, 'mic_09') is not None, str(found)[-300:])
    early_rows = [row for row in rows if row['end'] < 1.0]
    if early_rows:
        early_text = ' '.join(row['text'] for row in early_rows)
        film(f'> cam_01 0.10-{early_rows[-1]["end"] + 0.05:.2f} {early_text}\n  ~ cam_02 sync\n')
        code, found = problems()
        hit = message(found, 'no picture')
        record('speakers: a camera that had not started yet is refused, saying what it covers',
               code == 1 and hit is not None and hit['line'] == 11, str(found)[-300:])
        film(f'> cam_01 0.10-{early_rows[-1]["end"] + 0.05:.2f} {early_text} {{sound mic_01}}\n')
        code, found = problems()
        hit = message(found, 'mic_01')
        record('speakers: a mic that had not started yet is refused on its line',
               code == 1 and hit is not None and hit['line'] == 10 and hit['severity'] == 'error', str(found)[-300:])
    # A cut in the middle of the line, so the synced camera has to follow it: strike a stretch between sentences.
    gaps = [index for index in range(3, len(pick) - 4) if pick[index + 1]['start'] - pick[index]['end'] > 0.2]
    middle = gaps[0] + 1 if gaps else len(pick) // 2
    kept = pick[:middle] + pick[middle + 2:]
    struck = ' '.join(row['text'] for row in pick[:middle]) + ' ~~' + ' '.join(
        row['text'] for row in pick[middle:middle + 2]) + '~~ ' + ' '.join(row['text'] for row in pick[middle + 2:])
    body = (f'> cam_01 {start:.2f}-{end:.2f} {struck} {{sound mic_01}}\n  ~ cam_02 sync Reaction\n')
    film(body)
    code, found = problems()
    errors = [item for item in found if item['severity'] == 'error']
    record('speakers: the synced line with sound from a mic passes check', code in (0, 1) and not errors, str(errors)[-400:])
    compared = speed.compare_paths(tool, record, 'a synced camera over a line with a cut, sound from a mic', root)
    if not compared:
        return
    fast = compared[0]
    edit = json.loads((fast / 'edit.json').read_text(encoding='utf-8'))
    lines = json.loads((fast / 'lines.json').read_text(encoding='utf-8'))['lines']
    spoken = next(row for row in lines if row['kind'] == 'spoken')
    expected = []
    for run in spoken['runs']:
        at, source_in, source_out = run['at'], run['in'], run['out']
        first = round(at * rate)
        last = round((at + source_out - source_in) * rate)
        for number in range(first, last):
            moment = source_in + (number / rate - at) - data['cam_02']['offset_s']
            expected.append(int(np.floor(moment * rate + 1e-6)) % 512)
    frames = speed.counters(speed.frames_of(fast / 'preview.mp4'))
    distance = [min(abs(a - b), 512 - abs(a - b)) for a, b in zip(frames, expected)]
    record('speakers: every frame of the synced camera is the one the offset names, within one frame',
           len(frames) == len(expected) and max(distance, default=9) <= 1, f'{len(frames)}/{len(expected)} frames, worst {max(distance, default=9)}')
    exact = sum(1 for gap in distance if gap == 0)
    record('speakers: most frames are exact (a frame off only where the measured offset rounds across a frame)',
           exact >= 0.9 * len(distance), f'{exact} of {len(distance)}')
    items = [item for item in edit['audio'] if item['track'] == 'dialogue']
    record('speakers: the dialogue plays from the mic, at the offset', all(
        item['src'] == 'mic_01' and abs(item['in'] - (run['in'] - data['mic_01']['offset_s'])) < 1e-3
        for item, run in zip(items, spoken['runs'])) and len(items) == len(spoken['runs']), str(items)[:300])
    stem, source = decoded(fast / 'stems' / 'dialogue.wav'), decoded(work / 'mic_a.wav')
    item = items[0]
    length = int((item['out'] - item['in']) * RATE) - 2000
    played = stem[int(item['at'] * RATE) + 1000:int(item['at'] * RATE) + 1000 + length]
    heard = source[int(item['in'] * RATE) + 1000:int(item['in'] * RATE) + 1000 + length]
    lag = correlate_at(heard, played, 480)
    match = float(np.corrcoef(played[:len(heard)], heard[:len(played)])[0, 1])
    record('speakers: the rendered stem is that mic, sample for sample', abs(lag) <= 1 and match > 0.98,
           f'lag {lag} samples, correlation {match:.3f}')
    captions = json.loads((fast / 'captions.json').read_text(encoding='utf-8'))
    placed = [word for cue in captions['cues'] for word in cue.get('words', [])]
    wanted = spoken['words']
    record('speakers: caption words keep the kept words\' film times',
           len(placed) == len(wanted) and all(abs(a['start'] - b['start']) < 0.05 for a, b in zip(placed, wanted))
           and [a['id'] for a in placed] == [b['id'] for b in wanted], f'{len(placed)}/{len(wanted)}')
    manifest = json.loads((fast / 'manifest.json').read_text(encoding='utf-8'))
    record('speakers: the version records the line-up it used',
           manifest.get('lineup', {}).get('sources', {}).get('cam_02', {}).get('sha256')
           == data['cam_02']['sha256'], str(manifest.get('lineup'))[:300])
    # The hand-off: the mic on the dialogue track at its own in-point, the camera on V2 at its own, and the note.
    out = work / 'handoff.xml'
    code, output = tool('exchange.py', 'write', root, fast.name, '--out', out)
    xml = out.read_text(encoding='utf-8') if out.is_file() else ''
    record('speakers: exchange.py write carries the mic and the second camera', code == 0
           and 'mic_a.wav' in xml and 'cam_b.mp4' in xml and 'no matching audio item' not in output, output[-500:])
    record('speakers: exchange.py write lists the line-up among what the XML cannot carry',
           'line-up' in output.lower() or 'lined up' in output.lower(), output[-400:])
    # A second run with the camera in its own line and a mic-only spoken line: the picture comes wholly from the camera.
    write_words(root, 'mic_02', [row for row in rows if row['true'] == 'Thom'])
    thom = [row for row in rows if row['true'] == 'Thom' and row['start'] > 2.0][:5]
    if len(thom) >= 3 and all(b['start'] - a['end'] < 1.0 for a, b in zip(thom, thom[1:])):
        film(f"> mic_02 {thom[0]['start'] - 0.05:.2f}-{thom[-1]['end'] + 0.05:.2f} "
             + ' '.join(row['text'] for row in thom) + '\n  ~ cam_01 sync\n')
        code, found = problems()
        hit = message(found, 'has no picture')
        record('speakers: a mic-only line wholly under a synced camera is not warned as uncovered',
               hit is None and not [item for item in found if item['severity'] == 'error'], str(found)[-300:])
    # Two cameras in turn over one line, and a picture line with a mic's sound.
    half = (pick[0]['start'] + pick[5]['end']) / 2
    film(f"> cam_01 {start:.2f}-{pick[5]['end'] + 0.05:.2f} " + ' '.join(row['text'] for row in pick[:6])
         + '\n  ~ cam_02 sync 1.0 First\n  ~ cam_01 sync 0.5 Back to the first\n'
         f'- cam_02 {half:.2f}-{half + 1:.2f} sound mic_02 Reaction with his mic\n')
    code, found = problems()
    errors = [item for item in found if item['severity'] == 'error']
    record('speakers: cameras in turn over a line, and a picture line with a mic\'s sound, pass check', not errors,
           str(errors)[-400:])
    code, output = tool('cut.py', 'render', root)
    version = sorted((root / 'cuts').glob('v[0-9]*'))[-1]
    edit = json.loads((version / 'edit.json').read_text(encoding='utf-8'))
    nat = [item for item in edit['audio'] if item['track'] == 'nat']
    record('speakers: a picture line can take its sound from a mic',
           code in (0, 1) and nat and nat[0]['src'] == 'mic_02'
           and abs(nat[0]['in'] - (half + data['cam_02']['offset_s'] - data['mic_02']['offset_s'])) < 1e-3,
           str(nat)[:200])
    check_used_sound(tool, record, j, scripts_dir, speech)
    check_one_source(tool, record, j, scripts_dir, speech)


def check_used_sound(tool, record, j, scripts_dir, speech):
    """A cut inside a line lands in a pause heard in the sound the film plays: here the camera has steady noise over
    every pause and the mic has none, so the same line is unmeasured on one and measured on the other."""
    samples, words = speech
    work = Path(j('speakers-pause'))
    work.mkdir(parents=True, exist_ok=True)
    voices, rows = conversation(samples, words, 33, 14)
    noisy = camera(voices, 1, gain_db=-22, noise_db=-16)
    # Enough speech in the camera's sound to line it up, with steady noise far above its pauses.
    write_wav(work / 'cam.wav', noisy)
    write_wav(work / 'mic.wav', mic(voices, 'Celia', 2, bleed_db=-14, noise_db=-70))
    write_wav(work / 'cam_ref.wav', camera(voices, 3))
    root = work / 'project'
    new_project(tool, root, [('camera', work / 'cam_ref.wav'), ('other', work / 'cam.wav'), ('mic', work / 'mic.wav')])
    tool('map.py', 'sync', root, '--reference', 'cam_01')
    data = saved(root)['sources']
    rows = [row for row in rows if row['end'] < 13]
    write_words(root, 'src_01', rows)
    gaps = [index for index in range(2, len(rows) - 4) if 0.2 < rows[index + 1]['start'] - rows[index]['end'] < 1.0]
    if not gaps or data['mic_01'].get('state') != 'lined-up' or data['src_01'].get('state') != 'lined-up':
        record('speakers: the pause fixture lines up and has a pause to cut in', False, str(data)[-400:])
        return
    index = gaps[0]
    keep_a = rows[max(0, index - 2):index + 1]
    drop = rows[index + 1:index + 3]
    keep_b = rows[index + 3:index + 6]
    span = (keep_a[0]['start'] - 0.05, keep_b[-1]['end'] + 0.05)
    line = (f'> src_01 {span[0]:.2f}-{span[1]:.2f} ' + ' '.join(row['text'] for row in keep_a) + ' ~~'
            + ' '.join(row['text'] for row in drop) + '~~ ' + ' '.join(row['text'] for row in keep_b))
    write = lambda text: (root / 'film.md').write_text(FRONT.format(size='320x180', fps=25, captions='none') + text,
                                                       encoding='utf-8')
    write(line + '\n')
    _, own = tool('cut.py', 'check', root, '--json')
    write(line + ' {sound mic_01}\n')
    _, used = tool('cut.py', 'check', root, '--json')
    own, used = json.loads(own[own.index('{'):]), json.loads(used[used.index('{'):])
    own_line = next(row for row in own['lines'] if row['kind'] == 'spoken')
    used_line = next(row for row in used['lines'] if row['kind'] == 'spoken')
    record('speakers: the line\'s own noisy sound cannot measure its pauses', bool(own_line.get('unmeasured_cuts')),
           str(own_line.get('unmeasured_why')))
    record('speakers: from the mic, the same line\'s cuts are measured in the sound it plays',
           not used_line.get('unmeasured_cuts') and used_line.get('sound_source') == 'mic_01',
           str(used_line.get('unmeasured_why')))
    run = used_line['runs'][0]
    record('speakers: the cut lands in the pause after the kept word',
           keep_a[-1]['end'] - 0.02 <= run['out'] <= rows[index + 1]['start'] + 0.02,
           f"out {run['out']} between {keep_a[-1]['end']} and {rows[index + 1]['start']}")


def check_one_source(tool, record, j, scripts_dir, speech):
    """A film of one source keeps every file the way it was: no line-up field appears anywhere in it."""
    speed = load(scripts_dir, 'speed', 'selftest_cases')
    work = Path(j('speakers-one'))
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'clip.mp4'
    speed.counted_source(scripts_dir, source, seconds=3)
    root = speed.project(work / 'project', source, speed.FRONT.format(size='320x180', fps=30, captions='srt') + (
        '> src_01 0:00.20-0:02.00 alpha bravo\n'), [('alpha', 0.3, 0.8), ('bravo', 1.0, 1.6)])
    code, output, folder, manifest = speed.render(tool, root)
    lines = json.loads((folder / 'lines.json').read_text(encoding='utf-8'))['lines']
    edit = json.loads((folder / 'edit.json').read_text(encoding='utf-8'))
    found = [key for row in lines for key in row if key in ('sync', 'sound_source', 'speaker')]
    found += [key for row in lines for run in row.get('runs', []) for key in run if key.startswith('sound_')]
    found += [key for row in lines for word in row.get('words', []) for key in word if key == 'speaker']
    found += [key for key in manifest if key == 'lineup']
    record('speakers: a one-source film gains no line-up field in lines.json, edit.json or manifest.json',
           code in (0, 1) and not found and all(set(item) <= {'track', 'src', 'in', 'out', 'at', 'fade_ms'}
                                                for item in edit['audio']), str(found))
    record('speakers: a one-source project writes no line-up file', not (Path(root) / 'map' / 'sync.json').exists())


# ----------------------------------------------------------------------------------------------- labels

def label_accuracy(words):
    """(correct, wrong, unlabelled) of labelled words against the fixture's truth."""
    correct = sum(1 for word in words if word.get('speaker') == word.get('true'))
    labelled = sum(1 for word in words if word.get('speaker') is not None)
    return correct, labelled - correct, len(words) - labelled


def check_labels(tool, record, j, scripts_dir, speech):
    """Speaker labels from per-person mics, what shows them, and the words that must stay unlabelled."""
    samples, words = speech
    work = Path(j('speakers-labels'))
    work.mkdir(parents=True, exist_ok=True)
    voices, rows = conversation(samples, words, 61, 60)
    write_wav(work / 'cam.wav', camera(voices, 1))
    write_wav(work / 'mic_a.wav', late(mic(voices, 'Celia', 2, gain_db=14, bleed_db=-16), 3.0), 44100)
    write_wav(work / 'mic_b.wav', late(mic(voices, 'Thom', 3, gain_db=-10, bleed_db=-16, noise_db=-60), 1.5))
    # A mic that hears both people the same way: nothing on it can tell them apart.
    write_wav(work / 'mic_table.wav', late(mic(voices, 'Celia', 4, bleed_db=0), 1.5))
    root = work / 'project'
    new_project(tool, root, [('camera', work / 'cam.wav'), ('mic', work / 'mic_a.wav'), ('mic', work / 'mic_b.wav'),
                             ('mic', work / 'mic_table.wav')])
    rows = [row for row in rows if row['end'] < 58]
    write_words(root, 'cam_01', rows)
    code, output = tool('map.py', 'speakers', root, 'cam_01', '--mic', 'mic_01=Celia', '--mic', 'mic_02=Thom')
    record('speakers: labelling without a line-up is refused and names the fix', code == 2 and 'sync' in output,
           output[-300:])
    code, output = tool('map.py', 'sync', root, '--reference', 'cam_01')
    data = saved(root)['sources']
    record('speakers: the label fixture lines up', all(data[name]['state'] == 'lined-up' for name in ('mic_01', 'mic_02')),
           output[-400:])
    code, output = tool('map.py', 'speakers', root, 'cam_01', '--mic', 'mic_01=Celia', '--mic', 'mic_02=Thom')
    path = root / 'map' / 'cam_01' / 'words.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    labelled = [dict(word, true=row['true']) for word, row in zip(stored['words'], rows)]
    correct, wrong, none = label_accuracy(labelled)
    record('speakers: the loudest clear mic names the speaker, though the other mic runs 24 dB hotter or colder',
           code == 0 and correct / max(1, correct + wrong) >= 0.97 and none <= 0.1 * len(rows),
           f'{correct} right, {wrong} wrong, {none} unlabelled of {len(rows)}')
    record('speakers: the words record how they were labelled, as a draft',
           stored.get('speaker_labels', {}).get('method') == 'mic-level' and stored['speaker_labels'].get('draft') is True
           and 'read' in stored['speaker_labels'].get('note', ''), str(stored.get('speaker_labels'))[:200])
    record('speakers: map.py speakers says labels are drafts', 'Drafts' in output, output[-200:])
    code, shown = tool('map.py', 'words', root, 'cam_01', '--from', '0', '--to', '20')
    record('speakers: map.py words shows each word\'s speaker and that labels are drafts',
           code in (0, 1) and '[Celia]' in shown and '[Thom]' in shown and 'drafts' in shown, shown[:200])
    text = (root / 'map' / 'cam_01' / 'transcript.md').read_text(encoding='utf-8')
    record('speakers: transcript.md shows the speakers and says they are drafts',
           '[Celia]' in text and '[Thom]' in text and 'drafts' in text, text[:300])
    phrases = re.findall(r'^\*\*[^*]+\*\*\s+\[([^\]]+)\]', text, re.MULTILINE)
    record('speakers: transcript.md breaks its phrases where the speaker changes', len(set(phrases)) >= 2 and all(
        phrases), str(phrases[:8]))
    first = stored['words'][0]['id']
    code, output = tool('map.py', 'fix', root, first, '--speaker', 'Someone Else', '--by', 'person')
    code2, _ = tool('map.py', 'speakers', root, 'cam_01', '--mic', 'mic_01=Celia', '--mic', 'mic_02=Thom')
    again = json.loads(path.read_text(encoding='utf-8'))
    record('speakers: a corrected label survives another labelling run',
           code == 0 and code2 == 0 and again['words'][0]['speaker'] == 'Someone Else', output[-200:])
    code, output = tool('map.py', 'speakers', root, 'cam_01', '--mic', 'mic_01=Celia', '--mic', 'mic_03=Table')
    table = json.loads(path.read_text(encoding='utf-8'))['words']
    named = [word for word in table[1:] if word.get('true', None) is None]
    record('speakers: a mic that hears both people as loud names nobody it cannot tell apart',
           code == 0 and sum(1 for word in table if word.get('speaker') == 'Table') <= 0.05 * len(table),
           str({name: sum(1 for word in table if word.get('speaker') == name) for name in ('Celia', 'Table', None)}))
    # Words that nobody clearly owns stay unlabelled: both people speak at once, equally.
    both, both_rows = conversation(samples, words, 71, 30)
    shared = {name: voice for name, voice in both.items()}
    overlap = shared['Celia'] + shared['Thom']
    equal = {'Celia': overlap, 'Thom': overlap}
    write_wav(work / 'same_a.wav', mic(equal, 'Celia', 5, bleed_db=-80))
    write_wav(work / 'same_b.wav', mic(equal, 'Thom', 6, bleed_db=-80))
    write_wav(work / 'same_cam.wav', camera(both, 7))
    root = work / 'project-same'
    new_project(tool, root, [('camera', work / 'same_cam.wav'), ('mic', work / 'same_a.wav'),
                             ('mic', work / 'same_b.wav')])
    tool('map.py', 'sync', root, '--reference', 'cam_01')
    write_words(root, 'cam_01', [row for row in both_rows if row['end'] < 28])
    code, output = tool('map.py', 'speakers', root, 'cam_01', '--mic', 'mic_01=A', '--mic', 'mic_02=B')
    stored = json.loads((root / 'map' / 'cam_01' / 'words.json').read_text(encoding='utf-8'))['words']
    record('speakers: a word with no clear winner stays unlabelled', code == 0 and all(
        word.get('speaker') is None for word in stored), output[-200:])
    code, output = tool('map.py', 'speakers', root, 'cam_01', '--rename', 'A=Ana')
    record('speakers: --rename needs no line-up and changes no unlabelled word', code == 0, output[-200:])
    check_caption_breaks(tool, record, j, scripts_dir)


def check_caption_breaks(tool, record, j, scripts_dir):
    """Captions break where the speaker changes, in captions.py itself and through a rendered film."""
    speed = load(scripts_dir, 'speed', 'selftest_cases')
    captions = load(scripts_dir, 'captions')
    words = [{'id': f'x-w{number:06d}', 'text': text, 'start': 0.3 * number, 'end': 0.3 * number + 0.25,
              'speaker': speaker} for number, (text, speaker) in enumerate(
                  [('we', 'A'), ('both', 'A'), ('know', 'A'), ('that', 'A'), ('do', 'B'), ('we', 'B'), ('really', 'B')])]
    source = Path(j('speakers-caption.json'))
    source.write_text(json.dumps({'words': words}), encoding='utf-8')
    prefix = j('speakers-caption')
    args = captions.argument_parser().parse_args(['build', str(source), '--out', prefix])
    report = captions.run_build(args)
    cues = report.get('cues') or json.loads(Path(prefix + '.json').read_text(encoding='utf-8'))['cues']
    mixed = [cue for cue in cues if len({word.get('speaker') for word in cue.get('words', [])}) > 1]
    record('speakers: captions.py build never runs a caption across a change of speaker',
           len(cues) >= 2 and not mixed, str([cue.get('text') for cue in cues]))
    # The same through a film: the labels reach the caption builder.
    work = Path(j('speakers-caption-film'))
    work.mkdir(parents=True, exist_ok=True)
    clip = work / 'clip.mp4'
    speed.counted_source(scripts_dir, clip, seconds=4)
    timed = [('we', 0.3, 0.55), ('both', 0.6, 0.85), ('know', 0.9, 1.15), ('that', 1.2, 1.45), ('do', 1.5, 1.75),
             ('we', 1.8, 2.05), ('really', 2.1, 2.35), ('now', 2.4, 2.65)]
    root = speed.project(work / 'project', clip, speed.FRONT.format(size='320x180', fps=30, captions='srt') + (
        '> src_01 0:00.20-0:02.80 we both know that do we really now\n'), timed)
    path = Path(root) / 'map' / 'src_01' / 'words.json'
    stored = json.loads(path.read_text(encoding='utf-8'))
    for number, word in enumerate(stored['words']):
        word['speaker'] = 'A' if number < 4 else None if number == 4 else 'B'
    path.write_text(json.dumps(stored), encoding='utf-8')
    code, output, folder, _ = speed.render(tool, root)
    built = json.loads((folder / 'captions.json').read_text(encoding='utf-8'))['cues'] if folder.is_dir() else []
    speakers = [{word.get('speaker') for word in cue.get('words', [])} - {None} for cue in built]
    record('speakers: a film\'s captions break at a speaker change, an unlabelled word between them included',
           len(built) >= 2 and all(len(group) <= 1 for group in speakers), str(speakers))
    lines = json.loads((folder / 'lines.json').read_text(encoding='utf-8'))['lines']
    record('speakers: lines.json carries each kept word\'s speaker',
           any(word.get('speaker') == 'A' for row in lines for word in row.get('words', [])))


# ----------------------------------------------------------------------------------------------- imports

IMPORTS = {
    'WhisperX: a segment\'s speaker reaches the words without one': (
        {'segments': [{'start': 0.5, 'end': 1.5, 'text': 'hello there', 'speaker': 'SPEAKER_00', 'words': [
            {'word': 'hello', 'start': 0.5, 'end': 0.9, 'score': 0.9, 'speaker': 'SPEAKER_00'},
            {'word': 'there', 'start': 1.0, 'end': 1.5, 'score': 0.8}]},
            {'start': 2.0, 'end': 2.5, 'text': 'hi', 'speaker': 'SPEAKER_01', 'words': [
                {'word': 'hi', 'start': 2.0, 'end': 2.5, 'score': 0.9, 'speaker': 'SPEAKER_01'}]}],
         'word_segments': []},
        [('hello', 0.5, 0.9, 'SPEAKER_00'), ('there', 1.0, 1.5, 'SPEAKER_00'), ('hi', 2.0, 2.5, 'SPEAKER_01')]),
    'Deepgram: words, punctuation and a speaker of 0 are kept': (
        {'metadata': {'duration': 3.0}, 'results': {'channels': [{'alternatives': [{'transcript': 'Hello there. Hi.',
            'words': [{'word': 'hello', 'punctuated_word': 'Hello', 'start': 0.5, 'end': 0.9, 'confidence': 0.9,
                       'speaker': 0},
                      {'word': 'there', 'punctuated_word': 'there.', 'start': 1.0, 'end': 1.5, 'confidence': 0.8,
                       'speaker': 0},
                      {'word': 'hi', 'punctuated_word': 'Hi.', 'start': 2.0, 'end': 2.5, 'confidence': 0.9,
                       'speaker': 1}]}]}]}},
        [('Hello', 0.5, 0.9, '0'), ('there.', 1.0, 1.5, '0'), ('Hi.', 2.0, 2.5, '1')]),
    'AssemblyAI: milliseconds become seconds and speakers stay': (
        {'audio_duration': 3, 'words': [{'text': 'Hello', 'start': 500, 'end': 900, 'confidence': 0.9, 'speaker': 'A'},
                                        {'text': 'there.', 'start': 1000, 'end': 1500, 'confidence': 0.8, 'speaker': 'A'},
                                        {'text': 'Hi.', 'start': 2000, 'end': 2500, 'confidence': 0.9, 'speaker': 'B'}]},
        [('Hello', 0.5, 0.9, 'A'), ('there.', 1.0, 1.5, 'A'), ('Hi.', 2.0, 2.5, 'B')]),
    'Rev: monologues, with punctuation joined to its word': (
        {'monologues': [{'speaker': 0, 'elements': [
            {'type': 'text', 'value': 'Hello', 'ts': 0.5, 'end_ts': 0.9, 'confidence': 0.9},
            {'type': 'punct', 'value': ' '},
            {'type': 'text', 'value': 'there', 'ts': 1.0, 'end_ts': 1.5, 'confidence': 0.8},
            {'type': 'punct', 'value': '.'}]},
            {'speaker': 1, 'elements': [{'type': 'text', 'value': 'Hi', 'ts': 2.0, 'end_ts': 2.5, 'confidence': 0.9},
                                        {'type': 'punct', 'value': '.'}]}]},
        [('Hello', 0.5, 0.9, '0'), ('there.', 1.0, 1.5, '0'), ('Hi.', 2.0, 2.5, '1')]),
    'Amazon Transcribe: items, with speaker labels on each': (
        {'results': {'items': [
            {'start_time': '0.5', 'end_time': '0.9', 'type': 'pronunciation', 'speaker_label': 'spk_0',
             'alternatives': [{'confidence': '0.9', 'content': 'Hello'}]},
            {'start_time': '1.0', 'end_time': '1.5', 'type': 'pronunciation', 'speaker_label': 'spk_0',
             'alternatives': [{'confidence': '0.8', 'content': 'there'}]},
            {'type': 'punctuation', 'alternatives': [{'confidence': '0.0', 'content': '.'}]},
            {'start_time': '2.0', 'end_time': '2.5', 'type': 'pronunciation', 'speaker_label': 'spk_1',
             'alternatives': [{'confidence': '0.9', 'content': 'Hi'}]}]}},
        [('Hello', 0.5, 0.9, 'spk_0'), ('there.', 1.0, 1.5, 'spk_0'), ('Hi', 2.0, 2.5, 'spk_1')]),
    'Amazon Transcribe: an older file keeps speakers in a separate list': (
        {'results': {'speaker_labels': {'segments': [
            {'speaker_label': 'spk_0', 'items': [{'start_time': '0.5', 'end_time': '0.9', 'speaker_label': 'spk_0'},
                                                 {'start_time': '1.0', 'end_time': '1.5', 'speaker_label': 'spk_0'}]},
            {'speaker_label': 'spk_1', 'items': [{'start_time': '2.0', 'end_time': '2.5', 'speaker_label': 'spk_1'}]}]},
            'items': [
                {'start_time': '0.5', 'end_time': '0.9', 'type': 'pronunciation',
                 'alternatives': [{'confidence': '0.9', 'content': 'Hello'}]},
                {'start_time': '1.0', 'end_time': '1.5', 'type': 'pronunciation',
                 'alternatives': [{'confidence': '0.8', 'content': 'there'}]},
                {'start_time': '2.0', 'end_time': '2.5', 'type': 'pronunciation',
                 'alternatives': [{'confidence': '0.9', 'content': 'Hi'}]}]}},
        [('Hello', 0.5, 0.9, 'spk_0'), ('there', 1.0, 1.5, 'spk_0'), ('Hi', 2.0, 2.5, 'spk_1')]),
    'ElevenLabs Scribe: speaker_id kept, spacing and audio events left out': (
        {'language_code': 'eng', 'text': 'Hello there. Hi.', 'words': [
            {'text': 'Hello', 'start': 0.5, 'end': 0.9, 'type': 'word', 'speaker_id': 'speaker_0'},
            {'text': ' ', 'start': 0.9, 'end': 1.0, 'type': 'spacing', 'speaker_id': 'speaker_0'},
            {'text': 'there.', 'start': 1.0, 'end': 1.5, 'type': 'word', 'speaker_id': 'speaker_0'},
            {'text': '(laughs)', 'start': 1.6, 'end': 1.9, 'type': 'audio_event', 'speaker_id': 'speaker_0'},
            {'text': 'Hi.', 'start': 2.0, 'end': 2.5, 'type': 'word', 'speaker_id': 'speaker_1'}]},
        [('Hello', 0.5, 0.9, 'speaker_0'), ('there.', 1.0, 1.5, 'speaker_0'), ('Hi.', 2.0, 2.5, 'speaker_1')]),
    'Google Speech-to-Text: the last result holds the speaker tags': (
        {'results': [{'alternatives': [{'transcript': 'Hello there. Hi.', 'words': [
            {'startTime': '0.500s', 'endTime': '0.900s', 'word': 'Hello'}]}]},
            {'alternatives': [{'words': [
                {'startTime': '0.500s', 'endTime': '0.900s', 'word': 'Hello', 'speakerTag': 1},
                {'startTime': '1s', 'endTime': '1.500s', 'word': 'there.', 'speakerTag': 1},
                {'startTime': '2s', 'endTime': '2.500s', 'word': 'Hi.', 'speakerTag': 2}]}]}]},
        [('Hello', 0.5, 0.9, '1'), ('there.', 1.0, 1.5, '1'), ('Hi.', 2.0, 2.5, '2')]),
    'A plain word list with a speaker on each word, as before': (
        {'words': [{'word': 'hello', 'start': 0.5, 'end': 0.9, 'speaker': 'Ana'},
                   {'text': 'hi', 'start': 2.0, 'end': 2.5, 'speaker': 'Ben'}]},
        [('hello', 0.5, 0.9, 'Ana'), ('hi', 2.0, 2.5, 'Ben')]),
    'A plain word list with no speakers stays unlabelled': (
        {'words': [{'word': 'hello', 'start': 0.5, 'end': 0.9}]}, [('hello', 0.5, 0.9, None)]),
}


def check_imports(tool, record, j, scripts_dir):
    """--words import keeps the speaker fields of the word-timed formats people have; what is not word-timed is
    still estimated. These are the formats' documented shapes, not captures of each service's current output."""
    transcribe = load(scripts_dir, 'transcribe')
    work = Path(j('speakers-import'))
    work.mkdir(parents=True, exist_ok=True)
    for number, (name, (data, expected)) in enumerate(IMPORTS.items()):
        path = work / f'import-{number}.json'
        path.write_text(json.dumps(data), encoding='utf-8')
        try:
            words = transcribe.normalize(transcribe.read_import(path), 'src_01')
            found = [(word['text'], round(word['start'], 3), round(word['end'], 3), word['speaker']) for word in words]
        except Exception as error:  # a format this cannot read is this case's failure, not the module's
            found = repr(error)
        record(f'speakers: import: {name}', found == expected, f'{found}')
    vtt = work / 'voices.vtt'
    vtt.write_text('WEBVTT\n\n00:00.500 --> 00:01.500\n<v Ana>hello there</v>\n\n00:02.000 --> 00:02.500\n'
                   '<v Ben>hi\n', encoding='utf-8')
    words = transcribe.normalize(transcribe.read_import(vtt), 'src_01')
    record('speakers: import: WebVTT voice tags name the cue\'s speaker',
           [word['speaker'] for word in words] == ['Ana', 'Ana', 'Ben'] and words[0]['estimated'], str(words)[:200])
    # Through the map: labels are recorded as imported drafts, and the transcript shows them.
    clip = work / 'tone.wav'
    write_wav(clip, 0.1 * np.sin(2 * np.pi * 220 * np.arange(3 * RATE) / RATE))
    root = work / 'project'
    new_project(tool, root, [('other', clip)])
    source = work / 'import-1.json'
    code, output = tool('map.py', 'run', root, '--alias', 'src_01', '--words', f'import:{source}')
    stored = json.loads((root / 'map' / 'src_01' / 'words.json').read_text(encoding='utf-8'))
    record('speakers: map.py run --words import keeps speakers and records them as imported drafts',
           code in (0, 1) and [word['speaker'] for word in stored['words']] == ['0', '0', '1']
           and stored.get('speaker_labels', {}).get('method') == 'imported'
           and stored['speaker_labels'].get('draft') is True, output[-300:])
    code, output = tool('map.py', 'speakers', root, 'src_01', '--rename', '0=Ana', '--rename', '1=Ben')
    stored = json.loads((root / 'map' / 'src_01' / 'words.json').read_text(encoding='utf-8'))
    text = (root / 'map' / 'src_01' / 'transcript.md').read_text(encoding='utf-8')
    record('speakers: map.py speakers --rename gives imported speakers their names',
           code == 0 and [word['speaker'] for word in stored['words']] == ['Ana', 'Ana', 'Ben'] and '[Ben]' in text,
           output[-200:])
    # Milliseconds with no sign of the service in the file: the media's length tells.
    bare = work / 'bare.json'
    bare.write_text(json.dumps({'words': [{'text': 'Hello', 'start': 500, 'end': 900, 'speaker': 'A'},
                                          {'text': 'Hi', 'start': 2000, 'end': 2500, 'speaker': 'B'}]}), encoding='utf-8')
    code, output = tool('map.py', 'run', root, '--alias', 'src_01', '--words', f'import:{bare}', '--retranscribe', 'src_01')
    stored = json.loads((root / 'map' / 'src_01' / 'words.json').read_text(encoding='utf-8'))
    record('speakers: word times far past the media\'s end are read as milliseconds, and it says so',
           code in (0, 1) and abs(stored['words'][1]['end'] - 2.5) < 1e-6 and 'millisecond' in output, output[-300:])


def run_speakers_cases(tool, record, j, scripts_dir, skip=None):
    """Line-up, the paper edit over it and speaker labels, on real speech with known answers."""
    check_imports(tool, record, j, scripts_dir)
    found = example(scripts_dir)
    if found is None:
        (skip or (lambda name, reason, count=1: print(f'SKIP  {name} ({reason})')))(
            'speakers: real-speech cases', 'the first-cut example is not installed', 60)
        return
    speech = (clip_samples(found[0]), found[1])
    check_lineup(tool, record, j, scripts_dir, speech)
    check_labels(tool, record, j, scripts_dir, speech)
    check_paper_edit(tool, record, j, scripts_dir, speech)
