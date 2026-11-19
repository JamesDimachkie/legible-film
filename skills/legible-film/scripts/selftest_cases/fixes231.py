"""2.3.1 regressions: each case reproduces a fault an independent review found in 2.3.0 and fails on 2.3.0.

5   a render receipt bound to obsolete timing          (film_render.py, project.py add-version)
6   the blind handoff and its grading check            (pack.py, evals/judge_packet.py, evals/grade_task.py)
7   the render lock and the staged timing modules      (project.py run_render)
8   Python and the two Node timing checks disagreeing  (cue_list.py, cue_gen.cjs, film_capture.mjs, render_block.cjs)
9   required typography gates                          (film_check.py, look.py world-sheet)
14  rhythm comparison sampled too coarsely             (measure.py compare --as rebuild)

A review council of the 2.3.1 branch then found faults in those fixes; each lettered case fails on d20da59:
A  an unknown model name counted as its own family    (pack.family_of)
B  a legacy receipt whose cue list changed             (project._timing_binding)
C  modules staged from beside the cue list            (project.run_render, _timing_binding)
D  timing sampled after the render; module drift       (film_render.py, project._timing_binding)
E  a cue whose id is "__proto__"                       (cue_gen.cjs)
F  duplicate letters; the report's own status trusted (pack.reading_problems, check.py, grade_task.py)
G  a clear miss read as "measure again"                (measure.py compare --as rebuild)
H  world-sheet type clipped, overflowing, clamped     (look.py world-sheet)
I  a moved film failing its own typography gate       (film_check.py, look.py world-sheet)
J  alone/ under the readers' root                     (pack.py)
K  the render preload checking the page's module      (project.run_render)
L  add-version "screened" after the timing changed    (project.add_version)

A second council round found faults in those; each case from M fails on e7097a3:
M  add-version --render hashed the timing after it    (project.add_version)
N  "screened" by modification times                   (project.add_version, cue_list.compile_cue_constants)
O  a cue id "__proto__" lost in times.gen.js           (cue_list.py, cue_gen.cjs)
P  --reads . or a drive root                           (pack.make_pack)
Q  a world sheet copied to another film or folder     (film_check.py, look.py world-sheet)
R  modules beside an external cue list; the preload   (film_render.py, project.run_render, render_block.cjs)

A third council round found faults in those; each case from S fails on 011cc56:
S  a world sheet judged by a hash of text read        (world_spec.py, look.py world-sheet, film_check.py)
T  film_check.py needing numpy and Pillow for a sheet (film_check.py, world_spec.py)
U  "screened" with no timing modules and no receipt   (project.add_version)

Two release-gate reviews found faults on 6b78913; each case from V fails on 6b78913:
V  world-sheet location, moved projects, deep pages, BOM (world_spec.py, look.py, film_check.py)
W  the film.js reader raising or failing on kit films   (world_spec.py)
X  non-ASCII text crashing film_check.py on Windows      (film_check.py)
Y  boolean scores, vendor list, POSIX /, --verify      (pack.py, check.py)
Z  -0.0/ties, codegen errors, LF_CUES_GEN, refusal hints (cue_list.py, cue_gen.cjs, project.py, film_render.py)
AA setup.py SCRIPTS inventory guard & active-venv cache  (setup.py)

A fifth review found the two readers that guessed (film.js source, Markdown readings) wrong again; each case from AB
fails on d0e732f:
AB a world sheet checked by a reading of film.js         (world_spec.py, look.py, film_check.py)
AC a line-up reading read from Markdown                  (pack.py, references/eyes.md)
AD huge numbers, and Python and Node apart past 10^15 s or a film's rates and sizes  (cue_list.py, cue_gen.cjs)

The review of round 5 found boundary faults on 160657a; each case from AE fails on 160657a:
AE a redraw command no shell runs as printed (a quoted title) (world_spec.py, film_check.py)
AF line-up readings at the review's boundaries           (pack.py)
AG a 2.3.0 receipt registered with cues.spotted.json     (project._timing_binding)
AH folders named with accented, CJK or emoji characters (every script that prints; their readers)
AI a script that prints without setting its output up    (scripts/*.py)
AJ a scale colour-matrix name FFmpeg 8.0 refuses          (selftest_cases/speed.py)
AK a dependency message from an interpreter in a non-ASCII folder (every script's output set-up)
AL a child process's text read with the locale's strict codec    (every subprocess call)
AM film_capture.mjs doing nothing when started through a link (film_capture.mjs; /var on macOS)
AN a frame screenshot on Playwright's 30 s, saying nothing of the frame (film_capture.mjs)
"""
import ast
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path


def _write_lf(path, text):
    """Write TEXT with LF line ends (Path.write_text takes newline= only from Python 3.10)."""
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _synth_video(ffmpeg, path, freq=440, color='0x1a3355', color2='0x226688', dur=3.0):
    half = dur / 2.0
    vf = f"drawbox=x=120:y=80:w=240:h=120:color={color2}:t=fill:enable='gte(t,{half})'"
    cmd = [ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'color=c={color}:s=640x360:r=24:d={dur}',
           '-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=48000:duration={dur}',
           '-vf', vf, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if res.returncode:
        raise RuntimeError(f'ffmpeg failed for {path}: {res.stderr[-300:]}')


# ------------------------------------------------------------------------------------------------ 8: timing checks

# One table, run through cue_list.verify_cue_constants, film_capture.mjs verifyCuesGenSync and the render_block.cjs
# preload. Each row: a cue list the modules are generated from, what changes afterwards, and whether the modules must
# still be accepted. In 2.3.0 the two Node checks accepted a removed cue and a same-length wrong digest, put a cue
# on a half frame on another frame than Python, and all three accepted a shortened silence.
def _timing_table():
    def edit_cues(fn):
        return ('cues', fn)

    def edit_module(fn):
        return ('module', fn)

    def remove_second(doc):
        doc['events'] = doc['events'][:1]

    def zero_digest(text):
        start = text.index('CUES_SHA256 = "') + len('CUES_SHA256 = "')
        return text[:start] + '0' * 64 + text[start + 64:]

    def shorten_silence(doc):
        doc['events'][0]['t_end'] = 1.2

    def add_role(doc):
        doc['events'][0]['role'] = 'spotted'

    def move_cue(doc):
        doc['events'][0]['t'] = 0.75

    def move_section(doc):
        doc['sections'][0]['b'] = 1.5

    def proto_id(doc):
        doc['events'][0]['id'] = '__proto__'

    def inject_proto_export(text):
        import re as _re
        exported = {}
        for ln in text.splitlines():
            m = _re.match(r'^export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)(?:\s+as\s+const)?;\s*$', ln)
            if m:
                exported[m.group(1)] = json.loads(m.group(2))
        suf = ' as const' if ' as const;' in text else ''
        return text.splitlines()[0] + '\nexport const __proto__ = ' + json.dumps(exported) + suf + ';\n'

    two = {'version': 2, 'fps': 24, 'events': [{'id': 'a', 't': 0.5, 'scale': 'contact'},
                                               {'id': 'b', 't': 1.0, 'scale': 'contact'}]}
    return [
        ('a genuine cue on a half frame (1.1875 s at 24 fps)',
         {'version': 2, 'fps': 24, 'events': [{'id': 'hit', 't': 1.1875, 'scale': 'contact'}]}, None, True),
        ('a cue removed from the list', two, edit_cues(remove_second), False),
        ('CUES_SHA256 replaced by 64 zeros (same length, wrong value)', two, edit_module(zero_digest), False),
        ('a silence shortened from 1.5 s to 1.2 s',
         {'version': 2, 'fps': 24, 'duration': 3.0, 'events': [{'id': 'hush', 't': 1.0, 't_end': 1.5, 'scale': 'silence',
                                               'sound': 'silent'}]}, edit_cues(shorten_silence), False),
        ('a role added by spotting, no cue moved', two, edit_cues(add_role), True),
        ('a cue moved from 0.5 s to 0.75 s', two, edit_cues(move_cue), False),
        ('a section end moved',
         {'version': 2, 'fps': 30, 'sections': [{'id': 's1', 'a': 0, 'b': 1.0}],
          'events': [{'id': 'c', 't': 0.4, 'section': 's1'}]}, edit_cues(move_section), False),
        ('NTSC 29.97 fps with a section and a duration',
         {'version': 2, 'fps': 29.97, 'duration': 2.5, 'sections': [{'id': 'open', 'a': 0.0, 'b': 1.25}],
          'events': [{'id': 'k1', 't': 1.0}, {'id': 'k2', 't': 2.0021}]}, None, True),
        ('a rational fps string and a time on an exact rounding tie (1/128 s)',
         {'version': 2, 'fps': '30000/1001', 'events': [{'id': 'tie', 't': 0.0078125},
                                                         {'id': 'n', 'frame': 45}]}, None, True),
        ('a cue at -0.0 s and an exact 1/128 tie just under the 1e9 s bound',
         {'version': 2, 'fps': 24, 'events': [{'id': 'zero', 't': -0.0},
                                              {'id': 'bigtie', 't': 999999999.0078125}]}, None, True),
        ('export const __proto__ in times.gen.js (E Node null-prototype guard)',
         two, edit_module(inject_proto_export), False),
        # E, O: an id "__proto__" is lost in the object literals of times.gen.js, so a list naming one is refused by
        # all three (the Node checks had kept it in null-prototype objects and passed a module the film read without it)
        ('a cue renamed "__proto__" after codegen (E, O)', two, edit_cues(proto_id), False),
    ]


def case_8(tool, record, j, scripts, skip=None):
    cl = _load('lf_fix231_cl', scripts / 'cue_list.py')
    node = shutil.which('node')
    if not node:
        if skip:
            skip('fixes231: Python and both Node timing checks agree on one table', 'Node missing', 1)
        return
    capture_url = (scripts / 'film_capture.mjs').resolve().as_uri()
    probe = ("import {verifyCuesGenSync} from %s; try { verifyCuesGenSync(process.argv[1], process.argv[2]); "
             "process.exit(0); } catch (e) { console.error(e.message); process.exit(2); }" % json.dumps(capture_url))
    preload = (scripts / 'render_block.cjs').resolve().as_posix()
    rows, wrong = [], []
    for k, (name, doc, change, accept) in enumerate(_timing_table()):
        d = Path(j('fix231_timing', f'case{k}'))
        d.mkdir(parents=True, exist_ok=True)
        cues = d / 'cues.json'
        _write_lf(cues, json.dumps(doc, indent=1))
        cl.compile_cue_constants(cues)
        gen = d / 'times.gen.js'
        if change and change[0] == 'cues':
            changed = copy.deepcopy(doc)
            change[1](changed)
            _write_lf(cues, json.dumps(changed, indent=1))
        elif change:
            for name_gen in ('times.gen.js', 'times.gen.ts'):
                _write_lf(d / name_gen, change[1]((d / name_gen).read_text(encoding='utf-8')))
        py_ok = not cl.verify_cue_constants(cues, gen)
        r_cap = subprocess.run([node, '--input-type=module', '-e', probe, str(cues), str(gen)], capture_output=True,
                               text=True, encoding='utf-8', errors='replace')
        env = dict(os.environ, NODE_OPTIONS=f'--require "{preload}"', LF_CUES_FILE=str(cues.resolve()),
                   LF_CUES_GEN=str(gen.resolve()))
        env.pop('LF_BLOCK_LOG', None)
        r_pre = subprocess.run([node, '-e', 'process.exit(0)'], capture_output=True, text=True, encoding='utf-8',
                               errors='replace', env=env)
        cap_ok, pre_ok = r_cap.returncode == 0, r_pre.returncode == 0
        rows.append((name, py_ok, cap_ok, pre_ok))
        if not (py_ok == cap_ok == pre_ok == accept):
            wrong.append(f'{name}: python={py_ok} film_capture={cap_ok} render_block={pre_ok} want={accept} '
                         f'({(r_cap.stderr + r_pre.stderr).strip()[:160]})')
    record('fixes231 #8: Python and both Node timing checks agree on one table (removed cue, same-length wrong '
           'digest, half frame, shortened silence, moved section, NTSC, ties)',
           not wrong, '; '.join(wrong) or f'{len(rows)} cases agree')


# ------------------------------------------------------------------------------------------------ 7: render lock

def case_7(tool, record, j, scripts, skip=None):
    cl = _load('lf_fix231_cl7', scripts / 'cue_list.py')
    proj = _load('lf_fix231_project', scripts / 'project.py')
    page = Path(j('fix231_lock', 'page'))
    page.mkdir(parents=True, exist_ok=True)
    _write_lf(page / 'index.html', '<!doctype html><title>t</title>\n')
    doc = {'version': 2, 'fps': 24, 'events': [{'id': 'hit', 't': 0.25, 'scale': 'contact'}]}
    cues = page / 'cues.json'
    _write_lf(cues, json.dumps(doc))
    cl.compile_cue_constants(cues)
    moved = dict(doc, events=[{'id': 'hit', 't': 0.75, 'scale': 'contact'}])
    lock_path = Path(j('fix231_lock', 'heavy.lock'))
    out = Path(j('fix231_lock', 'out.mp4'))
    cmd = f'"{sys.executable}" -c "pass" {{page}} {{out}}'
    saved = {k: os.environ.get(k) for k in ('LF_HEAVY_LOCK', 'LF_HEAVY_LOCK_MARKER')}

    def attempt():
        """(refusal text or None, lock file left behind, lock variables left in this process)."""
        os.environ['LF_HEAVY_LOCK'] = str(lock_path)
        os.environ.pop('LF_HEAVY_LOCK_MARKER', None)
        refused = None
        try:
            proj.run_render(cmd, page, out, 0, 0.05, cues_file=cues, page_dir=page)
        except proj.Refused as error:
            refused = str(error)
        stranded = lock_path.exists()
        marker_left = os.environ.get('LF_HEAVY_LOCK_MARKER') is not None
        if stranded:
            lock_path.unlink()
        return refused, stranded, marker_left

    try:
        # both modules stale: refused, and the lock is released
        _write_lf(cues, json.dumps(moved))
        r1, stranded1, marker1 = attempt()
        # the JavaScript module regenerated, the TypeScript one still stale: refused before the engine runs
        cl.compile_cue_constants(cues, out_ts=Path(j('fix231_lock', 'elsewhere.ts')), out_js=page / 'times.gen.js')
        r2, stranded2, marker2 = attempt()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    record('fixes231 #7: a timing refusal releases the render lock, and a stale times.gen.ts is refused beside a '
           'valid times.gen.js',
           r1 is not None and not stranded1 and not marker1 and r2 is not None and 'times.gen.ts' in r2
           and not stranded2,
           f'stale both: refused={bool(r1)} lock_left={stranded1} env_left={marker1}; stale ts: refused={r2!r:.140} '
           f'lock_left={stranded2}')


# ------------------------------------------------------------------------------------------------ 14: rhythm

def case_14(tool, record, j, scripts, skip=None):
    measure = _load('lf_fix231_measure', scripts / 'measure.py')
    summary = {'events_per_10s': 5.0, 'median_hold_s': 1.2, 'median_move_s': 0.4, 'occupancy': 0.3}

    def profile(name, analysed, events):
        d = Path(j('fix231_rhythm', name))
        d.mkdir(parents=True, exist_ok=True)
        _write_lf(d / 'measure.json', json.dumps({'version': measure.VERSION, 'fps': 60.0, 'analysed_fps': analysed,
                                                 'events': events, 'summary': summary}))
        return d

    coarse = measure.compare_dirs(profile('src8', 8.0, [1.0]), profile('oth8', 8.0, [1.125]), mode='rebuild')
    fine_off = measure.compare_dirs(profile('src30', 30.0, [1.0]), profile('oth30', 30.0, [1.125]), mode='rebuild')
    fine_on = measure.compare_dirs(profile('src30b', 30.0, [1.0]), profile('oth30b', 30.0, [1.0167]), mode='rebuild')
    c_cli, out_cli = tool('measure.py', 'compare', j('fix231_rhythm', 'src8'), j('fix231_rhythm', 'oth8'),
                          '--as', 'rebuild')
    record('fixes231 #14: rebuild compare sampled at 8 fps for a 60 fps source is inconclusive, never on-rhythm '
           '(an event 7.5 source frames late had passed "within 2 frames")',
           coarse['status'] == 'inconclusive' and c_cli != 0 and fine_off['status'] == 'off-rhythm'
           and fine_on['status'] == 'on-rhythm',
           f"8fps={coarse['status']} (cli exit {c_cli}), 30fps late={fine_off['status']}, "
           f"30fps 1 frame={fine_on['status']}")
    # G: an event two seconds late is a miss however coarsely it was sampled; only an offset within what the sampling
    # cannot resolve (two source frames plus one sample) is "measure again"
    late = measure.compare_dirs(profile('src8g', 8.0, [1.0, 4.0]), profile('oth8g', 8.0, [3.0, 4.0]), mode='rebuild')
    near = measure.compare_dirs(profile('src8h', 8.0, [1.0, 4.0]), profile('oth8h', 8.0, [1.15, 4.0]), mode='rebuild')
    record('fixes231 G: at 8 fps sampling, an event 2 s late is off-rhythm and one within a sample is inconclusive',
           late['status'] == 'off-rhythm' and near['status'] == 'inconclusive',
           f"2 s late={late['status']}, 0.15 s late={near['status']}")


# ------------------------------------------------------------------------------------------------ 6: blind handoff

def case_6(tool, record, j, scripts, skip=None):
    pack = _load('lf_fix231_pack', scripts / 'pack.py')
    ffmpeg = shutil.which('ffmpeg')
    evals_dir = scripts.parents[2] / 'evals'
    # same vendor is one family however it is written; an empty family is none
    pairs = [('Claude', 'claude-opus-4-1', False), ('anthropic', 'Claude Opus', False), ('gpt-6.1-sol', 'OpenAI', False),
             ('Gemini 2.5', 'google', False), ('anthropic', 'google', True), ('claude', 'gpt-5', True)]
    fam_wrong = [(a, b) for a, b, want in pairs
                 if bool(pack.family_of(a) and pack.family_of(b) and pack.family_of(a) != pack.family_of(b)) != want] \
        if hasattr(pack, 'family_of') else ['pack.family_of missing']
    if not ffmpeg or not (evals_dir / 'judge_packet.py').is_file():
        record('fixes231 #6: model families normalise to their vendor', not fam_wrong, str(fam_wrong))
        if skip:
            skip('fixes231: blind handoff folders and grading', 'FFmpeg or evals missing', 1)
        return
    grade = _load('lf_fix231_grade', evals_dir / 'grade_task.py')
    run = Path(j('fix231_blind', 'run'))
    ws = run / 'workspace'
    (ws / 'deliver').mkdir(parents=True, exist_ok=True)
    _synth_video(ffmpeg, ws / 'clip.mp4', freq=440, dur=8.5)
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-ss', '2', '-t', '6', '-i', str(ws / 'clip.mp4'), '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(ws / 'deliver' / 'output.mp4')], check=True)
    ref = Path(j('fix231_blind', 'ref.mp4'))
    _synth_video(ffmpeg, ref, freq=554, color='0x241935', color2='0xc77dff', dur=2.5)
    pkt = Path(j('fix231_blind', 'packet'))
    r_pkt = subprocess.run([sys.executable, '-I', str(evals_dir / 'judge_packet.py'), 'quick-trim', '--run', str(run),
                            '--out', str(pkt), '--blind-pack-against', str(ref)],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
    readers = pkt.parent / f'{pkt.name}-lineup'
    keys = pkt.parent / f'{pkt.name}-blind-keys'
    key = json.loads((keys / 'pack-1-key.json').read_text(encoding='utf-8')) if (keys / 'pack-1-key.json').is_file() else {}
    letters = set(key.get('letters') or {})
    # every file readers are handed sits in a lettered line-up folder: nothing unlettered, nothing that shows ours
    outside = [str(p.relative_to(readers)) for p in readers.rglob('*') if p.is_file()
               and not (len(p.parts) >= 3 and p.parts[-3] == 'lineup' and p.parts[-2] in letters)] \
        if readers.is_dir() else ['no readers folder']
    record('fixes231 #6: the blind readers\' folder holds only the lettered line-up (no unlettered candidate)',
           r_pkt.returncode == 0 and bool(letters) and not outside,
           f'packet exit {r_pkt.returncode}; outside the line-up: {outside[:4]}')

    delivered = ws / 'deliver' / 'output.mp4'
    task = grade.tasks()['quick-trim']
    forged = Path(j('fix231_blind', 'forged.json'))
    _write_lf(forged, json.dumps({'film_sha256': _sha(delivered), 'cross_family': True, 'status': 'pass'}))
    forged_row = grade.blind_pack_check(forged, ws, task)
    ours = key.get('ours_letter', 'A')
    other = next((x for x in sorted(letters) if x != ours), 'B')

    def reading(family, tier):
        return {'model_family': family, 'overall_ranking': [ours, other],
                'films': {ours: {'tier': tier, 'pacing': 8, 'visual_clutter': 8, 'callout_placement': 8},
                          other: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}}}

    for name, fam in (('a', 'anthropic'), ('b', 'google'), ('same', 'claude-opus-4-1')):
        _write_lf(Path(j('fix231_blind', f'read_{name}.json')), json.dumps(reading(fam, 'studio')))
    genuine = Path(j('fix231_blind', 'genuine.json'))
    same = Path(j('fix231_blind', 'same.json'))
    c_g, _ = tool('pack.py', 'record', str(keys / 'pack-1-key.json'), '--lineup-a', j('fix231_blind', 'read_a.json'),
                  '--lineup-b', j('fix231_blind', 'read_b.json'), '--out', str(genuine))
    tool('pack.py', 'record', str(keys / 'pack-1-key.json'), '--family-a', 'Claude',
         '--lineup-a', j('fix231_blind', 'read_a.json'), '--lineup-b', j('fix231_blind', 'read_same.json'),
         '--out', str(same))
    same_doc = json.loads(same.read_text(encoding='utf-8')) if same.is_file() else {}
    genuine_row = grade.blind_pack_check(genuine, ws, task)
    same_row = grade.blind_pack_check(same, ws, task)
    record('fixes231 #6: the blind-pack grade needs two complete readings from two vendors, bound to the film; '
           '"Claude" and "claude-opus-4-1" are one family',
           (forged_row or {}).get('state') != 'pass' and (same_row or {}).get('state') != 'pass'
           and same_doc.get('cross_family') is False and c_g == 0 and (genuine_row or {}).get('state') == 'pass'
           and not fam_wrong,
           f"forged={(forged_row or {}).get('state')}, same-vendor={(same_row or {}).get('state')} "
           f"(cross_family {same_doc.get('cross_family')}), genuine={(genuine_row or {}).get('state')}, "
           f"family pairs wrong={fam_wrong}")

    # check.py --blind-pack, the CLI's own check, took the same report's status and cross_family on trust (and a report
    # with no film hash for any film): the forged and hashless reports are not a pass, the genuine one still is
    hashless = Path(j('fix231_blind', 'hashless.json'))
    _write_lf(hashless, json.dumps({k: v for k, v in json.loads(genuine.read_text(encoding='utf-8')).items() if k != 'film_sha256'})
              if genuine.is_file() else '{}')
    empty_readers = Path(j('fix231_blind', 'empty-readers.json'))
    _write_lf(empty_readers, json.dumps({'film_sha256': _sha(delivered), 'cross_family': True, 'status': 'pass', 'readers': {}}))
    states = {}
    for name, report in (('forged', forged), ('empty-readers', empty_readers), ('same-vendor', same), ('hashless', hashless),
                         ('genuine', genuine)):
        out = Path(j('fix231_blind', f'check-{name}.json'))
        tool('check.py', '--file', str(delivered), '--no-speech', '--blind-pack', str(report), '--json', str(out))
        rows = json.loads(out.read_text(encoding='utf-8')).get('items', []) if out.is_file() else []
        states[name] = next((r.get('state') for r in rows if r.get('id') == 'blind_pack' or r.get('group') == 'blind_pack'), None)
    record('fixes231 #6: check.py --blind-pack passes only two complete cross-family readings bound to this film',
           states.get('genuine') == 'pass' and all(states.get(n) not in ('pass', None) for n in ('forged', 'empty-readers', 'same-vendor', 'hashless')),
           f'states={states}')


def _reading_report(sha, tier='studio', ours_first=True, families=('anthropic', 'google'), letters=('A', 'B')):
    """A blind-pack.json as pack.py record writes it: two readers of the line-up LETTERS, ours A, yardstick B."""
    ours, other = 'A', 'B'
    ranking = list(letters) if len(set(letters)) < len(letters) else ([ours, other] if ours_first else [other, ours])

    def reader(family):
        return {'model_family': family, 'ranking': ranking, 'ours_rank': ranking.index(ours) + 1,
                'yardstick_rank': ranking.index(other) + 1 if other in ranking else None, 'ours_tier': tier,
                'amateur_flag': tier in ('beginner', 'hobbyist', 'skilled hobbyist'), 'below_yardstick': not ours_first,
                'dimensions': {d: {'ours': 8 if ours_first else 3, 'yardstick': 6 if ours_first else 8}
                               for d in ('pacing', 'visual_clutter', 'callout_placement')}, 'steals': []}
    return {'version': 1, 'tool': 'pack.py record', 'film_sha256': sha, 'ours_letter': ours, 'letters': list(letters),
            'yardstick_letter': other, 'cross_family': True, 'families': list(families),
            'readers': {'a': reader(families[0]), 'b': reader(families[1])},
            'dimension_averages': {}, 'status': 'pass', 'reasons': []}


def case_A(tool, record, j, scripts, skip=None):
    pack = _load('lf_fix231_packA', scripts / 'pack.py')
    same = [('gpt-6.1-sol', 'Sol'), ('Gemini', 'Carbon'), ('Terra', 'Sol'), ('GPT-6.1 Terra', 'openai'),
            ('Claude Opus 5.5', 'Fable'), ('Antigravity', 'Gemini 3'), ('Sonnet', 'haiku')]
    cross = [('Sol', 'Claude'), ('Carbon', 'Fable'), ('Terra', 'Carbon')]
    unknown = ['Mystery-7', 'reader two', '']
    wrong = [f'{a}/{b} not one family' for a, b in same
             if not (pack.family_of(a) and pack.family_of(a) == pack.family_of(b))]
    wrong += [f'{a}/{b} not two families' for a, b in cross
              if not (pack.family_of(a) and pack.family_of(b) and pack.family_of(a) != pack.family_of(b))]
    wrong += [f'{n!r} read as {pack.family_of(n)!r}' for n in unknown if pack.family_of(n)]
    for fams in (('gpt-6.1-sol', 'Sol'), ('Mystery-7', 'Claude')):
        if not pack.reading_problems(_reading_report('0' * 64, families=fams)):
            wrong.append(f'readers {fams} counted as two families')
    record('fixes231 A: a model name the table does not know is no family (Sol, Terra, Carbon map to their vendors)',
           not wrong, '; '.join(wrong) or f'{len(same) + len(cross) + len(unknown) + 2} names checked')


def case_F(tool, record, j, scripts, skip=None):
    pack = _load('lf_fix231_packF', scripts / 'pack.py')
    check = _load('lf_fix231_check', scripts / 'check.py')
    evals_dir = scripts.parents[2] / 'evals'
    grade = _load('lf_fix231_gradeF', evals_dir / 'grade_task.py') if (evals_dir / 'grade_task.py').is_file() else None
    ws = Path(j('fix231_verdict', 'ws'))
    (ws / 'deliver').mkdir(parents=True, exist_ok=True)
    film = ws / 'deliver' / 'output.mp4'
    film.write_bytes(b'stand-in film bytes')
    sha = _sha(film)
    dup = pack.reading_problems(_reading_report(sha, letters=('A', 'B', 'A')))
    states = {}
    for name, doc in (('genuine', _reading_report(sha)),
                      ('poor', _reading_report(sha, tier='beginner', ours_first=False)),
                      ('amateur-first', _reading_report(sha, tier='beginner', ours_first=True)),
                      ('duplicate-letters', _reading_report(sha, letters=('A', 'B', 'A')))):
        path = Path(j('fix231_verdict', f'{name}.json'))
        _write_lf(path, json.dumps(doc))
        states[name] = (check.blind_pack_item(path, sha).get('state'),
                        (grade.blind_pack_check(path, ws, grade.tasks()['quick-trim']) or {}).get('state')
                        if grade else 'pass')
    ok = (bool(dup) and states['genuine'] == ('pass', 'pass')
          and all(s != 'pass' for n in ('poor', 'amateur-first', 'duplicate-letters') for s in states[n]))
    record('fixes231 F: duplicate line-up letters are no line-up, and check.py and the grader take the verdict from '
           'the readings (two "beginner" readings, even ranked first, do not pass)',
           ok, f'duplicate letters: {dup[:1] or "accepted"}; (check, grade) states {states}')


# ------------------------------------------------------------------------------------------------ B C D K: binding

def _bind_module_env():
    return {k: os.environ.get(k) for k in ('LF_HEAVY_LOCK', 'LF_HEAVY_LOCK_MARKER')}


