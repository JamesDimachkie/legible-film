#!/usr/bin/env python3
"""Assemble an edit.json into a BT.709 H.264 picture, stems, cues and declarations.

  python assemble.py edit.json --out picture.mp4 --json report.json
  python assemble.py edit.json --out picture.mp4 --spool-gib 4

Picture edits keep their source-clock boundaries and sample the frame showing at each output
time. The output frame grid tiles picture intervals; audio uses sample clocks and mixed stems remain floating point.
Retimed audio
reports its unpadded duration and warns that transient timing may move. Source and motion frames
are streamed; --spool-gib is retained for compatibility and does not limit encoded or audio files.
Planning decodes each range once to obtain its timestamps, then decodes it again while rendering.
On the every-frame path each picture decoder uses one input thread to reduce concurrent decoder memory; decoding may
take longer.
A plain cut (plain_cut_reason decides) has FFmpeg draw its picture, in YUV where the source allows: Python only says
which frame comes next, by the same rule and from the same timestamps; --every-frame turns that off. Output
measurements do not prove a film
has been watched, heard, approved, or cleared for use. Needs numpy, Pillow, FFmpeg
and ffprobe. declared.json contains an ignore string of designed holds and dips
for blank_scan.py and motion_scan.py --ignore, never flash_scan.py.

Spatial layers (references/spatial.md): an image overlay may be pinned to a track ("pin": {"layer", "fit": corners
or follow}) or drawn behind a matte's foreground ("behind": {"layer"}), and a "blur" overlay blurs a tracked or matted
region ("region": {"layer"}). Layer frames follow the renderer's own frame choice and framing, and are drawn only
over a single shot of the source they were made from; where they are not drawn, the notes say why, and the report's
"layers" counts frames drawn and not drawn. A blur that cannot cover a frame where its source is on screen stops the
render before encoding. A drawn blur is not anonymisation: a person checks every frame. A picture item past where
its source's frames really end is shortened to that end and reported, whatever the file's header claims, and is never
filled with a frozen frame; an item carrying the film.md line it came from ("line", as cut.py render adds) is refused
naming that line instead, since shortening one line slides every later line against its sound. Exit 0 on completion,
1 when review notes remain, 2 on error.
"""
import argparse
import bisect
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter
except ImportError as missing:
    import runpy
    project_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'project.py')
    sys.exit(runpy.run_path(project_file)['missing_package'](missing))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from motion_scan import Frames
from render_common import Encoder, decoded_count, display_geometry, exact_rate, find_tool, h264_args, overlay_probe
from render_common import COLOUR, TAG_BT709, decoded_short, picture_goes_on, presentation_frame_before
from reframe import (analyse, bounds, consistent_zooms, face_review, face_targets, method_spans, position, probe,
                     propose, validate_path)

spec = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)

CAPTIONS = Path(__file__).with_name('captions.py')
_cue_spec = importlib.util.spec_from_file_location('lf_cue_list', Path(__file__).with_name('cue_list.py'))
cue_list = importlib.util.module_from_spec(_cue_spec)
_cue_spec.loader.exec_module(cue_list)
# Audio fade shapes an edit.json audio item may ask for (FFmpeg afade curves): tri is linear, qsin equal power.
FADE_CURVES = ('tri', 'qsin')
HDR_TRANSFERS = ('smpte2084', 'arib-std-b67')
# cut.py check lets a range run this far past its source; the render shortens it without refusing the line.
RANGE_SLACK_S = 0.05
# On FFmpeg 9.0.2 and a 1080p30 film on a 16-core laptop, x264 at the delivery settings ran at 12 frames a second on
# one thread, 40 on eight, 54 on twelve and 62 on sixteen, for about 29 MB more per thread; the files were the same
# size within 0.1%. A fixed count keeps a render's bytes the same from run to run on one machine.
ENCODER_THREADS = min(12, os.cpu_count() or 1)
# One decoder runs at a time on the plain-cut path and for a timestamp pass, so it can use more than one thread.
DECODER_THREADS = min(6, os.cpu_count() or 1)

def run(command, seconds=1800):
    """Run a process with a time limit and raise a useful error on failure or timeout."""
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=seconds)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f'command did not finish within {seconds} s and was stopped: {Path(command[0]).name}')
    if result.returncode:
        raise RuntimeError('command failed: ' + result.stderr[-1200:])
    return result


def write_json(path, data):
    """Write UTF-8 JSON with explicit indentation and LF line endings on every platform."""
    with open(path, 'w', encoding='utf-8', newline='\n') as file:
        json.dump(data, file, indent=2)


def nearest(times, value):
    """Choose the nearest decoded timestamp, breaking ties towards the earlier frame."""
    index = bisect.bisect_left(times, value)
    return min((max(0, index - 1), min(index, len(times) - 1)), key=lambda i: abs(times[i] - value))


def source_path(root, sources, name):
    """Resolve a source key or a path relative to edit.json."""
    entry = sources.get(name, name)
    filename = entry['file'] if isinstance(entry, dict) else entry
    return str((root / filename).resolve())


def audio_source_path(root, sources, name):
    """Resolve original sound separately when a picture source uses a silent proxy."""
    entry = sources.get(name, name)
    filename = entry.get('audio_file', entry['file']) if isinstance(entry, dict) else entry
    return str((root / filename).resolve())


def edit_inputs(edit, root, edit_path):
    """Every file an edit reads: the edit itself, its picture, audio and image sources, caption files and saved
    crop paths."""
    inputs = [edit_path]
    inputs.extend(source_path(root, edit['sources'], item['src']) for item in edit['picture'])
    inputs.extend(audio_source_path(root, edit['sources'], item['src']) for item in edit.get('audio', []))
    for overlay in edit.get('overlays', []):
        if overlay.get('kind') == 'captions' and overlay.get('file'):
            inputs.append(root / overlay['file'])
        elif overlay.get('src'):
            inputs.append(source_path(root, edit['sources'], overlay['src']))
    for item in edit['picture']:
        crop = item.get('crop')
        if isinstance(crop, dict) and isinstance(crop.get('path'), str) and crop['path'] != 'auto':
            inputs.append(root / crop['path'])
    for overlay in edit.get('overlays', []):
        for _, reference in layer_roles(overlay):
            sidecar = root / reference['layer']
            inputs.append(sidecar)
            try:
                data = json.loads(sidecar.read_text(encoding='utf-8')).get('data')
            except (OSError, ValueError, AttributeError):
                data = None
            if isinstance(data, str):
                inputs.append(sidecar.parent / data)
    return inputs


def has_filter(ffmpeg, name):
    """Check the filters available in this FFmpeg build."""
    try:
        result = subprocess.run([ffmpeg, '-hide_banner', '-filters'], stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError('cannot inspect FFmpeg filters: no answer within 60 s')
    if result.returncode:
        raise RuntimeError('cannot inspect FFmpeg filters')
    return name in set(re.findall(r'^\s*[TSC.]{2,3}\s+(\S+)', result.stdout, re.MULTILINE))


def colour_filter(stream, width, height):
    """Build a source-aware SDR conversion and describe every assumption."""
    matrix = stream.get('color_space', 'unknown')
    transfer = stream.get('color_transfer', 'unknown')
    primaries = stream.get('color_primaries', 'unknown')
    field = stream.get('field_order', 'unknown')
    assumed = []
    missing_transfer = transfer in ('unknown', 'unspecified', 'reserved', None)
    missing_primaries = primaries in ('unknown', 'unspecified', 'reserved', None)
    hdr = transfer in HDR_TRANSFERS
    if stream.get('color_range') in (None, 'unknown', 'unspecified', 'reserved'):
        assumed.append('range tag missing; FFmpeg decoder and filter defaults used')
    fallback = 'smpte170m' if width <= 1024 and height <= 576 else 'bt709'
    if matrix in ('unknown', 'unspecified', 'reserved', None):
        matrix = fallback
        assumed.append('matrix assumed ' + matrix + ' from source size')
    if missing_transfer:
        assumed.append('transfer tag missing; SDR transfer not converted')
    if missing_primaries and hdr:
        primaries = fallback
        assumed.append('primaries assumed ' + primaries + ' from source size')
    elif missing_primaries:
        assumed.append('primaries tag missing; SDR primaries not converted')
    filters = []
    if field not in ('unknown', 'progressive', None):
        filters.append('bwdif=mode=send_frame:parity=auto:deint=all')
    # Label the input matrix; zscale also needs transfer and primaries for HDR.
    if matrix != 'gbr':
        if not hdr and (missing_transfer or missing_primaries):
            filters.append(f'setparams=colorspace={matrix}')
        else:
            filters.append(f'setparams=colorspace={matrix}:color_trc={transfer}:color_primaries={primaries}')
    if hdr:
        filters.extend(['zscale=t=linear:npl=100', 'format=gbrpf32le', 'zscale=p=bt709',
                        'tonemap=tonemap=hable:desat=0', 'zscale=t=bt709:m=bt709:r=tv', 'format=yuv420p'])
        conversion = 'HDR to BT.709 SDR: zscale linear, Hable tone map and BT.709 output'
    elif matrix == 'gbr':
        conversion = 'RGB decoded directly; output encoded as BT.709'
    elif missing_transfer or missing_primaries:
        conversion = f'SDR decoded with {matrix} matrix; untagged transfer or primaries not converted'
    elif transfer == 'iec61966-2-1':
        # sRGB is how graphics applications (Cavalry, browsers, PNG renders) tag their output. Video treats it as
        # display values to keep, as the kit does for its own renders; converting the curve through linear light
        # crushed a Cavalry title's background from RGB 16 to 5. Only the matrix and primaries convert.
        filters.extend(['format=yuv444p', 'colorspace=all=bt709:range=tv:itrc=bt709',
                        'scale=out_color_matrix=bt709:out_range=tv'])
        conversion = f'{matrix}/sRGB/{primaries} converted to BT.709, sRGB values kept as display values'
    else:
        filters.extend(['format=yuv444p', 'colorspace=all=bt709:range=tv',
                        'scale=out_color_matrix=bt709:out_range=tv'])
        conversion = f'{matrix}/{transfer}/{primaries} converted to BT.709'
    filters.append('format=rgb24')
    return ','.join(filters), assumed, conversion


def probe_source(ffprobe, filename):
    """Read stream metadata and count decoded frames before reserving disk."""
    command = [ffprobe, '-v', 'error', '-select_streams', 'v:0',
               '-show_streams', '-of', 'json', filename]
    stream = json.loads(run(command).stdout)['streams'][0]
    count = 0
    width, height = probe(ffprobe, filename)
    return stream, count, width, height


def source_origin(ffprobe, filename):
    """The format presentation origin used to translate source-relative edit times."""
    command = [ffprobe, '-v', 'error', '-show_entries', 'format=start_time', '-of', 'json', filename]
    data = json.loads(run(command).stdout)
    value = (data.get('format') or {}).get('start_time')
    if value in (None, 'N/A'):
        return 0.0
    origin = float(value)
    if not math.isfinite(origin):
        raise ValueError('non-finite source presentation origin: ' + filename)
    return origin


class PlaybackSeekError(ValueError):
    """A seeked playback decode failed and can be retried from the start."""

    def __init__(self, source, message):
        """Keep the failed source so the complete picture can be restarted safely."""
        super().__init__(message)
        self.source = source


class FrameSource:
    """The independent decoder configuration for one clip occurrence."""

    def __init__(self, ffmpeg, filename, vf, size, options, times, properties=None, clock=''):
        """Retain the exact decoder settings and the timestamps found during planning; `clock` is the part of
        `vf` that trims and times the range, before any picture work."""
        self.ffmpeg = ffmpeg
        self.filename = filename
        self.vf = vf
        self.size = size
        self.options = options
        self.times = times
        self.properties = properties
        self.clock = clock

    def open(self):
        """Start a forward-only reader when its clip becomes active."""
        return FrameWindow(self)

    def retry_without_seek(self):
        """Validate the linear clock before restarting the whole picture with this source."""
        options = list(self.options)
        position = options.index('-ss')
        seek = float(options[position + 1])
        del options[position:position + 2]
        duration = options.index('-t') + 1
        options[duration] = f'{float(options[duration]) + seek:.9f}'
        reader = Frames(self.ffmpeg, self.filename, self.vf, self.size, options, timestamps_only=True)
        try:
            times = reader.scan()
        except RuntimeError as error:
            raise ValueError('video decoder failed while reading picture: ' + str(error)) from error
        if times != self.times:
            raise ValueError('video decoder failed while reading picture: linear retry timestamps changed')
        self.options = options
        if self.properties is not None:
            self.properties['decode_seek_s'] = 0.0


class FrameWindow:
    """Keep at most the two most recent decoded frames for repeated and blended samples."""

    def __init__(self, source):
        """Open this clip's decoder and start with an empty forward window."""
        self.source = source
        self.reader = Frames(source.ffmpeg, source.filename, source.vf, source.size, source.options)
        self.iterator = iter(self.reader)
        self.index = -1
        self.frames = {}
        self.finished = False

    def frame(self, index):
        """Return a frame by monotonically advancing the decoder, retaining one-frame lookahead."""
        if index < self.index - 1:
            raise RuntimeError('picture frame requested behind the streaming window')
        while self.index < index:
            try:
                raw = next(self.iterator)
            except StopIteration:
                self._validate()
                raise RuntimeError('short decoded frame')
            self.index += 1
            self.frames[self.index] = raw
            self.frames.pop(self.index - 2, None)
        if index not in self.frames:
            raise RuntimeError('short decoded frame')
        return self.frames[index]

    def _validate(self):
        """Verify the playback decode against the planning pass before accepting the render."""
        if self.finished:
            return
        self.finished = True
        try:
            times = self.reader.times(self.index + 1)
        except RuntimeError as error:
            message = 'video decoder failed while reading picture: ' + str(error)
            if '-ss' in self.source.options:
                raise PlaybackSeekError(self.source, message) from error
            raise ValueError(message) from error
        if times != self.source.times:
            raise ValueError('video decoder failed while reading picture: playback timestamps changed')

    def close(self):
        """Finish the range, including its unused handle, and verify its count and timestamps."""
        if self.finished:
            return
        for _ in self.iterator:
            self.index += 1
        self._validate()
        self.frames.clear()

    def abort(self):
        """Stop this reader on a failed render without waiting for an unconsumed pipe."""
        if self.finished:
            return
        if self.reader.proc.poll() is None:
            self.reader.proc.kill()
        self.reader.proc.stdout.close()
        self.reader.proc.wait()
        self.reader.reader.join()
        self.finished = True
        self.frames.clear()


def picture_line(item):
    """Where an error about a picture item points a person: its film.md line, when cut.py rendered it."""
    return f"film.md line {item['line']}: " if item.get('line') is not None else ''


def shorten_picture(item, requested, available, notes):
    """An out-point past the picture's end: shortened and reported, or for a line of a paper edit, refused."""
    if item.get('line') is not None and requested - available > RANGE_SLACK_S:
        raise ValueError(f"{picture_line(item)}{item['src']}'s picture ends at {available:.3f} s and this line needs "
                         f'it to {requested:.3f} s, so nothing was rendered. End the line by then, or hold its last '
                         f"frame with a pause hold line; map.py run PROJECT --alias {item['src']} --rebuild lets "
                         'cut.py check report this before a render.')
    item['out'] = available
    notes.append(f"Picture {item['src']} out clamped from {requested:.6f} to {available:.6f} s; "
                 'review the shortened edit.')
    return available


def hdr_transfer(ffprobe, root, sources, name, stream):
    """The HDR transfer a picture source was recorded with, or None. A preview proxy stands in for the source under
    audio_file, and the original's own tags decide."""
    entry = sources.get(name)
    if isinstance(entry, dict) and entry.get('audio_file'):
        original = audio_source_path(root, sources, name)
        stream = json.loads(run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                 'stream=color_transfer', '-of', 'json', original]).stdout)['streams'][0]
    transfer = stream.get('color_transfer')
    return transfer if transfer in HDR_TRANSFERS else None


