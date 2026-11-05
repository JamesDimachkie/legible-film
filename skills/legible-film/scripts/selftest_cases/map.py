"""Offline synthetic known-answer checks for the map lane."""
import json
import subprocess
from pathlib import Path

from PIL import Image


def check_transcript_protection_and_cleanup(tool, record, j, scripts_dir):
    """Exercise direct transcription, its write race, and abandoned temporary files."""
    import contextlib
    import importlib.util
    import io
    import os
    import sys
    from unittest.mock import patch

    code, help_text = tool('map.py', '--help')
    record('map: top-level usage shows the relink command',
           code == 0 and 'python map.py relink PROJECT' in help_text, help_text[-500:])
    quick = (Path(scripts_dir).parent / 'paths' / 'quick.md').read_text(encoding='utf-8')
    captions_step = next((p for p in quick.split('\n\n') if 'Captions come from' in p), '')
    record('map: standalone captions give the transcriber a prompt for names and terms',
           'transcribe.py' in captions_step and '--prompt' in captions_step, captions_step)
    root = Path(j('direct-transcribe-project'))
    media = Path(j('direct-transcribe.wav'))
    source = Path(j('direct-transcribe.srt'))
    source.write_text('1\n00:00:00,100 --> 00:00:00,600\nWrong\n', encoding='utf-8')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=1', str(media)], check=True, capture_output=True)
    code, output = tool('map.py', 'add', root, media, '--role', 'interview')
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    words = folder / 'words.json'
    corrected = json.dumps({'words': [{'id': 'int_01-w000001', 'text': 'Corrected',
                                       'start': .1, 'end': .6}]}) + '\n'
    words.write_text(corrected, encoding='utf-8')
    code, output = tool('transcribe.py', media, '--project', root, '--alias', 'int_01',
                        '--engine', 'import', '--import-file', source)
    after = words.read_text(encoding='utf-8')
    record('map: direct project transcription refuses a corrected transcript',
           code == 2 and after == corrected and '--retranscribe int_01' in output, output[-300:])
    words.write_text(corrected, encoding='utf-8')
    explicit = Path(j('direct-explicit.json'))
    explicit.write_text('old', encoding='utf-8')
    code, output = tool('transcribe.py', media, '--project', root, '--alias', 'int_01', '--out', explicit,
                        '--engine', 'import', '--import-file', source)
    record('map: explicit --out still replaces the named output', code == 0
           and json.loads(explicit.read_text(encoding='utf-8'))['words'][0]['text'] == 'Wrong', output[-300:])
    spec = importlib.util.spec_from_file_location('direct_transcribe_race', Path(scripts_dir) / 'transcribe.py')
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    words.unlink()
    original_import = transcribe.read_import

    def appear(path):
        words.write_text(corrected, encoding='utf-8')
        return original_import(path)

    argv = ['transcribe.py', str(media), '--project', str(root), '--alias', 'int_01',
            '--engine', 'import', '--import-file', str(source)]
    err = io.StringIO()
    with patch.object(sys, 'argv', argv), patch.object(transcribe, 'read_import', side_effect=appear), \
            contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        race_code = transcribe.main()
    record('map: a transcript created during transcription is retained', race_code == 2
           and words.read_text(encoding='utf-8') == corrected, err.getvalue()[-300:])
    legacy = folder / '.words-abandoned.json'
    dead = folder / '.words-2147483647-abandoned.json'
    live = folder / ('.words-' + str(os.getpid()) + '-active.json')
    for path in (legacy, dead, live):
        path.write_text('temporary', encoding='utf-8')
    code, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'skip')
    record('map: next run removes abandoned transcripts and keeps a live worker temporary',
           code == 0 and not legacy.exists() and not dead.exists() and live.exists(), output[-300:])
    old_status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    old_status['running'] = [{'job': 'map int_01', 'progress': 0}]
    (root / 'status.json').write_text(json.dumps(old_status), encoding='utf-8')
    legacy.write_text('unknown owner', encoding='utf-8')
    code, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'skip')
    warned = code == 0 and legacy.exists() and 'earlier map job has no PID' in output
    code, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'skip')
    record('map: a PID-less legacy temporary is disclosed before later cleanup',
           warned and code == 0 and not legacy.exists(), output[-300:])
    spec = importlib.util.spec_from_file_location('map_running_pid', Path(scripts_dir) / 'map.py')
    mapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mapper)
    observed = []

    def stop_at_probe(path):
        observed.extend(json.loads((root / 'status.json').read_text(encoding='utf-8'))['running'])
        raise RuntimeError('intentional stop at probe')

    try:
        with patch.object(mapper, 'probe', side_effect=stop_at_probe):
            mapper.run(root, ['int_01'], 'skip')
    except RuntimeError as error:
        if str(error) != 'intentional stop at probe':
            raise
    record('map: a running map entry records its process ID',
           any(row.get('job') == 'map int_01' and row.get('pid') == os.getpid() for row in observed), str(observed))
    child_code = ('import importlib.util, os, sys\n'
                  'spec = importlib.util.spec_from_file_location("map_crash", sys.argv[1])\n'
                  'module = importlib.util.module_from_spec(spec)\n'
                  'spec.loader.exec_module(module)\n'
                  'def crash(path):\n    os._exit(17)\n'
                  'module.probe = crash\n'
                  'print(os.getpid(), flush=True)\n'
                  'module.run(sys.argv[2], ["int_01"], "skip")\n')
    child = subprocess.Popen([sys.executable, '-I', '-c', child_code, str(Path(scripts_dir) / 'map.py'), str(root)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    child_out, child_error = child.communicate(timeout=30)
    child_pid = int(child_out.decode('ascii').strip())
    crashed = json.loads((root / 'status.json').read_text(encoding='utf-8')).get('running', [])
    status_code, status_text = tool('project.py', 'status', root)
    record('map: an abruptly exited mapper no longer owns the status line',
           child.returncode == 17 and any(job.get('pid') == child_pid for job in crashed)
           and status_code == 0 and 'map int_01' not in status_text and 'interrupted' in status_text,
           str((child.returncode, child.pid, child_pid, crashed, status_text, child_error[-200:])))
    prompt_root = Path(j('prompt-project'))
    tool('map.py', 'add', prompt_root, media, '--role', 'interview')
    original_run = mapper.subprocess.run
    passed = []

    def capture_prompt(cmd, *args, **kwargs):
        if len(cmd) > 1 and str(cmd[1]).endswith('transcribe.py'):
            passed.extend(cmd)
            Path(cmd[cmd.index('--out') + 1]).write_text('{"words": []}', encoding='utf-8')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return original_run(cmd, *args, **kwargs)

    try:
        with patch.object(mapper.subprocess, 'run', side_effect=capture_prompt):
            mapper.run(prompt_root, ['int_01'], 'auto', prompt='Name One, Name Two')
    except TypeError:
        pass
    record('map: the transcription prompt reaches the protected project workflow',
           '--prompt' in passed and passed[passed.index('--prompt') + 1] == 'Name One, Name Two', str(passed))
    code, help_text = tool('map.py', 'run', '--help')
    record('map: the run command exposes a transcription prompt', code == 0 and '--prompt' in help_text,
           help_text[-300:])
    concurrent = Path(j('concurrent-map-project'))
    tool('map.py', 'add', concurrent, media, '--role', 'interview')
    status_path = concurrent / 'status.json'
    status = json.loads(status_path.read_text(encoding='utf-8'))
    other_job = {'job': 'map int_01', 'pid': os.getpid(), 'progress': .5}
    status['running'] = [other_job]
    status_path.write_text(json.dumps(status), encoding='utf-8')
    active_folder = concurrent / 'map' / 'int_01'
    active_folder.mkdir(parents=True, exist_ok=True)
    old_temp = active_folder / '.words-in-use.json'
    old_temp.write_text('active', encoding='utf-8')
    code, output = tool('map.py', 'run', concurrent, '--alias', 'int_01', '--words', 'skip')
    remaining = json.loads(status_path.read_text(encoding='utf-8')).get('running', [])
    record('map: a second mapper cannot remove a live mapper or its temporary file', code == 2
           and 'already' in output.lower() and other_job in remaining and old_temp.is_file(),
           str((code, remaining, output[-200:])))


def check_transcript_media_identity(tool, record, j):
    """A retained transcript stays bound, warns on every read, and can only be rebound deliberately."""
    import hashlib
    import wave

    def make_source(path, value):
        with wave.open(str(path), 'wb') as handle:
            handle.setparams((1, 2, 8000, 8000, 'NONE', 'not compressed'))
            handle.writeframes(int(value).to_bytes(2, 'little', signed=True) * 8000)

    source = Path(j('identity-map.wav'))
    make_source(source, 10)
    old_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    old_size = source.stat().st_size
    imported = Path(j('identity-map.srt'))
    imported.write_text('1\n00:00:00,100 --> 00:00:00,300\nalpha\n', encoding='utf-8')
    root = Path(j('identity-map-project'))
    first, detail = tool('map.py', 'add', root, source, '--role', 'interview')
    second, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(imported))
    path = root / 'map' / 'int_01' / 'words.json'
    data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    media = data.get('media') or {}
    record('map: imported transcript records the media hash, size and chosen stream',
           first == second == 0 and media.get('sha256') == old_hash and media.get('bytes') == old_size
           and media.get('audio_stream') == 0, detail + output + str(media))
    # Simulate an older transcript which predates the media field.
    data.pop('media', None)
    path.write_text(json.dumps(data), encoding='utf-8')
    make_source(source, 400)
    new_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    code1, warning1 = tool('map.py', 'run', root)
    code2, warning2 = tool('map.py', 'run', root)
    kept = json.loads(path.read_text(encoding='utf-8'))
    word_id = kept['words'][0]['id']
    code3, warning3 = tool('map.py', 'words', root, 'int_01')
    code4, warning4 = tool('map.py', 'fix', root, word_id, 'corrected')
    warnings = (warning1, warning2, warning3, warning4)
    record('map: changed legacy media stays bound to the old hash, warns on run, cache, words and fix, and exits 1',
           all(code == 1 for code in (code1, code2, code3, code4))
           and kept.get('media', {}).get('sha256') == old_hash
           and all('stale' in value.lower() and 'int_01' in value
                   and '--retranscribe' in value and 'confirm-words' in value for value in warnings),
           '\n'.join(warnings))
    readable = (root / 'map' / 'int_01' / 'transcript.md').read_text(encoding='utf-8')
    record('map: the readable transcript marks its stale media and names both remedies',
           'stale' in readable.lower() and '--retranscribe' in readable and 'confirm-words' in readable, readable)
    missing, missing_out = tool('map.py', 'confirm-words', root, 'int_01')
    empty, empty_out = tool('map.py', 'confirm-words', root, 'int_01', '--note', '   ')
    record('map: confirmation refuses a missing or blank note', missing == empty == 2, missing_out + empty_out)
    confirmed, confirm_out = tool('map.py', 'confirm-words', root, 'int_01', '--note', 'listened to the rewrap')
    bound = json.loads(path.read_text(encoding='utf-8'))
    decisions = root / 'decisions.jsonl'
    entries = [json.loads(line) for line in decisions.read_text(encoding='utf-8').splitlines()] \
        if decisions.exists() else []
    refreshed = (root / 'map' / 'int_01' / 'transcript.md').read_text(encoding='utf-8')
    rerun, rerun_out = tool('map.py', 'run', root)
    record('map: documented confirmation binds current bytes and stream and appends a decision',
           confirmed == rerun == 0 and bound.get('media', {}).get('sha256') == new_hash
           and bound.get('media', {}).get('audio_stream') == 0
           and bound.get('media', {}).get('confirmation')
           and 'listened to the rewrap' in json.dumps(bound) and 'listened to the rewrap' in json.dumps(entries)
           and 'stale' not in rerun_out.lower(), confirm_out + rerun_out + str(bound.get('media')))
    record('map: readable transcript removes the stale warning after a checked confirmation',
           'stale' not in refreshed.lower(), refreshed)
    make_source(source, 900)
    replace, replace_out = tool('map.py', 'run', root, '--alias', 'int_01', '--words',
                                'import:' + str(imported), '--retranscribe', 'int_01')
    replaced = json.loads(path.read_text(encoding='utf-8'))
    record('map: explicit retranscription replaces words and binds the replacement file',
           replace == 0 and replaced.get('media', {}).get('sha256') == hashlib.sha256(source.read_bytes()).hexdigest()
           and replaced['words'][0]['text'] == 'alpha', replace_out + str(replaced.get('media')))

    data = json.loads(path.read_text(encoding='utf-8'))
    data.pop('media', None)
    path.write_text(json.dumps(data), encoding='utf-8')
    legacy, legacy_out = tool('map.py', 'run', root)
    again, again_out = tool('map.py', 'run', root)
    data = json.loads(path.read_text(encoding='utf-8'))
    current_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    record('map: unchanged legacy transcript binds once and announces its binding once',
           legacy == again == 0 and data.get('media', {}).get('sha256') == current_hash
           and 'bound' in legacy_out.lower() and 'bound' not in again_out.lower(), legacy_out + again_out)
    data.pop('media', None)
    data.pop('audio_stream', None)
    path.write_text(json.dumps(data), encoding='utf-8')
    index_path = root / 'map' / 'sources.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))
    index['sources'][0]['audio'] = None
    index_path.write_text(json.dumps(index), encoding='utf-8')
    stream_code, stream_out = tool('map.py', 'run', root)
    record('map: an unknown legacy audio stream never becomes a current transcript silently',
           stream_code == 1 and 'stale' in stream_out.lower() and 'stream' in stream_out.lower()
           and '--retranscribe' in stream_out and 'confirm-words' in stream_out, stream_out)
    make_source(source, 1200)
    before_remap_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    confirm_code, confirm_output = tool('map.py', 'confirm-words', root, 'int_01', '--note', 'checked new file')
    index = json.loads(index_path.read_text(encoding='utf-8'))['sources'][0]
    data = json.loads(path.read_text(encoding='utf-8'))
    record('map: confirmation before remapping binds current bytes and invalidates old maps',
           confirm_code == 0 and index.get('sha256') == before_remap_hash
           and data.get('media', {}).get('sha256') == before_remap_hash
           and not index.get('mapped', {}).get('audio') and not index.get('mapped', {}).get('shots'),
           confirm_output + str(index) + str(data.get('media')))


def check_confirm_changed_stream(tool, record, j):
    """A checked rewrap can explicitly confirm a different stream index without retranscribing."""
    root = Path(j('identity-confirm-stream-project'))
    source = Path(j('identity-confirm-stream.mkv'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:d=1', '-map', '0:a', '-map', '1:a',
                    '-c:a', 'pcm_s16le', str(source)], check=True, capture_output=True)
    srt = Path(j('identity-confirm-stream.srt'))
    srt.write_text('1\n00:00:00,100 --> 00:00:00,300\nalpha\n', encoding='utf-8')
    added, add_out = tool('map.py', 'add', root, source, '--role', 'interview', '--stream', '0')
    mapped, map_out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(srt))
    confirmed, confirm_out = tool('map.py', 'confirm-words', root, 'int_01', '--stream', '1',
                                  '--note', 'checked stream 1')
    words_path = root / 'map' / 'int_01' / 'words.json'
    words = json.loads(words_path.read_text(encoding='utf-8')) if words_path.exists() else {}
    index_path = root / 'map' / 'sources.json'
    index = json.loads(index_path.read_text(encoding='utf-8'))['sources'][0] if index_path.exists() else {}
    record('map: checked confirmation can bind a different selected audio stream',
           added == mapped == confirmed == 0 and words.get('media', {}).get('audio_stream') == 1
           and (index.get('audio') or {}).get('index') == 1 and words['words'][0]['text'] == 'alpha'
           and not index.get('mapped', {}).get('audio'), add_out + map_out + confirm_out + str(index))
    replacement = Path(j('identity-confirm-new-layout.mkv'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:d=1',
                    '-c:a', 'pcm_s16le', str(replacement)], check=True, capture_output=True)
    source.write_bytes(replacement.read_bytes())
    missing, missing_out = tool('map.py', 'run', root)
    rebound, rebound_out = tool('map.py', 'confirm-words', root, 'int_01', '--stream', '0',
                                '--note', 'checked rewrapped stream')
    words = json.loads(words_path.read_text(encoding='utf-8'))
    index = json.loads(index_path.read_text(encoding='utf-8'))['sources'][0]
    record('map: a missing old stream names both remedies and confirmation accepts the checked replacement stream',
           missing == 2 and 'int_01' in missing_out and '--retranscribe' in missing_out
           and 'confirm-words' in missing_out and rebound == 0 and words.get('media', {}).get('audio_stream') == 0
           and (index.get('audio') or {}).get('index') == 0, missing_out + rebound_out)


