#!/usr/bin/env node
// First-stage classifier for cells in the extracted page-0x39 records. Direct
// glyphs and markers are resolved; string/control families remain explicit for
// a later interpreter. See tools/cell-glyph-spec.md and token-name-spec.md.
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
  if (d === 0xFF) return { kind: 'marker', what: 'terminator' };
  if (e === 0x55) return { kind: 'specialAction', d, e };
  if (d === 0xFB && e === 0xC8)
    return { kind: 'runtimeConditional', d, e, condition: 'bit 0,H' };
  if (d === 0xFB && [0xCA, 0xCB, 0xD6, 0xD7, 0xD8].includes(e))
    return { kind: 'inlineString', d, e };
  // 39:4F1A direct glyph cases
  if (d === 0xFC && e >= 0x3C && e <= 0x40) return { kind: 'glyph', code: (e - 0x3C) + 5 };
  if (d === 0xFE && e >= 0x7D && e <= 0x81) return { kind: 'glyph', code: e - 0x7D };
  if (e === 0x42 && d < 0x0A) return { kind: 'glyph', code: d };
  // Other cells need _KeyToString or a family-specific control path. Do not
  // pretend E is a standard token-table index: _KeyToString first transforms it.
  if (d === 0x00) return { kind: 'keyString', d, e };
  if (d === 0xFB || d === 0xFC || d === 0xFE) return { kind: 'familyToken', d, e };
  return { kind: 'keyString', d, e };
}

function fmt(d, e) {
  const r = resolveCell(d, e);
  const hex = `${d.toString(16).padStart(2, '0')}${e.toString(16).padStart(2, '0')}`;
  if (r.kind === 'glyph') return `${hex} →glyph 0x${r.code.toString(16)}`;
  if (r.kind === 'colGlyph') return `${hex} →col-glyph #${r.index}`;
  if (r.kind === 'marker') return `${hex} [${r.what}]`;
  if (r.kind === 'keyString') return `${hex} →_KeyToString`;
  if (r.kind === 'familyToken') return `${hex} →family-token (${d.toString(16)})`;
  if (r.kind === 'inlineString') return `${hex} →inline string`;
  if (r.kind === 'specialAction') return `${hex} →special action`;
  if (r.kind === 'runtimeConditional') return `${hex} →conditional (${r.condition})`;
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
