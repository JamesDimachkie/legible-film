// analyse(): steps through every output frame without painting and reports reading windows,
// contrast, the ground's luminance, predicted flashing and truth (DESIGN §7). It measures the
// film's own state (opacity through every ancestor, scale against rest, blur, safe area, cover);
// it cannot see the encoded file, so the QC scripts still run on the delivered render.

import { evaluate, findFact, inScreen } from './engine.js';
import { mul, apply, matScale } from './node.js';
import { contrast, luminance, isRed, hex, parse, over, mix } from './color.js';
import { lettersShown } from './text.js';
import { motionReport, patternRisk, PATTERN_THRESHOLDS } from './motion.js';
import { flashPredictor } from './flashmap.js';

const ESSENTIAL = new Set(['claim', 'qualifier', 'headline', 'identity', 'ui', 'caption']);
const r3 = v => (v == null ? null : +v.toFixed(3));

function bbox(M, node) {
  const ink = node.ink || [0, 0, node.w, node.h];
  const pts = [[ink[0], ink[1]], [ink[2], ink[1]], [ink[0], ink[3]], [ink[2], ink[3]]].map(p => apply(M, p[0], p[1]));
  return [Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1])), Math.max(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1]))];
}
const overlaps = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
const area = b => Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1]);
const clipTo = (b, W, H) => [Math.max(0, b[0]), Math.max(0, b[1]), Math.min(W, b[2]), Math.min(H, b[3])];

function displays(fact) {
  if (!fact) return [];
  const d = fact.display;
  return Array.isArray(d) ? d : d != null ? [d] : [];
}

