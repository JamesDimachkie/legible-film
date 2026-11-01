"""Known-answer cue detection and input-custody regressions."""
import importlib.util
import json
import os
from pathlib import Path
import wave

import numpy as np


def run_cues_cases(tool, record, j, scripts_dir):
    """Check correlation after loud material and protect all cue-check inputs."""
    root = Path(j('cues-cases'))
    root.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('lf_cue_house_cases', Path(scripts_dir) / 'cue_onsets.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rate = 48000
    times = np.arange(int(.05 * rate)) / rate
    reference = .65 * np.sin(2 * np.pi * 900 * times) * np.exp(-70 * times)
    samples = np.zeros(rate, dtype=np.float64)
    samples[:rate // 4] = np.random.default_rng(7).uniform(-.9, .9, rate // 4)
    samples[rate // 2:rate // 2 + len(reference)] = reference

    def wav(path, signal):
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            stream.writeframes((np.clip(signal, -1, 1) * 32767).astype('<i2').tobytes())

    audio = root / 'audio.wav'
    ref = root / 'reference.wav'
    wav(audio, samples)
    wav(ref, reference)
    cues = root / 'cues.json'
    cues.write_text(json.dumps({'events': [{'id': 'cue', 't': .5, 'window_ms': 120,
                                            'tolerance_ms': 5, 'ref': ref.name}]}), encoding='utf-8')
    row = module.reference_match(samples, reference, .5, 'attack', 120, 5, False, str(ref))
    record('cues: in-memory match ignores silence after loud audio',
           row.get('status') == 'on cue' and abs(row.get('onset_s', 0) - .5) <= .001
           and -1 <= row.get('correlation', 2) <= 1, str(row))
    report_path = root / 'result.json'
    code, output = tool('cue_onsets.py', audio, cues, '--json', report_path)
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    row = (report.get('rows') or [{}])[0]
    record('cues: WAV command finds the on-cue reference with bounded correlation',
           code == 0 and row.get('status') == 'on cue' and abs(row.get('onset_s', 0) - .5) <= .001
           and -1 <= row.get('correlation', 2) <= 1, str(row) + output[-200:])
    second = row.get('second_best')
    margin = row.get('margin')
    record('cues: second peak and margin refer to actual bounded candidates',
           row.get('competitor_exclusion_s') == .05 and
           ((second is None and margin is None) or
            (isinstance(second, (int, float)) and -1 <= second <= 1 and isinstance(margin, (int, float))
             and abs(margin - (row.get('correlation', 0) - second)) < .0002)), str(row))
    repeated = np.zeros(rate, dtype=np.float64)
    repeated[rate // 2:rate // 2 + len(reference)] = reference
    repeated[round(.57 * rate):round(.57 * rate) + len(reference)] = reference
    competing = module.reference_match(repeated, reference, .5, 'attack', 120, 5, False, str(ref))
    record('cues: two real reference matches remain inconclusive',
           competing.get('status') == 'inconclusive' and competing.get('second_best', 0) >= .99
           and competing.get('margin', 1) <= .001, str(competing))
    adjacent = np.zeros(rate, dtype=np.float64)
    adjacent[rate // 2:rate // 2 + len(reference)] = reference
    adjacent[rate // 2 + len(reference):rate // 2 + 2 * len(reference)] = reference
    boundary = module.reference_match(adjacent, reference, .5, 'attack', 120, 5, False, str(ref))
    record('cues: a second match exactly one reference length away remains a competitor',
           boundary.get('status') == 'inconclusive' and boundary.get('second_best', 0) == 1.0
           and boundary.get('margin') == 0.0, str(boundary))
    silent = module.reference_match(np.zeros(rate), reference, .5, 'attack', 120, 5, False, str(ref))
    absent = module.reference_match(np.zeros(rate), reference, .5, 'attack', 120, 5, True, str(ref))
    record('cues: digital silence supplies no correlation candidate',
           silent.get('status') == 'missing' and absent.get('status') == 'quiet as intended'
           and silent.get('correlation') is None and silent.get('second_best') is None, str((silent, absent)))
    quiet = np.zeros(rate)
    quiet[:rate // 4] = .9
    env = module.envelope_db(quiet)
    record('cues: onset envelope measures silence after loud samples without cancellation',
           np.all(np.isfinite(env)) and np.max(env[300:]) <= -175, str((float(np.nanmin(env)), float(np.nanmax(env)))))
    quiet[round(.35 * rate):] = 1e-8
    env = module.envelope_db(quiet)
    expected = 20 * np.log10(1e-8 + 1e-9)
    record('cues: onset envelope retains very quiet energy after a loud section',
           np.max(np.abs(env[400:] - expected)) < .01, str((float(env[400]), float(expected))))

    short_audio = root / 'short.wav'
    short_signal = np.zeros(rate // 10)
    short_signal[2400:2500] = .8
    wav(short_audio, short_signal)
    short_cues = root / 'short-cues.json'
    short_cues.write_text(json.dumps({'events': [{'id': 'short', 't': .05, 'sound': 'required'}]}),
                          encoding='utf-8')
    chance_report = root / 'chance.json'
    code, output = tool('cue_onsets.py', short_audio, short_cues, '--chance', '5', '--json', chance_report)
    chance_data = json.loads(chance_report.read_text(encoding='utf-8')) if chance_report.is_file() else {}
    chance = chance_data.get('summary', {}).get('chance', {})
    record('cues: chance baseline does not sample outside a short file',
           code in (0, 1) and chance.get('sets') == 0 and chance.get('verdict', '').startswith('not run'),
           str(chance) + output[-200:])

    for name in ('audio', 'cues', 'reference'):
        target = {'audio': audio, 'cues': cues, 'reference': ref}[name]
        before = target.read_bytes()
        code, output = tool('cue_onsets.py', audio, cues, '--json', target)
        unchanged = target.read_bytes() == before
        record('cues: report cannot replace ' + name,
               code == 2 and unchanged and 'input' in output.lower(), output[-250:])
        if not unchanged:
            target.write_bytes(before)
    alias = str(root) + os.sep + '.' + os.sep + cues.name
    before = cues.read_bytes()
    code, output = tool('cue_onsets.py', audio, cues, '--json', alias)
    unchanged = cues.read_bytes() == before
    record('cues: alternate spelling cannot replace the cue file',
           code == 2 and unchanged and 'input' in output.lower(), output[-250:])
    if not unchanged:
        cues.write_bytes(before)
    hardlink = root / 'audio-link.json'
    try:
        os.link(audio, hardlink)
        linked = True
    except OSError as error:
        linked = False
        print('SKIP  cues: hard-link collision (' + str(error) + ')')
    if linked:
        before = audio.read_bytes()
        code, output = tool('cue_onsets.py', audio, cues, '--json', hardlink)
        record('cues: hard-linked report cannot replace audio',
               code == 2 and audio.read_bytes() == before and 'input' in output.lower(), output[-250:])
