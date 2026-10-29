// The kit a film spec receives: every block, and a clock helper for beat arithmetic.
//   export default function film(kit) { const { Words, clock } = kit; const T = clock({ bpm: 150 }); ... }

import { Words } from './words.js';
import { Terminal } from './terminal.js';
import { Number_ } from './number.js';
import { Name } from './name.js';
import { Picture } from './picture.js';
import { Chain } from './chain.js';
import { Without } from './without.js';
import { EndCard } from './endcard.js';
import { Caption } from './caption.js';
import { Dither } from './dither.js';
import { block } from './common.js';

export function clock({ bpm, offset = 0 }) {
  const spb = 60 / bpm;
  return {
    bpm, offset, spb,
    b: n => n * spb,                 // a duration of n beats, in seconds
    at: n => offset + n * spb,       // the film time of beat n
    bar: (n, beatsPerBar = 4) => offset + n * beatsPerBar * spb,
  };
}

// `block` lets a film define its own device with the same contract (see BLOCKS.md).
export const kit = { Words, Terminal, Number: Number_, Name, Picture, Chain, Without, EndCard, Caption, Dither, clock, block };
