# Film kit: blocks and options

A film is `film.js` beside `index.html`: a function of the kit returning a spec. Scenes play in
order; each is a block, a device with one job, built once and updated purely from t. Times are
seconds; `T.b(n)` (from `clock({bpm})`) is n beats, and strings such as `'2b'` or `'0.5b'` also work.
Layout is in frame units (`u` = 1% of the shorter side) inside the safe area, so one timeline
renders 16:9, 9:16 and 1:1 (`?w=1080&h=1920`). In a tall frame display type takes the condensed
width and blocks stack rather than shrink.

```js
export default function film(kit) {
  const { Words, Terminal, Number, Name, Picture, Chain, Without, EndCard, Caption, Dither, clock, block } = kit;
  const T = clock({ bpm: 150, offset: 0 });
  return { title, size: [1920, 1080], fps: 60, beat: { bpm: 150, offset: 0 }, brand: '#3D7BFF',
           facts: 'facts.json', scenes: [ ... ], captions: Caption({ ... }) };
}
```

## Spec options

| Option | Meaning |
|---|---|
| `size`, `fps`, `duration` | frame size (overridden by `?w=&h=`), frame rate (60 default), optional fixed length |
| `beat` | `{bpm, offset}`: the beat grid; `offset` is the film time of beat 0 |
| `brand`, `palette` | one brand colour builds the palette (tinted neutrals in OKLCH); `palette: {paper: '#..'}` overrides a name |
| `ground` | the starting ground (palette name or colour); blocks set their own |
| `facts` | path to facts.json; every `claim` must equal a fact's `display` (a string or a list), every `qualifier` its `label_beside_value` |
| `reading` | `{cps: 15, base: 0.3, captionCps: 20}`: the reading rule for need_s |
| `readingRests` | default true: each claim, qualifier, identity, ui and headline text declares its reading hold `[readFrom, readFrom + need_s]` as a rest (excluded from pace gates). `readFrom` comes from the block's own timeline (the landing, the end of typing), so rests are identical at every size; analyse() checks the text really is readable by then. Texture never gets one |
| `pace` | the film's own pace contract, passed through info (for example `{maxStill: 0.6, maxStillShare: 0.4}`) |
| `music` | `{stop, drop}` film times; an end card sets `stop`, a Words shot with `drop: true` sets `drop` |
| `pace` | your pace contract, passed to info() for make_film.py |
| `texture` | `{kind: 'dots' \| 'rows', spacing, dot, words, maxDiff: 8, alpha}`: a sparse world texture that moves with the camera. Its alpha is set per ground so the light-dark difference is `maxDiff` cd/m2 (8 by default, under the 20 cd/m2 pattern criterion) |
| `safe` | `{x, top, bottom}` margins as fractions (defaults 0.06/0.08/0.08 wide; 0.07/0.10/0.17 tall). Reels ads ask for about 0.06/0.14/0.35 |
| `fonts` | `{display: {url, family, weight: '200 900', stretch: '75% 125%'}, text, mono}`: a supplied brand font replaces the kit's |
| `captions`, `overlays` | screen-space blocks that run across scenes (Caption) |

Every scene takes `len` (its length), `start` (an absolute start, otherwise it follows the previous
scene), `enter` (`cut`, `whipX`, `whipY`, `zoom`), `exit` (`cut`, `through`, `collapse`) and
`move: {push, roll}` (the default slow push and slight roll, so a frame never parks).

Joins: `whipX`/`whipY` accelerate the camera away, cut at peak speed and arrive from the opposite
side decelerating (cut, smear and fast windows and a `whoosh` cue at the apex are registered).
`through` flies the camera into the counter of a letter (O, D, A, B, P, R, 0...), whose window shows
the next scene's ground and grows until it fills the frame at the cut; the next scene arrives from
depth. `collapse` shrinks everything into a point the next scene grows from.

## Blocks

### Words: the kinetic-type sequencer
One idea per beat or half beat. `Words({shots, exit, through: {letter, shot}, drift, push, roll, maxPerSecond})`.

