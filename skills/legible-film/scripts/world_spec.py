#!/usr/bin/env python3
"""What a world sheet is drawn from, and whether a sheet on disk still matches the film it is checked for.

Standard library only: look.py draws a sheet from these values and film_check.py checks a sheet's record with them, so
the preflight check never needs numpy or Pillow (look.py exits 2 without them). This module has no standalone
operation. --help documents it; exit 0.

What the check does and does not catch:
- Where a sheet is looked for: only the film's own qa/ and the refs/ of the project holding the film, at any depth
  (find_project). A sheet in a non-project folder above the film is ignored.
- Whose it is: the record's target_rel (resolved from the sheet's folder) must name this film or the project holding
  it, and a project's sheet counts only inside a project. A 2.3.0 record (neither target_rel nor drawn) keeps its
  absolute-path rule and nothing more.
- Whether it still matches: the record keeps the title and world line the sheet drew and where each came from. Each
  is compared with what the film is now, from sources that do not guess:
  - a kit film's title: the title the running page reports (film_check.py passes it in);
  - a project's title: its status.json title, which must still be the one recorded when the sheet was drawn;
  - the world line: the World line stated now in treatment.md, look.md or BOARD.md.
  A value given on the command line (--title, --world-line) is not compared, and the brand is never compared: the
  running page does not report it, and reading it from film.js is a guess. So the check tells you that a sheet sits
  in this film's or its project's place and names it, and that the title and world line it shows are the ones the
  film has now: a guard against the usual accident (a film folder copied or retitled), not a proof of which film a
  sheet was drawn for. It does not notice a changed brand, a value you gave on the command line, or a copy whose
  title and world line are unchanged.

The film.js reader below only chooses what to draw when --title or --brand is not given. It is small and can misread
a spec; a misread is caught by the title check, and the refusal says to draw again with --title.
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

# Output is set up before anything can print, a failed import's message included: UTF-8 to a pipe or a file, a
# stand-in character on a console that cannot show one (as project.safe_output does).
if __name__ == '__main__':
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, 'reconfigure'):
            _piped = not _stream.isatty()
            _stream.reconfigure(**({'encoding': 'utf-8'} if _piped else {}), errors='replace')


HERE = Path(__file__).resolve().parent
DEFAULT_BRAND = '#2F9E6B'
# Every option a sheet is drawn with, and its value when it is not given. title, world_line and brand come from the
# film when they are not given.
OPTION_DEFAULTS = {
    'title': None, 'world_line': None, 'brand': None,
    'bg': '#0D1016', 'fg': '#F4F1EA', 'muted': '#9BA3B0',
    'serif_words': 'Let it stand.', 'display_text': 'SHIP CLEAN.', 'display_px': 132,
    'secondary_text': 'Every cue lands on one clock.', 'secondary_px': 48,
    'mono_label': 'SECTION 01 · WORLD SHEET', 'display_tracking': -0.035, 'mono_tracking': 0.12,
    'distinct_secondary': False,
}
WORLD_FILES = ('treatment.md', 'look.md', 'BOARD.md')
# the title the kit's info() reports for a spec with none
KIT_PLACEHOLDER_TITLE = 'untitled'


def _project():
    spec = importlib.util.spec_from_file_location('lf_world_spec_project', HERE / 'project.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PROJECT = None


def find_project(path):
    global _PROJECT
    if _PROJECT is None:
        _PROJECT = _project()
    return _PROJECT.find_project(path)


def _read_text(path):
    """Read UTF-8 (with or without BOM) or UTF-16 (with BOM) safely; None when missing or unreadable."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return None
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16', errors='replace')
    return raw.decode('utf-8-sig', errors='replace')


def _read_json(path):
    """Parse JSON from UTF-8 (with or without BOM) or UTF-16 (with BOM); None when missing or invalid."""
    try:
        raw = Path(path).read_bytes()
        text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
        return json.loads(text)
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def world_target(target):
    """(root, kind) for a project folder ('project') or a standalone kit film folder ('kit')."""
    p = Path(target)
    proj = find_project(target)
    if proj is not None:
        return proj.resolve(), 'project'
    if p.is_dir() and ((p / 'film.js').is_file() or (p / 'index.html').is_file()):
        return p.resolve(), 'kit'
    raise ValueError(f'{target} is neither a project folder nor a kit film folder')


