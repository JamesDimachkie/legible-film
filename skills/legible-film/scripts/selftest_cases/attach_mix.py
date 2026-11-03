"""Known-answer cases for attaching processed buses to a cut."""
import json
import copy
import hashlib
import importlib.util
import math
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path
import wave

import numpy as np


def preflight_cases(tool, record, j, scripts_dir):
    module_spec = importlib.util.spec_from_file_location('lf_cut_attach_cases', Path(scripts_dir) / 'cut.py')
    cut = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(cut)
    original = {'fps': '24000/1001', 'clock': 'seconds',
                'sections': [{'id': 'first', 'a': 0, 'b': 2, 'clock': 'action'}],
                'events': [{'id': 'turn', 't': 1, 'scale': 'turn', 'section': 'first', 'sync': 'attack'}]}
    spotted = copy.deepcopy(original)
    spotted['events'][0].update(role='tap', gain_db=-3, enabled=True, spotting=['kept'])
    record('attach mix: spotting choices preserve the authored timing', cut.same_cue_timing(original, spotted), '')
    spotted['events'][0]['t'] = 1.1
    record('attach mix: a spotted cue with a moved time is refused', not cut.same_cue_timing(original, spotted), '')
    legacy = {'fps': '24000/1001', 'events': [{'id': 'one', 't': 1}], 'sections': []}
    normalized = {'fps': 24000/1001, 'fps_exact': '24000/1001',
                  'events': [{'id': 'one', 't': 1, 'scale': 'contact', 'sync': 'attack', 'lead_ms': 0}],
                  'sections': []}
    record('attach mix: loader-normalized defaults and rational fps preserve timing',
           cut.same_cue_timing(legacy, normalized), '')
    retimed = copy.deepcopy(original)
    retimed['sections'][0]['b'] = 2.1
    record('attach mix: moving a section under the same id changes timing',
           not cut.same_cue_timing(original, retimed), '')
    changed_rate = copy.deepcopy(original)
    changed_rate['fps'] = 24
    record('attach mix: changing the frame rate changes timing',
           not cut.same_cue_timing(original, changed_rate), '')
    cl = cut.load_sibling('cue_list')
    schedule = {'fps_exact': '25/1', 'frames': 2, 'pts_us': [0, 40000], 'duration_us': [40000, 40000],
                'visible_start_us': 0, 'visible_end_us': 80000}
    first = {'sha256': 'a' * 64, 'geometry': cl.geometry({'width': 320, 'height': 180}),
             'schedule': schedule, 'untimed': False}
    within = copy.deepcopy(first)
    within['schedule']['pts_us'][1] += 500
    changed = copy.deepcopy(first)
    changed['schedule']['pts_us'][1] += 40000
    compare = getattr(cut, 'same_attached_picture', lambda _cl, a, b: (a == b, 'exact equality'))
    record('attach mix: picture schedules use the shared timing tolerance',
           compare(cl, first, within)[0] and not compare(cl, first, changed)[0], '')
    generated = {'version': 'v2', 'events': [
        {'id': 'plate', 't': -.4, 'role': '__cut_fade_plate__', 'enabled': False},
        {'id': 'title', 't': 1, 'role': 'pop', 'enabled': False},
        {'id': 'invalid', 't': -.2, 'role': 'pop', 'enabled': False}]}
    filter_cues = getattr(cut, 'without_generated_fade_cues', lambda value: value)
    filtered = filter_cues(generated)
    record('cut: generated fade plates do not export pre-film sound cues',
           [event['id'] for event in filtered['events']] == ['title', 'invalid'], str(filtered))
    root = Path(j('attach-mix-cases'))
    root.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.new('RGBA', (8, 8), (0, 0, 0, 255)).save(root / 'fade.png')
    assembler_spec = importlib.util.spec_from_file_location('attach_assembler_cases', Path(scripts_dir) / 'assemble.py')
    assembler = importlib.util.module_from_spec(assembler_spec)
    assembler_spec.loader.exec_module(assembler)
    fade_overlay = {'kind': 'image', 'src': 'fade', 'from': -.4, 'to': .4, 'x': 0, 'y': 0,
                    'w': 1, 'fade_ms': 400, 'role': '__cut_fade_plate__'}
    title_overlay = dict(fade_overlay, **{'from': .5, 'to': 1, 'role': 'pop'})
    emitted = []
    images, _ = assembler.prepare_overlays({'sources': {'fade': {'file': 'fade.png'}},
                                            'overlays': [fade_overlay, title_overlay]}, root, 8, emitted, [])
    assembled_cues = {'version': 'v2', 'sections': [], 'events': [cl.upgrade_event(row) for row in emitted]}
    cleaned = filter_cues(assembled_cues)
    record('cut: assembler fade timing stays intact and its generated cue is removed',
           images[0][2:4] == (-.4, .4) and len(cleaned['events']) == 1
           and cleaned['events'][0]['t'] == .5 and not cl.validate_v2(cleaned, 25), str(cleaned))
    (root / 'picture-timing.json').write_bytes((json.dumps(schedule, sort_keys=True) + '\n').encode('utf-8'))
    picture_identity = {'picture_sha256': first['sha256'], 'picture_timing': cl.timing_block(schedule)}
    recorded = {'picture-timing.json': hashlib.sha256((root / 'picture-timing.json').read_bytes()).hexdigest()}
    verify = getattr(cut, 'version_picture_matches', lambda _cl, _root, _id, _files, _picture: (True, ''))
    wrong_identity = dict(picture_identity, picture_sha256='b' * 64)
    record('attach mix: the source picture matches the version packet and timing identity',
           verify(cl, root, picture_identity, recorded, first)[0]
           and not verify(cl, root, wrong_identity, recorded, first)[0]
           and not verify(cl, root, picture_identity, recorded, changed)[0]
           and not verify(cl, root, picture_identity, {}, first)[0], '')
    version = root / 'cuts' / 'v001'
    version.mkdir(parents=True, exist_ok=True)
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': False}), encoding='utf-8')
    (root / 'film.md').write_text('---\ntitle: Synthetic\n---\n', encoding='utf-8')
    buses = root / 'buses'
    buses.mkdir()
    report = buses / 'mix-report.json'
    report.write_text('{}', encoding='utf-8')
    code, output = tool('cut.py', 'attach-mix', root, '--version', 'v001', '--buses', buses, '--report', report)
    record('attach mix: non-final version names the final render command',
           code == 2 and 'render' in output and '--final' in output, output[-300:])
    stem = version / 'stems' / 'dialogue.wav'
    stem.parent.mkdir()
    stem.write_bytes(b'changed')
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': True,
                                                       'files': {'stems/dialogue.wav': '0' * 64}}),
                                           encoding='utf-8')
    code, output = tool('cut.py', 'attach-mix', root, '--version', 'v001', '--buses', buses, '--report', report)
    record('attach mix: altered version stems are refused before publishing',
           code == 2 and 'version file changed' in output and not (root / 'cuts' / 'v002').exists(), output[-300:])
    (version / 'stems' / 'extra.wav').write_bytes(b'extra')
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': True,
                                                       'files': {'stems/dialogue.wav': hashlib.sha256(b'changed').hexdigest()}}),
                                           encoding='utf-8')
    code, output = tool('cut.py', 'attach-mix', root, '--version', 'v001', '--buses', buses, '--report', report)
    record('attach mix: an unrecorded stem cannot enter the delivered mix',
           code == 2 and 'unrecorded stem' in output and not (root / 'cuts' / 'v002').exists(), output[-300:])
    (version / 'stems' / 'extra.wav').unlink()
    (version / 'edit.json').write_text('{"film_fades": {}}', encoding='utf-8')
    for name in ('preview.mp4', 'edit-cues.json', 'film.md'):
        (version / name).write_bytes(name.encode())
    recorded = {'stems/dialogue.wav': hashlib.sha256(stem.read_bytes()).hexdigest()}
    recorded.update({name: hashlib.sha256((version / name).read_bytes()).hexdigest()
                     for name in ('preview.mp4', 'edit-cues.json', 'film.md')})
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': True, 'files': recorded}),
                                           encoding='utf-8')
    code, output = tool('cut.py', 'attach-mix', root, '--version', 'v001', '--buses', buses, '--report', report)
    record('attach mix: an unrecorded edit cannot provide fades',
           code == 2 and 'missing recorded edit.json' in output and not (root / 'cuts' / 'v002').exists(), output[-300:])
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': True,
                                                       'files': {'../../film.md': '0' * 64}}), encoding='utf-8')
    code, output = tool('cut.py', 'attach-mix', root, '--version', 'v001', '--buses', buses, '--report', report)
    record('attach mix: version file paths cannot escape the version',
           code == 2 and 'version file changed' in output and not (root / 'cuts' / 'v002').exists(), output[-300:])
    # The 'cue_list' reader must prove a version binding, not just accept legacy input.
    (version / 'edit-cues.json').write_text('{"version":"v1","events":[]}', encoding='utf-8')
    (version / 'preview.mp4').write_bytes(b'picture')
    (version / 'film.md').write_text('film', encoding='utf-8')
    listed_files = ['preview.mp4', 'edit.json', 'edit-cues.json', 'film.md', 'stems/dialogue.wav']
    hashes = {name: hashlib.sha256((version / name).read_bytes()).hexdigest() for name in listed_files}
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': True, 'files': hashes,
                                                       'identity': {'cues_sha256': hashes['edit-cues.json']}}),
                                           encoding='utf-8')
    code, output = tool('cut.py', 'attach-mix', root, '--version', 'v001', '--buses', buses, '--report', report)
    record('attach mix: an unversioned cue list cannot prove the version identity',
           code == 2 and 'bound' in output and not (root / 'cuts' / 'v002').exists(), output[-300:])
    identity = cl.paper_identity('a' * 64, {})
    cue_doc = {'version': 'v2', 'picture': dict(identity, path='.'), 'sections': [], 'events': []}
    (version / 'edit-cues.json').write_text(json.dumps(cue_doc), encoding='utf-8')
    hashes = {name: hashlib.sha256((version / name).read_bytes()).hexdigest() for name in listed_files}
    (version / 'manifest.json').write_text(json.dumps({'version': 'v001', 'final': True, 'files': hashes,
        'film_md_sha256': 'a' * 64, 'sources': {}, 'identity': {'cues_sha256': hashes['edit-cues.json']}}),
        encoding='utf-8')
    for name, sample in (('effects.wav', 200), ('bed.wav', 0)):
        with wave.open(str(buses / name), 'wb') as stream:
            stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
            stream.writeframes(np.full(4800, sample, dtype='<i2').tobytes())
    report.write_text(json.dumps({'exit_code': 0, 'mastering': {'preset': 'none'}, 'gain_applied_db': 0,
        'inputs': {'cues': hashes['edit-cues.json'], 'voice': [{'sha256': hashes['stems/dialogue.wav'],
                                                                'at_s': 0, 'gain_db': 0}]},
        'outputs': {name: hashlib.sha256((buses / name).read_bytes()).hexdigest()
                    for name in ('effects.wav', 'bed.wav')}}), encoding='utf-8')
    try:
        loaded_buses = cut.attach_inputs(root, SimpleNamespace(version='v001', buses=buses, report=report,
                                                               replace=[]))[5]
        silent_skipped = 'effects' in loaded_buses and 'bed' not in loaded_buses
        output = 'retained buses: ' + ', '.join(sorted(loaded_buses))
    except Exception as error:
        silent_skipped = False
        output = str(error)
    record('attach mix: a verified silent ambience bus is skipped', silent_skipped, str(output)[-200:])
    cue_doc['events'] = [{'id': 'quiet', 't': .2, 't_end': .5, 'scale': 'silence', 'scope': 'all',
                          'sound': 'silent', 'decision': 'the source voice should fade'}]
    (version / 'edit-cues.json').write_text(json.dumps(cue_doc), encoding='utf-8')
    cue_digest = hashlib.sha256((version / 'edit-cues.json').read_bytes()).hexdigest()
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
    manifest['files']['edit-cues.json'] = manifest['identity']['cues_sha256'] = cue_digest
    with wave.open(str(stem), 'wb') as stream:
        stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.full(48000, 500, dtype='<i2').tobytes())
    manifest['files']['stems/dialogue.wav'] = hashlib.sha256(stem.read_bytes()).hexdigest()
    (version / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    mix_report = json.loads(report.read_text(encoding='utf-8'))
    mix_report['inputs']['cues'] = cue_digest
    mix_report['inputs']['voice'][0]['sha256'] = manifest['files']['stems/dialogue.wav']
    report.write_text(json.dumps(mix_report), encoding='utf-8')
    try:
        checked = cut.attach_inputs(root, SimpleNamespace(version='v001', buses=buses, report=report,
                                                          replace=[], strict=False))
        looks = checked[-1]
        all_look = isinstance(looks, list) and any('dialogue' in item and '0.2' in item and '0.5' in item
                                                   for item in looks)
        detail = str(looks)
    except Exception as error:
        all_look, detail = False, str(error)
    record('attach mix: audible retained dialogue is a look by default', all_look, detail)
    try:
        cut.attach_inputs(root, SimpleNamespace(version='v001', buses=buses, report=report,
                                                replace=[], strict=True))
        strict_refused, detail = False, 'not refused'
    except ValueError as error:
        detail = str(error)
        strict_refused = ('dialogue' in detail and '0.2' in detail and '0.5' in detail
                          and '--replace ROLE' in detail and 'scope' in detail)
    record('attach mix: strict mode refuses the same retained dialogue with remedies', strict_refused, detail)
    with wave.open(str(stem), 'wb') as stream:
        stream.setparams((1, 2, 48000, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.zeros(48000, dtype='<i2').tobytes())
    manifest['files']['stems/dialogue.wav'] = hashlib.sha256(stem.read_bytes()).hexdigest()
    (version / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    mix_report['inputs']['voice'][0]['sha256'] = manifest['files']['stems/dialogue.wav']
    report.write_text(json.dumps(mix_report), encoding='utf-8')
    try:
        cut.attach_inputs(root, SimpleNamespace(version='v001', buses=buses, report=report, replace=[]))
        already_silent = True
    except ValueError:
        already_silent = False
    record('attach mix: an all-scoped span already silent in retained stems is accepted', already_silent, '')
    try:
        checked = cut.attach_inputs(root, SimpleNamespace(version='v001', buses=buses, report=report,
                                                          replace=[], strict=True))
        strict_silent, detail = checked[-1] == [], str(checked[-1])
    except ValueError as error:
        strict_silent, detail = False, str(error)
    record('attach mix: strict mode accepts an already silent retained stem', strict_silent, detail)
    stage = root / 'synthetic-stage'
    (stage / 'qa').mkdir(parents=True)
    (stage / 'edit-cues.json').write_text('old', encoding='utf-8')
    (stage / 'checks.json').write_text('old check', encoding='utf-8')
    (stage / 'checks-final.json').write_text('old final check', encoding='utf-8')
    (stage / 'qa' / 'report.json').write_text('old qa', encoding='utf-8')
    chosen = root / 'chosen.json'
    chosen.write_text('spotted list', encoding='utf-8')
    prepare = getattr(cut, 'prepare_attached_version', lambda _stage, _chosen: None)
    prepare(stage, chosen)
    record('attach mix: a new version uses the chosen list and discards inherited QA',
           (stage / 'edit-cues.json').read_bytes() == chosen.read_bytes()
           and not (stage / 'checks.json').exists() and not (stage / 'checks-final.json').exists()
           and not (stage / 'qa').exists(), '')


def rendered_cases(tool, record, j, scripts_dir):
    """Render a synthetic version, spot its join, mix, attach and inspect the delivered streams."""
    root = Path(j('attach-rendered'))
    root.mkdir(parents=True, exist_ok=True)
    project = root / 'project'
    rate = 48000

    def ffmpeg(*args):
        result = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-v', 'error', '-y',
                                 *map(str, args)], capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stderr[-500:])

    def wav(path, hz, seconds, level):
        t = np.arange(round(seconds * rate)) / rate
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            stream.writeframes((np.sin(2*np.pi*hz*t)*level*32767).astype('<i2').tobytes())

    def read(path):
        data = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-vn', '-ac', '1',
                                        '-ar', str(rate), '-f', 'f32le', '-'])
        return np.frombuffer(data, dtype='<f4')

    def amplitude(samples, hz, start, end):
        lo, hi = round(start * rate), round(end * rate)
        x = samples[lo:hi]
        if len(x) < 10:
            return 0.0
        phase = np.exp(-2j*np.pi*hz*np.arange(len(x))/rate)
        window = np.hanning(len(x))
        return float(abs(np.dot(x * window, phase)) * 2 / window.sum())

    def tree(folder):
        return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(folder.rglob('*')) if p.is_file()}

    source = root / 'source.mp4'
    nat = root / 'nat.mp4'
    for path, freq in ((source, 440), (nat, 660)):
        ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=15:duration=4',
               '-f', 'lavfi', '-i', f'sine=frequency={freq}:duration=4:sample_rate=48000',
               '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', path)
    old_music = root / 'original-music.wav'
    wav(old_music, 220, 4, .08)
    srt = root / 'words.srt'
    srt.write_text('1\n00:00:00,300 --> 00:00:01,200\nAlpha bravo\n\n'
                   '2\n00:00:01,700 --> 00:00:02,700\nCharlie delta\n', encoding='utf-8')
    steps = [tool('map.py', 'add', project, source, '--role', 'interview'),
             tool('map.py', 'add', project, nat, '--role', 'broll'),
             tool('map.py', 'add', project, old_music, '--role', 'music'),
             tool('map.py', 'run', project, '--alias', 'int_01', '--words', 'import:' + str(srt))]
    (project / 'film.md').write_text(
        '---\ntitle: Synthetic attach\nsize: 160x90\nfps: 15\ncaptions: srt\n---\n'
        '- music music_01 0:00-0:04 -6dB\n'
        '> int_01 0:00.20-0:01.40 Alpha bravo {fade in 0.4}\n'
        '  ~ broll_01 0:00-0:01 sound -6dB\n'
        '> int_01 0:01.60-0:03.00 Charlie delta {fade out 0.4}\n', encoding='utf-8')
    steps.append(tool('cut.py', 'render', project, '--final'))
    version = project / 'cuts' / 'v001'
    if not (version / 'manifest.json').is_file():
        record('attach mix: a final synthetic version with dialogue, music and effects renders', False,
               ' | '.join(out[-350:] for _, out in steps))
        return
    manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
    stems = version / 'stems'
    required = [stems / (name + '.wav') for name in ('dialogue', 'music', 'nat')]
    listed = json.loads((version / 'edit-cues.json').read_text(encoding='utf-8'))
    joins = [e for e in listed.get('events', []) if e.get('id', '').startswith('join-')]
    ready = all(p.is_file() for p in required) and bool(joins)
    record('attach mix: a final synthetic version with dialogue, music and effects renders', ready,
           f'stems={sorted(p.name for p in stems.glob("*.wav"))}; joins={joins}; '
           + ' | '.join(out[-200:] for _, out in steps if _ not in (0, 1)))
    if not ready:
        return
    join = joins[0]
    sound = root / 'sound'
    sound.mkdir()
    wav(sound / 'hit.wav', 1400, .4, .08)
    wav(sound / 'ambience.wav', 900, 1, .01)
    wav(sound / 'new-music.wav', 330, 4, .04)
    palette = sound / 'palette.json'
    palette.write_text(json.dumps({'version': 2,
        'roles': {'hit': {'takes': ['hit.wav'], 'sync': 'attack', 'points_s': [0]},
                  'ambience': {'takes': ['ambience.wav'], 'loop': True, 'crossfade_ms': 50}},
        'music': {'file': 'new-music.wav'},
        'bed': {'role': 'ambience', 'fade_in_ms': 0, 'fade_out_ms': 0},
        'voice': {'file': str((stems / 'dialogue.wav').resolve())}}), encoding='utf-8')
    edits = sound / 'edits.json'
    edits.write_text(json.dumps({join['id']: {'action': 'keep', 'role': 'hit'}}), encoding='utf-8')
    code, spot_text = tool('spot_cues.py', version / 'edit-cues.json', '--out-dir', sound / 'spot',
                           '--palette', palette, '--edits', edits)
    spotted = sound / 'spot' / 'cues.spotted.json'
    duration = float(manifest['duration_s'])
    buses = sound / 'mix'
    if code == 0 and spotted.is_file():
        code, mix_text = tool('mix_cues.py', spotted, palette, '--out-dir', buses, '--duration', duration,
                              '--master', 'none', '--duck-default-db', '6', '--voice-separation-lu', '0.01')
    else:
        mix_text = spot_text
    report_path = buses / 'mix-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('attach mix: spotted join and processed mixer buses are produced',
           code == 0 and report.get('ducking', {}).get('dips', 0) > 0, mix_text[-500:])
    if code != 0:
        return
    check_code, check_text = tool('check.py', project, '--version', 'v001', '--no-speech')
    checked_old = (version / 'checks.json').is_file()
    record('attach mix: the source version can carry an existing check',
           check_code in (0, 1) and checked_old, check_text[-300:])
    before = tree(version)
    code, attach_text = tool('cut.py', 'attach-mix', project, '--version', 'v001', '--buses', buses,
                             '--report', report_path)
    attached = project / 'cuts' / 'v002'
    record('attach mix: the processed buses make a new version and leave the original byte-identical',
           code == 0 and (attached / 'manifest.json').is_file() and tree(version) == before, attach_text[-700:])
    if code != 0 or not (attached / 'manifest.json').is_file():
        return
    record('attach mix: old QA results are not copied into the new version',
           not (attached / 'checks.json').exists() and not (attached / 'qa').exists(), '')
    current = json.loads((attached / 'manifest.json').read_text(encoding='utf-8'))
    provenance = current.get('mix') or {}
    reference = hashlib.sha256((stems / 'dialogue.wav').read_bytes()).hexdigest()
    record('attach mix: provenance records every bus, retained stem and dialogue reference',
           provenance.get('voice_reference') == reference and set(provenance.get('buses', {})) == {'music', 'effects', 'bed'}
           and {'dialogue', 'music', 'nat'} <= set(provenance.get('stems', {}))
           and provenance.get('fades') == 'v001' and provenance.get('master') == 'v001', str(provenance)[:500])
    attached_cues_hash = hashlib.sha256((attached / 'edit-cues.json').read_bytes()).hexdigest()
    record('attach mix: the new version binds the spotted list used by the mixer',
           attached_cues_hash == report.get('inputs', {}).get('cues')
           and current.get('identity', {}).get('cues_sha256') == attached_cues_hash,
           f"version {attached_cues_hash}; mixer {report.get('inputs', {}).get('cues')}")
    delivered = read(attached / 'preview.mp4')
    voice, music, natural = (read(p) for p in required)
    at = float(join['t'])
    sample_at = min(.6, max(.45, at - .4))
    span = (sample_at, sample_at + .15)
    ratios = {}
    for label, original, hz in (('dialogue', voice, 440), ('music', music, 220), ('effects', natural, 660)):
        reference_level = amplitude(original, hz, *span)
        actual_level = amplitude(delivered, hz, *span)
        ratios[label] = 20*math.log10(max(actual_level, 1e-12)/max(reference_level, 1e-12))
    record('attach mix: dialogue and original music and effects appear once',
           all(abs(v) < .2 for v in ratios.values()), str(ratios))
    fade = json.loads((version / 'edit.json').read_text(encoding='utf-8')).get('film_fades') or {}
    early = (.15, .25)
    fade_ratio = amplitude(delivered, 220, *early) / max(amplitude(music, 220, *early), 1e-12)
    expected_fade = sum(early) / 2 / max(float(fade.get('in', 0)), 1e-12)
    fade_error = 20*math.log10(max(fade_ratio, 1e-12)/max(expected_fade, 1e-12))
    record('attach mix: the version fade is applied once',
           fade.get('in', 0) >= .3 and abs(fade_error) < .8, f'fade error {fade_error:.3f} dB; settings {fade}')
    quiet = (max(.45, at-.35), max(.45, at-.35)+.12)
    during = (at+.08, at+.20)
    music_before = amplitude(delivered, 330, *quiet)
    music_during = amplitude(delivered, 330, *during)
    duck_db = 20*math.log10(max(music_during, 1e-12)/max(music_before, 1e-12))
    expected_depth = (report.get('ducking', {}).get('events') or [{}])[0].get('depth_db', 0)
    record('attach mix: the delivered music dips under the hit by the reported depth',
           abs(duck_db + expected_depth) < .5, f'actual {duck_db:.3f} dB; reported -{expected_depth} dB')
    record('attach mix: new effect and ambience are present in the delivery',
           amplitude(delivered, 1400, *during) > .005 and amplitude(delivered, 900, *quiet) > .002,
           f'hit {amplitude(delivered, 1400, *during):.5f}; bed {amplitude(delivered, 900, *quiet):.5f}')
    cl_spec = importlib.util.spec_from_file_location('attach_cue_list', Path(scripts_dir) / 'cue_list.py')
    cl = importlib.util.module_from_spec(cl_spec)
    cl_spec.loader.exec_module(cl)
    old_picture = cl.picture_identity(version / 'preview.mp4')
    new_picture = cl.picture_identity(attached / 'preview.mp4')
    record('attach mix: packet hash, geometry and frame schedule survive the mux',
           old_picture['sha256'] == new_picture['sha256']
           and cl.geometry_compare(old_picture['geometry'], new_picture['geometry'])[0] == 'equal'
           and not cl.compare_schedules(old_picture['schedule'], new_picture['schedule']), '')
    record('attach mix: the attached cue list is fresh against the new version',
           cl.check(attached / 'edit-cues.json', attached).state == 'fresh', '')
    check_code, check_text = tool('check.py', project, '--version', 'v002', '--no-speech')
    record('attach mix: check.py runs on the attached version',
           check_code in (0, 1) and (attached / 'checks.json').is_file(), check_text[-300:])
    if (attached / 'checks.json').is_file():
        verify_code, verify_text = tool('check.py', '--verify', attached / 'checks.json')
        record('attach mix: the new check remains current for its recorded inputs',
               verify_code == 0, verify_text[-300:])
    code, replace_text = tool('cut.py', 'attach-mix', project, '--version', 'v001', '--buses', buses,
                              '--report', report_path, '--replace', 'music')
    replaced = project / 'cuts' / 'v003'
    new_manifest = json.loads((replaced / 'manifest.json').read_text(encoding='utf-8')) if code == 0 else {}
    record('attach mix: replacing music removes only the original music stem',
           code == 0 and not (replaced / 'stems' / 'music.wav').exists()
           and (replaced / 'stems' / 'dialogue.wav').exists() and (replaced / 'stems' / 'nat.wav').exists()
           and new_manifest.get('mix', {}).get('replaced') == ['music'], replace_text[-500:])
    if code == 0:
        replaced_audio = read(replaced / 'preview.mp4')
        old_level = amplitude(delivered, 220, *span)
        new_level = amplitude(replaced_audio, 220, *span)
        preserved = {}
        for label, hz in (('dialogue', 440), ('effects', 660), ('new music', 330)):
            a = amplitude(delivered, hz, *span)
            b = amplitude(replaced_audio, hz, *span)
            preserved[label] = 20*math.log10(max(b, 1e-12)/max(a, 1e-12))
        record('attach mix: replacement removes the original music from delivered audio',
               new_level < .02*old_level and all(abs(value) < .3 for value in preserved.values()),
               f'old music {old_level:.6f} to {new_level:.6f}; preserved {preserved}')
    changed_bus = buses / 'effects.wav'
    unchanged = changed_bus.read_bytes()
    changed_bus.write_bytes(unchanged + b'changed')
    code, swapped = tool('cut.py', 'attach-mix', project, '--version', 'v001', '--buses', buses,
                         '--report', report_path)
    changed_bus.write_bytes(unchanged)
    record('attach mix: a bus changed under its report is refused',
           code == 2 and 'does not match' in swapped and not (project / 'cuts' / 'v004').exists(), swapped[-300:])
    for name in ('voice.wav', 'mix.wav'):
        code, rejected = tool('cut.py', 'attach-mix', project, '--version', 'v001', '--buses', buses / name,
                              '--report', report_path)
        record(f'attach mix: {name} cannot be offered as the bus folder',
               code == 2 and '--buses' in rejected, rejected[-200:])
    code, master_render = tool('cut.py', 'render', project, '--final', '--master', 'web')
    master_source = project / 'cuts' / 'v004'
    if code not in (0, 1) or not (master_source / 'manifest.json').is_file():
        record('attach mix: a version with a master renders', False, master_render[-500:])
        return
    record('attach mix: a version with a master renders', True, master_render[-200:])
    master_palette = sound / 'master-palette.json'
    master_spec = json.loads(palette.read_text(encoding='utf-8'))
    master_spec['voice']['file'] = str((master_source / 'stems' / 'dialogue.wav').resolve())
    master_palette.write_text(json.dumps(master_spec), encoding='utf-8')
    master_buses = sound / 'master-mix'
    code, master_mix = tool('mix_cues.py', spotted, master_palette, '--out-dir', master_buses,
                            '--duration', duration, '--master', 'none', '--duck-default-db', '6',
                            '--voice-separation-lu', '0.01')
    if code == 0:
        code, master_attach = tool('cut.py', 'attach-mix', project, '--version', 'v004', '--buses', master_buses,
                                   '--report', master_buses / 'mix-report.json')
    else:
        master_attach = master_mix
    master_version = project / 'cuts' / 'v005'
    if code != 0 or not (master_version / 'audio-master.json').is_file():
        record('attach mix: the version master is applied once to the new mix', False, master_attach[-500:])
        return
    master_report = json.loads((master_version / 'audio-master.json').read_text(encoding='utf-8'))
    mastered = read(master_version / 'preview.mp4')
    mastered_voice = read(master_source / 'stems' / 'dialogue.wav')
    second = master_report.get('second_pass') or {}
    try:
        reported_gain = float(second['output_i']) - float(second['input_i'])
        audible_gain = 20*math.log10(max(amplitude(mastered, 440, *span), 1e-12)
                                     / max(amplitude(mastered_voice, 440, *span), 1e-12))
        gain_error = audible_gain - reported_gain
    except (KeyError, ValueError, TypeError):
        reported_gain = audible_gain = gain_error = float('inf')
    record('attach mix: the version master is applied once to the new mix',
           master_report.get('actual_mode') == 'linear' and abs(gain_error) < .5
           and master_report.get('target_lufs') == -16,
           f"mode={master_report.get('actual_mode')}; reported gain={reported_gain:.3f}; "
           f'dialogue gain={audible_gain:.3f}; error={gain_error:.3f}')

    # A real mixer report for an all-scoped silence, bound to this synthetic version.
    quiet = {'id': 'quiet-test', 't': .55, 't_end': .75, 'scale': 'silence', 'scope': 'all',
             'sound': 'silent', 'decision': 'hold the added sound'}
    version_cues = version / 'edit-cues.json'
    version_list = json.loads(version_cues.read_text(encoding='utf-8'))
    version_list['events'].append(quiet)
    version_cues.write_text(json.dumps(version_list), encoding='utf-8')
    manifest_path = version / 'manifest.json'
    quiet_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    quiet_hash = hashlib.sha256(version_cues.read_bytes()).hexdigest()
    quiet_manifest['files']['edit-cues.json'] = quiet_hash
    quiet_manifest['identity']['cues_sha256'] = quiet_hash
    manifest_path.write_text(json.dumps(quiet_manifest), encoding='utf-8')
    spotted_list = json.loads(spotted.read_text(encoding='utf-8'))
    spotted_list['events'].append(quiet)
    quiet_cues = sound / 'quiet-cues.json'
    quiet_cues.write_text(json.dumps(spotted_list), encoding='utf-8')
    quiet_buses = sound / 'quiet-mix'
    code, quiet_mix = tool('mix_cues.py', quiet_cues, palette, '--out-dir', quiet_buses,
                           '--duration', duration, '--master', 'none', '--duck-default-db', '6',
                           '--voice-separation-lu', '0.01')
    quiet_report = quiet_buses / 'mix-report.json'
    if code != 0 or not quiet_report.is_file():
        record('attach mix: all-scoped fixture makes a bound mixer report', False, quiet_mix[-700:])
        return
    record('attach mix: all-scoped fixture makes a bound mixer report', True, '')
    original = tree(version)
    strict_code, strict_text = tool('cut.py', 'attach-mix', project, '--version', 'v001',
                                    '--buses', quiet_buses, '--report', quiet_report, '--strict')
    record('attach mix: strict all-scoped silence refuses without a new version',
           strict_code == 2 and not (project / 'cuts' / 'v006').exists() and tree(version) == original
           and 'dialogue' in strict_text and '0.55' in strict_text and '0.75' in strict_text
           and '--replace ROLE' in strict_text and 'scope' in strict_text, strict_text[-700:])
    look_code, look_text = tool('cut.py', 'attach-mix', project, '--version', 'v001',
                                '--buses', quiet_buses, '--report', quiet_report)
    looked = project / 'cuts' / 'v006'
    looked_manifest = json.loads((looked / 'manifest.json').read_text(encoding='utf-8')) \
        if (looked / 'manifest.json').is_file() else {}
    record('attach mix: all-scoped silence publishes with a look and leaves version stems untouched',
           look_code == 1 and tree(version) == original and looked_manifest
           and all((looked / 'stems' / path.name).is_file()
                   and (looked / 'stems' / path.name).read_bytes() == path.read_bytes() for path in required)
           and all(name in look_text for name in ('dialogue', 'music', 'nat', '0.55', '0.75',
                                                   '--replace ROLE', 'scope'))
           and 'look' in look_text.lower()
           and any('dialogue' in note and '0.55' in note and '0.75' in note
                   for note in looked_manifest.get('notes', [])), look_text[-1000:])
    replace_code, replace_look = tool('cut.py', 'attach-mix', project, '--version', 'v001',
                                      '--buses', quiet_buses, '--report', quiet_report, '--replace', 'music')
    replaced_quiet = project / 'cuts' / 'v007'
    record('attach mix: replacing a noisy stem removes its look and keeps the other stems',
           replace_code == 1 and tree(version) == original
           and not (replaced_quiet / 'stems' / 'music.wav').exists()
           and all((replaced_quiet / 'stems' / path.name).is_file()
                   and (replaced_quiet / 'stems' / path.name).read_bytes() == path.read_bytes()
                   for path in (required[0], required[2]))
           and 'retained stem music (role music)' not in replace_look
           and 'retained stem dialogue' in replace_look and 'retained stem nat' in replace_look,
           replace_look[-1000:])


def run_attach_mix_cases(tool, record, j, scripts_dir):
    preflight_cases(tool, record, j, scripts_dir)
    rendered_cases(tool, record, j, scripts_dir)


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as temp:
        results = []
        def tool(name, *args):
            p = subprocess.run([sys.executable, str(Path(__file__).parents[1] / name), *map(str, args)],
                               capture_output=True, text=True)
            return p.returncode, p.stdout + p.stderr
        def record(name, ok, detail):
            results.append(ok)
            print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ': ' + detail))
        runner = run_attach_mix_cases if '--integration' in sys.argv else preflight_cases
        runner(tool, record, lambda name: str(Path(temp) / name), Path(__file__).parents[1])
        sys.exit(0 if all(results) else 1)