def conform(ffmpeg, ffprobe, edit, root, temp, spool_limit, notes):
    """Plan each range with a null-output decode, retaining timestamps rather than picture bytes. Each source is asked
    about once, and ranges are planned side by side, since each pass only decodes and reads timestamps."""
    probed = {}
    transcribe = None
    for item in edit['picture']:
        filename = source_path(root, edit['sources'], item['src'])
        if filename in probed:
            continue
        stream, _, width, height = probe_source(ffprobe, filename)
        if stream.get('color_transfer') in HDR_TRANSFERS and not has_filter(ffmpeg, 'zscale'):
            raise RuntimeError('this FFmpeg build lacks zscale; HDR conversion needs a build with libzimg')
        vf, assumptions, conversion = colour_filter(stream, int(stream['width']), int(stream['height']))
        vf += f',scale={width}:{height}:flags=lanczos,setsar=1'
        origin = source_origin(ffprobe, filename)
        if transcribe is None:
            transcribe_spec = importlib.util.spec_from_file_location('lf_picture_duration',
                                                                     Path(__file__).with_name('transcribe.py'))
            transcribe = importlib.util.module_from_spec(transcribe_spec)
            transcribe_spec.loader.exec_module(transcribe)
        facts = json.loads(run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json',
                                filename]).stdout)
        try:
            video_bounds = math.isfinite(float(stream.get('duration'))) and float(stream['duration']) > 0
        except (TypeError, ValueError):
            video_bounds = False
        if 'matroska' in (facts.get('format') or {}).get('format_name', ''):
            tag = (stream.get('tags') or {}).get('DURATION')
            try:
                tag_end = transcribe.project.parse_time(tag) if tag else None
                video_bounds = video_bounds or (tag_end is not None and math.isfinite(tag_end) and tag_end > origin)
            except (TypeError, ValueError):
                pass
        audio_present = any(row.get('codec_type') == 'audio' for row in facts.get('streams', []))
        if not video_bounds and audio_present:
            raise ValueError('cannot establish the picture stream end independently of audio; '
                             'remux the source with a known video duration before editing')
        transfer = hdr_transfer(ffprobe, root, edit['sources'], item['src'], stream)
        probed[filename] = (stream, width, height, vf, assumptions, conversion, origin,
                            transcribe.presentation_duration({'format': facts.get('format', {}),
                                                              'streams': [stream]}), transfer)
        if transfer:
            notes.append(f"Picture {item['src']}: this source is HDR ({transfer}) and was converted to SDR with a "
                         'Hable tone map; compare its highlights with the original.')

    def plan_range(item):
        """One picture range's timestamps and decoder, with the notes it raised."""
        filename = source_path(root, edit['sources'], item['src'])
        stream, width, height, vf, assumptions, conversion, origin, source_duration, transfer = probed[filename]
        range_notes = []
        requested_start = float(item['in'])
        requested_stop = float(item['out'])
        if not math.isfinite(requested_start) or not math.isfinite(requested_stop) or requested_start < 0:
            raise ValueError('invalid picture range')
        original_stop = requested_stop
        if requested_stop > source_duration + .001:
            if requested_start >= source_duration:
                raise ValueError(picture_line(item) + 'picture in-point is at or beyond the source end: ' + filename)
            requested_stop = shorten_picture(item, requested_stop, source_duration, range_notes)
        try:
            start, seek = presentation_frame_before(ffprobe, filename, origin, requested_start, requested_stop,
                                                    return_seek=True)
        except ValueError as error:
            raise ValueError(picture_line(item) + str(error)) from error
        stop = float(item['out']) + 1.0
        if stop <= start:
            raise ValueError('invalid picture range')
        clock = f'trim=start={origin + start:.9f}:end={origin + stop:.9f},setpts=PTS-({origin:.9f})/TB,'
        numerator, denominator = stream.get('time_base', '0/1').split('/')
        tick = float(numerator) / float(denominator)
        # Timestamps need the decoder and the clock, no picture work; a deinterlacer is the one filter that could
        # change them.
        scan_filter = clock + ('null' if stream.get('field_order') in ('unknown', 'progressive', None) else vf)
        while True:
            options = ['-copyts']
            if seek:
                options.extend(['-ss', f'{seek:.9f}'])
            options.extend(['-t', f'{stop - seek + 1:.9f}', '-threads', '1'])
            reader = Frames(ffmpeg, filename, scan_filter, width * height * 3,
                            [*options[:-1], str(DECODER_THREADS)], timestamps_only=True)
            try:
                times = reader.scan()
            except RuntimeError as error:
                if seek:
                    seek = 0.0
                    continue
                raise ValueError('video decoder failed while reading picture: ' + str(error)) from error
            if times[0] > start + max(tick, 1e-5):
                if seek:
                    seek = 0.0
                    continue
                raise ValueError('decoded picture did not include the covering frame; normalize the source')
            break
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            raise ValueError('picture presentation timestamps are not strictly increasing; '
                             'normalize the source before editing')
        end = reader.end()
        intervals = np.diff(times)
        # The header is not the picture: a file cut short still claims every second it once had.
        spacing = float(np.median(intervals)) if len(intervals) else 0.0
        if (decoded_short(requested_stop, end, spacing)
                and not picture_goes_on(ffprobe, filename, origin, requested_stop)):
            requested_stop = shorten_picture(item, requested_stop, end, range_notes)
        elif spacing and requested_stop - end > 1.5 * spacing:
            # Inside the slack a header and a file can differ for ordinary reasons, so it holds; it does not hide it.
            range_notes.append(f"Picture {item['src']} holds its last frame for {requested_stop - end:.3f} s: the source's "
                               f'picture ends at {end:.3f} s, just short of this line.')
        end = max(end, requested_stop)
        variable = bool(len(intervals) > 1 and np.max(intervals) - np.min(intervals) > .0001)
        rotation = float(stream.get('tags', {}).get('rotate', 0))
        for side_data in stream.get('side_data_list', []):
            rotation = float(side_data.get('rotation', rotation))
        row = {**display_geometry(stream), 'source_matrix': stream.get('color_space'),
               'source_transfer': stream.get('color_transfer'),
               'source_primaries': stream.get('color_primaries'),
               'source_pixel_format': stream.get('pix_fmt'), 'source_range': stream.get('color_range'),
               'hdr_transfer': transfer,
               'field_order': stream.get('field_order'), 'variable_timing': variable,
               'reported_rotation_degrees': rotation, 'rotation_conversion': 'FFmpeg autorotation',
               'presentation_origin_s': origin,
               'decode_seek_s': seek,
               'conversion': conversion, 'assumptions': assumptions, 'filter': vf,
               'time_base': stream.get('time_base', '0/1')}
        source = FrameSource(ffmpeg, filename, clock + vf, width * height * 3, options, times, row, clock)
        return filename, row, (source, width, height, times, end, tick, original_stop), range_notes

    if len(edit['picture']) > 1:
        with ThreadPoolExecutor(DECODER_THREADS) as pool:
            planned = list(pool.map(plan_range, edit['picture']))
    else:
        planned = [plan_range(edit['picture'][0])]
    cache, properties = {}, {}
    for number, (filename, row, entry, range_notes) in enumerate(planned):
        properties[filename] = row
        cache[number] = entry
        notes.extend(range_notes)
    return cache, properties, 0


def analyse_auto_crops(edit, root, cache, ffmpeg):
    """Measure each automatic cover crop before choosing sizes across clips from the same source."""
    width, height = edit['size']
    analyses = {}
    for number, item in enumerate(edit['picture']):
        crop = item.get('crop', {})
        if crop.get('path') != 'auto' or item.get('fit', 'cover') != 'cover':
            continue
        _, sw, sh, _, _, _, _ = cache[number]
        analysis_width = 320
        analysis_height = max(2, round(sh / sw * analysis_width / 2) * 2)
        start, stop = float(item['in']), float(item['out'])
        faces = {}
        clock, subjects, _ = analyse(ffmpeg, source_path(root, edit['sources'], item['src']),
                                     analysis_width, analysis_height, start, stop, faces)
        selected = [(time, box) for time, box in zip(clock, subjects) if start <= time < stop]
        if not selected:
            raise ValueError('no frames for automatic crop')
        faces['samples'] = [sample for sample in faces['samples'] if start <= sample['t'] < stop]
        cw, ch = bounds(sw, sh, width / height)
        analyses[number] = {'source': item['src'], 'clock': [row[0] for row in selected],
                            'subjects': [row[1] for row in selected], 'faces': faces,
                            'crop_width': cw, 'crop_height': ch, 'explicit_zoom': 'zoom' in crop}
    return analyses


def crop_review_notes(name, at, start, speed, findings):
    """Turn sampled face findings into timecoded review notes on both relevant clocks."""
    descriptions = {'face_too_large': 'a detected face does not fit the crop; widen it or letterbox',
                    'people_do_not_fit': 'detected people do not fit one crop; cut between them or letterbox',
                    'face_outside_crop': 'a detected face leaves the smoothed crop; adjust it or letterbox'}
    return [f"Crop {name} at edit {project.format_time(at + item['t'])} "
            f"(source {project.format_time(start + item['t'] * speed)}): {descriptions[item['kind']]}."
            for item in findings]


