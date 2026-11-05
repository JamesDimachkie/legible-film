# The paper edit (film.md)

`film.md` is the film written as text, in the order it plays. The agent writes it, a person reads it like a script
and edits it in any text editor, and every render compiles from it. Deleting words from a spoken line cuts them from
the video. `cut.py check` validates it against the map; `cut.py render` turns it into a version (references/project.md
section 4).

Contents: [1. A first look](#1-a-first-look) · [2. Front matter](#2-front-matter) · [3. Spoken lines](#3-spoken-lines) ·
[4. Picture lines](#4-picture-lines) · [5. Lines over a line: cutaways, titles, music](#5-lines-over-a-line) ·
[6. Titles, stills, music and pauses](#6-titles-stills-music-and-pauses) · [7. Modifiers](#7-modifiers) ·
[8. Timing rules](#8-timing-rules) · [9. Sections and notes](#9-sections-and-notes) · [10. Errors](#10-errors) ·
[11. Examples](#11-examples) · [12. Commands](#12-commands)

## 1. A first look

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

Read it top to bottom: music starts with the film; the interview line plays with "Honestly," cut out; b-roll of the
van; then the next interview line, with the dashboard recording covering the speaker while the speaker keeps talking
and a title appearing half a second in.

Every line starts with a marker:

| Marker | Line | Takes time in the film? |
|---|---|---|
| `>` | a spoken line: a source, a range, the words to keep | yes |
| `-` | a picture line, or `title`, `still`, `music`, `pause` | yes, except `title` and `music` |
| `~` (indented) | something over the line above: a cutaway, a title, music, a moving graphic | no |
| `##` | a section heading | no |
| anything else | a note to readers; never rendered | no |

Times are source times written `ss.ss`, `m:ss.ss` or `h:mm:ss.ss` (`12:03.40` is 12 minutes 3.4 seconds into that
source). A range is `start-end` with no spaces (`12:03.40-12:07.10`). Durations are plain seconds (`2.0`).

## 2. Front matter

The block between the two `---` lines at the top holds the film's settings, one `key: value` per line.

| Key | Example | Meaning |
|---|---|---|
| `title` | `Northwind field story` | the film's name (status line, Screening Room) |
| `audience` | `people scrolling a phone feed who have never heard of her` | who watches, where, and what they already know |
| `takeaway` | `They see that the fix took one person a weekend.` | what the viewer leaves with, one sentence starting "They" |
| `story` | `A field engineer tired of losing data builds the tool she needed, and the whole team switches.` | the spine in one sentence, with a turn; `check` prints it and the Screening Room shows all three above the script |
| `size` | `1080x1920` | output width x height in pixels; both even. Required. |
| `fps` | `30`, `25`, `29.97`, `30000/1001` | output frame rate. A decimal NTSC rate means the exact fraction (29.97 is 30000/1001). Required. |
| `target` | `45` or `0:45` | intended length in seconds; `check` reports the estimate against it |
| `captions` | `burn, srt, vtt` or `none` | `burn` draws captions into the picture on a translucent backing plate that fits the words; `srt` and `vtt` are the sidecars delivered with the film. `plate` states the plate explicitly; `highlight` marks the word being spoken. Caption files are always written into each version for review. |
| `music` | `-18dB, fade 1.5` | defaults for every `music` line: gain and fade length |
| `pad` | `0.2` | the most pause, in seconds, kept on each side of a cut inside a spoken line (default 0.2) |
| `max_pause` | `0.8` | shorten any pause inside a spoken line that is longer than this, cutting in its middle (default: keep pauses as spoken) |
| `fit` | `cover` or `contain` | default framing when a source's shape differs from `size` (default `cover`) |
| `crop` | `center`, `auto`, `left`, `right`, `top`, `bottom` or `x,y` | default crop for `cover` framing: a fixed centre (`0.62,0.5` keeps a speaker right of centre), or `auto` using sampled faces when available, otherwise motion and detail; a line's own `{crop ...}` overrides it; inspect the result |
| `background` | `black`, `#101418` | colour behind `fit contain`, pauses, title cards and audio-only lines |
| `bars` | `allow` | the delivery deliberately keeps black bars (letterbox or pillarbox), so the check does not flag them |
| `font` | `sans`, `mono`, or a font file path | title font: `sans` is the bundled Mona Sans, `mono` the bundled Geist Mono |

Values are single lines, not YAML: write them unquoted (a value may contain colons and quotation marks).
Unknown keys are an error (usually a typo), so a setting is never silently ignored. `check` warns when a film
longer than 20 s does not state its `audience`, `takeaway` and `story`
([finding-the-story](finding-the-story.md) §2).

## 3. Spoken lines

```markdown
> int_01 12:03.40-12:07.10 We tried everything. Nothing held up in the field.
```

A source alias, a range in that source, then the words to keep. The words are matched, in order, against the
transcript words (`map/int_01/words.json`) whose middle falls inside the range. Transcript words you leave out are
cut.

- **Cutting words.** Delete them, or strike them through so a reader still sees what went:
  `We tried ~~um, we tried~~ everything.` Both cut the same words. `...` and other marks without letters or digits are
  ignored, so `We tried ... everything` is a fine way to show a cut.
- **Matching** ignores case and punctuation (`Field.` matches `field`). Words must be the transcript's words: fixing a
  transcript typo in film.md makes the word unmatched; fix it in `words.json` instead, or keep the transcript's
  spelling. A repeated word ("I I think") matches the copy that gives the fewest cuts.
- **Order.** A line plays its source in order. To reorder, split it into two lines.
- **Where cuts fall.** Each cut goes in the pause between a kept word and a removed one. `cut.py` measures that pause
  in the source audio rather than trusting the transcript's word edges (transcribers are often 50 to 150 ms off):
  it cuts in a clear quiet stretch (0.12 s or longer) at or next to the transcript's pause, keeping a short handle
  after the kept word and at most `pad` seconds of pause on each side, to reduce the chance of cutting into a word or
  an audible breath. Quiet is not proof of silence between words: a stop consonant can be quiet for a moment. Word
  edges marked `estimated` get a wider search window. When words run together with no pause, the cut goes at the
  quietest moment within 30 ms of the transcript's word boundary and is listed as a tight cut for a person to listen
  to. When the line's audio cannot be measured (no sound, a decode failure, or sound that never drops below the
  speech), its cuts are placed from transcript times only and listed as unmeasured, with the reason. Deleting whole
  phrases or sentences gives clean cuts; deleting one word from the middle of a phrase usually gives a tight one.
  Two consecutive spoken lines that play the same source continuously do not create a cut at their shared boundary;
  a gap, removed word or different source still needs inspection.
- **Line edges.** The line starts and ends at the range you wrote when that point is quiet. When the range edge falls
  inside a word, the edge moves to the nearest quiet point outside the kept words. When it is clear of words but not
  quiet (a breath, or music and effects under the dialogue), it moves to a quiet point within 0.5 s if there is one,
  and otherwise stays where you wrote it and is listed as tight. So write each range with the pause you want before
  and after the line.
- **Jump cuts.** Cuts inside a line join two pieces of the same shot: a jump cut. `lines.json` lists them, and a
  cutaway (`~`) over a jump hides it.
- **Pinned caption break.** Add a separate line such as `- caption break before int_01-w000123`. The caption starting
  at that source word keeps the boundary when you move the spoken line. Find the ID in the source's `words.json`.
  If the word is cut or occurs more than once in the film, `cut.py check` reports the ambiguity. SRT, VTT, JSON and
  burned captions all use the same boundary.
- **Modifiers** go in braces at the end of the line: `> int_01 1:02-1:09 words to keep {crop auto, dissolve 0.25}`.
  Spoken lines take `fit`, `zoom`, `crop`, `dissolve`, `dip`, `fade`, `sound` (a gain such as `sound -3dB`), `tail`
  and `lead`; not speed, because speech plays at its recorded speed.
- **Carrying sound across a join.** A line's sound normally stops where its picture does. `tail N` lets the line's
  own sound run on N seconds under the next line, fading out (an L cut); `lead N` starts it N seconds before its
  picture, fading in under the end of the line before (a J cut). The extra sound is the source just after or before
  the range you wrote, so write the range as usual: the kept words, the captions and every later line stay exactly
  where they were. When the source has less sound there than you asked for (it starts or ends, or the neighbouring
  line plays the same stretch), the tail or lead is shortened to what there is and `check` says so. When the
  extra sound holds transcript words you did not keep, `check` names them: they will be heard but not captioned.

  ```markdown
  > int_01 4:10.20-4:15.80 It broke the moment it got wet. {tail 0.8}
  - broll_02 0:20.00-0:23.00 Workshop, rain on the window
  > int_02 1:02.00-1:06.40 So we built our own. {lead 0.5}
  ```

  The room under "got wet" carries 0.8 s into the workshop shot, and the second speaker's room comes up half a
  second before we see them.
- **Audio-only sources** (a voice-over `vo_01`) have no picture: cover the line with cutaways. Any part left
  uncovered shows the background colour and `check` warns about it.
- **Sound from a lined-up mic.** With recordings lined up by `map.py sync` ([footage](footage.md) §14), `{sound mic_01}`
  plays a mic instead of the line's own sound, and `{sound mic_01 -3dB}` sets its gain. The range and the words stay on
  the line's own source, so nothing is retyped when you change mics; the mic plays the same moment, at the saved offset.
  The line's cuts and edges are measured in the mic's sound, since that is what a viewer hears, and its join report,
  `tail`, `lead` and dissolve use the mic too. A line takes one mic: where two people talk at once, take the source that
  hears both, or register a mix of them as a source of its own.

  ```markdown
  > cam_01 4:10.20-4:15.80 It broke the moment it got wet. {sound mic_01}
  ```

## 4. Picture lines

```markdown
- broll_04 0:12.00-0:14.10 x1.5 fit contain dissolve 0.25 Crew unloading the van
```

A source alias, a range, optional modifiers, then a description for readers. The line lasts the range divided by its
speed. Picture lines are silent unless they say `sound` (the source's own sound, `sound -12dB` for a gain).

Modifiers come right after the range; the description starts at the first word that is not a modifier. If a
description begins with a modifier word, put `|` before it: `- broll_04 0:12-0:14 | zoom lens on the tripod`.
Modifiers may also go in braces at the end, as on spoken lines.

## 5. Lines over a line

An indented `~` line sits over the line above it (the nearest spoken, picture, still, pause or card line) and takes
no time of its own.

```markdown
> int_01 14:20.00-14:24.60 So we built the tool we needed, in six weeks.
  ~ screen_02 0:41.00-0:47.00 x1.5 Dashboard loads
  ~ broll_07 0:03.00-0:04.50 +4.0 The team at the whiteboard
  ~ title "Six weeks" 1.5 upper +2.0
```

- **Cutaways** (`~ ALIAS RANGE`): their picture covers the line above while its sound continues. The first starts
  with the line, each next one where the previous ended, or at `+N` seconds after the line's start. A cutaway that
  would run past the end of its line is trimmed to it. `sound` mixes the cutaway's own sound under the line.
- **The same moment from another camera** (`~ ALIAS sync [SECONDS] [+N] [modifiers] [description]`): the picture of a
  camera lined up by `map.py sync` ([footage](footage.md) §14), with no times to retype. It starts and ends like a
  cutaway: with the line, or where the one before it ended, or `+N` in, and it lasts the rest of the line or the seconds
  given. Every frame is the one the offset names, and a cut inside the line cuts this picture too, so it never slips
  against the sound; because it jumps with the line it does not hide a jump cut, and `check` still lists one. It takes
  `fit`, `zoom`, `crop`, a dissolve and `+N`, and runs at the line's speed. It takes no sound, since it would double the
  line's, and no speed of its own. A range is needed only for a shot of another moment, which is an ordinary cutaway.
  An audio-only line wholly under `~ ALIAS sync` gets no warning about uncovered picture.

  ```markdown
  > mic_01 14:20.00-14:24.60 So we built the tool we needed, in six weeks.
    ~ cam_01 sync Wide
    ~ cam_02 sync 1.5 +2.0 Ben reacts
  ```
- **Stills** (`~ still ALIAS SECONDS`) work the same way: they replace the picture, and an image's clear areas show
  the background colour.
- **Graphics over the picture** (`~ over ALIAS [SECONDS] [+N] [fade F]`): a video with transparency (a lower third or
  title from Cavalry, After Effects or another engine; PNG MOV, QuickTime Animation, ProRes 4444 or VP9 WebM) or a
  PNG with transparency (a logo), drawn over the line's picture, full frame; the line's picture shows where it is
  clear, and `check` refuses a file without transparency. Make it at the film's size, the graphic placed where it
  should sit on a clear background: one smaller or of another shape is scaled to the film's width, and `check` warns.
  Render a video at the film's frame rate too (`check` refuses another): its first frame lands on its start, and it
  lasts its own length or the seconds given, trimmed to the line, and animates itself; `fade` adds a dissolve at both
  ends. A PNG lasts the seconds given or the rest of the line, fading in and out over 0.25 s unless `fade` sets
  another.
- **Titles and music** (`~ title ...`, `~ music ...`) start with the line above, or `+N` seconds into it.
- **Pins, titles behind people and blurs** use a layer in the project's `spatial/` folder (a tracked surface or
  point from `track.py`, or a matte): `~ title "Live in 40 cities" 2.0 pin screen` maps the title onto a tracked
  screen, `~ still logo_01 3.0 pin screen` an image (drawn over the line, not a cutaway), `~ title "Six weeks" 2.0
  behind subject` keeps a person in front of the title, and `~ blur plate [SECONDS] [+N]` blurs a tracked region for
  the line. Each is drawn only while its layer's source is on screen, and a blur stops the render rather than miss a
  frame. `check` reports a missing, stale or wrong-source layer on its line. See [spatial](spatial.md).

## 6. Titles, stills, music and pauses

```markdown
- title "Field view" 2.0 lower
- title "Dana Ortiz" "Field engineer" 3.0 lower
- title "Part two" 2.0 center card
- still still_03 3.0 zoom 1.1 The founding photo
- still broll_02 0:12.40 2.0 Freeze on the handshake
- music music_01 0:00-0:45 -18dB fade 2.0
- pause 1.0
- pause 0.6 hold
```

- **`title "Text" ["Second line"] SECONDS [lower|center|upper]`**: text drawn over the picture that follows, starting
  where the line is written (default `lower`). A second quoted string is a smaller line under the first (a name
  and a role). `+N` delays it; `fade 0.4` sets its fade (default 0.25). With `card` it takes its own time on the
  background colour instead of covering picture. Titles use the bundled fonts (front matter `font`).
- **`still ALIAS SECONDS`**: an image source shown for that long; with a video source, `still ALIAS TIME SECONDS`
  freezes the frame at that source time. Takes `fit`, `zoom`, `crop` and joins.
- **`music ALIAS RANGE [GAIN] [fade F]`**: a music source playing from where the line is written (put it at the top of
  the film for a bed under everything). It stops at its range's end or the film's end, whichever comes first, fading
  in and out over `fade` seconds (default from front matter, else 1.0). `+N` delays it; `at m:ss` places it at an
  exact film time. Levels are rough; mastering happens at delivery.
- **`pause SECONDS`**: a beat of silence on the background colour; `pause SECONDS hold` freezes the last frame of the
  line before instead.

## 7. Modifiers

| Modifier | On | Meaning |
|---|---|---|
| `x1.5` (or `1.5x`) | picture, cutaway | speed; the line lasts range / speed |
| `fit contain` / `fit cover` | picture, spoken, still, cutaway | letterbox the whole frame, or fill the frame by cropping |
| `zoom 1.2` | picture, spoken, still, cutaway | crop in by this factor (cover framing) |
| `crop auto` | picture, spoken, still, cutaway | follow the largest sampled frontal face when OpenCV is installed, otherwise motion and detail; review the version's crop notes |
| `crop center`, `crop left`, `crop right`, `crop top`, `crop bottom`, `crop 0.3,0.5` | same | a fixed crop centre (fractions of the source frame for `x,y`) |
| `dissolve 0.25` | any line that takes time, cutaway | dissolve into this line over 0.25 s (into and out of a cutaway); between two lines it also crossfades their sound (below) |
| `tail 0.8` | spoken, picture with `sound` | the line's own sound runs on 0.8 s under the next line, fading out (an L cut) |
| `lead 0.5` | spoken, picture with `sound` | the line's sound starts 0.5 s before its picture, fading in under the line before (a J cut) |
| `dip 0.5` | same | dip to the background colour and back over 0.5 s |
| `fade in 1.0` | the first line | fade picture and sound up from black at the film's start |
| `fade out 1.5` | the last line | fade picture and sound down to black at the film's end |
| `sound` / `sound -12dB` | picture, cutaway, spoken | use the source's own sound (spoken lines always do; the gain adjusts them) |
| `sound mic_01` / `sound mic_01 -3dB` | spoken, picture at normal speed | play this lined-up source instead, at the same moment (section 3) |
| `sync` | `~` line, after its alias | show this lined-up camera at the same moment, with no range (section 5) |
| `+2.0` | `~` lines, title, music | start this many seconds later |
| `at 0:12.5` | title, music | start at this film time |
| `-18dB` | music | gain |
| `fade 2.0` | music, title, over | fade length at both ends |
| `card` | title | take its own time on the background colour |
| `pin screen` / `pin screen follow` | title, `~ still` image | map it onto the surface tracked in `spatial/screen.json` every frame, or move it with the track ([spatial](spatial.md)) |
| `behind subject` | title, `~ still` image | draw it, then the matte `spatial/subject.json`'s foreground over it |
| `hold` | pause | freeze the previous frame instead of the background |

**Sound at a join.** `tail` and `lead` take the extra sound from the source around the range, never from beyond the
source's own start or end, and never replay what the neighbouring line plays from the same source. `dissolve N`
between two lines crossfades their sound over N seconds with an equal-power curve, so a picture dissolve no longer
lands on a hard sound cut. The sound crossfade sits as close to the picture dissolve as it can while both lines'
kept words stay at full level (it may start a few hundredths of a second before or after the picture); when the
pause between the words is shorter than N it is shortened, and with under 0.1 s of room the sound still cuts, with a
warning. A join takes either a dissolve or a tail and lead, not both. A `dip` does not change the sound. `lines.json`
records what each line carries (`sound_carry`: `tail`, `lead`, or the crossfade's film times).

```markdown
> int_01 1:02.00-1:06.50 And that was the last of the old way.
> int_03 0:14.20-0:19.00 The new building opened in May. {dissolve 0.6}
```

For `crop auto`, install the optional detector with `setup.py --install faces`. It samples a Haar frontal-face
cascade, which can miss profiles, small or occluded faces and can mistake other objects for faces. It does not
identify a person or the speaker. Without a detection it falls back to motion and detail. With faces in at least two
samples and at least half of all samples, the assembler attempts to match face size across automatic crops of a
source, within its crop and 2x zoom limits; a line's explicit `zoom` wins. `fit contain` keeps the whole picture. The
version's notes name each clip's method and flag sampled faces that cannot fit or leave the smoothed crop, with times
to review. Sampling
does not guarantee the framing between samples:
watch the rendered film, and cut between people, adjust the crop or letterbox where needed.

Cover is the default, and it fills the frame by discarding whatever does not fit: a vertical clip in a landscape film
keeps about a third of its height. When cover discards a third or more of a source's height or width, `check` and
`render` warn, naming the first such line and these two options, and say so when OpenCV finds a face outside what is
kept in a few sampled frames. The framing itself does not change, and a line that already says `crop auto` or
`fit contain` gets no warning.

## 8. Timing rules

- Lines that take time play one after another, in the order written. A spoken line lasts as long as its kept
  pieces; a picture line its range divided by speed; a still, card or pause its seconds.
- Joins never change timing. `dissolve 0.25` on a line starts the dissolve where the line starts and lets the outgoing
  picture run 0.25 s longer under it, so sound stays in sync. The outgoing source needs that much picture after its
  range; when it does not have it, the join shortens and `check` says so. `tail`, `lead` and a dissolve's sound
  crossfade add sound around a join without moving any line or word.

### The join report

Every join between two passages (a change of source, or a gap in one source, including a cut inside a spoken line)
is measured in the source sound at its out and in points, so `check` reports it before anything renders and
`render` records it in `lines.json` (`joins`). For each side a join lists the level over the 0.4 s next to the join,
the level right at it (0.15 s), and the **background**: the median level of the 50 ms frames within 2 s of the join
where nobody speaks (speech is masked with the map's voice activity in `map/ALIAS/audio.json`, or else the
transcript words), with its spectral centroid. The report measures the background's low end at 20-100 Hz, both in
those frames within 2 s and in speech-free frames within 0.4 s of the join. This approximate band includes the
sub-bass booms below 90 Hz; 50 ms frames resolve it in 20 Hz steps, so it is not a sharp frequency cutoff. Across
the join it gives the level, background and low-end jumps, the change of tone (how far the background's octave-band
shape moves, in dB, and the centroid ratio), what bridges it (`tail`, `lead`, a dissolve's crossfade, a music bed,
or a cutaway's sound playing through it), and the lengths of the shots on each side. Low-end values are omitted when
too few speech-free frames can be measured; they are not zero.

`check` warns, with the time and a suggestion, when an unbridged join's background or level changes by 6 dB or more,
or its tone changes by 10 dB or more (a different sound world). It also warns when the low end changes by at least
6 dB in either window, or by at least 3.5 dB in the 0.4 s window when both sides are bass-dominant (their low-end
levels are within 4 dB of their full-background levels in that window). At least one side's low end must reach
-35 dBFS.

For a low-end change of 6 dB or more, a tail or lead shorter than 0.5 s does not suppress the low-end warning; the
report still lists it as a bridge for the other sound checks. A dissolve or other sound carried across the join
continues to count as a bridge. A 0.5 s tail or lead spans more than the 0.4 s near-join measurement, but its
duration alone does not prove that it carries the same bass. In JSON, `bridged` lists the original sound bridges,
`low_bridged` lists the bridges that count for a detected low-end change, and `abrupt_change` names the reasons for
the warning. These are review prompts, not audibility thresholds:

```
film.md:51: warning: the sound changes abruptly at 0:32.26 (+14 dB in the background)
  suggestion: carry it across with tail or lead, dissolve it, lower the louder side with {sound -6dB}, put a bed under, or cut on a stronger beat
```

A join is judged only when both sides sound at it and both have a background to compare. A side quieter than
-45 dBFS right at the join is a pause, and a cut into or out of a pause is not called abrupt. A side with almost no
sound between words (a tight speech edit) has no background, and its plain level mostly measures speech against a
pause. The report lists both as not judged, with the reason. The low-end thresholds were tuned on one feature-film
trailer. None of the 15 joins in three interview cuts warned, but none could be judged because of silence or too
little speech-free background. These cases cannot establish how often a warning will agree with a listener elsewhere.
The report measures source sound, not the mix: listen to the rendered version.

### Picture pace

`check` also lists every picture change (each edit, and the source's own shot changes inside a line when the map
has `shots.json`) and warns when three or more fall within 3 seconds, for example `4 picture changes in 2.8 s
(0:35.81 to 0:39.86; shots of 1.4, 1.4, 1.2 s)`. Put deliberate fast cutting in a section whose name contains
`montage` (`## Battle montage`); changes inside such a section are not counted.
A freeze is one picture event with the shot it holds: `still ALIAS TIME` or `pause N hold` followed by the same
source running on from the frozen frame counts the cut into the freeze only.
- A `- title` or `- music` line starts where it is written: at the start of the next line that takes time. A title
  or music line written after the last line that takes time has nothing to play over and is an error.
- Lines over a line (`~`) are timed from the start of the line above.

## 9. Sections and notes

`## Name` starts a section; the lines under it belong to it until the next heading (`lines.json` records it). A
section whose name contains `montage` marks deliberate fast cutting (section 8, picture pace). A single
`#` heading is the document's own title and changes nothing. Any line that is not front matter, a heading, or a line
starting with `>`, `-` (followed by a known alias or keyword), or `~` is a note to readers: write plans, questions and
reasons freely. A `-` bullet whose first word is not an alias or keyword is a note too, so ordinary bullet lists are
safe. Text inside `<!-- -->` comments and fenced code blocks is ignored.

## 10. Errors

`cut.py check` reports each problem with its line number and a suggestion, for example:

```
film.md:7: error: "feild" is not in int_01's transcript between 12:03.40 and 12:07.10
  suggestion: the transcript has "field" at 12:06.92; use the transcript's words
film.md:9: error: unknown source alias broll_14
  suggestion: known aliases near it: broll_04, broll_01
film.md:12: error: range ends at 31:10.00 but int_02 lasts 30:58.21
  suggestion: end the range by 30:58.21
film.md:14: error: the range ends at 0:19.50 but src_01's picture ends at 0:18.71 (decoded; the file's header says 0:23.25)
  suggestion: end the range by 0:18.71, or hold its last frame with a pause hold line
film.md:15: warning: cutaway runs 1.20 s past its line; it will be trimmed
film.md:18: error: cam_02 and cam_01 are not lined up: its line-up is a look: only 2 of 9 test windows agree
  suggestion: run map.py sync PROJECT and read what it says about cam_02; a look stays a look until someone listens, then map.py sync PROJECT --set ALIAS=SECONDS --note TEXT
film.md:21: error: cam_02 has no picture for this moment (0:03.10 of cam_01): on cam_01's clock it runs 0:12.30-41:07.00
  suggestion: start it later with +N, end it sooner with SECONDS, or show another camera
```

Errors stop a render: bad grammar, unknown aliases, ranges outside a source, unmatched or out-of-order words, a picture
line on a source with no picture, a line-up that is missing, stale or a look under `~ ALIAS sync` or `{sound ALIAS}`, a
lined-up source that does not cover the moment, and any line that would last longer than four times `target` (three
hours without one), which is almost always a mistyped range or speed. A blocked render exits 2, since nothing was made
to look at (`check` exits 1 for the same errors; `render --json` says `"status": "blocked"`). "Outside a source" means
where it really ends: a source's duration can be its header's claim, so a range is checked against the map's decoded end
of picture and sound, and a picture range against the picture's end even when the sound goes on. A map made before this
has the header of the video stream to go on, and a render that finds less picture than that refuses the line; `map.py
run PROJECT --alias ALIAS --rebuild` measures it. The renderer never fills a range with a frozen frame: a hold is a line
you write (`pause N hold`, `still ALIAS TIME N`). Warnings describe something that will render but deserves a look: a
duration far from `target`, a tight cut, a trimmed cutaway, uncovered audio-only picture, sound that ends before its
picture does, an abrupt sound change at a join, busy cutting, a flash frame (under half a second of a picture: a
source's shot change just inside a range, or a moment of a line's own picture left between two cutaways), an interview
line said more than 30 s before the line it follows, burned captions on a landscape frame whose audience is a phone
feed, a film whose first word may continue a sentence, a question or exclamation answered with under 0.5 s where the
source took 1 s or more, and, in a film over 20 s, a join between passages with no note between its lines saying what
links the two sides ([finding-the-story](finding-the-story.md) §4).

## 11. Examples

**Interview cut-down** (a vertical social cut from a 30-minute interview):

```markdown
---
title: Why we rebuilt it
size: 1080x1920
fps: 29.97
target: 40
captions: burn, srt, plate
crop: auto
---
## Hook
> int_01 4:10.20-4:15.80 Every tool we tried ~~kind of~~ broke the moment it got wet.
## Turn
> int_01 9:02.00-9:08.40 So we stopped buying and ~~we, uh,~~ started building.
  ~ broll_02 0:20.00-0:23.00 Workshop, hands on the soldering iron
> int_01 17:44.10-17:50.00 Six weeks later it was on every truck. {dissolve 0.2}
- title "Northwind Field Tools" 2.5 center
- broll_05 1:02.00-1:05.00 Truck pulls out at dawn {fade out 1.0}
```

**Tutorial** (voice-over over a screen recording, sped up where nothing happens):

```markdown
---
title: Export a report in three steps
size: 1920x1080
fps: 30
captions: srt, vtt
---
## Step 1
> vo_01 0:00.50-0:06.20 First, open the reports tab and pick a date range.
  ~ screen_01 0:02.00-0:08.00 Reports tab, date picker
  ~ title "1  Choose dates" 2.0 upper
## Step 2
> vo_01 0:07.00-0:12.40 Then choose the columns you need.
  ~ screen_01 0:15.00-0:31.20 x3 Column picker (sped up)
## Step 3
> vo_01 0:13.10-0:17.00 And press export.
  ~ screen_01 0:40.00-0:44.00 zoom 1.4 crop 0.8,0.2 Export button
- pause 0.5 hold
```

**Montage** (picture to music, no dialogue):

```markdown
---
title: Season recap
size: 1080x1080
fps: 25
captions: none
music: -14dB, fade 2.0
---
- music music_01 0:00-0:30
- broll_01 0:04.00-0:06.00 {fade in 0.5}
- broll_03 1:10.00-1:12.40 x0.5 Slow motion splash
- broll_02 0:30.00-0:32.00 dissolve 0.3
- still still_01 2.0 zoom 1.1 Team photo
- title "See you next season" 2.0 center card {fade out 1.0}
```

## 12. Commands

```
python cut.py check PROJECT [--json]          validate film.md against map/ without rendering
python cut.py render PROJECT [--label TEXT] [--resolves n1,n2] [--final] [--every-frame]
python cut.py diff PROJECT vA vB [--json]     what changed between two versions
python cut.py draft PROJECT --select 'int_01:"we tried everything"' ... [--force]
python cut.py tighten PROJECT ALIAS [--pause 0.35] [--fillers named|LIST] [--punch-in 1.1] [--music-bed]
    [--reel-limit N] [--out FILE] [--force]
```

`check` lists errors and warnings with line numbers. Tight and unmeasured cuts name the line's start, end or an
interior cut and nearby kept words when known. It also lists each spoken line's kept and cut words, the estimated
duration against `target`, and the join report: one row per join between lines (and any abrupt cut inside a line),
for example `0:32.26 line 50 > 51: -26.3 > -13.9 dB (+12.4), background -30.1 > -16.1 (+14.0), tone 7.8 dB,
shots 0.9 | 1.8 s, ABRUPT (background and level)`. `check --json` adds `joins`, `picture_changes` and
`busy_cutting` and writes UTF-8 when redirected. A crop position takes two source-frame fractions, for example
`{crop 0.58,0.5}`; a single number is not a complete position. `render` writes the next `cuts/vNNN/` (edit.json, lines.json, captions, preview.mp4,
manifest.json) and points `cuts/current` at it. `draft` writes a first film.md from phrases found in the transcripts.
`tighten` makes a paper edit for one source, shortens measured quiet with `max_pause` and, where needed, line splits,
and writes a removal list and a labelled BEFORE/AFTER reel, with LISTEN prompts for untranscribed sound. Reel edges
fade over 30 ms with silent gaps; `--reel-limit N` limits events, cuts first, and reports any omitted events. Fillers
are opt-in and remain visible struck through. Untranscribed
energetic sound is a listening prompt, not a filler detection; quiet speech and inaccurate word edges can be missed.
The `Tighten (declared jump cuts)` section identifies intentional fast cuts in the check without suppressing the
timing data. `--music-bed` declares a music or ambience bed and leaves pauses and fillers intact; it does not detect
the bed automatically. When measured quiet handles permit, this section also gives its cuts a sound crossfade up to 0.1 seconds;
otherwise the report identifies the short edge fades. Restore a struck filler by unstriking it. To restore a line split, merge its ranges and adjust
`max_pause` if needed; to restore one in-line pause, split at a shared continuous range boundary. See
[Tighten a talking head](recipes.md#tighten-a-talking-head).

What a render adds that film.md does not say:

- **Captions** are built from the kept words by `captions.py` (its reading-speed, line-length and duration rules). A
  caption never runs across a change of source, a change of labelled speaker (an unlabelled word between two speakers
  counts as neither) or a pause of 0.6 s or more. Labels are drafts, so a wrong one moves a break until a person
  corrects it. Every caption word carries its transcript word ID and its speaker. Lines hold up to 42 characters in a
  landscape or square frame and fewer in a tall one (26 at 9:16, 37 at 4:5), so burned text keeps its size.
- **Previews** are short side 540 (never larger than the film). Sources much larger than that are previewed from a
  smaller copy cached in `cuts/.cache/`; `--final` always reads the originals and keeps the sound stems.
- **Sound** in the preview is the dialogue, natural sound and music mixed with a light limiter; levels are for
  review, and mastering happens at delivery.
- **Several recordings.** `lines.json` marks a `~ ALIAS sync` stretch with `sync` and its source `range`, and a spoken
  line that takes another source's sound with `sound_source` and each run's `sound_in` and `sound_out`. `manifest.json`
  records the offsets it used (`lineup`), so a later line-up cannot change what a version says it was cut from.
