# Reshape routing eval

## codex / new

Models: none recorded. Rule: right in at least 2 of 2 runs.

| Run | Right | Of | Unscored | Errors |
|---|---|---|---|---|
| r1 | 14 | 15 | 0 | 0 |
| r2 | 14 | 15 | 0 | 0 |

| # | Case | Expected | Routes per run | Right | Right under rule | Words before first action (median) | Frame ok | Forbidden | Build attempts |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P01 | create | create, create | 2/2 | yes | 20322.0 | no, no | - | 0 |
| 2 | P02 | create | create, create | 2/2 | yes | 8315.5 | no, no | - | 0 |
| 3 | P03 | create | create, create | 2/2 | yes | 31601.5 | yes, yes | - | 0 |
| 4 | P04 | insert | insert, insert | 2/2 | yes | 8820.5 | yes, yes | - | 0 |
| 5 | P05 | cut | cut, cut | 2/2 | yes | 15330.5 | no, no | - | 0 |
| 6 | P06 | sound | sound, sound | 2/2 | yes | 14807.5 | no, no | - | 0 |
| 7 | P07 | quick | quick, quick | 2/2 | yes | 4543.0 | yes, yes | - | 0 |
| 8 | P08 | cut | cut, cut | 2/2 | yes | 24101.5 | no, no | - | 0 |
| 9 | P09 | editor | editor, editor | 2/2 | yes | 5183.5 | yes, yes | - | 0 |
| 10 | P10 | quick | quick, quick | 2/2 | yes | 12277.0 | yes, yes | - | 0 |
| 11 | H1v2 | create | create, create | 2/2 | yes | 15747.0 | no, no | - | 0 |
| 12 | H2v2 | create | create, create | 2/2 | yes | 29619.5 | no, no | - | 0 |
| 13 | H3v2 | create | cut, cut | 0/2 | no | 15821.0 | no, no | - | 0 |
| 14 | H4v2 | create | create, create | 2/2 | yes | 26059.5 | no, no | - | 0 |
| 15 | H5v2 | no-skill | no-skill, no-skill | 2/2 | yes | 0.0 | yes, yes | - | 0 |
| 16 | R16 | create | create, create | 2/2 | yes | 5416.5 | no, no | ran tsrct; ran tsrct (denied) | 1 |
| 17 | R17 | quick | quick, quick | 2/2 | yes | 4367.5 | yes, yes | - | 0 |
| 18 | R18 | quick | quick, quick | 2/2 | yes | 2819.5 | yes, yes | - | 0 |
| 19 | R19 | create | create, create | 2/2 | yes | 7423.0 | yes, yes | - | 0 |
| 20 | R20 | cut | cut, editor | 1/2 | no | 10157.0 | no, yes | - | 0 |

| Path | Prompts | Right under rule |
|---|---|---|
| create | H1v2, H2v2, H3v2, H4v2, P01, P02, P03 | H1v2, H2v2, H4v2, P01, P02, P03 |
| cut | P05, P08 | P05, P08 |
| insert | P04 | P04 |
| sound | P06 | P06 |
| editor | P09 | P09 |
| quick | P07, P10 | P07, P10 |

Prompts right under the rule: 14 of 15. Complete: True. Routing bar (13 of 15 and every path): True.
Words read before the first action: median 12833.5, range 0-37594, n 30. Forbidden hits: 3. Build or spend attempts: 1.

Route checks 16-20 (each required; passed per run):

- R16: failed, failed
- R17: failed, failed
- R18: passed, passed
- R19: passed, passed
- R20: passed, passed

Infrastructure errors:
- none

Unscored sessions:
- none

