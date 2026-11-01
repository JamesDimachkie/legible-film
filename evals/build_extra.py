#!/usr/bin/env python3
"""Add source-shot and simulated timeline fixtures to a completed fixture build.

  python evals/build_extra.py CACHE FIXTURES

This renders small picture-only excerpts from a pinned CC BY film, and creates
synthetic XML revisions tied to the NASA excerpt. The XML word boundaries are
estimated, not verified timings. It renders: run one heavy job at a time.
Exit 0 on success, 2 on error.
"""
import argparse
import importlib.util
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('fixture_builder', HERE / 'build_fixtures.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)


def shot(source, out, start):
    """Extract a short picture-only shot without the film's soundtrack."""
    B.run('-ss', str(start), '-i', source, '-t', '3.2', '-map', '0:v:0', '-an', '-vf', 'scale=480:200,fps=24',
          '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '1', '-pix_fmt', 'yuv420p', out)


def add_text(parent, tag, value):
    """Add one XML element and set its text."""
    node = ET.SubElement(parent, tag)
    node.text = str(value)
    return node


def rate(parent):
    """Add an integral 30 fps rate."""
    node = ET.SubElement(parent, 'rate')
    add_text(node, 'timebase', 30)
    add_text(node, 'ntsc', 'FALSE')


def timeline(path, spans):
    """Write a minimal FCP 7 XML with one audio track and source ranges in frames."""
    root = ET.Element('xmeml', {'version': '4'})
    sequence = ET.SubElement(root, 'sequence')
    add_text(sequence, 'name', 'Public corpus simulation')
    add_text(sequence, 'duration', sum(end - start for start, end in spans))
    rate(sequence)
    media = ET.SubElement(sequence, 'media')
    audio = ET.SubElement(media, 'audio')
    track = ET.SubElement(audio, 'track')
    cursor = 0
    for number, (start, end) in enumerate(spans):
        clip = ET.SubElement(track, 'clipitem', {'id': f'clip-{number}'})
        add_text(clip, 'name', 'interview.mp4')
        add_text(clip, 'enabled', 'TRUE')
        rate(clip)
        add_text(clip, 'start', cursor)
        add_text(clip, 'end', cursor + end - start)
        add_text(clip, 'in', start)
        add_text(clip, 'out', end)
        reference = ET.SubElement(clip, 'file', {'id': 'public-source'})
        if number == 0:
            add_text(reference, 'name', 'interview.mp4')
            add_text(reference, 'pathurl', 'file://localhost/interview.mp4')
            rate(reference)
        cursor += end - start
    ET.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def words(path):
    """Split publisher cues into estimated timings; never claim word alignment."""
    cues = [
        (0.0, 2.269, 'John Mather welcome to Curious Universe'),
        (2.269, 4.338, "Thank you Padi it's great to be here with you"),
        (4.338, 5.539, "I'm delighted that you're here"),
        (5.539, 7.775, "It's the first time we've seen each other in a while"),
        (7.775, 10.277, 'since the James Webb Space Telescope launched'),
    ]
    all_words = []
    for start, end, text in cues:
        tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)
        for index, token in enumerate(tokens):
            left = start + (end - start) * index / len(tokens)
            right = start + (end - start) * (index + 1) / len(tokens)
            all_words.append({'id': f'w{len(all_words) + 1:03}', 'text': token, 'start': left, 'end': right,
                              'estimated': True})
    data = {'sources': [{'id': 'int_01', 'media_reference': 'interview.mp4', 'words': all_words}]}
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')


def expected(path, statuses, shift):
    """Write hand-derived caption fates for an edit, independently of exchange.py."""
    rows = []
    for number, status in enumerate(statuses, 1):
        row = {'caption': number, 'status': status}
        if status == 'moved':
            row['shift_s'] = shift
        if status == 'stale' and number == 1:
            row['cut_words'] = ['welcome', 'to']
        rows.append(row)
    path.write_text(json.dumps({'captions': rows}, indent=2) + '\n', encoding='utf-8')


def main():
    """Build three film shots and two labelled, synthetic timeline revisions."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('cache', type=Path)
    parser.add_argument('fixtures', type=Path)
    args = parser.parse_args()
    try:
        source = B.checked(args.cache, 'video/tears_of_steel_720p.mov')
        music = B.checked(args.cache, 'music/evening_melodrama.mp3')
        full_interview = B.checked(args.cache, 'video/mather_interview.webm')
        narration = B.checked(args.cache, 'speech/tale.mp3')
        inputs = args.fixtures / 'inputs'
        references = args.fixtures / 'references'
        if not (inputs / 'interview.mp4').is_file() or not (references / 'interview.srt').is_file():
            raise ValueError('run build_fixtures.py first')
        for name, start in (('a', 90), ('b', 180), ('c', 270)):
            shot(source, inputs / f'shot-{name}.mp4', start)
        shutil.copyfile(music, inputs / 'song.mp3')
        shutil.copyfile(full_interview, inputs / 'interview-full.webm')
        shutil.copyfile(narration, inputs / 'tale.mp3')
        credits = ('Tears of Steel: (CC) Blender Foundation, https://mango.blender.org/, '
                   'https://creativecommons.org/licenses/by/3.0/.\n'
                   'Evening Melodrama: Kevin MacLeod, https://incompetech.com/, '
                   'https://creativecommons.org/licenses/by/3.0/.\n'
                   'LibriVox: A Tale of Two Cities, Charles Dickens, read by Laurie Anne Walden, US public domain.\n'
                   'Cosmic Dawn: NASA Goddard Space Flight Center; music rights not independently verified.\n')
        with (inputs / 'source-credits.txt').open('w', encoding='utf-8', newline='\n') as handle:
            handle.write(credits)
        shutil.copyfile(references / 'interview.srt', inputs / 'premiere.srt')
        timeline(inputs / 'before.xml', [(0, 308)])
        timeline(inputs / 'after.xml', [(0, 68), (131, 308)])
        timeline(inputs / 'after-hard.xml', [(0, 22), (47, 68), (131, 308)])
        timeline(inputs / 'after-split.xml', [(0, 26), (43, 68), (130, 308)])
        words(inputs / 'premiere-words.json')
        expected(references / 'premiere-changes.json',
                 ['unchanged', 'removed', 'moved', 'moved', 'moved'], -63 / 30)
        expected(references / 'premiere-changes-hard.json',
                 ['stale', 'removed', 'moved', 'moved', 'moved'], -88 / 30)
        print(f'built extra fixtures in {args.fixtures}')
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