# ------------------------------------------------------------------------------------------------ reading film.js

def _mask_js(text):
    """TEXT with comments blanked and the contents of string literals replaced by spaces, same length, so keys and
    braces can be found without a `title:` in a comment or a string counting."""
    out, i, n = list(text), 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '/' and i + 1 < n and text[i + 1] in '/*':
            end = text.find('\n', i) if text[i + 1] == '/' else text.find('*/', i + 2)
            end = n if end < 0 else (end if text[i + 1] == '/' else end + 2)
            for k in range(i, end):
                if out[k] != '\n':
                    out[k] = ' '
            i = end
        elif ch in '\'"`':
            k = i + 1
            while k < n and text[k] != ch and not (ch != '`' and text[k] == '\n'):
                k += 2 if text[k] == '\\' else 1
            for m in range(i + 1, min(k, n)):
                if out[m] != '\n':
                    out[m] = ' '
            i = k + 1
        else:
            i += 1
    return ''.join(out)


def _openers(masked):
    """For each index, the index of the '{' whose object holds it (-1 at the top level)."""
    stack, where = [], [-1] * (len(masked) + 1)
    for i, ch in enumerate(masked):
        if ch == '}' and stack:
            stack.pop()
        where[i] = stack[-1] if stack else -1
        if ch == '{':
            stack.append(i)
    where[len(masked)] = stack[-1] if stack else -1
    return where


_STRING = re.compile(r"""\s*(?:'((?:[^'\\\n]|\\.)*)'|"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\$]|\\.|\$(?!\{))*)`)""")


def _string_at(text, pos):
    """The string literal starting at POS (after spaces), or None; a template literal with ${...} is not a value."""
    m = _STRING.match(text, pos)
    if not m:
        return None
    raw = next(g for g in m.groups() if g is not None)
    return re.sub(r'\\(.)', r'\1', raw)


def _value_at(text, masked, pos):
    """The string a spec key's value at POS holds: a literal, or a constant declared with one."""
    found = _string_at(text, pos)
    if found is not None:
        return found
    m = re.match(r'\s*([A-Za-z_$][\w$]*)\s*(?=[,}\n])', masked[pos:])
    return _constant(text, masked, m.group(1)) if m else None


def _constant(text, masked, name):
    m = re.search(r'\b(?:const|let|var)\s+' + re.escape(name) + r'\s*=', masked)
    return _string_at(text, m.end()) if m else None


def _depth(where, pos):
    depth, at = 0, where[pos]
    while at >= 0:
        depth, at = depth + 1, where[at]
    return depth


def film_spec_values(text):
    """{'title', 'brand'} as a quick reading of the spec film.js returns (the object with the scenes key), used only
    to choose what a sheet draws when --title or --brand is not given. None where it finds no literal. It can be
    wrong (a spread, Object.assign, a getter, a title set later); the sheet check compares the title with the one the
    running page reports, so a wrong reading is refused, not passed. It never raises."""
    values = {'title': None, 'brand': None}
    try:
        masked = _mask_js(text)
        where = _openers(masked)
        keys = [(m.group(1), m.start(1), m.end()) for m in
                re.finditer(r'(?<![\w$.])(title|brand|scenes)\s*(:|(?=[,}]))', masked)]
        spec = next((where[start] for key, start, _ in keys if key == 'scenes'), None)
        for name in values:
            own = [(start, end) for key, start, end in keys if key == name and (spec is None or where[start] == spec)]
            if spec is None and own:   # no scenes key to find the spec by: the outermost one
                depth = min(_depth(where, start) for start, _ in own)
                own = [(s, e) for s, e in own if _depth(where, s) == depth]
            for start, end in own:
                colon = masked[end - 1] == ':'
                value = _value_at(text, masked, end) if colon else _constant(text, masked, name)
                if value is not None:
                    values[name] = value
                    break
        values['brand'] = normal_hex(values['brand'])
    except Exception:   # noqa: BLE001 - any input: a reading the sheet does without
        return {'title': None, 'brand': None}
    return values


# ------------------------------------------------------------------------------------------------ what a sheet draws

