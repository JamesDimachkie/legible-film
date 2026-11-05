#!/usr/bin/env python3
"""Install what setup.py installs, then test what the scripts need from each package.

  python .github/scripts/extras_check.py            # every group through setup.py, at the pinned versions
  python .github/scripts/extras_check.py --newest   # the newest releases in a throwaway environment, with no pins

Pinned, it runs setup.py --install for core, transcription, faces and spatial, and the listening group's packages, all
into the environment setup.py selects, then checks that every installed package is the version constraints.txt names.
Set LOCALAPPDATA (Windows) or XDG_DATA_HOME to an empty folder to leave your own per-user environment as it is. It
needs the network and FFmpeg, and downloads no model.

The probes are the upstream behaviour that has broken or would break the scripts: OpenCV's bundled face cascade and
trackers, PyAV decoding through faster-whisper, its voice detector on ONNX Runtime, the missing-model error transcribe.py
turns into a download prompt, and PyTorch reading numpy arrays. A pass does not prove transcription is accurate, or
anything about macOS or Linux when run on Windows. Exit 0 when every probe passed, 1 when one failed, 2 if the
installs could not run.
"""
import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'skills' / 'legible-film' / 'scripts'
GROUPS = ('core', 'transcription', 'faces', 'spatial')
NEWEST = ('numpy', 'Pillow', 'opencv-python', 'faster-whisper', 'onnxruntime', 'transformers', 'huggingface-hub',
          'safetensors', 'librosa', 'soundfile', 'soxr')
# In a new environment before any install, at the version the Python came with.
TOOLING = {'pip', 'setuptools', 'wheel'}


def run_or_stop(command):
    """Run one install step; a failure ends the run with exit 2."""
    print('$ ' + ' '.join(map(str, command)), flush=True)
    code = subprocess.run([str(part) for part in command]).returncode
    if code:
        sys.exit(2)


def load_setup():
    """setup.py as a module, for the listening packages without their 1.4 GB of weights."""
    spec = importlib.util.spec_from_file_location('lf_setup', SCRIPTS / 'setup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_pinned():
    """Every group through setup.py; returns the Python it names. Exit 1 is right here: no model was downloaded."""
    script = SCRIPTS / 'setup.py'
    for group in GROUPS:
        print(f'$ setup.py --install {group} --yes', flush=True)
        if subprocess.run([sys.executable, str(script), '--install', group, '--yes']).returncode not in (0, 1):
            sys.exit(2)
    report = subprocess.run([sys.executable, str(script), '--json'], capture_output=True, text=True, encoding='utf-8')
    python = json.loads(report.stdout)['python']
    try:
        load_setup().install_ear_packages(python)
    except ValueError as error:
        print(error, file=sys.stderr)
        sys.exit(2)
    return python


def install_newest(folder):
    """The newest releases into a new environment, and the same index for PyTorch as setup.py."""
    run_or_stop([sys.executable, '-m', 'venv', folder])
    python = Path(folder) / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    run_or_stop([python, '-m', 'pip', 'install', '--upgrade', 'torch', '--index-url',
                 'https://download.pytorch.org/whl/cpu'])
    run_or_stop([python, '-m', 'pip', 'install', '--upgrade', *NEWEST])
    return str(python)


def probe_pins():
    """Each installed package is the one constraints.txt names for this Python and system."""
    from importlib import metadata

    from pip._vendor.packaging.requirements import Requirement  # pip is in every environment setup.py installs into
    pins = {}
    for line in (SCRIPTS / 'constraints.txt').read_text(encoding='utf-8').splitlines():
        if line.strip() and not line.startswith('#'):
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate():
                pins[requirement.name.lower().replace('_', '-')] = str(requirement.specifier).lstrip('=')
    wrong = []
    for dist in metadata.distributions():
        name = dist.metadata['Name'].lower().replace('_', '-')
        version = dist.version.split('+')[0]
        if name not in TOOLING and pins.get(name) != version:
            wrong.append(f'{name} {version} (constraints.txt: {pins.get(name, "not named")})')
    assert not wrong, '; '.join(wrong)
    return f'{len(pins)} pins hold for this Python'


def probe_core():
    import PIL
    import numpy
    from PIL import Image
    assert Image.Resampling.LANCZOS is not None
    return f'numpy {numpy.__version__}, Pillow {PIL.__version__}'


def probe_opencv():
    import cv2
    import numpy
    model = Path(cv2.data.haarcascades) / 'haarcascade_frontalface_default.xml'
    classifier = cv2.CascadeClassifier(str(model))
    assert not classifier.empty(), 'the face cascade did not load'
    frame = numpy.zeros((120, 160), dtype=numpy.uint8)
    classifier.detectMultiScale(frame)
    points = cv2.goodFeaturesToTrack(numpy.random.default_rng(1).integers(0, 255, (120, 160), dtype=numpy.uint8), 20,
                                     0.01, 5)
    cv2.calcOpticalFlowPyrLK(frame, frame, points, None)
    cv2.SIFT_create()
    return f'OpenCV {cv2.__version__}: face cascade, optical flow and SIFT'


def probe_decode(folder):
    import av
    from faster_whisper.audio import decode_audio
    tone = Path(folder) / 'tone.wav'
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    str(tone)], check=True)
    samples = decode_audio(str(tone))
    assert abs(len(samples) - 16000) < 2000, f'decoded {len(samples)} samples from one second'
    return f'PyAV {av.__version__} decodes a file through faster-whisper'


