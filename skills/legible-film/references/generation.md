# Generation: making assets with generative and enhancement tools

How to get professional results from image, video, voice, music and effects generators, and from upscaling,
interpolation, matting and relighting tools. Finding licensed assets is in [assets](assets.md). The gates still
apply: paid generation waits for the person's approval, and private, client or unreleased material goes to a hosted
service only with their permission.

The landscape in §8 was read on vendors' pages on 2026-10-27 and changes month to month. Re-read the current pages
before recommending a tool, and choose by the shot, its rights and the person's data rules, not by brand or a
leaderboard. Where the person or their organisation rules out a provider, keep the requirement and choose an allowed
alternative.

## Contents

1. [Decide what may be generated](#1-decide-what-may-be-generated)
2. [The shot contract](#2-the-shot-contract)
3. [Prompts, references and keyframes](#3-prompts-references-and-keyframes)
4. [Variants, selection and when to stop](#4-variants-selection-and-when-to-stop)
5. [Unify, repair and enhance](#5-unify-repair-and-enhance)
6. [Inspect what you generated](#6-inspect-what-you-generated)
7. [Rights, privacy and disclosure](#7-rights-privacy-and-disclosure)
8. [The landscape on 2026-10-27](#8-the-landscape-on-2026-10-27)
9. [What spending more buys](#9-what-spending-more-buys)

## 1. Decide what may be generated

Classify every shot by what must be exact: a person's identity, packaging, an interface state, a mechanism, words,
data, or only atmosphere. Then give each kind of material its job:

- **Real capture** for evidence and authentic performance.
- **Stock** for an established location or action at a fair price.
- **Generation** for impossible or stylised worlds, atmosphere and exploration.
- **Code-rendered graphics** for exact text, interfaces, charts and data.

Generation is the wrong tool for a literal product demonstration with critical dimensions, marks or behaviour; for
exact interfaces, charts, captions and required copy; and for anything presented as evidence. Generated detail is
never recovered fact. A sustained emotional performance, long continuous geography, fast overlapping hands,
transparent objects, liquids and mirrors are high-risk: plan around such a shot only after a successful test.

## 2. The shot contract

Write a short contract for every generated shot before prompting:

```text
Shot: 04, the product placed beside the speaker
Purpose: establish the object's scale and its matte material
Must preserve: the approved silhouette, badge position and finish
Action: one placement; the hand withdraws
Camera: waist-height medium close-up; slow straight push; level horizon
Light: broad soft key from camera left; restrained edge light
Sound: placement click and room tone; narration supplied separately
Duration: enough handles around the action for the cut
Reject if: the logo changes, contact floats, fingers fuse, the shape bends, an extra cut appears
```

The reject line is decided before any take is seen, so attractive light cannot argue a broken product into the cut.

## 3. Prompts, references and keyframes

- **Describe decisions, not adjectives:** subject and action first, then framing and camera move, lens or depth of
  field, light, environmental motion, style and colour, and sound, each only where it matters. One action and one
  camera idea per shot. "A slow push towards the brushed-metal dial; soft side light; the hand turns it one notch"
  directs; a stack of quality words does not.
- **Leave out** contradictory moves, invented numeric camera precision, several simultaneous transformations, and a
  whole film in one clip. Keep text and logos out of the generated plate and composite them exactly afterwards.
  Phrase positively, as Runway's Gen-4 guide recommends
  ([guide](https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide)), and follow the
  chosen model's own guide.
- **Describe the composition, not empty space.** Asked to leave "a calm darker band for the title", image models tend
  to draw a literal band. Describe what is in each part of the frame, and make room for type in the film itself (a
  tint plate, a crop, a push to one side).
- **Approve a keyframe, then animate it.** For identity and composition that must hold, generate or design an approved
  still first and use image-to-video, describing only the motion. For a set of stills that must match, pass the
  approved first image as the reference for every later one, and keep each output's asset ID beside its file so a
  later edit can reuse it without uploading again.
- **Keep a small reference pack:** neutral product views, a character turnaround, wardrobe, the light and style
  reference and a simple layout. Reuse the originals, never copies of copies, and check every invariant across shots.
- **Start and end frames must agree** on perspective, scale, light, object count and the direction of action. Use
  intermediate keyframes where the model supports them. A match cut between two good shots often beats forcing one
  elaborate transition.
- **Record the recipe:** model and version, route, parameters, prompt, input hashes, seed, output metadata and the
  chosen take. Seeds help experiments; they do not guarantee identity across model updates.
- **Layered stills:** generate one clean background plate with no foreground objects, then each object on its own.
  Prove each cut-out's alpha over light and dark grounds (a painted checkerboard is not transparency), record whether
  it is straight or premultiplied ([studio](studio.md) §7.9), and compose a still to check scale, light direction,
  occlusion and edges before anything moves.
- **Music:** brief on structure from the cue list (the energy shape in plain words, each section change with its
  time, the reading holds where the music must stay steady, the ending, the allowed sources), with reference audio
  per section rather than one reference for the whole piece. Where a take puts a drop the picture does not need, edit
  the music, not the picture. Generators tend to ignore requested sections; ask for extra length and build the
  structure in the edit.
- **Voice:** save a designed voice through the vendor's persistent voice feature (ElevenLabs, for example, creates a
  reusable voice ID from a generated preview: [create a voice](https://elevenlabs.io/docs/api-reference/text-to-voice/create))
  and reuse that ID, model and settings for every line. Generate each pickup with the phrases around it
  ([studio](studio.md) §7.7). Cloning a real person's voice is a separate act that needs their documented consent and a
  route whose terms allow it.
- **Choose photoreal or stylised by the emotional job** (reassure, demonstrate, unsettle). Use photoreal people and
  places only where every behaviour in the shot is physically plausible.

## 4. Variants, selection and when to stop

- Write the selection criteria before reviewing: action clarity, product and identity fidelity, physical
  plausibility, temporal stability, fit with the edit, sound fidelity and rights. Product, identity and rights
  failures are rejections, never a small deduction.
- Work in bounded batches, for example four variants, reviewed side by side. Change one variable at a time once you
  understand the failure.
- When variants fail the same action repeatedly, simplify it, change the camera distance, split it into shots, or
  change medium. Never keep paying because the first frame looks good.
- Track **cost per accepted second of the cut**, not per generated second, and record why each rejected take failed so
  nobody repeats the prompt.
- **Price the whole set before the first paid run.** Most routes quote a run before it starts (a dry run or an
  estimate). Give the person the price of each step and the total for the set (music takes, the effects kit, the
  pictures) and wait for one go. A refused or failed run can still be charged: check the account before running it
  again, and say so.
- **Choose models from the route's current catalogue and schema,** never from memory: read which inputs it takes
  (references, duration, tempo, outputs) and which of them change the price.
- Start a beat at 2-4 usable seconds and lengthen only when the take holds. Trim before drift begins, and cut on
  purposeful action or a sound. Never conceal a defect that changes the product's behaviour, safety or identity.
- Once a take is approved, record its properties (identity, key objects, action, framing, light) in the asset
  register, and check every regenerated replacement against that list before it enters the cut.

## 5. Unify, repair and enhance

**Unify** generated, stock, captured and rendered shots at the sequence level: interpret each source's colour first
(one input transform per source, one output transform), then match exposure, black level, white balance, highlight
roll-off, sharpness and depth cues with scopes, and apply one restrained look ([studio](studio.md) §7.9).
Protect exact interface and text in separate layers. Add grain to unify the finish, never as a claim of photographic
origin, and add motion blur only where motion stays readable. Consistent room tone, foley and transition tails make
separate shots read as one sequence.

**Repair in a deliberate order**, on selected shots with handles, after preserving the originals:

1. Inspect metadata, cadence, colour space and interlacing, and split at cuts.
2. Fix what blocks later work: deinterlacing, cadence and duplicate frames, and restrained noise reduction. A clean
   generated plate may need none.
3. Retime or interpolate at source resolution, never across a cut, flash, interface change or designed hold. Keep the
   audio separate and resynchronise it deliberately.
4. Upscale once, to the delivery size, conservatively. Never chain aggressive "detail" models.
5. Composite and grade, then add final texture, controlled sharpening and grain. Encode a delivery copy and inspect
   it again.

Reduce noise before sharpening or resampling. No small source becomes a real high-resolution capture because the export
is 4K.

Each step needs a real route: the local command, API or app, the model's licence and the hardware it needs. Where
there is none, choose a simpler treatment. A prepared command or a vendor's capability page is not a repair that ran.

## 6. Inspect what you generated

Use the scripts to find suspect frames (`motion_scan.py`, `blank_scan.py`, `flash_scan.py`), then look at every frame
of a short hero shot around contact, mouths, occlusion, cuts, matte changes and its first and last frames:

- hands, finger count, grip and contact; feet and weight transfer;
- faces, teeth, gaze, identity, skin and expression continuity;
- every letter, logo, numeral and interface state, at 100%: generated vehicles, clothing and products often carry a
  real maker's mark;
- object permanence, geometry, reflections, shadows, gravity and material behaviour;
- flicker, crawling texture, jitter, background warping, exposure or colour pumping;
- matte chatter, halos, edge blur and contact shadows;
- spoken words, lip-sync, unintended speech or music, clicks and clipped tails.

A still that the film will push into needs more pixels than the frame: its width at least the frame's width times
the largest zoom. A 2048-px picture cropped to 1.7x leaves about 1,200 source pixels across a 3840-px frame, and it
looks soft.

A contact sheet cannot show smooth motion, and a meter cannot judge a mix: the person's normal-speed viewing is still
required.

## 7. Rights, privacy and disclosure

- **Read the terms for the exact route.** The same model can carry different rights through its own app, its API and
  an aggregator. Check output ownership, commercial use, plan eligibility, revenue thresholds, whether inputs and
  outputs train the vendor's models, watermarks and content credentials, and any indemnity. An indemnity must protect
  the customer for the intended use; a clause making the customer indemnify the vendor is the opposite.
- **Free tiers are often non-commercial,** and some outputs stay non-commercial after upgrading
  ([World Labs terms](https://www.worldlabs.ai/terms-of-service)).
- **Open weights are not unrestricted:** read each checkpoint's licence. Some carry revenue thresholds, branding duties
  or territorial limits (one 3D model's licence excludes the EU, the UK and South Korea:
  [Hunyuan3D-2.1](https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1/blob/main/LICENSE)). Running locally does not make
  a hosted wrapper private.
- **Words that read as removing a mark get refused.** A request that mentions removing a watermark, especially with
  a reference image attached, can be blocked as watermark removal. Say what the scene contains instead ("no text or
  logos in the scene").
- **Automated access:** some services forbid scripted or agent use of their apps
  ([Midjourney terms](https://docs.midjourney.com/hc/en-us/articles/32083055291277-Terms-of-Service)). Use the
  documented API or have the person operate the app.
- **Stock licences can forbid AI processing:** check before uploading a licensed asset to a generator or upscaler.
- **Provenance:** keep visible marks and content credentials, and keep a manifest of which portions are generated,
  stock, captured or rendered, with model, version, date, prompt and licence basis.
- **Disclose** realistic generated or altered people, products, events or behaviour where a viewer could take them as
  evidence, and follow each platform's labelling rules
  ([YouTube disclosure policy](https://support.google.com/youtube/answer/14328491?hl=en-GB)).

## 8. The landscape on 2026-10-27

A starting list of strong options by category, read on the vendors' pages on 2026-10-27; capabilities and prices
change monthly. Before committing, record an authorised route for each candidate (an account, API or local install
the person approves, with its cap) and compare at least two on the actual shot. Where no route is available, compare
from documentation and record the shot's quality as untested.

**Images**

- **OpenAI GPT Image 2.5** (Sunburst for precise edits, Flare for throughput): custom sizes in multiples of 16, from
  1:3 to 3:1, up to 3,840 px a side and 655,360 to 8,294,400 pixels in all, with anything above 2560x1440 marked
  experimental; transparent backgrounds ([guide](https://developers.openai.com/api/docs/guides/image-generation)).
- **Google Nano Banana 2.1**: reference-led compositions and conversational revisions at 1K-4K
  ([pricing](https://ai.google.dev/gemini-api/docs/pricing)).
- **Black Forest Labs FLUX 3 Image and Klein**: layout control with bounding boxes; Klein has open weights under its
  own commercial terms ([FLUX 3](https://bfl.ai/models/flux-3-image)).
- **Midjourney V8.2**: art direction and look development; no automated access under its terms.
- **Ideogram 4.5 and Vector**: typography and genuine SVG output ([Vector](https://ideogram.ai/models/vector/)).
- **Adobe Firefly Image 5** for images, and Illustrator's Text to Vector Graphic for editable vectors
  ([vectors](https://helpx.adobe.com/illustrator/desktop/use-generative-ai/generate-scenes-subjects-and-icons.html));
  Adobe's indemnity covers only eligible plans, features and exports
  ([conditions](https://helpx.adobe.com/legal/product-descriptions/adobe-firefly.html)).

**Video**

- **Google Gemini Omni 1.1 Flash**: conversational generation and editing, extension and interpolation
  ([model](https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash)).
- **Google Veo 3.1**: first and last frames and content credentials, on Google's enterprise platform or a partner
  route; its Gemini API preview endpoints shut down on 2026-10-22 ([video guide](https://ai.google.dev/gemini-api/docs/video)).
- **Runway Gen-4.5, Act-Two and Aleph 2.0**: Act-Two transfers a real performance to a character; Aleph edits and
  relights existing shots ([API pricing](https://docs.dev.runwayml.com/guides/pricing/)).
- **Luma Ray3.2**: up to sixteen keyframes, HDR and 16-bit EXR output for compositing ([Ray](https://lumalabs.ai/ray)).
- **Seedance 2.5**: up to 30 s with audio and rich image, video and audio references
  ([release](https://seed.bytedance.com/en/blog/one-take-creation-flexible-referencing-introducing-seedance-2-5)).
- **Kling 4.0**: long takes with up to ten keyframes ([guide](https://kling.ai/blog/kling-4-ai-video-model)).
- **FLUX 3 Video**: up to ten keyframes, a cheap draft mode that continues into the final
  ([overview](https://help.bfl.ai/articles/7342522296-what-is-flux-3)).
- **HeyGen Video 1**: economical reference-driven scenes with native sound; free output is non-commercial
  ([API](https://www.heygen.com/ai-video-api)).
- **Open weights:** LTX-2.5 ([model card](https://huggingface.co/Lightricks/LTX-2.5/blob/main/README.md)) and MiniMax H3
  ([repository](https://github.com/MiniMax-AI/MiniMax-H3)); at full precision both exceed a typical laptop's GPU
  memory, so check quantisation, offloading, RAM and run time before choosing a local route. Both carry
  revenue-threshold licences.
- **The Sora 2 API is gone:** OpenAI shut down the Videos API and its Sora 2 models on 2026-09-24
  ([deprecations](https://developers.openai.com/api/docs/deprecations)).

**Voice:** ElevenLabs v4 ([models](https://elevenlabs.io/docs/overview/models)), Cartesia Sonic
([pricing](https://www.cartesia.ai/pricing)), Google Gemini 3.8 Flash TTS for directed delivery
([model](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts)), and Chatterbox to run locally under the
MIT licence ([repository](https://github.com/resemble-ai/chatterbox)). Cloning conditions differ by route, so read them
for the one you use. A local model checks nothing, so obtain and record the speaker's consent yourself.

**Music:** Suno v6 grants commercial rights on paid downloads only ([rights](https://help.suno.com/en/articles/9601665));
Eleven Music's self-serve rights exclude film, TV and radio, so check how its terms classify your use
([music terms](https://elevenlabs.io/music-terms)); Google
Lyria 3.5 is cheap for exploration ([guide](https://ai.google.dev/gemini-api/docs/music-generation)); Stable Audio 3
runs locally under a revenue-threshold licence ([licence](https://stability.ai/license)). Udio had disabled downloads
at the time of reading ([notice](https://help.udio.com/en/articles/12683565-changes-associated-with-the-universal-music-group-umg-partnership)).
For exact cue hits, exclusivity or broadcast, a composer or a cleared library is often the better route.

**Sound effects:** ElevenLabs Sound Effects, 0.1-30 s with looping
([docs](https://elevenlabs.io/docs/overview/capabilities/sound-effects)); Adobe Firefly sound effects at 48 kHz; Stable
Audio 3 Small SFX locally. Generate isolated layers (attack, body, tail, ambience) and fit each transient to its frame
in the edit.

**Repair and enhancement**

- **Restoration and upscaling:** Topaz ([pricing](https://www.topazlabs.com/pricing)); DaVinci Resolve Studio's noise
  reduction, SuperScale and Speed Warp ([Studio](https://www.blackmagicdesign.com/products/davinciresolve/studio));
  Neat Video for camera noise; Real-ESRGAN locally ([repository](https://github.com/xinntao/Real-ESRGAN)).
- **Interpolation:** Topaz's models, Resolve Speed Warp, or RIFE locally ([repository](https://github.com/hzwer/ECCV2022-RIFE)).
- **Matting:** After Effects Object Matte and Roto Brush, Resolve Magic Mask, SAM 3 for segmentation masks to refine
  into a soft matte, under its own licence ([repository](https://github.com/facebookresearch/sam3)), and Robust Video
  Matting for people (GPL-3.0).
- **Relighting:** Resolve Relight for modest shaping; Runway Aleph or Beeble where changing image content is
  acceptable.

**3D and scenes:** Meshy and Tripo for props to clean up afterwards; World Labs Marble for explorable environments
([docs](https://docs.worldlabs.ai/marble/models)). Use manufacturer CAD or measured modelling for a hero product.

## 9. What spending more buys

| Spend | Buys | Wasted on |
|---|---|---|
| Nothing new | script, animatic, shot contracts, type, a disciplined edit; local tools where already licensed and feasible | calling local inference free while ignoring setup, using non-commercial tiers for client work |
| About $10-50 | one commercial voice, image or music route, clean keyframes, a few bounded comparisons | several overlapping subscriptions, unused credits, a "Pro" label without the needed rights |
| About $50-200 | more deliberate variants, better references, the right native output format, one restoration or compositing tool | generating every shot at maximum resolution, long clips trimmed to a second, stacked enhancement passes |
| About $200-1,000+ | a controlled hero shoot, CAD cleanup, a specialist colourist, compositor or voice artist, a well-cleared licence | more generations of an action the medium cannot do |
| Contract | indemnity, confidentiality and no-training terms, organisational eligibility, support and capacity | unlimited throughput when the real problem is accuracy or approval |

Account for rejected takes, repairs and review time. Stop buying resolution when a shot still fails on identity,
action or comprehension: the next useful spend is the one that fixes the actual failure.
