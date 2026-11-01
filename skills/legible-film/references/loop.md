# The loop, stage by stage

The full text of each stage. [SKILL.md](../SKILL.md#the-loop) holds the order, the one-line status after each
stage, the command that starts it and its done-when line; read the stage here before you run it on a project.
A bare script name (`check.py PROJECT`) means `python "<SKILL_DIR>/scripts/check.py" PROJECT`, run from the
person's working folder with the Python `setup.py` names.

Map, Plan, Cut, Check, Screen, Revise, Deliver. Each stage updates `status.json`; post the one-line status
(`project.py status`) in chat after each one, so the person always knows where things stand. A stage no script
records (Plan, or a stage that waits on the person) is set with `project.py stage PROJECT STAGE now|done|waiting
--note TEXT`: `waiting` when you have done your part and it needs the person, such as agreeing the direction.

## Contents

1. [Map](#map-make-the-sources-legible)
2. [Plan](#plan-the-film-as-text)
3. [Cut](#cut-render-a-version)
4. [Check](#check-the-file-a-viewer-receives)
5. [Screen](#screen-the-person-watches)
6. [Revise](#revise-change-what-was-asked-keep-what-was-approved)
7. [Deliver](#deliver)

## Map: make the sources legible

`map.py add PROJECT FILES --role interview|broll|screen|music|vo|sfx|still|other` (`other` for a finished film or
anything else), then `map.py run PROJECT`. Each source
gets a role-and-number alias (never its file name) and the map its streams allow: shots with contact sheets for
picture, loudness and silences for sound, and a local word-timed transcript (`transcribe.py`) for every source with
sound (`map.py run PROJECT --alias ALIAS --words skip` leaves one out, such as music whose words do not matter). A
still gets one sheet and nothing else. Read the transcripts (`map/<alias>/transcript.md` is the readable view) to find
the story and the sheets to find the pictures; you do not need to watch. A file with several audio tracks uses its
default one unless `--stream INDEX` names another, and every later step uses the same one. An existing transcript is
imported (`--words import:FILE --alias ALIAS`); a missing model is installed by `setup.py --install transcription`
with the person's yes. A transcript is never replaced once written (people correct them): `map.py fix PROJECT
WORD_ID TEXT` corrects a word and records it (`--start S --end E` corrects its timing, when a smeared word edge
puts a cut in speech), `--retranscribe ALIAS` replaces one deliberately, and `map.py relink` follows a moved file.
A transcript records the file and sound stream it was made from; when the file changes it is stale, and no script
uses its words until you transcribe it again or, after checking it against the new file, confirm it (`map.py
confirm-words PROJECT ALIAS --note TEXT`).
`map.py words PROJECT ALIAS --from 9:11 --to 9:20` lists word times and the measured pauses for choosing ranges;
`map.py run PROJECT --check` confirms a map is complete without redoing it. Transcription runs at about real time to 30 times faster depending on the machine and what
else it is doing, and prints its progress: start `map.py run` for a long source in the background (or with a long
timeout) and read its output, rather than letting a tool time-out stop it part way.

Rotated phone video, non-square pixels, variable frame rate, HDR and captions in Arabic, Hebrew, Thai or Devanagari
are handled ([footage](footage.md)); review transcript prompts at the joins they touch, complex-script
captions with a fluent reader, HDR-to-SDR conversions, and the picture and sound of every retime.

Done when every source has the map its role and streams allow, and anything not mapped is named with the reason.

## Plan: the film as text

- When the request leaves the look open (a designed film, titles, music or a grade, or the person asks), start
  from the person's taste: their references, or their expectations when they have none, asked in one message
  with a default per question and kept in `look.md` ([look](look.md)). Everything below reads it.
- Decide what the film is for before choosing a single line, and write it at the top of `film.md`: `audience` (who
  watches, where, and what they already know), `takeaway` (what they leave with, one sentence starting "They") and
  `story` (the spine in one sentence, with a turn in it). For a recording, read everything, write three spines that
  are different films, have a reviewer compare them, and build the strongest from its ending
  ([finding-the-story](finding-the-story.md) §3); for a designed film, write three concepts, choose
  one ([story-and-score](story-and-score.md)), and have a reviewer who did not write it judge the concept
  and its score before you build ([plan review brief](../assets/templates/plan-review-brief.md) C): structure is cheap
  to change only then. A cut can pass every check and still be a list of lines:
  the direction is what makes it a film.
- Write the paper edit, `film.md` ([paper-edit](paper-edit.md)): spoken lines in the order they play,
  pictures, cutaways, titles, music. The recipe for the kind of video says what matters
  ([recipes](recipes.md)). `cut.py draft` makes a first one from selected phrases; `grade.py hooks` lists
  lines in the transcripts that could open the film, with how long each takes to say and whether it cuts cleanly.
- Before rendering anything long, `grade.py paper PROJECT` puts the paper edit in front of a reviewer who judges its
  hook, structure, pacing and ending against its stated direction.
- Give every essential text a reading window and keep one clock for picture and sound ([timing](timing.md)).
- When a brief exists, its deliverable fits one line: size, frame rate, duration, renditions, sound, captions
  ([formats](formats.md)).

Done when, for a paper-edit project, `film.md` states its audience, takeaway and story, a note under each section
says why that beat follows, a note at each join between passages says what links its two sides in meaning and what the viewer feels across it
([finding-the-story](finding-the-story.md) §4), and `cut.py check` has no errors and a decision for each
warning; for a kit
film, the direction and beats are in the brief or score and its own timeline checks. When you chose the direction
(the request left it open), the person has agreed it and the plan; a request that already fixes them (a cutdown to a
stated length, a repair, an editor's revision) needs no further agreement.

## Cut: render a version

- `cut.py render PROJECT` compiles the paper edit into a new version (`cuts/vNNN/`: preview, timeline, timed lines,
  captions, manifest) and never changes an earlier one. A cut inside a spoken line goes in a quiet stretch measured
  in the audio; a join with no clear quiet stretch is listed as a tight cut, and a join whose audio could not be
  measured is listed as unmeasured. Quiet is not proof of a pause (a stop consonant can be quiet), so each tight or
  unmeasured cut needs a person's ear, or selects that cut at a clear pause.
- Render a version for a change you mean to keep. Settle alternatives (a caption split, a trim) with `cut.py check`,
  stills and the strip first; render competing versions only when the person asks, or as [review](review.md) §6
  describes.
- Finish a recording as the material allows: distracting jumps covered or reframed, the speaker named once (unless
  the project's privacy rules keep that name off screen), an ending that lands
  ([finding-the-story](finding-the-story.md) §7).
- Before the person sees it, an editor who did not make the cut reviews it: run `check.py PROJECT` first, so the
  packet carries the measured checks, then `grade.py review PROJECT` builds the packet and its brief; give it to a
  reviewer with no part in the cut (a fresh agent, of another provider only with the person's yes: the Gates), verify
  its findings, fix the confirmed ones and re-review once ([review](review.md) §4). You cannot watch your
  own cut and you see what you meant: in four agent cuts tested, the flashes of other shots, holes in the sound and
  events merged out of order were missed by the agents that made them and found by independent reviewers. Read the
  strips (`strip.py`) yourself as well.
- Code-rendered frames are pure functions of time; footage keeps its own motion and shutter. Render from frozen
  sources, convert and tag colour explicitly (BT.709 for HD), and mux the mastered sound onto the picture with lengths
  matched ([finishing](finishing.md), [ffmpeg-cookbook](ffmpeg-cookbook.md)).

Done when the version renders and an independent review leaves no blocking or visible finding open, or names each
one for the person (a self-review is labelled as one).

## Check: the file a viewer receives

`check.py PROJECT` runs the checks this file and job call for (its `--help` lists them) and writes `checks.json`:
spec, sound edges, flashing, near-empty frames (the paper edit's fades, holds and cards are declared for it),
technical checks, an empty first frame, burned-caption contrast, title contrast (each title's letters against the
picture around them, 3:1 at least; a low title gets the nearest colour and a black plate that pass, with their
ratios), what only a person can judge, and captions as three items that say what
they compared: reading rules, following the edit (against the kept words), and matching the speech (a screen against
a local transcript of the file's audio, when faster-whisper is installed). A final file adds loudness against a named
target and true peak after a lossy re-encode. Each item is pass, look, fail, needs you or not assessed (with what
would assess it). `checks.json` records every file and tool the result depends on; when one changes, the status says
the result is out of date (it compares size and time; `check.py --verify` hashes every file and lists what changed). A house caption style with reviewed exceptions
goes in with `--caption-profile` ([footage](footage.md)). For deeper checks
(a claim through its whole interval, sound on cue, drift, what a revision changed), use the scripts in the table
below and [qc](qc.md); declare designed holds, cuts and silences before running detectors, and keep each
check's exit status.

Done when every check that applies has run, nothing fails, and each look has a recorded decision. A not-assessed
item stays unverified: install what it names and rerun, or run the script that measures the same thing and say which;
otherwise report it as not checked. The needs-you items wait for Screen.

## Screen: the person watches

`screen.py build PROJECT` writes the Screening Room (`screening/index.html`): the cut beside its paper edit, the
readiness line, what changed since the last version, checks, notes and versions. Open it for the person, or run
`screen.py serve PROJECT --open` for live mode, where their notes and ticks reach the project folder directly and the
page follows new versions. When the person reviews away from this machine or with others (a client, an editor, a
team), [Flask](https://flask.do) is the recommended collaboration and feedback layer: post each version there and
bring every note back into `notes.json` ([review](review.md) §1; posting there needs the person's yes,
asked once per project: the Gates). Ask for a muted pass at viewing size, then a pass with sound. Put open choices to them as
options they can play (`screen.py ask PROJECT --at T --text Q --option A=PATH --option B=PATH`), loudness-matched, one
difference at a time ([review](review.md)). For a small revision, a short report of the changed moments
with their times can stand in for the room and the scorecard. Synthetic critics find problems to verify; they never
outrank the person's approved choices. Replaying a moment and stepping frames in the room are for inspecting; only a
full pass at normal speed counts as watched or heard.

**The scorecard** ([grading](grading.md)) breaks a version into fifteen dimensions of content, picture,
sound and delivery, scored 0 to 10 with evidence. `grade.py PROJECT`, or `grade.py --file FILE --platform NAME` for
any file (card beside it; check its delivery spec separately), measures the file and writes a reviewer packet; it
does not score. A reviewer who did not make the cut (a fresh agent, chosen as the Gates say) scores from the packet,
citing moments, and `grade.py merge PROJECT judged.json` checks that each citation exists and writes the card the
room shows. Without one, label your scores self-review, low confidence, and leave unobservable dimensions unscored.
The card guides what to change first and is never approval: the person's scores (`scores.json`, set in the room) take
precedence, and `grade.py scores PROJECT` refreshes the card after one changes (the live room runs it itself).

Done when the person has watched (and heard) the version, or the status names exactly what is still unwatched or
unheard.

## Revise: change what was asked, keep what was approved

- `screen.py notes PROJECT` lists open notes with their moment and line. Before you edit `film.md`, `cut.py diff
  PROJECT vLAST` (one version) shows what changed in it since that render: the person may have edited it, so build
  on their changes. Each note becomes a paper-edit change at its cause; render a new version; `cut.py diff PROJECT vA vB` lists the paper-edit lines, words, durations and captions
  that changed, and only what the note asked for should change.
- Compare the rendered picture and sound with the approved version too: `compare_versions.py` locates candidate
  picture changes between lossy renders and exact changed frames only between verified lossless ones; inspect
  important text and the changed moments at full size; when a sound moves, check the old window is quiet and the new
  one on cue (`cue_onsets.py`). [qc](qc.md#6-change-proof-on-every-revision) has the method.
- Close each note (`screen.py resolve PROJECT NOTE --in vNNN --reply TEXT`) and record decisions with what was
  rejected (`screen.py decide`).
- When an ambiguous note would change approved design, show a still or a short motion proposal first. Check every use
  of anything shared you changed.
- When an editor works in Premiere, their timeline is the source of truth: `exchange.py` follows its words and
  captions through each exported revision ([recipes](recipes.md#assisting-an-editor-in-premiere)).

Done when every note is done or declined with a reason, and the diff and the picture and sound comparison show no
change the notes did not ask for (or name each one).

## Deliver

- `cut.py render PROJECT --final` renders `film.md` again as a new version at full size: its `preview.mp4` is the
  delivery file. `cut.py diff PROJECT vAPPROVED vNEW` should show no line or word change from the approved version.
  Master the sound for its destination: for a dialogue cut, add `--master PLATFORM` (its report says when the
  target was missed); for a designed film, `mix_cues.py` (music ducked under voice).
- Copy the new version's `preview.mp4` into `deliver/` under a versioned name (`deliver/film-v004.mp4`) with its
  `captions.srt` and `captions.vtt` beside every file with speech; burn captions in only for feeds that play muted.
  Run `check.py PROJECT --final deliver/film-v004.mp4 --captions deliver/film-v004.srt` on that copy, so the
  captions checked are the ones delivered, and record its SHA-256.
- Rebuild the Screening Room (`screen.py build PROJECT`) so it shows the final version, and ask the person to watch
  it at normal speed and, when it has sound, to listen. A review counts only for the file it was made on: when the
  person says they watched or heard the delivered file itself, record it with
  `project.py review PROJECT watched_muted|heard|names --file deliver/film-v004.mp4`. Until they have, the report
  names it unwatched (and unheard) and awaiting approval.
- Where the platform shows a cover or thumbnail, `grade.py thumbs` proposes candidate frames to choose from.
- Write the delivery report ([template](../assets/templates/delivery-report.md)): hashes, specs, what changed, what was
  checked and what was not, the weakest point, who watched and listened. Re-read changeable claims at their source
  before any release.

Done when every deliverable is in `deliver/` and passes its own checks, the report is complete, and the person has
watched and heard the final files or the report names what is still unwatched or unheard. Posting and sending wait
for the person.
