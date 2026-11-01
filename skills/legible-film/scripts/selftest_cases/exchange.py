"""Known-answer cases for exchange.py on hand-built Final Cut Pro 7 XML (the shape Premiere Pro exports)."""
import hashlib
import json
from pathlib import Path

TPS = 254016000000
FRAME_TICKS = 10594584000  # one frame at 24000/1001


def clip(start, end, src_in, src_out, extra=''):
    """A clipitem on the dialogue track; source positions in frames, written as pproTicks too."""
    return (f'<clipitem id="c{start}"><name>clip</name><enabled>TRUE</enabled>'
            f'<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><start>{start}</start><end>{end}</end>'
            f'<in>{src_in}</in><out>{src_out}</out><pproTicksIn>{src_in * FRAME_TICKS}</pproTicksIn>'
            f'<pproTicksOut>{src_out * FRAME_TICKS}</pproTicksOut><file id="f1"/>{extra}</clipitem>')


def transition(start, end):
    """A centred one-frame-cut crossfade."""
    return (f'<transitionitem><start>{start}</start><end>{end}</end><alignment>center</alignment>'
            f'<cutPointTicks>{FRAME_TICKS}</cutPointTicks><effect><effectid>KGAudioTransCrossFade0dB</effectid>'
            '</effect></transitionitem>')


def timeline(items, duration):
    """A sequence at 24000/1001 with one file (media/a.mov) and the given dialogue-track items."""
    return ('<?xml version="1.0"?><xmeml version="4"><sequence><name>s</name>'
            f'<duration>{duration}</duration><rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate>'
            '<media><video><track/></video><audio><track>'
            '<clipitem id="def"><name>x</name><enabled>FALSE</enabled><start>9000</start><end>9001</end><in>0</in>'
            '<out>1</out><file id="f1"><name>a.mov</name><pathurl>file://localhost/media/a.mov</pathurl>'
            '<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate></file></clipitem>'
            + ''.join(items) + '</track></audio></media></sequence></xmeml>')


def check_identity_and_stale_transcripts(tool, record, j):
    """Identical local IDs in two recordings remain different, and stale project words never map."""
    source_a = Path(j('identity-a.wav'))
    source_b = Path(j('identity-b.wav'))
    source_a.write_bytes(b'synthetic recording A')
    source_b.write_bytes(b'synthetic recording B')
    first = Path(j('identity-first.xml'))
    second = Path(j('identity-second.xml'))
    first.write_text(sequence_xml([(True, [plain_clip(0, 30, 0, 30,
                     file_xml('f1', '/' + source_a.resolve().as_posix()))])], 30, 30, False), encoding='utf-8')
    second.write_text(sequence_xml([(True, [plain_clip(0, 30, 0, 30,
                      file_xml('f2', '/' + source_b.resolve().as_posix()))])], 30, 30, False), encoding='utf-8')
    words = Path(j('identity-two.json'))
    groups = [{'id': 'A', 'media_reference': str(source_a),
               'words': [{'id': 'w1', 'text': 'alpha', 'start': .1, 'end': .3}]},
              {'id': 'B', 'media_reference': str(source_b),
               'words': [{'id': 'w1', 'text': 'beta', 'start': .1, 'end': .3}]}]
    words.write_text(json.dumps({'sources': groups}), encoding='utf-8')
    srt = Path(j('identity-caption.srt'))
    srt.write_text('1\n00:00:00,100 --> 00:00:00,300\nalpha\n', encoding='utf-8')
    report = Path(j('identity-compare.json'))
    code, output = tool('exchange.py', 'compare', first, second, '--words', words, '--captions', srt,
                        '--json', report)
    data = load_report(report)
    record('exchange: A/w1 alpha and B/w1 beta are different words and the alpha caption is removed',
           code == 1 and data.get('complete') is True and data.get('words_cut') == ['A:w1']
           and data.get('words_added') == ['B:w1']
           and [row['status'] for row in data.get('captions', [])] == ['removed'], str(data)[:900] + output)
    rows_out = Path(j('identity-placed.json'))
    placed_code, placed_output = tool('exchange.py', 'words', first, '--words', words, '--json', rows_out)
    placed = load_report(rows_out)
    rows = placed.get('words') or [{}]
    record('exchange: edit-time words keep the local id and expose the source-scoped identity',
           placed_code == 0 and rows[0].get('id') == 'w1' and rows[0].get('source') == 'A'
           and rows[0].get('identity') == 'A:w1', str(placed)[:700] + placed_output)
    record('exchange: an unbound transcript still maps and its match discloses missing media provenance',
           placed_code == 0 and 'does not record' in str(placed.get('matches', [])).lower(),
           str(placed.get('matches')) + placed_output)

    duplicate = Path(j('identity-duplicate.json'))
    duplicate.write_text(json.dumps({'source': 'A', 'media_reference': str(source_a), 'words': [
        {'id': 'w1', 'text': 'alpha', 'start': .1, 'end': .3},
        {'id': 'w1', 'text': 'beta', 'start': .4, 'end': .6}]}), encoding='utf-8')
    duplicate_alias = Path(j('identity-duplicate-alias.json'))
    duplicate_alias.write_text(json.dumps({'source': 'A', 'media_reference': str(source_a), 'words': [
        {'id': 'w9', 'text': 'gamma', 'start': .1, 'end': .3}]}), encoding='utf-8')
    duplicate_code, duplicate_out = tool('exchange.py', 'words', first, '--words', duplicate)
    alias_code, alias_out = tool('exchange.py', 'words', first, '--words', words, '--words', duplicate_alias)
    record('exchange: duplicate word IDs and duplicate source aliases fail with the file named',
           duplicate_code == alias_code == 2 and str(duplicate) in duplicate_out
           and str(duplicate_alias) in alias_out and 'alias' in alias_out.lower(),
           duplicate_out + alias_out)
    escaped = Path(j('identity-escaped.json'))
    escaped.write_text(json.dumps({'sources': [
        {'id': 'A:B', 'media_reference': str(source_a),
         'words': [{'id': 'w1', 'text': 'alpha', 'start': .1, 'end': .3}]},
        {'id': 'A', 'media_reference': str(source_b),
         'words': [{'id': 'B:w1', 'text': 'beta', 'start': .1, 'end': .3}]}]}), encoding='utf-8')
    escaped_report = Path(j('identity-escaped-compare.json'))
    escaped_code, escaped_out = tool('exchange.py', 'compare', first, second, '--words', escaped,
                                     '--json', escaped_report)
    escaped_result = load_report(escaped_report)
    record('exchange: source and word IDs containing the separator cannot collide',
           escaped_code == 1 and escaped_result.get('words_cut') == ['A%3AB:w1']
           and escaped_result.get('words_added') == ['A:B%3Aw1'], str(escaped_result)[:500] + escaped_out)

    root = media_project(j('identity-stale-project'), [('int_01', 'source.wav', b'old recording',
                                                         [('old word', .1, .3)])])
    transcript_path = root / 'map' / 'int_01' / 'words.json'
    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    transcript['media'] = {'sha256': hashlib.sha256(b'old recording').hexdigest(), 'audio_stream': 0}
    transcript_path.write_text(json.dumps(transcript), encoding='utf-8')
    media = root / 'source.wav'
    media.write_bytes(b'new recording')
    stale_xml = Path(j('identity-stale.xml'))
    stale_xml.write_text(sequence_xml([(True, [plain_clip(0, 30, 0, 30,
                         file_xml('f1', '/' + media.resolve().as_posix()))])], 30, 30, False), encoding='utf-8')
    stale_report = Path(j('identity-stale-words.json'))
    stale_code, stale_out = tool('exchange.py', 'words', stale_xml, '--project', root, '--json', stale_report)
    stale = load_report(stale_report)
    compared = Path(j('identity-stale-compare.json'))
    compare_code, compare_out = tool('exchange.py', 'compare', stale_xml, stale_xml, '--project', root,
                                     '--json', compared)
    result = load_report(compared)
    why = str(stale.get('unmatched', []))
    record('exchange: stale transcript is not placed, even before the map index is refreshed',
           stale_code == 1 and not stale.get('words') and 'stale' in why.lower()
           and '--retranscribe' in why and 'confirm-words' in why, why + stale_out)
    record('exchange: stale words are unknown, never cut, and the comparison is incomplete',
           compare_code == 1 and result.get('complete') is False and not result.get('words_cut')
           and result.get('words_unknown') == ['int_01:int_01-w000001'], str(result)[:900] + compare_out)
    mapped_code, mapped_out = tool('exchange.py', 'words', stale_xml, '--project', root, '--map', 'source.wav=int_01')
    record('exchange: explicit mapping does not override a known stale transcript',
           mapped_code == 1 and 'stale' in mapped_out.lower(), mapped_out)
    current_hash = hashlib.sha256(media.read_bytes()).hexdigest()
    transcript['media'] = {'sha256': current_hash, 'audio_stream': 0,
                           'confirmation': {'by': 'agent', 'note': 'checked the rewrap',
                                            'previous_media': {'sha256': hashlib.sha256(b'old recording').hexdigest(),
                                                               'audio_stream': 0}}}
    transcript_path.write_text(json.dumps(transcript), encoding='utf-8')
    index_path = root / 'map' / 'sources.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    index['sources'][0].update(sha256=current_hash, audio={'index': 0})
    index_path.write_text(json.dumps(index), encoding='utf-8')
    confirmed_report = Path(j('identity-confirmed-match.json'))
    confirmed_code, confirmed_out = tool('exchange.py', 'words', stale_xml, '--project', root,
                                         '--json', confirmed_report)
    matches = load_report(confirmed_report).get('matches', [])
    how = matches[0]['by'] if matches else ''
    record('exchange: a checked rebind is described as confirmed, with its actor',
           confirmed_code == 0 and 'confirmed' in how.lower() and 'agent' in how.lower(), how + confirmed_out)
    transcript['media'] = {'sha256': current_hash, 'audio_stream': None}
    transcript_path.write_text(json.dumps(transcript), encoding='utf-8')
    no_stream_code, no_stream_out = tool('exchange.py', 'words', stale_xml, '--project', root)
    record('exchange: a bound transcript with unknown audio stream is not treated as current',
           no_stream_code == 1 and 'stale' in no_stream_out.lower() and 'stream' in no_stream_out.lower(),
           no_stream_out)


