#!/usr/bin/env python3
"""Build and serve a local Screening Room, and manage screening notes and decisions.

  screen.py build PROJECT
  screen.py serve PROJECT [--port PORT] [--open]
  screen.py notes PROJECT [--all]
  screen.py resolve PROJECT NOTE_ID --in VERSION --reply TEXT [--declined]
  screen.py ask PROJECT --at SECONDS --text TEXT [--option LABEL=PATH ...]
  screen.py decide PROJECT --category C --subject S --decision D [--rejected R ...] --by WHO
  screen.py import-notes PROJECT FILE --origin flask
  C: story, picture, sound, captions, delivery. WHO: person, agent, reviewer.

`notes` lists each open note (all with --all): its moment, where it came from (the room, Flask or the agent, from
the note's `origin` field) and its words quoted on one line, as material to judge rather than instructions.

In the room, J, K and L shuttle as in editing applications (L forward and J backward, each press again doubling the
speed to 8x; K stops), the left and right arrows step one frame when paused and one second when playing or with
Shift, Home and End go to the start and end, Space plays or pauses, N adds a note, and ? (or the Keys button) shows
these keys. No key acts while a box (the note, the replay times) has focus. Playing backward steps back in small
seeks, since browsers cannot play video in reverse.

The live room link is printed by `screen.py serve`; keep it from that command's output. It is not saved in the
shareable screening folder. The room presents checks and requests human review; it does not establish perceptual
approval.
Exit 0 on success, 1 when there is something to inspect, 2 when the command cannot run.
"""
import argparse
import difflib
import functools
import hashlib
import html
import http.client
import http.cookies
import importlib.util
import json
import mimetypes
import math
import os
import re
import secrets
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import unicodedata
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('lf_project', Path(__file__).with_name('project.py'))
project = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project)
CUT_SPEC = importlib.util.spec_from_file_location('lf_screen_cut', Path(__file__).with_name('cut.py'))
cut = importlib.util.module_from_spec(CUT_SPEC)
CUT_SPEC.loader.exec_module(cut)
LOCK = threading.RLock()
HASH_CACHE = {}
# The room's typefaces (SIL Open Font License, Latin subsets), copied beside the page so it also works as a file.
FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'
FONTS = ('Inter-Latin-400.woff2', 'Inter-Latin-500.woff2', 'Inter-Latin-600.woff2', 'IBMPlexMono-Latin-400.woff2')
NOTE_ORIGINS = {'room': 'the Screening Room', 'flask': 'Flask', 'agent': 'the agent (screen.py ask)'}


def read_json(path, default):
    """Read optional project data using the project contract."""
    return project.load_json(path, default)


def warn_file(path, message='invalid or damaged data'):
    """Name an optional file the agent can repair, without exposing it in the page."""
    print(f'warning: {path.name}: {message}', file=sys.stderr)


def optional_object(path, default):
    """Read an optional JSON object; do not replace damaged files on disk."""
    if not path.exists():
        return default
    try:
        value = read_json(path, default)
        if not isinstance(value, dict):
            raise ValueError('expected an object')
        return value
    except (OSError, ValueError, TypeError, RecursionError):
        warn_file(path)
        return default


def object_rows(path, value, key):
    """Keep object rows from an optional array and warn if its shape is damaged."""
    rows = value.get(key)
    if not isinstance(rows, list):
        warn_file(path, f'{key} must be a list')
        return []
    good = [row for row in rows if isinstance(row, dict)]
    if len(good) != len(rows):
        warn_file(path, f'some {key} entries are invalid')
    return good


def finite(value):
    """Whether a value is a finite JSON number, excluding booleans."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def public_detail(value):
    """Remove local paths and fingerprints from a diagnostic shown to the person."""
    if not isinstance(value, str):
        return ''
    value = re.sub(r'(?i)\b[a-z]:[\\/][^\r\n\'"<>|,;:]*', '[local path]', value)
    value = re.sub(r'(?<![\w:])/(?:[^/\s\'"<>:,;]+/)+[^\s\'"<>:,;]*', '[local path]', value)
    value = re.sub(r'(?i)\b[0-9a-f]{64}\b', '[fingerprint]', value)
    return value[:1000]


def room_status(root):
    """Read status safely; indicate whether it is safe to write the original file."""
    path = root / 'status.json'
    default = project.default_status(root.name)
    value = optional_object(path, None)
    if value is None:
        return default, not path.exists()
    valid = True
    for key, shape in (('stages', dict), ('reviewed', dict), ('running', list), ('blind_spots', list)):
        if key in value and not isinstance(value[key], shape):
            warn_file(path, f'{key} has an invalid shape')
            value[key] = default.get(key, {} if shape is dict else [])
            valid = False
    stages = value.get('stages', {})
    if any(name not in project.STAGES or not isinstance(state, str) or state not in project.STATES
           for name, state in stages.items()):
        warn_file(path, 'stage entries are invalid')
        value['stages'] = {name: state for name, state in stages.items() if name in project.STAGES
                           and isinstance(state, str) and state in project.STATES}
        valid = False
    reviewed = value.get('reviewed', {})
    if any(not isinstance(entry, dict) for entry in reviewed.values()):
        warn_file(path, 'review entries must be objects')
        value['reviewed'] = {name: entry for name, entry in reviewed.items() if isinstance(entry, dict)}
        valid = False
    if not all(isinstance(item, dict) for item in value.get('running', [])):
        warn_file(path, 'running entries must be objects')
        value['running'] = []
        valid = False
    else:
        value['running'] = project.live_running(value.get('running', []))
    if not all(isinstance(item, str) for item in value.get('blind_spots', [])):
        warn_file(path, 'blind spots must be text')
        value['blind_spots'] = []
        valid = False
    return value, valid


def room_checks(path):
    """Expose only safe check items and summary, never a source file path."""
    value = optional_object(path, {})
    rows = object_rows(path, value, 'items') if 'items' in value else []
    items = []
    for row in rows:
        if row.get('state') not in ('pass', 'look', 'fail', 'you', 'skip'):
            warn_file(path, 'a check has an invalid state')
            continue
        item = {key: row[key] for key in ('id', 'label', 'state', 'detail', 'at') if key in row}
        for key in ('id', 'label', 'detail'):
            if key in item and not isinstance(item[key], str):
                item[key] = ''
            elif key in item and key != 'id':
                item[key] = public_detail(item[key])
        if 'at' in item and item['at'] is not None and not finite(item['at']):
            item['at'] = None
        items.append(item)
    summary = value.get('summary', {})
    if not isinstance(summary, dict):
        warn_file(path, 'summary must be an object')
        summary = {}
    summary = {key: val for key, val in summary.items() if key in ('pass', 'look', 'fail', 'you', 'skip')
               and type(val) is int and val >= 0}
    return {'items': items, 'summary': summary}


def room_lines(path):
    """Keep only timed line objects the room can safely place on the timeline."""
    value = optional_object(path, {})
    rows = object_rows(path, value, 'lines') if 'lines' in value else []
    result = []
    for row in rows:
        if type(row.get('line')) is not int or not finite(row.get('start')) or not finite(row.get('end')):
            warn_file(path, 'a line has invalid timing or line number')
            continue
        if row['start'] < 0 or row['end'] < row['start']:
            warn_file(path, 'a line has invalid timing')
            continue
        item = dict(row)
        for key in ('kind', 'source'):
            if key in item and not isinstance(item[key], str):
                warn_file(path, f'line {key} must be text')
                item.pop(key)
        words = item.get('words', [])
        if not isinstance(words, list):
            warn_file(path, 'line words must be a list')
            words = []
        clean_words = [word for word in words if isinstance(word, str) or (
            isinstance(word, dict) and finite(word.get('start')) and finite(word.get('end'))
            and word['end'] >= word['start'])]
        if len(clean_words) != len(words):
            warn_file(path, 'a word has invalid timing')
        item['words'] = clean_words
        result.append(item)
    return {'lines': result}


def room_freshness(root, path):
    """Whether a version's checks still describe their inputs, for the room: {'state': current, out_of_date,
    inputs_not_recorded, none or unknown, 'changed': [file names]}. Only file names reach the page, never a path."""
    try:
        raw = read_json(path, None)
        if not isinstance(raw, dict):
            return {'state': 'none', 'changed': []}
        state, changes = project.checks_freshness(root, raw)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
        return {'state': 'unknown', 'changed': []}
    names = [Path(str(row.get('path', ''))).name for row in changes]
    return {'state': {'unrecorded': 'inputs_not_recorded'}.get(state, state), 'changed': names}


def safe_status_line(root, version, status, checks):
    """Use the project status when possible; fall back to the safe snapshot, which never counts checks whose
    inputs changed as passing and says when their inputs could not be compared."""
    if not version:
        return 'No complete version yet'
    try:
        return project.status_line(root, version)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
        fresh = room_freshness(root, root / 'cuts' / str(version) / 'checks.json')
        label = f"v{int(version[1:])}"
        parts = []
        if fresh['state'] == 'out_of_date':
            parts.append(f"{label} checked \u00b7 out of date ({', '.join(fresh['changed'][:4])} changed): "
                         'run check.py again')
        else:
            reviewed = status.get('reviewed', {}).get(version, {})
            reviewed = reviewed if isinstance(reviewed, dict) else {}
            summary = counts(checks, reviewed)
            mark = ' \u00b7 inputs not verified' if fresh['state'] != 'current' else ''
            parts.append(f"{label} checked \u00b7 {project.readiness(summary)}{mark}")
        final_path = root / 'cuts' / str(version) / 'checks-final.json'
        if final_path.exists():
            final_raw = optional_object(final_path, {})
            final_fresh = room_freshness(root, final_path)
            if final_fresh['state'] == 'out_of_date':
                changed = ', '.join(final_fresh['changed'][:4])
                parts.append(f'final checked \u00b7 out of date ({changed} changed): run check.py again')
            elif final_fresh['state'] in ('none', 'unknown') or not (
                    isinstance(final_raw.get('items'), list) or isinstance(final_raw.get('summary'), dict)):
                parts.append('final check status unknown')
            else:
                summary = counts(room_checks(final_path), {})
                mark = ' \u00b7 inputs not verified' if final_fresh['state'] != 'current' else ''
                parts.append(f"final checked \u00b7 {project.readiness(summary)}{mark}")
        return '; '.join(parts)


def review_key(item):
    """The status.json `reviewed` key for a check only a person can judge: the item's own id (check.py
    writes watched_muted, heard and names), so any person check can be ticked."""
    key = str(item.get('id', '')).strip()
    return key if item.get('state') == 'you' and re.fullmatch(r'[a-z0-9_]{1,40}', key) else None


def counts(checks, reviewed):
    """Count check items, excluding completed identifiable human reviews."""
    result = {key: 0 for key in ('pass', 'look', 'fail', 'you', 'skip')}
    items = checks.get('items', [])
    if not items:
        result.update({k: checks.get('summary', {}).get(k, 0) for k in result})
        return result
    for item in items:
        state = item.get('state')
        if state in result and not (state == 'you' and review_key(item) and reviewed.get(review_key(item))):
            result[state] += 1
    return result


def refresh_status(root, stage=False, version=None):
    """Update readiness after every operation using current checks and review records."""
    if version is None and project.versions(root):
        snapshot = complete_snapshot(root)
        version = snapshot['current'] if snapshot else None
    _, writable = room_status(root)
    if stage and writable:
        project.set_stage(root, 'screen')
    with project.file_lock(root / 'status.json'):
        status, writable = room_status(root)
        if not writable:
            return status
        checks = room_checks(root / 'cuts' / str(version) / 'checks.json')
        reviewed = status.get('reviewed', {}).get(version, {})
        if not isinstance(reviewed, dict):
            warn_file(root / 'status.json', 'review entries must be objects')
            return status
        # checks.json describes the preview; only reviews recorded against the preview count for it.
        preview = project.preview_sha256(root, version) if version else None
        reviewed = project.reviews_for(reviewed, preview, bool(preview))
        remaining = [item.get('label', item.get('id', 'review')) for item in checks.get('items', [])
                     if item.get('state') == 'you' and not (review_key(item) and reviewed.get(review_key(item)))]
        summary = counts(checks, reviewed)
        if not checks.get('items') and summary['you']:
            remaining = ['human review'] * summary['you']
        line = safe_status_line(root, version, status, checks)
        fields = {'current': version, 'needs_you': remaining, 'line': line}
        return project._update_status(root, fields)


def paper_words(text):
    """Keep strike state and attach punctuation-only tokens to their preceding word."""
    result = []
    for index, part in enumerate(re.split(r'~~', text)):
        for word in part.split():
            if not cut.normal_tokens(word):
                if result:
                    result[-1]['text'] += word
            else:
                result.append({'text': word, 'removed': bool(index % 2)})
    return result


def changed_words(current, previous):
    """Show explicitly struck words once, and words deleted since the parent where they belonged."""
    after = paper_words(current)
    if previous is None:
        return after
    before = [part['text'] for part in paper_words(previous) if not part['removed']]
    matcher = difflib.SequenceMatcher(None, [tuple(cut.normal_tokens(word)) for word in before],
                                      [tuple(cut.normal_tokens(part['text'])) for part in after], autojunk=False)
    result = []
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag in ('delete', 'replace'):
            result.extend({'text': word, 'removed': True} for word in before[a:b])
        if tag in ('equal', 'insert', 'replace'):
            result.extend(after[c:d])
    return result


def parse_paper(text):
    """Use the compiler's grammar for the title, line kinds, descriptions and modifiers."""
    settings, entries = cut.parse_film(text, cut.Problems())
    return settings.get('title', ''), entries


def paper_changes(current, parent):
    """Align compiler entries by source and display deleted parent entries in their old position."""
    title, entries = parse_paper(current)
    _, old = parse_paper(parent) if parent else ('', [])
    changes = {}
    removed = []
    pairs = {}
    if parent:
        matcher = difflib.SequenceMatcher(None, [cut.line_key(item) for item in old],
                                          [cut.line_key(item) for item in entries], autojunk=False)
        operations = matcher.get_opcodes()
        inserted = [index for tag, _, _, c, d in operations if tag != 'equal' for index in range(c, d)]
        deleted = [index for tag, a, b, _, _ in operations if tag != 'equal' for index in range(a, b)]
        moved_old = set()
        moved_new = set()
        for old_index in deleted:
            match = next((index for index in inserted if index not in moved_new
                          and cut.line_key(old[old_index]) == cut.line_key(entries[index])), None)
            if match is not None:
                moved_old.add(old_index)
                moved_new.add(match)
                before, after = old[old_index], entries[match]
                pairs[after['line']] = before
                changes[str(after['line'])] = {'moved': True,
                                              'changed': cut.line_content(before) != cut.line_content(after)}
        for tag, a, b, c, d in operations:
            if tag == 'equal':
                for before, after in zip(old[a:b], entries[c:d]):
                    pairs[after['line']] = before
                    if cut.line_content(before) != cut.line_content(after):
                        changes[str(after['line'])] = {'changed': True}
                continue
            before_line = entries[c]['line'] if c < len(entries) else None
            for index in range(a, b):
                if index not in moved_old:
                    removed.append(dict(old[index], before_line=before_line))
            for index in range(c, d):
                if index not in moved_new:
                    changes[str(entries[index]['line'])] = {'changed': True}
    for entry in entries:
        if entry['kind'] != 'spoken':
            continue
        previous = pairs.get(entry['line'])
        parts = changed_words(entry['text'], previous['text'] if previous else None)
        entry['parts'] = parts
        if str(entry['line']) in changes:
            changes[str(entry['line'])].update(parts=parts,
                                                removed=[part['text'] for part in parts if part['removed']])
    return title, entries, changes, removed


def public_sources(root):
    """Keep only source fields needed by the room; never embed original paths or hashes."""
    path = root / 'map' / 'sources.json'
    source_map = optional_object(path, {})
    result = []
    for source in object_rows(path, source_map, 'sources') if 'sources' in source_map else []:
        alias = source.get('alias')
        role = source.get('role')
        if (not isinstance(alias, str) or not cut.ALIAS_SHAPE.fullmatch(alias) or not isinstance(role, str)
                or not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}', role)):
            warn_file(path, 'a source has an invalid alias or role')
            continue
        entry = {'alias': alias, 'role': role}
        duration = source.get('duration_s')
        if finite(duration) and duration >= 0:
            entry['duration_s'] = duration
        elif duration is not None:
            warn_file(path, 'a source duration is invalid')
        video = source.get('video')
        if isinstance(video, dict):
            clean_video = {}
            for key in ('width', 'height'):
                if type(video.get(key)) is int and video[key] > 0:
                    clean_video[key] = video[key]
                elif key in video:
                    warn_file(path, 'a source picture size is invalid')
            size = video.get('size')
            if isinstance(size, list) and len(size) == 2 and all(type(x) is int and x > 0 for x in size):
                clean_video['size'] = size
            elif size is not None:
                warn_file(path, 'a source picture size is invalid')
            fps = video.get('fps')
            if (finite(fps) and fps > 0) or (isinstance(fps, str) and re.fullmatch(r'\d+(?:\.\d+)?(?:/\d+)?', fps)):
                clean_video['fps'] = fps
            elif fps is not None:
                warn_file(path, 'a source frame rate is invalid')
            entry['video'] = clean_video
        audio = source.get('audio')
        if isinstance(audio, dict):
            clean = {}
            if type(audio.get('index')) is int and audio['index'] >= 0:
                clean['index'] = audio['index']
            if type(audio.get('channels')) is int and 1 <= audio['channels'] <= 64:
                clean['channels'] = audio['channels']
            language = audio.get('language')
            if isinstance(language, str) and re.fullmatch(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8})?', language):
                clean['language'] = language
            entry['audio'] = clean
        result.append(entry)
    return {'sources': result}


