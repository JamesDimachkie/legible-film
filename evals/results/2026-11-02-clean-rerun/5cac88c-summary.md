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
| 1 | P01 | create | create, create, create | 3/3 | yes | 2027 | no, no, no | - | 0 |
| 2 | P02 | create | create, create, create | 3/3 | yes | 2027 | no, no, no | - | 0 |
| 3 | P03 | create | create, create, create | 3/3 | yes | 2027 | yes, yes, yes | - | 0 |
| 4 | P04 | insert | insert, insert, insert | 3/3 | yes | 1752 | yes, yes, yes | - | 0 |
| 5 | P05 | cut | cut, cut, cut | 3/3 | yes | 2392 | no, no, no | - | 0 |
| 6 | P06 | sound | sound, sound, sound | 3/3 | yes | 1631 | yes, yes, yes | - | 0 |
| 7 | P07 | quick | quick, quick, quick | 3/3 | yes | 2180 | yes, yes, yes | - | 0 |
| 8 | P08 | cut | cut, cut, cut | 3/3 | yes | 2259 | yes, yes, no | - | 0 |
| 9 | P09 | editor | editor, editor, editor | 3/3 | yes | 1573 | yes, yes, yes | - | 0 |
| 10 | P10 | quick | quick, quick, quick | 3/3 | yes | 1601 | yes, yes, yes | - | 0 |
| 11 | H1v2 | create | create, create, create | 3/3 | yes | 5009 | yes, no, no | - | 0 |
| 12 | H2v2 | create | create, create, create | 3/3 | yes | 2027 | yes, yes, no | - | 0 |
| 13 | H3v2 | create | cut, cut, cut | 0/3 | no | 1857 | no, no, yes | - | 0 |
| 14 | H4v2 | create | create, create, create | 3/3 | yes | 2027 | yes, no, yes | - | 0 |
| 15 | H5v2 | no-skill | no-skill, no-skill, no-skill | 3/3 | yes | 0 | yes, yes, yes | - | 0 |
| 16 | R16 | create | error, error, error | 0/3 | no | None |  | - | 0 |
| 17 | R17 | quick | quick, quick, quick | 3/3 | yes | 1968 | yes, yes, yes | - | 0 |
| 18 | R18 | quick | quick, quick, quick | 3/3 | yes | 1601 | yes, no, no | - | 0 |
| 19 | R19 | create | unscored, unscored, unscored | 0/3 | no | 2666 | yes, yes, yes | - | 0 |
| 20 | R20 | cut | cut, editor, unscored | 1/3 | no | 1008 | yes, yes, yes | - | 0 |

| Path | Prompts | Right under rule |
|---|---|---|
| create | H1v2, H2v2, H3v2, H4v2, P01, P02, P03 | H1v2, H2v2, H4v2, P01, P02, P03 |
| cut | P05, P08 | P05, P08 |
| insert | P04 | P04 |
| sound | P06 | P06 |
| editor | P09 | P09 |
| quick | P07, P10 | P07, P10 |

Prompts right under the rule: 14 of 15. Complete: True. Routing bar (13 of 15 and every path): True.
Words read before the first action: median 2027, range 0-7107, n 45. Forbidden hits: 0. Build or spend attempts: 0.

Route checks 16-20 (each required; passed per run):

- R16: error, error, error
- R17: failed, failed, failed
- R18: passed, passed, passed
- R19: passed, passed, passed
- R20: passed, passed, passed

Infrastructure errors:
- claude/new/R16/r1: RuntimeError: Tesseract is installed (%LOCALAPPDATA%\Tesseract\bin\tsrct.cmd); route check 16 needs an environment without it
- claude/new/R16/r2: RuntimeError: Tesseract is installed (%LOCALAPPDATA%\Tesseract\bin\tsrct.cmd); route check 16 needs an environment without it
- claude/new/R16/r3: RuntimeError: Tesseract is installed (%LOCALAPPDATA%\Tesseract\bin\tsrct.cmd); route check 16 needs an environment without it

