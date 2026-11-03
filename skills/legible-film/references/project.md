# The project folder

Any task longer than one operation keeps its state in one folder. The folder is the agent's memory between turns
and the person's window into the work: every script reads and writes it, and the Screening Room shows it. Every path
but quick uses one; a quick edit (one operation on one file) needs none of it.

Contents: [1. Layout](#1-layout) · [2. Sources and the map](#2-sources-and-the-map) ·
[3. The paper edit](#3-the-paper-edit) · [4. Versions](#4-versions) · [5. Checks](#5-checks) ·
[6. Notes and decisions](#6-notes-and-decisions) · [7. Status](#7-status) · [8. Rules for every file](#8-rules-for-every-file)

## 1. Layout

```
<project>/
  film.md               front matter (path, timeline, frame) for every project; for a paper project, the paper edit
  cues.json             the cue list, exported from the timeline's owner (references/timing.md §0)
  audio/                conform, mixer and listening outputs, never beside a page
  brief.md              optional: who it is for, where it plays, what was promised
  map/sources.json      every source: alias, path, hash, probe, role
  map/<alias>/          words.json, shots.json, audio.json and contact sheets for one source
  spatial/<name>.json   a track or matte layer bound to one source, its frames beside it (references/spatial.md)
  cuts/v001/ ...        one folder per rendered version; its rendered media and compiled edit never change
  cuts/current          one line: the current version's name (v003)
  notes.json            notes pinned to moments
  scores.json           the person's own scorecard scores, set in the Screening Room
  decisions.jsonl       decisions, one JSON object per line, appended and never rewritten
  taste.json            optional person and preference-file binding, with this project's stable ID
  status.json           where the task stands: read by the Screening Room and the chat status line
  screening/index.html  the Screening Room
  deliver/              final files and the delivery report
```

`scripts/project.py` reads and writes this layout (paths, status, versions, times); the other scripts import it.
`project.py init PROJECT --path PATH --timeline OWNER [--page DIR]` starts one with its front matter written; each
frame field reads `missing` until `--what`, `--audience` or `--why` gives it as `assumed`. A page the film is drawn on
may live inside the project (`film/`) or beside it; `film.md` `page:` names it.

## 2. Sources and the map

`map/sources.json`:

```json
{"version": 1, "sources": [
  {"alias": "int_01", "role": "interview", "path": "media/a.mp4", "sha256": "…", "bytes": 1234567,
   "duration_s": 1832.4, "video": {"width": 1920, "height": 1080, "fps": "30000/1001"},
   "audio": {"channels": 2, "rate": 48000}, "mapped": {"words": true, "shots": true, "audio": true}}]}
```

- **Aliases** are a role and a number (`int_01`, `broll_04`, `screen_02`, `music_01`, `still_03`, `vo_01`), never a
  file name: file names often carry people's names, and an alias stays the same when a file moves. Roles: interview,
  broll, screen, music, sfx, vo, still, other.
- `path` points at the file where it already is: relative to the project folder when the file is inside it,
  otherwise the absolute local path. Media is not copied (`map.py add --copy` makes alias-named copies for a
  self-contained project). Paths stay in this local file and the Screening Room shows aliases only; review packets and reports
  built from the project can name local paths, so read them before they leave the machine. `sha256` is of the file; the map for a source is reused while it matches.
- `video.width` and `video.height` are the picture as it is shown: after the file's rotation, in square pixels. The
  coded size, sample aspect ratio and rotation are recorded beside them, and every script frames, crops and
  captions in the shown picture.
- `map/<alias>/transcript-review.json` lists places to listen before trusting the transcript (a long repeated
  phrase, words where the audio has no speech energy, speech the transcript does not cover), measured from
  `speech_band_db` in `audio.json`. They are prompts: music and noise can trigger them and quiet speech can be
  missed, and no word is ever changed or deleted because of them.

`map/<alias>/words.json` (a transcript; draft until a person has checked it):

```json
{"version": 1, "source": "int_01", "engine": "faster-whisper small", "language": "en", "draft": true,
 "media": {"sha256": "…", "bytes": 1234567, "audio_stream": 1},
 "words": [{"id": "int_01-w000001", "text": "We", "start": 12.03, "end": 12.18, "p": 0.97,
            "speaker": null, "estimated": false}]}
```

- `media` is the file and sound stream the transcript was made from. When the source's file or stream no longer
  matches it, the transcript is **stale**: every `map.py` run says so, `cut.py check` refuses spoken lines on it
  (and on a source whose file changed since it was mapped: its size on every check, its SHA-256 before a render),
  `exchange.py` does not place its words and `check.py` counts its clips, until you transcribe it again
  (`--retranscribe ALIAS`) or, after checking it against the new file, confirm it (`map.py confirm-words PROJECT
  ALIAS --note TEXT`, recorded in the transcript and `decisions.jsonl`). A transcript written before this record
  existed is bound to its source by the next `map.py run` when the file is unchanged.
- Times are source seconds. A word ID is the source alias and the word's position in that transcript, so it is stable
  for that `words.json`; a new transcription makes new IDs, recorded by `engine`.
- `estimated: true` marks a word whose edges were not measured (split from a longer segment). Empty transcript rows
  are dropped, never kept as words. `speaker` stays null unless a source states it.
- A transcript, once written, is kept: rerunning the map never replaces it (a person may have corrected it). Replace
  one deliberately with `map.py run PROJECT --alias ALIAS --retranscribe ALIAS`; `--words import:FILE` needs exactly
  one `--alias`. When a file moves, `map.py relink PROJECT ALIAS PATH` checks its hash and keeps its alias.
  `map/<alias>/transcript.md` is a readable view of `words.json` (timed phrases). `map.py words PROJECT ALIAS`
  `--from 9:11 --to 9:20` shows individual IDs, text and source-second edges and, between words, the word gap, how
  long nothing is spoken (from `audio.json` `speech_activity`; it joins pauses under about 0.5 s) and how far the
  gap's quietest quarter-second (`levels_db`) falls below the words either side. The fixed -40 dB `silences` appear
  only where they found quiet, and the header says when a source's room tone sits above that threshold. Maps without
  voice activity show levels only. A gap is not proof of silence: listen.
  `map.py fix PROJECT WORD_ID [TEXT] [--start S] [--end E]` corrects text or source-second timing and records the
  change in `decisions.jsonl`. Timing must stay inside the source and
  between neighbouring words. It retains the word ID and any `estimated` flag; listen to the result. It prints the
  word's ID and time, its text before and after with a few words either side, and each `film.md` spoken line over the
  word that stops (or starts) matching the transcript; an ID that does not exist is refused with the nearest one, and refused timing names the neighbouring
  words with their times and the window the edges must stay within.
- Shot, contact-sheet and audio maps use a format-version constant, source content hash and selected audio stream
  as their cache identity; changing the skill path or script bytes alone does not invalidate them. `map.py run PROJECT
  --check` checks cached file structure and referenced sheets without rehashing or decoding the source; it reports
  whether a transcript is present, not whether it is accurate. `map.py run PROJECT` rehashes the source. Complete
  pre-versioned v1 maps are reused and labeled; `--rebuild` regenerates map outputs. Transcripts remain protected
  unless explicitly retranscribed.
- A source's `audio` records the chosen stream: its absolute index, language, layout and start. Mapping,
  transcription, cutting and checks all use that stream; choosing another (`--stream`) for a source that already
  has a transcript needs `--retranscribe`.

`map/<alias>/shots.json`: `{"version": 1, "source": "…", "shots": [{"start": 0.0, "end": 4.2, "sheet": "sheet-01.jpg",
"tile": 3}], "sampled": false}`. Sheets hold up to 60 tiles each and cover every shot up to 600; above that the
shots are sampled (`"sampled": true`, `"sampled_count"`), and a shot without a tile has no `sheet`. `"effects"`
lists shot-change candidates within 1 s of each other that return to the same picture (a flash or effect inside one
shot: `{"start", "end", "changes", "kind", "difference_levels"}`); they are not shot changes. Maps made before it
have no `effects` until `map.py run --rebuild`.
`map/<alias>/audio.json`: `{"version": 1, "source": "…", "integrated_lufs": -23.1, "levels_db":
{"step_s": 0.25, "values": […]}, "silences": [{"start": 3.1, "end": 4.6}]}`.

Transcription runs locally: faster-whisper when it is installed (`setup.py --install transcription`; the `small`
model by default, `--quality best` for large-v3-turbo), otherwise FFmpeg's whisper filter with a downloaded model
(less accurate, word edges estimated), or an imported transcript. A model not yet on this machine is downloaded
only with `--download` (its size is named first); without it the run stops and keeps any existing transcript.
Nothing is uploaded.

## 3. The paper edit

`film.md` is the film as text, in the order it plays. The agent writes it; the person reads it like a script and may
edit it in any text editor. Front matter holds the settings; each line below it is one piece of the film:

```markdown
---
title: Northwind field story
size: 1080x1920
fps: 30
target: 45
captions: burn, srt
---

## Hook
- music music_01 0:00-1:00 -18dB fade 1.5
> int_01 12:03.40-12:07.10 We tried everything. ~~Honestly,~~ nothing held up in the field.
- broll_04 0:12.00-0:14.10 Crew unloading the van
## Why
> int_01 14:20.00-14:24.60 So we built the tool we needed, in six weeks.
  ~ screen_02 0:41.00-0:47.00 x1.5 Dashboard loads, push in to the map
  ~ title "Field view" 2.0 lower +0.5
```

- Lines play in the order they are written.
- `>` a spoken line: a source, its range in source time, then the words to keep. Deleting words from the line cuts
  them: the words are matched against the transcript in that range, and cuts fall in the pauses around removed words.
- `-` a picture line: a source, its range and a description (or `title`, `still`, `music`, `pause`).
- An indented `~` line is a cutaway: its picture covers the line above while that line's sound continues.
- `##` headings name sections. Any other text is a note to readers and does not render.
- Times are `m:ss.ss` or `h:mm:ss.ss` in the source's own time. The full grammar is in [paper-edit](paper-edit.md).

### Front matter every project carries

Every `film.md` starts with the project's path, the timeline that owns it and the frame. When the owner is not the
paper edit, the body may be empty and `cut.py check` accepts it.

```yaml
path: create                # create | cut | insert | sound | editor | quick
timeline: page              # page | paper | editor | picture | file | tesseract
page: film/                 # when the owner is a page or a Tesseract project
frame:
  what: "Fieldnote: an app that turns a site walk's voice memos into a filed report"
  audience: "site managers, on LinkedIn, often muted"
  why: "the report is the part of the day they hate"
  knows_by: [{s: 3, what: "what it is and who it is for", channel: "type"}]
  state: {what: confirmed, audience: assumed, why: confirmed, knows_by: assumed}
  waived: null              # or {reason: "...", by: "person"}
  cold_read: {state: not-run}   # matched | mismatched, with by (model), method and file_sha256
```

Each frame field is `missing`, `assumed`, `confirmed` or `waived` (with the reason and who waived it). Ask only for
missing fields, in one message. The cold read is a fresh reader's answer to "what is this, for whom, why care?" after
the first seconds (`grade.py cold PROJECT`, recorded with `--record`); it records `matched` or `mismatched` with the
reader's model, never "confirmed". A kit film outside a project puts the same `frame` keys in its spec; `film_check.py`
warns when they are missing and `make_film.py` copies them into the delivery report. `project.py status` prints the
owner and the context (`timeline: page · context: 2 confirmed, 2 assumed`), and `status.json` gains `timeline`, `path`
and `context`.

## 4. Versions

Each render writes a new `cuts/vNNN/` and never re-renders an earlier one. A version's rendered media and compiled
edit (`film.md`, `edit.json`, `lines.json`, captions, `manifest.json`) never change; the checks, QA outputs and
scorecard derived from them may be refreshed and replaced:

- `manifest.json`: `{"version": "v003", "parent": "v002", "created": "2026-10-30T09:12:00Z", "label": "tighter hook",
  "duration_s": 45.0, "size": [1080, 1920], "fps": "30", "film_md_sha256": "…", "files": {"preview.mp4": "<sha256>"},
  "notes_resolved": ["n4"], "sources": {"int_01": {"path": "…", "bytes": 1234, "sha256": "…", "video_stream": 0,
  "audio_stream": 1, "words_sha256": "…"}}}`. `sources` records every mapped source the version used as the map had
  it at render time, so a later re-map or a replaced file is visible against the version.
- `film.md` as compiled, `edit.json` (the timeline `assemble.py` renders), `lines.json` (each paper-edit line's place
  in edit time: `{"line": 12, "section": "Why", "kind": "spoken", "source": "int_01", "start": 6.0, "end": 10.6,
  "jump_cuts": [8.1], "words": [{"id": "int_01-w000412", "text": "So", "start": 6.02, "end": 6.18}]}`; a cutaway also
  carries `"over"`, the number of the spoken line it covers), `captions.srt`, `captions.vtt` and `captions.json`
  (word-timed, edit time, with word IDs). `lines.json` wraps its lines as `{"version": 1,
  "film_version": "v003", "duration_s": 45.0, "lines": [...]}`; the manifest's `duration_s` is the rendered
  length in whole frames. It also carries the join report: `joins` (each join between passages with the level,
  background and tone on each side, what bridges it and the shots around it), `picture_changes`, `busy_cutting`, and
  on each line that carries sound across a join, `sound_carry`.
- **Edit-time words** have one shape, written by `exchange.py words` and read by `captions.py check --words` (which
  also reads a version's `lines.json`): `{"version": 1, "words": [{"id": "int_01-w000412", "text": "So", "start":
  6.02, "end": 6.18, "estimated": false, "source": "int_01"}]}`, in edit seconds. `id` is the transcript word's ID
  (section 2), so a word keeps one ID through every edit; when an edit uses a source word twice, `exchange.py` adds
  a unique `occurrence`, the `clip` number and `split`, and `source_start`/`source_end`, the part of the word's
  source interval the clip keeps. `estimated` marks edges that were not measured (an estimated transcript word, or
  one a cut split). Readers ignore fields they do not know.
- `preview.mp4`: the review copy (short side 540, H.264, same colour tags as the final; with `cut.py render --final`
  it is the full-size delivery file), and `strip/strip-NN.jpg`:
  one screening strip per minute, listed in `strip/strip.json`.
- `checks.json` (section 5) and `qa/` (the checks' raw outputs), written by `check.py` after the render; rerunning
  the checks replaces them. `scorecard.json`, `scorecard.html` and `grade/` (the scorecard, its reviewer packet and
  a per-frame measurement sidecar), written by `grade.py`, are replaced the same way; so is `review/`, the packet an
  independent reviewer judges the cut from (`grade.py review`: frames of every join, the opening and ending, the
  transcript with source times, the measured checks, the brief, and the editor's direction in `direction.md` to read
  after a first impression), whose reviewer writes only in `review/notes/`. The
  rendered files themselves never change.
- Records of how the version was made: `declared.json` (designed fades, holds and title cards, which checks treat as
  intended), `caption-burn.json` (the caption size used, any rule relaxed and measured contrast), `audio-master.json`
  (both loudness passes, the mode actually used and the delivered measurements, for `--master`), and in the
  manifest `title_font` (requested and actual) and `audio_master`. `qa/technical.json` holds the technical checks'
  raw measurements.

### Identity: what a version was made from

`manifest.json` carries an `identity` block that ties the version to its source, its picture and its cue list:

```json
"identity": {
  "source": {"kind": "page", "path": "film/", "sha256": "<page fingerprint>", "snapshot_sha256": "<kept copy>"},
  "picture_sha256": "<packet hash of preview.mp4>",
  "picture_timing": {"fps_exact": "24000/1001", "frames": 720, "pts_file": "picture-timing.json", "pts_sha256": "..."},
  "binding": "receipt", "receipt": "receipt.json",
  "cues_sha256": "...", "cues_provenance": "exported",
  "conform_sha256": null, "mix": null,
  "registered": true
}
```

- `source` is the page (its fingerprint and the frozen copy's `snapshot_sha256`), the paper edit (`film_md_sha256`
  with the version's `sources`), or a picture. The picture is named by its packet hash and its frame schedule
  (`picture-timing.json`), so a remux keeps it and a re-encode, trim or retime does not.
- `cues_provenance` copies the list's `provenance` (`exported` or `observed`, or `plan-bound` for a bound plan).
- `binding` says how the master was tied to its source. `receipt` means the render attested the frozen source it read
  and the output it wrote; `screened` means no receipt, the master being newer than every source file (a look);
  `overridden` means older, accepted by a recorded decision with its reason (a look); `unverified` means the binding
  cannot be checked (a look that says why); `plan-bound` means a plan list bound by the frame-change screen at each
  turn. A mismatch is never registered; it is refused.

`cut.py render` fills the block for a paper version. `project.py add-version` registers a master made anywhere else
as `cuts/vNNN/` without re-encoding it (another container is remuxed to MP4), with `picture-timing.json`, the list as
`cues.json` and, for `--render`, `receipt.json` beside the manifest, so `check.py`, `screen.py`, `grade.py` and
`compare_versions.py` work on it unchanged. It exits 0 registered, 1 registered with a look (`unverified`, or a
planned turn with no frame change) and 2 refused:

```text
project.py add-version PROJECT --cues cues.json --file MASTER [--render "CMD"] [--sound WAV [--mix-report R]]
                       [--page DIR] [--receipt R] [--accept-older "reason"] [--label TEXT] [--stems DIR]
                       [--min-free-gib 3] [--wait-min 20]
```

`--render` runs CMD on the frozen copy the cue export kept, under the heavy-job lock with outbound network blocked
([engines](engines.md) §2). `--sound` muxes a mix onto the master with the picture copied, on any route, only when
the mixer's report (`mix-report.json` beside the WAV, or `--mix-report`) names the `--cues` list among its inputs;
the mixer reads the spotted list, so register with `cues.spotted.json`. `--receipt` takes a kit render's
`<output>.manifest.json`, and a `plan` list is bound here by screening each turn on the master.
`cut.py attach-mix PROJECT --version vNNN --buses DIR --report DIR/mix-report.json [--replace ROLE ...] [--strict]`
adds designed sound to a paper version that kept its stems (`--final`). It takes
the mixer's processed `music.wav`, `effects.wav` and `bed.wav`, never `voice.wav` or `mix.wav`; dialogue stays the
version's own stem; fades and the master are applied once; the result is a new version whose manifest `mix` names
every bus and stem it used. A retained stem with sound inside a `scope: all` silence is a look naming the stem and the
span, answered by `--replace ROLE` or a narrower scope; `--strict` refuses it instead.

A cue list stays fresh against its own version. A later version with a different picture refuses it and leaves the
earlier version fresh. Version folders are immutable; only `check.py`'s own QA files (`qa/`, `checks.json`,
`checks-final.json`) may be written into one, and only by the project that holds it.

`cuts/current` names the version the person is looking at. What a person does with a version (watched it muted,
heard it with sound, approved it) is recorded in `status.json` under `reviewed` and in `decisions.jsonl`, not in the
version folder. Each review names the file it was made on by its SHA-256, so it counts only for that file (section 6).

## 5. Checks

`checks.json` lists what was checked on one file, each with a state a person can read at a glance:

```json
{"version": 1, "file": "cuts/v003/preview.mp4", "sha256": "…", "final": false, "items": [
  {"id": "spec", "label": "1080×1920 · 45.0 s · H.264", "state": "pass", "detail": "", "at": null}],
 "summary": {"pass": 11, "look": 1, "fail": 0, "you": 2, "skip": 0}}
```

`check.py --final FILE` writes the same shape to `checks-final.json` beside it, with `"final": true` and the final
file's path and `sha256`; add `--captions FILE` to check the caption file delivered with it, or the caption items say
they read the version's own `captions.srt`.

Every checks file also records what its result depends on: `inputs` (each with its `role`, `path`, `sha256`,
`bytes` and `mtime_ns`: the checked file, the captions, `lines.json`, `edit.json`, `film.md`, `declared.json`, the
manifest, the title images, the transcripts the speech check used and, for an editor's export, the media its
timeline plays; a file that did not exist is recorded too, so adding it later counts as a change; files given to
`check.py --file` are recorded by absolute path) and `tools` (the skill version, Python, the FFmpeg and FFprobe
version lines, the packages and helpers the run used, faster-whisper and its model by name when this run
transcribed, and the SHA-256 of each script it ran). Every input is fingerprinted before the run writes anything,
and an input at a path the run writes or removes is refused. When any input or tool changes, the result is out of
date. Reading status compares each file's size and modification time and hashes only when they differ, so it is
fast and can miss a change that keeps both; `check.py --verify CHECKS.json` hashes every file and lists each change
(exit 0 current, 1 changed, 2 when a record is missing or malformed and cannot be verified). Recording a person's
review and checking a final always hash.

States: `pass` (measured and fine), `look` (measured; a person should look), `fail` (measured and wrong), `you` (only
a person can judge: watched muted, heard with sound), `skip` (not assessed: the label begins "Not assessed" and says
why and how to supply it; never read as passed). `at` is an edit time when the item belongs to a moment. An item may
carry its full measurement beside the readable detail: `dropouts` lists every hole as `holes` (`[start, end]` in
seconds), while its detail names the first eight.

Caption items say what they compared: `captions_rules` (reading rules), `captions_edit` (captions against the kept
words in `lines.json`: words cut but still captioned; this compares text with the paper edit, not with the sound) and
`captions_speech` (captions against an automatic transcript of the checked file's audio, made locally; every word
the transcript hears is checked against the whole caption timeline, differences and speech no caption carries are
`look`, so it passes only when every transcribed word is in a caption; `skip` with the install line without
faster-whisper). `captions_speech` is the only item that compares captions with the sound, and its agreement is a
screen, not proof: a transcript can mishear. Report its differences for review, and have a person check every
caption against the audio. On a final file, `loudness` (against the destination's target only when one is named)
and `true_peak` (after a lossy re-encode; `skip` with the diagnostic when it could not be measured, `fail` when the
original already exceeds −1 dBTP) are separate items. Each run writes to a fresh folder and copies only what it
produced into `qa/` (`qa/final-*` for a final file): a scanner that crashed, lacked a dependency or wrote no report is
`skip`, never an earlier result.

Two groups join the items when a project has a frame or a cue list ([qc](qc.md) §2). **Context** reports each
frame field and its state, the cold read and any waiver, as `pass`, `unconfirmed`, `look` or `not assessed`. **Sync**
reports whether the cue list is present and fresh against this version, its binding, every turn's decision, the frame
change at each cue, whether the sound follows the list, and the transport check. A stale list is a `fail`.
`unconfirmed` and `not assessed` in these groups leave the exit code alone unless `check.py --strict` is given.

The scorecard ([grading](grading.md)) is a guide for the person, not a check. `scorecard.json` names the graded
file by `media_sha256`, so a card for an older file is never shown as current. Each dimension has a score (or
`not_scored` with the reason), its basis (`measured` evidence, `judged` by a reviewer, or the `person`'s own score,
which takes precedence), its confidence, timecoded evidence and its `validation`: a state
(`passed_degradation_test`, `partly_passed` or `unvalidated`) with the cases it was and was not tested against. The
blind degradation test used two kinds of video where they apply (voice only the interview);
[grading](grading.md#validation) defines the states and has the table. A judged score carries `judge_provenance`:
`model_family`, `model` and `same_family_as_cut_maker` (true, false or null when unknown). The card's `transcript`
says where the words came from (the project, `--words`, a local transcription, or none). `grade/frames.jsonl.gz` holds
per-frame measurements keyed to the file's hash and the analysis settings, so a regrade does not decode again. A file
graded outside a project gets `NAME.scorecard.json`, `NAME.scorecard.html` and `NAME.grade/` beside it.

## 6. Notes and decisions

`notes.json`:

```json
{"version": 1, "notes": [
  {"id": "n1", "version": "v002", "t": 6.2, "line": 12, "word": "int_01-w000415", "author": "person",
   "kind": "note", "text": "cut the pause before the answer", "options": [], "status": "done",
   "resolved_in": "v003", "reply": "0.8 s shorter; caption rebuilt"}]}
```

- `kind` is `note` (from the person) or `question` (from the agent, with `options` the person can play or pick; the
  person's pick is stored on the question as `answer`). `status` is `open`, `done` or `declined` (with the reason in
  `reply`). Only questions created with `screen.py ask` carry `options`, each an existing media file inside the
  project, never under `map/` or a dot-folder; a note posted from the page never has options.
- `origin` says where a note was made: `room` (the Screening Room), `agent` (`screen.py ask`) or `flask` (brought
  in from Flask; set it when importing). `screen.py notes` lists it with each note and quotes the note's words as
  material to judge, never instructions; a note without it lists as "origin not recorded".
- Imported Flask notes retain `flask_id` and an optional local `drawn_frame` path; the same Flask ID is imported once.
  `taste.json` binds one person and an optional team profile path; the confirmed, editable preferences and their
  evidence live in that profile, not in the version ([taste](taste.md)). Film-specific preferences follow the
  project's stable ID, including when its folder moves.
- A note pinned over a cutaway names what is on screen and what is heard: `line` and `source` are the visible
  picture (also in `picture_line` and `picture_source`), and `spoken_line`, `spoken_source` and `word` are the speech
  under it when known. Older notes may lack these fields.
- `scores.json` (project root) holds the person's own scorecard scores, kept apart from the agent's:
  `{"version": 1, "scores": {"v003": {"hook": {"score": 7, "by": "person", "at": "…"}}}}`, written by the
  Screening Room with the project's file lock.
- `status.json` `reviewed` is keyed by version, then by the id of a check only a person can judge (`watched_muted`,
  `heard`, `names`), plus `approved`; each value is `{"by": "…", "at": "…", "file": "cuts/v003/preview.mp4",
  "sha256": "…"}`, naming the file the person reviewed. Reviews of the version's preview sit directly under the
  version; reviews of another file of that version (a final) sit under `files`, keyed by that file's SHA-256:
  `{"v003": {"watched_muted": {…}, "files": {"<sha256>": {"heard": {…}}}}}`. A review counts for a checked file only
  when its `sha256` matches that file's content, so watching the preview never passes a different final; an older
  record without `sha256` counts for the preview only. Writers: the Screening Room (the preview it plays) and
  `project.py review PROJECT KIND [--file FILE]` (`project.record_review`), used only when the person says they did
  it.
- `decisions.jsonl`, one line each: `{"at": "…", "by": "person|agent|reviewer", "category": "story|picture|sound|captions|delivery",
  "subject": "…", "decision": "…", "rejected": ["…"], "version": "v003"}`.
  `screen.py decide PROJECT --category story --subject opening --decision "keep" --by reviewer` records a decision.
  Categories are `story`, `picture`, `sound`, `captions` and `delivery`; `--by` is `person`, `agent` or `reviewer`.

## 7. Status

`status.json` says where the task stands, for the Screening Room and for the one-line status the agent posts in chat:

```json
{"version": 1, "title": "Northwind field story", "skill_version": "2.0.0", "updated": "2026-10-30T09:14:00Z",
 "stage": "screen", "stages": {"map": "done", "plan": "done", "cut": "done", "check": "done", "screen": "now",
 "revise": "todo", "deliver": "todo"}, "current": "v003",
 "line": "v3 checked · 11 checks pass · 1 to look at · 2 need you",
 "running": [{"job": "render v004", "started": "…", "progress": 0.4, "pid": 4120}],
 "needs_you": ["watch v3 muted", "listen with sound"], "blind_spots": ["not heard on a phone speaker"],
 "reviewed": {"v003": {"watched_muted": {"by": "person", "at": "…", "file": "cuts/v003/preview.mp4",
                                           "sha256": "…"}, "heard": null, "approved": null}}}
```

Stages: map, plan, cut, check, screen, revise, deliver; each `todo`, `now`, `done`, `skipped` or `waiting`.
`project.py stage PROJECT plan waiting --note "Agree the direction"` records that the agent has done its part and
the person needs to respond. `project.py status PROJECT` shows every waiting stage and its note;
`project.py stage PROJECT plan done` resolves it. A wait is not silently completed by later stage work. A project only moves
forward on its own: moving to the next stage completes the one it leaves, a jump over stages leaves them to do, and a
script that works on an earlier stage (mapping a new source during Revise, rebuilding the room) leaves the stage where
it is. Going back is explicit (`project.set_stage(root, stage, back=True)`) and resets the stages after it.

The line reads `vN checked · …` once checks exist (with `approved` when the person approved it); when a final check
exists it adds `; final deliver/film.mp4 checked · 1 failed · …`, naming the file it describes, and a person item
counts as done only when a review matches that file. A final check with a failure sets the `check` stage back to
`now`. Before any check the line reads `vN rendered · not checked yet`, and it names a running job while one runs;
the room and `project.py status` print the same line. Each running job records its process ID (`pid`), so a job
whose process has died (a killed render or mapping) is left out of the line and the room. A checks file whose
inputs changed reads `out of date (cuts/v003/captions.srt changed): run check.py again`; one written before inputs
were recorded ends `· inputs not recorded`. `approved` shows only when the approval was recorded for the checked
file's SHA-256 and that file is unchanged: a preview replaced after it was rendered says so and is approved by no
one. When `status.json` cannot be read as written, the Screening Room's fallback line still shows the final check and
whether each result is current, or says the status is unknown.

A stage marked done means its work ran, not that its checks passed or that the person accepted it. A reader that
needs those (an integration, a delivery gate) uses `project.py status PROJECT --json`, which keeps four things
apart: `progress` (stages, notes and running jobs), `checks` (each checks file: current, out of date or inputs not
recorded, with its summary), `review` (person checks and screening notes still open) and `acceptance` (the person's
`approved` record for a file's SHA-256, or none).

## 8. Rules for every file

- UTF-8 JSON and Markdown with LF line endings; paths relative to the project folder; times in seconds unless the
  format says otherwise.
- Writes are atomic (a temporary file, then a rename), so a page or agent reading at the same moment never sees half
  a file.
- No personal names in aliases or in file names the scripts create. Transcripts, captions, burned-in pictures, file
  metadata and the reports built from them hold whatever the material holds: the scripts do not remove names from
  them, so check anything that leaves the machine against the project's privacy rules. The folder stays local;
  nothing in it is uploaded without the person's yes.
