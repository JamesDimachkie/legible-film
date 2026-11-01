# Recipes

One recipe per kind of video, each mapped onto the loop (Map, Plan, Cut, Check, Screen, Revise, Deliver; see
[project](project.md)). Take the recipe that matches the request, skip what it does not need, and keep the checks.

Contents: [Quick edits](#quick-edits) · [Tighten a talking head](#tighten-a-talking-head) · [Captions only](#captions-only) · [Interview or talking head](#interview-or-talking-head) ·
[Podcast or long video to short clips](#podcast-or-long-video-to-short-clips) · [Screen-recorded tutorial](#screen-recorded-tutorial) ·
[Montage, vlog or event](#montage-vlog-or-event) · [Explainer or ad with a voice-over](#explainer-or-ad-with-a-voice-over) ·
[Trailer from a finished film](#trailer-or-teaser-from-a-finished-film) ·
[Launch film or kinetic type](#launch-film-or-kinetic-type) ·
[Animated insert over a recording](#animated-insert-over-a-recording) · [Graphics over footage](#graphics-over-footage) ·
[Pinned graphics, titles behind people and privacy blurs](#pinned-graphics-titles-behind-people-and-privacy-blurs) ·
[Music or lyric video](#music-or-lyric-video) ·
[Generated clips](#generated-clips) · [Assisting an editor in Premiere](#assisting-an-editor-in-premiere)

## Quick edits

Trim, crop to 9:16 or 1:1, resize, convert, compress, extract audio, make a GIF, change speed, or two of these
together, on one file. No project folder, brief or paper edit. A request to keep the best part, a moment or a story
("cut it down to the payoff") chooses content, so it is a cut with a project and a paper edit instead. Write the
output beside the original under a new name and scratch files in the system's temporary folder, never above the
person's working folder.

1. Probe the file (`ffprobe`, or `qc_file.py FILE`) for its size, frame rate, duration and streams. Ask only for what
   cannot be inferred: the cut point, which part of a wide frame to keep when the subject is unclear, or which
   interval is meant when a request reads two ways ("trim the first 3 seconds" usually means remove them; if it could
   mean keep only them, ask).
2. Run the operation from the [ffmpeg-cookbook](ffmpeg-cookbook.md#cut-and-reframe), combining two operations in one
   command so the picture is encoded once. To remove the first 3 seconds and make a 9:16 version, put `-ss 3` before
   the input so everything after 3 s is kept, and crop and scale that interval; the cookbook has the command. For a
   fixed crop, choose its centre from a still and show the still.
3. For a 9:16 crop of a moving subject, write a one-item edit file and render it with `assemble.py edit.json --out
   picture.mp4`; it also writes one WAV stem per audio track (`main.wav` here), which the cookbook's
   [mux command](ffmpeg-cookbook.md#mux) puts back under the picture:

   ```json
   {"version": 1, "size": [1080, 1920], "fps": 30, "sources": {"a": {"file": "clip.mp4"}},
    "picture": [{"src": "a", "in": 3.0, "out": 10.0, "crop": {"path": "auto"}}],
    "audio": [{"track": "main", "src": "a", "in": 3.0, "out": 10.0, "at": 0.0}]}
   ```

   The automatic path follows the largest frontal face when OpenCV is installed, otherwise sustained motion and
   detail; neither recognises who matters: look at frames of the result
   (`frame_sheet.py picture.mp4 --every 1 --out crop.png`) and report any moment the subject leaves the frame.
4. Check the output against what was asked: its size, frame rate and expected duration (the source's length minus
   what was removed, to the nearest frame). For an H.264 MP4 with sound, `check.py --file OUT.mp4 --spec WxH@FPS
   --duration S` does this with flashing and the technical checks. It expects an H.264, `yuv420p`, BT.709-tagged MP4
   with fast start and a sound track, so for a silent file, a GIF, WebM, ProRes or an audio file, run `qc_file.py`
   with that file's own spec instead ([qc](qc.md#2-the-battery)).
5. Show the file with one line of what changed. Keep the original.

## Tighten a talking head

For a single local video, `tighten.py INPUT.mp4` writes `INPUT-tight.mp4` beside it, with a report,
machine-readable removal list, checks and a labelled listening reel. The project it makes, with the paper edit, stays
beside the result (`INPUT-tight-project/`), so the person can revise it. It never overwrites an existing output. Local
transcription needs faster-whisper and cached weights; if it is missing, ask before installing it with
`setup.py --install transcription`. `--silence-only` uses measured quiet without a transcript:
it cannot find fillers or establish word coverage, and quiet speech may be removed.

For an existing mapped project, run `cut.py tighten PROJECT int_01`. It writes `film.md`, a report,
a JSON removal list and a reel. It uses the paper edit's `max_pause` setting (0.35 s by default) for ordinary
in-line pauses, and splits a range when the compiler cannot safely shorten that gap or an alternating framing needs
separate lines. If `max_pause` would remove detected sound, the edit switches to verified quiet-only splits and the
report says so. The requested target can remain unmet when sound occupies a gap. `--pause 0.5` changes the target;
`--fillers named` additionally requests transcript words such as um, uh and hmm. For a lexical phrase, opt in
explicitly: `--fillers "like,you know,I mean"`. Repeated words and possible false starts are prompts, not cuts.
`--punch-in 1.1` alternates zoom on the generated lines; it is off by default and does not hide every interior jump.
Existing outputs are protected unless `--force` is given; the previous paper edit is saved as a backup.

For a source with a continuous music bed or prominent ambience under the speech, use `--music-bed` on either command:
it leaves pauses and
requested fillers in place because cutting them would interrupt the bed. This is a declaration, not automatic
detection. A steady bed can be mistaken for room tone, so check the source before running without the flag; the
report's sound prompts still need listening. The JSON list and reel retain the individual prompt times.

Each reel removal has a labelled BEFORE and AFTER, using the compiler's actual sound fades; LISTEN items cover
untranscribed sound. Clip edges fade over 30 ms, with silence between clips. Context reaches surrounding words and at
least about a second either side where available; a source edge can make that impossible. The report says if the reel
is long. By default the reel plays every cut and the first five listening prompts, and the report and the command's
output say how many of each it plays. `--reel-limit N` selects at most N events, cuts first (the total plays them all);
the report and the JSON keep the complete list. Without a transcript, word boundaries are not verified.

Each removal also scores its join: how much the picture changes across it, as a multiple of the shot's own change
from frame to frame. A hand or head that moved during a removed pause jumps at the join; the report ranks the joins
so those are checked first, with a cutaway, another angle or a longer pause to cover them. The score ranks; it does
not judge continuity.

The automatic cut guard requires at least 120 ms after the preceding transcript word and before the next, 30 ms of
measured sound at both fade edges within 8 dB of the source's fifth-percentile level, and at least 120 ms removed.
It can leave a longer pause when these conditions cannot be met. These measurements cannot prove that a word's tail,
quiet speech or a steady music bed is safe: inspect and listen to every join.

Read the removal list and listen to the complete reel, especially **untranscribed sound**: energetic audio outside
the draft transcript is not proof of a filler and can also be breath, music or noise. Quiet speech can escape this
screen. Check the transcript against the source, listen to tight cuts, and watch jump cuts at normal speed. The
report gives an edit time where a cutaway could hide each jump; the check identifies busy cutting in the declared
tighten section and retains its timing data. Where measured quiet handles and word clearance allow, the compiler
overlaps the sound with an equal-power crossfade of up to 0.1 seconds; otherwise it uses short edge fades. The report
says which happened and gives the actual duration.
The report distinguishes picture removals from audio omitted after the crossfade. Unstrike a filler to restore it.
For a split-range pause, merge the two lines and ranges; also change `max_pause` if it would shorten that pause again.
To restore a single in-line pause,
split at a shared continuous source boundary; `max_pause: none` restores all in-line pauses. Recheck after editing.
Giving `map.py run --prompt` a list of filler spellings may change what the transcriber retains; compare and listen,
because a prompt does not guarantee accurate words or timings. An alternative is to speed up a long pause rather
than cut it; this command does not offer that treatment.

## Captions only

1. Register the file with `map.py add PROJECT FILE --role interview`, then use `map.py run PROJECT --alias int_01
   --prompt "names and terms"` with the assigned alias. To import a transcript, use `--words import:FILE` instead.
   The map retains existing transcripts; deliberate replacement needs `--retranscribe int_01`.
2. `captions.py build`, then `captions.py check` against the transcript of the delivered audio; `burn` only when the
   feed plays muted, after reading the map's contact sheets for text already burned into the picture (subtitles,
   lower thirds), which yours must clear. Short captions are often intentional: report reading speed, never merge
   to satisfy it.
3. A person reads every caption against the audio, names and numbers first. Deliver SRT and WebVTT with the file.

## Interview or talking head

- **Map:** `map.py add` the interview (role interview) and any b-roll; `map.py run`. Read the transcript, not the
  video, to find the story; look at the contact sheets for the b-roll.
- **Plan:** read the whole transcript, write the direction (`audience`, `takeaway`, `story`), choose the ending
  first and then the opening that makes it land ([finding-the-story](finding-the-story.md)); then the paper edit:
  spoken lines in story order, sections named for their beats, cutaways where a jump cut or a claim needs a picture.
  Keep answers whole until the person has heard the structure.
- **Cut:** `cut.py render`, finished as the material allows ([finding-the-story](finding-the-story.md) §7):
  distracting jumps covered or reframed, the speaker named once, an ending that lands. Screen your own cut with
  `strip.py` (pauses, jump cuts, loudness) before showing it.
- **Check, Screen:** `check.py`, then `screen.py build` (or `serve`), and post the status line.
- **Revise:** each note becomes a paper-edit change; `cut.py diff` says what moved in the paper edit.
- **Joins:** `cut.py` looks for a measured quiet stretch at each join that removes words and lists a join without one
  as a tight cut (or as unmeasured when the audio could not be measured). Quiet is not proof of silence between
  words: a person listens to every tight and unmeasured cut. When the request
  requires cuts only in pauses, change the selects, or leave that join open until a pause is confirmed.

## Podcast or long video to short clips

- **Map** the long source with transcription; mark candidate moments in the transcript: a self-contained answer, a
  turn, a laugh, a strong claim the source supports. Prefer moments that make sense without what came before.
- **Plan** each clip in its own project folder with its own `film.md` and its own direction (each clip is a film:
  [finding-the-story](finding-the-story.md)), then render and check each separately. To
  transcribe the long source once, `map.py add` it to each project and import the first project's
  `map/<alias>/words.json` with `map.py run PROJECT --alias ALIAS --words import:FILE`. A `##` section labels part of
  one film; it does not make a separate output. Open on the strongest line; end on a resolved thought, not a cut-off
  breath.
- **Cut** at 9:16 with `crop auto` (it follows the largest frontal face when OpenCV is installed, otherwise motion
  and detail; it misses profiles, so two people sitting apart need a cut between them or a letterboxed wide shot;
  check the subject stays in frame on the strip), captions burned for muted feeds and placed clear of the platform's
  buttons ([formats](formats.md)).
- **A fast speaker** fills a narrow frame's captions faster than a viewer reads (25 to 30 characters per second
  against a limit of about 20) and long cues shrink to fit. Lower the load at its source rather than in the captions:
  strike fillers, false starts and asides the meaning does not need (listen to each new cut), or choose the passage
  where the speaker says it more slowly. Report the reading speed that remains, with your decision; never merge cues or shrink
  type to pass it.
- **Check** each clip on its own; one clip passing never covers another.

## Screen-recorded tutorial

- **Map** the recording (role screen) and any voice-over (role vo). Silences and still stretches in `audio.json` and
  the contact sheets show dead time.
- **Plan:** the steps a viewer must follow, one line each; cut dead time, speed up waits (`x2`) and say so on screen
  when timing matters; push in (`crop`) on the area being used, never so tight the pointer leaves the frame.
- **Cut, Check:** text in the recording must stay readable at the delivered size: check stills at viewing size.
  Screen recordings often vary their frame timing; the scripts time frames by presentation timestamps.

## Montage, vlog or event

- **Map** every clip; for unscripted footage the contact sheets are the selects: look at them, note the strongest
  shots, and discard soft, shaky or empty ones.
- **Plan:** the direction first ([finding-the-story](finding-the-story.md) §2), then a shape (arrival, build, peak,
  release) before a shot order; one idea per shot; a picture line per shot.
  For music, `tempo_map.py` gives the beats; cut on strong beats, not every beat.
- **Cut, Check:** motion between joins should feel continuous or deliberately broken; check the strip for repeated
  shots and for a final shot that lands with the music's ending.

## Explainer or ad with a voice-over

- A voice-over is a source like any other: record it (or generate it, with the person's yes to the cost and the
  voice's licence), then `map.py` it so its words are timed.
- The paper edit is spoken lines from the voice-over with picture over them (cutaways, stills, titles, screen
  footage). Every claim traces to the facts file ([claims-and-rights](claims-and-rights.md)); captions come from the
  voice-over's words.
- Music ducks under the voice ([sound](sound.md)); master for the destination at delivery.

## Trailer or teaser from a finished film

- **Map** the film (role `other`); a score under the dialogue hides speech from a small transcription model, so
  pass the characters' names with `--prompt` and correct the transcript before choosing lines.
- **Plan** the direction ([finding-the-story](finding-the-story.md) §8): premise, stakes, escalation, a final button,
  without the ending. Lines keep their meaning: never splice two scenes into a conversation that did not happen.
  A trailer is not the shortest piece of each beat ([finding-the-story](finding-the-story.md) §4): keep the setup
  the ending answers (the fear, the promise), show each cause before its effect, hold the emotional beats (a
  reaction, a look), and save the run of fast shots for the peak. Start from whole scenes and cut down. Every shot
  earns its place by what it tells the viewer about the thread (who, what is at stake, what has changed); a striking
  shot that tells nothing reads as random. Two lines from different scenes that seem to answer each other make a
  conversation that never happened: join scenes on a shared subject, a cause or an intended contrast instead, and
  keep the viewer oriented when the place changes.
- **Cut, Check:** the film's own music jumps at every scene change; prefer lines from one passage, or a bed of your
  own, and list each join for listening. Battle scenes and lightning often flash: screen candidate shots in the
  source (`flash_scan.py FILM --start S --end E`) before building around them. Credit the film as its licence
  requires.

## Launch film or kinetic type

Type-led films built in code use the film kit module: [kit](kit.md) and `make_film.py`, which takes a kit film from
preflight to delivered, checked files in one command, with the sound chain. A fast, beat-cut film of big words
follows [kinetic-type](kinetic-type.md). For photoreal, 3D or a different look, choose an engine in [engines](engines.md).
The loop still applies: the kit's own timeline is the plan, and `make_film.py` is cut and check. To screen a kit
film with the person, map its delivered master into a project (`map.py add PROJECT MASTER --role other`, then
`map.py run PROJECT --words skip` for a film without speech) and cut it as one picture line with its sound:

```markdown
---
title: Atlasfold
size: 1920x1080
fps: 60
captions: none
---
- src_01 0:00-0:24.00 sound The film as the kit delivered it
```

The room then shows it with its checks. Those checks run on that copy without the kit's declarations, so its designed
holds show as near-empty, and the kit's own QC (`OUT/qa/`) stays the check of record. Record the person's reviews
against the delivered master itself (`project.py review PROJECT KIND --file MASTER`).

## Animated insert over a recording

A designed animation that replaces the picture for a passage while the speakers keep talking, cut into a film made
here or handed to an editor.

- **Fix the clock first.** Map the recording (an editor's finished cut is role `other`) and find the passage with
  `map.py words`. Choose the in and out as source frames, the out exclusive, ending before the next speaker's first
  word or in a pause. Render at the source's exact rate (24000/1001, not 24), so insert frame k is source frame
  in + k and the insert's clock is source time minus the in point's time (the in frame divided by the rate). Keep
  the in, the out and every word anchor in one timing source ([timing](timing.md) §2); anchors follow
  [timing](timing.md) §1.
- **Plan it as a designed film** ([story-and-score](story-and-score.md)): one score row per event, with its word, its
  frame, picture, motion, text and truth, reviewed before you build (Plan in SKILL.md).
- **Build** in the kit when its blocks draw it, otherwise in another engine ([kit](kit.md) §1), from frozen inputs;
  in HyperFrames, write the anchors as its motion assertions ([engines](engines.md) §4).
- **Review each render on word sheets,** which label every tile with the word spoken then: one sheet at the anchors
  (`frame_sheet.py INSERT --at T1,T2 --words map/ALIAS/words.json --offset INf --out qa/anchors.png`, the times on
  the insert's clock: source time minus the in point's time) and one over the whole insert (the same with
  `--every 0.5` in place of `--at`, and `--out qa/overview.png`). Rounds follow [review](review.md) §4; a confirmed
  finding you do not take goes to the person ([review](review.md) §6).
- **Check** each render with the battery ([qc](qc.md) §2), the frames either side of each cut in context (the
  insert's first and last frames carry picture, never black), and every delivered size against the reviewed one
  ([finishing](finishing.md) §5).
- **Cut it in.** In a paper edit, give each line its own cutaway, each range continuing frame for frame from the last,
  and keep the pauses between the lines, or the insert jumps. For an editor, hand over what they ask for: usually a
  master at the exact rate (ProRes 422 HQ when they will re-encode), the in and out frames, and the timing source.
  Re-cutting the dialogue moves the words: re-time the insert.

## Graphics over footage

A lower third, a logo or a designed title drawn over the picture while it plays, made in Cavalry, After Effects or
another engine that renders transparency ([engines](engines.md) §1). The paper edit stays the film's one clock.

- **Design to the film.** Build at the size and frame rate in `film.md`'s front matter, over a transparent
  background, from the look's references ([look](look.md)), and set its key frames beside them (`look.py compare`)
  before the full render. In Cavalry the agent builds and sees the scene through its MCP server: at the start, ask
  the person's yes to what that sends off the machine and open the connection, so they click Allow in Cavalry once
  ([engines](engines.md) §12).
- **Render with transparency:** motion as a PNG MOV (or ProRes 4444, or VP9 with alpha), a still graphic as one PNG.
  Register a video with `map.py add PROJECT FILE --role broll` and a PNG with `--role still`.
- **Place it** under the line it belongs to with `~ over ALIAS [SECONDS] [+N] [fade F]` ([paper-edit](paper-edit.md)
  §5); a moving graphic plays from its first frame and animates itself. `cut.py check` refuses one at another frame
  rate or without transparency, and warns when one is not at the film's size.
- **Check** the version as usual, then step through the frames where the graphic lands and leaves in the Screening
  Room: it should sit clear of faces and the captions.
- **For an editor,** `exchange.py write` puts it on a track above the picture, without its fades; check that their
  editor reads its alpha channel.

## Pinned graphics, titles behind people and privacy blurs

A graphic or title that sits on a moving surface (a screen, a sign, a product), a title behind a person, or a blur
that follows a face or a number plate. Each reads a layer in the project's `spatial/` folder; the full contract and
commands are in [spatial](spatial.md).

1. **Choose the frames.** Write the line in film.md first, so you know the source range the effect covers. Take a
   still at the line's first frame (`frame_sheet.py SOURCE --at TIME --width 1280`) and read the surface's corners,
   the point, or the person's position from it, as fractions of the still (x over its width, y over its height),
   which `track.py` reads at the source's own size.
2. **Make the layer** over the line's range with a little margin: `track.py ALIAS --at TIME --region ... --from T1
   --to T2 --name screen --project P` for a flat surface (or `--point x,y` for something that only moves), or a
   matte for a person (`matte.py`). Read its summary: frames lost, worst error and drift, in pixels of the source.
3. **Write it** under the line: `~ still logo_01 3.0 pin screen`, `~ title "Six weeks" 2.0 behind subject`,
   `~ blur plate`. Run `cut.py check`: a missing, stale or wrong-source layer, and lost frames under a blur, are
   errors on that line.
4. **Render and look.** The version's notes list every stretch where a pin or `behind` was not drawn (another
   source on screen, a dissolve, a lost frame) and the report's `layers` gives the counts. Look at frames from the
   start, middle and end of each effect, at normal speed too; a blur stops the render rather than miss a frame, and
   a person checks every frame of it before the film leaves the machine. A blur is not anonymisation.

## Music or lyric video

- `tempo_map.py` on the track: tempo, downbeats, drops. Lyrics become timed words from `transcribe.py` on the vocal
  (or an imported lyric file), checked by a person.
- Picture and type change on the music's structure, not on every beat; flashing limits still apply to fast cuts
  ([kinetic-type](kinetic-type.md) section 8).

## Generated clips

- Generation is spending: ask for the cap first ([generation](generation.md)). Generate more than you need; keep the
  prompt, seed and model with each clip.
- Map generated clips like any source and select from the contact sheets; check every one for artefacts at full size
  (hands, text, faces that change). Label what is generated where the viewer would assume it is real.

## Assisting an editor in Premiere

The editor's timeline is the source of truth; the agent reads it and reports, and never changes their cuts. The
request sets the scope: a caption repair is a caption repair, with no paper edit and no planning loop. Map the
editor's source recordings once (`map.py add`, `map.py run`) so their transcripts are bound to the files.

1. The editor exports the sequence (File > Export > Final Cut Pro XML), the picture and the caption sidecar after
   each pass. `exchange.py read` reports clips, real cuts across crossfades, and anything not mapped (speed changes,
   effects, nested sequences).
2. Check the export as delivered, in one command:

   ```text
   check.py --file export.mp4 --captions export.srt --timeline export.xml --project PROJECT
            [--caption-profile house.json] [--delivery delivery.json] --json qa/export-checks.json
   ```

   It runs the file checks, the caption reading rules (in the editor's house style when given), the captions against
   the timeline's words (does each caption follow the edit), and the captions against a local transcript of the
   export's own sound (what is actually said; or `--speech-words FILE`, a transcript of this export). Every check it
   could not run reads "Not assessed" with what would assess it. The result records the hash of every input, so after
   the next export `check.py --verify qa/export-checks.json` says it no longer applies.
3. Words under an audio transition are marked estimated, with the transition: where they are heard is not measured.
   A source whose file changed since it was transcribed is stale, and its clips are not placed until it is transcribed
   again or confirmed (`map.py confirm-words`). A transcript that does not record its media, or that matched a clip
   by file name only, makes the timeline and caption items a look that says its identity is not verified: map the
   source (`map.py run`) so the transcript is bound to the file. Clips matched by content need the editor's media
   readable here; a proxy or transcode needs `--map CLIPFILE=ALIAS`.
4. After the editor's next pass, compare the two exports. It needs both XML revisions, the earlier captions, and the
   source transcripts:

   ```text
   exchange.py compare before.xml after.xml --project PROJECT --captions before.srt --json changes.json
   ```

   It follows each earlier caption into the new edit: unchanged, moved (with the shift), stale (the words cut),
   removed, split (the edit cut into a word; read it) or unknown (its words may be in material the comparison could
   not map or did not read). The result says whether the comparison is complete and names every track and clip it
   left out; it exits 1 until they are resolved. Without the earlier XML or the transcripts, say which comparisons
   are blocked, and check the current captions against a transcript of the current export instead.
5. Hand back a short list of proposed repairs by timecode, each tied to the files' hashes, for the editor to apply in
   their own application. On one real two-revision case, following captions through the edit flagged 5 of the
   editor's 18 caption changes and nothing else; checking captions against the source transcript placed through the
   edit flagged 21, of which the editor changed 7; together, 24 flags found 10 of the 18. Neither compared captions
   with the sound. Treat flags as candidates to read, and keep caption timing proposals apart from the dialogue cuts:
   a caption never moves a cut.

### Hand a Legible Film cut to an editor

Render the version, then write its editable Final Cut Pro 7 XML (xmeml) sequence and captions outside the version:

```text
cut.py render PROJECT
exchange.py write PROJECT v001 --out handoff.xml --verify
```

In Premiere, use File > Import and choose the XML; in Resolve, use File > Import > Timeline. Import `handoff.srt`
separately. The XML links original media by absolute file URL; `--relative` writes paths relative to the XML instead,
when moving the folder and its media together (application relinking may still be needed). Final Cut Pro X does not
import this format.

Picture, cutaways, available rendered graphics, source-channel dialogue, music, cross dissolves, audio crossfades,
lead and tail audio, and markers are written where supported. Source clips retain their full duration for handles.
The command prints the omissions and writes `handoff.notes.txt`: crops and reframing, zoom, speed changes, the mix,
gains, individual fades, spatial effects, graphic placement and burned captions need attention. A speed-changed clip
is placed at 1x; its intended source out and speed are in the notes. Mixed-rate conform and generated holds also need
inspection. Premiere ticks retain audio source points, but XML timeline positions are on a frame grid and cannot
retain every sub-frame audio offset. Compare picture, joins and sound with the render before continuing the edit.

When the version's manifest records source identities, the command refuses a size mismatch; `--verify` also checks
the recorded SHA-256. Older versions without those records are identified as unverified. The exporter has been tested
with its own round trip and OpenTimelineIO's Final Cut Pro 7 XML (xmeml) adapter on synthetic projects, and one
editor opened a synthetic hand-off in Premiere Pro 26.3 on macOS: media online with handles, clips, the dissolve, J
and L overlaps, markers and captions all in place. That test found the sequence's pixel aspect and stereo pan missing;
the sequence now declares square progressive pixels and each stereo channel is panned to its side, not yet
re-checked in Premiere. Resolve has not been tested. To compare an export from the editor with the render, export
WAV or PCM sound: AAC adds encoder delay that is not an edit offset. Transitions do not round-trip exactly; Premiere's
own XML re-export replaced custom audio fades with its default crossfade.
