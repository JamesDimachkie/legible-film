# Review and revisions

How people review a cut, how notes become fixes without breaking approved work, and how to use synthetic critics
without letting them steer the film. The person's notes are ground truth; critics find problems to verify.

Contents: [1. Human review](#1-human-review) · [2. Notes to fixes](#2-notes-to-fixes) ·
[3. Preserving approved work](#3-preserving-approved-work) · [4. Synthetic critics](#4-synthetic-critics) ·
[5. Verifying findings](#5-verifying-findings) · [6. Synthesis, competing builds and stopping](#6-synthesis-competing-builds-and-stopping) ·
[7. Who decides](#7-who-decides)

## 1. Human review

- Share each cut in a form the reviewer can play at once (an embedded video, a link to the file), with what changed
  and where, by timestamp. A bare file path is not a review.
- Ask for passes in this order:
  1. one unpaused, muted pass at the real viewing size (a phone in a feed, a laptop on a landing page);
  2. one pass with sound, on the devices where it will play;
  3. pauses on anything that caught their attention.

  A silent film needs the first and third; its review is complete without a listening pass.
- Reviewers who pause a screen recording at problem points are giving notes. Extract the frames at each pause, treat
  each pause as a note, then look across the film for other instances of the same problem.
- For a newcomer, show the cut once and ask what happened, what changed, what caused it and what the product did,
  before explaining anything.
- Record who watched and listened to which version, muted or with sound, on which device. A synthetic panel,
  selected stills and a cold human viewing are different evidence; keep them separate in the report.

## 2. Notes to fixes

- Record each note as `time → intended job → what the reviewer saw or heard → likely cause → change → decision`
  ([review-log template](../assets/templates/review-log.md)).
- Translate the note into a hypothesis about a cause: "too fast" can mean late readability, an early exit,
  competing motion or unfamiliar content; "too busy" can mean competing rhythms, long tails or a reading problem.
- Fix the cause where it lives (often a shared helper), then check every use of what you changed.
- When resolving an ambiguous note would materially change the approved design, show a still or a short motion
  proposal first.
- Make every change visible and audible before asking about it: nobody can approve a gain change they have not
  heard or a timing change they have not seen.
- Keep going between notes: verify fix passes with the QC battery and targeted frames rather than waiting for the
  reviewer to rediscover a regression.

## 3. Preserving approved work

- Before editing, name the approved properties that must not move and keep the approved source and export as the
  **baseline**.
- After the fix, prove the change ([qc](qc.md) §6): `compare_versions.py` shows differences only where intended; the
  cue list is byte-identical when only the picture changed; decoded audio hashes match when the sound should be
  unchanged.
- One note once became a shared-helper change plus a new closing move; the reviewer asked for the original back, and
  the pre-edit baseline restored it exactly.
- Static checks do not prove motion: an ending checked frame by frame and on dense sheets was still called "a little
  wacky" once it was watched at speed. Ask for a normal-speed look at every changed move.

## 4. Synthetic critics

Blind reviewers with distinct lenses look at the cut the way its audience will and report specific, buildable
changes. They find problems; they are not an audience, and their agreement proves nothing on its own.

**When:** a first wave after the person approves the story and shape, before polish; a verification wave on the cut
that addresses it, by the same reviewers, each given their own earlier report; another wave only for a substantially
new cut or when the person asks. A panel on every fix pass is wasted effort.

**Lenses** (choose the ones this film needs):

| Lens | What only this lens catches |
|---|---|
| Creative director | cohesion, one type scale, transitions that carry an idea, restraint, moments of delight; the weakest three seconds |
| Colourist and cinematographer | grade drift, lifted blacks, depth of field, motion blur on fast moves, banding |
| Editor and motion designer | landings against the clock, dead air, holds, transition timing, stalls and jumps |
| Technical viewer on a muted phone feed | claim credibility, qualifiers legible at feed size, what an expert would reply |
| Design-savvy non-technical viewer | story clarity, the emotional arc, jargon |
| Owner persona | pride, defensibility to experts, fairness to other authors, readiness to post (a persona, not the person) |

Spread lenses across model families where you can, and run them in small waves: a wave of reviewers shares the
account's rate limits and can stop together, so keep partial evidence and resume rather than restart.

**The critic brief** ([template](../assets/templates/critic-brief.md)) gives: the product, the audience and where it
plays; the file and the tools allowed; how to look at a film you cannot play (a frame every 0.5 s, every transition
at 20-30 frames a second, full resolution where grade, depth, type or alignment matter; "you cannot listen: where
sound matters, measure and say so"); what changed in this version and which findings were already resolved, so they
are not reported again; the fixed constraints they must not recommend breaking (approved claims, claim rules, the
music structure, decisions the person made); and the report format. A proposal to add explanatory copy must first
show why picture, sequence or duration cannot solve the problem.

**The report:** a one-sentence verdict; the story in their own words; a short ranked list of findings, each with
the frames, the evidence, the likely cause, an exact proposed fix and a severity; what must be protected; and the
checks not performed. No score: a number is not release acceptance.

**Severity:**

- **Blocking:** a wrong fact, an unreadable qualifier, a hard-limit breach, a broken delivery spec, or a defect on a
  key moment (the opening, the payoff, the ending, the logo).
- **Visible:** noticeable on a normal viewing.
- **Pause-only:** visible only when paused.

## 5. Verifying findings

A critic's finding is a hypothesis. Before acting on anything blocking or visible, seek the strongest reason it
might be wrong: intended behaviour, a stale cut, a measurement artifact, or a fix that damages protected work.

- **Check it yourself.** Open the delivered frames it names and the frames around them, the code or data behind them,
  and a normal-speed play when feel is the question. Record what you saw and measured, by frame; an impression is
  not a check.
- **Separate what a viewer meets from what a pause reveals.** Many motion blemishes vanish at speed; anything on the
  opening, the payoff, the ending or the logo does not. A wrong fact, an unreadable qualifier or a broken delivery spec
  stays serious however briefly it shows, and is never dismissed because it is easier to see paused.
- **Weigh the fix as well as the fault.** Confirm the cause sits where the finding says, and ask what the change would
  disturb: a join, a sync point, a reading window, an approved move. A real problem with a poor remedy keeps its place
  on the list with a better remedy.
- **Bring in an independent verifier** when findings conflict or a fix would materially change the film.
- Close each one as **confirmed**, **refuted** (and why) or **unresolved**, with its evidence and scope. Factual and
  release-critical items stay open until settled.

## 6. Synthesis, competing builds and stopping

Write a synthesis per round: confirmed findings ranked by viewer or claim impact, with the lenses that raised them;
where the lenses disagreed and how evidence settled it (a colourist once measured that a brighter grade would erase
the separation of cards from the desk, so it was dropped); what was built, by timestamp; what was not taken and why
(it conflicts with the person's direction, breaks a claim rule, or changes an approved shape: offer those to the
person as options); and anything outside the film that must agree with it.

When one passage stays weak after two rounds, stop polishing it. Make two or three **competing builds** of that
passage, each from a different starting point (the most direct image of what must be understood; one continuous
camera move; the music's structure), keeping its entry and exit and its claims fixed. Show them to the person in
motion and build the one they choose, taking the best idea from the others.

Stop when no blocking or visible finding remains open, every check has a result, and a named person has watched and
listened, or when the person calls it; either way, list what you would still improve.

## 7. Who decides

- The person's notes outrank every critic. What they have watched and approved stays unless they change it; a
  panel's preference is a question to put to them with a before and after, not a reason to redesign quietly.
- The owner or client approves claims and release; an owner persona's notes are weighed like client notes, but the
  real owner decides.
- Facts still need sources, whoever approves the look.
