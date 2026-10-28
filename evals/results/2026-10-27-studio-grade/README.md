# Behaviour evaluation: studio grade, 2026-10-27

Eval 6 from [evals.json](../../evals.json), given to two fresh agent sessions: one with Legible Film 1.1.0 installed
and one without. A grader from another model family scored both blind against the expectations.

| Eval | With the skill | Without | What separated them (from the grader's notes) |
|---|---|---|---|
| 6 Studio-grade plan for someone new to video | 9/9 | 2/9 | The skill run planned a spend line with a fallback for each item, moving concept sketches and an animatic before any choice, styleframes of the densest text and the proof, questions about paid use, countries and term before buying, a viewer-comprehension bar with a loop on the weakest moment, and a facts file. The other run gave one written direction, a spending table and an approval gate, and assumed organic use. |

Three passes were borderline ([grades.md](grades.md)). In the skill run, the reference study is promised but names no
sources and comes after a recommended direction, and the facts file adds the brief's description of the app as an
extra entry. In the other run, the licence statement covers only an assumed organic use.

## How it ran

- **What was tested:** the `skills/legible-film/` folder at commit `fe30898`, unchanged in the 1.1.0 release.
- **Runners:**
  - GPT-6.1 Terra at low reasoning effort, through the Codex CLI (`codex exec`), one fresh session per arm.
  - Sessions ran in full access, without user configuration, MCP servers or plugins (`--ignore-user-config`).
  - The skill arm had the skill at `.agents/skills/legible-film/` and was told to read and follow SKILL.md; the other
    was told to use no installed skills. The exact texts are in [prompts.md](prompts.md).
  - The sessions took 60 s (with the skill) and 30 s (without).
- **Grader:** Claude Sonnet 5.5.
  - The two runs sat under neutral labels A and B, assigned at random. The key was held back until the grades were
    written.
  - Blinding was partial: the skill run left a plan, a budget and a facts file beside its reply.
- **Environment:** as in the [1.0.0 round](../2026-10-27/README.md#how-it-ran). The author's personal Codex
  instruction file was loaded into both sessions. It asks for approval before spending, which favours the run without
  the skill on that part of expectation 1.
- **Outputs** are published as written, in [runs/e6](runs/e6); results are in [grades.json](grades.json).

## Limits

- One run per arm, on one model, at low effort: one observation each, with no estimate of run-to-run variation.
- The skill's author wrote the expectations, so they measure adherence to the studio method, not the quality of a
  film. No film was made, watched or heard.
- The request asked for a plan. It does not show how the gates, the study or the loop hold up across a real
  production.
