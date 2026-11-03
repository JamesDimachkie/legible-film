# Delivery report

- Project and version:
- File, size and SHA-256:
- Spec: duration, dimensions, frame rate, codec and pixel format, colour tags, audio:
- Inputs: source commit or frozen-copy hashes, tool versions, render settings:

## What changed from the previous version
(with timestamps)

## What was checked
- Spec, decode and colour tags (`qc_file.py`):
- Loudness, true peak before and after a lossy re-encode, head and tail, mono fold-down:
- Flashing (`flash_scan.py`), blank frames (`blank_scan.py`), motion (`motion_scan.py`):
- Frames: overview, every transition, viewing size, full-resolution moments:
- Sound against the cue list (`cue_onsets.py`); delivered audio against the master (`sync_check.py`):
- Change proof against the baseline (`compare_versions.py`), cue list and audio hashes:
- Claims and strings against `facts.json`; the independent claims check:
- Asset rights (`assets.csv`):

## Context
(the context group as `check.py` wrote it, with each frame field and its state and "unconfirmed" kept as written;
the cold read with the reader's model and the file's hash, or "not assessed (cold read not run)"; any waiver with its
reason)

## Sync
- Cue list: provenance (exported, observed or plan-bound), fresh or stale against this version, binding (receipt,
  screened, overridden, unverified or plan-bound, with the reason for any but receipt):
- Frame change at cue (a screen that says a change happened within a frame of each turn and contact; whether it is
  the intended one is the screener's call):
- Sound follows the list (onsets against cue times, with chance):
- Turn leads and follow coupling (screens against an uncalibrated null, never significance, with n, seed and spread,
  or inconclusive):
- Turns without a decision, and masking pairs still open:

## Not checked, and why

## Who has watched and listened
(name, version, muted or with sound, device; otherwise: unwatched, and unheard for sound. For a silent deliverable:
audio intentionally absent, no audio stream verified.)

## The weakest remaining point

## Publication status
Nothing has been posted, uploaded or sent. (Change this line only when the person has done so.)
