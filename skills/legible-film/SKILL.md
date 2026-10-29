---
name: legible-film
description: "Video production for coding agents: plans, builds, scores, renders, revises and quality-checks short videos such as product and launch films, teasers, explainers, demos, ads, loops, logo stings, kinetic type, motion graphics, screen recordings, edited footage and generated clips. Use when making or changing a video, choosing video tools, designing its story, picture or sound, timing it to music, encoding or muxing a deliverable, or checking an exported file before it ships. Includes a film kit (a small engine whose films check their own facts, reading time and flashing before they render), sound tools, a motion-blur renderer, and an opt-in studio grade for the highest quality at higher spend. Works with any engine: the kit, HyperFrames, Remotion, Blender, an editor or plain FFmpeg. Not for transcription, downloading or metadata lookups alone."
license: Apache-2.0
argument-hint: "[brief · setup · film|kit|teaser|short|studio · cut|cutdown|captions · score|mix · check|review · revise|deliver] [request]"
compatibility: "Scripts need Python 3.9+ and FFmpeg/ffprobe on PATH; most also need numpy, and the sheet tools need Pillow. The film kit's checks and renders also need Node 18+ with Playwright and a Chromium. No accounts or paid services required."
metadata:
  author: "James Dimachkie"
  version: "1.2.3"
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

The person may start with a command (`/legible-film cut interview.mp4`; `$legible-film cut interview.mp4` in Codex)
or simply describe the work. Either way, take the matching row's path.

- **The command alone, with no request:** list every command below under its group, each with its "For" line, and ask
  what they want to make. Start nothing.
- **A command:** take its path, with the rest of the request as its target. If another row fits the request better,
  say so once and continue on the path they confirm.