def caption_records(folder, manifest):
    """Keep caption adjustments and measured samples, without image masks or font paths."""
    path = folder / 'caption-burn.json'
    report = optional_object(path, None)
    result = {'burned': report is not None, 'relaxed': [], 'resized': [], 'contrast': None}
    allowed = {'minimum gap', 'minimum duration', 'reading speed', 'single-word cues',
               'protected phrase breaks', 'maximum duration', 'line length for an unbreakable word'}

    def relaxation(name, value=None):
        if isinstance(name, str) and name in allowed:
            row = {'constraint': name}
            if finite(value) or isinstance(value, bool):
                row['allowed'] = value
            if row not in result['relaxed']:
                result['relaxed'].append(row)

    notes = manifest.get('notes', [])
    if not isinstance(notes, list):
        warn_file(folder / 'manifest.json', 'notes must be a list')
        notes = []
    for note in notes:
        if not isinstance(note, str):
            continue
        match = re.search(r'relaxed limits \((\d+(?:\.\d+)?) characters/s, '
                          r'(\d+(?:\.\d+)?) s minimum\)', note)
        if match:
            relaxation('reading speed', float(match.group(1)))
            relaxation('minimum duration', float(match.group(2)))
        match = re.search(r'caption segmentation relaxed ([^;]+)', note)
        if match:
            relaxation(match.group(1))
    overlays = object_rows(path, report, 'overlays') if isinstance(report, dict) else []
    ratios = []
    samples = 0
    for overlay in overlays:
        for row in object_rows(path, overlay, 'review') if 'review' in overlay else []:
            if row.get('rule') == 'segmentation relaxation':
                relaxation(row.get('constraint'), row.get('allowed'))
            if row.get('rule') == 'caption reduced to fit':
                cue, requested, used = row.get('cue'), row.get('requested_size_px'), row.get('used_size_px')
                if type(cue) is int and cue > 0 and finite(requested) and finite(used) and requested > 0 and used > 0:
                    result['resized'].append({'cue': cue, 'requested': requested, 'used': used})
                else:
                    warn_file(path, 'a caption size change is invalid')
        contrast = overlay.get('contrast')
        if isinstance(contrast, dict):
            minimum = contrast.get('minimum_ratio')
            if finite(minimum) and minimum > 0:
                ratios.append(minimum)
            entries = contrast.get('samples', [])
            if isinstance(entries, list):
                samples += sum(1 for row in entries if isinstance(row, dict)
                               and finite(row.get('ratio')) and row['ratio'] > 0)
            else:
                warn_file(path, 'caption contrast samples must be a list')
    if ratios:
        result['contrast'] = {'minimum': min(ratios), 'samples': samples}
    elif overlays:
        result['contrast'] = {'minimum': None, 'samples': samples}
    return result


def audio_master_record(folder, manifest):
    """Summarize measured master values without copying its paths or raw encoder logs."""
    path = folder / 'audio-master.json'
    report = optional_object(path, None)
    if report is None:
        return {'missing': True} if manifest.get('audio_master') else None
    result = {}
    mode = report.get('actual_mode')
    result['mode'] = mode.lower() if isinstance(mode, str) and mode.lower() in ('linear', 'dynamic') else None
    for key in ('target_lufs', 'target_tolerance_lu', 'requested_true_peak_dbtp'):
        if finite(report.get(key)):
            result[key] = report[key]
    source = report.get('target_source')
    if isinstance(source, str):
        result['target_source'] = ('working' if source.startswith('working') else
                                   'script' if source.startswith('film.md') else
                                   'specified' if source == '--master-target' else 'unknown')
    delivered = report.get('delivered_aac')
    delivered = delivered if isinstance(delivered, dict) else {}
    reencoded = report.get('simulated_aac_reencode')
    reencoded = reencoded if isinstance(reencoded, dict) else {}
    for dest, source_data, field in (('measured_lufs', delivered, 'integrated_lufs'),
                                     ('true_peak_dbtp', delivered, 'true_peak_dbtp'),
                                     ('reencode_peak_dbtp', reencoded, 'true_peak_dbtp')):
        result[dest] = source_data.get(field) if finite(source_data.get(field)) else None
    return result


def title_font_record(manifest):
    """Return only the title font's fallback flag and a safe family name."""
    font = manifest.get('title_font')
    if not isinstance(font, dict) or type(font.get('fallback')) is not bool:
        return None
    result = {'fallback': font['fallback']}
    face = font.get('face')
    if isinstance(face, list) and face and isinstance(face[0], str):
        family = face[0].strip()
        if re.fullmatch(r'[\w .+()\-]{1,60}', family):
            result['family'] = family
    return result


def source_map_file(root, alias, name):
    """Resolve a known source record without following a map link outside the project."""
    try:
        project_root = root.resolve()
        map_root = (root / 'map').resolve()
        path = (map_root / alias / name).resolve()
        if map_root.is_relative_to(project_root) and path.is_relative_to(map_root):
            return path
    except (OSError, ValueError, RuntimeError):
        pass
    warn_file(root / 'map' / alias / name, 'source record is outside the project')
    return None


def source_records(root, folder, sources):
    """Use the version's recorded stream, and label current-map transcript facts as current."""
    path = folder / 'edit.json'
    edit = optional_object(path, None)
    indexed = edit.get('sources', {}) if isinstance(edit, dict) else {}
    if not isinstance(indexed, dict):
        warn_file(path, 'sources must be an object')
        indexed = {}
    audio = edit.get('audio') if isinstance(edit, dict) else None
    audible = {item['src'] for item in audio if isinstance(item, dict) and isinstance(item.get('src'), str)} \
        if isinstance(audio, list) else None
    records = []
    for source in sources:
        alias = source['alias']
        selected = indexed.get(alias)
        row = {'alias': alias, 'role': source['role'], 'stream': None,
               'selection': 'not_used' if isinstance(edit, dict) and alias not in indexed else 'unrecorded'}
        if isinstance(selected, dict) and type(selected.get('audio_stream')) is int and selected['audio_stream'] >= 0:
            row.update(stream=selected['audio_stream'], selection='recorded')
        if audible is not None and alias in indexed:
            row['sound_used'] = alias in audible
        current_audio = source.get('audio') or {}
        if type(current_audio.get('index')) is int:
            row['map_stream'] = current_audio['index']
        for key in ('language', 'channels'):
            if key in current_audio and (row['selection'] != 'recorded' or row['stream'] == row.get('map_stream')):
                row[key] = current_audio[key]
        words_path = source_map_file(root, alias, 'words.json')
        words = optional_object(words_path, None) if words_path else None
        if isinstance(words, dict) and words.get('voice_detection') in ('on', 'off'):
            row['voice_detection'] = words['voice_detection']
        records.append(row)
    return records


def transcript_records(root, paper, sources, manifest):
    """Associate current-map prompts with overlapping source ranges in the compiled script."""
    known = {source['alias'] for source in sources}
    results = {}
    recognized = {'repeated_phrase', 'word_in_low_energy', 'uncovered_energy', 'uncovered_speech', 'low_confidence'}
    for alias in known:
        lines = [entry for entry in paper if entry.get('kind') == 'spoken' and entry.get('alias') == alias
                 and finite(entry.get('start')) and finite(entry.get('end'))]
        if not lines:
            continue
        path = source_map_file(root, alias, 'transcript-review.json')
        review = optional_object(path, None) if path else None
        prompts = object_rows(path, review, 'prompts') if isinstance(review, dict) else []
        for prompt in prompts:
            start, end, kind = prompt.get('start'), prompt.get('end'), prompt.get('kind')
            if (not isinstance(kind, str) or kind not in recognized or not finite(start)
                    or not finite(end) or start < 0 or end < start):
                warn_file(path, 'a transcript prompt has invalid timing or kind')
                continue
            for line in lines:
                if end >= line['start'] and start <= line['end']:
                    results.setdefault(str(line['line']), []).append({'kind': kind, 'origin': 'current_map'})
    notes = manifest.get('notes', [])
    for note in notes if isinstance(notes, list) else []:
        match = re.match(r'film\.md:(\d+):\s+([a-z]+_\d+) transcript review\b', note) if isinstance(note, str) else None
        if match and match.group(2) in known:
            line = match.group(1)
            if line in results:
                for entry in results[line]:
                    entry['recorded_in_version'] = True
            elif any(str(entry.get('line')) == line and entry.get('kind') == 'spoken' for entry in paper):
                results[line] = [{'kind': 'other', 'origin': 'version', 'recorded_in_version': True}]
    return results


def version_records(root, folder, manifest, paper, sources):
    """Select bounded production facts from the rendered version and current source map."""
    result = {'captions': caption_records(folder, manifest), 'audio_master': audio_master_record(folder, manifest),
              'title_font': title_font_record(manifest), 'sources': source_records(root, folder, sources)}
    speech_path = folder / 'qa' / 'speech-words.json'
    speech = optional_object(speech_path, None)
    if isinstance(speech, dict) and speech.get('voice_detection') == 'off':
        result['caption_speech_voice_detection'] = 'off'
    return result, transcript_records(root, paper, sources, manifest)


def safe_options(root, note):
    """Return only well-formed, local media options on agent questions."""
    if (note.get('kind') != 'question' or note.get('author') != 'agent'
            or not isinstance(note.get('options'), list)):
        return []
    result = []
    suffixes = ('.mp4', '.webm', '.mov', '.wav', '.mp3', '.m4a', '.ogg', '.jpg', '.png', '.webp')
    for item in note['options']:
        if not isinstance(item, dict):
            continue
        label, path = item.get('label'), item.get('path')
        if not isinstance(label, str) or not label.strip() or not isinstance(path, str) or not path:
            continue
        try:
            candidate = (root / path).resolve()
        except (OSError, ValueError):
            continue
        if not candidate.is_relative_to(root) or candidate.suffix.lower() not in suffixes:
            continue
        relative = candidate.relative_to(root)
        if not relative.parts or relative.parts[0].lower() == 'map' or any(p.startswith('.') for p in relative.parts):
            continue
        result.append({'label': label, 'path': relative.as_posix()})
    return result


def public_notes(root):
    """Keep malformed or ordinary-note options out of the page and file allowlist."""
    path = root / 'notes.json'
    data = optional_object(path, {'version': 1, 'notes': []})
    notes = object_rows(path, data, 'notes')
    valid = [note for note in notes if isinstance(note.get('text'), str) and finite(note.get('t'))]
    if len(valid) != len(notes):
        warn_file(path, 'a note has invalid text or timing')
    notes = valid
    return {'version': 1, 'notes': [dict(note, options=safe_options(root, note))
                                    for note in notes if isinstance(note, dict)]}


def room_scores(path):
    """Keep well-formed personal score records for display."""
    data = optional_object(path, {'version': 1, 'scores': {}})
    versions = data.get('scores')
    if not isinstance(versions, dict):
        warn_file(path, 'scores must be an object')
        return {'version': 1, 'scores': {}}
    result = {}
    for version, dimensions in versions.items():
        if not isinstance(version, str) or not isinstance(dimensions, dict):
            warn_file(path, 'a version score is invalid')
            continue
        result[version] = {key: value for key, value in dimensions.items() if isinstance(key, str)
                           and isinstance(value, dict) and type(value.get('score')) is int
                           and 0 <= value['score'] <= 10 and value.get('by') == 'person'}
        if len(result[version]) != len(dimensions):
            warn_file(path, 'a person score is invalid')
    return {'version': 1, 'scores': result}


def public_card_value(value, depth=0):
    """Keep scorecard display data while removing packet paths and fingerprints."""
    if depth > 24:
        return None
    if isinstance(value, dict):
        result = {}
        excluded = {'file', 'path', 'ref', 'packet', 'packet_id', 'mask_png_b64', 'measures'}
        for key, item in value.items():
            if (not isinstance(key, str) or key in excluded or key.endswith('sha256')
                    or public_detail(key) != key):
                continue
            result[key] = public_card_value(item, depth + 1)
        return result
    if isinstance(value, list):
        return [public_card_value(item, depth + 1) for item in value]
    if isinstance(value, str):
        return public_detail(value)
    if value is None or isinstance(value, bool) or finite(value):
        return value
    return None


def room_card(path):
    """Drop malformed scorecard rows rather than breaking unrelated room sections."""
    card = optional_object(path, None)
    if card is None:
        return None
    dimensions = object_rows(path, card, 'dimensions')
    clean = []
    for dimension in dimensions:
        if not isinstance(dimension.get('id'), str):
            warn_file(path, 'a scorecard dimension needs an id')
            continue
        row = dict(dimension)
        if row.get('score') is not None and not finite(row['score']):
            warn_file(path, 'a dimension score is invalid')
            row['score'] = None
        for key in ('evidence', 'assessments'):
            if key in row:
                row[key] = object_rows(path, row, key)
        clean.append(row)
    card = dict(card)
    card.pop('file', None)
    card['dimensions'] = clean
    for key in ('overall', 'groups', 'parent', 'validation'):
        if key in card and card[key] is not None and not isinstance(card[key], dict):
            warn_file(path, f'{key} must be an object')
            card[key] = {} if key != 'parent' else None
    if isinstance(card.get('groups'), dict):
        card['groups'] = {key: value for key, value in card['groups'].items() if isinstance(key, str) and key
                          and (value is None or finite(value))}
    for key in ('fixes', 'not_scored', 'review_prompts'):
        if key in card:
            card[key] = object_rows(path, card, key)
    media = card.get('media_sha256')
    visible = {key: card[key] for key in ('notice', 'overall', 'groups', 'dimensions', 'fixes', 'not_scored',
                                          'review_prompts', 'parent', 'validation') if key in card}
    visible = public_card_value(visible)
    if isinstance(media, str):
        visible['media_sha256'] = media
    return visible


def media_hash(path):
    """Hash the actual preview and reuse it only while its file identity is unchanged."""
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in HASH_CACHE:
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        HASH_CACHE.clear()
        HASH_CACHE[key] = digest.hexdigest()
    return HASH_CACHE[key]


def note_paragraphs(notes):
    """Join notes on consecutive lines of film.md into one paragraph, as a reader sees them; a README screenshot showed
    a two-sentence join note as four fragments."""
    merged = []
    for note in notes:
        last = merged[-1] if merged else None
        if last and note['line'] == last['end'] + 1 and note.get('section') == last.get('section'):
            last['text'] += ' ' + note['text']
            last['end'] = note['line']
        else:
            merged.append(dict(note, end=note['line']))
    return [{key: value for key, value in note.items() if key != 'end'} for note in merged]


def data_for(root):
    """Load a complete snapshot for static use and live polling."""
    version = project.current_version(root)
    manifests = {}
    for name in project.versions(root):
        candidate = root / 'cuts' / name
        if not all((candidate / name).is_file() for name in ('film.md', 'manifest.json', 'preview.mp4')):
            print(f'warning: skipping incomplete {name}', file=sys.stderr)
            continue
        try:
            manifest = read_json(candidate / 'manifest.json', {})
            if not isinstance(manifest, dict):
                raise ValueError('manifest must be an object')
            safe = {key: manifest[key] for key in ('version', 'parent', 'created', 'label', 'duration_s', 'size', 'fps')
                    if key in manifest}
            if 'duration_s' in safe and (not finite(safe['duration_s']) or safe['duration_s'] <= 0):
                warn_file(candidate / 'manifest.json', 'duration is invalid')
                safe.pop('duration_s')
            if 'size' in safe and (not isinstance(safe['size'], list) or len(safe['size']) != 2
                                   or not all(type(x) is int and x > 0 for x in safe['size'])):
                warn_file(candidate / 'manifest.json', 'size is invalid')
                safe.pop('size')
            for key in ('parent', 'created', 'label', 'fps'):
                if key in safe and safe[key] is not None and not isinstance(safe[key], (str, int, float)):
                    warn_file(candidate / 'manifest.json', f'{key} is invalid')
                    safe.pop(key)
            manifests[name] = safe
        except (OSError, ValueError):
            print(f'warning: skipping damaged manifest for {name}', file=sys.stderr)
    if version not in manifests:
        version = next(reversed(manifests), None)
    if not version:
        raise ValueError('no complete rendered version; render a version first')
    folder = root / 'cuts' / version
    manifest = manifests.get(version, {})
    parent = manifest.get('parent')
    if parent and parent not in manifests:
        print(f'warning: parent {parent} is incomplete or missing', file=sys.stderr)
        parent = None
    film = project.read_text(folder / 'film.md')
    previous = project.read_text(root / 'cuts' / parent / 'film.md') if parent and (
        root / 'cuts' / parent / 'film.md').is_file() else ''
    title, paper, changed, removed = paper_changes(film, previous)
    decisions = []
    path = root / 'decisions.jsonl'
    if path.exists():
        try:
            decision_lines = project.read_text(path).splitlines()
        except (OSError, UnicodeError):
            warn_file(path)
            decision_lines = []
        for number, line in enumerate(decision_lines, 1):
            if line.strip():
                try:
                    item = json.loads(line)
                    if not isinstance(item, dict):
                        raise ValueError('decision must be an object')
                    decisions.append(item)
                except (ValueError, RecursionError):
                    warn_file(path, f'skipping damaged line {number}')
    # The folder's name only: a full path would carry the person's user name into a page they might share.
    status, _ = room_status(root)
    checks = room_checks(folder / 'checks.json')
    checks['freshness'] = room_freshness(root, folder / 'checks.json')
    status['line'] = safe_status_line(root, version, status, checks)
    strip_path = folder / 'strip' / 'strip.json'
    strip = optional_object(strip_path, {})
    images = []
    strip_entries = strip.get('images', [])
    if not isinstance(strip_entries, list):
        warn_file(strip_path, 'images must be a list')
        strip_entries = []
    for item in strip_entries:
        name = item.get('image', '') if isinstance(item, dict) else Path(item).name if isinstance(item, str) else ''
        if not isinstance(name, str):
            warn_file(strip_path, 'an image name must be text')
            continue
        if re.fullmatch(r'strip-\d+\.jpg', name) and (folder / 'strip' / name).is_file():
            images.append((folder / 'strip' / name).relative_to(root).as_posix())
    card = room_card(folder / 'scorecard.json')
    card_state = 'unknown'
    if card and isinstance(card.get('media_sha256'), str):
        try:
            card_state = 'current' if card['media_sha256'] == media_hash(folder / 'preview.mp4') else 'outdated'
        except OSError:
            warn_file(folder / 'preview.mp4', 'could not verify the scorecard')
    if card:
        card.pop('media_sha256', None)
    source_data = public_sources(root)
    raw_manifest = optional_object(folder / 'manifest.json', {})
    details, transcript = version_records(root, folder, raw_manifest, paper, source_data['sources'])
    # The script's notes to readers (why each beat follows, what the viewer feels across a join) are shown in place.
    reader_notes = []
    film_settings, _ = cut.parse_film(film, cut.Problems(), notes=reader_notes)
    direction = {key: film_settings.get(key) for key in ('story', 'audience', 'takeaway') if film_settings.get(key)}
    return {'project': root.name, 'title': title, 'direction': direction, 'reader_notes': note_paragraphs(reader_notes),
            'current': version, 'status': status,
            'versions': manifests, 'film': film, 'lines': room_lines(folder / 'lines.json'),
            'checks': checks, 'strip': {'images': images},
            'sources': source_data, 'version_details': details, 'transcript_review': transcript,
            'notes': public_notes(root), 'decisions': decisions,
            'paper': paper, 'changes': changed, 'removed_lines': removed, 'strip_images': images,
            'scorecard': card, 'scorecard_state': card_state,
            'scores': room_scores(root / 'scores.json')}


