// The film engine: one clock, layers, the camera rig, registries and the window.__lf contract.
//
// Layers, bottom to top:  ground (full-frame colour) · world-space effects canvas (texture, threads)
// · fx layer (shakes, beat bumps) > camera layer (scene move, whips) > world (scene groups of nodes)
// · screen-space effects canvas (speed lines, bursts, flashes) · overlay (captions) · preview UI.
// The world, the camera and temporary effects each own one transform, so they never fight.

import { Node, mul, translate, rotate, scale, apply, invert, matScale } from './node.js';
import { palette as makePalette, resolve, typeOn, mix, luminance, hex, parse } from './color.js';
import { ease, curves, clamp, lerp, loglerp, progress, decay, token } from './ease.js';
import { rng, hash, noise1 } from './rng.js';
import { textNode, sizeForWidth, counterOf, measure, inkMetrics, typed, textOutline, loopAround } from './text.js';
import * as FX from './fx.js';

const r6 = v => +(+v).toFixed(6);

export function resolveTime(v, beat) {
  if (v == null) return v;
  if (typeof v === 'number') return v;
  if (typeof v === 'object' && 'b' in v) return beatsToSeconds(v.b, beat);
  const s = String(v).trim();
  const m = s.match(/^(-?[\d.]+)\s*(b|beats?|s)?$/);
  if (!m) throw new Error(`cannot read the time "${v}"`);
  if (m[2] && m[2][0] === 'b') return beatsToSeconds(+m[1], beat);
  return +m[1];
}
function beatsToSeconds(n, beat) {
  if (!beat) throw new Error('a time in beats needs a beat grid (spec.beat = {bpm, offset})');
  return (n * 60) / beat.bpm;
}

export class Film {
  constructor(spec, env) {
    this.spec = spec;
    this.env = env;
    this.W = env.W; this.H = env.H;
    this.fps = spec.fps ?? 60;
    this.beat = spec.beat ? { bpm: spec.beat.bpm, offset: spec.beat.offset ?? 0 } : null;
    this.u = Math.min(this.W, this.H) / 100;
    this.portrait = this.H > this.W;
    this.pal = makePalette(spec.brand ?? '#3D7BFF', spec.palette);
    const sa = { ...(this.portrait ? { x: 0.07, top: 0.1, bottom: 0.17 } : { x: 0.06, top: 0.08, bottom: 0.08 }), ...(spec.safe || {}) };
    this.safe = [this.W * sa.x, this.H * sa.top, this.W * (1 - sa.x), this.H * (1 - sa.bottom)];
    this.reading = { cps: 15, base: 0.3, captionCps: 20, ...(spec.reading || {}) };
    this.reg = { cues: [], cuts: [], smears: [], fast: [], rests: [], flashes: [], texts: [], captions: [], grounds: [], warnings: [], errors: [] };
    this.music = null;
    this.whips = []; this.shakes = []; this.bumps = []; this.arrivals = []; this.overrides = []; this.groupTerms = [];
    this.fx = []; this.occluders = []; this.windows = []; this.plates = []; this.tracks = [];
    this.frameT = null;
    this.scenes = [];
    this.cueIds = new Set();
    this.facts = env.facts || null;
    this.textIds = new Set();
  }

  // ---------- time ----------
  time(v) { return resolveTime(v, this.beat); }
  b(n) { return beatsToSeconds(n, this.beat); }
  atBeat(n) { return (this.beat?.offset ?? 0) + beatsToSeconds(n, this.beat); }
  // Frame-locked time: what typed characters, carets, counters and seeds follow.
  locked(t) { return this.frameT != null ? this.frameT : Math.floor(t * this.fps + 1e-6) / this.fps; }
  frameIndex(t) { return Math.round(this.locked(t) * this.fps); }

