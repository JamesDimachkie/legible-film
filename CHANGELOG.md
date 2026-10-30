# Changelog

## 1.2.4 (2026-10-29)

Fixes from a video professional's questions: exact NTSC frame rates, resumes that notice a tool upgrade, and caption
checks against the current dialogue.

- **Frame rates:** `"fps": 29.97` encoded at 2997/100, a rate editing applications read as non-standard. A decimal
  NTSC rate (23.976 or 23.98, 29.97, 47.952, 59.94, 119.88) now means the exact fraction (30000/1001 and its
  family) in every encode, and `edit.json`, `transcript_cut.py --fps` and `motion_blur.py --fps` accept
  `"30000/1001"`. The cue list `assemble.py` writes carries the exact rate as a number.
- **make_film.py --resume** keys each step on the builds of the tools it uses, as the doctor finds them (FFmpeg,
  ffprobe, Node, Playwright, and Chromium by path, size and time): an FFmpeg upgrade reruns the renders, muxes and
  QC and reuses spotting and the sound kit. New cases show what a change reruns: a picture-only edit re-renders both
  sizes and reuses the sound; a new master remixes and re-muxes and reuses both renders; an FFmpeg upgrade reruns a
  render and reuses a Python-only step.
- **captions.py check** compares captions with a word-timed transcript of the current audio. It names caption words
  no longer spoken nearby (words cut from the audio but left on screen), flags a caption over no matching speech,
  and reports a whole file offset once. Reading speed, duration, single-word lines, small gaps, words spoken but not
  captioned, and when each caption enters and leaves against the speech are now review prompts with their numbers
  (exit 0): short captions are often intentional, and a person decides. Overlaps, too many or too long lines, and
  the dialogue findings still exit 1. `build` writes its files when only review prompts remain.

## 1.2.3 (2026-10-29)

Commands: a named way into each kind of video work.

- **16 commands** start the skill on one path: `brief` and `setup` to plan; `film`, `kit`, `teaser`, `short` and
  `studio` to make; `cut`, `cutdown` and `captions` to edit; `score` and `mix` for sound; `check` and `review`; and
  `revise` and `deliver`. Type `/legible-film cut interview.mp4` (`$legible-film cut interview.mp4` in Codex), or
  `/legible-film` alone for the list. They are a column in SKILL.md's path table, so a command and a plain request
  take the same path; `studio` can lead any other command. Checked by hand in Claude Code 2.1.312 and Codex CLI
  0.160.0: the command alone lists the commands and starts nothing, and `cutdown` with its input missing reports it
  as not assessed and finishes the work that does not need it.
- **README:** rewritten around the commands, with the install in one line at the top, the reasons in three points,
  every script in a collapsible list, the evidence in one place, and a new limit: edits do not yet round-trip to
  editing applications.
- `examples/prompts.md` opens with one example per command.
- SKILL.md's scripts table now lists `voice_clean.py`, which shipped in 1.2.0 without an entry.

## 1.2.2 (2026-10-29)

Sound iterations without re-rendering the picture, taste reported as numbers, and library takes that fit their cues.

- **make_film.py --sound-only** reuses the previous make's renders and picture checks when the picture source and
  the cue list are unchanged (cue content is compared, not the note of which size exported it), muxes the new sound
  into versioned deliverables beside the earlier ones (`_1920x1080-2.mp4`), and reruns the spec, sync and sound
  checks on them. On the Atlasfold showcase at two sizes, a remix with a new master took 82 s against 39 minutes for
  the full make, and both video streams came out bit-identical. Any change to the picture, the cue list, a render or
  a lossless master is refused with the reason; a refused run keeps the earlier `make-state.json`; like `--resume`,
  it trusts only records written in its own output folder; manifests record `picture_reused`.
- **Taste checks:** a missed pace target and a cue a few milliseconds early or late are reported as measured numbers
  against their targets under their own heading in the delivery report, for a person to look and listen at, and no
  longer set the exit status. Safety and specification gates (flashing, spec, sync, a required cue missing) still
  do.