def complete_snapshot(root):
    """Return no snapshot when there is no complete render; preserve other errors."""
    if not project.versions(root):
        return None
    try:
        return data_for(root)
    except ValueError as error:
        if str(error) == 'no complete rendered version; render a version first':
            return None
        raise


def page(root):
    """Build a self-contained page with script-safe embedded JSON."""
    data = json.dumps(data_for(root), ensure_ascii=True).replace('<', '\\u003c').replace('>', '\\u003e')
    return PAGE.replace('DATA_PLACEHOLDER', data)


def copy_fonts(folder):
    """Place the room's fonts beside the page, replacing a copy only when it differs; a missing font only warns,
    because the page falls back to system fonts."""
    target = folder / 'fonts'
    for name in FONTS:
        source = FONT_DIR / name
        destination = target / name
        try:
            body = source.read_bytes()
            if destination.is_file() and destination.read_bytes() == body:
                continue
            target.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name('.' + name + '.' + secrets.token_hex(4))
            temporary.write_bytes(body)
            os.replace(temporary, destination)
        except OSError as error:
            print(f'warning: font {name} not copied ({error.strerror or error}); the room uses system fonts',
                  file=sys.stderr)


def build(root):
    """Write the room atomically after updating project readiness."""
    snapshot = data_for(root)
    refresh_status(root, True, snapshot['current'])
    project.write_atomic(root / 'screening' / 'index.html', page(root))
    copy_fonts(root / 'screening')


def add_note(root, payload, kind='note'):
    """Add a person note or an agent question."""
    with project.file_lock(root / 'notes.json'):
        return _add_note(root, payload, kind)


def import_flask_notes(root, path):
    """Atomically import a validated Flask feedback list, preserving ids and drawn-frame paths."""
    source = project.load_json(path, None)
    if not isinstance(source, list):
        raise ValueError('Flask input must be a JSON list')
    incoming = []
    for number, row in enumerate(source, 1):
        if not isinstance(row, dict):
            raise ValueError(f'Flask note {number} must be an object')
        ident = row.get('flask_id', row.get('id'))
        text = row.get('text')
        author = row.get('author')
        version = row.get('version')
        moment = row.get('time', row.get('t'))
        if isinstance(moment, str):
            moment = project.parse_time(moment)
        drawing = row.get('drawn_frame', row.get('image_path'))
        if not isinstance(ident, str) or not ident.strip():
            raise ValueError(f'Flask note {number} needs its original id')
        if not isinstance(text, str) or not text.strip() or not isinstance(author, str) or not author.strip():
            raise ValueError(f'Flask note {number} needs text and author')
        if not isinstance(version, str) or not project.VERSION_NAME.fullmatch(version):
            raise ValueError(f'Flask note {number} needs its mapped local version, such as v003')
        if not (root / 'cuts' / version).is_dir():
            raise ValueError(f'Flask note {number}: local version {version} does not exist')
        if not finite(moment) or moment < 0:
            raise ValueError(f'Flask note {number} needs a non-negative time in seconds')
        if drawing is not None and (not isinstance(drawing, str) or not drawing.strip()):
            raise ValueError(f'Flask note {number}: drawn_frame must be a local path')
        if drawing is not None:
            frame = (root / drawing).resolve()
            if not frame.is_relative_to(root) or not frame.is_file():
                raise ValueError(f'Flask note {number}: save the drawn frame in the project first')
            drawing = frame.relative_to(root).as_posix()
        incoming.append({'flask_id': ident, 'text': text, 'author': author, 'version': version,
                         't': moment, 'drawn_frame': drawing})
    path_out = root / 'notes.json'
    project.refuse_overwriting_inputs([path_out], [path])
    with project.file_lock(path_out):
        notes = read_json(path_out, {'version': 1, 'notes': []})
        if not isinstance(notes, dict) or not isinstance(notes.get('notes'), list):
            raise ValueError('Notes could not be read. Ask your agent to repair notes.json.')
        if any(not isinstance(note, dict) for note in notes['notes']):
            raise ValueError('notes.json contains an invalid note')
        existing = {note.get('flask_id'): note for note in notes['notes'] if note.get('origin') == 'flask'}
        ids = {str(note.get('id')) for note in notes['notes']}
        added = 0
        skipped = 0
        changed = 0
        for row in incoming:
            if row['flask_id'] in existing:
                skipped += 1
                old = existing[row['flask_id']]
                if any(old.get(key) != row[key] for key in ('text', 'author', 'version', 't', 'drawn_frame')):
                    changed += 1
                continue
            number = 1
            while 'n' + str(number) in ids:
                number += 1
            ident = 'n' + str(number)
            note = {'id': ident, **row, 'line': None, 'word': None, 'origin': 'flask', 'kind': 'note',
                    'options': [], 'status': 'open', 'resolved_in': None, 'reply': None}
            notes['notes'].append(note)
            ids.add(ident)
            existing[row['flask_id']] = note
            added += 1
        if added:
            project.save_json(path_out, notes)
    if added:
        refresh_status(root)
    return added, skipped, changed


def moment_context(snapshot, moment):
    """Find the visible picture and the spoken line under it at an edit time."""
    items = snapshot.get('lines', {})
    items = items if isinstance(items, list) else items.get('lines', [])
    active = [item for item in items if item.get('start', 0) <= moment < item.get('end', 0)]
    parsed = {item['line']: item for item in snapshot.get('paper', [])}
    def kind(item):
        return item.get('kind') or parsed.get(item.get('line'), {}).get('kind')
    spoken = next((item for item in active if kind(item) == 'spoken'), None)
    # A graphic drawn over the picture (~ over, a pinned still) is not the picture under it.
    picture = next((item for item in reversed(active) if not item.get('overlay')
                    and (kind(item) in ('picture', 'cutaway', 'still', 'card')
                         or (kind(item) == 'title' and item.get('card')))),
                   None)
    pause = next((item for item in reversed(active) if kind(item) == 'pause'), None)
    visible = picture or spoken or pause
    def source(item):
        return item.get('source') or parsed.get(item.get('line'), {}).get('alias') if item else None
    word = None
    if spoken:
        words = spoken.get('words', [])
        word = next((item.get('id') for item in words if isinstance(item, dict)
                     and item.get('start', -1) <= moment < item.get('end', -1)), None)
        if word is None and len(words) == 1 and isinstance(words[0], str):
            word = words[0]
    return {'line': visible.get('line') if visible else None, 'source': source(visible), 'word': word,
            'spoken_line': spoken.get('line') if spoken else None, 'spoken_source': source(spoken),
            'picture_line': picture.get('line') if picture else None, 'picture_source': source(picture)}


def _add_note(root, payload, kind):
    """Append a note with the notes lock held."""
    notes = read_json(root / 'notes.json', {'version': 1, 'notes': []})
    if not isinstance(notes, dict) or not isinstance(notes.get('notes', []), list):
        raise ValueError('Notes could not be read. Ask your agent to repair notes.json.')
    notes.setdefault('notes', [])
    ids = {str(item.get('id')) for item in notes['notes'] if isinstance(item, dict)}
    number = 1
    while 'n' + str(number) in ids:
        number += 1
    snapshot = complete_snapshot(root)
    version = snapshot['current'] if snapshot else None
    text = payload.get('text')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Enter a note or question as text.')
    text = text.strip()
    t = payload.get('t')
    if not finite(t) or t < 0:
        raise ValueError('Choose a time inside the film.')
    if snapshot:
        duration = snapshot['versions'][version].get('duration_s')
        if not finite(duration) or t >= duration:
            raise ValueError('Choose a time inside the film.')
    if payload.get('version') and payload['version'] != version:
        raise ValueError('the current version changed; review the moment again before saving')
    context = moment_context(snapshot, t) if snapshot and kind == 'note' else {
        'line': payload.get('line'), 'word': payload.get('word')}
    supplied = payload.get('options', [])
    options = safe_options(root, {'kind': kind, 'author': 'agent' if kind == 'question' else 'person',
                                  'options': supplied})
    if kind == 'question' and (not isinstance(supplied, list) or len(options) != len(supplied)):
        raise ValueError('question options must have a label and a local media path')
    note = {'id': 'n' + str(number), 'version': version, 't': t, **context,
            'author': 'agent' if kind == 'question' else 'person',
            'origin': 'agent' if kind == 'question' else 'room',
            'kind': kind, 'text': text, 'options': options, 'status': 'open',
            'resolved_in': None, 'reply': None}
    notes['notes'].append(note)
    project.save_json(root / 'notes.json', notes)
    refresh_status(root)
    return note


def decision(root, category, subject, value, rejected, who):
    """Append a decision through project.py."""
    if (category not in ('story', 'picture', 'sound', 'captions', 'delivery')
            or who not in ('person', 'agent', 'reviewer')):
        raise ValueError('category must be story, picture, sound, captions or delivery; '
                         'by must be person, agent or reviewer')
    snapshot = complete_snapshot(root)
    row = {'at': project.now(), 'by': who, 'category': category, 'subject': subject, 'decision': value,
           'rejected': rejected, 'version': snapshot['current'] if snapshot else None}
    project.append_jsonl(root / 'decisions.jsonl', row)
    return row


def save_person_score(root, data):
    """Record a person's dimension score without modifying the agent's scorecard."""
    snapshot = data_for(root)
    version = snapshot['current']
    if data.get('version') and data['version'] != version:
        raise ValueError('the current version changed; review the score again')
    dimension = data.get('dimension')
    score = data.get('score')
    card = snapshot.get('scorecard') or {}
    if snapshot.get('scorecard_state') == 'outdated':
        raise ValueError('This scorecard is out of date. Ask your agent to grade this version again.')
    valid = {item.get('id') for item in card.get('dimensions', []) if isinstance(item, dict)}
    if dimension not in valid or type(score) is not int or not 0 <= score <= 10:
        raise ValueError('choose a listed dimension and a whole-number score from 0 to 10')
    path = root / 'scores.json'
    with project.file_lock(path):
        scores = read_json(path, {'version': 1, 'scores': {}})
        if not isinstance(scores, dict) or not isinstance(scores.get('scores'), dict):
            raise ValueError('Scores could not be read. Ask your agent to repair scores.json.')
        if version in scores['scores'] and not isinstance(scores['scores'][version], dict):
            raise ValueError('Scores could not be read. Ask your agent to repair scores.json.')
        scores.setdefault('scores', {}).setdefault(version, {})[dimension] = {
            'score': score, 'by': 'person', 'at': project.now()}
        project.save_json(path, scores)
    command = [sys.executable, '-I', str(Path(__file__).with_name('grade.py')), 'scores', str(root),
               '--version', version]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        print('warning: grade.py scores could not run: ' + str(error), file=sys.stderr)
        return {'ok': True, 'grade': 'error', 'message': 'Your score was saved, but the scorecard could not update.'}
    if result.returncode not in (0, 1):
        print('warning: grade.py scores: ' + (result.stderr or result.stdout).strip(), file=sys.stderr)
        return {'ok': True, 'grade': 'error', 'message': 'Your score was saved, but the scorecard could not update.'}
    return {'ok': True, 'grade': 'incomplete' if result.returncode == 1 else 'updated'}


def apply_api(root, endpoint, data):
    """Apply one serialised live edit."""
    with LOCK:
        if endpoint == 'notes':
            return add_note(root, data)
        if endpoint == 'score':
            return save_person_score(root, data)
        if endpoint == 'answer':
            with project.file_lock(root / 'notes.json'):
                notes = read_json(root / 'notes.json', {'version': 1, 'notes': []})
                if not isinstance(notes, dict) or not isinstance(notes.get('notes', []), list):
                    raise ValueError('Notes could not be read. Ask your agent to repair notes.json.')
                note = next((n for n in notes.get('notes', []) if isinstance(n, dict)
                             and n.get('id') == data.get('id')), None)
                if not note or note.get('kind') != 'question':
                    raise ValueError('That question could not be found.')
                answer = data.get('answer')
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError('Enter an answer as text.')
                note['answer'] = answer.strip()
                project.save_json(root / 'notes.json', notes)
        elif endpoint in ('review', 'approve'):
            key = 'approved' if endpoint == 'approve' else data.get('kind')
            if not isinstance(key, str):
                raise ValueError('Choose a review item.')
            version = data_for(root)['current']
            if data.get('version') and data['version'] != version:
                raise ValueError('The version changed. Review the current version first.')
            checks = room_checks(root / 'cuts' / version / 'checks.json')
            allowed = {review_key(item) for item in checks.get('items', [])} - {None}
            if key != 'approved' and key not in allowed | {'watched_muted', 'heard'}:
                raise ValueError('unknown review')
            # The room plays the version's preview, so the review names that file by its SHA-256.
            _, already = project.record_review(root, version, key)
            if already:
                return {'ok': True, 'already': True}
            decision(root, 'delivery', key, key, [], 'person')
        else:
            raise ValueError('unknown endpoint')
        refresh_status(root)
        return {'ok': True}


def check_request_depth(value):
    """Reject deeply nested input before later handlers traverse it."""
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > 32:
            raise ValueError('The request is too deeply nested.')
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)


def make_handler(root, token, instance=None):
    """Create a loopback-only, token-protected project file handler."""
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def host_matches(self):
            """The browser must name this room's own loopback address (this also blocks DNS rebinding)."""
            valid_hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
            return self.headers.get('Host', '') in valid_hosts

        def refuse(self):
            """Explain a refused request: a different host (a forwarded port, a container) or an old link."""
            if not self.host_matches():
                address = f'127.0.0.1:{self.server.server_port}'
                self.respond(403, (f'This Screening Room answers only at {address}, on the machine running it. '
                                   'This request named another address, as a forwarded port or a container does. '
                                   'Open the link the agent printed on that machine, or forward the port so this '
                                   f'browser opens the room as {address} too.').encode())
                return
            self.respond(403, b"This link has expired; reopen the room from the agent's link.")

        def authorised(self):
            if not self.host_matches():
                return False
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            supplied_query = query.get('t', [''])[0]
            self.token_query = supplied_query.isascii() and secrets.compare_digest(supplied_query, token)
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
            except http.cookies.CookieError:
                return False
            name = 'lf_token_' + str(self.server.server_port)
            supplied = supplied_query or (cookie[name].value if name in cookie else '')
            return supplied.isascii() and secrets.compare_digest(supplied, token)

        def respond(self, code, body, content='text/plain', extra=None):
            self.send_response(code)
            self.send_header('Content-Type', content)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            if instance:
                self.send_header('X-Legible-Film-Instance', instance)
            if code in (200, 206) and getattr(self, 'token_query', False):
                self.send_header('Set-Cookie', 'lf_token_' + str(self.server.server_port) + '=' + token
                                 + '; HttpOnly; SameSite=Strict; Path=/')
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.authorised():
                self.refuse()
                return
            raw = urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
            if raw == '/favicon.ico':
                icon = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
                        b'<rect width="64" height="64" rx="10" fill="#3b5cf6"/>'
                        b'<path d="M25 17v30l24-15z" fill="white"/></svg>')
                self.respond(200, icon, 'image/svg+xml')
                return
            if raw == '/api/status':
                try:
                    with LOCK:
                        body = json.dumps(data_for(root), ensure_ascii=True).encode()
                    self.respond(200, body, 'application/json')
                except (ValueError, OSError, json.JSONDecodeError) as error:
                    self.respond(500, str(error).encode())
                return
            parts = raw.replace('\\', '/').split('/')
            if '..' in parts:
                self.respond(403, b'Forbidden')
                return
            allowed = raw == '/screening/index.html' or bool(re.fullmatch(
                r'/cuts/v\d+/(?:preview\.mp4|strip/strip-\d+\.jpg)', raw)) or raw in (
                '/screening/fonts/' + name for name in FONTS)
            if not allowed:
                notes = public_notes(root)
                options = [option.get('path', '') for note in notes.get('notes', [])
                           for option in note.get('options', [])]
                allowed = raw.lstrip('/') in options and Path(raw).suffix.lower() in (
                    '.mp4', '.webm', '.mov', '.wav', '.mp3', '.m4a', '.ogg', '.jpg', '.png', '.webp')
            if not allowed:
                self.respond(404, b'Not found')
                return
            target = (root / raw.lstrip('/')).resolve()
            if not target.is_relative_to(root) or not target.is_file():
                self.respond(404, b'Not found')
                return
            size = target.stat().st_size
            start, end, code = 0, size - 1, 200
            requested = self.headers.get('Range')
            if requested:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
                if not match or not any(match.groups()) or size == 0:
                    self.respond(416, b'', extra={'Content-Range': 'bytes */' + str(size)})
                    return
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), end) if right else end
                else:
                    start = max(0, size - int(right))
                if start > end or start >= size:
                    self.respond(416, b'', extra={'Content-Range': 'bytes */' + str(size)})
                    return
                code = 206
            self.send_response(code)
            kind = 'font/woff2' if target.suffix == '.woff2' else mimetypes.guess_type(str(target))[0]
            self.send_header('Content-Type', kind or 'application/octet-stream')
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Cache-Control', 'no-store')
            if self.token_query:
                self.send_header('Set-Cookie', 'lf_token_' + str(self.server.server_port) + '=' + token
                                 + '; HttpOnly; SameSite=Strict; Path=/')
            if code == 206:
                self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.end_headers()
            with target.open('rb') as stream:
                stream.seek(start)
                remaining = end - start + 1
                while remaining:
                    chunk = stream.read(min(remaining, 1024 * 1024))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_POST(self):
            if not self.authorised():
                self.refuse()
                return
            # Same-origin browser requests only; prevent cross-origin form submissions.
            origin = self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{self.server.server_port}',
                                         f'http://localhost:{self.server.server_port}'}:
                self.respond(403, b'Forbidden')
                return
            path = urllib.parse.urlsplit(self.path).path
            if path not in ('/api/notes', '/api/answer', '/api/review', '/api/approve', '/api/score'):
                self.respond(404, b'Not found')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length <= 0 or length > 65536 or self.headers.get_content_type() != 'application/json':
                    raise ValueError('expected a small JSON request')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('expected a JSON object')
                check_request_depth(data)
                result = apply_api(root, path.rsplit('/', 1)[1], data)
                self.respond(200, json.dumps(result).encode(), 'application/json')
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                self.respond(400, b'Enter a valid, reasonably sized JSON request.')
            except ValueError as error:
                self.respond(400, str(error).encode())
            except (TypeError, AttributeError, KeyError):
                self.respond(400, b'The request contains an invalid value.')
            except OSError:
                self.respond(400, b'Could not save. Ask your agent to inspect the project.')

        def log_message(self, fmt, *args):
            pass
    return Handler


