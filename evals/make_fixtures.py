#!/usr/bin/env python3
"""Build the media the behaviour evaluations use into evals/files/.

  python evals/make_fixtures.py

check-me.mp4 (eval 2) is meant to be 640x360, 30 fps, 4 s with audio. It has three planted defects:
  - colour tags missing (default conversion, no BT.709 tags);
  - a 3.2 s soundtrack muxed with -shortest, which truncates the picture short of 4 s;
  - a full-frame white flash at 5 Hz from 1.0 s to 2.0 s (a WCAG 2.3.1 candidate).
demo.mp4 (eval 4) is a 20 s silent 1280x720 product demo in three passages: a card arrives at 1 s;
a cursor moves to a button and presses it at 8 s and 11 s; a success bar fills from 12 s to 16 s.
film-v3.mp4 (eval 5) is a 10 s 1280x720 test film with a tone, standing in for unreleased material.
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

    demo = os.path.join(OUT, 'demo.mp4')
    shapes = [('0x14181c', '1280x720'), ('0xf2f2f2', '520x300'), ('0x3b82f6', '180x56'), ('0x93c5fd', '180x56'),
              ('0xffffff', '18x18'), ('0x22c55e', '800x24')]
    inputs = []
    for colour, size in shapes:
        inputs += ['-f', 'lavfi', '-i', f'color=c={colour}:s={size}:r=30:d=20']
    graph = ("[0][1]overlay=x=380:y=150:enable='gte(t,1)'[a];"
             "[a][2]overlay=x=550:y=380:enable='gte(t,5)'[b];"
             "[b][3]overlay=x=550:y=380:enable='between(t,8,8.2)+between(t,11,11.2)'[c];"
             "[c][4]overlay=x='if(lt(t,8),200+(t-5)*120,560)':y='if(lt(t,8),560-(t-5)*50,410)':"
             "enable='between(t,5,12)'[d];"
             "[d][5]overlay=x='-800+min(t-12,4)*260':y=600:enable='gte(t,12)',format=yuv420p[v]")
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y', *inputs, '-filter_complex', graph,
                    '-map', '[v]', '-c:v', 'libx264', '-crf', '20', '-t', '20', demo], check=True)
    print(demo)

    film = os.path.join(OUT, 'film-v3.mp4')
    subprocess.run(['ffmpeg', '-hide_banner', '-v', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc2=size=1280x720:rate=30:duration=10',
                    '-f', 'lavfi', '-i', 'sine=frequency=330:sample_rate=48000:duration=10',
                    '-vf', 'format=yuv420p', '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-crf', '22',
                    '-c:a', 'aac', '-b:a', '128k', film], check=True)
    print(film)


if __name__ == '__main__':
    main()
