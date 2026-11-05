# Final eval record: candidate 5cac88c against 2.0.0, clean, 2026-11-02

*Published with 2.2 on 2026-11-05, with personal paths replaced. It measures a pre-release candidate of 2.1, not a release.
The results of the same checks on 2.2 are in `../2026-11-05-2.2/`.*

This is the reshape's §13 eval of the candidate at `5cac88c78cb86042b0c9c8702f00af29ed33c13d` (`lf-candidate-pin3`)
against 2.0.0 at `754e079` (`lf-baseline`). **Only these clean numbers are reported.** The earlier runs
(`../2026-11-01-reshape-baseline/`, its `candidate-b20c341/` and `candidate-5cac88c/`, and the earlier trigger
records) stay as history.

## How it was run

- **Harness:** `evals/trigger_run.py` at `ff58cd5`.
  - Claude routing and trigger sessions run without the user's CLAUDE.md, rules or auto memory.
  - Every routing session's process tree ends with it.
  - Codex runs with every configured MCP server disabled by name and checked before it starts. No agent-started
    process was left running in any session.
- **Scorer:** `evals/routing_score.py` frozen at `bb40d87`, sha
  `dc94c8875da18e10243b5c061d4de98d854ff6c139c7389fef1216fc64fdd0d1`. Every change since the first scorer, with the
  sessions it moved, is in `../2026-11-01-reshape-baseline/README.md`.
- **Cases:** `evals/reshape-routing.json`, sha `4544d55eabde51841363cfd711dfa0160bce4a33da53501d4140d8508be684f2`.
  The held-outs are the v2 set, sealed by `evals/heldout-v2.sha256`.
- **Routing:** each arm ran P01-P10 and the five v2 held-outs, with route checks 16-20 on the candidate. Claude ran
  3 times at 8 turns; Codex ran 2 times at a 40-step cap.
- **Sessions moved by the final scorer fix:**
  - Both arms were scored again from their streams, which moved only the four Codex H1v2 sessions the earlier spend
    rule had stopped at a pricing look-up.
  - Those four were run again; every other session is as first recorded.
- **Triggering:** the 20 queries and the eight Opus queries, both arms in one run, 3 reps per query, Claude.

**Files:**
- `5cac88c-results.jsonl` and `2.0.0-results.jsonl`: routing rows with ids, routes and counts only.
- `*-summary.md` and `*-summary.json`: the runner's per-run tables.
- `comparison.json`: the measures below.
- `trigger-combined.md` and `.json`: triggering per query.

The raw streams stay in the local run folder.

## The criteria, per host (candidate 5cac88c)

| §13 criterion | Claude | Codex |
|---|---|---|
| Routing: 13 of 15 right in 2 of 3 Claude runs and both Codex runs, every path | **met** (14 of 15 on both hosts together) | **met** |
| Zero forbidden reads | **met** (0) | **met** (0) |
| Zero build attempts | **met** (0) | **met** (0) |
| On every planning prompt, the frame before any build step and only missing fields asked | **not met** (3 sessions build first; frame ok 14 of 30) | **not met** (2 sessions build first; frame ok 0 of 20) |
| Words read before the first action under 3,000 | **met on the median** (2,027); 39 of 45 sessions under | **not met** (median 14,807; 3 of 30 under) |
| Triggering no worse than 2.0.0 (20 queries and the eight Opus queries) | **met** (no worse on all 28) | not measured (trigger mode is Claude) |
| Route checks 16-20, each required | **not met** (17 fails; 16 not run) | **not met** (17 fails; 16 not run) |

2.0.0 does not clear §13's routing bar (10 of 15 with both hosts, editor path failing), so routing discriminates.
On Claude alone 2.0.0 does clear it (13 of 15), so on that host it does not.

## Routing per prompt (runs right: Claude of 3, Codex of 2)

| Prompt | Expected | 2.0.0 Claude | 2.0.0 Codex | 5cac88c Claude | 5cac88c Codex |
|---|---|---|---|---|---|
| P01 | create | 3 | 2 | 3 | 2 |
| P02 | create | 3 | 2 | 3 | 2 |
| P03 | create | 3 | 1 (one unscored) | 3 | 2 |
| P04 | insert | 3 | 2 | 3 | 2 |
| P05 | cut | 3 | 1 (one unscored) | 3 | 2 |
| P06 | sound | 3 | 2 | 3 | 2 |
| P07 | quick | 3 | 2 | 3 | 2 |
| P08 | cut | 3 | 2 | 3 | 2 |
| P09 | editor | 3 | 1 (one unscored) | 3 | 2 |
| P10 | quick | 3 | 2 | 3 | 2 |
| H1v2 | create | 1 (cut, create, unscored) | 0 (unscored, sound) | 3 | 2 |
| H2v2 | create | 3 | 2 | 3 | 2 |
| H3v2 | create | 0 (cut ×3) | 1 (create, cut) | 0 (cut ×3) | 0 (cut ×2) |
| H4v2 | create | 3 | 2 | 3 | 2 |
| H5v2 | no-skill | 3 | 2 | 3 | 2 |
| **Right under the rule** | | 13 of 15 | 10 of 15 | 14 of 15 | 14 of 15 |

## Measures, prompts 1-15

