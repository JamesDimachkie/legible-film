// Type: font loading, measurement after fonts load, fitting display words to the safe width,
// whole-letter and whole-word spans with word spaces that never collapse, outlined type,
// extruded 3D type, and the counter (hole) of a letter for camera dives.

import { Node } from './node.js';
import { mix } from './color.js';

export const FAMILIES = { display: 'LF Display', text: 'LF Text', mono: 'LF Mono' };

export const DEFAULT_FONTS = {
  display: { url: 'fonts/MonaSansVF.woff2', weight: '200 900', stretch: '75% 125%' },
  text: { url: 'fonts/MonaSansVF.woff2', weight: '200 900', stretch: '75% 125%' },
  mono: { url: 'fonts/GeistMonoVF.woff2', weight: '100 900', stretch: '100%' },
};

// Load every face before anything is measured. Brand fonts in the spec replace these.
export async function loadFonts(base, fonts = {}) {
  const all = { ...DEFAULT_FONTS, ...fonts };
  const loaded = [];
  for (const [role, f] of Object.entries(all)) {
    const desc = { weight: f.weight || '100 900', stretch: f.stretch || '100%', style: 'normal' };
    const face = new FontFace(f.family || FAMILIES[role], `url(${new URL(f.url, base).href})`, desc);
    await face.load();
    document.fonts.add(face);
    loaded.push(face);
    if (f.family) FAMILIES[role] = f.family;
  }
  await document.fonts.ready;
  return loaded;
}

let measureBox = null;
function measurer() {
  if (!measureBox) {
    measureBox = document.createElement('div');
    measureBox.id = 'lf-measure';
    // Displayed (never display:none, which measures zero) but invisible and untransformed.
    measureBox.style.cssText = 'position:absolute;left:0;top:0;visibility:hidden;pointer-events:none;contain:layout style;';
    document.body.appendChild(measureBox);
  }
  return measureBox;
}

let canvasCtx = null;
function ctx2d() {
  if (!canvasCtx) canvasCtx = document.createElement('canvas').getContext('2d');
  return canvasCtx;
}

const STRETCH_KEYWORDS = [
  [50, 'ultra-condensed'], [62.5, 'extra-condensed'], [75, 'condensed'], [87.5, 'semi-condensed'],
  [100, 'normal'], [112.5, 'semi-expanded'], [125, 'expanded'], [150, 'extra-expanded'],
];
function stretchKeyword(pct) {
  let best = STRETCH_KEYWORDS[4];
  for (const k of STRETCH_KEYWORDS) if (Math.abs(k[0] - pct) < Math.abs(best[0] - pct)) best = k;
  return best[1];
}

export function styleCss(st) {
  const fam = FAMILIES[st.font || 'display'] || st.font;
  return [
    `font-family:"${fam}"`, `font-size:${st.size}px`, `font-weight:${st.weight ?? 800}`,
    `font-stretch:${st.width ?? 100}%`, `line-height:${st.lineHeight ?? 1}`,
    `letter-spacing:${st.tracking ?? 0}em`, 'white-space:pre', 'font-kerning:normal',
    'font-optical-sizing:auto', 'font-feature-settings:"tnum" 1' + (st.features ? ',' + st.features : ''),
  ].join(';');
}

// Vertical metrics in em: ascent and descent of the face, and the ink box of a string.
export function inkMetrics(string, st) {
  const c = ctx2d();
  const fam = FAMILIES[st.font || 'display'] || st.font;
  c.font = `${st.weight ?? 800} 200px "${fam}"`;
  try { c.fontStretch = stretchKeyword(st.width ?? 100); } catch (e) { /* older engines */ }
  const m = c.measureText(string || 'H');
  return {
    asc: m.fontBoundingBoxAscent / 200, desc: m.fontBoundingBoxDescent / 200,
    inkAsc: m.actualBoundingBoxAscent / 200, inkDesc: m.actualBoundingBoxDescent / 200,
  };
}

