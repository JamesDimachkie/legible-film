"""Known-answer tests for a tightened paper edit and its rendered sound.

The source is a counter-free synthetic video with distinct tone words, planted quiet gaps, a filler and an
untranscribed burst. These checks test this fixture and the rendered file, not perception or transcript accuracy.
"""
import json
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import wave

import numpy as np

RATE = 48000
DURATION = 7.4
ROWS = [('alpha', 0.50, 0.90, 400), ('um', 1.15, 1.45, 600), ('bravo', 1.70, 2.10, 800),
        ('charlie', 3.65, 4.05, 1000), ('delta', 5.40, 5.80, 1200), ('echo', 6.00, 6.40, 1400),
        ('echo', 6.55, 6.85, 1600)]
BURST = (2.50, 2.75, 1800)


def make_fixture(root, room_db=None, bed_db=None):
    """Write the synthetic source, whose unique tone frequencies identify all speech-like intervals."""
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(111)
    room_rms = .0004 if room_db is None else 10 ** (room_db / 20)
    samples = rng.normal(0, room_rms, int(RATE * DURATION))
    if bed_db is not None:
        samples += 2 ** .5 * 10 ** (bed_db / 20) * np.sin(2 * np.pi * 220 * np.arange(len(samples)) / RATE)
    for start, end, freq in [(row[1], row[2], row[3]) for row in ROWS] + [BURST]:
        a, b = int(start * RATE), int(end * RATE)
        times = np.arange(b - a) / RATE
        samples[a:b] += .25 * np.sin(2 * np.pi * freq * times)
    wav = root / 'tones.wav'
    with wave.open(str(wav), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.int16(np.clip(samples, -1, 1) * 32767).tobytes())
    media = root / 'source.mkv'
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
               f'color=c=0x405060:s=320x180:r=25:d={DURATION}', '-i', str(wav), '-map', '0:v', '-map', '1:a',
               '-c:v', 'ffv1', '-c:a', 'pcm_s16le', '-shortest', str(media)]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return media


def write_words(root, rows=ROWS):
    """Bind a transcript to the exact synthetic media and selected sound stream."""
    source = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    words = [{'id': f'int_01-w{index:06d}', 'text': text, 'start': start, 'end': end, 'p': .99}
             for index, (text, start, end, _) in enumerate(rows, 1)]
    data = {'version': 1, 'source': 'int_01', 'engine': 'synthetic', 'words': words,
            'media': {'sha256': source['sha256'], 'audio_stream': source['audio']['index']}}
    (folder / 'words.json').write_text(json.dumps(data), encoding='utf-8')


def tone_strength(samples, frequency):
    """Largest 0.1-second matched-tone amplitude anywhere in the decoded deliverable."""
    count = RATE // 10
    times = np.arange(count) / RATE
    sine = np.sin(2 * np.pi * frequency * times)
    cosine = np.cos(2 * np.pi * frequency * times)
    best = 0.0
    for start in range(0, max(0, len(samples) - count), count // 2):
        chunk = samples[start:start + count]
        amplitude = 2 * np.hypot(float(chunk @ sine), float(chunk @ cosine)) / count
        best = max(best, amplitude)
    return best


def tone_coverage(samples, frequency):
    """Approximate retained tone duration using independent 40 ms windows every 10 ms."""
    width = RATE // 25
    step = RATE // 100
    times = np.arange(width) / RATE
    sine = np.sin(2 * np.pi * frequency * times)
    cosine = np.cos(2 * np.pi * frequency * times)
    active = []
    for start in range(0, max(0, len(samples) - width), step):
        chunk = samples[start:start + width]
        amplitude = 2 * np.hypot(float(chunk @ sine), float(chunk @ cosine)) / width
        if amplitude > .12:
            active.append(start / RATE)
    return (max(active) - min(active)) if active else 0.0


def decode(path):
    """Decode the actual MP4's sound, not the source or compiler's timeline."""
    result = subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-i', str(path), '-vn', '-ac', '1',
                             '-ar', str(RATE), '-f', 'f32le', 'pipe:1'], capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return np.frombuffer(result.stdout, dtype='<f4')


