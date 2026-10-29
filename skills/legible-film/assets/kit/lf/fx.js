// Effects. Each has one job and is a pure function of t; seeds are fixed at build time.
//   speed:  inward speed lines charging into a point before a hit
//   burst:  a ring, rays and sparks for the biggest hits only
//   tracer:  a thread drawn in two additive passes (wide dim glow, thin bright core) whose tail
//           drains into its head when it arrives
//   flash:  a full-frame light flash (registered, so flashing is predicted before a render)
//   texture: a sparse world-space dot grid or ghost rows of type that moves with the camera

import { rng } from './rng.js';
import { ease, clamp, decay } from './ease.js';
import { parse, alphaForDifference, canvasOver, luminance } from './color.js';
import { FAMILIES } from './text.js';

const rgba = (c, a) => {
  const [r, g, b] = parse(c);
  return `rgba(${Math.round(r * 255)},${Math.round(g * 255)},${Math.round(b * 255)},${clamp(a).toFixed(4)})`;
};

export function speedLines(o) {
  const R = rng(o.seed ?? 7);
  const n = o.count ?? 26;
  const lines = Array.from({ length: n }, (_, i) => ({
    a: ((i + R() * 0.8) / n) * Math.PI * 2,
    start: R() * 0.55,                  // stagger inside the window
    len: 0.12 + R() * 0.24,             // fraction of the frame half-diagonal
    width: 0.3 + R() * 0.8,             // fraction of a frame unit
    stop: 0.3 + R() * 0.2,              // how close to the point it gets (fraction of half-diagonal)
  }));
  return {
    kind: 'speed', layer: 'screen', t0: o.t0, t1: o.t1,
    draw(c, t, env) {
      if (t < o.t0 || t >= o.t1 + 0.02) return;
      const [px, py] = typeof o.at === 'function' ? o.at(t) : o.at || [env.W / 2, env.H / 2];
      const hd = Math.hypot(env.W, env.H) / 2;
      const span = o.t1 - o.t0;
      c.save();
      for (const l of lines) {
        const p = (t - o.t0 - l.start * span * 0.6) / (span * (1 - l.start * 0.6));
        if (p <= 0 || p > 1) continue;
        const q = ease.in2(p);
        const head = hd * (1.15 - (1.15 - l.stop) * q);
        const tail = head + hd * l.len * (0.4 + 0.6 * (1 - q));
        const w = l.width * env.u * (0.6 + 0.8 * q);
        const ca = Math.cos(l.a), sa = Math.sin(l.a);
        const nx = -sa, ny = ca;
        const a = (o.alpha ?? 0.85) * ease.fade(Math.min(1, p * 3)) * (p > 0.92 ? (1 - p) / 0.08 : 1);
        c.fillStyle = rgba(o.color, a);
        c.beginPath();
        c.moveTo(px + ca * head + nx * w * 0.15, py + sa * head + ny * w * 0.15);
        c.lineTo(px + ca * tail + nx * w, py + sa * tail + ny * w);
        c.lineTo(px + ca * tail - nx * w, py + sa * tail - ny * w);
        c.lineTo(px + ca * head - nx * w * 0.15, py + sa * head - ny * w * 0.15);
        c.closePath();
        c.fill();
      }
      c.restore();
    },
  };
}

