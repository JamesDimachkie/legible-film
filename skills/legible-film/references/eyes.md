# Eyes: double-blind relative lineups

Blind evaluation of motion, pacing, visual clutter, and callout placement without relying on the maker's own eye or
isolated single-file scoring. Readers find faults; only the person watching at normal speed with sound decides if the
film works.

## 1. Why relative lineups beat single-file inspection

- A standalone rubric check misses how a cut compares against strong references.
- Showing four lettered cuts (`A..D`) standardized for resolution, aspect ratio, and frame rate under a neutral random
  folder (`pack.py`) prevents identity leakage and forces concrete visual comparisons.
- Keep `pack-N-KEY.txt` / `pack-N-key.json` outside the pack directory; give readers only the blinded `lineup/` or
  `alone/` path. With a lineup, `alone/` sits in a neutral folder of its own (`--alone-reads`, by default `READS-alone`
  beside the readers' root), never under the root that holds `lineup/`: its sheets of ours would show which letter is
  ours. Never include metric targets or thresholds in reader briefs.

## 2. Three readers per round

1. **Two cross-family lineup readers** (`lineup/A..D`): two different model families read `story-01.jpg` (2 fps overview)
   and `move-1..K.jpg` (every native frame of the `K=5` busiest 1-second windows). Each ranks the line-up overall,
   gives every film a craft tier (`beginner | hobbyist | freelance | studio`), scores it from 1 to 10 on **pacing**,
   **visual_clutter** and **callout_placement**, and names its strongest and weakest moments. The brief `pack.py`
   writes asks for this JSON object, `pack.py record --help` prints it, and `pack.py record` reads it, from a UTF-8
   file (a byte-order mark is fine), and nothing else (a prose or Markdown reading, or a file in another encoding, is
   refused as incomplete, saying what to ask the reader for):

```text
Answer with one JSON object and nothing else (it may sit in one fenced code block). This example is for a
line-up of two films, A and B; yours has an entry for every letter in your line-up:

{
  "model_family": "anthropic",
  "overall_ranking": ["B", "A"],
  "films": {
    "A": {"tier": "hobbyist", "pacing": 6, "visual_clutter": 7, "callout_placement": 5,
          "strongest": "the title lands on the beat", "weakest": "the callout covers the chart",
          "tells": "every move eases the same way"},
    "B": {"tier": "studio", "pacing": 9, "visual_clutter": 8, "callout_placement": 9,
          "strongest": "each cut lands on a change", "weakest": "the end card holds too long",
          "tells": "type sits on one baseline grid"}
  },
  "steals": ["hold the last frame for a beat before the cut"]
}

- model_family: your model's vendor: anthropic, openai, google, meta, mistral or xai.
- overall_ranking: every line-up letter once, best crafted first.
- films: one object per line-up letter. tier is one of beginner, hobbyist, freelance or studio. pacing,
  visual_clutter (10 is cleanest) and callout_placement are numbers from 1 to 10.
- strongest, weakest and tells (text, in each film) and steals (a list of concrete craft choices worth keeping)
  are for the people who read the results: pack.py record does not check them, and any of them may be left out.
```

2. **One fault-finder** (`alone/`): reads `story-01.jpg`, `move-1..10.jpg` (every frame of the 10 busiest 1-second
   windows), and `key-1..5.png` (full-size rest keys) to catch broken text, overlaps, dead holds, seam flashes, and
   missing cause-and-effect steps.

## 3. Commands and stop criteria

```text
python pack.py cuts/v001/preview.mp4 --against refs/V01.mp4 --against refs/V02.mp4 --out cuts/v001/qa
python pack.py record cuts/v001/qa/pack-1-key.json --lineup-a r_claude.json --lineup-b r_gemini.json --family-a anthropic --family-b google --fault-finder r_ff.txt --out cuts/v001/qa/blind-pack.json
python check.py PROJECT --blind-pack cuts/v001/qa/blind-pack.json
```

`pack.py record` marks `blind-pack.json` as **`look`** (and `check.py --blind-pack` checks the recorded readings again
itself, whatever status the report holds) when:
- the line-up letters repeat, or either reading is not the JSON object above, complete for every letter of the
  line-up (every letter ranked once, a tier from the four, and the three scores as numbers from 1 to 10): `pack.py
  record` names what is wrong and what to ask the reader for;
- the two lineup readers are not from two distinct known vendors (`anthropic | openai | google | meta | mistral | xai`;
  an unknown model name has no vendor until `--family-a` or `--family-b` names one);
- **both** lineup readers classify ours as `beginner` or `hobbyist`; or
- **both** lineup readers put ours below the yardstick cut (`--against 1` or `--yardstick`), either in overall rank or
  on any dimension score.

`deal()` ensures `ours` never keeps the same lineup letter in consecutive packs in the same key folder.
