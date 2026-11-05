#!/usr/bin/env python3
"""Compile the paper edit (film.md) into a rendered version; check it, compare versions, or draft one.

  python cut.py check PROJECT [--json] [--no-audio]
  python cut.py render PROJECT [--label TEXT] [--resolves n1,n2] [--final] [--master PLATFORM] [--every-frame]
      [--json]
  python cut.py diff PROJECT vA [vB] [--json]
  python cut.py draft PROJECT --select 'int_01:"we tried everything"' [--select ALIAS:START-END ...] [--force]
  python cut.py tighten PROJECT ALIAS [--pause 0.35] [--fillers named|LIST] [--punch-in 1.1] [--music-bed]
      [--reel-limit N] [--out FILE] [--force]

check parses film.md (grammar: references/paper-edit.md) and validates it against map/ without rendering: aliases,
ranges inside each source, every spoken line's words found in order among its transcript words (a word not found is
reported with the nearest transcript words), joins, fades, and the estimated duration against `target`. Each problem
has a line number and a suggestion. check and render also warn when cover framing discards a third or more of a
source's height or width, naming the line, what keeps more of it, and any sampled face it would lose where OpenCV is
installed; a face it misses is not evidence that nobody is there.

Lines that pin to, draw behind or blur a layer in spatial/ (references/spatial.md) are checked against it: the layer
exists, is the right kind, is current for its source (the map's size and SHA-256), was made from the source on
screen under the line, and has a tracked frame for every source frame shown; under a blur, a lost or missing frame is
an error, because the render would stop. render records each layer's sidecar SHA-256 in manifest.json.

Cuts inside a spoken line go in the pause between a kept word and a removed one. The pause is measured in the source
audio, not taken from the transcript's word edges: the cut lands in a clear quiet stretch (0.12 s or more) at or
next to the transcript's pause, keeping a short handle after the kept word and at most `pad` seconds of pause each
side, to reduce the chance of cutting into a word or an audible breath. Estimated word edges get a wider search
window. Where words run together the cut goes at the quietest moment within 30 ms of the transcript's boundary
and is listed as a tight cut to listen to. When a line's audio cannot be measured (no FFmpeg, --no-audio, audio
that will not decode, or sound that never drops far below the speech), its cuts fall back to transcript times and
each one is listed as tight and unmeasured (lines' unmeasured_cuts), with a warning that says why.

Several recordings of one conversation, once map.py sync has lined them up: ~ ALIAS sync shows another camera over a
line at the same moment, with no times to retype, and follows every cut inside the line; {sound ALIAS} takes a line's
sound from a lined-up mic, and the line's cuts are measured in that sound. A stale or low-confidence line-up, a source
that does not cover the moment and a camera or mic that was not rolling yet are errors on their line. Each stretch uses
the offset at its own place in the recording, so a drifting source stays in step line by line.

Sound across a join: {tail N} runs a line's own sound on N seconds under the next line, fading out; {lead N} starts
it N seconds before its picture, fading in; {dissolve N} between two lines also crossfades their sound (equal
power), kept clear of both lines' words. The extra sound comes from the source around the written range and is
shortened, with a warning, when the source has less. No kept word moves.

The join report: every join between two passages (a change of source, or a gap in one source) is measured in the
source sound at its out and in points: the level over 0.4 s on each side, the background (sound where nobody
speaks, masked with the map's voice activity or the transcript), its 20-100 Hz low end, the change of tone, what
bridges it (tail, lead, dissolve, music bed, a cutaway's sound) and the shots around it. check warns on unbridged
background or level changes of 6 dB, low-end changes of 6 dB (or 3.5 dB when both near-join backgrounds are
bass-dominant), or tone changes of 10 dB. For a low-end change of 6 dB or more, a tail or lead under 0.5 s does not
count as bridging it. It also warns when three or more picture changes (edits and sources' own shot changes) fall
within 3 s outside a section whose name contains "montage"; a freeze (still ALIAS TIME, pause N hold) and the same
source running on from the frozen frame are one change. check --json and each version's lines.json carry joins,
picture_changes and busy_cutting. The report measures source sound before the mix, so it does not prove a join
sounds right either.

render compiles film.md into the next immutable version cuts/vNNN/: edit.json (the timeline assemble.py renders),
lines.json, word-timed captions built by captions.py from the kept words (srt, vtt, json with word IDs),
preview.mp4 (short side 540, or the film's full size with --final, which also keeps the sound stems) and
manifest.json. It then points cuts/current at the version and marks the cut stage done in status.json; a running
job shows progress while it renders. Large sources are previewed from cached proxies in cuts/.cache/.
--resolves n1,n2 only records which notes the version answers (manifest.json notes_resolved); it does not close
them, because closing needs a reply for the person. For each named note still open in notes.json the render prints
the command that closes it, `screen.py resolve PROJECT NOTE --in vNNN --reply TEXT`, with the new version filled in.
Picture, audio, words and captions share the source/edit clock; the output picture samples the source frame showing
at each output-frame time. Transcript-energy and repeated-phrase prompts ask for listening, never automatic deletion.
A plain cut has FFmpeg draw its picture; everything else (and --every-frame) passes every frame through Python. The
output and manifest.json say which ran; references/finishing.md says what counts as plain and how the two compare.
With --final --master PLATFORM, a two-pass dialogue master records both passes, the actual mode and delivered AAC
measurements in audio-master.json. Its default -16 LUFS is a working target, not a platform requirement; use
--master-target or film.md loudness to set another target. Listen to the delivered sound and review warnings.

diff reports, as text or JSON, the front-matter settings that changed (size, fps, captions, fit, crop, background,
music defaults, pad, max_pause, font, bars, loudness, target, title, caption breaks, and preview or final render), the
lines added, removed or changed (including their modifiers and source aliases), words cut or restored (word IDs),
the duration change and caption changes between two versions. With one version, it compares that version's paper
edit with the working film.md: what changed since that render (the person's edits, or yours) that no version holds
yet, as settings and lines only, since words, durations and captions exist once it renders. Read it before editing
film.md, and build on the changes it shows. draft writes a first film.md from phrases found in the transcripts.
tighten writes a paper edit, removal report and labelled BEFORE/AFTER listening reel. It shortens measured quiet and
removes only named, requested fillers. Its section crossfades sound only when measured quiet handles permit;
otherwise it keeps short edge fades. Declare a known continuous music or ambience bed with --music-bed to leave pauses and
fillers intact. Automatic measurements cannot reliably identify a steady bed. The transcript may omit words;
review the flagged sound and listen to every join.

What this does not prove: that a cut sounds or looks right. Quiet audio is not always a pause (a stop consonant can
be quiet for a moment), transcripts are drafts, and the preview is a review copy. Watch and listen to every version.
Needs numpy, Pillow and FFmpeg; check runs without FFmpeg from transcript timings alone.

A range is checked against where its source really ends: the map's decoded end of picture and sound (sources.json
"ends"), or for a map made before that the video stream's own header. A range past the picture is an error on its line
even when the sound goes on; a line whose sound ends early is an error when decoding stopped short of the header, and a
warning when the sound really is that short. The renderer never fills a range with a frozen frame: a hold is declared
(pause N hold, still ALIAS TIME N).

Exit codes: 0 nothing to report; 1 something to inspect (check found errors in film.md; a render with review notes;
phrases not found); 2 could not run, which includes a render blocked by errors in film.md, since nothing was rendered.
render --json says which with "status": "rendered" (and the version) or "blocked" (and the problems).
"""
import argparse
import contextlib
import difflib
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
# A range may run this far past its source: a header and its last frame or sample can differ by about this much.
RANGE_SLACK = 0.05


