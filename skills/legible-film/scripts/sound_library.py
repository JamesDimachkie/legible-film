#!/usr/bin/env python3
"""Index licensed effects, choose a cue-driven palette, or fetch Openverse audio.

  python -I sound_library.py index sounds --licences licences.csv --out library.json
  python -I sound_library.py pick cues.json library.json --out palette.json --takes 3 --seed 7
  python -I sound_library.py search whoosh --openverse --licence cc0 --max 6 --out sounds

Index walks WAV, FLAC, AIFF/AIF, MP3 and OGG, decoding each source once with
FFmpeg. Native channel/rate metadata comes from ffprobe; analysis uses 48 kHz
stereo. Loudness is FFmpeg EBU R128; short-term LUFS needs 3 seconds and is
null for shorter effects. Active RMS is the labelled fallback for matching
short takes. Sync uses cue_onsets.py's 1 ms hops / 5 ms forward RMS windows,
stamped at the right edge. End is threshold-dependent (-55 dBFS RMS).

CSV columns: path (relative path or glob), licence, source_url, attribution,
date. A nearest-folder licence.json or LICENCE.txt applies to its descendants;
FILE.licence.json overrides the folder, CSV overrides both. Missing grants
are indexed as unlicensed and excluded by pick without --allow-unlicensed.
Records are supplied licence evidence, not independent legal clearance.

Pick ranks tags and measured shape, rejects unsuitable durations, and keeps
variants near the first take's brightness and level. It writes level-matched
24-bit WAV copies in PALETTE_STEM-takes/ so the existing mixer needs no change.
The role's gain_db is 0; take_records hold original hashes and applied gains.
No music, limiter, playback or quality verdict. Every palette remains unheard.

Search uses GET https://api.openverse.org/v1/audio/ with q, license, page_size,
and duration=short; only exact cc0/by results are downloaded (never NC/ND).
One result page, max 20 files, 16 MiB and 20 seconds per file. No credentials.
Unauthenticated API budget: at most one request/second and five/hour, persisted
in the user's cache (or --rate-state). HTTP 429 stops with its
Retry-After reason; no retries. See Openverse's API documentation before use:
https://api.openverse.org/v1/ and
https://docs.openverse.org/api/reference/authentication_and_throttling.html

Needs Python 3.9+, numpy and FFmpeg/ffprobe. --json writes a command report.
Exit 0 complete; 1 indexed errors, rejected downloads or unfilled roles;
2 invalid input, missing tools or unreachable Openverse. Local commands never
use the network. Downloaded bytes are decoded only by FFmpeg, never executed.
"""
import argparse
import csv
import datetime
import fnmatch
import hashlib
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


io, onsets = sibling('sound_io'), sibling('cue_onsets')
find_tool = io.find_tool
RATE = 48000
EXTENSIONS = {'.wav', '.flac', '.aiff', '.aif', '.mp3', '.ogg'}
ALIASES = {'whsh': 'whoosh', 'swsh': 'whoosh', 'swoosh': 'whoosh', 'swish': 'whoosh',
           'impct': 'impact', 'imp': 'impact', 'hit': 'impact', 'boom': 'impact',
           'rise': 'riser', 'swell': 'riser', 'build': 'riser', 'click': 'tick',
           'keys': 'key', 'keyboard': 'key', 'typing': 'key', 'glch': 'glitch'}
