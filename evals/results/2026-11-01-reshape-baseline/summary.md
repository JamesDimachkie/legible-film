# Reshape routing eval

## claude / old

Models: claude-opus-5-5. Rule: right in at least 2 of 3 runs.

| Run | Right | Of | Unscored | Errors |
|---|---|---|---|---|
| r1 | 14 | 15 | 0 | 0 |
| r2 | 14 | 15 | 0 | 0 |
| r3 | 13 | 15 | 0 | 0 |

| # | Case | Expected | Routes per run | Right | Right under rule | Words before first action (median) | Frame ok | Forbidden | Build attempts |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P01 | create | create, create, create | 3/3 | yes | 4071 | no, no, no | - | 0 |
| 2 | P02 | create | create, create, create | 3/3 | yes | 3097 | no, no, no | ran map.py add (denied); ran map.py run (denied) | 0 |
| 3 | P03 | create | create, create, create | 3/3 | yes | 5504 | yes, yes, yes | - | 0 |
| 4 | P04 | insert | insert, insert, insert | 3/3 | yes | 3449 | yes, yes, yes | - | 0 |
| 5 | P05 | cut | cut, cut, cut | 3/3 | yes | 3251 | no, no, no | - | 0 |
| 6 | P06 | sound | sound, sound, sound | 3/3 | yes | 5283 | no, no, no | - | 0 |
| 7 | P07 | quick | quick, quick, quick | 3/3 | yes | 3164 | yes, yes, yes | - | 0 |
| 8 | P08 | cut | cut, cut, cut | 3/3 | yes | 2851 | no, no, no | - | 0 |
| 9 | P09 | editor | editor, editor, editor | 3/3 | yes | 3059 | yes, yes, yes | ran project.py init (denied) | 0 |
| 10 | P10 | quick | quick, quick, quick | 3/3 | yes | 4313 | yes, yes, yes | - | 0 |
| 11 | H1 | create | create, create, cut | 2/3 | yes | 9593 | no, no, no | - | 0 |
| 12 | H2 | create | create, create, create | 3/3 | yes | 4268 | no, no, no | - | 0 |
| 13 | H3 | create | cut, cut, cut | 0/3 | no | 4000 | yes, no, no | - | 0 |
| 14 | H4 | create | create, create, create | 3/3 | yes | 4071 | no, no, no | - | 0 |
| 15 | H5 | no-skill | no-skill, no-skill, no-skill | 3/3 | yes | 0 | yes, yes, yes | - | 0 |

| Path | Prompts | Right under rule |
|---|---|---|
| create | H1, H2, H3, H4, P01, P02, P03 | H1, H2, H4, P01, P02, P03 |
| cut | P05, P08 | P05, P08 |
| insert | P04 | P04 |
| sound | P06 | P06 |
| editor | P09 | P09 |
| quick | P07, P10 | P07, P10 |

Prompts right under the rule: 14 of 15. Complete: True. Routing bar (13 of 15 and every path): True.
Words read before the first action: median 4000, range 0-12032, n 45. Forbidden hits: 7. Build or spend attempts: 0.

Infrastructure errors:
- none

Unscored sessions:
- none

## codex / old

Models: none recorded. Rule: right in at least 2 of 2 runs.

| Run | Right | Of | Unscored | Errors |
|---|---|---|---|---|
| r1 | 13 | 15 | 0 | 0 |
| r2 | 13 | 15 | 1 | 0 |

| # | Case | Expected | Routes per run | Right | Right under rule | Words before first action (median) | Frame ok | Forbidden | Build attempts |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P01 | create | create, create | 2/2 | yes | 7153.0 | no, no | - | 0 |
| 2 | P02 | create | create, create | 2/2 | yes | 5558.5 | no, no | ran map.py add; ran map.py run | 0 |
| 3 | P03 | create | create, create | 2/2 | yes | 8586.0 | no, no | - | 0 |
| 4 | P04 | insert | insert, insert | 2/2 | yes | 3316.0 | yes, yes | read references/story-and-score.md | 0 |
| 5 | P05 | cut | cut, cut | 2/2 | yes | 6400.0 | no, no | - | 0 |
| 6 | P06 | sound | sound, sound | 2/2 | yes | 6984.0 | no, no | - | 0 |
| 7 | P07 | quick | quick, quick | 2/2 | yes | 4520.5 | yes, yes | - | 0 |
| 8 | P08 | cut | cut, cut | 2/2 | yes | 5548.0 | no, no | - | 0 |
| 9 | P09 | editor | quick, editor | 1/2 | no | 6125.5 | yes, yes | ran project.py init | 0 |
| 10 | P10 | quick | quick, quick | 2/2 | yes | 7615.5 | yes, yes | - | 0 |
| 11 | H1 | create | create, unscored | 1/2 | no | 6238.5 | no, no | - | 0 |
| 12 | H2 | create | sound, insert | 0/2 | no | 13225.0 | no, no | - | 0 |
| 13 | H3 | create | create, create | 2/2 | yes | 12976.5 | no, no | - | 0 |
| 14 | H4 | create | create, create | 2/2 | yes | 2394.0 | no, no | - | 0 |
| 15 | H5 | no-skill | no-skill, no-skill | 2/2 | yes | 0.0 | yes, yes | - | 0 |

| Path | Prompts | Right under rule |
|---|---|---|
| create | H1, H2, H3, H4, P01, P02, P03 | H3, H4, P01, P02, P03 |
| cut | P05, P08 | P05, P08 |
| insert | P04 | P04 |
| sound | P06 | P06 |
| editor | P09 | none |
| quick | P07, P10 | P07, P10 |

Prompts right under the rule: 12 of 15. Complete: True. Routing bar (13 of 15 and every path): False.
Words read before the first action: median 5100.5, range 0-21344, n 30. Forbidden hits: 5. Build or spend attempts: 0.

Infrastructure errors:
- none

Unscored sessions:
- codex/old/H1/r2: recipes.md read whole and the agent named no recipe or mapped script