def check_transcript_unavailable(tool, record, j):
    """When transcribe.py cannot run, map.py says so in one line after its reason, and the status says the map is
    waiting on that, not interrupted."""
    import wave
    source = Path(j('no-transcript.wav'))
    with wave.open(str(source), 'wb') as handle:
        handle.setparams((1, 2, 8000, 8000, 'NONE', 'not compressed'))
        handle.writeframes(b'\x00\x00' * 8000)
    root = Path(j('no-transcript-project'))
    tool('map.py', 'add', root, source, '--role', 'interview')
    code, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + j('no-such-words.json'))
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('map: a transcript that cannot be made or imported is one clear line and a waiting status, not a raw '
           'subprocess error',
           code == 2 and 'returned non-zero exit status' not in output and 'no transcript yet' in output
           and status.get('line', '').startswith('map waiting') and 'interrupted' not in status.get('line', ''),
           output[-500:] + str(status.get('line')))
    # Transcription not set up: faster-whisper cannot be imported by transcribe.py (blocked here where it is installed).
    import os
    blocker = Path(j('no-faster-whisper'))
    (blocker / 'faster_whisper').mkdir(parents=True, exist_ok=True)
    (blocker / 'faster_whisper' / '__init__.py').write_text("raise ImportError('blocked for a test')\n",
                                                             encoding='utf-8')
    saved = os.environ.get('PYTHONPATH')
    os.environ['PYTHONPATH'] = str(blocker)
    try:
        code, output = tool('map.py', 'run', root, '--alias', 'int_01')
    finally:
        if saved is None:
            os.environ.pop('PYTHONPATH', None)
        else:
            os.environ['PYTHONPATH'] = saved
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('map: with transcription not set up, map.py names the fix once and the map waits on it',
           code == 2 and 'returned non-zero exit status' not in output and '--install transcription' in output
           and status.get('line') == 'map waiting: transcription is not set up here', output[-500:]
           + str(status.get('line')))


def cut_short_source(path, seconds=8, keep=.6):
    """A complete MP4 with its index at the front, cut short by bytes: its header still claims every second."""
    whole = Path(path).with_name(Path(path).stem + '-whole.mp4')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', f'testsrc2=s=320x180:r=10:d={seconds}',
                    '-f', 'lavfi', '-i', f'sine=frequency=440:sample_rate=48000:duration={seconds}', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-g', '10', '-c:a', 'aac', '-movflags', '+faststart', str(whole)],
                   check=True, capture_output=True)
    data = whole.read_bytes()
    Path(path).write_bytes(data[:int(len(data) * keep)])
    return whole


def last_frame_end(path, selector, frame):
    """Where a stream's decoded frames really end, read frame by frame, for the known answer."""
    result = subprocess.run(['ffprobe', '-v', 'quiet', '-select_streams', selector, '-show_entries',
                             'frame=best_effort_timestamp_time', '-of', 'csv=p=0', str(path)],
                            capture_output=True, text=True)
    return float(result.stdout.split()[-1].strip(',')) + frame


