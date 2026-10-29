// Safe logos. An SVG is inlined only after removing scripts, foreignObject, embedded documents,
// event-handler attributes and script or external links. Prefer drawing it as an <img>, which runs
// no script at all; inline it only when its parts must be animated.

const DROP = new Set(['script', 'foreignobject', 'iframe', 'embed', 'object', 'audio', 'video', 'handler', 'listener']);

export function sanitizeSvg(text) {
  const doc = new DOMParser().parseFromString(text, 'image/svg+xml');
  const root = doc.documentElement;
  if (!root || root.nodeName.toLowerCase() !== 'svg' || doc.querySelector('parsererror')) throw new Error('logo is not a well-formed SVG');
  const removed = [];
  const walk = el => {
    for (const child of Array.from(el.children)) {
      if (DROP.has(child.localName.toLowerCase())) { removed.push(child.localName); child.remove(); continue; }
      walk(child);
    }
    for (const a of Array.from(el.attributes || [])) {
      const name = a.name.toLowerCase(), v = a.value.trim().toLowerCase().replace(/\s+/g, '');
      if (name.startsWith('on')) { removed.push(`@${a.name}`); el.removeAttribute(a.name); continue; }
      if ((name === 'href' || name.endsWith(':href')) && !(v.startsWith('#') || v.startsWith('data:image/png') || v.startsWith('data:image/jpeg') || v.startsWith('data:image/webp'))) {
        removed.push(`@${a.name}=${a.value.slice(0, 40)}`); el.removeAttribute(a.name); continue;
      }
      if ((name === 'style' || name === 'fill' || name === 'stroke' || name === 'filter' || name === 'mask' || name === 'clip-path') && /javascript:|url\((?!#)/.test(v)) {
        removed.push(`@${a.name}`); el.removeAttribute(a.name);
      }
    }
  };
  walk(root);
  for (const s of Array.from(root.querySelectorAll('style'))) {
    if (/@import|url\((?!\s*['"]?#)|javascript:|expression\(/i.test(s.textContent)) { removed.push('style'); s.remove(); }
  }
  const svg = document.importNode(root, true);
  return { svg, removed };
}
