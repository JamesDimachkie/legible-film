// Seeded randomness. Never Math.random: every value is a pure function of its seed.

function mixBits(z) {
  z = Math.imul(z ^ (z >>> 16), 0x85ebca6b);
  z = Math.imul(z ^ (z >>> 13), 0xc2b2ae35);
  return (z ^ (z >>> 16)) >>> 0;
}

// A sequence generator: rng(seed)() returns floats in [0, 1).
export function rng(seed = 1) {
  let s = (typeof seed === 'string' ? hashString(seed) : seed) >>> 0;
  return () => {
    s = (s + 0x9e3779b9) >>> 0;
    return mixBits(s) / 4294967296;
  };
}

// A stateless hash of integers to [0, 1): the same inputs always give the same value.
export function hash(...ints) {
  let h = 0x2545f491;
  for (const v of ints) h = mixBits((h ^ (Math.floor(v) | 0)) + 0x9e3779b9);
  return h / 4294967296;
}

export function hashString(str) {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 0x01000193) >>> 0;
  return mixBits(h);
}

// Smooth 1-D value noise in [-1, 1], seeded: frame-exact grain or drift.
export function noise1(x, seed = 0) {
  const i = Math.floor(x), f = x - i;
  const u = f * f * (3 - 2 * f);
  const a = hash(i, seed) * 2 - 1, b = hash(i + 1, seed) * 2 - 1;
  return a + (b - a) * u;
}
