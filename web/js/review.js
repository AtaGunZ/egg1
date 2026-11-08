// Findings list (filters, counts) + review workspace for the selected finding (+ decision form).
import { $, $$, el, fmtNum, fmtVal, fmtReq, DECISIONS, debounce, toast } from './util.js';

const REASONS = {
  missing_measure: 'A required measurement is missing from the model',
  low_confidence: 'The measurement is only an estimate (low confidence)',
  legal_judgement: 'This needs a legal interpretation by a human',
  missing_context: 'Project context is missing (open Settings)',
  exception_may_apply: 'A regulatory exception may apply',
};
const STATUS_RANK = { violation: 0, review: 1, pass: 2, not_applicable: 3 };
const PAGE = 200;

export class Review {
  constructor(deps) {
    this.d = deps;
    this.findings = []; this.byId = new Map(); this.summary = {};
    this.selectedId = null; this.shown = PAGE; this.drafts = {};
    this.filters = { q: '', violation: true, review: true, pass: false, decided: '', category: '', article: '', storey: '' };
    this._bindFilters();
    $('#btnNextUndecided').addEventListener('click', () => this.nextUndecided());
    $('#btnRecheck').addEventListener('click', () => deps.recheck?.());
    $('#findingList').addEventListener('click', e => {
      const li = e.target.closest('.fi'); if (li) this.select(li.dataset.id);
      if (e.target.closest('.more button')) { this.shown += PAGE; this.renderList(); }
    });
  }

  // ---------------------------------------------------------------------------------- data
  setFindings(findings, summary) {
    this.findings = findings || []; this.summary = summary || {};
    this.byId = new Map(this.findings.map(f => [f.id, f]));
    this.fillFilterOptions();
    this.renderCounts();
    this.renderList();
    if (this.selectedId && !this.byId.has(this.selectedId)) { this.selectedId = null; this.d.onSelect?.(null); }
    this.renderReview();
  }
  get selected() { return this.byId.get(this.selectedId) || null; }

  setDecision(fid, rec) {
    const f = this.byId.get(fid); if (!f) return;
    f.decision = rec || null;
    this.renderCounts(); this.renderListItem(fid);
    if (fid === this.selectedId) this.renderReview(true);
  }

  // ---------------------------------------------------------------------------------- filters
  _bindFilters() {
    const f = this.filters, upd = () => { this.shown = PAGE; this.renderList(); };
    $('#fSearch').addEventListener('input', debounce(e => { f.q = e.target.value.trim().toLowerCase(); upd(); }, 120));
    for (const [id, key] of [['fViolation', 'violation'], ['fReview', 'review'], ['fPass', 'pass']]) $('#' + id).addEventListener('change', e => { f[key] = e.target.checked; upd(); });
    for (const [id, key] of [['fDecided', 'decided'], ['fCategory', 'category'], ['fArticle', 'article'], ['fStorey', 'storey']]) $('#' + id).addEventListener('change', e => { f[key] = e.target.value; upd(); });
  }
  fillFilterOptions() {
    const fill = (id, label, values, fmt = x => x) => {
      const sel = $('#' + id), keep = sel.value;
      sel.replaceChildren(el('option', { value: '', text: label }), ...values.map(v => el('option', { value: String(v), text: fmt(v) })));
      sel.value = values.map(String).includes(keep) ? keep : '';
    };
    const uniq = fn => [...new Set(this.findings.map(fn).filter(v => v != null && v !== ''))];
    fill('fCategory', 'all categories', uniq(f => f.category).sort());
    fill('fArticle', 'all articles', uniq(f => f.article).sort((a, b) => a - b), a => `Article ${a}`);
    fill('fStorey', 'all storeys', uniq(f => f.storey_name).sort());
    this.filters.category = $('#fCategory').value; this.filters.article = $('#fArticle').value; this.filters.storey = $('#fStorey').value;
  }
  matches(f) {
    const x = this.filters;
    if (f.status === 'not_applicable') return false;
    if (!x[f.status]) return false;
    if (x.category && f.category !== x.category) return false;
    if (x.article && String(f.article) !== x.article) return false;
    if (x.storey && f.storey_name !== x.storey) return false;
    if (x.decided === 'decided' && !f.decision) return false;
    if (x.decided === 'undecided' && f.decision) return false;
    if (x.q) {
      const hay = `${f.title_en} ${f.title_tr} ${f.message_en} ${f.rule_id} ${f.article} ${f.category} ${f.storey_name} ${f.decision?.note || ''}`.toLowerCase();
      if (!x.q.split(/\s+/).every(w => hay.includes(w))) return false;
    }
    return true;
  }
  get filtered() {
    return this.findings.filter(f => this.matches(f)).sort((a, b) =>
      (STATUS_RANK[a.status] - STATUS_RANK[b.status]) || ((a.article || 0) - (b.article || 0)) || String(a.paragraph || '').localeCompare(String(b.paragraph || ''), undefined, { numeric: true }) || a.id.localeCompare(b.id));
  }