def check_decoded_end(tool, record, j):
    """map.py records where picture and sound really end and says plainly when that differs from the header; a whole
    file is unchanged, and a map made before this keeps working."""
    folder = Path(j('map-decoded-end'))
    folder.mkdir(parents=True, exist_ok=True)
    short = folder / 'short.mp4'
    whole = cut_short_source(short)
    picture, sound = last_frame_end(short, 'v:0', .1), last_frame_end(short, 'a:0', 1024 / 48000)
    damaged = folder / 'damaged'
    tool('map.py', 'add', damaged, short, '--role', 'other')
    code, output = tool('map.py', 'run', damaged, '--alias', 'src_01', '--words', 'skip')
    index = damaged / 'map' / 'sources.json'
    row = json.loads(index.read_text(encoding='utf-8'))['sources'][0]
    ends = row.get('ends') or {}
    measured = (ends.get('picture') or {}).get('decoded') or 0, (ends.get('sound') or {}).get('decoded') or 0
    record('map: the real decoded end of picture and sound is recorded from the map\'s own decode',
           2 < picture < 7 and abs(measured[0] - picture) < .11 and abs(measured[1] - sound) < .05
           and (ends.get('picture') or {}).get('header', 0) > 7.9, f'known {picture}, {sound}; recorded {ends}')
    record('map: a source that decodes short of its header says so plainly, exits 1 and maps what is there',
           code == 1 and 'header' in output and f'{measured[0]:.2f}' in output and 'decodes' in output
           and abs(row.get('duration_s', 0) - max(measured)) < .05, output[-400:])
    shots = json.loads((damaged / 'map' / 'src_01' / 'shots.json').read_text(encoding='utf-8'))['shots']
    record('map: the last shot ends where the picture does', abs(shots[-1]['end'] - measured[0]) < .11, str(shots[-1]))
    code, again = tool('map.py', 'run', damaged, '--alias', 'src_01', '--words', 'skip')
    record('map: running again from the cache still says the source decodes short',
           code == 1 and 'cached' in again and 'decodes' in again, again[-300:])

    healthy = folder / 'healthy'
    tool('map.py', 'add', healthy, whole, '--role', 'other')
    code, output = tool('map.py', 'run', healthy, '--alias', 'src_01', '--words', 'skip')
    row = json.loads((healthy / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    record('map: a whole file keeps its header length, with both ends recorded and nothing to report',
           code == 0 and 'decodes' not in output and abs(row['duration_s'] - 8) < .05
           and abs(row['ends']['picture']['decoded'] - 8) < .11 and abs(row['ends']['sound']['decoded'] - 8) < .05
           and row['ends']['picture']['usable'] == row['ends']['picture']['header'], str(row.get('ends')) + output[-200:])

    data = json.loads(index.read_text(encoding='utf-8'))
    data['sources'][0].pop('ends', None)
    index.write_text(json.dumps(data), encoding='utf-8')
    code, output = tool('map.py', 'run', damaged, '--alias', 'src_01', '--words', 'skip')
    record('map: a map made before the decoded end was recorded still runs, and says how to measure it',
           code == 0 and 'cached' in output and '--rebuild' in output, output[-300:])
    code, output = tool('map.py', 'run', damaged, '--alias', 'src_01', '--words', 'skip', '--rebuild')
    row = json.loads(index.read_text(encoding='utf-8'))['sources'][0]
    record('map: --rebuild measures the decoded end of an older map', code == 1 and 'ends' in row, output[-300:])


def silent_default_source(path, first_default=True):
    """Picture with two sound streams, 1 digitally silent and 2 a tone; the default flag on 1, or on 2."""
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=3',
                    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:sample_rate=48000:duration=3', '-map', '0:v', '-map', '1:a',
                    '-map', '2:a', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac',
                    '-disposition:a:0', 'default' if first_default else '0',
                    '-disposition:a:1', '0' if first_default else 'default', str(path)],
                   check=True, capture_output=True)


