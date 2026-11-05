# QC the delivered file

Run every check on the exact file a viewer will receive. A preview, a lab render or a passing build proves
only itself. The scripts are in the skill's `scripts/` folder (run them as SKILL.md says); each prints `--help`, the
measuring scripts write JSON with `--json`, and the sheet tools write PNGs. Keep the outputs in `qa/`.

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

Then map each requirement of the brief to the check that measures it, so no requirement rests on a check built for
something else (a clean flash screen says nothing about a qualifier that drops out for 16 frames):

| Requirement | Check | Interval | Tolerance |
|---|---|---|---|
| "Up to 2x faster" stays legible with its qualifier | `region_check.py --region <qualifier> --reference approved.png` | 4.20-9.00 s, every decoded frame | the tool's codec tolerance |
| The send click sounds on the button press | `cue_onsets.py` on the delivered mix against the original event times | the cue's window | the brief's 25 ms, never a default |
| Plays muted on a phone | `frame_sheet.py --width 384` at each text moment | each reading window | read by a person |

## 2. The battery

The commands show a 1080p60 MP4 with sound; substitute each rendition's own spec. For a GIF, leave out fast start,
the YUV pixel format, BT.709 tags and audio; for an alpha version, use the agreed alpha codec and pixel format. Run
the brand-patch check only where a flat brand patch is defined, and record any check that does not apply, with the
reason. Exit codes are shared: 0 nothing found, 1 something to inspect or fix, 2 the check could not run.

**A standalone file against a stated spec.** `check.py --file FILE --spec WxH@FPS --duration S` runs a fixed set:
by default it expects H.264, `yuv420p`, BT.709 tags, fast start and a sound track (`--vcodec`, `--pix-fmt`, `--color`
or a `--delivery` JSON state another spec; a silent file or a GIF fails its spec item otherwise), takes no declared
ranges, and does not check the audio codec or sample rate. With `--captions` (and `--timeline` for an editor's
export) it adds the caption items ([editor](../paths/editor.md)). For anything else the brief states, run the battery: `qc_file.py` with the spec's codec, pixel format, colour,
audio codec and sample-rate flags; `blank_scan.py` and `motion_scan.py` with the designed ranges as `--ignore`; and
`flash_scan.py` over the whole file. Keep each exit status, and explain every flag inside a declared range. For a
1920x1080, 60 fps, 45 s H.264 file with AAC at 48 kHz:

```text
qc_file.py deliver/film-v6.mp4 --spec 1920x1080@60 --duration 45 --vcodec h264 --pix-fmt yuv420p --color bt709 --audio required --acodec aac --sample-rate 48000 --faststart --lossy-check --detect --json qa/qc.json
```