// Build the content of a text element: words as inline-blocks separated by margins (so spaces
// never collapse), letters as spans (for whole-letter reveals).
function fill(el, string, st) {
  el.textContent = '';
  const words = string.split(' ');
  const letters = [], wordEls = [];
  words.forEach((w, i) => {
    const we = document.createElement('span');
    we.className = 'lf-w';
    we.style.display = 'inline-block';
    if (i > 0) we.style.marginLeft = `${st.space ?? 0.26}em`;
    for (const ch of Array.from(w)) {
      const le = document.createElement('span');
      le.className = 'lf-l';
      le.textContent = ch;
      we.appendChild(le);
      letters.push(le);
    }
    el.appendChild(we);
    wordEls.push(we);
  });
  return { letters, wordEls };
}

export function measure(string, st) {
  const el = document.createElement('div');
  el.style.cssText = styleCss(st) + ';position:absolute;left:0;top:0;';
  fill(el, string, st);
  measurer().appendChild(el);
  const r = el.getBoundingClientRect();
  el.remove();
  return { w: r.width, h: r.height };
}

// The font size at which `string` is `width` px wide (measured, then refined once).
export function sizeForWidth(string, st, width) {
  const ref = measure(string, { ...st, size: 200 });
  let size = (200 * width) / Math.max(1, ref.w);
  const check = measure(string, { ...st, size });
  size *= width / Math.max(1, check.w);
  return size;
}

