// Shared helpers for blocks: line layout in frame units, hits, colour choice and block definition.

// Define a block: a factory whose result the engine builds once and updates purely from t.
export function block(kind, build, extra = {}) {
  return (opts = {}) => ({ kind, opts, build: ctx => build(ctx, opts), ...(extra.assets ? { assets: () => extra.assets(opts) } : {}), ...(extra.inlineSvg ? { inlineSvg: extra.inlineSvg(opts) } : {}) });
}

// Split a text into lines: '/' or '\n' separate lines; `tall` gives the portrait breaks.
export function linesOf(ctx, text, tall) {
  const src = ctx.portrait && tall != null ? tall : text;
  return String(src).split(/\s*[\/\n]\s*/).filter(Boolean);
}
// The registered string: the lines joined by single spaces (what a reader reads).
export const joinLines = lines => lines.join(' ');

// Lay out display lines centred on the origin of `parent`, each fitted to the safe width
// (`justify`, the default) or all at one size (`uniform`). Returns nodes and the block's ink height.
export function layoutLines(ctx, parent, lines, o = {}) {
  const sw = ctx.safe[2] - ctx.safe[0], sh = ctx.safe[3] - ctx.safe[1];
  const n = lines.length;
  const gap = o.gap ?? 0.16;
  const maxH = o.maxH ?? Math.min(0.46, (0.86 / n) / (1 + gap));
  const nodes = lines.map(s => ctx.fitText(parent, {
    string: s, fill: o.fill ?? 0.92, maxH: (o.maxHPer ?? maxH) * (o.scaleFor ? o.scaleFor(s) : 1),
    weight: o.weight, width: o.width, tracking: o.tracking, font: o.font, minH: o.minH ?? 0.07,
    color: o.color, outline: o.outline, strokeColor: o.strokeColor, extrude: o.extrude, maxSize: o.maxSize,
  }));
  if (o.uniform) {
    const size = Math.min(...nodes.map(nd => nd.fontPx));
    nodes.forEach((nd, i) => { nd.el.remove(); nd.parent.children.splice(nd.parent.children.indexOf(nd), 1); });
    const again = lines.map(s => ctx.textNode(parent, { string: s, size, weight: o.weight ?? 820, width: o.width ?? (ctx.portrait ? 75 : 100), tracking: o.tracking ?? -0.02, color: o.color, outline: o.outline, strokeColor: o.strokeColor, extrude: o.extrude }));
    nodes.splice(0, nodes.length, ...again);
  }
  const caps = nodes.map(nd => nd.ink[3] - nd.ink[1]);
  const g = gap * Math.max(...caps);
  const total = caps.reduce((a, b) => a + b, 0) + g * (n - 1);
  let y = -total / 2 + (o.dy ?? 0);
  nodes.forEach((nd, i) => {
    nd.rest({ x: o.align === 'left' ? ctx.safe[0] - ctx.W / 2 + nd.w * 0 : 0, y: y + caps[i] / 2 });
    if (o.align === 'left') { nd.ax = 0; }
    y += caps[i] + g;
  });
  return { nodes, height: total, caps, width: Math.max(...nodes.map(nd => nd.w)) };
}

// The colour for type on a ground: an explicit colour, the accent when asked and legible, or the
// palette colour with the higher contrast.
export function typeColour(ctx, ground, want) {
  if (want === 'accent') {
    const a = ctx.pal.accent;
    return contrastOK(ctx, a, ground) ? a : ctx.typeOn(ground);
  }
  if (want) return ctx.colour(want);
  return ctx.typeOn(ground);
}
function contrastOK(ctx, a, g) {
  const la = ctx.luminance(a), lg = ctx.luminance(g);
  return (Math.max(la, lg) + 0.05) / (Math.min(la, lg) + 0.05) >= 3;
}

// Hits on a landing: none, beat (a camera bump), hit (bump + small shake), punch (speed lines charging
// in, then a ring, rays and sparks, a bigger bump and shake; for the biggest moments only).
export function hitAt(ctx, t, kind, o = {}) {
  if (!kind || kind === 'none') return;
  const colour = o.colour || ctx.pal.paper;
  if (kind === 'beat') ctx.bump(t, { amt: 0.03 });
  else if (kind === 'hit') { ctx.bump(t, { amt: 0.035 }); ctx.shake(t, { amp: 0.8, tau: 0.07 }); }
  else if (kind === 'punch') {
    // The biggest moments. Kept inside the flash limit by design: the charge is short, sparse, thin
    // accent lines (white lines converging over a dark ground swung third-of-frame windows many times
    // a second on a delivered file); one kick, no rattle.
    const at = o.at || (() => [ctx.W / 2, ctx.H / 2]);
    const charge = o.charge ?? 0.24;
    ctx.fx.speed({ t0: t - charge, t1: t, at, color: o.lines || ctx.pal.accent, count: 22, alpha: 0.6, seed: Math.round(t * 1000) });
    ctx.fx.burst({ t, at, color: o.burst || ctx.pal.accent, spark: o.spark || ctx.mix(colour, ctx.pal.accent, 0.5), rays: 6, alpha: 0.65, seed: Math.round(t * 977) });
    ctx.bump(t, { amt: 0.05, tau: 0.04 });
    ctx.shake(t, { amp: 1.1, tau: 0.08 });
    ctx.change(t - charge, t + 0.2, 'punch');
  }
}

export const cueRoleFor = { slam: 'impact', stack: 'impact', pair: 'impact', cut: 'hit', extrude: 'impact_big', outline: 'impact' };
