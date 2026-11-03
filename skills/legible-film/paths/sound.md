# Sound: sound for a picture that stays as it is

**Covers** sound for a silent or locked picture, effects and a bed, rescoring, conforming music to a cut, a voice over
music, and fixing sync.

**Timeline owner.** The **picture**, a finished file, or its page when one exists. The picture is fixed; sound is
placed against it and muxed onto it with the picture stream copied, so its identity survives.

## Steps

1. **Frame.** Inherit the context when the picture comes with one; otherwise ask once for the missing fields. Done
   when every field has a state.
2. **Read the picture muted.** Strips and sheets (`frame_sheet.py PICTURE --every 0.5 --out qa/overview.png`) and
   `motion_scan.py PICTURE` for cuts, holds and moves. Done when sections and turns are listed with their frames.
3. **Cue list.** Read [sound](../references/sound.md) for the proposition and who leads each passage, and
   [timing](../references/timing.md) §0, with §3 for sync points. When a page exists, export from it as in
   [create](create.md) step 3. Otherwise build the list from observed anchors. `listen.py sync PICTURE --candidates`
   proposes them from the picture's frame differences, as unconfirmed hints; confirm each on frames, and record its
   source time, an uncertainty and who verified it. The list's `picture` copies the `kind`, `sha256`, `geometry` and
   `timing` that `cue_list.py fingerprint picture PICTURE --json --timing-out picture-timing.json` prints, plus `path`,
   with `picture-timing.json` beside the list; its `provenance` is `observed`, not exported. Give each section its
   clock. Done when `cue_list.py cues.json` reads `fresh`, every turn has a decision and every follow span an intent.
4. **Palette, and music when there is a bed.** Before any paid or generated music, voice or effect, ask for the spend in
   your reply and generate nothing until the person says yes; then read [generation](../references/generation.md). Build
   the palette from chosen or synthesised takes (`make_sound_kit.py --out DIR`), each with its licence recorded as
   [claims-and-rights](../references/claims-and-rights.md) says. With a music bed, read
   [timing](../references/timing.md) §9 for music as the clock; `tempo_map.py MUSIC --json audio/tempo.json` measures
   each candidate take and the palette's `music` names the chosen one; effects-only work has no music take and skips the
   tempo map. Done when every role the list asks for has a take, and the bed has its chosen take when there is one.
5. **Spot, conform, mix, register.** Read [formats](../references/formats.md) for where it is heard before you master.
   Spot first, since spotting writes the list the conform and the mix both read. `spot_cues.py cues.json --out-dir audio
   --palette palette.json` writes `audio/cues.spotted.json`. With a music bed, `conform.py MUSIC --map conform-map.json
   --cues audio/cues.spotted.json --tempo audio/tempo.json --snap bar --out audio/bed.wav --report audio/conform.json`
   fits the chosen take to the list's sections at bar lines, and `mix_cues.py audio/cues.spotted.json palette.json
   --out-dir audio/mix --music audio/bed.wav --conform audio/conform.json` mixes. For effects only, skip the conform and
   mix with `mix_cues.py audio/cues.spotted.json palette.json --out-dir audio/mix --no-music`. Either way, `project.py
   add-version PROJECT --cues audio/cues.spotted.json --file PICTURE --sound audio/mix/mix.wav` muxes the mix onto the
   picture with the stream copied and registers the version; it refuses a mix whose report names another list. A picture
   that is a paper version takes the buses through `cut.py attach-mix` instead ([cut](cut.md) step 5). Done when any
   conform report names the spotted list, and the version's picture identity equals the input's, its packet hash and its
   timing both, which a mux keeps.
6. **Shared last steps.** Check, Screen, Revise and Deliver, from [loop](../references/loop.md). The sync group adds
   `listen.py sync MASTER --cues audio/cues.spotted.json` (with `--video PICTURE --source-kind stem` when you measure a
   stem) and `listen.py transcript MASTER`, each labelled. The follow coupling it reports is a screening signal against
   an uncalibrated null, never a significance verdict; whether the sound works is still the listener's call.

## First question

"Which moments must the sound make felt, and where is it heard? Is there music you must use?"
