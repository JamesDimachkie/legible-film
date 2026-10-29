// Terminal: a terminal window; a command typed character by character on whole frames with a caret,
// output lines arriving quickly, the camera following the caret and pushing in.
//
// Terminal({ command, prompt?, output?: [string | {text, tone: 'mute'|'ok'|'accent'|'text'}], title?,
//            typeAt?, cps?, lineGap?, hold?, push?: 'content' | 'window' | false, ground?, role?, len?,
//            fullFrame? })
// Interface text has role `ui`. Durations and curves come from the motion-token scale. With fullFrame: true
// the window is the whole frame, as a terminal is on a phone (useful in a tall frame, where a short window
// is a band across a tall empty field).

import { block } from './common.js';

export const Terminal = block('terminal', (ctx, o) => {
  const u = ctx.u, pal = ctx.pal;
  const ground = ctx.colour(o.ground || 'deep');
  ctx.ground(ctx.t0, ground);
  const sw = ctx.safe[2] - ctx.safe[0];
  const fs = o.size ?? u * (ctx.portrait ? 4 : 3.8);
  const lh = fs * 1.55;
  const pad = fs * 1.4;
  const outputs = (o.output || []).map(x => (typeof x === 'string' ? { text: x } : x));
  const prompt = o.prompt ?? '$';
  const command = String(o.command || '');
  const nLines = 1 + outputs.length;
  const full = !!o.fullFrame;
  const barH = fs * 1.9;
  // A full-frame window overhangs the frame (shakes and the arrival never show its edge). Its colour is the
  // ground: once the window is the frame a lighter panel is invisible, and it would only add a light-dark swing.
  const panel = full ? ground : pal.panel;
  const winW = full ? ctx.W * 1.08 : Math.min(sw * (ctx.portrait ? 1 : 0.74), Math.max(sw * (ctx.portrait ? 0.9 : 0.62), fs * 0.62 * (Math.max(prompt.length + 1 + command.length, ...outputs.map(x => x.text.length)) + 6)));
  const winH = full ? ctx.H * 1.08 : barH + pad * 2 + lh * (nLines - 1) + fs;
  // Where the frame's safe area starts inside the window (zero for a window inside the frame).
  const inset = full ? [(winW - ctx.W) / 2 + ctx.safe[0], (winH - ctx.H) / 2 + ctx.safe[1]] : [0, 0];

  // Window: a panel with a title bar.
  const win = ctx.group.add({ name: 'terminal', w: winW, h: winH });
  win.el.style.cssText += full ? `;background:${panel};` : `;width:${winW}px;height:${winH}px;border-radius:${fs * 0.55}px;background:${pal.panel};` +
    `box-shadow:0 ${u * 1.2}px ${u * 5}px rgba(0,0,0,0.35), inset 0 0 0 1px ${ctx.mix(pal.panel, pal.paper, 0.1)};`;
  // A full-frame window has no title bar (a phone terminal has none, and a pushed-in camera would cut it).
  const bar = win.add({ name: 'bar', w: winW, h: barH, ax: 0, ay: 0 });
  bar.el.style.cssText += `;width:${winW}px;height:${barH}px;border-bottom:1px solid ${ctx.mix(pal.panel, pal.paper, 0.08)};`;
  if (full) bar.el.style.display = 'none';
  ['#ff5f57', '#febc2e', '#28c840'].forEach((c, i) => {
    const d = bar.add({ w: fs * 0.62, h: fs * 0.62 });
    d.el.style.cssText += `;width:${fs * 0.62}px;height:${fs * 0.62}px;border-radius:50%;background:${ctx.mix(c, pal.panel, 0.25)};`;
    d.rest({ x: pad * 0.75 + i * fs * 1.05, y: barH / 2 });
  });
  if (o.title) {
    const tt = ctx.textNode(bar, { string: o.title, font: 'mono', size: fs * 0.72, weight: 500, color: pal.mute, anchor: [0.5, 0.5] });
    tt.rest({ x: winW / 2, y: barH / 2 });
  }
  const mono = { font: 'mono', size: fs, weight: 500, tracking: 0, lineHeight: 1.2, anchor: [0, 0.5] };
  // Lines start at the safe edge in a full-frame window, their block centred on the frame's height.
  const x0 = full ? inset[0] + fs * 0.31 : pad;
  const y0 = full ? winH / 2 - (lh * outputs.length) / 2 : barH + pad + fs * 0.5;
  const pNode = ctx.textNode(win, { ...mono, string: prompt, color: pal.accent === pal.panel ? pal.paper : ctx.mix(pal.accent, pal.paper, 0.35), weight: 600 });
  pNode.rest({ x: x0, y: y0 });
  const cmdX = x0 + pNode.w + fs * 0.62;
  const cNode = ctx.textNode(win, { ...mono, string: command, color: pal.paper, weight: 560 });
  cNode.rest({ x: cmdX, y: y0 });
  const tones = { mute: ctx.mix(pal.mute, pal.paper, 0.25), ok: pal.success, accent: ctx.mix(pal.accent, pal.paper, 0.35), text: pal.paper };
  const oNodes = outputs.map((x, i) => {
    const n = ctx.textNode(win, { ...mono, string: x.text, color: tones[x.tone || 'mute'] || tones.mute });
    n.rest({ x: x0, y: y0 + lh * (i + 1) });
    return n;
  });
  // Caret: a block the width of one character.
  const cw = ctx.measure('M', { ...mono }).w;
  const caret = win.add({ name: 'caret', w: cw, h: fs * 1.15, ax: 0, ay: 0.5 });
  caret.el.style.cssText += `;width:${cw}px;height:${fs * 1.15}px;background:${pal.paper};border-radius:${fs * 0.08}px;`;
  caret.rest({ y: y0 });
  ctx.plate(win, panel);
  ctx.track(win, o.id ? `${o.id}-window` : 'terminal-window');
  ctx.track(caret, 'terminal-caret', { discrete: true });

  // Timing on whole frames.
  const tok = ctx.token('arrive', 'large', 0.1);
  const typeAt = ctx.t0 + ctx.time(o.typeAt ?? 0.06);   // typing starts as the window arrives: no empty beat
  const cps = o.cps ?? 24;
  const typeEnd = typeAt + command.length / cps;
  const lineGap = ctx.time(o.lineGap ?? 0.22);
  const outAt = outputs.map((x, i) => typeEnd + ctx.time(o.firstLine ?? 0.28) + i * lineGap);
  const lastAt = outAt.length ? outAt[outAt.length - 1] : typeEnd;
  const lineTok = ctx.token('arrive', 'small', 0.02);
  const hold = ctx.time(o.hold ?? 1.4);
  const len = o.len != null ? ctx.time(o.len) : lastAt + lineTok.d + hold - ctx.t0;

  const bg = () => panel;
  const role = o.role || 'ui';
  ctx.text({ id: o.id || 'ui-command', role, string: `${prompt} ${command}`.trim(), fact: o.fact, nodes: [pNode, cNode], bg, readFrom: typeEnd });
  outputs.forEach((x, i) => ctx.text({ id: x.id || `ui-output-${i + 1}`, role: x.role || role, string: x.text, fact: x.fact, nodes: [oNodes[i]], bg, readFrom: outAt[i] + lineTok.d }));

  // Cues: a key accent on each word of the command (not one per key), a tick on enter, a pop per line.
  const words = [];
  command.replace(/\S+/g, (m, idx) => { words.push(idx); return m; });
  // Typing is one gesture: one key accent where it starts (the rest is texture).
  ctx.cue({ t: typeAt, role: 'key', sync: 'attack', gain_db: -6, picture: 'the command starts typing' });
  ctx.cue({ t: typeEnd + 0.12, role: 'tick', sync: 'attack', gain_db: -4, picture: 'the command is entered' });
  outAt.forEach((t, i) => ctx.cue({ t: t + lineTok.d * 0.35, role: outputs[i].cue || 'pop', sync: 'attack', gain_db: outputs[i].tone === 'ok' ? -2 : -7, picture: `output line ${i + 1} arrives` }));

  // Camera: frames the window, follows the caret while typing, then pushes in on the content.
  const lw = Math.max(pNode.w + fs * 0.62 + cNode.w, ...oNodes.map(n => n.w));
  const contentC = [x0 + lw / 2, (y0 - fs * 0.6 + y0 + lh * outputs.length + fs * 0.6) / 2];
  const zFit = full ? 1 : Math.min(1, (sw * 0.96) / winW, ((ctx.safe[3] - ctx.safe[1]) * 0.96) / winH);
  const zContent = Math.min((sw * 0.94) / lw, ((ctx.safe[3] - ctx.safe[1]) * 0.9) / (lh * outputs.length + fs * 1.4));
  const zEnd = o.push === false ? zFit : o.push === 'window' ? Math.max(zFit, (ctx.W * 1.02) / winW) : Math.max(zFit * 1.05, zContent);

  function update(t) {
    const lt = ctx.locked(t);
    const p = ctx.progress(t, ctx.t0, ctx.t0 + tok.d);
    win.opacity = o.fadeIn ? ctx.ease.fade(Math.min(1, p * 1.6)) : 1;
    // A window inside the frame rises into place; a full-frame window is already the frame.
    win.y = full ? 0 : (1 - tok.curve(p)) * u * 6;
    win.s = full ? 1 : ctx.lerp(0.965, 1, tok.curve(p));
    const ty = ctx.typed(cNode, Math.max(0, (lt - typeAt) * cps + 1e-6));
    cNode.reveal = ty.reveal;
    const caretX = cmdX + ty.caretX;
    const lineIdx = outAt.filter(x => lt >= x).length;
    // The caret sits after the typed text, then on the next empty line once output starts.
    if (lineIdx === 0) { caret.x = caretX + fs * 0.06; caret.y = y0; }
    else { caret.x = x0 + (lineIdx < outputs.length ? 0 : oNodes[lineIdx - 1].w + fs * 0.6); caret.y = y0 + lh * Math.min(lineIdx, outputs.length); }
    const typing = lt >= typeAt && lt < typeEnd + 0.1;
    const blink = Math.floor((lt - ctx.t0) / 0.5) % 2 === 0;
    caret.opacity = typing || blink ? 1 : 0;
    oNodes.forEach((n, i) => {
      const q = ctx.progress(t, outAt[i], outAt[i] + lineTok.d);
      n.opacity = t < outAt[i] ? 0 : ctx.ease.fade(Math.min(1, q * 1.8));
      n.y += (1 - lineTok.curve(q)) * fs * 0.6;
    });
  }

  function camera(t) {
    const m = win.matrix();
    const toWorld = (x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
    // Continuous typed progress (not the whole-frame caret) so the camera glides.
    const prog = ctx.clamp((t - typeAt) / Math.max(0.01, typeEnd - typeAt));
    const cmdW = cNode.w * prog;
    const follow = toWorld(cmdX + cmdW, y0);
    const winC = toWorld(winW / 2, winH / 2);
    const endC = toWorld(contentC[0], contentC[1]);
    const a = ctx.curves.camera(ctx.progress(t, ctx.t0, typeAt + 0.2));
    const b = ctx.curves.camera(ctx.progress(t, typeEnd - 0.1, lastAt + 0.4));
    const startP = winC;
    // While the command types, the camera follows the caret (a steady pan, never a parked frame).
    const typeP = [ctx.lerp(winC[0], ctx.lerp(winC[0], follow[0], 0.9), a), ctx.lerp(winC[1], follow[1], a * 0.3)];
    // A full-frame window keeps the content block centred (the push never crops a line's start).
    let P = full ? endC : [ctx.lerp(typeP[0], endC[0], b), ctx.lerp(typeP[1], endC[1], b)];
    // The window arrives already close (about the content framing), so its first frames are never a small
    // window in an empty field.
    const z0 = o.pushFrom != null ? zFit * o.pushFrom : ctx.loglerp(zFit, zEnd, 0.55);
    const z = ctx.loglerp(z0, ctx.loglerp(zFit, zEnd, 0.7), a);
    // After the push lands on the content, keep approaching the fit (never past it) so the hold moves.
    const tail = ctx.progress(t, lastAt + 0.4, ctx.t0 + len);
    const z2 = ctx.loglerp(z, zEnd * 0.78, b) * ctx.loglerp(1, 1 / 0.78, ctx.curves.drift(tail));
    // In a tall frame the content is short against the safe height: the camera also travels down
    // across it (inside the safe area), so the hold keeps moving.
    let S = [ctx.W / 2, ctx.H / 2];
    if (full) {
      // The view never leaves the window: the camera centre stays where the window still covers the frame.
      const lo = toWorld(0, 0), hi = toWorld(winW, winH);
      const half = [ctx.W / 2 / z2, ctx.H / 2 / z2];
      P = P.map((v, k) => {
        const a0 = Math.min(lo[k], hi[k]) + half[k], a1 = Math.max(lo[k], hi[k]) - half[k];
        return a0 > a1 ? (a0 + a1) / 2 : ctx.clamp(v, a0, a1);
      });
    } else if (ctx.portrait) {
      const contentH = (lh * outputs.length + fs * 1.4) * z2;
      const roomY = Math.max(0, ((ctx.safe[3] - ctx.safe[1]) * 0.96 - contentH) / 2);
      S = [S[0], S[1] + roomY * 0.4 * (1 - 2 * ctx.curves.drift(ctx.progress(t, ctx.t0, ctx.t0 + len)))];
    }
    return ctx.frameAt(P, S, z2, 0.25 - 0.5 * ctx.progress(t, ctx.t0, ctx.t0 + len));
  }

  return { len, update, camera: t => ({ ...camera(t), drift: false }), ground0: ground };
});
