#!/usr/bin/env python3
"""Load a cue list (cues.json v1 or v2), check it against the picture it was exported from, and fingerprint pictures.

  python cue_list.py cues.json [--owner PATH] [--json]       the list's state against its owner
  python cue_list.py fingerprint page|picture|paper PATH [--json] [--timing-out FILE]
  python cue_list.py freeze PAGE [--json] [--offline] [--entry index.html]
                                                            keep a frozen copy of a page for export and render
  python cue_list.py scan PAGE FILE... [--json]             the references of files a page loaded at run time

Every tool that reads a cue list calls load(path, owner=None). The owner is a page folder, a video file, or a
cuts/vNNN folder (its manifest.json); None resolves the list's picture.path beside the list. States:

  fresh        the owner's identity equals the list's: a page's files byte for byte (source_files), a video's
               picture stream and frame schedule, a paper edit's film.md and sources.
  unverified   the list cannot be checked: no owner resolvable, an owner of another kind, a stream without
               timestamps, a display transform other than quarter turns and flips. A look that says so.
  unversioned  a v1 list (no picture identity). A look.
  unbound      a plan list ({"kind": "plan", "sha256": null}). Only project.py add-version and the planning writers
               accept it (load(..., allow_plan=True)); every other reader refuses it: "unbound plan: register the
               master first".
  stale        the owner changed since export: exit 2, "stale: re-export". For a page, any added, removed or changed
               file, line endings alone included; when only line endings differ the refusal says "stale: line
               endings changed since export; re-export".

A v2 list's top-level provenance says where its times came from: exported (the default when absent), observed
(anchors read off a finished picture, confirmed on frames), plan (an unbound plan list), or plan-bound (the copy
add-version writes once it binds a plan). An unknown version, a v2 list without picture.sha256 that is not a plan,
an unknown provenance and a malformed v2 event are errors (exit 2), never legacy. v1 lists parse as before: readers validate their own fields; in memory a v1 event has scale
contact, a v1 silent cue's window_ms either side of t is its silence span, and a v1 audible cue's window_ms stays its
onset search window. A rational fps ("24000/1001") reaches readers as a float, with fps_exact beside it.

Identity, one function per kind (fingerprint):
  page     SHA-256 over every file a render reads (sorted paths, each by file_digest) plus the URL and SHA-256 of
           every vendored network file. Excluded: top-level qa/, audio/, node_modules, __pycache__, renders/,
           snapshots/, dist/, coverage/, every top-level dot entry (.git, .hyperframes/, .lf-frozen/), the export
           files cues.json, reading.json, captions.srt, captions.vtt, palette.json, sound-edits.json, and whatever
           a .hyperframesignore in the folder matches (gitignore rules). The fingerprint names a page across
           platforms; freshness and binding rest on exact bytes (source_files, snapshot_sha256).
  picture  the packet hash of the first video stream (ffmpeg -c copy -f hash), its display geometry (sizes, sample
           aspect ratio, the display matrix whole and, for quarter turns and flips, one canonical form, any crop)
           and its frame schedule (every presentation time and duration in integer microseconds, the visible span),
           kept as picture-timing.json. Two schedules match when the frame counts are equal and every time
           (measured from the first frame), duration and visible end lies within the larger of 1 ms and a quarter
           frame. A uniform shift of the whole picture is the same picture out of sync, for the sync group.
  paper    SHA-256 of a version's film.md together with its sources' identities (manifest.json).
  plan     {"kind": "plan", "sha256": null}: no identity until add-version binds it.

file_digest(path) hashes text files (.html .js .css .json .md .svg .csv .txt) with CRLF read as LF and every other
file as bytes (digest version lf1), so Windows and Linux agree on a page's fingerprint.

freeze(PAGE) copies the fingerprinted files into PAGE/.lf-frozen/<snapshot_sha256>/, vendors every version-pinned
network URL the page references (fetched once, stored at a fixed local path, the reference rewritten in the copy),
copies a file referenced by ../ or an absolute path from outside the page under _outside/ (a ../ that stays inside
the page is an in-page file, kept in place), and records frozen_files (exact-byte SHA-256 of every file in the copy),
snapshot_sha256 (the SHA-256 of that sorted list), source_files, source_digests (each file's file_digest before any
rewrite) and the vendored URLs. References are read where a page loads from: HTML src, href, srcset and poster; CSS
url() and @import; JS import, export ... from and dynamic import(). A URL in a data string is not a reference; a
request made at run time is caught by export interception. Closure covers what the render reads: freeze scans the
entry page (--entry, default index.html) and every page file its static references reach, transitively (a
HyperFrames data-composition-src included); the cue export then scans every other file it saw the page load
(cue_list.py scan). A file none of these reach is copied and fingerprinted but not scanned; the record lists it in
not_scanned and the cue list as not loaded, not scanned. An unpinned URL, a fetch that failed, an outside
reference, or a reference to an excluded file in the page makes the binding unverified. --offline fetches nothing.

Exit 0 fresh (or a fingerprint or freeze written), 1 a look (unverified, unversioned, unbound), 2 stale or an error.
"""
import argparse
import copy
import fractions
import hashlib
import json
import math
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

DIGEST = 'lf1'
TEXT_EXTENSIONS = ('.html', '.js', '.css', '.json', '.md', '.svg', '.csv', '.txt')
EXPORTS = ('cues.json', 'reading.json', 'captions.srt', 'captions.vtt')
EXPORT_FILES = EXPORTS + ('palette.json', 'sound-edits.json')
SKIP_TOP = frozenset({'qa', 'audio', '.git', 'node_modules', '__pycache__'})
ENGINE_TOP = frozenset({'renders', 'snapshots', 'dist', 'coverage'})
IGNORE_FILE = '.hyperframesignore'
FROZEN_DIR = '.lf-frozen'
FROZEN_RECORD = '.lf-frozen.json'
STATES = ('fresh', 'unverified', 'unversioned', 'unbound', 'stale')
KINDS = ('page', 'paper', 'picture', 'plan')
SCALES = ('turn', 'follow', 'contact', 'silence')
CLOCKS = ('speech', 'music', 'action', 'silence')
SOUNDS = ('required', 'silent', 'optional')
SYNCS = ('attack', 'apex', 'end')
SCOPES = ('new', 'effects', 'all')
PROVENANCES = ('exported', 'observed', 'plan', 'plan-bound')
UNBOUND_MESSAGE = 'unbound plan: register the master first'
STALE_MESSAGE = 'stale: re-export'
LINE_ENDINGS_MESSAGE = 'stale: line endings changed since export; re-export'
HEX64 = re.compile(r'[0-9a-f]{64}$')


class CueListError(ValueError):
    """The list cannot be read as written (exit 2)."""


class StaleCueList(CueListError):
    """The list's picture changed since export (exit 2, "stale: re-export")."""


class UnboundPlan(CueListError):
    """A plan list reached a reader that needs a bound picture."""


# ================================================================ digests

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    """The SHA-256 of a file's exact bytes."""
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def file_digest(path):
    """The cross-platform per-file digest (lf1): text files with CRLF read as LF, other files as bytes."""
    path = Path(path)
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return sha256_bytes(path.read_bytes().replace(b'\r\n', b'\n'))
    return sha256_file(path)


