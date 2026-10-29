// Nodes: the kit's own small scene graph. Blocks set plain properties from t (pure); the engine
// flushes them to the DOM afterwards, and analyse() reads them without touching the DOM.
// Affine matrices are [a, b, c, d, e, f]: (x, y) -> (a x + c y + e, b x + d y + f).

export const I = [1, 0, 0, 1, 0, 0];
export function mul(m, n) {
  return [
    m[0] * n[0] + m[2] * n[1], m[1] * n[0] + m[3] * n[1],
    m[0] * n[2] + m[2] * n[3], m[1] * n[2] + m[3] * n[3],
    m[0] * n[4] + m[2] * n[5] + m[4], m[1] * n[4] + m[3] * n[5] + m[5],
  ];
}
export const translate = (x, y) => [1, 0, 0, 1, x, y];
export const scale = (sx, sy = sx) => [sx, 0, 0, sy, 0, 0];
export function rotate(deg) {
  const r = (deg * Math.PI) / 180, c = Math.cos(r), s = Math.sin(r);
  return [c, s, -s, c, 0, 0];
}
export const apply = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
export function invert(m) {
  const det = m[0] * m[3] - m[1] * m[2];
  const a = m[3] / det, b = -m[1] / det, c = -m[2] / det, d = m[0] / det;
  return [a, b, c, d, -(a * m[4] + c * m[5]), -(b * m[4] + d * m[5])];
}
export const matScale = m => Math.sqrt(Math.abs(m[0] * m[3] - m[1] * m[2]));

const f3 = v => (Math.abs(v) < 1e-6 ? 0 : +v.toFixed(3));

let NEXT_ID = 1;

export class Node {
  constructor({ el, parent = null, w = 0, h = 0, ax = 0.5, ay = 0.5, name = '' } = {}) {
    this.id = NEXT_ID++;
    this.name = name;
    this.el = el || document.createElement('div');
    this.el.className = (this.el.className ? this.el.className + ' ' : '') + 'lf-node';
    this.parent = parent;
    this.children = [];
    this.w = w; this.h = h; this.ax = ax; this.ay = ay;
    // Ink box in local layout coordinates (for safe-area and cover tests); defaults to the layout box.
    this.ink = null;
    this.base = {};
    this.reset();
    this._css = {};
    if (parent) { parent.children.push(this); parent.el.appendChild(this.el); }
  }

  // The state a node has before any block's update touches it this frame.
  reset() {
    this.x = 0; this.y = 0; this.s = 1; this.sx = 1; this.sy = 1; this.rot = 0;
    this.opacity = 1; this.blur = 0; this.color = null; this.fill = null; this.stroke = 0;
    this.strokeColor = null; this.reveal = Infinity; this.revealWords = Infinity; this.text = null;
    this.rx = 0; this.ry = 0; this.extra = null; this.flat = false;
    Object.assign(this, this.base);
  }

  // Build-time properties: the state every frame starts from before blocks animate it.
  rest(props) { Object.assign(this.base, props); Object.assign(this, props); return this; }

  add(opts = {}) { return new Node({ ...opts, parent: this }); }

  local() {
    let m = translate(this.x, this.y);
    if (this.rot) m = mul(m, rotate(this.rot));
    const sx = this.s * this.sx, sy = this.s * this.sy;
    if (sx !== 1 || sy !== 1) m = mul(m, scale(sx, sy));
    if (this.w || this.h) m = mul(m, translate(-this.ax * this.w, -this.ay * this.h));
    return m;
  }

  // Matrix from this node's layout box to the coordinates of `upTo` (exclusive), or the root.
  matrix(upTo = null) {
    let m = this.local();
    for (let p = this.parent; p && p !== upTo; p = p.parent) m = mul(p.local(), m);
    return m;
  }

  // Product of opacities from this node to the root.
  alpha() {
    let a = 1;
    for (let n = this; n; n = n.parent) a *= n.opacity;
    return a;
  }

  // Own scale relative to its rest state (camera excluded), and the largest blur up the chain.
  ownScale() {
    let s = 1;
    for (let n = this; n; n = n.parent) s *= n.s * Math.sqrt(Math.abs(n.sx * n.sy));
    return s;
  }
  blurChain() {
    let b = 0;
    for (let n = this; n; n = n.parent) b = Math.max(b, n.blur);
    return b;
  }

  css(prop, value) {
    if (this._css[prop] === value) return;
    this._css[prop] = value;
    this.el.style.setProperty(prop, value);
  }

  flush() {
    const sx = this.s * this.sx, sy = this.s * this.sy;
    let tr = `translate(${f3(this.x)}px,${f3(this.y)}px)`;
    if (this.rot) tr += ` rotate(${f3(this.rot)}deg)`;
    if (sx !== 1 || sy !== 1) tr += ` scale(${f3(Math.max(sx, 1e-4))},${f3(Math.max(sy, 1e-4))})`;
    if (this.w || this.h) tr += ` translate(${f3(-this.ax * this.w)}px,${f3(-this.ay * this.h)}px)`;
    this.css('transform', tr);
    const o = this.opacity < 0.002 ? 0 : this.opacity > 0.998 ? 1 : +this.opacity.toFixed(4);
    this.css('opacity', String(o));
    this.css('visibility', o === 0 ? 'hidden' : 'visible');
    this.css('filter', this.blur > 0.05 ? `blur(${f3(this.blur)}px)` : 'none');
    if (this.color != null && !this.textColour) this.css('color', this.color);
    if (this.fill != null) this.css('background-color', this.fill);
    if (this.onFlush) this.onFlush(this);
    for (const c of this.children) c.flush();
  }

  resetTree() {
    this.reset();
    if (this.onReset) this.onReset(this);
    for (const c of this.children) c.resetTree();
  }
}
