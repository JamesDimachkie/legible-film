# Sound

Deciding what one video's sound should do, then making and checking it. No loudness figure, effect-to-music
ratio, cue density or other film's numbers is a target here. The one fixed rule: nothing jarring.

You can measure sound but you cannot hear it. Every report keeps four things apart: the treatment (what the
sound is meant to do), measurements, tool labels, and the listener's decision. Until a named person has heard
the delivered file, the sound is **unheard**.

Contents: [1. Read the film first](#1-read-the-film-before-any-sound) · [2. Map the moments](#2-map-the-moments) ·
[3. Who leads](#3-who-leads-each-passage) · [4. What sound does to picture](#4-what-sound-does-to-the-picture) ·
[5. Music](#5-music) · [6. Effects](#6-effects-and-the-palette) · [7. Voice](#7-voice-and-narration) ·
[8. Mix and master](#8-mix-and-master) · [9. Clean signal](#9-clean-signal) · [10. Endings](#10-endings) ·
[11. Loudness references](#11-loudness-references-not-targets) · [12. Decisions people can hear](#12-decisions-people-can-hear)

## 1. Read the film before any sound

- Look at the cut muted (sheets and a short preview), then write: "The viewer starts ___; this film shows
  ___; by the end they should understand ___ and feel ___." If that will not come, settle the film's purpose
  before choosing a genre or a palette.
- Record what is fixed: approved picture and sound, captions, claims, the devices it plays on, whether it ends
  or loops, and whether it must work muted (most feed video autoplays muted; the picture must carry the claim
  without sound).
- Write a sound proposition with a cause and a consequence: "the scattered inputs sound separate until they
  become one result; then the texture becomes continuous." "Premium, modern, energetic" names no decision.

## 2. Map the moments

For each passage that matters:

`time → what changes for the viewer → intended reading and feeling → what leads → what yields or stays silent → timing anchor → question for the listener`

- An animation's first frame is rarely its meaningful moment. Separate contact, continuous motion,
  anticipation and consequence; each has a different timing job ([timing](timing.md)).
- The cue list is an inventory, not an obligation. Record intentional silence as a decision (`"sound":
  "silent"` in `cues.json`), and keep that role silent through rebuilds rather than letting a default sound
  creep in.
- Where the viewer must read a number or a sentence, try the hold with no new sound events: an unexpected sound
  pulls attention from the task at hand.

## 3. Who leads each passage

Decide per passage, not per film: music leads (effects add selected detail), effects lead (actions make the
phrase), voice leads, quiet leads, or music and effects form one gesture. Then place the passage on these
dimensions, in words rather than scores:

- **Clock:** speech, a chain of actions, a musical phrase, a change of state.
- **Relation to the image:** literal (a credible cause), stylised, or abstract (a consistent rule for graphics
  that have no real sound). A designed UI sound is not the product's real sound; do not present it as one.
- **Density:** how many changes need their own sound. A busy frame can need one continuing sound; a nearly
  empty one can need detail.
- **Energy and contrast:** build, hold, drop or reset.
- **Sync:** which contacts land exactly, which movements sit inside a broader phrase.
- **Material and stance:** bodily, mechanical, soft, brittle, warm, uncanny. The subject does not choose the
  instruments; a technical subject can be scored with tactile acoustic sound.
- **Ending:** what the last sound leaves behind: completion, an open capability, a question, a brand, a clean
  loop.

## 4. What sound does to the picture

Hypotheses to test in the cut, with their evidence:

| Mechanism | Evidence | Use |
|---|---|---|
| A sound at the instant two moving objects cross can make viewers see a bounce or collision; extra beeps can add perceived flashes. | Replicated lab effects with simple, ambiguous stimuli (Sekuler et al. 1997; Shams et al. 2000) | Decide what each contact should seem to be; avoid implying collisions or extra events by accident. |
| Sounds pull the perceived timing of nearby visual events slightly toward them. | Replicated, small shifts | Put the attack on the meaningful event. |
| Rising intensity tends to be judged as changing more than falling intensity, often linked to approach. | Contested (Neuhoff 1998 and later work) | A level change alters scale; keep approach, upward motion and anticipation distinct. |
| Rounded and angular shapes pair with rounded and harsh sounds. | Replicated across languages; appears with some non-speech sounds too | Choose a rounded or brittle vocabulary before individual effects. |
| Music steers how viewers interpret and remember the same footage. | Several lab studies; effects on perceived pace are mixed | In a comparison, give both sides the same sound treatment. |
| Unexpected sounds briefly disrupt an ongoing visual task. | Large lab literature (Parmentier 2014 review) | Spend interruption where it matters, never during a read. |
| Silences can be perceived as events. | One 2023 paper, several experiments (Goh et al.) | A dropout can mark a boundary, but a muted viewer never gets it. |
| Hearing is most sensitive in the mid frequencies (roughly 2-5 kHz); equal level is not equal loudness. | ISO 226 equal-loudness contours (pure tones) | If a cue jars, test its level, onset, narrow-band emphasis and roughness one at a time. |

None of this yields a tempo, a cue density, a silence length, a loudness or a ratio.

## 5. Music

- Give music a job: "Music supplies ___; it enters, changes or leaves when ___ because ___." Pulse, emotion,
  brand character, continuity and structure are jobs. No music, intermittent cues, and music growing out of
  the effects are all options.
- Fit two or three candidates (a no-music version counts) to the real picture, conformed to its turning point
  and ending, and let the listener choose. A track heard alone does not show what it does to a 40-second cut.
- Generated music tends to ignore requested sections. In one documented set of takes, every take held a
  steady tempo, ignored the requested builds and breaks, and some went silent seconds before the end. Ask for
  about 20% more length than the film needs and build the structure in the edit (crossfades at bar lines,
  gain automation, filtering). Per-section audio references made requested structure land where text alone
  did not.
- When a generator has a tempo control, set it, then measure every take with `tempo_map.py` (tempo, phase, drops,
  drift) and choose by the grid and the drop the film needs, not by the take heard first ([timing](timing.md) §9).
- To lengthen or reshape a sustained take (pads, choirs), regenerate rather than splice repeated bars;
  splices mid-chord sound glitchy even on the bar grid.
- Conforming, beat phase and swing are in [timing](timing.md).
- Rights: some generation plans make output non-commercial, and upgrading later does not cover earlier
  output. Record the plan at creation in the asset register ([claims-and-rights](claims-and-rights.md)).

## 6. Effects and the palette

- Define a world before generating assets: material family, attack, tonal or noisy, apparent distance, room,
  how much variation is allowed. Give each sound family one meaning (selection, completion, error) and keep it.
- For each cue, ask what it adds (attention, weight, character, structure, expectation, release), then compare
  the moment without it; keep it if something useful goes. When a moment feels weak, try subtraction before
  gain: remove a competing rhythm, shorten a tail, clear the moment before it.
- Keep each family's meaning stable and its repeats alike: a sound that marks completion in one scene and appears
  at random in the next teaches the viewer nothing. Size each sound to what causes it; small sounds on big moments
  shrink them, and a loud sound over a still picture reads as a mistake.
- Typing: keep key sounds in one small family, vary level and timing slightly rather than timbre, and thin dense
  typing to a few word-level accents. Bright, identical, machine-gun keys are the common failure.
- Audition every sound alone and every composite moment alone before using them; context hides defects and
  layers combine. Tool labels can be revealing: a "fast air whoosh" that reads alone as "a balloon squeak" is
  a palette problem, not a timing one.
- Keep a manifest for the palette ([palette.json](../assets/templates/palette.json)): each role's approved takes,
  their file hashes, provenance, gain and the sync point inside each take. Reuse accepted takes instead of
  regenerating them on every mix, and disclose any unavailable role or substitution before calling a mix final.
- `make_sound_kit.py` synthesises a rights-clean starter palette (impacts, hits, whooshes, ticks, pops, keys, a
  riser, a sting) with exactly known sync points, and a temp music track at an exact tempo, so a film can be
  timed, mixed and checked before anyone buys or generates sound. It is a draft palette: replace roles as better
  takes are chosen, and let a person decide whether any of it ships.
- `mix_cues.py` builds the effects stem, the music bed and the mix from the cue list and the palette, placing each
  take by its own sync point (attack, apex or end), rotating the takes of a role across repeats, ducking the bed only
  where an event asks, and reporting missing roles, events that would smear together, and hits that sit under the
  music. It places and reports; the listener decides.
- A sound of the film's own (a knock, a stamp, a shutter, the product's real alert) carries more than another
  generic impact.
- Repeated takes with equal peaks can differ in perceived loudness; compare short-term loudness and audition
  them in context before trimming.
- Tonal effects belong to the music when pitched to its key; rerun artifact checks after retuning.
- Video-to-sound and other generators supply raw material; the design is still yours, and uploads of private
  footage need permission.

## 7. Voice and narration

- Cast the stance, not just the voice: serious facts read as crisp reporting, not lament; a whispered opening
  that then switches to normal speech reads as a mistake.
- Speech must be intelligible over the bed: duck music under speech only as much as the phrase needs, and
  clear masking frequencies rather than raising the voice into a limiter.
- Captions for every spoken line (WCAG 1.2.2 for web video), timed to the speech and readable
  ([timing](timing.md)); a transcript of generated speech is a first draft to check, not a caption file.
- Synthetic voices need rights for the intended use; record the voice, the plan and the date.

## 8. Mix and master

- **Nothing jarring:** no accidental clipping, distortion or clicks, nothing painful, no startling jump, no
  ending louder than the body. Contrast, surprise and texture remain creative tools; whether a moment crosses
  into jarring is decided by ear.
- Master with a light safety limiter, not a loudness maximiser. Lift a quiet passage with plain gain (ramped)
  rather than more limiting. Removing all limiting can leave openings too quiet on a phone.
- Duck music under an effect or a voice only where the moment's hierarchy needs it, by an amount set by
  listening; rearranging or removing a layer may solve it first.
- **Make every sound change audible before asking about it.** Mux each variant onto the picture and share it;
  a listener cannot approve a gain change they have not heard, and tuning by measurement alone drifts away
  from what sounds right.
- Lossy encoders overshoot sharp transients (EBU Tech 3344; worse at low bitrates). Measure true peak on the
  encoded deliverable and after a simulated platform re-encode (`qc_file.py --lossy-check`), and trim the
  limiter until the re-encode stays below 0 dBTP.
- A short-delay stereo widener combs transients and changes in mono (one widener put "glitchy noise on the kicks";
  a mid/side gain change worked instead). Check important cues in mono; `qc_file.py` reports how much quieter the
  mix becomes when folded to mono, and a large loss points to out-of-phase content.
- To find out whether an effect can be heard against the music, render the moment with and without it and compare
  the difference in the effect's own frequency band. The number locates a likely masking problem; the listener
  decides.
- Render a band-limited preview (roughly 350 Hz-8 kHz) to see which cues depend on deep bass or air. An
  essential event carried only by deep bass needs an attack or harmonics that survive a phone speaker: the
  pitch survives through harmonics, the felt weight does not.
- Mux the mastered mix onto the finished picture. An engine's own audio path can render at a different level
  (one HTML renderer placed audio 11.6 dB below its source); measure, then deliver the master.

## 9. Clean signal

These prevent unintended artifacts in any mix. The numbers are what worked in one pipeline, not perceptual
limits, and a designed hard cut is still allowed when it is the intent.

- No synthesised voice stops mid-decay: give every note a release (8-40 ms worked). Notes cut at a fraction of
  their level click on every beat.
- Pitch one-shots with polyphase resampling rather than FFT resampling (which wraps a sound's ends into each
  other), and re-fade the edges after pitching.
- Ramp every gain change. A duck that steps in one sample crackles; a limiter with a few milliseconds of
  look-ahead and a smooth release does not.
- Fade drop-outs and riser ends (about 25-30 ms); a 10 ms cut can pop.
- Scan for narrow resonances (sliding 0.5 s windows) and for clicks; play every flag in context. Sharp, narrow
  peaks in the 3-6.5 kHz region were heard as unpleasant in one series; replacing the sound fixed it where
  notching did not.

## 10. Endings

- An ending is a design choice: a cadence, a ring-out, a dry stop, a loop seam. Unity relief, refusal of triumph
  and an unsettled close are all legitimate endings; one victory sting would misstate most of them.
- The ending must not be louder than the body. In one series a logo landed at full level over a bed that had
  already stopped and was heard as "exceedingly loud, kind of jarring"; bringing it to about body level fixed it.
- A final hit can ring out: one music-led film ended on a six-second reverb tail, band-passed and set a few dB
  under the hit, which let the logo settle without a hard stop.
- When a design has a drop and the bar before it keeps its bass, the drop lands weakly. In one film every bar
  dropped its low end 10-15 dB before the downbeat except the bar into the re-drop; a short bass cut over the last
  half-beat restored the contrast.
- Check the decoded head and tail of the delivered file (`qc_file.py` reports them): no sound at full level on the
  first samples unless a hit is designed for frame 0, no click or truncation at the end, and silence at the end when
  intended.

## 11. Loudness references, not targets

Measure integrated loudness and true peak on the delivered file and report them; they describe the file.
Choose levels from the delivery spec and the listening decision. Published references, for context:

| Context | Reference |
|---|---|
| Broadcast (EBU R128-2023) | −23.0 LUFS programme loudness; true peak ≤ −1 dBTP |
| Short-form broadcast content (EBU R128 s1) | −23.0 LUFS; maximum short-term loudness −18 LUFS; ≤ −1 dBTP |
| US broadcast (ATSC A/85:2026) | −24 LKFS; true peak below −2 dBTP; streaming annex: one target between −23 and −27 LKFS |
| Music streaming (Spotify, music masters) | playback normalised to −14 LUFS; peaks ≤ −1 dBTP, −2 dBTP for loud masters |
| Social video platforms | no official loudness target found for YouTube, X or LinkedIn; third-party measurements of YouTube's normalisation (about −14 LUFS) are measurements, not a spec |

A quiet, dynamic mix and a dense, loud one can both be right. Two films approved by the same listener in one
month were mastered about 5 LU apart; carrying one's numbers to the other made it sound muted.

## 12. Decisions people can hear

- At an uncertain moment, prepare two or three treatments that differ in one choice, with the picture fixed,
  some lead-in and aftermath, and similar overall loudness: a literal contact against a musical articulation,
  a hit against a reduction, tight sync against broad alignment. Ask a concrete question: "Does this make the
  result feel like a confirmation or an alarm?"
- Record each note as `time → intended job → what the listener heard → likely cause → change → decision`.
  "Too busy" can mean competing rhythms, long tails, an intrusive timbre or a reading problem; it does not
  automatically mean the effects are too loud.
- Ask for the full delivered film at normal speed, on the devices where it will play (a phone speaker when a
  key moment depends on bass, stereo detail or a quiet texture). Until then, report the sound as unheard.
