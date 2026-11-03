# Insert: picture made for a passage of footage

**Covers** an animation in place of a passage's picture, timed to its words; a lower third, logo or title over the
footage; graphics pinned to a moving surface, titles behind a person, and tracked blurs.

**Timeline owner.** The **host**, the paper edit (`paper`) or an editor's timeline (`editor`). The insert is a page
inside it, on the host's clock; the host's sound and the picture outside the passage do not change.

## Steps

1. **Pin the passage.** Map the recording (an editor's finished cut is role `other`) and find the passage with `map.py
   words`. Choose the in and out as source frames, the out exclusive, ending before the next speaker's first word or in
   a pause. Render at the source's exact rate (24000/1001, not 24), so insert frame k is source frame in + k
   ([timing](../references/timing.md) §5 has the frame arithmetic). Transcript word times are estimates, often a tenth
   of a second or more, so each anchor records `source_t`, `uncertainty_s` and `verified_by` (a person at normal speed,
   or `none`). Done when every anchor has a start time, a frame and an uncertainty.
2. **Frame.** Inherit the host's context and state what the viewer must understand at each word, one score row per
   anchor, reviewed before you build. Done when each anchor has a meaning line.
3. **Build the page.** Read [timing](../references/timing.md) §0, and §6 for reading windows. When the kit's blocks draw
   the insert, read [kit](../references/kit.md); otherwise read [engines](../references/engines.md) §4 for HyperFrames
   or §12 for Cavalry. When the graphics' look is open, read [look](../references/look.md). The anchors are its turns.
   In HyperFrames, also write them as `appearsBy` motion assertions. Export `cues.json` from the page as in
   [create](create.md) step 3, with the host passage's fingerprint and the source-to-host time map. Review each render
   on word sheets, `frame_sheet.py INSERT --at T1,T2 --words map/ALIAS/words.json --offset INf --out qa/anchors.png` at
   the anchors and the same with `--every 0.5` over the whole insert. Done when every turn lands within one frame of its
   anchor estimate, said in those words.
4. **Composite in context.** In a paper edit, give each spoken line its own `~` cutaway
   ([paper-edit](../references/paper-edit.md) §5 has the `~` lines), each range continuing frame for frame from the
   last, and keep the pauses between lines. For an editor, hand over a master at the exact rate (ProRes 422 HQ when they
   will re-encode), the in and out frames and the timing source, as repairs by timecode. Done when `cut.py check` passes
   or the hand-back lists hashes.
5. **Check in context.** The insert's first and last frames carry picture, never black. Done when the picture outside
   the passage is unchanged (`compare_versions.py`, the passage as `--expect`), the sound outside it is unchanged
   (`sync_check.py NEW OLD --outside A,B`, the passage in the old file's seconds), the sync group is clean at the
   anchors, and anything unmeasurable is reported as not assessed.
6. **Shared last steps.** Check, Screen, Revise and Deliver, from [loop](../references/loop.md). Re-cutting the
   dialogue moves the words, so the insert is re-timed and its list re-exported.

## By kind

- **Graphics over footage.** Build at the film's size and frame rate over a transparent background, and set key
  frames beside the look's references (`look.py compare`) before the full render. Render motion as a PNG MOV (or
  ProRes 4444, or VP9 with alpha) and a still as one PNG; register them with `map.py add --role broll` or
  `--role still`, and place them with `~ over ALIAS [SECONDS] [+N] [fade F]` under the line they belong to.
  `cut.py check` refuses one at another frame rate or without transparency. Step through the frames where it lands
  and leaves; it sits clear of faces and captions. In Cavalry, ask the person's yes to what leaves the machine before
  the first call ([engines](../references/engines.md) §12).
- **Pinned graphics, titles behind a person, blurs.** Read [spatial](../references/spatial.md) first. Write the line in
  `film.md`, read the surface's corners or the person's position from a still, then make the layer (`track.py ALIAS --at
  TIME --region ... --from T1 --to T2 --name screen --project P`, or `matte.py` for a person) and write it under the
  line (`pin`, `behind`, `blur`). `cut.py check` errors on a missing, stale or wrong-source layer. Look at the start,
  middle and end of each effect; a person checks every frame of a blur before the film leaves the machine, and a blur is
  not anonymisation.

## First question

"Which passage, and what must the viewer understand at each word?"
