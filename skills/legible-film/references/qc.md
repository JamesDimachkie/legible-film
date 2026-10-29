# QC the delivered file

Run every check on the exact file a viewer will receive. A preview, a lab render or a passing build proves
only itself. Scripts are in `scripts/`; each prints `--help`, the measuring scripts write JSON with `--json`, and
the sheet tools write PNGs. Keep the outputs in `qa/`.

Contents: [1. Declare intent first](#1-declare-intent-first) · [2. The battery](#2-the-battery) ·
[3. Looking at a film you cannot play](#3-looking-at-a-film-you-cannot-play) · [4. Interpreting flags](#4-interpreting-flags) ·
[5. Claims and strings](#5-claims-and-strings) · [6. Change proof](#6-change-proof-on-every-revision) · [7. What no script checks](#7-what-no-script-checks) ·
[8. Reporting](#8-reporting)

## 1. Declare intent first

Before running detectors, write `qa/declared.md`: every designed cut, freeze, hold, flash, blank breath and
silence, with its time range and the reason it is there. Pass designed blanks to `blank_scan.py --ignore`, designed
holds, freezes and cuts to `motion_scan.py --ignore`, and silences as silent cues. Run `flash_scan.py` over the whole
file: a designed flash is still held to the hard limit. A flag inside a declared range is expected; a flag anywhere
else is a candidate to inspect. A declaration is
only for what was designed: listing an accident as intended turns a defect into a false report. Tune a
threshold only with representative evidence and a stated reason.

## 2. The battery

The commands show a 1080p60 MP4 with sound; substitute each rendition's own spec. For a GIF, leave out fast start,
the YUV pixel format, BT.709 tags and audio; for an alpha version, use the agreed alpha codec and pixel format. Run
the brand-patch check only where a flat brand patch is defined, and record any check that does not apply, with the
reason. Exit codes are shared: 0 nothing found, 1 something to inspect or fix, 2 the check could not run.

| # | Check | Command | Proves | Does not prove |
|---|---|---|---|---|
| 1 | Spec, decode, colour, loudness | `python scripts/qc_file.py film.mp4 --spec 1920x1080@60 --duration 32 --pix-fmt yuv420p --color bt709 --audio required --sample-rate 48000 --faststart --lossy-check --detect --json qa/qc.json` | size, rate, duration, decoded frame count, clean decode, colour tags, fast start, integrated loudness, true peak before and after an AAC re-encode, audio and video lengths agree, head and tail levels, the mono fold-down loss; black, frozen and silent candidates | that the picture is right, that it looks or sounds good |
| 2 | Brand colour survives | add `--color-patch 4.0@120,80,40,40=#3080C0` (a flat region at a time) | the region decodes to the brand colour under the file's own tags | how every player will show it |
| 3 | Flashing (hard limit) | `python scripts/flash_scan.py film.mp4 --json qa/flash.json` | no candidate WCAG 2.3.1 general or red flash sequence was found | certification (Harding, IRIS, broadcast PSE) |
| 4 | Near-empty frames | `python scripts/blank_scan.py film.mp4 --ignore <designed> --json qa/blank.json` | runs of flat or failed frames outside declared ranges | that a declared breath reads as intended |
| 5 | Cuts, one-frame intrusions, stutter, holds, pace, loop seam | `python scripts/motion_scan.py film.mp4 [--loop] --ignore <designed> --json qa/motion.json`; with a declared pace contract add `--end <end card> --max-still 0.6 --max-still-share 0.4` | where the cuts are, stray single frames, repeated frames inside motion, when motion first starts, long holds, still share and still stretches, cuts per 10 s, seam continuity | whether a move or a hold feels right at speed |
| 6 | Overview | `python scripts/frame_sheet.py film.mp4 --every 0.5 --out qa/overview.png` | what is on screen every half second | anything between the samples |
| 7 | Every transition | `python scripts/frame_sheet.py film.mp4 --around <cut times> --span 1.6 --rate 20 --out qa/joins.png` | sampled states around each join; `--frames A-B` shows every decoded frame of a suspect interval | rhythm |
| 8 | Viewing size | `python scripts/frame_sheet.py film.mp4 --at <text moments> --width 384 --out qa/phone.png` | what essential text looks like at feed size | that someone can read it in time |
| 9 | Full-resolution moments | `python scripts/frame_sheet.py film.mp4 --at <changed and busiest moments> --width 1920 --keep-frames qa/frames --out qa/full.png` | margins, overlaps, print over illustration, qualifiers beside numbers, every rendition | motion |
| 10 | Sounds on cue | `python scripts/cue_onsets.py stems/effects.wav cues.json --json qa/cues.json` (or the delivered file) | each required sound's onset offset, silent cues quiet | that the cue list matches the picture, or that it sounds right |
| 11 | Delivered audio vs approved mix | `python scripts/sync_check.py film.mp4 audio/master.wav --json qa/sync.json` | transport offset, or a drift (a lag that grows) with its rate ratio and the resampling that repairs it; a single shift never fixes a drift | picture-event sync |
| 13 | A qualifier, logo or patch through its whole interval | `python scripts/region_check.py film.mp4 --region X,Y,W,H --interval A-B --reference approved.png --json qa/region.json` | every decoded frame of the interval still carries the region (one representative still misses a qualifier that leaves 0.5 s early) | that it is read in time |
| 12 | Motion path | `python scripts/onion_frames.py --out qa/onion.png qa/frames/<consecutive frames>` | spacing, overshoot and jumps across a move | a single bad frame inside the stack |

Run 1-9 on every delivered rendition (each aspect ratio, the loop, the alpha version, the GIF), adapted as above;
10-11 when there is sound; the change proof in §6 on every revision. Add `--max-level` (4.2 for 1080p60, 5.2 for
2160p60) and `--max-size-mb` to check 1 when a player or platform sets those limits.

A film made with the kit also has a check before any render: `python scripts/film_check.py <film>` reports facts
mismatches, contrast, reading windows and predicted flashing from the film's own timeline, and writes the cue list,
the captions and `qa/declared.json` (the designed cuts, rests and flashes to pass to `--ignore`).

## 3. Looking at a film you cannot play

- An overview every 0.5 s finds missing assets, wrong scenes and layout drift.
- Sample every transition at 20-30 frames a second, from just before to just after the cut, to find blinks,
  overlaps and jumps at the join; look at a suspect interval frame by frame with `--frames A-B`.
- Full-resolution frames at every changed moment and at each scene's busiest moment find the defects
  low-resolution sheets hide (a plate 30 px from the edge, a dot on body text, two texts overlapping for three
  frames). Audit every rendition and still at full resolution, not just the master.
- For each changed move, look at consecutive frames (`frame_sheet.py --frames A-B`) and an onion skin for
  stalls, jumps, blinks and objects moving against their own direction.
- In a film cut to music, sample stills on the beat grid (the beats and half beats around each change) rather than
  at round seconds, because that is where its events land.
- At a whip or any fast move into a cut, look at the frames either side of the cut: the last outgoing frame is the
  fastest and should be the most blurred. A sharp frame there means the motion-blur window was cut short at the cut.
- Count words on viewing-size sheets to check reading load; do not judge readability from memory of the copy.
- Batch frames into sheets: images are expensive in context, and a sheet keeps comparisons side by side.

## 4. Interpreting flags

A flag is a candidate until inspected. For each one:

1. Inspect the exact frames and their neighbours at full resolution (`frame_sheet.py --frames A-B --width 1920`).
2. Compare with the last approved export at the same time.
3. Try to refute it: intended behaviour, a stale cut, a measurement artifact (a near-black fade can cross the
   blank threshold in one encode and not another), or a fix that would damage approved work.
4. Record it as **confirmed**, **refuted** (with the reason) or **unresolved**.

A failed or incomplete decode is not a clean result: the affected checks are unverified. A high-contrast
diagnostic image does not establish how visible a defect is at normal viewing.

## 5. Claims and strings

- Every on-screen number, footnote, label, voice line, caption, thumbnail and post-copy line matches
  `facts.json`, with its label or footnote ([claims-and-rights](claims-and-rights.md)).
- No new claim wording appeared during the build.
- No picture implies a relation or capability the facts do not state, and no effect contradicts the words on its
  frame (an error colour on a success, overlapping tiles in a "fits" shot, a line struck through a promise).
- Proof every string ([product-demos](product-demos.md) §2): plurals, casing, punctuation, number formats,
  leftovers.
- Read key frames as paused stills: each should be a true picture of the story at that moment.
- Before release, an independent reviewer checks the strings against today's sources.

## 6. Change proof on every revision

- **Picture:** `python scripts/compare_versions.py new.mp4 baseline.mp4 --expect <changed ranges>` lists where
  the picture changed. Two renders of the same source are rarely bit-identical after lossy encoding; establish
  your pipeline's normal range for unchanged windows (one HTML pipeline measured about 42-45 dB PSNR). PSNR
  averages the frame, so also inspect important text and geometry at full size around the change.
- **Cue list:** after a picture-only change, re-export the cue list and compare it byte for byte with the one
  the mix used; reuse the mix only when they are identical.
- **Sound that should be unchanged:** hash the decoded audio of both files in one stated format (see the
  cookbook). For an intended sound edit, compare the unchanged intervals on the masters before encoding: once
  the master changes at all, the encoder's noise changes across the whole file.
- **Shared elements:** list every use of anything shared you changed (a helper, a style, a sound) and check
  each.

## 7. What no script checks

The bundled detectors read frame differences, brightness and audio envelopes, so they miss what only an eye at full
resolution catches: print over illustration, a qualifier drifting away from its number, two scenes' text
overlapping for a few frames, a thread that blinks out, partial letterforms during a reveal, an object a few pixels
outside the margin, a footnote that leaves early, and a review copy whose colour differs from the master. Nor does
any script screen regular patterns (stripes, grids, dither) against the regulator's criteria in
[kinetic-type](kinetic-type.md) §8; look for them at the delivered size. Look for
these at each scene's busiest moment, in every rendition.

Nor do they judge:

- Motion at normal playback speed: rhythm, smoothness, whether a transition reads.
- How the sound sounds: balance, harshness, intelligibility, whether a hit feels right.
- Comprehension: whether a newcomer understands what happened and what the product did.
- Taste, brand fit, and whether the film is worth watching twice.

These need a person ([review](review.md)). Report each as checked by a named person, or as unwatched and unheard.

## 8. Reporting

Report what was produced and what was checked, with numbers (duration, frame count, loudness, true peak before
and after re-encode, file size, bitrate), every check not run and why, confirmed and unresolved findings, the
weakest remaining point, and who has watched and listened to which version under which conditions. Do not
grade the film.
