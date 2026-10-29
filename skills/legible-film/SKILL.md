---
name: legible-film
description: "Video production for coding agents: plans, builds, scores, renders, revises and quality-checks short videos such as product and launch films, teasers, explainers, demos, ads, loops, logo stings, kinetic type, motion graphics, screen recordings, edited footage and generated clips. Use when making or changing a video, choosing video tools, designing its story, picture or sound, timing it to music, encoding or muxing a deliverable, or checking an exported file before it ships. Includes a film kit (a small engine whose films check their own facts, reading time and flashing before they render), sound tools, a motion-blur renderer, and an opt-in studio grade for the highest quality at higher spend. Works with any engine: the kit, HyperFrames, Remotion, Blender, an editor or plain FFmpeg. Not for transcription, downloading or metadata lookups alone."
license: Apache-2.0
compatibility: "Scripts need Python 3.9+ and FFmpeg/ffprobe on PATH; most also need numpy, and the sheet tools need Pillow. The film kit's checks and renders also need Node 18+ with Playwright and a Chromium. No accounts or paid services required."
metadata:
  author: "James Dimachkie"
  version: "1.2.0"
---

# Legible Film

Make short videos a viewer understands and trusts: one story, picture and sound composed on one clock, every claim
traced to a source, and the delivered file checked before anyone ships it. You plan, build, render, measure and
inspect frames; a person watches at normal speed and listens. Keep those two kinds of evidence apart in everything
you report.

## Principles

1. **Start from the change in the viewer.** Decide what the audience should understand or feel by the end, and what
   they will see that causes it. A look is not a story.
2. **One experience.** Story, picture, motion, sound and the product's truth are composed together in one score,
   not layered on afterwards. "Good" and "professional" are where this work starts.
3. **The delivered file is the film.** Previews, lab renders and passing builds prove only themselves.
4. **Truth in words and pictures.** Every claim traces to the facts file, and a picture claims what it shows.
5. **Every element earns its place.** Strengthen a weak element until it does; thinning the piece to primitives is
   not the fix. Lead with the strongest true thing about the product.
6. **Never jarring; the rest is creative.** No loudness, ratio, shot length or curve is right for every video.
7. **Show it before you ask.** Make every change visible and audible to the person before asking them to judge it.
8. **Approved work stays approved.** Fix causes where they live, check every use of anything shared, and keep the
   baseline.

## What you can and cannot observe

- You can read the brief and its sources, write and run code, render, decode, measure, and inspect single frames and
  contact sheets.
- You cannot watch motion at playback speed or hear. Until a named person has watched the delivered file at normal
  speed, report it as **unwatched**; until they have listened to its sound, report it as **unheard**. A silent
  deliverable has nothing to hear: record its audio as intentionally absent, with the missing stream verified.
- Describe audio by its measurements and tool labels, and motion by what stills and measurements show.
- Report what you produced, what you checked (with numbers), what you did not check, and the weakest remaining
  point. Grading belongs to the people watching.

## Gates

Ask the person before you spend money or start paid generation (the cap is theirs to set); upload private, client or
unreleased material to any hosted service, including frame describers, transcription and enhancement tools; or
publish, post, send or hand over anything. Keep facts to the facts file and record every asset's source and licence
([claims-and-rights](references/claims-and-rights.md)). Run one heavy render at a time, check free memory first, and
stop only processes you started, by their own PID.

## Choose the path