| Shot option | Meaning |
|---|---|
| `text`, `tall` | the words; `/` breaks lines; `tall` gives the portrait breaks |
| `string` | the registered string if it differs from the joined lines |
| `dur`, `at` | how long the shot holds (default 1 beat), or an explicit time after the scene start. A shot's time is its landing (the contact frame) |
| `style` | `slam` (lands from scale and blur), `stack` (a kicker, then the big word `gap` later), `pair` (two lines from opposite sides), `cut` (hard-cut words with per-shot size and slight rotation), `extrude` (3-D type out of depth), `outline` (an outline, filled at `fillAt`: drawn while not yet true) |
| `kicker`, `kickerColor` | the small line above (`stack`) |
| `ground`, `color` | a ground per shot (flip at phrase changes; each flip counts toward the flash budget); type colour defaults to the palette colour with the higher contrast; `'accent'` when legible |
| `enter` | `cut`, `whipX`, `whipY`, `zoom` |
| `hit` | `none`, `beat` (a camera bump), `hit` (bump and small shake), `punch` (speed lines, ring, rays and sparks: the biggest moments only) |
| `build: 'lines'`, `step`, `uniform` | lines land one per `step`; all lines at one size |
| `role`, `fact`, `id` | `headline` by default; `claim` needs a fact |
| `fill`, `weight`, `width`, `tracking`, `maxH` | type: fill of the safe width (0.86, or 0.76 for holds over 2.5 beats), axes |
| `fillAt`, `fillHit`, `fillCue` | outline only: when it becomes true, and how that lands |
| `pulse` | camera bumps on later beats of a long hold (`['1.5b']`) |
| `drop` | this landing (or fill) is the planned musical drop |
| `open`, `openHit` | already in place on the scene's first frame (frame 0 reads as a feed cover); its hit and cue land `openHit` later (default one beat). The first shot of a scene entered by a collapse (grow) or a fly-through (arrive) behaves the same way, landing when the growth or arrival ends |
| `still` | default: every shot whose role must be read holds locked off (no drift, push or roll); only `texture` words move. Big high-contrast type drifting even 30-50 px/s carried letter stems across third-of-frame windows and measured as flashing |
| `lineEntrance`, `lineHit` | in a line build, later lines appear in place on their beat (`lineEntrance: 'slam'` restores the slam); `lineHit` for them (`beat` by default, `none` for no bump) |
| `cue`, `lead`, `rot`, `depth` | cue role override or `false`; entrance lead; rotation; extrusion depth (em) |

Texture shots have their own slow push and roll from their cut; drift and push share the room the
widest line leaves inside the safe area, along whichever axis has more room. Reading shots are still. Display words are fitted to the safe width after fonts load; a word that would fall below 7%
of the frame height warns that the phrase should be split. Reveals are whole letters or whole words;
word spaces are margins, so they never collapse.

### Terminal: a command typed on frames
`Terminal({command, prompt, output: [string | {text, tone: 'mute'|'ok'|'accent'|'text', fact, role}], title, typeAt, cps: 24, lineGap, firstLine, hold, push: 'content'|'window'|false, pushFrom, ground, role: 'ui', fact})`.
Characters, the caret and its blink follow `__lf.frame()`. The camera glides along the typed text
(continuous progress, not the stepping caret), then pushes in toward the fitted content without
passing it; a tall frame also travels vertically. Durations and curves come from the motion tokens.
Cues: a `key` accent per word of the command, a `tick` on enter, a `pop` per output line.

### Number: a value from a fact
`Number({fact, land: 'slam'|'cut'|'digits', label, qualifier: true, step, at, hold, ground, hit})`.
The value is the fact's `display`; the qualifier is its `label_beside_value`, beside the number at
label size. It lands by a slam, a cut, or digit by digit with each digit arriving already final. It
never rolls or counts through values that were not measured.

### Name: the product's name out of depth
`Name({name, kicker, sub, fact, subFact, subRole, kickerColor, color, ground, at, fly, cps, depth, sweep, pushFrom, exit})`.
Extruded type (a capped stack of copies along depth, sides from the palette) flies in from depth and
lands with a punch; a light band sweeps the face once; the kicker sits above; the sub line types on
frames. With `exit: 'through'` the face turns square to the camera and, for the extreme end of the
dive, is drawn as traced vector outlines with the counter's window sharing their edge (a composited
3-D layer is a bitmap and goes soft when magnified).

