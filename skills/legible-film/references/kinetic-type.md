# Kinetic type: films of big words on a beat

A register for films made of large words, camera moves and hits on a beat grid: launch teasers, trailers, hype
films, a manifesto of a few claims. It is a choice made in step 2 like any concept. The change sentence, the facts
file and every hard limit still apply, and words on a beat are not by themselves a concept. Numbers here describe
films that were measured; a film adopts one only as its own declared contract.

Contents: [1. When it fits](#1-when-it-fits) · [2. Brief to beat sheet](#2-from-brief-to-beat-sheet) ·
[3. Devices](#3-devices) · [4. Pace you can measure](#4-pace-you-can-measure) · [5. Motion between hits](#5-motion-between-hits) ·
[6. Type and colour](#6-type-and-colour) · [7. Joins in motion](#7-joins-in-motion) ·
[8. Safety in this register](#8-safety-in-this-register) · [9. Sound](#9-sound) · [10. Render](#10-render) ·
[11. Checks](#11-checks-particular-to-this-register) · [12. With the kit](#12-with-the-kit)

## 1. When it fits

- **Fits:** an announcement whose job is energy and recall, 15-60 s long, for a feed where the words carry the claim
  with the sound off.
- **Fits a passage:** a mixed film can open or close in this register and change clock for the demonstration
  ([timing](timing.md) §1).
- **Does not fit:** showing how something works step by step, interface evidence the viewer must inspect, long text,
  disclosures, a product whose promise is calm, or an audience at particular risk from flashing or motion.

The register answers what the viewer should feel (momentum, confidence, appetite). The story still needs its change,
evidence and boundary ([story-and-score](story-and-score.md) §2).

## 2. From brief to beat sheet

1. **Length and tempo.** Choose them together, since a beat lasts 60 / BPM seconds: 0.35 s at 172 BPM, 0.4 s at
   150, 0.5 s at 120. Shorter films carry faster tempos. As starting drafts, teasers of 15-25 s tend to sit around
   150-175 BPM, launch films run 40-55 s, and calmer brand films of 30-45 s settle nearer 120-128 BPM. When the music will be generated or written to a tempo, choose one with a whole number of frames per
   beat ([timing](timing.md) §5): at 60 fps, 150 BPM gives 24 frames and 120 gives 30, while 172 gives 20.93.
2. **Words first.** Write the film as a short spoken script, then cut it into one or two words per beat. A phrase of
   four to eight words fills four to nine beats.
3. **Copy for this register:**
   - one claim per phrase, from the facts file;
   - concrete nouns and verbs over adjectives ("it maps every photo" over "amazing results");
   - a change of device every three or four phrases (a denial, a number, the name, a joke, a reveal), so the rhythm
     does not flatten;
   - end on the name, then hold: only the end card stays.
4. **The drop is the turn.** The music's biggest change carries the film's turn ([story-and-score](story-and-score.md)
   §5). Put the biggest visual change on it (the first picture, the first ground in the accent colour, the push into
   the product) and keep one dimension of change unused until then. Measure where the track drops with
   `tempo_map.py`, then choose the offset into the track that lands it on the planned beat:
   `offset = drop time in the track − planned beat × 60 / BPM`. `tempo_map.py --drop-at-beat N` computes it and snaps
   it to a measured downbeat.
5. **The beat sheet is the score** ([score.csv](../assets/templates/score.csv)) written in beats: for each block, its
   start and end beat, the words, the device, the ground, the hit on its first beat, the sound and the fact behind
   any claim. Place the drop, the stops and the end card first and fill around them.

## 3. Devices

| Device | It says | How it moves | Truth check |
|---|---|---|---|
| Statement | one idea a beat | words land or snap on the beat, one or two at a time | a factual word needs its facts entry |
| Denial ("NO X.") | the old cost is gone | a simple mock of the old way, then it breaks | the product really removes X; the mock is not a real competitor's interface |
| Number | a measured scale | a large figure lands with its unit and label: snapped, landed from scale, or digit by digit | the value is from the facts file, with its qualifier beside it; no roll or count through values nobody measured ([claims-and-rights](claims-and-rights.md) §2) |
| Name | who and what | the name out of depth, a light sweep | exact spelling and casing |
| Input to output | how it is used | a command typed or a request written, then a push into the key that becomes the drop | a real command and output, or labelled illustrative ([product-demos](product-demos.md) §5) |
| Proof in pictures | it exists | a capture or screenshot punched in on words | recorded, or a labelled reconstruction |
| Thread | what feeds what | nodes linked by the thread, the camera riding it | links only what the facts link |
| Recap | everything you saw | the film so far, replayed | replay it slowly or inside a small window (§8) |
| End card | where to get it | logo, name and one practical line, held | the practical line is current on release day |

A **running caption** (the whole sentence in small type, its current word highlighted, while the display words cut)
keeps the line readable for a viewer who missed a word, and it exports as the caption file from the same source.

## 4. Pace you can measure

A film can land every cut on the rhythm of a fast reference and still read as a slideshow, because the feel of this
register comes from what moves between the hits. `motion_scan.py` measures it:

- **still share:** frames where under 1.5% of the picture changes by more than 24 grey levels from the frame before
  (at 320 px wide);
- **still stretches** and the longest one, each with the beat it starts on when you give the tempo;
- **change events per 10 s:** frames where half the picture or more is replaced at once, with a whip's blurred
  frames or a flash counted once; and full-frame flips.

Measure the references the person chose and put their numbers beside the film's ([studio](studio.md) §4). Measured
this way on a published 52-second kinetic-type launch film, before its end card: 29% of frames still, the longest
still stretch 0.57 s, and 5.5 change events per 10 s.

Declare the film's own pace contract in the brief, for example "40% still frames or fewer and no still stretch over
0.6 s, outside the end card and the declared reading holds", and check the delivered file against it:

```bash
python scripts/motion_scan.py film.mp4 --end 21.0 --max-still 0.6 --max-still-share 0.4 --ignore 9.5-10.4 --json qa/pace.json
```

A declared reading hold is a decision, not a defect ([picture](picture.md) §8). For a reference filmed off a screen
with a phone, measure only the screen (`--crop`): handheld movement counts as motion everywhere.

## 5. Motion between hits

- Keep something moving between the hits: the camera's slow push and slight roll, a landed word that keeps scaling
  (2-5% a second) or sliding, ghost rows of type, drifting particles with a job.
- On a flat ground, give the world a sparse texture so the camera's move shows ([picture](picture.md) §6).
- Still pictures stall first: push or pan them, punch in on each word, cut in to a detail on a beat.
- Only the end card holds, and even it creeps in.
- Movement between hits is texture. It never competes with the word being read ([picture](picture.md) §3).

## 6. Type and colour

- **One or two words per beat, filling most of the frame width.** Type 300-600 px tall on a 1920-wide frame still
  reads at 60-120 px in a 384-px phone feed. Split the phrase when a word would have to shrink below about a fifth of
  the frame height.
- **One new thing per beat:** a word, a ground, a picture. A cut, its ground change and its sound are one event.
- **Runs of beat cuts** can tighten from whole beats to half beats to a quarter beat before a hit, inside the flash
  budget (§8).
- **Grounds:** a dark ground, the brand accent and a light ground, changed at phrase changes; type colour follows the
  ground, and the accent colour goes to the one word carrying the claim ([picture](picture.md) §2). Make the dark and light grounds
  tints of the brand colour rather than pure black and white ([picture](picture.md) §9).
- **The width axis is motion:** a variable font's width can stretch, squeeze or fill a measure, on a word that stands
  alone (never on text that reflows).
- **Outline, then fill:** a word drawn as an outline while it is not yet true fills on the beat it becomes true.
- **Extruded type** is a stack of copies along depth; cap the count, since every copy costs paint time and memory.
- **The product's own visual language:** glyph scrambles and code backdrops say "code"; a game or a physical product
  needs its own ([story-and-score](story-and-score.md) §6).
- **Glitches read as failure:** never on the product's name or a claim ([studio](studio.md) §7.5).

## 7. Joins in motion

- **Whips** between shots, alternating horizontal and vertical. Cut at the whip's fastest frame, with a long-shutter
  smear (§10) and a whoosh whose apex lands on the cut; the next shot arrives already moving.
- **Dive through a letter:** the camera flies through the counter of an O, D, A, B, P, R or 0, and the inside becomes the
  next shot.
- **Shrink to a point:** everything shrinks into a point, and the next element (a line, a logo) grows out of it.
- **Switch-off:** the frame squashes to a line, then a point, to close a section.
- Fades are the mark of template motion in this register; keep them for small lines on the end card. Mix object-led
  joins in among the whips, which repeated read as a template ([picture](picture.md) §7).

## 8. Safety in this register

This register lives next to three hard limits.

- **Flashing.** A full-frame change between a dark and a light ground is half a flash. At 172 BPM, a ground change on
  every beat gives about 1.4 flashes a second, on every half beat about 2.9, and a quarter-beat run about 5.7,
  against the limit of three (WCAG 2.3.1). Saturated warm accents add red flashes: `flash_scan.py` computes the red
  ratio in linear light, where a saturated orange counts. In one published 52-second kinetic-type film, a recap that
  replayed earlier light and dark shots at speed screened at 20 transitions in one second, and large orange numerals
  rolling on a reel at 23 red transitions, about three times the limit each. Plan against the budget:
  - in fast runs, alternate grounds of similar lightness, or change hue rather than lightness;
  - keep saturated reds and oranges off full-frame changes;
  - replay a recap slowly or inside a small window;
  - `film_check.py` predicts flashes from the kit's ground timeline before rendering, and `flash_scan.py` screens
    every delivered file.
- **Patterns.** Regular patterns can provoke seizures without flashing. The UK regulator's guidance treats a pattern
  as a risk when all of these hold: more than five clear light-dark stripe pairs in any orientation (rows of dots
  count); dark bars below 160 cd/m² with at least 20 cd/m² between light and dark; and more than 40% of the screen
  when still, or more than 25% when it changes direction, oscillates, flashes or reverses contrast. Smooth flow in one
  direction is exempt ([Ofcom, Section Two guidance, Annex 1](https://www.ofcom.org.uk/siteassets/resources/documents/tv-radio-and-on-demand/broadcast-guidance/programme-guidance/broadcast-code-guidance/section-2-guidance-notes.pdf)).
  Keep world textures faint, and check dither fields, speed lines and grids against these criteria at the delivered
  size; `film_check.py` warns from the kit's own patterns, and a person qualified in these tests settles borderline
  cases.
- **Motion.** Whips, rolls, zooms through letters and shakes are large full-frame motion, which can make susceptible
  viewers dizzy ([picture](picture.md) §6). Keep shakes short and decaying and never oscillating.
- **Reading.** Words carrying a claim, a qualifier, the name or the practical line get a reading window that fits
  ([timing](timing.md) §6); texture words need none. A qualifier never flies past at beat speed: it sits beside its
  claim and stays.
- **Contrast** holds at every ground. Over a picture, put a tint plate under the words.

## 9. Sound

In this register the sound does as much work as the picture, and every rule in [sound](sound.md) holds.

- **Each cut is a sound decision:** a hit on a beat cut, a whoosh with its apex on a whip's cut, a riser whose end
  lands on the drop, a tick or pop for a small element. A silent cut is a decision too, and reading holds stay
  quiet.
- **Music at an exact tempo.** When a generator has a tempo control, set it, then measure every take with
  `tempo_map.py` and choose by grid strength and the drop you need. Fit the grid on the stretch the film uses
  (`--window`): a 0.15% tempo error moves a cue 47 s in by about 70 ms, past the 45 ms at which early sound becomes
  noticeable ([timing](timing.md) §4).
- **A starter palette** for this register, with the sync point each is placed by: impact, boom and tap
  (attack), whoosh and sweep (apex), tick, pop and key (attack), riser (end), glitch (attack) and sting
  (attack). `make_sound_kit.py` synthesises a rights-clean set with exact sync points for timing, animatics and
  drafts; chosen generated or licensed takes replace it role by role in `palette.json`.
- **Generating one-shots:** describe one isolated event per prompt, with its material and length, as a single pass
  or hit, and exclude music, voices, room reverb and background noise. Most routes charge by the second, so keep
  them short.
- **A sound of the film's own** (a knock, a stamp, a shutter) does more than another generic impact.
- **Repeats** rotate two to four takes of one sound, so a run of hits does not machine-gun.
- **Hits against the bed:** `mix_cues.py` reports each hit's level against the music in its first 150 ms. A hit under
  the music is a candidate for a listening check, not an automatic gain change; duck the bed only where a moment
  needs it.
- **Typing** at speed turns per-key clicks into a rattle; thin them to word-level accents unless the rattle is the
  texture.
- **The ending:** stopping the music dead on the sting suits this register; keep the sting near the body's level
  ([sound](sound.md) §10).
- **True peak after re-encode:** dense masters overshoot. In the same published film, a master at −0.2 dBTP measured
  +0.7 dBTP after a 128 kbps AAC re-encode (`qc_file.py --lossy-check`).

## 10. Render

- Real motion blur matters most here: whips and fast type without it strobe ([picture](picture.md) §5). Render with
  sub-frame accumulation ([finishing](finishing.md) §2), with `film_render.py` for the kit or `motion_blur.py` for an
  engine rendered at a multiple of the delivery rate.
- Inside a whip, a shutter several times the usual 180° smears the move. When a cut falls inside a frame's sample
  window, the window slides to that side of the cut instead of being cut short, so the fastest frame before the cut
  stays blurred.
- Iterate sharp, one sample a frame, at 1080p. Render the blurred master once the cut is approved, and 4K only when
  the destination needs it and memory allows.
- Bloom and grain belong in the render, never faked in the page; grain multiplies the bitrate a file needs
  ([finishing](finishing.md) §5). At 4K, set the H.264 level ([finishing](finishing.md) §4).
- A tall version is the same timeline composed for the tall frame ([formats](formats.md) §3), never the wide film
  letterboxed.

## 11. Checks particular to this register

- Before rendering: `film_check.py` (truth, contrast, reading windows, predicted flashing).
- Stills on the beat grid rather than at random times, and contact sheets at 10-20 frames a second of the busiest
  seconds ([qc](qc.md) §3).
- At every whip, look at the frames either side of the cut: the last outgoing frame is the most blurred.
- `flash_scan.py` on every rendition; `motion_scan.py` with the declared pace contract; `cue_onsets.py` on the
  effects stem; `qc_file.py FILM --lossy-check --max-level LEVEL`, with the level for the delivery size and frame
  rate ([qc](qc.md) §2).
- A person watches at normal speed, muted at feed size first, then with sound. This register is the easiest to
  misjudge from stills.

## 12. With the kit

The [film kit](kit.md) implements these devices as blocks, places them on the beat grid, and exports the cue list,
the captions and the declarations the checks need.
