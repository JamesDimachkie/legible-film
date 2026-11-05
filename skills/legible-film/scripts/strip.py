#!/usr/bin/env python3
"""Make readable screening strips from a rendered cut or any video.

  python strip.py PROJECT [--version v001]
  python strip.py --video FILE --out DIR

Shows sampled frames, measured audio and available caption and section timing. It cannot show motion or sound.
Exit 0 on success, 2 on error.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import io
import math
import os
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
spec = importlib.util.spec_from_file_location('lf_map', Path(__file__).with_name('map.py'))
mapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapper)


def font(size):
    """Choose a legible system font."""
    for name in ('C:/Windows/Fonts/arial.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf',
                 '/System/Library/Fonts/Helvetica.ttc', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                 '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf'):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def entries(path, keys):
    """Read a list or a named list from optional timeline JSON."""
    data = project.load_json(path, [])
    if isinstance(data, list):
        return data
    for key in keys:
        if isinstance(data.get(key), list):
            return data[key]
    return []


def caption_words(path):
    """The timed words of a version's captions.json: each cue's words, or the cue itself when it has none."""
    cues = entries(path, ('cues', 'captions', 'words', 'items'))
    return [word for cue in cues if isinstance(cue, dict) for word in (cue.get('words') or [cue])]


def wrap_text(draw, text, face, width):
    """Wrap text to a measured pixel width."""
    lines = []
    current = ''
    for word in text.split():
        candidate = (current + ' ' + word).strip()
        if current and draw.textlength(candidate, font=face) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def line_event(row, field):
    """Label a timeline boundary with its actual kind and source."""
    moment = float(row[field])
    kind = str(row.get('kind') or 'line').upper().replace('_', ' ')
    source = str(row.get('source') or '')
    section = str(row.get('section') or '')
    details = '  '.join(part for part in (source, section) if part)
    return moment, f'{project.format_time(moment, 1)}  {kind} {field.upper()}  {details}'.rstrip()


def make(video, out, captions, lines):
    """Render one strip per minute, divided into readable ten-second panels."""
    video = Path(video)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    facts = mapper.probe(video)
    duration = float(facts['format']['duration'])
    names = [f'strip-{minute + 1:02d}.jpg' for minute in range(math.ceil(duration / 60))] + ['strip.json']
    project.refuse_overwriting_inputs([out / name for name in names], [video])
    picture = next((s for s in facts['streams'] if s.get('codec_type') == 'video'
                    and not s.get('disposition', {}).get('attached_pic')), None)
    try:
        picture_end = float(picture.get('duration', duration)) if picture else 0
    except (TypeError, ValueError):
        picture_end = duration
    try:
        frame_rate = float(Fraction(picture.get('avg_frame_rate', '0/1'))) if picture else 0
    except (ValueError, ZeroDivisionError):
        frame_rate = 0
    end_margin = max(0.1, 1 / frame_rate) if frame_rate > 0 else 0.1
    portrait = bool(picture and picture.get('height', 0) > picture.get('width', 0))
    frame_height = 270 if portrait else 120
    frame_extra = frame_height - 120
    audio = mapper.audio_map(video, any(s['codec_type'] == 'audio' for s in facts['streams']), duration)
    values = audio['levels_db']['values']
    normal = font(23)
    small = font(19)
    dummy = ImageDraw.Draw(Image.new('RGB', (1, 1)))
    images = []

    def thumbnail(moment):
        """One panel frame as JPEG bytes; each decode is short, so several run at once."""
        seek = min(moment, max(0, picture_end - end_margin))
        cmd = ['ffmpeg', '-v', 'error', '-ss', str(seek), '-i', str(video), '-frames:v', '1',
               '-vf', f'scale=270:{frame_height}:force_original_aspect_ratio=decrease',
               '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1']
        return subprocess.run(cmd, capture_output=True, check=True).stdout

    moments = range(0, math.ceil(duration), 2) if picture and picture_end > 0 else ()
    with ThreadPoolExecutor(6) as pool:
        thumbnails = dict(zip(moments, pool.map(thumbnail, moments)))
    for minute in range(math.ceil(duration / 60)):
        start = minute * 60
        end = min(duration, start + 60)
        panels = []
        for panel_start in range(start, math.ceil(end), 10):
            panel_end = min(end, panel_start + 10)
            active = [row for row in captions if row.get('start') is not None and row.get('end') is not None
                      and panel_start <= float(row['start']) < panel_end]
            grouped = []
            for row in active:
                text = str(row.get('text', row.get('word', ''))).strip()
                if text:
                    grouped.append((float(row['start']), text))
            # Timestamped two-second groups retain timing without unreadable overlapping labels.
            pieces = []
            for group in range(5):
                selected = [(t, text) for t, text in grouped
                            if panel_start + group * 2 <= t < panel_start + group * 2 + 2]
                if selected:
                    pieces.append(project.format_time(selected[0][0], 1) + '  ' + ' '.join(x[1] for x in selected))
            text_lines = []
            for piece in pieces:
                text_lines.extend(wrap_text(dummy, piece, normal, 1430))
            events = []
            for row in lines:
                for field in ('start', 'end'):
                    if (row.get(field) is not None and panel_start <= float(row[field])
                            and (float(row[field]) < panel_end or (panel_end == duration
                                 and float(row[field]) == duration))):
                        events.append(line_event(row, field))
            labels = []
            for moment, label in sorted(events):
                labels.extend(wrap_text(dummy, label, small, 1430))
            panels.append((panel_start, panel_end, text_lines, labels))
        heights = [270 + frame_extra + max(1, len(text)) * 30 + max(1, len(labels)) * 26
                   for _, _, text, labels in panels]
        image = Image.new('RGB', (1600, sum(heights) + 20), 'white')
        draw = ImageDraw.Draw(image)
        top = 10
        for (begin, finish, text_lines, labels), height in zip(panels, heights):
            draw.line((0, top, 1599, top), fill='#555555', width=2)
            draw.text((8, top + 8), 'TIME', fill='black', font=small)
            draw.text((130, top + 8), project.format_time(begin, 0) + ' - ' + project.format_time(finish, 0),
                      fill='black', font=normal)
            draw.text((8, top + 42), 'FRAMES', fill='black', font=small)
            for n in range(5):
                t = begin + 2 * n
                if t >= finish:
                    break
                xx = 130 + n * 290
                if picture and picture_end > 0:
                    if thumbnails[t]:
                        thumb = Image.open(io.BytesIO(thumbnails[t])).convert('RGB')
                        image.paste(thumb, (xx, top + 42))
                    else:
                        draw.text((xx, top + 42), 'No picture', fill='black', font=normal)
                else:
                    draw.rectangle((xx, top + 42, xx + 260, top + 42 + frame_height), fill='#eeeeee')
                    draw.text((xx + 10, top + 55), 'No picture', fill='black', font=normal)
                draw.text((xx, top + 165 + frame_extra), project.format_time(t, 0), fill='black', font=small)
            draw.text((8, top + 200 + frame_extra), 'AUDIO', fill='black', font=small)
            draw.text((8, top + 226 + frame_extra), 'RMS dBFS', fill='black', font=small)
            draw.text((8, top + 247 + frame_extra), '-60 to 0', fill='black', font=font(15))
            draw.line((130, top + 258 + frame_extra, 1575, top + 258 + frame_extra), fill='#777777')
            for idx in range(int(begin * 4), min(len(values), math.ceil(finish * 4))):
                level = max(-60, min(0, values[idx]))
                xx = 130 + int((idx / 4 - begin) / 10 * 1445)
                draw.line((xx, top + 258 + frame_extra, xx, top + 258 + frame_extra - int((level + 60))),
                          fill='#333333', width=4)
            y = top + 270 + frame_extra
            draw.text((8, y), 'WORDS', fill='black', font=small)
            for text in text_lines or ['(none)']:
                draw.text((130, y), text, fill='black', font=normal)
                y += 30
            draw.text((8, y), 'LINES', fill='black', font=small)
            for label in labels or ['(none)']:
                draw.text((130, y), label, fill='black', font=small)
                y += 26
            top += height
        name = f'strip-{minute + 1:02d}.jpg'
        handle, temp = tempfile.mkstemp(suffix='.jpg', dir=str(out))
        os.close(handle)
        try:
            image.save(temp, quality=92)
            os.replace(temp, out / name)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        images.append({'image': name, 'start': start, 'end': end})
    project.save_json(out / 'strip.json', {'version': 1, 'images': images, 'words': len(captions)})
    print(f'{len(images)} strips, {duration:.2f}s')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('project', nargs='?')
    parser.add_argument('--version')
    parser.add_argument('--video')
    parser.add_argument('--out')
    args = parser.parse_args()
    try:
        if args.video:
            if not args.out or args.project or args.version:
                raise ValueError('--video requires --out and no project or version')
            make(args.video, args.out, [], [])
        else:
            if not args.project or args.out:
                raise ValueError('supply a project, or --video and --out')
            version = args.version or project.current_version(args.project)
            if not version or not project.VERSION_NAME.fullmatch(version):
                raise ValueError('no valid cut version')
            cut = Path(args.project) / 'cuts' / version
            make(cut / 'preview.mp4', cut / 'strip', caption_words(cut / 'captions.json'),
                 entries(cut / 'lines.json', ('lines', 'items')))
        return 0
    except Exception as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
