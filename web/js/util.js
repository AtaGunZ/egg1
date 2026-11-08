// Small DOM / formatting helpers shared by all modules.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** el('div.cls#id', {attrs, on:{click}}, ...children) */
export function el(spec, props = {}, ...kids) {
  const m = /^([a-z0-9]+)?((?:[.#][\w-]+)*)$/i.exec(spec);
  const node = document.createElement(m && m[1] ? m[1] : 'div');
  for (const part of (m && m[2] ? m[2].match(/[.#][\w-]+/g) : []) || []) {
    if (part[0] === '.') node.classList.add(part.slice(1)); else node.id = part.slice(1);
  }
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'on') for (const [ev, fn] of Object.entries(v)) node.addEventListener(ev, fn);
    else if (k === 'text') node.textContent = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k === 'style' && typeof v === 'object') Object.assign(node.style, v);
    else if (v === true) node.setAttribute(k, '');
    else node.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    node.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return node;
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

export function toast(title, body = '', kind = '', ms = 5000) {
  const t = el('div.toast' + (kind ? '.' + kind : ''), { role: 'status' }, el('b', { text: title }), body ? el('span', { text: body }) : null);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), ms);
  t.addEventListener('click', () => t.remove());
}

export function fmtNum(v, digits = 2) {
  if (v == null || Number.isNaN(v)) return '–';
  if (typeof v !== 'number') return String(v);
  const s = v.toFixed(digits);
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s;
}
export const fmtVal = (m, digits = 2) => (!m || m.value == null) ? null : `${fmtNum(m.value, digits)} ${m.unit || ''}`.trim();
export const fmtReq = (r, digits = 2) => (!r || r.value == null) ? null : `${r.op || ''} ${fmtNum(r.value, digits)} ${r.unit || ''}`.trim();
export const fmtBytes = n => n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.round(n / 1e3) + ' kB';

export const DECISIONS = {
  accepted_violation: { label: 'Accept violation', short: 'Accepted', key: 'A' },
  waived: { label: 'Waive', short: 'Waived', key: 'W' },
  compliant: { label: 'Mark compliant', short: 'Compliant', key: 'C' },
  needs_info: { label: 'Needs info', short: 'Needs info', key: 'N' },
};

export function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

/** Make a splitter draggable. dir 'v' resizes `target` width (target is right of splitter), 'h' resizes target height (above). */
export function dragSplitter(handle, { dir, target, min = 200, max = 900, store }) {
  const key = store && 'bimcheck.split.' + store;
  try { const s = key && localStorage.getItem(key); if (s) apply(+s); } catch { /* ignore */ }
  function apply(px) {
    px = Math.max(min, Math.min(max, px));
    if (dir === 'v') { target.style.width = px + 'px'; } else { target.style.flex = `0 0 ${px}px`; }
    return px;
  }
  handle.addEventListener('pointerdown', ev => {
    ev.preventDefault();
    handle.setPointerCapture(ev.pointerId);
    handle.classList.add('drag');
    const startX = ev.clientX, startY = ev.clientY;
    const startSize = dir === 'v' ? target.getBoundingClientRect().width : target.getBoundingClientRect().height;
    let last = startSize;
    const move = e => {
      last = apply(dir === 'v' ? startSize - (e.clientX - startX) : startSize + (e.clientY - startY));
      window.dispatchEvent(new Event('resize'));
    };
    const up = () => {
      handle.classList.remove('drag');
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      try { if (key) localStorage.setItem(key, String(last)); } catch { /* ignore */ }
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
  });
}
