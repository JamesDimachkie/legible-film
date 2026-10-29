<h1 align="center"><img src=".github/media/banner.jpg" alt="Legible Film: video production for coding agents" width="100%"></h1>

[![CI](https://github.com/JamesDimachkie/legible-film/actions/workflows/ci.yml/badge.svg)](https://github.com/JamesDimachkie/legible-film/actions/workflows/ci.yml)

Legible Film is an Agent Skill that lets a coding agent (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot and
others) make video end to end: films built in code, edits cut from recordings, sound designed and mixed for the
screens people actually use, and every delivered file checked before anyone ships it. Its name is the standard it
holds every film to: legible to the viewer it is made for, and honest about what was checked.

It works the way a careful director, editor and finisher would: one story, picture and sound composed on one clock,
every claim traced to a source, approved work kept approved, and nothing reported as watched or heard until a person
has watched and listened.

[![Six frames from Atlasfold, a 24-second launch film for a fictional product, made with the bundled film kit](.github/media/atlasfold-stills.jpg)](https://github.com/JamesDimachkie/legible-film/raw/main/.github/media/atlasfold-showcase.mp4)

*Atlasfold, a launch film for a fictional product, built with the bundled film kit and rendered with one command at
16:9 and 9:16. [Watch it with sound](https://github.com/JamesDimachkie/legible-film/raw/main/.github/media/atlasfold-showcase.mp4)
(24 s): every sound in it was synthesised by the skill's own sound kit. In a blind A/B listen, its author preferred it
to the same film mixed with downloaded CC0 library sounds. It passes the skill's flash screen in both shapes.*

In a small blind-graded test (five requests, one run each on one model), agents with the skill met 35 of 35
expectations and agents without it met 10 of 35. Every prompt, output and grade is
[published](evals/results/2026-10-27/README.md), with what the test could not control.

Created by James Dimachkie. Licensed under Apache-2.0.

## Why it exists

Coding agents can now build a launch film, a product demo or an explainer from code, generated assets and FFmpeg.
They can also render something that passes every build check and still fails the viewer: text that leaves before it
can be read, a brand colour shifted by the encoder, a soundtrack that clips on the platform's re-encode, a picture
that claims more than the product does, or an approved scene broken by a fix somewhere else. Nor can an agent watch
its own film at speed or hear it.

This skill encodes a working method for those problems. It was built from making launch films, product demos and
client videos with coding agents in 2026. Its rules come from defects found in real cuts, notes from the people who
watched and listened, measurements on delivered files, and published standards and research checked against their
sources. Its scripts were written for that work and are tested against synthetic media with known answers.

## What it can do

**Build a film in code.** A small, dependency-free browser engine for type-led films, from a calm launch film to
beat-cut kinetic type, with the skill's rules built in. `make_film.py` takes a film from preflight to delivered,
checked files in one command: claims bound to a facts file, contrast and reading time checked on the film's own
timeline, flashing predicted before a frame renders, motion blur that respects cuts, one timeline rendered at 16:9,
9:16 and 1:1, and a delivery report that says what was and was not checked.

**Edit recordings.** Interviews, talking heads, screen recordings and cut-downs. An edit lives in one `edit.json` that
`assemble.py` renders frame-accurately: J and L cuts, dissolves, retimes, crop paths, overlays, and HDR phone footage
tone-mapped for ordinary screens. `transcript_cut.py` cuts from a word-timed transcript in the gaps between words,
`reframe.py` follows the subject into a tall frame, and `captions.py` builds, checks and burns captions clear of
faces and platform buttons.

**Sound that survives a phone speaker.** A sound chain from the picture's own cue list: spotting that merges
collisions and thins dense runs, licensed library sounds layered over synthesised low end and air, music that ducks
under a voice phrase by phrase, mastering to the destination's loudness with a limiter checked after a lossy
re-encode, and a blind, loudness-matched A/B pair so a person chooses by listening.

**Checks an agent cannot do by eye.** Each script is tested against synthetic media with known answers: spec, colour
tags and loudness; WCAG 2.3.1 flash screening; near-empty frames; cuts, holds and pace; a claim or qualifier present
through every frame of its interval; sound on cue, or a moved sound gone from its old place; audio drift and the
resampling that repairs it; the exact frames a revision changed.

## How it works

The agent works through nine steps, each ending on a condition it can check:

1. **Brief, facts and format.** Who it is for, where it plays, what must read muted, a facts file for every claim,
   and a QC plan that maps each requirement to the check that measures it.
2. **Story and score.** The change the film makes in its viewer, three concepts (or, for an edit of recordings, the
   selects and an outline drawn from them), and a score that plans every moment across picture, motion, text, music,
   effects and the product's truth.
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

Until a named person has watched the delivered file, the agent reports it as unwatched; until someone has listened to
a file with sound, as unheard. It asks before spending money, uploading private material to a hosted service, or
publishing anything.

## See it check a file

`evals/make_fixtures.py` builds a four-second clip with three planted defects. Asked to check it before posting, an
agent following the skill runs the bundled scripts on that exact file:

```
python skills/legible-film/scripts/qc_file.py evals/files/check-me.mp4 --spec 640x360@30 --duration 4 \
    --vcodec h264 --pix-fmt yuv420p --color bt709 --audio required
python skills/legible-film/scripts/flash_scan.py evals/files/check-me.mp4
```

Their output, shortened to the findings:

```
check-me.mp4: h264 640x360 yuv420p @ 30 fps, 3.2 s; colour None/None/None; faststart False
  loudness: -21.8 LUFS integrated, LRA 20.0 LU, true peak -20.8 dBTP
  warning: colour primaries untagged: players will guess; tag them (e.g. bt709)
  warning: sound at level in the first 5 ms: a click unless a hit is designed for frame 0
  warning: the last 10 ms is not near silence: check for a cut-off tail unless the ending is a designed hard stop
  FAIL duration: expected 4.0 +/- 0.0333 s, got 3.2
  FAIL color_tags: expected ['bt709', 'bt709', 'bt709'], got [None, None, None]
  not checked: picture content, motion at playback speed, text legibility at viewing size, flashing (flash_scan.py), how the sound sounds, sync to picture events, claims, rights
check-me.mp4: 96 frames at 30 fps; busiest second: general 11 transitions (at 1.1 s), red 11 (at 1.1 s); FLAGGED
```

All three defects are caught: muxing with `-shortest` cut the picture to 3.2 s, the colour tags are missing, and a
5 Hz full-frame flash fails the WCAG 2.3.1 screen. The report also names what no script checked, which goes into the
delivery report alongside who has watched and listened.

## Install

**Claude Code.** In a Claude Code session:

```
/plugin marketplace add JamesDimachkie/legible-film
/plugin install legible-film@jamesdimachkie
```

**Any agent that reads Agent Skills** (Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Amp, Goose, Claude Code).
In a terminal with Node.js installed, from your project folder:

```
npx skills add JamesDimachkie/legible-film
```

Add `-g` for a user-wide install or `-a codex` (or another agent name) to target one agent.

**By hand:** copy `skills/legible-film/` into `~/.claude/skills/` for Claude Code, or into `.agents/skills/`
(project) or `~/.agents/skills/` (user) for most other agents.

**Requirements:** Python 3.9 or later, FFmpeg and ffprobe on `PATH`, and `pip install numpy Pillow` (into whichever
Python environment the agent will use) for the scripts. The film kit also needs Node.js 18 or later with Playwright
and Chromium; `python skills/legible-film/scripts/make_film.py --doctor` checks all of it and prints the one command
that fixes each missing piece. If you are unsure whether these are installed, ask your coding
agent: "Install Legible Film, check its requirements and run its self-test; ask me before changing anything that
needs my permission."

**Check the installation.** From a clone of this repository:

```
git clone https://github.com/JamesDimachkie/legible-film
cd legible-film
python skills/legible-film/scripts/selftest.py
```

If you installed through a plugin or `npx skills`, the same script sits in the installed skill's `scripts/` folder;
ask your agent to run the Legible Film skill's self-test. It builds synthetic media with known answers and runs about
360 checks across every script in a few minutes, writing only to a temporary folder. It counts any case it could not
run (the film-kit cases need Playwright) and remembers a passing environment; `--quick` checks the dependencies in
seconds.

## Use it

Ask for what you want. Agents that support skills load this one from its description when a request is video work;
to be certain, name it: "Use Legible Film to check this cut." For example:

- "Make a 30-second launch film for our release, 16:9 for the post and 9:16 for stories. Facts are in `docs/`."
- "Use the film kit to make a 15-second teaser for 2.0, with a draft soundtrack."
- "Cut a 12-second Reels clip from the clean answer in `interview.mp4`, with captions burned in and an SRT."
- "Put this voiceover over the music for the landing page and keep the voice clear throughout."
- "Here is the cut. Check it before I post it."
- "The client says the end feels rushed. Fix that without touching anything they already approved."
- "Which tools should I use to turn these screen recordings into a two-minute tutorial with captions?"

More are in [examples/prompts.md](examples/prompts.md).

## Studio grade

For the best film the budget allows, ask for it by name: "Use Legible Film at studio grade for our launch film.
Budget up to $800 for music, voice and stock." The agent then works the way a small studio would:

- **It leads with the film.** Its first reply describes two or three directions you can picture, then what you will
  see and decide at each step, in plain words.
- **It studies before it designs.** It finds comparable pieces whose makers explained their decisions, annotates what
  to borrow from each and what must not transfer, and mines your product's own material for the idea.
- **It shows instead of asking.** You choose between things you can watch and hear: three short, rough idea videos
  with temporary sound, sample stills of the look made from the hardest frames in every shape you will post, and a
  rough timed version of the whole film before anything is polished. Everything temporary is labelled.
- **It spends on what the film needs most.** Purchases and generation runs are line items you approve, each showing
  what is payable now, what is already committed and what remains under your cap, with each licence checked for the
  real use ([finding assets](skills/legible-film/references/assets.md),
  [making them](skills/legible-film/references/generation.md)).
- **It brings specialist craft** to story, picture, type, editing, sound design, music, voice, mix and finishing,
  while the design can still change.
- **It leaves the watching and listening to people.** It prepares and measures; you, or viewers you name, judge how
  the film moves and sounds, and nothing is reported as watched or heard until someone has.
- **It keeps raising the weakest moment** until viewers can answer six questions with evidence (understanding,
  specificity, experience, earned payoff, truth and afterimage) or you decide to stop.

Every gate still applies: nothing is bought, uploaded or published without you. The full method is in
[studio](skills/legible-film/references/studio.md).

In a blind comparison with 1.0.1, which has the method but not studio grade, the plans 1.1.0 made won all four
pairs: two studio-grade requests, two runs each, one model. The judge, a different model family, rated each
preference medium confidence. It preferred 1.1.0 for leading a newcomer and for money and rights, and found the
1.0.1 plans more concrete about what appears on screen
([evidence](evals/results/2026-10-28-studio-vs-1.0.1/README.md)). That measures plans, not finished films.

## What is inside

```
skills/legible-film/
  SKILL.md            the method: principles, gates, nine steps, revisions, hard limits, gotchas
  references/         story-and-score, timing, picture, product-demos, sound, claims-and-rights, formats,
                      engines, finishing, ffmpeg-cookbook, qc, review, case-library, sources; studio grade,
                      finding assets, making assets with generative tools; the film kit, kinetic type, footage
  scripts/            the tools below, each with --help, plus a self-test
  assets/kit/         the film kit: engine, blocks, open-licence fonts, a starter film and the Atlasfold showcase
  assets/templates/   brief, treatment, facts, score, cues, sound palette, asset register, budget, review log,
                      critic brief, delivery report
  assets/examples/    a filled 40-second score for a fictional product
evals/                behaviour and trigger evaluations for the skill itself
```

| Stage | Scripts |
|---|---|
| Make a kit film | `new_film.py`, `film_check.py` (preflight), `make_film.py` (one command to delivered files), `film_render.py`, `motion_blur.py` |
| Edit recordings | `transcript_cut.py`, `assemble.py`, `reframe.py`, `captions.py` |
| Sound | `tempo_map.py`, `make_sound_kit.py`, `sound_library.py`, `spot_cues.py`, `mix_cues.py`, `sound_check.py`, `voice_clean.py` |
| Check the delivered file | `qc_file.py`, `frame_sheet.py`, `flash_scan.py`, `blank_scan.py`, `motion_scan.py`, `region_check.py`, `cue_onsets.py`, `sync_check.py`, `compare_versions.py`, `onion_frames.py` |
| The environment | `selftest.py`, `kit_selftest.py` |

What each one answers is in [SKILL.md](skills/legible-film/SKILL.md#scripts).

## Limits

- The scripts measure; they do not watch or listen. Rhythm, feel, comprehension and how the sound sounds are decided
  by people, and the skill says so in every report.
- `flash_scan.py` screens for WCAG 2.3.1 flashing. It is not a Harding, IRIS or broadcast PSE certification.
- Tool versions, platform specs and provider terms in the references were checked between 2026-10-27 and
  2026-10-29 and change often; each is dated, and linked to its source wherever a stable page exists, so it can be
  re-checked.
- Evaluations are small:
  - seven requests: five on 1.0.0, with and without the skill, and two studio-grade ones comparing 1.1.0 with 1.0.1;
  - one or two runs per arm, on one model;
  - graded blind by another model family, against expectations written by the skill's author.

  They measure plans and behaviour, not how good a finished film is. Evals 8-11, added in 1.2.0 for the film kit,
  footage editing and dialogue, have not been run yet. Whether agents load the skill unprompted has not been tested.
  Details are in [evals/README.md](evals/README.md).
- The footage tools work on measurements, not understanding: `reframe.py` follows sustained motion and detail, not a
  recognised subject, so its path is a proposal to review; `transcript_cut.py` proposes cuts in word gaps for a
  person to listen to; the burned-caption check estimates text from frame changes, which moving faces and cuts can
  confuse. `voice_clean.py` is a conservative starting point, never an automatic fix.
- The film kit renders through a headless browser and is built for type-led motion graphics, not photoreal or 3D
  work; the references route those to other engines.

## Contributing

Suggestions and fixes are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Rules change only with evidence (a
defect, a measurement, a source), and every script change keeps `selftest.py` passing.

## Licence

Apache-2.0. Copyright 2026 James Dimachkie. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
