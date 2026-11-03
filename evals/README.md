# Evaluations

## Film-output evaluations for 2.0: experimental

`tasks.json` defines 25 requests across quick edits, captions, interviews, shorts, tutorials, montages,
explainers, launch films, music videos, generated clips, Premiere and pause removal. Each kind has an everyday and
a hard case. The grader keeps four states: **pass**, **fail**, **review** and **not_run**. A task is inconclusive until every
required check and review has evidence; a failed check makes the task fail. The catalogue and the harness do not,
on their own, show that a recipe produces a good film.

The current corpus is narrow: many tasks share one NASA interview, one CC BY film and one CC BY music track. The
shorts use the full interview; the tutorial and Premiere timeline are simulated. NASA's publisher captions are
not independently verified word-for-word; the XML word edges are estimated. The music tracks' beats are not yet
independently annotated. NASA's page and general policy did not independently establish the music rights in the
full interview: settle that before redistributing it or a derived film. The pinned Tears of Steel and music sources
require the attribution recorded in `media/sources.json`. The media and generated fixtures belong outside the
repository and must not be committed.

### Prepare the public inputs

From the repository root, use a scratch folder outside the repository. The local corpus import verifies each
SHA-256 and makes no network request; `CORPUS_DIR` is a local folder holding the same files. `--fetch` opts into
downloading only URLs in `media/sources.json`, and a hash mismatch is an error. `build_extra.py` expects the
Tears of Steel, NASA interview, LibriVox and Evening Melodrama files as well as the NASA captions.

```powershell
python -I evals/media/fetch.py ../work/cache --from-corpus CORPUS_DIR video/mather_interview.webm references/mather.srt speech/tale.mp3 music/evening_melodrama.mp3 video/tears_of_steel_720p.mov
python -I evals/with_lock.py --lock HEAVY.lock -- python -I evals/build_fixtures.py ../work/cache ../work/fixtures
python -I evals/with_lock.py --lock HEAVY.lock -- python -I evals/build_extra.py ../work/cache ../work/fixtures
```

On a machine that runs several jobs at once, `with_lock.py` makes renders, transcriptions and real agent runs take
turns: it waits for 1000 MiB of available memory and the exclusive lock, and reports a lock older than 45 minutes
instead of deleting it. These fixtures do not make a publisher transcript into ground truth: a person must listen and
check text and word edges. `draft_asr.py MEDIA --model LOCAL_MODEL_DIR --out DRAFT.json --length 12` uses an
already-cached optional faster-whisper model without a network download or VAD; take the lock for it.
`check_alignment.py REFERENCE.srt DRAFT.json` compares a locally generated word-timed draft with the publisher cues, but
neither is an independent human check. On the ten-second excerpt, offline base.en ASR agreed on 38 of 39 tokens and
spelled the name `Patty` where the publisher captions say `Padi`. The median difference between cue-proportional word
midpoints and the ASR midpoints was 0.196 s; the maximum was 0.661 s. Those are differences between two estimates, not
measured alignment errors. Listen to the name, all words and edit boundaries next.

### Stage or run

The runner stages by default and does not start an agent. Each run gets a fresh folder, its own copied inputs and a
preserved input baseline. Task answers stay in the fixture reference folder. These commands select one task, a
kind or the whole catalogue; run each desired runner and arm separately:

```powershell
python -I evals/run.py interview-tighten --fixtures ../work/fixtures --runs ../work/runs --runner codex --arm with
python -I evals/run.py --kind interview --fixtures ../work/fixtures --runs ../work/runs --runner claude --arm without
python -I evals/run.py --all --fixtures ../work/fixtures --runs ../work/runs --runner codex --arm with
```

