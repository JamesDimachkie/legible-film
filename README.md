<h1 align="center"><img src=".github/media/banner.jpg" alt="Legible Film: video production for coding agents" width="100%"></h1>

<p align="center">
  <a href="https://github.com/JamesDimachkie/legible-film/actions/workflows/ci.yml"><img src="https://github.com/JamesDimachkie/legible-film/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/JamesDimachkie/legible-film/releases/latest"><img src="https://img.shields.io/github/v/release/JamesDimachkie/legible-film?label=release" alt="Latest release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-Apache--2.0-blue" alt="Licence: Apache-2.0"></a>
</p>

Video production for your coding agent. Build films in code, cut interviews into stories, score and mix the sound,
and check every file before it ships. Name the job with a word like `cut`, `score` or `check`, and the agent follows
a method written for it.

In a terminal with Node.js, from your project folder:

```
npx skills add JamesDimachkie/legible-film
```

Then type `/legible-film` in Claude Code or `$legible-film` in Codex to see the commands. Cursor, Gemini CLI, GitHub
Copilot, OpenCode and other agents that read Agent Skills load it too, from a plain request or their own skill syntax.
[Install](#install) has the Claude Code plugin and the other ways in.

[![Six frames from Atlasfold, a 24-second launch film for a fictional product, made with the bundled film kit](.github/media/atlasfold-stills.jpg)](https://github.com/JamesDimachkie/legible-film/raw/main/.github/media/atlasfold-showcase.mp4)

*Atlasfold, a launch film for a fictional product, built with the bundled film kit and rendered with one command at
16:9 and 9:16. [Watch it with sound](https://github.com/JamesDimachkie/legible-film/raw/main/.github/media/atlasfold-showcase.mp4)
(24 s): every sound in it was synthesised by the skill's own sound kit. In a blind A/B listen, its author preferred it
to the same film mixed with downloaded CC0 library sounds. It passes the skill's flash screen in both shapes.*

Created by James Dimachkie. Licensed under Apache-2.0.

## Why

A coding agent can build a launch film from code or cut an interview with FFmpeg. It can also ship one that passes
every build check and still fails the viewer: a caption gone before anyone can read it, a brand colour shifted by the
encoder, a soundtrack that clips after the platform re-encodes it, a claim the product can't back, an approved scene
broken by a fix somewhere else. And it can't watch its own film at speed or hear it.

- **A command for each job.** `/legible-film cutdown the approved cut to 9:16 and 15 seconds` starts the work a
  cut-down needs: the shorter version gets its own timeline, the tall one reframes the approved edit, and each is
  checked as a deliverable of its own. Sixteen commands cover planning, making, editing, sound, checking, revising
  and delivering.
- **Checks on the file that ships.** 28 scripts, each tested against synthetic media with known answers: flashing
  (WCAG 2.3.1), colour tags, loudness and true peak after a lossy re-encode, near-empty frames, pace, a claim present
  through every frame of its interval, sound on cue, audio drift, and the exact frames a revision changed.
- **Honest about the rest.** Scripts measure; people watch and listen. Nothing is reported as watched or heard until a
  person has, and every delivery report says what was checked, what wasn't, and the weakest point left. The agent asks
  before it spends money, uploads private footage or publishes anything.

The method comes from making launch films, product demos and client videos with coding agents in 2026: defects found
in real cuts, notes from the people who watched and listened, measurements on delivered files, and published standards
checked against their sources.

## How it works

Name a command and what it applies to:

```
/legible-film brief a 30-second launch film for our 2.0 release; the facts are in docs/
/legible-film kit the launch film at 16:9 and 9:16, with a draft soundtrack
/legible-film cut a 60-second story from interview.mp4 and the b-roll in broll/
/legible-film captions the cut, burned in for Reels, with an SRT
/legible-film check final.mp4 before I post it
/legible-film revise: the client says the ending feels rushed
```

Or describe what you want in your own words; a plain request takes the same paths. Type `/legible-film` alone to see
the list. More requests are in [examples/prompts.md](examples/prompts.md).

### 16 commands

| Command | Use it to |
|---|---|
| **Plan** | |
| `brief` | Turn a request into a brief, a facts file and a QC plan before anything is made |
| `setup` | Choose the tools for a job and check your machine can run them |
| **Make** | |
| `film` | Make a new video on whichever engine fits: HyperFrames, Remotion, Blender, an editor or FFmpeg |
| `kit` | Build a type-led film with the bundled film kit, taken to delivered files by one command |
| `teaser` | Put big words on the beat: a teaser, trailer or hype film |
| `short` | Make a logo sting, a loop or a clip under 15 seconds |
| `studio` | Aim for the best film your budget allows |
| **Edit** | |
| `cut` | Edit interviews, talking heads, screen recordings and event footage |
| `cutdown` | Make a new length or shape from an approved cut |
| `captions` | Build, check or burn in captions |
| **Sound** | |
| `score` | Design sound and music on the picture's clock |
| `mix` | Set a voice over music, cleaned and mastered for where it plays |
| **Check** | |
| `check` | Run every applicable check on a file before it ships, then hand it to a person to watch |
| `review` | Run a review round: people's notes, and critics whose findings are verified before anything changes |
| **Change and deliver** | |
| `revise` | Change an approved cut and check that everything else still matches the approved version |
| `deliver` | Encode for each platform, with hashes and a delivery report |

`studio` can lead another command: `/legible-film studio film our launch, budget $800`. Each command takes its part of
the same [nine-step method](#the-method).

## What's inside

**A film kit.** A small, dependency-free browser engine for type-led films, from a calm launch film to beat-cut
kinetic type. `make_film.py` takes a film from preflight to delivered, checked files in one command: claims bound to a
facts file, contrast and reading time checked on the film's own timeline, flashing predicted before a frame renders,
motion blur that respects cuts, and one timeline rendered at 16:9, 9:16 and 1:1. `--sound-only` remixes the sound
without re-rendering the picture: a new master for Atlasfold at both sizes took 82 seconds instead of the full make's
39 minutes on the author's laptop, with the picture bit-identical.

**Footage tools.** An edit lives in one `edit.json` that `assemble.py` renders frame-accurately: J and L cuts,
dissolves, retimes, crop paths, overlays, and HDR phone footage tone-mapped for ordinary screens. `transcript_cut.py`
proposes cuts in the gaps between words, `reframe.py` proposes a crop path for a tall frame from motion and detail,
`captions.py` builds, checks and burns captions clear of faces and platform buttons, and `voice_clean.py` makes a
conservative cleanup of a dialogue recording. Each proposal is for a person to review.

**A sound chain.** It works from the picture's own cue list: spotting that merges collisions and thins dense runs,
synthesised or licensed sounds, music that ducks under a voice phrase by phrase, mastering to the destination's
loudness with a limiter checked after a lossy re-encode, and a blind, loudness-matched A/B pair so a person chooses by
listening.

**Checks.** The QC scripts above, run on the exact file a viewer receives, feeding a delivery report that records
each result.

<details>
<summary>Every script, by stage</summary>

| Stage | Scripts |
|---|---|
| Make a kit film | `new_film.py`, `film_check.py` (preflight), `make_film.py` (one command to delivered files), `film_render.py`, `motion_blur.py` |
| Edit recordings | `transcript_cut.py`, `assemble.py`, `reframe.py`, `captions.py` |
| Sound | `tempo_map.py`, `make_sound_kit.py`, `sound_library.py`, `spot_cues.py`, `mix_cues.py`, `sound_check.py`, `voice_clean.py` |
| Check the delivered file | `qc_file.py`, `frame_sheet.py`, `flash_scan.py`, `blank_scan.py`, `motion_scan.py`, `region_check.py`, `cue_onsets.py`, `sync_check.py`, `compare_versions.py`, `onion_frames.py` |
| The environment | `selftest.py`, `kit_selftest.py` |

What each one answers is in [SKILL.md](skills/legible-film/SKILL.md#scripts). Every script explains itself with
`--help`.

```
skills/legible-film/
  SKILL.md            the method: principles, gates, commands and paths, nine steps, revisions, hard limits
  references/         story and score, timing, picture, sound, footage, formats, finishing, QC, review, the film
                      kit, kinetic type, studio grade, finding and making assets, claims and rights, and more
  scripts/            the tools above, plus a self-test
  assets/kit/         the film kit: engine, blocks, open-licence fonts, a starter film and the Atlasfold showcase
  assets/templates/   brief, treatment, facts, score, cues, sound palette, asset register, budget, review log,
                      critic brief, delivery report
evals/                behaviour and trigger evaluations for the skill itself
```

</details>

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

## The method

The commands draw on nine steps, each ending on a condition the agent can check:

1. **Brief, facts and format.** Who it is for, where it plays, what must read muted, a facts file for every claim, and
   a QC plan that maps each requirement to the check that measures it.
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
a file with sound, as unheard.

## Studio grade

For the best film the budget allows, start with `studio` or ask for it by name: "Use Legible Film at studio grade for
our launch film. Budget up to $800 for music, voice and stock." The agent then works the way a small studio would:

- **It leads with the film.** Its first reply describes two or three directions you can picture, then what you will
  see and decide at each step.
- **It shows before it asks.** You choose between things you can watch and hear: rough idea videos with temporary
  sound, sample stills of the look in every shape you will post, and a rough timed version of the whole film before
  anything is polished.
- **It spends on what the film needs most.** Purchases and generation runs are line items you approve against your
  cap, with each licence checked for the real use ([finding assets](skills/legible-film/references/assets.md),
  [making them](skills/legible-film/references/generation.md)).
- **It keeps raising the weakest moment** until viewers can answer six questions with evidence (understanding,
  specificity, experience, earned payoff, truth and afterimage) or you decide to stop.

Nothing is bought, uploaded or published without you. The full method is in
[studio](skills/legible-film/references/studio.md).

## Install

**Any agent that reads Agent Skills** (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, OpenCode, Amp, Goose).
In a terminal with Node.js installed, from your project folder:

```
npx skills add JamesDimachkie/legible-film
```

Add `-g` for a user-wide install or `-a codex` (or another agent name) to target one agent.

**Claude Code plugin.** In a Claude Code session:

```
/plugin marketplace add JamesDimachkie/legible-film
/plugin install legible-film@jamesdimachkie
```

The command is `/legible-film`; its full plugin name is `/legible-film:legible-film`.

**By hand:** copy `skills/legible-film/` into `~/.claude/skills/` for Claude Code, or into `.agents/skills/` (project)
or `~/.agents/skills/` (user) for most other agents.

**Requirements:** Python 3.9 or later, FFmpeg and ffprobe on `PATH`, and `pip install numpy Pillow` (into whichever
Python environment the agent will use) for the scripts. The film kit also needs Node.js 18 or later with Playwright and
Chromium. `/legible-film setup` checks all of it and prints the one command that fixes each missing piece; or ask your
agent: "Install Legible Film, check its requirements and run its self-test; ask me before changing anything that needs
my permission."

**Check the installation.** From a clone of this repository:

```
git clone https://github.com/JamesDimachkie/legible-film
cd legible-film
python skills/legible-film/scripts/selftest.py
```

If you installed through a plugin or `npx skills`, the same script sits in the installed skill's `scripts/` folder;
ask your agent to run the Legible Film skill's self-test. It builds synthetic media with known answers in a temporary
folder and runs about 400 checks across every script in a few minutes. It counts any case it could not run (the
film-kit cases need Playwright) and records a passing environment in your user cache, so the next run can skip it;
`--quick` checks the dependencies in seconds.

## Evidence

- **Behaviour (1.0.0).** In a small blind-graded test (five requests, one run per arm on one model), agents with the
  skill met 35 of 35 expectations and agents without it met 10 of 35. Three of the requests were rewritten and run
  again after a first round in which both arms lacked their input files; both rounds are published. Every prompt, output and grade is
  [published](evals/results/2026-10-27/README.md), with what the test could not control.
- **Studio grade (1.1.0).** In a blind comparison with 1.0.1, which has the method but not studio grade, the plans
  1.1.0 made won all four pairs: two studio-grade requests, two runs each, one model, judged by a different model
  family at medium confidence. The 1.0.1 plans were more concrete about what appears on screen
  ([evidence](evals/results/2026-10-28-studio-vs-1.0.1/README.md)). That measures plans, not finished films.
- **The showcase.** Atlasfold above was watched by its author after its final revision, and its sound chosen in a
  blind A/B listen.

What has not been measured is in [Limits](#limits).

## Limits

- The scripts measure; they do not watch or listen. Rhythm, feel, comprehension and how the sound sounds are decided
  by people, and the skill says so in every report.
- `flash_scan.py` screens for WCAG 2.3.1 flashing. It is not a Harding, IRIS or broadcast PSE certification.
- Tool versions, platform specs and provider terms in the references were checked between 2026-10-27 and 2026-10-29
  and change often; each is dated, and linked to its source wherever a stable page exists, so it can be re-checked.
- Evaluations are small: seven requests on one model, one or two runs per arm, graded blind by another model family
  against expectations written by the skill's author. They measure plans and behaviour, not how good a finished film
  is. Evals 8-11, added in 1.2.0 for the film kit, footage editing and dialogue, have not been run yet, and no edit of
  real footage made with the skill has been watched by a person. Whether agents load the skill unprompted has not
  been tested. Details are in [evals/README.md](evals/README.md).
- The footage tools work on measurements, not understanding: `reframe.py` follows sustained motion and detail, not a
  recognised subject, so its path is a proposal to review; `transcript_cut.py` proposes cuts in word gaps for a person
  to listen to; the burned-caption check estimates text from frame changes, which moving faces and cuts can confuse.
  `voice_clean.py` is a conservative starting point, never an automatic fix.
- Edits don't round-trip to editing applications yet: `edit.json` is rendered by `assemble.py`, and there is no
  Premiere, Final Cut or Resolve exchange.
- The film kit renders through a headless browser and is built for type-led motion graphics, not photoreal or 3D
  work; the references route those to other engines.

## Contributing

Suggestions and fixes are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md). Rules change only with evidence (a defect,
a measurement, a source), and every script change keeps `selftest.py` passing.

## Licence

Apache-2.0. Copyright 2026 James Dimachkie. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
