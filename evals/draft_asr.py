#!/usr/bin/env python3
"""Produce a local, explicitly unverified word-timed draft from a cached model.

  python evals/draft_asr.py MEDIA --model LOCAL_MODEL_DIR --out draft.json --length 12

Needs optional faster-whisper and a separately obtained, already cached model.
For another environment, install faster-whisper with pip and provision the model
under that environment's policies. No download is attempted. Voice activity
detection is disabled; audio is decoded by FFmpeg to avoid a PyAV dependency.
This draft is not a verified transcript or precise alignment. Run one heavy job at a time.
Exit 0 for a draft, 2 if requirements are unavailable.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('eval_grade_task', HERE / 'grade_task.py')
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


def main():
    """Transcribe a bounded excerpt with a local model and preserve its word times."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('media', type=Path)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--length', type=float, default=12)
    parser.add_argument('--language', default='en')
    args = parser.parse_args()
    try:
        if not args.model.is_dir() or not args.media.is_file() or args.length <= 0:
            raise ValueError('media and local model must exist; length must be positive')
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise ValueError('optional faster-whisper is missing; install it in an authorized environment') from error
        command = ['ffmpeg', '-v', 'error', '-i', str(args.media), '-t', str(args.length), '-vn', '-ac', '1',
                   '-ar', '16000', '-f', 'f32le', 'pipe:1']
        decoded = subprocess.run(command, capture_output=True, check=True).stdout
        samples = np.frombuffer(decoded[:len(decoded) // 4 * 4], dtype='<f4')
        model = WhisperModel(str(args.model.resolve()), device='cpu', compute_type='int8', cpu_threads=2,
                             local_files_only=True)
        segments, info = model.transcribe(samples, language=args.language, vad_filter=False, word_timestamps=True)
        rows = []
        for segment in segments:
            for word in segment.words or []:
                rows.append({'text': word.word.strip(), 'start': word.start, 'end': word.end,
                             'probability': word.probability})
        result = {'engine': 'faster-whisper local model, CPU int8, no VAD', 'model_dir': str(args.model),
                  'language': info.language, 'draft': True, 'words': rows,
                  'warning': 'Unverified speech and timing; listen and check every word and edit boundary.'}
        G.P.save_json(args.out, result)
        print(f'{len(rows)} draft words; {sum(row["end"] <= row["start"] for row in rows)} zero-length timings')
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