class RoomServer(ThreadingHTTPServer):
    """Ignore normal browser disconnects while preserving unexpected server errors."""

    def server_bind(self):
        """Bind without HTTPServer's reverse-DNS lookup of its own host (socket.getfqdn), which can take tens of
        seconds on macOS; the room only ever binds to 127.0.0.1."""
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    def handle_error(self, request, client_address):
        error = sys.exc_info()[1]
        if isinstance(error, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout)):
            return
        super().handle_error(request, client_address)


def pid_alive(pid):
    """Check a discovery PID without sending it a signal, including on Windows."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, OverflowError, OSError):
        return False


def interrupt_server(signum, frame):
    """Allow normal termination signals to run the server's cleanup."""
    raise KeyboardInterrupt


def discovery_alive(info):
    """Confirm the PID and loopback server identify the recorded room without storing its token."""
    if not isinstance(info, dict) or not pid_alive(info.get('pid')):
        return False
    try:
        legacy_url = info.get('url')
        if legacy_url:
            url = urllib.parse.urlsplit(legacy_url)
            if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or not url.port
                    or url.path != '/screening/index.html' or not urllib.parse.parse_qs(url.query).get('t')):
                return False
            port = url.port
            path = url.path + '?' + url.query
        else:
            port = info.get('port')
            if type(port) is not int or not 1 <= port <= 65535:
                return False
            path = '/screening/index.html'
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=1)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            if legacy_url:
                return response.status == 200
            if info.get('instance'):
                return response.status == 403 and response.getheader('X-Legible-Film-Instance') == info['instance']
            return (info.get('legacy') is True and response.status == 403
                    and b"This link has expired; reopen the room" in response.read())
        finally:
            connection.close()
    except (OSError, ValueError, TypeError, http.client.HTTPException):
        return False


def serve(root, port, open_browser):
    """Print the private link, serve until interrupted and remove our token-free discovery record."""
    build(root)
    token = secrets.token_urlsafe(32)
    instance = secrets.token_hex(16)
    server = None
    info = root / 'screening' / 'server.json'
    try:
        with project.file_lock(info, timeout=5):
            prior = optional_object(info, {})
            if prior and discovery_alive(prior):
                if prior.get('url'):
                    old_port = prior.get('port') or urllib.parse.urlsplit(prior['url']).port
                    project.save_json(info, {'pid': prior['pid'], 'port': old_port, 'legacy': True})
                raise ValueError('A Screening Room is already running. Reopen the link in the original command output.')
            if prior:
                print('warning: replacing a stale Screening Room server record', file=sys.stderr)
            server = RoomServer(('127.0.0.1', port), make_handler(root, token, instance))
            project.save_json(info, {'pid': os.getpid(), 'port': server.server_port, 'instance': instance})
    except TimeoutError as error:
        if server:
            server.server_close()
        holder = info.with_name('.' + info.name + '.lock')
        content = holder.read_text(encoding='ascii', errors='replace').strip() if holder.exists() else ''
        message = f'{error} (held by: {content or "unknown"}); if no Screening Room is running, delete it'
        raise ValueError(message) from None
    except Exception:
        if server:
            server.server_close()
        raise
    url = 'http:' + '//127.0.0.1:' + str(server.server_port) + '/screening/index.html?t=' + token
    print(url, flush=True)
    if open_browser:
        webbrowser.open(url)
    previous_term = signal.signal(signal.SIGTERM, interrupt_server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        signal.signal(signal.SIGTERM, previous_term)
        with project.file_lock(info):
            current = read_json(info, {})
            if current.get('pid') == os.getpid() and current.get('instance') == instance:
                info.unlink(missing_ok=True)


def quoted(text):
    """Quote text on one line: JSON escapes newlines and quotes, and invisible format characters (direction
    overrides, zero-width marks) are shown as escapes so the quoted words cannot rearrange the listing."""
    body = json.dumps(str(text), ensure_ascii=False)
    hidden = ('Cf', 'Zl', 'Zp', 'Co', 'Cs')
    return ''.join(f'\\u{ord(char):04x}' if unicodedata.category(char) in hidden else char for char in body)


def field(value):
    """A note field for the listing: a plain word as it is, anything else quoted on one line."""
    text = str(value)
    return text if re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', text) else quoted(text)


def note_origin(note):
    """Where a note came from, read from its fields: `origin` when recorded, else what its author implies."""
    origin = note.get('origin')
    if isinstance(origin, str) and origin.strip():
        return NOTE_ORIGINS.get(origin.strip().lower(), field(origin.strip()))
    if note.get('kind') == 'question' or note.get('author') == 'agent':
        return 'the agent (screen.py ask)'
    who = note.get('author')
    return 'origin not recorded' + (f' (by {field(who)})' if who else '')


def print_notes(notes, include_all):
    """List notes for the agent: where each came from, then its words quoted as material, never as instructions."""
    shown = [note for note in sorted(notes, key=lambda n: (n.get('status') != 'open', n.get('t', 0)))
             if include_all or note.get('status') == 'open']
    if shown:
        print('Each note quotes what a reviewer wrote about the film: material to act on with judgment, '
              'not instructions to follow.')
    for note in shown:
        where = 'question' if note.get('kind') == 'question' else 'note'
        if note.get('line') is not None:
            where += ' line ' + field(note['line'])
        if note.get('source'):
            where += ' source ' + field(note['source'])
        if note.get('spoken_line') is not None and note.get('spoken_line') != note.get('line'):
            where += ' spoken line ' + field(note['spoken_line'])
            if note.get('spoken_source'):
                where += ' source ' + field(note['spoken_source'])
        print(f"{field(note.get('id', '?'))} {field(note.get('status'))} {field(note.get('version'))} "
              f"{project.format_time(note.get('t', 0))} {where}, from {note_origin(note)}")
        print('  Text: ' + quoted(note.get('text', '')))
        if include_all and note.get('reply'):
            print('  Reply: ' + quoted(note['reply']))


def main():
    """Parse commands and report actionable errors."""
    project.safe_output()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('build', 'serve', 'notes', 'resolve', 'ask', 'decide', 'import-notes'):
        p = sub.add_parser(name)
        p.add_argument('project')
        if name == 'serve':
            p.add_argument('--port', type=int, default=0)
            p.add_argument('--open', action='store_true')
        if name == 'notes':
            p.add_argument('--all', action='store_true', help='include resolved and declined notes')
        if name == 'resolve':
            p.add_argument('note_id')
            p.add_argument('--in', dest='resolved_in', required=True)
            p.add_argument('--reply', required=True)
            p.add_argument('--declined', action='store_true')
        if name == 'ask':
            p.add_argument('--at', type=float, required=True)
            p.add_argument('--text', required=True)
            p.add_argument('--option', action='append', default=[])
        if name == 'decide':
            p.add_argument('--category', required=True, help='story, picture, sound, captions or delivery')
            p.add_argument('--subject', required=True, help='what the decision concerns')
            p.add_argument('--decision', required=True, help='the chosen decision')
            p.add_argument('--by', required=True, help='person, agent or reviewer')
            p.add_argument('--rejected', action='append', default=[])
        if name == 'import-notes':
            p.add_argument('file')
            p.add_argument('--origin', required=True, choices=('flask',))
    args = parser.parse_args()
    try:
        root = project.find_project(args.project)
        if root is None:
            raise ValueError('project not found')
        root = root.resolve()
        if args.command == 'build':
            build(root)
            print(root / 'screening' / 'index.html')
        elif args.command == 'serve':
            serve(root, args.port, args.open)
        elif args.command == 'notes':
            notes = public_notes(root)['notes']
            print_notes(notes, args.all)
            return 1 if any(note.get('status') == 'open' for note in notes) else 0
        elif args.command == 'resolve':
            with project.file_lock(root / 'notes.json'):
                notes = read_json(root / 'notes.json', {'notes': []})
                note = next((n for n in notes['notes'] if n.get('id') == args.note_id), None)
                snapshot = complete_snapshot(root)
                if not note or not snapshot or args.resolved_in not in snapshot['versions']:
                    raise ValueError('note or complete resolution version not found')
                note.update(status='declined' if args.declined else 'done', resolved_in=args.resolved_in,
                            reply=args.reply)
                project.save_json(root / 'notes.json', notes)
            refresh_status(root)
            print(f"{note['id']} {note['status']} in {args.resolved_in}: {args.reply}")
        elif args.command == 'ask':
            options = []
            for option in args.option:
                label, sep, path = option.partition('=')
                candidate = (root / path).resolve()
                if not sep or not label or not candidate.is_relative_to(root) or not candidate.is_file():
                    raise ValueError('each option must be LABEL=existing project-relative file')
                options.append({'label': label, 'path': candidate.relative_to(root).as_posix()})
            note = add_note(root, {'t': args.at, 'text': args.text, 'options': options}, 'question')
            print(note['id'] + (' (no complete version yet)' if note['version'] is None else ''))
        elif args.command == 'decide':
            row = decision(root, args.category, args.subject, args.decision, args.rejected, args.by)
            refresh_status(root)
            if row['version'] is None:
                print('Decision recorded; no complete version yet.')
        elif args.command == 'import-notes':
            added, skipped, changed = import_flask_notes(root, args.file)
            print(f'Flask notes: {added} imported, {skipped} already present')
            if changed:
                print(f'{changed} existing Flask note(s) differ from the import; inspect them, nothing was replaced')
                return 1
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print('cannot run: ' + str(error), file=sys.stderr)
        return 2


PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='10' fill='%233b5cf6'/%3E%3Cpath d='M25 17v30l24-15z' fill='white'/%3E%3C/svg%3E">
<title>Screening Room</title>
<style>
/* Fonts ship with the skill (assets/fonts, SIL Open Font License); build copies them beside this page. */
@font-face{font-family:'Inter';font-style:normal;font-weight:400;font-display:swap;
src:url(fonts/Inter-Latin-400.woff2) format('woff2');unicode-range:
U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,
U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Inter';font-style:normal;font-weight:500;font-display:swap;
src:url(fonts/Inter-Latin-500.woff2) format('woff2');unicode-range:
U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,
U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Inter';font-style:normal;font-weight:600;font-display:swap;
src:url(fonts/Inter-Latin-600.woff2) format('woff2');unicode-range:
U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,
U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'IBM Plex Mono';font-style:normal;font-weight:400;font-display:swap;
src:url(fonts/IBMPlexMono-Latin-400.woff2) format('woff2');unicode-range:
U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,
U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
/* Tokens (values adapted from Rune, MIT; see NOTICE): neutral layers, text levels, hairlines, one blue accent, states.
   Every rule below reads these, so the look changes here. Values marked * are darker or lighter steps than the
   theme's own token so the text reaches 4.5:1. */
:root{color-scheme:light dark;
--bg:#ffffff;--surface:#fafafa;--surface-2:#f2f2f2;--surface-3:#eeeeee;--surface-button:#ffffff;
--hover:#0000000a;--pressed:#00000014;--video:#080808;
--text:#161616;--text-2:#5c5c5c;--text-3:#6b6b6b;--on-accent:#ffffff;
--border:#0000001a;--border-muted:#00000014;--border-strong:#00000033;
--accent:#3b5cf6;--accent-hover:#0b34f4;--accent-text:#3b5cf6;--accent-soft:#ecf1fe;--accent-soft-text:#3250df;
--accent-line:#c3d4fd;--focus:#3b5cf6;
--pass:#1d783c;--pass-bg:#e7f9ea;--pass-line:#b8e9c1;
--look:#68552b;--look-bg:#fefaec;--look-line:#f7e5b5;
--fail:#b82d35;--fail-bg:#fceceb;--fail-line:#f2bbb7;
--you:#3250df;--you-bg:#ecf1fe;--you-line:#c3d4fd;
--skip:#6b6b6b;--skip-bg:#f2f2f2;--skip-line:#0000001a;
--elev-button:#0000001a 0 1px 1.5px 0,#00000024 0 0 0 .5px;
--role-interview:#7698fd;--role-broll:#49c970;--role-screen:#8271f8;--role-music:#e7af36;--role-vo:#00abcf;
--role-still:#aeaeae;--role-sfx:#ff8648;--role-other:#808080;
--font-text:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
--font-mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace;
--size-xs:12px;--size-sm:13px;--size-base:14px;--size-lg:16px;--size-xl:20px;
--leading-tight:12px;--leading-compact:16px;--leading-base:20px;--leading-xl:28px;
--weight-regular:400;--weight-medium:500;--weight-strong:600;--track-tight:-.16px;--track-tightest:-.32px;
--radius-xs:2px;--radius-sm:4px;--radius-md:6px;--radius-lg:8px;--radius-xl:10px;
--space-1:4px;--space-2:8px;--space-3:12px;--space-4:16px;--space-5:20px;--space-6:24px;--space-8:32px;
--space-10:40px;--container:1280px;--time-column:60px}
@media(prefers-color-scheme:dark){:root{
--bg:#161616;--surface:#242424;--surface-2:#2e2e2e;--surface-3:#3a3a3a;--surface-button:#ffffff0f;
--hover:#ffffff0f;--pressed:#ffffff1a;
--text:#fafafa;--text-2:#aeaeae;--text-3:#9a9a9a;--on-accent:#ffffff;
--border:#ffffff1a;--border-muted:#ffffff14;--border-strong:#ffffff33;
--accent:#3b5cf6;--accent-hover:#3250df;--accent-text:#a2bcff;--accent-soft:#021945;--accent-soft-text:#a2bcff;
--accent-line:#2c47c8;--focus:#a2bcff;
--pass:#6bd586;--pass-bg:#14361d;--pass-line:#1d783c;
--look:#f2cf76;--look-bg:#4b4025;--look-line:#ac8833;
--fail:#f17471;--fail-bg:#461516;--fail-line:#97252b;
--you:#a2bcff;--you-bg:#021945;--you-line:#2c47c8;
--skip:#9a9a9a;--skip-bg:#2e2e2e;--skip-line:#ffffff1a;
--elev-button:#00000066 0 1px 2px 0,#ffffff33 0 0 0 .5px,#ffffff1a 0 -.5px 0 0}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:var(--weight-regular)
var(--size-base)/var(--leading-base) var(--font-text);-webkit-font-smoothing:antialiased}
main{max-width:var(--container);margin:auto;padding:var(--space-8) var(--space-8) var(--space-10)}h1,h2,h3,p{margin:0}
h1{font-size:var(--size-xl);line-height:var(--leading-xl);font-weight:var(--weight-strong);
letter-spacing:var(--track-tightest)}h2{font-size:var(--size-base);line-height:var(--leading-base);
font-weight:var(--weight-strong);letter-spacing:var(--track-tight)}h3{font-weight:var(--weight-strong)}
button{font:inherit;color:inherit;cursor:pointer}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
button,.pill{border:0;background:var(--surface-button);box-shadow:var(--elev-button);border-radius:var(--radius-md);
padding:6px var(--space-3);font-size:var(--size-sm);line-height:var(--leading-base);font-weight:var(--weight-medium)}
button:hover{background-image:linear-gradient(var(--hover),var(--hover))}
button:active{background-image:linear-gradient(var(--pressed),var(--pressed))}
button:disabled{cursor:default;color:var(--text-3);background:var(--surface-2);background-image:none;box-shadow:none}
.eyebrow,.section-label{font-size:var(--size-xs);line-height:var(--leading-compact);font-weight:var(--weight-medium);
letter-spacing:.06em;text-transform:uppercase;color:var(--text-2)}.head-top{display:flex;align-items:start;
justify-content:space-between;gap:var(--space-4);margin-top:var(--space-2)}.title-row{display:flex;
align-items:baseline;flex-wrap:wrap;gap:var(--space-3)}.subtitle,.muted,.meta{color:var(--text-2)}
.subtitle{font:var(--size-xs)/var(--leading-compact) var(--font-mono)}.badge{font:var(--size-xs)/var(--leading-compact)
var(--font-mono);white-space:nowrap;background:var(--accent-soft);color:var(--accent-soft-text);
border:1px solid var(--accent-line);border-radius:var(--radius-sm);padding:3px var(--space-2)}
.readiness{margin:var(--space-4) 0 var(--space-1);color:var(--text-2)}.readiness strong{color:var(--text);
font-weight:var(--weight-medium)}.next-step{margin:0 0 var(--space-4);color:var(--text);font-size:var(--size-sm)}
.stages,.legend,.controls,.option-row,.versions{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-2)}
.stage{font-size:var(--size-xs);line-height:var(--leading-compact);text-transform:capitalize;
border:1px solid var(--border);border-radius:var(--radius-sm);padding:3px var(--space-2);color:var(--text-2)}
.stage.done{background:var(--surface-2);color:var(--text);border-color:transparent}.stage.now{
border-color:var(--accent-line);background:var(--accent-soft);color:var(--accent-soft-text);
font-weight:var(--weight-medium)}.stage.skipped{border-style:dashed;color:var(--text-3)}.grid{display:grid;
grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:var(--space-4);margin:var(--space-6) 0}.card{min-width:0;
background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);overflow:hidden}
.card-head{padding:var(--space-3) var(--space-4) 10px;display:flex;justify-content:space-between;align-items:baseline;
gap:var(--space-2)}.card-body{padding:0 var(--space-4) var(--space-4)}
.player-wrap{background:var(--video);display:flex;justify-content:center;align-items:center}video{display:block;
width:100%;max-height:55vh;background:var(--video);object-fit:contain}.player-info{display:flex;
justify-content:space-between;gap:10px;padding:var(--space-3) var(--space-4) 0;font-size:var(--size-sm);
color:var(--text-2)}#clock{font-family:var(--font-mono);color:var(--text)}.controls{padding:var(--space-3)
var(--space-4) var(--space-4)}
.primary{background:var(--accent);color:var(--on-accent);box-shadow:none}.primary:hover{background:var(--accent-hover)}
.paper{max-height:55vh;overflow-y:auto;padding:0 var(--space-2) var(--space-3)}.section-label{margin:var(--space-4)
var(--space-2) var(--space-1)}.line{display:grid;grid-template-columns:var(--time-column) minmax(0,1fr);
gap:var(--space-2);padding:var(--space-2);border-radius:var(--radius-md);cursor:pointer}
.line[data-line]:hover{background:var(--hover)}.line.active,.line.active:hover{background:var(--accent-soft)}
.line.cutaway{margin-left:18px}.reader-note{margin:2px var(--space-2) var(--space-2)
calc(var(--time-column) + var(--space-4));font-size:var(--size-sm);line-height:var(--leading-base);
color:var(--text-2);overflow-wrap:anywhere;border-left:2px solid var(--border-strong);padding-left:var(--space-2)}
.time{font:var(--size-xs)/var(--leading-base) var(--font-mono);font-variant-numeric:tabular-nums;color:var(--text-2)}
.line-main{min-width:0;overflow-wrap:anywhere;color:var(--text-2)}.line-main i{font-style:normal;color:var(--text)}
.line.active .line-main i{color:var(--text)}.meta{font-size:var(--size-xs);line-height:var(--leading-compact);
display:block;margin-top:var(--space-1);overflow-wrap:anywhere}.tag{color:var(--accent-soft-text);
font-size:var(--size-xs);font-weight:var(--weight-medium);display:inline-block;margin-left:var(--space-2)}
.over{font-size:var(--size-xs);text-transform:uppercase;letter-spacing:.04em;color:var(--accent-soft-text);
font-weight:var(--weight-medium);margin-right:6px}del{color:var(--text-3)}.timeline{padding:var(--space-4);
margin:0 0 var(--space-6)}.timeline-head{display:flex;justify-content:space-between;gap:var(--space-3);
align-items:center;flex-wrap:wrap}.legend{font-size:var(--size-xs);color:var(--text-2);gap:var(--space-3)}
.legend span{display:inline-flex;align-items:center;gap:6px}.swatch{width:8px;height:8px;border-radius:var(--radius-xs);
display:inline-block}.strip{display:flex;position:relative;height:38px;margin-top:var(--space-4)}
.block{min-width:2px;position:absolute;height:26px;border:1px solid var(--surface);border-radius:var(--radius-xs);
cursor:pointer}.block:hover{filter:brightness(1.08)}
.block.changed{outline:2px solid var(--text);outline-offset:-2px}.dot{position:absolute;top:5px;width:7px;height:7px;
border-radius:50%;background:var(--text);box-shadow:0 0 0 1.5px var(--surface)}.playhead{position:absolute;
top:-4px;bottom:-4px;border-left:2px solid var(--text);pointer-events:none}.stack{margin:0 0 var(--space-6)}
.item{border-top:1px solid var(--border);padding:var(--space-3) 0}.check-row{display:grid;
grid-template-columns:22px minmax(0,1fr) auto;gap:var(--space-2);align-items:start}
.check-icon{font-size:var(--size-lg);line-height:var(--leading-base);font-weight:var(--weight-strong);text-align:center}
.pass{color:var(--pass)}.look{color:var(--look)}.fail{color:var(--fail)}.you{color:var(--you)}.skip{color:var(--skip)}
.detail{display:block;color:var(--text-2);font-size:var(--size-xs);line-height:var(--leading-compact);
margin-top:3px;overflow-wrap:anywhere}.small-button{font-size:var(--size-xs);line-height:var(--leading-compact);
padding:4px var(--space-2)}.time-button{font-family:var(--font-mono);font-weight:var(--weight-regular);
font-variant-numeric:tabular-nums}
.note-top{display:flex;align-items:baseline;gap:var(--space-2)}.note-text{overflow-wrap:anywhere}
.note-status{font-size:var(--size-xs);line-height:var(--leading-compact);color:var(--text-2);margin:6px 0 0 61px}
.option-row{margin:10px 0 0 61px}.option-row button{font-size:var(--size-xs);line-height:var(--leading-compact);
padding:4px var(--space-2)}.shared-audio{max-width:100%;height:32px;margin:10px 0 0 61px}
textarea,input,select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--border-strong);
border-radius:var(--radius-md)}textarea{width:100%;padding:var(--space-2);min-height:76px}
#noteForm{padding:0 var(--space-4) var(--space-4)}#noteForm p{margin-bottom:var(--space-2)}
.versions-card{padding:var(--space-4)}.versions{margin-top:var(--space-3)}.version-card{border:1px solid var(--border);
border-radius:var(--radius-md);padding:6px 10px;font:var(--size-xs)/var(--leading-compact) var(--font-mono);
background:var(--bg)}
a{color:var(--accent-text);text-underline-offset:2px}.blind{font-size:var(--size-xs);color:var(--text-2);
margin:var(--space-4) 0}details{margin:0 0 var(--space-6);padding:var(--space-3) var(--space-4)}
summary{cursor:pointer;font-weight:var(--weight-medium)}#stripImages img{display:block;width:100%;height:auto;
margin-top:var(--space-3);border-radius:var(--radius-sm)}#backCut{margin-left:var(--space-4);margin-top:10px}
#copyResult{margin-top:var(--space-2);font-size:var(--size-xs)}
kbd{font:var(--size-xs)/1 var(--font-mono);border:1px solid var(--border);border-radius:var(--radius-sm);
padding:2px 5px;margin-left:6px;background:var(--surface-2);color:var(--text-2)}
.paper-head{align-items:center}.paper-hint{font-size:var(--size-xs);color:var(--text-2);
padding:0 var(--space-4) var(--space-2)}
.direction{padding:0 var(--space-4) 10px;font-size:var(--size-sm);line-height:var(--leading-base)}
.direction p{margin:0 0 var(--space-1)}.direction strong{font-weight:var(--weight-medium)}
.paper{border-top:1px solid var(--border);scrollbar-color:var(--border-strong) transparent}
.line.changed{box-shadow:inset 2px 0 0 var(--accent)}.line.removed{cursor:default}
.line.focus-line{outline:2px solid var(--focus);outline-offset:-2px}
.line.removed .line-main{color:var(--text-3)}.line .meta{font-size:var(--size-xs);line-height:var(--leading-compact)}
.line-main .source-name,.source-name{color:var(--text-2)}
.line-main .effect{display:block;color:var(--text-2);font-size:var(--size-xs)}
.axis{display:flex;justify-content:space-between;color:var(--text-2);font:var(--size-xs)/var(--leading-compact)
var(--font-mono);font-variant-numeric:tabular-nums;margin-top:var(--space-2)}.playhead{z-index:2}
.compact-controls{display:flex;gap:6px;flex-wrap:wrap;padding:0 var(--space-4) var(--space-3)}
.compact-controls button{font-size:var(--size-xs);line-height:var(--leading-compact);padding:4px var(--space-2)}
.frame-time{font-size:var(--size-xs);color:var(--text-2);padding:0 var(--space-4) var(--space-3)}
.key-legend{font-size:var(--size-xs);color:var(--text-2);padding:0 var(--space-4) var(--space-3)}
.key-legend dl{display:grid;grid-template-columns:max-content 1fr;gap:4px var(--space-3);margin:0}
.key-legend dt{white-space:nowrap}.key-legend dt kbd{margin-left:0;margin-right:4px}.key-legend dd{margin:0}
#shuttle{font-size:var(--size-xs);color:var(--text-2);align-self:center}
.replay{padding:var(--space-3) var(--space-4);border-top:1px solid var(--border);background:var(--surface-2)}
.replay-fields{display:flex;align-items:end;gap:var(--space-2);flex-wrap:wrap;margin-top:var(--space-2)}
.replay-fields label{font-size:var(--size-xs);color:var(--text-2)}.replay-fields input{display:block;width:82px;
font-family:var(--font-mono);padding:5px;margin-top:2px}
.replay-note{font-size:var(--size-xs);color:var(--text-2);margin-top:var(--space-2)}.check-detail{margin:2px 0 0;
padding:0}.check-detail summary{font-size:var(--size-xs);color:var(--accent-text);font-weight:var(--weight-medium)}
.check-detail .detail{margin-top:var(--space-1)}
.check-actions,.moment-actions,.evidence{display:flex;gap:6px;flex-wrap:wrap;margin-top:var(--space-2)}
.scorecard{padding:var(--space-4);margin-bottom:var(--space-6)}.score-top{display:flex;gap:var(--space-4);
align-items:baseline;flex-wrap:wrap}.score-value{font:var(--size-xl)/var(--leading-xl) var(--font-mono);
letter-spacing:var(--track-tightest)}.score-sub{font-size:var(--size-sm);color:var(--text-2)}
.groups{display:flex;gap:var(--space-2);flex-wrap:wrap;margin:var(--space-3) 0}.group{background:var(--surface-2);
border-radius:var(--radius-md);padding:4px var(--space-2);font-size:var(--size-sm)}.dimension{padding:var(--space-3) 0;
border-top:1px solid var(--border)}.dimension-head{display:flex;justify-content:space-between;align-items:center;
gap:10px;flex-wrap:wrap}.dimension-head strong{font-weight:var(--weight-medium)}
.dimension-meta,.score-explain{font-size:var(--size-xs);color:var(--text-2)}.score-input{padding:4px;max-width:110px}
.fixes{margin-top:var(--space-4)}.fixes h3{font-size:var(--size-sm)}.fixes ol{padding-left:22px}
.fixes li{padding:4px 0}.score-summary{color:var(--accent-text);font-size:var(--size-sm)}
.changed-link{font-size:var(--size-xs);line-height:var(--leading-compact);padding:4px var(--space-2)}
.source-now{overflow-wrap:anywhere;text-align:right}
.version-details{padding:var(--space-3) var(--space-4);margin-bottom:var(--space-6)}
.version-details summary{cursor:pointer;font-weight:var(--weight-medium)}
.version-details h3{font-size:var(--size-sm);margin:var(--space-4) 0 6px}.version-details p{font-size:var(--size-sm);
line-height:var(--leading-base);margin:6px 0;color:var(--text-2)}
.transcript-prompt{margin:0 var(--space-4) 10px calc(var(--time-column) + var(--space-4));
font-size:var(--size-xs);line-height:var(--leading-compact);color:var(--text-2);padding:0}
.transcript-prompt summary{cursor:pointer;color:var(--accent-text)}.transcript-prompt p{margin:4px 0}
.waiting-areas{border-top:1px solid var(--border);padding:var(--space-3) 0;margin:0}
.waiting-areas summary{cursor:pointer}
.prompt-group{margin:10px 0}.prompt-times{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
@media(prefers-reduced-motion:no-preference){button,.line,.block{transition:background-color .12s ease,
box-shadow .12s ease,filter .12s ease}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important;
scroll-behavior:auto!important}}
@media(max-width:760px){main{padding:var(--space-6) var(--space-4) var(--space-10)}.grid{
grid-template-columns:minmax(0,1fr);gap:var(--space-3)}.head-top{flex-wrap:wrap}.badge{white-space:normal}
.card-head{padding:var(--space-3) var(--space-3) 10px}.card-body{padding:0 var(--space-3) var(--space-3)}
.player-info{padding:var(--space-3) var(--space-3) 0}.controls{padding:var(--space-3)}.timeline{padding:var(--space-3)}
.note-status,.option-row,.shared-audio{margin-left:0}.line.cutaway{margin-left:10px}}
</style></head><body><main>
<header><p class="eyebrow">Screening room <span class="muted"> / Review your film</span></p><div class="head-top">
<div class="title-row">
<h1 id="title"></h1><span class="subtitle" id="filmInfo"></span></div><span class="badge" id="version"></span></div>
<p class="readiness"><strong>Readiness:</strong> <span id="readiness"></span></p>
<p class="next-step" id="nextStep"></p><div id="stages" class="stages"></div>
<p id="connection" class="next-step" role="status" hidden></p>
<p><a id="scoreSummary" class="score-summary" href="#scorecard" hidden></a></p>
</header><div class="grid"><section class="card"><div class="card-head"><h2>This version</h2>
<span class="muted" id="playerLabel"></span></div><div class="player-wrap"><video id="player" controls
preload="metadata"></video></div><button id="backCut" hidden>Back to the film</button>
<div class="player-info"><span id="clock"></span><span id="source" class="source-now"></span></div>
<div class="controls"><button id="noteButton">Add note <kbd>N</kbd></button>
<button id="approve">Approve this version</button></div><div id="noteForm" hidden>
<p>Note at <span id="noteTime"></span> <span id="noteContext" class="muted"></span></p>
<textarea id="noteText" aria-label="Note"></textarea><button id="saveNote">Save note</button></div>
<div class="compact-controls"><button id="stepBack">Previous frame</button>
<button id="stepForward">Next frame</button><button id="keysButton" aria-expanded="false" aria-controls="keyLegend"
aria-keyshortcuts="Shift+Slash">Keys <kbd>?</kbd></button><span id="shuttle" role="status"></span></div>
<div id="keyLegend" class="key-legend" role="region" aria-label="Keyboard shortcuts" hidden><dl>
<dt><kbd>Space</kbd> or <kbd>K</kbd></dt><dd>Play or pause (K pauses)</dd>
<dt><kbd>L</kbd></dt><dd>Play forward; press again for 2x, 4x, 8x</dd>
<dt><kbd>J</kbd></dt><dd>Play backward; press again for 2x, 4x, 8x</dd>
<dt><kbd>&larr;</kbd> <kbd>&rarr;</kbd></dt><dd>One frame back or forward when paused; one second when playing</dd>
<dt><kbd>Shift</kbd> + <kbd>&larr;</kbd> <kbd>&rarr;</kbd></dt><dd>One second back or forward</dd>
<dt><kbd>Home</kbd> <kbd>End</kbd></dt><dd>Start or end of the film</dd>
<dt><kbd>N</kbd></dt><dd>Add a note at this moment</dd>
<dt><kbd>?</kbd></dt><dd>Show or hide these keys</dd></dl>
<p>Keys do nothing while you type in a box.</p></div>
<p id="frameTime" class="frame-time">Frame stepping is approximate in your browser.</p>
<div id="replay" class="replay" hidden><strong>Replay this moment</strong>
<div class="replay-fields"><label>From (seconds)<input id="replayStart" type="number" min="0" step="0.1"></label>
<label>To (seconds)<input id="replayEnd" type="number" min="0" step="0.1"></label>
<button id="playLoop">Play on repeat</button><button id="stopLoop">Stop repeat</button></div>
<p id="loopState" class="replay-note" hidden></p>
<p class="replay-note">A replay or frame step does not count as watching or listening to the whole film.</p></div>
</section><section class="card"><div class="card-head paper-head">
<h2>Script</h2><button id="seeChanges" class="changed-link" hidden></button></div>
<div id="direction" class="direction" hidden></div>
<p class="paper-hint">Scroll to read more. Select a line to go to that moment.</p><div id="paper" class="paper"></div>
</section></div><section class="card timeline"><div class="timeline-head"><h2>Timeline</h2>
<div id="legend" class="legend"></div></div><div id="strip" class="strip" aria-label="Timeline"></div>
<div id="axis" class="axis" aria-label="Film time"></div></section>
<details id="versionDetails" class="card version-details" hidden><summary>About this version</summary>
<div id="versionFacts"></div></details>
<section id="scorecard" class="card scorecard" hidden></section>
<details class="card"><summary>Screening strips (what the agent sees)</summary><div id="stripImages"></div></details>
<div class="grid stack"><section class="card"><div class="card-head"><h2>Checks</h2></div>
<div id="checks" class="card-body"></div></section><section class="card"><div class="card-head">
<h2>Notes and questions</h2></div><div class="card-body"><div id="notes"></div>
<audio id="optionAudio" class="shared-audio" controls hidden></audio><p><button id="copy" class="small-button">
Copy for your agent</button></p><div id="copyResult" class="muted"></div></div></section></div>
<section class="card versions-card"><h2>Versions</h2><div id="versions" class="versions"></div></section>
<section id="decisionCard" class="card versions-card" hidden><h2>Decisions</h2><div id="decisions"></div></section>
<p id="blind" class="blind"></p></main><script id="screen-data" type="application/json">DATA_PLACEHOLDER</script>
<script>
'use strict';
let data=JSON.parse(document.getElementById('screen-data').textContent);
const live=location.protocol!=='file:', $=id=>document.getElementById(id), player=$('player');
// Role colours are tokens in the page's style, so the timeline follows the light or dark theme.
const colors=Object.fromEntries(['interview','broll','screen','music','vo','still','sfx','other'].map(
  role=>[role,'var(--role-'+role+')']));
