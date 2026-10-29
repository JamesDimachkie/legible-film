// Names from Legible Film 1.2.0, still accepted so films written against it run unchanged. Each old
// block option, style, hit, join and sound-role name is rewritten to its current name before a block
// builds; nothing else depends on the old names.

const STYLE = { slam: 'land', stack: 'kicker', pair: 'meet', cut: 'snap' };
const HIT = { beat: 'bump', hit: 'shake', punch: 'burst' };
const JOIN = { whipX: 'whip-h', whipY: 'whip-v', through: 'dive', collapse: 'shrink' };
const ROLE = { impact_big: 'boom', whoosh_big: 'sweep', logo_hit: 'sting', hit: 'tap' };
const KEYS = { through: 'dive', throughD: 'diveD', throughLetter: 'diveLetter', logoGain: 'stingGain', charge: 'converge' };
const VALUES = {
  style: STYLE, land: STYLE, lineEntrance: STYLE,
  hit: HIT, lineHit: HIT, fillHit: HIT, openHit: HIT,
  enter: JOIN, exit: JOIN,
  cue: ROLE, fillCue: ROLE,
};

const plain = x => x && typeof x === 'object' && (Array.isArray(x) || Object.getPrototypeOf(x) === Object.prototype);

// Rewrite a block's options in place (shots, words, outputs and other nested lists included).
export function legacyOpts(o, depth = 0) {
  if (!plain(o) || depth > 6) return o;
  if (Array.isArray(o)) { o.forEach(x => legacyOpts(x, depth + 1)); return o; }
  for (const [old, now] of Object.entries(KEYS)) {
    if (old in o && !(now in o) && (old !== 'through' || plain(o[old]))) { o[now] = o[old]; delete o[old]; }
  }
  for (const [key, map] of Object.entries(VALUES)) {
    if (typeof o[key] === 'string' && map[o[key]] && !(key === 'land' && o[key] === 'land')) o[key] = map[o[key]];
  }
  for (const v of Object.values(o)) legacyOpts(v, depth + 1);
  return o;
}

export const legacyRole = r => ROLE[r] || r;
export const legacyHit = k => HIT[k] || k;

// The spec's pace contract was written with camelCase keys in 1.2.0.
export function legacyPace(p) {
  if (!plain(p)) return p;
  const out = { ...p };
  if (out.maxStill != null && out.max_still == null) out.max_still = out.maxStill;
  if (out.maxStillShare != null && out.max_still_share == null) out.max_still_share = out.maxStillShare;
  delete out.maxStill; delete out.maxStillShare;
  return out;
}

// Old names on an object (the kit's blocks, the curves, ctx), hidden from enumeration.
export function alias(obj, names) {
  for (const [old, now] of Object.entries(names)) {
    if (!(old in obj)) Object.defineProperty(obj, old, { get: () => obj[now], enumerable: false });
  }
  return obj;
}