| Measure | 2.0.0 Claude (45) | 2.0.0 Codex (30) | 5cac88c Claude (45) | 5cac88c Codex (30) |
|---|---|---|---|---|
| Words before the first action, median (range) | 3,059 (0-12,032) | 5,698 (0-24,182) | 2,027 (0-7,107) | 14,807 (0-40,957) |
| Sessions under 3,000 words | 20 | 10 | 39 | 3 |
| Forbidden reads or runs | 6 | 4 | 0 | 0 |
| Build or spend attempts | 0 | 1 (see below) | 0 | 0 |
| Frame questions | 4 | 0 | 16 | 0 |
| Frame ok, the frozen scorer (planning prompts) | 3 of 30 | 0 of 20 | 14 of 30 | 0 of 20 |
| Frame recorded in `film.md` (supplementary) | 0 | 0 | 15 | 10 |
| Frame first, by event order | 5 of 30 | 1 of 20 | 25 of 30 | 11 of 20 |
| Build step before any frame | 7 | 15 | 3 | 2 |
| No frame and no build before the session ended | 18 | 4 | 2 | 7 |
| Money gate asked on H1v2 | 1 of 3 | 2 of 2 | 2 of 3 | 2 of 2 |
| Unscored | 1 | 4 | 0 | 0 |
| Infrastructure errors | 0 | 0 | 0 | 0 |

How these measures are read:
- **The candidate's frame-first breaks.**
  - Claude P05 r1-r3 ran `tighten.py` (heavy, denied) before any frame.
  - Codex P05 r2 ran it too (stopped).
  - Codex P06 r1 wrote its own `render_sound.py` before `project.py init`.
- **Codex and "asked" expectations.** In exec mode Codex never stops for a reply, so "asked" expectations cannot hold
  there.
- **The frame-order rule.** A frame is a frame question, a written frame, or `project.py init` with frame fields. A
  build step is a build, spend or heavy attempt, a non-markdown project write, or a run of a script that makes film
  material.
- **2.0.0's one Codex spend attempt.** H1v2 r1's rerun checked whether a key was set
  (`Test-Path Env:RUNWAYML_API_SECRET`), and the frozen spend pattern matches the provider's name. It spent nothing
  and the session is unscored either way. It counts under the frozen rule and does not touch the candidate's
  criteria.

## Route checks 16-20 (candidate)

| Check | Claude | Codex |
|---|---|---|
| R16: Tesseract hand-off | not run: Tesseract is installed on this machine, and the check needs an environment without it (for the author) | not run |
| R17: the sound at the drop | failed ×3 | failed ×2 |
| R18: captions, no paper edit | passed ×3 | passed ×2 |
| R19: screen in an engine project | passed ×3 (routes unscored: the agent goes to `loop.md` and the project's scripts) | passed ×2 |
| R20: hand off to the editor | passed ×3 | passed ×2 |

**R17 fails the frozen keyword check.** Every run ran `listen.py transcript`, as required. The check then requires the
word "hint" in the answer, and no run uses it. Instead, each answer labels its findings as measurements. Two of the
five, for the author to judge whether this meets "reports hints as hints":

> **They don't identify the sounds.** "Riser" and "bass" describe the measured brightness and frequency balance.
> Nothing here recognises what instrument or sound it is. … **Nobody has listened yet.** How the drop actually
> sounds, and whether it's jarring, can't be measured. It needs a person to listen at normal speed.
> (Claude, r1)

> At about **16 seconds**, the rising electronic tone cuts into a much louder, bass-heavy repeating pulse that
> continues to the end. The measured level jumps about **10.5 dB**. I assessed the waveform and spectrum; I did not
> hear the clip. (Codex, r1)

## Triggering (clean)

| Set | Should trigger: 2.0.0 | 5cac88c | Should not: 2.0.0 | 5cac88c | No worse |
|---|---|---|---|---|---|
| The 20 queries | 27/30 | 27/30 | 0/30 | 0/30 | yes, on every query |
| Opus's eight | 12/12 | 12/12 | 0/12 | 0/12 | yes, on every query |
| Combined | 39/42 | 39/42 | 0/42 | 0/42 | yes |

Both arms miss the same should-trigger query on all three runs: "what frame rate should I export a gif at so it
plays at the right speed". Per-query tables are in `trigger-combined.md`.

## Open at the time

- **R16:** it needs an environment without Tesseract. It had no such machine then.
- **R17:** whether answers that call their findings measurements, and say nobody has listened, meet "reports hints
  as hints".
- **H3v2:** it keeps its sealed label, create, and both arms route it to cut. Is a brand film cut to music from
  supplied footage create or cut?

## Limits

- **Repetitions.** n is 3 Claude and 2 Codex runs per prompt, and 3 per trigger query.
- **AGENTS.md.** Codex still loads the author's global `AGENTS.md`; no per-run override stops it.
- **Codex network.** Codex shell network steps are read, not stopped. The candidate's H1v2 sessions fetched provider
  pricing pages.
- **Inherited effort.** Claude sessions inherit the launching environment's effort (`CLAUDE_EFFORT=xhigh`).
- **What the measures are.** The frame and money-gate measures are keyword and event-order evidence for a person to
  audit, not a reading of intent.
