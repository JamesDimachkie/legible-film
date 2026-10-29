// Predicted flashing by the method flash_scan.py applies to the delivered file: each frame is drawn
// small (192 px wide) from the film's own state (ground, world effects, plates, counter windows,
// the type itself and the screen effect canvases); windows a third of the frame wide and high, on a
// sixth-of-the-frame grid, track their 74th and 26th luminance percentiles; a transition is a swing
// of at least 0.10 whose darker end is below 0.80 (and a swing of 20 in the saturated-red amount);
// more than six in any second is flagged. It is a prediction: motion blur, encoding and anything a
// block draws without registering it (a text, a plate, an effect) are not in it.

import { mul, apply } from './node.js';
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
      c.globalAlpha = Math.min(1, n.alpha());
      const st = n.style;
      c.font = `${st.weight ?? 800} ${st.size}px "${FAMILIES[st.font || 'display'] || st.font}"`;
      try { c.fontStretch = stretchKw(st.width ?? 100); } catch (e) { /* older engines */ }
      const bl = n.blurChain();
      c.filter = bl > 0.5 ? `blur(${(bl * k * Math.sqrt(Math.abs(M[0] * M[3]))).toFixed(2)}px)` : 'none';
      const col = n.color || film.typeOn(ground);
      const shown = Math.min(n.letters.length, Math.max(0, Math.floor(n.reveal)));
      const out = n.stroke > 0;
      if (out) { c.strokeStyle = n.strokeColor || col; c.lineWidth = n.stroke * 2; } else c.fillStyle = col;
      for (let i = 0; i < shown; i++) {
        const ch = n.letters[i].textContent, b = n.letterBoxes[i];
        if (out) c.strokeText(ch, b[0], n.baseline); else c.fillText(ch, b[0], n.baseline);
      }
      if (out && n.knockout) { c.fillStyle = n.knockout; for (let i = 0; i < shown; i++) c.fillText(n.letters[i].textContent, n.letterBoxes[i][0], n.baseline); }
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
      return { scan_size: [W, H], gb, rb, flagged: rows.filter(r => r.general_max_per_s > 6 || r.red_max_per_s > 6), rows, debug };
    },
  };
}
