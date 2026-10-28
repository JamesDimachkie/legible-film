# Claims and rights

Keeping every claim supported within its stated scope, in words and in pictures, and every asset usable for
its intended purpose.

Contents: [1. The facts file](#1-the-facts-file) · [2. Claim rules](#2-claim-rules) ·
[3. Claims made by pictures](#3-claims-made-by-pictures) · [4. Before release](#4-before-release-or-re-release) ·
[5. Held variants](#5-variants-that-wait-on-an-outside-event) · [6. Rights and provenance](#6-rights-and-provenance) ·
[7. Generated media](#7-generated-media) · [8. Uploads and privacy](#8-uploads-and-privacy)

## 1. The facts file

Every number and factual statement on screen, in narration, in captions, in the thumbnail and in the post copy
comes from `facts.json` ([template](../assets/templates/facts.json)). Each entry records:

- the exact displayed wording, the value and its unit;
- the source (URL or document), the date it was read, and the conditions that change its meaning (hardware,
  sample, tier, date, plan, "illustrative");
- the label shown beside it and any footnote;
- its status: `current`, `dated` (shown with its date or version), or `illustrative`;
- whether it can change before release, and who approved it.

Build the film so it reads displayed facts from this file where the engine allows, so a correction is a
one-place edit.

## 2. Claim rules

Write these into the brief before the build:

- Every on-screen number has a footnote or source, or an "illustrative" label for examples.
- A condition that changes a number's meaning sits next to the number, not only in a footnote.
- No animated count through values that were never measured (no roll from 4.88 to 21.83). A counter may count
  when every intermediate value is real.
- No visual link, motion or arrangement implies a relation or capability the facts do not support.
- Competitors and other authors appear neutrally; the picture never implies their work is the product's.
- New wording of an approved claim is a new claim; check it against the source.
- A dated claim is valid when its date or version is on screen.
- When a client restates a published figure differently, reconcile the two: use the published figure, or the
  client's figure on the client's explicit authority, and tell them what a viewer who checks will find.

## 3. Claims made by pictures

Pictures need the same support as words:

- An object travelling into the product says "this goes into the product". A line joining two things says
  "these are connected". A count of lanes, bars or dots encodes a ratio. "All" and "every" are numbers.
- When a number changes, change the picture that encodes it: replacing "4×" with "6×" in the copy while four
  lanes still race in the picture leaves the film saying 4×.
- Solid markers on real places read as a live network; a sheen across a price reads as an infomercial.
- In demonstrations, keep recorded behaviour and designed illustration distinguishable, and label
  reconstructions ([product-demos](product-demos.md)).
- Generated or photoreal footage is not evidence that a product operation happened.

## 4. Before release or re-release

- Re-read every changeable source and diff it against what the film says: product cards, prices, licences,
  rankings, status pages, documentation. Sources change between a first read and a release, sometimes in the
  same week.
- Check what outside the film must agree with it: the product page, a repository description, the post copy,
  the thumbnail.
- Have an independent reviewer (a fresh context, ideally another model family, or a person) check every
  on-screen string, footnote, voice line and caption against today's sources, and record the result. In one
  documented release this check caught an approved headline that overclaimed after the picture had already
  been corrected.

## 5. Variants that wait on an outside event

When a deliverable depends on an outside event (a merge, a launch, a price, an approval):

- keep the candidate variant clearly held, outside the send-ready folder;
- record the release condition and who confirms it, the source to re-check, the QC still outstanding, and the
  promotion steps;
- if the condition can change while you build, build both variants and check the condition again at the
  moment of delivery.

If the owner releases a variant before its condition holds, that is their decision; use it if a public source
still supports it, and tell them what a checking viewer will find.

## 6. Rights and provenance

Record every asset in `assets.csv` ([template](../assets/templates/assets.csv)): role, file and hash,
source or provider, model or version, creation date, the account plan at creation, the licence or terms URL,
the permitted use, cost, whether private material was uploaded, and approval.

- Check whether a licence depends on creation date, subscription status, distribution, revenue or audience.
  A plan upgrade usually covers new output only; regenerate on the covered plan rather than assuming.
- Fonts: confirm the licence covers embedding in video and distribution; ship the font files with the
  project.
- Music, sound effects, stock footage and images: the licence must cover the platform and the paid or organic
  use.
- Open-source tools have code licences and sometimes separate model-weight licences: Demucs's code is MIT, but
  its maintainer stated on 2026-10-26 that the licence of the pretrained weights is unclear, so treat its
  output as a risk for commercial work.
- Resolve uncertain permissions before delivery, or replace the asset.

## 7. Generated media

Before a paid or hosted generation, confirm: the person's approval and spending cap; the provider and model;
the plan's commercial terms; whether inputs or outputs are used for training; what you will upload. Keep each
take, its prompt, settings, date and cost in the asset register. A prepared request is not a generation
receipt; record what actually ran.

Provider terms change often. As read on 2026-10-27 (re-check before relying on any row):

| Provider | Output ownership and commercial use | Training on your inputs/outputs by default | Source |
|---|---|---|---|
| OpenAI API | rights in output assigned to the user (per terms; page not machine-readable at check time) | API: no, unless you opt in; consumer apps: may be used unless you opt out | [terms](https://openai.com/policies/terms-of-use/); [API data use](https://developers.openai.com/api/docs/guides/your-data) |
| Google Gemini API (incl. image and video models) | Google does not claim ownership; preview products can restrict commercial use | unpaid tier: yes; paid tier: no | [Gemini API terms](https://ai.google.dev/gemini-api/terms) |
| Runway | Runway does not claim ownership of inputs or outputs | yes (no opt-out described in the terms) | [terms](https://runway.com/terms-of-use) |
| Luma | customer owns output; commercial use only for output made during an active subscription | yes | [terms](https://lumalabs.ai/legal/terms-of-service) |
| Adobe Firefly | Adobe claims no ownership; marketed as commercially safe | no: Adobe states it does not train Firefly on user content | [Firefly approach](https://www.adobe.com/ai/overview/firefly/gen-ai-approach.html) |
| ElevenLabs | user retains rights; free plan non-commercial, paid plans commercial | yes, with an opt-out | [terms](https://elevenlabs.io/terms-of-use) |
| Stability AI | rights assigned to the user; community licence free up to USD 1M annual revenue | yes, with an opt-out | [terms](https://stability.ai/terms-of-service) |

## 8. Uploads and privacy

- Private, client or unreleased material goes to a hosted service only with the owner's permission. That
  includes AI frame describers, transcription services, "enhance" and upscaling tools, and video-to-sound
  generators.
- Some tools upload by default when an API key is present (for example a video-understanding skill that sends
  local files to a hosted model when its key is set, or a snapshot command that can send frames to a
  describer). Choose the local mode explicitly for private work.
- Keep real customer data, personal data and credentials out of frames, filenames, project files and logs.