export function analyse(film, opts = {}) {
  const fps = opts.fps || film.fps;
  const n = Math.round(film.duration * fps);
  const W = film.W, H = film.H, S = film.safe, tol = 1.0;
  const texts = film.reg.texts;
  const st = texts.map(() => ({ first: null, last: null, runs: [], cur: null, minPx: Infinity, at: null }));
  const lum = new Array(n), red = new Array(n);
  const savedFrame = film.frameT;
  // Motion tracks: every text node and every element a block registered as moving.
  const elements = [];
  texts.forEach(tx => tx.nodes.forEach((node, j) => elements.push({ id: tx.nodes.length > 1 ? `${tx.id}#${j + 1}` : tx.id, node, group: tx.id, parent: node.parent, family: node.parent?.parent, samples: new Float32Array(n * 9), invalid: [] })));
  for (const tr of film.tracks) elements.push({ id: tr.id, discrete: tr.discrete, node: tr.node, group: tr.id, parent: tr.node.parent, family: tr.node.parent?.parent, samples: new Float32Array(n * 9), invalid: [] });
  const readFlags = texts.map(() => new Uint8Array(n));
  const patterns = film.fx.filter(e => e.pattern).concat(film.patterns || []);
  const patternHits = patterns.map(() => ({ frames: 0, first: null, worst: null }));
  let prevCam = null;
  const camHist = [];

  const fp = opts.flash === false ? null : flashPredictor(film);
  for (let k = 0; k < n; k++) {
    const t = k / fps;
    film.frameT = t;
    if (fp) {
      // Two samples inside the frame's exposure (180-degree shutter, widened in smear windows, never
      // across a cut), the way the render averages its sub-frames.
      let f = 1;
      for (const sm of film.reg.smears) if (t >= sm[0] && t <= sm[1]) f = Math.max(f, sm[2]);
      const E = (0.5 / fps) * f;
      let a = t - E / 2, b = t + E / 2;
      for (const cu of film.reg.cuts) {
        if (cu > a && cu <= t) a = cu;
        if (cu > t && cu < b) b = cu - 1e-6;
      }
      // Inside fast windows the render takes many sub-samples; the prediction takes six there.
      const fast = film.reg.fast.some(w => t >= w[0] && t <= w[1]) || f > 1;
      const ns = fast ? 6 : 2;
      fp.push(t, Array.from({ length: ns }, (_, i) => a + ((b - a) * (i + 0.5)) / ns), ts => evaluate(film, Math.max(0, Math.min(film.duration, ts))));
    }
    const cam = evaluate(film, t);
    const ground = film.groundAt(t);
    let L = luminance(ground);
    const G = L;
    let frameRed = isRed(ground);
    // Text and plates change the frame's mean luminance roughly by their ink area.
    const shown = [];
    texts.forEach((tx, i) => {
      const s = st[i];
      const sc = tx.scene >= 0 ? film.scenes[tx.scene] : { active: true };
      let present = false, readable = true, minPx = Infinity, colour = null, boxes = [];
      for (const node of tx.nodes) {
        const a = node.alpha();
        const vis = sc && sc.active && a > 0.02 && lettersShown(node) > 0 && node.revealWords > 0;
        if (vis) present = true;
        const M = inScreen(node) ? node.matrix() : mul(cam.M, node.matrix());
        const b = bbox(M, node);
        boxes.push(b);
        const px = node.fontPx * Math.sqrt(Math.abs(M[0] * M[3] - M[1] * M[2]));
        minPx = Math.min(minPx, px);
        colour = colour || (node.stroke > 0 ? node.strokeColor : node.color) || film.typeOn(ground);
        const ok = vis && a >= 0.98 && lettersShown(node) >= 1 && node.revealWords >= node.wordEls.length &&
          Math.abs(node.ownScale() - 1) <= 0.02 && node.blurChain() <= 0.35 &&
          b[0] >= S[0] - tol && b[1] >= S[1] - tol && b[2] <= S[2] + tol && b[3] <= S[3] + tol;
        if (!ok) readable = false;
        if (vis) shown.push({ b, colour: (node.stroke > 0 ? null : colour), a });
      }
      if (present && readable) {
        for (const occ of film.occluders) {
          if (occ.node.id <= Math.min(...tx.nodes.map(x => x.id))) continue;
          if (occ.node.alpha() < 0.5 || !(inScreen(occ.node) || film.scenes.some(x => x.active && isUnder(occ.node, x.group)))) continue;
          const ob = bbox(inScreen(occ.node) ? occ.node.matrix() : mul(cam.M, occ.node.matrix()), occ.node);
          if (boxes.some(b => overlaps(b, ob))) { readable = false; break; }
        }
      }
      if (!present) readable = false;
      if (present) { if (s.first == null) s.first = t; s.last = t; }
      if (readable) readFlags[i][k] = 1;
      if (readable) {
        if (!s.cur) s.cur = { start: t, end: t, minPx, colour, bg: tx.bg ? tx.bg(t) : ground };
        s.cur.end = t; s.cur.minPx = Math.min(s.cur.minPx, minPx);
      } else if (s.cur) { s.runs.push(s.cur); s.cur = null; }
    });
    for (const p of film.plates) {
      if (p.node.alpha() < 0.02 || !(inScreen(p.node) || film.scenes.some(x => x.active && isUnder(p.node, x.group)))) continue;
      const b = clipTo(bbox(inScreen(p.node) ? p.node.matrix() : mul(cam.M, p.node.matrix()), p.node), W, H);
      const f = area(b) / (W * H);
      L += f * p.node.alpha() * (luminance(p.colour) - G);
    }
    for (const s of shown) {
      if (!s.colour) continue;
      const f = (area(clipTo(s.b, W, H)) / (W * H)) * 0.4;
      L += f * s.a * (luminance(s.colour) - G);
    }
    for (const w of film.windows) {
      if (t < w.t0 || t >= w.t1) continue;
      const M = mul(cam.M, w.node.matrix());
      const sz = Math.abs(M[0]) * Math.min(w.hole.w, w.hole.h);
      const f = Math.min(1, (Math.PI / 4) * sz * sz / (W * H));
      L += f * (luminance(w.colour) - L);
    }
    for (const e of film.fx) {
      if (e.kind !== 'flash') continue;
      const a = e.alphaAt(t);
      if (a > 0) { L = L + a * (luminance(e.color) - L); if (isRed(e.color) && a > 0.5) frameRed = true; }
    }
    lum[k] = Math.max(0, Math.min(1, L));
    red[k] = frameRed;
    // Motion samples.
    for (const e of elements) {
      const node = e.node, a = node.alpha();
      const o = k * 9;
      if (a <= 0.02) { e.samples[o] = 0; continue; }
      const M = inScreen(node) ? node.matrix() : mul(cam.M, node.matrix());
      const b = bbox(M, node), lb = bbox(node.matrix(), node);
      e.samples.set([1, (b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[2] - b[0], b[3] - b[1], (lb[0] + lb[2]) / 2, (lb[1] + lb[3]) / 2, lb[2] - lb[0], lb[3] - lb[1]], o);
      for (let q = node; q; q = q.parent) {
        const what = q.s * q.sx < -1e-9 || q.s * q.sy < -1e-9 ? 'negative scale' : q.opacity > 1 + 1e-6 ? `opacity ${q.opacity.toFixed(3)} above 1` : q.opacity < -1e-6 ? 'negative opacity' : q.blur < 0 ? 'negative blur' : q.w < 0 || q.h < 0 ? 'negative size' : null;
        if (what) { if (e.invalid.length < 10) e.invalid.push({ t, what: q === node ? what : `${what} (on ancestor ${q.name || q.id})` }); break; }
      }
    }
    // Regular patterns: how the pattern moves this frame (camera-borne patterns flow with the camera).
    const shaking = film.shakes.some(sh => t >= sh.t && t < sh.t + sh.tau * 4);
    const acrossCut = film.reg.cuts.some(c => c > (k - 1) / fps + 1e-9 && c <= t + 1e-9);
    if (acrossCut) camHist.length = 0;
    const v = prevCam && !acrossCut ? [cam.M[4] - prevCam[4], cam.M[5] - prevCam[5], Math.log(matScale(cam.M) / matScale(prevCam))] : [0, 0, 0];
    camHist.push(v); if (camHist.length > 15) camHist.shift();
    const reversed = [0, 1, 2].some(i => camHist.some(x => x[i] > 1e-4) && camHist.some(x => x[i] < -1e-4) && Math.max(...camHist.map(x => Math.abs(x[i]))) > (i === 2 ? 2e-3 : 0.5));
    const camMoving = Math.hypot(v[0], v[1]) > 0.1 || Math.abs(v[2]) > 2e-4;
    prevCam = cam.M;
    const penv = { W, H, u: film.u, zoom: cam.zoom, groundAt: x => film.groundAt(x), typeOn: g => film.typeOn(g), cam, film };
    patterns.forEach((p, j) => {
      if (acrossCut) return;            // motion is unknown on the first frame after a cut
      const smp = p.pattern(t, penv);
      if (!smp) return;
      const motion = smp.motion || (shaking || reversed || smp.changing ? 'changing' : camMoving ? 'flow' : 'still');
      const rec = { ...smp, motion, t };
      if (patternRisk(rec)) {
        const h = patternHits[j];
        h.frames++; if (h.first == null) h.first = t;
        if (!h.worst || rec.diff_cdm2 * rec.area > h.worst.diff_cdm2 * h.worst.area) h.worst = rec;
      }
    });
  }
  film.frameT = savedFrame;

  // ---------- flashing ----------
  const trans = [];
  let dir = 0, hi = lum[0], lo = lum[0], anchor = lum[0];
  for (let k = 1; k < n; k++) {
    const v = lum[k];
    if (dir === 0) {
      hi = Math.max(hi, v); lo = Math.min(lo, v);
      if (hi - lo >= 0.1 && lo < 0.8) { dir = v >= hi ? 1 : -1; anchor = v; trans.push(k / fps); }
    } else if (dir === 1) {
      if (v > anchor) anchor = v;
      else if (anchor - v >= 0.1 && v < 0.8) { dir = -1; anchor = v; trans.push(k / fps); }
    } else {
      if (v < anchor) anchor = v;
      else if (v - anchor >= 0.1 && anchor < 0.8) { dir = 1; anchor = v; trans.push(k / fps); }
    }
  }
  const redTrans = [];
  for (let k = 1; k < n; k++) if (red[k] !== red[k - 1]) redTrans.push(k / fps);
  const maxIn1s = arr => {
    let best = 0, at = null;
    for (let i = 0; i < arr.length; i++) {
      let j = i;
      while (j < arr.length && arr[j] < arr[i] + 1 - 1e-9) j++;
      if (j - i > best) { best = j - i; at = arr[i]; }
    }
    return [best, at];
  };
  const [maxT, atT] = maxIn1s(trans), [maxR, atR] = maxIn1s(redTrans);
  const errors = [], warnings = [];
  // The flashing verdict uses the window method of flash_scan.py on a small raster of each frame
  // (lf/flashmap.js); the whole-frame ground series above stays as the luminance strip.
  const fr = fp ? fp.result() : null;
  const gT = fr ? fr.gb.general_max_per_s : maxT, gAt = fr ? fr.gb.general_at_s : atT;
  const rT = fr ? fr.rb.red_max_per_s : maxR, rAt = fr ? fr.rb.red_at_s : atR;
  if (gT > 6) errors.push(`flash: ${gT} opposing luminance transitions within 1 s from ${gAt} s in window ${fr ? JSON.stringify(fr.gb.window) : 'frame'} (more than 3 flashes)` + (fr && fr.flagged.length > 1 ? `; ${fr.flagged.length} windows over the limit` : ''));
  if (rT > 6) errors.push(`red flash: ${rT} saturated-red transitions within 1 s from ${rAt} s`);
  if (gT > 4 && gT <= 6) warnings.push(`flash: ${gT} predicted transitions within 1 s from ${gAt} s (limit 6); check the render with flash_scan.py`);

  // ---------- texts ----------
  const out = [];
  texts.forEach((tx, i) => {
    const s = st[i];
    if (s.cur) s.runs.push(s.cur);
    const best = s.runs.reduce((a, r) => (!a || r.end - r.start > a.end - a.start ? r : a), null);
    const cps = tx.role === 'caption' ? film.reading.captionCps : film.reading.cps;
    const need = tx.role === 'texture' ? 0 : film.reading.base + tx.string.length / cps;
    const rec = {
      id: tx.id, role: tx.role, string: tx.string, fact: tx.fact, scene: tx.scene + 1,
      in: r3(s.first), readStart: best ? r3(best.start) : null, readEnd: best ? r3(best.end + 1 / fps) : null,
      out: s.last != null ? r3(s.last + 1 / fps) : null, need_s: r3(need),
      min_font_px: best ? Math.round(best.minPx) : null,
      colour: best ? hex(parse(best.colour)) : null, ground: best ? hex(parse(best.bg)) : null, contrast: null,
    };
    if (best) rec.contrast = +contrast(best.colour, best.bg).toFixed(2);
    const essential = ESSENTIAL.has(tx.role);
    if (essential) {
      if (s.first == null) errors.push(`${tx.id}: "${tx.string}" never appears`);
      else if (!best) errors.push(`reading: ${tx.id} "${tx.string}" is never fully readable (in view, settled, sharp, inside the safe area and uncovered)`);
      else {
        const usable = best.end + 1 / fps - best.start;
        if (usable + 1e-6 < need) errors.push(`reading: ${tx.id} "${tx.string}" is readable for ${usable.toFixed(2)} s; it needs ${need.toFixed(2)} s`);
        const weight = tx.nodes[0]?.style?.weight ?? 400;
        const large = best.minPx >= 24 || (best.minPx >= 18.66 && weight >= 700);
        const minC = large ? 3 : 4.5;
        if (rec.contrast < minC) errors.push(`contrast: ${tx.id} "${tx.string}" is ${rec.contrast}:1 (needs ${minC}:1 at ${Math.round(best.minPx)} px)`);
        const phone = best.minPx * (384 / W);
        if (phone < 8) warnings.push(`${tx.id}: ${Math.round(best.minPx)} px renders about ${phone.toFixed(1)} px at a 384 px phone feed`);
      }
    }
    // Truth.
    const facts = film.facts;
    if (facts && (tx.role === 'claim' || tx.role === 'qualifier')) {
      if (!tx.fact) errors.push(`truth: ${tx.role} ${tx.id} "${tx.string}" has no fact id`);
      else {
        const f = findFact(facts, tx.fact);
        if (!f) errors.push(`truth: ${tx.id} names fact "${tx.fact}", which is not in the facts file`);
        else if (tx.role === 'claim' && !displays(f).includes(tx.string)) errors.push(`truth: ${tx.id} "${tx.string}" does not match the display of fact "${tx.fact}" (${JSON.stringify(f.display)})`);
        else if (tx.role === 'qualifier' && f.label_beside_value !== tx.string) errors.push(`truth: qualifier ${tx.id} "${tx.string}" does not match label_beside_value of fact "${tx.fact}"`);
      }
    } else if (facts && tx.fact && !findFact(facts, tx.fact)) {
      errors.push(`truth: ${tx.id} names fact "${tx.fact}", which is not in the facts file`);
    }
    if (!tx.fact && tx.role !== 'texture' && /\d/.test(tx.string)) warnings.push(`truth: ${tx.id} "${tx.string}" contains a digit but no fact id`);
    out.push(rec);
  });

  // Motion and patterns.
  const motion = motionReport({
    fps, n, cuts: film.reg.cuts, hits: [...film.bumps.map(b => [b.t, b.t + 0.06]), ...film.shakes.map(x => [x.t, x.t + x.tau * 3])], blurWins: [...film.reg.smears, ...film.reg.fast].map(w => [w[0], w[1]]), elements,
    readable: texts.map((tx, i) => ({ id: tx.id, group: tx.id, flags: readFlags[i] })),
  });
  const mw = motion.warnings;
  warnings.push(...mw.slice(0, 40));
  if (mw.length > 40) warnings.push(`motion: ${mw.length - 40} more motion warnings in analysis.motion.warnings`);
  const patternOut = patterns.map((p, j) => ({ id: p.id || p.kind, risk_frames: patternHits[j].frames, first_s: patternHits[j].first, worst: patternHits[j].worst }));
  for (const p of patternOut) {
    if (!p.risk_frames) continue;
    const w = p.worst;
    warnings.push(`pattern: ${p.id} meets the Ofcom regular-pattern criteria on ${p.risk_frames} frame(s) from ${p.first_s.toFixed(2)} s: ${w.pairs.toFixed(0)} light-dark pairs, ${w.diff_cdm2.toFixed(1)} cd/m2 difference (darker ${w.dark_cdm2.toFixed(1)} cd/m2), ${Math.round(w.area * 100)}% of the screen, ${w.motion}; a photosensitivity risk`);
  }

  return {
    texts: out,
    motion,
    patterns: { thresholds: PATTERN_THRESHOLDS, items: patternOut },
    grounds: { fps, luminance: lum.map(v => +v.toFixed(4)), red },
    flash: {
      max_transitions_in_1s: gT, at_s: gAt, window: fr ? fr.gb.window : null, red_max_transitions_in_1s: rT, red_at_s: rAt,
      method: fr ? `flash_scan.py's window method on a ${fr.scan_size[0]}x${fr.scan_size[1]} raster of grounds, plates, windows, type and effect canvases` : 'whole-frame ground series',
      flagged: fr ? fr.flagged : [], debug: opts.flashDebug && fr ? fr.debug : undefined, frame_mean: { max_transitions_in_1s: maxT, at_s: atT != null ? r3(atT) : null, red_max_transitions_in_1s: maxR },
    },
    errors: [...film.reg.errors, ...errors],
    warnings: [...film.reg.warnings, ...warnings],
  };
}

function isUnder(node, group) {
  for (let n = node; n; n = n.parent) if (n === group) return true;
  return false;
}