// A text node. Options: string, font, size, weight, width, tracking, lineHeight, color,
// outline (stroke px; the word is drawn as an outline until node.fillOn is reached),
// extrude {depth (em), layers, near, far, rx, ry}, anchor [ax, ay] on the ink box.
export function textNode(parent, opts) {
  const st = { font: 'display', size: 100, weight: 800, width: 100, lineHeight: 1, ...opts };
  const string = String(opts.string ?? '');
  const el = document.createElement('div');
  el.style.cssText = styleCss(st) + ';position:absolute;left:0;top:0;transform-origin:0 0;';

  let front = el, copies = [];
  if (opts.extrude) {
    // A capped stack of copies along depth inside a 3-D context; the front copy is the face.
    const x = opts.extrude;
    const layers = x.layers ?? 26;
    const inner = document.createElement('div');
    inner.className = 'lf-x3d';
    inner.style.cssText = 'position:relative;transform-style:preserve-3d;';
    for (let i = layers; i >= 1; i--) {
      const c = document.createElement('div');
      c.className = 'lf-x3d-layer';
      c.style.cssText = `position:absolute;left:0;top:0;transform:translateZ(${(-i * (x.depth ?? 0.2) * st.size / layers).toFixed(2)}px);`;
      c.style.color = mix(x.near, x.far, (i - 1) / Math.max(1, layers - 1));
      fill(c, string, st);
      inner.appendChild(c);
      copies.push(c);
    }
    front = document.createElement('div');
    front.className = 'lf-x3d-face';
    front.style.cssText = 'position:relative;transform:translateZ(0.5px);';
    inner.appendChild(front);
    el.appendChild(inner);
    el.style.perspective = `${(x.perspective ?? 6) * st.size}px`;
  }
  const { letters, wordEls } = fill(front, string, st);
  // Outlined type: variable fonts have overlapping contours, so a plain stroke shows their insides.
  // Instead the face is stroked at twice the width and a knockout copy filled with the ground sits
  // on top: only the outer half of the stroke shows, a clean outline.
  let knock = null;
  if (opts.outline) {
    knock = document.createElement('div');
    knock.className = 'lf-knockout';
    knock.style.cssText = 'position:absolute;left:0;top:0;z-index:2;-webkit-text-stroke:0;';
    fill(knock, string, st);
    front.appendChild(knock);
  }
  measurer().appendChild(el);
  const r = front.getBoundingClientRect();
  const w = r.width, h = r.height;
  // Positions of letters (for counters) and words, relative to the element, while displayed.
  const letterBoxes = letters.map(l => { const b = l.getBoundingClientRect(); return [b.left - r.left, b.top - r.top, b.width, b.height]; });
  const wordBoxes = wordEls.map(l => { const b = l.getBoundingClientRect(); return [b.left - r.left, b.top - r.top, b.width, b.height]; });
  // The real baseline, measured with a zero-size probe (computed metrics can be off by rounding).
  let measuredBaseline = null;
  if (wordEls.length) {
    const probe = document.createElement('span');
    probe.style.cssText = 'display:inline-block;width:0;height:0;vertical-align:baseline;';
    wordEls[0].appendChild(probe);
    measuredBaseline = probe.getBoundingClientRect().top - r.top;
    probe.remove();
  }
  el.remove();
  if (opts.extrude) { el.style.width = `${w}px`; el.style.height = `${h}px`; el.style.perspectiveOrigin = '50% 50%'; }

  const node = new Node({ el, parent, w, h });
  const mtx = inkMetrics(string, st);
  const lh = st.lineHeight * st.size;
  const baseline = measuredBaseline ?? (lh - (mtx.asc + mtx.desc) * st.size) / 2 + mtx.asc * st.size;
  node.baseline = baseline;
  node.ink = [0, baseline - mtx.inkAsc * st.size, w, baseline + mtx.inkDesc * st.size];
  // Anchor on the ink box (default: its centre), so caps-only words centre optically.
  const [ax, ay] = opts.anchor ?? [0.5, 0.5];
  node.ax = ax;
  node.ay = (node.ink[1] + ay * (node.ink[3] - node.ink[1])) / h;
  node.string = string;
  node.style = st;
  node.fontPx = st.size;
  node.letters = letters;
  node.wordEls = wordEls;
  node.letterBoxes = letterBoxes;
  node.wordBoxes = wordBoxes;
  node.front = front;
  node.copies = copies;
  node.kind = 'text';
  node.rest({ color: opts.color ?? null });
  if (opts.extrude) node.rest({ rx: opts.extrude.rx ?? 0, ry: opts.extrude.ry ?? 0 });
  if (opts.outline) node.rest({ stroke: opts.outline, strokeColor: opts.strokeColor ?? opts.color });

  const prev = { reveal: null, rw: null, stroke: null, rx: null, ry: null, fc: null, flat: false, kc: null };
  node.textColour = true;
  node.onFlush = n => {
    const nl = letters.length;
    const shown = Math.min(nl, Math.max(0, Math.floor(n.reveal)));
    if (shown !== prev.reveal) {
      letters.forEach((l, i) => { l.style.opacity = i < shown ? '' : '0'; });
      prev.reveal = shown;
    }
    const ws = Math.min(wordEls.length, Math.max(0, Math.floor(n.revealWords)));
    if (ws !== prev.rw) {
      wordEls.forEach((l, i) => { l.style.visibility = i < ws ? '' : 'hidden'; });
      prev.rw = ws;
    }
    const out = n.stroke > 0;
    const sk = out ? `${(n.stroke * 2).toFixed(2)}px ${n.strokeColor || n.color}` : '';
    if (sk !== prev.stroke) { front.style.webkitTextStroke = sk; prev.stroke = sk; }
    const fc = n.clipText ? 'transparent' : out ? n.strokeColor || n.color || '' : n.color || '';
    if (fc !== prev.fc) { front.style.color = fc; prev.fc = fc; }
    if (knock) {
      const kc = out ? n.knockout || 'transparent' : '';
      if (kc !== prev.kc) { knock.style.color = kc; knock.style.visibility = out ? 'visible' : 'hidden'; prev.kc = kc; }
    }
    // `flat`: drop the 3-D stack (copies and perspective) and draw the face alone. Browsers stop
    // rasterising 3-D layers at very high zoom, so dives go flat for their last stretch.
    const flat = !!n.flat;
    if (copies.length && flat !== prev.flat) {
      for (const c of copies) c.style.display = flat ? 'none' : '';
      el.style.perspective = flat ? 'none' : `${(opts.extrude.perspective ?? 6) * st.size}px`;
      el.firstChild.style.transformStyle = flat ? 'flat' : 'preserve-3d';
      prev.flat = flat; prev.rx = null;
    }
    if (copies.length && flat) {
      if (prev.rx !== 'flat') { el.firstChild.style.transform = 'none'; prev.rx = 'flat'; }
    } else if (copies.length && (n.rx !== prev.rx || n.ry !== prev.ry)) {
      el.firstChild.style.transform = `rotateX(${n.rx.toFixed(3)}deg) rotateY(${n.ry.toFixed(3)}deg)`;
      prev.rx = n.rx; prev.ry = n.ry;
    }
  };
  return node;
}