let active=null,noteAt=0,optionVideo=false,cutTime=0,loop=null,firstPaper=true,observedFrame=null,frameRequest=0;
let expectedLoopSeek=null,scoreKey='';
function localKey(){return 'legible-film:'+data.project+':'+data.current}
function local(){try{return JSON.parse(localStorage.getItem(localKey())||'{}')}catch(e){return {}}}
function saveLocal(v){localStorage.setItem(localKey(),JSON.stringify(v))}
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;
  if(cls)n.className=cls;return n}
function media(path){return '../'+path.split('/').map(encodeURIComponent).join('/')}
function fmt(s){s=Math.max(0,Number(s)||0);return Math.floor(s/60)+':'+(s%60).toFixed(2).padStart(5,'0')}
function frameFmt(s){s=Math.max(0,Number(s)||0);return Math.floor(s/60)+':'+(s%60).toFixed(3).padStart(6,'0')}
function shortVersion(v){return /^v\d+$/.test(v)?'v'+Number(v.slice(1)):v}
function entries(){return Array.isArray(data.lines)?data.lines:(data.lines.lines||[])}
function lineInfo(line){return (data.paper||[]).find(x=>x.line===line.line)||
  {line:line.line,kind:line.kind||'picture',text:'',alias:line.source||''}}
function cleanText(text){return String(text||'').replace(/~~/g,'')}
function alias(line){return lineInfo(line).alias||line.source||''}
function at(t){return entries().find(x=>t>=x.start&&t<x.end&&lineInfo(x).kind==='spoken')||null}
function visibleAt(t){let matches=entries().filter(x=>t>=x.start&&t<x.end),picture=matches.filter(x=>
  ['picture','cutaway','still','card'].includes(lineInfo(x).kind)||
  (x.kind==='title'&&x.card));return picture.pop()||at(t)||matches.find(x=>lineInfo(x).kind==='pause')||null}
function sourceName(alias){if(!alias)return '';let source=(data.sources.sources||[]).find(x=>x.alias===alias)||{};
  let match=alias.match(/_(\d+)$/),role=source.role||alias.split('_')[0];
  let names={int:'Interview',interview:'Interview',broll:'B-roll',screen:'Screen recording',music:'Music',
    vo:'Voiceover',still:'Still image',sfx:'Sound effect',other:'Source'};
  return (names[role]||'Source')+(match?' '+Number(match[1]):'')}
