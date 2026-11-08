// Project settings drawer: ProjectContext form + rule threshold overrides.
import { $, $$, el, fmtNum, toast } from './util.js';
import { api } from './api.js';

const OPT = {
  use: [['', '— unknown —'], ['residential', 'Residential'], ['commercial', 'Commercial'], ['mixed', 'Mixed (ground-floor commerce)'], ['other', 'Other']],
  zone_type: [['', '— unknown —'], ['konut', 'Konut (residential)'], ['ticaret', 'Ticaret (commercial)'], ['karma', 'Karma (mixed)'], ['sanayi', 'Sanayi (industrial)'], ['other', 'Other']],
  building_order: [['', '— unknown —'], ['detached', 'Detached (ayrık)'], ['adjacent', 'Adjacent (bitişik)'], ['block', 'Block (blok)']],
  heating: [['', '— unknown —'], ['central', 'Central'], ['stove', 'Stove'], ['none', 'None']],
  has_elevator: [['', '— unknown —'], ['true', 'Yes'], ['false', 'No']],
};
const FIELDS = [
  ['use', 'Building use', 'select'], ['zone_type', 'Zone type', 'select'], ['building_order', 'Building order', 'select'], ['heating', 'Heating', 'select'],
  ['parcel_area', 'Parcel area (m²)', 'number'], ['road_width', 'Road width (m)', 'number'],
  ['taks', 'TAKS (footprint ratio)', 'number'], ['kaks', 'KAKS / emsal', 'number'],
  ['max_storeys', 'Max storeys (Hmax kat)', 'int'], ['max_height', 'Max height (m)', 'number'],
  ['front_setback', 'Front setback (m)', 'number'], ['side_setback', 'Side setback (m)', 'number'], ['rear_setback', 'Rear setback (m)', 'number'],
  ['front_edge_index', 'Front edge index (parcel edge facing the road)', 'int'],
  ['has_elevator', 'Has elevator', 'select'], ['is_single_dwelling', 'Single dwelling', 'check'],
];

export class Settings {
  constructor({ getProject, hasDrawing, onSaved }) {
    this.get = getProject; this.hasDrawing = hasDrawing; this.onSaved = onSaved;
    this.tab = 'ctx'; this.ctx = {}; this.rules = null; this.overrides = {};
    $('#drawerClose').addEventListener('click', () => this.close());
    $('#drawerBack').addEventListener('click', () => this.close());
    $$('.drawer-tabs .tab').forEach(t => t.addEventListener('click', () => this.show(t.dataset.tab)));
  }
  get isOpen() { return !$('#drawer').hidden; }
  async open(tab) { $('#drawer').hidden = false; $('#drawerBack').hidden = false; await this.show(tab || this.tab); }
  close() { $('#drawer').hidden = true; $('#drawerBack').hidden = true; }

