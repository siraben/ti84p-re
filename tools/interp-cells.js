#!/usr/bin/env node
// Data-driven cell resolver for the page-0x39 MathPrint records: read a handler
// record from web/mathprint/layout.json and resolve each (D,E) cell to a
// concrete glyph / token-name / marker per tools/cell-glyph-spec.md (decoded
// from ROM). This is the cell-resolution half of the record-walking interpreter
// (task 3): no guessing — the dispatch is exactly eqdisp_emit_glyph (39:4E8E)
// and eqdisp_map_token_glyph (39:4F1A).
//
// Usage: node tools/interp-cells.js [classHex]   (default 08 = fnInt/nDeriv row)

const fs = require('fs');
const path = require('path');
const root = path.dirname(__dirname);
const layout = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'layout.json')));

// Resolve one cell (d,e) -> {kind, ...}. Mirrors 39:4E8E dispatch + 39:4F1A map.
function resolveCell(d, e) {
  if (d === 0x1F) return { kind: 'marker', what: 'cursor/answer-area (no draw)' };
  if (d === 0x82) return { kind: 'colGlyph', index: e - 0x3E };
  // 39:4F1A direct glyph cases
  if (d === 0xFC && e >= 0x3C && e <= 0x40) return { kind: 'glyph', code: (e - 0x3C) + 5 };
  if (d === 0xFE && e >= 0x7D && e <= 0x81) return { kind: 'glyph', code: e - 0x7D };
  if (e === 0x42 && d < 0x0A) return { kind: 'glyph', code: d };
  if (d === 0xFF) return { kind: 'marker', what: 'terminator' };
  // otherwise: a token whose NAME string is drawn (00xx etc.) or an FE/FC/FB
  // family display byte that expands to a 2-byte token (see spec §3)
  if (d === 0x00) return { kind: 'token', tok: e };
  if (d === 0xFB || d === 0xFC || d === 0xFE) return { kind: 'familyToken', d, e };
  return { kind: 'token', tok: (d << 8) | e };
}

function fmt(d, e) {
  const r = resolveCell(d, e);
  const hex = `${d.toString(16).padStart(2, '0')}${e.toString(16).padStart(2, '0')}`;
  if (r.kind === 'glyph') return `${hex} →glyph 0x${r.code.toString(16)}`;
  if (r.kind === 'colGlyph') return `${hex} →col-glyph #${r.index}`;
  if (r.kind === 'marker') return `${hex} [${r.what}]`;
  if (r.kind === 'token') return `${hex} →token 0x${r.tok.toString(16)}`;
  if (r.kind === 'familyToken') return `${hex} →family-token (${d.toString(16)})`;
  return hex;
}

function dumpClass(cls) {
  const c = layout.classes.find(x => x.cls === cls);
  if (!c || !('rows' in c)) { console.log(`class ${cls.toString(16)}: no record`); return; }
  console.log(`class 0x${cls.toString(16)} @ 0x${c.ptr.toString(16)}  rows=${c.rows}`);
  c.items.forEach((it, i) => {
    console.log(`  row ${i} action=0x${it.action.toString(16)} count=${it.count}`);
    console.log('    ' + it.cells.map(([d, e]) => fmt(d, e)).join('  '));
  });
}

if (require.main === module) {
  const cls = parseInt(process.argv[2] || '08', 16);
  dumpClass(cls);
}
module.exports = { resolveCell };
