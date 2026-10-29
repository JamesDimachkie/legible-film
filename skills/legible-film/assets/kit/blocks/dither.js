// Dither field: a tone field (a gradient, slow noise, or an image's luminance) rendered as an ordered
// (Bayer) or blue-noise-like dither in two palette colours (ink and paper). The cell size is in frame
// units and must stay several pixels wide at the delivered size (single-pixel dither is destroyed by
// 4:2:0 encoding and shimmers in motion). The pattern is fixed to world cells, so it moves with the
// world or stays still and never crawls. Dense high-contrast patterns over large areas are flagged
// as a photosensitivity risk.
//
// Dither({ field: 'gradient' | 'noise' | 'image', src?, ink?, paper?, cell?: 0.9, pattern?: 'bayer' | 'blue',
//          angle?: 30, speed?: 0.15, len, words?: Words-like single headline { text, role, fact } })

import { block, typeColour, layoutLines, linesOf, joinLines } from './common.js';

const BAYER = (() => {
  // 8x8 Bayer matrix, built recursively.
  let m = [[0]];
  for (let k = 0; k < 3; k++) {
    const n = m.length, out = Array.from({ length: n * 2 }, () => new Array(n * 2));
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      const v = m[y][x] * 4;
      out[y][x] = v; out[y][x + n] = v + 2; out[y + n][x] = v + 3; out[y + n][x + n] = v + 1;
    }
    m = out;
  }
  return m.map(r => r.map(v => (v + 0.5) / 64));
})();
// Interleaved gradient noise: a cheap blue-noise-like threshold per cell, stable in world space.
const IGN = (x, y) => { const v = 52.9829189 * ((0.06711056 * x + 0.00583715 * y) % 1); return v - Math.floor(v); };

