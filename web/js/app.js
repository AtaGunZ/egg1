// BIMCheck web UI bootstrap: routing, project loading, live updates, wiring of viewer / review / settings / drawing.
import { $, $$, el, toast, fmtNum, fmtBytes, dragSplitter, DECISIONS } from './util.js';
import { api, upload, connectWS } from './api.js';
import { Viewer } from './viewer.js';
import { initTools } from './tools.js';
import { Review } from './review.js';
import { Settings } from './settings.js';
import { DrawingView } from './drawing2d.js';

const S = { pid: null, project: null, bm: null, dm: null, ws: null, glbVersion: 0, dmVersion: 0, wsOpen: false, stage: 'idle', stageMsg: '', samples: [], pending: {}, uploading: false };
let viewer, tools, review, settings, drawing, queue = Promise.resolve();
const tab = { cur: '3d' };

// ================================================================================================ overlay / progress
const overlay = {
  show(msg, frac, sub) {
    $('#overlay').hidden = false; $('#overlayMsg').textContent = msg;
    $('#overlayBar').hidden = frac == null; if (frac != null) $('#overlayBar div').style.width = Math.round(frac * 100) + '%';
    $('#overlaySub').textContent = sub || '';
    const pb = $('#progressbar'); pb.hidden = false;
    if (frac == null) pb.classList.add('indet'); else { pb.classList.remove('indet'); pb.firstElementChild.style.width = Math.round(frac * 100) + '%'; }
  },
  hide() { $('#overlay').hidden = true; $('#progressbar').hidden = true; $('#progressbar').classList.remove('indet'); },
};

function setStatus() {
  const dot = $('#statusDot'), txt = $('#statusText');
  const busy = S.stage !== 'idle';
  dot.className = 'dot ' + (!S.wsOpen ? 'err' : busy ? 'busy' : 'ok');
  txt.textContent = !S.wsOpen ? 'offline' : busy ? (S.stageMsg || S.stage) : 'live';
  $('#statusBox').title = S.wsOpen ? 'Connected: re-checks arrive automatically' : 'Disconnected, reconnecting…';
  if (!S.uploading) {
    const pb = $('#progressbar');
    if (busy && S.pid) { pb.hidden = false; pb.classList.add('indet'); } else if (!$('#overlay').hidden === false) { pb.hidden = true; pb.classList.remove('indet'); }
  }
  if (S.uploading && busy) $('#overlaySub').textContent = S.stageMsg;
}

// ================================================================================================ routing
window.addEventListener('hashchange', route);
async function route() {
  const m = /^#\/([\w-]+)/.exec(location.hash);
  if (!m) return showHome();
  await openProject(m[1]);
}
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

async function showHome() {
  closeProject();
  $('#home').hidden = false; $('#layout').hidden = true; $('#topActions').hidden = true; $('#projectBox').hidden = true;
  document.title = 'BIMCheck';
  S.stage = 'idle'; setStatus();
  const list = $('#projectList');
  try {
    const ps = await api.projects();
    list.replaceChildren(...(ps.length ? ps.map(p => el('a.pitem', { href: '#/' + p.id },
      el('span.nm', { text: p.name }), el('span.mt', { text: [p.model && p.model.file, p.drawing && p.drawing.file].filter(Boolean).join(' · ') || 'empty' }),
      el('span.spacer'), el('span.mt', { text: (p.updated || '').replace('T', ' ').slice(0, 16) }),
      el('button.btn.small', { text: 'delete', title: 'Delete project', on: { click: async ev => { ev.preventDefault(); ev.stopPropagation(); if (confirm(`Delete project "${p.name}" and all its data?`)) { await api.deleteProject(p.id); showHome(); } } } }))) : [el('span.muted', { text: 'none yet' })]));
  } catch (e) { list.replaceChildren(el('span.muted', { text: 'Could not load projects: ' + e.message })); }
}

function closeProject() {
  S.ws?.close(); S.ws = null; S.pid = null; S.project = null; S.bm = null; S.dm = null; S.glbVersion = 0; S.dmVersion = 0; S.wsOpen = false;
  if (viewer) { viewer.clearModel(); viewer.setBuildingModel(null); }
  review?.setFindings([], {}); drawing?.setModel(null);
  settings?.close(); hidePopover();
}

