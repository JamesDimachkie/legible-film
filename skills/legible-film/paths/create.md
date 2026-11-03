# Create: a new film drawn in an engine

**Covers** launch films, motion graphics, social posts, loops, stings, kinetic type, explainers drawn in code, lyric
videos and generated montages.

**Timeline owner.** A **page** (the kit's `film.js`, a HyperFrames page, or a Tesseract project when the person
chooses it). The page is the clock; the cue list, captions and checks are exported from it, never typed beside it.

## Steps

1. **Frame.** `project.py init PROJECT --path create --timeline page --page DIR` writes `film.md` front matter with
   the frame fields, each `missing` until `--what`, `--audience` or `--why` gives it as `assumed`
   ([project](../references/project.md) §3). Fill what the request gives and ask once for the rest. Done when each
   field is confirmed, assumed or waived with a reason, and only missing fields were asked.
2. **Look and concept.** When the look is open, read [look](../references/look.md) and settle it first. Read
   [story-and-score](../references/story-and-score.md) with its [treatment](../assets/templates/treatment.md), then
   write three concepts that are three different films, choose one, and have a reviewer who did not write it judge the
   concept and its score ([plan review brief](../assets/templates/plan-review-brief.md) C). When the film makes a claim,
   read [claims-and-rights](../references/claims-and-rights.md) and [sources](../references/sources.md) before you write
   it. Then read [timing](../references/timing.md) §0 and write the cue sheet, a clock per section and a decision per
   turn. When the chosen concept needs paid or generated material (footage, images, music or a voice), stop there and
   ask for the spend in your reply, with what it buys; generate nothing until the person says yes. Read
   [generation](../references/generation.md) before the first generation. Done when the sheet names every section's
   clock and every spend the concept needs has the person's yes.
3. **Build.** Read [picture](../references/picture.md) as you build, and [timing](../references/timing.md) §5-8 for
   frame arithmetic, reading windows and holds. When the film is type-led, read [kit](../references/kit.md) and
   [kinetic-type](../references/kinetic-type.md); when an interface is on screen,
   [product-demos](../references/product-demos.md); when it uses outside footage, [assets](../references/assets.md);
   when the destination sets its size or length, [formats](../references/formats.md); when flat art moves in depth,
   the layers-in-depth recipe in [picture](../references/picture.md) §8. Declare sections and cues on the page with
   kit `cue()`, `window.__cues` on any page, or HyperFrames timeline labels plus the `lf-cues` block.
   For HyperFrames, open its skill through your host. In Claude Code use the Skill tool with `hyperframes:hyperframes`;
   in Codex use the installed `hyperframes` skill from its skill list ([engines](../references/engines.md) §4 gives
   each host's install). Export with `node film_capture.mjs cues DIR --out DIR/cues.json --source timelines
   --verify`, or for the kit with `film_check.py DIR --verify-cues`, which writes `DIR/cues.json` through the same
   export. Both freeze the page with `cue_list.py freeze`, starting from its entry page, and keep
   `DIR/.lf-frozen/<snapshot_sha256>/` for the render. Done when `cues.json` v2 carries the page fingerprint and the
   snapshot hash, and every "no frame change" flag is answered by a fixed picture, a cue declared `picture: none`, or
   a held frame declared `picture: held` with a decision.
4. **Sound.** A film silent by the person's decision skips this step: record it with `screen.py decide PROJECT
   --category sound --subject audio --decision "silent by decision: no audio stream" --by person`, and make no music,
   conform or mix. Otherwise read [sound](../references/sound.md), and [assets](../references/assets.md) for outside
   music or effects; paid music waits for the person's yes, as in step 2. Build the palette, then spot. `spot_cues.py
   DIR/cues.json --out-dir audio --palette palette.json` writes `audio/cues.spotted.json` (declared runs kept), the list
   the conform and the mix read. `tempo_map.py MUSIC --json audio/tempo.json` measures the take; `conform.py MUSIC --map
   conform-map.json --cues audio/cues.spotted.json --tempo audio/tempo.json --snap bar --out audio/bed.wav --report
   audio/conform.json` fits it at bar lines, the map bound to the spotted list by section ids and by its hash
   ([template](../assets/templates/conform-map.json)). Then `mix_cues.py audio/cues.spotted.json palette.json --out-dir
   audio/mix --music audio/bed.wav --conform audio/conform.json`, with pan, pitch and section gain where the sheet asks;
   the palette's `music` names the take the bed came from, with no timing or gain of its own. Every output goes under
   `audio/`. Done when every turn has a decision, every masking pair in `mix-report.json` is answered or named, and the
   report hashes every file it read and wrote; for a silent film, when the decision is recorded.
5. **Render, mux, register.** Register with the spotted list the mix read, since `--sound` refuses a mix whose report
   names another list. For the kit, `make_film.py DIR --sound none` renders the kept copy and writes a receipt beside
   each file in `DIR-make/deliver/`; register one with `project.py add-version PROJECT --cues audio/cues.spotted.json
   --file MASTER --receipt MASTER.manifest.json --sound audio/mix/mix.wav`. Any other engine runs through `project.py
   add-version PROJECT --cues audio/cues.spotted.json --render "CMD" --file OUT --sound audio/mix/mix.wav`, CMD naming
   `{page}` and `{out}`; it renders the kept copy with outbound network blocked, muxes the sound with the picture
   copied, and registers the version ([project](../references/project.md) §4). A silent film registers the same way
   with `--cues DIR/cues.json` and no `--sound`. Its kit master from `--sound none` has no audio stream, and the
   delivery report says audio is intentionally absent; `qc_file.py MASTER --audio none` confirms another engine's
   master has none. Done when `manifest.json` holds the source and picture fingerprints with `binding: receipt` and
   the picture was not re-encoded.
6. **Shared last steps.** Check, Screen, Revise and Deliver, from [loop](../references/loop.md). A retime returns to
   step 3; every reader refuses the old list as stale, `conform.py` refuses the old map and `mix_cues.py --conform` the
   old bed.

**Narrated films.** The voice is the clock for the passages it speaks. Map it (`map.py add PROJECT VOICE --role vo`,
`map.py run PROJECT`) and read its word times with `map.py words PROJECT ALIAS`. Anchor each moment the picture must
meet as in [insert](insert.md) step 1, with `source_t`, `uncertainty_s` and `verified_by`. Reading text may lead the
voice so the eye reads ahead; in one measured narrated film each line was complete 0.9 to 3.6 s before its last word was
spoken. A demonstration lands on its word, within about 0.2 s and usually just before it. The voice enters the mix as
the palette's `voice` entry ([template](../assets/templates/palette.json)), and `mix_cues.py` ducks the music under it.

**Tesseract.** If the person has Tesseract installed and chooses it, hand the build to its skills
([engines](../references/engines.md) §Tesseract); the frame, the cue list and the register-a-version loop stay here.

## First question

"Who watches this, where, and what should they know or do afterwards? Is sound on where it plays?"