def check_transition_word_uncertainty(tool, record, j):
    """Unmeasured transition sound marks overlapping words in placement and comparison reports."""
    rate = 24000 / 1001
    xml = Path(j('identity-fade.xml'))
    xml.write_text(timeline([clip(0, -1, 100, 149), transition(47, 49), clip(-1, 96, 299, 348)], 96),
                   encoding='utf-8')
    words = Path(j('identity-fade-words.json'))
    words.write_text(json.dumps({'source': 'A', 'media_reference': 'a.mov', 'words': [
        {'id': 'outside', 'text': 'clear', 'start': 140 / rate, 'end': 145 / rate},
        {'id': 'inside', 'text': 'fade', 'start': 147.2 / rate, 'end': 147.8 / rate},
        {'id': 'incoming', 'text': 'next', 'start': 300.2 / rate, 'end': 300.8 / rate}]}), encoding='utf-8')
    out = Path(j('identity-fade-placement.json'))
    code, output = tool('exchange.py', 'words', xml, '--words', words, '--json', out)
    placed = {row['id']: row for row in load_report(out).get('words', [])}
    inside = placed.get('inside', {})
    span = (inside.get('transitions') or [{}])[0]
    record('exchange: words over an audio transition carry its edit-second span and are estimated',
           code == 0 and placed.get('outside', {}).get('estimated') is False and inside.get('estimated') is True
           and placed.get('incoming', {}).get('estimated') is True and span.get('audio') == 'unassessed'
           and span.get('effect') == 'KGAudioTransCrossFade0dB'
           and abs(span.get('start', -1) - 47 / rate) < 1e-6 and abs(span.get('end', -1) - 49 / rate) < 1e-6,
           str(placed) + output)
    compared = Path(j('identity-fade-compare.json'))
    compare_code, compare_out = tool('exchange.py', 'compare', xml, xml, '--words', words, '--json', compared)
    report = load_report(compared)
    before = {row['id']: row for row in report.get('words_before', [])}
    after = {row['id']: row for row in report.get('words_after', [])}
    record('exchange: compare includes transition uncertainty on both edits word rows',
           compare_code == 0 and before.get('inside', {}).get('estimated') is True
           and after.get('incoming', {}).get('transitions', [{}])[0].get('audio') == 'unassessed'
           and before.get('outside', {}).get('estimated') is False, str(report)[:1000] + compare_out)


