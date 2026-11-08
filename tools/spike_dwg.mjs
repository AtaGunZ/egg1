import { LibreDwg, Dwg_File_Type } from '@mlightcad/libredwg-web';
import fs from 'fs';
const lib = await LibreDwg.create();
for (const f of process.argv.slice(2)) {
  const buf = fs.readFileSync(f);
  const h = lib.dwg_read_data(buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength), Dwg_File_Type.DWG);
  const db = lib.convert(h);
  const types = {}; for (const e of db.entities) types[e.type]=(types[e.type]||0)+1;
  console.log(f, 'entities', db.entities.length, 'layers', db.tables.LAYER.entries.length);
  console.log(JSON.stringify(types));
  console.log(db.tables.LAYER.entries.map(l=>l.name).slice(0,60).join(' | '));
  lib.dwg_free(h);
}
