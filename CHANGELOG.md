# Changelog

## 1.0.1 (2026-10-27)

Fixes from two independent reviews of the scripts and references. Each script fix has a known-answer case in
`selftest.py`, which now runs 38 checks.

- `flash_scan.py`, `blank_scan.py`, `motion_scan.py` and `frame_sheet.py` time every frame by its own presentation
  timestamp on the film's clock. Before, a file with variable frame timing could be timed wrongly: the flash screen
  cleared a 4 Hz flash whose last half-second ran at 10 fps, and times in a 30 fps GIF were off by up to 0.2 s.
- `flash_scan.py` screens interlaced video field by field. Before, a flash between the two fields of each frame was
  cleared, because the woven frames look steady.
- `blank_scan.py` flags a render that is blank throughout (new `--floor`).
- `compare_versions.py` pairs frames by index whatever each file's timing, reports times on NEW's own clock, and
  reports a missing or added tail as a change instead of comparing it against a repeat of the shorter file's last
  frame.
- `cue_onsets.py` rejects a cue list or option values it cannot check as written, no longer fails on two cues at the
  same instant, and returns the exit code its report implies.
- `qc_file.py` fails audio checks requested on a file without audio instead of leaving them out.
- Every script returns 2 when it cannot read its input or write its output, keeping 1 for a check that ran and found
  something.
- References: the review step's completion condition, the silent-deliverable path, QC battery notes for GIF and
  alpha renditions, transition sampling, GIF frame timing, sync tolerance, the score's layout and cue windows.
- Evaluations: all five behaviour evals run on 1.0.0 and graded blind, with every prompt, output and grade in
  `evals/results/2026-10-27/`. Evals 3-5 now come with inputs both arms can work on (`make_fixtures.py` builds a
  silent demo and a stand-in film), after a first round in which both arms stopped for want of files.
- README: a header, an example of the checks on a file with planted defects, clearer installation, and the
  evaluation result with a link to its evidence.

## 1.0.0 (2026-10-27)

First public release of Legible Film.

- The method: principles, approval gates, nine steps with completion conditions, revisions, short pieces, hard limits
  and gotchas.
- References for story and score, timing, picture, product demos, sound, claims and rights, formats, engines,
  finishing, an FFmpeg cookbook, QC, review, a case library and sources.
- Scripts: `qc_file.py`, `frame_sheet.py`, `flash_scan.py`, `blank_scan.py`, `motion_scan.py`, `cue_onsets.py`,
  `sync_check.py`, `compare_versions.py`, `onion_frames.py`, and `selftest.py` with synthetic known-answer cases.
- Templates for the brief, treatment, facts, score, cues, asset register, review log, critic brief and delivery
  report.
- Packaging for Claude Code (plugin and marketplace) and the cross-agent `skills` CLI.
