# Contributing

Thank you for helping improve this skill. It stays useful by staying evidence-based and tool-agnostic.

## What makes a good change

- **A rule comes with its evidence:** a defect you can show (frames, a measurement), a listener's or viewer's note on
  a real cut, or a published standard or study with a link. Say which.
- **Numbers carry their basis.** A threshold that worked on one film is described as that film's setting, not as a
  target for every video.
- **Facts carry a date.** Tool versions, platform limits and provider terms change; date them and link the source.
- **Keep the method tool-agnostic.** Engine-specific detail belongs in `references/engines.md`.
- **Keep SKILL.md short.** Detail goes into the reference file that owns the topic, reached from SKILL.md.

## Scripts

- Python 3.9 or later, the standard library plus numpy and Pillow, and FFmpeg and ffprobe found on `PATH` (or through
  `--ffmpeg` / `--ffprobe` and the `FFMPEG` / `FFPROBE` environment variables).
- Every script prints `--help` and states in its docstring what it cannot establish; measuring scripts write JSON
  with `--json`, and image tools write PNGs.
- Add a known-answer case for any new behaviour to the matching module in `scripts/selftest_cases/` (a new module
  goes in `CASE_MODULES` in `scripts/selftest.py`), and keep every case passing. With the Python that `setup.py`
  names (`$PY`, as in the README's Try it):

  ```
  "$PY" skills/legible-film/scripts/selftest.py --smoke
  "$PY" skills/legible-film/scripts/selftest.py --force
  ```

  `--smoke` takes about ten seconds; the full run takes 16 to 32 minutes. CI runs it on Linux, macOS, Windows and on
  Python 3.9 with FFmpeg 5.1, and `.github/scripts/check_docs.py` checks the docs, links and line endings.

## Tested versions

`skills/legible-film/scripts/constraints.txt` names the exact version of everything `setup.py` installs through pip,
the packages those pull in included, and every pip install in `setup.py` and CI uses it. `PLAYWRIGHT_CORE` in `setup.py`
does the same for the film kit, and so for its Chromium build. The `upstream` workflow installs the newest releases
without either, weekly or by hand, so a break upstream shows there before any pin moves; it blocks nothing.

To move a pin:

1. Change its line in `constraints.txt`, or `PLAYWRIGHT_CORE`. Each Python from 3.9 keeps one version with wheels for
   every system it runs on; PyPI lists a release's wheels. Any package the new version pulls in gets a pin of its own:
   `pip install --dry-run --only-binary :all: -c constraints.txt PACKAGE` lists them.
2. Anything PyTorch depends on must also be a version its CPU index (`https://download.pytorch.org/whl/cpu`) carries,
   as the note in `constraints.txt` says.
3. On the oldest and the newest Python you can, run `.github/scripts/extras_check.py`, which installs every group
   through `setup.py` into the per-user environment and tests what the scripts need from each package, then the full
   self-test with that environment's Python. Set `LOCALAPPDATA` (Windows) or `XDG_DATA_HOME` to an empty folder first,
   so your own environment stays as it is.
4. CI's `pins` job does the same on each system. Say in the CHANGELOG which pin moved and why.

## Privacy

Never commit real customer material, personal data, credentials, unreleased product footage or anything you do not
have the right to share. Use synthetic or public examples.

## Licence

By contributing you agree that your contribution is licensed under Apache-2.0, the licence of this repository.
