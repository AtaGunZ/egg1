// Left "View" panel + bottom toolbar: storeys, section cut, classes, display toggles. Binds the DOM to the Viewer.
import { CLASS_GROUPS } from './viewer.js';
import { $, $$, el, fmtNum } from './util.js';

export function initTools(viewer, hooks = {}) {
  const storeyList = $('#storeyList'), classList = $('#classList');
  let mode = 'single';

  // ---- storey mode segmented control
  $$('#storeyMode button').forEach(b => b.addEventListener('click', () => {
    mode = b.dataset.m;
    $$('#storeyMode button').forEach(x => x.classList.toggle('on', x === b));
    const s = viewer.cur.storey;
    if (s) viewer.setStorey({ mode, idx: s.idx });
  }));

  function buildStoreys() {
    storeyList.replaceChildren();
    const counts = {};
    for (const r of viewer.records.values()) counts[r.storeyIdx] = (counts[r.storeyIdx] || 0) + 1;
    const all = el('button.schip', { dataset: { idx: '' }, on: { click: () => viewer.setStorey(null) } }, el('span', { text: 'All storeys' }), el('small', { text: String(viewer.records.size) }));
    storeyList.append(all);
    for (let i = viewer.storeys.length - 1; i >= 0; i--) {
      const s = viewer.storeys[i];
      storeyList.append(el('button.schip', {
        dataset: { idx: String(i) }, title: `Elevation ${fmtNum(s.elevation)} m`,
        on: { click: () => { const cur = viewer.cur.storey; viewer.setStorey(cur && cur.idx === i && cur.mode === mode ? null : { mode, idx: i }); } },
      }, el('span', { text: s.name || `Level ${i}` }), el('small', { text: `${fmtNum(s.elevation, 2)} m · ${counts[i] || 0}` })));
    }
  }

  function buildClasses() {
    classList.replaceChildren();
    const counts = viewer.classCounts();
    for (const g of CLASS_GROUPS) {
      if (!counts[g.id]) continue;
      const cb = el('input', { type: 'checkbox', checked: viewer.classVisible[g.id] || null, dataset: { g: g.id } });
      cb.checked = viewer.classVisible[g.id];
      cb.addEventListener('change', () => viewer.setClassVisible(g.id, cb.checked));
      classList.append(el('label', { title: `Show/hide ${g.label.toLowerCase()}` }, cb, el('span.sw', { style: { background: g.color } }), g.label, el('span.n', { text: String(counts[g.id]) })));
    }
  }

  // ---- section
  const secOn = $('#secOn'), secSlider = $('#secSlider'), secVal = $('#secVal');
  const secY = () => { const [a, b] = viewer.sectionRange(); return a + (b - a) * (+secSlider.value); };
  function applySection() {
    secSlider.disabled = !secOn.checked;
    const y = secY();
    secVal.textContent = secOn.checked ? `cut at z = ${fmtNum(y, 2)} m` : 'off';
    viewer.setSection(secOn.checked, y);
  }
  secOn.addEventListener('change', applySection);
  secSlider.addEventListener('input', applySection);
  $('#secPlan').addEventListener('click', () => {
    const st = viewer.cur.storey ? viewer.storeys[viewer.cur.storey.idx] : viewer.storeys[0];
    const [a, b] = viewer.sectionRange();
    const y = Math.min(Math.max((st ? st.elevation : a) + 1.2, a), b);
    secSlider.value = (y - a) / ((b - a) || 1); secOn.checked = true; applySection();
    viewer.setView('top');
  });

  // ---- display
  const optXray = $('#optXray');
  optXray.addEventListener('change', () => viewer.setXray(optXray.checked));
  $('#optEdges').addEventListener('change', e => viewer.setEdges(e.target.checked));
  $('#optGrid').addEventListener('change', e => viewer.setGrid(e.target.checked));
  $('#optAutoHide').addEventListener('change', e => viewer.setAutoHide(e.target.checked));

  // ---- collapse
  $('#toolsCollapse').addEventListener('click', () => {
    const body = $('#toolsBody'); body.hidden = !body.hidden;
    $('#toolsCollapse').textContent = body.hidden ? '+' : '–';
  });

  // ---- bottom toolbar
  $$('#vbar [data-view]').forEach(b => b.addEventListener('click', () => viewer.setView(b.dataset.view)));
  $$('#vbar [data-act]').forEach(b => b.addEventListener('click', () => hooks.action?.(b.dataset.act)));

  function syncSection() {
    const [a, b] = viewer.sectionRange();
    if (!viewer.section.on) { secSlider.value = 1; }
    else secSlider.value = (viewer.section.y - a) / ((b - a) || 1);
    secOn.checked = viewer.section.on; secSlider.disabled = !secOn.checked;
    secVal.textContent = secOn.checked ? `cut at z = ${fmtNum(viewer.section.y, 2)} m` : 'off';
  }

  function sync() {
    const s = viewer.cur.storey;
    $$('#storeyList .schip').forEach(b => {
      const idx = b.dataset.idx === '' ? null : +b.dataset.idx;
      const on = s ? idx === s.idx : idx === null;
      const inside = s && idx != null && (s.mode === 'single' ? idx === s.idx : s.mode === 'below' ? idx <= s.idx : idx >= s.idx);
      b.classList.toggle('on', !!on); b.classList.toggle('in', !!inside); b.classList.toggle('out', !!s && idx != null && !inside);
    });
    if (s) { mode = s.mode; $$('#storeyMode button').forEach(x => x.classList.toggle('on', x.dataset.m === mode)); }
    optXray.checked = !!viewer.cur.xray;
    $$('#classList input').forEach(cb => { cb.checked = viewer.classVisible[cb.dataset.g]; });
  }

  return {
    rebuild() { buildStoreys(); buildClasses(); syncSection(); sync(); },
    sync, syncSection,
  };
}