def check_exchange_input_protection(tool, record, j):
    """A JSON output cannot replace any explicit input by path, alternate spelling, or hard link."""
    import os
    path = Path(j('identity-protected.xml'))
    path.write_text(timeline([clip(0, 24, 0, 24)], 24), encoding='utf-8')
    original = path.read_bytes()
    code, output = tool('exchange.py', 'read', path, '--json', path)
    same = code == 2 and path.read_bytes() == original and 'input' in output.lower()
    path.write_bytes(original)
    sub = Path(j('identity-path-spelling'))
    sub.mkdir(exist_ok=True)
    spelling = sub / '..' / path.name
    code, output2 = tool('exchange.py', 'read', path, '--json', spelling)
    alternate = code == 2 and path.read_bytes() == original and 'input' in output2.lower()
    path.write_bytes(original)
    link = Path(j('identity-protected-link.xml'))
    try:
        os.link(path, link)
    except OSError as error:
        print(f'SKIP  exchange hard-link protection: {error}')
        linked = True
    else:
        code, output3 = tool('exchange.py', 'read', path, '--json', link)
        linked = code == 2 and path.read_bytes() == original and 'input' in output3.lower()
    record('exchange: same path, alternate spelling and available hard links cannot overwrite the XML',
           same and alternate and linked, output + output2)
    path.write_bytes(original)
    words = Path(j('identity-protected-words.json'))
    words.write_text(json.dumps({'source': 'int_01', 'media_reference': 'a.mov',
                                 'words': [{'id': 'w1', 'text': 'hi', 'start': .1, 'end': .2}]}),
                     encoding='utf-8')
    caption = Path(j('identity-protected.srt'))
    caption.write_text('1\n00:00:00,100 --> 00:00:00,200\nhi\n', encoding='utf-8')
    outcomes = []
    for command, target in [('words', words), ('words', path), ('compare', words), ('compare', path),
                            ('compare', caption)]:
        before = target.read_bytes()
        arguments = ([command, path, '--words', words] if command == 'words'
                     else [command, path, path, '--words', words, '--captions', caption])
        code, detail = tool('exchange.py', *arguments, '--json', target)
        outcomes.append((command, target.name, code, before == target.read_bytes(), detail))
        target.write_bytes(before)
    root = media_project(j('identity-protection-project'), [('int_01', 'source.wav', b'original',
                                                              [('hi', .1, .2)])])
    for target in (root / 'map' / 'sources.json', root / 'map' / 'int_01' / 'words.json', root / 'source.wav'):
        before = target.read_bytes()
        code, detail = tool('exchange.py', 'words', path, '--project', root, '--json', target)
        outcomes.append(('project', target.name, code, before == target.read_bytes(), detail))
        target.write_bytes(before)
    record('exchange: words and compare protect every explicit and project input from JSON output',
           all(code == 2 and intact and 'input' in detail.lower() for _, _, code, intact, detail in outcomes),
           str(outcomes))


def run_exchange_cases(tool, record, j, scripts_dir):
    """Real cuts across a crossfade, exact source ranges, words placed, handles, speed changes and revisions."""
    check_identity_and_stale_transcripts(tool, record, j)
    check_transition_word_uncertainty(tool, record, j)
    check_exchange_input_protection(tool, record, j)
    rate = 24000 / 1001
    # Clip A: frames 0-48 from source 100-148; a crossfade 47-49 cuts at 48; clip B: 48-96 from source 300-348
    # (exported with one handle frame each side of the cut); clip C after a plain cut at 96.
    first = Path(j('exchange-r1.xml'))
    first.write_text(timeline([clip(0, -1, 100, 149), transition(47, 49), clip(-1, 96, 299, 348),
                               clip(96, 144, 500, 548)], 144), encoding='utf-8')
    words = {'sources': [{'id': 'int_01', 'media_reference': 'media/a.mov', 'words': [
        {'id': 'w1', 'text': 'early', 'start': 110 / rate, 'end': 115 / rate},
        {'id': 'w2', 'text': 'handle', 'start': 148.2 / rate, 'end': 148.8 / rate},
        {'id': 'w3', 'text': 'middle', 'start': 320 / rate, 'end': 325 / rate},
        {'id': 'w4', 'text': '', 'start': 326 / rate, 'end': 327 / rate},
        {'id': 'w5', 'text': 'later', 'start': 510 / rate, 'end': 520 / rate}]}]}
    words_path = Path(j('exchange-words.json'))
    words_path.write_text(json.dumps(words), encoding='utf-8')
    code, output = tool('exchange.py', 'read', first, '--json', j('exchange-read.json'))
    result = json.loads(Path(j('exchange-read.json')).read_text(encoding='utf-8'))
    a, b = result['clips'][1], result['clips'][2]
    record('exchange: a crossfade cut is its start plus cutPointTicks; handles are reported apart',
           code == 0 and result['rate'] == '24000/1001' and (a['start_frame'], a['end_frame']) == (0, 48)
           and (b['start_frame'], b['end_frame']) == (48, 96) and a.get('handle_after') == 1
           and b.get('handle_before') == 1 and abs(b['source_in'] - 300 / rate) < 1e-9
           and abs(a['source_out'] - 148 / rate) < 1e-9, str(result['clips'])[:400] + output[-200:])
    record('exchange: a disabled clip is listed and never mapped', result['clips'][0]['mapped'] is False)
    code, output = tool('exchange.py', 'words', first, '--words', words_path, '--json', j('exchange-words-out.json'))
    placed = json.loads(Path(j('exchange-words-out.json')).read_text(encoding='utf-8'))
    times = {row['id']: (round(row['start'] * rate, 3), round(row['end'] * rate, 3)) for row in placed['words']}
    record('exchange: words land at their edit frames; empty rows are dropped',
           times == {'w1': (10.0, 15.0), 'w3': (68.0, 73.0), 'w5': (106.0, 116.0)}, str(times))
    record('exchange: a word only inside a transition handle gets a state and no time',
           placed['states'].get('int_01:w2') == 'handle_only', str(placed['states']))
    speed = Path(j('exchange-speed.xml'))
    speed.write_text(timeline([clip(0, 48, 100, 196, '<filter><effect><effectid>timeremap</effectid></effect>'
                                                     '</filter>')], 48), encoding='utf-8')
    code, output = tool('exchange.py', 'read', speed, '--json', j('exchange-speed.json'))
    result = json.loads(Path(j('exchange-speed.json')).read_text(encoding='utf-8'))
    record('exchange: a speed change is reported as not mapped, never guessed',
           code == 1 and result['clips'][1]['mapped'] is False and result['not_mapped'], str(result['not_mapped']))
    second = Path(j('exchange-r2.xml'))
    second.write_text(timeline([clip(0, 48, 100, 148), clip(48, 96, 500, 548)], 96), encoding='utf-8')
    captions = Path(j('exchange-r1.srt'))
    captions.write_text('1\n00:00:00,417 --> 00:00:00,626\nearly\n\n2\n00:00:02,836 --> 00:00:03,045\nmiddle\n\n'
                        '3\n00:00:04,421 --> 00:00:04,838\nlater\n', encoding='utf-8')
    code, output = tool('exchange.py', 'compare', first, second, '--words', words_path, '--captions', captions,
                        '--json', j('exchange-compare.json'))
    report = json.loads(Path(j('exchange-compare.json')).read_text(encoding='utf-8'))
    fates = [row['status'] for row in report['captions']]
    record('exchange: an edit that drops a clip cuts its words, removes its caption and moves the rest',
           code == 1 and report['words_cut'] == ['int_01:w3'] and fates == ['unchanged', 'removed', 'moved'],
           str(fates) + ' ' + str(report['words_cut']))
    run_exchange_handoff_cases(tool, record, j, scripts_dir)
    check_mixed_rate_handles(tool, record, j)
    check_repeated_uses(tool, record, j)