def check_declared_busy(record, scripts_dir):
    """A declared tighten section identifies busy pacing; ordinary sections still warn."""
    spec = importlib.util.spec_from_file_location('tighten_busy_cut', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cut)
    changes = [{'at': at, 'line': 10, 'kind': 'edit'} for at in (1.0, 1.5, 2.0)]
    cut.picture_changes = lambda segments, source_map, assets=None: changes
    outcomes = []
    for section in ('Tighten (declared jump cuts)', 'Interview'):
        plan = {'segments': [], 'pieces': []}
        problems = cut.Problems()
        cut.join_report(plan, [{'line': 10, 'section': section}], None, None, problems)
        outcomes.append((plan['busy_cutting'], problems.items))
    declared, ordinary = outcomes
    record('tighten: declared jump-cut pacing is named and other films still get a busy warning',
           cut.picture_changes([], None, {}) == changes
           and len(declared[0]) == 1 and any(item['severity'] == 'info' and 'declared talking-head' in item['message']
                                        for item in declared[1])
           and len(ordinary[0]) == 1 and any(item['severity'] == 'warning' for item in ordinary[1]),
           str(outcomes))
    cut.picture_changes = lambda segments, source_map, assets=None: [dict(change, kind='source shot')
                                                                    for change in changes]
    plan = {'segments': [], 'pieces': []}
    problems = cut.Problems()
    cut.join_report(plan, [{'line': 10, 'section': 'Tighten (declared jump cuts)'}], None, None, problems)
    record('tighten: busy source-shot changes still warn in a declared tighten section',
           all(item['kind'] == 'source shot' for item in cut.picture_changes([], None, {}))
           and len(plan['busy_cutting']) == 1 and any(item['severity'] == 'warning' for item in problems.items),
           str(problems.items))


