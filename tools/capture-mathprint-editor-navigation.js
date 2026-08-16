#!/usr/bin/env node
// Reduce TilEm MathPrint editor RAM snapshots to self-checking navigation
// oracles.  Raw dumps and screenshots remain external capture artifacts; the
// emitted sparse states retain every byte consumed by the editor decoder.

'use strict';

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const root = path.dirname(__dirname);
const rom = require(path.join(root,'web','mathprint','rom-engine.js'));
const font = JSON.parse(fs.readFileSync(
  path.join(root,'web','mathprint','font.json')));
rom.setSettledTokenStrings(JSON.parse(fs.readFileSync(
  path.join(root,'web','mathprint','token-strings.json'))));

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exit(2);
}

function argumentsByName(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key || !key.startsWith('--') || value === undefined)
      fail('arguments must be --name value pairs');
    result[key.slice(2)] = value;
  }
  return result;
}

function digest(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function packedLcdBytes(grid) {
  return Buffer.from(grid.flatMap(row => {
    if (!Array.isArray(row) || row.length % 8)
      throw new Error('LCD grid rows must be byte-aligned');
    const bytes = [];
    for (let x = 0; x < row.length; x += 8) {
      let value = 0;
      for (let bit = 0; bit < 8; bit++)
        value |= row[x + bit] << (7 - bit);
      bytes.push(value);
    }
    return bytes;
  }));
}

function projection(state) {
  return {
    entryId:state.entryId,
    controller:state.controller,
    cursor:{
      recordId:state.editor.cursor.recordId,
      byteOffset:state.editor.cursor.byteOffset,
      boundaries:state.editor.cursor.boundaries,
      path:state.editor.cursor.path,
      left:state.editor.cursor.left,
      right:state.editor.cursor.right,
    },
    expression:state.expression,
    editorExpression:state.editor.expression,
    nodes:state.nodes.map(node => ({
      record_id:node.record_id === undefined ? node.id : node.record_id,
      render_type:node.render_type === undefined ? node.type : node.render_type,
      word03:node.word03,word05:node.word05,word07:node.word07,
      word09:node.word09,word0B:node.word0B,word0D:node.word0D,
      word0F:node.word0F,word11:node.word11,byte13:node.byte13,
      child_ids:node.child_ids.slice(),
      payload:node.payload.slice(),
    })).sort((left,right) => left.record_id - right.record_id),
  };
}

function sameState(left, right) {
  return JSON.stringify(projection(left)) === JSON.stringify(projection(right));
}

function readWord(ram, address) {
  return ram.readUInt16LE(address - 0x8000);
}

function mergedRanges(ranges) {
  const result = [];
  for (const [start,end] of ranges
    .filter(([start,end]) => start < end)
    .sort((left,right) => left[0] - right[0])) {
    const previous = result.at(-1);
    if (previous && start <= previous[1])
      previous[1] = Math.max(previous[1],end);
    else
      result.push([start,end]);
  }
  return result;
}

function sparseSegments(raw) {
  // 34:4ACE/4A83 consume the arena from structuralStart through mainTail.
  // When the gap is active, editTail through editorBoundary contains the
  // right payload and every leaf record relocated after it.
  const ranges = mergedRanges([
    [0x89f1,0x89f2],
    [0x8daf,0x8dc4],
    [0x96f4,0x96fc],
    [readWord(raw,0x8daf),readWord(raw,0x8dbe)],
    [readWord(raw,0x96f8),readWord(raw,0x8db1)],
  ]);
  const hasher = crypto.createHash('sha256');
  const segments = ranges.map(([address,end]) => {
    const bytes = raw.subarray(address - 0x8000,end - 0x8000);
    const encodedAddress = Buffer.alloc(2);
    encodedAddress.writeUInt16LE(address);
    hasher.update(encodedAddress);
    hasher.update(bytes);
    return {address,bytes:bytes.toString('hex')};
  });
  return {segments,sparse_state_sha256:hasher.digest('hex')};
}

function decodeSparse(state) {
  const ram = new Uint8Array(0x8000);
  for (const segment of state.segments)
    ram.set(Buffer.from(segment.bytes,'hex'),segment.address - 0x8000);
  return rom.decodeMathPrintEditorRam(ram);
}

function captureStatePaths(ramPath, screenshotPath, name) {
  const raw = fs.readFileSync(ramPath);
  if (raw.length < 0x8000)
    throw new RangeError(`${ramPath} is shorter than one logical RAM window`);
  const sparse = sparseSegments(raw);
  const decoded = decodeSparse(sparse);
  const direct = rom.decodeMathPrintEditorRam(
    new Uint8Array(raw.subarray(0,0x8000)));
  if (!sameState(decoded,direct))
    throw new Error(`${name}: sparse RAM does not preserve the decoded state`);
  const reconstructed = rom.constructEditorExpressionProgram(
    decoded.editor.expression,7,font);
  const operations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,{
      glyphAdvance:(depth,code) => depth === 0
        ? 6 : font.small.glyphs[code].w,
    });
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  return {
    name,
    source_ram_sha256:digest(raw),
    screenshot_sha256:digest(fs.readFileSync(screenshotPath)),
    lcd_bitmap_sha256:digest(packedLcdBytes(lcd)),
    ...sparse,
  };
}

function captureState(prefix, index, name) {
  return captureStatePaths(
    `${prefix}-${index}.ram`,`${prefix}-${index}.png`,name);
}

function main() {
  const args = argumentsByName(process.argv.slice(2));
  for (const name of ['name','prefix','macro','trace','direction','states'])
    if (!args[name]) fail(`missing --${name}`);
  if (args.direction !== 'left' && args.direction !== 'right')
    fail('--direction must be left or right');
  const names = args.states.split(',');
  if (!names.length || names.some(name => !name))
    fail('--states must contain comma-separated state names');
  const states = names.map((name,index) =>
    captureState(args.prefix,index,name));
  const decoded = states.map(decodeSparse);
  const transitions = [];
  for (let index = 0; index + 1 < decoded.length; index++) {
    const moved = rom.editorMoveCursor(decoded[index],args.direction,font);
    if (!sameState(moved.state,decoded[index + 1]))
      throw new Error(
        `${args.name}: translated transition ${index} does not match state ${index + 1}`);
    transitions.push({
      capture:args.name,
      from_index:index,
      to_index:index + 1,
      direction:args.direction,
      status:moved.mutation.status,
      routine:moved.mutation.routine,
    });
  }
  process.stdout.write(`${JSON.stringify({
    capture:{
      macro:args.macro,
      macro_sha256:digest(fs.readFileSync(args.macro)),
      trace_sha256:digest(fs.readFileSync(args.trace)),
      states,
    },
    transitions,
  },null,2)}\n`);
}

module.exports = {
  captureState,captureStatePaths,decodeSparse,projection,sameState,
};

if (require.main === module) main();
