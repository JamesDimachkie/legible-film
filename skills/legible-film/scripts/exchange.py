#!/usr/bin/env python3
"""Write a version as Final Cut Pro 7 XML (xmeml), or read an editing application's timeline and follow its words.
Premiere Pro can export this format with File > Export > Final Cut Pro XML; Final Cut Pro X does not import it.

  python exchange.py write PROJECT vNNN --out TIMELINE.xml [--format xmeml] [--relative] [--verify]
  python exchange.py read TIMELINE.xml [--track N] [--json timeline.json]
  python exchange.py words TIMELINE.xml (--project PROJECT | --words WORDS.json ...) [--map FILE=ALIAS ...]
                     [--track N] [--json words.json]
  python exchange.py compare BEFORE.xml AFTER.xml (--project PROJECT | --words WORDS.json ...) [--map FILE=ALIAS]
                     [--captions BEFORE.srt] [--json changes.json]

read: one audio track (default 1, the first; the dialogue track in most edits) as clips with exact rates. A clip
next to a transition carries -1 for its start or end and extra source frames (handles) around the cut; the real cut
is the transition's start plus its cutPointTicks, and the handles are reported separately. Source positions use
Premiere's pproTicks (254016000000 per second) when present, so nothing is rounded to frames; otherwise frames at the
clip's rate, resolved by inheritance: the clip's own <rate>, then its sequence's timebase; a missing ntsc flag is
taken from the sequence and the clip's file when they have the same timebase (they must agree), and a clip rate that
is malformed or ambiguous is not mapped. Handles are sequence frames and convert to seconds at the sequence's rate,
whatever the clip's rate. Drop-frame is a timecode label, never applied to numeric frames. A disabled
clip or a disabled track does not play: its clips are skipped and listed as skipped. Other audio tracks are listed
(disabled, or enabled with clips this run did not read).
words: every source word placed at its time in the edit, written in the shared edit-time word schema
({"version": 1, "words": [{"id", "text", "start", "end", "estimated", "source", ...}]}, edit seconds), which
captions.py check --words reads. Transcripts come from the project's map (--project: every map/<alias>/words.json,
with map/sources.json paths and hashes), from WORDS.json files (this skill's words.json, or {"sources": [{"id",
"media_reference", "words": [...]}]}), or from an explicit --map FILE=ALIAS. When the timeline's file can be read
here, its content decides: it takes the transcript of the source with the same SHA-256 (found under any name), and a
same-named source with different content is refused. An explicit --map cannot override recorded stale media; check and
confirm the transcript against a changed proxy or rewrap, or retranscribe. When the file cannot be read, a file
name only one transcript has is accepted and the match says it was not verified; a name several transcripts share is
not mapped. Each match says how it was made; every clip without a transcript is listed with the reason. A word cut
by a clip edge is marked split; a word only inside a transition's handles is marked handle-only and given no time.
Words keep their transcript id and carry an identity of URL-escaped source alias + ':' + URL-escaped local id;
states and compare's word lists use that identity. Missing IDs use the reserved !row-N form. Duplicate word IDs or
source aliases are errors. An unbound transcript maps with its missing provenance disclosed; a stale transcript is
not mapped, even with --map, until it is retranscribed or checked and confirmed with map.py confirm-words.
Matches of confirmed transcripts name who confirmed the binding, rather than implying the transcript was made from
the replacement bytes.
An overlapping audio transition is attached to a word in edit seconds and makes its edges estimated. Compare also
includes both edits' word rows. JSON output never replaces an input, including through a hard link.
compare: words used in BEFORE and cut in AFTER, and, with --captions, each BEFORE caption followed through its words
into AFTER: unchanged, moved, stale (words cut, listed), removed, split (a word the edit cut into, part of its source
interval gone) or unknown (with the reason). Each use of a word is matched to one use in AFTER; when the edits use a
source word a different number of times, which use was cut cannot be told from word IDs, so its caption is unknown
and the word is listed as used a different number of times. A caption whose text is not found among BEFORE's words
is unknown too. A word that clips this run could not map, clips with an uncertain transcript, or enabled
tracks it did not read might still hold is unknown, never called cut. The result carries each side's coverage
(track read, clips skipped, not mapped or unmatched, tracks left out) and says whether the comparison is complete.
The duration change converts each sequence at its own frame rate.

write: original mapped media, editable picture and dialogue, available rendered graphic images, markers and a separate
SRT, with a lined-up camera or mic at the in-point its offset gave. The printed and saved notes list what was not
carried. Paths are absolute file URLs unless --relative is given.
When the manifest records source identities, size is checked; --verify also checks the recorded SHA-256. Older
versions without that record are identified as unverified.
This exporter has been checked by its round trip and OpenTimelineIO's Final Cut Pro 7 XML (xmeml) adapter on
synthetic fixtures, and opened in Premiere Pro 26.3 on macOS in one editor's synthetic test: media online, clips, a
dissolve, J and L cuts, markers and captions in place. That test found the sequence's pixel aspect and the stereo pan
missing; both are written now, not yet re-checked in Premiere. Resolve is untested. Compare it with the render.
OpenTimelineIO JSON output is not implemented.

What it does not do: interpret speed changes, time remaps, effects, nested sequences or multicam clips (reported as
not mapped, never guessed); read more than one audio track per run; judge how a crossfade sounds (transition audio is
reported as unassessed); or decide whether a stale caption is wrong (a caption may tidy speech on purpose). Following
captions through the edit compares them with the paper's words, not with the sound: check captions against a
transcript of the delivered audio too (captions.py check --words with transcribe.py's output, or check.py).
Exit 0 for a written hand-off, or when every clip is mapped and matched, the comparison is complete and nothing is
stale; 1 when a clip is not
mapped or has no transcript, a track was left out, or something is stale, cut, split or unknown, 2 when it cannot run.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
TICKS_PER_SECOND = 254016000000
UNSUPPORTED_EFFECTS = ('timeremap', 'speed', 'reverse')
UNSUPPORTED_CONTENT = {'sequence': 'a nested sequence (its clips are not followed)',
                       'multiclip': 'a multicam clip (its angles are not followed)'}
ANYTHING = '*'


def load_sibling(name):
    """Load a script beside this one as a module."""
    spec = importlib.util.spec_from_file_location('lf_' + name, HERE / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


P = load_sibling('project')


def text(node, path, default=''):
    """Stripped text at a child path, or the default."""
    value = node.findtext(path) if node is not None else None
    return value.strip() if value else default


def enabled(node):
    """Whether a clip or track plays: <enabled> is absent or not FALSE."""
    return text(node, 'enabled', 'TRUE').upper() != 'FALSE'


def rate_parts(node):
    """An element's own <rate> as (timebase, ntsc), each None when absent; ValueError when either is malformed."""
    rate = node.find('rate') if node is not None else None
    if rate is None:
        return None, None
    base, ntsc = text(rate, 'timebase'), text(rate, 'ntsc').upper()
    if base and (not base.isdigit() or int(base) <= 0):
        raise ValueError(f'timebase {base!r} is not a positive whole number')
    if ntsc not in ('', 'TRUE', 'FALSE'):
        raise ValueError(f'ntsc {ntsc!r} is neither TRUE nor FALSE')
    return (int(base) if base else None), ({'TRUE': True, 'FALSE': False}.get(ntsc))


def exact_rate(base, ntsc):
    """The exact frame rate of a timebase: base x 1000/1001 when NTSC."""
    return Fraction(base * 1000, 1001) if ntsc else Fraction(base)


def resolve_rate(own, contexts):
    """An element's exact rate from its own (timebase, ntsc) and its context, enclosing element first. A missing
    timebase comes from the first context that has one; a missing ntsc flag from the contexts with the same timebase,
    which must agree; with none of those it is FALSE, unless the context is NTSC (then the rate is ambiguous).
    Returns (rate, None) or (None, why)."""
    base, ntsc = own
    if base is None:
        found = next(((b, n) for b, n in contexts if b is not None), None)
        if found is None:
            return None, 'no frame rate here or in its context'
        base, ntsc = found[0], found[1] if ntsc is None else ntsc
    if ntsc is None:
        flags = {n for b, n in contexts if b == base and n is not None}
        if len(flags) > 1:
            return None, f'timebase {base} has no ntsc flag and its sequence and file disagree on NTSC'
        if flags:
            ntsc = flags.pop()
        elif any(n for _, n in contexts):
            return None, f'timebase {base} has no ntsc flag inside NTSC material'
        else:
            ntsc = False
    return exact_rate(base, ntsc), None


def file_table(root, base=None):
    """Every <file> defined in the document: id -> path URL, name and own rate parts (later references carry only
    the id). A malformed file rate is kept as None, so it is never inherited."""
    files = {}
    for node in root.iter('file'):
        key = node.get('id')
        url = urllib.parse.unquote(text(node, 'pathurl'))
        if url and base is not None and not urllib.parse.urlsplit(url).scheme and not Path(url).is_absolute():
            url = str((Path(base) / url).resolve())
        if key and (url or key not in files):
            try:
                parts = rate_parts(node)
            except ValueError:
                parts = None
            files[key] = {'url': url, 'name': text(node, 'name'), 'rate_parts': parts}
    return files


def unsupported(clip):
    """What this reader does not interpret in a clip: nested sequences, multicam clips, and speed or time-remap effects
    (by effect id)."""
    found = [why for tag, why in UNSUPPORTED_CONTENT.items() if clip.find(tag) is not None]
    for effect in clip.iter('effect'):
        effect_id = text(effect, 'effectid').lower()
        if any(word in effect_id for word in UNSUPPORTED_EFFECTS):
            found.append(effect_id)
    return found


def transition_row(node, frame_ticks):
    """A transition's span and its cut frame (start plus cutPointTicks)."""
    start, end = int(text(node, 'start', '0')), int(text(node, 'end', '0'))
    cut_ticks = text(node, 'cutPointTicks')
    if cut_ticks:
        cut = start + round(int(cut_ticks) / frame_ticks)
    else:
        alignment = text(node, 'alignment', 'center')
        cut = start if alignment == 'start-black' or alignment == 'start' else end if alignment.startswith('end') \
            else start + (end - start) // 2
    return {'start': start, 'end': end, 'cut': cut,
            'effect': text(node, 'effect/effectid') or text(node, 'effect/name'), 'audio': 'unassessed'}


def other_tracks(tracks, chosen):
    """Audio tracks besides the one read: disabled ones, and enabled ones holding clips this run did not read (with
    the file ids of their enabled clips, so a comparison can tell which sources they may hold)."""
    disabled, unread = [], []
    for number, track in enumerate(tracks, 1):
        clips = [node for node in track if node.tag == 'clipitem']
        if number == chosen:
            continue
        if not enabled(track):
            disabled.append({'track': number, 'clips': len(clips)})
        elif clips:
            files = [node.find('file').get('id') if node.find('file') is not None else None
                     for node in clips if enabled(node)]
            unread.append({'track': number, 'clips': len(clips), 'files': files})
    return disabled, unread


def sequence_rate(sequence):
    """The sequence's exact rate and its (timebase, ntsc) for clips to inherit; ValueError when it has none."""
    base, ntsc = rate_parts(sequence)
    if base is None:
        raise ValueError('the sequence has no frame rate')
    return exact_rate(base, bool(ntsc)), (base, bool(ntsc))


