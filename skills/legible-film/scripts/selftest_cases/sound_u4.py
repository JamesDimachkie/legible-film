"""Known-answer tests for the sound lane's mixer contract."""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import wave

import numpy as np


def run_sound_u4_cases(tool, record, j, scripts_dir):
    root = Path(j('sound-u4-cases'))
    root.mkdir(parents=True, exist_ok=True)
    rate = 48000
    cue_spec = importlib.util.spec_from_file_location('sound_u4_cue_list', Path(scripts_dir) / 'cue_list.py')
    cue_list = importlib.util.module_from_spec(cue_spec)
    cue_spec.loader.exec_module(cue_list)
    page = Path(scripts_dir) / 'testpages' / 'identity'
    listed = cue_list.load(page / 'cues.json')
    if listed.state != 'fresh':
        raise ValueError('the shared synthetic page is not fresh: ' + listed.message)
    picture = dict(listed.picture, path=str(page.resolve()))
    def wav(path, audio):
        with wave.open(str(path), 'wb') as out:
            out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            out.writeframes((np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes())
    def save(path, data):
        if path == cues and data.get('version') != 'v1':
            data = dict(data, version='v2', picture=picture,
                        events=[dict(ev, scale=ev.get('scale', 'contact')) for ev in data.get('events', [])],
                        sections=[dict(section, clock=section.get('clock', 'action'))
                                  for section in data.get('sections', [])])
        path.write_text(json.dumps(data), encoding='utf-8')
    def read_audio(path):
        b = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '2', '-ar', str(rate),
                                     '-f', 'f32le', '-'])
        return np.frombuffer(b, dtype='<f4').reshape(-1, 2)
    take, voice = root / 'take.wav', root / 'voice-source.wav'
    t = np.arange(round(.25 * rate)) / rate
    wav(take, .08 * np.sin(2 * np.pi * 440 * t) * np.minimum(t * 1000, 1))
    t = np.arange(rate * 3) / rate
    wav(voice, .03 * np.sin(2 * np.pi * 190 * t))
    cues, palette, out = root / 'events.json', root / 'palette.json', root / 'mix'
    save(cues, {'version': 'v1', 'events': [{'id': 'legacy', 't': .4, 'role': 'tap'}], 'duration': 1})
    save(palette, {'version': 1, 'roles': {'tap': {'takes': [take.name], 'sync': 'attack', 'points_s': [0]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    expected = np.zeros((rate, 2), dtype='<f4')
    original = read_audio(take)
    expected[round(.4*rate):round(.4*rate)+len(original)] = original
    expected_wav = root / 'expected-legacy.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'f32le', '-ar', str(rate), '-ac', '2', '-i', '-',
                    '-c:a', 'pcm_s24le', '-map_metadata', '-1', '-bitexact', str(expected_wav)],
                   input=expected.tobytes(), check=True, capture_output=True)
    record('sound U4: a v1 list produces the known legacy mix bytes',
           code == 0 and (out / 'mix.wav').read_bytes() == expected_wav.read_bytes(), output[-200:])
    save(cues, {'version': 'v1', 'events': [{'id': 'legacy', 't': .4, 'role': 'tap'}], 'duration': 1,
                'sections': [{'id': 'ignored', 'a': 0, 'b': 1, 'gain_db': {'effects': -6}}]})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    record('sound U4: v1 sections do not affect the shared legacy view',
           code == 0 and (out / 'mix.wav').read_bytes() == expected_wav.read_bytes(), output[-200:])
    save(cues, {'version': 'v1', 'events': [{'id': 'legacy', 't': .4, 'role': 'tap',
                                             'scale': 'turn', 'lead_ms': -100}], 'duration': 1})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    record('sound U4: v1 events use the shared contact scale',
           code == 0 and (out / 'mix.wav').read_bytes() == expected_wav.read_bytes(), output[-200:])
    events = [{'id': f'p{i}', 't': .15 + i*.4, 'scale': 'contact', 'role': 'tap',
               'pan': -1 + 2*i/5, 'pitch_st': i} for i in range(6)]
    save(cues, {'events': events, 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'sync': 'attack', 'points_s': [0]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report_path = out / 'mix-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    if (out / 'effects.wav').exists():
        audio = read_audio(out / 'effects.wav')
        pans, energies, pitches = [], [], []
        for event in events:
            start = round((event['t'] + .04) * rate)
            x = audio[start:start + round(.12 * rate)]
            rms = np.sqrt(np.mean(x.astype(np.float64)**2, axis=0))
            pans.append(float(rms[1] - rms[0]))
            energies.append(float(np.linalg.norm(rms)))
            spectrum = np.abs(np.fft.rfft(x.mean(axis=1) * np.hanning(len(x)), n=131072))
            k = int(np.argmax(spectrum))
            pitches.append(k * rate / 131072)
        cents = [1200 * np.log2(actual / (440 * 2**(i/12))) for i, actual in enumerate(pitches)]
        spread = 20 * np.log10(max(energies) / min(energies))
    else:
        pans, cents, spread = [], [999], 999
    record('sound U4: six pitches rise by semitones within 10 cents',
           code == 0 and len(cents) == 6 and max(map(abs, cents)) < 10, str(cents) + output[-200:])
    record('sound U4: pan is monotonic and preserves power',
           len(pans) == 6 and all(a < b for a, b in zip(pans, pans[1:])) and spread < .1,
           str((pans, spread)))
    inputs, outputs = report.get('inputs', {}), report.get('outputs', {})
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    record('sound U4: report binds cue, palette and written audio',
           inputs.get('cues') == digest(cues) and inputs.get('palette') == digest(palette)
           and outputs.get('effects.wav') == digest(out / 'effects.wav'), str((inputs, outputs)))
    numeric_pan_audio = (out / 'effects.wav').read_bytes()
    positioned = [dict(event, x=event['pan'], pan='x') for event in events]
    save(cues, {'events': positioned, 'duration': 2.8})
    x_out = root / 'mix-x'
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', x_out, '--master', 'none')
    record('sound U4: pan from x matches equivalent numeric pan',
           code == 0 and (x_out / 'effects.wav').read_bytes() == numeric_pan_audio, output[-200:])
    save(cues, {'events': [{'id': 'prior', 't': .4, 'role': 'tap'},
                           {'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                            'sound': 'silent', 'scope': 'effects'}], 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'sync': 'attack', 'points_s': [0]}},
                   'voice': {'file': voice.name}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    if (out / 'voice.wav').exists():
        actual, original = read_audio(out / 'voice.wav'), read_audio(voice)[:round(2.8 * rate)]
        voice_difference = float(np.max(np.abs(actual-original)))
    else:
        voice_difference = 1
    record('sound U4: effects-scoped silence leaves voice untouched',
           code == 0 and voice_difference < 2e-7, str(voice_difference) + output[-150:])
    effects = read_audio(out / 'effects.wav')
    before = np.sqrt(np.mean(effects[round(.43*rate):round(.49*rate)].astype(np.float64)**2))
    during = np.sqrt(np.mean(effects[round(.55*rate):round(.62*rate)].astype(np.float64)**2))
    attenuation = 20*np.log10(max(during, 1e-12) / max(before, 1e-12))
    record('sound U4: effects-scoped silence attenuates an existing tail', attenuation < -59.5, str(attenuation))
    report = json.loads(report_path.read_text(encoding='utf-8'))
    recorded_inputs = report.get('inputs', {}).get('files', {})
    recorded_outputs = report.get('outputs', {})
    record('sound U4: report hashes each read file and each written WAV',
           all(recorded_inputs.get(str(path.resolve())) == digest(path) for path in (cues, palette, take, voice))
           and all(recorded_outputs.get(name) == digest(out / name)
                   for name in ('effects.wav', 'music.wav', 'bed.wav', 'voice.wav', 'mix.wav')),
           str((recorded_inputs, recorded_outputs))[:300])
    tail_level = float(np.sqrt(np.mean(effects[round(.5*rate):round(1.5*rate)].astype(np.float64)**2)))
    measured_tail = 20*np.log10(max(tail_level, 1e-12))
    tail_row = (report.get('silent_window_tails') or [{}])[0]
    record('sound U4: silence tail levels reflect bus attenuation',
           abs(tail_row.get('rms_dbfs', 999) - measured_tail) < .2,
           str((tail_row.get('rms_dbfs'), measured_tail)))

    save(cues, {'events': [{'id': 'a', 't': .3, 'role': 'tap', 'hero': True},
                           {'id': 'b', 't': .32, 'role': 'tap'},
                           {'id': 'c', 't': 1.5, 'role': 'tap'}], 'duration': 2.8,
                'sections': [{'id': 'one', 'a': 0, 'b': 1},
                             {'id': 'two', 'a': 1, 'b': 2.8, 'gain_db': {'effects': -6}}]})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'sync': 'attack', 'points_s': [0]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    effects = read_audio(out / 'effects.wav')
    first = np.sqrt(np.mean(effects[round(.3*rate):round(.315*rate)].astype(np.float64)**2))
    second = np.sqrt(np.mean(effects[round(1.5*rate):round(1.515*rate)].astype(np.float64)**2))
    delta = 20*np.log10(second/first)
    record('sound U4: section effects gain applies once', code == 0 and abs(delta + 6) < .2, str(delta))
    presence = {row['id']: row for row in report.get('presence', [])}
    presence_delta = (presence.get('c', {}).get('effect_dbfs_rms', 999)
                      - presence.get('a', {}).get('effect_dbfs_rms', 0))
    record('sound U4: presence reflects the processed section gain',
           abs(presence_delta + 6) < .2, str(presence_delta))
    record('sound U4: simultaneous-band masking and hero margin are reported',
           any(set(row['ids']) == {'a', 'b'} for row in report.get('masking', []))
           and any(row['id'] == 'a' for row in report.get('hero_presence', [])),
           str((report.get('masking'), report.get('hero_presence'))))
    long_take = root / 'long.wav'
    long_signal = np.zeros(rate, np.float32)
    long_signal[:round(.1*rate)] = .08*np.sin(2*np.pi*440*np.arange(round(.1*rate))/rate)
    wav(long_take, long_signal)
    save(cues, {'events': [{'id': 'short', 't': .3, 'role': 'tap'},
                           {'id': 'long', 't': .32, 'role': 'other'}], 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'sync': 'attack', 'points_s': [0]},
                                           'other': {'takes': [long_take.name], 'sync': 'attack', 'points_s': [0]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('sound U4: masking compares the nearby sound, not long silent tails',
           code == 0 and any(set(row['ids']) == {'short', 'long'} for row in report.get('masking', [])),
           str(report.get('masking')) + output[-100:])

    save(cues, {'events': [], 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {}, 'music': {'file': voice.name}})
    conform = root / 'conform.json'
    save(conform, {'cues_sha256': digest(cues), 'music_sha256': digest(voice), 'bed_sha256': digest(take)})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--music', take,
                        '--conform', conform, '--master', 'none')
    record('sound U4: correctly bound music is accepted', code == 0, output[-200:])
    music = read_audio(out / 'music.wav')[:round(.2*rate)]
    bed = read_audio(take)[:round(.2*rate)]
    difference = float(np.max(np.abs(music - bed)))
    record('sound U4: conformed bed keeps its film-clock samples and gain',
           code == 0 and difference < 2e-7, str(difference))
    save(cues, {'events': [], 'duration': 2.7})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--music', take,
                        '--conform', conform, '--master', 'none')
    record('sound U4: a retimed cue list refuses the bed', code == 2 and 'stale bed' in output, output[-200:])
    save(conform, {'cues_sha256': digest(cues), 'music_sha256': digest(voice), 'bed_sha256': digest(take)})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--music', voice,
                        '--conform', conform, '--master', 'none')
    record('sound U4: a swapped bed is refused', code == 2 and 'stale bed' in output, output[-200:])
    save(palette, {'version': 2, 'roles': {}, 'music': {'file': take.name}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--music', take,
                        '--conform', conform, '--master', 'none')
    record('sound U4: a swapped palette music source is refused', code == 2 and 'stale bed' in output,
           output[-200:])
    save(palette, {'version': 2, 'roles': {}, 'music': {'file': voice.name}})
    save(cues, {'events': [], 'duration': 2.8,
                'sections': [{'id': 'one', 'a': 0, 'b': 2.8, 'gain_db': {'music': -2}}]})
    save(conform, {'cues_sha256': digest(cues), 'music_sha256': digest(voice), 'bed_sha256': digest(take)})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--music', take,
                        '--conform', conform, '--master', 'none')
    record('sound U4: a second section music gain is refused', code == 2 and 'duplicate' in output, output[-200:])
    save(cues, {'events': [{'id': 'turn', 't': 1, 'scale': 'turn', 'lead_ms': -100, 'role': 'tap'},
                           {'id': 'follow', 't': 1.5, 't_end': 2.0, 'scale': 'follow', 'role': 'tap'}],
                'duration': 2.8})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'sync': 'attack', 'points_s': [0]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    rows = report.get('events_placed') or []
    record('sound U4: turn lead moves the take and a follow span places none',
           code == 0 and len(rows) == 1 and rows[0]['id'] == 'turn'
           and abs(rows[0]['placed_sync_s'] - .9) < 1/rate and rows[0].get('picture_t') == 1, str(rows))
    save(cues, {'events': [{'id': 'end', 't': 1, 'role': 'tap', 'sync': 'end', 'pitch_st': 12}],
                'duration': 2.8})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'sync': 'end', 'points_s': [.25]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    row = (report.get('events_placed') or [{}])[0]
    record('sound U4: pitch-shifted end sync is remeasured and aligned',
           code == 0 and row.get('point_source') == 'measured' and .12 < row.get('point_s', 0) < .13
           and abs(row.get('placed_sync_s', 0) - 1) < 1/rate, str(row))
    save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                            'sound': 'silent', 'scope': 'all'}], 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {}, 'voice': {'file': voice.name}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    record('sound U4: all-scoped silence requires a decision before touching voice',
           code == 2 and 'decision' in output, output[-200:])
    save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                            'sound': 'silent', 'scope': 'all', 'decision': 'the voice rests'}], 'duration': 2.8})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    processed_voice = read_audio(out / 'voice.wav')
    reference_voice = read_audio(voice)
    interval = slice(round(.7*rate), round(1.3*rate))
    voice_ratio = np.sqrt(np.mean(processed_voice[interval].astype(np.float64)**2)) / max(
        1e-12, np.sqrt(np.mean(reference_voice[interval].astype(np.float64)**2)))
    record('sound U4: an all-scoped decision attenuates the mixer voice by 60 dB',
           code == 0 and voice_ratio < .00102, str(voice_ratio) + output[-150:])
    silent_take = root / 'zero.wav'
    wav(silent_take, np.zeros(round(.1*rate)))
    save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                            'sound': 'silent', 'scope': 'new'},
                           {'id': 'new', 't': .7, 'role': 'tap'}], 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [silent_take.name], 'points_s': [0]}}})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    record('sound U4: a new silent take still violates a silence span',
           code == 1 and any(row.get('take_event_id') == 'new' for row in report.get('silent_window_violations', [])),
           output[-200:])
    save(palette, {'version': 2, 'roles': {'tap': {'takes': [take.name], 'points_s': [0]}}})
    for scope in ('effects', 'all'):
        save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                                'sound': 'silent', 'scope': scope},
                               {'id': 'suppressed', 't': .7, 'role': 'tap'}], 'duration': 2.8})
        code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        processed = read_audio(out / 'effects.wav') if (out / 'effects.wav').exists() else np.ones((1, 2))
        quiet_peak = float(np.max(np.abs(processed[round(.7*rate):round(.95*rate)])))
        record(f'sound U4: a suppressed take within {scope} silence does not violate it',
               code == 0 and not report.get('silent_window_violations') and quiet_peak < .001,
               f'exit {code}; peak {quiet_peak}; violations {report.get("silent_window_violations")}; {output[-150:]}')
        save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                                'sound': 'silent', 'scope': scope},
                               {'id': 'ramp-edge', 't': .5, 'role': 'tap'}], 'duration': 2.8})
        code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
        record(f'sound U4: an audible overlap at the {scope} ramp is still a violation',
               code == 1 and any(row.get('take_event_id') == 'ramp-edge'
                                 for row in report.get('silent_window_violations', [])),
               f'exit {code}; violations {report.get("silent_window_violations")}; {output[-150:]}')
    save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                            'sound': 'silent', 'scope': 'effects'},
                           {'id': 'boosted', 't': .7, 'role': 'tap'}], 'duration': 2.8,
                'sections': [{'id': 'whole', 'a': 0, 'b': 2.8, 'gain_db': {'effects': 30}}]})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    boosted = read_audio(out / 'effects.wav') if (out / 'effects.wav').exists() else np.zeros((1, 2))
    boosted_peak = float(np.max(np.abs(boosted[round(.7*rate):round(.95*rate)])))
    record('sound U4: a section gain that leaves a ramped-silence overlap audible is flagged',
           code == 1 and boosted_peak > .001 and any(row.get('take_event_id') == 'boosted'
                                                      for row in report.get('silent_window_violations', [])),
           f'exit {code}; peak {boosted_peak}; {output[-150:]}')
    save(cues, {'events': [{'id': 'quiet', 't': .5, 't_end': 1.5, 'scale': 'silence',
                            'sound': 'silent', 'scope': 'effects'},
                           {'id': 'normalized', 't': .7, 'role': 'tap'}], 'duration': 2.8})
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', out, '--master', 'none', '--gain-to-lufs', '-35')
    report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    boosted = read_audio(out / 'effects.wav') if (out / 'effects.wav').exists() else np.zeros((1, 2))
    boosted_peak = float(np.max(np.abs(boosted[round(.7*rate):round(.95*rate)])))
    record('sound U4: final gain that makes a ramped-silence overlap audible is flagged',
           code == 1 and report.get('gain_applied_db', 0) > 0 and boosted_peak > .001
           and any(row.get('take_event_id') == 'normalized' for row in report.get('silent_window_violations', [])),
           f'exit {code}; gain {report.get("gain_applied_db")}; peak {boosted_peak}; {output[-150:]}')
    save(cues, {'events': [], 'duration': 2.8})
    save(palette, {'version': 2, 'roles': {}})
    collision = root / 'collision'
    code, output = tool('mix_cues.py', cues, palette, '--out-dir', collision, '--master', 'none',
                        '--json', collision / 'effects.wav')
    record('sound U4: a report cannot overwrite a WAV output',
           code == 2 and not (collision / 'effects.wav').exists(), output[-200:])


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
        run_sound_u4_cases(tool, record, lambda name: str(Path(temp) / name), Path(__file__).parents[1])
        sys.exit(0 if all(results) else 1)