FAMILIES = {'impact', 'whoosh', 'riser', 'tick', 'pop', 'key', 'glitch'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tags(text):
    words = re.findall(r'[a-z]+', re.sub(r'([a-z])([A-Z])', r'\1 \2', str(text)).lower())
    return sorted(set(words + [ALIASES[w] for w in words if w in ALIASES]))


def positive_int(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError('must be above zero')
    return value


def tools(a):
    ff, probe = find_tool('ffmpeg', a.ffmpeg), find_tool('ffprobe', a.ffprobe)
    if not ff or not probe:
        raise ValueError('FFmpeg and ffprobe are required (PATH, environment, or --ffmpeg/--ffprobe)')
    return ff, probe


def licence_record(value, evidence):
    if not isinstance(value, dict):
        raise ValueError('licence record must be an object: ' + str(evidence))
    grant = str(value.get('licence', value.get('license', '')) or '').strip()
    valid = bool(grant) and grant.lower() not in ('unknown', 'unlicensed', 'none', 'null', 'n/a')
    return {'licensed': valid, 'licence': grant if valid else 'unlicensed',
            'source': value.get('source_url', value.get('source URL', value.get('source', ''))),
            'attribution': value.get('attribution', value.get('attribution_text', value.get('attribution text', ''))),
            'date': value.get('date', ''), 'creator': value.get('creator', ''), 'evidence': str(evidence),
            'licence_url': value.get('licence_url', value.get('license_url', ''))}


def licences_csv(path):
    if not path:
        return []
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or 'path' not in reader.fieldnames or 'licence' not in reader.fieldnames:
            raise ValueError('licences CSV needs path and licence columns')
        return list(reader)


def licence_for(path, root, rows, csv_path):
    relative = path.relative_to(root).as_posix()
    matches = [r for r in rows if r.get('path') and
               (fnmatch.fnmatchcase(relative, r['path'].replace('\\', '/')) or
                str(path).replace('\\', '/') == r['path'].replace('\\', '/'))]
    if matches:
        matches.sort(key=lambda r: (not any(c in r['path'] for c in '*?['), len(r['path'])))
        return licence_record(matches[-1], csv_path)
    sidecar = Path(str(path) + '.licence.json')
    if sidecar.is_file():
        return licence_record(read_json(sidecar), sidecar)
    folder = path.parent
    while folder == root or root in folder.parents:
        record = folder / 'licence.json'
        if record.is_file():
            return licence_record(read_json(record), record)
        record = folder / 'LICENCE.txt'
        if record.is_file():
            text = record.read_text(encoding='utf-8-sig').strip()
            return licence_record({'licence': text, 'source': str(record)}, record)
        folder = folder.parent
    return licence_record({}, '')


def envelope(x, mono=False, padding=0):
    """Bounded PCM blocks; identical 5 ms/1 ms windows, including overlap."""
    total = len(x) + 2 * padding
    values = []
    for start in range(0, total - 239, RATE):
        stop = min(total, start + RATE + 192)
        block = np.zeros((stop - start, 2), dtype=np.float64)
        lo, hi = max(start, padding), min(stop, len(x) + padding)
        if hi > lo:
            block[lo - start:hi - start] = x[lo - padding:hi - padding]
        if not np.isfinite(block).all():
            raise ValueError('audio contains non-finite samples')
        if mono:
            # Match cue_onsets' FFmpeg mono downmix of stereo: sum/sqrt(2).
            # Equal-power downmix level matters for threshold-dependent ends.
            y = block.mean(axis=1) * math.sqrt(2)
            energy = y ** 2
        else:
            energy = np.mean(block ** 2, axis=1)
        cs = np.r_[0., np.cumsum(energy)]
        starts = np.arange(0, len(block) - 239, 48)
        values.append(np.sqrt(np.maximum(0, (cs[starts + 240] - cs[starts]) / 240)))
    return np.concatenate(values) if values else np.zeros(0)


def signal_points(x):
    # Initialise the existing detector from bounded-block RMS measurements.
    # Padding lets cue_onsets see attacks at sample zero and terminal cuts.
    sig = onsets.Signal(np.zeros(240), 9., -55.)
    sig.env = 20 * np.log10(envelope(x, mono=True, padding=960) + 1e-9)
    sig.rise = np.zeros_like(sig.env)
    sig.rise[3:] = sig.env[3:] - sig.env[:-3]
    lo, hi = 3, len(sig.env) - 1
    result, found = {}, {}
    for kind in ('attack', 'apex', 'end'):
        start, stop = lo, hi
        audible = np.flatnonzero(sig.env >= -55.)
        if kind == 'end' and len(audible):
            # Look at the final audible region, not an internal pause/notch.
            start = max(lo, int(audible[-1]) - 12)
            stop = min(hi, int(audible[-1]) + 30)
        if kind == 'attack':
            hits = np.flatnonzero((sig.rise >= 9.) & (sig.env >= -55.))
            if len(hits):
                stop = min(hi, int(hits[0]) + 5)
        ok, k, strength = getattr(sig, kind)(start, stop)
        if not ok and len(audible):
            k = int(audible[0] if kind == 'attack' else audible[-1])
        result[kind] = max(0., min(len(x) / RATE, (k + onsets.LAG) / 1000 - .020))
        found[kind] = bool(ok)
    return result, found


def features(x, meter_text):
    n = len(x)
    if n < 240:
        raise ValueError('audio needs at least 5 ms of finite samples')
    # Sum channel energies for shape/spectrum; mono fold-down only for cue sync.
    env = envelope(x)
    peak, mid_power, side_power = 0., 0., 0.
    for start in range(0, n, RATE):
        block = np.asarray(x[start:start + RATE], dtype=np.float64)
        peak = max(peak, float(np.max(np.abs(block))))
        mid_power += float(np.sum(((block[:, 0] + block[:, 1]) / 2) ** 2))
        side_power += float(np.sum(((block[:, 0] - block[:, 1]) / 2) ** 2))
    active = env > max(1e-6, float(env.max()) * .01)
    active_rms = float(np.sqrt(np.mean(env[active] ** 2))) if active.any() else 0.
    # First local peak reaching 25% of global envelope maximum, then 10/90% rise.
    local = np.flatnonzero((env[1:-1] >= env[:-2]) & (env[1:-1] > env[2:]) &
                          (env[1:-1] >= env.max() * .25)) + 1
    first = int(local[0]) if len(local) else int(np.argmax(env))
    before = env[:first + 1]
    ten = np.flatnonzero(before >= env[first] * .1)
    ninety = np.flatnonzero(before >= env[first] * .9)
    rise = max(0., (int(ninety[0]) - int(ten[0])) / 1000) if len(ten) and len(ninety) else 0.
    # Welch-style bounded FFT blocks; avoid one giant FFT for long recordings.
    width = min(4096, n)
    power = np.zeros(width // 2 + 1)
    window = np.hanning(width)
    for start in range(0, n - width + 1, max(1, width // 2)):
        block = np.asarray(x[start:start + width], dtype=np.float64)
        power += np.sum(np.abs(np.fft.rfft(block * window[:, None], axis=0)) ** 2, axis=1)
    f = np.fft.rfftfreq(width, 1 / RATE)
    total = max(float(power.sum()), 1e-30)
    bands = {'low': float(power[f < 250].sum() / total),
             'mid': float(power[(f >= 250) & (f < 4000)].sum() / total),
             'high': float(power[f >= 4000].sum() / total)}
    active_indices = np.flatnonzero(active)
    body = env[active_indices[0]:active_indices[-1] + 1] if len(active_indices) else env
    bins = np.array([np.mean(s ** 2) for s in np.array_split(body, min(10, len(body)))])
    rising = float(np.corrcoef(np.arange(len(bins)), bins)[0, 1]) if np.std(bins) > 1e-15 else 0.
    points, valid = signal_points(x)
    summary = meter_text.split('Summary:')[-1]
    def meter_value(pattern):
        hits = re.findall(pattern, summary)
        v = float(hits[-1]) if hits else float('nan')
        return v if math.isfinite(v) else None
    integrated = meter_value(r'I:\s*([-+\w.]+) LUFS')
    if n < .4 * RATE or integrated is None or integrated <= -69.9:
        integrated = None
    short = [float(v) for v in re.findall(r'\bS:\s*([-+\d.]+)', meter_text)]
    short = [v for v in short[29:] if v > -69.9] if n >= 3 * RATE else []
    return {'duration_s': n / RATE, 'analysis_rate': RATE, 'integrated_lufs': integrated,
            'short_term_lufs': {'max': max(short) if short else None,
                                'median': float(np.median(short)) if short else None, 'window_s': 3},
            'true_peak_dbtp': meter_value(r'Peak:\s*([-+\w.]+) dBFS'), 'peak_dbfs': io.db(peak),
            'active_rms_dbfs': io.db(active_rms), 'points_s': points, 'sync_found': valid,
            'attack_rise_s': rise, 'spectral_centroid_hz': float(np.sum(f * power) / total),
            'energy_shares': bands, 'riser_shape': rising, 'end_clean': valid['end'],
            'stereo_width': side_power / max(mid_power + side_power, 1e-30),
            'audible': peak > .001, 'apex_fraction': points['apex'] / (n / RATE),
            'apex_prominence_db': io.db(env.max() / max(float(np.median(body)), 1e-12)),
            'tail_energy_ratio': float(np.mean(body[-max(1, len(body) // 4):] ** 2) /
                                       max(float(np.mean(body[:max(1, len(body) // 4)] ** 2)), 1e-30))}


def measure_file(ffmpeg, ffprobe, path, max_duration=None):
    formats = 'wav,flac,aiff,mp3,ogg'
    probe = io.run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe', '-format_whitelist', formats, '-select_streams', 'a:0',
                    '-show_entries', 'stream=sample_rate,channels:format=format_name', '-of', 'json', str(path)])
    metadata = json.loads(probe.stdout)
    streams = metadata.get('streams', [])
    if not streams:
        raise ValueError('no audio stream')
    # A single decoder feeds both the raw analysis and the R128 meter.
    with tempfile.TemporaryDirectory(prefix='lf-library-') as temp:
        raw = Path(temp) / 'decoded.f32'
        command = [ffmpeg, '-hide_banner', '-nostdin', '-y', '-v', 'info', '-protocol_whitelist', 'file,pipe',
                   '-format_whitelist', formats, '-i', str(path), '-filter_complex',
                   '[0:a:0]asplit=2[p][m];[p]aresample=48000,aformat=channel_layouts=stereo[pcm];'
                   '[m]ebur128=peak=true[meter]', '-map', '[pcm]']
        limit = ['-t', str(max_duration + .001)] if max_duration is not None else []
        command += limit + ['-c:a', 'pcm_f32le', '-f', 'f32le', str(raw), '-map', '[meter]'] + limit + ['-f', 'null', '-']
        r = io.run(command)
        if not raw.stat().st_size or raw.stat().st_size % 8:
            raise ValueError('empty or invalid decoded PCM')
        x = np.memmap(raw, mode='r', dtype='<f4', shape=(raw.stat().st_size // 8, 2))
        try:
            result = features(x, r.stderr.decode(errors='replace'))
        finally:
            x._mmap.close()
    result.update(channels=int(streams[0]['channels']), sample_rate=int(streams[0]['sample_rate']),
                  format=metadata.get('format', {}).get('format_name'))
    return result


def index_library(a):
    ffmpeg, ffprobe = tools(a)
    root = Path(a.library_dir).resolve()
    if not root.is_dir():
        raise ValueError('library directory does not exist: ' + str(root))
    rows, files, errors = licences_csv(a.licences), [], []
    for path in sorted(root.rglob('*')):
        if path.suffix.lower() not in EXTENSIONS or not path.is_file() or path.is_symlink():
            continue
        try:
            record = dict(path=path.relative_to(root).as_posix(), sha256=sha256(path),
                          tags=tags(path.relative_to(root).with_suffix('')))
            record.update(measure_file(ffmpeg, ffprobe, path))
            record.update(licence_for(path, root, rows, a.licences))
            files.append(record)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append({'path': str(path), 'reason': str(exc)})
    result = {'version': 1, 'root': str(root), 'files': files, 'errors': errors,
              'status': 'unheard', 'exit_code': 1 if errors else 0,
              'limit': 'Measured shape and supplied licence records; suitability and rights need review.'}
    io.save_json(a.out or root / 'library.json', result)
    print(f"Indexed {len(files)} files; {sum(not r['licensed'] for r in files)} unlicensed; {len(errors)} errors.")
    return result


def cue_roles(spec):
    events, fps, problems = onsets.validate(spec)
    if problems:
        raise ValueError('; '.join(problems))
    timed = sorted([(onsets.cue_time(ev, fps), ev) for ev in events], key=lambda row: row[0])
    roles = {}
    for i, (t, ev) in enumerate(timed):
        if ev.get('sound') == 'silent':
            continue
        role = ev.get('role')
        if not isinstance(role, str) or not role.strip():
            raise ValueError('every non-silent cue needs a role')
        following = next((s - t for s, e in timed[i + 1:] if s > t), 3.)
        previous = next((t - s for s, e in reversed(timed[:i]) if s < t), max(t, .1))
        roles.setdefault(role, []).append({'sync': ev.get('sync', 'attack'), 'next_s': following,
                                           'previous_s': previous, 't': t})
    return roles


def candidate_score(row, role, cues):
    words = set(tags(role))
    family = next((x for x in ('whoosh', 'riser', 'impact', 'key', 'tick', 'pop', 'glitch') if x in words), None)
    matches = words & set(row['tags'])
    known = FAMILIES & set(row['tags'])
    d = row['duration_s']
    if not row['audible']:
        return None, 'inaudible'
    if family is None and not matches:
        return None, 'custom role has no tag match'
    if known and family and family not in known:
        return None, 'tags identify a different sound family'
    before = row['points_s']
    for cue in cues:
        sync = cue['sync']
        if not row['sync_found'].get(sync):
            return None, sync + ' point is not detectable'
        # Allow designed overlap, but exclude files that swamp the cue spacing.
        if d - before[sync] > max(.25, 2 * cue['next_s']):
            return None, 'tail exceeds cue spacing'
        if sync != 'attack' and before[sync] > max(.4, 2 * cue['previous_s']):
            return None, 'lead exceeds cue spacing'
    cap = {'impact': 3., 'whoosh': 4., 'riser': 12., 'tick': .35, 'pop': .45, 'key': .35, 'glitch': 1.2}.get(family, 6.)
    if d > cap:
        return None, 'duration exceeds role limit'
    sharp = math.exp(-row['attack_rise_s'] / .012)
    central = max(0., 1 - abs(row['apex_fraction'] - .5) * 2)
    decay = max(0., min(1., 1 - row['tail_energy_ratio']))
    rising = max(0., row['riser_shape'])
    bright = min(1., row['spectral_centroid_hz'] / 4000)
    score = 3 * len(matches) / max(1, len(words))
    if family == 'impact':
        score += 3 * sharp + 3 * decay + 2 * (1 - row['apex_fraction'])
    elif family == 'whoosh':
        prominence = min(1., max(0., row.get('apex_prominence_db', 0)) / 6)
        score += 3 * central + prominence + 2 * (1 - sharp) + 2 * (1 - abs(row['riser_shape']))
    elif family == 'riser':
        score += 5 * rising + 2 * row['apex_fraction'] + 2 * row['end_clean']
    elif family in ('tick', 'pop', 'key'):
        score += 2 * bright + 2 * sharp + 2 * math.exp(-d / .15)
    elif family == 'glitch':
        score += bright + sharp + math.exp(-d / .4)
    for cue in cues:
        score += (central if cue['sync'] == 'apex' else rising if cue['sync'] == 'end' else sharp) / len(cues)
    return score, 'tags and measured shape'


def pick_palette(a):
    ffmpeg, _ = tools(a)
    library, spec = read_json(a.library), read_json(a.cues)
    if not isinstance(library, dict) or not isinstance(library.get('files'), list) or not library.get('root'):
        raise ValueError('library needs root and files (run index first)')
    roles = cue_roles(spec)
    root = Path(library['root'])
    if not root.is_absolute():
        root = Path(a.library).resolve().parent / root
    target = Path(a.out or 'palette.json').resolve()
    take_dir = target.parent / (target.stem + '-takes')
    result = {'version': 1, 'rate': RATE, 'seed': a.seed, 'roles': {}, 'status': 'unheard',
              'missing_roles': [], 'attributions': [], 'warnings': [], 'limit': 'Heuristic selection; unheard.'}
    rng = np.random.default_rng(a.seed)
    for role, cues in roles.items():
        ranked, reasons = [], {}
        for row in library['files']:
            if not a.allow_unlicensed and not row.get('licensed'):
                reason, score = 'no licence information', None
            else:
                score, reason = candidate_score(row, role, cues)
            if score is None:
                reasons[reason] = reasons.get(reason, 0) + 1
            else:
                ranked.append((score, float(rng.random()), row))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        rs = {'takes': [], 'sha256': [], 'sync': cues[0]['sync'], 'points_s': [], 'gain_db': 0,
              'take_records': [], 'source': [], 'licence': [], 'attribution': []}
        anchor, seen = None, set()
        for score, tie, row in ranked:
            if len(rs['takes']) >= a.takes:
                break
            if row['sha256'] in seen:
                continue
            if anchor is not None:
                ratio = max(row['spectral_centroid_hz'], 1) / max(anchor['spectral_centroid_hz'], 1)
                if not .5 <= ratio <= 2 or abs(row['active_rms_dbfs'] - anchor['active_rms_dbfs']) > 8:
                    continue
            try:
                source = (root / row['path']).resolve()
                if root.resolve() not in source.parents or not source.is_file():
                    raise ValueError('source missing or outside library')
                if sha256(source) != row['sha256']:
                    raise ValueError('source hash changed since index; reindex')
                x = io.decode(ffmpeg, source, RATE, 2)
                # Use active RMS for sub-3-second one-shots; full ST for long effects.
                loudness = row['short_term_lufs']['max']
                method = 'short_term_lufs_max' if loudness is not None else 'active_rms_dbfs'
                if loudness is not None and row['channels'] == 1:
                    loudness += 10 * math.log10(2)  # mono becomes two equal output channels
                loudness = loudness if loudness is not None else row['active_rms_dbfs']
                gain = min(-23. - loudness, -6. - max(row['peak_dbfs'], row.get('true_peak_dbtp') or row['peak_dbfs']))
                x *= 10 ** (gain / 20)
                points, found = signal_points(x)
                if not all(found[c['sync']] for c in cues):
                    raise ValueError('sync no longer detectable after level matching')
                slug = re.sub(r'[^A-Za-z0-9_-]', '_', role)[:48]
                name = f'{slug}-{hashlib.sha256(role.encode()).hexdigest()[:8]}-{row["sha256"][:12]}.wav'
                take = take_dir / name
                io.write_wav(ffmpeg, take, x, RATE)
            except (OSError, ValueError) as exc:
                reason = str(exc)
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            anchor = anchor or row
            seen.add(row['sha256'])
            relative = take.relative_to(target.parent).as_posix()
            record = {'file': relative, 'sha256': sha256(take), 'sync': rs['sync'],
                      'points_s': points, 'gain_db': gain, 'gain_baked_into_file': True,
                      'matching_metric': method, 'matched_level': loudness + gain,
                      'source_file': str(source), 'source_sha256': row['sha256'],
                      'source': row.get('source', ''), 'licence': row['licence'],
                      'attribution': row.get('attribution', ''), 'licence_evidence': row.get('evidence', ''),
                      'score': score}
            rs['takes'].append(relative); rs['sha256'].append(record['sha256'])
            rs['points_s'].append(points[rs['sync']]); rs['take_records'].append(record)
            for key in ('source', 'licence', 'attribution'):
                rs[key].append(record[key])
            credit = record['attribution']
            if credit and credit not in result['attributions']:
                result['attributions'].append(credit)
            if not row.get('licensed'):
                result['warnings'].append(f'{role}: UNLICENSED take selected by explicit override')
        if rs['takes']:
            result['roles'][role] = rs
        else:
            reason = ('library has no indexed audio' if not library['files'] else
                      'no eligible licensed candidate' if not a.allow_unlicensed else 'no eligible candidate')
            result['missing_roles'].append({'role': role, 'reason': reason, 'rejections': reasons})
        print(f"{role}: {len(rs['takes'])} take(s)" + ('' if rs['takes'] else '; ' + json.dumps(reasons)))
    result['exit_code'] = 1 if result['missing_roles'] or result['warnings'] else 0
    io.save_json(target, result)
    print('Delivery attribution lines:')
    for line in result['attributions']:
        print('  ' + line)
    if not result['attributions']:
        print('  None supplied. Review the source licence records before delivery.')
    return result


def public_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError('download requires a public HTTPS URL')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('download URL resolves to a non-public address')
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Openverse answered a query in about 34 s on 2026-10-28; slow public APIs need room.
FETCH_TIMEOUT = 90


def fetch(url, limit):
    public_url(url)
    request = urllib.request.Request(url, headers={'User-Agent': 'LegibleFilm/1.2 sound-library (no authentication)'})
    with urllib.request.build_opener(PublicRedirect()).open(request, timeout=FETCH_TIMEOUT) as response:
        if int(response.headers.get('Content-Length', '0')) > limit:
            raise ValueError('download exceeds byte limit')
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('download exceeds byte limit')
        return data


def reserve_request(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive lock also coordinates separate search processes using this state.
    lock = Path(str(path) + '.lock')
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Openverse rate state locked by another process: ' + str(lock))
    try:
        os.close(fd)
        now = time.time()
        recent = read_json(path) if path.is_file() else []
        recent = [float(t) for t in recent if now - float(t) < 3600]
        if len(recent) >= 5:
            raise ValueError('Openverse anonymous budget exhausted (5/hour); retry after ' + str(math.ceil(3600 - (now - recent[0]))) + ' s')
        if recent and now - recent[-1] < 1.1:
            time.sleep(1.1 - (now - recent[-1]))
        io.save_json(path, recent + [time.time()])
    finally:
        lock.unlink()


def search_openverse(a):
    global FETCH_TIMEOUT
    FETCH_TIMEOUT = getattr(a, "timeout", FETCH_TIMEOUT)
    ffmpeg, ffprobe = tools(a)
    if not a.openverse:
        raise ValueError('search currently requires --openverse')
    if a.max > 20:
        raise ValueError('--max must be 1..20')
    out = Path(a.out or 'openverse-sounds').resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = a.rate_state or Path.home() / '.cache' / 'legible-film' / 'openverse-requests.json'
    reserve_request(state)
    query = urllib.parse.urlencode({'q': a.query, 'license': a.licence or 'cc0,by',
                                    'page_size': a.max, 'duration': 'short'})
    try:
        payload = json.loads(fetch('https://api.openverse.org/v1/audio/?' + query, 4 * 1024 * 1024))
    except (OSError, ValueError) as exc:
        raise ValueError('Openverse API unreachable: ' + str(exc) +
                         (f'; Retry-After {exc.headers.get("Retry-After", "unspecified")}' if isinstance(exc, urllib.error.HTTPError) and exc.code == 429 else ''))
    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        raise ValueError('Openverse API returned an invalid results object')
    result = {'query': a.query, 'downloaded': [], 'rejected': [], 'status': 'unheard'}
    for item in payload['results'][:a.max]:
        try:
            if not isinstance(item, dict):
                raise ValueError('result is not an audio object')
            code = str(item.get('license', '')).lower()
            if code not in ('cc0', 'by') or (a.licence and code != a.licence):
                raise ValueError('only the requested exact CC0/CC BY licence is allowed')
            version = str(item.get('license_version', ''))
            if version not in (('1.0',) if code == 'cc0' else ('1.0', '2.0', '2.5', '3.0', '4.0')):
                raise ValueError('missing or unsupported licence version')
            seconds = float(item.get('duration', 0)) / 1000  # API duration is milliseconds.
            if not 0 < seconds <= 20:
                raise ValueError('not a small effect (duration must be <=20 seconds)')
            url = item.get('url')
            data = fetch(url, 16 * 1024 * 1024)
            identity = hashlib.sha256(str(item.get('id', url)).encode()).hexdigest()[:16]
            folder = out / (re.sub(r'[^A-Za-z0-9_-]', '_', a.query)[:40] + '-' + identity)
            folder.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='lf-fetch-') as temp:
                raw = Path(temp) / 'download.bin'
                raw.write_bytes(data)
                measured = measure_file(ffmpeg, ffprobe, raw, max_duration=20)
                if measured['duration_s'] > 20:
                    raise ValueError('decoded duration exceeds 20 seconds')
                # Choose the extension from FFmpeg's detected format, never a remote name.
                extension = {'wav': 'wav', 'aiff': 'aiff', 'flac': 'flac', 'mp3': 'mp3', 'ogg': 'ogg'}.get(measured['format'])
                if not extension:
                    raise ValueError('unsupported decoded audio format')
                path = folder / ('audio.' + extension)
                path.write_bytes(data)
            licence_url = ('https://creativecommons.org/publicdomain/zero/1.0/' if code == 'cc0' else
                           f'https://creativecommons.org/licenses/by/{version}/')
            source = item.get('foreign_landing_url', '')
            creator = item.get('creator') or 'Creator not supplied'
            title = item.get('title') or 'Untitled audio'
            attribution = f'"{title}" by {creator} ({source}), CC {"0" if code == "cc0" else "BY"} {version} ({licence_url}). Level adjusted.'
            record = {'source_url': source, 'download_url': url, 'creator': creator,
                      'licence': 'CC0 1.0' if code == 'cc0' else 'CC BY ' + version,
                      'licence_url': licence_url, 'attribution': attribution,
                      'date': datetime.date.today().isoformat(), 'title': title,
                      'openverse_id': item.get('id'), 'sha256': sha256(path),
                      'limit': 'Openverse metadata, not independently verified at source.'}
            io.save_json(folder / 'licence.json', record)
            result['downloaded'].append(dict(record, file=str(path)))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            result['rejected'].append({'id': item.get('id') if isinstance(item, dict) else None, 'reason': str(exc)})
    result['exit_code'] = 1 if result['rejected'] or not result['downloaded'] else 0
    io.save_json(out / ('search-' + hashlib.sha256(a.query.encode()).hexdigest()[:12] + '.json'), result)
    print(f"Downloaded {len(result['downloaded'])}; rejected {len(result['rejected'])}. Unheard.")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    index = sub.add_parser('index', help='decode once and measure a local library')
    index.add_argument('library_dir'); index.add_argument('--licences'); index.add_argument('--out')
    pick = sub.add_parser('pick', help='fill an existing-format palette for the cue roles')
    pick.add_argument('cues'); pick.add_argument('library'); pick.add_argument('--out')
    pick.add_argument('--takes', type=positive_int, default=3); pick.add_argument('--seed', type=int, default=7)
    pick.add_argument('--allow-unlicensed', action='store_true')
    search = sub.add_parser('search', help='fetch only CC0 or CC BY Openverse effects')
    search.add_argument('query'); search.add_argument('--openverse', action='store_true')
    search.add_argument('--licence', choices=('cc0', 'by')); search.add_argument('--max', type=positive_int, default=6)
    search.add_argument('--timeout', type=positive_int, default=90, help='seconds to wait for each request (default 90)')
    search.add_argument('--out'); search.add_argument('--rate-state', help='shared local rate-budget JSON path')
    for parser in (index, pick, search):
        parser.add_argument('--json'); parser.add_argument('--ffmpeg'); parser.add_argument('--ffprobe')
    a = p.parse_args()
    try:
        if getattr(a, 'seed', 0) < 0:
            raise ValueError('--seed must be non-negative')
        result = {'index': index_library, 'pick': pick_palette, 'search': search_openverse}[a.command](a)
        if a.json:
            io.save_json(a.json, result)
        return result['exit_code']
    except (OSError, ValueError, TypeError, KeyError, OverflowError, AttributeError) as exc:
        print('sound_library.py: ' + str(exc), file=sys.stderr)
        if a.json:
            try:
                io.save_json(a.json, {'exit_code': 2, 'error': str(exc), 'command': a.command})
            except OSError:
                pass
        return 2


if __name__ == '__main__':
    sys.exit(main())
