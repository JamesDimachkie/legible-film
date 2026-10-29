// Without: a denial, "NO X.", over a simple drawn mock of the old way (bars of a timeline, tiles,
// rows of a rack) that then breaks apart. The denial is a claim and needs a fact. The pieces clear the
// centre before the denial settles, so the words never sit on a busy picture.
//
// Without({ text: 'NO CLOUD.', fact, mock: 'timeline' | 'tiles' | 'rack', breakAt?: '2b', hold?, ground?, seed? })

import { block, typeColour, hitAt } from './common.js';

export const Without = block('without', (ctx, o) => {
  if (!o.fact) ctx.warn(`Without: "${o.text}" is a claim and needs a fact id`);
  const pal = ctx.pal, u = ctx.u;
  const ground = ctx.colour(o.ground || 'ink');
  ctx.ground(ctx.t0, ground);
  const dark = ctx.luminance(ground) < 0.3;
  const R = ctx.rng(o.seed ?? 19);
  const mockG = ctx.group.add({ name: 'mock' });
  const sw = ctx.safe[2] - ctx.safe[0], sh = ctx.safe[3] - ctx.safe[1];
  const mw = sw * (ctx.portrait ? 0.95 : 0.78), mh = sh * (ctx.portrait ? 0.5 : 0.66);
  const fillA = dark ? ctx.mix(pal.panel, pal.paper, 0.08) : pal.mist;
  const fillB = dark ? ctx.mix(pal.rule, pal.accent, 0.25) : ctx.mix(pal.mist, pal.accent, 0.25);
  const pieces = [];
  const piece = (x, y, w, h, colour, r) => {
    const n = mockG.add({ w, h });
    n.el.style.cssText += `;width:${w}px;height:${h}px;border-radius:${r ?? u * 0.4}px;background:${colour};`;
    n.rest({ x, y });
    const a = Math.atan2(y, x) + (R() - 0.5) * 0.9;
    pieces.push({ n, vx: Math.cos(a) * (0.9 + R()) * ctx.W, vy: Math.sin(a) * (0.6 + R()) * ctx.H - ctx.H * 0.4, w: (R() - 0.5) * 520, d: R() * 0.06 });
    return n;
  };
  const kind = o.mock || 'timeline';
  if (kind === 'timeline') {
    const rows = 5, rh = mh / rows;
    for (let r = 0; r < rows; r++) {
      let x = -mw / 2;
      while (x < mw / 2 - u * 4) {
        const w = Math.min(mw / 2 - x, (0.08 + R() * 0.24) * mw);
        piece(x + w / 2, -mh / 2 + rh * (r + 0.5), w - u * 0.6, rh * 0.72, r % 2 ? fillA : fillB);
        x += w;
      }
    }
    piece(-mw * 0.18, 0, u * 0.35, mh * 1.08, pal.accent, 0);   // the playhead
  } else if (kind === 'tiles') {
    const cols = ctx.portrait ? 3 : 5, rows = ctx.portrait ? 4 : 3;
    const tw = mw / cols, th = mh / rows;
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) piece(-mw / 2 + tw * (c + 0.5), -mh / 2 + th * (r + 0.5), tw - u * 1.2, th - u * 1.2, (r + c) % 3 ? fillA : fillB, u * 0.9);
  } else {
    const rows = 7, rh = mh / rows;
    for (let r = 0; r < rows; r++) {
      piece(0, -mh / 2 + rh * (r + 0.5), mw * 0.62, rh * 0.8, fillA, u * 0.3);
      for (let k = 0; k < 3; k++) piece(-mw * 0.25 + k * u * 1.6, -mh / 2 + rh * (r + 0.5), u * 0.8, u * 0.8, k === 0 ? pal.success : fillB, u);
    }
  }
  pieces.slice(0, 3).forEach((p, i) => ctx.track(p.n, `without-piece-${i + 1}`));
  const colour = typeColour(ctx, ground, o.color);
  const word = ctx.fitText(ctx.group, { string: o.text, fill: 0.9, maxH: 0.4, weight: 880, tracking: -0.03, color: colour });

  const breakAt = ctx.t0 + ctx.time(o.breakAt ?? (ctx.film.beat ? '3b' : 1.2));
  const land = breakAt + ctx.time(o.landDelay ?? 0.12);
  const len = o.len != null ? ctx.time(o.len) : land - ctx.t0 + ctx.time(o.hold ?? 1.6);
  ctx.text({ id: o.id || `claim-${o.fact || 'without'}`, role: 'claim', string: o.text, fact: o.fact, nodes: [word] });
  ctx.cue({ t: breakAt, role: 'glitch', sync: 'attack', picture: 'the old way breaks apart' });
  ctx.cue({ t: land, role: 'impact', sync: 'attack', picture: `"${o.text}" lands` });
  hitAt(ctx, breakAt, 'hit');
  // The pieces fly fast: give the render motion blur over the break so they never strobe.
  ctx.fast(breakAt, breakAt + 0.45, 12);
  ctx.smear(breakAt, breakAt + 0.4, 2);
  hitAt(ctx, land, 'beat');
  const tok = ctx.token('arrive', 'large', 0.1);

  function update(t) {
    const q = ctx.progress(t, ctx.t0, ctx.t0 + tok.d * 1.4);
    mockG.opacity = ctx.ease.fade(q);
    mockG.s = ctx.lerp(0.94, 1, tok.curve(q));
    // A slow drift sideways, as if the old timeline were still playing.
    mockG.x = -u * 2.5 * (t - ctx.t0);
    for (const p of pieces) {
      const dt = t - breakAt - p.d;
      if (dt <= 0) continue;
      p.n.x += p.vx * dt * 0.6;
      p.n.y += p.vy * dt * 0.6 + 0.5 * ctx.H * 3.2 * dt * dt;
      p.n.rot = p.w * dt;
      p.n.opacity = 1 - ctx.clamp(dt / 0.42);
    }
    const p = ctx.progress(t, land - 0.1, land);
    if (t < land) {
      const e = ctx.curves.slam(p);
      word.s = ctx.loglerp(2, 1, e);
      word.blur = (1 - e) * u * 1.6;
      word.opacity = t < land - 0.1 ? 0 : ctx.ease.fade(Math.min(1, p * 2.5));
    }
  }
  return { len, update, ground0: ground };
});
