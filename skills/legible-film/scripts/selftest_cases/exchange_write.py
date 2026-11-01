"""Synthetic render and timeline export checks; these do not prove an editor can import the result."""
import importlib.util
import json
import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path, PurePosixPath

from PIL import Image


def make_media(path, tone):
    """Make a small source whose supplied transcript is independent of its tone."""
    colour = {500: 'red', 600: 'blue', 700: 'green', 800: 'yellow'}[tone]
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
               'testsrc2=size=160x90:rate=25:duration=8', '-f', 'lavfi', '-i',
               f'sine=frequency={tone}:sample_rate=48000:duration=8', '-vf',
               f'drawbox=x=0:y=0:w=45:h=45:color={colour}:t=fill', '-c:v', 'mpeg4', '-threads', '1',
               '-c:a', 'aac', '-ac', '2', '-shortest', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(result.stderr[-1000:])


def fixture(tool, root, fps='25'):
    """Render a project with words, a cutaway, a title, carries, a dissolve, crop and speed."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    code, output = tool('project.py', 'init', root, '--title', 'Synthetic export')
    if code:
        raise RuntimeError(output)
    media = root / 'media with caf\u00e9'
    media.mkdir(exist_ok=True)
    for number in range(1, 5):
        make_media(media / f'source {number}.mp4', 400 + number * 100)
    still = media / 'still caf\u00e9.png'
    Image.new('RGB', (160, 90), 'purple').save(still)
    music = media / 'music.wav'
    result = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                             'sine=frequency=220:sample_rate=48000:duration=8', '-ac', '2', str(music)],
                            capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace')[-500:])
    code, output = tool('map.py', 'add', root, *(media / f'source {number}.mp4' for number in range(1, 4)),
                        '--role', 'interview')
    if code:
        raise RuntimeError(output)
    for kind, path in (('still', still), ('music', music)):
        code, output = tool('map.py', 'add', root, path, '--role', kind)
        if code:
            raise RuntimeError(output)
    code, output = tool('map.py', 'add', root, media / 'source 4.mp4', '--role', 'broll')
    if code:
        raise RuntimeError(output)
    index = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))
    ranges = [(0.5, 0.9), (1.2, 1.6), (2.0, 2.4), (4.0, 4.4), (4.8, 5.2), (5.6, 6.0)]
    for number, source in enumerate(index['sources'][:3], 1):
        alias = source['alias']
        letter = 'abc'[number - 1]
        rows = [{'id': f'{alias}-w{i + 1:06d}', 'text': f'{letter}{i}', 'start': start, 'end': end,
                 'estimated': False} for i, (start, end) in enumerate(ranges)]
        directory = root / 'map' / alias
        directory.mkdir(exist_ok=True)
        transcript = {'version': 1, 'source': alias, 'words': rows,
                      'media': {'sha256': source['sha256'], 'audio_stream': source['audio']['index']}}
        (directory / 'words.json').write_text(json.dumps(transcript), encoding='utf-8')
    film = (f'---\ntitle: Export fixture\nsize: 160x90\nfps: {fps}\ncaptions: srt\n---\n'
            '- music music_01 0:00-0:08 -18dB\n'
            '> int_01 0:00.30-0:02.70 a0 ~~a1~~ a2 {tail 0.6}\n'
            '  ~ broll_01 0:01.00-0:02.00 +0.41 Cutaway\n'
            '  ~ title "Fixture" 1.0 lower +0.2\n'
            '> int_02 0:00.30-0:02.70 b0 b1 b2\n'
            '> int_03 0:03.40-0:06.50 c3 c4 c5 {lead 0.4}\n'
            '> int_02 0:03.40-0:06.30 b3 b4 b5 {dissolve 0.6}\n'
            '- broll_01 0:01.00-0:02.50 x1.5 crop 0.4,0.5 Sped picture\n'
            '- still still_01 1.0 Purple image\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    code, output = tool('cut.py', 'render', root)
    if code not in (0, 1) or not (root / 'cuts' / 'v001' / 'edit.json').is_file():
        raise RuntimeError(output[-3000:])
    return root, output


def inspect_fixture(tool, record, root, fps):
    """Check a written XML against the rendered version's known lines, notes, tracks and words."""
    version = root / 'cuts' / 'v001'
    lines = json.loads((version / 'lines.json').read_text(encoding='utf-8'))
    note = {'version': 1, 'notes': [{'id': 'n1', 'version': 'v001', 't': 1.0, 'status': 'open',
                                     'origin': 'room', 'text': 'Inspect this moment'},
                                    {'id': 'n2', 'version': 'v001', 't': 2.0, 'status': 'resolved',
                                     'origin': 'room', 'text': 'Do not include'}]}
    (root / 'notes.json').write_text(json.dumps(note), encoding='utf-8')
    output = root.parent / ('handoff-' + fps.replace('/', '-') + '.xml')
    code, text = tool('exchange.py', 'write', root, 'v001', '--out', output)
    record(f'exchange write {fps}: writes the XML, SRT and notes, with application-test boundary',
           code == 0 and output.is_file() and output.with_suffix('.srt').read_bytes()
           == (version / 'captions.srt').read_bytes() and output.with_suffix('.notes.txt').is_file()
           and 'OpenTimelineIO' in text and 'not yet tested' in text
           and 'render-time source identity' in text and 'could not be verified' in text, text[-1000:])
    if code:
        return
    tree = ET.parse(output)
    sequence = tree.find('.//sequence')
    picture = sequence.findall('media/video/track')
    audio = sequence.findall('media/audio/track')
    markers = sequence.findall('marker')
    rate = sequence.find('rate')
    expected_base = 30 if '/' in fps else 25
    expected_ntsc = 'TRUE' if '/' in fps else 'FALSE'
    record(f'exchange write {fps}: sequence rate, original paths, V1/V2/V3 and linked stereo channels',
           rate.findtext('timebase') == str(expected_base) and rate.findtext('ntsc') == expected_ntsc
           and len(picture) >= 3 and len(picture[0].findall('clipitem')) >= 4
           and len(picture[1].findall('clipitem')) == 2 and len(picture[2].findall('clipitem')) == 1
           and len(audio) >= 3 and len(audio[0].findall('clipitem')) == len(audio[1].findall('clipitem'))
           and {item.findtext('sourcetrack/trackindex') for item in audio[0].findall('clipitem')} == {'1'}
           and {item.findtext('sourcetrack/trackindex') for item in audio[1].findall('clipitem')} == {'2'}
           and all(item.findall('link') for item in audio[0].findall('clipitem')),
           f'video={len(picture)}, audio={len(audio)}')
    # From an editor's Premiere test of 2.0: without these the sequence came in as PAL-601 and stereo as mono.
    sample = sequence.find('media/video/format/samplecharacteristics')
    pans = [(item.findtext('sourcetrack/trackindex'), item.findtext('filter/effect/effectid'),
             item.findtext('filter/effect/parameter/value')) for track in audio for item in track.findall('clipitem')]
    notes_text = output.with_suffix('.notes.txt').read_text(encoding='utf-8')
    record(f'exchange write {fps}: a square-pixel progressive sequence, and each stereo channel panned to its side',
           sample.findtext('pixelaspectratio') == 'square' and sample.findtext('anamorphic') == 'FALSE'
           and sample.findtext('fielddominance') == 'none' and pans
           and all(effect == 'audiopan' and value == ('-1' if channel == '1' else '1')
                   for channel, effect, value in pans)
           and 'panned left' in notes_text and 'square-pixel' in notes_text, str(pans) + notes_text[:400])
    urls = [node.text for node in tree.findall('.//file/pathurl')]
    original = [url for url in urls if 'source%20' in url]
    record(f'exchange write {fps}: full source duration and escaped Unicode and spaces',
           len(original) == 4 and all('caf%C3%A9' in url and '%20' in url for url in original)
           and all(int(node.findtext('duration')) == 200 for node in tree.findall('.//file')
                   if 'source%20' in (node.findtext('pathurl') or '')),
           str(original))
    if '/' in fps:
        record('exchange write: mixed source rate stays on the file and picture while audio uses sequence rate',
               all(node.findtext('rate/timebase') == '25' and node.findtext('rate/ntsc') == 'FALSE'
                   for node in tree.findall('.//file') if 'source%20' in (node.findtext('pathurl') or ''))
               and all(node.findtext('rate/timebase') == '25' and node.findtext('rate/ntsc') == 'FALSE'
                       for track in picture for node in track.findall('clipitem'))
               and all(node.findtext('rate/timebase') == '30' and node.findtext('rate/ntsc') == 'TRUE'
                       for track in audio for node in track.findall('clipitem'))
               and 'mixed-rate editor conform is not verified' in text, text[-500:])
    note_text = output.with_suffix('.notes.txt').read_text(encoding='utf-8')
    spoken_line = next(line for line in lines['lines'] if line.get('kind') == 'spoken')
    marker_count = sum(bool(line.get('text') or line.get('words')) for line in lines['lines'])
    record(f'exchange write {fps}: line and open-note markers, and only the clip actually cropped and the speed change '
           'named as not carried',
           any(node.findtext('name') == 'Note n1' and node.findtext('comment') == 'room: "Inspect this moment"'
               for node in markers) and not any(node.findtext('name') == 'Note n2' for node in markers)
           and any(node.findtext('name') == f"Line {spoken_line['line']}" and node.findtext('comment') == 'a0 a2'
                   for node in markers)
           and 'a1' not in picture[0].find('clipitem/name').text
           and len([node for node in markers if node.findtext('name', '').startswith('Line ')]) == marker_count
           and note_text.count('crop, zoom or reframe') == 1 and 'speed x1.5' in note_text, note_text)
    trans = audio[0].findall('transitionitem')
    carry = [item.findtext('name', '') for track in audio[2:] for item in track.findall('clipitem')]
    record(f'exchange write {fps}: transition handles and J/L audio are present',
           len(trans) == 1 and int(trans[0].findtext('end')) > int(trans[0].findtext('start'))
           and any(' tail' in name for name in carry) and any(' lead' in name for name in carry)
           and len(picture[0].findall('transitionitem')) == 1, str(carry))
    record(f'exchange write {fps}: original still on V2 and music on separate audio tracks',
           any('still%20caf%C3%A9.png' in url for url in urls)
           and any('gen-still-still_01' in item.findtext('name', '') for item in picture[1].findall('clipitem'))
           and any('music_01' in item.findtext('name', '') for track in audio[2:]
                   for item in track.findall('clipitem')), str(urls) + str(carry))
    cutaway_start = int(picture[1].find('clipitem/start').text)
    declared = json.loads((version / 'declared.json').read_text(encoding='utf-8'))
    raw_cut = min(declared['cuts'], key=lambda value: abs(value - 0.41))
    expected_cut = math.ceil(raw_cut * float(Fraction(fps)) - 1e-12)
    select = f'select=eq(n\\,{cutaway_start - 1})+eq(n\\,{cutaway_start})'
    decode = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(version / 'preview.mp4'), '-vf', select,
                             '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                            capture_output=True)
    stride = 160 * 90 * 3
    pixel = (10 * 160 + 10) * 3
    before = decode.stdout[pixel:pixel + 3]
    after = decode.stdout[stride + pixel:stride + pixel + 3]
    report = json.loads((version / 'assemble-report.json').read_text(encoding='utf-8'))
    picture_snap = next(row for row in report['snaps'] if row.get('clock') == 'source edit time')
    picture_in = int(picture[0].find('clipitem/pproTicksIn').text) / 254016000000
    first_run = next(line['runs'][0] for line in lines['lines'] if line.get('runs'))
    audio_in = int(audio[0].find('clipitem/pproTicksIn').text) / 254016000000
    audio_first = audio[0].find('clipitem')
    audio_grid_in = int(audio_first.findtext('in')) / float(Fraction(fps))
    audio_grid_out = audio_grid_in + (int(audio_first.findtext('end')) - int(audio_first.findtext('start'))) \
        / float(Fraction(fps))
    record(f'exchange write {fps}: XML picture cut matches decoded render and audio ticks keep source samples',
           cutaway_start == expected_cut and len(before) == len(after) == 3
           and before[0] > 150 and before[1] < 100 and after[0] > 150 and after[1] > 130
           and abs(picture_in - picture_snap['covering_frame_pts']) < 1e-6
           and abs(audio_in - first_run['in']) < 1 / 48000,
           f'cut={cutaway_start}, expected={expected_cut}, pixels={list(before)}/{list(after)}, '
           f'picture in={picture_in}, audio in={audio_in}, ffmpeg={decode.stderr[-200:]}')
    tolerance = 0.5 / float(Fraction(fps)) + 1e-7
    record(f'exchange write {fps}: frame-grid audio endpoints stay within half a frame of the saved source ticks',
           abs(audio_grid_in - first_run['in']) <= tolerance and abs(audio_grid_out - first_run['out']) <= tolerance,
           f"grid={audio_grid_in:.6f}-{audio_grid_out:.6f}, source={first_run['in']}-{first_run['out']}")
    read_file = root.parent / ('read-' + fps.replace('/', '-') + '.json')
    words_file = root.parent / ('words-' + fps.replace('/', '-') + '.json')
    read_code, read_text = tool('exchange.py', 'read', output, '--json', read_file)
    word_code, word_text = tool('exchange.py', 'words', output, '--project', root, '--json', words_file)
    read = json.loads(read_file.read_text(encoding='utf-8'))
    words = json.loads(words_file.read_text(encoding='utf-8'))['words']
    expected = [word for line in lines['lines'] for word in line.get('words', [])]
    caption_data = json.loads((version / 'captions.json').read_text(encoding='utf-8'))
    caption_words = [word for cue in caption_data['cues'] for word in cue.get('words', [])]
    run_count = sum(len(line.get('runs', [])) for line in lines['lines'])
    tolerance = 0.5 / float(Fraction(fps)) + 0.00011
    agrees = len(words) == len(expected) and all(
        actual['id'] == wanted['id'] and actual['text'] == wanted['text']
        and abs(actual['start'] - wanted['start']) <= tolerance
        and abs(actual['end'] - wanted['end']) <= tolerance for actual, wanted in zip(words, expected))
    captions_agree = [(word['id'], word['text']) for word in caption_words] == [
        (word['id'], word['text']) for word in expected]
    record(f'exchange write {fps}: read, words and captions preserve kept words within half a frame',
           read_code == word_code == 0 and len(read['clips']) == run_count and len(read['transitions']) == 1
           and agrees and captions_agree and 'a1' not in [word['text'] for word in words],
           read_text + word_text + str([(row['text'], row['start']) for row in words]))
    relative = output.with_name(output.stem + '-relative.xml')
    rel_code, rel_text = tool('exchange.py', 'write', root, 'v001', '--out', relative, '--relative')
    rel_words, rel_out = tool('exchange.py', 'words', relative, '--project', root)
    rel_urls = [node.text for node in ET.parse(relative).findall('.//file/pathurl')]
    record(f'exchange write {fps}: relative source paths resolve from the XML folder',
           rel_code == rel_words == 0 and all(not url.startswith('file:') for url in rel_urls)
           and f'{len(expected)} words placed' in rel_out, rel_text[-500:] + rel_out)
    missing = root / 'media with caf\u00e9' / 'source 1.mp4'
    hidden = missing.with_suffix('.unavailable')
    missing.rename(hidden)
    try:
        bad_output = output.with_name(output.stem + '-missing.xml')
        bad_code, bad_text = tool('exchange.py', 'write', root, 'v001', '--out', bad_output)
    finally:
        hidden.rename(missing)
    record(f'exchange write {fps}: missing original source exits 2 before writing',
           bad_code == 2 and not bad_output.exists() and ('missing' in bad_text.lower() or
                                                            'registered original' in bad_text.lower()), bad_text)
    # Any version folder is immutable, not only the one exported: a hand-off aimed inside another one is refused.
    other = root / 'cuts' / 'v009'
    other.mkdir(parents=True, exist_ok=True)
    (other / 'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nkept\n', encoding='utf-8')
    inside_code, inside_text = tool('exchange.py', 'write', root, 'v001', '--out', other / 'captions.xml')
    record(f'exchange write {fps}: a hand-off inside another version folder is refused and changes nothing there',
           inside_code == 2 and not (other / 'captions.xml').exists()
           and (other / 'captions.srt').read_text(encoding='utf-8').endswith('kept\n'), inside_text[-300:])
    for path in (other / 'captions.srt', other):
        path.unlink() if path.is_file() else path.rmdir()
    # Another project's versions are just as immutable.
    elsewhere = root.parent / f'other project {fps.replace("/", "-")}'
    (elsewhere / 'cuts' / 'v001').mkdir(parents=True, exist_ok=True)
    (elsewhere / 'status.json').write_text('{}', encoding='utf-8')
    (elsewhere / 'cuts' / 'v001' / 'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nmine\n',
                                                             encoding='utf-8')
    cross_code, cross_text = tool('exchange.py', 'write', root, 'v001', '--out',
                                  elsewhere / 'cuts' / 'v001' / 'captions.xml')
    record(f'exchange write {fps}: a hand-off inside another project\'s version folder is refused',
           cross_code == 2 and not (elsewhere / 'cuts' / 'v001' / 'captions.xml').exists()
           and (elsewhere / 'cuts' / 'v001' / 'captions.srt').read_text(encoding='utf-8').endswith('mine\n'),
           cross_text[-300:])