def canonical(obj):
    """Canonical JSON bytes: sorted keys, no spaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def snapshot_hash(frozen_files):
    """snapshot_sha256: the SHA-256 of the sorted path and exact-byte hash list of a frozen copy."""
    return sha256_bytes(canonical({str(k): str(v) for k, v in frozen_files.items()}))


# ================================================================ page files

def _glob_regex(pattern):
    """Translate one gitignore glob (no leading ! or trailing /) to a regex body."""
    out, i = [], 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
            continue
        if pattern.startswith('/**', i) and i + 3 == len(pattern):
            out.append('/.*')
            i += 3
            continue
        if pattern.startswith('**', i):
            out.append('.*')
            i += 2
            continue
        if c == '*':
            out.append('[^/]*')
        elif c == '?':
            out.append('[^/]')
        elif c == '[':
            end = pattern.find(']', i + 1)
            if end == -1:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1:end]
                if body.startswith('!'):
                    body = '^' + body[1:]
                out.append('[' + body.replace('\\', '\\\\') + ']')
                i = end
        elif c == '\\' and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 1
        else:
            out.append(re.escape(c))
        i += 1
    return ''.join(out)


class IgnoreRules:
    """The rules of one .hyperframesignore, applied as gitignore applies them (last match wins; a file below an
    ignored folder cannot be re-included)."""

    def __init__(self, text=''):
        self.rules = []
        for line in text.splitlines():
            line = line.rstrip('\r')
            if not line.strip() or line.startswith('#'):
                continue
            if not line.endswith('\\ '):
                line = line.rstrip(' ')
            negate = line.startswith('!')
            if negate:
                line = line[1:]
            elif line.startswith('\\!') or line.startswith('\\#'):
                line = line[1:]
            dir_only = line.endswith('/')
            line = line.rstrip('/')
            if not line:
                continue
            anchored = '/' in line
            line = line.lstrip('/')
            body = _glob_regex(line)
            regex = re.compile(('^' if anchored else '^(?:.*/)?') + body + '$')
            self.rules.append((regex, negate, dir_only))

    def _match(self, rel, is_dir):
        ignored = False
        for regex, negate, dir_only in self.rules:
            if dir_only and not is_dir:
                continue
            if regex.match(rel):
                ignored = not negate
        return ignored

    def ignored(self, rel, is_dir=False):
        parts = rel.split('/')
        for n in range(1, len(parts)):
            if self._match('/'.join(parts[:n]), True):
                return True
        return self._match(rel, is_dir)


def excluded_top(name, is_dir):
    """Whether a top-level entry of a page folder is outside its identity."""
    if name.startswith('.'):
        return True
    if is_dir:
        return name in SKIP_TOP or name in ENGINE_TOP
    return name in EXPORT_FILES or name in SKIP_TOP


def ignore_rules(folder):
    path = Path(folder) / IGNORE_FILE
    if path.is_file():
        return IgnoreRules(path.read_text(encoding='utf-8', errors='replace'))
    return IgnoreRules('')


def page_files(folder):
    """Every file of a page folder its identity covers, as sorted POSIX paths relative to the folder."""
    folder = Path(folder)
    if not folder.is_dir():
        raise CueListError(f'not a page folder: {folder}')
    rules = ignore_rules(folder)
    found = []
    for root, dirs, names in os.walk(folder):
        rel_root = Path(root).relative_to(folder).as_posix()
        top = rel_root == '.'
        keep = []
        for d in sorted(dirs):
            rel = d if top else rel_root + '/' + d
            if (top and excluded_top(d, True)) or rules.ignored(rel, True):
                continue
            keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            rel = n if top else rel_root + '/' + n
            if (top and excluded_top(n, False)) or rules.ignored(rel, False):
                continue
            found.append(rel)
    return sorted(found)


def source_files(folder):
    """{path: exact-byte SHA-256} of every file the page identity covers."""
    folder = Path(folder)
    return {rel: sha256_file(folder / rel) for rel in page_files(folder)}


def page_fingerprint(folder, vendored=None, files=None):
    """The page fingerprint: file_digest of each covered file plus the vendored URL and hash pairs."""
    folder = Path(folder)
    names = page_files(folder) if files is None else sorted(files)
    return fingerprint_from_digests({rel: file_digest(folder / rel) for rel in names}, vendored)


def fingerprint_from_digests(digests, vendored=None):
    """The page fingerprint from recorded per-file digests ({path: file_digest}, as a freeze record's
    source_digests holds them) and the vendored URL and hash pairs, so a receipt can be checked without the page."""
    files = {str(k): str(v) for k, v in digests.items()}
    pairs = {str(k): str(v) for k, v in (vendored or {}).items()}
    return sha256_bytes(canonical({'digest': DIGEST, 'files': files, 'vendored': pairs}))


# ================================================================ freeze

# Reference positions, the places a page loads from (BUILD-DECISIONS row 31). A URL in a data string is not a
# reference: requests made at run time are covered by export interception and the render trace or block.
HTML_ATTR = re.compile(r"""(?<![\w-])(?:src|href|srcset|poster)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""", re.I)
LINK_TAG = re.compile(r'<a\s[^>]*>', re.I)
CSS_URL = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)\s]*))\s*\)""", re.I)
CSS_IMPORT = re.compile(r"""@import\s+(?:"([^"]*)"|'([^']*)')""", re.I)
JS_STATIC = re.compile(r"""\b(?:import|export)\s+(?:[\w$*{}\s,]+?\s+from\s+)?(?:"([^"]*)"|'([^']*)')""")
JS_FROM = re.compile(r"""\bexport\s+[\w$*{}\s,]*?\s*from\s+(?:"([^"]*)"|'([^']*)')""")
JS_DYNAMIC = re.compile(r"""\bimport\s*\(\s*(?:"([^"]*)"|'([^']*)'|`([^`$]*)`)\s*\)""")
PINNED = re.compile(r'@(?:\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?|[0-9a-f]{7,40})(?=/|$)|/[0-9a-f]{40}(?=/)')
HTML_TYPES = ('.html', '.htm', '.svg')
CSS_TYPES = ('.css',)
JS_TYPES = ('.js', '.mjs')
SCANNED = HTML_TYPES + CSS_TYPES + JS_TYPES
IGNORED_HOSTS = ('www.w3.org', 'w3.org')


def pinned(url):
    """Whether a URL names an exact version or commit (gsap@3.14.2, a 40-hex commit), never a range or latest."""
    return bool(PINNED.search(url.split('?', 1)[0].split('#', 1)[0]))


def _values(pattern, text):
    for m in pattern.finditer(text):
        value = next((g for g in m.groups() if g is not None), '')
        if value.strip():
            yield value.strip()


def reference_strings(rel, text):
    """Every string in a reference position of one page file: HTML src, href (not a link the viewer follows),
    srcset and poster; CSS url() and @import; JS import, export ... from and dynamic import(). HTML files are read
    for their inline style and script too."""
    found = []
    lower = rel.lower()
    if lower.endswith(HTML_TYPES):
        scrubbed = LINK_TAG.sub('', text)   # <a href> is a link the viewer may follow, not a load
        for m in HTML_ATTR.finditer(scrubbed):
            value = next((g for g in m.groups() if g is not None), '')
            if m.group(0).lower().lstrip().startswith('srcset'):
                found += [part.strip().split()[0] for part in value.split(',') if part.strip()]
            elif value.strip():
                found.append(value.strip())
    if lower.endswith(HTML_TYPES + CSS_TYPES):
        found += list(_values(CSS_URL, text)) + list(_values(CSS_IMPORT, text))
    if lower.endswith(HTML_TYPES + JS_TYPES):
        found += list(_values(JS_STATIC, text)) + list(_values(JS_FROM, text)) + list(_values(JS_DYNAMIC, text))
    return found


def page_references(folder, files):
    """Network URLs, ../ paths and absolute paths in the reference positions of the page's files:
    {kind: {ref: [files]}}."""
    folder = Path(folder)
    found = {'url': {}, 'up': {}, 'absolute': {}}
    for rel in files:
        if not rel.lower().endswith(SCANNED):
            continue
        text = (folder / rel).read_text(encoding='utf-8', errors='replace')
        for ref in reference_strings(rel, text):
            if ref.startswith('//'):
                ref = 'https:' + ref
            if re.match(r'https?://', ref, re.I):
                host = ref.split('/')[2].lower()
                if host not in IGNORED_HOSTS:
                    found['url'].setdefault(ref, []).append(rel)
                continue
            if re.match(r'(?:data|blob|javascript|mailto|about):|#', ref, re.I):
                continue
            path = ref.split('?', 1)[0].split('#', 1)[0]
            if path.startswith('../') or path.startswith('./../'):
                found['up'].setdefault(ref, []).append(rel)
                continue
            if path.startswith('file://'):
                found['absolute'].setdefault(ref, []).append(rel)
                continue
            if re.match(r'[A-Za-z]:[\\/]', path):
                if Path(path).exists():
                    found['absolute'].setdefault(ref, []).append(rel)
                continue
            if path.startswith('/') and not path.startswith('//'):
                if (folder / path.lstrip('/')).exists():
                    continue   # root-relative: the copy is the server root
                if Path(path).is_absolute() and Path(path).exists():
                    found['absolute'].setdefault(ref, []).append(rel)
    return {kind: {ref: sorted(set(users)) for ref, users in refs.items()} for kind, refs in found.items()}


