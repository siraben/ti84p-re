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
const exponentialLogBaseOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-exponential-logbase-oracles.json')));
const matrixOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-matrix-oracles.json')));
const groupingOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-grouping-oracles.json')));

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
   retainUnchanged:true,
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
  {word05:6,word07:0x10,word09:0x2a,word11:0x0301,byte13:2},
  [0x11,0x13,0x14,0x15,0x16,0x17]);
expectEqual('33:4F23 nonsquare matrix product', rom.matrixChildCount(matrixRoot), 6);
const matrixGraph = rom.executeSettledRecordGraph([
  matrixRoot,
  settledRecord(0x11,0,{word0B:6,word0D:2}),
  settledRecord(0x13,0,{word0B:18,word0D:2}),
  settledRecord(0x14,0,{word0B:30,word0D:2}),
  settledRecord(0x15,0,{word0B:6,word0D:9}),
  settledRecord(0x16,0,{word0B:18,word0D:9}),
  settledRecord(0x17,0,{word0B:30,word0D:9}),
], 0x10, {renderLeaf:leafGlyph});
expectEqual('settled matrix brackets surround row-major children',
  matrixGraph.map(op => [op.kind,op.recordId,op.depth,
    op.x === undefined ? op.from.x : op.x,op.y === undefined ? op.from.y : op.y]), [
    ['line',0x10,1,2,0], ['point',0x10,1,3,0], ['point',0x10,1,3,15],
    ['glyph',0x11,0,6,2], ['glyph',0x13,0,18,2], ['glyph',0x14,0,30,2],
    ['glyph',0x15,0,6,9], ['glyph',0x16,0,18,9], ['glyph',0x17,0,30,9],
    ['line',0x10,1,38,0], ['point',0x10,1,37,0], ['point',0x10,1,37,15],
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
  settledRecord(0x12,0,{word05:19,word07:33,word09:9,word11:6},[],
    [0xef,0x29,0x13,0x00,0xef,0x2d]),
  settledRecord(0x13,0x29,{word05:3,word07:19,word09:33,word0B:9},
    [0x14,0x15,0x16,0x17]),
  settledRecord(0x14,1,{word05:5,word07:4,word09:2,word0D:14,word11:1},[],[0x4e]),
  settledRecord(0x15,0,{word05:5,word07:4,word09:2,word0B:8,word0D:14,word11:1},[],[0x31]),
  settledRecord(0x16,0,{word05:5,word07:4,word09:2,word0B:4,word11:1},[],[0x33]),
  settledRecord(0x17,0,{word05:10,word07:10,word09:6,word0B:18,word0D:3,word11:7},[],
    [0x4e,0xef,0x2a,0x18,0x00,0xef,0x2d]),
  settledRecord(0x18,0x2a,{word05:1,word07:10,word09:4,word0B:6,word0D:6,word11:2},[0x19]),
  settledRecord(0x19,0,{word07:4,word09:2,word11:1},[],[0x32]),
];
expectEqual('settled summation program independently reproduces trace glyph order',
  settledGlyphStream(summationProgram,0x12), [
    [0xc6,3,6,0], [0x4e,0,14,1], [0x3d,4,14,1], [0x31,8,14,1],
    [0x33,4,0,1], [0x4e,18,6,0], [0x32,24,3,1],
  ]);

const nderivProgram = [
  settledRecord(0x11,0,{word05:13,word07:47,word09:6,word11:6},[],
    [0xef,0x23,0x12,0x00,0xef,0x2d]),
  settledRecord(0x12,0x23,{word05:3,word07:13,word09:47,word0B:6},[0x13,0x14,0x15]),
  settledRecord(0x13,1,{word05:5,word07:4,word09:2,word0B:5,word0D:8,word11:1},[],[0x58]),
  settledRecord(0x14,0,{word05:10,word07:10,word09:6,word0B:16,word11:7},[],
    [0x58,0xef,0x2a,0x16,0x00,0xef,0x2d]),
  settledRecord(0x16,0x2a,{word07:10,word09:4,word0B:6,word0D:6},[0x17]),
  settledRecord(0x17,0,{word07:4,word09:2,word11:1},[],[0x32]),
  settledRecord(0x15,0,{word05:5,word07:4,word09:2,word0B:43,word0D:8,word11:1},[],[0x31]),
];
expectEqual('settled nDeriv program independently reproduces trace glyph order',
  settledGlyphStream(nderivProgram,0x11), [
    [0x64,3,0,1], [0x64,1,8,1], [0x58,5,8,1], [0x58,16,3,0],
    [0x32,22,0,1], [0x58,35,8,1], [0x3d,39,8,1], [0x31,43,8,1],
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
  ['summation',summationProgram,0x12,'34ced684d56f59e6cf109a6d63bd07e314a086392b1b8e6881e1bb159087c052'],
  ['nDeriv',nderivProgram,0x11,'f116d977a338a01cd1764a417eed93c5553771ee458ed7376a72cb347668c9f7'],
  ['nested integral/fraction',integralFractionProgram,0x07,'3e14504af269ef52a7d3032b2ab3f9c91460ffbc5c7f445f8d4b9aea9621d1aa'],
]) expectEqual(`settled ${name} independently reproduces final LCD pixels`,
                settledRasterHash(nodes,entryId), expected);
for (const [name,nodes,entryId,expected] of [
  ['absolute',absoluteProgram,0x0d,'5215280de472ff2d94dc2b158b2edf22820c906b895d6272b5e009c10f6ab997'],
  ['nth root',nthRootProgram,0x0e,'de981d526c703a91d101e260d6aed69d3f750a4526a7d4c01b9187c060132b31'],
  ['radical',radicalProgram,0x0f,'4ab47d3ecc113ccf67f1c120e37e5d64ed697f5b6698c4f124274765b17f48fe'],
  ['summation',summationProgram,0x12,'abcbf43abbeb54c298f870ff06ae0d1aef4ed93155708a9dc89978d1c97c4cb6'],
  ['nDeriv',nderivProgram,0x11,'27227b09148e4ceabb91f49990e278fba214c9f2b95ddf7456c988d6b212fd69'],
  ['nested integral/fraction',integralFractionProgram,0x07,'f82758d431e616be056a6748e332b7dd5d859cb948f2192bdc99e7e14d38e237'],
]) expectEqual(`settled ${name} independently reproduces LCD write order`,
                settledWriteHash(nodes,entryId,true), expected);
for (const [name,nodes,entryId,expected] of [
  ['absolute',absoluteProgram,0x0d,'0c11578979dbf5a5c6ef423dfbc4e1a465322e5e639257ccc44e69f910cdcf99'],
  ['nth root',nthRootProgram,0x0e,'7b9fa6dd5d22b6e68570c45970764516b985780ce5de55c1945ac0b937ce99e5'],
  ['radical',radicalProgram,0x0f,'56cd3a3c3b9eea8c2b99e96abee7d7175d5c3fd1e7930c4319aa1d464cc84750'],
  ['summation',summationProgram,0x12,'59cb61779aac701b6e37c3a659e9c30acbfdff194b4421340225bc176f1f72bb'],
  ['nDeriv',nderivProgram,0x11,'62841da8f502b1d17ceb34f93ea183f4e22f389d410655f0f5cc9b81799b8f77'],
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
expectEqual('34:5935 maps the radical token through 34:594D',
  rom.settledStructuralTokenType(0x00,0xbc), 0x27);
expectEqual('34:5996 selects the radical metadata row',
  rom.settledRecordMetadata(0x27), [0x03,0x01,0x00,0x00,0x00]);
expectEqual('34:5935 maps the nth-root token through 34:594D',
  rom.settledStructuralTokenType(0x00,0xf1), 0x24);
expectEqual('34:5996 selects the nth-root metadata row',
  rom.settledRecordMetadata(0x24), [0x01,0x01,0x02,0x00,0x00]);
expectEqual('34:5935 maps the stacked-fraction token through 34:594D',
  rom.settledStructuralTokenType(0xef,0x2e), 0x20);
expectEqual('34:5996 selects the stacked-fraction metadata row',
  rom.settledRecordMetadata(0x20), [0x02,0x01,0x02,0x00,0x00]);
expectEqual('34:5935 maps the integral token through 34:594D',
  rom.settledStructuralTokenType(0x00,0x24), 0x22);
expectEqual('34:5996 selects the integral metadata row',
  rom.settledRecordMetadata(0x22), [0x04,0x03,0x04,0x01,0x02]);
expectEqual('34:5935 maps the summation token through 34:594D',
  rom.settledStructuralTokenType(0xef,0x33), 0x29);
expectEqual('34:5996 selects the summation metadata row',
  rom.settledRecordMetadata(0x29), [0x04,0x04,0x01,0x02,0x03]);
expectEqual('34:5935 maps the nDeriv token through 34:594D',
  rom.settledStructuralTokenType(0x00,0x25), 0x23);
expectEqual('34:5996 selects the nDeriv metadata row',
  rom.settledRecordMetadata(0x23), [0x04,0x02,0x01,0x03,0x00]);
expectEqual('34:5935 maps the e-power token through 34:594D',
  rom.settledStructuralTokenType(0x00,0xbf), 0x25);
expectEqual('34:5935 maps the ten-power token through 34:594D',
  rom.settledStructuralTokenType(0x00,0xc1), 0x26);
expectEqual('34:5935 maps the log-base token through 34:594D',
  rom.settledStructuralTokenType(0xef,0x34), 0x28);
expectEqual('34:5996 selects the exponential metadata rows',
  [rom.settledRecordMetadata(0x25),rom.settledRecordMetadata(0x26)],
  [[0x03,0x01,0x00,0x00,0x00],[0x03,0x01,0x00,0x00,0x00]]);
expectEqual('34:5996 selects the log-base metadata row',
  rom.settledRecordMetadata(0x28), [0x04,0x02,0x01,0x00,0x00]);
expectEqual('34:5935 maps the matrix token through 34:594D',
  rom.settledStructuralTokenType(0xef,0x2b), 0x2b);
expectEqual('34:5996 selects the matrix metadata row',
  rom.settledRecordMetadata(0x2b), [0x06,0x10,0xda,0xdb,0x9c]);
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
for (const oracle of groupingOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} independently constructs the grouping graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(program.nodes, program.entry_id, {
    origin:program.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const writes = rom.rasterizeSettledOperations(operations, font).writes;
  expectEqual(`${oracle.expression} reproduces accepted grouping write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} reproduces accepted grouping write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
  const browser = mp.constructedProgramForExpression(oracle.expression);
  if (!browser)
    throw new Error(`${oracle.expression} has no browser-constructed record program`);
  const expectedBrowser = rom.constructSettledExpressionProgram(oracle.spec, 1, font);
  expectEqual(`${oracle.expression} browser grammar preserves the grouping AST`,
    browser.nodes, expectedBrowser.nodes);
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
for (const oracle of constructionOracles.composition_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of constructionOracles.nth_root_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of constructionOracles.fraction_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of constructionOracles.integral_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of constructionOracles.summation_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of constructionOracles.nderiv_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of constructionOracles.multiarg_fraction_numerator_cases) {
  expectEqual(`${oracle.expression} trace graph decodes to the asserted expression`,
    oracle.trace_decoded_spec, oracle.spec);
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of exponentialLogBaseOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
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
for (const oracle of matrixOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} independently constructs the fresh TilEm graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.display_origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(program.nodes, program.entry_id, {
    origin:program.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const writes = rom.rasterizeSettledOperations(operations, font).writes;
  expectEqual(`${oracle.expression} independently reproduces synchronous accepted-write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} independently reproduces synchronous accepted-write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
}
expectEqual('browser selects translated absolute record construction',
  mp.constructedProgramForExpression('abs(X-3)').nodes,
  rom.constructSettledAbsoluteProgram([0x58,0x71,0x33]).nodes);
expectEqual('arbitrary flat absolute expression constructs from its own tokens',
  mp.constructedProgramForExpression('abs(A+12)').nodes[2].payload,
  [0x41,0x70,0x31,0x32]);
expectEqual('browser composes translated radical and power construction',
  mp.constructedProgramForExpression('sqrt(X^2+1)').nodes,
  rom.constructSettledRadicalProgram({
    kind:'sequence',
    parts:[{kind:'power',base:[0x58],exponent:[0x32]},[0x70,0x31]],
  }, 1, font).nodes);
expectEqual('browser constructs a radical inside a raised exponent',
  mp.constructedProgramForExpression('X^sqrt(2)').nodes,
  rom.constructSettledExpressionProgram({
    kind:'power', base:[0x58],
    exponent:{kind:'radical',radicand:[0x32]},
  }, 1, font).nodes);
expectEqual('browser constructs nested radicals',
  mp.constructedProgramForExpression('sqrt(sqrt(2))').nodes,
  rom.constructSettledRadicalProgram(
    {kind:'radical',radicand:[0x32]}, 1, font).nodes);
expectEqual('browser constructs a powered nth-root radicand',
  mp.constructedProgramForExpression('nthroot(3,X^2)').nodes,
  rom.constructSettledNthRootProgram(
    [0x33], {kind:'power',base:[0x58],exponent:[0x32]}, 1, font).nodes);
expectEqual('browser constructs an nth root inside a raised exponent',
  mp.constructedProgramForExpression('X^nthroot(3,2)').nodes,
  rom.constructSettledExpressionProgram({
    kind:'power', base:[0x58],
    exponent:{kind:'nthRoot',index:[0x33],radicand:[0x32]},
  }, 1, font).nodes);
expectEqual('browser constructs a stacked fraction from its operands',
  mp.constructedProgramForExpression('12//X').nodes,
  rom.constructSettledFractionProgram([0x31,0x32], [0x58], 1, font).nodes);
expectEqual('browser constructs a structural fraction numerator in ROM ID order',
  mp.constructedProgramForExpression('X^2//3').nodes,
  rom.constructSettledFractionProgram(
    {kind:'power',base:[0x58],exponent:[0x32]}, [0x33], 1, font).nodes);
expectEqual('browser constructs a structural fraction denominator',
  mp.constructedProgramForExpression('3//X^2').nodes,
  rom.constructSettledFractionProgram(
    [0x33], {kind:'power',base:[0x58],exponent:[0x32]}, 1, font).nodes);
expectEqual('browser constructs a mixed structural fraction numerator',
  mp.constructedProgramForExpression('(X^2+1)//3').nodes,
  rom.constructSettledFractionProgram({
    kind:'sequence',
    parts:[{kind:'power',base:[0x58],exponent:[0x32]},[0x70,0x31]],
  }, [0x33], 1, font).nodes);
expectEqual('browser constructs a fraction nested in the denominator',
  mp.constructedProgramForExpression('1//(2//3)').nodes,
  rom.constructSettledFractionProgram(
    [0x31], {kind:'fraction',numerator:[0x32],denominator:[0x33]}, 1, font).nodes);
expectEqual('browser constructs a fraction nested in the numerator',
  mp.constructedProgramForExpression('(1//2)//3').nodes,
  rom.constructSettledFractionProgram(
    {kind:'fraction',numerator:[0x31],denominator:[0x32]}, [0x33], 1, font).nodes);
expectEqual('browser composes a fraction inside a radical',
  mp.constructedProgramForExpression('sqrt(1//2)').nodes,
  rom.constructSettledRadicalProgram(
    {kind:'fraction',numerator:[0x31],denominator:[0x32]}, 1, font).nodes);
expectEqual('browser composes a fraction inside a raised exponent',
  mp.constructedProgramForExpression('X^(1//2)').nodes,
  rom.constructSettledPowerProgram({
    base:[0x58],
    exponent:{kind:'fraction',numerator:[0x31],denominator:[0x32]},
  }, 1, font).nodes);
expectEqual('browser constructs a radical fraction numerator in ROM ID order',
  mp.constructedProgramForExpression('sqrt(2)//3').nodes,
  rom.constructSettledFractionProgram(
    {kind:'radical',radicand:[0x32]}, [0x33], 1, font).nodes);
expectEqual('browser constructs an nth-root fraction numerator in ROM ID order',
  mp.constructedProgramForExpression('nthroot(3,2)//3').nodes,
  rom.constructSettledFractionProgram(
    {kind:'nthRoot',index:[0x33],radicand:[0x32]}, [0x33], 1, font).nodes);
expectEqual('browser constructs a four-argument integral in ROM ID order',
  mp.constructedProgramForExpression('int(1,2,X,X)').nodes,
  rom.constructSettledIntegralProgram(
    [0x31], [0x32], [0x58], [0x58], 1, font).nodes);
expectEqual('browser constructs implicit multiplication after a fraction',
  mp.constructedProgramForExpression('int(1,2,(1//2)X,X)').nodes,
  rom.constructSettledIntegralProgram([0x31], [0x32], {
    kind:'sequence', parts:[
      {kind:'fraction',numerator:[0x31],denominator:[0x32]}, [0x58],
    ],
  }, [0x58], 1, font).nodes);
expectEqual('browser constructs structural integral bounds',
  mp.constructedProgramForExpression('int(sqrt(2),sqrt(3),X,X)').nodes,
  rom.constructSettledIntegralProgram(
    {kind:'radical',radicand:[0x32]},
    {kind:'radical',radicand:[0x33]}, [0x58], [0x58], 1, font).nodes);
expectEqual('browser recursively reserves nested integral arguments',
  mp.constructedProgramForExpression('int(1,2,int(3,4,X,X),X)').nodes,
  rom.constructSettledIntegralProgram([0x31], [0x32], {
    kind:'integral', lower:[0x33], upper:[0x34], body:[0x58], variable:[0x58],
  }, [0x58], 1, font).nodes);
expectEqual('browser constructs all four summation fields from tokens',
  mp.constructedProgramForExpression('sum(N,1,3,N^2)').nodes,
  rom.constructSettledSummationProgram(
    [0x4e], [0x31], [0x33],
    {kind:'power',base:[0x4e],exponent:[0x32]}, 1, font).nodes);
expectEqual('constructed summation leaves no empty-slot placeholder',
  settledGlyphStream(
    mp.constructedProgramForExpression('sum(N,1,3,N^2)').nodes, 1)
    .map(([code]) => code).includes(0xf7), false);
expectEqual('browser constructs unequal-width summation bounds',
  mp.constructedProgramForExpression('sum(N,12,3,N+12)').nodes,
  rom.constructSettledSummationProgram(
    [0x4e], [0x31,0x32], [0x33], [0x4e,0x70,0x31,0x32], 1, font).nodes);
expectEqual('browser constructs structural summation bounds',
  mp.constructedProgramForExpression('sum(N,1^2,2^2,N)').nodes,
  rom.constructSettledSummationProgram(
    [0x4e], {kind:'power',base:[0x31],exponent:[0x32]},
    {kind:'power',base:[0x32],exponent:[0x32]}, [0x4e], 1, font).nodes);
expectEqual('browser recursively reserves nested summation arguments',
  mp.constructedProgramForExpression('sum(N,1,3,sum(A,1,2,A))').nodes,
  rom.constructSettledSummationProgram([0x4e], [0x31], [0x33], {
    kind:'summation', variable:[0x41], lower:[0x31], upper:[0x32], body:[0x41],
  }, 1, font).nodes);
expectEqual('browser constructs all three nDeriv fields from tokens',
  mp.constructedProgramForExpression('nDeriv(X^2,X,1)').nodes,
  rom.constructSettledNDerivProgram(
    [0x58], {kind:'power',base:[0x58],exponent:[0x32]}, [0x31], 1, font).nodes);
expectEqual('browser preserves an ordinary X in the nDeriv body leaf',
  mp.constructedProgramForExpression('nDeriv(X,X,1)').nodes
    .find(node => node.record_id === 4).payload, [0x58]);
expectEqual('browser constructs structural nDeriv bodies',
  mp.constructedProgramForExpression('nDeriv(sqrt(X),X,2)').nodes,
  rom.constructSettledNDerivProgram(
    [0x58], {kind:'radical',radicand:[0x58]}, [0x32], 1, font).nodes);
expectEqual('browser recursively reserves nested nDeriv arguments',
  mp.constructedProgramForExpression('nDeriv(nDeriv(A^2,A,1),X,2)').nodes,
  rom.constructSettledNDerivProgram([0x58], {
    kind:'nDeriv',variable:[0x41],
    body:{kind:'power',base:[0x41],exponent:[0x32]},value:[0x31],
  }, [0x32], 1, font).nodes);
for (const oracle of constructionOracles.multiarg_fraction_numerator_cases)
  expectEqual(`${oracle.expression} browser constructs the trace-decoded graph`,
    mp.constructedProgramForExpression(oracle.expression).nodes,
    rom.constructSettledExpressionProgram(oracle.spec, 1, font).nodes);
for (const oracle of exponentialLogBaseOracles.cases)
  expectEqual(`${oracle.expression} browser constructs the trace-decoded graph`,
    mp.constructedProgramForExpression(oracle.expression).nodes,
    rom.constructSettledExpressionProgram(oracle.spec, 1, font).nodes);
for (const oracle of matrixOracles.cases)
  expectEqual(`${oracle.expression} browser constructs the trace-decoded graph`,
    mp.constructedProgramForExpression(oracle.expression).nodes,
    rom.constructSettledExpressionProgram(oracle.spec, 1, font).nodes);
expectEqual('browser places matrix results at the right-aligned LCD origin',
  mp.constructedProgramForExpression('matrix(2,3,4,-2,0,-7,8,8)').origin,
  {x:41,y:9});
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
for (const expression of ['X^', '^2', 'X^^2'])
  expectEqual(`${expression} is outside the translated power grammar`,
    mp.constructedProgramForExpression(expression), null);
if (!mp.constructedProgramForExpression('X^(2)'))
  throw new Error('grouped power exponent has no translated record program');
expectThrows('power constructor rejects an empty base', RangeError,
  () => rom.constructSettledPowerProgram({base:[], exponent:[0x32]}, 1, font));
expectThrows('power constructor rejects an empty exponent', RangeError,
  () => rom.constructSettledPowerProgram({base:[0x58], exponent:[]}, 1, font));
expectThrows('power constructor detects record ID exhaustion', RangeError,
  () => rom.constructSettledPowerProgram(
    {base:[0x58], exponent:[0x32]}, 0xffff, font));
const cyclicExpression = {kind:'radical'};
cyclicExpression.radicand = cyclicExpression;
expectThrows('compositional constructor rejects cyclic expressions', RangeError,
  () => rom.constructSettledExpressionProgram(cyclicExpression, 1, font));
expectThrows('compositional constructor rejects an empty sequence', RangeError,
  () => rom.constructSettledExpressionProgram({kind:'sequence',parts:[]}, 1, font));
expectThrows('compositional constructor rejects an empty radical', RangeError,
  () => rom.constructSettledRadicalProgram([], 1, font));
expectThrows('compositional constructor rejects an empty nth-root index', RangeError,
  () => rom.constructSettledNthRootProgram([], [0x32], 1, font));
expectThrows('compositional constructor rejects an empty nth-root radicand', RangeError,
  () => rom.constructSettledNthRootProgram([0x33], [], 1, font));
expectThrows('compositional constructor rejects an empty fraction numerator', RangeError,
  () => rom.constructSettledFractionProgram([], [0x32], 1, font));
expectThrows('compositional constructor rejects an empty fraction denominator', RangeError,
  () => rom.constructSettledFractionProgram([0x31], [], 1, font));
for (const [label,lower,upper,body,variable] of [
  ['lower bound',[],[0x32],[0x58],[0x58]],
  ['upper bound',[0x31],[],[0x58],[0x58]],
  ['body',[0x31],[0x32],[],[0x58]],
  ['variable',[0x31],[0x32],[0x58],[]],
]) expectThrows(`integral constructor rejects an empty ${label}`, RangeError,
  () => rom.constructSettledIntegralProgram(
    lower, upper, body, variable, 1, font));
expectThrows('integral constructor rejects a structural variable', RangeError,
  () => rom.constructSettledIntegralProgram(
    [0x31], [0x32], [0x58], {kind:'radical',radicand:[0x58]}, 1, font));
expectThrows('integral constructor detects record ID exhaustion', RangeError,
  () => rom.constructSettledIntegralProgram(
    [0x31], [0x32], [0x58], [0x58], 0xfffb, font));
expectThrows('integral constructor rejects overflowing body width', RangeError,
  () => rom.constructSettledIntegralProgram(
    [0x31], [0x32], new Array(10921).fill(0x58), [0x58], 1, font));
const cyclicIntegral = {kind:'integral',lower:[0x31],upper:[0x32],variable:[0x58]};
cyclicIntegral.body = cyclicIntegral;
expectThrows('integral constructor rejects nested cycles', RangeError,
  () => rom.constructSettledExpressionProgram(cyclicIntegral, 1, font));
for (const [label,variable,lower,upper,body] of [
  ['variable',[],[0x31],[0x33],[0x4e]],
  ['lower bound',[0x4e],[],[0x33],[0x4e]],
  ['upper bound',[0x4e],[0x31],[],[0x4e]],
  ['body',[0x4e],[0x31],[0x33],[]],
]) expectThrows(`summation constructor rejects an empty ${label}`, RangeError,
  () => rom.constructSettledSummationProgram(
    variable, lower, upper, body, 1, font));
expectThrows('summation constructor rejects a structural variable', RangeError,
  () => rom.constructSettledSummationProgram(
    {kind:'radical',radicand:[0x4e]}, [0x31], [0x33], [0x4e], 1, font));
expectThrows('summation constructor detects record ID exhaustion', RangeError,
  () => rom.constructSettledSummationProgram(
    [0x4e], [0x31], [0x33], [0x4e], 0xfffb, font));
expectThrows('summation constructor rejects overflowing body width', RangeError,
  () => rom.constructSettledSummationProgram(
    [0x4e], [0x31], [0x33], new Array(10921).fill(0x4e), 1, font));
const cyclicSummation = {
  kind:'summation',variable:[0x4e],lower:[0x31],upper:[0x33],
};
cyclicSummation.body = cyclicSummation;
expectThrows('summation constructor rejects nested cycles', RangeError,
  () => rom.constructSettledExpressionProgram(cyclicSummation, 1, font));
for (const [label,variable,body,value] of [
  ['variable',[],[0x58],[0x31]],
  ['body',[0x58],[],[0x31]],
  ['evaluation value',[0x58],[0x58],[]],
]) expectThrows(`nDeriv constructor rejects an empty ${label}`, RangeError,
  () => rom.constructSettledNDerivProgram(variable, body, value, 1, font));
expectThrows('nDeriv constructor rejects a structural variable', RangeError,
  () => rom.constructSettledNDerivProgram(
    {kind:'radical',radicand:[0x58]}, [0x58], [0x31], 1, font));
expectThrows('nDeriv constructor detects record ID exhaustion', RangeError,
  () => rom.constructSettledNDerivProgram(
    [0x58], [0x58], [0x31], 0xfffc, font));
expectThrows('nDeriv constructor rejects overflowing body width', RangeError,
  () => rom.constructSettledNDerivProgram(
    [0x58], new Array(10921).fill(0x58), [0x31], 1, font));
const cyclicNDeriv = {kind:'nDeriv',variable:[0x58],value:[0x31]};
cyclicNDeriv.body = cyclicNDeriv;
expectThrows('nDeriv constructor rejects nested cycles', RangeError,
  () => rom.constructSettledExpressionProgram(cyclicNDeriv, 1, font));
for (const expression of [
  'int(,2,X,X)', 'int(1,,X,X)', 'int(1,2,,X)', 'int(1,2,X,)',
  'int(1,2,X)', 'int(1,2,X,X', 'int(1,2,X,sqrt(X))',
]) expectEqual(`${expression} is outside the translated integral grammar`,
  mp.constructedProgramForExpression(expression), null);
for (const expression of [
  'sum(,1,3,N)', 'sum(N,,3,N)', 'sum(N,1,,N)', 'sum(N,1,3,)',
  'sum(N,1,3)', 'sum(N,1,3,N', 'sum(sqrt(N),1,3,N)',
]) expectEqual(`${expression} is outside the translated summation grammar`,
  mp.constructedProgramForExpression(expression), null);
for (const expression of [
  'nDeriv(,X,1)', 'nDeriv(X,,1)', 'nDeriv(X,X,)',
  'nDeriv(X,X)', 'nDeriv(X,X,1', 'nDeriv(X,sqrt(X),1)',
]) expectEqual(`${expression} is outside the translated nDeriv grammar`,
  mp.constructedProgramForExpression(expression), null);
expectThrows('matrix constructor rejects missing dimensions', RangeError,
  () => rom.constructSettledExpressionProgram({kind:'matrix'}, 1, font));
expectThrows('matrix constructor rejects an incomplete row-major payload', RangeError,
  () => rom.constructSettledExpressionProgram(
    {kind:'matrix',rows:2,columns:2,elements:[[0x31],[0x32]]}, 1, font));
expectThrows('matrix constructor rejects a count wider than byte13', RangeError,
  () => rom.constructSettledExpressionProgram({
    kind:'matrix',rows:16,columns:16,
    elements:Array.from({length:256}, () => [0x31]),
  }, 1, font));
for (const expression of [
  'matrix(0,1,1)', 'matrix(1,0,1)', 'matrix(2,2,1,2,3)',
  'matrix(2,2,1,2,3,4,5)', 'matrix(16,16,1)',
]) expectEqual(`${expression} is outside the translated matrix grammar`,
  mp.constructedProgramForExpression(expression), null);
expectThrows('compositional constructor rejects overflowing leaf metrics', RangeError,
  () => rom.constructSettledExpressionProgram(new Array(10923).fill(0x58), 1, font));
expectThrows('compositional constructor rejects record ID exhaustion', RangeError,
  () => rom.constructSettledRadicalProgram([0x32], 0xffff, font));
expectThrows('fraction constructor detects record ID exhaustion', RangeError,
  () => rom.constructSettledFractionProgram([0x31], [0x32], 0xfffd, font));
expectThrows('fraction constructor rejects overflowing child width', RangeError,
  () => rom.constructSettledFractionProgram(
    new Array(16384).fill(0x31), [0x32], 1, font));
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
  '34:4900, 34:5935, 34:7393, and 34:7609 translated absolute construction');
expectEqual('radical browser path labels translated construction',
  mp.generatedForExpression('sqrt(X^2+1)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated radical construction');
expectEqual('nth-root browser path labels translated construction',
  mp.generatedForExpression('nthroot(3,X+1)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated nth-root construction');
expectEqual('compositional browser path labels translated construction',
  mp.generatedForExpression('X^sqrt(2)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated power construction');
expectEqual('fraction browser path labels translated construction',
  mp.generatedForExpression('1//2').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated fraction construction');
expectEqual('integral browser path labels translated construction',
  mp.generatedForExpression('int(1,2,X,X)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated integral construction');
expectEqual('summation browser path labels translated construction',
  mp.generatedForExpression('sum(N,1,3,N^2)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated summation construction');
expectEqual('nDeriv browser path labels translated construction',
  mp.generatedForExpression('nDeriv(X^2,X,1)').programSource,
  '34:4900, 34:5935, 34:7393, and 34:7609 translated nDeriv construction');
if (!mp.generatedForExpression('A+(X)'))
  throw new Error('visible grouped expression has no generated LCD write stream');

for (const [label, expression] of mp.presets) {
  const program = mp.constructedProgramForExpression(expression);
  if (!program)
    throw new Error(`${label} (${expression}) has no constructed record program`);
  const generated = mp.generatedForExpression(expression);
  if (!generated || generated.width !== 96 || generated.height !== 64 ||
      generated.events.length === 0)
    throw new Error(`${label} (${expression}) has no pixel-level LCD write trace`);
  if (generated.events.some(event => !Array.isArray(event.pointer) ||
      !Array.isArray(event.changes) || !Number.isInteger(event.value)))
    throw new Error(`${label} (${expression}) has an incomplete LCD write event`);
  if (generated.operations.some(operation => operation.kind === 'glyph' &&
      operation.code === 0xf7))
    throw new Error(`${label} (${expression}) renders an empty-slot placeholder`);
  if (generated.operations.some(operation =>
      operation.kind.startsWith('unresolved')))
    throw new Error(`${label} (${expression}) has an unresolved render operation`);
}

expectEqual('34:6143 keeps incoming-A-dependent type 1F explicit',
  rom.executeSettledRecordGraph([settledRecord(1,0x1f)],1), [{
    kind:'unresolved-render',
    missing:'incoming A and the selected 34:6143 branch',
    routine:'34:6143', origin:{x:0,y:0}, recordId:1, recordType:0x1f, depth:1,
  }]);
expectEqual('34:62A1 radical primitive order', rom.settledRadicalOperations(12, 0x1d), [
  {kind:'bitmap', x:0, y:5, width:5, height:7,
   rows:[0x04,0x04,0x04,0x04,0x14,0x0c,0x04], retainUnchanged:true,
   routine:'34:62A4 → 34:62D0 → 34:630C'},
  {kind:'line', axis:'vertical', from:{x:2,y:1}, to:{x:2,y:4},
   routine:'34:62AE → 34:5D96'},
  {kind:'child-select', index:1, routine:'34:62B1 → 34:6D4B'},
  {kind:'line', axis:'horizontal', from:{x:2,y:0}, to:{x:0x20,y:0},
   routine:'34:62C3 → 34:5DA6'},
  {kind:'child', index:1, routine:'34:62C6 → 34:660A'},
]);
expectEqual('34:62D0 raised radical selects the final five bitmap rows',
  rom.settledRadicalOperations(7, 6, 1)[0], {
    kind:'bitmap', x:0, y:2, width:5, height:5,
    rows:[0x04,0x04,0x14,0x0c,0x04], retainUnchanged:true,
    routine:'34:62A4 → 34:62D0 → 34:630C',
  });
const raisedRadicalBitmap = rom.settledRadicalOperations(7, 6, 1)[0];
const raisedRadicalInitial = Array.from({length:64}, () => new Array(96).fill(0));
for (let row = 0; row < raisedRadicalBitmap.height; row++)
  for (let column = 0; column < raisedRadicalBitmap.width; column++)
    raisedRadicalInitial[raisedRadicalBitmap.y + row][column] =
      (raisedRadicalBitmap.rows[row] >> (raisedRadicalBitmap.width - 1 - column)) & 1;
const unchangedRadicalWrites = rom.rasterizeSettledOperations(
  [raisedRadicalBitmap], font, {initialGrid:raisedRadicalInitial}).writes;
expectEqual('34:630C preserves accepted unchanged raised-radical writes',
  unchangedRadicalWrites.map(write => [write.pointer,write.value,write.changes]), [
    [[0,2],0x20,[]], [[0,3],0x20,[]], [[0,4],0xa0,[]],
    [[0,5],0x60,[]], [[0,6],0x20,[]],
  ]);
expectEqual('34:62D0 raised nth root selects the final five bitmap rows',
  rom.settledNthRootOperations(4, 4, 9, 1)[1], {
    kind:'bitmap', x:3, y:4, width:5, height:5,
    rows:[0x04,0x04,0x14,0x0c,0x04], retainUnchanged:true,
    routine:'34:6321 → 34:62D0 → 34:630C',
  });
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
