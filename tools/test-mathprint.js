#!/usr/bin/env node
// Fuzz + corpus test for the MathPrint layout renderer (web/mathprint/app.js).
// Robustness only: every generated expression must parse and lay out without
// throwing, and produce a sane bounding box. The parser is lenient (it renders
// partial input as you type), so this checks it never crashes or produces a
// degenerate box. Pixel parity against the real calculator is checked
// separately by tools/parity-mathprint.py.
//
// Usage: node tools/test-mathprint.js [count]   (default 5000)

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const root = path.dirname(__dirname);
const mp = require(path.join(root, 'web', 'mathprint', 'app.js'));
const rom = require(path.join(root, 'web', 'mathprint', 'rom-engine.js'));
const { resolveCell } = require(path.join(root, 'tools', 'interp-cells.js'));
const font = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'font.json')));
mp.setFont(font);
const layout = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'layout.json')));
mp.setLayout(layout);
const drawOrder = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'draw-order.json')));
const recordPrograms = JSON.parse(fs.readFileSync(
  path.join(root, 'web', 'mathprint', 'record-programs.json')));
const constructionOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-construction-oracles.json')));
mp.setRecordPrograms(recordPrograms);

function expectEqual(label, actual, expected) {
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error(`${label}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
}

function expectThrows(label, errorType, operation) {
  try {
    operation();
  } catch (error) {
    if (error instanceof errorType) return;
    throw new Error(`${label}: threw ${error.constructor.name}, expected ${errorType.name}`);
  }
  throw new Error(`${label}: did not throw ${errorType.name}`);
}

// Executable translations of closed page-39 routines. These expectations are
// pinned to the extracted OS 2.55MP records and the byte-decoded algorithms.
const integralRow = rom.emitHandlerRow(layout, 0x0d, 2);
expectEqual('39:4DCA class 0D row 2', {
  countAddress: integralRow.countAddress,
  actionAddress: integralRow.actionAddress,
  cellsAddress: integralRow.cellsAddress,
  count: integralRow.count,
  action: integralRow.action,
}, { countAddress: 0x60fc, actionAddress: 0x60ff,
     cellsAddress: 0x6134, count: 10, action: 0x2c });
expectEqual('39:4DE6 integral glyph emission', integralRow.emissions[8], {
  slot: 8,
  address: 0x6144,
  cell: [0x08, 0x42],
  output: { kind: 'directGlyph', d: 0x08, e: 0x42,
            glyph: 0x08, routine: '39:4F1A' },
});

for (const [[d, e], glyph] of [
  [[0xfc, 0x3c], 5], [[0xfc, 0x40], 9],
  [[0xfe, 0x7d], 0], [[0xfe, 0x81], 4], [[9, 0x42], 9],
]) expectEqual(`39:4F1A ${d.toString(16)}:${e.toString(16)}`,
               rom.mapDirectGlyph(d, e), glyph);
for (const [d, e] of [[0xfc, 0x3b], [0xfc, 0x41], [0xfe, 0x7c],
                       [0xfe, 0x82], [0x0a, 0x42], [0, 0x10]])
  expectEqual(`39:4F1A carry ${d.toString(16)}:${e.toString(16)}`,
              rom.mapDirectGlyph(d, e), null);

expectEqual('39:4E8E cursor branch', rom.classifyCell(layout, 0x1f, 0x12),
  {kind:'cursorMarker', d:0x1f, e:0x12, routine:'39:4E93'});
expectEqual('39:4E8E indexed-string branch', rom.classifyCell(layout, 0x82, 0x42),
  {kind:'indexedString', d:0x82, e:0x42, index:4, routine:'39:4EBF'});
expectEqual('39:6675 delimiter branch', rom.classifyCell(layout, 0xfc, 0x00),
  {kind:'fixedDelimiter', d:0xfc, e:0, layoutClass:0x17, index:0, routine:'39:6675'});
expectEqual('01:6D10 E=1F index', rom.keyToStringIndex(6, 0x1f),
  {index:0x56, branch:'E=1F'});
expectEqual('01:6D10 ordinary index', rom.keyToStringIndex(0, 0x10),
  {index:0, branch:'ordinary E-10'});

const fractionDescriptor = rom.descriptorState(layout, 0x686f);
expectEqual('39:6A00 descriptor ABI', fractionDescriptor, {
  descriptorAddress:0x686f, penBaseLow:3, penBaseHigh:25,
  boxWord:0x3535, rowHeight:6, rows:1, columns:4,
  cellPointer:0x6878,
  cells:[[0xfb,0xca],[0xfb,0xcb],[0xfb,0xcc],[0xfb,0xcd]],
});
expectEqual('39:683D descriptor origin', rom.descriptorPen(fractionDescriptor, 0, 0),
  {low:3, high:25, hl:0x1903});
expectEqual('39:683D descriptor column step', rom.descriptorPen(fractionDescriptor, 0, 3),
  {low:3, high:46, hl:0x2e03});
const twoRow = rom.descriptorState(layout, 0x6893);
expectEqual('39:683D descriptor row step', rom.descriptorPen(twoRow, 1, 2),
  {low:70, high:32, hl:0x2046});
expectEqual('39:69C8 kind 10 selector', rom.selectDescriptor(layout, 0x10).descriptor.addr, 0x686f);
expectEqual('39:69C8 kind 11 selector', rom.selectDescriptor(layout, 0x11).descriptor.addr, 0x6880);
expectEqual('39:69C8 kind 12 selector', rom.selectDescriptor(layout, 0x12),
  {kind:'measuredFraction', routine:'39:6A8A'});
expectEqual('39:69C8 unresolved family boundary', rom.selectDescriptor(layout, 0x13),
  {kind:'unresolvedDescriptorFamily', templateKind:3,
   missing:'ram:025E/0254 family-shape predicates'});
expectEqual('39:6B1C endpoint', rom.fractionEndpoint(2, 0x17),
  {left:0x29, right:0x2d, top:0x17, bottom:0x1d});
expectEqual('39:5949 class-6 low slot', rom.multiArgumentRowStep(6, 2), 2);
expectEqual('39:5949 class-6 high slot', rom.multiArgumentRowStep(6, 3), 1);
expectEqual('39:5949 other class', rom.multiArgumentRowStep(5, 2), 1);
expectEqual('34:5E98 top integral hook point', rom.settledPointOperation(3, 0), {
  kind:'point', x:3, y:0, registers:{b:3,c:0x3f,d:1},
  routine:'34:5E98–5EA6 → 04:4155',
});
expectEqual('34:5E98 lower fraction corner', rom.settledPointOperation(0x20, 0x14), {
  kind:'point', x:0x20, y:0x14, registers:{b:0x20,c:0x2b,d:1},
  routine:'34:5E98–5EA6 → 04:4155',
});
expectEqual('34:5DD1 x clipping', rom.settledPointOperation(0x60, 0), null);
expectEqual('34:5DEF y clipping', rom.settledPointOperation(0, 0x40), null);
const fullViewport = {xOrigin:0, yOrigin:0, xMax:0x5f, yMax:0x3e, xClip:0, yClip:0};
expectEqual('34:5D96 integral stem',
  rom.settledVerticalOperation(2, 1, 0x15, fullViewport), {
    kind:'line', axis:'vertical', from:{x:2,y:0x3e}, to:{x:2,y:0x2a},
    routine:'34:5D96–5DA5 → 04:431D',
  });
expectEqual('34:5DA6 fraction bar with live origin',
  rom.settledHorizontalOperation(1, 5, 6,
    {xOrigin:16, yOrigin:5, xMax:0x5f, yMax:0x3e, xClip:0, yClip:0}), {
    kind:'line', axis:'horizontal', from:{x:17,y:52}, to:{x:21,y:52},
    routine:'34:5DA6–5DBD → 04:4382',
  });
expectEqual('34:5D96 endpoint sorting and clipping',
  rom.settledVerticalOperation(3, 9, 1,
    {xOrigin:0, yOrigin:0, xMax:0x5f, yMax:6, xClip:0, yClip:2}), {
    kind:'line', axis:'vertical', from:{x:3,y:0x3f}, to:{x:3,y:0x39},
    routine:'34:5D96–5DA5 → 04:431D',
  });
expectEqual('34:5DA6 fully clipped',
  rom.settledHorizontalOperation(0, 2, 0, {...fullViewport, xClip:5}), null);
const objectHandlers = [0x6d0c,0x706a,0x70b8,0x702c,0x7133,0x70a0,0x70e2,
  0x70e2,0x7087,0x7102,0x717e,0x70c1,0x71c6];
objectHandlers.forEach((handler, kind) => expectEqual(`34:7012 object kind ${kind}`,
  rom.settledObjectHandler(kind), {
    kind, handler, tableAddress:0x7012 + 2 * kind, routine:'34:700C → 34:6105',
  }));
let rejectedObjectKind = false;
try { rom.settledObjectHandler(13); } catch (error) { rejectedObjectKind = error instanceof RangeError; }
expectEqual('34:7012 object kind bound', rejectedObjectKind, true);
expectEqual('34:620A fraction primitive order', rom.settledFractionOperations(4, 4, 6), [
  {kind:'child', index:1, routine:'34:620A → 34:636C'},
  {kind:'child', index:2, routine:'34:6214 → 34:6378'},
  {kind:'line', axis:'horizontal', from:{x:1,y:6}, to:{x:5,y:6},
   routine:'34:622C → 34:5DA6'},
]);
expectEqual('34:620A fraction chooses wider child', rom.settledFractionOperations(7, 3, 9)[2],
  {kind:'line', axis:'horizontal', from:{x:1,y:9}, to:{x:8,y:9},
   routine:'34:622C → 34:5DA6'});
expectEqual('34:6375 single-child traversal', rom.settledSingleChildOperations(), [
  {kind:'child', index:1, routine:'34:6375 → 34:636C'},
]);
expectEqual('34:6347 absolute primitive order', rom.settledAbsoluteOperations(0x1e, 7), [
  {kind:'line', axis:'vertical', from:{x:2,y:0}, to:{x:2,y:6},
   routine:'34:6351 → 34:5D96'},
  {kind:'line', axis:'vertical', from:{x:0x1a,y:0}, to:{x:0x1a,y:6},
   routine:'34:6360 → 34:5D96'},
  {kind:'child', index:1, routine:'34:6366 → 34:636C'},
]);
expectEqual('34:6315 nth-root primitive order', rom.settledNthRootOperations(4, 0x18), [
  {kind:'child', index:1, routine:'34:6315 → 34:636C'},
  {kind:'bitmap', x:3, y:4, width:5, height:7,
   rows:[0x04,0x04,0x04,0x04,0x14,0x0c,0x04],
   routine:'34:6321 → 34:62D0 → 34:630C'},
  {kind:'line', axis:'vertical', from:{x:5,y:3}, to:{x:5,y:4},
   routine:'34:6331 → 34:5D96'},
  {kind:'child-select', index:2, routine:'34:6334 → 34:6CCA'},
  {kind:'line', axis:'horizontal', from:{x:5,y:2}, to:{x:0x1e,y:2},
   routine:'34:6344 → 34:5DA6'},
  {kind:'child', index:2, routine:'34:6344 → 34:62C3 → 34:62C6'},
]);
expectEqual('settled record header ABI', rom.decodeSettledRecord([
  0x10,0x00,0x27,0x0f,0x00,0x01,0x00,0x0c,0x00,0x1b,
  0x00,0x08,0x00,0x00,0x00,0x00,0x00,0x01,0x00,0xef,
]), {
  id:0x10, type:0x27, word03:0x0f, word05:1, word07:0x0c,
  word09:0x1b, word0B:8, word0D:0, word0F:0, word11:1, byte13:0xef,
});
const renderHandlers = [0x6143,0x620a,0x6347,0x622f,0x640e,0x6315,0x637e,
  0x63ad,0x62a1,0x63b2,0x6504,0x6375,0x65aa];
renderHandlers.forEach((handler, index) => {
  const renderType = 0x1f + index;
  expectEqual(`34:6119 render type ${renderType.toString(16)}`,
    rom.settledRenderHandler(renderType), {
      renderType, handler, tableAddress:0x6119 + 2 * index,
      routine:'34:6105 → 34:6119',
    });
});
expectEqual('34:5D1A five-row compound',
  rom.settledCompoundOperations('open', 10, 4, 5), [
    {kind:'point',x:13,y:4,routine:'34:5D1A → 34:5E85'},
    {kind:'point',x:13,y:8,routine:'34:5D1A → 34:5E85'},
    {kind:'line',axis:'vertical',from:{x:12,y:5},to:{x:12,y:7},
     routine:'34:5D1A → 34:5D96'},
  ]);
expectEqual('34:5D07 tall compound',
  rom.settledCompoundOperations('close', 20, 6, 7), [
    {kind:'point',x:21,y:6,routine:'34:5D07 → 34:5E85'},
    {kind:'point',x:21,y:12,routine:'34:5D07 → 34:5E85'},
    {kind:'point',x:22,y:7,routine:'34:5D07 → 34:5E85'},
    {kind:'point',x:22,y:11,routine:'34:5D07 → 34:5E85'},
    {kind:'line',axis:'vertical',from:{x:23,y:8},to:{x:23,y:10},
     routine:'34:5D07 → 34:5D96'},
  ]);
const settledRecord = (id, type, fields = {}, childIds = [], payload = []) => ({
  id, type, word03:0, word05:0, word07:0, word09:0, word0B:0,
  word0D:0, word0F:0, word11:0, byte13:0, ...fields, childIds, payload,
});
const leafGlyph = record => [{kind:'glyph',code:record.id,x:0,y:0,routine:'test leaf'}];
const absoluteGraph = rom.executeSettledRecordGraph([
  settledRecord(0x0e, 0x21, {word07:7,word09:0x1e}, [0x0d]),
  settledRecord(0x0d, 0x00, {word0B:4}),
], 0x0e, {renderLeaf:leafGlyph});
expectEqual('settled graph absolute child ID and origin',
  absoluteGraph.map(op => [op.kind, op.recordId, op.depth,
    op.from ? op.from.x : op.x, op.from ? op.from.y : op.y]), [
    ['line',0x0e,1,2,0], ['line',0x0e,1,0x1a,0],
    ['glyph',0x0d,0,4,0],
  ]);
const nthRootGraph = rom.executeSettledRecordGraph([
  settledRecord(0x0f, 0x24, {word07:11}, [0x10,0x11]),
  settledRecord(0x10, 0x00, {word07:4}),
  settledRecord(0x11, 0x00, {word07:0x18,word0B:8,word0D:4}),
], 0x0f, {renderLeaf:leafGlyph});
expectEqual('settled graph nth-root drawing order and child offsets',
  nthRootGraph.map(op => [op.kind, op.recordId, op.x === undefined ? op.from.x : op.x,
    op.y === undefined ? op.from.y : op.y]), [
    ['glyph',0x10,0,0], ['bitmap',0x0f,3,4], ['line',0x0f,5,3],
    ['line',0x0f,5,2], ['glyph',0x11,8,4],
  ]);
const nestedFractionGraph = rom.executeSettledRecordGraph([
  settledRecord(0x0d, 0x20, {word0B:6}, [0x0e,0x0f]),
  settledRecord(0x0e, 0x00, {word07:4}),
  settledRecord(0x0f, 0x00, {word07:4,word0D:8}),
], 0x0d, {renderLeaf:leafGlyph,origin:{x:16,y:5}});
expectEqual('settled nested fraction keeps local rule and live origin',
  nestedFractionGraph.map(op => [op.kind,op.recordId,
    op.from ? op.from.x : op.x, op.from ? op.from.y : op.y,
    op.to ? op.to.x : null, op.to ? op.to.y : null]), [
    ['glyph',0x0e,16,5,null,null],
    ['glyph',0x0f,16,13,null,null],
    ['line',0x0d,17,11,21,11],
  ]);
const matrixRoot = settledRecord(0x10, 0x2b,
  {word05:4,word07:0x10,word09:0x1e,word11:0x0201,byte13:2},
  [0x11,0x13,0x14,0x15]);
expectEqual('33:4F23 matrix product', rom.matrixChildCount(matrixRoot), 4);
const matrixGraph = rom.executeSettledRecordGraph([
  matrixRoot,
  settledRecord(0x11,0,{word0B:6,word0D:2}),
  settledRecord(0x13,0,{word0B:16,word0D:2}),
  settledRecord(0x14,0,{word0B:6,word0D:9}),
  settledRecord(0x15,0,{word0B:16,word0D:9}),
], 0x10, {renderLeaf:leafGlyph});
expectEqual('settled matrix brackets surround row-major children',
  matrixGraph.map(op => [op.kind,op.recordId,op.depth,
    op.x === undefined ? op.from.x : op.x,op.y === undefined ? op.from.y : op.y]), [
    ['line',0x10,1,2,0], ['point',0x10,1,3,0], ['point',0x10,1,3,15],
    ['glyph',0x11,0,6,2], ['glyph',0x13,0,16,2],
    ['glyph',0x14,0,6,9], ['glyph',0x15,0,16,9],
    ['line',0x10,1,26,0], ['point',0x10,1,25,0], ['point',0x10,1,25,15],
  ]);

const settledGlyphAdvance = (depth, code) => {
  if (depth === 0) return 6;
  const glyph = font.small.glyphs[code];
  if (!glyph) throw new Error(`small glyph 0x${code.toString(16)} is absent`);
  return glyph.w;
};
const settledGlyphStream = (nodes, entryId) => rom.executeSettledRecordProgram(
  nodes, entryId, {glyphAdvance:settledGlyphAdvance},
).filter(operation => operation.kind === 'glyph')
  .map(operation => [operation.code,operation.x,operation.y,operation.depth]);

const absoluteProgram = [
  settledRecord(0x0d,0,{word09:3,word11:6},[],
    [0xef,0x21,0x0e,0x00,0xef,0x2d]),
  settledRecord(0x0e,0x21,{word07:7,word09:30,word0B:3},[0x0f]),
  settledRecord(0x0f,0,{word07:18,word09:3,word0B:6,word11:3},[],
    [0x58,0x71,0x33]),
];
expectEqual('settled absolute program independently reproduces trace glyph order',
  settledGlyphStream(absoluteProgram,0x0d), [
    [0x58,6,0,0], [0x2d,12,0,0], [0x33,18,0,0],
  ]);

const summationProgram = [
  settledRecord(0x12,0,{word09:9,word11:13},[],
    [0xef,0x29,0x13,0x00,0xef,0x2d,0x4e,
     0xef,0x2a,0x18,0x00,0xef,0x2d]),
  settledRecord(0x13,0x29,{word05:3,word07:19,word09:31,word0B:9},
    [0x14,0x15,0x16,0x17]),
  settledRecord(0x14,1,{word07:4,word09:2,word0D:14,word11:1},[],[0x4e]),
  settledRecord(0x15,0,{word07:6,word09:2,word0B:8,word0D:14,word11:2},[],
    [0xef,0x1e]),
  settledRecord(0x16,0,{word07:4,word09:2,word0B:5,word11:1},[],[0x31]),
  settledRecord(0x17,0,{word05:7,word07:6,word09:3,word0B:20,word0D:6,word11:1},[],[0x33]),
  settledRecord(0x18,0x2a,{word07:16,word09:4,word0B:6,word0D:37},[0x19]),
  settledRecord(0x19,0,{word07:4,word09:2,word11:1},[],[0x32]),
];
expectEqual('settled summation program independently reproduces trace glyph order',
  settledGlyphStream(summationProgram,0x12), [
    [0xc6,4,6,0], [0x4e,0,14,1], [0x3d,4,14,1], [0xf7,8,14,1],
    [0x31,5,0,1], [0x33,20,6,0], [0x4e,31,6,0], [0x32,37,3,1],
  ]);

const nderivProgram = [
  settledRecord(0x11,0,{word09:6,word11:7},[],
    [0xef,0x23,0x12,0x00,0xef,0x2d,0x31]),
  settledRecord(0x12,0x23,{word05:3,word07:13,word09:47,word0B:6},[0x13,0x14,0x15]),
  settledRecord(0x13,1,{word05:5,word07:4,word09:2,word0B:5,word0D:8,word11:1},[],[0x58]),
  settledRecord(0x14,0,{word05:10,word07:10,word09:6,word0B:16,word11:8},[],
    [0xef,0x1e,0xef,0x2a,0x16,0x00,0xef,0x2d]),
  settledRecord(0x16,0x2a,{word07:10,word09:4,word0B:6,word0D:6},[0x17]),
  settledRecord(0x17,0,{word07:4,word09:2,word11:1},[],[0x32]),
  settledRecord(0x15,0,{word05:5,word07:4,word09:2,word0B:43,word0D:8,word11:1},[],[0x58]),
];
expectEqual('settled nDeriv program independently reproduces trace glyph order',
  settledGlyphStream(nderivProgram,0x11), [
    [0x64,3,0,1], [0x64,1,8,1], [0x58,5,8,1], [0xf7,16,3,0],
    [0x32,22,0,1], [0x58,35,8,1], [0x3d,39,8,1], [0x58,43,8,1],
    [0x31,47,3,0],
  ]);
const nthRootProgram = [
  settledRecord(0x0e,0,{word09:7,word11:6},[],
    [0xef,0x24,0x0f,0x00,0xef,0x2d]),
  settledRecord(0x0f,0x24,{word07:11,word09:26,word0B:7},[0x10,0x11]),
  settledRecord(0x10,0,{word05:5,word07:4,word09:2,word11:1},[],[0x33]),
  settledRecord(0x11,0,{word05:7,word07:18,word09:3,word0B:8,word0D:4,word11:3},[],
    [0x58,0x70,0x31]),
];
const radicalProgram = [
  settledRecord(0x0f,0,{word09:8,word11:6},[],
    [0xef,0x27,0x10,0x00,0xef,0x2d]),
  settledRecord(0x10,0x27,{word07:12,word09:27,word0B:8},[0x11]),
  settledRecord(0x11,0,{word05:10,word07:22,word09:6,word0B:5,word0D:2,word11:9},[],
    [0x58,0xef,0x2a,0x12,0x00,0xef,0x2d,0x70,0x31]),
  settledRecord(0x12,0x2a,{word07:10,word09:4,word0B:6,word0D:6},[0x13]),
  settledRecord(0x13,0,{word05:5,word07:4,word09:2,word11:1},[],[0x32]),
];
const integralFractionProgram = [
  settledRecord(0x07,0,{word09:11,word11:6},[],
    [0xef,0x22,0x08,0x00,0xef,0x2d]),
  settledRecord(0x08,0x22,{word07:23,word09:50,word0B:11},[0x09,0x0a,0x0b,0x0c]),
  settledRecord(0x09,0,{word05:5,word07:4,word09:2,word0B:6,word0D:18,word11:1},[],[0x31]),
  settledRecord(0x0a,0,{word05:5,word07:4,word09:2,word0B:6,word11:1},[],[0x32]),
  settledRecord(0x0b,0,{word05:13,word07:14,word09:6,word0B:16,word0D:5,word11:7},[],
    [0xef,0x20,0x0d,0x00,0xef,0x2d,0x58]),
  settledRecord(0x0d,0x20,{word05:2,word07:13,word09:8,word0B:6},[0x0e,0x0f]),
  settledRecord(0x0e,0,{word05:5,word07:4,word09:2,word0B:2,word11:1},[],[0x31]),
  settledRecord(0x0f,0,{word05:5,word07:4,word09:2,word0B:2,word0D:8,word11:1},[],[0x32]),
  settledRecord(0x0c,1,{word05:7,word07:6,word09:3,word0B:42,word0D:8,word11:1},[],[0x58]),
];

const settledRasterHash = (nodes, entryId) => {
  const operations = rom.executeSettledRecordProgram(nodes, entryId, {
    glyphAdvance:settledGlyphAdvance,
  });
  const bits = rom.rasterizeSettledOperations(operations, font).grid
    .map(row => row.join('')).join('');
  return crypto.createHash('sha256').update(bits).digest('hex');
};
const settledWriteHash = (nodes, entryId, visibleOnly = false) => {
  const operations = rom.executeSettledRecordProgram(nodes, entryId, {
    glyphAdvance:settledGlyphAdvance,
  });
  let writes = rom.rasterizeSettledOperations(operations, font).writes;
  if (visibleOnly) writes = writes.filter(write => write.changes.length);
  const bytes = writes
    .flatMap(write => [...write.pointer,write.value]);
  return crypto.createHash('sha256').update(Buffer.from(bytes)).digest('hex');
};
// These hashes come from independent T6A04 replay at the return of the outer
// 34:660A call. The record snapshots are executor inputs; LCD events are not.
for (const [name,nodes,entryId,expected] of [
  ['absolute',absoluteProgram,0x0d,'d0442f38290a446074d49f43cff43f852569143d8ab2851e914a59cec0ad087d'],
  ['nth root',nthRootProgram,0x0e,'1b939a055eb331245bd8d2abf782fc9978fb3488a6dc61d660bbada0f463df30'],
  ['radical',radicalProgram,0x0f,'8731b65f0db1f172145b596c0b85339e2ededb8dc3b883f9a423a01cb75185ae'],
  ['summation',summationProgram,0x12,'9e73a0dce521895a417ebf80a723d6f608c24999935fc1bf38cb5cc744cc3b4f'],
  ['nDeriv',nderivProgram,0x11,'15b36862c68d200239930acc52622c0f7898e66ad74c751fed1e03dd6ddeb3a5'],
  ['nested integral/fraction',integralFractionProgram,0x07,'3e14504af269ef52a7d3032b2ab3f9c91460ffbc5c7f445f8d4b9aea9621d1aa'],
]) expectEqual(`settled ${name} independently reproduces final LCD pixels`,
                settledRasterHash(nodes,entryId), expected);
for (const [name,nodes,entryId,expected] of [
  ['absolute',absoluteProgram,0x0d,'5215280de472ff2d94dc2b158b2edf22820c906b895d6272b5e009c10f6ab997'],
  ['nth root',nthRootProgram,0x0e,'de981d526c703a91d101e260d6aed69d3f750a4526a7d4c01b9187c060132b31'],
  ['radical',radicalProgram,0x0f,'4ab47d3ecc113ccf67f1c120e37e5d64ed697f5b6698c4f124274765b17f48fe'],
  ['summation',summationProgram,0x12,'930d12d5c4ad8a8ecb3650776ac937753c755606a5046e11b2a8117873b2b0d9'],
  ['nDeriv',nderivProgram,0x11,'632a357aa5b55ab4d8fcc20a4e39e95c3f664166228c5a9625457e5fb5d645fc'],
  ['nested integral/fraction',integralFractionProgram,0x07,'f82758d431e616be056a6748e332b7dd5d859cb948f2192bdc99e7e14d38e237'],
]) expectEqual(`settled ${name} independently reproduces LCD write order`,
                settledWriteHash(nodes,entryId,true), expected);
for (const [name,nodes,entryId,expected] of [
  ['absolute',absoluteProgram,0x0d,'0c11578979dbf5a5c6ef423dfbc4e1a465322e5e639257ccc44e69f910cdcf99'],
  ['nth root',nthRootProgram,0x0e,'7b9fa6dd5d22b6e68570c45970764516b985780ce5de55c1945ac0b937ce99e5'],
  ['radical',radicalProgram,0x0f,'56cd3a3c3b9eea8c2b99e96abee7d7175d5c3fd1e7930c4319aa1d464cc84750'],
  ['summation',summationProgram,0x12,'4cb34332e177c4255fbcb816c4b2d35bfde37af28e19eec3954878fce3c604c8'],
  ['nDeriv',nderivProgram,0x11,'0fd35d37d451e9df18349f062eebf72b3d913b27a31779cc9cd8b723f2365952'],
  ['nested integral/fraction',integralFractionProgram,0x07,'2b8bc21220f632c2524e011418d51cc6040036941e076a642f6645b2b5d581a2'],
]) expectEqual(`settled ${name} independently reproduces every accepted LCD data write`,
                settledWriteHash(nodes,entryId), expected);

const browserProgramCases = [
  ['abs(X-3)', absoluteProgram, 0x0d],
  ['nthroot(3,X+1)', nthRootProgram, 0x0e],
  ['sqrt(X^2+1)', radicalProgram, 0x0f],
  ['sum(N,1,3,N^2)', summationProgram, 0x12],
  ['nDeriv(X^2,X,1)', nderivProgram, 0x11],
  ['int(1,2,(1//2)X,X)', integralFractionProgram, 0x07],
];
expectEqual('34:5935 maps the absolute token through 34:594D',
  rom.settledStructuralTokenType(0x00,0xb2), 0x21);
expectEqual('34:5935 leaves an ordinary token unmapped',
  rom.settledStructuralTokenType(0x00,0x58), null);
expectEqual('34:5996 selects the absolute metadata row',
  rom.settledRecordMetadata(0x21), [0x03,0x01,0x00,0x00,0x00]);
expectEqual('34:5935 maps the power token through 34:594D',
  rom.settledStructuralTokenType(0x00,0xf0), 0x2a);
expectEqual('34:5996 selects the power metadata row',
  rom.settledRecordMetadata(0x2a), [0x01,0x01,0x00,0x00,0x00]);
const constructedAbsolute = rom.constructSettledAbsoluteProgram([0x58,0x71,0x33],0x0d);
expectEqual('absolute tokens independently construct the settled record graph',
  constructedAbsolute.nodes, recordPrograms.programs['abs(X-3)'].nodes);
for (const oracle of constructionOracles.absolute_cases) {
  const program = rom.constructSettledAbsoluteProgram(oracle.tokens, oracle.entry_id);
  expectEqual(`${oracle.expression} independently constructs the fresh TilEm graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(program.nodes, program.entry_id, {
    origin:program.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const writes = rom.rasterizeSettledOperations(operations, font).writes;
  expectEqual(`${oracle.expression} independently reproduces fresh accepted-write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} independently reproduces fresh accepted-write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
}
for (const oracle of constructionOracles.power_cases) {
  const program = rom.constructSettledPowerProgram(oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} independently constructs the fresh TilEm graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(program.nodes, program.entry_id, {
    origin:program.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const writes = rom.rasterizeSettledOperations(operations, font).writes;
  expectEqual(`${oracle.expression} independently reproduces fresh accepted-write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} independently reproduces fresh accepted-write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
}
expectEqual('browser selects translated absolute record construction',
  mp.constructedProgramForExpression('abs(X-3)').nodes,
  rom.constructSettledAbsoluteProgram([0x58,0x71,0x33]).nodes);
expectEqual('arbitrary flat absolute expression constructs from its own tokens',
  mp.constructedProgramForExpression('abs(A+12)').nodes[2].payload,
  [0x41,0x70,0x31,0x32]);
expectEqual('untranslated expression has no generated record constructor',
  mp.constructedProgramForExpression('sqrt(X^2+1)'), null);
const constructedPower = rom.constructSettledPowerProgram(
  {base:[0x58], exponent:[0x32]}, 0x0d, font);
expectEqual('power tokens independently construct the settled X^2 graph',
  constructedPower.nodes, [
    {record_id:13,render_type:0,word03:12,word05:10,word07:10,word09:6,
     word0B:0,word0D:0,word0F:7,word11:7,byte13:88,child_ids:[],
     payload:[88,239,42,14,0,239,45]},
    {record_id:14,render_type:42,word03:13,word05:1,word07:10,word09:4,
     word0B:6,word0D:6,word0F:0,word11:1,byte13:88,child_ids:[15],payload:[]},
    {record_id:15,render_type:0,word03:14,word05:5,word07:4,word09:2,
     word0B:0,word0D:0,word0F:1,word11:1,byte13:50,child_ids:[],payload:[50]},
  ]);
expectEqual('power constructor applies small-font width to a multi-token exponent',
  rom.constructSettledPowerProgram(
    {base:[0x58], exponent:[0x31,0x32]}, 0x0d, font).nodes,
  [
    {record_id:13,render_type:0,word03:12,word05:10,word07:14,word09:6,
     word0B:0,word0D:0,word0F:7,word11:7,byte13:88,child_ids:[],
     payload:[88,239,42,14,0,239,45]},
    {record_id:14,render_type:42,word03:13,word05:1,word07:10,word09:8,
     word0B:6,word0D:6,word0F:0,word11:1,byte13:88,child_ids:[15],payload:[]},
    {record_id:15,render_type:0,word03:14,word05:5,word07:8,word09:2,
     word0B:0,word0D:0,word0F:2,word11:2,byte13:49,child_ids:[],payload:[49,50]},
  ]);
expectEqual('power constructor preserves right-associative nested depth metrics',
  rom.constructSettledPowerProgram({
    base:[0x32], exponent:{base:[0x58], exponent:[0x32]},
  }, 0x0f, font).nodes,
  [
    {record_id:15,render_type:0,word03:14,word05:13,word07:14,word09:9,
     word0B:0,word0D:0,word0F:7,word11:7,byte13:50,child_ids:[],
     payload:[50,239,42,16,0,239,45]},
    {record_id:16,render_type:42,word03:15,word05:1,word07:13,word09:8,
     word0B:9,word0D:6,word0F:0,word11:1,byte13:50,child_ids:[17],payload:[]},
    {record_id:17,render_type:0,word03:16,word05:8,word07:8,word09:5,
     word0B:0,word0D:0,word0F:7,word11:7,byte13:88,child_ids:[],
     payload:[88,239,42,18,0,239,45]},
    {record_id:18,render_type:42,word03:17,word05:1,word07:8,word09:4,
     word0B:5,word0D:4,word0F:0,word11:2,byte13:50,child_ids:[19],payload:[]},
    {record_id:19,render_type:0,word03:18,word05:5,word07:4,word09:2,
     word0B:0,word0D:0,word0F:1,word11:1,byte13:50,child_ids:[],payload:[50]},
  ]);
expectEqual('browser selects translated power construction',
  mp.constructedProgramForExpression('X^2').nodes,
  rom.constructSettledPowerProgram({base:[0x58], exponent:[0x32]}, 1, font).nodes);
expectEqual('browser parses powers right associatively',
  mp.constructedProgramForExpression('2^X^2').nodes,
  rom.constructSettledPowerProgram({
    base:[0x32], exponent:{base:[0x58], exponent:[0x32]},
  }, 1, font).nodes);
expectEqual('power browser path labels translated construction',
  mp.generatedForExpression('X^2').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated power construction');
for (const expression of ['X^', '^2', 'X^^2', 'X^(2)', 'X+1^2'])
  expectEqual(`${expression} is outside the translated power grammar`,
    mp.constructedProgramForExpression(expression), null);
expectThrows('power constructor rejects an empty base', RangeError,
  () => rom.constructSettledPowerProgram({base:[], exponent:[0x32]}, 1, font));
expectThrows('power constructor rejects an empty exponent', RangeError,
  () => rom.constructSettledPowerProgram({base:[0x58], exponent:[]}, 1, font));
expectThrows('power constructor detects record ID exhaustion', RangeError,
  () => rom.constructSettledPowerProgram(
    {base:[0x58], exponent:[0x32]}, 0xffff, font));
for (const [expression,nodes,entryId] of browserProgramCases) {
  const fixture = recordPrograms.programs[expression];
  expectEqual(`${expression} browser fixture entry`, fixture.entry_id, entryId);
  const generated = mp.generatedForExpression(expression);
  const fixtureOperations = rom.executeSettledRecordProgram(fixture.nodes, fixture.entry_id, {
    origin:fixture.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const expectedOperations = rom.executeSettledRecordProgram(nodes, entryId, {
    glyphAdvance:settledGlyphAdvance,
  });
  expectEqual(`${expression} browser fixture operation stream`,
    fixtureOperations, expectedOperations);
  expectEqual(`${expression} browser executor final pixels`, generated.final,
    rom.rasterizeSettledOperations(
      expectedOperations, font).grid.map(row => row.join('')));
  expectEqual(`${expression} browser executor write count`, generated.events.length,
    rom.rasterizeSettledOperations(expectedOperations, font).writes.length);
}
expectEqual('absolute browser path labels translated construction',
  mp.generatedForExpression('abs(X-3)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated construction');
expectEqual('remaining browser paths label captured record input',
  mp.generatedForExpression('sqrt(X^2+1)').programSource,
  'captured settled record snapshot');
expectEqual('arbitrary expression has no captured record program',
  mp.generatedForExpression('1//(2//3)'), null);

expectEqual('34:6143 keeps incoming-A-dependent type 1F explicit',
  rom.executeSettledRecordGraph([settledRecord(1,0x1f)],1), [{
    kind:'unresolved-render',
    missing:'incoming A and the selected 34:6143 branch',
    routine:'34:6143', origin:{x:0,y:0}, recordId:1, recordType:0x1f, depth:1,
  }]);
expectEqual('34:62A1 radical primitive order', rom.settledRadicalOperations(12, 0x1d), [
  {kind:'bitmap', x:0, y:5, width:5, height:7,
   rows:[0x04,0x04,0x04,0x04,0x14,0x0c,0x04],
   routine:'34:62A4 → 34:62D0 → 34:630C'},
  {kind:'line', axis:'vertical', from:{x:2,y:1}, to:{x:2,y:4},
   routine:'34:62AE → 34:5D96'},
  {kind:'child-select', index:1, routine:'34:62B1 → 34:6D4B'},
  {kind:'line', axis:'horizontal', from:{x:2,y:0}, to:{x:0x20,y:0},
   routine:'34:62C3 → 34:5DA6'},
  {kind:'child', index:1, routine:'34:62C6 → 34:660A'},
]);
expectEqual('34:622F integral primitive order', rom.settledIntegralOperations(0x17), [
  {kind:'line', axis:'vertical', from:{x:2,y:1}, to:{x:2,y:0x15},
   routine:'34:6239 → 34:5D96'},
  {kind:'point', x:3, y:0, routine:'34:6244 → 34:5E85'},
  {kind:'point', x:4, y:1, routine:'34:624B → 34:5E85'},
  {kind:'point', x:1, y:0x16, routine:'34:6257 → 34:5E85'},
  {kind:'point', x:0, y:0x15, routine:'34:625D → 34:5E85'},
]);

for (const [expression, record] of Object.entries(drawOrder.scenarios)) {
  const final = mp.traceFrame(record, record.events.length)
    .map(row => row.map(pixel => pixel ? '1' : '0').join(''));
  if (JSON.stringify(final) !== JSON.stringify(record.final))
    throw new Error(`${expression}: captured LCD timeline does not reach its final grid`);
  const initial = mp.traceFrame(record, 0)
    .map(row => row.map(pixel => pixel ? '1' : '0').join(''));
  if (JSON.stringify(initial) !== JSON.stringify(record.initial))
    throw new Error(`${expression}: captured LCD timeline does not preserve its initial grid`);
}

const CELL_CASES = [
  [[0xFC, 0x3C], { kind: 'glyph', code: 5 }],
  [[0xFC, 0x41], { kind: 'familyToken', d: 0xFC, e: 0x41 }],
  [[0xFE, 0x7D], { kind: 'glyph', code: 0 }],
  [[0xFE, 0xA7], { kind: 'delimiterFamily', d: 0xFE, e: 0xA7, family: 0x18, index: 0 }],
  [[0xFB, 0xCA], { kind: 'inlineString', d: 0xFB, e: 0xCA }],
  [[0xFB, 0xC8], { kind: 'runtimeConditional', d: 0xFB, e: 0xC8, condition: 'bit 0,H' }],
  [[0x1F, 0], { kind: 'marker', what: 'cursor/answer-area (no draw)' }],
  [[0x82, 0x42], { kind: 'colGlyph', index: 4 }],
  [[0xFF, 0], { kind: 'marker', what: 'terminator' }],
  [[3, 0x42], { kind: 'glyph', code: 3 }],
  [[0, 0x55], { kind: 'specialAction', d: 0, e: 0x55 }],
];
for (const [[d, e], expected] of CELL_CASES) {
  const actual = resolveCell(d, e);
  if (JSON.stringify(actual) !== JSON.stringify(expected))
    throw new Error(`cell ${d.toString(16)}:${e.toString(16)}: ${JSON.stringify(actual)}`);
}

function dims(box) {
  const lines = mp.toText(box).split('\n');
  const widths = lines.map(line => line.length);
  if (new Set(widths).size > 1) throw new Error(`ragged rows: ${widths.join(',')}`);
  return { h: lines.length, w: widths[0] || 0 };
}

// Deterministic PRNG so failures reproduce (no Math.random in CI).
let seed = 0x2545f491;
const rnd = () => {
  seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; seed >>>= 0;
  return seed / 0x100000000;
};
const pick = a => a[Math.floor(rnd() * a.length)];

const ATOMS = ['1', '2', '3', '42', '0.5', 'X', 'A', 'B', 'pi', 'N'];
function gen(depth) {
  if (depth <= 0) return pick(ATOMS);
  switch (Math.floor(rnd() * 9)) {
    case 0: return `${gen(depth - 1)}+${gen(depth - 1)}`;
    case 1: return `${gen(depth - 1)}-${gen(depth - 1)}`;
    case 2: return `${gen(depth - 1)}*${gen(depth - 1)}`;
    case 3: return `${gen(depth - 1)}/${gen(depth - 1)}`;
    case 4: return `${gen(depth - 1)}^${gen(depth - 1)}`;
    case 5: return `(${gen(depth - 1)})`;
    case 6: return `sqrt(${gen(depth - 1)})`;
    case 7: return `int(${pick(ATOMS)},${pick(ATOMS)},${gen(depth - 1)},X)`;
    default: return `${gen(depth - 1)}${gen(depth - 1)}`;  // implicit multiply
  }
}

// Common hand-written expressions (the realistic homescreen / template cases).
const CORPUS = [
  '1/2', 'X^2', '(A+B)/C', '1/(2/3)', 'sqrt(X^2+1)', 'int(1,2,X^2,X)',
  'int(1,2,(1/2)X,X)', '(int(1,2,(1//2)X,X))+2', 'sqrt((X^2+1)/X)', 'X^2+2X+1', '(X+1)/(X-1)',
  '1/2+1/3', 'sqrt(2)/2', 'X^(1/2)', 'abs(X-3)', '2^X^2', '((1))', '',
];

let pass = 0, fail = 0;
const fails = [];
function check(expr) {
  try {
    const box = mp.parse(expr);
    const d = dims(box);
    if (expr !== '' && (d.h < 1 || d.w < 1)) throw new Error(`empty box ${d.w}x${d.h}`);
    if (d.h > 256 || d.w > 2000) throw new Error(`box too large ${d.w}x${d.h}`);
    for (const [index, mark] of mp.penLog(box).entries()) {
      const mw = mark.w || 1, mh = mark.h || 1;
      if (mark.x < 0 || mark.y < 0 || mark.x + mw > d.w || mark.y + mh > d.h)
        throw new Error(`mark ${index} outside ${d.w}x${d.h}`);
    }
    pass++;
  } catch (e) {
    fail++;
    if (fails.length < 20) fails.push(`${JSON.stringify(expr)}: ${e.message}`);
  }
}

const N = parseInt(process.argv[2] || '5000', 10);
CORPUS.forEach(check);
for (let k = 0; k < N; k++) check(gen(1 + Math.floor(rnd() * 4)));

console.log(`corpus+fuzz: ${pass} passed, ${fail} failed (of ${pass + fail})`);
if (fails.length) {
  console.log('failures:');
  fails.forEach(f => console.log('  ' + f));
  process.exit(1);
}