async function openProject(id) {
  if (S.pid === id && S.project) return;
  closeProject();
  let p;
  try { p = await api.project(id); } catch (e) { toast('Project not found', e.message, 'err'); location.hash = '#/'; return; }
  S.pid = id; S.project = p;
  S.willUpload = !!S.pending[id];   // a file is about to be uploaded: don't flash the "No 3D model yet" card
  if (S.willUpload) overlay.show('Loading sample…', null, 'Reading the model, extracting measurements and running checks (can take ~25 s)');
  $('#home').hidden = true; $('#layout').hidden = false; $('#topActions').hidden = false; $('#projectBox').hidden = false;
  ensureUI();
  renderHeader();
  viewer.resize();
  S.ws = connectWS(id, {
    state: st => { S.wsOpen = st === 'open'; setStatus(); if (st === 'open' && S.project) enqueue(() => refreshAll({ quiet: true })); },
    event: onWsEvent,
  });
  await enqueue(() => refreshAll({ initial: true }));
  const pend = S.pending[id]; delete S.pending[id];
  try { for (const f of pend || []) await uploadFile(f); }
  finally { S.willUpload = false; if (pend) { overlay.hide(); renderHeader(); } }
}

// ================================================================================================ UI construction (once)
let uiReady = false;
function ensureUI() {
  if (uiReady) return; uiReady = true;
  viewer = new Viewer({ canvas: $('#gl'), container: $('#view3d'), labels: $('#labels'), cube: $('#cube') });
  window.__viewer = viewer; // handy for debugging in the console
  tools = initTools(viewer, { action: doAction });
  viewer.onChange = kind => { if (kind === 'appearance') tools.sync(); if (kind === 'appearance' || kind === 'section') updateHint(); };
  viewer.onPick = onPick;
  review = new Review({
    onSelect: onSelectFinding, saveDecision, openArticle, recheck: () => runRecheck(),
    elementInfo: guid => { const e = viewer.element(guid); return e ? { name: e.name || e.ifc_class, kind: e.kind } : (viewer.record(guid) ? { name: viewer.record(guid).name, kind: viewer.record(guid).kind } : null); },
    flyToElement: guid => { setTab('3d'); viewer.flyToGuids([guid]); },
    showDrawing: f => { setTab('2d'); drawing.show(f); },
  });
  settings = new Settings({ getProject: () => S.pid, hasDrawing: () => !!S.dm, onSaved: () => enqueue(() => refreshAll({ quiet: true })) });
  drawing = new DrawingView($('#view2d'));
  window.__review = review;
  dragSplitter($('#vsplit'), { dir: 'v', target: $('#side'), min: 320, max: Math.round(window.innerWidth * 0.7), store: 'side' });
  dragSplitter($('#hsplit'), { dir: 'h', target: $('#findingsPane'), min: 120, max: 900, store: 'list' });
  window.addEventListener('resize', () => viewer.resize());
  $('#tab3d').addEventListener('click', () => setTab('3d')); $('#tab2d').addEventListener('click', () => setTab('2d'));
  $('#btnSettings').addEventListener('click', () => settings.open());
  $('#btnHelp').addEventListener('click', showHelp);
  $('#projectName').addEventListener('click', async () => {
    const n = prompt('Project name', S.project.name); if (n && n.trim() && n !== S.project.name) { S.project = await api.rename(S.pid, n.trim()); renderHeader(); }
  });
  const rm = $('#reportMenu');
  $('#btnReport').addEventListener('click', e => { e.stopPropagation(); rm.hidden = !rm.hidden; });
  document.addEventListener('click', () => { rm.hidden = true; });
  $('#modalClose').addEventListener('click', closeModal); $('#modalBack').addEventListener('click', e => { if (e.target.id === 'modalBack') closeModal(); });
  for (const id of ['fileModel', 'fileDrawing', 'emptyModel']) $('#' + id).addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) uploadFile(f); });
  document.addEventListener('keydown', onKey);
  document.addEventListener('pointerdown', e => { if (!e.target.closest('#popover') && !e.target.closest('#gl')) hidePopover(); });
  fillSampleButtons($('#emptySamples'), 'model');
  fillSampleButtons(drawing.empty, 'drawing', true);
}