_WORLD = re.compile(r'^-[ \t]*(?:World(?:[ \t]+line)?|Visual[ \t]+world)\b[^:\n]*:[ \t]*(\S.*)$',
                    re.MULTILINE | re.IGNORECASE)


def _text(value):
    """VALUE trimmed, or None when it is not text or is empty."""
    return value.strip() or None if isinstance(value, str) else None


def stated_world_line(root):
    """(world line, file) from the first World, World line or Visual world bullet in ROOT's treatment.md, look.md or
    BOARD.md; (None, None) when none states one. frame.what and a Tone line are not a world line."""
    for fname in WORLD_FILES:
        m = _WORLD.search(_read_text(Path(root) / fname) or '')
        if m and m.group(1).strip():
            return m.group(1).strip(), fname
    return None, None


def status_title(root):
    """A project's title as status.json states it now, or None."""
    status = _read_json(Path(root) / 'status.json')
    return _text(status.get('title')) if isinstance(status, dict) else None


def _page_reading(root):
    """(title, brand, file) read from ROOT's film.js, or the title of its index.html."""
    root = Path(root)
    if (root / 'film.js').is_file():
        spec = film_spec_values(_read_text(root / 'film.js') or '')
        title = _text(spec['title'])
        return (None if title == KIT_PLACEHOLDER_TITLE else title), spec['brand'], 'film.js'
    m = re.search(r'<title[^>]*>(.*?)</title>', _read_text(root / 'index.html') or '', re.IGNORECASE | re.DOTALL)
    return (_text(re.sub(r'\s+', ' ', m.group(1))) if m else None), None, 'index.html'


def given_options(**options):
    """The options given (not None), as a sheet's record keeps them."""
    return {k: v for k, v in options.items() if k in OPTION_DEFAULTS and v is not None}


def sheet_values(root, kind, options=None):
    """(values, sources): the values a world sheet for ROOT draws with OPTIONS (those given; the rest default), and
    where its title and world line came from: 'option'; 'status.json' (a project's title); the file a World line is
    stated in; 'film.js' or 'index.html' (read from a kit film's page); or 'default' (the folder's name, the default
    world line)."""
    root = Path(root)
    opts = dict(OPTION_DEFAULTS)
    opts.update(given_options(**(options or {})))
    read_title, read_brand, page_file = None, None, None
    if kind == 'kit' or (root / 'film.js').is_file():
        read_title, read_brand, page_file = _page_reading(root)
    if kind == 'project':   # a project's title is the one project.py init keeps
        read_title, page_file = status_title(root), 'status.json'
    if opts['title']:
        title, title_from = opts['title'], 'option'
    elif read_title:
        title, title_from = read_title, page_file
    else:
        title, title_from = root.name, 'default'
    stated_line, line_file = stated_world_line(root)
    if opts['world_line'] is not None:
        world_line, line_from = opts['world_line'], 'option'
    elif stated_line:
        world_line, line_from = stated_line, line_file
    else:
        world_line, line_from = f'{title} x brass proofreader table', 'default'
    values = {**opts, 'kind': kind, 'title': title, 'brand': opts['brand'] or read_brand or DEFAULT_BRAND,
              'world_line': world_line}
    return values, {'title': title_from, 'world_line': line_from}


def normal_hex(value):
    """'#RRGGBB' in capitals for a 3- or 6-digit hex colour, else None."""
    s = str(value or '').strip().lstrip('#')
    if len(s) == 3:
        s = ''.join(ch * 2 for ch in s)
    return '#' + s.upper() if re.fullmatch(r'[0-9a-fA-F]{6}', s) else None


# ------------------------------------------------------------------------------------------------ the check

def running_title(info_title):
    """The title a running page reports, or None when it states none (missing, empty, or the kit's 'untitled')."""
    if info_title is None or isinstance(info_title, bool):
        return None
    title = str(info_title).strip()
    return None if title in ('', KIT_PLACEHOLDER_TITLE) else title


def _matches(shown, source, now):
    """A value the sheet drew from SOURCE still matches NOW: a value given as an option is not compared; a default
    passes only while nothing is stated; anything else must equal what is stated now."""
    if source == 'option':
        return True
    if source == 'default':
        return now is None
    return _text(shown) is not None and _text(shown) == now


