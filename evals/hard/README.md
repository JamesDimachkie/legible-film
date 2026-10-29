# Hard outcome evaluation (hard-v1)

Four tasks that ask an agent to make, repair, audit and decide on real files, then grade what it left behind. A
script decodes the run's outputs and scores 22 items worth 90 points. Three further judgements (communication, craft
and the precision of one question) are blind pairwise comparisons, reported separately and never added to the 90.

The full design, with the exact prompts, planted ground truth, every item's pass condition and the reasons each item
is expected to be hard, is in [DESIGN.md](DESIGN.md). The engineering pilot is in [PILOT.md](PILOT.md).

## What it measures, and what it does not

It measures reliable production under conflicting evidence and exact preservation constraints: finding defects at
the right frame or millisecond with decoded evidence, changing one thing and proving nothing else moved, rendering
two finished films that keep locked copy, colour and sound sync, and holding a release that lacks authority while
finishing the safe work. A tool name, a promised check or a claim to have watched or listened earns nothing.

It does not measure film quality, comprehension, legibility, photosensitivity safety, loudness quality or legal
clearance. The automatic score checks a fixed synthetic contract; whether a film is good is left to the blind
judgements in DESIGN.md.

## The four tasks

| ID | Task | Points |
|---|---|---:|
| 101 | Forensic delivery audit: locate six planted picture and sound defects in a delivered file, with decoded evidence, leaving intentional holds alone | 26 |
| 102 | Surgical revision: repair one closing qualifier in an approved film without changing any other pixel, timestamp, sample or cue byte | 22 |
| 103 | Render under conflicting pressure: two finished teasers (640x360 and 360x640) with the supported claim, intact qualifier, true brand colour, a safe flash count and sound synced by attack, apex and end | 32 |
| 104 | Release decision with missing authority: corrected copy, an asset-rights decision, a held release and one precise question | 10 |

## Requirements

Python 3.12 with numpy and Pillow, and FFmpeg with ffprobe on PATH. Run every command from `evals/hard/`, with an
explicit interpreter and `-I`. The examples use PowerShell; set `$py` to your Python 3.12 executable first.

Every output path defaults to a folder here (`fixtures/`, `runs/`, `grades/`, `pilot/`), and the scripts refuse to
write outside `evals/hard/`. Generated files are ignored by `.gitignore`; never commit them.

## Build the fixtures and check them

```powershell
& $py -I make_hard_fixtures.py --out fixtures --seed 20261028
& $py -I make_hard_fixtures.py --out fixtures --check
```

The generator draws every picture, glyph, sound and record itself; nothing is downloaded or borrowed. It refuses to
overwrite an existing set: use a new `--out` folder for another seed. `--check` decodes the actual files and verifies
each planted defect (15 checks), writing `fixtures/fixture-check.json`.

Only `fixtures/public/h101` to `h104` may reach a runner. `fixtures/oracle/` holds the answers and must never be
staged with a run or shown to a judge.

## Prepare runs

```powershell
& $py -I prepare_hard_runs.py --task 103 --name h103-v120-s1-r1 --skill <frozen-skill-directory>
& $py -I prepare_hard_runs.py --task 103 --name h103-noskill-s1-r1
```

Each call stages one run in `runs/<name>/`: the task's listed public inputs under `input/` and, with `--skill`, a
copy of a frozen skill directory at `.agents/skills/legible-film/`. It writes the literal prompt to
`runs/_logs/<name>.prompt.txt`, adds the name to `runs/_logs/jobs.txt`, sets `parallel.txt` to 1 and records input,
skill and prompt hashes in a custody file. It never launches a model.

The prompt names the Python the runner should use. `hard-evals.json` holds a `{python}` placeholder, which the
preparer fills from `--python <path>` or, by default, from the Python running it. Use the same value for every arm.

## Grade

After a run is closed and its files hashed, grade it from outside the run:

```powershell
& $py -I grade_hard.py --fixtures fixtures --run runs/h103-v120-s1-r1 --task h103
& $py -I grade_hard.py --fixtures fixtures --run pilot/perfect --task all --out grades/perfect.json
```

`--task all` expects subfolders `h101/` to `h104/`. The grade goes to `grades/<run folder>.json` unless `--out`
names another path here, with pass or fail, points and measured evidence for each item. The grader never runs
submitted code or trusts submitted measurements. It exits 0 when it writes a report, including a score of zero, and
2 when the trusted fixtures or the grader itself fail.

## Pilot: a grader check, not a skill result

Hand-made controls on the development seed, built and graded by `build_pilot.py`:

| Control | Automatic points |
|---|---:|
| Positive control, made knowing the answers | 90/90 |
| Empty outputs, inputs present | 0/90 |
| Checklist prose only, claiming every check | 0/90 |
| Plausible near miss | 57/90 |

Four single-task mutations (false audio evidence, audio 18 ms late, reference-style flashing, an 18 ms mux offset)
each failed only their intended items. This shows the grader separates these controls. No coding agent or judge was
run, so it says nothing yet about either skill version or about film quality.

```powershell
& $py -I build_pilot.py --fixtures fixtures --out pilot
```

## Validity limits

- **Construct and oracle bias.** Rigid legal tiles, known source precedence, a small synthetic sound vocabulary and an
  exact lossless target can reward solving this engineered contract rather than making better real films.
- **The author knows every answer.** One author wrote the fixtures, the oracle and the grader, which share a media
  module. Mutation tests and independent decodes reduce this; independent review of the oracle has not been done.
- **Synthetic contracts.** Task 104's licences and marks are invented; its grade is not legal advice or clearance.
  Task 103's flash screen and peak estimate are task-specific checks, not certifications.
- **No OCR.** Locked panels are checked by pixel identity, not by reading text. Wrong copy added elsewhere in a frame
  needs the blind review.
- **Single runner family.** The planned runs use one runner family with shared global instructions and small samples.
  Freeze versions, keep both arms identical and report these limits next to any result.
- Byte-identical fixtures were confirmed on one Python, numpy, Pillow and FFmpeg stack. On another stack, regenerate,
  run `--check` and pin the new input hashes before comparing versions.
