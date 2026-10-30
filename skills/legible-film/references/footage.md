# Footage: films cut from recordings

Interviews, talking heads, screen recordings, event films, tutorials, montages and social cut-downs are edited from
recordings rather than drawn. The steps, gates and QC are the same; this file covers what changes. The edit lives in
one file, `edit.json`, that `assemble.py` renders, so the cue list, the sound chain, the QC battery and the delivery
report run unchanged.

Contents: [1. Story from the material](#1-story-from-the-material) · [2. Ingest](#2-ingest) ·
[3. Selects](#3-selects) · [4. The edit](#4-the-edit) · [5. The edit file](#5-the-edit-file) · [6. Other ratios](#6-other-ratios) ·
[7. Speed and stabilisation](#7-speed-and-stabilisation) · [8. Colour](#8-colour) ·
[9. Screen recordings](#9-screen-recordings) · [10. Dialogue](#10-dialogue) · [11. Captions](#11-captions) ·
[12. Approvals and lock](#12-approvals-and-lock) · [13. Variants and hand-off](#13-variants-and-hand-off)

## 1. Story from the material

The story step changes shape: the approved brief, the selects and an outline drawn from the sources take the place of
three invented concepts. The facts file and the boundary still apply, and so does the truth rule for speech: an edit
may shorten what a person said, never change what it means. Joining two phrases into a sentence the speaker did not
say, or moving an answer onto another question, is a claim the facts do not support
([claims-and-rights](claims-and-rights.md)).

## 2. Ingest

- Copy the originals into `media/` and never write to them. Record each file's SHA-256 (`certutil -hashfile FILE
  SHA256` on Windows, `shasum -a 256 FILE` elsewhere), then probe it with `qc_file.py FILE --json
  qa/sources/NAME.json` for its container, codec, size, frame rate, rotation, colour tags and range, audio and
  duration, one file per command. Its variable-frame-rate flag is a suspicion from average against nominal rate, not
  a classification: read the frame timestamps when it matters. Record timecode (`ffprobe -show_entries
  format_tags=timecode:stream_tags=timecode`) and scan type (`idet`, below) separately, and report unknown values as
  unknown.
- Record rights and consent per source and per person on camera in `assets.csv`. Private, client and unreleased
  footage stays local: transcription, enhancement and frame description run on this machine unless the person
  approves an upload ([engines](engines.md) §9 lists local speech models).
- Check what will need converting, and say so in the report: phones and screen recorders often record a variable
  frame rate; phones store rotation as metadata; recent phones record HDR (HLG or Dolby Vision) by default; broadcast
  and older cameras may be interlaced (`ffmpeg -i FILE -vf idet -f null -` counts field orders). `assemble.py` reads
  presentation timestamps and converts deliberately; a conversion it cannot make is a reason to stop.
- Make review copies, never edit copies: a small H.264 file with burned-in source time, so notes can name the moment
  (`frame_sheet.py` sheets do the same for stills).

## 3. Selects

- Transcribe locally into word-timed JSON (WhisperX-style). A speech model's transcript is a draft: names, numbers
  and anything a select depends on are checked against the audio by a person.
- Write selects as quoted phrases or word ranges, each with its purpose in the story. `transcript_cut.py` finds them,
  proposes each cut in the gap between words with handles, and writes the picture and audio items of `edit.json`.
  Give it the source audio (`--audio`) so it measures silence instead of trusting word timings, and shot boundaries
  (`--shots`) so it can tell a same-shot jump cut. It reports phrases it could not find, each join's gap, and any
  join with no measured silence; listen to every join, and check that the assembler's frame snaps do not land inside
  a word.
- Show the person the selects as a paper edit (the text in order, with durations) before cutting picture. Agreeing
  the words is cheaper than agreeing a cut.

## 4. The edit

- Build the rough cut from the selects, then fine-tune joins in `edit.json`. `assemble.py edit.json --out
  picture.mp4` renders it frame-accurately, writes stems per audio track, `edit-cues.json` and `declared.json`, and
  reports every snap, retime, crop and conversion (§5 describes the file).
- A jump cut on the same shot is a choice: cover it with B-roll or a cutaway, cut to a tighter size (a punch-in of
  at least about 20% so it reads as intended, sharp only if the source has the pixels), or keep it visibly as the
  film's style. An accidental one reads as a glitch.
- Split edits carry speech across picture: let the next speaker's voice start under the outgoing shot (a J cut) or
  the speaker's voice run over the reaction (an L cut). Each audio edit gets a short fade (10-20 ms) so no join
  clicks.
- Dialogue never cuts to digital silence. Fill gaps with the room's own tone, recorded or lifted from a pause in the
  same take.
- Dissolves keep the outgoing shot opaque while the incoming one fades over it, as in [picture](picture.md) §7;
  a dip to a colour is for a change of time or place.
- Graphics, lower thirds and callouts are overlays in `edit.json` or a kit film composited over the picture; their
  entrances become cues, so the sound chain spots them like any other event.
- Check each cut with the [qc](qc.md) battery. Pass the `ignore` string from `declared.json` (designed holds and dips,
  as `START-END` seconds) to `blank_scan.py` and `motion_scan.py --ignore`, never to `flash_scan.py`, and run
  `motion_scan.py` with `--footage`: a speaker holding still for two frames is camera footage behaving normally, and only exact duplicate
  frames are defects there. A cut-down has no approved mix to sync against until its own mix exists; check it
  against the source window instead.

## 5. The edit file

`edit.json` is the edit decision list. Times are seconds; `in` and `out` are source times; edit time follows the
order of `picture`.

```json
{
  "version": 1,
  "size": [1080, 1920], "fps": 30,
  "sources": {"a": {"file": "media/interview.mp4"}, "b": {"file": "media/broll.mov"},
              "bed": {"file": "music/bed.wav"}, "lt": {"file": "art/name.png"}},
  "picture": [
    {"src": "a", "in": 12.40, "out": 18.92, "crop": {"path": [[0.0, 0.62, 0.42], [6.5, 0.58, 0.40]], "zoom": 1.0}},
    {"src": "b", "in": 3.00, "out": 5.50, "speed": 0.5, "retime": "blend", "join": {"kind": "dissolve", "dur": 0.25}}
  ],
  "audio": [
    {"track": "dialogue", "src": "a", "in": 12.20, "out": 19.10, "at": -0.20, "fade_ms": 12},
    {"track": "music", "src": "bed", "in": 0.0, "out": 30.0, "at": 0.0, "gain_db": -12}
  ],
  "overlays": [
    {"kind": "image", "src": "lt", "from": 1.0, "to": 4.5, "x": 0.06, "y": 0.70, "w": 0.6, "fade_ms": 200},
    {"kind": "captions", "file": "captions.srt", "avoid": [[0.2, 0.2, 0.6, 0.47]], "plate": true}
  ],
  "holds": [],
  "cues": [{"id": "name-in", "t": 1.0, "sound": "optional", "sync": "attack", "role": "pop"}]
}
```

- **`fps`** is a number or a fraction: `25`, `29.97` or `"30000/1001"`. A decimal NTSC rate (23.976, 29.97, 59.94)
  means the exact fraction, which is what an editing application expects; 2997/100 is not.
- **Picture items** last `(out - in) / speed`. `in` and `out` snap to the source's decoded frame times, and the
  report lists every snap. `fit` is `cover` (default) or `contain` (with a `background` colour). `retime` is
  `nearest` (default), `blend` or `motion`.
- **`join`** describes the join into an item: `cut` (default), `dissolve` or `dip` (to `color`), with `dur`. A
  dissolve keeps the outgoing shot opaque while the incoming one fades over it. Three-way overlaps are refused.
- **`crop.path`** is `[[edit seconds from the clip's start, centre x, centre y], ...]` as fractions of the source
  frame; the crop has the output's aspect ratio, `zoom` scales it, and it never leaves the source. `"auto"` asks
  `reframe.py` for a path; a file name loads one it wrote.
- **Audio items** carry their own `at` (edit time), so audio can start before its picture (a J cut) or run past it
  (an L cut); `fade_ms` (default 15) keeps joins from clicking, and each `track` becomes a stem
  (`dialogue.wav`, `music.wav`).
- **Overlays:** `image` at `x`, `y` and width `w` (fractions of the frame) from `from` to `to`; `captions` from an
  SRT, VTT or caption JSON, burned by `captions.py` with its `safe`, `avoid`, `plate`, `highlight`, `font` and
  `font_size` fields.
- **Cues:** `edit-cues.json` lists every join and image overlay as a candidate sound moment, withheld unless the item
  sets `"sound": true` (with a `role`), plus the edit's own `cues`; captions never become cues. `declared.json`
  lists the cuts, dissolves and `holds`, and an `ignore` string of the designed holds and dips ready for
  `blank_scan.py` and `motion_scan.py --ignore` (never `flash_scan.py`).

## 6. Other ratios

- A tall or square rendition of wide footage follows the subject, not the centre. `reframe.py SOURCE --aspect 9:16
  --auto` proposes a smoothed crop path from sustained motion and detail; `--path` checks one written by hand. It
  flags frames where the subject leaves the crop and writes a sheet of the window over time: review that sheet before
  rendering, and treat the auto path as a proposal, never a tracker.
- Two people in a wide shot rarely fit one tall crop: cut between them, stack them, or keep the wide shot letterboxed
  for that moment, and say which.
- Re-place captions, lower thirds and graphics for each rendition inside its own safe area ([formats](formats.md) §3).

## 7. Speed and stabilisation

- `speed` in `edit.json` retimes a clip; `retime` chooses how: `nearest` repeats frames (honest, steppy), `blend`
  mixes neighbours (soft), `motion` interpolates (smooth, can warp edges and hands; inspect every retimed range frame
  by frame). Audio taken from a retimed clip keeps its pitch. Real slow motion needs a high-frame-rate source.
- Stabilise in two passes with FFmpeg's vid.stab, run from the clip's folder so the transform file path has no drive
  colon (ran on FFmpeg 9.0.2; check `ffmpeg -filters` for `vidstabdetect`):

  ```bash
  ffmpeg -i shaky.mp4 -vf "vidstabdetect=shakiness=6:accuracy=12:result=transforms.trf" -f null -
  ffmpeg -i shaky.mp4 -vf "vidstabtransform=input=transforms.trf:smoothing=15:zoom=0:optzoom=1,unsharp=5:5:0.6:3:3:0.0" stable.mp4
  ```

  `optzoom=1` zooms just enough to hide moving edges; check the result for warped verticals and for a zoom that
  crops essential picture. Stabilisation is a choice: handheld motion can be the point.

## 8. Colour

- Interpret each source before matching anything: read its tags, the camera's profile and the shooting notes. A flat
  picture is not proof of a log profile; apply a camera manufacturer's LUT only when the source is known to use that
  profile, with FFmpeg's `lut3d`.
- HDR phone footage for an SDR delivery needs tone mapping, not retagging (ran on FFmpeg 9.0.2 with an HLG source):

  ```bash
  ffmpeg -i hlg.mov -vf "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv" -c:v libx264 -crf 18 sdr.mp4
  ```

- Match shots to a reference shot in one working space, exposure and white balance first. Measure, then look: a
  waveform shows levels and clipping, a vectorscope shows casts and skin tones (skin falls near one line on the
  scope whatever the complexion).

  ```bash
  ffmpeg -ss 4 -i shot.mp4 -vf "format=yuv444p,waveform=mode=column:display=overlay:filter=lowpass:graticule=green:flags=numbers+dots" -frames:v 1 wave.png
  ffmpeg -ss 4 -i shot.mp4 -vf "format=yuv444p,vectorscope=mode=color3:graticule=green:flags=name" -frames:v 1 scope.png
  ```

- Skin tones and continuity are approved by a person on a decent display; a scope says where to look, not whether
  it looks right.

## 9. Screen recordings

- Record at the delivery size or larger, at a constant frame rate, with a clean desktop, notifications off and test
  data ([product-demos](product-demos.md) §7). Check every frame for secrets before anyone else sees it.
- Guide the eye with crop paths in `edit.json`: zoom to the region that matters before the action, hold while it
  happens, ease out after. Text inside the zoom must clear the reading limits at viewing size
  ([timing](timing.md)).
- Speed through waiting (a load, an install) with a stated speed-up rather than a hidden cut, and keep the cursor's
  path continuous across it.
- A recording stays a recording: a rebuilt interface is labelled as a reconstruction ([product-demos](product-demos.md)
  §5).

## 10. Dialogue

- Clean dialogue conservatively, and only after listening reports a problem: `voice_clean.py` applies a high-pass,
  noise reduction sized from the measured floor, de-essing and light compression in steps, measuring each and keeping
  the original. Every step is a starting point for a listener; over-cleaned speech sounds underwater and is worse than
  a little noise.
- In the mix, a `voice` track in the palette ducks the music by the voice's own envelope to a stated separation
  (10 LU is a starting point), and `sound_check.py --voice` reports the separation per phrase. Intelligibility is
  judged by a person listening on a phone and on headphones.
- Keep stems (dialogue, music, effects) aligned and complete, so a later edit or a dub does not need the whole mix
  rebuilt.

## 11. Captions

- Every piece with speech ships a sidecar caption file; a muted feed also gets them burned in. `captions.py build`
  makes SRT and WebVTT from the word timings under the reading rules, `check` tests an existing file, and `burn`
  renders them inside the safe area, from one conformed timed source.
- After every edit, wherever it was made, check the captions against the current dialogue: a word-timed transcript
  of the delivered audio (a local tool, or a hosted one only with the person's permission), then
  `captions.py check captions.srt --words current-words.json`. It names caption words no longer spoken under the
  caption (cut from the audio but left on screen) and captions over no matching speech; fix both. Music symbols,
  bracketed sound descriptions and speaker labels are left for a listener. Spelling differences such as
  numbers written as digits can show as stale words, so read each one. Against a transcript (rather than a
  listening pass), a flagged word is a candidate: on one real two-revision case, about one in four led to an edit
  and most of the rest were transcript variants the editor kept. Styling tags, empty transcript rows and word
  times the transcript marks as estimated are allowed for.
- Entrances, exits, short captions and reading speed come back as review prompts with their numbers. Short captions
  are often intentional; a person listens and decides, and nothing is merged or retimed to satisfy a number.
- Fix a caption at the change, or rebuild captions that came from a timed source; never shift an old caption file by
  hand.
- A person checks every caption against the audio, names and numbers first ([formats](formats.md) §7).

## 12. Approvals and lock

- Rough cut, fine cut, picture lock, sound, finish. Share each with burned-in time so notes name the moment, and keep
  each approved version as a baseline ([review](review.md)).
- Picture lock freezes the cue list. A picture change after lock re-exports the cues, the captions and every
  rendition's mix; compare the new cue list with the locked one before reusing anything.

## 13. Variants and hand-off

- Each variant (a ratio, a length, a language) is its own deliverable with its own QC run; a pass on one never covers
  another. A different length or story is a different edit with its own `edit.json`.
- A translated version needs a native speaker's review of every line, and its own caption timing.
- To finish in an editing application, export the cut list through OpenTimelineIO (FCPXML, EDL, AAF); effects,
  retimes and transitions do not survive the round trip, so list them in the hand-off ([engines](engines.md) §7).
