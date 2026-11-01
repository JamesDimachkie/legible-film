# Suite validation, 2026-10-29

How far the evaluation suite was validated on 2026-10-29, on a 2.0 pre-release build. It is an experimental suite,
not a completed recipe benchmark. The skill tree it checked has the `run.py --hash-skill` SHA-256
`711f398cc2b84edda846685b25e2dff9c246864179c6c48975e9eebb58351a3c`.

## Task coverage

`C` means a positive and a deliberately bad control separated on the stated **single target check**, not that the
positive passed the full task. Every positive remains inconclusive because scorecard and independent or human
reviews were not completed. `N` means no validated positive/negative control exists for that task. A duration-only
check is not counted as proof of an unmeasured story, beat, frame or word-preservation criterion.

| Kind | Everyday | Hard or judgement | Target evidence |
|---|---|---|---|
| Quick edits | `quick-trim` C | `quick-ambiguous-crop` C | Correct source excerpts; question-shaped reply |
| Captions | `captions-basic` C | `captions-offset` C | Wrong name; 1.2 s offset vs unverified publisher cues |
| Interview | `interview-tighten` C | `interview-retake` C | Planted near-silence; repeated source excerpt |
| Shorts | `short-one` N | `short-two` N | Framing, safe zones and self-contained story need real controls |
| Tutorial | `tutorial-waits` C | `tutorial-small` C | Three sampled screen states; planted red cursor |
| Montage | `montage-beats` C | `montage-ending` C | Sampled shot identity only; beats and ending unverified |
| Explainer | `explainer-voice` C | `explainer-mix` C | Voice excerpts present vs same-duration music-only output |
| Launch film | `launch-simple` N | `launch-qualifier` N | On-screen facts, qualifiers and craft need controls |
| Music video | `music-visual` C | `music-lyric` N | Sampled shot identity only; lyric readability unverified |
| Generated clips | `generation-cap` C | `generation-limit` C; `generation-false-footage` N | Question-text proxy only; no independent paid-call audit |
| Premiere | `premiere-removal` C | `premiere-mixed` C | Synthetic XML caption fates, shifts and planted cut words |
| Pause removal | `pauses-basic` C | `pauses-retake` C | Planted near-silence; repeated source excerpt |

Current-source regrading: **19 targeted pairs separated, 0 target separations failed, 6 tasks not run**. The
positive/negative video pairs for the cut, pause, retake, tutorial and montage tests keep the same approximate
duration, so the target check has to detect more than a length difference. The generated-clip controls are canned
responses, not agent runs. No control proves no words were lost everywhere, perceptual quality, rights clearance,
or an actual external-call boundary.

`evals/selftest.py`: **38 passed, 0 failed, 0 not run** in the last offline harness run. All 25 catalogue tasks
were staged once with fixture inputs; no real agent was started. The two local test-double clients exercised
staging, streamed-event parsing, final text, file inventory and grading; their numbers are not agent smoke results.
Real Claude and Codex smoke runs: **0 run, 2 not run**; the validation used no paid services, uploads or network
access beyond public media. The runner does not itself enforce those restrictions.

The `check.py` path was exercised on the rebuilt quick-trim control: **3 pass, 2 look, 0 fail, 2 human checks,
0 skip**. The looks were loudness (-17.0 LUFS vs its -14 target) and the last 10 ms of audio. The full grade is
inconclusive. An earlier control's missing MP4 fast-start flag was fixed in the control builders and the check was
rerun. A neutral packet and a one-frame-per-second contact sheet were also generated, with no external reviewer.

## Reference limitations

The NASA publisher reference and a local offline base.en draft agreed on 38 of 39 tokens; `Padi` in the source
caption was `Patty` in the draft. Their estimated word midpoints differed by a median 0.196 s and a maximum 0.661 s.
The draft assigned a zero-length interval to `Thank`. This is not a human transcript check or an error bound on
either source. The separate LibriVox draft also had one zero-length word; the explainer control records an
estimated adjustment in a separate file instead of changing the original. Neither transcript has been listened to.
The NASA full interview's music provenance remains unresolved for redistribution.

## Findings, and what became of them

The validation found four defects in the skill's scripts. All four are fixed in 2.0, each with a self-test case.

1. Three 24 fps segments ending at 2.666... s left a gap in the picture at 8 s (an extra output frame from rounding).
   Fixed; the case is "24 fps rounded edges tile on the output frame grid" in `scripts/selftest_cases/footage.py`.
2. `exchange.py compare` called a caption unchanged when an edit split one of its words, because it tested whether
   a word's ID occurred, not whether its whole source interval survived. Split words are now named; the case is "a
   word an edit cuts into is partly cut and its caption is not unchanged" in `scripts/selftest_cases/exchange.py`.
3. `captions.py build` dropped an input word's `estimated` flag from its summary. Fixed; the case is "the build
   summary preserves an existing estimated word flag" in `scripts/selftest_cases/captions.py`.
4. Local transcription failed outright when `onnxruntime` (faster-whisper's voice detector) was missing. It now
   drafts without voice detection and says so; the case is "missing onnxruntime falls back" in
   `scripts/selftest_cases/map.py`.

The scorecard adapter (`evals/grade_task.py`) binds each card to the delivered file (`file_sha256`) and each judged
dimension to its reviewer's model family (`judge_family`). `evals/selftest.py` runs apart from the skill's self-test
([evals/README.md](../../README.md) gives the command).

## Scale

One run in each of 25 tasks x 3 arms x 2 clients is 150 sessions; at the 30-minute per-run timeout, the serial
ceiling is 75 hours before fixtures and review. Four earlier, different 1.2.5 Claude tasks reported a mean of
753.5 seconds and about $5.00 per session. Applying that small sample to only the 75 Claude sessions gives about
15.7 hours and $375 reported cost; this is an extrapolation, not a quote or authorization. Codex, independent
judges, repetitions and actual billing remain unmeasured.