  async show(tab) {
    this.tab = tab;
    $$('.drawer-tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    const body = $('#drawerBody'); body.replaceChildren(el('div.muted', { text: 'Loading…' }));
    try {
      const id = this.get();
      this.ctx = await api.context(id); this.overrides = { ...(this.ctx.overrides || {}) };
      if (tab === 'ctx') this.renderContext(); else await this.renderRules();
    } catch (e) { body.replaceChildren(el('div.hintbox', { text: e.message })); }
  }

  // ------------------------------------------------------------------------------------------ context
  renderContext() {
    const body = $('#drawerBody'), ctx = this.ctx; this.inputs = {}; this.srcs = {};
    const grid = el('div.fgrid');
    for (const [key, label, type] of FIELDS) {
      let inp;
      if (type === 'select') {
        inp = el('select', {}, ...OPT[key].map(([v, t]) => el('option', { value: v, text: t })));
        inp.value = ctx[key] == null ? '' : String(ctx[key]);
      } else if (type === 'check') { inp = el('input', { type: 'checkbox' }); inp.checked = !!ctx[key]; }
      else { inp = el('input', { type: 'number', step: type === 'int' ? '1' : 'any', placeholder: 'unknown' }); inp.value = ctx[key] == null ? '' : ctx[key]; }
      this.inputs[key] = { inp, type };
      const src = el('span.src'); this.srcs[key] = src;
      grid.append(el('div.field' + (type === 'check' ? '.full' : ''), {}, el('label', { text: label }), type === 'check' ? el('label.check', {}, inp, 'Yes') : inp, src));
    }
    const derive = el('button.btn', { text: '⇣ Derive from drawing', disabled: !this.hasDrawing() || null, title: this.hasDrawing() ? 'Fill parcel area, TAKS … from the uploaded drawing' : 'Upload a DWG/DXF drawing first', on: { click: () => this.derive() } });
    const save = el('button.btn.primary', { text: 'Save & re-check', on: { click: () => this.saveContext(save) } });
    body.replaceChildren(
      el('p.muted', { text: 'Parcel and plan-note parameters. Empty = unknown: the engine then falls back to the regulation default or marks the finding “needs review”.' }),
      grid,
      el('div.actions', {}, save, derive, el('span.muted.small', { text: 'Rule thresholds are on the next tab.' })));
  }
  async derive() {
    try {
      const d = await api.deriveContext(this.get());
      let n = 0;
      for (const [k, v] of Object.entries(d.context || {})) {
        const f = this.inputs[k]; if (!f) continue;
        if (f.type === 'check') f.inp.checked = !!v; else f.inp.value = v == null ? '' : v;
        this.srcs[k].textContent = '↳ from drawing: ' + (d.sources?.[k] || 'drawing'); n++;
      }
      this.derivedExtra = Object.fromEntries(Object.entries(d.context || {}).filter(([k]) => !this.inputs[k]));
      toast(n ? `Filled ${n} field(s) from the drawing` : 'Nothing could be derived', (d.warnings || []).join(' · '), n ? 'ok' : 'warn');
    } catch (e) { toast('Derive failed', e.message, 'err'); }
  }
  async saveContext(btn) {
    const out = { ...this.ctx, ...(this.derivedExtra || {}) };
    for (const [k, { inp, type }] of Object.entries(this.inputs)) {
      let v;
      if (type === 'check') v = inp.checked;
      else if (type === 'select') v = inp.value === '' ? null : (k === 'has_elevator' ? inp.value === 'true' : inp.value);
      else v = inp.value === '' ? null : (type === 'int' ? parseInt(inp.value, 10) : parseFloat(inp.value));
      if (v === null) delete out[k]; else out[k] = v;
    }
    out.municipality = out.municipality || 'kayseri';
    btn.disabled = true; btn.textContent = 'Saving & checking…';
    try { const r = await api.putContext(this.get(), out); toast('Context saved', 'Findings re-checked.', 'ok'); this.ctx = r.context; this.onSaved?.(r); }
    catch (e) { toast('Save failed', e.message, 'err'); }
    btn.disabled = false; btn.textContent = 'Save & re-check';
  }

  // ------------------------------------------------------------------------------------------ rules
  async renderRules() {
    const body = $('#drawerBody');
    if (!this.rules) {
      try { this.rules = await api.rules(); }
      catch (e) { body.replaceChildren(el('div.hintbox', { text: 'Rule catalogue not available yet: ' + e.message })); return; }
    }
    const rules = this.rules.rules || [];
    this.ovInputs = {};
    const q = el('input', { type: 'search', placeholder: 'Filter rules (id, article, text)…', style: { flex: 1 } });
    const only = el('input', { type: 'checkbox' });
    const list = el('div');
    const counts = rules.reduce((a, r) => (a[r.automation] = (a[r.automation] || 0) + 1, a), {});
    const draw = () => {
      const t = q.value.trim().toLowerCase();
      list.replaceChildren(...rules.filter(r => (!only.checked || this.editable(r)) && (!t || `${r.id} ${r.title_en} ${r.title_tr} ${r.article} ${r.category}`.toLowerCase().includes(t))).slice(0, 400).map(r => this.ruleRow(r)));
    };
    q.addEventListener('input', draw); only.addEventListener('change', draw);
    const save = el('button.btn.primary', { text: 'Save thresholds & re-check', on: { click: () => this.saveOverrides(save) } });
    body.replaceChildren(
      el('p.muted', {}, `${rules.length} rules from `, el('b', { text: this.rules.regulation?.title || 'catalogue' }), ` · `, el('span.auto.auto', { text: `${counts.auto || 0} auto` }), ' ', el('span.auto.semi', { text: `${counts.semi || 0} semi` }), ' ', el('span.auto.manual', { text: `${counts.manual || 0} manual — needs human` })),
      el('div.row', {}, q, el('label.check', {}, only, 'only editable')),
      list, el('div.actions', {}, save, el('span.muted.small', { text: 'Only changed values are stored as project overrides.' })));
    draw();
  }
  editable(r) { return r.automation !== 'manual' && r.check && typeof r.check.limit === 'number'; }
  ruleRow(r) {
    const c = r.check || {}, ov = this.overrides[r.id] || {};
    const manual = r.automation === 'manual';
    const rb = el('div.rb', {}, el('div', { text: r.text_tr || '' }));
    if (manual) rb.append(el('div.hintbox', { style: { marginTop: '6px' } }, el('b', { text: 'Needs human: ' }), 'catalogued from the regulation, but the engine does not decide it. It is never silently skipped; reviewers judge it manually.'));
    else if (this.editable(r)) {
      const mk = (key, def) => {
        const inp = el('input', { type: 'number', step: 'any', placeholder: String(def), 'aria-label': `${r.id} ${key}` });
        if (ov[key] != null) inp.value = ov[key];
        const row = el('span.ovr' + (ov[key] != null ? '.changed' : ''), {}, el('span', { text: `${key === 'limit' ? (c.op || 'limit') : 'max'} (default ${fmtNum(def, 3)} ${c.unit || ''})` }), inp,
          el('button.btn.small', { text: 'reset', on: { click: () => { inp.value = ''; row.classList.remove('changed'); } } }));
        inp.addEventListener('input', () => row.classList.toggle('changed', inp.value !== ''));
        (this.ovInputs[r.id] ||= {})[key] = { inp, def };
        return row;
      };
      rb.append(mk('limit', c.limit)); if (typeof c.limit_max === 'number') rb.append(mk('limit_max', c.limit_max));
    } else rb.append(el('div.muted.small', { text: 'No numeric threshold to override (custom check).' }));
    return el('details.rule' + (manual ? '.manual' : ''), {},
      el('summary', {}, el('span.tag.art', { text: r.id }), el('span', { style: { flex: 1 }, text: r.title_en || r.title_tr }), manual ? el('span.auto.manual', { text: 'needs human' }) : el('span.auto.' + r.automation, { text: r.automation }),
        this.overrides[r.id] ? el('span.tag.dec', { text: 'overridden' }) : null), rb);
  }
  async saveOverrides(btn) {
    const next = { ...this.overrides };
    for (const [id, keys] of Object.entries(this.ovInputs || {})) {
      const o = {};
      for (const [k, { inp }] of Object.entries(keys)) if (inp.value !== '') o[k] = parseFloat(inp.value);
      if (Object.keys(o).length) next[id] = o; else delete next[id];
    }
    btn.disabled = true; btn.textContent = 'Saving & checking…';
    try { const r = await api.putOverrides(this.get(), next); this.overrides = r.overrides; toast('Thresholds saved', `${Object.keys(r.overrides).length} override(s) active. Findings re-checked.`, 'ok'); this.onSaved?.(r); }
    catch (e) { toast('Save failed', e.message, 'err'); }
    btn.disabled = false; btn.textContent = 'Save thresholds & re-check';
  }
}