def check_silent_default_stream(tool, record, j):
    """With several sound streams each is measured and printed; a silent chosen stream gives way to one with sound,
    which is said with the command to override it; a stream someone chose stays chosen."""
    folder = Path(j('map-silent-default'))
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / 'obs.mkv'
    silent_default_source(source)
    root = folder / 'project'
    tool('map.py', 'add', root, source, '--role', 'other')
    code, output = tool('map.py', 'run', root, '--alias', 'src_01', '--words', 'skip')
    row = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    audio = json.loads((root / 'map' / 'src_01' / 'audio.json').read_text(encoding='utf-8'))
    record('map: each of several sound streams is measured and printed with its level',
           code == 0 and 'stream 1' in output and 'stream 2' in output and 'digitally silent' in output
           and any('stream 2' in line and ' dB' in line for line in output.splitlines()), output[-500:])
    record('map: a digitally silent default gives way to the stream with sound, says so and names the override',
           row['audio']['index'] == 2 and audio.get('stream_index') == 2 and audio.get('integrated_lufs') is not None
           and audio['integrated_lufs'] > -60 and '--stream 1' in output, output[-500:] + str(row.get('audio')))
    code, again = tool('map.py', 'run', root, '--alias', 'src_01', '--words', 'skip')
    row = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    record('map: running again keeps the stream with sound, from the cached map',
           code == 0 and 'cached' in again and row['audio']['index'] == 2, again[-300:])
    (root / 'film.md').write_text('---\ntitle: Silent default\nsize: 160x90\nfps: 10\ncaptions: none\n---\n'
                                  '- src_01 0:00.50-0:02.50 sound The tone\n', encoding='utf-8')
    code, rendered = tool('cut.py', 'render', root)
    preview = root / 'cuts' / 'v001' / 'preview.mp4'
    measured = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-i', str(preview), '-af', 'volumedetect', '-vn',
                               '-f', 'null', '-'], capture_output=True, text=True, encoding='utf-8', errors='replace')
    peak = next((float(line.split('max_volume:')[1].split()[0]) for line in measured.stderr.splitlines()
                 if 'max_volume:' in line), -200.0)
    record('map: the film cut from that source has its sound, not the silent default',
           code in (0, 1) and peak > -30, f'peak {peak}; {rendered[-300:]}')
    chosen = folder / 'chosen'
    tool('map.py', 'add', chosen, source, '--role', 'other', '--stream', 1)
    code, output = tool('map.py', 'run', chosen, '--alias', 'src_01', '--words', 'skip')
    row = json.loads((chosen / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    record('map: a stream someone chose stays chosen, with a warning that it is silent and another has sound',
           code == 0 and row['audio']['index'] == 1 and 'stream 1' in output and 'digitally silent' in output
           and '--stream 2' in output, output[-500:])
    picked = folder / 'picked'
    tool('map.py', 'add', picked, source, '--role', 'other')
    code, output = tool('map.py', 'run', picked, '--alias', 'src_01', '--words', 'skip', '--stream', 1)
    code, output = tool('map.py', 'run', picked, '--alias', 'src_01', '--words', 'skip')
    row = json.loads((picked / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    record('map: a stream chosen on an earlier run stays chosen on the next', row['audio']['index'] == 1, output[-300:])
    empty = folder / 'no-words.json'
    empty.write_text(json.dumps({'words': []}), encoding='utf-8')
    code, output = tool('transcribe.py', source, '--engine', 'import', '--import-file', empty, '--out',
                        folder / 'words.json')
    record('transcribe: no words from one of several sound streams names the others and --stream',
           code == 0 and 'stream 2' in output and '--stream' in output, output[-300:])
    plain = folder / 'one-stream.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=10:d=2', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:sample_rate=48000:duration=2', '-shortest', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(plain)], check=True, capture_output=True)
    single = folder / 'single'
    tool('map.py', 'add', single, plain, '--role', 'other')
    code, output = tool('map.py', 'run', single, '--alias', 'src_01', '--words', 'skip')
    record('map: a source with one sound stream prints no stream levels', code == 0 and 'stream 1 ' not in output,
           output[-300:])


def run_map_cases(tool, record, j, scripts_dir):
    """Check transcripts, source privacy, caching, scene and silence timing, and strips."""
    check_transcript_unavailable(tool, record, j)
    check_silent_default_stream(tool, record, j)
    check_decoded_end(tool, record, j)
    check_transcript_media_identity(tool, record, j)
    check_confirm_changed_stream(tool, record, j)
    polish_map_cases(tool, record, j)
    check_words_pause_report(tool, record, j)
    polish_cache_relocation_case(tool, record, j, scripts_dir)
    check_transcript_protection_and_cleanup(tool, record, j, scripts_dir)
    check_map_add_and_import(tool, record, j)
    check_stream_identity(tool, record, j)
    check_vad_fallback(tool, record, j)
    check_transcript_fix(tool, record, j)
    check_fix_reports(tool, record, j)
    check_flash_inside_shot(tool, record, j)
    check_download_disclosure(tool, record, j)
    check_cutaway_labels(tool, record, j)
    check_transcript_review_prompts(tool, record, j, scripts_dir)
    check_adjacent_repeats(record, scripts_dir)
    root = Path(j('map-project'))
    source = Path(j('jane-doe-interview.mp4'))
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
           'color=black:s=160x90:r=10:d=1', '-f', 'lavfi', '-i', 'color=white:s=160x90:r=10:d=1',
           '-f', 'lavfi', '-i', 'color=black:s=160x90:r=10:d=1', '-f', 'lavfi', '-i',
           r'aevalsrc=if(between(t\,1\,2)\,0\,0.2*sin(2*PI*440*t)):s=8000:d=3',
           '-filter_complex', '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]', '-map', '[v]', '-map', '3:a',
           '-c:v', 'mpeg4', '-c:a', 'aac', str(source)]
    subprocess.run(cmd, check=True, capture_output=True)
    code, out = tool('map.py', 'add', root, source, '--role', 'interview')
    index_text = (root / 'map' / 'sources.json').read_text(encoding='utf-8')
    data = json.loads(index_text)
    record('map: external source stays in place', code == 0 and data['sources'][0]['alias'] == 'int_01'
           and Path(data['sources'][0]['path']) == source.resolve() and not (root / 'media').exists(), out)
    code, out = tool('map.py', 'add', root, source, '--role', 'interview')
    data = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))
    record('map: duplicate source reuses alias', code == 0 and len(data['sources']) == 1
           and 'int_01' in out and 'already registered' in out, out)
    moved = Path(j('moved.mp4'))
    moved.write_bytes(source.read_bytes())
    code, out = tool('map.py', 'relink', root, 'int_01', moved)
    relinked = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))['sources'][0]
    record('map: relink retains alias and verifies hash', code == 0 and relinked['alias'] == 'int_01'
           and Path(relinked['path']) == moved.resolve(), out)
    tool('map.py', 'relink', root, 'int_01', source)
    copyroot = Path(j('map-copy'))
    code, out = tool('map.py', 'add', copyroot, source, '--role', 'interview', '--copy')
    copied = json.loads((copyroot / 'map' / 'sources.json').read_text(encoding='utf-8'))
    record('map: optional copy is alias named', code == 0 and copied['sources'][0]['path'] == 'media/int_01.mp4'
           and (copyroot / 'media' / 'int_01.mp4').exists(), out)
    internal = root / 'internal.mp4'
    internal.write_bytes(source.read_bytes() + b'fixture')
    code, out = tool('map.py', 'add', root, internal, '--role', 'broll')
    data = json.loads((root / 'map' / 'sources.json').read_text(encoding='utf-8'))
    record('map: internal source uses relative path', code == 0 and data['sources'][1]['path'] == 'internal.mp4', out)
    srt = Path(j('source.srt'))
    srt.write_text('1\n00:00:00,200 --> 00:00:00,800\nHello world\n\n', encoding='utf-8')
    status_path = root / 'status.json'
    status = json.loads(status_path.read_text(encoding='utf-8'))
    status['running'] = [{'job': 'render v001', 'progress': .2}]
    status_path.write_text(json.dumps(status), encoding='utf-8')
    code, out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(srt))
    record('map: run imported SRT', code == 0, out)
    readable = root / 'map' / 'int_01' / 'transcript.md'
    record('map: imported words produce a timed readable transcript',
           readable.is_file() and 'Hello world' in readable.read_text(encoding='utf-8'), out[-200:])
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('map: mapping one of two sources leaves the stage unfinished',
           status['stages']['map'] == 'now', str(status['stages']))
    record('map: mapping does not remove another running job',
           any(job['job'] == 'render v001' for job in status['running']), str(status['running']))
    words_path = root / 'map' / 'int_01' / 'words.json'
    words = json.loads(words_path.read_text(encoding='utf-8')) if words_path.exists() else {'words': []}
    record('map: SRT estimates and word IDs', [w['id'] for w in words['words']] ==
           ['int_01-w000001', 'int_01-w000002'] and all(w['estimated'] for w in words['words']), str(words))
    words['draft'] = False
    words['words'][0]['text'] = 'corrected'
    words_path.write_text(json.dumps(words), encoding='utf-8')
    other = Path(j('other.srt'))
    other.write_text('1\n00:00:00,200 --> 00:00:00,800\nWrong\n', encoding='utf-8')
    code, out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(other))
    retained = json.loads(words_path.read_text(encoding='utf-8'))
    record('map: corrected transcript survives a changed input', code == 0 and retained == words, out)
    code, out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(other),
                     '--retranscribe', 'int_01')
    replaced = json.loads(words_path.read_text(encoding='utf-8'))
    record('map: explicit retranscription replaces named transcript', code == 0
           and replaced['words'][0]['text'] == 'Wrong', out)
    code, out = tool('map.py', 'run', root, '--words', 'import:' + str(other))
    record('map: import requires alias', code == 2, out)
    code, out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(srt))
    record('map: second run cached', code == 0 and 'cached' in out, out)
    shots_path = root / 'map' / 'int_01' / 'shots.json'
    shots = json.loads(shots_path.read_text(encoding='utf-8'))['shots'] if shots_path.exists() else []
    record('map: planted cuts within one frame', len(shots) == 3 and abs(shots[1]['start'] - 1) <= 0.1
           and abs(shots[2]['start'] - 2) <= 0.1, str(shots))
    audio_path = root / 'map' / 'int_01' / 'audio.json'
    audio = json.loads(audio_path.read_text(encoding='utf-8')) if audio_path.exists() else {'silences': []}
    record('map: planted silence within 0.1 seconds', any(abs(s['start'] - 1) <= 0.1 and abs(s['end'] - 2) <= 0.1
           for s in audio['silences']), str(audio['silences']))
    transcript = Path(j('words.json'))
    transcript.write_text(json.dumps({'segments': [{'words': [{'word': ' Hi', 'start': 0.2, 'end': 0.4,
                           'score': 0.9}, {'word': ' ', 'start': 0.4, 'end': 0.5}]}]}), encoding='utf-8')
    output = Path(j('imported.json'))
    code, out = tool('transcribe.py', source, '--engine', 'import', '--import-file', transcript, '--out', output)
    imported = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {'words': []}
    record('map: WhisperX words and empty rows', code == 0 and len(imported['words']) == 1
           and imported['words'][0].get('p') == 0.9, out)
    bad_media = Path(j('bad-media.bin'))
    bad_media.write_bytes(b'not media')
    bad_output = Path(j('bad-import.json'))
    code, out = tool('transcribe.py', bad_media, '--engine', 'import', '--import-file', transcript,
                     '--out', bad_output)
    record('map: invalid media is probed before import writes', code == 2 and 'ffprobe:' in out
           and not bad_output.exists(), out)
    import importlib.util
    spec = importlib.util.spec_from_file_location('transcribe_cases', Path(scripts_dir) / 'transcribe.py')
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    crlf = Path(j('empty-crlf.srt'))
    crlf.write_bytes(b'1\r\n00:00:01,000 --> 00:00:02,000\r\nFirst\r\n\r\n2\r\n'
                     b'00:00:03,000 --> 00:00:04,000\r\n\r\n3\r\n'
                     b'00:00:05,000 --> 00:00:06,000\r\nThird line\r\n')
    imported_crlf = transcribe.read_import(crlf)
    record('map: CRLF empty cue does not swallow the next cue',
           [w['text'] for w in imported_crlf] == ['First', 'Third', 'line']
           and imported_crlf[1]['start'] == 5.0, str(imported_crlf))
    corrected = transcribe.constrain_audio_start([{'text': 'Hello', 'start': 1.74, 'end': 2.36}], 2.0)
    record('map: ASR cannot place a word before the audio stream starts', corrected[0]['start'] == 2.0
           and corrected[0]['estimated'] and corrected[0]['end'] == 2.36, str(corrected))
    unordered = [{'text': 'second', 'start': 2.0, 'end': 3.0},
                 {'text': 'first', 'start': 1.0, 'end': 2.5}]
    ordered = transcribe.ordered_words(unordered)
    record('map: estimated words sorted and overlaps trimmed', ordered[0]['text'] == 'first'
           and ordered[0]['end'] <= ordered[1]['start'], str(ordered))
    from unittest.mock import patch
    silence_log = subprocess.CompletedProcess([], 0, '', 'silence_start: 3599\nsilence_end: 3601')
    with patch.object(transcribe.subprocess, 'run', return_value=silence_log), \
            patch.object(transcribe, 'vad_silence', return_value=3600.25):
        ranges = transcribe.audio_ranges('unused.wav', 7201)
    record('map: long audio splits at VAD-confirmed silence', ranges == [(0.0, 3600.25), (3600.25, 7201)],
           str(ranges))
    record('map: shorter audio is one whole range', transcribe.audio_ranges('unused.wav', 7200) == [(0, 7200)])
    with patch.object(transcribe.subprocess, 'run', return_value=silence_log), \
            patch.object(transcribe, 'vad_silence', return_value=None):
        try:
            transcribe.audio_ranges('unused.wav', 7201)
            refused = False
        except ValueError:
            refused = True
    record('map: no fixed split when VAD finds no silence', refused)
    spec = importlib.util.spec_from_file_location('map_cases', Path(scripts_dir) / 'map.py')
    mapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mapper)
    record('map: all 61 shots selected and 601 sampled to 600', mapper.sheet_indices(61) == list(range(61))
           and len(set(mapper.sheet_indices(601))) == 600)
    offset = Path(j('offset.mov'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=s=64x64:r=10:d=4',
                    '-itsoffset', '2', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-map', '0:v', '-map', '1:a', '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', str(offset)],
                   check=True, capture_output=True)
    offset_audio = mapper.audio_map(offset, True, 4)['levels_db']['values']
    record('map: delayed audio levels use picture clock', max(offset_audio[:7]) < -80
           and max(offset_audio[8:12]) > -40, str(offset_audio))
    import numpy as np
    import types
    import sys
    class FakeModel:
        error = ModuleNotFoundError('onnxruntime is missing')

        def __init__(self, *args, **kwargs):
            pass
        def transcribe(self, samples, **kwargs):
            first = int(np.flatnonzero(np.abs(samples) > .01)[0]) / 16000
            word = types.SimpleNamespace(word='hello', start=first, end=first + .1, probability=1)
            return [types.SimpleNamespace(words=[word])], types.SimpleNamespace(language='en')
    args = types.SimpleNamespace(model='fake', model_dir=None, no_download=True, language=None,
                                 file=offset, prompt=None)
    with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=FakeModel)}):
        offset_words, _ = transcribe.faster(args)
    record('map: delayed first word uses picture clock', abs(offset_words[0]['start'] - 2) < .1,
           str(offset_words))
    from unittest.mock import patch
    many = Path(j('many-shots-project'))
    tool('map.py', 'add', many, source, '--role', 'interview')
    original_run = mapper.subprocess.run
    def fake_run(cmd, *args, **kwargs):
        if len(cmd) > 1 and str(cmd[1]).endswith('frame_sheet.py'):
            Path(cmd[cmd.index('--out') + 1]).write_bytes(b'sheet')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return original_run(cmd, *args, **kwargs)
    planted = [{'start': i * 0.04, 'end': (i + 1) * 0.04} for i in range(61)]
    with patch.object(mapper, 'shots', return_value=(planted, [])), \
            patch.object(mapper.subprocess, 'run', side_effect=fake_run):
        mapper.run(many, None, 'skip')
    pages = json.loads((many / 'map' / 'int_01' / 'shots.json').read_text(encoding='utf-8'))
    record('map: 61 shots get references across two sheets', len(pages['shots']) == 61
           and all('sheet' in row and 'tile' in row for row in pages['shots'])
           and pages['shots'][-1]['sheet'] == 'sheet-02.jpg' and pages['shots'][-1]['tile'] == 1,
           str(pages['shots'][-1]))
    model = Path(j('fake-ggml.bin'))
    model.write_bytes(b'fixture')
    passed = []
    def capture_transcriber(cmd, *args, **kwargs):
        if len(cmd) > 1 and str(cmd[1]).endswith('transcribe.py'):
            passed.extend(cmd)
            words_file = Path(cmd[cmd.index('--out') + 1])
            words_file.write_text(json.dumps({'words': []}), encoding='utf-8')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return fake_run(cmd, *args, **kwargs)
    with patch.object(mapper, 'shots', return_value=(planted[:1], [])), \
            patch.object(mapper.subprocess, 'run', side_effect=capture_transcriber):
        mapper.run(many, None, 'auto', str(model), 'ffmpeg')
    record('map: FFmpeg engine and GGML model passed through', '--ggml-model' in passed
           and passed[passed.index('--ggml-model') + 1] == str(model)
           and passed[passed.index('--engine') + 1] == 'ffmpeg', str(passed))
    race = Path(j('transcript-race'))
    tool('map.py', 'add', race, source, '--role', 'interview')
    human_words = race / 'map' / 'int_01' / 'words.json'
    def edit_during_transcription(cmd, *args, **kwargs):
        if len(cmd) > 1 and str(cmd[1]).endswith('transcribe.py'):
            Path(cmd[cmd.index('--out') + 1]).write_text('{"words": []}', encoding='utf-8')
            human_words.write_text('{"draft": false, "words": [{"text": "human"}]}', encoding='utf-8')
            return subprocess.CompletedProcess(cmd, 0, '', '')
        return fake_run(cmd, *args, **kwargs)
    refused = False
    try:
        with patch.object(mapper, 'shots', return_value=(planted[:1], [])), \
                patch.object(mapper.subprocess, 'run', side_effect=edit_during_transcription):
            mapper.run(race, None, 'auto')
    except ValueError as error:
        refused = 'changed during transcription' in str(error)
    record('map: a transcript edited during transcription is retained', refused
           and json.loads(human_words.read_text(encoding='utf-8'))['words'][0]['text'] == 'human')
    preview = root / 'cuts' / 'v001' / 'preview.mp4' 
    preview.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=1:d=70',
                    '-c:v', 'mpeg4', str(preview)], check=True, capture_output=True)
    code, out = tool('strip.py', root, '--version', 'v001')
    strip = preview.parent / 'strip'
    paths = sorted(strip.glob('strip-*.jpg'))
    record('map: 70 seconds produces two 1600px strips', code == 0 and len(paths) == 2
           and all(Image.open(p).width == 1600 for p in paths), out)
    standalone = Path(j('standalone'))
    code, out = tool('strip.py', '--video', source, '--out', standalone)
    record('map: strip standalone video', code == 0 and (standalone / 'strip-01.jpg').exists(), out)
    captions_input = Path(j('caption-words.json'))
    captions_input.write_text(json.dumps({'words': [{'text': 'Visible', 'start': .5, 'end': .8},
                                                    {'text': 'speech', 'start': .9, 'end': 1.2}]}),
                              encoding='utf-8')
    prefix = preview.parent / 'captions'
    code, out = tool('captions.py', 'build', captions_input, '--out', prefix)
    spec = importlib.util.spec_from_file_location('strip_cases', Path(scripts_dir) / 'strip.py')
    strip_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strip_module)
    cues = strip_module.entries(prefix.with_suffix('.json'), ('cues',))
    words = [word for cue in cues for word in (cue.get('words') or [cue])]
    drawn = []
    original_text = strip_module.ImageDraw.ImageDraw.text
    def capture_text(draw, xy, text, *args, **kwargs):
        drawn.append(str(text))
        return original_text(draw, xy, text, *args, **kwargs)
    with patch.object(strip_module.ImageDraw.ImageDraw, 'text', capture_text):
        strip_module.make(source, Path(j('caption-strip')), words, [])
    record('map: captions build to strip shows word-timed text', code == 0
           and any('Visible speech' in text for text in drawn), out + str(drawn))
    audio_only = Path(j('audio-only.wav'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=duration=3', str(audio_only)],
                   check=True, capture_output=True)
    no_picture = Path(j('no-picture-strip'))
    code, out = tool('strip.py', '--video', audio_only, '--out', no_picture)
    record('map: audio-only produces a strip', code == 0 and (no_picture / 'strip-01.jpg').is_file(), out)
    portrait = Path(j('portrait-long-audio.mp4'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=s=90x160:r=10:d=1',
                    '-f', 'lavfi', '-i', 'sine=duration=3', '-c:v', 'mpeg4', '-c:a', 'aac', str(portrait)],
                   check=True, capture_output=True)
    portrait_out = Path(j('portrait-strip'))
    code, out = tool('strip.py', '--video', portrait, '--out', portrait_out)
    record('map: portrait and longer audio produce a strip', code == 0
           and (portrait_out / 'strip-01.jpg').is_file(), out)


def check_map_add_and_import(tool, record, j):
    """Slow media work stays outside the source-index lock; failed copies do not block the next add."""
    import contextlib
    import importlib.util
    import shutil
    import wave
    from unittest.mock import patch
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_map_lock', scripts / 'map.py')
    mapper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mapper)
    source = Path(j('map-lock-source.wav'))
    with wave.open(str(source), 'wb') as handle:
        handle.setparams((1, 2, 8000, 8000, 'NONE', 'not compressed'))
        handle.writeframes(b'\x00\x00' * 8000)
    original_lock = mapper.project.file_lock
    original_digest = mapper.digest
    original_probe = mapper.probe
    original_copy = shutil.copyfile
    held = [False]
    inside = []

    @contextlib.contextmanager
    def tracked_lock(path, *args, **kwargs):
        with original_lock(path, *args, **kwargs):
            track = Path(path).name == 'sources.json'
            held[0] = track
            try:
                yield
            finally:
                if track:
                    held[0] = False

    def track(name, function):
        def call(*args, **kwargs):
            if held[0]:
                inside.append(name)
            return function(*args, **kwargs)
        return call

    root = Path(j('map-lock-case'))
    with patch.object(mapper.project, 'file_lock', tracked_lock), \
            patch.object(mapper, 'digest', track('hash', original_digest)), \
            patch.object(mapper, 'probe', track('probe', original_probe)), \
            patch.object(mapper.shutil, 'copyfile', track('copy', original_copy)):
        mapper.add(root, [source], 'interview', copy=True)
    record('map: source index is not locked while hashing, probing or copying', not inside, str(inside))
    bad = Path(j('invalid-media.mp4'))
    bad.write_bytes(b'not a media file')
    failed = Path(j('map-failed-copy'))
    code, output = tool('map.py', 'add', failed, bad, '--role', 'interview', '--copy')
    code2, output2 = tool('map.py', 'add', failed, source, '--role', 'interview', '--copy')
    leftovers = list((failed / 'media').glob('*')) if (failed / 'media').exists() else []
    record('map: a failed copy does not leave an alias or temporary file behind',
           code == 2 and code2 == 0 and len(leftovers) == 1 and leftovers[0].name == 'int_01.wav',
           output + output2 + str(leftovers))
    words = root / 'map' / 'int_01' / 'words.json'
    words.parent.mkdir(parents=True, exist_ok=True)
    words.write_text(json.dumps({'words': [{'text': 'kept', 'start': .2, 'end': .5}]}), encoding='utf-8')
    transcript = Path(j('replacement.srt'))
    transcript.write_text('1\n00:00:00,200 --> 00:00:00,500\nnew\n', encoding='utf-8')
    code, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(transcript))
    record('map: retained transcript names the explicit replacement command',
           code == 0 and '--retranscribe int_01' in output and 'retained' in output, output[-400:])


