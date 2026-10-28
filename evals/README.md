# Evaluations

Two kinds of evaluation for the skill itself.

## Behaviour (`evals.json`)

Five realistic requests, each paired with expectations describing what the skill should change in an agent's
behaviour: honest status (unwatched, unheard), the approval gates, a facts file, QC on the delivered
file, baselines for revisions, and treatments chosen by listening. Objective expectations are checked by running the
scripts; the rest are graded from the agent's transcript and files.

To run one:

1. `python evals/make_fixtures.py` builds the media eval 2 needs (with planted defects) into `evals/files/`.
2. Give the prompt to a fresh agent session twice: once with the skill installed and once without it, same model,
   same folder.
3. Grade the transcripts against the expectations under neutral labels that hide which run had the skill, using a
   grader from a different model family than the runners. Record pass or fail per expectation, with the evidence.

## Triggering (`trigger-queries.json`)

Ten requests that should load the skill and ten near-misses that should not. Run each about three times in a fresh
session and count how often the skill loads; tune the description when a near-miss triggers or a real request does
not.

## Results

Results are recorded below with the date, the model and the skill version. Until a row exists, an evaluation has not
been run.

### 2026-10-27: behaviour evals 1-3

- **Runners:** GPT-6.1 Terra (Codex, priority tier, default effort), one run per condition, each in its own folder.
  "With skill": told to read and follow SKILL.md. "Without": told to use no installed skills.
- **Skill version:** commit `ab63dd2`, before the independent review's fixes.
- **Grader:** Claude Sonnet 5.5, a different model family from the runners, with neutral A/B labels assigned at
  random. Blinding was partial: the skill runs produced extra files (a facts file, a `qa/` folder) that hint at which
  run had the skill. The grader credited only quoted evidence and flagged two borderline passes.

| Eval | With skill | Without | What separated them |
|---|---|---|---|
| 1 launch-film plan | 10/11 | 2/11 | Brief, facts file, three concepts with a governing operation, the four tests, a boundary sentence and a score, against a timeline alone. Neither run planned delivered-file QC. |
| 2 QC of a file with three planted defects | 8/8 | 5/8 | Both found the short duration and the missing colour tags. Only the skill run screened for flashing and found the planted 5 Hz full-frame flash (a WCAG 2.3.1 failure), and it reported true peak after a lossy re-encode. |
| 3 targeted revision | 7/7 | 3/7 | Cue list re-exported and compared byte for byte before reusing the mix, shared helpers checked, a motion proposal before changing the approved design, and the normal-speed viewing given to a person. The run without the skill planned to watch and listen itself. |

Total: 25 of 26 expectations with the skill, 10 of 26 without.

The one miss with the skill (eval 1: no delivered-file QC in a plan) led to a change: step 1 and the brief template
now record how the delivered file will be checked.

**Limits:** one run per condition on one model; expectations written by the skill's author, so they measure adherence
to this method rather than film quality; no film was rendered or watched; evals 4 and 5 and the trigger queries have
not been run.