Add `--execute` only after the actual provider, potential spending, and external execution environment are
authorized. On a machine shared with other heavy jobs, wrap that command in `evals/with_lock.py`. **The runner does not enforce a network,
provider-billing or filesystem-read boundary.** Do not execute it under a no-upload or no-paid-services constraint
until an external sandbox enforces that constraint. Claude receives a project-local `.claude/skills/legible-film`;
Codex receives `.agents/skills/legible-film` and an explicit prompt path. Codex automatic discovery and the absence
of ambient user-level skills in the without-skill arm have not been verified. `--ignore-user-config` and Claude's
project settings option alone do not establish a clean comparison. Resolve that isolation before interpreting
between-arm results. No credentials are copied or installed by the runner.

For an earlier arm, provide a separately exported skill, a declared ref and the content hash printed by
`python -I evals/run.py --hash-skill PATH`. Use `--arm earlier --earlier-skill PATH --earlier-ref REF
--earlier-sha256 HASH`. The bytes are pinned but the declared ref is not verified by this no-Git runner. Verify the
export's origin separately. Each run stores `run.json`, full `transcript.jsonl`, stderr, the final response,
changed and removed files, wall time, reported turns and tool calls, and reported usage or cost where available.
For Codex, `--max-turns` is not enforced by the current CLI command; the wall-time limit still applies.

### Grade and review

```powershell
python -I evals/grade_task.py TASK --run RUN_FOLDER --fixtures ../work/fixtures --out RUN_FOLDER/grade.json
python -I evals/judge_packet.py TASK --run RUN_FOLDER --out ../work/blind/NEUTRAL_ID
python -I evals/report.py ../work/runs --out ../work/report.md
```

Add `--skill-check` to the grader only under the heavy lock: it runs the skill's `check.py` on a delivered file.
A `look` becomes review and `skip` remains not_run; neither is converted into a pass. The neutral packet includes the request, the
original inputs, produced artifacts, hashes and task-specific review criteria, without the run metadata or
transcript. Add `--sheets` under the heavy lock for timestamped one-frame-per-second contact sheets; they do not
show motion between frames or convey sound. Inspect artifact content and metadata for identity leaks before
independent review. Fill the template
with a reviewer type, independent model family or person, criterion state and specific evidence; then pass both
`--packet PACKET_DIR --judgment JUDGMENT.json` to the grader. For a model review, the run must record the actual
producer family with `--producer-family`; a reviewer of the same family is rejected. A model review cannot satisfy
the human normal-speed viewing, listening or publisher-transcript verification criteria. The no-spend criterion
stays not_run until an independent execution audit is integrated; absence of a tool call in a transcript is not
proof of no external calls.

If a compatible `scorecard.json` becomes available, pass `--scorecard PATH`. Its `file` must name the delivered
video relative to the workspace and `file_sha256` must match its bytes. A judged dimension also needs a
`judge_family` different from the run's recorded `producer_family`. The shared scorecard spec currently lacks those
machine-readable fields; add them when the scorecard is integrated. The provisional eval threshold is 6/10 per listed
dimension; it is not a delivery gate and has not been calibrated against human judgments or degradations.
Missing or unbound dimensions remain not_run. Reports show pass/fail denominators separately from review and not_run,
scorecard means only for supplied scores, process means only for recorded measurements, and recipe locations to
inspect. A failure points to a recipe for investigation; it does not establish the cause.

### What the checks actually prove

The suite's validation record from 2026-10-29, with the defects it found and their fixes, is in
[results/2026-10-29-suite-validation](results/2026-10-29-suite-validation/README.md).

- `video` probes one output's duration and aspect ratio. It does not prove a correct shot, transcript, codec,
  framing or burned-in caption. `exists` proves only the presence of a file.
- `captions` compares words and approximate cue times with publisher captions. Zero token mismatches and a
  0.8-second median cue-based tolerance are provisional. This is agreement with an unverified reference, not WER
  against checked speech or a word-edge measurement.
- `audio_chunks` correlates a few short source excerpts with the delivered sound. A 0.30 threshold is a provisional
  proxy; missing other words, repeated takes, speed changes and music can evade or confuse it. `silence` measures
  near-silence at -45 dB; it does not find every pause or establish a clean join.
