# Engines and tools

Which tool for which job, the rules every code-rendered engine shares, and verified traps. Versions and terms
were checked on 2026-10-27; tools in this space change weekly, so confirm with each tool's `--help` and docs
before relying on a flag.

Contents: [1. Choose by job](#1-choose-by-job) · [2. Rules for every code-rendered engine](#2-rules-for-every-code-rendered-engine) ·
[3. Traps met in browser-captured renders](#3-traps-met-in-browser-captured-renders) · [4. HyperFrames](#4-hyperframes) · [5. Remotion](#5-remotion) ·
[Tesseract](#tesseract) · [6. Blender](#6-blender) · [7. Editing and analysis](#7-editing-and-analysis) · [8. Capture](#8-capture) ·
[9. Speech and captions](#9-speech-and-captions) · [10. Audio](#10-audio-tools) · [11. QC beyond the scripts](#11-qc-beyond-the-bundled-scripts) ·
[12. Agent-facing tools](#12-agent-facing-tools) · [13. Machine hygiene](#13-machine-hygiene)

## 1. Choose by job

| Job | Default | Alternatives and when |
|---|---|---|
| Type-led launch films, teasers and kinetic type | **The film kit** bundled with this skill ([kit](kit.md)): blocks on a beat grid, the cue list, captions and QC declarations exported from the picture's own timeline, truth, contrast, reading and flash checks before rendering, and a cut-aware motion-blur render | any engine below when the film needs what the kit's blocks do not draw |
| Motion graphics, explainers, UI reconstructions | **HyperFrames** (HTML, CSS and a paused GSAP timeline; Apache-2.0) | **Remotion** for React teams and templated or data-driven video (check its licence); Revideo or Motion Canvas for generator-style TypeScript (Motion Canvas is effectively dormant); **Cavalry**, a motion designer's own timeline the agent drives through its MCP server, when motion feel matters and the person wants a scene to edit by hand (§12); **Tesseract**, when the person has it installed and chooses it ([Tesseract](#tesseract)) |
| Mathematical and diagram explainers | **Manim Community** (MIT) | HTML engines for UI-heavy pieces |
| 3D product shots, lit scenes, camera moves through space | **Blender** (headless CLI, Python API) | Three.js inside an HTML composition for stylised 3D |
| Assembling, trimming, muxing, encoding, captions, measuring | **FFmpeg** | MoviePy 2.x for quick scripted cuts in Python |
| Editing real footage with a human in the loop | an NLE project (Kdenlive/MLT, DaVinci Resolve) | OpenTimelineIO to exchange cut lists; auto-editor for first-pass silence cuts |
| Recording a real interface | scripted browser capture (Playwright screencast) for review clips; a deterministic reconstruction for the deliverable | OBS for screen plus camera; FFmpeg screen-capture devices |
| Transcripts and caption timing | **WhisperX** for word alignment | faster-whisper or whisper.cpp for speed on CPU; FFmpeg 8+ `whisper` filter where the build includes it |
| Generated plates, voice, music, effects | the provider the person approves, within their cap | see [claims-and-rights](claims-and-rights.md) for terms |
| Review with collaborators: watching a version, notes on moments, drawings, replies | **Flask** ([flask.do](https://flask.do)), through its MCP server ([review](review.md) §1) | the local Screening Room (`screen.py`) for private work on this machine |

Pick one engine per designed piece and keep one clock for the film. A film drawn in an engine has its page as the
timeline, and its cue list is exported from that page (§2). A piece inside footage renders at the film's size and
frame rate, and the host places it (`~ over`, a cutaway or a picture line), so the host stays the only timeline. Two
engines inside one piece means two timing systems to keep in agreement.

## 2. Rules for every code-rendered engine

These make a render repeatable and seekable; most render bugs break one of them.

- **Every frame is a pure function of time.** No wall clock (`Date.now`, `performance.now`), no unseeded
  `Math.random` (use a seeded generator), no CSS transitions or keyframe animations in a captured page,
  no `requestAnimationFrame` loops that advance state, no network fetch during the render.
- **One timeline, paused and seeked.** Animations are driven by seeking the timeline to each frame's time,
  never by playing it.
- **Fonts and assets are ready before frame 0**, and text is laid out only after every face and weight in use has
  loaded; text measured against a fallback font keeps the wrong width. Ship fonts as local files. Measure each
  element once, at build time, while it is displayed (an element under `display: none` measures zero), and keep the
  numbers; measuring during the render makes a frame depend on the order frames were drawn.
- **A supplied SVG is untrusted input.** Inlined into the page, it can run script. Remove scripts,
  `foreignObject`, event-handler attributes and `javascript:` links before inlining it, or draw it as an `<img>`,
  which runs none.
- **Frame-exact state.** Anything that counts or switches (typed characters, a caret, a counter, a label) is computed
  from the whole frame number, so motion-blur samples taken between frames agree with each other.
- **Seek tests:** seek to an important time, to a distant time, and back; compare. A stateful bug shows as a
  difference. Identical hashes of blank frames prove nothing: confirm the root has its intended size and the
  frames have varying content.
- **A promise that resolves to a GSAP timeline never settles:** timelines are thenable. Return a wrapper
  (`{ tl }`) from async builders, and return a boolean, never the timeline, from a browser-evaluate predicate.
- **Before rendering, search the composition** for anything that runs on the wall clock or the browser's own
  animation engine (`Date.now`, `performance.now`, `Math.random`, CSS `transition`, `animation`, `@keyframes`) and
  for fonts or scripts loaded from the network. Each hit needs a reason to stay.
- **Know your pipeline's noise floor.** Two renders of one source are rarely bit-identical after the finish and
  encode: in one HTML pipeline, unchanged stretches between re-renders read 42-45 dB PSNR. Measure that range once
  with `compare_versions.py`; a difference outside it, or one that wanders between renders of an unchanged source,
  needs explaining before QC.

When a render looks wrong, reproduce the symptom in a short window on the actual renderer before changing any shared
helper, and narrow it down by switching parts of the composition off until it disappears.

### Cue export, the frozen copy and the render

The page declares its timing and the cue list is exported from it, so picture and sound share one clock
([timing](timing.md) §0). `node film_capture.mjs cues DIR --out DIR/cues.json` (or a local URL with `--root DIR`)
reads the kit's `__lf` cues (`--source lf`), a page's `window.__cues` once `window.__cues_ready` is true
(`--source declared`; `--global` and `--ready` rename them), or timeline labels plus the `lf-cues` block
(`--source timelines`, §4). Without `--source` it picks timelines, then lf, then declared. It exits 0 written, 1
written with a look (`--verify`) and 2 refused. The kit exports through `film_check.py`, the same freeze underneath.

- **The frozen copy.** Export freezes the page first (`cue_list.py freeze PAGE --entry index.html`; the exporter
  passes the page a URL names). Freeze starts at the entry page and follows its static references (HTML `src`,
  `href`, `srcset` and `poster`; CSS `url()` and `@import`; JS imports, a HyperFrames `data-composition-src`
  included); a URL inside a data string is not a reference. Every version-pinned network URL is fetched once, stored
  in the copy and hashed (`gsap@3.14.2` is pinned; `gsap@3` is not); a file referenced by `../` or an absolute path
  from outside the page is copied in under `_outside/`, and a `../` that stays inside the page is kept in place.
  Export loads the copy with every request intercepted, scans every other file it saw the page load, and keeps the
  copy as `.lf-frozen/<snapshot_sha256>/` inside the page, a folder the fingerprint skips. A file nothing reaches is
  copied and fingerprinted but not scanned; the list names it under `export.not_loaded_not_scanned`. An unpinned
  URL, a failed fetch, an outside reference, a reference to an excluded file, a system font, or a request the copy
  does not hold makes the binding `unverified`; a request that leaves the copy is recorded and let through, so the
  page still exports.
- **`--verify`** seeks a frame either side of each turn and contact and flags "no frame change" as a look. Answer each
  flag by fixing the picture, declaring a sound-only cue `picture: none`, or declaring a held frame `picture: held`
  with a decision. `--candidates` lists motion peaks as unconfirmed suggestions.
- **The render reads the kept copy, never the live page.** `project.py add-version PROJECT --cues cues.json --render
  "CMD" --file OUT` runs CMD with `{page}` set to the kept copy and `{out}` to OUT, under the render lock (it waits
  for `--min-free-gib`, default 3, up to `--wait-min`, default 20) with outbound network blocked, and refuses when
  the copy or the live page changed since export. OUT must be new, under the page's `renders/` or outside the page,
  and CMD's output must name it; for HyperFrames, `--render "npx hyperframes render {page} -o {out}"`. Name the
  output in CMD, since engines' default outputs are timestamped and cannot be told apart. The kit's
  `film_render.py DIR --cues DIR/cues.json --out OUT` renders its kept copy the same way and writes the receipt
  `OUT.manifest.json`.
- **Binding.** A render whose inputs are shown closed binds `receipt`. The kit's renderer traces every request
  (`render_trace: traced`); another engine renders with outbound network blocked (`render_trace: blocked`, the
  mechanism recorded). An engine that can be neither traced nor blocked records `render_trace: none` and binds
  `unverified`, which the sync group reports as a look.

## 3. Traps met in browser-captured renders

Each of these was hit in production with an HTML engine (HyperFrames, on Chromium):

- **A from-state shows at t = 0.** A single `fromTo` showed its starting values from the first frame, because GSAP
  applies them when the tween is created. Add `immediateRender: false`, or give the element a CSS baseline and animate
  with `to`.
- **Opacity overshoots.** An opacity tween on an overshooting ease read 1.12; animate opacity on its own
  non-overshooting curve.
- **An exit fade is still visible on the last frame.** A fade ending exactly at the composition's end left content in
  the final frame; finish exit fades a few hundredths of a second early, on a gentler curve.
- **Stills and the render disagree on type.** With generic font families, the snapshot and the render picked different
  fonts; shipped `@font-face` fonts made them match.
- **Word spaces collapse.** Spaces between inline-block word spans collapsed before the last word in the render; give
  the spans a margin instead of relying on the space character.
- **Dark brand tints shift.** 8-bit 4:2:0 encoding flattened a near-black brand tint; judge dark tones on the encoded
  file, not the browser.
- **Placed audio comes out quiet.** An `<audio>` element in the composition rendered 11.6 dB below its source; mux the
  mastered mix instead.
- **A standalone harness never sees the timeline.** Waiting on the default animation-frame polling never fired in a
  headless shell; poll on an interval, and inject `window.__timelines = {}` before the page loads.

Measured while building this skill's own capture worker (Chromium 156 through Playwright, on Windows):

- **A clip in CSS pixels returns CSS pixels.** At a device scale factor of 2, a DevTools screenshot whose clip scale was
  1 came back at half the intended size (320x180 for a 640x360 render); capture at the device scale, then check the
  decoded frame's size. After a build, when a capture comes back the wrong size, cuts an edge, swaps a font or drifts in
  timing between seeks, run `film_capture.mjs calibrate` as the remedy. It checks this machine's capture of size, all
  four edges, a large 3D layer, fonts and seek determinism. It belongs to rendering, after the film exists, never to
  planning.

General browser-animation hygiene that prevents others: animate position with transforms rather than layout
properties (layout positions round to whole pixels, so slow drifts step); keep any blur that animates on small layers;
overscan a plate that is blurred so its transparent edge never enters the frame; and load gradients as pre-rendered,
dithered images when a soft ramp bands.

## 4. HyperFrames

HeyGen's HTML-to-video framework (Apache-2.0; release 0.8.223 was the latest when checked on 2026-10-31; pre-1.0,
with releases most days; Node 22+ and FFmpeg required). Pin a version per project.

- **Loop:** `npx hyperframes init <dir> --non-interactive`, author, `lint`, `check --json` (the browser gate: console
  errors, layout overflow and occlusion, contrast with a suggested compliant colour, audio, and craft warnings such
  as a line on screen too briefly to read, a still stretch, text below a size floor and an empty first frame),
  `snapshot --at t1,t2` for stills, short `render` windows, then the full render. Fix lint errors first: with lint
  errors, the layout and contrast audits can report "0 samples" and look clean.
- **Motion assertions:** a `*.motion.json` sidecar beside a composition states intent (`appearsBy`, `before`,
  `staysInFrame`, `keepsMoving`) and `check` verifies it on the seeked timeline. Write the score's anchors as
  `appearsBy` at their word times so a late landing fails the check.
- **History** (marked a trial in 0.8.223): the CLI keeps every write; when the person also edits in HyperFrames' app,
  `history --since mine --who <you>` at the start of a turn shows what they changed, and `history undo` reverts
  only your own edits.
- **Transcription:** `npx hyperframes transcribe` uses NVIDIA Parakeet when installed, otherwise whisper with an
  English-only model that renders non-English speech in English; pass `--model small --language <code>` for
  other languages, or transcribe with this skill's `transcribe.py`.
- **Determinism:** every timed element has `class="clip"`, `data-start` and `data-duration`; each composition
  registers one paused GSAP timeline keyed to its `data-composition-id` (write the literal
  `window.__timelines["<id>"] = tl`; wrapped forms have tripped the linter). No `repeat: -1`, no timers or
  unseeded randomness, and every asset loaded before frame 0. `render --docker` pins Chromium,
  fonts and the encoder for bit-stable output across machines.
- **`render` reads the live project folder** during the render. Render the frozen copy the cue export kept, through
  `project.py add-version --render` (§2), and give `--output` an explicit path, since the default is a timestamped file
  in `renders/`.
- **Audio:** a placed `<audio>` element has rendered well below its source level; every `<audio>` needs an
  `id`. Deliver by muxing the mastered mix onto the rendered picture.
- **Privacy:** `snapshot --describe` sends frames to a hosted model; keep it off for private work. Telemetry is
  on by default (`HYPERFRAMES_NO_TELEMETRY=1`, `DO_NOT_TRACK=1`, or `npx hyperframes telemetry disable`);
  GSAP loads from a CDN unless `HYPERFRAMES_GSAP_BASE_URL` points to a local copy. Load it from a pinned version
  (`gsap@3.14.2`), so the frozen copy can vendor it and the render binds.
- **Workers:** each render worker is a separate Chrome (roughly 256 MB each); on a small machine use one or
  two.
- **Snapshots floor to the frame grid:** a time between frames returns the earlier frame; ask for times that
  sit on frames (or slightly after).
- **Its own skills, by host.** Use HyperFrames' skills for the engine's mechanics and this skill for the film, its
  clock and its checks. In Claude Code, install the plugin (`claude plugin marketplace add heygen-com/hyperframes`,
  then `claude plugin install hyperframes@hyperframes`) and open it with the Skill tool as `hyperframes:hyperframes`;
  a standalone install (`npx skills add heygen-com/hyperframes`) names it `hyperframes`. In Codex,
  `npx hyperframes skills update` installs the core skills into the user's shared skills folder, `~/.agents/skills`,
  which Codex reads in every project; start a new session, then use the `hyperframes` skill from the skill list
  (`$hyperframes`). `npx hyperframes skills check` says whether a host sees them.
- **Declaring cues.** Labels on the composition's paused timeline (`window.__timelines["<data-composition-id>"]`)
  give time, and a JSON block on the page gives meaning; the exporter merges them by id. A label is `cue:<id>` (a
  cue's start), `cue:<id>:end` (a span's end) or `section:<id>` (a section's start; it ends at the next section or
  at `section:<id>:end`), offset by the composition's `data-start`. The page carries:

  ```html
  <script type="application/json" id="lf-cues">
  {"sections": {"open": {"clock": "speech"}, "drop": {"clock": "music"}, "hold": {"clock": "silence"}},
   "events": {
     "drop-in": {"scale": "turn", "sync": "attack", "lead_ms": -83, "role": "hit", "sound": "required",
                 "hero": true, "el": "#wordmark", "decision": "the hit leads the cut by two frames"},
     "type-run": {"scale": "follow", "role": "key", "run": true, "intent": "key density follows the typing"}}}
  </script>
  ```

  A label with no entry, an entry with no label, a span with no `:end` label, or a cue outside every section stops
  the export (exit 2) with the names; nothing is guessed. `el` gives the cue's `x` and `y` from the element's box at
  its time, for panning. A `window.__cues` entry may name `label` in place of `t`.

## 5. Remotion

React video framework (4.0.539 on 2026-10-26). **Licence:** free for individuals, for-profit organisations of
up to three employees and non-profits; other companies need a company licence (read the licence FAQ for
agency work). Official agent skills (`npx skills add remotion-dev/skills`) and a Claude Code plugin exist;
the hosted Remotion MCP server was shut down on 2026-10-26.

- Each scene is a pure function of `useCurrentFrame()`; `interpolate` extrapolates unless clamped.
- Render muted and mux the audio with FFmpeg; Remotion's own AAC output has been reported to carry encoder
  priming (a couple of frames of offset).
- `premountFor` affects Studio preview only, not renders.
- Set the colour space explicitly and verify the delivered tags ([finishing](finishing.md)).

### Faster renders of HyperFrames and Remotion projects (checked 2026-10-31)

[Strobe](https://github.com/hridaya423/strobe) (Apache-2.0; v0.1.0, first released 2026-10-31, one author) renders an
existing HyperFrames or Remotion project to the same MP4 with no code changes, keeping each frame on the GPU. Its own
benchmark of seven launch videos reports 2.8 to 7.3 times faster on an M4 Mac mini and 4.6 to 11.6 times on a Windows
PC with an RTX 4070 Ti. It ships for macOS on Apple silicon and Windows x64 only, uses the project's own Node and
`node_modules` (so Remotion's licence still applies), and is not tested here; downloading its binary is the person's
call. Its default `--mode fast` rasterises on the GPU and can land a level away from Remotion's pixels; `--mode
reference` matches them. Before using it for a deliverable, render a short range with both the engine and Strobe and
compare them with `compare_versions.py` against the pipeline's noise floor (§2), then check the file as usual.

## Tesseract

Tesseract is a proprietary video tool with its own agent skills (Edit Video, Motion Graphics) and a command line,
`tsrct`. This skill holds no Tesseract code, files or dependency, and has not run it. When the person has Tesseract
installed and chooses it, create, cut and insert hand the build to Tesseract's skills, and everything else stays here.

1. Write the brief and the frame as usual, and record `timeline: tesseract` in `film.md` ([project](project.md) §3).
2. Write the cue list as a plan: `cues.json` v2 whose picture is `{"kind": "plan", "sha256": null}`, with the sections,
   their clocks and the turns the build must land. It is unbound; every reader but the registration refuses it.
3. Stop at the hand-off and name it, with what to build in Tesseract, the brief, the frame and the plan it reads,
   and the command that brings the master back.
4. The exported master returns through `project.py add-version PROJECT --cues cues.json --file MASTER`, which
   screens each planned turn for a frame change on the returned picture and writes the bound list (provenance
   `plan-bound`); a turn with no frame change is a look (exit 1). Sound, checks and review then run here as on any path.

In cut, when Tesseract owns the cut, `film.md` holds the frame and front matter only, and the readable edit is
Tesseract's project. A `.tsrct` project reaches Premiere or After Effects through its own `tsrct-conv`; this skill's
hand-off to an editor stays `exchange.py write`, which needs no proprietary tool.

Its terms, quoted from Tesseract's `TERMS.md` (Mirage US LLC, last updated 2026-09-21). This skill does not claim to
have verified them:

> 2.2.2: "Nothing in these Terms grants you the right or license to [...] download, access, use, copy, modify, or
> otherwise exploit, in any manner, the Tesseract Plugin to develop, make, have made, train, improve, offer,
> distribute, license or sell any technology, product or service that serves as a substitute for, replicates,
> eliminates or reduces the need for, or otherwise competes with, the Tesseract Plugin"
>
> 2.2.3: "The license granted under these Terms does not authorize Commercial Use of the Tesseract Plugin by or on
> behalf of a Covered Business unless a separate written agreement executed by Mirage expressly authorizes that
> use", where a Covered Business is a for-profit business with annual revenue of US$1,000,000 or more.

Tesseract is proprietary. Read its terms before use; the choice is yours.

## 6. Blender

5.2 LTS and 4.5 LTS were current on 2026-10-22. Headless: `blender -b file.blend -o //render/frame_##### -F PNG -s 1 -e 240 -a`.
Arguments run in order, so put `-a` or `-f N` last. Run scripts with `-P script.py -- args`. Cycles GPU
backends: CUDA and OptiX (NVIDIA), HIP (AMD), oneAPI (Intel), Metal (Apple). Renders compete with browser
renders for memory; run one at a time.

## 7. Editing and analysis

- **FFmpeg** 9.0.2 (2026-09-18). Builds differ: whether `libass` (subtitles), `libvmaf` and `whisper` are
  enabled depends on the build (`ffmpeg -filters`). Tested commands are in [ffmpeg-cookbook](ffmpeg-cookbook.md).
- **Kdenlive / MLT `melt`** for scripted renders of an editable timeline; generating `.kdenlive` files by hand
  is brittle.
- **DaVinci Resolve** 21.1 moved advanced (and, by some reports, all) Python scripting to the paid Studio
  edition and added a native MCP server there; test on the installed version.
- **OpenTimelineIO** to exchange cut lists (FCPXML, EDL, AAF through `OpenTimelineIO-Plugins`); effects and
  transitions do not survive the round trip.
- **auto-editor** (now a Nim binary; the PyPI package is stale) for first-pass dead-air removal; tune its
  thresholds.
- **PySceneDetect** or FFmpeg's `scdet` for shot boundaries in footage.

### Optional subject matte models (checked 2026-10-31)

| Model | Code and weight licence | Exact ONNX weights | Use |
|---|---|---|---|
| MODNet, Xenova conversion | [Code: Apache-2.0](https://github.com/ZHKKKe/MODNet/blob/master/LICENSE); [weight model card: Apache-2.0](https://huggingface.co/Xenova/modnet) | [Pinned download](https://huggingface.co/Xenova/modnet/resolve/fa2fa546052fba4c08921230a26cc69a333fca12/onnx/model.onnx); SHA-256 `07c308cf0fc7e6e8b2065a12ed7fc07e1de8febb7dc7839d7b7f15dd66584df9` | Optional CPU portrait backend. It cannot select one person with a box; inspect every result. |
| BiRefNet Lite, Studio Ludens 512 conversion | [Code: MIT](https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE); [converted weights and licence: MIT](https://huggingface.co/studioludens/birefnet-lite-512); [upstream weights: MIT](https://huggingface.co/ZhengPeng7/BiRefNet_lite) | [Compared file](https://huggingface.co/studioludens/birefnet-lite-512/resolve/962e67969ec6acec9c19fab76acee4f5e22e990c/onnx/model.onnx); SHA-256 `1cb0fb360dadd15af77c639085d77a9df67db0c64315560c3de005f676345ac2` | Comparison only; not installed or shipped by this skill. |

The optional MODNet download is about 26 MB and requires `setup.py --install spatial --download` with consent.
The runtime checks its hash before inference and records the model URL, hash and licences in each layer. A low
flicker measure cannot establish that the subject or its edges were found correctly.

### Optional speaker model (checked 2026-11-05)

`map.py speakers --shared` compares voices on one track ([footage](footage.md) §14) with [SpeechBrain's
ECAPA-TDNN](https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb) (Apache-2.0), through a [community ONNX
conversion](https://huggingface.co/vedk00/ecapa-voxceleb-speaker-embedding-onnx) pinned to revision `a9cb9321b07b` and
each file's SHA-256 in `lineup.py`. It is about 84 MB, downloads only with `--download` after its size is named, runs
through onnxruntime and sends nothing out. SpeechBrain does not publish this conversion, so a hash that does not match
is refused rather than updated.

## 8. Capture

- **Playwright** (1.64): set the viewport and the video size to the target resolution (the default video is
  scaled to fit 800x800); recordings default to 25 fps; the file completes only when the context closes. The
  Screencast API delivers frames with timestamps. Real-time capture is not frame-accurate: in one test,
  in-page timing marks landed 0.1-0.4 s late against the recording. Find event times by detecting pixel
  change in the region that moves, and select exact frames by timestamp after decoding.
- **Chrome DevTools screencast** sends frames only when the page repaints (variable frame rate). To keep video
  time equal to session time, write the latest frame into each fixed output slot (for example every 1/30 s)
  and test the recorder against a clock page before trusting its timing.
- **Puppeteer** 25.x replaced `page.screencast()` with `page.record()` (Chrome 153+, needs FFmpeg).
- **OBS Studio** 33 with its built-in WebSocket server (port 4455) for scripted screen and camera capture.
- **FFmpeg devices:** `gdigrab`/`ddagrab` (Windows), `avfoundation` (macOS), `x11grab`/`kmsgrab` (Linux);
  set a constant output frame rate and verify it with ffprobe.

## 9. Speech and captions

| Tool | Licence | Strength |
|---|---|---|
| WhisperX | BSD-2-Clause | best word-level alignment (forced alignment on top of faster-whisper); diarisation needs a gated model |
| faster-whisper | MIT | fast on CPU with int8 |
| whisper.cpp | MIT | portable CPU and GPU builds; the engine behind FFmpeg's `whisper` filter |
| openai-whisper | MIT | reference implementation; slowest |

All of them can hallucinate over silence and music; use voice-activity detection and check every caption
against the audio. Burn captions with FFmpeg's `subtitles` filter (needs libass), or render styled captions
in the composition engine.

## 10. Audio tools

- **FFmpeg filters:** `ebur128` (loudness, `peak=true` for true peak), `loudnorm` (two-pass normalisation),
  `silencedetect`, `astats`, `adelay`, `afade`, `alimiter`.
- **pyloudnorm** (BS.1770 meter in Python), **ffmpeg-normalize** (batch loudnorm).
- **librosa** 1.0 (requires Python 3.12+) for onset and beat tracking.
- **Bundled with this skill:** `tempo_map.py` (tempo, phase, downbeats, drops and drift of a track),
  `make_sound_kit.py` (a synthesised, rights-clean starter palette and temp track with exact sync points),
  `conform.py` (a take fitted to the spotted cue list's sections), `mix_cues.py` (the effects stem, bed and mix from
  the spotted list and the palette) and `listen.py` (measure, transcript, sync, sheet and labels; [sound](sound.md)
  §13).
- **[earshot](https://github.com/Leonxlnx/earshot)** (Leon Lin, MIT; young) gives agents measurements and labels for
  sounds, cue sync sheets and code-made effects. The skill's `listen.py` follows its shape, takes its launch-film
  reference ranges and credits it in `NOTICE`. Finding sounds by description, realness scores, A/B comparison,
  code-made effects and its MCP server stay in earshot. Its rule holds here too. Times and levels are meters, labels
  in a mix are half right, and taste is out of reach.
- **Demucs** for stem separation: code MIT, pretrained-weights licence unclear (see
  [claims-and-rights](claims-and-rights.md)).
- SoX upstream has not released since 2015; prefer FFmpeg.

## 11. QC beyond the bundled scripts

- **MediaInfo** for a second opinion on container metadata.
- **VMAF** (Netflix, BSD-2-Clause-Patent; FFmpeg `libvmaf`) to compare an encode against its source when you
  change codec or bitrate. It does not judge whether the film looks right.
- **Photosensitivity:** `flash_scan.py` screens for WCAG 2.3.1. **EA IRIS** (BSD-3-Clause, build from source)
  is a fuller open screen and states it does not certify compliance. **Trace PEAT** is legacy (2017, Windows).
  **Harding FPA** is the commercial test UK advertising guidance expects; broadcast delivery specs often
  require a PSE test compliant with ITU-R BT.1702.

## 12. Agent-facing tools

- Video-understanding skills that extract frames and transcripts are useful for studying references. Check
  their data flow: at least one popular skill uploads local files to a hosted model whenever its API key is
  set, unless you choose its local engine.
- FFmpeg MCP servers are young convenience wrappers; an agent that knows FFmpeg can call it directly.
- Engine-specific skills (HyperFrames, Remotion) cover their own mechanics; use them for the engine and this skill
  for the film, its evidence and its QC.

### Cavalry, driven through its MCP server (checked 2026-10-31)

Cavalry (by Canva; free for individuals since 2.7, with a Canva sign-in) is a 2D motion-design application, and from
2.8 it runs an MCP server inside the app on `localhost:6768`, on by default. The agent reads `read_preamble`, looks
up the scripting API, layer types, docs and examples with the search tools, compile-checks a script with
`preflight_script`, builds with `execute_script` (JavaScript against the open scene), and sees its work with
`snapshot_layer`, which renders one layer or the whole
composition to a PNG at any frame (ask for `maxSize` 1024; the default is 256). Use it when motion feel matters more
than code: keyframes and easing on a motion designer's timeline avoid the one speed curve and stock perspective tilts
that give generated HTML motion away, and the person keeps a scene to adjust by hand.

- **Connecting.** Canva's package (`cavalry-mcp-server.zip`, on Cavalry's "AI automation with Claude" docs page) is a
  Node bridge to that port. Claude Desktop installs it as an extension; another client registers its
  `server/index.js` as a stdio MCP server (Claude Code: `claude mcp add cavalry -- node PATH/server/index.js`).
  Adding an MCP server changes the agent's tools, so the person does it, or says yes to it.
- **One Allow per session of Cavalry.** Cavalry asks the person to Allow each app (Claude Code, Codex, Claude
  Desktop) once each time Cavalry starts; the approval then holds for every session of that app until Cavalry quits,
  and Cavalry has no setting to keep it longer. Make the first Cavalry call `read_preamble`, before any building,
  while the person is there: tell them to click Allow in Cavalry, once, and that it lasts until Cavalry quits. Until
  they do, every tool answers "Cavalry has not approved this connection". The click is Cavalry's guard on an app that
  runs scripts on this machine, so it stays the person's.
- **What leaves the machine.** Tool results (scene structure, layer values, script output, snapshots) go to the
  agent's model provider, and while the person is signed in, Cavalry sends every script `execute_script` runs to
  Canva's checking service, which uses a third-party provider. Ask once per project, as for any upload, and keep
  client material out of a Cavalry scene unless the person agrees.
- **Into the film.** Before a long render, snapshot the key moments and set them beside the references
  (`look.py compare`). Render a PNG sequence at the film's size and frame rate from a script (`api.addRenderQueueItem`,
  `api.setGenerator(item, "generator", "renderPNG")`, `api.render`) and pack it with FFmpeg: a lower third or title
  over a transparent background (the composition's `backgroundColor` alpha 0) as a PNG MOV that keeps its alpha
  (`ffmpeg -framerate FPS -i NAME.%05d.png -c:v png -pix_fmt rgba NAME.mov`), placed with `~ over ALIAS` over the line
  it belongs to; a still graphic as one transparent PNG, placed the same way for its seconds; a full-frame piece as
  H.264, placed as a picture or a cutaway. Register a video with `map.py add --role broll` and a PNG with `--role
  still`. Cavalry's PNGs are tagged sRGB and the render keeps their values. Keep the `.cv` scene with the project as
  its editable source; every check then runs on the delivered file as usual.
- **Tested here** (2026-10-31, Cavalry 2.8.0 on Windows 11): a script client on the same bridge built a 3-second
  title and a 4-second lower third, `snapshot_layer` returned frames of each, the title's PNG render went through map,
  cut and check with its colours matching Cavalry's own render, and the lower third, packed as a PNG MOV, went over
  the example interview with `~ over` and through check. A fresh Claude Code session (`claude -p`) was refused until
  the person clicked Allow; the next two fresh sessions connected without asking, and one read the preamble, built a
  text layer, saw it with `snapshot_layer` and removed it. macOS is not yet tested.

## 13. Machine hygiene

- Run one heavy render at a time; check free memory before starting; prefer one or two workers on a laptop.
  `with_lock.py -- CMD` waits for the machine's render lock and for free memory (`--min-free-gib`, 3 by default)
  before it runs CMD, up to `--wait-min` (20 by default; exit 2 when the wait runs out), and reports a lock older
  than 45 minutes rather than removing it. Size workers from one worker's measured peak memory at the
  target resolution, not from a guess: a 4K browser worker with motion-blur accumulation needs several times what a
  1080p one does.
- Render from a frozen copy of the source so edits during a render cannot leak into it.
- Stop only processes you started, by their own PID; a pattern kill on a shared machine stops other people's
  jobs. Leave other jobs' lock files alone.
- Some renderers cancel when the launching shell exits; keep the owning process alive and collect the
  renderer's own completion record.
- Turn off telemetry you do not want (HyperFrames, the `skills` CLI: `DO_NOT_TRACK=1`).
