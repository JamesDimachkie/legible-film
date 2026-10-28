#!/usr/bin/env python3
"""Blend ordered frames into one onion-skin image to inspect a motion path.

Equal-weight overlay of two or more same-size frames (for example consecutive frames from
frame_sheet.py --keep-frames). Spacing between the ghosts shows speed: even spacing is constant
speed, bunching is easing, a sudden gap is a jump. Keep the individual frames and a normal-speed
viewing too: an overlay hides a single bad frame inside the stack.

  python onion_frames.py --out qa/onion.png qa/frames/frame-000118-at-1.967s.png qa/frames/frame-000119-at-1.983s.png

Needs Pillow. Refuses to overwrite an existing output or an input. Exit code 0 when the blend is
written, 2 when an input is missing or unreadable or the output cannot be written.
"""

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit('onion_frames.py needs Pillow: pip install Pillow')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True, type=Path, help='new PNG file')
    parser.add_argument('frames', nargs='+', type=Path, help='ordered frames (PNG or JPEG)')
    args = parser.parse_args()
    if len(args.frames) < 2:
        parser.error('supply at least two frames')
    if args.out.suffix.lower() != '.png':
        parser.error('the output must be a PNG')
    if args.out.resolve() in {path.resolve() for path in args.frames}:
        parser.error('the output must differ from the inputs')
    for path in args.frames:
        if not path.is_file():
            parser.error(f'not a file: {path}')
    merged = None
    try:
        for count, path in enumerate(args.frames, start=1):
            try:
                with Image.open(path) as source:
                    frame = source.convert('RGBA')
            except OSError as e:  # includes Pillow's UnidentifiedImageError
                parser.error(f'cannot read {path} as an image: {e}')
            if merged is None:
                merged = frame
                continue
            if frame.size != merged.size:
                frame.close()
                parser.error(f'frame size differs: {path}')
            result = Image.blend(merged, frame, 1 / count)
            merged.close()
            frame.close()
            merged = result
        try:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open('xb') as output:  # exclusive creation keeps earlier review artifacts
                merged.save(output, format='PNG')
        except FileExistsError:
            if args.out.is_file():
                parser.error(f'output already exists: {args.out}')
            parser.error(f'cannot write {args.out}: part of its folder path is a file')
        except OSError as e:
            parser.error(f'cannot write {args.out}: {e.strerror or e}')
        print(args.out)
    finally:
        if merged is not None:
            merged.close()


if __name__ == '__main__':
    main()
