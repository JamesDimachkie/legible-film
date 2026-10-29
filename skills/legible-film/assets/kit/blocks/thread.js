// Thread: two to four nodes joined by the tracer. The camera rides the thread from node to node,
// then pulls back to show the whole chain. The thread connects only what the spec says is connected.
//
// Thread({ nodes: [{ label, sub?, role?, fact?, id? }], links?: [[0, 1], [1, 2]], hop?: '2b', ground?,
//         ride?: 1.5, pullback?: '2b', hold?: '2b' })

import { block, typeColour } from './common.js';

export const Thread = block('thread', (ctx, o) => {
  const items = o.nodes || [];
  if (items.length < 2 || items.length > 4) throw new Error('Thread takes two to four nodes');
  const links = o.links || items.slice(1).map((_, i) => [i, i + 1]);
  for (const [a, b] of links) if (!items[a] || !items[b]) throw new Error(`Thread link ${a}-${b} names a node that does not exist`);
  const pal = ctx.pal, u = ctx.u;
  const ground = ctx.colour(o.ground || 'ink');
  ctx.ground(ctx.t0, ground);
  const dark = ctx.luminance(ground) < 0.3;
  const card = dark ? pal.panel : pal.soft;
  const ink = typeColour(ctx, card);
  const accent = pal.accent;
  const vertical = ctx.portrait;
  const sw = ctx.safe[2] - ctx.safe[0], sh = ctx.safe[3] - ctx.safe[1];
  const n = items.length;
  const fs = u * (o.size ?? (vertical ? 7 : 6.2));
  const nodes = items.map((it, i) => {
    const g = ctx.group.add({ name: `thread-${i + 1}` });
    const label = ctx.textNode(g, { string: it.label, size: fs, weight: 800, width: 100, tracking: -0.02, color: ink });
    let sub = null;
    if (it.sub) sub = ctx.textNode(g, { string: it.sub, font: 'mono', size: fs * 0.42, weight: 500, color: ctx.mix(ink, card, 0.3) });
    const w = Math.max(label.w, sub ? sub.w : 0) + fs * 1.3;
    const h = (label.ink[3] - label.ink[1]) + (sub ? fs * 0.75 : 0) + fs * 1.1;
    const box = g.add({ name: 'card', w, h });
    box.el.style.cssText += `;width:${w}px;height:${h}px;border-radius:${fs * 0.28}px;background:${card};box-shadow:inset 0 0 0 ${Math.max(1, u * 0.18)}px ${ctx.mix(card, accent, 0.5)};`;
    g.el.insertBefore(box.el, g.el.firstChild);
    label.rest({ y: sub ? -fs * 0.32 : 0 });
    if (sub) sub.rest({ y: fs * 0.52 });
    ctx.plate(box, card);
    ctx.track(box, `thread-node-${i + 1}`);
    return { g, label, sub, box, w, h, it };
  });
  // Lay out along a line with equal gaps; a tall frame stacks them.
  const along = vertical ? nodes.map(x => x.h) : nodes.map(x => x.w);
  const gap = Math.max(fs * 1.8, ((vertical ? sh : sw) - along.reduce((a, b) => a + b, 0)) / (n - 1) * 0.6);
  const total = along.reduce((a, b) => a + b, 0) + gap * (n - 1);
  let p = -total / 2;
  nodes.forEach((x, i) => {
    const c = p + along[i] / 2;
    x.g.rest(vertical ? { x: 0, y: c } : { x: c, y: 0 });
    x.pos = vertical ? [0, c] : [c, 0];
    p += along[i] + gap;
  });
  const fitZoom = Math.min(1, (sw * 0.96) / (vertical ? Math.max(...nodes.map(x => x.w)) : total), (sh * 0.94) / (vertical ? total : Math.max(...nodes.map(x => x.h))));

  // Timing: the first node is there; each link launches a tracer and the target node arrives with it.
  const hop = ctx.time(o.hop ?? (ctx.film.beat ? '2b' : 0.8));
  const start = ctx.t0 + ctx.time(o.lead ?? 0.35);
  const arrive = new Array(n).fill(null);
  arrive[links[0][0]] = ctx.t0 + 0.05;
  const tracers = links.map(([a, b], k) => {
    const t0 = start + k * hop, t1 = t0 + hop * 0.72;
    if (arrive[b] == null) arrive[b] = t1;
    if (arrive[a] == null) arrive[a] = t0;
    const edge = (x, towards) => {
      const d = vertical ? Math.sign(towards[1] - x.pos[1]) : Math.sign(towards[0] - x.pos[0]);
      return vertical ? [x.pos[0], x.pos[1] + d * x.h / 2] : [x.pos[0] + d * x.w / 2, x.pos[1]];
    };
    const A = edge(nodes[a], nodes[b].pos), B = edge(nodes[b], nodes[a].pos);
    const mid = [(A[0] + B[0]) / 2 + (vertical ? fs * 0.9 : 0), (A[1] + B[1]) / 2 + (vertical ? 0 : -fs * 0.9)];
    const quad = f => [(1 - f) * (1 - f) * A[0] + 2 * (1 - f) * f * mid[0] + f * f * B[0], (1 - f) * (1 - f) * A[1] + 2 * (1 - f) * f * mid[1] + f * f * B[1]];
    const path = () => Array.from({ length: 17 }, (_, j) => quad(j / 16)).map(q => ctx.worldOf(ctx.group, q[0], q[1]));
    const tracer = ctx.fx.tracer({ t0, t1, path, color: accent, core: ctx.mix(accent, '#FFFFFF', 0.7), width: 0.55, tail: 0.45, drain: 0.28, keep: true, keepAlpha: 0.6 });
    ctx.cue({ t: (t0 + t1) / 2, role: 'whoosh', sync: 'apex', gain_db: -6, picture: `thread runs from ${items[a].label} to ${items[b].label} (peak speed)` });
    ctx.cue({ t: t1, role: 'pop', sync: 'attack', gain_db: -3, picture: `${items[b].label} is reached` });
    return { a, b, t0, t1, tracer, A, B, mid };
  });
  const lastArrive = Math.max(...arrive);
  const pull0 = lastArrive + ctx.time(o.settle ?? 0.25);
  const pull1 = pull0 + ctx.time(o.pullback ?? (ctx.film.beat ? '2b' : 0.8));
  const len = o.len != null ? ctx.time(o.len) : pull1 - ctx.t0 + ctx.time(o.hold ?? (ctx.film.beat ? '3b' : 1.2));
  // Kept threads stay drawn until the scene ends, never into the next one.
  for (const c of tracers) c.tracer.until = ctx.t0 + len;
  nodes.forEach((x, i) => {
    ctx.text({ id: x.it.id || `thread-${i + 1}`, role: x.it.role || 'headline', string: x.it.label, fact: x.it.fact, nodes: [x.label], bg: () => card });
    if (x.sub) ctx.text({ id: `${x.it.id || `thread-${i + 1}`}-sub`, role: x.it.subRole || 'headline', string: x.it.sub, fact: x.it.subFact, nodes: [x.sub], bg: () => card });
  });
  const tok = ctx.token('arrive', 'medium', 0.05);

  function update(t) {
    nodes.forEach((x, i) => {
      const q = ctx.progress(t, arrive[i] - tok.d * 0.25, arrive[i] + tok.d * 0.75);
      x.g.opacity = t < arrive[i] - tok.d * 0.25 ? 0 : ctx.ease.fade(Math.min(1, q * 1.5));
      x.g.s = ctx.lerp(0.86, 1, tok.curve(q));
    });
  }
  // Ride the tracer head; between hops hold on the node just reached; then pull back to show the whole.
  const ride = o.ride ?? 1.45;
  function headPoint(t) {
    let pt = nodes[links[0][0]].pos;
    for (const c of tracers) {
      if (t < c.t0) break;
      const h = c.tracer.head(Math.min(t, c.t1));
      // The camera rides a centre-to-centre curve beside the thread, so a hand-off never jumps.
      const pa = nodes[c.a].pos, pb = nodes[c.b].pos;
      const pts = [pa, [c.mid[0] + (pa[0] + pb[0]) / 2 - (c.A[0] + c.B[0]) / 2, c.mid[1] + (pa[1] + pb[1]) / 2 - (c.A[1] + c.B[1]) / 2], pb];
      const f = h;
      const q1 = [pts[0][0] + (pts[1][0] - pts[0][0]) * f, pts[0][1] + (pts[1][1] - pts[0][1]) * f];
      const q2 = [pts[1][0] + (pts[2][0] - pts[1][0]) * f, pts[1][1] + (pts[2][1] - pts[1][1]) * f];
      pt = [q1[0] + (q2[0] - q1[0]) * f, q1[1] + (q2[1] - q1[1]) * f];
      if (t >= c.t1) pt = nodes[c.b].pos;
    }
    return pt;
  }
  // The camera eases toward the head rather than locking to it, so it never jerks at a hand-off.
  function camera(t) {
    const k = 0.09;
    const h0 = headPoint(t), h1 = headPoint(t - k), h2 = headPoint(t - 2 * k);
    const P = [(h0[0] * 2 + h1[0] + h2[0]) / 4, (h0[1] * 2 + h1[1] + h2[1]) / 4];
    const zr = Math.min(ride, (sw * 0.9) / Math.max(...nodes.map(x => x.w)) * 0.75);
    const q = ctx.curves.camera(ctx.progress(t, pull0, pull1));
    const intro = ctx.curves.camera(ctx.progress(t, ctx.t0, start + 0.1));
    const zoom = ctx.loglerp(ctx.loglerp(zr * 0.92, zr, intro), fitZoom, q) * Math.exp(0.01 * (t - ctx.t0));
    const C = [ctx.lerp(P[0], 0, q), ctx.lerp(P[1], 0, q)];
    return { x: C[0], y: C[1], zoom, rot: (1 - q) * 0.8 * Math.sin((t - ctx.t0) * 0.9), drift: false };
  }
  return { len, update, camera, ground0: ground };
});