export function burst(o) {
  const R = rng(o.seed ?? 11);
  const sparks = Array.from({ length: o.sparks ?? 18 }, (_, i) => ({
    a: ((i + R() * 0.9) / (o.sparks ?? 18)) * Math.PI * 2,
    v: 0.35 + R() * 0.55, len: 0.04 + R() * 0.07, w: 0.5 + R() * 0.7,
  }));
  const rays = Array.from({ length: o.rays ?? 10 }, (_, i) => ({ a: ((i + 0.5 * R()) / (o.rays ?? 10)) * Math.PI * 2, w: 0.02 + R() * 0.03 }));
  const D = 0.6;
  return {
    kind: 'burst', layer: 'screen', t0: o.t, t1: o.t + D,
    draw(c, t, env) {
      const dt = t - o.t;
      if (dt < 0 || dt > D) return;
      const [px, py] = typeof o.at === 'function' ? o.at(t) : o.at || [env.W / 2, env.H / 2];
      const m = Math.min(env.W, env.H) * (o.size ?? 0.5);
      c.save();
      // Rays: brief wedges, gone in about a tenth of a second.
      if (dt < 0.14) {
        const a = (1 - dt / 0.14) * (o.alpha ?? 0.9);
        c.fillStyle = rgba(o.color, a * 0.55);
        for (const r of rays) {
          const r0 = m * (0.3 + dt * 2), r1 = m * (1.2 + dt * 4);
          c.beginPath();
          c.moveTo(px + Math.cos(r.a - r.w * 0.2) * r0, py + Math.sin(r.a - r.w * 0.2) * r0);
          c.lineTo(px + Math.cos(r.a - r.w) * r1, py + Math.sin(r.a - r.w) * r1);
          c.lineTo(px + Math.cos(r.a + r.w) * r1, py + Math.sin(r.a + r.w) * r1);
          c.lineTo(px + Math.cos(r.a + r.w * 0.2) * r0, py + Math.sin(r.a + r.w * 0.2) * r0);
          c.fill();
        }
      }
      // Ring.
      const rr = m * (0.25 + 0.95 * (1 - Math.exp(-dt / 0.11)));
      const lw = env.u * 2.2 * Math.exp(-dt / 0.13);
      if (lw > 0.3) {
        c.strokeStyle = rgba(o.ring ?? o.color, (o.alpha ?? 0.9) * decay(dt, 0.2));
        c.lineWidth = lw;
        c.beginPath(); c.arc(px, py, rr, 0, Math.PI * 2); c.stroke();
      }
      // Sparks: decelerating streaks that shrink and fade.
      const travel = 1 - Math.exp(-dt / 0.13);
      for (const s of sparks) {
        const r0 = m * (0.35 + s.v * 1.1 * travel);
        const len = m * s.len * (1 - dt / D);
        const ca = Math.cos(s.a), sa = Math.sin(s.a);
        c.strokeStyle = rgba(o.spark ?? o.color, (o.alpha ?? 0.9) * (1 - dt / D));
        c.lineWidth = env.u * s.w;
        c.lineCap = 'round';
        c.beginPath();
        c.moveTo(px + ca * r0, py + sa * r0);
        c.lineTo(px + ca * (r0 + len), py + sa * (r0 + len));
        c.stroke();
      }
      c.restore();
    },
  };
}