### Picture: an image that pushes and pans
`Picture({src, from: {focus, zoom}, to: {focus, zoom}, len, words: [{text, tall, at, dur, role, fact, hit}], tint, tintAlpha, details: [{at, focus, zoom, push, cue}], label, labelFact, ground})`.
Zoom is interpolated in log space and the frame stays covered. Words punch in on beats over a tint
plate in screen space (contrast is checked against the plate over white). Details are hard cut-ins.
It warns when the source has fewer pixels than the frame width times the largest zoom.

### Chain: nodes joined by the comet thread
`Chain({nodes: [{label, sub, role, fact, id}], links: [[0, 1], ...], hop, lead, settle, pullback, hold, ride, size, ground})`.
Two to four cards; the thread (two additive passes, a wide dim glow and a thin bright core, the tail
draining into the head on arrival) runs only along the links given. The camera rides a curve beside
the thread from node to node, then pulls back to show the whole chain; the drawn line stays until
the scene ends.

### Without: the old way, broken
`Without({text: 'NO X.', fact, mock: 'timeline'|'tiles'|'rack', breakAt, landDelay, hold, ground, seed})`.
A simple drawn mock (timeline bars, tiles, rack rows) drifts as if still running, then breaks apart
(seeded pieces under gravity, with motion-blur windows) and the denial lands as the centre clears.
The denial is a claim and needs a fact.

