// EndCard: a logo (a safe SVG, drawn as an <img> unless it must be inlined) or a typed wordmark,
// a tagline and a practical line (an address, "available now"), held readable and declared as a rest.
// A slow push; a sting cue whose default gain keeps it near the body's level (a sting louder
// than the film over a stopped bed was heard as jarring); exports where the music stops.
//
// EndCard({ logo?: 'logo.svg', logoHeight?, wordmark?, tagline?, line?, wordmarkFact?, taglineFact?, lineFact?,
//           taglineRole?, ground?, hold?, len?, musicStop?: true, stingGain?: -6 })

import { block, typeColour } from './common.js';
import { sanitizeSvg } from '../lf/svg.js';

export const EndCard = block('endcard', (ctx, o) => {
  const ground = ctx.colour(o.ground || 'paper');
  ctx.ground(ctx.t0, ground);
  const colour = typeColour(ctx, ground, o.color);
  const accent = typeColour(ctx, ground, 'accent');
  const mute = ctx.mix(colour, ground, 0.35);
  const g = ctx.group.add({ name: 'endcard' });
  const u = ctx.u;
  const items = [];
  let logoNode = null, wordNode = null;
  if (o.logo) {
    const asset = ctx.env.images.get(o.logo);
    const hgt = (o.logoHeight ?? (ctx.portrait ? 0.1 : 0.14)) * ctx.H;
    if (asset?.svgText) {
      const { svg, removed } = sanitizeSvg(asset.svgText);
      if (removed.length) ctx.warn(`EndCard: removed unsafe parts from ${o.logo}: ${removed.join(', ')}`);
      const vb = (svg.getAttribute('viewBox') || '0 0 100 100').split(/[\s,]+/).map(Number);
      const w = (hgt * vb[2]) / vb[3];
      svg.setAttribute('width', w); svg.setAttribute('height', hgt);
      logoNode = g.add({ name: 'logo', w, h: hgt });
      logoNode.el.appendChild(svg);
    } else if (asset?.img) {
      const w = (hgt * asset.width) / asset.height;
      logoNode = g.add({ name: 'logo', w, h: hgt });
      const img = asset.img;
      img.style.cssText = `display:block;width:${w}px;height:${hgt}px;`;
      logoNode.el.appendChild(img);
    }
    if (logoNode) ctx.track(logoNode, 'logo');
    if (logoNode) items.push({ node: logoNode, h: hgt, gap: u * 3.5 });
  }
  if (o.wordmark) {
    wordNode = ctx.fitText(g, { string: o.wordmark, fill: o.wordmarkFill ?? (ctx.portrait ? 0.86 : 0.64), maxH: 0.32, weight: 820, width: ctx.portrait ? 87.5 : 100, tracking: -0.035, color: colour });
    items.push({ node: wordNode, h: wordNode.ink[3] - wordNode.ink[1], gap: u * 6 });
  }
  const small = u * (ctx.portrait ? 5.6 : 4.8);
  let tagNode = null, lineNode = null;
  if (o.tagline) {
    tagNode = ctx.textNode(g, { string: o.tagline, size: small * 1.2, weight: 760, width: 112.5, tracking: 0.06, color: accent });
    items.push({ node: tagNode, h: tagNode.ink[3] - tagNode.ink[1], gap: u * 3.4 });
  }
  if (o.line) {
    lineNode = ctx.textNode(g, { string: o.line, font: 'mono', size: small, weight: 520, tracking: 0, color: colour });
    items.push({ node: lineNode, h: lineNode.ink[3] - lineNode.ink[1], gap: 0 });
  }
  const total = items.reduce((a, it, i) => a + it.h + (i < items.length - 1 ? it.gap : 0), 0);
  let y = -total / 2;
  for (const it of items) { it.node.rest({ y: y + it.h / 2 }); y += it.h + it.gap; }
  if (logoNode) logoNode.ay = 0.5;

  const hit = ctx.t0 + ctx.time(o.at ?? (o.typed === false ? 0.24 : 0.1));
  const cps = o.cps ?? 16;
  const typeEnd = wordNode && o.typed !== false ? hit + o.wordmark.length / cps : hit;
  const lockAt = wordNode && o.typed !== false ? typeEnd : hit;
  const tagAt = lockAt + ctx.time(o.tagDelay ?? 0.25);
  const lineAt = tagAt + ctx.time(o.lineDelay ?? 0.3);
  const lastIn = (lineNode ? lineAt : tagNode ? tagAt : lockAt) + 0.25;
  const len = o.len != null ? ctx.time(o.len) : lastIn - ctx.t0 + ctx.time(o.hold ?? 2.6);
  const end = ctx.t0 + len;
  if (wordNode) ctx.text({ id: 'identity-wordmark', role: 'identity', string: o.wordmark, fact: o.wordmarkFact, nodes: [wordNode], readFrom: lockAt });
  if (tagNode) ctx.text({ id: 'endcard-tagline', role: o.taglineRole || 'claim', string: o.tagline, fact: o.taglineFact, nodes: [tagNode], readFrom: tagAt + 0.22 });
  if (lineNode) ctx.text({ id: 'endcard-line', role: o.lineRole || 'claim', string: o.line, fact: o.lineFact, nodes: [lineNode], readFrom: lineAt + 0.22 });
  if (wordNode || logoNode) ctx.change(Math.min(hit - 0.12, ctx.t0), hit + 0.05, 'the mark lands');
  ctx.cue({ id: 'sting', t: lockAt, role: 'sting', sync: 'attack', gain_db: o.stingGain ?? -6, duck_db: 0, picture: 'the mark locks' });
  // The tagline and line ride on the sting's ring-out (a tick inside it was inaudible). The
  // silent window starts after the ring-out (o.ringOut, 1.6 s by default) so it guards new sounds only.
  const quiet0 = lockAt + (o.ringOut ?? 1.6), quiet1 = end - 0.15;
  if (quiet1 - quiet0 > 0.2) ctx.cue({ id: 'end-read', t: +((quiet0 + quiet1) / 2).toFixed(6), sound: 'silent', window_ms: Math.round(((quiet1 - quiet0) / 2) * 1000), picture: 'the end card is read: no new sound' });
  ctx.rest(lockAt, end, 'end card');
  if (o.musicStop !== false) ctx.music({ stop: +lockAt.toFixed(6) });
  ctx.bump(lockAt, { amt: 0.02, tau: 0.05 });

  function update(t) {
    if (logoNode) {
      const q = ctx.progress(t, hit - 0.12, hit);
      logoNode.opacity = ctx.ease.fade(q);
      logoNode.s = ctx.loglerp(1.25, 1, ctx.curves.land(q));
    }
    if (wordNode) {
      if (o.typed !== false) wordNode.reveal = ctx.typed(wordNode, ctx.locked(t) < hit ? 0 : (ctx.locked(t) - hit) * cps + 1 + 1e-6).reveal;
      else {
        // Slams in: scale and blur into the contact frame, then holds.
        // The landing starts on the card's first frame, so the arrival is never an empty card.
        const s0 = Math.min(hit - 0.08, ctx.t0);
        const q = ctx.progress(t, s0, hit);
        wordNode.opacity = t < s0 ? 0 : ctx.ease.fade(Math.min(1, q * 3));
        if (t < hit) { const e = ctx.curves.land(q); wordNode.s = ctx.loglerp(1.35, 1, e); wordNode.blur = (1 - e) * u * 1.2; }
      }
    }
    for (const [n, at] of [[tagNode, tagAt], [lineNode, lineAt]]) {
      if (!n) continue;
      const q = ctx.progress(t, at, at + 0.22);
      n.opacity = ctx.ease.fade(q);
      n.y += (1 - ctx.curves.arrive(q)) * small * 0.5;
    }
  }
  function camera(t) {
    return { x: 0, y: 0, zoom: Math.exp(0.018 * (t - ctx.t0)), rot: 0, drift: false };
  }
  return { len, update, camera, ground0: ground };
}, { assets: o => (o.logo ? [o.logo] : []), inlineSvg: o => !!o.inlineLogo });