COMPOSITION_SRC = re.compile(r"""(?<![\w-])data-composition-src\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>"']+))""", re.I)


def _local_target(rel, ref):
    """The page-relative path a local reference from file `rel` names (POSIX, normalised), or None for a URL, a
    scheme, a fragment or a path that leaves the folder."""
    if re.match(r'(?:[a-z][a-z0-9+.-]*:|//|#)', ref, re.I):
        return None
    path = ref.split('?', 1)[0].split('#', 1)[0]
    if not path:
        return None
    joined = path.lstrip('/') if path.startswith('/') else posixpath.join(posixpath.dirname(rel), path)
    target = posixpath.normpath(joined)
    return None if target.startswith('..') or target == '.' else target


def reached_files(folder, files, entry='index.html'):
    """The page files the entry page reaches through static references, transitively: every reference position
    reference_strings reads, and a HyperFrames scene's data-composition-src. Sorted; the entry first in the walk."""
    folder = Path(folder)
    known = set(files)
    if entry not in known:
        return sorted(known)   # no entry to walk from: every file is scanned, as before
    seen, queue = {entry}, [entry]
    while queue:
        rel = queue.pop(0)
        if not rel.lower().endswith(SCANNED):
            continue
        text = (folder / rel).read_text(encoding='utf-8', errors='replace')
        refs = list(reference_strings(rel, text))
        if rel.lower().endswith(HTML_TYPES):
            refs += list(_values(COMPOSITION_SRC, text))
        for ref in refs:
            target = _local_target(rel, ref)
            if target in known and target not in seen:
                seen.add(target)
                queue.append(target)
    return sorted(seen)


def classify_local(folder, files, refs):
    """For the ../ and absolute references found: ({(user, ref): (copy path, target)} outside the page, [user ->
    target] inside the folder but outside the identity). A ../ that stays inside the page is an in-page file."""
    folder = Path(folder)
    outside, unidentified = {}, []
    for kind in ('up', 'absolute'):
        for ref, users in sorted(refs[kind].items()):
            for user in users:
                base = folder / os.path.dirname(user)
                raw = ref.split('?', 1)[0].split('#', 1)[0]
                raw = raw[7:] if raw.startswith('file://') else raw
                if re.match(r'/[A-Za-z]:', raw):
                    raw = raw[1:]
                target = Path(raw) if Path(raw).is_absolute() else (base / raw)
                if not target.is_file():
                    continue
                try:
                    inside = Path(os.path.abspath(target)).relative_to(folder).as_posix()
                except ValueError:
                    inside = None
                if inside in files:
                    continue   # a ../ that stays inside the page (the kit's blocks/ importing ../lf/): kept in place
                if inside is not None:
                    unidentified.append(f'{user} -> {inside}')   # inside the folder, outside the identity
                    continue
                outside[(user, ref)] = (_outside_path(folder, target), target)
    return outside, unidentified


def scan_loaded(folder, loaded):
    """What makes a binding unverified in files a page loaded at run time that freeze's static walk did not reach:
    {'files', 'reasons', 'refs'}. Their URLs were never vendored, so any URL in a reference position counts."""
    folder = Path(folder).resolve()
    files = page_files(folder)
    loaded = sorted(rel for rel in set(loaded) if rel in set(files))
    refs = page_references(folder, loaded)
    outside, unidentified = classify_local(folder, files, refs)
    reasons = []
    unpinned_urls = sorted(u for u in refs['url'] if not pinned(u))
    pinned_urls = sorted(u for u in refs['url'] if pinned(u))
    if unpinned_urls:
        reasons.append('unpinned URL (in a file loaded at run time): ' + ', '.join(unpinned_urls))
    if pinned_urls:
        reasons.append('not vendored (in a file loaded at run time): ' + ', '.join(pinned_urls))
    if outside:
        reasons.append('outside reference (in a file loaded at run time): ' + ', '.join(sorted({r for _, r in outside})))
    if unidentified:
        reasons.append('references a file the identity excludes (loaded at run time): ' +
                       ', '.join(sorted(set(unidentified))))
    return {'files': loaded, 'reasons': reasons, 'refs': refs}


def _vendor_path(url):
    name = re.sub(r'[^A-Za-z0-9._-]', '_', url.split('?', 1)[0].rstrip('/').rsplit('/', 1)[-1]) or 'file'
    return '_vendor/' + sha256_bytes(url.encode('utf-8'))[:16] + '-' + name[-80:]


def _outside_path(folder, resolved):
    resolved = Path(os.path.abspath(resolved))
    try:
        rel = Path(os.path.relpath(resolved, Path(folder).resolve()))
        parts = ['_up' if p == '..' else p for p in rel.parts]
    except ValueError:   # another drive
        parts = ['_abs'] + [p.replace(':', '').strip('\\/') for p in resolved.parts if p.strip('\\/')]
    return '_outside/' + '/'.join(parts)


def default_fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'legible-film cue_list freeze'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def _relative(from_file, to_file):
    return os.path.relpath(to_file, os.path.dirname(from_file) or '.').replace(os.sep, '/')


def freeze(folder, fetch=None, offline=False, entry='index.html'):
    """Keep a frozen copy of a page: PAGE/.lf-frozen/<snapshot_sha256>/ holding only its fingerprinted files, pinned
    URLs vendored and outside files copied in. Only the entry page and what its static references reach are scanned;
    every page file is copied and fingerprinted. Returns the record (also written into the copy as .lf-frozen.json)."""
    folder = Path(folder).resolve()
    files = page_files(folder)
    sources = {rel: sha256_file(folder / rel) for rel in files}
    entry = str(entry or 'index.html').split('?', 1)[0].lstrip('/')
    scanned = reached_files(folder, files, entry)
    refs = page_references(folder, scanned)
    fetch = fetch or default_fetch
    reasons, vendored, vendor_files, unpinned, failed = [], {}, {}, [], []
    for url in sorted(refs['url']):
        if not pinned(url):
            unpinned.append(url)
            continue
        if offline:
            failed.append(url)
            continue
        try:
            data = fetch(url)
        except Exception as error:   # any fetch failure leaves the reference live and the binding unverified
            failed.append(url)
            reasons.append(f'could not fetch {url}: {error}')
            continue
        vendored[url] = sha256_bytes(data)
        vendor_files[url] = (_vendor_path(url), data)
    outside, unidentified = classify_local(folder, files, refs)
    if unpinned:
        reasons.append('unpinned URL: ' + ', '.join(unpinned))
    if failed:
        reasons.append('not vendored: ' + ', '.join(failed))
    if outside:
        reasons.append('outside reference: ' + ', '.join(sorted({ref for _, ref in outside})))
    if unidentified:
        reasons.append('references a file the identity excludes: ' + ', '.join(sorted(set(unidentified))))
    digests = {rel: file_digest(folder / rel) for rel in files}   # pre-rewrite, as the fingerprint reads them
    fingerprint_value = fingerprint_from_digests(digests, vendored)
    parent = folder / FROZEN_DIR
    parent.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.tmp-', dir=str(parent)))
    try:
        for rel in files:
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(folder / rel, target)
        for url, (rel, data) in vendor_files.items():
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        for (_, _), (rel, source) in outside.items():
            target = staging / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        rewrites = {}
        for url, (rel, _) in vendor_files.items():
            for user in refs['url'][url]:
                rewrites.setdefault(user, []).append((url, _relative(user, rel)))
        for (user, ref), (rel, _) in outside.items():
            rewrites.setdefault(user, []).append((ref, _relative(user, rel)))
        for user, pairs in rewrites.items():
            path = staging / user
            data = path.read_bytes()
            for old, new in sorted(pairs, key=lambda p: -len(p[0])):
                data = data.replace(old.encode('utf-8'), new.encode('utf-8'))
            path.write_bytes(data)
        frozen = {}
        for root, _, names in os.walk(staging):
            for n in names:
                p = Path(root) / n
                rel = p.relative_to(staging).as_posix()
                if rel != FROZEN_RECORD:
                    frozen[rel] = sha256_file(p)
        frozen = dict(sorted(frozen.items()))
        snapshot = snapshot_hash(frozen)
        record = {'digest': DIGEST, 'fingerprint': fingerprint_value, 'snapshot_sha256': snapshot,
                  'source_files': sources, 'source_digests': digests, 'frozen_files': frozen,
                  'vendored': [{'url': u, 'sha256': vendored[u], 'path': vendor_files[u][0]} for u in sorted(vendored)],
                  'outside': [{'ref': ref, 'from': user, 'path': rel} for (user, ref), (rel, _) in sorted(outside.items())],
                  'unpinned': unpinned, 'binding': 'unverified' if reasons else 'closed', 'reasons': reasons,
                  'entry': entry, 'scanned': scanned, 'not_scanned': [rel for rel in files if rel not in set(scanned)],
                  'copy': f'{FROZEN_DIR}/{snapshot}'}
        # write_bytes keeps LF on every system (Path.write_text has no newline argument before Python 3.10)
        (staging / FROZEN_RECORD).write_bytes((json.dumps(record, indent=1, ensure_ascii=False) + '\n').encode())
        final = parent / snapshot
        if final.is_dir():
            shutil.rmtree(staging, ignore_errors=True)
        else:
            os.replace(staging, final)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return record


