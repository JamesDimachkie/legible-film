# Commands

Every 2.0 command still works. The person may start with a command (`/legible-film cut ...` in Claude Code,
`$legible-film ...` in Codex) or describe the job in their own words; either way the work runs on one path. Each name
below resolves to one path. A `fixed` name always opens its path. A `by timeline` name acts on the project's owner
(`film.md` `timeline`) inside a project, and opens the listed path outside one, unless its row says otherwise.

The paths: [create](../paths/create.md) · [cut](../paths/cut.md) · [insert](../paths/insert.md) ·
[sound](../paths/sound.md) · [editor](../paths/editor.md) · [quick](../paths/quick.md). An old link into
[recipes](recipes.md) lands on a heading that names the path its recipe moved to.

| Name | Path | Dispatch | For |
|---|---|---|---|
| `kit` | create | fixed | A type-led film, sting or loop made with the bundled film kit ([kit](kit.md), [blocks](../assets/kit/BLOCKS.md)) |
| `teaser` | create | fixed | A short, beat-cut film of big words, made with the kit |
| `look` | create | by timeline | The person's references, or their expectations, for the project's film on its own timeline ([look](look.md), [template](../assets/templates/look.md)); outside a project, read the reference only and start no film |
| `moodboard` | create | by timeline | The same as `look`; outside a project, read the reference only and start no film |
| `taste` | create | by timeline | Propose, confirm and show the person's preferences for the project in hand ([taste](taste.md)); outside a project, read the reference only and start no film |
| `preferences` | create | by timeline | The same as `taste`; outside a project, read the reference only and start no film |
| `studio` | create | fixed | The best film a budget allows ([studio](studio.md) on top of the path; [case-library](case-library.md)) |
| `launch` | create | fixed | New alias: a launch film |
| `design` | create | fixed | New alias: a designed film or motion graphics |
| `motion` | create | fixed | New alias: motion graphics |
| `map` | cut | fixed | Make the sources legible: transcripts, shots, sound |
| `plan` | cut | fixed | The brief when one is needed, and the paper edit |
| `brief` | cut | fixed | The same as `plan`; a brief when audience, destination or approval matter ([template](../assets/templates/brief.md)) |
| `film` | cut | fixed | The same as `plan` |
| `cut` | cut | fixed | Render the paper edit; with only raw sources, start at the map |
| `shorts` | cut | fixed | Short clips from a long video, or a new length or shape |
| `cutdown` | cut | fixed | The same as `shorts` |
| `tighten` | cut | fixed | Shorten measured dead air as a paper edit, with a reel of every removal |
| `screen` | cut | by timeline | Open the Screening Room on the current version |
| `review` | cut | by timeline | The same as `screen` |
| `revise` | cut | by timeline | Apply notes and show what else changed |
| `deliver` | cut | by timeline | Final files, captions, mastering and the delivery report |
| `insert` | insert | fixed | An animation in place of a passage's picture, timed to its words |
| `graphics` | insert | fixed | A lower third, logo or title over the footage |
| `cavalry` | insert | fixed | The same as `graphics`, built in Cavalry |
| `spatial` | insert | fixed | Pin a graphic to a moving surface or put a title behind a person ([spatial](spatial.md)) |
| `track` | insert | fixed | The same as `spatial` |
| `blur` | insert | fixed | A blur that follows a face or a plate |
| `score` | sound | fixed | Sound for a picture: effects, a bed, a score |
| `mix` | sound | fixed | A mix of voice, music and effects to picture |
| `sound` | sound | fixed | New alias: sound for a picture |
| `sfx` | sound | fixed | New alias: effects for a picture |
| `premiere` | editor | fixed | Follow an editor's Premiere or Resolve timeline and captions through revisions |
| `handoff` | editor | by timeline | A version as Final Cut Pro 7 XML for an editor to finish |
| `export` | editor | fixed | The same as `handoff` from a paper project |
| `quick` | quick | fixed | A one-file change: trim, reframe, convert, compress, extract audio, GIF, speed |
| `check` | quick | by timeline | Check a version or any file |
| `grade` | quick | fixed | A scorecard for a version or any file ([grading](grading.md)) |
| `captions` | quick | by timeline | Captions for a video |
| `setup` | quick | fixed | Check this machine and install what it needs |
| `doctor` | quick | fixed | The same as `setup` |
| `convert` | quick | fixed | New alias: convert one file |

## Dispatch by timeline

`setup` and `doctor` run before any path. Outside a project, `check` and `captions` work on a file (quick), and the
stage verbs open the cut path. Inside a project they act on its owning timeline, so a version registered from a page
is screened, checked and graded with `screen.py`, `check.py` and `grade.py`, never `cut.py`.

| Owner (`film.md` `timeline`) | check | screen, review | revise | deliver | handoff | captions |
|---|---|---|---|---|---|---|
| paper | `check.py PROJECT` | `screen.py build PROJECT` | change `film.md`, then `cut.py render` | `cut.py render --final`, then [Deliver](loop.md#deliver) | `exchange.py write PROJECT vNNN --out handoff.xml --verify` | inside the project ([cut](../paths/cut.md)) |
| page, picture or tesseract | `check.py PROJECT` on the registered version | `screen.py build PROJECT` | change the page, re-export, `project.py add-version` | the final render through `project.py add-version`, then Deliver | the master at its exact rate, with its cue list | from the master's words |
| editor | `check.py --file` on their export | a short report of the changed moments | repairs by timecode | the repair list and its checks | their timeline, back with the repairs | the caption checks of [editor](../paths/editor.md) step 3 |