def load_sibling(name):
    """Load a sibling script as a module, the way the other 2.0 scripts load project.py."""
    spec = importlib.util.spec_from_file_location('lf_cut_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


project = load_sibling('project')

FRONT_KEYS = ('title', 'size', 'fps', 'target', 'captions', 'music', 'pad', 'max_pause', 'fit', 'crop',
              'background', 'font', 'loudness', 'bars', 'audience', 'takeaway', 'story',
              'path', 'timeline', 'page', 'frame')
# The film's direction (references/finding-the-story.md section 2): who it is for, what they leave with, its spine.
DIRECTION_KEYS = ('audience', 'takeaway', 'story')
SHORT_CLIP = 20.0  # seconds; a cut longer than this without a stated direction is warned about
RENDER_WAIT = 60  # seconds a render waits for another render of the same project before it stops
# What cut.py diff compares besides the lines: every parsed front-matter setting, caption breaks and the render mode.
OUTPUT_SETTINGS = ('size', 'fps', 'captions', 'fit', 'crop', 'background', 'music_gain', 'music_fade', 'pad',
                   'max_pause', 'font', 'bars', 'loudness', 'target', 'title', 'caption_breaks', 'render')
CAPTION_WORDS = ('burn', 'srt', 'vtt', 'none', 'plate', 'highlight')
KEYWORDS = ('title', 'still', 'music', 'pause')
POSITIONS = {'lower': 'lower', 'center': 'center', 'centre': 'center', 'upper': 'upper'}
CROPS = {'center': (0.5, 0.5), 'centre': (0.5, 0.5), 'left': (0.0, 0.5), 'right': (1.0, 0.5),
         'top': (0.5, 0.0), 'bottom': (0.5, 1.0)}
MODIFIER_WORDS = ('fit', 'zoom', 'crop', 'dissolve', 'dip', 'fade', 'sound', 'tail', 'lead', 'at', 'card',
                  'hold', 'pin', 'behind') + tuple(POSITIONS)
LAYER_NAME = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')  # a layer in the project's spatial/ folder
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.gif')
TIME = r'\d+(?::\d{1,2}){0,2}(?:\.\d+)?'
RANGE_AT_START = re.compile(rf'^({TIME})\s*[-\u2013\u2014]\s*({TIME})(?=\s|\{{|$)')
ALIAS_SHAPE = re.compile(r'^[a-z]+_\d+$')
GAIN = re.compile(r'^([+-]?\d+(?:\.\d+)?)db$', re.IGNORECASE)
NUMBER = re.compile(r'^(\d+(?:\.\d+)?|\.\d+)s?$')
SPEED = re.compile(r'^(?:x(\d+(?:\.\d+)?|\.\d+)|(\d+(?:\.\d+)?|\.\d+)x)$', re.IGNORECASE)
OFFSET = re.compile(r'^\+(\d+(?:\.\d+)?|\.\d+)s?$')
ALLOWED = {
    'spoken': {'fit', 'zoom', 'crop', 'join', 'fade_in', 'fade_out', 'sound', 'sound_from', 'tail', 'lead'},
    'picture': {'speed', 'fit', 'zoom', 'crop', 'join', 'fade_in', 'fade_out', 'sound', 'sound_from', 'tail', 'lead'},
    'cutaway': {'speed', 'fit', 'zoom', 'crop', 'join', 'sound', 'offset'},
    'synced': {'fit', 'zoom', 'crop', 'join', 'offset'},
    'still': {'fit', 'zoom', 'crop', 'join', 'fade_in', 'fade_out'},
    'still_over': {'fit', 'zoom', 'crop', 'join', 'offset', 'pin', 'behind'},
    'title': {'position', 'card', 'offset', 'at', 'fade', 'join', 'fade_in', 'fade_out', 'pin', 'behind'},
    'title_over': {'position', 'offset', 'fade', 'pin', 'behind'},
    'blur': {'offset'},
    'over': {'offset', 'fade'},
    'music': {'gain', 'fade', 'offset', 'at'},
    'pause': {'hold', 'join', 'fade_in', 'fade_out'},
}

HOP = 0.005
WINDOW = 0.015
MIN_QUIET = 0.04
CLEAR_PAUSE = 0.12
EDGE_REACH = 0.5  # seconds from a written line edge that a quiet stretch is looked for
NEAR = 0.06
DIP_REACH = 0.03
DIP_PENALTY = 120.0
HANDLE = (0.03, 0.08)
SLACK_KEPT = (0.02, 0.10)
SLACK_REMOVED = (0.06, 0.15)
AUDIO_FADE_MS = 10
CAPTION_BREAK = 0.6
TITLE_FADE = 0.25
PREVIEW_SHORT = 540
PROXY_BELOW = 0.7
MAX_FILM = 3 * 3600.0
# Joins between passages (references/paper-edit.md section 8), measured in the source sound at each out and in point.
# Calibrated on a trailer whose joins jump 7 to 12 dB and on interview cuts whose joins fall in pauses.
JOIN_WINDOW = 0.4  # seconds of sound measured on each side of a join
JOIN_EDGE = 0.15  # seconds right at the join that decide whether a side is silent
JOIN_RATE = 16000
SILENT_DB = -45.0  # dBFS at the join: quieter than this is silence (a pause), not a sound to match
JUMP_DB = 6.0  # an unbridged level change this large is abrupt
TONE_DB = 10.0  # a change of spectral shape this large (mean dB over octave bands) is a different sound world
TONE_BANDS = (63, 125, 250, 500, 1000, 2000, 4000, 8000)
LOW_BAND = (20, 100)  # Hz: the sub-bass below speech, including the reported booms below about 90 Hz
LOW_JUMP_DB = 6.0  # a large low-frequency jump in the background or near the join
LOW_DOMINANT_JUMP_DB = 3.5  # a smaller jump when the low end dominates both near-join backgrounds
LOW_DOMINANT_WITHIN_DB = 4.0  # low-band level within this many dB of the near-join background
LOW_MIN_DB = -35.0  # ignore changes where neither side has appreciable low-frequency energy
BED_REACH = 2.0  # seconds of each side's sound searched for its bed (the sound where nobody speaks)
BED_FRAME = 0.05  # seconds per frame of bed
BED_MIN_FRAMES = 3  # fewer speech-free frames than this, and a side has no bed to compare
SPEECH_PAD = 0.06  # seconds around transcript words treated as speech when the map has no voice activity
BRIDGE_COVER = 0.2  # another sound playing this far on each side of a join carries it
BRIDGE_MIN = 0.1  # the shortest tail, lead or sound crossfade that counts as carrying a join
LOW_BRIDGE_MIN = 0.5  # a lead or tail shorter than this does not bridge a large low-end change
WORD_ROOM = 0.03  # seconds a dissolve's sound crossfade keeps clear of a kept word
BUSY_CHANGES = 3  # this many picture changes ...
BUSY_SECONDS = 3.0  # ... within this many seconds, outside a montage section, is reported


# ----------------------------------------------------------------------------------------------- problems

class Problems:
    """Errors, warnings and notes about film.md, each with a line number and a suggestion."""

    def __init__(self):
        self.items = []

    def add(self, severity, line, message, suggestion=''):
        """Record one problem."""
        self.items.append({'severity': severity, 'line': line, 'message': message, 'suggestion': suggestion})

    def error(self, line, message, suggestion=''):
        """Something that stops a render."""
        self.add('error', line, message, suggestion)

    def warn(self, line, message, suggestion=''):
        """Something that renders but deserves a look."""
        self.add('warning', line, message, suggestion)

    def note(self, line, message, suggestion=''):
        """Information only."""
        self.add('info', line, message, suggestion)

    def count(self, severity):
        """How many problems of one severity."""
        return sum(1 for item in self.items if item['severity'] == severity)


def fmt(seconds):
    """A source or film time as m:ss.ss for messages."""
    return project.format_time(max(0.0, seconds))


def seconds_value(token):
    """A plain duration ('2', '2.5', '0.25s') in seconds, or None."""
    match = NUMBER.match(token or '')
    return float(match.group(1)) if match else None


def time_value(token):
    """A time (ss.ss, m:ss.ss or h:mm:ss.ss) in seconds, or None."""
    try:
        return project.parse_time(token)
    except (ValueError, TypeError):
        return None


def sha256_file(path):
    """The SHA-256 of a file, read in blocks."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def find_tool(name):
    """An executable from an environment override (FFMPEG, FFPROBE) or PATH, or None."""
    override = os.environ.get(name.upper())
    if override:
        return override if os.path.isfile(override) or shutil.which(override) else None
    return shutil.which(name)


# ----------------------------------------------------------------------------------------------- front matter

def split_front_matter(lines, problems):
    """The front matter's raw settings ({key: (value, line)}) and the index of the first body line."""
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or lines[start].strip() != '---':
        problems.error(start + 1, 'film.md has no front matter',
                       'start the file with ---, then size: 1920x1080 and fps: 30 on their own lines, then ---')
        return {}, start
    found = {}
    for index in range(start + 1, len(lines)):
        raw = lines[index]
        text = raw.strip()
        if not text or text.startswith('#'):
            continue
        # Nested record fields belong to their parent, not to cut's top-level settings.
        if raw[0].isspace():
            continue
        if text == '---':
            return found, index + 1
        key, separator, value = text.partition(':')
        if not separator:
            problems.error(index + 1, f'front matter line is not "key: value": {text}', 'write it as key: value')
            continue
        found[key.strip().lower()] = (value.strip(), index + 1)
    problems.error(start + 1, 'the front matter is not closed', 'add a line with --- after the settings')
    return found, len(lines)


def unquote(text):
    """Text without one pair of surrounding quotes."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in '"\'':
        return text[1:-1]
    return text


def default_settings():
    """Settings before the front matter is read."""
    return {'title': '', 'audience': '', 'takeaway': '', 'story': '', 'size': None, 'fps': None, 'fps_text': None,
            'target': None, 'captions': {'srt'},
            'music_gain': -18.0, 'music_fade': 1.0, 'pad': 0.2, 'max_pause': None, 'fit': 'cover',
            'crop': (0.5, 0.5), 'background': '#000000', 'font': 'sans'}


def parse_size(value, line, problems):
    """(width, height) from '1080x1920', or None with an error."""
    match = re.fullmatch(r'(\d+)\s*[xX\u00d7]\s*(\d+)', value)
    if not match:
        problems.error(line, f'size must be WIDTHxHEIGHT, not {value!r}', 'for example size: 1920x1080')
        return None
    width, height = int(match.group(1)), int(match.group(2))
    if width < 16 or height < 16 or width % 2 or height % 2:
        problems.error(line, f'size {width}x{height} must have even sides of at least 16 pixels',
                       f'use {max(16, width + width % 2)}x{max(16, height + height % 2)}')
        return None
    return width, height


def parse_fps(value, line, problems):
    """(exact rate, text for the manifest) from '30', '29.97' or '30000/1001', or (None, None)."""
    render_common = load_sibling('render_common')
    try:
        rate = render_common.exact_rate(value)
    except ValueError:
        problems.error(line, f'fps must be a number or a fraction, not {value!r}', 'for example fps: 30 or 30000/1001')
        return None, None
    text = str(rate.numerator) if rate.denominator == 1 else f'{rate.numerator}/{rate.denominator}'
    return rate, text


def parse_captions(value, line, problems):
    """The set of caption words."""
    words = {word for word in re.split(r'[,\s]+', value.lower()) if word}
    unknown = sorted(words - set(CAPTION_WORDS))
    if unknown:
        problems.error(line, f'unknown captions setting: {", ".join(unknown)}',
                       'use any of burn, srt, vtt, plate, highlight, or none')
    if 'none' in words and len(words) > 1:
        problems.warn(line, 'captions: none is combined with other words; none wins')
    return set() if 'none' in words else words & set(CAPTION_WORDS)


def parse_music_defaults(value, line, problems, settings):
    """Default gain and fade for music lines from 'music: -18dB, fade 1.5'."""
    tokens = [token for token in re.split(r'[,\s]+', value) if token]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        gain = GAIN.match(token)
        if gain:
            settings['music_gain'] = float(gain.group(1))
            index += 1
        elif token.lower() == 'fade' and index + 1 < len(tokens) and seconds_value(tokens[index + 1]) is not None:
            settings['music_fade'] = seconds_value(tokens[index + 1])
            index += 2
        else:
            problems.error(line, f'music defaults: cannot read {token!r}', 'for example music: -18dB, fade 1.5')
            return


def parse_crop_value(token):
    """A crop setting: 'auto', or a (x, y) centre in fractions of the source frame; None when not a crop."""
    low = token.lower()
    if low == 'auto':
        return 'auto'
    if low in CROPS:
        return CROPS[low]
    match = re.fullmatch(r'(\d*\.?\d+),(\d*\.?\d+)', low)
    if match:
        x, y = float(match.group(1)), float(match.group(2))
        if 0 <= x <= 1 and 0 <= y <= 1:
            return (x, y)
    return None


def parse_settings(found, problems, root=None):
    """Validated settings from the front matter."""
    settings = default_settings()
    for key, (value, line) in found.items():
        if key not in FRONT_KEYS:
            close = difflib.get_close_matches(key, FRONT_KEYS, 1)
            problems.error(line, f'unknown setting {key!r}',
                           f'did you mean {close[0]}?' if close else 'settings: ' + ', '.join(FRONT_KEYS))
    for key in ('size', 'fps'):
        if key not in found:
            problems.error(1, f'the front matter needs {key}',
                           'add size: 1920x1080' if key == 'size' else 'add fps: 30')
    for key, (value, line) in found.items():
        if key in ('title',) + DIRECTION_KEYS:
            settings[key] = unquote(value)
        elif key == 'size':
            settings['size'] = parse_size(value, line, problems)
        elif key == 'fps':
            settings['fps'], settings['fps_text'] = parse_fps(value, line, problems)
        elif key == 'target':
            target = time_value(value.rstrip('s'))
            if target is None or target <= 0:
                problems.error(line, f'target must be seconds or m:ss, not {value!r}', 'for example target: 45')
            settings['target'] = target
        elif key == 'captions':
            settings['captions'] = parse_captions(value, line, problems)
        elif key == 'music':
            parse_music_defaults(value, line, problems, settings)
        elif key in ('pad', 'max_pause'):
            parse_seconds_setting(key, value, line, problems, settings)
        elif key == 'fit':
            if value.lower() not in ('cover', 'contain'):
                problems.error(line, f'fit must be cover or contain, not {value!r}')
            else:
                settings['fit'] = value.lower()
        elif key == 'crop':
            crop = parse_crop_value(value)
            if crop is None:
                problems.error(line, f'crop must be center, auto, left, right, top, bottom or x,y, not {value!r}')
            else:
                settings['crop'] = crop
        elif key == 'background':
            parse_background(value, line, problems, settings)
        elif key == 'font':
            parse_font(value, line, problems, settings, root)
        elif key == 'loudness':
            try:
                target = float(value)
                if not math.isfinite(target):
                    raise ValueError('non-finite target')
                settings['loudness'] = target
            except ValueError:
                problems.error(line, f'loudness must be a finite LUFS target, not {value!r}')
        elif key == 'bars':
            if value.lower() not in ('allow', 'allowed', 'yes', 'true', 'no', 'false'):
                problems.error(line, f'bars must be allow or no, not {value!r}')
            else:
                settings['bars'] = value.lower() in ('allow', 'allowed', 'yes', 'true')
    return settings


def parse_seconds_setting(key, value, line, problems, settings):
    """pad (0.05 to 2 s) or max_pause (0.1 s or more, or none)."""
    if key == 'max_pause' and value.lower() in ('none', 'off', 'keep', ''):
        settings['max_pause'] = None
        return
    number = seconds_value(value)
    low, high = (0.05, 2.0) if key == 'pad' else (0.1, 60.0)
    if number is None or not low <= number <= high:
        problems.error(line, f'{key} must be seconds between {low} and {high:g}, not {value!r}',
                       'for example pad: 0.2' if key == 'pad' else 'for example max_pause: 0.8, or none')
        return
    settings[key] = number


def parse_background(value, line, problems, settings):
    """A colour name or #hex Pillow understands."""
    from PIL import ImageColor
    try:
        red, green, blue = ImageColor.getrgb(unquote(value))[:3]
    except ValueError:
        problems.error(line, f'background is not a colour: {value!r}', 'for example background: black or #101418')
        return
    settings['background'] = f'#{red:02x}{green:02x}{blue:02x}'


def parse_font(value, line, problems, settings, root):
    """sans, mono or a font file."""
    choice = unquote(value)
    if choice.lower() in ('sans', 'mono'):
        settings['font'] = choice.lower()
        return
    path = Path(choice)
    if not path.is_absolute() and root is not None:
        path = Path(root) / path
    if not path.is_file():
        problems.error(line, f'font file not found: {choice}', 'use sans, mono, or a path to a .ttf, .otf or .woff2')
        return
    settings['font'] = str(path)


# ----------------------------------------------------------------------------------------------- body lines

def take_modifier(tokens, index):
    """Read one modifier at tokens[index]: (name, value, next index), or (None, None, index) if it is not one."""
    word = tokens[index]
    low = word.lower()
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    speed = SPEED.match(word)
    if speed:
        return 'speed', float(speed.group(1) or speed.group(2)), index + 1
    offset = OFFSET.match(word)
    if offset:
        return 'offset', float(offset.group(1)), index + 1
    gain = GAIN.match(word)
    if gain:
        return 'gain', float(gain.group(1)), index + 1
    if low in POSITIONS:
        return 'position', POSITIONS[low], index + 1
    if low in ('card', 'hold'):
        return low, True, index + 1
    if following is None:
        return (('sound', 0.0, index + 1) if low == 'sound' else (None, None, index))
    low_next = following.lower()
    if low == 'fit' and low_next in ('cover', 'contain'):
        return 'fit', low_next, index + 2
    if low == 'zoom' and seconds_value(following) is not None:
        return 'zoom', seconds_value(following), index + 2
    if low == 'crop' and parse_crop_value(following) is not None:
        return 'crop', parse_crop_value(following), index + 2
    if low in ('dissolve', 'dip') and seconds_value(following) is not None:
        return 'join', (low, seconds_value(following)), index + 2
    if low in ('tail', 'lead') and seconds_value(following) is not None:
        return low, seconds_value(following), index + 2
    if low == 'fade':
        third = tokens[index + 2] if index + 2 < len(tokens) else None
        if low_next in ('in', 'out') and seconds_value(third) is not None:
            return 'fade_' + low_next, seconds_value(third), index + 3
        if seconds_value(following) is not None:
            return 'fade', seconds_value(following), index + 2
    if low == 'sound':
        if ALIAS_SHAPE.match(following):
            # sound mic_01, or sound mic_01 -3dB: the line's sound from a lined-up source, at this gain.
            third = GAIN.match(tokens[index + 2]) if index + 2 < len(tokens) else None
            return 'sound_from', (following, float(third.group(1)) if third else 0.0), index + (3 if third else 2)
        sound_gain = GAIN.match(following)
        return ('sound', float(sound_gain.group(1)), index + 2) if sound_gain else ('sound', 0.0, index + 1)
    if low == 'at' and time_value(following) is not None:
        return 'at', time_value(following), index + 2
    if low in ('pin', 'behind') and LAYER_NAME.match(following):
        third = tokens[index + 2] if index + 2 < len(tokens) else None
        if low == 'pin' and third is not None and third.lower() == 'follow':
            return 'pin', (following, 'follow'), index + 3
        return low, ((following, None) if low == 'pin' else following), index + 2
    return None, None, index


def store_modifier(mods, name, value, allowed, kind, line, problems):
    """Add one modifier to a line's modifiers, refusing ones the line kind does not take."""
    if name not in allowed:
        label = {'join': 'dissolve/dip', 'fade_in': 'fade in', 'fade_out': 'fade out',
                 'sound_from': 'sound from another source', 'speed': 'speed'}.get(name, name)
        if kind == 'synced':
            problems.error(line, f'{label} does not apply to a ~ sync line: it shows the same moment as the line above '
                           'at the same speed, under that line\'s sound',
                           'remove it, or write the range of a separate cutaway')
            return
        problems.error(line, f'{label} does not apply to a {kind.replace("_over", "")} line',
                       'see references/paper-edit.md section 7 for which modifiers each line takes')
        return
    if name == 'sound_from':
        if 'sound_from' in mods or 'sound' in mods:
            problems.error(line, 'sound is given twice', 'keep one')
            return
        mods['sound_from'], mods['sound'] = value
        return
    if name in mods:
        problems.error(line, f'{name.replace("_", " ")} is given twice', 'keep one')
        return
    mods[name] = value


def parse_brace_mods(text, allowed, kind, line, problems, mods):
    """Modifiers written in braces at the end of a line: every token must be one. Commas separate modifiers, but a
    comma between two numbers belongs to a crop position (`{crop 0.66,0.5, dissolve 0.25}`)."""
    text = re.sub(r'(\d)\s*,\s*(?=[-.\d])', r'\1;', text)
    tokens = [token.replace(';', ',') for token in re.split(r'[,\s]+', text) if token]
    index = 0
    while index < len(tokens):
        name, value, after = take_modifier(tokens, index)
        if name is None:
            close = difflib.get_close_matches(tokens[index].lower(), MODIFIER_WORDS, 1)
            suggestion = ('use crop x,y, for example {crop 0.58,0.5}' if tokens[index].lower() == 'crop' else
                          f'did you mean {close[0]}?' if close else 'for example {crop auto, dissolve 0.25}')
            problems.error(line, f'cannot read modifier {tokens[index]!r} in braces', suggestion)
            return
        store_modifier(mods, name, value, allowed, kind, line, problems)
        index = after


def split_braces(text):
    """(text without a trailing {...} block, the block's content or None)."""
    match = re.search(r'\{([^{}]*)\}\s*$', text)
    if not match:
        return text, None
    return text[:match.start()].rstrip(), match.group(1)


def greedy_mods(tokens, allowed, kind, line, problems, mods):
    """Modifiers at the start of tokens (picture lines); the rest is a description. Returns the description."""
    index = 0
    while index < len(tokens):
        if tokens[index] == '|':
            return ' '.join(tokens[index + 1:])
        name, value, after = take_modifier(tokens, index)
        if kind == 'synced' and name in ('speed', 'sound', 'sound_from'):
            store_modifier(mods, name, value, allowed, kind, line, problems)
            index = after
            continue
        if name == 'sound_from' and name not in allowed:
            store_modifier(mods, name, value, allowed, kind, line, problems)
            index = after
            continue
        if name is None or name not in allowed:
            if tokens[index].lower() in ('zoom', 'crop', 'fit', 'dissolve', 'dip', 'fade') and name is None:
                problems.warn(line, f'"{" ".join(tokens[index:index + 2])}" is read as the description',
                              f'write the modifier with its value (for example {tokens[index].lower()} '
                              f'{"1.2" if tokens[index].lower() == "zoom" else "0.25"}), '
                              'or put | before a description that starts with it')
            return ' '.join(tokens[index:])
        store_modifier(mods, name, value, allowed, kind, line, problems)
        index = after
    return ''


def read_range(text, line, problems, usage):
    """(start, end, rest of the text) from a line body that starts with a range; None after an error."""
    match = RANGE_AT_START.match(text)
    if not match:
        first = text.split()[0] if text.split() else ''
        hint = 'use a dot for decimals' if re.search(r'\d,\d', first) else f'write it like: {usage}'
        problems.error(line, f'expected a source range like 1:02.50-1:07.10, found {first!r}' if first
                       else 'the line needs a source range like 1:02.50-1:07.10', hint)
        return None
    start, end = project.parse_time(match.group(1)), project.parse_time(match.group(2))
    if end <= start:
        problems.error(line, f'the range ends ({fmt(end)}) before it starts ({fmt(start)})',
                       'write the earlier time first')
        return None
    return start, end, text[match.end():].strip()


def new_entry(kind, line, section, over):
    """A parsed line with the fields every kind shares."""
    return {'kind': kind, 'line': line, 'section': section, 'over': over, 'mods': {}, 'text': '', 'alias': None,
            'start': None, 'end': None, 'bad': False}


def parse_spoken(body, line, section, problems):
    """A '>' line: alias, range, words to keep, optional {modifiers}."""
    usage = '> int_01 1:02.50-1:07.10 the words to keep'
    entry = new_entry('spoken', line, section, False)
    parts = body.split(None, 1)
    if len(parts) < 2:
        problems.error(line, 'a spoken line needs a source, a range and the words to keep', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    entry['alias'] = parts[0]
    if RANGE_AT_START.match(parts[0]):
        problems.error(line, 'the spoken line starts with a range; the source alias comes first',
                       f'write it like: {usage}')
        entry['bad'] = True
        return entry
    found = read_range(parts[1], line, problems, usage)
    if found is None:
        entry['bad'] = True
        return entry
    entry['start'], entry['end'], rest = found
    rest, braces = split_braces(rest)
    if braces is not None:
        parse_brace_mods(braces, ALLOWED['spoken'], 'spoken', line, problems, entry['mods'])
    if rest.count('~~') % 2:
        problems.error(line, 'a ~~strikethrough~~ is not closed', 'end the struck words with ~~')
        entry['bad'] = True
    entry['struck'] = [part.strip() for part in re.findall(r'~~(.*?)~~', rest)]
    entry['text'] = rest
    entry['words'] = re.sub(r'~~.*?~~', ' ', rest).split()
    if not any(normal_tokens(word) for word in entry['words']):
        problems.error(line, 'a spoken line needs the words to keep',
                       'copy the words from the transcript after the range; delete the ones to cut')
        entry['bad'] = True
    return entry


def tokens_with_quotes(text):
    """Tokens where "quoted strings" (straight or curly quotes) stay whole: [(is_quoted, text)]."""
    found = re.findall(r'"([^"]*)"|\u201c([^\u201d]*)\u201d|(\S+)', text)
    return [(bool(a or b) or (not c), a or b or c) for a, b, c in found]


def parse_title(body, line, section, over, problems):
    """title "Text" ["Second line"] SECONDS [position] [card] [+N | at T] [fade F]."""
    entry = new_entry('title', line, section, over)
    usage = 'title "Text" 2.0 lower'
    rest, braces = split_braces(body)
    tokens = tokens_with_quotes(rest)
    texts = []
    while tokens and tokens[0][0]:
        texts.append(tokens.pop(0)[1].strip())
    if not texts or not texts[0]:
        problems.error(line, 'a title needs its text in quotes', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    if len(texts) > 2:
        problems.error(line, 'a title takes at most two quoted lines (a main line and a smaller one)')
    plain = [token for _, token in tokens]
    if not plain or seconds_value(plain[0]) is None:
        problems.error(line, 'a title needs its duration in seconds after the text', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    entry['seconds'] = seconds_value(plain.pop(0))
    entry['texts'] = texts[:2]
    entry['text'] = ' / '.join(texts[:2])
    allowed = ALLOWED['title_over' if over else 'title']
    parse_brace_mods(' '.join(plain), allowed, 'title_over' if over else 'title', line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, allowed, 'title_over' if over else 'title', line, problems, entry['mods'])
    if entry['seconds'] <= 0:
        problems.error(line, 'a title must last more than 0 seconds')
        entry['bad'] = True
    card = entry['mods'].get('card')
    for name in ('join', 'fade_in', 'fade_out'):
        if name in entry['mods'] and not card:
            problems.error(line, f'{name.replace("_", " ")} applies to a title card only', 'add card, or remove it')
    for name in ('pin', 'behind'):
        if name in entry['mods'] and card:
            problems.error(line, f'a title card has no picture to {name} it to', f'remove card, or remove {name}')
            del entry['mods'][name]
    if card:
        entry['kind'] = 'card'
    return entry


def parse_still(tokens, line, section, over, problems, braces):
    """still ALIAS SECONDS (an image) or still ALIAS TIME SECONDS (a frame of a video), then modifiers."""
    entry = new_entry('still', line, section, over)
    usage = 'still still_03 3.0, or still broll_02 0:12.40 2.0 to freeze a video frame'
    if len(tokens) < 3:
        problems.error(line, 'a still needs a source and seconds', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    entry['alias'] = tokens[1]
    rest = tokens[2:]
    if len(rest) >= 2 and time_value(rest[0]) is not None and seconds_value(rest[1]) is not None:
        entry['freeze'] = time_value(rest[0])
        entry['seconds'] = seconds_value(rest[1])
        rest = rest[2:]
    elif seconds_value(rest[0]) is not None:
        entry['freeze'] = None
        entry['seconds'] = seconds_value(rest[0])
        rest = rest[1:]
    else:
        problems.error(line, f'expected seconds after the source, found {rest[0]!r}', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    kind = 'still_over' if over else 'still'
    entry['text'] = greedy_mods(rest, ALLOWED[kind], kind, line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED[kind], kind, line, problems, entry['mods'])
    if entry['seconds'] <= 0:
        problems.error(line, 'a still must last more than 0 seconds')
        entry['bad'] = True
    return entry


def parse_over(tokens, line, section, over, problems, braces):
    """over ALIAS [SECONDS], then +N and fade: a video with transparency (a lower third or title made in Cavalry or
    another engine) drawn over the picture of the line above at the film's own frame rate, or a PNG with
    transparency (a logo, a still graphic) drawn over it for its seconds."""
    entry = new_entry('over', line, section, over)
    usage = 'over gfx_01, or over gfx_01 4.0 +1.5 fade 0.2'
    if not over:
        problems.error(line, 'an over line draws over another line', f'indent it under that line: ~ {usage}')
        entry['bad'] = True
        return entry
    if len(tokens) < 2:
        problems.error(line, 'an over line needs a source', f'write it like: ~ {usage}')
        entry['bad'] = True
        return entry
    entry['alias'] = tokens[1]
    rest = tokens[2:]
    entry['seconds'] = None
    if rest and seconds_value(rest[0]) is not None:
        entry['seconds'] = seconds_value(rest[0])
        rest = rest[1:]
    entry['text'] = greedy_mods(rest, ALLOWED['over'], 'over', line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED['over'], 'over', line, problems, entry['mods'])
    if entry['seconds'] is not None and entry['seconds'] <= 0:
        problems.error(line, 'an over line must last more than 0 seconds')
        entry['bad'] = True
    return entry


def parse_music(body, line, section, over, problems, braces):
    """music ALIAS RANGE [GAIN] [fade F] [+N | at T] [description]."""
    entry = new_entry('music', line, section, over)
    usage = 'music music_01 0:00-0:45 -18dB'
    parts = body.split(None, 1)
    if len(parts) < 2:
        problems.error(line, 'a music line needs a source and a range', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    entry['alias'] = parts[0]
    found = read_range(parts[1], line, problems, usage)
    if found is None:
        entry['bad'] = True
        return entry
    entry['start'], entry['end'], rest = found
    entry['text'] = greedy_mods(rest.split(), ALLOWED['music'], 'music', line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED['music'], 'music', line, problems, entry['mods'])
    return entry


def parse_pause(tokens, line, section, problems, braces):
    """pause SECONDS [hold]."""
    entry = new_entry('pause', line, section, False)
    if len(tokens) < 2 or seconds_value(tokens[1]) is None or seconds_value(tokens[1]) <= 0:
        problems.error(line, 'a pause needs its length in seconds', 'write it like: pause 1.0, or pause 0.6 hold')
        entry['bad'] = True
        return entry
    entry['seconds'] = seconds_value(tokens[1])
    entry['text'] = greedy_mods(tokens[2:], ALLOWED['pause'], 'pause', line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED['pause'], 'pause', line, problems, entry['mods'])
    return entry


def parse_picture(body, line, section, over, problems, braces):
    """ALIAS RANGE [modifiers] [description]: a picture line, or a cutaway when over."""
    kind = 'cutaway' if over else 'picture'
    entry = new_entry(kind, line, section, over)
    usage = ('~ ' if over else '- ') + 'broll_04 0:12.00-0:14.10 description'
    parts = body.split(None, 1)
    entry['alias'] = parts[0]
    if len(parts) < 2:
        problems.error(line, f'a {kind} line needs a source range after the alias', f'write it like: {usage}')
        entry['bad'] = True
        return entry
    first = parts[1].split()[0].lower()
    if first == 'sync':
        return parse_synced(entry, parts[1].split()[1:], line, over, problems, braces)
    found = read_range(parts[1], line, problems, usage)
    if found is None:
        entry['bad'] = True
        return entry
    entry['start'], entry['end'], rest = found
    entry['text'] = greedy_mods(rest.split(), ALLOWED[kind], kind, line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED[kind], kind, line, problems, entry['mods'])
    return entry


def parse_synced(entry, tokens, line, over, problems, braces):
    """~ ALIAS sync [SECONDS] [+N] [modifiers] [description]: the same moment as the line above, from a lined-up source,
    so no times are retyped. Its source times come from the line above and the saved line-up when it is compiled."""
    entry['sync'] = True
    if not over:
        problems.error(line, 'sync shows the same moment as the line above, so it sits over a line',
                       f'indent it under that line: ~ {entry["alias"]} sync')
        entry['bad'] = True
        return entry
    entry['seconds'] = None
    if tokens and seconds_value(tokens[0]) is not None:
        entry['seconds'] = seconds_value(tokens[0])
        tokens = tokens[1:]
    entry['text'] = greedy_mods(tokens, ALLOWED['synced'], 'synced', line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED['synced'], 'synced', line, problems, entry['mods'])
    if entry['seconds'] is not None and entry['seconds'] <= 0:
        problems.error(line, 'a ~ sync line must last more than 0 seconds')
        entry['bad'] = True
    return entry


def parse_blur(tokens, line, section, over, problems, braces):
    """~ blur NAME [SECONDS] [+N]: blur the region a layer in spatial/ follows, over the line above."""
    entry = new_entry('blur', line, section, over)
    usage = '~ blur plate, or ~ blur face 2.0 +1.5'
    if not over:
        problems.error(line, 'a blur sits over a line', 'indent it under the line it covers: ~ blur NAME')
        entry['bad'] = True
        return entry
    if len(tokens) < 2 or not LAYER_NAME.match(tokens[1]):
        problems.error(line, 'a blur needs the name of a layer in spatial/ (lowercase letters, digits, hyphens)',
                       f'write it like: {usage}')
        entry['bad'] = True
        return entry
    entry['layer'] = tokens[1]
    rest = tokens[2:]
    entry['seconds'] = seconds_value(rest[0]) if rest else None
    if entry['seconds'] is not None:
        rest = rest[1:]
    extra = greedy_mods(rest, ALLOWED['blur'], 'blur', line, problems, entry['mods'])
    if braces is not None:
        parse_brace_mods(braces, ALLOWED['blur'], 'blur', line, problems, entry['mods'])
    if extra:
        problems.error(line, f'cannot read {extra!r} on a blur line', f'write it like: {usage}')
        entry['bad'] = True
    if entry['seconds'] is not None and entry['seconds'] <= 0:
        problems.error(line, 'a blur must last more than 0 seconds')
        entry['bad'] = True
    entry['text'] = 'blur ' + entry['layer']
    return entry


def parse_item(body, line, section, over, problems):
    """A '-' or '~' line's content: a keyword line or a picture line."""
    body, braces = split_braces(body) if not body.lower().startswith('title') else (body, None)
    tokens = body.split()
    head = tokens[0].lower()
    if head == 'title':
        return parse_title(body[len(tokens[0]):].strip(), line, section, over, problems)
    if head == 'still':
        return parse_still(tokens, line, section, over, problems, braces)
    if head == 'music':
        return parse_music(body[len(tokens[0]):].strip(), line, section, over, problems, braces)
    if head == 'blur':
        return parse_blur(tokens, line, section, over, problems, braces)
    if head == 'over':
        return parse_over(tokens, line, section, over, problems, braces)
    if head == 'pause':
        if over:
            problems.error(line, 'a pause cannot sit over a line', 'write it as its own line: - pause 1.0')
            entry = new_entry('pause', line, section, True)
            entry['bad'] = True
            return entry
        return parse_pause(tokens, line, section, problems, braces)
    return parse_picture(body, line, section, over, problems, braces)


def is_item_line(first, aliases):
    """Whether a '-' bullet is a film line (a keyword or an alias) rather than a note."""
    low = first.lower()
    return low in KEYWORDS or first in aliases or bool(ALIAS_SHAPE.match(first))


def parse_film(text, problems, aliases=(), root=None, notes=None):
    """Settings and entries from film.md text. Entries keep their physical line numbers (from 1). When `notes` is a
    list, each note to readers (any other plain line) is appended to it with its line number and section."""
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    found, body = split_front_matter(lines, problems)
    settings = parse_settings(found, problems, root)
    entries = []
    section = None
    fence = False
    comment = False
    for index in range(body, len(lines)):
        number = index + 1
        stripped = lines[index].strip()
        if stripped.startswith('```'):
            fence = not fence
            continue
        if fence:
            continue
        if comment:
            comment = '-->' not in stripped
            continue
        if stripped.startswith('<!--'):
            comment = '-->' not in stripped
            continue
        if not stripped:
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        if heading:
            if len(heading.group(1)) >= 2:
                section = heading.group(2).strip()
            continue
        if stripped.startswith('>'):
            entries.append(parse_spoken(stripped[1:].strip(), number, section, problems))
        elif stripped.startswith('- caption break before'):
            match = re.fullmatch(r'-\s+caption\s+break\s+before\s+([A-Za-z0-9_]+-w\d+)\s*', stripped)
            if not match:
                problems.error(number, 'caption break needs a source word ID',
                               'write: - caption break before int_01-w000123')
            else:
                settings.setdefault('caption_breaks', []).append({'word': match.group(1), 'line': number})
        elif re.match(r'^~(\s|$)', stripped):
            content = stripped[1:].strip()
            if not content:
                problems.error(number, 'an empty ~ line', 'write a cutaway like: ~ broll_04 0:12.00-0:14.10')
                continue
            entries.append(parse_item(content, number, section, True, problems))
        elif re.match(r'^-\s+\S', stripped) and is_item_line(stripped[1:].split()[0], aliases):
            entries.append(parse_item(stripped[1:].strip(), number, section, False, problems))
        elif notes is not None:
            notes.append({'line': number, 'section': section, 'text': stripped})
    return settings, entries


# ----------------------------------------------------------------------------------------------- the map

class SourceMap:
    """map/sources.json and each source's transcript."""

    def __init__(self, root):
        self.root = Path(root)
        data = project.load_json(self.root / 'map' / 'sources.json', None)
        if not isinstance(data, dict) or not isinstance(data.get('sources'), list):
            raise ValueError('map/sources.json is missing or unreadable; register the sources first (map.py add)')
        self.sources = {source['alias']: source for source in data['sources'] if source.get('alias')}
        self.cache = {}
        self.geometry_cache = {}
        self.review_cache = {}
        self.shots_cache = {}
        self.stale_cache = {}
        self.media_cache = {}
        self.media_stats = {}
        self.picture_ends = {}
        self.verify_media = False
        self.saved_lineup = None
        self.lineup_used = set()

    def lineup(self):
        """The saved line-up (lineup.py): loaded for a film that uses one, so a one-source film never reads it."""
        if self.saved_lineup is None:
            self.saved_lineup = load_sibling('lineup').Lineup(self.root, self.sources)
        return self.saved_lineup

    def lineup_problem(self, first, second):
        """Why two sources cannot be mapped onto each other ('' when they can); both are recorded as used."""
        reason = self.lineup().usable(first, second)
        if not reason:
            self.lineup_used.update((first, second))
        return reason

    def path(self, alias):
        """The source file's path."""
        path = Path(self.sources[alias]['path'])
        return path if path.is_absolute() else self.root / path

    def duration(self, alias):
        """The source's duration in seconds (0 when unknown)."""
        return float(self.sources[alias].get('duration_s') or 0)

    def stream_ends(self, alias, name):
        """The map's record of where one stream ends ({'header', 'decoded', 'usable'}), {} for a map without one."""
        ends = self.sources[alias].get('ends')
        row = ends.get(name) if isinstance(ends, dict) else None
        return row if isinstance(row, dict) else {}

    def short_note(self, alias, name):
        """What to say after a stream's end when it decodes short of its header, else nothing."""
        row = self.stream_ends(alias, name)
        if row.get('header') and row.get('usable') and row['usable'] < row['header']:
            return f" (decoded; the file's header says {fmt(row['header'])})"
        return ''

    def picture_end(self, alias):
        """Where the source's picture ends: the map's decoded end; for a map made before it recorded one, the video
        stream's own header (a source's duration is its longest stream's, and sound can run on past the picture); the
        duration when neither can be read."""
        usable = self.stream_ends(alias, 'picture').get('usable')
        if usable:
            return float(usable)
        if alias not in self.picture_ends:
            self.picture_ends[alias] = self.duration(alias)
            ffprobe = find_tool('ffprobe')
            if ffprobe and self.has_video(alias) and self.has_audio(alias) and self.path(alias).is_file():
                result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
                                         str(self.path(alias))], capture_output=True, text=True, encoding='utf-8',
                                        errors='replace')
                try:
                    facts = json.loads(result.stdout)
                    video = next(row for row in facts['streams'] if row.get('codec_type') == 'video'
                                 and not (row.get('disposition') or {}).get('attached_pic'))
                    self.picture_ends[alias] = load_sibling('transcribe').presentation_duration(
                        {'format': facts.get('format', {}), 'streams': [video]})
                except (KeyError, StopIteration, TypeError, ValueError):
                    pass
        return self.picture_ends[alias]

    def sound_end(self, alias):
        """Where the source's sound ends: the map's decoded end, else the source's duration."""
        return float(self.stream_ends(alias, 'sound').get('usable') or self.duration(alias))

    def is_image(self, alias):
        """Whether the source is a still image."""
        source = self.sources[alias]
        return source.get('role') == 'still' or Path(source['path']).suffix.lower() in IMAGE_SUFFIXES

    def has_video(self, alias):
        """Whether the source has moving picture."""
        return bool(self.sources[alias].get('video')) and not self.is_image(alias)

    def has_audio(self, alias):
        """Whether the source has sound."""
        return bool(self.sources[alias].get('audio'))

    def size(self, alias):
        """Displayed square-pixel dimensions, including for maps made by older versions."""
        video = self.sources[alias].get('video') or {}
        if video and not video.get('geometry_version') and alias not in self.geometry_cache:
            ffprobe = find_tool('ffprobe')
            if ffprobe and self.path(alias).is_file():
                command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams',
                           '-of', 'json', str(self.path(alias))]
                result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
                if result.returncode:
                    raise ValueError(f'cannot inspect display geometry for {alias}: {result.stderr[-300:]}')
                streams = json.loads(result.stdout).get('streams') or []
                if not streams:
                    raise ValueError(f'cannot inspect display geometry for {alias}: no video stream')
                self.geometry_cache[alias] = load_sibling('render_common').display_geometry(streams[0])
        video = self.geometry_cache.get(alias, video)
        if video.get('width') and video.get('height'):
            return int(video['width']), int(video['height'])
        return None

    def fps(self, alias):
        """The source frame rate as a fraction, or None."""
        video = self.sources[alias].get('video') or {}
        try:
            rate = Fraction(str(video.get('fps')))
        except (ValueError, ZeroDivisionError):
            return None
        return rate if rate > 0 else None

    def words(self, alias):
        """The transcript words in the transcript's order (each with its index), or None when there is none."""
        if alias not in self.cache:
            data = project.load_json(self.root / 'map' / alias / 'words.json', None)
            words = None
            if isinstance(data, dict) and isinstance(data.get('words'), list):
                rows = [word for word in data['words'] if str(word.get('text', '')).strip()
                        and isinstance(word.get('start'), (int, float)) and isinstance(word.get('end'), (int, float))]
                words = [dict(word, index=index) for index, word in enumerate(rows)]
            self.cache[alias] = words
        return self.cache[alias]

    def stale_transcript(self, alias):
        """Why the source's transcript does not fit the source's file as it is now, or '' when it does: made from other
        media or another sound stream than the map records, or the file itself changed since it was mapped (its byte
        count on every check; its SHA-256 too when the map verifies media, as a render does)."""
        if alias not in self.stale_cache:
            data = project.load_json(self.root / 'map' / alias / 'words.json', None)
            source = self.sources.get(alias) or {}
            state, reason = project.transcript_state(source, data)
            if state != 'stale':
                reason = self.media_change(alias, source)
            self.stale_cache[alias] = reason if state == 'stale' or reason else ''
        return self.stale_cache[alias]

    def media_change(self, alias, source):
        """How the source's file differs from the map's record of it ('' when it does not, or cannot be read)."""
        path = self.path(alias)
        if not path.is_file():
            return ''
        recorded = source.get('bytes')
        stat = path.stat()
        size = stat.st_size
        # Kept so a render can confirm, before it publishes, that the file it checked is the file it read.
        self.media_stats[alias] = (stat.st_size, stat.st_mtime_ns)
        if isinstance(recorded, int) and recorded > 0 and size != recorded:
            return f'the source file changed since it was mapped ({size} bytes, the map has {recorded})'
        if self.verify_media and isinstance(source.get('sha256'), str) and recorded:
            if sha256_file(path) != source['sha256']:
                return 'the source file changed since it was mapped (its SHA-256 differs)'
        return ''

    def media_problem(self, alias):
        """Why a source's file cannot be used as the map measured it ('' when it can): changed since it was mapped,
        or, when the map verifies media (a render), missing."""
        if alias not in self.media_cache:
            path = self.path(alias)
            if self.verify_media and not path.is_file():
                self.media_cache[alias] = f'the source file is missing ({path})'
            else:
                self.media_cache[alias] = self.media_change(alias, self.sources.get(alias) or {})
        return self.media_cache[alias]

    def shot_starts(self, alias):
        """Source times where the source's own shots change (map/<alias>/shots.json); [] when not mapped."""
        if alias not in self.shots_cache:
            data = project.load_json(self.root / 'map' / alias / 'shots.json', None)
            rows = data.get('shots') if isinstance(data, dict) else None
            starts = [float(row['start']) for row in rows or [] if isinstance(row, dict)
                      and isinstance(row.get('start'), (int, float)) and row['start'] > 0]
            self.shots_cache[alias] = sorted(starts)
        return self.shots_cache[alias]

    def transcript_review(self, alias):
        """Recompute prompts from the current words so manual corrections cannot leave stale findings."""
        if alias not in self.review_cache:
            audio = project.load_json(self.root / 'map' / alias / 'audio.json', {}) or {}
            self.review_cache[alias] = load_sibling('transcribe').transcript_review(self.words(alias) or [], audio)
        return self.review_cache[alias]


class Envelope:
    """The level of a stretch of source audio in dB, every HOP seconds, with a quiet threshold for pauses."""

    def __init__(self, samples, rate, origin):
        import numpy as np
        hop = max(1, int(round(rate * HOP)))
        count = len(samples) // hop
        power = np.zeros(count, np.float64)
        block = 2000
        for first in range(0, count, block):
            # Blocks of 10 s keep memory near the 16-bit samples themselves, even for a long line.
            chunk = samples[first * hop:(first + block) * hop].astype(np.float32) / 32768.0
            power[first:first + len(chunk) // hop] = (chunk[:len(chunk) // hop * hop].reshape(-1, hop) ** 2).mean(1)
        width = max(1, int(round(WINDOW / HOP)))
        smooth = np.convolve(power, np.ones(width) / width, mode='same') if count else power
        self.db = 10 * np.log10(smooth + 1e-10)
        self.times = origin + (np.arange(count) + 0.5) * hop / rate
        if len(self.db) < 10:
            self.reliable = False
            self.threshold = -60.0
            return
        floor = max(float(np.percentile(self.db, 5)), -100.0)
        peak = float(np.percentile(self.db, 95))
        self.reliable = peak - floor >= 15
        self.threshold = min(max(floor + 9, peak - 45), peak - 15)

    def on_clock(self, shift):
        """The same measurements with its times read on another source's clock, `shift` seconds earlier than its own."""
        moved = object.__new__(Envelope)
        moved.__dict__.update(self.__dict__)
        moved.times = self.times - shift
        return moved

    def index(self, moment):
        """The envelope step nearest a time."""
        import numpy as np
        return int(np.clip(round((moment - self.times[0]) / HOP), 0, len(self.times) - 1))

    def quiet_at(self, moment):
        """Whether the audio is quiet around a moment (within 10 ms)."""
        centre = self.index(moment)
        return bool((self.db[max(0, centre - 2):centre + 3] < self.threshold).all())

    def quiet_runs(self, low, high):
        """Stretches of at least MIN_QUIET seconds below the threshold between two times: [(start, end)]."""
        first, last = self.index(low), self.index(high)
        runs = []
        begin = None
        for step in range(first, last + 2):
            quiet = step <= last and self.db[step] < self.threshold
            if quiet and begin is None:
                begin = step
            elif not quiet and begin is not None:
                start = max(low, self.times[begin] - HOP / 2)
                end = min(high, self.times[step - 1] + HOP / 2)
                if end - start >= MIN_QUIET:
                    runs.append((start, end))
                begin = None
        return runs

    def dip_near(self, moment, low, high):
        """The quietest moment between two times, penalising distance from `moment` (DIP_PENALTY dB per second)."""
        first, last = self.index(low), self.index(high)
        if last <= first:
            return moment
        times = self.times[first:last + 1]
        score = self.db[first:last + 1] + DIP_PENALTY * abs(times - moment)
        return float(times[int(score.argmin())])


class Envelopes:
    """Source audio levels, decoded on demand with FFmpeg."""

    def __init__(self, source_map, ffmpeg):
        self.map = source_map
        self.ffmpeg = ffmpeg
        self.cache = {}

    def get(self, alias, start, end):
        """An Envelope for a stretch of a source's audio, or None when it cannot be decoded."""
        if not self.ffmpeg or not self.map.has_audio(alias):
            return None
        start = max(0.0, start)
        if self.map.duration(alias):
            end = min(end, self.map.duration(alias))
        key = (alias, round(start, 3), round(end, 3))
        if key not in self.cache:
            self.cache[key] = self.decode(alias, start, end)
        return self.cache[key]

    def from_source(self, alias, start, end, shift):
        """The level of another source's sound over a stretch of a line's own clock, `shift` seconds later on its own,
        with its times on the line's clock: where a line's cuts are measured when its sound comes from there."""
        low = max(0.0, start + shift)
        high = end + shift
        if self.map.duration(alias):
            high = min(high, self.map.duration(alias))
        if high <= low:
            return None
        found = self.get(alias, low, high)
        return found.on_clock(shift) if found is not None and len(found.times) else found

    def decode(self, alias, start, end):
        """Decode mono 16 kHz audio and measure it."""
        import numpy as np
        rate = 8000
        try:
            transcribe = load_sibling('transcribe')
            stream = (self.map.sources[alias].get('audio') or {}).get('index')
            command = transcribe.audio_window_command(self.map.path(alias), stream, start, end, rate=rate,
                                                       sample_format='s16le', ffmpeg=self.ffmpeg)
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            return None
        if result.returncode or not result.stdout:
            return None
        return Envelope(np.frombuffer(result.stdout, dtype=np.int16), rate, start)


# ----------------------------------------------------------------------------------------------- words

def normal_tokens(text):
    """The comparable pieces of a word: lower case, apostrophes dropped, split at other punctuation."""
    text = unicodedata.normalize('NFKC', str(text)).lower()
    text = re.sub("['`\u2018\u2019\u02bc]", '', text)
    return re.findall(r'[^\W_]+', text)


def range_words(words, start, end):
    """Indices of transcript words whose middle lies inside a range."""
    return [word['index'] for word in words if start - 1e-6 <= (word['start'] + word['end']) / 2 <= end + 1e-6]


def best_alignment(paper, transcript):
    """Match paper tokens in order to transcript tokens with the fewest breaks; a list of transcript positions."""
    count = len(transcript)
    infinite = float('inf')
    cost = [0 if paper[0] == token else infinite for token in transcript]
    back = []
    for step in range(1, len(paper)):
        row = [infinite] * count
        link = [-1] * count
        best, best_at = infinite, -1
        for position in range(count):
            if position >= 2 and cost[position - 2] < best:
                best, best_at = cost[position - 2], position - 2
            if paper[step] != transcript[position]:
                continue
            adjacent = cost[position - 1] if position >= 1 else infinite
            if adjacent <= best + 1:
                row[position], link[position] = adjacent, position - 1
            else:
                row[position], link[position] = best + 1, best_at
        back.append(link)
        cost = row
    final = min(range(count), key=lambda position: (cost[position], position)) if count else -1
    if final < 0 or cost[final] == infinite:
        return None
    path = [final]
    for link in reversed(back):
        path.append(link[path[-1]])
    return list(reversed(path))


def match_spoken(entry, words, problems):
    """Kept transcript word indices for a spoken line, or None after reporting what did not match."""
    indices = range_words(words, entry['start'], entry['end'])
    alias = entry['alias']
    if not indices:
        problems.error(entry['line'], f'no transcript words in {alias} between {fmt(entry["start"])} and '
                       f'{fmt(entry["end"])}', nearby_hint(words, entry['start'], entry['end']))
        return None
    transcript, owner = [], []
    for index in indices:
        for token in normal_tokens(words[index]['text']):
            transcript.append(token)
            owner.append(index)
    paper, origin = [], []
    for number, word in enumerate(entry['words']):
        for token in normal_tokens(word):
            paper.append(token)
            origin.append(number)
    path = best_alignment(paper, transcript) if paper and transcript else None
    if path is not None:
        return sorted(set(owner[position] for position in path))
    report_unmatched(entry, words, indices, paper, origin, transcript, owner, problems)
    return None


def nearby_hint(words, start, end):
    """A suggestion naming the transcript words nearest an empty range."""
    before = [word for word in words if word['end'] <= start]
    after = [word for word in words if word['start'] >= end]
    parts = []
    if before:
        parts.append(f'"{before[-1]["text"]}" ends at {fmt(before[-1]["end"])}')
    if after:
        parts.append(f'"{after[0]["text"]}" starts at {fmt(after[0]["start"])}')
    return ('nearest words: ' + '; '.join(parts)) if parts else 'the transcript is empty'


def report_unmatched(entry, words, indices, paper, origin, transcript, owner, problems):
    """Report paper words not found in the range, with the nearest transcript words and a better range."""
    alias, line = entry['alias'], entry['line']
    matcher = difflib.SequenceMatcher(None, paper, transcript, autojunk=False)
    matched = set()
    for block in matcher.get_matching_blocks():
        matched.update(range(block.a, block.a + block.size))
    missing = sorted(set(origin[position] for position in range(len(paper)) if position not in matched))
    if not missing:
        problems.error(line, f'the words are in a different order from {alias}\'s transcript',
                       'a line plays its source in order; split it into two lines to reorder')
        return
    vocabulary = sorted(set(transcript))
    for number in missing:
        word = entry['words'][number]
        tokens = normal_tokens(word)
        if tokens and all(token in vocabulary for token in tokens):
            index = owner[transcript.index(tokens[0])]
            problems.error(line, f'"{word}" is in the transcript of {alias} here ({fmt(words[index]["start"])}) but '
                           'out of order with the words around it', 'a line plays its source in order: check the word '
                           'order against the transcript, or split the line in two to reorder')
            continue
        outside = find_outside(words, indices, tokens, entry['start'], entry['end'])
        if outside is not None:
            found, start, end = outside
            problems.error(line, f'"{word}" is not in {alias}\'s transcript between {fmt(entry["start"])} and '
                           f'{fmt(entry["end"])}', f'"{found["text"]}" is at {fmt(found["start"])}, outside the '
                           f'range; widen the range to {fmt(start)}-{fmt(end)}')
            continue
        close = difflib.get_close_matches(tokens[0] if tokens else word.lower(), vocabulary, 3, 0.5)
        if close:
            spots = []
            for token in close:
                index = owner[transcript.index(token)]
                spots.append(f'"{words[index]["text"]}" at {fmt(words[index]["start"])}')
            hint = 'the transcript has ' + ', '.join(spots) + '; use the transcript\'s words'
        else:
            context = ' '.join(words[index]['text'] for index in indices[:12])
            hint = f'the transcript there reads: "{context}{" ..." if len(indices) > 12 else ""}"'
        problems.error(line, f'"{word}" is not in {alias}\'s transcript between {fmt(entry["start"])} and '
                       f'{fmt(entry["end"])}', hint)


def find_outside(words, indices, tokens, start, end):
    """A transcript word matching tokens within 20 s outside a range: (word, widened start, widened end)."""
    if not tokens:
        return None
    inside = set(indices)
    candidates = [word for word in words if word['index'] not in inside and normal_tokens(word['text']) == tokens
                  and start - 20 <= word['start'] <= end + 20]
    if not candidates:
        return None
    found = min(candidates, key=lambda word: min(abs(word['start'] - start), abs(word['end'] - end)))
    return found, min(start, found['start'] - 0.2), max(end, found['end'] + 0.2)


# ----------------------------------------------------------------------------------------------- cut placement

def transcript_cut(low, high, side, handle, pad):
    """A cut placed from transcript times alone: keep a handle and at most pad seconds of the pause."""
    if high <= low:
        return (low + high) / 2
    keep = min(max((high - low) / 2, min(handle, (high - low) * 0.8)), pad)
    return low + keep if side == 'after' else high - keep


def place_cut(envelope, gap, window, side, handle, pad):
    """A cut between a kept word and a removed one: (time, tight).

    side 'after' cuts after a kept word (removed material follows); 'before' cuts before a kept word. gap is the
    pause by the transcript's times; window is how far the search may reach. In order of preference the cut goes:
    in a clear pause (a quiet stretch of CLEAR_PAUSE seconds or more) overlapping the transcript's pause or within
    NEAR seconds of it; in a shorter quiet stretch within DIP_REACH of the transcript's word boundary (tight: it may
    be a stop consonant); or at the quietest moment within DIP_REACH of that boundary (tight). In a pause it keeps a
    handle after the kept word and at most pad seconds of the pause."""
    low, high = gap
    if envelope is None or not envelope.reliable:
        return transcript_cut(low, high, side, handle, pad), high - low < handle
    runs = envelope.quiet_runs(*window)
    boundary = (low + high) / 2

    def distance(run):
        """How far a quiet stretch is from the transcript's boundary."""
        return 0.0 if run[0] <= boundary <= run[1] else min(abs(run[0] - boundary), abs(run[1] - boundary))

    def best(pool):
        """The longest stretch, then the nearest the boundary, then the nearest the kept word."""
        tie = (lambda run: -run[0]) if side == 'after' else (lambda run: run[1])
        return max(pool, key=lambda run: (round(run[1] - run[0], 2), -round(distance(run), 2), tie(run)))

    def inside_run(run):
        """A cut point inside a quiet stretch."""
        start, end = run
        length = end - start
        keep = min(max(length / 2, min(handle, length * 0.8)), pad)
        return start + keep if side == 'after' else end - keep

    clear = [run for run in runs if run[1] - run[0] >= CLEAR_PAUSE and run[1] > low - NEAR and run[0] < high + NEAR]
    if clear:
        return inside_run(best(clear)), False
    short = [run for run in runs if distance(run) <= DIP_REACH]
    if short:
        return inside_run(best(short)), True
    reach = (max(window[0], boundary - DIP_REACH), min(window[1], boundary + DIP_REACH))
    return envelope.dip_near(boundary, *reach), True


def edge_settings(word):
    """(handle, slack into a kept word, slack into a removed word) for a word's measured or estimated edges."""
    estimated = 1 if word.get('estimated') else 0
    return HANDLE[estimated], SLACK_KEPT[estimated], SLACK_REMOVED[estimated]


def cut_after(words, kept, envelope, pad):
    """A cut after kept word index `kept` (the next transcript word is removed or far away): (time, tight)."""
    word = words[kept]
    handle, slack_kept, _ = edge_settings(word)
    following = words[kept + 1] if kept + 1 < len(words) else None
    high = following['start'] if following else word['end'] + 2.0
    slack_removed = edge_settings(following)[2] if following else 0.0
    return place_cut(envelope, (word['end'], high), (word['end'] - slack_kept, high + slack_removed), 'after',
                     handle, pad)


def cut_before(words, kept, envelope, pad):
    """A cut before kept word index `kept` (the previous transcript word is removed or far away): (time, tight)."""
    word = words[kept]
    handle, slack_kept, _ = edge_settings(word)
    previous = words[kept - 1] if kept > 0 else None
    low = previous['end'] if previous else max(0.0, word['start'] - 2.0)
    slack_removed = edge_settings(previous)[2] if previous else 0.0
    return place_cut(envelope, (low, word['start']), (low - slack_removed, word['start'] + slack_kept), 'before',
                     handle, pad)


def line_edge(words, kept, written, side, envelope, pad):
    """A line's in point (side 'before') or out point (side 'after'): the written range edge when it is quiet and
    clear of neighbouring words; when it is clear but not quiet, the nearest quiet point within EDGE_REACH of it, or
    else the written edge itself, listed as tight; when it falls inside a word, the nearest quiet point outside the
    kept word. (time, tight, moved).

    A clear edge used to be moved like a cut between words, to the middle of the gap to the next transcript word:
    with music under the dialogue that gap ran to seconds, and an edge moved up to 7.3 s into unrelated shots."""
    word = words[kept]
    handle = edge_settings(word)[0]
    previous = words[kept - 1] if kept > 0 else None
    following = words[kept + 1] if kept + 1 < len(words) else None
    if side == 'before':
        clear = written <= word['start'] - handle and (previous is None or written >= previous['end'])
        low = max(written - EDGE_REACH, previous['end'] if previous else 0.0)
        high = min(written + EDGE_REACH, word['start'] - handle)
    else:
        clear = written >= word['end'] + handle and (following is None or written <= following['start'])
        low = max(written - EDGE_REACH, word['end'] + handle)
        high = min(written + EDGE_REACH, following['start'] if following else written + EDGE_REACH)
    quiet = envelope is None or not envelope.reliable or envelope.quiet_at(written)
    if clear and quiet:
        return written, False, False
    if clear:
        runs = envelope.quiet_runs(low, high) if high > low else []
        if runs:
            point = min((min(max(written, start), end) for start, end in runs), key=lambda t: abs(t - written))
            return point, False, abs(point - written) > 1e-6
        return written, True, False
    moment, tight = (cut_before if side == 'before' else cut_after)(words, kept, envelope, pad)
    return moment, tight, True


def spoken_runs(entry, words, kept, envelope, settings, problems):
    """Contiguous pieces of a spoken line: [{'in', 'out', 'words', 'tight'}] in source time."""
    indices = range_words(words, entry['start'], entry['end'])
    kept_set = set(kept)
    groups = []
    for index in indices:
        if index in kept_set:
            if groups and groups[-1][-1] == index - 1:
                groups[-1].append(index)
            else:
                groups.append([index])
    pause_limit = settings.get('max_pause')
    measured_splits = {}
    if pause_limit:
        split = []
        for group in groups:
            current = [group[0]]
            for index in group[1:]:
                before, after = words[index - 1], words[index]
                gap = after['start'] - before['end']
                should_split = False
                if envelope is not None and envelope.reliable:
                    boundary = (before['end'] + after['start']) / 2
                    spans = envelope.quiet_runs(before['start'], after['end'])
                    central = [run for run in spans if run[0] <= boundary <= run[1]
                               and run[1] - run[0] > pause_limit + .01]
                    if central:
                        quiet = max(central, key=lambda run: run[1] - run[0])
                        removal = max(quiet[1] - quiet[0] - pause_limit, gap - pause_limit)
                        if removal > .01 and removal <= quiet[1] - quiet[0]:
                            left = max(quiet[0], min(quiet[1] - removal, boundary - removal / 2))
                            measured_splits[index] = (left, left + removal)
                            should_split = True
                if not should_split and gap > pause_limit and envelope is not None and envelope.reliable:
                    candidates = envelope.quiet_runs(before['end'], after['start'])
                    removal = gap - pause_limit
                    if candidates and removal > .01:
                        single = [run for run in candidates if run[1] - run[0] >= removal]
                        if single:
                            quiet = max(single, key=lambda run: run[1] - run[0])
                            left = max(quiet[0], min(quiet[1] - removal, before['end'] + pause_limit / 2))
                            right = left + removal
                        else:
                            first, last = candidates[0], candidates[-1]
                            minimum_kept = first[0] - before['end'] + after['start'] - last[1]
                            if minimum_kept <= pause_limit:
                                low = max(first[0], last[0] - removal)
                                high = min(first[1], last[1] - removal)
                                if low <= high:
                                    left = max(low, min(high, before['end'] + pause_limit / 2))
                                    right = left + removal
                                else:
                                    left, right = first[0], last[1]
                            else:
                                left = right = None
                        if left is not None and right - left > .01:
                            for earlier, later in zip(candidates, candidates[1:]):
                                if earlier[1] < right and later[0] > left:
                                    problems.warn(entry['line'], f'max_pause removes sound near '
                                                  f'{fmt(max(left, earlier[1]))}; listen to the cut')
                                    break
                            measured_splits[index] = (left, right)
                            should_split = True
                    if not should_split:
                        problems.warn(entry['line'], f'max_pause could not be met near {fmt(before["end"])}',
                                      'sound fills the pause; listen and adjust the edit')
                elif not should_split and gap > pause_limit and (envelope is None or not envelope.reliable):
                    should_split = True
                if should_split:
                    split.append(current)
                    current = []
                current.append(index)
            split.append(current)
        groups = split
        if envelope is None or not envelope.reliable:
            problems.warn(entry['line'], 'max_pause could not be measured in the audio',
                          'the transcript-based fallback is approximate; listen to the pauses')
    pad = settings['pad']
    runs = []
    for number, group in enumerate(groups):
        first, last = group[0], group[-1]
        joined_before = number > 0 and groups[number - 1][-1] == first - 1
        joined_after = number + 1 < len(groups) and groups[number + 1][0] == last + 1
        if number == 0:
            start, tight_in, _ = line_edge(words, first, entry['start'], 'before', envelope, pad)
        elif joined_before and first in measured_splits:
            start = measured_splits[first][1]
            tight_in = False
        else:
            start, tight_in = cut_before(words, first, envelope, pause_limit / 2 if joined_before else pad)
        if number == len(groups) - 1:
            end, tight_out, _ = line_edge(words, last, entry['end'], 'after', envelope, pad)
        elif joined_after and last + 1 in measured_splits:
            end = measured_splits[last + 1][0]
            tight_out = False
        else:
            end, tight_out = cut_after(words, last, envelope, pause_limit / 2 if joined_after else pad)
        runs.append({'in': max(0.0, start), 'out': end, 'words': group, 'tight': [tight_in, tight_out]})
    return merge_crossed_runs(runs, words, entry, problems)


def merge_crossed_runs(runs, words, entry, problems):
    """Join neighbouring pieces whose cut points cross (no room to remove the words between them)."""
    merged = []
    for run in runs:
        if merged and run['in'] <= merged[-1]['out'] + 0.01:
            previous = merged[-1]
            between = [words[index]['text'] for index in range(previous['words'][-1] + 1, run['words'][0])]
            if between:
                problems.warn(entry['line'], f'could not cut "{" ".join(between)}" cleanly: no pause around it',
                              'it stays in; cut more words around it, or listen and adjust the range')
            previous['out'] = run['out']
            previous['words'] = list(range(previous['words'][0], run['words'][-1] + 1))
            previous['tight'][1] = run['tight'][1]
            continue
        merged.append(run)
    return merged


# ----------------------------------------------------------------------------------------------- compile

def validate_entry(entry, source_map, problems):
    """Check an entry's alias, range and kind against the map; mark it bad on an error."""
    if entry['bad'] or entry['kind'] in ('title', 'card', 'pause', 'blur'):
        return
    alias, line = entry['alias'], entry['line']
    if alias not in source_map.sources:
        close = difflib.get_close_matches(alias, list(source_map.sources), 3, 0.5)
        problems.error(line, f'unknown source alias {alias}', ('known aliases near it: ' + ', '.join(close)) if close
                       else 'known aliases: ' + ', '.join(sorted(source_map.sources)[:12]))
        entry['bad'] = True
        return
    kind = entry['kind']
    if entry.get('sync'):
        validate_synced(entry, source_map, problems)
        return
    if 'sound_from' in entry['mods'] and not validate_sound_from(entry, source_map, problems):
        entry['bad'] = True
        return
    # Spoken lines report a changed file through their transcript (stale_transcript); every other use of a source
    # (picture, cutaway, still, music) needs the file the map measured too: its duration, shots and geometry.
    # A changed file still compiles, so the lines over it (a layer made from the old file) report their own problems
    # in the same check; a missing file cannot.
    problem = source_map.media_problem(alias) if kind != 'spoken' else ''
    if problem:
        problems.error(line, f'{alias}: {problem}',
                       'restore the file, or map it again (map.py run PROJECT) so it is measured as it is now')
        if problem.startswith('the source file is missing'):
            entry['bad'] = True
            return
    if kind == 'still':
        validate_still(entry, source_map, problems)
        return
    if kind == 'over':
        validate_over(entry, source_map, problems)
        return
    duration = source_map.duration(alias)
    range_past_end(entry, source_map, problems)
    if duration and entry['start'] >= duration:
        entry['bad'] = True
    if kind in ('picture', 'cutaway') and not source_map.has_video(alias):
        what = 'is an image; use - still ' + alias + ' 3.0' if source_map.is_image(alias) else 'has no picture'
        problems.error(line, f'{alias} {what.split(";")[0]}', what.split('; ')[1] if ';' in what else
                       'use it in a music line or under a line with ~ music, or as a spoken line covered by cutaways')
        entry['bad'] = True
    if kind in ('music', 'spoken') and not source_map.has_audio(alias) and 'sound_from' not in entry['mods']:
        problems.error(line, f'{alias} has no sound', 'use a picture line for a silent source')
        entry['bad'] = True
    if 'sound' in entry['mods'] and kind != 'spoken' and not source_map.has_audio(alias) \
            and 'sound_from' not in entry['mods']:
        problems.error(line, f'{alias} has no sound to use', 'remove sound')
        entry['bad'] = True
    if kind == 'spoken' and source_map.words(alias) is None:
        problems.error(line, f'{alias} has no transcript (map/{alias}/words.json)',
                       f'map it with map.py run, or use a picture line with its sound: - {alias} '
                       f'{fmt(entry["start"])}-{fmt(entry["end"])} sound')
        entry['bad'] = True
    elif kind == 'spoken' and source_map.stale_transcript(alias):
        problems.error(line, f'{alias}: {source_map.stale_transcript(alias)}, so its word times may not fit the file',
                       f'map it again (map.py run PROJECT), then transcribe it again (map.py run PROJECT '
                       f'--retranscribe {alias}) or, after checking it, confirm it (map.py confirm-words PROJECT '
                       f'{alias} --note TEXT)')
        entry['bad'] = True


def validate_synced(entry, source_map, problems):
    """A ~ ALIAS sync line: a registered source with picture, unchanged since it was mapped. Its line-up and what it
    covers are checked when it is compiled, since they depend on the line above."""
    alias, line = entry['alias'], entry['line']
    problem = source_map.media_problem(alias)
    if problem:
        problems.error(line, f'{alias}: {problem}',
                       'restore the file, or map it again (map.py run PROJECT) and line it up again (map.py sync)')
        entry['bad'] = True
    elif not source_map.has_video(alias):
        problems.error(line, f'{alias} has no picture to show', 'name a lined-up camera; {sound ' + alias + '} on the '
                       'line above takes its sound')
        entry['bad'] = True


def lineup_suggestion(alias):
    """How to get past a line-up that cannot be used."""
    return (f'run map.py sync PROJECT and read what it says about {alias}; a look stays a look until someone listens, '
            'then map.py sync PROJECT --set ALIAS=SECONDS --note TEXT')


def validate_sound_from(entry, source_map, problems):
    """{sound ALIAS} on a line: a registered, unchanged source with sound, lined up with the line's own source."""
    alias, line, sound = entry['alias'], entry['line'], entry['mods']['sound_from']
    if sound not in source_map.sources:
        close = difflib.get_close_matches(sound, list(source_map.sources), 3, 0.5)
        problems.error(line, f'unknown source alias {sound} in sound', ('known aliases near it: ' + ', '.join(close))
                       if close else 'known aliases: ' + ', '.join(sorted(source_map.sources)[:12]))
        return False
    if sound == alias:
        problems.error(line, f'{sound} is this line\'s own source', 'write sound, or sound -3dB, for its own sound')
        return False
    problem = source_map.media_problem(sound)
    if problem:
        problems.error(line, f'{sound}: {problem}',
                       'restore the file, or map it again (map.py run PROJECT) and line it up again (map.py sync)')
        return False
    if not source_map.has_audio(sound):
        problems.error(line, f'{sound} has no sound to take', 'name a lined-up source with sound')
        return False
    reason = source_map.lineup_problem(alias, sound)
    if reason:
        problems.error(line, f'{alias} and {sound} are not lined up: {reason}', lineup_suggestion(sound))
        return False
    return True


def range_past_end(entry, source_map, problems):
    """Check a range against where its source really ends. Picture needs picture, so a range past it is an error though
    the sound goes on. Sound that stops short of its header is an error; sound that is simply shorter than its picture
    is a warning, since a camera file's often is, and the render carries on with the rest of the line silent."""
    alias, line, end = entry['alias'], entry['line'], entry['end']
    duration = source_map.duration(alias)
    stop = source_map.picture_end(alias)
    why = source_map.short_note(alias, 'picture')
    if (entry['kind'] in ('picture', 'cutaway') and source_map.has_video(alias) and stop and end > stop + RANGE_SLACK
            and (why or stop < duration - RANGE_SLACK)):
        problems.error(line, f"the range ends at {fmt(end)} but {alias}'s picture ends at {fmt(stop)}{why}",
                       f'end the range by {fmt(stop)}, or hold its last frame with a pause hold line')
        entry['bad'] = True
        return
    if duration and end > duration + RANGE_SLACK:
        problems.error(line, f'the range ends at {fmt(end)} but {alias} lasts {fmt(duration)}'
                       + (why or source_map.short_note(alias, 'sound')), f'end the range by {fmt(duration)}')
        entry['bad'] = True
        return
    stop = source_map.sound_end(alias)
    if ((entry['kind'] in ('music', 'spoken') or 'sound' in entry['mods']) and source_map.has_audio(alias) and stop
            and end > stop + RANGE_SLACK and 'sound_from' not in entry['mods']):
        why = source_map.short_note(alias, 'sound')
        message = f"the range ends at {fmt(end)} but {alias}'s sound ends at {fmt(stop)}{why}"
        if why:
            problems.error(line, message, f'end the range by {fmt(stop)}, or remove its sound')
            entry['bad'] = True
        else:
            problems.warn(line, message + '; the rest of this line is silent', f'end the range by {fmt(stop)}, or '
                          'lay other sound under the rest')


def picture_past_end(plan, source_map, problems):
    """A line's own picture past where its source's picture ends. A spoken line is checked here, not by its range, once
    cutaways have taken what they cover: a cutaway may cover the part with no picture of its own."""
    named = set()
    for seg in plan['segments']:
        alias = seg['key']
        if alias not in source_map.sources or not source_map.has_video(alias) or seg['line'] in named:
            continue
        stop = source_map.picture_end(alias)
        out = seg['s0'] + (seg['t1'] - seg['t0']) * seg['speed']
        if stop and out > stop + RANGE_SLACK:
            named.add(seg['line'])
            problems.error(seg['line'], f"this line plays {alias} to {fmt(out)} but {alias}'s picture ends at "
                           f"{fmt(stop)}{source_map.short_note(alias, 'picture')}",
                           f'end the line by {fmt(stop)}, or cover the rest with a cutaway (~ line)')


COVER_LOSS = 1 / 3  # cover framing that discards this share of a source's height or width says so
COVER_NOTE = 'cover framing discards'
COVER_FACE_SAMPLES = 3


def faces_outside_crop(detect, samples, centre, size):
    """The sample times at which a detected face's centre falls outside the kept part of the frame: `samples` is
    [(time, RGB frame)], `centre` and `size` the crop as fractions of the frame, `detect` gives each frame's boxes."""
    left, top = centre[0] - size[0] / 2, centre[1] - size[1] / 2
    lost = []
    for moment, frame in samples:
        for box in detect(frame):
            x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            if not (left <= x <= left + size[0] and top <= y <= top + size[1]):
                lost.append(moment)
                break
    return lost


def cover_faces(source_map, alias, segments, display, kept, ffmpeg):
    """When OpenCV is installed: the source times, in a few sampled frames of these lines, where a face falls outside
    what cover keeps. [] when it is not, when no face is lost, or when a frame cannot be read; the note stands
    anyway. Faces smaller than about 3% of the frame's width go unseen."""
    if not ffmpeg:
        return []
    import numpy as np
    detect, _ = load_sibling('reframe').make_face_detector()
    if detect is None:
        return []
    width = 640  # the detector's smallest face is 18 pixels
    height = max(2, even(display[1] * width / display[0]))
    found = []
    for seg in segments[:COVER_FACE_SAMPLES]:
        length = (seg['t1'] - seg['t0']) * seg['speed']
        moments = [seg['s0'] + length * share for share in (.25, .75)]
        samples = []
        for moment in moments:
            result = subprocess.run([ffmpeg, '-v', 'error', '-ss', f'{moment:.3f}', '-i', str(source_map.path(alias)),
                                     '-frames:v', '1', '-vf', f'scale={width}:{height}', '-f', 'rawvideo',
                                     '-pix_fmt', 'rgb24', '-'], stdin=subprocess.DEVNULL, capture_output=True)
            if result.returncode or len(result.stdout) != width * height * 3:
                continue
            samples.append((moment, np.frombuffer(result.stdout, np.uint8).reshape(height, width, 3)))
        crop = seg['frame']['crop'][0]
        try:
            found += faces_outside_crop(detect, samples, (crop[1], crop[2]), kept)
        except ValueError:
            return []
    return found


def cover_framing(plan, source_map, settings, problems, ffmpeg=None):
    """Warn once per source when cover framing throws away a third or more of its height or width, naming the first
    line and what would keep more of it. A line with fit contain or crop auto has already chosen; the framing stays as
    it was asked for."""
    if not settings.get('size'):
        return
    width, height = settings['size']
    film = width / height
    flagged = {}
    for seg in plan['segments']:
        alias, frame = seg['key'], seg['frame']
        if (alias not in source_map.sources or not source_map.has_video(alias) or frame.get('fit') != 'cover'
                or frame.get('crop') == 'auto'):
            continue
        try:
            display = source_map.size(alias)
        except ValueError:
            continue
        if display:
            flagged.setdefault(alias, (display, []))[1].append(seg)
    for alias, (display, segments) in flagged.items():
        shape = display[0] / display[1]
        kept = (min(1.0, film / shape), min(1.0, shape / film))
        lost = 1 - min(kept)
        if lost < COVER_LOSS - 1e-9:
            continue
        lines = sorted({seg['line'] for seg in segments})
        side = 'height' if kept[1] < kept[0] else 'width'
        more = f' (and {len(lines) - 1} more line{"s" if len(lines) > 2 else ""})' if len(lines) > 1 else ''
        faces = cover_faces(source_map, alias, segments, display, kept, ffmpeg)
        said = f"; OpenCV finds a face outside what it keeps at {alias} {fmt(faces[0])}" if faces else ''
        problems.warn(lines[0], f"{COVER_NOTE} {round(lost * 100)}% of {alias}'s {side} on this line{more}: a "
                      f'{display[0]}x{display[1]} clip in a {width}x{height} film{said}',
                      '{crop auto} follows the largest face or the motion, and {fit contain} keeps the whole picture, '
                      'letterboxed (references/paper-edit.md section 7)')


def validate_over(entry, source_map, problems):
    """~ over needs a PNG or a video with transparency; remember the graphic's size and frame rate (read as the
    render reads them) for the compiler."""
    alias, line = entry['alias'], entry['line']
    path = source_map.path(alias)
    if source_map.is_image(alias):
        if not image_transparent(path):
            problems.error(line, f'{alias} has no transparency, so ~ over would cover the whole picture',
                           f'export it as a PNG with transparency, or write ~ still {alias} SECONDS for a '
                           'full-frame cutaway')
            entry['bad'] = True
            return
        from PIL import Image
        with Image.open(path) as image:
            entry['graphic'] = {'size': image.size}
        return
    if not source_map.has_video(alias):
        problems.error(line, f'{alias} has no picture; ~ over draws a video or image with transparency')
        entry['bad'] = True
        return
    try:
        entry['graphic'] = load_sibling('render_common').overlay_probe(path)
    except ValueError as error:
        problems.error(line, f'{alias}: {error}')
        entry['bad'] = True
        return
    if not entry['graphic']['alpha']:
        problems.error(line, f'{alias} has no transparency ({entry["graphic"]["pix_fmt"]}), so ~ over would cover the '
                       'whole picture', 'render it with an alpha channel (PNG in a MOV, QuickTime Animation, ProRes '
                       '4444 or VP9 WebM)')
        entry['bad'] = True


def validate_still(entry, source_map, problems):
    """A still needs an image, or a video with a freeze time inside it."""
    alias, line = entry['alias'], entry['line']
    if source_map.is_image(alias):
        if entry.get('freeze') is not None:
            problems.warn(line, f'{alias} is an image; the time {fmt(entry["freeze"])} is ignored')
        if (entry['over'] and not {'pin', 'behind'} & set(entry['mods'])
                and image_transparent(source_map.path(alias))):
            problems.warn(line, f'{alias} has clear areas; a ~ still replaces the picture, so they show the '
                          'background colour', f'to draw it over the picture, write ~ over {alias} '
                          f'{entry["seconds"]:g}')
        return
    if not source_map.has_video(alias):
        problems.error(line, f'{alias} has no picture to show as a still')
        entry['bad'] = True
        return
    if entry.get('freeze') is None:
        problems.error(line, f'{alias} is a video: say which frame to freeze',
                       f'write it like: still {alias} 0:12.40 {entry["seconds"]:g}')
        entry['bad'] = True
        return
    stop = source_map.picture_end(alias)
    if stop and entry['freeze'] >= stop:
        problems.error(line, f'the freeze time {fmt(entry["freeze"])} is past the end of {alias}\'s picture, '
                       f"{fmt(stop)}{source_map.short_note(alias, 'picture')}")
        entry['bad'] = True


def plausible_limit(settings):
    """The longest a line may plausibly last: four times the target, and never more than three hours."""
    target = settings.get('target')
    return min(MAX_FILM, 4 * target) if target else MAX_FILM


def check_length(entry, settings, problems):
    """Refuse a line whose length is implausible (a mistyped range or speed), before anything is decoded."""
    if entry['bad'] or entry['kind'] in ('music', 'title'):
        return
    if entry.get('start') is not None:
        length = (entry['end'] - entry['start']) / max(entry['mods'].get('speed', 1.0), 1e-9)
    else:
        length = entry.get('seconds') or 0.0
    limit = plausible_limit(settings)
    if length > limit:
        basis = '4x the target' if settings.get('target') and limit < MAX_FILM else 'the 3-hour limit'
        problems.error(entry['line'], f'this line would last {length:.0f} s, more than {basis} ({limit:.0f} s)',
                       'check its range and speed (x0.01 makes a line 100 times longer); if the film really is '
                       'this long, raise target')
        entry['bad'] = True


def check_plausible(edit, total, limit):
    """A last check on the timeline assemble.py will render: no item or film longer than is plausible."""
    if total > MAX_FILM:
        raise RuntimeError(f'the film would last {total / 3600:.1f} hours; refusing to render')
    for item in edit['picture']:
        length = (float(item['out']) - float(item['in'])) / float(item.get('speed', 1))
        if length > limit + 2.0:
            raise RuntimeError(f'a picture item from {item["src"]} would last {length:.0f} s; refusing to render')
    for item in edit['audio']:
        if float(item['out']) - float(item['in']) > max(limit, total) + 1.0:
            raise RuntimeError(f'an audio item from {item["src"]} would last '
                               f'{float(item["out"]) - float(item["in"]):.0f} s; refusing to render')


def framing(entry, settings):
    """The picture framing for an entry: fit, zoom and crop (assemble.py's crop path or 'auto')."""
    mods = entry['mods']
    crop = mods.get('crop', settings['crop'])
    path = 'auto' if crop == 'auto' else [[0, crop[0], crop[1]]]
    frame = {'fit': mods.get('fit', settings['fit']), 'zoom': mods.get('zoom', 1.0), 'crop': path}
    if 'zoom' in mods:
        frame['zoom_explicit'] = True
    return frame


def segment(t0, t1, key, s0, speed, join, frame, grid, limit, line):
    """One stretch of picture on the edit clock."""
    return {'t0': t0, 't1': t1, 'key': key, 's0': s0, 'speed': speed, 'join': join, 'frame': frame, 'grid': grid,
            'limit': limit, 'line': line}


def cut_description(record, at, words):
    """Name the edge and the nearest kept words on either side of an edit-clock cut."""
    if abs(at - record.get('start', -1)) < .0002:
        edge = 'the start of this line'
    elif abs(at - record.get('end', -1)) < .0002:
        edge = 'the end of this line'
    else:
        edge = 'a cut inside the line'
    before = [word for word in words if word['end'] <= at + .0001]
    after = [word for word in words if word['start'] >= at - .0001]
    sides = []
    if before:
        sides.append('after ' + repr(max(before, key=lambda word: word['end'])['text']))
    if after:
        sides.append('before ' + repr(min(after, key=lambda word: word['start'])['text']))
    return f"{edge} at {fmt(at)}" + (' (' + ', '.join(sides) + ')' if sides else '')


def report_tight_cuts(records, total, problems):
    """Report actual boundaries, their edge and nearby words; never call unmeasured cuts clean."""
    seen = set()
    words = []
    for record in records:
        for word in record.get('words', []):
            if (isinstance(word, dict) and isinstance(word.get('start'), (int, float))
                    and isinstance(word.get('end'), (int, float)) and word.get('text')):
                words.append(word)
    for record in records:
        if record.get('kind') != 'spoken':
            continue
        tight = [at for at in record.get('tight_cuts', []) if .0001 < at < total - .0001]
        record['tight_cuts'] = tight
        if 'unmeasured_cuts' in record:
            unmeasured = [at for at in record['unmeasured_cuts'] if .0001 < at < total - .0001]
            record['unmeasured_cuts'] = unmeasured
            for at in unmeasured:
                key = round(at, 4)
                if key in seen:
                    continue
                seen.add(key)
                description = cut_description(record, at, words)
                problems.warn(record['line'], f'{description} was placed from transcript times only, not measured: '
                              f'{record.get("unmeasured_why", "the audio was not measured")}',
                              'listen: transcript word edges can clip a word or keep a breath')
        for at in tight:
            key = round(at, 4)
            if key in seen:
                continue
            seen.add(key)
            description = cut_description(record, at, words)
            problems.warn(record['line'], f'{description} has no audible pause; listen to it',
                          'cut at a pause between phrases if it sounds clipped')


class Compiler:
    """Turn parsed entries into a timeline: picture segments, audio items, overlays, assets, lines and words."""

    def __init__(self, settings, entries, source_map, envelopes, problems):
        self.settings = settings
        self.entries = entries
        self.map = source_map
        self.envelopes = envelopes
        self.problems = problems
        self.rate = settings['fps'] or Fraction(30)
        self.segments = []
        self.audio = []
        self.overlays = []
        self.assets = {}
        self.lines = []
        self.words = []
        self.fades = {}
        self.cursor = 0.0
        self.pending = []
        self.layers = []
        self.freezes = 0
        self.energy_review_reported = set()
        self.last_spoken = None
        self.line_pieces = []
        self.spans = {}
        self.layer_uses = []
        self.attached = {}
        self.drift_said = set()

    def say_drift(self, alias, line):
        """Say once when a source used here drifts past a frame: each stretch is right at its own place, and a long
        unbroken take moves against it."""
        note = self.map.lineup().drift_note(alias) if alias not in self.drift_said else ''
        self.drift_said.add(alias)
        if note:
            self.problems.warn(line, note + '; each stretch uses the offset at its own place in the recording',
                               'look at the long takes: the longer the unbroken stretch, the further its end moves')

    def grid(self, alias):
        """The frame grid used to predict assemble.py's snapping: (rate, offset)."""
        return (self.map.fps(alias) or self.rate, 0.0)

    def background_frame(self):
        """Framing for generated plain clips."""
        return {'fit': 'cover', 'zoom': 1.0, 'crop': [[0, 0.5, 0.5]]}

    def run(self):
        """Compile every entry; returns the plan."""
        timed = [entry for entry in self.entries if not entry['over'] and entry['kind'] != 'music'
                 and entry['kind'] != 'title']
        first_timed = timed[0]['line'] if timed else None
        last_timed = timed[-1]['line'] if timed else None
        parent = None
        attached = {}
        for entry in self.entries:
            if entry['over']:
                if parent is None:
                    self.problems.error(entry['line'], 'a ~ line needs a line above it to sit over',
                                        'put it under a spoken, picture, still, pause or card line')
                else:
                    attached.setdefault(parent['line'], []).append(entry)
                continue
            if entry['kind'] in ('music', 'title'):
                continue
            parent = entry
        self.attached = attached
        for entry in self.entries:
            validate_entry(entry, self.map, self.problems)
            check_length(entry, self.settings, self.problems)
        for entry in self.entries:
            if entry['over']:
                continue
            if entry['kind'] in ('music', 'title'):
                self.pending.append(entry)
                continue
            self.check_edges(entry, first_timed, last_timed)
            if entry['bad']:
                self.last_spoken = None
                continue
            start = self.cursor
            if entry['kind'] != 'spoken':
                self.last_spoken = None
            built = self.build_timed(entry)
            if built is None:
                self.last_spoken = None
                continue
            self.flush_pending(start)
            for over in attached.get(entry['line'], []):
                if not over['bad']:
                    self.build_over(over, entry, built)
            self.lay_cutaways(built)
            self.segments.extend(built['segments'])
            self.lines.append(built['record'])
            for piece in built['pieces']:
                piece['record'] = built['record']
            self.line_pieces.append(built['pieces'])
        total = self.cursor
        self.carry_sound(total)
        if total > MAX_FILM:
            self.problems.error(1, f'the film would last {total / 3600:.1f} hours, over the 3-hour limit',
                                'check ranges, speeds and pauses')
        for entry in self.pending:
            if entry['bad']:
                continue
            if entry['kind'] == 'music':
                hint = ('a music line starts where it is written: move it to the top of the film for a bed under '
                        'everything, or indent it as "  ~ music ..." under the line it should start with')
            else:
                hint = ('a title starts where it is written: indent it as "  ~ title ..." under the line it should '
                        'appear over, or move it above the line it should start with')
            self.problems.error(entry['line'], f'this {entry["kind"]} line comes after the last line that takes '
                                'time, so it has nothing to play over', hint)
        self.finish_layers(total)
        if self.segments and self.segments[0]['join']:
            self.problems.error(self.segments[0]['line'], 'the first line has nothing to dissolve or dip from',
                                'use fade in 0.5 instead')
            self.segments[0]['join'] = None
        report_tight_cuts(self.lines, total, self.problems)
        self.lines.sort(key=lambda record: record['line'])
        return {'duration': total, 'segments': self.segments, 'audio': self.audio, 'overlays': self.overlays,
                'assets': self.assets, 'lines': self.lines, 'words': self.words, 'fades': self.fades,
                'pieces': self.line_pieces, 'spans': self.spans, 'layer_uses': self.layer_uses}

    def check_edges(self, entry, first_timed, last_timed):
        """fade in only on the first line, fade out only on the last."""
        mods = entry['mods']
        if 'fade_in' in mods and entry['line'] != first_timed:
            self.problems.error(entry['line'], 'fade in applies to the film\'s first line only',
                                'between lines use dip 0.5 or dissolve 0.25')
            del mods['fade_in']
        if 'fade_out' in mods and entry['line'] != last_timed:
            self.problems.error(entry['line'], 'fade out applies to the film\'s last line only',
                                'between lines use dip 0.5 or dissolve 0.25')
            del mods['fade_out']
        if 'fade_in' in mods:
            self.fades['in'] = mods['fade_in']
        if 'fade_out' in mods:
            self.fades['out'] = mods['fade_out']

    def join_of(self, entry):
        """The join into a line: None for a cut, else (kind, seconds)."""
        join = entry['mods'].get('join')
        if join and join[1] <= 0:
            return None
        return join

    def build_timed(self, entry):
        """Picture segments, audio and a lines.json record for a line that takes time."""
        builder = {'spoken': self.build_spoken, 'picture': self.build_picture, 'still': self.build_still,
                   'pause': self.build_pause, 'card': self.build_card}[entry['kind']]
        return builder(entry)

    def record(self, entry, kind, start, end, **extra):
        """A lines.json record."""
        record = {'line': entry['line'], 'section': entry['section'], 'kind': kind, 'start': round(start, 4),
                  'end': round(end, 4)}
        if entry.get('alias'):
            record['source'] = entry['alias']
        if entry.get('start') is not None and kind not in ('title', 'card'):
            record['range'] = [round(entry['start'], 4), round(entry['end'], 4)]
        if entry.get('text'):
            record['text'] = entry['text']
        record.update(extra)
        return record

    def build_spoken(self, entry):
        """A spoken line: match words, place cuts, lay the kept pieces end to end."""
        alias = entry['alias']
        words = self.map.words(alias)
        kept = match_spoken(entry, words, self.problems)
        if kept is None:
            entry['bad'] = True
            return None
        envelope = None
        sound_alias = entry['mods'].get('sound_from')
        lineup = self.map.lineup() if sound_alias else None
        if self.envelopes is not None and sound_alias:
            shift = lineup.map_time(alias, sound_alias, entry['start']) - entry['start']
            envelope = self.envelopes.from_source(sound_alias, entry['start'] - 2.5, entry['end'] + 2.5, shift)
        elif self.envelopes is not None:
            envelope = self.envelopes.get(alias, entry['start'] - 2.5, entry['end'] + 2.5)
        unmeasured_why = self.unmeasured_reason(sound_alias or alias, envelope)
        runs = spoken_runs(entry, words, kept, envelope, self.settings, self.problems)
        if sound_alias and not self.sound_covers(entry, sound_alias, [(run['in'], run['out']) for run in runs]):
            entry['bad'] = True
            self.last_spoken = None
            return None
        previous = self.last_spoken
        continuous = False
        if (previous and previous['alias'] == alias and runs and
                previous['word'] + 1 == runs[0]['words'][0] and runs[0]['in'] < previous['out']):
            first_word = words[runs[0]['words'][0]]
            if previous['out'] >= runs[0]['out'] or previous['out'] >= first_word['end']:
                self.problems.error(entry['line'], 'adjacent source lines overlap the next word',
                                    'adjust the ranges; the next word has no unplayed audio left')
                entry['bad'] = True
                self.last_spoken = None
                return None
            if previous['out'] > first_word['start']:
                self.problems.warn(entry['line'], f'adjacent source lines meet inside a word at '
                                   f'{fmt(previous["out"])}; listen to the join')
            runs[0]['in'] = previous['out']
            continuous = True
        indices = range_words(words, entry['start'], entry['end'])
        same_boundary = (previous and runs and previous['alias'] == alias
                         and abs(previous['range_end'] - entry['start']) < 1e-6
                         and previous['last_in_range'] and indices and indices[0] == runs[0]['words'][0]
                         and previous['word'] + 1 == runs[0]['words'][0]
                         and abs(previous['out'] - runs[0]['in']) < 1e-6
                         and previous['gain'] == entry['mods'].get('sound', 0.0) and not self.join_of(entry))
        if same_boundary and previous.get('sound') != sound_alias:
            same_boundary = False
        if same_boundary and sound_alias:
            # A drifting source's offset moves between lines: only the same sample carries on without a fade.
            carried = lineup.map_time(alias, sound_alias, runs[0]['in'])
            same_boundary = abs(previous['audio']['out'] - carried) < 1e-4
        if same_boundary:
            continuous = True
            for key in ('tight_cuts', 'unmeasured_cuts'):
                old = previous['record'].get(key, [])
                previous['record'][key] = [at for at in old if abs(at - self.cursor) > .00011]
            runs[0]['tight'][0] = False
        same_sound = not previous or previous.get('sound') == sound_alias
        self.last_spoken = ({'alias': alias, 'word': runs[-1]['words'][-1], 'out': runs[-1]['out'],
                             'range_end': entry['end'], 'last_in_range': bool(indices)
                             and indices[-1] == runs[-1]['words'][-1], 'record': None,
                             'gain': entry['mods'].get('sound', 0.0), 'audio': None, 'sound': sound_alias}
                            if runs else None)
        review = self.map.transcript_review(alias)
        if review.get('energy_check', '').startswith('unavailable') and alias not in self.energy_review_reported:
            self.problems.warn(entry['line'], f'{alias} transcript energy review is unavailable',
                               f'run map.py run with --alias {alias}, then listen around the joins')
            self.energy_review_reported.add(alias)
        for prompt in review.get('prompts', []):
            if float(prompt.get('end', 0)) < entry['start'] or float(prompt.get('start', 0)) > entry['end']:
                continue
            self.problems.warn(entry['line'], f'{alias} transcript review at {fmt(float(prompt["start"]))}: '
                               f'{prompt.get("detail", "listen to this source interval")}',
                               'listen around the paper-edit joins and correct the transcript if needed')
        start = self.cursor
        segments, cuts, tight, kept_words, pieces = [], [], [], [], []
        has_picture = self.map.has_video(alias)
        frame = framing(entry, self.settings) if has_picture else self.background_frame()
        gain = entry['mods'].get('sound', 0.0)
        for number, run in enumerate(runs):
            at = self.cursor
            length = run['out'] - run['in']
            key = alias if has_picture else self.need_background()
            s0 = run['in'] if has_picture else 0.0
            limit = self.map.picture_end(alias) if has_picture else None
            join = self.join_of(entry) if number == 0 else None
            segments.append(segment(at, at + length, key, s0, 1.0, join, frame,
                                    self.grid(alias) if has_picture else (self.rate, 0.0), limit, entry['line']))
            shift = lineup.map_time(alias, sound_alias, run['in']) - run['in'] if sound_alias else 0.0
            sound_in, sound_out = run['in'] + shift, run['out'] + shift
            # A mic that started a hair after this piece: its sound starts when it does, at the right moment.
            late = max(0.0, -sound_in)
            item = {'track': 'dialogue', 'src': sound_alias or alias, 'in': round(sound_in + late, 6),
                    'out': round(sound_out, 6), 'at': round(at + late, 6), 'fade_ms': AUDIO_FADE_MS,
                    **({'gain_db': gain} if gain else {})}
            if same_boundary and number == 0:
                previous['audio']['fade_out_ms'] = 0
                item['fade_in_ms'] = 0
            self.audio.append(item)
            self.last_spoken['audio'] = item
            first, last = words[run['words'][0]], words[run['words'][-1]]
            spoken = (at + max(0.0, first['start'] - run['in']), at + min(run['out'], last['end']) - run['in'])
            pieces.append(self.piece(entry, sound_alias or alias, sound_in, sound_out, at, at + length, item, spoken))
            pieces[-1]['continuous'] = continuous and number == 0 and same_sound
            pieces[-1].update(clock_alias=alias, clock_in=run['in'])
            if number:
                cuts.append(round(at, 4))
            if run['tight'][0] and number == 0:
                tight.append(round(at, 4))
            if number and (run['tight'][0] or runs[number - 1]['tight'][1]):
                tight.append(round(at, 4))
            if run['tight'][1] and number == len(runs) - 1:
                tight.append(round(at + length, 4))
            for index in run['words']:
                word = words[index]
                kept_words.append(self.edit_word(word, run, at))
            self.cursor = at + length
        covered = any(over.get('sync') and not over['bad'] and over.get('seconds') is None
                      and 'offset' not in over['mods'] for over in self.attached.get(entry['line'], []))
        if not has_picture and not covered:
            self.problems.warn(entry['line'], f'{alias} has no picture; uncovered parts of this line show the '
                               'background colour', 'cover it with cutaways (~ lines)')
        removed = [words[index] for index in range_words(words, entry['start'], entry['end'])
                   if index not in set(kept)]
        self.words.extend(kept_words)
        extra = {}
        if unmeasured_why:
            # Every join of this line was placed from transcript times: list each as tight and say why.
            unmeasured = sorted(set(cuts + ([] if continuous else [round(start, 4)]) + [round(self.cursor, 4)]))
            tight = sorted(set(tight) | set(unmeasured))
            extra = {'unmeasured_cuts': unmeasured, 'unmeasured_why': unmeasured_why}
        run_rows = [{'in': round(run['in'], 4), 'out': round(run['out'], 4), 'at': round(segments[number]['t0'], 4)}
                    for number, run in enumerate(runs)]
        if sound_alias:
            extra['sound_source'] = sound_alias
            for row, piece in zip(run_rows, pieces):
                row.update(sound_src=sound_alias, sound_in=round(piece['in'], 6), sound_out=round(piece['out'], 6))
            self.say_drift(sound_alias, entry['line'])
        record = self.record(entry, 'spoken', start, self.cursor, words=kept_words,
                             cut_words=[{'id': word.get('id'), 'text': word['text']} for word in removed],
                             runs=run_rows,
                             audio_cuts=cuts, jump_cuts=list(cuts) if has_picture else [], tight_cuts=tight,
                             **extra)
        if self.last_spoken is not None:
            self.last_spoken['record'] = record
        return {'entry': entry, 'start': start, 'end': self.cursor, 'segments': segments, 'record': record,
                'spans': [], 'pieces': pieces}

    def sound_covers(self, entry, sound, spans):
        """Whether a lined-up source has sound for every stretch of a line, given on the line's own clock; an error on
        its line, saying what it does cover, when it does not."""
        lineup = self.map.lineup()
        alias = entry['alias']
        stop = self.map.sound_end(sound)
        for low, high in spans:
            first = lineup.map_time(alias, sound, low)
            last = first + high - low
            if first < -RANGE_SLACK or (stop and last > stop + RANGE_SLACK):
                begin = lineup.map_time(sound, alias, 0.0)
                finish = lineup.map_time(sound, alias, stop) if stop else None
                covers = (f'{fmt(max(0.0, begin))}-{fmt(finish)}' if finish is not None
                          else f'from {fmt(max(0.0, begin))}')
                self.problems.error(entry['line'], f"{sound} has no sound for {fmt(low)}-{fmt(high)} of {alias}: on "
                                    f"{alias}'s clock it runs {covers}",
                                    f'keep this line inside that stretch, or take its sound from another source')
                return False
        return True

    def piece(self, entry, alias, source_in, source_out, start, end, item=None, spoken=(None, None)):
        """One stretch of a line on the edit clock and its own sound item (None when silent): the unit that joins
        are measured on and that tail, lead and dissolve carry sound across. `spoken` is the film time of its
        first kept word's start and last kept word's end."""
        if item is not None:
            self.spans[id(item)] = (start, end)
        return {'line': entry['line'], 'entry': entry, 'alias': alias, 'in': source_in, 'out': source_out,
                'at': start, 'end': end, 'item': item, 'gain': (item or {}).get('gain_db', 0.0),
                'speed': entry['mods'].get('speed', 1.0), 'first_word': spoken[0], 'last_word': spoken[1],
                'continuous': False, 'carry': {}, 'clock_alias': alias, 'clock_in': source_in}

    def unmeasured_reason(self, alias, envelope):
        """Why a spoken line's cuts could not be measured in its audio, or None when they were."""
        if envelope is not None and envelope.reliable:
            return None
        if self.envelopes is None:
            return 'pauses were not measured (FFmpeg was not found, or check ran with --no-audio)'
        if not self.map.has_audio(alias):
            return f'map/sources.json lists no sound for {alias}'
        if envelope is None:
            return f'the audio of {alias} could not be decoded here'
        return (f'the sound level of {alias} never falls far enough below the speech to tell a pause from a word '
                '(steady noise, music or a tone under it)')

    def edit_word(self, word, run, at):
        """A kept word placed on the edit clock."""
        start = at + max(0.0, word['start'] - run['in'])
        end = at + min(run['out'], word['end']) - run['in']
        result = {'id': word.get('id'), 'text': str(word['text']).strip(), 'start': round(start, 4),
                  'end': round(max(end, start + 0.01), 4)}
        if word.get('estimated'):
            result['estimated'] = True
        if word.get('speaker') is not None:
            result['speaker'] = word['speaker']
        return result

    def build_picture(self, entry):
        """A picture line: one segment, silent unless it asks for sound."""
        alias = entry['alias']
        speed = entry['mods'].get('speed', 1.0)
        if speed <= 0:
            self.problems.error(entry['line'], 'speed must be more than 0')
            return None
        start = self.cursor
        length = (entry['end'] - entry['start']) / speed
        seg = segment(start, start + length, alias, entry['start'], speed, self.join_of(entry),
                      framing(entry, self.settings), self.grid(alias), self.map.picture_end(alias), entry['line'])
        self.check_carry(entry, speed)
        item = None
        sound_alias = entry['mods'].get('sound_from')
        sound_in, sound_out = entry['start'], entry['end']
        extra = {}
        if sound_alias:
            if speed != 1:
                self.problems.error(entry['line'], f'sound from {sound_alias} cannot play at x{speed:g}: it would slip '
                                    'off the picture it is lined up with', 'remove the speed, or the sound')
                return None
            if not self.sound_covers(entry, sound_alias, [(entry['start'], entry['end'])]):
                return None
            shift = self.map.lineup().map_time(alias, sound_alias, entry['start']) - entry['start']
            sound_in, sound_out = round(entry['start'] + shift, 6), round(entry['end'] + shift, 6)
            extra['sound_source'] = sound_alias
            self.say_drift(sound_alias, entry['line'])
        if 'sound' in entry['mods']:
            late = max(0.0, -sound_in)
            item = {'track': 'nat', 'src': sound_alias or alias, 'in': sound_in + late, 'out': sound_out,
                    'at': round(start + late, 6), 'fade_ms': 15, 'gain_db': entry['mods']['sound']}
            self.audio.append(item)
        self.cursor = start + length
        record = self.record(entry, 'picture', start, self.cursor, speed=speed, **extra)
        piece = self.piece(entry, sound_alias or alias, sound_in, sound_out, start, self.cursor, item)
        piece.update(clock_alias=alias, clock_in=entry['start'])
        return {'entry': entry, 'start': start, 'end': self.cursor, 'segments': [seg], 'record': record, 'spans': [],
                'pieces': [piece]}

    def check_carry(self, entry, speed):
        """tail and lead carry a picture line's own sound, so it needs sound at its recorded speed."""
        for name in ('tail', 'lead'):
            if name not in entry['mods']:
                continue
            if 'sound' not in entry['mods']:
                self.problems.error(entry['line'], f'{name} carries the line\'s own sound, and this picture line is '
                                    'silent', f'add sound (or sound -12dB) before {name}, or remove {name}')
                del entry['mods'][name]
            elif speed != 1:
                self.problems.error(entry['line'], f'{name} cannot carry the sound of a line played at x{speed:g}',
                                    f'remove the speed or the {name}')
                del entry['mods'][name]

    def still_key(self, entry):
        """The generated clip that shows a still: the image itself, or a frozen video frame."""
        alias = entry['alias']
        if self.map.is_image(alias):
            key = f'gen-still-{alias}'
            self.assets.setdefault(key, {'kind': 'still', 'alias': alias, 'need': 0.0})
            return key
        self.freezes += 1
        key = f'gen-freeze-{self.freezes:02d}'
        self.assets[key] = {'kind': 'freeze', 'alias': alias, 'time': entry['freeze'], 'need': 0.0}
        return key

    def need_background(self):
        """The generated plain clip in the background colour."""
        self.assets.setdefault('gen-background', {'kind': 'background', 'need': 0.0})
        return 'gen-background'

    def build_still(self, entry):
        """A still image or frozen frame for a number of seconds."""
        start = self.cursor
        key = self.still_key(entry)
        seg = segment(start, start + entry['seconds'], key, 0.0, 1.0, self.join_of(entry),
                      framing(entry, self.settings), (self.rate, 0.0), None, entry['line'])
        self.cursor = start + entry['seconds']
        record = self.record(entry, 'still', start, self.cursor)
        return {'entry': entry, 'start': start, 'end': self.cursor, 'segments': [seg], 'record': record, 'spans': [],
                'pieces': [self.piece(entry, None, None, None, start, self.cursor)]}

    def build_pause(self, entry):
        """A beat of silence on the background colour, or a hold of the previous frame."""
        start = self.cursor
        key = self.need_background()
        frame = self.background_frame()
        if entry['mods'].get('hold'):
            if not self.segments:
                self.problems.error(entry['line'], 'pause hold needs a line before it to hold')
                return None
            last = self.segments[-1]
            frame = last['frame']
            if last['key'].startswith('gen-'):
                key = last['key']
            else:
                self.freezes += 1
                key = f'gen-freeze-{self.freezes:02d}'
                moment = last['s0'] + (last['t1'] - last['t0']) * last['speed'] - 1.0 / float(last['grid'][0])
                self.assets[key] = {'kind': 'freeze', 'alias': last['key'], 'time': max(0.0, moment), 'need': 0.0,
                                    'hold_previous': True}
        seg = segment(start, start + entry['seconds'], key, 0.0, 1.0, self.join_of(entry), frame,
                      (self.rate, 0.0), None, entry['line'])
        if entry['mods'].get('hold'):
            seg['hold_previous'] = True
        self.cursor = start + entry['seconds']
        record = self.record(entry, 'pause', start, self.cursor, hold=bool(entry['mods'].get('hold')))
        return {'entry': entry, 'start': start, 'end': self.cursor, 'segments': [seg], 'record': record, 'spans': [],
                'pieces': [self.piece(entry, None, None, None, start, self.cursor)]}

    def build_card(self, entry):
        """A title card: its own time on the background colour, with the title over it."""
        start = self.cursor
        seg = segment(start, start + entry['seconds'], self.need_background(), 0.0, 1.0, self.join_of(entry),
                      self.background_frame(), (self.rate, 0.0), None, entry['line'])
        self.cursor = start + entry['seconds']
        self.add_title(entry, start, entry['seconds'], 'center')
        record = self.record(entry, 'title', start, self.cursor, card=True, position=entry['mods'].get(
            'position', 'center'))
        return {'entry': entry, 'start': start, 'end': self.cursor, 'segments': [seg], 'record': record, 'spans': [],
                'pieces': [self.piece(entry, None, None, None, start, self.cursor)]}

    def add_title(self, entry, start, length, default_position):
        """A title overlay; rendered to a transparent PNG at render time."""
        key = f'title-{len([k for k in self.assets if k.startswith("title-")]) + 1:02d}'
        self.assets[key] = {'kind': 'title', 'texts': entry['texts'],
                            'position': entry['mods'].get('position', default_position)}
        fade = entry['mods'].get('fade', TITLE_FADE)
        overlay = {'kind': 'image', 'src': key, 'from': round(start, 6), 'to': round(start + length, 6),
                   'x': 0, 'y': 0, 'w': 1.0, 'fade_ms': round(min(fade, length / 2) * 1000)}
        self.attach_layers(entry, overlay, False)
        if (overlay.get('pin') or {}).get('fit') == 'corners':
            # A title pinned to a surface fills it: its picture is cut to the text, not the whole frame.
            self.assets[key]['trim'] = True
        self.overlays.append(overlay)
        return key

    def layer_fit(self, name, requested):
        """How a pin follows its track: as asked, else corners for a region track and follow for a point track."""
        if requested:
            return requested
        layer = project.load_json(self.map.root / 'spatial' / f'{name}.json', None)
        frames = layer.get('frames') if isinstance(layer, dict) else None
        shapes = [frame for frame in frames or [] if isinstance(frame, dict) and frame.get('point') is not None]
        return 'follow' if shapes else 'corners'

    def attach_layers(self, entry, overlay, still):
        """Add pin and behind (references/spatial.md) to an image overlay, and remember each use for check."""
        mods = entry['mods']
        if 'pin' in mods:
            name, requested = mods['pin']
            fit = self.layer_fit(name, requested)
            overlay['pin'] = {'layer': f'spatial/{name}.json', 'fit': fit}
            if fit == 'follow' and still:
                overlay['pin']['offset'] = [0, 0]
                overlay['w'] = 0.25
            self.layer_uses.append({'line': entry['line'], 'role': 'pin', 'name': name, 'from': overlay['from'],
                                    'to': overlay['to']})
        if 'behind' in mods:
            overlay['behind'] = {'layer': f"spatial/{mods['behind']}.json"}
            self.layer_uses.append({'line': entry['line'], 'role': 'behind', 'name': mods['behind'],
                                    'from': overlay['from'], 'to': overlay['to']})

    def over_span(self, entry, built, seconds):
        """Where a timed ~ overlay (a blur, a pinned still) sits over its line: (start, end), or None after an
        error. It starts with the line or +N into it and is trimmed to the line's end."""
        start = built['start'] + entry['mods'].get('offset', 0.0)
        if start >= built['end'] - 1e-6:
            self.problems.error(entry['line'], f'this {entry["kind"]} starts at or after the end of its line '
                                f'({fmt(built["end"])})', 'reduce its +offset')
            return None
        end = built['end'] if seconds is None else start + seconds
        if end > built['end'] + 1e-6:
            self.problems.note(entry['line'], f'the {entry["kind"]} runs {end - built["end"]:.2f} s past its line; '
                               'it is trimmed')
            end = built['end']
        return start, end

    def add_blur(self, entry, parent, built):
        """~ blur NAME: a blur overlay over the region a layer follows, for the line or its seconds."""
        span = self.over_span(entry, built, entry['seconds'])
        if span is None:
            return
        start, end = span
        self.overlays.append({'kind': 'blur', 'region': {'layer': f"spatial/{entry['layer']}.json"},
                              'from': round(start, 6), 'to': round(end, 6)})
        self.layer_uses.append({'line': entry['line'], 'role': 'blur', 'name': entry['layer'], 'from': start,
                                'to': end})
        self.lines.append(self.record(entry, 'blur', start, end, over=parent['line'], layer=entry['layer']))

    def add_still_overlay(self, entry, parent, built):
        """~ still ALIAS SECONDS pin NAME | behind NAME: an image drawn over the line's picture (not a cutaway)."""
        if not self.map.is_image(entry['alias']):
            self.problems.error(entry['line'], f'pin and behind draw an image; {entry["alias"]} is a video',
                                'use a still image source (map.py add FILE --role still)')
            return
        span = self.over_span(entry, built, entry['seconds'])
        if span is None:
            return
        start, end = span
        overlay = {'kind': 'image', 'src': entry['alias'], 'from': round(start, 6), 'to': round(end, 6), 'x': 0,
                   'y': 0, 'w': 1.0, 'fade_ms': round(min(TITLE_FADE, (end - start) / 2) * 1000)}
        self.attach_layers(entry, overlay, True)
        self.overlays.append(overlay)
        self.lines.append(self.record(entry, 'still', start, end, over=parent['line'], overlay=True))

    def add_moving_overlay(self, entry, parent, built):
        """~ over ALIAS [SECONDS]: a video with transparency drawn over the line's picture, full frame, frame for frame
        at the film's rate (its first frame on the overlay's first frame), for its own length or the given seconds.
        A PNG with transparency is drawn the same way, for the given seconds or the rest of the line."""
        alias = entry['alias']
        graphic = entry.get('graphic') or {}
        self.warn_graphic_size(entry, graphic.get('size'))
        if self.map.is_image(alias):
            span = self.over_span(entry, built, entry['seconds'])
            if span is None:
                return
            start, end = span
            fade = float(entry['mods'].get('fade', TITLE_FADE))
            self.overlays.append({'kind': 'image', 'src': alias, 'from': round(start, 6), 'to': round(end, 6),
                                  'x': 0, 'y': 0, 'w': 1.0, 'fade_ms': round(min(fade, (end - start) / 2) * 1000)})
            self.lines.append(self.record(entry, 'still', start, end, over=parent['line'], overlay=True))
            return
        rate = graphic.get('rate') or self.map.fps(alias)
        if rate is None or rate != self.rate:
            self.problems.error(entry['line'], f'{alias} runs at {rate or "an unknown rate"} fps and the film at '
                                f'{self.rate}', f'render the graphic at {self.rate} fps, so each of its frames is one '
                                'of the film\'s')
            return
        length = self.map.duration(alias)
        seconds = length if entry['seconds'] is None else min(entry['seconds'], length or entry['seconds'])
        span = self.over_span(entry, built, seconds)
        if span is None:
            return
        start, end = span
        fade = float(entry['mods'].get('fade', 0.0))
        self.overlays.append({'kind': 'video', 'src': alias, 'from': round(start, 6), 'to': round(end, 6), 'x': 0,
                              'y': 0, 'w': 1.0, 'fade_ms': round(min(fade, (end - start) / 2) * 1000)})
        self.lines.append(self.record(entry, 'still', start, end, over=parent['line'], overlay=True, moving=True))

    def warn_graphic_size(self, entry, size):
        """~ over draws its graphic full frame, scaled to the film's width: say so when that reshapes or enlarges it."""
        film = tuple(self.settings['size'])
        if not size or tuple(size) == film:
            return
        reshaped = abs(size[0] * film[1] - size[1] * film[0]) > 0.01 * size[0] * film[1]
        if reshaped or size[0] < film[0]:
            self.problems.warn(entry['line'], f'{entry["alias"]} is {size[0]}x{size[1]} and the film '
                               f"{film[0]}x{film[1]}; ~ over draws it full frame, scaled to the film's width",
                               f'export it at {film[0]}x{film[1]}, the graphic where it should sit on a clear '
                               'background')

    def flush_pending(self, start):
        """Title and music lines written before this line start where it starts."""
        for entry in self.pending:
            if not entry['bad']:
                self.place_layer(entry, start, None)
        self.pending = []

    def place_layer(self, entry, anchor, parent_line):
        """Queue a title or music line at an anchor time (with its +offset or at time)."""
        mods = entry['mods']
        start = mods['at'] if 'at' in mods else anchor + mods.get('offset', 0.0)
        entry['placed'] = start
        entry['parent_line'] = parent_line
        self.layers.append(entry)

    def finish_layers(self, total):
        """Place titles and music now that the film's length is known."""
        for entry in self.layers:
            start = entry['placed']
            if start >= total - 1e-6:
                self.problems.error(entry['line'], f'this {entry["kind"]} starts at {fmt(start)}, at or after the '
                                    f'film\'s end ({fmt(total)})', 'move it earlier or reduce its offset')
                continue
            extra = {'over': entry['parent_line']} if entry['parent_line'] else {}
            if entry['kind'] == 'title':
                length = min(entry['seconds'], total - start)
                if length < entry['seconds'] - 1e-6:
                    self.problems.warn(entry['line'], f'the title is cut short by the film\'s end '
                                       f'({length:.2f} of {entry["seconds"]:g} s)')
                self.add_title(entry, start, length, 'lower')
                self.lines.append(self.record(entry, 'title', start, start + length,
                                              position=entry['mods'].get('position', 'lower'), **extra))
            else:
                self.add_music(entry, start, total, extra)

    def add_music(self, entry, start, total, extra):
        """A music line as an audio item with gain and fades, stopped at the film's end."""
        mods = entry['mods']
        length = min(entry['end'] - entry['start'], total - start)
        if length < entry['end'] - entry['start'] - 0.01:
            self.problems.note(entry['line'], f'music trimmed at the film\'s end ({length:.2f} s of '
                               f'{entry["end"] - entry["start"]:.2f} s)')
        fade = mods.get('fade', self.settings['music_fade'])
        item = {'track': 'music', 'src': entry['alias'], 'in': entry['start'], 'out': round(entry['start'] + length, 6),
                'at': round(start, 6), 'gain_db': mods.get('gain', self.settings['music_gain']),
                'fade_ms': round(min(fade, length / 2) * 1000)}
        self.audio.append(item)
        self.spans[id(item)] = (start, start + length)
        self.lines.append(self.record(entry, 'music', start, start + length,
                                      gain_db=mods.get('gain', self.settings['music_gain']), **extra))

    def build_over(self, over, parent, built):
        """A ~ line over a timed line: a cutaway or still covering its picture, or a title or music line."""
        if over['kind'] in ('title', 'music'):
            self.place_layer(over, built['start'], parent['line'])
            return
        if over['kind'] == 'blur':
            self.add_blur(over, parent, built)
            return
        if over['kind'] == 'still' and {'pin', 'behind'} & set(over['mods']):
            self.add_still_overlay(over, parent, built)
            return
        if over['kind'] == 'over':
            self.add_moving_overlay(over, parent, built)
            return
        if over.get('sync'):
            self.add_synced(over, parent, built)
            return
        line = over['line']
        cursor = built['spans'][-1][1] if built['spans'] else built['start']
        start = built['start'] + over['mods']['offset'] if 'offset' in over['mods'] else cursor
        if built['spans'] and start < built['spans'][-1][1] - 1e-6:
            self.problems.error(line, 'this cutaway starts before the previous one ends',
                                'remove its +offset, or make it larger')
            return
        if start >= built['end'] - 1e-6:
            self.problems.error(line, f'this cutaway starts at or after the end of its line ({fmt(built["end"])})',
                                'reduce its +offset')
            return
        if over['kind'] == 'still':
            speed = 1.0
            length = over['seconds']
            key, s0, grid, limit = self.still_key(over), 0.0, (self.rate, 0.0), None
        else:
            speed = over['mods'].get('speed', 1.0)
            length = (over['end'] - over['start']) / speed
            key, s0, grid, limit = over['alias'], over['start'], self.grid(over['alias']), \
                self.map.picture_end(over['alias'])
        end = start + length
        if end > built['end'] + 1e-6:
            excess = end - built['end']
            report = self.problems.warn if excess > 0.5 else self.problems.note
            report(line, f'the cutaway runs {excess:.2f} s past its line; it is trimmed')
            end = built['end']
        join = self.join_of(over)
        seg = segment(start, end, key, s0, speed, join, framing(over, self.settings), grid, limit, line)
        built['spans'].append((start, end, seg))
        if 'sound' in over['mods'] and over['kind'] != 'still':
            item = {'track': 'nat', 'src': over['alias'], 'in': over['start'],
                    'out': round(over['start'] + (end - start) * speed, 6), 'at': round(start, 6), 'fade_ms': 15,
                    'gain_db': over['mods']['sound']}
            self.audio.append(item)
            self.spans[id(item)] = (start, end)
        kind = 'cutaway'
        record = self.record(over, kind, start, end, over=parent['line'])
        if over['kind'] == 'still':
            record['still'] = True
        self.lines.append(record)

    def add_synced(self, over, parent, built):
        """~ ALIAS sync: another camera's picture of the same moment over the line above, one stretch per piece of the
        line, so a cut inside the line cuts this picture too and every frame stays at the offset. It takes the place of
        a cutaway: it starts with the line, where the previous one ended, or +N in, and lasts the seconds given or the
        rest of the line."""
        line, alias = over['line'], over['alias']
        if parent['kind'] not in ('spoken', 'picture'):
            self.problems.error(line, f'~ {alias} sync needs a spoken or picture line above it to take its moment '
                                f'from; a {parent["kind"]} has no source clock',
                                'put it under a spoken or picture line, or write a cutaway with its own range')
            return
        reason = self.map.lineup_problem(parent['alias'], alias)
        if reason:
            self.problems.error(line, f"{alias} and {parent['alias']} are not lined up: {reason}",
                                lineup_suggestion(alias))
            return
        cursor = built['spans'][-1][1] if built['spans'] else built['start']
        start = built['start'] + over['mods']['offset'] if 'offset' in over['mods'] else cursor
        if built['spans'] and start < built['spans'][-1][1] - 1e-6:
            self.problems.error(line, 'this cutaway starts before the previous one ends',
                                'remove its +offset, or make it larger')
            return
        if start >= built['end'] - 1e-6:
            self.problems.error(line, f'this cutaway starts at or after the end of its line ({fmt(built["end"])})',
                                'reduce its +offset')
            return
        end = built['end'] if over['seconds'] is None else start + over['seconds']
        if end > built['end'] + 1e-6:
            report = self.problems.warn if end - built['end'] > 0.5 else self.problems.note
            report(line, f'the cutaway runs {end - built["end"]:.2f} s past its line; it is trimmed')
            end = built['end']
        lineup = self.map.lineup()
        stop = self.map.picture_end(alias)
        frame = framing(over, self.settings)
        join = self.join_of(over)
        made = []
        for piece in built['pieces']:
            low, high = max(start, piece['at']), min(end, piece['end'])
            if high <= low + 1e-9:
                continue
            speed = piece['speed']
            moment = piece['clock_in'] + (low - piece['at']) * speed
            first = lineup.map_time(piece['clock_alias'], alias, moment)
            last = first + (high - low) * speed
            half_frame = 0.5 / float(self.grid(alias)[0])
            if first < -half_frame or (stop and last > stop + RANGE_SLACK):
                begin = lineup.map_time(alias, piece['clock_alias'], 0.0)
                finish = lineup.map_time(alias, piece['clock_alias'], stop) if stop else None
                covers = (f'{fmt(max(0.0, begin))}-{fmt(finish)}' if finish is not None
                          else f'from {fmt(max(0.0, begin))}')
                self.problems.error(line, f"{alias} has no picture for this moment ({fmt(moment)} of "
                                    f"{piece['clock_alias']}): on {piece['clock_alias']}'s clock it runs {covers}",
                                    'start it later with +N, end it sooner with SECONDS, or show another camera')
                return
            seg = segment(low, high, alias, max(0.0, first), speed, None if made else join, frame, self.grid(alias),
                          stop, line)
            seg['synced'] = True
            made.append((low, high, seg))
        if not made:
            return
        made[-1][2]['return_join'] = join
        built['spans'].extend(made)
        for low, high, seg in made:
            self.lines.append(self.record(over, 'cutaway', low, high, over=parent['line'], sync=True,
                                          range=[round(seg['s0'], 4),
                                                 round(seg['s0'] + (high - low) * seg['speed'], 4)]))
        self.say_drift(alias, line)

    def carry_sound(self, total):
        """Carry sound across the joins between lines: a line's tail, the next line's lead, and the sound of a
        dissolve. Only the extra sound outside the kept words moves; every kept word stays where it was."""
        if not self.line_pieces:
            return
        last, first = self.line_pieces[-1][-1], self.line_pieces[0][0]
        if last['entry']['mods'].get('tail'):
            self.problems.warn(last['line'], 'the last line\'s tail has nothing after it to run under; ignored',
                               'use fade out 1.0 to end the film\'s sound')
        if first['entry']['mods'].get('lead'):
            self.problems.warn(first['line'], 'the first line\'s lead has nothing before it to start under; ignored',
                               'use fade in 1.0 to start the film\'s sound')
        for before, after in zip(self.line_pieces, self.line_pieces[1:]):
            out_piece, in_piece = before[-1], after[0]
            tail = out_piece['entry']['mods'].get('tail')
            lead = in_piece['entry']['mods'].get('lead')
            join = self.join_of(in_piece['entry'])
            dissolve = join[1] if join and join[0] == 'dissolve' else None
            if dissolve and (tail or lead):
                self.problems.error(in_piece['line'], 'this join has a dissolve and a tail or lead, and both would '
                                    'shape its sound',
                                    'keep the dissolve (it crossfades the sound), or the tail and lead')
                continue
            if in_piece['continuous'] or same_passage(out_piece, in_piece):
                if tail or lead:
                    self.problems.note(in_piece['line'], 'this line continues the line above in the same source, so '
                                       'there is no join for tail or lead to carry')
                continue
            if tail:
                self.carry_tail(out_piece, in_piece, tail, total)
            if lead:
                self.carry_lead(out_piece, in_piece, lead)
            if dissolve:
                self.carry_dissolve(out_piece, in_piece, dissolve, total)
        if any(piece['entry'].get('section') == 'Tighten (declared jump cuts)'
               for pieces in self.line_pieces for piece in pieces):
            load_sibling('tighten').carry_crossfades(self, total)

    def sound_after(self, piece):
        """Seconds of source sound after a piece's out point (unbounded when the source length is unknown)."""
        duration = self.map.sound_end(piece['alias'])
        return max(0.0, duration - piece['out']) if duration else float('inf')

    def carry_tail(self, out_piece, in_piece, seconds, total):
        """tail N: the line's own sound runs on N seconds past its end, fading out under the next line."""
        line, alias = out_piece['line'], out_piece['alias']
        limits = [(self.sound_after(out_piece), f'{alias} has no more sound after {fmt(out_piece["out"])}'),
                  (total - out_piece['end'], 'the film ends')]
        if in_piece['alias'] == alias and in_piece['item'] is not None and in_piece['in'] >= out_piece['out'] - 1e-6:
            limits.append((in_piece['in'] - out_piece['out'], f'the next line plays {alias} from '
                           f'{fmt(in_piece["in"])}, and the tail would play it twice'))
        length, why = min(limits + [(seconds, '')], key=lambda limit: limit[0])
        if length < seconds - 0.005:
            self.problems.warn(line, f'tail shortened to {max(0.0, length):.2f} s of {seconds:g} s: {why}',
                               'shorten the tail, or end the range earlier so more sound follows it')
        if length < 0.02:
            return
        item = out_piece['item']
        item['out'] = round(item['out'] + length, 6)
        item['fade_out_ms'] = round(length * 1000, 3)
        self.spans[id(item)] = (self.spans[id(item)][0], out_piece['end'] + length)
        out_piece['carry']['tail'] = round(length, 4)
        out_piece['record'].setdefault('sound_carry', {})['tail'] = round(length, 4)
        self.report_carried_words(out_piece, out_piece['out'], out_piece['out'] + length, 'tail')

    def carry_lead(self, out_piece, in_piece, seconds):
        """lead N: the line's own sound starts N seconds before its picture, fading in under the line before."""
        line, alias = in_piece['line'], in_piece['alias']
        limits = [(in_piece['in'], f'{alias} has only {in_piece["in"]:.2f} s of sound before {fmt(in_piece["in"])}'),
                  (in_piece['at'], 'the film starts')]
        if out_piece['alias'] == alias and out_piece['item'] is not None and out_piece['out'] <= in_piece['in'] + 1e-6:
            limits.append((in_piece['in'] - out_piece['out'], f'the line before plays {alias} up to '
                           f'{fmt(out_piece["out"])}, and the lead would play it twice'))
        length, why = min(limits + [(seconds, '')], key=lambda limit: limit[0])
        if length < seconds - 0.005:
            self.problems.warn(line, f'lead shortened to {max(0.0, length):.2f} s of {seconds:g} s: {why}',
                               'shorten the lead, or start the range later so more sound comes before it')
        if length < 0.02:
            return
        item = in_piece['item']
        item['in'] = round(item['in'] - length, 6)
        item['at'] = round(item['at'] - length, 6)
        item['fade_in_ms'] = round(length * 1000, 3)
        self.spans[id(item)] = (in_piece['at'] - length, self.spans[id(item)][1])
        in_piece['carry']['lead'] = round(length, 4)
        in_piece['record'].setdefault('sound_carry', {})['lead'] = round(length, 4)
        self.report_carried_words(in_piece, in_piece['in'] - length, in_piece['in'], 'lead')

    def carry_dissolve(self, out_piece, in_piece, seconds, total):
        """dissolve N also crossfades the two lines' sound over N seconds (equal power). The crossfade sits as close
        to the picture dissolve as it can while both lines' kept words stay at full level; with less room it is
        shorter, and the report says so."""
        a, b = out_piece['item'], in_piece['item']
        if a is None and b is None:
            return
        join_at, requested = in_piece['at'], seconds
        low, high = 0.0, total  # the crossfade [start, start + length] must lie inside these
        reasons = []
        if a is not None:
            if out_piece['last_word'] is not None:
                low = max(low, out_piece['last_word'] + WORD_ROOM)
            after = self.sound_after(out_piece) if out_piece['speed'] == 1 else 0.0
            high = min(high, join_at + after)
            low = max(low, out_piece['at'] + 0.02)
            if after < seconds:
                reasons.append(f'{out_piece["alias"]} has {after:.2f} s of sound after {fmt(out_piece["out"])}')
        if b is not None:
            if in_piece['first_word'] is not None:
                high = min(high, in_piece['first_word'] - WORD_ROOM)
            before = in_piece['in'] if in_piece['speed'] == 1 else 0.0
            low = max(low, join_at - before)
            high = min(high, in_piece['end'] - 0.02)
            if before < seconds:
                reasons.append(f'{in_piece["alias"]} has {before:.2f} s of sound before {fmt(in_piece["in"])}')
        if a is not None and b is not None and out_piece['alias'] == in_piece['alias'] \
                and in_piece['in'] >= out_piece['out']:
            gap = in_piece['in'] - out_piece['out']
            if gap < seconds:
                reasons.append('both sides play the same source, so the crossfade may not repeat the '
                               f'{gap:.2f} s between them')
            seconds = min(seconds, gap)
        if out_piece['last_word'] is not None or in_piece['first_word'] is not None:
            reasons.append(f'the kept words leave {max(0.0, high - low):.2f} s between them')
        length = min(seconds, high - low)
        line = in_piece['line']
        if length < BRIDGE_MIN:
            self.problems.warn(line, f'no room for the dissolve\'s sound crossfade ({max(0.0, length):.2f} s): '
                               + '; '.join(reasons), 'the sound cuts at the join; leave more pause around the words, '
                               'or carry the sound with tail or lead instead')
            if length < 0.02:
                return
        elif length < requested - 0.005:
            self.problems.note(line, f'the dissolve\'s sound crossfade is {length:.2f} s: ' + '; '.join(reasons))
        start = min(max(join_at, low), high - length)
        end = start + length
        if a is not None:
            a['out'] = round(a['out'] + end - join_at, 6)
            a['fade_out_ms'] = round(length * 1000, 3)
            a['fade_out_curve'] = 'qsin'
            self.spans[id(a)] = (self.spans[id(a)][0], end)
            if end > join_at:
                self.report_carried_words(out_piece, out_piece['out'], out_piece['out'] + end - join_at, 'dissolve')
        if b is not None:
            b['in'] = round(b['in'] - (join_at - start), 6)
            b['at'] = round(start, 6)
            b['fade_in_ms'] = round(length * 1000, 3)
            b['fade_in_curve'] = 'qsin'
            self.spans[id(b)] = (start, self.spans[id(b)][1])
            if start < join_at:
                self.report_carried_words(in_piece, in_piece['in'] - (join_at - start), in_piece['in'], 'dissolve')
        in_piece['carry']['dissolve'] = [round(start, 4), round(end, 4)]
        in_piece['record'].setdefault('sound_carry', {})['crossfade'] = [round(start, 4), round(end, 4)]

    def report_carried_words(self, piece, low, high, what):
        """Say when carried sound holds transcript words the film does not keep (heard, but never captioned)."""
        # Sound from a lined-up mic is heard against the words of the line's own source, on that source's clock.
        words = self.map.words(piece['clock_alias'] or piece['alias']) or []
        shift = piece['in'] - piece['clock_in'] if piece['in'] is not None else 0.0
        heard = [word['text'] for word in words if low - shift < (word['start'] + word['end']) / 2 < high - shift]
        if heard:
            shown = ' '.join(heard[:6]) + (' ...' if len(heard) > 6 else '')
            self.problems.warn(piece['line'], f'the {what} carries {len(heard)} word(s) of {piece["alias"]} that the '
                               f'film does not keep or caption: "{shown}"',
                               f'listen to it; shorten the {what} to stop before them, or keep them in the line')

    def lay_cutaways(self, built):
        """Replace the parts of a line's picture that its cutaways cover; joins return out of a cutaway."""
        if not built['spans']:
            return
        pieces = []
        for seg in built['segments']:
            parts = [(seg['t0'], seg['t1'])]
            for c0, c1, _ in built['spans']:
                parts = [piece for a, b in parts for piece in ((a, min(b, c0)), (max(a, c1), b)) if piece[1] > piece[0]]
            for a, b in parts:
                piece = dict(seg, t0=a, t1=b, s0=seg['s0'] + (a - seg['t0']) * seg['speed'])
                if a > seg['t0'] + 1e-9:
                    returning = [span for span in built['spans'] if abs(span[1] - a) < 1e-6]
                    piece['join'] = (returning[0][2].get('return_join', returning[0][2]['join'])
                                     if returning else None)
                pieces.append(piece)
        pieces.extend(span[2] for span in built['spans'])
        pieces.sort(key=lambda item: item['t0'])
        frame = 0.5 / float(self.rate)
        merged = []
        for piece in pieces:
            if piece['t1'] - piece['t0'] < frame and merged:
                merged[-1]['t1'] = piece['t1']
                continue
            merged.append(piece)
        if len(merged) > 1 and merged[0]['t1'] - merged[0]['t0'] < frame:
            merged[1] = dict(merged[1], t0=merged[0]['t0'],
                             s0=merged[1]['s0'] - (merged[1]['t0'] - merged[0]['t0']) * merged[1]['speed'],
                             join=merged[0]['join'])
            merged.pop(0)
        built['segments'] = merged
        record = built['record']
        if record.get('jump_cuts'):
            # A camera lined up with the line jumps with it, so only a cutaway with its own range hides a jump.
            hiding = [(c0, c1) for c0, c1, seg in built['spans'] if not seg.get('synced')]
            covered = [t for t in record['jump_cuts'] if any(c0 - 1e-3 <= t <= c1 + 1e-3 for c0, c1 in hiding)]
            record['jump_cuts'] = [t for t in record['jump_cuts'] if t not in covered]


# ----------------------------------------------------------------------------------------------- joins

def same_passage(before, after):
    """Whether two pieces play one source continuously (no join to hear or carry)."""
    return (before['alias'] is not None and before['alias'] == after['alias'] and before['speed'] == after['speed']
            and abs(after['in'] - before['out']) < 0.02)


def band_shape(power, freqs):
    """Octave-band shape of a power spectrum: each band's share of the total in dB, and the spectral centroid."""
    usable = freqs >= TONE_BANDS[0]
    total = float(power[usable].sum())
    if total <= 0:
        return [-120.0] * (len(TONE_BANDS) - 1), None
    centroid = float((power[usable] * freqs[usable]).sum() / total)
    shape = [10 * math.log10(float(power[(freqs >= low) & (freqs < high)].sum()) / total + 1e-12)
             for low, high in zip(TONE_BANDS, TONE_BANDS[1:])]
    return shape, centroid


def low_band_level(frames, rate):
    """Median 20-100 Hz RMS in speech-free frames, with a Hann energy correction."""
    import numpy as np
    hop = len(frames[0])
    taper = np.hanning(hop)
    freqs = np.fft.rfftfreq(hop, 1.0 / rate)
    bins = (freqs >= LOW_BAND[0]) & (freqs < LOW_BAND[1])
    scale = 2 / (hop * float((taper ** 2).sum()))
    levels = []
    for frame in frames:
        spectrum = np.abs(np.fft.rfft(frame * taper)) ** 2
        energy = float(spectrum[bins].sum()) * scale
        levels.append(10 * math.log10(energy + 1e-12))
    return float(np.median(levels))


def sound_facts(samples, rate, at_start, speech):
    """What one side of a join sounds like, from float samples running away from the join (`at_start`: the window
    starts at the join). level_db is the level over the JOIN_WINDOW seconds next to the join and edge_db over the
    JOIN_EDGE seconds right at it. The bed is the sound where nobody speaks: the median level of the 50 ms frames
    that `speech` (a mask, one flag per sample) leaves free, with their low-frequency level, shape and centroid.
    near_low_db and near_bed_db use the same speech-free frames within JOIN_WINDOW. Speech against a pause makes
    plain levels jump at almost every interview join; the bed does not."""
    import numpy as np
    if len(samples) < rate * 0.05:
        return None
    near = int(JOIN_WINDOW * rate)
    edge = int(JOIN_EDGE * rate)
    window = samples[:near] if at_start else samples[-near:]
    edge_samples = samples[:edge] if at_start else samples[-edge:]
    facts = {'level_db': 10 * math.log10(float(np.mean(window ** 2)) + 1e-12),
             'edge_db': 10 * math.log10(float(np.mean(edge_samples ** 2)) + 1e-12)}
    hop = int(BED_FRAME * rate)
    frames = [samples[i:i + hop] for i in range(0, len(samples) - hop + 1, hop) if not speech[i:i + hop].any()]
    facts['bed_frames'] = len(frames)
    if len(frames) >= BED_MIN_FRAMES:
        levels = [10 * math.log10(float(np.mean(frame ** 2)) + 1e-12) for frame in frames]
        facts['bed_db'] = float(np.median(levels))
        taper = np.hanning(hop)
        power = np.mean([np.abs(np.fft.rfft(frame * taper)) ** 2 for frame in frames], axis=0)
        freqs = np.fft.rfftfreq(hop, 1.0 / rate)
        facts['low_db'] = low_band_level(frames, rate)
        facts['shape'], centroid = band_shape(power, freqs)
        facts['centroid_hz'] = round(centroid) if centroid else None
    near_speech = speech[:near] if at_start else speech[-near:]
    near_frames = [window[i:i + hop] for i in range(0, len(window) - hop + 1, hop)
                   if not near_speech[i:i + hop].any()]
    if len(near_frames) >= BED_MIN_FRAMES:
        facts['near_low_db'] = low_band_level(near_frames, rate)
        levels = [10 * math.log10(float(np.mean(frame ** 2)) + 1e-12) for frame in near_frames]
        facts['near_bed_db'] = float(np.median(levels))
    return facts


def tone_change(first, second):
    """How far two sounds' spectral shapes differ: the mean dB difference over the octave bands either one uses."""
    used = [(a, b) for a, b in zip(first, second) if max(a, b) > -30]
    return round(sum(abs(a - b) for a, b in used) / len(used), 1) if used else 0.0


class SoundMeter:
    """Source sound beside each join for the join report, decoded with FFmpeg at 16 kHz mono, with the source's
    speech masked out: the map's voice-activity segments (map/<alias>/audio.json speech_activity), else its
    transcript words, else nothing (all of it counts as bed, and the join says so)."""

    def __init__(self, source_map, ffmpeg):
        self.map = source_map
        self.ffmpeg = ffmpeg
        self.cache = {}
        self.speech_cache = {}
        self.transcribe = None

    def speech(self, alias):
        """(source-time speech spans, how they were found) for a source."""
        if alias not in self.speech_cache:
            audio = project.load_json(self.map.root / 'map' / alias / 'audio.json', {}) or {}
            activity = audio.get('speech_activity') if isinstance(audio, dict) else None
            rows = activity.get('segments') if isinstance(activity, dict) else None
            if isinstance(rows, list) and rows:
                spans = [(float(row[0]), float(row[1])) for row in rows if isinstance(row, (list, tuple))
                         and len(row) >= 2]
                found = (spans, 'voice activity')
            elif self.map.words(alias):
                found = ([(word['start'] - SPEECH_PAD, word['end'] + SPEECH_PAD) for word in self.map.words(alias)],
                         'transcript words')
            else:
                found = ([], 'none')
            self.speech_cache[alias] = found
        return self.speech_cache[alias]

    def facts(self, alias, start, end, at_start, gain):
        """sound_facts for a source window with a line's gain applied, or None when it cannot be decoded."""
        start = max(0.0, start)
        if end - start < 0.05:
            return None
        key = (alias, round(start, 4), round(end, 4), at_start)
        if key not in self.cache:
            self.cache[key] = self.decode(alias, start, end, at_start)
        found = self.cache[key]
        if found is None:
            return None
        found = dict(found)
        for name in ('level_db', 'edge_db', 'bed_db', 'low_db', 'near_low_db', 'near_bed_db'):
            if name in found:
                found[name] = round(max(found[name] + gain, -120.0), 1)
        return found

    def decode(self, alias, start, end, at_start):
        """Decode, mask and measure one window."""
        import numpy as np
        if self.transcribe is None:
            self.transcribe = load_sibling('transcribe')
        try:
            stream = (self.map.sources[alias].get('audio') or {}).get('index')
            command = self.transcribe.audio_window_command(self.map.path(alias), stream, start, end, rate=JOIN_RATE,
                                                           sample_format='s16le', ffmpeg=self.ffmpeg)
            result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        except (subprocess.TimeoutExpired, ValueError, OSError):
            return None
        if result.returncode or not result.stdout:
            return None
        samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float64) / 32768.0
        mask = np.zeros(len(samples), bool)
        spans, method = self.speech(alias)
        for low, high in spans:
            if high > start and low < end:
                mask[max(0, int((low - start) * JOIN_RATE)):max(0, int((high - start) * JOIN_RATE))] = True
        facts = sound_facts(samples, JOIN_RATE, at_start, mask)
        if facts is not None:
            facts['speech_mask'] = method
        return facts


def shown_source(seg, assets):
    """What a segment shows from a source: (alias, first source time, last source time), a frozen frame being one
    source time; None for generated pictures (backgrounds, cards, images)."""
    asset = assets.get(seg['key'])
    if asset is not None:
        return (asset['alias'], asset['time'], asset['time']) if asset['kind'] == 'freeze' else None
    if seg['key'].startswith('gen-'):
        return None
    return seg['key'], seg['s0'], seg['s0'] + (seg['t1'] - seg['t0']) * seg['speed']


def same_picture(previous, seg, assets, frame):
    """True when seg carries on the picture previous shows: one source running on, or a frame of it frozen and
    then running on again from that frame (a freeze is one picture event with the shot it holds, not a cut)."""
    if seg['join']:
        return False
    if previous['key'] == seg['key'] and seg['key'] == 'gen-background':
        return True
    before, after = shown_source(previous, assets), shown_source(seg, assets)
    if before is None or after is None or before[0] != after[0]:
        return False
    moving = previous['key'] not in assets and seg['key'] not in assets
    if moving and previous['speed'] != seg['speed']:
        return False
    return abs(after[1] - before[2]) < frame


def picture_changes(segments, source_map, assets=None):
    """Every moment the picture changes on the edit clock: edits between segments (not a source continuing, a hold,
    nor a freeze of a source that then runs on from the frozen frame) and the sources' own shot changes inside a
    segment (map/<alias>/shots.json)."""
    assets = assets or {}
    changes = []
    previous = None
    for seg in segments:
        frame = 1.5 / float(seg['grid'][0])
        if previous is not None and not seg.get('hold_previous') and not same_picture(previous, seg, assets, frame):
            changes.append({'at': round(seg['t0'], 4), 'line': seg['line'], 'kind': 'edit'})
        if seg['key'] in source_map.sources:
            run_end = seg['s0'] + (seg['t1'] - seg['t0']) * seg['speed']
            for moment in source_map.shot_starts(seg['key']):
                if seg['s0'] + frame < moment < run_end - frame:
                    changes.append({'at': round(seg['t0'] + (moment - seg['s0']) / seg['speed'], 4),
                                    'line': seg['line'], 'kind': 'source shot'})
        previous = seg
    return sorted(changes, key=lambda change: change['at'])


def is_montage(section):
    """A section whose name contains "montage" is cut fast on purpose."""
    return 'montage' in (section or '').lower()


def busy_stretches(changes, sections):
    """Stretches where BUSY_CHANGES or more picture changes fall within BUSY_SECONDS, outside montage sections."""
    counted = [change for change in changes if not is_montage(sections.get(change['line']))]
    stretches = []
    last = len(counted) - 1
    for first in range(len(counted)):
        end = first
        while end < last and counted[end + 1]['at'] - counted[first]['at'] <= BUSY_SECONDS + 1e-6:
            end += 1
        if end - first + 1 < BUSY_CHANGES:
            continue
        if stretches and first <= stretches[-1]['_last']:
            stretches[-1]['_last'] = end
        else:
            stretches.append({'_first': first, '_last': end})
    found = []
    for stretch in stretches:
        group = counted[stretch['_first']:stretch['_last'] + 1]
        times = [change['at'] for change in group]
        found.append({'start': times[0], 'end': times[-1], 'changes': len(group), 'line': group[0]['line'],
                      'shots': [round(b - a, 2) for a, b in zip(times, times[1:])]})
    return found


def shot_lengths(at, changes, total):
    """The lengths of the shot ending at a moment and the shot starting there."""
    times = [0.0] + [change['at'] for change in changes] + [total]
    before = max([t for t in times if t < at - 1e-3], default=0.0)
    after = min([t for t in times if t > at + 1e-3], default=total)
    return [round(at - before, 2), round(after - at, 2)]


def join_side(piece, meter, outgoing):
    """What one side of a join plays, measured in the source next to the join: up to BED_REACH seconds of the
    sound the film plays on that side (never past the piece's own range)."""
    side = {'line': piece['line'], 'source': piece['alias']}
    if piece['item'] is None:
        side['sound'] = False
        return side
    side['source_time'] = round(piece['out'] if outgoing else piece['in'], 4)
    if meter is None:
        return side
    if outgoing:
        end = piece['out']
        start = min(max(piece['in'], end - BED_REACH), end - 0.1)
    else:
        start = piece['in']
        end = max(min(piece['out'], start + BED_REACH), start + 0.1)
    facts = meter.facts(piece['alias'], start, end, not outgoing, piece['gain'])
    if facts is not None:
        side.update(facts)
        side['silent'] = facts['edge_db'] < SILENT_DB
    return side


def join_bridges(before, after, plan, at, carry_min=BRIDGE_MIN):
    """What carries sound across a join: tail, lead, a dissolve's crossfade, or other sound playing through it."""
    found = []
    if before['carry'].get('tail', 0) >= carry_min:
        found.append(f'tail {before["carry"]["tail"]:.2f} s')
    if after['carry'].get('lead', 0) >= carry_min:
        found.append(f'lead {after["carry"]["lead"]:.2f} s')
    crossfade = after['carry'].get('dissolve')
    if crossfade and crossfade[1] - crossfade[0] >= BRIDGE_MIN:
        found.append(f'dissolve {crossfade[1] - crossfade[0]:.2f} s')
    crossfade = after['carry'].get('tighten_crossfade')
    if crossfade and crossfade[1] - crossfade[0] >= BRIDGE_MIN - 1e-6:
        found.append(f'audio crossfade {crossfade[1] - crossfade[0]:.2f} s')
    own = {id(before['item']), id(after['item'])}
    names = {'music': 'music bed', 'nat': 'cutaway sound', 'dialogue': 'sound carried from another line'}
    for item in plan['audio']:
        if id(item) in own:
            continue
        start, end = plan['spans'].get(id(item), (item['at'], item['at'] + item['out'] - item['in']))
        if start <= at - BRIDGE_COVER and end >= at + BRIDGE_COVER:
            found.append(f'{names.get(item["track"], item["track"])} {item["src"]}')
    return found


def low_change_basis(join):
    """Which speech-free window has a meaningful low-end jump, if either does."""
    first, second = join['from'], join['to']
    if abs(join['low_jump_db']) >= LOW_JUMP_DB and max(first['low_db'], second['low_db']) >= LOW_MIN_DB:
        return 'background'
    if 'near_low_jump_db' not in join:
        return None
    low = (first['near_low_db'], second['near_low_db'])
    jump = abs(join['near_low_jump_db'])
    dominant = all(side['near_low_db'] >= side['near_bed_db'] - LOW_DOMINANT_WITHIN_DB
                   for side in (first, second))
    if max(low) >= LOW_MIN_DB and (jump >= LOW_JUMP_DB or (dominant and jump >= LOW_DOMINANT_JUMP_DB)):
        return 'near'
    return None


def describe_join(before, after, plan, meter, changes):
    """One join between two passages: both sides' sound, the change across it, what bridges it, the shots.

    A change is judged only when both sides sound at the join and both have a bed (sound where nobody speaks):
    the bed or the level next to the join changing by JUMP_DB or more, a low-end change, or the bed's spectral
    shape by TONE_DB or more. A side silent at the join is a pause; a side with too little sound between words has
    no bed, and its plain level mostly measures speech against a pause; neither is judged."""
    at = after['at']
    join = {'at': round(at, 4), 'line': after['line'], 'kind': 'cut' if before['line'] == after['line'] else 'line',
            'from': join_side(before, meter, True), 'to': join_side(after, meter, False),
            'bridged': join_bridges(before, after, plan, at), 'shots': shot_lengths(at, changes, plan['duration'])}
    first, second = join['from'], join['to']
    join['change'] = None
    found = []
    if 'level_db' in first and 'level_db' in second:
        join['jump_db'] = round(second['level_db'] - first['level_db'], 1)
        sounding = not first['silent'] and not second['silent']
        if 'bed_db' in first and 'bed_db' in second:
            join['bed_jump_db'] = round(second['bed_db'] - first['bed_db'], 1)
            join['tone_change_db'] = tone_change(first['shape'], second['shape'])
            join['low_jump_db'] = round(second['low_db'] - first['low_db'], 1)
            if 'near_low_db' in first and 'near_low_db' in second:
                join['near_low_jump_db'] = round(second['near_low_db'] - first['near_low_db'], 1)
                join['near_bed_jump_db'] = round(second['near_bed_db'] - first['near_bed_db'], 1)
            low_basis = low_change_basis(join)
            if low_basis:
                join['low_change_basis'] = low_basis
            if first['centroid_hz'] and second['centroid_hz']:
                join['centroid_ratio'] = round(max(first['centroid_hz'], second['centroid_hz'])
                                               / min(first['centroid_hz'], second['centroid_hz']), 2)
            if sounding:
                found = [name for name, over in (('background', abs(join['bed_jump_db']) >= JUMP_DB),
                                                 ('level', abs(join['jump_db']) >= JUMP_DB),
                                                 ('low end', bool(low_basis)),
                                                 ('tone', join['tone_change_db'] >= TONE_DB)) if over]
                join['change'] = ' and '.join(found) or None
        join['judged'] = ('yes' if sounding and 'bed_jump_db' in join else 'no: silence at the join' if not sounding
                          else 'no: too little sound between words to compare the background')
    for side in (first, second):
        side.pop('shape', None)
    if 'low end' in found:
        jump = join['near_low_jump_db'] if join['low_change_basis'] == 'near' else join['low_jump_db']
        minimum = LOW_BRIDGE_MIN if abs(jump) >= LOW_JUMP_DB else BRIDGE_MIN
        join['low_bridge_min_s'] = minimum
        join['low_bridged'] = join_bridges(before, after, plan, at, carry_min=minimum)
    abrupt = [name for name in found if not (join.get('low_bridged') if name == 'low end' else join['bridged'])]
    join['abrupt_change'] = ' and '.join(abrupt) or None
    join['abrupt'] = bool(abrupt)
    return join


def join_report(plan, entries, source_map, ffmpeg, problems):
    """Measure every join between two passages (a change of source, or a gap in one source) and the pace of the
    picture; warn about abrupt unbridged sound and busy cutting. Adds joins, picture_changes and busy_cutting to
    the plan."""
    sections = {entry['line']: entry['section'] for entry in entries}
    changes = picture_changes(plan['segments'], source_map, plan.get('assets'))
    meter = SoundMeter(source_map, ffmpeg) if ffmpeg else None
    pieces = [piece for line in plan['pieces'] for piece in line]
    joins = []
    for before, after in zip(pieces, pieces[1:]):
        if after['continuous'] or same_passage(before, after):
            continue
        joins.append(describe_join(before, after, plan, meter, changes))
    for join in joins:
        if not join['abrupt']:
            continue
        change = join['abrupt_change']
        what = (f'{join["bed_jump_db"]:+.0f} dB in the background' if 'background' in change else
                f'{join["jump_db"]:+.0f} dB' if 'level' in change or 'tone' in change else '')
        if 'low end' in change:
            low_jump = join['near_low_jump_db'] if join['low_change_basis'] == 'near' else join['low_jump_db']
            what += (', ' if what else '') + f'{low_jump:+.1f} dB in the low end'
        what += ', a different sound world' if 'tone' in change else ''
        what = what.lstrip(', ')
        carry = ('tail or lead of at least 0.5 s' if 'low end' in change
                 and join.get('low_bridge_min_s') == LOW_BRIDGE_MIN else 'tail or lead')
        if join['kind'] == 'cut':
            problems.warn(join['line'], f'the sound changes abruptly at {fmt(join["at"])} ({what}), at a cut inside '
                          'the line', f'split the line there and carry the sound across with {carry}, put a bed or a '
                          'cutaway with sound over it, lower the louder side with {sound -6dB}, or cut at another '
                          'pause or on a stronger beat')
        else:
            problems.warn(join['line'], f'the sound changes abruptly at {fmt(join["at"])} ({what})',
                          f'carry it across with {carry}, dissolve it, lower the louder side with {{sound -6dB}}, '
                          'put a bed under, or cut on a stronger beat')
    busy = busy_stretches(changes, sections)
    declared = []
    for stretch in busy:
        in_stretch = [change for change in changes if stretch['start'] - 1e-6 <= change['at'] <= stretch['end'] + 1e-6]
        if in_stretch and all(change['kind'] == 'edit'
                              and sections.get(change['line']) == 'Tighten (declared jump cuts)'
                              for change in in_stretch):
            declared.append(stretch)
            continue
        span = stretch['end'] - stretch['start']
        shots = ', '.join(f'{shot:.1f}' for shot in stretch['shots'])
        problems.warn(stretch['line'], f'{stretch["changes"]} picture changes in {span:.1f} s '
                      f'({fmt(stretch["start"])} to {fmt(stretch["end"])}; shots of {shots} s)',
                      'hold a shot long enough to read, drop one, or put these lines in a section whose name contains '
                      '"montage" if fast cutting is the point')
    if declared:
        problems.note(declared[0]['line'], f'{len(declared)} busy-cutting stretch(es) in declared talking-head '
                      'jump cuts', 'inspect the jumps and rhythm; a cutaway can hide a jump')
    plan['joins'] = joins
    plan['picture_changes'] = changes
    plan['busy_cutting'] = busy
    plan['joins_measured'] = meter is not None


def join_summary(plan):
    """check's text lines for the join report: every join between lines, and abrupt cuts inside a line."""
    joins = plan.get('joins') or []
    if not joins and not plan.get('picture_changes'):
        return []
    abrupt = sum(1 for join in joins if join['abrupt'])
    bridged = sum(1 for join in joins if join['bridged'])
    silent = sum(1 for join in joins if join['from'].get('silent') or join['to'].get('silent')
                 or join['from'].get('sound') is False or join['to'].get('sound') is False)
    head = f'joins: {len(joins)} between passages'
    if plan.get('joins_measured'):
        head += f'; {abrupt} abrupt, {bridged} with sound carried, {silent} into or out of silence'
    else:
        head += ' (sound not measured: no FFmpeg, or --no-audio)'
    shots = [b - a for a, b in zip([0.0] + [c['at'] for c in plan['picture_changes']],
                                   [c['at'] for c in plan['picture_changes']] + [plan['duration']])]
    rows = [head, f'picture: {len(plan["picture_changes"])} changes, shortest shot {min(shots):.1f} s, '
            f'{len(plan.get("busy_cutting") or [])} busy stretch(es)' if shots else 'picture: no changes']
    for join in joins:
        if join['kind'] == 'cut' and not join['abrupt']:
            continue
        rows.append('  ' + join_row(join))
    return rows


def join_row(join):
    """One join as a line of text."""
    first, second = join['from'], join['to']

    def level(side):
        if side.get('sound') is False:
            return 'no sound'
        return f'{side["level_db"]:.1f} dB' if 'level_db' in side else 'not measured'
    text = f'{fmt(join["at"])} line {first["line"]} > {second["line"]}: {level(first)} > {level(second)}'
    if 'jump_db' in join:
        text += f' ({join["jump_db"]:+.1f})'
    if 'bed_jump_db' in join:
        text += (f', background {first["bed_db"]:.1f} > {second["bed_db"]:.1f} ({join["bed_jump_db"]:+.1f}), '
                 f'low end {first["low_db"]:.1f} > {second["low_db"]:.1f} ({join["low_jump_db"]:+.1f}), '
                 f'tone {join["tone_change_db"]:.1f} dB')
    if 'near_low_jump_db' in join:
        text += (f', near-join low end {first["near_low_db"]:.1f} > {second["near_low_db"]:.1f} '
                 f'({join["near_low_jump_db"]:+.1f})')
    if first.get('silent') or second.get('silent'):
        text += ', silence at the join'
    elif 'jump_db' in join and 'bed_jump_db' not in join:
        text += ', no background between words to compare'
    text += f', shots {join["shots"][0]:.1f} | {join["shots"][1]:.1f} s'
    if join['bridged']:
        text += ', bridged by ' + ', '.join(join['bridged'])
        if 'low end' in (join.get('abrupt_change') or ''):
            text += ' (too short to bridge the large low-end change)'
    if join['abrupt']:
        text += ', ABRUPT (' + join['abrupt_change'] + ')'
    return text


# ----------------------------------------------------------------------------------------------- analysis

def load_project(target):
    """The project folder for a path (a folder or its film.md)."""
    folder = project.find_project(target)
    if folder is None:
        raise ValueError(f'no project folder at or above {target}')
    return folder


def pin_blocked_by_bad_line(pin, entries, source_map):
    """A failed spoken line cannot yet establish whether one of its transcript IDs was kept."""
    for entry in entries:
        if not entry.get('bad') or entry.get('kind') != 'spoken':
            continue
        alias = entry.get('alias')
        if alias not in source_map.sources:
            continue
        words = source_map.words(alias) or []
        for index in range_words(words, entry['start'], entry['end']):
            if words[index].get('id') == pin['word']:
                return True
    return False


SLIVER = 0.5


BACKWARD_S = 30.0
SPEECH_ROLES = ('interview', 'camera', 'mic')  # sources where consecutive lines read as one telling
FEED_WIDTH = 390
FEED_WORDS = re.compile(r'\b(phone|feed|scroll\w*|mobile|social|reels?|shorts|tiktok|instagram|stories)\b', re.I)


SENTENCE_END = ('.', '?', '!', '\u2026', '"', '\u201d')
SENTENCE_PAUSE = 1.0


BEAT_FILM = 0.5
BEAT_SOURCE = 1.0


def no_beat_after(plan, source_map, problems):
    """Name a line ending on a question or an exclamation that the cut answers with almost no pause, where the source
    took its time: the moment had a beat (a hesitation, a look) and the cut took it away. A teaser cut the false start
    and silence between "...freaked out by my robot hand?" and "Alright, fine.", leaving 0.33 s of the source's 3.3 s,
    and the person watching asked for "a tiny bit of time to breathe" there."""
    spoken = sorted((record for record in plan['lines'] if record.get('kind') == 'spoken'
                     and record.get('words') and isinstance(record['words'][0], dict)),
                    key=lambda record: record['start'])
    for before, after in zip(spoken, spoken[1:]):
        last, first = before['words'][-1], after['words'][0]
        if not str(last.get('text', '')).rstrip('"\'\u201d').endswith(('?', '!')):
            continue
        film_beat = float(first['start']) - float(last['end'])
        if film_beat >= BEAT_FILM or before.get('source') != after.get('source'):
            continue
        words = {word.get('id'): word for word in source_map.words(before.get('source')) or []}
        said, answered = words.get(last.get('id')), words.get(first.get('id'))
        if not said or not answered:
            continue
        source_beat = float(answered['start']) - float(said['end'])
        if source_beat < BEAT_SOURCE:
            continue
        problems.warn(after['line'], f'only {film_beat:.2f} s after "{last["text"]}" at {fmt(float(last["end"]))} '
                      f'before the next words, where the source took {source_beat:.1f} s',
                      'a line that asks for an answer needs a beat: keep some of the pause or the reaction before the '
                      'reply, or let the line run on')


def sound_speed(plan, item):
    """The speed a sound item plays at, as assemble.py takes it: that of a picture segment from the same source
    over its range."""
    for seg in plan['segments']:
        speed = float(seg.get('speed') or 1.0)
        source_end = seg['s0'] + (seg['t1'] - seg['t0']) * speed
        if seg['key'] == item['src'] and seg['s0'] < float(item['out']) and float(item['in']) < source_end:
            return speed
    return 1.0


def sound_past_picture(plan, settings, problems):
    """Name a film whose length is just past a whole frame while its last sound runs to the end. The picture is
    rounded to whole frames (to the nearest one when it is within a quarter frame, depending on the sources' clocks)
    and the sound is cut where the picture ends, so the last sound's fade-out can be cut short: a teaser that gained
    0.80 s mid-film at 24 fps moved its picture 19 frames (0.792 s) and its sound 0.800 s, and the closing title's
    sound ended 8 ms before its fade-out did. A film fade-out fades the sound with the picture, so it is exempt."""
    total = float(plan['duration'] or 0.0)
    rate = float(settings.get('fps') or 0)
    if total <= 0 or rate <= 0 or (plan.get('fades') or {}).get('out') or not plan['audio']:
        return
    frames = math.floor(total * rate + 1e-9)
    over = total - frames / rate
    if over <= 0.0005 or over > 0.25 / rate:
        return
    sound_end = max(float(item['at']) + (float(item['out']) - float(item['in'])) / sound_speed(plan, item)
                    for item in plan['audio'])
    if sound_end <= frames / rate + 0.0005:
        return
    last = max(plan['lines'], key=lambda record: record.get('end', 0.0), default={'line': 1})
    problems.warn(last.get('line', 1), f'the film is {total:.3f} s, {total * rate - frames:.2f} of a frame past '
                  f'{frames} frames at {rate:g} fps, and its last sound runs to the end: the picture can end at '
                  f'{frames / rate:.3f} s and cut the last {(sound_end - frames / rate) * 1000:.0f} ms of that sound '
                  'before its fade-out ends',
                  f'make the film a whole number of frames (change a line by whole frames of {1 / rate:.4f} s: '
                  f'{over:.3f} s shorter or {(frames + 1) / rate - total:.3f} s longer), end the last sound earlier, '
                  'or hold the picture past it')


def opening_mid_sentence(plan, source_map, problems):
    """Name a film whose first spoken word may continue a sentence: the word before it in the source does not end
    a sentence and no second of pause separates them. A reviewed cut that trimmed its setup opened on a clipped
    clause with a lowercase first caption, and a blind judge marked its hook down for it. Punctuation cannot tell a
    clipped thought from a line that stands alone (a question can), so this is a prompt for a decision."""
    spoken = sorted((record for record in plan['lines'] if record.get('kind') == 'spoken' and record.get('words')),
                    key=lambda record: record['start'])
    if not spoken or not isinstance(spoken[0]['words'][0], dict):
        return
    first = spoken[0]
    words = source_map.words(first.get('source')) or []
    position = {word.get('id'): number for number, word in enumerate(words)}
    number = position.get(first['words'][0].get('id'))
    if not number:
        return
    previous, current = words[number - 1], words[number]
    if (str(previous.get('text', '')).rstrip().endswith(SENTENCE_END)
            or float(current['start']) - float(previous['end']) >= SENTENCE_PAUSE):
        return
    problems.warn(first['line'], f'the film may open mid-sentence: "{previous["text"]} {current["text"]}" at '
                  f'{fmt(float(current["start"]))} in {first.get("source")}, with the words before it cut',
                  'start where the sentence starts, or confirm the first line stands as a whole thought: a viewer '
                  'meets a clipped one, and the first caption starts mid-sentence')


def join_notes(plan, notes, problems):
    """Name each join between passages with no note to readers between its two lines. The note says what links the
    two sides in meaning (a shared subject, situation, question, cause or intended contrast), where the viewer is and
    what they feel across it (finding-the-story section 4). Words that happen to fit are not a link, and writing the
    link down is how an editor finds a join that has none: agents joined lines because the words lined up, and the
    person watching found the scenes random. Short clips, montage sections and lines that continue the same passage
    are left alone."""
    if not plan['segments'] or plan['duration'] <= SHORT_CLIP:
        return
    timed = sorted((record for record in plan['lines'] if record.get('kind') in ('spoken', 'picture', 'still')
                    and record.get('range') and not record.get('over')), key=lambda record: record['start'])
    places = sorted(note['line'] for note in notes)
    for before, after in zip(timed, timed[1:]):
        same = before.get('source') == after.get('source')
        if same and 0 <= after['range'][0] - before['range'][1] <= 0.5:
            continue
        if all('montage' in str(record.get('section') or '').lower() for record in (before, after)):
            continue
        if any(before['line'] < line < after['line'] for line in places):
            continue
        problems.warn(after['line'], f'no note at the join from line {before["line"]} ({before.get("source")} '
                      f'{fmt(before["range"][1])}) to this line ({after.get("source")} {fmt(after["range"][0])})',
                      'write a plain line between them: what links the two sides in meaning (a shared subject, '
                      'situation, question, cause or intended contrast), where the viewer is, and what they feel '
                      'across it; if only the words link them, change the join')


def out_of_order(plan, source_map, problems):
    """Warn where an interview line plays something said more than 30 s before the line it follows. A viewer takes
    consecutive lines as one telling, in order: an interview cut that put one remembered phone call straight before
    another from years later played to two blind judges as one event. A hook taken from later in the interview is
    often deliberate; the warning asks for the reason."""
    spoken = sorted((record for record in plan['lines'] if record.get('kind') == 'spoken' and record.get('range')),
                    key=lambda record: record['start'])
    for before, after in zip(spoken, spoken[1:]):
        alias = after.get('source')
        if alias != before.get('source') or (source_map.sources.get(alias) or {}).get('role') not in SPEECH_ROLES:
            continue
        back = before['range'][1] - after['range'][0]
        if back > BACKWARD_S:
            problems.warn(after['line'], f'this line was said {fmt(back)} before the line it follows '
                          f'({fmt(after["range"][0])} after {fmt(before["range"][1])} in {alias}): viewers take '
                          f'consecutive lines as one telling, in order',
                          'check both describe the moment the cut implies, make the jump clear (a title, a change of '
                          'scene), or say why the order is faithful in the join note')


def feed_captions(settings, problems):
    """Warn when burned captions on a landscape frame are meant for a phone feed, where the frame shows about 390 px
    wide: two blind judges found landscape captions about 8 px tall there, unreadable muted."""
    size = settings.get('size')
    audience = settings.get('audience') or ''
    if not size or 'burn' not in settings.get('captions', ()) or size[0] <= size[1] * 1.2:
        return
    if not FEED_WORDS.search(audience):
        return
    shown = 0.045 * size[1] * FEED_WIDTH / size[0]
    problems.warn(1, f'burned captions on a {size[0]}x{size[1]} frame show about {shown:.0f} px tall in a phone feed '
                  f'({FEED_WIDTH} px wide), which the audience line names',
                  'use 9:16 or 4:5 for a phone feed (crop auto keeps the speaker in frame), or say why landscape')



def continuous_pictures(segments):
    """Join consecutive segments that continue the same source picture with the same framing and no break (a line
    split in two, a cutaway of the same shot over its own line): a viewer sees one shot, not two pieces. An editor's
    deliberate 0.13 s continuation of a shot was named as a flash frame before this."""
    merged = []
    for segment in segments:
        previous = merged[-1] if merged else None
        speed = segment.get('speed') or 1.0
        if (previous is not None and previous.get('key') == segment.get('key') and not segment.get('join')
                and (previous.get('speed') or 1.0) == speed and abs(previous['t1'] - segment['t0']) < 0.02
                and abs(previous['s0'] + (previous['t1'] - previous['t0']) * speed - segment['s0']) < 0.05
                and previous.get('frame') == segment.get('frame')):
            merged[-1] = dict(previous, t1=segment['t1'])
        else:
            merged.append(dict(segment))
    return merged


def picture_slivers(plan, source_map, problems):
    """Warn where the film shows a picture for under half a second without meaning to: a source's shot change just
    inside a picture range (a flash of the neighbouring shot), or a moment of a line's own picture left between two
    cutaways. Editors call it a flash frame; a viewer sees a stray face or a graphic. Pieces at a dissolve or fade are
    blended, so they are left alone."""
    changes = {}
    segments = continuous_pictures(plan['segments'])
    for index, segment in enumerate(segments):
        alias = segment.get('key')
        if alias not in source_map.sources or not source_map.has_video(alias):
            continue
        if alias not in changes:
            data = project.load_json(source_map.root / 'map' / alias / 'shots.json', {}) or {}
            rows = data.get('shots') if isinstance(data, dict) else None
            changes[alias] = sorted(float(row['start']) for row in rows or [] if isinstance(row, dict)
                                    and isinstance(row.get('start'), (int, float)) and row['start'] > 0)
        grid = segment.get('grid')
        frame = 1.0 / float(grid[0]) if grid and grid[0] else 1 / 30
        speed = segment.get('speed') or 1.0
        start, end = segment['s0'], segment['s0'] + (segment['t1'] - segment['t0']) * speed
        inside = [t for t in changes[alias] if start < t < end]
        edges = [start] + inside + [end]
        following = segments[index + 1] if index + 1 < len(segments) else None
        blended_in = bool(segment.get('join'))
        blended_out = bool(following and following.get('join') and following['t0'] < segment['t1'])
        for number, (a, b) in enumerate(zip(edges, edges[1:])):
            shown = (b - a) / speed
            first, last = number == 0, number == len(edges) - 2
            if not frame * 0.5 < shown < SLIVER or (first and blended_in) or (last and blended_out):
                continue
            at = segment['t0'] + (a - start) / speed
            if inside:
                change = b if first else a
                problems.warn(segment['line'], f'{shown:.2f} s of another shot shows at {fmt(at)} in the film: '
                              f'{alias} changes shot at {fmt(change)}, just '
                              f'{"inside the start" if first else "before the end" if last else "inside"} '
                              f'of this range (a flash frame)',
                              f'start this range at or after {fmt(change)}' if first else
                              f'end this range at or before {fmt(change)}' if last else
                              'choose a range within one shot')
            else:
                problems.warn(segment['line'], f'only {shown:.2f} s of this picture shows at {fmt(at)} in the film, '
                              f'between other pictures (a flash frame)',
                              'extend the picture before or after it over this moment, or hold this one longer')


def analyse(root, measure=True, verify_media=False):
    """Parse and compile film.md: (text, settings, entries, plan, problems, source map). With `verify_media`, every
    spoken source's file is hashed against the map before its words are trusted (a render does this)."""
    film = root / 'film.md'
    if not film.is_file():
        raise ValueError(f'no film.md in {root}; write one (references/paper-edit.md) or run cut.py draft')
    text = project.read_text(film)
    problems = Problems()
    source_map = SourceMap(root)
    source_map.verify_media = verify_media
    reader_notes = []
    settings, entries = parse_film(text, problems, set(source_map.sources), root, notes=reader_notes)
    ffmpeg = find_tool('ffmpeg') if measure else None
    envelopes = Envelopes(source_map, ffmpeg) if ffmpeg else None
    if measure and not ffmpeg:
        problems.note(1, 'FFmpeg not found: cuts are placed from transcript times without measuring pauses')
    plan = Compiler(settings, entries, source_map, envelopes, problems).run()
    picture_past_end(plan, source_map, problems)
    cover_framing(plan, source_map, settings, problems, ffmpeg)
    join_report(plan, entries, source_map, ffmpeg, problems)
    pins = settings.get('caption_breaks') or []
    plan['caption_breaks'] = []
    for pin in pins:
        found = [word for word in plan['words'] if word.get('id') == pin['word']]
        if not found and pin_blocked_by_bad_line(pin, entries, source_map):
            continue
        if not found:
            problems.error(pin['line'], f"caption break word {pin['word']} is not kept in the film",
                           'restore the word or remove the caption break')
        elif len(found) > 1:
            problems.error(pin['line'], f"caption break word {pin['word']} appears more than once",
                           'use a unique source word for the boundary')
        else:
            plan['caption_breaks'].append(pin['word'])
    target = settings.get('target')
    if target and plan['duration']:
        difference = plan['duration'] - target
        if abs(difference) > max(1.0, 0.1 * target):
            problems.warn(1, f'estimated length {plan["duration"]:.1f} s is {abs(difference):.1f} s '
                          f'{"over" if difference > 0 else "under"} the target of {target:g} s',
                          'cut lines or words' if difference > 0 else 'add material, or change target')
    if not plan['segments'] and not problems.count('error'):
        problems.error(1, 'film.md has no lines that take time', 'add a spoken (>) or picture (-) line')
    missing = [key for key in DIRECTION_KEYS if not (settings.get(key) or '').strip()]
    if missing and plan['segments'] and plan['duration'] > SHORT_CLIP:
        # Every check can pass on a cut that is only a list of lines; the direction is what makes it a film.
        problems.warn(1, 'film.md does not state its ' + ', '.join(missing) + ', so nothing says what this cut is '
                      'for or why its lines are in this order',
                      'write audience, takeaway and story before choosing lines (references/finding-the-story.md)')
    if 'burn' in settings.get('captions', ()) and plan['segments'] and not plan['words']:
        problems.warn(1, 'captions: burn, but no spoken line keeps a word, so there is nothing to caption',
                      'add spoken (>) lines, or drop burn for a film without speech')
    check_layers(plan, source_map, problems)
    picture_slivers(plan, source_map, problems)
    out_of_order(plan, source_map, problems)
    feed_captions(settings, problems)
    join_notes(plan, reader_notes, problems)
    opening_mid_sentence(plan, source_map, problems)
    no_beat_after(plan, source_map, problems)
    sound_past_picture(plan, settings, problems)
    problems.items.sort(key=lambda item: (item['line'], ('error', 'warning', 'info').index(item['severity'])))
    return text, settings, entries, plan, problems, source_map


def layer_hint(role, name):
    """How to make a layer for a role."""
    if role == 'behind':
        return f'make it with matte.py (references/spatial.md), named {name}'
    return (f'make it with track.py SOURCE --at TIME --region x,y,w,h --name {name} --project PROJECT '
            '(references/spatial.md)')


def layer_spans(plan, use, alias):
    """The parts of a layer use's film interval where `alias` is on screen: [(film start, film end, segment)]."""
    rows = []
    for seg in plan['segments']:
        low, high = max(seg['t0'], use['from']), min(seg['t1'], use['to'])
        if high > low + 1e-6 and seg['key'] == alias:
            rows.append((low, high, seg))
    return rows


def check_layer_frames(use, layer, spans, problems, spatial):
    """Source frames a layer is drawn over that it has no usable frame for: outside its range, or lost."""
    times = layer['times']
    outside, lost = [], []
    for low, high, seg in spans:
        first = seg['s0'] + (low - seg['t0']) * seg['speed']
        last = seg['s0'] + (high - seg['t0']) * seg['speed']
        if spatial.frame_index(times, first) is None or spatial.frame_index(times, last - 1e-3) is None:
            outside.append((low, high, first, last))
        if layer['kind'] == 'track':
            for index, moment in enumerate(times):
                if first - 1e-6 <= moment < last and layer['frames'][index]['state'] == 'lost':
                    lost.append(seg['t0'] + (moment - seg['s0']) / seg['speed'])
    blur = use['role'] == 'blur'
    report = problems.error if blur else problems.warn
    consequence = 'the render stops (a privacy blur fails closed)' if blur else f'the {use["role"]} is not drawn there'
    for low, high, first, last in outside:
        report(use['line'], f"layer {use['name']} covers source {fmt(times[0])}-{fmt(times[-1])}, but this line "
               f'shows {fmt(first)}-{fmt(last)} of it ({fmt(low)}-{fmt(high)} in the film); {consequence}',
               f'track it over that range again (track.py ... --from {fmt(max(0.0, first))} --to {fmt(last)})')
    if lost:
        shown = ', '.join(fmt(moment) for moment in lost[:4]) + (' ...' if len(lost) > 4 else '')
        report(use['line'], f"layer {use['name']} is lost on {len(lost)} frame{'s' if len(lost) != 1 else ''} this "
               f'line shows (film {shown}); {consequence}',
               'track again with a key frame nearer those frames, a larger --region, or shorten the line')


def check_layers(plan, source_map, problems):
    """Every layer a line pins to, draws behind or blurs: present, readable, the right kind, current for its source
    (the map's size and SHA-256), made from the source on screen under the line, and covering the frames shown."""
    uses = plan.get('layer_uses') or []
    if not uses:
        return
    spatial = load_sibling('spatial')
    root = source_map.root
    kinds = {'pin': ('track',), 'behind': ('matte',), 'blur': ('track', 'matte')}
    for use in uses:
        line, role, name = use['line'], use['role'], use['name']
        path = root / 'spatial' / f'{name}.json'
        if not path.is_file():
            problems.error(line, f'no layer spatial/{name}.json', layer_hint(role, name))
            continue
        try:
            layer = spatial.read_layer(path)
        except ValueError as error:
            problems.error(line, f'layer {name} cannot be read: {error}', layer_hint(role, name))
            continue
        if layer['kind'] not in kinds[role]:
            problems.error(line, f'{role} needs a {" or ".join(kinds[role])} layer; {name} is a {layer["kind"]}',
                           layer_hint(role, name))
            continue
        state = spatial.layer_state(path, layer, root)
        if state['state'] != 'current':
            problems.error(line, f"layer {name} is {state['state']}: " + '; '.join(state['reasons']),
                           'make it again from the source as it is now: ' + layer_hint(role, name))
            continue
        alias = layer_alias(spatial, root, layer, state['source_file'])
        on_screen = sorted({seg['key'] for seg in plan['segments']
                            if seg['t0'] < use['to'] and seg['t1'] > use['from']})
        spans = layer_spans(plan, use, alias)
        if not spans:
            made = alias or layer['source']['file']
            problems.error(line, f"layer {name} was made from {made}, but {', '.join(on_screen) or 'nothing'} is on "
                           'screen here', f'put this line over a shot of {made}, or make a layer from the source '
                           'on screen')
            continue
        frozen = [seg for seg in plan['segments'] if seg['t0'] < use['to'] and seg['t1'] > use['from']
                  and (plan['assets'].get(seg['key']) or {}).get('alias') == alias]
        if role == 'blur' and frozen:
            problems.error(line, f'a frame frozen from {alias} is on screen at {fmt(frozen[0]["t0"])} under blur '
                           f'{name}; a freeze is a new picture and is not blurred',
                           'remove the freeze from the blurred stretch, or end the blur before it')
        shown = sum(high - low for low, high, _ in spans)
        if role != 'blur' and shown < use['to'] - use['from'] - 1e-3:
            problems.warn(line, f'{alias} is on screen for {shown:.2f} of {use["to"] - use["from"]:.2f} s of this '
                          f'{role}; it is drawn only there (not under other sources, dissolves or dips)',
                          'shorten it to the shot it belongs to')
        check_layer_frames(use, layer, spans, problems, spatial)


def layer_alias(spatial, root, layer, source_file):
    """The map alias of a layer's source: as the layer records it, else the map row for the same file."""
    alias = layer['source'].get('alias')
    if alias:
        return alias
    row = spatial.map_row_for(root, source_file)
    return row['alias'] if row else None


def layer_records(plan, root):
    """What a version records about each layer it uses: sidecar and data SHA-256, kind, source and range."""
    spatial = load_sibling('spatial')
    names = []
    for use in plan.get('layer_uses') or []:
        if use['name'] not in names:
            names.append(use['name'])
    rows = []
    for name in names:
        record = spatial.layer_record(Path(root) / 'spatial' / f'{name}.json')
        record['sidecar'] = f'spatial/{name}.json'
        rows.append(record)
    return rows


def spoken_summary(record):
    """A one-line description of what a spoken line keeps and cuts."""
    kept = len(record.get('words', []))
    cut = [word['text'] for word in record.get('cut_words', [])]
    parts = [f'line {record["line"]} {record.get("source")}: keeps {kept} of {kept + len(cut)} words']
    if record.get('sound_source'):
        parts[0] += f', sound from {record["sound_source"]}'
    if cut:
        shown = ', '.join(f'"{text}"' for text in cut[:8]) + (' ...' if len(cut) > 8 else '')
        parts.append('cuts ' + shown)
    if record.get('jump_cuts'):
        parts.append(f'{len(record["jump_cuts"])} jump cut{"s" if len(record["jump_cuts"]) > 1 else ""}')
    hidden = len(record.get('audio_cuts', [])) - len(record.get('jump_cuts', []))
    if hidden > 0:
        parts.append(f'{hidden} under cutaways')
    return '; '.join(parts)


def print_problems(problems, verbose=False):
    """Problems as 'film.md:LINE: severity: message' with a suggestion line."""
    for item in problems.items:
        if item['severity'] == 'info' and not verbose:
            continue
        print(f'film.md:{item["line"]}: {item["severity"]}: {item["message"]}')
        if item['suggestion']:
            print(f'  suggestion: {item["suggestion"]}')


def preference_summary(root, lines, include_details=False):
    """Expose confirmed preference looks as non-gating direction for this plan or version."""
    if not (root / 'taste.json').is_file():
        return None
    if not (HERE / 'taste.py').is_file():
        return {'summary': 'preferences unavailable: taste.py is missing'}
    return load_sibling('taste').summary(root, lines, include_details)


def run_check(args):
    """cut.py check: validate film.md against the map without rendering."""
    root = load_project(args.project)
    text, settings, entries, plan, problems, _ = analyse(root, measure=not args.no_audio)
    errors, warnings = problems.count('error'), problems.count('warning')
    target = settings.get('target')
    report = {'project': str(root), 'ok': errors == 0, 'errors': errors, 'warnings': warnings,
              'duration_s': round(plan['duration'], 3), 'target_s': target, 'problems': problems.items,
              'lines': plan['lines'], 'joins': plan['joins'], 'picture_changes': plan['picture_changes'],
              'busy_cutting': plan['busy_cutting']}
    preference = preference_summary(root, plan, include_details=True)
    if preference is not None:
        report['preferences'] = preference
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return 1 if errors else 0
    sections = len({entry['section'] for entry in entries if entry['section']})
    timing = f'estimated {plan["duration"]:.1f} s' + (f' (target {target:g} s)' if target else '')
    print(f'film.md: {len(entries)} lines, {sections} section{"s" if sections != 1 else ""}, {timing}')
    if settings.get('story'):
        print('story: ' + settings['story'])
    print_problems(problems)
    for record in plan['lines']:
        if record['kind'] == 'spoken':
            print(spoken_summary(record))
    for row in join_summary(plan):
        print(row)
    if preference is not None:
        print(preference['summary'])
    print(f'{errors} error{"s" if errors != 1 else ""}, {warnings} warning{"s" if warnings != 1 else ""}')
    return 1 if errors else 0


# ----------------------------------------------------------------------------------------------- render assets

def run_command(command, what, seconds=1800):
    """Run a process with a time limit; raise with its error output on failure."""
    try:
        result = subprocess.run([str(part) for part in command], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=seconds)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'{what} did not finish within {seconds} s and was stopped')
    if result.returncode:
        raise RuntimeError(f'{what} failed: {(result.stderr or result.stdout)[-1500:]}')
    return result


def rate_text(rate):
    """A frame rate as FFmpeg's num/den."""
    return f'{rate.numerator}/{rate.denominator}'


def even(value):
    """The nearest even whole number, at least 2."""
    return max(2, int(round(value / 2.0)) * 2)


def render_size(size, final):
    """The render size: the film's size, or short side 540 for a preview (never larger than the film)."""
    width, height = size
    if final or min(width, height) <= PREVIEW_SHORT:
        return width, height
    scale = PREVIEW_SHORT / min(width, height)
    return even(width * scale), even(height * scale)


BT709 = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv']


def make_background(ffmpeg, path, size, rate, colour, seconds):
    """A plain clip in the background colour."""
    width, height = size
    run_command([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                 f'color=c={colour}:s={width}x{height}:r={rate_text(rate)}:d={seconds:.3f}',
                 '-vf', 'format=rgb24,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p',
                 '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', *BT709, str(path)], 'background clip')


def image_transparent(path):
    """Whether an image has any pixel that is not fully opaque (False for a file Pillow cannot read, which FFmpeg
    then reads as before)."""
    from PIL import Image
    try:
        with Image.open(path) as image:
            if image.mode not in ('RGBA', 'LA', 'PA') and 'transparency' not in image.info:
                return False
            return image.convert('RGBA').getchannel('A').getextrema()[0] < 255
    except OSError:
        return False


def make_still(ffmpeg, path, image, rate, seconds, colour):
    """A clip that shows an image for a number of seconds at the film's frame rate; its clear areas show the
    background colour, as a title card's do."""
    scale = ("scale='trunc(min(iw,3840)/2)*2':'trunc(ih*min(iw,3840)/iw/2)*2':flags=lanczos:"
             'out_color_matrix=bt709:out_range=tv,format=yuv420p')
    flat = None
    if image_transparent(image):
        from PIL import Image
        flat = path.with_name(f'{path.stem}-flat.png')
        with Image.open(image) as picture:
            picture = picture.convert('RGBA')
            plate = Image.new('RGBA', picture.size, colour)
            Image.alpha_composite(plate, picture).convert('RGB').save(flat)
    run_command([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-loop', '1', '-framerate', rate_text(rate),
                 '-i', str(flat or image), '-t', f'{seconds:.3f}', '-vf', scale, '-r', rate_text(rate), '-c:v',
                 'libx264', '-preset', 'veryfast', '-crf', '14', '-tune', 'stillimage', *BT709, str(path)],
                'still clip')
    if flat:
        flat.unlink()


def make_freeze(ffmpeg, path, source, moment, rate, seconds):
    """A clip that holds one frame of a video, without converting it through RGB."""
    filters = (f'select=eq(n\\,0),loop=loop=-1:size=1:start=0,setpts=N/({rate_text(rate)})/TB,'
               "scale='trunc(iw/2)*2':'trunc(ih/2)*2',format=yuv420p")
    run_command([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-ss', f'{moment:.4f}', '-i', str(source), '-an',
                 '-vf', filters, '-r', rate_text(rate), '-t', f'{seconds:.3f}', '-c:v', 'libx264', '-preset',
                 'veryfast', '-crf', '14', str(path)], 'freeze frame')


def font_path(settings):
    """The title font: bundled Mona Sans or Geist Mono, or a file the front matter names."""
    if settings.get('_title_font_path'):
        return Path(settings['_title_font_path'])
    bundled = HERE.parent / 'assets' / 'kit' / 'fonts'
    choice = settings.get('font') or 'sans'
    if choice == 'sans':
        return bundled / 'MonaSansVF.woff2'
    if choice == 'mono':
        return bundled / 'GeistMonoVF.woff2'
    return Path(choice)


def load_font(path, size, weight):
    """A Pillow font at a size, with a variable font's weight axis set; a system font if the file will not load."""
    from PIL import ImageFont
    font = None
    for candidate in (path, Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'arialbd.ttf',
                      Path('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
                      Path('/System/Library/Fonts/Supplemental/Arial Bold.ttf')):
        try:
            font = ImageFont.truetype(str(candidate), size)
            break
        except OSError:
            continue
    if font is None:
        return ImageFont.load_default(size)
    try:
        values = []
        for axis in font.get_variation_axes():
            name = axis['name'].decode() if isinstance(axis['name'], bytes) else str(axis['name'])
            if 'eight' in name.lower():
                values.append(max(axis['minimum'], min(axis['maximum'], weight)))
            else:
                values.append(axis['default'])
        font.set_variation_by_axes(values)
    except (OSError, AttributeError, KeyError):
        pass
    return font


def wrap_text(text, font, width):
    """Lines of text that fit a width."""
    lines, current = [], ''
    for word in text.split():
        ink = font.getbbox(word)
        if max(float(font.getlength(word)), float(ink[2] - ink[0])) > width:
            raise ValueError(f'title word {word!r} does not fit the {width:.0f} px safe width; '
                             'shorten it or supply a deliberate break')
        trial = f'{current} {word}'.strip()
        bounds = font.getbbox(trial)
        if not current or max(float(font.getlength(trial)), float(bounds[2] - bounds[0])) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def title_font_info(settings):
    """Record the requested and loaded title face, including a fallback."""
    requested = str(font_path(settings))
    font = load_font(Path(requested), 24, 700)
    actual = str(getattr(font, 'path', '') or 'Pillow default')
    fallback = actual == 'Pillow default' or os.path.normcase(os.path.abspath(actual)) != \
        os.path.normcase(os.path.abspath(requested))
    return {'requested': requested, 'actual': actual, 'fallback': fallback,
            'face': list(font.getname()) if hasattr(font, 'getname') else None}


def make_title(path, size, texts, position, settings):
    """A transparent full-frame PNG with the title's text, a soft shadow behind it for any picture."""
    from PIL import Image, ImageDraw, ImageFilter
    from PIL import features
    width, height = size
    short = min(width, height)
    fonts = [load_font(font_path(settings), max(12, round(short * 0.072)), 700),
             load_font(font_path(settings), max(10, round(short * 0.044)), 450)]
    captions = load_sibling('captions')
    if any(captions.complex_shaping_needed(text) for text in texts):
        if not features.check('raqm'):
            raise ValueError('complex-script titles need Pillow with Raqm, HarfBuzz and FriBidi; '
                             'use a verified title image or install a Pillow build with Raqm')
        for number, text in enumerate(texts[:2]):
            selected = getattr(fonts[min(number, 1)], 'path', None)
            if not selected:
                raise ValueError('cannot verify glyph coverage of the selected title font')
            missing = captions.missing_glyphs(selected, text)
            if missing:
                raise ValueError('title font lacks glyphs ' + ', '.join('U+%04X' % code for code in missing[:20]))
    shadow_radius = max(1, short * 0.008)
    shadow_padding = math.ceil(3 * shadow_radius)
    safe_left, safe_right = width * .08, width * .92
    safe_top, safe_bottom = height * .04, height * .96
    rows = []
    for number, text in enumerate(texts[:2]):
        font = fonts[min(number, 1)]
        for line in wrap_text(text, font, safe_right - safe_left - 2 * shadow_padding):
            box = font.getbbox('Hg')
            rows.append((line, font, round((box[3] - box[1]) * 1.25)))
    total = sum(row[2] for row in rows)
    vertical = height > width
    if position == 'upper':
        top = height * (0.13 if vertical else 0.09)
    elif position == 'center':
        top = (height - total) / 2
    else:
        top = height * (0.70 if vertical else 0.79) - total
    shadow = Image.new('RGBA', size, (0, 0, 0, 0))
    text_layer = Image.new('RGBA', size, (0, 0, 0, 0))
    y = top
    for line, font, step in rows:
        x = (width - font.getlength(line)) / 2
        ink = font.getbbox(line)
        if (x + ink[0] - shadow_padding < safe_left or x + ink[2] + shadow_padding > safe_right
                or y + ink[1] - shadow_padding < safe_top or y + ink[3] + shadow_padding > safe_bottom):
            raise ValueError(f'title line {line!r} does not fit the {width}x{height} safe box; '
                             'use shorter text or deliberate breaks')
        ImageDraw.Draw(shadow).text((x, y), line, font=font, fill=(0, 0, 0, 190))
        ImageDraw.Draw(text_layer).text((x, y), line, font=font, fill=(255, 255, 255, 255))
        y += step
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_radius))
    Image.alpha_composite(shadow, text_layer).save(path)


def trim_to_content(path):
    """Cut a title picture to its text and a margin of a tenth of the text's height (for a title pinned to a
    surface)."""
    from PIL import Image
    with Image.open(path) as opened:
        image = opened.convert('RGBA')
    box = image.getchannel('A').getbbox()
    if box:
        margin = max(4, (box[3] - box[1]) // 10)
        image.crop((max(0, box[0] - margin), max(0, box[1] - margin), min(image.width, box[2] + margin),
                    min(image.height, box[3] + margin))).save(path)


def make_fade_plate(path, size, colour):
    """A full-frame opaque PNG used to fade the film's start or end."""
    from PIL import Image
    Image.new('RGBA', size, colour).save(path)


# ----------------------------------------------------------------------------------------------- render timeline

def snap(value, grid):
    """A source time on its frame grid, the way assemble.py snaps it."""
    rate, offset = grid
    return offset + round((value - offset) * float(rate)) / float(rate)


def picture_items(plan, settings, problems):
    """Keep picture boundaries on the same edit clock as sound, words, captions and lines."""
    segments = plan['segments']
    items, starts = [], []
    actual = 0.0
    for number, seg in enumerate(segments):
        following = segments[number + 1] if number + 1 < len(segments) else None
        overlap = following['join'][1] if following is not None and following['join'] else 0.0
        if following is not None and overlap:
            longest = min(following['t1'] - following['t0'], seg['t1'] - seg['t0'])
            if overlap > longest:
                problems.warn(following['line'], f'the {following["join"][0]} ({overlap:g} s) is longer than the '
                              f'shots it joins; shortened to {longest:.2f} s')
                overlap = longest
                following['join'] = (following['join'][0], longest)
        rate = float(seg['grid'][0])
        source_in = max(0.0, seg['s0'] + (actual - seg['t0']) * seg['speed'])
        source_out = source_in + (seg['t1'] + overlap - actual) * seg['speed']
        if seg['limit'] and source_out > seg['limit']:
            available = (seg['limit'] - source_in) / seg['speed'] - (seg['t1'] - actual)
            if following is not None and overlap:
                overlap = max(0.0, available)
                problems.warn(following['line'], f'not enough picture after the line above for the '
                              f'{following["join"][0]}; shortened to {overlap:.2f} s')
                following['join'] = (following['join'][0], overlap) if overlap >= 1 / rate else None
            source_out = min(seg['limit'], source_in + (seg['t1'] + overlap - actual) * seg['speed'])
        if source_out <= source_in:
            raise ValueError(f'picture line {seg["line"]} has no source duration')
        item = {'src': seg['key'], 'in': round(source_in, 6), 'out': round(source_out, 6)}
        if seg.get('hold_previous'):
            item['hold_previous'] = True
        if seg['speed'] != 1:
            item['speed'] = seg['speed']
        if seg['join']:
            item['join'] = {'kind': seg['join'][0], 'dur': round(seg['join'][1], 6),
                            'color': settings['background']}
        frame = seg['frame']
        item['fit'] = frame['fit']
        if frame['fit'] == 'contain':
            item['background'] = settings['background']
        item['crop'] = {'path': frame['crop']}
        if frame['crop'] != 'auto' or frame.get('zoom_explicit'):
            item['crop']['zoom'] = frame['zoom']
        items.append(item)
        starts.append(actual)
        actual += (source_out - source_in) / seg['speed'] - overlap
        if seg['key'] in plan['assets']:
            asset = plan['assets'][seg['key']]
            asset['need'] = max(asset['need'], source_out)
    return items, starts


def relative_source(version_dir, path):
    """A source path as edit.json sees it from a version folder: relative when it can be, absolute when the source
    is on another drive (Windows has no relative path between drives)."""
    source = Path(path).resolve()
    try:
        return Path(os.path.relpath(source, Path(version_dir).resolve())).as_posix()
    except ValueError:
        return source.as_posix()


def declared_ranges(plan):
    """Describe intentional low-detail or held intervals on the edit clock."""
    total = float(plan['duration'])
    ranges = []
    fades = plan.get('fades') or {}
    if fades.get('in'):
        ranges.append({'kind': 'fade', 'start': 0.0, 'end': min(total, float(fades['in']))})
    if fades.get('out'):
        ranges.append({'kind': 'fade', 'start': max(0.0, total - float(fades['out'])), 'end': total})
    for line in plan.get('lines', []):
        if line.get('kind') == 'pause':
            kind = 'hold' if line.get('hold') else 'pause'
        elif line.get('kind') == 'title' and line.get('card'):
            kind = 'title_card'
        elif line.get('overlay'):
            continue  # drawn over footage that still plays, so the footage under it is checked as usual
        elif line.get('kind') == 'still' or line.get('still'):
            kind = 'still'
        else:
            continue
        ranges.append({'kind': kind, 'start': float(line['start']), 'end': float(line['end'])})
    return ranges


CUT_FADE_CUE_ROLE = '__cut_fade_plate__'


def without_generated_fade_cues(document):
    """Remove sound cues for generated fade plates, leaving every other cue intact."""
    if not isinstance(document, dict) or not isinstance(document.get('events'), list):
        return document
    events = [event for event in document['events']
              if not (isinstance(event, dict) and event.get('role') == CUT_FADE_CUE_ROLE
                      and event.get('enabled') is False)]
    return dict(document, events=events)


def build_edit(plan, settings, source_map, version_dir, problems, captions_file):
    """The edit.json for assemble.py at the film's size, plus the extra keys cut.py records."""
    items, starts = picture_items(plan, settings, problems)
    sources = {}
    used = {item['src'] for item in items} | {item['src'] for item in plan['audio']}
    used |= {overlay['src'] for overlay in plan['overlays'] if overlay.get('src') in source_map.sources}
    bound = layer_sources(plan, source_map)
    for key in sorted(used):
        if key in source_map.sources:
            sources[key] = {'file': relative_source(version_dir, source_map.path(key))}
            audio = source_map.sources[key].get('audio') or {}
            if audio.get('index') is not None:
                sources[key]['audio_stream'] = audio['index']
            if key in bound:
                # Layers bind to the map's identity of the source, so a preview proxy still matches its layers.
                sources[key].update(sha256=source_map.sources[key].get('sha256'),
                                    bytes=source_map.sources[key].get('bytes'))
    for key, asset in plan['assets'].items():
        sources[key] = {'file': asset_file(key, asset)}
    overlays = [dict(overlay) for overlay in plan['overlays']]
    for overlay in overlays:
        for key in ('pin', 'behind', 'region'):
            if isinstance(overlay.get(key), dict):
                overlay[key] = dict(overlay[key], layer=relative_source(version_dir,
                                                                       source_map.root / overlay[key]['layer']))
    fade_plate = 'titles/fade.png'
    if plan['fades'].get('in'):
        seconds = plan['fades']['in']
        overlays.append({'kind': 'image', 'src': 'gen-fade', 'from': -seconds, 'to': seconds, 'x': 0, 'y': 0,
                         'w': 1.0, 'fade_ms': round(seconds * 1000)})
    if plan['fades'].get('out'):
        seconds = plan['fades']['out']
        total = plan['duration']
        overlays.append({'kind': 'image', 'src': 'gen-fade', 'from': total - seconds, 'to': total + seconds,
                         'x': 0, 'y': 0, 'w': 1.0, 'fade_ms': round(seconds * 1000)})
    if plan['fades']:
        sources['gen-fade'] = {'file': fade_plate}
    if captions_file and 'burn' in settings['captions']:
        overlay = {'kind': 'captions', 'file': captions_file}
        if 'plate' in settings['captions']:
            overlay['plate'] = True
        if 'highlight' in settings['captions']:
            overlay['highlight'] = True
        overlays.append(overlay)
    declarations = declared_ranges(plan)
    edit = {'version': 1, 'size': list(settings['size']), 'fps': settings['fps_text'], 'sources': sources,
            'picture': items, 'audio': plan['audio'], 'overlays': overlays,
            'holds': [row for row in declarations if row['kind'] == 'hold'],
            'declared': [row for row in declarations if row['kind'] != 'hold'], 'cues': [],
            'film_fades': plan['fades']}
    return edit, starts


def layer_sources(plan, source_map):
    """The source aliases the version's layers were made from."""
    spatial = load_sibling('spatial')
    aliases = set()
    for use in plan.get('layer_uses') or []:
        path = source_map.root / 'spatial' / f"{use['name']}.json"
        try:
            layer = spatial.read_layer(path)
        except ValueError:
            continue
        alias = layer_alias(spatial, source_map.root, layer, spatial.source_path(path, layer, source_map.root))
        if alias in source_map.sources:
            aliases.add(alias)
    return aliases


def asset_file(key, asset):
    """Where a generated asset lives inside the version folder."""
    if asset['kind'] == 'title':
        return f'titles/{key}.png'
    return f'media/{key[len("gen-"):]}.mp4'


def make_assets(plan, settings, source_map, version_dir, ffmpeg):
    """Render generated clips and title images into the version folder."""
    size = tuple(settings['size'])
    rate = settings['fps']
    (version_dir / 'media').mkdir(parents=True, exist_ok=True)
    (version_dir / 'titles').mkdir(parents=True, exist_ok=True)
    for key, asset in plan['assets'].items():
        path = version_dir / asset_file(key, asset)
        seconds = asset.get('need', 0.0) + 1.0
        if asset['kind'] == 'background':
            make_background(ffmpeg, path, size, rate, settings['background'], seconds)
        elif asset['kind'] == 'still':
            make_still(ffmpeg, path, source_map.path(asset['alias']), rate, seconds, settings['background'])
        elif asset['kind'] == 'freeze' and asset.get('hold_previous'):
            make_background(ffmpeg, path, size, rate, settings['background'], seconds)
        elif asset['kind'] == 'freeze':
            make_freeze(ffmpeg, path, source_map.path(asset['alias']), asset['time'], rate, seconds)
        elif asset['kind'] == 'title':
            make_title(path, size, asset['texts'], asset['position'], settings)
            if asset.get('trim'):
                trim_to_content(path)
    if plan['fades']:
        make_fade_plate(version_dir / 'titles' / 'fade.png', size, settings['background'])
    for folder in ('media', 'titles'):
        if not any((version_dir / folder).iterdir()):
            (version_dir / folder).rmdir()


# ----------------------------------------------------------------------------------------------- render captions

def sanitized_words(words):
    """Kept words in edit time, ordered and never overlapping, for captions.py (which keeps each word's ID)."""
    result = []
    previous_end = 0.0
    for word in words:
        start = max(word['start'], previous_end)
        end = max(word['end'], start + 0.02)
        result.append({'id': word.get('id'), 'text': word['text'], 'start': round(start, 4), 'end': round(end, 4),
                       **({'estimated': True} if word.get('estimated') else {}),
                       **({'speaker': word['speaker']} if word.get('speaker') is not None else {})})
        previous_end = end
    return result


def caption_groups(words, pinned=()):
    """Kept words split where a caption must not run on: a change of source (another speaker or recording), a change of
    labelled speaker (an unlabelled word between two speakers belongs to neither) or a pause of CAPTION_BREAK seconds or
    more."""
    groups = []
    speaker = None
    for word in words:
        source = str(word.get('id') or '').rsplit('-w', 1)[0]
        said = word.get('speaker')
        if (groups and word.get('id') not in pinned and source == groups[-1][0]
                and word['start'] - groups[-1][1][-1]['end'] < CAPTION_BREAK
                and (said is None or speaker is None or said == speaker)):
            groups[-1][1].append(word)
            speaker = said if said is not None else speaker
        else:
            groups.append((source, [word]))
            speaker = said
    return [group for _, group in groups]


def write_empty_captions(prefix):
    """Valid empty sidecars for a film with no kept words."""
    project.write_atomic(prefix.with_suffix('.srt'), '')
    project.write_atomic(prefix.with_suffix('.vtt'), 'WEBVTT\n')
    project.save_json(prefix.with_suffix('.json'), {'cues': []})


def caption_line_length(size):
    """Characters per caption line for the frame's shape: 42 for landscape and square, fewer for a tall frame, so
    the burn keeps text near its intended size instead of shrinking a 42-character line into a 9:16 frame (a cold
    run's two-line captions came out at 23 to 31 px in a 540x960 preview)."""
    if not size or size[0] >= size[1]:
        return 42
    return max(18, round(42 * size[0] / size[1] * 1.1))


def build_group(captions, words, prefix, notes, line_length=42):
    """Cues for one group through captions.py build (relaxed limits as a fallback); None when it cannot."""
    source = prefix.with_suffix('.words.json')
    project.save_json(source, {'words': sanitized_words(words)})
    for relaxed, extra in ((False, ['--line-length', str(line_length)]),
                           (True, ['--cps', '30', '--min-duration', '0.4', '--line-length', str(line_length + 6)])):
        args = captions.argument_parser().parse_args(['build', str(source), '--out', str(prefix), *extra])
        report = captions.run_build(args)
        blocking = [finding for finding in report.get('findings', []) if finding.get('rule') != 'line length']
        if not blocking and report.get('cues'):
            note = 'some captions needed relaxed limits (30 characters/s, 0.4 s minimum); review them'
            if relaxed and note not in notes:
                notes.append(note)
            for review in report.get('review', []):
                if review.get('rule') == 'segmentation relaxation':
                    note = 'caption segmentation relaxed ' + review['constraint'] + '; review the captions'
                    if note not in notes:
                        notes.append(note)
            if report.get('findings'):
                notes.append('a caption has a word longer than the line limit; fix the line length before delivery')
            cues = project.load_json(prefix.with_suffix('.json'), {}).get('cues', [])
            if not cues:
                raise ValueError('caption build reported cues but wrote an empty sidecar')
            return cues
    notes.append('captions could not be built for "' + ' '.join(word['text'] for word in words[:8]) + '": '
                 + '; '.join(str(item.get('rule')) for item in report.get('findings', [])))
    return None


def build_captions(plan, version_dir, work_dir, notes, size=None, wanted=True):
    """captions.srt/.vtt/.json: each group of kept words segmented by captions.py build (so caption rules live in
    one place, and every caption word keeps its transcript word ID), the cues joined without overlap and written by
    captions.py. Returns the caption file name for burning, or None. `wanted` is false for `captions: none`."""
    prefix = version_dir / 'captions'
    if not plan['words']:
        # Nothing to burn: a burn of no cues failed at the end of the render (64 s for a preview, 5 min for a final).
        write_empty_captions(prefix)
        note = 'no spoken words to caption: the caption files are empty and nothing was burned'
        if wanted and note not in notes:
            notes.append(note)
        return None
    captions = load_sibling('captions')
    cues = []
    for number, group in enumerate(caption_groups(plan['words'], set(plan.get('caption_breaks') or []))):
        built = build_group(captions, group, work_dir / f'captions-{number:03d}', notes, caption_line_length(size))
        if built is None:
            raise ValueError('captions could not be built for every kept word; inspect the caption notes')
        cues.extend(built)
    for current, following in zip(cues, cues[1:]):
        last_word = max((float(word['end']) for word in current.get('words', [])), default=float(current['end']))
        first_word = min((float(word['start']) for word in following.get('words', [])),
                         default=float(following['start']))
        pause = first_word - last_word
        if pause >= CAPTION_BREAK:
            padding = min(.2, pause / 3)
            end = round(min(float(current['end']), last_word + padding), 3)
            start = round(max(float(following['start']), first_word - padding), 3)
            if end != current['end'] or start != following['start']:
                current['end'], following['start'] = end, start
                note = 'caption durations were shortened around a long pause; review the reading time'
                if note not in notes:
                    notes.append(note)
            if end <= current['start'] or start >= following['end']:
                raise ValueError('caption groups cannot fit around the long pause; inspect the kept word timings')
        if float(current['end']) > float(following['start']) - .04:
            if first_word < last_word - 1e-6:
                raise ValueError('caption groups overlap in speech time; review their pinned or source boundary')
            gap = min(.04, max(0.0, first_word - last_word))
            boundary = (last_word + first_word) / 2
            current['end'] = round(min(float(current['end']), boundary - gap / 2), 3)
            following['start'] = round(max(float(following['start']), boundary + gap / 2), 3)
            if current['end'] <= current['start'] or following['start'] >= following['end']:
                raise ValueError('caption groups cannot fit around their boundary; inspect the kept word timings')
            note = 'caption durations were shortened at a required boundary; review the reading time'
            if note not in notes:
                notes.append(note)
    if not cues:
        raise ValueError('caption build returned no cues for kept words')
    captions.write_sidecars(cues, str(prefix))
    return 'captions.json'


def end_captions_with_film(prefix, length, notes):
    """End every caption by the film's last frame, rewriting the sidecars when one runs past it. Captions are segmented
    before the picture exists: a caption's minimum reading time can carry a short last word past the film, and a film
    length can round down to whole frames (a cue at 14.245 s on a film of 14.208 s)."""
    data = project.load_json(prefix.with_suffix('.json'), None)
    cues = data.get('cues') if isinstance(data, dict) else None
    limit = math.floor(length * 1000 + 1e-6) / 1000
    if not cues or all(float(cue['end']) <= limit for cue in cues):
        return
    kept = []
    for cue in cues:
        if float(cue['start']) >= limit:
            notes.append(f'a caption starting past the end of the film was left out: "{cue.get("text", "")}"')
            continue
        cue['end'] = min(float(cue['end']), limit)
        for word in cue.get('words') or []:
            word['end'] = min(float(word['end']), limit)
        kept.append(cue)
    load_sibling('captions').write_sidecars(kept, str(prefix))


# ----------------------------------------------------------------------------------------------- render media

def estimate_spool(edit, settings, source_map, proxies):
    """No raw picture spool: source and motion frames are decoded as their clips play."""
    return 0


def plan_proxies(edit, settings, source_map, size, root, ffmpeg, progress):
    """Smaller copies of sources much larger than a preview needs, cached in cuts/.cache/: {alias: info}."""
    proxies = {}
    width, height = size
    aspect = width / height
    uses = {}
    # A moving overlay keeps its own file: a proxy (H.264) would drop its transparency.
    moving = {overlay['src'] for overlay in edit.get('overlays', []) if overlay.get('kind') == 'video'}
    for item in edit['picture']:
        if item['src'] in source_map.sources and item['src'] not in moving:
            crop = item.get('crop', {})
            zoom = float(crop.get('zoom', 1.0))
            if crop.get('path') == 'auto' and 'zoom' not in crop and item.get('fit', 'cover') == 'cover':
                zoom = load_sibling('reframe').MAX_AUTO_ZOOM
            uses[item['src']] = max(uses.get(item['src'], 1.0), zoom)
    for alias, zoom in sorted(uses.items()):
        ffprobe = find_tool('ffprobe')
        if not ffprobe:
            raise ValueError('ffprobe is required to plan square-pixel proxies')
        command = [ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json',
                   str(source_map.path(alias))]
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise ValueError(f'cannot inspect display geometry for {alias}: {result.stderr[-300:]}')
        streams = json.loads(result.stdout).get('streams') or []
        dims = None
        if streams:
            geometry = load_sibling('render_common').display_geometry(streams[0])
            dims = (geometry['width'], geometry['height'])
        if not dims:
            continue
        sw, sh = dims
        crop_w, crop_h = (sh * aspect, sh) if sw / sh > aspect else (sw, sw / aspect)
        scale = max(width / crop_w, height / crop_h) * zoom
        if scale >= PROXY_BELOW:
            continue
        pw, ph = even(sw * scale), even(sh * scale)
        source = source_map.sources[alias]
        cache = root / 'cuts' / '.cache'
        cache.mkdir(parents=True, exist_ok=True)
        path = cache / f'{alias}-{str(source.get("sha256") or "nohash")[:12]}-square-{pw}x{ph}.mp4'
        if not path.is_file():
            progress(f'making a {pw}x{ph} proxy of {alias}')
            partial = path.with_name(path.stem + '.partial.mp4')
            duration = source_map.duration(alias)
            bound = ['-t', f'{duration + 1:.3f}'] if duration else []
            run_command([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', str(source_map.path(alias)),
                         '-map', '0:v:0', '-an', '-vf', f'scale={pw}:{ph}:flags=bicubic,setsar=1',
                         '-fps_mode', 'passthrough',
                         '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '16', '-pix_fmt', 'yuv420p', *bound,
                         str(partial)], f'proxy for {alias}', seconds=max(1800, int(duration * 3)))
            os.replace(partial, path)
        proxies[alias] = {'file': path, 'width': pw, 'height': ph,
                          'rate': float(source_map.fps(alias) or settings['fps'])}
    return proxies


def stop_tree(process):
    """Stop a process and everything it started (assemble.py's FFmpeg children)."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
    else:
        process.kill()
    process.wait()


def folder_bytes(folder):
    """The total size of the files under a folder."""
    total = 0
    for parent, _, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(parent, name))
            except OSError:
                continue
    return total


def watch(command, folder, seconds_limit, byte_limit, progress):
    """Run a process, stopping it (and its children) if it runs longer than seconds_limit or the files under folder
    grow past byte_limit: a hung FFmpeg filter can otherwise write without end. Returns (exit code, output)."""
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace')
    captured = {}
    reader = threading.Thread(target=lambda: captured.update(zip(('out', 'err'), process.communicate())),
                              daemon=True)
    reader.start()
    started = time.time()
    last_progress = started
    while True:
        reader.join(0.5)
        if not reader.is_alive():
            break
        elapsed = time.time() - started
        written = folder_bytes(folder)
        if written > byte_limit or elapsed > seconds_limit:
            stop_tree(process)
            reader.join()
            reason = (f'wrote {written / 1024 ** 3:.1f} GB, more than the {byte_limit / 1024 ** 3:.1f} GB this render '
                      'can need' if written > byte_limit else f'ran longer than {seconds_limit:.0f} s')
            raise RuntimeError(f'{Path(command[2]).name if len(command) > 2 else command[0]} {reason}; stopped')
        if time.time() - last_progress >= 2.0:
            progress(elapsed)
            last_progress = time.time()
    return process.returncode, captured.get('out', '') + captured.get('err', '')


def run_assemble(edit_path, out_dir, spool_gib, progress, seconds_limit, byte_limit, every_frame=False):
    """Run assemble.py on an edit under the watchdog; returns its exit code and output."""
    command = [sys.executable, '-I', str(HERE / 'assemble.py'), str(edit_path), '--out', str(out_dir / 'picture.mp4'),
               '--json', str(out_dir / 'assemble-report.json'), '--spool-gib', f'{spool_gib:.2f}']
    if every_frame:
        command.append('--every-frame')
    return watch(command, out_dir, seconds_limit, byte_limit, progress)


def render_budget(render_edit, spool, length, size):
    """Watchdog budget for audio parts and tracks, three encoded picture copies and 1 GiB of extra space.

    The legacy raw-spool estimate is now zero; this is a watchdog ceiling, not a free-space prediction.
    """
    audio = (2 * len(render_edit['audio']) + 4) * length * 48000 * 8
    picture = 3 * math.ceil(length * 60) * size[0] * size[1]
    return int(spool + audio + picture + 1024 ** 3)


def mux_preview(ffmpeg, picture, stems, total, fades, out, frames=None):
    """preview.mp4: the assembled picture with the stems mixed to stereo AAC. A limiter at -1 dBFS keeps most overs
    out; on a loud source the AAC encoder can still overshoot full scale (mastering at delivery limits true peak)."""
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', str(picture)]
    for stem in stems:
        command += ['-i', str(stem)]
    if stems:
        inputs = ''.join(f'[{number + 1}:a]' for number in range(len(stems)))
        chain = (f'{inputs}amix=inputs={len(stems)}:duration=longest:normalize=0' if len(stems) > 1
                 else f'{inputs}anull')
    else:
        command += ['-f', 'lavfi', '-t', f'{total:.6f}', '-i', 'anullsrc=r=48000:cl=stereo']
        chain = '[1:a]anull'
    if fades.get('in'):
        chain += f',afade=t=in:st=0:d={fades["in"]:.3f}'
    if fades.get('out'):
        chain += f',afade=t=out:st={max(0.0, total - fades["out"]):.4f}:d={fades["out"]:.3f}'
    # At 0.98 the AAC encoder overshot to +1.5 dBFS on a loud film scene; at 0.891 (-1 dBFS) it stayed at -0.1.
    chain += ',alimiter=limit=0.891:level=false:latency=true,apad[mix]'
    command += ['-filter_complex', chain, '-map', '0:v', '-map', '[mix]', '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', '-t', f'{total:.6f}']
    # The picture input already has the planned frame count. A video-frame limit stops muxing audio early.
    command.append(str(out))
    run_command(command, 'preview mux')


def mix_for_master(ffmpeg, stems, total, fades, output):
    """Sum float stems with headroom and fades before loudness processing."""
    if not stems:
        raise ValueError('dialogue master needs an audio stem; render without --master for a silent film')
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y']
    for stem in stems:
        command += ['-i', str(stem)]
    inputs = ''.join(f'[{number}:a]' for number in range(len(stems)))
    chain = (f'{inputs}amix=inputs={len(stems)}:duration=longest:normalize=0' if len(stems) > 1
             else f'{inputs}anull')
    if fades.get('in'):
        chain += f',afade=t=in:st=0:d={fades["in"]:.6f}'
    if fades.get('out'):
        chain += f',afade=t=out:st={max(0.0, total - fades["out"]):.6f}:d={fades["out"]:.6f}'
    chain += f',apad=whole_dur={total:.9f}[mix]'
    command += ['-filter_complex', chain, '-map', '[mix]', '-t', f'{total:.9f}',
                '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le', str(output)]
    run_command(command, 'float master mix')


def loudnorm_report(stderr):
    """Read FFmpeg's final loudnorm measurements, including the actual processing mode."""
    for block in reversed(re.findall(r'\{[^{}]*\}', stderr, re.DOTALL)):
        try:
            report = json.loads(block)
        except json.JSONDecodeError:
            continue
        if 'input_i' in report and 'normalization_type' in report:
            return report
    raise RuntimeError('FFmpeg did not report loudnorm measurements or processing mode')


def loudnorm_passes(ffmpeg, source, output, target, ceiling=-1.5):
    """Perform both passes and retain the measurements and actual second-pass mode."""
    base = f'loudnorm=I={target:g}:TP={ceiling:g}:LRA=11'
    first = run_command([ffmpeg, '-hide_banner', '-nostdin', '-i', str(source), '-af', base + ':print_format=json',
                         '-ar', '48000', '-f', 'null', '-'], 'loudness analysis')
    measured = loudnorm_report(first.stderr)
    fields = (('input_i', 'measured_I'), ('input_tp', 'measured_TP'), ('input_lra', 'measured_LRA'),
              ('input_thresh', 'measured_thresh'), ('target_offset', 'offset'))
    values = []
    for key, option in fields:
        try:
            number = float(measured[key])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError(f'no usable {key} loudness reading; inspect the sound') from error
        if not math.isfinite(number):
            raise ValueError(f'no finite {key} loudness reading; silence cannot be normalized')
        values.append(f'{option}={number:.6f}')
    target_range = min(50, max(11, math.ceil(float(measured['input_lra'])) + 1))
    second_base = f'loudnorm=I={target:g}:TP={ceiling:g}:LRA={target_range}'
    chain = second_base + ':' + ':'.join(values) + ':linear=true:print_format=json'
    second = run_command([ffmpeg, '-hide_banner', '-nostdin', '-y', '-i', str(source), '-af', chain,
                          '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le', str(output)], 'loudness master')
    return measured, loudnorm_report(second.stderr)


def mux_master(ffmpeg, picture, master, total, frames, out):
    """Encode the mastered audio once, preserving the already rendered picture."""
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', str(picture), '-i', str(master),
               '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
               '-ar', '48000', '-ac', '2', '-movflags', '+faststart', '-movie_timescale', '48000',
               '-t', f'{total:.9f}']
    command.append(str(out))
    run_command(command, 'master mux')


def verify_mux_output(ffprobe, path, frames, duration, notes):
    """Verify decoded picture frames and the delivered audio stream's sample-clock duration."""
    probe = run_command([ffprobe, '-v', 'error', '-threads', '8', '-select_streams', 'v:0', '-count_frames',
                         '-show_entries', 'stream=nb_read_frames', '-of', 'json', str(path)], 'mux frame check')
    streams = json.loads(probe.stdout).get('streams') or []
    value = (streams[0] if streams else {}).get('nb_read_frames')
    if not str(value).isdigit() or int(value) != frames:
        raise ValueError(f'muxed picture has {value} decoded frames, expected {frames}')
    probe = run_command([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                         'stream=sample_rate,duration_ts,time_base', '-of', 'json', str(path)], 'mux audio check')
    streams = json.loads(probe.stdout).get('streams') or []
    if not streams:
        notes.append('muxed audio duration could not be checked; inspect the delivery')
        return
    audio = streams[0]
    try:
        sample_rate = int(audio['sample_rate'])
        actual = round(int(audio['duration_ts']) * Fraction(audio['time_base']) * sample_rate)
        expected = round(duration * sample_rate)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        notes.append('muxed audio sample count could not be checked; inspect the delivery')
        return
    if abs(actual - expected) > 1:
        notes.append(f'muxed audio has {actual} samples, expected {expected}; inspect the end of the sound')


def measure_master(ffmpeg, ffprobe, delivered, platform, target, target_source, first, second):
    """Probe delivery rate and meter its AAC and a simulated downstream AAC re-encode."""
    probe = run_command([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_entries',
                         'stream=sample_rate,channels,codec_name', '-of', 'json', str(delivered)],
                        'master delivery probe')
    streams = json.loads(probe.stdout).get('streams') or []
    if not streams:
        raise ValueError('master delivery has no audio stream')
    stream = streams[0]
    if int(stream.get('sample_rate', 0)) != 48000:
        raise ValueError('master delivery sample rate is not 48000 Hz')
    qc = load_sibling('qc_file')
    return {'version': 1, 'platform': platform, 'target_lufs': target, 'target_source': target_source,
            'target_tolerance_lu': .5, 'requested_true_peak_dbtp': -1.5, 'sample_rate_hz': 48000,
            'delivery_stream': stream,
            'first_pass': first, 'second_pass': second, 'actual_mode': second.get('normalization_type'),
            'delivered_aac': qc.loudness(ffmpeg, str(delivered)),
            'simulated_aac_reencode': qc.lossy_true_peak(ffmpeg, str(delivered), '128k')}


def master_warnings(report):
    """Make fallback, missing measurements, and unmet delivery targets visible."""
    notes = []
    mode = report.get('actual_mode')
    if str(mode).lower() != 'linear':
        notes.append(f'loudnorm used {mode or "an unknown mode"}, not requested linear mode; listen to the master')
    delivered = report.get('delivered_aac') or {}
    loud = delivered.get('integrated_lufs')
    peak = delivered.get('true_peak_dbtp')
    if loud is None:
        notes.append('delivered AAC loudness could not be measured; run qc_file.py on the master')
    # The meter rounds to 0.1 LU, so treat its tolerance boundary as needing review.
    elif abs(loud - report['target_lufs']) >= report.get('target_tolerance_lu', .5):
        notes.append(f'delivered AAC measured {loud:.1f} LUFS, target {report["target_lufs"]:g} LUFS')
    if peak is None:
        notes.append('delivered AAC true peak could not be measured; run qc_file.py on the master')
    elif peak > report['requested_true_peak_dbtp'] + .05:
        notes.append(f'delivered AAC true peak {peak:.2f} dBTP exceeds the requested '
                     f'{report["requested_true_peak_dbtp"]:g} dBTP mastering ceiling')
    reencode = report.get('simulated_aac_reencode') or {}
    peak = reencode.get('true_peak_dbtp')
    if peak is None:
        notes.append('true peak after simulated AAC re-encode could not be measured; check FFmpeg AAC support')
    elif peak > -1:
        notes.append(f'simulated AAC re-encode true peak {peak:.1f} dBTP exceeds -1 dBTP')
    return notes


def sync_offset(edit, starts, report_path):
    """The largest difference between where assemble.py put each picture item and where the plan put it."""
    report = project.load_json(report_path, {})
    snaps = report.get('snaps', [])
    picture = [snap_item for snap_item in snaps if snap_item.get('clock') in ('video PTS', 'source edit time')]
    if len(picture) != 2 * len(edit['picture']):
        return None
    actual, worst = 0.0, 0.0
    for number, item in enumerate(edit['picture']):
        worst = max(worst, abs(actual - starts[number]))
        first, last = picture[2 * number]['snapped'], picture[2 * number + 1]['snapped']
        following = edit['picture'][number + 1] if number + 1 < len(edit['picture']) else None
        overlap = following.get('join', {}).get('dur', 0) if following else 0
        actual += (last - first) / float(item.get('speed', 1)) - overlap
    return worst


# ----------------------------------------------------------------------------------------------- render command

class Job:
    """The render's entry in status.json's running list, with an estimated progress."""

    def __init__(self, root, name):
        self.root = root
        self.name = f'render {name}'
        self.started = project.now()
        self.progress = 0.0
        self.lock = threading.Lock()

    def update(self, progress, line=None):
        """Write the job's progress (and optionally the status line)."""
        with self.lock, project.file_lock(Path(self.root) / 'status.json'):
            self.progress = max(self.progress, min(0.99, progress))
            status = project.read_status(self.root)
            running = [job for job in status.get('running') or [] if job.get('job') != self.name]
            # The process ID lets the status line and the room drop a render that was killed mid-way.
            running.append({'job': self.name, 'started': self.started, 'progress': round(self.progress, 2),
                            'pid': os.getpid()})
            fields = {'running': running}
            if line:
                fields['line'] = line
            project._update_status(self.root, fields)

    def finish(self, **fields):
        """Remove the job from the running list and merge any other status fields."""
        with self.lock, project.file_lock(Path(self.root) / 'status.json'):
            status = project.read_status(self.root)
            running = [job for job in status.get('running') or [] if job.get('job') != self.name]
            project._update_status(self.root, dict(running=running, **fields))


def staging_paths(root, name):
    """The staging folder (renamed into place at the end) and the scratch folder for one render, after removing
    any left by a render that was stopped before it could clean up. Call it only while holding the project's
    render lock (render_version does), so no running render's folders are removed."""
    cuts = root / 'cuts'
    cuts.mkdir(parents=True, exist_ok=True)
    for stale in list(cuts.glob('.v*.partial')) + list(cuts.glob('.v*.work')):
        remove_tree(stale)
    return cuts / f'.{name}.partial', cuts / f'.{name}.work'


def remove_tree(path):
    """Delete a scratch folder, tolerating files still being released on Windows."""
    for _ in range(5):
        if not path.exists():
            return
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            time.sleep(0.5)


def publish(staging, final):
    """Rename the finished staging folder to its version name."""
    for attempt in range(10):
        try:
            os.replace(staging, final)
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(0.5)


def render_version(root, args, plan, settings, source_map, problems, film_text):
    """Compile and render the next version under the project's render lock; returns (version name, notes, manifest).

    The lock (cuts/.render.lock) is held from choosing the version number until the version is published and made
    current, so two renders of one project never take the same number or remove each other's staging folders. A
    second render waits up to RENDER_WAIT seconds, then stops and names the process that holds the lock; a lock
    left by a render that died is broken at once."""
    with contextlib.ExitStack() as stack:
        try:
            stack.enter_context(project.file_lock(root / 'cuts' / 'render', timeout=RENDER_WAIT))
        except TimeoutError:
            _, pid = project._lock_holder(root / 'cuts' / '.render.lock')
            holder = f'process {pid}' if pid else 'another process'
            raise RuntimeError(f'another render of this project ({holder}) is still running after '
                               f'{RENDER_WAIT} s; wait for it to finish, then render again') from None
        return render_locked(root, args, plan, settings, source_map, problems, film_text)


def render_locked(root, args, plan, settings, source_map, problems, film_text):
    """Compile and render the next version while holding the render lock."""
    ffmpeg, ffprobe = find_tool('ffmpeg'), find_tool('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('FFmpeg and ffprobe are needed to render')
    name = project.next_version(root)
    parent = project.current_version(root)
    staging, work = staging_paths(root, name)
    remove_tree(staging)
    remove_tree(work)
    staging.mkdir()
    work.mkdir()
    job = Job(root, name)
    if (project.read_status(root).get('stages') or {}).get('plan') in ('todo', 'now'):
        project.update_status(root, stages={'plan': 'done'})
    project.set_stage(root, 'cut')
    job.update(0.02, line=f'rendering {name}')
    notes = [f"film.md:{item['line']}: {item['message']} {item['suggestion']}".strip()
             for item in problems.items if item['severity'] == 'warning'
             and ('transcript review' in item['message'] or 'transcript energy review' in item['message']
                  or COVER_NOTE in item['message'])]
    began = time.time()
    try:
        captions_file = build_captions(plan, staging, work, notes, settings.get('size'), bool(settings['captions']))
        edit, starts = build_edit(plan, settings, source_map, staging, problems, captions_file)
        if plan.get('layer_uses'):
            settings['_layers'] = layer_records(plan, root)
        if any(asset['kind'] == 'title' for asset in plan['assets'].values()):
            info = title_font_info(settings)
            settings['_title_font_info'] = info
            if info['actual'] != 'Pillow default':
                settings['_title_font_path'] = info['actual']
            if info['fallback']:
                warning = f"requested title font {info['requested']} could not load; using {info['actual']}"
                print('warning: ' + warning, file=sys.stderr, flush=True)
                notes.append(warning)
        make_assets(plan, settings, source_map, staging, ffmpeg)
        job.update(0.1)
        size = render_size(settings['size'], args.final)
        render_edit = json.loads(json.dumps(edit))
        render_edit['size'] = list(size)
        # A range the map could not know is short (no decoded ends in it) is refused by assemble.py, naming its line.
        for item, seg in zip(render_edit['picture'], plan['segments']):
            if seg['key'] in source_map.sources:
                item['line'] = seg['line']
        for overlay in render_edit.get('overlays', []):
            if overlay.get('kind') == 'image' and overlay.get('src') == 'gen-fade':
                overlay['role'] = CUT_FADE_CUE_ROLE
        # assemble.py writes edit-cues.json v2 bound to this paper edit: film.md and the sources it was cut from.
        render_edit['paper'] = {'film_md_sha256': hashlib.sha256(film_text.encode('utf-8')).hexdigest(),
                                'sources': source_identities(source_map, edit['sources'])}
        proxies = {} if args.final else plan_proxies(edit, settings, source_map, size, root, ffmpeg,
                                                     lambda text: job.update(0.12, line=f'rendering {name}: {text}'))
        for alias, proxy in proxies.items():
            original = render_edit['sources'][alias]
            render_edit['sources'][alias] = dict(original, file=relative_source(staging, proxy['file']),
                                                  audio_file=original['file'])
        project.save_json(staging / 'edit.json', edit)
        project.save_json(staging / 'edit-render.json', render_edit)
        spool = estimate_spool(render_edit, settings, source_map, proxies)
        free = shutil.disk_usage(work).free
        if free < 2 * 1024 ** 3:
            raise RuntimeError(f'this render needs at least 2 GiB free for temporary picture and audio files; '
                               f'{free / 1024 ** 3:.1f} GiB is free; free some disk or shorten the film')
        spool_gib = 8.0
        frames = math.ceil(plan['duration'] * float(settings['fps']))
        expected = 3.0 + frames * (0.012 + size[0] * size[1] / 1e6 * 0.05) + spool / 1e9 * 2.0
        job.update(0.15, line=f'rendering {name}')

        check_plausible(render_edit, plan['duration'], plausible_limit(settings))

        def progress(elapsed):
            """Advance the estimated progress while assemble.py works."""
            job.update(0.15 + 0.7 * (1 - math.exp(-elapsed / expected)))

        code, output = run_assemble(staging / 'edit-render.json', work, spool_gib, progress, max(900.0, expected * 8),
                                    render_budget(render_edit, spool, plan['duration'], size),
                                    getattr(args, 'every_frame', False))
        (staging / 'edit-render.json').unlink()
        if code not in (0, 1):
            raise RuntimeError('assemble.py could not render: ' + output.strip()[-1500:])
        notes.extend(line[len('NOTE: '):] for line in output.splitlines() if line.startswith('NOTE: ')
                     and not line.startswith('NOTE: Caption burn was encoded again'))
        job.update(0.87)
        assembled = project.load_json(work / 'assemble-report.json', {}) or {}
        frames_out = assembled.get('frames') or frames
        settings['_picture_path'] = assembled.get('picture_path')
        settings['_hdr_sources'] = assembled.get('hdr_sources') or []
        length = frames_out / float(settings['fps'])
        end_captions_with_film(staging / 'captions', length, notes)
        stems = sorted(work.glob('*.wav'))
        master_report = None
        platform = getattr(args, 'master', None)
        if platform:
            explicit = getattr(args, 'master_target', None)
            target = explicit if explicit is not None else settings.get('loudness', -16.0)
            target_source = ('--master-target' if explicit is not None else 'film.md loudness'
                             if settings.get('loudness') is not None else
                             'working dialogue target; not a platform spec')
            mix = work / 'master-mix.wav'
            master = work / 'master-normalized.wav'
            mix_for_master(ffmpeg, stems, length, plan['fades'], mix)
            first, second = loudnorm_passes(ffmpeg, mix, master, target)
            mux_master(ffmpeg, work / 'picture.mp4', master, length, frames_out, staging / 'preview.mp4')
            master_report = measure_master(ffmpeg, ffprobe, staging / 'preview.mp4', platform, target,
                                           target_source, first, second)
            project.save_json(staging / 'audio-master.json', master_report)
            notes.extend(master_warnings(master_report))
            if target_source.startswith('working'):
                notes.append(f'{target:g} LUFS is a working dialogue target, not a published {platform} specification')
            settings['_audio_master'] = {'platform': platform, 'target_lufs': target, 'target_source': target_source,
                                         'actual_mode': master_report['actual_mode'], 'report': 'audio-master.json'}
        else:
            mux_preview(ffmpeg, work / 'picture.mp4', stems, length, plan['fades'], staging / 'preview.mp4', frames_out)
        verify_mux_output(ffprobe, staging / 'preview.mp4', frames_out, length, notes)
        if args.final and stems:
            (staging / 'stems').mkdir()
            for stem in stems:
                shutil.copy2(stem, staging / 'stems' / stem.name)
        for sidecar in ('assemble-report.json', 'declared.json', 'edit-cues.json', 'caption-burn.json'):
            if (work / sidecar).is_file():
                shutil.copy2(work / sidecar, staging / sidecar)
        cue_list = load_sibling('cue_list')
        if (staging / 'edit-cues.json').is_file():
            cue_path = staging / 'edit-cues.json'
            cue_document = project.load_json(cue_path, None)
            filtered = without_generated_fade_cues(cue_document)
            if filtered != cue_document:
                project.save_json(cue_path, filtered)
            cue_list.check(staging / 'edit-cues.json')   # the list every reader will load must read here
        offset = sync_offset(edit, starts, work / 'assemble-report.json')
        frame = 1 / float(settings['fps'])
        if offset is None:
            notes.append('picture boundaries could not be compared with the edit clock; inspect the assembly report '
                         'and check picture, sound and captions at each join')
        elif offset > frame + 1e-6:
            notes.append(f'picture drifts up to {offset * 1000:.0f} ms from the sound plan (variable frame rate '
                         'source?); check lip sync')
        job.update(0.93)
        lines = {'version': 1, 'film_version': name, 'duration_s': round(plan['duration'], 4),
                 'lines': plan['lines'], 'joins': plan['joins'], 'picture_changes': plan['picture_changes'],
                 'busy_cutting': plan['busy_cutting']}
        project.save_json(staging / 'lines.json', lines)
        project.write_atomic(staging / 'film.md', film_text)
        make_strips(staging, notes)
        changed = [alias for alias, stat in sorted(source_map.media_stats.items()) if alias in edit['sources']
                   and file_stat(source_map.path(alias)) != stat]
        if changed:
            raise RuntimeError(', '.join(changed) + ' changed while this version rendered, so it may mix two files; '
                               'nothing was published. Map it again if the change is intended, then render again.')
        sources = source_identities(source_map, edit['sources'])
        if source_map.lineup_used:
            settings['_lineup'] = source_map.lineup().used_record(source_map.lineup_used)
        identity = version_identity(cue_list, staging, film_text, sources)
        manifest = write_manifest(staging, name, parent, args, settings, size, film_text, notes, offset,
                                  sorted(proxies), time.time() - began, root, length, frames_out, sources, identity)
        publish(staging, root / 'cuts' / name)
    except BaseException as error:
        remove_tree(staging)
        job.finish(line=f'render {name} failed: {str(error)[:160]}')
        raise
    finally:
        remove_tree(work)
    project.set_current(root, name)
    number = int(name[1:])
    project.set_stage(root, 'check', line=f'v{number} rendered \u00b7 not checked yet')
    job.finish(current=name)
    return name, notes, manifest


def make_strips(staging, notes):
    """Screening strips (strip/strip-NN.jpg) made inside the version before its manifest seals it, when strip.py
    is installed beside this script."""
    if not (HERE / 'strip.py').is_file():
        return
    try:
        strip = load_sibling('strip')
        # captions.json keeps its words under "cues"; reading other keys left every render's strip without words.
        strip.make(staging / 'preview.mp4', staging / 'strip', strip.caption_words(staging / 'captions.json'),
                   strip.entries(staging / 'lines.json', ('lines', 'items')))
    except Exception as error:  # strips are a convenience: a failure must not lose the rendered version
        notes.append(f'screening strips not made: {error}')


def file_stat(path):
    """A file's size and modification time, or None when it is gone."""
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return stat.st_size, stat.st_mtime_ns


def source_identities(source_map, aliases):
    """Each mapped source a version used, as the map recorded it when the version was made (path, bytes, SHA-256,
    streams) and its transcript's SHA-256, so a later re-map cannot change what the version says it was cut from."""
    identities = {}
    for alias in sorted(alias for alias in aliases if alias in source_map.sources):
        source = source_map.sources[alias]
        words = source_map.root / 'map' / alias / 'words.json'
        identities[alias] = {'path': source.get('path'), 'bytes': source.get('bytes'), 'sha256': source.get('sha256'),
                             'video_stream': (source.get('video') or {}).get('index'),
                             'audio_stream': (source.get('audio') or {}).get('index'),
                             'words_sha256': sha256_file(words) if words.is_file() else None}
    return identities


def version_identity(cue_list, staging, film_text, sources):
    """manifest.json identity for a rendered paper version: its source (the paper fingerprint), the picture
    stream's packet hash and frame schedule (picture-timing.json, written here), the cue list's hash, and
    binding: receipt, since this render made the picture from what it fingerprinted."""
    paper = cue_list.paper_identity(hashlib.sha256(film_text.encode('utf-8')).hexdigest(), sources)
    found = cue_list.picture_identity(staging / 'preview.mp4')
    if found['schedule'] is not None:
        cue_list.write_schedule(found['schedule'], staging / 'picture-timing.json')
    cues = staging / 'edit-cues.json'
    listed = cue_list.check(cues) if cues.is_file() else None
    return {'source': {'kind': 'paper', 'path': 'film.md', 'sha256': paper['sha256'],
                       'film_md_sha256': paper['film_md_sha256']},
            'picture_sha256': found['sha256'], 'picture_timing': cue_list.timing_block(found['schedule']),
            'binding': 'receipt', 'receipt': None,
            'cues_sha256': sha256_file(cues) if cues.is_file() else None,
            'cues_provenance': listed.provenance if listed else None,
            'conform_sha256': None, 'mix': None, 'registered': False}


def write_manifest(staging, name, parent, args, settings, size, film_text, notes, offset, proxies, seconds, root,
                   length, frames=None, sources=None, identity=None):
    """manifest.json: the version's identity, its parent, sizes, every file's SHA-256 and its sources' identities."""
    resolved = [note.strip() for note in (args.resolves or '').split(',') if note.strip()]
    known = {note.get('id') for note in (project.load_json(root / 'notes.json', {}) or {}).get('notes', [])}
    for note in resolved:
        if note not in known:
            notes.append(f'--resolves names {note}, which is not in notes.json')
    files = {}
    for path in sorted(staging.rglob('*')):
        if path.is_file() and path.name != 'manifest.json':
            files[path.relative_to(staging).as_posix()] = sha256_file(path)
    manifest = {'version': name, 'parent': parent, 'created': project.now(), 'label': args.label or '',
                'duration_s': round(length, 4), 'frames': frames, 'size': list(settings['size']),
                'fps': settings['fps_text'],
                'film_md_sha256': hashlib.sha256(film_text.encode('utf-8')).hexdigest(), 'files': files,
                'sources': sources or {},
                'notes_resolved': resolved, 'title': settings['title'], 'preview_size': list(size),
                'final': bool(args.final), 'skill_version': project.skill_version(),
                'captions': sorted(settings['captions']), 'proxies': proxies, 'render_seconds': round(seconds, 1),
                'picture_path': settings.get('_picture_path'),
                'audio_processing': {'intermediate': '48 kHz stereo float PCM',
                                     'preview_mix': ('two-pass dialogue master before AAC'
                                                     if settings.get('_audio_master') else
                                                     'summed without normalization; limiter at -1 dBFS before AAC')},
                'audio_master': settings.get('_audio_master'),
                'title_font': settings.get('_title_font_info'),
                'sync_max_offset_s': round(offset, 4) if offset is not None else None, 'notes': notes}
    if identity is not None:
        manifest['identity'] = identity
    preference = preference_summary(root, project.load_json(staging / 'lines.json', {}))
    if preference is not None:
        manifest['preferences'] = preference
    if settings.get('_layers'):
        manifest['layers'] = settings['_layers']
    if settings.get('_lineup'):
        manifest['lineup'] = settings['_lineup']
    if settings.get('_hdr_sources'):
        manifest['hdr_sources'] = [{'alias': alias} for alias in settings['_hdr_sources']]
    project.save_json(staging / 'manifest.json', manifest)
    return manifest


def picture_path_text(path):
    """Which way the render drew the picture, for the printed output."""
    path = path or {}
    if path.get('path') == 'ffmpeg':
        return 'FFmpeg (a plain cut; Python chose the frames and drew none)'
    return f"every frame through Python ({path.get('reason', 'reason not recorded')})"


def resolve_commands(root, resolved, version):
    """The screen.py resolve command for each named note still open in notes.json; closed and unknown notes get
    none (an unknown one is already a render note)."""
    notes = (project.load_json(root / 'notes.json', {}) or {}).get('notes', [])
    status = {note.get('id'): note.get('status') for note in notes if isinstance(note, dict)}
    script = HERE / 'screen.py'
    return [f'"{sys.executable}" "{script}" resolve "{root}" {note} --in {version} '
            f'--reply "<what changed, for the person>"' for note in resolved if status.get(note) == 'open']


def run_render(args):
    """cut.py render: check, then compile and render the next version."""
    if getattr(args, 'master', None) and not args.final:
        raise ValueError('--master requires --final')
    if getattr(args, 'master_target', None) is not None:
        if not getattr(args, 'master', None):
            raise ValueError('--master-target requires --master')
        if not math.isfinite(args.master_target) or not -70 <= args.master_target <= -5:
            raise ValueError('--master-target must be between -70 and -5 LUFS')
    root = load_project(args.project)
    text, settings, entries, plan, problems, source_map = analyse(root, verify_media=True)
    if getattr(args, 'master', None):
        target = args.master_target if args.master_target is not None else settings.get('loudness', -16.0)
        if not math.isfinite(target) or not -70 <= target <= -5:
            raise ValueError('the master loudness target must be between -70 and -5 LUFS')
    if problems.count('error'):
        # Exit 2 is what it means everywhere: the render could not run, so nothing was made to look at.
        if args.json:
            print(json.dumps({'status': 'blocked', 'version': None, 'problems': problems.items}, indent=1,
                             ensure_ascii=False))
            return 2
        print_problems(problems)
        print(f'not rendered: {problems.count("error")} error(s) in film.md')
        return 2
    name, notes, manifest = render_version(root, args, plan, settings, source_map, problems, text)
    closing = resolve_commands(root, manifest.get('notes_resolved') or [], name)
    if args.json:
        print(json.dumps({'status': 'rendered', 'version': name, 'manifest': manifest, 'problems': problems.items,
                          'resolve_commands': closing}, indent=1, ensure_ascii=False))
    else:
        print_problems(problems)
        size = manifest['preview_size']
        print(f'rendered {name}: {manifest["duration_s"]:.2f} s, preview {size[0]}x{size[1]} at {manifest["fps"]} fps '
              f'in {manifest["render_seconds"]:.0f} s -> cuts/{name}/preview.mp4')
        print('picture: ' + picture_path_text(manifest.get('picture_path')))
        if manifest.get('preferences'):
            print(manifest['preferences']['summary'])
        for note in notes:
            print('note: ' + note)
        if closing:
            print('--resolves only recorded these notes in manifest.json; after reviewing ' + name + ', close each '
                  'still-open note with a reply for the person:')
            for command in closing:
                print('  ' + command)
    return 1 if notes or problems.count('warning') else 0


# ----------------------------------------------------------------------------------------------- diff

def line_key(entry):
    """What makes two versions' lines the same line: kind, source and where it starts in the source."""
    if entry['kind'] in ('title', 'card'):
        return (entry['kind'], entry.get('text'))
    if entry['kind'] == 'pause':
        return ('pause',)
    return (entry['kind'], entry.get('alias'), round(entry['start'], 1) if entry.get('start') is not None else None)


def line_content(entry):
    """Everything about a line that a change would touch, its source included."""
    return (entry['kind'], entry.get('alias'), entry.get('text'), entry.get('start'), entry.get('end'),
            entry.get('seconds'), entry.get('freeze'), json.dumps(entry.get('mods'), sort_keys=True, default=str))


def setting_text(key, value):
    """A front-matter setting as a person writes it, for the diff."""
    if value is None:
        return 'default'
    if key == 'size':
        return f'{value[0]}x{value[1]}'
    if key == 'captions':
        return ', '.join(sorted(value)) or 'none'
    if key == 'crop' and isinstance(value, tuple):
        return f'{value[0]:g},{value[1]:g}'
    if key == 'bars':
        return 'allow' if value else 'no'
    if key == 'caption_breaks':
        return ', '.join(pin['word'] for pin in value) or 'none'
    if isinstance(value, float):
        return f'{value:g}'
    return str(value)


def compare_settings(old, new):
    """Front-matter settings that differ between two versions, and whether each was a preview or a final render."""
    changes = []
    for key in OUTPUT_SETTINGS:
        before, after = old.get(key), new.get(key)
        if key == 'fps':
            before, after = old.get('fps_text'), new.get('fps_text')
        elif key == 'bars':
            before, after = bool(before), bool(after)
        elif key == 'caption_breaks':
            before, after = before or [], after or []
        if setting_text(key, before) != setting_text(key, after):
            changes.append({'setting': key, 'from': setting_text(key, before), 'to': setting_text(key, after)})
    return changes


def modifier_text(name, value):
    """One parsed modifier in a readable form for a line comparison."""
    if name == 'join':
        return f'{value[0]} {value[1]:g}'
    if name in ('sound', 'gain'):
        return f'{name} {value:g}dB' if name == 'sound' else f'{value:g}dB'
    if name == 'crop' and isinstance(value, (tuple, list)):
        return f'crop {value[0]:g},{value[1]:g}'
    if name == 'speed':
        return f'x{value:g}'
    if name == 'offset':
        return f'+{value:g}'
    if name in ('card', 'hold') and value is True:
        return name
    if name == 'at':
        return f'at {fmt(value)}'
    label = name.replace('_', ' ')
    if isinstance(value, (int, float)):
        return f'{label} {value:g}'
    return f'{label} {value}'


def describe(entry):
    """A readable form of a line, retaining its full text, strike marks and modifiers."""
    parts = [entry['kind'], entry.get('alias') or '']
    if entry.get('sync'):
        parts.append('sync')
    if entry.get('start') is not None:
        parts.append(f'{fmt(entry["start"])}-{fmt(entry["end"])}')
    if entry.get('seconds') is not None:
        parts.append(f'{entry["seconds"]:g} s')
    text = entry.get('text') or ''
    parts.append(f'"{text}"' if text else '')
    mods = entry.get('mods') or {}
    if mods:
        parts.append('{' + ', '.join(modifier_text(name, value) for name, value in sorted(mods.items())) + '}')
    return ' '.join(part for part in parts if part)


def compare_lines(old_entries, new_entries):
    """Lines added, removed and changed between two parsed paper edits."""
    old_keys = [line_key(entry) for entry in old_entries]
    new_keys = [line_key(entry) for entry in new_entries]
    matcher = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)
    added, removed, changed = [], [], []

    def change(old, new):
        """Record a line present in both versions whose content differs."""
        if line_content(old) != line_content(new):
            changed.append({'from_line': old['line'], 'to_line': new['line'], 'from': describe(old),
                            'to': describe(new)})

    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == 'equal':
            for old, new in zip(old_entries[a0:a1], new_entries[b0:b1]):
                change(old, new)
            continue
        olds, news = old_entries[a0:a1], new_entries[b0:b1]
        paired = 0
        if tag == 'replace':
            for old, new in zip(olds, news):
                if old['kind'] != new['kind']:
                    break
                change(old, new)
                paired += 1
        removed.extend({'line': old['line'], 'what': describe(old)} for old in olds[paired:])
        added.extend({'line': new['line'], 'what': describe(new)} for new in news[paired:])
    return added, removed, changed


def kept_words(lines):
    """{word ID: text} for every kept word in a lines.json."""
    result = {}
    rows = lines if isinstance(lines, list) else (lines or {}).get('lines', [])
    for record in rows:
        for word in record.get('words', []) if isinstance(record, dict) else []:
            if isinstance(word, dict) and word.get('id'):
                result[word['id']] = word.get('text', '')
    return result


def word_changes_by_line(lines, changed, kind):
    """Group removed or restored words by their source line in the appropriate version."""
    wanted = {word['id'] for word in changed}
    groups = []
    rows = lines if isinstance(lines, list) else (lines or {}).get('lines', [])
    for row in rows:
        words = [word for word in row.get('words', []) if word.get('id') in wanted]
        if words:
            groups.append({'line': row.get('line'), 'source': row.get('source'), kind: words})
    return groups


def compare_captions(old, new):
    """Caption cues added, removed, retimed and the changed texts."""
    def cues(data):
        return [(round(float(cue['start']), 2), round(float(cue['end']), 2), cue.get('text', '').replace('\n', ' '))
                for cue in (data or {}).get('cues', [])]
    before, after = cues(old), cues(new)
    matcher = difflib.SequenceMatcher(None, [cue[2] for cue in before], [cue[2] for cue in after], autojunk=False)
    added, removed, moved, retimed, texts = 0, 0, 0, 0, []
    for tag, a0, a1, b0, b1 in matcher.get_opcodes():
        if tag == 'equal':
            for x, y in zip(before[a0:a1], after[b0:b1]):
                if x[:2] != y[:2]:
                    if abs((x[1] - x[0]) - (y[1] - y[0])) < .015:
                        moved += 1
                    else:
                        retimed += 1
            continue
        removed += a1 - a0
        added += b1 - b0
        texts.extend({'from': cue[2]} for cue in before[a0:a1])
        texts.extend({'to': cue[2]} for cue in after[b0:b1])
    return {'changed': bool(added or removed or moved or retimed), 'added': added, 'removed': removed,
            'moved': moved, 'retimed': retimed,
            'cues_from': len(before), 'cues_to': len(after), 'texts': texts[:40]}


def diff_versions(root, old, new):
    """The diff report between two version folders."""
    folders = {}
    for name in (old, new):
        folder = root / 'cuts' / name
        if not (folder / 'film.md').is_file():
            raise ValueError(f'no version {name} in {root / "cuts"}')
        folders[name] = folder
    parsed, front = {}, {}
    for name, folder in folders.items():
        settings, entries = parse_film(project.read_text(folder / 'film.md'), Problems(), root=root)
        parsed[name] = entries
        render = (project.load_json(folder / 'manifest.json', {}) or {}).get('final')
        front[name] = dict(settings, render=None if render is None else 'final' if render else 'preview')
    added, removed, changed = compare_lines(parsed[old], parsed[new])
    old_lines = project.load_json(folders[old] / 'lines.json', {})
    new_lines = project.load_json(folders[new] / 'lines.json', {})
    words_old = kept_words(old_lines)
    words_new = kept_words(new_lines)
    cut = [{'id': key, 'text': words_old[key]} for key in words_old if key not in words_new]
    restored = [{'id': key, 'text': words_new[key]} for key in words_new if key not in words_old]
    durations = [float((project.load_json(folders[name] / 'manifest.json', {}) or {}).get('duration_s') or 0)
                 for name in (old, new)]
    captions = compare_captions(project.load_json(folders[old] / 'captions.json', {}),
                                project.load_json(folders[new] / 'captions.json', {}))
    report = {'from': old, 'to': new, 'settings': compare_settings(front[old], front[new]),
              'lines': {'added': added, 'removed': removed, 'changed': changed},
              'words': {'cut': cut, 'restored': restored,
                        'by_line': word_changes_by_line(old_lines, cut, 'cut')
                        + word_changes_by_line(new_lines, restored, 'restored')},
              'duration': {'from_s': durations[0], 'to_s': durations[1],
                           'change_s': round(durations[1] - durations[0], 4)},
              'captions': captions}
    report['summary'] = diff_summary(report)
    return report


def diff_working(root, old):
    """What changed in the working film.md since a version was rendered: settings and lines, not yet rendered."""
    folder = root / 'cuts' / old
    if not (folder / 'film.md').is_file():
        raise ValueError(f'no version {old} in {root / "cuts"}')
    if not (root / 'film.md').is_file():
        raise ValueError(f'no film.md in {root}')
    working_problems = Problems()
    old_settings, old_entries = parse_film(project.read_text(folder / 'film.md'), Problems(), root=root)
    new_settings, new_entries = parse_film(project.read_text(root / 'film.md'), working_problems, root=root)
    errors = [item for item in working_problems.items if item['severity'] == 'error']
    render = (project.load_json(folder / 'manifest.json', {}) or {}).get('final')
    old_settings['render'] = new_settings['render'] = None if render is None else 'final' if render else 'preview'
    added, removed, changed = compare_lines(old_entries, new_entries)
    report = {'from': old, 'to': 'working', 'settings': compare_settings(old_settings, new_settings),
              'lines': {'added': added, 'removed': removed, 'changed': changed},
              'words': {'cut': [], 'restored': [], 'by_line': []}, 'errors': errors}
    counts = [f'{len(report["lines"][key])} {key}' for key in ('added', 'removed', 'changed') if report['lines'][key]]
    parts = [f'film.md since {old} (not rendered)']
    if errors:
        parts.append(f'{len(errors)} error{"s" if len(errors) > 1 else ""} in film.md, so what it says may not be '
                     f'what it shows (cut.py check): ' + '; '.join(f'line {item["line"]}: {item["message"]}'
                                                                    for item in errors[:3]))
    if report['settings']:
        parts.append('settings: ' + ', '.join(f'{row["setting"]} {row["from"]} -> {row["to"]}'
                                              for row in report['settings']))
    parts.append('lines: ' + (', '.join(counts) if counts else 'no change'))
    report['summary'] = '; '.join(parts)
    return report


def diff_summary(report):
    """One short paragraph a person can read."""
    lines = report['lines']
    parts = [f'{report["from"]} -> {report["to"]}: {report["duration"]["change_s"]:+.2f} s '
             f'({report["duration"]["from_s"]:.2f} -> {report["duration"]["to_s"]:.2f} s)']
    if report['settings']:
        parts.append('settings: ' + ', '.join(f'{row["setting"]} {row["from"]} -> {row["to"]}'
                                              for row in report['settings']))
    counts = [f'{len(lines[key])} {key}' for key in ('added', 'removed', 'changed') if lines[key]]
    parts.append('lines: ' + (', '.join(counts) if counts else 'no change'))
    words = report['words']
    if words['cut']:
        shown = ', '.join(f'"{word["text"]}"' for word in words['cut'][:10])
        parts.append(f'{len(words["cut"])} word{"s" if len(words["cut"]) > 1 else ""} cut ({shown})')
    if words['restored']:
        shown = ', '.join(f'"{word["text"]}"' for word in words['restored'][:10])
        parts.append(f'{len(words["restored"])} restored ({shown})')
    captions = report['captions']
    if captions['changed']:
        parts.append(f'captions: {captions["added"]} added, {captions["removed"]} removed, '
                     f'{captions.get("moved", 0)} moved, {captions["retimed"]} retimed')
    else:
        parts.append('captions unchanged')
    return '; '.join(parts)


def run_diff(args):
    """cut.py diff."""
    root = load_project(args.project)
    report = diff_versions(root, args.a, args.b) if args.b else diff_working(root, args.a)
    failed = 1 if report.get('errors') else 0
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return failed
    print(report['summary'])
    for key in ('added', 'removed'):
        for item in report['lines'][key]:
            print(f'  {key} line {item["line"]}: {item["what"]}')
    for item in report['lines']['changed']:
        print(f'  changed line {item["from_line"]} -> {item["to_line"]}: {item["from"]}  =>  {item["to"]}')
    for row in report['words']['by_line']:
        kind = 'cut' if 'cut' in row else 'restored'
        print(f'  line {row["line"]} ({row.get("source") or "source"}): {kind} '
              + ', '.join(word.get('text', '') for word in row[kind]))
    return failed


# ----------------------------------------------------------------------------------------------- draft

def parse_select(text):
    """('alias', phrase or None, (start, end) or None) from ALIAS:"phrase" or ALIAS:START-END."""
    alias, separator, rest = text.partition(':')
    rest = rest.strip()
    if not separator or not alias.strip() or not rest:
        raise ValueError(f'a select is ALIAS:"phrase" or ALIAS:START-END, not {text!r}')
    span = RANGE_AT_START.match(rest)
    if span and span.end() == len(rest):
        return alias.strip(), None, (project.parse_time(span.group(1)), project.parse_time(span.group(2)))
    return alias.strip(), unquote(rest), None


def find_phrase(words, phrase):
    """(first, last) word indices of a phrase in a transcript: exact, else the closest window; None if none fits."""
    target = normal_tokens(phrase)
    if not target or not words:
        return None
    tokens, owner = [], []
    for word in words:
        for token in normal_tokens(word['text']):
            tokens.append(token)
            owner.append(word['index'])
    size = len(target)
    for start in range(len(tokens) - size + 1):
        if tokens[start:start + size] == target:
            return owner[start], owner[start + size - 1]
    best, best_score = None, 0.0
    for width in range(max(1, size - 2), size + 3):
        for start in range(0, max(0, len(tokens) - width) + 1):
            score = difflib.SequenceMatcher(None, target, tokens[start:start + width], autojunk=False).ratio()
            if score > best_score:
                best, best_score = (owner[start], owner[min(len(owner) - 1, start + width - 1)]), score
    return best if best_score >= 0.75 else None


def draft_line(source_map, alias, words, first, last):
    """A spoken line for transcript words first..last, with a little pause each side."""
    start_word, end_word = words[first], words[last]
    before = words[first - 1]['end'] if first > 0 else 0.0
    after = words[last + 1]['start'] if last + 1 < len(words) else start_word['start'] + 1e9
    start = max(before + (start_word['start'] - before) / 2, start_word['start'] - 0.2, 0.0)
    end = min(end_word['end'] + (after - end_word['end']) / 2, end_word['end'] + 0.2)
    if source_map.duration(alias):
        end = min(end, source_map.duration(alias))
    text = ' '.join(str(word['text']).strip() for word in words[first:last + 1])
    return f'> {alias} {project.format_time(start)}-{project.format_time(end)} {text}', end - start


def run_draft(args):
    """cut.py draft: a first film.md from selects."""
    caption_problems = Problems()
    captions = parse_captions(args.captions, 1, caption_problems)
    if caption_problems.count('error'):
        raise ValueError(caption_problems.items[0]['message'])
    root = load_project(args.project)
    film = root / 'film.md'
    kept = {}
    if film.exists():
        # The direction is written before the selects (references/finding-the-story.md), so a draft keeps it, and a
        # film.md with no lines yet can be drafted into without --force.
        old_settings, old_entries = parse_film(project.read_text(film), Problems())
        kept = {key: old_settings[key].strip() for key in DIRECTION_KEYS if (old_settings.get(key) or '').strip()}
        if old_entries and not args.force:
            raise ValueError('film.md has lines; pass --force to replace them (the old one is kept as film.md.bak, '
                             'and its audience, takeaway and story are kept)')
    source_map = SourceMap(root)
    lines, missing, total = [], [], 0.0
    first_alias = None
    for select in args.select:
        alias, phrase, span = parse_select(select)
        if alias not in source_map.sources:
            missing.append(f'{select}: unknown alias {alias}')
            continue
        first_alias = first_alias or alias
        words = source_map.words(alias)
        if span is not None:
            if words and range_words(words, *span):
                indices = range_words(words, *span)
                lines.append(f'> {alias} {project.format_time(span[0])}-{project.format_time(span[1])} '
                             + ' '.join(str(words[index]['text']).strip() for index in indices))
            else:
                lines.append(f'- {alias} {project.format_time(span[0])}-{project.format_time(span[1])}')
            total += span[1] - span[0]
            continue
        if not words:
            missing.append(f'{select}: {alias} has no transcript')
            continue
        if source_map.stale_transcript(alias):
            missing.append(f'{select}: {alias}: {source_map.stale_transcript(alias)}; map it again, then transcribe '
                           f'it again or confirm it (map.py confirm-words)')
            continue
        found = find_phrase(words, phrase)
        if found is None:
            missing.append(f'{select}: phrase not found in {alias}')
            continue
        line, length = draft_line(source_map, alias, words, *found)
        lines.append(line)
        total += length
    if not lines:
        for item in missing:
            print('not found: ' + item)
        return 1
    size, fps = '1920x1080', '30'
    if first_alias and source_map.size(first_alias):
        size = 'x'.join(str(value) for value in source_map.size(first_alias))
        rate = source_map.fps(first_alias)
        if rate:
            fps = str(rate.numerator) if rate.denominator == 1 else f'{rate.numerator}/{rate.denominator}'
    title = project.read_status(root).get('title') or root.name
    direction = [f'{key}: {kept[key]}' for key in DIRECTION_KEYS if key in kept]
    reminder = ([] if len(direction) == len(DIRECTION_KEYS) else
                ['Write audience, takeaway and story in the front matter before arranging these selects into beats '
                 '(references/finding-the-story.md).', ''])
    text = '\n'.join(['---', f'title: {title}', *direction, f'size: {size}', f'fps: {fps}',
                      f'target: {math.ceil(total)}',
                      'captions: ' + (', '.join(sorted(captions)) if captions else 'none'),
                      '---', '', f'Drafted by cut.py draft from {len(args.select)} selects; '
                      'delete words to cut them, then run cut.py check.', '', *reminder, '## Selects', *lines, ''])
    if film.exists():
        shutil.copy2(film, root / 'film.md.bak')
    project.write_atomic(film, text)
    print(f'wrote {film} with {len(lines)} line{"s" if len(lines) != 1 else ""} ({total:.1f} s)')
    for item in missing:
        print('not found: ' + item)
    return 1 if missing else 0


def run_tighten(args):
    """Write a reviewable tightened paper edit using the existing compiler."""
    return load_sibling('tighten').tighten_project(args, sys.modules[__name__])


def checked_version_files(folder, manifest):
    """Verify the original version's recorded files before using or copying them."""
    files = manifest.get('files')
    if not isinstance(files, dict) or not files:
        raise ValueError('the version has no file hashes; render a final version again')
    base = folder.resolve()
    for relative, expected in files.items():
        path = (folder / relative).resolve()
        if not path.is_relative_to(base) or not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f'version file changed or is missing: {relative}')
    for stem in (folder / 'stems').glob('*.wav'):
        relative = stem.relative_to(folder).as_posix()
        if relative not in files:
            raise ValueError(f'unrecorded stem in version: {relative}')
    for required in ('preview.mp4', 'edit.json', 'edit-cues.json', 'film.md', 'stems/dialogue.wav'):
        if required not in files:
            raise ValueError(f'version is missing recorded {required}; render it again with --final')
    return dict(files)


def attached_stem_role(name):
    """Return the bus role of an attached stem or the original track name."""
    match = re.fullmatch(r'attached-(music|effects|bed)(?:-\d+)?', name)
    return match.group(1) if match else name


def same_attached_picture(cue_list, before, after):
    """Compare packets, display geometry and the shared frame schedule."""
    if before.get('sha256') != after.get('sha256'):
        return False, 'the picture packets changed'
    state, reason = cue_list.geometry_compare(before.get('geometry'), after.get('geometry'))
    if state == 'changed':
        return False, reason
    if before.get('untimed') or after.get('untimed') or not before.get('schedule') or not after.get('schedule'):
        return False, 'the picture timing cannot be verified'
    difference = cue_list.compare_schedules(before['schedule'], after['schedule'])
    if difference:
        return False, difference
    return True, reason if state == 'unverified' else ''


def version_picture_matches(cue_list, folder, identity, files, picture):
    """Verify the source picture against its version's packet and timing record."""
    if not identity.get('picture_sha256') or identity['picture_sha256'] != picture.get('sha256'):
        return False, 'the picture packet hash differs from the version'
    timing = identity.get('picture_timing') or {}
    schedule_name = timing.get('pts_file')
    if not isinstance(schedule_name, str) or schedule_name not in files or not timing.get('pts_sha256'):
        return False, 'the version has no recorded frame schedule'
    if picture.get('untimed') or not picture.get('schedule'):
        return False, 'the picture timing cannot be verified'
    expected = cue_list.read_schedule(folder / schedule_name, timing['pts_sha256'])
    if expected is None:
        return False, 'the version frame schedule is missing'
    difference = cue_list.compare_schedules(expected, picture['schedule'], timing.get('fps_exact'))
    return (False, difference) if difference else (True, '')


def prepare_attached_version(staging, mix_cue_path):
    """Carry the mixed list forward and leave checks for the new picture to run."""
    shutil.copy2(mix_cue_path, staging / 'edit-cues.json')
    shutil.copy2(mix_cue_path, staging / 'mix-cues.json')
    for name in ('checks.json', 'checks-final.json'):
        (staging / name).unlink(missing_ok=True)
    if (staging / 'qa').exists():
        shutil.rmtree(staging / 'qa')


def stem_has_sound(ffmpeg, path, start=0, end=None):
    """Whether a stem contains nonzero samples over the requested span."""
    command = [ffmpeg, '-hide_banner', '-nostdin', '-i', str(path), '-ss', str(start)]
    if end is not None:
        command += ['-t', str(end - start)]
    command += ['-vn', '-af', 'astats=metadata=0:reset=0', '-f', 'null', '-']
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired:
        raise ValueError('retained stem inspection timed out') from None
    if result.returncode:
        raise ValueError('cannot inspect retained stem: ' + result.stderr.decode(errors='replace')[-300:])
    output = result.stderr.decode(errors='replace')
    if re.search(r'Number of NaNs:\s*[1-9]', output) or re.search(r'Number of Infs:\s*[1-9]', output):
        raise ValueError('a retained stem contains non-finite samples')
    peaks = re.findall(r'Peak level dB:\s*(-inf|[-+0-9.eE]+)', output)
    return any(value != '-inf' for value in peaks)


def same_cue_timing(original, spotted):
    """Compare authored clock and event timing while allowing spotting decisions."""
    def fps(data):
        value = data.get('fps_exact', data.get('fps'))
        return float(Fraction(str(value))) if value is not None else None
    def keyed(data, key, convert):
        items = data.get(key, [])
        if not isinstance(items, list) or any(not isinstance(item, dict) or 'id' not in item for item in items):
            raise ValueError('cue timing needs uniquely named events and sections')
        result = {str(item['id']): convert(item) for item in items}
        if len(result) != len(items):
            raise ValueError('cue timing needs uniquely named events and sections')
        return result
    def timing(data):
        rate = fps(data)
        sections = keyed(data, 'sections', lambda s: (s.get('a'), s.get('b'), s.get('clock')))
        def event(item):
            t = item.get('t')
            if t is None and rate and item.get('frame') is not None:
                t = float(item['frame']) / rate
            if t is None or not math.isfinite(float(t)):
                raise ValueError('event timing is missing or invalid')
            section = item.get('section')
            inherited_clock = (sections.get(str(section)) or (None, None, None))[2]
            return (round(float(t), 9), item.get('t_end'), item.get('scale', 'contact'), section,
                    item.get('clock', inherited_clock), item.get('lead_ms', 0), item.get('sync', 'attack'))
        return rate, sections, keyed(data, 'events', event)
    old_rate, old_sections, old_events = timing(original)
    new_rate, new_sections, new_events = timing(spotted)
    same_rate = old_rate == new_rate or (old_rate is not None and new_rate is not None
                                         and abs(old_rate - new_rate) < 1e-9)
    return (same_rate and original.get('clock') == spotted.get('clock')
            and old_sections == new_sections and old_events == new_events)


def attach_inputs(root, args):
    """Validate the version, its cue list, mixer report and each processed bus."""
    if not project.VERSION_NAME.fullmatch(args.version):
        raise ValueError('version must be a version name such as v001')
    folder = root / 'cuts' / args.version
    manifest_path = folder / 'manifest.json'
    if not manifest_path.is_file():
        raise ValueError('no such version: ' + args.version)
    manifest = project.load_json(manifest_path, {})
    stems_dir = folder / 'stems'
    if not manifest.get('final') or not stems_dir.is_dir():
        raise ValueError(f'no final stems; run cut.py render "{root}" --final')
    files = checked_version_files(folder, manifest)
    cue_path = folder / 'edit-cues.json'
    if not cue_path.is_file():
        raise ValueError('the version has no edit-cues.json; render it again with --final')
    cues_hash = sha256_file(cue_path)
    identity = manifest.get('identity') or {}
    if identity.get('cues_sha256') != cues_hash:
        raise ValueError('the version cue list is not bound to its manifest')
    cue_list = load_sibling('cue_list')
    listed = cue_list.load(cue_path, owner=folder)
    if listed.state != 'fresh' or listed.sha256 != cues_hash:
        raise ValueError('the version cue list is not bound to this version: ' + listed.message)
    bus_dir = Path(args.buses)
    if not bus_dir.is_dir():
        raise ValueError('--buses must name the mixer output folder, not voice.wav or mix.wav')
    report_path = Path(args.report)
    report = project.load_json(report_path, None)
    if not isinstance(report, dict):
        raise ValueError('cannot read the mixer report')
    if report.get('exit_code') != 0:
        raise ValueError('the mixer report did not pass')
    if (report.get('mastering') or {}).get('preset') != 'none' or report.get('gain_applied_db') != 0:
        raise ValueError('attach needs mixer buses made with --master none and no gain normalization')
    mix_inputs = report.get('inputs') or {}
    mix_cue_hash = mix_inputs.get('cues')
    mix_cue_path = cue_path
    if mix_cue_hash != cues_hash:
        if not isinstance(mix_inputs.get('cues_path'), str):
            raise ValueError('the mixer report does not identify its cue list')
        mix_cue_path = Path(mix_inputs['cues_path'])
        if not mix_cue_path.is_file() or sha256_file(mix_cue_path) != mix_cue_hash:
            raise ValueError('the mixer cue list differs from its report')
        listed = cue_list.load(mix_cue_path, owner=folder)
        if listed.state != 'fresh' or listed.sha256 != mix_cue_hash:
            raise ValueError('the mixer cue list is not bound to this version: ' + listed.message)
        original = project.load_json(cue_path, None)
        spotted = project.load_json(mix_cue_path, None)
        if not isinstance(original, dict) or not isinstance(spotted, dict):
            raise ValueError('cannot read the version and mixer cue lists')
        if not same_cue_timing(original, spotted):
            raise ValueError('the mixer cue list changes version timing; re-export the version cues')
    reference = stems_dir / 'dialogue.wav'
    if not reference.is_file() or files.get('stems/dialogue.wav') != sha256_file(reference):
        raise ValueError('the version needs its recorded dialogue stem')
    reference_hash = sha256_file(reference)
    voices = (report.get('inputs') or {}).get('voice') or []
    if len(voices) != 1 or voices[0].get('sha256') != reference_hash or voices[0].get('at_s') != 0 or voices[0].get('gain_db') != 0:
        raise ValueError('the mixer voice reference is not the version dialogue stem at its original gain and time')
    outputs = report.get('outputs') or {}
    buses = {}
    for role in ('music', 'effects', 'bed'):
        path = bus_dir / (role + '.wav')
        if path.is_file():
            if outputs.get(path.name) != sha256_file(path):
                raise ValueError(f'{path.name} does not match the mixer report')
            if role == 'bed':
                ffmpeg = find_tool('ffmpeg')
                if not ffmpeg:
                    raise ValueError('FFmpeg is required to check the ambience bus')
                if not stem_has_sound(ffmpeg, path):
                    continue
            buses[role] = path
        elif path.name in outputs:
            raise ValueError(f'the mixer report names a missing bus: {path.name}')
    if not buses:
        raise ValueError('no processed buses found')
    replace = {role for group in (args.replace or []) for role in group}
    stem_paths = {path.stem: path for path in sorted(stems_dir.glob('*.wav'))}
    unknown = replace - {attached_stem_role(name) for name in stem_paths}
    if unknown:
        raise ValueError('no version stems for --replace: ' + ', '.join(sorted(unknown)))
    if 'dialogue' in replace:
        raise ValueError('dialogue cannot be replaced by a mixer bus')
    retained = {name: path for name, path in stem_paths.items() if attached_stem_role(name) not in replace}
    silence_looks = []
    all_silences = [event for event in listed.events if isinstance(event, dict)
                    and event.get('scale') == 'silence' and event.get('scope', 'new') == 'all']
    if all_silences:
        ffmpeg = find_tool('ffmpeg')
        if not ffmpeg:
            raise ValueError('FFmpeg is required to check retained stems')
        for event in all_silences:
            for name, path in retained.items():
                if stem_has_sound(ffmpeg, path, float(event['t']), float(event['t_end'])):
                    role = attached_stem_role(name)
                    message = (f"all-scoped silence {float(event['t']):g}..{float(event['t_end']):g}s: "
                               f'retained stem {name} (role {role}) has sound; use --replace ROLE for a '
                               'replaceable stem, or change the silence scope')
                    message += ('; dialogue cannot be replaced' if role == 'dialogue'
                                else f' (for this stem: --replace {role})')
                    silence_looks.append(message)
        if silence_looks and getattr(args, 'strict', False):
            raise ValueError('strict: ' + '; '.join(silence_looks))
    music_input = (report.get('inputs') or {}).get('music')
    if 'music' in buses and any(attached_stem_role(name) == 'music' and music_input == sha256_file(path)
                                for name, path in retained.items()):
        raise ValueError('the music bus processes the retained music stem; use --replace music to avoid doubling it')
    return (folder, manifest, files, report, report_path, buses, retained, sorted(replace), reference_hash,
            cue_list, mix_cue_path, silence_looks)


def run_attach_mix(args):
    """Create an immutable version from a final cut and processed mixer buses."""
    root = load_project(args.project)
    with project.file_lock(root / 'cuts' / 'render', timeout=RENDER_WAIT):
        (folder, manifest, files, report, report_path, buses, retained, replaced, reference_hash,
         cue_list, mix_cue_path, silence_looks) = attach_inputs(root, args)
        ffmpeg, ffprobe = find_tool('ffmpeg'), find_tool('ffprobe')
        if not ffmpeg or not ffprobe:
            raise ValueError('FFmpeg and ffprobe are required')
        source_picture = cue_list.picture_identity(folder / 'preview.mp4')
        valid, reason = version_picture_matches(cue_list, folder, manifest.get('identity') or {}, files, source_picture)
        if not valid:
            raise ValueError('the source picture is not bound to this version: ' + reason)
        edit = project.load_json(folder / 'edit.json', {})
        fades = edit.get('film_fades') or {}
        if not isinstance(fades, dict):
            raise ValueError('version fades are invalid')
        duration = float(manifest['duration_s'])
        frames = int(manifest['frames'])
        if duration <= 0 or frames <= 0:
            raise ValueError('version duration and frame count must be positive')
        name = project.next_version(root)
        final = root / 'cuts' / name
        if final.exists():
            raise ValueError('next version already exists')
        captured = {str(path): sha256_file(path) for path in [report_path, mix_cue_path, *buses.values()]}
        manifest_hash = sha256_file(folder / 'manifest.json')
        with tempfile.TemporaryDirectory(prefix=f'.{name}.attach-', dir=root / 'cuts') as temp:
            work = Path(temp)
            staging = work / 'version'
            shutil.copytree(folder, staging)
            prepare_attached_version(staging, mix_cue_path)
            stage_stems = staging / 'stems'
            for path in stage_stems.glob('*.wav'):
                if attached_stem_role(path.stem) in replaced:
                    path.unlink()
            bus_copies = {}
            for role, path in buses.items():
                dest = stage_stems / ('attached-' + role + '.wav')
                number = 2
                while dest.exists():
                    dest = stage_stems / f'attached-{role}-{number}.wav'
                    number += 1
                shutil.copy2(path, dest)
                bus_copies[role] = dest
            shutil.copy2(report_path, staging / 'attached-mix-report.json')
            selected = [stage_stems / path.name for path in retained.values()] + list(bus_copies.values())
            output = staging / 'preview.mp4'
            output.unlink()
            master = manifest.get('audio_master')
            notes = list(silence_looks)
            if master:
                mix = work / 'sum.wav'
                normalized = work / 'master.wav'
                mix_for_master(ffmpeg, selected, duration, fades, mix)
                first, second = loudnorm_passes(ffmpeg, mix, normalized, float(master['target_lufs']))
                mux_master(ffmpeg, folder / 'preview.mp4', normalized, duration, frames, output)
                master_report = measure_master(ffmpeg, ffprobe, output, master['platform'], float(master['target_lufs']),
                                               master.get('target_source', 'version'), first, second)
                project.save_json(staging / 'audio-master.json', master_report)
                notes.extend(master_warnings(master_report))
            else:
                mux_preview(ffmpeg, folder / 'preview.mp4', selected, duration, fades, output, frames)
            verify_mux_output(ffprobe, output, frames, duration, notes)
            same, picture_note = same_attached_picture(cue_list, source_picture, cue_list.picture_identity(output))
            if not same:
                raise ValueError('the mux changed the picture identity: ' + picture_note)
            if picture_note:
                notes.append('picture identity unverified: ' + picture_note)
            checked_version_files(folder, manifest)
            if sha256_file(folder / 'manifest.json') != manifest_hash or any(sha256_file(path) != value for path, value in captured.items()):
                raise ValueError('an input changed while attaching the mix; no version was published')
            provenance = {'report_sha256': captured[str(report_path)],
                          'cues_sha256': captured[str(mix_cue_path)],
                          'buses': {role: captured[str(path)] for role, path in buses.items()},
                          'stems': {name: {'from': args.version, 'sha256': sha256_file(path),
                                           'role': attached_stem_role(name)} for name, path in retained.items()},
                          'replaced': replaced, 'voice_reference': reference_hash,
                          'fades': args.version, 'master': args.version}
            manifest['version'] = name
            manifest['parent'] = args.version
            manifest['created'] = project.now()
            manifest['label'] = args.label or ''
            manifest['mix'] = provenance
            manifest['identity']['mix'] = provenance
            manifest['identity']['cues_sha256'] = captured[str(mix_cue_path)]
            manifest['notes'] = list(manifest.get('notes') or []) + notes
            manifest['files'] = {path.relative_to(staging).as_posix(): sha256_file(path)
                                 for path in sorted(staging.rglob('*')) if path.is_file() and path.name != 'manifest.json'}
            project.save_json(staging / 'manifest.json', manifest)
            publish(staging, final)
        project.set_current(root, name)
        project.set_stage(root, 'check', line=f'{name} mix attached; not checked yet')
        print(f'{name} attached; original {args.version} is unchanged. Unheard.')
        for look in silence_looks:
            print('LOOK: ' + look)
        return 1 if silence_looks else 0


# ----------------------------------------------------------------------------------------------- main

def argument_parser():
    """The command line."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check', help='validate film.md against the map without rendering')
    check.add_argument('project')
    check.add_argument('--json', action='store_true', help='print the full report as JSON')
    check.add_argument('--no-audio', action='store_true', help='place cuts from transcript times only')
    render = sub.add_parser('render', help='render the next version')
    render.add_argument('project')
    render.add_argument('--label', default='', help='a short label for this version')
    render.add_argument('--resolves', default='',
                        help='note IDs this version answers, comma separated; only recorded in manifest.json. '
                             'Close each with screen.py resolve PROJECT NOTE --in vNNN --reply TEXT '
                             '(the render prints the command for each note still open)')
    render.add_argument('--final', action='store_true', help='render at full size and keep the sound stems')
    render.add_argument('--every-frame', action='store_true',
                        help='draw every frame in Python even when the film is a plain cut, to compare the paths')
    render.add_argument('--master', choices=('youtube', 'linkedin', 'instagram', 'tiktok', 'x', 'web'),
                        help='two-pass dialogue master for this destination (requires --final)')
    render.add_argument('--master-target', type=float, help='override the working dialogue target in LUFS')
    render.add_argument('--json', action='store_true')
    diff = sub.add_parser('diff', help='what changed between two versions, or since a version in the working film.md')
    diff.add_argument('project')
    diff.add_argument('a')
    diff.add_argument('b', nargs='?', help='the newer version; without it, the working film.md')
    diff.add_argument('--json', action='store_true')
    draft = sub.add_parser('draft', help='write a first film.md from selects')
    draft.add_argument('project')
    draft.add_argument('--select', action='append', required=True, help='ALIAS:"phrase" or ALIAS:START-END')
    draft.add_argument('--captions', default='srt, vtt', help='caption outputs, e.g. "burn, srt, vtt"')
    draft.add_argument('--force', action='store_true', help='replace an existing film.md (kept as film.md.bak)')
    tighten = sub.add_parser('tighten', help='write a paper edit, removal report and listening reel')
    tighten.add_argument('project')
    tighten.add_argument('alias')
    tighten.add_argument('--pause', type=float, default=0.35, help='target pause in seconds')
    tighten.add_argument('--fillers', help='named or a comma-separated list; off by default')
    tighten.add_argument('--punch-in', type=float, help='alternate this zoom on successive lines')
    tighten.add_argument('--music-bed', action='store_true', help='keep pauses and fillers when a bed is present')
    tighten.add_argument('--reel-limit', type=int, help='show at most N reel events, cuts first; off by default')
    tighten.add_argument('--out', help='paper edit path (default PROJECT/film.md)')
    tighten.add_argument('--silence-only', action='store_true', help='use measured quiet without a transcript')
    tighten.add_argument('--force', action='store_true', help='replace existing outputs; keep the old edit as .bak')
    attach = sub.add_parser('attach-mix', help='attach processed buses to a final cut')
    attach.add_argument('project')
    attach.add_argument('--version', required=True)
    attach.add_argument('--buses', required=True)
    attach.add_argument('--report', required=True)
    attach.add_argument('--replace', action='append', nargs='+', default=[])
    attach.add_argument('--strict', action='store_true',
                        help='refuse attachment when retained stems contain sound in an all-scoped silence')
    attach.add_argument('--label', default='')
    return parser


def main():
    """Run one command and return the shared exit code."""
    args = argument_parser().parse_args()
    project.safe_output()
    try:
        handler = {'check': run_check, 'render': run_render, 'diff': run_diff, 'draft': run_draft,
                   'tighten': run_tighten, 'attach-mix': run_attach_mix}[args.command]
        return handler(args)
    except ImportError as error:
        name = 'PIL' if error.name and (error.name == 'PIL' or error.name.startswith('PIL.')) else 'numpy'
        print(project.dependency_message(name), file=sys.stderr)
        return 2
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as error:
        print(f'cut: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
