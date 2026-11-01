# SKILL.md as a router: triggering and routing, 2026-10-31

Fresh `claude -p` sessions (Claude Code 2.1.314, model claude-opus-5-5) in a temporary project whose only skill was
one variant of `legible-film`, run by [`evals/trigger_run.py`](../../trigger_run.py): project settings only, no MCP
servers, read-only tools, at most three turns, no saved sessions. The user-level CLAUDE.md held only an unexpanded
import line, the same for every variant.

| Variant | SKILL.md | SHA-256 (first 12) |
|---|---|---|
| `old` | The 2.0 release file (34.6 KB, description 719 characters) | `fbe3413bc849` |
| `new` | First router draft (description 347 characters) | `14fa07ad1824` |
| `new2` | Router with the final description (346 characters) | `0089e0fe647f` |
| `new3` | The final file at the time (13.8 KB): `new2` with First run marked once per machine and a platform-specs row | `29b57c4b1314` |

Triggering depends only on the name and description, which `new2` and `new3` share, so `new2`'s trigger runs stand
for the final file.

## Triggering (`trigger-results.jsonl`)

Each of the 20 queries in [`trigger-queries.json`](../../trigger-queries.json), twice per variant.

| Variant | Should trigger loaded | Should not trigger loaded |
|---|---|---|
| old | 17/20 | 2/20 |
| new | 16/20 | 0/20 |
| new2 (final) | 18/20 | 0/20 |

`new` failed the pass rule by one run: "my exported video looks washed out in safari" loaded 1/2 with `old` and 0/2
with `new`, which had dropped "checking an exported file". `new2` restored that branch ("or checking how an export
looks or plays") and added "exporting": the Safari query loaded 2/2. "Transcribe this podcast episode" loaded 2/2
with `old` and 0/2 with both routers ("Not for ... transcribing ... alone"). "What frame rate should I export a gif
at" loaded 0/2 with every variant. The description was tuned on these same queries, so the margin is in-sample.

## Routing (`routing-results.jsonl`)

Four requests, twice per variant, asking for the first commands and the references to read, with only the Skill
tool. All 24 answers named an expected command and reference and none named a forbidden one; the raw transcripts
(2.7 MB) are kept outside the repository, and the JSONL here holds each answer. Read against each other:

- **Trim and 9:16:** all variants treat it as a quick edit with no project and read the quick-edits recipe. `new2`
  started every job with setup, install and smoke test; `new3` marks First run once per machine, like `old`.
- **60-second story from an interview:** all go `project.py init`, `map.py add`, `map.py run`; `old` reads
  finding-the-story, paper-edit and recipes; `new2`/`new3` read loop.md's stage sections, finding-the-story and
  paper-edit.
- **Check an export for YouTube:** all run `check.py --file` and read qc §2; `old` also read formats (platform
  specs), `new2` did not; `new3`, with the platform-specs row, does again.
- **Two Premiere exports, stale captions:** all run `exchange.py compare` and `check.py --file` with the timeline,
  and read the assisting-an-editor recipe.

The routing score matches names in the answer; it is not a judgement of the plan.