- **`studio` before another command** (`/legible-film studio film ...`): that command's path at
  [studio grade](#studio-grade).

| Command | For | Path |
|---|---|---|
| **Plan** | | |
| `brief` | Turn a request into a brief, a facts file and a QC plan before anything is made | Step 1, from the [brief](assets/templates/brief.md) and [facts](assets/templates/facts.json) templates |
| `setup` | Choose the tools for a job, and check this machine can run them | [engines](references/engines.md); `python scripts/make_film.py --doctor` and `python scripts/selftest.py --quick`; for the film kit, [kit](references/kit.md) §2 |
| **Make** | | |
| `film` | A new video, on whichever engine fits: HyperFrames, Remotion, Blender, an editor or FFmpeg | Steps 1-9 |
| `kit` | A type-led film built with the bundled engine, taken to delivered files by one command | Steps 1-9, building with the [film kit](references/kit.md) and `make_film.py` |
| `teaser` | A fast, beat-cut film of big words: a teaser, trailer or hype film | Steps 1-9 in the [kinetic-type](references/kinetic-type.md) register |
| `short` | A logo sting, a loop, or a clip under about 15 s | Steps 1-9, done lightly ([short pieces](#short-pieces)) |
| `studio` | The best film possible, with a budget for premium work | Steps 1-9 at [studio grade](#studio-grade) |
| **Edit** | | |
| `cut` | An edit of recordings: an interview, talking head, screen recording or event film | Steps 1-9 with [footage](references/footage.md) |
| `cutdown` | A new length or shape from an approved cut: 9:16, 1:1, a 15-second version | Steps 1-9 with [footage](references/footage.md#6-other-ratios) §6 and §13: a new length is a new edit with its own timeline; a new shape reframes the approved one |
| `captions` | Captions for an existing video: build, check or burn them | [footage](references/footage.md#11-captions) §11 and [formats](references/formats.md#7-captions) §7, with `captions.py` |
| **Sound** | | |
| `score` | Sound and music for a picture, on the picture's clock | Step 5 with [sound](references/sound.md); for a kit film, `make_film.py FILM --sound draft` (or `library:FOLDER`), then `--sound-only` to remix without re-rendering |
| `mix` | Clean and mix existing dialogue over music, mastered for where it plays | [footage](references/footage.md#10-dialogue) §10 and [sound](references/sound.md); keep the stems and get a person to listen |
| **Check** | | |
| `check` | Run every applicable check on an existing file before it ships, then hand it to a person to watch | Step 7, then step 8 |
| `review` | A review round: people's notes, and critics whose findings are verified before anything changes | Step 8 with [review](references/review.md) |
| **Change and deliver** | | |
| `revise` | A change to an approved cut, checked against the approved version for anything else that moved | [Revisions](#revisions), then steps 6-9 |
| `deliver` | Encode for each platform, with hashes and a delivery report | Steps 6, 7 and 9 with [formats](references/formats.md) and [finishing](references/finishing.md) |

When an input the path needs is missing (the footage, the approved mix, the baseline), name the operations it blocks
and finish everything that does not depend on it: the plan, the hypotheses, and the comparisons and checks to run when
it arrives. Report missing media as not assessed.

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
- Write the QC plan as a table: each requirement of the brief (a claim on screen for its whole interval, a sound on
  its event, a duration, a loudness), the check that measures it, its frame interval and its tolerance, and who will
  watch. A safety screen such as the flash scan never stands in for a requirement's own check.

Done when `brief.md` ([template](assets/templates/brief.md)) states the deliverable in one line (size, frame rate,
duration, renditions, sound, captions), every claim in the draft has a facts entry, and the person has agreed the
brief.

### 2. Story and score

Read [story-and-score](references/story-and-score.md); for product interfaces, [product-demos](references/product-demos.md).

- Write the change, its evidence and its boundary ("This does not establish ___").
- Write three concepts (the product in use, a relational analogy, a reframe), choose one, state it as a governing
  operation, and run the operation, truth, decoding and specificity tests. For an edit of recordings, the approved
  selects and an outline drawn from the sources take the place of the concepts ([footage](references/footage.md) §1).
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
- When music is the clock, measure the track's grid with `tempo_map.py` before building on it.

Done when the cue list ([cues.json](assets/templates/cues.json)) is exported from the same source as the picture, and
every essential text has a usable reading window that fits its task at viewing size.

### 4. Picture

Read [picture](references/picture.md), and [engines](references/engines.md) for the tool you build with.

- Decide a world with reasons: a type scale, one accent with one meaning, a few named motion curves, and the thread
  the viewer follows if the concept has one.
- Build every code-rendered frame as a pure function of time: no wall clock, no unseeded randomness, no CSS
  transitions in a captured page, fonts loaded before anything is measured. Footage keeps its captured motion,
  performances and frame rate.
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
  fast code-rendered motion real motion blur (`film_render.py` for the kit, `motion_blur.py` for other engines);
  photographed footage keeps its own shutter.
- Convert and tag colour explicitly (BT.709 for HD SDR) and verify it; deliver H.264 as `yuv420p` unless the spec
  says otherwise.
- Mux the mastered mix onto the finished picture with the audio length matched to the picture.
- Version every export and make a light review copy with the same colour tags.

Done when the delivered file exists with a manifest (versions, hashes, settings) and `qc_file.py` passes its spec.

### 7. QC the delivered file

Read [qc](references/qc.md). Check the file a viewer will receive.

- Declare designed cuts, holds, flashes and silences, with reasons, before running detectors.
- Run `qc_file.py`, `flash_scan.py`, `blank_scan.py`, `motion_scan.py` and `frame_sheet.py` (overview, every
  transition, viewing size); `region_check.py` on every essential claim, qualifier and logo across its whole
  interval, because stills say nothing about the frames between them; with sound, `cue_onsets.py` and
  `sync_check.py`; on a revision, `compare_versions.py`. Run each check as its own command and keep its exit status.
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
- Check preservation: `compare_versions.py` locates candidate picture changes (with `--lossless-proof` on lossless
  re-renders, the exact frames); inspect the changed moment and every essential text at full size, since a lossy
  PSNR pass cannot prove every pixel unchanged. After a picture-only change, the re-exported cue list is
  byte-identical before the mix is reused; decoded audio hashes match when the sound should be unchanged.
- Before rebuilding a mix, record each event's picture time, each sound's sync point and the brief's tolerance, and
  check the delivered mix against that record. When a sound moves or goes, check both windows on the delivered mix:
  the old one quiet, the new one on cue. Keep the effects stem and the mix recipe; without them, a removal is
  unverified, and the report says so.

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
- On FFmpeg 9, encoding RGB frames (a browser capture, PNGs) with colour options alone left primaries and transfer
  untagged in both libx264 and libvpx-vp9, and some filters (`tmix`) drop tags; re-encoding an already tagged file
  kept them. End every filter chain with `setparams` and check the tags on the output.
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
- PowerShell has no brace expansion, and a here-string's closing delimiter must start its own line; `ffprobe` reads
  one input per call. List files explicitly and probe each file on its own ([ffmpeg-cookbook](references/ffmpeg-cookbook.md#windows-and-quoting-notes)).
- Screen recordings and GIFs often vary their frame timing, so frame number divided by frame rate is not when a
  frame plays; a flash screen that assumed it cleared a 4 Hz flash. Time frames by their presentation timestamps,
  as the scripts do.

## Scripts

In `scripts/`; each prints `--help`. The measuring scripts also write JSON with `--json`; `frame_sheet.py` and
`onion_frames.py` write PNG images. Exit codes are shared: 0 nothing found, 1 something to inspect or fix, 2 the
check could not run, which the report lists as not checked. Run `python scripts/selftest.py` once per environment
and skill version to confirm it (a few minutes, synthetic media only; it remembers a passing environment, and reruns
after an update or with `--force`), and `python scripts/kit_selftest.py` before using the film kit
(it checks Node, Playwright and Chromium, and skips with the reason when one is missing).

| Script | Answers |
|---|---|
| **Make a kit film** | |
| `new_film.py` | Start a film project from the kit. |
| `film_check.py` | Before rendering a kit film: facts, contrast, reading windows, predicted flashing, determinism; writes the cue list, captions and QC declarations. |
| `make_film.py` | One command from a kit film to delivered, checked files: doctor, preflight, sound chain, render, mux, the QC battery, an A/B listening pair and the delivery report. `--doctor` checks the setup; `--loop` measures a loop's seam, `--web` adds a WebM and poster, `--res` sets the output's short side. |
| `film_render.py` | Render a kit film with cut-aware motion blur and the correct colour path (it drives `film_capture.mjs`). |
| `motion_blur.py` | Turn a render made at a multiple of the frame rate into true motion blur, never across a cut. |
| **Edit recordings** | |
| `transcript_cut.py` | Turn selects from a word-timed transcript into edit items, with cuts proposed in the gaps between words; which joins lack measured silence, and which are same-shot jump cuts? |
| `assemble.py` | Render an `edit.json` frame-accurately: cuts, J and L cuts, dissolves, retimes, crop paths, overlays, colour conversion; stems, cue list and declarations. |
| `reframe.py` | Propose or check a crop path that keeps the subject in a tall or square frame; flag frames where it leaves. |
| `captions.py` | Build SRT and WebVTT under reading rules, check a caption file (or a burned-in one) against them, and burn captions clear of faces and platform overlays. |
| **Sound** | |
| `tempo_map.py` | What are a track's tempo, phase, downbeats and drops, how steady is it, and what offset lands its drop on a chosen beat? |
| `make_sound_kit.py` | Synthesise a rights-clean draft palette and temp track with exactly known sync points. |
| `sound_library.py` | Index a folder of licensed effects (sync points, brightness, loudness, licences) and pick a palette for a cue list. |
| `spot_cues.py` | Turn the picture's cue list into sound gestures: merge collisions, thin dense runs, keep layer limits, apply sound edits. |
| `mix_cues.py` | Build the effects stem, the bed and the mix from the cue list and the palette, and master them; which hits are missing, smeared or under the music? |
| `sound_check.py` | Listening candidates in a mix: phone-band loss, brightness, digital silence, crest, layers, the ending. |
| `voice_clean.py` | A conservative cleanup of a dialogue recording (high-pass, noise reduction sized from the measured floor, de-essing, light compression), each step measured and the original kept: a starting point for a listener. |
| **Check the delivered file** | |
| `qc_file.py` | Does the file meet its spec and decode cleanly? Colour tags, loudness, true peak before and after a lossy re-encode, head and tail levels, mono fold-down, brand colour patches. |
| `frame_sheet.py` | What exactly is on screen at these times, at full size or at viewing size? Paginates to a pixel budget, or writes single frames. |
| `flash_scan.py` | Is there a candidate WCAG 2.3.1 flash sequence? |
| `blank_scan.py` | Are there near-empty frames outside the designed ones? |
| `motion_scan.py` | Cuts, one-frame intrusions, repeated frames in motion, holds, first motion, loop seam; pace (still share, still stretches, cuts per 10 s) against a declared contract. |
| `region_check.py` | Does a text, logo or patch survive its whole interval in the delivered file, or does it drop out early? |
| `cue_onsets.py` | Does each sound start, peak or end on its cue, do silent cues stay quiet, and is the hit rate better than chance? With a reference file, is that sound in the mix, and has a moved sound left its old place? |
| `sync_check.py` | Is the delivered audio offset or drifting against the approved mix, and if it drifts, what resampling repairs it? |
| `compare_versions.py` | Where did the picture change between two renders? |
| `onion_frames.py` | What path and spacing does a move have across these frames? |
| **The environment** | |
| `selftest.py` | Do the scripts work here? Synthetic media with known answers, every script; `--quick` probes the dependencies in seconds. |
| `kit_selftest.py` | Do Node, Playwright and Chromium capture and render the kit correctly here? |

`film_capture.mjs`, `render_common.py` and `sound_io.py` are helpers the scripts above load.

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
| Editing recordings: selects, the edit file, reframing, colour, dialogue, captions | [footage](references/footage.md) |
| Finding assets: footage, stills, music, effects, voice, type, 3D, textures | [assets](references/assets.md) |
| Making assets with generative or enhancement tools | [generation](references/generation.md) |
| Checking a figure | [sources](references/sources.md) |