def frozen_record(folder, snapshot):
    """The record a kept copy holds, or None."""
    path = Path(folder) / FROZEN_DIR / str(snapshot) / FROZEN_RECORD
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def verify_frozen(copy_dir, frozen_files, snapshot):
    """Problems with a kept copy: files added, missing or changed against frozen_files, or a list that does not hash
    to snapshot. Top-level dot entries are skipped: the copy's own record (.lf-frozen.json) and what an engine writes
    into the project it renders (.hyperframes/); a freeze never copies a top-level dot entry, so none is in the
    snapshot."""
    copy_dir = Path(copy_dir)
    problems = []
    if snapshot_hash(frozen_files) != snapshot:
        problems.append('frozen_files does not hash to snapshot_sha256')
    seen = {}
    for root, dirs, names in os.walk(copy_dir):
        if Path(root) == copy_dir:
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            names = [n for n in names if not n.startswith('.')]
        for n in names:
            p = Path(root) / n
            seen[p.relative_to(copy_dir).as_posix()] = sha256_file(p)
    for rel in sorted(set(seen) | set(frozen_files)):
        if rel not in seen:
            problems.append(f'missing from the copy: {rel}')
        elif rel not in frozen_files:
            problems.append(f'not in the snapshot: {rel}')
        elif seen[rel] != frozen_files[rel]:
            problems.append(f'changed since export: {rel}')
    return problems


# ================================================================ video identity

def find_tool(name):
    explicit = os.environ.get(name.upper())
    if explicit and (os.path.isfile(explicit) or shutil.which(explicit)):
        return explicit
    return shutil.which(name)


def _run(command):
    r = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise CueListError(f'{Path(command[0]).name} could not read the file: ' + r.stderr.strip()[-300:])
    return r.stdout


def parse_rate(value):
    """A frame rate as a Fraction: a number, 'N/D' or 'N'; NTSC decimals (29.97, 23.976) mean N*1000/1001."""
    if isinstance(value, bool) or value is None:
        raise CueListError(f'fps must be a positive number or a rational string, not {value!r}')
    try:
        if isinstance(value, str):
            text = value.strip()
            rate = fractions.Fraction(text) if re.fullmatch(r'\d+(/\d+)?', text) else None
            if rate is None:
                value = float(text)
        if not isinstance(value, str):
            number = float(value)
            if not math.isfinite(number) or number <= 0:
                raise ValueError
            ntsc = number * 1001 / 1000
            if abs(number - round(number)) > 1e-9 and abs(ntsc - round(ntsc)) < 0.01:
                rate = fractions.Fraction(round(ntsc) * 1000, 1001)
            else:
                rate = fractions.Fraction(number).limit_denominator(1001)
    except (ValueError, ZeroDivisionError):
        raise CueListError(f'fps must be a positive number or a rational string, not {value!r}') from None
    if rate <= 0:
        raise CueListError(f'fps must be positive, not {value!r}')
    return rate


def rate_text(rate):
    return f'{rate.numerator}/{rate.denominator}'


def tolerance_us(fps_exact):
    """The larger of 1 ms and a quarter frame at fps_exact, in microseconds."""
    try:
        rate = parse_rate(fps_exact)
    except CueListError:
        return 1000
    return max(1000, int(round(250000 / float(rate))))


def _matrix(stream):
    for side in stream.get('side_data_list') or []:
        if 'display matrix' in str(side.get('side_data_type', '')).lower() and side.get('displaymatrix'):
            try:
                values = [int(n) for line in side['displaymatrix'].strip().splitlines()
                          for n in line.split(':', 1)[-1].split()]
            except ValueError:
                continue
            if len(values) == 9:
                return values
    return None


def canonical_transform(matrix):
    """{'rotate': 0|90|180|270, 'hflip': bool} for a quarter turn with or without a horizontal flip; None for any
    other transform. A horizontal plus a vertical flip is a half turn."""
    if matrix is None:
        return {'rotate': 0, 'hflip': False}
    a, b, u, c, d, v, x, y, w = matrix
    unit = 1 << 16
    if u or v or x or y or w != 1 << 30:
        return None
    if any(value not in (0, unit, -unit) for value in (a, b, c, d)):
        return None
    if (a != 0) == (b != 0) or (c != 0) == (d != 0) or (a != 0) == (c != 0):
        return None
    det = (a * d - b * c) // (unit * unit)
    hflip = det < 0
    if hflip:
        a, c = -a, -c
    rotation = (-math.degrees(math.atan2(b, a))) % 360
    return {'rotate': int(round(rotation)) % 360, 'hflip': hflip}


def _sar(value):
    if not value or value in ('N/A', '0:1', '0:0'):
        return '1:1'
    try:
        n, d = (int(x) for x in str(value).split(':'))
        f = fractions.Fraction(n, d)
        return f'{f.numerator}:{f.denominator}' if n > 0 and d > 0 else '1:1'
    except (ValueError, ZeroDivisionError):
        return '1:1'


def _crop(stream):
    crop = {}
    for key in ('crop_top', 'crop_bottom', 'crop_left', 'crop_right'):
        if isinstance(stream.get(key), int) and stream[key]:
            crop[key[5:]] = stream[key]
    for side in stream.get('side_data_list') or []:
        if 'crop' in str(side.get('side_data_type', '')).lower():
            for key in ('crop_top', 'crop_bottom', 'crop_left', 'crop_right'):
                value = side.get(key)
                if isinstance(value, int) and value:
                    crop[key[5:]] = value
    return crop or None