// ================================================================================================ home page wiring (always)
function initHome() {
  $('#homeModel').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) newProjectWithFiles([f]); });
  $('#homeDrawing').addEventListener('change', e => { const f = e.target.files[0]; e.target.value = ''; if (f) newProjectWithFiles([f]); });
  api.samples().then(s => { S.samples = s; fillSampleButtons($('#sampleButtons'), 'all'); fillSampleButtons($('#emptySamples'), 'model'); if (drawing) fillSampleButtons(drawing.empty, 'drawing', true); }).catch(() => {});
}

function fillSampleButtons(host, which, append = false) {
  if (!host) return;
  host.querySelectorAll('.sample-btn').forEach(n => n.remove());
  const list = S.samples.filter(s => which === 'all' || (which === 'model' ? s.kind === 'ifc' : s.kind !== 'ifc'));
  for (const s of list) {
    const b = el('button.btn.sample-btn' + (s.kind === 'ifc' ? '.primary' : ''), { title: `${s.name} · ${fmtBytes(s.size)}`, on: { click: () => loadSample(s) } },
      (s.kind === 'ifc' ? 'Load sample: ' : 'Load drawing sample: ') + s.label, el('span.muted.small', { text: fmtBytes(s.size) }));
    if (s.kind === 'ifc') b.style.color = '';
    host.append(b);
  }
}

async function loadSample(s) {
  try {
    const blob = await (await fetch(s.url)).blob();
    const file = new File([blob], s.name, { type: 'application/octet-stream' });
    if (S.pid && !$('#layout').hidden) await uploadFile(file);
    else await newProjectWithFiles([file], s.label);
  } catch (e) { toast('Could not load sample', e.message, 'err'); }
}

async function newProjectWithFiles(files, name) {
  try {
    const p = await api.createProject(name || files[0].name.replace(/\.[^.]+$/, ''));
    S.pending[p.id] = files;
    go('#/' + p.id);
  } catch (e) { toast('Could not create project', e.message, 'err'); }
}

// drag & drop anywhere
let dragDepth = 0;
document.addEventListener('dragenter', e => { if (e.dataTransfer?.types?.includes('Files')) { dragDepth++; $('#dropCard').classList.add('drag'); } });
document.addEventListener('dragleave', () => { if (--dragDepth <= 0) { dragDepth = 0; $('#dropCard').classList.remove('drag'); } });
document.addEventListener('dragover', e => { if (e.dataTransfer?.types?.includes('Files')) e.preventDefault(); });
document.addEventListener('drop', e => {
  e.preventDefault(); dragDepth = 0; $('#dropCard').classList.remove('drag');
  const files = [...(e.dataTransfer?.files || [])].filter(f => /\.(ifc|dwg|dxf)$/i.test(f.name));
  if (!files.length) return toast('Unsupported file', 'Drop an .ifc, .dwg or .dxf file.', 'warn');
  files.sort((a, b) => (/\.ifc$/i.test(a.name) ? 0 : 1) - (/\.ifc$/i.test(b.name) ? 0 : 1));
  if (S.pid && !$('#layout').hidden) (async () => { for (const f of files) await uploadFile(f); })(); else newProjectWithFiles(files);
});

// ================================================================================================ header / uploads
function renderHeader() {
  const p = S.project; if (!p) return;
  $('#projectName').textContent = p.name; document.title = `${p.name} · BIMCheck`;
  const tags = $('#fileTags'); tags.replaceChildren();
  if (p.model) tags.append(el('span.filetag', { text: '▣ ' + p.model.file, title: `${p.model.ifc_schema || ''} ${p.model.application || ''}` }));
  if (p.drawing) tags.append(el('span.filetag', { text: '▤ ' + p.drawing.file }));
  for (const a of $$('#reportMenu a')) { a.href = api.reportUrl(S.pid, a.dataset.fmt); if (a.dataset.fmt !== 'html') a.setAttribute('download', ''); }
  $('#emptyView').hidden = !!(p.model || p.has_glb || S.willUpload || S.uploading);
}

