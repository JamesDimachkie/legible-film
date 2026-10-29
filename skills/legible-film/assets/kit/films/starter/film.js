// Starter film: about 12 s, showing the shape of a spec. Replace the product, the facts and the words.
//
// A spec is a function of the kit that returns plain data. Every block is a device with one job;
// scenes play in order. Times are seconds; T.b(n) is n beats, and strings like '2b' also work.
// Run:  python scripts/film_check.py <this folder>   (truth, contrast, reading, flashing, lint, exports)
// Look: open index.html on a local server (python -m http.server), keys: space, , . arrows 0-9 S R L.

export default function film(kit) {
  const { Type, Number, EndCard, Caption, clock } = kit;
  const T = clock({ bpm: 120, offset: 0 });          // 120 BPM at 60 fps: 30 frames per beat

  return {
    title: 'Northwind (starter)',
    size: [1920, 1080],                               // ?w=1080&h=1920 renders the same timeline tall
    fps: 60,
    beat: { bpm: T.bpm, offset: T.offset },
    brand: '#2F9E6B',                                 // one brand colour: the palette is built from it
    facts: 'facts.json',                              // every claim must match a fact's display exactly
    texture: { kind: 'dots' },                        // a sparse world texture, so camera moves read
    pace: { max_still: 0.6, max_still_share: 0.4 },      // your film's own pace contract (QC reads it)

    scenes: [
      // Kinetic words: one idea per beat. A shot lands on its time; hits: none, bump, shake, burst.
      Type({
        exit: 'shrink',                             // shrink into a point; the next scene grows from it
        shots: [
          { text: 'NOTES.', kicker: 'ALL YOUR', style: 'kicker', open: true, dur: '3b', ground: 'ink', fact: 'what' },   // open: frame 0 reads as a cover
          { text: 'EVERY/DEVICE.', style: 'snap', dur: '3b', ground: 'paper', fact: 'what' },
        ],
      }),
      // A number lands from a fact (never typed here, never rolled through unmeasured values).
      Number({ fact: 'platforms', label: 'PLATFORMS', qualifier: true, ground: 'ink', land: 'digits', hold: '4b' }),
      // A claim. role 'claim' + fact id: the preflight checks the words against facts.json.
      Type({
        enter: 'whip-h', exit: 'dive', dive: { letter: 'O' },
        shots: [{ text: 'WORKS/OFFLINE.', dur: '5b', ground: 'accent', role: 'claim', fact: 'offline', id: 'claim-offline', hit: 'burst', drop: true }],
      }),
      // The end card: held readable, declared as a rest; the music stops on the sting.
      EndCard({ wordmark: 'northwind', typed: false, wordmarkFact: 'product', tagline: 'AVAILABLE NOW', taglineFact: 'release', line: 'northwind.example', lineFact: 'url', ground: 'paper', len: '7b' }),
    ],

    // Captions: one running line carrying the sentence while the display words cut (SRT and WebVTT
    // are exported from this same source by film_check.py).
    captions: Caption({ sentences: [{ text: 'All your notes, on every device.', t0: 0.05, t1: T.at(6) - 0.05 }] }),
  };
}