export const Dither = block('dither', (ctx, o) => {
  const pal = ctx.pal, u = ctx.u;
  const ink = ctx.colour(o.ink || 'ink'), paper = ctx.colour(o.paper || 'accent');
  const cellPx = (o.cell ?? 0.9) * u;
  if (cellPx < 3) ctx.warn(`Dither: cells are ${cellPx.toFixed(1)} px at ${ctx.W}x${ctx.H}; under about 3 px the pattern is destroyed by 4:2:0 encoding and shimmers in motion`);
  const len = ctx.time(o.len ?? 3);
  ctx.ground(ctx.t0, ink);
  const over = 1.4;
  const W = ctx.W * over, H = ctx.H * over;
  const cols = Math.ceil(W / cellPx), rows = Math.ceil(H / cellPx);
  const node = ctx.group.add({ name: 'dither', w: cols * cellPx, h: rows * cellPx });
  const cv = document.createElement('canvas');
  cv.width = cols; cv.height = rows;
  // Drawn at one pixel per cell and scaled up without smoothing: crisp square cells.
  cv.style.cssText = `display:block;width:${cols * cellPx}px;height:${rows * cellPx}px;image-rendering:pixelated;`;
  node.el.appendChild(cv);
  const c2 = cv.getContext('2d');
  const img = c2.createImageData(cols, rows);
  const [ir, ig, ib] = ctx.parse(ink).map(v => Math.round(v * 255)), [pr, pg, pb] = ctx.parse(paper).map(v => Math.round(v * 255));
  let lumField = null;
  if (o.field === 'image') {
    const a = ctx.env.images.get(o.src);
    if (!a?.img) throw new Error(`Dither: ${o.src} was not loaded`);
    const s = document.createElement('canvas'); s.width = cols; s.height = rows;
    const sc = s.getContext('2d');
    const k = Math.max(cols / a.width, rows / a.height);
    sc.drawImage(a.img, (cols - a.width * k) / 2, (rows - a.height * k) / 2, a.width * k, a.height * k);
    const d = sc.getImageData(0, 0, cols, rows).data;
    lumField = new Float32Array(cols * rows);
    for (let i = 0; i < cols * rows; i++) lumField[i] = (0.2126 * d[i * 4] + 0.7152 * d[i * 4 + 1] + 0.0722 * d[i * 4 + 2]) / 255;
  }
  const ang = ((o.angle ?? 30) * Math.PI) / 180;
  const tone = (x, y, t) => {
    if (lumField) return lumField[y * cols + x];
    const nx = x / cols - 0.5, ny = y / rows - 0.5;
    const g = 0.5 + (nx * Math.cos(ang) + ny * Math.sin(ang)) * 1.15;
    if (o.field !== 'noise') return g;
    const s = t * (o.speed ?? 0.15);
    return 0.55 * g + 0.45 * (0.5 + 0.5 * ctx.noise1(x * 0.06 + s * 3, 7) * ctx.noise1(y * 0.06 - s * 2, 11));
  };
  const thresh = o.pattern === 'blue' ? IGN : (x, y) => BAYER[y & 7][x & 7];
  let lastKey = null;
  function paint(t) {
    const key = o.field === 'noise' ? ctx.frameIndex(t) : 0;
    if (key === lastKey) return;
    lastKey = key;
    const d = img.data;
    for (let y = 0; y < rows; y++) for (let x = 0; x < cols; x++) {
      const on = tone(x, y, key / ctx.fps) > thresh(x, y);
      const i = (y * cols + x) * 4;
      d[i] = on ? pr : ir; d[i + 1] = on ? pg : ig; d[i + 2] = on ? pb : ib; d[i + 3] = 255;
    }
    c2.putImageData(img, 0, 0);
  }
  node.onFlush = () => paint(ctx.film._t);
  ctx.plate(node, ctx.mix(ink, paper, 0.5));
  // Regular-pattern check (Ofcom criteria, in analyse()): two colours, the cell size on screen, the
  // covered area and how it moves. An ordered dither at mid tones alternates every cell, so a
  // light-dark pair spans two cells. A changing noise field counts as changing; a field that moves
  // only with the camera flows; a still camera on a still field is stationary.
  const L1 = ctx.luminance(ink) * 100, L2 = ctx.luminance(paper) * 100;
  const scene = ctx.scene;
  ctx.film.patterns = ctx.film.patterns || [];
  ctx.film.patterns.push({
    id: o.id || `dither-${scene.index + 1}`, kind: 'dither',
    pattern(t, env) {
      if (!scene.active || node.alpha() < 0.02) return null;
      const M = env.cam.M, z = Math.sqrt(Math.abs(M[0] * M[3] - M[1] * M[2]));
      const pairs = Math.max(env.W, env.H) / (2 * cellPx * z);
      const area = Math.min(1, (cols * cellPx * z * rows * cellPx * z) / (env.W * env.H));
      return { pairs, dark_cdm2: Math.min(L1, L2), diff_cdm2: Math.abs(L1 - L2), area, changing: o.field === 'noise', motion: o.field === 'noise' ? 'changing' : o.still ? 'still' : undefined };
    },
  });

  let words = null;
  if (o.words) {
    const g = ctx.screenGroup.add({ name: 'dither-words' });
    const plateCol = ink;
    const lines = linesOf(ctx, o.words.text, o.words.tall);
    const lay = layoutLines(ctx, g, lines, { fill: 0.8, weight: 860, color: typeColour(ctx, plateCol, o.words.color) });
    const pad = u * 3;
    const back = g.add({ w: lay.width + pad * 2, h: lay.height + pad * 2 });
    back.el.style.cssText += `;width:${back.w}px;height:${back.h}px;background:${plateCol};`;
    g.el.insertBefore(back.el, g.el.firstChild);
    ctx.text({ id: o.words.id, role: o.words.role || 'headline', string: joinLines(lines), fact: o.words.fact, nodes: lay.nodes, bg: () => plateCol });
    words = g;
  }
  function camera(t) {
    return { x: o.still ? 0 : u * 6 * (t - ctx.t0), y: 0, zoom: o.still ? 1 : Math.exp(0.02 * (t - ctx.t0)), rot: 0, drift: false };
  }
  return { len, update() {}, camera, ground0: ink };
}, { assets: o => (o.field === 'image' && o.src ? [o.src] : []) });