  // ---------- registries ----------
  warn(msg) { if (!this.reg.warnings.includes(msg)) this.reg.warnings.push(msg); }
  error(msg) { if (!this.reg.errors.includes(msg)) this.reg.errors.push(msg); }
  cue(e) {
    let id = e.id || `${e.role || 'cue'}-${this.reg.cues.length + 1}`;
    for (let k = 2; this.cueIds.has(id); k++) id = `${e.id || e.role}-${k}`;
    this.cueIds.add(id);
    const ev = { id, t: r6(this.time(e.t)), picture: e.picture || '', sound: e.sound || 'required' };
    if (ev.sound !== 'silent') ev.sync = e.sync || 'attack';
    for (const k of ['role', 'gain_db', 'duck_db', 'variant', 'window_ms', 'tolerance_ms']) if (e[k] != null) ev[k] = e[k];
    if (ev.sound !== 'silent' && ev.tolerance_ms == null) ev.tolerance_ms = ev.sync === 'apex' ? 25 : 17;
    this.reg.cues.push(ev);
    return ev;
  }
  cut(t) { this.reg.cuts.push(r6(this.time(t))); }
  smear(t0, t1, f) { this.reg.smears.push([r6(t0), r6(t1), f]); }
  fastWindow(t0, t1, n) { this.reg.fast.push([r6(t0), r6(t1), n]); }
  rest(t0, t1, label) { this.reg.rests.push([r6(this.time(t0)), r6(this.time(t1)), label || 'rest']); }
  ground(t, colour, o = {}) {
    this.reg.grounds.push({ t: this.time(t), colour: resolve(this.pal, colour), fade: o.fade ?? 0 });
  }
  caption(c) { this.reg.captions.push(c); }

