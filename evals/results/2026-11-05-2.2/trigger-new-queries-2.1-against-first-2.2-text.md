# Trigger summary

Models: claude-opus-5-5

| Variant | Should trigger loaded | Should not trigger loaded |
|---|---|---|
| old | 13/18 | 0/12 |
| new | 18/18 | 0/12 |

Trigger pass: True

| Query | old | new |
|---|---|---|
| should_not_trigger/00 write show notes for my podcast episode | 0 | 0 |
| should_not_trigger/01 what is a good mic for recording interviews | 0 | 0 |
| should_not_trigger/02 translate this srt file into French | 0 | 0 |
| should_not_trigger/03 give me a list of questions for my next podcast guest | 0 | 0 |
| should_trigger/00 add subtitles to this video | 1 | 3 |
| should_trigger/01 burn captions into my reel | 3 | 3 |
| should_trigger/02 cut our podcast episode down to the best 20 minutes | 0 | 3 |
| should_trigger/03 edit this interview into a two minute story | 3 | 3 |
| should_trigger/04 make three vertical shorts from this long video | 3 | 3 |
| should_trigger/05 remove the long pauses from my screen recording | 3 | 3 |

