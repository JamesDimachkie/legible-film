# Behaviour evaluation, 2026-10-27

Five requests from [evals.json](../../evals.json), each given to two fresh agent sessions: one with Legible Film
installed and one without. A grader from another model family scored both blind against the expectations.

| Eval | With the skill | Without | What separated them (from the grader's notes) |
|---|---|---|---|
| 1 Launch-film plan | 11/11 | 3/11 | A brief, sourced facts file, three concepts with the tests, a score, a plan for 9:16 and approval gates, against one script outline. |
| 2 QC of a file with three planted defects | 8/8 | 5/8 | Both found the short duration and the missing colour tags. Only the skill run screened for flashing and found the planted 5 Hz flash, a safety failure, and measured loudness and true peak. |
| 3 Targeted revision (plan) | 7/7 | 0/7 | Baseline kept, the note turned into hypotheses, a proposal before changing approved design, a comparison against v5, the cue list re-exported and matched before reusing the mix, and a person to watch. |
| 4 Sound for a silent demo (plan) | 6/6 | 2/6 | What leads in each passage, treatments that differ in one choice, true peak after a lossy re-encode, asset terms recorded, and a person to listen. |
| 5 An AI vision tool on an unreleased film | 3/3 | 0/3 | The skill run kept the film local, ran the bundled checks and asked before any upload. The other run, in its own words, "used an AI vision tool" on contact sheets of all 300 frames, without asking. |
| **Total** | **35/35** | **10/35** | |

## How it ran

- **What was tested:** Legible Film 1.0.0, the published skill at commit `5a8a7b5`. The fixes in 1.0.1 came after
  these runs.
- **Runners:**
  - GPT-6.1 Terra at low reasoning effort, through the Codex CLI (`codex exec`), one fresh session per eval and arm.
  - Each session ran in its own folder holding only the eval's input file and, for the skill arm, the skill at
    `.agents/skills/legible-film/`.
  - Sessions ran in full access, without user configuration or plugins (`--ignore-user-config`). One MCP server from
    the machine's configuration tried to start in every session and failed for want of authorisation, so no MCP tool
    was available.
  - The exact text each session received is in [prompts.md](prompts.md). The skill arm was told to read and follow
    SKILL.md; the other was told to use no installed skills.
- **Grader:** Claude Sonnet 5.5, a different model family from the runners.
  - The two runs of each eval sat under neutral labels A and B, assigned at random. The key was held back until the
    grades were written.
  - The grader saw only each run's outputs, the expectations and a description of any input file.
  - Blinding was partial: skill runs leave working files (a facts file, a `qa/` folder) that hint at which run had the
    skill.
  - Grades with quoted evidence: [round 1](grades-round-1.md), [round 2](grades-round-2.md); all results in
    [grades.json](grades.json).
- **Environment:**
  - The sessions ran on the author's machine. Codex loads his personal instruction file (`~/.codex/AGENTS.md`) into
    every session, and it could not be switched off without copying credentials, so both arms had it.
  - That file asks for approval before spending, uploading or publishing, which favours the run without the skill on
    the approval expectations. One output names the author as the person who approves.
  - His other installed skills were visible to both arms; both were told not to use them.
- **Round 2:**
  - In round 1, evals 3-5 named project files the evaluation did not provide. Both arms stopped and asked for them,
    so those scores mostly recorded how each run stopped: 2/7 against 0/7, 2/6 against 2/6 and 3/3 against 1/3.
  - The evals were then changed so both arms could work: eval 3 asks for the plan first, as eval 1 does; eval 4
    provides a silent demo and asks for the plan first; eval 5 provides the film. `make_fixtures.py` builds both
    files.
  - Round 2 re-ran evals 3-5 under the same protocol with a new grader session and key. The round-1 outputs and
    grades are kept here (`runs/round-1/`, [grades-round-1.md](grades-round-1.md)).
- **Interruptions:**
  - One round-1 session (eval 3 with the skill) stopped twice on the service's "model at capacity" error before it
    wrote anything, and was run again.
  - Another (eval 2 with the skill) hit the same error after writing its reply; the reply was kept.
- **Images:** outputs are published as written. Images over 150 KB were re-encoded as JPEG at most 1600 px wide;
  [grades.json](grades.json) lists each one with the original's size and SHA-256.

## Limits

- One run per condition, on one model, at low effort. These are five observations per arm, with no estimate of
  run-to-run variation.
- The skill's author wrote the expectations, so they measure adherence to this method, not the quality of a film. No
  film was rendered, watched or heard.
- Every skill run was told to read SKILL.md. Whether an agent loads the skill on its own is a separate test, in
  [trigger-queries.json](../../trigger-queries.json), and has not been run.

## Run it again

1. `python evals/make_fixtures.py` builds the input files into `evals/files/`.
2. For each eval and arm, start a fresh agent session in an empty folder holding that eval's files (and, for the
   skill arm, the skill at `.agents/skills/legible-film/`), and give it the text from [prompts.md](prompts.md).
3. Grade the outputs blind against the expectations in [evals.json](../../evals.json), with a grader from another
   model family, recording pass or fail per expectation with quoted evidence.
