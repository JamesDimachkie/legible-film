# Hard-eval engineering pilot

The hand-authored positive control passes **22/22 automatic items, 90/90 points**. An output-empty run with all normal inputs scores **0/90**, and a run containing only confident checklist prose also scores **0/90**. No coding agent or blind judge was run. “Perfect” is the positive control's directory name, not a judgement of its film quality.

```text
Automatic points, development seed 20261028       0                 45                 90
Hand-authored positive control                   |██████████████████████████████████████| 90
Plausible near-miss control                      |████████████████████████              | 57
Empty outputs                                   |                                      |  0
Checklist prose only                            |                                      |  0
```

| Control | Automatic result | Expected failures actually observed |
|---|---:|---|
| Positive control | 90/90, 22/22 items | None |
| Empty outputs, original inputs present | 0/90, 0/22 | Every item |
| Checklist-only, including unsupported watching/listening claims | 0/90, 0/22 | Every item |
| Near miss | 57/90, 14/22 | A1: one-frame error; R3: global helper changes approved opener; B2/B3: qualifier six frames early; D1–D4: stale copy, wrong rights, false release and no missing-decision question |
| False audio evidence | 18/26 on task 101 | A4/A6: supplied “evidence” is the approved mix, not delivered PCM |
| Audio samples shifted 18 ms late | 26/32 on task 103 | B5 only |
| Reference-style flashing with intact legal panels | 27/32 on task 103 | B3 only |
| Audio transport shifted 18 ms by mux timestamps | 26/32 on task 103 | B5 only |

The B2/B3 dependency is intentional and documented: a run cannot earn the flash outcome by dropping mandatory content. These eight controls are not eight independent agent observations. The false-audio and transport mutations target measurement custody, not merely omission of an output.

## Fixture verification and reproducibility

`make_hard_fixtures.py --check` passed **15/15** checks on the main seed. Checks decode the actual MOV/MKV/MP4 and PCM, including the single-frame insertion, partial Y, early qualifier, +18/+30/+48 ms delayed attacks, five-millisecond clipped flat top and wrong colour conversion under correct tags. The public revision source was rendered and compared with the baseline; the hidden corrected render differs in precisely frames 174–179 and only the allowed qualifier region. The reference contains ten large transitions in one second.

An initial identical-seed rebuild found changing Matroska container identifiers: 40/41 public files were byte-identical. The encoder and supplied revision renderer now use FFmpeg's bitexact mux flag. Two fresh builds then produced **41/41 identical public file SHA-256 hashes**. This establishes reproducibility on this exact local stack, not across arbitrary FFmpeg builds.

The development verification seed 20261103 moves the insertion to frame 93, the glyph damage to [45,48), the qualifier gap to [172,180), audio delays to +20/+32/+50 ms, and clipping to sample 297648. It also passes 15/15 fixture checks and all eight control expectations, with the same scores. Seed 20261104 additionally changes the supported result to 17/24, the brand patch to (55,145,205), and the audio slope to 7 ms/s with delays +21/+35/+56 ms. It passes 15/15 fixture checks and all eight control expectations too. These are exercised development variants, **not held-out results**. To reproduce them, build each seed into a new fixture folder and run the pilot against it.

## What the positive control actually contains

* Task 101: the known correct intervals/numbers, full-resolution PNG evidence decoded from the input, and a decoded 48 kHz stereo WAV. The author knew the answers.
* Task 102: a copy of the public project with a closing-scene-only override, rendered by the public source. The hidden answer movie was **not** copied into the run. The grader compares all frames, outside-mask pixels, PTS, PCM and cues.
* Task 103: an original minimal collection-to-index graphic rendered in wide and tall compositions, protected legal panels, a visible milestone lamp and the supplied effects placed by attack/apex/end. The grader found zero-millisecond waveform offsets at all three cues and no wrong lamp frames. Post-second-AAC 4x peak estimate was approximately **−12.25 dBFS** for both outputs, under this task's −1 dBFS ceiling.
* Task 104: the recomputed bounded copy, three replacements and one permitted asset, a held release, and one owner-approval question.

The positive film is intentionally only an engineering control. No one watched it at normal speed or listened. A decoded defect frame was visually inspected during authoring; that is not a playback review. Comprehension, aesthetic quality and sound quality remain unjudged.

## Reproduce locally

Run from `evals/hard/`, with `$hardPy` set to a Python 3.12 executable. The generator refuses to overwrite an existing fixture set, and the pilot builder requires a new or empty output directory.

```powershell
$hardPy = '<path-to-python-3.12>'
& $hardPy -I make_hard_fixtures.py --out fixtures --check
& $hardPy -I build_pilot.py --fixtures fixtures --out pilot-reproduction
# Or re-grade the already built controls without rendering again:
& $hardPy -I build_pilot.py --fixtures fixtures --out pilot --grade-only
# A single task/run:
& $hardPy -I grade_hard.py --fixtures fixtures --run pilot/perfect/h103 --task h103 --out pilot/h103-only-grade.json
```

The full pilot before adding the timestamp mutation took 38.50 seconds. With all eight controls, a subsequent main-seed grading-only pass took 58.48 seconds; the first verification seed took 56.28 seconds. The second verification seed's complete build and eight-control pilot took 58.16 seconds. These are local author-control timings, not Codex run timings. No peak-process-memory benchmark was performed. The largest raster was 640×360 or 360×640; no paid or network services were used.

Environment: Python 3.12.10, numpy 2.3.5, Pillow 12.2.0, FFmpeg/ffprobe 9.0.2 full build. All Python invocations used an explicit Python executable with `-I`. No Git operation, repository/harness write, desktop playback, model runner, model judge or subagent was used.

## Evidence

Generated files are not committed. After the commands above, the evidence is:

* `fixtures/fixture-check.json`: the 15 fixture checks
* `pilot/pilot-results.json`: the eight controls, their failed items and whether each behaved as expected
* `pilot/<control>-grade.json`: item-level grades for `perfect`, `empty`, `checklist-only`, `near-miss`, `forged-audio`, `late-audio`, `unsafe-flash` and `timestamp-shift`

The original package validation found valid syntax, exact prompts, 41 listed public files, 15/15 fixture checks on seeds 20261028, 20261103 and 20261104, and all eight controls as expected on each seed. No agent was run.

The strongest remaining limitation is author/oracle bias: a positive control and these targeted mutations can expose broken grading paths, but cannot establish that this benchmark predicts the quality of real films or that either skill version will score below its ceiling. Those claims require independent oracle review, actual runner calibration and blind finished-film review.
