# Reshape routing eval

## claude / new

Models: claude-opus-5-5. Rule: right in at least 2 of 3 runs.

| Run | Right | Of | Unscored | Errors |
|---|---|---|---|---|
| r1 | 14 | 15 | 0 | 0 |
| r2 | 14 | 15 | 0 | 0 |
| r3 | 14 | 15 | 0 | 0 |

| # | Case | Expected | Routes per run | Right | Right under rule | Words before first action (median) | Frame ok | Forbidden | Build attempts |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P01 | create | create, create, create | 3/3 | yes | 18128 | no, no, yes | - | 0 |
| 2 | P02 | create | create, create, create | 3/3 | yes | 2041 | no, no, no | - | 0 |
| 3 | P03 | create | create, create, create | 3/3 | yes | 2041 | yes, yes, yes | - | 0 |
| 4 | P04 | insert | insert, insert, insert | 3/3 | yes | 11111 | no, yes, yes | - | 0 |
| 5 | P05 | cut | cut, cut, cut | 3/3 | yes | 2368 | no, no, no | - | 0 |
| 6 | P06 | sound | sound, sound, sound | 3/3 | yes | 1633 | no, no, no | - | 0 |
| 7 | P07 | quick | quick, quick, quick | 3/3 | yes | 4543 | yes, yes, yes | - | 0 |
| 8 | P08 | cut | cut, cut, cut | 3/3 | yes | 3372 | yes, no, no | - | 0 |
| 9 | P09 | editor | editor, editor, editor | 3/3 | yes | 1575 | yes, yes, yes | ran project.py init (denied) | 0 |
| 10 | P10 | quick | quick, quick, quick | 3/3 | yes | 1641 | yes, yes, yes | - | 0 |
| 11 | H1v2 | create | create, create, create | 3/3 | yes | 5023 | no, no, yes | - | 2 |
| 12 | H2v2 | create | create, create, create | 3/3 | yes | 2041 | no, no, no | - | 0 |
| 13 | H3v2 | create | cut, cut, cut | 0/3 | no | 2368 | no, no, no | - | 0 |
| 14 | H4v2 | create | create, create, create | 3/3 | yes | 2041 | yes, no, no | - | 0 |
| 15 | H5v2 | no-skill | no-skill, no-skill, no-skill | 3/3 | yes | 0 | yes, yes, yes | - | 0 |
| 16 | R16 | create | create, create, create | 3/3 | yes | 1010 | no, yes, no | ran tsrct; ran tsrct (denied) | 4 |
| 17 | R17 | quick | quick, quick, quick | 3/3 | yes | 1641 | yes, yes, yes | - | 0 |
| 18 | R18 | quick | quick, quick, quick | 3/3 | yes | 1641 | no, yes, yes | - | 0 |
| 19 | R19 | create | unscored, unscored, unscored | 0/3 | no | 1010 | yes, yes, yes | - | 0 |
| 20 | R20 | cut | editor, editor, editor | 0/3 | no | 1575 | no, no, yes | - | 0 |

| Path | Prompts | Right under rule |
|---|---|---|
| create | H1v2, H2v2, H3v2, H4v2, P01, P02, P03 | H1v2, H2v2, H4v2, P01, P02, P03 |
| cut | P05, P08 | P05, P08 |
| insert | P04 | P04 |
| sound | P06 | P06 |
| editor | P09 | P09 |
| quick | P07, P10 | P07, P10 |

Prompts right under the rule: 14 of 15. Complete: True. Routing bar (13 of 15 and every path): True.
Words read before the first action: median 2368, range 0-20297, n 45. Forbidden hits: 6. Build or spend attempts: 6.

Route checks 16-20 (each required; passed per run):

- R16: failed, failed, failed
- R17: failed, failed, failed
- R18: passed, passed, passed
- R19: passed, passed, passed
- R20: passed, passed, passed

Infrastructure errors:
- none

Unscored sessions:
- claude/new/R19/r1: the skill loaded but no path-mapped file was read or run
- claude/new/R19/r2: the skill loaded but no path-mapped file was read or run
- claude/new/R19/r3: the skill loaded but no path-mapped file was read or run

