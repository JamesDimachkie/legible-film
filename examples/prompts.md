# Example requests

Adapt these to your project. Point the agent at your brief, your facts and the assets you have the right to use.

## With a command

Start with `/legible-film` (`$legible-film` in Codex) and a command, then say what it applies to. The longer requests
below work the same with or without one.

```
/legible-film setup
/legible-film quick trim the first 3 seconds off clip.mp4 and make a 9:16 version for Reels
/legible-film map interview.mp4 as the interview and everything in broll/ as b-roll
/legible-film plan a 60-second story from the interview: who it is for and the line it opens on
/legible-film cut a 60-second story from interview.mp4 and the b-roll in broll/
/legible-film check the current version
/legible-film screen v3 so I can watch it and leave notes
/legible-film revise: my notes are in the room; keep everything else exactly as it is
/legible-film grade final.mp4 for YouTube: hook, pacing, picture and sound
/legible-film captions final.mp4: an SRT and a burned-in version clear of the platform buttons
/legible-film shorts three 30-second clips from podcast.mp4 for Reels, each standing on its own
/legible-film premiere here are the editor's last two XML exports and the earlier captions; which are now stale?
/legible-film handoff v003 to Premiere: the original clips with handles, and the captions
/legible-film tighten interview.mp4: take out the dead air and keep every word
/legible-film insert an animation in place of int_01 from 1:12 to 1:20, timed to the words
/legible-film graphics a lower third for the speaker in Cavalry, over their first line
/legible-film spatial pin logo.png to the laptop screen in broll_02 and blur the number plate in broll_05
/legible-film taste show my confirmed preferences, and propose new ones from my notes on this film
/legible-film score the approved picture: sparse, warm, with a hit on the logo at 0:14
/legible-film mix voiceover.wav over bed.wav for the landing page; keep the voice clear throughout
/legible-film kit a 20-second teaser for the 2.0 launch, with a draft soundtrack
/legible-film studio film our launch, budget $800 for music, voice and stock
/legible-film deliver the approved master for X, Instagram Reels and YouTube
```

Older names still work: `brief` and `film` start `plan`, `review` opens the Screening Room, `cutdown` makes
`shorts`, and `teaser` starts the `kit`.

## A new film

> Make a 30-second launch film for [product], 1920x1080 at 60 fps for an X post, plus a 1080x1920 version for
> stories. It autoplays muted in the feed, so the story must read without sound; sound is for people who unmute.
> Facts and figures are in `docs/facts.md`; use nothing else as a claim. The brand is on [site]: take colours, logo
> and fonts from the live site. Ask before any paid generation; the budget cap is [amount]. Show me the treatment
> and a short motion study before building the whole film.

## A product demo from real interface code

> Build a 20-second silent demo of [feature] from the product's own components in `web/`. Use invented data and
> label the interface as a reconstruction. Show the trigger, the response and the result, and make the counts agree
> in every frame. Deliver an MP4 and a WebM loop for the landing page, with frame 0 as the poster.

## Checking a cut before it ships

> Here is `deliver/film-v6.mp4`. Run the full QC on it against this spec: 1920x1080, 60 fps, 45 s, H.264 yuv420p,
> BT.709, AAC 48 kHz. The designed cuts are at 12.0 and 28.5, and 31-33 s is a deliberate hold. Tell me what you
> checked, what you could not check, and the weakest point.

## An interview cut you can follow

> Cut a 60-second story from `interview.mp4` with b-roll from `broll/`, 9:16 for Reels with burned captions. Show me
> the paper edit before you render, then open the Screening Room so I can watch it muted and with sound and leave
> notes on the moments that need work. Cut only in pauses, and tell me where a join removed words.

## Following an editor's Premiere cut

> Our editor works in Premiere. Here are their Final Cut Pro XML exports of revisions 1 and 2, the revision 1
> captions, and the source media (or word-timed transcripts of it). Tell me which captions moved, which carry words
> cut from the new edit, which were removed, and anything in the timeline you could not read. Treat those as
> candidates, and check them against the exported audio before saying what is actually said. Don't change their cut.

## A targeted revision

> The client says the ending feels rushed. Fix the ending in a new version and keep the rest of approved v5 as it is.
> Compare the new version with v5, tell me everything that changed, and show me the ending before and after.

## Sound

> Give me three treatments for the reveal at 18 s: a hard contact, a musical swell, and silence before the hit.
> Same picture, matched loudness. I'll choose by listening.

## Tools

> I have twelve screen recordings and a voiceover script. What tools should I use to make a two-minute tutorial with
> captions, and how would you check the captions against the audio?
