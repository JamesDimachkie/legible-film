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
- Add a case to `scripts/selftest.py` with a known answer for any new behaviour, and keep it passing:

  ```
  python skills/legible-film/scripts/selftest.py
  ```

## Privacy

Never commit real customer material, personal data, credentials, unreleased product footage or anything you do not
have the right to share. Use synthetic or public examples.

## Licence

By contributing you agree that your contribution is licensed under Apache-2.0, the licence of this repository.
