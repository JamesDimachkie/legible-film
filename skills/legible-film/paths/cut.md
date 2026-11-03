# Cut: recordings shaped into a film

**Covers** interviews, podcasts, tutorials, tightening and jump cuts, shorts, voice-over explainers, trailers from
finished films, montages, and captions inside a project.

**Timeline owner.** The **paper edit** (`film.md`), the film as text in the order it plays. Every render compiles it
into a new version; nothing else holds the cut.

## Steps

1. **Frame.** `project.py init PROJECT --path cut --timeline paper` writes the frame fields atop `film.md`, each
   `missing` until `--what`, `--audience` or `--why` gives it as `assumed` ([project](../references/project.md) §3);
   it keeps anything already in the folder. Fill what the request gives and ask once for the rest. Done when each
   field is confirmed, assumed or waived with a reason, and only missing fields were asked.
2. **Map.** `map.py add PROJECT FILES --role interview|broll|screen|music|vo|sfx|still|other`, then
   `map.py run PROJECT`; music and sfx roles skip words by default (`--words all` keeps lyrics). Start a long
   transcription in the background and read its output. When a source is awkward (a variable frame rate, several
   audio streams, poor dialogue), read [footage](../references/footage.md). A transcript is never replaced once
   written; `map.py fix` corrects a word and records it, and `map.py words PROJECT ALIAS --from A --to B` lists word
   times and pauses. Done when every source has the map its role allows, or a reason.
3. **Plan.** Read [finding-the-story](../references/finding-the-story.md) before you choose a line, and
   [paper-edit](../references/paper-edit.md) before you write the edit. `audience`, `takeaway` (one sentence starting
   "They") and `story` (the spine, with a turn in it) join the frame atop `film.md`. For a recording, read everything,
   write three spines that are three different films, have a reviewer compare them, and build the strongest from its
   ending. When the look is open, read [look](../references/look.md); when the film makes a claim,
   [claims-and-rights](../references/claims-and-rights.md). Then the paper edit (`cut.py draft` from selected
   phrases; `grade.py hooks` for openings), with a note under each section saying why that beat follows and at each
   join saying what links its sides. Before rendering anything long, `grade.py paper`. Done when `cut.py check` has
   no errors, each warning has a decision, and the takeaway and story are written.
4. **Cut.** `cut.py render PROJECT` makes a version; add `--final` when step 5 follows, since only a final render keeps
   the stems. Before a final render for a destination, read [formats](../references/formats.md). A cut inside a spoken
   line lands in a measured quiet stretch; a join without one is listed as tight, and a person listens to every tight or
   unmeasured join. Run `check.py PROJECT`, then `grade.py review PROJECT` for a reviewer who did not make the cut;
   verify its findings and fix the confirmed ones. Done when the review leaves no blocking finding open.
5. **Designed sound, when asked.** Read [timing](../references/timing.md) §0 and [sound](../references/sound.md) first.
   The render writes `cuts/vNNN/edit-cues.json`, carrying the paper identity. Spot it first with `spot_cues.py
   cuts/vNNN/edit-cues.json --out-dir audio --palette palette.json`, then mix the spotted list with `mix_cues.py
   audio/cues.spotted.json palette.json --out-dir audio/mix --master none`, the version's dialogue stem
   (`cuts/vNNN/stems/dialogue.wav`) as the palette's `voice`. The mixer reads the voice only as a reference for masking,
   hero presence and ducking, and its `mix.wav` is a preview. Attach with `cut.py attach-mix PROJECT --version vNNN
   --buses audio/mix --report audio/mix/mix-report.json`, which takes the mixer's processed `music.wav`, `effects.wav`
   and, when it carries ambience, `bed.wav`, and never `voice.wav` or `mix.wav`. Dialogue stays the version's own stem,
   every stem not named in `--replace` stays, and attach-mix applies the version's fades and master once. Done when the
   new version carries each retained stem and each bus once and the manifest's `mix` record names them.
6. **Shared last steps.** Check, Screen, Revise and Deliver, from [loop](../references/loop.md). Every join is
   measured (`cut.py render`'s listening warning, `sound_check.py`). A join inside a bed, a bridge, a crossfade or an
   intended hard cut is a recorded decision; an unbridged level jump over 6 dB with no decision is a `look`.

## By kind

- **Tightening.** `tighten.py FILE` for one file, or `cut.py tighten PROJECT ALIAS` in a project. Declare a music or
  ambience bed with `--music-bed`, since nothing detects it, and listen to the whole reel. `--help` and
  [paper-edit](../references/paper-edit.md) §12 hold the rules.
- **Interviews and voice-over explainers.** The story comes from the transcript
  ([finding-the-story](../references/finding-the-story.md) §1-7). A voice-over is a source to map, and every claim
  traces to the facts file.
- **Shorts.** One project per clip, each with its own direction; import the long source's words into each
  (`map.py run PROJECT --alias ALIAS --words import:FILE`). Reframing is in [footage](../references/footage.md) §6;
  a fast speaker's reading load is lowered at its source, never by merging captions (§11).
- **Tutorials.** [footage](../references/footage.md) §9.
- **Montages.** A shape (arrival, build, peak, release) before a shot order; cutting on beats is a choice a passage
  makes on purpose.
- **Trailers from a finished film.** [finding-the-story](../references/finding-the-story.md) §8. Map it as `other`
  with the characters' names in `--prompt`, and screen candidate shots for flashing in the source
  (`flash_scan.py FILM --start S --end E`).
- **Captions in a project.** `captions.py build`, then `captions.py check` against the delivered audio's transcript
  ([footage](../references/footage.md) §11). A person reads every caption.

## First question

"Who is it for, what should they leave with, and how long?"