function dimensionName(id){let labels={hook:'Opening',structure:'Structure',pacing:'Pacing',emotion:'Emotion',
  cta:'Ending and next step',thumbnail:'Cover',visual_pacing:'Picture changes',text:'Text and captions',
  image:'Lighting and image',composition:'Framing',voice:'Voice',sound_design:'Music and effects',
  mix:'Sound balance',platform_fit:'Fit for where it will be shown',access:'Accessibility'};
  return labels[id]||String(id||'Area').replace(/_/g,' ')}
function dimensionLabel(d){return ['hook','visual_pacing','mix','platform_fit'].includes(d.id)?
  dimensionName(d.id):(d.label||dimensionName(d.id))}
function sourceNode(alias){let node=el('span',sourceName(alias),'source-name');node.title=alias||'';return node}
function pictureName(line){if(!line)return '';let name=sourceName(alias(line));if(name)return name;
  let kind=lineInfo(line).kind;return kind==='pause'?'Pause':kind==='card'||(line.kind==='title'&&line.card)?
    'Title card':kind==='title'?'Title':'Picture'}
function effects(info){let m=info.mods||{},out=[];
  if(m.offset!==undefined)out.push('Starts '+m.offset+' s into the line');
  if(m.fade_in!==undefined)out.push('Fades in over '+m.fade_in+' s');
  if(m.fade_out!==undefined)out.push('Fades out over '+m.fade_out+' s');
  if(m.fade!==undefined)out.push('Fades over '+m.fade+' s');
  if(m.speed!==undefined)out.push('Plays at '+m.speed+' times the original speed');
  if(m.join)out.push((m.join[0]==='dissolve'?'Dissolves':'Fades through black')+' over '+m.join[1]+' s');
  if(m.hold)out.push('Holds the previous picture');
  if(m.at!==undefined)out.push('Starts at '+fmt(m.at));
  return out.join(' \u00b7 ')}
function reviewed(){return Object.assign({},(data.status.reviewed||{})[data.current]||{},local().ticks||{})}
function checkKey(item){return item.state==='you'&&/^[a-z0-9_]{1,40}$/.test(item.id||'')?item.id:null}
function shape(size){if(!Array.isArray(size)||!size[0]||!size[1])return '';
  let a=size[0],b=size[1];while(b){let c=a%b;a=b;b=c}
  if(size[0]/a<=32&&size[1]/a<=32)return size[0]/a+':'+size[1]/a;
  // 1280x534 reduces to 640:267; a person reads 2.40:1.
  return size[0]>=size[1]?(size[0]/size[1]).toFixed(2)+':1':'1:'+(size[1]/size[0]).toFixed(2)}
function age(created){let t=Date.parse(created);if(!Number.isFinite(t))return '';
  let mins=Math.max(0,Math.floor((Date.now()-t)/60000));
  if(mins<1)return 'rendered just now';if(mins<60)return 'rendered '+mins+' min ago';
  if(mins<1440)return 'rendered '+Math.floor(mins/60)+' hr ago';
  let days=Math.floor(mins/1440);return 'rendered '+days+' day'+(days===1?'':'s')+' ago'}
function cutSrc(){return media('cuts/'+data.current+'/preview.mp4')}
function backToCut(seek){optionVideo=false;$('backCut').hidden=true;player.src=cutSrc();
  player.currentTime=seek===undefined?cutTime:seek;player.pause();sync()}
function seekCut(t){loop=null;if(optionVideo)backToCut(t);else player.currentTime=t}
function playOption(option){if(!option.path)return;
  let ext=option.path.split('.').pop().toLowerCase(), src=media(option.path);
  if(['mp4','webm','mov','m4v'].includes(ext)){
    if(!optionVideo)cutTime=player.currentTime;
    optionVideo=true;$('optionAudio').pause();$('backCut').hidden=false;player.src=src;
    player.play().catch(()=>{});$('playerLabel').textContent='Option '+option.label;
  }else{
    let audio=$('optionAudio');audio.hidden=false;audio.src=src;audio.play().catch(()=>{});
  }
}
function revealLine(node){if(!node)return;let panel=$('paper'),box=panel.getBoundingClientRect();
  panel.scrollTop+=node.getBoundingClientRect().top-box.top-12}
function renderPaper(){
  let reviewOpen=new Set([...$('paper').querySelectorAll('.transcript-prompt[open]')].map(x=>x.dataset.line));
  let previousScroll=$('paper').scrollTop;$('paper').replaceChildren();
  let section=null,removed=data.removed_lines||[],timed=entries(),noteIndex=0;
  let notes=(data.reader_notes||[]).filter(n=>n&&Number.isFinite(n.line)&&typeof n.text==='string');
  function heading(name){if(name&&name!==section){section=name;$('paper').append(el('div',section,'section-label'))}}
  // Notes to readers sit where the script has them, under their own section.
  function showNotes(before){while(noteIndex<notes.length&&notes[noteIndex].line<before){let n=notes[noteIndex++];
    heading(n.section);$('paper').append(el('p',n.text,'reader-note'))}}
  function show(info,isRemoved){
    if(!isRemoved)heading(info.section);
    let line=timed.find(x=>x.line===info.line),change=data.changes[String(info.line)];
    let node=el('div',undefined,'line'+(info.over?' cutaway':'')+(isRemoved?' removed':'')+
      (!isRemoved&&change?' changed':''));
    if(line&&!isRemoved){node.tabIndex=0;node.dataset.line=info.line;node.setAttribute('role','button');
      node.setAttribute('aria-label','Go to '+fmt(line.start)+' '+cleanText(info.text));
      node.onclick=()=>seekCut(line.start);
      node.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();node.click()}}}
    node.append(el('span',isRemoved?'Removed':line?fmt(line.start):'', 'time'));
    let content=el('div',undefined,'line-main');
    if(info.over&&['picture','cutaway','still'].includes(info.kind))
      content.append(el('span','Picture over speech','over'));
    let words=el(info.kind==='spoken'?'i':'span');
    if(isRemoved){words.append(el('del',(info.text||'').replace(/~~/g,'')))}
    else if(info.kind==='spoken'){
      (info.parts||[]).forEach((part,index)=>{if(index)words.append(document.createTextNode(' '));
        words.append(part.removed?el('del',part.text):document.createTextNode(part.text))});
    }else if(info.kind==='title'||info.kind==='card')words.textContent=
      (info.kind==='card'?'Title card: ':'Title: ')+(info.text||'')+
      (Number.isFinite(info.seconds)?' \u00b7 '+info.seconds+' s':'');
    else if(info.kind==='pause')words.textContent='Pause'+
      (Number.isFinite(info.seconds)?' \u00b7 '+info.seconds+' s':'');
    else words.textContent=info.text||({'music':'Music','still':'Still image'}[info.kind]||'Picture');
    content.append(words);
    if(!isRemoved&&change)content.append(el('span',
      (change.moved?'Moved':'Changed')+' in '+shortVersion(data.current),'tag'));
    let meta=el('small',undefined,'meta');if(info.alias)meta.append(sourceNode(info.alias));
    let effect=isRemoved?'':effects(info);if(effect)meta.append(el('span',effect,'effect'));
      if(meta.childNodes.length)content.append(meta);
    node.append(content);$('paper').append(node);
    let prompts=!isRemoved&&data.transcript_review&&data.transcript_review[String(info.line)];
    if(Array.isArray(prompts)&&prompts.length){
      let review=el('details',undefined,'transcript-prompt');review.dataset.line=String(info.line);
      review.open=reviewOpen.has(review.dataset.line);review.append(el('summary','Listen around this join'));
      let reasons={repeated_phrase:'A phrase may be repeated.',
        word_in_low_energy:'A transcribed word falls in a quiet part.',
        uncovered_energy:'Sound here has no transcript words.',
        uncovered_speech:'Speech here has no transcript words.',
        low_confidence:'The transcriber was unsure of some words here.',
        other:'The render recorded a transcript concern.'};
      [...new Set(prompts.map(p=>reasons[p.kind]||reasons.other))].forEach(text=>review.append(el('p',text)));
      review.append(el('p','These are prompts, not proof: music and noise can trigger them, '+
        'and quiet speech can be missed.'));
      if(prompts.some(p=>p.origin==='current_map'))review.append(el('p',
        'The current source transcript may have changed since this version was made.'));
      $('paper').append(review)}
  }
  (data.paper||[]).forEach(info=>{showNotes(info.line);
    removed.filter(x=>x.before_line===info.line).forEach(x=>show(x,true));show(info,false)});
  showNotes(Infinity);removed.filter(x=>x.before_line===null).forEach(x=>show(x,true));
  let changed=$('paper').querySelectorAll('.changed,.removed'),button=$('seeChanges');button.hidden=!changed.length;
  button.textContent='See '+changed.length+' change'+(changed.length===1?'':'s');
  button.onclick=()=>revealLine(changed[0]);active=null;
  if(firstPaper&&changed.length){requestAnimationFrame(()=>revealLine(changed[0]));firstPaper=false}
  else $('paper').scrollTop=previousScroll;
}
function renderTimeline(){
  $('strip').replaceChildren();$('legend').replaceChildren();let roles={};
  (data.sources.sources||[]).forEach(s=>roles[s.alias]=s.role);
  let used=new Set();entries().forEach(line=>used.add(roles[alias(line)]||'other'));
  used.forEach(role=>{let item=el('span'),swatch=el('i',undefined,'swatch');
    let labels={interview:'Interview',broll:'B-roll',screen:'Screen recording',vo:'Voiceover',still:'Still image',
      music:'Music',sfx:'Sound effect',other:'Other visuals and sources'};
    swatch.style.background=colors[role]||colors.other;
    item.append(swatch,document.createTextNode(labels[role]||'Other visuals and sources'));
    $('legend').append(item)});
  let duration=(data.versions[data.current]||{}).duration_s||Math.max(1,...entries().map(x=>x.end));
  let lanes=[];entries().forEach(line=>{
    let lane=lanes.findIndex(end=>end<=line.start);if(lane<0){lane=lanes.length;lanes.push(0)}
    lanes[lane]=line.end;
    let info=lineInfo(line),block=el('div',undefined,'block'+(data.changes[String(line.line)]?' changed':''));
    block.style.left=(100*line.start/duration)+'%';
    block.style.width=(100*Math.max(0,line.end-line.start)/duration)+'%';
    block.style.top=(lane*28)+'px';block.style.background=colors[roles[info.alias]]||colors.other;
    block.title=cleanText(info.text);block.setAttribute('aria-label',cleanText(info.text));
    block.onclick=()=>seekCut(line.start);$('strip').append(block);
  });$('strip').style.height=Math.max(28,lanes.length*28)+'px';
  (data.notes.notes||[]).concat(local().notes||[]).filter(n=>n.version===data.current&&
    Number.isFinite(n.t)&&n.t>=0&&n.t<=duration).forEach(n=>{
    let dot=el('span',undefined,'dot');dot.style.left=(100*n.t/duration)+'%';dot.style.top='-6px';
    dot.title='Note at '+fmt(n.t);$('strip').append(dot)});
  $('strip').append(el('div',undefined,'playhead'));
  $('axis').replaceChildren();[0,.25,.5,.75,1].forEach(f=>$('axis').append(el('span',fmt(duration*f))));
}
async function markReview(kind){try{if(live)await post('review',{kind});else{
  let v=local();v.ticks=v.ticks||{};v.ticks[kind]=true;saveLocal(v);render()}}catch(e){alert(e.message)}}
function renderChecks(items,ticks){
  const icons={pass:'\u2713',look:'\u25d0',fail:'\u2717',you:'\u25cb',skip:'\u2013'};
  let opened=new Set([...$('checks').querySelectorAll('.check-detail[open]')].map(n=>n.dataset.check));
  $('checks').replaceChildren();items.forEach(item=>{
    let row=el('div',undefined,'item check-row');row.append(el('span',icons[item.state]||'',
      'check-icon '+item.state));let text=el('div'),label=item.label||item.id||'',detail=item.detail||'';
    if(item.id==='spec'){
      label=item.state==='pass'?'Video format and length checked':'Video format or length needs attention';
      detail=[item.label,detail].filter(Boolean).join(' \u00b7 ')}
    if(item.id==='blank'){
      label=item.state==='pass'?'No nearly blank moments found':'Some moments may look nearly blank';
      detail='A dark, still or simple picture can be intentional. Review the moment to decide.'}
    if(item.id==='flash')label=label.replace(/\s*\(WCAG[^)]*\)/,'');
    if(item.id==='loudness'){label='Sound level';
      if(data.version_details&&data.version_details.audio_master&&!data.version_details.audio_master.missing)
        detail=detail.replace(/preview, not mastered/i,'preview; see About this version for its sound master');
      else detail=detail.replace('mastered','adjusted for delivery')}
    if(item.id==='edges'&&item.state!=='skip'){
      label=item.state==='pass'?'Sound starts and ends near silence':'Check the start and end of the sound';
      detail='Listen for clicks or an abrupt ending.'}
    if(item.id==='mono'&&item.state!=='skip'){
      label=item.state==='pass'?'Sound checked on one speaker':'Check sound on one speaker';
      detail='This combines the left and right sound channels to find changes. Listen on one speaker too.'}
    if(item.id==='interlace'&&item.state!=='skip'){
      label=item.state==='pass'?'No comb-like lines found in sampled moving pictures':
        'Moving pictures may show unwanted lines';
      detail='Look for thin, comb-like lines around moving objects.'}
    if(item.id==='freeze'&&item.state!=='skip'){
      label=item.state==='pass'?'No unexplained frozen picture found':'A moment may look frozen';
      detail='Still pictures can trigger this check even when they are intentional.'}
    if(item.id==='color_range'&&item.state!=='skip'){
      label=item.state==='pass'?'Picture brightness range checked':'Picture brightness range needs attention';
      detail='The sampled picture values were compared with the range recorded in the video file.'}
    if(item.id==='audio_integrity'&&item.state!=='skip'){
      label=item.state==='pass'?'Sound signal checked':'Sound signal needs attention';
      detail=item.state==='pass'?'The sound signal was measured. Listen for distortion too.':
        'A sound measurement needs review. Ask your agent to inspect it and listen for distortion.'}
    if(item.id==='captions_edit'&&item.state!=='skip'){
      label=item.state==='pass'?'Captions follow the script':'Captions and script need comparison';
      detail='This compares caption text with the written script; it does not check the sound.'}
    if(item.state==='skip'){
      let labels={mono:'Sound on one speaker',bars:'Borders around the picture',interlace:'Lines in moving pictures',
        freeze:'Frozen picture',color_range:'Picture colour range',audio_integrity:'Sound signal problems'};
      if(labels[item.id])label=labels[item.id];
      if(item.id==='interlace'&&/too few classified frames/i.test(detail))
        detail='Too few frames could be classified; look for unwanted lines in movement.';
      else if(item.id==='mono'&&/requires stereo/i.test(detail))
        detail='This check needs separate left and right sound channels.';
      else if(item.id==='bars'&&/no stable crop/i.test(detail))
        detail='There were too few consistent picture samples to assess the borders.';
      else if(item.id==='color_range'&&/fewer than three/i.test(detail))
        detail='Fewer than three picture samples were available to inspect the colour range.';
      else if(item.id==='color_range'&&/range tag/i.test(detail))
        detail='The file\'s colour-range tag does not allow this particular check.';
      else if(item.id==='audio_integrity'&&/statistics unavailable or silent/i.test(detail))
        detail='The sound could not be measured, or it may be silent; listen to it.';
      else if(item.id==='captions_speech'){
        if(/--no-speech/i.test(detail))detail='The speech comparison was turned off for this check.';
        else if(/no sound/i.test(detail))detail='There is no sound to compare with the captions.';
        else if(/not installed|onnxruntime/i.test(detail))
          detail='The speech recognition needed for this comparison is unavailable on this machine.';
        else if(/not downloaded|weights|cache/i.test(detail))
          detail='The speech recognition model needed for this comparison is unavailable on this machine.';
        else detail='The speech comparison could not run. Ask your agent to investigate.';
      }
      if(!detail)detail='No reason was recorded; ask your agent to inspect this check.';
    }
    if(item.state==='skip')label='Not run: '+label;
    text.append(el('span',label));
    if(detail){let more=el('details',undefined,'check-detail'),summary=el('summary','Details');
      more.dataset.check=item.id||label;more.open=opened.has(more.dataset.check);
      more.append(summary,el('small',detail,'detail'));text.append(more)}
    if(Number.isFinite(Number(item.at))&&item.at!==null&&item.at!==undefined){
      let actions=el('div',undefined,'check-actions'),go=el('button','Go to '+fmt(item.at),'small-button');
      go.onclick=()=>seekCut(Number(item.at));let replay=el('button','Replay moment','small-button');
      replay.onclick=()=>replayMoment(Number(item.at));actions.append(go,replay);text.append(actions)}row.append(text);
    let key=checkKey(item);if(key){let button=el('button',ticks[key]?'Done':'Mark done','small-button');
      button.disabled=!!ticks[key];button.onclick=()=>markReview(key);row.append(button)}$('checks').append(row);
  });
}
function renderNotes(){
  $('notes').replaceChildren();(data.notes.notes||[]).concat(local().notes||[]).forEach(n=>{
    let row=el('div',undefined,'item'),top=el('div',undefined,'note-top');
    let same=!n.version||n.version===data.current;
    let seek=el('button',fmt(n.t),'small-button time-button');seek.disabled=!same;seek.onclick=()=>seekCut(n.t);
    top.append(seek,el('span',n.text,'note-text'));row.append(top);
    let context=(n.kind==='question'?'Agent question':'Note')+(n.origin==='flask'?' from Flask':'')+' \u00b7 '+n.status+
      (n.version&&!same?' \u00b7 '+shortVersion(n.version):'');
    row.append(el('div',context,'note-status'));
    if(n.source||n.spoken_source){let where=el('div','Picture: ','note-status');
      where.append(sourceNode(n.source||n.spoken_source));if(n.spoken_line&&n.spoken_line!==n.line){
        where.append(document.createTextNode(' \u00b7 Speech: '),sourceNode(n.spoken_source))}row.append(where)}
    if(same){let actions=el('div',undefined,'moment-actions'),replay=el('button','Replay moment','small-button');
      replay.onclick=()=>replayMoment(Number(n.t));actions.append(replay);row.append(actions)}
    if(n.reply)row.append(el('div','Reply: '+n.reply,'note-status'));
    if(n.kind==='question'){
      let options=el('div',undefined,'option-row');(n.options||[]).forEach(o=>{
        if(o.path){let play=el('button','\u25b6 '+o.label);play.onclick=()=>playOption(o);options.append(play)}
        let choose=el('button','Choose '+o.label);choose.onclick=()=>answer(n.id,o.label);options.append(choose);
      });row.append(options);let chosen=(local().answers||{})[n.id]||n.answer;
      if(chosen)row.append(el('div','Chosen: '+chosen,'note-status'));
    }$('notes').append(row);
  });
}
function reviewerProvenance(value){
  if(!value||typeof value!=='object')return 'Reviewer model and independence not recorded.';
  let relation=value.same_family_as_cut_maker===false?'another model family':
    value.same_family_as_cut_maker===true?'the same model family as the editor':
      'a model family whose relationship to the editor is unknown';
  return 'Reviewer from '+relation+', using stills and the transcript. Model: '+(value.model||'not recorded')+
    '; family: '+(value.model_family||'not recorded')+'.';
}
function addEvidence(container,items){(Array.isArray(items)?items:[]).filter(e=>e&&typeof e==='object').forEach(e=>{
  let evidence=el('div',undefined,'evidence');if(typeof e.t==='number'&&Number.isFinite(e.t)){
    let go=el('button',fmt(e.t),'small-button time-button');go.onclick=()=>seekCut(e.t);evidence.append(go)}
  evidence.append(el('span',e.note||e.text||''));container.append(evidence)})}
