# Studio grade against 1.0.1, 2026-10-28

Does studio grade change what an agent does with a studio-grade request, compared with the same skill before studio
grade existed? Every session here had the skill installed: either 1.0.1, which has the method but not studio grade, or
1.1.0. Both versions received the same words. Two graders from another model family judged the results blind to the
version:

- a checklist grader marked each run against the eval's expectations ([evals.json](../../evals.json));
- a judge, who never saw the expectations, compared the runs in pairs. It was asked which plan would lead to the
  better film and the better experience for the person, and told to penalise padding and jargon.

## Result on the released skill (round 2)

| Eval | Checklist, 1.1.0 runs | Checklist, 1.0.1 runs | Pairs the judge gave to 1.1.0 |
|---|---|---|---|
| 6 Pocketfern: consumer app, X, $600 | 9/9, 7/9 | 2/9, 3/9 | 2 of 2, medium confidence |
| 7 Atlasfold: open-source command-line tool, README and LinkedIn, $400 | 9/9, 8/9 | 3/9, 4/9 | 2 of 2, medium confidence |

Across the four pairs, by criterion:

| Criterion | 1.1.0 | 1.0.1 | No clear difference |
|---|---|---|---|
| Leading a newcomer | 4 | 0 | 0 |
| Money and rights | 4 | 0 | 0 |
| Creative thinking | 3 | 0 | 1 |
| Craft that would show on screen | 0 | 4 | 0 |
| Honesty | 0 | 0 | 4 |

From the judge's notes:

- **The 1.1.0 plans:** they set out what the person will see and decide at each step, split the budget with a
  fallback per line, ask how the film will be used before buying music, and offer named directions to choose
  between.
- **The 1.0.1 plans:** they described the finished film more concretely on screen (the product named in the first
  frame, a visual thread, a generous end hold), but led to a single approval of written documents.
- **Weaknesses in the 1.1.0 plans:** the judge called one of them heavier than a 45-second README film needs, and
  noted that another left the film's middle to a screen recording that did not exist yet.

The full notes are in each eval's [preferences.md](round-2/e7/preferences.md) and
[grades.md](round-2/e7/grades.md) (eval 6: [preferences](round-2/e6/preferences.md), [grades](round-2/e6/grades.md)).

## How the result changed between rounds

**Round 1** (eval 6 only, on a 1.1.0 draft at commit `efd8e13`):

- The checklist gave the draft 8/9 and 8/9, against 2/9 and 3/9 for 1.0.1.
- The judge split the two pairs, one to each version, and gave creative thinking and on-screen craft to 1.0.1 in both
  pairs. The draft's plans deferred the film itself to later gates.
- No plan stated the quality bar's loop on the weakest moment, so expectation 7 failed for all four runs.

Two changes followed before round 2:

- **Lead with the film:** the first reply now opens with two or three directions the person can picture, and says
  how the film will be judged.
- **Fixes from an independent review:** craft passes became options rather than a house style, the study was bounded,
  and the bar's decisions were separated from viewers' answers.

Eval 6's two 1.0.1 runs were graded in both rounds, by separate grader sessions, and scored 2/9 and 3/9 both times.

## How it ran

- **Versions:**
  - 1.0.1: tag `v1.0.1`, `eea7f79`.
  - 1.1.0-draft: `efd8e13`.
  - 1.1.0: `0a06944`, the skill folder released as 1.1.0.
  - Each run folder's `SKILL-VERSION.txt` names its commit.
- **Runners:**
  - GPT-6.1 Terra at low reasoning effort, through the Codex CLI (`codex exec`), as in [earlier rounds](../2026-10-27/README.md#how-it-ran).
  - Each session ran fresh in its own folder, with the skill at `.agents/skills/legible-film/`, and was told to read
    and follow SKILL.md. The exact texts are in [prompts.md](prompts.md).
  - Sessions took 45-65 s.
  - The runner's built-in web search was available; one 1.1.0 run used it for a short desk study. No session played
    a film.
  - One MCP server from the machine's configuration tried to start in every session and failed for want of
    authorisation, so no MCP tool was available.
- **Graders:** Claude Sonnet 5.5, a different model family from the runners.
  - The checklist grader saw four runs under random letters.
  - The judge saw two pairs, with P and Q assigned at random and the sides reversed between the pairs.
  - The keys were held back until the grades and preferences were written.
- **Environment:**
  - The author's personal Codex instruction file loaded into every session, as in earlier rounds. It names the
    author, which is why some outputs address "James".
  - Runs on an interim commit, `8409434`, were superseded by the review fixes before they were graded. They were not
    graded and are not published.
- **Outputs** are published as written, in each round's `runs/`. The one edit: a reply that linked its own files by
  absolute local path has that prefix removed, so its links resolve here.

## Limits

- **Sample:** two runs per version per eval, on one model at low effort. Every preference is medium confidence at
  best.
- **Plans, not films:** no film was made, watched or heard. Which plan leads to the better film is the judge's
  forecast.
- **Authorship:** the skill's author wrote both requests and the checklist expectations, so the checklist measures
  adherence to the studio method. The judge is the measure less shaped by the author.
- **One grading family:** the judge and the checklist grader are the same model family.
