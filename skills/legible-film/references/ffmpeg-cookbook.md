# FFmpeg cookbook

Commands for finishing and checking a film. Each was run on FFmpeg 9.0.2 (2026-10-27) unless marked; most
work on FFmpeg 5.1 or later. Replace file names, times and sizes with your own. Builds differ: check
`ffmpeg -filters` for `subtitles` (libass), `libvmaf` and `whisper`.

Contents: [Inspect](#inspect) · [Frames and sheets](#frames-and-sheets) · [Colour](#colour) · [Encode](#encode) ·
[Frame rate](#frame-rate) · [Audio](#audio) · [Mux](#mux) · [Captions](#captions) · [Compare](#compare) ·
[Recordings](#recordings) · [Windows notes](#windows-and-quoting-notes)

## Inspect

```bash
# Streams and container metadata as JSON
ffprobe -v error -show_format -show_streams -of json film.mp4

# Decode every stream; any output is an error
ffmpeg -v error -i film.mp4 -map 0:v? -map 0:a? -f null -

# Colour tags only
ffprobe -v error -select_streams v:0 -show_entries stream=pix_fmt,color_primaries,color_transfer,color_space,color_range -of csv=p=0 film.mp4
```

`scripts/qc_file.py` runs all of these and more, and compares them with a spec.

## Frames and sheets

```bash
# Exact frame by zero-based index (frame 120)
ffmpeg -v error -i film.mp4 -vf "select=eq(n\,120)" -fps_mode passthrough -frames:v 1 frame-120.png

# Fast frame near a time (input seek; usually right for constant-frame-rate files, verify when it matters)
ffmpeg -v error -ss 12.5 -i film.mp4 -frames:v 1 at-12.5.png

# Overview tile without Python: one frame every 0.5 s, 8 x 8 tiles
ffmpeg -v error -i film.mp4 -vf "fps=2,scale=320:-1,tile=8x8:padding=4" -frames:v 1 overview.png

# Phone-feed-width preview of the whole film
ffmpeg -v error -i film.mp4 -vf "scale=384:-2" -c:a copy phone-preview.mp4
```

`scripts/frame_sheet.py` labels every tile with its decoded timestamp and frame number using Pillow, so it does
not depend on `drawtext` and fontconfig.

## Colour

```bash
# RGB frames (a PNG sequence from a browser render) to correctly converted and tagged BT.709 H.264
ffmpeg -framerate 60 -i frames/%05d.png \
  -vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv" \
  -c:v libx264 -preset slow -crf 14 -profile:v high -movflags +faststart picture.mp4

# Repair missing tags on an H.264 file without re-encoding (use hevc_metadata for HEVC)
ffmpeg -i in.mp4 -c copy -bsf:v "h264_metadata=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1" out.mp4
```

- Output options alone (`-color_primaries bt709 -color_trc bt709 -colorspace bt709`) left primaries and
  transfer untagged on FFmpeg 9.0.2; tag in the filter graph instead.
- Some filters drop colour properties: `tmix` output lost its primaries and transfer tags. End every filter
  chain with the `setparams` step above, and check the tags on the result.
- Tags describe pixels; converting with the default matrix and then tagging BT.709 shifts colours
  ([finishing](finishing.md) §3). Verify a brand colour with `qc_file.py --color-patch`.

## Encode

```bash
# Web master: H.264 High, 4:2:0, fast start, AAC
ffmpeg -i picture.mp4 -i master.wav -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 256k -ar 48000 -movflags +faststart film.mp4

# Light review copy (re-encoding a tagged source kept its BT.709 tags)
ffmpeg -i film.mp4 -c:v libx264 -preset slow -b:v 6M -maxrate 9M -bufsize 12M -pix_fmt yuv420p -c:a copy -movflags +faststart light.mp4

# GIF at 25 fps with a generated palette (GIF timing is stored in centiseconds, so 25 and 50 fps are exact)
ffmpeg -i loop.mp4 -vf "fps=25,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a" -loop 0 loop.gif

# Alpha for editors: ProRes 4444
ffmpeg -framerate 60 -i frames/%05d.png -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le sting-alpha.mov

# Alpha for browsers: VP9 WebM (ffprobe reports yuv420p plus alpha_mode=1)
ffmpeg -framerate 60 -i frames/%05d.png -c:v libvpx-vp9 -pix_fmt yuva420p -b:v 0 -crf 30 sting-alpha.webm

# Light temporal grain before the delivery encode (test it after a platform-like re-encode)
ffmpeg -i in.mp4 -vf "noise=alls=2:allf=t,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709" -c:v libx264 -crf 16 -c:a copy grained.mp4
```

A finish that blends layers must run in RGB: put `format=gbrp` before the blend filters and convert back with
the colour step above.

## Frame rate

```bash
# 120 fps render to 60 fps by keeping every second frame (sharp; verified: output frame 5 = source frame 10)
ffmpeg -i render120.mp4 -vf "fps=60" -c:v libx264 -crf 14 out60.mp4

# 120 to 60 fps averaging pairs (a two-sample motion blur); tmix drops colour tags, so re-tag
ffmpeg -i render120.mp4 -vf "tmix=frames=2:weights=1 1,fps=60,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709" -c:v libx264 -crf 14 blur60.mp4
```

## Audio

```bash
# Integrated loudness, loudness range and true peak (ITU-R BS.1770)
ffmpeg -nostats -i film.mp4 -map 0:a:0 -af ebur128=peak=true:framelog=quiet -f null -

# Simulate a platform re-encode, then measure its true peak
ffmpeg -v error -i film.mp4 -map 0:a:0 -c:a aac -b:a 128k reencode.m4a
ffmpeg -nostats -i reencode.m4a -af ebur128=peak=true:framelog=quiet -f null -

# Two-pass normalisation, only when the delivery spec sets a loudness target.
# Pass 1 prints JSON (input_i, input_tp, input_lra, input_thresh, target_offset):
ffmpeg -nostats -i mix.wav -af loudnorm=I=-23:TP=-1:LRA=11:print_format=json -f null -
# Pass 2 applies it linearly with the measured values:
ffmpeg -i mix.wav -af loudnorm=I=-23:TP=-1:LRA=11:measured_I=<input_i>:measured_TP=<input_tp>:measured_LRA=<input_lra>:measured_thresh=<input_thresh>:offset=<target_offset>:linear=true -ar 48000 mix-norm.wav

# Phone-speaker band preview and a mono check
ffmpeg -i film.mp4 -af "highpass=f=350,lowpass=f=8000" -c:v copy phone-band.mp4
ffmpeg -i film.mp4 -af "pan=mono|c0=0.5*c0+0.5*c1" -c:v copy mono.mp4

# Hash decoded audio to prove it is unchanged (Git Bash, macOS, Linux)
ffmpeg -v error -i film.mp4 -map 0:a:0 -f s16le -ar 48000 -ac 2 - | sha256sum
# ...anywhere Python runs
ffmpeg -v error -i film.mp4 -map 0:a:0 -f s16le -ar 48000 -ac 2 - | python -c "import hashlib,sys;print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"

# Extract the soundtrack as 24-bit WAV
ffmpeg -i film.mp4 -map 0:a:0 -c:a pcm_s24le soundtrack.wav
```

Single-pass `loudnorm` normalises dynamically and can change the mix's dynamics. Even in the second pass,
`linear=true` is a request: when linear gain cannot meet the target within the true-peak and range limits, FFmpeg
falls back to dynamic normalisation (a fallback reproduced on a synthetic tone in review). Add
`print_format=json` to the second pass and read `normalization_type`; if it says `dynamic` and the dynamics must
be kept, relax the target or apply plain gain with `volume=` instead.

### Repair a steadily growing audio offset

A global shift cannot remove drift. Compare separated non-silent windows with
`sync_check.py delivered.mp4 approved.wav --windows 8 --json qa/sync.json`. A supported affine fit reports
`delivered_time = time_scale * reference_time + offset_s`, with `rate_ratio = 1 / time_scale`.
Positive offset means late audio. For a sample-clock error made by slowing audio to **0.99** of the approved
rate, `rate_ratio` is about **0.99**, and the repair speed is **1.010101010101**. The tool retains the original
window measurements and validates the proposed rate against full-length rate-adjusted windows. A step edit,
nonlinear drift or weak/ambiguous correlation does not justify a single global repair.

Use the tool's printed command and exact measured values. General recipe, with a 24 s picture, a fitted
`time_scale` of 1.010101010101 and a fitted `offset_s` of +0.043 s:

```bash
# Inverse sample-clock repair: speed up, reset PTS, remove the corrected offset,
# then pad/trim audio to the picture's measured duration. Copy every picture frame.
ffmpeg -i delivered.mp4 -map 0:v:0 -map 0:a:0 -c:v copy \
  -af "aresample=48000,asetrate=48000*1.010101010101,aresample=48000,asetpts=PTS-STARTPTS,atrim=start=0.042570000,asetpts=PTS-STARTPTS,apad,atrim=duration=24,asetpts=N/SR/TB" \
  -t 24 -c:a aac -b:a 256k -ar 48000 -movflags +faststart delivered-rate-repaired.mp4
```

For general values `S = time_scale`, `B = offset_s`, and picture duration `D`, use `asetrate=48000*S`, then
`aresample=48000,asetpts=PTS-STARTPTS`. If `B > 0`, remove `B/S` seconds with `atrim=start=B/S` and reset
PTS again. If `B < 0`, insert `round(-B/S*48000)` samples of silence with `adelay=NS:all=1` (replace `N`
with that integer); do not trim. If `B = 0`, omit both. Finish with `apad,atrim=duration=D,asetpts=N/SR/TB`
and output `-t D`, never `-shortest`. Substitute evaluated numbers in filter arguments. Measure `D` from the
picture, not the longer drifting audio or the container duration. The printed command requires a zero-origin
picture; resolve nonzero container origins and discontinuities before applying this decoded-sample-clock fit.

`asetrate` plus `aresample` changes pitch and is the inverse of a sample-clock error. For a true tempo error
whose pitch should stay unchanged, substitute `atempo=S,asetpts=PTS-STARTPTS` for the rate filters (chain
supported factors for a large change), then apply the same offset and duration steps. It is not the inverse
of a pitch-changing resample. Prefer reconforming the approved master when the cause is uncertain.
Re-run `sync_check.py` at every separated window on the repaired deliverable, `cue_onsets.py` against the
picture's cue list, and the file/true-peak checks; a person must listen. These synthetic repairs establish
measured alignment only, not picture-event sync or audio quality.

## Mux

```bash
# Master audio onto the picture, matching the picture's length exactly (pads a short master, trims a long one)
D=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 picture.mp4)
ffmpeg -i picture.mp4 -i master.wav -map 0:v:0 -map 1:a:0 -c:v copy -af apad -t "$D" -c:a aac -b:a 256k -ar 48000 -movflags +faststart film.mp4
```

Verified trap: `-shortest` with a 3.2 s master truncated a 4.0 s picture to 94 of its 120 frames. With
`apad` and `-t` set to the picture duration, both a short and a long master gave exactly 120 frames and equal
audio and video lengths.

## Captions

```bash
# Burn in (run from the folder holding the .srt; see the Windows notes)
ffmpeg -i film.mp4 -vf "subtitles=captions.srt:force_style='FontSize=24,Outline=2'" -c:a copy film-captioned.mp4

# Soft captions in MP4
ffmpeg -i film.mp4 -i captions.srt -map 0 -map 1 -c copy -c:s mov_text -metadata:s:s:0 language=eng film-cc.mp4
```

## Compare

```bash
# Per-frame PSNR between two versions (run inside the output folder; relative stats file name)
cd qa && ffmpeg -i ../new.mp4 -i ../old.mp4 -lavfi "[0:v][1:v]psnr=stats_file=psnr.log" -f null -
```

`scripts/compare_versions.py` does this and lists the changed time ranges. VMAF (needs a `libvmaf` build)
compares an encode against its source when a codec or bitrate changes; the first input is the encode.

## Recordings

```bash
# Find when a region of a screen recording changes (event times), reading pts_time from showinfo
ffmpeg -i rec.webm -vf "crop=400:200:100:300,select='gt(scene,0.002)',showinfo" -f null - 2>&1 | grep pts_time

# Exact frame at or after a time in a variable-frame-rate recording
ffmpeg -i rec.webm -vf "select='gte(t,12.4)'" -frames:v 1 at-12.4.png
```

Periodic changes every few seconds in a VP8 or VP9 recording can be keyframes, not events.

## Windows and quoting notes

- In filter arguments, a drive-letter colon is read as an option separator. Absolute Windows paths failed
  with "Invalid argument" for both the `subtitles` filter and `psnr=stats_file=`. Run FFmpeg from the file's
  folder and use relative names, or escape the colon (`C\:/path`).
- Escape commas inside filter expressions (`eq(n\,120)`) and quote the whole filter graph.
- Some builds do not support `-pattern_type glob`; use numbered sequences (`frames/%05d.png`).
- `ffprobe` takes one input per call ("Argument 'b.mp4' provided as input filename, but 'a.mp4' was already
  specified"), and `-vsync` is gone from FFmpeg 9 (use `-fps_mode`). Probe each file on its own and check each exit
  code; a chained batch reports only the last.
- PowerShell has no brace expansion (`{a,b}.mp4`), and a here-string's closing `'@` must start its own line. Windows
  PowerShell 5.1 writes text files with a byte-order mark (`Set-Content -Encoding UTF8`) or as UTF-16 (`Out-File`,
  `>`); write files for other tools with `[IO.File]::WriteAllText`, which writes UTF-8 without one. Tested in
  PowerShell 5.1 and 7:

  ```powershell
  $cues = @'
  [{"id": "hit", "t": 0.5, "sound": "required", "sync": "attack", "tolerance_ms": 25}]
  '@
  [IO.File]::WriteAllText("$PWD\cues.json", $cues)
  foreach ($f in @('a.mp4', 'b.mp4')) {
    ffprobe -v error -show_entries format=duration -of csv=p=0 $f
    if ($LASTEXITCODE -ne 0) { Write-Output "$f could not be probed (exit $LASTEXITCODE)" }
  }
  ```
- `drawtext` needs fontconfig or an explicit `fontfile=`. On a Windows static build without a fontconfig file,
  FFmpeg 9.0.2 printed fontconfig errors and fell back to a default font, and an 8.1 build crashed. Pass
  `fontfile=` explicitly, or label images with Pillow (as `frame_sheet.py` does).
