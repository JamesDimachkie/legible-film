# The shared last steps

Every path ends with Check, Screen, Revise and Deliver. Its own steps make the film; these four put the file a viewer
receives in front of the checks and the person, change only what they ask, and deliver. A bare script name
(`check.py PROJECT`) means `python "<SKILL_DIR>/scripts/check.py" PROJECT`, run from the person's working folder with
the Python `setup.py` names.

Each stage updates `status.json`; post the one-line status (`project.py status`) in chat after each one, so the
person always knows where things stand. A stage no script records (a stage that waits on the person) is set with
`project.py stage PROJECT STAGE now|done|waiting --note TEXT`.

Inside a project, these stages act on its owning timeline (`film.md` `timeline`). A version registered from a page, a
finished picture or a Tesseract export is checked, screened and graded with `check.py`, `screen.py` and `grade.py`
like any other, and never re-rendered with `cut.py` ([commands](commands.md#dispatch-by-timeline)).

## Contents

1. [Check](#check-the-file-a-viewer-receives)
2. [Screen](#screen-the-person-watches)
3. [Revise](#revise-change-what-was-asked-keep-what-was-approved)
4. [Deliver](#deliver)
5. [Map, Plan and Cut](#map-make-the-sources-legible), now in the cut path

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

Two groups report the frame and the clock. **Context** shows each frame field and its state; a field assumed or missing
reads `unconfirmed`, and says which. For the cold read, give a fresh agent the packet from `grade.py cold PROJECT`
(frames every half second and words from the first seconds, never the brief) and record its answer with `--record
--assessment ANSWER.json`; a mismatch is a `look`. **Sync** shows whether the cue list is present and fresh against this
version, its binding, every turn's decision, the frame change at each cue (a screen that says a change happened, not
that it is the intended one), whether the sound follows the list against chance, masking pairs, and the transport check.
A stale list is a `fail`, and the fix is a re-export from the owner, never an edit of the list.

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
- When a revision moves picture timing, re-export the cue list from the owner first. The old list is refused as
  stale, and so are the bed and the mix made from it, so spot, conform and mix again from the new list before
  registering the new version.
- When an editor works in Premiere, their timeline is the source of truth: `exchange.py` follows its words and
  captions through each exported revision ([editor](../paths/editor.md)).

Done when every note is done or declined with a reason, and the diff and the picture and sound comparison show no
change the notes did not ask for (or name each one).

## Deliver

- For a paper edit, `cut.py render PROJECT --final` renders `film.md` again as a new version at full size: its
  `preview.mp4` is the delivery file. `cut.py diff PROJECT vAPPROVED vNEW` should show no line or word change from the
  approved version. Master the sound for its destination: for a dialogue cut, add `--master PLATFORM` (its report
  says when the target was missed); designed sound joins through `cut.py attach-mix`. For any other owner, the
  delivery render is registered through `project.py add-version`, as its path's last build step says.
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
  checked and what was not, the weakest point, who watched and listened. Its Context and Sync sections print the
  check groups' states as written, with the two sync measures under their own labels, so "unconfirmed" and "frame
  change at cue" reach the reader. Re-read changeable claims at their source before any release.

Done when every deliverable is in `deliver/` and passes its own checks, the report is complete, and the person has
watched and heard the final files or the report names what is still unwatched or unheard. Posting and sending wait
for the person.

## Map: make the sources legible

Moved to [cut](../paths/cut.md), step 2.

## Plan: the film as text

Moved to [cut](../paths/cut.md), step 3.

## Cut: render a version

Moved to [cut](../paths/cut.md), step 4.
