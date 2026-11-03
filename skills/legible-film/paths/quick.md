# Quick: one file, one change or one question

**Covers** a trim at given points, a reframe to another aspect ratio, a resize, convert, compress, audio extract, GIF
or speed change on one file, or two of these together; captions for a file outside a project; a standalone check or
grade of any file; a question about what a file's sound does; and `setup`.

**Timeline owner.** The **file**. No project folder, brief, frame or paper edit. Choosing what to keep by what it
says or shows (the best part, the payoff) chooses content, so that is a [cut](cut.md), even from one file.

## First run

Once per machine, before its first job. `setup.py` says what works here; read back the fixes the job needs.
`setup.py --install core` installs numpy and Pillow and names the Python to run every script with. With the person's
yes, `--install transcription` adds faster-whisper and `--install kit` the film kit's browser; any model downloads
only with `--download`, after the person hears its size. `selftest.py --smoke` is the ten-second real check. Done
when `setup.py` exits 0 or names what is missing for this job.

## Steps

1. **Make the change beside the original, under a new name.** Read [ffmpeg-cookbook](../references/ffmpeg-cookbook.md)
   for the command, and [gotchas](../references/gotchas.md) before you write your own; when the request names a
   destination or a platform, read [formats](../references/formats.md). Probe first (`ffprobe` or `qc_file.py FILE`) for
   size, rate, duration and streams, and ask only for what cannot be inferred (a cut point, which part of a wide frame
   to keep, or which interval a two-way request means). Combine two operations in one command so the picture is encoded
   once ([cookbook](../references/ffmpeg-cookbook.md#cut-and-reframe)). A crop that follows a moving subject is a
   one-item edit file rendered with `assemble.py edit.json --out picture.mp4`, which also writes a WAV stem per audio
   track for the [mux](../references/ffmpeg-cookbook.md#mux):

   ```json
   {"version": 1, "size": [1080, 1920], "fps": 30, "sources": {"a": {"file": "source.mp4"}},
    "picture": [{"src": "a", "in": 4.0, "out": 12.0, "crop": {"path": "auto"}}],
    "audio": [{"track": "main", "src": "a", "in": 4.0, "out": 12.0, "at": 0.0}]}
   ```

   The automatic path follows the largest frontal face, or motion and detail without OpenCV, and recognises no one, so
   look at frames of the result and report any moment the subject leaves the frame. Captions come from `transcribe.py
   FILE --out words.json --prompt "names and terms"`, then `captions.py build` and `captions.py check`; a person reads
   every caption ([footage](../references/footage.md) §11 has the rules). Done when the output exists and the original
   is untouched.
2. **Check matched to the edit.** `check.py --file OUT --against IN --edit KIND`, with KIND one of `trim:A,B`,
   `speed:X`, `reframe`, `convert`, `extract-audio`, `captions` or `compress`. The kind sets what must hold. A trim
   lasts B minus A within one frame with the audio offset unchanged; a speed change scales the duration by X; a
   reframe keeps duration and sound; a convert keeps duration and stream count for its destination; an audio extract
   has no video stream and the source's duration; captions change no stream. Done when the report has no fail.
3. **Show it.** One line of what changed, with the file. A standalone check runs `check.py --file F [--delivery JSON]`
   ([qc](../references/qc.md) §2 says what it runs), a scorecard `grade.py --file FILE --platform NAME`
   ([grading](../references/grading.md)), and a sound question `listen.py transcript F` ([sound](../references/sound.md)
   §13), whose events are measured onsets and level changes, not identified sounds and not a listening verdict. The
   report says what was not assessed. Done when the person has the file or the answer, and what was not assessed is
   named.

## First question

None; ask only for a missing parameter.
