// 3D viewer: three.js scene, filtering (storeys / classes / section / x-ray), highlighting, dimensions, picking, fly-to.
// Data coordinates are Z-up (IFC world). The GLB is already Y-up: toViewer([x,y,z]) = [x, z, -y].
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

export const toViewer = p => new THREE.Vector3(p[0], p[2], -p[1]);
export const fromViewer = v => [v.x, -v.z, v.y];

export const CLASS_GROUPS = [
  { id: 'wall', label: 'Walls', color: '#d9d2c3', kinds: ['wall'] },
  { id: 'slab', label: 'Slabs', color: '#9aa3ad', kinds: ['slab'] },
  { id: 'roof', label: 'Roofs', color: '#c0674d', kinds: ['roof'] },
  { id: 'covering', label: 'Ceilings', color: '#e8e8e8', kinds: ['covering'] },
  { id: 'door', label: 'Doors', color: '#a77a4b', kinds: ['door'] },
  { id: 'window', label: 'Windows', color: '#7fc2ee', kinds: ['window'] },
  { id: 'stair', label: 'Stairs', color: '#b0b0b0', kinds: ['stair'] },
  { id: 'railing', label: 'Railings', color: '#6e7a8a', kinds: ['railing'] },
  { id: 'space', label: 'Spaces', color: '#5fd39a', kinds: ['space'] },
  { id: 'other', label: 'Other', color: '#c9a3e8', kinds: ['column', 'beam', 'other'] },
];
const KIND_TO_GROUP = {};
for (const g of CLASS_GROUPS) for (const k of g.kinds) KIND_TO_GROUP[k] = g.id;
const IFC_TO_KIND = {
  ifcwall: 'wall', ifcwallstandardcase: 'wall', ifccurtainwall: 'wall', ifcslab: 'slab', ifcroof: 'roof', ifccovering: 'covering',
  ifcdoor: 'door', ifcwindow: 'window', ifcstair: 'stair', ifcstairflight: 'stair', ifcramp: 'stair', ifcrampflight: 'stair',
  ifcrailing: 'railing', ifcspace: 'space', ifccolumn: 'column', ifcbeam: 'beam',
};
const groupOf = (kind, ifcClass) => KIND_TO_GROUP[kind] || KIND_TO_GROUP[IFC_TO_KIND[(ifcClass || '').toLowerCase()]] || 'other';

const COL = {
  off: new THREE.Color('#ff3b3b'), offEm: new THREE.Color('#6d0c0c'),
  ctx: new THREE.Color('#ffb21e'), ctxEm: new THREE.Color('#4d3300'),
  pick: new THREE.Color('#33c9ff'), pickEm: new THREE.Color('#06495f'),
  ghost: new THREE.Color('#7d93ad'),
};

export class Viewer {
  constructor({ canvas, container, labels, cube }) {
    this.canvas = canvas; this.container = container; this.cubeEl = cube;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.localClippingEnabled = true;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
    this.camera.position.set(14, 10, 16);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true; this.controls.dampingFactor = 0.12; this.controls.screenSpacePanning = true;
    this.controls.addEventListener('change', () => this.requestRender());
    this.labelRenderer = new CSS2DRenderer({ element: labels });
    labels.style.pointerEvents = 'none';

    this.scene.add(new THREE.HemisphereLight(0xe3edf9, 0x59636f, 1.25));
    this.sun = new THREE.DirectionalLight(0xffffff, 1.9); this.sun.position.set(30, 60, 40); this.scene.add(this.sun);
    const fill = new THREE.DirectionalLight(0xbcd2ff, 0.55); fill.position.set(-40, 20, -30); this.scene.add(fill);

    this.modelGroup = new THREE.Group(); this.scene.add(this.modelGroup);
    this.dimGroup = new THREE.Group(); this.dimGroup.renderOrder = 999; this.scene.add(this.dimGroup);
    this.helpers = new THREE.Group(); this.scene.add(this.helpers);
    this.clipPlanes = []; this.plane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);
    this.sectionHelper = null;

