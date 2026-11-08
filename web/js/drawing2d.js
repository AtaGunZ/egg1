// Light 2D SVG viewer for the DrawingModel (parcel, footprint, rooms, walls, openings, dimensions) + finding overlay.
import { el, fmtNum } from './util.js';

const NS = 'http://www.w3.org/2000/svg';
const S = (name, attrs = {}, ...kids) => {
  const n = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) if (v != null) n.setAttribute(k, v);
  for (const k of kids) if (k) n.append(k);
  return n;
};
const ptsStr = poly => poly.map(p => `${p[0]},${p[1]}`).join(' ');

export class DrawingView {
  constructor(container) {
    this.root = container; this.dm = null; this.viewId = null; this.finding = null;
    this.k = 1; this.tx = 0; this.ty = 0; this.labels = [];
    this.svg = S('svg', { tabindex: 0, 'aria-label': '2D drawing view' });
    this.world = S('g'); this.labelG = S('g', { 'pointer-events': 'none' });
    this.svg.append(this.world, this.labelG);
    this.bar = el('div.d2bar', {});
    this.legend = el('div.d2legend', {});
    this.empty = el('div.d2empty', { text: 'No drawing uploaded yet. Use “DWG / DXF” in the header to add one.' });
    this.root.append(this.svg, this.bar, this.legend, this.empty);
    this._bind();
    new ResizeObserver(() => { if (this.dm && this.root.clientWidth && !this._fitted) this.fit(); this._apply(); }).observe(this.root);
  }

  setModel(dm) {
    this.dm = dm;
    this.empty.hidden = !!dm; this.svg.style.display = dm ? '' : 'none'; this.bar.hidden = this.legend.hidden = !dm;
    if (!dm) return;
    const views = dm.views || [];
    if (!views.find(v => v.id === this.viewId)) this.viewId = this._defaultView();
    this._buildBar(); this.render(true);
  }
  _defaultView() {
    const dm = this.dm, views = dm.views || [];
    return (dm.parcel && dm.parcel.view_id) || (dm.footprint && dm.footprint.view_id) || (views.find(v => v.kind === 'floor_plan') || views[0] || {}).id || null;
  }
  _buildBar() {
    const views = this.dm.views || [];
    const sel = el('select', { 'aria-label': 'Drawing view' }, ...views.map(v => el('option', { value: v.id, text: `${v.name || v.id} (${v.kind})` })));
    if (!views.length) sel.append(el('option', { value: '', text: 'whole drawing' }));
    sel.value = this.viewId || '';
    sel.addEventListener('change', () => { this.viewId = sel.value || null; this.render(true); });
    this.sel = sel;
    this.bar.replaceChildren(el('span.muted', { text: 'View' }), sel, el('button.btn.small', { text: 'Fit', on: { click: () => { this.fit(); this._apply(); } } }),
      el('span.muted.small', { text: `${(this.dm.source || {}).file || ''} · ${(this.dm.source || {}).units || '?'}` }));
  }

  /** Select a finding: switches to its view and draws the overlay. */
  show(finding) {
    this.finding = finding || null;
    if (!this.dm) return;
    if (finding && finding.view_id && (this.dm.views || []).some(v => v.id === finding.view_id)) { this.viewId = finding.view_id; if (this.sel) this.sel.value = this.viewId; }
    this.render(true);
  }

  _inView(o) { return !this.viewId || !o.view_id || o.view_id === this.viewId; }

