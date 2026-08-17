#!/usr/bin/env node
// Command-line view of the executable page-0x39 cell interpreter shared with
// the browser. See tools/cell-glyph-spec.md and token-name-spec.md.
//
// Usage: node tools/interp-cells.js [classHex]   (default 08 = fnInt/nDeriv row)

const fs = require('fs');
const path = require('path');
const root = path.dirname(__dirname);
const layout = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'layout.json')));
const rom = require(path.join(root, 'web', 'mathprint', 'rom-engine.js'));
const tokenStrings = JSON.parse(fs.readFileSync(
  path.join(root, 'web', 'mathprint', 'token-strings.json')));
rom.setSettledTokenStrings(tokenStrings);

// Delegate cell decisions and counted-string resolution to the browser's
// executable page-39/page-1 translations.
function resolveCell(d, e) {
  const decoded = rom.classifyCell(layout, d, e);
  if (decoded.kind === 'cursorMarker')
    return { kind: 'marker', what: 'cursor/answer-area (no draw)' };
  if (decoded.kind === 'indexedString') return { kind: 'colGlyph', index: decoded.index };
  if (decoded.kind === 'skip') return { kind: 'marker', what: 'terminator' };
  if (decoded.kind === 'directGlyph') return { kind: 'glyph', code: decoded.glyph };
  if (decoded.kind === 'conditionalInlineString')
    return { kind: 'runtimeConditional', d, e, condition: decoded.condition };
  if (decoded.kind === 'inlineString') return { kind: 'inlineString', d, e };
  if (decoded.kind === 'specialAction') return { kind: 'specialAction', d, e };
  if (decoded.kind === 'fixedDelimiter')
    return {
      kind:'delimiterFamily',d,e,family:decoded.layoutClass,index:decoded.index,
      remapped:[decoded.remapped.d,decoded.remapped.e],
      remapSource:decoded.remapped.source,
    };
  if (decoded.kind === 'keyString') return {
    kind:'keyString',d,e,codes:decoded.selection.codes,
    source:decoded.selection.source,
  };
  throw new Error(`unhandled decoded cell kind ${decoded.kind}`);
}

function fmt(d, e) {
  const r = resolveCell(d, e);
  const hex = `${d.toString(16).padStart(2, '0')}${e.toString(16).padStart(2, '0')}`;
  if (r.kind === 'glyph') return `${hex} →glyph 0x${r.code.toString(16)}`;
  if (r.kind === 'colGlyph') return `${hex} →col-glyph #${r.index}`;
  if (r.kind === 'marker') return `${hex} [${r.what}]`;
  if (r.kind === 'keyString') {
    const codes = r.codes === null ? 'unresolved' : r.codes.map(value =>
      value.toString(16).padStart(2,'0')).join(' ');
    return `${hex} →_KeyToString [${codes}] via ${r.source}`;
  }
  if (r.kind === 'inlineString') return `${hex} →inline string`;
  if (r.kind === 'specialAction') return `${hex} →special action`;
  if (r.kind === 'runtimeConditional') return `${hex} →conditional (${r.condition})`;
  if (r.kind === 'delimiterFamily') {
    const mapped = r.remapped.map(value =>
      value.toString(16).padStart(2,'0')).join('');
    return `${hex} →delimiter family ${r.family.toString(16)} #${r.index} →${mapped}`;
  }
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
