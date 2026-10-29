// Atlasfold 1.0: a 24.8 s teaser for a fictional open-source command-line tool (DESIGN.md §12).
//
// Concept. A folder of photos is a pile; Atlasfold folds it into a map. The film's operation is the
// fold: scattered photo cards turn over into the tiles of one map. "A MAP." first appears as an
// outline (not yet true); it comes back filled on the beat the map exists. Then the facts land one
// idea per beat, the name arrives out of depth, and the camera flies through its O to the end card.
//
// Clock: 150 BPM, 60 fps, 24 frames per beat; every landing sits on the beat grid.
// Truth: every claim is in facts.json; the map, the photos and the search are labelled ILLUSTRATION.

export default function film(kit) {
  const { Type, Terminal, Name, EndCard, block, clock } = kit;
  const T = clock({ bpm: 150, offset: 0 });

  // ---- A device of this film's own: scattered photo cards fold into the tiles of one map. ----
  const Fold = block('fold', (ctx, o) => {
    const { u, pal } = ctx;
    const R = ctx.rng(42);
    const ground = ctx.colour('deep');
    ctx.ground(ctx.t0, ground);
    const cols = ctx.portrait ? 3 : 5, rows = ctx.portrait ? 5 : 3;
    const sw = ctx.safe[2] - ctx.safe[0], sh = ctx.safe[3] - ctx.safe[1];
    const mapW = Math.min(sw * (ctx.portrait ? 0.96 : 0.84), (sh * 0.78) * cols / (rows * 0.75));
    const tw = mapW / cols, th = tw * 0.75, mapH = th * rows;
    const at = n => ctx.t0 + T.b(n);

    // The map: land from seeded value noise, a coastline in the accent, faint contours and a graticule.
    const vnoise = (x, y, s) => {
      const i = Math.floor(x), j = Math.floor(y), fx = x - i, fy = y - j;
      const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
      const h = (a, b) => ctx.hash(a, b, s);
      const a = h(i, j) + (h(i + 1, j) - h(i, j)) * sx, b = h(i, j + 1) + (h(i + 1, j + 1) - h(i, j + 1)) * sx;
      return a + (b - a) * sy;
    };
    const fbm = (x, y) => {
      let v = 0, amp = 0.5, f = 1;
      for (let k = 0; k < 5; k++) { v += amp * vnoise(x * f, y * f, 11 + k); f *= 2.03; amp *= 0.5; }
      return v;
    };
    const field = (x, y) => fbm(x * 3.1 / mapW * (cols / 5) * 1.6 + 2.3, y * 3.1 / mapW * (cols / 5) * 1.6 + 7.1) + 0.18 * (0.5 - Math.hypot(x / mapW - 0.5, y / mapH - 0.5));
    const S = 0.5;                                  // the map is computed at half resolution
    const mw = Math.ceil(mapW * S), mh = Math.ceil(mapH * S);
    const map = document.createElement('canvas');
    map.width = mw; map.height = mh;
    const mc = map.getContext('2d');
    const img = mc.createImageData(mw, mh);
    const rgb = c => ctx.parse(c).map(v => Math.round(v * 255));
    const sea = rgb(ctx.mix(pal.deep, pal.accent, 0.32)), land = rgb(ctx.mix(pal.panel, pal.paper, 0.3));
    const high = rgb(ctx.mix(pal.panel, pal.paper, 0.42));
    const coast = rgb(ctx.mix(pal.accent, pal.paper, 0.25));
    // Land stays close in tone to the sea: a bright map moving under a camera push saws window luminance.
    const contour = rgb(ctx.mix(pal.panel, pal.paper, 0.55));
    const LEVEL = 0.45;
    const seaLine = rgb(ctx.mix(pal.deep, pal.accent, 0.5));
    const mixc = (a, b, k) => [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k];
    for (let y = 0; y < mh; y++) for (let x = 0; x < mw; x++) {
      const f = field(x / S, y / S);
      let c;
      if (f > LEVEL) {
        // Land with hill shading (lighter with height) and contour lines every few steps of height.
        const h = Math.min(1, (f - LEVEL) / 0.2);
        c = mixc(land, high, h);
        const band = ((f - LEVEL) / 0.028) % 1;
        if (band < 0.12) c = mixc(c, contour, 0.8);
        if (Math.abs(f - LEVEL) < 0.008) c = coast;
      } else {
        // Sea with depth lines.
        c = sea;
        const band = ((LEVEL - f) / 0.04) % 1;
        if (band < 0.07 && LEVEL - f < 0.16) c = mixc(sea, seaLine, 0.7 * (1 - (LEVEL - f) / 0.16));
      }
      const i = (y * mw + x) * 4;
      img.data[i] = c[0]; img.data[i + 1] = c[1]; img.data[i + 2] = c[2]; img.data[i + 3] = 255;
    }
    mc.putImageData(img, 0, 0);
    mc.strokeStyle = 'rgba(255,255,255,0.16)'; mc.lineWidth = 1;
    for (let k = 1; k < cols * 2; k++) { mc.beginPath(); mc.moveTo((k * mw) / (cols * 2), 0); mc.lineTo((k * mw) / (cols * 2), mh); mc.stroke(); }
    for (let k = 1; k < rows * 2; k++) { mc.beginPath(); mc.moveTo(0, (k * mh) / (rows * 2)); mc.lineTo(mw, (k * mh) / (rows * 2)); mc.stroke(); }

    // Photo cards: small drawn landscapes printed with a white border (illustrations of photos).
    const skies = [['#f4a261', '#e76f51'], ['#8ecae6', '#219ebc'], ['#cdd7e1', '#8d99ae'], ['#ffb4a2', '#6d597a'], ['#a8dadc', '#457b9d']];
    const photo = k => {
      const c = document.createElement('canvas');
      const W = Math.round(tw * 1.25), H = Math.round(th * 1.25);
      c.width = W; c.height = H;
      const x = c.getContext('2d');
      const r = ctx.rng(100 + k);
      const sky = skies[Math.floor(r() * skies.length)];
      x.fillStyle = pal.paper; x.fillRect(0, 0, W, H);
      const b = W * 0.05;
      const g = x.createLinearGradient(0, b, 0, H - b);
      g.addColorStop(0, sky[0]); g.addColorStop(1, sky[1]);
      x.fillStyle = g; x.fillRect(b, b, W - 2 * b, H - 2 * b);
      x.save(); x.beginPath(); x.rect(b, b, W - 2 * b, H - 2 * b); x.clip();
      x.fillStyle = 'rgba(255,255,240,0.85)';
      x.beginPath(); x.arc(b + (0.2 + 0.6 * r()) * (W - 2 * b), b + (0.18 + 0.2 * r()) * H, H * (0.06 + 0.05 * r()), 0, 7); x.fill();
      for (let layer = 0; layer < 3; layer++) {
        const base = H * (0.5 + layer * 0.14 + r() * 0.05);
        x.fillStyle = ctx.mix(sky[1], '#10151c', 0.35 + layer * 0.22);
        x.beginPath(); x.moveTo(0, H);
        for (let px = 0; px <= W; px += W / 12) x.lineTo(px, base - H * 0.12 * Math.abs(Math.sin(px / W * (3 + layer * 2) + r() * 6)) * (1 - layer * 0.25));
        x.lineTo(W, H); x.closePath(); x.fill();
      }
      x.restore();
      return c;
    };

    const cards = [];
    const grp = ctx.group.add({ name: 'fold' });
    const centreR = Math.hypot(cols, rows) / 2;
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const k = r * cols + c;
      const card = grp.add({ name: `card-${k}`, w: tw, h: th });
      card.el.style.cssText += `;width:${tw}px;height:${th}px;`;
      const ph = photo(k);
      ph.style.cssText = `position:absolute;left:0;top:0;width:${tw}px;height:${th}px;border-radius:${u * 0.35}px;box-shadow:0 ${u * 0.6}px ${u * 2.2}px rgba(0,0,0,0.45);`;
      const tile = document.createElement('canvas');
      tile.width = Math.ceil(tw * S * 2); tile.height = Math.ceil(th * S * 2);
      const tc = tile.getContext('2d');
      tc.imageSmoothingQuality = 'high';
      tc.drawImage(map, c * tw * S, r * th * S, tw * S, th * S, 0, 0, tile.width, tile.height);
      tile.style.cssText = `position:absolute;left:0;top:0;width:${tw}px;height:${th}px;visibility:hidden;`;
      card.el.append(ph, tile);
      const grid = [-mapW / 2 + tw * (c + 0.5), -mapH / 2 + th * (r + 0.5)];
      const scatter = [(R() * 2 - 1) * ctx.W * 0.34, (R() * 2 - 1) * ctx.H * 0.3];
      const a = Math.atan2(scatter[1], scatter[0]) + (R() - 0.5) * 0.6;
      const from = [Math.cos(a) * ctx.W * 0.9, Math.sin(a) * ctx.H * 0.9];
      const d = Math.hypot(c - (cols - 1) / 2, r - (rows - 1) / 2) / centreR;
      const it = { card, ph, tile, grid, scatter, from, rot: (R() * 2 - 1) * 24, inAt: k % 4 === 0 ? ctx.t0 - 0.12 - 0.08 * R() : ctx.t0 + R() * T.b(1.1), /* every fourth card is already flying when the cut lands; the rest arrive together */ foldAt: at(2) + Math.min(1, d) * T.b(1.6) + R() * 0.06, side: null };
      let shown = null;
      card.onFlush = n => {
        const side = n.extra ? 1 : 0;
        if (side !== shown) { ph.style.visibility = side ? 'hidden' : 'visible'; tile.style.visibility = side ? 'visible' : 'hidden'; shown = side; }
      };
      ctx.track(card, `card-${k + 1}`);
      ctx.plate(card, '#7d8597');   // the cards' mean tone, for the flash prediction
      cards.push(it);
    }
    const foldDur = T.b(1.15);
    // The clock never depends on layout (5 x 3 wide, 3 x 5 tall): the lock is a fixed beat time.
    const allIn = at(2) + T.b(1.6) + 0.06 + foldDur;
    const lock = allIn + 0.06;
    // A hard cut into motion: the cards already flying carry the energy across the join.
    ctx.cue({ t: ctx.t0, role: 'whoosh', sync: 'apex', gain_db: -6, picture: 'cut into photo cards already in flight' });
    ctx.cue({ t: at(2), role: 'riser', sync: 'end', sound: 'optional', gain_db: -9, picture: 'the fold begins' });
    ctx.cue({ t: lock, role: 'impact', sync: 'attack', picture: 'the last tile locks: the photos are one map' });
    ctx.bump(lock, { amt: 0.025 });

    // The photos' white print borders become the paper frame of the finished map.
    const frameW = u * 0.9;
    const frame = grp.add({ name: 'map-frame', w: mapW + frameW * 2, h: mapH + frameW * 2 });
    frame.el.style.cssText += `;width:${mapW + frameW * 2}px;height:${mapH + frameW * 2}px;box-shadow:inset 0 0 0 ${frameW}px ${pal.paper}, 0 ${u}px ${u * 4}px rgba(0,0,0,0.5);border-radius:${u * 0.3}px;`;
    grp.el.insertBefore(frame.el, grp.el.firstChild);

    // Pins where the photos sit, chosen on land.
    const pins = [];
    const P = ctx.rng(7);
    for (let tries = 0; pins.length < 5 && tries < 4000; tries++) {
      const fx = 0.12 + 0.76 * P(), fy = 0.15 + 0.7 * P();
      const strict = tries < 3000;
      if ((strict && field(fx * mapW, fy * mapH) < 0.49) || pins.some(p => Math.hypot(p.fx - fx, (p.fy - fy) * 0.6) < (strict ? 0.16 : 0.08))) continue;
      pins.push({ fx, fy });
    }
    const pinR = u * 1.25;
    pins.forEach((p, i) => {
      const n = grp.add({ name: `pin-${i}`, w: pinR * 2, h: pinR * 2 });
      n.el.style.cssText += `;width:${pinR * 2}px;height:${pinR * 2}px;border-radius:50%;background:${pal.accent};box-shadow:0 0 0 ${u * 0.4}px ${pal.paper}, 0 ${u * 0.4}px ${u * 1.4}px rgba(0,0,0,0.5);`;
      const ring = grp.add({ name: `ring-${i}`, w: pinR * 2, h: pinR * 2 });
      ring.el.style.cssText += `;width:${pinR * 2}px;height:${pinR * 2}px;border-radius:50%;box-shadow:0 0 0 ${u * 0.3}px ${pal.accent};`;
      p.node = n; p.ring = ring;
      ctx.track(n, `pin-${i + 1}`);
      p.x = -mapW / 2 + p.fx * mapW; p.y = -mapH / 2 + p.fy * mapH;
      p.at = lock + T.b(0.5) + i * 0.07;
      // The pins drop as one run: the first one sounds; the rest are texture.
      if (i === 0) ctx.cue({ t: p.at, role: 'pop', sync: 'attack', gain_db: -7, picture: 'the pins drop (a run of five)' });
    });
    const matches = [1, 3];

    // A search field above the map, and the query typed on whole frames.
    const q = o.query;
    const barW = Math.min(mapW * 0.56, sw * 0.9), barH = u * 7.2;
    // The search field is interface over the map: screen space, so the map can push beneath it.
    const bar = ctx.screenGroup.add({ name: 'search', w: barW, h: barH });
    bar.el.style.cssText += `;width:${barW}px;height:${barH}px;border-radius:${barH / 2}px;background:${pal.paper};box-shadow:0 ${u * 0.8}px ${u * 3}px rgba(0,0,0,0.45);`;
    bar.rest({ y: ctx.safe[1] - ctx.H / 2 + barH * 0.5 + u * 1.5 });
    const glass = bar.add({ w: barH * 0.36, h: barH * 0.36 });
    glass.el.style.cssText += `;width:${barH * 0.36}px;height:${barH * 0.36}px;border-radius:50%;box-shadow:inset 0 0 0 ${u * 0.42}px ${pal.ink};`;
    glass.rest({ x: barH * 0.55, y: barH * 0.46 });
    const handle = bar.add({ w: barH * 0.17, h: u * 0.42 });
    handle.el.style.cssText += `;width:${barH * 0.17}px;height:${u * 0.42}px;background:${pal.ink};border-radius:${u}px;`;
    handle.rest({ x: barH * 0.71, y: barH * 0.63, rot: 45 });
    const qNode = ctx.textNode(bar, { string: q, font: 'mono', size: u * 3.6, weight: 560, color: pal.ink, anchor: [0, 0.5] });
    qNode.rest({ x: barH * 0.95, y: barH / 2 });
    ctx.track(bar, 'search-field');
    const caret = bar.add({ w: u * 0.35, h: u * 4 });
    caret.el.style.cssText += `;width:${u * 0.35}px;height:${u * 4}px;background:${pal.accent};`;
    const barAt = lock + T.b(1.05), typeAt = barAt + 0.14, cps = 20, typeEnd = typeAt + q.length / cps;
    const found = typeEnd + 0.2;
    ctx.text({ id: 'ui-search', role: 'ui', string: q, fact: 'map-illustration', nodes: [qNode], bg: () => pal.paper, readFrom: typeEnd });
    ctx.cue({ t: typeAt, role: 'key', sync: 'attack', gain_db: -8, picture: 'the query starts typing' });
    ctx.cue({ t: found, role: 'tick', sync: 'attack', gain_db: -2, picture: 'matching photos light up on the map' });
    const len = T.b(o.beats ?? 10);

    const label = ctx.textNode(ctx.screenGroup, { string: 'ILLUSTRATION', font: 'mono', size: u * 3.1, weight: 600, tracking: 0.14, color: ctx.mix(pal.paper, ground, 0.2), anchor: [0, 1] });
    label.rest({ x: ctx.safe[0] - ctx.W / 2, y: ctx.safe[3] - ctx.H / 2 });
    ctx.text({ id: 'qualifier-illustration', role: 'qualifier', string: 'ILLUSTRATION', fact: 'map-illustration', nodes: [label], bg: () => ground, readFrom: ctx.t0 });
    ctx.change(lock - 0.1, lock + 0.1, 'the last tile locks');
    ctx.change(ctx.t0, Math.max(...cards.map(x => x.inAt)) + 0.45, 'photo cards fly in');
    ctx.change(at(2), allIn, 'the cards turn over into map tiles');

    function update(t) {
      for (const it of cards) {
        const a = ctx.progress(t, it.inAt, it.inAt + 0.42);
        const ea = ctx.curves.arrive(a);
        const f = ctx.progress(t, it.foldAt, it.foldAt + foldDur);
        const ef = ctx.curves.camera(f);
        const gap = u * 0.9 * (1 - ctx.curves.settle(ctx.progress(t, allIn - 0.05, lock + 0.18)));
        const gx = it.grid[0] * (1 + gap / tw * 0.9), gy = it.grid[1] * (1 + gap / th * 0.9);
        const sx = ctx.lerp(it.from[0], it.scatter[0], ea), sy = ctx.lerp(it.from[1], it.scatter[1], ea);
        it.card.x = ctx.lerp(sx, gx, ef);
        it.card.y = ctx.lerp(sy, gy, ef);
        it.card.rot = ctx.lerp(it.rot * (1.6 - 0.6 * ea), 0, ef);
        it.card.opacity = t < it.inAt ? 0 : 1;
        const flip = ctx.progress(f, 0.2, 0.8);
        it.card.sx = Math.max(0.02, Math.abs(Math.cos(Math.PI * flip)));
        it.card.s = (ctx.lerp(0.92, 1.08, ea) + (1 - ea) * 0.3) * ctx.lerp(1, 1 / 1.08, ef) + 0.12 * Math.sin(Math.PI * flip);
        it.card.extra = flip >= 0.5 ? 1 : 0;
      }
      const fr = ctx.progress(t, allIn - 0.1, lock + 0.15);
      frame.opacity = ctx.ease.fade(fr);
      frame.s = ctx.lerp(1.04, 1, ctx.curves.settle(fr));
      const sel = ctx.progress(t, found, found + 0.25);
      pins.forEach((p, i) => {
        const d = ctx.progress(t, p.at - 0.12, p.at + 0.1);
        p.node.x = p.x; p.node.y = p.y - (1 - ctx.curves.arrive(d)) * u * 5;
        p.node.opacity = t < p.at - 0.12 ? 0 : ctx.ease.fade(Math.min(1, d * 2)) * (matches.includes(i) ? 1 : 1 - 0.55 * sel);
        p.node.s = matches.includes(i) ? 1 + 0.35 * ctx.curves.arrive(sel) : 1;
        p.ring.x = p.x; p.ring.y = p.y;
        const pr = (t - found) / 0.7;
        p.ring.opacity = matches.includes(i) && pr > 0 ? Math.max(0, 1 - (pr % 1)) : 0;
        p.ring.s = 1 + 2.2 * ctx.ease.out3(pr % 1);
      });
      const b = ctx.progress(t, barAt, barAt + 0.3);
      bar.opacity = t < barAt ? 0 : ctx.ease.fade(Math.min(1, b * 1.5));
      bar.y += (1 - ctx.curves.open(b)) * u * 4;
      bar.sy = ctx.lerp(0.6, 1, ctx.curves.open(b));
      const ty = ctx.typed(qNode, Math.max(0, (ctx.locked(t) - typeAt) * cps + 1e-6));
      qNode.reveal = ty.reveal;
      caret.x = qNode.x + ty.caretX + u * 0.3;
      caret.y = barH / 2;
      caret.opacity = t < typeAt ? 0 : (ctx.locked(t) < typeEnd + 0.1 || Math.floor(ctx.locked(t) / 0.5) % 2 === 0 ? 1 : 0);
    }
    function camera(t) {
      // Starts pulled back over the pile, settles onto the map as it locks, then leans toward the matches.
      const settle = ctx.curves.camera(ctx.progress(t, at(1.8), lock + 0.2));
      // After the lock the camera keeps travelling into the map and leans toward the matches.
      const after = ctx.progress(t, lock, ctx.t0 + len);
      const lean = ctx.curves.camera(ctx.progress(t, found - 0.3, ctx.t0 + len));
      const mx = (pins[matches[0]].x + pins[matches[1]].x) / 2, my = (pins[matches[0]].y + pins[matches[1]].y) / 2;
      const z0 = 0.86, z1 = Math.min(1.02, (sw * 0.98) / mapW, (sh * 0.92) / (mapH + barH * 2.4));
      return {
        x: ctx.lerp(0, mx * 0.6, lean), y: ctx.lerp(0, u * 2, settle) + my * 0.5 * lean,
        zoom: ctx.loglerp(z0, z1, settle) * ctx.loglerp(1, 1.35, ctx.curves.drift(after)),
        rot: ctx.lerp(-1.6, 0, settle) + 1.0 * lean, drift: false,
      };
    }
    return { len, update, camera, ground0: ground };
  });

  return {
    title: 'Atlasfold 1.0',
    size: [1920, 1080],
    fps: 60,
    beat: { bpm: T.bpm, offset: T.offset },
    brand: '#3D7BFF',
    facts: 'facts.json',
    reading: { cps: 15, base: 0.3 },
    readingRests: true,   // claims, qualifiers, names and interface text declare their reading holds
    pace: { max_still: 0.6, max_still_share: 0.4 },   // the film's own pace contract (before the end card)
    texture: { kind: 'dots', spacing: 4.4, dot: 0.16 },
    scenes: [
      // Hook: the problem in the viewer's terms. "A MAP." is an outline: it is not true yet.
      Type({
        exit: 'dive', dive: { letter: 'A', shot: -1 }, diveD: 0.5,
        shots: [
          { text: 'PHOTOS.', kicker: 'A FOLDER OF', style: 'kicker', open: true, openHit: '1b', dur: '3b', ground: 'ink', fact: 'what', hit: 'shake' },
          { text: 'IS NOT', tall: 'IS/NOT', style: 'snap', dur: '2b', ground: 'paper', fact: 'what', fill: 0.78, rot: -3 },
          { text: 'A MAP.', tall: 'A/MAP.', style: 'outline', dur: '4b', fact: 'what', hit: 'bump' },
        ],
      }),
      // The command, typed: the product acting. Illustrative reconstruction (facts: terminal-illustration).
      Terminal({
        enter: 'zoom', exit: 'cut',
        prompt: '~/photos $', command: 'atlasfold .', title: 'atlasfold',
        output: [
          { text: 'reading photos', tone: 'mute', fact: 'terminal-illustration' },
          { text: 'placing them on a map', tone: 'mute', fact: 'terminal-illustration' },
          { text: 'map ready', tone: 'ok', fact: 'terminal-illustration' },
        ],
        fact: 'terminal-illustration', cps: 20, len: '9b', arriveFrom: 1.2,
      }),
      // The fold: the photos turn over into one map (an illustration).
      Fold({ enter: 'cut', query: 'lisbon', beats: 9 }),
      // The turn: the outline from the hook comes back, and fills on the beat. The film's peak.
      Type({
        enter: 'zoom', exit: 'shrink',
        shots: [{ text: 'A SEARCHABLE/MAP.', tall: 'A/SEARCHABLE/MAP.', style: 'outline', fillAt: '1b', fillHit: 'burst', fillCue: 'boom', drop: true, dur: '5b', ground: 'ink', role: 'claim', fact: 'what', id: 'claim-what' }],
      }),
      // The facts, one idea per beat.
      Type({
        exit: 'whip-v',
        shots: [
          { text: 'RUNS/OFFLINE.', dur: '4b', ground: 'ink', role: 'claim', fact: 'offline', id: 'claim-offline', hit: 'shake' },
          { text: 'MACOS./WINDOWS./LINUX.', build: 'lines', step: '1b', lineHit: 'none', uniform: true, dur: '7b', ground: 'paper', role: 'claim', fact: 'platforms', id: 'claim-platforms', enter: 'whip-h', hit: 'shake' },
          { text: 'MIT.', dur: '2b', ground: 'accent', role: 'claim', fact: 'licence', id: 'claim-licence', enter: 'whip-v', hit: 'shake' },
        ],
      }),
      // The name, out of depth; the camera flies through its O to the end card.
      Name({ name: 'ATLASFOLD', color: 'accent', kickerColor: 'paper', kicker: 'INTRODUCING', sub: 'VERSION 1.0', fact: 'release', subFact: 'release', subRole: 'identity', ground: 'ink', at: '0.5b', fly: 0.36, subDelay: 0.1, cps: 30, len: '6b', exit: 'dive' }),
      EndCard({ wordmark: 'ATLASFOLD', typed: false, wordmarkFact: 'release', tagline: 'OUT TODAY', taglineFact: 'release', line: 'atlasfold.example', lineFact: 'url', ground: 'paper', len: '9b' }),
    ],
  };
}