| # | Check | Command | Shows | Does not show |
|---|---|---|---|---|
| 1 | Spec, decode, colour, loudness | `qc_file.py film.mp4 --spec 1920x1080@60 --duration 32 --vcodec h264 --pix-fmt yuv420p --color bt709 --audio required --acodec aac --sample-rate 48000 --faststart --lossy-check --detect --json qa/qc.json` | size, rate, duration, codecs, sample rate, decoded frame count, clean decode, colour tags, fast start, integrated loudness, true peak before and after an AAC re-encode, audio and video lengths agree, head and tail levels, the mono fold-down loss; black, frozen and silent candidates | that the picture is right, that it looks or sounds good |
| 2 | Brand colour survives | add `--color-patch 4.0@120,80,40,40=#3080C0` (a flat region at a time) | the region decodes to the brand colour under the file's own tags | how every player will show it |
| 3 | Flashing (hard limit) | `flash_scan.py film.mp4 --json qa/flash.json` | no candidate WCAG 2.3.1 general or red flash sequence was found; in `check.py` a percentile or red flash fails, and a window only the same-pixel pattern detectors counted (`classic_max_per_s` at most 6), or swings no opposite swing reverses in the same pixels (shapes sliding or morphing; `coherent_max_per_s`), is a look, since camera movement over fine detail and moving shapes also trigger them: watch that moment, and a pattern that really flashes fails | certification (Harding, IRIS, broadcast PSE) |
| 4 | Near-empty frames | `blank_scan.py film.mp4 --ignore <designed> --json qa/blank.json` | runs of flat or failed frames outside declared ranges; `check.py` also makes frame 0 black, white or one colour a look (most feeds use it as the thumbnail and autoplay frame), with when the picture first shows and a designed fade in named as the cause | that a declared breath reads as intended |
| 5 | Cuts, one-frame intrusions, stutter, holds, pace, loop seam | `motion_scan.py film.mp4 [--loop] --ignore <designed> --json qa/motion.json`; with a declared pace contract add `--end <end card> --max-still 0.6 --max-still-share 0.4`; on camera footage add `--footage` | where the cuts are, stray single frames, repeated frames inside motion (with `--footage`, only exact duplicates), when motion first starts, long holds, still share and still stretches, cuts per 10 s, seam continuity; the moving area, with pace inside it when it is small | whether a move or a hold feels right at speed |
| 6 | Overview | `frame_sheet.py film.mp4 --every 0.5 --out qa/overview.png` | what is on screen every half second | anything between the samples |
| 7 | Every transition | `frame_sheet.py film.mp4 --around <cut times> --span 1.6 --rate 20 --out qa/joins.png` | sampled states around each join; `--frames A-B` shows every decoded frame of a suspect interval | rhythm |
| 8 | Viewing size | `frame_sheet.py film.mp4 --at <text moments> --width 384 --out qa/phone.png` | what essential text looks like at feed size | that someone can read it in time |
| 9 | Full-resolution moments | `frame_sheet.py film.mp4 --at <changed and busiest moments> --width 1920 --keep-frames qa/frames --out qa/full.png` | margins, overlaps, print over illustration, qualifiers beside numbers, every rendition | motion |
| 10 | Sounds on cue | `cue_onsets.py stems/effects.wav cues.json --json qa/cues.json` (or the delivered file) | each required sound's onset offset, silent cues quiet | that the cue list matches the picture, or that it sounds right |
| 11 | Delivered audio vs approved mix | `sync_check.py film.mp4 audio/master.wav --json qa/sync.json` | transport offset, or a drift (a lag that grows) with its rate ratio and the resampling that repairs it; a single shift never fixes a drift | picture-event sync |
| 12 | Motion path | `onion_frames.py --out qa/onion.png qa/frames/<consecutive frames>` | spacing, overshoot and jumps across a move | a single bad frame inside the stack |
| 13 | A qualifier, logo or patch through its whole interval | `region_check.py film.mp4 --region X,Y,W,H --interval A-B --reference approved.png --json qa/region.json` | compares every frame displayed in the interval with the reference by ink retention and structure, so a qualifier that leaves 0.5 s early is caught where one still would miss it; use a tight region per qualifier and inspect the failing frames | that the copy or every word survived (not OCR: a small lost word in a large region can pass), or that it is read in time |

Run 1-9 on every delivered rendition (each aspect ratio, the loop, the alpha version, the GIF), adapted as above;
10-11 when there is sound; the change proof in §6 on every revision. Add `--max-level` (4.2 for 1080p60, 5.2 for
2160p60) and `--max-size-mb` to check 1 when a player or platform sets those limits.

