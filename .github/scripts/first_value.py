#!/usr/bin/env python3
"""Run the README's quickstart as written, time every step, and fail when it is too slow.

  python .github/scripts/first_value.py [--readme README.md] [--os linux|macos|windows] [--budget 300]
      [--skip TEXT ...] [--instead OLD NEW ...] [--skip-os] [--summary FILE] [--dry-run]

The quickstart is the fenced code blocks between `<!-- first-value:start -->` and `<!-- first-value:end -->`. The
paragraph of text just above a block says which systems it is for: a label naming Linux, macOS or Windows runs only
there (one block can name several), and a block whose label names none runs everywhere. Blocks run in the order written,
in one shell session per run (bash on Linux and macOS, PowerShell on Windows), so a variable set by one line is seen
by the next. Every command line is a step; a `#` comment line names the steps below it; a line ending in `\\` (bash)
or a backtick (PowerShell) continues on the next line.

A step that installs the system's own packages (apt, apt-get, brew, winget, choco, dnf, pacman, with or without
sudo) is timed and reported separately and does not count against the budget. Every other step counts. After a
package step the PATH is refreshed the way a new terminal would see it (on Windows, from the registry). A step passes
with exit 0; a step that runs one of the skill's scripts also passes with exit 1, the scripts' "something to
inspect", except a check.py step whose summary counts a failed check. The first check's summary line must match
the one the README quotes ("The first check ends `...`"), so the README cannot drift from the output. Any other exit
stops the run. No step may open a window: a quickstart line that calls start,
Start-Process, Invoke-Item, explorer, open or xdg-open is refused, and on Windows a program name or `& $variable`
that resolves only to a file without a program extension (which Windows would hand to another application) is
refused with exit 9009 rather than run.

The table goes to $GITHUB_STEP_SUMMARY when it is set, to --summary FILE when given, and always to the output.
--skip leaves out steps whose command contains TEXT and --instead runs NEW where the quickstart says OLD; both are
named in the table, so a run that used them is never mistaken for the quickstart as written. --skip-os leaves out
the package steps (for a machine that already has them).

What it does not prove: that the quickstart is fast on a person's own machine (CI runners differ, and package
installs and downloads depend on the network), or that the first cut is any good.

Exit 0 when every step passed within the budget, 1 when every step passed but the counted steps took longer than
the budget, 2 when a step failed or the quickstart could not be read or run.
"""
import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
START = '<!-- first-value:start -->'
END = '<!-- first-value:end -->'
FENCE = re.compile(r'^(```+|~~~+)(.*)$')
OS_WORDS = {'linux': ('linux',), 'macos': ('macos', 'mac os', 'os x'), 'windows': ('windows',)}
PACKAGE_TOOLS = ('apt', 'apt-get', 'brew', 'winget', 'choco', 'dnf', 'pacman')
SKILL_SCRIPTS = 'skills/legible-film/scripts/'
MARK = '@@first-value'
COMMAND_WORD = re.compile(r'(?:^|[(|;{]|&&)\s*([A-Za-z][\w.-]*)')
CALLED_VARIABLE = re.compile(r'&\s*\$(\w+)')
OPENERS = {'start', 'start-process', 'saps', 'invoke-item', 'ii', 'explorer', 'explorer.exe', 'open', 'xdg-open',
           'cmd', 'cmd.exe'}
PS_GUARD = r"""
function __fv_runnable([string]$path) {
    $exts = (($env:PATHEXT + ';.EXE;.COM;.BAT;.CMD') -split ';') | Where-Object { $_ }
    return ($exts -contains [IO.Path]::GetExtension($path))
}
function __fv_guard([string]$name) {
    $first = Get-Command -Name $name -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $first -or $first.CommandType -ne 'Application') { return }
    $good = @(Get-Command -Name $name -CommandType Application -All -ErrorAction SilentlyContinue |
              Where-Object { __fv_runnable $_.Source })
    if ($good.Count -gt 0) {
        $body = "& '" + ($good[0].Source -replace "'", "''") + "' @args"
    } else {
        $body = "[Console]::Error.WriteLine('first_value: " + $name + " resolves only to files Windows would " +
                "open with another program; not running it'); `$global:LASTEXITCODE = 9009"
    }
    Set-Item -Path ('function:global:' + $name) -Value ([scriptblock]::Create($body))
}
function __fv_value([object]$value) {
    if ($value -isnot [string] -or -not $value) { return $true }
    if (Test-Path -LiteralPath $value -PathType Leaf) {
        if (__fv_runnable $value) { return $true }
        [Console]::Error.WriteLine('first_value: ' + $value + ' is not a program Windows runs directly; not running it')
        return $false
    }
    if ($value -match '^[A-Za-z][\w.-]*$') { __fv_guard $value }
    return $true
}
"""


