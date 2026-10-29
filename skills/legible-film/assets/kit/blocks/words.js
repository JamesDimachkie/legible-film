// Words: the kinetic-type sequencer. One idea per beat or half beat; each shot lands on its time.
//
// Words({ shots: [{ text, tall?, dur, style, kicker?, ground?, color?, enter?, hit?, role?, fact?, id?,
//                   fill?, weight?, width?, tracking?, fillAt?, rot?, cue?, pulse?, drop? }],
//         exit?: 'cut' | 'through' | 'collapse', through?: { letter: 'O' | index, shot? }, maxPerSecond? })
//
// A shot's time is its landing (the contact frame), which is where its impact cue sits; entrances
// that travel start before it. Durations accept seconds or '1b' / '0.5b' beats.

import { block, linesOf, joinLines, layoutLines, typeColour, hitAt, cueRoleFor } from './common.js';

const LEAD = { slam: 0.1, stack: 0, pair: 0.3, cut: 0, extrude: 0.42, outline: 0.07 };

export const Words = block('words', (ctx, o) => {
  const shots = (o.shots || []).map(s => (typeof s === 'string' ? { text: s } : { ...s }));
  if (!shots.length) throw new Error('Words needs shots');
  const beat1 = ctx.film.beat ? ctx.b(1) : 0.4;
  const R = ctx.rng(o.seed ?? 5);
  let at = 0;
  let prevGround = o.ground ? ctx.colour(o.ground) : ctx.groundAt(ctx.t0 - 1e-6);
  const built = [];

  shots.forEach((s, i) => {
    const style = s.style || o.style || 'slam';
    const dur = s.dur != null ? ctx.time(s.dur) : beat1;
    const land = ctx.t0 + (s.at != null ? ctx.time(s.at) : at);
    at = land - ctx.t0 + dur;
    const enter = s.enter || (i === 0 ? 'cut' : o.enter || 'cut');
    let lead = enter === 'whipX' || enter === 'whipY' ? 0 : enter === 'zoom' ? 0.24 : LEAD[style] ?? 0.1;
    if (i === 0 && ctx.film.scenes.length > 1 && lead > 0 && !s.lead) lead = Math.min(lead, 0.1);
    const ground = s.ground ? ctx.colour(s.ground) : prevGround;
    const colour = typeColour(ctx, ground, s.color);
    const group = ctx.group.add({ name: `shot-${i + 1}` });
    const lines = linesOf(ctx, s.text, s.tall);
    const string = s.string || joinLines(lines);
    const fill = s.fill ?? (style === 'cut' ? 0.62 + 0.26 * R() : dur > beat1 * 2.5 ? 0.76 : 0.86);
    const weight = s.weight ?? (style === 'stack' || style === 'cut' ? 860 : 820);
    const width = s.width ?? o.width;
    const layoutOpts = {
      fill, weight, width, tracking: s.tracking ?? -0.025, color: colour, maxHPer: s.maxH,
      outline: style === 'outline' ? Math.max(2, ctx.u * (ctx.portrait ? 0.5 : 0.38)) : 0, strokeColor: colour,
    };
    let kicker = null;
    if (style === 'extrude') {
      const near = ctx.mix(ctx.pal.accent, ground, 0.15), far = ctx.mix(ctx.pal.accentDeep, ground, 0.55);
      layoutOpts.extrude = { depth: s.depth ?? 0.22, layers: 22, near, far, rx: 6, ry: -10 };
    }
    const lay = layoutLines(ctx, group, lines, { ...layoutOpts, uniform: s.uniform, dy: style === 'stack' ? ctx.u * 4 : 0 });
    if (style === 'stack' || s.kicker) {
      const kt = s.kicker || '';
      if (kt) {
        kicker = ctx.textNode(group, {
          string: kt, font: 'display', size: ctx.u * (ctx.portrait ? 5.2 : 4.6), weight: 640, width: 112.5,
          tracking: 0.06, color: s.kickerColor ? ctx.colour(s.kickerColor) : (o.kickerAccent !== false ? typeColour(ctx, ground, 'accent') : colour),
        });
        const top = -lay.height / 2 + ctx.u * 4;
        kicker.rest({ y: top - (kicker.ink[3] - kicker.ink[1]) / 2 - ctx.u * 3.2 });
      }
    }
    const kland = land;                                        // the kicker shows on the shot's time
    const wordLand = style === 'stack' ? land + (s.gap != null ? ctx.time(s.gap) : beat1) : land;
    const cutAt = Math.max(ctx.t0, (style === 'stack' ? kland : wordLand) - lead);
    if (i === 0 || s.ground) ctx.ground(cutAt, ground);
    prevGround = ground;
    const rot = s.rot ?? (style === 'cut' ? (R() * 2 - 1) * 4 : 0);
    const dx = style === 'cut' ? (R() * 2 - 1) * (ctx.safe[2] - ctx.safe[0]) * (1 - fill) * 0.4 : 0;
    const dy = style === 'cut' ? (R() * 2 - 1) * ctx.H * 0.05 : 0;
    group.rest({ rot, x: dx, y: dy });
    if (style === 'outline') for (const n of lay.nodes) n.rest({ knockout: ground });
    const role = s.role || o.role || 'headline';
    const entry = ctx.text({ id: s.id, role, string, fact: s.fact, nodes: lay.nodes });
    if (kicker) ctx.text({ id: s.id ? s.id + '-kicker' : undefined, role: s.kickerRole || (role === 'texture' ? 'texture' : 'headline'), string: kicker.string, fact: s.kickerFact, nodes: [kicker] });

    // Entrance.
    if (i > 0) {
      if (enter === 'whipX' || enter === 'whipY') ctx.whip(cutAt, { dir: enter === 'whipX' ? [s.dir ?? 1, 0] : [0, s.dir ?? 1] });
      else ctx.cut(cutAt);
    }
    if (enter === 'zoom') ctx.zoomIn({ group, t: cutAt, d: lead + 0.04, from: 2.4 });
    // Hit and cue.
    const hit = s.hit ?? (style === 'cut' ? 'beat' : style === 'stack' || style === 'slam' || style === 'extrude' ? 'hit' : 'beat');
    const step = s.build === 'lines' ? ctx.time(s.step ?? beat1) : 0;
    const nodeLand = lay.nodes.map((_, k) => wordLand + k * step);
    const landing = style === 'outline' ? null : wordLand;
    if (landing != null && !(enter === 'whipX' || enter === 'whipY')) {
      lay.nodes.forEach((nd, k) => {
        if (k > 0 && !step) return;
        const centre = () => ctx.screenOf(nd);
        hitAt(ctx, nodeLand[k], k === lay.nodes.length - 1 ? hit : (s.lineHit ?? 'beat'), { colour, at: centre });
        if (s.cue !== false) ctx.cue({ id: k === 0 ? s.cueId : undefined, t: nodeLand[k], role: s.cue || (hit === 'punch' ? 'impact_big' : cueRoleFor[style] || 'impact'), sync: 'attack', picture: step ? `"${lines[k]}" lands` : `"${string}" lands` });
      });
    }
    if (kicker && s.cue !== false) ctx.cue({ t: kland, role: 'tick', sync: 'attack', picture: `kicker "${kicker.string}" appears`, gain_db: -4 });
    const fillAt = style === 'outline' ? (s.fillAt != null ? land + ctx.time(s.fillAt) : null) : null;
    if (style === 'outline') {
      if (s.cue !== false) ctx.cue({ t: land, role: 'tick', sync: 'attack', picture: `outline "${string}" appears`, gain_db: -3 });
      if (fillAt != null) {
        hitAt(ctx, fillAt, s.fillHit ?? 'hit', { colour, at: () => ctx.screenOf(lay.nodes[0]) });
        ctx.cue({ t: fillAt, role: s.fillCue || 'impact', sync: 'attack', picture: `"${string}" fills: it becomes true` });
      }
    }
    // Pulses: small camera bumps on later beats of a long hold (times after the landing). The music
    // carries them; they keep a held word alive without moving it out of its reading state.
    for (const p of [].concat(s.pulse || [])) ctx.bump(wordLand + ctx.time(p), { amt: s.pulseAmt ?? 0.02, tau: 0.05 });
    // The planned musical drop sits on this shot's landing (or its fill, for an outline).
    if (s.drop) ctx.music({ drop: +((fillAt ?? wordLand)).toFixed(6) });
    built.push({ i, s, style, group, nodes: lay.nodes, nodeLand, kicker, cutAt, land: wordLand, kland, lead, end: null, fillAt, enter, string, entry });
  });
  for (let i = 0; i < built.length; i++) built[i].end = i + 1 < built.length ? built[i + 1].cutAt : null;
  const len = at;

  // Flash budget: full-frame ground changes inside any second.
  const changes = built.filter((b, i) => i > 0 && b.s.ground && ctx.colour(b.s.ground) !== ctx.colour(built[i - 1].s.ground || shots[0].ground || 'ink')).map(b => b.cutAt);
  for (let i = 0; i < changes.length; i++) {
    let j = i; while (j < changes.length && changes[j] < changes[i] + 1) j++;
    if (j - i > (o.maxPerSecond ?? 5)) { ctx.warn(`Words: ${j - i} ground changes within 1 s from ${changes[i].toFixed(2)} s; every full-frame flip counts toward the flash budget (6 transitions)`); break; }
  }

  const drift = o.drift ?? 8;     // frame units per second while a word holds (capped by the room)
  function update(t) {
    for (const b of built) {
      const vis = t >= b.cutAt - 1e-9 && (b.end == null || t < b.end - 1e-9);
      b.group.opacity = vis ? 1 : 0;
      if (!vis) continue;
      const dl = t - b.land;
      const dir = b.i % 2 ? -1 : 1;
      if (b.zmax == null) camera(t);
      if (b.driftAxis === 'y') b.group.y += dir * b.driftV * Math.max(0, dl);
      else b.group.x += dir * b.driftV * Math.max(0, dl);
      for (const [k, n] of b.nodes.entries()) {
        const nl = b.nodeLand[k];
        if (b.style === 'slam' || b.style === 'stack' || b.style === 'outline') {
          const t0 = nl - (b.style === 'stack' || k > 0 ? 0.1 : b.lead);
          if (t < nl) {
            const p = ctx.progress(t, t0, nl);
            if (t < t0) { n.opacity = 0; continue; }
            const e = ctx.curves.slam(p);
            n.s = ctx.loglerp(b.style === 'stack' || k > 0 ? 1.7 : 2.1, 1, e);
            n.blur = (1 - e) * ctx.u * 1.6;
            n.opacity = ctx.ease.fade(Math.min(1, p * 2.5));
          }
          if (b.style === 'outline' && b.fillAt != null && t >= b.fillAt) n.stroke = 0;
        } else if (b.style === 'pair') {
          const side = k % 2 ? 1 : -1;
          const p = ctx.progress(t, b.land - b.lead, b.land);
          n.x += side * (1 - ctx.curves.arrive(p)) * ctx.W * 0.75;
        } else if (b.style === 'extrude') {
          const p = ctx.progress(t, b.land - b.lead, b.land);
          const e = ctx.ease.out4(p);
          n.s = ctx.loglerp(0.08, 1, e);
          n.ry = ctx.lerp(48, -10, e) - 4 * ctx.clamp(dl / 3);
          n.rx = ctx.lerp(18, 6, e);
          n.opacity = ctx.ease.fade(Math.min(1, p * 4));
        }
      }
      if (b.kicker && t < b.kland + 0.06 && b.kland > ctx.t0 + 0.02) {
        const p = ctx.progress(t, b.kland - 0.001, b.kland + 0.06);
        b.kicker.opacity = ctx.ease.fade(p);
      }
    }
  }

  // Each shot has its own slow push and slight roll, restarting at its cut, so a frame never parks
  // and a long run of shots never accumulates zoom.
  const push = o.push ?? 0.14, roll = o.roll ?? 0.8;
  function camera(t) {
    let b = built[0];
    for (const x of built) if (t >= x.cutAt - 1e-9) b = x;
    const span = Math.max(0.2, (b.end ?? ctx.t0 + len) - b.cutAt);
    const dt = Math.max(0, t - b.cutAt);
    if (b.zmax == null) {
      // Drift and push share the room the shot's widest line leaves inside the safe area (half each),
      // so neither ever carries the words out of it.
      const sw = ctx.safe[2] - ctx.safe[0], sh = ctx.safe[3] - ctx.safe[1];
      const sinR = Math.sin((roll * Math.PI) / 360);
      const w0 = Math.max(...b.nodes.map(n => Math.abs(n.x) * 2 + n.w)) + Math.abs(b.group.base.x || 0) * 2;
      const tall = Math.max(...b.nodes.map(n => Math.abs(n.y) * 2 + (n.ink[3] - n.ink[1])));
      const roomX = Math.max(0, (sw * 0.985 - w0 - tall * sinR * 2) / 2);
      const roomY = Math.max(0, (sh * 0.985 - tall - w0 * sinR * 2) / 2);
      const hold = Math.max(0.2, (b.end ?? ctx.t0 + len) - b.land);
      // Drift along whichever axis has more room (a tall frame drifts vertically).
      b.driftAxis = roomY > roomX * 1.3 ? 'y' : 'x';
      const room = b.driftAxis === 'y' ? roomY : roomX;
      b.driftV = Math.min(drift * ctx.u * (b.driftAxis === 'y' ? 2 : 1), (room * 0.5) / hold);
      const wide = w0 + (b.driftAxis === 'x' ? 2 * b.driftV * hold : 0);
      const tallD = tall + (b.driftAxis === 'y' ? 2 * b.driftV * hold : 0);
      b.zmax = Math.max(1, Math.min(sw / (wide + tallD * sinR * 2), sh / (tallD + wide * sinR * 2)) * 0.985);
    }
    const rate = Math.min(push, Math.log(b.zmax) / span);
    return { x: 0, y: 0, zoom: Math.exp(rate * dt), rot: (b.i % 2 ? -1 : 1) * roll * (dt / span - 0.5), drift: false };
  }

  return {
    len,
    camera,
    ground0: built[0] && (built[0].s.ground ? ctx.colour(built[0].s.ground) : prevGround),
    update,
    through() {
      const want = o.through || {};
      const b = built[want.shot != null ? (want.shot < 0 ? built.length + want.shot : want.shot) : built.length - 1];
      for (const n of b.nodes) {
        if (typeof want.letter === 'number') return { node: n, letter: want.letter };
        const letters = n.letters.map(l => l.textContent);
        const cands = want.letter ? [want.letter] : ['O', 'D', 'A', 'B', 'P', 'R', '0', 'Q', 'o', 'a', 'e', 'd', 'b', 'p'];
        for (const c of cands) { const k = letters.indexOf(c); if (k >= 0) return { node: n, letter: k }; }
      }
      ctx.warn('Words exit "through": no letter with a counter in the last shot');
      return { node: b.nodes[0], letter: 0 };
    },
    shots: built,
  };
});
