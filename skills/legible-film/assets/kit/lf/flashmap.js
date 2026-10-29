// Predicted flashing by the method flash_scan.py applies to the delivered file: each frame is drawn
// small (192 px wide) from the film's own state (ground, world effects, plates, counter windows,
// the type itself and the screen effect canvases); windows a third of the frame wide and high, on a
// sixth-of-the-frame grid, track their 74th and 26th luminance percentiles; a transition is a swing
// of at least 0.10 whose darker end is below 0.80 (and a swing of 20 in the saturated-red amount);
// more than six in any second is flagged. It is a prediction: motion blur, encoding and anything a
// block draws without registering or tracking it (a text, a plate, an effect, a tracked node) are not
// in it.
//
// A tracked node (ctx.track) is drawn as its element paints: its fill or background, borders, box
// shadows, and the images and canvases inside it, through its whole subtree, each node with its own
// transform, opacity, blur and blend mode composited as a layer. A plate stands in for its node's
// content and a registered text is drawn with the type. Whatever a tracked node paints that this
// cannot model (an SVG, a video, a CSS background image, a transform or filter inside the element, a
// 3-D turn, a cross-origin image) is listed in `incomplete`, so a prediction never reads as whole
// when it is not.

import { mul, apply, matScale } from './node.js';
import { FAMILIES } from './text.js';
import { inScreen } from './engine.js';

const STRETCH = [[50, 'ultra-condensed'], [62.5, 'extra-condensed'], [75, 'condensed'], [87.5, 'semi-condensed'], [100, 'normal'], [112.5, 'semi-expanded'], [125, 'expanded'], [150, 'extra-expanded']];
const stretchKw = pct => STRETCH.reduce((b, k) => (Math.abs(k[0] - pct) < Math.abs(b[0] - pct) ? k : b), STRETCH[4])[1];
const Max6 = v => Math.max(6, v);
const LUT = new Float32Array(256).map((_, i) => { const c = i / 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; });

class Zig {
  constructor(thr, darkerBelow = null) { this.thr = thr; this.db = darkerBelow; this.p = null; this.e = null; this.et = 0; this.d = 0; this.ends = []; }
  count(a, b, t) { if (Math.abs(b - a) >= this.thr && (this.db == null || Math.min(a, b) < this.db)) this.ends.push(t); }
  push(t, v) {
    if (this.p == null) { this.p = this.e = v; this.et = t; return; }
    if (this.d === 0) {
      if (v - this.p >= this.thr) { this.d = 1; this.e = v; this.et = t; }
      else if (this.p - v >= this.thr) { this.d = -1; this.e = v; this.et = t; }
      return;
    }
    if ((this.d === 1 && v > this.e) || (this.d === -1 && v < this.e)) { this.e = v; this.et = t; }
    else if (Math.abs(this.e - v) >= this.thr) { this.count(this.p, this.e, this.et); this.p = this.e; this.e = v; this.et = t; this.d = -this.d; }
  }
  finish() { if (this.d !== 0) this.count(this.p, this.e, this.et); }
}

function busiest(ends) {
  ends = [...ends].sort((a, b) => a - b);
  let best = 0, at = null, j = 0;
  for (let i = 0; i < ends.length; i++) {
    while (ends[i] - ends[j] >= 1.0) j++;
    if (i - j + 1 > best) { best = i - j + 1; at = +ends[j].toFixed(3); }
  }
  return [best, at];
}

