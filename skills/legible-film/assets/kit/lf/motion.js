// Per-element motion checks and regular-pattern checks for analyse(). Measurements of the film's own
// state, reported as warnings with times and ids; a person still judges motion at speed.
//
// Motion (screen space, what the eye sees): each element's track is split into moves at cuts and
// wherever it is absent or at rest. Reported:
//   jumps     a frame-to-frame step far larger than its neighbours in the same move (steps on the
//             frame a registered camera bump or shake lands are counted as jumps_on_hits instead)
//   speed     a step longer than one of the element's own widths (it strobes without motion blur);
//             steps inside smear or fast windows are counted as blurred, not warned
//   onsets    two unrelated elements starting to move within two frames while a text is being read
//             (from camera-free coordinates, so a camera move is one cause, not many)
//   geometry  negative size or scale, opacity outside 0..1, negative blur
// Elements registered as `discrete` (a caret stepping by whole characters) get the geometry and
// onset checks only.
//
// Patterns (Ofcom, Section Two guidance, Annex 1, 2017): a regular pattern is a risk only when all
// hold: more than five light-dark pairs across the screen; the darker below 160 cd/m2 and a
// difference of at least 20 cd/m2 (relative luminance x 100, for a 100 cd/m2 SDR white); and it
// covers more than 40% of the screen if stationary, or more than 25% if it changes direction,
// oscillates, flashes or reverses contrast. A pattern flowing smoothly in one direction is exempt.

export const MOTION_THRESHOLDS = {
  jump_ratio: 5,            // a step this many times the move's median step...
  jump_neighbour_ratio: 2,  // ...and this many times both neighbouring steps...
  jump_min_px: 6,           // ...and at least this many pixels
  speed_widths_per_frame: 1,
  onset_frames: 2,
  rest_px: 0.05,            // below this a frame counts as at rest
};
export const PATTERN_THRESHOLDS = { min_pairs: 5, dark_max_cdm2: 160, min_diff_cdm2: 20, area_still: 0.4, area_changing: 0.25, white_cdm2: 100 };

const inWin = (t, wins) => wins.some(w => t >= w[0] - 1e-9 && t <= w[1] + 1e-9);

