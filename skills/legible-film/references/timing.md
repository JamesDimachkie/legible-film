# Timing: one clock for picture and sound

How each passage keeps time, how picture and sound share events, where a sound sits against a picture event, and
how long text needs on screen. Use it in step 3 and whenever something "feels off" without an obvious cause.

Contents: [1. Choose the clock](#1-choose-the-clock-for-each-passage) · [2. The cue list is a contract](#2-the-cue-list-is-a-contract) ·
[3. Where a sound sits](#3-where-a-sound-sits-against-a-picture-event) · [4. Tolerances](#4-tolerances) ·
[5. Frame arithmetic](#5-frame-arithmetic) · [6. Reading windows](#6-reading-windows) ·
[7. Reading and action](#7-reading-and-action) · [8. Inserting holds](#8-inserting-holds) ·
[9. When music is the clock](#9-when-music-is-the-clock)

## 1. Choose the clock for each passage

Each passage follows one clock, and choosing it is a creative decision:

- **Action:** a chain of visible causes sets the timing (a silent demo, a product action).
- **Speech:** narration or dialogue sets it; picture events land on words.
- **Music:** a beat grid sets it; changes land on bars, beats or the music's own events.
- **Deliberate silence:** nothing new arrives, so a result or a sentence can be read.

A film can change clock between passages. An intended offset (a sound that anticipates, a landing just after the
beat) is valid when it is intended; drift is not.

## 2. The cue list is a contract

- Keep every shared event in one timing source (a module, a JSON file, a table the build reads): an ID, a time on
  the film clock, and what happens. Specs, the cue list and every builder use the same absolute times.
- Compute sync points from the animation itself: the contact frame, the frame of peak velocity, the frame a settle
  becomes visually complete, the frame a line becomes readable. Never type them by hand; the picture moves under a
  hand-typed number as soon as anything is retimed.
- Scene-local clocks are fine. Record each scene's offset from the film clock in the same source.
- After any picture-only change, re-export the cue list and compare it byte for byte with the list the mix used.
  Reuse the mix only when they are identical.
- A counter, a check mark or a total updates in the same frame as the event that causes it; a beat of delay reads
  as lag.
- An animation has not moved at all on the frame it starts, so its first visible change comes a frame later.
  Cue the first visible change, not the tween's start.
- A transition reads on its fastest frame. When a transition must land on a beat, solve its start from the frame
  you want its peak on.

## 3. Where a sound sits against a picture event

The picture event and the take's own sync point are different instants. Place each take at
`picture event time − the take's sync offset`, with the offset measured inside the take, and check the decoded
audio.

| Picture event | The take's sync point | Notes |
|---|---|---|
| A contact or landing | the take's measured onset, on the contact frame | The move must arrive with velocity; a soft ease into rest has no contact to hit. |
| A whip or fast camera move | the take's energy apex, on the picture's peak velocity | Cut a whip on its fastest frame; give "air" to real scene transitions, not to every move. |
| A reverse swell into an event | the take's end, on the event | |
| A headline landing | one soft cue, or none | One documented film sounded every headline with a single soft tick and left exits and settles silent: one film's taste filter, not a rule. |
| A text sequence | one quiet cue per meaningful phrase, or silence | Dense typing gets a few word-level accents, not a sound per key. |
| Events on the same frame | decide whether they are one gesture | A mixer that merges them makes one fuller sound; two separate hits a frame or two apart smear. |
| Exits, settles, scrolls, progress bars | usually nothing | The music or the next event carries them. |

Ease-out curves look landed long before they end: a quartic ease-out has covered 90% of its distance by 44% of
its duration, and an exponential one by 33%. A sound cued on the tween's last frame arrives after the eye has
already seen the landing. Cue the frame where the move becomes visually complete.

Consistency carries meaning: give each sound family one meaning (selection, completion, error) and keep it, and
when one kind of action gets a sound, give every repeat of it the same sound.

In `cues.json`, each event's `sync` names the take's own sync point: `attack`, `apex` or `end`. Its `role` names the
sound to play from the palette, so `mix_cues.py` can place the take and `cue_onsets.py` can check it
([sound](sound.md) §6).

## 4. Tolerances

- ITU-R BT.1359-1 puts the average **detectability** thresholds at about **+45 ms** (sound early) and **−125 ms**
  (sound late), and acceptability at +90 ms and −185 ms. Viewers notice early sound sooner than late sound. These
  are broadcast transport limits, not creative targets.
- EBU R37 asks each production stage to stay within **5 ms early to 15 ms late**, and an emission chain within
  40 ms early to 60 ms late. These are transport limits: set the film's own sync tolerance separately. A frame
  is 17 ms at 60 fps and 42 ms at 24 fps, so a one-frame tolerance does not by itself meet the per-stage figures.
- There is no single sync tolerance: a run of repeated hits exposes an offset that an isolated event hides.
- Measure the delivered offsets with `cue_onsets.py` (sounds against the cue list) and `sync_check.py` (delivered
  audio against the approved mix). In a full mix with music, compare the share of cues answered with chance
  (`--chance`): busy music lands near any cue by luck. Measurements locate problems; whether a hit feels right is
  decided by listening.

## 5. Frame arithmetic

Pair tempo and frame rate so each beat spans an integer count of frames; otherwise cue frames round differently from
beat to beat and picture and music drift by up to a frame.

| BPM | Frames per beat at 24 fps | at 25 fps | at 30 fps | at 60 fps |
|---|---|---|---|---|
| 75 | 19.2 | 20 | 24 | 48 |
| 90 | 16 | 16.67 | 20 | 40 |
| 100 | 14.4 | 15 | 18 | 36 |
| 120 | 12 | 12.5 | 15 | 30 |
| 125 | 11.52 | 12 | 14.4 | 28.8 |
| 150 | 9.6 | 10 | 12 | 24 |

`frames_per_beat = 60 × fps / BPM`. With supplied music at an awkward tempo, keep the frame rate, place each cue on
the frame nearest the measured beat time, and note why; never retime the music to suit the grid. A helper such as
`at(bar, beat, sixteenth)` that returns a whole frame keeps every cue on the grid; a cue deliberately off it gets a
written reason beside it.

Two more pieces of arithmetic: a dissolve or crossfade of `d` seconds between clips shortens the timeline by `d`
and shifts every later cue by `d` (FFmpeg's `xfade` takes `offset = first clip length − d`); and converting 24 fps
material to 60 fps repeats frames in an uneven 2-3 cadence that reads as judder in slow pans.

## 6. Reading windows

For every text a viewer must read (copy, labels, UI strings, captions, footnotes), record four times on the film
clock:

- `in`: it starts to appear;
- `readStart`: every required word is legible at viewing size, after blur, clipping, masks, occlusion and motion;
- `readEnd`: any required part stops being legible, including when its container starts to leave;
- `out`: it is gone.

The **usable reading interval** is `readEnd − readStart`, and it must fit the reading task. An animation's nominal
duration is not reading time. A payoff must be fully readable before its scene leaves: in one documented case, the
last line of a card finished appearing 0.2 s after the card began to leave, so the scene's point was never readable,
and a two-frames-a-second overview did not show it. Compare each element's "fully in" time with its container's
"out" time.

How long is enough depends on the reader, the language, the complexity and what else moves; no average sets it.
Reference points, with what they measure:

- Netflix's English timed-text guide allows up to **20 characters per second** for adult programmes and **17** for
  children's, 42 characters per line, two lines, and events from about 0.8 s (20 frames) to 7 s. These are limits
  for viewers reading while also watching picture.
- Brysbaert's 2019 meta-analysis (190 studies) puts adult silent reading of English non-fiction at about **238
  words a minute** (typical range 175-300). That is continuous reading on a page, not text in motion.

Check every essential text at the size it will be seen. A 1920-wide frame shown 384 px wide in a phone feed is at
one-fifth scale: 84 px type reads as about 17 px and 20 px as about 4 px. Decide which rendition each text must be
readable in (the feed, or the opened player) and recompose rather than shrink. To measure the usable interval, look
at every frame around the entrance and around the exit at viewing size (`frame_sheet.py --frames A-B --width 384`),
note the first frame where every required word is legible and the first frame where one is not, and take the
difference. A sheet sampled at intervals cannot show those boundaries, and readability itself still needs a person
looking at that size. You already know the copy and a first-time viewer does not, so judge reading load from the
frames, never from memory.

## 7. Reading and action

Motion and reading compete for the same eyes. Patterns that let the picture carry part of a sentence:

| Pattern | Useful when | Check |
|---|---|---|
| Append phrases on a held line | earlier words stay necessary to understand the payoff | reserve the final width or move the line gently; keep qualifiers and word spacing |
| Replace one phrase with the next | the viewer should focus on one changing idea | clear the old phrase before the new one takes its place |
| Hold a stem, change one slot | comparing states or supported alternatives | keep the stem readable and hold each alternative long enough |
| Setup, product action, payoff | the action conveys what explanatory copy would repeat | the action reads muted, and the payoff does not overclaim |

- Use whole sentences when they read better. Keep each claim with its conditions, each number with its unit, and
  each proper name in one piece; required disclosures stay whole.
- Alternate reading with important action when simultaneous motion would make either one easy to miss.
- Where the viewer must read a number or a sentence, try the hold with no new sound events.
- Do not dwell on what the audience already knows: one documented demo held 2.8 s on a result most viewers
  understood at a glance; 0.6 s served it.
- When text reads too fast but the motion feels right, add reading holds at settled states rather than slowing every
  move: one launch film gained twelve holds (7.8 s in all) after the note "it moves a little fast for how much text
  is on screen".

## 8. Inserting holds

- Represent each hold as `(original time, added duration)`. An event's new time is its original time plus the
  durations of all earlier holds.
- An animation or sound that spans a hold point needs its own decision: shifting only the events that start later
  does not lengthen an action already in progress.
- Warp the cue list with the same holds, re-export it, and re-run `cue_onsets.py` on the new mix.
- Check the result at viewing size and in motion. A measured interval is not comprehension.

## 9. When music is the clock

- Decide early which events coincide with the music (section changes, the main reveal, contacts) and which float.
  In a music-led passage, a landing meant for a downbeat that arrives 0.2-0.5 s after it reads as late; an
  intended off-beat or action-led landing is not late.
- Pick the structure early: tempo, bar length, the drop, any re-drop, the climax, the final hit. One beat module
  that lists the events, exported as the sound cue list, keeps picture and music on one clock.
- Conform a chosen track to the film at bar lines with short crossfades, and judge it against the real cut.
- Find the track's beat phase from its kick attacks, not from bass energy: in one film a bass-energy estimate put
  the conform 68 ms early, and the listener heard it ("off on some beats just by a hair"). Measure swing when the
  groove has one, and place off-beat events with the same swing.
- Measure a track before building on it: `beat_grid.py` reports its tempo, its phase from attacks, its downbeats and
  drops, how far beats sit from the grid (residual) and how far the tempo wanders (drift). Fit only the stretch the
  film uses (`--window`), give the tempo you asked for (`--bpm`) so it cannot lock to half or double, and let
  `--drop-at-beat N` compute the offset into the track that lands the drop on film beat N.
- State the film's own timing contract for the events meant to coincide (one music-led film held its hits within
  about 5 ms of the eighth-note grid), and check the delivered file against it.
- Build loops in whole bars, so music and picture come round together.
- Generated music usually ignores requested sections; see [sound](sound.md).