| The request | Path |
|---|---|
| A new video | Steps 1-9 |
| A fast, beat-cut film of big words (a teaser, trailer or hype film) | Steps 1-9 in the [kinetic-type](references/kinetic-type.md) register |
| A type-led film built with the bundled engine | Steps 1-9, building with the [film kit](references/kit.md) |
| The best film possible, with a budget for premium work | Steps 1-9 at [studio grade](#studio-grade) |
| A logo sting, a loop, or a clip under about 15 s | Steps 1-9, done lightly ([short pieces](#short-pieces)) |
| A change to an approved cut | [Revisions](#revisions), then steps 6-9 |
| Check or review an existing file | Steps 7-8 |
| Choose or set up tools | [engines](references/engines.md) |

## Studio grade

When the person asks for studio grade, the highest quality, or gives a budget for premium assets, follow
[studio](references/studio.md) on top of the steps: it adds a study of comparable work, choices the person can watch
(concept sketches, styleframes, an animatic), spending on the film's real bottleneck, specialist craft passes, and a
loop that raises the weakest moment until viewers clear a six-question bar or the person stops. Every gate and hard
limit still applies. To find assets, read
[assets](references/assets.md); to make them with generative tools, [generation](references/generation.md).

## Steps

Each step leaves a file in the project, so the next session, person or agent can pick it up.

### 1. Brief, facts and format

- Collect the audience and where they watch, the one change the video should make, the deliverables, what is fixed
  (approved copy, claims, brand, footage), the budget and who approves it. The destination decides whether it must
  read muted, whether it loops and which renditions are owed ([formats](references/formats.md)).
- Start the facts file ([facts.json](assets/templates/facts.json)): every number and factual line with its source,
  date read, conditions and on-screen label.
- Ask only for what is genuinely missing (usually the audience, where it plays, or the facts); write down everything
  you assumed instead of asking.
- Write down how the delivered file will be checked (step 7) and who will watch it, so the plan carries its QC from
  the start.

Done when `brief.md` ([template](assets/templates/brief.md)) states the deliverable in one line (size, frame rate,
duration, renditions, sound, captions), every claim in the draft has a facts entry, and the person has agreed the
brief.

### 2. Story and score

Read [story-and-score](references/story-and-score.md); for product interfaces, [product-demos](references/product-demos.md).

- Write the change, its evidence and its boundary ("This does not establish ___").
- Write three concepts (the product in use, a relational analogy, a reframe), choose one, state it as a governing
  operation, and run the operation, truth, decoding and specificity tests.
- Choose the structure, the turn, the peak and the ending's job, then fill the score
  ([score.csv](assets/templates/score.csv); a [filled example](assets/examples/score-example.md) shows the method).

Done when `treatment.md` ([template](assets/templates/treatment.md)) names one concept with its boundary and test
answers, every moment has a score row whose text traces to the facts file, and the person agrees the story.

### 3. The clock

Read [timing](references/timing.md).

- Choose each passage's clock: action, speech, music or deliberate silence.
- Keep every event picture and sound share in one timing source that both the picture code and the cue export read;
  compute sync points from the animation, never by hand.
- Give each essential text its `in`, `readStart`, `readEnd` and `out`.
- When music is the clock, measure the track's grid with `beat_grid.py` before building on it.

Done when the cue list ([cues.json](assets/templates/cues.json)) is exported from the same source as the picture, and
every essential text has a usable reading window that fits its task at viewing size.

### 4. Picture

Read [picture](references/picture.md), and [engines](references/engines.md) for the tool you build with.

- Decide a world with reasons: a type scale, one accent with one meaning, a few named motion curves, and the thread
  the viewer follows if the concept has one.
- Build every frame as a pure function of time: no wall clock, no unseeded randomness, no CSS transitions in a
  captured page, fonts loaded before anything is measured.
- Work in a lab loop before any full render: stills at each cue's frames, short motion windows, seeks out of order
  and back, and sheets at viewing size (`frame_sheet.py`).
- With the [film kit](references/kit.md), run `film_check.py` before every render: it reports facts mismatches,
  contrast, reading windows and predicted flashing from the film's own timeline.

Done when style frames are judged at full size and at viewing size, every changed moment is checked in stills and a
short motion render, and the engine's own checks pass.

### 5. Sound

Read [sound](references/sound.md). For a planned silent deliverable, record audio as intentionally absent and go to
step 6; step 7 verifies the exported file with `qc_file.py --audio none`, unless the destination requires a silent
track.

- Decide what the sound does: for each passage what leads (music, effects, voice or quiet), which events sound, and
  how it ends.
- Where the choice is open, prepare treatments that differ in one choice, picture fixed and loudness matched, so the
  person chooses by listening.
- Place each take by its sync point against the cue list (`mix_cues.py` builds the stem and mix from the cue list and
  the palette), and master with a light safety limiter. `make_sound_kit.py` gives a rights-clean draft palette and a
  temp track to time against before any sound is bought or generated.

Done when each passage has a lead and a job, `cue_onsets.py` matches the cue list, the true peak stays below 0 dBTP
after a lossy re-encode, and the person's listening decision is recorded or the sound is reported as unheard.

### 6. Render, finish and mux

Read [finishing](references/finishing.md) and the [ffmpeg-cookbook](references/ffmpeg-cookbook.md).

- Render a frozen copy of the source, recording tool versions and input hashes; render a short window first. Give
  fast motion real motion blur (`film_render.py` for the kit, `motion_blur.py` for other engines).
- Convert and tag colour explicitly (BT.709 for HD SDR) and verify it; deliver H.264 as `yuv420p` unless the spec
  says otherwise.
- Mux the mastered mix onto the finished picture with the audio length matched to the picture.
- Version every export and make a light review copy with the same colour tags.

Done when the delivered file exists with a manifest (versions, hashes, settings) and `qc_file.py` passes its spec.

### 7. QC the delivered file

Read [qc](references/qc.md). Check the file a viewer will receive.

- Declare designed cuts, holds, flashes and silences, with reasons, before running detectors.
- Run `qc_file.py`, `flash_scan.py`, `blank_scan.py`, `motion_scan.py` and `frame_sheet.py` (overview, every
  transition, viewing size); with sound, `cue_onsets.py` and `sync_check.py`; on a revision, `compare_versions.py`.
- Inspect every flag in context and record it as confirmed, refuted or unresolved; check every string against the
  facts file.

Done when every applicable check has a result or a stated reason it was not run.

### 8. Review with people

Read [review](references/review.md).

- Share each cut where the person can play it, with what changed and where. Ask for a muted pass at viewing size,
  then a sounded pass, then pauses on problems; treat each pause as a note and fix its cause.
- Synthetic critics, with separate lenses and ideally another model family, find problems to verify; they never
  outrank the person's approved choices.

Done when no blocking or visible finding is open and a named person has watched the delivered file at normal speed,
muted and, if it has sound, with sound. While a pass is pending this step stays open, and the report says
**unwatched** for a missing viewing and **unheard** for a missing listening, each on its own.

### 9. Deliver

- Put the deliverables at the top of a delivery folder and the QA material in `qa/`.
- Write the delivery report ([template](assets/templates/delivery-report.md)): SHA-256, specs, what changed, what was
  checked, what was not, the weakest point, who watched and listened, and the publication status.
- Before a release or re-release, re-read every changeable claim at its source.

Done when every deliverable in the format exists and passes its own spec, and the report is complete. Posting and
sending wait for the person.

## Revisions

- Name the change and the approved properties that must stay; keep the approved source and export as the
  **baseline**.
- Fix the cause where it lives, then check every use of anything shared you changed. When resolving an ambiguous
  note would change the approved design, show a still or a short motion proposal first.
- Prove it: `compare_versions.py` shows changes only where intended; after a picture-only change, the re-exported cue
  list is byte-identical before the mix is reused; decoded audio hashes match when the sound should be unchanged.

## Short pieces

A sting, a loop or a one-idea clip still earns every step, at its own scale. The brief and facts can be a few lines.
When the idea is already settled, record it with its boundary instead of exploring three concepts. The clock may be a
single bar of music or one action. QC and a person's viewing are never skipped: a two-second sting can still flash,
clip, or misspell a name. For a loop, the last frame leads into frame 0, `motion_scan.py --loop` checks the join, and
frame 0 doubles as the poster.

## Hard limits

- **Flashing:** no more than three general or red flashes in any one second (WCAG 2.3.1). Run `flash_scan.py` on every
  delivered file; it screens and does not certify.
- **Contrast:** essential text at least 4.5:1 (3:1 for large text) and essential graphics 3:1, against the actual
  background; colour never the only carrier of meaning.
- **Truth:** no claim beyond the facts file, in words or pictures; reconstructions and illustrations are labelled.
- **Sound:** no clipping or overs after a lossy re-encode, and nothing jarring.
- **Rights:** every asset's licence covers the intended use.

## Gotchas

Each was hit in real production or measured while building this skill.

- Default RGB-to-YUV conversion uses the BT.601 matrix; tagging the result BT.709 shifted a brand blue from
  (48,128,192) to (39,123,195). Convert with an explicit BT.709 matrix, then tag ([finishing](references/finishing.md) §3).
- On FFmpeg 9, colour options alone left primaries and transfer untagged, and some filters (`tmix`) drop tags: end
  every filter chain with `setparams` and check the tags on the output.
- `-shortest` with a short soundtrack truncated a 120-frame picture to 94 frames; pad with `apad` and cut with `-t`.
- Lossy encoders push true peak up on sharp transients; measure after a simulated platform re-encode.
- An engine's own audio path can render far below its source (11.6 dB in one HTML renderer); mux the mastered mix.
- HTML renderers can read the live project folder while rendering; render a frozen copy.
- Frame describers and video-understanding tools can upload frames or files when an API key is present; choose local
  modes for private work.
- A beat phase estimated from bass energy was 68 ms early and audible; find it from kick attacks.
- Generated music tends to ignore requested sections; ask for extra length and build the structure in the edit.
- A two-frames-a-second overview passed defects that full-resolution frames caught, and a frame-by-frame check passed
  an ending that looked wrong at speed. Use each check for what it can see.
- In FFmpeg filter arguments, a Windows drive-letter colon breaks the graph; run from the file's folder.
- Screen recordings and GIFs often vary their frame timing, so frame number divided by frame rate is not when a
  frame plays; a flash screen that assumed it cleared a 4 Hz flash. Time frames by their presentation timestamps,
  as the scripts do.

## Scripts

In `scripts/`; each prints `--help`. The measuring scripts also write JSON with `--json`; `frame_sheet.py` and
`onion_frames.py` write PNG images. Exit codes are shared: 0 nothing found, 1 something to inspect or fix, 2 the
check could not run, which the report lists as not checked. Run `python scripts/selftest.py` once to confirm the
environment (about a minute, synthetic media only), and `python scripts/kit_selftest.py` before using the film kit
(it checks Node, Playwright and Chromium, and skips with the reason when one is missing).

| Script | Answers |
|---|---|
| `qc_file.py` | Does the file meet its spec and decode cleanly? Colour tags, loudness, true peak before and after a lossy re-encode, head and tail levels, mono fold-down, brand colour patches. |
| `frame_sheet.py` | What exactly is on screen at these times, at full size or at viewing size? |
| `flash_scan.py` | Is there a candidate WCAG 2.3.1 flash sequence? |
| `blank_scan.py` | Are there near-empty frames outside the designed ones? |
| `motion_scan.py` | Cuts, one-frame intrusions, repeated frames in motion, holds, first motion, loop seam; pace (still share, still stretches, cuts per 10 s) against a declared contract. |
| `cue_onsets.py` | Does each sound start, peak or end on its cue, do silent cues stay quiet, and is the hit rate better than chance? |
| `sync_check.py` | Is the delivered audio offset or drifting against the approved mix? |
| `compare_versions.py` | Where did the picture change between two renders? |
| `onion_frames.py` | What path and spacing does a move have across these frames? |
| `beat_grid.py` | What are a track's tempo, phase, downbeats and drops, how steady is it, and what offset lands its drop on a chosen beat? |
| `mix_cues.py` | Build the effects stem, the bed and the mix from the cue list and the palette; which hits are missing, smeared or under the music? |
| `make_sound_kit.py` | Synthesise a rights-clean draft palette and temp track with exactly known sync points. |
| `motion_blur.py` | Turn a render made at a multiple of the frame rate into true motion blur, never across a cut. |
| `new_film.py` | Start a film project from the kit. |
| `film_check.py` | Before rendering a kit film: facts, contrast, reading windows, predicted flashing, determinism; writes the cue list, captions and QC declarations. |
| `film_render.py` | Render a kit film with cut-aware motion blur and the correct colour path (it drives `film_capture.mjs`). |

## References

| When | File |
|---|---|
| Step 1 | [formats](references/formats.md) |
| Any claim or generated asset | [claims-and-rights](references/claims-and-rights.md) |
| Step 2 | [story-and-score](references/story-and-score.md); precedents in [case-library](references/case-library.md) |
| Product interfaces | [product-demos](references/product-demos.md) |
| Step 3 | [timing](references/timing.md) |
| Step 4 | [picture](references/picture.md); [engines](references/engines.md) |
| Step 5 | [sound](references/sound.md) |
| Step 6 | [finishing](references/finishing.md); [ffmpeg-cookbook](references/ffmpeg-cookbook.md) |
| Step 7 | [qc](references/qc.md) |
| Step 8 and revisions | [review](references/review.md) |
| Studio grade | [studio](references/studio.md) |
| A fast, beat-cut film of big words | [kinetic-type](references/kinetic-type.md) |
| Building with the bundled engine | [kit](references/kit.md) |
| Finding assets: footage, stills, music, effects, voice, type, 3D, textures | [assets](references/assets.md) |
| Making assets with generative or enhancement tools | [generation](references/generation.md) |
| Checking a figure | [sources](references/sources.md) |
