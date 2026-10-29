#!/usr/bin/env python3
"""Start a film project from the Legible Film kit (a small browser engine for type-led motion films).

Copies the kit (index.html, lf/, blocks/, fonts/ with their licences) into FOLDER, then writes a
film.js and facts.json from a template film: the commented starter (about 12 s) or the Atlasfold
showcase. It never overwrites an existing file: anything already there is kept and listed. With
--brand, the template's brand colour is replaced; the kit builds the whole palette from it.

  python new_film.py films/launch
  python new_film.py films/launch --from atlasfold --brand '#3D7BFF'
  python new_film.py films/launch --json qa/new_film.json

What it does not do: it does not write your story, check your facts or render anything. Replace the
template's facts with the product's real ones (with sources and dates) before any claim ships, then
run film_check.py on the folder.

Needs Python 3.9+ only. Exit codes: 0 the project was written (or was already complete), 1 some
files already existed and were kept (listed), 2 the kit or template could not be found or written.
"""

import argparse
import json
import os
import re
import shutil
import sys

KIT_PARTS = ['index.html', 'lf', 'blocks', 'fonts']
TEMPLATES = ('starter', 'atlasfold')


def find_kit(explicit=None):
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in ([explicit] if explicit else []) + [os.path.join(here, '..', 'assets', 'kit'), os.path.join(here, '..', 'kit')]:
        if cand and os.path.isfile(os.path.join(cand, 'index.html')) and os.path.isdir(os.path.join(cand, 'lf')):
            return os.path.abspath(cand)
    return None


def copy_tree(src, dst, written, kept):
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for name in sorted(os.listdir(src)):
            if name.startswith('.') or name == '__pycache__':
                continue
            copy_tree(os.path.join(src, name), os.path.join(dst, name), written, kept)
    else:
        if os.path.exists(dst):
            kept.append(dst)
        else:
            shutil.copy2(src, dst)
            written.append(dst)


def write_new(path, text, written, kept):
    if os.path.exists(path):
        kept.append(path)
        return
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    written.append(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('folder', help='the new project folder (created if missing)')
    ap.add_argument('--from', dest='template', choices=TEMPLATES, default='starter', help='template film (default starter)')
    ap.add_argument('--brand', help="brand colour as #RRGGBB, for example '#3D7BFF'")
    ap.add_argument('--kit', help='path to assets/kit (found next to this script by default)')
    ap.add_argument('--json', help='write what was written and kept as JSON')
    a = ap.parse_args()

    kit = find_kit(a.kit)
    if not kit:
        print('new_film.py: cannot find the kit (assets/kit with index.html and lf/); pass --kit', file=sys.stderr)
        return 2
    tdir = os.path.join(kit, 'films', a.template)
    tfilm = os.path.join(tdir, 'film.js')
    if not os.path.isfile(tfilm):
        print(f'new_film.py: template {a.template} not found at {tdir}', file=sys.stderr)
        return 2
    if a.brand and not re.fullmatch(r'#[0-9A-Fa-f]{6}', a.brand):
        print(f'new_film.py: --brand must look like #3D7BFF, not {a.brand!r}', file=sys.stderr)
        return 2

    out = os.path.abspath(a.folder)
    written, kept = [], []
    try:
        os.makedirs(out, exist_ok=True)
        for part in KIT_PARTS:
            copy_tree(os.path.join(kit, part), os.path.join(out, part), written, kept)
        with open(tfilm, encoding='utf-8') as f:
            film = f.read()
        if a.brand:
            film, n = re.subn(r"brand:\s*'#[0-9A-Fa-f]{6}'", f"brand: '{a.brand.upper()}'", film, count=1)
            if not n:
                film = film.replace('    fps: 60,', f"    fps: 60,\n    brand: '{a.brand.upper()}',", 1)
        write_new(os.path.join(out, 'film.js'), film, written, kept)
        tfacts = os.path.join(tdir, 'facts.json')
        if os.path.isfile(tfacts):
            with open(tfacts, encoding='utf-8') as f:
                write_new(os.path.join(out, 'facts.json'), f.read(), written, kept)
        for sub in ('qa', 'assets'):
            os.makedirs(os.path.join(out, sub), exist_ok=True)
    except OSError as e:
        print(f'new_film.py: could not write the project: {e}', file=sys.stderr)
        return 2

    rel = lambda p: os.path.relpath(p, out)
    print(f'Film project: {out}  (template {a.template}{", brand " + a.brand.upper() if a.brand else ""})')
    print(f'  wrote {len(written)} file(s)' + (f'; kept {len(kept)} existing file(s): ' + ', '.join(rel(p) for p in kept[:8]) + (' ...' if len(kept) > 8 else '') if kept else ''))
    print('Next steps:')
    print('  1. Replace facts.json with the product\'s real facts (source, date, conditions, on-screen display).')
    print('  2. Edit film.js: one block per scene; every claim carries role "claim" and its fact id.')
    print(f'  3. Preview: python -m http.server --directory "{out}" 8000, then open http://127.0.0.1:8000/')
    print('     (keys: space play, , . frame, arrows beat, 0-9 jump, S safe area, R reading states, L luminance).')
    print(f'  4. Preflight: python scripts/film_check.py "{out}" --size 1920x1080, and again with --size 1080x1920.')
    print('  5. Render with film_render.py, then run the QC battery on the delivered file.')
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'folder': out, 'template': a.template, 'brand': a.brand, 'written': [rel(p) for p in written], 'kept': [rel(p) for p in kept]}, f, indent=1)
    return 1 if kept else 0


if __name__ == '__main__':
    sys.exit(main())