**An edit checked against its input.** After a quick edit, `check.py --file OUT --against IN --edit KIND` checks
the invariants of that kind of edit as well as the file: `trim:A,B` lasts B minus A within one frame with the audio
offset unchanged; `speed:X` scales the duration by X; `reframe` keeps duration and sound; `convert` keeps duration
and the stream count for its destination; `extract-audio` has no video stream and the source's duration; `captions`
changes no stream; `compress` keeps duration and streams. Where it is cheap it also compares content with the source,
tolerant of re-encoding and scaling: eight sampled pictures against the source frames the edit says they show (`trim`,
`speed`, `convert`, `compress`) and the sound against the source's (`trim`, `convert`, `compress`, `extract-audio`,
`reframe`). Sound that matches nothing there, or most pictures that do not match, is a `fail`; a mix of matching and
not is a `look`; too little to compare (flat picture, a steady tone) is not assessed. What is not compared says
`Not assessed: content`: a reframe's picture or any frame that changed shape, a speed change's sound, and sound in a
file with several streams or over 15 minutes. A passage in the same shot a second or less away can still match: this finds the wrong content, not a slip
of a moment. Thresholds were measured on the first-cut example and synthetic media, not across kinds of film.

**The context and sync groups.** Inside a project, `check.py` adds two groups. Their `unconfirmed` and
`not assessed` items leave the exit code alone unless `--strict` is given; a stale cue list is a `fail` either way.

| Group | Items | States |
|---|---|---|
| Context | each frame field present, and its state; `knows_by` has a second and a channel; the cold read with its model and file hash; a waiver with its reason | `pass` (confirmed), `unconfirmed` (assumed or missing, saying which), `look` (cold read mismatched), `not assessed` (cold read not run) |
| Sync | the cue list present and fresh against this version; the binding (`receipt` and `plan-bound` pass; `screened`, `overridden` and `unverified` are looks that say why) and the render receipt; the version's picture packets, timing and geometry against its manifest; every turn decided; **frame change at cue**; **sound follows the list**; turn leads measured, and each follow span screened against an uncalibrated null (`listen.py sync`; context, never significance); silence scopes; masking pairs answered; conform and mix bound to this list and their media; transport and mux offset against the master; the `listen.py transcript` measured | `pass`, `look`, `fail` (stale, or missing or unbound where the path requires a bound list), `not assessed` (no list on a path that allows none, a plan not yet bound, an inconclusive measure) |
| Stress (`--stress`) | `delivery_check.py`'s low-bitrate proxy re-encode, CAMBI and VMAF worst windows | `look`; `not assessed` when the screen cannot run or its metrics are unavailable (no libvmaf) |

**Frame change at cue** is a screen. The delivered video's frame-to-frame difference within one frame of each turn
and contact must exceed three times the median difference over the surrounding second (a starting value). It says a
change happened, not that it is the intended one; the person and the cold read carry that. Cues declared
`picture: none` or `picture: held` are skipped, and the held ones listed. **Sound follows the list** compares onsets
with cue times against chance (`cue_onsets.py --chance`). Neither is a pass mark for congruence; listening is.

A film made with the kit also has a check before any render: `film_check.py <film>` reports facts
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
- Use each view for what it can see: a two-frames-a-second overview passed defects that full-resolution frames
  caught, and a frame-by-frame check passed an ending that looked wrong at speed (§7).

## 4. Interpreting flags

A flag is a candidate until inspected. For each one:

1. Inspect the exact frames and their neighbours at full resolution (`frame_sheet.py --frames A-B --width 1920`).
2. Compare with the last approved export at the same time.
3. Try to refute it: intended behaviour, a stale cut, a measurement artifact (a near-black fade can cross the
   blank threshold in one encode and not another), or a fix that would damage approved work.
4. Record it as **confirmed**, **refuted** (with the reason) or **unresolved**.

