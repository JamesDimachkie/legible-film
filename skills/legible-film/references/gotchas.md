# Gotchas

Read this before you write an FFmpeg command or filter graph of your own, convert colour, pad or mix audio, retime,
set a frame rate, measure decoded audio, or cut on transcript times. Each was hit in real production or measured
while building this skill, and each applies to every kind of job; the scripts already handle them, so they bite when
you work outside a script.

**Act on whole lists.** Long output can reach you shortened (a harness that truncates it, a compression tool that
keeps a sample of rows). Before an edit that depends on every clip, word, note or change, read the report from the
file the script wrote (`--json`) and check its rows against the total it states.

Lessons for one topic live in its reference: colour and muxing in [finishing](finishing.md), commands and Windows
quoting in [ffmpeg-cookbook](ffmpeg-cookbook.md), engine audio and true peak in [sound](sound.md), frame timing in
[footage](footage.md), beat phase in [timing](timing.md), renderers and uploading tools in [engines](engines.md),
sampled views in [qc](qc.md).

## FFmpeg and the picture

- Give every FFmpeg call a time limit and bound its audio padding: an `amix … apad, atrim` graph never ended in about
  one run in seven on FFmpeg 9.0.2 and wrote a 40 GB file. Pad with `apad` and cut with `-t` (or `apad=whole_dur`);
  `-shortest` with a short soundtrack truncated a 120-frame picture to 94 frames.
- Default RGB-to-YUV conversion uses the BT.601 matrix; tagging the result BT.709 shifted a brand blue from
  (48,128,192) to (39,123,195). Convert with an explicit BT.709 matrix, tag in the filter graph (`setparams`), and
  check the output's tags ([finishing](finishing.md) §3).
- A decimal 29.97 written as 2997/100 reads as a non-standard rate in editing applications; write the exact
  30000/1001, as the scripts do.

## Cuts and sound

- Cut points taken from a transcript's word times alone landed in speech or breaths on a third of joins; measure the
  pause in the audio, as `cut.py` does, and have a person listen to the joins it flags as tight.
- `atempo=1` is not a no-op: at 1x it shifted pulses by up to 18 ms and dropped samples. Leave tempo filters out
  at normal speed, and check event positions after a real retime (pitch-preserving retimes moved events up to 41 ms).
- Mixing in 16-bit intermediates clipped two overlapping parts that were each below full scale; mix in float and
  limit once, at the end.
- `loudnorm` asked for linear gain fell back to dynamic processing without failing, and wrote 192 kHz unless the
  output rate was set; read its second-pass report and set the rate.
- Audio decoded to a raw pipe loses its stream's start time: a tone 1.05 s into the source measured at 0.25 s.
  Decode on the source clock (`aresample=async=1:first_pts=0`).
