# Formats and deliverables

What each kind of piece needs, what to hand over, and the checks particular to it. The brief sets duration,
dimensions, streams and sound; nothing here imposes a length, a music bed or a house look.

Contents: [1. The destination decides](#1-the-destination-decides) · [2. Deliverables and checks by format](#2-deliverables-and-checks-by-format) ·
[3. Other aspect ratios](#3-other-aspect-ratios) · [4. Loops](#4-loops) · [5. GIFs](#5-gifs) ·
[6. Logo stings, intros and outros](#6-logo-stings-intros-and-outros) · [7. Captions](#7-captions) ·
[8. The first frame and the cover](#8-the-first-frame-and-the-cover) · [9. Platform specs](#9-platform-specs-checked-2026-10-27)

## 1. The destination decides

Settle these in the brief before anything is designed:

- **Where it plays and how big.** A launch post on X or LinkedIn autoplays muted in a phone feed about 384 px wide;
  sound is for the people who unmute. A landing-page loop plays muted and repeats. A conference screen is large and
  loud.
- **Whether it must read muted.** In a feed it must: the picture carries the claim, the proof and the invitation.
- **Whether it loops.**
- **The renditions owed:** aspect ratios, a cover still, caption files, alpha versions, a GIF.
- **The deliverable:** one documented feed launch film was 1920x1080 at 60 fps, H.264 High with AAC at 48 kHz,
  delivered with a manifest of hashes, a light review copy and a README for each version.
- **The frame rate:** 60 fps when interface, text or the camera moves, because slow drifts visibly step and quick
  moves judder at 30. Footage keeps the rate it was shot at; GIFs follow §5.

Density sets duration. When a piece feels crammed, lengthen it before squeezing another scene in; when the length is
fixed, take a task out. In one series a post carrying six scenes in 14 seconds became a 24-second piece with one
idea per bar, and every scene then had room to land.

## 2. Deliverables and checks by format

| Format | Usually delivered | Checks particular to it |
|---|---|---|
| Launch or announcement film (often 30-90 s for a feed) | the master; renditions for each feed it will post to; a cover still; a caption file if anyone speaks | a muted pass at feed size; the product name and its practical fact (date, URL, "available now") readable on the closing card; changeable claims re-read on release day |
| Product or feature demo | the master; a cover still | one capability shown as trigger, response and result; the feature named where a viewer could search for it; demo states consistent in every frame ([product-demos](product-demos.md)) |
| Release or update clip | the master | the new behaviour shown rather than described; the version or date on the closing card |
| Landing-page loop | MP4 and WebM; a cover still (usually frame 0); a GIF if asked | the seam on the delivered file (`motion_scan.py --loop`); frame 0 composed and identifiable; the file size the page can afford |
| Logo sting, intro or outro | the master; alpha version(s); stills of the mark | the hit lands on the lock; the tail decays to silence; the logo holds long enough to read; alpha checked over light and dark |
| Explainer or walkthrough | the master; a caption sidecar; a chapter list when long | every step's text inside its reading window; captions agree with any burned-in text |
| Talking head or interview edit | the master; a caption sidecar | eyelines and screen direction across cuts; jump cuts consistent when intended; speech clear over music |
| Screen-recording tutorial | the master; a caption sidecar | the cursor and viewport easy to follow; no private data in any frame |
| Social cut-down | one rendition per destination | each cut ends where a sentence or a musical phrase ends; composed for its own frame |

## 3. Other aspect ratios

- Compose each aspect ratio for its own frame, driven by the same timeline so the soundtrack and cue list carry over
  unchanged. A centre slice of a wide master shrinks the product and wastes most of a tall frame, and a wide film
  letterboxed inside a tall one wastes even more. The film kit lays its blocks out in frame units, so one timeline
  renders 16:9, 9:16 and 1:1 ([kit](kit.md)).
- A rendition with its own length or story (a 15 s cut-down of a 60 s film) gets its own timeline, cue list and mix;
  one timeline serves only renditions that share the story and the length.
- In a tall frame, stack the composition and bring the camera closer to the region that matters.
- Decide line breaks for each rendition in the copy itself, not by wherever a box happens to wrap.
- Keep text and essential interface clear of the platform's own overlays (names, captions, buttons). For Instagram
  Reels ads, Meta's ads guide asks advertisers to keep roughly the top 14%, the bottom 35% and 6% at each side free
  of text and logos. Overlays change often; read the current guidance and note the date you read it.

## 4. Loops

- Measure the jump from the final frame into frame 0 against the frame-to-frame changes either side of it: identity, position, velocity,
  lighting and any sound must all carry on. Matching images at the two ends can still hide a pause or a change of
  speed. `motion_scan.py --loop` measures this on the delivered file.
- The last frame should lead into frame 0 the way any frame leads into the next. A loop that ends on a copy of frame 0
  shows that pose twice and hitches on every pass.
- With music, make the loop a whole number of bars so picture and sound come round together, and let the sound run
  on through the join instead of fading out at the end of each pass.
- On a web page, use an MP4 and a WebM in a `<video autoplay muted loop playsinline>` element, with frame 0 as the
  poster.

## 5. GIFs

GIF stores each frame's display time in hundredths of a second. At 25 fps a frame lasts exactly 4/100 s, and at
50 fps exactly 2/100 s, so every frame gets the same delay. 30 fps would need 3.33/100 s, so encoders alternate
3/100 and 4/100 to keep the average, which spaces the frames unevenly. Export GIFs at 25 or 50 fps from the master,
with a palette generated for the clip ([ffmpeg-cookbook](ffmpeg-cookbook.md#encode)), and check the encoded
duration.

## 6. Logo stings, intros and outros

- Let the viewer see the mark come together, and build a wordmark from whole letters; partial letterforms mid-build
  read as a rendering fault.
- The logo holds, fully formed and at a readable size, long enough to be read before the end.
- The sound is usually one hit on the moment the mark locks, with a tail that dies away to silence; add a music bed
  only when asked.
- When the sting will sit over other footage, deliver it with alpha: ProRes 4444 for editors and VP9 WebM for
  browsers. The composition must not paint a background of its own: check that frame 0 is transparent, and look at
  stills over a light and a dark background to check shadows and fine lines.
- Verified on FFmpeg 9.0.2: ffprobe reported a ProRes 4444 file encoded as `yuva444p10le` as `yuva444p12le`, and a VP9
  alpha WebM as `yuv420p` with `alpha_mode=1`. Both are expected readings, not faults.

## 7. Captions

- Ship captions as a sidecar file (SRT or WebVTT) for every piece with speech; WCAG 1.2.2 asks for captions on
  prerecorded web video.
- When captions are also burned in for muted feeds, generate both from one caption source so their timings cannot
  drift apart, and compare them.
- In a tall crop of a wide talking head the face fills the middle of the frame (about 20-67% of the height in one test
  1080x1920 cut) and the platform's own text covers the bottom. Put burned captions between the chin and the bottom
  overlay zone, in short lines, over a plate when the ground is busy. When no position clears both the mouth and the
  overlays, keep the mouth clear, record the conflict as the weakest point, and check it on the platform's preview.
- A transcript from a speech model is a first draft. Time it to the reading limits in [timing](timing.md), then have a
  named person check every caption against the audio, names and numbers first; a second model's transcript is a
  comparison, not that check.

## 8. The first frame and the cover

- The first frame works as a cover, because some feeds show it before play: the name with a one-line definition, or
  the problem mid-action.
- Suggest a cover frame to the person when the title card is not the strongest frame of the film.
- Make the cover still from a lossless frame carrying the same finish as the master, or from the master itself, and
  check its text and colour at full size; a pre-finish snapshot is not the delivered cover.

## 9. Platform specs (checked 2026-10-27)

Platforms change limits without notice; re-read the page before relying on a number.

| Platform | What the official page says | Source |
|---|---|---|
| YouTube | MP4 with the moov atom at the front; H.264 High, progressive, 4:2:0, BT.709 for SDR; AAC-LC 48 kHz; upload at the recorded frame rate; SDR guidance about 8 Mbps for 1080p at 24-30 fps and 12 Mbps at 48-60 fps | [YouTube help](https://support.google.com/youtube/answer/1722171) |
| LinkedIn (ads) | MP4; 75 KB-500 MB; 3 s-30 min (15-30 s recommended); 16:9, 1:1, 4:5 and 9:16; under 30 fps; H.264 or VP8 with AAC or MPEG-4 audio | [LinkedIn help](https://www.linkedin.com/help/lms/answer/a424737) |
| Instagram Reels (ads) | 9:16; 1440x2560 recommended; up to 15 min and 4 GB; H.264, square pixels, fixed frame rate, progressive; stereo AAC at 128 kbps or more; the safe zones in §3 | [Meta ads guide](https://www.facebook.com/business/ads-guide/update/video/instagram-reels) |
| TikTok (in-feed ads, non-Spark) | 9:16 recommended at 540x960 or more; up to 10 min and 500 MB; at least 516 kbps | [TikTok ads help](https://ads.tiktok.com/resources/help/article/tiktok-auction-in-feed-ads) |
| X | the help pages could not be read at check time, and third-party figures conflict | [X help](https://help.x.com) |

Organic (non-ad) limits are not published consistently. Without a current official figure, deliver a conservative
master: H.264 High, `yuv420p`, BT.709 tags, AAC 48 kHz, 1080 lines, 60 fps or less, fast start, and a moderate
bitrate inside the platform's file-size limit.