class QuickstartError(Exception):
    """The quickstart cannot be read or run as written."""


def current_os():
    """The running system as linux, macos or windows."""
    name = platform.system()
    if name == 'Darwin':
        return 'macos'
    return 'windows' if name == 'Windows' else 'linux'


def label_systems(label):
    """The systems a block's label names; an empty set means every system."""
    text = label.lower()
    return {name for name, words in OS_WORDS.items() if any(word in text for word in words)}


def read_blocks(text):
    """Return [(label, [lines])] for every fenced block between the markers, in order; a block's label is the
    paragraph of text just above it."""
    if START not in text or END not in text:
        raise QuickstartError(f'no {START} ... {END} section')
    section = text.split(START, 1)[1].split(END, 1)[0]
    blocks = []
    paragraph = []
    ended = True
    label = ''
    fence = None
    lines = []
    for line in section.replace('\r\n', '\n').split('\n'):
        match = FENCE.match(line.strip())
        if fence is None and match:
            fence = match.group(1)
            label = ' '.join(paragraph)
            paragraph = []
            lines = []
        elif fence is not None and line.strip().startswith(fence) and not line.strip()[len(fence):].strip():
            blocks.append((label, lines))
            fence = None
        elif fence is not None:
            lines.append(line)
        elif not line.strip():
            ended = True
        elif not line.strip().startswith('<!--'):
            paragraph = [line.strip()] if ended else paragraph + [line.strip()]
            ended = False
    if fence is not None:
        raise QuickstartError('a code block in the quickstart is not closed')
    return blocks


def is_package_step(command):
    """True when the command installs the system's own packages."""
    words = command.replace('&&', ' ').split()
    words = [word for word in words if word != 'sudo']
    return bool(words) and words[0] in PACKAGE_TOOLS


def is_skill_step(command):
    """True when the command runs one of the skill's scripts, whose exit 1 means something to inspect."""
    return SKILL_SCRIPTS in command.replace('\\', '/')


def parse_steps(lines, windows):
    """Turn a block's lines into steps: (comment label, command), joining continued lines."""
    steps = []
    label = ''
    pending = ''
    mark = '`' if windows else '\\'
    for raw in lines:
        line = raw.rstrip()
        if not pending and (not line.strip() or line.strip().startswith('#')):
            if line.strip().startswith('#'):
                label = line.strip().lstrip('#').strip()
            continue
        if line.endswith(mark):
            pending += line[:-1].rstrip() + ' '
            continue
        steps.append((label, (pending + line.strip()).strip()))
        pending = ''
    if pending:
        steps.append((label, pending.strip()))
    return steps


def select_steps(blocks, system):
    """The steps for one system, in the order the quickstart lists them."""
    steps = []
    for label, lines in blocks:
        systems = label_systems(label)
        if systems and system not in systems:
            continue
        steps.extend(parse_steps(lines, system == 'windows'))
    if not steps:
        raise QuickstartError(f'the quickstart has no steps for {system}')
    return steps


