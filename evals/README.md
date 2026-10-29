# Evaluations

Two kinds of evaluation for the skill itself.

## Behaviour (`evals.json`)

Seven realistic requests, each paired with expectations describing what the skill should change in an agent's
behaviour: honest status (unwatched, unheard), the approval gates, a facts file, QC on the delivered file, baselines
for revisions, treatments chosen by listening, and (evals 6 and 7, added in 1.1.0) studio-grade plans for someone new
to video, for a consumer app and for an open-source command-line tool.

To run one:

1. `python evals/make_fixtures.py` builds the input files evals 2, 4 and 5 use into `evals/files/`.
2. Give the request to two fresh agent sessions on the same model, each in its own empty folder holding the eval's
   files: one with the skill installed and told to follow it, one without it.
3. Grade both runs' outputs against the expectations under neutral labels that hide which run had the skill, with a
   grader from a different model family. Record pass or fail per expectation, with quoted evidence.

## Triggering (`trigger-queries.json`)

Ten requests that should load the skill and ten near-misses that should not. Run each about three times in a fresh
session and count how often the skill loads; tune the description when a near-miss triggers or a real request does
not.

## Results

Each round is recorded with its date, models and skill version. An evaluation without a row here has not been run.

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
- The trigger queries have not been run.

### Earlier: a pre-release draft, evals 1-3

Run the same way on a draft before the final review: 25 of 26 expectations with the skill, 10 of 26 without. The
miss with the skill was a plan with no delivered-file QC in eval 1. That led to a change: step 1 and the brief
template now record how the delivered file will be checked, and the 1.0.0 run met that expectation.
