"""Find Node, Playwright and a Chromium for the browser cases the way the kit does (film_capture.mjs): an explicit
override first (LF_PLAYWRIGHT_MODULE, LF_CHROMIUM), then the working folder, the kit, the per-user data folder
setup.py installs playwright-core into, Playwright's own browser cache on each system, and an installed Chrome or
Edge last. A helper module, not a case area (its name starts with an underscore)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent


def data_home():
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'legible-film'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'legible-film'


def playwright_module():
    """(package folder or None, how it was found)."""
    explicit = os.environ.get('LF_PLAYWRIGHT_MODULE')
    if explicit:
        path = Path(explicit)
        return (path if (path / 'package.json').is_file() else None), 'LF_PLAYWRIGHT_MODULE'
    roots = [Path.cwd() / 'node_modules', SCRIPTS / 'node_modules', SCRIPTS.parent / 'node_modules',
             data_home() / 'playwright' / 'node_modules']
    for root in roots:
        for name in ('playwright', 'playwright-core'):
            if (root / name / 'package.json').is_file():
                return root / name, str(root)
    return None, 'searched ' + ', '.join(str(r) for r in roots)


def playwright_core(module):
    """playwright-core for a Playwright package folder (itself, or the copy beside it)."""
    if module is None:
        return None
    if module.name == 'playwright-core':
        return module
    for candidate in (module.parent / 'playwright-core', module / 'node_modules' / 'playwright-core'):
        if (candidate / 'package.json').is_file():
            return candidate
    return module


def browser_cache():
    explicit = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if explicit and explicit != '0':
        return Path(explicit)
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'ms-playwright'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'ms-playwright'
    return Path.home() / '.cache' / 'ms-playwright'


CACHE_EXES = ('chrome-win64/chrome.exe', 'chrome-win/chrome.exe', 'chrome-linux/chrome', 'chrome-linux64/chrome',
              'chrome-mac/Chromium.app/Contents/MacOS/Chromium',
              'chrome-mac-arm64/Chromium.app/Contents/MacOS/Chromium',
              'chrome-headless-shell-win64/chrome-headless-shell.exe',
              'chrome-headless-shell-linux64/chrome-headless-shell',
              'chrome-headless-shell-mac-arm64/chrome-headless-shell',
              'chrome-headless-shell-mac-x64/chrome-headless-shell')
SYSTEM = ('C:/Program Files/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
          'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
          '/Applications/Chromium.app/Contents/MacOS/Chromium')


def chromium(module, node):
    """(executable or None, how it was found)."""
    explicit = os.environ.get('LF_CHROMIUM')
    if explicit:
        return (Path(explicit) if Path(explicit).is_file() else None), 'LF_CHROMIUM'
    if module and node:
        try:
            r = subprocess.run([node, '-e', 'console.log(require(process.argv[1]).chromium.executablePath())',
                                str(module)], capture_output=True, text=True, timeout=20)
            path = Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
            if path and path.is_file():
                return path, 'Playwright'
        except (OSError, subprocess.SubprocessError):
            pass
    cache = browser_cache()
    if cache.is_dir():
        def build(entry):
            tail = entry.name.rsplit('-', 1)[-1]
            return (0 if entry.name.startswith('chromium-') else 1, -(int(tail) if tail.isdigit() else 0))
        for entry in sorted((e for e in cache.iterdir() if e.name.startswith(('chromium-', 'chromium_headless_shell-'))),
                            key=build):
            for exe in CACHE_EXES:
                if (entry / exe).is_file():
                    return entry / exe, str(cache)
    for path in SYSTEM:
        if Path(path).is_file():
            return Path(path), 'installed browser'
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser'):
        found = shutil.which(name)
        if found:
            return Path(found), 'PATH'
    return None, f'no Chromium in {cache} or the usual install places'


def discover():
    """{'module', 'core', 'node', 'chrome', 'missing': reason text or ''}."""
    node = shutil.which('node')
    module, module_from = playwright_module()
    chrome, chrome_from = chromium(module, node) if node else (None, 'not searched without Node')
    missing = []
    if not node:
        missing.append('Node is not on PATH')
    if module is None:
        missing.append('Playwright not found (' + module_from + ')')
    if chrome is None:
        missing.append('Chromium not found (' + chrome_from + ')')
    return {'module': str(module) if module else None, 'core': playwright_core(module), 'node': node,
            'chrome': chrome, 'missing': '; '.join(missing)}
