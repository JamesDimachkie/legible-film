// Picture: an image that pushes and pans (zoom in log space), words punched in on beats over a tint
// plate, and cut-ins to details (scale, focus point, cue). Warns when the source has fewer pixels
// than the frame width times the largest zoom.
//
// Picture({ src, from?: { focus: [0.5, 0.5], zoom: 1 }, to?: { focus, zoom: 1.15 }, len,
//           words?: [{ text, at, dur, role?, fact?, id? }], tint?: 'ink', tintAlpha?: 0.55,
//           details?: [{ at, focus, zoom, cue? }], label?: 'ILLUSTRATION' })

import { block, typeColour, hitAt, linesOf, joinLines, layoutLines } from './common.js';

export const Picture = block('picture', (ctx, o) => {
  const asset = ctx.env.images.get(o.src);
  if (!asset?.img) throw new Error(`Picture: ${o.src} was not loaded`);
  const iw = asset.width, ih = asset.height;
  const cover = Math.max(ctx.W / iw, ctx.H / ih);
  const w = iw * cover, h = ih * cover;
  const img = ctx.group.add({ name: 'picture', w, h });
  const el = asset.img;
  el.style.cssText = `display:block;width:${w}px;height:${h}px;`;
  img.el.appendChild(el);
  ctx.track(img, 'picture');
  const len = ctx.time(o.len ?? 3);
  const from = { focus: [0.5, 0.5], zoom: 1, ...(o.from || {}) };
  const to = { focus: from.focus, zoom: 1.12, ...(o.to || {}) };
  const details = (o.details || []).map(d => ({ ...d, t: ctx.t0 + ctx.time(d.at) })).sort((a, b) => a.t - b.t);
  const zmax = Math.max(from.zoom, to.zoom, ...details.map(d => d.zoom || 1));
  if (iw < ctx.W * zmax) ctx.warn(`Picture: ${o.src} is ${iw} px wide; at ${zmax.toFixed(2)}x it needs ${Math.ceil(ctx.W * zmax)} px to stay sharp at ${ctx.W} px`);
  const ground = ctx.colour(o.ground || 'ink');
  ctx.ground(ctx.t0, ground);

  // Tint plate for words (screen space, so a push never moves the words out of the safe area).
  const tintCol = ctx.colour(o.tint || 'ink');
  const tintA = o.tintAlpha ?? 0.58;
  const plate = ctx.screenGroup.add({ name: 'tint', w: ctx.W, h: ctx.H });
  plate.el.style.cssText += `;width:${ctx.W}px;height:${ctx.H}px;background:${tintCol};`;
  const words = (o.words || []).map((x, i) => {
    const g = ctx.screenGroup.add({ name: `pword-${i + 1}` });
    const lines = linesOf(ctx, x.text, x.tall);
    // Words over a picture: the plate is the ground they are read against.
    const plateOver = ctx.mix(tintCol, ctx.pal.mute, 0.15);
    const colour = typeColour(ctx, tintCol, x.color);
    const lay = layoutLines(ctx, g, lines, { fill: x.fill ?? 0.84, weight: 840, tracking: -0.025, color: colour });
    const at = ctx.t0 + ctx.time(x.at), dur = ctx.time(x.dur ?? (ctx.film.beat ? '2b' : 0.8));
    const string = joinLines(lines);
    // Contrast is checked against the plate over the brightest the picture could be (white).
    ctx.text({ id: x.id, role: x.role || 'headline', string, fact: x.fact, nodes: lay.nodes, bg: () => ctx.mix(tintCol, '#FFFFFF', 1 - tintA), readFrom: ctx.t0 + ctx.time(x.at) });
    ctx.change(ctx.t0 + ctx.time(x.at) - 0.06, ctx.t0 + ctx.time(x.at) + 0.05, `"${string}" punches in`);
    hitAt(ctx, at, x.hit ?? 'beat');
    ctx.cue({ t: at, role: x.cue || 'impact', sync: 'attack', picture: `"${string}" punches in over the picture` });
    return { g, lay, at, end: at + dur };
  });
  for (const d of details) {
    ctx.cut(d.t);
    if (d.cue !== false) ctx.cue({ t: d.t, role: d.cue || 'hit', sync: 'attack', picture: 'cut-in to a detail' });
  }
  let label = null;
  if (o.label) {
    label = ctx.textNode(ctx.screenGroup, { string: o.label, font: 'mono', size: ctx.u * 2.4, weight: 600, tracking: 0.12, color: ctx.pal.paper, anchor: [0, 1] });
    label.rest({ x: ctx.safe[0] - ctx.W / 2, y: ctx.safe[3] - ctx.H / 2 });
    ctx.text({ id: 'picture-label', role: 'qualifier', string: o.label, fact: o.labelFact, nodes: [label], bg: () => tintCol, readFrom: ctx.t0 });
  }

  function framing(t) {
    let seg = { t0: ctx.t0, t1: ctx.t0 + len, a: from, b: to };
    for (let i = 0; i < details.length; i++) {
      if (t >= details[i].t) {
        const d = details[i];
        const next = details[i + 1] ? details[i + 1].t : ctx.t0 + len;
        seg = { t0: d.t, t1: next, a: { focus: d.focus, zoom: d.zoom }, b: { focus: d.focus, zoom: (d.zoom || 1) * (d.push ?? 1.06) } };
      }
    }
    const p = ctx.curves.drift((t - seg.t0) / (seg.t1 - seg.t0));
    const f = [ctx.lerp(seg.a.focus[0], seg.b.focus[0], p), ctx.lerp(seg.a.focus[1], seg.b.focus[1], p)];
    const z = ctx.loglerp(seg.a.zoom || 1, seg.b.zoom || 1, p);
    return { f, z };
  }
  function update(t) {
    const any = words.find(x => t >= x.at - 0.001 && t < x.end);
    const q = any ? ctx.progress(t, any.at - 0.06, any.at) : 0;
    plate.opacity = any ? tintA * ctx.ease.fade(q) : 0;
    for (const x of words) x.g.opacity = t >= x.at && t < x.end ? 1 : 0;
  }
  function camera(t) {
    const { f, z } = framing(t);
    // Keep the frame covered: the focus point is clamped so no stage edge shows.
    const P = [(f[0] - 0.5) * w, (f[1] - 0.5) * h];
    const mx = Math.max(0, (w * z - ctx.W) / (2 * z)), my = Math.max(0, (h * z - ctx.H) / (2 * z));
    return { x: ctx.clamp(P[0], -mx, mx), y: ctx.clamp(P[1], -my, my), zoom: z, rot: 0, drift: false };
  }
  return { len, update, camera, ground0: ground };
}, { assets: o => [o.src] });
