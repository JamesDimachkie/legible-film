# Picture

Deciding what one film's picture should do, and the craft rules that keep it legible. No shot length, reading rate,
easing curve, type size, transition or look is right for every video, and one film's settings are not another
film's targets. The numbers below are the history of particular films, given so you can see the reasoning.

You can design, build and inspect frames, geometry and measurements. You cannot watch at playback speed: a person's
normal-speed viewing decides rhythm, feel and comprehension.

Contents: [1. The job](#1-decide-what-this-picture-must-do) · [2. A world with reasons](#2-a-world-with-reasons) ·
[3. Attention](#3-attention-one-task-at-a-time) · [4. Type and layout](#4-type-and-layout) · [5. Motion](#5-motion) ·
[6. Camera](#6-camera) · [7. Joins](#7-joins) · [8. Recipes](#8-recipes) · [9. Colour, light and finish](#9-colour-light-and-finish) ·
[10. Earned, not default](#10-earned-not-default) · [11. Footage, recordings and generated shots](#11-footage-recordings-and-generated-shots) ·
[12. Decisions people can watch](#12-decisions-people-can-watch)

## 1. Decide what this picture must do

- Start from the change sentence and the governing operation in `treatment.md`. "Premium", "kinetic" and
  "cinematic" describe appearance, not what the viewer should see happen.
- For each meaningful moment write what the viewer must understand, look at or read; which element they follow;
  what changes; what competes. Viewers mark event boundaries mostly at changes of action and situation, not at
  every cut, so put a boundary where the question changes (how it works → what it produces).
- Keep real capture, faithful reconstruction, illustration and future vision distinct, and label each as what it is.
- When the film joins a series, match the grammar of the released films first (type, accent, stage, how things
  build), and check frames from them before designing. A sibling film that drifts to a different voice reads as a
  different maker.

## 2. A world with reasons

- **One world**: a stage (light or dark, neutral or tinted), a type scale, margins, a material, and how things enter
  and leave, each with a reason inside this film. One documented film was a warm paper desk with a single thread as
  the product's spine and one accent colour on the operative word only. Mixed worlds can also cohere through
  recurring type and movement.
- **One type scale**, applied everywhere. Off-scale sizes read as mistakes, and near-miss values for the same role
  (weights or tracking that almost match) read as "almost matched".
- **One accent with one meaning**: "new", "now", "yours", "the product acting". Never let it also mean error or
  success, and check that it does not collide with the meaning the product's own interface gives that colour.
- **A few named motion curves**, each with a job (arrival, settle, exit, camera, drift), used consistently. Ad-hoc
  curves on every element read as generated.
- **A supplied brand wins.** Capture it from the live product (tokens, logo files, fonts from its CSS), use the
  vector logo as given, and record any element a reviewer might flag as an approved exception in the brief.

## 3. Attention: one task at a time

- Give each arrival to the thing the viewer should notice next. Abrupt motion onsets tend to draw the eye; quiet
  the flourish that would steal a result.
- The number of moving objects a viewer can track falls as speed rises (about eight slow, one fast, in one study).
  Move labels with their objects; coordinated motion groups things; a split shows one member branching off.
- Viewers often miss large changes when a cut, a flicker or competing motion hides the transient. When a changed
  number or state is the evidence, make the comparison findable.
- One focal point at a time, unless a comparison needs two.

## 4. Type and layout

Rules that came from rendered defects; each is cheap to check on a full-resolution frame.

- **No print over busy illustration.** Copy and footnotes sit in a clear field or on a solid plate. Check every
  label against every moving object at every time: a footnote that ran under an illustrated globe was found only by
  checking each time. Mask animated backgrounds (networks, particles) out from behind text and cards; fading
  individual elements is not enough, because streaks still cross type mid-flight.
- **Copy stays in its own column.** Measure the widest line and card in each scene against where the illustration
  lives; one scene's 84 px answers reached past the centre of the frame into the figures it was describing.
- **A qualifier that changes a number's meaning sits beside the number** at label size, with the full condition in
  the footnote. Footnotes and "illustrative" labels never shrink below footnote size or leave the frame early.
- **Comparable numbers share one size and one aligned column**, with tabular figures. Small print never swaps into
  big print.
- **Text from two scenes never overlaps.** A simultaneous cross-fade printed one card over another for three frames;
  clear the outgoing text, leave a beat, then bring in the next.
- **Reveals use whole letters or whole words** unless partial letterforms are the point. A per-letter mask rise
  showed partial glyphs that read as a render glitch. Before building a sweep or letter reveal through a name, list
  every partial state and check none spells another word.
- **Word spaces stay open** when words meet, including during overshoot; inline word spans can collapse the space
  before the last word in some renderers.
- **Margins hold for objects as well as text**, in every rendition and crop; measure object bounds at their extreme
  times (one chip started 21 px off the frame edge). Keep text and essential interface out of platform overlay
  zones ([formats](formats.md)).
- **Readable at viewing size.** Decide which rendition each text must read in and check it there
  (`frame_sheet.py --width 384` for a phone feed). One launch film set captions at 56-64 px and interface text at
  36-40 px after camera scale and judged every frame at 384 px wide.
- Group chips by meaning, not by available width; a wrapping row strands one chip on its own line.
- Balance short multi-line text so no line ends on one stranded word.
- A moving reading cursor gets its own rail clear of the next line of text.
- Size boxes with their padding included (`box-sizing: border-box` in CSS): with content-box sizing, padding pushed
  a 912 px card 54 px past the margin.
- A variable font clamps any weight outside its axis to the nearest weight it has, silently; check the axis range
  before specifying a weight. Do not animate the weight of text that reflows.

## 5. Motion

**Character.** Describe the behaviour in verbs ("aligns decisively", "yields and rebounds", "flows at a constant
rate") and test it on the important action. Calm, snappy, playful and mechanical are performances to compare, each
with a cost. Time spent moving and time spent on the important state are separate settings, and stillness is
available.

**Motion makes claims.** People read simple shape motion as causal (one object meeting another before it moves) or
as intentional (pursuit, self-directed turns). Check that a move does not credit the product with agency, speed or
certainty it lacks, and show a real intermediate state when processing matters.

**Weight and cause:**

- Arrivals decelerate into place; departures accelerate away; a camera eases at both ends.
- Fade with a curve that is gentle at both ends. A fade-out on a strong ease-out drops its first frames abruptly:
  an exponential ease-out over 12 frames removes 44% of the opacity in the first frame, which reads as a pop.
- Zoom geometrically: interpolate the logarithm of the scale (`exp(lerp(log a, log b, t))`). Scale interpolated
  linearly from 1× to 4× reaches 2.5× at the halfway frame instead of 2×, so the move dawdles and then rushes.
- Duration grows with distance, and the slowest move in a film should be several times the fastest, or everything
  seems to move at one tempo. When the product's own interface animates at a known speed, show that speed.
- Shape settles slightly before position, and a contact can squash briefly at the contact edge.
- Moves meant as one gesture overlap (overlapping action, in animators' terms): begin the second before the first
  has finished, so neither stops dead at
  the hand-off.
- Overshoot belongs to a true landing, sparingly. Type settles without bounce; an overshoot that closes a word
  space reads as a typo.
- Keep values that drive geometry (size, radius, blur, clip) inside their valid range, so an overshoot never makes
  one negative; renderers
  can reject the invalid value and freeze the last valid shape.
- When an object changes form, change that one object: one documented card kept a single continuous outline while its
  lettering dissolved. Two overlapping copies fading against each other read as a ghost, and if both layers are
  ever transparent at once the object blinks (a near-empty card showed for one frame until the layers were reordered).

**Measure the path before rendering.** For any element whose path is computed, compute its frame-to-frame step for
the whole move. A step far larger than its neighbours is a jump. In one film a closing line held for 0.25 s and then
travelled about 450 px in 0.15 s; the listener called it "a jump". The fix moved the same line forward slowly along
its own direction in one curve, with a largest step of 3.9 px, landing on the final hit.

**Speed and the frame rate.** What the eye objects to is how far an element jumps between displayed frames compared
with its own size: a small label that leaps several of its own widths per frame strobes or doubles. Give fast elements
motion blur ([finishing](finishing.md)), or rethink how they travel: shorten the trip, or replace the move with a cut.
Halving the frame rate doubles every jump. Prefer 60 fps when interface, text or the camera moves.

## 6. Camera

- Write what each camera move reveals, follows or changes, and compare it with a locked view; a move that only adds
  activity costs attention.
- Frame by an anchor: "this world point sits at this screen point at this scale". Interpolate the points linearly
  and the scale in log space, and the subject keeps a steady line and an even rate of zoom.
- Land the camera on measured element coordinates after layout, not on guessed offsets. Keep the world, the camera
  and temporary effects (shake, punch) on separate layers so they never fight over one transform.
- Check the whole approach and the landing: text size after scale, the landing after a copy change, and the edges
  at the most extreme moment (a scaling layer can expose the stage edge; overscan moving layers).
- A camera move over a flat ground is invisible: with nothing fixed to the world, a slow push reads as a still frame.
  A sparse texture that moves with the world (a dot grid, faint type, grain of the material) makes the move visible.
- Large or full-frame motion (fast zooms, rolls, parallax) can trigger dizziness or nausea in susceptible viewers;
  WCAG 2.3.3 names parallax and non-essential motion. Use it where it earns its place.
- Flat layout suits reading and comparison; layered planes give hierarchy; full 3D earns its cost when form,
  material or spatial relations matter.

## 7. Joins

Choose the relationship first, then the technique:

| Join | Fits when | Failure test |
|---|---|---|
| Plain cut | the next view brings the next fact, contrast or scale | can the eye find the destination without searching? |
| Match cut | shape, framing or movement links two views | does the resemblance imply a false equivalence? |
| Object carry | the same entity continues into a new context | is it really the same entity, and is the destination relation true? |
| Morph | a state or form genuinely becomes another | does continuous geometry imply a continuity of data or capability that does not exist? |
| Whip | energy or fast relocation belongs to the passage | does the viewer reorient before the next essential event? |
| Dissolve | time passing, atmosphere, a gentle association | what does the overlap show? competing text makes noise |
| Hold | a result or feeling is still landing | has the shot finished giving the viewer something? |

- Momentum carries across a cut. Editors have long cut on action: a whip in one documented film cut at its fastest
  frame, on a whoosh where the music lifts, and the next shot was already travelling. A fast exit into a static
  opening loses that energy; when one side must be still, let both be.
- A pose the viewer has just seen settle should not be shown settling again on the other side of the cut; the
  repetition reads as a stall.
- A carried element is the same object on both sides of the join: same place, size, corners, colour, shadow, opacity
  and blur, positioned the same way in both scenes. A sub-pixel difference in how the two scenes place it makes the
  frame shimmer at the swap.
- A dissolve in which both pictures fade at once darkens the frame: halfway through, the upper picture shows at
  half strength and the lower one only through it, about three-quarters of full brightness in total. Keep the
  outgoing picture opaque and fade the incoming one over it.
- Continuity editing hides cuts and even changes on screen (in one study viewers missed a quarter to a third of
  continuity edits while looking for them). Match action when the viewer should carry an event across; announce a
  consequential change when seamlessness would hide it.
- A cut is a sound baseline. "Slideshow" pacing is repeated stop-start with nothing developing, not the use of cuts.
- Too many identical whips read as a template; make some transitions object-led. A stock transition preset reads as
  a template unless the concept calls for exactly that texture.

## 8. Recipes

**Object carry across a camera move.** Draw the travelling copy in a screen-space layer outside any motion-blurred
stage, so it stays sharp while the world blurs, and under the grade layer, so it keeps the grade. Map it with a
perspective transform (a CSS `matrix3d` homography from the projected corners of the world rectangle) seen through a
virtual camera that glides from the start shot to the end shot, so it matches the real object exactly at both ends.
Hide the real object for exactly the flight window, and verify the hand-off bounds at the swap frames with a
seek-and-measure probe.

**The thread.** Hand the same element to a top layer at its identical screen position (its world points projected
through the camera) and carry it on, rather than fading it and bringing in a new one. Control its line, head dot and
glow together at every hand-off: a glow helper once faded its gradient but left its core dot at full opacity. Drawn
additively in two passes, a wide dim glow under a thin bright core, it reads as light; when it arrives, its tail
drains into its head rather than vanishing. A thread that would imply a false relationship stops short or recedes; it
never connects.

**A contact.** A velocity discontinuity plus a shadow change on the contact frame, then a short squash (about 80 ms),
reads as an impact; a soft ease into rest does not. Other materials need other responses, and an abstract state
change may need no contact at all.

**3D card flips.** A card rotating through a pile intersects it; lift it by at least half its size times the sine of
the flip angle. Rows can flip like a split-flap board.

**Holds that breathe.** A small push or slow drift keeps an otherwise lifeless hold alive when the treatment calls for
it; start a drift from rest so the cut into it carries no jolt. Preserve deliberate locked-off reading holds and
approved freezes: a detector flag or reviewer agreement alone is not a reason to add motion.

**Show rates honestly.** A pulse that stands for a rate must be visible at viewing size; one film made its pulses
three times longer, with fading tails and glowing heads.

## 9. Colour, light and finish

- Give colour, light and texture each a job: selection, separation, material or atmosphere. Colour is never the only
  carrier of meaning (WCAG 1.4.1). Essential text needs at least 4.5:1 contrast (3:1 for large text, WCAG 1.4.3) and
  essential graphics 3:1 (WCAG 1.4.11), checked against the background as it changes.
- **Tint the neutrals.** From the brand colour, build a scale from near-white to near-black that keeps the brand's hue
  at low chroma (OKLCH makes this a matter of holding the hue and lowering the chroma), and use it for every ground,
  panel, rule and text colour instead of pure greys: the light ground is a very light tint, the dark ground a very
  dark one. The film carries the brand without spending the accent, and semantic colours (success, error) keep their
  meaning without dominating. Check that a dark tint survives the encode with `qc_file.py --color-patch` on a patch of
  ground.
- Interpolate colours in a perceptual space; blending in gamma-encoded sRGB gives muddy, darker midpoints.
- 8-bit pipelines step slow changes: a background drifting from 20 to 24 on the 0-255 scale over four seconds can only
  take five values. Keep slow tint changes small, hide them in motion, or dither. Smooth gradients that span few code
  values band; ship them as dithered images ([finishing](finishing.md)).
- Judge dark brand tones and gradients on the encoded file: 8-bit 4:2:0 encoding flattens dark tints.
- Light can mark selection: depth of field directs the eye when the blur is capped and the subject stays sharp.
  Brightening a paper stage to make whites "pop" can erase the separation between cards and the desk.
- **A finish pass.** One series lifted every piece with a single change to its shared motion and finish: a living
  camera (a slow scale across the piece, a further push onto the logo), impact frames (a small camera punch and a
  soft light flash on the same frame as the boom), type that settles into focus, slight depth on landing cards, and a
  finish of bloom, vignette and grain. Another film may need a different finish, or none. Blend layers in RGB: a
  screen blend run on YUV planes turned every deliverable purple, and a numeric pixel check against the raw render
  caught it.
- Realistic rendering can be mistaken for evidence. Generated or rendered realism suits atmosphere and metaphor, not
  proof that a product operation happened.

## 10. Earned, not default

Every element earns its place, and a weak element is strengthened until it does; stripping the piece down to bare
primitives is not the fix. Defaults are where generated work looks generic, so question each one:

- the stock opening fade, the slow push and the centred closing card that every generator reaches for;
- a small card floating in an empty field, or text left and interface right in every shot;
- an eyebrow label over a headline over a subhead; stacked taglines;
- clip-art icons, glitter meant to say "intelligence", drifting particles, and gradients or glows with no job;
- decorative captions, invented metrics and labels nobody needs (an invented number is an unsupported claim);
- bounce on copy, and a new text trick on every card.

Each is fine when it was chosen for this product and this moment.

## 11. Footage, recordings and generated shots

- **Live action and interviews:** keep screen direction, eyelines and action continuous across cuts; intended jump
  cuts read as intended when they are consistent. Stabilisation and speed ramps are motion choices to judge at speed.
- **Screen recordings:** the viewer follows the cursor and the viewport. Zoom and pan follow the action, not a timer;
  the cursor arrives before the click and the response follows it.
- **Generated video:** check identity drift between shots (faces, products, logos), text, hands, and physics that
  implies a capability. Label generated shots in the asset register ([claims-and-rights](claims-and-rights.md)).

## 12. Decisions people can watch

- Style frames settle a look, boards a sequence, an animatic timed development, and a short motion study a risky
  mechanism. A still cannot approve rhythm.
- At an open question, show comparisons that change one thing: a plain cut against the proposed transition, a heavy
  landing against a responsive one, a hold against its shortened version.
- Translate a note into a hypothesis about its cause: "too fast" can mean late readability, an early exit,
  competing motion or unfamiliar content.
- Ask for an unpaused, muted pass at feed size first, then a pass with sound, then pauses to diagnose, and record who
  watched which version under which conditions.
