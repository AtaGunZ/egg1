// DWG -> compact JSON bridge using LibreDwg WASM (@mlightcad/libredwg-web).
// usage: node tools/drawing/dwg_bridge.mjs <in.dwg> <out.json>
// Output schema (bridge v1):
//  {bridge_version, dwg_version, header:{INSUNITS,EXTMIN,EXTMAX,MEASUREMENT,LUNITS,DIMSCALE,...},
//   layers:[{name,color,frozen,off,locked}], blocks:{name:{base:[x,y,z],entities:[...]}}, modelspace:[...]}
// Entities are the libredwg objects with noise removed and points compacted to [x,y(,z)] arrays.
import { LibreDwg, Dwg_File_Type } from '@mlightcad/libredwg-web';
import fs from 'fs';

const [,, inFile, outFile] = process.argv;
if (!inFile || !outFile) { console.error('usage: dwg_bridge.mjs in.dwg out.json'); process.exit(2); }

const DROP = new Set(['xdata','handle','ownerDictionaryHardId','ownerBlockRecordSoftId','ownerHandle','colorName','lineType',
  'lineweight','lineTypeScale','isVisible','transparency','transparencyType','extrusionDirection','subclassMarker',
  'version','textLineSpacingStyle','textLineSpacingFactor','byBlockColor','offsetFromBlock','offsetFromAnnotation',
  'horizontalDirection','knotTolerance','controlTolerance','fitTolerance','startTangent','endTangent','knots',
  'isHooklineSameDirection','isHooklineExists','leaderCreationFlag','isArrowheadEnabled','isSpline','pixel_size']);
const KEEP_EXTRUSION = new Set(['CIRCLE','ARC','LWPOLYLINE','INSERT','TEXT','MTEXT','ELLIPSE','HATCH']);

function rnd(v) { return Math.round(v * 1e5) / 1e5; }
function compact(v, key) {
  if (typeof v === 'bigint') return v.toString();
  if (typeof v === 'number') return Number.isInteger(v) ? v : rnd(v);
  if (Array.isArray(v)) return v.map((x) => compact(x, key));
  if (v && typeof v === 'object') {
    const ks = Object.keys(v);
    if (ks.length && ks.every((k) => k === 'x' || k === 'y' || k === 'z') && 'x' in v && 'y' in v) {
      return 'z' in v ? [rnd(v.x), rnd(v.y), rnd(v.z)] : [rnd(v.x), rnd(v.y)];
    }
    if ('x' in v && 'y' in v && ('bulge' in v || 'id' in v) && ks.length <= 8) {
      return [rnd(v.x), rnd(v.y), rnd(v.bulge || 0)];
    }
    const o = {};
    for (const k of ks) { if (DROP.has(k)) continue; o[k] = compact(v[k], k); }
    return o;
  }
  return v;
}
function ent(e) {
  const o = {};
  for (const k of Object.keys(e)) {
    if (DROP.has(k)) {
      if (k === 'extrusionDirection' && KEEP_EXTRUSION.has(e.type) && e[k] && Math.abs(e[k].z) < 0.999999) o.ext = compact(e[k]);
      continue;
    }
    o[k] = compact(e[k], k);
  }
  return o;
}

const lib = await LibreDwg.create();
const buf = fs.readFileSync(inFile);
const h = lib.dwg_read_data(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength), Dwg_File_Type.DWG);
if (!h) { console.error('dwg_read_data failed'); process.exit(3); }
const db = lib.convert(h);

const H = db.header || {};
const header = {};
for (const k of ['INSUNITS','MEASUREMENT','LUNITS','LUPREC','DIMSCALE','DIMLFAC','DIMTXT','DIMDEC','DIMLUNIT','ANGBASE','ANGDIR','ACADVER','ELEVATION','LTSCALE','TEXTSIZE','DWGCODEPAGE','DIMSTYLE'])
  if (k in H) header[k] = compact(H[k]);
for (const k of ['EXTMIN','EXTMAX','LIMMIN','LIMMAX','INSBASE']) if (k in H) header[k] = compact(H[k]);

const layers = (db.tables.LAYER?.entries || []).map((l) => ({
  name: l.name, color: l.colorIndex, frozen: !!l.frozen, off: !!l.off, locked: !!l.locked, lineType: l.lineType }));

const blocks = {};
let modelspace = [];
for (const b of db.tables.BLOCK_RECORD.entries) {
  const list = (b.entities || []).map(ent);
  if (b.name === '*Model_Space') modelspace = list;
  else if (b.name.startsWith('*Paper_Space')) { /* ignore paper space */ }
  else if (list.length || !b.name.startsWith('*')) blocks[b.name] = { base: compact(b.basePoint), entities: list };
}
let dwgVersion = null;
try { dwgVersion = String.fromCharCode(...buf.subarray(0, 6)); } catch (e) {}
const out = { bridge_version: 1, dwg_version: dwgVersion, header, layers, blocks, modelspace };
fs.writeFileSync(outFile, JSON.stringify(out));
lib.dwg_free(h);
console.error(`ok entities(modelspace)=${modelspace.length} blocks=${Object.keys(blocks).length} layers=${layers.length}`);