- `audio_repeat` checks whether the known false-start excerpt occurs more than once; its 0.45 correlation threshold
  is provisional and it cannot detect a different false take. `screen_states` samples three frames against the
  known synthetic tutorial states. `cursor_presence` checks the planted red cursor twice per second. These do not
  prove pointer continuity or text legibility between samples, and the cursor check is not a general detector.
- `shot_sequence` compares sampled output frames with the three supplied source shots and flags a confidently
  identified repeated or missing shot. It samples at two frames per second; rapid repeats, reframes, transitions,
  colour treatments and overlays can make it inconclusive or evade it. Musical beat alignment remains unscored.
- `caption_changes` compares every synthetic cue's fate and, for moved cues, its shift, against hand-defined XML
  answers; the planted stale case also requires the cut words. `inputs_unchanged` compares the editor XML files to
  the preserved pre-run copies. Neither establishes that estimated word edges match the recording or covers a
  real editor's projects. `question` counts question marks and topic words; it does not establish a good question
  or no spending.
- The task-specific review criteria, scorecard and the skill's checker remain separate. Strong beats, repeated
  shots, subject framing, text readability, caption safe zones, self-contained story, audio quality, word-accurate
  speech, changes to an editor's files, and real paid-call monitoring are not yet reliably automated here.

`python -I evals/selftest.py --work ../work/selftests` runs offline harness counterexamples. Under the lock,
`python -I evals/prove_media.py ../work/fixtures ../work/proof`, `python -I evals/prove_montage.py
../work/fixtures ../work/montage-proof`, `python -I evals/prove_tutorial.py ../work/fixtures ../work/tutorial-proof`,
`python -I evals/prove_captions.py ../work/fixtures ../work/caption-proof` and `python -I evals/prove_explainer.py
../work/fixtures ../work/explainer-proof` test a subset of targeted good and bad controls using real media and the
skill's scripts. The explainer control requires an offline ASR draft saved as `references/tale-asr-draft.json`;
its zero-length word is given an explicitly estimated boundary in a separate copy, and the captions are unverified.
The caption control builds cues separately with a 50-character line limit after the default
builder rejected the full reference; that is not proof of a readable captioned film. These controls do not provide
full gold solutions or prove all 25 graders. Run the
independent-model and human reviews, and make and validate task-specific good and bad solutions, before using the
suite as a recipe-tuning benchmark. Do not treat a duration-only bad control as proof that a grader detects the
failure the task is intended to expose.

### Full-run scale and cost

The minimum matrix is 25 tasks x 3 arms x 2 runners = 150 agent sessions, before repetitions and judging. The
default 30-minute timeout implies a 75-hour serial ceiling if all sessions reach it; setup, fixture builds and
judging are additional. An earlier four-task Claude 1.2.5 trial reported 521-1019 seconds and $3.97-$5.99 per
session (mean 753.5 seconds, $5.00). Applying that small, different-task sample only to the 75 Claude sessions
would imply roughly 15.7 hours and $375 in reported cost; this is not a quote, a billing prediction or authorization.
Codex and independent-judge costs and durations are unmeasured. More than one run per cell is needed to estimate
variation; predeclare repetitions and randomize execution order before drawing conclusions.

## Routing eval for the 2.1 reshape: experimental

`reshape-routing.json` freezes 10 development prompts, the five sealed held-out prompts (by id, expected path and
rules only) and route checks 16-20, each with its expected path (`create`, `cut`, `insert`, `sound`, `editor`,
`quick`, or `no-skill`), its forbidden reads and runs, its frame expectation and one scripted person reply. It also
freezes how a session's route is read: for a candidate with `paths/`, the first `paths/*.md` read; for 2.0.0, the
first path-mapped file read or run (`kit.md`, `new_film.py` create; `paper-edit.md`, `map.py` cut; `sound.md`
sound; `qc.md` quick), with `recipes.md` resolved by the recipe a partial read covers, or else the first recipe
heading, then mapped script, the agent names after reading it. A session that loads the skill and resolves to no
path is **unscored**: listed, never a pass. `command-names.json` holds the 36 command names and aliases in 2.0.0's
`SKILL.md`. The held-out prompts stay outside the repository; `heldout.sha256` seals them and the harness refuses a
file that does not match.

