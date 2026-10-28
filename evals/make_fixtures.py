#!/usr/bin/env python3
"""Build the media the behaviour evaluations use, with known defects, into evals/files/.

  python evals/make_fixtures.py

check-me.mp4 is meant to be 640x360, 30 fps, 4 s with audio. It has three planted defects:
  - colour tags missing (default conversion, no BT.709 tags);
  - a 3.2 s soundtrack muxed with -shortest, which truncates the picture short of 4 s;
  - a full-frame white flash at 5 Hz from 1.0 s to 2.0 s (a WCAG 2.3.1 candidate).
Needs FFmpeg with libx264 and the native AAC encoder.
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'files')


def main():
    if not shutil.which('ffmpeg'):
        sys.exit('ffmpeg is required on PATH')
    os.makedirs(OUT, exist_ok=True)
    target = os.path.join(OUT, 'check-me.mp4')
    flash = "drawbox=x=0:y=0:w=iw:h=ih:color=white@1:t=fill:enable='between(t,1,2)*lt(mod(t,0.2),0.1)'"
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30:duration=4',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=3.2',
                    '-vf', flash + ',format=yuv420p', '-map', '0:v', '-map', '1:a',
                    '-c:v', 'libx264', '-crf', '20', '-c:a', 'aac', '-b:a', '192k', '-ac', '2',
                    '-shortest', target], check=True)
    print(target)


if __name__ == '__main__':
    main()