  render(refit = false) {
    const dm = this.dm; if (!dm) return;
    this.world.replaceChildren(); this.labels = [];
    const g = this.world, vid = this.viewId, f = this.finding;
    const vb = (dm.views || []).find(v => v.id === vid);
    const hl = new Set(f ? (f.element_guids || []).concat((f.highlight || []).map(h => h.guid)) : []);
    const label = (text, x, y, cls = '', dy = 0) => this.labels.push({ text, x, y, cls, dy });
    const stroke = (c, w = 1.2, dash) => ({ stroke: c, 'stroke-width': w, 'vector-effect': 'non-scaling-stroke', fill: 'none', 'stroke-dasharray': dash });

    let n = 0;
    for (const w of dm.walls || []) { if (!this._inView(w) || !w.polyline || n++ > 8000) continue; g.append(S('polyline', { points: ptsStr(w.polyline), ...stroke('#7b8aa0', 1) })); }
    const p = dm.parcel;
    if (p && p.polygon && this._inView(p)) {
      g.append(S('polygon', { points: ptsStr(p.polygon), fill: 'rgba(63,197,130,.07)', ...stroke('#3fc582', 1.8, '8 5') }));
      const c = centroid(p.polygon); label(`Parcel ${fmtNum(p.area, 1)} m²`, c[0], c[1], 'parcel', 0);
    }
    const fp = dm.footprint;
    if (fp && fp.polygon && this._inView(fp)) {
      g.append(S('polygon', { points: ptsStr(fp.polygon), fill: 'rgba(74,163,255,.14)', ...stroke('#4aa3ff', 1.8) }));
      const c = centroid(fp.polygon); label(`Footprint ${fmtNum(fp.area, 1)} m²`, c[0], c[1], 'foot', -14);
    }
    for (const r of dm.rooms || []) {
      if (!this._inView(r) || !r.polygon) continue;
      const hot = hl.has(r.id);
      g.append(S('polygon', { points: ptsStr(r.polygon), fill: hot ? 'rgba(255,95,95,.35)' : 'rgba(255,255,255,.035)', ...stroke(hot ? '#ff5f5f' : '#4d6683', hot ? 2 : 1) }));
      const c = r.label_point || centroid(r.polygon);
      label(`${r.name || r.usage || ''}${r.area ? ' · ' + fmtNum(r.area, 1) + ' m²' : ''}`, c[0], c[1], hot ? 'hot' : 'room');
    }
    for (const s of dm.stairs || []) if (this._inView(s) && s.bbox) { const [a, b, c, d] = s.bbox; g.append(S('rect', { x: a, y: b, width: c - a, height: d - b, ...stroke('#b0b0b0', 1, '3 3') })); }
    for (const d of dm.doors || []) if (this._inView(d) && d.position) g.append(S('circle', { cx: d.position[0], cy: d.position[1], r: Math.max((d.width || 0.9) / 2, 0.25), fill: 'rgba(255,183,58,.35)', stroke: '#ffb73a', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' }));
    for (const d of dm.windows || []) if (this._inView(d) && d.position) g.append(S('circle', { cx: d.position[0], cy: d.position[1], r: Math.max((d.width || 1) / 2, 0.25), fill: 'rgba(127,194,238,.3)', stroke: '#7fc2ee', 'stroke-width': 1, 'vector-effect': 'non-scaling-stroke' }));
    n = 0;
    for (const d of dm.dimensions || []) {
      if (!this._inView(d) || !d.p1 || !d.p2 || n++ > 400) continue;
      g.append(S('line', { x1: d.p1[0], y1: d.p1[1], x2: d.p2[0], y2: d.p2[1], ...stroke('#8da2ba', 1) }));
      label(d.text || fmtNum(d.measurement, 2), (d.p1[0] + d.p2[0]) / 2, (d.p1[1] + d.p2[1]) / 2, 'dim');
    }
    // finding overlay
    const box = bboxOf([p && p.polygon, fp && fp.polygon, ...(dm.rooms || []).filter(r => this._inView(r)).map(r => r.polygon)]);
    if (f) {
      for (const d of f.dimensions || []) {
        if (!d.p1 || !d.p2) continue;
        g.append(S('line', { x1: d.p1[0], y1: d.p1[1], x2: d.p2[0], y2: d.p2[1], stroke: '#ffe14a', 'stroke-width': 4, 'stroke-linecap': 'round', 'vector-effect': 'non-scaling-stroke' }));
        label(d.label || '', (d.p1[0] + d.p2[0]) / 2, (d.p1[1] + d.p2[1]) / 2, 'fdim');
        box.add(d.p1); box.add(d.p2);
      }
      if (f.anchor && !(f.dimensions || []).length) { box.add(f.anchor); label('● ' + (f.rule_id || ''), f.anchor[0], f.anchor[1], 'fdim'); }
    }
    if (box.empty() && vb && vb.bbox) { box.add([vb.bbox[0], vb.bbox[1]]); box.add([vb.bbox[2], vb.bbox[3]]); }
    this.box = box;
    this.legend.replaceChildren(
      ...[['#3fc582', 'parcel'], ['#4aa3ff', 'footprint'], ['#4d6683', 'rooms'], ['#7b8aa0', 'walls'], ['#ffb73a', 'doors'], ['#7fc2ee', 'windows'], ['#ffe14a', 'finding']].map(([c, t]) => el('span', {}, el('i', { style: { background: c } }), t)));
    if (refit || !this._fitted) this.fit();
    this._apply();
  }

  fit() {
    const b = this.box, W = this.root.clientWidth, H = this.root.clientHeight;
    if (!b || b.empty() || !W || !H) return;
    const w = Math.max(b.maxx - b.minx, 1e-6), h = Math.max(b.maxy - b.miny, 1e-6), pad = 60;
    this.k = Math.min((W - pad * 2) / w, (H - pad * 2) / h);
    this.tx = W / 2 - ((b.minx + b.maxx) / 2) * this.k; this.ty = H / 2 + ((b.miny + b.maxy) / 2) * this.k;
    this._fitted = true;
  }
  _apply() {
    this.world.setAttribute('transform', `translate(${this.tx},${this.ty}) scale(${this.k},${-this.k})`);
    this.labelG.replaceChildren(...this.labels.map(l => {
      const t = S('text', { x: l.x * this.k + this.tx, y: -l.y * this.k + this.ty + (l.dy || 0), 'text-anchor': 'middle', 'font-size': l.cls === 'fdim' ? 13 : 11, 'font-weight': l.cls === 'fdim' || l.cls === 'hot' ? 700 : 400,
        fill: { parcel: '#3fc582', foot: '#7cc0ff', room: '#a9b8ca', hot: '#ff9a9a', dim: '#8da2ba', fdim: '#ffe14a' }[l.cls] || '#ccc', stroke: '#0b1117', 'stroke-width': 3, 'paint-order': 'stroke' });
      t.textContent = l.text; return t;
    }));
  }
  _bind() {
    let drag = null;
    this.svg.addEventListener('pointerdown', e => { drag = { x: e.clientX, y: e.clientY, tx: this.tx, ty: this.ty }; this.svg.setPointerCapture(e.pointerId); this.svg.classList.add('panning'); });
    this.svg.addEventListener('pointermove', e => { if (!drag) return; this.tx = drag.tx + e.clientX - drag.x; this.ty = drag.ty + e.clientY - drag.y; this._apply(); });
    const up = () => { drag = null; this.svg.classList.remove('panning'); };
    this.svg.addEventListener('pointerup', up); this.svg.addEventListener('pointercancel', up);
    this.svg.addEventListener('wheel', e => {
      e.preventDefault();
      const r = this.svg.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top, f = Math.exp(-e.deltaY * 0.0015);
      this.tx = mx - (mx - this.tx) * f; this.ty = my - (my - this.ty) * f; this.k *= f; this._apply();
    }, { passive: false });
    this.svg.addEventListener('dblclick', () => { this.fit(); this._apply(); });
  }
}

function centroid(poly) { let x = 0, y = 0; for (const p of poly) { x += p[0]; y += p[1]; } return [x / poly.length, y / poly.length]; }
function bboxOf(polys) {
  const b = { minx: Infinity, miny: Infinity, maxx: -Infinity, maxy: -Infinity, empty() { return this.minx === Infinity; }, add(p) { this.minx = Math.min(this.minx, p[0]); this.maxx = Math.max(this.maxx, p[0]); this.miny = Math.min(this.miny, p[1]); this.maxy = Math.max(this.maxy, p[1]); } };
  for (const poly of polys) for (const p of poly || []) b.add(p);
  return b;
}