def sheet_owner(png, meta, folder, info_title=None):
    """('own', None) when the world sheet PNG, with its record META, still matches the film in FOLDER, whose running
    page reports INFO_TITLE; ('other', None) when its record names another film or a non-project folder; ('values',
    diffs) when it names this film or its project but its title or world line no longer match (or its record is
    incomplete). DIFFS is [(what, the sheet's value, the value now)]."""
    if not isinstance(meta, dict) or not (meta.get('target_rel') or meta.get('target')):
        return 'other', None
    here = Path(folder).resolve()
    png = Path(png)
    target = ((png.parent / str(meta['target_rel'])).resolve() if meta.get('target_rel')
              else Path(str(meta['target'])).resolve())
    kind = meta.get('kind')
    if not (here == target or (kind == 'project' and target in here.parents)):
        return 'other', None
    if kind == 'project' and find_project(target) != target:
        return 'other', None   # a project's sheet copied into a folder that is not a project
    if 'target_rel' not in meta and 'drawn' not in meta:
        return 'own', None   # a 2.3.0 record: its absolute path, and nothing more
    drawn, sources = meta.get('drawn'), meta.get('sources')
    if not isinstance(drawn, dict) or not isinstance(sources, dict) or (
            kind == 'project' and 'project_title' not in meta):
        return 'values', [('record', 'its record does not say where its title and world line came from (an earlier '
                                     'build drew it)', None)]
    diffs = []
    if kind == 'project':
        now = status_title(target)
        if _text(meta.get('project_title')) != now:
            diffs.append(('project_title', _text(meta.get('project_title')), now))
        elif not _matches(drawn.get('title'), sources.get('title'), now):
            diffs.append(('title', drawn.get('title'), now))
    elif not _matches(drawn.get('title'), sources.get('title'), running_title(info_title)):
        diffs.append(('title', drawn.get('title'), running_title(info_title)))
    line_now, _ = stated_world_line(target)
    if not _matches(drawn.get('world_line'), sources.get('world_line'), line_now):
        diffs.append(('world_line', drawn.get('world_line'), line_now))
    return ('values', diffs) if diffs else ('own', None)


def _q(value):
    return 'none' if value is None else repr(value)


def describe(diffs):
    """The differences, in words: what the sheet shows and what the film states now."""
    words = {
        'title': lambda a, b: f'it shows the title {_q(a)} where this film ' + (
            f'states {b!r}' if b is not None else 'states no title'),
        'project_title': lambda a, b: f'it was drawn for the project titled {_q(a)} where this project\'s status.json '
                                      f'title is {_q(b)}',
        'world_line': lambda a, b: f'it shows the world line {_q(a)} where this film ' + (
            f'states {b!r}' if b is not None else 'states none'),
    }
    return '; '.join(str(a) if k == 'record' else words[k](a, b) for k, a, b in diffs)


def redraw_advice(png, meta, diffs, info_title=None):
    """What to do about a refused sheet: draw it again with look.py world-sheet, for the folder named on a line of its
    own, exactly, and (when the title it showed was read from the film's source or fell back to the folder's name) with
    the running title, also on a line of its own, passed with --title. It is not a command line: none is right in sh,
    cmd.exe and PowerShell at once, and the skill's other messages name the script and what to give it too."""
    meta = meta if isinstance(meta, dict) else {}
    target = str((Path(png).parent / str(meta['target_rel'])).resolve() if meta.get('target_rel')
                 else Path(str(meta.get('target') or Path(png).parent.parent)))
    source = (meta.get('sources') or {}).get('title') if isinstance(meta.get('sources'), dict) else None
    title_differs = any(k == 'title' for k, _, _ in diffs or [])
    lines = [f'    folder: {target}']
    if meta.get('kind') != 'project' and title_differs and source in ('film.js', 'index.html', 'default'):
        title = running_title(info_title)
        if title is None:
            head = ('Draw it again with look.py world-sheet for this folder, passing the title it should show '
                    'with --title:')
        else:
            head = 'Draw it again with look.py world-sheet for this folder, passing this title with --title:'
            lines.append(f'    title: {title}')
    else:
        head = 'Draw it again with look.py world-sheet for this folder:'
    return chr(10).join([head, *lines])


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