def mixed_rate_xml(out_a, cross, in_b):
    """A 30 fps sequence of two 60 fps clips (no Premiere ticks) joined by a centred crossfade over `cross`
    sequence frames at frame 60, so each clip carries cross / 2 frames of handle."""
    half = cross // 2
    rate = '<rate><timebase>60</timebase><ntsc>FALSE</ntsc></rate>'
    return ('<?xml version="1.0"?><xmeml version="5"><sequence><duration>120</duration>'
            '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media><audio><track>'
            f'<clipitem id="a"><start>0</start><end>-1</end><in>0</in><out>{out_a}</out>{rate}'
            '<file id="f1"><name>a.wav</name><pathurl>file://localhost/C:/missing/a.wav</pathurl></file></clipitem>'
            f'<transitionitem><start>{60 - half}</start><end>{60 + half}</end><alignment>center</alignment>'
            '<effect><effectid>Cross Fade</effectid></effect></transitionitem>'
            f'<clipitem id="b"><start>-1</start><end>120</end><in>{in_b}</in><out>240</out>{rate}'
            '<file id="f2"><name>b.wav</name><pathurl>file://localhost/C:/missing/b.wav</pathurl></file></clipitem>'
            '</track></audio></media></sequence></xmeml>')


def check_mixed_rate_handles(tool, record, j):
    """Transition handles are sequence frames: at 30 fps over 60 fps clips, 2 handle frames are 4 source frames.
    Each clip plays exactly 2 s of its source, so the second clip's word at 2.01 s lands at 2.01 s."""
    words = Path(j('mixed-rate-words.json'))
    words.write_text(json.dumps({'sources': [
        {'id': 'first', 'media_reference': 'a.wav', 'words': [{'id': 'a1', 'text': 'Hello', 'start': .5,
                                                                'end': .7}]},
        {'id': 'second', 'media_reference': 'b.wav', 'words': [{'id': 'b1', 'text': 'world', 'start': 2.01,
                                                                 'end': 2.1}]}]}), encoding='utf-8')
    placed = {}
    for name, out_a, cross, in_b in (('short', 124, 4, 116), ('long', 150, 30, 90)):
        xml = Path(j(f'mixed-rate-{name}.xml'))
        xml.write_text(mixed_rate_xml(out_a, cross, in_b), encoding='utf-8')
        code, output = tool('exchange.py', 'words', xml, '--words', words, '--json', j(f'mixed-rate-{name}.json'))
        report = load_report(j(f'mixed-rate-{name}.json'))
        placed[name] = (code, {row['id']: round(row['start'], 6) for row in report.get('words', [])},
                        output[-200:])
    record('exchange: mixed-rate transition handles convert at the sequence rate (short and long crossfades)',
           all(code == 0 and times == {'a1': .5, 'b1': 2.01} for code, times, _ in placed.values()), str(placed))


def check_repeated_uses(tool, record, j):
    """Two uses of one source word, one removed: each caption is matched to one use or is unknown, never both
    matched to the survivor; a caption not found in BEFORE is unknown; both exit 1 with the reason."""
    item = ('<clipitem id="{id}"><start>{start}</start><end>{end}</end><in>0</in><out>30</out>'
            '<file id="f1"><name>a.wav</name><pathurl>file://localhost/a.wav</pathurl></file></clipitem>')

    def edit(name, starts):
        path = Path(j(name))
        clips = ''.join(item.format(id=f'c{start}', start=start, end=start + 30) for start in starts)
        path.write_text('<xmeml version="5"><sequence><duration>' + str(30 * len(starts)) + '</duration>'
                        '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate><media><audio><track>' + clips
                        + '</track></audio></media></sequence></xmeml>', encoding='utf-8')
        return path

    twice, once, kept = edit('uses-twice.xml', (0, 30)), edit('uses-once.xml', (0,)), edit('uses-same.xml', (0, 30))
    words = Path(j('uses-words.json'))
    words.write_text(json.dumps({'source': 'int_01', 'media_reference': 'a.wav',
                                 'words': [{'id': 'w1', 'text': 'Hello', 'start': .1, 'end': .3}]}), encoding='utf-8')
    both = Path(j('uses-both.srt'))
    both.write_text('1\n00:00:00,100 --> 00:00:00,300\nHello\n\n2\n00:00:01,100 --> 00:00:01,300\nHello\n',
                    encoding='utf-8')
    stranger = Path(j('uses-stranger.srt'))
    stranger.write_text('1\n00:00:00,100 --> 00:00:00,300\nGoodbye\n', encoding='utf-8')
    code, output = tool('exchange.py', 'compare', twice, once, '--words', words, '--captions', both, '--json',
                        j('uses-removed.json'))
    report = load_report(j('uses-removed.json'))
    states = [row['status'] for row in report.get('captions', [])]
    record('exchange: a removed repeat of a word is not matched twice; its captions are unknown with the reason',
           code == 1 and states == ['unknown', 'unknown'] and 'different number of times' in output
           and report.get('words_uses_changed') == [{'word': 'int_01:w1', 'before': 2, 'after': 1}], output[-400:])
    code, output = tool('exchange.py', 'compare', twice, once, '--words', words, '--captions', stranger)
    record('exchange: a caption not found in BEFORE is unknown, named, and exits 1',
           code == 1 and '1 unknown' in output and 'not matched in BEFORE' in output, output[-300:])
    code, output = tool('exchange.py', 'compare', twice, kept, '--words', words, '--captions', both, '--json',
                        j('uses-same.json'))
    states = [row['status'] for row in load_report(j('uses-same.json')).get('captions', [])]
    record('exchange: a word used twice in both edits pairs one to one and stays unchanged',
           code == 0 and states == ['unchanged', 'unchanged'], output[-300:])


