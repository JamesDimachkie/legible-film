// Caption: a running caption line that carries the whole sentence in small type while the display
// words cut, with the current word highlighted. Exported as SRT and WebVTT (film_check.py) from the
// same source as the picture. Put it in the spec as `captions: Caption({...})`; it lives in screen
// space above the film, on a plate so it reads on every ground.
//
// Caption({ sentences: [{ text, t0, t1, words?: [[word, t], ...] }], size?, plate?: true, position?: 'bottom' })

import { block } from './common.js';
import { over } from '../lf/color.js';

export const Caption = block('caption', (ctx, o) => {
  const pal = ctx.pal, u = ctx.u;
  const size = o.size ?? u * (ctx.portrait ? 4.2 : 3.8);
  const sw = ctx.safe[2] - ctx.safe[0];
  const plateCol = o.plateColour ? ctx.colour(o.plateColour) : pal.deep;
  const plateAlpha = o.plate === false ? 0 : o.plateAlpha ?? 0.82;
  const on = pal.paper, off = ctx.mix(pal.paper, plateCol, 0.42);
  const items = [];
  for (const [k, s] of (o.sentences || []).entries()) {
    const t0 = ctx.time(s.t0), t1 = ctx.time(s.t1);
    const words = s.text.split(/\s+/).filter(Boolean);
    let times = s.words ? s.words.map(w => ctx.time(w[1])) : null;
    if (!times) {
      // Spread the words over the sentence by length, finishing a little before it leaves.
      const L = words.reduce((a, w) => a + w.length + 1, 0);
      let acc = 0;
      times = words.map(w => { const tt = t0 + ((t1 - t0) * 0.8 * acc) / L; acc += w.length + 1; return tt; });
    }
    // One line, or two balanced lines when it would not fit.
    const st = { font: 'text', size, weight: 600, width: 100, tracking: 0.005, lineHeight: 1.25 };
    const full = ctx.measure(s.text, st).w;
    let lines = [words];
    if (full > sw * 0.88) {
      let best = 1, bestD = Infinity;
      for (let i = 1; i < words.length; i++) {
        const a = ctx.measure(words.slice(0, i).join(' '), st).w, b = ctx.measure(words.slice(i).join(' '), st).w;
        if (Math.abs(a - b) < bestD) { bestD = Math.abs(a - b); best = i; }
      }
      lines = [words.slice(0, best), words.slice(best)];
    }
    const g = ctx.group.add({ name: `caption-${k + 1}` });
    const nodes = lines.map(ws => ctx.textNode(g, { ...st, string: ws.join(' '), color: off }));
    const lh = size * 1.3;
    const maxW = Math.max(...nodes.map(n => n.w));
    const padX = size * 0.7, padY = size * 0.45;
    const plate = g.add({ name: 'plate', w: maxW + padX * 2, h: lh * nodes.length + padY * 2 - (lh - size) });
    plate.el.style.cssText += `;width:${plate.w}px;height:${plate.h}px;border-radius:${size * 0.35}px;background:${plateCol};`;
    g.el.insertBefore(plate.el, g.el.firstChild);
    plate.rest({ opacity: plateAlpha });
    const bottom = ctx.safe[3] - (o.lift ?? size * 0.4);
    const y0 = bottom - plate.h / 2;
    g.rest({ x: ctx.W / 2, y: y0 });
    nodes.forEach((n, i) => n.rest({ y: (i - (nodes.length - 1) / 2) * lh }));
    const bg = t => (plateAlpha > 0 ? overGround(ctx, ctx.film.groundAt(t), plateCol, plateAlpha) : ctx.film.groundAt(t));
    ctx.text({ id: s.id || `caption-${k + 1}`, role: 'caption', string: s.text, nodes, bg });
    // Word index per line for highlighting.
    let idx = 0;
    const map = lines.map(ws => ws.map(() => idx++));
    nodes.forEach((n, li) => {
      let prev = null;
      n.onFlushExtra = nn => {
        const cur = nn.extra;
        if (cur === prev) return;
        prev = cur;
        n.wordEls.forEach((we, wi) => { we.style.color = map[li][wi] === cur ? on : ''; });
      };
      const base = n.onFlush;
      n.onFlush = nn => { base(nn); nn.onFlushExtra(nn); };
    });
    items.push({ g, nodes, t0, t1, times, words });
    ctx.caption({ t0: +t0.toFixed(6), t1: +t1.toFixed(6), text: s.text, words: words.map((w, i) => [w, +times[i].toFixed(6)]) });
  }
  function update(t) {
    for (const it of items) {
      const vis = t >= it.t0 && t < it.t1;
      it.g.opacity = vis ? 1 : 0;
      if (!vis) continue;
      let cur = -1;
      for (let i = 0; i < it.times.length; i++) if (ctx.locked(t) >= it.times[i]) cur = i;
      for (const n of it.nodes) n.extra = cur;
    }
  }
  return { len: 0.001, update };
});

// The plate composited over the ground in linear light, as the screen shows it.
function overGround(ctx, ground, plate, a) {
  return over(ground, plate, a);
}