def read_timeline(path, track_number=1):
    """The sequence's rate and duration, and one audio track as clips with their real cuts and handles."""
    root = ET.parse(path).getroot()
    sequence = root.find('.//sequence')
    if sequence is None:
        raise ValueError('no <sequence> in this file; is it Final Cut Pro 7 XML (xmeml)?')
    rate, parts = sequence_rate(sequence)
    frame_ticks = Fraction(TICKS_PER_SECOND) / rate
    tracks = sequence.findall('media/audio/track')
    if not 1 <= track_number <= len(tracks):
        raise ValueError(f'audio track {track_number} does not exist (the sequence has {len(tracks)})')
    track = tracks[track_number - 1]
    files = file_table(root, Path(path).resolve().parent)
    items = [node for node in track if node.tag in ('clipitem', 'transitionitem')]
    transitions = {index: transition_row(node, frame_ticks) for index, node in enumerate(items)
                   if node.tag == 'transitionitem'}
    context = {'transitions': transitions, 'files': files, 'rate': rate, 'sequence_parts': parts,
               'frame_ticks': frame_ticks, 'track_enabled': enabled(track), 'problems': [], 'skipped': []}
    clips = []
    for index, node in enumerate(items):
        if node.tag == 'clipitem':
            clips.append(clip_row(node, index, len(clips) + 1, context))
    disabled, unread = other_tracks(tracks, track_number)
    return {'file': str(path), 'rate': f'{rate.numerator}/{rate.denominator}', 'frame_ticks': str(frame_ticks),
            'duration_frames': int(text(sequence, 'duration', '0') or 0), 'track': track_number,
            'track_enabled': context['track_enabled'], 'clips': clips, 'transitions': list(transitions.values()),
            'not_mapped': context['problems'], 'skipped': context['skipped'],
            'other_tracks': {'audio': len(tracks), 'video': len(sequence.findall('media/video/track')),
                             'disabled_audio': disabled, 'enabled_audio_not_read': unread}}


def clip_rate(node, file_id, context):
    """The clip's exact rate by inheritance (its own, then its sequence and file): (rate, None) or (None, why)."""
    try:
        own = rate_parts(node)
    except ValueError as error:
        return None, str(error)
    contexts = [context['sequence_parts']]
    file_parts = (context['files'].get(file_id) or {}).get('rate_parts')
    if file_parts:
        contexts.append(file_parts)
    return resolve_rate(own, contexts)


def clip_row(node, index, number, context):
    """One clip with its nominal (cut-to-cut) placement and source range; handles reported apart. A clip that does
    not play (disabled, or on a disabled track) is skipped; one this reader cannot interpret is not mapped."""
    transitions, rate, frame_ticks = context['transitions'], context['rate'], context['frame_ticks']
    problems = context['problems']
    start, end = int(text(node, 'start', '0')), int(text(node, 'end', '0'))
    before, after = transitions.get(index - 1), transitions.get(index + 1)
    row = {'number': number, 'id': node.get('id'), 'enabled': enabled(node),
           'file': (node.find('file').get('id') if node.find('file') is not None else None)}
    if not context['track_enabled'] or not row['enabled']:
        why = 'the track is disabled' if not context['track_enabled'] else 'the clip is disabled'
        row.update({'mapped': False, 'skipped': why})
        context['skipped'].append({'clip': number, 'why': why})
        return row
    if start == -1:
        if before is None:
            problems.append({'clip': number, 'why': 'start is -1 with no transition before it'})
            row['mapped'] = False
            return row
        start, row['handle_before'] = before['cut'], before['cut'] - before['start']
    if end == -1:
        if after is None:
            problems.append({'clip': number, 'why': 'end is -1 with no transition after it'})
            row['mapped'] = False
            return row
        end, row['handle_after'] = after['cut'], after['end'] - after['cut']
    row.update({'start_frame': start, 'end_frame': end, 'start': float(start / rate), 'end': float(end / rate)})
    handle_before, handle_after = row.get('handle_before', 0), row.get('handle_after', 0)
    ticks_in, ticks_out = text(node, 'pproTicksIn'), text(node, 'pproTicksOut')
    if ticks_in and ticks_out:
        source_in = (Fraction(int(ticks_in)) + handle_before * frame_ticks) / TICKS_PER_SECOND
        source_out = (Fraction(int(ticks_out)) - handle_after * frame_ticks) / TICKS_PER_SECOND
    else:
        own_rate, why = clip_rate(node, row['file'], context)
        if own_rate is None:
            row['mapped'] = False
            problems.append({'clip': number, 'why': 'not mapped: frame rate: ' + why})
            return row
        # In and out count frames at the clip's rate; handles are sequence frames, so each converts at its own rate.
        source_in = Fraction(int(text(node, 'in', '0'))) / own_rate + handle_before / rate
        source_out = Fraction(int(text(node, 'out', '0'))) / own_rate - handle_after / rate
    effects = unsupported(node)
    if row['file'] is None and not effects:
        effects.append('no source file')
    row.update({'source_in': float(source_in), 'source_out': float(source_out),
                'handle_in': float(source_in - handle_before * frame_ticks / TICKS_PER_SECOND),
                'handle_out': float(source_out + handle_after * frame_ticks / TICKS_PER_SECOND),
                'mapped': not effects})
    duration = (end - start) / rate
    if abs(float(source_out - source_in) - float(duration)) > 1.5 / float(rate) and not effects:
        effects.append('source and timeline durations differ (a speed change?)')
    if effects:
        row['mapped'] = False
        problems.append({'clip': number, 'why': 'not mapped: ' + ', '.join(effects)})
    return row


def path_parts(name):
    """A file reference (URL, Windows or POSIX path, or bare name) as case-folded path parts, file name last."""
    value = urllib.parse.unquote(str(name or '')).replace('\\', '/')
    for prefix in ('file://localhost', 'file://'):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
    return tuple(part.casefold() for part in PurePosixPath(value).parts if part not in ('/', ''))


def display_name(reference):
    """A file reference's own file name, in the case the editor sees it."""
    return PurePosixPath(urllib.parse.unquote(str(reference or '')).replace('\\', '/')).name


def file_key(name):
    """A comparable file name: the last path part, case-folded."""
    parts = path_parts(name)
    return parts[-1] if parts else ''


def word_identity(source, word):
    """A collision-free, readable source-scoped word key, including a reserved form for words without IDs."""
    alias = urllib.parse.quote(str(source), safe='')
    local = word.get('id')
    part = urllib.parse.quote(str(local), safe='') if local is not None else f"!row-{word['row']}"
    return alias + ':' + part


def transcript_words(group, path):
    """A transcript's non-empty words, in source seconds."""
    words = []
    ids = set()
    for number, word in enumerate(group.get('words', []), 1):
        local = word.get('id')
        if local is not None:
            local = str(local)
            if local in ids:
                raise ValueError(f'{path}: repeated transcript word ID {local!r}')
            ids.add(local)
        token = str(word.get('text', word.get('word', ''))).strip()
        if token and float(word['end']) >= float(word['start']):
            words.append({'id': local, 'row': number, 'text': token, 'start': float(word['start']),
                          'end': float(word['end']), 'estimated': bool(word.get('estimated'))})
    return words


def load_words(paths):
    """Word-timed transcripts in the order given: [{'source', 'reference', 'sha256', 'words', 'from'}]. A transcript
    with no media reference (transcribe.py's words.json) is matched through the project map or --map."""
    transcripts = []
    for path in paths:
        data = P.load_json(path, None)
        if isinstance(data, list):
            data = {'words': data}
        if not isinstance(data, dict):
            raise ValueError(f'{path}: expected a JSON object or a list of words')
        groups = data['sources'] if 'sources' in data else [data]
        for group in groups:
            reference = group.get('media_reference') or group.get('path') or group.get('file') or ''
            source = group.get('id') or group.get('source') or (Path(reference).stem if reference else Path(path).stem)
            media = P.transcript_media(group)
            transcripts.append({'source': str(source), 'reference': reference,
                                'sha256': group.get('sha256') or (media or {}).get('sha256'),
                                'media': media, 'words': transcript_words(group, path), 'from': str(path)})
    return transcripts


def project_sources(project):
    """The project's sources by alias, with current file hashes and paths resolved against the project folder."""
    root = Path(project)
    index = P.load_json(root / 'map' / 'sources.json', None)
    if not isinstance(index, dict):
        raise ValueError(f'no map/sources.json in {root}; is it a project folder?')
    sources = {}
    for source in index.get('sources', []):
        path = Path(str(source.get('path', '')))
        path = path if path.is_absolute() else root / path
        alias = source['alias']
        if alias in sources:
            raise ValueError(f'{root / "map" / "sources.json"}: repeated source alias {alias!r}')
        current = dict(source, path=str(path))
        if path.is_file():
            current['sha256'] = sha256_of(path) or source.get('sha256')
        sources[alias] = current
    return sources


def gather_transcripts(word_paths, project=None):
    """Transcripts from explicit files or the project map; reject ambiguous aliases and retain media provenance."""
    found = {}
    sources = project_sources(project) if project else {}
    if project and not word_paths:
        word_paths = [Path(project) / 'map' / alias / 'words.json' for alias in sources
                      if (Path(project) / 'map' / alias / 'words.json').is_file()]
    for transcript in load_words(word_paths):
        alias = transcript['source']
        if alias in found:
            raise ValueError(f"{transcript['from']}: source alias {alias!r} already occurs in {found[alias]['from']}")
        source = sources.get(transcript['source'])
        if source:
            if not transcript['reference']:
                transcript['reference'] = source['path']
            transcript['sha256'] = source.get('sha256')
            transcript['state'], transcript['reason'] = P.transcript_state(source, {'media': transcript['media']})
            if transcript['state'] == 'current' and ((transcript['media'] or {}).get('audio_stream') is None
                                                      or (source.get('audio') or {}).get('index') is None):
                transcript['state'] = 'stale'
                transcript['reason'] = 'the transcript or source does not record its sound stream'
        else:
            transcript['state'] = 'bound' if transcript['media'] else 'unbound'
            if transcript['media'] and transcript['media'].get('audio_stream') is None:
                transcript['state'] = 'stale'
                transcript['reason'] = 'the transcript does not record its sound stream'
        found[alias] = transcript
    return list(found.values())


def parse_mapping(pairs):
    """--map FILE=ALIAS pairs as [(path parts, alias)]."""
    mapping = []
    for pair in pairs or []:
        name, separator, alias = pair.rpartition('=')
        if not separator or not name.strip() or not alias.strip():
            raise ValueError(f'--map takes FILE=ALIAS (the file name in the timeline, then a transcript alias): {pair}')
        mapping.append((path_parts(name.strip()), alias.strip()))
    return mapping


def local_path(url):
    """The file a timeline's (already unquoted) path URL names on this machine, or None."""
    value = url or ''
    for prefix in ('file://localhost', 'file://'):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    if re.match(r'/[A-Za-z]:', value):
        value = value[1:]
    return Path(value) if value else None


