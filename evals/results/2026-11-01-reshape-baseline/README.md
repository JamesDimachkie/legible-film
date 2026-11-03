# Reshape routing baseline: Legible Film 2.0.0, 2026-11-01

> **Not a clean measure.** Later checks found that these sessions ran with the person's own agent instructions
> loaded (Claude Code's user `CLAUDE.md` and rules; Codex's global `AGENTS.md`) and, on Codex, with the person's
> MCP servers available, because the per-run override meant to disable them did not. The runner in this release
> (`evals/trigger_run.py`) has the same gaps. This record stays as history; do not read its numbers as a clean
> measure of 2.0.0.

The frozen 2.0.0 skill (`754e079`) run through `evals/trigger_run.py routing` on the 15 prompts of
`evals/reshape-routing.json` (10 development, 5 sealed held-outs), 3 Claude Code runs and 2 Codex runs each, in plan
mode: 75 sessions, 0 infrastructure errors, 1 unscored. The candidate is measured against these numbers under the
same harness, caps and frozen scorer. Files here: `routing-results.jsonl` (one row per session, no prompt, answer or
command text), `summary.md` and `summary.json` (per host), `combined-bar.json` (the §13 bar across both hosts) and
`scorer-history.json` (every scorer version on these sessions). Transcripts are kept outside the repository because
they contain the held-out prompts.

Models: Claude Code 2.1.316 with claude-opus-5-5. Codex CLI 0.160.0; the trace does not name the model, and the runs
used the person's Codex configuration unchanged apart from the per-run overrides (its default model).

## Results

**Routing bar (§13: at least 13 of 15 right in 2 of 3 Claude runs and both Codex runs, and every path right at least
once): not met.** 11 of 15 prompts are right on both hosts; the editor path is not (Codex routed P09 to quick in one
run).

| Host | Rule | Runs right of 15 | Prompts right under the rule | Every path | Bar on this host alone |
|---|---|---|---|---|---|
| Claude | 2 of 3 runs | 14, 14, 13 | 14 of 15 (H3 not) | yes | met |
| Codex | 2 of 2 runs | 13, 13 | 12 of 15 (P09, H1, H2 not) | no (editor) | not met |
| Both | Claude 2 of 3 and Codex 2 of 2 | | 11 of 15 | no (editor) | **not met** |

On Claude alone 2.0.0 clears the routing bar, so for that host routing does not discriminate (§13), and words read,
frame-first and the films carry the comparison. Per prompt (right runs):

| # | Prompt | Expected | Claude | Codex | Right on both |
|---|---|---|---|---|---|
| 1 | P01 | create | 3/3 | 2/2 | yes |
| 2 | P02 | create | 3/3 | 2/2 | yes |
| 3 | P03 | create | 3/3 | 2/2 | yes |
| 4 | P04 | insert | 3/3 | 2/2 | yes |
| 5 | P05 | cut | 3/3 | 2/2 | yes |
| 6 | P06 | sound | 3/3 | 2/2 | yes |
| 7 | P07 | quick | 3/3 | 2/2 | yes |
| 8 | P08 | cut | 3/3 | 2/2 | yes |
| 9 | P09 | editor | 3/3 | 1/2 (quick) | no |
| 10 | P10 | quick | 3/3 | 2/2 | yes |
| 11 | H1 | create | 2/3 (one cut) | 1/2 (one unscored) | no |
| 12 | H2 | create | 3/3 | 0/2 (sound, insert) | no |
| 13 | H3 | create | 0/3 (cut: the explainer recipe) | 2/2 | no |
| 14 | H4 | create | 3/3 | 2/2 | yes |
| 15 | H5 | no skill | 3/3 | 2/2 | yes |

Other measures, all sessions:

| Measure | Claude (45) | Codex (30) |
|---|---|---|
| Words of skill text read before the first action: median (range) | 4,000 (0-12,032) | 5,100 (0-21,344) |
| Sessions asking a frame question (audience, takeaway or destination) | 4 | 0 |
| Sessions writing a frame | 1 | 0 |
| Sessions ending their first exchange with a question (scripted reply sent) | 12 | 0 |
| Forbidden reads or runs (sessions) | 5 (`map.py` on P02; `project.py init` on P09) | 3 (`map.py` on P02; `project.py init` on P09; `story-and-score.md` on P04) |
| Build or spend attempts | 0 | 0 |
| Sessions with a heavy attempt (denied on Claude; the session stopped on Codex) | 15 | 17 |
| Sessions with a network attempt (denied on Claude) | 3 | 2 |
| H1 money gate raised before any generation | 3 of 3 | 1 of 2 |
| Sessions ended by the turn or step limit | 10 of 45 (8 turns) | 6 of 30 (40 steps) |

