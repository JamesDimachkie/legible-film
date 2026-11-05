# A first cut in a minute

A 23-second scene with clear speech, its transcript and a paper edit, so a first check and a first cut need no
footage of your own and no transcription model. On a laptop the cut takes well under a minute from an empty folder.

| File | What it is |
|---|---|
| `tears-of-steel-bridge.mp4` | The excerpt: 1280x534, 24 fps, H.264 and AAC, BT.709, 23.25 s, 3.4 MB |
| `tears-of-steel-bridge.words.json` | Its word-timed transcript in clip seconds, the format `map.py run --words import:` reads |
| `film.md` | A paper edit that cuts the scene to about 15 s along one line of meaning |

## The scene

Thom and Celia on a bridge in Amsterdam, the opening of Tears of Steel. He says he is leaving to follow his passion;
she asks why he won't admit her robot hand frightens him; he denies it, then admits it; she ends it. The excerpt is
source 0:22.25 to 0:45.50 of the film, starting after the funding credit. Its last five seconds belong to the next
scene: a robot hologram from about 18 s, then the title card "40 years later" from about 20.5 s, under the end of
Celia's last line, as the film plays it. Its sound fades in over 0.3 s and out over 0.5 s; nothing else is changed.

The transcript is a draft, like every transcript: the words were checked against two local transcriptions, and the
opening line ("You're a jerk, Thom.") was corrected by hand. Between 0:19.6 and 0:21.1 two voices overlap and the
transcribers disagree, so the paper edit leaves that stretch out. Listen before you use those words.

## Run it

The main README's [Try it](../../README.md#try-it) runs this example, step by step, on Linux, macOS and Windows: a
first check of the clip, then a project started from this folder's paper edit (`project.py init FOLDER --film
examples/first-cut/film.md`), the clip and its transcript added, a render and its check. `screen.py serve FOLDER
--open` then shows the cut in the Screening Room.

## What to expect

The first check reads the file and says what it could measure and what it could not:

```
  ok    1280x534 · 23.2 s · H.264
  ok    -17.1 LUFS  (measured; no target specified)
  ok    True peak -1.5 dBTP after a lossy re-encode
  ...
  skip  Not assessed: captions  (the export has sound and no caption file was given: ...)
  you   Watched by you, muted
  you   Heard by you, with sound
  unconfirmed  Context: what  (missing or incomplete)
  ...
  skip  Not assessed: cold read  (no named cold read recorded)
  skip  Not assessed: sync  (no cue list supplied)
14 checks pass · 2 need you · 3 not assessed; 4 unconfirmed
```

Loudness is measured, not judged: no target was named, so nothing is compared. Each item it could not assess says
what to give it, and the two that need you are the ones no script can do. The four context fields (what the film is,
for whom, why, and what the viewer knows by when) read unconfirmed because nobody has stated them for a loose file;
unconfirmed never fails a check.

`cut.py render` writes `cuts/v001/` in the project: the preview, its captions and the edit it compiled. It warns twice,
and exits 1 to say so. The cut after "I'm freaked out." has no audible pause, because the next words follow at once in
the film. Listen to it. (The map lists no silences because the film's score plays under the whole scene; cuts go in the
pauses between words, and that is the one place without a pause.) At 0:04.75 the background drops 6 dB across a join;
carry it with a tail, a lead or a bed, or keep it as a decision. The project check then exits 0, passes 23 items, asks
you to watch, listen and check the names in the captions, and gives the reason for each item it could not assess, such
as the cold read and the mix measures a designed soundtrack would supply. Where faster-whisper is installed it also
compares the captions with the sound and flags "Thom", which the transcriber spells "Tom": names are where transcripts
go wrong.

Edit `film.md` and render again to make `v002`: strike a word with `~~...~~` to cut it, or delete a line.

## Attribution

Tears of Steel, © Blender Foundation, [mango.blender.org](https://mango.blender.org/), licensed under
[Creative Commons Attribution 3.0](https://creativecommons.org/licenses/by/3.0/). The excerpt is cut from the 720p
release, re-encoded and with its sound faded in and out at the ends; the transcript and paper edit are this
project's own.
