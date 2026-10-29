# The film kit

A small browser engine for type-led films, bundled in [assets/kit/](../assets/kit/): ten blocks for the common devices
(type on the beat, a terminal, a number, the name, a still, a thread, a denial, an end card, a running caption, a
dither field), a camera that never parks, a palette built from one brand colour, and checks that run on the film's own
timeline before anything renders. Every frame is a pure function of time; the page implements `window.__lf`, so the
renderer and the checks can drive it. Every option is in [BLOCKS.md](../assets/kit/BLOCKS.md).

Contents: [1. When to use it](#1-when-to-use-it) · [2. Set up](#2-set-up) · [3. The loop](#3-the-loop) ·
[4. Writing the spec](#4-writing-the-spec) · [5. What the checks prove](#5-what-the-checks-prove-and-what-they-do-not) ·
[6. Gates people can watch](#6-gates-people-can-watch) · [7. Sound](#7-sound) · [8. Your own device](#8-your-own-device) ·
[9. Limits](#9-limits)

## 1. When to use it

- **Use it** for launch films, teasers, kinetic type, short explainers and end cards whose picture is type, simple
  interface, drawn devices and stills: it gives you the cue list, captions, reading windows and QC declarations from
  the picture's own timeline, and a cut-aware motion-blur render.
- **Use another engine** ([engines](engines.md)) for real interface code, complex layout, live footage, 3D scenes or
  anything its blocks do not draw. A kit film can still include a picture or a rendered clip as a still or a plate.

## 2. Set up

- Python 3.9+ with numpy and Pillow, FFmpeg, Node 18+, and Playwright with a Chromium (`npm install playwright-core`
  in the project, or point `--playwright` or `LF_PLAYWRIGHT_MODULE` at an installed package; the tools reuse any
  Chromium Playwright has already installed and never download one).
- `python scripts/make_film.py --doctor` checks all of it and prints the one command that fixes each missing piece.
  `python scripts/kit_selftest.py --require` runs synthetic capture and render contract checks on this machine (without
  `--require`, a missing dependency is a skip, not a failure). A pass does not establish a particular film's
  playback, colour or every delivery size.

## 3. The loop

1. **Start a project:** `python scripts/new_film.py my-film --brand '#3D7BFF'` (or `--from atlasfold` for the
   showcase). It never overwrites a file.
2. **Facts first:** replace `facts.json` with the product's facts ([claims-and-rights](claims-and-rights.md)) and
   bind each claim the film registers to its fact. Preflight checks registered text, not every picture or implied
   claim; review the whole film against the evidence.
3. **Write `film.js`:** one block per scene, in beats when music is the clock (§4).
4. **Preview:** serve the folder (`python -m http.server --directory my-film 8000`) and open it. Space plays; `,` and
   `.` step a frame; the arrow keys step a beat; S shows the safe area, R the reading states, L the ground luminance.
5. **Preflight** at every size you will deliver: `python scripts/film_check.py my-film --size 1920x1080`, then
   `--size 1080x1920` (add `--res N` when the render scales the frame, so type size and the large-text contrast rule
   are judged at the delivered size). Fix every error; read every warning.
6. **Stills** of the hardest frames in every size, at full size and at feed size, judged as [picture](picture.md)
   says: with the preview served, `node scripts/film_capture.mjs stills http://127.0.0.1:8000/?render --at 2.5,b12
   --size 1080x1920 --out qa/stills`, or a quick `make_film.py --preview` and `frame_sheet.py` on its renders.
7. **Make:** `python scripts/make_film.py my-film --sizes 1920x1080,1080x1920 --samples 4` runs preflight, sound,
   render, mux, the QC battery and the declared-cut check, and writes `deliver/` with a filled delivery report.
   `--preview` renders one sharp sample a frame for a quick look; `--resume` skips finished steps in the same
   output folder (a copied or moved folder runs every step again). `--res N` sets each output's short side (720
   makes 1280x720 and 720x1280; an odd side is refused with a `--res` that works), and the preflight judges type at
   that size. A loop (`loop: true` in the spec, or `--loop`) gets its seam measured on every delivered file, the
   WebM included; `--web`
   adds a VP9 WebM encoded from a lossless render and a poster from frame 0, for a landing page. A template
   inside the kit (`assets/kit/films/atlasfold`) can be made directly: it is copied with the kit to `OUT/project/`.
8. **Look, then people:** read the sheets in `qa/`, write the weakest point into the report, and ask a person to watch
   at normal speed, muted at feed size, then with sound ([review](review.md)). Until they have, the film is
   **unwatched** and its sound **unheard**.

## 4. Writing the spec

- **Choose the device by its job,** not its look. The register's devices and their truth checks are in
  [kinetic-type](kinetic-type.md) §3; a calm film uses fewer hits, longer holds and quieter joins from the same blocks.
- **Bind every claim:** a text with role `claim` carries its fact id and must match the fact's display exactly; a
  qualifier matches `label_beside_value` and sits beside its claim. Headlines and texture carry no facts.
- **Time in beats when music is the clock:** `clock({bpm, offset})` gives `T.b(n)`; take the tempo and offset from
  `tempo_map.py` on the chosen track ([timing](timing.md) §9), and mark the drop shot with `drop: true`.
- **Declare the contract:** `pace` (for example `{max_still: 0.6, max_still_share: 0.4}`) when the register calls for
  one; claims, names and interface lines declare their reading holds as rests by default, so a held claim is never
  scored as a stall. Pace and cue spacing are guides: look and listen at the measurements and let the reviewer decide.
- **Iterate sound:** pass `--sound-only` with the same film, sizes and `--out` to reuse verified picture renders.
  The make checks the picture source and cue hashes, versions the deliverable, and reruns audio checks.
- **Ground changes are flash budget:** every full-frame change between light and dark counts ([kinetic-type](kinetic-type.md)
  §8); the Type block warns when a run of flips crowds the limit.
- **Tall frames:** blocks lay out in frame units, take the condensed width and stack; check the tall stills rather
  than assuming. A shot can give its own tall line breaks (`tall`).
- **Supplied brand wins:** pass the brand's fonts (`fonts`) and colours (`palette`); the bundled fonts (Mona Sans and
  Geist Mono, SIL OFL) are defaults.

## 5. What the checks prove, and what they do not

`film_check.py` reads the page's own state on every frame:

| It reports | From | It cannot tell you |
|---|---|---|
| Facts mismatches, digits in unbound text | each registered text against `facts.json` | whether the picture implies more than the words ([claims-and-rights](claims-and-rights.md) §3) |
| Reading windows (`in`, `readStart`, `readEnd`, `out`) against a reading rule | opacity, scale, blur, safe area and cover per frame | whether a first-time viewer reads it in time |
| WCAG contrast of every text against its ground, judged at the delivered size | known colours | contrast over a busy picture beyond its plate |
| Predicted flashing and red flashing | the ground timeline, flashes, plates, the type and every tracked node as its element paints | flashing in a clip or in drawing nobody tracked; a tracked node it cannot draw (an SVG, a video) marks the prediction incomplete; `flash_scan.py` screens the rendered file |
| Regular-pattern risk (the regulator's criteria) | the kit's own textures and dither | patterns inside supplied images |
| Jumps, strobing speed, competing onsets, invalid geometry, a loop seam | each tracked element's position, size, orientation and opacity | whether the motion feels right at speed |
| Determinism and network use | a lint of the film and blocks; requests after ready | impurity in code it cannot see |

The rendered file is the film: `make_film.py` runs the delivered-file battery ([qc](qc.md)) and checks that every
declared cut appears in the render within a frame.

## 6. Gates people can watch

The kit makes the watchable gates of [studio](studio.md) §5 cheap:

- **Concept sketches:** two or three short specs that differ in the idea, rendered with `--preview` over the draft
  temp track.
- **Styleframes:** stills of the hardest frames in every size, at full and at feed size.
- **An animatic:** a `--preview` render of the whole film with `?animatic` in the page URL (time, frame, bar and
  beat, and the scene's name in a corner), so notes can name an exact moment ("at bar 5, beat 3").

## 7. Sound

The kit exports the cue list with each event's role and sync point. `make_film.py --sound draft` synthesises a
rights-clean palette and a temp track at the film's tempo with its drop and stop, and `mix_cues.py` places every take
by its sync point ([sound](sound.md) §6). Replace roles with chosen takes in `palette.json`, keep the cue list as the
contract, and let the listener decide.

## 8. Your own device

When no block fits, define one with `kit.block` (the Atlasfold film's photo-to-map fold is an example): set node
properties only in `update(t)`, register texts, cues, cuts, rests and fast windows through the context, and `track`
any element that moves so the motion checks see it. Measure layout once at build time ([engines](engines.md) §2).

## 9. Limits

- Its checks model the page; they predict, and the encoded file is checked separately. A film can pass every check
  and still read as busy, fast or flat at speed.
- Chromium is the tested renderer. Rendering costs roughly one browser per worker; on a laptop render 1080p with one
  worker and keep 4K for when the destination needs it ([finishing](finishing.md) §2).
- It draws type, simple interface, drawn devices and stills. Real product interfaces and footage come from their own
  engines and recordings, labelled for what they are ([product-demos](product-demos.md) §5).