export function motionReport({ fps, n, cuts, blurWins, hits = [], elements, readable }) {
  const T = MOTION_THRESHOLDS;
  const warnings = [], summary = [];
  const cutBetween = k => cuts.some(c => c > (k - 1) / fps + 1e-9 && c <= k / fps + 1e-9);
  const onsets = [];
  for (const e of elements) {
    const s = e.samples;               // per frame: [present, cx, cy, w, h, lx, ly, lw, lh]
    const at = (k, i) => s[k * 9 + i];
    let moves = 0, maxStep = 0, maxWidths = 0, jumps = 0, jumpsOnHits = 0, fastUnblurred = 0, fastBlurred = 0;
    // Screen-space moves.
    let cur = null;
    const flush = () => {
      if (!cur || cur.steps.length < 2) { cur = null; return; }
      moves++;
      const st = cur.steps.map(x => x.d);
      const sorted = [...st].sort((a, b) => a - b);
      const med = sorted[Math.floor(sorted.length / 2)] || 0;
      cur.steps.forEach((x, i) => {
        const prev = i > 0 ? st[i - 1] : 0, next = i < st.length - 1 ? st[i + 1] : 0;
        if (x.d > T.jump_min_px && x.d > T.jump_ratio * Math.max(med, 0.5) && x.d > T.jump_neighbour_ratio * Math.max(prev, next)) {
          // A step on the frame a designed hit lands (camera bump or shake) is the hit itself.
          if (hits.some(h => x.t >= h[0] - 0.5 / fps && x.t <= h[1])) { jumpsOnHits++; return; }
          jumps++;
          if (!inWin(x.t, blurWins)) warnings.push(`motion jump: ${e.id} steps ${x.d.toFixed(1)} px at ${x.t.toFixed(3)} s (move median ${med.toFixed(1)} px)`);
        }
      });
      cur = null;
    };
    for (let k = 1; k < n && !e.discrete; k++) {
      const t = k / fps;
      if (!at(k, 0) || !at(k - 1, 0) || cutBetween(k)) { flush(); continue; }
      const dx = at(k, 1) - at(k - 1, 1), dy = at(k, 2) - at(k - 1, 2);
      const d = Math.hypot(dx, dy) + (Math.abs(at(k, 3) - at(k - 1, 3)) + Math.abs(at(k, 4) - at(k - 1, 4))) / 2;
      if (d < T.rest_px) { flush(); continue; }
      if (!cur) cur = { steps: [] };
      cur.steps.push({ t, d });
      maxStep = Math.max(maxStep, d);
      // Own size: the larger dimension (a card turning edge-on is not a fast mover).
      const w = Math.max(1, Math.min(Math.max(at(k, 3), at(k, 4)), Math.max(at(k - 1, 3), at(k - 1, 4))));
      const widths = Math.hypot(dx, dy) / w;
      maxWidths = Math.max(maxWidths, widths);
      if (widths > T.speed_widths_per_frame) {
        if (inWin(t, blurWins)) fastBlurred++;
        else {
          fastUnblurred++;
          if (fastUnblurred <= 3) warnings.push(`motion speed: ${e.id} travels ${widths.toFixed(2)} of its own widths in one frame at ${t.toFixed(3)} s outside any smear or fast window (it strobes without blur; threshold ${T.speed_widths_per_frame})`);
        }
      }
    }
    flush();
    // Camera-free onsets.
    let moving = false;
    for (let k = 1; k < n; k++) {
      if (!at(k, 0) || !at(k - 1, 0) || cutBetween(k)) { moving = false; continue; }
      const d = Math.hypot(at(k, 5) - at(k - 1, 5), at(k, 6) - at(k - 1, 6)) + (Math.abs(at(k, 7) - at(k - 1, 7)) + Math.abs(at(k, 8) - at(k - 1, 8))) / 2;
      const m = d >= T.rest_px * 4;
      if (m && !moving) onsets.push({ k, e });
      moving = m;
    }
    summary.push({ id: e.id, discrete: !!e.discrete, moves, max_step_px: +maxStep.toFixed(2), max_widths_per_frame: +maxWidths.toFixed(3), jumps, jumps_on_hits: jumpsOnHits, fast_frames_unblurred: fastUnblurred, fast_frames_blurred: fastBlurred, invalid: e.invalid.length });
    for (const inv of e.invalid.slice(0, 3)) warnings.push(`motion geometry: ${e.id} ${inv.what} at ${inv.t.toFixed(3)} s`);
  }
  // Competing onsets: unrelated elements (different groups and parents) starting within two frames
  // while another text is readable.
  onsets.sort((a, b) => a.k - b.k);
  const seen = new Set();
  for (let i = 0; i < onsets.length; i++) for (let j = i + 1; j < onsets.length && onsets[j].k - onsets[i].k <= T.onset_frames; j++) {
    const A = onsets[i].e, B = onsets[j].e;
    const under = (x, y) => { for (let q = x.node; q; q = q.parent) if (q === y.node) return true; return false; };
    if (A.group === B.group || A.parent === B.parent || A.family === B.family || under(A, B) || under(B, A)) continue;
    const k = onsets[j].k;
    const reading = readable.filter(r => r.flags[k] && r.group !== A.group && r.group !== B.group).map(r => r.id);
    if (!reading.length) continue;
    const key = `${A.id}|${B.id}|${Math.round(k / 6)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    warnings.push(`motion onsets: ${A.id} and ${B.id} start moving within ${onsets[j].k - onsets[i].k} frame(s) at ${(k / fps).toFixed(3)} s while ${reading.slice(0, 2).join(', ')} is being read`);
  }
  return { thresholds: T, warnings, elements: summary };
}

// A pattern sample per frame: { pairs, dark_cdm2, diff_cdm2, area, motion: 'still' | 'flow' | 'changing' }.
export function patternRisk(p) {
  const P = PATTERN_THRESHOLDS;
  if (p.pairs <= P.min_pairs || p.dark_cdm2 >= P.dark_max_cdm2 || p.diff_cdm2 < P.min_diff_cdm2) return false;
  if (p.motion === 'flow') return false;
  return p.area > (p.motion === 'still' ? P.area_still : P.area_changing);
}
