# What is tested, and what is not

This is the long version of the README's summary. A pass in a self-test shows that a script measures a known answer on a
machine. It says nothing about the quality of a particular film.

## State of each part

| Part | State | What it rests on |
|---|---|---|
| Cutting recordings from a paper edit: cuts in measured pauses, immutable versions, diffs | Tested | 240 of 240 cuts in measured silence on test material; known-answer self-tests |
| Checks on the delivered file (spec, loudness, true peak, flashing, holes, captions, contrast) | Tested on known answers | the self-test on Linux, macOS and Windows; every check says what it cannot see |
| Quick-edit checks that compare content with the source (trim, extract audio, and others where cheap) | Tested on known answers | wrong-source and low-bitrate correct controls on the example clip and synthetic media; thresholds rest on that material |
| Sources checked to where they really decode | Tested on known answers | files cut short by bytes, and picture ending before sound; FFmpeg 5.1 has not been tried by hand |
| Plain cuts rendered by FFmpeg | Tested | the frame-identity case across three rates and three containers, in preview and final, against the every-frame path; variable frame rate, rotated, late-audio and non-square sources matched by burned counter, with identical audio |
| Lining up recordings (`map.py sync`) | Experimental | three public AMI meetings: 25 of 27 pairs lined up, median error 2.9 ms, worst 10.3 ms, including air path; the other two, 15 s excerpts, and 6 of 6 unrelated pairs were looks. Not yet podcasts or real camera clocks |
| Speaker labels | Experimental | two mics: 93% of 6,246 words labelled, 97.5% of those right (96.6 to 98.5 across meetings). One shared track with two people: 93 to 97% labelled, 93 to 94% right (91.4 to 96.6). Meetings with hand-timed words, not podcasts; imported formats tested on documented shapes only; drafts until a person reads them |
| Following an editor's Premiere revisions and checking their export | Read-only; tested on one editor's real revisions | every clip and placed word matched |
| Handing a cut to an editor as Final Cut Pro 7 XML (Premiere, Resolve) | Experimental | read back by OpenTimelineIO on synthetic projects, every cut within half a frame; opened in Premiere in one editor's synthetic test, whose pixel-aspect and stereo findings are fixed but not yet re-checked there; Resolve untested; line-up groups are listed in its notes, not carried |
| Spatial layers: tracking, pins, titles behind a person, tracked blur | Experimental | under 1 px on synthetic planes; on public footage a sign tracked every frame and a face did not; a blur stops the render rather than miss a frame |
| Mattes (key, luma, difference, a subject model) | Experimental | the keys on known answers; the subject model misses people and fringes hair on hard frames |
| Tightening a recording | Experimental | synthetic speech with decaying word tails; on a public reading, 6 of 22 long pauses shortened, every cut near room tone; on one editor's raw interview, 10 cuts (7.3% shorter), all 184 words kept, no clipped word found by listening models, two joins with a visible arm jump; a music bed must be declared |
| Preferences the person confirms | Experimental | known-answer cases and a dry run on one person's notes; nothing shows they predict notes |
| Captions against a transcript | Tested on synthetic cases and one editor's real captions | a transcript can mishear; a person reads every caption |
| Local transcription | Works; accuracy on your audio not measured | transcripts are drafts until a person reads them |
| The Screening Room | Used by one person on one film | no measurement yet |
| Reviewing together in Flask | Used by one person on one teaser, through five versions | every note came back into the project and was closed with a reply in the next version |
| The scorecard | Experimental | a blind test on real and damaged cuts: 4 dimensions told them apart on both, 7 on one, 4 not yet; printed beside every score |
| Agents choosing the story (compared spines, an independent review of each cut) | Experimental | calibrated judges; review raised blind scores on two films; not yet shown on harder material |
| The film kit | Tested | its own self-test in CI |
| The six paths, the frame and the command map | Experimental | the routing evaluation below |
| Cue lists bound to their picture, registered masters, conform and attach-mix | Experimental | each tool's acceptance checks in the self-test; a tool is named in the skill's steps only after its check passes |
| Listening by instrument, `listen.py` | Experimental | known-answer cases and local replays, every number with its n and spread; its sync screen's null is uncalibrated, so follow coupling is a screening signal, never significance; its labels are hints, and the sound is unheard until a person listens |
| Graphics over footage (`~ over`), and Cavalry driven through its MCP server | Experimental | known-answer self-tests: PNG and PNG MOV overlays frame for frame through a cut, ProRes 4444 and VP9 decoded with their colours and transparency; one Cavalry title and one lower third built, seen, rendered, cut and checked on Windows, and Cavalry driven from a fresh Claude Code session; macOS untested |

## The numbers

