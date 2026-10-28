# Legible Film

Video production for coding agents. The name is the standard it holds every film to: legible to the viewer it is
made for, and honest about what was checked.

An Agent Skill that teaches a coding agent (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot and others) to
make short videos the way a careful director, editor and finisher would: one story, picture and sound composed on one
clock, every claim traced to a source, and the delivered file checked before anyone ships it.

Created by James Dimachkie. Licensed under Apache-2.0.

## Why it exists

Coding agents can now build a launch film, a product demo or an explainer from code, generated assets and FFmpeg.
They can also render something that passes every build check and still fails the viewer: text that leaves before it
can be read, a brand colour shifted by the encoder, a soundtrack that clips on the platform's re-encode, a picture
that claims more than the product does, an approved scene quietly broken by a fix somewhere else. And an agent cannot
watch its own film at speed or hear it.

This skill encodes a working method for those problems. It was built from making launch films, product demos and
client videos with coding agents in 2026. Its rules come from defects found in real cuts, notes from the people who
watched and listened, measurements on delivered files, and published standards and research checked against their
sources. Its scripts were written for that work and are tested against synthetic media with known answers.

## What it does

The agent works through nine steps, each ending on a condition it can check:

1. **Brief, facts and format.** Who it is for, where it plays, what must read muted, and a facts file for every claim.
2. **Story and score.** The change the film makes in its viewer, three concepts, one governing operation, and a score
   that plans every moment across picture, motion, text, music, effects and the product's truth.
3. **The clock.** One timing source for picture and sound, sync points computed from the animation, and a reading
   window for every essential text.
4. **Picture.** A world with reasons, motion with weight and cause, joins chosen for what they mean, and craft rules
   drawn from rendered defects.
5. **Sound.** What leads each passage, which events sound, how it ends, and one hard rule: nothing jarring.
6. **Render, finish and mux.** Frozen sources, correct colour conversion and tags, audio matched to picture.
7. **QC the delivered file.** Spec, decode, colour, loudness, true peak after a platform re-encode, flashing, blank
   frames, motion, sync and claims, run on the exact file a viewer will receive.
8. **Review with people.** Muted at viewing size, then with sound, then pauses; synthetic critics verified before
   anything changes; approved work kept approved.
9. **Deliver.** The file, its hash, and a report that says what was checked, what was not, and who has watched and
   listened.

Until a named person has watched the delivered file, and listened when it has sound, the agent reports it as
unwatched and unheard.
It asks before spending money, uploading private material to a hosted service, or publishing anything.

## Install

**Claude Code**

```
/plugin marketplace add JamesDimachkie/legible-film
/plugin install legible-film@jamesdimachkie
```

**Any agent that reads Agent Skills** (Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Amp, Goose, Claude Code):

```
npx skills add JamesDimachkie/legible-film
```

Add `-g` for a user-wide install or `-a codex` (or another agent name) to target one agent.

**By hand:** copy `skills/legible-film/` into `~/.claude/skills/` for Claude Code, or into `.agents/skills/`
(project) or `~/.agents/skills/` (user) for most other agents.

**Requirements:** Python 3.9 or later, FFmpeg and ffprobe on `PATH`, and `pip install numpy Pillow` (into whichever
Python environment the agent will use) for the scripts.

**Check the installation.** From a clone of this repository:

```
git clone https://github.com/JamesDimachkie/legible-film
cd legible-film
python skills/legible-film/scripts/selftest.py
```

If you installed through a plugin or `npx skills`, the same script sits in the installed skill's `scripts/` folder;
ask your agent to run the Legible Film skill's self-test. It builds synthetic media with known answers and checks
every script against them in about twenty seconds, writing only to a temporary folder.

## Use it

Ask for what you want; the skill loads when the task is video work. For example:

- "Make a 30-second launch film for our release, 16:9 for the post and 9:16 for stories. Facts are in `docs/`."
- "Here is the cut. Check it before I post it."
- "The client says the end feels rushed. Fix that without touching anything they already approved."
- "Which tools should I use to turn these screen recordings into a two-minute tutorial with captions?"

More are in [examples/prompts.md](examples/prompts.md).

## What is inside

```
skills/legible-film/
  SKILL.md            the method: principles, gates, nine steps, revisions, hard limits, gotchas
  references/         story-and-score, timing, picture, product-demos, sound, claims-and-rights, formats,
                      engines, finishing, ffmpeg-cookbook, qc, review, case-library, sources
  scripts/            QC tools for the delivered file, plus a self-test
  assets/templates/   brief, treatment, facts, score, cues, asset register, review log, critic brief, delivery report
evals/                behaviour and trigger evaluations for the skill itself
```

| Script | Answers |
|---|---|
| `qc_file.py` | Does the file meet its spec and decode cleanly? Colour tags, loudness, true peak before and after a lossy re-encode, head and tail levels, mono fold-down, brand colour patches. |
| `frame_sheet.py` | What exactly is on screen at these times, at full size or at viewing size? |
| `flash_scan.py` | Is there a candidate WCAG 2.3.1 flash sequence? |
| `blank_scan.py` | Are there near-empty frames outside the designed ones? |
| `motion_scan.py` | Cuts, one-frame intrusions, repeated frames in motion, holds, first motion, loop seam. |
| `cue_onsets.py` | Does each sound start on its cue, do silent cues stay quiet, and is the hit rate better than chance? |
| `sync_check.py` | Is the delivered audio offset or drifting against the approved mix? |
| `compare_versions.py` | Where did the picture change between two renders? |
| `onion_frames.py` | What path and spacing does a move have across these frames? |

## Limits

- The scripts measure; they do not watch or listen. Rhythm, feel, comprehension and how the sound sounds are decided
  by people, and the skill says so in every report.
- `flash_scan.py` screens for WCAG 2.3.1 flashing. It is not a Harding, IRIS or broadcast PSE certification.
- Tool versions, platform specs and provider terms in the references were checked on 2026-10-27 and change often;
  each is dated, and linked to its source wherever a stable page exists, so it can be re-checked.
- Evaluations so far are small: three requests, one run each with and without the skill on one model, graded
  blind by another model family. With the skill, runs met 25 of 26 expectations; without it, 10. The details,
  including what was not run, are in [evals/README.md](evals/README.md).

## Contributing

Suggestions and fixes are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Rules change only with evidence (a
defect, a measurement, a source), and every script change keeps `selftest.py` passing.

## License

Apache-2.0. Copyright 2026 James Dimachkie. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