def sha256_of(path):
    """The SHA-256 of a local file, or None when it cannot be read."""
    digest = hashlib.sha256()
    try:
        with open(path, 'rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()


def content_digest(url, transcripts, digests):
    """The SHA-256 of the timeline's file when it can be read here and some transcript has a hash to compare with
    (computed once per file), else None."""
    local = local_path(url)
    if local is None or not any(t.get('sha256') for t in transcripts):
        return None
    key = str(local)
    if key not in digests:
        digests[key] = sha256_of(local) if local.is_file() else None
    return digests[key]


def by_content(digest, named, transcripts, name):
    """The transcript a readable file's content picks: (transcript, how, None), (None, None, why) or None when no
    transcript has a hash to compare with."""
    same = [t for t in transcripts if t.get('sha256') == digest]
    named_ids = {id(t) for t in named}
    preferred = [t for t in same if id(t) in named_ids] or same
    if len(preferred) == 1:
        renamed = '' if id(preferred[0]) in named_ids else ' under another name'
        return preferred[0], f'content (SHA-256 matches the source{renamed})', None
    if len(preferred) > 1:
        aliases = ', '.join(t['source'] for t in preferred)
        return None, None, f'ambiguous: sources {aliases} have this exact content; give --map {name}=ALIAS'
    hashed = [t for t in named if t.get('sha256')]
    if hashed:
        aliases = ', '.join(t['source'] for t in hashed)
        return None, None, (f'content differs: {name} here is not the file of {aliases} (SHA-256 differs); if it is a '
                            f'proxy or copy of the same recording, give --map {name}=ALIAS')
    return None


def choose_transcript(reference, url, transcripts, mapping, digests=None):
    """The transcript for one timeline file: (transcript, how it was matched, None) or (None, None, the reason none
    was chosen). A readable file is matched by content; an unreadable one by a file name only one transcript has."""
    parts = path_parts(reference)
    name = display_name(reference)
    by_alias = {transcript['source']: transcript for transcript in transcripts}
    for wanted, alias in mapping:
        if wanted and parts[-len(wanted):] == wanted:
            if alias in by_alias:
                return by_alias[alias], '--map', None
            return None, None, f'--map names {alias}, but no transcript has that alias'
    named = [t for t in transcripts if t['reference'] and file_key(t['reference']) == (parts[-1] if parts else '')]
    digest = content_digest(url, transcripts, {} if digests is None else digests)
    if digest:
        decided = by_content(digest, named, transcripts, name)
        if decided:
            return decided
    if len(named) == 1:
        if digest:
            how = 'file name (no hash to compare with)'
        elif named[0].get('sha256'):
            how = 'file name, not verified (the file cannot be read here)'
        else:
            how = 'file name'
        return named[0], how, None
    if len(named) > 1:
        aliases = ', '.join(t['source'] for t in named)
        return None, None, (f'ambiguous: {len(named)} transcripts are for files named {name} ({aliases}) and the file '
                            f'cannot be read here to compare content; give --map {name}=ALIAS')
    loose = [t['source'] for t in transcripts if not t['reference']]
    hint = (f'; transcripts with no media reference: {", ".join(loose)} (give --project or --map FILE=ALIAS)'
            if loose else '')
    return None, None, 'no transcript for this file' + hint


def stale_reason(transcript, reason):
    """Explain why words cannot be mapped and both deliberate remedies."""
    alias = transcript['source']
    return (f'stale transcript for {alias}: {reason}; use map.py run PROJECT --alias {alias} '
            f'--retranscribe {alias}, or check it and use map.py confirm-words PROJECT {alias} --note TEXT')


def pick_transcript(reference, url, transcripts, mapping, digests=None):
    """Resolve a clip, then enforce its transcript's recorded provenance and disclose unbound words."""
    digests = {} if digests is None else digests
    chosen, how, why = choose_transcript(reference, url, transcripts, mapping, digests)
    digest = content_digest(url, transcripts, digests)
    if chosen:
        if chosen.get('state') == 'stale':
            return None, None, stale_reason(chosen, chosen.get('reason', 'source media changed'))
        media = chosen.get('media')
        if media and digest and digest != media['sha256']:
            return None, None, stale_reason(chosen, 'the clip file differs from the transcript media')
        if chosen.get('state') == 'unbound':
            how += '; the transcript does not record the media it was made from'
        confirmation = (media or {}).get('confirmation')
        if isinstance(confirmation, dict):
            actor = confirmation.get('by') if confirmation.get('by') in ('person', 'agent') else 'unspecified'
            if how.startswith('content ('):
                how = f'confirmed media binding by {actor} (source file SHA-256 verified)'
            else:
                how += f'; transcript media binding confirmed by {actor}'
        return chosen, how, why
    named = [item for item in transcripts if item['reference'] and file_key(item['reference']) == file_key(reference)]
    if len(named) == 1:
        candidate = named[0]
        if candidate.get('state') == 'stale':
            return None, None, stale_reason(candidate, candidate.get('reason', 'source media changed'))
        if candidate.get('media') and digest and candidate['media']['sha256'] != digest:
            return None, None, stale_reason(candidate, 'the clip file differs from the transcript media')
    return None, how, why


def possible_sources(reference, url, transcripts, mapping, digests):
    """The source aliases a file might hold words of: the matched one; when the match failed, every transcript with
    its file name or its content, and every transcript with no media reference; ANYTHING when there is no file."""
    if not reference:
        return {ANYTHING}
    transcript, _, _ = pick_transcript(reference, url, transcripts, mapping, digests)
    if transcript:
        return {transcript['source']}
    name = file_key(reference)
    digest = content_digest(url, transcripts, digests)
    parts = path_parts(reference)
    aliases = {alias for wanted, alias in mapping or [] if wanted and parts[-len(wanted):] == wanted}
    return aliases | {t['source'] for t in transcripts if not t['reference'] or file_key(t['reference']) == name
                      or (digest and t.get('sha256') == digest)}


def resolve_clips(timeline, transcripts, mapping=None, matches=None, digests=None):
    """Each mapped clip's transcript: ({clip number: transcript}, [{clip, file, why}] for clips without one). With a
    `matches` list, each matched file is added once as {file, source, by, clips}."""
    files = file_table(ET.parse(timeline['file']).getroot(), Path(timeline['file']).resolve().parent)
    digests = {} if digests is None else digests
    chosen, unmatched, decided, matched = {}, [], {}, {}
    for clip in timeline['clips']:
        if not clip.get('mapped'):
            continue
        entry = files.get(clip['file']) or {}
        reference = entry.get('url') or entry.get('name') or ''
        if reference not in decided:
            decided[reference] = pick_transcript(reference, entry.get('url') or '', transcripts, mapping or [],
                                                 digests)
        transcript, how, why = decided[reference]
        if transcript:
            chosen[clip['number']] = transcript
            row = matched.setdefault(reference, {'file': display_name(reference), 'source': transcript['source'],
                                                 'by': how, 'clips': []})
            row['clips'].append(clip['number'])
        else:
            unmatched.append({'clip': clip['number'], 'file': display_name(reference) or None, 'why': why})
    if matches is not None:
        matches.extend(matched.values())
    return chosen, unmatched


def place_words(timeline, transcripts, chosen=None):
    """Every word of every mapped clip at its edit time, with the part of its source interval the clip keeps; words
    only in handles get a state and no time. Without `chosen` (from resolve_clips), transcripts are matched here."""
    if chosen is None:
        chosen, _ = resolve_clips(timeline, transcripts)
    occurrences, states = [], {}
    rate = Fraction(timeline['rate'])
    transitions = [{'start': float(item['start'] / rate), 'end': float(item['end'] / rate),
                    'effect': item['effect'], 'audio': item['audio']} for item in timeline['transitions']]
    for clip in timeline['clips']:
        transcript = chosen.get(clip['number']) if clip.get('mapped') else None
        if not transcript:
            continue
        for word in transcript['words']:
            key = word_identity(transcript['source'], word)
            if word['end'] <= clip['handle_in'] or word['start'] >= clip['handle_out']:
                continue
            if word['end'] <= clip['source_in'] or word['start'] >= clip['source_out']:
                states.setdefault(key, 'handle_only')
                continue
            left, right = max(word['start'], clip['source_in']), min(word['end'], clip['source_out'])
            split = left > word['start'] or right < word['end']
            start = clip['start'] + (left - clip['source_in'])
            end = clip['start'] + (right - clip['source_in'])
            overlap = [item for item in transitions if start < item['end'] and end > item['start']]
            occurrences.append({'id': f"c{clip['number']:03d}:{key}", 'word': key, 'word_id': word['id'],
                                'text': word['text'],
                                'clip': clip['number'], 'source': transcript['source'],
                                'start': start, 'end': end, 'transitions': overlap,
                                'source_start': left, 'source_end': right,
                                'split': split, 'estimated': word['estimated'] or split or bool(overlap)})
            states[key] = 'used'
    occurrences.sort(key=lambda row: (row['start'], row['end']))
    return occurrences, states


def edit_words(occurrences):
    """Placed words in the shared edit-time word schema: id (the transcript word's ID), text, start and end (edit
    seconds), estimated, source (alias), plus the clip, whether a clip edge split the word, the part of the source
    interval placed (source_start, source_end) and the occurrence ID (unique when the edit uses a word twice)."""
    result = []
    for row in occurrences:
        item = {'id': row['word_id'], 'identity': row['word'], 'text': row['text'],
                'start': round(row['start'], 6), 'end': round(row['end'], 6),
                'estimated': row['estimated'], 'source': row['source'], 'clip': row['clip'], 'split': row['split'],
                'source_start': round(row['source_start'], 6), 'source_end': round(row['source_end'], 6),
                'occurrence': row['id']}
        if row['transitions']:
            item['transitions'] = row['transitions']
        result.append(item)
    return result


def interval_cover(rows):
    """{word ID: seconds of its source interval the edit keeps}, the union of its placed parts."""
    parts = {}
    for row in rows:
        parts.setdefault(row['word'], []).append((row['source_start'], row['source_end']))
    covered = {}
    for word, spans in parts.items():
        total, reach = 0.0, None
        for left, right in sorted(spans):
            if reach is None or left >= reach:
                total += right - left
                reach = right
            elif right > reach:
                total += right - reach
                reach = right
        covered[word] = total
    return covered


def word_uses(rows):
    """{word ID: [use]} in edit order, each use {'start', 'end', 'source_end'} in edit seconds. Parts of one word that
    adjacent clips place end to end, each continuing forward in the source (whole, or with a piece cut out), are one
    use; a part that starts the word again is another use."""
    uses = {}
    for row in sorted(rows, key=lambda item: (item['start'], item['end'])):
        spans = uses.setdefault(row['word'], [])
        last = spans[-1] if spans else None
        if last and abs(row['start'] - last['end']) < 1e-6 and row['source_start'] >= last['source_end'] - 1e-6:
            last['end'], last['source_end'] = row['end'], row['source_end']
        else:
            spans.append({'start': row['start'], 'end': row['end'], 'source_end': row['source_end']})
    return uses


def use_index(uses, row):
    """Which of its word's uses a placed row belongs to."""
    return next(number for number, use in enumerate(uses[row['word']])
                if use['start'] - 1e-6 <= row['start'] <= use['end'] + 1e-6)


def follow_captions(captions_path, before, after, unknown=frozenset(), split=frozenset()):
    """Each caption of BEFORE, followed through its words into AFTER. Each use of a word in BEFORE is matched to
    one use in AFTER: in order when the word is used as many times in both, otherwise not at all. A caption whose
    words may be in material the comparison could not map, whose word is used a different number of times in the
    two edits (which use was cut cannot be told from word IDs), or whose text is not found among BEFORE's words is
    unknown, with the reason; one with a word the edit cut into is split."""
    captions = load_sibling('captions')
    cues = captions.read_input(captions_path)
    words = [{'text': row['text'], 'start': row['start'], 'end': row['end'], 'word': row['word']} for row in before]
    _, _, regions = captions.check_word_timing(cues, words, 0.5)
    uses_before, uses_after = word_uses(before), word_uses(after)
    results = []
    for number, (cue, region) in enumerate(zip(cues, regions), 1):
        if region is None:
            results.append({'caption': number, 'status': 'unknown', 'start': cue['start'],
                            'why': "not matched in BEFORE: its text was not found among BEFORE's words"})
            continue
        used = [row for row in before if row['start'] < region[1] and row['end'] > region[0]]
        kept = [row for row in used if row['word'] in uses_after]
        cut = [row['text'] for row in used if row['word'] not in uses_after]
        doubtful = [row['text'] for row in used if row['word'] in unknown]
        parted = [row['text'] for row in used if row['word'] in split]
        repeated = [row for row in kept if len(uses_before[row['word']]) != len(uses_after[row['word']])]
        if doubtful:
            results.append({'caption': number, 'status': 'unknown', 'start': cue['start'], 'unknown_words': doubtful,
                            'why': 'its words may be in material this comparison could not map or did not read'})
            continue
        if repeated:
            counts = ', '.join(f'"{row["text"]}" {len(uses_before[row["word"]])} -> {len(uses_after[row["word"]])}'
                               for row in repeated)
            results.append({'caption': number, 'status': 'unknown', 'start': cue['start'],
                            'unknown_words': [row['text'] for row in repeated],
                            'why': f'a word is used a different number of times in BEFORE and AFTER ({counts}); '
                                   'which use the edit removed or added cannot be told from word IDs'})
            continue
        if not kept:
            results.append({'caption': number, 'status': 'removed', 'start': cue['start'], 'cut_words': cut})
            continue
        new_start = min(uses_after[row['word']][use_index(uses_before, row)]['start'] for row in kept)
        status = 'stale' if cut else 'split' if parted else ('moved' if abs(new_start - region[0]) > 0.04
                                                             else 'unchanged')
        result = {'caption': number, 'status': status, 'start': cue['start'], 'cut_words': cut,
                  'shift_s': round(new_start - region[0], 3)}
        if parted:
            result['split_words'] = parted
        results.append(result)
    return results


def duration_s(timeline):
    """A sequence's duration in seconds at its own frame rate."""
    return timeline['duration_frames'] / Fraction(timeline['rate'])


def uncertain_sources(timeline, unmatched, transcripts, mapping, digests):
    """Sources whose words material outside this comparison might hold: clips not mapped, clips with an uncertain
    transcript, and enabled audio tracks not read (ANYTHING when a clip has no file to judge)."""
    files = file_table(ET.parse(timeline['file']).getroot())
    unmatched_clips = {row['clip'] for row in unmatched}
    ids = [clip['file'] for clip in timeline['clips']
           if not clip.get('skipped') and (not clip.get('mapped') or clip['number'] in unmatched_clips)]
    for track in timeline['other_tracks']['enabled_audio_not_read']:
        ids.extend(track.get('files', []))
    sources = set()
    for file_id in ids:
        entry = files.get(file_id) or {}
        reference = entry.get('url') or entry.get('name') or ''
        sources |= possible_sources(reference, entry.get('url') or '', transcripts, mapping, digests)
    return sources


def coverage_of(timeline, unmatched):
    """What one side of a comparison read and left out."""
    return {'track': timeline['track'], 'track_enabled': timeline['track_enabled'],
            'clips': len(timeline['clips']), 'mapped': sum(1 for clip in timeline['clips'] if clip.get('mapped')),
            'skipped': timeline['skipped'], 'not_mapped': timeline['not_mapped'], 'unmatched': unmatched,
            'disabled_audio': timeline['other_tracks']['disabled_audio'],
            'enabled_audio_not_read': [{'track': row['track'], 'clips': row['clips']}
                                       for row in timeline['other_tracks']['enabled_audio_not_read']]}


def incomplete_reasons(label, coverage):
    """Why one side of a comparison is incomplete, in words."""
    reasons = []
    if not coverage['track_enabled']:
        reasons.append(f"{label}: audio track {coverage['track']} is disabled, so nothing on it was compared")
    if coverage['not_mapped']:
        reasons.append(f"{label}: {len(coverage['not_mapped'])} clip(s) not mapped")
    if coverage['unmatched']:
        reasons.append(f"{label}: {len(coverage['unmatched'])} clip(s) with no transcript")
    if coverage['enabled_audio_not_read']:
        tracks = ', '.join(f"{row['track']} ({row['clips']} clips)" for row in coverage['enabled_audio_not_read'])
        reasons.append(f'{label}: enabled audio tracks not read: {tracks}')
    return reasons


def stale_unplaced_words(timeline, unmatched, transcripts, mapping, digests):
    """Words in stale transcript ranges are unknown even when neither edit can place them."""
    files = file_table(ET.parse(timeline['file']).getroot())
    clips = {clip['number']: clip for clip in timeline['clips']}
    unknown = set()
    for item in unmatched:
        if 'stale transcript' not in item.get('why', '').lower():
            continue
        clip = clips[item['clip']]
        entry = files.get(clip['file']) or {}
        reference = entry.get('url') or entry.get('name') or ''
        possible = possible_sources(reference, entry.get('url') or '', transcripts, mapping, digests)
        for transcript in transcripts:
            if transcript['source'] not in possible and ANYTHING not in possible:
                continue
            for word in transcript['words']:
                if word['start'] < clip['source_out'] and word['end'] > clip['source_in']:
                    unknown.add(word_identity(transcript['source'], word))
    return unknown


def compare(before_path, after_path, word_paths, track, captions_path=None, project=None, mapping=None):
    """Words used in BEFORE and cut in AFTER, restored, partly cut or unknown; each side's coverage and whether the
    comparison is complete; and (with captions) each caption's fate."""
    transcripts = gather_transcripts(word_paths, project)
    before, after = read_timeline(before_path, track), read_timeline(after_path, track)
    digests = {}
    chosen_before, unmatched_before = resolve_clips(before, transcripts, mapping, digests=digests)
    chosen_after, unmatched_after = resolve_clips(after, transcripts, mapping, digests=digests)
    first, _ = place_words(before, transcripts, chosen_before)
    second, _ = place_words(after, transcripts, chosen_after)
    source_of = {row['word']: row['source'] for row in first + second}
    unsure_after = uncertain_sources(after, unmatched_after, transcripts, mapping, digests)
    unsure_before = uncertain_sources(before, unmatched_before, transcripts, mapping, digests)
    used_before, used_after = {row['word'] for row in first}, {row['word'] for row in second}
    unknown = {word for word in used_before - used_after
               if ANYTHING in unsure_after or source_of[word] in unsure_after}
    unknown |= {word for word in used_after - used_before
                if ANYTHING in unsure_before or source_of[word] in unsure_before}
    cover_before, cover_after = interval_cover(first), interval_cover(second)
    tolerance = float(1 / Fraction(after['rate']))
    split = {word for word in used_before & used_after if cover_before[word] - cover_after[word] > tolerance}
    unknown |= {word for word in split if ANYTHING in unsure_after or source_of[word] in unsure_after}
    split -= unknown
    unknown |= stale_unplaced_words(before, unmatched_before, transcripts, mapping, digests)
    unknown |= stale_unplaced_words(after, unmatched_after, transcripts, mapping, digests)
    uses_before, uses_after = word_uses(first), word_uses(second)
    uses_changed = [{'word': word, 'before': len(uses_before[word]), 'after': len(uses_after[word])}
                    for word in sorted(used_before & used_after - unknown)
                    if len(uses_before[word]) != len(uses_after[word])]
    coverage = {'before': coverage_of(before, unmatched_before), 'after': coverage_of(after, unmatched_after)}
    reasons = incomplete_reasons('BEFORE', coverage['before']) + incomplete_reasons('AFTER', coverage['after'])
    report = {'before': str(before_path), 'after': str(after_path),
              'duration_change_s': round(float(duration_s(after) - duration_s(before)), 3),
              'words_cut': sorted(used_before - used_after - unknown),
              'words_added': sorted(used_after - used_before - unknown), 'words_split': sorted(split),
              'words_unknown': sorted(unknown), 'words_uses_changed': uses_changed,
              'words_before': edit_words(first), 'words_after': edit_words(second),
              'complete': not reasons, 'incomplete': reasons,
              'coverage': coverage, 'not_mapped': {'before': before['not_mapped'], 'after': after['not_mapped']},
              'unmatched': {'before': unmatched_before, 'after': unmatched_after},
              'skipped': {'before': before['skipped'], 'after': after['skipped']}}
    if captions_path:
        report['captions'] = follow_captions(captions_path, first, second, unknown, split)
    return report


def describe_tracks(timeline, label=''):
    """Lines about the track read and the others: disabled, or enabled with clips this run did not read."""
    lines = []
    prefix = label + ' ' if label else ''
    if not timeline['track_enabled']:
        lines.append(f"{prefix}audio track {timeline['track']} is disabled in the timeline: its clips do not play and "
                     'were skipped')
    others = timeline['other_tracks']
    disabled = [row for row in others['disabled_audio'] if row['clips']]
    if disabled:
        lines.append(prefix + 'disabled audio tracks skipped: ' + ', '.join(f"{row['track']} ({row['clips']} clips)"
                                                                            for row in disabled))
    if others['enabled_audio_not_read']:
        lines.append(prefix + 'enabled audio tracks not read (use --track N): '
                     + ', '.join(f"{row['track']} ({row['clips']} clips)" for row in others['enabled_audio_not_read']))
    return lines


def problem_lines(label, rows, limit=8):
    """Up to `limit` clip problems, one per line."""
    lines = [f"  {label} clip {row['clip']}: {row['why']}" for row in rows[:limit]]
    if len(rows) > limit:
        lines.append(f'  ... and {len(rows) - limit} more (see --json)')
    return lines


def run_read(args):
    """The read command: (result, flagged)."""
    result = read_timeline(args.timeline, args.track)
    mapped = sum(1 for clip in result['clips'] if clip.get('mapped'))
    print(f"{result['rate']} fps, {result['duration_frames']} frames; audio track {args.track}: "
          f"{len(result['clips'])} clips ({mapped} mapped, {len(result['skipped'])} skipped, "
          f"{len(result['not_mapped'])} not mapped), {len(result['transitions'])} transitions")
    for line in describe_tracks(result) + problem_lines('not mapped:', result['not_mapped']):
        print(line)
    return result, bool(result['not_mapped']) or not result['track_enabled']


def run_words(args, mapping):
    """The words command: (result, flagged)."""
    timeline = read_timeline(args.timeline, args.track)
    transcripts = gather_transcripts(args.words, args.project)
    matches = []
    chosen, unmatched = resolve_clips(timeline, transcripts, mapping, matches)
    occurrences, states = place_words(timeline, transcripts, chosen)
    result = {'version': 1, 'timeline': str(args.timeline), 'words': edit_words(occurrences), 'states': states,
              'matches': matches, 'unmatched': unmatched, 'not_mapped': timeline['not_mapped'],
              'skipped': timeline['skipped'], 'coverage': coverage_of(timeline, unmatched),
              'transcripts': [{'source': t['source'], 'from': t['from']} for t in transcripts]}
    handle_only = sum(1 for state in states.values() if state == 'handle_only')
    split = sum(1 for row in occurrences if row['split'])
    print(f'{len(occurrences)} words placed ({split} split at a clip edge); {handle_only} words only in transition '
          f"handles; {len(unmatched)} clip(s) with no transcript; {len(timeline['not_mapped'])} not mapped; "
          f"{len(timeline['skipped'])} skipped")
    for row in matches:
        if row['by'] != 'file name' and not row['by'].startswith('content'):
            print(f"  {row['file']} -> {row['source']} by {row['by']}")
    for line in describe_tracks(timeline) + problem_lines('no transcript for', unmatched) \
            + problem_lines('not mapped:', timeline['not_mapped']):
        print(line)
    return result, bool(unmatched or timeline['not_mapped']) or not timeline['track_enabled']


def sample(words, limit=6):
    """A few word IDs for the console, with a count of the rest."""
    more = f' and {len(words) - limit} more' if len(words) > limit else ''
    return ', '.join(words[:limit]) + more


def run_compare(args, mapping):
    """The compare command: (result, flagged)."""
    result = compare(args.before, args.after, args.words, args.track, args.captions, args.project, mapping)
    print(f"{len(result['words_cut'])} words cut, {len(result['words_added'])} added, {len(result['words_split'])} "
          f"partly cut, {len(result['words_unknown'])} unknown; duration change {result['duration_change_s']} s")
    for side in ('before', 'after'):
        for line in describe_tracks(read_side(result, side), side.upper()) \
                + problem_lines(side.upper() + ' not mapped:', result['not_mapped'][side]) \
                + problem_lines(side.upper() + ' no transcript for', result['unmatched'][side]):
            print(line)
    if result['words_unknown']:
        print('unknown, not called cut (material this comparison could not map or did not read may hold them): '
              + sample(result['words_unknown']))
    if result['words_split']:
        print('partly cut (an edit cut into the word): ' + sample(result['words_split']))
    if result['words_uses_changed']:
        print('used a different number of times (a repeated use was removed or added): '
              + sample([f"{row['word']} {row['before']} -> {row['after']}" for row in result['words_uses_changed']]))
    flagged = bool(result['words_cut'] or result['words_unknown'] or result['words_split']
                   or result['words_uses_changed'] or not result['complete'])
    if 'captions' in result:
        counts = {}
        for row in result['captions']:
            counts[row['status']] = counts.get(row['status'], 0) + 1
        print('captions: ' + ', '.join(f'{count} {status}' for status, count in sorted(counts.items())))
        unknown = [row for row in result['captions'] if row['status'] == 'unknown']
        for row in unknown[:8]:
            print(f"  caption {row['caption']} unknown: {row['why']}")
        if len(unknown) > 8:
            print(f'  ... and {len(unknown) - 8} more unknown (see --json)')
        flagged = flagged or any(counts.get(status) for status in ('stale', 'removed', 'split', 'unknown'))
    if not result['complete']:
        print('comparison incomplete: ' + '; '.join(result['incomplete']))
    return result, flagged


def read_side(result, side):
    """One side's coverage in the shape describe_tracks reads."""
    coverage = result['coverage'][side]
    return {'track': coverage['track'], 'track_enabled': coverage['track_enabled'],
            'other_tracks': {'disabled_audio': coverage['disabled_audio'],
                             'enabled_audio_not_read': coverage['enabled_audio_not_read']}}


# ------------------------------------------------------------------------------------------- timeline hand-off


def xmeml_rate(value):
    """Return an exactly representable FCP 7 timebase and NTSC flag."""
    rate = Fraction(str(value))
    if rate <= 0:
        raise ValueError('frame rate must be positive')
    if rate.denominator == 1:
        return int(rate), False
    nominal = rate * Fraction(1001, 1000)
    if nominal.denominator == 1:
        return int(nominal), True
    raise ValueError(f'frame rate {rate} cannot be represented exactly in Final Cut Pro 7 XML')


def xml_text(parent, tag, value):
    """Append a text element and return it."""
    node = ET.SubElement(parent, tag)
    node.text = str(value)
    return node


def xml_rate(parent, rate):
    """Append an exact FCP 7 rate."""
    base, ntsc = xmeml_rate(rate)
    node = ET.SubElement(parent, 'rate')
    xml_text(node, 'timebase', base)
    xml_text(node, 'ntsc', 'TRUE' if ntsc else 'FALSE')


def frame_at(seconds, rate):
    """Round a time to the nearest frame on a specified clock."""
    return math.floor(Fraction(str(seconds)) * rate + Fraction(1, 2))


def media_url(path, output_dir, relative):
    """Encode an absolute local file URL, or a path relative to the XML folder."""
    path = Path(path).resolve()
    if relative:
        try:
            value = os.path.relpath(path, output_dir).replace('\\', '/')
        except ValueError as error:
            raise ValueError(f'cannot make {path} relative to the XML: {error}') from error
        return urllib.parse.quote(value, safe='/')
    return localhost_file_url(path.as_uri())


def localhost_file_url(value):
    """Use the localhost authority for an absolute file URI on Windows or POSIX."""
    if value.startswith('file:///'):
        value = 'file://localhost/' + value[len('file:///'):]
    return value


def probe_media(path):
    """Read local source stream facts without decoding media."""
    command = ['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise ValueError(f'ffprobe could not read {path}: {result.stderr.strip()}')
    return json.loads(result.stdout)


def export_sources(root, version_dir, edit, manifest, sequence_rate, notes, verify):
    """Resolve original mapped sources, plus the version's own rendered graphics and generated plates."""
    index = P.load_json(root / 'map' / 'sources.json', {})
    if not isinstance(index, dict) or not isinstance(index.get('sources'), list):
        raise ValueError('map/sources.json is missing or malformed')
    mapped = {row['alias']: row for row in index['sources']}
    recorded = manifest.get('sources')
    if not isinstance(recorded, dict):
        recorded = {}
        notes.append('The version has no render-time source identity records; its sources could not be verified.')
    elif not verify:
        notes.append('Source SHA-256 was not checked; use --verify to detect same-size changes.')
    sources = {}
    for number, (key, value) in enumerate(edit.get('sources', {}).items(), 1):
        file = Path(str(value.get('file', '')))
        file = file if file.is_absolute() else version_dir / file
        file = file.resolve()
        original = mapped.get(key)
        if key.startswith('gen-still-') and key[len('gen-still-'):] in mapped:
            original = mapped[key[len('gen-still-'):]]
            file = Path(original['path'])
            file = (file if file.is_absolute() else root / file).resolve()
        elif original:
            registered = Path(original['path'])
            registered = (registered if registered.is_absolute() else root / registered).resolve()
            if not P.same_file(file, registered):
                raise ValueError(f'{key}: the version does not refer to its registered original source: {file}')
        if not file.is_file():
            raise ValueError(f'{key}: source is missing: {file}')
        alias = original.get('alias') if original else None
        identity = recorded.get(alias) if alias else None
        if original and not isinstance(identity, dict):
            notes.append(f'{alias}: no render-time source identity is recorded; the source could not be verified.')
        elif isinstance(identity, dict):
            if identity.get('bytes') is None:
                notes.append(f'{alias}: the render-time source size is missing; the source could not be size-verified.')
            elif file.stat().st_size != identity['bytes']:
                raise ValueError(f'{alias}: source size differs from the version manifest: {file}')
            if verify:
                if not identity.get('sha256'):
                    notes.append(f'{alias}: no render-time SHA-256 is recorded; the source could not be hash-verified.')
                elif P.file_sha256(file) != identity['sha256']:
                    raise ValueError(f'{alias}: source SHA-256 differs from the version manifest: {file}')
        facts = probe_media(file)
        streams = facts.get('streams', [])
        video = next((row for row in streams if row.get('codec_type') == 'video'), {})
        audio = next((row for row in streams if row.get('codec_type') == 'audio'), {})
        metadata = original or {}
        rate_text = ((metadata.get('video') or {}).get('fps') or video.get('avg_frame_rate')
                     or video.get('r_frame_rate') or str(sequence_rate))
        try:
            rate = Fraction(str(rate_text))
            xmeml_rate(rate)
        except (ValueError, ZeroDivisionError):
            rate = sequence_rate
            notes.append(f'{key}: source frame rate {rate_text} cannot be represented; sequence rate used.')
        if rate != sequence_rate:
            notes.append(f'{key}: mixed-rate editor conform is not verified; timeline positions use the sequence grid, '
                         'and the file records the original frame rate.')
        average, nominal = video.get('avg_frame_rate'), video.get('r_frame_rate')
        if average and nominal and average != nominal:
            notes.append(f"{key}: variable frame rate (average {video['avg_frame_rate']}, nominal "
                         f"{video['r_frame_rate']}); the editor conforms it its own way, so a cut can land a frame "
                         'from the render: compare it with the preview.')
        try:
            duration = float(metadata.get('duration_s') or facts.get('format', {}).get('duration') or 0)
        except (TypeError, ValueError):
            duration = 0.0
        if not math.isfinite(duration) or duration < 0:
            raise ValueError(f'{key}: invalid source duration')
        if duration == 0:
            duration = max([float(item.get('out', 0)) for item in edit.get('picture', [])
                            if item.get('src') == key] + [float(item.get('to', 0)) for item in
                                                          edit.get('overlays', []) if item.get('src') == key] + [1])
            notes.append(f'{key}: still image has no finite source duration; the XML uses {duration:.3f} s.')
        channels = int(((metadata.get('audio') or {}).get('channels') or audio.get('channels') or 0))
        if len([stream for stream in streams if stream.get('codec_type') == 'audio']) > 1:
            notes.append(f'{key}: selection among multiple audio streams is not carried; check it in the editor.')
        if key.startswith('gen-') and not key.startswith('gen-still-'):
            notes.append(f'{key}: a generated hold or background plate is linked; it is not the original footage.')
        try:
            origin = float(facts.get('format', {}).get('start_time') or 0)
        except (TypeError, ValueError):
            origin = 0.0
        notes.extend(stream_notes(key, video, audio, rate))
        sources[key] = {'id': f'file-{number}', 'path': file, 'rate': rate, 'duration': duration,
                        'video': video, 'audio': audio, 'channels': channels, 'origin': origin,
                        'sequence_rate': sequence_rate}
    return sources


def stream_notes(key, video, audio, rate):
    """What an editor needs to check about a source's own streams: a picture that starts apart from its sound
    (an editor's test file started 33 ms late and did not transfer identically), and non-square pixels."""
    notes = []
    try:
        lead = float(video.get('start_time')) - float(audio.get('start_time'))
    except (TypeError, ValueError):
        lead = 0.0
    if video and audio and abs(lead) >= 0.5 / float(rate):
        notes.append(f"{key}: the picture starts {abs(lead) * 1000:.0f} ms {'after' if lead > 0 else 'before'} the "
                     'sound in the file; editors place the two streams their own way, so check sync against the '
                     'preview.')
    aspect = str(video.get('sample_aspect_ratio') or '1:1')
    if video and aspect not in ('1:1', '0:1', 'N/A'):
        notes.append(f'{key}: non-square pixels ({aspect}); the sequence is square-pixel, so check that the editor '
                     "reads the file's own pixel aspect and the framing matches the preview.")
    return notes


def line_text(line):
    """Use only kept words for speech, or the description for another line."""
    line = line or {}
    if line.get('kind') == 'spoken' and isinstance(line.get('words'), list):
        return ' '.join(str(word.get('text', '')).strip() for word in line['words']).strip()
    return ' '.join(str(line.get('text') or '').split())


def clip_name(line, source):
    """A short, readable source and line description."""
    words = line_text(line)
    return f'{source} - {words[:72]}' if words else source


def export_clip(src, start, end, source_in, source_out, name, **extra):
    """Create a timed, unretimed source interval for an output track."""
    result = {'src': src, 'start': float(start), 'end': float(end), 'in': float(source_in),
              'out': float(source_out), 'name': name}
    result.update(extra)
    return result


def picture_boundary(value, rate, tolerance):
    """Use assemble.py's first output frame at or after a picture boundary."""
    fps = float(rate)
    nearest = round(value * fps)
    if (nearest > 0 or value == 0) and abs(value - nearest / fps) <= tolerance:
        return nearest
    return math.ceil(value * fps - 1e-12)


def report_picture_facts(edit, key, source, report, version_dir):
    """Find the render's probed video facts, including generated files replaced by original stills."""
    recorded = (report or {}).get('sources') or {}
    if not isinstance(recorded, dict):
        return source['video']
    spelling = Path(str(edit.get('sources', {}).get(key, {}).get('file', '')))
    original = spelling if spelling.is_absolute() else version_dir / spelling
    expected = os.path.normcase(os.path.normpath(str(original.resolve())))
    matches = [facts for path, facts in recorded.items() if os.path.normcase(os.path.normpath(path)) == expected]
    if not matches and not spelling.is_absolute() and '..' not in spelling.parts:
        suffix = os.path.normcase(os.path.normpath(str(spelling)))
        matches = [facts for path, facts in recorded.items()
                   if os.path.normcase(os.path.normpath(path)).endswith(os.sep + suffix)]
    return matches[0] if len(matches) == 1 and isinstance(matches[0], dict) else source['video']


def picture_plans(edit, sources, report, notes, version_dir):
    """Rebuild the rendered picture's output-frame intervals from its saved source snaps."""
    rate = Fraction(str(edit['fps']))
    snaps = [snap for snap in (report or {}).get('snaps', []) if snap.get('clock') == 'source edit time']
    items = edit.get('picture', [])
    if (len(snaps) != 2 * len(items) or any(snaps[i * 2].get('src') != item['src']
                                            for i, item in enumerate(items))):
        snaps = []
        notes.append('The assembly report lacks matching picture snaps; picture boundaries are estimated from '
                     'edit.json.')
    ticks = []
    for item in items:
        facts = report_picture_facts(edit, item['src'], sources[item['src']], report, version_dir)
        if facts.get('variable_timing'):
            notes.append(f"{item['src']}: variable source frame timing may not transfer to the editor; inspect it.")
        try:
            ticks.append(max(float(Fraction(facts.get('time_base', '0/1'))), 1e-6)
                         / float(item.get('speed', 1)))
        except (ValueError, ZeroDivisionError):
            ticks.append(1e-6)
    tolerance = min(sum(ticks), 0.25 / float(rate))
    plans = []
    previous_end = 0.0
    for number, item in enumerate(items):
        start_in = float(snaps[number * 2]['snapped']) if snaps else float(item['in'])
        stop_in = float(snaps[number * 2 + 1]['snapped']) if snaps else float(item['out'])
        speed = float(item.get('speed', 1))
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError('invalid picture speed')
        join = item.get('join') or {}
        overlap = float(join.get('dur', 0)) if join.get('kind') in ('dissolve', 'dip') else 0.0
        raw_start = previous_end - overlap if number else 0.0
        raw_end = raw_start + (stop_in - start_in) / speed
        start_frame = picture_boundary(raw_start, rate, tolerance)
        end_frame = picture_boundary(raw_end, rate, tolerance)
        plans.append({'raw_start': raw_start, 'raw_end': raw_end, 'start': start_frame / float(rate),
                      'end': end_frame / float(rate), 'in': start_in, 'out': stop_in,
                      'covering': snaps[number * 2].get('covering_frame_pts') if snaps else None,
                      'tolerance': tolerance})
        previous_end = raw_end
    return plans


def covering_picture(source, moment, report_value=None):
    """The source presentation frame used at a picture clip's first output frame."""
    if source['path'].suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'):
        return 0.0
    try:
        tick = max(float(Fraction(source['video'].get('time_base', '0/1'))), 1e-6)
    except (ValueError, ZeroDivisionError):
        tick = 1e-6
    precision = 0.5 * 10 ** (math.floor(math.log10(max(abs(moment), 1))) - 5)
    tolerance = min(0.1 / float(source['rate']), max(1e-6, precision, tick * 0.50001))
    if report_value is not None:
        report_value = float(report_value)
        delta = report_value - moment
        if delta <= tolerance or (source['rate'] == source['sequence_rate'] and delta <= tick * 0.51):
            return report_value
    render_common = load_sibling('render_common')
    return float(render_common.presentation_frame_before('ffprobe', str(source['path']), source['origin'],
                                                          moment + tolerance))


def framing_changed(item, source, size):
    """Whether a picture item is framed other than its whole source frame, centred, at the sequence's shape: the only
    framing the XML carries. A default centred cover at zoom 1 of a source the sequence's shape is not a change."""
    crop = item.get('crop')
    path = crop.get('path') if isinstance(crop, dict) else crop
    zoom = float((crop.get('zoom') if isinstance(crop, dict) else None) or item.get('zoom') or 1)
    if path == 'auto' or abs(zoom - 1) > 1e-6:
        return True
    if isinstance(path, list) and any(abs(float(key[1]) - .5) > 1e-6 or abs(float(key[2]) - .5) > 1e-6
                                      for key in path if isinstance(key, (list, tuple)) and len(key) >= 3):
        return True
    try:
        # The displayed shape, after rotation and pixel aspect: a phone clip stored 1920x1080 with a 90-degree tag is
        # shown tall, and the render crops it, so its framing is a change the editor must rebuild.
        shown = load_sibling('render_common').display_geometry(source.get('video') or {})
        return abs(float(shown['width']) / float(shown['height']) - float(size[0]) / float(size[1])) > 0.005
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return True


def picture_tracks(edit, lines, sources, report, notes, version_dir):
    """Recover cutaways and, where source runs permit, the picture hidden underneath them."""
    main, covers = [], []
    plans = picture_plans(edit, sources, report, notes, version_dir)
    cutaways = [line for line in lines if line.get('kind') == 'cutaway']
    by_number = {line.get('line'): line for line in lines}
    for item, plan in zip(edit.get('picture', []), plans):
        speed = float(item.get('speed', 1))
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError('invalid picture speed')
        join = item.get('join') or {}
        at, timeline_end = plan['start'], plan['end']
        length = timeline_end - at
        desired = plan['in'] + max(0.0, at - plan['raw_start']) * speed
        covering = plan['covering'] if abs(desired - plan['in']) < 1e-7 else None
        source_in = covering_picture(sources[item['src']], desired, covering)
        source_out = min(source_in + length, sources[item['src']]['duration'])
        if source_out <= source_in:
            raise ValueError(f"{item['src']}: picture starts at or beyond the end of its source")
        end = min(timeline_end, at + source_out - source_in)
        if end < timeline_end - 0.001:
            notes.append(f"{item['src']} at {at:.3f} s: the 1x clip ends early; the remainder is a gap.")
        if speed != 1:
            notes.append(f"{item['src']} at {at:.3f} s: speed x{speed:g} is not carried; the clip is 1x, "
                         f"and the intended source out is {float(item['out']):.3f} s.")
        if framing_changed(item, sources[item['src']], edit.get('size')):
            notes.append(f"{item['src']} at {at:.3f} s: its crop, zoom or reframe is not carried; the clip shows the "
                         'whole source frame, so rebuild the framing from the render.')
        if item.get('hold_previous'):
            notes.append(f"{item['src']} at {at:.3f} s: hold-previous effect is not carried.")
        if join.get('kind') == 'dip':
            notes.append(f"{item['src']} at {at:.3f} s: dip transition is not carried; inspect the join.")
        matching = [line for line in cutaways if (abs(float(line['start']) - plan['raw_start']) < 0.01
                                                  or abs(float(line['start']) - at) < 0.05)
                    and (line.get('source') == item['src'] or line.get('still'))]
        line = matching[0] if matching else next((line for line in lines if not line.get('over')
                                                   and float(line.get('start', -1)) <= at + 0.02
                                                   and float(line.get('end', -1)) > at + 0.02), None)
        clip = export_clip(item['src'], at, end, source_in, source_out, clip_name(line, item['src']),
                           join=join if join.get('kind') == 'dissolve' else None)
        if matching:
            covers.append(clip)
            parent = by_number.get(line.get('over'), {})
            recovered = False
            if parent.get('kind') == 'spoken':
                for run in parent.get('runs', []):
                    run_at = float(run['at'])
                    run_end = run_at + float(run['out']) - float(run['in'])
                    rate = Fraction(str(edit['fps']))
                    left = max(at, picture_boundary(run_at, rate, plan['tolerance']) / float(rate))
                    right = min(end, picture_boundary(run_end, rate, plan['tolerance']) / float(rate))
                    if right > left and sources.get(parent.get('source'), {}).get('video'):
                        source_in = covering_picture(sources[parent['source']], float(run['in']) + left - run_at)
                        main.append(export_clip(parent['source'], left, right, source_in, source_in + right - left,
                                                clip_name(parent, parent['source'])))
                        recovered = True
            elif parent.get('kind') == 'picture' and parent.get('range'):
                factor = float(parent.get('speed', 1))
                source_in = covering_picture(sources[parent['source']],
                                             float(parent['range'][0]) + (at - float(parent['start'])) * factor)
                main.append(export_clip(parent['source'], at, end, source_in, source_in + length,
                                        clip_name(parent, parent['source'])))
                recovered = True
            if not recovered:
                notes.append(f'At {at:.3f} s: the picture under a cutaway could not be reconstructed; V1 has a gap.')
            if clip['join']:
                notes.append(f'At {at:.3f} s: a dissolve between V1 and V2 is not carried as a transition.')
                clip['join'] = None
        elif line and line.get('kind') == 'still':
            covers.append(clip)
        else:
            main.append(clip)
    main.sort(key=lambda clip: clip['start'])
    merged = []
    for clip in main:
        if (merged and merged[-1]['src'] == clip['src'] and not clip.get('join')
                and abs(merged[-1]['end'] - clip['start']) < 0.002
                and abs(merged[-1]['out'] - clip['in']) < 0.002):
            merged[-1]['end'], merged[-1]['out'] = clip['end'], clip['out']
        else:
            merged.append(clip)
    return merged, covers


def dialogue_tracks(edit, lines, sources, notes):
    """Build the kept dialogue on the first tracks and put J/L extensions on additional tracks."""
    primary, carries = [], []
    items = [item for item in edit.get('audio', []) if item.get('track') == 'dialogue']
    for line in lines:
        if line.get('kind') != 'spoken':
            continue
        for run in line.get('runs', []):
            start = float(run['at'])
            end = start + float(run['out']) - float(run['in'])
            # A line that takes its sound from a lined-up mic plays that mic, at that mic's own times.
            sound = run.get('sound_src') or line.get('source')
            sound_in = float(run.get('sound_in', run['in']))
            sound_out = float(run.get('sound_out', run['out']))
            matches = [item for item in items if item['src'] == sound
                       and abs((float(item['in']) - float(item['at'])) - (sound_in - start)) < 0.01
                       and float(item['at']) < end
                       and float(item['at']) + float(item['out']) - float(item['in']) > start]
            if not matches:
                notes.append(f"{sound} at {start:.3f} s: dialogue run has no matching audio item.")
                continue
            item = matches[0]
            primary.append(export_clip(item['src'], start, end, sound_in, sound_out,
                                       clip_name(line, item['src']), line=line, item=item))
    primary.sort(key=lambda clip: clip['start'])
    for before, after in zip(primary, primary[1:]):
        crossfade = (after['line'].get('sound_carry') or {}).get('crossfade')
        if not crossfade:
            continue
        start, end = map(float, crossfade)
        if (start < before['start'] or end > after['end'] or
                start < float(after['item']['at']) - 0.01 or
                end > float(before['item']['at']) + float(before['item']['out']) - float(before['item']['in']) + 0.01):
            notes.append(f'At {start:.3f} s: audio crossfade could not be represented; rebuild it in the editor.')
            continue
        before['out'] += end - before['end']
        before['end'] = end
        after['in'] += start - after['start']
        after['start'] = start
        after['join'] = {'kind': 'dissolve', 'dur': end - start, 'audio': True}
    for clip in primary:
        item, line = clip['item'], clip['line']
        actual_start = float(item['at'])
        actual_end = actual_start + float(item['out']) - float(item['in'])
        core_start = float(line['start'])
        core_end = float(line['end'])
        if (line.get('sound_carry') or {}).get('lead') and actual_start < core_start:
            carries.append(export_clip(clip['src'], actual_start, core_start, item['in'],
                                       float(item['in']) + core_start - actual_start, clip['name'] + ' lead'))
        if (line.get('sound_carry') or {}).get('tail') and actual_end > core_end:
            carries.append(export_clip(clip['src'], core_end, actual_end,
                                       float(item['out']) - (actual_end - core_end), item['out'],
                                       clip['name'] + ' tail'))
    if carries:
        notes.append('J/L extensions are on additional audio tracks; their fade curves and levels are not carried.')
    if any(item.get('fade_ms') or item.get('fade_in_ms') or item.get('fade_out_ms') for item in items):
        notes.append('Individual dialogue fades and the rendered mix/limiter are not carried; inspect the joins.')
    if any(item.get('gain_db') for item in edit.get('audio', [])):
        notes.append('Audio clip gains and the rendered mix are not carried; set levels in the editor.')
    if any(sources[item['src']]['channels'] >= 2 for item in items):
        notes.append('Each source sound channel is its own mono track; a stereo source\'s first channel is panned '
                     'left and its second right, as Final Cut Pro 7 writes a stereo pair. That pan has not yet been '
                     'checked in Premiere or Resolve: play a stereo clip and confirm left and right before mixing.')
    tracks = [primary, []]
    tracks[1] = [dict(clip, channel=2) for clip in primary if sources[clip['src']]['channels'] >= 2]
    for carry in carries:
        for channel in range(1, min(sources[carry['src']]['channels'], 2) + 1):
            candidate = dict(carry, channel=channel)
            placed = False
            for track in tracks[2:]:
                if all(candidate['start'] >= other['end'] - 0.001 or candidate['end'] <= other['start'] + 0.001
                       for other in track):
                    track.append(candidate)
                    placed = True
                    break
            if not placed:
                tracks.append([candidate])
    return tracks


def add_other_audio(edit, tracks, sources, notes):
    """Place music and other non-dialogue audio on separate, non-overlapping tracks."""
    for item in edit.get('audio', []):
        if item.get('track') == 'dialogue':
            continue
        start = float(item['at'])
        speed = 1.0
        for picture in edit.get('picture', []):
            if (picture['src'] == item['src'] and float(picture['in']) < float(item['out'])
                    and float(item['in']) < float(picture['out'])):
                speed = float(picture.get('speed', 1))
                break
        if not math.isfinite(speed) or speed <= 0:
            raise ValueError(f"{item['src']}: invalid audio speed")
        length = (float(item['out']) - float(item['in'])) / speed
        source_out = min(float(item['in']) + length, sources[item['src']]['duration'])
        end = start + source_out - float(item['in'])
        if speed != 1:
            notes.append(f"{item['src']} at {start:.3f} s: audio speed x{speed:g} is not carried.")
        for channel in range(1, min(sources[item['src']]['channels'], 2) + 1):
            clip = export_clip(item['src'], start, end, item['in'], source_out,
                               f"{item['src']} - {item.get('track', 'audio')}", channel=channel)
            tracks.append([clip])
        notes.append(f"{item['src']}: {item.get('track', 'audio')} gain and fades are not carried.")
    for key, source in sources.items():
        if source['channels'] > 2:
            notes.append(f"{key}: only the first two of {source['channels']} audio channels are carried.")


def graphic_tracks(edit, notes):
    """Place image overlays on V3 and higher when their intervals overlap."""
    tracks = [[]]
    for overlay in edit.get('overlays', []):
        if overlay.get('kind') not in ('image', 'video'):
            notes.append(f"Overlay {overlay.get('kind', 'unknown')}: not carried in the XML.")
            continue
        if overlay.get('kind') == 'video':
            notes.append(f"{overlay['src']}: a moving overlay; its transparency comes from the file, so check that the "
                         'editor reads its alpha channel.')
        if any(key in overlay for key in ('pin', 'behind', 'blur')):
            notes.append(f"{overlay.get('src', 'overlay')}: pin, behind or blur is not carried.")
        start = max(0.0, float(overlay.get('from', 0)))
        end = float(overlay.get('to', start))
        if end <= start:
            continue
        clip = export_clip(overlay['src'], start, end, 0, end - start, overlay['src'])
        for track in tracks:
            if all(start >= other['end'] or end <= other['start'] for other in track):
                track.append(clip)
                break
        else:
            tracks.append([clip])
        notes.append(f"{overlay['src']}: graphic position, scale, opacity and fades are not carried.")
    return tracks


def assign_links(video_tracks, audio_tracks, rate, sources):
    """Assign stable clip IDs and link synchronized picture and source-channel audio."""
    all_tracks = [('video', video_tracks), ('audio', audio_tracks)]
    count = 0
    for kind, tracks in all_tracks:
        for track_number, track in enumerate(tracks, 1):
            track.sort(key=lambda clip: clip['start'])
            for clip_number, clip in enumerate(track, 1):
                count += 1
                clip.update({'id': f'clip-{count}', 'kind': kind, 'track_number': track_number,
                             'clip_number': clip_number, 'links': []})
    for track in video_tracks:
        for picture in track:
            candidates = [audio for audio in audio_tracks[0] if audio['src'] == picture['src']
                          and abs((audio['in'] - audio['start']) - (picture['in'] - picture['start']))
                          <= max(1 / float(rate), 1 / float(sources[picture['src']]['rate'])) + 1e-6
                          and min(audio['end'], picture['end']) > max(audio['start'], picture['start'])]
            if not candidates:
                continue
            audio = max(candidates, key=lambda row: min(row['end'], picture['end']) -
                        max(row['start'], picture['start']))
            group = [picture, audio]
            if len(audio_tracks) > 1:
                group.extend(row for row in audio_tracks[1] if row['src'] == audio['src']
                             and abs(row['start'] - audio['start']) < 0.001
                             and abs(row['in'] - audio['in']) < 0.001)
            for row in group:
                row['links'].extend(member for member in group if member is not row)


def append_file(parent, source, output_dir, relative, defined):
    """Reference a file ID, fully defining it on its first use."""
    node = ET.SubElement(parent, 'file', {'id': source['id']})
    if source['id'] in defined:
        return
    defined.add(source['id'])
    xml_text(node, 'name', source['path'].name)
    xml_text(node, 'pathurl', media_url(source['path'], output_dir, relative))
    xml_rate(node, source['rate'])
    xml_text(node, 'duration', frame_at(source['duration'], source['rate']))
    media = ET.SubElement(node, 'media')
    if source['video']:
        video = ET.SubElement(media, 'video')
        sample = ET.SubElement(video, 'samplecharacteristics')
        xml_rate(sample, source['rate'])
        xml_text(sample, 'width', source['video'].get('width', 0))
        xml_text(sample, 'height', source['video'].get('height', 0))
    if source['audio']:
        audio = ET.SubElement(media, 'audio')
        xml_text(audio, 'channelcount', source['channels'])
        sample = ET.SubElement(audio, 'samplecharacteristics')
        xml_text(sample, 'samplerate', source['audio'].get('sample_rate', 48000))


def append_transition(parent, start, end, rate, audio):
    """Add a start-aligned FCP cross transition; its cut is at the beginning of the overlap."""
    node = ET.SubElement(parent, 'transitionitem')
    xml_text(node, 'start', frame_at(start, rate))
    xml_text(node, 'end', frame_at(end, rate))
    xml_text(node, 'alignment', 'start')
    xml_text(node, 'cutPointTicks', 0)
    xml_rate(node, rate)
    effect = ET.SubElement(node, 'effect')
    xml_text(effect, 'name', 'Cross Fade (+3dB)' if audio else 'Cross Dissolve')
    xml_text(effect, 'effectid', 'KGAudioTransCrossFade3dB' if audio else 'Cross Dissolve')
    xml_text(effect, 'effectcategory', 'Audio Transitions' if audio else 'Dissolve')
    xml_text(effect, 'effecttype', 'transition')
    xml_text(effect, 'mediatype', 'audio' if audio else 'video')


def append_pan(parent, value):
    """Pan one channel of a stereo pair hard left (-1) or right (1), as Final Cut Pro 7 writes a stereo pair.

    Each source channel is its own mono track, and an importer centres a mono track unless told otherwise: in an
    editor's Premiere test both channels of a stereo source played in both speakers."""
    effect = ET.SubElement(ET.SubElement(parent, 'filter'), 'effect')
    xml_text(effect, 'name', 'Audio Pan')
    xml_text(effect, 'effectid', 'audiopan')
    xml_text(effect, 'effectcategory', 'audiopan')
    xml_text(effect, 'effecttype', 'audiopan')
    xml_text(effect, 'mediatype', 'audio')
    parameter = ET.SubElement(effect, 'parameter')
    xml_text(parameter, 'parameterid', 'pan')
    xml_text(parameter, 'name', 'Pan')
    xml_text(parameter, 'valuemin', -1)
    xml_text(parameter, 'valuemax', 1)
    xml_text(parameter, 'value', value)


def audio_frame_range(clip, source, rate, transition_after):
    """Choose a frame-grid source interval that keeps both endpoints as close as possible to the source ticks."""
    start_frame = frame_at(clip['start'], rate)
    end_frame = frame_at(clip['end'], rate)
    logical_end = frame_at(transition_after[0], rate) if transition_after else end_frame
    handle = ((frame_at(transition_after[1], rate) - logical_end) / float(rate) if transition_after else 0.0)
    logical_duration = (logical_end - start_frame) / float(rate)
    center = (clip['in'] + clip['out'] - handle - logical_duration) / 2
    span = end_frame - start_frame
    if span <= 0:
        raise ValueError(f"{clip['src']}: audio interval is shorter than the XML frame grid can represent")
    maximum = frame_at(source['duration'], rate) - span
    if maximum < 0:
        raise ValueError(f"{clip['src']}: audio interval cannot fit within its source on the XML frame grid")
    source_in = min(max(0, frame_at(center, rate)), maximum)
    start_error = abs(source_in / float(rate) - clip['in'])
    end_error = abs(source_in / float(rate) + logical_duration - (clip['out'] - handle))
    return source_in, source_in + span, max(start_error, end_error)


def append_clip(parent, clip, source, rate, output_dir, relative, defined, before, after, notes):
    """Write a clip item, retaining the transition handles in its source range."""
    node = ET.SubElement(parent, 'clipitem', {'id': clip['id']})
    xml_text(node, 'name', clip['name'])
    xml_text(node, 'enabled', 'TRUE')
    clip_rate = source['rate'] if clip['kind'] == 'video' else rate
    xml_rate(node, clip_rate)
    xml_text(node, 'duration', frame_at(source['duration'], clip_rate))
    xml_text(node, 'start', -1 if before else frame_at(clip['start'], rate))
    xml_text(node, 'end', -1 if after else frame_at(clip['end'], rate))
    if clip['kind'] == 'audio':
        source_in, source_out, error = audio_frame_range(clip, source, rate, after)
        if error > 0.5 / float(rate) + 1e-7:
            notes.append(f"{clip['src']} at {clip['start']:.3f} s: frame-based audio source boundaries can differ "
                         f'from the saved ticks by up to {error:.3f} s; inspect the edit.')
    else:
        source_in = frame_at(clip['in'], clip_rate)
        source_out = frame_at(clip['out'], clip_rate)
    xml_text(node, 'in', source_in)
    xml_text(node, 'out', source_out)
    xml_text(node, 'pproTicksIn', round(Fraction(str(clip['in'])) * TICKS_PER_SECOND))
    xml_text(node, 'pproTicksOut', round(Fraction(str(clip['out'])) * TICKS_PER_SECOND))
    append_file(node, source, output_dir, relative, defined)
    if clip['kind'] == 'audio':
        source_track = ET.SubElement(node, 'sourcetrack')
        xml_text(source_track, 'mediatype', 'audio')
        xml_text(source_track, 'trackindex', clip.get('channel', 1))
        if source['channels'] >= 2 and clip.get('channel', 1) in (1, 2):
            append_pan(node, -1 if clip.get('channel', 1) == 1 else 1)
    for member in clip['links']:
        link = ET.SubElement(node, 'link')
        xml_text(link, 'linkclipref', member['id'])
        xml_text(link, 'mediatype', member['kind'])
        xml_text(link, 'trackindex', member['track_number'])
        xml_text(link, 'clipindex', member['clip_number'])


def append_track(parent, clips, sources, rate, output_dir, relative, defined, notes):
    """Write clips and any representable adjacent transitions in edit order."""
    node = ET.SubElement(parent, 'track')
    transitions = {}
    for index in range(1, len(clips)):
        before, after = clips[index - 1], clips[index]
        join = after.get('join') or {}
        if join.get('kind') != 'dissolve':
            if after['start'] < before['end'] - 0.5 / float(rate):
                notes.append(f"{after['src']} at {after['start']:.3f} s: an overlapping clip has no XML transition.")
            continue
        start = after['start']
        end = before['end']
        if frame_at(end, rate) <= frame_at(start, rate) or end > after['end'] + 0.001:
            notes.append(f"{after['src']} at {start:.3f} s: dissolve could not be represented.")
            continue
        transitions[index] = (start, end)
    for index, clip in enumerate(clips):
        if index in transitions:
            start, end = transitions[index]
            append_transition(node, start, end, rate, clip['kind'] == 'audio')
        append_clip(node, clip, sources[clip['src']], rate, output_dir, relative, defined,
                    transitions.get(index), transitions.get(index + 1), notes)
    xml_text(node, 'enabled', 'TRUE')
    xml_text(node, 'locked', 'FALSE')


def append_marker(sequence, at, label, body, rate):
    """Add a sequence marker at an edit time."""
    marker = ET.SubElement(sequence, 'marker')
    xml_text(marker, 'name', label)
    xml_text(marker, 'comment', body)
    xml_text(marker, 'in', frame_at(at, rate))
    xml_text(marker, 'out', -1)


def timeline_xml(edit, lines, manifest, sources, video_tracks, audio_tracks, notes, output, relative, markers):
    """Build a complete FCP 7 XML sequence and return its UTF-8 text."""
    rate = Fraction(str(edit['fps']))
    xmeml_rate(rate)
    assign_links(video_tracks, audio_tracks, rate, sources)
    root = ET.Element('xmeml', {'version': '5'})
    sequence = ET.SubElement(root, 'sequence', {'id': 'sequence-1'})
    xml_text(sequence, 'name', manifest.get('title') or manifest.get('version') or 'Legible Film')
    xml_text(sequence, 'duration', manifest.get('frames') or frame_at(lines.get('duration_s', 0), rate))
    xml_rate(sequence, rate)
    for at, label, body in markers:
        append_marker(sequence, at, label, body, rate)
    media = ET.SubElement(sequence, 'media')
    video = ET.SubElement(media, 'video')
    format_node = ET.SubElement(video, 'format')
    sample = ET.SubElement(format_node, 'samplecharacteristics')
    xml_rate(sample, rate)
    xml_text(sample, 'width', edit['size'][0])
    xml_text(sample, 'height', edit['size'][1])
    # The render is square-pixel and progressive. Without these an importer picks its own default: Premiere chose
    # PAL-601 (35:32 pixels) in an editor's test. Sources keep their own pixel aspect, which the editor reads.
    xml_text(sample, 'anamorphic', 'FALSE')
    xml_text(sample, 'pixelaspectratio', 'square')
    xml_text(sample, 'fielddominance', 'none')
    defined = set()
    for track in video_tracks:
        append_track(video, track, sources, rate, output.parent, relative, defined, notes)
    audio = ET.SubElement(media, 'audio')
    for track in audio_tracks:
        append_track(audio, track, sources, rate, output.parent, relative, defined, notes)
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + \
        ET.tostring(root, encoding='unicode') + '\n'


def run_write(args):
    """Write one version as FCP 7 XML, its captions and an explicit list of omissions."""
    root = Path(args.project).resolve()
    if not re.fullmatch(r'v[0-9]{3,}', args.version):
        raise ValueError('version must have the form v001')
    version_dir = root / 'cuts' / args.version
    edit_file, lines_file, manifest_file = (version_dir / name for name in ('edit.json', 'lines.json', 'manifest.json'))
    report_file = version_dir / 'assemble-report.json'
    edit, lines, manifest = (P.load_json(path, None) for path in (edit_file, lines_file, manifest_file))
    if not all(isinstance(value, dict) for value in (edit, lines, manifest)):
        raise ValueError(f'{version_dir}: edit.json, lines.json and manifest.json are required')
    rate = Fraction(str(edit['fps']))
    xmeml_rate(rate)
    output = Path(args.out).resolve()
    if output.suffix.lower() != '.xml':
        raise ValueError('--out must name an XML file')
    captions = version_dir / 'captions.srt'
    srt_output = output.with_suffix('.srt')
    note_output = output.with_suffix('.notes.txt')
    notes = []
    sources = export_sources(root, version_dir, edit, manifest, rate, notes, args.verify)
    inputs = [edit_file, lines_file, manifest_file, report_file, captions, root / 'map' / 'sources.json',
              root / 'notes.json']
    inputs.extend(source['path'] for source in sources.values())
    outputs = [output, srt_output, note_output]
    P.refuse_overwriting_inputs(outputs, inputs)
    # Every version folder is immutable, this project's or another's: its manifest hashes its files.
    own_cuts = (root / 'cuts').resolve()
    for target in outputs:
        for folder in target.parents:
            project_cuts = folder.name == 'cuts' and any((folder.parent / name).is_file()
                                                         for name in ('film.md', 'status.json'))
            if folder == own_cuts or project_cuts:
                raise ValueError(f'write the hand-off outside {folder}: version folders never change')
    report = P.load_json(report_file, {}) or {}
    if not isinstance(report, dict):
        report = {}
    picture, cutaways = picture_tracks(edit, lines.get('lines', []), sources, report, notes, version_dir)
    graphics = graphic_tracks(edit, notes)
    audio = dialogue_tracks(edit, lines.get('lines', []), sources, notes)
    add_other_audio(edit, audio, sources, notes)
    markers = []
    for line in lines.get('lines', []):
        description = line_text(line)
        if description:
            markers.append((float(line.get('start', 0)), f"Line {line.get('line', '')}", description))
    note_data = P.load_json(root / 'notes.json', {}) or {}
    for note in note_data.get('notes', []):
        if (note.get('version') == args.version and note.get('status', 'open') == 'open'
                and note.get('t') is not None):
            markers.append((float(note['t']), f"Note {note.get('id', '')}",
                            f"{note.get('origin', 'unknown')}: \"{note.get('text', '')}\""))
    if not captions.is_file():
        notes.append('The version has no captions.srt; no SRT was written.')
    if manifest.get('lineup'):
        notes.append('The line-up itself is not carried: each camera and mic clip sits at the in-point its offset '
                     'gave, with no sync group or multicam clip, and a drift correction is the in-point of each clip. '
                     'Slip a clip and it leaves the others; link them in the editor first if you mean to.')
    if edit.get('holds'):
        notes.append('Hold effects are not carried as editable source holds.')
    if edit.get('film_fades'):
        notes.append('Film fade effects are not carried.')
    notes.append('Burned captions are not carried in the XML; import the SRT separately.')
    notes.append('Audio source points use Premiere ticks; sub-frame timeline placement is rounded to XML frames.')
    notes.append('Pixel geometry, colour conversion, retiming and the finished mix can differ; compare the render.')
    xml = timeline_xml(edit, lines, manifest, sources, [picture, cutaways] + graphics, audio,
                       notes, output, args.relative, sorted(markers))
    unique_notes = list(dict.fromkeys(notes))
    shape = ('What the editor will see: a square-pixel sequence with the main picture on V1, cutaways and stills on '
             'V2, graphics on V3; each source sound channel on its own mono track (dialogue first, then lead and tail '
             'pieces and music), a stereo pair panned left and right, linked to its picture; clips keep their full '
             'source length as handles. To compare an export from the editor with the render, export WAV or PCM '
             'sound: an AAC export adds encoder delay (1,024 samples in one Premiere test), which is not an edit '
             'offset. '
             + ('Media paths are relative to the XML: keep the media beside it.' if args.relative else
                'Media paths are absolute file paths on this machine: on another machine, relink, or write again '
                'with --relative and copy the media with the XML.'))
    report = (shape + '\n\nNot carried or requires inspection:\n'
              + ''.join(f'- {note}\n' for note in unique_notes))
    P.write_atomic(output, xml)
    if captions.is_file():
        P.write_atomic(srt_output, P.read_text(captions))
    P.write_atomic(note_output, report)
    print(f'Wrote {output} (Final Cut Pro 7 XML (xmeml))')
    if captions.is_file():
        print(f'Wrote {srt_output}')
    print(f'Wrote {note_output}')
    print('Checked by round trip, OpenTimelineIO and one synthetic Premiere import; the pixel aspect and stereo pan '
          'written since, and Resolve, are not yet tested.')
    print(report, end='')
    return 0


def protect_inputs(args):
    """Protect explicitly supplied files, project maps and local timeline media from a JSON output."""
    timelines = ([args.timeline] if args.command in ('read', 'words') else [args.before, args.after])
    inputs = timelines + list(getattr(args, 'words', [])) + [getattr(args, 'captions', None)]
    P.refuse_overwriting_inputs([args.json], inputs)
    root = Path(args.project) if getattr(args, 'project', None) else None
    if root:
        index = root / 'map' / 'sources.json'
        inputs.append(index)
        data = P.load_json(index, {})
        for source in data.get('sources', []):
            path = Path(str(source.get('path', '')))
            inputs.append(path if path.is_absolute() else root / path)
            inputs.append(root / 'map' / source['alias'] / 'words.json')
    for timeline in timelines:
        files = file_table(ET.parse(timeline).getroot(), Path(timeline).resolve().parent)
        for entry in files.values():
            path = local_path(entry.get('url') or '')
            if path is not None:
                inputs.append(path)
    P.refuse_overwriting_inputs([args.json], inputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    writing = sub.add_parser('write', help='write a version as Final Cut Pro 7 XML (xmeml)')
    writing.add_argument('project')
    writing.add_argument('version')
    writing.add_argument('--out', required=True, help='XML output, outside cuts/ (version folders never change)')
    writing.add_argument('--format', choices=('xmeml',), default='xmeml')
    writing.add_argument('--relative', action='store_true', help='write source paths relative to the XML folder')
    writing.add_argument('--verify', action='store_true', help='also compare source hashes with the version manifest')
    read = sub.add_parser('read')
    read.add_argument('timeline')
    words = sub.add_parser('words')
    words.add_argument('timeline')
    comparing = sub.add_parser('compare')
    comparing.add_argument('before')
    comparing.add_argument('after')
    comparing.add_argument('--captions')
    for command in (words, comparing):
        command.add_argument('--words', action='append', default=[], help='a word-timed transcript (repeatable)')
        command.add_argument('--project', help='project folder: transcripts, file paths and hashes from its map')
        command.add_argument('--map', action='append', default=[], metavar='FILE=ALIAS',
                             help='use the transcript ALIAS for the timeline file FILE (repeatable)')
    for command in (read, words, comparing):
        command.add_argument('--track', type=int, default=1, help='audio track number (default 1)')
        command.add_argument('--json', help='write the result here')
    args = parser.parse_args()
    P.safe_output()
    try:
        if args.command == 'write':
            return run_write(args)
        protect_inputs(args)
        if args.command == 'read':
            result, flagged = run_read(args)
        else:
            if not args.words and not args.project:
                raise ValueError('give --project PROJECT or --words WORDS.json')
            mapping = parse_mapping(args.map)
            run = run_words if args.command == 'words' else run_compare
            result, flagged = run(args, mapping)
        if args.json:
            P.save_json(args.json, result)
        return 1 if flagged else 0
    except (OSError, ValueError, KeyError, ET.ParseError, json.JSONDecodeError, RuntimeError, ArithmeticError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