    this.records = new Map();     // guid -> record
    this.bm = null; this.bmEls = new Map(); this.storeys = [];
    this.variantCache = new Map();
    this.modelBox = new THREE.Box3(new THREE.Vector3(-5, 0, -5), new THREE.Vector3(5, 5, 5));
    // filter state
    this.classVisible = Object.fromEntries(CLASS_GROUPS.map(g => [g.id, g.id !== 'space']));
    this.base = { storey: null, xray: false };   // storey: {mode, idx}|null
    this.focusState = null;                      // {hl:Map, storey, xray, autoHide:Set, finding}
    this.hidden = new Set(); this.isolated = null; this.picked = new Set();
    this.opt = { edges: true, grid: true, autoHide: true };
    this.section = { on: false, y: 0 };
    this.onPick = () => {}; this.onChange = () => {};
    this.dirty = true; this.tween = null; this.edgeQueue = []; this.pickMeshes = [];

    this._ro = new ResizeObserver(() => this.resize());
    this._ro.observe(container);
    this._bindPointer();
    this._buildCube();
    this.resize();
    const loop = () => {
      this._raf = requestAnimationFrame(loop);
      if (this.tween) this._stepTween();
      const moved = this.controls.update();
      if (moved || this.dirty) this._render();
    };
    loop();
  }

  // ------------------------------------------------------------------------------------------------ plumbing
  requestRender() { this.dirty = true; }
  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.labelRenderer.setSize(w, h);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    for (const o of this.dimGroup.children) if (o.material?.resolution) o.material.resolution.set(w, h);
    this.requestRender();
  }
  _render() {
    this.dirty = false;
    this.renderer.render(this.scene, this.camera);
    this.labelRenderer.render(this.scene, this.camera);
    this._updateCube();
  }
  dispose() { cancelAnimationFrame(this._raf); this._ro.disconnect(); this.renderer.dispose(); }

  // ------------------------------------------------------------------------------------------------ loading
  setBuildingModel(bm) {
    this.bm = bm || null;
    this.storeys = ((bm && bm.storeys) || []).slice().sort((a, b) => (a.elevation ?? 0) - (b.elevation ?? 0));
    this.bmEls = new Map(((bm && bm.elements) || []).map(e => [e.guid, e]));
    if (this.records.size) { this._assignStoreys(); this.appearance(); }
  }
  element(guid) { return this.bmEls.get(guid) || null; }
  record(guid) { return this.records.get(guid) || null; }

  clearModel() {
    for (const rec of this.records.values()) for (const m of rec.meshes) m.geometry?.dispose?.();
    this.modelGroup.clear(); this.records.clear(); this.variantCache.clear(); this.edgeQueue.length = 0;
    this.clearFocus(true);
  }

  async loadGLB(url, { onProgress, keepCamera = false } = {}) {
    const resp = await fetch(url);
    if (!resp.ok) { const e = new Error(resp.status === 404 ? 'no 3D geometry for this project' : `GLB request failed (${resp.status})`); e.status = resp.status; throw e; }
    const total = +resp.headers.get('content-length') || 0;
    let buf;
    if (resp.body && total) {
      const rd = resp.body.getReader(); const chunks = []; let got = 0;
      for (;;) { const { done, value } = await rd.read(); if (done) break; chunks.push(value); got += value.length; onProgress?.(got / total); }
      const all = new Uint8Array(got); let o = 0; for (const c of chunks) { all.set(c, o); o += c.length; }
      buf = all.buffer;
    } else buf = await resp.arrayBuffer();
    onProgress?.(1);
    await new Promise(r => setTimeout(r, 0));
    const gltf = await new GLTFLoader().parseAsync(buf, '');
    const camState = keepCamera ? { p: this.camera.position.clone(), t: this.controls.target.clone() } : null;
    const prevFocus = this.focusState && this.focusState.finding;
    this.clearModel();
    this.modelGroup.add(gltf.scene);
    this._indexScene(gltf.scene);
    if (!this.records.size) throw new Error('the GLB contains no meshes');
    this._assignStoreys();
    this._computeBounds();
    this._buildHelpers();
    this._queueEdges();
    this.appearance();
    if (camState) { this.camera.position.copy(camState.p); this.controls.target.copy(camState.t); this.controls.update(); }
    else this.fit(false);
    this.requestRender(); this.onChange('model');
    return { prevFocus, count: this.records.size };
  }

  _indexScene(root) {
    root.updateMatrixWorld(true);
    const ownerOf = o => { for (let n = o; n && n !== root.parent; n = n.parent) if (n.userData?.guid) return n; return null; };
    root.traverse(o => {
      if (!o.isMesh) return;
      const own = ownerOf(o);
      const ud = own ? own.userData : {};
      const guid = ud.guid || o.name;
      let rec = this.records.get(guid);
      if (!rec) {
        rec = { guid, meshes: [], kind: ud.kind || null, ifcClass: ud.ifc_class || null, name: ud.name || o.name, glbStorey: ud.storey_id || null, group: 'other', storeyIdx: null, box: new THREE.Box3(), mode: 'normal', visible: true };
        rec.group = groupOf(rec.kind, rec.ifcClass);
        this.records.set(guid, rec);
      }
      rec.meshes.push(o);
      o.userData.guid = guid;
      const base = o.material;
      o.userData.base = base;
      this._prepBase(base, rec);
    });
    for (const rec of this.records.values()) for (const m of rec.meshes) rec.box.expandByObject(m);
  }

  _prepBase(m, rec) {
    if (m.userData.__prepped) return;
    m.userData.__prepped = true;
    m.side = THREE.DoubleSide;
    if ('metalness' in m) { m.metalness = Math.min(m.metalness ?? 0, 0.1); m.roughness = Math.max(m.roughness ?? 0.9, 0.7); }
    if (rec.group === 'space') { m.transparent = true; m.opacity = Math.min(m.opacity, 0.2); m.depthWrite = false; }
    else if (m.opacity < 0.98 || m.transparent) { m.transparent = true; m.depthWrite = false; m.opacity = Math.max(m.opacity, 0.12); }
    else { m.polygonOffset = true; m.polygonOffsetFactor = 1; m.polygonOffsetUnits = 1; }
    m.clippingPlanes = this.clipPlanes;
    m.userData.orig = { color: m.color ? m.color.clone() : null, opacity: m.opacity };
  }

  _assignStoreys() {
    const elev = this.storeys.map(s => s.elevation ?? 0);
    const idxOfId = new Map(this.storeys.map((s, i) => [s.id, i]));
    for (const rec of this.records.values()) {
      const be = this.bmEls.get(rec.guid);
      if (be && !rec.kind) { rec.kind = be.kind; rec.group = groupOf(be.kind, be.ifc_class); }
      let idx = null;
      const sid = (be && be.storey_id) || rec.glbStorey;
      if (sid != null && idxOfId.has(sid)) idx = idxOfId.get(sid);
      if (idx == null && elev.length) {
        const zc = rec.box.isEmpty() ? 0 : rec.box.min.y + 0.3; // data z == viewer y
        idx = 0; for (let i = 0; i < elev.length; i++) if (elev[i] <= zc) idx = i;
      }
      rec.storeyIdx = idx;
    }
  }

  _computeBounds() {
    this.modelBox.makeEmpty();
    for (const rec of this.records.values()) if (rec.group !== 'space' || this.records.size < 3) this.modelBox.union(rec.box);
    if (this.modelBox.isEmpty()) for (const rec of this.records.values()) this.modelBox.union(rec.box);
    const size = this.modelBox.getSize(new THREE.Vector3()), diag = size.length();
    this.camera.near = Math.max(diag / 3000, 0.02); this.camera.far = diag * 40; this.camera.updateProjectionMatrix();
    this.controls.maxDistance = diag * 8; this.controls.minDistance = 0.3;
    this.sun.position.set(diag, diag * 1.8, diag * 1.2);
  }

  _buildHelpers() {
    this.helpers.clear();
    const b = this.modelBox, size = b.getSize(new THREE.Vector3()), c = b.getCenter(new THREE.Vector3());
    const ext = Math.max(size.x, size.z, 6) * 2.2;
    const div = Math.round(ext / (ext > 80 ? 5 : 1));
    this.grid = new THREE.GridHelper(ext, div, 0x587089, 0x2c3a4a);
    this.grid.position.set(c.x, b.min.y - 0.02, c.z);
    this.grid.material.transparent = true; this.grid.material.opacity = 0.55; this.grid.material.depthWrite = false;
    this.grid.visible = this.opt.grid;
    this.helpers.add(this.grid);
    // axes at the SW corner so orientation errors are obvious: X red (east), Y green (north = -z in the viewer), Z blue (up)
    const o = new THREE.Vector3(b.min.x, b.min.y, b.max.z), L = Math.max(Math.min(size.x, size.z) * 0.18, 1.2);
    const axes = [[new THREE.Vector3(1, 0, 0), 0xff5a5a, 'X'], [new THREE.Vector3(0, 0, -1), 0x5aff7a, 'Y'], [new THREE.Vector3(0, 1, 0), 0x5a9cff, 'Z']];
    for (const [d, col, name] of axes) {
      const g = new THREE.BufferGeometry().setFromPoints([o, o.clone().addScaledVector(d, L)]);
      this.helpers.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: col })));
      const div = document.createElement('div'); div.textContent = name;
      div.style.cssText = `color:#${col.toString(16)};font:700 11px sans-serif;text-shadow:0 0 3px #000`;
      const lab = new CSS2DObject(div); lab.position.copy(o).addScaledVector(d, L * 1.12); this.helpers.add(lab);
    }
    // section plane visual
    const sg = new THREE.PlaneGeometry(1, 1); sg.rotateX(-Math.PI / 2);
    const sm = new THREE.MeshBasicMaterial({ color: 0x4aa3ff, transparent: true, opacity: 0.1, side: THREE.DoubleSide, depthWrite: false });
    this.sectionHelper = new THREE.Mesh(sg, sm); this.sectionHelper.scale.set(size.x * 1.15 + 1, 1, size.z * 1.15 + 1);
    this.sectionHelper.position.set(c.x, 0, c.z); this.sectionHelper.visible = false; this.sectionHelper.renderOrder = 5;
    const ol = new THREE.LineSegments(new THREE.EdgesGeometry(sg), new THREE.LineBasicMaterial({ color: 0x4aa3ff }));
    this.sectionHelper.add(ol);
    this.helpers.add(this.sectionHelper);
    this.setSection(this.section.on, this.section.on ? this.section.y : b.max.y);
  }

  // ------------------------------------------------------------------------------------------------ edge lines (time-sliced)
  _queueEdges() {
    const geoCache = new Map();
    this.edgeMat = new THREE.LineBasicMaterial({ color: 0x0c1218, transparent: true, opacity: 0.55, clippingPlanes: this.clipPlanes });
    this.edgeQueue = [];
    for (const rec of this.records.values()) {
      if (rec.group === 'space') continue;
      for (const m of rec.meshes) {
        const base = m.userData.base;
        if (base.transparent && base.opacity < 0.9) continue;
        this.edgeQueue.push({ m, geoCache });
      }
    }
    this._pumpEdges();
  }
  _pumpEdges() {
    const t0 = performance.now();
    while (this.edgeQueue.length && performance.now() - t0 < 12) {
      const { m, geoCache } = this.edgeQueue.pop();
      if (!m.parent) continue;
      let eg = geoCache.get(m.geometry.uuid);
      if (!eg) { eg = new THREE.EdgesGeometry(m.geometry, 35); geoCache.set(m.geometry.uuid, eg); }
      const ls = new THREE.LineSegments(eg, this.edgeMat);
      ls.userData.isEdge = true; ls.raycast = () => {};
      ls.visible = m.visible && this.opt.edges && m.userData.mode !== 'ghost';
      m.add(ls); m.userData.edges = ls;
    }
    this.requestRender();
    if (this.edgeQueue.length) setTimeout(() => this._pumpEdges(), 16);
  }

  // ------------------------------------------------------------------------------------------------ appearance
  get cur() { return this.focusState || this.base; }

  _variant(base, mode, rec) {
    let slot = this.variantCache.get(base);
    if (!slot) this.variantCache.set(base, slot = {});
    const key = mode + (rec.group === 'space' ? 's' : '');
    if (slot[key]) return slot[key];
    const m = base.clone();
    m.clippingPlanes = this.clipPlanes; m.side = THREE.DoubleSide;
    if (mode === 'ghost') {
      m.transparent = true; m.opacity = 0.07; m.depthWrite = false; m.polygonOffset = false;
      if (m.color) m.color.lerp(COL.ghost, 0.7);
    } else if (mode === 'off' || mode === 'ctx' || mode === 'pick') {
      const [c, e] = mode === 'off' ? [COL.off, COL.offEm] : mode === 'ctx' ? [COL.ctx, COL.ctxEm] : [COL.pick, COL.pickEm];
      if (m.color) m.color.copy(c);
      if (m.emissive) m.emissive.copy(e);
      if (rec.group === 'space') { m.transparent = true; m.opacity = mode === 'ctx' ? 0.28 : 0.5; m.depthWrite = false; }
      else if (base.transparent) { m.transparent = true; m.opacity = 0.6; m.depthWrite = false; }
      else { m.transparent = false; m.opacity = 1; m.depthWrite = true; }
    }
    slot[key] = m;
    return m;
  }

  storeyVisible(rec) {
    const s = this.cur.storey;
    if (!s || !this.storeys.length) return true;
    const i = rec.storeyIdx;
    if (i == null) return false;
    return s.mode === 'single' ? i === s.idx : s.mode === 'below' ? i <= s.idx : i >= s.idx;
  }

  appearance() {
    const hl = this.focusState && this.focusState.hl;
    const xray = this.cur.xray;
    const picks = [];
    for (const rec of this.records.values()) {
      const role = hl && hl.get(rec.guid);
      let vis = this.classVisible[rec.group] && this.storeyVisible(rec) && !this.hidden.has(rec.guid);
      if (this.isolated && !this.isolated.has(rec.guid)) vis = false;
      if (vis && this.focusState && this.opt.autoHide && this.focusState.autoHide.has(rec.guid)) vis = false;
      let mode = 'normal';
      if (role) { vis = !this.hidden.has(rec.guid); mode = role === 'context' ? 'ctx' : 'off'; }
      else if (this.picked.has(rec.guid)) { mode = 'pick'; if (this.isolated?.has(rec.guid)) vis = true; }
      else if (xray) mode = 'ghost';
      rec.mode = mode; rec.visible = !!vis;
      for (const m of rec.meshes) {
        m.visible = !!vis;
        m.material = mode === 'normal' ? m.userData.base : this._variant(m.userData.base, mode, rec);
        m.userData.mode = mode;
        if (m.userData.edges) m.userData.edges.visible = vis && this.opt.edges && mode !== 'ghost';
        if (vis && mode !== 'ghost') picks.push(m);
      }
    }
    this.pickMeshes = picks;
    this.requestRender();
    this.onChange('appearance');
  }

  // ---- state setters used by the UI
  setClassVisible(id, on) { this.classVisible[id] = on; this.appearance(); }
  classCounts() { const c = {}; for (const r of this.records.values()) c[r.group] = (c[r.group] || 0) + 1; return c; }
  setStorey(storey) { this.cur.storey = storey; this.appearance(); }
  setXray(on) { this.cur.xray = on; this.appearance(); }
  setEdges(on) { this.opt.edges = on; this.appearance(); }
  setGrid(on) { this.opt.grid = on; if (this.grid) this.grid.visible = on; this.requestRender(); }
  setAutoHide(on) { this.opt.autoHide = on; this.appearance(); }
  sectionRange() { return [this.modelBox.min.y, this.modelBox.max.y]; }
  setSection(on, y) {
    this.section = { on, y };
    this.clipPlanes.length = 0;
    if (on) { this.plane.constant = y; this.clipPlanes.push(this.plane); }
    if (this.sectionHelper) { this.sectionHelper.visible = on; this.sectionHelper.position.y = y; }
    this.requestRender(); this.onChange('section');
  }
  hideSelected() { for (const g of this.picked) this.hidden.add(g); this.picked.clear(); this.appearance(); }
  isolateSelected() { if (this.picked.size) { this.isolated = new Set(this.picked); this.picked.clear(); this.appearance(); } }
  showAll() {
    this.hidden.clear(); this.isolated = null; this.picked.clear();
    for (const g of CLASS_GROUPS) this.classVisible[g.id] = g.id !== 'space';
    this.cur.storey = null; this.cur.xray = false;
    this.setSection(false, this.modelBox.max.y);
    this.appearance();
  }
  setPicked(guids) { this.picked = new Set(guids); this.appearance(); }

  // ------------------------------------------------------------------------------------------------ review focus
  focus(finding, { fly = true } = {}) {
    const hl = new Map();
    const list = (finding.highlight && finding.highlight.length) ? finding.highlight : (finding.element_guids || []).map(g => ({ guid: g, role: 'offending' }));
    for (const h of list) {
      const role = h.role === 'context' ? 'context' : 'offending';
      if (this.records.has(h.guid)) { if (role === 'offending' || !hl.has(h.guid)) hl.set(h.guid, role); continue; }
      // container elements (e.g. IfcStair) have no mesh of their own: use same-kind meshes inside their bbox (e.g. flights)
      const be = this.bmEls.get(h.guid);
      if (!be || !be.bbox) continue;
      const bb = new THREE.Box3(toViewer(be.bbox.min), toViewer(be.bbox.max));
      bb.min.set(Math.min(bb.min.x, bb.max.x), Math.min(bb.min.y, bb.max.y), Math.min(bb.min.z, bb.max.z)); bb.max.set(Math.max(bb.min.x, bb.max.x), Math.max(bb.min.y, bb.max.y), Math.max(bb.min.z, bb.max.z));
      const bb2 = new THREE.Box3(toViewer(be.bbox.min), toViewer(be.bbox.max)); const lo = bb2.min.clone().min(bb2.max), hi = bb2.min.clone().max(bb2.max);
      const box = new THREE.Box3(lo.subScalar(0.05), hi.addScalar(0.05));
      for (const r of this.records.values()) if ((r.group === groupOf(be.kind, be.ifc_class) || (r.ifcClass && be.ifc_class && r.ifcClass.startsWith(be.ifc_class))) && box.containsBox(r.box) && !hl.has(r.guid)) hl.set(r.guid, role);
    }
    const missing = hl.size ? 0 : list.length;
    const offenders = [...hl].filter(([, r]) => r === 'offending').map(([g]) => this.records.get(g));
    const subject = offenders.length ? offenders : [...hl.keys()].map(g => this.records.get(g));
    let storey = null;
    if (this.storeys.length) {
      let idx = finding.storey_id ? this.storeys.findIndex(s => s.id === finding.storey_id) : -1;
      if (idx < 0 && subject.length) idx = Math.min(...subject.map(r => r.storeyIdx ?? 99));
      if (idx >= 0 && idx < 99) storey = { mode: 'single', idx };
    }
    // auto-hide ceilings / roof / slabs above the offender
    const autoHide = new Set();
    if (subject.length) {
      const top = Math.max(...subject.map(r => r.box.max.y));
      for (const rec of this.records.values()) {
        if (hl.has(rec.guid)) continue;
        if (['roof', 'covering', 'slab'].includes(rec.group) && rec.box.min.y >= top - 0.08) autoHide.add(rec.guid);
      }
    }
    const prev = this.focusState;
    this.focusState = { hl, storey, xray: true, autoHide, finding, missing, prevPick: prev ? prev.prevPick : new Set(this.picked) };
    this.picked.clear();
    // spaces are shown as highlighted elements only when they are part of the finding
    this.setDims(finding);
    this.appearance();
    if (fly) this.flyToFinding(finding, hl);
    return { highlighted: hl.size, missing, storey: storey ? this.storeys[storey.idx] : null };
  }
  clearFocus(silent = false) {
    if (!this.focusState) return;
    this.focusState = null;
    this.clearDims();
    if (!silent) this.appearance();
  }
  focusBox(finding, hl) {
    const box = new THREE.Box3();
    for (const [g, role] of hl || []) if (role === 'offending') box.union(this.records.get(g).box);
    if (box.isEmpty()) for (const g of (hl || new Map()).keys()) box.union(this.records.get(g).box);
    for (const d of finding.dimensions || []) { if (d.p1) box.expandByPoint(toViewer(d.p1)); if (d.p2) box.expandByPoint(toViewer(d.p2)); }
    if (box.isEmpty() && finding.anchor) { const a = toViewer(finding.anchor); box.expandByPoint(a); }
    return box;
  }
  flyToFinding(finding, hl) {
    const box = this.focusBox(finding, hl || (this.focusState && this.focusState.hl));
    if (box.isEmpty()) return this.fit(true);
    this.flyToBox(box, { minRadius: 1.4 });
  }
  flyToGuids(guids) {
    const box = new THREE.Box3();
    for (const g of guids) { const r = this.records.get(g); if (r) box.union(r.box); }
    if (!box.isEmpty()) this.flyToBox(box, { minRadius: 1.2 });
  }

  // ------------------------------------------------------------------------------------------------ dimensions
  clearDims() {
    for (const o of [...this.dimGroup.children]) { o.geometry?.dispose?.(); o.material?.dispose?.(); }
    this.dimGroup.clear(); this.requestRender();
  }
  setDims(finding) {
    this.clearDims();
    const dims = finding.dimensions || [];
    const w = this.container.clientWidth, h = this.container.clientHeight;
    const color = finding.status === 'violation' ? 0xffe14a : 0x59e3ff;
    for (const d of dims) {
      if (!d.p1 || !d.p2) continue;
      const a = toViewer(d.p1), b = toViewer(d.p2), dir = b.clone().sub(a), len = dir.length();
      if (len < 1e-6) continue;
      dir.normalize();
      let perp = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
      if (perp.lengthSq() < 1e-4) perp = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(1, 0, 0));
      perp.normalize();
      const tk = Math.min(Math.max(len * 0.06, 0.07), 0.3);
      const pos = [a, b, a.clone().addScaledVector(perp, -tk), a.clone().addScaledVector(perp, tk), b.clone().addScaledVector(perp, -tk), b.clone().addScaledVector(perp, tk)];
      const g = new LineSegmentsGeometry(); g.setPositions(pos.flatMap(p => [p.x, p.y, p.z]));
      const mat = new LineMaterial({ color, linewidth: 3.2, transparent: true, depthTest: false, resolution: new THREE.Vector2(w, h) });
      const line = new LineSegments2(g, mat); line.renderOrder = 999; line.frustumCulled = false;
      this.dimGroup.add(line);
      if (d.label) {
        const div = document.createElement('div'); div.className = 'dim-label' + (finding.status === 'violation' ? ' vio' : ''); div.textContent = d.label;
        const lab = new CSS2DObject(div); lab.position.copy(a).add(b).multiplyScalar(0.5); this.dimGroup.add(lab);
      }
    }
    const hasOffender = this.focusState && [...this.focusState.hl.values()].includes('offending');
    if (!hasOffender && !dims.length && finding.anchor) {
      const div = document.createElement('div'); div.className = 'pin-label'; div.textContent = '●  ' + (finding.rule_id || '');
      const lab = new CSS2DObject(div); lab.position.copy(toViewer(finding.anchor)); this.dimGroup.add(lab);
    }
    this.requestRender();
  }

  // ------------------------------------------------------------------------------------------------ camera
  fit(animate = true) {
    const box = new THREE.Box3();
    for (const r of this.records.values()) if (r.visible && r.group !== 'space') box.union(r.box);
    if (box.isEmpty()) box.copy(this.modelBox);
    this.flyToBox(box, { animate, minRadius: 1 });
  }
  _viewDir() {
    const d = this.camera.position.clone().sub(this.controls.target);
    if (d.lengthSq() < 1e-6) d.set(1, 0.8, 1);
    d.normalize(); if (d.y < 0.3) { d.y = 0.5; d.normalize(); }
    return d;
  }
  flyToBox(box, { animate = true, minRadius = 1, dir } = {}) {
    const sph = box.getBoundingSphere(new THREE.Sphere());
    const r = Math.max(sph.radius, minRadius);
    const vfov = THREE.MathUtils.degToRad(this.camera.fov), hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect);
    const dist = (r / Math.sin(Math.min(vfov, hfov) / 2)) * 1.12;
    const d = (dir || this._viewDir()).clone().normalize();
    this._flyTo(sph.center.clone(), sph.center.clone().addScaledVector(d, dist), animate);
  }
  setView(name) {
    const dirs = { top: [0, 1, 0.0008], front: [0, 0.0, 1], back: [0, 0, -1], left: [-1, 0, 0], right: [1, 0, 0], iso: [1, 0.85, 1.1], bottom: [0, -1, 0.0008] };
    const v = dirs[name]; if (!v) return;
    const box = new THREE.Box3();
    for (const r of this.records.values()) if (r.visible && r.group !== 'space') box.union(r.box);
    if (box.isEmpty()) box.copy(this.modelBox);
    this.flyToBox(box, { dir: new THREE.Vector3(...v) });
  }
  _flyTo(target, pos, animate) {
    if (!animate) { this.controls.target.copy(target); this.camera.position.copy(pos); this.controls.update(); this.requestRender(); return; }
    this.tween = { t0: performance.now(), dur: 750, fromT: this.controls.target.clone(), fromP: this.camera.position.clone(), toT: target, toP: pos };
  }
  _stepTween() {
    const tw = this.tween, k = Math.min((performance.now() - tw.t0) / tw.dur, 1), e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    // interpolate in spherical offset space so the camera swings instead of cutting through the model
    const c = tw.fromT.clone().lerp(tw.toT, e);
    const o0 = tw.fromP.clone().sub(tw.fromT), o1 = tw.toP.clone().sub(tw.toT);
    const s0 = new THREE.Spherical().setFromVector3(o0), s1 = new THREE.Spherical().setFromVector3(o1);
    let dth = s1.theta - s0.theta; if (dth > Math.PI) dth -= 2 * Math.PI; if (dth < -Math.PI) dth += 2 * Math.PI;
    const s = new THREE.Spherical(s0.radius + (s1.radius - s0.radius) * e, s0.phi + (s1.phi - s0.phi) * e, s0.theta + dth * e);
    this.controls.target.copy(c); this.camera.position.copy(c).add(new THREE.Vector3().setFromSpherical(s));
    this.camera.lookAt(c); this.requestRender();
    if (k >= 1) this.tween = null;
  }

  // ------------------------------------------------------------------------------------------------ picking
  _bindPointer() {
    let down = null;
    this.canvas.addEventListener('pointerdown', e => { down = { x: e.clientX, y: e.clientY, t: performance.now() }; this.tween = null; });
    this.canvas.addEventListener('pointerup', e => {
      if (!down) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      const d = down; down = null;
      if (moved > 5 || e.button !== 0 || performance.now() - d.t > 600) return;
      const rect = this.canvas.getBoundingClientRect();
      const guid = this.pickAt(e.clientX - rect.left, e.clientY - rect.top);
      this.onPick(guid, { x: e.clientX - rect.left, y: e.clientY - rect.top, additive: e.shiftKey || e.ctrlKey || e.metaKey });
    });
  }
  pickAt(px, py) {
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2((px / rect.width) * 2 - 1, -(py / rect.height) * 2 + 1);
    const rc = new THREE.Raycaster(); rc.setFromCamera(ndc, this.camera);
    const hits = rc.intersectObjects(this.pickMeshes, false);
    for (const h of hits) {
      if (this.section.on && h.point.y > this.section.y) continue;
      return h.object.userData.guid;
    }
    return null;
  }
  screenPos(guid) {
    const r = this.records.get(guid); if (!r) return null;
    const c = r.box.getCenter(new THREE.Vector3()).project(this.camera);
    return { x: (c.x + 1) / 2 * this.container.clientWidth, y: (1 - c.y) / 2 * this.container.clientHeight };
  }

  // ------------------------------------------------------------------------------------------------ view cube
  _buildCube() {
    const s = 23, faces = [
      ['front', `translateZ(${s}px)`], ['back', `rotateY(180deg) translateZ(${s}px)`], ['right', `rotateY(90deg) translateZ(${s}px)`],
      ['left', `rotateY(-90deg) translateZ(${s}px)`], ['top', `rotateX(90deg) translateZ(${s}px)`], ['bottom', `rotateX(-90deg) translateZ(${s}px)`],
    ];
    this.cubeEl.innerHTML = '';
    for (const [name, tf] of faces) {
      const d = document.createElement('div'); d.textContent = name.toUpperCase(); d.style.transform = tf; d.dataset.view = name;
      d.title = `${name} view`; d.addEventListener('click', () => this.setView(name));
      this.cubeEl.append(d);
    }
  }
  _updateCube() {
    const e = this.camera.matrixWorldInverse.elements, s = [1, -1, 1], m = new Array(16);
    for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) m[c * 4 + r] = (r < 3 && c < 3) ? e[c * 4 + r] * s[r] * s[c] : (r === c ? 1 : 0);
    this.cubeEl.style.transform = `matrix3d(${m.join(',')})`;
  }
}
