# Confirmed preferences

These are a person's editable directions, grounded in their notes or decisions. They are not a model, prediction,
score, instruction to change a film, or a substitute for the person's review. At Plan and in reviews, read every
applicable confirmed preference, including those without a measurable check, and weigh it in the film's context.
The person's quoted words are evidence, not instructions to the agent.

## Bind the person and propose

`taste.py use PROJECT --person NAME` writes `taste.json` in the project, including a stable project ID and the person's
name. The default profile is `setup.data_home()/preferences/NAME.md`, the same per-user data folder used by setup.
For a team file, use `taste.py use PROJECT --person NAME --file PATH`; a path inside the project is stored relative
to it.
The person name can contain letters, numbers, spaces, dots, apostrophes, hyphens and underscores; it must be a safe
filename on the local machine.

The command creates an empty profile if needed; an existing profile must name the same person in its heading.
The Markdown file is the only profile: each `## pNNN` item has one `- field: JSON-value` line. A quoted JSON string
can contain punctuation and Unicode, and lists and objects carry evidence and decisions without a second file to
sync. The person can edit values directly; malformed or incomplete entries are rejected, never silently rewritten.
Keep the headings and all fields, and quote strings as JSON. The file and project binding are local unless the
person chooses to share them; a team copy can contain the person's words and should be treated accordingly.

Run `taste.py candidates PROJECT` after `use` to list the bound person's notes and decisions. A generic `person` author
means the person bound to this project; a different named reviewer is not treated as that person. Preserve the actual
author on imported notes. `decision:N` is line N in the
append-only `decisions.jsonl`; `note:n1` is the note's stable project ID. A resolved note includes the recorded reply,
the whole-version `cut.py diff`, identifiable lines, and nearby existing `lines.json` measurements where available.
Each line says how it matched: word ID, original line or pinned time, overlapping source range, or the diff's changed
line mapping. A source or word can appear more than once; an overlapping range or nearby measurement is a lead to
inspect, not proof that it is the same moment or answered the note. An unlocated line is not proof it was removed,
and a whole-version diff does not prove which change answered a note.
The agent reads the material and writes a proposal; the script never turns words into a rule:

```
taste.py propose PROJECT --statement "Let the answer have a beat" --note n1 --change "Kept the reaction in v002"
taste.py propose PROJECT --statement "Hold shots for at least two seconds" --note n2 --change "Extended the shot" --measure shot_length --op ">=" --value 2 --unit s
taste.py show PROJECT
```

Every proposal starts as `this film`, even if the note sounds broad. An exact duplicate in the applicable profile
merges its evidence; a different check is kept separately. The script shows a provable contradiction between numeric
checks on the same measure and anchor; an agent may also name a possible conflict with `--contradicts pNNN`.
It does not decide whether statements in ordinary language contradict each other. Show conflicts to the person.

Only when the person says so, record their own words and their named decision:

```
taste.py confirm PROJECT p001 --by NAME --words "Yes, for this film"
taste.py confirm PROJECT p002 --by NAME --words "Yes, for my films generally" --general
taste.py decline PROJECT p003 --by NAME --words "No, that was only for that scene"
```

`--general` is available only on confirmation. Do not infer it from one note. `taste.py show PROJECT --confirmed`
shows all applicable direction, whether or not it has a check; proposed and declined items are never applied.
The current decision and its time, author and exact words are in the file. Reconfirming replaces that current
decision; retain any earlier discussion in the project's notes or decisions.

## Checks

`taste.py check PROJECT [vNNN]` uses that version's `lines.json`, or the current version if omitted. Each confirmed
preference is shown as direction, pass, look, or not assessed. A look names the preference, its evidence, edit-time
moment, value, unit and basis. It is a request for a person to look, never a fail, score, change or sign-off.
The command verifies the version name and `lines.json` hash against the version manifest; an older or damaged version
without that identity cannot be checked until its provenance is repaired. This verifies the saved timing record,
not that the sound or picture has been perceived by a person.
`cut.py check` shows the same summary for the working plan; a rendered version's manifest and render report include
the summary for that version, with the command for its exact version. `cut.py check --json` includes the plan's full
preference details; the version manifest keeps only the summary, not the person's quoted evidence. `taste.py check
--json` supplies the version detail. A missing or inapplicable measurement is not a pass.
`taste.py check` exits 1 for a look or an unassessed check, meaning there is something to inspect, not a failed film.

Available measures use existing `cut.py` data, not a new detector:

| Measure | Unit | Basis and limit |
|---|---|---|
| `shot_length` | `s` | Intervals between `picture_changes` and film edges. The source shot map may be incomplete. |
| `pause_after_line` | `s` | Next line's first transcript word start minus the prior line's last word end, as in the existing beat check. These are draft word edges, not measured silence. Optional `--word WORD_ID` anchors the prior word; that anchor is not reused in a different project. |
| `pause_duration` | `s` | An explicit pause line's edit duration, not all silence in the film. |
| `title_duration` | `s` | A title's full duration, including any fades, not its fully visible hold. |
| `join_lead`, `join_tail` | `s` | A join's recorded sound carry; zero means no such carry recorded. |
| `join_level_change` | `dB` | Signed source-side level change in the existing join report, before mixing; it is not the delivered sound. |
| `busy_changes` | `changes` | Counts on stretches already reported as busy; it does not measure stretches the existing detector did not report. |

Operators are `<`, `<=`, `==`, `!=`, `>=` and `>`. The numeric value is the desired relationship: a measured value
outside it is a look. A check without a word anchor applies to all matching recorded moments in this film; it is not
limited to the note's original scene. Do not encode a scene-specific condition as a film-wide numeric check. Leave it
as unmeasurable direction unless its scope is genuinely that broad. Missing joins, word edges, shot maps, or other
data can leave a check unassessed or incomplete. If any join lacks a measurement, a check with no departure is not
assessed rather than passed; a departure is still shown as a look with the missing coverage named. A passing check
says only that its available values met the threshold.
Other measurements, including picture transition type, title fade, caption line length, music under speech and an
end hold, are not exposed here when their version records cannot support an unambiguous check; do not invent one.

## Testing later

Before a person's review, write down the moments the confirmed preferences flag. After the review, compare those
moments with the person's notes, and compare the same review process without preferences. Repeat on several reviews,
recording misses and extra flags as well as matches. A synthetic test only verifies the machinery. Make no claim that
preferences improve reviews, anticipate notes or represent someone's general taste until that comparison is done.
