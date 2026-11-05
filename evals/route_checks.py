#!/usr/bin/env python3
"""Route checks 16-20 of the reshape routing eval (SPEC section 13): their project fixtures and their scoring.

New code beside the frozen scorer: evals/routing_score.py, which scores prompts 1-15, is not changed; this module
reads the events and the score it produces. The checks run on a candidate variant only (one with paths/), since
2.0.0 lacks registered engine versions and listen.py.

Fixtures, built by the harness in the session's scratch project with the variant's own scripts before the session:

  engine-registered (19)  project.py init --path create --timeline page, a v2 plan cue list, and a stub master
                          registered with project.py add-version (which binds the plan to the master).
  paper (20)              project.py init, two short stub sources mapped with supplied word timings (no
                          transcription), a three-clip paper edit, and one cut.py render (version v001).

Checks, each a list of requirements with evidence; a check passes when every requirement is met:

  16  route create; engines.md read where it covers its Tesseract section; a frame written; a plan cue list
      written (JSON whose picture.kind is plan); no tsrct attempt; the final text names the Tesseract hand-off;
      and tsrct is not on PATH (else an infrastructure error, never a pass).
  17  route quick; listen.py transcript run; the final text calls what it reports hints.
  18  route quick; no paper edit (no cut.py draft, no paper-edit.md), no triad (no finding-the-story.md or
      story-and-score.md read).
  19  screen.py run; cut.py never run.
  20  exchange.py write run; the XML it wrote outside cuts/ parses, with the paper edit's clip count and its
      duration within one frame (both read from the version the fixture rendered).

Every check also needs no forbidden read or run from the cases file and no build or spend attempt.

Self-test: evals/selftest.py runs these checks on stub streams; it does not build the fixtures.
"""
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import routing_score  # noqa: E402  (read only: events, reads and file helpers)

TIMEOUT = 600


class FixtureError(RuntimeError):
    """A fixture could not be built with the variant's scripts: an infrastructure error, never a pass."""


def applies(skill_dir):
    """Route checks apply to a candidate variant only (it has paths/)."""
    return (Path(skill_dir) / 'paths').is_dir()


def run_script(skill_dir, script, *args, cwd):
    """Run one of the variant's scripts; refuse on exit 2 or more."""
    command = [sys.executable, '-I', str(Path(skill_dir) / 'scripts' / script), *map(str, args)]
    done = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=TIMEOUT)
    if done.returncode not in (0, 1):
        raise FixtureError(f"{script} {' '.join(map(str, args[:2]))} exited {done.returncode}: "
                           f"{(done.stdout + done.stderr).strip()[-600:]}")
    return done


def ffmpeg(*args):
    """Run FFmpeg quietly."""
    exe = shutil.which('ffmpeg')
    if not exe:
        raise FixtureError('ffmpeg is not on PATH')
    done = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-y', *map(str, args)], capture_output=True,
                          text=True, encoding='utf-8', errors='replace')
    if done.returncode:
        raise FixtureError(f'ffmpeg: {done.stderr.strip()[-400:]}')