// Visible fraction of letters: whole letters only.
export function lettersShown(node) {
  const n = node.letters.length;
  return Math.min(n, Math.max(0, Math.floor(node.reveal))) / Math.max(1, n);
}

// The largest enclosed counter of letter `index` in a text node: its centre and size in the node's
// layout coordinates, and a mask image (the counter, dilated under the ink) for a window behind it.
export function counterOf(node, index, opts = {}) {
  const st = node.style;
  const ch = node.letters[index]?.textContent;
  const box = node.letterBoxes[index];
  if (!ch || !box) return null;
  // Raster at up to four times the layout size (bounded), for a precise traced outline.
  const S = [4, 3, 2].find(k => (box[2] * k + st.size * k * 0.5) * (box[3] * k + st.size * k * 0.5) < 6e6) || 2;
  const pad = Math.ceil(st.size * S * 0.25);
  const W = Math.ceil(box[2] * S) + 2 * pad, H = Math.ceil(box[3] * S) + 2 * pad;
  const cv = document.createElement('canvas');
  cv.width = W; cv.height = H;
  const c = cv.getContext('2d');
  const fam = FAMILIES[st.font || 'display'] || st.font;
  c.font = `${st.weight ?? 800} ${st.size * S}px "${fam}"`;
  try { c.fontStretch = stretchKeyword(st.width ?? 100); } catch (e) { /* ignore */ }
  c.fillStyle = '#000';
  c.textBaseline = 'alphabetic';
  const x0 = pad;                    // the glyph's origin sits at the DOM letter box's left edge
  c.fillText(ch, x0, pad + (node.baseline - box[1]) * S);
  const data = c.getImageData(0, 0, W, H).data;
  const ink = new Uint8Array(W * H);
  for (let i = 0; i < W * H; i++) ink[i] = data[i * 4 + 3] > 110 ? 1 : 0;
  // Label connected non-ink regions; any region touching the border is outside the letter.
  const lab = new Int32Array(W * H);
  const stack = [];
  const flood = (start, id) => {
    stack.length = 0; stack.push(start); lab[start] = id;
    let n = 0, sx = 0, sy = 0, minx = W, miny = H, maxx = 0, maxy = 0, edge = false;
    while (stack.length) {
      const p = stack.pop(), x = p % W, y = (p / W) | 0;
      n++; sx += x; sy += y;
      if (x < minx) minx = x; if (x > maxx) maxx = x; if (y < miny) miny = y; if (y > maxy) maxy = y;
      if (x === 0 || y === 0 || x === W - 1 || y === H - 1) edge = true;
      if (x > 0 && !lab[p - 1] && !ink[p - 1]) { lab[p - 1] = id; stack.push(p - 1); }
      if (x < W - 1 && !lab[p + 1] && !ink[p + 1]) { lab[p + 1] = id; stack.push(p + 1); }
      if (y > 0 && !lab[p - W] && !ink[p - W]) { lab[p - W] = id; stack.push(p - W); }
      if (y < H - 1 && !lab[p + W] && !ink[p + W]) { lab[p + W] = id; stack.push(p + W); }
    }
    return { id, n, cx: sx / n, cy: sy / n, minx, miny, maxx, maxy, edge };
  };
  let best = null, id = 1;
  for (let p = 0; p < W * H; p++) {
    if (lab[p] || ink[p]) continue;
    const r = flood(p, id++);
    if (!r.edge && (!best || r.n > best.n)) best = r;
  }
  if (!best || best.n < 20) return null;
  // The counter as a vector outline: marching squares over the anti-aliased raster, so the window
  // stays sharp however far the camera magnifies it (a scaled bitmap stair-steps).
  // The field is the counter's "not ink" coverage, restricted to the counter and the ink next to it.
  const near = new Uint8Array(W * H);
  const R = 3;
  for (let p = 0; p < W * H; p++) {
    if (lab[p] !== best.id) continue;
    const x = p % W, y = (p / W) | 0;
    for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++) {
      const xx = x + dx, yy = y + dy;
      if (xx >= 0 && yy >= 0 && xx < W && yy < H) near[yy * W + xx] = 1;
    }
  }
  const v = new Float32Array(W * H);
  for (let p = 0; p < W * H; p++) {
    if (lab[p] === best.id) v[p] = 1 - data[p * 4 + 3] / 255;
    else if (ink[p] && near[p]) v[p] = 1 - data[p * 4 + 3] / 255;
  }
  // iso 0.5 traces the letter's edge exactly; a lower level grows the window under the ink.
  const iso = opts.iso ?? (opts.dilate === 1 ? 0.45 : 0.2);
  const loops = traceLoops(v, W, H, iso);
  const loop = loops.reduce((m, l) => (l.length > m.length ? l : m), []);
  if (loop.length < 8) return null;
  const d = 'M' + loop.map(p => `${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join('L') + 'Z';
  // Map raster coordinates back to the node's layout coordinates.
  const ox = box[0] - pad / S;
  const oy = box[1] - pad / S;
  return {
    cx: ox + best.cx / S, cy: oy + best.cy / S,
    w: (best.maxx - best.minx + 1) / S, h: (best.maxy - best.miny + 1) / S,
    path: d, vw: W, vh: H, mx: ox, my: oy, mw: W / S, mh: H / S,
  };
}

// Marching squares: closed iso-lines of a scalar field (row-major, W x H) at level `iso`.
export function traceLoops(v, W, H, iso) {
  const segs = new Map();
  const key = (x, y) => `${Math.round(x * 64)},${Math.round(y * 64)}`;
  const lerpP = (x0, y0, v0, x1, y1, v1) => { const k = (iso - v0) / (v1 - v0); return [x0 + (x1 - x0) * k, y0 + (y1 - y0) * k]; };
  const addSeg = (P, Q) => {
    const kp = key(P[0], P[1]), kq = key(Q[0], Q[1]);
    if (kp === kq) return;
    if (!segs.has(kp)) segs.set(kp, []);
    segs.get(kp).push(kq);
    if (!segs.has(kq)) segs.set(kq, []);
    segs.get(kq).push(kp);
  };
  for (let y = 0; y < H - 1; y++) for (let x = 0; x < W - 1; x++) {
    const a0 = v[y * W + x], a1 = v[y * W + x + 1], a2 = v[(y + 1) * W + x + 1], a3 = v[(y + 1) * W + x];
    const c = (a0 > iso ? 1 : 0) | (a1 > iso ? 2 : 0) | (a2 > iso ? 4 : 0) | (a3 > iso ? 8 : 0);
    if (c === 0 || c === 15) continue;
    const T = () => lerpP(x, y, a0, x + 1, y, a1), Rr = () => lerpP(x + 1, y, a1, x + 1, y + 1, a2);
    const Bm = () => lerpP(x, y + 1, a3, x + 1, y + 1, a2), L = () => lerpP(x, y, a0, x, y + 1, a3);
    const centre = (a0 + a1 + a2 + a3) / 4 > iso;
    switch (c) {
      case 1: case 14: addSeg(L(), T()); break;
      case 2: case 13: addSeg(T(), Rr()); break;
      case 3: case 12: addSeg(L(), Rr()); break;
      case 4: case 11: addSeg(Rr(), Bm()); break;
      case 6: case 9: addSeg(T(), Bm()); break;
      case 7: case 8: addSeg(L(), Bm()); break;
      case 5: if (centre) { addSeg(L(), Bm()); addSeg(T(), Rr()); } else { addSeg(L(), T()); addSeg(Rr(), Bm()); } break;
      case 10: if (centre) { addSeg(L(), T()); addSeg(Rr(), Bm()); } else { addSeg(T(), Rr()); addSeg(L(), Bm()); } break;
    }
  }
  const used = new Set(), loops = [];
  for (const k0 of segs.keys()) {
    if (used.has(k0)) continue;
    const pts = [];
    let k = k0, prevK = null, guard = 0;
    while (k && !used.has(k) && guard++ < 400000) {
      used.add(k);
      const [px, py] = k.split(',').map(n => +n / 64);
      pts.push([px, py]);
      let nextK = null;
      for (const q of segs.get(k) || []) if (q !== prevK && !used.has(q)) { nextK = q; break; }
      prevK = k; k = nextK;
    }
    if (pts.length >= 3) loops.push(pts);
  }
  return loops;
}

const pathOf = (loops, sx, sy, ox, oy) => loops.map(l => 'M' + l.map(p => `${(ox + p[0] * sx).toFixed(2)} ${(oy + p[1] * sy).toFixed(2)}`).join('L') + 'Z').join('');

// The whole text as vector outlines in the node's layout coordinates (fill with evenodd): drawn in
// place of a magnified bitmap at the extreme end of a dive, so nothing stair-steps or goes soft.
export function textOutline(node) {
  const st = node.style;
  const fam = FAMILIES[st.font || 'display'] || st.font;
  const parts = [], loops = [];
  node.letters.forEach((le, i) => {
    const box = node.letterBoxes[i];
    const S = [4, 3, 2].find(k => (box[2] * k + st.size * k * 0.5) * (box[3] * k + st.size * k * 0.5) < 4e6) || 2;
    const pad = Math.ceil(st.size * S * 0.25);
    const W = Math.ceil(box[2] * S) + 2 * pad, H = Math.ceil(box[3] * S) + 2 * pad;
    const cv = document.createElement('canvas');
    cv.width = W; cv.height = H;
    const c = cv.getContext('2d');
    c.font = `${st.weight ?? 800} ${st.size * S}px "${fam}"`;
    try { c.fontStretch = stretchKeyword(st.width ?? 100); } catch (e) { /* ignore */ }
    c.fillStyle = '#000';
    c.fillText(le.textContent, pad, pad + (node.baseline - box[1]) * S);
    const data = c.getImageData(0, 0, W, H).data;
    const v = new Float32Array(W * H);
    for (let p = 0; p < W * H; p++) v[p] = data[p * 4 + 3] / 255;
    const ls = traceLoops(v, W, H, 0.5).map(l => l.map(p => [box[0] - pad / S + p[0] / S, box[1] - pad / S + p[1] / S]));
    loops.push(...ls.map(l => ({ letter: i, pts: l })));
    parts.push(pathOf(ls, 1, 1, 0, 0));
  });
  return { d: parts.join(''), loops };
}

// The smallest outline loop of letter `index` that contains (x, y): the counter around that point.
export function loopAround(outline, index, x, y) {
  const inside = (pts) => {
    let c = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  const area = pts => Math.abs(pts.reduce((a, p, i) => { const q = pts[(i + 1) % pts.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0) / 2);
  let best = null;
  for (const l of outline.loops) if (l.letter === index && inside(l.pts) && (!best || area(l.pts) < area(best))) best = l.pts;
  return best ? 'M' + best.map(p => `${p[0].toFixed(2)} ${p[1].toFixed(2)}`).join('L') + 'Z' : null;
}

// Typing: after `chars` characters of the node's string are typed, how many letters show and where
// the caret sits (in the node's layout coordinates). Spaces are typed but are not letters.
export function typed(node, chars) {
  const str = node.string;
  const n = Math.max(0, Math.min(str.length, Math.floor(chars)));
  let letters = 0;
  for (let i = 0; i < n; i++) if (str[i] !== ' ') letters++;
  let x = 0;
  if (letters > 0) { const b = node.letterBoxes[letters - 1]; x = b[0] + b[2]; }
  if (n > 0 && str[n - 1] === ' ') x += (node.style.space ?? 0.26) * node.fontPx;
  return { reveal: letters, caretX: x, done: n >= str.length };
}