def check_stream_identity(tool, record, j):
    """A non-first default and an explicit override travel through mapping and audio measurement."""
    import importlib.util
    import numpy as np
    source = Path(j('two-tracks.mkv'))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=880:d=1', '-map', '0:a', '-map', '1:a',
                    '-disposition:a:0', '0', '-disposition:a:1', 'default', '-metadata:s:a:1', 'language=fra',
                    '-c:a', 'pcm_s16le', str(source)], check=True)
    root = Path(j('stream-project'))
    code, output = tool('map.py', 'add', root, source, '--role', 'interview')
    index_path = root / 'map' / 'sources.json'
    data = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {}
    audio = ((data.get('sources') or [{}])[0].get('audio') or {})
    record('map: non-first default audio stream is recorded with its index and language',
           code == 0 and audio.get('index') == 1 and audio.get('language') == 'fra', str(audio) + output)
    selected = Path(j('stream-explicit'))
    code, output = tool('map.py', 'add', selected, source, '--role', 'interview', '--stream', '0')
    index = selected / 'map' / 'sources.json'
    facts = json.loads(index.read_text(encoding='utf-8')) if index.exists() else {}
    chosen = ((facts.get('sources') or [{}])[0].get('audio') or {}).get('index')
    if code == 0:
        scripts = Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location('case_cut_stream', scripts / 'cut.py')
        cut = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cut)
        envelope = cut.Envelopes(cut.SourceMap(selected), 'ffmpeg')
        measured = envelope.get('int_01', 0, .9)
        time = float(measured.db.mean()) if measured is not None else None
        # The decoder helper returns the chosen stream, independently verified by its frequency.
        spec2 = importlib.util.spec_from_file_location('case_transcribe_stream', scripts / 'transcribe.py')
        transcribe = importlib.util.module_from_spec(spec2)
        spec2.loader.exec_module(transcribe)
        if hasattr(transcribe, 'decode_audio_window'):
            samples = transcribe.decode_audio_window(source, 0, 0, .9, rate=8000)
            spectrum = np.abs(np.fft.rfft(samples))
            freq = np.fft.rfftfreq(len(samples), 1 / 8000)[int(np.argmax(spectrum))]
        else:
            freq = None
    else:
        time, freq = None, None
    record('map: explicit first stream is used by the shared audio decoder',
           code == 0 and chosen == 0 and freq is not None and abs(freq - 440) < 2 and time is not None,
           f'index={chosen}; frequency={freq}; envelope={time}; {output[-300:]}')
    first, first_out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'skip')
    cache = root / 'map' / 'int_01' / 'cache.json'
    before = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    second, second_out = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'skip', '--stream', '0')
    after = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    audio_map = root / 'map' / 'int_01' / 'audio.json'
    mapped = json.loads(audio_map.read_text(encoding='utf-8')) if audio_map.exists() else {}
    record('map: changing streams invalidates the audio-map cache',
           first == 0 and second == 0 and before.get('audio_stream') == 1 and after.get('audio_stream') == 0
           and mapped.get('stream_index') == 0, first_out[-200:] + second_out[-200:])
    if code == 0:
        spec3 = importlib.util.spec_from_file_location('case_stream_assemble', scripts / 'assemble.py')
        assemble = importlib.util.module_from_spec(spec3)
        spec3.loader.exec_module(assemble)
        out = Path(j('selected-stem'))
        out.mkdir(parents=True, exist_ok=True)
        edit = {'sources': {'a': {'file': str(source), 'audio_stream': 0}}, 'audio': [
            {'src': 'a', 'track': 'speech', 'in': 0, 'out': .9, 'at': 0, 'fade_ms': 0}]}
        assemble.render_audio('ffmpeg', 'ffprobe', edit, out, [], .9, out, out, [])
        raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(out / 'speech.wav'), '-ac', '1', '-ar', '8000',
                              '-f', 'f32le', '-'], capture_output=True, check=True).stdout
        samples = np.frombuffer(raw, '<f4')
        freq = np.fft.rfftfreq(len(samples), 1 / 8000)[int(np.argmax(np.abs(np.fft.rfft(samples))))]
    record('map: assembly cuts the same explicitly chosen track',
           code == 0 and freq is not None and abs(freq - 440) < 2, f'output frequency {freq}')