def stub_av(path, seconds, tone, size='320x180', fps=25):
    """A small source with a moving test pattern and a tone."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg('-f', 'lavfi', '-i', f'testsrc2=size={size}:rate={fps}:duration={seconds}', '-f', 'lavfi', '-i',
           f'sine=frequency={tone}:sample_rate=48000:duration={seconds}', '-c:v', 'libx264', '-preset',
           'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ac', '2', '-shortest', path)


def build_engine_project(project, skill_dir):
    """Fixture 19: a create project whose timeline a page owns, with one master registered from a plan list."""
    run_script(skill_dir, 'project.py', 'init', project, '--title', 'Launch film', '--path', 'create',
               '--timeline', 'page', cwd=project)
    master = project / 'renders' / 'launch-film.mp4'
    stub_av(master, 6, 330, size='640x360', fps=25)
    plan = {
        'version': 'v2', 'clock': 'seconds from the first frame of the film', 'fps': '25',
        'provenance': 'plan', 'picture': {'kind': 'plan', 'sha256': None},
        'sections': [{'id': 'open', 'a': 0.0, 'b': 3.0, 'clock': 'music', 'label': 'what this is'},
                     {'id': 'turn', 'a': 3.0, 'b': 6.0, 'clock': 'music', 'label': 'what it does'}],
        'events': [{'id': 'turn-1', 't': 3.0, 'scale': 'turn', 'sync': 'attack', 'section': 'turn',
                    'decision': 'the cut lands on the downbeat', 'picture': 'cut to the product'}],
    }
    plan_path = project / 'film' / 'plan.json'
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, indent=1), encoding='utf-8', newline='\n')
    run_script(skill_dir, 'project.py', 'add-version', project, '--cues', plan_path, '--file', master, cwd=project)
    versions = sorted(p.name for p in (project / 'cuts').glob('v*') if p.is_dir())
    if not versions:
        raise FixtureError('add-version registered no version')
    return {'kind': 'engine-registered', 'version': versions[-1]}


def build_paper_project(project, skill_dir):
    """Fixture 20: a paper project with one rendered version; returns the version and its clip count and duration."""
    run_script(skill_dir, 'project.py', 'init', project, '--title', 'Interview cut', cwd=project)
    media = project / 'media'
    for number, tone in ((1, 500), (2, 700)):
        stub_av(media / f'interview {number}.mp4', 8, tone)
    run_script(skill_dir, 'map.py', 'add', project, media / 'interview 1.mp4', media / 'interview 2.mp4',
               '--role', 'interview', cwd=project)
    index = json.loads((project / 'map' / 'sources.json').read_text(encoding='utf-8'))
    spans = [(0.5, 0.9), (1.2, 1.6), (2.0, 2.4), (4.0, 4.4), (4.8, 5.2), (5.6, 6.0)]
    for number, source in enumerate(index['sources'], 1):
        alias = source['alias']
        rows = [{'id': f'{alias}-w{i + 1:06d}', 'text': f"{'ab'[number - 1]}{i}", 'start': a, 'end': b,
                 'estimated': False} for i, (a, b) in enumerate(spans)]
        folder = project / 'map' / alias
        folder.mkdir(exist_ok=True)
        transcript = {'version': 1, 'source': alias, 'words': rows,
                      'media': {'sha256': source['sha256'], 'audio_stream': source['audio']['index']}}
        (folder / 'words.json').write_text(json.dumps(transcript), encoding='utf-8', newline='\n')
    first, second = (s['alias'] for s in index['sources'][:2])
    film = ('---\ntitle: Interview cut\nsize: 320x180\nfps: 25\ncaptions: srt\n---\n'
            f'> {first} 0:00.30-0:02.70 a0 a1 a2\n'
            f'> {second} 0:00.30-0:02.70 b0 b1 b2\n'
            f'> {first} 0:03.40-0:06.30 a3 a4 a5\n')
    (project / 'film.md').write_text(film, encoding='utf-8', newline='\n')
    run_script(skill_dir, 'cut.py', 'render', project, cwd=project)
    versions = sorted(p.name for p in (project / 'cuts').glob('v*') if p.is_dir())
    if not versions:
        raise FixtureError('cut.py render made no version')
    clips, duration = version_shape(project / 'cuts' / versions[-1])
    return {'kind': 'paper', 'version': versions[-1], 'clips': clips, 'duration_s': duration}


def version_shape(version):
    """(clip count, duration in seconds) of a rendered paper version: the picture clips its edit.json lists and the
    duration its manifest.json records."""
    try:
        edit = json.loads((version / 'edit.json').read_text(encoding='utf-8'))
        manifest = json.loads((version / 'manifest.json').read_text(encoding='utf-8'))
        return len(edit['picture']), float(manifest['duration_s'])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FixtureError(f'no picture clip list and duration in {version}: {exc}') from exc


BUILDERS = {'engine-registered': build_engine_project, 'paper': build_paper_project}


def build_fixture(kind, project, skill_dir):
    """Build a route check's project fixture in the scratch project; returns what scoring needs to know about it."""
    if kind not in BUILDERS:
        raise FixtureError(f'unknown project fixture {kind!r}')
    return BUILDERS[kind](Path(project), skill_dir)


def tesseract_installed():
    """Where Tesseract's CLI is installed, on PATH or in its default install folders (the Windows installer puts it
    in %LOCALAPPDATA%\\Tesseract without adding it to PATH), or None."""
    on_path = shutil.which('tsrct')
    if on_path:
        return on_path
    import os
    homes = [Path(os.environ[v]) / 'Tesseract' for v in ('LOCALAPPDATA', 'XDG_DATA_HOME') if os.environ.get(v)]
    homes += [Path.home() / 'Library' / 'Application Support' / 'Tesseract', Path.home() / '.local' / 'share' / 'Tesseract']
    for home in homes:
        for found in [home / 'bin' / name for name in ('tsrct', 'tsrct.cmd', 'tsrct.exe')] + \
                sorted(home.glob('public-cli/*/bin/tsrct*')):
            if found.is_file():
                return str(found)
    return None


