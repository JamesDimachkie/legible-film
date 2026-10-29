// Name: the product's name out of depth in extruded type, with a light sweep across the face,
// a kicker above and a typed sub line below.
//
// Name({ name, kicker?, sub?, fact?, subFact?, kickerFact?, ground?, at?, hold?, depth?, sweep?: true })

import { block, typeColour, hitAt } from './common.js';

export const Name = block('name', (ctx, o) => {
  const ground = ctx.colour(o.ground || 'ink');
  ctx.ground(ctx.t0, ground);
  const colour = typeColour(ctx, ground, o.color);
  const accent = typeColour(ctx, ground, o.kickerColor || 'accent');
  const g = ctx.group.add({ name: 'name' });
  // Side colours from the palette: an accent face gets deep-accent sides; any other face, accent sides.
  const isAccent = colour === ctx.pal.accent;
  const near = isAccent ? ctx.mix(ctx.pal.accentDeep, ground, 0.15) : ctx.mix(ctx.pal.accent, ground, 0.1);
  const far = isAccent ? ctx.mix(ctx.pal.accentDeep, ground, 0.7) : ctx.mix(ctx.pal.accentDeep, ground, 0.6);
  const nameNode = ctx.fitText(g, {
    string: o.name, fill: o.fill ?? 0.9, maxH: 0.36, weight: o.weight ?? 880, width: o.width ?? (ctx.portrait ? 75 : 112.5), tracking: -0.02, color: colour,
    extrude: { depth: o.depth ?? 0.26, layers: 26, near, far, rx: 8, ry: -12 },
  });
  const cap = nameNode.ink[3] - nameNode.ink[1];
  const small = ctx.u * (ctx.portrait ? 5 : 4.3);
  let kNode = null, sNode = null;
  if (o.kicker) {
    kNode = ctx.textNode(g, { string: o.kicker, size: small, weight: 660, width: 112.5, tracking: 0.08, color: accent });
    kNode.rest({ y: -cap / 2 - small * 1.6 });
  }
  if (o.sub) {
    sNode = ctx.textNode(g, { string: o.sub, font: 'mono', size: small * 1.05, weight: 560, tracking: 0.02, color: o.subColor ? ctx.colour(o.subColor) : ctx.typeOn(ground) });
    sNode.rest({ y: cap / 2 + small * 1.7 });
  }
  // Light sweep: a soft band of light crossing the face once, after the landing.
  const face = nameNode.front;
  const sweepColour = ctx.mix(colour, '#FFFFFF', 0.85);
  if (o.sweep !== false) {
    face.style.backgroundImage = `linear-gradient(100deg, ${colour} 0%, ${colour} 40%, ${sweepColour} 50%, ${colour} 60%, ${colour} 100%)`;
    face.style.backgroundSize = '300% 100%';
    face.style.webkitBackgroundClip = 'text';
    face.style.backgroundClip = 'text';
    nameNode.clipText = true;
  }

  const land = ctx.t0 + ctx.time(o.at ?? 0.5);
  const fly = ctx.time(o.fly ?? 0.5);
  const kAt = Math.max(ctx.t0, land - ctx.time(o.kickerLead ?? 0.4));
  const subAt = land + ctx.time(o.subDelay ?? 0.3);
  const cps = o.cps ?? 18;
  const subEnd = sNode ? subAt + o.sub.length / cps : land;
  const sweep0 = land + 0.12, sweep1 = sweep0 + ctx.time(o.sweepDur ?? 0.9);
  const len = o.len != null ? ctx.time(o.len) : Math.max(subEnd, land) - ctx.t0 + ctx.time(o.hold ?? 1.5);
  ctx.text({ id: o.id || 'identity-name', role: 'identity', string: o.name, fact: o.fact, nodes: [nameNode], readFrom: land });
  if (kNode) ctx.text({ id: 'name-kicker', role: o.kickerRole || 'headline', string: o.kicker, fact: o.kickerFact, nodes: [kNode], readFrom: kAt + 0.18 });
  if (sNode) ctx.text({ id: 'name-sub', role: o.subRole || 'headline', string: o.sub, fact: o.subFact, nodes: [sNode], readFrom: subEnd });
  ctx.change(land - 0.15, land + 0.05, `${o.name} lands`);
  hitAt(ctx, land, o.hit ?? 'punch', { colour, at: () => ctx.screenOf(nameNode) });
  ctx.cue({ t: land, role: 'impact_big', sync: 'attack', picture: `${o.name} lands out of depth` });
  ctx.cue({ t: land - fly, role: 'riser', sync: 'end', sound: 'optional', picture: 'the name begins its flight', gain_db: -6 });
  // The kicker and the typed sub line ride on the landing's sound (a quiet cue 100 ms after an
  // impact was inaudible in the mix); a kicker well before the landing keeps its tick.
  if (kNode && land - kAt >= 0.3 && kAt - ctx.t0 >= 0.06) ctx.cue({ t: kAt, role: 'tick', sync: 'attack', gain_db: -5, picture: 'kicker appears' });

  function update(t) {
    const p = ctx.progress(t, land - fly, land);
    const e = ctx.ease.out4(p);
    nameNode.s = ctx.loglerp(0.06, 1, e);
    nameNode.ry = ctx.lerp(52, -12, e) - 14 * ctx.clamp((t - land) / 2.4);
    nameNode.rx = ctx.lerp(22, 8, e) - 5 * ctx.clamp((t - land) / 2.4);
    nameNode.opacity = t < land - fly ? 0 : ctx.ease.fade(Math.min(1, p * 5));
    // Before a fly-through, the face turns square to the camera so its counter is a true window.
    if (o.exit === 'through') {
      const flat = ctx.curves.camera(ctx.progress(t, ctx.t0 + len - 1.05, ctx.t0 + len - 0.6));
      nameNode.ry *= 1 - flat; nameNode.rx *= 1 - flat;
      nameNode.flat = t >= ctx.t0 + len - (o.flatFor ?? 0.35);
    }
    if (o.sweep !== false) {
      const q = ctx.curves.camera(ctx.progress(t, sweep0, sweep1));
      face.style.backgroundPosition = `${(100 - q * 100).toFixed(2)}% 0`;
    }
    if (kNode) {
      const q = ctx.progress(t, kAt, kAt + 0.18);
      kNode.opacity = ctx.ease.fade(q);
      kNode.y += (1 - ctx.curves.arrive(q)) * small * 0.6;
    }
    if (sNode) sNode.reveal = ctx.typed(sNode, Math.max(0, (ctx.locked(t) - subAt) * cps + 1e-6)).reveal;
  }
  // A steady push toward the fitted framing (never past it) keeps the hold alive while it is read.
  function camera(t) {
    const p = ctx.progress(t, ctx.t0, ctx.t0 + len - 0.55);
    return { x: 0, y: 0, zoom: ctx.loglerp(o.pushFrom ?? 0.98, 1.02, ctx.curves.drift(p)), rot: ctx.lerp(-1.4, 0.6, p), drift: false };
  }
  return { len, update, camera, ground0: ground, through: () => {
    // Prefer the roundest counter: O, then D, 0, Q, B, P, R, A.
    const order = o.throughLetter ? [o.throughLetter] : ['O', 'D', '0', 'Q', 'B', 'P', 'R', 'A', 'o', 'a', 'e'];
    const ls = nameNode.letters.map(l => l.textContent);
    for (const c of order) { const k = ls.indexOf(c); if (k >= 0) return { node: nameNode, letter: k }; }
    return { node: nameNode, letter: 0 };
  } };
});