def geometry(stream):
    """How the picture stream displays, normalised so a remux within MP4, MOV and MKV compares equal."""
    width, height = int(stream.get('width') or 0), int(stream.get('height') or 0)
    coded_w = int(stream.get('coded_width') or 0) or width
    coded_h = int(stream.get('coded_height') or 0) or height
    sar = _sar(stream.get('sample_aspect_ratio'))
    matrix = _matrix(stream)
    transform = canonical_transform(matrix)
    crop = _crop(stream)
    n, d = (int(x) for x in sar.split(':'))
    shown_w = width - ((crop or {}).get('left', 0) + (crop or {}).get('right', 0))
    shown_h = height - ((crop or {}).get('top', 0) + (crop or {}).get('bottom', 0))
    shown_w = int(round(shown_w * n / d))
    if transform and transform['rotate'] in (90, 270):
        shown_w, shown_h = shown_h, shown_w
    return {'width': width, 'height': height, 'coded_width': coded_w, 'coded_height': coded_h, 'sar': sar,
            'display_width': shown_w, 'display_height': shown_h,
            'matrix': matrix or [1 << 16, 0, 0, 0, 1 << 16, 0, 0, 0, 1 << 30],
            'transform': transform, 'crop': crop}


def geometry_compare(listed, actual):
    """(state, reason): 'equal', 'unverified' (equal, but a transform other than quarter turns and flips) or
    'changed'."""
    if not listed or not actual:
        return 'equal', ''
    keys = ('width', 'height', 'coded_width', 'coded_height', 'sar', 'display_width', 'display_height', 'crop')
    for key in keys:
        if listed.get(key) != actual.get(key):
            return 'changed', f'display {key} changed ({listed.get(key)} to {actual.get(key)})'
    if listed.get('transform') and actual.get('transform'):
        if listed['transform'] != actual['transform']:
            return 'changed', f"display transform changed ({listed['transform']} to {actual['transform']})"
        return 'equal', ''
    if listed.get('matrix') != actual.get('matrix'):
        return 'changed', 'display matrix changed'
    return 'unverified', 'the display transform is not a quarter turn or flip, so it is compared exactly and binds unverified'


def picture_identity(path):
    """{'sha256', 'geometry', 'schedule' (None when untimed), 'untimed'} of a file's first video stream."""
    ffmpeg, ffprobe = find_tool('ffmpeg'), find_tool('ffprobe')
    if not ffmpeg or not ffprobe:
        raise CueListError('ffmpeg and ffprobe are needed to identify a picture')
    path = str(path)
    if not os.path.isfile(path):
        raise CueListError(f'no such picture: {path}')
    out = _run([ffmpeg, '-hide_banner', '-nostdin', '-v', 'error', '-i', path, '-map', '0:v:0', '-c', 'copy',
                '-f', 'hash', '-hash', 'sha256', '-'])
    found = re.search(r'SHA256=([0-9a-f]{64})', out)
    if not found:
        raise CueListError(f'no video stream to hash in {path}')
    streams = json.loads(_run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_streams', '-of', 'json',
                               path])).get('streams') or []
    if not streams:
        raise CueListError(f'no video stream in {path}')
    stream = streams[0]
    shape = geometry(stream)
    rate = None
    for key in ('r_frame_rate', 'avg_frame_rate'):
        try:
            candidate = fractions.Fraction(stream.get(key) or '0/0')
            if candidate > 0:
                rate = candidate
                break
        except (ValueError, ZeroDivisionError):
            continue
    base = fractions.Fraction(stream.get('time_base') or '1/1')
    rows = _run([ffprobe, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'packet=pts,duration,flags',
                 '-of', 'compact=p=0:nk=0', path])
    packets, untimed = [], False
    for line in rows.splitlines():
        fields = dict(part.split('=', 1) for part in line.strip().split('|') if '=' in part)
        if not fields:
            continue
        if 'D' in fields.get('flags', ''):
            continue
        if fields.get('pts') in (None, '', 'N/A'):
            untimed = True
            continue
        duration = fields.get('duration')
        packets.append((int(fields['pts']), None if duration in (None, '', 'N/A') else int(duration)))
    schedule = None
    if packets and not untimed:
        packets.sort()
        to_us = lambda ticks: int(round(ticks * base * 1000000))  # noqa: E731
        pts = [to_us(p) for p, _ in packets]
        frame_us = int(round(1000000 / float(rate))) if rate else None
        durations = []
        for i, (p, dur) in enumerate(packets):
            if dur:
                durations.append(to_us(dur))
            elif i + 1 < len(packets):
                durations.append(to_us(packets[i + 1][0] - p))
            else:
                durations.append(frame_us or 0)
        schedule = {'fps_exact': rate_text(rate) if rate else None, 'frames': len(pts), 'pts_us': pts,
                    'duration_us': durations, 'visible_start_us': pts[0],
                    'visible_end_us': max(p + d for p, d in zip(pts, durations))}
    return {'sha256': found.group(1), 'geometry': shape, 'schedule': schedule, 'untimed': untimed or not packets,
            'fps_exact': rate_text(rate) if rate else None}


def schedule_sha256(schedule):
    return sha256_bytes(canonical(schedule))


def timing_block(schedule, pts_file='picture-timing.json'):
    """The identity's timing summary for a schedule: fps_exact, frames, pts_file, pts_sha256 (or untimed)."""
    if schedule is None:
        return {'untimed': True}
    return {'fps_exact': schedule['fps_exact'], 'frames': schedule['frames'], 'pts_file': pts_file,
            'pts_sha256': schedule_sha256(schedule), 'visible_start_us': schedule['visible_start_us'],
            'visible_end_us': schedule['visible_end_us']}


def write_schedule(schedule, path):
    Path(path).write_bytes((json.dumps(schedule, sort_keys=True) + '\n').encode('utf-8'))   # LF on every system


def read_schedule(path, expected_sha256=None):
    """A picture-timing.json, checked against its recorded hash; None when it is missing."""
    path = Path(path)
    if not path.is_file():
        return None
    schedule = json.loads(path.read_text(encoding='utf-8'))
    if expected_sha256 and schedule_sha256(schedule) != expected_sha256:
        raise StaleCueList(f'{STALE_MESSAGE} ({path.name} does not match its recorded pts_sha256)')
    return schedule


def schedule_shift_us(listed, actual):
    """How far the whole picture moved on the container clock (actual minus listed first frame), in microseconds.
    A uniform shift is the same picture out of sync: the sync group reports it; identity does not."""
    return actual['pts_us'][0] - listed['pts_us'][0] if listed['pts_us'] and actual['pts_us'] else 0


def compare_schedules(listed, actual, fps_exact=None):
    """'' when two frame schedules match within tolerance_us, else the first difference. Times are compared from
    each schedule's first frame, so a remux that shifts the whole timeline (Matroska moving everything by the audio
    priming on some FFmpeg builds) keeps the picture's identity, while a retime, a moved frame, a changed frame
    duration or a trimmed visible end does not."""
    tol = tolerance_us(fps_exact or listed.get('fps_exact') or actual.get('fps_exact'))
    if listed['frames'] != actual['frames'] or len(listed['pts_us']) != len(actual['pts_us']):
        return f"the frame count changed ({listed['frames']} to {actual['frames']})"
    a0, b0 = listed['pts_us'][0], actual['pts_us'][0]
    for i, (a, b) in enumerate(zip(listed['pts_us'], actual['pts_us'])):
        if abs((a - a0) - (b - b0)) > tol:
            return f'frame {i} moved {abs((a - a0) - (b - b0)) / 1000:.3f} ms (tolerance {tol / 1000:.3f} ms)'
    for i, (a, b) in enumerate(zip(listed['duration_us'], actual['duration_us'])):
        if abs(a - b) > tol:
            return f'frame {i} lasts {abs(a - b) / 1000:.3f} ms longer or shorter (tolerance {tol / 1000:.3f} ms)'
    for key in ('visible_start_us', 'visible_end_us'):
        if abs((listed[key] - a0) - (actual[key] - b0)) > tol:
            return f'the visible span changed ({key} {listed[key]} to {actual[key]})'
    return ''


# ================================================================ paper identity

def paper_identity(film_md_sha256, sources):
    sources = sources or {}
    return {'kind': 'paper', 'sha256': sha256_bytes(canonical({'film_md_sha256': film_md_sha256, 'sources': sources})),
            'film_md_sha256': film_md_sha256, 'sources': sources}


def read_manifest(folder):
    path = Path(folder) / 'manifest.json'
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as error:
        raise CueListError(f'cannot read {path}: {error}') from None