The one unscored session is Codex H1 r2: it read `recipes.md` whole as its first mapped file and named no recipe or
mapped script. The words figure counts SKILL.md and every skill file read before the first write, script run or other
action (2.0.0's SKILL.md alone is 2,394 words; the spec's 4,966 is SKILL.md plus `loop.md`). Frame and money-gate
figures are keyword evidence kept with the text in the transcripts, not judgements.

## Scorer: frozen

The candidate eval runs on this scorer; any later change to it reruns both arms.

| File | Commit | SHA-256 |
|---|---|---|
| `evals/routing_score.py` (the scorer, prompts 1-15) | last changed `98350ee`; frozen at `8b273c6` | `a232f3bbf969992a0d89561ec62095d32b1d402e1b9adf3e23fa55354ccb1186` |
| `evals/reshape-routing.json` (cases, route maps, patterns, caps) | `390477e` | `4544d55eabde51841363cfd711dfa0160bce4a33da53501d4140d8508be684f2` |
| `evals/route_checks.py` (route checks 16-20, candidate only; new, beside the scorer) | added after the baseline | `ed0b504d312be977578df833f315eb003e90acc8c3c201ea0f7dce9ce4625d10` |
| `evals/trigger_run.py` (runner, guard, rescore) | `8b273c6`, then route-check wiring only | `3a94beed1c53a1277fbc7017c4f24d5222c7d8b28901680c44c7728a2e80a9da` (was `4a618353ad068f4f835cd72897a0e1b6fc7f9672d7752d6cd0f18dd110d020d8` for the baseline run) |

The commits named here are from the private development history, which reaches this repository squashed into one
release commit. In the public copy of `evals/reshape-routing.json`, the product, client and community names in prompts
1-3 are replaced with neutral labels, the demo fixture is renamed `product-demo.mp4` and the held-out path is generic,
so that file hashes to `293984c5763a3a9a158f5fbf3841d486dddac704f965f9d630d2a635ba3d2ae1`. The SHA-256 in the table
is the original's, the wording these sessions ran on. Routes, rules, caps and patterns are unchanged.

The runner's route-check wiring (fixtures, the 16-20 checks, skipping them for 2.0.0) leaves prompts 1-15 as they
were: rescoring these 75 sessions with it gives byte-identical rows.

## Scorer changes during the baseline

The scorer was revised while its results were visible, which can drift toward the answer. Every version since the
first is scored here on the same final 75 sessions (`scorer-history.json`). The first version scores 44 right, 12
wrong and 19 unscored; the frozen one 67 right, 7 wrong and 1 unscored. No session moved from right to wrong. Kind:
**recognition** changes how commands and reads are recognised; **rule** changes how a recognised read resolves to a
route or how the frame is read. After the integrator's guard (from `2cc9e56`) only recognition changes were made, each
with a synthetic selftest.

| Commit | Kind | What changed | Sessions moved (from -> to; expected) |
|---|---|---|---|
| `e8ba5f2` | - | first scorer | - |
| `a5c5156` | rule, recognition | a whole `recipes.md` read also resolves from the agent's text before the read; read-only git, `ffmpeg -version` and system queries are looks (the routing ask also changed, for later sessions) | Codex P05 r2, P07 r1, P07 r2, P09 r2: unscored -> expected |
| `709c0ad` | rule, recognition | a heading in a partial read's first ten lines wins; filtered reads (`Select-String`, grep with context) are section reads | Claude P02 r2 cut -> create; Claude P03 r1 unscored -> create; Codex P08 r1 unscored -> cut; **Codex P02 r1 unscored -> quick (not expected)** |
| `287fdb6` | recognition | a Grep showing one heading with lines after it is a read (guard: `tighten.py` heavy, `--help` never an attempt) | Claude P04 r2 cut -> insert; P05 r1, r2, r3 unscored -> cut; P07 r2, r3 unscored -> quick; P09 r2 cut -> editor |
| `9d2cb33` | rule, recognition | the first `recipes.md` read showing a mapped recipe resolves (sub-headings skipped); a Grep for a heading's text without `##` is a read | Claude P09 r1 cut -> editor; **Codex H2 r2 unscored -> insert (not expected)** |
| `37b726a` | recognition | bare file names after `cd` into the skill folder | Claude H1 r1, H2 r2 unscored -> create |
| `3b023dd` | recognition | only parts of a command that run something are attempts; split outside quotes | none |
| `b633fca` | rule, recognition | first question from any message of the first exchange; `rg -A` sections; PowerShell `if` looks | Codex P04 r1 unscored -> insert |
| `0ece867` | rule, recognition | a read of the top of `recipes.md` is on no recipe and the search stops at a committing step, not `setup.py`; nested shells and spliced quotes | Codex H3 r2 quick -> create; Codex P02 r1 quick -> create; Codex P05 r1 unscored -> cut |
| `6168bea` | recognition | Codex wrappers decoded as a POSIX shell; `$path` variables | Codex P04 r2 unscored -> insert; **Codex P08 r2 sound -> unscored (away)** |
| `2cc9e56` | recognition | reads through a loaded PowerShell variable (`$t[a..b]`, `$t \| Select-String`) | Codex P08 r2 unscored -> cut |
| `98350ee` | recognition | `--doctor` and loop headers are not attempts; a stopped Codex command is an attempt | none (4 Claude sessions denied on those steps were rerun) |