function plainPrompt(prompt){let text=typeof prompt.text==='string'?prompt.text:'';
  if(/^Sidecar cue/i.test(text))return 'Captions here may be hard to read in time.';
  if(/^Sample peak/i.test(text))return 'Sound here may be too loud; listen and check its level.';
  if(/^Stereo phase/i.test(text))return 'Sound here may change on one speaker; compare both versions.';
  if(/^Check blank:/i.test(text))return 'This moment may look nearly blank; review it.';
  if(/^Check freeze:/i.test(text))return 'The picture may look frozen here; watch this moment.';
  if(/^Check audio_integrity:/i.test(text))return 'The sound signal needs attention; ask your agent to inspect it.';
  if(/^Check /i.test(text))return 'A check needs your attention at this moment.';
  return text||'Review this moment.'}
function renderVersionDetails(){
  let facts=$('versionFacts'),details=data.version_details||{},captions=details.captions||{};
  facts.replaceChildren();
  function group(title,lines){if(!lines.length)return;facts.append(el('h3',title));
    lines.forEach(text=>facts.append(el('p',text)))}
  let captionsText=[];
  if(captions.burned)captionsText.push('Captions are drawn onto this version of the picture.');
  let rules={
    'minimum gap':'The gap between captions could be shorter than usual.',
    'minimum duration':'Some captions could be shown for less time than usual.',
    'reading speed':'Some captions may need to be read faster than usual.',
    'single-word cues':'A caption may contain just one word.',
    'protected phrase breaks':'A phrase may have been split across captions.',
    'maximum duration':'A caption may stay on screen longer than usual.',
    'line length for an unbreakable word':'A long word may make a caption line longer than usual.'};
  (captions.relaxed||[]).forEach(row=>{let text=rules[row.constraint];if(!text)return;
    if(typeof row.allowed==='number'&&row.constraint==='reading speed')
      text+=' Allowed: '+row.allowed+' characters per second.';
    if(typeof row.allowed==='number'&&row.constraint==='minimum duration')
      text+=' Allowed: '+row.allowed+' seconds minimum.';
    captionsText.push(text)});
  (captions.resized||[]).forEach(row=>captionsText.push('Caption '+row.cue+' was made smaller to fit ('+
    row.requested+' to '+row.used+' pixels).'));
  if(captions.contrast){let c=captions.contrast;
    captionsText.push(typeof c.minimum==='number'?'Lowest sampled contrast: '+c.minimum+':1'+
      (c.samples?' across '+c.samples+' sample'+(c.samples===1?'':'s'):'')+'.':
      'Caption contrast could not be measured from the sampled pictures.');
    captionsText.push('These samples do not establish that captions are readable; check them on the picture.')}
  if(details.caption_speech_voice_detection==='off')captionsText.push(
    'The caption comparison used a transcript made without voice detection; listen to check the words.');
  group('Captions',captionsText);
  let font=details.title_font;
  if(font&&font.fallback)group('Titles',['A different font was used for titles'+
    (font.family?' ('+font.family+')':'')+'. Check how the titles look.']);
  let master=details.audio_master,sound=[];
  if(master&&master.missing)sound.push('The sound-mastering record for this version is unavailable.');
  else if(master){
    if(master.mode==='linear')sound.push('Sound level used a steady adjustment (linear mode).');
    else if(master.mode==='dynamic')sound.push('Sound level used a changing adjustment (dynamic mode); listen to it.');
    else sound.push('The sound adjustment mode was not recorded.');
    if(typeof master.target_lufs==='number')sound.push('Target sound level: '+master.target_lufs+
      ' LUFS (average loudness)'+(master.target_source==='working'?'; a working target, not a platform rule.':'.'));
    else sound.push('The target sound level was not recorded.');
    if(typeof master.measured_lufs==='number'){
      let message='The delivered sound measured '+master.measured_lufs+' LUFS.';
      let tolerance=typeof master.target_tolerance_lu==='number'?master.target_tolerance_lu:.5;
      if(typeof master.target_lufs==='number'&&Math.abs(master.measured_lufs-master.target_lufs)>tolerance)
        message+=' It missed the target by '+Math.abs(master.measured_lufs-master.target_lufs).toFixed(1)+' LU.';
      sound.push(message)
    }else sound.push('The delivered sound level was not measured.');
    if(typeof master.true_peak_dbtp!=='number')sound.push('The delivered sound peak was not measured.');
    else if(typeof master.requested_true_peak_dbtp==='number'&&
      master.true_peak_dbtp>master.requested_true_peak_dbtp+.05)sound.push('The sound peak was '+
      master.true_peak_dbtp+' dBTP (peak level), above the requested '+master.requested_true_peak_dbtp+' limit.');
    if(typeof master.reencode_peak_dbtp!=='number')sound.push(
      'The sound peak after a simulated conversion was not measured.');
    else if(master.reencode_peak_dbtp>-1)sound.push('After a simulated conversion, the sound peak was '+
      master.reencode_peak_dbtp+' dBTP, above the -1 dBTP check.');
  }
  group('Sound',sound);
  let sources=[];(details.sources||[]).forEach(source=>{
    let name=sourceName(source.alias)||'Source',text=name+': ';
    if(source.selection==='not_used')text+='not used in this version.';
    else if(source.selection==='recorded')text+='sound track (stream '+source.stream+') was selected for this version.';
    else if(source.sound_used===false)text+='no sound from this source was used in this version.';
    else text+='the audio stream for this version was not recorded.';
    if(source.selection==='recorded'&&source.sound_used===false)
      text+=' No sound from this source is used in the film.';
    if(typeof source.map_stream==='number'&&source.map_stream!==source.stream)
      text+=' The current source map selects stream '+source.map_stream+'.';
    if(source.voice_detection==='off')text+=
      ' The current transcript was made without voice detection; listen to check it.';
    sources.push(text)});
  group('Sources and sound',sources);
  $('versionDetails').hidden=!facts.childNodes.length;
  if(facts.childNodes.length)facts.append(el('p','These records help you review the film; they are not approval.',
    'dimension-meta'));
}
function renderScorecard(){
  let card=data.scorecard,section=$('scorecard'),summary=$('scoreSummary');
  let opened=new Set([...section.querySelectorAll('details[open][data-key]')].map(x=>x.dataset.key));
  section.replaceChildren();section.hidden=!card||!Array.isArray(card.dimensions);
  summary.hidden=section.hidden;if(section.hidden)return;
  let overall=card.overall||{},top=el('div',undefined,'score-top');top.append(el('h2','Craft scorecard'));
  if(typeof overall.score==='number')top.append(el('span',overall.score+'/100','score-value'));
  let coverage=typeof overall.scored==='number'&&typeof overall.of==='number'?
    overall.scored+' of '+overall.of+' areas':'';
  if(overall.scored===0)top.append(el('span','No areas have been scored yet.','score-sub'));
  else if(coverage&&overall.scored<overall.of)
    top.append(el('span','Based on '+coverage+'; a partial score.','score-sub'));
  top.append(el('span','A guide to what may improve the film, not an approval check.','score-sub'));section.append(top);
  let freshness=data.scorecard_state==='current'?'This scorecard matches this video.':
    data.scorecard_state==='outdated'?
      'Out of date: this scorecard is for a different video. Ask your agent to regrade.':
    'The scorecard could not be matched to this video.';
  section.append(el('p',freshness,'score-explain'));
  if(card.notice)section.append(el('p',String(card.notice),'score-explain'));
  if(card.validation&&card.validation.state==='unvalidated')section.append(el('p',
    'Not yet validated: scores are provisional.','score-explain'));
  if(card.validation&&card.validation.state==='partial')section.append(el('p',
    'Some areas have been tested against deliberate defects; every score is still a reviewer judgment.',
    'score-explain'));
  summary.textContent='Craft score: '+(typeof overall.score==='number'?overall.score+'/100':'waiting for review')+
    (coverage?' ('+coverage+')':'')+
    (data.scorecard_state==='outdated'?' \u00b7 out of date':'')+' \u00b7 See scorecard';
  if(overall.scored>0)section.append(el('p',overall.scored+' of '+overall.of+
    ' areas scored. A partial average can change when coverage or the basis changes.','score-explain'));
  let groupValues=Object.entries(card.groups||{});
  if(groupValues.some(([,value])=>typeof value==='number')){let groups=el('div',undefined,'groups');
    groupValues.forEach(([name,value])=>{if(name)groups.append(el('span',name[0].toUpperCase()+name.slice(1)+' '+
      (value===null?'not scored':value+'/10'),'group'))});section.append(groups)}
  let yours=(((data.scores||{}).scores||{})[data.current]||{});
  function dimensionRow(d){
    let row=el('div',undefined,'dimension'),head=el('div',undefined,'dimension-head');
    head.append(el('strong',dimensionLabel(d)));
    let value=typeof d.score==='number'?d.score+'/10':d.status==='waiting'?'Waiting for review':'Not scored';
    head.append(el('span',(d.basis==='person'?'Current rating: ':d.score===null?'':'Reviewer: ')+value));
    row.append(head);
    if((d.status==='waiting'||d.status==='not_scored')&&d.reason&&
       d.reason!=='Waiting for supported judgment.')row.append(el('div',d.reason,'dimension-meta'));
    let basis={measured:'Measured from the file',judged:'Scored by a reviewer',person:'Your rating takes precedence'};
    if(d.basis)row.append(el('div',(basis[d.basis]||String(d.basis))+' \u00b7 Confidence: '+
      (d.confidence||'not provided'),'dimension-meta'));
    let tested={passed_degradation_test:'Tested: a reviewer caught deliberate defects here on two kinds of video.',
      partly_passed:'Partly tested: caught on one of two kinds of video.',unvalidated:'Not yet validated.'};
    if(typeof d.score==='number'&&(tested[d.validation]||(card.validation&&card.validation.state==='unvalidated'))){
      let note=el('div',tested[d.validation]||'Not yet validated.','dimension-meta');
      if(d.validation_detail){let more=el('details');more.append(el('summary','What was tested'));
        more.append(el('div',String(d.validation_detail),'dimension-meta'));note.append(more)}
      row.append(note)}
    if(d.basis==='judged')row.append(el('div',reviewerProvenance(d.judge_provenance),'dimension-meta'));
    if(d.basis==='judged'&&d.judged_by)row.append(el('div','Reviewer: '+d.judged_by,'dimension-meta'));
    if(live){let label=el('label','Your score '),select=el('select',undefined,'score-input');
      select.dataset.dimension=d.id;select.setAttribute('aria-label','Your score for '+dimensionLabel(d));
      let placeholder=el('option','Choose /10');placeholder.value='';select.append(placeholder);
      for(let n=0;n<=10;n++){let option=el('option',String(n));option.value=String(n);select.append(option)}
      if(yours[d.id])select.value=String(yours[d.id].score);
      select.onchange=async()=>{if(select.value==='')return;try{await post('score',{
        version:data.current,dimension:d.id,score:Number(select.value)})}catch(e){alert(e.message)}};
      label.append(select);row.append(label)
    }else if(yours[d.id])row.append(el('div','Your score: '+yours[d.id].score+
      '/10 (takes precedence)','dimension-meta'));
    addEvidence(row,d.evidence);
    let assessments=(Array.isArray(d.assessments)?d.assessments:[]).filter(a=>a&&typeof a==='object');
    if(assessments.length){let more=el('details',undefined,'check-detail');more.dataset.key='assessment-'+d.id;
      more.open=opened.has(more.dataset.key);more.append(el('summary','Other assessments and evidence'));
      assessments.forEach(a=>{let item=el('div',undefined,'detail');
        item.append(el('span',(a.basis==='person'?'Person':'Reviewer')+': '+a.score+'/10 \u00b7 Confidence: '+
          (a.confidence||'not provided')));
        if(a.basis==='judged')item.append(el('div',reviewerProvenance(a.judge_provenance),'dimension-meta'));
        if(a.judged_by&&a.basis==='judged')item.append(el('div','Reviewer: '+a.judged_by,'dimension-meta'));
        addEvidence(item,a.evidence);more.append(item)});row.append(more)}
    return row;
  }
  let waiting=[],shown=[];card.dimensions.forEach(d=>{
    let ordinary=!d.reason||d.reason==='Waiting for supported judgment.';
    if(d.status==='waiting'&&d.score==null&&ordinary&&!yours[d.id]&&
       !(Array.isArray(d.evidence)&&d.evidence.length)&&!(Array.isArray(d.assessments)&&d.assessments.length))
      waiting.push(d);
    else shown.push(d)});
  shown.forEach(d=>section.append(dimensionRow(d)));
  if(waiting.length){let more=el('details',undefined,'waiting-areas');more.dataset.key='waiting-areas';
    more.open=opened.has(more.dataset.key);let label=waiting.length+' area'+(waiting.length===1?'':'s')+
      ' waiting for a reviewer: '+(live?'open to score them yourself':'open to see them');
    more.append(el('summary',label));waiting.forEach(d=>more.append(dimensionRow(d)));section.append(more)}
  if(Array.isArray(card.fixes)&&card.fixes.length){let fixes=el('div',undefined,'fixes');
    fixes.append(el('h3','Suggested fixes'));let list=el('ol');
    card.fixes.filter(f=>f&&typeof f==='object').forEach(f=>{let item=el('li');
      item.append(document.createTextNode(typeof f.text==='string'?f.text:''));
      let info=(data.paper||[]).find(x=>x.line===f.line),timed=entries().find(x=>x.line===f.line);
      if(info&&timed){let words=info.parts?
        info.parts.filter(p=>!p.removed).map(p=>p.text).join(' '):cleanText(info.text);
        let line=el('button',fmt(timed.start)+' \u00b7 '+(words||'See this line').split(/\s+/).slice(0,5).join(' '),
          'small-button');line.onclick=()=>{let target=document.querySelector('.line[data-line="'+info.line+'"]');
          document.querySelectorAll('.focus-line').forEach(n=>n.classList.remove('focus-line'));
          if(target){target.classList.add('focus-line');revealLine(target);target.focus({preventScroll:true})}
          $('paper').scrollIntoView({block:'nearest'});seekCut(timed.start)};item.append(' ',line)}
      if(f.proposed_by)item.append(el('div','Suggested by '+f.proposed_by+'.','dimension-meta'));
      if(typeof f.gain==='number')item.append(el('div','Estimated gain: '+f.gain+'; not measured.','dimension-meta'));
      list.append(item)});fixes.append(list);section.append(fixes)}
  if(Array.isArray(card.review_prompts)&&card.review_prompts.length){let prompts=el('div',undefined,'fixes');
    prompts.append(el('h3','Moments to review'));let grouped=new Map();
    card.review_prompts.filter(p=>p&&typeof p==='object').forEach(p=>{
      let label=plainPrompt(p),kind=/^Check ([a-z_]+):/i.exec(p.text||'');
      let key=(p.dimension||'')+'|'+label+'|'+(kind?kind[1]:'');
      if(!grouped.has(key))grouped.set(key,{label,items:[]});grouped.get(key).items.push(p)});
    grouped.forEach((group,key)=>{let item=el('div',undefined,'prompt-group');
      item.append(el('span',group.label+(group.items.length>1?' \u00b7 '+group.items.length+' moments':'')));
      let times=el('div',undefined,'prompt-times');group.items.forEach(p=>{
        if(typeof p.t==='number'&&Number.isFinite(p.t)){
          let go=el('button',fmt(p.t),'small-button time-button');go.onclick=()=>seekCut(p.t);times.append(go)}});
      if(times.childNodes.length)item.append(times);
      if(group.items.some(p=>p.text||p.next)){let detail=el('details',undefined,'check-detail');
        detail.dataset.key='prompt-'+key;detail.open=opened.has(detail.dataset.key);
        detail.append(el('summary','Details'));group.items.forEach(p=>{
          let text=[p.text,p.next].filter(x=>typeof x==='string').join(' ');
          if(text)detail.append(el('p',(Number.isFinite(p.t)?fmt(p.t)+' \u00b7 ':'')+text,'dimension-meta'))});
        item.append(detail)}prompts.append(item)});section.append(prompts)}
  if(card.parent&&typeof card.parent==='object'&&typeof overall.score==='number'){let p=card.parent,delta=
    typeof overall.score==='number'&&typeof p.overall==='number'?
    ' \u00b7 '+(overall.score-p.overall>=0?'+':'')+(overall.score-p.overall)+' points':'';
    section.append(el('p','Compared with '+shortVersion(p.version||'previous version')+delta,'score-explain'));
    if(p.comparable_coverage_and_basis===false)section.append(el('p',
      'Coverage or scoring basis changed, so these averages may not be comparable.','score-explain'));
    if(p.changed&&typeof p.changed==='object')Object.entries(p.changed).forEach(([id,pair])=>{
      let dim=card.dimensions.find(d=>d.id===id);
      if(Array.isArray(pair)&&pair.length===2&&pair.every(value=>typeof value==='number'&&Number.isFinite(value)))
        section.append(el('p',(dim?dimensionLabel(dim):dimensionName(id))+': '+pair[0]+'/10 \u2192 '+
          pair[1]+'/10','score-explain'))})}
  (Array.isArray(card.not_scored)?card.not_scored:[]).filter(d=>d&&typeof d==='object').forEach(d=>
    section.append(el('p',(d.label||dimensionName(d.id))+' not scored: '+
      (d.reason||'no evidence provided'),'score-explain')));
}
function renderPart(id,work){try{work()}catch(error){console.warn('Could not show '+id+': '+error.message);
  let target=$(id);if(target){target.hidden=false;
    target.textContent='This section is unavailable. Ask your agent to inspect it.'}}}
