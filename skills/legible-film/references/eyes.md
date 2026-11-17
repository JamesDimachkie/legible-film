# Eyes: double-blind relative lineups

Blind evaluation of motion, pacing, visual clutter, and callout placement without relying on the maker's own eye or
isolated single-file scoring. Readers find faults; only the person watching at normal speed with sound decides if the
film works.

## 1. Why relative lineups beat single-file inspection

- A standalone rubric check misses how a cut compares against strong references.
- Showing four lettered cuts (`A..D`) standardized for resolution, aspect ratio, and frame rate under a neutral random
  folder (`pack.py`) prevents identity leakage and forces concrete visual comparisons.
- Keep `pack-N-KEY.txt` / `pack-N-key.json` outside the pack directory; give readers only the blinded `lineup/` or
  `alone/` path. Never include metric targets or thresholds in reader briefs.

## 2. Three readers per round

1. **Two cross-family lineup readers** (`lineup/A..D`): two different model families read `story-01.jpg` (2 fps overview)
   and `move-1..K.jpg` (every native frame of the `K=5` busiest 1-second windows). Each ranks the lineup overall and
   on **pacing**, **visual_clutter**, and **callout_placement**, assigns a craft tier
   (`beginner | hobbyist | freelance | studio`), and cites exact sheets and frames.
2. **One fault-finder** (`alone/`): reads `story-01.jpg`, `move-1..10.jpg` (every frame of the 10 busiest 1-second
   windows), and `key-1..5.png` (full-size rest keys) to catch broken text, overlaps, dead holds, seam flashes, and
   missing cause-and-effect steps.

## 3. Commands and stop criteria

```text
python pack.py cuts/v001/preview.mp4 --against refs/V01.mp4 --against refs/V02.mp4 --out cuts/v001/qa
python pack.py record cuts/v001/qa/pack-1-key.json --lineup-a r_claude.json --lineup-b r_gemini.json --fault-finder r_ff.txt --out cuts/v001/qa/blind-pack.json
python check.py PROJECT --blind-pack cuts/v001/qa/blind-pack.json
```

`pack.py record` marks `blind-pack.json` as **`look`** (and `check.py` surfaces `blind_pack`) when:
- the two lineup readers are from the same model family (`cross_family: false`);
- **both** lineup readers classify ours as `beginner` or `hobbyist`; or
- **both** lineup readers rank ours below the yardstick cut (`--against 1` or `--yardstick`).

`deal()` ensures `ours` never keeps the same lineup letter in consecutive packs in the same key folder.