def is_version(folder):
    folder = Path(folder)
    return folder.is_dir() and (folder / 'manifest.json').is_file()


def fingerprint(kind, path, vendored=None):
    """The identity of a picture by kind: page (a folder), picture (a video file), paper (a cuts/vNNN folder)."""
    path = Path(path)
    if kind == 'page':
        if not path.is_dir():
            raise CueListError(f'not a page folder: {path}')
        return {'kind': 'page', 'sha256': page_fingerprint(path, vendored), 'digest': DIGEST,
                'source_files': source_files(path)}
    if kind == 'picture':
        found = picture_identity(path)
        return {'kind': 'picture', 'sha256': found['sha256'], 'geometry': found['geometry'],
                'timing': timing_block(found['schedule']), 'schedule': found['schedule']}
    if kind == 'paper':
        if not is_version(path):
            raise CueListError(f'not a version folder (no manifest.json): {path}')
        manifest = read_manifest(path)
        return paper_identity(manifest.get('film_md_sha256'), manifest.get('sources') or {})
    raise CueListError(f'unknown fingerprint kind {kind!r}: page, picture or paper')


# ================================================================ the loader

def read_document(path):
    """(document, sha256 of the bytes): UTF-8 (with or without BOM) or BOM-marked UTF-16 JSON."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CueListError(f'cannot read cue file {path}: {error.strerror or error}') from None
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        text = raw.decode(encoding)
    except UnicodeError:
        raise CueListError(f'cannot read cue file {path}: it is not UTF-8 or BOM-marked UTF-16 text') from None
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as error:
        raise CueListError(f'cannot read cue file {path}: invalid JSON at line {error.lineno}, column '
                           f'{error.colno}') from None
    return doc, sha256_bytes(raw)


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_v2(doc, fps):
    """Every reason a v2 document is malformed (an empty list when it is well formed)."""
    problems = []
    sections = doc.get('sections', [])
    events = doc.get('events')
    if not isinstance(sections, list):
        return ['"sections" must be a list']
    if not isinstance(events, list):
        return ['a v2 cue list needs an "events" list']
    section_ids = set()
    for i, section in enumerate(sections):
        if not isinstance(section, dict):
            problems.append(f'section {i} is not an object')
            continue
        sid = section.get('id')
        if not isinstance(sid, str) or not sid:
            problems.append(f'section {i}: id must be text')
            continue
        if sid in section_ids:
            problems.append(f'section {sid!r}: ids must be unique')
        section_ids.add(sid)
        a, b = section.get('a'), section.get('b')
        if not (_finite(a) and _finite(b) and 0 <= a < b):
            problems.append(f'section {sid!r}: a and b must be times with 0 <= a < b')
        if section.get('clock') not in CLOCKS:
            problems.append(f"section {sid!r}: clock must be speech, music, action or silence, not "
                            f"{section.get('clock')!r}")
        gains = section.get('gain_db', {})
        if not isinstance(gains, dict) or not all(isinstance(k, str) and _finite(v) for k, v in gains.items()):
            problems.append(f'section {sid!r}: gain_db must map a bus name to a number')
    ids, follows = set(), set()
    for ev in events:
        if isinstance(ev, dict) and ev.get('scale') == 'follow':
            follows.add(str(ev.get('id')))
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            problems.append(f'event {i} is not an object')
            continue
        eid = ev.get('id')
        if isinstance(eid, bool) or not isinstance(eid, (str, int)) or eid == '':
            problems.append(f'event {i}: id must be text or an integer')
            continue
        name = f'event {eid!r}'
        if str(eid) in ids:
            problems.append(f'{name}: ids must be unique')
        ids.add(str(eid))
        if 't' in ev:
            if not (_finite(ev['t']) and ev['t'] >= 0):
                problems.append(f'{name}: t must be a time in seconds, 0 or more')
        elif 'frame' in ev:
            if not (_finite(ev['frame']) and ev['frame'] >= 0) or not fps:
                problems.append(f'{name}: frame needs a top-level fps and a frame number, 0 or more')
        else:
            problems.append(f'{name} has no time: give t in seconds')
        scale = ev.get('scale')
        if scale not in SCALES:
            problems.append(f'{name}: scale must be turn, follow, contact or silence, not {scale!r}')
        if scale in ('follow', 'silence'):
            start = ev.get('t')
            end = ev.get('t_end')
            if not (_finite(end) and _finite(start) and end > start):
                problems.append(f'{name}: a {scale} span needs t_end after t')
        elif 't_end' in ev and not (_finite(ev['t_end']) and _finite(ev.get('t')) and ev['t_end'] > ev['t']):
            problems.append(f'{name}: t_end must come after t')
        for key, allowed in (('sound', SOUNDS), ('sync', SYNCS)):
            if key in ev and ev[key] not in allowed:
                problems.append(f"{name}: {key} must be {', '.join(allowed)}, not {ev[key]!r}")
        if 'scope' in ev and (scale != 'silence' or ev['scope'] not in SCOPES):
            problems.append(f"{name}: scope belongs to a silence and is new, effects or all, not {ev['scope']!r}")
        if 'window_ms' in ev:
            problems.append(f'{name}: window_ms is not part of v2 (silence is a span; readers take their own '
                            f'onset window)')
        if 'depth' in ev:
            problems.append(f'{name}: depth was deleted in v2')
        for key in ('lead_ms', 'gain_db', 'pitch_st', 'strength'):
            if key in ev and not _finite(ev[key]):
                problems.append(f'{name}: {key} must be a number')
        if 'tolerance_ms' in ev and not (_finite(ev['tolerance_ms']) and ev['tolerance_ms'] > 0):
            problems.append(f'{name}: tolerance_ms must be a positive number')
        for key in ('x', 'y'):
            if key in ev and not (_finite(ev[key]) and -1 <= ev[key] <= 1):
                problems.append(f'{name}: {key} must lie in -1..1')
        if 'pan' in ev and ev['pan'] != 'x' and not (_finite(ev['pan']) and -1 <= ev['pan'] <= 1):
            problems.append(f'{name}: pan must be a number in -1..1 or "x"')
        for key in ('run', 'hero', 'enabled'):
            if key in ev and not isinstance(ev[key], bool):
                problems.append(f'{name}: {key} must be true or false')
        if 'section' in ev and ev['section'] not in section_ids:
            problems.append(f"{name}: section {ev['section']!r} is not a section id")
        if 'span' in ev and str(ev['span']) not in follows:
            problems.append(f"{name}: span {ev['span']!r} names no follow event")
        if 'picture' in ev and not isinstance(ev['picture'], str):
            problems.append(f'{name}: picture must be text')
        if ev.get('picture') == 'held' and not ev.get('decision'):
            problems.append(f'{name}: picture: held needs a decision')
    return problems


def validate_picture(picture):
    """(kind, problems) for a v2 picture block."""
    if not isinstance(picture, dict):
        return None, ['a v2 cue list needs a "picture" object naming what it was exported from']
    kind = picture.get('kind')
    if kind not in KINDS:
        return None, [f'picture.kind must be page, paper, picture or plan, not {kind!r}']
    sha = picture.get('sha256')
    if kind == 'plan':
        return kind, ([] if sha is None else ['a plan list carries no hash; a bound plan is kind picture'])
    if not isinstance(sha, str) or not HEX64.match(sha):
        return kind, [f'a v2 {kind} list needs picture.sha256 (only an unbound plan has none)']
    problems = []
    if kind == 'page':
        files = picture.get('source_files')
        if not isinstance(files, dict) or not files or not all(isinstance(v, str) for v in files.values()):
            problems.append('a page list needs picture.source_files, every covered file by exact-byte SHA-256')
        if not isinstance(picture.get('snapshot_sha256'), str):
            problems.append('a page list needs picture.snapshot_sha256')
    if kind == 'paper':
        if not isinstance(picture.get('film_md_sha256'), str) or not isinstance(picture.get('sources'), dict):
            problems.append('a paper list needs picture.film_md_sha256 and picture.sources')
    return kind, problems


def provenance_of(doc, kind):
    """(provenance, problems): where the list's times came from. `exported` from the owner (the default when the
    field is absent), `observed` (anchors read off a finished picture and confirmed on frames), `plan` (an unbound
    plan list; a plan list without the field reads as plan), `plan-bound` (the copy add-version writes once it binds a
    plan to its master, kind picture)."""
    value = doc.get('provenance')
    if value is None:
        return ('plan' if kind == 'plan' else 'exported'), []
    if value not in PROVENANCES:
        return value, [f"provenance must be {', '.join(PROVENANCES)}, not {value!r}"]
    if (value == 'plan') != (kind == 'plan'):
        return value, [f'provenance {value!r} does not fit picture.kind {kind!r} (only a plan list is a plan)']
    if value == 'plan-bound' and kind != 'picture':
        return value, ['provenance plan-bound belongs to a bound plan, which is kind picture']
    return value, []


class CueList:
    """A loaded cue list: the document as read and its normalised view."""

    def __init__(self, path, doc, sha256, version):
        self.path = Path(path)
        self.doc = doc
        self.sha256 = sha256
        self.version = version
        self.picture = doc.get('picture') if isinstance(doc, dict) and version == 'v2' else None
        self.kind = (self.picture or {}).get('kind')
        self.events = copy.deepcopy(doc.get('events') if isinstance(doc, dict) else doc)
        self.sections = copy.deepcopy(doc.get('sections', [])) if isinstance(doc, dict) and version == 'v2' else []
        self.fps = None
        self.fps_exact = None
        self.state = None
        self.reasons = []
        self.owner = None
        self.provenance = 'exported'

    def set_fps(self, value):
        rate = parse_rate(value)
        self.fps, self.fps_exact = float(rate), rate_text(rate)

    @property
    def message(self):
        reason = '; '.join(self.reasons)
        if self.state == 'fresh':
            return 'fresh'
        if self.state == 'stale':
            return reason if reason.startswith('stale') else f'{STALE_MESSAGE} ({reason})' if reason else STALE_MESSAGE
        if self.state == 'unbound':
            return UNBOUND_MESSAGE
        if self.state == 'unversioned':
            return 'unversioned: a v1 cue list records no picture identity, so it cannot be checked for staleness'
        return f'unverified: {reason}' if reason else 'unverified'

    @property
    def note(self):
        """A look to print beside a reader's output, or None when the list is fresh."""
        return None if self.state == 'fresh' else self.message

    def scale(self, ev):
        """The event's scale; a v1 event is a contact."""
        return ev.get('scale', 'contact') if self.version == 'v2' else 'contact'

    def silence_span(self, ev):
        """(a, b) for a silence: a v2 silence's t..t_end, a v1 silent cue's window_ms either side of t; else None."""
        if self.version == 'v2':
            if ev.get('scale') == 'silence':
                return float(ev['t']), float(ev['t_end'])
            return None
        if ev.get('sound') == 'silent' and _finite(ev.get('window_ms')) and _finite(ev.get('t')):
            w = ev['window_ms'] / 1000
            return ev['t'] - w, ev['t'] + w
        return None

    def onset_window_ms(self, ev, default):
        """The onset search window: a v1 audible cue keeps its window_ms; v2 events take the reader's default."""
        if self.version == 'v1' and ev.get('sound') != 'silent' and _finite(ev.get('window_ms')):
            return float(ev['window_ms'])
        return default

    def as_json(self):
        return {'path': str(self.path), 'version': self.version, 'state': self.state, 'message': self.message,
                'reasons': self.reasons, 'kind': self.kind, 'provenance': self.provenance,
                'owner': str(self.owner) if self.owner else None,
                'fps': self.fps, 'fps_exact': self.fps_exact, 'cues_sha256': self.sha256,
                'events': len(self.events) if isinstance(self.events, list) else None,
                'sections': len(self.sections)}


