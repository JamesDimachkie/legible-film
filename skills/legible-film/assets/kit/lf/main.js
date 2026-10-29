// Bootstrap: loads fonts and assets, imports the film spec, builds the film and implements
// window.__lf (DESIGN §5). URL: ?film=path/to/film.js (default film.js beside index.html),
// ?w=&h= override the size (one timeline, every aspect ratio), ?render hides the preview UI,
// ?t= opens the preview at a time.

import { buildFilm, evaluate, draw, findFact } from './engine.js';
import { analyse } from './analyse.js';
import { loadFonts } from './text.js';
import { kit } from '../blocks/index.js';
import { legacyPace } from './legacy.js';

const q = new URLSearchParams(location.search);
const renderMode = q.has('render');
let resolveReady, rejectReady;
const ready = new Promise((res, rej) => { resolveReady = res; rejectReady = rej; });
ready.catch(() => {});
let film = null;
const need = () => { if (!film) throw new Error('the film is not built yet: await window.__lf.ready'); return film; };

window.__lf = {
  ready,
  info() { return info(need()); },
  seek(t) { const f = need(); evaluate(f, +t); draw(f); },
  frame(t) { need().frameT = t == null ? null : +t; },
  get _film() { return film; },   // for debugging tools; not part of the contract
  analyse(opts) { const f = need(); const r = analyse(f, opts); evaluate(f, f._t ?? 0); draw(f); return r; },
};

// Reading holds: the kit declares each essential text's designed reading hold, [readStart,
// readStart + need_s], as a rest for claims, qualifiers, identities and interface text (spec option
// `readingRests`, default true). Headlines and texture never get one, so they must keep moving.
const READ_ROLES = new Set(['claim', 'qualifier', 'identity', 'ui', 'headline']);
function readingRests(f) {
  if (f.readRests) return f.readRests;   // declared from the timeline: identical at every size
  if (f._readingRests) return f._readingRests;
  const out = [];
  if (f.spec.readingRests !== false) {
    const saved = f._t ?? 0;
    const a = analyse(f);
    evaluate(f, saved); draw(f);
    for (const x of a.texts) {
      if (!READ_ROLES.has(x.role) || x.readStart == null) continue;
      const t1 = Math.min(x.readEnd, x.readStart + x.need_s);
      out.push([+x.readStart.toFixed(6), +t1.toFixed(6), `read: ${x.id}`]);
    }
  }
  return (f._readingRests = out);
}

// music: where it stops dead (an end card that asks for it) and the planned drop (a Type shot with
// `drop: true`, or spec.music.drop), both film times; null when the film names neither.
function musicInfo(f) {
  const stop = f.music?.stop ?? (f.spec.music?.stop != null ? f.time(f.spec.music.stop) : null);
  const drop = f.music?.drop ?? (f.spec.music?.drop != null ? f.time(f.spec.music.drop) : null);
  return stop == null && drop == null ? null : { stop: stop == null ? null : +stop.toFixed(6), drop: drop == null ? null : +drop.toFixed(6) };
}

function info(f) {
  const cues = f.reg.cues.map(c => ({ ...c }));
  const rests = [...f.reg.rests, ...readingRests(f)].sort((a, b) => a[0] - b[0]);
  return {
    title: f.spec.title || 'untitled', width: f.W, height: f.H, fps: f.fps,
    duration: +f.duration.toFixed(6), frames: f.frames, beat: f.beat,
    cuts: f.reg.cuts, seams: f.reg.seams, blanks: f.reg.blanks, changes: f.reg.changes.map(c => c[0]), change_windows: f.reg.changes, smears: f.reg.smears.slice().sort((a, b) => a[0] - b[0]),
    fast: f.reg.fast.slice().sort((a, b) => a[0] - b[0]), rests, flashes: f.reg.flashes,
    music: musicInfo(f), pace: legacyPace(f.spec.pace) || null, loop: f.loop, cues, captions: f.reg.captions,
    texts: f.reg.texts.map(x => ({ id: x.id, role: x.role, string: x.string, fact: x.fact, scene: x.scene + 1 })),
    grounds: f.reg.grounds.map(g => [+g.t.toFixed(6), g.colour, g.fade]),
    warnings: f.reg.warnings.slice(),
  };
}

async function boot() {
  const filmUrl = new URL(q.get('film') || 'film.js', location.href);
  const kitBase = new URL('../', import.meta.url);
  const mod = await import(filmUrl.href);
  const spec = typeof mod.default === 'function' ? mod.default(kit) : mod.default;
  if (!spec || !Array.isArray(spec.scenes)) throw new Error('film.js must export default a spec (or a function of the kit returning one) with scenes');
  const size = spec.size || [1920, 1080];
  const W = +(q.get('w') || size[0]), H = +(q.get('h') || size[1]);
  // Fonts: the kit's open-licence faces unless the spec supplies brand fonts (paths relative to film.js).
  const fonts = {};
  for (const [role, f] of Object.entries(spec.fonts || {})) fonts[role] = { ...f, url: new URL(f.url, filmUrl).href };
  await loadFonts(kitBase, fonts);
  let facts = null;
  if (spec.facts) {
    const r = await fetch(new URL(spec.facts, filmUrl)); // lf-lint-ok: build time, before __lf.ready
    if (!r.ok) throw new Error(`facts file ${spec.facts} could not be read (${r.status})`);
    facts = await r.json();
  }
  // Every image a block names is loaded and decoded before the film is built.
  const images = new Map();
  for (const sc of spec.scenes) for (const src of (sc.assets ? sc.assets() : [])) {
    if (images.has(src)) continue;
    const url = new URL(src, filmUrl).href;
    if (/\.svg(\?|$)/i.test(src) && sc.inlineSvg) {
      const r = await fetch(url); // lf-lint-ok: build time, before __lf.ready
      images.set(src, { svgText: await r.text(), url });
    } else {
      const img = new Image();
      img.decoding = 'sync';
      img.src = url;
      await img.decode();
      images.set(src, { img, url, width: img.naturalWidth, height: img.naturalHeight });
    }
  }
  document.documentElement.style.setProperty('--lf-w', `${W}px`);
  document.documentElement.style.setProperty('--lf-h', `${H}px`);
  const stage = document.getElementById('lf-stage');
  film = await buildFilm(spec, { W, H, stage, facts, images, filmUrl, dpr: window.devicePixelRatio || 1, render: renderMode, animatic: q.has('animatic'), findFact });
  evaluate(film, 0); draw(film);
  if (!renderMode) {
    const { previewUI } = await import('./ui.js');
    previewUI(film, { start: +(q.get('t') || 0) });
  } else {
    document.body.classList.add('lf-render');
  }
  await document.fonts.ready;
}

boot().then(() => resolveReady(), e => {
  console.error(e);
  const box = document.createElement('pre');
  box.className = 'lf-error';
  box.textContent = `Film failed to build:\n${e && e.stack || e}`;
  document.body.appendChild(box);
  rejectReady(new Error(String(e && e.message || e)));
});