  // ---------------------------------------------------------------------------------- list
  renderCounts() {
    const c = { violation: 0, review: 0, pass: 0 }; let decided = 0, open = 0;
    for (const f of this.findings) {
      if (c[f.status] != null) c[f.status]++;
      if (f.status === 'violation' || f.status === 'review') { open++; if (f.decision) decided++; }
    }
    $('#counts').replaceChildren(
      el('span.cnt.v', { text: `${c.violation} violations`, title: 'Violations' }), el('span.cnt.r', { text: `${c.review} review`, title: 'Needs human review' }),
      el('span.cnt.p', { text: `${c.pass} pass` }), el('span.cnt.d', { text: `${decided}/${open} decided`, title: 'Decided violations + reviews' }));
  }
  _item(f) {
    const dec = f.decision;
    return el('li.fi' + `.${f.status}` + (dec ? '.decided' : '') + (f.id === this.selectedId ? '.sel' : ''), { dataset: { id: f.id }, role: 'option', 'aria-selected': f.id === this.selectedId ? 'true' : 'false' },
      el('span.bar-s'),
      el('div', {},
        el('div.t', { text: f.title_en || f.title_tr || f.rule_id }),
        el('div.m', { text: f.message_en || f.message_tr || '' }),
        el('div.meta', {},
          el('span.tag.art', { text: `Art. ${f.article}${f.paragraph ? '/' + f.paragraph : ''}` }),
          f.storey_name ? el('span.tag', { text: f.storey_name }) : null,
          f.category ? el('span.tag', { text: f.category }) : null,
          dec ? el('span.tag.dec', { text: '✓ ' + DECISIONS[dec.decision].short }) : null)),
      el('span.badge.' + f.status, { text: f.status === 'violation' ? 'viol' : f.status === 'not_applicable' ? 'n/a' : f.status }));
  }
  renderList() {
    const ul = $('#findingList'), rows = this.filtered, vis = rows.slice(0, this.shown);
    ul.replaceChildren(...vis.map(f => this._item(f)));
    if (!rows.length) ul.append(el('li.pad.muted', { text: this.findings.length ? 'No findings match the filters.' : 'No findings yet. Upload a model to run the checks.' }));
    if (rows.length > vis.length) ul.append(el('li.more', {}, el('button', { text: `Show ${Math.min(PAGE, rows.length - vis.length)} more (${rows.length - vis.length} hidden)` })));
  }
  renderListItem(fid) {
    const old = $$('#findingList .fi').find(n => n.dataset.id === fid);
    const f = this.byId.get(fid);
    if (old && f) old.replaceWith(this._item(f));
  }