- **sound_library.py pick** trims a take that is longer than its cue spacing or role allows: the attack and at least
  120 ms of body are kept, a 30 ms fade ends it, and the palette and attribution record the original and used
  lengths. A take licensed no-derivatives, or one with too little room for its attack, is skipped with the reason.
  `--max-duration`, `--min-body` and `--fade-ms` tune it.

## 1.2.1 (2026-10-29)

The film kit's own vocabulary, loops, and web deliverables. Films written for 1.2.0 still run unchanged: the old
names are read as the new ones, and the Atlasfold showcase renders the same pixels.

- **Names:** blocks `Type`, `Still` and `Thread` (were `Words`, `Picture`, `Chain`); shot styles `land`, `kicker`,
  `meet`, `snap`; hits `bump`, `shake`, `burst`; entrances `whip-h` and `whip-v`; exits `dive` and `shrink`; the
  `tracer` effect and its `converge` option; sound roles `boom`, `sweep`, `sting` (EndCard `stingGain`) and `tap`;
  `beat_grid.py` is now `tempo_map.py`. Palettes and cue lists with the 1.2.0 role names still mix.
- **Blank nodes:** `group.add({w, h})` lays the element out at that size (`node.size(w, h)` resizes one), and the
  preflight errors on a tracked node that never paints (transparent throughout, no size, always outside the frame,
  or nothing to draw), naming the node and its block.
- **Loops:** `loop: true` holds the camera and the preflight checks that the camera, the ground and every tracked
  element return to their frame-0 values at the end; BLOCKS.md documents the camera hold (`drift: false`) with a
  loop example.
- **make_film.py:** `--loop` (on by itself for a loop film) measures the seam on every delivered file with
  `motion_scan.py --loop`; `--web` adds a VP9 WebM encoded from a lossless render and a poster from frame 0, both
  checked; `--res N` is now the output's short side (it scaled from 1080 lines before, so `1280x720 --res 720`
  failed), an odd side is refused before anything runs with a `--res` that works, and manifests record the real
  output size; the film's `pace` contract is read in either spelling, so its gates now run; a template inside the
  kit (`assets/kit/films/atlasfold`) can be made directly.
- **Terminal:** `fullFrame: true` makes the window the whole frame, for a tall frame.
- `references/ffmpeg-cookbook.md`: an opaque VP9 WebM recipe from a lossless master with the BT.709 matrix, and its
  poster, tested on a flat brand colour.

- **Fixes from an independent review** of the kit and make pipeline (Atlasfold renders the same pixels):
  - **make_film.py --resume** binds `make-state.json` to the resolved output folder and records outputs relative to it:
    resuming in a copied or moved folder runs every step again (it reported a missing deliverable as delivered and
    wrote manifests into the original folder), a cached step whose outputs or results point outside the output or film
    folder runs again, and manifests are never written outside the output folder.
  - **Flash prediction** draws every tracked node as its element paints (fill, background, borders, box shadows,
    images and canvases, through its children, with their opacity, blur and blend mode). A white tracked panel flipping
    eight times a second predicted 0 transitions; it now predicts 9, as `flash_scan.py` measures on the render. A
    tracked node it cannot draw (an SVG, a video) marks the prediction incomplete in film_check.py's output.
  - **Loop seam:** the preflight compares each tracked element's corners, so a square turned 90 degrees no longer
    passes because it fills the same box; blur and 3-D turns are compared too.
  - **make_film.py --web --loop** measures each WebM's own seam with `motion_scan.py --loop` and carries it into the
    WebM's manifest, the delivery report and the exit status.
  - **Blank nodes:** a `transparent` or alpha-zero fill no longer counts as paint; borders, shadows and text count only
    in a colour that is not transparent, and a child only on frames it is visible.
  - **--res:** film_check.py takes `--res N` (make_film.py passes its own) and judges type size, the large-text
    contrast rule, dither cells and still resolution at the delivered size, keeping the layout at the CSS size.

## 1.2.0 (2026-10-29)

Legible Film now makes video end to end: films built in code, edits cut from recordings, a sound chain designed for
phone speakers, and checks for what an agent cannot see by eye. Every new script is tested against synthetic media
with known answers, and its help says what it does not prove.

