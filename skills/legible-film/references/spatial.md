# Spatial layers: pins, titles behind people, tracked blurs

A plain overlay is a flat picture at a fixed place. A spatial layer is a file that says, for every frame of a
source, where something is in that frame: a tracked surface (a screen, a sign, a product face), a tracked point, or
a matte (which pixels belong to a person). The assembler reads layers to pin a graphic or title to a moving surface,
to put a title behind a person, and to blur a moving face or number plate.

The durable part is the data, not the method: a layer is a readable file on the source's own clock, bound to the
exact source file it was made from, with its method and measured quality recorded. Any tool that writes the
contract below can feed the assembler.

Contents: [1. Commands](#1-commands) · [2. The paper edit](#2-the-paper-edit) · [3. The layer file](#3-the-layer-file) ·
[4. How layers are drawn](#4-how-layers-are-drawn) · [5. What it proves](#5-what-it-proves-and-does-not) ·
[6. Recipes](#6-recipes) · [7. Measured](#7-measured)

## 1. Commands

| Command | What it does |
|---|---|
| `track.py SOURCE --at TIME --region x,y,w,h --name NAME --project P [--from T1 --to T2]` | Tracks a flat surface from a key frame, forward and backward, and writes `spatial/NAME.json`. `--region` also takes four corners (`x1,y1,...,x4,y4`, clockwise from top left), in displayed pixels or as fractions. The range defaults to 5 s either side of `--at`. |
| `track.py SOURCE --at TIME --point x,y --name NAME --project P` | Follows one point that only moves (no turn or scale): for a label or a blur that follows something. |
| `matte.py ...` | Writes matte layers (key, luma, difference, a subject model); see its `--help`. |
| `spatial.py show LAYER.json` | What a layer is: kind, source, range, method, measured quality, current or stale. |
| `spatial.py check LAYER.json [--verify]` | Exit 1 when the layer is stale, a source frame in its range has no layer frame, its times are out of order, or its frames do not match the source's displayed size. `--verify` hashes the source and data files. |
| `cut.py check PROJECT` | Reports, on the film.md line, a missing layer, a layer of the wrong kind, a stale layer, a layer made from another source than the one on screen, and frames it is drawn over that are lost or outside its range. |

`track.py` needs OpenCV (`opencv-python`, installed by `setup.py --install spatial`) and no model or
download. Without it the script says how to install it and exits 2. `SOURCE` is a file, or an alias with
`--project`. Pick the key frame and region from a still (`frame_sheet.py SOURCE --at TIME --width 1280`): the tile is
the displayed frame (after rotation and pixel aspect), scaled. Give `--region` and `--point` as fractions of the tile
(each x divided by the tile's width, each y by its height), which mean the same at any size; whole numbers are
pixels of the source's displayed frame, so a tile's pixels must first be scaled by the source width over the tile
width (a 1280-wide tile of 3840-wide footage: times 3).

Exit codes: `track.py` exits 0 when every frame tracked, 1 when frames are lost or the worst frame error is over
2 px (look at them), 2 when it cannot run.

## 2. The paper edit

```markdown
> int_01 0:12.00-0:16.40 We built it in six weeks.
  ~ title "Six weeks" 2.0 center behind subject
- broll_03 0:41.00-0:46.00 The dashboard on the laptop
  ~ still logo_01 3.0 pin screen
  ~ title "Live in 40 cities" 2.0 pin screen +1.0
- broll_07 0:02.00-0:06.00 Street, a parked car
  ~ blur plate
```

- `behind NAME` (on a title, or a `~ still` image): the title is drawn, then the matte `spatial/NAME.json` puts the
  person's pixels back over it, so the person stays in front.
- `pin NAME` (on a title, or a `~ still` image): the picture is mapped onto the tracked surface every frame, with a
  perspective warp and antialiased edges. A title pinned this way is cut to its text and fills the surface; an
  image keeps its proportions inside the surface (letterboxed, never stretched). On a point track, or with
  `pin NAME follow`, the picture moves (and, on a region track, scales) with the track instead; a followed still is
  centred on the point at a quarter of the frame's width.
- `~ blur NAME [SECONDS] [+N]`: blurs the region a track or matte follows, padded, for the line above (or SECONDS of
  it, starting +N into it). A blur covers the region under every title and graphic, and is part of any frame a
  `pause hold` freezes.
- A `~ still` with `pin` or `behind` is an image drawn over the line's picture, not a cutaway; it needs an image
  source.

`cut.py render` writes these into `edit.json` with the layer's path from the version folder; it copies no layer
data into the version. `manifest.json` lists each layer the version used with the SHA-256 of its sidecar (and of a
matte's data file), its source identity, range and method, so an old version can be explained after a layer is made
again.

In `edit.json` (for a quick edit, written by hand):

```json
{"kind": "image", "src": "logo", "from": 1.0, "to": 4.0, "x": 0, "y": 0, "w": 0.25,
 "pin": {"layer": "spatial/screen.json", "fit": "corners", "aspect": "keep"}}
{"kind": "image", "src": "title-01", "from": 0.0, "to": 2.0, "x": 0, "y": 0, "w": 1.0,
 "behind": {"layer": "spatial/subject.json"}}
{"kind": "blur", "region": {"layer": "spatial/plate.json"}, "from": 2.0, "to": 6.0, "strength": 0.04, "pad": 0.15}
```

`fit` is `corners` (the default) or `follow`; `aspect` is `keep` (the default) or `stretch` (the image's corners go
exactly on the surface's corners). Follow moves the overlay from where `x`, `y` place it on its first drawn frame,
or centres it on the track when `"offset": [dx, dy]` (fractions of the output) is given. A blur's `strength` is its
radius as a share of the output height (default 0.04); `pad` grows the region by that share of its size on each side
(default 0.15); `size` sets the square a point track's blur covers (default 0.15 of the output height). An overlay
may combine `pin` and `behind`. In a version folder the layer path is relative to `edit.json`
(`../../spatial/NAME.json`); a source that a layer binds to carries the map's `sha256` and `bytes`.

## 3. The layer file

A layer lives at `spatial/NAME.json` in the project (NAME is lowercase letters, digits and hyphens), with a matte's
data file beside it; for a quick edit with no project, beside the output.

```json
{"version": 1, "kind": "track",
 "source": {"alias": "broll_03", "file": "../media/laptop.mp4", "size": 123456789, "sha256": "…",
            "video_stream": 0, "origin_s": 0.0,
            "display": {"rotation_degrees": 90, "sample_aspect_ratio": "1", "coded_size": [1920, 1080]}},
 "frame_size": [1080, 1920],
 "clock": "source", "times": [41.0, 41.033367, 41.066733],
 "frames": [{"state": "key", "corners": [[0.31, 0.42], [0.66, 0.40], [0.67, 0.61], [0.30, 0.63]], "error_px": 0.0},
            {"state": "tracked", "corners": [[0.31, 0.42], [0.66, 0.40], [0.67, 0.61], [0.30, 0.62]],
             "error_px": 0.41},
            {"state": "lost"}],
 "method": {"tool": "track.py", "backend": "opencv", "opencv": "4.13.0", "mode": "region", "params": {}},
 "quality": {"frames": 3, "tracked": 2, "lost": 1, "error_px_median": 0.41, "error_px_worst": 0.41,
             "drift_px": 0.3},
 "made": "2026-10-31T09:00:00Z"}
```

```json
{"version": 1, "kind": "matte", "source": {"…": "as above"}, "frame_size": [1920, 1080],
 "clock": "source", "times": [12.0, 12.04, 12.08],
 "data": "subject.matte.mkv", "data_sha256": "…", "data_frames": 3,
 "method": {"tool": "matte.py", "backend": "modnet", "model": "…", "licence": "Apache-2.0", "params": {}},
 "quality": {"flicker": 0.004, "coverage": [0.18, 0.31]}}
```

- `kind`: `track` or `matte`. `depth` is reserved for a later version and refused today.
- `source` binds the layer to one file and one video stream: `alias` (when the source is in the map; null
  otherwise), `file` (relative to the sidecar's folder, absolute on another drive), `size` and `sha256` (the map's
  registered values for a mapped source, so checking a layer does not hash a large file again; `cut.py render`
  still verifies the source itself), `video_stream` (the
  absolute ffprobe index of the picture stream; not the map's sound stream), `origin_s` (the file's format start
  time, which the assembler subtracts from every presentation time) and `display` (the rotation, pixel aspect and
  coded size the frame size came from).
- `frame_size` is the displayed frame: after the file's rotation, in square pixels. Every coordinate is a fraction
  of it, with the top-left corner of the picture at 0, 0 and pixel edges on whole pixels. Corners may fall outside
  0-1 (a surface partly out of frame).
- `times` is the only clock: the exact decoded presentation time of each layer frame, in order, in seconds on the
  clock `assemble.py` uses (the same decoder, the format start time subtracted; [footage](footage.md)). Frame `i`
  of `frames`, or of a matte's data file, is the source frame shown at `times[i]`. Track frames carry no time of
  their own.
- Track frames: `state` is `key` (where a person or agent set the region), `tracked` or `lost`. A tracked or key
  frame has `corners` (a region: top-left, top-right, bottom-right, bottom-left of the surface) or `point` (a point
  track), never both kinds in one layer; a lost frame has neither: nothing is invented where the fit failed.
  `error_px` is the frame's measured error in displayed pixels (below).
- Mattes: `data` is an FFV1 video (`.mkv`) of `gray` frames at `frame_size`, 255 foreground and 0 background, stored
  exactly (0 and 255 survive; no limited-range squeeze). Its frames are matched to `times` by their order in the
  file, decoded with passthrough timing, never by the MKV's own timestamps. `data_sha256` and `data_frames` record
  the data file the sidecar was written with.
- `quality` holds what was measured, named and with units, and never a claim beyond it.

**Current or stale.** A layer is stale, and is not drawn, when its source file changed (its size differs from the
map's, or the map was made again from other media), when the source's picture stream, displayed size or start time
differs from the layer's, when it was made from a proxy, or when a matte's data file is missing. Status and renders
compare sizes and the map's hash; `spatial.py check --verify` hashes the files.

**Finding a layer frame.** `spatial.frame_index` takes, for a source time, the last layer frame at or before it, within
half of the local frame interval (variable frame rates included); there is no layer outside its range. The assembler
does not look up by time: it takes the source frame the renderer chose for each output frame and uses the layer
frame with that same presentation time.

## 4. How layers are drawn

- **Through the renderer's own framing.** Each layer frame is placed by the same functions that place the picture:
  the frame choice (`clip_sample`), the crop, zoom, fit, reframe path and letterbox (`clip_framing`), and the
  source's rotation and pixel aspect, which the decoded frame already carries. A preview proxy is bound by the map's
  identity of the original and scaled with it.
- **One clip at a time.** A layer is bound to each use of its source: a repeated source, a cutaway and each side of a
  dissolve have their own clock. A pin or `behind` is drawn only while a single shot of its own source is on screen.
  Under a cutaway from another source, during a dissolve or dip, on a held frame (`pause hold`), on a lost frame,
  outside the layer's range or with a stale layer, it is not drawn, and the version's notes say where and why.
  Before rendering, `cut.py check` warns when the layer's source is on screen for only part of the overlay, or the
  layer is lost or out of range on frames it covers, and refuses a stale layer.
- **Retimes.** Under `blend` or `motion` retiming there is no single source frame: track corners are interpolated
  between the two tracked frames around the moment, mattes take the nearer frame, and the notes ask for a look.
- **Blur fails closed.** A blur covers its padded region on every frame where its source is on screen, including
  both sides of a dissolve, before any title or graphic is drawn. When any such frame is lost, missing, outside the
  layer or stale, or the source is never on screen during the blur, the render stops (exit 2) and names the times.
  `cut.py check` reports the same as errors. A frame frozen from the blurred source (`still ALIAS TIME`) is a new
  picture and is not blurred; check refuses one inside a blur.
- **The report.** `assemble-report.json` (in each version) has `layers`: for every layered overlay, the frames in its
  interval, the frames drawn, each stretch not drawn with its reason, the track's worst `error_px` where drawn and,
  for `behind`, the matte's measured change between consecutive drawn frames (`matte_flicker`; real movement counts
  too).

## 5. What it proves and does not

- `track.py`'s `error_px` per frame is the largest of three measured disagreements: the homography's RMS residual
  over the features that agree, their median forward-backward error, and how far the region's corners move between
  fits to two halves of those features (large where corners are extrapolated, as when most of a surface is out of
  frame). It measures agreement among features, not the true position: a surface that bends, a reflection or a
  repeated pattern can agree with itself and still be wrong. `drift_px` is a round trip: the region tracked from each
  end of the range back to the key frame, as the mean distance of its corners from where they started.
- A frame is `lost` when too few features agree, the fitted region is implausible (folded, far too large or small,
  under a fifth in frame) or the picture inside it no longer correlates with the key frame's (a cover, a cut, a
  change of light). Lost frames are honest gaps; tracking resumes when the key frame's features are found again,
  and a surface found again must look more like the key frame than one followed frame to frame. A track never
  crosses a shot change: frames in another shot are lost, because a look-alike in the next shot (the same logo on
  another wall) is the commonest false match. A shot change is a large picture change well above the recent motion;
  a fast whip pan can read as one and end a track early.
- A point track measures `error_px` as the spread of its features' agreement (a face that talks and turns spreads
  them); it compares the point's patch with its last good look, so it follows a turning face but can slide slowly
  along it: its round-trip `drift_px` says how far.
- `spatial.py check` proves a layer belongs to the source as it is now and has a frame for every source frame in
  its range. It does not prove the track follows the right surface or the matte the right person.
- A pin, `behind` or blur being drawn proves the geometry was applied, not that it looks attached: look at frames of
  the rendered version (`frame_sheet.py`), at normal speed too.
- **A blur is not anonymisation.** It hides detail inside a padded region where the layer says the region is. It can
  miss a face the layer does not cover, a reflection, a frame a person was not tracked on, and recognisable voice,
  clothing or context. A person checks every frame of a privacy blur before anything leaves the machine.

## 6. Recipes

**A title behind a person.** Make a subject matte over the line's range (`matte.py`, see its `--help`), named
`subject`. Write `~ title "Six weeks" 2.0 center behind subject` under the line. `cut.py check`, render, and look at
frames where the title crosses the person's edges (hair, hands): a matte's soft or wrong edge shows there first, and
the report's `matte_flicker` says how much the drawn matte changed between frames.

**A graphic pinned to a screen.** Take a still at the line's first frame (`frame_sheet.py SOURCE --at 0:41.20`),
read the screen's four corners, and track it over the range the line uses:
`track.py broll_03 --at 0:41.20 --region 412,318,980,300,995,602,405,640 --from 0:41.00 --to 0:46.00 --name screen
--project P`. Read the summary (frames lost, worst error, drift); 1 px or less at the film's size reads as attached.
Write `~ still logo_01 3.0 pin screen` (or a pinned title) under the line, check, render and look at frames from the
start, middle and end of the pin. A screen with little texture tracks poorly: include its bezel in the region, or
put the key frame where the screen shows detail.

**A tracked privacy blur.** Track the plate or face over the whole line with margin either side
(`track.py broll_07 --at 0:03.00 --region ... --from 0:01.50 --to 0:06.50 --name plate --project P`, or `--point`
for something that only moves), write `~ blur plate` under the line, and run `cut.py check`: lost frames inside the
line are errors, because the render would stop. Retrack with a key frame nearer the lost stretch, a larger region,
or a matte. After rendering, look at every frame of the blurred stretch (`frame_sheet.py --frames A-B`), and record
that a person did.

## 7. Measured

On synthetic known-answer media (`selftest_cases/spatial.py`, one run): a textured plane moved by known homographies
at 1280x720 is tracked within 0.06 px at its worst corner while wholly in view and 0.1 px while at least half is in
view; with under half in view the extrapolated corners were 1.0 and 1.9 px out, and `error_px` said 0.6 and 2.9 px,
so the estimate can understate there. Frames where the plane is covered, or under 15% in view, are lost and carry no
corners; the round-trip drift was 0.9 px. A point on the same plane is followed within 0.5 px, lost while covered
and found again within 0.8 px (its `error_px` said 0.2-0.8 px there). Through a 90-degree rotation tag,
variable frame timing, x1.5 and crop auto together, a pinned overlay lands within 1.5 output pixels of the tracked
square. These prove the arithmetic and the bookkeeping, not performance on real footage: real footage results are
recorded in the release notes with the clips they were measured on.