def plan_steps(steps, skips, instead, skip_os):
    """Return one dict per step with what will run and why."""
    replace = {old.strip(): new.strip() for old, new in instead}
    plan = []
    for index, (label, command) in enumerate(steps, 1):
        item = {'n': index, 'label': label, 'written': command, 'run': command, 'package': is_package_step(command),
                'note': '', 'state': 'not run', 'seconds': None, 'exit': None}
        if command in replace:
            item['run'] = replace[command]
            item['note'] = f'ran `{item["run"]}` instead (--instead)'
        if any(text in command for text in skips) or (skip_os and item['package']):
            item['state'] = 'skipped'
            item['note'] = 'skipped (--skip-os)' if skip_os and item['package'] else 'skipped (--skip)'
        openers = {word.lower() for word in command_words(item['run'])} & OPENERS
        if openers:
            raise QuickstartError(f'step {index} would open a window or another program '
                                  f'({sorted(openers)[0]}): {item["run"]}')
        item['allowed'] = (0, 1) if is_skill_step(item['run']) else (0,)
        plan.append(item)
    return plan


def bash_script(plan):
    """A bash script that runs each step and prints start and end markers around it."""
    out = ['export PYTHONUNBUFFERED=1']
    for item in plan:
        if item['state'] == 'skipped':
            continue
        n = item['n']
        allowed = max(item['allowed'])
        out.append(f"printf '\\n{MARK} start {n}@@\\n'")
        out.append(item['run'])
        out.append('__rc=$?')
        out.append(f"printf '\\n{MARK} end {n} %s@@\\n' \"$__rc\"")
        out.append(f'if [ "$__rc" -gt {allowed} ]; then exit "$__rc"; fi')
        if item['package']:
            out.append('hash -r')
    return '\n'.join(out) + '\nexit 0\n'


def command_words(command):
    """The bare command names a step calls: its first word and the first word after ( | ; { && or ||."""
    return set(COMMAND_WORD.findall(command))


def powershell_script(plan):
    """A PowerShell script that runs each step and prints start and end markers around it. Before each step, every
    program it names and every `& $variable` it calls is resolved to a file Windows runs directly: a name that only
    resolves to a file without a program extension (which Windows would hand to another application, opening a
    window) is refused with exit 9009 instead."""
    out = ["$ErrorActionPreference = 'Continue'", '$env:PYTHONUNBUFFERED = "1"',
           '[Console]::OutputEncoding = [Text.Encoding]::UTF8; $OutputEncoding = [Text.Encoding]::UTF8',
           "if ($PSStyle) { $PSStyle.OutputRendering = 'PlainText' }", PS_GUARD]
    refresh = ("$__known = $env:Path -split ';'; foreach ($__scope in 'Machine', 'User') { "
               "foreach ($__dir in ([Environment]::GetEnvironmentVariable('Path', $__scope) -split ';')) { "
               "if ($__dir -and $__known -notcontains $__dir) { $env:Path += ';' + $__dir; $__known += $__dir } } }")
    for item in plan:
        if item['state'] == 'skipped':
            continue
        n = item['n']
        allowed = max(item['allowed'])
        out.append(f"[Console]::Out.WriteLine(''); [Console]::Out.WriteLine('{MARK} start {n}@@'); "
                   '[Console]::Out.Flush()')
        out.append('$global:LASTEXITCODE = 0; $__blocked = $false; $__ok = $true')
        out.extend(f"__fv_guard '{name}'" for name in sorted(command_words(item['run'])))
        out.extend(f'if (-not (__fv_value ${name})) {{ $__blocked = $true }}'
                   for name in sorted(set(CALLED_VARIABLE.findall(item['run']))))
        out.append('if ($__blocked) { $global:LASTEXITCODE = 9009 } else {')
        out.append(item['run'])
        out.append('$__ok = $?')
        out.append('}')
        out.append('$__rc = $global:LASTEXITCODE; if (-not $__ok -and $__rc -eq 0) { $__rc = 2 }')
        out.append(f"[Console]::Out.WriteLine(''); [Console]::Out.WriteLine('{MARK} end {n} ' + $__rc + '@@'); "
                   '[Console]::Out.Flush()')
        out.append(f'if ($__rc -gt {allowed} -or $__rc -lt 0) {{ exit $__rc }}')
        if item['package']:
            out.append(refresh)
    return '\r\n'.join(out) + '\r\nexit 0\r\n'


