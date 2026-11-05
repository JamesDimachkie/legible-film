#!/usr/bin/env python3
"""Score one planning session of the reshape routing eval from its event stream, not from its answer text.

Used by `trigger_run.py routing`. A session is first normalised into events (skill loads, file reads, searches,
commands, writes, the agent's text, the scripted reply and the end of each exchange), from Claude Code's
stream JSON or from `codex exec --json`. Scoring then reads, in order:

- the route: for a candidate skill (it has `paths/`), the first `paths/*.md` read; for the 2.0.0 baseline, the
  first path-mapped file read or run, and when that file is `references/recipes.md`, the recipe the read covers
  (a partial read) or else the first recipe heading, then the first mapped script, the agent names after that
  read. A session that loads the skill and resolves to no path is unscored. A session that never loads the
  skill routes to `no-skill`;
- every skill file read before the first action, with its words (whitespace-separated, as `wc -w`). An action is
  a write, a skill script run (other than `--help`), any command that is not a read, list, search or probe, or
  the end of the first exchange (the agent speaking to the person);
- the first question, the frame fields it asks for, and whether a frame was written (keyword evidence, kept with
  the text so a person can audit it);
- forbidden reads and runs, required ones (route checks), and build, spend, network, install and heavy attempts.

Exit codes when run directly (`python evals/routing_score.py SESSION.json`, a rescoring aid): 0 scored, 2 could
not run.
"""
import ast
import json
import re
import shlex
import sys
from pathlib import Path

SKILL = 'legible-film'
READ_VERBS = {'cat', 'type', 'head', 'tail', 'sed', 'less', 'more', 'get-content', 'gc', 'awk', 'nl'}
LOOK_VERBS = READ_VERBS | {'ls', 'dir', 'get-childitem', 'gci', 'find', 'rg', 'grep', 'select-string', 'wc',
                           'ffprobe', 'mediainfo', 'pwd', 'echo', 'which', 'where', 'where.exe', 'test-path',
                           'resolve-path', 'get-item', 'stat', 'file', 'tree', 'cd', 'set-location', 'write-output',
                           'measure-object', 'select-object', 'sort-object', 'format-list', 'out-string', 'true',
                           'command', 'get-command', 'printf', 'cut'}
SCRIPT = re.compile(r'([A-Za-z0-9_\-]+\.(?:py|mjs))\b')
SKILL_FILE = re.compile(r'(SKILL\.md|(?:references|paths)[/\\][A-Za-z0-9_.\-]+\.md|scripts[/\\][A-Za-z0-9_.\-]+\.(?:py|mjs))')


# ---------------------------------------------------------------- paths and words

def skill_relative(path):
    """The part of a path inside the skill folder (`references/kit.md`), or None."""
    text = str(path or '').replace('\\', '/')
    marker = '/' + SKILL + '/'
    if marker in text:
        rest = text.rsplit(marker, 1)[1]
        return rest if SKILL_FILE.fullmatch(rest) else None
    text = text.lstrip('./')
    return text if SKILL_FILE.fullmatch(text) else None


def file_lines(skill_dir, rel):
    """Lines of a skill file in the staged variant, or an empty list."""
    try:
        return (Path(skill_dir) / rel).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []


def words_in(skill_dir, rel, first=None, count=None):
    """Words in a skill file, or in the lines [first, first + count) (1-based first line)."""
    lines = file_lines(skill_dir, rel)
    start = max((first or 1) - 1, 0)
    end = len(lines) if count is None else start + count
    return sum(len(line.split()) for line in lines[start:end])


HEAD_LEAD = 10


def is_heading(line, only=None):
    """A `## ` or `### ` heading line; with `only`, one whose title is in that set."""
    if not (line.startswith('## ') or line.startswith('### ')):
        return False
    return only is None or line.lstrip('#').strip() in only


def heading_at(skill_dir, rel, first, count, only=None):
    """The recipe heading a partial read is on: a heading within its first lines (an agent often starts a read a
    few lines above the heading it found), else the section its first line falls in. A read that starts in the
    preamble with no heading near its start (the top of the file) is on no section. With `only`, sub-headings inside
    a recipe are skipped and only those titles count."""
    lines = file_lines(skill_dir, rel)
    start = max((first or 1) - 1, 0)
    end = len(lines) if count is None else min(len(lines), start + count)
    for i in range(start, min(end, start + HEAD_LEAD)):
        if is_heading(lines[i], only):
            return lines[i].lstrip('#').strip()
    for i in range(min(start, len(lines) - 1), -1, -1):
        if is_heading(lines[i], only):
            return lines[i].lstrip('#').strip()
    return None


# ---------------------------------------------------------------- commands

SHELLS = {'pwsh', 'pwsh.exe', 'powershell', 'powershell.exe', 'bash', 'bash.exe', 'sh', 'zsh'}


def shell_script(command):
    """The script a shell wrapper runs, decoded as the shell would (Codex quotes it for a POSIX shell, splicing
    quotes as '...'\"'\"'...'), or None when the command is not a wrapper or cannot be split."""
    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return None
    if len(parts) < 3 or parts[0].replace('\\', '/').rsplit('/', 1)[-1].lower() not in SHELLS:
        return None
    for i, part in enumerate(parts[1:-1], 1):
        if part.lower() in ('-command', '-c', '-lc'):
            return ' '.join(parts[i + 1:])
    return None