def check_vad_fallback(tool, record, j):
    """A missing optional VAD dependency leaves a disclosed local draft path."""
    import contextlib
    import importlib.util
    import io
    import sys
    import types
    from types import SimpleNamespace
    from unittest.mock import patch
    import numpy as np
    scripts = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('case_transcribe_vad', scripts / 'transcribe.py')
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    calls = []

    class FakeModel:
        def __init__(self, *args, **kwargs):
            pass

        def transcribe(self, samples, **kwargs):
            calls.append(kwargs['vad_filter'])
            if kwargs['vad_filter']:
                raise self.error
            word = SimpleNamespace(word='Hello', start=.1, end=.4, probability=.9)
            return iter([SimpleNamespace(words=[word])]), SimpleNamespace(language='en')

    mocked_ffmpeg = subprocess.CompletedProcess([], 0, np.zeros(16000, dtype='<f4').tobytes(), b'')
    with patch.dict(sys.modules, {'faster_whisper': types.SimpleNamespace(WhisperModel=FakeModel)}), \
            patch.object(transcribe, 'duration', return_value=1), \
            patch.object(transcribe, 'audio_ranges', return_value=[(0, 1)]), \
            patch.object(transcribe, 'decode_audio_window', return_value=np.zeros(16000, dtype=np.float32)), \
            patch.object(transcribe.subprocess, 'run', return_value=mocked_ffmpeg), \
            patch.object(transcribe.importlib.util, 'find_spec', return_value=None):
        for error in (ModuleNotFoundError('onnxruntime is missing'), RuntimeError('onnxruntime is needed for VAD')):
            calls.clear()
            FakeModel.error = error
            args = SimpleNamespace(file='unused.wav', model='base', model_dir=None, no_download=True, language=None,
                                   prompt=None, stream=0, vad_disabled=False)
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                rows, language = transcribe.faster(args)
            record('map: missing onnxruntime falls back after ' + error.__class__.__name__,
                   calls == [True, False] and args.vad_disabled and language == 'en' and len(rows) == 1,
                   f'calls={calls}; disabled={args.vad_disabled}')
            fixes = [line for line in output.getvalue().splitlines() if '--install transcription' in line]
            record('map: VAD repair command has no trailing prose after ' + error.__class__.__name__,
                   bool(fixes) and all(line.endswith('--install transcription') for line in fixes), output.getvalue())


def check_transcript_fix(tool, record, j):
    """A correction preserves timing and provenance and refreshes the readable transcript."""
    root = Path(j('map-correction'))
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    (root / 'map' / 'sources.json').write_text(json.dumps({'sources': [{'alias': 'int_01'}]}), encoding='utf-8')
    path = folder / 'words.json'
    rows = [{'id': 'int_01-w000001', 'text': 'Hello', 'start': .1, 'end': .5},
            {'id': 'int_01-w000002', 'text': 'there', 'start': .6, 'end': 1.0}]
    path.write_text(json.dumps({'words': rows}), encoding='utf-8')
    code, output = tool('map.py', 'fix', root, 'int_01-w000001', 'Hallo', '--by', 'person')
    changed = json.loads(path.read_text(encoding='utf-8'))['words'][0]
    decision = json.loads((root / 'decisions.jsonl').read_text(encoding='utf-8').splitlines()[0])
    readable = (folder / 'transcript.md').read_text(encoding='utf-8')
    record('map: word correction retains ID and timing and records its decision',
           code == 0 and changed['text'] == 'Hallo' and changed['start'] == .1 and changed['end'] == .5
           and decision['subject'] == changed['id'] and decision['by'] == 'person'
           and 'Hello' in decision['decision'] and 'Hallo' in decision['decision'], output)
    record('map: correction refreshes phrase text and word IDs',
           'Hallo there' in readable and 'int_01-w000001' in readable and '0:00.10' in readable, readable)
    before = path.read_bytes()
    code, output = tool('map.py', 'fix', root, 'int_01-w999999', 'Missing')
    record('map: an unknown word ID cannot alter the transcript', code == 2 and path.read_bytes() == before, output)
    code, output = tool('map.py', 'run', '--help')
    record('map: run help explains its options', code == 0 and 'import:FILE' in output
           and 'replace the selected alias' in output, output)


FIX_FILM = """---
title: Fix case
size: 320x180
fps: 25
captions: none
---
## One
> int_01 0:00.00-0:02.00 the quick brown fox
> int_01 0:02.00-0:04.00 jumps over the dog
"""


def check_fix_reports(tool, record, j):
    """map.py fix names the word it changed (ID, time, before and after, words either side), says when a film.md
    line over it stops or starts matching, and refuses a missing ID or alias naming the nearest."""
    root = Path(j('map-fix-report'))
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    (root / 'map' / 'sources.json').write_text(json.dumps({'sources': [{'alias': 'int_01', 'duration_s': 5.0}]}),
                                               encoding='utf-8')
    texts = ['the', 'quick', 'brown', 'fox', 'jumps', 'over', 'the', 'dog']
    rows = [{'id': f'int_01-w{number + 1:06d}', 'text': text, 'start': .1 + .5 * number, 'end': .4 + .5 * number}
            for number, text in enumerate(texts)]
    path = folder / 'words.json'
    path.write_text(json.dumps({'words': rows}), encoding='utf-8')
    (root / 'film.md').write_text(FIX_FILM, encoding='utf-8')
    code, output = tool('map.py', 'fix', root, 'int_01-w000002', 'quack')
    record('map: fix names the word it changed, its time and the words either side',
           code == 0 and 'int_01-w000002 at 0:00.60-0:00.90' in output and '"quick" -> "quack"' in output
           and 'before: the [quick] brown fox jumps' in output and 'after:  the [quack] brown fox jumps' in output,
           output)
    record('map: fix says which film.md line stops matching after the change',
           'film.md line 8 (int_01 0:00.00-0:02.00) stops matching' in output and '"quick"' in output
           and 'line 9' not in output, output)
    code, output = tool('map.py', 'fix', root, 'int_01-w000002', 'quick')
    record('map: fix says when a film.md line matches again', code == 0 and 'line 8' in output
           and 'now matches' in output, output)
    before = path.read_bytes()
    code, output = tool('map.py', 'fix', root, 'int_01-w000099', 'x')
    record('map: fix refuses a missing word ID and names the nearest one',
           code == 2 and path.read_bytes() == before and 'nearest is int_01-w000008 "dog" at 0:03.60' in output
           and 'int_01-w000001 to int_01-w000008' in output, output)
    code, output = tool('map.py', 'fix', root, 'int_1-w000002', 'x')
    record('map: fix refuses an unregistered source and names the nearest alias',
           code == 2 and path.read_bytes() == before and 'did you mean int_01' in output, output)
    code, output = tool('map.py', 'fix', root, 'int_01-w000002', '--start', '0.3')
    record('map: a refused timing fix names the neighbouring words and the window that would pass',
           code == 2 and path.read_bytes() == before and 'asked for 0.300-0.900 s' in output
           and 'int_01-w000001 "the" at 0.100-0.400 s' in output and 'int_01-w000003 "brown" at 1.100-1.400 s' in output
           and 'within 0.400-1.100 s' in output, output)
    code, output = tool('map.py', 'fix', root, 'int_01-w000008', '--end', '6')
    record('map: a refused timing fix on the last word names the end of the source',
           code == 2 and 'source ends at 5.000 s' in output and 'within 3.400-5.000 s' in output, output)