export function flashPredictor(film, scanWidth = 192, ss = 3) {
  const W = scanWidth - (scanWidth % 2);
  const H = Max6(Math.round((W * film.H) / film.W / 2) * 2);
  // Drawn at ss times the scan size and area-averaged down (as FFmpeg's area scaling does), so type
  // moving by sub-pixels changes the scan pixels continuously instead of in canvas-snapped steps.
  const k = (W * ss) / film.W;
  const cv = document.createElement('canvas');
  cv.width = W * ss; cv.height = H * ss;
  const c = cv.getContext('2d', { willReadFrequently: true });
  const ww = Math.floor(W / 3), wh = Math.floor(H / 3);
  const xs = [...new Set([...Array(Math.floor((W - ww) / Math.max(1, Math.floor(W / 6))) + 1).keys()].map(i => i * Math.max(1, Math.floor(W / 6))).concat([W - ww]))].sort((a, b) => a - b);
  const ys = [...new Set([...Array(Math.floor((H - wh) / Math.max(1, Math.floor(H / 6))) + 1).keys()].map(i => i * Math.max(1, Math.floor(H / 6))).concat([H - wh]))].sort((a, b) => a - b);
  const wins = [];
  for (const y of ys) for (const x of xs) wins.push([x, y]);
  const npx = ww * wh, k26 = Math.floor(0.26 * (npx - 1)), k74 = Math.floor(0.74 * (npx - 1));
  const zigs = wins.map(() => ({ hi: new Zig(0.1, 0.8), lo: new Zig(0.1, 0.8), red: new Zig(20) }));
  const series = wins.map(() => []);
  const Y = new Float32Array(W * H), RD = new Float32Array(W * H), buf = new Float32Array(npx), rbuf = new Float32Array(npx);
  const texts = film.reg.texts.flatMap(tx => tx.nodes.map(n => ({ n, tx })));
  const textNodes = new Set(texts.map(x => x.n)), plateNodes = new Set(film.plates.map(p => p.node));
  const trackedNodes = new Set(film.tracks.map(tr => tr.node));
  const under = (n, set) => { for (let p = n.parent; p; p = p.parent) if (set.has(p)) return true; return false; };
  // Each subtree once: a tracked node inside another tracked node, or inside a plate, is drawn with it.
  const roots = film.tracks.filter(tr => !plateNodes.has(tr.node) && !textNodes.has(tr.node) &&
    !under(tr.node, trackedNodes) && !under(tr.node, plateNodes));
  const missing = new Map();
  const miss = (tr, why) => { if (!missing.has(tr)) missing.set(tr, new Set()); missing.get(tr).add(why); };
  // Layers for a node's opacity, blur and blend mode, one per depth of the subtree.
  const layers = [];
  const layer = d => {
    if (!layers[d]) { const lc = document.createElement('canvas'); lc.width = cv.width; lc.height = cv.height; layers[d] = lc.getContext('2d'); }
    const g = layers[d];
    g.setTransform(1, 0, 0, 1, 0, 0); g.globalAlpha = 1; g.globalCompositeOperation = 'source-over'; g.filter = 'none';
    g.clearRect(0, 0, cv.width, cv.height);
    return g;
  };

  // Whole letters, outlines and blur, as a text node draws them (the alpha and blur are the chain's
  // unless a layer above applies them).
  function drawType(g, n, M, ground, alpha = n.alpha(), bl = n.blurChain()) {
    g.globalAlpha = Math.min(1, alpha);
    const st = n.style;
    g.font = `${st.weight ?? 800} ${st.size}px "${FAMILIES[st.font || 'display'] || st.font}"`;
    try { g.fontStretch = stretchKw(st.width ?? 100); } catch (e) { /* older engines */ }
    g.filter = bl > 0.5 ? `blur(${(bl * k * Math.sqrt(Math.abs(M[0] * M[3]))).toFixed(2)}px)` : 'none';
    const col = n.color || film.typeOn(ground);
    const shown = Math.min(n.letters.length, Math.max(0, Math.floor(n.reveal)));
    const out = n.stroke > 0;
    if (out) { g.strokeStyle = n.strokeColor || col; g.lineWidth = n.stroke * 2; } else g.fillStyle = col;
    for (let i = 0; i < shown; i++) {
      const ch = n.letters[i].textContent, b = n.letterBoxes[i];
      if (out) g.strokeText(ch, b[0], n.baseline); else g.fillText(ch, b[0], n.baseline);
    }
    if (out && n.knockout) { g.fillStyle = n.knockout; for (let i = 0; i < shown; i++) g.fillText(n.letters[i].textContent, n.letterBoxes[i][0], n.baseline); }
  }

  // What an element paints, read once (layout and the styles a block sets at build time are fixed;
  // the properties a node flushes every frame come from the node itself).
  const looks = new WeakMap();
  function look(el) {
    let s = looks.get(el);
    if (s) return s;
    const cs = getComputedStyle(el);
    const sides = ['Top', 'Right', 'Bottom', 'Left'].map(side => ({
      w: /^(none|hidden)$/.test(cs[`border${side}Style`]) ? 0 : parseFloat(cs[`border${side}Width`]) || 0, c: cs[`border${side}Color`] }));
    s = {
      display: cs.display, visibility: cs.visibility, opacity: +cs.opacity, bg: cs.backgroundColor, sides,
      bgImage: !!cs.backgroundImage && cs.backgroundImage !== 'none', radius: cs.borderTopLeftRadius,
      shadows: shadows(cs.boxShadow), blend: cs.mixBlendMode || 'normal',
      extra: ['transform', 'filter', 'clipPath', 'mask', 'perspective'].filter(p => cs[p] && cs[p] !== 'none'),
      text: [...el.childNodes].some(x => x.nodeType === 3 && x.textContent.trim()),
      size: [el.offsetWidth || 0, el.offsetHeight || 0],
    };
    looks.set(el, s);
    return s;
  }
  // Computed box shadows: "colour x y blur spread [inset]", comma-separated outside brackets.
  function shadows(v) {
    if (!v || v === 'none') return [];
    return v.split(/,(?![^()]*\))/).map(part => {
      const colour = (part.match(/rgba?\([^)]*\)|#[0-9a-f]{3,8}\b/i) || ['transparent'])[0];
      const [x = 0, y = 0, blur = 0, spread = 0] = (part.replace(colour, '').match(/-?[\d.]+(?=px)/g) || []).map(Number);
      return { colour, x, y, blur, spread, inset: /\binset\b/.test(part) };
    });
  }
  const BLEND = { normal: 'source-over', 'plus-lighter': 'lighter' };
  const rrect = (g, x, y, w, h, r) => {
    g.beginPath();
    const q = Math.max(0, Math.min(r, w / 2, h / 2));
    if (q > 0 && g.roundRect) g.roundRect(x, y, Math.max(0, w), Math.max(0, h), q); else g.rect(x, y, Math.max(0, w), Math.max(0, h));
  };
  // A box in its own coordinates (the context carries its transform): outer shadows, the fill, inset
  // shadows, then the borders. A shadow's blur radius is two standard deviations.
  function paintBox(g, s, w, h, fill) {
    const r = /%$/.test(s.radius) ? (parseFloat(s.radius) / 100) * Math.min(w, h) : parseFloat(s.radius) || 0;
    const T = g.getTransform(), dev = Math.sqrt(Math.abs(T.a * T.d - T.b * T.c));
    const BIG = 1e5;
    for (const sh of s.shadows) {
      if (sh.inset) continue;
      g.save();
      rrect(g, 0, 0, w, h, r); g.rect(-BIG, -BIG, 2 * BIG, 2 * BIG); g.clip('evenodd');
      g.filter = sh.blur > 0 ? `blur(${((sh.blur / 2) * dev).toFixed(2)}px)` : 'none';
      g.fillStyle = sh.colour;
      rrect(g, sh.x - sh.spread, sh.y - sh.spread, w + 2 * sh.spread, h + 2 * sh.spread, r + sh.spread); g.fill();
      g.restore();
    }
    if (fill) { g.fillStyle = fill; rrect(g, 0, 0, w, h, r); g.fill(); }
    for (const sh of s.shadows) {
      if (!sh.inset) continue;
      g.save();
      rrect(g, 0, 0, w, h, r); g.clip();
      g.filter = sh.blur > 0 ? `blur(${((sh.blur / 2) * dev).toFixed(2)}px)` : 'none';
      g.fillStyle = sh.colour;
      rrect(g, sh.x + sh.spread, sh.y + sh.spread, w - 2 * sh.spread, h - 2 * sh.spread, r - sh.spread);
      g.rect(-BIG, -BIG, 2 * BIG, 2 * BIG); g.fill('evenodd');
      g.restore();
    }
    const [bt, br, bb, bl] = s.sides;
    if (bt.w || br.w || bb.w || bl.w) {
      if (s.sides.every(x => x.w === bt.w && x.c === bt.c)) {
        g.fillStyle = bt.c; rrect(g, 0, 0, w, h, r);
        if (w > 2 * bt.w && h > 2 * bt.w) {
          const q = Math.max(0, Math.min(r - bt.w, (w - 2 * bt.w) / 2, (h - 2 * bt.w) / 2));
          if (q > 0 && g.roundRect) g.roundRect(bt.w, bt.w, w - 2 * bt.w, h - 2 * bt.w, q); else g.rect(bt.w, bt.w, w - 2 * bt.w, h - 2 * bt.w);
        }
        g.fill('evenodd');
      } else {
        for (const [side, x, y, ww, hh] of [[bt, 0, 0, w, bt.w], [bb, 0, h - bb.w, w, bb.w], [bl, 0, 0, bl.w, h], [br, w - br.w, 0, br.w, h]]) {
          if (side.w) { g.fillStyle = side.c; g.fillRect(x, y, ww, hh); }
        }
      }
    }
    return r;
  }
  // A plain element inside a tracked node (an image, a canvas, a styled box), at its layout offset.
  function paintElement(g, el, base, tr, depth = 0) {
    const s = look(el);
    if (s.display === 'none' || (el.style.visibility || s.visibility) === 'hidden' || s.opacity <= 0.002 || depth > 8) return;
    if (el instanceof SVGElement) { miss(tr, 'an SVG'); return; }
    if (s.extra.length) { miss(tr, `a CSS ${s.extra.join(', ')} inside the element`); return; }
    let x = 0, y = 0, e = el;
    for (; e && e !== base; e = e.offsetParent) { x += e.offsetLeft; y += e.offsetTop; }
    if (e !== base) { miss(tr, 'an element laid out outside its node'); return; }
    const [w, h] = s.size;
    g.save();
    g.translate(x, y);
    g.globalAlpha *= Math.min(1, s.opacity);
    const r = paintBox(g, s, w, h, s.bg);
    if (s.bgImage) miss(tr, 'a CSS background image');
    if (s.text) miss(tr, 'text that is not a registered text');
    const [bt, br, bb, bl] = s.sides.map(v => v.w);
    if (el.tagName === 'VIDEO') miss(tr, 'a video');
    else if (el.tagName === 'CANVAS' || el.tagName === 'IMG') {
      const ok = el.tagName === 'CANVAS' ? el.width > 0 && el.height > 0 : el.complete && el.naturalWidth > 0;
      const src = el.tagName === 'IMG' ? new URL(el.currentSrc || el.src, location.href) : null;
      if (src && src.origin !== location.origin && !/^(data|blob):$/.test(src.protocol)) miss(tr, 'a cross-origin image');
      else if (ok) {
        if (r > 0) { rrect(g, 0, 0, w, h, r); g.clip(); }
        g.drawImage(el, bl, bt, Math.max(0, w - bl - br), Math.max(0, h - bt - bb));
      }
    }
    for (const ch of el.children) paintElement(g, ch, base, tr, depth + 1);
    g.restore();
  }
  // A node of a tracked subtree into g: its own box and plain elements, then its child nodes. A node with
  // an opacity, a blur or a blend mode is drawn into a layer of its own and composited, as the browser does.
  function paintNode(g, n, tr, depth, ground, nodeM) {
    const s = look(n.el);
    if (n.opacity <= 0.002 || s.display === 'none') return;
    if (n.rx || n.ry) miss(tr, 'a 3-D turn');
    const blend = BLEND[s.blend] || s.blend;
    const own = n.opacity < 0.998 || n.blur > 0.05 || blend !== 'source-over';
    const L = own ? layer(depth) : g;
    const m = nodeM(n);
    if (n.letters) {
      if (!textNodes.has(n)) { L.save(); L.setTransform(...m); drawType(L, n, m, ground, 1, 0); L.restore(); }
    } else {
      L.save();
      L.setTransform(...m);
      const [w, h] = n.w || n.h ? [n.w, n.h] : s.size;
      paintBox(L, s, w, h, n.fill ?? s.bg);
      if (s.bgImage) miss(tr, 'a CSS background image');
      if (s.text) miss(tr, 'text that is not a registered text');
      const nodeEls = new Set(n.children.map(x => x.el));
      for (const el of n.el.children) if (!nodeEls.has(el)) paintElement(L, el, n.el, tr);
      L.restore();
    }
    for (const ch of n.children) if (!plateNodes.has(ch) && !textNodes.has(ch)) paintNode(L, ch, tr, depth + 1, ground, nodeM);
    if (own) {
      g.save(); g.setTransform(1, 0, 0, 1, 0, 0);
      g.globalAlpha = Math.min(1, Math.max(0, n.opacity)); g.globalCompositeOperation = blend;
      g.filter = n.blur > 0.05 ? `blur(${(n.blur * matScale(m)).toFixed(2)}px)` : 'none';
      g.drawImage(L.canvas, 0, 0);
      g.restore();
    }
  }

  function drawFrame(t, cam) {
    const ground = film.groundAt(t);
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.globalAlpha = 1; c.filter = 'none';
    c.fillStyle = ground; c.fillRect(0, 0, W * ss, H * ss);
    const env = {
      W: film.W, H: film.H, u: film.u, zoom: cam.zoom,
      groundAt: x => film.groundAt(x), groundLum: x => film.groundLum(x), typeOn: g => film.typeOn(g),
      visibleWorld: () => [-film.W * 4, -film.H * 4, film.W * 4, film.H * 4],
    };
    const M = cam.M;
    c.setTransform(M[0] * k, M[1] * k, M[2] * k, M[3] * k, M[4] * k, M[5] * k);
    for (const e of film.fx) if (e.layer === 'world' && e.kind !== 'texture') { c.save(); e.draw(c, t, env); c.restore(); }
    const nodeM = n => { const m = inScreen(n) ? n.matrix() : mul(M, n.matrix()); return [m[0] * k, m[1] * k, m[2] * k, m[3] * k, m[4] * k, m[5] * k]; };
    const live = n => n.alpha() > 0.01;
    for (const p of film.plates) {
      if (!live(p.node) || !(p.node.w > 0)) continue;
      c.setTransform(...nodeM(p.node)); c.globalAlpha = p.node.alpha();
      c.fillStyle = p.colour; c.fillRect(0, 0, p.node.w, p.node.h);
    }
    c.globalAlpha = 1;
    for (const tr of roots) {
      const n = tr.node, up = n.parent ? n.parent.alpha() : 1;
      if (up * n.opacity <= 0.01) continue;
      const g = layer(0);
      paintNode(g, n, tr, 1, ground, nodeM);
      const ub = n.parent ? n.parent.blurChain() : 0;
      c.save(); c.setTransform(1, 0, 0, 1, 0, 0); c.globalAlpha = Math.min(1, up);
      c.filter = ub > 0.05 && n.parent ? `blur(${(ub * matScale(nodeM(n.parent))).toFixed(2)}px)` : 'none';
      c.drawImage(g.canvas, 0, 0);
      c.restore();
    }
    for (const w of film.windows) {
      if (t < w.t0 || t >= w.t1 || !w.path2d) continue;
      const m = nodeM(w.node);
      const sx = w.hole.mw / w.hole.vw;
      c.setTransform(...mul(m, [sx, 0, 0, sx, w.hole.mx, w.hole.my]));
      c.fillStyle = w.colour; c.fill(w.path2d);
    }
    for (const { n } of texts) {
      if (!live(n) || !n.letters) continue;
      c.setTransform(...nodeM(n));
      drawType(c, n, M, ground);
    }
    c.filter = 'none'; c.globalAlpha = 1;
    c.setTransform(k, 0, 0, k, 0, 0);
    for (const e of film.fx) if (e.layer === 'screen') { c.save(); e.draw(c, t, env); c.restore(); }
  }

  return {
    size: [W, H], windows: wins.length,
    // Each output frame is averaged over sub-frame times inside its exposure (the render blurs the
    // same way); `at(ts)` puts the film in its state at ts and returns the camera.
    push(t, times, at) {
      Y.fill(0); RD.fill(0);
      const AR = new Float32Array(W * H), AG = new Float32Array(W * H), AB = new Float32Array(W * H);
      const SW = W * ss;
      for (const ts of times) {
        drawFrame(ts, at(ts));
        const d = c.getImageData(0, 0, SW, H * ss).data;
        for (let y = 0; y < H * ss; y++) {
          const row = ((y / ss) | 0) * W;
          for (let x = 0, p = y * SW * 4; x < SW; x++, p += 4) {
            const i = row + ((x / ss) | 0);
            AR[i] += LUT[d[p]]; AG[i] += LUT[d[p + 1]]; AB[i] += LUT[d[p + 2]];
          }
        }
      }
      const nS = times.length * ss * ss;
      for (let i = 0; i < W * H; i++) {
        const r = AR[i] / nS, g = AG[i] / nS, b = AB[i] / nS;
        Y[i] = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        const s = r + g + b + 1e-9;
        RD[i] = r / s >= 0.8 ? Math.max(0, (r - g - b) * 320) : 0;
      }
      wins.forEach(([x0, y0], wi) => {
        let q = 0;
        for (let y = y0; y < y0 + wh; y++) for (let x = x0; x < x0 + ww; x++) { buf[q] = Y[y * W + x]; rbuf[q++] = RD[y * W + x]; }
        buf.sort(); rbuf.sort();
        zigs[wi].hi.push(t, buf[k74]); zigs[wi].lo.push(t, buf[k26]); zigs[wi].red.push(t, rbuf[k74]);
        series[wi].push([+t.toFixed(3), +buf[k74].toFixed(3), +buf[k26].toFixed(3)]);
      });
    },
    result() {
      const rows = wins.map(([x, y], wi) => {
        const z = zigs[wi];
        z.hi.finish(); z.lo.finish(); z.red.finish();
        const g = [busiest(z.hi.ends), busiest(z.lo.ends)].reduce((a, b) => (b[0] > a[0] ? b : a));
        const r = busiest(z.red.ends);
        return { window: [x, y, ww, wh], general_max_per_s: g[0], general_at_s: g[1], red_max_per_s: r[0], red_at_s: r[1] };
      });
      const gb = rows.reduce((a, b) => (b.general_max_per_s > a.general_max_per_s ? b : a));
      const rb = rows.reduce((a, b) => (b.red_max_per_s > a.red_max_per_s ? b : a));
      const bi = rows.indexOf(gb);
      const debug = { window: gb.window, hi_ends: zigs[bi].hi.ends.map(x => +x.toFixed(3)), lo_ends: zigs[bi].lo.ends.map(x => +x.toFixed(3)), series: series[bi] };
      const incomplete = [...missing].map(([tr, why]) => ({ id: tr.id, block: tr.block, scene: tr.scene, unmodelled: [...why] }));
      return { scan_size: [W, H], gb, rb, flagged: rows.filter(r => r.general_max_per_s > 6 || r.red_max_per_s > 6), rows, debug, incomplete,
        tracked: roots.length };
    },
  };
}
