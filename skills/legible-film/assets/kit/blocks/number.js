// Number: a large number lands with its label; the value comes from a fact, never typed here.
// It lands by a cut, a slam, or digit by digit (each digit arriving already final). It never rolls or
// counts through values that were not measured. Unit, label and any qualifier sit beside it.
//
// Number({ fact, land?: 'slam' | 'cut' | 'digits', label?, qualifier?: true, at?, hold?, ground?, hit? })
// The displayed value is the fact's `display`; the qualifier is its `label_beside_value`.

import { block, typeColour, hitAt } from './common.js';

export const Number_ = block('number', (ctx, o) => {
  const f = ctx.fact(o.fact);
  if (!f) throw new Error(`Number: fact "${o.fact}" is not in the facts file`);
  const value = Array.isArray(f.display) ? f.display[o.displayIndex ?? 0] : f.display;
  if (!value) throw new Error(`Number: fact "${o.fact}" has no display string`);
  const ground = ctx.colour(o.ground || 'ink');
  ctx.ground(ctx.t0, ground);
  const colour = typeColour(ctx, ground, o.color);
  const accent = typeColour(ctx, ground, 'accent');
  const g = ctx.group;
  const valueNode = ctx.fitText(g, { string: value, fill: o.fill ?? 0.7, maxH: 0.5, weight: 860, tracking: -0.03, color: colour });
  const capV = valueNode.ink[3] - valueNode.ink[1];
  const small = ctx.u * (ctx.portrait ? 5 : 4.4);
  let labelNode = null, qualNode = null;
  if (o.label) {
    labelNode = ctx.textNode(g, { string: o.label, size: small, weight: 640, width: 112.5, tracking: 0.04, color: colour });
    labelNode.rest({ y: capV / 2 + small * 1.3 });
  }
  if (o.qualifier && f.label_beside_value) {
    qualNode = ctx.textNode(g, { string: f.label_beside_value, size: small * 0.82, weight: 560, width: 100, tracking: 0.02, color: accent, anchor: [0, 0.5] });
    qualNode.rest({ x: valueNode.w / 2 + small * 0.8, y: -capV / 2 + small * 0.5 });
    if (qualNode.x + qualNode.w > ctx.safe[2] - ctx.W / 2) { qualNode.ax = 0.5; qualNode.rest({ x: 0, y: (labelNode ? labelNode.y : capV / 2) + small * 1.5 }); }
  }
  const blockH = capV + (labelNode ? small * 2 : 0) + (qualNode && qualNode.ax === 0.5 ? small * 1.5 : 0);
  for (const n of [valueNode, labelNode, qualNode]) if (n) n.rest({ y: n.y - (blockH - capV) / 2 });

  const land = ctx.t0 + ctx.time(o.at ?? 0.12);
  const style = o.land || 'slam';
  const digits = valueNode.letters.length;
  const step = ctx.time(o.step ?? 0.07);
  const done = style === 'digits' ? land + (digits - 1) * step : land;
  ctx.text({ id: o.id || `claim-${o.fact}`, role: 'claim', string: value, fact: o.fact, nodes: [valueNode] });
  if (labelNode) ctx.text({ id: `${o.id || o.fact}-label`, role: o.labelRole || 'headline', string: o.label, fact: o.fact, nodes: [labelNode] });
  if (qualNode) ctx.text({ id: `${o.id || o.fact}-qualifier`, role: 'qualifier', string: f.label_beside_value, fact: o.fact, nodes: [qualNode] });
  hitAt(ctx, done, o.hit ?? 'hit', { colour, at: () => ctx.screenOf(valueNode) });
  ctx.cue({ t: done, role: 'impact', sync: 'attack', picture: `${value} lands` });
  if (style === 'digits') for (let i = 0; i < digits - 1; i++) ctx.cue({ t: land + i * step, role: 'tick', sync: 'attack', gain_db: -8, picture: `digit ${i + 1} arrives` });
  const labelAt = done + ctx.time(o.labelDelay ?? 0.18);
  const len = o.len != null ? ctx.time(o.len) : labelAt - ctx.t0 + ctx.time(o.hold ?? 1.8);

  function update(t) {
    if (style === 'slam') {
      const t0 = land - 0.1;
      if (t < land) {
        const p = ctx.progress(t, t0, land);
        const e = ctx.curves.slam(p);
        valueNode.s = ctx.loglerp(2.2, 1, e);
        valueNode.blur = (1 - e) * ctx.u * 1.6;
        valueNode.opacity = t < t0 ? 0 : ctx.ease.fade(Math.min(1, p * 2.5));
      }
    } else if (style === 'cut') {
      valueNode.opacity = t >= land ? 1 : 0;
    } else {
      const lt = ctx.locked(t);
      valueNode.reveal = lt < land ? 0 : Math.floor((lt - land) / step + 1e-6) + 1;
    }
    for (const n of [labelNode, qualNode]) {
      if (!n) continue;
      const q = ctx.progress(t, labelAt, labelAt + 0.2);
      n.opacity = ctx.ease.fade(q);
      n.y += (1 - ctx.curves.arrive(q)) * small * 0.5;
    }
  }
  return { len, update, ground0: ground };
});
