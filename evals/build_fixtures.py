#!/usr/bin/env python3
"""Build small local evaluation inputs from verified public sources.

  python evals/build_fixtures.py CACHE OUTPUT

Run the media fetcher first. OUTPUT is scratch outside the repository. On the shared
machine, run one heavy job at a time and check free memory first: this command renders.
The synthetic tutorial and XML are simulations, not recordings of a real editor.
Publisher caption cues are reference candidates, not verified word boundaries.
Exit 0 on success, 2 if inputs, tools or rendering are unavailable.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
MANIFEST = HERE / 'media' / 'sources.json'


def sha256(path):
    """Hash a potentially large input without loading it into memory."""
    result = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def checked(cache, name):
    """Reject a missing or modified input, including an incorrect cached file."""
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    rows = {row['file']: row for row in manifest['sources']}
    path = cache / name
    if not path.is_file() or sha256(path) != rows[name]['sha256']:
        raise ValueError(f'{name} is missing or differs from its pinned SHA-256')
    return path


def run(*args):
    """Run one bounded FFmpeg render, stopping on the first error."""
    command = ['ffmpeg', '-hide_banner', '-v', 'error', '-y', '-threads', '1']
    command.extend(str(value) for value in args)
    completed = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if completed.returncode:
        raise RuntimeError(completed.stderr[-3000:])


def interview(source, out):
    """A short, real, publisher-captioned excerpt, scaled to keep the jobs small."""
    run('-ss', '54.120', '-i', source, '-t', '10.277', '-map', '0:v:0', '-map', '0:a:0',
        '-vf', 'scale=480:270,fps=30', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1',
        '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-movflags', '+faststart', out)


def split_pause(source, out):
    """Insert a known 2.4-second freeze and silence at the publisher cue boundary."""
    graph = (
        '[0:v]trim=0:2.267,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=2.4[v0];'
        '[0:a]atrim=0:2.267,asetpts=PTS-STARTPTS,apad=pad_dur=2.4,atrim=duration=4.667[a0];'
        '[0:v]trim=start=2.267,setpts=PTS-STARTPTS[v1];'
        '[0:a]atrim=start=2.267,asetpts=PTS-STARTPTS[a1];'
        '[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]'
    )
    run('-i', source, '-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', out)


def delayed_audio(source, out):
    """Shift the real audio 1.2 s later without silently trimming the end."""
    graph = '[0:v]tpad=stop_mode=clone:stop_duration=1.2[v];[0:a]adelay=1200:all=1[a]'
    run('-i', source, '-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', out)


def false_start(source, out):
    """Prepend the first half of a sentence, a silence, and the complete take."""
    graph = (
        '[0:v]trim=0:1.1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.7[v0];'
        '[0:a]atrim=0:1.1,asetpts=PTS-STARTPTS,apad=pad_dur=0.7,atrim=duration=1.8[a0];'
        '[0:v]setpts=PTS-STARTPTS[v1];[0:a]asetpts=PTS-STARTPTS[a1];'
        '[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]'
    )
    run('-i', source, '-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-c:v', 'libx264',
        '-preset', 'ultrafast', '-threads', '1', '-pix_fmt', 'yuv420p', '-c:a', 'aac', out)


def font(size):
    """Use an installed readable font; keep Pillow's default as a fallback."""
    for name in ('arial.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def tutorial_frame(path, step):
    """Draw a deliberately small, synthetic screen sequence with an identifiable pointer."""
    image = Image.new('RGB', (640, 360), '#edf2f7')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 639, 55), fill='#24324b')
    draw.text((22, 13), 'Field notes', font=font(24), fill='white')
    draw.rounded_rectangle((40, 85, 600, 320), radius=10, fill='white', outline='#aab6c4', width=2)
    labels = ['1. Open a project', '2. Add a note', '3. Save the note']
    draw.text((65, 108), labels[step], font=font(26), fill='#17273c')
    draw.rectangle((66, 172, 445, 218), outline='#52627a', width=2)
    draw.text((80, 180), 'Project: Hill survey', font=font(19), fill='#17273c')
    draw.rounded_rectangle((465, 250, 560, 295), radius=6, fill='#2258a5')
    draw.text((483, 260), 'Save', font=font(18), fill='white')
    positions = [(120, 130), (340, 190), (500, 270)]
    x, y = positions[step]
    draw.polygon([(x, y), (x + 7, y + 23), (x + 13, y + 14), (x + 22, y + 13)], fill='#e94831')
    image.save(path)


def tutorial(out, scratch):
    """Render three UI states: 4, 4 and 2 seconds; two intentional waits are 2 seconds each."""
    images = []
    for number in range(3):
        path = scratch / f'tutorial-{number}.png'
        tutorial_frame(path, number)
        images.append(path)
    graph = '[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]'
    run('-loop', '1', '-t', '4', '-i', images[0], '-loop', '1', '-t', '4', '-i', images[1],
        '-loop', '1', '-t', '2', '-i', images[2], '-filter_complex', graph, '-map', '[v]',
        '-r', '15', '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-pix_fmt', 'yuv420p', out)


def caption_reference(out, shift):
    """Publisher cues clipped to whole phrases; these have not been verified by listening."""
    lines = [
        (0.0, 2.269, 'John Mather, welcome to Curious Universe.'),
        (2.269, 4.338, "Thank you, Padi, it's great to be here with you."),
        (4.338, 5.539, "I'm delighted that you're here."),
        (5.539, 7.775, "It's the first time we've seen each other in a while"),
        (7.775, 10.277, 'since the James Webb Space Telescope launched.'),
    ]

    def stamp(seconds):
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3600000)
        minutes, milliseconds = divmod(milliseconds, 60000)
        seconds, milliseconds = divmod(milliseconds, 1000)
        return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'

    blocks = []
    for number, (start, end, text) in enumerate(lines, 1):
        blocks.append(f'{number}\n{stamp(start + shift)} --> {stamp(end + shift)}\n{text}')
    with out.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write('\n\n'.join(blocks) + '\n')


def main():
    """Render the shared inputs and write a provenance file for the fixture build."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cache', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        source = checked(args.cache, 'video/mather_interview.webm')
        checked(args.cache, 'references/mather.srt')
        base = args.output / 'inputs'
        private = args.output / 'references'
        base.mkdir(parents=True, exist_ok=True)
        private.mkdir(parents=True, exist_ok=True)
        interview(source, base / 'interview.mp4')
        split_pause(base / 'interview.mp4', base / 'interview-gap.mp4')
        delayed_audio(base / 'interview.mp4', base / 'interview-offset.mp4')
        false_start(base / 'interview.mp4', base / 'interview-false-start.mp4')
        tutorial(base / 'tutorial.mp4', private)
        caption_reference(private / 'interview.srt', 0)
        caption_reference(private / 'interview-offset.srt', 1.2)
        info = {
            'source': 'video/mather_interview.webm',
            'source_start_s': 54.12,
            'source_duration_s': 10.277,
            'inserted_pause_s': 2.4,
            'pause_at_s': 2.267,
            'audio_offset_s': 1.2,
            'reference': 'NASA publisher captions: phrase timings and text not independently verified',
            'tutorial': 'Pillow simulation, not a real screen capture',
        }
        (args.output / 'provenance.json').write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
        print(f'built fixtures in {args.output}')
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
