# Changelog

## 2.2.0 (2026-11-05)

**Upgrading from 2.1.** A blocked render now exits 2 instead of 1. `--install transcription` no longer downloads a model:
add `--download` (about 460 MB). `setup.py` no longer installs into a shared Python. Every 2.1 command still works.

**Several recordings of one conversation**

- `map.py sync` lines up cameras and mics from their sound, with no clap, and reports confidence and drift. The result is
  bound to each source's SHA-256; low confidence or no overlap is a look and is never applied silently.
- `~ ALIAS sync` shows a lined-up camera at the same moment, and `{sound ALIAS}` takes a line's sound from a lined-up mic.
  New roles `camera` and `mic`. Cuts land in pauses measured in the sound actually used.
- Speaker labels: `map.py speakers` from per-person mics, from an imported transcript, or (`--shared --download`) from an
  optional local model on one track; `map.py fix --speaker` corrects them, and captions break where the speaker changes.
  Labels are drafts until a person reads them. `references/footage.md` has the steps for a two-person, multi-camera
  podcast.

**Faster renders**

- Plain cuts render about four times faster: FFmpeg draws the picture and the same rule chooses the frames. A 30 s 1080p30
  final went from 125 s to 29 s on soft footage (62 s on grainy footage), and the example's first cut from 42 s to 12 s.
  `--every-frame` opts out, and the render and its manifest say which path ran. Dissolves, overlays, layers and moving
  crops stay on the every-frame path.

**Checks that no longer pass the wrong file**

- Sources are checked to where they really decode: `map.py` records it and warns, `cut.py check` gives a line-numbered
  error for a range past it, and nothing is freeze-filled without being declared. Before this, a file cut short could
  render and check clean with a frozen, silent ending.
- An empty caption file on a film with sound is a look or a fail, and a wordless transcript of measurable sound is not
  assessed; before, both read as ok.
- Quick edits compare pictures and sound with the source, so a wrong recording or a wrong trim now fails. What is not
  compared says "Not assessed: content".
- A blocked render exits 2, so it can no longer be read as a render with notes.
- `map.py` and `check.py` measure every sound stream. A silent default track gives way to one with sound and says so, with
  the `--stream` command to override, and `check.py` reads the stream a player plays.
- "moov atom not found" no longer claims FFmpeg is missing, and captions end with the film.

**Phone footage**

- HDR sources get a note at render and a look in `check.py`; the tone map is unchanged. A cover framing that discards a
  third or more of a source warns, names the line and offers the options that keep more of it.

**Installs**

- What you install is what was tested: `scripts/constraints.txt` pins every pip package per Python from 3.9, wheels only,
  and playwright-core is exact. CI installs the same, and a weekly `upstream` workflow tries the newest releases, so a
  breaking upstream change is seen before the pins move. This also keeps OpenCV below 5, whose missing face cascade cost
  `crop auto` and the scorecard their face detection without saying so.
- `setup.py` installs into the active virtual environment, otherwise a per-user one, and never a shared Python.

**The front page and the evidence**

- The README is about 40% shorter, with more of it folded, and opens on the launch film. The full tables moved to `docs/evidence.md`, with
  wording corrected where a number could not be traced to a published record.
- `paths/cut.md` skips story development when a request only shortens pauses. The skill's description names captions,
  subtitles, interviews and podcasts again. A new issue form asks how a film went or where you got stuck.
- The routing evaluation's harness and results are published in `evals/`.

## 2.1.0 (2026-11-03)

**Upgrading from 2.0.** Every 2.0 command still works, and each now opens one of six paths
(`references/commands.md`). New aliases: `launch`, `design` and `motion` open create, `sound` and `sfx` open sound,
and `convert` opens quick. Inside a project, `check`, `screen`, `review`, `revise`, `deliver` and `handoff` act on the
project's own timeline, so a version rendered in an engine is screened and checked without `cut.py`. No script is
removed and no script's existing flags change. Old links still land: `references/recipes.md` and the Map, Plan and
Cut sections of `references/loop.md` are now forwarding headings.

An agentic video assistant for any kind of video, with picture and sound on one clock. 2.0 grew around transcripts
and joins; 2.1 routes each request to the path its timeline belongs to, loads only what that path needs, sets every
film's context first, and keeps picture and sound on one exported cue list.

**Six paths**

