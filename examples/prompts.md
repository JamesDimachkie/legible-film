# Example requests

Adapt these to your project. Point the agent at your brief, your facts and the assets you have the right to use.

## With a command

Start with `/legible-film` (`$legible-film` in Codex) and a command, then say what it applies to. The longer requests
below work the same with or without one.

```
/legible-film brief a 45-second explainer for the new billing page; the facts are in docs/billing.md
/legible-film setup for a type-led launch film and a captioned interview cut
/legible-film film a 30-second launch film for 2.0, 16:9 for the post and 9:16 for stories
/legible-film kit a 20-second teaser for the 2.0 launch, with a draft soundtrack
/legible-film teaser four words on the beat of track.wav for the conference opener
/legible-film short a 3-second logo sting that loops cleanly for the site header
/legible-film studio film our launch, budget $800 for music, voice and stock
/legible-film cut a 60-second story from interview.mp4 and the b-roll in broll/
/legible-film cutdown the approved cut to 9:16 and 15 seconds for Reels
/legible-film captions final.mp4: an SRT and a burned-in version clear of the platform buttons
/legible-film score the approved picture: sparse, warm, with a hit on the logo at 0:14
/legible-film mix voiceover.wav over bed.wav for the landing page; keep the voice clear throughout
/legible-film check final.mp4 before I post it
/legible-film review the v3 cut with the team; here are their notes
/legible-film revise: the client says the ending feels rushed; keep everything they approved
/legible-film deliver the approved master for X, Instagram Reels and YouTube
```

## A new film

> Make a 30-second launch film for [product], 1920x1080 at 60 fps for an X post, plus a 1080x1920 version for
> stories. It autoplays muted in the feed, so the story must read without sound; sound is for people who unmute.
> Facts and figures are in `docs/facts.md`; use nothing else as a claim. The brand is on [site]: take colours, logo
> and fonts from the live site. Ask before any paid generation; the budget cap is [amount]. Show me the treatment and a short
> motion study before building the whole film.

## A product demo from real interface code

> Build a 20-second silent demo of [feature] from the product's own components in `web/`. Use invented data and
> label the interface as a reconstruction. Show the trigger, the response and the result, and make the counts agree
> in every frame. Deliver an MP4 and a WebM loop for the landing page, with frame 0 as the poster.

## Checking a cut before it ships

> Here is `deliver/film-v6.mp4`. Run the full QC on it against this spec: 1920x1080, 60 fps, 45 s, H.264 yuv420p,
> BT.709, AAC 48 kHz. The designed cuts are at 12.0 and 28.5, and 31-33 s is a deliberate hold. Tell me what you
> checked, what you could not check, and the weakest point.

## A targeted revision

> The client says the ending feels rushed. Fix that, and keep everything they approved in v5 exactly as it is.
> Prove what changed against v5, and show me a before and after of the ending.

## Sound

> Give me three treatments for the reveal at 18 s: a hard contact, a musical swell, and silence before the hit.
> Same picture, matched loudness. I'll choose by listening.

## Tools

> I have twelve screen recordings and a voiceover script. What tools should I use to make a two-minute tutorial with
> captions, and how would you check the captions against the audio?
