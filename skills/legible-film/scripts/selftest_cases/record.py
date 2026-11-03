"""The project record (SPEC §6): project.py init --path --timeline --page writes film.md's front matter with the frame
fields, reads it back, prints "timeline: page · context: 2 confirmed, 2 assumed" in status, and puts timeline, path
and context into status.json and status --json. A plain init writes no record, as before."""
import importlib.util
import json
from pathlib import Path

SPEC_FRAME = '''---
path: create                # create | cut | insert | sound | editor | quick
timeline: page              # page | paper | editor | picture | file | tesseract
page: film/                 # when the owner is a page or a Tesseract project
frame:
  what: "Legible Film: an open-source skill that lets a coding agent make video, picture and sound on one clock"
  audience: "developers who run coding agents, on X, often muted"
  why: "they want video without a studio"
  knows_by: [{s: 3, what: "what this is and who it is for", channel: "type"}]
  state: {what: confirmed, audience: assumed, why: confirmed, knows_by: assumed}
  waived: null              # or {reason: "...", by: "person"}
  cold_read: {state: not-run}   # matched | mismatched; by (model), method, file_sha256; never "confirmed"
---
'''


def run_record_cases(tool, record, j, scripts_dir, skip=None):
    spec = importlib.util.spec_from_file_location('selftest_record_project', Path(scripts_dir) / 'project.py')
    project = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(project)
    root = Path(j('record-cases'))
    root.mkdir(parents=True, exist_ok=True)

    plain = root / 'plain'
    code, out = tool('project.py', 'init', plain)
    record('record: a plain init writes no film.md and no record, as before',
           code == 0 and not (plain / 'film.md').exists() and 'timeline' not in json.loads(
               (plain / 'status.json').read_text(encoding='utf-8')), out[-200:])

    made = root / 'made'
    code, out = tool('project.py', 'init', made, '--path', 'create', '--timeline', 'page', '--page', 'film',
                     '--what', 'a launch film for a coding skill')
    fields = project.parse_front_matter((made / 'film.md').read_text(encoding='utf-8')) if (made / 'film.md').is_file() else {}
    frame = fields.get('frame') or {}
    record('record: init --path --timeline --page writes the record with every frame field and its state',
           code == 0 and fields.get('path') == 'create' and fields.get('timeline') == 'page' and fields.get('page') == 'film/'
           and frame.get('what') == 'a launch film for a coding skill' and frame.get('state', {}).get('what') == 'assumed'
           and frame.get('state', {}).get('audience') == 'missing' and frame.get('knows_by') == []
           and frame.get('cold_read') == {'state': 'not-run'}, str(fields)[:300])
    code, out = tool('project.py', 'status', made)
    record('record: status reads it back before the line: timeline and context counted',
           code == 0 and out.startswith('timeline: page · context: 1 assumed, 3 missing'), out.strip()[:200])

    (made / 'film.md').write_text(SPEC_FRAME, encoding='utf-8')
    parsed = project.parse_front_matter(SPEC_FRAME)
    knows = (parsed.get('frame') or {}).get('knows_by') or [{}]
    record('record: the SPEC §6 front matter reads back whole (flow mappings, lists, quotes, comments, null)',
           parsed.get('page') == 'film/' and parsed['frame']['why'] == 'they want video without a studio'
           and knows[0] == {'s': 3, 'what': 'what this is and who it is for', 'channel': 'type'}
           and parsed['frame']['waived'] is None and parsed['frame']['state']['audience'] == 'assumed',
           str(parsed)[:300])
    code, out = tool('project.py', 'status', made)
    status = json.loads((made / 'status.json').read_text(encoding='utf-8'))
    record('record: status prints "timeline: page · context: 2 confirmed, 2 assumed"',
           code == 0 and out.startswith('timeline: page · context: 2 confirmed, 2 assumed · '), out.strip()[:200])
    record('record: status.json gains timeline, path and context',
           status.get('timeline') == 'page' and status.get('path') == 'create'
           and status.get('context', {}).get('confirmed') == 2 and status.get('context', {}).get('assumed') == 2
           and status['context']['fields']['knows_by'] == 'assumed', str({k: status.get(k) for k in ('timeline', 'path', 'context')}))
    code, out = tool('project.py', 'status', made, '--json')
    report = json.loads(out) if code == 0 else {}
    record('record: status --json carries timeline, path and context, and the line once',
           report.get('timeline') == 'page' and report.get('context', {}).get('confirmed') == 2
           and report.get('line', '').count('timeline: page') == 1, out[-200:])

    paper = root / 'paper.md'
    paper.write_text('---\ntitle: a paper edit\nsize: 1920x1080\nfps: 30\n---\n\nint_01 0:01-0:03 hello\n', encoding='utf-8')
    cut = root / 'cut'
    code, out = tool('project.py', 'init', cut, '--path', 'cut', '--timeline', 'paper')
    code2, out2 = tool('project.py', 'init', cut, '--film', paper)
    text = (cut / 'film.md').read_text(encoding='utf-8') if (cut / 'film.md').is_file() else ''
    fields = project.parse_front_matter(text) if text else {}
    record('record: a paper edit brought in after the record keeps both: its settings and body, and the record on top',
           code == 0 and code2 == 0 and fields.get('timeline') == 'paper' and fields.get('title') == 'a paper edit'
           and text.rstrip().endswith('int_01 0:01-0:03 hello') and isinstance(fields.get('frame'), dict),
           (out + out2)[-200:] + ' | ' + text[:200])
    waived = root / 'waived'
    tool('project.py', 'init', waived, '--path', 'quick', '--timeline', 'file')
    film = waived / 'film.md'
    film.write_text(film.read_text(encoding='utf-8').replace('  waived: null', '  waived: {reason: "a quick trim", by: "person"}'),
                    encoding='utf-8')
    code, out = tool('project.py', 'status', waived)
    record('record: a waived frame reads as waived, with its reason in status.json',
           code == 0 and out.startswith('timeline: file · context: waived')
           and json.loads((waived / 'status.json').read_text(encoding='utf-8')).get('context', {}).get('waived') == 'a quick trim',
           out.strip()[:200])