def check_flash_inside_shot(tool, record, j):
    """A two-frame white flash inside a shot is recorded as an effect, not two shot changes; a real cut to another
    picture stays a shot change."""
    root = Path(j('map-flash'))
    root.mkdir(parents=True, exist_ok=True)
    source = root / 'flash.mp4'
    graph = ("testsrc2=s=160x90:r=25:d=2.5,drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='between(t,1,1.07)'"
             '[a];smptebars=s=160x90:r=25:d=1.5[b];[a][b]concat=n=2:v=1[v]')
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-filter_complex', graph, '-map', '[v]', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(source)], check=True, capture_output=True)
    tool('map.py', 'add', root, source, '--role', 'broll')
    code, output = tool('map.py', 'run', root, '--words', 'skip')
    data = json.loads((root / 'map' / 'broll_01' / 'shots.json').read_text(encoding='utf-8')) \
        if (root / 'map' / 'broll_01' / 'shots.json').is_file() else {}
    starts = [round(row['start'], 2) for row in data.get('shots', [])]
    effects = data.get('effects', [])
    record('map: a flash inside a shot is an effect, not two shot changes; a real cut stays a shot change',
           code == 0 and len(starts) == 2 and starts[0] == 0 and abs(starts[1] - 2.5) <= .05 and len(effects) == 1
           and abs(effects[0]['start'] - 1.0) <= .05 and effects[0]['changes'] >= 2, f'{starts} {effects} {output}')