def plan_picture(edit, root, cache, ffmpeg, ffprobe, temp, notes=None):
    """Snap picture edits, place joins, and resolve crop paths on the edit clock."""
    clips = []
    snaps = []
    cues = []
    cuts = []
    dissolves = []
    width, height = edit['size']
    analyses = analyse_auto_crops(edit, root, cache, ffmpeg)
    auto_zooms = consistent_zooms(analyses)
    for number, item in enumerate(edit['picture']):
        name = item['src']
        filename = source_path(root, edit['sources'], name)
        rawpath, sw, sh, times, end, tick, original_stop = cache[number]
        start = float(item['in'])
        stop = float(item['out'])
        gap = max(0.0, times[0] - start)
        if start >= stop or gap > .5 + max(tick, 1e-6) or stop > end + max(tick, 1e-6):
            raise ValueError('empty or uncovered picture range for ' + name)
        if gap > max(tick, 1e-6) and notes is not None:
            notes.append(f'Picture {name}: held its first decoded frame back {gap:.3f} s to cover the in-point.')
        speed = float(item.get('speed', 1))
        mode = item.get('retime', 'nearest')
        if not math.isfinite(speed) or speed <= 0 or mode not in ('nearest', 'blend', 'motion'):
            raise ValueError('invalid picture speed or retime mode')
        duration = (stop - start) / speed
        join = item.get('join', {'kind': 'cut'})
        kind = join.get('kind', 'cut')
        overlap = float(join.get('dur', 0)) if kind != 'cut' else 0
        if kind not in ('cut', 'dissolve', 'dip') or overlap < 0:
            raise ValueError('invalid join')
        if overlap and (not clips or overlap > min(duration, clips[-1]['duration'])):
            raise ValueError('invalid overlap duration')
        at = clips[-1]['at'] + clips[-1]['duration'] - overlap if clips else 0
        if len(clips) > 1 and at < clips[-2]['at'] + clips[-2]['duration']:
            raise ValueError('three-way joins are not supported')
        if clips:
            cuts.append(at)
            # A join is a candidate sound moment, withheld unless the edit asks for it: most footage cuts are silent.
            cues.append({'id': f'join-{len(clips)}', 't': at, 'sound': 'optional',
                         'role': join.get('role', 'whoosh'), 'sync': 'attack',
                         'enabled': bool(join.get('sound', False))})
            if kind == 'dissolve':
                dissolves.append({'start': at, 'end': at + overlap})
        for point, requested, actual in (('in', start, start), ('out', original_stop, stop)):
            covered = max(0, bisect.bisect_right(times, actual + max(tick, 1e-6)) - 1)
            snaps.append({'src': name, 'point': point, 'requested': requested, 'snapped': actual,
                          'delta': actual - requested,
                          'clock': 'source edit time', 'covering_frame_pts': times[covered]})
        crop = item.get('crop', {})
        path = crop.get('path', [[0, .5, .5]])
        fit = item.get('fit', 'cover')
        if fit not in ('cover', 'contain'):
            raise ValueError('invalid fit')
        zoom = float(crop.get('zoom', 1))
        crop_info = {}
        if path == 'auto' and fit == 'contain':
            path = [[0, .5, .5]]
            crop_info = {'method': 'whole frame (contain)'}
            if notes is not None:
                notes.append(f'Crop {name} at edit {project.format_time(at)}: whole frame (contain); '
                             'automatic cropping was not applied.')
        elif path == 'auto':
            info = analyses[number]
            match = auto_zooms.get(number)
            if match:
                zoom = match['zoom']
            crop_width, crop_height = bounds(sw, sh, width / height, zoom)
            targets, methods = face_targets(info['clock'], info['subjects'], info['faces'], crop_width, crop_height)
            local_times = [(time - start) / speed for time in info['clock']]
            path = propose(local_times, targets, crop_width, crop_height, .2)
            samples = [dict(sample, t=(sample['t'] - start) / speed) for sample in info['faces']['samples']]
            findings = face_review(samples, path, crop_width, crop_height)
            crop_info = {'method_spans': method_spans(local_times, methods, duration),
                         'face_detection': {'state': info['faces']['state'], 'reason': info['faces']['reason'],
                                            'sample_count': len(samples),
                                            'positive_samples': sum(bool(sample['boxes']) for sample in samples)},
                         'face_findings': findings, 'face_height': info['face_height'],
                         'zoom_source': 'explicit' if info['explicit_zoom'] else 'automatic'}
            if notes is not None:
                description = ', '.join(sorted(set(methods)))
                reason = f"; {info['faces']['reason']}" if info['faces']['reason'] else ''
                notes.append(f'Crop {name} at edit {project.format_time(at)}: {description}{reason}; '
                             'inspect the framing.')
                notes.extend(crop_review_notes(name, at, start, speed, findings))
                if match and match['constrained']:
                    notes.append(f'Crop {name} at edit {project.format_time(at)}: face size matching was limited '
                                 'by the crop or automatic zoom limit; compare the shots.')
                elif not info['explicit_zoom'] and info['face_height'] is None and any(
                        sample['boxes'] for sample in samples):
                    notes.append(f'Crop {name} at edit {project.format_time(at)}: too few face samples for '
                                 'automatic size matching; zoom remains 1.')
        elif isinstance(path, str):
            with open(root / path, encoding='utf-8') as file:
                loaded = json.load(file)
            path = loaded.get('path', loaded) if isinstance(loaded, dict) else loaded
            if isinstance(loaded, dict) and loaded.get('clock') == 'source':
                # reframe.py writes source-clock times; the edit counts from the clip's in-point at its speed.
                path = [[(key[0] - start) / speed, key[1], key[2]] for key in validate_path(path)]
        path = validate_path(path)
        clips.append({'src': name, 'file': filename, 'raw': rawpath, 'sw': sw, 'sh': sh, 'times': times,
                      'start': start, 'stop': stop, 'duration': duration, 'at': at,
                      'speed': speed, 'mode': mode, 'kind': kind, 'overlap': overlap,
                      'hold_previous': bool(item.get('hold_previous')),
                      'colour': join.get('color', 'black'), 'crop': path, 'zoom': zoom, 'crop_info': crop_info,
                      'fit': fit, 'background': item.get('background', 'black'), 'time_tick': tick})
    return clips, snaps, cues, cuts, dissolves


def audio_packet_end(ffprobe, filename, stream='a:0'):
    """Find the last audio packet's end without retaining the packet list."""
    command = [ffprobe, '-v', 'error', '-select_streams', str(stream), '-show_packets',
               '-show_entries', 'packet=pts_time,duration_time', '-of', 'csv=p=0', filename]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace')
    end = None
    for line in proc.stdout:
        values = line.strip().split(',')
        try:
            timestamp, duration = float(values[0]), float(values[1])
        except (ValueError, IndexError):
            continue
        if math.isfinite(timestamp) and math.isfinite(duration) and duration > 0:
            end = max(end if end is not None else -math.inf, timestamp + duration)
    proc.stdout.close()
    error = proc.stderr.read()
    if proc.wait() or end is None:
        raise ValueError('cannot determine audio stream end: ' + (error.strip() or filename))
    return end


def audio_rate(ffprobe, filename, stream=None):
    """Find the rate and audio stream bounds on FFmpeg's source presentation clock."""
    spec = importlib.util.spec_from_file_location('lf_transcribe_audio', Path(__file__).with_name('transcribe.py'))
    transcribe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transcribe)
    stream = transcribe.probe_audio(filename, stream, ffprobe)['index']
    command = [ffprobe, '-v', 'error', '-select_streams', str(stream), '-show_entries',
               'stream=sample_rate,start_time,duration:stream_tags=DURATION:format=start_time',
               '-of', 'json', filename]
    probe_data = json.loads(run(command).stdout)
    streams = probe_data.get('streams') or []
    if not streams:
        raise ValueError(f'no audio stream {stream} in {filename}; choose a source with sound')
    info = streams[0]
    rate = int(info['sample_rate'])
    if rate <= 0:
        raise ValueError('invalid sample rate: ' + filename)
    origin = float(probe_data.get('format', {}).get('start_time', 0))
    start = float(info.get('start_time', origin))
    duration = info.get('duration')
    tag = info.get('tags', {}).get('DURATION')
    if duration is not None:
        end = start + float(duration)
    elif tag:
        hours, minutes, seconds = tag.split(':')
        end = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    else:
        end = audio_packet_end(ffprobe, filename, stream)
    return rate, start - origin, end - origin


def tempo_filters(speed, rubberband):
    """Choose a measured pitch-preserving stretcher, retaining an atempo fallback."""
    if speed == 1:
        return []
    if rubberband and .01 <= speed <= 100:
        return ['aresample=48000:filter_size=16',
                f'rubberband=tempo={speed}:window=short:transients=smooth:channels=together']
    filters = []
    remaining = speed
    while remaining > 2:
        filters.append('atempo=2')
        remaining /= 2
    while remaining < .5:
        filters.append('atempo=.5')
        remaining *= 2
    if remaining != 1:
        filters.append(f'atempo={remaining}')
    return filters


def render_audio(ffmpeg, ffprobe, edit, root, clips, total, temp, output_dir, notes):
    """Render faded audio edits on independent sample clocks into track stems."""
    tracks = {}
    snaps = []
    rubberband = None
    for number, item in enumerate(edit.get('audio', [])):
        track = item['track']
        name = item['src']
        filename = audio_source_path(root, edit['sources'], name)
        at = float(item.get('at', 0))
        source = edit['sources'].get(name) or {}
        selected = source.get('audio_stream') if isinstance(source, dict) else None
        spec = importlib.util.spec_from_file_location('lf_selected_audio', Path(__file__).with_name('transcribe.py'))
        transcribe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(transcribe)
        selected = transcribe.probe_audio(filename, selected, ffprobe)['index']
        rate, stream_start, source_end = audio_rate(ffprobe, filename, selected)
        start = round(float(item['in']) * rate) / rate
        requested_end = round(float(item['out']) * rate) / rate
        end = min(requested_end, round(source_end * rate) / rate)
        if end < requested_end:
            notes.append(f'Audio {name} out clamped from {requested_end:.6f} to {end:.6f} s.')
        fade = float(item.get('fade_ms', 15)) / 1000
        fade_in = float(item.get('fade_in_ms', fade * 1000)) / 1000
        fade_out = float(item.get('fade_out_ms', fade * 1000)) / 1000
        curves = (item.get('fade_in_curve', 'tri'), item.get('fade_out_curve', 'tri'))
        if not track or any(char in track for char in ('/', '\\', ':')) or end <= start or min(fade, fade_in,
                                                                                               fade_out) < 0:
            raise ValueError('invalid audio item')
        if any(curve not in FADE_CURVES for curve in curves):
            raise ValueError(f'invalid audio fade curve {curves}; use one of {", ".join(FADE_CURVES)}')
        for point, actual in (('in', start), ('out', end)):
            requested = float(item[point])
            snaps.append({'src': name, 'point': point, 'requested': requested, 'snapped': actual,
                          'delta': actual - requested, 'clock': 'audio sample', 'sample_rate': rate,
                          'stream_start_s': stream_start})
        speeds = {clip['speed'] for clip in clips if clip['src'] == name and start < clip['stop']
                  and end > clip['start']}
        if len(speeds) > 1:
            raise ValueError('ambiguous audio retime speed for ' + name)
        speed = next(iter(speeds), 1.0)
        duration = (end - start) / speed
        filters = ['aresample=async=1:first_pts=0',
                   f'atrim=start_sample={round(start * rate)}:end_sample={round(end * rate)}',
                   'asetpts=PTS-STARTPTS']
        if speed != 1 and rubberband is None:
            rubberband = has_filter(ffmpeg, 'rubberband')
        use_rubberband = bool(rubberband and .01 <= speed <= 100)
        prefix = list(filters)
        tempo = tempo_filters(speed, use_rubberband)
        if use_rubberband:
            # Give the stretcher silence to flush its lookahead, then keep only the source's intended duration.
            tempo.insert(1, f'apad=pad_dur={max(.25, .25 * speed):.9f}')
            tempo.append(f'atrim=duration={duration:.9f}')
        filters.extend(tempo)
        filters.extend([f"volume={float(item.get('gain_db', 0))}dB", 'aresample=48000'])
        edge_in, edge_out = fade_edges(fade_in, fade_out, duration)
        if edge_in:
            filters.append(f'afade=t=in:st=0:d={edge_in}' + (f':curve={curves[0]}' if curves[0] != 'tri' else ''))
        if edge_out:
            filters.append(f'afade=t=out:st={duration - edge_out}:d={edge_out}'
                           + (f':curve={curves[1]}' if curves[1] != 'tri' else ''))
        if at < 0:
            filters.extend([f'atrim=start={-at}', 'asetpts=PTS-STARTPTS'])
        elif at > 0:
            # Delay in samples avoids rounding the edit clock to milliseconds.
            filters.append(f'adelay={round(at * 48000)}S:all=1')
        part = os.path.join(temp, f'audio-{number}.wav')
        command = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', filename, '-map', f'0:{selected}', '-vn',
                   '-af', ','.join(filters), '-ar', '48000', '-ac', '2', '-c:a', 'pcm_f32le', part]
        try:
            run(command)
        except RuntimeError:
            if not use_rubberband:
                raise
            fallback = prefix + tempo_filters(speed, False) + filters[len(prefix) + len(tempo):]
            command[command.index('-af') + 1] = ','.join(fallback)
            run(command)
            use_rubberband = False
            notes.append(f'Audio {name}: rubberband could not run; used atempo. Inspect retimed sync and sound.')
        if speed == 1.0:
            # The stem is padded to the film: only the part says that the sound stopped before the item did.
            measured = run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', part])
            part_end = float(json.loads(measured.stdout)['format'].get('duration') or 0) - max(0.0, at)
            if duration + min(0.0, at) - part_end > RANGE_SLACK_S:
                notes.append(f'Audio {name} decodes only to {start + part_end - min(0.0, at):.3f} s of the '
                             f'{end:.3f} s this item asks for; the rest of it is silent.')
        if speed != 1.0:
            # The padded track length hides time-stretcher shortfalls; measure the part before mixing.
            measured = run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', part])
            part_duration = float(json.loads(measured.stdout)['format']['duration'])
            expected = max(0.0, duration + at)
            difference = part_duration - expected
            snaps.append({'src': name, 'point': 'retime duration', 'clock': 'decoded audio part', 'speed': speed,
                          'expected_duration_s': expected, 'actual_duration_s': part_duration,
                          'delta': difference, 'stretcher': 'rubberband' if use_rubberband else 'atempo'})
            notes.append(f'Audio {name} retimed {speed:g}x: transients can move or repeat; '
                         'inspect picture and sound sync.')
            if speed < .5:
                notes.append(f'Audio {name} retimed below 0.5x: transient shifts may exceed one frame; '
                             'inspect every sync point and the tail.')
            if use_rubberband and rate != 48000:
                notes.append(f'Audio {name} uses a short resampling filter before retiming; '
                             'inspect high-frequency detail.')
            if not use_rubberband:
                notes.append(f'Audio {name} used atempo because rubberband is unavailable for this retime; '
                             'inspect transients and sync.')
            if abs(difference) > .001:
                notes.append(f'Audio {name} retimed part is {difference * 1000:+.1f} ms from its planned duration; '
                             'the track is padded or trimmed. Inspect the tail and sync.')
        tracks.setdefault(track, []).append(part)
    for track, parts in tracks.items():
        mix_track(ffmpeg, parts, total, output_dir / (track + '.wav'))
    return snaps


