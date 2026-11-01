# Trigger and routing summary

Models: claude-opus-5-5

| Variant | Should trigger loaded | Should not trigger loaded |
|---|---|---|
| old | 17/20 | 2/20 |
| new | 16/20 | 0/20 |
| new2 | 18/20 | 0/20 |

Trigger pass: True

| Query | old | new | new2 |
|---|---|---|---|
| should_not_trigger/00 transcribe this podcast episode for me | 2 | 0 | 0 |
| should_not_trigger/01 download this youtube video as an mp4 | 0 | 0 | 0 |
| should_not_trigger/02 write a blog post announcing our product launch | 0 | 0 | 0 |
| should_not_trigger/03 design a logo for my startup | 0 | 0 | 0 |
| should_not_trigger/04 compress this png so it loads faster | 0 | 0 | 0 |
| should_not_trigger/05 fix the failing test in my react component | 0 | 0 | 0 |
| should_not_trigger/06 summarise the main points from this meeting recording | 0 | 0 | 0 |
| should_not_trigger/07 convert this wav file to mp3 | 0 | 0 | 0 |
| should_not_trigger/08 what is the resolution of this video file | 0 | 0 | 0 |
| should_not_trigger/09 write a script for a podcast intro | 0 | 0 | 0 |
| should_trigger/00 make a 30 second launch video for my app's new feature | 2 | 2 | 2 |
| should_trigger/01 can you check this mp4 before I upload it to youtube | 2 | 2 | 2 |
| should_trigger/02 my exported video looks washed out in safari but fine in chrome, why | 1 | 0 | 2 |
| should_trigger/03 add background music and a few sound effects to this demo video | 2 | 2 | 2 |
| should_trigger/04 there's a weird single frame flash in my hyperframes render around 12 seconds | 2 | 2 | 2 |
| should_trigger/05 turn these four screenshots into a 20 second product teaser | 2 | 2 | 2 |
| should_trigger/06 the audio in my reel clips after instagram compresses it | 2 | 2 | 2 |
| should_trigger/07 make a seamless looping hero animation for our landing page | 2 | 2 | 2 |
| should_trigger/08 the client wants the ending slower but everything else stays exactly as approved | 2 | 2 | 2 |
| should_trigger/09 what frame rate should I export a gif at so it plays at the right speed | 0 | 0 | 0 |

| Variant | Case | Rep | First expected command | Forbidden named | References named | Ref ok |
|---|---|---|---|---|---|---|
| old | quick-916 | 1 | ffprobe |  | ffmpeg-cookbook.md, finishing.md, footage.md, recipes.md | True |
| old | quick-916 | 2 | ffprobe |  | ffmpeg-cookbook.md, footage.md, recipes.md | True |
| old | check-youtube | 1 | setup.py |  | formats.md, qc.md | True |
| old | check-youtube | 2 | setup.py |  | formats.md, qc.md | True |
| old | interview-story | 1 | setup.py |  | film.md, finding-the-story.md, paper-edit.md, project.md, recipes.md, transcript.md | True |
| old | interview-story | 2 | setup.py |  | film.md, finding-the-story.md, paper-edit.md, project.md, recipes.md, transcript.md | True |
| old | premiere-stale | 1 | setup.py |  | footage.md, qc.md, recipes.md | True |
| old | premiere-stale | 2 | setup.py |  | footage.md, qc.md, recipes.md | True |
| new2 | quick-916 | 1 | ffmpeg |  | gotchas.md, recipes.md | True |
| new2 | quick-916 | 2 | ffmpeg |  | ffmpeg-cookbook.md, gotchas.md, recipes.md | True |
| new2 | interview-story | 1 | setup.py |  | finding-the-story.md, footage.md, loop.md, paper-edit.md, project.md | True |
| new2 | interview-story | 2 | setup.py |  | finding-the-story.md, loop.md, paper-edit.md, project.md | True |
| new2 | check-youtube | 1 | setup.py |  | gotchas.md, qc.md | True |
| new2 | check-youtube | 2 | setup.py |  | gotchas.md, qc.md | True |
| new2 | premiere-stale | 1 | setup.py |  | footage.md, recipes.md, review.md | True |
| new2 | premiere-stale | 2 | setup.py |  | gotchas.md, recipes.md | True |
| new3 | check-youtube | 1 | setup.py |  | formats.md, gotchas.md, qc.md | True |
| new3 | check-youtube | 2 | setup.py |  | formats.md, gotchas.md, qc.md | True |
| new3 | interview-story | 1 | setup.py |  | finding-the-story.md, formats.md, loop.md, paper-edit.md, project.md | True |
| new3 | interview-story | 2 | setup.py |  | finding-the-story.md, formats.md, loop.md, paper-edit.md, project.md | True |
| new3 | quick-916 | 1 | ffmpeg |  | formats.md, gotchas.md, recipes.md | True |
| new3 | quick-916 | 2 | ffmpeg |  | formats.md, gotchas.md, recipes.md | True |
| new3 | premiere-stale | 1 | setup.py |  | gotchas.md, recipes.md, scripts.md | True |
| new3 | premiere-stale | 2 | setup.py |  | gotchas.md, recipes.md, scripts.md | True |