function render(){
  let m=data.versions[data.current]||{},ticks=reviewed(),items=data.checks.items||[];
  $('title').textContent=data.title||data.status.title||'Screening Room';
  // The film's stated direction, so the person judges the cut against what it set out to do.
  let direction=data.direction||{};$('direction').replaceChildren();
  [['story','The story'],['audience','For'],['takeaway','They leave with']].forEach(([key,label])=>{
    if(direction[key]){let p=el('p');p.append(el('strong',label+': '),document.createTextNode(direction[key]));
      $('direction').append(p)}});
  $('direction').hidden=!$('direction').childNodes.length;
  document.title=$('title').textContent+' \u00b7 Screening Room';
  $('filmInfo').textContent=[m.duration_s?fmt(m.duration_s):'',shape(m.size)].filter(Boolean).join(' \u00b7 ');
  $('version').textContent=shortVersion(data.current)+' \u00b7 '+(age(m.created)||m.label||'current');
  let count={pass:0,look:0,fail:0,you:0,skip:0};items.forEach(i=>{
    if(i.state in count&&!(i.state==='you'&&checkKey(i)&&ticks[checkKey(i)]))count[i.state]++});
  $('readiness').textContent=data.status.line || '';
  if(!live && Object.keys(local().ticks||{}).length)
    $('readiness').textContent+=' \u00b7 local review: '+count.you+' need you';
  let fresh=data.checks.freshness||{};
  $('nextStep').textContent=fresh.state==='out_of_date'?'Next: Run the checks again: '+
    (fresh.changed||[]).slice(0,4).join(', ')+' changed after they ran, so their results no longer count.':
    count.fail?'Next: Review the failed checks below.':
    count.you?'Next: Play the film, then mark the checks that need you.':
    count.look?'Next: Review the checks marked to look at.':
    count.skip?'Next: Review the checks that were not assessed.':'Next: Review the cut and notes.';
  let stageNames={map:['Map','Sources made readable: transcripts, shots and sound levels'],
    plan:['Plan','The film written as a script (the paper edit)'],cut:['Cut','A version rendered from the script'],
    check:['Check','Automatic checks on the file'],screen:['Screen','You watch, listen and leave notes'],
    revise:['Revise','Your notes become a new version'],deliver:['Deliver','Final files, captions and the report']};
  $('stages').replaceChildren();Object.entries(stageNames).forEach(([s,[label,meaning]])=>{
    let pill=el('span',label,'stage '+((data.status.stages||{})[s]||''));pill.title=meaning;$('stages').append(pill)});
  if(!optionVideo&&player.getAttribute('src')!==cutSrc())player.src=cutSrc();
  renderPart('paper',renderPaper);renderPart('strip',renderTimeline);
  renderPart('versionFacts',renderVersionDetails);
  renderPart('checks',()=>renderChecks(items,ticks));renderPart('notes',renderNotes);
  let nextScoreKey=JSON.stringify([data.current,data.scorecard,data.scores,data.scorecard_state]);
  if(nextScoreKey!==scoreKey){scoreKey=nextScoreKey;renderPart('scorecard',renderScorecard)}
  $('approve').disabled=!!ticks.approved;$('approve').textContent=ticks.approved?'Approved':'Approve this version';
  renderPart('decisions',()=>{$('decisions').replaceChildren();
  let decisions=(data.decisions||[]).filter(d=>d&&typeof d==='object');
  $('decisionCard').hidden=!decisions.length;decisions.forEach(d=>{
    let text=[d.version,d.category,d.subject,d.decision,d.by].filter(Boolean).join(' \u00b7 ');
    $('decisions').append(el('div',text,'item'));})});
  renderPart('stripImages',()=>{$('stripImages').replaceChildren();data.strip_images.forEach(path=>{
    let img=el('img');img.src=media(path);img.alt='Screening strip';$('stripImages').append(img)})});
  renderPart('versions',()=>{$('versions').replaceChildren();Object.entries(data.versions).forEach(([v,x])=>{
    let tick=v===data.current?ticks:((data.status.reviewed||{})[v]||{});
    let label=shortVersion(v)+' \u00b7 '+(x.label||'')+(tick.approved?' \u00b7 approved':'')+
      (v===data.current?' \u00b7 current':'');let badge=el('span',label,'version-card');badge.id='version-'+v;
    if(x.parent){let link=el('a',' parent '+shortVersion(x.parent));link.href='#version-'+x.parent;badge.append(link)}
    $('versions').append(badge)})});
  renderPart('blind',()=>{let spots=(data.status.blind_spots||[]).map(s=>{
    if(/captions.*speech|speech.*captions|faster.whisper|onnxruntime|captions_speech/i.test(s))
      return 'Speech was not compared with the captions on this machine.';
    if(/loudness.*preview/i.test(s))return 'Sound level is checked on the final file.';
    if(/pip install|--install /i.test(s))return 'A check could not run on this machine; ask your agent for details.';
    return s});
    $('blind').textContent='Blind spots: '+(spots.join(' \u00b7 ')||'none recorded')});sync();
}
function sync(){
  $('playerLabel').textContent=optionVideo?'Playing an option':shortVersion(data.current);
  if(optionVideo)return;
  let speechLine=at(player.currentTime),picture=visibleAt(player.currentTime),line=speechLine||picture;
  $('clock').textContent=fmt(player.currentTime);
  let visible=picture&&alias(picture),speech=speechLine&&alias(speechLine);
  $('source').textContent=picture?'Picture: '+pictureName(picture)+(speech&&speech!==visible?
    ' \u00b7 Speech: '+sourceName(speech):''):'';
  $('source').title=[visible,speech&&speech!==visible?speech:null].filter(Boolean).join(' / ');
  let n=line&&document.querySelector('.line[data-line="'+line.line+'"]');
  if(n!==active){if(active)active.classList.remove('active');active=n;if(n){n.classList.add('active');
    if(!player.paused)revealLine(n)}}
  let p=document.querySelector('.playhead'),m=data.versions[data.current]||{};
  if(p)p.style.left=Math.min(100,100*player.currentTime/(m.duration_s||player.duration||1))+'%';
  if(loop&&player.currentTime>=loop.end){expectedLoopSeek=loop.start;player.currentTime=loop.start;
    player.play().catch(()=>{})}
  showLoop()
}
// A repeat must never trap playback: it says when it is on, and pausing ends it, so the next play is the whole film
// (a repeat set at 0:00 kept a person inside the first two seconds through pause and play).
function showLoop(){let state=$('loopState');state.hidden=!loop;
  if(loop)state.textContent='Repeating '+fmt(loop.start)+' to '+fmt(loop.end)+
    '. Pause, Stop repeat or select a line to play the whole film.'}
function frameRate(){let raw=String((data.versions[data.current]||{}).fps||'');
  let ntsc={'23.976':24000/1001,'29.97':30000/1001,'59.94':60000/1001};
  if(ntsc[raw])return ntsc[raw];let parts=raw.split('/'),value=Number(parts[0])/(parts.length===2?Number(parts[1]):1);
  return Number.isFinite(value)&&value>0?value:null}
function observeFrame(requested){observedFrame=null;let request=++frameRequest;
  $('frameTime').textContent='Frame stepping is approximate. Requested '+frameFmt(requested)+
    '; waiting for the displayed frame time.';
  player.addEventListener('seeked',()=>{
    if(request!==frameRequest||optionVideo||typeof player.requestVideoFrameCallback!=='function')return;
    player.requestVideoFrameCallback((_,frame)=>{
      if(!optionVideo&&request===frameRequest){observedFrame=frame.mediaTime;$('frameTime').textContent=
        'Frame stepping is approximate. Displayed frame time: '+frameFmt(observedFrame)+'.'}});
  },{once:true});
  setTimeout(()=>{if(request===frameRequest&&observedFrame===null)$('frameTime').textContent=
    'Frame stepping is approximate. Requested '+frameFmt(requested)+'; displayed frame time unavailable.'},1000)}
function stepFrame(direction){let rate=frameRate();loop=null;if(optionVideo)backToCut();player.pause();
  if(!rate){$('frameTime').textContent='Frame rate is unavailable for this version.';return}
  let duration=Number.isFinite(player.duration)?player.duration:(data.versions[data.current]||{}).duration_s;
  let last=Math.max(0,Math.ceil(duration*rate)-1),index=Math.floor(player.currentTime*rate+1e-6)+direction;
  let requested=Math.min(Math.max(0,duration-.001),(Math.max(0,Math.min(last,index))+.5)/rate);
  observeFrame(requested);player.currentTime=requested}
function replayMoment(moment){if(!Number.isFinite(moment))return;loop=null;if(optionVideo)backToCut();
  let duration=Number.isFinite(player.duration)?player.duration:(data.versions[data.current]||{}).duration_s||0;
  $('replayStart').value=Math.max(0,moment-1).toFixed(1);$('replayEnd').value=Math.min(duration,moment+2).toFixed(1);
  $('replay').hidden=false;seekCut(moment);$('replay').scrollIntoView({block:'nearest'});$('replayStart').focus()}
$('stepBack').onclick=()=>stepFrame(-1);$('stepForward').onclick=()=>stepFrame(1);
$('playLoop').onclick=()=>{let start=Number($('replayStart').value),end=Number($('replayEnd').value);
  let duration=Number.isFinite(player.duration)?player.duration:(data.versions[data.current]||{}).duration_s||0;
  if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end<=start||end>duration){
    alert('Choose a start and end within the film, with the end after the start.');return}
  loop={start,end};expectedLoopSeek=start;player.currentTime=start;showLoop();player.play().catch(()=>{})};
$('stopLoop').onclick=()=>{loop=null;player.pause();showLoop()};
player.addEventListener('pause',()=>{if(loop){loop=null;showLoop()}});
function expired(){let banner=$('connection');banner.hidden=false;
  banner.textContent="This link has expired; reopen the room from the agent's link."}
async function post(path,body){let response=await fetch('../api/'+path,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(response.status===403){expired();throw Error($('connection').textContent)}
  if(!response.ok)throw Error(await response.text());let result=await response.json();await poll();
  if(result.grade==='error')throw Error(result.message||'Your score was saved, but the scorecard could not update.');
  if(result.grade==='incomplete'){$('connection').hidden=false;
    $('connection').textContent='Your score was saved; some areas are still waiting for review.'}}
async function answer(id,value){if(live){try{await post('answer',{id,answer:value})}catch(e){alert(e.message)}}else{
  let v=local();v.answers=v.answers||{};v.answers[id]=value;saveLocal(v);render()}}
$('backCut').onclick=()=>backToCut();
$('noteButton').onclick=()=>{if(optionVideo)backToCut();noteAt=player.currentTime;
  let picture=visibleAt(noteAt),speech=at(noteAt),visible=picture&&alias(picture),said=speech&&alias(speech);
  $('noteTime').textContent=fmt(noteAt);$('noteContext').textContent=picture?'\u00b7 Picture: '+pictureName(picture)+
    (said&&said!==visible?' \u00b7 Speech: '+sourceName(said):''):'';
  $('noteForm').hidden=false;$('noteText').focus()};
$('saveNote').onclick=async()=>{
  let text=$('noteText').value.trim();if(!text)return;let line=at(noteAt),picture=visibleAt(noteAt),word=null;
  if(line&&Array.isArray(line.words)){let w=line.words.find(x=>typeof x==='object'&&noteAt>=x.start&&noteAt<x.end);
    if(w)word=w.id;else if(line.words.length===1&&typeof line.words[0]==='string')word=line.words[0]}
  let n={version:data.current,t:noteAt,line:picture?picture.line:null,source:picture?alias(picture):null,
    picture_line:picture&&picture!==line?picture.line:null,picture_source:picture&&picture!==line?alias(picture):null,
    spoken_line:line?line.line:null,spoken_source:line?alias(line):null,word,text,kind:'note',status:'open'};
  try{if(live)await post('notes',n);else{let v=local();v.notes=v.notes||[];v.notes.push(n);saveLocal(v);render()}
    $('noteText').value='';$('noteForm').hidden=true}catch(e){alert(e.message)}
};
$('approve').onclick=async()=>{try{
  let failed=(data.checks.items||[]).some(i=>i.state==='fail') || ((data.checks.summary||{}).fail||0)>0;
  let message=failed?'Checks have failed. Record approval anyway?':'Approve this version?';
  if(!live)message+=' This stays in this browser until you copy it to the agent.';
  if(!confirm(message))return;
  if(live)await post('approve',{version:data.current});else{
    let v=local();v.ticks=v.ticks||{};v.ticks.approved=true;saveLocal(v);render()}}catch(e){alert(e.message)}};
$('copy').onclick=async()=>{let v=local(),payload={version:data.current,notes:v.notes||[],
  answers:v.answers||{},ticks:v.ticks||{}};
  let text='Version '+data.current+'\n'+payload.notes.map(n=>fmt(n.t)+' line '+n.line+
    (n.word?' word '+n.word:'')+': '+n.text).join('\n')+'\nAnswers: '+JSON.stringify(payload.answers)+
    '\nTicks: '+JSON.stringify(payload.ticks)+'\n\n'+JSON.stringify(payload);
  try{await navigator.clipboard.writeText(text);$('copyResult').textContent='Copied'}catch(e){
    let box=el('textarea');box.value=text;$('copyResult').replaceChildren(box);
    box.select();document.execCommand('copy')}
};
let snapshot=JSON.stringify(data);async function poll(){try{
  let r=await fetch('../api/status',{cache:'no-store'});if(r.status===403){expired();return}if(!r.ok){
    $('connection').hidden=false;
    $('connection').textContent='Live update unavailable. Ask your agent to inspect the project.';
    return}$('connection').hidden=true;
  let next=await r.json(),key=JSON.stringify(next);
  if(key!==snapshot){let changed=next.current!==data.current;data=next;snapshot=key;
    if(changed){firstPaper=true;loop=null;if(optionVideo)backToCut(0)}render()}
}catch(e){$('connection').hidden=false;$('connection').textContent='Live connection unavailable.'}}
player.addEventListener('seeking',()=>{if(!loop)return;
  if(expectedLoopSeek!==null&&Math.abs(player.currentTime-expectedLoopSeek)<.01){expectedLoopSeek=null;return}
  expectedLoopSeek=null;if(player.currentTime<loop.start||player.currentTime>=loop.end)loop=null});
player.addEventListener('timeupdate',sync);
// A seek while paused (the seek bar, a frame step, a check's time) brings its line into view; a line in view stays put.
player.addEventListener('seeked',()=>{sync();if(!player.paused||!active)return;
  let box=$('paper').getBoundingClientRect(),row=active.getBoundingClientRect();
  if(row.top<box.top||row.bottom>box.bottom)revealLine(active)});
// J, K and L shuttle as in editing applications: L plays forward and each further L doubles the speed (to 8x); J
// plays backward the same way (browsers cannot play video backward, so it steps back in small seeks); K stops.
let shuttle=0,reverseTimer=null;
function stopReverse(){if(reverseTimer){clearInterval(reverseTimer);reverseTimer=null}}
function showShuttle(){$('shuttle').textContent=shuttle>1?'Playing '+shuttle+'x':shuttle<0?
  'Playing backward'+(shuttle<-1?' '+(-shuttle)+'x':''):''}
function setShuttle(speed){stopReverse();shuttle=speed;loop=null;if(optionVideo)backToCut();
  if(speed>0){player.playbackRate=speed;player.play().catch(()=>{})}
  else{player.playbackRate=1;player.pause();
    if(speed<0)reverseTimer=setInterval(()=>{let next=player.currentTime+speed*.1;
      if(next<=0){player.currentTime=0;setShuttle(0)}else player.currentTime=next},100)}
  showShuttle()}
function filmLength(){return Number.isFinite(player.duration)?player.duration:
  (data.versions[data.current]||{}).duration_s||0}
function seekTo(moment){loop=null;if(optionVideo)backToCut();
  player.currentTime=Math.min(Math.max(0,moment),Math.max(0,filmLength()-.001))}
function toggleKeys(){let legend=$('keyLegend');legend.hidden=!legend.hidden;
  $('keysButton').setAttribute('aria-expanded',String(!legend.hidden))}
$('keysButton').onclick=toggleKeys;
player.addEventListener('play',()=>{if(shuttle<0){stopReverse();shuttle=0;showShuttle()}});
player.addEventListener('pause',()=>{if(shuttle>0){shuttle=0;player.playbackRate=1;showShuttle()}});
function editorKey(e){let key=e.key.length===1?e.key.toLowerCase():e.key;
  if(key==='?'){toggleKeys();return true}
  if(key==='Escape'&&!$('keyLegend').hidden){toggleKeys();return true}
  if(e.ctrlKey||e.metaKey||e.altKey)return false;
  if(key==='l'){let now=shuttle>0?shuttle:player.paused?0:1;setShuttle(now?Math.min(8,now*2):1);return true}
  if(key==='j'){let now=shuttle<0?-shuttle:0;setShuttle(-(now?Math.min(8,now*2):1));return true}
  if(key==='k'){setShuttle(0);return true}
  if(key==='Home'||key==='End'){setShuttle(0);let rate=frameRate()||30;
    seekTo(key==='Home'?0:filmLength()-.5/rate);return true}
  if(key==='ArrowLeft'||key==='ArrowRight'){let direction=key==='ArrowLeft'?-1:1;
    if(e.shiftKey||!player.paused||shuttle<0)seekTo(player.currentTime+direction);else stepFrame(direction);return true}
  return false}
document.addEventListener('keydown',e=>{
  // No key acts while a box has focus: the note, the replay times and any other field get every key typed.
  if(/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)||document.activeElement.isContentEditable)return;
  if(editorKey(e)){e.preventDefault();return}
  // A focused button keeps Space for itself; N still opens a note after any button was clicked.
  if(e.code==='Space'){if(document.activeElement.tagName==='BUTTON')return;
    e.preventDefault();if(shuttle<0)setShuttle(0);else player.paused?player.play():player.pause()}
  // Cancel the key: the note box takes focus on keydown, and the N would otherwise be typed into it.
  else if(e.key.toLowerCase()==='n'&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();$('noteButton').click()}});
render();if(live){poll();setInterval(poll,2000)}
</script></body></html>'''

if __name__ == '__main__':
    sys.exit(main())