An inconclusive result stays inconclusive: a cue hit rate no better than chance, a weak sync correlation, an onset
under a repetitive bed. Report the candidate offset and what it rests on, then name the next diagnostic (the isolated
effects stem, the sound's reference file, a person listening at that time). Loosening a tolerance to reach a pass
turns an open question into a false one.

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

- **Paper edit:** for a project, `cut.py diff PROJECT vA vB` lists the lines, words, durations and captions that
  changed; it says nothing about the rendered picture or sound, so compare those too.
- **Picture:** `compare_versions.py new.mp4 baseline.mp4 --expect <changed ranges>` locates candidate picture
  changes, and for each changed range names the 4x4 cell of the frame that changed most (with that cell's PSNR) and
  boxes the changed area in pixels: look there first. Exact changed frames need both versions re-rendered losslessly (`-qp 0`) and compared with
  `--lossless-proof`, which asserts rather than verifies that the inputs are lossless. Between lossy files, establish
  your pipeline's normal range for unchanged windows (one HTML pipeline measured about 42-45 dB PSNR; a
  deterministic FFmpeg pipeline re-renders an unchanged picture bit-identically, but a picture change moves the
  encoder's choices for a few seconds around it: unchanged frames near an edit read about 45-62 dB, starting up to
  3.5 s before it).
  PSNR averages the frame, so a small text change can hide in it: inspect important text, geometry and the changed
  moments at full size. Frames are paired by index, so for a version that gained or lost frames say how many and
  where: `--offset-frames 18 --offset-at 10.1` (negative for removed frames) pairs frames directly before that point
  and shifted after it, moves to the frame within a second where the pictures match, and reports the added frames or
  the removal point as a change (name it in `--expect` when intended).
- **Cue list:** after a picture change, re-export the cue list from the owner. A list, bed or mix made before the
  change is refused as stale; spot, conform and mix again from the new list.
- **Outside a declared change:** `sync_check.py NEW OLD --outside A,B` compares the sound outside A..B (the old file's
  seconds) in aligned 50 ms windows (`--window-ms`), judges each against the reference's own level there, and states its
  detection limit; a window under the codec's noise floor reads not assessed. Pair it with `compare_versions.py --expect
  A-B` for the picture.
- **Sound that should be unchanged:** hash the decoded audio of both files in one stated format (see the
  cookbook). For an intended sound edit, compare the unchanged intervals on the masters before encoding: once
  the master changes at all, the encoder's noise changes across the whole file. Previews keep no master: measure
  the encoder's own floor instead (re-encode the baseline's decoded sound, shifted as the edit shifted it, with the
  same settings) and treat a residual at that floor as unchanged.
- **Shared elements:** list every use of anything shared you changed (a helper, a style, a sound) and check
  each.

## 7. What no script checks

The bundled detectors read frame differences, brightness and audio envelopes, so they miss what only an eye at full
resolution catches: print over illustration, a qualifier drifting away from its number, two scenes' text
overlapping for a few frames, a thread that blinks out, partial letterforms during a reveal, an object a few pixels
outside the margin, a footnote that leaves early, and a review copy whose colour differs from the master. Look for
these at each scene's busiest moment, in every rendition.

Regular patterns (stripes, grids, dither) are screened only in kit films: `film_check.py` checks the kit's own
registered textures and dither against the regulator's criteria in [kinetic-type](kinetic-type.md) §8 ([kit](kit.md)
§5). Nothing screens patterns inside supplied footage or images, or in the delivered file; look for them at the
delivered size and get specialist review where the destination requires it.

Nor do they judge:

- Motion at normal playback speed: rhythm, smoothness, whether a transition reads.
- How the sound sounds: balance, harshness, intelligibility, whether a hit feels right.
- Comprehension: whether a newcomer understands what happened and what the product did.
- Taste, brand fit, and whether the film is worth watching twice.

These need a person ([review](review.md)). Report each as checked by a named person, or as unwatched and unheard.

## 8. Reporting

Report what was produced and what was checked, with numbers (duration, frame count, loudness, true peak before
and after re-encode, file size, bitrate), every check not run and why, confirmed and unresolved findings, the
weakest remaining point, and who has watched and listened to which version under which conditions. Print the
context and sync groups' states as they were written, in the delivery report's Context and Sync sections, with the
frame change at cue and sound follows the list under their own labels. Keep
subjective ratings in the scorecard ([grading](grading.md)), each with its reviewer, evidence and confidence; a
rating is not a QC pass.

Pace and cue-spacing targets are guides. Review the measured numbers in context; the reviewer's verdict decides.