def probe_voice():
    import ctranslate2
    import numpy
    import onnxruntime
    import tokenizers
    from faster_whisper.vad import get_speech_timestamps
    get_speech_timestamps(numpy.zeros(32000, dtype=numpy.float32))
    return (f'ONNX Runtime {onnxruntime.__version__} runs the voice detector; ctranslate2 {ctranslate2.__version__}, '
            f'tokenizers {tokenizers.__version__} import')


def probe_missing_model(folder):
    os.environ['HF_HUB_CACHE'] = str(Path(folder) / 'empty-cache')
    from faster_whisper import WhisperModel
    try:
        WhisperModel('small', device='cpu', compute_type='int8', local_files_only=True)
    except Exception as error:
        name = error.__class__.__name__
        assert name == 'LocalEntryNotFoundError', f'{name}, which transcribe.py would not turn into a download prompt'
        return 'a missing model raises LocalEntryNotFoundError, and nothing downloads'
    raise AssertionError('a model loaded from an empty cache')


def probe_listening():
    import librosa
    import numpy
    import soundfile
    import soxr
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification, ClapModel, ClapProcessor  # noqa: F401
    assert torch.from_numpy(numpy.zeros(3)).sum().item() == 0
    assert soxr.resample(numpy.zeros(4800, dtype=numpy.float32), 48000, 16000).shape[0] == 1600
    return f'torch {torch.__version__} reads numpy; librosa {librosa.__version__}, soundfile {soundfile.__version__}'


def probes(pinned):
    """Run in the target environment: every probe, whatever the others do. Exit 1 when one failed."""
    failed = 0
    with tempfile.TemporaryDirectory() as folder:
        steps = [('core', probe_core), ('OpenCV', probe_opencv), ('decoding', lambda: probe_decode(folder)),
                 ('voice detector', probe_voice), ('missing model', lambda: probe_missing_model(folder)),
                 ('listening packages', probe_listening)]
        if pinned:
            steps.insert(0, ('pins', probe_pins))
        for name, step in steps:
            try:
                print(f'ok    {name}: {step()}', flush=True)
            except Exception as error:
                failed += 1
                print(f'FAIL  {name}: {error.__class__.__name__}: {error}', flush=True)
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--newest', action='store_true', help='the newest releases, with no pins')
    parser.add_argument('--probes', choices=['pinned', 'newest'], help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.probes:
        return probes(args.probes == 'pinned')
    with tempfile.TemporaryDirectory() as folder:
        python = install_newest(folder) if args.newest else install_pinned()
        checks = [[python, '-m', 'pip', 'check'],
                  [python, '-I', str(Path(__file__).resolve()), '--probes', 'newest' if args.newest else 'pinned'],
                  [python, '-I', str(SCRIPTS / 'selftest.py'), '--quick'],
                  [python, '-I', str(SCRIPTS / 'selftest.py'), '--smoke']]
        codes = []
        for command in checks:
            print('$ ' + ' '.join(command), flush=True)
            codes.append(subprocess.run(command).returncode)
    return 1 if any(codes) else 0


if __name__ == '__main__':
    sys.exit(main())