### Make a film in code

- **The film kit** (`assets/kit/`, `references/kit.md`): a small, dependency-free browser engine for type-led films,
  from a calm launch film to beat-cut kinetic type, laid out in frame units so one timeline renders 16:9, 9:16 and
  1:1. Blocks for the common devices (big words on the beat, a terminal, a number, the name, a picture, a chain of
  linked ideas, a denial, an end card, a running caption), a camera rig, a palette built from one brand colour as
  tinted neutrals, and variable type fitted to the frame.
- **Checks before rendering** (`film_check.py`): claims bound to the facts file, contrast at every ground, reading
  windows, flashing predicted with `flash_scan.py`'s own method, regular-pattern warnings, and a determinism lint; it writes the cue list, captions and QC declarations.
- **One command to delivered files** (`make_film.py`): doctor, preflight, the sound chain, render with cut-aware
  motion blur in linear light, mux, the QC battery per size, a blind A/B listening pair and an auto-filled delivery
  report; `--resume` skips finished work.
- `new_film.py`, `film_render.py` (with `film_capture.mjs`) and `motion_blur.py` for any engine rendered at a
  multiple of the frame rate. A starter film and the Atlasfold showcase.
- `references/kinetic-type.md`: the register of big words on a beat, its devices with their truth checks, pace you
  can measure, and its safety limits (flash budgets, regular patterns, readable qualifiers, motion).

### Edit recordings

- `references/footage.md`: ingest, selects, the edit, the `edit.json` contract, other ratios, speed and
  stabilisation, colour and HDR, screen recordings, dialogue, captions, approvals and lock, variants and hand-off.
- `assemble.py`: renders `edit.json` frame-accurately on presentation timestamps, with J and L cuts, dissolves,
  dips, retimes (nearest, blend, motion), crop paths, image overlays and burned captions; converts HDR, BT.601 and
  BT.2020 sources deliberately; writes stems per track, the cue list and QC declarations.
- `reframe.py` proposes or checks a subject crop path for tall and square frames, rate-limited, and flags frames
  where the subject leaves it. `transcript_cut.py` turns selects in a word-timed transcript into edit items, with
  cuts proposed in the gaps between words and jump cuts flagged. `captions.py` builds SRT and WebVTT under reading
  rules, checks caption files and burned-in captions (timing and contrast), and burns captions clear of faces and
  platform overlays.

### Sound

- The sound chain from the picture's cue list: `beat_grid.py` measures a track's tempo, downbeats, drops and drift;
  `spot_cues.py` merges collisions and thins dense runs; `make_sound_kit.py` synthesises a rights-clean draft palette
  with sub, air and a looping bed; `sound_library.py` indexes licensed effects and picks a palette;
  `mix_cues.py` builds stems and the mix, ducks music under a voice by phrase, and masters to the destination
  (social, web, broadcast) with a safety limiter checked after an AAC re-encode, reporting any shortfall;
  `sound_check.py` reports listening candidates (phone-band loss, brightness, digital silence, crest, layers, the
  ending, voice-to-bed separation). `voice_clean.py` is a guarded dialogue cleanup measured step by step.

### Checks

- `region_check.py`: a claim, qualifier or logo through every decoded frame of its interval.
- `cue_onsets.py`: end sync, matching a reference sound in a mix, a moved sound's old window, and explicit
  inconclusive results with the next diagnostic. `sync_check.py`: drift with its rate ratio and the resampling that
  repairs it.
- `motion_scan.py`: pace (still share, still stretches, change events) against a declared contract, `--footage` for
  camera footage, and pace inside a small moving area. `compare_versions.py`: thresholds for deterministic pipelines,
  per-frame PSNR and `--lossless-proof`. `frame_sheet.py`: pages within a pixel budget and single frames.
  `qc_file.py`: H.264 level and file size.
- `selftest.py --quick` probes dependencies in seconds; a passing run is remembered per environment and skill
  version; skipped cases are counted. `kit_selftest.py` checks capture and render in the browser.