def check_download_disclosure(tool, record, j):
    """Use fake model constructors: this test never contacts a model host."""
    import contextlib
    import importlib.util
    import io
    import sys
    from types import SimpleNamespace
    from unittest.mock import patch
    path = Path(__file__).resolve().parent.parent / 'transcribe.py'
    spec = importlib.util.spec_from_file_location('cache_notice_case', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing_type = type('LocalEntryNotFoundError', (Exception,), {})
    calls = []

    class FakeModel:
        missing = False

        def __init__(self, *args, **kwargs):
            calls.append(kwargs['local_files_only'])
            if self.missing and kwargs['local_files_only']:
                raise missing_type('not in cache')

        def transcribe(self, *args, **kwargs):
            return iter([]), SimpleNamespace(language='en')

    args = SimpleNamespace(file='unused', model='base', model_dir=None, no_download=False, download=False,
                           language=None, prompt=None, stream=0, vad_disabled=False)
    output = io.StringIO()
    with patch.dict(sys.modules, {'faster_whisper': SimpleNamespace(WhisperModel=FakeModel)}), \
            patch.object(module, 'duration', return_value=1), \
            patch.object(module, 'decode_audio_window', return_value=[]), contextlib.redirect_stdout(output):
        module.faster(args)
        cached_output = output.getvalue()
        output.seek(0)
        output.truncate(0)
        FakeModel.missing = True
        try:
            module.faster(args)
        except ValueError as error:
            refused = str(error)
        args.download = True
        module.faster(args)
    record('map: cached models do not trigger a download notice', calls == [True, True, True, False]
           and 'download' not in cached_output.lower(), cached_output)
    record('map: missing model is disclosed and requires permission before a download-capable lookup',
           'not cached' in refused and '150 MB' in refused and '--download' in refused
           and 'explicitly permitted' in output.getvalue(), refused + output.getvalue())


def check_cutaway_labels(tool, record, j):
    """Cutaway boundaries must not look like new spoken lines."""
    import importlib.util
    path = Path(__file__).resolve().parent.parent / 'strip.py'
    spec = importlib.util.spec_from_file_location('strip_cutaway_case', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    row = {'kind': 'cutaway', 'source': 'broll_01', 'section': 'Interview', 'start': 1.5, 'end': 2.5}
    start = module.line_event(row, 'start')[1]
    end = module.line_event(row, 'end')[1]
    record('map: strip labels cutaway start and end with their source',
           'CUTAWAY START' in start and 'CUTAWAY END' in end and 'broll_01' in start, start + ' / ' + end)


def check_transcript_review_prompts(tool, record, j, scripts_dir):
    """Keep draft words intact while showing repeat, silence and uncovered-audio prompts."""
    import importlib.util
    root = Path(j('transcript-review'))
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    text = ['we', 'have', 'a', 'plan', 'we', 'have', 'a', 'plan', 'ghost']
    rows = [{'id': f'int_01-w{index + 1:06d}', 'text': word, 'start': index * .25,
             'end': index * .25 + .15} for index, word in enumerate(text)]
    rows[-1].update(start=3.0, end=3.2)
    values = [-200.0] * 24
    values[:9] = [-20.0] * 9
    values[16:23] = [-20.0] * 7
    audio = {'speech_band_db': {'step_s': .25, 'values': values}}
    (folder / 'audio.json').write_text(json.dumps(audio), encoding='utf-8')
    words_path = folder / 'words.json'
    words_path.write_text(json.dumps({'words': rows}), encoding='utf-8')
    original = words_path.read_bytes()
    spec = importlib.util.spec_from_file_location('wave2_map', Path(scripts_dir) / 'map.py')
    mapping = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mapping)
    mapping.write_transcript(folder, 'int_01', rows)
    review = json.loads((folder / 'transcript-review.json').read_text(encoding='utf-8'))
    kinds = {row['kind'] for row in review['prompts']}
    markdown = (folder / 'transcript.md').read_text(encoding='utf-8')
    record('map: transcript review keeps words and surfaces repeat, low energy and uncovered audio',
           words_path.read_bytes() == original
           and {'repeated_phrase', 'word_in_low_energy', 'uncovered_energy'} <= kinds
           and 'Review prompts' in markdown and 'never delete words' in markdown,
           f'kinds={kinds}; markdown={markdown[:500]}')
    index = {'version': 1, 'sources': [{'alias': 'int_01', 'role': 'interview', 'path': 'unused.wav',
                                       'duration_s': 6, 'video': None, 'audio': {'index': 0}}]}
    (root / 'map' / 'sources.json').write_text(json.dumps(index), encoding='utf-8')
    film = ('---\nsize: 320x180\nfps: 25\ncaptions: srt\n---\n'
            '> int_01 0:00-0:05 we have a plan we have a plan ghost\n')
    (root / 'film.md').write_text(film, encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--no-audio', '--json')
    record('map: transcript concerns are shown at paper-edit joins without deleting words',
           code in (0, 1) and 'transcript review' in output and 'listen around the paper-edit joins' in output
           and words_path.read_bytes() == original, output[-1000:])
    record('map: uncovered energy is explicitly a possible music or noise false positive',
           any(item['kind'] == 'uncovered_energy' and 'music or noise' in item['detail']
               for item in review['prompts']), str(review['prompts']))
    quiet = mapping.transcribe.transcript_review([], {'speech_band_db': {'step_s': .25, 'values': [-55.0] * 8}})
    record('map: quiet untranscribed energy remains a disclosed heuristic blind spot',
           not any(item['kind'] == 'uncovered_energy' for item in quiet['prompts'])
           and 'heuristic' in quiet['energy_check'], str(quiet))
    # With the voice-activity model's segments, only speech without words is prompted; music under them is not.
    loud = {'step_s': .25, 'values': [-20.0] * 32}
    spoken = [{'id': f'int_01-w{index + 1:06d}', 'text': 'word', 'start': index * .5, 'end': index * .5 + .4}
              for index in range(5)]
    heard = mapping.transcribe.transcript_review(spoken, {'speech_band_db': loud, 'speech_activity': {
        'method': 'Silero voice-activity model (faster-whisper)', 'segments': [[0.1, 2.3], [3.5, 5.5]]}})
    uncovered = [(item['start'], item['end']) for item in heard['prompts'] if item['kind'].startswith('uncovered')]
    music = mapping.transcribe.transcript_review(spoken, {'speech_band_db': loud, 'speech_activity': {
        'method': 'Silero voice-activity model (faster-whisper)', 'segments': []}})
    record('map: speech the voice-activity model hears without words is prompted; music under no speech is not',
           uncovered == [(3.5, 5.5)] and 'voice-activity' in heard['energy_check']
           and not any(item['kind'].startswith('uncovered') for item in music['prompts']),
           f'heard={heard["prompts"]}; music={music["prompts"]}')
    unsure_words = [dict(word, p=.95) for word in spoken]
    unsure_words[1]['p'], unsure_words[2]['p'] = .05, .1
    unsure = mapping.transcribe.transcript_review(unsure_words, {'speech_band_db': loud})
    flagged = [item for item in unsure['prompts'] if item['kind'] == 'low_confidence']
    record('map: words the transcriber was unsure of become one review prompt naming them',
           len(flagged) == 1 and flagged[0]['word_ids'] == [spoken[1]['id'], spoken[2]['id']], str(flagged))
    record('map: speech segments split at a decoding chunk edge are joined',
           mapping.transcribe.merge_speech([[599.8, 600.0], [600.0, 601.2], [605, 606]])
           == [[599.8, 601.2], [605.0, 606.0]], str(mapping.transcribe.merge_speech([[599.8, 600.0], [600.0, 601.2]])))


def check_adjacent_repeats(record, scripts_dir):
    """Repeated phrases elsewhere in an interview do not imply a transcription loop."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('round2_transcribe', Path(scripts_dir) / 'transcribe.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def prompts(text):
        words = [{'id': str(index), 'text': word, 'start': index * .25, 'end': index * .25 + .2}
                 for index, word in enumerate(text.split())]
        original = json.dumps(words)
        result = module.transcript_review(words, {'speech_band_db': {'step_s': .25, 'values': [-20.0] * 48}})
        return [item for item in result['prompts'] if item['kind'] == 'repeated_phrase'], json.dumps(words) == original

    distant, intact = prompts('James Webb Space Telescope gives us data James Webb Space Telescope')
    repeated, intact2 = prompts('We have a plan we have a plan')
    record('map: repeated interview topics are not mistaken for adjacent transcription loops',
           not distant and len(repeated) == 1 and intact and intact2, f'distant={distant}; adjacent={repeated}')


def polish_map_cases(tool, record, j):
    """Correct one edge, inspect timed words and check completeness without remapping."""
    import hashlib
    root = Path(j('polish-map'))
    folder = root / 'map' / 'int_01'
    folder.mkdir(parents=True, exist_ok=True)
    media = root / 'source.bin'
    media.write_bytes(b'synthetic source')
    identity = hashlib.sha256(media.read_bytes()).hexdigest()
    source = {'alias': 'int_01', 'role': 'interview', 'path': 'source.bin', 'sha256': identity,
              'duration_s': 2, 'video': None, 'audio': {'index': 1},
              'mapped': {'shots': True, 'audio': True, 'words': True}}
    (root / 'map' / 'sources.json').write_text(json.dumps({'sources': [source]}), encoding='utf-8')
    rows = [{'id': 'int_01-w000001', 'text': 'First', 'start': .1, 'end': .25},
            {'id': 'int_01-w000002', 'text': 'middle', 'start': .3, 'end': .6},
            {'id': 'int_01-w000003', 'text': 'last.', 'start': .8, 'end': 1.0}]
    path = folder / 'words.json'
    path.write_text(json.dumps({'words': rows}), encoding='utf-8')
    (folder / 'shots.json').write_text(json.dumps({'version': 1, 'source': 'int_01', 'shots': []}),
                                       encoding='utf-8')
    (folder / 'audio.json').write_text(json.dumps({'version': 1, 'source': 'int_01', 'stream_index': 1,
                                                  'silences': [{'start': .65, 'end': .8}],
                                                  'levels_db': {'values': []},
                                                  'speech_band_db': {'values': []}}), encoding='utf-8')
    (folder / 'cache.json').write_text(json.dumps({'format_version': 1, 'sha256': identity,
                                                  'audio_stream': 1}), encoding='utf-8')
    code, output = tool('map.py', 'fix', root, 'int_01-w000002', '--start', '.35', '--end', '.65')
    fixed = json.loads(path.read_text(encoding='utf-8'))['words'][1]
    decisions = root / 'decisions.jsonl'
    logged = decisions.read_text(encoding='utf-8') if decisions.is_file() else ''
    record('map: timing-only correction is saved with the word ID and an audit decision',
           code == 0 and fixed['text'] == 'middle' and fixed['start'] == .35 and fixed['end'] == .65
           and '.3' in logged and '.65' in logged, output + logged)
    before = path.read_bytes()
    checks = []
    for opts in (('--start', '.2'), ('--end', '.9'), ('--end', '2.1'), ('--start', 'nan')):
        outcome, _ = tool('map.py', 'fix', root, 'int_01-w000002', *opts)
        checks.append(outcome == 2 and path.read_bytes() == before)
    record('map: timing corrections refuse overlapping, out-of-source and non-finite edges', all(checks), str(checks))
    code, output = tool('map.py', 'words', root, 'int_01', '--from', '0:00.30', '--to', '0:01.00')
    record('map: words lists IDs, source-clock edges and measured quiet between words',
           code == 0 and 'int_01-w000002' in output and 'middle' in output
           and '0.350' in output and '0.650' in output and 'quiet' in output.lower(), output)
    status = root / 'status.json'
    code, output = tool('map.py', 'run', root, '--check')
    record('map: quick complete check does not change project status',
           code == 0 and 'complete' in output.lower() and not status.exists(), output)
    cache = folder / 'cache.json'
    key = json.loads(cache.read_text(encoding='utf-8'))
    key['format_version'] = 999
    cache.write_text(json.dumps(key), encoding='utf-8')
    code, output = tool('map.py', 'run', root, '--check')
    record('map: a different map format version is incomplete', code == 1 and 'format' in output, output)
    key['format_version'] = 1
    cache.write_text(json.dumps(key), encoding='utf-8')
    (folder / 'audio.json').unlink()
    code, output = tool('map.py', 'run', root, '--check')
    record('map: quick check reports missing outputs as incomplete',
           code == 1 and ('incomplete' in output.lower() or 'missing' in output.lower()), output)


def check_words_pause_report(tool, record, j):
    """map.py words on a source whose pauses hold steady noise just above -40 dB (about -39 dB RMS, the level of a
    film's room tone): FFmpeg's fixed threshold finds no silence, so the report shows each pause from voice activity
    and its drop below the words, and says the threshold cannot see them. A map without voice activity (an older
    map, or one made without faster-whisper) still shows the levels."""
    import re
    import wave
    import numpy as np
    rate = 8000  # the map measures levels at 8 kHz, so white noise at this rate keeps its level
    times = np.arange(int(rate * 9.0)) / rate
    # Uniform noise of +/-0.02: about -39 dB RMS with peaks near -34 dB, so no 0.1 s stays below -40 dB.
    samples = np.random.default_rng(40).uniform(-0.02, 0.02, len(times))
    spoken = [('alpha', 0.5, 1.5), ('bravo', 3.1, 4.1), ('charlie', 5.0, 6.0), ('delta', 7.0, 8.0)]
    for _, start, end in spoken:
        inside = (times >= start) & (times < end)
        samples[inside] += 0.3 * np.sin(2 * np.pi * 440 * times[inside])
    source = Path(j('pause-noise.wav'))
    with wave.open(str(source), 'wb') as sound:
        sound.setparams((1, 2, rate, len(samples), 'NONE', 'not compressed'))
        sound.writeframes((samples * 32767).astype('<i2').tobytes())
    transcript = Path(j('pause-noise.json'))
    transcript.write_text(json.dumps({'words': [{'text': text, 'start': start, 'end': end}
                                                for text, start, end in spoken]}), encoding='utf-8')
    root = Path(j('pause-project'))
    tool('map.py', 'add', root, source, '--role', 'interview')
    code, output = tool('map.py', 'run', root, '--alias', 'int_01', '--words', 'import:' + str(transcript))
    path = root / 'map' / 'int_01' / 'audio.json'
    audio = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    record('map: steady noise just above -40 dB hides every pause from the fixed silence threshold',
           code == 0 and audio.get('silences') == [], output[-300:] + str(audio.get('silences')))
    audio['speech_activity'] = {'method': 'synthetic voice activity',
                                'segments': [[start - 0.05, end + 0.05] for _, start, end in spoken]}
    path.write_text(json.dumps(audio), encoding='utf-8')
    code, output = tool('map.py', 'words', root, 'int_01')
    level = re.search(r'alpha\n  word gap 1\.600s; nothing spoken 1\.550-3\.050s \(1\.500s\); level falls to '
                      r'(-\d+\.\d) dB, (\d+) dB below the words either side\n', output)
    record('map: words shows how long nothing is spoken in each pause and how far its level falls',
           code == 0 and level is not None and -40 < float(level.group(1)) < -36 and int(level.group(2)) >= 15
           and 'quiet' in output, output)
    record('map: words says plainly when the fixed threshold cannot see this source\'s pauses',
           'touches 0 of the 3 clear pauses' in output and 'cannot see these pauses' in output, output)
    for label, value in (('an older map', None), ('a map made without faster-whisper', 'null')):
        if value is None:
            audio.pop('speech_activity', None)
        else:
            audio['speech_activity'] = None
        path.write_text(json.dumps(audio), encoding='utf-8')
        code, output = tool('map.py', 'words', root, 'int_01', '--from', '1', '--to', '3.5')
        record(f'map: words on {label}, with no voice activity, still shows the level drop and says why',
               code == 0 and 'no voice activity' in output and 'nothing spoken 1' not in output
               and re.search(r'word gap 1\.600s; level falls to -\d+\.\d dB, \d+ dB below', output) is not None,
               output)


def polish_cache_relocation_case(tool, record, j, scripts_dir):
    """A new skill path and changed script bytes reuse a complete map for unchanged source content."""
    import shutil
    import sys
    import wave
    root = Path(j('polish-cache-project'))
    source = Path(j('polish-cache.wav'))
    with wave.open(str(source), 'wb') as sound:
        sound.setparams((1, 2, 8000, 8000, 'NONE', 'not compressed'))
        sound.writeframes(b'\x00\x00' * 8000)
    added, output = tool('map.py', 'add', root, source, '--role', 'interview')
    first, output2 = tool('map.py', 'run', root, '--words', 'skip')
    waiting, waiting_output = tool('project.py', 'stage', root, 'map', 'waiting', '--note', 'Review transcript')
    folder = root / 'map' / 'int_01'
    output_files = [folder / 'shots.json', folder / 'audio.json']
    old = [path.read_bytes() for path in output_files] if all(path.exists() for path in output_files) else []
    moved = Path(j('polish-moved-scripts'))
    shutil.copytree(scripts_dir, moved, ignore=shutil.ignore_patterns('__pycache__', '.git'))
    mapper = moved / 'map.py'
    with mapper.open('a', encoding='utf-8') as handle:
        handle.write('\n# A path-independent script change.\n')
    proc = subprocess.run([sys.executable, '-I', '-B', str(mapper), 'run', str(root), '--words', 'skip'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    new = [path.read_bytes() for path in output_files] if old else []
    cache = json.loads((folder / 'cache.json').read_text(encoding='utf-8')) if old else {}
    record('map: changed scripts at a different skill path reuse the unchanged source map',
           added == first == proc.returncode == 0 and 'cached' in proc.stdout and old == new
           and cache.get('format_version') == 1 and 'scripts' not in cache, output + output2 + proc.stdout)
    status = json.loads((root / 'status.json').read_text(encoding='utf-8'))
    record('map: rerunning a finished map preserves an explicit wait for the person',
           waiting == 0 and status['stages']['map'] == 'waiting', waiting_output + proc.stdout + str(status))