- `SKILL.md` is now a router of about 1,000 words (it was 2,394): the gates, the frame, one table of paths, the timing
  floor and the shared last steps. Each path lives in `paths/`: **create** (a new film drawn in an engine), **cut**
  (recordings shaped into a film), **insert** (picture made for a passage of footage), **sound** (sound for a picture
  that stays as it is), **editor** (assisting someone in Premiere or Resolve) and **quick** (one file, one change or
  one question). Each path names its timeline owner, the references it reads and when, steps that end on a stated
  done criterion, and its first question.
- **The frame first.** Every film states what it is, for whom, why they care, and what the viewer knows by which
  second, each field confirmed, assumed, missing or waived. Only missing fields are asked. Quick and editor work
  inherits its context.

**One clock**

- `references/timing.md` §0 is the contract. It sets one owner per timeline, the cue list exported from it and never
  typed twice, four scales (turn, follow span, contact, silence), a decision on every turn, and two labelled measures
  on the delivered file (the frame changes at each cue; the sound follows the list).
- `cues.json` v2 records its picture's exact identity, so a retime makes the list, the conformed bed and the mix stale
  and every reader refuses them. Kit films, HyperFrames pages (timeline labels plus an `lf-cues` block) and pages that
  declare `window.__cues` export their lists from a frozen copy that the render then reads. Freeze scans what the render
  reads, the entry page and every file its static references reach, then every file the export saw load; a file nothing
  reaches is copied and fingerprinted, and listed as not loaded, not scanned.
- Sound is spotted first, and the conform and the mix both read the spotted list, so a conformed bed is bound by hash
  to the list the mixer reads. A version that carries a mix registers with that spotted list.
- `references/timing.md` §3 gives starting values for sound that leads a turn (`lead_ms` -83 to -208, 2 to 5 frames at
  24 fps) and for a music-led transition (the accent on the first visible change, the cut half a beat later), and
  `paths/create.md` routes a narrated film, with the voice mapped for word times, anchors with an uncertainty, reading
  text ahead of the voice and demonstrations on the word, and the voice in the palette's `voice` entry.
- The beat rules the reference films contradict are gone ("cut on strong beats", whole frames per beat, thinning
  every typing run). Landing on beats and thinning a run remain choices a passage makes on purpose.

