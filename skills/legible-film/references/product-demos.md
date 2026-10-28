# Product demos

Showing a product doing something, truthfully and readably: its distinguishing behaviour, demo states that agree
with each other, an interface the viewer can read, and a clear line between recording and reconstruction.

Contents: [1. The distinguishing behaviour](#1-show-the-distinguishing-behaviour) · [2. One data model](#2-one-data-model-with-asserts) ·
[3. Trigger, response, result](#3-trigger-response-result) · [4. Framing the interface](#4-framing-the-interface-to-be-read) ·
[5. Recording or reconstruction](#5-recording-or-reconstruction) · [6. Real interface code](#6-real-interface-code-in-a-composition) ·
[7. Data and privacy](#7-data-and-privacy)

## 1. Show the distinguishing behaviour

- State what the viewer should understand, the product behaviour that demonstrates it, and the visual rule that
  connects the shots.
- Show what the product does beyond the obvious version: how it resolves a conflict, ranks a result, or changes only
  the relevant records. A polished tour of generic screens proves nothing about this product.
- Make the product identifiable: enough real interface that a stranger knows what it is, and the feature named
  once, where a viewer could search for it (a label in the interface, a line of copy, or the closing card).
- The payoff is the consequence for a person, not the feature's name.
- Muted test: with the sound off, can a viewer follow cause, action and result, and say whose product it is?

## 2. One data model with asserts

Derive every label, count, position and before/after state from one data module, with stable IDs for records that
move between states. Then assert, in code, the relations the story depends on:

- totals equal their rows; parts add up to the whole; a stated ratio matches the numbers beside it;
- a ranked or sorted list is actually in order; statuses match the actions shown;
- dates, weekdays, plurals and units agree ("1 task", "2 tasks"; "No results" rather than "0 results");
- records outside the operation stay unchanged, and nothing that already happened is rewritten by the product's
  action;
- one figure does not appear twice in a frame with two meanings.

They must hold throughout, including mid-transition: a total sitting over a half-updated list is a false number
for every frame it is visible. Pause anywhere, and the frame should be a true screenshot of the story at that
moment. Internal consistency still does not make a real product claim; recorded behaviour and designed illustration
stay distinguishable.

Proof every string before review: one casing for the product name, typographic punctuation, one time and currency
format, thousands separators, and no leftovers (placeholder names, "lorem", "TODO", "1 items"). Keep every on-screen
string in one copy or data file, so the proofing pass and the facts check can see all of it. Invented people and
companies are plausibly fictional and never real.

## 3. Trigger, response, result

- Stage a visible trigger, the product's response, and a readable result, in that order.
- The cursor arrives before the click, and the response follows the product's real interaction contract.
- Counters and statuses change on the frame their cause lands.
- A value that changes should change cleanly (roll its digits, or cut); two numbers dissolving into each other in
  one place are unreadable while they overlap.
- Keep moving elements off text while it is being read: give them their own lanes, or keep the text on top, and
  look at the busiest frames at full resolution to be sure.
- Compressed time and unexplained waits imply speed. Keep measured waits at real time, or label the compression.
- Type at a pace a person could read; for long strings, reveal by word.

## 4. Framing the interface to be read

- Push in on the interaction that carries the story until it reads at viewing size, and keep wide shots of dense
  interface short.
- Frame the region that matters. Half-empty grids and tables cut off at the frame edge look like a spreadsheet,
  and a spreadsheet says nothing about this product.
- Recompose for each rendition: a vertical cut gets its own framing of the same states, not a crop
  ([formats](formats.md)).
- Interface strings count toward what the viewer must read whenever the story depends on them.
- Screenshots and recordings are valid when they serve the demonstration; there is no requirement to rebuild a real
  interface. A static screenshot cannot change state, so it rarely carries the main moment alone.

## 5. Recording or reconstruction

| Source | Strength | Watch for |
|---|---|---|
| Recording of the real product | evidence of real behaviour | private data on screen; timing set by the machine, network and load |
| Scripted capture (browser automation) | repeatable, controllable | real-time capture is not frame-accurate; check timestamps ([engines](engines.md)) |
| Reconstruction from the product's own interface code | exact, editable, deterministic | label it; keep its behaviour consistent with the product |
| Illustration or concept | clarity for invisible processes | label it; no implied capability or measurement |

When the real behaviour is what must be proved, record it with permitted test data, or verify a labelled
reconstruction against the product before making the claim.

## 6. Real interface code in a composition

Rendering the product's own components inside an HTML composition keeps the interface exact and editable:

- Vendor the product's web folder at a known commit and import its pure render functions and stylesheets as
  modules; its own CSS draws it exactly and carries its own fonts.
- The product's media queries follow the composition's viewport (often 1920 px wide), so a phone layout drawn in a
  small box still gets the desktop layout. Render phone states separately at a phone viewport and composite them as
  images, or render a narrower desktop layout and scale it.
- Hiding a grid column with `display: none` can push the next item into the empty first column; pin it explicitly.
- Inside a scaled host, measured element boxes are in scaled pixels while animated sizes may be in layout pixels;
  convert before using one for the other.
- To aim a camera at the interface, build every other animation first, seek to each shot's moment, measure the
  target, then add the camera moves.

## 7. Data and privacy

- Use synthetic or sanitised records, labelled as illustrative where they could be mistaken for real customers or
  results.
- Real customer data, personal data, credentials and internal documents stay out of the film and out of any hosted
  tool used to make it.
- Real names on screen need permission.