  // ---------------------------------------------------------------------------------- navigation
  select(id, { fly = true } = {}) {
    if (id === this.selectedId) { if (fly) this.d.onSelect?.(this.selected, { fly }); return; }
    const prev = this.selectedId; this.selectedId = id;
    $$('#findingList .fi').forEach(n => {
      const on = n.dataset.id === id; n.classList.toggle('sel', on); n.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) n.scrollIntoView({ block: 'nearest' });
    });
    this.renderReview();
    this.d.onSelect?.(this.selected, { fly, prev });
  }
  deselect() { if (this.selectedId) { this.selectedId = null; $$('#findingList .fi.sel').forEach(n => n.classList.remove('sel')); this.renderReview(); this.d.onSelect?.(null); } }
  move(delta) {
    const rows = this.filtered; if (!rows.length) return;
    let i = rows.findIndex(f => f.id === this.selectedId);
    i = i < 0 ? (delta > 0 ? 0 : rows.length - 1) : Math.max(0, Math.min(rows.length - 1, i + delta));
    if (i >= this.shown) { this.shown = i + PAGE; this.renderList(); }
    this.select(rows[i].id);
  }
  nextUndecided() {
    const rows = this.filtered.filter(f => (f.status === 'violation' || f.status === 'review'));
    if (!rows.length) return toast('Nothing to review', 'No violations or reviews match the current filters.', 'warn');
    const start = rows.findIndex(f => f.id === this.selectedId);
    for (let k = 1; k <= rows.length; k++) {
      const f = rows[(start + k + rows.length) % rows.length];
      if (!f.decision) { const i = this.filtered.indexOf(f); if (i >= this.shown) { this.shown = i + PAGE; this.renderList(); } return this.select(f.id); }
    }
    toast('All done', 'Every violation / review in this filter has a decision.', 'ok');
  }

  // ---------------------------------------------------------------------------------- review panel
  renderReview(keepScroll = false) {
    const pane = $('#reviewPane'), f = this.selected;
    const scroll = pane.scrollTop;
    if (!f) { pane.replaceChildren(el('div.muted.pad', { id: 'reviewEmpty' }, 'Select a finding to review it. Use ', el('kbd', { text: '↑' }), el('kbd', { text: '↓' }), ' to move, ', el('kbd', { text: 'A' }), ' accept, ', el('kbd', { text: 'W' }), ' waive, ', el('kbd', { text: 'C' }), ' compliant, ', el('kbd', { text: 'N' }), ' needs info, ', el('kbd', { text: 'U' }), ' next undecided.')); return; }
    const m = f.measured, r = f.required;
    const mv = fmtVal(m), rv = fmtReq(r);
    const cls = f.status === 'violation' ? 'bad' : f.status === 'pass' ? 'ok' : 'na';
    const hl = (f.highlight && f.highlight.length) ? f.highlight : (f.element_guids || []).map(g => ({ guid: g, role: 'offending' }));
    const art = `Art. ${f.article}${f.paragraph ? ' ¶' + f.paragraph : ''}`;
    const dec = f.decision;
    const ta = el('textarea', { rows: 3, placeholder: 'Reviewer note (saved with the decision)…', 'aria-label': 'Reviewer note' });
    ta.value = (dec && dec.note) || this.drafts[f.id] || '';
    const saved = el('span.saved', { text: 'Saved ✓' });
    const flash = () => { saved.classList.add('show'); setTimeout(() => saved.classList.remove('show'), 1400); };
    const save = async (decision, noteText) => {
      try { await this.d.saveDecision(f.id, decision, noteText); flash(); } catch (e) { toast('Could not save decision', e.message, 'err'); }
    };
    const autosave = debounce(() => { if (f.decision) save(f.decision.decision, ta.value); }, 700);
    ta.addEventListener('input', () => { this.drafts[f.id] = ta.value; autosave(); });
    ta.addEventListener('blur', () => { if (f.decision && f.decision.note !== ta.value) save(f.decision.decision, ta.value); });
    ta.addEventListener('keydown', e => { if (e.key === 'Escape') ta.blur(); });

    const dbtns = Object.entries(DECISIONS).map(([k, v]) => el('button.dbtn' + (dec && dec.decision === k ? '.on' : ''), {
      dataset: { d: k }, title: `${v.label} (${v.key}) — press again to clear`, 'aria-pressed': dec && dec.decision === k ? 'true' : 'false',
      on: { click: () => this.decide(k) },
    }, v.label, el('kbd', { text: v.key })));
    this._saveFn = save; this._ta = ta;

    const excerpt = f.regulation_excerpt;
    const body = el('div.rv', {},
      el('div', {}, el('h2', { text: f.title_en || f.title_tr || f.rule_id }), f.title_tr && f.title_tr !== f.title_en ? el('div.tr', { text: f.title_tr }) : null),
      el('div.chips-row', {},
        el('span.badge.' + f.status, { text: f.status }),
        el('button.rulebtn', { title: 'Show the rule, its limit, exceptions and the full article text', on: { click: () => (this.d.openRule || this.d.openArticle)?.(f) }, text: `📖 Show relevant rule · ${art}` }),
        el('span.tag', { text: f.rule_id }),
        f.category ? el('span.tag', { text: f.category }) : null, f.severity ? el('span.tag', { text: f.severity }) : null,
        f.storey_name ? el('span.tag', { text: f.storey_name }) : null, el('span.tag', { text: (f.source || '').replace('_', ' ') })),
      el('div.msg', { text: f.message_en || f.message_tr || '' }),
      (f.message_tr && f.message_tr !== f.message_en) ? el('div.muted.small', { text: f.message_tr }) : null,
      el('div.mvr', {},
        el('div', {}, el('div.k', { text: 'Measured' }), el('div.v.' + (mv ? cls : 'na'), {}, mv || 'not available', m && m.provenance ? el('span.prov.' + m.provenance, { text: m.provenance, title: `Value taken from: ${m.provenance}` }) : null)),
        el('div', {}, el('div.k', { text: 'Required' }), el('div.v', {}, rv || '–'))),
      (f.review_reason || f.review_hint) ? el('div.hintbox', {}, el('b', { text: 'Needs a human: ' }), REASONS[f.review_reason] || f.review_reason || '', f.review_hint ? el('div', { text: f.review_hint, style: { marginTop: '4px' } }) : null) : null,
      excerpt ? el('details.excerpt', {}, el('summary', { text: `Regulation text — ${art}` }), el('p', { text: excerpt }), el('button.btn.small', { text: 'Open full rule ↗', on: { click: () => this.d.openRule?.(f) } })) : null,
      hl.length ? el('div', {}, el('h4', { text: `Elements (${hl.length})` }), el('div.els', {}, ...hl.slice(0, 40).map(h => {
        const info = this.d.elementInfo?.(h.guid) || {};
        return el('button.el', { title: h.guid, on: { click: () => this.d.flyToElement?.(h.guid) } }, el('span.role.' + h.role), el('span.nm', { text: info.name || h.guid }), el('small', { text: info.kind || '' }));
      }), hl.length > 40 ? el('div.muted.small', { text: `… and ${hl.length - 40} more` }) : null)) : null,
      (f.source === 'drawing_model' || f.view_id) ? el('div.row', {}, el('button.btn.small', { text: 'Show in drawing (2D)', on: { click: () => this.d.showDrawing?.(f) } })) : null,
      el('div.dform', {}, el('h4', { text: 'Decision' }), el('div.dbtns', {}, ...dbtns), el('div', { style: { height: '8px' } }), ta,
        el('div.row.between', { style: { marginTop: '6px' } },
          el('span.dmeta', { text: dec ? `${dec.by || 'reviewer'} · ${(dec.at || '').replace('T', ' ').slice(0, 16)}` : 'No decision yet' }),
          el('span.row', {}, saved, dec ? el('button.linkish', { text: 'clear', title: 'Remove the decision', on: { click: () => this.decide(dec.decision) } }) : null))),
    );
    pane.replaceChildren(body);
    pane.scrollTop = keepScroll ? scroll : 0;
  }

  /** Apply decision k to the selected finding (toggles off when already set). */
  async decide(k) {
    const f = this.selected; if (!f) return;
    const same = f.decision && f.decision.decision === k;
    const noteText = this._ta ? this._ta.value : (f.decision?.note || '');
    try {
      await this.d.saveDecision(f.id, same ? null : k, same ? '' : noteText);
      const sv = $('#reviewPane .saved'); if (sv) { sv.classList.add('show'); setTimeout(() => sv.classList.remove('show'), 1400); }
      if (same) { this.drafts[f.id] = ''; }
    } catch (e) { toast('Could not save decision', e.message, 'err'); }
  }
}
