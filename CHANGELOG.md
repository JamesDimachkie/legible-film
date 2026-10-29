# Changelog

## 1.2.0 (2026-10-28)

The film kit, sound and render tools, and a kinetic-type register: the skill can now make a film end to end, and the
film checks its own facts, reading time and flashing before it renders.

- **The film kit** (`assets/kit/`, `references/kit.md`): a small, dependency-free browser engine for type-led films,
  from a calm launch film to beat-cut kinetic type.
  - Blocks for the common devices (type on the beat, a terminal, a number, the name, a still, a thread, a denial, an
    end card, a running caption), laid out in frame units so one timeline renders 16:9, 9:16 and 1:1.
  - A camera rig that never parks, a palette built from one brand colour as tinted neutrals, variable type fitted to
    the frame, effects registered so flashing can be predicted.
  - `film_check.py` before every render: claims bound to the facts file, contrast at every ground, measured reading
    windows, predicted flashing, a determinism lint; it writes the cue list, the captions and the QC declarations.
  - `new_film.py` to start a project; a starter film and a showcase film for a fictional product.
  - Loops: `loop: true` holds the camera and the preflight checks that the end returns to frame 0; a tracked
    node that never paints (no size, transparent, nothing to draw) is a preflight error naming its block.
- **Render:** `film_render.py` (with `film_capture.mjs`) renders kit films with cut-aware motion blur averaged in
  linear light, optional bloom and grain, and the BT.709 colour path; `motion_blur.py` does the same for any engine
  rendered at a multiple of the frame rate. `--res N` sets the output's short side; an odd side is refused.
- **Make:** `make_film.py` takes a kit film from preflight to delivered, checked files in one command; `--loop`
  measures the seam on each file, `--web` adds a VP9 WebM from a lossless render and a poster from frame 0.
- **Sound:** `tempo_map.py` measures a track's tempo, phase, downbeats, drops and drift and computes the offset that
  lands a drop on a chosen beat; `make_sound_kit.py` synthesises a rights-clean draft palette and temp track with
  exact sync points; `mix_cues.py` builds the effects stem, the bed and the mix from the cue list and
  `assets/templates/palette.json`, and reports hits that are missing, smeared or under the music. `cue_onsets.py`
  checks `end` sync points.
- **Measurement:** `motion_scan.py` reports pace (still share, still stretches with their beats, cuts per 10 s) and
  checks a declared pace contract; `qc_file.py` checks the H.264 level and the file size.
- `references/kinetic-type.md`: the register of big words on a beat, from brief to beat sheet, its devices with
  their truth checks, pace you can measure, joins that are moves, sound, render, and its safety limits (flash
  budgets for ground changes, readable qualifiers, motion).
- Reference updates:
  - tinted neutrals from the brand colour, a world texture that shows camera moves, how the thread is drawn
    (`picture.md`);
  - measuring a track's grid before building on it (`timing.md`);
  - the palette manifest, the draft kit and the mixer (`sound.md`);
  - composition rather than empty space, pricing a whole set before the first paid run, refused prompts, marks on
    generated objects, source pixels for pushes (`generation.md`);
  - open museum collections and a house style from public-domain art (`assets.md`);
  - measuring the pace of references, and naming a look by its cause (`studio.md`);
  - interface motion by job for reconstructions (`product-demos.md`);
  - motion blur that slides at cuts and long shutters for whips (`finishing.md`);
  - the kit in the engine table, untrusted SVG, measuring layout once (`engines.md`);
  - the preflight, pace, beat-grid stills and whip frames (`qc.md`);
  - one timeline for every aspect ratio (`formats.md`);
  - numbers a film states about itself, claims bound to facts (`claims-and-rights.md`).
- Evaluations: eval 8 (a kinetic teaser plan) and eval 9 (a film built with the kit).

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