def fade_edges(fade_in, fade_out, duration):
    """The fade-in and fade-out lengths of an audio part, shrunk in proportion when together they exceed it.
    Equal fades give the earlier rule exactly: each is at most half the part."""
    if fade_in + fade_out <= duration:
        return fade_in, fade_out
    scale = duration / (fade_in + fade_out)
    return fade_in * scale, fade_out * scale


def mix_track(ffmpeg, parts, total, out, seconds=1800):
    """Mix one track's parts into a stem exactly `total` seconds long.

    apad=whole_dur pads to the film's length and then ends the stream by itself; the output option -t trims parts
    that run longer and bounds the file whatever the filters do. The earlier graph (amix, then an endless apad and
    atrim=duration) hung FFmpeg 9.0 in about one run in nine with two or more parts, writing silence without end."""
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y']
    for part in parts:
        command.extend(['-i', str(part)])
    inputs = ''.join(f'[{index}:a]' for index in range(len(parts)))
    graph = f'{inputs}amix=inputs={len(parts)}:duration=longest:normalize=0,apad=whole_dur={total}[a]'
    command.extend(['-filter_complex', graph, '-map', '[a]', '-t', str(total), '-c:a', 'pcm_f32le', str(out)])
    run(command, seconds)


def motion_retimes(ffmpeg, clips, properties, fps, temp, spool_limit, already_used):
    """Plan interpolated timestamps without storing interpolated RGB frames."""
    for clip in clips:
        if clip['mode'] != 'motion':
            continue
        if not any(abs(value - clip['start']) <= max(clip['time_tick'], 1e-6) for value in clip['times']):
            raise ValueError('motion interpolation cannot start inside a held source frame; '
                             'use nearest or blend retiming for this range')
        origin = properties[clip['file']]['presentation_origin_s']
        # PTS retiming precedes interpolation so interpolation runs on the output clock.
        vf = (f"trim=start={origin + clip['start']}:end={origin + clip['stop']},"
              f"setpts=(PTS-({origin + clip['start']})/TB)/{clip['speed']},tpad=stop_mode=clone:stop_duration=1,"
              f"minterpolate=fps={fps}:mi_mode=mci,trim=duration={clip['duration']},"
              + properties[clip['file']]['filter'])
        size = clip['sw'] * clip['sh'] * 3
        options = ['-copyts', '-threads', '1']
        reader = Frames(ffmpeg, clip['file'], vf, size, options, timestamps_only=True)
        times = reader.scan()
        if len(times) > math.ceil(clip['duration'] * fps) + 4:
            raise RuntimeError('interpolated frames exceed disk reservation')
        clip['motion_raw'] = FrameSource(ffmpeg, clip['file'], vf, size, options, times)
        clip['motion_times'] = times


class MovingOverlay:
    """A video with transparency drawn over the picture (a lower third or title made in Cavalry or another engine):
    decoded once and in order to straight-alpha RGBA, one of its frames per output frame, sized to its share of the
    film's width, holding its last frame if the film asks for more. RGB codecs (PNG, QuickTime Animation) keep their
    values, as sRGB graphics do in the picture; YUV with alpha (ProRes 4444, VP9) is read with the matrix its file
    declares."""

    def __init__(self, filename, width, spec, fps):
        probe = overlay_probe(filename)
        self.vp9 = probe['vp9']
        if not probe['alpha']:
            raise ValueError(f'{Path(filename).name} has no transparency ({probe["pix_fmt"]}); render it with an alpha '
                             'channel (PNG in a MOV, QuickTime Animation, ProRes 4444 or VP9 WebM)')
        if probe['rate'] != Fraction(str(fps)):
            raise ValueError(f'{Path(filename).name} runs at {probe["rate"]} fps and the film at {fps}: render it at '
                             "the film's rate, so each of its frames is one of the film's")
        self.filename, self.size = filename, probe['size']
        target = max(1, round(float(spec.get('w', 1.0)) * width))
        self.target = (target, max(1, round(self.size[1] * target / self.size[0])))
        self.process, self.index, self.image = None, -1, None

    def frame(self, index):
        """The overlay's frame `index` (0 is its first), decoding forward."""
        if self.process is None:
            command = [find_tool('ffmpeg'), '-v', 'error', '-nostdin'] + (['-c:v', 'libvpx-vp9'] if self.vp9 else [])
            command += ['-i', str(self.filename), '-vf', 'format=rgba', '-fps_mode', 'passthrough', '-f', 'rawvideo',
                        '-pix_fmt', 'rgba', '-']
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            self.index, self.image = -1, None
        size = self.size[0] * self.size[1] * 4
        while self.index < index:
            data = self.process.stdout.read(size)
            if len(data) < size:
                break
            self.index += 1
            image = Image.frombytes('RGBA', self.size, data)
            if self.target != self.size:
                # Resample premultiplied, so transparent pixels' colour does not bleed into the edges.
                image = image.convert('RGBa').resize(self.target, Image.Resampling.LANCZOS).convert('RGBA')
            self.image = image
        if self.image is None:
            raise ValueError(f'no frames could be decoded from the moving overlay {Path(self.filename).name}')
        return self.image

    def close(self):
        """Stop the decoder; a later frame() starts it again from the first frame."""
        if self.process is not None:
            self.process.kill()
            self.process.wait()
            self.process = None


def prepare_overlays(edit, root, width, cues, notes):
    """Load image overlays, open moving overlays and collect captions for a later burn pass."""
    images = []
    captions = []
    pictures = 0
    for overlay in edit.get('overlays', []):
        kind = overlay.get('kind')
        if kind == 'video':
            start, end = float(overlay['from']), float(overlay['to'])
            fade = float(overlay.get('fade_ms', 0)) / 1000
            if end <= start or fade < 0:
                raise ValueError('invalid overlay timing')
            filename = source_path(root, edit['sources'], overlay['src'])
            images.append((MovingOverlay(filename, width, overlay, edit['fps']), overlay, start, end, fade))
            continue
        if kind == 'blur':
            start, end = float(overlay['from']), float(overlay['to'])
            if end <= start or float(overlay.get('strength', 0.0)) < 0 or float(overlay.get('pad', 0.0)) < 0:
                raise ValueError('invalid blur overlay: from must be before to; strength and pad not negative')
            images.append((None, overlay, start, end, 0.0))
            continue
        if kind == 'captions':
            if CAPTIONS.is_file():
                spec = importlib.util.spec_from_file_location('legible_captions', CAPTIONS)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                # Read now so a malformed caption file fails before rendering; captions never become sound cues.
                module.read_input(root / overlay['file'])
                captions.append(overlay)
            else:
                notes.append('Captions skipped: captions.py is not present at ' + str(CAPTIONS))
            continue
        if kind != 'image':
            raise ValueError('unknown overlay kind')
        filename = source_path(root, edit['sources'], overlay['src'])
        image = Image.open(filename).convert('RGBA')
        pin = overlay.get('pin')
        if not (isinstance(pin, dict) and pin.get('fit', 'corners') == 'corners'):
            ow = max(1, round(float(overlay['w']) * width))
            oh = max(1, round(image.height * ow / image.width))
            image = image.resize((ow, oh), Image.Resampling.LANCZOS)
        start = float(overlay['from'])
        end = float(overlay['to'])
        fade = float(overlay.get('fade_ms', 0)) / 1000
        if end <= start or fade < 0:
            raise ValueError('invalid overlay timing')
        # An overlay may start before the film (cut.py's generated fade-in starts at minus its length); on the film
        # clock it appears at the first frame, so its cue is there and never at a negative time.
        cues.append({'id': f'overlay-{pictures}', 't': max(0.0, start), 'sound': 'optional',
                     'role': overlay.get('role', 'pop'), 'sync': 'attack',
                     'enabled': bool(overlay.get('sound', False))})
        pictures += 1
        images.append((image, overlay, start, end, fade))
    return images, captions



def source_grid_matches(clip, fps):
    """A unit-speed CFR clip whose in-point and timestamps follow the output frame grid."""
    times = clip['times']
    if clip['mode'] != 'nearest' or clip['speed'] != 1 or len(times) < 2:
        return False
    tick = max(1e-6, clip['time_tick'])
    if abs(times[nearest(times, clip['start'])] - clip['start']) > tick * .51:
        return False
    step = 1.0 / float(fps)
    precision = max(1e-6, .5 * 10 ** (math.floor(math.log10(max(abs(times[-1]), 1))) - 5))
    return all(abs(value - (times[0] + number * step)) <= tick * 1.01 + precision
               for number, value in enumerate(times))


def clip_sample(clip, time):
    """The renderer's choice of source frame for an edit time: {'times', 'raw', 'index', 'sample_time', 'blend'}.

    `index` is the decoded frame shown; `blend` is the share of the next frame mixed in under blend retiming (None
    otherwise). Layers (spatial.py) are matched to this same choice, never to a second calculation."""
    if clip['mode'] == 'motion':
        sample_time = max(0, time - clip['at'])
        times = clip['motion_times']
        rawpath = clip['motion_raw']
    else:
        sample_time = clip['start'] + max(0, time - clip['at']) * clip['speed']
        times = clip['times']
        rawpath = clip['raw']
    precision = 0.5 * 10 ** (math.floor(math.log10(max(abs(sample_time), 1))) - 5)
    interval = times[1] - times[0] if len(times) > 1 else 1.0
    tick_factor = 1.01 if clip.get('_matching_grid') else .50001
    tolerance = min(interval * .1, max(1e-6, precision, clip['time_tick'] * tick_factor))
    index = max(0, min(len(times) - 1, bisect.bisect_right(times, sample_time + tolerance) - 1))
    blend = None
    if clip['mode'] == 'blend' and index + 1 < len(times) and times[index + 1] < clip['stop']:
        blend = (sample_time - times[index]) / (times[index + 1] - times[index])
    return {'times': times, 'raw': rawpath, 'index': index, 'sample_time': sample_time, 'blend': blend}


