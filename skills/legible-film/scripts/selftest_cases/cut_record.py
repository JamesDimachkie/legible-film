"""Paper cut settings coexist with the full project-record front matter."""
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_cut_record_cases(tool, record, j, scripts_dir):
    scripts = Path(scripts_dir)
    example = load(scripts / 'selftest_cases' / 'record.py', 'cut_record_example').SPEC_FRAME
    cut = load(scripts / 'cut.py', 'cut_record_script')
    root = Path(j('cut-record'))
    code, output = tool('project.py', 'init', root, '--path', 'cut', '--timeline', 'paper', '--page', 'film')
    if code != 0:
        record('cut record: a paper project is initialized', False, output[-300:])
        return
    (root / 'map' / 'sources.json').write_text(json.dumps({'version': 1, 'sources': []}), encoding='utf-8')
    example = example.replace('path: create', 'path: cut', 1).replace('timeline: page', 'timeline: paper', 1)
    cut_settings = ('title: Cut title\nsize: 320x180\naudience: Cut audience\n'
                    'takeaway: Cut takeaway\ntarget: 1\ncaptions: none\n')
    nested = ('  title: Nested title\n  size: 12x12\n  target: 99\n  captions: burn\n'
              '  extra: |\n    ---\n    story: nested text\n')
    text = (example.replace('---\n', '---\n' + cut_settings, 1)
            .replace('\n---\n', '\n' + nested + 'fps: 25\nstory: Cut story\n---\n', 1)
            + '\n- title "Paper record" 1.0 center card\n')
    film = root / 'film.md'
    film.write_text(text, encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--json', '--no-audio')
    try:
        result = json.loads(output)
    except ValueError:
        result = {}
    record('cut record: the full section 6 record passes cut.py check on a paper project',
           code == 0 and result.get('ok') is True and result.get('errors') == 0
           and result.get('duration_s') == 1 and result.get('lines', [{}])[0].get('card') is True,
           output[-1200:])
    problems = cut.Problems()
    settings, entries = cut.parse_film(text, problems, root=root)
    record('cut record: top-level cut settings win over nested frame values on either side of the frame',
           problems.count('error') == 0 and len(entries) == 1 and settings.get('title') == 'Cut title'
           and settings.get('audience') == 'Cut audience' and settings.get('takeaway') == 'Cut takeaway'
           and settings.get('story') == 'Cut story' and settings.get('size') == (320, 180)
           and float(settings.get('fps') or 0) == 25 and settings.get('target') == 1
           and settings.get('captions') == set(), str((settings, problems.items))[:1200])
    film.write_text(text.replace('fps: 25\n', 'fps: 25\naudienc: typo\n', 1), encoding='utf-8')
    code, output = tool('cut.py', 'check', root, '--json', '--no-audio')
    record('cut record: an unknown top-level setting is still refused',
           code == 1 and "unknown setting 'audienc'" in output, output[-600:])


if __name__ == '__main__':
    with tempfile.TemporaryDirectory() as temp:
        results = []
        scripts = Path(__file__).parents[1]
        def tool(name, *args):
            process = subprocess.run([sys.executable, str(scripts / name), *map(str, args)],
                                     capture_output=True, text=True, encoding='utf-8', errors='replace')
            return process.returncode, process.stdout + process.stderr
        def record(name, ok, detail):
            results.append(ok)
            print(('PASS ' if ok else 'FAIL ') + name + ('' if ok else ': ' + detail))
        run_cut_record_cases(tool, record, lambda name: str(Path(temp) / name), scripts)
        sys.exit(0 if all(results) else 1)