def environment(case):
    """An infrastructure problem with the session's environment for this check, or None."""
    if case['id'] == 'R16':
        found = tesseract_installed()
        if found:
            return f'Tesseract is installed ({found}); route check 16 needs an environment without it'
    return None


# ---------------------------------------------------------------- scoring

def shell_reads(command, rel):
    """Reads of one skill file in a shell command, split on ; && | only outside quotes (an awk or sed program can hold
    a ;): [(heading a filter looks for, or None)]. A read verb's segment that names the file is a read."""
    found = []
    name = rel.rsplit('/', 1)[-1]
    for segment in routing_score.segments(command):
        if routing_score.first_word(segment) not in routing_score.READ_VERBS and \
                routing_score.first_word(segment) not in ('select-string', 'rg', 'grep'):
            continue
        if not re.search(r'(?:^|[\s"\'/\\])' + re.escape(name) + r'(?:$|[\s"\'|;])', segment):
            continue
        wanted = re.search(r'\^?#{2,3}\s+([A-Za-z][^/|\'"$\\{};]*[A-Za-z0-9])', segment)
        if wanted:
            found.append(wanted.group(1).strip())
        elif routing_score.first_word(segment) in ('cat', 'type', 'get-content', 'gc', 'more', 'less', 'nl') and \
                not re.search(r'\|\s*(?:head|tail|select-object|sed|awk)\b|-TotalCount|-Head\b|-Tail\b', command, re.I):
            found.append(None)
    return found


def tsrct_runs(events):
    """Commands that run Tesseract's CLI: a segment whose verb is tsrct; looking it up (which, where, Get-Command,
    --version) is not a run."""
    runs = []
    for event in events:
        if event['kind'] != 'command':
            continue
        for segment in routing_score.segments(event['command']):
            verb = routing_score.first_word(segment)
            if re.match(r'^tsrct(?:-[a-z]+)?$', verb) and not routing_score.help_only(segment):
                runs.append(segment[:120])
    return runs


def forbidden_hits(case, score, events):
    """The frozen scorer's forbidden hits, except a hit on a bare command name (tsrct) when the command only looked it
    up: the frozen rule matches the word anywhere in a command."""
    hits = [f['hit'] for f in score['forbidden']]
    bare = {rule['run'] for rule in case.get('forbidden', []) if 'run' in rule and '.' not in rule['run']}
    if 'tsrct' in bare and not tsrct_runs(events):
        hits = [h for h in hits if not h.startswith('ran tsrct')]
    return hits


def covers_section(events, skill_dir, rel, heading):
    """Evidence that a read of a skill file showed a section: a whole read, a range over the heading, or a filter."""
    lines = routing_score.file_lines(skill_dir, rel)
    line = next((i + 1 for i, text in enumerate(lines) if routing_score.is_heading(text) and
                 text.lstrip('#').strip().lower().startswith(heading.lower())), None)
    for event in events:
        if event['kind'] == 'command':
            for wanted in shell_reads(event['command'], rel):
                if wanted is None:
                    return f'{rel} read whole in a shell command'
                if wanted.lower().startswith(heading.lower()):
                    return f'filtered read of {rel} for {heading}'
    for event in events:
        parts = []
        if event['kind'] == 'read' and routing_score.skill_relative(event.get('path')) == rel:
            parts.append((event.get('first'), event.get('count'), event.get('heading')))
        if event['kind'] == 'command':
            parts += [(f, c, h) for name, f, c, _, h in event.get('reads', []) if name == rel]
        for first, count, wanted in parts:
            if wanted and wanted.lower().startswith(heading.lower()):
                return f'filtered read of {rel} for {heading}'
            if first is None and count is None and not wanted:
                return f'{rel} read whole'
            start = first or 1
            if line and count and start <= line < start + count:
                return f'{rel} lines {start}-{start + count - 1} cover line {line}'
    return None


