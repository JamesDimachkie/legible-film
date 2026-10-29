#!/usr/bin/env python3
"""Check the repository's Markdown: inline relative links, images (Markdown or HTML <img>) and heading
anchors resolve, SKILL.md stays under 500 lines, and every script SKILL.md names exists and answers --help
(Node scripts too, when node is on PATH).

Reference-style links, external URLs and links inside fenced code are not checked, nor are the agent
outputs under evals/results/*/runs, which are published verbatim.

  python .github/scripts/check_docs.py
"""

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
                dest = os.path.normpath(os.path.join(folder, file_part)) if file_part else path
                rel = os.path.relpath(path, ROOT)
                if not os.path.exists(dest):
                    problems.append(f'{rel}: missing target {target}')
                elif anchor and dest.endswith('.md') and anchor not in anchors(dest):
                    problems.append(f'{rel}: missing anchor {target}')
    with open(os.path.join(SKILL, 'SKILL.md'), encoding='utf-8') as fh:
        skill = fh.read()
    for script in sorted(set(re.findall(r'`([a-z_]+\.py)', skill))):
        path = os.path.join(SKILL, 'scripts', script)
        if not os.path.exists(path):
            problems.append(f'SKILL.md names a missing script: {script}')
            continue
        r = subprocess.run([sys.executable, path, '--help'], capture_output=True, text=True)
        if r.returncode:
            problems.append(f'{script} --help failed')
    node = shutil.which('node')
    for script in sorted(set(re.findall(r'`([a-z_]+\.mjs)', skill))):
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
    for p in problems:
        print(p)
    print(f'{len(problems)} problem(s)')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
