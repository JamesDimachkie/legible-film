#!/usr/bin/env python3
"""Check the repository's Markdown: inline relative links, images (Markdown or HTML <img>) and heading
anchors resolve, SKILL.md stays within its size budget (under 16,000 bytes, a description under 400 characters),
every script SKILL.md, paths/*.md and references/*.md name exists and answers --help (Node scripts
too, when node is on PATH), the README's command table names the same commands as
references/commands.md (SKILL.md's table until the command map exists), every script
has a row in references/scripts.md, the README's image tags parse to known attributes, SKILL.md, the plugin
manifests and the newest CHANGELOG entry give one version, and text files use LF line endings (published run outputs
are left verbatim).

Reference-style links, external URLs and links inside fenced code are not checked, nor are the agent
outputs under evals/results/*/runs, which are published verbatim.

The 2.1 reshape adds:
- Draft tool lines. A line in SKILL.md, paths/*.md or references/*.md that ends with the HTML comment
  `<!-- draft-tool -->` may name a script that is not built yet; it is accepted and counted by default, and every
  one is a problem under --final (the mode the integrated candidate runs). A tool line without the marker must name a
  script that exists and answers --help.
- The personal-path gate. No text file in the repository may hold a personal path: a drive-letter Users folder,
  /Users/, /home/, AppData, _npx or .t3/, nor any term in LF_PRIVATE_TERMS (comma or newline separated, set from
  private CI; a hit prints the file and line, never the term). .github/scripts/private-paths.txt allows the
  legitimate hits, one per line: `path | text the allowed line contains | reason`. Every run first plants a personal
  path in a scratch folder and fails unless the gate catches it.
- The command map. When references/commands.md exists, every name in evals/command-names.json appears there exactly
  once, in a table row whose first cell is the backticked name, whose second cell names one of the six paths
  (create, cut, insert, sound, editor, quick) and whose third cell is `fixed` or `by timeline`; once paths/ exists,
  each path file exists. Every Markdown file under paths/ and references/ is reachable from SKILL.md within two links.
- SKILL.md holds at most 900 words once paths/ exists, and always under --final. Scripts awaiting their row in
  references/scripts.md (PENDING_ROWS) are accepted until --final.

  python .github/scripts/check_docs.py [--final]
"""

import argparse
import html.parser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SKILL = os.path.join(ROOT, 'skills', 'legible-film')
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)|<img\s[^>]*?src="([^"]+)"')
DRAFT = '<!-- draft-tool -->'
PATHS = ('create', 'cut', 'insert', 'sound', 'editor', 'quick')
WORD_CAP = 900
# Scripts built in U1 whose rows in references/scripts.md the docs lane (U2) writes; accepted until --final.
PENDING_ROWS = {'cue_list.py', 'with_lock.py'}
PERSONAL = re.compile(r'[A-Z]:[\\/]Users|/Users/|/home/|AppData|_npx|\.t3/')
ALLOWLIST = os.path.join(ROOT, '.github', 'scripts', 'private-paths.txt')
# The gate's own files hold its patterns; they are not scanned.
GATE_FILES = {os.path.join('.github', 'scripts', 'check_docs.py'), os.path.join('.github', 'scripts', 'private-paths.txt')}
SCANNED = ('.py', '.mjs', '.cjs', '.js', '.md', '.json', '.yml', '.yaml', '.txt', '.html', '.css', '.csv', '.toml',
           '.ps1', '.sh')


def read_allowlist(path=ALLOWLIST):
    """[(relative path, literal, reason)] from private-paths.txt."""
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = [part.strip() for part in line.split(' | ')]
            if len(parts) == 3 and all(parts):
                entries.append((parts[0].replace('\\', '/'), parts[1], parts[2]))
    return entries


def private_terms():
    raw = os.environ.get('LF_PRIVATE_TERMS', '')
    return [term.strip() for term in re.split(r'[,\n]', raw) if term.strip()]


def personal_path_hits(root, allow, terms=(), skip=GATE_FILES):
    """Every line under root holding a personal path or a private term that no allowlist entry covers:
    [(relative path, line number, what matched)]. A private term is never allowlisted."""
    hits = []
    lowered = [term.lower() for term in terms]
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ('.git', 'node_modules', '__pycache__', '.lf-frozen'))
        for name in sorted(files):
            path = os.path.join(folder, name)
            rel = os.path.relpath(path, root)
            if rel in skip or not name.endswith(SCANNED):
                continue
            try:
                with open(path, encoding='utf-8', errors='replace') as fh:
                    lines = fh.read().splitlines()
            except OSError:
                continue
            posix = rel.replace(os.sep, '/')
            for number, line in enumerate(lines, 1):
                found = PERSONAL.search(line)
                term = next((i for i, t in enumerate(lowered) if t in line.lower()), None)
                if not found and term is None:
                    continue
                if term is None and any(posix == entry and literal in line for entry, literal, _ in allow):
                    continue
                hits.append((posix, number, f'private term #{term + 1}' if term is not None else found.group(0)))
    return hits