def _restore_env(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def case_binding(tool, record, j, scripts, skip=None):
    from types import SimpleNamespace
    cl = _load('lf_fix231_clB', scripts / 'cue_list.py')
    proj = _load('lf_fix231_projB', scripts / 'project.py')
    doc = {'version': 2, 'fps': 24, 'events': [{'id': 'hit', 't': 0.25, 'scale': 'contact'}]}
    moved = dict(doc, events=[{'id': 'hit', 't': 0.75, 'scale': 'contact'}])

    def page_at(name, modules=True, cues_elsewhere=False):
        page = Path(j('fix231_bind', name, 'page'))
        page.mkdir(parents=True, exist_ok=True)
        _write_lf(page / 'index.html', '<!doctype html><title>t</title>\n')
        home = Path(j('fix231_bind', name, 'list')) if cues_elsewhere else page
        home.mkdir(parents=True, exist_ok=True)
        cues = home / 'cues.json'
        _write_lf(cues, json.dumps(doc))
        if modules:
            cl.compile_cue_constants(cues)
        return page, cues

    def bind(receipt, cues, page):
        listed = SimpleNamespace(sha256=_sha(cues))
        try:
            return 'reasons' if proj._timing_binding(cl, listed, receipt, cues, page) else 'binds'
        except proj.Refused as error:
            return 'refused: ' + str(error)[:90]

    # B: a receipt that records only the cue list's hash, from a page with no modules and from one with them
    page, cues = page_at('b_plain', modules=False)
    b_plain = bind({'cues_sha256': '0' * 64}, cues, page)
    b_same = bind({'cues_sha256': _sha(cues)}, cues, page)
    page, cues = page_at('b_modules')
    b_modules = bind({'cues_sha256': '0' * 64}, cues, page)
    record('fixes231 B: a receipt whose cue-list hash is not the list\'s is refused, with or without generated modules',
           b_plain.startswith('refused') and b_modules.startswith('refused') and b_same == 'binds',
           f'no modules: {b_plain}; with modules: {b_modules}; same list: {b_same}')

    # D: the timing hash matches, the modules are the ones rendered, but they do not hold the list's timing
    page, cues = page_at('d_drift')
    _write_lf(cues, json.dumps(moved))
    rendered = {n: _sha(page / n) for n in ('times.gen.js', 'times.gen.ts')}
    d_drift = bind({'cues_timing_sha256': cl.cue_timing_sha256(cues), 'generated': rendered, 'cues_sha256': _sha(cues)},
                   cues, page)
    record('fixes231 D: generated modules that do not hold the cue list\'s timing are refused even when the receipt\'s '
           'timing hash matches', d_drift.startswith('refused'), d_drift)

    lock_path = Path(j('fix231_bind', 'heavy.lock'))
    saved = _bind_module_env()

    def render(page, cues, cmd, out_name):
        os.environ['LF_HEAVY_LOCK'] = str(lock_path)
        os.environ.pop('LF_HEAVY_LOCK_MARKER', None)
        try:
            return proj.run_render(cmd, page, Path(j('fix231_bind', out_name)), 0, 0.05, cues_file=cues, page_dir=page)
        except proj.Refused as error:
            return 'refused: ' + str(error)[:120]

    probe = Path(j('fix231_bind', 'probe.py'))
    _write_lf(probe, 'import json, os, sys\nopen(sys.argv[2] + ".env.json", "w").write(json.dumps('
                     '{"gen": os.environ.get("LF_CUES_GEN"), "page": sys.argv[1]}))\n')
    cmd = f'"{sys.executable}" "{probe}" {{page}} {{out}}'
    try:
        # C: modules beside a cue list kept outside the page are staged and recorded; the receipt must still bind
        page, cues = page_at('c_beside', cues_elsewhere=True)
        ran = render(page, cues, cmd, 'c.mp4')
        c_state = ran if isinstance(ran, str) else bind(
            {'cues_timing_sha256': cl.cue_timing_sha256(cues), 'generated': ran['generated'], 'cues_sha256': _sha(cues)},
            cues, page)
        record('fixes231 C: a receipt for modules the render staged from beside the cue list binds when nothing changed',
               c_state == 'binds' and not isinstance(ran, str) and bool(ran['generated']), c_state)

        # K: the preload is pointed at the staged module the engine reads, and the staged copies are verified
        page, cues = page_at('k_staged')
        ran = render(page, cues, cmd, 'k.mp4')
        seen = json.loads(Path(j('fix231_bind', 'k.mp4.env.json')).read_text(encoding='utf-8')) \
            if Path(j('fix231_bind', 'k.mp4.env.json')).is_file() else {}
        # LF_CUES_GEN names every staged module without path-separator collisions (R, Z): each must be in the staged page
        given = cl.parse_cues_gen_env(seen.get('gen')) if hasattr(cl, 'parse_cues_gen_env') else \
            [g for g in (seen.get('gen') or '').split(os.pathsep) if g]
        in_staged = len(given) == 2 and all(Path(g).resolve().parent == Path(seen.get('page', '.')).resolve()
                                            for g in given)
        stale_dir = Path(j('fix231_bind', 'k_stale'))
        stale_dir.mkdir(parents=True, exist_ok=True)
        _write_lf(stale_dir / 'cues.json', json.dumps(moved))
        cl.compile_cue_constants(stale_dir / 'cues.json')
        stale = (stale_dir / 'times.gen.js').read_bytes()
        real_copy = shutil.copyfile

        def racing_copy(src, dst, *a, **k):
            # the module changes between its check and its copy into the staged page
            result = real_copy(src, dst, *a, **k)
            if Path(dst).name == 'times.gen.js' and 'lf-page-' in str(dst):
                Path(dst).write_bytes(stale)
            return result
        shutil.copyfile = racing_copy
        try:
            raced = render(page, cues, cmd, 'k2.mp4')
        finally:
            shutil.copyfile = real_copy
        record('fixes231 K: the render preload checks the staged module the engine reads, and a staged copy that '
               'differs from the checked module is refused',
               in_staged and isinstance(raced, str) and raced.startswith('refused'),
               f"preload given {seen.get('gen')} for page {seen.get('page')}; raced copy: "
               f"{raced if isinstance(raced, str) else 'rendered'}")
    finally:
        _restore_env(saved)
        if lock_path.exists():
            lock_path.unlink()


# ------------------------------------------------------------------------------------------------ J: alone/

def case_J(tool, record, j, scripts, skip=None):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        if skip:
            skip('fixes231 J: alone/ kept out of the readers\' root', 'FFmpeg missing', 1)
        return
    pack = _load('lf_fix231_packJ', scripts / 'pack.py')
    film, ref = Path(j('fix231_alone', 'film.mp4')), Path(j('fix231_alone', 'ref.mp4'))
    film.parent.mkdir(parents=True, exist_ok=True)
    _synth_video(ffmpeg, film, dur=3.0)
    _synth_video(ffmpeg, ref, freq=554, color='0x241935', color2='0xc77dff', dur=3.0)
    reads = Path(j('fix231_alone', 'reads'))
    key = pack.make_pack(film, [ref], Path(j('fix231_alone', 'keys')), reads_root=reads)
    alone = Path(key['alone']['dir']).resolve()
    under = [str(p) for p in reads.rglob('alone')]
    try:
        pack.make_pack(film, [ref], Path(j('fix231_alone', 'keys2')), reads_root=reads, alone_root=reads)
        same_root = 'accepted'
    except ValueError as error:
        same_root = 'refused: ' + str(error)[:80]
    record('fixes231 J: with a line-up, alone/ is never under the readers\' root (by default or by --alone-reads)',
           not under and alone.is_dir() and reads.resolve() not in alone.parents and same_root.startswith('refused'),
           f'alone/ under the readers\' root: {under[:2]}; alone at {alone}; --alone-reads = --reads: {same_root}')


# ------------------------------------------------------------------------------------------------ 9: typography

def _ink_runs(png, rgb, x0=776, x1=1836, y0=260, tol=40):
    """Contiguous row runs (start, end) in a column of a sheet holding pixels near RGB, top to bottom from Y0."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(png).convert('RGB')).astype(int)[y0:, x0:x1]
    near = (np.abs(a - np.array(rgb)).sum(axis=2) <= tol).any(axis=1)
    runs, start = [], None
    for y, hit in enumerate(near):
        if hit and start is None:
            start = y
        elif not hit and start is not None:
            runs.append((y0 + start, y0 + y))
            start = None
    if start is not None:
        runs.append((y0 + start, y0 + len(near)))
    return runs


def case_9_sheet(tool, record, j, scripts, skip=None):
    kit_src = scripts.parent / 'assets' / 'kit'
    film = Path(j('fix231_sheet', 'film'))
    shutil.copytree(kit_src, film)
    shutil.copy2(film / 'films' / 'starter' / 'film.js', film / 'film.js')
    heights = {}
    for disp, sec in ((220, 110), (148, 72)):
        out = Path(j('fix231_sheet', f'sheet-{disp}.png'))
        c, o = tool('look.py', 'world-sheet', str(film), '--out', str(out), '--display-px', str(disp),
                    '--secondary-px', str(sec), '--fg', '#F4F1EA', '--muted', '#9BA3B0', '--json')
        meta = json.loads(out.with_suffix('.json').read_text(encoding='utf-8')) if out.with_suffix('.json').is_file() else {}
        ink = _ink_runs(out, (244, 241, 234)) if out.is_file() else []
        display = ink[0] if ink else (0, 0)
        muted = [r for r in _ink_runs(out, (155, 163, 176)) if r[0] >= display[1]] if out.is_file() else []
        heights[disp] = (display[1] - display[0], (muted[0][1] - muted[0][0]) if muted else 0,
                         meta.get('display_px'), meta.get('secondary_px'), c)
    big, small = heights[220], heights[148]
    ratio_d = big[0] / max(1, small[0])
    ratio_s = big[1] / max(1, small[1])
    record('fixes231 #9: world sheets asked for at 220/110 and 148/72 px draw type at those sizes and report them',
           big[4] == 0 and small[4] == 0 and 1.3 <= ratio_d <= 1.7 and 1.3 <= ratio_s <= 1.8
           and big[2:4] == (220, 110) and small[2:4] == (148, 72),
           f'display ink {big[0]} vs {small[0]} px (x{ratio_d:.2f}, asked x1.49); secondary {big[1]} vs {small[1]} px '
           f'(x{ratio_s:.2f}, asked x1.53); reported {big[2:4]} and {small[2:4]}')

    # H: at 220/110 the display line had been cut to "SHIP CLE" and the secondary drawn past the panel and the canvas
    import numpy as np
    from PIL import Image, ImageDraw
    look = _load('lf_fix231_look', scripts / 'look.py')
    png = Path(j('fix231_sheet', 'sheet-220.png'))
    problems = []
    if png.is_file():
        a = np.asarray(Image.open(png).convert('RGB')).astype(int)
        h, w = a.shape[:2]

        def near(region, rgb):
            return (np.abs(region - np.array(rgb)).sum(axis=2) <= 40)
        # nothing drawn in the margin right of the specimen panel (the panel ends 56 px before the sheet's edge)
        margin = a[152:, w - 56:]
        if near(margin, (244, 241, 234)).any() or near(margin, (155, 163, 176)).any():
            problems.append('type drawn past the specimen panel')
        # the whole display line: as much ink as "SHIP CLEAN." set alone at 220 px with the same font and tracking
        font = look._font(220, 'sans')
        alone = Image.new('RGB', (3200, 400), (27, 30, 36))
        look._draw_tracked(ImageDraw.Draw(alone), (20, 20), 'SHIP CLEAN.', font, 220, -0.035, (244, 241, 234))
        want = int(near(np.asarray(alone).astype(int), (244, 241, 234)).sum())
        muted_rows = [y for y in range(276, h) if near(a[y:y + 1, 736:w - 56], (155, 163, 176)).sum() > 40]
        stop = muted_rows[0] if muted_rows else h
        got = int(near(a[260:stop, 736:w - 56], (244, 241, 234)).sum())
        if not 0.92 <= got / max(1, want) <= 1.08:
            problems.append(f'display ink {got} px against {want} px for the whole line')
    else:
        problems.append('no 220 px sheet')
    eight = look._font(8, 'sans')
    if getattr(eight, 'size', 8) != 8:
        problems.append(f'an 8 px size drawn at {eight.size} px')
    c_huge, o_huge = tool('look.py', 'world-sheet', str(film), '--out', j('fix231_sheet', 'huge.png'),
                          '--display-px', '2400', '--secondary-px', '110')
    if c_huge == 0:
        problems.append('a 2400 px display line that no sheet can hold was drawn without a word')
    record('fixes231 H: world-sheet type at 220/110 px is drawn whole, inside its panel; sizes under 10 px are drawn '
           'at their size; a size it cannot draw is reported', not problems,
           '; '.join(problems) or f'exit for 2400 px: {c_huge} ({o_huge.strip()[-90:]})')


GOOD_FILM = """
export default function film(kit) {
  const { block, clock } = kit;
  const T = clock({ bpm: 120, offset: 0 });
  const Card = block('card', (ctx) => {
    const g = ctx.group;
    const p = ctx.colour('paper');
    ctx.ground(0, 'ink');
    const main = ctx.textNode(g, { string: 'Let it stand.', font: 'serif', size: 46, tracking: -0.035, color: p });
    main.rest({ y: -32 });
    const sub = ctx.textNode(g, { string: 'PROOF TABLE', font: 'serif', fontStyle: 'italic', size: 20, tracking: -0.035, color: p });
    sub.rest({ y: 40 });
    ctx.text({ id: 'serif-main', role: 'headline', string: main.string, nodes: [main], readFrom: 0 });
    ctx.text({ id: 'serif-sub', role: 'qualifier', string: sub.string, nodes: [sub], readFrom: 0 });
    ctx.cue({ id: 'open-hit', t: 0.25, scale: 'contact', role: 'tap', picture: 'held', decision: 'held proof card' });
    return { len: 2.0, ground0: ctx.colour('ink') };
  });
  return {
    title: 'Gate Film', size: [640, 360], fps: 24, beat: { bpm: T.bpm, offset: 0 },
    frame: { what: 'proof', audience: 'editors', why: 'clarity', knows_by: '2s' },
    scenes: [Card()],
  };
}
"""


def _gated_film(kit_src, folder):
    shutil.copytree(kit_src, folder)
    _write_lf(folder / 'film.js', GOOD_FILM.lstrip())
    _write_lf(folder / 'gates.json', '{"world_sheet": "required", "typography": "required"}\n')


def case_9_gates(tool, record, j, scripts, skip=None):
    kit_src = scripts.parent / 'assets' / 'kit'
    # control: the gated film with its own sheet and the release's analyser passes
    control = Path(j('fix231_gate', 'control'))
    _gated_film(kit_src, control)
    tool('look.py', 'world-sheet', str(control))
    c_ctl, o_ctl = tool('film_check.py', str(control), '--size', '640x360')
    if c_ctl == 2 and ('needs node' in o_ctl.lower() or 'playwright' in o_ctl.lower() or 'missing' in o_ctl.lower()):
        if skip:
            skip('fixes231: required typography gates in film_check.py', 'Node, Chromium or Playwright missing', 2)
        return
    # the same film with an analyser that reports no typography (as the 2.2.0 analyser did)
    old = Path(j('fix231_gate', 'old_analyser'))
    _gated_film(kit_src, old)
    analyser = old / 'lf' / 'analyse.js'
    text = analyser.read_text(encoding='utf-8')
    _write_lf(analyser, text.replace('    typography,\n', '', 1))
    tool('look.py', 'world-sheet', str(old))
    c_old, o_old = tool('film_check.py', str(old), '--size', '640x360')
    record('fixes231 #9: a required typography gate fails when the analyser supplies no typography data',
           c_ctl == 0 and '    typography,\n' in text and c_old == 1 and 'no typography data' in o_old,
           f'control exit {c_ctl}; no-typography analyser exit {c_old}: {o_old.strip()[-200:]}')
    # another film's sheet in the parent folder's refs/ is not this film's sheet
    parent = Path(j('fix231_gate', 'parent'))
    film = parent / 'film'
    parent.mkdir(parents=True, exist_ok=True)
    _gated_film(kit_src, film)
    other = parent / 'other'
    _gated_film(kit_src, other)
    tool('look.py', 'world-sheet', str(other), '--out', str(parent / 'refs' / 'world-sheet.png'))
    c_par, o_par = tool('film_check.py', str(film), '--size', '640x360')
    record('fixes231 #9: a required world sheet that belongs to another film (parent refs/) does not count',
           (parent / 'refs' / 'world-sheet.json').is_file() and c_par == 1 and 'world sheet missing' in o_par,
           f'exit {c_par}: {o_par.strip()[-200:]}')
    # I: the gated film, copied elsewhere with its own sheet, is still the film the sheet was drawn for
    moved = Path(j('fix231_gate', 'moved', 'control-copy'))
    shutil.copytree(control, moved)
    c_mv, o_mv = tool('film_check.py', str(moved), '--size', '640x360')
    record('fixes231 I: a gated film copied to another folder passes with the world sheet it carries',
           c_ctl == 0 and c_mv == 0, f'control exit {c_ctl}; copy exit {c_mv}: {o_mv.strip()[-200:]}')


# ------------------------------------------------------------------------------------------------ 5: receipt timing

IMPORT_FILM = """
import { CLOCK, TIMES } from './times.gen.js';
export default function film(kit) {
  const { block, clock } = kit;
  const T = clock({ bpm: 120, offset: 0 });
  const Card = block('card', (ctx) => {
    const g = ctx.group;
    ctx.ground(0, 'ink');
    const main = ctx.textNode(g, { string: 'ONE CLOCK.', font: 'display', size: 48, tracking: -0.035, color: ctx.colour('paper') });
    main.rest({ y: 0 });
    ctx.text({ id: 'clock-main', role: 'headline', string: main.string, nodes: [main], readFrom: 0 });
    ctx.cue({ id: 'land-hit', t: TIMES['land-hit'] ?? 0.25, scale: 'contact', role: 'tap', picture: 'held', decision: 'held title' });
    return { len: 2.0, ground0: ctx.colour('ink'), camera: () => ({ drift: false }) };
  });
  return {
    title: 'Receipt Timing', size: [320, 180], fps: 24, beat: { bpm: T.bpm, offset: 0 },
    frame: { what: 'sync', audience: 'makers', why: 'single source', knows_by: '1.2s' },
    scenes: [Card({ len: 2.0 })],
  };
}
"""


def case_5(tool, record, j, scripts, skip=None):
    kit_src = scripts.parent / 'assets' / 'kit'
    film = Path(j('fix231_receipt', 'film'))
    shutil.copytree(kit_src, film)
    _write_lf(film / 'film.js', IMPORT_FILM.split('\n', 2)[2].replace("TIMES['land-hit'] ?? 0.25", '0.25'))
    c0, o0 = tool('film_check.py', str(film), '--size', '320x180')
    if c0 == 2 and ('needs node' in o0.lower() or 'playwright' in o0.lower() or 'missing' in o0.lower()):
        if skip:
            skip('fixes231: render receipt bound to the cue timing', 'Node, Chromium or Playwright missing', 1)
        return
    if not (film / 'cues.json').is_file():
        record('fixes231 #5: a render receipt binds only the cue timing and generated modules it rendered', False,
               f'film_check exported no cue list (exit {c0}): {o0.strip()[-200:]}')
        return
    tool('cue_list.py', 'codegen', str(film / 'cues.json'))
    _write_lf(film / 'film.js', IMPORT_FILM.lstrip())
    c1, o1 = tool('film_check.py', str(film), '--size', '320x180')
    mp4 = Path(j('fix231_receipt', 'render.mp4'))
    c2, o2 = tool('film_render.py', str(film), '--cues', str(film / 'cues.json'), '--size', '320x180', '--preview',
                  '--force', '--out', str(mp4))
    ca, oa = tool('project.py', 'add-version', j('fix231_receipt', 'proj_a'), '--cues', str(film / 'cues.json'),
                  '--file', str(mp4), '--receipt', str(mp4) + '.manifest.json')
    man_a = Path(j('fix231_receipt', 'proj_a', 'cuts', 'v001', 'manifest.json'))
    bind_a = (json.loads(man_a.read_text(encoding='utf-8')).get('identity') or {}).get('binding') if man_a.is_file() else None
    # make_film.receipt_for carries both cues_timing_sha256 (binds spotted cues) and generated (refuses deleted modules)
    mf = _load('lf_fix231_mf', scripts / 'make_film.py')
    derived_path = Path(j('fix231_receipt', 'derived.manifest.json'))
    _write_lf(derived_path, json.dumps(mf.receipt_for(str(mp4) + '.manifest.json', 'encode', mp4), indent=1))
    spotted = Path(j('fix231_receipt', 'cues.spotted.json'))
    sdoc = json.loads((film / 'cues.json').read_text(encoding='utf-8'))
    sdoc['picture']['path'] = str(film.resolve().as_posix()) + '/'
    for ev in sdoc.get('events') or []:
        ev['role'] = 'spotted-tap'
    _write_lf(spotted, json.dumps(sdoc, indent=1))
    cs, os_ = tool('project.py', 'add-version', j('fix231_receipt', 'proj_spot'), '--cues', str(spotted),
                   '--file', str(mp4), '--receipt', str(derived_path))
    bind_spot = _binding(j('fix231_receipt', 'proj_spot'))
    saved_gen = {n: (film / n).read_bytes() for n in ('times.gen.js', 'times.gen.ts')}
    for n in saved_gen:
        (film / n).unlink()
    try:
        cdel, odel = tool('project.py', 'add-version', j('fix231_receipt', 'proj_del'), '--cues', str(film / 'cues.json'),
                          '--file', str(mp4), '--receipt', str(derived_path))
    finally:
        for n, b in saved_gen.items():
            (film / n).write_bytes(b)
    bind_del = _binding(j('fix231_receipt', 'proj_del'))
    record('fixes231 #5: make_film.receipt_for preserves cues_timing_sha256 (binding a spotted cue list) and generated '
           '(refusing deleted timing modules)',
           cs == 0 and bind_spot == 'receipt' and (cdel != 0 or bind_del != 'receipt'),
           f'spotted={cs}/{bind_spot} ({os_.strip()[-100:]}); deleted-gen={cdel}/{bind_del} ({odel.strip()[-100:]})')
    # move the cue from 0.25 s to 0.75 s and regenerate both modules; the old render must not bind
    doc = json.loads((film / 'cues.json').read_text(encoding='utf-8'))
    for ev in doc.get('events') or []:
        if ev.get('id') == 'land-hit':
            ev['t'] = 0.75
            ev.pop('frame', None)
    _write_lf(film / 'cues.json', json.dumps(doc, indent=1))
    # first with the modules as rendered (only the list's timing moved), then with both regenerated
    cc, oc = tool('project.py', 'add-version', j('fix231_receipt', 'proj_c'), '--cues', str(film / 'cues.json'),
                  '--file', str(mp4), '--receipt', str(mp4) + '.manifest.json')
    man_c = Path(j('fix231_receipt', 'proj_c', 'cuts', 'v001', 'manifest.json'))
    bind_c = (json.loads(man_c.read_text(encoding='utf-8')).get('identity') or {}).get('binding') if man_c.is_file() else None
    cg, og = tool('cue_list.py', 'codegen', str(film / 'cues.json'))
    cb, ob = tool('project.py', 'add-version', j('fix231_receipt', 'proj_b'), '--cues', str(film / 'cues.json'),
                  '--file', str(mp4), '--receipt', str(mp4) + '.manifest.json')
    man_b = Path(j('fix231_receipt', 'proj_b', 'cuts', 'v001', 'manifest.json'))
    bind_b = (json.loads(man_b.read_text(encoding='utf-8')).get('identity') or {}).get('binding') if man_b.is_file() else None
    record('fixes231 #5: a render receipt binds only the cue timing and generated modules it rendered (a moved cue '
           'with regenerated modules no longer registers the old render as binding)',
           c1 == 0 and c2 == 0 and ca == 0 and bind_a == 'receipt' and cg == 0 and (cc != 0 or bind_c != 'receipt')
           and (cb != 0 or bind_b != 'receipt'),
           f'check={c1} render={c2} before-move={ca}/{bind_a} moved-list-only={cc}/{bind_c} codegen={cg} '
           f'moved-and-regenerated={cb}/{bind_b}: {oc.strip()[-160:]} | {ob.strip()[-160:]}')


def case_DL(tool, record, j, scripts, skip=None):
    """D: the receipt records the cue timing the render was given, not the list as it stands when the render ends.
    L: add-version without a receipt does not call an older render "screened" after the cue list changed."""
    kit_src = scripts.parent / 'assets' / 'kit'
    film = Path(j('fix231_during', 'film'))
    shutil.copytree(kit_src, film)
    _write_lf(film / 'film.js', IMPORT_FILM.split('\n', 2)[2].replace("TIMES['land-hit'] ?? 0.25", '0.25'))
    c0, o0 = tool('film_check.py', str(film), '--size', '320x180')
    if c0 == 2 and ('needs node' in o0.lower() or 'playwright' in o0.lower() or 'missing' in o0.lower()):
        if skip:
            skip('fixes231: timing sampled before the render; add-version after a timing change', 'Node, Chromium or '
                 'Playwright missing', 2)
        return
    cues = film / 'cues.json'
    tool('cue_list.py', 'codegen', str(cues))
    _write_lf(film / 'film.js', IMPORT_FILM.lstrip())
    c1, o1 = tool('film_check.py', str(film), '--size', '320x180')
    cl = _load('lf_fix231_clD', scripts / 'cue_list.py')
    before = cl.cue_timing_sha256(cues) if cues.is_file() else None

    def move_cue(t):
        doc = json.loads(cues.read_text(encoding='utf-8'))
        for ev in doc.get('events') or []:
            if ev.get('id') == 'land-hit':
                ev['t'] = t
                ev.pop('frame', None)
        _write_lf(cues, json.dumps(doc, indent=1))

    fr = _load('lf_fix231_render', scripts / 'film_render.py')
    real_part = fr.render_part
    moved = []

    def part_while_cue_moves(*a, **k):
        if not moved:
            move_cue(0.75)   # the cue moves while the render runs
            moved.append(True)
        return real_part(*a, **k)
    mp4 = Path(j('fix231_during', 'render.mp4'))
    fr.render_part = part_while_cue_moves
    argv = sys.argv
    sys.argv = ['film_render.py', str(film), '--cues', str(cues), '--size', '320x180', '--preview', '--force',
                '--out', str(mp4)]
    try:
        c2 = fr.main()
    except SystemExit as stop:
        c2 = stop.code
    finally:
        sys.argv = argv
        fr.render_part = real_part
    man = Path(str(mp4) + '.manifest.json')
    recorded = json.loads(man.read_text(encoding='utf-8')).get('cues_timing_sha256') if man.is_file() else None
    cb, ob = tool('project.py', 'add-version', j('fix231_during', 'proj_d'), '--cues', str(cues), '--file', str(mp4),
                  '--receipt', str(man))
    man_d = Path(j('fix231_during', 'proj_d', 'cuts', 'v001', 'manifest.json'))
    bind_d = (json.loads(man_d.read_text(encoding='utf-8')).get('identity') or {}).get('binding') if man_d.is_file() else None
    record('fixes231 D: a render receipt records the cue timing the render was given, so a cue moved during the '
           'render does not bind the render',
           c1 == 0 and c2 == 0 and bool(moved) and recorded == before and (cb != 0 or bind_d != 'receipt'),
           f'check={c1} render={c2} recorded timing is the one given: {recorded == before}; '
           f'add-version={cb}/{bind_d}: {ob.strip()[-160:]}')

    # L: the cue list changes after the render; with no receipt, the render is older than what it should show
    move_cue(1.0)
    cl_, ol = tool('project.py', 'add-version', j('fix231_during', 'proj_l'), '--cues', str(cues), '--file', str(mp4))
    man_l = Path(j('fix231_during', 'proj_l', 'cuts', 'v001', 'manifest.json'))
    bind_l = (json.loads(man_l.read_text(encoding='utf-8')).get('identity') or {}).get('binding') if man_l.is_file() else None
    record('fixes231 L: add-version without a receipt does not call a render "screened" when the cue list changed '
           'after it', c2 == 0 and bind_l != 'screened' and (cl_ != 0 or bind_l is not None),
           f'add-version={cl_}/{bind_l}: {ol.strip()[-160:]}')


# ------------------------------------------------------------------------------------------------ round 3 (M-S)

def _import_film(tool, j, scripts, name):
    """A kit film whose film.js imports ./times.gen.js, exported and checked: (film, cues, check exit, output), or
    None when Node, Chromium or Playwright is missing."""
    film = Path(j(name, 'film'))
    shutil.copytree(scripts.parent / 'assets' / 'kit', film)
    _write_lf(film / 'film.js', IMPORT_FILM.split('\n', 2)[2].replace("TIMES['land-hit'] ?? 0.25", '0.25'))
    c0, o0 = tool('film_check.py', str(film), '--size', '320x180')
    if c0 == 2 and ('needs node' in o0.lower() or 'playwright' in o0.lower() or 'missing' in o0.lower()):
        return None
    cues = film / 'cues.json'
    tool('cue_list.py', 'codegen', str(cues))
    _write_lf(film / 'film.js', IMPORT_FILM.lstrip())
    c1, o1 = tool('film_check.py', str(film), '--size', '320x180')
    return film, cues, c1, o1


def _move_land_hit(cues, t):
    doc = json.loads(Path(cues).read_text(encoding='utf-8'))
    for ev in doc.get('events') or []:
        if ev.get('id') == 'land-hit':
            ev['t'] = t
            ev.pop('frame', None)
    _write_lf(cues, json.dumps(doc, indent=1))


def _binding(project_dir):
    man = Path(project_dir, 'cuts', 'v001', 'manifest.json')
    return (json.loads(man.read_text(encoding='utf-8')).get('identity') or {}).get('binding') if man.is_file() else None


MOVE_DURING = """const fs = require('fs');
const [cues, src, out] = process.argv.slice(2);
const doc = JSON.parse(fs.readFileSync(cues, 'utf8'));
for (const ev of doc.events) if (ev.id === 'land-hit') { ev.t = 0.75; delete ev.frame; }
fs.writeFileSync(cues, JSON.stringify(doc, null, 1));
fs.copyFileSync(src, out);
console.log(out);
"""


def case_M(tool, record, j, scripts, skip=None):
    """M: add-version --render records the cue timing sampled before the render, and refuses one that moved during it."""
    ffmpeg, node = shutil.which('ffmpeg'), shutil.which('node')
    made = _import_film(tool, j, scripts, 'fix231_m') if ffmpeg and node else None
    if made is None:
        if skip:
            skip('fixes231 M: add-version --render with a cue moved during the render', 'Node, FFmpeg or Chromium missing')
        return
    film, cues, c1, o1 = made
    src = Path(j('fix231_m', 'engine.mp4'))
    _synth_video(ffmpeg, src, dur=2.0)
    script = Path(j('fix231_m', 'move_during.cjs'))
    _write_lf(script, MOVE_DURING)
    before = _load('lf_fix231_clM', scripts / 'cue_list.py').cue_timing_sha256(cues)
    saved = _bind_module_env()
    os.environ['LF_HEAVY_LOCK'] = j('fix231_m', 'heavy.lock')
    os.environ.pop('LF_HEAVY_LOCK_MARKER', None)
    try:
        code, text = tool('project.py', 'add-version', j('fix231_m', 'proj'), '--cues', str(cues),
                          '--file', j('fix231_m', 'out.mp4'), '--min-free-gib', '0', '--wait-min', '0.5',
                          '--render', f'"{node}" "{script}" "{cues}" "{src}" {{out}} {{page}}')
    finally:
        _restore_env(saved)
    receipt = Path(j('fix231_m', 'proj', 'cuts', 'v001', 'receipt.json'))
    recorded = json.loads(receipt.read_text(encoding='utf-8')).get('cues_timing_sha256') if receipt.is_file() else None
    record('fixes231 M: add-version --render refuses a render during which a cue moved, and never records the moved '
           'timing for it', c1 == 0 and code == 2 and 'during the render' in text and recorded in (None, before),
           f'check={c1} add-version={code}/{_binding(j("fix231_m", "proj"))} recorded the timing given: '
           f'{recorded in (None, before)}: {text.strip()[-200:]}')


def case_N(tool, record, j, scripts, skip=None):
    """N: add-version without a receipt compares the timing by content: a check run after the render does not make an
    unchanged render "older", and modules that do not hold the cue list's timing are never screened."""
    made = _import_film(tool, j, scripts, 'fix231_n')
    if made is None:
        if skip:
            skip('fixes231 N: add-version screened by content', 'Node, Chromium or Playwright missing', 2)
        return
    film, cues, c1, o1 = made
    mp4 = Path(j('fix231_n', 'render.mp4'))
    c2, o2 = tool('film_render.py', str(film), '--cues', str(cues), '--size', '320x180', '--preview', '--force',
                  '--out', str(mp4))
    modules = {n: (film / n).read_bytes() for n in ('times.gen.js', 'times.gen.ts')}
    c3, o3 = tool('film_check.py', str(film), '--size', '320x180')   # render, check, register: the usual order
    ca, oa = tool('project.py', 'add-version', j('fix231_n', 'proj_a'), '--cues', str(cues), '--file', str(mp4))
    bind_a = _binding(j('fix231_n', 'proj_a'))
    record('fixes231 N: a render checked again before it is registered (no receipt) is screened, not refused as older',
           c1 == 0 and c2 == 0 and c3 == 0 and bind_a == 'screened'
           and all((film / n).read_bytes() == b for n, b in modules.items()),
           f'check={c1} render={c2} check again={c3} add-version={ca}/{bind_a}: {oa.strip()[-160:]}')
    # the cue moves and the modules are not regenerated; a render made after that is newer than every file
    _move_land_hit(cues, 0.75)
    later = Path(j('fix231_n', 'later.mp4'))
    shutil.copyfile(mp4, later)
    ahead = max(p.stat().st_mtime for p in film.rglob('*') if p.is_file()) + 5
    os.utime(later, (ahead, ahead))
    cb, ob = tool('project.py', 'add-version', j('fix231_n', 'proj_b'), '--cues', str(cues), '--file', str(later))
    bind_b = _binding(j('fix231_n', 'proj_b'))
    record('fixes231 N: timing modules that do not hold the cue list\'s timing are not screened, however new the master',
           bind_b != 'screened' and cb != 0, f'add-version={cb}/{bind_b}: {ob.strip()[-160:]}')


def case_O(tool, record, j, scripts, skip=None):
    """O: a cue or section id "__proto__" is refused with a message: an object literal in times.gen.js loses it."""
    cl = _load('lf_fix231_clO', scripts / 'cue_list.py')
    node = shutil.which('node')
    d = Path(j('fix231_proto'))
    d.mkdir(parents=True, exist_ok=True)
    said = {}
    node_ok = True
    cue_gen_js = (scripts / 'cue_gen.cjs').resolve().as_posix()
    for label, doc in (('event', {'version': 2, 'fps': 24, 'events': [{'id': '__proto__', 't': 0.25, 'scale': 'contact'}]}),
                       ('section', {'version': 2, 'fps': 24, 'sections': [{'id': '__proto__', 'a': 0, 'b': 1.0,
                                                                            'clock': 'action'}],
                                    'events': [{'id': 'b', 't': 0.5, 'scale': 'contact',
                                               'section': '__proto__'}]})):
        cues = d / f'{label}.json'
        _write_lf(cues, json.dumps(doc))
        try:
            cl.compile_cue_constants(cues, out_ts=d / f'{label}.gen.ts', out_js=d / f'{label}.gen.js')
            said[label] = 'generated'
        except cl.CueListError as error:
            said[label] = 'refused: ' + str(error)[:120]
        said[label + ' list'] = '; '.join(cl.validate_v2(doc, 24)) or 'valid'
        if node:
            saved_res = dict(cl.RESERVED_IDS)
            cl.RESERVED_IDS.clear()
            try:
                legacy_js = d / f'{label}_230.gen.js'
                cl.compile_cue_constants(cues, out_ts=d / f'{label}_230.gen.ts', out_js=legacy_js)
            finally:
                cl.RESERVED_IDS.update(saved_res)
            r_n = subprocess.run([node, '-e', f'const g = require({json.dumps(cue_gen_js)}); '
                                              'const p = g.verifyGenerated(process.argv[1], process.argv[2]); '
                                              'if (p.length) { console.error(p.join("; ")); process.exit(2); }',
                                  str(cues), str(legacy_js)],
                                 capture_output=True, text=True, encoding='utf-8', errors='replace')
            n_out = r_n.stdout + r_n.stderr
            said[label + ' node'] = f'{r_n.returncode}:{n_out.strip()[:80]}'
            if r_n.returncode == 0 or '__proto__' not in n_out:
                node_ok = False
    record('fixes231 O: codegen, cue-list check and cue_gen.cjs refuse a cue or section id "__proto__", naming it, '
           'even against a 2.3.0-generated module',
           all(said[k].startswith('refused') and '__proto__' in said[k] for k in ('event', 'section'))
           and all('__proto__' in said[k] for k in ('event list', 'section list'))
           and node_ok, str(said)[:340])


def case_P(tool, record, j, scripts, skip=None):
    """P: --reads . or a drive root: the default alone/ folder is built from the resolved path, and a root that has
    no folder beside it is refused in words for that case."""
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        if skip:
            skip('fixes231 P: --reads . and a drive root', 'FFmpeg missing', 2)
        return
    pack = _load('lf_fix231_packP', scripts / 'pack.py')
    base = Path(j('fix231_dot'))
    film, ref = base / 'film.mp4', base / 'ref.mp4'
    base.mkdir(parents=True, exist_ok=True)
    _synth_video(ffmpeg, film, dur=2.0)
    _synth_video(ffmpeg, ref, freq=554, color='0x241935', color2='0xc77dff', dur=2.0)
    readers = base / 'readers'
    readers.mkdir()
    here = os.getcwd()
    os.chdir(readers)
    try:
        key = pack.make_pack(film, [ref], base / 'keys', reads_root='.')
        dot = Path(key['alone']['dir']).resolve()
        dot_state = 'made'
    except ValueError as error:
        dot, dot_state = None, 'refused: ' + str(error)[:120]
    finally:
        os.chdir(here)
    want = (base / 'readers-alone').resolve()
    record('fixes231 P: with --reads ., alone/ goes beside the readers\' folder, not inside it',
           dot is not None and want in dot.parents and readers.resolve() not in dot.parents,
           f'{dot_state}; alone at {dot}')
    anchor = Path(base.resolve().anchor)
    try:
        pack.make_pack(film, [ref], base / 'keys-root', reads_root=anchor)
        root_state = 'accepted'
    except ValueError as error:
        root_state = str(error)
    expect_root = 'drive root' if anchor.drive else 'filesystem root'
    record('fixes231 P: --reads at a root is refused for having no folder beside it, without naming an '
           '--alone-reads that was not given',
           root_state != 'accepted' and '--alone-reads ' + str(anchor) not in root_state
           and expect_root in root_state and (bool(anchor.drive) or '--alone-reads' not in root_state)
           and not (anchor / '-alone').exists(), root_state[:200])


def case_Q(tool, record, j, scripts, skip=None):
    """Q: a world sheet copied alone into another film, or a project's sheet copied into another folder, does not pass
    for those films; a film moved with its own sheet still does."""
    kit_src = scripts.parent / 'assets' / 'kit'
    # the project-identity guard alone: a project's sheet drawn while its status.json states no title (so its title
    # and world line are defaults) copied into a film folder that is not a project. Every comparison then agrees
    # (no title stated there either), so only the guard keeps it from counting there.
    ws = _load('lf_fix231_wsQ', scripts / 'world_spec.py')
    bare = Path(j('fix231_copy', 'bare_project'))
    tool('project.py', 'init', str(bare))
    status = json.loads((bare / 'status.json').read_text(encoding='utf-8'))
    status.pop('title', None)
    _write_lf(bare / 'status.json', json.dumps(status, indent=1))
    c_bare, o_bare = tool('look.py', 'world-sheet', str(bare))
    if c_bare == 0:
        loose_film = Path(j('fix231_copy', 'not_a_project', 'film'))
        _sheet_film(kit_src, loose_film)
        _copy_sheet(bare / 'refs', loose_film / 'qa')
        bare_meta = json.loads((loose_film / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
        own_verdict = ws.sheet_owner(bare / 'refs' / 'world-sheet.png', bare_meta, bare / 'film', None)[0]
        copy_verdict = ws.sheet_owner(loose_film / 'qa' / 'world-sheet.png', bare_meta, loose_film, None)[0]
        record('fixes231 Q: a project\'s sheet drawn with no status title, copied into a film folder that is not a '
               'project, does not count there (only the project-identity guard refuses it), while it counts in its '
               'own project', own_verdict == 'own' and copy_verdict == 'other'
               and (bare_meta.get('sources') or {}).get('title') == 'default' and bare_meta.get('project_title') is None,
               f'own={own_verdict} copy={copy_verdict} sources={bare_meta.get("sources")}')
    elif skip:
        skip('fixes231 Q: the project-identity guard alone', f'look.py world-sheet could not draw: {o_bare.strip()[-80:]}')
    first = Path(j('fix231_copy', 'first'))
    _gated_film(kit_src, first)
    tool('look.py', 'world-sheet', str(first))
    c_first, o_first = tool('film_check.py', str(first), '--size', '640x360')
    if c_first == 2 and ('needs node' in o_first.lower() or 'playwright' in o_first.lower() or 'missing' in o_first.lower()):
        if skip:
            skip('fixes231 Q: copied world sheets', 'Node, Chromium or Playwright missing', 3)
        return
    second = Path(j('fix231_copy', 'second'))
    _gated_film(kit_src, second)
    _write_lf(second / 'film.js', GOOD_FILM.lstrip().replace("'Gate Film'", "'Second Film'")
              .replace("what: 'proof'", "what: 'another proof'"))
    (second / 'qa').mkdir(exist_ok=True)
    for ext in ('.png', '.json'):
        shutil.copyfile(first / 'qa' / f'world-sheet{ext}', second / 'qa' / f'world-sheet{ext}')
    c_sec, o_sec = tool('film_check.py', str(second), '--size', '640x360')
    record('fixes231 Q: a film\'s world sheet copied alone into another film\'s qa/ does not pass for that film',
           c_first == 0 and c_sec == 1 and 'world sheet' in o_sec,
           f'own sheet exit {c_first}; copied sheet exit {c_sec}: {o_sec.strip()[-200:]}')
    # a project's sheet, and a standalone film in a folder that is not that project
    proj = Path(j('fix231_copy', 'project'))
    tool('project.py', 'init', str(proj), '--title', 'Sheet Project')
    inside = proj / 'film'
    _gated_film(kit_src, inside)
    tool('look.py', 'world-sheet', str(proj))
    c_in, o_in = tool('film_check.py', str(inside), '--size', '640x360')
    elsewhere = Path(j('fix231_copy', 'elsewhere', 'Sheet Project'))
    (elsewhere / 'refs').mkdir(parents=True)
    for ext in ('.png', '.json'):
        shutil.copyfile(proj / 'refs' / f'world-sheet{ext}', elsewhere / 'refs' / f'world-sheet{ext}')
    loose = elsewhere / 'film'
    _gated_film(kit_src, loose)
    c_out, o_out = tool('film_check.py', str(loose), '--size', '640x360')
    # Also copy the project sheet (kind='project', target_rel='..') into a standalone kit film's qa/ whose title and
    # folder name match 'Sheet Project', so only sheet_owner's find_project(target) == target check blocks it.
    impostor = Path(j('fix231_copy', 'impostor', 'Sheet Project'))
    _gated_film(kit_src, impostor)
    _write_lf(impostor / 'film.js', GOOD_FILM.lstrip().replace("'Gate Film'", "'Sheet Project'"))
    (impostor / 'qa').mkdir(exist_ok=True)
    for ext in ('.png', '.json'):
        shutil.copyfile(proj / 'refs' / f'world-sheet{ext}', impostor / 'qa' / f'world-sheet{ext}')
    c_imp, o_imp = tool('film_check.py', str(impostor), '--size', '640x360')
    record('fixes231 Q: a project\'s world sheet passes the films in that project, and a copy of it in a non-project '
           'folder (even of the same name and title) passes none of the films there',
           c_in == 0 and c_out == 1 and c_imp == 1 and 'world sheet' in o_out and 'world sheet' in o_imp,
           f'in project={c_in}; non-project refs={c_out}; non-project qa={c_imp}: {o_imp.strip()[-160:]}')


PROBE_TS = """import os, subprocess, sys
page = sys.argv[1]
ts = os.path.join(page, 'times.gen.ts')
text = open(ts, encoding='utf-8').read()
open(ts, 'w', encoding='utf-8', newline='\\n').write(text.replace('"t": 0.25', '"t": 0.75'))
sys.exit(subprocess.run([sys.argv[2], '-e', 'process.exit(0)']).returncode)
"""


def case_R(tool, record, j, scripts, skip=None):
    """R: film_render.py stages the timing modules from where add-version takes them (beside an external cue list),
    and the render preload checks every staged module, not the first."""
    node = shutil.which('node')
    made = _import_film(tool, j, scripts, 'fix231_r') if node else None
    if made is None:
        if skip:
            skip('fixes231 R: timing modules beside an external cue list; every staged module checked',
                 'Node, Chromium or Playwright missing', 2)
        return
    film, cues, c1, o1 = made
    outside = Path(j('fix231_r', 'list'))
    outside.mkdir()
    doc = json.loads(cues.read_text(encoding='utf-8'))
    doc['picture']['path'] = '../film/'
    _write_lf(outside / 'cues.json', json.dumps(doc, indent=1))
    for n in ('times.gen.js', 'times.gen.ts'):
        shutil.move(str(film / n), str(outside / n))
    cues.unlink()
    mp4 = Path(j('fix231_r', 'render.mp4'))
    c2, o2 = tool('film_render.py', str(film), '--cues', str(outside / 'cues.json'), '--size', '320x180', '--preview',
                  '--force', '--out', str(mp4))
    man = Path(str(mp4) + '.manifest.json')
    generated = json.loads(man.read_text(encoding='utf-8')).get('generated') if man.is_file() else None
    want = {n: _sha(outside / n) for n in ('times.gen.js', 'times.gen.ts')}
    record('fixes231 R: film_render.py renders, checks and records the timing modules beside an external cue list',
           c1 == 0 and c2 == 0 and generated == want, f'check={c1} render={c2} generated={generated}: {o2.strip()[-200:]}')

    # the staged times.gen.ts changes after the Python check: the preload, given only times.gen.js, had let it through
    proj = _load('lf_fix231_projR', scripts / 'project.py')
    cl = _load('lf_fix231_clR', scripts / 'cue_list.py')
    page = Path(j('fix231_r', 'page'))
    page.mkdir()
    _write_lf(page / 'index.html', '<!doctype html><title>t</title>\n')
    _write_lf(page / 'cues.json', json.dumps({'version': 2, 'fps': 24, 'events': [{'id': 'hit', 't': 0.25}]}))
    cl.compile_cue_constants(page / 'cues.json')
    probe = Path(j('fix231_r', 'probe_ts.py'))
    _write_lf(probe, PROBE_TS)
    saved = _bind_module_env()
    os.environ['LF_HEAVY_LOCK'] = j('fix231_r', 'heavy.lock')
    os.environ.pop('LF_HEAVY_LOCK_MARKER', None)
    try:
        ran = proj.run_render(f'"{sys.executable}" "{probe}" {{page}} "{node}" {{out}}', page,
                              Path(j('fix231_r', 'out.mp4')), 0, 0.05, cues_file=page / 'cues.json', page_dir=page)
        state = f"exit {ran['returncode']}: {ran['output'].strip()[-160:]}"
        caught = ran['returncode'] != 0 and 'times.gen.ts' in ran['output']
    except proj.Refused as error:
        state, caught = 'refused: ' + str(error)[:160], False
    finally:
        _restore_env(saved)
    record('fixes231 R: the render preload checks every staged timing module, so a staged times.gen.ts that changed '
           'after the Python check stops the engine', caught, state)


# ------------------------------------------------------------------------------------------------ round 4 (S-U)

SHEET_BASE = GOOD_FILM.lstrip().replace(
    "    frame: { what: 'proof', audience: 'editors', why: 'clarity', knows_by: '2s' },\n", "    brand: '#2F9E6B',\n")


def _no_browser(code, text):
    return code == 2 and ('needs node' in text.lower() or 'playwright' in text.lower() or 'missing' in text.lower())


def _sheet_film(kit_src, folder, js=SHEET_BASE):
    shutil.copytree(kit_src, folder)
    _write_lf(folder / 'film.js', js)
    _write_lf(folder / 'gates.json', '{"world_sheet": "required", "typography": "required"}\n')


def _page_only(kit_src, folder, title):
    """A gated page with no film.js: index.html (titled TITLE) loads its spec (titled TITLE) from spec.js."""
    _sheet_film(kit_src, folder, GOOD_FILM.lstrip().replace("'Gate Film'", repr(title)))
    os.replace(folder / 'film.js', folder / 'spec.js')
    main = folder / 'lf' / 'main.js'
    _write_lf(main, main.read_text(encoding='utf-8').replace("q.get('film') || 'film.js'", "q.get('film') || 'spec.js'"))
    index = folder / 'index.html'
    _write_lf(index, index.read_text(encoding='utf-8').replace('<title>Legible Film kit</title>', f'<title>{title}</title>'))


def _copy_sheet(src_dir, dst_dir):
    dst_dir.mkdir(parents=True, exist_ok=True)
    for ext in ('.png', '.json'):
        shutil.copyfile(src_dir / f'world-sheet{ext}', dst_dir / f'world-sheet{ext}')


def case_S(tool, record, j, scripts, skip=None):
    """S: a world sheet counts for a film when drawing it for that film now, with the options it was drawn with, draws
    the same values. A hash of text read from the film's files had passed another project's sheet (every project
    hashed to nulls) and sheets of films whose titles it could not read, and failed a film's own sheet after harmless
    edits."""
    kit_src = scripts.parent / 'assets' / 'kit'
    check = lambda film: tool('film_check.py', str(film), '--size', '640x360')   # noqa: E731

    # projects Alpha and Beta, in folders of the same name: Alpha's sheet copied into Beta's refs/
    films = {}
    for name, title in (('alpha', 'Alpha'), ('beta', 'Beta')):
        proj = Path(j('fix231_values', name, 'project'))
        tool('project.py', 'init', str(proj), '--title', title)
        _sheet_film(kit_src, proj / 'film', GOOD_FILM.lstrip())
        films[name] = proj
    tool('look.py', 'world-sheet', str(films['alpha']))
    c_a, o_a = check(films['alpha'] / 'film')
    if _no_browser(c_a, o_a):
        if skip:
            skip('fixes231 S: world sheets judged by the values they draw', 'Node, Chromium or Playwright missing', 9)
        return
    _copy_sheet(films['alpha'] / 'refs', films['beta'] / 'refs')
    c_b, o_b = check(films['beta'] / 'film')
    record('fixes231 S: project Alpha\'s world sheet copied into project Beta does not pass Beta\'s film',
           c_a == 0 and c_b == 1 and 'world sheet' in o_b,
           f'Alpha exit {c_a}; Beta with Alpha\'s sheet exit {c_b}: {o_b.strip()[-200:]}')
    record('fixes231 S: the refusal says the sheet was drawn for another film or from other values, naming them',
           c_b == 1 and 'drawn for another film' in o_b and "'Alpha'" in o_b and "'Beta'" in o_b
           and "this film's" not in o_b, o_b.strip()[-260:])

    # films whose titles the hint reader could not read: constants, template literals, index.html-only pages, each
    # pair in folders of the same name
    pairs = {
        'constant': lambda title: "const TITLE = '%s';\n" % title + GOOD_FILM.lstrip().replace("title: 'Gate Film'",
                                                                                                'title: TITLE'),
        'template literal': lambda title: GOOD_FILM.lstrip().replace("title: 'Gate Film'", 'title: `%s`' % title),
        'index.html only': None,
    }
    outcome = {}
    for label, js in pairs.items():
        made = []
        for side, title in (('a', 'Alpha Film'), ('b', 'Beta Film')):
            film = Path(j('fix231_values', label.replace(' ', '_').replace('.', '_') + '_' + side, 'film'))
            if js is None:
                _page_only(kit_src, film, title)
            else:
                _sheet_film(kit_src, film, js(title))
            made.append(film)
        tool('look.py', 'world-sheet', str(made[0]))
        c_own, o_own = check(made[0])
        _copy_sheet(made[0] / 'qa', made[1] / 'qa')
        c_cp, o_cp = check(made[1])
        outcome[label] = (c_own, c_cp, o_cp.strip()[-160:])
        record(f'fixes231 S: a world sheet passes its own film and not another whose title is set by a {label}'
               if label != 'index.html only' else
               'fixes231 S: a world sheet passes its own index.html-only page and not another titled otherwise',
               c_own == 0 and c_cp == 1 and 'Alpha Film' in o_cp,
               f'own exit {c_own}; copied exit {c_cp}: {o_cp.strip()[-200:]} | {o_own.strip()[-120:] if c_own else ""}')

    # harmless edits keep a film's own sheet
    base = Path(j('fix231_values', 'harmless', 'base'))
    _sheet_film(kit_src, base)
    tool('look.py', 'world-sheet', str(base))
    edits = {
        'the brand colour written in lower case': lambda f: _write_lf(
            f / 'film.js', (f / 'film.js').read_text(encoding='utf-8').replace("'#2F9E6B'", "'#2f9e6b'")),
        'frame: { what } added, as film_check.py suggests': lambda f: _write_lf(
            f / 'film.js', (f / 'film.js').read_text(encoding='utf-8').replace(
                "    brand: '#2F9E6B',\n", "    brand: '#2F9E6B',\n    frame: { what: 'proof', audience: 'editors', "
                                          "why: 'clarity', knows_by: '2s' },\n")),
        'the title in backticks': lambda f: _write_lf(
            f / 'film.js', (f / 'film.js').read_text(encoding='utf-8').replace("title: 'Gate Film'", 'title: `Gate Film`')),
        'a "- Tone:" line in treatment.md': lambda f: _write_lf(f / 'treatment.md', '# Treatment\n\n- Tone: calm, exact\n'),
        'a comment holding what: and title:': lambda f: _write_lf(
            f / 'film.js', "// what: 'draft' title: 'Draft cut'\n" + (f / 'film.js').read_text(encoding='utf-8')),
    }
    for i, (label, edit) in enumerate(edits.items()):
        film = Path(j('fix231_values', 'harmless', f'edit{i}'))
        shutil.copytree(base, film)
        edit(film)
        c_e, o_e = check(film)
        record(f'fixes231 S: a film keeps its own world sheet after {label}', c_e == 0,
               f'exit {c_e}: {o_e.strip()[-200:]}')

    # a sheet drawn with overrides passes its own film (and a moved copy of it), while changing the film's own stated
    # brand or world line invalidates the sheet
    over = Path(j('fix231_values', 'override', 'film'))
    _sheet_film(kit_src, over)
    tool('look.py', 'world-sheet', str(over), '--world-line', 'proof x printing press', '--brand', '#C0392B')
    c_o, o_o = check(over)
    over_moved = Path(j('fix231_values', 'override_moved', 'renamed'))
    shutil.copytree(over, over_moved)
    c_om, o_om = check(over_moved)
    meta = json.loads((over / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
    record('fixes231 S: a sheet drawn with --world-line and --brand records them and passes its own film before and '
           'after moving', c_o == 0 and c_om == 0 and (meta.get('options') or {}).get('brand') == '#C0392B',
           f'own={c_o} moved={c_om}; options={meta.get("options")}: {o_o.strip()[-160:]}')


NO_IMAGING = """import runpy, sys
sys.modules['numpy'] = None
sys.modules['PIL'] = None
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""


def case_T(tool, record, j, scripts, skip=None):
    """T: film_check.py judges a world sheet's owner without numpy or Pillow (look.py exits 2 without them)."""
    film = Path(j('fix231_noimaging', 'film'))
    _sheet_film(scripts.parent / 'assets' / 'kit', film)
    tool('look.py', 'world-sheet', str(film))

    def bare(*args):
        r = subprocess.run([sys.executable, '-I', '-c', NO_IMAGING, *map(str, args)], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        return r.returncode, r.stdout + r.stderr
    c_look, _ = bare(scripts / 'look.py', 'world-sheet', str(film), '--out', j('fix231_noimaging', 'x.png'))
    c_chk, o_chk = bare(scripts / 'film_check.py', str(film), '--size', '640x360')
    if _no_browser(c_chk, o_chk) and 'numpy' not in o_chk.lower() and 'pillow' not in o_chk.lower():
        if skip:
            skip('fixes231 T: film_check.py without numpy or Pillow', 'Node, Chromium or Playwright missing')
        return
    record('fixes231 T: film_check.py passes a film\'s own world sheet with numpy and Pillow unavailable',
           c_look == 2 and c_chk == 0, f'look.py without them exit {c_look}; film_check.py exit {c_chk}: '
           f'{o_chk.strip()[-200:]}')


def case_U(tool, record, j, scripts, skip=None):
    """U: add-version with no receipt and no timing modules anywhere registers the render "unverified", naming the
    missing link: nothing ties it to the cue list's timing, so a cue edited after the render had been "screened"."""
    ffmpeg = shutil.which('ffmpeg')
    film = Path(j('fix231_nomodules', 'film'))
    shutil.copytree(scripts.parent / 'assets' / 'kit', film)
    _write_lf(film / 'film.js', IMPORT_FILM.split('\n', 2)[2].replace("TIMES['land-hit'] ?? 0.25", '0.25'))
    c0, o0 = tool('film_check.py', str(film), '--size', '320x180') if ffmpeg else (2, 'ffmpeg missing')
    if _no_browser(c0, o0):
        if skip:
            skip('fixes231 U: add-version with no receipt and no timing modules', 'Node, FFmpeg or Chromium missing', 2)
        return
    for name in ('times.gen.js', 'times.gen.ts'):
        if (film / name).is_file():
            (film / name).unlink()
    cues = film / 'cues.json'
    mp4 = Path(j('fix231_nomodules', 'render.mp4'))
    _synth_video(ffmpeg, mp4, dur=2.0)
    ahead = max(p.stat().st_mtime for p in film.rglob('*') if p.is_file()) + 5
    os.utime(mp4, (ahead, ahead))
    raw = cues.read_bytes()

    def register(name):
        code, text = tool('project.py', 'add-version', j('fix231_nomodules', name), '--cues', str(cues), '--file',
                          str(mp4))
        man = Path(j('fix231_nomodules', name, 'cuts', 'v001', 'manifest.json'))
        ident = (json.loads(man.read_text(encoding='utf-8')).get('identity') or {}) if man.is_file() else {}
        return code, text, ident.get('binding'), ' '.join(ident.get('binding_reasons') or [])

    _move_land_hit(cues, 0.75)   # the cue is edited after the render
    c1, o1, b1, r1 = register('proj_edited')
    record('fixes231 U: with no timing modules and no receipt, a render whose cue was edited after it is registered '
           '"unverified" (exit 1), naming the missing link', c0 == 0 and c1 == 1 and b1 == 'unverified' and 'times.gen' in r1,
           f'check={c0} add-version={c1}/{b1}: {r1[:200]} {o1.strip()[-120:]}')
    _write_lf(cues, raw.decode('utf-8'))   # the same list, rewritten: newer than the master, content unchanged
    os.utime(cues, (ahead + 10, ahead + 10))
    c2, o2, b2, r2 = register('proj_rewritten')
    record('fixes231 U: a cue list whose bytes were only rewritten after the render is not refused as newer; the '
           'render is registered "unverified" (exit 1, not 2)', c2 == 1 and b2 == 'unverified', f'add-version={c2}/{b2}: {o2.strip()[-160:]}')


# ------------------------------------------------------------------------------------------------ release gate (V-AA)

def case_V(tool, record, j, scripts, skip=None):
    """V: world sheets are looked for only in the film's qa/ and its enclosing project's refs/ (at any depth), found
    by target_rel, keep an untitled film or project valid when it is moved, accept UTF-8 BOMs, and keep a 2.3.0
    record's absolute-path rule; a cross-drive record (drawn, no target_rel) is still checked."""
    kit_src = scripts.parent / 'assets' / 'kit'
    ws_mod = _load('lf_fix231_wsV', scripts / 'world_spec.py')
    check = lambda f: tool('film_check.py', str(f), '--size', '640x360')   # noqa: E731
    nf_a = Path(j('fix231_v', 'nf_a'))
    _sheet_film(kit_src, nf_a)
    tool('look.py', 'world-sheet', str(nf_a))
    c_nfa, o_nfa = check(nf_a)
    if _no_browser(c_nfa, o_nfa):
        if skip:
            skip('fixes231 V: world-sheet location, deep project pages and UTF-8 BOM',
                 'Node, Chromium or Playwright missing', 5)
        return

    # 2. Gate A #4a: nested project page 3 levels deep finds project refs/world-sheet.png; non-project ancestor does not.
    deep = Path(j('fix231_v', 'deep_proj'))
    tool('project.py', 'init', str(deep), '--title', 'Deep Project', '--path', 'create', '--timeline', 'page',
         '--page', 'src/films/launch')
    deep_page = deep / 'src' / 'films' / 'launch'
    _sheet_film(kit_src, deep_page)
    c_dws, _ = tool('look.py', 'world-sheet', str(deep_page))
    c_dchk, o_dchk = check(deep_page)
    plain = Path(j('fix231_v', 'plain_above'))
    plain_page = plain / 'src' / 'films' / 'launch'
    _sheet_film(kit_src, plain_page)
    _copy_sheet(deep / 'refs', plain / 'refs')
    c_pchk, o_pchk = check(plain_page)
    record('fixes231 V: a project page nested three folders deep finds its project\'s refs/world-sheet.png, while a '
           'non-project folder above a film is ignored',
           c_dws == 0 and (deep / 'refs' / 'world-sheet.png').is_file() and c_dchk == 0 and c_pchk == 1,
           f'deep_ws={c_dws} deep_check={c_dchk} non_project_above={c_pchk}: {o_dchk.strip()[-140:]}')

    # 3. A project started without --title (its status.json title is its folder's name) keeps its sheet when the
    #    project is moved or renamed, and a sheet drawn before film/ exists still passes once it does.
    ua = Path(j('fix231_v', 'empty_a', 'project'))
    tool('project.py', 'init', str(ua))
    _sheet_film(kit_src, ua / 'film', SHEET_BASE.replace("'Gate Film'", "'Alpha'"))
    tool('look.py', 'world-sheet', str(ua))
    c_ua, _ = check(ua / 'film')
    ua_moved = Path(j('fix231_v', 'moved_untitled_proj'))
    shutil.copytree(ua, ua_moved)
    c_umv, o_umv = check(ua_moved / 'film')
    early = Path(j('fix231_v', 'early_proj'))
    tool('project.py', 'init', str(early))
    tool('look.py', 'world-sheet', str(early))
    _sheet_film(kit_src, early / 'film')
    c_early, o_early = check(early / 'film')
    record('fixes231 V: a project started without --title keeps its sheet when moved, and a sheet drawn before film/ '
           'was added passes once it is',
           c_ua == 0 and c_umv == 0 and c_early == 0,
           f'own={c_ua} moved={c_umv} early={c_early}: {(o_umv if c_umv else o_early).strip()[-160:]}')

    # 4. Gate A #4c: UTF-8 BOM on status.json, gates.json, world-sheet.json, film.js and treatment.md.
    bom_a = Path(j('fix231_v', 'bom_a'))
    bom_b = Path(j('fix231_v', 'bom_b'))
    tool('project.py', 'init', str(bom_a), '--title', 'Alpha BOM')
    tool('project.py', 'init', str(bom_b), '--title', 'Beta BOM')
    _sheet_film(kit_src, bom_a / 'film')
    _sheet_film(kit_src, bom_b / 'film')
    _write_lf(bom_a / 'treatment.md', '# Treatment\n- World line: brass x prism\n')
    tool('look.py', 'world-sheet', str(bom_a))
    for p in (bom_a / 'status.json', bom_a / 'treatment.md', bom_a / 'refs' / 'world-sheet.json',
              bom_a / 'film' / 'gates.json', bom_a / 'film' / 'film.js',
              bom_b / 'status.json', bom_b / 'film' / 'gates.json'):
        raw = p.read_bytes()
        if not raw.startswith(b'\xef\xbb\xbf'):
            p.write_bytes(b'\xef\xbb\xbf' + raw)
    c_boma, o_boma = check(bom_a / 'film')
    _copy_sheet(bom_a / 'refs', bom_b / 'refs')
    c_bomb, o_bomb = check(bom_b / 'film')
    record('fixes231 V: UTF-8 BOM on status.json, gates.json, world-sheet.json, film.js and treatment.md passes own '
           'project and still refuses another BOM project',
           c_boma == 0 and c_bomb == 1 and 'Alpha BOM' in o_bomb,
           f'bom_own={c_boma} bom_other={c_bomb}: {(o_boma if c_boma else o_bomb).strip()[-180:]}')

    # 5. Cross-drive --out (target_rel=None with drawn) is not mistaken for a 2.3.0 record; 2.3.0 record keeps its rule.
    xd = Path(j('fix231_v', 'xdrive'))
    _sheet_film(kit_src, xd)
    tool('look.py', 'world-sheet', str(xd))
    xd_json = xd / 'qa' / 'world-sheet.json'
    xd_meta = json.loads(xd_json.read_text(encoding='utf-8'))
    xd_meta['target_rel'] = None   # as written when --out was on another drive
    _write_lf(xd_json, json.dumps(xd_meta, indent=1))
    v_same, _ = ws_mod.sheet_owner(xd / 'qa' / 'world-sheet.png', xd_meta, xd, 'Gate Film')
    _write_lf(xd / 'film.js', SHEET_BASE.replace("'Gate Film'", "'Retitled Film'"))
    v_retitled, _ = ws_mod.sheet_owner(xd / 'qa' / 'world-sheet.png', xd_meta, xd, 'Retitled Film')
    c_xd, o_xd = check(xd)
    # Genuine 2.3.0 record (no target_rel, no drawn): passes at its target even after retitling, fails elsewhere.
    rec_230 = {'tool': 'look.py world-sheet', 'target': str(xd.resolve()), 'kind': 'kit', 'pass': True}
    v_230_own, _ = ws_mod.sheet_owner(xd / 'qa' / 'world-sheet.png', rec_230, xd, 'Retitled Film')
    v_230_other, _ = ws_mod.sheet_owner(nf_a / 'qa' / 'world-sheet.png', rec_230, nf_a, 'Gate Film')
    record('fixes231 V: a cross-drive sheet record (target_rel=None with drawn) still checks staleness when retitled, '
           'while a 2.3.0 record keeps its absolute-path check',
           v_same == 'own' and v_retitled == 'values' and c_xd == 1 and v_230_own == 'own' and v_230_other == 'other',
           f'xdrive_same={v_same} xdrive_retitled={v_retitled} check={c_xd} 230_own={v_230_own} 230_other={v_230_other}')

    # 6. Untitled kit film moved/renamed keeps its sheet; adding a title afterwards invalidates it.
    untitled_js = SHEET_BASE.replace("title: 'Gate Film', ", '')
    ut = Path(j('fix231_v', 'untitled_alpha'))
    _sheet_film(kit_src, ut, untitled_js)
    tool('look.py', 'world-sheet', str(ut))
    ut_moved = Path(j('fix231_v', 'untitled_moved'))
    shutil.copytree(ut, ut_moved)
    c_utm, o_utm = check(ut_moved)
    _write_lf(ut_moved / 'film.js', SHEET_BASE.replace("'Gate Film'", "'Added Title'"))
    c_utr, o_utr = check(ut_moved)
    record('fixes231 V: an untitled kit film renamed to another folder keeps its world sheet until a title is added',
           c_utm == 0 and c_utr == 1 and 'Added Title' in o_utr,
           f'moved={c_utm} retitled={c_utr}: {(o_utm if c_utm else o_utr).strip()[-180:]}')


def case_W(tool, record, j, scripts, skip=None):
    """W: world_spec.film_spec_values, which only chooses what a sheet draws when --title or --brand is not given,
    returns text or None and never raises, on any input; it still reads the kit's own films."""
    ws = _load('lf_fix231_wsW', scripts / 'world_spec.py')
    kit_films = scripts.parent / 'assets' / 'kit' / 'films'
    inputs = {name: 'export default function film(){' + body + '}' for name, (body, _) in REVIEW_FORMS.items()}
    inputs.update({
        'call': "export default () => ({ title: getTitle(), brand: getBrand(), scenes: [] });",
        'cycle': "const A = `${B}`, B = `${A}`; export default () => ({ title: A, scenes: [] });",
        'empty': '', 'unclosed template': 'const x = `unclosed ${', 'unclosed string': "return { title: 'open",
        'nested parentheses': '(' * 10000 + ')' * 10000, 'lone braces': '}}}{{{', 'binary': bytes(range(256)).decode('latin-1'),
        'not text': None, 'bytes': b"return {title:'x',scenes:[]}", 'number': 42,
    })
    bad = []
    for label, src in inputs.items():
        try:
            got = ws.film_spec_values(src)
            if set(got) != {'title', 'brand'} or not all(v is None or isinstance(v, str) for v in got.values()):
                bad.append(f'{label} returned {got!r}')
        except Exception as error:   # noqa: BLE001
            bad.append(f'{label} raised {error!r}')
    kit = {name: ws.film_spec_values((kit_films / name / 'film.js').read_text(encoding='utf-8'))
           for name in ('starter', 'atlasfold')}
    record('fixes231 W: the film.js reader returns text or None without raising on the review forms and on '
           'malformed, binary or non-text input, and reads the kit films',
           not bad and kit['starter'] == {'title': 'Northwind (starter)', 'brand': '#2F9E6B'}
           and kit['atlasfold'] == {'title': 'Atlasfold 1.0', 'brand': '#3D7BFF'},
           '; '.join(bad) or f'{len(inputs)} inputs; kit={kit}')

    # the documents say what the check is: a guard against the usual accident, not proof of which film a sheet was
    # drawn for (it had been described as telling you "the sheet was drawn for this film")
    skill = scripts.parent
    texts = {'world_spec.py': ws.__doc__ or '', 'look.md': (skill / 'references' / 'look.md').read_text(encoding='utf-8')}
    changelog = skill.parent.parent / 'CHANGELOG.md'
    if changelog.is_file():
        texts['CHANGELOG.md'] = changelog.read_text(encoding='utf-8')
    flat = {name: ' '.join(text.split()) for name, text in texts.items()}
    wrong_words = [name for name, text in flat.items()
                   if 'was drawn for this film' in text or 'guard against the usual accident' not in text
                   or 'not a proof of which film a sheet was drawn for' not in text]
    record('fixes231 W: the world-sheet documents call the check a guard against the usual accident, not proof of '
           'which film a sheet was drawn for', not wrong_words, f'checked {sorted(flat)}; wrong: {wrong_words}')


def case_X(tool, record, j, scripts, skip=None):
    """X: film_check.py reads UTF-8 page output and prints non-ASCII titles cleanly without PYTHONUTF8."""
    kit_src = scripts.parent / 'assets' / 'kit'
    title = 'Árbol “日本語” Launch'
    film = Path(j('fix231_utf8', 'film with spaces'))
    _sheet_film(kit_src, film, SHEET_BASE.replace("'Gate Film'", repr(title)))
    c_ws, o_ws = tool('look.py', 'world-sheet', str(film))
    env = dict(os.environ, LC_ALL='C', PYTHONCOERCECLOCALE='0')
    env.pop('PYTHONUTF8', None)
    env.pop('PYTHONIOENCODING', None)

    def run_check(*extra):
        r = subprocess.run([sys.executable, '-I', str(scripts / 'film_check.py'), str(film), '--size', '640x360',
                            *extra], capture_output=True, env=env)
        return r.returncode, (r.stdout + r.stderr).decode('utf-8', errors='replace')

    c_cap, o_cap = run_check()
    if _no_browser(c_cap, o_cap):
        if skip:
            skip('fixes231 X: non-ASCII film_check.py', 'Node, Chromium or Playwright missing', 2)
        return
    record('fixes231 X: film_check.py checks and prints a non-ASCII film title without PYTHONUTF8',
           c_ws == 0 and c_cap == 0 and title in o_cap and 'Traceback' not in o_cap,
           f'ws={c_ws} check={c_cap}: {o_cap.strip()[-220:]}')

    # Other side: a non-ASCII film with a 4-word serif violation still fails preflight cleanly (exit 1, no traceback).
    bad = Path(j('fix231_utf8', 'bad_serif'))
    _sheet_film(kit_src, bad, SHEET_BASE.replace("'Gate Film'", repr(title)).replace(
        "'Let it stand.'", "'Cuatro palabras en serif'"))
    tool('look.py', 'world-sheet', str(bad))
    r_bad = subprocess.run([sys.executable, '-I', str(scripts / 'film_check.py'), str(bad), '--size', '640x360'],
                           capture_output=True, env=env)
    o_bad = (r_bad.stdout + r_bad.stderr).decode('utf-8', errors='replace')
    record('fixes231 X: a non-ASCII film breaking the serif rule exits 1 cleanly without a traceback',
           r_bad.returncode == 1 and 'serif' in o_bad and 'Traceback' not in o_bad,
           f'exit={r_bad.returncode}: {o_bad.strip()[-200:]}')


def case_Y(tool, record, j, scripts, skip=None):
    """Y: pack.py record rejects boolean scores and names the accepted vendors; POSIX / root gives actionable advice;
    check.py --verify hashes pack.py. (Its Markdown and alternative-JSON readings went with the Markdown reader: AC.)"""
    from pathlib import PurePosixPath
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        if skip:
            skip('fixes231 Y: boolean scores, vendors, POSIX /, check.py --verify', 'FFmpeg missing', 2)
        return
    pack = _load('lf_fix231_packY', scripts / 'pack.py')
    base = Path(j('fix231_y'))
    ours_mp4, ref_mp4 = base / 'ours.mp4', base / 'ref.mp4'
    base.mkdir(parents=True, exist_ok=True)
    _synth_video(ffmpeg, ours_mp4, dur=2.0)
    _synth_video(ffmpeg, ref_mp4, freq=554, color='0x241935', color2='0xc77dff', dur=2.0)
    key = pack.make_pack(ours_mp4, [ref_mp4], base / 'keys', k=1, k_alone=1, reads_root=base / 'reads')
    key_json = Path(key['key_json'])
    ours = key['ours_letter']
    other = next(l for l in key['letters'] if l != ours)

    # 1. Boolean dimension score rejected by pack.py record AND unlisted --family-a lists accepted vendors.
    j_bool = base / 'j_bool.json'
    _write_lf(j_bool, json.dumps({
        'model_family': 'anthropic', 'overall_ranking': [ours, other],
        'films': {ours: {'tier': 'studio', 'pacing': True, 'visual_clutter': 8, 'callout_placement': 8},
                  other: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}},
    }))
    j_google_ok = base / 'j_google_ok.json'
    _write_lf(j_google_ok, json.dumps({
        'model_family': 'google', 'overall_ranking': [ours, other],
        'films': {ours: {'tier': 'studio', 'pacing': 8, 'visual_clutter': 8, 'callout_placement': 8},
                  other: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}},
    }))
    bp_bool = base / 'bp_bool.json'
    tool('pack.py', 'record', str(key_json), '--lineup-a', str(j_bool), '--lineup-b', str(j_google_ok),
         '--out', str(bp_bool))
    bool_doc = json.loads(bp_bool.read_text(encoding='utf-8')) if bp_bool.is_file() else {}
    j_ok = base / 'j_ok.json'
    _write_lf(j_ok, json.dumps({
        'model_family': 'anthropic', 'overall_ranking': [ours, other],
        'films': {ours: {'tier': 'studio', 'pacing': 9, 'visual_clutter': 9, 'callout_placement': 8},
                  other: {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}},
    }))
    bp_vend = base / 'bp_vend.json'
    _, o_vend = tool('pack.py', 'record', str(key_json), '--lineup-a', str(j_ok), '--lineup-b', str(j_google_ok),
                     '--family-a', 'cohere', '--family-b', 'google', '--out', str(bp_vend))
    bp_ok = base / 'bp_ok.json'
    c_ok, _ = tool('pack.py', 'record', str(key_json), '--lineup-a', str(j_ok), '--lineup-b', str(j_google_ok),
                   '--out', str(bp_ok))
    # POSIX / root check via helper (exercises POSIX branch on Windows too).
    posix_err = ''
    if hasattr(pack, '_resolve_alone_reads'):
        try:
            pack._resolve_alone_reads('/', None, _resolved=(PurePosixPath('/'), PurePosixPath('/tmp/alone')))
        except ValueError as err:
            posix_err = str(err)
    record('fixes231 Y: pack.py record rejects boolean dimension scores, lists the six accepted vendors for an '
           'unlisted --family-a, and refuses POSIX / without impossible --alone-reads advice',
           c_ok == 0 and bool_doc.get('status') == 'look'
           and (bool_doc.get('dimension_averages') or {}).get('pacing') != 4.5
           and all(v in o_vend for v in ('anthropic', 'openai', 'google', 'meta', 'mistral', 'xai'))
           and '(--family-a/--family-b)' not in o_vend
           and 'filesystem root' in posix_err and '--alone-reads' not in posix_err,
           f'bool={bool_doc.get("status")}; vend={o_vend.strip()[-140:]}; posix={posix_err[:120]}')

    # 2. Gate B #3a: check.py --verify detects pack.py modification after a --blind-pack check.
    skill_copy = base / 'skill_copy' / 'scripts'
    shutil.copytree(scripts, skill_copy, ignore=shutil.ignore_patterns('__pycache__', 'selftest_cases', 'testpages'))
    shutil.copy2(scripts.parent / 'SKILL.md', skill_copy.parent / 'SKILL.md')
    checks_out = base / 'checks_bp.json'
    subprocess.run([sys.executable, '-I', str(skill_copy / 'check.py'), '--file', str(ours_mp4), '--no-speech',
                    '--blind-pack', str(bp_ok), '--json', str(checks_out)],
                   capture_output=True, text=True, encoding='utf-8', errors='replace')
    chk_doc = json.loads(checks_out.read_text(encoding='utf-8')) if checks_out.is_file() else {}
    bp_state = next((r.get('state') for r in chk_doc.get('items', []) if r.get('id') == 'blind_pack'), None)
    scripts_map = (chk_doc.get('tools') or {}).get('scripts') or {}
    r_v0 = subprocess.run([sys.executable, '-I', str(skill_copy / 'check.py'), '--verify', str(checks_out)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    with open(skill_copy / 'pack.py', 'a', encoding='utf-8', newline='\n') as fh:
        fh.write('\n# modified after check\n')
    r_v1 = subprocess.run([sys.executable, '-I', str(skill_copy / 'check.py'), '--verify', str(checks_out)],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    v1_out = r_v1.stdout + r_v1.stderr
    record('fixes231 Y: check.py --verify exits 0 before and exits 1 naming pack.py after pack.py changes',
           bp_state == 'pass' and 'pack.py' in scripts_map and 'render_common.py' in scripts_map
           and r_v0.returncode == 0 and r_v1.returncode == 1 and 'pack.py' in v1_out,
           f'bp={bp_state} v0={r_v0.returncode} v1={r_v1.returncode}: {v1_out.strip()[-160:]}')


def case_Z(tool, record, j, scripts, skip=None):
    """Z: Python/Node agree on -0.0 and ties >= 1e9; cue_list.py codegen exits 2 without traceback on malformed times/fps;
    LF_CUES_GEN handles ';' and ':' paths; three drift refusals say to run cue_list.py codegen; --help covers codegen."""
    node = shutil.which('node')
    cl = _load('lf_fix231_clZ', scripts / 'cue_list.py')
    proj = _load('lf_fix231_projZ', scripts / 'project.py')
    base = Path(j('fix231_z'))
    base.mkdir(parents=True, exist_ok=True)

    # 1. -0.0 canonicalised to 0.0, and malformed t / fps rejected with exit 2 (no traceback) in Python & Node.
    z_cues = base / 'negzero.json'
    _write_lf(z_cues, json.dumps({'version': 2, 'fps': 24, 'events': [{'id': 'z', 't': -0.0, 'scale': 'contact'}]}))
    cz, oz = tool('cue_list.py', 'codegen', str(z_cues))
    z_js_txt = (base / 'times.gen.js').read_text(encoding='utf-8') if (base / 'times.gen.js').is_file() else ''
    bad_inputs = [
        ('t_abc', {'version': 2, 'fps': 24, 'events': [{'id': 'a', 't': 'abc'}]}),
        ('t_nan', {'version': 2, 'fps': 24, 'events': [{'id': 'a', 't': 'nan'}]}),
        ('t_inf', {'version': 2, 'fps': 24, 'events': [{'id': 'a', 't': 'inf'}]}),
        ('t_bool', {'version': 2, 'fps': 24, 'events': [{'id': 'a', 't': True}]}),
        ('t_huge', {'version': 2, 'fps': 60, 'events': [{'id': 'a', 't': 1e308}]}),
        ('fps_list', {'version': 2, 'fps': ['x', 1], 'events': [{'id': 'a', 't': 0.5}]}),
        ('fps_under', {'version': 2, 'fps': '2_4', 'events': [{'id': 'a', 't': 0.5}]}),
        ('fps_arabic', {'version': 2, 'fps': '\u0662\u0664', 'events': [{'id': 'a', 't': 0.5}]}),
    ]
    bad_fails = []
    cue_gen_js = (scripts / 'cue_gen.cjs').resolve().as_posix()
    for bname, bdoc in bad_inputs:
        bp = base / f'{bname}.json'
        _write_lf(bp, json.dumps(bdoc))
        cb, ob = tool('cue_list.py', 'codegen', str(bp), '--out-ts', str(base / f'{bname}.ts'),
                      '--out-js', str(base / f'{bname}.js'))
        if cb != 2 or 'Traceback' in ob:
            bad_fails.append(f'{bname}:py={cb}({"tb" if "Traceback" in ob else ob.strip()[:60]})')
        if node:
            rn = subprocess.run([node, '-e', f'require({json.dumps(cue_gen_js)}).expectedConstants(process.argv[1])',
                                 str(bp)], capture_output=True, text=True, encoding='utf-8', errors='replace')
            if rn.returncode == 0:
                bad_fails.append(f'{bname}:node=0')
    # the Node side: cue_gen.cjs builds what cue_list.py builds for -0.0 and for a frame rate that is an exact tie at six
    # decimals (24.0078125 = 3073/128, kept whole by the denominator limit of 1001; a rate of 1000000000.0390625 had
    # been the tie here until rates were held to 1 to 1000, which leaves Node's old rounding, wrong only at 10^9 and
    # beyond, nothing to get wrong)
    if node:
        tie = base / 'tie.json'
        _write_lf(tie, json.dumps({'version': 2, 'fps': 24.0078125,
                                   'events': [{'id': 'z', 't': -0.0}, {'id': 'h', 't': -1 / 128}]}))
        py_rows = [_python_constants(cl, p) for p in (z_cues, tie)]
        node_rows = _node_constants(node, scripts, [z_cues, tie], base)
        record('fixes231 Z: cue_gen.cjs builds the same constants as cue_list.py for t -0.0 and for a frame rate that '
               'is an exact tie at six decimals (24.0078125)',
               node_rows == py_rows and (py_rows[1].get('CLOCK') or {}).get('fps') == 24.007812,
               f"python fps {(py_rows[1].get('CLOCK') or {}).get('fps')}, node fps "
               f"{((node_rows[1] if len(node_rows) > 1 else {}).get('CLOCK') or {}).get('fps')}; same={node_rows == py_rows}")
    elif skip:
        skip('fixes231 Z: cue_gen.cjs and cue_list.py agree on -0.0 and a frame rate that is a tie', 'Node missing')
    record('fixes231 Z: cue_list.py codegen canonicalises -0.0 to 0.0 and exits 2 without traceback on malformed '
           't/fps (agreed with cue_gen.cjs)',
           cz == 0 and '-0.0' not in z_js_txt and '"z": 0.0' in z_js_txt and not bad_fails,
           f'cz={cz} neg0={"-0.0" in z_js_txt} bad={bad_fails[:4]}')

    # 2. LF_CUES_GEN handles folder names containing os.pathsep (';' on Windows, ':' on POSIX) and stops tampered ts.
    sep_char = ';' if os.name == 'nt' else ':'
    tricky = base / f'dir{sep_char}2026' / 'page'
    tricky.mkdir(parents=True, exist_ok=True)
    _write_lf(tricky / 'index.html', '<!doctype html><title>t</title>\n')
    _write_lf(tricky / 'cues.json', json.dumps({'version': 2, 'fps': 24, 'events': [{'id': 'hit', 't': 0.25}]}))
    cl.compile_cue_constants(tricky / 'cues.json')
    if node:
        preload = (scripts / 'render_block.cjs').resolve().as_posix()
        capture_url = (scripts / 'film_capture.mjs').resolve().as_uri()
        enc_fn = getattr(cl, 'format_cues_gen_env', lambda ps: os.pathsep.join(str(p) for p in ps))
        gen_env = enc_fn([tricky / 'times.gen.js', tricky / 'times.gen.ts'])
        env_ok = dict(os.environ, NODE_OPTIONS=f'--require "{preload}"',
                      LF_CUES_FILE=str((tricky / 'cues.json').resolve()), LF_CUES_GEN=gen_env)
        env_ok.pop('LF_BLOCK_LOG', None)
        r_pre_ok = subprocess.run([node, '-e', 'process.exit(0)'], capture_output=True, text=True, encoding='utf-8',
                                  errors='replace', env=env_ok)
        # Tamper times.gen.ts in the tricky folder -> preload must still catch the second module!
        orig_ts = (tricky / 'times.gen.ts').read_text(encoding='utf-8')
        _write_lf(tricky / 'times.gen.ts', orig_ts.replace('"t": 0.25', '"t": 0.95'))
        r_pre_bad = subprocess.run([node, '-e', 'process.exit(0)'], capture_output=True, text=True, encoding='utf-8',
                                   errors='replace', env=env_ok)
        _write_lf(tricky / 'times.gen.ts', orig_ts)
        # Also check parseCuesGenEnv / parse_cues_gen_env on paths containing BOTH ':' and ';' and '[draft]'.
        sample_paths = ['/tmp/2026:11:18/a;b/times.gen.js', 'C:\\work;dir\\[draft]\\times.gen.ts']
        py_parsed = cl.parse_cues_gen_env(cl.format_cues_gen_env(sample_paths)) if hasattr(cl, 'parse_cues_gen_env') else []
        py_single = cl.parse_cues_gen_env('[draft]/a;b:c/times.gen.js') if hasattr(cl, 'parse_cues_gen_env') else []
        r_js_parse = subprocess.run(
            [node, '-e', f'const g = require({json.dumps(cue_gen_js)}); '
                         'console.log(JSON.stringify([g.parseCuesGenEnv ? g.parseCuesGenEnv(process.argv[1]) : null, '
                         'g.parseCuesGenEnv ? g.parseCuesGenEnv(process.argv[2]) : null]));',
             json.dumps(sample_paths), '[draft]/a;b:c/times.gen.js'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        js_parsed = json.loads(r_js_parse.stdout) if r_js_parse.returncode == 0 and r_js_parse.stdout.strip() else [None, None]
        record('fixes231 Z: LF_CUES_GEN carries module paths containing ; and : without splitting, and still catches '
               'a tampered second module',
               r_pre_ok.returncode == 0 and r_pre_bad.returncode == 2 and 'times.gen.ts' in r_pre_bad.stderr
               and py_parsed == sample_paths and py_single == ['[draft]/a;b:c/times.gen.js']
               and js_parsed == [sample_paths, ['[draft]/a;b:c/times.gen.js']],
               f'ok={r_pre_ok.returncode}({r_pre_ok.stderr.strip()[:80]}) bad={r_pre_bad.returncode} '
               f'py={py_parsed == sample_paths} js={js_parsed == [sample_paths, ["[draft]/a;b:c/times.gen.js"]]}')
    elif skip:
        skip('fixes231 Z: LF_CUES_GEN Node check', 'Node missing', 1)

    # 3. Three drift refusals say to run cue_list.py codegen; project.py drops stray "the "; --help documents codegen & world_spec.
    drift_dir = base / 'drift_page'
    drift_dir.mkdir(parents=True, exist_ok=True)
    _write_lf(drift_dir / 'index.html', '<!doctype html><title>d</title>\n')
    frec = cl.freeze(drift_dir, offline=True)
    drift_cues = drift_dir / 'cues.json'
    pic_obj = {'kind': 'page', 'path': './', 'sha256': frec['fingerprint'],
               'snapshot_sha256': frec['snapshot_sha256'], 'source_files': frec['source_files']}
    _write_lf(drift_cues, json.dumps({
        'version': 'v2', 'fps': 24, 'provenance': 'exported', 'picture': pic_obj,
        'events': [{'id': 'hit', 't': 0.25, 'scale': 'contact'}],
    }))
    cl.compile_cue_constants(drift_cues)
    # Drift cues.json without rerunning codegen.
    _write_lf(drift_cues, json.dumps({
        'version': 'v2', 'fps': 24, 'provenance': 'exported', 'picture': pic_obj,
        'events': [{'id': 'hit', 't': 0.75, 'scale': 'contact'}],
    }))
    cv, ov = tool('cue_list.py', 'codegen', str(drift_cues), '--verify')
    # film_render.py stops at its tool check (Node, FFmpeg, ffprobe) before it reads the timing, so its refusal can be
    # seen only where Node is installed
    cfr, ofr = (tool('film_render.py', str(drift_dir), '--cues', str(drift_cues), '--out', str(base / 'never.mp4'))
                if node else (None, ''))
    if not node and skip:
        skip('fixes231 Z: film_render.py tells the user to run cue_list.py codegen',
             'Node missing: film_render.py refuses for the missing engine before it reads the timing')
    try:
        proj.run_render(f'"{sys.executable}" -c "pass" {{page}} {{out}}', drift_dir, base / 'never2.mp4',
                        0, 0.05, cues_file=drift_cues, page_dir=drift_dir)
        rr_msg = ''
    except proj.Refused as err:
        rr_msg = str(err)
    from types import SimpleNamespace
    try:
        proj._timing_binding(cl, SimpleNamespace(sha256=_sha(drift_cues)),
                             {'cues_timing_sha256': cl.cue_timing_sha256(drift_cues),
                              'generated': {n: _sha(drift_dir / n) for n in ('times.gen.js', 'times.gen.ts')}},
                             drift_cues, drift_dir)
        tb_msg = ''
    except proj.Refused as err:
        tb_msg = str(err)
    ch_cl, oh_cl = tool('cue_list.py', '--help')
    ch_ws, oh_ws = tool('world_spec.py', '--help')
    record('fixes231 Z: codegen --verify, film_render.py (where Node is installed) and run_render tell the user to '
           'run cue_list.py codegen; _timing_binding drops stray "the "; cue_list.py and world_spec.py --help explain '
           'themselves',
           cv == 2 and 'run cue_list.py codegen' in ov
           and (not node or (cfr == 2 and 'run cue_list.py codegen' in ofr))
           and 'run cue_list.py codegen' in rr_msg
           and tb_msg.startswith('times.gen.js') and not tb_msg.startswith('the times.gen.js')
           and ch_cl == 0 and 'codegen' in oh_cl
           and ch_ws == 0 and len(oh_ws.strip()) > 20,
           f'verify={ov.strip()[-80:]} | fr={ofr.strip()[-80:]} | rr={rr_msg[-80:]} | tb={tb_msg[:50]} | help={ "codegen" in oh_cl }/{ch_ws}')


def case_AA(tool, record, j, scripts, skip=None):
    """AA: setup.py SCRIPTS covers every file in scripts/ (except explained non-scripts), flags missing helpers, and
    clears _IMPORTS after installing core into an active virtual environment."""
    setup_mod = _load('lf_fix231_setup', scripts / 'setup.py')
    exceptions = {
        'NOTICE': 'third-party license attribution text, not an executable script or runtime constraint',
    }
    actual = {p.name for p in scripts.iterdir() if p.is_file() and not p.name.startswith('.')}
    listed = set(setup_mod.SCRIPTS)
    unaccounted = sorted(actual - listed - set(exceptions))
    stale = sorted(listed - actual)

    base = Path(j('fix231_aa'))
    skill_copy = base / 'legible-film'
    shutil.copytree(scripts.parent, skill_copy,
                    ignore=shutil.ignore_patterns('__pycache__', 'selftest_cases', 'testpages', 'assets'))
    # Intact skill folder -> Skill is ready; removing world_spec.py & cue_gen.cjs -> Skill fails naming both.
    r_intact = subprocess.run([sys.executable, '-I', str(skill_copy / 'scripts' / 'setup.py'), '--json'],
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
    intact_doc = json.loads(r_intact.stdout) if r_intact.stdout.strip().startswith('{') else {}
    intact_skill = (intact_doc.get('summary') or {}).get('Skill')

    (skill_copy / 'scripts' / 'world_spec.py').unlink()
    (skill_copy / 'scripts' / 'cue_gen.cjs').unlink()
    r_miss = subprocess.run([sys.executable, '-I', str(skill_copy / 'scripts' / 'setup.py'), '--json'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    miss_doc = json.loads(r_miss.stdout) if r_miss.stdout.strip().startswith('{') else {}
    miss_rows = (miss_doc.get('capabilities') or {}).get('Skill') or []
    miss_detail = ' '.join(str(r.get('detail', '')) for r in miss_rows)
    # Restore removed files for the venv test below.
    shutil.copy2(scripts / 'world_spec.py', skill_copy / 'scripts' / 'world_spec.py')
    shutil.copy2(scripts / 'cue_gen.cjs', skill_copy / 'scripts' / 'cue_gen.cjs')

    record('fixes231 AA: setup.py SCRIPTS accounts for every file in scripts/ and flags missing world_spec.py and '
           'cue_gen.cjs while passing an intact skill folder',
           not unaccounted and not stale and intact_skill == 'ready'
           and r_miss.returncode == 1 and 'world_spec.py' in miss_detail and 'cue_gen.cjs' in miss_detail,
           f'unaccounted={unaccounted} stale={stale} intact={intact_skill} miss={r_miss.returncode}:{miss_detail[:120]}')

    # Gate B #4: setup.py --install core --yes inside a fresh active virtual environment clears _IMPORTS.
    def _make_venv(vdir, write_pkgs):
        subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(vdir)], check=True)
        vpy = vdir / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        plib = Path(subprocess.check_output([str(vpy), '-I', '-X', 'utf8', '-c',
                                             'import sysconfig; print(sysconfig.get_path("purelib"))'],
                                            text=True, encoding='utf-8', errors='replace').strip())
        plib.mkdir(parents=True, exist_ok=True)
        _write_lf(plib / 'pip.py',
                  'import pathlib, sys\n'
                  'if "--version" in sys.argv:\n'
                  '    print("pip 24.0")\n'
                  '    sys.exit(0)\n'
                  'if "install" in sys.argv and ' + repr(bool(write_pkgs)) + ':\n'
                  '    here = pathlib.Path(__file__).resolve().parent\n'
                  '    (here / "numpy.py").write_text("__version__ = \'2.0\'\\n", encoding="utf-8")\n'
                  '    pil = here / "PIL"\n'
                  '    pil.mkdir(exist_ok=True)\n'
                  '    (pil / "__init__.py").write_text("__version__ = \'11.0\'\\n", encoding="utf-8")\n'
                  'sys.exit(0)\n')
        return vpy

    appdata = base / 'empty_appdata'
    appdata.mkdir(parents=True, exist_ok=True)
    clean_env = dict(os.environ, LOCALAPPDATA=str(appdata), XDG_DATA_HOME=str(appdata))
    vpy_ok = _make_venv(base / 'venv_ok', write_pkgs=True)
    r_ok = subprocess.run([str(vpy_ok), str(skill_copy / 'scripts' / 'setup.py'), '--install', 'core', '--yes', '--json'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env)
    ok_doc = json.loads(r_ok.stdout) if r_ok.stdout.strip().startswith('{') else {}
    edit_rows = {r.get('label'): r.get('state') for r in (ok_doc.get('capabilities') or {}).get('Edit and check video') or []}

    # Check from the other side: when numpy remains absent after install, setup.py still reports it missing (exit 1).
    vpy_bad = _make_venv(base / 'venv_bad', write_pkgs=False)
    r_bad = subprocess.run([str(vpy_bad), str(skill_copy / 'scripts' / 'setup.py'), '--install', 'core', '--yes', '--json'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace', env=clean_env)
    bad_doc = json.loads(r_bad.stdout) if r_bad.stdout.strip().startswith('{') else {}
    bad_rows = {r.get('label'): r.get('state') for r in (bad_doc.get('capabilities') or {}).get('Edit and check video') or []}
    ffmpeg_ready = edit_rows.get('ffmpeg') == 'ready' and edit_rows.get('ffprobe') == 'ready'
    record('fixes231 AA: setup.py --install core --yes inside an active venv reports newly installed numpy and Pillow '
           'as ready (and still exits 1 when numpy remains absent)',
           edit_rows.get('numpy') == 'ready' and edit_rows.get('Pillow') == 'ready'
           and (not ffmpeg_ready or r_ok.returncode == 0)
           and r_bad.returncode == 1 and bad_rows.get('numpy') == 'missing',
           f'ok_rc={r_ok.returncode} rows={edit_rows}; bad_rc={r_bad.returncode} bad_numpy={bad_rows.get("numpy")}')



# ------------------------------------------------------------------------------------------------ round 5 (AB-AD)

# The 25 film.js forms of the round-4 review: each body as the spec function's body, and the title Node reports when it
# runs it. A reader of the source had read 11 of them wrong; the check now takes the title from the running page.
REVIEW_FORMS = {
    'duplicate': ("return {title:'Old',title:'Actual',brand:'#123456',scenes:[]};", 'Actual'),
    'spread': ("return {title:'Old',...{title:'Actual'},brand:'#123456',scenes:[]};", 'Actual'),
    'assign': ("return Object.assign({title:'Old',brand:'#123456',scenes:[]},{title:'Actual'});", 'Actual'),
    'two_returns': ("if(true) return {title:'Actual',brand:'#123456',scenes:[]}; "
                    "return {title:'Decoy',brand:'#123456',scenes:[]};", 'Actual'),
    'helper_after_return': ("return {title:'Actual',brand:'#123456',scenes:[]}; "
                            "function helper(){return {title:'Decoy',brand:'#123456',scenes:[]};}", 'Actual'),
    'computed_key': ("return {title:'Old',['title']:'Actual',brand:'#123456',scenes:[]};", 'Actual'),
    'getter_override': ("return {title:'Old',get title(){return 'Actual'},brand:'#123456',scenes:[]};", 'Actual'),
    'property_write': ("const s={title:'Old',brand:'#123456',scenes:[]};s.title='Actual';return s;", 'Actual'),
    'parameter_shadow': ("const title='Outer';function make(title){return {title,brand:'#123456',scenes:[]};}"
                         "return make('Actual');", 'Actual'),
    'compound_assignment': ("let title='Old';title+='Actual';return {title,brand:'#123456',scenes:[]};", 'OldActual'),
    'division': ("const a=12,b=2,c=3,x=a/b/c;return {title:'Actual',brand:'#123456',scenes:[]};", 'Actual'),
    'division_comment': ("let y=8; let x=y/2; // /\nreturn {title:'Actual',brand:'#123456',scenes:[]};", 'Actual'),
    'regex_after_paren': ('if(true) /[`]/.test("x");return {title:"Actual",brand:"#123456",scenes:[]};', 'Actual'),
    'regex_after_return': ('function helper(){return /[`]/;} helper();return {title:"Actual",brand:"#123456",scenes:[]};',
                           'Actual'),
    'nested_template': ('const x=`${`nested ${"x"}`}`;return {title:"Actual",brand:"#123456",scenes:[]};', 'Actual'),
    'template_braces': ('const x=`${({a:"}"}).a}`;return {title:"Actual",brand:"#123456",scenes:[]};', 'Actual'),
    'escaped': (r"""return {title:'Actual\'s `title`',brand:'#123456',scenes:[]};""", "Actual's `title`"),
    'template_unicode': (r"""return {title:`\u0041ctual`,brand:'#123456',scenes:[]};""", 'Actual'),
    'nested_object': ("const o={title:'Decoy'};return {title:'Actual',brand:'#123456',scenes:[],nested:{title:'Nested'}};",
                      'Actual'),
    'array': ("const o=[{title:'Decoy',scenes:[]}];return {title:'Actual',brand:'#123456',scenes:[]};", 'Actual'),
    'defaults': ("function f(x={title:'Decoy',scenes:[]}){}return {title:'Actual',brand:'#123456',scenes:[]};", 'Actual'),
    'calls': ("function f(x){return x} f({title:'Decoy',scenes:[]});return {title:'Actual',brand:'#123456',scenes:[]};",
              'Actual'),
    'title_string': ('const text="return {title:\'Decoy\',scenes:[]}";return {title:"Actual",brand:"#123456",scenes:[]};',
                     'Actual'),
    'asi': ("const P='Actual'\nconst B='#123456'\nreturn {title:P,brand:B,scenes:[]}", 'Actual'),
    'crlf': ("const P='Actual';\r\nreturn {title:P,brand:'#123456',scenes:[]};", 'Actual'),
}

FORM_CARD = """  const Card = kit.block('card', (ctx) => {
    const g = ctx.group;
    const p = ctx.colour('paper');
    ctx.ground(0, 'ink');
    const main = ctx.textNode(g, { string: 'Let it stand.', font: 'serif', size: 46, tracking: -0.035, color: p });
    main.rest({ y: 0 });
    ctx.text({ id: 'serif-main', role: 'headline', string: main.string, nodes: [main], readFrom: 0 });
    return { len: 2.0, ground0: ctx.colour('ink') };
  });
"""


def _form_film(body):
    """A gated kit film whose spec function runs BODY, each `scenes:[]` holding one card."""
    return 'export default function film(kit) {\n' + FORM_CARD + body.replace('scenes:[]', 'scenes:[Card()]') + '\n}\n'


def _preflight(film):
    doc = json.loads((Path(film) / 'qa' / 'preflight.json').read_text(encoding='utf-8'))
    return (doc.get('info') or {}).get('title'), bool((doc.get('world_sheet') or {}).get('present'))


def case_AB(tool, record, j, scripts, skip=None):
    """AB: a world sheet's title is checked against the title the running page reports (a kit film) or the project's
    status.json title, and its world line against the World line stated now; a value given as an option is not
    compared. A reader of film.js had passed a retitled film's old sheet and refused a moved project's own."""
    kit_src = scripts.parent / 'assets' / 'kit'
    ws = _load('lf_fix231_wsAB', scripts / 'world_spec.py')
    check = lambda f: tool('film_check.py', str(f), '--size', '640x360')   # noqa: E731

    # 1. the review's 25 film.js forms, each a real film drawn then checked: the sheet passes exactly when the title
    #    it shows is the one the page runs with (which is the one Node reports); a misread is refused, naming the
    #    --title that fixes it, and drawing with that --title passes
    first = Path(j('fix231_ab', 'forms', 'f-duplicate'))
    _sheet_film(kit_src, first, _form_film(REVIEW_FORMS['duplicate'][0]))
    tool('look.py', 'world-sheet', str(first))
    c0, o0 = check(first)
    if _no_browser(c0, o0):
        if skip:
            skip('fixes231 AB: world sheets checked against the running title', 'Node, Chromium or Playwright missing', 8)
        return
    wrong, misread, fixed = [], [], []
    # the escaped title is the point of template_unicode: the source reader cannot read the escape and misreads it,
    # which takes the refusal path; written as plain Actual it is read right and tests nothing (round 6's review)
    if chr(92) + 'u0041ctual' not in REVIEW_FORMS['template_unicode'][0]:
        wrong.append('template_unicode holds no escaped title')
    for name, (body, node_title) in REVIEW_FORMS.items():
        film = Path(j('fix231_ab', 'forms', 'f-' + name))
        if name != 'duplicate':
            _sheet_film(kit_src, film, _form_film(body))
            tool('look.py', 'world-sheet', str(film))
        meta = json.loads((film / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
        shown = (meta.get('drawn') or {}).get('title')
        code, out = (c0, o0) if name == 'duplicate' else check(film)
        running, present = _preflight(film)
        if running != node_title or present != (shown == node_title) or code != (0 if present else 1):
            wrong.append(f'{name}: shows {shown!r} runs {running!r} node {node_title!r} present={present} exit {code}')
        if shown != node_title:
            misread.append(name)
            if f'    title: {node_title}' not in out:
                wrong.append(f'{name}: the refusal does not give the title {node_title!r}: {out.strip()[-160:]}')
            if name in ('spread', 'assign', 'compound_assignment'):   # three of them drawn again as the refusal says
                tool('look.py', 'world-sheet', str(film), '--title', node_title)
                c_t, _ = check(film)
                fixed.append(c_t == 0)
    record('fixes231 AB: each of the 25 review film.js forms, drawn then checked, passes exactly when the title its '
           'sheet shows is the title the page runs with (as Node reports it); a misread is refused and passes once '
           'drawn with the --title the refusal names',
           not wrong and len(fixed) == 3 and all(fixed) and 'template_unicode' in misread,
           f'{len(REVIEW_FORMS)} forms, {len(misread)} misread ({", ".join(misread)}), {sum(fixed)} of 3 fixed; '
           + '; '.join(wrong))

    # 2. the review's finding 1: a film retitled by a spread after its sheet was drawn is refused; a film moved or
    #    renamed with its sheet passes
    base = Path(j('fix231_ab', 'retitle', 'gate'))
    _sheet_film(kit_src, base)
    tool('look.py', 'world-sheet', str(base))
    renamed = Path(j('fix231_ab', 'retitle', 'moved', 'renamed folder'))
    shutil.copytree(base, renamed)
    c_mv, o_mv = check(renamed)
    copied = Path(j('fix231_ab', 'retitle', 'copied'))
    shutil.copytree(base, copied)
    _write_lf(copied / 'film.js', SHEET_BASE.replace("title: 'Gate Film',", "title: 'Gate Film', ...{title: 'New Film'},"))
    c_cp, o_cp = check(copied)
    record('fixes231 AB: a film copied and retitled (by a spread the source reader cannot see) is refused, naming the '
           'title shown and the title it runs with; a film moved or renamed with its sheet passes',
           c_mv == 0 and c_cp == 1 and "'Gate Film'" in o_cp and "'New Film'" in o_cp
           and '    title: New Film' in o_cp, f'moved={c_mv} retitled={c_cp}: {o_cp.strip()[-220:]}')

    # 3. a computed title: the folder's name is drawn and refused, with the --title to give; --title matching the
    #    running title passes
    comp = Path(j('fix231_ab', 'computed', 'comp'))
    _sheet_film(kit_src, comp, SHEET_BASE.replace("title: 'Gate Film'", "title: ['Gate', 'Film'].join(' ')"))
    tool('look.py', 'world-sheet', str(comp))
    c_cd, o_cd = check(comp)
    tool('look.py', 'world-sheet', str(comp), '--title', 'Gate Film')
    c_ct, o_ct = check(comp)
    record('fixes231 AB: a computed title is refused while the sheet shows the folder\'s name, giving the title '
           '"Gate Film" to pass with --title; drawn with that --title it passes',
           c_cd == 1 and "'comp'" in o_cd and '    title: Gate Film' in o_cd and c_ct == 0,
           f'default={c_cd} titled={c_ct}: {o_cd.strip()[-200:]}')

    # 4. a project's sheet copied into another project titled otherwise is refused, drawn with or without --title;
    #    a project retitled in its status.json is refused too
    projects = {}
    for name, title in (('one', 'Campaign One'), ('two', 'Campaign Two'), ('three', 'Campaign Three')):
        proj = Path(j('fix231_ab', 'projects', name))
        tool('project.py', 'init', str(proj), '--title', title)
        _sheet_film(kit_src, proj / 'film')
        projects[name] = proj
    tool('look.py', 'world-sheet', str(projects['one']))
    c_own, _ = check(projects['one'] / 'film')
    _copy_sheet(projects['one'] / 'refs', projects['two'] / 'refs')
    c_plain, o_plain = check(projects['two'] / 'film')
    tool('look.py', 'world-sheet', str(projects['three']), '--title', 'Custom Title')
    c_own3, _ = check(projects['three'] / 'film')
    _copy_sheet(projects['three'] / 'refs', projects['two'] / 'refs')
    c_titled, o_titled = check(projects['two'] / 'film')
    status = projects['three'] / 'status.json'
    _write_lf(status, status.read_text(encoding='utf-8').replace('"Campaign Three"', '"Campaign Renamed"'))
    c_ret, o_ret = check(projects['three'] / 'film')
    record('fixes231 AB: a project\'s sheet copied into another project with a different title is refused, drawn with '
           'or without --title, and so is a sheet whose project was retitled in status.json',
           c_own == 0 and c_own3 == 0 and c_plain == 1 and c_titled == 1 and c_ret == 1
           and "'Campaign One'" in o_plain and "'Campaign Two'" in o_plain and "'Campaign Three'" in o_titled
           and "'Campaign Renamed'" in o_ret,
           f'own={c_own}/{c_own3} copied={c_plain} copied_titled={c_titled} retitled={c_ret}: {o_titled.strip()[-200:]}')

    # 5. the review's finding 2: an explicitly titled project moved into a folder named like its title keeps its sheet
    titled = Path(j('fix231_ab', 'finding2', 'titled-project'))
    tool('project.py', 'init', str(titled), '--title', 'Campaign')
    _sheet_film(kit_src, titled / 'film')
    tool('look.py', 'world-sheet', str(titled))
    c_t0, _ = check(titled / 'film')
    moved = Path(j('fix231_ab', 'finding2', 'moved', 'Campaign'))
    shutil.copytree(titled, moved)
    c_t1, o_t1 = check(moved / 'film')
    record('fixes231 AB: an explicitly titled project moved into a folder named like its title keeps its sheet',
           c_t0 == 0 and c_t1 == 0, f'before={c_t0} moved={c_t1}: {o_t1.strip()[-200:]}')

    # 6. the world line: a stated one must still be stated; a default one passes only while none is; one given as
    #    an option is not compared
    wl = Path(j('fix231_ab', 'world', 'stated'))
    _sheet_film(kit_src, wl)
    _write_lf(wl / 'treatment.md', '# Treatment\n\n- World line: proof x printing press\n')
    tool('look.py', 'world-sheet', str(wl))
    c_w0, _ = check(wl)
    _write_lf(wl / 'treatment.md', '# Treatment\n\n- World line: proof x lighthouse\n')
    c_w1, o_w1 = check(wl)
    wd = Path(j('fix231_ab', 'world', 'default'))
    _sheet_film(kit_src, wd)
    tool('look.py', 'world-sheet', str(wd))
    c_d0, _ = check(wd)
    _write_lf(wd / 'look.md', '# Look\n\n- World line: proof x lighthouse\n')
    c_d1, o_d1 = check(wd)
    wo = Path(j('fix231_ab', 'world', 'option'))
    _sheet_film(kit_src, wo)
    tool('look.py', 'world-sheet', str(wo), '--world-line', 'proof x brass')
    _write_lf(wo / 'treatment.md', '# Treatment\n\n- World line: proof x lighthouse\n')
    c_o1, o_o1 = check(wo)
    record('fixes231 AB: a changed stated World line, or one stated after a default was drawn, is refused naming both; '
           'a --world-line given at draw time is not compared',
           c_w0 == 0 and c_w1 == 1 and "'proof x printing press'" in o_w1 and "'proof x lighthouse'" in o_w1
           and c_d0 == 0 and c_d1 == 1 and "'proof x lighthouse'" in o_d1 and c_o1 == 0,
           f'stated={c_w0}/{c_w1} default={c_d0}/{c_d1} option={c_o1}: {o_w1.strip()[-200:]}')

    # 7. the record: the title and world line drawn and where each came from; a project's status.json title as it
    #    was, even with --title
    meta_k = json.loads((comp / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
    meta_p = json.loads((projects['three'] / 'refs' / 'world-sheet.json').read_text(encoding='utf-8'))
    meta_w = json.loads((wl / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
    meta_b = json.loads((base / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
    record('fixes231 AB: the record keeps where the title and world line came from (option, film.js, status.json, a '
           'stated file, default) and a project\'s status.json title at draw time',
           meta_k.get('sources') == {'title': 'option', 'world_line': 'default'}
           and meta_b.get('sources') == {'title': 'film.js', 'world_line': 'default'}
           and meta_w.get('sources') == {'title': 'film.js', 'world_line': 'treatment.md'}
           and (meta_p.get('sources') or {}).get('title') == 'option' and meta_p.get('project_title') == 'Campaign Three'
           and 'hints' not in meta_k,
           f"kit={meta_k.get('sources')} base={meta_b.get('sources')} world={meta_w.get('sources')} "
           f"project={meta_p.get('sources')}/{meta_p.get('project_title')}")

    # 8. the check function itself: the kit's placeholder title and an empty one are "no title"; it never raises on
    #    a record of the wrong shape
    png = base / 'qa' / 'world-sheet.png'
    untitled = dict(meta_b, sources={'title': 'default', 'world_line': 'default'})
    verdicts, shapes = [], []
    for t in ('untitled', '', None, '  ', 'Named'):
        try:
            verdicts.append(ws.sheet_owner(png, untitled, base, t)[0])
        except Exception as error:   # noqa: BLE001
            verdicts.append(f'raised {error!r}')
    for bad in ({}, [], None, {'target_rel': '..'}, {'target_rel': '..', 'drawn': 'x'},
                {'target_rel': '..', 'drawn': {}, 'sources': {}}, {'target_rel': '..', 'kind': 'project', 'drawn': {}}):
        try:
            shapes.append(ws.sheet_owner(png, bad, base, 'Gate Film')[0])
        except Exception as error:   # noqa: BLE001
            shapes.append(f'raised {error!r}')
    record('fixes231 AB: a sheet drawn with the folder\'s name passes while the page reports no title (missing, empty or '
           '"untitled"), and records of the wrong shape are refused without raising',
           verdicts == ['own', 'own', 'own', 'own', 'values'] and all(v in ('other', 'values') for v in shapes),
           f'untitled={verdicts} shapes={shapes}')



# The round-4 review's reading files: a Markdown template for ours A and yardstick B, each attack changing one field,
# and JSON with the other key names and scores written as text it had claimed were read.
REVIEW_MARKDOWN = ('model_family: {family}\n1. overall_ranking: {ranking}\n2. A: {tier}, pacing: {score}, '
                   'visual_clutter: 8, callout_placement: 8\n   B: freelance, pacing: 7, visual_clutter: 7, '
                   'callout_placement: 7\n{extra}')
REVIEW_MARKDOWN_ATTACKS = {
    'valid': {}, 'denominator100': {'score': '8/100'}, 'over80': {'score': '80/10'}, 'negative': {'score': '-3'},
    'scientific': {'score': '1e1'}, 'unknown_rank': {'ranking': 'A, B, G'}, 'duplicate_rank': {'ranking': 'A, B, A'},
    'conflicting_tier': {'tier': 'studio; tier: beginner'},
    'duplicate_letter': {'extra': '   A: beginner, pacing: 1, visual_clutter: 1, callout_placement: 1\n'},
    'nonreading': {'tier': 'studio is a word mentioned here; no judgment is supplied'},
}
REVIEW_PLAIN_LABELS = ('model_family: {family}\n1. overall_ranking: A, B\n2. films:\n'
                       'A: studio, pacing: 8, visual_clutter: 8, callout_placement: 8\n'
                       'B: freelance, pacing: 7, visual_clutter: 7, callout_placement: 7\n3. steals:\n- clear cut\n')



# A text file a person or a tool on Windows may have written: LF, CRLF or CR line ends, with or without a UTF-8
# byte-order mark. Cases that read such a file test every form (round 6's LF-only reading fixtures had missed CRLF).
CR, LF, BOM = chr(13), chr(10), chr(0xfeff)


def _text_forms(text):
    """{form: bytes} for TEXT saved with LF, CRLF and CR line ends, each with and without a byte-order mark."""
    plain = text.lstrip(BOM).replace(CR + LF, LF).replace(CR, LF)
    forms = {}
    for label, end in (('LF', LF), ('CRLF', CR + LF), ('CR', CR)):
        for bom in ('', BOM):
            forms[label + (' + BOM' if bom else '')] = (bom + plain.replace(LF, end)).encode('utf-8')
    return forms


def _same_in_every_form(results):
    """The one result every form gave, or a result that says which forms differ."""
    first = next(iter(results.values()))
    if all(r[:2] == first[:2] for r in results.values()):
        return first
    return ('forms differ: ' + ', '.join(f'{form}={r[:2]}' for form, r in results.items()), None, [])


def _json_reading(family, **change):
    """A complete JSON reading of line-up A (ours) and B, with CHANGE applied to its top level."""
    doc = {'model_family': family, 'overall_ranking': ['A', 'B'],
           'films': {'A': {'tier': 'studio', 'pacing': 8, 'visual_clutter': 8, 'callout_placement': 8,
                           'strongest': 'clean cuts', 'weakest': 'a long hold', 'tells': 'none'},
                     'B': {'tier': 'freelance', 'pacing': 7, 'visual_clutter': 7, 'callout_placement': 7}},
           'steals': ['hold the end card']}
    doc.update(change)
    return doc


def _with_film(family, letter, **fields):
    doc = _json_reading(family)
    doc['films'][letter] = dict(doc['films'][letter], **fields)
    return doc


def case_AC(tool, record, j, scripts, skip=None):
    """AC: a blind line-up reading is the JSON object the brief shows, and nothing else: one shape, in the brief,
    pack.py record --help and references/eyes.md alike; anything else leaves the reading incomplete, saying what is
    wrong, and check.py --blind-pack agrees with pack.py record on every reading. A Markdown reader had accepted
    contradictory and invalid readings as complete, and refused a valid plain form."""
    try:
        pack = _load('lf_fix231_packAC', scripts / 'pack.py')
        check = _load('lf_fix231_checkAC', scripts / 'check.py')
    except SystemExit:
        if skip:
            skip('fixes231 AC: JSON line-up readings', 'numpy or Pillow missing', 4)
        return
    base = Path(j('fix231_ac'))
    base.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(b'stand-in film').hexdigest()
    key = base / 'pack-1-key.json'
    _write_lf(key, json.dumps({'ours_letter': 'A', 'letters': {'A': {'stem': 'ours'}, 'B': {'stem': 'reference'}},
                               'film_sha256': sha}))

    # 1. one shape: the brief pack.py writes, pack.py record --help and references/eyes.md hold the same text
    brief = Path(j('fix231_ac', 'brief'))
    brief.mkdir(parents=True, exist_ok=True)
    lineup_brief, _ = pack._render_briefs(brief, 1, brief / 'pack', {'duration': 2.0, 'fps': 24.0}, 2, 1, 1)
    brief_text = Path(lineup_brief).read_text(encoding='utf-8')
    c_help, o_help = tool('pack.py', 'record', '--help')
    eyes = (scripts.parent / 'references' / 'eyes.md').read_text(encoding='utf-8')
    shape = str(getattr(pack, 'READING_SHAPE', '') or '').strip('\n')
    try:
        example = json.loads(shape[shape.index('{'):shape.index('\n}') + 2])
    except ValueError:
        example = {}
    record('fixes231 AC: the reading shape is one text, word for word in the line-up brief, pack.py record --help and '
           'references/eyes.md, its example is a complete reading, and none of them offers Markdown',
           bool(shape) and shape in brief_text and c_help == 0 and shape in o_help and shape in eyes
           and 'Markdown' not in brief_text + o_help and 'labeled' not in brief_text
           and example.get('overall_ranking') == ['B', 'A'],
           f'brief={shape in brief_text} help={c_help}/{shape in o_help} eyes={shape in eyes}')

    # 2. readings: each written to two files (anthropic and google), recorded, then checked as check.py does
    def run_once(name, a_bytes, b_bytes, flags):
        a_path, b_path, out = base / f'{name}-a.txt', base / f'{name}-b.txt', base / f'{name}-report.json'
        a_path.write_bytes(a_bytes)
        b_path.write_bytes(b_bytes)
        try:
            res = pack.record_readings(key, a_path, b_path, out=out, **dict(flags))
        except Exception as error:   # noqa: BLE001
            return f'raised {error!r}', None, []
        state = check.blind_pack_item(out, sha).get('state')
        return res['status'], state, res['reasons']

    def run(name, a_text, b_text, *flags):
        """Each reading in every line-end and byte-order-mark form (_text_forms); all forms must agree."""
        b_forms = _text_forms(b_text)
        return _same_in_every_form({form: run_once(f'{name}-{i}', data, b_forms[form], flags)
                                    for i, (form, data) in enumerate(_text_forms(a_text).items())})

    def both(doc_a, doc_b=None, wrap=json.dumps):
        return wrap(doc_a), wrap(doc_b if doc_b is not None else dict(doc_a, model_family='google'))

    md = {name: tuple(REVIEW_MARKDOWN.format(**{'ranking': 'A, B', 'tier': 'studio', 'score': '8/10', 'extra': '',
                                                **opts, 'family': fam})
                      for fam in ('anthropic', 'google'))
          for name, opts in REVIEW_MARKDOWN_ATTACKS.items()}
    md['plain labels'] = tuple(REVIEW_PLAIN_LABELS.format(family=fam) for fam in ('anthropic', 'google'))
    alt = {}
    for shape_key in ('films', 'letters', 'top', 'per_letter', 'entries'):
        entries = {l: {'tier': 'professional studio', 'pacing': '8/10', 'visual_clutter': '8/10',
                       'callout_placement': '8/10'} for l in 'AB'}
        docs = []
        for fam in ('anthropic', 'google'):
            doc = {'model_family': fam, 'overall_ranking': ['A', 'B']}
            doc.update(entries if shape_key == 'top' else {shape_key: entries})
            docs.append(json.dumps(doc))
        alt[f'json {shape_key} with text scores'] = tuple(docs)
    good = json.dumps(_json_reading('anthropic'))
    good_b = json.dumps(_json_reading('google'))
    refused = {**md, **alt,
               'unknown letter in the ranking': both(_json_reading('anthropic', overall_ranking=['A', 'B', 'G'])),
               'letter ranked twice': both(_json_reading('anthropic', overall_ranking=['A', 'B', 'A'])),
               'ranking as text': both(_json_reading('anthropic', overall_ranking='A, B')),
               'tier not one of the four': both(_with_film('anthropic', 'A', tier='professional studio')),
               'tier in capitals': both(_with_film('anthropic', 'A', tier='Studio')),
               'tier skilled hobbyist': both(_with_film('anthropic', 'A', tier='skilled hobbyist')),
               'score as text': both(_with_film('anthropic', 'A', pacing='8')),
               'score over 10': both(_with_film('anthropic', 'A', pacing=80)),
               'score under 1': both(_with_film('anthropic', 'A', pacing=0)),
               'score true': both(_with_film('anthropic', 'A', pacing=True)),
               'score for the yardstick missing': both(_with_film('anthropic', 'B', callout_placement=None)),
               'a letter not in the line-up': both(_json_reading('anthropic', films=dict(
                   _json_reading('x')['films'], G=_json_reading('x')['films']['B']))),
               'no entry for the yardstick': both(_json_reading('anthropic', films={'A': _json_reading('x')['films']['A']})),
               'film A twice': (good.replace('"films": {', '"films": {"A": {"tier": "beginner", "pacing": 1, '
                                             '"visual_clutter": 1, "callout_placement": 1}, ', 1), good_b),
               'no model family': both(_json_reading(None), _json_reading(None)),
               'two JSON blocks': ('```json\n' + good + '\n```\nand again\n```json\n' + good + '\n```\n', good_b),
               'prose only': ('Film A is the stronger: studio work.\n', good_b),
               'an array': ('[' + good + ']', good_b),
               'broken JSON': (good[:-1], good_b),
               'NaN score': (json.dumps(_with_film('anthropic', 'A', pacing=float('nan'))), good_b),
               }
    accepted = {
        'the whole text': (good, good_b),
        'one fenced block with prose around': ('Here is my reading.\n\n```json\n' + good + '\n```\n\nThanks.\n', good_b),
        'a fenced block with no language': ('```\n' + good + '\n```\n', good_b),
        'unknown extra keys': both(_json_reading('anthropic', notes='fine', films=dict(
            _json_reading('x')['films'], A=dict(_json_reading('x')['films']['A'], confidence=0.8)))),
        'scores with decimals': both(_with_film('anthropic', 'A', pacing=7.5)),
        'a UTF-8 byte-order mark': ('﻿' + good, good_b),
    }
    wrong = []
    for name, (a_text, b_text) in refused.items():
        status, state, reasons = run(name.replace(' ', '_'), a_text, b_text)
        if status != 'look' or state == 'pass' or state is None or not any('incomplete' in r for r in reasons):
            wrong.append(f'{name}: record {status}, check {state}, {reasons[:1]}')
    for name, (a_text, b_text) in accepted.items():
        status, state, reasons = run(name.replace(' ', '_'), a_text, b_text)
        if status != 'pass' or state != 'pass':
            wrong.append(f'{name}: record {status}, check {state}, {reasons[:2]}')
    status_fam, state_fam, _ = run('family_by_flag', json.dumps(_json_reading(None)), json.dumps(_json_reading(None)),
                                   ('family_a', 'anthropic'), ('family_b', 'google'))
    if status_fam != 'pass' or state_fam != 'pass':
        wrong.append(f'model family by --family-a/--family-b: record {status_fam}, check {state_fam}')
    record('fixes231 AC: the review\'s Markdown readings, its JSON with other key names or text scores, and every '
           'invalid JSON reading are refused as incomplete; a correct JSON reading, whole or in one fenced block with '
           'prose around, passes; check.py --blind-pack agrees with pack.py record on every one',
           not wrong, f'{len(refused)} refused, {len(accepted) + 1} accepted; ' + '; '.join(wrong))

    # 3. the message says what is wrong and what to ask the reader for
    _, _, r_unknown = run('msg_unknown', *both(_json_reading('anthropic', overall_ranking=['A', 'B', 'G'])))
    _, _, r_prose = run('msg_prose', 'A is better.\n', good_b)
    _, _, r_tier = run('msg_tier', *both(_with_film('anthropic', 'A', tier='Studio')))
    said = ' | '.join(r_unknown + r_prose + r_tier)
    record('fixes231 AC: a refused reading names what is wrong and what to ask the reader for',
           any('names G, not in the line-up' in r and 'ask the reader' in r for r in r_unknown)
           and any('no JSON object' in r and 'ask the reader for the JSON object the brief shows' in r
                   and 'pack.py record --help' in r and 'new reader of the same lineup/ folder' in r for r in r_prose)
           and any("tier for A is 'Studio'" in r and 'beginner, hobbyist, freelance, studio' in r for r in r_tier),
           said[:400])



NODE_CONSTANTS = """const g = require(process.argv[2]);
const paths = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify(paths.map((p) => { try { return g.expectedConstants(p); } catch (e) { return {error: e.message}; } })));
"""


def _python_constants(cl, path):
    try:
        found = cl._cues_constants_data(path)
        return {k: found[k] for k in ('CUES_SHA256', 'CLOCK', 'SECTIONS', 'TIMES', 'FRAMES', 'CUES')}
    except cl.CueListError as error:
        return {'error': str(error)}
    except Exception as error:   # noqa: BLE001 - a traceback in Python is a difference too
        return {'error': f'raised {type(error).__name__}: {error}'[:200]}


def _node_constants(node, scripts, paths, work):
    """cue_gen.cjs expectedConstants for each cue list in PATHS, in one Node process."""
    runner, listing = Path(work) / 'constants.cjs', Path(work) / 'paths.json'
    _write_lf(runner, NODE_CONSTANTS)
    _write_lf(listing, json.dumps([str(p) for p in paths]))
    r = subprocess.run([node, str(runner), str((scripts / 'cue_gen.cjs').resolve()), str(listing)], capture_output=True,
                       text=True, encoding='utf-8', errors='replace', timeout=120)
    rows = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
    return [{k: row[k] for k in ('CUES_SHA256', 'CLOCK', 'SECTIONS', 'TIMES', 'FRAMES', 'CUES') if k in row}
            if 'error' not in row else row for row in rows]


AD_COMMON_RATES = [  # every common rate, as a fraction, a whole number and its decimal spellings
    '24000/1001', 24, 25, '30000/1001', 30, 48, 50, '60000/1001', 60, 100, 120, 240, 1000,
    23.976, 23.98, 29.97, 59.94, 47.952, 119.88, 239.76, '23.976', '23.98', '29.97', '59.94', '119.88',
    24.0, '24', '24.0', '25.00', ' 30 ', '48/1', '50/1', 60.0, '1000', '1000/1', '1000.0', 1, 1.0, '1', '1/1',
    '2002/2002', '1000000/1000', '24000/1000', '2997/100', '5994/100', '90000/3003', '15000/1001', '1440000/48047']
# past the bounds, refused by both with the same message: under 1, over 1000, a rate that limits to 0, the review's
# NTSC-route rate whose derived numerator Node rounded, and the float the review printed two ways
AD_REFUSED_RATES = [0.5, 0.999, '999/1000', '1000/1001', '1001/1', 1000.6, 1001, 2000, '0/5', 0.0001, 1e-308,
                    3.0226124694072083e-05, 464311658961133.8, 1e15, '9007199254740991/1', '1000000001/1000000', 'x', '', '24/0', -24, True]
AD_REFUSED_SIZES = ['0x1080', '1920x0', '32769x1080', '1080x32769', '0000x0001', '0' * 5000 + '32769x1',
                    '1' * 6000 + 'x1080']


def _ad_range_docs(seed=231):
    """Cue lists across the accepted range: the common rates, random rates and rationals inside 1 to 1000, NTSC
    decimals, sizes up to 32768, and times on, beside and half way between frame boundaries up to 10^9 s. Each list
    holds many events, so tens of thousands of times are compared in a few hundred lists."""
    import random
    rng = random.Random(seed)
    rates = list(AD_COMMON_RATES)
    rates += [rng.uniform(1, 1000) for _ in range(120)]
    rates += [repr(rng.uniform(1, 1000)) for _ in range(40)]
    rates += [round(rng.uniform(1, 1000), rng.choice((1, 2, 3))) for _ in range(60)]
    for _ in range(120):
        den = rng.choice((1, 2, 3, 7, 100, 1001, 1000, rng.randint(1, 10 ** 6), rng.randint(1, 10 ** 12)))
        rates.append(f'{rng.randint(den, 1000 * den)}/{den}')
    for _ in range(60):   # the NTSC route: k * 1000/1001 written as a decimal
        k = rng.randint(1, 1000)
        rates.append(round(k * 1000 / 1001, rng.choice((2, 3))))
    rates += [1 + 2 ** -40, 1000 - 2 ** -40, math.nextafter(1000.0, 0), '1000000000000/1000000000', '999999999/1000000']
    sizes = ['1x1', '32768x32768', '00032768x00001', '1920x1080', '3840x2160', '7680x4320', '8192x4320', '1080x1920']
    sizes += [f'{rng.randint(1, 32768)}x{rng.randint(1, 32768)}' for _ in range(40)]
    docs = []
    for n, fps in enumerate(rates):
        rate = float(Fraction(fps.strip())) if isinstance(fps, str) else float(fps)
        events, sections = [], []
        last = int(1e9 * rate)
        for i in range(100):
            k = rng.choice((rng.randint(0, 2000), rng.randint(0, last), int(10 ** rng.uniform(0, math.log10(last + 1)))))
            on = k / rate
            t = rng.choice((on, (k + 0.5) / rate, math.nextafter(on, 0), math.nextafter(on, 2e9),
                            math.nextafter((k + 0.5) / rate, 0), round(on, 6), round((k + 0.5) / rate, 6)))
            t = min(t, 1e9) * rng.choice((1, 1, 1, -1))
            if i % 10 == 9:
                events.append({'id': f'e{i}', 'frame': k})
            elif i % 10 == 8 and abs(t) < 1e9 - 2:
                events.append({'id': f'e{i}', 't': t, 'scale': 'silence', 't_end': t + rng.random()})
            else:
                events.append({'id': f'e{i}', 't': t})
        for i in range(6):
            a = rng.choice(events).get('t', 0.0)
            sections.append({'id': f's{i}', 'a': a, 'b': min(abs(a) + rng.random() * 30, 1e9)})
        docs.append({'version': 2, 'fps': fps, 'size': sizes[n % len(sizes)], 'events': events, 'sections': sections,
                     **({'duration': 1e9} if n % 7 == 0 else {})})
    return docs


def case_AD(tool, record, j, scripts, skip=None):
    """AD: a number too large for a float is refused with a message (exit 2), not a traceback; cue times beyond
    10^9 s, frame numbers beyond 2^53 - 1, frame rates outside 1 to 1000 and sizes outside 1 to 32768 are refused in
    Python and Node with the same message; and every cue list either accepts, the two build the same constants for (a
    differential table, and tens of thousands of times across the accepted range)."""
    cl = _load('lf_fix231_clAD', scripts / 'cue_list.py')
    node = shutil.which('node')
    base = Path(j('fix231_ad'))
    base.mkdir(parents=True, exist_ok=True)

    # 1. a number too large for a float, as t or as fps: a message and exit 2 from codegen
    huge = {'huge t': {'version': 2, 'fps': 24, 'events': [{'id': 'a', 't': 10 ** 400}]},
            'huge fps': {'version': 2, 'fps': 10 ** 400, 'events': [{'id': 'a', 't': 0.25}]},
            'huge fps text': {'version': 2, 'fps': '1' + '0' * 400, 'events': [{'id': 'a', 't': 0.25}]},
            'huge frame': {'version': 2, 'fps': 24, 'events': [{'id': 'a', 'frame': 10 ** 400}]}}
    bad = []
    for name, doc in huge.items():
        path = base / (name.replace(' ', '_') + '.json')
        _write_lf(path, json.dumps(doc))
        code, out = tool('cue_list.py', 'codegen', str(path), '--out-ts', str(base / 'x.ts'), '--out-js', str(base / 'x.js'))
        if code != 2 or 'Traceback' in out or 'must be' not in out and 'overflows' not in out and 'beyond' not in out:
            bad.append(f'{name}: exit {code}: {out.strip()[-120:]}')
    record('fixes231 AD: cue_list.py codegen refuses a t, fps or frame too large for a float with a message and exit 2, '
           'not a traceback', not bad, '; '.join(bad) or f'{len(huge)} refused')

    # 2. the differential table: Python and Node build the same constants for every list both accept, and refuse
    #    the same lists; past the bounds both refuse in the same words
    rates = [23.976, 24, 25, 29.97, 30, 60, '24000/1001', '30000/1001', 1000000, 1000000000.0390625,
             # rational parts past 2^53 - 1 (refused in both, in the same words) and just inside
             '216172782113820900/9007199254742537', '9007199254740992/375299968947541', '24/9007199254740992',
             '9007199254740991/375299968947541', '24/9007199254740991', '0009007199254740991/9007199254740991',
             # rates that limit to 0 (refused in both) and positive neighbours
             0.0001, 1e-308, '1e-308', 0.0005, '0/5', 0.001, 0.01, '1/1001']
    times = [0.0, -0.0, 0.25, 1.1875, 1 / 128, 3 / 128, math.nextafter(1 / 128, 0), math.nextafter(1 / 128, 1),
             1e6 + 1 / 128, 1e9 - 1 + 1 / 128, 1e9, -1e9, 1e9 + 1 / 128, 1e12 + 1 / 128, 1e15, 1e20]
    docs = []
    for fps in rates:
        for t in times:
            for silence in (False, True):
                docs.append({'version': 2, 'fps': fps, 'events': [
                    {'id': 'a', 't': t, 'scale': 'silence' if silence else 'contact',
                     **({'t_end': t + 1.0 if abs(t) < 1e9 - 1 else t} if silence else {})}],
                     'sections': [{'id': 's', 'a': 0, 'b': t + 2.0 if abs(t) < 1e9 - 2 else t}]})
        for frame in (5, 5.0, 2 ** 53 - 1, 2 ** 53, 2 ** 53 + 1):
            docs.append({'version': 2, 'fps': fps, 'events': [{'id': 'f', 'frame': frame}]})
    docs.append({'version': 2, 'fps': 2 ** 53 + 2, 'events': [{'id': 'a', 't': 0}]})
    # gate A2: the size's width and height either side of 2^53 - 1, digits of another script, very long zero-padded
    # values (Python 3.11+ refuses int() on more than 4300 digits), and the gate's own rate inputs
    arabic = ''.join(chr(0x660 + int(d)) for d in '1280') + 'x' + ''.join(chr(0x660 + int(d)) for d in '720')
    for size in ('9007199254740991x1080', '9007199254740992x1080', '9007199254740993x1080', '1920x9007199254740992',
                 '1080x9007199254740991', '0009007199254740991x1080', arabic, '0' * 5000 + '1920x1080', '1280x720'):
        docs.append({'version': 2, 'fps': 24, 'size': size, 'events': [{'id': 'a', 't': 0.5}]})
    for fps in ('27021597764222979/9007199254740994', '27021597764222979/9007199254740991', 0.0005,
                '0' * 5000 + '24', '0' * 5000 + '24/1', '24/' + '0' * 5000 + '1'):
        docs.append({'version': 2, 'fps': fps, 'sections': [{'id': 's1', 'a': 0.0, 'b': 2.0, 'clock': 'action'}],
                     'events': [{'id': 'hit', 't': 1.0, 'scale': 'contact'}]})
    paths = []
    for i, doc in enumerate(docs):
        path = base / f'diff-{i}.json'
        _write_lf(path, json.dumps(doc))
        paths.append(path)
    py = [_python_constants(cl, p) for p in paths]
    bound = 'a cue time is beyond 1000000000 s'
    py_beyond = sum(1 for d, row in zip(docs, py) if 'error' in row and bound in row['error'])
    py_kept = sum(1 for row in py if 'error' not in row)
    if not node:
        if skip:
            skip('fixes231 AD: Python and Node build the same constants for every cue list either accepts',
                 'Node missing: cue_gen.cjs cannot run')
        record('fixes231 AD: Python refuses cue times beyond 10^9 s and keeps those within it',
               py_beyond > 0 and py_kept > 0
               and all(bound not in row.get('error', '') for d, row in zip(docs, py)
                       if all('t' in e and abs(e['t']) <= 1e9 - 1 for e in d['events'])),
               f'{py_kept} built, {py_beyond} beyond the bound')
        _ad_range(record, cl, node, scripts, base)
        _ad_ids(record, cl, node, scripts, base)
        return
    nd = _node_constants(node, scripts, paths, base)
    differ = []
    for doc, a, b in zip(docs, py, nd):
        if a != b:
            differ.append(f"fps {doc['fps']} {doc['events'][0]}: python {str(a)[:90]} node {str(b)[:90]}")
    record('fixes231 AD: across the differential table Python and Node build the same constants for every cue list both '
           'accept, refuse the same lists, and refuse times beyond 10^9 s, frames beyond 2^53 - 1 and such frame rates '
           'in the same words',
           len(nd) == len(docs) and not differ and py_beyond > 0 and py_kept > 0,
           f'{len(docs)} lists: {py_kept} built, {py_beyond} beyond the time bound, {len(differ)} differ; '
           + '; '.join(differ[:4]))
    _ad_range(record, cl, node, scripts, base)
    _ad_ids(record, cl, node, scripts, base)


def _ad_range(record, cl, node, scripts, base):
    """AD part 3: across the accepted range (_ad_range_docs) both build the same constants, and a frame rate under 1
    or over 1000 and a width or height under 1 or over 32768 are refused by both with one message, no number in it
    written in either language's own float format (round 6's review found 85 refusals that differed only so)."""
    docs = _ad_range_docs()
    refused = [{'version': 2, 'fps': fps, 'events': [{'id': 'a', 't': 0.5}]} for fps in AD_REFUSED_RATES]
    refused += [{'version': 2, 'fps': 24, 'size': size, 'events': [{'id': 'a', 't': 0.5}]} for size in AD_REFUSED_SIZES]
    # a malformed time names its cue as JSON.stringify quotes it, in both (Python's repr had written 'a' for "a")
    refused += [{'version': 2, 'fps': 24, 'duration': 3, 'sections': [{'id': cid, 'a': 'x'}], 'events': []}
                for cid in ('a', 'q' + chr(34) + 'x', chr(0xe9) + 't' + chr(0xe9), chr(10), chr(0xd800), '5')]
    refused += [{'version': 2, 'fps': 24, 'duration': 3, 'events': [{'id': 'a', 't': '1e400'}]}]
    paths = []
    for i, doc in enumerate(docs + refused):
        path = base / f'range-{i}.json'
        _write_lf(path, json.dumps(doc))
        paths.append(path)
    py = [_python_constants(cl, p) for p in paths]
    wrong = [f"{doc['fps']!r} {doc.get('size')}: {str(row.get('error'))[:120]}"
             for doc, row in zip(docs, py) if 'error' in row]
    for doc, row in zip(refused, py[len(docs):]):
        said = row.get('error', '')
        if not ('fps must be from 1 to 1000 frames a second' in said or 'must have a width and height from 1 to 32768' in said
                or said.startswith('fps must be a positive number or a rational string')
                or 'numerator or denominator beyond' in said
                or said.endswith((' a must be a finite number', ' t must be a finite number'))):
            wrong.append(f"refused? fps {doc['fps']!r} size {doc.get('size', '')[:12]}: {str(row)[:120]}")
    times = sum(len(doc['events']) + len(doc['sections']) for doc in docs)
    if not node:
        record('fixes231 AD: Python builds every cue list across the accepted range and refuses a frame rate or size past '
               'its bounds', not wrong, '; '.join(wrong[:3]) or f'{len(docs)} lists, {times} times; {len(refused)} refused')
        return
    nd = _node_constants(node, scripts, paths, base)
    differ = [f"{doc['fps']!r}: python {str(a)[:100]} node {str(b)[:100]}"
              for doc, a, b in zip(docs + refused, py, nd) if a != b]
    record('fixes231 AD: across the accepted range (common, random and NTSC rates from 1 to 1000, sizes to 32768, times '
           'on and around frame boundaries to 10^9 s) Python and Node build the same constants, and both refuse a rate '
           'or size past the bounds with the same message',
           len(nd) == len(paths) and not differ and not wrong and times > 10000,
           f'{len(docs)} lists, {times} times, {len(refused)} refused; {len(differ)} differ; '
           + '; '.join((differ + wrong)[:3]))



# Cue and section ids as written in a file (raw JSON, so 9007199254740993 stays the number written), with the text each
# stands for, or None when the id rule refuses it. Round 7's review: Python kept 9007199254740993 exactly and Node's
# JSON.parse rounded it, so Python generated a module both Node checks refused; 1.0 was "1.0" in one and "1" in the
# other; 1e20, arrays and objects differed too.
AD_IDS = [('"a"', 'a'), ('"9007199254740993"', '9007199254740993'), ('9007199254740991', '9007199254740991'),
          ('-9007199254740991', '-9007199254740991'), ('1', '1'), ('1.0', '1'), ('-0.0', '0'), ('1e0', '1'),
          ('9007199254740993', None), ('9007199254740992', None), ('-9007199254740992', None), ('1e20', None),
          ('1.5', None), ('[1]', None), ('{"a": 1}', None), ('true', None), ('null', None)]


# No name: where a cue list gives a name the timing hash covers as it is written (a cue's scale and section, a
# section's clock, and a section's id), each of these is refused. A number there was written 1.0 by Python and 1 by
# Node, so the modules Python generated were refused by both Node checks (the confirmation of round 8).
AD_NOT_NAMES = ['1', '1.0', '9007199254740993', '1e21', 'true', '[1.0]', '{"a": 1.0}', '0', '-0.0', 'false', '[]', '{}']
# No size: only text is a size, and anything else takes the default 1920 by 1080 in both. Node's String() of a list
# holding "800x600" is that text, so it had read 800 by 600 where Python took the default, and the two hashed
# different clocks for a list both accept (the re-check of round 9).
AD_NOT_SIZES = ['"size": ["800x600"]', '"size": [["800x600"]]', '"export": {"size": ["800x600"]}',
                '"size": ["99999x99999"]', '"size": 800', '"size": {"w": 800}', '"size": true']
AD_ID_RULE = ('an id must be text, or a whole number from -9007199254740991 to 9007199254740991; write any other id '
              'as text, in double quotes')


def _ad_doc(events='{"id": "e", "t": 0.5, "scale": "contact"}', sections='', extra=''):
    """A v2 plan list, well formed apart from what the caller writes into it."""
    return ('{"version": "v2", "fps": 24, "duration": 3, ' + (extra + ', ' if extra else '')
            + '"picture": {"kind": "plan"}, "sections": [' + sections + '], "events": [' + events + ']}')


def _ad_ids(record, cl, node, scripts, base):
    """AD part 4: a cue's id is text, or a whole number within 2^53 - 1 either way, written as that whole number, and
    a span names a follow cue the same way; every other name the timing hash covers (a section's id, a cue's scale
    and section, a section's clock) is text. Anything else is refused by Python and Node with one
    message, and the cue list reader refuses it too; what both build, the reader reads. A size that is not text is
    no size to either, and a "sections" or "events" that is no list holds none. Round 8's lists were not v2 lists and
    were never given to the reader, so a section id the reader refuses had been written up as allowed."""
    rows, paths = [], []

    def add(label, text, want, reader=True):
        """WANT: ('TIMES' or 'SECTIONS', the key the constants must hold), or the refusal's text. READER: whether the
        cue list reader is asked too."""
        path = base / f'id-{len(paths)}.json'
        _write_lf(path, text)
        rows.append((label, want, text if reader else None))
        paths.append(path)

    section = '{"id": "s", "a": 0, "b": 1, "clock": "action"}'
    for raw, want in AD_IDS:
        add(f'cue id {raw}', _ad_doc('{"id": ' + raw + ', "t": 0.5, "scale": "contact"}'),
            ('TIMES', want) if want is not None else f'event 0: {AD_ID_RULE}')
        add(f'section id {raw}', _ad_doc(sections='{"id": ' + raw + ', "a": 0, "b": 1, "clock": "action"}'),
            ('SECTIONS', json.loads(raw)) if raw.startswith('"') else "section 0: a section's id must be text, in double quotes")
    for raw in AD_NOT_NAMES:
        add(f'scale {raw}', _ad_doc('{"id": "e", "t": 0.5, "scale": ' + raw + '}'), 'event "e" scale must be text, in double quotes')
        add(f'section {raw}', _ad_doc('{"id": "e", "t": 0.5, "scale": "contact", "section": ' + raw + '}', section),
            'event "e" section must be text, in double quotes')
        add(f'clock {raw}', _ad_doc(sections='{"id": "s", "a": 0, "b": 1, "clock": ' + raw + '}'),
            'section "s" clock must be text, in double quotes')
    # what works today and goes on working: names as text, a cue in its section, a follow cue named by a span
    add('names as text', _ad_doc('{"id": "e", "t": 0.5, "scale": "contact", "role": "tap", "section": "s", "picture": '
                                 '"held", "decision": "kept"}', section), ('TIMES', 'e'))
    # a role and a picture note are not in the hash, and real lists keep objects there: built as before, by both (the
    # reader holds a v2 list's picture note to text, as it did, so it is not asked)
    add('a picture note and a role that are objects',
        _ad_doc('{"id": "e", "t": 0.5, "scale": "contact", "role": {"bus": 2.0}, "picture": {"line": 17, "frame": 49, '
                '"motion": 23.58, "window_s": [21.4, 23.0]}}'), ('TIMES', 'e'), reader=False)
    for raw in AD_NOT_SIZES:
        add(f'no size: {raw}', _ad_doc(extra=raw), ('CLOCK', 'width'))
    # a "sections" or "events" that is no list holds none in both (a number there had been a traceback in Python);
    # the reader refuses such a list, so it is not asked
    for raw in ('"sections": 123', '"sections": true', '"events": 123', '"events": true'):
        text = '{"version": "v2", "fps": 24, "duration": 3, "picture": {"kind": "plan"}, ' + raw + ', '
        text += ('"events": [{"id": "e", "t": 0.5, "scale": "contact"}]}' if raw.startswith('"sections"')
                 else '"sections": []}')
        add(f'no list: {raw}', text, ('CLOCK', 'width'), reader=False)
    for span in ('"1"', '1', '1.0'):
        add(f'a follow cue 1.0 named by span {span}',
            _ad_doc('{"id": 1.0, "t": 0.0, "t_end": 2.0, "scale": "follow"}, {"id": "hit", "t": 1.0, "scale": "contact", '
                    '"span": ' + span + '}'), ('TIMES', '1'))
    py = [_python_constants(cl, path) for path in paths]
    wrong = []
    for (label, want, text), row, path in zip(rows, py, paths):
        if isinstance(want, str):
            if row.get('error') != f'{path.name}: {want}':
                wrong.append(f'{label}: not refused as {want!r}: {str(row)[:110]}')
        elif 'error' in row or want[1] not in (row.get(want[0]) or {}):
            wrong.append(f'{label}: not built with {want[1]!r} in {want[0]}: {str(row)[:110]}')
        elif label.startswith('no size') and (row['CLOCK']['width'], row['CLOCK']['height']) != (1920, 1080):
            wrong.append(f"{label}: built {row['CLOCK']['width']} by {row['CLOCK']['height']}, not the default")
        # the cue list reader agrees: it reads what both build, and refuses what both refuse
        if text is None:
            continue
        try:
            problems = cl.validate_v2(json.loads(text), 24.0)
        except Exception as error:   # noqa: BLE001 - a traceback from the reader is a fault of its own
            problems = None
            wrong.append(f'{label}: the reader raised {type(error).__name__}: {error}'[:160])
        if problems is not None and bool(problems) != isinstance(want, str):
            wrong.append(f'{label}: the reader says {problems[:2] or "nothing"}, the constants say {str(want)[:60]}')
    # two things the reader said badly: an empty id was told to be put in double quotes, and a whole number of more
    # than 4300 digits (which Python does not read) ended in a traceback
    said = cl.validate_v2(json.loads(_ad_doc('{"id": "", "t": 0.5, "scale": "contact"}')), 24.0)
    if said != ['event 0: an id must not be empty']:
        wrong.append(f'an empty id: the reader says {said}')
    long_id = base / 'id-long.json'
    _write_lf(long_id, _ad_doc('{"id": ' + '9' * 4301 + ', "t": 0.5, "scale": "contact"}'))
    for read in (cl.read_document, cl._cues_constants_data):
        try:
            read(long_id)   # a Python with no such limit reads it, and the id rule refuses it later
        except cl.CueListError:
            pass
        except Exception as error:   # noqa: BLE001
            wrong.append(f'a 4301-digit id: {read.__name__} raised {type(error).__name__}')
    if not node:
        record('fixes231 AD: Python builds a text or whole-number cue id within 2^53 - 1, refuses any other id and any '
               'name that is not text, and the cue list reader agrees', not wrong,
               '; '.join(wrong[:3]) or f'{len(paths)} lists')
        return
    nd = _node_constants(node, scripts, paths, base)
    differ = [f'{label}: python {str(a)[:90]} node {str(b)[:90]}' for (label, _, _), a, b in zip(rows, py, nd) if a != b]
    record('fixes231 AD: Python and Node build the same constants for a text or whole-number cue id within 2^53 - 1 (1.0 '
           'as "1", and a span names it so) and refuse with the same message any other id (9007199254740993, 1e20, 1.5, '
           'an array, an object, true, null) and any section id, scale, section or clock that is not text (0, false and '
           '[] too); a role and a picture note stay as the list gives them; a size that is not text is the default in '
           'both; the cue list reader reads what they build and refuses what they refuse',
           len(nd) == len(paths) and not differ and not wrong,
           f'{len(paths)} lists; {len(differ)} differ; ' + '; '.join((differ + wrong)[:3]))


# ------------------------------------------------------------------------------------------------ round 5 review (AE-)

def case_AE(tool, record, j, scripts, skip=None):
    """AE: a world-sheet refusal says to draw the sheet again with look.py world-sheet and gives the folder and the
    title the film runs with each on a line of its own, exactly as they are, with the title to pass with --title.
    Nothing in it is a shell command line: none is right in sh, cmd.exe and PowerShell at once. Round 6 had printed a
    command "ready to paste" that no shell runs as printed (look.py is no command), and a title holding a double
    quote had broken the one before it."""
    ws = _load('lf_fix231_wsAE', scripts / 'world_spec.py')
    kit_src = scripts.parent / 'assets' / 'kit'
    # every spelling of the world line the reader takes is the one look.md and the changelog list (round 6's review:
    # "- World:" was read and listed nowhere)
    look_md = (scripts.parent / 'references' / 'look.md').read_text(encoding='utf-8')
    changelog = scripts.parents[2] / 'CHANGELOG.md'
    log = changelog.read_text(encoding='utf-8') if changelog.is_file() else None
    spellings = {'World': '- World: brass x prism', 'World line': '- World line: brass x prism',
                 'Visual world': '- Visual world: brass x prism'}
    unlisted = [name for name, line in spellings.items()
                if not ws._WORLD.search(line) or f'`{name}`' not in look_md or (log is not None and f'`{name}`' not in log)]
    unlisted += [line for line in ('- Tone: warm', '- Worldbuilding: x', 'World line: no bullet') if ws._WORLD.search(line)]
    # any label after the word World is taken too, which the documents say (round 7's review: they had listed only the
    # three labels); the reader is left as it is for this release
    prefix = ws._WORLD.search('- World population: eight billion')
    if not (prefix and prefix.group(1) == 'eight billion' and '- World population' in look_md
            and (log is None or '- World population' in log)):
        unlisted.append('- World population: read, and said so in look.md and the changelog')
    record('fixes231 AE: each spelling the world-line reader takes (World, World line, Visual world, and any label after '
           'World) is listed in look.md and the changelog, and no other line is read as one',
           not unlisted, ', '.join(unlisted) or f'{len(spellings)} spellings')
    B, Q, NL = chr(92), chr(34), chr(10)
    titles = ['Gate', 'A Gate Film', "Actual's cut", 'A' + B + 'B cut', 'R&D (v2) [cut]; #1',
              'A ' + Q + 'quoted' + Q + ' title', 'A ' + chr(96) + 'tick', 'Cost $HOME', '100%PATH% off', 'Hi!',
              'ends' + B, 'Arbol ' + chr(0x65e5) + chr(0x672c), '-x film', 'emoji ' + chr(0x1f3ac)]
    wrong = []
    for folder_name in ('paste film', 'cost $HOME ' + chr(0xe9) + 'lan'):
        film = Path(j('fix231_ae', folder_name))
        _sheet_film(kit_src, film)
        c_draw, o_draw = tool('look.py', 'world-sheet', str(film))
        if c_draw == 2 and ('numpy' in o_draw or 'Pillow' in o_draw or 'PIL' in o_draw):
            if skip:
                skip('fixes231 AE: what a refusal says to do', 'numpy or Pillow missing', 2)
            return
        png = film / 'qa' / 'world-sheet.png'
        meta = json.loads((film / 'qa' / 'world-sheet.json').read_text(encoding='utf-8'))
        for title in titles:
            advise = getattr(ws, 'redraw_advice', None)
            if advise is None:
                wrong.append('world_spec has no redraw_advice')
                break
            text = advise(png, meta, [('title', 'Gate Film', title)], title)
            lines = text.split(NL)
            if not (lines[0].startswith('Draw it again with look.py world-sheet') and 'with --title' in lines[0]
                    and lines[1] == f'    folder: {film.resolve()}' and lines[2] == f'    title: {title}'
                    and len(lines) == 3):
                wrong.append(f'{title!r} in {folder_name!r}: {text[:160]!r}')
            if any(line.lstrip().startswith(('look.py', 'python')) for line in lines) or '--title ' + Q in text:
                wrong.append(f'{title!r}: something in it reads as a command line: {text[:160]!r}')
        # a sheet whose own title was not the trouble names the folder only
        other = ws.redraw_advice(png, meta, [('world_line', 'a', 'b')], 'Gate Film')             if hasattr(ws, 'redraw_advice') else None
        if other != f'Draw it again with look.py world-sheet for this folder:{NL}    folder: {film.resolve()}':
            wrong.append(f'world line only: {other!r}')
    record('fixes231 AE: a refusal gives the folder and the running title each on a line of its own, exactly, says to '
           'draw again with look.py world-sheet passing the title with --title, and prints no command line',
           not wrong, '; '.join(wrong[:3]) or f'{len(titles)} titles in 2 folders')

    # end to end: the review's running title holding double quotes
    quoted = Path(j('fix231_ae', 'quoted'))
    _sheet_film(kit_src, quoted, SHEET_BASE.replace("title: 'Gate Film'", "title: ['A', '" + Q + "quoted" + Q
                                                    + "', 'title'].join(' ')"))
    tool('look.py', 'world-sheet', str(quoted))
    c_q, o_q = tool('film_check.py', str(quoted), '--size', '640x360')
    if _no_browser(c_q, o_q):
        if skip:
            skip('fixes231 AE: a refusal for a running title holding double quotes', 'Node, Chromium or Playwright missing')
        return
    title = 'A ' + Q + 'quoted' + Q + ' title'
    record('fixes231 AE: a film whose running title holds double quotes is refused with that title, exactly, on a line '
           'of its own',
           c_q == 1 and f'    title: {title}' in o_q and 'Draw it again with look.py world-sheet' in o_q
           and '--title ' + Q not in o_q, o_q.strip()[-260:])


def case_AF(tool, record, j, scripts, skip=None):
    """AF: line-up readings at the review's boundaries: each is recorded as pack.py record and checked as check.py
    --blind-pack does, and the two agree."""
    try:
        pack = _load('lf_fix231_packAF', scripts / 'pack.py')
        check = _load('lf_fix231_checkAF', scripts / 'check.py')
    except SystemExit:
        if skip:
            skip('fixes231 AF: line-up readings at the review\'s boundaries', 'numpy or Pillow missing', 1)
        return
    base = Path(j('fix231_af'))
    base.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(b'stand-in film').hexdigest()
    key = base / 'pack-1-key.json'
    _write_lf(key, json.dumps({'ours_letter': 'A', 'letters': {'A': {'stem': 'ours'}, 'B': {'stem': 'reference'}},
                               'film_sha256': sha}))

    def run_once(name, a_bytes, b_bytes):
        a_path, b_path, out = base / f'{name}-a.txt', base / f'{name}-b.txt', base / f'{name}-report.json'
        a_path.write_bytes(a_bytes)
        b_path.write_bytes(b_bytes)
        try:
            res = pack.record_readings(key, a_path, b_path, out=out)
        except Exception as error:   # noqa: BLE001
            return f'raised {type(error).__name__}', None, []
        return res['status'], check.blind_pack_item(out, sha).get('state'), res['reasons']

    def run(name, a_bytes, b_bytes=None):
        """(record status, check.py state, reasons) for reader A's response A_BYTES beside a valid reader B. Text is
        tried in every line-end and byte-order-mark form (_text_forms), which must all give the same result."""
        b_text = b_bytes.decode('utf-8') if isinstance(b_bytes, bytes) else json.dumps(_json_reading('google'))
        if isinstance(a_bytes, bytes):
            return run_once(name, a_bytes, b_text.encode('utf-8'))
        b_forms = _text_forms(b_text)
        return _same_in_every_form({form: run_once(f'{name}-{i}', data, b_forms[form])
                                    for i, (form, data) in enumerate(_text_forms(a_bytes).items())})

    # review 2: a score written as a JSON integer too large for a float leaves the reading incomplete, naming it
    huge = {
        'ours pacing 10**400': json.dumps(_with_film('anthropic', 'A', pacing=10 ** 400)),
        'yardstick pacing 10**400': json.dumps(_with_film('anthropic', 'B', pacing=10 ** 400)),
        'ours score -10**400': json.dumps(_with_film('anthropic', 'A', callout_placement=-10 ** 400)),
    }
    got = {name: run('huge_' + str(i), text) for i, (name, text) in enumerate(huge.items())}
    control = run('huge_control', json.dumps(_with_film('anthropic', 'B', pacing=10)))
    record('fixes231 AF: a score written as a JSON integer too large for a float leaves the reading incomplete, '
           'naming the field (check.py agrees), and a whole-number score in range still passes',
           all(s == 'look' and st == 'look' and any('pacing for' in r or 'callout_placement for' in r for r in rs)
               for s, st, rs in got.values()) and control[:2] == ('pass', 'pass'),
           f'{ {k: v[:2] for k, v in got.items()} } control={control[:2]} {[v[2][:1] for v in got.values()]}'[:400])

    # review 3: the whole text is tried as JSON first; when it is not, the one fenced block is read, whatever the
    # prose around it begins with; two blocks and a key given twice are still refused
    good = json.dumps(_json_reading('anthropic'), indent=1)
    fence = '```json\n' + good + '\n```\n'
    twice = good.replace('"films": {', '"films": {"A": {"tier": "beginner", "pacing": 1, "visual_clutter": 1, '
                                       '"callout_placement": 1}, ', 1)
    cases = {
        'brace-led prose, one block': ('{My notes follow}\n' + fence + 'Thank you.\n', 'pass'),
        'bracket-led prose, one block': ('[draft] my reading:\n' + fence, 'pass'),
        'brace-led prose, two blocks': ('{My notes}\n' + fence + fence, 'look'),
        'brace-led prose, a key twice in the block': ('{My notes}\n```json\n' + twice + '\n```\n', 'look'),
        'a key twice in the whole text': (twice, 'look'),
        'broken whole text, no block': (good[:-2], 'look'),
        'the whole text': (good, 'pass'),
    }
    seen = {name: run('fence_' + str(i), text) for i, (name, (text, _)) in enumerate(cases.items())}
    record('fixes231 AF: a valid reading in the one fenced block passes whatever the prose before it begins with, '
           'while two blocks, a key given twice and broken JSON are still refused (check.py agrees)',
           all(seen[name][:2] == (want, want) for name, (_, want) in cases.items()),
           str({name: seen[name][:2] for name in cases})[:400])

    # review 7: strongest, weakest, tells and steals are free text the tool does not check, as the shape says
    free = {
        'steals as text': json.dumps(_json_reading('anthropic', steals='hold the end card')),
        'steals left out': json.dumps({k: v for k, v in _json_reading('anthropic').items() if k != 'steals'}),
        'steals holding a number': json.dumps(_json_reading('anthropic', steals=['keep it', 3])),
        'strongest true, tells left out': json.dumps(_with_film('anthropic', 'A', strongest=True, tells=None)),
    }
    free_seen = {name: run('free_' + str(i), text) for i, (name, text) in enumerate(free.items())}
    says = 'pack.py record does not check them, and any of them may be left out' in ' '.join(
        str(getattr(pack, 'READING_SHAPE', '')).split())
    record('fixes231 AF: the shape says strongest, weakest, tells and steals are free text the tool does not check, '
           'and readings holding them in any form, or leaving them out, pass (check.py agrees)',
           says and all(v[:2] == ('pass', 'pass') for v in free_seen.values()),
           f'says={says} ' + str({k: v[:2] for k, v in free_seen.items()})[:300])

    # review 8: NaN and Infinity are not JSON, wherever they stand
    nan, inf = float('nan'), float('inf')
    tokens = {
        'NaN in an unknown top-level field': json.dumps(_json_reading('anthropic', notes=nan)),
        'NaN in a film\'s unknown field': json.dumps(_with_film('anthropic', 'B', confidence=nan)),
        'Infinity as free text': json.dumps(_with_film('anthropic', 'A', strongest=inf)),
        '-Infinity in steals': json.dumps(_json_reading('anthropic', steals=['a', -inf])),
        'NaN in the one fenced block': 'My reading:\n```json\n' + json.dumps(_json_reading('anthropic', x=nan))
                                       + '\n```\n',
    }
    token_seen = {name: run('token_' + str(i), text) for i, (name, text) in enumerate(tokens.items())}
    text_nan = run('token_text', json.dumps(_json_reading('anthropic', notes='NaN')))
    record('fixes231 AF: NaN, Infinity or -Infinity anywhere in a reading leaves it incomplete, saying it is not JSON '
           '(check.py agrees); the word "NaN" as a string still passes',
           all(v[:2] == ('look', 'look') and any('not JSON' in r for r in v[2]) for v in token_seen.values())
           and text_nan[:2] == ('pass', 'pass'),
           str({k: v[:2] for k, v in token_seen.items()})[:300] + f' text={text_nan[:2]}')

    # review 10: a reading is UTF-8 (a byte-order mark is fine); another encoding is refused, saying so
    plain = json.dumps(_with_film('anthropic', 'A', strongest='Arbol ' + chr(0x65e5)), ensure_ascii=False)
    encodings = {
        'UTF-16 with a byte-order mark': (plain.encode('utf-16'), 'look'),
        'UTF-16 without one': (plain.encode('utf-16-le'), 'look'),
        'UTF-32': (plain.encode('utf-32'), 'look'),
        'Latin-1 with an accent': (json.dumps(_with_film('anthropic', 'A', strongest='caf' + chr(0xe9)),
                                              ensure_ascii=False).encode('latin-1'), 'look'),
        'UTF-8': (plain.encode('utf-8'), 'pass'),
        'UTF-8 with a byte-order mark': (plain.encode('utf-8-sig'), 'pass'),
    }
    enc_seen = {name: run('enc_' + str(i), data) for i, (name, (data, _)) in enumerate(encodings.items())}
    said = [r for name, (_, want) in encodings.items() if want == 'look' for r in enc_seen[name][2]
            if r.startswith("reader A's reading is incomplete")]
    record('fixes231 AF: a reading in UTF-16, UTF-32 or Latin-1 is refused, saying to save it as UTF-8, while UTF-8 '
           'with or without a byte-order mark passes (check.py agrees); the help says a reading is UTF-8',
           all(enc_seen[name][:2] == (want, want) for name, (_, want) in encodings.items())
           and len(said) == 4 and all('save the reading as UTF-8' in r for r in said)
           and 'UTF-8 file' in tool('pack.py', 'record', '--help')[1],
           str({k: v[:2] for k, v in enc_seen.items()})[:300])

    # gate A (not blocking): a hand-edited blind-pack.json holding letters or a ranking of the wrong types is a look
    # from check.py with a message, never a traceback (a {} letter or a [1, "B"] ranking had raised TypeError)
    good_report = base / 'huge_control-0-report.json'   # the LF form of the control reading
    sound = json.loads(good_report.read_text(encoding='utf-8')) if good_report.is_file() else {}
    damaged = {
        'an unhashable letter': dict(sound, letters=['A', 'B', {}]),
        'a ranking of a number and a letter': dict(sound, readers=dict(sound.get('readers') or {}, a=dict(
            (sound.get('readers') or {}).get('a') or {}, ranking=[1, 'B']))),
        'letters as text': dict(sound, letters='AB'),
        'readers as a list': dict(sound, readers=[1, 2]),
        'an unhashable ours letter': dict(sound, ours_letter={'A': 1}),
        # gate 3: the summary fields check.py describes the report with
        'families as a number': dict(sound, families=7),
        'families as a mapping': dict(sound, families={'a': 'openai'}),
        'families holding a number': dict(sound, families=['openai', 3]),
        'dimension_averages as a list': dict(sound, dimension_averages=[1, 2]),
        'dimension_averages as text': dict(sound, dimension_averages='pacing 4'),
        'a dimension average as a mapping': dict(sound, dimension_averages={'pacing': {'x': 1}}),
        'reasons holding numbers': dict(sound, status='look', reasons=[1, 2]),
        'reasons as a number': dict(sound, status='look', reasons=5),
        # round 7's review and gate 4: a null reason had shared the families rule, raising TypeError under a look
        # and passing under a pass
        'reasons holding a null': dict(sound, status='look', reasons=[None]),
        'reasons holding a null, status pass': dict(sound, status='pass', reasons=[None]),
        'reasons mixing text and null': dict(sound, status='look', reasons=['ranked below the yardstick', None]),
    }
    states, labels = {}, {}
    for i, (name, doc) in enumerate(damaged.items()):
        path = base / f'damaged-{i}.json'
        _write_lf(path, json.dumps(doc))
        try:
            found = check.blind_pack_item(path, sha)
            states[name] = found.get('state')
            labels[name] = str(found.get('label') or found.get('title') or '') + ' ' + str(found.get('detail') or '')
        except Exception as error:   # noqa: BLE001
            states[name] = f'raised {type(error).__name__}'
    control_state = check.blind_pack_item(good_report, sha).get('state') if good_report.is_file() else None
    # text reasons are still accepted: under a look they are the detail; under a pass they do not stop it
    texts_look, texts_pass = None, None
    for i, status in enumerate(('look', 'pass')):
        path = base / f'reasons-text-{i}.json'
        _write_lf(path, json.dumps(dict(sound, status=status, reasons=['ours ranked second', 'pacing scored 6'])))
        found = check.blind_pack_item(path, sha) if sound else {}
        if status == 'look':
            texts_look = found.get('state') == 'look' and 'ours ranked second' in str(found.get('detail'))
        else:
            texts_pass = found.get('state') == 'pass'
    summary = [name for name in damaged if name.startswith(('families', 'dimension', 'a dimension', 'reasons'))]
    unsaid = [name for name in summary if 'damaged report' not in labels.get(name, '')
              or name.split()[0 if not name.startswith('a ') else 1].rstrip('s') not in labels.get(name, '')]
    record('fixes231 AF: a hand-edited blind-pack.json with letters, a ranking, families, dimension averages or reasons '
           'of the wrong types is a look from check.py saying what is damaged, never a traceback; the undamaged report '
           'still passes',
           all(s == 'look' for s in states.values()) and control_state == 'pass' and not unsaid
           and texts_look and texts_pass,
           f'{states} control={control_state} unsaid={unsaid} text reasons: look={texts_look} pass={texts_pass}')



def case_AG(tool, record, j, scripts, skip=None):
    """AG: a 2.3.0 receipt registered with the spotted copy of its cue list (cues.spotted.json, as the sound workflow
    says) binds when what is on disk proves the timing it rendered: its recorded modules, still on disk and holding the
    list's timing (a film_render.py receipt). It is refused when the spotted list's timing differs, when the modules
    changed since the render, and when it records no modules and names another list (B)."""
    from types import SimpleNamespace
    cl = _load('lf_fix231_clAG', scripts / 'cue_list.py')
    proj = _load('lf_fix231_projAG', scripts / 'project.py')
    doc = {'version': 2, 'fps': 24, 'events': [{'id': 'hit', 't': 0.25, 'scale': 'contact'},
                                               {'id': 'land', 't': 1.0, 'scale': 'contact'}]}

    def project_at(name):
        """A page with cues.json and its modules, and the spotted copy spotting writes beside the project's audio."""
        root = Path(j('fix231_ag', name))
        page = root / 'film'
        page.mkdir(parents=True, exist_ok=True)
        _write_lf(page / 'index.html', '<!doctype html><title>t</title>\n')
        _write_lf(page / 'cues.json', json.dumps(doc, indent=1))
        cl.compile_cue_constants(page / 'cues.json')
        spotted = root / 'audio' / 'cues.spotted.json'
        spotted.parent.mkdir(parents=True, exist_ok=True)
        roles = copy.deepcopy(doc)
        for ev, role in zip(roles['events'], ('tap', 'land')):
            ev.update(role=role, sound=f'{role}-1')
        _write_lf(spotted, json.dumps(roles, indent=1))
        return page, spotted

    def bind(receipt, cues, page):
        try:
            return 'reasons' if proj._timing_binding(cl, SimpleNamespace(sha256=_sha(cues)), receipt, cues, page) \
                else 'binds'
        except proj.Refused as error:
            return 'refused: ' + str(error)[:100]

    def render_receipt(page):
        """What a 2.3.0 film_render.py receipt records: the list it was given and the modules, no timing hash."""
        return {'cues_sha256': _sha(page / 'cues.json'),
                'generated': {n: _sha(page / n) for n in ('times.gen.js', 'times.gen.ts')}}

    page, spotted = project_at('render_spotted')
    a_spotted = bind(render_receipt(page), spotted, page)
    a_own = bind(render_receipt(page), page / 'cues.json', page)
    # the other side: the spotted list's timing differs; the modules changed since the render; no modules recorded
    page2, spotted2 = project_at('render_moved')
    receipt2 = render_receipt(page2)
    moved = json.loads(spotted2.read_text(encoding='utf-8'))
    moved['events'][1]['t'] = 1.5
    _write_lf(spotted2, json.dumps(moved, indent=1))
    a_moved = bind(receipt2, spotted2, page2)
    page3, spotted3 = project_at('render_regenerated')
    receipt3 = render_receipt(page3)
    _write_lf(page3 / 'times.gen.js', (page3 / 'times.gen.js').read_text(encoding='utf-8') + '\n')
    a_changed = bind(receipt3, spotted3, page3)
    page4, spotted4 = project_at('no_modules')
    a_bare = bind({'cues_sha256': '0' * 64}, spotted4, page4)
    # the modules alone prove the timing: the page's cues.json rewritten byte for byte with the same timing, so the
    # list the receipt names is found nowhere (round 6's review: removing this proof had left AG passing)
    page9, spotted9 = project_at('render_list_rewritten')
    receipt9 = render_receipt(page9)
    _write_lf(page9 / 'cues.json', (page9 / 'cues.json').read_text(encoding='utf-8') + '\n')
    a_rewritten = (bind(receipt9, spotted9, page9), bind(receipt9, page9 / 'cues.json', page9))
    record('fixes231 AG: a 2.3.0 film_render.py receipt registered with cues.spotted.json binds when its recorded '
           'modules are on disk and hold that list\'s timing, even once the cues.json it names was rewritten with the '
           'same timing; it is refused when the spotted timing differs, when the modules changed since the render, and '
           'when no modules are recorded and the list is another',
           a_spotted == 'binds' and a_own == 'binds' and a_rewritten == ('binds', 'binds')
           and a_moved.startswith('refused') and a_changed.startswith('refused') and a_bare.startswith('refused'),
           f'spotted={a_spotted}; own={a_own}; rewritten={a_rewritten}; moved={a_moved}; changed={a_changed}; '
           f'bare={a_bare}')

    # a 2.3.0 make_film.py deliverable receipt records the list's hash and no modules: the page's cues.json is that
    # very list (found by its hash) and holds the spotted list's timing, so it binds; otherwise it is refused
    def make_receipt(page):
        return {'cues_sha256': _sha(page / 'cues.json')}

    page5, spotted5 = project_at('make_spotted')
    b_spotted = bind(make_receipt(page5), spotted5, page5)
    page6, spotted6 = project_at('make_list_edited')
    receipt6 = make_receipt(page6)
    _write_lf(page6 / 'cues.json', (page6 / 'cues.json').read_text(encoding='utf-8') + '\n')   # same timing, new bytes
    b_edited = bind(receipt6, spotted6, page6)
    page7, spotted7 = project_at('make_list_gone')
    receipt7 = make_receipt(page7)
    (page7 / 'cues.json').unlink()
    b_gone = bind(receipt7, spotted7, page7)
    # a page without timing modules: only the named list's timing can tell a moved spotted cue
    page8, spotted8 = project_at('make_no_modules')
    for n in ('times.gen.js', 'times.gen.ts'):
        (page8 / n).unlink()
    receipt8 = make_receipt(page8)
    b_plain = bind(receipt8, spotted8, page8)
    moved8 = json.loads(spotted8.read_text(encoding='utf-8'))
    moved8['events'][0]['t'] = 0.5
    _write_lf(spotted8, json.dumps(moved8, indent=1))
    b_plain_moved = bind(receipt8, spotted8, page8)
    record('fixes231 AG: a 2.3.0 make_film.py receipt (no modules recorded) binds cues.spotted.json when the page\'s '
           'cues.json is the very list it names and holds that timing; it is refused when that list was edited or is '
           'gone, and when the spotted timing differs (with or without modules on the page)',
           b_spotted == 'binds' and b_plain == 'binds' and b_edited.startswith('refused')
           and b_gone.startswith('refused') and b_plain_moved.startswith('refused'),
           f'spotted={b_spotted}; no modules={b_plain}; edited={b_edited}; gone={b_gone}; moved={b_plain_moved}')

    # what the changelog says of a 2.3.0 receipt is these rules: round 6 still said it bound "only when its
    # cues_sha256 and any recorded modules match", which a byte-edited list proven by its modules contradicts
    changelog = scripts.parents[2] / 'CHANGELOG.md'
    if changelog.is_file():
        entry = ' '.join(changelog.read_text(encoding='utf-8').split('\n## 2.3.0')[0].split())
        record('fixes231 AG: the changelog says a 2.3.0 receipt binds through its recorded modules or the very cues.json '
               'it names, as project.py does, and nowhere that it needs its cues_sha256 to match',
               'binds only when its `cues_sha256`' not in entry and 'its recorded timing modules, still on disk and '
               'holding that timing' in entry and 'the very `cues.json` it names' in entry, entry[:0] or 'checked')



AH_NAMES = {
    'accented': 'caf' + chr(0xe9) + ' ' + chr(0xe9) + 'lan',
    'CJK': chr(0x65e5) + chr(0x672c) + chr(0x8a9e) + ' film',
    'emoji': 'emoji ' + chr(0x1f3ac) + ' film',
}
AH_FILM = GOOD_FILM.lstrip().replace("size: [640, 360]", "size: [320, 180]")
# gate 3: a folder whose UTF-8 bytes hold ones cp1252 cannot decode (0x81 in Á and the emoji, 0x9d in 東); the
# names above happen to avoid them, which is why a strict locale read of ffprobe's output had passed them
AH_NAMES['cp1252-undecodable'] = chr(0xc1) + 'rbol ' + chr(0x6771) + chr(0x4eac) + ' ' + chr(0x1f601)


def _ah_media(root, run, ffmpeg, bad):
    """The scripts that read ffprobe or ffmpeg as text (map.py add, tighten.py --silence-only, check.py --file with
    --captions, compare_versions.py, frame_sheet.py, motion_scan.py) on a valid clip and an unreadable file in ROOT:
    no traceback, the valid one done, the unreadable one refused in words with exit 2. check.py compares the captions
    with the speech where the speech model is installed (transcribe.py had died reading ffprobe, and the comparison
    was skipped as 'could not run'); without the model that item says the model is missing, which is not a failure."""
    media = root / 'media'
    media.mkdir(exist_ok=True)
    valid, broken, srt = media / 'clip.mp4', media / 'broken.mp4', media / 'clip.srt'
    # a tone and then silence, so tighten.py has a pause to measure
    made = subprocess.run([ffmpeg, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=4', '-f', 'lavfi',
                           '-i', 'sine=f=440:d=1.5,apad=whole_dur=4', '-shortest', '-c:v', 'libx264', '-pix_fmt',
                           'yuv420p', '-c:a', 'aac', str(valid)], capture_output=True, text=True, encoding='utf-8',
                          errors='replace')
    if made.returncode:
        bad.append(f'the clip could not be made: {made.stderr[-200:]}')
        return
    broken.write_bytes(b'not a video\n' * 200)
    _write_lf(srt, '1\n00:00:00,500 --> 00:00:01,500\nHello there\n')
    for label, f, ok in (('valid', valid, None), ('unreadable', broken, (2,))):
        run(f'map.py add {label}', 'map.py', 'add', root, f, '--role', 'broll', ok=ok or (0,))
        run(f'tighten.py --silence-only {label}', 'tighten.py', f, '--silence-only', '--out',
            media / f'{label}-tight.mp4', ok=ok or (0, 1))
        code, out = run(f'check.py --file --captions {label}', 'check.py', '--file', f, '--captions', srt,
                        ok=ok or (0, 1))
        if label == 'valid' and 'could not run' in out:   # transcribe.py had died reading ffprobe: a silent skip
            bad.append('check.py --file --captions: the speech comparison could not run: '
                       + next((line.strip() for line in out.splitlines() if 'could not run' in line), '')[:160])
        run(f'compare_versions.py {label}', 'compare_versions.py', f, valid, ok=ok or (0,))
        run(f'frame_sheet.py {label}', 'frame_sheet.py', f, '--out', media / f'sheet-{label}.png', '--every', '1',
            ok=ok or (0,))
        run(f'motion_scan.py {label}', 'motion_scan.py', f, ok=ok or (0, 1))


def _ah_run(scripts, script, *args, env, to_file=None):
    """(exit, output) of a script run as a command with -I, its output bytes decoded as UTF-8 (what safe_output
    writes when the output is not a console)."""
    cmd = [sys.executable, '-I', str(scripts / script), *map(str, args)]
    if to_file is not None:
        with open(to_file, 'wb') as fh:
            r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env=env, timeout=900)
        return r.returncode, Path(to_file).read_bytes().decode('utf-8', errors='replace') + r.stderr.decode(
            'utf-8', errors='replace')
    r = subprocess.run(cmd, capture_output=True, env=env, timeout=900)
    return r.returncode, (r.stdout + r.stderr).decode('utf-8', errors='replace')


def case_AH(tool, record, j, scripts, skip=None):
    """AH: a project and film in a folder named with accented, CJK or emoji characters go through every script that
    calls another (new_film, look.py world-sheet, film_check.py and the cue export it runs, cue_list.py codegen,
    freeze and scan, film_render.py, project.py add-version with a receipt and with --render, check.py, pack.py and
    record, setup.py) with Python not in UTF-8 mode: no traceback, the right exit codes, the folder named right in
    what is printed and written. A script printing a path to a piped cp1252 stream had crashed."""
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONUTF8', 'PYTHONIOENCODING')}
    ffmpeg = shutil.which('ffmpeg')
    browser = None
    for label, name in AH_NAMES.items():
        steps, bad = {}, []
        root = Path(j('fix231_ah', label)) / name
        root.parent.mkdir(parents=True, exist_ok=True)

        def run(step, script, *args, ok=(0,), to_file=None, extra_env=None, must_name=False):
            code, out = _ah_run(scripts, script, *args, env=dict(env, **(extra_env or {})), to_file=to_file)
            steps[step] = code
            if 'Traceback' in out or chr(0xc3) in out or chr(0xfffd) in out or code not in ok \
                    or (must_name and name not in out):
                bad.append(f'{step}: exit {code}: {out.strip()[-160:]!r}')
            return code, out

        run('project init', 'project.py', 'init', root, '--title', 'Paths ' + label, must_name=True)
        film = root / 'film'
        run('new_film', 'new_film.py', film, must_name=True)
        _write_lf(film / 'film.js', AH_FILM)
        _write_lf(film / 'gates.json', '{"world_sheet": "required", "typography": "required"}\n')
        run('new_film to a file', 'new_film.py', film, ok=(0, 1), to_file=root.parent / 'new_film.out')
        run('look.py world-sheet', 'look.py', 'world-sheet', root, must_name=True)
        code, out = run('film_check.py', 'film_check.py', film, '--size', '320x180', ok=(0, 2))
        if code == 2 and _no_browser(code, out):
            browser = False
            bad = [b for b in bad if not b.startswith('film_check.py')]
            steps['film_check.py'] = 'no browser'
        else:
            browser = True
            if code != 0:
                bad.append(f'film_check.py: exit {code}')
        if browser:
            run('cue_list.py codegen', 'cue_list.py', 'codegen', film / 'cues.json', '--json')
            for step, args in (('cue_list.py freeze --json', ('freeze', film, '--json', '--offline')),
                               ('cue_list.py scan --json', ('scan', film, film / 'film.js', '--json'))):
                code, out = run(step, 'cue_list.py', *args)
                try:
                    doc = json.JSONDecoder().raw_decode(out[out.index('{'):])[0] if '{' in out else None
                    if step.startswith('cue_list.py freeze') and not (doc and (film / str(doc.get('copy'))).is_dir()):
                        bad.append(f'{step}: the frozen copy it names is not in the folder')
                except ValueError as error:
                    bad.append(f'{step}: not JSON ({error})')
            render = root / 'renders' / 'v.mp4'
            run('film_render.py', 'film_render.py', film, '--cues', film / 'cues.json', '--preview', '--out', render,
                must_name=True)
            run('add-version --receipt', 'project.py', 'add-version', root, '--cues', film / 'cues.json', '--file',
                render, '--receipt', str(render) + '.manifest.json', must_name=False)
            cmd = (f'"{sys.executable}" -I "{scripts / "film_render.py"}" {{page}} --preview --out {{out}}')
            run('add-version --render', 'project.py', 'add-version', root, '--cues', film / 'cues.json', '--render',
                cmd, '--file', root / 'renders' / 'r.mp4', ok=(0, 1))
            run('check.py', 'check.py', root, '--version', 'v001', '--no-speech', ok=(0, 1))
            if ffmpeg and render.is_file():
                ref = root / 'ref.mp4'
                _synth_video(ffmpeg, ref, freq=554, color='0x241935', color2='0xc77dff', dur=2.0)
                code, out = run('pack.py', 'pack.py', render, '--against', ref, '--k', '1', '--k-alone', '1',
                                '--out', root / 'qa', '--reads', root / 'reads', '--json')
                key = json.JSONDecoder().raw_decode(out[out.index('{'):])[0] if code == 0 and '{' in out else {}
                if key and not Path(key.get('key_json', '')).is_file():
                    bad.append(f"pack.py: the key it names is not on disk: {key.get('key_json')!r}")
                if key:
                    ours = key['ours_letter']
                    other = next(x for x in key['letters'] if x != ours)
                    for fam in ('anthropic', 'google'):
                        _write_lf(root / f'{fam}.json', json.dumps(_json_reading(fam, overall_ranking=[ours, other],
                                  films={ours: _json_reading('x')['films']['A'], other: _json_reading('x')['films']['B']})))
                    run('pack.py record', 'pack.py', 'record', key['key_json'], '--lineup-a', root / 'anthropic.json',
                        '--lineup-b', root / 'google.json', '--out', root / 'qa' / 'blind-pack.json')
        appdata = root / 'appdata'
        appdata.mkdir(exist_ok=True)
        code, out = run('setup.py --json', 'setup.py', '--json', ok=(0, 1),
                        extra_env={'LOCALAPPDATA': str(appdata), 'XDG_DATA_HOME': str(appdata)})
        try:
            json.JSONDecoder().raw_decode(out[out.index('{'):])
        except ValueError as error:
            bad.append(f'setup.py --json: not JSON ({error})')
        if label == 'cp1252-undecodable' and ffmpeg:
            _ah_media(root, run, ffmpeg, bad)
        on_disk = [p for p in (root / 'status.json', film / 'film.js', root / 'refs' / 'world-sheet.png')
                   if not p.is_file()]
        if on_disk:
            bad.append(f'missing on disk: {[str(p) for p in on_disk]}')
        record(f'fixes231 AH: a project in a folder named with {label} characters runs through every script that '
               'calls another, Python not in UTF-8 mode: no traceback, right exits, the folder named right',
               not bad, f'{steps}; ' + '; '.join(bad[:3]))
    if browser is False and skip:
        skip('fixes231 AH: the browser steps (film_check.py, cue export, render, add-version, check, pack)',
             'Node, Chromium or Playwright missing', 1)



# Scripts that may run as a command without setting their output up first, each with why. Empty: every script with a
# __main__ block sets it up right after its docstring and standard-library imports.
SAFE_OUTPUT_EXCEPTIONS = {}


def _is_stdlib(name):
    """NAME (a top-level module) is part of Python itself: a module that cannot fail to import, nor print when it does."""
    names = getattr(sys, 'stdlib_module_names', None)
    if names is not None:
        return name in names
    import sysconfig   # Python 3.9: the module's file is in the standard library's folder, or it is built in
    if name in sys.builtin_module_names or name == '__future__':
        return True
    spec = importlib.util.find_spec(name)
    origin = str(getattr(spec, 'origin', '') or '')
    stdlib = str(Path(sysconfig.get_paths()['stdlib']).resolve())
    return bool(origin) and str(Path(origin).resolve()).startswith(stdlib) and 'site-packages' not in origin


def _output_setup_index(tree):
    """The index in TREE's body of the block that sets output up (an `if __name__ == '__main__'` whose body
    reconfigures sys.stdout and sys.stderr), or None."""
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Name) \
                and node.test.left.id == '__name__' and 'reconfigure' in ast.unparse(node):
            return i
    return None


def _script_readers(tree, source):
    """Calls in TREE that run one of the skill's scripts (sys.executable or a .py path) and read its output as text,
    with (line, whether they decode UTF-8)."""
    found = []
    # a command held in a variable is read from that variable's assignments in the same function
    scopes = {}
    for scope in ast.walk(tree):
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for inner in ast.walk(scope):
                scopes.setdefault(id(inner), scope)

    def command_text(call):
        first = call.args[0]
        text = ast.get_source_segment(source, first) or ''
        names = {n.id for n in ast.walk(first) if isinstance(n, ast.Name)}
        scope = scopes.get(id(call), tree)
        for node in ast.walk(scope):
            if isinstance(node, (ast.Assign, ast.AugAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id in names for t in targets):
                    text += ' ' + (ast.get_source_segment(source, node.value) or '')
        return text

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
        if name not in ('run', 'Popen', 'check_output'):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        texty = any(k in kw and not (isinstance(kw[k], ast.Constant) and kw[k].value in (False, None))
                    for k in ('text', 'universal_newlines'))
        child = command_text(node)
        if texty and ('.py' in child or 'sys.executable' in child or "'-I'" in child):
            enc = kw.get('encoding')
            found.append((node.lineno, isinstance(enc, ast.Constant) and str(enc.value).lower() in ('utf-8', 'utf8')))
    return found


def case_AI(tool, record, j, scripts, skip=None):
    """AI: every script in scripts/ that runs as a command sets its output up (UTF-8 to a pipe or file, a stand-in
    character on a console that cannot show one) before anything can print: the block follows only the docstring and
    standard-library imports, so a failed import's message (numpy or Pillow missing) is UTF-8 too. And every place a
    script or the self-test runs one of the scripts and reads its output as text decodes UTF-8. Round 6 had set the
    output up in main() only: a dependency message printed while importing went out in the code page, and a parent
    reading UTF-8 named the interpreter in "café élan" wrongly."""
    missing, early_writers, bad_readers = [], [], []
    for path in sorted(Path(scripts).glob('*.py')):
        if path.name in SAFE_OUTPUT_EXCEPTIONS:
            continue
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        if any(isinstance(n, ast.If) and isinstance(n.test, ast.Compare) and isinstance(n.test.left, ast.Name)
               and n.test.left.id == '__name__' for n in tree.body):
            at = _output_setup_index(tree)
            if at is None:
                missing.append(path.name)
            else:
                for node in tree.body[:at]:
                    if isinstance(node, ast.Expr) and isinstance(getattr(node, 'value', None), ast.Constant):
                        continue
                    modules = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                               [node.module or ''] if isinstance(node, ast.ImportFrom) and node.level == 0 else None)
                    if modules is None or not all(_is_stdlib(m.split('.')[0]) for m in modules):
                        early_writers.append(f'{path.name}:{node.lineno}')
                        break
    roots = [Path(scripts), Path(scripts) / 'selftest_cases', Path(scripts).parents[2] / '.github' / 'scripts']
    for root in roots:
        for path in sorted(root.glob('*.py')) if root.is_dir() else []:
            source = path.read_text(encoding='utf-8')
            for line, utf8 in _script_readers(ast.parse(source), source):
                if not utf8:
                    bad_readers.append(f'{path.name}:{line}')
    record('fixes231 AI: every script sets its output up before anything can print (only its docstring and '
           'standard-library imports come first), and every reader of a script decodes UTF-8',
           not missing and not early_writers and not bad_readers,
           f'missing: {missing}; something before the set-up: {early_writers}; readers not decoding UTF-8: '
           f'{bad_readers[:6]}; exceptions: {sorted(SAFE_OUTPUT_EXCEPTIONS)}')


# The names the scale filter takes for in_color_matrix and out_color_matrix in every FFmpeg the skill supports (5.1
# to 9), from FFmpeg's own libavfilter/vf_scale.c at n5.1.10, n6.1.6, n7.1.5, n8.0.1 and n9.0.2: 5.1 and 6.1 read a
# string by substring; 7.0 to 8.0 take only these named values; 9.0 adds bt470bg and bt2020nc. "bt2020nc" in the speed
# case's fixture failed on Ubuntu 26.04's FFmpeg 8.0.1 ("Undefined constant ... 'bt2020nc'").
SCALE_MATRIX_NAMES = ('bt601', 'bt470', 'smpte170m', 'bt709', 'fcc', 'smpte240m', 'bt2020')


def case_AJ(tool, record, j, scripts, skip=None):
    """AJ: every colour-matrix name given to FFmpeg's scale filter, in the scripts and in the self-test, is one every
    supported FFmpeg (5.1 to 9) takes, and no probed name is formatted into one (a stream's colour space goes to
    setparams, which takes every name ffprobe prints but "reserved"). Needs no FFmpeg: it reads the source."""
    import re
    roots = [Path(scripts), Path(scripts) / 'selftest_cases']
    found, bad = 0, []
    pattern = re.compile(r'(in|out)_color_matrix=([^:,\'"\s)]+)')
    for root in roots:
        for path in sorted(root.glob('*.py')):
            text = path.read_text(encoding='utf-8')
            for line_no, line in enumerate(text.splitlines(), 1):
                for side, name in pattern.findall(line):
                    if path.name == 'fixes231.py' and 'SCALE_MATRIX_NAMES' in line:
                        continue
                    found += 1
                    if '{' in name or '%' in name:
                        bad.append(f'{path.name}:{line_no}: a value formatted in ({name})')
                    elif name not in SCALE_MATRIX_NAMES and not (side == 'in' and name == 'auto'):
                        bad.append(f'{path.name}:{line_no}: {side}_color_matrix={name}')
    record('fixes231 AJ: every colour-matrix name given to the scale filter is one FFmpeg 5.1 to 9 all accept, and none '
           'is formatted from a probed value', found > 0 and not bad, f'{found} names; ' + '; '.join(bad[:4]))



def case_AK(tool, record, j, scripts, skip=None):
    """AK: a dependency message printed while a script is still importing (numpy or Pillow missing) names the
    interpreter exactly, in UTF-8, when that interpreter sits in a folder named with accented, CJK or emoji characters
    and a parent reads the output: the first-run reproductions of the round-6 review. Output set up in main() only had
    left these messages in the code page (CJK as backslash escapes), so the repair command named the folder wrongly."""
    import venv  # noqa: F401 - only to fail early where venv is missing
    env = {k: v for k, v in os.environ.items() if k not in ('PYTHONUTF8', 'PYTHONIOENCODING')}
    blocker = ("import importlib.abc, runpy, sys\n"
               "class Block(importlib.abc.MetaPathFinder):\n"
               " def find_spec(self, name, path=None, target=None):\n"
               "  if name == 'PIL' or name.startswith('PIL.'): raise ModuleNotFoundError(name, name=name)\n"
               "sys.meta_path.insert(0, Block())\n"
               "sys.argv = [sys.argv[1], '--help']\n"
               "runpy.run_path(sys.argv[0], run_name='__main__')\n")
    for label, name in AH_NAMES.items():
        bad = []
        bare = Path(j('fix231_ak', label)) / name / 'bare'
        made = subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', str(bare)], capture_output=True)
        with_numpy = Path(j('fix231_ak', label)) / name / 'site'
        made2 = subprocess.run([sys.executable, '-I', '-m', 'venv', '--without-pip', '--system-site-packages',
                                str(with_numpy)], capture_output=True)
        if made.returncode or made2.returncode:
            if skip:
                skip(f'fixes231 AK: dependency messages from an interpreter in a {label} folder',
                     'venv could not make an interpreter here')
            continue
        exe = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
        bare_py, site_py = bare / exe, with_numpy / exe

        def check(step, cmd, want, interpreter):
            r = subprocess.run(cmd, capture_output=True, env=env, timeout=300)
            try:
                text = (r.stdout + r.stderr).decode('utf-8')
            except UnicodeDecodeError as error:
                bad.append(f'{step}: not UTF-8 ({error.reason} at byte {error.start})')
                return
            named = str(interpreter).replace(chr(92), '/') in text.replace(chr(92), '/')
            if r.returncode != 2 or want not in text or '--install core' not in text or not named \
                    or 'Traceback' in text or chr(0xfffd) in text:
                bad.append(f'{step}: exit {r.returncode}, names the interpreter: {named}: {text.strip()[-140:]!r}')

        for script, args in (('map.py', ['--help']), ('captions.py', ['--help']), ('flash_scan.py', ['--help']),
                             ('blank_scan.py', ['--help']), ('selftest.py', ['--quick'])):
            check(f'{script} without numpy', [str(bare_py), '-I', str(scripts / script), *args], 'numpy', bare_py)
        try:
            import numpy  # noqa: F401
            has_numpy = True
        except ImportError:
            has_numpy = False
        if has_numpy:
            for script in ('map.py', 'captions.py', 'frame_sheet.py'):
                check(f'{script} without Pillow', [str(site_py), '-I', '-c', blocker, str(scripts / script)], 'Pillow',
                      site_py)
        record(f'fixes231 AK: with an interpreter in a {label} folder, a missing numpy or Pillow is named with that '
               'interpreter exactly, in UTF-8, by map, captions, flash_scan, blank_scan, frame_sheet and selftest',
               not bad, '; '.join(bad[:3]))


# The tools whose output is in the console's code page, not UTF-8: read in the locale encoding with stand-ins, with a
# comment saying so. Keyed by the file (relative to the repository) and the first word of the command.
CODE_PAGE_READERS = {
    ('skills/legible-film/scripts/selftest_cases/check.py', 'shell'): 'PowerShell (speech for a fixture)',
    ('skills/legible-film/scripts/selftest_cases/cut.py', 'shell'): 'PowerShell (speech for a fixture)',
    ('skills/legible-film/scripts/selftest_cases/grade.py', 'shell'): 'PowerShell (speech for a fixture)',
    ('skills/legible-film/scripts/selftest_cases/custody.py', "'cmd'"): 'cmd.exe mklink (a junction for a fixture)',
    ('evals/trigger_run.py', "'vm_stat'"): 'vm_stat (macOS free memory)',
}
# Byte reads decoded strictly on purpose: the case asserts the output is valid UTF-8.
STRICT_DECODES = {('skills/legible-film/scripts/selftest_cases/cut.py', 'proc.stdout')}
SUBPROCESS_CALLS = {'run', 'check_output', 'Popen', 'call', 'check_call', 'getoutput', 'getstatusoutput'}


def _encoding_problems(repo):
    """Every subprocess call in scripts/, selftest_cases/, evals/ and .github/scripts that reads text without stating
    encoding='utf-8' and errors='replace' (or, for a code-page tool, errors='replace' and the locale, said in a
    comment), and every .stdout or .stderr decoded strictly. A text read left to the locale's strict codec had ended
    map.py, transcribe.py and tighten.py in a reader-thread traceback on Windows for a folder whose UTF-8 bytes
    hold one cp1252 cannot decode (gate 3)."""
    problems, seen = [], 0
    roots = [repo / 'skills/legible-film/scripts', repo / 'evals', repo / '.github/scripts']
    for f in sorted(p for root in roots if root.is_dir() for p in root.rglob('*.py') if 'node_modules' not in p.parts):
        rel = f.relative_to(repo).as_posix()
        text = f.read_text(encoding='utf-8')
        lines = text.split('\n')
        tree = ast.parse(text)
        parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}

        def kw(call, name):
            return next((k.value for k in call.keywords if k.arg == name), None)

        def const(node, value):
            return isinstance(node, ast.Constant) and node.value == value

        def judge(call, where, head):
            """A problem with CALL's text read, or None. HEAD is the first word of the command it runs."""
            text_mode = any(kw(call, k) is not None and not const(kw(call, k), False) and not const(kw(call, k), None)
                            for k in ('text', 'universal_newlines')) or kw(call, 'encoding') is not None \
                or kw(call, 'errors') is not None
            if not text_mode:
                return None
            reader = CODE_PAGE_READERS.get((rel, head))
            if reader:
                said = ' '.join(lines[max(0, where - 3):where]).lower()
                if kw(call, 'encoding') is not None or not const(kw(call, 'errors'), 'replace') or (
                        'code page' not in said and 'locale encoding' not in said):
                    return f'{rel}:{where} {reader}: the locale encoding with errors=replace, said in a comment above'
                return None
            if not (const(kw(call, 'encoding'), 'utf-8') and const(kw(call, 'errors'), 'replace')):
                return f"{rel}:{where} reads {head} as text without encoding='utf-8', errors='replace'"
            return None

        def head_of(call):
            first = call.args[0] if call.args else kw(call, 'args')
            if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
                first = first.elts[0]
            elif isinstance(first, ast.BinOp) and isinstance(first.left, (ast.List, ast.Name)):
                first = first.left.elts[0] if isinstance(first.left, ast.List) and first.left.elts else first.left
            return ast.unparse(first) if first is not None else '?'

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == 'decode' and isinstance(fn.value, ast.Attribute)
                    and fn.value.attr in ('stdout', 'stderr')):
                if len(node.args) < 2 and kw(node, 'errors') is None and (rel, ast.unparse(fn.value)) not in STRICT_DECODES:
                    problems.append(f'{rel}:{node.lineno} decodes {ast.unparse(fn.value)} strictly')
                continue
            if not (isinstance(fn, ast.Attribute) and fn.attr in SUBPROCESS_CALLS and isinstance(fn.value, ast.Name)
                    and fn.value.id in ('subprocess', 'sp')):
                continue
            seen += 1
            if fn.attr in ('getoutput', 'getstatusoutput'):
                problems.append(f'{rel}:{node.lineno} {fn.attr} reads text in the locale strictly')
                continue
            if any(k.arg is None for k in node.keywords):
                # the call forwards **kwargs: judge each call of the function (or the class whose __init__ it is)
                func = node
                while func in parents and not isinstance(func, ast.FunctionDef):
                    func = parents[func]
                name = func.name if isinstance(func, ast.FunctionDef) else None
                if name == '__init__' and isinstance(parents.get(func), ast.ClassDef):
                    name = parents[func].name
                callers = [c for c in ast.walk(tree) if isinstance(c, ast.Call) and name and (
                    (isinstance(c.func, ast.Name) and c.func.id == name)
                    or (isinstance(c.func, ast.Attribute) and c.func.attr == name))]
                if not callers:
                    problems.append(f'{rel}:{node.lineno} forwards **kwargs from a function nothing here calls')
                problems += [p for p in (judge(c, c.lineno, head_of(c)) for c in callers) if p]
                continue
            problem = judge(node, node.lineno, head_of(node))
            if problem:
                problems.append(problem)
    return problems, seen


def case_AL(tool, record, j, scripts, skip=None):
    """AL: no text read of a child process is left to the locale's strict codec. ffmpeg, ffprobe, node and this
    skill's scripts write UTF-8, so a text read of them states encoding='utf-8', errors='replace'; the few system
    tools that write the console's code page (CODE_PAGE_READERS) keep the locale encoding, with errors='replace' and
    a comment. The walk finds every call itself: gate 3 listed some thirty it had found by hand."""
    repo = scripts.parents[2]
    problems, seen = _encoding_problems(repo)
    record('fixes231 AL: every subprocess text read in scripts/, selftest_cases/, evals/ and .github/scripts states '
           "encoding='utf-8', errors='replace', or is a listed code-page tool read in the locale with replace",
           seen > 100 and not problems, f'{seen} calls; ' + '; '.join(problems[:4]))


def case_AM(tool, record, j, scripts, skip=None):
    """AM: film_capture.mjs started through a linked folder runs. Node resolves the link for import.meta.url and not in
    process.argv[1], so its started-as-a-command test had failed, and under macOS's /var -> /private/var every export
    from an install in the temporary folder printed nothing and exited 0 (the browser run's isolated-install case).
    Imported as a module through the same link, it does not start."""
    node = shutil.which('node')
    if not node:
        if skip:
            skip('fixes231 AM: film_capture.mjs started through a linked folder', 'Node missing')
        return
    base = Path(j('fix231_am'))
    real, link = base / 'private-var', base / 'var'
    real.mkdir(parents=True, exist_ok=True)
    for name in ('film_capture.mjs', 'cue_gen.cjs'):
        shutil.copyfile(scripts / name, real / name)
    if not link.exists():
        if os.name == 'nt':   # a junction needs no privilege; its output is not read
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(real)], capture_output=True)
        else:
            os.symlink(real, link, target_is_directory=True)
    if not link.is_dir():
        record('fixes231 AM: a linked folder for film_capture.mjs could be made', False, str(link))
        return

    def node_run(*args):
        r = subprocess.run([node, *map(str, args)], capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=60)
        return r.returncode, r.stdout + r.stderr

    real_code, real_out = node_run(real / 'film_capture.mjs', '--help')
    link_code, link_out = node_run(link / 'film_capture.mjs', '--help')
    imported_code, imported_out = node_run('-e', 'import(process.argv[1]).then((m) => console.log("exports", '
                                           'Object.keys(m).length))', (link / 'film_capture.mjs').as_uri())
    help_line = 'Capture a local film page'
    record('fixes231 AM: film_capture.mjs started through a linked folder (as /var is on macOS) runs, as at its real '
           'path; imported through the link it does not start',
           real_code == 0 and help_line in real_out and link_code == 0 and help_line in link_out
           and imported_code == 0 and 'exports' in imported_out and help_line not in imported_out,
           f'real={real_code}:{real_out[:60]!r} link={link_code}:{link_out[:60]!r} import={imported_out[:60]!r}')


AN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>slow screenshot</title>
<style>html, body { margin: 0; width: 160px; height: 90px; overflow: hidden; background: #000; }
#bar { position: absolute; top: 20px; left: 0; width: 10px; height: 50px; background: #fff; }</style></head>
<body><div id="bar"></div>
<script>
// Once, after frame 3's paint has finished (two animation frames after its seek), the page's main thread is busy
// for 4 s, so the screenshot that follows cannot complete in less: the screenshot step, not the paint, is what waits.
let busy = false;
window.__lf = {
  ready: Promise.resolve(),
  info: () => ({title: 'slow screenshot', width: 160, height: 90, fps: 30, duration: 0.5, frames: 15, cuts: [],
                sections: [], cues: []}),
  frame: t => {},
  seek: t => {
    document.getElementById('bar').style.transform = 'translateX(' + (t * 200) + 'px)';
    if (t >= 0.1 && !busy) {
      busy = true;
      requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(() => {
        const end = performance.now() + 4000;
        while (performance.now() < end) {}
      }, 0)));
    }
  }
};
</script></body></html>
"""


def case_AN(tool, record, j, scripts, skip=None):
    """AN: a frame's screenshot is held to LF_FRAME_TIMEOUT_MS, the limit its seek and paint have, not
    Playwright's own 30 s; a screenshot that fails names the frame, its time in the film, how long the call waited and
    how many frames were captured before it. A page whose main thread is busy for 4 s after frame 3's paint renders
    with the limit at 8 s and fails at frame 3's screenshot with it at 1.5 s. The browser runs had each ended one
    render on a screenshot timeout that said none of this."""
    page = Path(j('fix231_an', 'page'))
    page.mkdir(parents=True, exist_ok=True)
    _write_lf(page / 'index.html', AN_PAGE)

    def render(limit, name):
        env = dict(os.environ, LF_FRAME_TIMEOUT_MS=str(limit))
        out = page.parent / f'{name}.mp4'
        r = subprocess.run([sys.executable, '-I', str(scripts / 'film_render.py'), str(page), '--out', str(out),
                            '--samples', '1', '--workers', '1', '--preview', '--force'], capture_output=True,
                           text=True, encoding='utf-8', errors='replace', env=env, timeout=600)
        return r.returncode, r.stdout + r.stderr, out

    code_ok, out_ok, made = render(8000, 'patient')
    # film_render.py stops at its own tool check, in its own words, before anything looks for a browser
    no_engine = code_ok == 2 and 'Node, FFmpeg and ffprobe are required' in out_ok
    if no_engine or (_no_browser(code_ok, out_ok) and 'screenshot of frame' not in out_ok):
        if skip:
            skip('fixes231 AN: a frame screenshot held to LF_FRAME_TIMEOUT_MS', 'Node, Chromium or Playwright missing')
        return
    code_low, out_low, _ = render(1500, 'impatient')
    m = re.search(r'the screenshot of frame (\d+) \(t=([0-9.]+) s, sample 1 of 1\) failed after (\d+) ms, with (\d+) '
                  r"frame\(s\) of this capture's frames 0 to 14 done before it \(limit 1500 ms, LF_FRAME_TIMEOUT_MS\)",
                  out_low)
    waited = int(m.group(3)) if m else None
    record('fixes231 AN: a frame screenshot honours LF_FRAME_TIMEOUT_MS (a 4 s stall renders at 8 s and fails at 1.5 s), '
           'and the failure names the frame, its time, the wait and the frames before it',
           code_ok == 0 and made.is_file() and code_low != 0 and m is not None and m.group(1) == '3'
           and m.group(2) == '0.100000' and m.group(4) == '3' and 1500 <= waited < 3900,
           f'at 8 s: exit {code_ok}; at 1.5 s: exit {code_low}: '
           + (m.group(0) if m else out_low.strip()[-400:]))


def run_fixes231_cases(tool, record, j, scripts_dir, skip=None):
    scripts = Path(scripts_dir)
    for case in (case_8, case_7, case_14, case_6, case_A, case_F, case_binding, case_J, case_9_sheet, case_9_gates,
                 case_5, case_DL, case_M, case_N, case_O, case_P, case_Q, case_R, case_S,
                 case_T, case_U, case_V, case_W, case_X, case_Y, case_Z, case_AA, case_AB, case_AC, case_AD, case_AE, case_AF, case_AG, case_AH, case_AI, case_AJ, case_AK, case_AL, case_AM, case_AN):
        case(tool, record, j, scripts, skip)