**New and extended tools** (each named in a path only once its check passes): `cue_list.py` (loader, fingerprints,
freeze), `film_capture.mjs cues`, `project.py add-version` (register a master from any engine, bound to its cue list
and render receipt), `cut.py attach-mix` (designed sound onto a paper version, one owner per stem), `conform.py`
(music fitted to the list's sections), `mix_cues.py` (pan, pitch, section gain, masking and hero reports, hashed
inputs and outputs), `listen.py` (measure, transcript, sync, sheet, labels; earshot's shape, MIT), `check.py`'s
context and sync groups and `--against IN --edit KIND`, `sync_check.py --outside`, `grade.py cold`,
`delivery_check.py`, and `with_lock.py` for one heavy job at a time. `add-version --sound` works on every route and
`--min-free-gib` and `--wait-min` set its render wait; `film_check.py --verify-cues` makes the kit's frame-change
screen opt-in; `listen.py sync` reports follow coupling as a screening signal against an uncalibrated null, never as
significance.

**From seven downloaded reference clips**

- `flash_scan.py` counts a classic or red swing toward the hard limit only when an opposite swing within one second
  moves at least a quarter of the window back in the same pixels. Shapes sliding or morphing through a window are a
  look (`coherent_max_per_s`), never a silent pass. On two reference clips, the 4 failing windows whose frames showed
  motion became looks and 2 windows the readings could not settle still fail. Real strobes still fail, including
  relays whose consecutive swings never share pixels.
- A layers-in-depth recipe in `references/picture.md` §8: one camera, flat layers placed at depths, parallax by
  depth, overscan with a probe, and a breakdown view drawn from the same scene on the same clock.
- `make_sound_kit.py --bars` places the default drop and stop bars inside shorter music, and refuses given bars that
  do not fit with bars that do.
- A follow span under 2 s reads "not assessed: span under 2 s" in `listen.py sync`, never an unexplained gap.

**What moved where**

- Recipe bodies moved into the path they belong to; `recipes.md` keeps its headings as pointers.
- The loop's Map, Plan and Cut moved to `paths/cut.md`; `loop.md` keeps Check, Screen, Revise and Deliver as the
  shared last steps.
- Studio grade's sound design and music passes (§7.5-7.6) moved to `sound.md` §14-15; `sound.md` §13 is the new
  listening layer.
- `engines.md` gains cue export and the frozen copy (§2), how to open HyperFrames' own skills in Claude Code and in
  Codex (§4), and a Tesseract route that hands the build to Tesseract's skills, with its terms quoted.

**What stays manual:** writing an original score; earshot's own sound-making, sound finding and realness scores;
warping reading holds into an existing timeline; refining word onsets against the audio; frame-exact 3D; cue export
from engines other than the kit, HyperFrames and `window.__cues` pages; Tesseract builds; and every act of watching
and listening.

**Known limits:** the 2.1 tools are verified on Linux and Windows; on macOS they have run only in the CI self-test.
The routing eval's harness is in `evals/`; no 2.1 routing results are published with this release.

## 2.0.0 (2026-10-31)

**Upgrading from 1.x.** Every 1.x command still works except `short`: `brief` and `film` open `plan`, `teaser` opens
`kit`, `cutdown` opens `shorts`, `review` opens `screen`. A sting, loop or clip under 15 s, which `short` made, is now
part of `kit`, and `shorts` now makes short clips from a long video. New commands: `quick`, `map`, `plan`,
`screen`, `shorts`, `insert`, `premiere`, `grade`, `handoff`, `tighten`, `taste` and `spatial`. No script or
reference was removed. FFmpeg 5.1 or later is now the minimum, and `setup.py --install core` installs numpy and
Pillow.

Video as legible as code. 2.0 reshapes the skill around one loop (Map, Plan, Cut, Check, Screen, Revise, Deliver)
that a coding agent runs and a person can follow at every step: the film is written down as a script, every render is
a version that never changes, checks run on the file a viewer receives, and the person watches, notes moments,
scores and approves in one local page. 1.x's film kit, sound chain and checks are all still here, now inside the loop.

**The loop**

- **A project folder** (`references/project.md`, `project.py`) shared by every script: sources mapped under role
  aliases (never file names), immutable versions in `cuts/vNNN/`, notes pinned to moments, an append-only decision
  log, and a one-line status the agent posts after each stage (`v3 checked · 11 checks pass · 1 to look at · 2 need
  you`). Writes are atomic and locked across processes; stages only move backwards when asked.
- **The Map** (`map.py`, `transcribe.py`, `strip.py`): a local word-timed transcript (faster-whisper, or FFmpeg's
  whisper filter, or an imported one; nothing uploaded), shots with contact sheets, loudness and silences, and
  screening strips that draw a cut as frames, levels and words. Transcripts are never overwritten once a person may
  have corrected them; `map.py fix` corrects a word and records it; review prompts mark places to listen, using a
  local voice-activity model so a music bed no longer fills them (Tears of Steel: 29 prompts down to 3, with the same
  deleted words found in a known-answer test).
- **Direction before lines** (`references/finding-the-story.md`): a film states who it is for, what they should leave
  with and its story in one sentence at the top of its script; `cut.py check` warns when a cut longer than 20 s does
  not, the script review judges the cut against it, and the Screening Room shows it above the script. The reference
  teaches finding the story in a recording (read everything, try the ending first, keep the speaker's meaning) and
  finishing it as an editor would (covering jumps, naming the speaker once, endings that land).
- **The paper edit** (`film.md`, `references/paper-edit.md`, `cut.py`): spoken lines, pictures, cutaways, titles,
  holds and music in the order they play. Strike a word to cut it. Cuts land in pauses measured in the audio: on
  test material 240 of 240 cuts fell in silence, where transcript timings alone put 52 in speech and 78 in breaths.
  `cut.py diff` says exactly which lines, words and durations changed between versions.
- **Checks** (`check.py`) in plain states (pass, look, fail, needs you, not assessed), each proving it ran now: spec,
  sound edges, flashing, near-empty frames, captions as three items that say what they compared (reading rules;
  following the edit; matching the speech, against a local transcript of the file's audio), burned-caption and title
  contrast, and technical checks (stereo that cancels on a phone speaker, black bars, interlacing, frozen picture,
  colour range, DC offset). Loudness is judged against a target only when one is named.
- **The Screening Room** (`screen.py`): one page with the cut, its script (struck words struck, changes marked, and the
  script's own notes on each beat and join in place), the timeline, checks, notes and versions; replay a moment, step
  frames, leave notes with `N`, tick what only a person can judge, approve. Live mode runs on 127.0.0.1 behind a private
  link made for that session and serves only the room's own files. It has light and dark modes, and every text measures
  4.5:1 contrast or better.
- **Reviewing together in Flask** (`references/review.md` §1): when the person reviews away from the machine or with
  a client, an editor or a team, [Flask](https://flask.do) is the recommended collaboration and feedback layer. The
  agent posts each version to one asset through Flask's MCP server, brings every note (its moment, words and
  drawing) back into `notes.json`, fixes it at its cause and closes it with a reply in the next version; uploading
  private material waits for the person's yes. The teaser in the README was revised this way through five versions.
- **The scorecard** (`grade.py`, `references/grading.md`): fifteen dimensions in content, picture, sound and
  delivery, each 0 to 10 with the moments behind it, scored by a reviewer who did not make the cut from a packet of
  stills, scopes, the opening at ten frames a second, the transcript and measurements; the person's own scores take
  precedence. Every dimension says how far it has been validated: in a blind degradation test on two real cuts,
  hook, structure, ending and image passed on both, seven more on one, and four not yet. `grade.py paper`, `hooks`
  and `thumbs` score the script before rendering, list opening lines and propose covers.
- **Premiere** (`exchange.py`): reads Final Cut Pro 7 XML exports, places the transcript's words in the edit, and
  follows each caption into the next revision (unchanged, moved, stale, split or removed), naming anything it cannot
  map. On one professional editor's two-revision case: 78 of 78 and 81 of 81 clips, 479 of 479 and 462 of 462 words
  within 1 ms; following captions through the edit flagged 5, all changed by the editor.

**Cuts that work, not only cuts that pass**: an agent cannot watch its own cut, and reviewing its own work it sees
what it meant. Blind tests with judges calibrated on deliberately broken versions of a good cut shaped what follows.
- *Independent review before the person sees a cut* (`grade.py review`, `references/review.md` §4): a packet of the
  joins at ten frames a second, the opening and ending, the transcript with source times and the measured checks; a
  reviewer with no part in the cut (another model family when the person allows it) looks first as a viewer, then at every
  join; the editor verifies, fixes and re-reviews once. On two first cuts it raised blind judges' scores from 5 to 7
  and from 6 to 7 or 8, removing two events merged into one and an undefined "it". A person watching the four films
  blind picked a reviewed cut as the best; the other reviewed cut was one of two the viewer found poorly composed.
- *Meaning before words* (`references/finding-the-story.md` §4): join on a shared subject, situation, question,
  cause or intended contrast, never because the words happen to fit; every shot tells the viewer something; keep the
  viewer oriented; a note at every join says what links it. Cut for feeling (Murch's order), keep the setups, let
  moments breathe, cut whole beats rather than breaths. Stories are chosen by comparing three spines.
- *Sound across joins* (`{tail N}`, `{lead N}`, `{dissolve N}` crossfading sound too, `{sound -6dB}`) and a measured
  report on every join (the background where nobody speaks on each side, its tone, its 20-100 Hz low end, what
  bridges it). On a teaser, it flags every join a person heard as wrong, including effects booms before quiet
  dialogue.
- *Checks for what agents miss*: flash frames of another shot, holes of digital silence, title contrast, abrupt
  sound at joins, busy cutting, interview lines played out of the order they were said, captions too small for a
  phone feed, joins without a note, an opening that may start mid-sentence, a question answered before it can land
  (no beat where the source had one), a film whose length cuts its last sound short.
- *Tools that stopped getting in the way*: `project.py stage`, `map.py fix --start --end` for word timing, `map.py
  words`, `map.py run --check`, a map that survives moving the skill, paper reviews that survive note edits,
  `frame_sheet.py` reading only the windows it needs (63 s to 0.7 s on a 17-minute source), caption plates that fit
  their words, the script's own notes shown in the Screening Room. `map.py words` shows the pauses under room tone
  that a fixed silence threshold misses, `compare_versions.py --offset-at` compares versions that gained or lost
  frames mid-film, `cut.py diff` names changed modifiers, and `render --resolves` prints the command that closes
  each note.

**From a working editor's review of the pre-release** (an editor's agent tested it on two real Premiere
revisions: every clip and every placed word matched its own oracle, then it reproduced the gaps below):

- *A transcript belongs to the file it was made from.* It records the file's SHA-256 and the sound stream; when the
  file changes the transcript is stale, every `map.py` run says so, and `cut.py`, `exchange.py` and `check.py` will
  not use its words until it is transcribed again or confirmed against the new file (`map.py confirm-words`).
- *A word belongs to its recording.* `exchange.py` identifies a word by its source and ID, refuses repeated IDs, and
  marks words under an audio transition as estimated, with the transition (on the editor's revisions: 33 of 33 and
  66 of 66, where 3 in each had looked measured).
- *An editor's export, checked as delivered.* `check.py --file` takes the export, its caption sidecar, the timeline
  XML, the source transcripts and a transcript of the export, plus the expected delivery settings; anything it
  cannot assess says "Not assessed". Every result records the hash of each file and tool it depends on and reads as
  out of date when one changes (`check.py --verify`). `--final` takes the delivered `--captions`.
- *Caption house styles.* `captions.py --profile` holds an editor's limits and the exceptions a person has reviewed
  (on the editor's revisions, 183 and 156 default prompts became 38 and 23); `complete` and `--strict` say whether
  the captions are done, not only whether a rule failed; an offset seen only on estimated word times is a prompt to
  listen.
- *No report overwrites its input*, in any script, by the same path, another spelling of it or a link.
- *Cue matching* no longer picks digital silence after loud material (an onset 86 ms early at a correlation of 12.4,
  now on cue at 1.0).
- *Done is not accepted.* `project.py status --json` keeps stage progress, current checks, open review and the
  person's approval of a file apart.
- *Editor assist mode* in SKILL.md: when an editor's application holds the edit, the request sets the scope, with no
  paper edit or planning loop; the privacy rule says what the skill does not remove from transcripts, captions and
  reports.

**From the editor's test of 2.0** (the same editor's agent, on a 2.0 pre-release build: a synthetic hand-off
opened in Premiere Pro 26.3 on macOS, one real export checked as delivered, and a raw 72 s interview answer
tightened):

- *The hand-off opens in Premiere.* Every source came online with its handles; the five clips and the dissolve
  landed where expected; chirps in each channel measured both J and L overlaps right; 6 of 6 markers and 10 of 10
  captions matched. Two faults it found are fixed: the sequence now declares square, progressive pixels (Premiere had
  chosen PAL-601, 35:32 pixels, for a landscape and a portrait 1080x1920 hand-off alike), and each channel of a
  stereo source is panned to its side, as Final Cut Pro 7 writes a stereo pair (both had played centred). The pan is
  not yet re-checked in Premiere.
  The notes now name a source whose picture starts apart from its sound and non-square source pixels, and say to
  compare WAV or PCM exports, since AAC adds 1,024 samples of encoder delay.
- *A caption exception belongs to the caption it reviewed.* An exception keyed by rule and start alone had accepted
  a different stale word after the caption at that start was edited. Exceptions now name the caption's start, end
  and text, and may carry the result's `fingerprint` from the report, which also reopens them when a new word basis
  changes the result; one without text and end is listed for review instead of applied.
- *Counts say what they count.* A summary that read "8 caption words" for eight captions holding nine words now gives
  captions (or places) and words apart.
- *A stale transcript exits 1.* `map.py` warned and exited 0, so a caller reading only the exit code took the words
  as usable.
- *Tighten says what its reel holds and where the picture jumps.* On the raw interview it made 10 cuts (5.2 s, 7.3%),
  kept all 184 words, aligned every join (correlation 0.996 or more), and no listening model found a clipped word, but
  the reel played 5 of 11 listening prompts without saying so and two joins showed an arm jump. The report and output
  now count cuts and prompts apart, and each join is scored by how much the picture changes across it against the
  shot's own motion, ranked so the jumps are checked first.

**Designed pictures over recordings**: `~ over` draws a graphic with transparency over a line while it plays, a
lower third or title as a video at the film's frame rate (PNG MOV, ProRes 4444 or VP9 with alpha, frame for frame
from its first frame) or a logo as one PNG, and refuses a file without transparency; a recipe for an animated insert
in place of a passage's picture, on the source's exact clock and timed to its words; `frame_sheet.py --words` labels each frame with the word spoken then;
a designed film's concept and score are reviewed before anything is built; `cut.py diff PROJECT vNNN` shows what
changed in the paper edit since a render, so an agent builds on the person's own edits.

**Footage the world actually shoots**: rotated phone video framed as shown, non-square pixels, variable frame rate
cut on presentation timestamps, HDR converted before a caption burn, Arabic, Hebrew, Thai and Devanagari captions
shaped through libass in bundled Noto Bold faces (a line mixing scripts names each script's face, so it renders on
Linux too), MP4 edit lists decoded on the source clock, one audio stream chosen once and used everywhere, retimes
that keep events within a frame.

**Fixes found by real use and review**: proxied HD interviews render with their sound; burned captions at a
readable weight on a plate; a 1x clip no longer passes through a time-stretch filter (it moved sounds 18 ms and
dropped samples); mixes keep headroom in float (16-bit intermediates clipped); final renders show every source
frame at 29.97 and 24 fps; the cookbook's trim keeps its sound and its 9:16 keeps HD colour; mixes that hung on
FFmpeg 9 always end; a silent final passes its spec check (the re-encode peak check is asked of files with sound
only); the interlacing check decides on idet's single-frame verdicts (its running tally called fine detail in
progressive film interlaced for seconds at a time); a crop path file from `reframe.py --start` plays from the
clip's in-point; burned captions no longer cost the picture a lossy generation (the caption-free area measured 39.6
dB PSNR against an uncaptioned render, now 51.1 dB); caption lines follow the frame's shape (26 characters at 9:16)
so vertical captions keep their size; screening strips made at render time show the timed words; a flash only the
pattern detectors count (camera movement over fine detail triggers them) asks a person to look, and a general or red
flash fails only when at least a quarter of a screening window (a third of the frame each way) changes together, in
one direction, so fine moving detail no longer fails a film (it had failed the film kit's own showcase) and a failure
names its own moment; a killed render or mapping no longer shows as running; a transparent PNG shown as a still
shows the background colour where it is clear (it showed black), and `cut.py check` suggests `~ over` for one placed
over a line.

**Beyond the cut**:
- *Hand a cut to an editor* (`exchange.py write`): a version becomes a Final Cut Pro 7 XML sequence that Premiere and
  Resolve open, of the original clips with their full handles: picture, cutaways and graphics on their own tracks,
  source-channel dialogue and music, dissolves and crossfades, J and L cuts as split edits, markers, and the captions
  as SRT beside it. Picture follows the frames the render chose. What the format cannot carry (crops, speed changes,
  the mix, spatial effects) is listed beside the XML. Read back by its own reader and OpenTimelineIO's on synthetic
  projects, every cut within half a frame, and opened in Premiere in the editor's test below; Resolve is untested.
- *Tighten* (`cut.py tighten`, `tighten.py FILE`): pauses shortened to a target where the sound is measured quiet,
  relative to the recording's own room tone, written as a paper edit; a cut waits until a word's tail and the room
  have died away to near room tone, and pauses under 0.12 s are left; named fillers struck only when asked; repeated
  words and untranscribed sound flagged to hear, never cut; a reel that plays each cut before and after, in whole
  words with soft edges, so a person can hear that no word went (after Auto-Editor's inverted edit). It is cautious:
  on the first 120 s of a public-domain LibriVox reading (*Birdseye Views of Far Lands*, chapter 1) over a still, it
  shortened 6 of 22 pauses longer than its 0.35 s target (2.8 s), and left a pause where it found no cut clear of a
  word's tail and the room's echo; every cut sits within 8 dB of room tone. A music bed is not detected: declared with
  `--music-bed`, pauses are left, and the report says why.
- *Spatial layers* (`track.py`, `matte.py`, `spatial.py`, `references/spatial.md`): track a surface or a point, then
  pin a graphic to it, put a title behind a person, or blur a moving face or plate; key, luma, difference and MODNet
  subject mattes. Layers are files bound to their source, drawn through the renderer's own frame choice and framing,
  recorded in each version, and checked on their line; a privacy blur that cannot cover a frame stops the render.
  Measured on public footage: a sign in NASA's *Designing Webb* b-roll (public domain; 13-20.4 s) tracked on all 109
  frames, feature agreement median 0.83 px and worst 5.2 px (no ground truth); on the Tears of Steel bridge scene a
  region track on a face lost 202 of 288 frames (a face is not flat) and a point track drifted 9.4 px. MODNet on
  the NASA Mather interview kept the speaker with a blue fringe at the hair.
- *Your references, per film* (`look.py`, `references/look.md`): before the paper edit, the agent asks in one
  message, each question with a default, for references (films, ads, channels, a frame, the product) and what to
  take from each, or, with none, offers three directions with public examples or asks who it is for, the feeling,
  the pace and what the person never wants. The answers become the project's `look.md`; references are copied
  into `refs/` under stable names, drawn as one board, and set beside stills of the film with colour measured per
  region. The plan and cut reviewers read it; references are never cut into the film (`map.py` refuses them),
  delivered or uploaded. Drawn from Leon Lin's `cook` and his notes on prompting with references.
- *Preferences the person confirms* (`taste.py`, `references/taste.md`): an agent proposes a preference with the notes
  and changes it came from; only the person confirms it, in their words, and only they make it general. The Plan
  step and both review briefs read the confirmed ones; those the kit can measure become looks, never failures or
  edits. `screen.py import-notes` brings Flask notes in whole, once each.
- *Smaller things agents tripped on*: J, K and L shuttle and frame steps in the Screening Room (`?` lists the keys);
  `compare_versions.py` says where in the frame a version changed; an empty first frame is a look; a title below
  contrast gets a colour and a plate that pass; a freeze followed by its own shot is not busy cutting; a flash
  inside a shot is not two shot changes; `map.py fix` shows the word in context and what it changes in film.md;
  a picture, still or music line on a changed source is an error, and every version records the sources it used.
- *Long and 4K finals on a laptop*: the renderer decodes each clip as it plays instead of spooling every picture
  range to disk first, with the same frame choice and output (frame hashes and whole files identical on the render
  cases). A 3-minute 4K synthetic edit needed 4.3 GB of temporary disk and now needs about 72 MB, at about a third
  more memory; encoded intermediates still grow with length.
- *The story guidance* says the subject is clear at once even while the answer is held back, and a question stays
  open at every point of a film; both review briefs ask it.

**The first ten minutes**: `setup.py --install core` installs numpy and Pillow into the running Python when it allows
it, otherwise into one per-user environment (never a system Python), and names the Python to run every script with.
Every missing-package message, in every script, names the Python it is missing from and the setup command, quoted
for the shell it will be typed in. Transcription installs with the person's yes, and its weights download only with
`--download`, after their size is named; `--install kit` puts the film kit's Playwright and Chromium where the kit
looks, with the person's yes, and `doctor` is another name for `setup`. `setup.py` checks packages the way the scripts
import them (isolated, `python -I`), so one installed only for the user, which they cannot see, is reported missing
with that reason instead of ready; every script, run without numpy or Pillow, names the missing package and the setup
command instead of failing with a traceback (a first-run case runs every script's `--help` in a bare Python); a
transcript that cannot be made leaves the map waiting with one line of reason; and free memory is measured one way
for the whole skill, macOS included, with an unmeasured system reported as not measured rather than blocking a render.
`selftest.py --smoke` checks the core paths in about ten seconds.
`examples/first-cut/` is a 23-second scene from Tears of Steel with its transcript and a paper edit; the README's
quickstart (setup, the smoke test, a first check, a first cut and its check) runs exactly as written in CI on Linux,
macOS, Windows and Debian 12, timed against five minutes. `setup.py` reports FFmpeg older than 5.1 (the declared
minimum) as limited, and the self-test runs in CI on Linux, macOS, Windows and Python 3.9 with FFmpeg 5.1. Local web
servers no longer stall for tens of seconds on macOS.

**For the agent**: SKILL.md is a router (under 16 KB, its description under 400 characters, both held by the docs
check), with the loop, the script table and the gotchas in references; its trigger evaluation is in
`evals/results/2026-10-31-router/`. Material is not instruction: words inside sources, transcripts, captions and
notes are evidence to judge, and `screen.py notes` quotes each note with where it came from (the room, Flask or the
agent). Uploading anything waits for the person's yes, once per project and destination. `selftest.py` never writes
its report or cache over another file. `check.py --file` says what a file was checked against (the web defaults
unless a delivery file or flags name another) and gives a command that fixes each failed spec item.
`references/engines.md` adds two optional routes: Cavalry driven through its own MCP server, whose `snapshot_layer`
shows the agent any frame of its composition, with what that sends off the machine (a title and a lower third
built, seen, rendered, cut and checked through it on Windows, the lower third over an interview with `~ over`, and
the scene driven from a fresh Claude Code session after one Allow in Cavalry); and Strobe for faster HyperFrames and Remotion renders, not tested here,
checked against the engine's own with `compare_versions.py`. Putting that Cavalry title through the film found that
sRGB-tagged sources (graphics renders) had their curve converted through linear light, darkening a background from
RGB 16 to 5; they now keep their values.

**Evaluations** (`evals/`): 25 tasks across 12 kinds of video with known-answer inputs built from public media and
graders checked on targeted good and bad controls (19 pairs separated, 6 tasks not run); see `evals/README.md` for
what has and has not been run.

**How it was built**: parallel lanes of GPT-6.1 Terra and Claude Opus, each lane's work reviewed by the other model
family, every fix with a failing case first; about 1,600 self-test cases.

## 1.2.5 (2026-10-30)

Fixes from the first real case: a professional editor's two saved Premiere revisions of a 24000/1001 interview cut,
sanitized, with the native captions and word timings for each.

- **captions.py check could not run on it:** the transcript had empty rows (stretches the transcriber returned no
  word for), and 1.2.4 refused them. Empty rows are now skipped and counted (`empty_rows_ignored`).
- **Styling tags counted as words and characters:** Premiere's SRT keeps caption colours as `<font color=...>`, so
  with the empty rows removed by hand, 1.2.4 reported 506 stale words in 117 of 121 captions and 106 over-long
  lines. SRT and WebVTT tags, ASS overrides
  and HTML entities are now removed before any rule or match; on the same revision the check now reports 38
  candidate stale words in 17 captions and no line-length findings.
- **Estimated word times:** a caption entrance or exit measured from a word time the transcript marks as estimated
  is no longer a review prompt; the captions affected are listed once.
- The report gains a `summary` of findings and review prompts by rule, so a pattern across a whole file (captions
  placed back to back, which Premiere does by default) reads as one line.
- Measured on that case: of the 38 words flagged in revision 1, the editor changed 10 in revision 2 and kept 28,
  13 of them near-spellings of a transcript word. The editor also removed 12 words the check did not flag, most
  likely after the dialogue changed in revision 2; catching those needs the words mapped across revisions, which
  this release does not do. The case itself stays private: no text from it is in this repository.

## 1.2.4 (2026-10-29)

Fixes from a video professional's questions: exact NTSC frame rates, resumes that notice a tool upgrade, and caption
checks against the current dialogue.

- **Frame rates:** `"fps": 29.97` encoded at 2997/100, a rate editing applications read as non-standard. A decimal
  NTSC rate (23.976 or 23.98, 29.97, 47.952, 59.94, 119.88) now means the exact fraction (30000/1001 and its
  family) in every encode, and `edit.json`, `transcript_cut.py --fps` and `motion_blur.py --fps` accept
  `"30000/1001"`. Explicit fractions and other rates are kept exactly as given. The cue list `assemble.py` writes
  carries the exact rate as a number.
- **make_film.py --resume** keys each step on the builds of the tools it uses, as the doctor finds them (FFmpeg,
  ffprobe, Node, Playwright, and Chromium by path, size and time): an FFmpeg upgrade reruns the renders, muxes and
  QC and reuses spotting and the sound kit. New cases show what a change reruns: a picture-only edit re-renders both
  sizes and reuses the sound; a new master remixes and re-muxes and reuses both renders; an FFmpeg or ffprobe
  upgrade reruns a render and reuses a Python-only step.
- **captions.py check** compares captions with a word-timed transcript of the current audio, matching each caption
  in order, one word to one caption, against the speech under it. It names caption words no longer spoken there
  (words cut from the audio but left on screen), flags a caption over no matching speech even when the same words
  are spoken nearby, and reports a whole file offset once (starts and ends shifted together; intentional lead-ins
  are not an offset). Music symbols, sound descriptions in brackets and speaker labels are not dialogue: those
  captions are left for a listener. Overlapping speakers load, and ten thousand captions check in a fraction of a
  second. Reading speed, duration, single-word lines, small gaps, words spoken but not captioned, and when each
  caption enters and leaves against the actual speech are now review prompts with their numbers (exit 0): short
  captions are often intentional, and a person decides. Overlaps, too many or too long lines, and the dialogue
  findings still exit 1. `build` writes its files when only review prompts remain.
- `selftest.py` prints any character a case reports (escaped on a Windows console or redirect in the legacy code
  page) instead of stopping the run.
- An independent review (GPT-6.1 Terra) of these changes found eight issues before release, each fixed with a case:
  nearby speech clearing a false caption, repeated words reusing one match, lead-ins read as an offset, sound
  descriptions read as dialogue, overlapping speakers refused, a quadratic slowdown, ffprobe missing from two resume
  keys, and explicit fractions being rounded.

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
