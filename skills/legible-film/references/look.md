# Look: the person's references and expectations

A film made to someone's taste starts from what they already like. References carry light, colour, pace, framing
and sound better than any description, so ask for them first, and when there are none, help the person say what they
expect. The result is the project's `look.md` (template in [look.md](../assets/templates/look.md)), which every
stage reads. It belongs to this film: for this film it outranks the person's general confirmed preferences
([taste](taste.md)) without changing them, and the person's notes in the Screening Room outrank it.

Run it when the request leaves the look open: a designed film (kit, insert, studio), titles, music or a grade over a
cut, or whenever the person asks. Skip it for a quick edit, an editor's own timeline, a repair, or a cutdown of a film
whose look is already approved; ask only what the job depends on.

## 1. One message, every question

Ask every open question in one message, numbered, each with the default you will use, so the person can answer by
number or reply "defaults". Skip what the request, the attachments or the brief already answer; when a brief is
needed, its questions go in the same message. Keep the person's words. A default is never a yes to spending,
uploading or publishing: those still wait for the person.

| # | Question | Default when unanswered |
|---|---|---|
| 1 | What is it for and where will it play? | Read from the request and the sources |
| 2 | Any references? Films, ads, channels, creators, a frame, a website or product: attach files or send links | None: section 2 |
| 3 | For each: what should we take from it, and what should we leave? | Its pace and feel; not its content |
| 4 | The feeling in three words | Taken from the references |
| 5 | Anything it must include, or must never have? | The defaults under Avoid in look.md |

Do not ask about pace, finish or sound in editing words the person may not use: show two short options that differ in
that one thing and let them pick. With references, do not ask them to describe the look in words as well: a few
strong references and a short request beat a long description.

Then `look.py init PROJECT`, `look.py add PROJECT FILE ... --take ... --leave ... --mode own|close` for files (with
`--range 0:12-0:20` for the part of a video that matters, which `compare` then samples, and `--note` for where it came
from and who made it) and `look.py add PROJECT --link URL` for links, which are not downloaded. Write their answers into look.md in their words, and delete every line that does not apply: a stray line
steers every later stage.

## 2. No references yet

Most people have none ready. Offer three directions and recommend one. Each direction is a sentence, two or three
public examples the person can open (a link, with the time that matters), and what to take from each. For a designed
film, also make a style frame of each direction with the kit or the engine in use; paid image or video generation
waits for the person's yes and cap ([generation](generation.md)). Do not download public videos to make examples.

Or ask the questions under Expectations in look.md: what it is for, who it is for, the feeling in three words, what
they have liked anywhere, what they never want.

The direction or style frame the person picks becomes the first reference, recorded under Decisions. A still settles
light, colour, framing and type, not pace or sound: when those matter, show a short motion or sound sample before the
whole film. Write "no references" in look.md when they choose to go without; the first look they approve is then the
reference for later rounds.

## 3. Study them

- Look at every image reference at full size, and draw the set with `look.py board PROJECT` to see it whole.
- Study a video reference over its range, frame by frame: `frame_sheet.py refs/V01.mp4 --every 0.25 --out
  refs/V01-rhythm.png` for its rhythm, `--around T --span 1.2 --rate 30` at each cut or transition, `motion_scan.py`
  for its pace in numbers. List what it does under Study in look.md, apart from the person's own words: timecode,
  what moves, how (duration, easing, direction), why it works.
- Take from several references and never copy one: "recreate closely" means its qualities (light, colour, pace,
  framing, type), never its shots, text, logos, characters or music. References are for study: they are not cut into
  the film (`map.py` refuses a reference and any copy of one), delivered, uploaded or named in anything published.
- For a product film, the product's real screens, logo files and photos beat drawn stand-ins; for sound, a licensed
  library take usually beats a synthesised effect ([sound](sound.md)).

## 4. Use them

- **Plan:** the paper edit's pace, length, structure and music follow look.md; say which reference a choice comes
  from when it is not obvious, and which approved look a render follows.
- **Designed pictures:** before a long render, render the hard moments as stills at the delivered size and put each
  beside its reference (`look.py compare PROJECT R01 --image still.png`, or `--at SECONDS` on the current preview),
  and get the person's yes on the stills first.
- **Review:** the independent reviewer writes its first impression unaided, then reads look.md and the side-by-sides.
  `look.py compare` measures colour per region (labelled measured: under "own style" the composition differs, so read
  it as a colour check only); whether the film sits beside its references is judged, and labelled judged. Give the
  reviewer a reference and a still unlabelled (`look.py compare ... --blind`; keep its key file back) and ask which is
  the film and why: a confident right answer names the next thing to fix. Ask it to rate one reference on the same
  scale without being told which it is: a reviewer who rates the film above its reference while the person says it
  is worse is being generous, and its scores are read that way. References sent to a reviewer on another service
  leave the machine, so that needs the person's yes.
- **The bar:** look.md names what the finished film should sit beside. The person's own judgement of a version, in
  their words, outranks every model's score, yours included; record it with their reasons under The bar.
- **Avoid:** check every version against the person's bans and the default list; an item stays out unless it was
  chosen for this film.

When a note changes the look, update look.md and say so.