def check_filler_choice(record, scripts_dir):
    """Only requested whole filler words or phrases are selected."""
    modules = []
    for name in ('cut', 'tighten'):
        spec = importlib.util.spec_from_file_location('tighten_choice_' + name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    cut, tighten = modules
    words = [{'text': text} for text in ('uh', 'like', 'you', 'know', 'today')]
    named = tighten.filler_indices(words, 'named', cut)
    chosen = tighten.filler_indices(words, 'like,you know', cut)
    record('tighten: lexical fillers require their explicit word or whole-phrase listing',
           named == {0} and chosen == {1, 2, 3}, f'named={named}, explicit={chosen}')


def check_crossfade_guard(record, scripts_dir):
    """Do not carry an untranscribed energetic burst into a crossfade handle."""
    modules = []
    for name in ('cut', 'tighten'):
        spec = importlib.util.spec_from_file_location('tighten_fade_' + name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    cut, tighten = modules
    outcomes = []
    for burst in (False, True):
        rate = 8000
        rng = np.random.default_rng(12)
        samples = rng.normal(0, 10, 5 * rate)
        for start, end in [(0.5, 1.0), (3.5, 4.0)] + ([(1.54, 1.64)] if burst else []):
            count = int((end - start) * rate)
            tone = 8000 * np.sin(2 * np.pi * 400 * np.arange(count) / rate)
            samples[int(start * rate):int(start * rate) + count] += tone
        envelope = cut.Envelope(samples.astype(np.int16), rate, 0.0)

        class Envelopes:
            def get(self, alias, start, end):
                return envelope

        class Source:
            def words(self, alias):
                return [{'start': .5, 'end': 1.0}, {'start': 3.5, 'end': 4.0}]

        class Compiler:
            def __init__(self):
                self.envelopes = Envelopes()
                self.map = Source()
                self.called = 0
                entry = {'section': 'Tighten (declared jump cuts)', 'mods': {}}
                before = {'entry': entry, 'alias': 'int_01', 'item': {}, 'speed': 1, 'out': 1.5,
                          'at': 0.0, 'end': 1.5, 'last_word': 1.0, 'carry': {}}
                after = {'entry': entry, 'alias': 'int_01', 'item': {}, 'speed': 1, 'in': 3.0,
                         'at': 1.5, 'end': 3.0, 'first_word': 2.0, 'carry': {}, 'record': {}}
                # Nonempty audio items stand in for the compiler's source clips.
                before['item']['src'] = 'int_01'
                after['item']['src'] = 'int_01'
                self.line_pieces = [[before], [after]]

            def join_of(self, entry):
                return None

            def carry_dissolve(self, before, after, seconds, total):
                self.called += 1
                after['carry']['dissolve'] = [1.5, 1.6]

        compiler = Compiler()
        compiler.tighten_guard = tighten.DecayGuard(samples.astype(np.float32) / 32768, rate)
        tighten.carry_crossfades(compiler, 3.0)
        outcomes.append(compiler.called)
    record('tighten: a sound crossfade is skipped when its source handle contains untranscribed energy',
           outcomes == [1, 0], str(outcomes))


def check_room_tone(tool, record, j, room_db):
    """Shorten a known gap over steady room tone while protecting a louder untranscribed burst."""
    suffix = str(abs(room_db))
    root = Path(j('tighten-room-' + suffix))
    media = make_fixture(Path(j('tighten-room-media-' + suffix)), room_db)
    code, output = tool('project.py', 'init', root, '--title', 'Synthetic room tone')
    code2, output2 = tool('map.py', 'add', root, media, '--role', 'interview')
    if code or code2:
        record(f'tighten: {room_db} dBFS room-tone fixture setup', False, output + output2)
        return
    write_words(root)
    code, output = tool('cut.py', 'tighten', root, 'int_01')
    path = root / 'film.tighten.json'
    if code not in (0, 1) or not path.exists():
        record(f'tighten: {room_db} dBFS room-tone edit', False, output)
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    gaps = [row for row in data['removals'] if row['kind'] == 'pause'
            and 4.05 <= row['start'] and row['end'] <= 5.40]
    remaining = 5.40 - 4.05 - sum(row['end'] - row['start'] for row in gaps)
    record(f'tighten: a pause over {room_db} dBFS room tone reaches the target',
           len(gaps) == 1 and abs(remaining - .35) <= .08, f'{remaining:.3f} s remains')
    flags = data['untranscribed_sound']
    safe = all(not (row['start'] < BURST[1] and row['end'] > BURST[0]) for row in data['removals'])
    flag = any(row['start'] <= BURST[0] + .02 and row['end'] >= BURST[1] - .02 for row in flags)
    record(f'tighten: louder untranscribed sound survives over {room_db} dBFS room tone',
           safe and flag, json.dumps({'flags': flags, 'removals': data['removals']}))


def check_partial_pause(record, scripts_dir):
    """A failed full pause cut can still use quiet without cutting the intervening burst."""
    modules = []
    for name in ('cut', 'tighten'):
        spec = importlib.util.spec_from_file_location('tighten_partial_' + name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    cut, tighten = modules
    rate = 8000
    samples = np.random.default_rng(111).normal(0, 10, int(rate * DURATION))
    for start, end, frequency in [(row[1], row[2], row[3]) for row in ROWS] + [BURST]:
        a, b = int(start * rate), int(end * rate)
        samples[a:b] += 8000 * np.sin(2 * np.pi * frequency * np.arange(b - a) / rate)
    envelope = cut.Envelope(samples.astype(np.int16), rate, 0)
    guard = tighten.DecayGuard(samples.astype(np.float32) / 32768, rate)
    words = [{'text': text, 'start': start, 'end': end} for text, start, end, _ in ROWS]
    unknown = tighten.unknown_sound(words, envelope, DURATION)
    existing = [(4.225, 5.225)]
    candidates = tighten.partial_pause_splits(words, set(), envelope, .35, existing, [], unknown, guard)
    available = [item for item in candidates if item['index'] == 3]
    record('tighten: a partly quiet gap can shorten without touching an untranscribed burst',
           len(available) == 1 and available[0]['end'] - available[0]['start'] > .5
           and not tighten.overlap(available[0]['start'], available[0]['end'], BURST[0], BURST[1])
           and not any(item['index'] == 4 for item in candidates), str(candidates))


def make_decay_fixture(root, kind):
    """Create known word tones with a decaying tail, a delayed echo, or a tiny removable gap."""
    root.mkdir(parents=True, exist_ok=True)
    short = kind == 'near-zero'
    duration = 2.6 if short else 5.2
    rows = [('first', .50, 1.00, 400), ('next', 1.39 if short else 3.40, 1.80 if short else 3.90, 800)]
    samples = np.random.default_rng(211).normal(0, 10 ** (-50 / 20), int(RATE * duration))
    for _, start, end, frequency in rows:
        a, b = int(start * RATE), int(end * RATE)
        samples[a:b] += .25 * np.sin(2 * np.pi * frequency * np.arange(b - a) / RATE)
    if not short:
        a, b = int(RATE), int(3.1 * RATE)
        times = np.arange(b - a) / RATE
        samples[a:b] += .25 * np.exp(-times / .18) * np.sin(2 * np.pi * 400 * times)
        if kind == 'reverb':
            a = int(1.45 * RATE)
            times = np.arange(b - a) / RATE
            samples[a:b] += .12 * np.exp(-times / .24) * np.sin(2 * np.pi * 1200 * times)
    wav = root / 'tail.wav'
    with wave.open(str(wav), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(np.int16(np.clip(samples, -1, 1) * 32767).tobytes())
    media = root / 'source.mkv'
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
               f'color=c=0x405060:s=320x180:r=25:d={duration}', '-i', str(wav), '-map', '0:v', '-map', '1:a',
               '-c:v', 'ffv1', '-c:a', 'pcm_s16le', '-shortest', str(media)]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return media, rows


def check_decay_tail(tool, record, j, kind, scripts_dir):
    """Check a compiled removal against the planted decay and the measured near-floor threshold."""
    root = Path(j('decay-' + kind))
    media, rows = make_decay_fixture(Path(j('decay-media-' + kind)), kind)
    code, output = tool('project.py', 'init', root, '--title', 'Decay and room tone')
    code2, output2 = tool('map.py', 'add', root, media, '--role', 'interview')
    if code or code2:
        record(f'tighten: {kind} fixture setup', False, output + output2)
        return
    write_words(root, rows)
    code, output = tool('cut.py', 'tighten', root, 'int_01')
    path = root / 'film.tighten.json'
    if code not in (0, 1) or not path.exists():
        record(f'tighten: {kind} edit', False, output)
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    if kind == 'near-zero':
        record('tighten: a near-zero pause is left without a join', not data['removals'], json.dumps(data))
        return
    spec = importlib.util.spec_from_file_location('decay_tighten', Path(scripts_dir) / 'tighten.py')
    tighten = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tighten)
    with wave.open(str(media.parent / 'tail.wav'), 'rb') as handle:
        samples = np.frombuffer(handle.readframes(handle.getnframes()), dtype='<i2').astype(np.float32) / 32768
    guard = tighten.DecayGuard(samples, RATE)
    rows_removed = [item for item in data['removals'] if item['kind'] == 'pause']
    threshold = 10 ** ((-50 + tighten.ROOM_MARGIN_DB) / 20)
    settle = 1.0 + .18 * np.log(.25 / (2 ** .5 * threshold))
    if kind == 'reverb':
        settle = max(settle, 1.45 + .24 * np.log(.12 / (2 ** .5 * threshold)))
    safe = bool(rows_removed) and all(item['audio_start'] >= settle - .03
                                      and guard.quiet(item['audio_start'] - .03, item['audio_start'])
                                      and item['audio_start'] >= rows[0][2] + tighten.WORD_HANDLE - .002
                                      and item['audio_end'] <= rows[1][1] - tighten.WORD_HANDLE + .002
                                      for item in rows_removed)
    record(f'tighten: {kind} tail decays to near room tone before the cut', safe,
           f'expected settle >= {settle:.3f}; {json.dumps(rows_removed)}')


def check_music_bed(tool, record, j):
    """A declared continuous bed keeps both pauses and explicitly requested fillers."""
    root = Path(j('tighten-bed'))
    media = make_fixture(Path(j('tighten-bed-media')), room_db=-50, bed_db=-35)
    code, output = tool('project.py', 'init', root, '--title', 'Synthetic continuous bed')
    code2, output2 = tool('map.py', 'add', root, media, '--role', 'interview')
    if code or code2:
        record('tighten: declared bed fixture setup', False, output + output2)
        return
    write_words(root)
    code, output = tool('cut.py', 'tighten', root, 'int_01', '--fillers', 'named', '--music-bed')
    path = root / 'film.tighten.json'
    if code != 1 or not path.exists():
        record('tighten: declared bed keeps pauses and fillers', False, output)
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    report = (root / 'film.tighten-report.md').read_text(encoding='utf-8')
    film = (root / 'film.md').read_text(encoding='utf-8')
    record('tighten: declared bed keeps pauses and fillers and reports why',
           not data['removals'] and data['selected_filler_count'] == 0 and data['music_bed_declared']
           and 'max_pause: none' in film and '~~' not in film and 'cutting would make the bed jump' in report
           and 'Pause at ' not in report, output)
    code, output = tool('cut.py', 'tighten', root, 'int_01', '--silence-only', '--music-bed', '--force')
    data = json.loads(path.read_text(encoding='utf-8'))
    report = (root / 'film.tighten-report.md').read_text(encoding='utf-8')
    record('tighten: a declared bed is also retained without a transcript',
           code == 1 and not data['removals'] and not data['untranscribed_sound_assessed']
           and 'Not assessed: no transcript' in report, output)


def check_reel_pairs(tool, record, root, scripts_dir):
    """Compare the comparison audio with the compiler's actual track for edge fades and crossfades."""
    modules = []
    for name in ('cut', 'tighten', 'assemble'):
        spec = importlib.util.spec_from_file_location('reel_test_' + name, Path(scripts_dir) / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    cut, tighten, assemble = modules
    long_reel = {'made': True, 'events': 1, 'total_events': 15, 'duration_s': 103.1, 'cuts': 1, 'total_cuts': 1,
                 'prompts': 0, 'total_prompts': 14, 'source_boundary_events': 0}
    # From an editor's test of 2.0 on a raw interview: ten cuts and eleven prompts, of which the reel played five.
    capped = tighten.reel_coverage({'events': 15, 'total_events': 21, 'duration_s': 112.4, 'cuts': 10,
                                    'total_cuts': 10, 'prompts': 5, 'total_prompts': 11})
    record('tighten: the reel says how many cuts and listening prompts it plays, and how to play them all',
           capped == 'Reel plays 10 of 10 cuts and 5 of 11 listening prompts (the report lists every one; '
                     '--reel-limit 21 plays them all); 112.4 s.', capped)
    long_report = tighten.report_text('int_01', .35, [], [], [], [], 'reel.mp4', long_reel,
                                      False, True, False, cut)
    record('tighten: one long reel event is not offered a useless count limit',
           'one event' in long_report.lower() and 'count limit cannot shorten' in long_report.lower(), long_report)
    source = cut.SourceMap(root)
    guard = tighten.DecayGuard.from_source(source, 'int_01', cut)
    data = json.loads((root / 'film.tighten.json').read_text(encoding='utf-8'))
    index = data['reel_info']['clips']
    pairs = [row for row in index if row['kind'] == 'AFTER']
    expected = len(data['removals'])
    complete = len(pairs) == expected and sum(row['kind'] == 'BEFORE' for row in index) == expected
    complete &= sum(row['kind'] == 'LISTEN' for row in index) == len(data['untranscribed_sound'])
    complete &= all(any(other['kind'] == 'BEFORE' and other['event_start'] == row['event_start']
                        and other['source_start'] == row['source_start'] and other['source_end'] == row['source_end']
                        for other in index) for row in pairs)
    record('tighten: the reel indexes complete BEFORE/AFTER pairs and LISTEN prompts', complete, json.dumps(index))
    words = source.words('int_01')
    duration = source.duration('int_01')
    full_context = all(row['source_start'] <= max(0.0, row['event_start'] - 1.0) + .002
                       and row['source_end'] >= min(duration, row['event_end'] + 1.0) - .002 for row in index)
    safe_edges = all((row['source_start'] == 0 or (guard.quiet(row['source_start'], row['source_start'] + .03)
                      and not any(tighten.overlap(row['source_start'], row['source_start'] + .03,
                                                  word['start'], word['end']) for word in words)))
                     and (row['source_end'] == duration or (guard.quiet(row['source_end'] - .03, row['source_end'])
                      and not any(tighten.overlap(row['source_end'] - .03, row['source_end'],
                                                  word['start'], word['end']) for word in words))) for row in index)
    record('tighten: reel context reaches complete words and avoids speech at its faded edges',
           full_context and safe_edges, json.dumps(index))
    reel_samples = decode(root / 'film.tighten-reel.mp4')
    gap_checks = []
    for left, right in zip(index, index[1:]):
        middle = (left['reel_start'] + left['duration_s'] + right['reel_start']) / 2
        section = reel_samples[int((middle - .025) * RATE):int((middle + .025) * RATE)]
        gap_checks.append(len(section) > 0 and float(np.sqrt(np.mean(section ** 2))) < .001)
    record('tighten: the review reel has quiet gaps between labelled clips', all(gap_checks), str(gap_checks))

    variant = root / 'crossfade.md'
    code, output = tool('cut.py', 'tighten', root, 'int_01', '--pause', '.6', '--reel-limit', '3', '--out', variant)
    variant_data = json.loads((root / 'crossfade.tighten.json').read_text(encoding='utf-8'))
    selected = [row for row in variant_data['removals'] if row['crossfade_s']]
    record('tighten: a sufficiently clear pause can still use a compiler crossfade',
           code in (0, 1) and bool(selected), output)
    if not selected:
        return
    text = variant.read_text(encoding='utf-8')
    plan, _ = tighten.compile_text(text, root, source, cut, guard)
    item = selected[0]
    context = next((row for row in variant_data['reel_info']['clips'] if row['kind'] == 'AFTER'
                    and abs(row['event_start'] - item['start']) < .003), None)
    if context is None:
        record('tighten: crossfade comparison appears in the limited reel', False, json.dumps(variant_data))
        return
    with tempfile.TemporaryDirectory(prefix='lf-reel-test-') as temp:
        temp = Path(temp)
        reference_dir, comparison_dir = temp / 'reference', temp / 'comparison'
        reference_dir.mkdir()
        comparison_dir.mkdir()
        stream = (source.sources['int_01'].get('audio') or {}).get('index')
        edit = {'sources': {'int_01': {'file': str(source.path('int_01')), 'audio_stream': stream}},
                'audio': plan['audio']}
        clips = [{'src': 'int_01', 'speed': 1.0, 'start': 0, 'stop': source.duration('int_01')}]
        assemble.render_audio(cut.find_tool('ffmpeg'), cut.find_tool('ffprobe'), edit, root, clips,
                              plan['duration'], str(reference_dir), reference_dir, [])
        reference = decode(reference_dir / 'dialogue.wav')
        audio, _ = tighten.comparison_audio(source, 'int_01', item, plan, context['source_start'],
                                            context['source_end'], comparison_dir, cut)
        comparison = decode(audio)
        left, _ = tighten.audio_pair(plan, 'int_01', item['audio_start'], item['audio_end'])
        offset = float(left['at']) + context['source_start'] - float(left['in'])
        global_start = float(item['edit_at']) - .10
        local_start = global_start - offset
        width = int(.20 * RATE)
        a = reference[round(global_start * RATE):round(global_start * RATE) + width]
        b = comparison[round(local_start * RATE):round(local_start * RATE) + width]
        difference = float(np.max(np.abs(a - b))) if len(a) == len(b) == width else float('inf')
        record('tighten: AFTER uses the same samples and crossfade as the compiled audio track',
               difference < .00001, f'maximum sample difference {difference}')
        reel = decode(root / 'crossfade.tighten-reel.mp4')[::6]
        ref = reference[::6]
        rate = RATE // 6
        reference_start = round((float(item['edit_at']) - .4) * rate)
        reel_start = round((context['reel_start'] + context['picture_join'] - .4) * rate)
        target = ref[reference_start:reference_start + round(.8 * rate)]
        radius = round(.10 * rate)
        search_start = max(0, reel_start - radius)
        search = reel[search_start:reel_start + len(target) + radius]
        if len(target) and len(search) >= len(target):
            target = target - np.mean(target)
            products = np.correlate(search, target, mode='valid')
            squares = np.r_[0.0, np.cumsum(search.astype(np.float64) ** 2)]
            sums = np.r_[0.0, np.cumsum(search.astype(np.float64))]
            energy = squares[len(target):] - squares[:-len(target)]
            energy -= (sums[len(target):] - sums[:-len(target)]) ** 2 / len(target)
            correlation = products / np.sqrt(np.maximum(energy * np.sum(target ** 2), 1e-20))
            position = int(np.argmax(correlation))
            best = float(correlation[position])
            lag_ms = (search_start + position - reel_start) * 1000 / rate
        else:
            best = 0.0
            lag_ms = float('inf')
        record('tighten: the encoded AFTER clip preserves the rendered crossfade in context',
               best > .90 and abs(lag_ms) <= 25, f'correlation {best:.3f}, alignment {lag_ms:.1f} ms')
    limited = root / 'limited.md'
    code, output = tool('cut.py', 'tighten', root, 'int_01', '--pause', '.6', '--reel-limit', '1', '--out', limited)
    limited_data = json.loads((root / 'limited.tighten.json').read_text(encoding='utf-8'))
    record('tighten: a reel count limit discloses the omitted events', code in (0, 1)
           and limited_data['reel_info']['events'] == 1 and limited_data['reel_info']['total_events'] > 1
           and [row['kind'] for row in limited_data['reel_info']['clips']] == ['BEFORE', 'AFTER'],
           output)


def check_reel_bounds(record, scripts_dir):
    """A reel clip stays near its words when no quiet stretch is close, and holds every cut but few prompts."""
    spec = importlib.util.spec_from_file_location('reel_bounds_tighten', Path(scripts_dir) / 'tighten.py')
    tighten = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tighten)

    class Loud:
        """A recording with no quiet stretch anywhere (speech or a bed throughout)."""
        def quiet_runs(self, low, high):
            return []

        def quiet(self, low, high):
            return False

    words = [{'text': 'w', 'start': 10.0 + n * 0.5, 'end': 10.4 + n * 0.5} for n in range(400)]
    start, end = tighten.reel_context(words, {'start': 60.4, 'end': 60.6}, 300.0, Loud())
    record('tighten: with no quiet nearby a reel clip stays near its words (fading at their edges), not the whole '
           'recording', 58.0 <= start <= 59.5 and 61.4 <= end <= 63.0, f'{start:.2f}-{end:.2f}')


def check_picture_jumps(record, j, scripts_dir):
    """A box that moves during a removed pause makes that join score far above the shot's own frame-to-frame change;
    a join where nothing moved does not."""
    spec = importlib.util.spec_from_file_location('picture_jump_tighten', Path(scripts_dir) / 'tighten.py')
    tighten = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tighten)
    folder = Path(j('tighten-jumps'))
    folder.mkdir(parents=True, exist_ok=True)
    video = folder / 'moved.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=0x405060:s=320x180:r=25:d=4',
                    '-vf', "drawbox=x=20:y=60:w=60:h=60:color=white:t=fill:enable='lt(t,2)',"
                           "drawbox=x=220:y=60:w=60:h=60:color=white:t=fill:enable='gte(t,2)'",
                    '-c:v', 'ffv1', str(video)], check=True, capture_output=True)

    class Source:
        def has_video(self, alias):
            return True

        def path(self, alias):
            return video

    removals = [{'start': 1.8, 'end': 2.2}, {'start': 0.8, 'end': 1.0}, {'start': 0.02, 'end': 0.3},
                {'start': 0.0, 'end': 0.3}]
    tighten.picture_jumps(Source(), 'int_01', removals, tighten.load_cut())
    moved, still, near, first = (item.get('picture_jump') for item in removals)
    record('tighten: a join where the picture moved during the removed pause scores far above one where it did not',
           moved is not None and still is not None and moved >= 5 and still < 1.5, str(removals))
    record('tighten: a join with too little or no picture before it says it was not assessed, at the source edge',
           near is None and first is None
           and all('source edge' in item.get('picture_jump_unassessed', '') for item in removals[2:]),
           str(removals[2:]))