def gate_catches_planted_path():
    """The gate's own test: a personal path planted in a scratch folder is caught, an allowlisted line is not, and a
    private term is caught without being printed."""
    planted = 'C:' + chr(92) + 'Users' + chr(92) + 'someone' + chr(92) + 'film.mp4'
    with tempfile.TemporaryDirectory() as scratch:
        with open(os.path.join(scratch, 'notes.md'), 'w', encoding='utf-8') as fh:
            fh.write('ok line\nsource: ' + planted + '\nthe codename is Bluebird\n')
        with open(os.path.join(scratch, 'allowed.py'), 'w', encoding='utf-8') as fh:
            fh.write("home = 'App' + 'Data'\nhome = 'AppData'  # per-user data\n")
        hits = personal_path_hits(scratch, [('allowed.py', "'AppData'  # per-user data", 'test')], ['bluebird'])
    return [(p, n) for p, n, _ in hits] == [('notes.md', 2), ('notes.md', 3)] and hits[1][2] == 'private term #1'


def anchors(path):
    """GitHub-style heading anchors of a Markdown file."""
    out = set()
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            m = re.match(r'#{1,6}\s+(.*)', line)
            if m:
                text = re.sub(r'[`*_]', '', m.group(1)).strip().lower()
                slug = re.sub(r'[^\w\- ]', '', text).replace(' ', '-')
                out.add(slug)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--final', action='store_true',
                        help='the integrated candidate: no draft tool lines, every reshape check enforced')
    final = parser.parse_args(argv).final
    problems = []
    results = os.path.join(ROOT, 'evals', 'results')
    for folder, _, files in os.walk(ROOT):
        if '.git' in folder.split(os.sep) or 'node_modules' in folder:
            continue
        # Published run outputs are kept verbatim; their links point into the folders they were written in.
        if folder.startswith(os.path.join(results, '')) and os.sep + 'runs' in folder[len(results):]:
            continue
        for name in files:
            if not name.endswith('.md'):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            text = re.sub(r'```.*?```', '', text, flags=re.S)
            for match in LINK.findall(text):
                target = match[0] or match[1]
                if re.match(r'^[a-z]+:', target):
                    continue
                file_part, _, anchor = target.partition('#')
                file_part = file_part.split('?', 1)[0]
                dest = os.path.normpath(os.path.join(folder, file_part)) if file_part else path
                rel = os.path.relpath(path, ROOT)
                if not os.path.exists(dest):
                    problems.append(f'{rel}: missing target {target}')
                elif anchor and dest.endswith('.md') and anchor not in anchors(dest):
                    problems.append(f'{rel}: missing anchor {target}')
    with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as fh:
        skill = fh.read()
    # Every script a document an agent reads names must exist and answer --help, unless its line is a draft tool line.
    docs = [os.path.join(SKILL, 'SKILL.md')]
    for sub in ('paths', 'references'):
        folder = os.path.join(SKILL, sub)
        if os.path.isdir(folder):
            docs += [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.endswith('.md')]
    named, drafts = '', []
    for doc in docs:
        with open(doc, encoding='utf-8') as fh:
            for number, line in enumerate(fh, 1):
                if line.rstrip().endswith(DRAFT):
                    drafts.append(f'{os.path.relpath(doc, ROOT)}:{number}')
                else:
                    named += line
    if drafts and final:
        problems.extend(f'{place}: a draft tool line (marked {DRAFT}) remains under --final' for place in drafts)
    elif drafts:
        print(f'note: {len(drafts)} draft tool line(s) accepted until --final: ' + ', '.join(drafts[:8])
              + (' ...' if len(drafts) > 8 else ''))
    for script in sorted(set(re.findall(r'`([a-z_]+\.py)', named))):
        path = os.path.join(SKILL, 'scripts', script)
        if not os.path.exists(path):
            problems.append(f'SKILL.md names a missing script: {script}')
            continue
        r = subprocess.run([sys.executable, path, '--help'], capture_output=True, text=True)
        if r.returncode:
            problems.append(f'{script} --help failed')
    node = shutil.which('node')
    for script in sorted(set(re.findall(r'`([a-z_]+\.mjs)', named))):
        path = os.path.join(SKILL, 'scripts', script)
        if not os.path.exists(path):
            problems.append(f'SKILL.md names a missing script: {script}')
        elif not node:
            print(f'note: node is not on PATH, so {script} --help was not run')
        elif subprocess.run([node, path, '--help'], capture_output=True, text=True).returncode:
            problems.append(f'{script} --help failed')
    lines = skill.count('\n')
    if lines > 500:
        problems.append(f'SKILL.md has {lines} lines; keep it under 500')
    # Every agent reads SKILL.md whole, and every agent with it installed reads the description on each turn.
    size = len(skill.encode('utf-8'))
    if size > 16000:
        problems.append(f'SKILL.md is {size} bytes; keep it under 16,000 and move detail into references')
    found = re.search(r'^description:\s*"(.*)"\s*$', skill, re.MULTILINE)
    if found and len(found.group(1)) > 400:
        problems.append(f'the SKILL.md description is {len(found.group(1))} characters; keep it under 400')
    # An HTML image whose attributes parse oddly (a lost `width=` leaves an attribute named `100%"`) renders wrong.
    class Images(html.parser.HTMLParser):
        def handle_starttag(self, tag, attrs):
            odd = [name for name, _ in attrs if name not in ('src', 'alt', 'width', 'height', 'media', 'srcset')]
            if tag in ('img', 'source') and odd:
                problems.append(f'README.md: an <{tag}> tag has unexpected attributes {odd}')
    with open(os.path.join(ROOT, 'README.md'), encoding='utf-8') as fh:
        Images().feed(fh.read())
    # LF everywhere, so a Windows edit cannot turn a file into a whole-file diff; published run outputs stay verbatim.
    text_types = ('.py', '.mjs', '.js', '.md', '.json', '.yml', '.yaml', '.txt', '.html', '.css', '.csv')
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in ('.git', 'node_modules', '__pycache__')]
        if folder.startswith(os.path.join(results, '')) or folder == results:
            continue
        for name in files:
            path = os.path.join(folder, name)
            if name.endswith(text_types):
                with open(path, 'rb') as fh:
                    if b'\r\n' in fh.read():
                        problems.append(f'{os.path.relpath(path, ROOT)} has CRLF line endings; save it with LF')
    # Every script an agent might run is in the scripts index SKILL.md routes to; modules other scripts import are not.
    helpers = {'dialogue_io.py', 'render_common.py', 'sound_io.py', 'film_capture.mjs'}
    with open(os.path.join(SKILL, 'references', 'scripts.md'), encoding='utf-8') as fh:
        indexed = set(re.findall(r'^\| `([a-z_]+\.(?:py|mjs))`', fh.read(), re.MULTILINE))
    for name in sorted(os.listdir(os.path.join(SKILL, 'scripts'))):
        if name.endswith(('.py', '.mjs')) and name not in helpers and name not in indexed:
            if name in PENDING_ROWS and not final:
                print(f'note: references/scripts.md has no row for scripts/{name} yet (accepted until --final)')
            else:
                problems.append(f'references/scripts.md has no row for scripts/{name}')
    # One version wherever a person or an installer reads it: SKILL.md, both plugin manifests, the newest released
    # CHANGELOG entry (an Unreleased section above it is not a version).
    versions = {}
    found = re.search(r'^\s*version:\s*"?([^"\n]+?)"?\s*$', skill, re.MULTILINE)
    versions['SKILL.md'] = found.group(1) if found else 'none'
    for name in ('plugin.json', 'marketplace.json'):
        with open(os.path.join(ROOT, '.claude-plugin', name), encoding='utf-8') as fh:
            versions[name] = ', '.join(sorted(set(re.findall(r'"version":\s*"([^"]+)"', fh.read())))) or 'none'
    with open(os.path.join(ROOT, 'CHANGELOG.md'), encoding='utf-8') as fh:
        found = re.search(r'^## (?!Unreleased\b)(\S+)', fh.read(), re.MULTILINE)
    versions['CHANGELOG.md'] = found.group(1) if found else 'none'
    if len(set(versions.values())) != 1:
        problems.append('versions disagree: ' + ', '.join(f'{name} {value}' for name, value in versions.items()))
    # The README's command table is what people read; the command map (references/commands.md) is what agents route
    # by. They name the same commands. Before the command map exists, SKILL.md's 2.0 command table stands in for it.
    with open(os.path.join(ROOT, 'README.md'), encoding='utf-8') as fh:
        readme = fh.read()
    command_map = os.path.join(SKILL, 'references', 'commands.md')
    if os.path.exists(command_map):
        with open(command_map, encoding='utf-8') as fh:
            routed, routed_name = fh.read(), 'references/commands.md'
    else:
        routed, routed_name = skill, 'SKILL.md'
    commands = [{name for row in re.findall(r'^\| (`[^|]*)\|', text, re.MULTILINE)
                 for name in re.findall(r'`([a-z]+)`', row)} for text in (routed, readme)]
    for name in sorted(commands[0] - commands[1]):
        problems.append(f'{routed_name} has the command {name}; the README command table does not')
    for name in sorted(commands[1] - commands[0]):
        problems.append(f'the README command table has the command {name}; {routed_name} does not')
    problems.extend(reshape_checks(skill, final))
    if not gate_catches_planted_path():
        problems.append('the personal-path gate missed a planted path; the gate itself is broken')
    for path, number, what in personal_path_hits(ROOT, read_allowlist(), private_terms()):
        problems.append(f'{path}:{number}: a personal path ({what}); remove it, or allow it in '
                        f'.github/scripts/private-paths.txt with a reason')
    for p in problems:
        print(p)
    print(f'{len(problems)} problem(s)')
    return 1 if problems else 0