def unwrap(command):
    """The command a shell wrapper runs (`pwsh -Command '...'`, `bash -lc '...'`), unwrapping nested wrappers too
    (Codex sometimes runs a second pwsh -Command inside its own), or the command itself."""
    for _ in range(3):
        decoded = shell_script(command)
        if decoded is not None:
            command = re.sub(r'^try \{ \[Console\]::OutputEncoding=[^}]*\} catch \{\}\s*', '', decoded)
            continue
        # The closing quote may differ from the opening one: Codex splices quoted pieces ("...'...').
        match = re.search(r'-Command\s+(["\'])(.*?)["\']?\s*$', command, re.S)
        if match:
            command = re.sub(r'^try \{ \[Console\]::OutputEncoding=[^}]*\} catch \{\}\s*', '', match.group(2))
            continue
        match = re.search(r'(?:^|[\s"\'/\\])(?:bash|sh|zsh)(?:\.exe)?["\']?\s+-l?c\s+(["\'])(.*)\1\s*$', command, re.S)
        if not match:
            break
        command = match.group(2)
    return command


def segments(command):
    """Pipeline and sequence parts of a shell command, split on && || ; | and newlines outside quotes."""
    parts, current, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            if ch == quote:
                quote = None
            current.append(ch)
        elif ch in '"\'':
            quote = ch
            current.append(ch)
        elif command.startswith(('&&', '||'), i):
            parts.append(''.join(current))
            current = []
            i += 1
        elif ch in ';|\n':
            parts.append(''.join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    parts.append(''.join(current))
    return [part.strip() for part in parts if part.strip()]


def first_word(segment):
    """The verb of one command segment, lower case, without its folder, quotes, `.exe` or a leading assignment."""
    text = re.sub(r'^(?:do|then|else)\s+', '', segment.strip())  # the body of a shell loop or if
    text = re.sub(r'^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+', '', text)
    text = re.sub(r'^\$[A-Za-z_]\w*\s*=\s*', '', text).lstrip('(&@ ')
    match = re.match(r'"([^"]*)"|\'([^\']*)\'|(\S+)', text)
    if not match:
        return ''
    word = next(g for g in match.groups() if g is not None)
    word = word.replace('\\', '/').rsplit('/', 1)[-1].lower()
    return word[:-4] if word.endswith('.exe') else word


INTERPRETER = re.compile(r'^(?:python[\d.]*|py|pythonw|node|uv|\$py|\$\{py\}|\$python)$')


REDIRECT = re.compile(r'^\d*(?:>{1,2}|<)&?\d*$')


SUBCOMMAND = re.compile(r'^[A-Za-z][A-Za-z0-9_-]*$')


def help_request(tokens):
    """True when a script's arguments only ask for its help (--help or -h), or a subcommand's help (`run --help`),
    with or without shell redirects such as 2>&1, > FILE or 2>/dev/null."""
    kept, skip = [], False
    for token in tokens:
        if skip:
            skip = False
            continue
        if REDIRECT.match(token):
            skip = not re.search(r'&\d*$', token)  # a bare > or 2> takes the next token as its target
            continue
        if re.match(r'^\d*>{1,2}\S+$', token):  # >out.txt, 2>/dev/null
            continue
        kept.append(token)
    if len(kept) >= 2 and SUBCOMMAND.match(kept[0]):
        kept = kept[1:]
    return bool(kept) and all(t in ('--help', '-h') for t in kept)


PYTHON = re.compile(r'^(?:python[\d.]*|py|pythonw|\$py|\$\{py\}|\$python)$')
PROBE_CALLS = {'print', 'bool', 'str', 'repr', 'len', 'sorted', 'list', 'dict', 'set', 'tuple', 'getattr', 'hasattr',
               'isinstance', 'type', 'find_spec', 'version', '__import__'}


def _probe_safe(node):
    """Every call inside an expression is a module look-up or a plain conversion."""
    for sub in ast.walk(node):
        if isinstance(sub, (ast.Lambda, ast.Await, ast.Yield, ast.YieldFrom, ast.NamedExpr)):
            return False
        if isinstance(sub, ast.Call):
            func = sub.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name not in PROBE_CALLS:
                return False
    return True


def import_probe(segment):
    """True when a segment runs Python only to import or look up modules and print what it finds, such as
    `python -c "import torch; print(torch.__version__)"` or a `find_spec` check: a look at the environment, not a
    run of what it imports. The code must parse, and hold only imports, assignments and print calls whose every call
    is a look-up (find_spec, version, bool, str, getattr and the like)."""
    if not PYTHON.match(first_word(segment)):
        return False
    match = re.search(r'(?:^|\s)-c\s+(["\'])(.*)\1((?:\s+\d*>{1,2}&?\S*)*)\s*$', segment.strip(), re.S)
    if not match:
        return False
    try:
        tree = ast.parse(match.group(2))
    except (SyntaxError, ValueError):
        return False
    for statement in tree.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(statement, ast.Assign) and _probe_safe(statement.value):
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and \
                isinstance(statement.value.func, ast.Name) and statement.value.func.id == 'print' and \
                _probe_safe(statement.value):
            continue
        return False
    return bool(tree.body)


def script_runs(command):
    """Each skill script a command runs: [(script, subcommand or None, arguments text)]. Asking a script for its
    --help or -h, with or without redirects, is a look, not a run."""
    runs = []
    for segment in segments(command):
        verb = first_word(segment)
        if not (INTERPRETER.match(verb) or verb.endswith(('.py', '.mjs'))):
            continue
        for match in SCRIPT.finditer(segment):
            args = segment[match.end():].strip().strip('"\'').strip()
            tokens = [t.strip('"\'') for t in args.split()]
            if help_request(tokens):
                break
            sub = next((t for t in tokens if not t.startswith('-')), None)
            runs.append((match.group(1), sub, args))
            break
    return runs


HELP = {'--help', '-h', 'help', '--version', '-v', '-V', '--doctor'}


def help_only(segment):
    """True when a command segment only asks a script or tool for its help, version or environment check
    (`make_film.py --doctor`), or a subcommand for its help (`map.py run --help`); shell redirections such as 2>&1
    are ignored."""
    tokens = [t.strip('"\'') for t in segment.split() if not re.match(r'^\d*>{1,2}&?\d*\S*$', t)]
    at = next((i for i, t in enumerate(tokens) if t.endswith(('.py', '.mjs'))), 0)
    rest = tokens[at + 1:]
    if len(rest) >= 2 and SUBCOMMAND.match(rest[0]) and all(t in ('--help', '-h') for t in rest[1:]):
        return True
    return bool(rest) and all(t in HELP for t in rest)


ASSIGN = re.compile(r'^\$?(?P<name>[A-Za-z_]\w*)\s*=\s*(?P<q>["\'])(?P<value>[^"\']*)(?P=q)\s*$')
FETCH = re.compile(r'(?:^|[\s(&{;|=])(?:curl(?:\.exe)?|wget|invoke-webrequest|iwr|invoke-restmethod|irm)\b', re.I)
URL = re.compile(r'https?://[^\s\'"`)]+', re.I)
DOC_URL = re.compile(r'^https?://(?:(?:docs?|developers?|help|support|learn)\.[^/\s]+|[^/\s]+/(?:[^?#\s]*/)?'
                     r'(?:docs?|guides?|documentation|pricing|plans|terms(?:-of-use)?|legal|licen[cs]e(?:-summary)?)'
                     r'(?:[/?#.]|$))', re.I)
SEND = re.compile(r'(?:^|\s)(?:-X\s*(?:POST|PUT|PATCH|DELETE)\b|--request\s+(?:POST|PUT|PATCH|DELETE)\b|-d\b|'
                  r'--data(?:-\w+)?\b|-F\b|--form\b|-T\b|--upload-file\b|-Method\s+[\'"]?(?:Post|Put|Patch|Delete)\b|'
                  r'-Body\b|-InFile\b)', re.I)
CREDENTIALS = re.compile(r'authorization|bearer\b|api[-_]?key|-u\s+\S+:|--user\b', re.I)
CATALOG = re.compile(r'\b(?:models?|catalog|voices?|presets?)\s+(?:search|list|ls|find|info|show)\b', re.I)
MAKES = re.compile(r'\b(?:generate|create|synthesi[sz]e|render|submit|upload)\b', re.I)


def lookup_only(segment):
    """True when a segment only reads about a service: a GET or HEAD of a documentation, guide or pricing page with
    no body and no credentials, or a search of a model, voice or preset catalog. Such a step is network at most,
    never spend."""
    if CATALOG.search(segment) and not MAKES.search(segment):
        return True
    if not FETCH.search(segment):
        return False
    urls = URL.findall(segment)
    return bool(urls) and all(DOC_URL.match(u) for u in urls) and not SEND.search(segment) and \
        not CREDENTIALS.search(segment)


def classify(command, classes):
    """Attempt classes a command matches, from the frozen patterns in the cases file. Only parts that run something
    count: a read, list, search or probe that merely names a script or service, and a help request, never match.
    Spend is judged part by part: a string assigned to a variable runs nothing, but its value stands in for the
    variable in later parts, and a part that only reads a service's documentation or pricing page, or searches its
    catalog, is not spend (lookup_only)."""
    kept = [s for s in segments(command) if not help_only(s) and not is_look(s)]
    text = ' ; '.join(kept)
    found = []
    assigned = {}
    spend_parts = []
    for part in kept:
        match = ASSIGN.match(part)
        if match:
            assigned[match.group('name')] = match.group('value')
            continue
        for name, value in assigned.items():
            part = re.sub(r'\$\{?' + re.escape(name) + r'\}?(?!\w)', lambda _: value, part)
        if not lookup_only(part):
            spend_parts.append(part)
    for name, patterns in classes.items():
        haystack = ' ; '.join(spend_parts) if name == 'spend' else text
        if any(re.search(p, haystack, re.I) for p in patterns):
            found.append(name)
    return found


def skill_folder(statement, inside):
    """After a `cd`, the folder inside the skill the shell is in ('' for its root), or None outside it."""
    target = statement.split(None, 1)[1].strip().strip('"\'').replace('\\', '/').rstrip('/') \
        if len(statement.split()) > 1 else ''
    marker = '/' + SKILL
    if marker in '/' + target:
        rest = ('/' + target).rsplit(marker, 1)[1].strip('/')
        return rest if rest in ('', 'references', 'scripts', 'paths') else None
    if inside is not None:
        if target == '..':
            return '' if inside else None
        if inside == '' and target in ('references', 'scripts', 'paths'):
            return target
    return None


def command_reads(command):
    """Skill files a command reads, with what part when it can be told:
    [(rel, first line, line count, approximate, heading a filtered read looks for)]."""
    reads = []
    inside = None
    held = {}
    loaded = {}
    statements = [s.strip() for s in re.split(r'&&|\|\||;|\n', command) if s.strip()]
    for statement in statements:
        assigned = re.match(r'^\$([A-Za-z_]\w*)\s*=\s*["\']([^"\']+)["\']\s*$', statement)
        if assigned and skill_relative(assigned.group(2)):
            held[assigned.group(1).lower()] = assigned.group(2)
            continue
        # $t = Get-Content FILE shows nothing; what a later use of $t shows is the read (below).
        content = re.match(r'^\$([A-Za-z_]\w*)\s*=\s*(?:Get-Content|gc|cat|type)\b(.*)$', statement, re.I)
        if content:
            source = [m.group(0) for m in re.finditer(r'[^\s"\']*' + SKILL_FILE.pattern, content.group(2))]
            source += [held[v.lower()] for v in re.findall(r'\$([A-Za-z_]\w*)', content.group(2)) if v.lower() in held]
            if source and skill_relative(source[0]):
                loaded[content.group(1).lower()] = skill_relative(source[0])
            continue
        verb = first_word(statement.split('|')[0])
        if verb in ('cd', 'set-location', 'pushd'):
            inside = skill_folder(statement, inside)
            continue
        context = re.search(r'-Context\s+\d+\s*,\s*(\d+)|(?:-A|-C|--after-context|--context)[ =]?(\d+)', statement)
        searching = verb in ('rg', 'grep', 'select-string')
        if verb not in READ_VERBS and not (searching and context):
            continue
        names = [skill_relative(m.group(0)) or skill_relative(m.group(1))
                 for m in re.finditer(r'[^\s"\']*' + SKILL_FILE.pattern, statement)]
        names += [skill_relative(held[v.lower()]) for v in re.findall(r'\$([A-Za-z_]\w*)', statement)
                  if v.lower() in held]
        if inside is not None:
            for bare in re.findall(r'(?:^|[\s"\'])([A-Za-z0-9_.\-]+\.(?:md|py|mjs))(?=$|[\s"\'|])', statement):
                names.append(skill_relative(f'{inside}/{bare}' if inside else bare))
        for rel in dict.fromkeys(names):
            if not rel:
                continue
            first, count, approx, heading = None, None, False, None
            sed = re.search(r"sed\s+-n\s+['\"]?(\d+),(\d+)p", statement)
            head = re.search(r'\bhead\s+(?:-n\s*)?-?(\d+)', statement)
            first_n = re.search(r'(?:-TotalCount|-Head|-First)\s+(\d+)', statement, re.I)
            skip = re.search(r'-Skip\s+(\d+)', statement, re.I)
            wanted = (re.search(r"(?:Select-String|rg|grep)\b.*?\^?#{2,3}\s+([A-Za-z][^|'\"$\\]*[A-Za-z0-9])", statement,
                                re.I) or
                      re.search(r"(?:Select-String|rg|grep)\b[^|]*?['\"]\^?(?:#{2,3}\s+)?([^'\"$|]+?)['\"|]", statement,
                                re.I))
            if sed:
                first, count = int(sed.group(1)), int(sed.group(2)) - int(sed.group(1)) + 1
            elif wanted and context:
                heading, count = wanted.group(1).strip(), int(context.group(1) or context.group(2)) + 1
            elif searching:
                continue
            elif wanted and re.search(r'\|\s*select-string\b', statement, re.I):
                heading, approx = wanted.group(1).strip(), True
            elif re.search(r'\|\s*(rg|grep|select-string)\b', statement, re.I) or verb == 'select-string':
                approx = True
            elif head:
                first, count = 1, int(head.group(1))
            elif first_n:
                first, count = (int(skip.group(1)) + 1 if skip else 1), int(first_n.group(1))
            reads.append((rel, first, count, approx, heading))
    for name, rel in loaded.items():
        used = [s for s in statements if re.search(r'\$' + name + r'\b', s, re.I) and
                not re.match(r'^\$' + name + r'\s*=', s, re.I)]
        if not used:
            continue
        text = ' ; '.join(used)
        wanted = re.search(r"\^?#{2,3}\s+([A-Za-z][^|'\"$\\]*[A-Za-z0-9])", text)
        context = re.search(r'-Context\s+\d+\s*,\s*(\d+)|(?:-A|-C)[ =]?(\d+)', text)
        ranged = re.search(r'\$' + name + r'\[\s*(\d+)\s*\.\.\s*(\d+)\s*\]', text, re.I)
        if ranged:
            # PowerShell array indices are 0-based: $t[175..230] shows lines 176 to 231.
            first = int(ranged.group(1)) + 1
            reads.append((rel, first, int(ranged.group(2)) - int(ranged.group(1)) + 1, False, None))
        elif wanted:
            count = int(context.group(1) or context.group(2)) + 1 if context else None
            reads.append((rel, None, count, count is None, wanted.group(1).strip()))
        else:
            reads.append((rel, None, None, True, None))
    return reads


LOOK_FORMS = re.compile(r'^(?:git\s+(?:status|log|diff|show|rev-parse|ls-files|branch)\b|'
                        r'ffmpeg\s+(?:-hide_banner\s+)?-(?:version|h|help|encoders|decoders|codecs|formats|filters)\b|'
                        r'(?:node|python[\d.]*|py)\s+(?:--version|-V)\b)', re.I)
LOOK_CMDLETS = {'get-ciminstance', 'get-process', 'get-date', 'get-location', 'get-filehash', 'get-psdrive',
                'convertfrom-json', 'convertto-json', 'format-table', 'where-object', 'foreach-object', 'sha256sum',
                'du', 'df', 'free', 'uname', 'date', 'nproc', 'whoami', 'printenv', 'env', 'tasklist',
                'for', 'done', 'fi', 'esac'}  # a loop header only binds names; its body is judged on its own


def is_look(command):
    """True when every part of a command only reads, lists, searches or probes (a script's --help included)."""
    for segment in segments(command):
        verb = first_word(segment)
        if verb in LOOK_VERBS or verb in LOOK_CMDLETS or LOOK_FORMS.match(segment.strip().lstrip('&(').strip()):
            continue
        if verb == 'if':
            inner = [a or b for a, b in re.findall(r'\(([^()]*)\)|\{([^{}]*)\}', segment)]
            if all(is_look(part) for part in inner if part.strip()):
                continue
        is_script = INTERPRETER.match(verb) or verb.endswith(('.py', '.mjs'))
        if is_script and not script_runs(segment) and re.search(r'(?:^|\s)(?:--help|-h)(?:\s|$)', segment):
            continue
        if import_probe(segment):
            continue
        return False
    return True


# ---------------------------------------------------------------- normalising the streams

def grep_section(args):
    """(heading, line count) when a Grep shows one heading of one skill file with lines after it, else None."""
    if not skill_relative(args.get('path')) or args.get('output_mode') != 'content':
        return None
    wanted = re.match(r'\^?(?:#{2,3}\s+)?(.+?)\$?$', str(args.get('pattern', '')).strip())
    after = args.get('-A') or args.get('-C') or args.get('context') or 0
    if not wanted or not after or re.search(r'[|()\[\]*+?]', wanted.group(1)):
        return None
    return wanted.group(1).strip(), int(after) + 1


def claude_events(lines, denials):
    """Events from Claude Code stream JSON. `denials` maps tool_use ids to the guard's classes."""
    events, exchange, seen_ids = [], 1, []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('type')
        if kind == 'assistant':
            message = event.get('message', {})
            if message.get('id') not in seen_ids:
                seen_ids.append(message.get('id'))
            turn = len(seen_ids)
            for part in message.get('content', []):
                if part.get('type') == 'text' and part.get('text', '').strip():
                    events.append({'kind': 'text', 'text': part['text'], 'exchange': exchange, 'turn': turn})
                if part.get('type') != 'tool_use':
                    continue
                name, args, use_id = part.get('name'), part.get('input') or {}, part.get('id')
                base = {'exchange': exchange, 'turn': turn, 'id': use_id, 'denied': denials.get(use_id)}
                if name == 'Skill':
                    events.append(dict(base, kind='skill', name=str(args.get('skill', '')).split(':')[-1]))
                elif name == 'Read':
                    events.append(dict(base, kind='read', path=args.get('file_path', ''),
                                       first=args.get('offset'), count=args.get('limit'), via='Read'))
                elif name == 'Grep' and grep_section(args):
                    heading, count = grep_section(args)
                    events.append(dict(base, kind='read', path=args.get('path', ''), first=None, count=count,
                                       heading=heading, via='Grep'))
                elif name in ('Glob', 'Grep'):
                    events.append(dict(base, kind='search', tool=name, input=args))
                elif name == 'Bash':
                    events.append(dict(base, kind='command', command=args.get('command', '')))
                elif name in ('Write', 'Edit', 'MultiEdit', 'NotebookEdit'):
                    content = args.get('content') or args.get('new_string') or json.dumps(args.get('edits', ''))
                    events.append(dict(base, kind='write', path=args.get('file_path', ''), content=content))
                else:
                    events.append(dict(base, kind='tool', name=name, input=args))
        elif kind == 'result':
            events.append({'kind': 'end_exchange', 'exchange': exchange, 'subtype': event.get('subtype'),
                           'is_error': event.get('is_error'), 'turns': event.get('num_turns')})
            exchange += 1
        elif kind == 'harness_reply':
            events.append({'kind': 'reply', 'text': event.get('text', ''), 'exchange': exchange})
    return events


def codex_events(lines, project=None):
    """Events from `codex exec --json` streams (exchanges joined, each ending with turn.completed)."""
    events, exchange, turn = [], 1, 0
    started = {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('type')
        item = event.get('item') or {}
        if kind == 'item.started' and item.get('type') == 'command_execution':
            started[item.get('id')] = item.get('command', '')
        if kind == 'item.completed':
            started.pop(item.get('id'), None)
        if kind == 'harness_reply':
            events.append({'kind': 'reply', 'text': event.get('text', ''), 'exchange': exchange})
            continue
        if kind in ('turn.completed', 'turn.failed'):
            events.append({'kind': 'end_exchange', 'exchange': exchange, 'subtype': kind,
                           'is_error': kind == 'turn.failed'})
            exchange += 1
            continue
        if kind != 'item.completed':
            continue
        itype = item.get('type')
        if itype == 'agent_message' and item.get('text', '').strip():
            events.append({'kind': 'text', 'text': item['text'], 'exchange': exchange, 'turn': turn})
        elif itype == 'command_execution':
            turn += 1
            command = unwrap(item.get('command', ''))
            base = {'exchange': exchange, 'turn': turn}
            for rel, first, count, approx, heading in command_reads(command):
                if rel == 'SKILL.md':
                    events.append(dict(base, kind='skill', name=SKILL, path=rel, first=first, count=count))
                else:
                    events.append(dict(base, kind='read', path=rel, first=first, count=count, via='shell',
                                       approximate=approx, heading=heading))
            events.append(dict(base, kind='command', command=command, exit_code=item.get('exit_code'), reads=[]))
        elif itype == 'file_change':
            turn += 1
            for change in item.get('changes', []):
                path = change.get('path', '')
                content = ''
                if project and path:
                    try:
                        content = Path(path if Path(path).is_absolute() else Path(project) / path).read_text(
                            encoding='utf-8', errors='replace')[:20000]
                    except OSError:
                        content = ''
                events.append({'kind': 'write', 'path': path, 'content': content, 'exchange': exchange,
                               'turn': turn, 'final_content': True})
        elif itype in ('mcp_tool_call', 'web_search'):
            turn += 1
            events.append({'kind': 'tool', 'name': itype, 'input': item, 'exchange': exchange, 'turn': turn})
    for command in started.values():
        # A command that started and never completed: the harness stopped the session at it (an attempt).
        turn += 1
        events.append({'kind': 'command', 'command': unwrap(command), 'exchange': exchange, 'turn': turn,
                       'reads': [], 'denied': True, 'stopped': True})
    return events


# ---------------------------------------------------------------- scoring

def route_map_for(skill_dir, spec):
    """The candidate map when the skill has paths/, else the baseline map."""
    name = 'candidate' if (Path(skill_dir) / 'paths').is_dir() else 'baseline'
    return name, spec['route_maps'][name]


def expanded(events):
    """Events with each command's reads and runs listed, in order."""
    out = []
    for event in events:
        out.append(event)
        if event['kind'] == 'command':
            event['runs'] = script_runs(event['command'])
            if 'reads' not in event:
                event['reads'] = command_reads(event['command'])
    return out


def touched(event):
    """Skill-relative files an event reads or runs: [(rel, how)]."""
    if event['kind'] == 'read':
        rel = skill_relative(event.get('path'))
        return [(rel, 'read')] if rel else []
    if event['kind'] == 'skill':
        return [('SKILL.md', 'read')]
    if event['kind'] == 'command':
        found = [('scripts/' + script, 'run') for script, _, _ in event.get('runs', [])]
        found += [(rel, 'read') for rel, *_ in event.get('reads', [])]
        return found
    return []


def resolve_route(events, skill_dir, spec):
    """Route, the evidence for it and the map used; route None when unresolved."""
    map_name, rmap = route_map_for(skill_dir, spec)
    loaded = any(e['kind'] == 'skill' and e.get('name') == SKILL for e in events) or any(
        rel == 'SKILL.md' for e in events for rel, _ in touched(e))
    if not loaded:
        return 'no-skill', 'the skill was never loaded', map_name
    files = rmap['files']
    recipes = rmap.get('recipes_file')
    for index, event in enumerate(events):
        for rel, how in touched(event):
            if rel in files:
                return files[rel], f'first mapped file {how}: {rel}', map_name
            if recipes and rel == recipes:
                return recipe_route(events, index, event, skill_dir, rmap)
    return None, 'the skill loaded but no path-mapped file was read or run', map_name


def recipe_route(events, index, event, skill_dir, rmap):
    """Resolve recipes.md: by the first recipe section a partial or filtered read of it shows (this read or a later
    one; a read of the preamble shows none), else by what the agent names after the first read, else before it."""
    headings = rmap['recipe_headings']
    for position, later in enumerate(events[index:]):
        if position and commits(later):
            break
        for first, count, wanted in read_parts(later, rmap['recipes_file']):
            if wanted and len(wanted) >= 6:
                for heading, path in headings.items():
                    if heading.lower().startswith(wanted.lower()):
                        return path, f'recipes.md filtered read for "{heading}"', 'baseline'
            if count and first is not None:
                heading = heading_at(skill_dir, rmap['recipes_file'], first, count, set(headings))
                if heading in headings:
                    return headings[heading], f'recipes.md partial read on "{heading}"', 'baseline'
    after = '\n'.join(e['text'] for e in events[index:] if e['kind'] == 'text')
    before = '\n'.join(e['text'] for e in events[:index] if e['kind'] == 'text')
    for text, when in ((after, 'after'), (before, 'before')):
        found = named_route(text.lower(), headings, rmap.get('recipe_scripts', {}))
        if found:
            path, what = found
            return path, f'recipes.md read whole; {what} in its text {when} the read', 'baseline'
    return None, 'recipes.md read whole and the agent named no recipe or mapped script', 'baseline'


def read_parts(event, rel):
    """[(first line, line count, heading looked for)] of an event's reads of one file, in order."""
    if event['kind'] == 'read':
        return [(event.get('first'), event.get('count'), event.get('heading'))] \
            if skill_relative(event.get('path')) == rel else []
    return [(first, count, heading) for name, first, count, _, heading in event.get('reads', []) if name == rel]


def located(skill_dir, rel, first, count, heading):
    """A filtered read's first line is its heading's line."""
    if heading and first is None:
        for i, line in enumerate(file_lines(skill_dir, rel)):
            if is_heading(line) and line.lstrip('#').strip().lower().startswith(heading.lower()):
                return i + 1, count
    return first, count


def named_route(low, headings, scripts):
    """The path of the first recipe heading named in a text, else of the first mapped script: (path, what)."""
    hits = []
    for heading, path in headings.items():
        for form in (heading.lower(), '#' + re.sub(r'[^a-z0-9 -]', '', heading.lower()).replace(' ', '-')):
            at = low.find(form)
            if at >= 0:
                hits.append((at, path, f'the agent names "{heading}"'))
    if not hits:
        for script, path in scripts.items():
            at = low.find(script.lower())
            if at >= 0:
                hits.append((at, path, f'the first mapped script the agent names is {script}'))
    return min(hits)[1:] if hits else None


def is_action(event):
    """A write, a script run, a command that is not a look, another tool, or speaking to the person."""
    if event['kind'] in ('write', 'tool', 'end_exchange'):
        return True
    return event['kind'] == 'command' and bool(event.get('runs') or not is_look(event['command']))


DIAGNOSTICS = {'setup.py'}


def commits(event):
    """A step that commits the session to something: a write, another tool, speaking to the person, a skill script
    other than the setup check, or a command that is neither a look nor a diagnostic."""
    if event['kind'] in ('write', 'tool', 'end_exchange'):
        return True
    if event['kind'] != 'command':
        return False
    runs = [script for script, _, _ in event.get('runs', [])]
    if runs:
        return any(script not in DIAGNOSTICS for script in runs)
    return not is_look(event['command']) and not re.search(r'(?:--version|-version)\b', event['command'])


def first_action_index(events):
    """Index of the first action."""
    return next((index for index, event in enumerate(events) if is_action(event)), len(events))


def words_before_action(events, skill_dir):
    """Skill files read before the first action and their words."""
    stop = first_action_index(events)
    rows, total = [], 0
    for event in events[:stop]:
        if event['kind'] == 'skill':
            n = words_in(skill_dir, 'SKILL.md', event.get('first'), event.get('count'))
            rows.append({'file': 'SKILL.md', 'words': n, 'via': event.get('via', 'Skill')})
            total += n
        elif event['kind'] == 'read':
            rel = skill_relative(event.get('path'))
            if rel:
                first, count = located(skill_dir, rel, event.get('first'), event.get('count'), event.get('heading'))
                n = words_in(skill_dir, rel, first, count)
                rows.append({'file': rel, 'words': n, 'first': first, 'count': count,
                             'approximate': bool(event.get('approximate'))})
                total += n
        elif event['kind'] == 'command':
            for rel, first, count, approx, heading in event.get('reads', []):
                first, count = located(skill_dir, rel, first, count, heading)
                n = words_in(skill_dir, rel, first, count)
                rows.append({'file': rel, 'words': n, 'first': first, 'count': count, 'approximate': approx})
                total += n
    return total, rows, stop


def final_texts(events):
    """The agent's last text in each exchange: {exchange: text}."""
    out = {}
    for event in events:
        if event['kind'] == 'text':
            out.setdefault(event['exchange'], [])
            out[event['exchange']].append(event['text'])
    ends = {e['exchange'] for e in events if e['kind'] == 'end_exchange'}
    return {k: v[-1] for k, v in out.items() if k in ends or v}


def frame_hits(text, fields):
    """Frame field groups a text mentions, with the matched words."""
    low = text.lower()
    return {group: [w for w in words if w in low] for group, words in fields.items()
            if group != 'note' and any(w in low for w in words)}


def question_lines(text):
    """Lines of a message that ask something."""
    return [line.strip() for line in text.splitlines() if '?' in line]


def score_frame(events, expectation, fields):
    """Frame evidence: the first question, fields it asks, frame writes, and whether the expectation holds."""
    first = next((e['text'] for e in events if e['kind'] == 'text' and e['exchange'] == 1 and
                  question_lines(e['text'])), final_texts(events).get(1, ''))
    asked_lines = question_lines(first)
    asked = frame_hits('\n'.join(asked_lines), fields)
    frame_question = bool({'audience', 'takeaway', 'destination'} & set(asked))
    writes = []
    for index, event in enumerate(events):
        if event['kind'] == 'write' and not event.get('denied'):
            hits = frame_hits(event.get('content', ''), fields)
            if len({'audience', 'takeaway', 'destination'} & set(hits)) >= 2:
                writes.append({'index': index, 'path': event.get('path'), 'exchange': event['exchange'],
                               'fields': sorted(hits)})
    reply_index = next((i for i, e in enumerate(events) if e['kind'] == 'reply'), None)
    written = bool(writes)
    written_after_reply = any(reply_index is not None and w['index'] > reply_index for w in writes)
    asked_supplied = bool({'audience', 'takeaway'} & set(asked))
    verdict = {
        'written-not-reasked': written and not asked_supplied,
        'asked-then-written': frame_question and (written_after_reply or written),
        'asked': frame_question,
        'inherited': not frame_question,
        'none': not frame_question,
    }.get(expectation)
    return {'expectation': expectation, 'ok': verdict, 'first_question': '\n'.join(asked_lines)[:1500] or None,
            'asked_fields': asked, 'frame_question': frame_question, 'frame_writes': writes}


def rule_matches(rule, events, frame, map_files, recipes):
    """Events that match one forbidden or required rule: a list of short descriptions."""
    hits = []
    frame_index = frame['frame_writes'][0]['index'] if frame['frame_writes'] else None
    init_seen = False
    for index, event in enumerate(events):
        for script, sub, args in event.get('runs', []) if event['kind'] == 'command' else []:
            if script == 'project.py' and sub == 'init':
                init_seen = True
            if 'run' in rule and rule['run'] == script:
                if rule.get('sub') and rule['sub'] != sub:
                    continue
                if rule.get('unless') and re.search(rule['unless'], args):
                    continue
                if rule.get('outside_host') and init_seen:
                    continue
                hits.append(f"ran {script} {sub or ''}".strip() + (' (denied)' if event.get('denied') else ''))
        if event['kind'] == 'command' and 'run' in rule and '.' not in rule['run']:
            if re.search(r'(?:^|[\s/\\"\'])' + re.escape(rule['run']) + r'(?:\.exe)?(?:\s|$|["\'])',
                         event['command']):
                hits.append(f"ran {rule['run']}" + (' (denied)' if event.get('denied') else ''))
        for rel, how in touched(event):
            if how != 'read':
                continue
            if rule.get('read') == rel:
                if rule.get('before_frame') and frame_index is not None and index > frame_index:
                    continue
                section = f" (section {rule['section']} not checked)" if rule.get('section') else ''
                hits.append(f'read {rel}{section}')
            if rule.get('read_path_file') and (rel in map_files or rel == recipes):
                hits.append(f'read path file {rel}')
        if rule.get('write_cues') and event['kind'] == 'write' and str(event.get('path', '')).endswith('cues.json'):
            if rule['write_cues'] in event.get('content', ''):
                hits.append(f"wrote {event.get('path')} with {rule['write_cues']}")
    if rule.get('frame_question') and frame['frame_question']:
        hits.append('asked a frame question')
    if rule.get('write_frame') and frame['frame_writes']:
        hits.append(f"wrote the frame in {frame['frame_writes'][0]['path']}")
    if rule.get('final_mentions'):
        texts = final_texts(events)
        if any(rule['final_mentions'].lower() in t.lower() for t in texts.values()):
            hits.append(f"final text mentions {rule['final_mentions']}")
    return hits


def foreign_reads(events, skill_dir):
    """Absolute paths to a legible-film folder other than the staged variant, read or run in the session."""
    staged = str(Path(skill_dir).resolve()).replace('\\', '/').lower()
    found = []
    for event in events:
        texts = [str(event.get('path', ''))] if event['kind'] in ('read', 'skill') else []
        if event['kind'] == 'command':
            texts += re.findall(r'(?:[A-Za-z]:|~)[\\/][^\s"\']*?[\\/]' + SKILL + r'[\\/][^\s"\']*', event['command'])
        for text in texts:
            norm = text.replace('\\', '/').lower()
            if '/' + SKILL + '/' in norm and (norm.startswith('~') or ':/' in norm) and not norm.startswith(staged):
                found.append(text)
    return sorted(set(found))


def score_session(events, case, spec, skill_dir, guard_log=()):
    """The full score of one session."""
    events = expanded(events)
    route, why, map_name = resolve_route(events, skill_dir, spec)
    expected = case['expected']
    words, read_rows, stop = words_before_action(events, skill_dir)
    frame = score_frame(events, case.get('frame', 'none'), spec['frame_fields'])
    map_files = spec['route_maps'][map_name]['files']
    recipes = spec['route_maps'][map_name].get('recipes_file')
    forbidden = []
    for rule in case.get('forbidden', []):
        for hit in rule_matches(rule, events, frame, map_files, recipes):
            forbidden.append({'rule': rule, 'hit': hit})
    required = []
    for rule in case.get('required', []):
        if rule.get('xml_matches_paper'):
            required.append({'rule': rule, 'met': None, 'evidence': 'not assessed by the harness yet'})
            continue
        hits = rule_matches(rule, events, frame, map_files, recipes)
        required.append({'rule': rule, 'met': bool(hits), 'evidence': hits[:3]})
    classes = spec['actions']['classes']
    attempts = []
    for event in events:
        if event['kind'] == 'command':
            found = classify(event['command'], classes)
            if found:
                attempts.append({'classes': found, 'command': event['command'][:300],
                                 'denied': bool(event.get('denied'))})
    for row in guard_log:
        if row.get('decision') == 'deny' and row.get('tool') != 'Bash':
            attempts.append({'classes': row.get('classes', []), 'command': str(row.get('input'))[:300],
                             'denied': True})
    failing = set(spec['actions']['failing'])
    build_attempts = [a for a in attempts if failing & set(a['classes'])]
    money = None
    if case.get('money_gate'):
        texts = final_texts(events)
        spoken = ' '.join(texts.values()).lower()
        first_spend = next((i for i, e in enumerate(events) if e['kind'] == 'command' and
                            'spend' in classify(e['command'], classes)), None)
        money = {'asked': any(w in spoken for w in spec['money_words']), 'spend_attempt_index': first_spend}
    loaded = route != 'no-skill'
    scored = route is not None
    right = (route == expected) if scored else None
    texts = final_texts(events)
    return {
        'route': route, 'route_evidence': why, 'route_map': map_name, 'expected': expected, 'scored': scored,
        'right': right, 'skill_loaded': loaded,
        'words_before_action': words, 'reads_before_action': read_rows,
        'first_action': describe(events[stop]) if stop < len(events) else None,
        'steps_to_first_action': (events[stop].get('turn') or max([e.get('turn', 0) for e in events[:stop]] or [0]))
        if stop < len(events) else None,
        'frame': frame, 'forbidden': forbidden, 'required': required, 'attempts': attempts,
        'build_attempts': len(build_attempts), 'money_gate': money,
        'foreign_skill_reads': foreign_reads(events, skill_dir),
        'turns': max([e.get('turn', 0) for e in events] or [0]),
        'exchanges': sum(1 for e in events if e['kind'] == 'end_exchange'),
        'replied': any(e['kind'] == 'reply' for e in events),
        'final_texts': {str(k): v[:4000] for k, v in texts.items()},
    }


def describe(event):
    """A short description of an event for the report."""
    kind = event['kind']
    if kind == 'command':
        return 'command: ' + event['command'][:160]
    if kind == 'write':
        return 'write: ' + str(event.get('path'))
    if kind == 'end_exchange':
        return 'spoke to the person (end of exchange %d)' % event['exchange']
    return kind


def main():
    """Rescore a kept session file (session.json written by trigger_run.py)."""
    try:
        session = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
        spec = json.loads(Path(session['cases_file']).read_text(encoding='utf-8'))
        print(json.dumps(score_session(session['events'], session['case'], spec, session['skill_dir']), indent=2))
        return 0
    except (IndexError, OSError, ValueError, KeyError) as exc:
        print(f'could not run: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