def shell_command(system, script_path):
    """The command that runs the generated script in the system's shell."""
    if system == 'windows':
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if not shell:
            raise QuickstartError('PowerShell is not on PATH')
        return [shell, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script_path)]
    shell = shutil.which('bash')
    if not shell:
        raise QuickstartError('bash is not on PATH')
    return [shell, '--noprofile', '--norc', str(script_path)]


def run_plan(plan, system, timeout):
    """Run the steps in one shell, streaming its output, and fill in each step's time and exit code."""
    by_number = {item['n']: item for item in plan}
    windows = system == 'windows'
    handle, name = tempfile.mkstemp(prefix='first-value-', suffix='.ps1' if windows else '.sh')
    os.close(handle)
    script = Path(name)
    started = {}
    output = {}
    try:
        if windows:
            script.write_text(powershell_script(plan), encoding='utf-8-sig', newline='')
        else:
            script.write_text(bash_script(plan), encoding='utf-8', newline='\n')
        process = subprocess.Popen(shell_command(system, script), cwd=str(ROOT), stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   env=dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8'))
        timer = threading.Timer(timeout, process.kill)
        timer.start()
        for raw in process.stdout:
            line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
            now = time.monotonic()
            marker = re.fullmatch(re.escape(MARK) + r' (start|end) (\d+)(?: (-?\d+))?@@', line.strip())
            if marker:
                n = int(marker.group(2))
                if marker.group(1) == 'start':
                    started[n] = now
                    output[n] = []
                    item = by_number[n]
                    print(f'\n=== step {n}: {item["run"]}', flush=True)
                else:
                    item = by_number[n]
                    item['seconds'] = now - started.pop(n, now)
                    item['exit'] = int(marker.group(3))
                    item['state'] = 'passed' if item['exit'] in item['allowed'] else 'failed'
                    item['output'] = output.pop(n, [])
                    if item['state'] == 'passed' and check_failed(item['run'], item['output']):
                        item['state'] = 'failed'
                        item['note'] = (item['note'] + ' ' if item['note'] else '') + 'a check failed'
                    print(f'=== step {n}: exit {item["exit"]}, {item["seconds"]:.1f} s', flush=True)
                continue
            for lines in output.values():
                lines.append(line)
            print(line, flush=True)
        code = process.wait()
        timer.cancel()
    finally:
        script.unlink(missing_ok=True)
    for n, began in started.items():
        by_number[n]['state'] = 'failed'
        by_number[n]['seconds'] = time.monotonic() - began
        by_number[n]['note'] = (by_number[n]['note'] + ' ' if by_number[n]['note'] else '') + 'did not finish'
    return code


def check_failed(command, lines):
    """Whether a check.py step reported a failed check. Its exit 1 also means "something to look at", which passes;
    a summary line counting failures does not."""
    if 'check.py' not in command:
        return False
    return any(re.search(r'\b[1-9]\d* failed\b', line) for line in lines)


def stale_quote(text, plan):
    """The README quotes the first check's summary line; when the check prints another, the README is out of date and
    that step fails with both lines."""
    quoted = re.search(r'The first check ends `([^`]+)`', text)
    step = next((item for item in plan if 'check.py' in item['run'] and '--file' in item['run']
                 and item.get('output') is not None), None)
    if not quoted or not step:
        return
    printed = [line.strip() for line in step['output'] if re.search(r'\d+ checks? pass', line)]
    if not printed or printed[-1] != quoted.group(1):
        step['state'] = 'failed'
        step['note'] = (step['note'] + ' ' if step['note'] else '') + (
            f'the README says the first check ends `{quoted.group(1)}`; it printed '
            + (f'`{printed[-1]}`' if printed else 'no summary line'))


def cell(text):
    """Text safe inside one Markdown table cell."""
    return str(text).replace('|', '\\|').replace('\n', ' ')


def summarize(plan, system, budget):
    """The Markdown report and whether the counted steps stayed within the budget."""
    counted = [item for item in plan if not item['package'] and item['seconds'] is not None]
    packages = [item for item in plan if item['package'] and item['seconds'] is not None]
    total = sum(item['seconds'] for item in counted)
    package_total = sum(item['seconds'] for item in packages)
    first_check = next((item for item in plan if 'check.py' in item['run'] and not item['package']), None)
    to_check = sum(item['seconds'] for item in counted if first_check and item['n'] <= first_check['n'])
    rows = ['| # | Step | Command | Time | Exit | Counted | Note |', '|---|---|---|---|---|---|---|']
    for item in plan:
        seconds = '' if item['seconds'] is None else f'{item["seconds"]:.1f} s'
        exit_code = '' if item['exit'] is None else str(item['exit'])
        counted_text = 'no: system packages' if item['package'] else 'yes'
        note = item['note'] or ('' if item['state'] == 'passed' else item['state'])
        rows.append(f'| {item["n"]} | {cell(item["label"])} | `{cell(item["written"])}` | {seconds} | {exit_code} | '
                    f'{counted_text} | {cell(note)} |')
    failed = [item for item in plan if item['state'] == 'failed']
    not_run = [item for item in plan if item['state'] == 'not run']
    altered = [item for item in plan if item['state'] == 'skipped' or item['run'] != item['written']]
    within = total <= budget
    lines = [f'## First value on {system}', '']
    if failed or not_run:
        lines.append(f'**Failed** at step {(failed or not_run)[0]["n"]}; the steps after it did not run.')
    else:
        verdict = 'within' if within else 'over'
        lines.append(f'**{total:.0f} s** from setup to the first cut checked, {verdict} the {budget:.0f} s budget '
                     f'(setup to the first check: {to_check:.0f} s). System packages took {package_total:.0f} s, '
                     'not counted.')
    if altered:
        lines.append('')
        lines.append('Not the quickstart exactly as written: ' + ', '.join(f'step {item["n"]}' for item in altered)
                     + ' (see Note).')
    lines += [''] + rows + ['']
    return '\n'.join(lines), within and not failed and not not_run


def write_summary(text, path):
    """Append the report to a summary file."""
    with open(path, 'a', encoding='utf-8', newline='\n') as handle:
        handle.write(text + '\n')


def main():
    """Read the quickstart, run it and report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--readme', default=str(ROOT / 'README.md'), help='the file holding the quickstart')
    parser.add_argument('--os', choices=sorted(OS_WORDS), default=current_os(), help='whose steps to run')
    parser.add_argument('--budget', type=float, default=300.0, help='seconds allowed for the counted steps')
    parser.add_argument('--skip', action='append', default=[], metavar='TEXT', help='leave out steps containing TEXT')
    parser.add_argument('--instead', nargs=2, action='append', default=[], metavar=('OLD', 'NEW'),
                        help='run NEW where the quickstart says OLD (the whole command)')
    parser.add_argument('--skip-os', action='store_true', help='leave out system package steps')
    parser.add_argument('--summary', help='also append the report to this file')
    parser.add_argument('--timeout', type=float, default=1800.0, help='stop the whole run after this many seconds')
    parser.add_argument('--dry-run', action='store_true', help='list the steps without running them')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    try:
        text = Path(args.readme).read_text(encoding='utf-8')
        blocks = read_blocks(text)
        plan = plan_steps(select_steps(blocks, args.os), args.skip, args.instead, args.skip_os)
        unused = [old for old, _ in args.instead if old.strip() not in {item['written'] for item in plan}]
        if unused:
            raise QuickstartError('--instead names a command the quickstart does not have: ' + unused[0])
        if args.dry_run:
            for item in plan:
                kind = 'package' if item['package'] else 'counted'
                print(f'{item["n"]:>2} [{kind}] {item["run"]}' + (f'  ({item["note"]})' if item['note'] else ''))
            return 0
        run_plan(plan, args.os, args.timeout)
        stale_quote(text, plan)
    except (OSError, QuickstartError) as error:
        print(f'first_value: cannot run: {error}', file=sys.stderr)
        return 2
    report, ok = summarize(plan, args.os, args.budget)
    print('\n' + report)
    for path in (os.environ.get('GITHUB_STEP_SUMMARY'), args.summary):
        if path:
            write_summary(report, path)
    if any(item['state'] in ('failed', 'not run') for item in plan):
        return 2
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