async function uploadFile(file) {
  const ext = (/\.([^.]+)$/.exec(file.name) || [])[1]?.toLowerCase();
  const kind = ext === 'ifc' ? 'model' : (ext === 'dwg' || ext === 'dxf') ? 'drawing' : null;
  if (!kind) return toast('Unsupported file', `${file.name}: expected .ifc, .dwg or .dxf`, 'warn');
  if (!S.pid) return newProjectWithFiles([file]);
  S.uploading = true;
  const t0 = performance.now();
  overlay.show(`Uploading ${file.name}`, 0, fmtBytes(file.size));
  const tick = setInterval(() => { if ($('#overlaySub').textContent.startsWith('server') || S.stage !== 'idle') $('#overlaySub').textContent = `${S.stageMsg || 'processing'} · ${Math.round((performance.now() - t0) / 1000)} s`; }, 1000);
  try {
    const r = await upload(`/api/projects/${S.pid}/${kind}`, file, f => {
      if (f === 'server') { overlay.show(kind === 'model' ? 'Reading the IFC model…' : 'Reading the drawing…', null, 'server: extracting geometry and measurements'); $('#overlaySub').textContent = 'server: extracting geometry and measurements'; }
      else overlay.show(`Uploading ${file.name}`, f, `${Math.round(f * 100)}% of ${fmtBytes(file.size)}`);
    });
    S.project = { ...S.project, ...r };
    if (r.check_error) toast('Rule engine not available', r.check_error, 'warn', 9000);
    const w = (r.model && r.model.warnings) || (r.drawing && r.drawing.warnings) || [];
    if (w.length) toast(`${file.name}: ${w.length} warning(s)`, w.slice(0, 3).join(' · '), 'warn', 9000);
    await enqueue(() => refreshAll({ quiet: false, uploadedKind: kind }));
    if (kind === 'drawing' && !S.dm) toast('No usable drawing data', 'See warnings in the drawing tab.', 'warn');
    if (kind === 'drawing') setTab(S.bm ? tab.cur : '2d');
  } catch (e) {
    toast(`Upload failed: ${file.name}`, e.message, 'err', 12000);
  } finally {
    clearInterval(tick); S.uploading = false; overlay.hide(); setStatus();
  }
}

// ================================================================================================ data loading
function enqueue(fn) { queue = queue.then(fn, fn).catch(e => { console.error(e); toast('Update failed', e.message, 'err'); }); return queue; }

async function refreshAll({ initial = false, quiet = false } = {}) {
  const id = S.pid; if (!id) return;
  const p = await api.project(id); if (S.pid !== id) return;
  S.project = p; renderHeader();
  const selId = review.selectedId;
  // building model + GLB
  if (p.model_version !== S.glbVersion) {
    const keep = S.glbVersion > 0;
    if (p.model) { try { S.bm = await api.buildingModel(id); } catch { S.bm = null; } } else S.bm = null;
    viewer.setBuildingModel(S.bm);
    if (p.has_glb) {
      if (!S.uploading) overlay.show('Loading 3D geometry…', 0);
      try {
        await viewer.loadGLB(api.glbUrl(id, p.model_version), { keepCamera: keep, onProgress: f => { if (!S.uploading) overlay.show('Loading 3D geometry…', f); } });
        S.glbVersion = p.model_version; tools.rebuild();
      } catch (e) { toast('3D view failed', e.message, 'err', 9000); }
      finally { if (!S.uploading) overlay.hide(); }
    } else { viewer.clearModel(); tools.rebuild(); S.glbVersion = p.model_version; }
    $('#emptyView').hidden = !!(p.model || p.has_glb || S.willUpload || S.uploading);
    if (p.model && !p.has_glb) toast('No 3D geometry', 'Building data was read but the 3D export is missing.', 'warn');
  }
  if (p.drawing_version !== S.dmVersion) {
    if (p.drawing) { try { S.dm = await api.drawingModel(id); } catch { S.dm = null; } } else S.dm = null;
    drawing.setModel(S.dm); S.dmVersion = p.drawing_version;
  }
  const fr = await api.findings(id); if (S.pid !== id) return;
  review.setFindings(fr.findings, fr.summary);
  if (selId && review.byId.has(selId)) onSelectFinding(review.byId.get(selId), { fly: false });
  if (!selId && initial && fr.findings.length) { /* leave unselected so the whole model is visible */ }
  if (!quiet && fr.summary && fr.summary.errors?.length) toast('Engine reported errors', fr.summary.errors.slice(0, 2).join(' · '), 'warn', 9000);
  updateHint();
}

