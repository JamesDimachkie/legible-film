#!/usr/bin/env python3
"""Check the repository's Markdown: inline relative links, images (Markdown or HTML <img>) and heading
anchors resolve, SKILL.md stays within its size budget (under 16,000 bytes, a description under 400 characters),
every script SKILL.md, references/loop.md and references/scripts.md name exists and answers --help (Node
scripts too, when node is on PATH), the README's command table names the same commands as SKILL.md's, every script
has a row in references/scripts.md, the README's image tags parse to known attributes, SKILL.md, the plugin
manifests and the newest CHANGELOG entry give one version, and text files use LF line endings (published run outputs
are left verbatim).

Reference-style links, external URLs and links inside fenced code are not checked, nor are the agent
outputs under evals/results/*/runs, which are published verbatim.

  python .github/scripts/check_docs.py
"""

import html.parser
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SKILL = os.path.join(ROOT, 'skills', 'legible-film')
LINK = re.compile(r'\[[^\]]*\]\(([^)\s]+)\)|<img\s[^>]*?src="([^"]+)"')


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


def main():
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
    # The router names some scripts; the loop and the scripts table name the rest an agent is sent to.
    named = skill
    for extra in ('loop.md', 'scripts.md'):
        path = os.path.join(SKILL, 'references', extra)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as fh:
                named += fh.read()
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
            problems.append(f'references/scripts.md has no row for scripts/{name}')
    # One version wherever a person or an installer reads it: SKILL.md, both plugin manifests, the newest CHANGELOG entry.
    versions = {}
    found = re.search(r'^\s*version:\s*"?([^"\n]+?)"?\s*$', skill, re.MULTILINE)
    versions['SKILL.md'] = found.group(1) if found else 'none'
    for name in ('plugin.json', 'marketplace.json'):
        with open(os.path.join(ROOT, '.claude-plugin', name), encoding='utf-8') as fh:
            versions[name] = ', '.join(sorted(set(re.findall(r'"version":\s*"([^"]+)"', fh.read())))) or 'none'
    with open(os.path.join(ROOT, 'CHANGELOG.md'), encoding='utf-8') as fh:
        found = re.search(r'^## (\S+)', fh.read(), re.MULTILINE)
    versions['CHANGELOG.md'] = found.group(1) if found else 'none'
    if len(set(versions.values())) != 1:
        problems.append('versions disagree: ' + ', '.join(f'{name} {value}' for name, value in versions.items()))
    # The README's command table is what people read; SKILL.md's is what agents route by. They name the same commands.
    with open(os.path.join(ROOT, 'README.md'), encoding='utf-8') as fh:
        readme = fh.read()
    commands = [{name for row in re.findall(r'^\| (`[^|]*)\|', text, re.MULTILINE)
                 for name in re.findall(r'`([a-z]+)`', row)} for text in (skill, readme)]
    for name in sorted(commands[0] - commands[1]):
        problems.append(f'SKILL.md has the command {name}; the README command table does not')
    for name in sorted(commands[1] - commands[0]):
        problems.append(f'the README command table has the command {name}; SKILL.md does not')
    for p in problems:
        print(p)
    print(f'{len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