def _resolve_owner(cl, owner):
    if owner is not None:
        owner = Path(owner)
        if not owner.exists():
            raise CueListError(f'no such owner: {owner}')
        return owner
    rel = (cl.picture or {}).get('path')
    if not isinstance(rel, str) or not rel:
        return None
    candidate = Path(rel) if os.path.isabs(rel) else cl.path.resolve().parent / rel
    return candidate if candidate.exists() else None


def _check_page(cl, owner):
    listed = cl.picture['source_files']
    live = source_files(owner)
    if live == listed:
        return 'fresh', []
    added = sorted(set(live) - set(listed))
    removed = sorted(set(listed) - set(live))
    changed = sorted(rel for rel in set(live) & set(listed) if live[rel] != listed[rel])
    vendored = cl.picture.get('vendored')
    if vendored is None:
        record = frozen_record(owner, cl.picture.get('snapshot_sha256')) or {}
        vendored = record.get('vendored', [])
    pairs = {item['url']: item['sha256'] for item in vendored} if isinstance(vendored, list) else dict(vendored)
    if not added and not removed and page_fingerprint(owner, pairs, list(live)) == cl.picture['sha256']:
        return 'stale', [LINE_ENDINGS_MESSAGE + ' (' + ', '.join(changed[:5]) + ')']
    parts = []
    for label, names in (('added', added), ('removed', removed), ('changed', changed)):
        if names:
            parts.append(f"{label} {', '.join(names[:5])}" + (f' and {len(names) - 5} more' if len(names) > 5 else ''))
    return 'stale', [f"{STALE_MESSAGE} (the page changed since export: {'; '.join(parts)})"]


def _check_picture(cl, owner):
    found = picture_identity(owner)
    listed = cl.picture
    if found['sha256'] != listed['sha256']:
        return 'stale', [f'{STALE_MESSAGE} (the picture stream changed: packet hash differs)']
    state, reason = geometry_compare(listed.get('geometry'), found['geometry'])
    if state == 'changed':
        return 'stale', [f'{STALE_MESSAGE} ({reason})']
    reasons = [reason] if state == 'unverified' else []
    timing = listed.get('timing') or {}
    if timing.get('untimed') or found['untimed']:
        return 'unverified', reasons + ['untimed: the picture stream carries no packet timestamps, so its timing '
                                        'cannot be checked']
    pts_file = timing.get('pts_file')
    schedule = read_schedule(cl.path.resolve().parent / pts_file, timing.get('pts_sha256')) if pts_file else None
    if schedule is None:
        return 'unverified', reasons + ['the list has no frame schedule (picture-timing.json) to compare']
    difference = compare_schedules(schedule, found['schedule'], timing.get('fps_exact'))
    if difference:
        return 'stale', [f'{STALE_MESSAGE} (the picture timing changed: {difference})']
    return ('unverified', reasons) if reasons else ('fresh', [])


def _check_version(cl, owner):
    manifest = read_manifest(owner)
    identity = manifest.get('identity') or {}
    if cl.kind == 'paper':
        if (manifest.get('film_md_sha256') != cl.picture.get('film_md_sha256') or
                (manifest.get('sources') or {}) != cl.picture.get('sources')):
            return 'stale', [f'{STALE_MESSAGE} (the paper edit or a source differs from {owner.name})']
        return 'fresh', []
    if cl.kind == 'page':
        source = identity.get('source') or {}
        if source.get('kind') != 'page':
            return 'unverified', [f'{owner.name} records no page source']
        if (source.get('sha256') != cl.picture['sha256'] or
                source.get('snapshot_sha256') != cl.picture.get('snapshot_sha256')):
            return 'stale', [f'{STALE_MESSAGE} (the page or its snapshot differs from {owner.name})']
        return 'fresh', []
    if cl.kind == 'picture':
        if not identity.get('picture_sha256'):
            return 'unverified', [f'{owner.name} records no picture identity']
        if identity['picture_sha256'] != cl.picture['sha256']:
            return 'stale', [f'{STALE_MESSAGE} (the picture stream differs from {owner.name})']
        state, reason = geometry_compare(cl.picture.get('geometry'), identity.get('geometry'))
        if state == 'changed':
            return 'stale', [f'{STALE_MESSAGE} ({reason} in {owner.name})']
        reasons = [reason] if state == 'unverified' else []
        timing = identity.get('picture_timing') or {}
        listed = cl.picture.get('timing') or {}
        mine = read_schedule(owner / timing['pts_file'], timing.get('pts_sha256')) if timing.get('pts_file') else None
        theirs = (read_schedule(cl.path.resolve().parent / listed['pts_file'], listed.get('pts_sha256'))
                  if listed.get('pts_file') else None)
        if mine is None or theirs is None:
            return 'unverified', reasons + ['a frame schedule is missing, so timing cannot be compared']
        difference = compare_schedules(theirs, mine, listed.get('fps_exact'))
        if difference:
            return 'stale', [f'{STALE_MESSAGE} (the picture timing differs from {owner.name}: {difference})']
        return ('unverified', reasons) if reasons else ('fresh', [])
    return 'unverified', [f'a {cl.kind} list cannot be compared with a version folder']