async function runRecheck() {
  try { overlay.show('Re-running all checks…'); await fetch(`/api/projects/${S.pid}/recheck`, { method: 'POST' }); await enqueue(() => refreshAll({ quiet: true })); toast('Re-checked', '', 'ok'); }
  catch (e) { toast('Re-check failed', e.message, 'err'); } finally { overlay.hide(); }
}

function onWsEvent(ev) {
  if (ev.type === 'status' || ev.type === 'hello') { S.stage = ev.stage || 'idle'; S.stageMsg = ev.message || ''; setStatus(); if (ev.error && ev.stage === 'idle') toast('Server', ev.error, 'warn'); return; }
  if (ev.type === 'decision_updated') { review.setDecision(ev.finding_id, ev.decision); return; }
  if (ev.type === 'model_updated' || ev.type === 'findings_updated') {
    const d = ev.diff, c = d && (d.counts || {});
    const n = k => d ? (c[k] ?? (Array.isArray(d[k]) ? d[k].length : +d[k] || 0)) : 0;
    const mine = S.uploading;
    enqueue(async () => {
      await refreshAll({ quiet: true });
      if (d && !d.initial) {
        const parts = [`${n('new')} new`, `${n('resolved')} resolved`, `${n('changed')} changed`];
        toast(ev.type === 'model_updated' ? (ev.kind === 'drawing' ? 'Drawing updated' : 'Model updated') : 'Findings updated', parts.join(' · '), n('new') ? 'warn' : 'ok', 7000);
      } else if (!mine && ev.type === 'model_updated') toast(ev.kind === 'drawing' ? 'Drawing loaded' : 'Model loaded', ev.summary ? `${ev.summary.violation || 0} violations · ${ev.summary.review || 0} to review` : '', 'ok');
    });
  }
}

// ================================================================================================ review <-> viewer
function onSelectFinding(f, opt = {}) {
  hidePopover();
  if (!f) { viewer.clearFocus(); drawing.show(null); updateHint(); return; }
  const hasGuids = (f.element_guids || []).length || (f.highlight || []).length;
  const drawingOnly = f.source === 'drawing_model' && !hasGuids;
  if (drawingOnly && S.dm) setTab('2d'); else if (tab.cur === '2d' && viewer.records.size && hasGuids) setTab('3d');
  drawing.show(f);
  if (viewer.records.size) {
    const r = viewer.focus(f, { fly: opt.fly !== false && tab.cur === '3d' });
    S.focusInfo = r;
    if (r.missing) toast('Some elements are not in the 3D view', `${r.missing} highlighted element(s) have no geometry.`, 'warn');
  }
  updateHint();
}
function updateHint() {
  const h = $('#stageHint'), f = review?.selected, fs = viewer?.focusState;
  if (!f || !fs) { h.textContent = viewer?.records.size ? 'Click a finding to fly to it · click elements for properties' : ''; return; }
  const st = fs.storey ? viewer.storeys[fs.storey.idx]?.name : null;
  h.textContent = `${fs.hl.size} element(s) highlighted${st ? ' · isolated: ' + st : ''}${fs.autoHide.size && viewer.opt.autoHide ? ` · ${fs.autoHide.size} ceiling/roof elements hidden` : ''}`;
}

async function saveDecision(fid, decision, note) {
  const r = await api.decision(S.pid, fid, decision, note);
  review.setDecision(fid, r.decision);
}