// Points along a polyline by arc length.
function along(pts) {
  const seg = [0];
  for (let i = 1; i < pts.length; i++) seg.push(seg[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const total = seg[seg.length - 1] || 1;
  const at = s => {
    const d = clamp(s) * total;
    let i = 1;
    while (i < seg.length - 1 && seg[i] < d) i++;
    const f = (d - seg[i - 1]) / Math.max(1e-6, seg[i] - seg[i - 1]);
    return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f];
  };
  return { at, total };
}

// A smooth path through points (Catmull-Rom sampled to a polyline).
export function smoothPath(points, steps = 24) {
  if (points.length < 3) {
    const out = [];
    for (let i = 0; i <= steps; i++) {
      const f = i / steps;
      out.push([points[0][0] + (points[1][0] - points[0][0]) * f, points[0][1] + (points[1][1] - points[0][1]) * f]);
    }
    return out;
  }
  const P = [points[0], ...points, points[points.length - 1]];
  const out = [];
  for (let i = 1; i < P.length - 2; i++) {
    for (let k = 0; k < steps; k++) {
      const t = k / steps, t2 = t * t, t3 = t2 * t;
      const f = j => 0.5 * ((2 * P[i][j]) + (-P[i - 1][j] + P[i + 1][j]) * t + (2 * P[i - 1][j] - 5 * P[i][j] + 4 * P[i + 1][j] - P[i + 2][j]) * t2 + (-P[i - 1][j] + 3 * P[i][j] - 3 * P[i + 1][j] + P[i + 2][j]) * t3);
      out.push([f(0), f(1)]);
    }
  }
  out.push(points[points.length - 1]);
  return out;
}

// o.path(t) -> world points; o.t0..o.t1 head travel; o.tail: tail length as a fraction of the path;
// o.drain: seconds for the tail to drain into the head after arrival; o.hold: keep the drawn line after.
export function tracer(o) {
  const drain = o.drain ?? 0.3;
  return {
    kind: 'tracer', layer: 'world', t0: o.t0, t1: o.t1 + drain + (o.hold ?? 0),
    head(t) {
      return (o.curve || ease.inOut2)((t - o.t0) / (o.t1 - o.t0));
    },
    until: o.until ?? o.t1 + drain + (o.hold ?? 0),
    draw(c, t, env) {
      if (t < o.t0 || t >= this.until) return;
      const pts = smoothPath(o.path(t));
      const A = along(pts);
      const head = this.head(t);
      const tailLen = o.tail ?? 0.35;
      let tail = Math.max(0, head - tailLen);
      if (t > o.t1) tail = Math.min(1, tailLen > 0 ? 1 - tailLen + tailLen * ((t - o.t1) / drain) : 1);
      const additive = o.blend === 'add' || (o.blend !== 'normal' && env.groundLum(t) < 0.3);
      c.save();
      c.lineCap = 'round'; c.lineJoin = 'round';
      const w = env.u * (o.width ?? 0.5);
      // A kept thread leaves the travelled line drawn, dimmer than the tracer.
      if (o.keep) {
        c.globalCompositeOperation = 'source-over';
        c.strokeStyle = rgba(o.lineColour ?? o.color, o.keepAlpha ?? 0.55);
        c.lineWidth = (w * 0.7) / env.zoom;
        c.beginPath();
        const m = 48;
        for (let i = 0; i <= m; i++) { const p = A.at((head * i) / m); i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]); }
        c.stroke();
      }
      c.globalCompositeOperation = additive ? 'lighter' : 'source-over';
      const n = 40;
      for (const pass of [{ w: w * 7, a: 0.16 }, { w: w * 2.2, a: 0.35 }, { w, a: 1 }]) {
        for (let i = 0; i < n; i++) {
          const s0 = tail + (head - tail) * (i / n), s1 = tail + (head - tail) * ((i + 1) / n);
          if (s1 <= s0) continue;
          const f = (i + 1) / n;                       // brighter toward the head
          const p0 = A.at(s0), p1 = A.at(s1);
          c.strokeStyle = rgba(pass.a === 1 ? (o.core ?? o.color) : o.color, pass.a * Math.pow(f, 1.6));
          c.lineWidth = (pass.w / env.zoom) * (pass.a === 1 ? 0.6 + 0.4 * f : 1);
          c.beginPath(); c.moveTo(p0[0], p0[1]); c.lineTo(p1[0], p1[1]); c.stroke();
        }
      }
      // The head: a bright point with a soft halo, gone once the tail has drained into it.
      const hp = A.at(head);
      const ha = t > o.t1 ? 1 - clamp((t - o.t1) / drain) : 1;
      if (ha > 0) {
        const g = c.createRadialGradient(hp[0], hp[1], 0, hp[0], hp[1], w * 9 / env.zoom);
        g.addColorStop(0, rgba(o.core ?? o.color, 0.95 * ha));
        g.addColorStop(0.25, rgba(o.color, 0.45 * ha));
        g.addColorStop(1, rgba(o.color, 0));
        c.fillStyle = g;
        c.beginPath(); c.arc(hp[0], hp[1], w * 9 / env.zoom, 0, Math.PI * 2); c.fill();
      }
      c.restore();
    },
  };
}

export function flash(o) {
  const d = o.d ?? 0.12;
  const env = t => {
    const dt = t - o.t;
    if (dt < 0 || dt > d) return 0;
    return (o.peak ?? 0.6) * (dt < 0.02 ? dt / 0.02 : Math.pow(1 - (dt - 0.02) / (d - 0.02), 2));
  };
  return {
    kind: 'flash', layer: 'screen', t0: o.t, t1: o.t + d, color: o.color, alphaAt: env,
    draw(c, t, e) {
      const a = env(t);
      if (a <= 0) return;
      c.fillStyle = rgba(o.color, a);
      c.fillRect(0, 0, e.W, e.H);
    },
  };
}