# ----------------------------------------------------------------------------------------------- the editor handoff

def file_xml(file_id, path):
    """A full <file> definition for a media path."""
    name = path.rsplit('/', 1)[-1]
    return (f'<file id="{file_id}"><name>{name}</name><pathurl>file://localhost{path}</pathurl>'
            '<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate></file>')


def clip_xml(start, end, src_in, src_out, inner, enabled=True):
    """A clipitem placing source frames src_in..src_out at start..end, holding `inner` (a file or a sequence)."""
    return (f'<clipitem id="k{start}"><name>clip</name><enabled>{"TRUE" if enabled else "FALSE"}</enabled>'
            f'<rate><timebase>24</timebase><ntsc>TRUE</ntsc></rate><start>{start}</start><end>{end}</end>'
            f'<in>{src_in}</in><out>{src_out}</out><pproTicksIn>{src_in * FRAME_TICKS}</pproTicksIn>'
            f'<pproTicksOut>{src_out * FRAME_TICKS}</pproTicksOut>{inner}</clipitem>')


def sequence_xml(tracks, duration, timebase=24, ntsc=True):
    """xmeml with one sequence; `tracks` is a list of (enabled, items) audio tracks."""
    body = ''.join(f'<track><enabled>{"TRUE" if enabled else "FALSE"}</enabled>{"".join(items)}</track>'
                   for enabled, items in tracks)
    return ('<?xml version="1.0"?><xmeml version="4"><sequence><name>s</name>'
            f'<duration>{duration}</duration><rate><timebase>{timebase}</timebase>'
            f'<ntsc>{"TRUE" if ntsc else "FALSE"}</ntsc></rate>'
            f'<media><video><track/></video><audio>{body}</audio></media></sequence></xmeml>')


def transcript(alias, rate, rows, reference=None):
    """A word-timed transcript in transcribe.py's shape (no media reference unless given); rows are (text, first
    source frame, last source frame)."""
    words = [{'id': f'{alias}-w{number:06d}', 'text': text, 'start': first / rate, 'end': last / rate,
              'speaker': None, 'estimated': False} for number, (text, first, last) in enumerate(rows, 1)]
    data = {'version': 1, 'source': alias, 'engine': 'faster-whisper small', 'language': 'en', 'draft': True,
            'words': words}
    if reference:
        data = {'sources': [{'id': alias, 'media_reference': reference, 'words': words}]}
    return data


