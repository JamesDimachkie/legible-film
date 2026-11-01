# Finding the story in a recording

For interviews, podcasts, talks, vlogs, events and any footage you did not design. The story is already in the
material: find it, choose it, and tell it in fewer words than were spoken. Use this during Plan before a single line
goes into `film.md`, and again whenever a cut is correct but nobody can say what it is about. A cut can pass every
check and still be a list of lines; this is what turns it into a film. Designed films (launch films, explainers)
start from [story-and-score](story-and-score.md) instead.

Contents: [1. Read everything](#1-read-everything-first) ·
[2. Direction](#2-write-the-direction-before-choosing-lines) · [3. Build from the ending](#3-build-from-the-ending) ·
[4. Cut for feeling](#4-cut-for-feeling) · [5. Lines](#5-choosing-lines) ·
[6. Picture and sound](#6-picture-and-sound-serve-the-words) ·
[7. Finish it like an editor](#7-finish-it-like-an-editor) · [8. Footage someone else made](#8-footage-someone-else-made) ·
[9. Before rendering](#9-before-rendering)

## 1. Read everything first

Read the whole transcript (`map/ALIAS/transcript.md`), not a keyword search, and look at every contact sheet. As you
read, mark candidates by what they can do in a film:

- **Stories:** an event with a moment in it ("the night the server room flooded"). One good story can carry a
  whole short film; a list of opinions rarely can.
- **Turns:** a "but", a change of mind, a surprise, the moment the speaker's view of something changed.
- **Images:** a line that makes the viewer see something.
- **Stakes:** why it matters to the speaker, in their own words.
- **Endings:** a line that resolves, reflects or looks forward, said with a finished, falling cadence.
- **Openers:** a specific, surprising line that makes a viewer ask a question.

Note what is missing as well: a fact the audience needs that nobody says on camera. A short title can carry it.

## 2. Write the direction before choosing lines

Write three settings at the top of `film.md` ([paper-edit](paper-edit.md) §2) before any lines:

- `audience:` who will watch, where, and what they already know.
  For example: `people scrolling a phone feed who have never heard of her`.
- `takeaway:` what they leave with, one sentence starting "They".
  For example: `They see that one stubborn engineer fixed what a whole team had given up on.`
- `story:` the spine in one sentence: where it starts, what changes or comes clear, where it lands.
  For example: `A field engineer tired of losing data builds the tool she needed, and the whole team switches.`

If you cannot write the story sentence, you do not have a film yet: read again, or ask the person what it is for. A
story sentence that strings events together ("he did this, then that, then this") is a chronology: say instead the
one question the opening raises and the answer the ending lands on. In a blind test, an interview cut whose story
listed four milestones played as a highlights reel, and a cut of the same interview built on one question was the
one both judges ranked first.
Each line you consider either moves the story or stays out. `cut.py draft` keeps the direction already in
`film.md`, so write it first and draft the selects into it.

## 3. Build from the ending

Choose a shape the material supports: a question and its answer, a change, a portrait, or an open reflection. Not
every recording has a reversal; every film needs an opening this audience can follow and an ending that completes,
or deliberately reframes, what the opening promised.

**Write three spines before choosing lines.** The first story you find is seldom the strongest, and two runs on the
same interview found stories of very different strength. Write three story cards in `plan/spines.md` (outside
`film.md`, where a heading would become a section), each a different film rather than three orders of the same
lines: a different question, ending or shape.
Each card gives the ending line, quoted with its source time; the opening line that raises the question it answers;
three to six beats with source times; what it leaves out; and why a stranger would stay. Then compare them, best by
a reviewer who did not write them ([review](review.md) §4): which opens one question and answers it, hooks this
audience, keeps the speaker's meaning and the order of events, and fits the length without shaving every beat
([plan review brief](../assets/templates/plan-review-brief.md), part A).
Build the strongest, and record the choice and the runner-up (`screen.py decide`). The steps below build it.

1. **Try the ending first:** the candidate that best delivers the takeaway, usually a reflection, a consequence or
   the opening's question answered, said with a finished cadence. A line that trails off ("and so, yeah") cannot
   end a film.
2. **Then the opening that makes that ending land:** a concrete, specific line that raises the question the ending
   answers, starting where its sentence starts (a clipped first clause reads as a mistake, and its first caption
   starts mid-sentence). Never a greeting, a name and title, or context the viewer has not yet asked for; a title can say who
   the speaker is. Hold back the answer, never the subject: within the first few seconds a stranger should be able
   to say what the film is about, unless it is deliberately abstract.
3. **Then the middle:** the fewest steps from that question to that answer. Each line follows from the one before
   and leads to the next; context only as much as the ending needs. At every point the viewer should be waiting to
   find something out: answer nothing before they wonder about it, and in a film over about a minute, open the next
   question before closing the current one, so no stretch leaves them nothing to stay for. Every question the film
   opens is answered, or deliberately left open, by the end.
4. **If the shape has a turn,** a first draft places it about two thirds of the way through (in 60 s, around 35 to
   45 s), leaving the ending room to land ([story-and-score](story-and-score.md) §5). Timings and word counts here
   are starting estimates, not rules.

Name the sections of `film.md` after the beats they play (`## Opening`, `## Turn`, `## Ending`, or names that say
what each does), and under each heading write one plain line (any plain line is a note to readers): what the viewer
learns in this beat and why the next one follows. If you cannot write that line, the order is wrong.

## 4. Cut for feeling

You read a film; a viewer feels it. Decide each cut the way an editor does, by what the viewer feels next, in this
order: the feeling first, then the story, then the rhythm, then where the eye is (Walter Murch's priorities in *In
the Blink of an Eye*). A cut that serves the story but breaks the feeling is the wrong cut. A structure filled in
with the shortest pieces that fit is not a film: a teaser cut that way from a feature lost the line its ending paid
off and jumped from a quiet moment to a furious one with nothing on screen to cause it.

- **Join on meaning, not on words.** Two pieces belong side by side when they share something the viewer can follow:
  the same subject; the same situation, or a change of place or time the viewer can read; a question the first
  raises and the second answers; a cause and its effect; or a contrast you intend. Words that happen to fit are not
  a link. A line that grammatically answers the last one but was said about something else, or a word repeated
  across two unrelated moments, makes a connection that was never there, and the viewer believes it: anything placed
  side by side reads as connected. Check the meaning each juxtaposition creates against the source.
- **Every shot tells the viewer something.** Ask of each line and each shot what it tells the viewer that the thread
  needs next: who someone is, what is at stake, what has changed, what it costs. A shot that tells the thread
  nothing reads as random, however striking it is. Cut it, or find the shot that carries the thread.
- **Keep the viewer oriented.** The viewer knows where and when they are and why the film has moved. A new place or
  time needs a cue: a shot that establishes it, a sound that leads in, a line or title that names it. Disorient only
  on purpose, and know why.
- **Every change of feeling is caused on screen.** When a person goes from hurt to furious, the viewer sees what
  turned them (a line, an event, a plan failing), or the shot holds long enough for the change to happen. A cut
  that skips the cause makes the change read as a mistake.
- **Keep the setup the ending needs.** The line or image the end pays off (a fear that comes true, a promise kept or
  broken) is worth more than another shot of spectacle. Cut spectacle before setup.
- **Let moments breathe.** The feeling of a line often lives in what follows it: the listener's face, the silence,
  the look away, the hesitation before an answer. Do not cut on the last syllable of an emotional line; take the time
  from a less important beat. When the shot cannot run on (the next words, or a false start you removed, begin at
  once), give the beat after the cut: start the next shot inside its own pause, before the reply. A teaser that cut a
  hesitation of 3.3 s after a challenging question down to 0.33 s felt abrupt to the person watching; holding the
  next shot on a second of its silence before the answer fixed it. `cut.py check` names a question or exclamation
  answered with under half a second where the source took a second or more.
- **Rhythm is a choice.** A new place or person needs time to register, often two seconds or more. A run of short
  shots is a deliberate flurry at a peak, not a way to fit more in; everywhere else, hold each shot long enough to
  be read. `cut.py check` warns at three picture changes within three seconds, except in a section whose name
  contains "montage".
- **Sound carries continuity.** A viewer forgives a picture cut far more readily than a sound cut. Across a join
  between passages, carry the sound (one line's sound running on under the next picture, the next sound arriving
  early, a crossfade, a bed under both), or cut on a strong beat where the hard change is the point: `{tail 0.8}`
  runs a line's sound on under the next, `{lead 0.5}` brings a line's sound in early, and `{dissolve N}` crossfades
  the sound with the picture ([paper-edit](paper-edit.md) §7). `cut.py check` reports the background level and tone
  on each side of every join: bridge each abrupt one, or say why it stays.
- **When it runs long, cut whole beats, not breaths.** Remove the least necessary beat entirely rather than shaving
  every beat until nothing lands. Length is a guide: if the piece needs more time to feel whole, say so to the
  person rather than shave.
- **Start long.** Lay the chosen scenes end to end whole first (an assembly two or three times the target), read
  it, then cut down beat by beat, keeping causes, setups and reactions.

At every join where the source changes or skips ahead, write one plain line in `film.md` between the two lines:
what links the two sides (the shared subject, situation, question, cause or intended contrast), where the viewer is
on each side, and what they feel before and after. If the only link is that the words fit, or you cannot write the
line, the join is wrong: keep more of the scene, add the cause or the cue, or move the line. `cut.py check` names
each join between passages that has no note.

## 5. Choosing lines

- Prefer the story to the summary, the concrete to the abstract, and the speaker's own stake to facts anyone could
  recite.
- One idea per line; keep a pause that carries meaning.
- A whole answer often beats four fragments. As a starting estimate, a 60-second piece holds about 120 to 150
  spoken words with room to breathe.
- **Keep the speaker's meaning.** Remove repetition and false starts only when the meaning stays intact. Keep
  negations, uncertainty, attribution and conditions ("might", "we think", "if it works"). Never attach an answer to
  a different question or fabricate a conversation. Compare every rearranged or shortened statement with the
  question and answer around it in the source, and flag context you cannot verify. Viewers take consecutive lines
  as one telling, in order: two similar stories from years apart play as one event unless the cut keeps them
  apart. `cut.py check` names every interview line said more than 30 s before the line it follows.
- Cut where the meaning and the sound both allow it: whole sentences give clean joins ([paper-edit](paper-edit.md)
  §3).

## 6. Picture and sound serve the words

- Cutaways go where the words describe something visible, where a jump cut needs covering, or where a big idea
  needs a moment to land; never as wallpaper.
- Give the key line room: a held shot or a beat of silence after it.
- A source with music baked into the dialogue (a film, a produced interview) jumps at every cut between passages.
  Prefer lines from one continuous passage, or obtain separate dialogue and music stems. A picture dissolve or a new
  bed does not repair a jump in the original soundtrack: ask a person to listen to each such join, and where it
  cannot be repaired, list it as an open issue.

## 7. Finish it like an editor

A cut with the right lines in the right order can still look like a test. Give it the finish a viewer expects
before anyone sees it (the grammar is in [paper-edit](paper-edit.md) §6 and §7):

- **Hide the jumps that distract.** A cut inside a spoken line is a jump cut on the speaker's face. Cover it with
  relevant footage (`~`) where there is some. Where there is none, a deliberate framing change of about 20% or more
  (split the line at the cut and give the second half `{zoom 1.2}`) can carry it, but only when the source's
  resolution and the crop allow it ([footage](footage.md)); an intentional, visible jump can also stay.
- **Leave no flash frames.** A range that starts or ends a moment before a shot change in its source shows a sliver
  of the other shot (a stray face, a transition graphic), and a cutaway that ends just before the next line leaves a
  glimpse of the speaker. Every one of four agent cuts tested had one. `cut.py check` names each with the time to
  move the edge to.
- **Name the speaker once,** when the viewer first wants to know who they are, never as the opening:
  `- title "Dana Ortiz" "Field engineer" 3.0 lower`.
- **Start clean:** trim silence before the hook; add `{fade in 0.3}` on the first line only when it serves the
  opening.
- **Let the ending land:** give the final thought a clean handle where the source has one (the range running on past
  the last word without the next sentence starting); otherwise choose another ending or an intentional `pause` with
  `hold`. Add `{fade out 1.0}` only when it serves the ending. Under a held last frame, carry the room (the line's own
  tail with `{tail N}`, or room tone laid under it): a blind judge heard 1.5 s of dead silence under a final fade as a
  cut-off.
- **Keep the room under every cut.** A produced source often has exact digital silence at its own edit points, and a
  listener hears the room vanish; each of four agent cuts tested kept at least one such hole. `check.py` lists them.
  Fill each with room tone from a quiet moment of the same source laid under it
  (`~ music int_01 0:21.40-0:22.20 0dB fade 0.05 +1.85`), or move the edge past it.
- **Music only when it serves:** a bed at the top of the film (`- music ALIAS 0:00-1:00 -20dB fade 1.5`) can lift a
  talking piece when its mood matches the takeaway; it ends with the film. Balance it against the actual voice, not a
  fixed gain, and have a person check that every word stays clear. Use only music the person has the right to use.
- **Captions** on for anything that plays muted in a feed (`captions: burn`), with names checked against a source.
- **Screen it** with `strip.py` before the person does, to find possible jumps, silences and captions that leave
  before they can be read. Motion, cadence, how each join sounds and the mix need a person watching and listening
  at normal speed.

## 8. Footage someone else made

A film, a series or an event recording follows the same spine, with one more rule: do not splice lines from
different scenes into a conversation that never happened. A cut that mixes scenes is a trailer or a montage and has
its own shape (premise, stakes, escalation, a final button); say which it is in `story:`. Check the rights to the
footage and to any music in it for the intended use.

Confirm who says each line. A transcript does not name its speakers, and in a scene with several people the face on
screen is often the listener: before a line is shown over a person, or relied on as theirs, look at the frames
around it (whose mouth moves, who the next shot cuts to). In one teaser a line held over a character for four
versions was another character's; frames showed his mouth closed through it.

## 9. Before rendering

- Read `film.md` top to bottom as a viewer would. Does each line follow from the last, and does the ending pay off
  the opening? If you need a title to explain a jump, the order is wrong. Read each join and the ending against the
  source around them, and restore any premise or qualifier the cut dropped. Read each join note: is every link
  one of meaning rather than of words, is every change of feeling caused, does the viewer know where they are, and
  does the sound carry or cut on purpose?
- Run `grade.py paper PROJECT`, then have a reviewer read `film.md` and `grade/paper.md` and judge the hook,
  structure, pacing and ending against the direction, citing the setup, one connection in the middle and the
  ending. A reviewer who did not write the script is best; when you review it yourself, record it as a self-review.
- Show the person the direction and the paper edit before the first render of anything longer than a short clip;
  they agree what the film is for, not only which lines it uses.

Done when three spines were compared and the choice recorded, `film.md` states its audience, takeaway and story,
each section has a note saying why that beat follows,
each join between passages has a note saying what links it and what the viewer feels across it, the ending completes or
deliberately reframes the opening, and the review above is recorded.