// World texture: drawn in world space under the content, so camera moves read over flat grounds.
export function texture(o) {
  const R = rng(o.seed ?? 3);
  const rows = (o.words || []).length ? o.words : null;
  const offs = Array.from({ length: 64 }, () => R());
  // Default contrast: the alpha giving a light-dark difference of `maxDiff` cd/m2 on each ground
  // (8 by default), clearly under the 20 cd/m2 at which a regular pattern can be a risk.
  const cache = new Map();
  return {
    kind: 'texture', id: 'world-texture', layer: 'world', t0: o.t0 ?? 0, t1: o.t1 ?? 1e9, spec: o,
    alphaAt(t, ground, col) {
      const k = ground + col;
      if (!cache.has(k)) cache.set(k, o.alpha ?? alphaForDifference(ground, col, o.maxDiff ?? 8, 0.3));
      return cache.get(k) * (o.fade ? o.fade(t) : 1);
    },
    // What analyse() needs for the pattern check at time t.
    pattern(t, env) {
      if (t < (o.t0 ?? 0) || t >= (o.t1 ?? 1e9)) return null;
      const ground = env.groundAt(t), col = o.color || env.typeOn(ground);
      const a = this.alphaAt(t, ground, col);
      const dot = canvasOver(ground, col, a);
      const L0 = luminance(ground) * 100, L1 = luminance(dot) * 100;
      const sp = env.u * (o.kind === 'rows' ? (o.size ?? 7) : (o.spacing ?? 4.2)) * env.zoom;
      if (a <= 0.002 || sp < 6) return null;
      return { pairs: Math.max(env.W, env.H) / sp, dark_cdm2: Math.min(L0, L1), diff_cdm2: Math.abs(L1 - L0), area: 1 };
    },
    draw(c, t, env) {
      if (t < (o.t0 ?? 0) || t >= (o.t1 ?? 1e9)) return;
      const ground = env.groundAt(t);
      const col = o.color || env.typeOn(ground);
      const a = this.alphaAt(t, ground, col);
      if (a <= 0.002) return;
      const [x0, y0, x1, y1] = env.visibleWorld();
      c.save();
      if (o.kind === 'rows' && rows) {
        const lh = env.u * (o.size ?? 7);
        c.font = `${o.weight ?? 800} ${lh * 0.82}px "${FAMILIES.display}"`;
        c.fillStyle = rgba(col, a);
        c.textBaseline = 'middle';
        const j0 = Math.floor(y0 / lh) - 1, j1 = Math.ceil(y1 / lh) + 1;
        if (j1 - j0 > 200) { c.restore(); return; }
        for (let j = j0; j <= j1; j++) {
          const word = rows[((j % rows.length) + rows.length) % rows.length] + '   ';
          const ww = c.measureText(word).width;
          const shift = offs[((j % 64) + 64) % 64] * ww + (o.drift ?? 0) * t * (j % 2 ? 1 : -1) * env.u;
          let x = Math.floor((x0 - shift) / ww) * ww + shift;
          for (let k = 0; x < x1 && k < 60; x += ww, k++) c.fillText(word, x, j * lh);
        }
      } else {
        const sp = env.u * (o.spacing ?? 4.2);
        if (sp * env.zoom < 6) { c.restore(); return; }
        const r = env.u * (o.dot ?? 0.2);
        c.fillStyle = rgba(col, a);
        const i0 = Math.floor(x0 / sp), i1 = Math.ceil(x1 / sp);
        const j0 = Math.floor(y0 / sp), j1 = Math.ceil(y1 / sp);
        if ((i1 - i0) * (j1 - j0) > 40000) { c.restore(); return; }
        for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) {
          c.beginPath(); c.arc(i * sp, j * sp, r, 0, Math.PI * 2); c.fill();
        }
      }
      c.restore();
    },
  };
}