Unscored sessions:
- claude/new/R19/r1: the skill loaded but no path-mapped file was read or run
- claude/new/R19/r2: the skill loaded but no path-mapped file was read or run
- claude/new/R19/r3: the skill loaded but no path-mapped file was read or run
- claude/new/R20/r3: the skill loaded but no path-mapped file was read or run

## codex / new

Models: none recorded. Rule: right in at least 2 of 2 runs.

| Run | Right | Of | Unscored | Errors |
|---|---|---|---|---|
| r1 | 14 | 15 | 0 | 0 |
| r2 | 14 | 15 | 0 | 0 |

| # | Case | Expected | Routes per run | Right | Right under rule | Words before first action (median) | Frame ok | Forbidden | Build attempts |
|---|---|---|---|---|---|---|---|---|---|
| 1 | P01 | create | create, create | 2/2 | yes | 23481.0 | no, no | - | 0 |
| 2 | P02 | create | create, create | 2/2 | yes | 16878.5 | no, no | - | 0 |
| 3 | P03 | create | create, create | 2/2 | yes | 30114.5 | no, no | - | 0 |
| 4 | P04 | insert | insert, insert | 2/2 | yes | 13704.0 | yes, yes | - | 0 |
| 5 | P05 | cut | cut, cut | 2/2 | yes | 7456.5 | no, no | - | 0 |
| 6 | P06 | sound | sound, sound | 2/2 | yes | 12108.5 | no, no | - | 0 |
| 7 | P07 | quick | quick, quick | 2/2 | yes | 5040.5 | yes, yes | - | 0 |
| 8 | P08 | cut | cut, cut | 2/2 | yes | 25553.0 | no, no | - | 0 |
| 9 | P09 | editor | editor, editor | 2/2 | yes | 14655.0 | yes, yes | - | 0 |
| 10 | P10 | quick | quick, quick | 2/2 | yes | 9066.0 | yes, yes | - | 0 |
| 11 | H1v2 | create | create, create | 2/2 | yes | 16237.5 | no, no | - | 0 |
| 12 | H2v2 | create | create, create | 2/2 | yes | 32441.5 | no, no | - | 0 |
| 13 | H3v2 | create | cut, cut | 0/2 | no | 5931.0 | no, no | - | 0 |
| 14 | H4v2 | create | create, create | 2/2 | yes | 27564.5 | no, no | - | 0 |
| 15 | H5v2 | no-skill | no-skill, no-skill | 2/2 | yes | 0.0 | yes, yes | - | 0 |
| 16 | R16 | create | error, error | 0/2 | no | None |  | - | 0 |
| 17 | R17 | quick | quick, quick | 2/2 | yes | 5892.0 | yes, yes | - | 0 |
| 18 | R18 | quick | quick, quick | 2/2 | yes | 5435.5 | yes, yes | - | 0 |
| 19 | R19 | create | create, create | 2/2 | yes | 6665.5 | yes, yes | - | 0 |
| 20 | R20 | cut | editor, editor | 0/2 | no | 3161.5 | no, yes | - | 0 |

| Path | Prompts | Right under rule |
|---|---|---|
| create | H1v2, H2v2, H3v2, H4v2, P01, P02, P03 | H1v2, H2v2, H4v2, P01, P02, P03 |
| cut | P05, P08 | P05, P08 |
| insert | P04 | P04 |
| sound | P06 | P06 |
| editor | P09 | P09 |
| quick | P07, P10 | P07, P10 |

Prompts right under the rule: 14 of 15. Complete: True. Routing bar (13 of 15 and every path): True.
Words read before the first action: median 14806.5, range 0-40957, n 30. Forbidden hits: 0. Build or spend attempts: 0.

Route checks 16-20 (each required; passed per run):

- R16: error, error
- R17: failed, failed
- R18: passed, passed
- R19: passed, passed
- R20: passed, passed

Infrastructure errors:
- codex/new/R16/r1: RuntimeError: Tesseract is installed (%LOCALAPPDATA%\Tesseract\bin\tsrct.cmd); route check 16 needs an environment without it
- codex/new/R16/r2: RuntimeError: Tesseract is installed (%LOCALAPPDATA%\Tesseract\bin\tsrct.cmd); route check 16 needs an environment without it

Unscored sessions:
- none