  // Register a text for analysis: {id, role, string, fact, nodes, bg(t) -> colour}.
  text(o) {
    let id = o.id || (o.role + '-' + o.string.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')).slice(0, 48);
    for (let k = 2; this.textIds.has(id); k++) id = `${o.id || id.replace(/-\d+$/, '')}-${k}`;
    this.textIds.add(id);
    const entry = { id, role: o.role || 'headline', string: o.string, fact: o.fact || null, nodes: o.nodes, bg: o.bg || null, scene: this.buildingOverlay ? -1 : this.scenes.length - 1 };
    this.reg.texts.push(entry);
    return entry;
  }
  occluder(node, colour) { this.occluders.push({ node, colour }); }
  // Register a moving element (texts are tracked automatically) for analyse()'s motion checks.
  track(node, id, o = {}) { this.tracks.push({ node, id: id || node.name || `node-${node.id}`, discrete: !!o.discrete }); return node; }
  plate(node, colour) { this.plates.push({ node, colour }); }

  // ---------- grounds ----------
  sortGrounds() { this.reg.grounds.sort((a, b) => a.t - b.t); }
  groundAt(t) {
    const g = this.reg.grounds;
    let cur = this.pal.ink, prev = cur, seg = null;
    for (const s of g) { if (s.t <= t + 1e-9) { prev = cur; cur = s.colour; seg = s; } else break; }
    if (seg && seg.fade > 0 && t < seg.t + seg.fade) return mix(prev, cur, ease.fade((t - seg.t) / seg.fade));
    return cur;
  }
  groundLum(t) { return luminance(this.groundAt(t)); }
  typeOn(ground) { return typeOn(this.pal, ground); }
  colour(c) { return resolve(this.pal, c); }

  // ---------- camera rig ----------
  whip(t, o = {}) {
    const c = this.time(t);
    const dir = o.dir ?? [1, 0];
    const pre = o.pre ?? 0.16, post = o.post ?? pre;
    const w = { c, dir, pre, post, dist: o.dist ?? 1.1 };
    this.whips.push(w);
    this.cut(c);
    this.smear(c - pre * 0.55, c + post * 0.55, o.smear ?? 3);
    this.fastWindow(c - pre, c + post, 12);
    if (o.cue !== false) this.cue({ id: o.id, t: c, role: o.role || 'whoosh', sync: 'apex', picture: o.picture || 'camera whip at peak speed (the cut)', gain_db: o.gain_db });
    return w;
  }
  shake(t, o = {}) { this.shakes.push({ t: this.time(t), amp: o.amp ?? 1.2, tau: o.tau ?? 0.12, freq: o.freq ?? 22, seed: o.seed ?? this.shakes.length + 1 }); }
  bump(t, o = {}) { this.bumps.push({ t: this.time(t), amt: o.amt ?? 0.035, tau: o.tau ?? 0.032 }); }
  // A camera arriving from depth after a cut: zoom multiplier from `from` to 1, decelerating.
  arrive(t, o = {}) { this.arrivals.push({ t: this.time(t), from: o.from ?? 1.7, d: o.d ?? 0.42, curve: o.curve || ease.out3 }); }
  // A camera that takes over during [t0, t1] (fly-throughs).
  override(t0, t1, fn) { this.overrides.push({ t0, t1, fn }); }

  // Anchor framing: world point P sits at screen point S at this zoom and roll.
  frameAt(P, S, zoom, rot = 0) {
    const C = [this.W / 2, this.H / 2];
    const inv = rotate(-rot);
    const d = apply(inv, (S[0] - C[0]) / zoom, (S[1] - C[1]) / zoom);
    return { x: P[0] - d[0], y: P[1] - d[1], zoom, rot };
  }
  camMatrix(c) {
    return mul(translate(this.W / 2, this.H / 2), mul(rotate(c.rot || 0), mul(scale(c.zoom), translate(-c.x, -c.y))));
  }

  sceneAt(t) {
    const S = this.scenes;
    for (let i = S.length - 1; i >= 0; i--) if (t >= S[i].t0 - 1e-9) return S[i];
    return S[0];
  }

  cameraAt(t) {
    const sc = this.sceneAt(t);
    let cam = null;
    for (const o of this.overrides) if (t >= o.t0 && t < o.t1) cam = o.fn(t);
    if (!cam) {
      const local = sc.camera ? sc.camera(t) : null;
      const mv = sc.move;
      const span = Math.max(0.001, sc.t1 - sc.t0);
      const p = (t - sc.t0) / span;
      cam = { x: 0, y: 0, zoom: 1, rot: 0, ...(local || {}) };
      if (!local || local.drift !== false) {
        cam.zoom *= Math.exp((mv.push ?? 0.03) * (t - sc.t0));
        cam.rot = (cam.rot || 0) + (mv.roll ?? 0.5) * (p - 0.5);
      }
    }
    for (const a of this.arrivals) {
      if (t >= a.t && t < a.t + a.d) cam.zoom *= loglerp(a.from, 1, a.curve((t - a.t) / a.d));
    }
    // Whips: screen offsets. The camera accelerates away along dir; the cut sits at peak speed;
    // the next shot arrives from the opposite side, decelerating.
    let ox = 0, oy = 0;
    for (const w of this.whips) {
      const D = w.dist * (Math.abs(w.dir[0]) >= Math.abs(w.dir[1]) ? this.W : this.H);
      let k = 0;
      if (t >= w.c - w.pre && t < w.c) k = -Math.pow((t - (w.c - w.pre)) / w.pre, 3);
      else if (t >= w.c && t < w.c + w.post) k = Math.pow(1 - (t - w.c) / w.post, 3);
      ox += w.dir[0] * D * k; oy += w.dir[1] * D * k;
    }
    // Shakes and bumps live on the fx layer.
    let sx = 0, sy = 0, srot = 0, bump = 1;
    for (const s of this.shakes) {
      const dt = t - s.t;
      if (dt < 0 || dt > s.tau * 6) continue;
      const a = s.amp * this.u * decay(dt, s.tau);
      sx += a * Math.sin(dt * s.freq * 6.283 + hash(s.seed, 1) * 6.283);
      sy += a * Math.sin(dt * s.freq * 5.1 + hash(s.seed, 2) * 6.283);
      srot += 0.25 * s.amp * decay(dt, s.tau) * Math.sin(dt * s.freq * 4.3 + hash(s.seed, 3) * 6.283);
    }
    for (const b of this.bumps) {
      const dt = t - b.t;
      if (dt < 0 || dt > 0.3) continue;
      bump *= 1 + b.amt * (dt < 0.012 ? dt / 0.012 : Math.exp(-(dt - 0.012) / b.tau));
    }
    const camM = mul(translate(ox, oy), this.camMatrix(cam));
    const C = [this.W / 2, this.H / 2];
    const fxM = mul(translate(C[0] + sx, C[1] + sy), mul(rotate(srot), mul(scale(bump), translate(-C[0], -C[1]))));
    return { cam, camM, fxM, M: mul(fxM, camM), zoom: cam.zoom * bump };
  }

  // ---------- transitions (engine level; blocks and scenes use them) ----------
  // Fly through the counter of a letter into what comes next. The counter becomes a window filled
  // with the next ground, growing until it fills the frame at the cut.
  through(o) {
    const { node, letter } = o;
    const c = this.time(o.t), d = o.d ?? 0.55;
    const x3d = !!(node.copies && node.copies.length);
    const hole = counterOf(node, letter, { dilate: x3d ? 1 : undefined });
    if (!hole) {
      this.warn(`exit "through": letter ${letter} of "${node.string}" has no counter; using a cut`);
      this.cut(c);
      return false;
    }
    const win = document.createElement('div');
    win.className = 'lf-window';
    const nextGround = resolve(this.pal, o.nextGround) || this.pal.paper;
    // The window is a vector path of the counter (sharp at any magnification).
    win.style.cssText = `position:absolute;left:${hole.mx}px;top:${hole.my}px;width:${hole.mw}px;height:${hole.mh}px;visibility:hidden;`;
    win.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${hole.vw} ${hole.vh}" width="${hole.mw}" height="${hole.mh}" style="display:block;overflow:visible"><path d="${hole.path}" fill="${nextGround}"/></svg>`;
    let mirror = null;
    if (x3d) {
      // A sibling node that mirrors the name's transform, outside its 3-D context. Once the block
      // turns the type flat (node.flat), the mirror also draws the whole text as vector outlines and
      // the DOM text hides: a composited 3-D layer is a bitmap that goes soft when magnified.
      mirror = node.parent.add({ name: 'through-window', w: node.w, h: node.h, ax: node.ax, ay: node.ay });
      const vec = document.createElement('div');
      vec.style.cssText = `position:absolute;left:0;top:0;width:${node.w}px;height:${node.h}px;visibility:hidden;`;
      const outline = textOutline(node);
      const counterD = loopAround(outline, letter, hole.cx, hole.cy);
      const face = node.color || this.typeOn(this.groundAt(c - d));
      vec.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${node.w} ${node.h}" width="${node.w}" height="${node.h}" style="display:block;overflow:visible"><path fill-rule="evenodd" d="${outline.d}" fill="${face}"/></svg>`;
      // In the vector phase the window is the same loop as the letter's counter: one shared edge.
      if (counterD) win.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${node.w} ${node.h}" width="${node.w}" height="${node.h}" style="display:block;overflow:visible"><path d="${counterD}" fill="${nextGround}" stroke="${nextGround}" stroke-width="0.35"/></svg>`;
      if (counterD) win.style.cssText = `position:absolute;left:0;top:0;width:${node.w}px;height:${node.h}px;visibility:hidden;`;
      mirror.el.append(vec, win);
      mirror.vec = vec;
    } else { node.el.style.isolation = 'isolate'; node.el.insertBefore(win, node.el.firstChild); }
    // The window paints under the letters: the word spans are positioned above it.
    for (const we of node.wordEls) { we.style.position = 'relative'; we.style.zIndex = '1'; }
    const knock = node.front && node.front.querySelector('.lf-knockout');
    if (knock) knock.style.zIndex = '3';
    const w = { node, el: win, t0: c - d, t1: c, colour: nextGround, hole, mirror };
    this.windows.push(w);
    const film = this;
    let start = null;
    this.override(c - d, c, t => {
      // Camera at the start of the move, from the scene's own camera.
      if (!start) {
        const sc = film.sceneAt(c - d);
        const local = sc.camera ? sc.camera(c - d) : null;
        start = { x: 0, y: 0, zoom: 1, rot: 0, ...(local || {}) };
        if (!local || local.drift !== false) {
          start.zoom *= Math.exp((sc.move.push ?? 0.03) * (c - d - sc.t0));
          start.rot = (start.rot || 0) + (sc.move.roll ?? 0.5) * ((c - d - sc.t0) / Math.max(0.001, sc.t1 - sc.t0) - 0.5);
        }
      }
      const m = node.matrix();
      const P = apply(m, hole.cx, hole.cy);
      const S0 = apply(film.camMatrix(start), P[0], P[1]);
      const ns = matScale(m);
      const zEnd = (1.25 * Math.hypot(film.W, film.H)) / (Math.min(hole.w, hole.h) * ns);
      const p = (t - (c - d)) / d;
      const z = loglerp(start.zoom, Math.max(zEnd, start.zoom * 2), ease.in3(p));
      const S = [lerp(S0[0], film.W / 2, ease.out3(Math.min(1, p * 1.3))), lerp(S0[1], film.H / 2, ease.out3(Math.min(1, p * 1.3)))];
      return film.frameAt(P, S, z, lerp(start.rot, 0, ease.out2(p)));
    });
    this.cut(c);
    this.smear(c - d * 0.4, c, 2.5);
    this.fastWindow(c - d * 0.6, c + 0.15, 12);
    this.ground(c, nextGround);
    if (o.cue !== false) this.cue({ t: c, role: o.role || 'whoosh_big', sync: 'apex', picture: `camera flies through the counter of "${node.letters[letter].textContent}" (the cut)` });
    this.arrive(c, { from: o.arriveFrom ?? 2.4, d: o.arriveD ?? 0.5 });
    return true;
  }

  // Everything in `group` shrinks into a point; the next scene can grow from it.
  collapse(o) {
    const c = this.time(o.t), d = o.d ?? 0.38;
    this.groupTerms.push({ node: o.group, t0: c - d, t1: c, f: p => loglerp(1, 0.004, ease.in3(p)), rot: o.rot ?? -8 });
    this.cut(c);
    this.fastWindow(c - d, c + 0.2, 10);
    this.smear(c - d * 0.5, c, 2);
    if (o.cue !== false) this.cue({ t: c - 0.02, role: o.role || 'whoosh', sync: 'apex', picture: 'everything collapses into a point' });
  }
  grow(o) {
    const c = this.time(o.t), d = o.d ?? 0.45;
    this.groupTerms.push({ node: o.group, t0: c, t1: c + d, f: p => loglerp(0.02, 1, ease.out4(p)), rot: o.rot ?? 6, grow: true });
    this.fastWindow(c, c + d * 0.6, 10);
  }
  // A zoom entrance for one group: arrives from a larger scale (from depth), decelerating.
  zoomIn(o) {
    const c = this.time(o.t), d = o.d ?? 0.3;
    this.groupTerms.push({ node: o.group, t0: c, t1: c + d, f: p => loglerp(o.from ?? 2.6, 1, ease.out4(p)), rot: 0, grow: true });
    this.fastWindow(c, c + d * 0.5, 10);
  }

  // ---------- effects ----------
  addFx(e) { this.fx.push(e); return e; }
  screenOf(node, lx, ly) {
    const m = inScreen(node) ? node.matrix() : mul(this._camNow.M, node.matrix());
    return apply(m, lx ?? node.w * 0.5, ly ?? (node.ink ? (node.ink[1] + node.ink[3]) / 2 : node.h * 0.5));
  }
  worldOf(node, lx, ly) {
    return apply(node.matrix(), lx ?? node.w * 0.5, ly ?? node.h * 0.5);
  }

  // ---------- type ----------
  // A display text fitted to `fill` of the safe width, capped by `maxH` of the safe height.
  fitText(parent, o) {
    const sw = this.safe[2] - this.safe[0], sh = this.safe[3] - this.safe[1];
    // In a tall frame display type defaults to the condensed width, so a word fills more of the frame.
    const st = { font: 'display', weight: 820, tracking: -0.02, lineHeight: 1, ...o, width: o.width ?? (this.portrait ? 75 : 100) };
    let size = sizeForWidth(o.string, st, sw * (o.fill ?? 0.9));
    const mt = inkMetrics(o.string, st);
    const capH = (mt.inkAsc + mt.inkDesc) || 0.72;
    const maxSize = (sh * (o.maxH ?? 0.42)) / capH;
    if (size > maxSize) size = maxSize;
    if (o.minH != null && size * capH < this.H * o.minH) {
      this.warn(`"${o.string}" fits only ${(size * capH / this.H * 100).toFixed(1)}% of the frame height at ${this.W}x${this.H}; split the phrase into fewer words per shot`);
    }
    if (o.maxSize) size = Math.min(size, o.maxSize);
    return textNode(parent, { ...st, size });
  }
  textNode(parent, o) { return textNode(parent, { font: 'display', ...o }); }
}

export function inScreen(node) {
  for (let n = node; n; n = n.parent) if (n.isScreen) return true;
  return false;
}

// ---------- building ----------
export async function buildFilm(spec, env) {
  const film = new Film(spec, env);
  const stage = env.stage;
  stage.style.width = `${film.W}px`;
  stage.style.height = `${film.H}px`;
  const dpr = env.dpr || 1;

  const groundEl = document.createElement('div');
  groundEl.className = 'lf-ground';
  const worldCanvas = document.createElement('canvas');
  const fxLayer = document.createElement('div');
  const camLayer = document.createElement('div');
  const screenCanvas = document.createElement('canvas');
  const overlay = document.createElement('div');
  for (const [el, cls] of [[worldCanvas, 'lf-canvas lf-world-fx'], [fxLayer, 'lf-fx'], [camLayer, 'lf-cam'], [screenCanvas, 'lf-canvas lf-screen-fx'], [overlay, 'lf-overlay']]) el.className = cls;
  for (const cv of [worldCanvas, screenCanvas]) {
    cv.width = Math.round(film.W * dpr); cv.height = Math.round(film.H * dpr);
    cv.style.width = `${film.W}px`; cv.style.height = `${film.H}px`;
  }
  stage.append(groundEl, worldCanvas, fxLayer, screenCanvas, overlay);
  fxLayer.appendChild(camLayer);
  const world = new Node({ name: 'world' });
  world.el.classList.add('lf-world');
  camLayer.appendChild(world.el);
  film.world = world;
  // Screen-space content per scene (words over pictures) and overlays (captions): never under the camera.
  const screenLayer = document.createElement('div');
  screenLayer.className = 'lf-screen';
  stage.insertBefore(screenLayer, screenCanvas);
  const screenRoot = new Node({ name: 'screen' });
  screenRoot.isScreen = true;
  screenLayer.appendChild(screenRoot.el);
  screenRoot.rest({ x: film.W / 2, y: film.H / 2 });
  const overlayRoot = new Node({ name: 'overlay' });
  overlayRoot.isScreen = true;
  overlay.appendChild(overlayRoot.el);
  film.screenRoot = screenRoot;
  film.overlayRoot = overlayRoot;
  film.overlay = overlay;
  film.stage = stage;

  if (spec.ground) film.ground(0, spec.ground);
  if (spec.texture) film.addFx(FX.texture(spec.texture));

  // Scenes, in order. A scene starts where the previous ended unless it says `start`.
  let t = 0;
  const scenes = spec.scenes || [];
  for (let i = 0; i < scenes.length; i++) {
    const def = scenes[i];
    if (!def || typeof def.build !== 'function') throw new Error(`scene ${i + 1} is not a block (use one of the kit's blocks)`);
    const t0 = def.opts?.start != null ? film.time(def.opts.start) : t;
    const group = world.add({ name: `scene-${i + 1}` });
    group.isScene = true;
    const screen = screenRoot.add({ name: `scene-${i + 1}-screen` });
    const sc = { index: i, t0, t1: t0, group, screen, def, move: { push: 0.03, roll: 0.5, ...(def.opts?.move || {}) } };
    film.scenes.push(sc);
    const ctx = makeCtx(film, sc);
    const built = await def.build(ctx);
    const len = film.time(def.opts?.len ?? built.len);
    if (!(len > 0)) throw new Error(`scene ${i + 1} (${def.kind}) has no length`);
    sc.t1 = t0 + len;
    sc.update = built.update || (() => {});
    sc.camera = built.camera || null;
    sc.built = built;
    t = sc.t1;
  }
  // Scene joins: the exit of one scene and the entrance of the next.
  for (let i = 0; i < film.scenes.length; i++) {
    const sc = film.scenes[i], next = film.scenes[i + 1];
    if (!next) continue;
    const c = next.t0;
    const exit = sc.def.opts?.exit || 'cut';
    const enter = next.def.opts?.enter || 'cut';
    const nextGround = next.built.ground0 || film.pal.ink;
    if (exit === 'through' && sc.built.through) {
      const tgt = sc.built.through();
      if (!film.through({ ...tgt, t: c, nextGround, d: sc.def.opts?.throughD })) {}
    } else if (exit === 'collapse') {
      film.collapse({ group: sc.group, t: c });
      film.grow({ group: next.group, t: c });
    } else if (enter === 'whipX' || enter === 'whipY' || exit === 'whipX' || exit === 'whipY') {
      const w = enter.startsWith('whip') ? enter : exit;
      film.whip(c, { dir: w === 'whipX' ? [1, 0] : [0, 1] });
    } else if (enter === 'zoom') {
      film.cut(c);
      film.arrive(c, { from: 2.2, d: 0.45 });
      film.fastWindow(c, c + 0.25, 10);
    } else {
      film.cut(c);
    }
  }
  film.duration = spec.duration != null ? film.time(spec.duration) : t;
  // Overlays (captions) run across scenes in screen space.
  film.overlays = [];
  film.buildingOverlay = true;
  for (const def of [...(spec.overlays || []), ...(spec.captions ? [spec.captions] : [])]) {
    const sc = { index: -1, t0: 0, t1: film.duration, group: overlayRoot, screen: overlayRoot, def, move: {} };
    const built = await def.build(makeCtx(film, sc));
    film.overlays.push({ ...built, sc });
  }
  film.buildingOverlay = false;
  film.frames = Math.round(film.duration * film.fps);
  film.sortGrounds();
  film.reg.cuts = [...new Set(film.reg.cuts.filter(c => c > 0 && c < film.duration))].sort((a, b) => a - b);
  film.reg.cues.sort((a, b) => a.t - b.t);
  film.worldCanvas = worldCanvas; film.screenCanvas = screenCanvas;
  film.groundEl = groundEl; film.fxLayer = fxLayer; film.camLayer = camLayer;
  film.dpr = dpr;
  return film;
}

// The context a block builds with.
function makeCtx(film, sc) {
  const ctx = {
    film, W: film.W, H: film.H, u: film.u, fps: film.fps, portrait: film.portrait, safe: film.safe,
    pal: film.pal, t0: sc.t0, group: sc.group, screenGroup: sc.screen, scene: sc,
    time: v => film.time(v), b: n => film.b(n), at: v => sc.t0 + film.time(v),
    locked: t => film.locked(t), frameIndex: t => film.frameIndex(t),
    colour: c => film.colour(c), typeOn: g => film.typeOn(g), groundAt: t => film.groundAt(t),
    ground: (t, c, o) => film.ground(t, c, o),
    cue: e => film.cue(e), cut: t => film.cut(t), rest: (a, b, l) => film.rest(a, b, l),
    smear: (a, b, f) => film.smear(a, b, f), fast: (a, b, n) => film.fastWindow(a, b, n),
    whip: (t, o) => film.whip(t, o), shake: (t, o) => film.shake(t, o), bump: (t, o) => film.bump(t, o),
    arrive: (t, o) => film.arrive(t, o), through: o => film.through(o), collapse: o => film.collapse(o),
    grow: o => film.grow(o), zoomIn: o => film.zoomIn(o),
    text: o => film.text(o), occluder: (n, c) => film.occluder(n, c), plate: (n, c) => film.plate(n, c),
    caption: c => film.caption(c), warn: m => film.warn(m), error: m => film.error(m),
    fitText: (parent, o) => film.fitText(parent, o), textNode: (parent, o) => film.textNode(parent, o),
    measure, typed, fx: {
      speed: o => film.addFx(FX.speedLines(o)), burst: o => film.addFx(FX.burst(o)),
      comet: o => film.addFx(FX.comet(o)), flash: o => {
        const f = film.addFx(FX.flash(o));
        film.reg.flashes.push([r6(o.t), r6(o.t + (o.d ?? 0.12)), o.label || 'light flash']);
        return f;
      },
      texture: o => film.addFx(FX.texture(o)),
    },
    screenOf: (n, x, y) => film.screenOf(n, x, y), worldOf: (n, x, y) => film.worldOf(n, x, y),
    frameAt: (P, S, z, r) => film.frameAt(P, S, z, r),
    music: m => { film.music = { ...(film.music || {}), ...m }; },
    track: (n, id, o) => film.track(n, id, o),
    facts: film.facts, fact: id => findFact(film.facts, id),
    ease, curves, clamp, lerp, loglerp, progress, decay, token, rng, hash, noise1, mix, hex, parse, luminance,
    env: film.env,
  };
  return ctx;
}

export function findFact(facts, id) {
  if (!facts || !id) return null;
  const list = Array.isArray(facts.claims) ? facts.claims : Array.isArray(facts) ? facts : Object.entries(facts.claims || facts).map(([k, v]) => ({ id: k, ...v }));
  return list.find(f => f.id === id) || null;
}

// ---------- evaluating and drawing ----------
export function evaluate(film, t) {
  film.world.resetTree();
  film.screenRoot.resetTree();
  film.overlayRoot.resetTree();
  const T = clamp(t, 0, film.duration);
  for (const sc of film.scenes) {
    const last = sc === film.scenes[film.scenes.length - 1];
    const active = T >= sc.t0 - 1e-9 && (T < sc.t1 - 1e-9 || (last && T <= film.duration + 1e-9));
    sc.active = active;
    sc.group.opacity = active ? 1 : 0;
    sc.screen.opacity = active ? 1 : 0;
    if (active) sc.update(T);
  }
  for (const ov of film.overlays) if (ov.update) ov.update(T);
  for (const w of film.windows) {
    if (!w.mirror) continue;
    const n = w.node, m = w.mirror;
    m.x = n.x; m.y = n.y; m.s = n.s; m.sx = n.sx; m.sy = n.sy; m.rot = n.rot;
    m.opacity = T >= w.t0 && T < w.t1 ? n.opacity : 0;
    const vector = !!n.flat && T >= w.t0 && T < w.t1;
    if (m.vecShown !== vector) { m.vec.style.visibility = vector ? 'visible' : 'hidden'; m.vecShown = vector; }
    if (vector) n.opacity = 0;
  }
  for (const g of film.groupTerms) {
    if (T < g.t0 || T >= g.t1) continue;
    const p = (T - g.t0) / (g.t1 - g.t0);
    g.node.s *= g.f(p);
    g.node.rot += g.rot * (g.grow ? 1 - p : p);
  }
  film._camNow = film.cameraAt(T);
  film._t = T;
  return film._camNow;
}

const cssMatrix = m => `matrix(${m.map(v => +v.toFixed(6)).join(',')})`;

export function draw(film) {
  const t = film._t, cam = film._camNow;
  film.world.flush();
  film.screenRoot.flush();
  film.overlayRoot.flush();
  film.groundEl.style.background = film.groundAt(t);
  film.camLayer.style.transform = cssMatrix(cam.camM);
  film.fxLayer.style.transform = cssMatrix(cam.fxM);
  for (const w of film.windows) w.el.style.visibility = t >= w.t0 && t < w.t1 ? 'visible' : 'hidden';
  const env = {
    W: film.W, H: film.H, u: film.u, zoom: cam.zoom,
    groundAt: x => film.groundAt(x), groundLum: x => film.groundLum(x), typeOn: g => film.typeOn(g),
    visibleWorld: () => {
      const inv = invert(cam.M);
      const pts = [[0, 0], [film.W, 0], [0, film.H], [film.W, film.H]].map(p => apply(inv, p[0], p[1]));
      return [Math.min(...pts.map(p => p[0])), Math.min(...pts.map(p => p[1])), Math.max(...pts.map(p => p[0])), Math.max(...pts.map(p => p[1]))];
    },
  };
  const dpr = film.dpr;
  const wc = film.worldCanvas.getContext('2d');
  wc.setTransform(1, 0, 0, 1, 0, 0);
  wc.clearRect(0, 0, film.worldCanvas.width, film.worldCanvas.height);
  const M = cam.M;
  wc.setTransform(M[0] * dpr, M[1] * dpr, M[2] * dpr, M[3] * dpr, M[4] * dpr, M[5] * dpr);
  for (const e of film.fx) if (e.layer === 'world') e.draw(wc, t, env);
  const scx = film.screenCanvas.getContext('2d');
  scx.setTransform(1, 0, 0, 1, 0, 0);
  scx.clearRect(0, 0, film.screenCanvas.width, film.screenCanvas.height);
  scx.setTransform(dpr, 0, 0, dpr, 0, 0);
  for (const e of film.fx) if (e.layer === 'screen') e.draw(scx, t, env);
  film.worldCanvas.style.mixBlendMode = 'normal';
  if (film.drawOverlay) film.drawOverlay(t);
  if (film.env.animatic) drawAnimatic(film, t);
}

// ?animatic: a small time, frame, bar/beat and scene readout for review notes ("at beat 23").
// Never on in a normal render; not a registered text.
function drawAnimatic(film, t) {
  if (!film.animaticEl) {
    const el = document.createElement('div');
    const u = film.u;
    el.className = 'lf-animatic';
    el.style.cssText = `position:absolute;right:${u * 1.6}px;top:${u * 1.6}px;padding:${u * 0.6}px ${u * 1}px;` +
      `background:rgba(8,10,14,0.82);color:#f2f4f8;font:600 ${Math.max(12, u * 2.1)}px/1.25 "LF Mono", ui-monospace, monospace;` +
      `border-radius:${u * 0.5}px;white-space:pre;z-index:90;text-align:right;letter-spacing:0.02em;`;
    film.stage.appendChild(el);
    film.animaticEl = el;
  }
  const k = Math.round(t * film.fps);
  const sc = film.sceneAt(t);
  const name = sc.def.opts?.name || `${sc.index + 1} ${sc.def.kind}`;
  let line2 = '';
  if (film.beat) {
    const bt = ((t - film.beat.offset) * film.beat.bpm) / 60;
    const bi = Math.floor(bt + 1e-6);
    line2 = `beat ${bt.toFixed(2)}  bar ${Math.floor(bi / 4) + 1}.${(((bi % 4) + 4) % 4) + 1}`;
  }
  film.animaticEl.textContent = [`${t.toFixed(3)} s  f ${k}`, line2, `scene ${name}`].filter(Boolean).join(String.fromCharCode(10));
}