- **Cuts land in pauses.** On the paper edit's test material, all 240 cuts inside spoken lines fell in silence measured
  in the audio. Cutting at the transcript's word edges instead put 52 cuts in speech and 78 in breaths, and clipped 6
  words. This was measured during 2.0 development; its raw record is not published.
- **Every frame shown.** Renders from MP4, WebM and MKV sources at 29.97, 24 and 25 fps show every expected source frame,
  in preview and final through FFmpeg's picture path and in final through the every-frame path. The case is
  `check_craft2_frame_identity` in `selftest_cases/cut.py`.
- **Flashing.** `flash_scan.py` gives the known answer on its synthetic cases: general and saturated-red flashes around
  the three-per-second limit, small and large areas, and alternating patterns. It screens for WCAG 2.3.1 flashing and is
  not a broadcast PSE certification.
- **Premiere.** On one professional editor's two revisions, every clip (78 of 78, 81 of 81) and every placed word (479 of
  479, 462 of 462, within 1 ms) matched. That footage is private, so these cannot be reproduced from this repository. The
  same editor's agent opened a hand-off of a synthetic 300-frame project in Premiere Pro 26.3 on macOS: every source came
  online, the five clips and the dissolve landed where expected, both J and L overlaps measured right, and 6 of 6 markers
  and 10 of 10 captions matched. It also found the sequence imported with the wrong pixel aspect and stereo played as
  centred mono; the hand-off now declares square pixels and pans each stereo channel, not yet re-checked in Premiere.
- **Render speed.** On a 16-core Windows laptop, before and after 2.2 on the same material: a 30 s 1080p30 final from
  124.7 s (124.3 to 125.5, n=3) to 29.3 s (28.5 to 30.4, n=3); a 30 s 1080p60 final from 211 to 250 s (n=2) to 42.3 s
  (41.3 to 42.6, n=3); a 3-minute 1080p60 preview from 330 s to 90 s (n=1 each); the example's first cut from 42.2 s to
  11.8 s (n=3). The footage is the example clip upscaled, which is soft. A 24 Mbit/s grainy source took 62 s for 30 s
  (n=2). Some earlier "before" runs had other jobs alongside. 4K was not re-measured.
- **The scripts.** CI_COUNTS_PLACEHOLDER
- **Review.** Each part was reviewed by a model of the other family from the one that wrote it (GPT-6.1 Terra and
  Claude). Each fix started from a case that failed.

## How agents route requests

ROUTING_PLACEHOLDER

## Not yet measured

How often local transcription mishears; whether a first film from one prompt is any good for someone who has never used
this skill; podcasts and real camera clocks for line-up and speaker labels; real phone HDR footage.

## What stays manual

- Writing an original score; [earshot](https://github.com/Leonxlnx/earshot)'s own sound-making, sound finding and
  realness scores (an optional, separate tool).
- Warping reading holds into an existing timeline, and refining word onsets against the audio.
- Frame-exact 3D.
- Cue export from engines other than the film kit, HyperFrames (its timelines with the `lf-cues` block) and pages that
  declare `window.__cues`.
- Builds in Tesseract, which run in its own skills; this skill hands off the brief, the frame and a plan cue list, and
  takes the master back.
- Every act of watching and listening.

## Limits

- The scripts measure; they do not watch or listen. Whether a cut works is decided by people, and every report says what
  was checked and what was not.
- Transcripts and speaker labels are drafts until a person has read them against the audio, names and numbers first.
- The scorecard's judgments come from an agent reading stills, scopes and words; it does not experience motion or sound,
  and each dimension says how far it has been validated.
- A cut handed to Premiere or Resolve (`exchange.py write`) carries the clips, joins, sound and markers, not crops, speed
  changes, fade curves or the mix (it lists each). It has been opened in Premiere in one synthetic test, not in Resolve; a
  variable-frame-rate source did not transfer identically there, and transitions do not round-trip exactly (Premiere's
  own re-export replaced custom audio fades).
- Plain cuts render through FFmpeg at about real time at 1080p30. Dissolves, dips, holds, overlays, layers, moving or
  automatic crops, coloured letterboxes and interlaced sources go frame by frame through Python, more slowly; the render
  prints which path ran.
- HDR sources are converted to SDR with the Hable tone map and a note. The only evidence on how that looks came from SDR
  clips converted to HDR, not real phone footage.
- The default cover framing crops a vertical clip in a landscape film heavily; a note names the line and the options that
  keep more of it.
- A graphic goes over footage when it has transparency: a PNG, or a video at the film's size and frame rate (`~ over`,
  from Cavalry, After Effects or another engine). Pins and titles behind a person take still images only, and the film
  kit's renders are opaque, so a kit animation enters as a full-frame cutaway.
- The self-test runs on Windows, Linux and macOS with Python 3.12, and on Linux with Python 3.9 and FFmpeg 5.1, the oldest
  supported. Other versions run a smaller set; see `.github/workflows/ci.yml`.
