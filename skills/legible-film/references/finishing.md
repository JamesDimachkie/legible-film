# Render, finish and mux

From a composition or edit to the delivered file: render custody, frame rate and motion blur, colour, encoding,
audio, and the delivery package. Commands are in [ffmpeg-cookbook](ffmpeg-cookbook.md).

Contents: [1. Render custody](#1-render-custody) · [2. Frame rate and motion blur](#2-frame-rate-and-motion-blur) ·
[3. Colour](#3-colour-convert-then-tag-then-verify) · [4. Encoding](#4-encoding) · [5. Banding, grain and finishes](#5-banding-grain-and-finishes) ·
[6. Audio and mux](#6-audio-and-mux) · [7. The delivery package](#7-the-delivery-package)

## 1. Render custody

- Render from a frozen copy of the source (or a bundle frozen at the render's start), so edits during a long
  render cannot reach it. Record the copy's file hashes, the tool versions and the settings beside the output.
- Render a short window around the riskiest moment first; render the whole film only when stills and the
  window pass.
- Version every export (`film-v7.mp4`) and never overwrite one; reviewers compare versions.
- One heavy render at a time, with free memory checked before starting. Give output paths as absolute paths
  when a script changes directory.
- Keep the editable project; the export is not the source.

## 2. Frame rate and motion blur

- Use 60 fps when interface elements, text or the camera travel: lower rates make interface motion judder and slow
  drifts visibly step.
  Match footage to its recorded rate. The delivery spec wins.
- GIF timing is stored in hundredths of a second, so only some rates are exact; export GIFs at 25 or 50 fps
  ([formats](formats.md#5-gifs)).
- **Fast flips and hard state changes:** blending frames to reach the delivery rate shows doubled images.
  Rendering at twice the rate and keeping every second frame keeps them sharp; averaging pairs gives a
  two-sample blur, which suits motion but not hard switches.
- **True motion blur by sub-frame accumulation:** render several samples per output frame at fractional times
  spread evenly across a shutter centred on the frame (a 180° shutter is the film convention), average them at
  float or 16-bit precision, and quantise once, straight to the delivery pixel format. Record whether you averaged
  gamma-encoded values or linear light; bright streaks on dark grounds look dimmer in the first. It costs roughly
  the number of samples in render time, so iterate on sharp previews and leave the blurred master until the cut is
  approved. Rules:
  - space samples a few pixels apart along the fastest movement, so an edge fades instead of stamping copies;
    frames with no fast motion need no extra samples;
  - a hard cut inside an accumulated range blends two shots into one double exposure: treat every cut as a shot
    boundary and keep each frame's samples inside its own shot. Slide the window to its own side of the cut rather
    than cutting it short: the frame just before a whip's cut is its fastest, and a truncated window leaves exactly
    that frame sharp;
  - a whip can take a longer shutter than the rest of the film (several times 180°) for a long-exposure smear;
    declare it as a window around the whip, and spend extra samples only inside such fast windows;
  - discrete state (text, counts, carets, layout switches) and any grain are computed from the whole frame number,
    so every sample of one output frame agrees;
  - an element that crosses many times its own size per frame smears into stepped copies however many samples you
    take: redesign the move;
  - after the render, inspect the frames with the most movement at full resolution.

  `film_render.py` does all of this for a film made with the kit, averaging in linear light by default and encoding
  with the colour path in §3. For any other engine, render at a whole multiple of the delivery rate and let
  `motion_blur.py` accumulate the frames with the same rules, given the cut list.

## 3. Colour: convert, then tag, then verify

Colour tags describe the pixels; they do not convert them. Browser and HTML renders produce RGB frames, and the
RGB-to-YUV conversion decides the stored values. Players then decode using the tags, and they disagree about
untagged video: one 2020 vendor test found Safari assuming BT.601, Firefox BT.709, and Chrome's assumption
varying with resolution and hardware acceleration.

Verified on FFmpeg 9.0.2 (2026-10-27), encoding a flat RGB patch (48,128,192) to H.264:

| Pipeline | Stored values | Decoded using the file's tags |
|---|---|---|
| default conversion, then tagged BT.709 | BT.601 values | **39,123,195** (shifted) |
| `scale=out_color_matrix=bt709:out_range=tv`, then tagged BT.709 | BT.709 values | 46,127,191 (rounding only) |
| colour-tagged frames converted afterwards | BT.709 values | 46,127,191 |

Also verified: setting `-color_primaries`, `-color_trc` and `-colorspace` as output options alone left the
primaries and transfer untagged on this FFmpeg version.

So, for HD SDR delivery:

1. Convert with an explicit matrix and range: `scale=out_color_matrix=bt709:out_range=tv,format=yuv420p`.
2. Tag in the filter graph: `setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv`
   (or the encoder's own VUI options).
3. Verify: `qc_file.py --color bt709` for the tags, and `--color-patch` on a flat brand-coloured region for the
   pixels. To fix tags on an existing H.264 file without re-encoding, use the `h264_metadata` bitstream filter
   (`hevc_metadata` for HEVC).

Dark tints are flattened by 8-bit 4:2:0 encoding; judge exact dark brand colours on the encoded file.

## 4. Encoding

- Default master for the web: H.264 High profile, 8-bit `yuv420p`, progressive, BT.709 tags, closed GOP, the
  `moov` atom at the front (`-movflags +faststart`), AAC-LC 48 kHz. YouTube's recommended upload settings ask
  for exactly this kind of file (H.264 High, 4:2:0, BT.709 for SDR, fast start; about 8 Mbps for 1080p at
  24-30 fps and 12 Mbps at 48-60 fps as minimum guidance).
- 4:2:2 and 4:4:4 H.264, and some HEVC variants, fail in browsers, phones or QuickTime; deliver them only when
  the spec asks.
- **Set the H.264 level, then check it.** A hardware decoder plays streams up to the level it was built for, and a
  device's specification names that level. x264 otherwise picks the level the stream needs, and slower presets use
  more reference frames: on FFmpeg 9.0.2 a 2160p60 encode signalled level 5.2 with `-preset slow` but 6.0 with
  `slower` and `veryslow`, while `-level 5.2` kept all three at 5.2. Pass `-level 4.2` for 1080p60 and `5.2` for
  2160p60 unless the spec says otherwise, and verify with `qc_file.py --max-level`.
- Alpha deliverables: ProRes 4444 (`.mov`) for editors, VP9 WebM with alpha for browsers. Check the alpha
  channel itself; a page background is not always captured as opaque.
- A seamless loop survives encoding better from a lossless intermediate (PNG sequence) encoded once; check the
  seam on the encoded file (`motion_scan.py --loop`).
- A lossless capture followed by one delivery encode avoids stacking lossy generations; trial it on a short
  window (disk use, frame count, alpha, colour) before adopting it for a pipeline.
- Platforms re-encode uploads. Deliver a high-quality master within the platform's limits rather than a file
  pre-compressed to a small size.

## 5. Banding, grain and finishes

- Smooth dark gradients band after 8-bit lossy encoding. Ship gradients as dithered images rather than CSS
  gradients where possible, and test the encoded result. To see banding that normal viewing hides, stretch the
  contrast of a still around its median; the stretch locates bands but overstates how visible they are.
- Dither only where there is a smooth ramp. A flat field rounded to one code value encodes cleanly; a flat field
  carrying a fixed dither pattern can come out of the encoder as shifting blocks and streaks, different every frame.
- Ten-bit masters band least and suit material that will be graded again; most browsers and phones play 8-bit
  `yuv420p` most reliably, so deliver that to the web.
- Fine grain or dither can mask banding, but a platform's re-encode may remove light noise; test with a
  platform-like re-encode before adopting grain, and apply it globally rather than per element.
- A finish that blends layers (bloom, screen, glow) must run on RGB frames: convert with `format=gbrp` before
  the blend. Blending on YUV planes once turned every frame of a deliverable purple; a pixel check of the
  centre of the frame against the raw render catches it.

## 6. Audio and mux

- Master the mix separately (WAV, 48 kHz), then mux it onto the finished picture, copying the video stream
  where possible.
- Match audio length to picture length explicitly: pad or trim the master to the intended picture duration.
  Relying on `-shortest` with a short soundtrack truncated a 4.0 s picture to 94 of its 120 frames in a test on
  FFmpeg 9.0.2; `apad` plus `-t` set to the picture duration gave exactly 120 frames
  ([ffmpeg-cookbook](ffmpeg-cookbook.md#mux)).
- Encode AAC-LC at 48 kHz and a generous bitrate (192-320 kbps for stereo); measure true peak on the encoded
  file and after a simulated platform re-encode (`qc_file.py --lossy-check`).
- After muxing, check the delivered audio against the approved master (`sync_check.py`). A limiter's
  look-ahead or an encoder's priming can shift audio by a millisecond or more; a constant small lag is
  transport, a changing lag is drift or an edit.
- A silent deliverable has no audio stream at all (`qc_file.py --audio none`), unless the platform needs a
  silent track.

## 7. The delivery package

- `deliver/` holds what the recipient asked for (each rendition, alpha versions, the cover still, caption files),
  each with its manifest, plus the README for the version; reports, sheets and logs live in `qa/`, so the folder
  reads cleanly to whoever opens it first.
- A manifest per deliverable: file name, SHA-256, size, codec settings, source version and input hashes.
- The delivery report ([template](../assets/templates/delivery-report.md)).
- A light review copy (lower bitrate, same picture and sound) for quick sharing stays out of the delivery
  folder. Give it the same colour tags as the master and check them, or people judge colour on a different picture.
- A late fix to one shot need not mean rendering the whole film again: rendering that shot and joining it at a cut
  or a still frame works when both parts share identical codec settings and closed GOPs (FFmpeg concat with stream
  copy). Mux the audio once afterwards, and run the QC battery across the join.
- A cover or poster still comes from a lossless frame with the same finish as the master, or from the master
  itself; check its text and colour at full size.
- Each aspect ratio is its own composition of the same timeline ([formats](formats.md#3-other-aspect-ratios)).
- Captions ship as sidecar files (SRT or WebVTT) and, where the platform needs them, burned in on a separate
  rendition.