### EndCard: held readable, declared as a rest
`EndCard({logo, inlineLogo, logoHeight, wordmark, typed, wordmarkFact, tagline, taglineFact, taglineRole, line, lineFact, lineRole, ground, at, hold, len, musicStop, logoGain: -6})`.
A logo is drawn as an `<img>` (no script runs); `inlineLogo` inlines it only after removing
scripts, foreignObject, event handlers and script or external links (each removal is reported).
A wordmark types or slams. The card is a declared rest with a slow push; a `logo_hit` cue (default
-6 dB, near the body's level) and the music stop sit on the lock.

### Caption: a running line in small type
`captions: Caption({sentences: [{text, t0, t1, words: [[word, t], ...]}], size, plate, plateColour, plateAlpha, lift})`.
Screen space, on a plate so it reads on every ground; the current word is highlighted; long lines
split into two balanced lines. Word times are spread by length when not given. film_check.py
exports SRT and WebVTT from the same source.

### Dither: a tone field as an ordered or blue-noise dither
`Dither({field: 'gradient'|'noise'|'image', src, ink, paper, cell: 0.9, pattern: 'bayer'|'blue', angle, speed, still, len, words: {text, role, fact}})`.
Cells are in frame units and fixed to world cells, so the pattern moves with the world or stays
still and never crawls. It warns under 3 px cells. analyse() applies the regular-pattern criteria
(below) to it every frame.

## A film's own device
`kit.block(kind, (ctx, opts) => ({len, update(t), camera(t)?, ground0?, through()?}), {assets})`
defines a block with the same contract (the Atlasfold film's photo-to-map fold is one). `ctx`
offers: `group` and `screenGroup` (world and screen-space parents; `group.add({w, h})` makes a node),
`fitText`, `textNode`, `text({id, role, string, fact, nodes, bg})` to register a text, `cue`, `cut`,
`rest`, `smear`, `fast`, `ground`, `whip`, `shake`, `bump`, `arrive`, `through`, `collapse`, `grow`,
`zoomIn`, `fx.speed/burst/comet/flash/texture`, `track(node, id, {discrete})` for motion checks,
`plate`, `occluder`, `locked(t)` (frame-locked time), `typed(node, chars)`, `rng`, `hash`, `noise1`,
`ease`, `curves`, `token`, `mix`, `typeOn`, `colour`, `frameAt(point, screen, zoom, roll)`, `music`.
Set node properties in `update(t)` only (x, y, s, sx, sy, rot, opacity, blur, reveal, rx, ry...);
the engine resets every node to its `rest()` state before each frame and flushes to the DOM after.

## Motion curves and tokens
Curves: `arrive`, `settle`, `exit`, `camera`, `drift`, `open`, `slam`, `fade` (the only curve for
opacity). Tokens for interface devices: `token(kind, size, distance)` with sizes `micro` 0.09 s,
`small` 0.16, `medium` 0.24, `large` 0.34, `stage` 0.55; exits 0.68 of arrivals; duration grows up to
60% with distance (a fraction of the frame diagonal).

## Hits
`beat` is a quick camera bump; `hit` a bump and one kick (the camera moves out once along a seeded
direction and returns without reversing; an oscillating shake over large type measured as flashing);
`punch` adds a short charge of sparse, thin accent speed lines (0.24 s), a ring, six rays and sparks.
Each punch, fill, slam landing and ground flip off a cut is declared in `changes`.

## Cue rules (applied after the build, each change reported in the warnings)
Same-role cues closer than 120 ms keep the first (the rest of a run is texture); different cues closer
than 60 ms are one gesture and keep the stronger role; nothing sounds on frame 0 unless the cue says
`atZero`. Blocks follow the same rules by design: typing gets one key accent where it starts, a run of
pins one pop, a name's kicker and typed sub line ride on its landing, an end card's tagline on the
logo hit; the end card's silent window starts after the logo hit's ring-out (`ringOut`, 1.6 s).

## Joins in info()
`cuts` lists every hard cut (motion blur never samples across one). `seams` lists the cuts that are
invisible by design (fly-throughs, collapses): the frame is already the next shot there, so a render
shows no large change. `changes` (with spans in `change_windows`) lists designed large changes that
are not cuts: slam landings, fills, punches, the mark landing, ground flips off a cut, cards flying
in. `blanks` lists designed near-empty frames (the end of a dive, a collapse point, a whip arrival).
film_check.py writes all of them to `qa/declared.json`, blanks included in `ignore`. A whip is a
visible cut: give the arriving shot content already in motion; a fast exit into an empty arrival
reads as a drop-out.

## Cue roles
`impact`, `impact_big`, `hit`, `whoosh`, `whoosh_big`, `tick`, `pop`, `key`, `riser` (sync `end`),
`logo_hit`, `glitch`, matching the sound lane's palette. Whips and fly-throughs cue at their apex.

## What analyse() reports
Per text: `in`, `readStart` (every glyph visible: opacity through all ancestors at least 0.98, own
scale within 2% of rest, blur under 0.35 px, inside the safe area, uncovered), `readEnd`, `out`,
`need_s`, `min_font_px`, colour, ground and WCAG contrast (3:1 at 24 px or 18.66 px bold and up,
otherwise 4.5:1). Flashing by flash_scan.py's own method on a small raster of every frame:
the ground, world effects, plates, counter windows, the type itself (whole letters, outlines, blur)
and the screen effect canvases, drawn at three times 192 px wide and area-averaged down, with two
sub-samples inside each frame's exposure (six inside fast and smear windows); windows a third of the
frame on a sixth-of-the-frame grid; 74th and 26th percentiles; a swing of at least 0.10 with the
darker below 0.80, and 20 in the saturated-red amount; more than 6 in any second is an error, 5-6 a
warning. On the first showcase render it predicted 13 and 11 where flash_scan.py measured 13 and 12.
The whole-frame ground series stays as the luminance strip. Truth against facts.json. Motion per tracked
element: jumps (a step over 5x the move's median, 2x both neighbours and 6 px; steps on a designed
bump or shake are counted as `jumps_on_hits`), speed (more than one own width, its larger dimension,
per frame outside smear and fast windows), competing onsets (unrelated elements starting within 2
frames while a text is read), invalid geometry. Regular patterns (Ofcom, Section Two guidance,
Annex 1, 2017): a risk only when more than five light-dark pairs, the darker under 160 cd/m2, a
difference of at least 20 cd/m2 (relative luminance x 100 for a 100 cd/m2 white), and over 40% of
the screen if stationary or 25% if it changes, oscillates or reverses; smooth one-direction flow
(a camera move) is exempt.

## Preview
Open `index.html` over a local server. Keys: space play/pause, `,` `.` one frame, arrows one beat,
0-9 jump to tenths, S safe area, R reading states (amber not yet readable, green readable, red
leaving), L the ground-luminance strip. `?render` hides the UI; `?animatic` adds a time, frame,
bar.beat and scene readout for review notes; `?film=path/film.js` previews another spec.
