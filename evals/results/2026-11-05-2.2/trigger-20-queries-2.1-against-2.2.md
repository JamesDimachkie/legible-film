# Trigger summary

Models: claude-opus-5-5

| Variant | Should trigger loaded | Should not trigger loaded |
|---|---|---|
| old | 26/30 | 0/30 |
| new | 27/30 | 0/30 |

Trigger pass: True

| Query | old | new |
|---|---|---|
| should_not_trigger/00 transcribe this podcast episode for me | 0 | 0 |
| should_not_trigger/01 download this youtube video as an mp4 | 0 | 0 |
| should_not_trigger/02 write a blog post announcing our product launch | 0 | 0 |
| should_not_trigger/03 design a logo for my startup | 0 | 0 |
| should_not_trigger/04 compress this png so it loads faster | 0 | 0 |
| should_not_trigger/05 fix the failing test in my react component | 0 | 0 |
| should_not_trigger/06 summarise the main points from this meeting recording | 0 | 0 |
| should_not_trigger/07 convert this wav file to mp3 | 0 | 0 |
| should_not_trigger/08 what is the resolution of this video file | 0 | 0 |
| should_not_trigger/09 write a script for a podcast intro | 0 | 0 |
| should_trigger/00 make a 30 second launch video for my app's new feature | 3 | 3 |
| should_trigger/01 can you check this mp4 before I upload it to youtube | 3 | 3 |
| should_trigger/02 my exported video looks washed out in safari but fine in chrome, why | 3 | 3 |
| should_trigger/03 add background music and a few sound effects to this demo video | 3 | 3 |
| should_trigger/04 there's a weird single frame flash in my hyperframes render around 12 seconds | 3 | 3 |
| should_trigger/05 turn these four screenshots into a 20 second product teaser | 3 | 3 |
| should_trigger/06 the audio in my reel clips after instagram compresses it | 2 | 3 |
| should_trigger/07 make a seamless looping hero animation for our landing page | 3 | 3 |
| should_trigger/08 the client wants the ending slower but everything else stays exactly as approved | 3 | 3 |
| should_trigger/09 what frame rate should I export a gif at so it plays at the right speed | 0 | 0 |