def load_report(path):
    """A JSON report, or {} when it was not written."""
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def run_exchange_handoff_cases(tool, record, j, scripts_dir):
    """The documented Premiere workflow end to end, transcripts resolved through the project map or an explicit
    mapping, every unmatched or unsupported clip reported (exit 1), and durations converted at their own rates."""
    rate = 24000 / 1001
    rows = [('Hello', 105, 112), ('world', 115, 130)]
    one_clip = sequence_xml([(True, [clip_xml(0, 48, 100, 148, file_xml('f1', '/Volumes/edit/media/a.mov'))])], 48)
    xml = Path(j('handoff.xml'))
    xml.write_text(one_clip, encoding='utf-8')
    captions = Path(j('handoff.srt'))
    captions.write_text('1\n00:00:00,200 --> 00:00:01,100\nHello world\n', encoding='utf-8')

    root = Path(j('handoff-project'))
    (root / 'map' / 'int_01').mkdir(parents=True, exist_ok=True)
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': [
        {'alias': 'int_01', 'role': 'interview', 'path': 'media/a.mov', 'sha256': '0' * 64}]}), encoding='utf-8')
    (root / 'map' / 'int_01' / 'words.json').write_text(json.dumps(transcript('int_01', rate, rows)),
                                                       encoding='utf-8')
    read_code, read_output = tool('exchange.py', 'read', xml)
    code, output = tool('exchange.py', 'words', xml, '--project', root, '--json', j('handoff-words.json'))
    placed = load_report(j('handoff-words.json'))
    fields = {'id', 'text', 'start', 'end', 'estimated', 'source'}
    shaped = placed.get('version') == 1 and len(placed.get('words', [])) == 2 and all(
        fields <= set(word) for word in placed['words']) and placed['words'][0]['source'] == 'int_01'
    check_code, check_output = tool('captions.py', 'check', captions, '--words', j('handoff-words.json'),
                                    '--json', j('handoff-check.json'))
    record('exchange: the documented Premiere workflow connects: read, words through the project map, then '
           'captions.py check --words finds the caption spoken', read_code == 0 and code == 0 and shaped
           and check_code == 0 and not load_report(j('handoff-check.json')).get('findings'),
           f'{read_code} {code} {check_code} ' + str(placed)[:300] + output[-200:] + check_output[-300:])

    named = Path(j('handoff-named.json'))
    named.write_text(json.dumps(transcript('int_01', rate, rows, reference='media/a.mov')), encoding='utf-8')
    code, output = tool('exchange.py', 'words', xml, '--words', named, '--json', j('handoff-named-out.json'))
    check_code, check_output = tool('captions.py', 'check', captions, '--words', j('handoff-named-out.json'))
    record('exchange: words written for captions.py use the shared edit-time schema, so check --words reads them',
           code == 0 and check_code == 0, output[-200:] + check_output[-300:])

    bare = Path(j('handoff-bare.json'))
    bare.write_text(json.dumps(transcript('int_01', rate, rows)), encoding='utf-8')
    code, output = tool('exchange.py', 'words', xml, '--words', bare, '--json', j('handoff-bare-out.json'))
    report = load_report(j('handoff-bare-out.json'))
    record('exchange: a clip whose transcript cannot be matched is reported and exits 1, never a silent zero',
           code == 1 and [row.get('clip') for row in report.get('unmatched', [])] == [1] and not report.get('words'),
           f'{code} ' + str(report)[:300] + output[-200:])
    code, output = tool('exchange.py', 'words', xml, '--words', bare, '--map', 'a.mov=int_01',
                        '--json', j('handoff-mapped.json'))
    report = load_report(j('handoff-mapped.json'))
    record('exchange: --map FILE=ALIAS resolves a transcript that has no media reference',
           code == 0 and len(report.get('words', [])) == 2 and not report.get('unmatched'), output[-200:])

    twins = Path(j('handoff-twins.json'))
    twins.write_text(json.dumps({'sources': [
        {'id': 'int_01', 'media_reference': 'cardA/A001.mov', 'words': transcript('int_01', rate, rows)['words']},
        {'id': 'int_02', 'media_reference': 'cardB/A001.mov', 'words': transcript('int_02', rate, rows)['words']}]}),
        encoding='utf-8')
    card = sequence_xml([(True, [clip_xml(0, 48, 100, 148, file_xml('f1', '/Volumes/edit/cardB/A001.mov'))])], 48)
    card_xml = Path(j('handoff-card.xml'))
    card_xml.write_text(card, encoding='utf-8')
    elsewhere = Path(j('handoff-elsewhere.xml'))
    elsewhere.write_text(card.replace('/Volumes/edit/cardB/A001.mov', '/Volumes/other/A001.mov'), encoding='utf-8')
    code, output = tool('exchange.py', 'words', elsewhere, '--words', twins, '--json', j('handoff-twins-out.json'))
    report = load_report(j('handoff-twins-out.json'))
    folder_code, folder_output = tool('exchange.py', 'words', card_xml, '--words', twins,
                                      '--json', j('handoff-card-out.json'))
    by_folder = load_report(j('handoff-card-out.json'))
    map_code, map_output = tool('exchange.py', 'words', card_xml, '--words', twins, '--map', 'cardB/A001.mov=int_02',
                                '--json', j('handoff-card-map.json'))
    by_map = load_report(j('handoff-card-map.json'))
    record('exchange: two transcripts for files with the same name are ambiguous when the file cannot be read, even '
           'if a folder looks like one of them; --map settles it',
           code == 1 and report.get('unmatched') and 'ambiguous' in str(report['unmatched'])
           and folder_code == 1 and 'ambiguous' in str(by_folder.get('unmatched')) and map_code == 0
           and {word['source'] for word in by_map.get('words', [])} == {'int_02'},
           f'{code} {folder_code} {map_code} ' + str(report.get('unmatched')) + output[-200:] + folder_output[-200:]
           + map_output[-200:])

    muted = Path(j('handoff-muted.xml'))
    muted.write_text(sequence_xml([(False, [clip_xml(0, 48, 100, 148, file_xml('f1', '/media/a.mov'))])], 48),
                     encoding='utf-8')
    code, output = tool('exchange.py', 'read', muted, '--json', j('handoff-muted.json'))
    report = load_report(j('handoff-muted.json'))
    clips = report.get('clips', [{}])
    record('exchange: a disabled track is skipped and said so; its clips are never mapped',
           clips and clips[0].get('mapped') is False and 'disabled' in str(report.get('skipped', '')).lower()
           and 'disabled' in output.lower(), str(report)[:300] + output[-200:])

    nested = Path(j('handoff-nested.xml'))
    inner = ('<sequence id="nest"><name>nested</name><duration>48</duration><rate><timebase>24</timebase>'
             '<ntsc>TRUE</ntsc></rate><media><audio><track/></audio></media></sequence>')
    nested.write_text(sequence_xml([(True, [clip_xml(0, 48, 0, 48, inner)])], 48), encoding='utf-8')
    code, output = tool('exchange.py', 'read', nested, '--json', j('handoff-nested.json'))
    report = load_report(j('handoff-nested.json'))
    clips = report.get('clips', [{}])
    record('exchange: a nested sequence is not mapped, with the reason, and read exits 1',
           code == 1 and clips and clips[0].get('mapped') is False and 'nested' in str(report.get('not_mapped')),
           f'{code} ' + str(report.get('not_mapped')) + output[-200:])

    after = Path(j('handoff-remapped.xml'))
    remap = '<filter><effect><effectid>timeremap</effectid></effect></filter>'
    after.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, file_xml('f1', '/media/a.mov')),
                                           clip_xml(48, 96, 300, 396, '<file id="f1"/>' + remap)])], 96),
                     encoding='utf-8')
    code, output = tool('exchange.py', 'compare', xml, after, '--words', named, '--json', j('handoff-compare.json'))
    report = load_report(j('handoff-compare.json'))
    record('exchange: compare exits 1 when a clip could not be mapped, even with no words cut',
           code == 1 and not report.get('words_cut') and report.get('not_mapped', {}).get('after'),
           f'{code} ' + output[-300:])

    thirty, twenty_four = Path(j('handoff-30.xml')), Path(j('handoff-24.xml'))
    thirty.write_text(sequence_xml([(True, [])], 90, 30, False), encoding='utf-8')
    twenty_four.write_text(sequence_xml([(True, [])], 90, 24, False), encoding='utf-8')
    code, output = tool('exchange.py', 'compare', thirty, twenty_four, '--words', named,
                        '--json', j('handoff-rates.json'))
    report = load_report(j('handoff-rates.json'))
    record('exchange: the duration change converts each sequence at its own rate (90 frames at 30 and 24 fps)',
           report.get('duration_change_s') == 0.75, str(report.get('duration_change_s')) + output[-200:])
    run_exchange_coverage_cases(tool, record, j, scripts_dir)