def overlay_case(tool, record, root):
    """Future spatial overlay fields are explicitly listed, rather than silently discarded."""
    original = root / 'cuts' / 'v001'
    altered = root / 'cuts' / 'v002'
    shutil.copytree(original, altered)
    edit_file = altered / 'edit.json'
    edit = json.loads(edit_file.read_text(encoding='utf-8'))
    edit['overlays'][0]['pin'] = {'track': 'synthetic'}
    edit['overlays'][0]['behind'] = 'synthetic'
    edit['overlays'].append({'kind': 'blur', 'from': 0, 'to': 1})
    edit_file.write_text(json.dumps(edit), encoding='utf-8')
    output = root.parent / 'spatial-omissions.xml'
    code, text = tool('exchange.py', 'write', root, 'v002', '--out', output)
    report = output.with_suffix('.notes.txt').read_text(encoding='utf-8') if output.is_file() else text
    record('exchange write: pin, behind and blur are named when present',
           code == 0 and all(term in report.lower() for term in ('pin', 'behind', 'blur')), report[-1000:])


def source_identity_case(tool, record, root):
    """Render-time identity catches size changes by default and same-size changes with --verify."""
    version = root / 'cuts' / 'v003'
    shutil.copytree(root / 'cuts' / 'v001', version)
    manifest_file = version / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    index = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))
    manifest['sources'] = {row['alias']: {'path': row['path'], 'bytes': row['bytes'], 'sha256': row['sha256'],
                                           'audio_stream': (row.get('audio') or {}).get('index')}
                           for row in index['sources']}
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    output = root.parent / 'identity-original.xml'
    original_code, original_text = tool('exchange.py', 'write', root, 'v003', '--out', output, '--verify')
    source = root / 'media with caf\u00e9' / 'source 1.mp4'
    original = source.read_bytes()
    changed = bytearray(original)
    changed[len(changed) // 2] ^= 1
    try:
        source.write_bytes(changed)
        same_code, same_text = tool('exchange.py', 'write', root, 'v003', '--out',
                                    root.parent / 'identity-same-size.xml')
        hash_path = root.parent / 'identity-wrong-hash.xml'
        hash_code, hash_text = tool('exchange.py', 'write', root, 'v003', '--out', hash_path, '--verify')
        source.write_bytes(original + b'X')
        size_path = root.parent / 'identity-wrong-size.xml'
        size_code, size_text = tool('exchange.py', 'write', root, 'v003', '--out', size_path)
    finally:
        source.write_bytes(original)
    record('exchange write: manifest size guard and optional SHA-256 guard use render-time identity',
           original_code == 0 and same_code == 0 and hash_code == size_code == 2
           and 'int_01' in hash_text and 'sha-256' in hash_text.lower()
           and 'int_01' in size_text and 'size' in size_text.lower()
           and not hash_path.exists() and not size_path.exists(),
           original_text[-300:] + same_text[-300:] + hash_text[-300:] + size_text[-300:])


def invalid_rate_case(tool, record, root):
    """A malformed rational rate is a refusal, not a traceback or partial hand-off."""
    version = root / 'cuts' / 'v004'
    shutil.copytree(root / 'cuts' / 'v001', version)
    edit_file = version / 'edit.json'
    edit = json.loads(edit_file.read_text(encoding='utf-8'))
    edit['fps'] = '0/0'
    edit_file.write_text(json.dumps(edit), encoding='utf-8')
    output = root.parent / 'invalid-rate.xml'
    code, text = tool('exchange.py', 'write', root, 'v004', '--out', output)
    record('exchange write: a malformed rational rate exits 2 before writing',
           code == 2 and not output.exists() and 'cannot run' in text, text[-300:])


def run_exchange_write_cases(tool, record, j, scripts_dir):
    """Render and round-trip two rates using only offline core dependencies."""
    spec = importlib.util.spec_from_file_location('lf_exchange_write_test', Path(scripts_dir) / 'exchange.py')
    exchange = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exchange)
    centred = {'fit': 'cover', 'crop': {'path': [[0, 0.5, 0.5]], 'zoom': 1.0}}
    upright = {'video': {'width': 1920, 'height': 1080, 'side_data_list': [{'rotation': -90}]}}
    landscape = {'video': {'width': 1920, 'height': 1080}}
    record('exchange write: a phone clip stored wide but shown tall is noted as reframed in a wide sequence; a '
           'centred clip of the sequence\'s shape is not',
           exchange.framing_changed(centred, upright, [1920, 1080]) is True
           and exchange.framing_changed(centred, landscape, [1920, 1080]) is False,
           str((exchange.framing_changed(centred, upright, [1920, 1080]),
                exchange.framing_changed(centred, landscape, [1920, 1080]))))
    mono = {'id': 'file-1', 'path': Path(j('mono.wav')), 'rate': Fraction(25), 'duration': 2.0, 'video': {},
            'audio': {'sample_rate': 48000}, 'channels': 1}
    track = ET.Element('track')
    exchange.append_clip(track, {'id': 'clip-1', 'name': 'mono', 'kind': 'audio', 'src': 'mono', 'start': 0.0,
                                 'end': 1.0, 'in': 0.0, 'out': 1.0, 'links': [], 'channel': 1},
                         mono, Fraction(25), Path(j()), False, set(), None, None, [])
    record('exchange write: a mono source stays centred (no pan)',
           track.find('clipitem') is not None and track.find('clipitem/filter') is None,
           ET.tostring(track, encoding='unicode')[:300])
    late = exchange.stream_notes('int_01', {'start_time': '0.033333', 'sample_aspect_ratio': '1:1'},
                                 {'start_time': '0.000000'}, Fraction(30))
    level = exchange.stream_notes('int_01', {'start_time': '0.000000', 'sample_aspect_ratio': '1:1'},
                                  {'start_time': '0.000000'}, Fraction(30))
    wide = exchange.stream_notes('int_01', {'start_time': '0', 'sample_aspect_ratio': '4:3'}, {}, Fraction(25))
    record('exchange write: a picture starting 33 ms after its sound, and non-square pixels, are named; level '
           'streams are not',
           len(late) == 1 and '33 ms after' in late[0] and not level
           and len(wide) == 1 and 'non-square pixels (4:3)' in wide[0], str((late, level, wide)))
    mac_uri = PurePosixPath('/Volumes/Shared caf\u00e9/shot 1.mov').as_uri()
    record('exchange write: macOS absolute file URL uses localhost and escapes spaces and Unicode',
           exchange.localhost_file_url(mac_uri) == 'file://localhost/Volumes/Shared%20caf%C3%A9/shot%201.mov',
           exchange.localhost_file_url(mac_uri))
    for name, fps in (('integer', '25'), ('ntsc', '30000/1001')):
        try:
            root, output = fixture(tool, j(name, 'export project'), fps)
        except (OSError, RuntimeError, ValueError, KeyError) as error:
            record(f'exchange write {fps}: synthetic project renders', False, str(error))
            continue
        record(f'exchange write {fps}: synthetic project renders',
               (root / 'cuts' / 'v001' / 'edit.json').is_file(), output[-300:])
        source = {'path': root / 'media with caf\u00e9' / 'source 1.mp4', 'rate': Fraction(25),
                  'sequence_rate': Fraction(fps), 'video': {'time_base': '1/12800'}, 'origin': 0.0}
        selected = exchange.covering_picture(source, 0.31995, 0.32)
        record(f'exchange write {fps}: a report frame just ahead of the actual sample is not chosen',
               abs(selected - 0.28) < 1e-6, str(selected))
        inspect_fixture(tool, record, root, fps)
        if name == 'integer':
            overlay_case(tool, record, root)
            source_identity_case(tool, record, root)
            invalid_rate_case(tool, record, root)
