"""Role-aware map (SPEC §9): map.py run --words auto transcribes speech roles only, so a music or sfx source never
waits on transcription; --words all transcribes every role, lyrics included. The engine here is FFmpeg's with a model
file that does not exist, so --words all must try to transcribe and say why it cannot, and no model is loaded."""
import math
import struct
import wave
from pathlib import Path


def tone(path, seconds=2.0, rate=48000):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        stream.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
                                    for i in range(int(seconds * rate))))


def run_roles_cases(tool, record, j, scripts_dir, skip=None):
    root = Path(j('roles-cases'))
    root.mkdir(parents=True, exist_ok=True)
    music = root / 'bed.wav'
    tone(music)
    project = root / 'project'
    code, out = tool('project.py', 'init', project)
    code_add, out_add = tool('map.py', 'add', project, music, '--role', 'music')
    missing = root / 'no-such-model.bin'
    code_auto, out_auto = tool('map.py', 'run', project, '--words', 'auto', '--engine', 'ffmpeg',
                               '--ggml-model', missing)
    words = project / 'map' / 'music_01' / 'words.json'
    record('roles: mapping a music role with --words auto does not halt on transcription',
           code == 0 and code_add == 0 and code_auto == 0 and not words.exists() and 'words skipped' in out_auto,
           f'exit {code_auto}: ' + out_auto.strip()[-300:])
    code_check, out_check = tool('map.py', 'run', project, '--check')
    record('roles: --check reads a music role without words as complete',
           code_check == 0 and 'words skipped for role music' in out_check, out_check.strip()[-300:])
    code_all, out_all = tool('map.py', 'run', project, '--words', 'all', '--engine', 'ffmpeg', '--ggml-model', missing)
    tried = words.exists() or ('transcri' in out_all.lower() and code_all != 0)
    record('roles: --words all transcribes a music role (here it tries and names why it cannot)',
           tried and 'words skipped' not in out_all, f'exit {code_all}: ' + out_all.strip()[-300:])