def run_tighten_cases(tool, record, j, scripts_dir):
    """Generate the edit, check safeguards, and measure all planted tones in a real render."""
    root = Path(j('tighten-project'))
    check_picture_jumps(record, j, scripts_dir)
    check_reel_bounds(record, scripts_dir)
    check_declared_busy(record, scripts_dir)
    check_filler_choice(record, scripts_dir)
    check_crossfade_guard(record, scripts_dir)
    check_partial_pause(record, scripts_dir)
    check_room_tone(tool, record, j, -50)
    check_room_tone(tool, record, j, -40)
    for kind in ('exponential', 'reverb', 'near-zero'):
        check_decay_tail(tool, record, j, kind, scripts_dir)
    check_music_bed(tool, record, j)
    media = make_fixture(Path(j('tighten-media')))
    code, output = tool('project.py', 'init', root, '--title', 'Synthetic tighten')
    code2, output2 = tool('map.py', 'add', root, media, '--role', 'interview')
    if code or code2:
        record('tighten: fixture setup', False, output + output2)
        return
    write_words(root)
    code, output = tool('cut.py', 'tighten', root, 'int_01')
    film = root / 'film.md'
    data_path = root / 'film.tighten.json'
    if code not in (0, 1) or not film.exists() or not data_path.exists():
        record('tighten: generate default paper edit and report', False, output)
        return
    default = film.read_text(encoding='utf-8')
    initial = json.loads(data_path.read_text(encoding='utf-8'))
    record('tighten: default keeps fillers and all words visible', '~~' not in default
           and all(text in default for text, _, _, _ in ROWS), default)
    flags = initial['untranscribed_sound']
    record('tighten: the planted untranscribed burst is flagged and retained',
           any(row['start'] <= BURST[0] + .02 and row['end'] >= BURST[1] - .02 for row in flags)
           and all(not (row['start'] < BURST[1] and row['end'] > BURST[0]) for row in initial['removals']),
           json.dumps(initial))
    record('tighten: every removal and flagged interval has a labelled reel',
           (root / 'film.tighten-reel.mp4').is_file() and (root / 'film.tighten-report.md').is_file(), output)
    report = (root / 'film.tighten-report.md').read_text(encoding='utf-8')
    record('tighten: the report warns that a steady bed may be cut as room tone',
           'bed can be mistaken for room tone and cut' in report, report[:400])
    before = film.read_bytes()
    protected, message = tool('cut.py', 'tighten', root, 'int_01', '--fillers', 'named')
    record('tighten: existing film is protected without --force', protected == 2 and film.read_bytes() == before,
           message)
    code, output = tool('cut.py', 'tighten', root, 'int_01', '--fillers', 'named', '--force', '--punch-in', '1.1')
    edited = film.read_text(encoding='utf-8') if film.exists() else ''
    data = json.loads(data_path.read_text(encoding='utf-8'))
    record('tighten: named filler is struck, and repeated words are only reported', code in (0, 1)
           and '~~um~~' in edited and 'echo echo' in edited
           and 'repeated echo echo' in (root / 'film.tighten-report.md').read_text(encoding='utf-8'), output)
    record('tighten: force retains the previous edit and alternate lines can punch in',
           (root / 'film.md.bak').read_bytes() == before and '{zoom 1.1}' in edited, edited)
    filler_rows = [row for row in data['removals'] if row['kind'] == 'filler']
    record('tighten: report includes the actual filler interval and duration',
           len(filler_rows) == 1 and filler_rows[0]['start'] < 1.15 and filler_rows[0]['end'] > 1.45,
           json.dumps(data['removals']))
    record('tighten: report distinguishes picture removal from the carried audio handles',
           bool(filler_rows) and filler_rows[0]['audio_start'] >= filler_rows[0]['start'] - .002
           and filler_rows[0]['audio_end'] <= filler_rows[0]['end'] + .002
           and (filler_rows[0]['crossfade_s'] is not None
                or 'short edge fades' in filler_rows[0]['sound']), json.dumps(filler_rows))
    check_code, check_output = tool('cut.py', 'check', root, '--json')
    try:
        check = json.loads(check_output)
    except ValueError:
        check = {}
    records = [line for line in check.get('lines', []) if line.get('kind') == 'spoken']
    runs = [run for line in records for run in line.get('runs', [])]
    by_words = {word['id'] for line in records for word in line.get('words', [])}
    expected = {f'int_01-w{index:06d}' for index in range(1, len(ROWS) + 1) if index != 2}
    record('tighten: compiler retains the intended word identities', check_code == 0 and by_words == expected,
           check_output[-1000:])
    gap_removals = [row for row in data['removals'] if row['kind'] == 'pause'
                    and 4.05 <= row['start'] and row['end'] <= 5.40]
    actual_gap = 5.40 - 4.05 - sum(row['end'] - row['start'] for row in gap_removals)
    record('tighten: a known quiet pause reaches the target within two frames',
           len(gap_removals) == 1 and abs(actual_gap - .35) <= .08, str(actual_gap))
    record('tighten: removal list agrees with compiled source ranges',
           len(data['removals']) == max(0, len(runs) - 1)
           and all(any(abs(run['out'] - row['start']) < .002 for run in runs)
                   and any(abs(run['in'] - row['end']) < .002 for run in runs) for row in data['removals']),
           json.dumps({'runs': runs, 'removals': data['removals']}))
    render_code, render_output = tool('cut.py', 'render', root, '--final')
    current_path = root / 'cuts' / 'current'
    current = current_path.read_text(encoding='utf-8').strip() if current_path.exists() else ''
    picture = root / 'cuts' / current / 'preview.mp4'
    if render_code not in (0, 1) or not picture.is_file():
        record('tighten: actual render for audio check', False, render_output[-2000:])
        return
    edit = json.loads((root / 'cuts' / current / 'edit.json').read_text(encoding='utf-8'))
    audio = sorted(edit['audio'], key=lambda item: item['at'])
    crossfades = [(left, right) for left, right in zip(audio, audio[1:])
                  if left.get('fade_out_curve') == 'qsin' and right.get('fade_in_curve') == 'qsin'
                  and left['at'] + left['out'] - left['in'] - right['at'] >= .099]
    expected_crossfades = sum(item['crossfade_s'] is not None for item in data['removals'])
    record('tighten: the rendered crossfades match the removal report',
           len(crossfades) == expected_crossfades, json.dumps(audio))
    samples = decode(picture)
    strengths = {freq: tone_strength(samples, freq) for _, _, _, freq in ROWS}
    strengths[BURST[2]] = tone_strength(samples, BURST[2])
    record('tighten: every kept word and the untranscribed burst survive in the decoded render',
           all(strengths[freq] > .12 for _, _, _, freq in ROWS if freq != 600) and strengths[BURST[2]] > .12,
           str(strengths))
    coverage = {freq: tone_coverage(samples, freq) for _, _, _, freq in ROWS if freq != 600}
    coverage[BURST[2]] = tone_coverage(samples, BURST[2])
    record('tighten: kept word tones and the burst retain their full planted duration within 40 ms',
           all(coverage[freq] >= end - start - .04 for _, start, end, freq in ROWS if freq != 600)
           and coverage[BURST[2]] >= BURST[1] - BURST[0] - .04, str(coverage))
    record('tighten: the removed filler tone is absent from the decoded render', strengths[600] < .025,
           str(strengths))
    check_reel_pairs(tool, record, root, scripts_dir)
    quick = Path(j('quick-tight.mp4'))
    quick_code, quick_output = tool('tighten.py', media, '--out', quick, '--silence-only')
    quick_report = quick.with_name('quick-tight.tighten-report.md')
    quick_data = quick.with_name('quick-tight.tighten.json')
    record('tighten: one-file silence-only path renders, checks and keeps a revision project',
           quick_code in (0, 1) and quick.is_file() and quick_report.is_file() and quick_data.is_file()
           and quick.with_name('quick-tight.tighten-checks.json').is_file() and 'Revision project:' in quick_output,
           quick_output[-2000:])
    if quick_report.exists() and quick_data.exists():
        record('tighten: silence-only reports untranscribed sound as not assessed',
               'Not assessed: no transcript' in quick_report.read_text(encoding='utf-8')
               and json.loads(quick_data.read_text(encoding='utf-8'))['untranscribed_sound_assessed'] is False,
               quick_output[-1000:])