def skill_links(path):
    """The Markdown files a skill document links to, resolved."""
    with open(path, encoding='utf-8') as fh:
        text = re.sub(r'```.*?```', '', fh.read(), flags=re.S)
    found = set()
    for target in re.findall(r'\[[^\]]*\]\(([^)\s#]+\.md)(?:#[^)]*)?\)', text):
        if not re.match(r'^[a-z]+:', target):
            found.add(os.path.normpath(os.path.join(os.path.dirname(path), target)))
    return found


def reshape_checks(skill, final):
    """The 2.1 checks: the SKILL.md word cap, the command map and the link depth from SKILL.md."""
    problems = []
    paths_dir = os.path.join(SKILL, 'paths')
    body = skill.split('---', 2)[2] if skill.startswith('---') else skill
    words = len(re.findall(r'\S+', body))
    if words > WORD_CAP and (final or os.path.isdir(paths_dir)):
        problems.append(f'SKILL.md has {words} words; the cap is {WORD_CAP}')
    elif words > WORD_CAP:
        print(f'note: SKILL.md has {words} words; the {WORD_CAP}-word cap applies once paths/ exists and under --final')
    commands = os.path.join(SKILL, 'references', 'commands.md')
    names_file = os.path.join(ROOT, 'evals', 'command-names.json')
    if os.path.exists(commands) and os.path.exists(names_file):
        with open(names_file, encoding='utf-8') as fh:
            names = json.load(fh)['names']
        rows = {}
        with open(commands, encoding='utf-8') as fh:
            for line in fh:
                if not line.startswith('|'):
                    continue
                cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
                found = re.fullmatch(r'`([a-z]+)`', cells[0])
                if not found:
                    continue
                second = cells[1] if len(cells) > 1 else ''
                path = next((p for p in PATHS if re.search(r'\b' + p + r'\b', second)), None)
                rows.setdefault(found.group(1), []).append((path, cells[2] if len(cells) > 2 else ''))
        for name in names:
            entries = rows.get(name, [])
            if len(entries) != 1:
                problems.append(f'references/commands.md: {name} appears {len(entries)} times; it must appear once')
            elif entries[0][0] is None:
                problems.append(f'references/commands.md: {name} names none of the six paths')
            elif entries[0][1] not in ('fixed', 'by timeline'):
                problems.append(f'references/commands.md: {name} has dispatch {entries[0][1]!r}; fixed or by timeline')
        if os.path.isdir(paths_dir) or final:
            for path in PATHS:
                if not os.path.exists(os.path.join(paths_dir, path + '.md')):
                    problems.append(f'paths/{path}.md is missing')
    elif final:
        problems.append('references/commands.md is missing (the command map)')
    start = os.path.normpath(os.path.join(SKILL, 'SKILL.md'))
    depth, frontier = {start: 0}, [start]
    while frontier:
        following = []
        for doc in frontier:
            for target in skill_links(doc):
                if target not in depth and os.path.exists(target) and target.startswith(os.path.normpath(SKILL)):
                    depth[target] = depth[doc] + 1
                    following.append(target)
        frontier = following
    for sub in ('paths', 'references'):
        folder = os.path.join(SKILL, sub)
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            doc = os.path.normpath(os.path.join(folder, name))
            if name.endswith('.md') and depth.get(doc, 99) > 2:
                problems.append(f'{sub}/{name} is not reachable from SKILL.md within two links')
    return problems


if __name__ == '__main__':
    sys.exit(main())
