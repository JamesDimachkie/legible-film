// Colour: parsing, OKLab/OKLCH, WCAG contrast, tinted-neutral palettes from one brand colour.
// Colours are interpolated in OKLab, never in gamma-encoded sRGB.

const clamp01 = v => (v < 0 ? 0 : v > 1 ? 1 : v);

export function parse(c) {
  if (Array.isArray(c)) return c.slice(0, 3).map(Number);
  if (typeof c !== 'string') throw new Error(`not a colour: ${c}`);
  let s = c.trim();
  if (s.startsWith('#')) {
    s = s.slice(1);
    if (s.length === 3) s = s.split('').map(x => x + x).join('');
    if (s.length !== 6) throw new Error(`not a colour: ${c}`);
    return [0, 2, 4].map(i => parseInt(s.slice(i, i + 2), 16) / 255);
  }
  const m = s.match(/^oklch\(\s*([\d.]+)(%?)\s+([\d.]+)\s+([\d.]+)\s*\)$/i);
  if (m) return oklchToRgb([+m[1] / (m[2] ? 100 : 1), +m[3], +m[4]]);
  const r = s.match(/^rgb\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)\s*\)$/i);
  if (r) return [+r[1] / 255, +r[2] / 255, +r[3] / 255];
  throw new Error(`not a colour: ${c}`);
}

export function hex(rgb) {
  return '#' + rgb.map(v => Math.round(clamp01(v) * 255).toString(16).padStart(2, '0')).join('').toUpperCase();
}

const toLinear = v => (v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4));
const toGamma = v => (v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055);

export function rgbToOklab(rgb) {
  const [r, g, b] = rgb.map(toLinear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
  ];
}

function oklabToLinear([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ];
}

export function oklabToRgb(lab) {
  return oklabToLinear(lab).map(v => clamp01(toGamma(clamp01(v))));
}

export function rgbToOklch(rgb) {
  const [L, a, b] = rgbToOklab(rgb);
  const C = Math.hypot(a, b);
  let h = (Math.atan2(b, a) * 180) / Math.PI;
  if (h < 0) h += 360;
  return [L, C, h];
}

const inGamut = lin => lin.every(v => v >= -1e-4 && v <= 1 + 1e-4);

// OKLCH to sRGB, reducing chroma (keeping lightness and hue) until the colour is in gamut.
export function oklchToRgb([L, C, h]) {
  const lab = c => [L, c * Math.cos((h * Math.PI) / 180), c * Math.sin((h * Math.PI) / 180)];
  if (inGamut(oklabToLinear(lab(C)))) return oklabToRgb(lab(C));
  let lo = 0, hi = C;
  for (let i = 0; i < 24; i++) {
    const mid = (lo + hi) / 2;
    if (inGamut(oklabToLinear(lab(mid)))) lo = mid; else hi = mid;
  }
  return oklabToRgb(lab(lo));
}

export function mix(a, b, t) {
  const A = rgbToOklab(parse(a)), B = rgbToOklab(parse(b));
  return hex(oklabToRgb(A.map((v, i) => v + (B[i] - v) * t)));
}

export function luminance(c) {
  const [r, g, b] = parse(c).map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const la = luminance(a), lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// Saturated red in the WCAG sense: R / (R + G + B) >= 0.8.
export function isRed(c) {
  const [r, g, b] = parse(c);
  const sum = r + g + b;
  return sum > 0.05 && r / sum >= 0.8;
}

// Composite colour `top` at opacity `a` over `bottom` (in linear light, as the screen adds them).
export function over(bottom, top, a) {
  const B = parse(bottom).map(toLinear), T = parse(top).map(toLinear);
  return hex(B.map((v, i) => toGamma(v + (T[i] - v) * clamp01(a))));
}

// A palette from one brand colour (DESIGN §11): neutrals that carry the brand's hue at low chroma,
// the brand as the single accent, semantic colours kept apart. Explicit colours override.
export function palette(brand = '#3D7BFF', overrides = {}) {
  const [bl, bc, bh] = rgbToOklch(parse(brand));
  const tint = (L, c) => hex(oklchToRgb([L, Math.min(c, bc * 0.35 + 0.004), bh]));
  const p = {
    accent: hex(parse(brand)),
    paper: tint(0.972, 0.012),
    soft: tint(0.925, 0.018),
    mist: tint(0.84, 0.022),
    mute: tint(0.62, 0.03),
    rule: tint(0.34, 0.03),
    panel: tint(0.235, 0.03),
    ink: tint(0.175, 0.026),
    deep: tint(0.13, 0.022),
    accentDeep: hex(oklchToRgb([Math.max(0.2, bl - 0.28), bc * 0.85, bh])),
    accentSoft: hex(oklchToRgb([Math.min(0.93, bl + 0.32), bc * 0.4, bh])),
    success: hex(oklchToRgb([0.74, 0.16, 152])),
    error: hex(oklchToRgb([0.64, 0.2, 27])),
  };
  for (const [k, v] of Object.entries(overrides || {})) p[k] = hex(parse(v));
  return p;
}

// Resolve a palette name or a literal colour.
export function resolve(pal, c) {
  if (c == null) return null;
  if (typeof c === 'string' && Object.prototype.hasOwnProperty.call(pal, c)) return pal[c];
  return hex(parse(c));
}

// The palette colour with the higher WCAG contrast against `ground` (paper or ink by default).
export function typeOn(pal, ground, candidates = ['paper', 'ink']) {
  let best = null, bestC = -1;
  for (const name of candidates) {
    const col = resolve(pal, name);
    const c = contrast(col, ground);
    if (c > bestC) { best = col; bestC = c; }
  }
  return best;
}

// Composite as a 2-D canvas does by default: in gamma-encoded sRGB (what the screen then shows).
export function canvasOver(bottom, top, a) {
  const B = parse(bottom), T = parse(top);
  return hex(B.map((v, i) => v + (T[i] - v) * clamp01(a)));
}

// The alpha at which `top` drawn over `bottom` differs from it by `cdm2` (relative luminance x 100,
// a 100 cd/m2 SDR white), capped at `cap`.
export function alphaForDifference(bottom, top, cdm2, cap = 1) {
  const L0 = luminance(bottom);
  const diff = a => Math.abs(luminance(canvasOver(bottom, top, a)) - L0) * 100;
  if (diff(cap) <= cdm2) return cap;
  let lo = 0, hi = cap;
  for (let i = 0; i < 20; i++) { const m = (lo + hi) / 2; if (diff(m) > cdm2) hi = m; else lo = m; }
  return lo;
}
