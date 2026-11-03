# Editor: assisting someone who edits in Premiere or Resolve

**Covers** following an editor's revisions in Premiere or Resolve, captions that went stale under an edit, checking
their export as delivered, and handing a cut to an editor as Final Cut Pro 7 XML.

**Timeline owner.** The **editor's timeline**. You read it and report; you never change their cuts. The request sets
the scope, so a caption repair stays a caption repair, with no paper edit and no frame questions.

## Steps

1. **Pin the authoritative export and timeline.** The editor exports the sequence (File > Export > Final Cut Pro XML),
   the picture and the caption sidecar after each pass. Map their source recordings once (`map.py add`, `map.py run`)
   so transcripts are bound to the files; a proxy or transcode needs `--map CLIPFILE=ALIAS`. Done when the export and
   the timeline are named in the report with their hashes.
2. **Compare revisions.** `exchange.py compare before.xml after.xml --project PROJECT --captions before.srt --json
   changes.json` follows each earlier caption into the new edit (unchanged, moved, stale, removed, split or unknown)
   and names every track and clip it left out; it exits 1 until they are resolved. Without the earlier XML or the
   transcripts, say which comparisons are blocked. Done when every change is listed by timecode.
3. **Check as delivered.** Read [qc](../references/qc.md) §2 for what `check.py --file` runs and what each item cannot
   see, and [footage](../references/footage.md) §11 for caption rules and house styles. `check.py --file export.mp4
   --captions export.srt --timeline export.xml --project PROJECT --json qa/export-checks.json` runs the file checks, the
   caption rules, the captions against the timeline's words and against a local transcript of the export's own sound.
   After the next export, `check.py --verify` says the result no longer applies. Done when `check.py --file` has run
   with the captions and the timeline.
4. **Repairs by timecode.** When a repair could touch approved work, read [review](../references/review.md) §2-3 first.
   Hand back a short list of proposed repairs, each tied to the files' hashes, for the editor to apply in their own
   application. Treat flags as candidates to read; a caption never moves a cut. Everything outside the declared repairs
   stays unchanged, and you show it with `sync_check.py NEW OLD` for transport, `sync_check.py NEW OLD --outside A,B`
   for sound content (A..B the repaired span in the old export's seconds) and `compare_versions.py NEW OLD` for picture.
   Duration and stream layout change only where a listed repair says so. Done when each repair has a timecode and a
   hash, and each comparison outside the repairs is reported.

## Hand-off from a paper edit

Inside a paper project, `handoff` writes the cut for an editor to finish. Write the latest version, the highest
`cuts/vNNN`, with `exchange.py write PROJECT vNNN --out handoff.xml --verify`; run `cut.py render PROJECT` first only
when the project has no version yet. In Premiere, File > Import the XML; in Resolve, File > Import > Timeline; import
`handoff.srt` separately. The XML links media by absolute file URL, or relative to the XML with `--relative` when the
folder moves with its media. Crops, speed changes, gains, fades, the mix and burned captions do not travel; the command
prints them and writes `handoff.notes.txt`. Compare against the render with WAV or PCM sound, since AAC adds encoder
delay. Resolve is untested. Done when `exchange.py read handoff.xml` reports the version's clip count and duration.

## First question

"Which export is latest, and which did you approve?"