# ----------------------------------------------------------------------------------------------- coverage and identity

def plain_clip(start, end, src_in, src_out, inner, rate='<rate><timebase>30</timebase></rate>', extra=''):
    """A clipitem with no Premiere ticks, so source positions come from frames at the clip's resolved rate."""
    return (f'<clipitem id="p{start}"><name>clip</name><enabled>TRUE</enabled>{rate}<start>{start}</start>'
            f'<end>{end}</end><in>{src_in}</in><out>{src_out}</out>{inner}{extra}</clipitem>')


def media_project(root, sources):
    """A project whose sources are real local files: [(alias, relative path, bytes, [(text, start s, end s)])]."""
    root = Path(root)
    entries = []
    for alias, relative, content, rows in sources:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries.append({'alias': alias, 'role': 'interview', 'path': relative,
                        'sha256': hashlib.sha256(content).hexdigest()})
        words = [{'id': f'{alias}-w{number:06d}', 'text': text, 'start': start, 'end': end, 'estimated': False}
                 for number, (text, start, end) in enumerate(rows, 1)]
        (root / 'map' / alias).mkdir(parents=True, exist_ok=True)
        (root / 'map' / alias / 'words.json').write_text(json.dumps({'version': 1, 'source': alias, 'words': words}),
                                                        encoding='utf-8')
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': entries}), encoding='utf-8')
    return root


