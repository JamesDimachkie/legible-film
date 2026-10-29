// Preview UI (never loaded with ?render). Playback here follows the wall clock, which is fine for a
// preview and never reaches a render: renders seek every frame through window.__lf.
//   space play/pause · , . one frame · arrows one beat · 0-9 jump to tenths
//   S safe area · R reading states · L ground-luminance strip

import { evaluate, draw } from './engine.js';
import { analyse } from './analyse.js';
import { mul, apply } from './node.js';

export function previewUI(film, { start = 0 } = {}) {
  const stage = film.stage;
  const ui = document.createElement('div');
  ui.id = 'lf-ui';
  ui.innerHTML = `
  <style>
    #lf-ui { position: fixed; left: 0; right: 0; bottom: 0; height: 92px; background: #111318; color: #c9ccd3;
      font: 12px/1.3 ui-monospace, Menlo, Consolas, monospace; border-top: 1px solid #262a33; user-select: none; }
    #lf-ui .row { display: flex; gap: 10px; align-items: center; padding: 6px 12px; }
    #lf-ui button { background: #1d2028; color: #dfe2ea; border: 1px solid #343946; border-radius: 4px; padding: 3px 9px; font: inherit; cursor: pointer; }
    #lf-ui button.on { background: #2d4da8; border-color: #4a6fd6; }
    #lf-ui canvas { display: block; width: 100%; height: 44px; cursor: pointer; }
    #lf-ui .readout { min-width: 260px; }
    #lf-ui .warn { color: #e8b75a; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; flex: 1; }
  </style>
  <div class="row"><button data-k="play">▶ play</button><span class="readout"></span>
    <button data-k="safe">S safe</button><button data-k="read">R reading</button><button data-k="lum">L luminance</button>
    <span class="warn"></span></div>
  <div class="row" style="padding-top:0"><canvas></canvas></div>`;
  document.body.appendChild(ui);
  const bar = ui.querySelector('canvas');
  const readout = ui.querySelector('.readout');
  const warn = ui.querySelector('.warn');
  const btn = k => ui.querySelector(`[data-k="${k}"]`);
  const layer = document.createElement('canvas');
  layer.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;z-index:50;';
  layer.width = film.W; layer.height = film.H;
  stage.appendChild(layer);
  const w = film.reg.warnings.length + film.reg.errors.length;
  warn.textContent = w ? `${w} build warning(s): ${[...film.reg.errors, ...film.reg.warnings].join(' · ')}` : '';
  warn.title = [...film.reg.errors, ...film.reg.warnings].join('\n');

  let t = Math.min(start, film.duration), playing = false, last = 0;
  const opts = { safe: false, read: false, lum: false };
  let report = null;
  const spf = 1 / film.fps;

  function fit() {
    const sw = window.innerWidth, sh = window.innerHeight - 92;
    const k = Math.min(sw / film.W, sh / film.H);
    stage.style.transform = `translate(${(sw - film.W * k) / 2}px, ${(sh - film.H * k) / 2}px) scale(${k})`;
    bar.width = bar.clientWidth * devicePixelRatio; bar.height = 44 * devicePixelRatio;
    drawBar();
  }
  function drawBar() {
    const c = bar.getContext('2d'), Wb = bar.width, Hb = bar.height, dp = devicePixelRatio;
    c.clearRect(0, 0, Wb, Hb);
    c.fillStyle = '#191c23'; c.fillRect(0, 0, Wb, Hb);
    const x = s => (s / film.duration) * Wb;
    if (film.beat) {
      c.fillStyle = '#262a34';
      for (let b = 0; ; b++) { const s = film.atBeat(b); if (s > film.duration) break; c.fillRect(x(s), 0, b % 4 ? 1 : 2, Hb * (b % 4 ? 0.25 : 0.4)); }
    }
    c.fillStyle = 'rgba(80,200,140,0.18)';
    for (const r of film.reg.rests) c.fillRect(x(r[0]), 0, x(r[1]) - x(r[0]), Hb);
    c.fillStyle = '#5c6270';
    for (const cut of film.reg.cuts) c.fillRect(x(cut), Hb * 0.45, dp, Hb * 0.55);
    for (const e of film.reg.cues) {
      c.fillStyle = e.sound === 'silent' ? '#6c7280' : e.sync === 'apex' ? '#5aa9e8' : e.sync === 'end' ? '#c78bf0' : '#e8b75a';
      c.fillRect(x(e.t) - dp, Hb * 0.62, 2 * dp, Hb * 0.38);
    }
    if (opts.lum && report) {
      const L = report.grounds.luminance;
      c.strokeStyle = '#e6e6e6'; c.lineWidth = dp; c.beginPath();
      L.forEach((v, i) => { const xx = (i / L.length) * Wb, yy = Hb * 0.6 * (1 - v); i ? c.lineTo(xx, yy) : c.moveTo(xx, yy); });
      c.stroke();
    }
    c.fillStyle = '#ff5a4f'; c.fillRect(x(t) - dp, 0, 2 * dp, Hb);
  }
  function overlays() {
    const c = layer.getContext('2d');
    c.clearRect(0, 0, layer.width, layer.height);
    if (opts.safe) {
      const s = film.safe;
      c.strokeStyle = 'rgba(255,90,79,0.8)'; c.setLineDash([12, 8]); c.lineWidth = 2;
      c.strokeRect(s[0], s[1], s[2] - s[0], s[3] - s[1]); c.setLineDash([]);
    }
    if (opts.read && report) {
      const cam = film._camNow;
      for (const r of report.texts) {
        const tx = film.reg.texts.find(x => x.id === r.id);
        if (!tx || r.in == null || t < r.in || t >= r.out) continue;
        const state = r.readStart == null || t < r.readStart ? 'pending' : t < r.readEnd ? 'readable' : 'leaving';
        c.strokeStyle = state === 'readable' ? '#3ddc84' : state === 'pending' ? '#f2b33d' : '#ff5a4f';
        c.lineWidth = 3;
        for (const n of tx.nodes) {
          const M = mul(cam.M, n.matrix()), ink = n.ink || [0, 0, n.w, n.h];
          const p = [[ink[0], ink[1]], [ink[2], ink[1]], [ink[2], ink[3]], [ink[0], ink[3]]].map(q => apply(M, q[0], q[1]));
          c.beginPath(); p.forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.closePath(); c.stroke();
        }
        c.fillStyle = c.strokeStyle; c.font = '600 22px ui-monospace, monospace';
        c.fillText(`${r.role} · ${state} · ${r.need_s}s`, film.safe[0], film.safe[1] - 8);
      }
    }
  }
  function show() {
    evaluate(film, t); draw(film); overlays(); drawBar();
    const beat = film.beat ? ((t - film.beat.offset) * film.beat.bpm) / 60 : null;
    readout.textContent = `${t.toFixed(3)} s · frame ${Math.round(t * film.fps)}` + (beat != null ? ` · beat ${beat.toFixed(2)}` : '') + ` / ${film.duration.toFixed(2)} s`;
  }
  const ensureReport = () => { if (!report) { report = analyse(film); } };
  function tick(now) {
    if (!playing) return;
    t += (now - last) / 1000; last = now;
    if (t >= film.duration) { t = 0; }
    show();
    requestAnimationFrame(tick); // lf-lint-ok: preview playback only, never loaded with ?render
  }
  function toggle(k) {
    if (k === 'play') {
      playing = !playing; btn('play').textContent = playing ? '❚❚ pause' : '▶ play';
      if (playing) { last = performance.now(); requestAnimationFrame(tick); } // lf-lint-ok: preview only
      return;
    }
    opts[k] = !opts[k];
    btn(k).classList.toggle('on', opts[k]);
    if ((k === 'read' || k === 'lum') && opts[k]) ensureReport();
    show();
  }
  ui.addEventListener('click', e => { const k = e.target?.dataset?.k; if (k) toggle(k); });
  const seekBar = e => { const r = bar.getBoundingClientRect(); t = Math.max(0, Math.min(film.duration, ((e.clientX - r.left) / r.width) * film.duration)); show(); };
  let dragging = false;
  bar.addEventListener('pointerdown', e => { dragging = true; seekBar(e); });
  window.addEventListener('pointermove', e => { if (dragging) seekBar(e); });
  window.addEventListener('pointerup', () => { dragging = false; });
  window.addEventListener('keydown', e => {
    const spb = film.beat ? 60 / film.beat.bpm : 0.5;
    if (e.key === ' ') { toggle('play'); e.preventDefault(); return; }
    if (e.key === ',') t = Math.max(0, Math.round(t * film.fps - 1) * spf);
    else if (e.key === '.') t = Math.min(film.duration, Math.round(t * film.fps + 1) * spf);
    else if (e.key === 'ArrowLeft') t = Math.max(0, t - spb);
    else if (e.key === 'ArrowRight') t = Math.min(film.duration, t + spb);
    else if (/^[0-9]$/.test(e.key)) t = (+e.key / 10) * film.duration;
    else if (e.key === 's' || e.key === 'S') return toggle('safe');
    else if (e.key === 'r' || e.key === 'R') return toggle('read');
    else if (e.key === 'l' || e.key === 'L') return toggle('lum');
    else return;
    e.preventDefault();
    show();
  });
  window.addEventListener('resize', fit);
  fit(); show();
}