def clip_framing(clip, time, width, height):
    """How the renderer places a clip's decoded frame (sw x sh) in the output frame at an edit time: contain
    (`size` and `offset` of the letterboxed picture) or cover (`box`, the crop in decoded pixels, rounded the way
    Pillow rounds a crop box)."""
    if clip['fit'] == 'contain':
        scale = min(width / clip['sw'], height / clip['sh'])
        size = (max(1, round(clip['sw'] * scale)), max(1, round(clip['sh'] * scale)))
        return {'fit': 'contain', 'size': size, 'offset': ((width - size[0]) // 2, (height - size[1]) // 2)}
    cw, ch = bounds(clip['sw'], clip['sh'], width / height, clip['zoom'])
    cx, cy = position(clip['crop'], max(0, time - clip['at']))
    cx = min(1 - cw / 2, max(cw / 2, cx))
    cy = min(1 - ch / 2, max(ch / 2, cy))
    box = ((cx - cw / 2) * clip['sw'], (cy - ch / 2) * clip['sh'],
           (cx + cw / 2) * clip['sw'], (cy + ch / 2) * clip['sh'])
    return {'fit': 'cover', 'box': tuple(int(round(value)) for value in box)}


def apply_framing(image, framing, width, height, background):
    """Place a decoded frame (or a layer frame at the decoded size) in the output frame."""
    if framing['fit'] == 'contain':
        image = image.resize(framing['size'], Image.Resampling.LANCZOS)
        canvas = Image.new(image.mode, (width, height), background)
        canvas.paste(image, framing['offset'])
        return canvas
    return image.crop(framing['box']).resize((width, height), Image.Resampling.LANCZOS)


def framing_matrix(framing, source_width, source_height, width, height):
    """The 3x3 matrix taking a point of the decoded frame (continuous pixels, edges on integers) to the output frame,
    for the framing clip_framing chose."""
    if framing['fit'] == 'contain':
        sx, sy = framing['size'][0] / source_width, framing['size'][1] / source_height
        tx, ty = framing['offset']
    else:
        x0, y0, x1, y1 = framing['box']
        sx, sy = width / (x1 - x0), height / (y1 - y0)
        tx, ty = -x0 * sx, -y0 * sy
    return np.array([[sx, 0, tx], [0, sy, ty], [0, 0, 1]], dtype=np.float64)


def render_clip(clip, time, handles, width, height):
    """Sample, crop and scale one picture clip at an edit time."""
    sample = clip_sample(clip, time)

    def get_frame(frame_index):
        """Read a PTS-selected frame from the forward reader or a legacy file handle."""
        handle = handles[sample['raw']]
        size = clip['sw'] * clip['sh'] * 3
        if hasattr(handle, 'frame'):
            raw = handle.frame(frame_index)
        else:
            handle.seek(frame_index * size)
            raw = handle.read(size)
        if len(raw) != size:
            raise RuntimeError('short decoded frame')
        return Image.frombytes('RGB', (clip['sw'], clip['sh']), raw)

    image = get_frame(sample['index'])
    if sample['blend'] is not None:
        image = Image.blend(image, get_frame(sample['index'] + 1), max(0, min(1, sample['blend'])))
    return apply_framing(image, clip_framing(clip, time, width, height), width, height, clip['background'])


# ----------------------------------------------------------------------------------------------- spatial layers

BLUR_STRENGTH = 0.04  # blur radius as a share of the output height
BLUR_PAD = 0.15  # padding as a share of the region's size on each side
POINT_BOX = 0.15  # a blur on a point track covers a square this share of the output height
# Why a layered overlay was not drawn on a frame, as the report counts it (reason prefix, cause).
SKIP_CAUSES = (('the track is lost', 'lost'), ('the layer is stale', 'stale'), ('another source', 'other_source'),
               ('a dissolve or dip', 'dissolve'), ('a held frame', 'held'), ("outside the layer's frames", 'outside'),
               ('no layer frame', 'missing'))


def layer_roles(spec):
    """[('pin' | 'behind' | 'blur', the layer reference)] for every layer an overlay reads."""
    roles = []
    if spec.get('kind') == 'blur':
        region = spec.get('region')
        if not isinstance(region, dict) or not isinstance(region.get('layer'), str):
            raise ValueError('a blur overlay needs "region": {"layer": "spatial/NAME.json"}')
        roles.append(('blur', region))
    for role in ('pin', 'behind'):
        if role in spec:
            if not isinstance(spec[role], dict) or not isinstance(spec[role].get('layer'), str):
                raise ValueError(f'"{role}" needs {{"layer": "spatial/NAME.json"}}')
            roles.append((role, spec[role]))
    return roles


def time_label(seconds):
    """An edit time as m:ss.ss."""
    return project.format_time(max(0.0, seconds))


def spans_of(frames, fps):
    """Consecutive output frame numbers as [(start s, end s)]."""
    spans = []
    for number in sorted(frames):
        if spans and number == spans[-1][1] + 1:
            spans[-1][1] = number
        else:
            spans.append([number, number])
    return [(start / fps, (end + 1) / fps) for start, end in spans]


def quad_centre(quad):
    """The projective centre of a quadrilateral: where its diagonals cross."""
    p1, p2, p3, p4 = quad
    d1, d2 = p3 - p1, p4 - p2
    denominator = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(denominator) < 1e-12:
        return quad.mean(axis=0)
    t = ((p2[0] - p1[0]) * d2[1] - (p2[1] - p1[1]) * d2[0]) / denominator
    return p1 + t * d1


def quad_area(quad):
    """A quadrilateral's area."""
    x, y = quad[:, 0], quad[:, 1]
    return abs(0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def premultiplied(image):
    """An RGBA image as a float32 premultiplied array, padded with two transparent pixels on every side."""
    array = np.asarray(image.convert('RGBA'), dtype=np.float32) / 255
    array[..., :3] *= array[..., 3:4]
    return np.pad(array, ((2, 2), (2, 2), (0, 0)))


def warp_overlay(image, overlay, quad, opacity, spatial):
    """Draw an RGBA overlay onto an RGB picture with its corners on `quad` (output pixels): a perspective warp with
    bilinear sampling of a copy scaled near the drawn size, so the edges are antialiased and nothing aliases."""
    width, height = image.size
    quad = np.asarray(quad, dtype=np.float64)
    if not np.all(np.isfinite(quad)) or opacity <= 0:
        return image
    x0, y0 = max(0, int(math.floor(quad[:, 0].min())) - 1), max(0, int(math.floor(quad[:, 1].min())) - 1)
    x1, y1 = min(width, int(math.ceil(quad[:, 0].max())) + 1), min(height, int(math.ceil(quad[:, 1].max())) + 1)
    if x1 <= x0 or y1 <= y0:
        return image
    edges = [float(np.linalg.norm(quad[(i + 1) % 4] - quad[i])) for i in range(4)]
    target = (max(edges[0], edges[2]), max(edges[1], edges[3]))
    if target[0] < overlay.width / 1.5 or target[1] < overlay.height / 1.5:
        overlay = overlay.resize((max(2, round(min(overlay.width, target[0]))),
                                  max(2, round(min(overlay.height, target[1])))), Image.Resampling.LANCZOS)
    source = premultiplied(overlay)
    w, h = overlay.size
    inverse = np.linalg.inv(spatial.homography([[0, 0], [w, 0], [w, h], [0, h]], quad))
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float64)
    points = np.stack([xs.ravel() + .5, ys.ravel() + .5, np.ones(xs.size)])
    mapped = inverse @ points
    u = mapped[0] / mapped[2] - .5 + 2
    v = mapped[1] / mapped[2] - .5 + 2
    limit_x, limit_y = source.shape[1] - 1, source.shape[0] - 1
    outside = (u < 0) | (v < 0) | (u > limit_x) | (v > limit_y) | (mapped[2] <= 0)
    u = np.clip(u, 0, limit_x - 1e-6)
    v = np.clip(v, 0, limit_y - 1e-6)
    left, top = np.floor(u).astype(int), np.floor(v).astype(int)
    fx, fy = (u - left)[:, None], (v - top)[:, None]
    sample = ((source[top, left] * (1 - fx) + source[top, left + 1] * fx) * (1 - fy)
              + (source[top + 1, left] * (1 - fx) + source[top + 1, left + 1] * fx) * fy)
    sample[outside] = 0
    sample = sample.reshape(y1 - y0, x1 - x0, 4) * opacity
    canvas = np.asarray(image, dtype=np.float32).copy()
    region = canvas[y0:y1, x0:x1] / 255
    region = sample[..., :3] + region * (1 - sample[..., 3:4])
    canvas[y0:y1, x0:x1] = np.clip(np.round(region * 255), 0, 255)
    return Image.fromarray(canvas.astype(np.uint8), 'RGB')


def matte_over(over, base, matte):
    """Put the matte's foreground of `base` back over `over`: 255 keeps base exactly, 0 keeps over."""
    weight = matte.astype(np.uint32)[..., None]
    mixed = (np.asarray(over, dtype=np.uint32) * (255 - weight) + np.asarray(base, dtype=np.uint32) * weight
             + 127) // 255
    return Image.fromarray(mixed.astype(np.uint8), 'RGB')


def blur_region(image, mask, radius):
    """Blur the picture under a mask (an 'L' image the size of the picture): pixelate, then soften, then composite
    through the mask, working only inside the mask's bounding box."""
    box = mask.getbbox()
    if box is None:
        return image
    margin = int(radius * 2) + 2
    x0, y0 = max(0, box[0] - margin), max(0, box[1] - margin)
    x1, y1 = min(image.width, box[2] + margin), min(image.height, box[3] + margin)
    region = image.crop((x0, y0, x1, y1))
    block = max(1, int(radius // 2))
    small = region.resize((max(1, region.width // block), max(1, region.height // block)), Image.Resampling.BOX)
    soft = small.resize(region.size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(max(1, radius / 2)))
    region.paste(soft, (0, 0), mask.crop((x0, y0, x1, y1)))
    image = image.copy()
    image.paste(region, (x0, y0))
    return image


def active_clips(intervals, number):
    """The clips on screen at an output frame, outgoing first (the renderer's own rule)."""
    return [clip for clip, start, end in intervals if start <= number < end]


class LayerPlan:
    """Spatial layers (references/spatial.md) drawn over the picture: image overlays pinned to a track or drawn
    behind a matte's foreground, and blur overlays over a tracked or matted region.

    Each layer frame is chosen from the source frame the renderer selected for that output frame (clip_sample) and
    placed through the renderer's own framing (clip_framing, framing_matrix, apply_framing), so a layer moves with
    the picture through crop, zoom, fit, reframe paths, rotation, pixel aspect and speed. A layer is drawn only over
    a clip of the source it was made from; under another source (a cutaway), during a dissolve or dip, on a held
    frame, a lost or missing frame or a stale layer, a pin or behind overlay is not drawn and the notes say where
    and why. A blur covers every clip of its source on screen, including both sides of a dissolve, and stops the
    render (fails closed) when any such frame has no usable layer frame."""

    def __init__(self, edit, root, clips, images, width, height, fps, count):
        spec = importlib.util.spec_from_file_location('lf_assemble_spatial', Path(__file__).with_name('spatial.py'))
        self.spatial = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.spatial)
        self.root = Path(root)
        self.sources = edit['sources']
        self.width, self.height, self.fps = width, height, float(fps)
        self.project_root = project.find_project(root)
        self.entries = {}
        self.readers = {}
        for number, (_, item, start, end, _) in enumerate(images):
            roles = layer_roles(item)
            if not roles:
                continue
            entry = {'number': number, 'spec': item, 'start': start, 'end': end, 'roles': {}, 'frames': {},
                     'skipped': {}, 'looks': set(), 'flicker': [], 'previous_matte': None, 'reference': None}
            for role, reference in roles:
                entry['roles'][role] = self.load(role, reference)
            self.entries[number] = entry
        self.intervals = clip_frame_intervals(clips, fps)
        self.schedule(count)

    def load(self, role, reference):
        """Read a layer for one role and check it can serve that role."""
        path = (self.root / reference['layer']).resolve()
        layer = self.spatial.read_layer(path)
        kind = layer['kind']
        if role == 'pin':
            fit = reference.get('fit', 'corners')
            if kind != 'track' or fit not in ('corners', 'follow'):
                raise ValueError(f'pin needs a track layer and fit corners or follow: {reference["layer"]}')
            if fit == 'corners' and self.spatial.track_shape(layer) == 'point':
                raise ValueError(f'{reference["layer"]} follows a point; pin it with "fit": "follow"')
            if reference.get('aspect', 'keep') not in ('keep', 'stretch'):
                raise ValueError('pin "aspect" is keep or stretch')
        if role == 'behind' and kind != 'matte':
            raise ValueError(f'behind needs a matte layer: {reference["layer"]} is a {kind}')
        if role == 'blur' and kind not in ('track', 'matte'):
            raise ValueError(f'a blur region needs a track or matte layer: {reference["layer"]}')
        state = self.spatial.layer_state(path, layer, self.project_root)
        return {'path': path, 'name': path.stem, 'file': reference['layer'], 'layer': layer, 'state': state,
                'reference': reference, 'relations': {}}

    def relation(self, use, clip):
        """'same' when a clip plays the layer's source as it was when the layer was made, 'stale' when it plays the
        layer's source but the layer no longer fits it, 'other' for any other source. Bound by the identity the
        edit records for the source (the map's size and SHA-256, never rehashed here), else by the file itself;
        a preview proxy is bound through the original file the edit names for its sound."""
        key = id(clip)
        if key not in use['relations']:
            layer, state = use['layer'], use['state']
            entry = self.sources.get(clip['src'])
            files = [Path(clip['file'])]
            if isinstance(entry, dict) and entry.get('audio_file'):
                files.append(Path(audio_source_path(self.root, self.sources, clip['src'])))
            by_path = [file for file in files if project.same_file(file, state['source_file'])]
            named = clip['src'] == layer['source'].get('alias') or bool(by_path)
            if isinstance(entry, dict) and isinstance(entry.get('sha256'), str):
                same = entry['sha256'] == layer['source']['sha256'] and entry.get('bytes') == layer['source']['size']
                named = named or same
            else:
                same = any(file.stat().st_size == layer['source']['size'] for file in by_path)
            if state['state'] == 'current' and same:
                result = 'same'
            else:
                result = 'stale' if named else 'other'
            use['relations'][key] = result
        return use['relations'][key]

    def pick(self, use, clip, time):
        """The layer frame(s) for a clip at an edit time, from the renderer's own frame choice: ({'index': i} or
        {'pair': (i, j), 'fraction': f, 'look': ...}, None), or (None, reason)."""
        spatial, layer = self.spatial, use['layer']
        times = layer['times']
        sample = clip_sample(clip, time)
        if clip['mode'] == 'motion':
            moment = clip['start'] + sample['sample_time'] * clip['speed']
            first = spatial.frame_index(times, moment)
            if first is None:
                return None, "outside the layer's frames"
            second = min(first + 1, len(times) - 1)
            span = times[second] - times[first]
            fraction = max(0.0, min(1.0, (moment - times[first]) / span)) if span > 0 else 0.0
            return {'pair': (first, second), 'fraction': fraction, 'look': 'motion-interpolated retime'}, None
        selected = sample['times'][sample['index']]
        first = spatial.match_frame(times, selected)
        if first is None:
            if selected < times[0] or selected > times[-1]:
                return None, "outside the layer's frames"
            return None, 'no layer frame for the source frame shown'
        if sample['blend'] is None:
            return {'index': first}, None
        second = spatial.match_frame(times, sample['times'][sample['index'] + 1])
        if second is None:
            return None, "outside the layer's frames"
        return {'pair': (first, second), 'fraction': max(0.0, min(1.0, sample['blend'])),
                'look': 'blended retime'}, None

    def usable(self, use, choice):
        """Whether a picked track frame (or pair) is tracked; matte frames always are."""
        if use['layer']['kind'] != 'track':
            return True
        indices = choice['pair'] if 'pair' in choice else (choice['index'],)
        return all(use['layer']['frames'][index]['state'] != 'lost' for index in indices)

    def frame_plan(self, entry, active, time):
        """What to draw for one overlay on one output frame: ([(clip, {role: choice})], None), or ([], the reason
        nothing is drawn)."""
        roles = entry['roles']
        blur = 'blur' in roles
        plans = []
        for role, use in roles.items():
            relations = [(clip, self.relation(use, clip)) for clip in active]
            mine = [clip for clip, relation in relations if relation != 'other']
            if not mine:
                names = ', '.join(sorted({clip['src'] for clip in active}))
                return [], f'another source is on screen ({names})'
            if any(relation == 'stale' for _, relation in relations):
                return [], 'the layer is stale: ' + '; '.join(use['state']['reasons'] or ['its source changed'])
            if len(active) > 1 and not blur:
                return [], 'a dissolve or dip is on screen (a pin or behind draws over a single shot)'
            for clip in mine:
                if clip.get('hold_previous'):
                    if blur:
                        continue
                    return [], 'a held frame is on screen'
                choice, reason = self.pick(use, clip, time)
                if reason is None and not self.usable(use, choice):
                    reason = 'the track is lost on this frame'
                if reason:
                    return [], reason
                plans.append((clip, role, choice))
        merged = {}
        for clip, role, choice in plans:
            merged.setdefault(id(clip), (clip, {}))[1][role] = choice
        return list(merged.values()), None

    def schedule(self, count):
        """Plan every layered overlay for every output frame before rendering. A blur that cannot cover its region
        on every frame where its source is on screen stops the render here, before anything is encoded."""
        failures = []
        for entry in self.entries.values():
            seen = False
            for number in range(count):
                time = number / self.fps
                if not entry['start'] <= time < entry['end']:
                    continue
                plan, reason = self.frame_plan(entry, active_clips(self.intervals, number), time)
                if reason is None:
                    entry['frames'][number] = plan
                    seen = seen or bool(plan)
                    for _, choices in plan:
                        entry['looks'].update(choice['look'] for choice in choices.values() if choice.get('look'))
                    continue
                entry['skipped'].setdefault(reason, []).append(number)
                if 'blur' in entry['roles'] and not reason.startswith('another source'):
                    failures.append((entry, number, reason))
            if 'blur' in entry['roles'] and not seen and not any(row[0] is entry for row in failures):
                failures.append((entry, None, 'its source is never on screen during the blur, so nothing would be '
                                              'blurred; check the layer and the blur times'))
        if failures:
            lines = []
            for entry in {id(row[0]): row[0] for row in failures}.values():
                by_reason = {}
                for owner, number, reason in failures:
                    if owner is entry:
                        by_reason.setdefault(reason, []).append(number)
                for reason, numbers in by_reason.items():
                    where = ', '.join(f'{time_label(a)}-{time_label(b)}' for a, b in
                                      spans_of([n for n in numbers if n is not None], self.fps)[:6])
                    lines.append(f"blur {entry['roles']['blur']['name']}: {reason}" + (f' at {where}' if where else ''))
            raise ValueError('a privacy blur must cover every frame of its source, so the render stopped: '
                             + '; '.join(lines))

    def matte_frame(self, use, clip, choice, time):
        """A matte frame placed in the output frame as an 'L' array, through the renderer's framing; a retimed pair
        takes the nearer frame."""
        index = choice['index'] if 'index' in choice else choice['pair'][round(choice['fraction'])]
        key = (str(use['path']), id(clip))
        if key not in self.readers:
            layer = use['layer']
            self.readers[key] = self.spatial.FrameReader(self.spatial.data_path(use['path'], layer),
                                                         layer['frame_size'], 'matte')
        frame = Image.fromarray(self.readers[key].frame(index), 'L')
        if frame.size != (clip['sw'], clip['sh']):
            frame = frame.resize((clip['sw'], clip['sh']), Image.Resampling.BILINEAR)
        return np.asarray(apply_framing(frame, clip_framing(clip, time, self.width, self.height),
                                        self.width, self.height, 0))

    def track_points(self, use, clip, choice, time):
        """A track frame in output pixels: (corners 4x2 or None, centre, size or None)."""
        spatial, layer = self.spatial, use['layer']
        if 'index' in choice:
            corners, point, _ = spatial.track_frame(layer, choice['index'])
        else:
            first = spatial.track_frame(layer, choice['pair'][0])
            second = spatial.track_frame(layer, choice['pair'][1])
            mix = choice['fraction']
            corners = None if first[0] is None else first[0] * (1 - mix) + second[0] * mix
            point = first[1] * (1 - mix) + second[1] * mix
        scale = np.array([clip['sw'] / layer['frame_size'][0], clip['sh'] / layer['frame_size'][1]])
        matrix = framing_matrix(clip_framing(clip, time, self.width, self.height), clip['sw'], clip['sh'],
                                self.width, self.height)
        if corners is not None:
            quad = spatial.apply_homography(matrix, corners * scale)
            return quad, quad_centre(quad), math.sqrt(quad_area(quad))
        return None, spatial.apply_homography(matrix, [point * scale])[0], None

    def blur_mask(self, entry, clip, choice, time):
        """The padded region a blur covers on one frame, as an 'L' mask the size of the output."""
        use, spec = entry['roles']['blur'], entry['spec']
        pad = float(spec.get('pad', BLUR_PAD))
        if use['layer']['kind'] == 'matte':
            matte = Image.fromarray(self.matte_frame(use, clip, choice, time), 'L')
            box = matte.point(lambda value: 255 if value >= 128 else 0).getbbox()
            # Thresholding a Gaussian-blurred mask at 4/255 grows it by about 2.15 sigma.
            grow = max(1.0, pad * (max(box[2] - box[0], box[3] - box[1]) if box else 0) / 2.15)
            grown = matte.point(lambda value: 255 if value >= 128 else 0).filter(ImageFilter.GaussianBlur(grow))
            mask = grown.point(lambda value: 255 if value >= 4 else 0)
        else:
            quad, centre, _ = self.track_points(use, clip, choice, time)
            if quad is None:
                side = float(spec.get('size', POINT_BOX)) * self.height / 2
                quad = centre + np.array([[-side, -side], [side, -side], [side, side], [-side, side]])
            middle = quad_centre(quad)
            quad = middle + (quad - middle) * (1 + 2 * pad)
            mask = Image.new('L', (self.width, self.height), 0)
            ImageDraw.Draw(mask).polygon([tuple(map(float, point)) for point in quad], fill=255)
        return mask.filter(ImageFilter.GaussianBlur(1.0)).point(lambda value: min(255, value * 2))

    def blur(self, image, number, time):
        """Blur every blur overlay's region on this frame (before titles and graphics are drawn, and before the
        frame is kept for a hold)."""
        for entry in self.entries.values():
            if 'blur' not in entry['roles'] or number not in entry['frames']:
                continue
            radius = max(2.0, float(entry['spec'].get('strength', BLUR_STRENGTH)) * self.height)
            for clip, choices in entry['frames'][number]:
                image = blur_region(image, self.blur_mask(entry, clip, choices['blur'], time), radius)
        return image

    def fitted(self, entry, overlay):
        """A corner-pinned image letterboxed (transparent) to the tracked region's shape on its key frame, so it is
        not stretched; unchanged with "aspect": "stretch". Made once per overlay."""
        if 'fitted' not in entry:
            use = entry['roles']['pin']
            entry['fitted'] = overlay
            frames = [frame for frame in use['layer']['frames'] if frame.get('corners') is not None]
            key = next((frame for frame in frames if frame['state'] == 'key'), frames[0] if frames else None)
            if use['reference'].get('aspect', 'keep') == 'keep' and key is not None:
                corners = np.asarray(key['corners'], dtype=np.float64) * use['layer']['frame_size']
                across = (np.linalg.norm(corners[1] - corners[0]) + np.linalg.norm(corners[2] - corners[3])) / 2
                down = (np.linalg.norm(corners[3] - corners[0]) + np.linalg.norm(corners[2] - corners[1])) / 2
                aspect = across / down if down > 0 else overlay.width / overlay.height
                width = max(overlay.width, round(overlay.height * aspect))
                height = max(overlay.height, round(overlay.width / aspect))
                if (width, height) != overlay.size:
                    canvas = Image.new('RGBA', (width, height), (0, 0, 0, 0))
                    canvas.paste(overlay, ((width - overlay.width) // 2, (height - overlay.height) // 2))
                    entry['fitted'] = canvas
        return entry['fitted']

    def reads(self, number):
        """Whether image overlay `number` is drawn through a layer."""
        return number in self.entries and 'blur' not in self.entries[number]['roles']

    def draw(self, number, image, overlay, opacity, time, frame_number):
        """Draw a pinned and/or behind image overlay on one output frame, or nothing where the plan says so."""
        entry = self.entries[number]
        if frame_number not in entry['frames']:
            return image
        clip, choices = entry['frames'][frame_number][0]
        spec = entry['spec']
        if 'pin' in choices:
            quad, centre, size = self.track_points(entry['roles']['pin'], clip, choices['pin'], time)
            if entry['roles']['pin']['reference'].get('fit', 'corners') == 'corners':
                over = warp_overlay(image, self.fitted(entry, overlay), quad, opacity, self.spatial)
            else:
                over = self.follow(entry, image, overlay, opacity, centre, size)
        else:
            over = image.copy()
            layer = overlay.copy()
            layer.putalpha(layer.getchannel('A').point(lambda value: round(value * max(0, opacity))))
            over.paste(layer, (round(float(spec.get('x', 0)) * self.width),
                               round(float(spec.get('y', 0)) * self.height)), layer)
        if 'behind' in choices:
            matte = self.matte_frame(entry['roles']['behind'], clip, choices['behind'], time)
            previous = entry['previous_matte']
            if previous is not None and previous[0] == frame_number - 1:
                change = float(np.mean(np.abs(matte.astype(np.int16) - previous[1]))) / 255
                entry['flicker'].append((time, change))
            entry['previous_matte'] = (frame_number, matte.astype(np.int16))
            over = matte_over(over, image, matte)
        return over

    def follow(self, entry, image, overlay, opacity, centre, size):
        """Move (and, for a region track, scale) an overlay with the track: from where x, y place it on its first
        drawn frame, or centred on the track plus "offset" (fractions of the output) when the pin gives one."""
        spec = entry['spec']
        reference = entry['roles']['pin']['reference']
        if entry['reference'] is None:
            entry['reference'] = (centre, size)
        start_centre, start_size = entry['reference']
        ratio = size / start_size if size and start_size else 1.0
        w, h = overlay.width * ratio, overlay.height * ratio
        if isinstance(reference.get('offset'), list):
            middle = centre + np.array([float(reference['offset'][0]) * self.width,
                                        float(reference['offset'][1]) * self.height])
        else:
            placed = np.array([float(spec.get('x', 0)) * self.width + overlay.width / 2,
                               float(spec.get('y', 0)) * self.height + overlay.height / 2])
            middle = centre + (placed - start_centre) * ratio
        quad = middle + np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]])
        return warp_overlay(image, overlay, quad, opacity, self.spatial)

    def close(self):
        """Stop every layer decoder."""
        for reader in self.readers.values():
            reader.close()

    def report(self, notes):
        """Each layered overlay's frames drawn and not drawn (with reasons), its track's worst error where drawn and
        a matte's measured change between frames where drawn; adds a note for each span not drawn and each
        interpolated retime."""
        rows = []
        for entry in self.entries.values():
            roles = entry['roles']
            label = ' and '.join(f"{role} {use['name']}" for role, use in roles.items())
            label = label[0].upper() + label[1:]
            total = len(entry['frames']) + sum(len(numbers) for numbers in entry['skipped'].values())
            row = {'overlay': entry['number'], 'kind': entry['spec'].get('kind'),
                   'roles': {role: {'layer': use['file'], 'kind': use['layer']['kind'],
                                    'state': use['state']['state'], 'reasons': use['state']['reasons']}
                             for role, use in roles.items()},
                   'from': entry['start'], 'to': entry['end'], 'frames': total, 'drawn_frames': len(entry['frames']),
                   'not_drawn': []}
            for reason, numbers in entry['skipped'].items():
                for start, end in spans_of(numbers, self.fps):
                    row['not_drawn'].append({'start': round(start, 6), 'end': round(end, 6), 'reason': reason})
                    if 'blur' in roles:
                        notes.append(f'{label}: nothing to blur {time_label(start)}-{time_label(end)}: {reason}.')
                    else:
                        notes.append(f'{label} not drawn {time_label(start)}-{time_label(end)}: {reason}.')
            row['not_drawn'].sort(key=lambda span: span['start'])
            row['frames_by_cause'] = {'drawn': len(entry['frames'])}
            for reason, numbers in entry['skipped'].items():
                cause = next((name for words, name in SKIP_CAUSES if reason.startswith(words)), 'other')
                row['frames_by_cause'][cause] = row['frames_by_cause'].get(cause, 0) + len(numbers)
            for look in sorted(entry['looks']):
                notes.append(f'{label} is drawn over a {look}: track corners are interpolated between tracked frames '
                             'and mattes take the nearer frame; look at it.')
            track = next((use['layer'] for use in roles.values() if use['layer']['kind'] == 'track'), None)
            if track:
                errors = [track['frames'][choice['index']]['error_px'] for plans in entry['frames'].values()
                          for _, choices in plans for choice in choices.values()
                          if 'index' in choice and track['frames'][choice['index']].get('error_px') is not None]
                row['track_error_px_worst'] = round(max(errors), 3) if errors else None
            if entry['flicker']:
                values = [value for _, value in entry['flicker']]
                worst = max(entry['flicker'], key=lambda pair: pair[1])
                row['matte_flicker'] = {'mean': round(float(np.mean(values)), 5), 'worst': round(worst[1], 5),
                                        'worst_at': round(worst[0], 6),
                                        'measure': 'mean absolute change of the drawn matte between consecutive '
                                                   'output frames (0-1); real movement counts too'}
            if 'blur' in roles:
                notes.append(f'{label} covers {len(entry["frames"])} frames; a privacy blur is not anonymisation: '
                             'a person checks every frame of it.')
            rows.append(row)
        return rows


def grid_tolerance(fps, clips):
    """Bound the accumulated source-clock rounding used for every output boundary."""
    rate = float(fps)
    precision = sum(max(float(clip.get('time_tick', 0)), 1e-6) / float(clip.get('speed', 1)) for clip in clips)
    return min(precision, .25 / rate)


def output_boundary(time, fps, tolerance):
    """Map a half-open time boundary to the first frame on or after it."""
    rate = float(fps)
    nearest = round(time * rate)
    if (nearest > 0 or time == 0) and abs(time - nearest / rate) <= tolerance:
        return nearest
    return math.ceil(time * rate - 1e-12)


def output_frame_count(total, fps, clips):
    """Use the same output-grid boundary as every clip's exclusive end."""
    return output_boundary(total, fps, grid_tolerance(fps, clips))


def clip_frame_intervals(clips, fps):
    """Snap starts and exclusive ends with one tolerance so adjacent cuts tile."""
    tolerance = grid_tolerance(fps, clips)
    return [(clip, output_boundary(clip['at'], fps, tolerance),
             output_boundary(clip['at'] + clip['duration'], fps, tolerance)) for clip in clips]


def render_picture(ffmpeg, clips, images, width, height, fps, total, output, layers=None):
    """Composite picture and image overlays into the shared capped encoder; `layers` (a LayerPlan) blurs regions
    before overlays are drawn and draws pinned and behind overlays."""
    handles = {}
    encoder = Encoder(ffmpeg, output, width, height, fps, 14, None, False, False, ENCODER_THREADS)
    count = output_frame_count(total, fps, clips)
    intervals = clip_frame_intervals(clips, fps)
    for clip in clips:
        clip['_matching_grid'] = source_grid_matches(clip, fps)
    held_images = {}
    previous_image = None

    def picture_for(clip, time):
        if not clip.get('hold_previous'):
            source = clip_sample(clip, time)['raw']
            if source not in handles:
                handles[source] = source.open() if isinstance(source, FrameSource) else open(source, 'rb')
            return render_clip(clip, time, handles, width, height)
        key = id(clip)
        if key not in held_images:
            if previous_image is None:
                raise ValueError('a hold needs a previous displayed frame')
            held_images[key] = previous_image.copy()
        return held_images[key].copy()

    try:
        for number in range(count):
            time = number / float(fps)
            active = active_clips(intervals, number)
            if not active:
                raise RuntimeError(f'gap in picture at {time:.6f}')
            active_sources = {clip_sample(clip, time)['raw'] for clip in active if not clip.get('hold_previous')}
            for source in list(handles):
                if source not in active_sources:
                    handles.pop(source).close()
            for key in list(held_images):
                if not any(id(clip) == key for clip in active):
                    del held_images[key]
            image = picture_for(active[0], time)
            for clip in active[1:]:
                incoming = picture_for(clip, time)
                fraction = min(1, max(0, (time - clip['at']) / clip['overlap'])) if clip['overlap'] else 1
                if clip['kind'] == 'dissolve':
                    # The outgoing image stays opaque beneath the arriving image.
                    image = Image.blend(image, incoming, fraction)
                elif clip['kind'] == 'dip':
                    colour = Image.new('RGB', (width, height), clip['colour'])
                    if fraction < .5:
                        image = Image.blend(image, colour, fraction * 2)
                    else:
                        image = Image.blend(colour, incoming, (fraction - .5) * 2)
                else:
                    image = incoming
            if layers is not None:
                image = layers.blur(image, number, time)
            previous_image = image.copy()
            for overlay_number, (overlay, spec, start, end, fade) in enumerate(images):
                if overlay is not None and start <= time < end:
                    if isinstance(overlay, MovingOverlay):
                        overlay = overlay.frame(int(math.floor((time - start) * float(fps) + 1e-6)))
                    opacity = min(1, (time - start) / fade, (end - time) / fade) if fade else 1
                    if layers is not None and layers.reads(overlay_number):
                        image = layers.draw(overlay_number, image, overlay, max(0, opacity), time, number)
                        continue
                    layer = overlay.copy()
                    layer.putalpha(layer.getchannel('A').point(lambda value: round(value * max(0, opacity))))
                    image.paste(layer, (round(float(spec.get('x', 0)) * width),
                                        round(float(spec.get('y', 0)) * height)), layer)
            encoder.write(np.asarray(image))
        for handle in handles.values():
            handle.close()
        handles.clear()
        encoder.close()
    except BaseException:
        encoder.abort()
        raise
    finally:
        for handle in handles.values():
            if hasattr(handle, 'abort'):
                handle.abort()
            else:
                handle.close()
        if layers is not None:
            layers.close()
        for overlay, *_ in images:
            if isinstance(overlay, MovingOverlay):
                overlay.close()
    return count


def render_picture_with_retry(ffmpeg, clips, images, width, height, fps, total, output, layer_factory=None):
    """Restart a failed seeked picture with a freshly scheduled layer plan and validated linear clock."""
    while True:
        for clip in clips:
            clip['_matching_grid'] = source_grid_matches(clip, fps)
        layers = layer_factory() if layer_factory is not None else None
        try:
            return render_picture(ffmpeg, clips, images, width, height, fps, total, output, layers), layers
        except PlaybackSeekError as error:
            error.source.retry_without_seek()


# ----------------------------------------------------------------------------------------------- plain cuts

# What a plain cut may contain. A key or kind not listed here (a line type added later, say) keeps its edit on the
# every-frame path until someone has shown both paths agree on it, so the plain path learns a thing by an entry here.
PLAIN_EDIT_KEYS = frozenset({'version', 'size', 'fps', 'sources', 'picture', 'audio', 'overlays', 'holds', 'declared',
                             'cues', 'film_fades', 'paper'})
PLAIN_PICTURE_KEYS = frozenset({'src', 'in', 'out', 'speed', 'retime', 'join', 'fit', 'background', 'crop', 'line',
                                'hold_previous'})
PLAIN_SOURCE_KEYS = frozenset({'file', 'audio_file', 'audio_stream', 'sha256', 'bytes'})
PLAIN_OVERLAY_KINDS = frozenset({'captions'})


def plain_cut_reason(edit, clips, properties, fps):
    """Why this plan needs every frame in Python, or '' when FFmpeg can draw its picture and Python need only say which
    frame comes next. This is the one place that decides, and it allows only what has been compared with the
    every-frame path: anything it does not recognise stays there."""
    extra = sorted(set(edit) - PLAIN_EDIT_KEYS)
    if extra:
        return f'the edit has {extra[0]}'
    for name, entry in edit['sources'].items():
        extra = sorted(set(entry) - PLAIN_SOURCE_KEYS) if isinstance(entry, dict) else []
        if extra:
            return f'source {name} has {extra[0]}'
    for overlay in edit.get('overlays', []):
        if overlay.get('kind') not in PLAIN_OVERLAY_KINDS:
            return f"it draws a {overlay.get('kind', 'graphic')} overlay"
    for item in edit['picture']:
        extra = sorted(set(item) - PLAIN_PICTURE_KEYS)
        if extra:
            return f"{picture_line(item)}a picture line has {extra[0]}"
    tiled = 0
    for clip, first, end in clip_frame_intervals(clips, fps):
        where = clip.get('src', 'a source')
        if clip['kind'] != 'cut' or clip['overlap']:
            return f"{where} joins with a {clip['kind']}"
        if clip['hold_previous']:
            return f'{where} is a held frame'
        if clip['mode'] != 'nearest':
            return f"{where} has a {clip['mode']} retime"
        if clip['crop_info'].get('method_spans') is not None:
            return f'{where} has an automatic crop'
        if len({(key[1], key[2]) for key in clip['crop']}) > 1:
            return f'{where} has a moving crop'
        if clip['fit'] == 'contain' and str(clip['background']).lower() not in ('black', '#000', '#000000'):
            return f'{where} is letterboxed on a colour'
        if properties[clip['file']].get('field_order') not in ('unknown', 'progressive', None):
            return f'{where} is interlaced'
        if first != tiled:
            return f'{where} does not follow the line before it'
        tiled = end
    return ''


def native_709(source):
    """Whether a source's samples (its row in the report's sources) are already this film's: 8-bit 4:2:0, limited range,
    BT.709 as colour_filter reads them. Such a picture stays in YUV, without the trip through RGB that softens colour
    edges on the every-frame path."""
    unknown = ('unknown', 'unspecified', 'reserved', None)
    fallback = 'smpte170m' if source['coded_width'] <= 1024 and source['coded_height'] <= 576 else 'bt709'
    matrix = fallback if source.get('source_matrix') in unknown else source['source_matrix']
    return (source.get('source_pixel_format') == 'yuv420p' and source.get('source_range') in (*unknown, 'tv', 'mpeg')
            and matrix == 'bt709' and source.get('source_transfer') in (*unknown, 'bt709')
            and source.get('source_primaries') in (*unknown, 'bt709'))


def plain_framing(clip, width, height):
    """The FFmpeg filters that place a clip's frames as clip_framing places them, from its own whole-pixel box or size
    and offset, and whether every position falls on a chroma sample."""
    framing = clip_framing(clip, 0, width, height)
    resize = f'scale={width}:{height}:flags=lanczos'
    if framing['fit'] == 'contain':
        (w, h), (x, y) = framing['size'], framing['offset']
        steps = [f'scale={w}:{h}:flags=lanczos', f'pad={width}:{height}:{x}:{y}:black']
        return steps, not (w % 2 or h % 2 or x % 2 or y % 2)
    x0, y0, x1, y1 = framing['box']
    if (x0, y0, x1, y1) == (0, 0, clip['sw'], clip['sh']):
        return [resize], True
    w, h = x1 - x0, y1 - y0
    return [f'crop={w}:{h}:{x0}:{y0}:exact=1', resize], not (w % 2 or h % 2 or x0 % 2 or y0 % 2)


def plain_source(clip, width, height, fps, end):
    """The decoder for one plain clip: FFmpeg crops, scales and converts, and hands over 4:2:0 frames ready to encode.
    It stops at the last frame the film shows, and its playback is checked against the timestamps planned for them."""
    raw = clip['raw']
    needed = clip_sample(clip, (end - 1) / float(fps))['index'] + 1
    clock = raw.clock + f'trim=end_frame={needed},'
    framing, on_chroma = plain_framing(clip, width, height)
    if native_709(raw.properties) and on_chroma:
        steps = [f"scale={clip['sw']}:{clip['sh']}:flags=lanczos", 'setsar=1', *framing, 'format=yuv420p']
    else:
        # The every-frame path's own conversion to RGB, and the encoder's own conversion from it.
        steps = [raw.vf[len(raw.clock):], *framing, COLOUR]
    options = list(raw.options)
    options[options.index('-threads') + 1] = str(DECODER_THREADS)
    return FrameSource(raw.ffmpeg, raw.filename, clock + ','.join(steps), width * height * 3 // 2, options,
                       raw.times[:needed], raw.properties, clock)


def render_plain_picture(ffmpeg, clips, sources, width, height, fps, total, output, lossless=False):
    """Encode a plain cut: FFmpeg decodes, frames and converts one clip at a time, clip_sample chooses each output frame
    exactly as the every-frame path does, and Python forwards those frames' bytes without touching a pixel. `lossless`
    makes an intermediate for a caption burn, which encodes for delivery after it."""
    if lossless:
        options = ['-vf', TAG_BT709, '-c:v', 'libx264', '-preset', 'ultrafast', '-qp', '0', '-threads',
                   str(ENCODER_THREADS), '-movflags', '+faststart', '-f', 'mp4']
    else:
        options = h264_args(width, height, fps, threads=ENCODER_THREADS)
        options[1] = 'format=yuv420p,' + TAG_BT709
    encoder = Encoder(ffmpeg, output, width, height, fps, pixels='yuv420p', options=options)
    window = None
    try:
        for clip, first, end in clip_frame_intervals(clips, fps):
            if first >= end:
                continue
            window = sources[id(clip)].open()
            for number in range(first, end):
                encoder.write_raw(window.frame(clip_sample(clip, number / float(fps))['index']))
            window.close()
            window = None
        encoder.close()
    except BaseException:
        encoder.abort()
        if window is not None:
            window.abort()
        raise
    return output_frame_count(total, fps, clips)


def render_plain_with_retry(ffmpeg, clips, width, height, fps, total, output, lossless=False):
    """Plan the plain decoders once, and restart a failed seeked clip with a validated linear clock."""
    for clip in clips:
        clip['_matching_grid'] = source_grid_matches(clip, fps)
    sources = {id(clip): plain_source(clip, width, height, fps, end)
               for clip, first, end in clip_frame_intervals(clips, fps) if first < end}
    while True:
        try:
            return render_plain_picture(ffmpeg, clips, sources, width, height, fps, total, output, lossless)
        except PlaybackSeekError as error:
            error.source.retry_without_seek()


def picture_path_text(path):
    """The picture path a render took, in a sentence."""
    if path['path'] == 'ffmpeg':
        return 'FFmpeg drew the picture (a plain cut)'
    return f"every frame through Python ({path['reason']})"


def caption_options(overlay):
    """Pass a captions overlay's placement and style fields to captions.py burn."""
    options = []
    for key, flag in (('safe', '--safe'), ('font', '--font'), ('font_size', '--font-size')):
        if key in overlay:
            value = overlay[key]
            options += [flag, ','.join(str(v) for v in value) if isinstance(value, list) else str(value)]
    for box in overlay.get('avoid', []):
        options += ['--avoid', ','.join(str(v) for v in box)]
    if 'plate' in overlay:
        options.append('--plate' if overlay['plate'] else '--no-plate')
    if overlay.get('highlight'):
        options.append('--highlight')
    return options


def burn_captions(captions, root, picture, temp):
    """Burn captions with captions.py after the picture is rendered, one overlay at a time."""
    current = picture
    reports = []
    for index, overlay in enumerate(captions):
        output = Path(temp) / f'caption-{index}.mp4'
        report = Path(temp) / f'caption-{index}.json'
        # Lossless whatever the preset, and this file exists only to be encoded for delivery after the burn.
        command = [sys.executable, '-I', str(CAPTIONS), 'burn', str(current), str(root / overlay['file']),
                   '--out', str(output), '--json', str(report), '--crf', '0', '--preset', 'ultrafast']
        command += caption_options(overlay)
        run(command, 6 * 3600)
        reports.append(json.loads(report.read_text(encoding='utf-8')))
        if index:
            current.unlink(missing_ok=True)
        current = output
    return current, reports


def cap_caption_encode(ffmpeg, source, destination, width, height, fps, expected_frames):
    """Apply the shared level cap without a lossy YUV-to-RGB-to-YUV round trip."""
    rate = exact_rate(fps)
    options = h264_args(width, height, fps, threads=ENCODER_THREADS)
    options[1] = f'setpts=N*{rate.denominator}/({rate.numerator}*TB),format=yuv420p,{TAG_BT709}'
    command = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-i', str(source), '-map', '0:v:0', '-an',
               '-frames:v', str(expected_frames), '-fps_mode', 'passthrough', *options, str(destination)]
    run(command, 6 * 3600)
    ffprobe = find_tool('ffprobe')
    if not ffprobe:
        raise ValueError('ffprobe is required to verify caption burn frames')
    count = decoded_count(ffprobe, destination)
    if count != expected_frames:
        raise ValueError(f'caption burn returned {count} frames, expected {expected_frames}')


def export(edit, out, report_path, temp, stage, picture, cues, cuts, dissolves, report):
    """Write sidecars in staging and move them to their final names after success."""
    events = sorted(cues + edit.get('cues', []), key=lambda cue: cue['t'])
    paper = edit.get('paper')
    if isinstance(paper, dict) and isinstance(paper.get('film_md_sha256'), str):
        # cut.py render passes the paper identity (film.md and its sources): the list is v2, bound to the version
        # folder it is copied into beside manifest.json, and every reader checks it through cue_list.py.
        rate = exact_rate(edit['fps'])
        identity = dict(cue_list.paper_identity(paper['film_md_sha256'], paper.get('sources') or {}), path='.')
        write_json(stage / 'edit-cues.json', {
            'version': 'v2', 'clock': 'seconds from the first frame of the film',
            'fps': rate.numerator if rate.denominator == 1 else f'{rate.numerator}/{rate.denominator}',
            'exported_from': 'assemble.py edit-cues (cut.py render)', 'provenance': 'exported', 'picture': identity,
            'sections': [],
            'events': [cue_list.upgrade_event(cue) for cue in events]})
    else:
        # A standalone edit has no paper identity: the list stays v1 (unversioned), with the exact rate as a number.
        write_json(stage / 'edit-cues.json', {'fps': float(exact_rate(edit['fps'])), 'events': events})
    holds = edit.get('holds', [])
    declared = edit.get('declared', [])
    dips = [{'start': clip['at'], 'end': clip['at'] + clip['overlap']}
            for clip in report.pop('_clips') if clip['kind'] == 'dip']
    ranges = sorted((float(x['start']), float(x['end'])) if isinstance(x, dict)
                    else (float(x[0]), float(x[1])) for x in holds + dips + declared)
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    ignore = ','.join(f'{start:.3f}-{end:.3f}' for start, end in merged)
    write_json(stage / 'declared.json', {'cuts': cuts, 'holds': holds, 'designed': declared,
                                         'dissolves': dissolves, 'ignore': ignore})
    write_json(stage / 'assemble-report.json', report)
    pairs = [(Path(picture), out)]
    for path in stage.iterdir():
        if path.name == 'assemble-report.json' and report_path:
            target = Path(report_path).resolve()
        else:
            target = out.parent / path.name
        pairs.append((path, target))
    if len({target for _, target in pairs}) != len(pairs):
        raise ValueError('output paths collide')
    backups = []
    installed = []
    try:
        for index, (_, target) in enumerate(pairs):
            if target.exists():
                backup = Path(temp) / f'previous-output-{index}'
                os.replace(target, backup)
                backups.append((backup, target))
        for source, target in pairs:
            os.replace(source, target)
            installed.append(target)
    except OSError:
        for target in installed:
            target.unlink(missing_ok=True)
        for backup, target in reversed(backups):
            os.replace(backup, target)
        raise



def main():
    """Validate the edit, stage outputs and publish them only after rendering succeeds."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('edit')
    parser.add_argument('--out', required=True)
    parser.add_argument('--json')
    parser.add_argument('--every-frame', action='store_true',
                        help='draw every frame in Python even when the edit is a plain cut')
    parser.add_argument('--spool-gib', type=float, default=8,
                        help='legacy compatibility option; picture frames are streamed instead of spooled')
    args = parser.parse_args()
    try:
        ffmpeg = find_tool('ffmpeg')
        ffprobe = find_tool('ffprobe')
        if not ffmpeg or not ffprobe:
            raise ValueError('FFmpeg and ffprobe are required')
        if not math.isfinite(args.spool_gib) or args.spool_gib <= 0:
            raise ValueError('spool-gib must be positive')
        edit_path = Path(args.edit).resolve()
        root = edit_path.parent
        edit = json.loads(edit_path.read_text(encoding='utf-8'))
        if edit.get('version') != 1 or not edit.get('picture'):
            raise ValueError('version 1 and at least one picture item are required')
        width, height = map(int, edit['size'])
        # A decimal NTSC rate (29.97) means 30000/1001; the encoders get the exact rate, the arithmetic a float.
        rate = exact_rate(edit['fps'])
        fps = float(rate)
        if width <= 0 or height <= 0 or width % 2 or height % 2:
            raise ValueError('size must be positive and even')
        out = Path(args.out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        targets = {out, out.parent / 'edit-cues.json', out.parent / 'declared.json'}
        if any(overlay.get('kind') == 'captions' for overlay in edit.get('overlays', [])):
            targets.add(out.parent / 'caption-burn.json')
        targets.add(Path(args.json).resolve() if args.json else out.parent / 'assemble-report.json')
        targets.update(out.parent / (item['track'] + '.wav') for item in edit.get('audio', []))
        project.refuse_overwriting_inputs(sorted(targets), edit_inputs(edit, root, edit_path))
        picture_sources = {source_path(root, edit['sources'], item['src']) for item in edit['picture']}
        notes = []
        with tempfile.TemporaryDirectory(prefix='legible-footage-', dir=out.parent) as temp:
            stage = Path(temp) / 'stage'
            stage.mkdir()
            limit = int(args.spool_gib * 1024 ** 3)
            cache, properties, used = conform(ffmpeg, ffprobe, edit, root, temp, limit, notes)
            clips, snaps, cues, cuts, dissolves = plan_picture(edit, root, cache, ffmpeg, ffprobe, temp, notes)
            total = clips[-1]['at'] + clips[-1]['duration']
            if total <= 0:
                raise ValueError('zero duration')
            motion_retimes(ffmpeg, clips, properties, fps, temp, limit, used)
            images, captions = prepare_overlays(edit, root, width, cues, notes)
            picture = Path(temp) / 'picture.mp4'
            layer_factory = None
            if any(layer_roles(spec) for _, spec, _, _, _ in images):
                def layer_factory():
                    """Schedule every layer before creating an encoder, including on a playback retry."""
                    return LayerPlan(edit, root, clips, images, width, height, rate,
                                     output_frame_count(total, rate, clips))
            why = 'asked for' if args.every_frame else plain_cut_reason(edit, clips, properties, rate)
            layers = None
            if not why:
                try:
                    count = render_plain_with_retry(ffmpeg, clips, width, height, rate, total, picture,
                                                    bool(captions))
                except (OSError, RuntimeError, ValueError) as error:
                    # The every-frame path stays the authority: it reports a real source fault in its own words.
                    why = f'the FFmpeg picture path failed: {str(error)[:300]}'
            if why:
                count, layers = render_picture_with_retry(ffmpeg, clips, images, width, height, rate, total,
                                                          picture, layer_factory)
            path = {'path': 'every-frame', 'reason': why} if why else {'path': 'ffmpeg', 'reason': 'plain cut'}
            if captions:
                captioned, caption_reports = burn_captions(captions, root, picture, temp)
                write_json(stage / 'caption-burn.json', {'version': 1, 'overlays': caption_reports})
                for caption_report in caption_reports:
                    for finding in caption_report.get('review', []):
                        if finding.get('rule') == 'caption reduced to fit':
                            notes.append(f"Caption {finding['cue']} reduced from {finding['requested_size_px']} to "
                                         f"{finding['used_size_px']} px; choose a wider area or shorter caption.")
                picture.unlink(missing_ok=True)
                picture = Path(temp) / 'caption-capped.mp4'
                cap_caption_encode(ffmpeg, captioned, picture, width, height, rate, count)
                notes.append('Caption burn used lossless YUV intermediates before the shared level-capped encoder; '
                             'review legibility.')
            snaps.extend(render_audio(ffmpeg, ffprobe, edit, root, clips, total, temp, stage, notes))
            hdr = {item['src'] for item in edit['picture']
                   if properties[source_path(root, edit['sources'], item['src'])].get('hdr_transfer')}
            report = {'duration_s': total, 'frames': count, 'picture_path': path, 'snaps': snaps,
                      'hdr_sources': sorted(hdr),
                      'sources': properties,
                      'spool_budget_bytes': limit, 'spool_limit_enforced': False, 'source_spool_bytes': used,
                      'motion_spool_bytes': 0, '_clips': clips,
                      'retimes': [{'src': clip['src'], 'in': clip['start'], 'out': clip['stop'],
                                   'speed': clip['speed'], 'mode': clip['mode']}
                                  for clip in clips if clip['speed'] != 1],
                      'crops': [{'src': clip['src'], 'path': clip['crop'], 'fit': clip['fit'],
                                 'zoom': clip['zoom'], **clip['crop_info']} for clip in clips], 'notes': notes}
            if layers is not None:
                report['layers'] = layers.report(notes)
            export(edit, out, args.json, temp, stage, picture, cues, cuts, dissolves, report)
        print(f'Rendered {count} frames; {len(snaps)} snap points; {len(notes)} review notes.')
        print('Picture: ' + picture_path_text(path))
        for note in notes:
            print('NOTE: ' + note)
        return 1 if notes else 0
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, TypeError, OverflowError) as error:
        print(f'assemble: cannot run: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