def local_file(path, content):
    """A local media stand-in with the given bytes; returns its <file> element."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return file_xml('f1', '/' + path.resolve().as_posix().lstrip('/'))


def run_exchange_coverage_cases(tool, record, j, scripts_dir):
    """A clip takes a transcript only when the file's content agrees with the project; a comparison names everything
    it left out and never claims a word cut that unmapped material might hold; frame rates inherit NTSC context; a
    word split by an edit is not called unchanged."""
    rate = 24000 / 1001
    rows = [('alpha', 105 / rate, 112 / rate)]
    project = media_project(j('cover-project'), [('int_01', 'media/cardA/A001.mov', b'synthetic A', rows),
                                                 ('int_02', 'media/cardB/A001.mov', b'synthetic B', rows)])
    single = media_project(j('cover-single'), [('int_01', 'media/cardA/A001.mov', b'synthetic A', rows)])

    def words_for(name, inner, where):
        xml = Path(j(name + '.xml'))
        xml.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, inner)])], 48), encoding='utf-8')
        code, output = tool('exchange.py', 'words', xml, '--project', where, '--json', j(name + '.json'))
        return code, load_report(j(name + '.json')), output

    code, tail, output = words_for('cover-tail', local_file(j('cover-moved', 'cardA', 'A001.mov'), b'synthetic B'),
                                   project)
    record("exchange: the file's content outranks a folder that looks like another source's",
           code == 0 and {word['source'] for word in tail.get('words', [])} == {'int_02'}, str(tail)[:300] + output)
    code, conflict, output = words_for('cover-conflict', local_file(j('cover-other', 'A001.mov'), b'synthetic B'),
                                       single)
    record("exchange: a readable file whose content differs from the project's same-named source is not mapped to it",
           code == 1 and not conflict.get('words') and 'content' in str(conflict.get('unmatched'))
           and '--map' in str(conflict.get('unmatched')), str(conflict)[:400] + output)
    code, renamed, output = words_for('cover-renamed', local_file(j('cover-renamed', 'take.mov'), b'synthetic A'),
                                      single)
    matches = renamed.get('matches', [])
    record('exchange: a renamed copy is found by its content, and the match says how it was made',
           code == 0 and {word['source'] for word in renamed.get('words', [])} == {'int_01'}
           and matches and 'content' in matches[0].get('by', ''), str(renamed)[:400] + output)
    code, unseen, output = words_for('cover-unseen', file_xml('f1', '/Volumes/edit/cardA/A001.mov'), project)
    record('exchange: a file that cannot be read, with a name two sources share, is not mapped even when its folder '
           'looks like one of them', code == 1 and not unseen.get('words')
           and 'ambiguous' in str(unseen.get('unmatched')), str(unseen)[:400] + output)
    code, named, output = words_for('cover-named', file_xml('f1', '/Volumes/edit/cardA/A001.mov'), single)
    matches = named.get('matches', [])
    record('exchange: an unreadable file with a unique name is matched by name and says it was not verified',
           code == 0 and named.get('words') and matches and 'not verified' in matches[0].get('by', ''),
           str(named)[:400] + output)

    source = local_file(j('cover-media', 'A001.mov'), b'synthetic A')
    alone = media_project(j('cover-alone'), [('int_01', str(Path(j('cover-media', 'A001.mov')).resolve()),
                                              b'synthetic A', rows)])
    muted_before, muted_after = Path(j('cover-muted-1.xml')), Path(j('cover-muted-2.xml'))
    for path in (muted_before, muted_after):
        path.write_text(sequence_xml([(False, [clip_xml(0, 48, 100, 148, source)])], 48), encoding='utf-8')
    code, output = tool('exchange.py', 'compare', muted_before, muted_after, '--project', alone,
                        '--json', j('cover-muted.json'))
    report = load_report(j('cover-muted.json'))
    record('exchange: comparing a disabled track exits 1, names it on the console and marks the result incomplete',
           code == 1 and 'disabled' in output.lower() and report.get('complete') is False
           and report.get('coverage', {}).get('before', {}).get('track_enabled') is False, f'{code} {output}')

    other = local_file(j('cover-media', 'B001.mov'), b'synthetic B')
    two_before, two_after = Path(j('cover-two-1.xml')), Path(j('cover-two-2.xml'))
    two_before.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, source)]),
                                        (True, [clip_xml(0, 48, 100, 148, other.replace('id="f1"', 'id="f2"'))])], 48),
                          encoding='utf-8')
    two_after.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, source)]), (True, [])], 48), encoding='utf-8')
    code, output = tool('exchange.py', 'compare', two_before, two_after, '--project', alone,
                        '--json', j('cover-two.json'))
    report = load_report(j('cover-two.json'))
    unread = report.get('coverage', {}).get('before', {}).get('enabled_audio_not_read')
    record('exchange: an enabled audio track the comparison did not read is named on the console and in the result',
           code == 1 and 'track' in output and '2' in output and 'not read' in output and unread
           and report.get('complete') is False, f'{code} {output} {unread}')

    remapped = Path(j('cover-remap.xml'))
    remap = '<filter><effect><effectid>timeremap</effectid></effect></filter>'
    remapped.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, source + remap)])], 48), encoding='utf-8')
    plain = Path(j('cover-plain.xml'))
    plain.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, source)])], 48), encoding='utf-8')
    captions = Path(j('cover-remap.srt'))
    captions.write_text('1\n00:00:00,200 --> 00:00:00,600\nalpha\n', encoding='utf-8')
    code, output = tool('exchange.py', 'compare', plain, remapped, '--project', alone, '--captions', captions,
                        '--json', j('cover-remap.json'))
    report = load_report(j('cover-remap.json'))
    record('exchange: a word whose clip became time-remapped is unknown, not cut, and its caption is unknown',
           code == 1 and not report.get('words_cut') and report.get('words_unknown') == ['int_01:int_01-w000001']
           and [row['status'] for row in report.get('captions', [])] == ['unknown'], str(report)[:500] + output)

    moved = Path(j('cover-moved-track.xml'))
    moved.write_text(sequence_xml([(True, []), (True, [clip_xml(0, 48, 100, 148, source)])], 48), encoding='utf-8')
    code, output = tool('exchange.py', 'compare', plain, moved, '--project', alone, '--json', j('cover-moved.json'))
    report = load_report(j('cover-moved.json'))
    record('exchange: a word moved to an audio track the comparison did not read is unknown, not cut',
           code == 1 and not report.get('words_cut') and report.get('words_unknown') == ['int_01:int_01-w000001'],
           str(report)[:400] + output)

    ntsc = '<rate><timebase>30</timebase><ntsc>TRUE</ntsc></rate>'
    inherited_file = (f'<file id="n1"><name>A001.mov</name><pathurl>file://localhost/media/A001.mov</pathurl>{ntsc}'
                      '</file>')

    def ntsc_read(name, clip_rate, file_rate=ntsc, sequence_ntsc=True, extra=''):
        inner = inherited_file.replace(ntsc, file_rate)
        xml = Path(j(name + '.xml'))
        xml.write_text(sequence_xml([(True, [plain_clip(0, 30, 36000, 36030, inner, clip_rate, extra)])], 30, 30,
                                    sequence_ntsc), encoding='utf-8')
        code, output = tool('exchange.py', 'read', xml, '--json', j(name + '.json'))
        report = load_report(j(name + '.json'))
        return code, (report.get('clips') or [{}])[0], output

    code, inherited, output = ntsc_read('cover-ntsc', '<rate><timebase>30</timebase></rate>')
    record('exchange: a clip with timebase 30 and no ntsc inherits NTSC from its sequence and file (frame 36000 is '
           '1201.2 s)', code == 0 and abs(inherited.get('source_in', 0) - 36000 * 1001 / 30000) < 1e-9,
           str(inherited) + output)
    clash_code, clash, clash_output = ntsc_read('cover-ntsc-clash', '<rate><timebase>30</timebase></rate>',
                                                '<rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>')
    bad_code, bad, bad_output = ntsc_read('cover-ntsc-bad', '<rate><timebase>thirty</timebase></rate>')
    record('exchange: an ambiguous or malformed clip rate is not mapped (sequence and file disagree; timebase '
           '"thirty")', clash_code == 1 and clash.get('mapped') is False and bad_code == 1
           and bad.get('mapped') is False, str((clash, bad)) + clash_output + bad_output)
    code, dropped, output = ntsc_read('cover-df', ntsc, extra='<timecode><string>00:10:00;00</string>'
                                      '<displayformat>DF</displayformat></timecode>')
    record('exchange: drop-frame is a timecode label; numeric frames are not corrected',
           code == 0 and abs(dropped.get('source_in', 0) - 36000 * 1001 / 30000) < 1e-9, str(dropped) + output)

    split_rows = [('early', 110 / rate, 115 / rate), ('middle', 120 / rate, 130 / rate),
                  ('later', 140 / rate, 146 / rate)]
    alone_split = media_project(j('cover-split'), [('int_01', str(Path(j('cover-media', 'A001.mov')).resolve()),
                                                    b'synthetic A', split_rows)])
    whole = Path(j('cover-whole.xml'))
    whole.write_text(sequence_xml([(True, [clip_xml(0, 48, 100, 148, source)])], 48), encoding='utf-8')
    cut_inside = Path(j('cover-cut-inside.xml'))
    cut_inside.write_text(sequence_xml([(True, [clip_xml(0, 25, 100, 125, source),
                                                clip_xml(25, 45, 128, 148, '<file id="f1"/>')])], 45), encoding='utf-8')
    joined = Path(j('cover-joined.xml'))
    joined.write_text(sequence_xml([(True, [clip_xml(0, 25, 100, 125, source),
                                            clip_xml(25, 48, 125, 148, '<file id="f1"/>')])], 48), encoding='utf-8')
    middle = Path(j('cover-middle.srt'))
    middle.write_text('1\n00:00:00,800 --> 00:00:01,300\nmiddle\n', encoding='utf-8')
    code, output = tool('exchange.py', 'compare', whole, cut_inside, '--project', alone_split, '--captions', middle,
                        '--json', j('cover-split.json'))
    report = load_report(j('cover-split.json'))
    joined_code, joined_output = tool('exchange.py', 'compare', whole, joined, '--project', alone_split, '--captions',
                                      middle, '--json', j('cover-joined.json'))
    kept = load_report(j('cover-joined.json'))
    record('exchange: a word an edit cuts into is partly cut and its caption is not unchanged; two clips that together '
           'keep the whole word are not', code == 1 and report.get('words_split') == ['int_01:int_01-w000002']
           and [row['status'] for row in report.get('captions', [])] == ['split']
           and not kept.get('words_split') and [row['status'] for row in kept.get('captions', [])] == ['unchanged'],
           str(report)[:400] + ' | ' + str(kept)[:300] + output + joined_output)
