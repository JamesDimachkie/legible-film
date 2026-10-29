// Easing curves and the motion-token scale. Every curve maps [0,1] to [0,1] and is clamped.

export const clamp = (v, a = 0, b = 1) => (v < a ? a : v > b ? b : v);
export const lerp = (a, b, t) => a + (b - a) * t;
export const progress = (t, t0, t1) => (t1 <= t0 ? (t >= t1 ? 1 : 0) : clamp((t - t0) / (t1 - t0)));
// Zoom geometrically: interpolate the logarithm of the scale.
export const loglerp = (a, b, t) => Math.exp(lerp(Math.log(a), Math.log(b), t));

// A cubic Bezier timing curve through (0,0), (x1,y1), (x2,y2), (1,1), solved by bisection
// (monotone in x for x1, x2 in [0,1]), so no curve can overshoot the time axis.
export function bezier(x1, y1, x2, y2) {
  const coord = (p1, p2, s) => 3 * (1 - s) * (1 - s) * s * p1 + 3 * (1 - s) * s * s * p2 + s * s * s;
  return p => {
    if (p <= 0) return 0;
    if (p >= 1) return 1;
    let lo = 0, hi = 1, s = p;
    for (let i = 0; i < 30; i++) {
      s = (lo + hi) / 2;
      if (coord(x1, x2, s) < p) lo = s; else hi = s;
    }
    return coord(y1, y2, s);
  };
}

const pow = k => p => Math.pow(clamp(p), k);
const powOut = k => p => 1 - Math.pow(1 - clamp(p), k);

export const ease = {
  linear: p => clamp(p),
  in2: pow(2), in3: pow(3), in4: pow(4),
  out2: powOut(2), out3: powOut(3), out4: powOut(4), out5: powOut(5),
  inOut2: p => (p = clamp(p), p < 0.5 ? 2 * p * p : 1 - 2 * (1 - p) * (1 - p)),
  inOut3: p => (p = clamp(p), p < 0.5 ? 4 * p * p * p : 1 - 4 * (1 - p) ** 3),
  // Gentle at both ends: the only curve for opacity fades (no first-frame pop).
  fade: p => 0.5 - 0.5 * Math.cos(Math.PI * clamp(p)),
  outExpo: p => (p = clamp(p), p >= 1 ? 1 : (1 - Math.pow(2, -10 * p)) / (1 - Math.pow(2, -10))),
  inExpo: p => (p = clamp(p), p <= 0 ? 0 : (Math.pow(2, 10 * p - 10) - Math.pow(2, -10)) / (1 - Math.pow(2, -10))),
};

// Named curves, each with one job. Use these rather than ad-hoc curves.
export const curves = {
  arrive: bezier(0.18, 0.86, 0.28, 1),    // things that land and decelerate into place
  settle: bezier(0.3, 0.6, 0.35, 1),      // the last few percent of a landing
  exit: bezier(0.55, 0, 0.92, 0.45),      // departures accelerate away
  camera: bezier(0.62, 0, 0.32, 1),       // camera moves ease at both ends
  drift: p => clamp(p),                   // constant-rate drift
  open: bezier(0.22, 0.78, 0.22, 1),      // a panel or menu opening from its trigger
  land: pow(2.2),                         // a word accelerating into its contact frame
  fade: ease.fade,
};
Object.defineProperty(curves, 'slam', { get: () => curves.land, enumerable: false });   // the 1.2.0 name

// Motion tokens for interface-like devices (terminal, panels, chips, menus).
// Arrivals are longer than exits, small elements faster than large ones, and duration grows with
// the distance travelled (as a fraction of the frame diagonal).
const BASE = { micro: 0.09, small: 0.16, medium: 0.24, large: 0.34, stage: 0.55 };
export function token(kind = 'arrive', size = 'medium', distance = 0) {
  const base = BASE[size] ?? BASE.medium;
  const k = kind === 'exit' ? 0.68 : kind === 'state' ? 0.6 : 1;
  const d = base * k * (1 + 0.6 * clamp(distance));
  const curve = kind === 'exit' ? curves.exit : kind === 'open' ? curves.open : kind === 'state' ? curves.fade : curves.arrive;
  return { d, curve };
}
export const tokens = { BASE, token };

// Shape helpers for impulses (pure functions of time since the event).
export const decay = (dt, tau) => (dt < 0 ? 0 : Math.exp(-dt / tau));
export const pulse = (dt, rise, tau) => (dt < 0 ? 0 : dt < rise ? ease.out2(dt / rise) : Math.exp(-(dt - rise) / tau));