Guard-rule changes that altered what a session could do (`tighten.py` heavy, `--help`, commands that only name a
script or service, `--doctor`, loop headers) were followed by `rescore --rerun-undenied`, and every session they
affected was run again under the final rules. The moves above are mostly sessions whose reads the first version could
not see; an independent blind check of a sample of transcripts against these routes would test that.

## Limits

- n is 3 Claude and 2 Codex runs per prompt; the per-prompt spread is in the tables.
- Codex ran on the person's normal Codex home and login, isolated only by per-run overrides (no plugins, apps,
  memories, MCP servers or other installed skills; the staged variant was the only skill read in every trace). Their
  global `AGENTS.md` still loaded, 6 of 30 sessions read a file it names, and the Codex sandbox lets a session read
  the whole user folder: one session listed a folder of another project outside its scratch project (Codex P03 r1;
  the path is kept in the local run notes, not in this repository). That sandbox
  also blocks `python`, `ffmpeg` and `ffprobe` in the scratch project, so many Codex steps went to diagnosing it, and
  17 Codex sessions ran the skill's own per-user Python environment (`legible-film/venv` in the local app-data
  folder, which `setup.py` creates) instead. The rows' `foreign_skill_reads` field lists those venv paths (and one
  path that is a rescore artifact); it is diagnostic only and no session read another copy of the skill.
- Codex in exec mode never stops for a reply: no Codex session ended its first exchange with a question, so the
  scripted reply was never sent there, and frame-first behaviour on Codex shows only as questions asked in passing.
- The media are synthetic stubs (test patterns and tones), so a session that inspects them learns little.
- Route checks 16-20 were not part of the baseline; 19 and 20 need project fixtures the harness does not build yet.
- Timings are not comparable as speed (method note below).

## Method note: concurrency and timings

Routing sessions are planning runs: one agent CLI process each, with every build, spend, network, install and heavy
step denied (Claude) or stopped (Codex). From 2026-11-01 evening they take no heavy-job lock and do not yield to
other jobs; each waits only for 2 GiB of free memory, and two run at once (`--workers 2`, each host's rows recorded
independently). Sessions recorded earlier ran one at a time under the lock. Routes, reads, words, questions and
attempts come from each session's own stream and do not depend on this, but the recorded seconds include memory
waits, earlier lock waits and contention with other work on the machine, so timings are not comparable as speed.
The candidate run uses the same settings.

## Codex step cap: 40

Claude Code runs keep the spec's eight turns. Codex counts every command as a step, and at eight steps the first
2.0.0 Codex sessions ended while still reading references, so frame-first behaviour and forbidden actions were not
observed on that host. The Codex cap is the smallest tested value at which 2.0.0 Codex sessions on P01 and P05
reached their first question or first committing step (a write, a pipeline step, or a build, spend or heavy attempt;
`setup.py` and other diagnostics do not count):

| Run | Cap | P01 | P05 |
|---|---|---|---|
| Measurement | 40 | question after step 7; build attempt at 18 | no question; heavy attempt at 23 |
| Check | 23 | neither within 24 steps (reads and environment checks) | heavy attempt at 20 |
| Check | 40 | question after step 9; heavy attempt at 28 | question after step 11; heavy attempt at 12 |

23 failed its check; 40 passed on both. The true minimum lies between 25 and 40 and was not narrowed further. Step
counts vary because the person's Codex sandbox makes `python`, `ffmpeg` and `ffprobe` fail in the scratch project, and
Codex spends steps diagnosing it. The same cap applies to the candidate. Codex sessions recorded at eight steps were
discarded and run again at 40.
