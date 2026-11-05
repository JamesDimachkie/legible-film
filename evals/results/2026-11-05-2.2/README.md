# Routing and triggering on 2.2, 2026-11-05

The same harness, frozen scorer and cases as the [Nov 2 record](../2026-11-02-clean-rerun/README.md), run on the 2.2
skill in fresh agent sessions. Sessions ran without the user's instructions, memory or MCP servers. Raw transcripts are not
published; the rows here keep ids, routes and counts, with personal paths removed.

- **Routing:** skill text at `03c3c20`, 20 cases. Claude Opus 5.5 ran 3 times, at most 8 turns; GPT-6.1 Terra through Codex
  ran 2 times, at most 40 steps.
- **R16 and triggering, again on the final text:** `c345195`, whose description adds "sounds" and whose Tesseract section
  says not to run `tsrct`. Between the two commits only those two passages of the skill's text changed.
- **Control:** released 2.1.0, three prompts, three runs each, on the same day.

## Results

| Measure, prompts 1-15 | Claude (45) | Codex (30) | Nov 2 candidate: Claude, Codex |
|---|---|---|---|
| Prompts routed right under the rule | 14 of 15 | 14 of 15 | 14 of 15, 14 of 15 |
| Words before the first action, median | 2,368 | 12,834 | 2,027, 14,807 |
| Sessions under 3,000 words | 29 | 2 | 39, 3 |
| Frame ok, frozen scorer (planning prompts) | 7 of 30 | 2 of 20 | 14 of 30, 0 of 20 |
| Money gate asked on the spending prompt | 3 of 3 | 2 of 2 | 2 of 3, 2 of 2 |
| Infrastructure errors | 0 | 0 | 0, 0 |

The one prompt both hosts miss is H3v2, a brand film cut to music from supplied footage. It routes to cut, and its sealed
label says create. That label is still an open question.

| Route check | Claude | Codex |
|---|---|---|
| R16: Tesseract hand-off | failed x3 | failed x2 |
| R17: the sound at the drop | failed x3 | failed x2 |
| R18: captions, no paper edit | passed x3 | passed x2 |
| R19: screen in an engine project | passed x3 | passed x2 |
| R20: hand off to the editor | passed x3 | passed x2 |

| Triggering, Claude, 3 runs per query | Released 2.1.0 | 2.2 |
|---|---|---|
| The 20 queries: should load, should not load | 26/30, 0/30 | 27/30, 0/30 |
| Eight more queries (2.2 only): should load, should not load | | 12/12, 0/12 |
| New queries naming subtitles, captions, podcasts, interviews, shorts and pauses | 13/18, 0/12 | 17/18, 0/12 |

The 2.1.0 figure on the new queries was measured beside the first 2.2 text, which scored 18/18. Each cell is 3 runs of each
query, so one query's result moves it by 3. These were one run of the harness on one day, on Claude only.

## How to read these

- **Frame ok fell on Claude, and the skill's text is not the reason.** Three prompts (P02, P06, H2v2) scored 5 of 9 on the
  Nov 2 candidate. On this day they scored 0 of 9 on released 2.1.0 and 0 of 9 on 2.2, where `SKILL.md`'s body and
  `paths/sound.md` are unchanged from the Nov 2 candidate. The agent CLI moved from 2.1.316 to 2.1.318 between the runs. That
  is the only difference we can name, and it is not shown to be the cause. Sessions run non-interactively, and an interactive
  session may behave differently. Either way, agents often start without stating the frame, and this remains open.
- **Codex in exec mode never stops for a reply,** so "asked" expectations cannot hold there.
- **Words read before acting are still far over the 3,000 target on Codex,** and slightly up on Claude.
- **The spending prompt:** two Claude sessions matched the frozen spend pattern. Both were looking up vendor prices; the
  guard denied them, one answer read as checked says nothing was generated or spent, and the plan waits for the person's
  approval. They count under the frozen rule.
- **P09, Claude r2:** one denied run of `project.py init` on a read-only editor request.
- **R16** runs here for the first time, on a machine without Tesseract. On the final text Claude routes right, does not run
  `tsrct` and names the hand-off, but writes neither the frame nor the plan cue list within 8 turns. Codex still fails.
  The hand-off stays experimental.
- **R17** fails a frozen keyword check for the word "hint". The answers call their findings measurements and say nobody has
  listened, as on Nov 2. The check is left as it was and counts as failed.
- **R19 on Claude** passes as a route check, while its route is unscored: the agent goes to `loop.md` and the project's
  scripts, as on Nov 2.

None of this measures whether a film is any good. It measures which guide an agent reads and what it does first.