```powershell
python -I evals/trigger_run.py routing --cases evals/reshape-routing.json --variant old=BASELINE/skills/legible-film --reps 3 --host claude --out OUT --work SCRATCH
python -I evals/trigger_run.py summary --out OUT --cases evals/reshape-routing.json
```

Sessions run `--workers` at a time (2), each once `--min-free-gib` (2) is free, in a fresh scratch project holding
the whole variant skill and stub media built with FFmpeg. They are planning runs, one agent CLI process each with
every heavy step denied, so they take no heavy-job lock; their timings are not comparable as speed. Plan mode: Write and Edit only inside the project; Bash allowed, with every build, spend,
network, install and heavy step denied and logged by a guard hook (patterns in the cases file; a build or spend
attempt fails the prompt); at most eight turns on Claude Code and forty steps on Codex (`codex_turn_limit`: Codex
counts every command as a step, and forty is the smallest tested cap at which 2.0.0 Codex sessions on P01 and P05
reached their first question or first committing step; the cases file records the measurement); one scripted reply
when the first exchange ends with a question.
`--sets route` adds route checks 16-20, on a candidate only (a skill with `paths/`). `route_checks.py` builds their
project fixtures in each session's scratch project with the variant's own scripts (19: a create project with a stub
master registered from a plan cue list by `project.py add-version`; 20: a paper project rendered once by `cut.py
render`) and scores what §13 states for each: 16 create, `engines.md` read over its Tesseract section, a frame and a
plan cue list written, no `tsrct` run and the hand-off named, with no `tsrct` on PATH; 17 quick and `listen.py
transcript` run; 18 quick with no paper edit and no triad; 19 `screen.py` run and never `cut.py`; 20 `exchange.py
write` run and the XML it wrote parsing with the version's clip count and duration. The frozen scorer is not changed. `--host codex` runs `codex exec --json` on the person's normal Codex home,
isolated only by per-run `-c` overrides that disable plugins, apps, memories, MCP servers and every installed user
skill, with the variant staged in the project's `.agents/skills`; Codex has no per-tool deny hook, so attempts are
read from its command events and the session stops at the first build or spend attempt. Its global `AGENTS.md`
still loads.

Scoring (`routing_score.py`) reads the stream, not the answer: the route; every skill file read before the first
action and its words (SKILL.md plus `loop.md` at 2.0.0 is 4,966); the first question and the frame fields it asks;
frame writes; forbidden and required reads and runs; attempts; reads of any other copy of the skill. The frame and
money-gate checks are keyword evidence kept with the text for a person to audit, not judgements. Results keep no
held-out prompt or answer text; the raw transcripts under `OUT` do, so keep `OUT` outside the repository.

## Earlier behaviour evaluations

### Behaviour (`evals.json`)

Eleven realistic requests, each paired with expectations describing what the skill should change in an agent's
behaviour: honest status (unwatched, unheard), the approval gates, a facts file, QC on the delivered file, baselines
for revisions, treatments chosen by listening, and (evals 6 and 7, added in 1.1.0) studio-grade plans for someone new
to video, for a consumer app and for an open-source command-line tool. Evals 10 and 11 test a captioned
vertical interview cut and a dialogue-over-music mix, including measured delivery checks and honest review limits.

To run one:

1. `python evals/make_fixtures.py` builds the input files evals 2, 4, 5, 10 and 11 use into `evals/files/`.
   It needs FFmpeg (libx264 and AAC), NumPy and Pillow. The footage inputs are synthetic; `files/answers.json` is
   for graders only and must not be given to either runner. Evals 10 and 11 have not been run.
2. Give the request to two fresh agent sessions on the same model, each in its own empty folder holding the eval's
   files: one with the skill installed and told to follow it, one without it.
3. Grade both runs' outputs against the expectations under neutral labels that hide which run had the skill, with a
   grader from a different model family. Record pass or fail per expectation, with quoted evidence.

