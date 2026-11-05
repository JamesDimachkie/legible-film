# Triggering: 2.0.0 against candidate 5cac88c (clean run)

The clean triggering run: both arms in the same run, Claude sessions without the user's CLAUDE.md, rules or auto memory (trigger_run.py ff58cd5). Candidate 5cac88c against 2.0.0.

Claude Code (`claude -p`, project settings only, read-only tools, three turns, stopped at the load), 3 reps per query per arm, model claude-opus-5-5, 0 timeouts. "Loaded" is a Skill call for legible-film or a Read of its SKILL.md. No worse: at least as many loads on a should-trigger query, no more on a should-not query. Sources (u0-work, not committed): 20/old `trigger20-clean`; 20/new `trigger20-clean`; opus8/old `trigger8-clean`; opus8/new `trigger8-clean`.

| Set | Kind | # | Query | 2.0.0 | Candidate | No worse |
|---|---|---|---|---|---|---|
| 20 | should trigger | 0 | make a 30 second launch video for my app's new feature | 3/3 | 3/3 | yes |
| 20 | should trigger | 1 | can you check this mp4 before I upload it to youtube | 3/3 | 3/3 | yes |
| 20 | should trigger | 2 | my exported video looks washed out in safari but fine in chrome, why | 3/3 | 3/3 | yes |
| 20 | should trigger | 3 | add background music and a few sound effects to this demo video | 3/3 | 3/3 | yes |
| 20 | should trigger | 4 | there's a weird single frame flash in my hyperframes render around 12 seconds | 3/3 | 3/3 | yes |
| 20 | should trigger | 5 | turn these four screenshots into a 20 second product teaser | 3/3 | 3/3 | yes |
| 20 | should trigger | 6 | the audio in my reel clips after instagram compresses it | 3/3 | 3/3 | yes |
| 20 | should trigger | 7 | make a seamless looping hero animation for our landing page | 3/3 | 3/3 | yes |
| 20 | should trigger | 8 | the client wants the ending slower but everything else stays exactly as approved | 3/3 | 3/3 | yes |
| 20 | should trigger | 9 | what frame rate should I export a gif at so it plays at the right speed | 0/3 | 0/3 | yes |
| 20 | should not trigger | 0 | transcribe this podcast episode for me | 0/3 | 0/3 | yes |
| 20 | should not trigger | 1 | download this youtube video as an mp4 | 0/3 | 0/3 | yes |
| 20 | should not trigger | 2 | write a blog post announcing our product launch | 0/3 | 0/3 | yes |
| 20 | should not trigger | 3 | design a logo for my startup | 0/3 | 0/3 | yes |
| 20 | should not trigger | 4 | compress this png so it loads faster | 0/3 | 0/3 | yes |
| 20 | should not trigger | 5 | fix the failing test in my react component | 0/3 | 0/3 | yes |
| 20 | should not trigger | 6 | summarise the main points from this meeting recording | 0/3 | 0/3 | yes |
| 20 | should not trigger | 7 | convert this wav file to mp3 | 0/3 | 0/3 | yes |
| 20 | should not trigger | 8 | what is the resolution of this video file | 0/3 | 0/3 | yes |
| 20 | should not trigger | 9 | write a script for a podcast intro | 0/3 | 0/3 | yes |
| opus8 | should trigger | 0 | sound design for this silent clip | 3/3 | 3/3 | yes |
| opus8 | should trigger | 1 | animate our logo reveal | 3/3 | 3/3 | yes |
| opus8 | should trigger | 2 | a 15 s square launch post | 3/3 | 3/3 | yes |
| opus8 | should trigger | 3 | make the drop land on the reveal | 3/3 | 3/3 | yes |
| opus8 | should not trigger | 0 | generate an image for my landing page | 0/3 | 0/3 | yes |
| opus8 | should not trigger | 1 | write lyrics for a jingle | 0/3 | 0/3 | yes |
| opus8 | should not trigger | 2 | make a slide deck | 0/3 | 0/3 | yes |
| opus8 | should not trigger | 3 | edit this photo | 0/3 | 0/3 | yes |

| Scope | Should trigger: 2.0.0 | Candidate | Should not: 2.0.0 | Candidate | No worse | Queries worse |
|---|---|---|---|---|---|---|
| 20 | 27/30 | 27/30 | 0/30 | 0/30 | yes | none |
| opus8 | 12/12 | 12/12 | 0/12 | 0/12 | yes | none |
| combined | 39/42 | 39/42 | 0/42 | 0/42 | yes | none |