def plan_list_written(events):
    """A write of JSON whose picture.kind is plan (or a write the agent made with that content)."""
    for event in events:
        if event['kind'] != 'write' or event.get('denied'):
            continue
        try:
            doc = json.loads(event.get('content') or '')
        except ValueError:
            continue
        if isinstance(doc, dict) and (doc.get('picture') or {}).get('kind') == 'plan':
            return str(event.get('path'))
    return None


def written_xml(project, fixture):
    """XML files the session wrote in the project, outside cuts/ (version folders never change)."""
    project = Path(project)
    return [p for p in project.rglob('*.xml') if 'cuts' not in p.relative_to(project).parts and
            '.claude' not in p.parts and '.agents' not in p.parts]


def xml_shape(path):
    """(clip count on the first video track, sequence duration in seconds) of an FCP7 XML file."""
    root = ET.parse(path).getroot()
    sequence = root.find('.//sequence')
    if sequence is None:
        raise ValueError('no sequence')
    rate = sequence.find('rate')
    timebase = int(rate.findtext('timebase')) if rate is not None else 25
    ntsc = (rate.findtext('ntsc') or '').upper() == 'TRUE' if rate is not None else False
    fps = Fraction(timebase * 1000, 1001) if ntsc else Fraction(timebase)
    track = sequence.find('./media/video/track')
    clips = len(track.findall('clipitem')) if track is not None else 0
    duration = int(sequence.findtext('duration') or 0)
    return clips, float(duration / fps), float(1 / fps)


def check(case, events, score, project, fixture, skill_dir):
    """The route check's requirements with evidence, and its verdict."""
    rid = case['id']
    needs = []

    def need(what, met, evidence=None):
        needs.append({'requirement': what, 'met': bool(met), 'evidence': evidence})

    if rid in ('R16', 'R17', 'R18'):
        need(f"route {case['expected']}", score['route'] == case['expected'], score['route_evidence'])
    hits = forbidden_hits(case, score, events)
    need('no forbidden read or run', not hits, hits)
    need('no build or spend attempt', score['build_attempts'] == 0, score['attempts'])
    runs = [(s, sub) for e in events if e['kind'] == 'command' and not e.get('denied')
            for s, sub, _ in e.get('runs', [])]
    finals = ' '.join(routing_score.final_texts(events).values()).lower()
    if rid == 'R16':
        need('engines.md read over its Tesseract section',
             covers_section(events, skill_dir, 'references/engines.md', 'Tesseract'),
             covers_section(events, skill_dir, 'references/engines.md', 'Tesseract'))
        need('a frame written', score['frame']['frame_writes'], score['frame']['frame_writes'][:1])
        need('a plan cue list written', plan_list_written(events), plan_list_written(events))
        tsrct = tsrct_runs(events)
        need('stops at the hand-off: no tsrct run or attempt', not tsrct, tsrct)
        need('names the Tesseract hand-off', 'tesseract' in finals and re.search(r'hand', finals), None)
    elif rid == 'R17':
        need('listen.py transcript run', ('listen.py', 'transcript') in runs, None)
        need('reports hints as hints', 'hint' in finals, None)
    elif rid == 'R18':
        pass  # route quick, and the forbidden reads and runs above: no paper edit, no triad
    elif rid == 'R19':
        need('screen.py run', any(s == 'screen.py' for s, _ in runs), None)
        need('cut.py never run', not any(s == 'cut.py' for s, _ in runs) and not any('cut.py' in h for h in hits),
             None)
    elif rid == 'R20':
        need('exchange.py write run', ('exchange.py', 'write') in runs, None)
        files = written_xml(project, fixture) if project else []
        shapes, problems = [], []
        for path in files:
            try:
                shapes.append((path, *xml_shape(path)))
            except (ET.ParseError, ValueError, TypeError) as exc:
                problems.append(f'{path.name}: {exc}')
        match = [p for p, clips, seconds, frame in shapes if fixture and clips == fixture['clips'] and
                 abs(seconds - fixture['duration_s']) <= frame + 1e-9]
        need('the XML it wrote parses with the paper edit\'s clip count and duration', match,
             {'expected': fixture and {'clips': fixture['clips'], 'duration_s': fixture['duration_s']},
              'found': [{'file': p.name, 'clips': c, 'duration_s': round(s, 3)} for p, c, s, _ in shapes],
              'unparsed': problems})
    return {'check': rid, 'passed': all(n['met'] for n in needs), 'requirements': needs}