### Triggering (`trigger-queries.json`)

Ten requests that should load the skill and ten near-misses that should not. Run each at least twice in a fresh
session and count how often the skill loads; tune the description when a near-miss triggers or a real request does
not.

## Results

Each round is recorded with its date, models and skill version. An evaluation without a row here has not been run.

### 2026-10-31: SKILL.md as a router, triggering and routing

Fresh `claude -p` sessions (Claude Code 2.1.314, claude-opus-5-5), each of the 20 trigger queries twice per variant
of SKILL.md, and four routing requests twice per variant. The full record is in
[results/2026-10-31-router](results/2026-10-31-router/README.md).

| Variant | Should trigger loaded | Should not trigger loaded |
|---|---|---|
| 1.x SKILL.md (34.6 KB) | 17/20 | 2/20 |
| Router with the final description | 18/20 | 0/20 |

All 24 routing answers named an expected command and reference and none named a forbidden one. The description was
tuned on these same queries, so the margin is in-sample.

### 2026-10-28: studio grade against 1.0.1, evals 6 and 7

This round compares versions, not skill against no skill: two runs per eval with 1.1.0 and two with 1.0.1, which has
the method but not studio grade, on the same runner. A checklist grader and a judge who never saw the expectations
both worked blind to the version. The full record is in
[results/2026-10-28-studio-vs-1.0.1](results/2026-10-28-studio-vs-1.0.1/README.md).

| Eval | Checklist, 1.1.0 | Checklist, 1.0.1 | Pairs the judge gave to 1.1.0 |
|---|---|---|---|
| 6 Studio-grade plan, consumer app | 9/9, 7/9 | 2/9, 3/9 | 2 of 2 |
| 7 Studio-grade plan, command-line tool | 9/9, 8/9 | 3/9, 4/9 | 2 of 2 |

The judge preferred 1.1.0 for leading a newcomer and for money and rights. It found the 1.0.1 plans more concrete
about what appears on screen.

An earlier draft of 1.1.0 split the judge's pairs one each. The changes that followed are described in the record.

### 2026-10-27: behaviour eval 6 (studio grade) on a 1.1.0 draft

Same runner, grader and protocol as the round below, on the skill at commit `fe30898`, before the changes above.
With the skill 9/9, without 2/9, from one run per arm. The full record is in
[results/2026-10-27-studio-grade](results/2026-10-27-studio-grade/README.md).

### 2026-10-27: behaviour evals 1-5 on Legible Film 1.0.0

Runners GPT-6.1 Terra through the Codex CLI, one run per arm; grader Claude Sonnet 5.5, blind. Evals 3-5 were run
twice: in the first round they named project files the evaluation did not provide, so both arms stopped, and the
evals were changed to give both arms something to work on. The full record (exact prompts, every output, both
graders' notes, the environment and the limits) is in [results/2026-10-27](results/2026-10-27/README.md).

| Eval | With the skill | Without |
|---|---|---|
| 1 Launch-film plan | 11/11 | 3/11 |
| 2 QC of a file with three planted defects | 8/8 | 5/8 |
| 3 Targeted revision (plan) | 7/7 | 0/7 |
| 4 Sound for a silent demo (plan) | 6/6 | 2/6 |
| 5 An AI vision tool on an unreleased film | 3/3 | 0/3 |
| **Total** | **35/35** | **10/35** |

**Limits:**

- These are five runs per arm on one model.
- The expectations were written by the skill's author, so they measure adherence to this method, not film quality.
- Both arms shared the author's personal agent instructions, which ask for approval before spending, uploading or
  publishing.
- The trigger queries had not been run then; they were on 2026-10-31 (above).

### Earlier: a pre-release draft, evals 1-3

Run the same way on a draft before the final review: 25 of 26 expectations with the skill, 10 of 26 without. The
miss with the skill was a plan with no delivered-file QC in eval 1. That led to a change: step 1 and the brief
template now record how the delivered file will be checked, and the 1.0.0 run met that expectation.