// ================================================================================================ picking & popover
function onPick(guid, o) {
  if (!guid) { if (!o.additive) { viewer.setPicked([]); hidePopover(); } return; }
  const next = new Set(viewer.picked);
  if (o.additive) { next.has(guid) ? next.delete(guid) : next.add(guid); } else { next.clear(); next.add(guid); }
  viewer.setPicked([...next]);
  if (next.size === 1) showPopover(guid, o.x, o.y); else hidePopover();
}
function hidePopover() { const p = $('#popover'); if (p) p.hidden = true; }
function showPopover(guid, x, y) {
  const pop = $('#popover'), rec = viewer.record(guid), be = viewer.element(guid) || {};
  const storey = viewer.storeys[rec?.storeyIdx]?.name;
  const rows = [['Class', be.ifc_class || rec?.ifcClass || '–'], ['Kind', be.kind || rec?.kind || '–'], ['Storey', storey || '–']];
  for (const [k, v] of Object.entries(be.measures || {})) {
    if (v == null || Array.isArray(v) || typeof v === 'object') continue;
    const prov = be.provenance && be.provenance[k];
    rows.push([k.replace(/_/g, ' '), typeof v === 'number' ? fmtNum(v, 3) : String(v) + (prov ? '' : '')]);
    if (prov) rows[rows.length - 1].push(prov);
  }
  const props = Object.entries(be.props || {}).filter(([, v]) => v != null && typeof v !== 'object').slice(0, 8);
  const mine = review.findings.filter(f => (f.element_guids || []).includes(guid) && f.status !== 'not_applicable');
  pop.replaceChildren(
    el('div.row.between', {}, el('h4', { text: be.name || rec?.name || guid }), el('button.linkish', { text: '✕', on: { click: () => { viewer.setPicked([]); hidePopover(); } }, 'aria-label': 'Close' })),
    el('table', {}, ...rows.map(([k, v, prov]) => el('tr', {}, el('td', { text: k }), el('td', {}, String(v), prov ? el('span.prov.' + prov, { text: prov }) : null)))),
    props.length ? el('details', {}, el('summary', { text: `Properties (${props.length})` }), el('table', {}, ...props.map(([k, v]) => el('tr', {}, el('td', { text: k }), el('td', { text: String(v) }))))) : null,
    el('div.guid', { text: 'GlobalId ' + guid, title: 'Click to copy', style: { cursor: 'copy' }, on: { click: e => { navigator.clipboard?.writeText(guid); toast('GlobalId copied', guid, 'ok', 1800); } } }),
    el('div.row', { style: { marginTop: '8px', flexWrap: 'wrap' } },
      el('button.btn.small', { text: 'Hide', on: { click: () => { doAction('hideSel'); hidePopover(); } } }),
      el('button.btn.small', { text: 'Isolate', on: { click: () => { doAction('isolateSel'); hidePopover(); } } }),
      el('button.btn.small', { text: 'Zoom', on: { click: () => viewer.flyToGuids([guid]) } })),
    mine.length ? el('div', { style: { marginTop: '8px' } }, el('h4', { text: 'Findings on this element', style: { margin: '0 0 4px', color: 'var(--mut)', fontSize: '11px' } }),
      ...mine.slice(0, 6).map(f => el('button.el', { on: { click: () => review.select(f.id) } }, el('span.badge.' + f.status, { text: f.status === 'violation' ? 'viol' : f.status }), el('span.nm', { text: f.title_en || f.rule_id })))) : null);
  pop.hidden = false;
  const W = $('#view3d').clientWidth, H = $('#view3d').clientHeight;
  pop.style.left = Math.max(8, Math.min(W - 300, x + 16)) + 'px'; pop.style.top = Math.max(8, Math.min(H - pop.offsetHeight - 8, y + 10)) + 'px';
}

function doAction(a) {
  if (a === 'fit') { if (review.selected && viewer.focusState) viewer.flyToFinding(review.selected); else viewer.fit(); }
  else if (a === 'fitAll') viewer.fit();
  else if (a === 'hideSel') { if (!viewer.picked.size) return toast('Nothing picked', 'Click an element in the 3D view first (Shift-click to add more).', 'warn', 3000); viewer.hideSelected(); }
  else if (a === 'isolateSel') { if (!viewer.picked.size) return toast('Nothing picked', 'Click an element in the 3D view first.', 'warn', 3000); viewer.isolateSelected(); }
  else if (a === 'showAll') { viewer.showAll(); tools.syncSection(); }
}

// ================================================================================================ tabs
function setTab(t) {
  tab.cur = t;
  $('#tab3d').classList.toggle('active', t === '3d'); $('#tab2d').classList.toggle('active', t === '2d');
  $('#tab3d').setAttribute('aria-selected', t === '3d'); $('#tab2d').setAttribute('aria-selected', t === '2d');
  $('#view3d').hidden = t !== '3d'; $('#view2d').hidden = t !== '2d';
  if (t === '3d') { viewer.resize(); viewer.requestRender(); } else { drawing.fit(); drawing._apply(); }
}

// ================================================================================================ modal: article viewer, help
function openModal(title, body) { $('#modalTitle').textContent = title; $('#modalBody').replaceChildren(...[].concat(body)); $('#modalBack').hidden = false; }
function closeModal() { $('#modalBack').hidden = true; }