- Scripts read JSON written by Windows PowerShell 5.1 (UTF-8 and UTF-16 with a byte-order mark).

### The method

- The QC plan maps each requirement to the check that measures it; claims are checked across their whole interval;
  a moved sound is checked in both places; inconclusive results stay open; missing media is reported as not assessed
  while the rest of the work continues.
- Code-render rules (pure-function frames, synthetic motion blur) apply to code-rendered picture; footage keeps its
  own motion and shutter. A cut-down with its own length gets its own timeline.
- Tested Windows recipes (PowerShell here-strings and files without a byte-order mark, one input per `ffprobe`,
  `-fps_mode`), and recipes for WebM, trims, tall crops, pauses in speech, stabilisation, scopes and HDR tone mapping.

### Evaluations

- Evals 8 (a kinetic teaser plan), 9 (a film built with the kit), 10 (a captioned 9:16 cut-down from an interview)
  and 11 (a dialogue-over-music mix), with synthetic fixtures and grader-only answers for 10 and 11.

## 1.1.0 (2026-10-27)

Studio grade: an opt-in path to the best film the budget allows, on top of the unchanged method.

- `references/studio.md`:
  - a first reply that leads with two or three directions the person can picture, then the route in plain words;
  - opening questions in plain words about the use, the material, the cap, references, who judges and what is owed,
    with a running total against the cap before every approval;
  - a bounded study of comparable work before design, from which the directions come, which also supplies
    references when the person has none;
  - leading someone new to video by showing choices instead of asking: scripts for presenting development and final
    gates, and a table that turns common feedback ("make it more premium", "it feels rushed") into something to show;
  - gates the person can watch: concept sketches, styleframes of the hardest frames, an animatic and sound direction,
    with a branch for silent films;
  - spending on the film's actual bottleneck, with product truth never the place to save;
  - specialist craft passes for story, picture, type, editing, sound design, music, voice, mix, finishing and
    product demonstrations, offered as options while the design can still change, with each judgement that needs
    eyes or ears assigned to a named person;
  - a loop that keeps raising the weakest moment until each of six bar questions is met with a named viewer's
    evidence, or the person decides to stop;
  - studio deliverables agreed at the brief, each with its own check: master, stems that reconstruct the mix,
    localisation material, captions, and an archive split into what the maker keeps and what the client may receive.
- `references/assets.md`:
  - how to find and clear footage, stills, music, sound effects, voice-over, type, 3D, finishing textures and interface
    art;
  - quality checks, dated sources by tier, licence questions (including the role an edit gives a stock person),
    search terms, rejection cues, a budget ladder and the asset record.
- `references/generation.md`:
  - when generation is the wrong medium, the shot contract, prompts, references and keyframes;
  - bounded variants with hard rejects and cost per accepted second, the repair order, frame-level inspection, and
    rights, privacy and disclosure;
  - a dated landscape of image, video, voice, music, effects, repair and 3D tools.
- `assets/examples/score-example.md`: a filled 40-second score for a fictional product. `assets/templates/budget.csv`:
  the spend plan, with commitments and the remaining cap.
- `references/claims-and-rights.md`: font files go to a client only where the licence allows it; otherwise the
  handover lists each font and how to licence it.
- README: what studio grade asks of the person, and a plain-language way to check the installation.
- Evaluations:
  - Two studio-grade requests: eval 6 (a consumer app) and eval 7 (an open-source command-line tool).
  - Both were compared blind with 1.0.1, two runs per version, on the same runner. The checklist gave 1.1.0 7-9/9 and
    1.0.1 2-4/9. A judge who never saw the expectations preferred the 1.1.0 plan in all four pairs, at medium
    confidence, but found the 1.0.1 plans more concrete about what appears on screen. The record is in
    `evals/results/2026-10-28-studio-vs-1.0.1/`.
  - An earlier run of eval 6 on a draft, with the skill against no skill, is in
    `evals/results/2026-10-27-studio-grade/`.
  - The eval records now state that one MCP server tried to start in every session and failed, so no MCP tool was
    available.

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