def check(path, owner=None):
    """Read a cue list and decide its state against its owner. Never raises for stale or unbound (see load)."""
    doc, digest = read_document(path)
    if isinstance(doc, list):
        version = 'v1'
    elif isinstance(doc, dict):
        raw = doc.get('version', 'v1')
        if raw in ('v1', 1, '1'):
            version = 'v1'
        elif raw == 'v2':
            version = 'v2'
        else:
            raise CueListError(f'{path}: unknown cue list version {raw!r} (v1 or v2)')
    else:
        raise CueListError(f'{path}: a cue list is an object with "events"')
    cl = CueList(path, doc, digest, version)
    fps = doc.get('fps') if isinstance(doc, dict) else None
    if version == 'v1':
        if fps is not None:
            try:
                cl.set_fps(fps)
            except CueListError:
                pass   # a v1 reader reports its own fps problem as it always has
        cl.state = 'unversioned'
        return cl
    if fps is not None:
        cl.set_fps(fps)
    kind, problems = validate_picture(doc.get('picture'))
    provenance, wrong = provenance_of(doc, kind)
    problems += wrong
    problems += validate_v2(doc, cl.fps)
    if problems:
        raise CueListError(f'{path} cannot be read as a v2 cue list: ' + '; '.join(problems))
    cl.kind = kind
    cl.provenance = provenance
    if kind == 'plan':
        cl.state = 'unbound'
        return cl
    resolved = _resolve_owner(cl, owner)
    cl.owner = resolved
    if resolved is None:
        cl.state, cl.reasons = 'unverified', ['no owner resolvable: give --owner, or keep picture.path beside the list']
        return cl
    if is_version(resolved):
        cl.state, cl.reasons = _check_version(cl, resolved)
    elif kind == 'page' and resolved.is_dir():
        cl.state, cl.reasons = _check_page(cl, resolved)
    elif kind == 'picture' and resolved.is_file():
        cl.state, cl.reasons = _check_picture(cl, resolved)
    else:
        cl.state, cl.reasons = 'unverified', [f'the owner {resolved} is not what a {kind} list binds to']
    return cl


def load(path, owner=None, allow_plan=False):
    """Load a cue list for a reader: raises StaleCueList for a stale list and UnboundPlan for a plan (unless
    allow_plan), CueListError for an unreadable one; returns the CueList otherwise (its .note is a look or None)."""
    cl = check(path, owner)
    if cl.state == 'stale':
        raise StaleCueList(cl.message)
    if cl.state == 'unbound' and not allow_plan:
        raise UnboundPlan(UNBOUND_MESSAGE)
    return cl


def load_for(prog, path, owner=None, allow_plan=False, stream=None):
    """load(), printing the list's look (unversioned, unverified) to stderr under the reader's name."""
    cl = load(path, owner, allow_plan)
    if cl.note:
        print(f'{prog}: cue list {cl.note}', file=stream or sys.stderr)
    return cl


def upgrade_event(ev):
    """A v1 event in v2 form: scale contact, a silent cue's window_ms either side of t as its span, an audible cue's
    window_ms dropped (v2 readers take their own onset window), depth deleted."""
    ev = dict(ev)
    ev.pop('depth', None)
    window = ev.pop('window_ms', None)
    if ev.get('sound') == 'silent' and _finite(window) and _finite(ev.get('t')):
        w = window / 1000
        ev['t'], ev['t_end'] = max(0.0, ev['t'] - w), ev['t'] + w
        ev.setdefault('scale', 'silence')
    ev.setdefault('scale', 'contact')
    return ev


# ================================================================ CLI

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'fingerprint':
        p = argparse.ArgumentParser(prog='cue_list.py fingerprint', description='The identity of a picture.')
        p.add_argument('kind', choices=('page', 'picture', 'paper'))
        p.add_argument('path')
        p.add_argument('--json', action='store_true')
        p.add_argument('--timing-out', help='write the frame schedule (picture-timing.json) here')
        a = p.parse_args(argv[1:])
        try:
            found = fingerprint(a.kind, a.path)
            if a.timing_out and found.get('schedule'):
                write_schedule(found['schedule'], a.timing_out)
            shown = {k: v for k, v in found.items() if k != 'schedule'}
        except (CueListError, OSError) as error:
            print(f'cue_list.py: {error}', file=sys.stderr)
            return 2
        print(json.dumps(shown, indent=1) if a.json else f"{a.kind} {found['sha256']}")
        return 0
    if argv and argv[0] == 'freeze':
        p = argparse.ArgumentParser(prog='cue_list.py freeze', description='Keep a frozen copy of a page.')
        p.add_argument('page')
        p.add_argument('--json', action='store_true')
        p.add_argument('--offline', action='store_true', help='fetch nothing; pinned URLs stay live (unverified)')
        p.add_argument('--entry', default='index.html', help='the entry page the static walk starts from')
        a = p.parse_args(argv[1:])
        try:
            record = freeze(a.page, offline=a.offline, entry=a.entry)
        except (CueListError, OSError) as error:
            print(f'cue_list.py: {error}', file=sys.stderr)
            return 2
        if a.json:
            print(json.dumps(record, indent=1, ensure_ascii=False))
        else:
            print(f"frozen {record['copy']} · fingerprint {record['fingerprint'][:16]} · binding {record['binding']}"
                  + (f" ({'; '.join(record['reasons'])})" if record['reasons'] else ''))
        return 0
    if argv and argv[0] == 'scan':
        p = argparse.ArgumentParser(prog='cue_list.py scan', description='The references of files a page loaded at '
                                    'run time that the static walk did not reach.')
        p.add_argument('page')
        p.add_argument('files', nargs='*')
        p.add_argument('--json', action='store_true')
        a = p.parse_args(argv[1:])
        try:
            found = scan_loaded(a.page, a.files)
        except (CueListError, OSError) as error:
            print(f'cue_list.py: {error}', file=sys.stderr)
            return 2
        shown = {'files': found['files'], 'reasons': found['reasons']}
        print(json.dumps(shown, indent=1, ensure_ascii=False) if a.json else
              ('; '.join(found['reasons']) or f"{len(found['files'])} file(s): nothing that leaves the page"))
        return 0
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('cues', help='a cues.json (v1 or v2), or the word fingerprint, freeze or scan')
    p.add_argument('--owner', help='a page folder, a video file or a cuts/vNNN folder')
    p.add_argument('--json', action='store_true')
    a = p.parse_args(argv)
    try:
        cl = check(a.cues, a.owner)
    except (CueListError, OSError) as error:
        if a.json:
            print(json.dumps({'path': a.cues, 'state': 'error', 'message': str(error)}, indent=1))
        else:
            print(f'cue_list.py: {error}', file=sys.stderr)
        return 2
    print(json.dumps(cl.as_json(), indent=1) if a.json else f'{a.cues}: {cl.message}')
    return {'fresh': 0, 'stale': 2}.get(cl.state, 1)


if __name__ == '__main__':
    sys.exit(main())