async function openArticle(n, para) {
  openModal(`Article ${n}`, el('div.muted', { text: 'Loading…' }));
  try {
    const a = await api.article(n);
    const nodes = [a.section ? el('div.muted.small', { text: a.section }) : null];
    for (const p of a.paragraphs || []) {
      const hit = String(p.no) === String(para);
      const revs = (p.revisions || []).map(r => el('span' + (r.type === 'added' ? '.rev-add' : '.rev-del'), { text: ' ' + r.text + ' ' }));
      nodes.push(el('div.para' + (hit ? '.hit' : ''), { dataset: { no: p.no } },
        el('b', { text: p.no ? `(${p.no}) ` : '' }), p.text || '', revs.length ? el('span.muted.small', {}, ' [revision: ', ...revs, ']') : null,
        p.items?.length ? el('ul', {}, ...p.items.map(it => el('li', {}, el('b', { text: `${it.key}) ` }), it.text, (it.revisions || []).length ? el('span.muted.small', {}, ' [', ...it.revisions.map(r => el('span' + (r.type === 'added' ? '.rev-add' : '.rev-del'), { text: ' ' + r.text + ' ' })), ']') : null))) : null));
    }
    openModal(`${a.label || 'Article ' + n} — ${a.title || ''}${a.page ? ` (p. ${a.page})` : ''}`, nodes.filter(Boolean));
    $('#modalBody .para.hit')?.scrollIntoView({ block: 'center' });
  } catch (e) { openModal(`Article ${n}`, el('div.hintbox', { text: 'Article text not available: ' + e.message })); }
}

function showHelp() {
  const rows = [['↑ ↓ / J K', 'previous / next finding'], ['A', 'accept violation'], ['W', 'waive'], ['C', 'mark compliant'], ['N', 'needs info'], ['(same key again)', 'clear the decision'], ['U', 'next undecided review'],
    ['F', 'fly to the selected finding (Shift+F: whole model)'], ['H / I / R', 'hide / isolate picked, reset (show all)'], ['Esc', 'close popover / deselect finding'], ['S', 'project settings'], ['1 – 6', 'top, front, back, left, right, iso view'], ['Click / Shift+click', 'pick element(s) in 3D'], ['Right-drag, wheel', 'pan, zoom (left-drag orbits)']];
  openModal('Keyboard shortcuts', el('table', { style: { borderCollapse: 'collapse' } }, ...rows.map(([k, v]) => el('tr', {}, el('td', { style: { padding: '3px 16px 3px 0' } }, ...k.split(' / ').map(x => el('kbd', { text: x }))), el('td', { text: v })))));
}

function onKey(e) {
  const t = e.target, typing = t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT') && !(t.type === 'checkbox' || t.type === 'range');
  if (e.key === 'Escape') {
    if (typing) { t.blur(); return; }
    if (!$('#modalBack').hidden) return closeModal();
    if (settings?.isOpen) return settings.close();
    if (!$('#popover').hidden) { viewer.setPicked([]); return hidePopover(); }
    if (viewer?.picked.size) return viewer.setPicked([]);
    return review?.deselect();
  }
  if (typing || e.ctrlKey || e.metaKey || e.altKey || $('#layout').hidden) return;
  const k = e.key.toLowerCase();
  const simple = {
    arrowdown: () => review.move(1), j: () => review.move(1), arrowup: () => review.move(-1), k: () => review.move(-1),
    a: () => review.decide('accepted_violation'), w: () => review.decide('waived'), c: () => review.decide('compliant'), n: () => review.decide('needs_info'),
    u: () => review.nextUndecided(), f: () => doAction(e.shiftKey ? 'fitAll' : 'fit'), h: () => doAction('hideSel'), i: () => doAction('isolateSel'), r: () => doAction('showAll'),
    s: () => settings.open(), '?': showHelp,
    1: () => viewer.setView('top'), 2: () => viewer.setView('front'), 3: () => viewer.setView('back'), 4: () => viewer.setView('left'), 5: () => viewer.setView('right'), 6: () => viewer.setView('iso'),
  };
  if (simple[k] && !(t.tagName === 'BUTTON' && (k === ' ' || k === 'enter'))) { e.preventDefault(); simple[k](); }
}

// ================================================================================================ go
initHome();
route();
