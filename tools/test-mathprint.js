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
const tokenStrings = JSON.parse(fs.readFileSync(
  path.join(root, 'web', 'mathprint', 'token-strings.json')));
rom.setSettledTokenStrings(tokenStrings);
const layout = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'layout.json')));
mp.setLayout(layout);
const drawOrder = JSON.parse(fs.readFileSync(path.join(root, 'web', 'mathprint', 'draw-order.json')));
const recordPrograms = JSON.parse(fs.readFileSync(
  path.join(root, 'web', 'mathprint', 'record-programs.json')));
const constructionOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-construction-oracles.json')));
const exponentialLogBaseOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-exponential-logbase-oracles.json')));
const nestedBaselineOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-nested-baseline-oracles.json')));
const matrixOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-matrix-oracles.json')));
const matrixBaselineOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-matrix-baseline-oracles.json')));
const liveEditorOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-live-editor-oracles.json')));
const editorGapOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-editor-gap-oracles.json')));
const editorMutationOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-editor-mutation-oracles.json')));
const editorStructuralMutationOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools',
    'mathprint-editor-structural-mutation-oracles.json')));
const editorTemplateBoundaryOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools',
    'mathprint-editor-template-boundary-oracles.json')));
const editorNavigationOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-editor-navigation-oracles.json')));
const editorStructuralNavigationOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools',
    'mathprint-editor-structural-navigation-oracles.json')));
const editorExtraStructuralNavigationOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools',
    'mathprint-editor-extra-structural-navigation-oracles.json')));
const editorSummationFillOracle = JSON.parse(fs.readFileSync(
  path.join(root, 'tools',
    'mathprint-editor-summation-fill-oracle.json')));
const editorDeletionOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-editor-deletion-oracles.json')));
const editorStructuralDeletionOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools',
    'mathprint-editor-structural-deletion-oracles.json')));
const groupingOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-grouping-oracles.json')));
const structuralBaseOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-structural-base-oracles.json')));
const namedTokenOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-named-token-oracles.json')));
const twoByteTokenOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-two-byte-token-oracles.json')));
const editorOverflowOracle = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-editor-overflow-oracle.json')));
const radicalViewportOracle = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-radical-viewport-oracles.json'))).cases[0];
const listOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-list-oracles.json')));
const verticalViewportOracle = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-vertical-viewport-oracle.json'))).cases[0];
const combinedViewportOracle = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-combined-viewport-oracle.json')));
const yEquSelectionOracle = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-yequ-selection-oracle.json')));

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

function packedLcdBytes(grid) {
  return Buffer.from(grid.flatMap(row => {
    if (!Array.isArray(row) || row.length % 8)
      throw new Error('LCD grid rows must be byte-aligned');
    const bytes = [];
    for (let x = 0; x < row.length; x += 8) {
      let value = 0;
      for (let bit = 0; bit < 8; bit++) value |= row[x + bit] << (7 - bit);
      bytes.push(value);
    }
    return bytes;
  }));
}

function cropInk(grid) {
  const rows = grid.map(row => Array.from(row, Number));
  const occupiedRows = rows
    .map((row, y) => row.some(Boolean) ? y : -1)
    .filter(y => y >= 0);
  if (!occupiedRows.length) return [[0]];
  const top = occupiedRows[0];
  const bottom = occupiedRows[occupiedRows.length - 1] + 1;
  const occupiedColumns = rows[0].map((_, x) =>
    rows.slice(top,bottom).some(row => row[x]) ? x : -1).filter(x => x >= 0);
  const left = occupiedColumns[0];
  const right = occupiedColumns[occupiedColumns.length - 1] + 1;
  return rows.slice(top,bottom).map(row => row.slice(left,right));
}

// Execute the closed action-controller instructions from pinned page-39 byte
// spans. The interpreter intentionally stops at the open row walker, wide-list
// body, argument-layout entry, or row-token tail. When the ignored local ROM is
// available, first prove that these spans came from the pinned OS image.
const controllerRomSpans = [
  {address:0x50a1, bytes:Buffer.from(
    '324d84cd6751214d843520f7c34754', 'hex')},
  {address:0x51ee, bytes:Buffer.from('c34754', 'hex')},
  {address:0x51f1, bytes:Buffer.from(
    'fe03c2a55221e0857eb7203efdcb1d4620eb3ae285fe08daa150', 'hex')},
  {address:0x52a2, bytes:Buffer.from('c34754', 'hex')},
  {address:0x52a5, bytes:Buffer.from(
    'fe04201821e0853ae2853d962805cd675118eafdcb1d4620e4c33e51', 'hex')},
];
const sharedMarkerRomSpan = {address:0x6143, bytes:Buffer.from(
  'fe27200e210c63fdcb445e2003210463185bfe22200b067cfdcb32d678cde13c' +
  'c9fe2128f1fe2506db28edfe2b2029ed5b20857ab720df7b0606fdcb445e2802' +
  '0608b830d106c1fdcb445e20cf3e0621c761fdcbff861817fe26061d28bafe28' +
  '066c28b8fe2906c628b221be613e08115f86d5cd941ae1cdcf3cc9', 'hex')};
const renderNestingTailRomSpans = [
  {address:0x61ce, bytes:Buffer.from(
    'fe2220067bfe03d8182efe27282afe212826fe2b2822fe282804fe2420067bfe' +
    '01c81814fe2320087bfe01c8fe021807fe2920077bfe04c0c3c979c9', 'hex')},
  {address:0x79c9, bytes:Buffer.from('e521158535e1c9', 'hex')},
];
const pointAddressRomSpan = {address:0x42b5, bytes:Buffer.from(
  'd521e442160078e6075f195e62cb38cb38cb3878f620324f843e3f91f68032' +
  '5184e67f87874f6f297b59195819d1c98040201008040201', 'hex')};
const pointAddressByteMap = new Map(Array.from(
  pointAddressRomSpan.bytes,
  (value, offset) => [pointAddressRomSpan.address + offset,value]));
const pointAddressByte = address => {
  if (!pointAddressByteMap.has(address))
    throw new Error(
      `point-address oracle reached unpinned byte 04:${address.toString(16)}`);
  return pointAddressByteMap.get(address);
};
const renderNestingTailByteMap = new Map(renderNestingTailRomSpans.flatMap(span =>
  Array.from(span.bytes,
    (value, offset) => [span.address + offset, value])));
const renderNestingTailByte = address => {
  if (!renderNestingTailByteMap.has(address))
    throw new Error(
      `render-nesting-tail oracle reached unpinned byte 34:${address.toString(16)}`);
  return renderNestingTailByteMap.get(address);
};

function runRawRenderNestingTail(renderType, childIndex, nestingCounter) {
  let pc = 0x61ce;
  let a = renderType, e = childIndex, hl = 0;
  let zero = false, carry = false, decremented = false;
  const stack = [];
  const memory = new Map([[0x8515,nestingCounter]]);
  const branchOutcomes = [];
  const signed = value => value < 0x80 ? value : value - 0x100;
  const finish = () => ({
    nestingCounterAfter:memory.get(0x8515),
    decremented,
    returnA:a,
    branchOutcomes,
  });
  for (let instructions = 0; instructions < 64; instructions++) {
    const opcode = renderNestingTailByte(pc);
    if (opcode === 0xfe) {
      const value = renderNestingTailByte(pc + 1);
      zero = a === value;
      carry = a < value;
      pc += 2;
    } else if (opcode === 0x20 || opcode === 0x28) {
      const taken = opcode === 0x20 ? !zero : zero;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken
        ? pc + 2 + signed(renderNestingTailByte(pc + 1))
        : pc + 2;
    } else if (opcode === 0x7b) {
      a = e; pc++;
    } else if (opcode === 0xd8 || opcode === 0xc8 || opcode === 0xc0) {
      const returned = opcode === 0xd8 ? carry : opcode === 0xc8 ? zero : !zero;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${returned ? 'returned' : 'fallthrough'}`);
      if (returned) return finish();
      pc++;
    } else if (opcode === 0x18) {
      pc += 2 + signed(renderNestingTailByte(pc + 1));
    } else if (opcode === 0xc3) {
      pc = renderNestingTailByte(pc + 1) |
        renderNestingTailByte(pc + 2) << 8;
    } else if (opcode === 0xe5) {
      stack.push(hl); pc++;
    } else if (opcode === 0x21) {
      hl = renderNestingTailByte(pc + 1) |
        renderNestingTailByte(pc + 2) << 8;
      pc += 3;
    } else if (opcode === 0x35) {
      const value = ((memory.get(hl) || 0) - 1) & 0xff;
      memory.set(hl,value);
      zero = value === 0;
      decremented = true;
      pc++;
    } else if (opcode === 0xe1) {
      hl = stack.pop(); pc++;
    } else if (opcode === 0xc9) {
      return finish();
    } else {
      throw new Error(
        `render-nesting-tail oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  throw new Error('render-nesting-tail oracle exceeded its instruction bound');
}

function runRawPointAddress(graphX, graphY) {
  let pc = 0x42b5, a = 0, b = graphX, c = graphY;
  let de = 0xa55a, hl = 0, carry = false;
  const stack = [];
  const memory = new Map();
  const word = address =>
    pointAddressByte(address) | pointAddressByte(address + 1) << 8;
  for (let instructions = 0; instructions < 64; instructions++) {
    const opcode = pointAddressByte(pc);
    if (opcode === 0xd5) {
      stack.push(de); pc++;
    } else if (opcode === 0x21) {
      hl = word(pc + 1); pc += 3;
    } else if (opcode === 0x16) {
      de = pointAddressByte(pc + 1) << 8 | de & 0xff; pc += 2;
    } else if (opcode === 0x78) {
      a = b; pc++;
    } else if (opcode === 0xe6) {
      a &= pointAddressByte(pc + 1); pc += 2;
    } else if (opcode === 0x5f) {
      de = de & 0xff00 | a; pc++;
    } else if (opcode === 0x19) {
      hl = (hl + de) & 0xffff; pc++;
    } else if (opcode === 0x5e) {
      de = de & 0xff00 | pointAddressByte(hl); pc++;
    } else if (opcode === 0x62) {
      hl = de & 0xff00 | hl & 0xff; pc++;
    } else if (opcode === 0xcb && pointAddressByte(pc + 1) === 0x38) {
      carry = (b & 1) !== 0; b >>>= 1; pc += 2;
    } else if (opcode === 0xf6) {
      a |= pointAddressByte(pc + 1); pc += 2;
    } else if (opcode === 0x32) {
      memory.set(word(pc + 1),a); pc += 3;
    } else if (opcode === 0x3e) {
      a = pointAddressByte(pc + 1); pc += 2;
    } else if (opcode === 0x91) {
      const result = a - c;
      carry = result < 0; a = result & 0xff; pc++;
    } else if (opcode === 0x87) {
      const result = a << 1;
      carry = result > 0xff; a = result & 0xff; pc++;
    } else if (opcode === 0x4f) {
      c = a; pc++;
    } else if (opcode === 0x6f) {
      hl = hl & 0xff00 | a; pc++;
    } else if (opcode === 0x29) {
      const result = hl << 1;
      carry = result > 0xffff; hl = result & 0xffff; pc++;
    } else if (opcode === 0x7b) {
      a = de & 0xff; pc++;
    } else if (opcode === 0x59) {
      de = de & 0xff00 | c; pc++;
    } else if (opcode === 0x58) {
      de = de & 0xff00 | b; pc++;
    } else if (opcode === 0xd1) {
      de = stack.pop(); pc++;
    } else if (opcode === 0xc9) {
      return {
        graphX,graphY,bitMask:a,byteColumn:b,
        displayRow:(memory.get(0x8451) || 0) & 0x7f,
        rowTimesFour:c,bufferOffset:hl,
        plotBufferAddress:(0x9872 + hl) & 0xffff,
        backupBufferAddress:(0x9340 + hl) & 0xffff,
        lcdColumnCommand:memory.get(0x844f),
        lcdRowCommand:memory.get(0x8451),
        routine:'04:42B5–42E3',
      };
    } else {
      throw new Error(
        `point-address oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  throw new Error('point-address oracle exceeded its instruction bound');
}
const overflowCueRomSpan = {address:0x66e9, bytes:Buffer.from(
  '3ae28521e08596fe08d83aa6973d6f26013e1f18052101013e1eed5b4b84' +
  '224b84cddb3fed534b84c9', 'hex')};
const overflowCueByteMap = new Map(Array.from(
  overflowCueRomSpan.bytes,
  (value, offset) => [overflowCueRomSpan.address + offset, value]));
const overflowCueByte = address => {
  if (!overflowCueByteMap.has(address))
    throw new Error(`overflow-cue oracle reached unpinned byte 39:${address.toString(16)}`);
  return overflowCueByteMap.get(address);
};
const editorViewportRomSpans = [
  {address:0x5dc2, bytes:Buffer.from('ed5b028eb7ed52c9', 'hex')},
  {address:0x5dca, bytes:Buffer.from('ed5bfc8d1600c9', 'hex')},
  {address:0x5f5d, bytes:Buffer.from(
    'd52a1685cdc25d3008010000ed43028e19110600fdcb445e20011b19d119cdca' +
    '5db7ed52d8ed5b028e1922028ec9', 'hex')},
  {address:0x5f8b, bytes:Buffer.from(
    'd52a1885ed5b048eb7ed523008010000ed43048e19110700fdcb445e20021b1b' +
    '19d119ed5bfd8d1600b7ed52d8ed5b048e1922048ec9', 'hex')},
];
const verticalCueRomSpans = [
  {page:0x34,address:0x6000,bytes:Buffer.from(
    'cda378c82a048e7cb52803efda53cda860c8efd753c9', 'hex')},
  {page:0x34,address:0x60a0,bytes:Buffer.from(
    '010700cd08781bc9cda060ebed5b048eb7ed52d2f85dbfc9', 'hex')},
  {page:0x35,address:0x7116,bytes:Buffer.from(
    '3afb8d32d8863e0432729bfdcb32fefdcbff86217d71e53a9a8521fa8dfe49' +
    '20057ed60718083afc8dcb3f86d60332d786e13e0432729b3e06115f86d5cd' +
    '941ae1ef3d54c93afb8d21fd8d86d60432d886fdcb32be3e0232019dfdcbff' +
    'c6fdcb05ce21827118af07081c3e00070000003e1c0800', 'hex')},
];
const glyphViewportRomSpan = {address:0x6c5f, bytes:Buffer.from(
  '2a1685ed5b028ecdbb213816e1e5ed5b168519e52a028ecdca5d1319d1cdbb21' +
  '3006d1e1f1d51824', 'hex')};
const runIndicatorRomSpan = {address:0x6bba, bytes:Buffer.from(
  'f33e2bcdc30cd3103614217784cb0e4e060816807acd895acdc920cdc30cdb11c' +
  'dc30cdb115f7acd895acdc9207bcb193804cb871802cbc7cdc30cd3111410d4c9',
  'hex')};
const editorViewportByteMap = new Map(editorViewportRomSpans.flatMap(span =>
  Array.from(span.bytes,
    (value, offset) => [span.address + offset, value])));
const editorViewportByte = address => {
  if (!editorViewportByteMap.has(address))
    throw new Error(
      `editor-viewport oracle reached unpinned byte 34:${address.toString(16)}`);
  return editorViewportByteMap.get(address);
};
const recordCapacityRomSpans = [
  {address:0x4868, bytes:Buffer.from('e5cd7c4bd13e02d8', 'hex')},
  {address:0x4b7c, bytes:Buffer.from(
    'c5cd864b3802ed52c1c92ab18dfdcb2d462007ed4bf88db7ed42ed4bbe8d' +
    'b7ed42c9', 'hex')},
];
const recordCapacityByteMap = new Map(recordCapacityRomSpans.flatMap(span =>
  Array.from(span.bytes,
    (value, offset) => [span.address + offset, value])));
const recordCapacityByte = address => {
  if (!recordCapacityByteMap.has(address))
    throw new Error(
      `record-capacity oracle reached unpinned byte 34:${address.toString(16)}`);
  return recordCapacityByteMap.get(address);
};
const allocationGeometryRomSpans = [
  {address:0x4f4c, bytes:Buffer.from(
    '7cb520012323e52b2911160019e3eb210000011400190b78b120fa424bd119ebc9',
    'hex')},
  {address:0x4f82, bytes:Buffer.from(
    '2901164202182b011670041c59031a4202182b01162b01162b011642021870041c' +
    '2b01162b0116', 'hex')},
];
const allocationGeometryByteMap = new Map(allocationGeometryRomSpans.flatMap(span =>
  Array.from(span.bytes,
    (value, offset) => [span.address + offset, value])));
const allocationGeometryByte = address => {
  if (!allocationGeometryByteMap.has(address))
    throw new Error(
      `allocation-geometry oracle reached unpinned byte 33:${address.toString(16)}`);
  return allocationGeometryByteMap.get(address);
};
const savedOperandRomSpan = {address:0x5abc, bytes:Buffer.from(
  '21998411e785c3921a3e1432e785cdaf1b3e1432788421788418e83e0532e785' +
  '3e4032e885117884180a3e00cd411f18e511998421e78518cdcdec19cdd25a11' +
  'f28518f011788421f28518ba21788411f28518b2fdcb116ec8cde15acde05918' +
  '0bfdcb116ec8cde15acdf959d818a7fdcb116ec8cd005bcde059180bfdcb116e' +
  'c8cd005bcdf959d818c2', 'hex')};
const savedOperandByteMap = new Map(Array.from(
  savedOperandRomSpan.bytes,
  (value, offset) => [savedOperandRomSpan.address + offset, value]));
const savedOperandByte = address => {
  if (!savedOperandByteMap.has(address))
    throw new Error(`saved-operand oracle reached unpinned byte 39:${address.toString(16)}`);
  return savedOperandByteMap.get(address);
};

// Page-39 alphabetic-VAT-search span. The fixed-bank calls are stubbed with their
// observed return flags/A values, but every local branch from 39:59E0 through
// 39:5A17 is executed from the extracted bytes below.
const operandEmitterRomSpan = {address:0x59af, bytes:Buffer.from(
  '3e0def2653181021e785cd2e5a3e0cef26533003cdaf1b3e14327884c93e17180d' +
  '3ade85fe1028cffe2928f13e05cdd95acd175a28caafcd533ad8cd2e5c2007' +
  'cd4219fe0628ea373fc9cd175a28b8afcd6f30d8cd2e5c20eecd4219fe0628ea' +
  '18e53ade85fe10c93ade85fe02c9', 'hex')};
const operandEmitterByteMap = new Map(Array.from(
  operandEmitterRomSpan.bytes,
  (value, offset) => [operandEmitterRomSpan.address + offset, value]));
const operandEmitterByte = address => {
  if (!operandEmitterByteMap.has(address))
    throw new Error(`alpha-search oracle reached unpinned byte 39:${address.toString(16)}`);
  return operandEmitterByteMap.get(address);
};
const operandEmitterWord = address =>
  operandEmitterByte(address) | (operandEmitterByte(address + 1) << 8);

function runRawAlphaSearch(direction, editorClass, editorSubClass, options = {}) {
  const start = direction === 'up' ? 0x59e0 : 0x59f9;
  const searchResults = options.searchResults || [];
  const special = options.specialResult || {};
  const savedOperand = options.savedOperand || new Array(9).fill(0);
  const memory = new Map([[0x85de,editorClass],[0x85df,editorSubClass]]);
  let pc = start, a = 0, h = 0, hl = 0, zero = false, carry = false;
  let searchIndex = 0, loopCount = 0, specialPath = null, postSearch = false;
  let callReturn = null, rstReturn = null;
  const effects = [];
  const finish = branch => ({
    branch:specialPath ? 'class-2-special' : postSearch ? 'post-search-complete' : branch,
    specialPath, loopCount, carry, effects,
  });
  for (let instructions = 0; instructions < 256; instructions++) {
    if (pc === 0x5a17) {
      a = memory.get(0x85de) || 0;
      zero = a === 0x02;
      pc = callReturn;
      continue;
    }
    if (pc === 0x5a2e) {
      zero = savedOperand.slice(1).every(value => value === 0);
      carry = false;
      pc = callReturn;
      continue;
    }
    if (pc === 0x3a53 || pc === 0x306f) {
      const result = searchResults[searchIndex++];
      if (!result) throw new Error('raw alpha-search result underflow');
      carry = !!result.carry;
      if (result.editorClass !== undefined) memory.set(0x85de,result.editorClass);
      if (result.editorSubClass !== undefined) memory.set(0x85df,result.editorSubClass);
      pc = callReturn;
      effects.push({kind:'find-alpha',index:searchIndex - 1,carry});
      continue;
    }
    if (pc === 0x5c2e) {
      zero = (memory.get(0x85de) || 0) === 3 &&
        (memory.get(0x85df) || 0) === 1;
      postSearch = zero;
      pc = callReturn;
      continue;
    }
    if (pc === 0x1942) {
      const result = searchResults[searchIndex - 1];
      a = result.postCode;
      if (result.nextEditorClass !== undefined)
        memory.set(0x85de,result.nextEditorClass);
      if (result.nextEditorSubClass !== undefined)
        memory.set(0x85df,result.nextEditorSubClass);
      pc = callReturn;
      continue;
    }
    if (pc === 0x1baf) {
      carry = !!special.call1BAFCarry;
      pc = callReturn;
      continue;
    }
    if (pc === 0x28) {
      carry = !!special.carry;
      pc = rstReturn;
      continue;
    }
    const opcode = operandEmitterByte(pc);
    if (opcode === 0x3a) {
      a = memory.get(operandEmitterWord(pc + 1)) || 0; pc += 3;
    } else if (opcode === 0xfe) {
      carry = a < operandEmitterByte(pc + 1); zero = a === operandEmitterByte(pc + 1); pc += 2;
    } else if (opcode === 0x28 || opcode === 0x20 || opcode === 0x30 || opcode === 0x18) {
      const displacement = signedByte(operandEmitterByte(pc + 1));
      const take = opcode === 0x18 ? true : opcode === 0x28 ? zero :
        opcode === 0x30 ? !carry : !zero;
      pc = take ? pc + 2 + displacement : pc + 2;
      if (take && pc === 0x59af) specialPath = '39:59AF';
      if (take && pc === 0x59b6) specialPath = '39:59B6';
      if (take && pc === 0x59e0) loopCount++;
    } else if (opcode === 0x3e) {
      a = operandEmitterByte(pc + 1); pc += 2;
    } else if (opcode === 0xcd) {
      const target = operandEmitterWord(pc + 1);
      callReturn = pc + 3;
      if (target === 0x5a17 || target === 0x3a53 || target === 0x306f ||
          target === 0x5c2e || target === 0x1942 || target === 0x1baf ||
          target === 0x5a2e) pc = target;
      else if (target === 0x5ad9) { pc += 3; }
      else throw new Error(`raw alpha-search unsupported call 39:${target.toString(16)}`);
    } else if (opcode === 0xef) {
      effects.push({kind:'emit-token',code:a}); rstReturn = pc + 1; pc = 0x28;
    } else if (opcode === 0xaf) {
      a = 0; zero = true; carry = false; pc++;
    } else if (opcode === 0x26) {
      h = operandEmitterByte(pc + 1); pc += 2;
    } else if (opcode === 0x21) {
      hl = operandEmitterWord(pc + 1); pc += 3;
    } else if (opcode === 0x32) {
      memory.set(operandEmitterWord(pc + 1),a); pc += 3;
    } else if (opcode === 0x37) {
      carry = true; pc++;
    } else if (opcode === 0x3f) {
      carry = !carry; pc++;
    } else if (opcode === 0xd8) {
      if (carry) return finish('search-carry');
      pc++;
    } else if (opcode === 0xc9) {
      return finish('search-complete');
    } else {
      throw new Error(`raw alpha-search unsupported opcode 0x${opcode.toString(16)} at 39:${pc.toString(16)}`);
    }
  }
  throw new Error('raw alpha-search exceeded its instruction bound');
}
const controllerByteMap = new Map(controllerRomSpans.flatMap(span =>
  Array.from(span.bytes, (value, offset) => [span.address + offset, value])));
const controllerByte = address => {
  if (!controllerByteMap.has(address))
    throw new Error(`controller oracle reached unpinned byte 39:${address.toString(16)}`);
  return controllerByteMap.get(address);
};
const signedByte = value => value < 0x80 ? value : value - 0x100;
const controllerWord = address =>
  controllerByte(address) | (controllerByte(address + 1) << 8);

function runRawController(action, argumentIndex, argumentCount, editorFlags) {
  let pc = action === 3 ? 0x51f1 : action === 4 ? 0x52a5 : null;
  if (pc === null) throw new RangeError('raw controller oracle accepts actions 3 and 4');
  const memory = new Map([
    [0x85e0, argumentIndex], [0x85e2, argumentCount], [0x844d, 0],
  ]);
  let a = action, hl = 0, zero = false, carry = false, calls = 0;
  for (let instructions = 0; instructions < 0x1000; instructions++) {
    if (pc === 0x513e) return {branch:'layout-first-argument', calls};
    if (pc === 0x520b) return {branch:'last-visible-argument', calls};
    if (pc === 0x523b) return {branch:'reverse-walker', calls};
    if (pc === 0x5447) return {branch:'row-token-tail', calls};
    const opcode = controllerByte(pc);
    if (opcode === 0xfe) {
      const operand = controllerByte(pc + 1);
      zero = a === operand;
      carry = a < operand;
      pc += 2;
    } else if (opcode === 0xc2) {
      pc = zero ? pc + 3 : controllerWord(pc + 1);
    } else if (opcode === 0xda) {
      pc = carry ? controllerWord(pc + 1) : pc + 3;
    } else if (opcode === 0xc3) {
      pc = controllerWord(pc + 1);
    } else if (opcode === 0x21) {
      hl = controllerWord(pc + 1);
      pc += 3;
    } else if (opcode === 0x7e) {
      a = memory.get(hl) || 0;
      pc++;
    } else if (opcode === 0xb7) {
      zero = a === 0;
      carry = false;
      pc++;
    } else if (opcode === 0x20 || opcode === 0x28 || opcode === 0x18) {
      const take = opcode === 0x18 || (opcode === 0x20 ? !zero : zero);
      pc = take ? pc + 2 + signedByte(controllerByte(pc + 1)) : pc + 2;
    } else if (opcode === 0xfd) {
      if (controllerByte(pc + 1) !== 0xcb ||
          controllerByte(pc + 2) !== 0x1d ||
          controllerByte(pc + 3) !== 0x46)
        throw new Error('controller oracle reached an unsupported indexed opcode');
      zero = (editorFlags & 1) === 0;
      pc += 4;
    } else if (opcode === 0x3a) {
      a = memory.get(controllerWord(pc + 1)) || 0;
      pc += 3;
    } else if (opcode === 0x32) {
      memory.set(controllerWord(pc + 1), a);
      pc += 3;
    } else if (opcode === 0x3d) {
      a = (a - 1) & 0xff;
      zero = a === 0;
      pc++;
    } else if (opcode === 0x96) {
      const operand = memory.get(hl) || 0;
      carry = a < operand;
      a = (a - operand) & 0xff;
      zero = a === 0;
      pc++;
    } else if (opcode === 0xcd) {
      const target = controllerWord(pc + 1);
      if (target !== 0x5167)
        throw new Error('controller oracle reached an unsupported call');
      calls++;
      pc += 3;
    } else if (opcode === 0x35) {
      const value = ((memory.get(hl) || 0) - 1) & 0xff;
      memory.set(hl, value);
      zero = value === 0;
      pc++;
    } else {
      throw new Error(`controller oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  throw new Error('controller oracle exceeded its instruction bound');
}

function runRawOverflowCue(direction, argumentIndex, argumentCount, winBottom,
                           cursorRow = 4, cursorColumn = 6) {
  let pc = direction === 'reverse' ? 0x66e9 :
    direction === 'forward' ? 0x66fe : null;
  if (pc === null)
    throw new RangeError('raw overflow-cue oracle accepts forward and reverse');
  const memory = new Map([
    [0x85e0,argumentIndex], [0x85e2,argumentCount], [0x97a6,winBottom],
    [0x844b,cursorRow], [0x844c,cursorColumn],
  ]);
  const readWord = address =>
    (memory.get(address) || 0) | ((memory.get(address + 1) || 0) << 8);
  const writeWord = (address, value) => {
    memory.set(address,value & 0xff);
    memory.set(address + 1,(value >> 8) & 0xff);
  };
  const literalWord = address =>
    overflowCueByte(address) | (overflowCueByte(address + 1) << 8);
  let a = 0, hl = 0, de = 0, carry = false;
  let remainingArguments = direction === 'forward' ? null : 0;
  let emission = null;
  const finish = branch => ({
    direction, branch, remainingArguments, emission,
    cursor:[memory.get(0x844b),memory.get(0x844c)],
  });
  for (let instructions = 0; instructions < 64; instructions++) {
    const opcode = overflowCueByte(pc);
    if (opcode === 0x3a) {
      a = memory.get(literalWord(pc + 1)) || 0;
      pc += 3;
    } else if (opcode === 0x21) {
      hl = literalWord(pc + 1);
      pc += 3;
    } else if (opcode === 0x96) {
      const operand = memory.get(hl) || 0;
      carry = a < operand;
      a = (a - operand) & 0xff;
      remainingArguments = a;
      pc++;
    } else if (opcode === 0xfe) {
      carry = a < overflowCueByte(pc + 1);
      pc += 2;
    } else if (opcode === 0xd8) {
      if (carry) return finish('return');
      pc++;
    } else if (opcode === 0x3d) {
      a = (a - 1) & 0xff;
      pc++;
    } else if (opcode === 0x6f) {
      hl = (hl & 0xff00) | a;
      pc++;
    } else if (opcode === 0x26) {
      hl = (hl & 0x00ff) | (overflowCueByte(pc + 1) << 8);
      pc += 2;
    } else if (opcode === 0x3e) {
      a = overflowCueByte(pc + 1);
      pc += 2;
    } else if (opcode === 0x18) {
      pc += 2 + signedByte(overflowCueByte(pc + 1));
    } else if (opcode === 0xed && overflowCueByte(pc + 1) === 0x5b) {
      de = readWord(literalWord(pc + 2));
      pc += 4;
    } else if (opcode === 0x22) {
      writeWord(literalWord(pc + 1),hl);
      pc += 3;
    } else if (opcode === 0xcd) {
      const target = literalWord(pc + 1);
      if (target !== 0x3fdb)
        throw new Error('overflow-cue oracle reached an unsupported call');
      emission = {
        row:memory.get(0x844b), column:memory.get(0x844c), code:a,
      };
      pc += 3;
    } else if (opcode === 0xed && overflowCueByte(pc + 1) === 0x53) {
      writeWord(literalWord(pc + 2),de);
      pc += 4;
    } else if (opcode === 0xc9) {
      return finish('emit-cue');
    } else {
      throw new Error(`overflow-cue oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  throw new Error('overflow-cue oracle exceeded its instruction bound');
}

function runRawSavedOperandWrapper(source, direction, recordFlags, buffers,
                                   searchResult) {
  const entries = {
    'saved-E7:up':0x5b10, 'saved-E7:down':0x5b1d,
    'saved-F2:up':0x5b2b, 'saved-F2:down':0x5b38,
  };
  let pc = entries[`${source}:${direction}`];
  if (pc === undefined)
    throw new RangeError('raw saved-operand oracle received an invalid wrapper');
  const memory = new Map();
  const writeBuffer = (address, values) =>
    values.forEach((value, index) => memory.set(address + index,value));
  const readBuffer = (address, length) =>
    Array.from({length}, (_, index) => memory.get(address + index) || 0);
  writeBuffer(0x8478,buffers.op1);
  writeBuffer(0x85e7,buffers.savedE7);
  writeBuffer(0x85f2,buffers.savedF2);
  const literalWord = address =>
    savedOperandByte(address) | (savedOperandByte(address + 1) << 8);
  const callStack = [];
  let hl = 0, de = 0;
  let zero = false;
  let carry = searchResult.incomingCarry || false;
  let searchInput = null;
  const finish = branch => ({
    branch, searchInput, carry,
    buffers:{
      op1:readBuffer(0x8478,11),
      savedE7:readBuffer(0x85e7,9),
      savedF2:readBuffer(0x85f2,9),
    },
  });
  for (let instructions = 0; instructions < 64; instructions++) {
    if (pc === 0x1a92) {
      writeBuffer(de,readBuffer(hl,9));
      if (!callStack.length) return finish('save-result');
      pc = callStack.pop();
      continue;
    }
    const opcode = savedOperandByte(pc);
    if (opcode === 0xfd) {
      if (savedOperandByte(pc + 1) !== 0xcb ||
          savedOperandByte(pc + 2) !== 0x11 ||
          savedOperandByte(pc + 3) !== 0x6e)
        throw new Error('saved-operand oracle reached an unsupported indexed opcode');
      zero = (recordFlags & 0x20) === 0;
      pc += 4;
    } else if (opcode === 0xc8) {
      if (zero) return finish('gated-return');
      pc++;
    } else if (opcode === 0xcd) {
      const target = literalWord(pc + 1);
      if (target === 0x5ae1 || target === 0x5b00) {
        callStack.push(pc + 3);
        pc = target;
      } else if (target === 0x59e0 || target === 0x59f9) {
        searchInput = readBuffer(0x8478,11);
        writeBuffer(0x8478,searchResult.op1);
        carry = searchResult.carry;
        pc += 3;
      } else {
        throw new Error(`saved-operand oracle reached unsupported call 0x${target.toString(16)}`);
      }
    } else if (opcode === 0x11) {
      de = literalWord(pc + 1);
      pc += 3;
    } else if (opcode === 0x21) {
      hl = literalWord(pc + 1);
      pc += 3;
    } else if (opcode === 0x18) {
      pc += 2 + signedByte(savedOperandByte(pc + 1));
    } else if (opcode === 0xc3) {
      const target = literalWord(pc + 1);
      if (target !== 0x1a92)
        throw new Error('saved-operand oracle reached an unsupported jump');
      pc = target;
    } else if (opcode === 0xd8) {
      if (carry) return finish('search-carry');
      pc++;
    } else {
      throw new Error(`saved-operand oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  throw new Error('saved-operand oracle exceeded its instruction bound');
}

function runRawEditorViewport(expressionEndpoint, previousXClip,
                              iy44Bit3, extraWidth, rightBound = 0x5f) {
  const literalWord = address => editorViewportByte(address) |
    (editorViewportByte(address + 1) << 8);
  const memory = new Map([
    [0x8516,expressionEndpoint], [0x8e02,previousXClip],
    [0x8dfc,rightBound],
  ]);
  let pc = 0x5f5d, hl = 0, de = extraWidth, bc = 0;
  let carry = false, zero = false, comparisonCoordinate = null;
  const stack = [], branchOutcomes = [];
  for (let instructions = 0; instructions < 64; instructions++) {
    const opcode = editorViewportByte(pc);
    if (opcode === 0xd5) {
      stack.push(de); pc++;
    } else if (opcode === 0x2a) {
      hl = memory.get(literalWord(pc + 1)) || 0; pc += 3;
    } else if (opcode === 0xcd) {
      const target = literalWord(pc + 1);
      if (target === 0x5dc2) {
        de = memory.get(0x8e02) || 0;
        carry = hl < de;
        hl = (hl - de) & 0xffff;
      } else if (target === 0x5dca) {
        comparisonCoordinate = hl;
        de = (memory.get(0x8dfc) || 0) & 0xff;
      } else {
        throw new Error(
          `editor-viewport oracle reached unsupported call 0x${target.toString(16)}`);
      }
      pc += 3;
    } else if (opcode === 0x30) {
      const taken = !carry;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(editorViewportByte(pc + 1)) : pc + 2;
    } else if (opcode === 0x01) {
      bc = literalWord(pc + 1); pc += 3;
    } else if (opcode === 0xed && editorViewportByte(pc + 1) === 0x43) {
      memory.set(literalWord(pc + 2),bc); pc += 4;
    } else if (opcode === 0x19) {
      hl = (hl + de) & 0xffff; pc++;
    } else if (opcode === 0x11) {
      de = literalWord(pc + 1); pc += 3;
    } else if (opcode === 0xfd && editorViewportByte(pc + 1) === 0xcb &&
               editorViewportByte(pc + 2) === 0x44 &&
               editorViewportByte(pc + 3) === 0x5e) {
      zero = !iy44Bit3; pc += 4;
    } else if (opcode === 0x20) {
      const taken = !zero;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(editorViewportByte(pc + 1)) : pc + 2;
    } else if (opcode === 0x1b) {
      de = (de - 1) & 0xffff; pc++;
    } else if (opcode === 0xd1) {
      de = stack.pop(); pc++;
    } else if (opcode === 0xb7) {
      carry = false; pc++;
    } else if (opcode === 0xed && editorViewportByte(pc + 1) === 0x52) {
      carry = hl < de;
      hl = (hl - de) & 0xffff;
      pc += 2;
    } else if (opcode === 0xd8) {
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${carry ? 'returned' : 'fallthrough'}`);
      if (carry) break;
      pc++;
    } else if (opcode === 0xed && editorViewportByte(pc + 1) === 0x5b) {
      const address = literalWord(pc + 2);
      if (address === 0x8dfd) comparisonCoordinate = hl;
      de = memory.get(address) || 0; pc += 4;
    } else if (opcode === 0x22) {
      memory.set(literalWord(pc + 1),hl); pc += 3;
    } else if (opcode === 0xc9) {
      break;
    } else {
      throw new Error(
        `editor-viewport oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  if (comparisonCoordinate === null)
    throw new Error('editor-viewport oracle did not reach its right-bound load');
  const xClip = memory.get(0x8e02) || 0;
  return {
    expressionEndpoint, previousXClip,
    resetPreviousClip:branchOutcomes[0] === '34:5F64:fallthrough',
    iy44Bit3:Boolean(iy44Bit3), cursorWidth:iy44Bit3 ? 6 : 5,
    extraWidth, rightBound, xOrigin:0, yOrigin:0, screenXOrigin:0, xClip,
    effectiveX:-xClip, cursorX:expressionEndpoint - xClip,
    comparisonCoordinate,
    branch:branchOutcomes[2] === '34:5F81:returned'
      ? 'return-before-right-bound' : 'store-horizontal-clip',
    branchOutcomes,
    routine:'34:5F5D–5F8A; applied by 34:5DBE–5DC9',
  };
}

function runRawEditorVerticalViewport(cursorTop, previousYClip,
                                      iy44Bit3, extraHeight,
                                      bottomBound = 0x3e) {
  const literalWord = address => editorViewportByte(address) |
    (editorViewportByte(address + 1) << 8);
  const memory = new Map([
    [0x8518,cursorTop], [0x8e04,previousYClip],
    [0x8dfd,bottomBound],
  ]);
  let pc = 0x5f8b, hl = 0, de = extraHeight, bc = 0;
  let carry = false, zero = false, comparisonCoordinate = null;
  const stack = [], branchOutcomes = [];
  for (let instructions = 0; instructions < 64; instructions++) {
    const opcode = editorViewportByte(pc);
    if (opcode === 0xd5) {
      stack.push(de); pc++;
    } else if (opcode === 0x2a) {
      hl = memory.get(literalWord(pc + 1)) || 0; pc += 3;
    } else if (opcode === 0xed && editorViewportByte(pc + 1) === 0x5b) {
      const address = literalWord(pc + 2);
      if (address === 0x8dfd) comparisonCoordinate = hl;
      de = memory.get(address) || 0; pc += 4;
    } else if (opcode === 0xb7) {
      carry = false; zero = (hl & 0xff) === 0; pc++;
    } else if (opcode === 0xed && editorViewportByte(pc + 1) === 0x52) {
      carry = hl < de;
      hl = (hl - de) & 0xffff;
      zero = hl === 0;
      pc += 2;
    } else if (opcode === 0x30) {
      const taken = !carry;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(editorViewportByte(pc + 1)) : pc + 2;
    } else if (opcode === 0x01) {
      bc = literalWord(pc + 1); pc += 3;
    } else if (opcode === 0xed && editorViewportByte(pc + 1) === 0x43) {
      memory.set(literalWord(pc + 2),bc); pc += 4;
    } else if (opcode === 0x19) {
      hl = (hl + de) & 0xffff; pc++;
    } else if (opcode === 0x11) {
      de = literalWord(pc + 1); pc += 3;
    } else if (opcode === 0xfd && editorViewportByte(pc + 1) === 0xcb &&
               editorViewportByte(pc + 2) === 0x44 &&
               editorViewportByte(pc + 3) === 0x5e) {
      zero = !iy44Bit3; pc += 4;
    } else if (opcode === 0x20) {
      const taken = !zero;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(editorViewportByte(pc + 1)) : pc + 2;
    } else if (opcode === 0x1b) {
      de = (de - 1) & 0xffff; pc++;
    } else if (opcode === 0xd1) {
      de = stack.pop(); pc++;
    } else if (opcode === 0x16) {
      de &= 0x00ff; pc += 2;
    } else if (opcode === 0xd8) {
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${carry ? 'returned' : 'fallthrough'}`);
      if (carry) break;
      pc++;
    } else if (opcode === 0x22) {
      memory.set(literalWord(pc + 1),hl); pc += 3;
    } else if (opcode === 0xc9) {
      break;
    } else {
      throw new Error(
        `vertical-viewport oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  if (comparisonCoordinate === null)
    throw new Error('vertical-viewport oracle did not reach its bottom-bound compare');
  const yClip = memory.get(0x8e04) || 0;
  return {
    cursorTop, previousYClip,
    resetPreviousClip:branchOutcomes[0] === '34:5F96:fallthrough',
    iy44Bit3:Boolean(iy44Bit3), cursorHeight:iy44Bit3 ? 7 : 5,
    extraHeight, bottomBound, yOrigin:0, screenYOrigin:0, yClip,
    effectiveY:-yClip, cursorY:cursorTop - yClip,
    comparisonCoordinate,
    branch:branchOutcomes[2] === '34:5FB7:returned'
      ? 'return-before-bottom-bound' : 'store-vertical-clip',
    branchOutcomes,
    routine:'34:5F8B–5FC0; applied by 34:6BE5–6BFC and 34:67C8–6872',
  };
}

function runRawRecordAllocationCapacity(input) {
  const literalWord = address => recordCapacityByte(address) |
    (recordCapacityByte(address + 1) << 8);
  const memory = new Map([
    [0x8db1,input.workspaceTop],
    [0x8dbe,input.recordTail],
    [0x8df8,input.reservedSpan],
  ]);
  let pc = 0x4868, a = 0, bc = 0, de = input.requestedBytes, hl = 0;
  let carry = false, zero = false;
  const stack = [], branchOutcomes = [];
  let afterReserved = null, availableBeforeRequest = null;
  let rangeBorrow = null, requestCompared = false, requestBorrow = false;
  for (let instructions = 0; instructions < 64; instructions++) {
    const opcode = recordCapacityByte(pc);
    if (opcode === 0xe5) {
      stack.push(hl); pc++;
    } else if (opcode === 0xc5) {
      stack.push(bc); pc++;
    } else if (opcode === 0xcd) {
      stack.push(pc + 3); pc = literalWord(pc + 1);
    } else if (opcode === 0xd1) {
      de = stack.pop(); pc++;
    } else if (opcode === 0xc1) {
      bc = stack.pop(); pc++;
    } else if (opcode === 0xc9) {
      pc = stack.pop();
    } else if (opcode === 0x2a) {
      hl = memory.get(literalWord(pc + 1)); pc += 3;
    } else if (opcode === 0xfd && recordCapacityByte(pc + 1) === 0xcb &&
               recordCapacityByte(pc + 2) === 0x2d &&
               recordCapacityByte(pc + 3) === 0x46) {
      zero = !input.iy2dBit0; pc += 4;
    } else if (opcode === 0x20) {
      const taken = !zero;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(recordCapacityByte(pc + 1)) : pc + 2;
    } else if (opcode === 0xed && recordCapacityByte(pc + 1) === 0x4b) {
      bc = memory.get(literalWord(pc + 2)); pc += 4;
    } else if (opcode === 0xb7) {
      carry = false; zero = a === 0; pc++;
    } else if (opcode === 0xed && recordCapacityByte(pc + 1) === 0x42) {
      const right = bc;
      carry = hl < right;
      hl = (hl - right) & 0xffff;
      if (pc === 0x4b94) afterReserved = hl;
      if (pc === 0x4b9b) {
        rangeBorrow = carry;
        availableBeforeRequest = hl;
      }
      pc += 2;
    } else if (opcode === 0x38) {
      const taken = carry;
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(recordCapacityByte(pc + 1)) : pc + 2;
    } else if (opcode === 0xed && recordCapacityByte(pc + 1) === 0x52) {
      requestCompared = true;
      requestBorrow = hl < de;
      carry = requestBorrow;
      hl = (hl - de) & 0xffff;
      pc += 2;
    } else if (opcode === 0x3e) {
      a = recordCapacityByte(pc + 1); pc += 2;
    } else if (opcode === 0xd8) {
      branchOutcomes.push(
        `34:${pc.toString(16).toUpperCase()}:${carry ? 'returned' : 'fallthrough'}`);
      if (carry) break;
      pc++;
      break;
    } else {
      throw new Error(
        `record-capacity oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  if (afterReserved === null) afterReserved = input.workspaceTop;
  if (rangeBorrow === null || availableBeforeRequest === null)
    throw new Error('record-capacity oracle did not execute its range subtraction');
  return {
    workspaceTop:input.workspaceTop,
    recordTail:input.recordTail,
    reservedSpan:input.reservedSpan,
    requestedBytes:input.requestedBytes,
    iy2dBit0:input.iy2dBit0,
    subtractReserved:!input.iy2dBit0,
    afterReserved,
    rangeBorrow,
    availableBeforeRequest,
    requestCompared,
    requestBorrow,
    remainingBytes:hl,
    carry,
    returnA:a,
    terminal:carry ? 'return-allocation-carry' : 'continue-allocation',
    branchOutcomes,
    routine:'34:4B7C–4B9D; caller 34:4862–4870',
  };
}

function runRawRecordAllocationGeometry(renderType, matrixElements = null) {
  if (renderType !== 0x2b) {
    const tableAddress = 0x4f82 + 3 * (renderType - 0x1f);
    return {
      renderType,matrixElements:null,
      workspaceRequest:allocationGeometryByte(tableAddress),
      childCount:allocationGeometryByte(tableAddress + 1),
      recordBytes:allocationGeometryByte(tableAddress + 2),
      tableAddress,branchOutcomes:[],routine:'33:4F6D–4F81',
    };
  }
  let pc = 0x4f4c, a = 0, bc = 0, de = 0, hl = matrixElements;
  let zero = false;
  const stack = [], branchOutcomes = [];
  for (let instructions = 0; instructions < 256; instructions++) {
    const opcode = allocationGeometryByte(pc);
    if (opcode === 0x7c) {
      a = hl >> 8; pc++;
    } else if (opcode === 0xb5) {
      a |= hl & 0xff; zero = a === 0; pc++;
    } else if (opcode === 0x20) {
      const taken = !zero;
      branchOutcomes.push(
        `33:${pc.toString(16).toUpperCase()}:${taken ? 'taken' : 'fallthrough'}`);
      pc = taken ? pc + 2 + signedByte(allocationGeometryByte(pc + 1)) : pc + 2;
    } else if (opcode === 0x23) {
      hl = (hl + 1) & 0xffff; pc++;
    } else if (opcode === 0xe5) {
      stack.push(hl); pc++;
    } else if (opcode === 0x2b) {
      hl = (hl - 1) & 0xffff; pc++;
    } else if (opcode === 0x29) {
      hl = (hl * 2) & 0xffff; pc++;
    } else if (opcode === 0x11) {
      de = allocationGeometryByte(pc + 1) |
        allocationGeometryByte(pc + 2) << 8;
      pc += 3;
    } else if (opcode === 0x19) {
      hl = (hl + de) & 0xffff; pc++;
    } else if (opcode === 0xe3) {
      const saved = stack.pop(); stack.push(hl); hl = saved; pc++;
    } else if (opcode === 0xeb) {
      [de,hl] = [hl,de]; pc++;
    } else if (opcode === 0x21) {
      hl = allocationGeometryByte(pc + 1) |
        allocationGeometryByte(pc + 2) << 8;
      pc += 3;
    } else if (opcode === 0x01) {
      bc = allocationGeometryByte(pc + 1) |
        allocationGeometryByte(pc + 2) << 8;
      pc += 3;
    } else if (opcode === 0x0b) {
      bc = (bc - 1) & 0xffff; pc++;
    } else if (opcode === 0x78) {
      a = bc >> 8; pc++;
    } else if (opcode === 0xb1) {
      a |= bc & 0xff; zero = a === 0; pc++;
    } else if (opcode === 0x42) {
      bc = (bc & 0x00ff) | (de & 0xff00); pc++;
    } else if (opcode === 0x4b) {
      bc = (bc & 0xff00) | (de & 0xff); pc++;
    } else if (opcode === 0xd1) {
      de = stack.pop(); pc++;
    } else if (opcode === 0xc9) {
      break;
    } else {
      throw new Error(
        `allocation-geometry oracle reached unsupported opcode 0x${opcode.toString(16)}`);
    }
  }
  return {
    renderType,matrixElements,
    workspaceRequest:de,childCount:bc,recordBytes:hl,
    tableAddress:0x4fa6,branchOutcomes,routine:'33:4F42–4F6C',
  };
}

const localRomPath = path.join(root, 'tools', 'rom.bin');
if (fs.existsSync(localRomPath)) {
  const localRom = fs.readFileSync(localRomPath);
  expectEqual('controller oracle uses the pinned OS 2.55MP image',
    crypto.createHash('sha256').update(localRom).digest('hex'),
    '7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d');
  for (const span of controllerRomSpans) {
    const offset = 0x39 * 0x4000 + (span.address & 0x3fff);
    expectEqual(`39:${span.address.toString(16)} raw controller bytes`,
      localRom.subarray(offset, offset + span.bytes.length), span.bytes);
  }
  const sharedMarkerOffset = 0x34 * 0x4000 +
    (sharedMarkerRomSpan.address & 0x3fff);
  expectEqual('34:6143–61BD raw shared-marker bytes',
    localRom.subarray(
      sharedMarkerOffset,sharedMarkerOffset + sharedMarkerRomSpan.bytes.length),
    sharedMarkerRomSpan.bytes);
  for (const span of renderNestingTailRomSpans) {
    const offset = 0x34 * 0x4000 + (span.address & 0x3fff);
    expectEqual(`34:${span.address.toString(16)} raw render-nesting-tail bytes`,
      localRom.subarray(offset,offset + span.bytes.length),span.bytes);
  }
  const pointAddressOffset = 0x04 * 0x4000 +
    (pointAddressRomSpan.address & 0x3fff);
  expectEqual('04:42B5–42EB raw point-address bytes',
    localRom.subarray(
      pointAddressOffset,pointAddressOffset + pointAddressRomSpan.bytes.length),
    pointAddressRomSpan.bytes);
  const overflowOffset = 0x39 * 0x4000 +
    (overflowCueRomSpan.address & 0x3fff);
  expectEqual('39:66E9–6711 raw overflow-cue bytes',
    localRom.subarray(
      overflowOffset, overflowOffset + overflowCueRomSpan.bytes.length),
    overflowCueRomSpan.bytes);
  const savedOperandOffset = 0x39 * 0x4000 +
    (savedOperandRomSpan.address & 0x3fff);
  expectEqual('39:5ABC–5B45 raw saved-operand bytes',
    localRom.subarray(
      savedOperandOffset,
      savedOperandOffset + savedOperandRomSpan.bytes.length),
    savedOperandRomSpan.bytes);
  for (const span of editorViewportRomSpans) {
    const offset = 0x34 * 0x4000 + (span.address & 0x3fff);
    expectEqual(`34:${span.address.toString(16)} raw editor-viewport bytes`,
      localRom.subarray(offset, offset + span.bytes.length), span.bytes);
  }
  for (const span of verticalCueRomSpans) {
    const offset = span.page * 0x4000 + (span.address & 0x3fff);
    expectEqual(
      `${span.page.toString(16)}:${span.address.toString(16)} raw vertical-cue bytes`,
      localRom.subarray(offset, offset + span.bytes.length), span.bytes);
  }
  const glyphViewportOffset = 0x34 * 0x4000 +
    (glyphViewportRomSpan.address & 0x3fff);
  expectEqual('34:6C5F–6C86 raw glyph-viewport bytes',
    localRom.subarray(
      glyphViewportOffset,glyphViewportOffset + glyphViewportRomSpan.bytes.length),
    glyphViewportRomSpan.bytes);
  const runIndicatorOffset = 0x01 * 0x4000 +
    (runIndicatorRomSpan.address & 0x3fff);
  expectEqual('01:6BBA–6BFA raw run-indicator bytes',
    localRom.subarray(
      runIndicatorOffset,runIndicatorOffset + runIndicatorRomSpan.bytes.length),
    runIndicatorRomSpan.bytes);
  for (const span of recordCapacityRomSpans) {
    const offset = 0x34 * 0x4000 + (span.address & 0x3fff);
    expectEqual(`34:${span.address.toString(16)} raw record-capacity bytes`,
      localRom.subarray(offset, offset + span.bytes.length), span.bytes);
  }
  for (const span of allocationGeometryRomSpans) {
    const offset = 0x33 * 0x4000 + (span.address & 0x3fff);
    expectEqual(`33:${span.address.toString(16)} raw allocation-geometry bytes`,
      localRom.subarray(offset, offset + span.bytes.length), span.bytes);
  }
}
expectEqual('39:52B6 relative jump targets the row-token tail',
  0x52b8 + signedByte(controllerByte(0x52b7)), 0x52a2);
expectEqual('39:66FE emits the fixed forward overflow cue',
  rom.editorForwardOverflowCue(), {
    direction:'forward', branch:'emit-cue', remainingArguments:null,
    emission:{row:1,column:1,code:0x1e}, cursorPreserved:true,
    routine:'39:66FE',
  });
expectEqual('39:66E9 returns with seven remaining arguments',
  rom.editorReverseOverflowCue(5, 12, 7), {
    direction:'reverse', argumentIndex:5, argumentCount:12, winBottom:7,
    remainingArguments:7, branch:'return', emission:null,
    cursorPreserved:true, routine:'39:66E9',
  });
expectEqual('39:66E9 wraps a zero window bottom before drawing',
  rom.editorReverseOverflowCue(1, 12, 0), {
    direction:'reverse', argumentIndex:1, argumentCount:12, winBottom:0,
    remainingArguments:11, branch:'emit-cue',
    emission:{row:0xff,column:1,code:0x1f},
    cursorPreserved:true, routine:'39:66E9',
  });
expectEqual('39:66FE translation matches the raw bytes', (() => {
  const raw = runRawOverflowCue('forward', 0, 0, 0, 0xa5, 0x5a);
  const translated = rom.editorForwardOverflowCue();
  return {
    raw, translated:{
      direction:translated.direction, branch:translated.branch,
      remainingArguments:translated.remainingArguments,
      emission:translated.emission, cursor:[0xa5,0x5a],
    },
  };
})(), {
  raw:{direction:'forward',branch:'emit-cue',remainingArguments:null,
    emission:{row:1,column:1,code:0x1e},cursor:[0xa5,0x5a]},
  translated:{direction:'forward',branch:'emit-cue',remainingArguments:null,
    emission:{row:1,column:1,code:0x1e},cursor:[0xa5,0x5a]},
});
expectThrows('39:66E9 rejects a non-byte window bottom', RangeError,
  () => rom.editorReverseOverflowCue(0, 8, 0x100));

// Compare all 65,536 count/index byte states with an interpreter that runs
// the pinned 39:66E9 bytes. The second loop exhausts the wrapped winBtm row.
let reverseCueReturnStates = 0;
let reverseCueEmitStates = 0;
for (let argumentCount = 0; argumentCount <= 0xff; argumentCount++) {
  for (let argumentIndex = 0; argumentIndex <= 0xff; argumentIndex++) {
    const raw = runRawOverflowCue(
      'reverse', argumentIndex, argumentCount, 7, 0xa5, 0x5a);
    const translated = rom.editorReverseOverflowCue(
      argumentIndex, argumentCount, 7);
    expectEqual('39:66E9 exhaustive raw-byte state', {
      branch:translated.branch,
      remainingArguments:translated.remainingArguments,
      emission:translated.emission,
      restored:raw.cursor,
    }, {
      branch:raw.branch,
      remainingArguments:raw.remainingArguments,
      emission:raw.emission,
      restored:[0xa5,0x5a],
    });
    if (translated.branch === 'return') reverseCueReturnStates++;
    else reverseCueEmitStates++;
  }
}
expectEqual('39:66E9 exhaustive terminal partition',
  [reverseCueReturnStates,reverseCueEmitStates], [0x800,0xf800]);
for (let winBottom = 0; winBottom <= 0xff; winBottom++) {
  const raw = runRawOverflowCue('reverse', 1, 12, winBottom);
  const translated = rom.editorReverseOverflowCue(1, 12, winBottom);
  expectEqual('39:66E9 exhaustive window-bottom row',
    translated.emission, raw.emission);
}

const alphaIdentity = (type, nameByte) =>
  [type,nameByte,0,0,0,0,0,0,0];
const alphaOp = (type, nameByte, extension9 = 0, extension10 = 0) =>
  [...alphaIdentity(type,nameByte),extension9,extension10];
const alphaVatEntry = (identity, pointer, page = 0, continuationByte = 0) =>
  ({identity,continuationByte,pointer,page});
const alphaRam = new Uint8Array(0x10000);
alphaRam[0x9000] = 0x85;
alphaRam[0x8ffb] = 0x02;
alphaRam[0x8ffa] = 3;
alphaRam[0x8ff9] = 0x43;
alphaRam[0x8ff8] = 0x41;
alphaRam[0x8ff7] = 0x54;
alphaRam[0x8ff6] = 0x00;
alphaRam[0x8ff1] = 0;
alphaRam[0x8ff0] = 0x58;
expectEqual('07:51BE decodes named and fixed VAT records',
  rom.editorDecodeAlphaVatRegion(alphaRam,0x9000,0x8fed), [
    alphaVatEntry([0x05,0x43,0x41,0x54,0,0,0,0,0],0x9000,2),
    alphaVatEntry([0x00,0x58,0,0,0,0,0,0,0],0x8ff6),
  ]);
expectEqual('07:510B accepts an empty VAT scan region',
  rom.editorDecodeAlphaVatRegion(alphaRam,0x9000,0x9000), []);
alphaRam[0x982e] = 0xed;
alphaRam[0x982f] = 0x8f;
alphaRam[0x9830] = 0x00;
alphaRam[0x9831] = 0x90;
expectEqual('07:50BE derives named-region bounds from pTemp and progPtr',
  rom.editorDecodeAlphaVatSnapshot(alphaRam,alphaOp(0x05,0x42)), {
    region:'named/list',start:0x9000,bound:0x8fed,
    pTemp:0x8fed,progPtr:0x9000,symTable:0xfe66,
    entries:[
      alphaVatEntry([0x05,0x43,0x41,0x54,0,0,0,0,0],0x9000,2),
      alphaVatEntry([0x00,0x58,0,0,0,0,0,0,0],0x8ff6),
    ],routine:'07:50BE–50F9',
  });
const alphaListRam = new Uint8Array(0x10000);
alphaListRam[0x9100] = 0x01;
alphaListRam[0x90fa] = 3;
alphaListRam[0x90f9] = 0x5d;
alphaListRam[0x90f8] = 0x01;
expectEqual('07:51BE removes the list length byte from the OP identity',
  rom.editorDecodeAlphaVatRegion(alphaListRam,0x9100,0x90f6), [
    alphaVatEntry([0x01,0x5d,0x01,0,0,0,0,0,0],0x9100),
  ]);
expectEqual('07:50BE selects the named region for a list-name OP identity',
  rom.editorDecodeAlphaVatSnapshot(alphaListRam,
    [0x00,0x5d,0x01,0,0,0,0,0,0,0,0],{pTemp:0x90f6,progPtr:0x9100}), {
    region:'named/list',start:0x9100,bound:0x90f6,
    pTemp:0x90f6,progPtr:0x9100,symTable:0xfe66,
    entries:[
      alphaVatEntry([0x01,0x5d,0x01,0,0,0,0,0,0],0x9100),
    ],routine:'07:50BE–50F9',
  });
const emptyAlphaRam = new Uint8Array(0x10000);
const alphaRegion = op1 => rom.editorDecodeAlphaVatSnapshot(
  emptyAlphaRam,op1,{pTemp:0x9000,progPtr:0x9000,symTable:0x9000}).region;
expectEqual('07:50C4 selects VAT regions from list-name encodings', [
  alphaRegion(alphaOp(0x01,0x5d)),
  alphaRegion(alphaOp(0x01,0xff)),
  alphaRegion(alphaOp(0x01,0x72)),
  alphaRegion(alphaOp(0x01,0x3a)),
  alphaRegion(alphaOp(0x0d,0x5d)),
  alphaRegion(alphaOp(0x0d,0xff)),
  alphaRegion(alphaOp(0x0d,0x72)),
  alphaRegion(alphaOp(0x0d,0x3a)),
], [
  'named/list','named/list','fixed-token','fixed-token',
  'named/list','named/list','fixed-token','fixed-token',
]);
const alphaMarkerRam = new Uint8Array(0x10000);
alphaMarkerRam[0x9200] = 0x0d;
alphaMarkerRam[0x91fa] = 0x3a;
alphaMarkerRam[0x91f9] = 0x41;
alphaMarkerRam[0x91f8] = 0x42;
expectEqual('07:51D6 treats 3Ah as a fixed three-byte list form',
  rom.editorDecodeAlphaVatRegion(alphaMarkerRam,0x9200,0x91f7), [
    alphaVatEntry([0x0d,0x3a,0x41,0x42,0,0,0,0,0],0x9200),
  ]);
const alphaType9Ram = new Uint8Array(0x10000);
alphaType9Ram[0x9300] = 0x09;
alphaType9Ram[0x92fa] = 4;
alphaType9Ram[0x92f9] = 0x41;
alphaType9Ram[0x92f8] = 0x42;
expectEqual('07:512C applies variable stepping to type 09h',
  rom.editorDecodeAlphaVatRegion(alphaType9Ram,0x9300,0x92f5), [
    alphaVatEntry([0x09,0x04,0x41,0x42,0,0,0,0,0],0x9300),
  ]);
const alphaFixedRam = new Uint8Array(0x10000);
alphaFixedRam[0xfe66] = 0x00;
alphaFixedRam[0xfe61] = 0x03;
alphaFixedRam[0xfe60] = 0x42;
alphaFixedRam[0xfe5f] = 0x00;
alphaFixedRam[0xfe5e] = 0x00;
alphaFixedRam[0x982e] = 0x5d;
alphaFixedRam[0x982f] = 0xfe;
alphaFixedRam[0x9830] = 0x5d;
alphaFixedRam[0x9831] = 0xfe;
expectEqual('07:50BE derives the fixed-token region from symTable and progPtr',
  rom.editorDecodeAlphaVatSnapshot(alphaFixedRam,alphaOp(0x00,0x41)), {
    region:'fixed-token',start:0xfe66,bound:0xfe5d,
    pTemp:0xfe5d,progPtr:0xfe5d,symTable:0xfe66,
    entries:[
      alphaVatEntry([0x00,0x42,0,0,0,0,0,0,0],0xfe66,3),
    ],routine:'07:50BE–50F9',
  });
expectThrows('07:51BE rejects an overlong logical VAT name', RangeError, () => {
  const ram = new Uint8Array(0x10000);
  ram[0x9400] = 5;
  ram[0x93fa] = 9;
  rom.editorDecodeAlphaVatRegion(ram,0x9400,0x93f0);
});
expectEqual('07:522E reads OP2+9 from immediately below the VAT record', (() => {
  const ram = new Uint8Array(0x10000);
  ram[0x9400] = 0x00;
  ram[0x93fb] = 0x03;
  ram[0x93fa] = 0x42;
  ram[0x93f7] = 0xa5;
  return rom.editorDecodeAlphaVatRegion(ram,0x9400,0x93f7);
})(), [alphaVatEntry([0x00,0x42,0,0,0,0,0,0,0],0x9400,3,0xa5)]);
const alphaVat = [
  alphaVatEntry(alphaIdentity(0x85,0x43),0x9fd0),
  alphaVatEntry(alphaIdentity(0x00,0x42),0x9fc0),
  alphaVatEntry(alphaIdentity(0x06,0x42),0x9fb0),
  alphaVatEntry(alphaIdentity(0x05,0x41),0x9fa0),
];
expectEqual('07:50B5 selects the nearest higher same-class VAT name',
  rom.editorFindAlphaVat('up',alphaOp(0x05,0x41),alphaVat), {
    direction:'up',sameType:true,sourceClass:0x05,carry:false,a:0,zero:true,
    op1:alphaOp(0x06,0x42),op3:alphaOp(0x06,0x42),
    vatPointer:0x9fb0,selectedIndex:2,compared:3,
    routine:'07:50B5 (_FindAlphaUp)',
  });
expectEqual('07:50B8 selects the nearest lower same-class VAT name',
  rom.editorFindAlphaVat('down',alphaOp(0x05,0x43),alphaVat), {
    direction:'down',sameType:true,sourceClass:0x05,carry:false,a:0,zero:true,
    op1:alphaOp(0x06,0x42),op3:alphaOp(0x06,0x42),
    vatPointer:0x9fb0,selectedIndex:2,compared:3,
    routine:'07:50B8 (_FindAlphaDn)',
  });
expectEqual('07:50B5 preserves OP1/OP3 and sets carry at the class endpoint',
  rom.editorFindAlphaVat('up',alphaOp(0x05,0x43),alphaVat), {
    direction:'up',sameType:true,sourceClass:0x05,carry:true,a:0xfe,zero:false,
    op1:alphaOp(0x05,0x43),op3:alphaOp(0x05,0x43),
    vatPointer:null,selectedIndex:null,compared:3,
    routine:'07:50B5 (_FindAlphaUp)',
  });
expectEqual('07:5247 aliases complex-list and list search classes',
  rom.editorFindAlphaVat('up',alphaOp(0x01,0x40),[
    alphaVatEntry(alphaIdentity(0x0d,0x41),0x9f90),
  ]).op1, alphaOp(0x0d,0x41));
expectEqual('07:5247 aliases types 18h/19h with class zero',
  rom.editorFindAlphaVat('up',alphaOp(0x18,0x40),[
    alphaVatEntry(alphaIdentity(0x19,0x41),0x9f80),
  ]).op1, alphaOp(0x19,0x41));
expectEqual('07:5199 gives the first OP name byte highest significance',
  rom.editorFindAlphaVat('up',[5,0x41,0x80,0,0,0,0,0,0,0,0],[
    alphaVatEntry([5,0x42,0x00,0,0,0,0,0,0],0x9f70),
    alphaVatEntry([5,0x41,0x70,0,0,0,0,0,0],0x9f60),
  ]).vatPointer, 0x9f70);
expectEqual('07:5151 FFh sentinel lets Up start from the lowest candidate',
  rom.editorFindAlphaVat('up',[5,0x7f,0xff,0,0,0,0,0,0,0,0],[
    alphaVatEntry(alphaIdentity(5,0x41),0x9f58),
    alphaVatEntry(alphaIdentity(5,0x42),0x9f57),
  ]).op1, alphaOp(5,0x41));
expectEqual('07:5151 FFh sentinel makes Dn report its endpoint',
  rom.editorFindAlphaVat('down',[5,0x40,0xff,0,0,0,0,0,0,0,0],[
    alphaVatEntry(alphaIdentity(5,0x41),0x9f56),
  ]).carry, true);
const staleNamedAlphaKey = [5,0x41,0,0xff,0xee,0xdd,0xcc,0xbb,0xaa,0x99,0x88];
expectEqual('07:50D6 zero-pads a named comparison key after its NUL',
  rom.editorFindAlphaVat('down',staleNamedAlphaKey,[
    alphaVatEntry(alphaIdentity(5,0x41),0x9f55),
  ]), {
    direction:'down',sameType:true,sourceClass:0x05,carry:true,a:0xfe,zero:false,
    op1:staleNamedAlphaKey,op3:staleNamedAlphaKey,
    vatPointer:null,selectedIndex:null,compared:1,
    routine:'07:50B8 (_FindAlphaDn)',
  });
expectEqual('07:50D6 keeps named successor selection independent of stale tail bytes',
  rom.editorFindAlphaVat('up',staleNamedAlphaKey,[
    alphaVatEntry(alphaIdentity(5,0x41),0x9f54),
    alphaVatEntry(alphaIdentity(5,0x42),0x9f53),
  ]).op1, alphaOp(5,0x42));
for (let continuationByte = 0; continuationByte <= 0xff; continuationByte++) {
  expectEqual('07:522E exhaustive selected OP extension byte',
    rom.editorFindAlphaVat('up',alphaOp(5,0x41,0xee,0xdd),[
      alphaVatEntry(alphaIdentity(5,0x42),0x9f53,0,continuationByte),
    ]).op1,
    alphaOp(5,0x42,continuationByte,0));
}
const staleFixedAlphaKey = [0,0x41,0x42,0x43,0xff,0xee,0xdd,0xcc,0xbb,0x77,0x66];
expectEqual('07:50E8 clears five fixed-token comparison-key tail bytes',
  rom.editorFindAlphaVat('down',staleFixedAlphaKey,[
    alphaVatEntry([0,0x41,0x42,0x43,0,0,0,0,0],0x9f52),
  ]).carry, true);
expectEqual('07:50E8 preserves all three fixed-token name bytes',
  rom.editorFindAlphaVat('up',staleFixedAlphaKey,[
    alphaVatEntry([0,0x41,0x42,0x44,0,0,0,0,0],0x9f51),
  ]).op1, [0,0x41,0x42,0x44,0,0,0,0,0,0,0]);
expectEqual('07:51BE rejects low and 72h first-name bytes',
  rom.editorFindAlphaVat('up',alphaOp(5,0x30),[
    alphaVatEntry(alphaIdentity(5,0x40),0x9f50),
    alphaVatEntry(alphaIdentity(5,0x72),0x9f40),
    alphaVatEntry(alphaIdentity(5,0x73),0x9f30),
  ]).op1, alphaOp(5,0x73));
expectEqual('07:5233 uses an archived page byte while inGroup is set',
  rom.editorFindAlphaVat('up',alphaOp(5,0x30),[
    alphaVatEntry(alphaIdentity(5,0x40),0x9f20,0x41),
  ],{inGroup:true}).op1, alphaOp(5,0x40));
const specialListEntry = {
  identity:[0x01,0x5d,0x40,0,0,0,0,0,0],
  continuationByte:0,pointer:0x9f10,page:0,
};
expectEqual('07:521B rejects the special list name by default',
  rom.editorFindAlphaVat(
    'up',[0x01,0x5c,0,0,0,0,0,0,0,0,0],[specialListEntry]).carry, true);
expectEqual('07:5227 accepts the special list name when IY+0 bit 0 is set',
  rom.editorFindAlphaVat(
    'up',[0x01,0x5c,0,0,0,0,0,0,0,0,0],[specialListEntry],
    {iy0Bit0:true}).op1, [...specialListEntry.identity,0,0]);
expectThrows('07:50B5 rejects a VAT entry without a pointer', RangeError,
  () => rom.editorFindAlphaVat('up',alphaOp(5,0),[
    {identity:alphaIdentity(5,1),continuationByte:0},
  ]));
expectThrows('07:50B5 rejects a nine-byte live OP scratch value', RangeError,
  () => rom.editorFindAlphaVat('up',alphaIdentity(5,0),[]));
expectThrows('07:50B5 requires the VAT continuation byte', RangeError,
  () => rom.editorFindAlphaVat('up',alphaOp(5,0),[
    {identity:alphaIdentity(5,1),pointer:0x9f00,page:0},
  ]));

const exhaustiveAlphaVat = Array.from({length:0x100}, (_, nameByte) => ({
  identity:alphaIdentity(nameByte & 1 ? 0x06 : 0x05,nameByte),
  continuationByte:0,
  pointer:0x9000 + (0xff - nameByte),
  page:0,
})).reverse();
const allowedAlphaNames = Array.from({length:0xbf}, (_, index) => index + 0x41)
  .filter(value => value !== 0x72);
for (let nameByte = 0; nameByte <= 0xff; nameByte++) {
  const source = alphaOp(0x05,nameByte);
  const up = rom.editorFindAlphaVat('up',source,exhaustiveAlphaVat);
  const down = rom.editorFindAlphaVat('down',source,exhaustiveAlphaVat);
  expectEqual('07:50B5 exhaustive one-byte alphabetic successor', {
    carry:up.carry,name:up.op1[1],pointer:up.vatPointer,
  }, (() => {
    const selected = allowedAlphaNames.find(value => value > nameByte);
    return selected === undefined
      ? {carry:true,name:nameByte,pointer:null}
      : {carry:false,name:selected,pointer:0x9000 + (0xff - selected)};
  })());
  expectEqual('07:50B8 exhaustive one-byte alphabetic predecessor', {
    carry:down.carry,name:down.op1[1],pointer:down.vatPointer,
  }, (() => {
    const selected = allowedAlphaNames.findLast(value => value < nameByte);
    return selected === undefined
      ? {carry:true,name:nameByte,pointer:null}
      : {carry:false,name:selected,pointer:0x9000 + (0xff - selected)};
  })());
}

const savedOperandBuffers = {
  op1:[0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09,0xaa,0xbb],
  savedE7:[0x05,0x42,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
  savedF2:[0x05,0x52,0x23,0x24,0x25,0x26,0x27,0x28,0x29],
};
const savedOperandState = (buffers, source, direction, carry,
                           incomingCarry = false) => {
  const input = (source === 'saved-E7' ? buffers.savedE7 : buffers.savedF2);
  const candidate = input.slice();
  candidate[1] += direction === 'up' ? 1 : -1;
  return {
    editorClass:0x04,editorSubClass:0,incomingCarry,
    vatSnapshot:carry ? [] : [
      alphaVatEntry(
        candidate,source === 'saved-E7' ? 0x9fe7 : 0x9ff2,0,0xa5),
    ],
  };
};
const savedOperandWalkerState = (direction, buffers = savedOperandBuffers,
                                 carry = false) => ({
  buffers,
  vatSnapshot:carry ? [] : ['saved-E7','saved-F2'].map((source, index) => {
    const input = source === 'saved-E7' ? buffers.savedE7 : buffers.savedF2;
    const candidate = input.slice();
    candidate[1] += direction === 'up' ? 1 : -1;
    return alphaVatEntry(candidate,0x9f00 - index * 0x10,0,0xa5);
  }),
});
expectEqual('39:5B10 preserves buffers and carry when bit 5 is clear', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-E7','up',0,savedOperandBuffers,{incomingCarry:true});
  return {
    branch:result.branch, searchCalled:result.searchCalled,
    carry:result.carry, copies:result.copies, buffers:result.buffers,
  };
})(), {
  branch:'gated-return',searchCalled:false,carry:true,copies:[],
  buffers:savedOperandBuffers,
});
expectEqual('39:5B10 restores E7 and saves a carry-clear alpha result', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-E7','up',0x20,savedOperandBuffers,
    savedOperandState(savedOperandBuffers,'saved-E7','up',false));
  return {
    branch:result.branch, searchInput:result.searchInput,
    carry:result.carry, copies:result.copies, buffers:result.buffers,
  };
})(), {
  branch:'save-result',searchInput:[...savedOperandBuffers.savedE7,0xaa,0xbb],
  carry:false,copies:[
    {from:0x85e7,to:0x8478,bytes:9,routine:'39:5AE1 → 00:1A92'},
    {from:0x8478,to:0x85e7,bytes:9,routine:'39:5AD2 → 00:1A92'},
  ],buffers:{
    op1:[0x05,0x43,0x13,0x14,0x15,0x16,0x17,0x18,0x19,0xa5,0],
    savedE7:[0x05,0x43,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
    savedF2:savedOperandBuffers.savedF2,
  },
});
expectEqual('39:5B38 carry exit leaves E7 unchanged after restoring F2', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-F2','down',0x20,savedOperandBuffers,
    savedOperandState(savedOperandBuffers,'saved-F2','down',true));
  return {
    branch:result.branch, searchInput:result.searchInput,
    carry:result.carry, copies:result.copies, buffers:result.buffers,
  };
})(), {
  branch:'search-carry',searchInput:[...savedOperandBuffers.savedF2,0xaa,0xbb],
  carry:true,copies:[
    {from:0x85f2,to:0x8478,bytes:9,routine:'39:5B00 → 00:1A92'},
  ],buffers:{
    op1:[...savedOperandBuffers.savedF2,0xaa,0xbb],
    savedE7:savedOperandBuffers.savedE7,
    savedF2:savedOperandBuffers.savedF2,
  },
});
expectEqual('39:5B10 applies the class-2 OP1 seed before E7 writeback', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-E7','up',0x20,savedOperandBuffers,{
      editorClass:2,specialResult:{carry:false},
    });
  return {
    branch:result.branch,carry:result.carry,
    op1:result.buffers.op1,savedE7:result.buffers.savedE7,
  };
})(), {
  branch:'save-result',carry:false,
  op1:[0x14,0x42,0x13,0x14,0x15,0x16,0x17,0x18,0x19,0xaa,0xbb],
  savedE7:[0x14,0x42,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
});
expectThrows('39:5B10 rejects an enabled search without its editor class',
  TypeError, () => rom.editorSavedOperandWrapper(
    'saved-E7','up',0x20,savedOperandBuffers,{vatSnapshot:[]}));
expectThrows('39:5B10 rejects an eleven-byte saved operand value',
  RangeError, () => rom.editorSavedOperandWrapper(
    'saved-E7','up',0x20,{...savedOperandBuffers,savedE7:new Array(11).fill(0)},
    {editorClass:4,vatSnapshot:[]}));
expectThrows('39:5B10 rejects a nine-byte live OP scratch value',
  RangeError, () => rom.editorSavedOperandWrapper(
    'saved-E7','up',0,{...savedOperandBuffers,op1:new Array(9).fill(0)},{}));

const savedOperandProjection = result => ({
  branch:result.branch,
  searchInput:result.searchInput,
  carry:result.carry,
  buffers:result.buffers,
});
let savedOperandWrapperStates = 0;
for (const source of ['saved-E7','saved-F2']) {
  for (const direction of ['up','down']) {
    for (let recordFlags = 0; recordFlags <= 0xff; recordFlags++) {
      for (const incomingCarry of [false,true]) {
        for (const searchCarry of [false,true]) {
          const searchState = savedOperandState(
            savedOperandBuffers,source,direction,searchCarry,incomingCarry);
          const translated = rom.editorSavedOperandWrapper(
            source,direction,recordFlags,savedOperandBuffers,searchState);
          const raw = runRawSavedOperandWrapper(
            source,direction,recordFlags,savedOperandBuffers,{
              incomingCarry,carry:translated.carry,
              op1:translated.buffers.op1,
            });
          expectEqual('39:5B10–5B44 exhaustive wrapper state',
            savedOperandProjection(translated), raw);
          savedOperandWrapperStates++;
        }
      }
    }
  }
}

// _Mov9B leaves both live extension bytes untouched when it restores E7/F2.
for (const source of ['saved-E7','saved-F2']) {
  for (const position of [9,10]) {
    for (let value = 0; value <= 0xff; value++) {
      const op1 = [...new Array(9).fill(0x55),0,0];
      op1[position] = value;
      const buffers = {...savedOperandBuffers,op1};
      const translated = rom.editorSavedOperandWrapper(
        source,'up',0x20,buffers,{editorClass:4,vatSnapshot:[]});
      const expectedOp1 = [
        ...(source === 'saved-E7' ? buffers.savedE7 : buffers.savedF2),
        op1[9],op1[10],
      ];
      expectEqual('39:5AE1/5B00 exhaustive live-extension preservation',
        savedOperandProjection(translated),
        runRawSavedOperandWrapper(source,'up',0x20,buffers,
          {carry:true,op1:expectedOp1}));
    }
  }
}
expectEqual('39:5B10–5B44 exhaustive wrapper state count',
  savedOperandWrapperStates, 0x1000);

// Exercise every value in every restored byte. An empty VAT makes the search
// carry, so OP1 retains the nine-byte source image and the live extensions.
for (const source of ['saved-E7','saved-F2']) {
  for (let position = 0; position < 9; position++) {
    for (let value = 0; value <= 0xff; value++) {
      const sourceValue = new Array(9).fill(0);
      sourceValue[position] = value;
      const buffers = {
        op1:[...new Array(9).fill(0x55),0xaa,0xbb],
        savedE7:source === 'saved-E7'
          ? sourceValue : new Array(9).fill(0x11),
        savedF2:source === 'saved-F2'
          ? sourceValue : new Array(9).fill(0x22),
      };
      const translated = rom.editorSavedOperandWrapper(
        source,'up',0x20,buffers,{editorClass:4,vatSnapshot:[]});
      expectEqual('39:5AE1/5B00 exhaustive restore basis',
        savedOperandProjection(translated),
        runRawSavedOperandWrapper(source,'up',0x20,buffers,
          {carry:true,op1:[...sourceValue,0xaa,0xbb]}));
    }
  }
}

// A selected successor exercises writeback for every payload-byte value.
for (const source of ['saved-E7','saved-F2']) {
  for (let position = 2; position < 9; position++) {
    for (let value = 0; value <= 0xff; value++) {
      const sourceValue = alphaIdentity(5,0x42);
      const resultValue = alphaIdentity(5,0x43);
      resultValue[position] = value;
      const buffers = {
        op1:[...new Array(9).fill(0x55),0xaa,0xbb],
        savedE7:source === 'saved-E7' ? sourceValue : alphaIdentity(5,0x62),
        savedF2:source === 'saved-F2' ? sourceValue : alphaIdentity(5,0x62),
      };
      const searchState = {editorClass:4,vatSnapshot:[
        alphaVatEntry(resultValue,0x9f00,0,0xa5),
      ]};
      const translated = rom.editorSavedOperandWrapper(
        source,'up',0x20,buffers,searchState);
      expectEqual('39:5AD2/5B08 exhaustive payload writeback basis',
        savedOperandProjection(translated),
        runRawSavedOperandWrapper(source,'up',0x20,buffers,
          {carry:false,op1:[...resultValue,0xa5,0]}));
    }
  }
}

const alphaSearchProjection = result => ({
  branch:result.branch, specialPath:result.specialPath || null,
  loopCount:result.loopCount === undefined ? 0 : result.loopCount,
  emitted:(result.effects || []).filter(effect => effect.kind === 'emit-token')
    .map(effect => effect.code),
});
const alphaSearchCases = [
  ['ascending class-2 marker', 'up', 0x02, 0x00,
   {specialResult:{carry:false}},
   {op1:alphaOp(2,0),specialResult:{carry:false}}],
  ['descending class-2 empty saved operand', 'down', 0x02, 0x00,
   {savedOperand:[0x02,0,0,0,0,0,0,0,0],specialResult:{carry:false}},
   {op1:alphaOp(2,0),savedOperand:[0x02,0,0,0,0,0,0,0,0],
    specialResult:{carry:false}}],
  ['ascending VAT-search carry', 'up', 0x04, 0x00,
   {searchResults:[{carry:true}]},
   {op1:alphaOp(5,0x42),vatSnapshot:[
     alphaVatEntry(alphaIdentity(5,0x41),0x9f00),
   ]}],
  ['ascending VAT-search clear', 'up', 0x04, 0x00,
   {searchResults:[{carry:false}]},
   {op1:alphaOp(5,0x41),vatSnapshot:[
     alphaVatEntry(alphaIdentity(5,0x42),0x9f00),
   ]}],
  ['ascending search repeat then clear', 'up', 0x03, 0x01,
   {searchResults:[{carry:false,postCode:0x06},{carry:false,postCode:0x05}]},
   {op1:alphaOp(5,0x41),vatSnapshot:[
     alphaVatEntry(alphaIdentity(6,0x42),0x9f00),
     alphaVatEntry(alphaIdentity(5,0x43),0x9ef0),
   ]}],
  ['descending VAT-search post-search exit', 'down', 0x03, 0x01,
   {searchResults:[{carry:false,postCode:0x05}]},
   {op1:alphaOp(5,0x43),vatSnapshot:[
     alphaVatEntry(alphaIdentity(5,0x42),0x9f00),
   ]}],
];
for (const [label, direction, editorClass, editorSubClass,
            rawOptions, translatedOptions] of alphaSearchCases) {
  const raw = runRawAlphaSearch(direction,editorClass,editorSubClass,rawOptions);
  const translated = rom.editorAlphaSearch(
    direction,editorClass,editorSubClass,translatedOptions);
  expectEqual(`39:59E0/59F9 ${label} byte-flow`,
    alphaSearchProjection(translated), alphaSearchProjection(raw));
}
expectEqual('39:59E0 derives alphabetic search from a raw VAT snapshot', (() => {
  const result = rom.editorAlphaSearch('up',0x04,0,{
    op1:alphaOp(0x05,0x42),vatRam:alphaRam,
  });
  return {
    branch:result.branch,carry:result.carry,op1:result.op1,
    vatPointer:result.vatPointer,
  };
})(), {
  branch:'search-complete',carry:false,
  op1:[0x05,0x43,0x41,0x54,0,0,0,0,0,0,0],vatPointer:0x9000,
});
expectThrows('39:59E0 rejects an omitted VAT snapshot', TypeError,
  () => rom.editorAlphaSearch('up',0x04,0,{op1:alphaOp(5,0x41)}));
expectThrows('39:59F9 rejects an omitted class-2 special result', TypeError,
  () => rom.editorAlphaSearch('down',0x02,0,{op1:alphaOp(2,0)}));
expectThrows('39:59F9 rejects a carrying class-2 1BAF result', TypeError,
  () => rom.editorAlphaSearch('down',0x02,0,
    {op1:alphaOp(2,0),specialResult:{carry:true}}));

let alphaSearchStates = 0;
for (const direction of ['up','down']) {
  for (const editorClass of [0x00,0x02,0x03,0x04,0xff]) {
    for (const editorSubClass of [0x00,0x01,0xff]) {
      if (editorClass === 0x02) {
        const options = direction === 'down'
          ? {op1:alphaOp(2,0),savedOperand:new Array(9).fill(0),
             specialResult:{carry:false}}
          : {op1:alphaOp(2,0),specialResult:{carry:false}};
        const raw = runRawAlphaSearch(direction,editorClass,editorSubClass,options);
        const translated = rom.editorAlphaSearch(
          direction,editorClass,editorSubClass,options);
        expectEqual('39:59E0/59F9 class-2 byte-flow basis',
          alphaSearchProjection(translated), alphaSearchProjection(raw));
        alphaSearchStates++;
        continue;
      }
      for (const carry of [false,true]) {
        const result = {carry};
        if (!carry && editorClass === 0x03 && editorSubClass === 0x01)
          result.postCode = 0x05;
        const rawOptions = {searchResults:[result]};
        const sourceName = direction === 'up'
          ? carry ? 0x42 : 0x41
          : carry ? 0x41 : 0x42;
        const candidateName = direction === 'up' ? 0x42 : 0x41;
        const translatedOptions = {
          op1:alphaOp(5,sourceName),
          vatSnapshot:carry ? [] : [
            alphaVatEntry(alphaIdentity(5,candidateName),0x9f00),
          ],
        };
        const raw = runRawAlphaSearch(
          direction,editorClass,editorSubClass,rawOptions);
        const translated = rom.editorAlphaSearch(
          direction,editorClass,editorSubClass,translatedOptions);
        expectEqual('39:59E0/59F9 alpha-search byte-flow basis',
          alphaSearchProjection(translated), alphaSearchProjection(raw));
        alphaSearchStates++;
      }
    }
  }
}
expectEqual('39:59E0/59F9 projected alpha-search state count', alphaSearchStates, 54);

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
expectEqual('39:4A74 ordinary token class dispatch',
  rom.editorTokenDispatch(layout, 0x2d), {
    raw:0x2d, iy2:0xff, iy9:0, coarseClass:0x03, normalizedClass:0x03,
    adjustments:[], handlerPointer:0x5f97, handlerRows:3,
    kind:'handlerLookup', routine:'39:4A74 → 39:4C27',
  });
expectEqual('39:4A74 fraction-context class remap',
  rom.editorTokenDispatch(layout, 0x2d, {iy9:1}).normalizedClass, 0x2b);
expectEqual('39:4A74 exponent context applies all three IY+2 tests',
  rom.editorTokenDispatch(layout, 0x3b, {iy2:0}), {
    raw:0x3b, iy2:0, iy9:0, coarseClass:0x11, normalizedClass:0x3c,
    adjustments:[
      'IY+2 bit 4 clear: raw-1',
      'IY+2 bit 6 clear: increment',
      'IY+2 bit 5 clear: increment',
    ], handlerPointer:0x619c, handlerRows:1,
    kind:'handlerLookup', routine:'39:4A74 → 39:4C27',
  });
expectEqual('39:4A74 preserves the measured-template handoff',
  rom.editorTokenDispatch(layout, 0x3d), {
    raw:0x3d, iy2:0xff, iy9:0, coarseClass:null, normalizedClass:null,
    adjustments:[], handlerPointer:null, handlerRows:null,
    kind:'templateHandoff', routine:'39:4A74 → 39:672E',
  });
expectEqual('39:4C27 keeps class zero as a non-handler table entry',
  rom.editorTokenDispatch(layout, 0x2a), {
    raw:0x2a, iy2:0xff, iy9:0, coarseClass:0, normalizedClass:0,
    adjustments:[], handlerPointer:0xc97a, handlerRows:null,
    kind:'handlerLookup', routine:'39:4A74 → 39:4C27',
  });
expectEqual('39:50CF clamps a short argument list and returns its window',
  rom.editorArgumentClamp(9, 4, {kbdKey:0x04}), {
    argumentIndex:9, argumentCount:4, clampedArgument:3, windowStart:0,
    kbdKey:0x04, continuation:'return-window-start', routine:'39:50CF',
  });
expectEqual('39:50CF computes the six-row overflow window for long lists',
  rom.editorArgumentClamp(9, 10, {kbdKey:0x04}), {
    argumentIndex:9, argumentCount:10, clampedArgument:9, windowStart:3,
    kbdKey:0x04, continuation:'cross-page-jump', routine:'39:50CF',
  });
expectEqual('39:50CF leaves an empty argument list at zero',
  rom.editorArgumentClamp(0xff, 0), {
    argumentIndex:0xff, argumentCount:0, clampedArgument:0, windowStart:0,
    kbdKey:null, continuation:'cross-page-jump', routine:'39:50CF',
  });
expectEqual('39:5101 maps argument slots to seven visible rows',
  [rom.editorRowFromArg(0),rom.editorRowFromArg(6),rom.editorRowFromArg(0xff)], [
    {argumentIndex:0,row:1,routine:'39:5101'},
    {argumentIndex:6,row:7,routine:'39:5101'},
    {argumentIndex:0xff,row:7,routine:'39:5101'},
  ]);
expectEqual('39:513E restores the caller baseline row after layout',
  rom.editorLayoutArgument(9, 10, {kbdKey:0x04,baselineRow:4}), {
    argumentIndex:9, argumentCount:10, clampedArgument:9, windowStart:3,
    kbdKey:0x04, continuation:'cross-page-jump',
    routine:'39:513E → 39:50CF → 39:5101',
    visibleRow:7, baselineRow:4, restoredRow:4,
  });
expectEqual('39:4C5A computes a visible slot and 984A cell base',
  rom.editorSubexpressionWindow(5, 3, 1, 0, 4), {
    argumentIndex:5, currentRow:3, rowDelta:2, slot:3,
    cellPointer:0x984a, cellOffset:6, cellAddress:0x9850,
    baselineRow:1, preEmissionRow:0, recordFlags:0, argumentCount:4,
    menuCurrent:null, measuresArgumentWidths:true, routine:'39:4C5A',
    branch:'argument-list', emission:'arglist', finalRow:1,
    continuation:'return',
  });
expectEqual('39:4C5A keeps a slot-before-window jump explicit',
  rom.editorSubexpressionWindow(1, 3, 1, 0, 4), {
    argumentIndex:1, currentRow:3, baselineRow:1, recordFlags:0,
    argumentCount:4, rowDelta:2, branch:'argument-before-visible-row',
    emission:null, continuation:'cross-page-jump', routine:'39:4C5A',
  });
expectEqual('39:4C5A preserves styled and empty-menu exits',
  [
    rom.editorSubexpressionWindow(5, 3, 1, 0x20, 4).branch,
    rom.editorSubexpressionWindow(5, 3, 1, 0, 0, {menuCurrent:0x41}).branch,
  ], ['styled-argument','empty-menu-fallback']);
expectEqual('39:4CA4 emits a direct handler-cell slot offset',
  rom.editorSubexpressionCell(2, 0x6000, 4, 0, 3), {
    slot:2, cellPointer:0x6000, cellOffset:4, cellAddress:0x6004,
    baselineRow:4, preEmissionRow:null, recordFlags:0, argumentCount:3,
    menuCurrent:null, measuresArgumentWidths:true, routine:'39:4CA4',
    branch:'argument-list', emission:'arglist', finalRow:4,
    continuation:'return',
  });
expectEqual('39:5167 returns immediately for an empty argument list',
  rom.editorAdvanceArgument(8, 0, 0, 1, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:0, currentRow:1,
    recordFlags:0, winTop:null,
    routine:'39:5167', lastArgument:null, nextArgument:0, rowStep:0,
    placementRow:null, nextRow:null, branch:'empty',
    effects:[{kind:'set-row-for-token',routine:'39:5447'}],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 stops at the final argument',
  rom.editorAdvanceArgument(8, 3, 4, 1, 0), {
    layoutClass:8, argumentIndex:3, argumentCount:4, currentRow:1,
    recordFlags:0, winTop:null,
    routine:'39:5167', lastArgument:3, nextArgument:3, rowStep:0,
    placementRow:null, nextRow:null, branch:'at-or-past-last',
    effects:[{kind:'set-row-for-token',routine:'39:5447'}],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 advances an ordinary argument by one row',
  rom.editorAdvanceArgument(8, 0, 4, 1, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:1,
    recordFlags:0, winTop:null,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:1,
    rowLimit:7, placementRow:2, nextRow:null, branch:'in-row',
    effects:[
      {kind:'emit-argument-index',argument:0,routine:'39:4E0A'},
      {kind:'advance-row',rows:1,value:2},
      {kind:'emit-argument-index',argument:1,routine:'39:4E0A'},
      {kind:'find-alpha',direction:'up',source:'saved-E7',routine:'39:5B10'},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 advances a low class-06 argument by two rows',
  rom.editorAdvanceArgument(6, 0, 4, 1, 0), {
    layoutClass:6, argumentIndex:0, argumentCount:4, currentRow:1,
    recordFlags:0, winTop:null,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:2,
    rowLimit:6, placementRow:3, nextRow:null, branch:'in-row',
    effects:[
      {kind:'emit-argument-index',argument:0,routine:'39:4E0A'},
      {kind:'advance-row',rows:2,value:3},
      {kind:'emit-argument-index',argument:1,routine:'39:4E0A'},
      {kind:'find-alpha',direction:'up',source:'saved-E7',routine:'39:5B10'},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 sends class-06 row six to overflow before a two-row step',
  rom.editorAdvanceArgument(6, 0, 4, 6, 0).branch,
  'subexpression-overflow');
expectEqual('39:5167 class-06 row six bypasses the styled overflow branch',
  rom.editorAdvanceArgument(6, 0, 4, 6, 0x20).branch,
  'subexpression-overflow');
expectEqual('39:5167 sends an unstyled row-seven argument to 39:4C5A',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:7,
    recordFlags:0, winTop:null,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:1,
    rowLimit:7, placementRow:7, nextRow:null,
    branch:'subexpression-overflow',
    effects:[
      {kind:'emit-subexpression',routine:'39:4C5A'},
      {kind:'restore-row',value:7},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'subexpression-window',
  });
expectEqual('39:5167 preserves the styled row-seven scroll sequence',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    winTop:5,savedOperandState:savedOperandWalkerState('up'),
  }).effects.map(({transition,...effect}) => effect), [
      {kind:'find-alpha',direction:'up',source:'saved-F2',routine:'39:5B2B',carry:false},
      {kind:'emit-argument-index',argument:0,routine:'39:4E0A'},
      {kind:'set-overflow',curCol:1,routine:'39:6712'},
      {kind:'save-window-top',value:5},
      {kind:'set-window-top',value:1},
      {kind:'scroll-editor',direction:'forward',routine:'39:3C81'},
      {kind:'find-alpha',direction:'up',source:'saved-E7',routine:'39:5B10'},
      {kind:'emit-saved-operand-tail',argument:1,routine:'39:5B46'},
      {kind:'finish-forward-overflow',direction:'forward',branch:'emit-cue',
        remainingArguments:null,emission:{row:1,column:1,code:0x1e},
        cursorPreserved:true,routine:'39:66FE'},
      {kind:'restore-window-top',value:5},
      {kind:'set-row-for-token',routine:'39:5447'},
    ]);
expectEqual('39:5167 derives the styled row-seven scroll branch from VAT',
  (() => {
    const result = rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
      winTop:5,savedOperandState:savedOperandWalkerState('up'),
    });
    return {
      branch:result.branch,savedF2Carry:result.savedF2Carry,
      f2:result.effects[0].transition.buffers.savedF2,
      e7:result.effects[6].transition.buffers.savedE7,
    };
  })(), {
    branch:'styled-overflow',savedF2Carry:false,
    f2:[0x05,0x53,0x23,0x24,0x25,0x26,0x27,0x28,0x29],
    e7:[0x05,0x43,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
  });
expectEqual('39:5167 leaves a missing styled VAT state explicit',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {winTop:5}), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:7,
    recordFlags:0x20, winTop:5,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:1,
    rowLimit:7, placementRow:null, nextRow:null,
    branch:'styled-overflow-unresolved',
    effects:[
      {kind:'find-alpha',direction:'up',source:'saved-F2',
        routine:'39:5B2B',unresolved:'VAT state'},
    ],
    continuation:'saved-F2-search',
  });
expectEqual('39:5167 stops styled overflow when saved-F2 search carries',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandState:savedOperandWalkerState('up',savedOperandBuffers,true),
  }).branch, 'styled-overflow-carry');
expectEqual('39:5167 composes F2 and E7 ascending-search state', (() => {
  const result = rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandState:savedOperandWalkerState('up'),
  });
  const f2 = result.effects.find(effect => effect.source === 'saved-F2');
  const e7 = result.effects.find(effect => effect.source === 'saved-E7');
  return {
    branch:result.branch,carry:result.savedF2Carry,
    f2Input:f2.transition.searchInput,
    f2Saved:f2.transition.buffers.savedF2,
    e7Input:e7.transition.searchInput,
    e7Saved:e7.transition.buffers.savedE7,
    e7SeesF2:e7.transition.buffers.savedF2,
  };
})(), {
  branch:'styled-overflow',carry:false,
  f2Input:[...savedOperandBuffers.savedF2,0xaa,0xbb],
  f2Saved:[0x05,0x53,0x23,0x24,0x25,0x26,0x27,0x28,0x29],
  e7Input:[...savedOperandBuffers.savedE7,0xa5,0],
  e7Saved:[0x05,0x43,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
  e7SeesF2:[0x05,0x53,0x23,0x24,0x25,0x26,0x27,0x28,0x29],
});
expectEqual('39:5167 derives the styled carry branch from the F2 wrapper',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandState:savedOperandWalkerState('up',savedOperandBuffers,true),
  }).branch, 'styled-overflow-carry');
expectThrows('39:5167 rejects saved-operand state without buffers',
  TypeError, () => rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandState:{vatSnapshot:[]},
  }));
expectEqual('39:523B stops before decrementing the first argument',
  rom.editorRetreatArgument(8, 0, 4, 4, 1, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:4,
    baselineRow:1, recordFlags:0, winTop:null,
    routine:'39:523B', nextArgument:0, rowStep:0, placementRow:null,
    nextRow:null, branch:'at-first', effects:[],
    continuation:'action-03-first-argument',
  });
expectEqual('39:523B retreats an ordinary argument by one row',
  rom.editorRetreatArgument(8, 2, 4, 4, 1, 0), {
    layoutClass:8, argumentIndex:2, argumentCount:4, currentRow:4,
    baselineRow:1, recordFlags:0, winTop:null,
    routine:'39:523B', nextArgument:1, rowStep:1,
    twoRowUnderflow:false, placementRow:3, nextRow:null, branch:'in-row',
    effects:[
      {kind:'emit-argument-index',argument:2,routine:'39:4E0A'},
      {kind:'retreat-row',rows:1,value:3},
      {kind:'emit-argument-index',argument:1,routine:'39:4E0A'},
      {kind:'find-alpha',direction:'down',source:'saved-E7',routine:'39:5B1D'},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'row-token-tail',
  });
expectEqual('39:523B executes the E7 descending-search transition', (() => {
  const result = rom.editorRetreatArgument(8, 2, 4, 4, 1, 0x20, {
    savedOperandState:savedOperandWalkerState('down'),
  });
  const effect = result.effects.find(item => item.source === 'saved-E7');
  return {
    branch:result.branch,
    direction:effect.transition.direction,
    input:effect.transition.searchInput,
    result:effect.transition.buffers.savedE7,
  };
})(), {
  branch:'in-row',direction:'down',input:[...savedOperandBuffers.savedE7,0xaa,0xbb],
  result:[0x05,0x41,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
});
expectEqual('39:523B retreats a class-06 low argument by two rows',
  rom.editorRetreatArgument(6, 3, 4, 3, 1, 0).placementRow, 1);
expectEqual('39:523B sends a class-06 row-two retreat to 39:4C5A',
  rom.editorRetreatArgument(6, 3, 4, 2, 1, 0).branch,
  'subexpression-overflow');
expectEqual('39:523B class-06 row two bypasses the styled overflow branch',
  rom.editorRetreatArgument(6, 3, 4, 2, 1, 0x20).branch,
  'subexpression-overflow');
expectEqual('39:523B sends a baseline-row retreat to 39:4C5A',
  rom.editorRetreatArgument(8, 2, 4, 1, 1, 0).branch,
  'subexpression-overflow');
expectEqual('39:523B preserves the styled reverse scroll sequence',
  rom.editorRetreatArgument(
    8, 2, 12, 1, 1, 0x20, {
      winTop:5,winBottom:7,
      savedOperandState:savedOperandWalkerState('down'),
    }).effects.map(({transition,...effect}) => effect), [
    {kind:'find-alpha',direction:'down',source:'saved-F2',routine:'39:5B38',carry:false},
    {kind:'emit-argument-index',argument:2,routine:'39:4E0A'},
    {kind:'set-overflow',curCol:1,routine:'39:6712'},
    {kind:'save-window-top',value:5},
    {kind:'set-window-top',value:1},
    {kind:'scroll-editor',direction:'reverse',routine:'39:3C93'},
    {kind:'find-alpha',direction:'down',source:'saved-E7',routine:'39:5B1D'},
    {kind:'emit-saved-operand-tail',argument:1,routine:'39:5B46'},
    {kind:'finish-reverse-overflow',remainingArguments:11,
      branch:'window-bottom',cue:{
        direction:'reverse',argumentIndex:1,argumentCount:12,winBottom:7,
        remainingArguments:11,branch:'emit-cue',
        emission:{row:6,column:1,code:0x1f},cursorPreserved:true,
        routine:'39:66E9',
      },routine:'39:66E9'},
    {kind:'restore-window-top',value:5},
    {kind:'set-row-for-token',routine:'39:5447'},
  ]);
expectEqual('39:523B stops styled overflow when saved-F2 search carries',
  rom.editorRetreatArgument(8, 2, 4, 1, 1, 0x20, {
    savedOperandState:savedOperandWalkerState('down',savedOperandBuffers,true),
  }).branch, 'styled-overflow-carry');
expectEqual('39:51F1 sends a nonzero argument through the reverse walker', {
  branch:rom.editorFirstArgumentAction(8, 2, 4, 4, 1, 0).branch,
  delegate:rom.editorFirstArgumentAction(8, 2, 4, 4, 1, 0).delegate.branch,
  nextArgument:rom.editorFirstArgumentAction(8, 2, 4, 4, 1, 0)
    .delegate.nextArgument,
}, {branch:'reverse-walker',delegate:'in-row',nextArgument:1});
expectEqual('39:51F1 bit 0 returns through the row-token tail',
  rom.editorFirstArgumentAction(8, 0, 4, 4, 1, 0, {editorFlags:1}), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:4,
    baselineRow:1, recordFlags:0, editorFlags:1, editorFlagBit0:true,
    routine:'39:51F1', iterations:0, finalArgument:0, firstVisibleSlot:null,
    preCallRow:null, highlightRow:null, finalRow:null,
    branch:'row-token-tail',
    effects:[{kind:'set-row-for-token',routine:'39:51EE → 39:5447'}],
    continuation:'row-token-tail',
  });
expectEqual('39:50A1 wraps a zero short-list counter through 256 calls',
  rom.editorFirstArgumentAction(8, 0, 0, 4, 1, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:0, currentRow:4,
    baselineRow:1, recordFlags:0, editorFlags:0, editorFlagBit0:false,
    routine:'39:51F1', iterations:256, finalArgument:0,
    firstVisibleSlot:null, preCallRow:null, highlightRow:null, finalRow:null,
    branch:'short-list-loop', effects:[
      {kind:'set-loop-counter',address:0x844d,value:0},
      {kind:'repeat-call-advance-argument',iterations:256,
        counterAddress:0x844d,counterFinal:0,
        counterUpdate:'decrement-after-call',routine:'39:50A1 → 39:5167'},
      {kind:'set-row-for-token',routine:'39:50AD → 39:5447'},
    ], continuation:'row-token-tail',
  });
expectEqual('39:50A1 calls once per nonzero short-list counter value', {
  one:rom.editorFirstArgumentAction(8, 0, 1, 4, 1, 0).iterations,
  seven:rom.editorFirstArgumentAction(8, 0, 7, 4, 1, 0).iterations,
}, {one:1,seven:7});
expectEqual('39:51F1 wraps the wide-list baseline row and selects its last slot',
  (() => {
    const result = rom.editorFirstArgumentAction(8, 0, 8, 4, 0, 0);
    return {
      branch:result.branch, finalArgument:result.finalArgument,
      firstVisibleSlot:result.firstVisibleSlot, preCallRow:result.preCallRow,
      highlightRow:result.highlightRow, finalRow:result.finalRow,
      effects:result.effects,
    };
  })(), {
    branch:'last-visible-argument', finalArgument:7, firstVisibleSlot:0,
    preCallRow:0xff, highlightRow:7, finalRow:null, effects:[
      {kind:'clear-saved-F2',address:0x85f2,value:0},
      {kind:'set-argument-index',value:7},
      {kind:'lookup-handler-row',rowSource:0x85df,routine:'39:4DCA'},
      {kind:'set-row',value:0xff},
      {kind:'emit-subexpression-from-slot',slot:0,routine:'39:4CA4'},
      {kind:'set-row-column',row:7,column:0},
      {kind:'emit-highlighted-argument',argument:7,routine:'39:4E14'},
      {kind:'set-row-for-token',routine:'39:51EE → 39:5447'},
    ],
  });
expectEqual('39:51F1 keeps maximum-count arithmetic byte-sized',
  (() => {
    const result = rom.editorFirstArgumentAction(8, 0, 0xff, 4, 0, 0);
    return [result.finalArgument,result.firstVisibleSlot,result.preCallRow];
  })(), [0xfe,0xf7,0xff]);
expectEqual('39:52A5 calls the forward walker once for a nonzero delta',
  (() => {
    const result = rom.editorAdvanceAction(
      8, 2, 7, 4, 0, {baselineRow:4,kbdKey:4});
    return {
      branch:result.branch, delta:result.delta,
      advanceCalls:result.advanceCalls,
      delegateBranch:result.delegate.branch,
      delegateNextArgument:result.delegate.nextArgument,
      delegateTail:result.delegate.effects.at(-1),
      effects:result.effects,
    };
  })(), {
    branch:'advance-once', delta:4, advanceCalls:1,
    delegateBranch:'in-row', delegateNextArgument:3,
    delegateTail:{kind:'set-row-for-token',routine:'39:5447'},
    effects:[
      {kind:'delegate-advance-argument',routine:'39:52B3 → 39:5167'},
      {kind:'set-row-for-token',routine:'39:52B6 → 39:52A2 → 39:5447'},
    ],
  });
expectEqual('39:52A5 lays out argument zero for a zero delta and clear bit 0',
  rom.editorAdvanceAction(8, 6, 7, 4, 0, {baselineRow:4,kbdKey:4}), {
    layoutClass:8, argumentIndex:6, argumentCount:7, currentRow:4,
    recordFlags:0, lastArgument:6, delta:0,
    editorFlags:0, editorFlagBit0:false, baselineRow:4, kbdKey:4,
    routine:'39:52A5', advanceCalls:0,
    layout:{
      argumentIndex:0, argumentCount:7, clampedArgument:0, windowStart:0,
      kbdKey:4, continuation:'return-window-start',
      routine:'39:513E → 39:50CF → 39:5101', visibleRow:1,
      baselineRow:4, restoredRow:4,
    },
    delegate:null,
    branch:'layout-first-argument', effects:[
      {kind:'layout-argument',argument:0,routine:'39:513E'},
    ], continuation:'argument-layout',
  });
expectEqual('39:52A5 uses the row-token tail for a zero delta and set bit 0',
  rom.editorAdvanceAction(8, 6, 7, 4, 0, {editorFlags:1}).branch,
  'row-token-tail');
expectEqual('39:52A5 preserves the terminating zero-count byte state', {
  branch:rom.editorAdvanceAction(8, 0xff, 0, 4, 0, {baselineRow:0}).branch,
  advanceCalls:rom.editorAdvanceAction(
    8, 0xff, 0, 4, 0, {baselineRow:0}).advanceCalls,
  layoutArgument:rom.editorAdvanceAction(8, 0xff, 0, 4, 0, {baselineRow:0})
    .layout.argumentIndex,
}, {branch:'layout-first-argument',advanceCalls:0,layoutArgument:0});
expectEqual('39:52A5 sends wrapped subtraction states through one call', [
  rom.editorAdvanceAction(8, 2, 0, 4, 0).delegate.branch,
  rom.editorAdvanceAction(8, 9, 7, 4, 0).delegate.branch,
  rom.editorAdvanceAction(8, 9, 7, 4, 0).delta,
], ['empty','at-or-past-last',0xfd]);
expectThrows('39:5167 rejects a non-object saved-operand state', TypeError,
  () => rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandState:1,
  }));
// The increment-wrap guard in the bytes cannot fire after the preceding
// unsigned count/index predicate: count is nonzero and index <= count-2.
// Exhaust the complete byte-pair domain so later condition rewrites cannot
// accidentally make that guard reachable.
for (let argumentCount = 0; argumentCount <= 0xff; argumentCount++)
  for (let argumentIndex = 0; argumentIndex <= 0xff; argumentIndex++)
    if (rom.editorAdvanceArgument(
      8, argumentIndex, argumentCount, 1, 0).branch === 'argument-wrap-guard')
      throw new Error('39:5167 increment-wrap guard became reachable');

// Exhaust every layout-class byte and relevant visible row for both walkers.
// The forward threshold is row 6 for a two-row class-06 slot and row 7
// otherwise. The reverse path tests the new slot after decrementing 85E0.
for (let layoutClass = 0; layoutClass <= 0xff; layoutClass++) {
  for (let argumentIndex = 0; argumentIndex <= 0xfd; argumentIndex++) {
    const rowStep = layoutClass === 6 && argumentIndex <= 2 ? 2 : 1;
    const rowLimit = rowStep === 2 ? 6 : 7;
    for (let currentRow = 0; currentRow <= 7; currentRow++) {
      const result = rom.editorAdvanceArgument(
        layoutClass, argumentIndex, argumentIndex + 2, currentRow, 0);
      expectEqual('39:5167 exhaustive row predicate', [
        result.rowStep, result.rowLimit, result.branch,
      ], [
        rowStep, rowLimit,
        currentRow < rowLimit ? 'in-row' : 'subexpression-overflow',
      ]);
    }
  }
  for (let argumentIndex = 1; argumentIndex <= 0xff; argumentIndex++) {
    const nextArgument = argumentIndex - 1;
    const rowStep = layoutClass === 6 && nextArgument <= 2 ? 2 : 1;
    for (let currentRow = 0; currentRow <= 7; currentRow++) {
      const twoRowUnderflow = rowStep === 2 && currentRow < 3;
      const result = rom.editorRetreatArgument(
        layoutClass, argumentIndex, 0xff, currentRow, 1, 0);
      expectEqual('39:523B exhaustive row predicate', [
        result.nextArgument, result.rowStep, result.twoRowUnderflow,
        result.branch,
      ], [
        nextArgument, rowStep, twoRowUnderflow,
        !twoRowUnderflow && currentRow > 1
          ? 'in-row' : 'subexpression-overflow',
      ]);
    }
  }
}

// Exhaust both controller actions over every count/index byte pair and both
// IY+1Dh bit-0 outcomes. This includes count underflow, index subtraction
// wrap, the 256-iteration zero counter, and the action-04 one-call exit.
let firstArgumentControllerStates = 0;
let argumentAdvanceControllerStates = 0;
let action03ReverseStates = 0;
let action03FlagTailStates = 0;
let action03ZeroCountStates = 0;
let action03ShortStates = 0;
let action03WideStates = 0;
let action04AdvanceOnceStates = 0;
let action04FlagTailStates = 0;
let action04LayoutStates = 0;
let action04LowerIndexPairs = 0;
let action04HigherIndexPairs = 0;
let action04ZeroCountPairs = 0;
for (const editorFlags of [0, 1]) {
  for (let argumentCount = 0; argumentCount <= 0xff; argumentCount++) {
    for (let argumentIndex = 0; argumentIndex <= 0xff; argumentIndex++) {
      const first = rom.editorFirstArgumentAction(
        8, argumentIndex, argumentCount, 4, 0, 0, {editorFlags});
      const rawAction03 = runRawController(
        3, argumentIndex, argumentCount, editorFlags);
      const expectedAction03Branch = rawAction03.calls
        ? 'short-list-loop' : rawAction03.branch;
      if (first.branch !== expectedAction03Branch)
        throw new Error('39:51F1 exhaustive controller branch mismatch');
      if (first.branch === 'short-list-loop' && first.iterations !==
          rawAction03.calls)
        throw new Error('39:50A1 exhaustive byte counter mismatch');
      if (first.branch === 'short-list-loop' && first.finalArgument !==
          (argumentCount === 0 ? 0 : argumentCount - 1))
        throw new Error('39:50A1 exhaustive final-index mismatch');
      if (first.branch === 'last-visible-argument' &&
          (first.finalArgument !== argumentCount - 1 ||
           first.firstVisibleSlot !== ((argumentCount - 8) & 0xff) ||
           first.preCallRow !== 0xff))
        throw new Error('39:51F1 exhaustive wide-list arithmetic mismatch');
      if (first.branch === 'reverse-walker') action03ReverseStates++;
      else if (first.branch === 'row-token-tail') action03FlagTailStates++;
      else if (argumentCount === 0) action03ZeroCountStates++;
      else if (first.branch === 'short-list-loop') action03ShortStates++;
      else action03WideStates++;
      firstArgumentControllerStates++;

      const action04 = rom.editorAdvanceAction(
        8, argumentIndex, argumentCount, 4, 0, {editorFlags});
      const lastArgument = (argumentCount - 1) & 0xff;
      const delta = (lastArgument - argumentIndex) & 0xff;
      const rawAction04 = runRawController(
        4, argumentIndex, argumentCount, editorFlags);
      const expectedAction04Branch = rawAction04.calls
        ? 'advance-once' : rawAction04.branch;
      if (action04.branch !== expectedAction04Branch || action04.delta !== delta)
        throw new Error('39:52A5 exhaustive controller branch mismatch');
      if (action04.advanceCalls !== rawAction04.calls)
        throw new Error('39:52A5 exhaustive call-count mismatch');
      if (delta !== 0) {
        const expectedDelegateBranch = argumentCount === 0
          ? 'empty'
          : argumentIndex < lastArgument ? 'in-row' : 'at-or-past-last';
        if (action04.delegate.branch !== expectedDelegateBranch)
          throw new Error('39:52A5 exhaustive delegate mismatch');
      }
      if (delta === 0 && !editorFlags && action04.layout.argumentIndex !== 0)
        throw new Error('39:52A5 flag-clear exit stopped laying out argument zero');
      if (delta !== 0) action04AdvanceOnceStates++;
      else if (editorFlags) action04FlagTailStates++;
      else action04LayoutStates++;
      if (editorFlags === 0 && delta !== 0) {
        if (argumentCount === 0) action04ZeroCountPairs++;
        else if (argumentIndex < lastArgument) action04LowerIndexPairs++;
        else action04HigherIndexPairs++;
      }
      argumentAdvanceControllerStates++;
    }
  }
}
expectEqual('39:51F1/52A5 exhaustive controller state totals',
  [firstArgumentControllerStates,argumentAdvanceControllerStates],
  [0x20000,0x20000]);
expectEqual('39:52A5 exhaustive terminal partition',
  [action04AdvanceOnceStates,action04FlagTailStates,action04LayoutStates],
  [0x1fe00,0x100,0x100]);
expectEqual('39:51F1 exhaustive terminal partition', [
  action03ReverseStates,action03FlagTailStates,action03ZeroCountStates,
  action03ShortStates,action03WideStates,
], [0x1fe00,0x100,1,7,0xf8]);
expectEqual('39:52A5 nonzero-delta count/index partition', [
  action04LowerIndexPairs,action04HigherIndexPairs,action04ZeroCountPairs,
], [32385,32640,255]);

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
expectEqual('39:69C8 stores normalized kind 10',
  rom.selectDescriptor(layout, 0x10).normalizedKind, 0x10);
expectEqual('39:69C8 stores normalized kind 11',
  rom.selectDescriptor(layout, 0x11).normalizedKind, 0x11);
expectEqual('39:69C8 kind 12 selector', rom.selectDescriptor(layout, 0x12),
  {kind:'measuredFraction', routine:'39:6A8A'});
expectEqual('39:69C8 unresolved family boundary', rom.selectDescriptor(layout, 0x13),
  {kind:'unresolvedDescriptorFamily', templateKind:3,
   missing:'ram:025E/0254 flag02 state (BIT 6, then BIT 5)'});
for (const [label, flag02, address] of [
  ['BIT 6 selects the six-column family', 0x40, 0x689c],
  ['BIT 5 selects the three-column family', 0x20, 0x68a5],
  ['cleared family flags select the two-row family', 0x00, 0x6893],
]) {
  const selected = rom.selectDescriptor(layout, 0x13, {flag02});
  expectEqual(`39:69C8 ${label}`, selected.descriptor.addr, address);
  expectEqual(`39:69C8 ${label} normalized kind`, selected.normalizedKind,
    flag02 & 0x40 ? 0x23 : flag02 & 0x20 ? 0x33 : 0x13);
}
expectThrows('39:69C8 rejects an invalid family flag byte', RangeError,
  () => rom.selectDescriptor(layout, 0x13, {flag02:0x100}));
expectEqual('39:6B1C endpoint', rom.fractionEndpoint(2, 0x17),
  {left:0x29, right:0x2d, top:0x17, bottom:0x1d});
expectEqual('39:5949 class-6 low slot', rom.multiArgumentRowStep(6, 2), 2);
expectEqual('39:5949 class-6 high slot', rom.multiArgumentRowStep(6, 3), 1);
expectEqual('39:5949 other class', rom.multiArgumentRowStep(5, 2), 1);
for (let graphX = 0; graphX <= 0xff; graphX++) {
  for (let graphY = 0; graphY <= 0xff; graphY++) {
    expectEqual('04:42B5 exhaustive point-address byte flow',
      rom.settledPage4PointAddress(graphX,graphY),
      runRawPointAddress(graphX,graphY));
  }
}
expectEqual('04:42B5 preserves byte-sized row aliasing',
  rom.settledPage4PointAddress(0xff,0xff),{
    graphX:0xff,graphY:0xff,bitMask:1,byteColumn:0x1f,
    displayRow:0x40,rowTimesFour:0,bufferOffset:0x1f,
    plotBufferAddress:0x9891,backupBufferAddress:0x935f,
    lcdColumnCommand:0x3f,lcdRowCommand:0xc0,routine:'04:42B5–42E3',
  });
expectEqual('04:4155 point-on byte transition',
  rom.settledPage4PointOnTransition(9,2,0x80),{
    x:9,y:2,before:0x80,after:0xc0,changed:true,pointer:[1,2],
    graphX:9,graphY:0x3d,bitMask:0x40,byteColumn:1,displayRow:2,
    rowTimesFour:8,bufferOffset:25,
    plotBufferAddress:0x988b,backupBufferAddress:0x9359,
    lcdColumnCommand:0x21,lcdRowCommand:0x82,
    routine:'34:5E98–5EA6 → 04:4155 → 04:42B5–42E3',
    mode:1,operation:'OR',
  });
let pointOnTransitionStates = 0;
for (let x = 0; x < 0x60; x++) {
  for (let y = 0; y < 0x40; y++) {
    const mask = 0x80 >> (x & 7);
    for (let before = 0; before <= 0xff; before++) {
      const transition = rom.settledPage4PointOnTransition(x,y,before);
      if (transition.after !== (before | mask) ||
          transition.changed !== ((before & mask) === 0) ||
          transition.pointer[0] !== (x >> 3) || transition.pointer[1] !== y)
        throw new Error('04:4155 exhaustive point-on transition mismatch');
      pointOnTransitionStates++;
    }
  }
}
expectEqual('04:4155 exhaustive visible point-on state count',
  pointOnTransitionStates,0x180000);
expectEqual('04:4155 accepts byte coordinates beyond the MathPrint clip',
  rom.settledPage4PointOnTransition(0x60,0,0).pointer,[12,0]);
expectEqual('04:4155 accepts a byte row beyond the MathPrint clip',
  rom.settledPage4PointOnTransition(0,0x40,0).pointer,[0,0x40]);
expectThrows('04:4155 rejects a non-byte x coordinate',RangeError,
  () => rom.settledPage4PointOnTransition(0x100,0,0));
expectThrows('04:4155 rejects a non-byte y coordinate',RangeError,
  () => rom.settledPage4PointOnTransition(0,0x100,0));
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
for (const [endpoint,xClip,cursorX] of [
  [89,0,89], [90,1,89], [94,5,89], [95,6,89], [96,7,89], [97,8,89], [106,17,89],
]) expectEqual(`34:5F5D editor horizontal clip at endpoint ${endpoint}`, {
  xClip:rom.settledEditorViewport(endpoint).xClip,
  cursorX:rom.settledEditorViewport(endpoint).cursorX,
}, {xClip,cursorX});
expectEqual('34:5F5D retains an existing larger horizontal clip',
  rom.settledEditorViewport(90,{previousXClip:4}).xClip, 4);
expectEqual('34:5F5D clears a clip beyond the edited endpoint', (() => {
  const viewport = rom.settledEditorViewport(2,{previousXClip:100});
  return {
    xClip:viewport.xClip, reset:viewport.resetPreviousClip,
    branch:viewport.branch, outcomes:viewport.branchOutcomes,
  };
})(), {
  xClip:0,reset:true,branch:'return-before-right-bound',outcomes:[
    '34:5F64:fallthrough','34:5F75:taken','34:5F81:returned',
  ],
});
expectEqual('34:5F5D wraps endpoint-plus-cursor arithmetic as a word', (() => {
  const viewport = rom.settledEditorViewport(0xffff);
  return {
    coordinate:viewport.comparisonCoordinate,xClip:viewport.xClip,
    branch:viewport.branch,
  };
})(), {coordinate:5,xClip:0,branch:'return-before-right-bound'});
expectEqual('34:5F5D applies the alternate cursor width and caller padding', {
  clearBit:rom.settledEditorViewport(91,{iy44Bit3:false}).xClip,
  extraThree:rom.settledEditorViewport(87,{extraWidth:3}).xClip,
}, {clearBit:1,extraThree:1});
expectEqual('logical and physical editor x origins remain separate', (() => {
  const viewport = rom.settledEditorViewport(106,{
    xOrigin:7,screenXOrigin:11,
  });
  return {
    logicalOrigin:viewport.xOrigin,
    screenOrigin:viewport.screenXOrigin,
    clip:viewport.xClip,
    effectiveX:viewport.effectiveX,
    cursorX:viewport.cursorX,
  };
})(), {
  logicalOrigin:7,screenOrigin:11,clip:17,effectiveX:1,cursorX:107,
});
expectThrows('34:5DCA rejects a right bound outside its low-byte ABI', RangeError,
  () => rom.settledEditorViewport(0xffff,{rightBound:0x100}));
expectThrows('34:5F5D rejects a caller width outside its two call sites', RangeError,
  () => rom.settledEditorViewport(90,{extraWidth:1}));

// Compare every 16-bit endpoint/difference with the pinned instruction span.
// endpoint=clip retains every possible nonzero clip; endpoint=clip+1 covers
// the reset path for every endpoint where that predicate is feasible.
let editorViewportRawStates = 0;
for (let endpoint = 0; endpoint <= 0xffff; endpoint++) {
  const previousClips = [0,endpoint];
  if (endpoint < 0xffff) previousClips.push(endpoint + 1);
  for (const previousXClip of previousClips) {
    for (const iy44Bit3 of [false,true]) {
      for (const extraWidth of [0,3]) {
        expectEqual('34:5F5D exhaustive raw-byte viewport state',
          rom.settledEditorViewport(endpoint,{
            previousXClip,iy44Bit3,extraWidth,
          }),
          runRawEditorViewport(
            endpoint,previousXClip,iy44Bit3,extraWidth));
        editorViewportRawStates++;
      }
    }
  }
}
expectEqual('34:5F5D exhaustive raw-byte viewport state count',
  editorViewportRawStates, 786428);
expectEqual('34:5F8B applies both live-editor vertical passes', (() => {
  const first = rom.settledEditorVerticalViewport(59,{extraHeight:0});
  const second = rom.settledEditorVerticalViewport(59,{
    previousYClip:first.yClip,extraHeight:4,
  });
  const combined = rom.settledEditorViewport2D(20,59);
  return {
    first:first.yClip,second:second.yClip,combined:combined.yClip,
    effectiveY:combined.effectiveY,cursorY:combined.cursorY,
  };
})(), {first:4,second:8,combined:8,effectiveY:-8,cursorY:51});
expectEqual('34:67C8 partitions the vertical glyph window', [
  rom.settledGlyphVerticalViewportDecision(11,1,19).action,
  rom.settledGlyphVerticalViewportDecision(14,1,19).action,
  rom.settledGlyphVerticalViewportDecision(18,1,19).action,
  rom.settledGlyphVerticalViewportDecision(76,0,19).action,
  rom.settledGlyphVerticalViewportDecision(81,0,19).action,
], ['skip-above','skip-above','clip-top','clip-bottom','skip-below']);
expectThrows('34:5F8B rejects a caller height outside its two call sites',
  RangeError,
  () => rom.settledEditorVerticalViewport(59,{extraHeight:1}));

let editorVerticalViewportRawStates = 0;
for (let cursorTop = 0; cursorTop <= 0xffff; cursorTop++) {
  const previousClips = [0,cursorTop];
  if (cursorTop < 0xffff) previousClips.push(cursorTop + 1);
  for (const previousYClip of previousClips) {
    for (const iy44Bit3 of [false,true]) {
      for (const extraHeight of [0,4]) {
        expectEqual('34:5F8B exhaustive raw-byte viewport state',
          rom.settledEditorVerticalViewport(cursorTop,{
            previousYClip,iy44Bit3,extraHeight,
          }),
          runRawEditorVerticalViewport(
            cursorTop,previousYClip,iy44Bit3,extraHeight));
        editorVerticalViewportRawStates++;
      }
    }
  }
}
expectEqual('34:5F8B exhaustive raw-byte viewport state count',
  editorVerticalViewportRawStates, 786428);
expectEqual('depth-four fraction uses the captured vertical viewport', (() => {
  const generated = mp.generatedForExpression(verticalViewportOracle.expression);
  const settled = rom.rasterizeSettledOperations(
    generated.settledOperations,font);
  const crop = cropInk(settled.grid.map(row => row.join('')));
  return {
    nativeTokens:generated.nativeTokens,
    recordHeight:generated.recordHeight,
    recordWidth:generated.recordWidth,
    firstClip:generated.editorViewport.verticalPasses[0].yClip,
    secondClip:generated.editorViewport.yClip,
    settledOperationCount:generated.settledOperations.length,
    settledWriteCount:settled.writes.length,
    settledWriteHash:crypto.createHash('sha256').update(Buffer.from(
      settled.writes.flatMap(write => [...write.pointer,write.value]))).digest('hex'),
    settledLcdHash:crypto.createHash('sha256').update(Buffer.from(
      settled.grid.flat())).digest('hex'),
    chromeOperationCount:generated.editorChrome.operations.length,
    fullOperationCount:generated.operations.length,
    fullWriteCount:generated.events.length,
    fullWriteHash:crypto.createHash('sha256').update(Buffer.from(
      generated.events.flatMap(write => [...write.pointer,write.value]))).digest('hex'),
    fullLcdHash:crypto.createHash('sha256').update(Buffer.from(
      generated.final.flatMap(row => Array.from(row,Number)))).digest('hex'),
    crop:[crop[0].length,crop.length,
      crypto.createHash('sha256').update(Buffer.from(crop.flat())).digest('hex')],
  };
})(), {
  nativeTokens:verticalViewportOracle.native_tokens,
  recordHeight:verticalViewportOracle.translated.word05_height,
  recordWidth:verticalViewportOracle.translated.expression_endpoint,
  firstClip:verticalViewportOracle.translated.first_vertical_clip,
  secondClip:verticalViewportOracle.translated.second_vertical_clip,
  settledOperationCount:verticalViewportOracle.translated.settled_operation_count,
  settledWriteCount:verticalViewportOracle.translated.settled_accepted_write_count,
  settledWriteHash:verticalViewportOracle.translated.settled_accepted_write_sha256,
  settledLcdHash:verticalViewportOracle.translated.settled_lcd_sha256,
  chromeOperationCount:verticalViewportOracle.translated.editor_chrome_operation_count,
  fullOperationCount:verticalViewportOracle.translated.full_operation_count,
  fullWriteCount:verticalViewportOracle.translated.full_accepted_write_count,
  fullWriteHash:verticalViewportOracle.translated.full_accepted_write_sha256,
  fullLcdHash:verticalViewportOracle.translated.full_lcd_sha256,
  crop:[verticalViewportOracle.entry_crop.width,
    verticalViewportOracle.entry_crop.height,
    verticalViewportOracle.entry_crop.sha256],
});
expectEqual('34:6000 emits both vertical cues for the tall fraction', (() => {
  const viewport = rom.settledEditorViewport2D(20,59);
  const cues = rom.settledEditorVerticalCueOperations(viewport,125);
  return {
    show:[cues.showUp,cues.showDown],
    endpoints:[cues.endpoint,cues.visibleEndpoint],
    positions:cues.operations.map(operation => [operation.x,operation.y]),
    rows:cues.operations.map(operation => operation.rows),
    outcomes:cues.branchOutcomes,
  };
})(), {
  show:[true,true], endpoints:[124,116], positions:[[44,0],[44,58]],
  rows:[[0x08,0x1c,0x3e,0x00],[0x00,0x3e,0x1c,0x08]],
  outcomes:['34:6009:fallthrough','34:60B3:taken',
    '34:5E01:taken','34:6011:fallthrough'],
});
expectEqual('34:60A8 includes the exact lower-cue boundary', [
  rom.settledEditorVerticalCueOperations(
    rom.settledEditorViewport2D(20,59),70).showDown,
  rom.settledEditorVerticalCueOperations(
    rom.settledEditorViewport2D(20,59),71).showDown,
  rom.settledEditorVerticalCueOperations({
    ...rom.settledEditorViewport2D(20,59),yClip:8,
  },5).branchOutcomes,
], [false,true,
  ['34:6009:fallthrough','34:60B3:fallthrough','34:6011:returned']]);
expectEqual('35:7116/715B reproduce the natural vertical-cue write stream', (() => {
  const generated = mp.generatedForExpression(verticalViewportOracle.expression);
  const writes = generated.events.slice(
    -verticalViewportOracle.editor_chrome_trace.accepted_write_count);
  return {
    count:writes.length,
    sha256:crypto.createHash('sha256').update(Buffer.from(
      writes.flatMap(write => [...write.pointer,write.value]))).digest('hex'),
  };
})(), {
  count:verticalViewportOracle.editor_chrome_trace.accepted_write_count,
  sha256:verticalViewportOracle.editor_chrome_trace.accepted_write_sha256,
});
expectEqual('33:4F82 exposes every fixed allocation geometry row',
  Array.from({length:12}, (_, index) => {
    const row = rom.settledRecordAllocationGeometry(0x1f + index);
    return [row.workspaceRequest,row.childCount,row.recordBytes,row.tableAddress];
  }), [
    [0x29,1,0x16,0x4f82], [0x42,2,0x18,0x4f85],
    [0x2b,1,0x16,0x4f88], [0x70,4,0x1c,0x4f8b],
    [0x59,3,0x1a,0x4f8e], [0x42,2,0x18,0x4f91],
    [0x2b,1,0x16,0x4f94], [0x2b,1,0x16,0x4f97],
    [0x2b,1,0x16,0x4f9a], [0x42,2,0x18,0x4f9d],
    [0x70,4,0x1c,0x4fa0], [0x2b,1,0x16,0x4fa3],
  ]);
for (let renderType = 0x1f; renderType < 0x2b; renderType++)
  expectEqual('33:4F6D fixed allocation geometry matches pinned table bytes',
    rom.settledRecordAllocationGeometry(renderType),
    runRawRecordAllocationGeometry(renderType));
const matrixAllocationOutcomes = zeroProduct => [
  `33:4F4E:${zeroProduct ? 'fallthrough' : 'taken'}`,
  ...new Array(19).fill('33:4F65:taken'),
  '33:4F65:fallthrough',
];
expectEqual('33:4F42 derives variable matrix allocation geometry',
  [0,4,0xffff].map(matrixElements =>
    rom.settledRecordAllocationGeometry(0x2b,matrixElements)), [
    {renderType:0x2b,matrixElements:0,workspaceRequest:64,
     childCount:2,recordBytes:24,tableAddress:0x4fa6,
     branchOutcomes:matrixAllocationOutcomes(true),routine:'33:4F42–4F6C'},
    {renderType:0x2b,matrixElements:4,workspaceRequest:130,
     childCount:5,recordBytes:30,tableAddress:0x4fa6,
     branchOutcomes:matrixAllocationOutcomes(false),routine:'33:4F42–4F6C'},
    {renderType:0x2b,matrixElements:0xffff,workspaceRequest:20,
     childCount:0,recordBytes:20,tableAddress:0x4fa6,
     branchOutcomes:matrixAllocationOutcomes(false),routine:'33:4F42–4F6C'},
  ]);
for (let matrixElements = 0; matrixElements <= 0xffff; matrixElements++)
  expectEqual('33:4F42 matrix allocation geometry matches pinned instruction bytes',
    rom.settledRecordAllocationGeometry(0x2b,matrixElements),
    runRawRecordAllocationGeometry(0x2b,matrixElements));
expectThrows('33:4F42 requires a matrix count for type 2Bh', RangeError,
  () => rom.settledRecordAllocationGeometry(0x2b));
expectEqual('34:4B7C accepts an exact-fit record request',
  rom.settledRecordAllocationCapacity({
    workspaceTop:1000,recordTail:200,reservedSpan:100,
    requestedBytes:700,iy2dBit0:false,
  }), {
    workspaceTop:1000,recordTail:200,reservedSpan:100,requestedBytes:700,
    iy2dBit0:false,subtractReserved:true,afterReserved:900,
    rangeBorrow:false,availableBeforeRequest:700,
    requestCompared:true,requestBorrow:false,remainingBytes:0,
    carry:false,returnA:2,terminal:'continue-allocation',branchOutcomes:[
      '34:4B8D:fallthrough','34:4B80:fallthrough','34:486F:fallthrough',
    ],routine:'34:4B7C–4B9D; caller 34:4862–4870',
  });
expectEqual('34:4B7C returns carry one byte beyond the available range',
  rom.settledRecordAllocationCapacity({
    workspaceTop:1000,recordTail:200,reservedSpan:100,
    requestedBytes:701,iy2dBit0:false,
  }).requestBorrow, true);
expectEqual('34:4B86 clears an earlier reserve-subtraction borrow',
  rom.settledRecordAllocationCapacity({
    workspaceTop:0,recordTail:0,reservedSpan:1,
    requestedBytes:0xffff,iy2dBit0:false,
  }).terminal, 'continue-allocation');
expectEqual('34:4B86 range borrow bypasses the request subtraction', (() => {
  const result = rom.settledRecordAllocationCapacity({
    workspaceTop:0,recordTail:1,reservedSpan:0,
    requestedBytes:0,iy2dBit0:false,
  });
  return [result.rangeBorrow,result.requestCompared,
    result.remainingBytes,result.terminal];
})(), [true,false,0xffff,'return-allocation-carry']);
expectEqual('34:4862 wires geometry request into capacity gate', (() => {
  const result = rom.settledRecordAllocationCheck(0x22,null,{
    workspaceTop:0x0100,recordTail:0x0080,reservedSpan:0x0010,
    iy2dBit0:false,
  });
  return {
    request:result.geometry.workspaceRequest,
    geometryBytes:result.geometry.recordBytes,
    capacityRequest:result.capacity.requestedBytes,
    carry:result.carry,returnA:result.returnA,
    routine:result.routine,
  };
})(), {
  request:0x70,geometryBytes:0x1c,capacityRequest:0x70,
  carry:false,returnA:2,
  routine:'34:4862 → 33:4F6D → 34:4B7C → 34:486F',
});
expectThrows('34:4862 rejects a request that disagrees with geometry', RangeError,
  () => rom.settledRecordAllocationCheck(0x22,null,{
    workspaceTop:0x100,recordTail:0,reservedSpan:0,requestedBytes:0x29,
    iy2dBit0:true,
  }));
expectEqual('34:4862 defaults a non-matrix geometry count',
  rom.settledRecordAllocationCheck(0x1f,{
    workspaceTop:0x100,recordTail:0,reservedSpan:0,iy2dBit0:true,
  }).geometry.workspaceRequest, 0x29);

// Compare every workspace word at each carry boundary, plus one deterministic
// mixed-word state, with an interpreter that executes the pinned instruction
// bytes through the allocator caller's RET C.
let recordCapacityRawStates = 0;
for (let workspaceTop = 0; workspaceTop <= 0xffff; workspaceTop++) {
  const states = [
    {workspaceTop,recordTail:0,reservedSpan:workspaceTop,
     requestedBytes:0,iy2dBit0:false},
    {workspaceTop,recordTail:0,reservedSpan:workspaceTop,
     requestedBytes:1,iy2dBit0:false},
    {workspaceTop,recordTail:1,reservedSpan:workspaceTop,
     requestedBytes:0,iy2dBit0:false},
    {workspaceTop,recordTail:0,reservedSpan:(workspaceTop + 1) & 0xffff,
     requestedBytes:0xffff,iy2dBit0:false},
    {workspaceTop,recordTail:workspaceTop,reservedSpan:0xffff,
     requestedBytes:0,iy2dBit0:true},
    {workspaceTop,recordTail:workspaceTop,reservedSpan:0xffff,
     requestedBytes:1,iy2dBit0:true},
    {workspaceTop,
     recordTail:(workspaceTop * 17) & 0xffff,
     reservedSpan:0x5a5a,
     requestedBytes:(workspaceTop * 257) & 0xffff,
     iy2dBit0:Boolean(workspaceTop & 1)},
  ];
  if (workspaceTop < 0xffff) states.push({
    workspaceTop,recordTail:workspaceTop + 1,reservedSpan:0xffff,
    requestedBytes:0,iy2dBit0:true,
  });
  for (const state of states) {
    expectEqual('34:4B7C raw-byte allocation-capacity boundary',
      rom.settledRecordAllocationCapacity(state),
      runRawRecordAllocationCapacity(state));
    recordCapacityRawStates++;
  }
}
expectEqual('34:4B7C raw-byte allocation-capacity state count',
  recordCapacityRawStates, 524287);
const editorCueOperations = rom.settledEditorViewportOperations([
  {kind:'point',x:17,y:4,routine:'test'},
  {kind:'line',axis:'horizontal',from:{x:16,y:5},to:{x:20,y:5},routine:'test'},
], rom.settledEditorViewport(106), 23);
expectEqual('34:5DBE/5DC2 applies the editor translation and appends the left cue',
  editorCueOperations, [
    {kind:'point',x:0,y:4,routine:'test'},
    {kind:'line',axis:'horizontal',from:{x:-1,y:5},to:{x:3,y:5},routine:'test'},
    {kind:'bitmap',x:0,y:8,width:4,height:7,
     rows:[0x00,0x02,0x06,0x0e,0x06,0x02,0x00],retainUnchanged:true,
     routine:'34:5FF2 → 34:6031 → 34:61B2; bitmap at 34:60B8'},
  ]);
expectEqual('34:6031 clamps a tall record cue to the viewport height',
  rom.settledEditorViewportOperations(
    [],rom.settledEditorViewport2D(110,59),125), [
    {kind:'bitmap',x:0,y:28,width:4,height:7,
     rows:[0x00,0x02,0x06,0x0e,0x06,0x02,0x00],retainUnchanged:true,
     routine:'34:5FF2 → 34:6031 → 34:61B2; bitmap at 34:60B8'},
  ]);
expectEqual('34:603E uses the viewport height in editor mode 49h',
  rom.settledEditorViewportOperations(
    [],rom.settledEditorViewport(106),23,{editorMode:0x49}), [
    {kind:'bitmap',x:0,y:28,width:4,height:7,
     rows:[0x00,0x02,0x06,0x0e,0x06,0x02,0x00],retainUnchanged:true,
     routine:'34:5FF2 → 34:6031 → 34:61B2; bitmap at 34:60B8'},
  ]);
expectEqual('combined horizontal and vertical viewport matches the natural LCD', (() => {
  const program = rom.constructSettledProgramFromTokens(
    combinedViewportOracle.native_tokens,1,font);
  const generated = mp.generateRecordProgram(program,{editor:true});
  const leftCue = generated.settledOperations.find(operation =>
    operation.routine ===
      '34:5FF2 → 34:6031 → 34:61B2; bitmap at 34:60B8');
  return {
    nodeCount:program.nodes.length,
    recordHeight:generated.recordHeight,
    expressionEndpoint:generated.recordWidth,
    xClip:generated.editorViewport.xClip,
    firstYClip:generated.editorViewport.verticalPasses[0].yClip,
    secondYClip:generated.editorViewport.yClip,
    leftCueY:leftCue.y,
    settledOperationCount:generated.settledOperations.length,
    chromeOperationCount:generated.editorChrome.operations.length,
    fullOperationCount:generated.operations.length,
    fullWriteCount:generated.events.length,
    fullWriteHash:crypto.createHash('sha256').update(Buffer.from(
      generated.events.flatMap(write => [...write.pointer,write.value]))).digest('hex'),
    settledLcdHash:crypto.createHash('sha256').update(Buffer.from(
      generated.settledFinal.flatMap(row => Array.from(row,Number)))).digest('hex'),
    fullLcdHash:crypto.createHash('sha256').update(Buffer.from(
      generated.final.flatMap(row => Array.from(row,Number)))).digest('hex'),
  };
})(), {
  nodeCount:combinedViewportOracle.translated.node_count,
  recordHeight:combinedViewportOracle.translated.record_height,
  expressionEndpoint:combinedViewportOracle.translated.expression_endpoint,
  xClip:combinedViewportOracle.translated.x_clip,
  firstYClip:combinedViewportOracle.translated.first_y_clip,
  secondYClip:combinedViewportOracle.translated.second_y_clip,
  leftCueY:combinedViewportOracle.translated.left_cue_y,
  settledOperationCount:combinedViewportOracle.translated.settled_operation_count,
  chromeOperationCount:
    combinedViewportOracle.translated.editor_chrome_operation_count,
  fullOperationCount:combinedViewportOracle.translated.full_operation_count,
  fullWriteCount:combinedViewportOracle.translated.full_accepted_write_count,
  fullWriteHash:combinedViewportOracle.translated.full_accepted_write_sha256,
  settledLcdHash:combinedViewportOracle.translated.settled_lcd_sha256,
  fullLcdHash:combinedViewportOracle.translated.full_lcd_sha256,
});
expectEqual('34:6C5F skips a glyph whose left edge precedes the editor clip',
  rom.settledEditorViewportOperations([
    {kind:'glyph',code:0x58,x:14,y:3,depth:0,routine:'test'},
    {kind:'glyph',code:0x41,x:17,y:3,depth:0,routine:'test'},
  ], rom.settledEditorViewport(106), 10).slice(0,-1), [
    {kind:'glyph',code:0x41,x:0,y:3,depth:0,routine:'test'},
  ]);
expectEqual('34:6C5F skips a root-hook bitmap whose left edge precedes the editor clip',
  rom.settledEditorViewportOperations([
    {kind:'bitmap',x:6,y:4,width:5,height:1,rows:[0x04],
     retainUnchanged:true,viewportAdvance:5,routine:'34:630C → 34:6C37'},
    {kind:'bitmap',x:7,y:4,width:5,height:1,rows:[0x04],
     retainUnchanged:true,viewportAdvance:5,routine:'34:630C → 34:6C37'},
  ], rom.settledEditorViewport(96), 10).slice(0,-1), [
    {kind:'bitmap',x:0,y:4,width:5,height:1,rows:[0x04],
     retainUnchanged:true,viewportAdvance:5,routine:'34:630C → 34:6C37'},
  ]);
expectEqual('34:6C6B skips only glyphs past the one-past-right endpoint',
  rom.settledEditorViewportOperations([
    {kind:'glyph',code:0x41,x:91,y:3,depth:1,routine:'test'},
    {kind:'glyph',code:0x41,x:92,y:3,depth:1,routine:'test'},
    {kind:'glyph',code:0x41,x:95,y:3,depth:1,routine:'test'},
  ], rom.settledEditorViewport(0), 10, {
    glyphAdvance:() => 4,
  }), [
    {kind:'glyph',code:0x41,x:91,y:3,depth:1,routine:'test'},
    {kind:'glyph',code:0x41,x:92,y:3,depth:1,routine:'test'},
  ]);
expectEqual('34:6C5F/6C7C exposes both glyph clipping comparisons', [
  rom.settledGlyphViewportDecision(0,4,1),
  rom.settledGlyphViewportDecision(92,4,0),
  rom.settledGlyphViewportDecision(95,4,0),
  rom.settledGlyphViewportDecision(0xffff,1,0),
], [
  {action:'skip-left',logicalPen:0,endpoint:null,rightExclusive:null,
   branchOutcomes:['34:6C69:taken']},
  {action:'draw',logicalPen:92,endpoint:96,rightExclusive:96,
   branchOutcomes:['34:6C69:fallthrough','34:6C7F:taken']},
  {action:'skip-right',logicalPen:95,endpoint:99,rightExclusive:96,
   branchOutcomes:['34:6C69:fallthrough','34:6C7F:fallthrough']},
  {action:'draw',logicalPen:0xffff,endpoint:0,rightExclusive:96,
   branchOutcomes:['34:6C69:fallthrough','34:6C7F:taken']},
]);
expectEqual('34:6659 gates embedded records by their logical endpoint', [
  rom.settledEmbeddedViewportDecision(56,63),
  rom.settledEmbeddedViewportDecision(63,63),
], [
  {action:'skip-left',logicalEndpoint:56,translatedEndpoint:0xfff9,
   branchOutcomes:['34:6659:taken']},
  {action:'draw',logicalEndpoint:63,translatedEndpoint:0,
   branchOutcomes:['34:6659:fallthrough']},
]);
expectEqual('34:608F selects and positions the right overflow bitmap',
  rom.settledEditorRightCueOperation(rom.settledEditorViewport(106), 23), {
    kind:'bitmap', x:91, y:8, width:4, height:7,
    rows:[0x00,0x04,0x06,0x07,0x06,0x04,0x00], retainUnchanged:true,
    routine:'34:5FFA → 34:607A → 34:608F; bitmap at 34:60C0',
  });
const retainedCueViewport = rom.settledEditorViewport(20,{previousXClip:10});
expectEqual('34:607A partitions every right-cue terminal predicate', [
  rom.settledEditorRightCueDecision(0,retainedCueViewport),
  rom.settledEditorRightCueDecision(10,retainedCueViewport),
  rom.settledEditorRightCueDecision(11,retainedCueViewport),
  rom.settledEditorRightCueDecision(12,retainedCueViewport),
  rom.settledEditorRightCueDecision(107,retainedCueViewport),
].map(result => ({
  action:result.action,
  endpoint:result.endpoint,
  translated:result.translatedEndpoint,
  comparison:result.comparisonCoordinate,
  carry:result.subtractionCarry,
  outcomes:result.branchOutcomes,
})), [
  {action:'return',endpoint:null,translated:null,comparison:null,carry:null,
   outcomes:['34:607F:returned','34:5FFD:fallthrough']},
  {action:'return',endpoint:9,translated:0xffff,comparison:null,carry:true,
   outcomes:['34:607F:fallthrough','34:6085:taken','34:5FFD:fallthrough']},
  {action:'return',endpoint:10,translated:0,comparison:0,carry:false,
   outcomes:['34:607F:fallthrough','34:6085:fallthrough','34:6087:taken',
     '34:5DE1:fallthrough','34:5FFD:fallthrough']},
  {action:'return',endpoint:11,translated:1,comparison:0,carry:false,
   outcomes:['34:607F:fallthrough','34:6085:fallthrough','34:6087:fallthrough',
     '34:5DE1:fallthrough','34:5FFD:fallthrough']},
  {action:'draw',endpoint:106,translated:96,comparison:95,carry:false,
   outcomes:['34:607F:fallthrough','34:6085:fallthrough','34:6087:fallthrough',
     '34:5DE1:taken','34:5FFD:taken']},
]);
expectEqual('34:608F uses physical origins and clamps tall cue placement', (() => {
  const viewport = rom.settledEditorViewport2D(106,59,{
    xOrigin:7,yOrigin:19,screenXOrigin:11,screenYOrigin:13,
  });
  const cue = rom.settledEditorRightCue(107,viewport,125);
  return {
    action:cue.action,
    x:cue.operation.x,
    y:cue.operation.y,
    leftCue:rom.settledEditorViewportOperations([],viewport,125).at(-1),
  };
})(), {
  action:'draw',x:102,y:41,
  leftCue:{kind:'bitmap',x:11,y:41,width:4,height:7,
    rows:[0x00,0x02,0x06,0x0e,0x06,0x02,0x00],retainUnchanged:true,
    routine:'34:5FF2 → 34:6031 → 34:61B2; bitmap at 34:60B8'},
});
let normalRightCueDraws = 0;
for (let endpoint = 0; endpoint <= 0xffff; endpoint++) {
  const viewport = rom.settledEditorViewport(endpoint);
  const wrapperWidth = (endpoint + viewport.cursorWidth +
    viewport.extraWidth) & 0xffff;
  normalRightCueDraws +=
    Number(rom.settledEditorRightCueDecision(wrapperWidth,viewport).showRight);
}
expectEqual('34:5F5D fresh-clip normal-origin invariant suppresses 34:608F',
  normalRightCueDraws,0);
expectEqual('ram:027B leaves the run indicator idle before counter zero',
  rom.settledRunIndicatorTick(2,0x78), {
    indicCounter:1, indicBusy:0x78, operation:null,
    routine:'ram:027B–0283',
  });
expectEqual('01:6BBA rotates and emits the run indicator at counter zero',
  rom.settledRunIndicatorTick(1,0x78), {
    indicCounter:0x14,
    indicBusy:0x3c,
    operation:{
      kind:'bitmap',x:95,y:0,width:1,height:8,
      rows:[0,0,1,1,1,1,0,0],retainUnchanged:true,asynchronous:true,
      routine:'ram:027B–0283 → 01:6BBA–6BFA',
    },
    routine:'ram:027B–0283 → 01:6BBA–6BFA',
  });
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
   retainUnchanged:true, viewportAdvance:5,
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
expectEqual('34:5E0F asymmetric opening brace order',
  rom.settledBraceOperations('open', 10, 4, 9, 5), [
    {kind:'point',x:14,y:4,routine:'34:5E0F → 34:5E85'},
    {kind:'point',x:13,y:4,routine:'34:5E0F → 34:5E85'},
    {kind:'line',axis:'vertical',from:{x:12,y:5},to:{x:12,y:8},
     routine:'34:5E0F → 34:5D96'},
    {kind:'point',x:11,y:9,routine:'34:5E0F → 34:5E85'},
    {kind:'line',axis:'vertical',from:{x:12,y:10},to:{x:12,y:11},
     routine:'34:5E0F → 34:5D96'},
    {kind:'point',x:13,y:12,routine:'34:5E0F → 34:5E85'},
    {kind:'point',x:14,y:12,routine:'34:5E0F → 34:5E85'},
  ]);
expectEqual('34:5E14 asymmetric closing brace order',
  rom.settledBraceOperations('close', 20, 6, 9, 5), [
    {kind:'point',x:20,y:6,routine:'34:5E14 → 34:5E85'},
    {kind:'point',x:21,y:6,routine:'34:5E14 → 34:5E85'},
    {kind:'line',axis:'vertical',from:{x:22,y:7},to:{x:22,y:10},
     routine:'34:5E14 → 34:5D96'},
    {kind:'point',x:23,y:11,routine:'34:5E14 → 34:5E85'},
    {kind:'line',axis:'vertical',from:{x:22,y:12},to:{x:22,y:13},
     routine:'34:5E14 → 34:5D96'},
    {kind:'point',x:21,y:14,routine:'34:5E14 → 34:5E85'},
    {kind:'point',x:20,y:14,routine:'34:5E14 → 34:5E85'},
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

// The browser decoder reads the settled graph itself. This is independent of
// the native-token parser: child IDs, payload markers, and postfix power
// binding all come from the constructed records.
expectEqual('browser decodes a settled multi-argument graph semantically',
  rom.decodeSettledExpressionGraph(
    mp.constructedProgramForExpression(
      'int(1,2,(1//2)X,X)+sum(N,1,3,N^2)').nodes, 1), {
    kind:'sequence',
    parts:[
      {
        kind:'integral', lower:[0x31], upper:[0x32],
        body:{kind:'sequence',parts:[
          {kind:'fraction',numerator:[0x31],denominator:[0x32]}, [0x58],
        ]}, variable:[0x58],
      },
      [0x70],
      {
        kind:'summation', variable:[0x4e], lower:[0x31], upper:[0x33],
        body:{kind:'power',base:[0x4e],exponent:[0x32]},
      },
    ],
  });
expectEqual('browser decodes matrix children and nested powers',
  rom.decodeSettledExpressionGraph(
    mp.constructedProgramForExpression(
      'matrix(2,2,sqrt(2),X^2,3,4)').nodes, 1), {
    kind:'matrix', rows:2, columns:2,
    elements:[
      {kind:'radical',radicand:[0x32]},
      {kind:'power',base:[0x58],exponent:[0x32]},
      [0x33], [0x34],
    ],
  });
const groupedNestedPowerSpec = {
  kind:'power',
  base:{kind:'group',expression:{
    kind:'power',base:[0x58],
    exponent:{kind:'group',expression:[0x58,0x71,0x32]},
  }},
  exponent:{kind:'power',
    base:{kind:'group',expression:[0x4e,0x83,0x58]},
    exponent:{kind:'group',expression:[0x4e,0x71,0x33]},
  },
};
const groupedNestedPowerProgram = rom.constructSettledExpressionProgram(
  groupedNestedPowerSpec, 7, font);
expectEqual('browser decodes grouped postfix power bases with token boundaries',
  rom.decodeSettledExpressionGraph(groupedNestedPowerProgram.nodes, 7),
  groupedNestedPowerSpec);
expectEqual('postfix power binds one atom after implicit and explicit products',
  rom.decodeSettledExpressionGraph(
    mp.constructedProgramForExpression('2X^2+A*B^3').nodes, 1), {
    kind:'sequence',parts:[
      [0x32], {kind:'power',base:[0x58],exponent:[0x32]},
      [0x70,0x41,0x82], {kind:'power',base:[0x42],exponent:[0x33]},
    ],
  });
expectEqual('function with a structural body remains one postfix-power base',
  rom.decodeSettledExpressionGraph(
    mp.constructedProgramForExpression('sin(sqrt(X))^2').nodes, 1), {
    kind:'power',
    base:{kind:'sequence',parts:[
      [0xc2], {kind:'radical',radicand:[0x58]}, [0x11],
    ]},
    exponent:[0x32],
  });
expectEqual('live mixed logBASE graph keeps the additive power boundary',
  rom.decodeSettledExpressionGraph(
    mp.constructedProgramForExpression(
      'logbase((X/X)+X^1,sqrt(A//X))').nodes, 1), {
    kind:'logBase',
    base:{kind:'sequence',parts:[
      {kind:'group',expression:[0x58,0x83,0x58]}, [0x70],
      {kind:'power',base:[0x58],exponent:[0x31]},
    ]},
    argument:{kind:'radical',radicand:{
      kind:'fraction',numerator:[0x41],denominator:[0x58],
    }},
  });
expectEqual('browser decodes a transparent transient root',
  rom.decodeSettledExpressionGraph([
    {id:1,type:0x1f,childIds:[2]},
    {id:2,type:0,payload:[0x58]},
  ], 1), [0x58]);
expectEqual('browser decodes a live matrix container through a transient root',
  rom.decodeSettledExpressionGraph([
    {id:6,type:0x1f,childIds:[7]},
    {id:7,type:0,payload:[
      0x06,0x06,
      0xef,0x27,8,0,0xef,0x2d,0x2b,
      0x58,0xef,0x2a,10,0,0xef,0x2d,
      0x07,0x06,0x33,0x2b,0x34,0x07,0x07,
    ]},
    {id:8,type:0x27,childIds:[9]},
    {id:9,type:0,payload:[0x32]},
    {id:10,type:0x2a,childIds:[11]},
    {id:11,type:0,payload:[0x32]},
  ], 6), {
    kind:'matrix',rows:2,columns:2,elements:[
      {kind:'radical',radicand:[0x32]},
      {kind:'power',base:[0x58],exponent:[0x32]},
      [0x33],[0x34],
    ],
  });
expectThrows('live matrix decoder rejects unequal row widths', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[
      0x06,0x06,0x31,0x2b,0x32,0x07,0x06,0x33,0x07,0x07,
    ]},
  ], 1));
expectThrows('live matrix decoder rejects a cycle through an element', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[
      0x06,0x06,0xef,0x27,2,0,0xef,0x2d,0x07,0x07,
    ]},
    {id:2,type:0x27,childIds:[1]},
  ], 1));
expectEqual('browser preserves extended tokens in a settled leaf',
  rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[0x58,0xef,0x2a,2,0,0xef,0x2d,0xef,0x1e]},
    {id:2,type:0x2a,childIds:[3]},
    {id:3,type:0,payload:[0x32]},
  ], 1), {
    kind:'sequence',
    parts:[{kind:'power',base:[0x58],exponent:[0x32]},
      {kind:'extendedToken',tokens:[0xef,0x1e]}],
  });
expectEqual('settled grouping respects a two-byte native token boundary',
  rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[0x5e,0x10]},
  ], 1), [0x5e,0x10]);
expectEqual('generated LCD records expose their graph-derived AST',
  mp.generatedForExpression('sum(N,1,3,N^2)').settledAst, {
    kind:'summation', variable:[0x4e], lower:[0x31], upper:[0x33],
    body:{kind:'power',base:[0x4e],exponent:[0x32]},
  });
expectEqual('semantic decoder retains non-structural EF function tokens',
  mp.generatedForNativeTokens([0xef,0x35,0x31,0x2b,0x35,0x11]).settledAst,
  [0xef,0x35,0x31,0x2b,0x35,0x11]);
expectThrows('settled semantic decoder rejects duplicate IDs', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[0x58]}, {id:1,type:0,payload:[0x59]},
  ], 1));
expectThrows('settled semantic decoder rejects a missing child', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[0xef,0x27,2,0]},
  ], 1));
expectThrows('settled semantic decoder rejects an unsupported structural type', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0x2c,childIds:[]},
  ], 1));
expectThrows('settled semantic decoder rejects a power without a base', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0,payload:[0xef,0x2a,2,0]},
    {id:2,type:0x2a,childIds:[3]}, {id:3,type:0,payload:[0x32]},
  ], 1));
expectThrows('settled semantic decoder rejects structural cycles', RangeError,
  () => rom.decodeSettledExpressionGraph([
    {id:1,type:0x20,childIds:[2,3]},
    {id:2,type:0,payload:[0xef,0x20,1,0]},
    {id:3,type:0,payload:[0x32]},
  ], 1));

expectEqual('editor payload units keep packed tokens and record markers whole', {
  empty:rom.editorPayloadCursorBoundaries([0xef,0x1e]),
  marker:rom.editorPayloadCursorBoundaries([0xef,0x22,8,0,0xef,0x2d]),
  mixed:rom.editorPayloadCursorBoundaries([0x31,0x5d,0x00,0x32]),
}, {empty:[0,2],marker:[0,6],mixed:[0,1,3,4]});
expectThrows('editor payload unit decoder rejects a truncated packed token', RangeError,
  () => rom.editorPayloadCursorBoundaries([0xef]));
expectThrows('editor graph decoder rejects a cursor inside a packed token', RangeError,
  () => rom.decodeEditorExpressionGraph([
    {id:1,type:0,payload:[0xef,0x1e]},
  ],1,1,1));

expectEqual('live editor gap oracle schema', editorGapOracles.schema, 2);
const editorCursorAtPath = (value, path) => path.reduce(
  (current, component) => current[component], value);
const editorGlyphAdvance = (depth, code) => {
  if (depth === 0) return 6;
  const glyph = font.small.glyphs[code];
  if (!glyph) throw new Error(`small glyph 0x${code.toString(16)} is absent`);
  return glyph.w;
};
const canonicalEditorRecord = node => ({
  record_id:node.record_id === undefined ? node.id : node.record_id,
  render_type:node.render_type === undefined ? node.type : node.render_type,
  word03:node.word03, word05:node.word05, word07:node.word07,
  word09:node.word09, word0B:node.word0B, word0D:node.word0D,
  word0F:node.word0F, word11:node.word11, byte13:node.byte13,
  child_ids:node.child_ids.slice(), payload:node.payload.slice(),
});
const editorRecordsById = nodes => nodes.map(canonicalEditorRecord)
  .sort((left,right) => left.record_id - right.record_id);
const editorStateProjection = state => ({
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
  nodes:editorRecordsById(state.nodes),
});
for (const oracle of editorGapOracles.cases) {
  const macro = fs.readFileSync(path.join(root, oracle.macro));
  expectEqual(`${oracle.name} capture macro hash`,
    crypto.createHash('sha256').update(macro).digest('hex'),
    oracle.macro_sha256);
  const ram = new Uint8Array(0x8000);
  const sparseDigest = crypto.createHash('sha256');
  for (const segment of oracle.segments) {
    const bytes = Buffer.from(segment.bytes,'hex');
    ram.set(bytes,segment.address - 0x8000);
    const address = Buffer.alloc(2);
    address.writeUInt16LE(segment.address);
    sparseDigest.update(address);
    sparseDigest.update(bytes);
  }
  expectEqual(`${oracle.name} sparse RAM state hash`,
    sparseDigest.digest('hex'),oracle.sparse_state_sha256);
  const decoded = rom.decodeMathPrintEditorRam(ram);
  expectEqual(`${oracle.name} live RAM graph and cursor`, {
    entry_id:decoded.entryId,
    active_record_id:decoded.editor.cursor.recordId,
    cursor_byte_offset:decoded.editor.cursor.byteOffset,
    cursor_path:decoded.editor.cursor.path,
    left:decoded.editor.cursor.left,
    right:decoded.editor.cursor.right,
    expression:decoded.expression,
    node_count:decoded.nodes.length,
  }, oracle.expected);
  expectEqual(`${oracle.name} cursor marker occupies the decoded path`,
    editorCursorAtPath(
      decoded.editor.expression,decoded.editor.cursor.path), {
      kind:'editorCursor',
      record_id:oracle.expected.active_record_id,
      byte_offset:oracle.expected.cursor_byte_offset,
      record_word0F:decoded.nodes.find(
        node => node.id === oracle.expected.active_record_id).word0F,
      record_word11:decoded.nodes.find(
        node => node.id === oracle.expected.active_record_id).word11,
      editor_leaf_record_id:oracle.expected.active_record_id,
    });
  const reconstructed = rom.constructEditorExpressionProgram(
    decoded.editor.expression,7,font);
  expectEqual(`${oracle.name} live editor constructor identity`, {
    entry_id:reconstructed.entry_id,
    wrapper_id:reconstructed.wrapper_id,
    active_record_id:reconstructed.editor.active_record_id,
    cursor_byte_offset:reconstructed.editor.cursor_byte_offset,
  }, {
    entry_id:oracle.expected.entry_id,
    wrapper_id:6,
    active_record_id:oracle.expected.active_record_id,
    cursor_byte_offset:oracle.expected.cursor_byte_offset,
  });
  expectEqual(`${oracle.name} reconstructed live record fields`,
    editorRecordsById(reconstructed.nodes),editorRecordsById(decoded.nodes));
  expectEqual(`${oracle.name} reconstructed graph retains cursor AST`,
    rom.decodeEditorExpressionGraph(
      reconstructed.nodes,reconstructed.entry_id,
      reconstructed.editor.active_record_id,
      reconstructed.editor.cursor_byte_offset).expression,
    decoded.editor.expression);
  const reconstructedOperations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const reconstructedLcd = rom.rasterizeSettledOperations(
    reconstructedOperations,font).grid;
  expectEqual(`${oracle.name} reconstructed cursor-off LCD bitmap`,
    crypto.createHash('sha256').update(
      packedLcdBytes(reconstructedLcd)).digest('hex'),
    oracle.lcd_bitmap_sha256);
}
expectEqual('live editor mutation oracle schema', editorMutationOracles.schema, 2);
const sparseEditorRam = (state, label) => {
  const ram = new Uint8Array(0x8000);
  const digest = crypto.createHash('sha256');
  for (const segment of state.segments) {
    const bytes = Buffer.from(segment.bytes,'hex');
    ram.set(bytes,segment.address - 0x8000);
    const address = Buffer.alloc(2);
    address.writeUInt16LE(segment.address);
    digest.update(address);
    digest.update(bytes);
  }
  expectEqual(`${label} sparse RAM state hash`,
    digest.digest('hex'),state.sparse_state_sha256);
  return ram;
};
for (const oracle of editorMutationOracles.transitions) {
  const macro = fs.readFileSync(path.join(root,oracle.macro));
  expectEqual(`${oracle.name} capture macro hash`,
    crypto.createHash('sha256').update(macro).digest('hex'),
    oracle.macro_sha256);
  const before = rom.decodeMathPrintEditorRam(
    sparseEditorRam(oracle.pre,`${oracle.name} pre-insertion`));
  const after = rom.decodeMathPrintEditorRam(
    sparseEditorRam(oracle.post,`${oracle.name} post-insertion`));
  const inserted = rom.editorInsertPackedToken(
    before,oracle.inserted_token);
  expectEqual(`${oracle.name} translated insertion path`,inserted.mutation,{
    inserted:oracle.inserted_token,
    record_id:before.editor.cursor.recordId,
    before_byte_offset:before.editor.cursor.byteOffset,
    after_byte_offset:after.editor.cursor.byteOffset,
    replaced_empty_slot:oracle.replaced_empty_slot,
    routine:oracle.trace.routine,
  });
  expectEqual(`${oracle.name} decoded editor transition`,
    inserted.expression,after.editor.expression);
  const reconstructed = rom.constructEditorExpressionProgram(
    inserted.expression,7,font);
  expectEqual(`${oracle.name} reconstructed post-insertion records`,
    editorRecordsById(reconstructed.nodes),editorRecordsById(after.nodes));
  const operations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  expectEqual(`${oracle.name} reconstructed post-insertion LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
    oracle.post.lcd_bitmap_sha256);
}
for (const sequence of editorMutationOracles.sequences) {
  const macro = fs.readFileSync(path.join(root,sequence.macro));
  expectEqual(`${sequence.name} capture macro hash`,
    crypto.createHash('sha256').update(macro).digest('hex'),
    sequence.macro_sha256);
  expectEqual(`${sequence.name} state/step count`,
    sequence.states.length,sequence.steps.length + 1);
  const states = sequence.states.map((state,index) =>
    rom.decodeMathPrintEditorRam(sparseEditorRam(
      state,`${sequence.name} state ${index}`)));
  for (let index = 0; index < states.length; index++) {
    const reconstructed = rom.constructEditorExpressionProgram(
      states[index].editor.expression,7,font);
    expectEqual(`${sequence.name} state ${index} reconstructed records`,
      editorRecordsById(reconstructed.nodes),editorRecordsById(states[index].nodes));
    const operations = rom.executeSettledRecordProgram(
      reconstructed.nodes,reconstructed.wrapper_id,
      {glyphAdvance:editorGlyphAdvance});
    const lcd = rom.rasterizeSettledOperations(operations,font).grid;
    expectEqual(`${sequence.name} state ${index} reconstructed LCD bitmap`,
      crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
      sequence.states[index].lcd_bitmap_sha256);
  }
  for (let index = 0; index < sequence.steps.length; index++) {
    const step = sequence.steps[index];
    const inserted = rom.editorInsertPackedToken(
      states[index],step.inserted_token);
    expectEqual(`${sequence.name} ${step.name} translated insertion path`,
      inserted.mutation,{
        inserted:step.inserted_token,
        record_id:states[index].editor.cursor.recordId,
        before_byte_offset:states[index].editor.cursor.byteOffset,
        after_byte_offset:states[index + 1].editor.cursor.byteOffset,
        replaced_empty_slot:step.replaced_empty_slot,
        routine:sequence.routine,
      });
    expectEqual(`${sequence.name} ${step.name} decoded editor transition`,
      inserted.expression,states[index + 1].editor.expression);
  }
}
expectEqual('live editor structural-mutation oracle schema',
  editorStructuralMutationOracles.schema,1);
for (const oracle of editorStructuralMutationOracles.transitions) {
  expectEqual(`${oracle.name} capture macro hash`,
    crypto.createHash('sha256').update(fs.readFileSync(path.join(
      root,oracle.macro))).digest('hex'),oracle.macro_sha256);
  const before = rom.decodeMathPrintEditorRam(
    sparseEditorRam(oracle.pre,`${oracle.name} pre-insertion`));
  const after = rom.decodeMathPrintEditorRam(
    sparseEditorRam(oracle.post,`${oracle.name} post-insertion`));
  if (oracle.name === 'blank_root_insert_fraction')
    expectEqual(`${oracle.name} decodes the blank cursor leaf`,{
      settled_expression:before.expression,
      editor_expression:before.editor.expression,
      controller:before.controller,
    },{
      settled_expression:null,
      editor_expression:{
        kind:'editorCursor',record_id:7,byte_offset:0,
        record_word0F:0,record_word11:0,editor_leaf_record_id:7,
      },
      controller:{recordId:6,renderType:0x1f,
        structuralDepth:0,activeLeafId:7},
    });
  const reconstructedBefore = rom.constructEditorExpressionProgram(
    before.editor.expression,7,font);
  expectEqual(`${oracle.name} reconstructs the blank cursor records`,
    editorRecordsById(reconstructedBefore.nodes),
    editorRecordsById(before.nodes));
  const beforeOperations = rom.executeSettledRecordProgram(
    reconstructedBefore.nodes,reconstructedBefore.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const beforeLcd = rom.rasterizeSettledOperations(
    beforeOperations,font).grid;
  expectEqual(`${oracle.name} reconstructs the blank cursor-off LCD`,
    crypto.createHash('sha256').update(
      packedLcdBytes(beforeLcd)).digest('hex'),
    oracle.pre.lcd_bitmap_sha256);

  const inserted = rom.editorInsertStructuralTemplate(
    before,oracle.source_token,font);
  expectEqual(`${oracle.name} translated structural insertion`,
    inserted.mutation,oracle.mutation);
  expectEqual(`${oracle.name} decoded structural transition`,
    inserted.expression,after.editor.expression);
  expectEqual(`${oracle.name} composable decoded arena state`,
    editorStateProjection(inserted.state),editorStateProjection(after));
  expectEqual(`${oracle.name} decoded post-key controller`,
    after.controller,{
      recordId:oracle.mutation.structural_record_id,
      renderType:oracle.mutation.render_type,
      structuralDepth:oracle.mutation.after_structural_depth,
      activeLeafId:oracle.mutation.after_record_id,
    });
  const reconstructed = rom.constructEditorExpressionProgram(
    inserted.expression,7,font);
  expectEqual(`${oracle.name} reconstructed structural records`,
    editorRecordsById(reconstructed.nodes),editorRecordsById(after.nodes));
  const operations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  expectEqual(`${oracle.name} reconstructed post-insertion LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
    oracle.post.lcd_bitmap_sha256);

  const blocked = rom.editorInsertStructuralTemplate({
    ...before,
    controller:{...before.controller,structuralDepth:4},
  },oracle.source_token);
  expectEqual(`${oracle.name} retains the expression at the depth limit`,
    blocked,{
      expression:before.editor.expression,
      mutation:{
        status:'depth-limit',source_token:oracle.source_token,
        render_type:oracle.mutation.render_type,before_structural_depth:4,
        after_structural_depth:5,return_a:3,flags45_bit6:true,
        error_address:0x9d20,error_value:5,
        routine:'34:473A → 35:7B37 → 34:54D2',
      },
    });
  if (before.expression === null) {
    const inactiveEmpty = sparseEditorRam(
      oracle.pre,`${oracle.name} inactive-empty rejection`);
    inactiveEmpty[0x89f1 - 0x8000] = 0;
    expectThrows(`${oracle.name} rejects an inactive empty leaf`,RangeError,
      () => rom.decodeMathPrintEditorRam(inactiveEmpty));
  }
}
expectEqual('live editor template-boundary oracle schema',
  editorTemplateBoundaryOracles.schema,1);
expectEqual('live editor template-boundary capture macro hash',
  crypto.createHash('sha256').update(fs.readFileSync(path.join(
    root,editorTemplateBoundaryOracles.capture.macro))).digest('hex'),
  editorTemplateBoundaryOracles.capture.macro_sha256);
for (const oracle of editorTemplateBoundaryOracles.transitions) {
  const before = rom.decodeMathPrintEditorRam(sparseEditorRam(
    oracle.pre,`${oracle.name} pre-insertion`));
  const after = rom.decodeMathPrintEditorRam(sparseEditorRam(
    oracle.post,`${oracle.name} post-insertion`));
  expectEqual(`${oracle.name} oracle LCD identity`,
    oracle.final_lcd_sha256,oracle.post.lcd_bitmap_sha256);
  const inserted = rom.editorInsertStructuralTemplate(
    before,oracle.source_token,font);
  expectEqual(`${oracle.name} translated structural insertion`,
    inserted.mutation,oracle.mutation);
  expectEqual(`${oracle.name} preserves the right structural marker`,
    inserted.mutation.replaced_right_token,[]);
  expectEqual(`${oracle.name} composable decoded arena state`,
    editorStateProjection(inserted.state),editorStateProjection(after));
  const wrapper = inserted.state.nodes.find(node =>
    (node.render_type === undefined ? node.type : node.render_type) === 0x1f);
  if (!wrapper) throw new Error(`${oracle.name} wrapper record is absent`);
  const operations = rom.executeSettledRecordProgram(
    inserted.state.nodes,
    wrapper.record_id === undefined ? wrapper.id : wrapper.record_id,
    {glyphAdvance:editorGlyphAdvance});
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  expectEqual(`${oracle.name} translated post-insertion LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
    oracle.post.lcd_bitmap_sha256);
}
const structuralAllocationBase = rom.decodeMathPrintEditorRam(sparseEditorRam(
  editorStructuralMutationOracles.transitions[0].pre,
  'structural allocation boundary source'));
const radicalAtLastTwoIds = rom.editorInsertStructuralTemplate({
  ...structuralAllocationBase,
  nodes:[...structuralAllocationBase.nodes,{id:0xfffd}],
},[0xbc]);
expectEqual('radical insertion can allocate the last two record IDs',{
  structural_record_id:radicalAtLastTwoIds.mutation.structural_record_id,
  child_record_ids:radicalAtLastTwoIds.mutation.child_record_ids,
}, {
  structural_record_id:0xfffe,child_record_ids:[0xffff],
});
expectThrows('fraction insertion still requires three record IDs',RangeError,
  () => rom.editorInsertStructuralTemplate({
    ...structuralAllocationBase,
    nodes:[...structuralAllocationBase.nodes,{id:0xfffd}],
  },[0xef,0x2e]));
expectThrows('radical insertion rejects a one-ID tail',RangeError,
  () => rom.editorInsertStructuralTemplate({
    ...structuralAllocationBase,
    nodes:[...structuralAllocationBase.nodes,{id:0xfffe}],
  },[0xbc]));
expectThrows('structural insertion keeps unsupported source types explicit',
  RangeError,() => rom.editorInsertStructuralTemplate(
    rom.decodeMathPrintEditorRam(sparseEditorRam(
      editorStructuralMutationOracles.transitions[0].pre,
      'unsupported structural insertion source')),[0xef,0x36]));
expectEqual('live editor navigation oracle schema',
  editorNavigationOracles.schema,1);
expectEqual('live editor navigation capture macro hash',
  crypto.createHash('sha256').update(fs.readFileSync(path.join(
    root,editorNavigationOracles.macro))).digest('hex'),
  editorNavigationOracles.macro_sha256);
const editorNavigationStates = {};
for (const [name,state] of Object.entries(editorNavigationOracles.states)) {
  const decoded = rom.decodeMathPrintEditorRam(sparseEditorRam(
    state,`editor navigation ${name}`));
  const reconstructed = rom.constructEditorExpressionProgram(
    decoded.editor.expression,7,font);
  expectEqual(`editor navigation ${name} reconstructed records`,
    editorRecordsById(reconstructed.nodes),editorRecordsById(decoded.nodes));
  const operations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  expectEqual(`editor navigation ${name} reconstructed LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
    state.lcd_bitmap_sha256);
  editorNavigationStates[name] = decoded;
}
for (const transition of editorNavigationOracles.transitions) {
  const before = editorNavigationStates[transition.from];
  const after = editorNavigationStates[transition.to];
  const moved = rom.editorMovePackedTokenCursor(
    before.editor.expression,transition.direction);
  expectEqual(`editor navigation ${transition.direction} mutation`,
    moved.mutation,{
      direction:transition.direction,moved:[0x32],record_id:7,
      before_byte_offset:before.editor.cursor.byteOffset,
      after_byte_offset:after.editor.cursor.byteOffset,
      routine:transition.routine,
    });
  expectEqual(`editor navigation ${transition.direction} decoded transition`,
    moved.expression,after.editor.expression);
  const reconstructed = rom.constructEditorExpressionProgram(
    moved.expression,7,font);
  expectEqual(`editor navigation ${transition.direction} post-state records`,
    editorRecordsById(reconstructed.nodes),editorRecordsById(after.nodes));
}
const packedCursorEnd = {
  kind:'sequence',parts:[
    [0x31,0x5d,0x00],
    {kind:'editorCursor',record_id:7,byte_offset:3,
      record_word0F:0,record_word11:0},
  ],
};
const packedCursorLeft = rom.editorMovePackedTokenCursor(
  packedCursorEnd,'left');
expectEqual('editor navigation moves a two-byte native token as one unit',
  packedCursorLeft,{
    expression:{kind:'sequence',parts:[
      [0x31],
      {kind:'editorCursor',record_id:7,byte_offset:1,
        record_word0F:0,record_word11:0},
      [0x5d,0x00],
    ]},
    mutation:{direction:'left',moved:[0x5d,0x00],record_id:7,
      before_byte_offset:3,after_byte_offset:1,
      routine:'34:42B4 → 00:3B49 → 06:4294–42C7'},
  });
expectEqual('editor navigation two-byte round trip',
  rom.editorMovePackedTokenCursor(
    packedCursorLeft.expression,'right').expression,packedCursorEnd);
expectThrows('editor navigation rejects movement beyond a leaf endpoint',
  RangeError,() => rom.editorMovePackedTokenCursor(
    editorNavigationStates.end.editor.expression,'right'));
expectThrows('editor navigation rejects a structural boundary',RangeError,
  () => rom.editorMovePackedTokenCursor({kind:'sequence',parts:[
    {kind:'fraction',numerator:[0x31],denominator:[0x32]},
    {kind:'editorCursor',record_id:7,byte_offset:6,
      record_word0F:0,record_word11:0},
  ]},'left'));
expectEqual('live editor structural-navigation oracle schema',
  editorStructuralNavigationOracles.schema,4);
const structuralNavigationProjection = state => ({
  controller:state.controller,
  cursor:{
    recordId:state.editor.cursor.recordId,
    byteOffset:state.editor.cursor.byteOffset,
    left:state.editor.cursor.left,
    right:state.editor.cursor.right,
  },
  expression:state.expression,
  editorExpression:state.editor.expression,
  nodes:state.nodes.map(node => ({
    record_id:node.record_id === undefined ? node.id : node.record_id,
    render_type:node.render_type === undefined ? node.type : node.render_type,
    word05:node.word05,word0F:node.word0F,word11:node.word11,
    child_ids:node.child_ids.slice(),payload:node.payload.slice(),
  })),
});
const exactStructuralNavigationProjection = state => ({
  ...structuralNavigationProjection(state),
  nodes:state.nodes.map(node => ({
    record_id:node.record_id === undefined ? node.id : node.record_id,
    render_type:node.render_type === undefined ? node.type : node.render_type,
    word03:node.word03,word05:node.word05,word07:node.word07,
    word09:node.word09,word0B:node.word0B,word0D:node.word0D,
    word0F:node.word0F,word11:node.word11,byte13:node.byte13,
    child_ids:node.child_ids.slice(),payload:node.payload.slice(),
  })).sort((left,right) => left.record_id - right.record_id),
});
const structuralNavigationStates = {};
for (const [captureName,capture] of Object.entries(
  editorStructuralNavigationOracles.captures)) {
  expectEqual(`${captureName} structural-navigation capture macro hash`,
    crypto.createHash('sha256').update(fs.readFileSync(path.join(
      root,capture.macro))).digest('hex'),capture.macro_sha256);
  structuralNavigationStates[captureName] = capture.states.map(state => {
    const decoded = rom.decodeMathPrintEditorRam(sparseEditorRam(
      state,`${captureName} structural-navigation ${state.name}`));
    const reconstructed = rom.constructEditorExpressionProgram(
      decoded.editor.expression,7,font);
    const operations = rom.executeSettledRecordProgram(
      reconstructed.nodes,reconstructed.wrapper_id,
      {glyphAdvance:editorGlyphAdvance});
    const lcd = rom.rasterizeSettledOperations(operations,font).grid;
    expectEqual(
      `${captureName} structural-navigation ${state.name} LCD bitmap`,
      crypto.createHash('sha256').update(
        packedLcdBytes(lcd)).digest('hex'),state.lcd_bitmap_sha256);
    return decoded;
  });
}
for (const transition of editorStructuralNavigationOracles.transitions) {
  const states = structuralNavigationStates[transition.capture];
  const before = states[transition.from_index];
  const after = states[transition.to_index];
  const moved = rom.editorMoveCursor(before,transition.direction);
  expectEqual(
    `${transition.capture} structural-navigation ${transition.from_index} status`,
    {status:moved.mutation.status,direction:moved.mutation.direction,
      routine:moved.mutation.routine},
    {status:transition.status,direction:transition.direction,
      routine:transition.routine});
  expectEqual(
    `${transition.capture} structural-navigation ${transition.from_index} state`,
    structuralNavigationProjection(moved.state),
    structuralNavigationProjection(after));
}
for (const [captureName,capture] of Object.entries(
  editorStructuralNavigationOracles.captures)) {
  const transitions = editorStructuralNavigationOracles.transitions.filter(
    transition => transition.capture === captureName);
  let state = structuralNavigationStates[captureName][0];
  for (const transition of transitions) {
    const moved = rom.editorMoveCursor(state,transition.direction);
    const expected = structuralNavigationStates[captureName][
      transition.to_index];
    expectEqual(
      `${captureName} composable structural-navigation ` +
      `${transition.from_index} state`,
      structuralNavigationProjection(moved.state),
      structuralNavigationProjection(expected));
    state = moved.state;
  }
}
expectEqual('live editor extra structural-navigation oracle schema',
  editorExtraStructuralNavigationOracles.schema,5);
const extraStructuralNavigationStates = {};
for (const [captureName,capture] of Object.entries(
  editorExtraStructuralNavigationOracles.captures)) {
  expectEqual(`${captureName} extra structural-navigation capture macro hash`,
    crypto.createHash('sha256').update(fs.readFileSync(path.join(
      root,capture.macro))).digest('hex'),capture.macro_sha256);
  extraStructuralNavigationStates[captureName] = capture.states.map(state => {
    const decoded = rom.decodeMathPrintEditorRam(sparseEditorRam(
      state,`${captureName} extra structural-navigation ${state.name}`));
    const reconstructed = rom.constructEditorExpressionProgram(
      decoded.editor.expression,decoded.entryId,font);
    const operations = rom.executeSettledRecordProgram(
      reconstructed.nodes,reconstructed.wrapper_id,
      {glyphAdvance:editorGlyphAdvance});
    const lcd = rom.rasterizeSettledOperations(operations,font).grid;
    expectEqual(
      `${captureName} extra structural-navigation ${state.name} LCD bitmap`,
      crypto.createHash('sha256').update(
        packedLcdBytes(lcd)).digest('hex'),state.lcd_bitmap_sha256);
    expectEqual(
      `${captureName} extra structural-navigation ${state.name} ` +
        'screenshot ink outside cursor cells',
      state.lcd_masked_bitmap_sha256,
      state.screenshot_lcd_masked_bitmap_sha256);
    expectEqual(
      `${captureName} extra structural-navigation ${state.name} cursor masks`,
      state.cursor_masks.every(mask =>
        Number.isInteger(mask.x) && Number.isInteger(mask.y) &&
        Number.isInteger(mask.width) && 0 < mask.width &&
        Number.isInteger(mask.height) && 0 < mask.height),true);
    return decoded;
  });
}
for (const transition of editorExtraStructuralNavigationOracles.transitions) {
  const states = extraStructuralNavigationStates[transition.capture];
  const moved = rom.editorMoveCursor(
    states[transition.from_index],transition.direction,font);
  expectEqual(
    `${transition.capture} extra structural-navigation ` +
      `${transition.from_index} status`,
    {status:moved.mutation.status,direction:moved.mutation.direction,
      routine:moved.mutation.routine},
    {status:transition.status,direction:transition.direction,
      routine:transition.routine});
  expectEqual(
    `${transition.capture} extra structural-navigation ` +
      `${transition.from_index} exact state`,
    exactStructuralNavigationProjection(moved.state),
    exactStructuralNavigationProjection(states[transition.to_index]));
}
for (const [captureName,capture] of Object.entries(
  editorExtraStructuralNavigationOracles.captures)) {
  let state = extraStructuralNavigationStates[captureName][0];
  for (let index = 0; index + 1 < capture.states.length; index++)
    state = rom.editorMoveCursor(
      state,editorExtraStructuralNavigationOracles.transitions.find(
        transition => transition.capture === captureName &&
          transition.from_index === index).direction,font).state;
  expectEqual(`${captureName} composable exact final state`,
    exactStructuralNavigationProjection(state),
    exactStructuralNavigationProjection(
      extraStructuralNavigationStates[captureName].at(-1)));
}
expectEqual('live editor summation-fill oracle schema',
  editorSummationFillOracle.schema,1);
const summationFillCapture = editorSummationFillOracle.captures.summation_fill;
expectEqual('live editor summation-fill capture macro hash',
  crypto.createHash('sha256').update(fs.readFileSync(path.join(
    root,summationFillCapture.macro))).digest('hex'),
  summationFillCapture.macro_sha256);
expectEqual('live editor summation-fill state/step count',
  summationFillCapture.states.length,
  editorSummationFillOracle.steps.length + 1);
const summationFillStates = summationFillCapture.states.map(
  (state,index) => {
    const decoded = rom.decodeMathPrintEditorRam(sparseEditorRam(
      state,`summation fill state ${index}`));
    const reconstructed = rom.constructEditorExpressionProgram(
      decoded.editor.expression,7,font);
    expectEqual(`summation fill state ${index} reconstructed records`,
      editorRecordsById(reconstructed.nodes),editorRecordsById(decoded.nodes));
    const operations = rom.executeSettledRecordProgram(
      reconstructed.nodes,reconstructed.wrapper_id,
      {glyphAdvance:editorGlyphAdvance});
    const lcd = rom.rasterizeSettledOperations(operations,font).grid;
    expectEqual(`summation fill state ${index} LCD bitmap`,
      crypto.createHash('sha256').update(
        packedLcdBytes(lcd)).digest('hex'),state.lcd_bitmap_sha256);
    return decoded;
  });
const blankSummationOracle = editorStructuralMutationOracles.transitions.find(
  oracle => oracle.name === 'blank_root_insert_summation');
if (!blankSummationOracle)
  throw new Error('blank-root summation insertion oracle is absent');
const blankSummationState = rom.decodeMathPrintEditorRam(sparseEditorRam(
  blankSummationOracle.pre,'blank-to-filled summation root'));
const insertedSummation = rom.editorInsertStructuralTemplate(
  blankSummationState,blankSummationOracle.source_token,font);
expectEqual('blank-to-filled summation structural insertion state',
  editorStateProjection(insertedSummation.state),
  editorStateProjection(summationFillStates[0]));
let summationFillState = insertedSummation.state;
for (let index = 0; index < editorSummationFillOracle.steps.length; index++) {
  const step = editorSummationFillOracle.steps[index];
  const result = step.operation === 'insert'
    ? rom.editorInsertPackedToken(summationFillState,step.token)
    : rom.editorMoveCursor(summationFillState,step.direction);
  expectEqual(`summation fill ${step.name} translated route`,{
    operation:step.operation,
    ...(step.operation === 'insert'
      ? {token:result.mutation.inserted}
      : {direction:result.mutation.direction}),
    status:result.mutation.status,
    routine:result.mutation.routine,
  },{
    operation:step.operation,
    ...(step.operation === 'insert'
      ? {token:step.token}
      : {direction:step.direction}),
    status:step.status,
    routine:step.routine,
  });
  expectEqual(`summation fill ${step.name} decoded state`,
    structuralNavigationProjection(result.state),
    structuralNavigationProjection(summationFillStates[index + 1]));
  summationFillState = result.state;
}
expectThrows('decoded editor cursor movement rejects an invalid direction',
  RangeError,() => rom.editorMoveCursor(
    structuralNavigationStates.right[0],'up'));
const syntheticNavigationState = (
  nodes,entryId,activeId,byteOffset,controllerId,structuralDepth) => {
  const controller = nodes.find(node => node.id === controllerId);
  const decoded = rom.decodeEditorExpressionGraph(
    nodes,entryId,activeId,byteOffset);
  return {
    entryId,nodes,
    controller:{
      recordId:controllerId,renderType:controller.type,
      structuralDepth,activeLeafId:activeId,
    },
    expression:rom.decodeSettledExpressionGraph(nodes,entryId),
    editor:{expression:decoded.expression,cursor:{
      ...decoded.cursor,
      left:nodes.find(node => node.id === activeId).payload.slice(0,byteOffset),
      right:nodes.find(node => node.id === activeId).payload.slice(byteOffset),
    }},
  };
};
const structuralNavigationArena = (type,childCount,options = {}) => {
  const structuralId = 3;
  const childIds = Array.from({length:childCount},(_,index) => 4 + index);
  const marker = [0xef,type,structuralId,0,0xef,0x2d];
  const prefix = type === 0x2a ? [0x31] : [];
  const atomicChildren = new Set(options.atomicChildren || []);
  const structural = {
    id:structuralId,type,word05:1,word0F:0,
    word11:type === 0x2b ? (options.columns || 1) << 8 : 1,
    byte13:type === 0x2b ? (options.rows || childCount) : 0,
    child_ids:childIds,payload:[],
  };
  const nodes = [
    {id:1,type:0x1f,word05:1,word0F:0,word11:0,
      child_ids:[2],payload:[]},
    structural,
    {id:2,type:0,word05:0,word0F:prefix.length,
      word11:prefix.length + marker.length,
      child_ids:[],payload:[...prefix,...marker]},
    ...childIds.map((id,index) => ({
      id,type:atomicChildren.has(index) ? 1 : 0,
      word05:0,word0F:0,word11:index === 0 ? 2 : 1,
      child_ids:[],payload:index === 0 ? [0x5d,0x00] : [0x31 + index],
    })),
  ];
  return syntheticNavigationState(nodes,2,2,prefix.length,1,0);
};
for (const domain of [
  {name:'fraction',type:0x20,children:2},
  {name:'absolute value',type:0x21,children:1},
  {name:'integral',type:0x22,children:4,atomicChildren:[3]},
  {name:'nDeriv',type:0x23,children:3,atomicChildren:[0]},
  {name:'nth root',type:0x24,children:2},
  {name:'radical',type:0x25,children:1},
  {name:'e power',type:0x26,children:1},
  {name:'ten power',type:0x27,children:1},
  {name:'log base',type:0x28,children:2},
  {name:'summation',type:0x29,children:4,atomicChildren:[0]},
  {name:'power',type:0x2a,children:1},
  {name:'six-child matrix',type:0x2b,children:6,rows:2,columns:3},
]) {
  const rootExitOffset = domain.type === 0x2a ? 7 : 6;
  let state = structuralNavigationArena(
    domain.type,domain.children,{rows:domain.rows,columns:domain.columns,
      atomicChildren:domain.atomicChildren});
  let moved = rom.editorMoveCursor(state,'right');
  expectEqual(`${domain.name} enters its first child`,{
    status:moved.mutation.status,recordId:moved.state.editor.cursor.recordId,
    byteOffset:moved.state.editor.cursor.byteOffset,
  },{status:'entered-structural-record',recordId:4,byteOffset:0});
  state = moved.state;
  for (let index = 0; index < domain.children; index++) {
    const atomic = (domain.atomicChildren || []).includes(index);
    if (!atomic) {
      moved = rom.editorMoveCursor(state,'right');
      expectEqual(`${domain.name} moves through child ${index}`,
        moved.mutation.status,'moved-packed-token');
      state = moved.state;
    }
    moved = rom.editorMoveCursor(state,'right');
    const last = index === domain.children - 1;
    expectEqual(`${domain.name} leaves child ${index}`,{
      status:moved.mutation.status,recordId:moved.state.editor.cursor.recordId,
      byteOffset:moved.state.editor.cursor.byteOffset,
      depth:moved.state.controller.structuralDepth,
    },last
      ? {status:'exited-structural-record',recordId:2,
        byteOffset:rootExitOffset,depth:0}
      : {status:'selected-structural-sibling',recordId:5 + index,
        byteOffset:0,depth:1});
    state = moved.state;
  }
  moved = rom.editorMoveCursor(state,'left');
  expectEqual(`${domain.name} re-enters its last child`,{
    status:moved.mutation.status,recordId:moved.state.editor.cursor.recordId,
    childIndex:moved.mutation.selected_child_index,
    byteOffset:moved.state.editor.cursor.byteOffset,
  },{status:'entered-structural-record',recordId:3 + domain.children,
    childIndex:domain.children - 1,
    byteOffset:(domain.atomicChildren || []).includes(domain.children - 1)
      ? 0 : domain.children === 1 ? 2 : 1});
}
const nestedNavigationNodes = [
  {id:1,type:0x1f,word05:1,word0F:0,word11:0,
    child_ids:[2],payload:[]},
  {id:3,type:0x21,word05:1,word0F:0,word11:1,
    child_ids:[4],payload:[]},
  {id:5,type:0x20,word05:1,word0F:0,word11:1,
    child_ids:[6,7],payload:[]},
  {id:2,type:0,word05:0,word0F:0,word11:6,child_ids:[],
    payload:[0xef,0x21,3,0,0xef,0x2d]},
  {id:4,type:0,word05:0,word0F:0,word11:6,child_ids:[],
    payload:[0xef,0x20,5,0,0xef,0x2d]},
  {id:6,type:0,word05:0,word0F:0,word11:1,child_ids:[],payload:[0x31]},
  {id:7,type:0,word05:0,word0F:0,word11:1,child_ids:[],payload:[0x32]},
];
let nestedNavigation = syntheticNavigationState(
  nestedNavigationNodes,2,2,0,1,0);
nestedNavigation = rom.editorMoveCursor(nestedNavigation,'right').state;
expectEqual('nested navigation enters the outer structural leaf',{
  controller:nestedNavigation.controller.recordId,
  record:nestedNavigation.editor.cursor.recordId,
  depth:nestedNavigation.controller.structuralDepth,
},{controller:3,record:4,depth:1});
nestedNavigation = rom.editorMoveCursor(nestedNavigation,'right').state;
expectEqual('nested navigation enters the inner structural leaf',{
  controller:nestedNavigation.controller.recordId,
  record:nestedNavigation.editor.cursor.recordId,
  depth:nestedNavigation.controller.structuralDepth,
},{controller:5,record:6,depth:2});
nestedNavigation = rom.editorMoveCursor(nestedNavigation,'left').state;
expectEqual('nested navigation exits to the containing outer leaf',{
  controller:nestedNavigation.controller.recordId,
  record:nestedNavigation.editor.cursor.recordId,
  byteOffset:nestedNavigation.editor.cursor.byteOffset,
  depth:nestedNavigation.controller.structuralDepth,
},{controller:3,record:4,byteOffset:0,depth:1});
nestedNavigation = rom.editorMoveCursor(nestedNavigation,'left').state;
expectEqual('nested navigation exits to the root leaf',{
  controller:nestedNavigation.controller.recordId,
  record:nestedNavigation.editor.cursor.recordId,
  byteOffset:nestedNavigation.editor.cursor.byteOffset,
  depth:nestedNavigation.controller.structuralDepth,
},{controller:1,record:2,byteOffset:0,depth:0});
expectEqual('live editor deletion oracle schema',editorDeletionOracles.schema,1);
for (const oracle of editorDeletionOracles.transitions) {
  expectEqual(`${oracle.name} deletion capture macro hash`,
    crypto.createHash('sha256').update(fs.readFileSync(path.join(
      root,oracle.macro))).digest('hex'),oracle.macro_sha256);
  const before = rom.decodeMathPrintEditorRam(sparseEditorRam(
    oracle.pre,`${oracle.name} pre-deletion`));
  const after = rom.decodeMathPrintEditorRam(sparseEditorRam(
    oracle.post,`${oracle.name} post-deletion`));
  const deleted = rom.editorDeletePackedToken(before.editor.expression);
  expectEqual(`${oracle.name} translated deletion path`,deleted.mutation,{
    deleted:oracle.deleted_token,
    record_id:before.editor.cursor.recordId,
    byte_offset:before.editor.cursor.byteOffset,
    restored_empty_slot:oracle.restored_empty_slot,
    routine:oracle.trace.routine,
  });
  expectEqual(`${oracle.name} decoded editor transition`,
    deleted.expression,after.editor.expression);
  const reconstructed = rom.constructEditorExpressionProgram(
    deleted.expression,7,font);
  expectEqual(`${oracle.name} reconstructed post-deletion records`,
    editorRecordsById(reconstructed.nodes),editorRecordsById(after.nodes));
  const operations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  expectEqual(`${oracle.name} reconstructed post-deletion LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
    oracle.post.lcd_bitmap_sha256);
}
expectEqual('live editor structural-deletion oracle schema',
  editorStructuralDeletionOracles.schema,4);
for (const oracle of editorStructuralDeletionOracles.transitions) {
  expectEqual(`${oracle.name} structural-deletion capture macro hash`,
    crypto.createHash('sha256').update(fs.readFileSync(path.join(
      root,oracle.macro))).digest('hex'),oracle.macro_sha256);
  const before = rom.decodeMathPrintEditorRam(sparseEditorRam(
    oracle.pre,`${oracle.name} pre-structural-deletion`));
  const after = rom.decodeMathPrintEditorRam(sparseEditorRam(
    oracle.post,`${oracle.name} post-structural-deletion`));
  const deleted = rom.editorDeleteStructuralTemplate(before);
  expectEqual(`${oracle.name} translated structural deletion`,
    deleted.mutation,oracle.mutation);
  expectEqual(`${oracle.name} decoded structural-deletion transition`,
    deleted.expression,after.editor.expression);
  let expectedController = before.controller;
  if (oracle.mutation.status === 'deleted-structural-template') {
    const owner = after.nodes.find(node =>
      node.child_ids.includes(oracle.mutation.parent_record_id));
    if (!owner)
      throw new Error(`${oracle.name} post-deletion parent controller is absent`);
    expectedController = {
      recordId:owner.id,renderType:owner.type,
      structuralDepth:oracle.mutation.after_structural_depth,
      activeLeafId:oracle.mutation.parent_record_id,
    };
  }
  expectEqual(`${oracle.name} post-deletion controller`,
    after.controller,expectedController);
  const reconstructed = rom.constructEditorExpressionProgram(
    deleted.expression,7,font);
  const canonicalLiveRecord = node => {
    const record = canonicalEditorRecord(node);
    // The ROM leaves the removed marker's EFh in physical byte +13h when the
    // resulting active payload is empty. It lies outside the zero-byte logical
    // payload and does not participate in decode or rendering.
    if (!record.payload.length) record.byte13 = 0;
    return record;
  };
  expectEqual(`${oracle.name} reconstructed structural-deletion records`,
    reconstructed.nodes.map(canonicalLiveRecord).sort(
      (left,right) => left.record_id - right.record_id),
    after.nodes.map(canonicalLiveRecord).sort(
      (left,right) => left.record_id - right.record_id));
  const operations = rom.executeSettledRecordProgram(
    reconstructed.nodes,reconstructed.wrapper_id,
    {glyphAdvance:editorGlyphAdvance});
  const lcd = rom.rasterizeSettledOperations(operations,font).grid;
  expectEqual(`${oracle.name} reconstructed post-deletion LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(lcd)).digest('hex'),
    oracle.post.lcd_bitmap_sha256);
}
const blankStructuralDeletionClasses = new Map([
  ['blank_root_insert_fraction',[0x20,'deleted-structural-template']],
  ['blank_root_insert_absolute',[0x21,'deleted-structural-template']],
  ['blank_root_insert_integral',[0x22,'protected-multi-argument-template']],
  ['blank_root_insert_nderiv',[0x23,'protected-multi-argument-template']],
  ['blank_root_insert_nthroot',[0x24,'deleted-structural-template']],
  ['blank_root_insert_epower',[0x25,'deleted-structural-template']],
  ['blank_root_insert_tenpower',[0x26,'deleted-structural-template']],
  ['blank_root_insert_radical',[0x27,'deleted-structural-template']],
  ['blank_root_insert_logbase',[0x28,'protected-multi-argument-template']],
  ['blank_root_insert_summation',[0x29,'protected-multi-argument-template']],
  ['blank_root_insert_power',[0x2a,'deleted-structural-template']],
]);
for (const [name,[renderType,status]] of blankStructuralDeletionClasses) {
  const insertion = editorStructuralMutationOracles.transitions.find(
    oracle => oracle.name === name);
  if (!insertion)
    throw new Error(`${name} structural insertion oracle is absent`);
  const before = rom.decodeMathPrintEditorRam(sparseEditorRam(
    insertion.post,`${name} blank structural-deletion class`));
  const deleted = rom.editorDeleteStructuralTemplate(before);
  expectEqual(`${name} blank structural-deletion dispatch`,{
    render_type:deleted.mutation.render_type,status:deleted.mutation.status,
  },{render_type:renderType,status});
  if (status === 'protected-multi-argument-template')
    expectEqual(`${name} protected deletion preserves the cursor tree`,
      deleted.expression,before.editor.expression);
}
const packedDelete = rom.editorDeletePackedToken({
  kind:'sequence',parts:[
    {kind:'editorCursor',record_id:7,byte_offset:0,
      record_word0F:0,record_word11:0},
    [0x5d,0x00,0x31],
  ],
});
expectEqual('editor deletion removes a two-byte native token as one unit',
  packedDelete,{
    expression:{kind:'sequence',parts:[
      {kind:'editorCursor',record_id:7,byte_offset:0,
        record_word0F:0,record_word11:0},
      [0x31],
    ]},
    mutation:{deleted:[0x5d,0x00],record_id:7,byte_offset:0,
      restored_empty_slot:false,
      routine:'34:4570 → 00:3687 → 06:4393–43A4'},
  });
expectThrows('editor deletion rejects a leaf endpoint',RangeError,
  () => rom.editorDeletePackedToken(
    editorNavigationStates.end.editor.expression));
expectThrows('editor deletion rejects a structural boundary',RangeError,
  () => rom.editorDeletePackedToken({kind:'sequence',parts:[
    {kind:'editorCursor',record_id:7,byte_offset:0,
      record_word0F:0,record_word11:0},
    {kind:'fraction',numerator:[0x31],denominator:[0x32]},
  ]}));
expectThrows('live editor constructor requires exactly one cursor', RangeError,
  () => rom.constructEditorExpressionProgram([0x31],7,font));
expectThrows('live editor constructor validates retained cursor record identity',
  RangeError, () => rom.constructEditorExpressionProgram({
    kind:'sequence', parts:[[0x31],{
      kind:'editorCursor',record_id:8,byte_offset:1,
      record_word0F:1,record_word11:1,
    }],
  },7,font));
const inlineCursorProgram = rom.constructEditorExpressionProgram({
  kind:'sequence', parts:[
    [0x31], {
      kind:'editorCursor',record_id:7,byte_offset:1,
      record_word0F:1,record_word11:1,
    }, [0x32],
  ],
},7,font);
expectEqual('live cursor participates in leaf metrics before following tokens',
  canonicalEditorRecord(
    inlineCursorProgram.nodes.find(node => node.record_id === 7)), {
    record_id:7,render_type:0,word03:6,word05:7,word07:12,word09:3,
    word0B:0,word0D:0,word0F:1,word11:1,byte13:0x31,
    child_ids:[],payload:[0x31,0x32],
  });
expectEqual('live cursor overlays a following token without advancing the leaf pen',
  rom.executeSettledRecordProgram(
    inlineCursorProgram.nodes,inlineCursorProgram.wrapper_id).map(operation => ({
      kind:operation.kind,x:operation.x,y:operation.y,
      ...(operation.kind === 'glyph' ? {code:operation.code} : {}),
    })), [
    {kind:'glyph',x:0,y:0,code:0x31},
    {kind:'editor-cursor-cell',x:6,y:0},
    {kind:'glyph',x:6,y:0,code:0x32},
  ]);
const numeratorCursorProgram = rom.constructEditorExpressionProgram({
  kind:'fraction',
  numerator:{kind:'sequence',parts:[
    {kind:'editorCursor',byte_offset:0},
    {kind:'radical',radicand:[0x32]},
  ]},
  denominator:[0x33],
},7,font);
expectEqual('cursor before a structural numerator retains numerator allocation state', {
  active_record_id:numeratorCursorProgram.editor.active_record_id,
  radical_byte13:numeratorCursorProgram.nodes.find(
    node => node.render_type === 0x27).byte13,
  record_ids:numeratorCursorProgram.nodes.map(node => node.record_id).sort(
    (left,right) => left - right),
}, {
  active_record_id:11,
  radical_byte13:0x10,
  record_ids:[6,7,8,9,10,11,12],
});
const emptyNumeratorRam = sparseEditorRam(
  editorGapOracles.cases.find(oracle =>
    oracle.name === 'fraction_empty'),
  'empty numerator insertion source');
const emptyNumerator = rom.decodeMathPrintEditorRam(emptyNumeratorRam);
const filledNumerator = rom.editorInsertPackedToken(
  emptyNumerator,[0x31]);
expectEqual('ordinary insertion replaces an empty-slot token', {
  mutation:filledNumerator.mutation,
  expression:filledNumerator.expression,
}, {
  mutation:{
    inserted:[0x31],record_id:9,before_byte_offset:0,
    after_byte_offset:1,replaced_empty_slot:true,
    routine:'34:4775–47A4 → 34:4BB9–4C0D → 00:3699 → 06:4341–4388',
  },
  expression:{
    kind:'fraction',
    numerator:{kind:'sequence',parts:[
      [0x31],{kind:'editorCursor',record_id:9,byte_offset:1,
        record_word0F:0,record_word11:2,editor_leaf_record_id:9},
    ],editor_leaf_record_id:9},
    denominator:{kind:'extendedToken',tokens:[0xef,0x1e],
      editor_leaf_record_id:10},
    editor_record_id:8,
    editor_record_byte13:0xef,
    editor_child_selector:1,
    editor_leaf_record_id:7,
  },
});
const filledNumeratorProgram = rom.constructEditorExpressionProgram(
  filledNumerator.expression,7,font);
expectEqual('filled numerator retains the active leaf and pre-gap header words',
  canonicalEditorRecord(filledNumeratorProgram.nodes.find(
    node => node.record_id === 9)), {
    record_id:9,render_type:0,word03:8,word05:5,word07:9,word09:2,
    word0B:2,word0D:0,word0F:0,word11:2,byte13:0x31,
    child_ids:[],payload:[0x31],
  });
expectThrows('ordinary insertion rejects multiple packed tokens', RangeError,
  () => rom.editorInsertPackedToken(emptyNumerator,[0x31,0x32]));
expectThrows('ordinary insertion rejects structural markers', RangeError,
  () => rom.editorInsertPackedToken(
    emptyNumerator,[0xef,0x20,8,0,0xef,0x2d]));

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

expectEqual('34:58F9 reads a single-byte packed token',
  rom.settledReadPackedToken([0x58,0x5d,0x00],0), {
    prefix:0,token:0x58,packed:0x58,bytes:[0x58],offset:0,next:1,length:1,
  });
expectEqual('34:58F9 reads a two-byte packed token',
  rom.settledReadPackedToken([0x58,0x5d,0x00],1), {
    prefix:0x5d,token:0,packed:0x5d00,bytes:[0x5d,0],offset:1,next:3,length:2,
  });
expectEqual('34:5911 walks backward across a two-byte token',
  rom.settledReadPackedTokenBackward([0x58,0x5d,0x00],3), {
    prefix:0x5d,token:0,packed:0x5d00,bytes:[0x5d,0],offset:1,next:3,length:2,
  });
expectEqual('34:5911 walks backward across a single-byte token',
  rom.settledReadPackedTokenBackward([0x58,0x5d,0x00],1), {
    prefix:0,token:0x58,packed:0x58,bytes:[0x58],offset:0,next:1,length:1,
  });
expectThrows('34:58F9 rejects a truncated native two-byte token', RangeError,
  () => rom.settledReadPackedToken([0x58,0x5d],1));
expectEqual('native token iterator preserves packed offsets',
  rom.settledNativeTokenUnits([0x58,0xf0,0x5d,0x00]).units.map(unit =>
    [unit.offset,unit.length,unit.packed]),
  [[0,1,0x58],[1,1,0xf0],[2,2,0x5d00]]);

expectEqual('browser parses explicit native token bytes',
  mp.parseNativeTokenInput(' hex: EF 33, 4E f0 32 '),
  [0xef,0x33,0x4e,0xf0,0x32]);
expectEqual('browser leaves expression text outside raw native mode',
  mp.parseNativeTokenInput('sum(N,1,3,N^2)'), null);
expectThrows('browser rejects an empty native byte stream', RangeError,
  () => mp.parseNativeTokenInput('hex:'));
expectThrows('browser rejects a short hexadecimal byte', RangeError,
  () => mp.parseNativeTokenInput('hex: EF 3'));
expectThrows('browser rejects 0x-prefixed hexadecimal fields', RangeError,
  () => mp.parseNativeTokenInput('hex: 0xEF 33'));
expectThrows('raw native mode rejects a truncated two-byte token', RangeError,
  () => mp.generatedForInput('hex: 5D'));
expectThrows('raw native mode rejects an unmatched group', RangeError,
  () => mp.generatedForInput('hex: 10 31'));
let ef36BrowserError = null;
try {
  mp.generatedForInput('hex: EF 36 31 11');
} catch (error) {
  ef36BrowserError = error;
}
if (!(ef36BrowserError instanceof RangeError))
  throw new Error('raw native EF36h path did not stop at the ROM reset boundary');
expectEqual('raw native EF36h path reports the traced terminal dispatch',
  [ef36BrowserError.code,ef36BrowserError.message,
   ef36BrowserError.romPath.terminal.path], [
    'SETTLED_EF36_RESET',
    'EF36h constructs type 0x2C, whose out-of-range 34:7611 geometry dispatch resets through ram:3BCD',
    ['34:7609','34:6105','ram:3BCD','03:467F','ram:0002','ram:028C','3F:412C'],
  ]);

const rawChangedSummation = mp.generatedForInput(
  'hex: EF 33 4E F0 33 70 32 2B 4E 2B 31 32 2B 33 34 11');
expectEqual('raw native mode preserves changed summation bytes',
  rawChangedSummation.nativeTokens,
  [0xef,0x33,0x4e,0xf0,0x33,0x70,0x32,0x2b,
   0x4e,0x2b,0x31,0x32,0x2b,0x33,0x34,0x11]);
expectEqual('raw native mode exposes every changed summation LCD byte write',
  rawChangedSummation.events.length, 104);
if (rawChangedSummation.events.some(event => event.pixels.length !== 8 ||
    event.pixels.some(pixel => pixel.changed !== (pixel.before !== pixel.value))))
  throw new Error('raw native mode has an incomplete pixel-level LCD trace');
expectEqual('raw native mode reaches its byte-replayed 96x64 framebuffer',
  mp.traceFrame(rawChangedSummation, rawChangedSummation.events.length),
  rom.replaySettledLcdWrites(rawChangedSummation.events));

const parseAheadAbi = result => ({
  a:result.a, stopCursor:result.stopCursor, de:result.de,
  zero:result.zero, carry:result.carry, scratch:result.scratch,
});

// The retained sum(N,1,3,N) trace exposes the four internal 34:5AA3 calls
// that split its source buffer. These values are relative translations of
// native 0x9DB8–0x9DBF pointers and preserve the returned registers, flags,
// and 0x9D02–0x9D05 scratch bytes.
const summationParseBuffer = [0x4e,0x2b,0x4e,0x2b,0x31,0x2b,0x33,0x11];
for (const [cursor, expected] of [
  [-1,{a:0,stopCursor:1,de:0,zero:false,carry:false,scratch:[0,1,0,0]}],
  [1,{a:0,stopCursor:3,de:0,zero:false,carry:false,scratch:[0,1,0,0]}],
  [3,{a:0,stopCursor:5,de:0,zero:false,carry:false,scratch:[0,1,0,0]}],
  [5,{a:0x11,stopCursor:7,de:0xff00,zero:true,carry:true,
      scratch:[0,1,0,0]}],
]) expectEqual(`34:5AA3 summation parse trace from byte ${cursor}`,
  parseAheadAbi(rom.settledParseAhead(summationParseBuffer,{
    entry:'internal5AA3',c:1,cursor,
  })),expected);

expectEqual('34:5AA7 preserves B and clears C',
  parseAheadAbi(rom.settledParseAhead([0x4e],{
    entry:'direct5AA7',b:0x12,c:0xff,
  })), {
    a:0,stopCursor:1,de:0,zero:true,carry:true,scratch:[0x12,0,0,0],
  });
expectEqual('34:5AA3 clears B and preserves C',
  parseAheadAbi(rom.settledParseAhead([0x4e],{
    entry:'internal5AA3',b:0x12,c:1,
  })), {
    a:0,stopCursor:1,de:0,zero:true,carry:true,scratch:[0,1,0,0],
  });
expectEqual('34:5AA9 preserves caller B and C after RES 6,B',
  parseAheadAbi(rom.settledParseAhead([0x4e],{
    entry:'internal5AA9',b:0x52,c:1,
  })), {
    a:0,stopCursor:1,de:0,zero:true,carry:true,scratch:[0x12,1,0,0],
  });
for (const [entry, expectedScratch] of [
  ['aheadEqual',[0x80,0,0,0]],
  ['parsAheadS',[1,0,0,0]],
  ['parsAhead',[0,0,0,0]],
]) expectEqual(`${entry} initializes its public-entry mode bytes`,
  parseAheadAbi(rom.settledParseAhead([0x4e],{
    entry,b:0xff,c:0xff,
  })).scratch,expectedScratch);

for (const [bytes, expected] of [
  [[0x12],true], [[0x28],true], [[0x29],false],
  [[0x9e],true], [[0xa5],true], [[0xa6],false],
  [[0xb1],true], [[0xcd],true], [[0xce],false],
  [[0xda],true], [[0xdb],true], [[0xee],true], [[0xef],false],
  [[0xbb,0x1f],true], [[0xbb,0x20],false],
  [[0xbb,0x25],true], [[0xbb,0x2e],true], [[0xbb,0x2f],false],
  [[0xbb,0x49],true], [[0xbb,0x4a],false],
  [[0xef,0x08],true], [[0xef,0x09],false],
  [[0xef,0x13],true], [[0xef,0x2e],false],
  [[0xef,0x32],true], [[0xef,0x35],true], [[0xef,0x36],false],
  [[0x5d,0x00],false],
]) expectEqual(`34:5A05 classifies ${bytes.map(value =>
  value.toString(16).padStart(2,'0')).join(' ')}`,
  rom.settledParseAheadFunctionToken(
    bytes.length === 2 ? bytes[0] : 0, bytes.at(-1)), expected);

for (const [label, bytes, expected] of [
  ['absolute value with nested radical',
    [0xb2,0xbc,0x58,0x11,0x11], {
      renderType:0x21, scanKind:3, metadata:[3,1,0,0,0],
      argumentChildOrder:[1], ranges:[[1,4,0x11,1]], stopCursor:4,
    }],
  ['integral source-to-child permutation',
    [0x24,0x58,0xf0,0x32,0x2b,0x58,0x2b,0x31,0x2b,0x32,0x11], {
      renderType:0x22, scanKind:4, metadata:[4,3,4,1,2],
      argumentChildOrder:[3,4,1,2],
      ranges:[[1,4,0x2b,3],[5,6,0x2b,4],[7,8,0x2b,1],[9,10,0x11,2]],
      stopCursor:10,
    }],
  ['summation source-to-child permutation',
    [0xef,0x33,0x4e,0xf0,0x32,0x2b,0x4e,0x2b,0x31,0x2b,0x33,0x11], {
      renderType:0x29, scanKind:4, metadata:[4,4,1,2,3],
      argumentChildOrder:[4,1,2,3],
      ranges:[[2,5,0x2b,4],[6,7,0x2b,1],[8,9,0x2b,2],[10,11,0x11,3]],
      stopCursor:11,
    }],
  ['nDeriv source-to-child permutation',
    [0x25,0x58,0xf0,0x32,0x2b,0x58,0x2b,0x31,0x11], {
      renderType:0x23, scanKind:4, metadata:[4,2,1,3,0],
      argumentChildOrder:[2,1,3],
      ranges:[[1,4,0x2b,2],[5,6,0x2b,1],[7,8,0x11,3]],
      stopCursor:8,
    }],
  ['logBASE source-to-child permutation',
    [0xef,0x34,0x33,0x34,0x35,0x2b,0x31,0x32,0x11], {
      renderType:0x28, scanKind:4, metadata:[4,2,1,0,0],
      argumentChildOrder:[2,1],
      ranges:[[2,5,0x2b,2],[6,8,0x11,1]], stopCursor:8,
    }],
]) {
  const scan = rom.settledStructuralArgumentScan(bytes);
  expectEqual(`34:5678 ${label}`, {
    renderType:scan.renderType,
    scanKind:scan.scanKind,
    metadata:scan.metadata,
    argumentChildOrder:scan.argumentChildOrder,
    ranges:scan.arguments.map(argument => [
      argument.start,argument.end,argument.delimiter,argument.childIndex,
    ]),
    stopCursor:scan.stopCursor,
  },expected);
}
expectThrows('34:5678 rejects a nonstructural opener', RangeError,
  () => rom.settledStructuralArgumentScan([0x58]));
expectThrows('34:5678 rejects an offset inside a packed token', RangeError,
  () => rom.settledStructuralArgumentScan([0xef,0x33,0x31,0x2b,
    0x4e,0x2b,0x31,0x2b,0x33,0x11],1));
expectThrows('34:5678 rejects a missing structural close', RangeError,
  () => rom.settledStructuralArgumentScan([0xb2,0x58]));

for (const [label, bytes, operatorOffset, expected] of [
  ['numeric raised run',[0x58,0xf0,0x31,0x32],1,{
    renderType:0x2a, metadata:[1,1,0,0,0], start:2, end:4,
    returnedCursor:4, restoredCursor:2, branch:'34:56A7 → 34:5866',
    parseAhead:null,
  }],
  ['outer editor slot',
    [0x32,0xf0,0x10,0x58,0xf0,0x10,0x32,0x0f,0x11,0x11],1,{
      renderType:0x2a, metadata:[1,1,0,0,0], start:2, end:10,
      returnedCursor:10, restoredCursor:2, branch:'34:56BB–56D3',
      parseAhead:{a:0x11,stopCursor:9,de:0xff00,zero:true,carry:true,
        scratch:[0x42,0,0,0]},
    }],
  ['nested editor slot',
    [0x32,0xf0,0x10,0x58,0xf0,0x10,0x32,0x0f,0x11,0x11],4,{
      renderType:0x2a, metadata:[1,1,0,0,0], start:5, end:9,
      returnedCursor:9, restoredCursor:5, branch:'34:56BB–56D3',
      parseAhead:{a:0x11,stopCursor:8,de:0xff00,zero:true,carry:true,
        scratch:[2,0,0,0]},
    }],
  ['nth-root editor slot',[0x32,0xf1,0x10,0x58,0x70,0x31,0x11],1,{
    renderType:0x24, metadata:[1,1,2,0,0], start:2, end:7,
    returnedCursor:7, restoredCursor:2, branch:'34:56BB–56D3',
    parseAhead:{a:0x11,stopCursor:6,de:0xff00,zero:true,carry:true,
      scratch:[2,0,0,0]},
  }],
]) {
  const scan = rom.settledRaisedOperandScan(bytes,operatorOffset);
  expectEqual(`34:5699 ${label}`,{
    renderType:scan.renderType,
    metadata:scan.metadata,
    start:scan.start,
    end:scan.end,
    returnedCursor:scan.returnedCursor,
    restoredCursor:scan.restoredCursor,
    branch:scan.branch,
    parseAhead:scan.parseAhead && parseAheadAbi(scan.parseAhead),
  },expected);
}
expectThrows('34:5699 rejects an untraced raised token-class branch',
  RangeError, () => rom.settledRaisedOperandScan([0x58,0xf0,0x64],1));
expectThrows('34:5699 rejects a missing raised close', RangeError,
  () => rom.settledRaisedOperandScan([0x58,0xf0,0x10,0x31],1));

for (const [label,prefix,token,expected] of [
  ['letter',0,0x58,{accepted:true,nameByteLimit:0}],
  ['Ans',0,0x72,{accepted:true,nameByteLimit:0}],
  ['matrix name',0x5c,0,{accepted:true,nameByteLimit:0}],
  ['string name',0xaa,0,{accepted:true,nameByteLimit:0}],
  ['pi',0,0xac,{accepted:true,nameByteLimit:0}],
  ['program designator',0,0x5f,{accepted:true,nameByteLimit:8}],
  ['list designator',0,0xeb,{accepted:true,nameByteLimit:5}],
  ['BB31',0xbb,0x31,{accepted:true,nameByteLimit:0}],
  ['other BB',0xbb,0x30,{accepted:false,nameByteLimit:0}],
  ['mode token',0,0x64,{accepted:false,nameByteLimit:0}],
]) {
  const actual = rom.settledRaisedExtendedTokenClass(prefix,token);
  expectEqual(`34:580C ${label}`,{
    accepted:actual.accepted,nameByteLimit:actual.nameByteLimit,
  },expected);
}
for (const [label,bytes,end,branch] of [
  ['direct letter',[0x58,0xf0,0x59],3,'34:580C → 34:5861'],
  ['direct Ans',[0x58,0xf0,0x72],3,'34:580C → 34:5861'],
  ['direct L1',[0x58,0xf0,0x5d,0x00],4,'34:580C → 34:5861'],
  ['program name',[0x58,0xf0,0x5f,0x41,0x31,0x42,0x70],6,
    '34:580C → 34:5836 (max 8)'],
  ['program name limit',[0x58,0xf0,0x5f,0x41,0x42,0x43,0x44,0x45,
    0x46,0x47,0x48,0x49],11,'34:580C → 34:5836 (max 8)'],
  ['list name low stop',[0x58,0xf0,0xeb,0x41,0x0a,0x2b],4,
    '34:580C → 34:5836 (max 5)'],
  ['list name high stop',[0x58,0xf0,0xeb,0x41,0x5c,0x00],4,
    '34:580C → 34:5836 (max 5)'],
]) {
  const scan = rom.settledRaisedOperandScan(bytes,1);
  expectEqual(`34:5699 ${label}`,{
    start:scan.start,end:scan.end,returnedCursor:scan.returnedCursor,
    restoredCursor:scan.restoredCursor,branch:scan.branch,
    accepted:scan.classifier.accepted,
    nameByteLimit:scan.classifier.nameByteLimit,
  },{start:2,end,returnedCursor:end,restoredCursor:2,branch,
    accepted:true,nameByteLimit:branch.includes('5836')
      ? Number(branch.match(/max (\d+)/)[1]) : 0});
}
expectEqual('34:583D bounded name digit path',
  rom.settledRaisedNameScan([0x31,0x41,0x2b],0,5),{
    start:0,end:2,acceptedBytes:2,limit:5,
    stop:'non_name_byte_below_41h',
    path:[
      '34:5840:fallthrough','34:5845:taken','34:5853:taken',
      '34:5840:fallthrough','34:5845:fallthrough',
      '34:5849:fallthrough','34:584D:fallthrough','34:5853:taken',
      '34:5840:fallthrough','34:5845:fallthrough','34:5849:taken',
    ],
  });
expectEqual('34:583D bounded name source boundary',
  rom.settledRaisedNameScan([0x41],0,5),{
    start:0,end:1,acceptedBytes:1,limit:5,stop:'source_boundary',
    path:[
      '34:5840:fallthrough','34:5845:fallthrough',
      '34:5849:fallthrough','34:584D:fallthrough','34:5853:taken',
      '34:5840:taken',
    ],
  });
expectEqual('bounded program name is one expression atom',
  rom.settledExpressionFromTokens([0x58,0xf0,0x5f,0x41,0x31]),{
    kind:'power',base:{kind:'tokens',tokens:[0x58]},
    exponent:{kind:'tokens',tokens:[0x5f,0x41,0x31]},
  });
for (const [label,nativeTokens] of [
  ['changed direct letter power',[0x58,0xf0,0x59]],
  ['changed direct Ans power',[0x58,0xf0,0x72]],
  ['changed direct list power',[0x58,0xf0,0x5d,0x00]],
  ['changed direct BB31 power',[0x58,0xf0,0xbb,0x31]],
]) {
  const generated = mp.generatedForNativeTokens(nativeTokens);
  if (!generated || !generated.events.length)
    throw new Error(`${label} has no generated LCD data-write timeline`);
  if (generated.operations.some(operation => operation.kind.startsWith('unresolved')) ||
      generated.events.some(event => event.pixels.length !== 8))
    throw new Error(`${label} has an unresolved pixel-level operation`);
  expectEqual(`${label} LCD replay`,
    rom.replaySettledLcdWrites(generated.events),
    generated.final.map(row => Array.from(row, pixel => Number(pixel))));
}

for (const [label, bytes, operatorOffset, numeratorStart, expected] of [
  ['single-token operands',[0x31,0xef,0x2e,0x32],1,0,{
    numerator:[0,1,0,0,0,1,false], denominator:[3,4,0,0,0,4,false],
    stopCursor:4,
  }],
  ['powered numerator',
    [0x10,0x58,0xf0,0x32,0x11,0xef,0x2e,0x33],5,0,{
      numerator:[0,5,0,0,0,5,false], denominator:[7,8,0,0,0,8,false],
      stopCursor:8,
    }],
  ['nested denominator',
    [0x31,0xef,0x2e,0x10,0x32,0xef,0x2e,0x33,0x11],1,0,{
      numerator:[0,1,0,0,0,1,false], denominator:[3,9,0,0,0,9,false],
      stopCursor:9,
    }],
  ['inner nested fraction',
    [0x31,0xef,0x2e,0x10,0x32,0xef,0x2e,0x33,0x11],5,4,{
      numerator:[4,5,0,0,0,5,false], denominator:[7,8,0,1,0,9,false],
      stopCursor:8,
    }],
  ['raised fraction wrapper',
    [0xf0,0x10,0x10,0x31,0xef,0x2e,0x32,0x11,0x11],4,3,{
      numerator:[3,4,0,0,0,4,false], denominator:[6,7,0,2,0,9,false],
      stopCursor:7,
    }],
]) {
  const scan = rom.settledFractionOperandScan(
    bytes,operatorOffset,numeratorStart);
  const range = operand => [
    operand.start,operand.end,operand.wrapper.nestingDepth,
    operand.wrapper.unwoundBoundaryCount,operand.wrapper.savedDepth,
    operand.wrapper.parseCursor,operand.wrapper.advancedSavedCursor,
  ];
  expectEqual(`34:5795 ${label}`,{
    numerator:range(scan.numerator),
    denominator:range(scan.denominator),
    stopCursor:scan.stopCursor,
  },expected);
}
expectThrows('34:5795 rejects an empty numerator', RangeError,
  () => rom.settledFractionOperandScan([0xef,0x2e,0x31],0,0));
expectThrows('34:5795 rejects an empty denominator', RangeError,
  () => rom.settledFractionOperandScan([0x31,0xef,0x2e],1,0));
expectThrows('34:5795 rejects a different fraction offset', RangeError,
  () => rom.settledFractionOperandScan(
    [0x31,0xef,0x2e,0x32,0xef,0x2e,0x33],4,0));

for (const [label, bytes, expected] of [
  ['one by one traced identity value',
    [0x06,0x06,0x31,0x07,0x07], {
      rows:1, columns:1, stopCursor:5,
      ranges:[[1,1,2,3,0x07,1,3,0xff]],
    }],
  ['two by two row-major value',
    [0x06,0x06,0x31,0x2b,0x32,0x07,
     0x06,0x33,0x2b,0x34,0x07,0x07], {
      rows:2, columns:2, stopCursor:12,
      ranges:[
        [1,1,2,3,0x2b,1,3,0], [1,2,4,5,0x07,3,5,0xff],
        [2,1,7,8,0x2b,6,8,0], [2,2,9,10,0x07,8,10,0xff],
      ],
    }],
  ['two by three traced signed value',
    [0x06,0x06,0x34,0x2b,0xb0,0x32,0x2b,0x30,0x07,
     0x06,0xb0,0x37,0x2b,0x38,0x2b,0x38,0x07,0x07], {
      rows:2, columns:3, stopCursor:18,
      ranges:[
        [1,1,2,3,0x2b,1,3,0], [1,2,4,6,0x2b,3,6,0],
        [1,3,7,8,0x07,6,8,0xff], [2,1,10,12,0x2b,9,12,0],
        [2,2,13,14,0x2b,12,14,0], [2,3,15,16,0x07,14,16,0xff],
      ],
    }],
  ['two by two structural-cell trace',
    [0x06,0x06,0xbc,0x32,0x11,0x2b,0x58,0x0d,0x07,
     0x06,0x33,0x2b,0x34,0x07,0x07], {
      rows:2, columns:2, stopCursor:15,
      ranges:[
        [1,1,2,5,0x2b,1,5,0], [1,2,6,8,0x07,5,8,0xff],
        [2,1,10,11,0x2b,9,11,0], [2,2,12,13,0x07,11,13,0xff],
      ],
    }],
]) {
  const scan = rom.settledMatrixContainerScan(bytes);
  expectEqual(`34:568A ${label}`,{
    renderType:scan.renderType,
    scanKind:scan.scanKind,
    metadata:scan.metadata,
    rows:scan.rows,
    columns:scan.columns,
    stopCursor:scan.stopCursor,
    ranges:scan.elements.map(element => [
      element.row,element.column,element.start,element.end,
      element.delimiter,element.rewoundCursor,element.returnedCursor,
      element.parseAhead.scratch[3],
    ]),
  },{
    renderType:0x2b, scanKind:6, metadata:[6,0x10,0xda,0xdb,0x9c],
    ...expected,
  });
}
expectThrows('34:568A rejects list braces as a matrix container', RangeError,
  () => rom.settledMatrixContainerScan(
    [0x08,0x08,0x31,0x09,0x09]));
expectThrows('34:568A rejects a ragged matrix value', RangeError,
  () => rom.settledMatrixContainerScan(
    [0x06,0x06,0x31,0x07,0x06,0x32,0x2b,0x33,0x07,0x07]));
expectThrows('34:568A rejects an empty matrix row', RangeError,
  () => rom.settledMatrixContainerScan([0x06,0x06,0x07,0x07]));
expectEqual('34:5BA7 bit-5 matrix mode resumes after a nested close',
  parseAheadAbi(rom.settledParseAhead(
    [0x06,0x06,0xbc,0x32,0x11,0x2b,0x33,0x07,0x07],{
      entry:'direct5AA7',b:0x20,cursor:1,
    })),{
    a:0,stopCursor:5,de:0,zero:false,carry:false,
    scratch:[0x60,0,0,0],
  });

for (const [label, bytes, stopCursor] of [
  ['nested comma in parentheses',[0x10,0x31,0x2b,0x32,0x11,0x2b,0x33],5],
  ['nested comma in braces',[0x08,0x31,0x2b,0x32,0x09,0x2b,0x33],5],
  ['single-byte token before comma',[0x31,0x2b,0x32],1],
  ['two-byte token before comma',[0x5d,0x00,0x2b,0x32],2],
]) expectEqual(`34:5AA3 ${label}`,
  rom.settledParseAhead(bytes,{
    entry:'internal5AA3',c:1,cursor:-1,
  }).stopCursor,stopCursor);
expectThrows('parse-ahead rejects a truncated two-byte token', RangeError,
  () => rom.settledParseAhead([0x5d],{
    entry:'internal5AA3',c:1,cursor:-1,
  }));

for (const [label, expression, nativeTokens] of [
  ['right-associated power','2^X^2',
    [0x32,0xf0,0x10,0x58,0xf0,0x32,0x11]],
  ['raised fraction boundaries','X^(1//2)',
    [0x58,0xf0,0x10,0x10,0x31,0xef,0x2e,0x32,0x11,0x11]],
  ['nested fraction denominator','1//(2//3)',
    [0x31,0xef,0x2e,0x10,0x32,0xef,0x2e,0x33,0x11]],
  ['integral storage order','int(1,2,X^2,X)',
    [0x24,0x58,0xf0,0x32,0x2b,0x58,0x2b,0x31,0x2b,0x32,0x11]],
  ['summation storage order','sum(N,1,3,N^2)',
    [0xef,0x33,0x4e,0xf0,0x32,0x2b,0x4e,0x2b,0x31,0x2b,0x33,0x11]],
  ['nDeriv storage order','nDeriv(X^2,X,1)',
    [0x25,0x58,0xf0,0x32,0x2b,0x58,0x2b,0x31,0x11]],
  ['logBASE storage order','logbase(12,345)',
    [0xef,0x34,0x33,0x34,0x35,0x2b,0x31,0x32,0x11]],
  ['matrix row-major square brackets','matrix(2,2,1,2,3,4)',
    [0x06,0x06,0x31,0x2b,0x32,0x07,
     0x06,0x33,0x2b,0x34,0x07,0x07]],
  ['named two-byte token','L1^2',[0x5d,0x00,0xf0,0x32]],
  ['named single-byte raised slot','X^Ans',[0x58,0xf0,0x10,0x72,0x11]],
  ['named two-byte raised slot','X^L1',[0x58,0xf0,0x10,0x5d,0x00,0x11]],
]) {
  const program = mp.constructedProgramForExpression(expression);
  if (!program) throw new Error(`${label} has no native-token browser program`);
  expectEqual(`${label} emits native calculator bytes`,
    program.native_tokens,nativeTokens);
  const reparsed = rom.constructSettledProgramFromTokens(nativeTokens,1,font);
  expectEqual(`${label} native scanner reproduces its settled graph`,
    reparsed.nodes,program.nodes);
}

for (const [label,nativeTokens,expectedEnd] of [
  ['Ans raised slot',[0x58,0xf0,0x10,0x72,0x11],5],
  ['L1 raised slot',[0x58,0xf0,0x10,0x5d,0x00,0x11],6],
]) {
  const scan = rom.settledRaisedOperandScan(nativeTokens,1);
  expectEqual(`34:5699 ${label} preserves the traced explicit boundary`,
    [scan.start,scan.end,scan.returnedCursor,scan.restoredCursor,scan.branch,
     scan.parseAhead.stopCursor],
    [2,expectedEnd,expectedEnd,2,'34:56BB–56D3',expectedEnd - 1]);
}

for (const [label, nativeTokens, expectedPayload, expectedWrites] of [
  ['single-byte multi-argument maximum',
    [0x19,0x31,0x2b,0xbc,0x58,0x11,0x11],
    [0x19,0x31,0x2b,0xef,0x27,0x02,0x00,0xef,0x2d,0x11], 104],
  ['single-byte inverse sine',
    [0xc3,0x58,0xf0,0x32,0x11],
    [0xc3,0x58,0xef,0x2a,0x02,0x00,0xef,0x2d,0x11], 81],
  ['BB multi-argument least common multiple',
    [0xbb,0x08,0x36,0x2b,0xbc,0x58,0x11,0x11],
    [0xbb,0x08,0x36,0x2b,0xef,0x27,0x02,0x00,0xef,0x2d,0x11], 104],
  ['EF multi-argument random integer without repetition',
    [0xef,0x35,0x31,0x2b,0x35,0x11],
    [0xef,0x35,0x31,0x2b,0x35,0x11], 168],
]) {
  const program = rom.constructSettledProgramFromTokens(nativeTokens,1,font);
  expectEqual(`${label} preserves the generic function and embedded child`,
    program.nodes[0].payload,expectedPayload);
  const generated = mp.generatedForNativeTokens(nativeTokens);
  expectEqual(`${label} emits a complete accepted LCD byte stream`,
    generated.events.length,expectedWrites);
  if (generated.operations.some(operation => operation.kind.startsWith('unresolved')) ||
      generated.events.some(event => event.pixels.length !== 8))
    throw new Error(`${label} has an unresolved or incomplete pixel-level path`);
  expectEqual(`${label} byte replay reaches its rasterized framebuffer`,
    rom.replaySettledLcdWrites(generated.events),
    generated.final.map(row => Array.from(row, pixel => Number(pixel))));
}

// These arbitrary inputs are deliberately absent from the captured graph/LCD
// fixtures. They pin the complete native-byte -> record graph -> accepted LCD
// byte stream -> 96x64 framebuffer path for changed values and deeper nesting.
// The hashes are deterministic regressions, not independent calculator oracles.
for (const [expression,nativeTokens,writeCount,writeHash,lcdHash] of [
  ['sum(N,12,34,N^3+2)',
    [0xef,0x33,0x4e,0xf0,0x33,0x70,0x32,0x2b,
     0x4e,0x2b,0x31,0x32,0x2b,0x33,0x34,0x11],
    104,'12efe48d6845f20c48f45fd0ff001bcf310ad5bc00729451a48a134504da16cc',
    'a97bdbb88c4f92848b33ee78290b89cc550463bf5c4a60df4d88b806250bf188'],
  ['int(12,34,(5//(6//7))X^3,X)',
    [0x24,0x10,0x35,0xef,0x2e,0x10,0x36,0xef,
     0x2e,0x37,0x11,0x11,0x58,0xf0,0x33,0x2b,
     0x58,0x2b,0x31,0x32,0x2b,0x33,0x34,0x11],
    172,'e6bbcd1876740b0ba7810415d2fcaeb88ce6f08ca8be74c9e8e5011c5a264435',
    '0ee1fe1ef5ee59b5a273003eae808efe344851d4f9f82315fae71b66c091e18d'],
  ['nDeriv((X^3+12)//sqrt(5),X,7)',
    [0x25,0x10,0x58,0xf0,0x33,0x70,0x31,0x32,
     0x11,0xef,0x2e,0x10,0xbc,0x35,0x11,0x11,
     0x2b,0x58,0x2b,0x37,0x11],
    173,'5003a3e479a9f50e30efe6e54efe844cbb2a34a04db768c2a10b5e5a73241f3d',
    'ccd9a4f098e3d8270e139528606ca85fe6ce37bed275aa834c3d369a8140fb82'],
  ['matrix(2,3,12,-34,0,5.6,-7,88)',
    [0x06,0x06,0x31,0x32,0x2b,0xb0,0x33,0x34,0x2b,0x30,0x07,
     0x06,0x35,0x3a,0x36,0x2b,0xb0,0x37,0x2b,0x38,0x38,0x07,0x07],
    183,'6ccac181d66c997c858dab657d5a8cdc0ea72dfd46d0ce4969ea52a5a08ab175',
    'e93a38668a7d0f6df53c56b6bf78c6a061f6062fe0991730e4098abc4634d2fa'],
  ['X^(1//(2//3))',
    [0x58,0xf0,0x10,0x10,0x31,0xef,0x2e,0x10,
     0x32,0xef,0x2e,0x33,0x11,0x11,0x11],
    36,'68e72bbf9297f85fb4daeb04a1b6f891434f8c570424982f742d2bad89344146',
    '0af8a5ff2cd2bc90699ee4cceccf6faea101e2dcdc5ff88cb4ab28d00526ca93'],
  ['int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)',
    [0x24,0x10,0x31,0xef,0x2e,0x32,0x11,0x58,0x2b,0x58,0x2b,0x31,0x2b,0x33,0x11,
     0x70,0x24,0x10,0x31,0xef,0x2e,0x32,0x11,0x58,0x2b,0x58,0x2b,0x31,0x2b,0x33,0x11],
    221,'1dd1291d71bd5d75580ee558655bb326fba504b8fd4e6de1957d91dacccf5094',
    'ac4035ffa5f44e6cc02c8c162216f7d410646d8ca470910f3adb01cef47ad377'],
]) {
  const browserProgram = mp.constructedProgramForExpression(expression);
  expectEqual(`${expression} changed-input frontend emits native bytes`,
    browserProgram.native_tokens,nativeTokens);
  const program = rom.constructSettledProgramFromTokens(nativeTokens,1,font);
  const operations = rom.executeSettledRecordProgram(
    program.nodes,program.entry_id,{
      origin:program.origin,glyphAdvance:settledGlyphAdvance,
    });
  if (operations.some(operation => operation.kind.startsWith('unresolved') ||
      operation.kind === 'glyph' && operation.code === 0xf7))
    throw new Error(`${expression} has an unresolved or empty pixel operation`);
  const rendered = rom.rasterizeSettledOperations(operations,font);
  expectEqual(`${expression} changed-input accepted LCD write count`,
    rendered.writes.length,writeCount);
  expectEqual(`${expression} changed-input accepted LCD write bytes`,
    crypto.createHash('sha256').update(Buffer.from(rendered.writes.flatMap(
      write => [...write.pointer,write.value]))).digest('hex'),writeHash);
  const replayed = rom.replaySettledLcdWrites(rendered.writes);
  expectEqual(`${expression} byte replay reaches the rasterized framebuffer`,
    replayed,rendered.grid);
  expectEqual(`${expression} changed-input packed 96x64 LCD`,
    crypto.createHash('sha256').update(packedLcdBytes(replayed)).digest('hex'),lcdHash);
  const browser = mp.generatedForExpression(expression);
  for (const step of [0,1,Math.floor(browser.events.length / 2),browser.events.length])
    expectEqual(`${expression} browser exposes pixel frame at write ${step}`,
      mp.traceFrame(browser,step),
      rom.replaySettledLcdWrites(browser.events,{
        width:browser.width,height:browser.height,count:step,
      }));
}

const overflowingIntegral =
  mp.generatedForExpression(editorOverflowOracle.expression);
// Exercise the same path used by the textarea, not only the direct generator:
// the wide model stays complete while the translated writer scrolls the 96 px
// LCD to the cursor. A second repeated integral checks that the clip keeps
// growing instead of truncating the input after the first structural object.
for (const [expression, expected] of [
  [
    'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)',
    {model:[103,23,106,10,17], generated:[96,64,106,10,198,17]},
  ],
  [
    'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)+' +
      'int(1,3,(1//2)X,X)',
    {model:[159,23,162,66,73], generated:[96,64,162,66,198,73]},
  ],
]) {
  const prepared = mp.prepareInput(expression);
  if (!prepared.model || !prepared.generated || prepared.generationError)
    throw new Error(`${expression} textarea preparation lost its generated/model path`);
  expectEqual(`${expression} textarea preserves the complete wide model`, [
    prepared.model.rows[0].length, prepared.model.rows.length,
    prepared.model.recordWidth, prepared.model.modelOverflowRight,
    prepared.model.modelViewport.xClip,
  ], expected.model);
  expectEqual(`${expression} textarea preserves the scrolled LCD writer`, [
    prepared.generated.width, prepared.generated.height,
    prepared.generated.recordWidth, prepared.generated.overflowRight,
    prepared.generated.events.length, prepared.generated.editorViewport.xClip,
  ], expected.generated);
  expectEqual(`${expression} textarea LCD replay remains pixel exact`,
    rom.replaySettledLcdWrites(prepared.generated.events, {
      width:prepared.generated.width, height:prepared.generated.height,
    }), prepared.generated.final.map(row => Array.from(row, Number)));
}
const retainedWideIntegral = mp.prepareInput(
  'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)',
  {previousXClip:73});
expectEqual('long integral edit retains a prior clip until the endpoint crosses it', {
  model:retainedWideIntegral.model.modelViewport.xClip,
  generated:retainedWideIntegral.generated.editorViewport.xClip,
  branch:retainedWideIntegral.generated.editorViewport.branch,
}, {model:73,generated:73,branch:'return-before-right-bound'});
const resetWideIntegral = mp.prepareInput(
  'int(1,3,(1//2)X,X)', {previousXClip:73});
expectEqual('shortened integral edit clears a clip beyond its endpoint', {
  model:resetWideIntegral.model.modelViewport.xClip,
  generated:resetWideIntegral.generated.editorViewport.xClip,
  reset:resetWideIntegral.generated.editorViewport.resetPreviousClip,
}, {model:0,generated:0,reset:true});
const eightIntegralText = new Array(8)
  .fill('int(1,3,(1//2)X,X)').join('+');
const eightIntegral = mp.prepareInput(eightIntegralText);
expectEqual('eight repeated integrals preserve the complete overflow model', {
  inputCharacters:eightIntegralText.length,
  nativeBytes:eightIntegral.generated.nativeTokens.length,
  modelWidth:eightIntegral.model.recordWidth,
  generatedWidth:eightIntegral.generated.recordWidth,
  xClip:eightIntegral.generated.editorViewport.xClip,
}, {inputCharacters:151,nativeBytes:127,modelWidth:442,generatedWidth:442,xClip:353});
expectEqual('eight repeated integrals retain a pixel-level LCD trace',
  rom.replaySettledLcdWrites(eightIntegral.generated.events, {
    width:eightIntegral.generated.width,
    height:eightIntegral.generated.height,
  }), eightIntegral.generated.final.map(row => Array.from(row, Number)));
expectEqual('long integral sum exposes its settled extent and editor scrolling', {
  lcd:[overflowingIntegral.width,overflowingIntegral.height],
  recordWidth:overflowingIntegral.recordWidth,
  overflowRight:overflowingIntegral.overflowRight,
  clippedInkPixels:overflowingIntegral.clippedInkPixels,
  xClip:overflowingIntegral.editorViewport.xClip,
  effectiveX:overflowingIntegral.editorViewport.effectiveX,
  cursorX:overflowingIntegral.editorViewport.cursorX,
  writes:overflowingIntegral.events.length,
  writeHash:crypto.createHash('sha256').update(Buffer.from(
    overflowingIntegral.events.flatMap(write => [...write.pointer,write.value])))
    .digest('hex'),
  lcdHash:crypto.createHash('sha256').update(Buffer.from(
    overflowingIntegral.final.flatMap(row => Array.from(row, Number))))
    .digest('hex'),
}, {
  lcd:[96,64], recordWidth:106, overflowRight:10, clippedInkPixels:20,
  xClip:editorOverflowOracle.viewport.ram_8e02_x_clip,
  effectiveX:editorOverflowOracle.viewport.effective_x,
  cursorX:editorOverflowOracle.viewport.cursor_x,
  writes:editorOverflowOracle.settled_editor_redraw
    .translated_expression_and_left_cue_write_count,
  writeHash:editorOverflowOracle.settled_editor_redraw
    .translated_expression_and_left_cue_write_sha256,
  lcdHash:editorOverflowOracle.settled_editor_redraw
    .translated_expression_and_left_cue_lcd_sha256,
});
const radicalViewportProgram = mp.constructedProgramForExpression(
  radicalViewportOracle.expression);
expectEqual('left-clipped radical input preserves calculator native tokens',
  radicalViewportProgram.native_tokens,radicalViewportOracle.native_tokens);
expectEqual('left-clipped radical decodes the calculator RAM graph',
  rom.decodeSettledExpressionGraph(
    radicalViewportOracle.nodes,radicalViewportOracle.wrapper_id),
  radicalViewportOracle.spec);
const radicalViewport = mp.generatedForExpression(radicalViewportOracle.expression);
expectEqual('left-clipped radical reproduces the editor viewport', {
  recordHeight:radicalViewportProgram.nodes[0].word05,
  recordWidth:radicalViewport.recordWidth,
  xClip:radicalViewport.editorViewport.xClip,
  effectiveX:radicalViewport.editorViewport.effectiveX,
  cursorX:radicalViewport.editorViewport.cursorX,
}, {
  recordHeight:radicalViewportOracle.record.word05_height,
  recordWidth:radicalViewportOracle.record.expression_endpoint,
  xClip:radicalViewportOracle.viewport.ram_8e02_x_clip,
  effectiveX:radicalViewportOracle.viewport.effective_x,
  cursorX:radicalViewportOracle.viewport.cursor_x,
});
expectEqual('34:6C69 reproduces the traced radical-hook skip',
  rom.settledGlyphViewportDecision(
    radicalViewportOracle.hook_gate.logical_pen,
    5,
    radicalViewportOracle.hook_gate.clip), {
    action:radicalViewportOracle.hook_gate.action,
    logicalPen:radicalViewportOracle.hook_gate.logical_pen,
    endpoint:null,
    rightExclusive:null,
    branchOutcomes:[
      `${radicalViewportOracle.hook_gate.comparison_address}:taken`,
    ],
  });
if (radicalViewport.operations.some(operation =>
  operation.kind === 'bitmap' && operation.recordType === 0x27 &&
  operation.routine.includes('34:630C')))
  throw new Error('34:6C69 retained a radical-hook bitmap left of the editor clip');
for (const routine of ['34:62AE → 34:5D96','34:62C3 → 34:5DA6'])
  if (!radicalViewport.operations.some(operation => operation.routine === routine))
    throw new Error(`left-clipped radical lost ${routine}`);
const radicalViewportCrop = cropInk(radicalViewport.final);
expectEqual('left-clipped radical reproduces the calculator entry crop', {
  dimensions:[radicalViewportCrop[0].length,radicalViewportCrop.length],
  sha256:crypto.createHash('sha256').update(
    Buffer.from(radicalViewportCrop.flat())).digest('hex'),
}, {
  dimensions:[radicalViewportOracle.entry_crop.width,
    radicalViewportOracle.entry_crop.height],
  sha256:radicalViewportOracle.entry_crop.sha256,
});
expectEqual('left-clipped radical retains the translated LCD write stream', {
  operations:radicalViewport.operations.length,
  writes:radicalViewport.events.length,
  writeSha256:crypto.createHash('sha256').update(Buffer.from(
    radicalViewport.events.flatMap(write => [...write.pointer,write.value])))
    .digest('hex'),
  lcdSha256:crypto.createHash('sha256').update(Buffer.from(
    radicalViewport.final.flatMap(row => Array.from(row,Number))))
    .digest('hex'),
}, {
  operations:radicalViewportOracle.translated.operation_count,
  writes:radicalViewportOracle.translated.accepted_write_count,
  writeSha256:radicalViewportOracle.translated.accepted_write_sha256,
  lcdSha256:radicalViewportOracle.translated.final_lcd_sha256,
});
const spacedLongIntegral = mp.constructedProgramForExpression(
  ' int(1, 3, (1 // 2) X, X) + int(1, 3, (1 // 2) X, X) ');
expectEqual('long integral whitespace still selects native construction',
  spacedLongIntegral.native_tokens,
  mp.constructedProgramForExpression(
    'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)').native_tokens);
expectEqual('long integral whitespace still generates the clipped LCD path', {
  recordWidth:mp.generatedForExpression(
    ' int(1, 3, (1 // 2) X, X) + int(1, 3, (1 // 2) X, X) ').recordWidth,
  xClip:mp.generatedForExpression(
    ' int(1, 3, (1 // 2) X, X) + int(1, 3, (1 // 2) X, X) ').editorViewport.xClip,
}, {recordWidth:106, xClip:17});
for (const name of ['integral', 'fnInt']) {
  const alias = `${name}(1,3,(1//2)X,X)+${name}(1,3,(1//2)X,X)`;
  const generated = mp.generatedForExpression(alias);
  expectEqual(`${name} alias selects the same native integral path`, {
    native:mp.constructedProgramForExpression(alias).native_tokens,
    recordWidth:generated.recordWidth,
    xClip:generated.editorViewport.xClip,
  }, {
    native:mp.constructedProgramForExpression(
      'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)').native_tokens,
    recordWidth:106, xClip:17,
  });
}
for (const [name, token] of [['sinh',0xc8], ['cosh',0xca], ['tanh',0xcc]]) {
  const expression = `${name}(sqrt(X^2+1))+${name}(Ans)`;
  const program = mp.constructedProgramForExpression(expression);
  const generated = mp.generatedForExpression(expression);
  if (!program || !generated)
    throw new Error(`${name} has no translated generated program`);
  const rawNative = mp.generatedForInput(
    `hex: ${program.native_tokens.map(byte =>
      byte.toString(16).padStart(2, '0')).join(' ')}`);
  expectEqual(`${name} selects its native one-argument token`,
    program.native_tokens.slice(0, 1), [token]);
  expectEqual(`${name} text and raw-native paths share the LCD write stream`, {
    events:generated.events.map(event => [event.pointer,event.value]),
    final:generated.final,
  }, {
    events:rawNative.events.map(event => [event.pointer,event.value]),
    final:rawNative.final,
  });
  if (!rawNative || generated.operations.some(operation =>
      operation.kind.startsWith('unresolved')) ||
      generated.events.some(event => event.pixels.length !== 8))
    throw new Error(`${name} generated path has unresolved or partial LCD writes`);
}

// Model mode keeps the complete composition on the canvas while the editable
// LCD path scrolls to the cursor. Check both views on the long expressions so
// a wide model cannot be mistaken for a 96-pixel LCD frame. The model's
// heuristic extent may differ from the settled record metric for mixed
// structural forms; its overflow metadata must still use the same endpoint
// and clip arithmetic.
for (const [expression, modelWidth, modelHeight, modelEndpoint,
             modelOverflow, modelClip] of [
  ['int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)', 103, 23, 106, 10, 17],
  ['int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)+' +
    'int(1,3,(1//2)X,X)', 159, 23, 162, 66, 73],
  ['int(12,34,(5//(6//7))X^3,X)+sum(N,1,99,N^2)+' +
    'nDeriv((X^3+12)//sqrt(5),X,7)', 167, 31, 168, 72, 79],
  ['int(123,456,(1//(2//(3//4)))X^5,X)+' +
    'int(789,999,(7//8)X,X)', 131, 39, 134, 38, 45],
]) {
  const model = mp.parse(expression);
  expectEqual(`${expression} model preserves its complete extent`, {
    width:model.rows[0].length,
    height:model.rows.length,
    recordWidth:model.recordWidth,
    overflowRight:model.modelOverflowRight,
    xClip:model.modelViewport.xClip,
    effectiveX:model.modelViewport.effectiveX,
  }, {
    width:modelWidth, height:modelHeight, recordWidth:modelEndpoint,
    overflowRight:modelOverflow, xClip:modelClip,
    effectiveX:-modelClip,
  });
}

// Closed model boxes must agree with a direct, unscrolled replay of the same
// settled graph. This catches heuristic spacing regressions in multi-glyph
// fractions, nested fractions, big operators, and structural power bases.
function settledModelBitmap(expression) {
  const program = mp.constructedProgramForExpression(expression);
  const entry = program.nodes.find(node => node.record_id === program.entry_id);
  const operations = rom.executeSettledRecordProgram(
    program.nodes, program.entry_id, {
      glyphAdvance:(depth, code) => depth ? font.small.glyphs[code].w : 6,
    });
  const pixels = operations.flatMap(operation =>
    rom.settledOperationPixels(operation, font));
  const width = Math.max(entry.word07,
    Math.max(...pixels.map(([x]) => x)) + 1);
  const height = Math.max(entry.word05,
    Math.max(...pixels.map(([,y]) => y)) + 1);
  const rendered = rom.rasterizeSettledOperations(operations, font, {
    width:Math.ceil(width / 8) * 8, height,
  });
  const ink = [];
  for (let y = 0; y < rendered.grid.length; y++)
    for (let x = 0; x < rendered.grid[y].length; x++)
      if (rendered.grid[y][x]) ink.push([x,y]);
  const left = Math.min(...ink.map(([x]) => x));
  const top = Math.min(...ink.map(([,y]) => y));
  const right = Math.max(...ink.map(([x]) => x));
  const bottom = Math.max(...ink.map(([,y]) => y));
  return rendered.grid.slice(top, bottom + 1)
    .map(row => row.slice(left, right + 1));
}
for (const expression of [
  '12//34', '(1+2)//(3+4)', '(X+1)//(2*3)', '1//(2//3)',
  'sum(N,1,3,N^2)', '(int(1,2,X,X))^2',
]) {
  expectEqual(`${expression} model bitmap follows translated settled geometry`,
    mp.parse(expression).rows, settledModelBitmap(expression));
}
const wordOverflowModel = mp.parse('X'.repeat(11000));
expectEqual('model remains usable beyond the translated word-width domain', {
  width:wordOverflowModel.rows[0].length,
  recordWidth:wordOverflowModel.recordWidth,
  overflowRight:wordOverflowModel.modelOverflowRight,
  viewport:wordOverflowModel.modelViewport,
}, {width:65999, recordWidth:66000, overflowRight:65904, viewport:null});

// A wide settled graph can contain enough LCD pixels to exceed V8's spread
// argument limit.  Keep this just beyond that limit so the model path proves it
// can still derive a complete extent rather than throwing while reducing the
// pixel list.  The expression remains under the 16-bit record metric, so this
// exercises the translated settled model itself (not only the lenient fallback).
const spreadLimitModel = mp.parse(
  new Array(900).fill('int(1,3,(1//2)X,X)').join('+'));
if (!spreadLimitModel || !Array.isArray(spreadLimitModel.rows) ||
    !spreadLimitModel.rows.length || !spreadLimitModel.rows.some(row => row.some(Boolean)) ||
    spreadLimitModel.rows[0].length <= 96 ||
    !Number.isInteger(spreadLimitModel.recordWidth) ||
    !Number.isInteger(spreadLimitModel.modelOverflowRight) ||
    !spreadLimitModel.modelViewport)
  throw new Error('long settled model did not survive pixel extent reduction');
expectEqual('long settled model keeps overflow metadata coherent', {
  recordWidth:spreadLimitModel.recordWidth,
  overflowRight:spreadLimitModel.modelOverflowRight,
  xClip:spreadLimitModel.modelViewport.xClip,
}, {
  recordWidth:50394, overflowRight:50298, xClip:50305,
});

// A structural expression can exceed the settled record's unsigned-word
// metric even though the editable model can still lay out every pixel. The
// input-preparation path must retain that model instead of blanking the
// preview when the translated constructor rejects the record.
const overWordIntegral = `int(1,3,${new Array(5462).fill('X').join('+')},X)`;
const preparedOverWordIntegral = mp.prepareInput(overWordIntegral);
if (!preparedOverWordIntegral.model || preparedOverWordIntegral.generated !== null ||
    !preparedOverWordIntegral.generationError)
  throw new Error('over-word integral did not retain its model fallback');
expectEqual('over-word integral model exposes full extent without a word viewport', {
  width:preparedOverWordIntegral.model.rows[0].length,
  height:preparedOverWordIntegral.model.rows.length,
  overflowRight:preparedOverWordIntegral.model.modelOverflowRight,
  viewport:preparedOverWordIntegral.model.modelViewport,
  error:preparedOverWordIntegral.generationError.constructor.name,
}, {width:65571, height:17, overflowRight:65475, viewport:null,
  error:'RangeError'});

// Wide-input corpus: keep the text compositor, native-token frontend, record
// constructor, editor viewport, and byte-level writer on the same overflow
// cases. These inputs are deliberately absent from the captured fixtures.
for (const [expression, expectedOverflow] of [
  [
    'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)',
    66,
  ],
  [
    'int(12,34,(5//(6//7))X^3,X)+sum(N,1,99,N^2)+' +
      'nDeriv((X^3+12)//sqrt(5),X,7)',
    72,
  ],
  [
    'int(123,456,(1//(2//(3//4)))X^5,X)+' +
      'int(789,999,(7//8)X,X)',
    38,
  ],
]) {
  const model = mp.parse(expression);
  if (!model || !Array.isArray(model.rows) || !model.rows.length ||
      !model.rows.some(row => row.some(Boolean)))
    throw new Error(`${expression} text model produced no visible pixels`);
  const program = mp.constructedProgramForExpression(expression);
  if (!program) throw new Error(`${expression} has no settled record program`);
  const generated = mp.generatedForExpression(expression);
  expectEqual(`${expression} record width agrees with the editor model`,
    generated.recordWidth, program.nodes[0].word07);
  expectEqual(`${expression} editor clip follows the endpoint`,
    generated.editorViewport.xClip,
    Math.max(0, generated.recordWidth + generated.editorViewport.cursorWidth -
      generated.editorViewport.rightBound));
  expectEqual(`${expression} records its expected visible overflow`,
    generated.overflowRight, expectedOverflow);
  if (generated.operations.some(operation =>
      operation.kind.startsWith('unresolved')) ||
      generated.events.some(event => event.pixels.length !== 8))
    throw new Error(`${expression} wide-input path emitted unresolved or partial pixels`);
  expectEqual(`${expression} wide-input byte replay reaches the final frame`,
    rom.replaySettledLcdWrites(generated.events, {
      width:generated.width, height:generated.height,
    }), generated.final.map(row => Array.from(row, Number)));
  for (const step of [0, 1, Math.floor(generated.events.length / 2), generated.events.length])
    expectEqual(`${expression} wide-input frame ${step}`,
      mp.traceFrame(generated, step),
      rom.replaySettledLcdWrites(generated.events, {
        width:generated.width, height:generated.height, count:step,
      }));
}

// Fractions can occupy a raised base slot without a second parenthesis pair.
// Keep these cases in the native-token corpus because that boundary is easy to
// miss when a denominator contains another structural record. The same cases
// also exercise long records and the editor's right-edge clip.
for (const [expression, expectedWidth, expectedOverflow] of [
  ['(X^2//int(0.5,Y1,12,X))^1', 54, 0],
  ['(X^2//sqrt(N))^1', 17, 0],
  ['(abs(Ans)//abs(Ans))^1', 31, 0],
  ['(1//2)^int(1,2,X,X)', 44, 0],
  ['(int(L1,Y1,L1,X)//sqrt(N))^int(12,X,(Ans),X)', 105, 9],
  ['(sum(N,1,1,Y1)//int(N,2,2,X))^A', 44, 0],
  ['1+Ans//int(2,Ans,Y1,X)^sum(N,A,2,Y1^Ans)^(2//1)^sqrt(Y1)+X//0.5',
    143, 47],
  ['int(N,X,1,X)+abs(X)^(2//2)^sqrt(X)//int(N,Y1,2,X)//sqrt(X)',
    95, 0],
  ['nthroot(12,nDeriv(sum(N,Ans,456,Ans),X,1))^' +
    'int(L1,Ans,nthroot(X,12^Ans),X)//N', 160, 64],
  ['nthroot(X,int(456,A,abs(0.5),X))^2', 86, 0],
  ['nDeriv((123+nthroot(456,A)^nthroot(A,logbase(12,Y1))),X,123)',
    149, 53],
  ['nthroot(N,logbase(123,A)//123^Ans)^Y1*abs(123)', 94, 0],
  ['matrix(1,1,(sum(N,12,GDB3,2))//2)', 47, 0],
  ['matrix(2,1,Pic2*[A]//12,abs((Y9)))', 48, 0],
  ['exp(remainder(matrix(2,3,sqrt(0.5),int(X,A,Str1,X),N//123,' +
    'sum(N,123,0.5,L6),Ans,exp(X)),sin(Str1)))', 219, 123],
  ['matrix(1,2,nthroot(2,N^X)//sum(N,[A],Y1,1)//remainder(Ans,GDB3),' +
    'sin(L1+N)//sqrt(Ans)*ln(X))', 149, 53],
]) {
  const program = mp.constructedProgramForExpression(expression);
  if (!program) throw new Error(`${expression} has no settled record program`);
  const reconstructed = rom.constructSettledProgramFromTokens(
    program.native_tokens, 1, font);
  expectEqual(`${expression} native-token graph round-trip`,
    reconstructed.nodes, program.nodes);
  const generated = mp.generatedForExpression(expression);
  expectEqual(`${expression} settled record width`, generated.recordWidth,
    expectedWidth);
  expectEqual(`${expression} editor overflow`, generated.overflowRight,
    expectedOverflow);
  if (generated.operations.some(operation =>
      operation.kind.startsWith('unresolved')) ||
      generated.events.some(event => event.pixels.length !== 8))
    throw new Error(`${expression} emitted unresolved or partial LCD pixels`);
  expectEqual(`${expression} pixel replay reaches the final frame`,
    rom.replaySettledLcdWrites(generated.events, {
      width:generated.width, height:generated.height,
    }), generated.final.map(row => Array.from(row, Number)));
}

// Child geometry fields and the page-34 coordinate arithmetic are 16-bit.
// This radical crosses the former 255-pixel JavaScript guard while remaining
// a valid record and clips its vinculum into the live editor viewport.
const oversizedRadical =
  'sqrt(logbase(Ans,nDeriv(L1,X,1))+' +
  'logbase(456,logbase(L1,N))*(int(2,X,Ans,X)))';
const oversizedRadicalGenerated = mp.generatedForExpression(oversizedRadical);
expectEqual('ROM retains a word-sized radical width',
  oversizedRadicalGenerated.recordWidth, 258);
expectEqual('word-sized radical vinculum clips to the editor viewport',
  oversizedRadicalGenerated.operations.find(operation =>
    operation.routine === '34:62C3 → 34:5DA6'), {
    kind:'line',axis:'horizontal',from:{x:-167,y:0},to:{x:87,y:0},
    routine:'34:62C3 → 34:5DA6',recordId:2,recordType:0x27,depth:0,
  });
expectEqual('34:62BA–62C3 wraps a radical vinculum as a Z80 word',
  rom.settledRadicalOperations(7,0xffff)[3].to.x, 2);

// The record metric fields are unsigned words. The largest flat expression
// that fits remains executable; adding one six-pixel cell must fail at the
// same constructor boundary instead of wrapping its width.
const maxWidthText = new Array(5461).fill('X').join('+');
const maxWidthProgram = mp.constructedProgramForExpression(maxWidthText);
expectEqual('frontend accepts a maximum-width settled leaf',
  maxWidthProgram.nodes[0].word07, 0xfff6);
const overWidthText = new Array(5462).fill('X').join('+');
expectThrows('frontend rejects a settled leaf wider than a word', RangeError,
  () => mp.constructedProgramForExpression(overWidthText));
const overWidthPrepared = mp.prepareInput(overWidthText);
expectEqual('model fallback preserves an expression beyond record-word capacity', {
  characters:overWidthText.length,
  modelPixels:[
    overWidthPrepared.model.rows[0].length,
    overWidthPrepared.model.rows.length,
  ],
  recordWidth:overWidthPrepared.model.recordWidth,
  modelOverflowRight:overWidthPrepared.model.modelOverflowRight,
  modelViewport:overWidthPrepared.model.modelViewport,
  generated:overWidthPrepared.generated,
  generationError:String(overWidthPrepared.generationError),
}, {
  characters:10923, modelPixels:[65537,7], recordWidth:65538,
  modelOverflowRight:65442, modelViewport:null, generated:null,
  generationError:'RangeError: settled leaf width must fit an unsigned word',
});

expectThrows('LCD replay rejects an out-of-bounds byte pointer', RangeError,
  () => rom.replaySettledLcdWrites([{pointer:[12,0],value:0xff}]));
expectThrows('LCD replay rejects a non-byte data value', RangeError,
  () => rom.replaySettledLcdWrites([{pointer:[0,0],value:0x100}]));

const pixelByteTrace = rom.traceSettledLcdWrites([
  {pointer:[1,2],value:0xa5},
  {pointer:[1,2],value:0xa5},
  {pointer:[1,2],value:0x24},
]);
expectEqual('pixel LCD trace retains every bit of each accepted byte',
  pixelByteTrace.events.map(event => ({
    before:event.beforeValue,
    after:event.value,
    pixels:event.pixels.map(pixel => [pixel.x,pixel.y,pixel.before,pixel.value,pixel.changed]),
  })), [
    {before:0x00,after:0xa5,pixels:[
      [8,2,0,1,true],[9,2,0,0,false],[10,2,0,1,true],[11,2,0,0,false],
      [12,2,0,0,false],[13,2,0,1,true],[14,2,0,0,false],[15,2,0,1,true],
    ]},
    {before:0xa5,after:0xa5,pixels:[
      [8,2,1,1,false],[9,2,0,0,false],[10,2,1,1,false],[11,2,0,0,false],
      [12,2,0,0,false],[13,2,1,1,false],[14,2,0,0,false],[15,2,1,1,false],
    ]},
    {before:0xa5,after:0x24,pixels:[
      [8,2,1,0,true],[9,2,0,0,false],[10,2,1,1,false],[11,2,0,0,false],
      [12,2,0,0,false],[13,2,1,1,false],[14,2,0,0,false],[15,2,1,0,true],
    ]},
  ]);
expectEqual('pixel LCD trace final grid matches ordinary byte replay',
  pixelByteTrace.grid, rom.replaySettledLcdWrites([
    {pointer:[1,2],value:0xa5},
    {pointer:[1,2],value:0xa5},
    {pointer:[1,2],value:0x24},
  ]));

for (const [bytes, expected] of [
  [[0x5c,0x00], {codes:[0xc1,0x41,0x5d],length:2,table:'5C',tableIndex:0}],
  [[0x5d,0x00], {codes:[0x4c,0x81],length:2,table:'5D',tableIndex:0}],
  [[0x5e,0x10], {codes:[0x59,0x81],length:2,table:'5E10',tableIndex:0}],
  [[0xaa,0x00], {codes:[0x53,0x74,0x72,0x31],length:2,table:'AA',tableIndex:0}],
  [[0xbb,0xff], {codes:[0x73,0x65,0x74,0x44,0x61,0x74,0x65,0x28],
                 length:2,table:'BB',tableIndex:0xf6}],
]) expectEqual(`01:6702 resolves ${bytes.map(value => value.toString(16)).join(' ')}`,
  rom.settledTokenSpelling(bytes,0), expected);
expectEqual('01:6702 rejects a truncated two-byte token',
  rom.settledTokenSpelling([0x5d],0), null);
expectEqual('01:6702 keeps bytes beyond the EF pointer array unresolved',
  rom.settledTokenSpelling([0xef,0x41],0), null);

for (const [expression, payload, glyphs] of [
  ['L1',[0x5d,0x00],[0x4c,0x81]],
  ['Y1',[0x5e,0x10],[0x59,0x81]],
  ['Str1',[0xaa,0x00],[0x53,0x74,0x72,0x31]],
  ['[A]',[0x5c,0x00],[0xc1,0x41,0x5d]],
  ['cumSum(L1)',[0xbb,0x29,0x5d,0x00,0x11],
    [0x63,0x75,0x6d,0x53,0x75,0x6d,0x4c,0x81]],
  ['remainder(Ans,2)',[0xef,0x32,0x72,0x2b,0x32,0x11],
    [0x72,0x65,0x6d,0x61,0x69,0x6e,0x64,0x65,0x72,
     0x41,0x6e,0x73,0x2c,0x32]],
]) {
  const program = mp.constructedProgramForExpression(expression);
  if (!program) throw new Error(`${expression} has no extended-token record program`);
  expectEqual(`${expression} preserves its native token bytes`,program.nodes[0].payload,payload);
  const operations = rom.executeSettledRecordProgram(program.nodes,program.entry_id,{
    origin:program.origin,glyphAdvance:settledGlyphAdvance,
  });
  expectEqual(`${expression} resolves every counted spelling glyph`,
    operations.filter(operation => operation.kind === 'glyph')
      .map(operation => operation.code),glyphs);
  if (operations.some(operation => operation.kind.startsWith('unresolved')))
    throw new Error(`${expression} has an unresolved pixel-level operation`);
  const rendered = rom.rasterizeSettledOperations(operations,font);
  if (!rendered.writes.length)
    throw new Error(`${expression} has no generated LCD data-write timeline`);
  const replayed = Array.from({length:rendered.height}, () =>
    new Array(rendered.width).fill(0));
  for (const write of rendered.writes)
    for (const [x,y,value] of write.changes) replayed[y][x] = value;
  expectEqual(`${expression} LCD timeline reaches its final pixel grid`,
    replayed,rendered.grid);
}

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
expectEqual('34:5935 maps EF36h to the exceptional type 2Ch path',
  rom.settledStructuralTokenType(0xef,0x36), 0x2c);
const ef36Path = rom.settledEf36SourcePath(0);
expectEqual('EF36h inserts and patches the traced embedded-record marker',
  [ef36Path.status,ef36Path.returnA,ef36Path.carry,
   ef36Path.insertion.placeholderBytes,ef36Path.insertion.patchedBytes], [
    'reset',0x2c,false,
    [0xef,0x2c,0x00,0x00,0xef,0x2d],
    [0xef,0x2c,0x08,0x00,0xef,0x2d],
  ]);
expectEqual('EF36h allocator reads the bytes after the legitimate table',
  [ef36Path.allocation.tableBase,ef36Path.allocation.tableAddress,
   ef36Path.allocation.byteE,ef36Path.allocation.childCount,
   ef36Path.allocation.recordSize],
  [0x4f82,0x4fa9,0x42,0x0002,0x0018]);
expectEqual('EF36h allocator constructs the observed first-context header',
  ef36Path.allocation.recordHeader, [
    0x08,0x00,0x2c,0x07,0x00,0x01,0x00,0x06,0x00,0x03,
    0x00,0x00,0x00,0x00,0x00,0x06,0x00,0x01,0x00,0xef,
  ]);
expectEqual('EF36h patches arbitrary unsigned record IDs little-endian',
  rom.settledEf36SourcePath(3,{parentId:0x1234,recordId:0xabcd}), {
    ...rom.settledEf36SourcePath(3),
    insertion:{...rom.settledEf36SourcePath(3).insertion,
      patchedBytes:[0xef,0x2c,0xcd,0xab,0xef,0x2d]},
    allocation:{...rom.settledEf36SourcePath(3).allocation,
      recordHeader:[
        0xcd,0xab,0x2c,0x34,0x12,0x01,0x00,0x06,0x00,0x03,
        0x00,0x00,0x00,0x00,0x00,0x06,0x00,0x01,0x00,0xef,
      ]},
  });
expectEqual('EF36h geometry dispatch reads code bytes after the table',
  [ef36Path.terminal.geometryTableBase,
   ef36Path.terminal.geometryTableAddress,
   ef36Path.terminal.geometryWord],
  [0x7611,0x762b,0x3bcd]);
expectEqual('35:7B37 applies its byte-exact structural-depth gate',
  [0,1,2,3,4,5,0xfe,0xff].map(depth => {
    const gate = rom.settledStructuralDepthGate(depth,0x2a);
    return [depth,gate.incrementedDepth,gate.status,gate.returnA,gate.carry];
  }), [
    [0,1,'accept',0x2a,false],[1,2,'accept',0x2a,false],
    [2,3,'accept',0x2a,false],[3,4,'accept',0x2a,false],
    [4,5,'depth-limit',0x03,true],[5,6,'depth-limit',0x03,true],
    [0xfe,0xff,'depth-limit',0x03,true],[0xff,0,'accept',0x2a,false],
  ]);
expectEqual('EF36h routes through the shared structural-depth gate',
  [0,1,2,3,4,5,0xfe,0xff].map(depth => {
    const path = rom.settledEf36SourcePath(depth);
    return [depth,path.incrementedDepth,path.status,path.returnA,path.carry];
  }), [
    [0,1,'reset',0x2c,false],[1,2,'reset',0x2c,false],
    [2,3,'reset',0x2c,false],[3,4,'reset',0x2c,false],
    [4,5,'depth-limit',0x03,true],[5,6,'depth-limit',0x03,true],
    [0xfe,0xff,'depth-limit',0x03,true],[0xff,0,'reset',0x2c,false],
  ]);
expectEqual('34:54D2 records the EF36h depth-limit state',
  rom.settledEf36SourcePath(4).error,
  {flags45Bit6:true,address:0x9d20,value:0x05});
expectThrows('EF36h bypasses the ordinary 34:59AC argument scanner', RangeError,
  () => rom.settledStructuralArgumentScan([0xef,0x36,0x31,0x11]));
expectThrows('type 2Ch has no legitimate 34:59AC metadata row', RangeError,
  () => rom.settledRecordMetadata(0x2c));
expectThrows('type 2Ch has no legitimate 34:6119 render handler', RangeError,
  () => rom.settledRenderHandler(0x2c));
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
const raisedExponentialNDeriv = rom.constructSettledExpressionProgram({
  kind:'nDeriv',
  variable:[0x58],
  body:{kind:'logBase',base:[0x31],argument:[0x32]},
  value:{kind:'ePower',exponent:[0x32]},
},1,font);
const raisedExponentialById = new Map(
  raisedExponentialNDeriv.nodes.map(node => [node.record_id,node]));
const raisedExponentialRoot = raisedExponentialNDeriv.nodes.find(
  node => node.render_type === 0x23);
const raisedExponentialValue = raisedExponentialById.get(
  raisedExponentialRoot.child_ids[2]);
const raisedExponentialRecord = raisedExponentialNDeriv.nodes.find(
  node => node.render_type === 0x25);
expectEqual(
  '34:73DB retains the six-row seed for a raised exponential value', {
    root:[raisedExponentialRoot.word07,raisedExponentialRoot.word09,
      raisedExponentialRoot.word0B],
    value:[raisedExponentialValue.word05,raisedExponentialValue.word09,
      raisedExponentialValue.word0D],
    exponential:[raisedExponentialRecord.word07,raisedExponentialRecord.word09,
      raisedExponentialRecord.word0B],
  }, {
    // Reset-origin trace SHA-256
    // 772b3db49ce913dcf1ccbe457da4bf3b4f34d537fc2f0dbca98d723775e071d1.
    root:[13,83,6], value:[9,6,4], exponential:[9,10,6],
  });
const raisedExponentialGlyph = rom.executeSettledRecordProgram(
  raisedExponentialNDeriv.nodes,raisedExponentialNDeriv.entry_id,{
    origin:raisedExponentialNDeriv.origin,
    glyphAdvance:settledGlyphAdvance,
  }).find(operation => operation.recordType === 0x25 &&
    operation.kind === 'glyph' && operation.code === 0xdb);
expectEqual('34:637E keeps the nested exponential marker in the large font', {
  x:raisedExponentialGlyph.x,
  y:raisedExponentialGlyph.y,
  depth:raisedExponentialGlyph.depth,
}, {x:73,y:6,depth:0});
const deepViewportSpec = {
  kind:'logBase',
  base:{kind:'power',
    base:{kind:'group',expression:{kind:'power',
      base:{kind:'group',expression:[0x32,0x71,0x4e]},
      exponent:{kind:'power',base:[0x32],exponent:[0x33]}}},
    exponent:{kind:'power',
      base:{kind:'group',expression:[0x41,0x82,0x31]},
      exponent:{kind:'group',expression:[0x58,0x82,0x41]}}},
  argument:{kind:'absolute',body:{kind:'fraction',
    numerator:{kind:'ePower',exponent:[0x41]},
    denominator:{kind:'fraction',numerator:[0x58],denominator:[0x41]}}},
};
const deepViewportProgram = rom.constructSettledExpressionProgram(
  deepViewportSpec,1,font);
const deepViewportRoot = deepViewportProgram.nodes.find(
  node => node.record_id === deepViewportProgram.entry_id);
const deepViewport = rom.settledEditorViewport(deepViewportRoot.word07);
const deepViewportOptions = {
  origin:deepViewportProgram.origin,
  glyphAdvance:settledGlyphAdvance,
};
const deepUngatedOperations = rom.executeSettledRecordProgram(
  deepViewportProgram.nodes,deepViewportProgram.entry_id,deepViewportOptions);
const deepGatedOperations = rom.executeSettledRecordProgram(
  deepViewportProgram.nodes,deepViewportProgram.entry_id,{
    ...deepViewportOptions,editorViewport:deepViewport,
  });
const deepGatedRecordIds = new Set(
  deepGatedOperations.map(operation => operation.recordId));
expectEqual('34:6659 skips the complete off-left nested power renderer', {
  root:[deepViewportRoot.word05,deepViewportRoot.word07,deepViewportRoot.word09],
  xClip:deepViewport.xClip,
  operationCounts:[deepUngatedOperations.length,deepGatedOperations.length],
  removedRecordIds:[...new Set(deepUngatedOperations
    .filter(operation => !deepGatedRecordIds.has(operation.recordId))
    .map(operation => operation.recordId))],
}, {
  root:[28,152,10],xClip:63,operationCounts:[58,56],removedRecordIds:[6,8],
});
const deepViewportGenerated = mp.generateRecordProgram(
  deepViewportProgram,{editor:true});
const deepViewportBitmap = cropInk(deepViewportGenerated.final);
expectEqual('depth-four viewport trace retains exact final pixel parity', {
  dimensions:[deepViewportBitmap[0].length,deepViewportBitmap.length],
  eventCount:deepViewportGenerated.events.length,
  sha256:crypto.createHash('sha256').update(
    Buffer.from(deepViewportBitmap.flat())).digest('hex'),
}, {
  // Reset-origin trace SHA-256
  // b8d970906e63db96d36847dfcafed91d97e73fc7699294cc8debd08e7affdd93.
  dimensions:[87,25],eventCount:220,
  sha256:'b4a60c6f5b1bc78d5a59f6b6fb0f379c999e70dc09c409131677142c0c2b1b09',
});
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
for (const listCase of listOracles.cases) {
  expectEqual(`${listCase.expression} encodes native list delimiters`,
    rom.encodeSettledExpressionTokens(listCase.spec), listCase.native_tokens);
  const program = rom.constructSettledProgramFromTokens(
    listCase.native_tokens, 1, font);
  expectEqual(`${listCase.expression} decodes semantic list elements`,
    rom.decodeSettledExpressionGraph(program.nodes,program.entry_id),
    listCase.spec);
  const operations = rom.executeSettledRecordProgram(
    program.nodes,program.entry_id,{glyphAdvance:settledGlyphAdvance});
  const crop = cropInk(rom.rasterizeSettledOperations(operations,font).grid);
  expectEqual(`${listCase.expression} reproduces captured list dimensions`,
    [crop[0].length,crop.length],
    [listCase.cropped_bitmap.width,listCase.cropped_bitmap.height]);
  expectEqual(`${listCase.expression} reproduces captured list pixels`,
    crypto.createHash('sha256').update(Buffer.from(crop.flat())).digest('hex'),
    listCase.cropped_bitmap.sha256);
  const browser = mp.constructedProgramForExpression(listCase.expression);
  if (!browser)
    throw new Error(`${listCase.expression} has no browser-constructed program`);
  expectEqual(`${listCase.expression} browser grammar preserves list bytes`,
    browser.native_tokens,listCase.native_tokens);
}
expectEqual('nested list payload retains semantic element boundaries',
  rom.decodeSettledExpressionGraph(
    rom.constructSettledProgramFromTokens(
      [0x08,0x31,0x2b,0x08,0x32,0x2b,0x33,0x09,0x09],1,font).nodes,1),
  {kind:'list',elements:[[0x31],{kind:'list',elements:[[0x32],[0x33]]}]});
for (const oracle of structuralBaseOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} independently constructs the structural-base graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(program.nodes, program.entry_id, {
    origin:program.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const writes = rom.rasterizeSettledOperations(operations, font).writes;
  expectEqual(`${oracle.expression} reproduces accepted structural-base write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} reproduces accepted structural-base write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
  const browser = mp.constructedProgramForExpression(oracle.expression);
  if (!browser)
    throw new Error(`${oracle.expression} has no browser-constructed record program`);
  const expectedBrowser = rom.constructSettledExpressionProgram(oracle.spec, 1, font);
  expectEqual(`${oracle.expression} browser grammar preserves the structural-base AST`,
    browser.nodes, expectedBrowser.nodes);
}
for (const oracle of namedTokenOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} independently constructs the named-token graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(
    program.nodes, program.entry_id, {
      origin:program.origin, glyphAdvance:settledGlyphAdvance,
    });
  const rendered = rom.rasterizeSettledOperations(operations, font);
  const writes = rendered.writes;
  expectEqual(`${oracle.expression} reproduces accepted named-token write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} reproduces accepted named-token write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
  expectEqual(`${oracle.expression} reproduces the final captured LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(rendered.grid)).digest('hex'),
    oracle.final_lcd_sha256);
  const browser = mp.constructedProgramForExpression(oracle.expression);
  if (!browser)
    throw new Error(`${oracle.expression} has no browser-constructed record program`);
  const expectedBrowser = rom.constructSettledExpressionProgram(oracle.spec, 1, font);
  expectEqual(`${oracle.expression} browser grammar preserves native token bytes`,
    browser.nodes, expectedBrowser.nodes);
  const nativeTokens = rom.encodeSettledExpressionTokens(oracle.spec);
  const nativeProgram = rom.constructSettledProgramFromTokens(
    nativeTokens, oracle.entry_id, font);
  expectEqual(`${oracle.expression} native bytes reproduce the captured graph`,
    nativeProgram.nodes, oracle.nodes);
}
for (const oracle of twoByteTokenOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} independently constructs the two-byte-token graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(
    program.nodes, program.entry_id, {
      origin:program.origin, glyphAdvance:settledGlyphAdvance,
    });
  const rendered = rom.rasterizeSettledOperations(operations, font);
  expectEqual(`${oracle.expression} reproduces accepted two-byte-token write count`,
    rendered.writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(rendered.writes.flatMap(
    write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} reproduces accepted two-byte-token write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
  expectEqual(`${oracle.expression} reproduces the two-byte-token LCD bitmap`,
    crypto.createHash('sha256').update(packedLcdBytes(rendered.grid)).digest('hex'),
    oracle.final_lcd_sha256);
  const browser = mp.constructedProgramForExpression(oracle.expression);
  if (!browser)
    throw new Error(`${oracle.expression} has no browser-constructed record program`);
  const expectedBrowser = rom.constructSettledExpressionProgram(oracle.spec, 1, font);
  expectEqual(`${oracle.expression} browser grammar preserves two-byte token bytes`,
    browser.nodes, expectedBrowser.nodes);
  const nativeTokens = rom.encodeSettledExpressionTokens(oracle.spec);
  const nativeProgram = rom.constructSettledProgramFromTokens(
    nativeTokens, oracle.entry_id, font);
  expectEqual(`${oracle.expression} native bytes reproduce the captured graph`,
    nativeProgram.nodes, oracle.nodes);
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
for (const oracle of nestedBaselineOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  const programById = new Map(program.nodes.map(node => [node.record_id,node]));
  const expectedNodes = oracle.nodes.map((node, index) => ({
    ...node,
    // The editor reserves one large-font cell for its live cursor after the
    // settled expression. That reserve changes only the outer leaf width and
    // is outside the closed expression program translated here.
    word07:index === 0 ? node.word07 - oracle.root_cursor_width : node.word07,
    // These traces enter logBASE through its interactive template and leave
    // its active-child selector at 2. Native-source construction visits the
    // 34:59AC child order 2,1 and leaves the same non-rendering field at 1.
    word05:node.render_type === 0x28
      ? programById.get(node.record_id).word05 : node.word05,
  }));
  expectEqual(`${oracle.expression} retains template logBASE child state`,
    oracle.nodes.filter(node => node.render_type === 0x28)
      .map(node => node.word05), [2]);
  expectEqual(`${oracle.expression} applies the traced nested baseline fields`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:expectedNodes});
  const operations = rom.executeSettledRecordProgram(program.nodes, program.entry_id, {
    origin:program.origin,
    glyphAdvance:settledGlyphAdvance,
  });
  const writes = rom.rasterizeSettledOperations(operations, font).writes;
  expectEqual(`${oracle.expression} reproduces nested-baseline write count`,
    writes.length, oracle.accepted_write_count);
  const writeBytes = Buffer.from(writes.flatMap(write => [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} reproduces nested-baseline write stream`,
    crypto.createHash('sha256').update(writeBytes).digest('hex'),
    oracle.accepted_write_sha256);
}
for (const oracle of nestedBaselineOracles.nested_layout_cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} reproduces the nested layout graph`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.origin, nodes:oracle.nodes});
  const root = program.nodes.find(node => node.record_id === program.entry_id);
  const recordOperations = rom.executeSettledRecordProgram(
    program.nodes, program.entry_id, {
      origin:program.origin,
      glyphAdvance:settledGlyphAdvance,
    });
  const synchronousOperations = rom.settledEditorViewportOperations(
    recordOperations,rom.settledEditorViewport(0),root.word05,{
      glyphAdvance:settledGlyphAdvance,
    });
  const synchronousWrites = rom.rasterizeSettledOperations(
    synchronousOperations,font).writes;
  expectEqual(`${oracle.expression} applies the traced right glyph gate`,
    synchronousWrites.length,oracle.synchronous_renderer.accepted_write_count);
  expectEqual(`${oracle.expression} reproduces synchronous write pointer order`,
    crypto.createHash('sha256').update(Buffer.from(
      synchronousWrites.flatMap(write => write.pointer))).digest('hex'),
    oracle.synchronous_renderer.pointer_sha256);
  expectEqual(`${oracle.expression} produces the synchronous counterfactual bytes`,
    crypto.createHash('sha256').update(Buffer.from(
      synchronousWrites.flatMap(write => [...write.pointer,write.value])))
      .digest('hex'),oracle.synchronous_renderer.translated_write_sha256);
  const interrupt = oracle.run_indicator_interrupt;
  const tick = rom.settledRunIndicatorTick(
    interrupt.indic_counter_before,interrupt.indic_busy_before);
  expectEqual(`${oracle.expression} translates the interrupt state transition`, {
    indicCounter:tick.indicCounter,
    indicBusy:tick.indicBusy,
    rows:tick.operation.rows,
  }, {
    indicCounter:interrupt.indic_counter_after,
    indicBusy:interrupt.indic_busy_after,
    rows:interrupt.rows,
  });
  const interruptedOperations = synchronousOperations.slice();
  interruptedOperations.splice(
    interrupt.after_operation_count,0,tick.operation);
  const interruptedWrites = rom.rasterizeSettledOperations(
    interruptedOperations,font).writes;
  expectEqual(`${oracle.expression} reproduces interrupt-inclusive write count`,
    interruptedWrites.length,oracle.accepted_write_count);
  expectEqual(`${oracle.expression} reproduces interrupt-inclusive write stream`,
    crypto.createHash('sha256').update(Buffer.from(
      interruptedWrites.flatMap(write => [...write.pointer,write.value])))
      .digest('hex'),oracle.accepted_write_sha256);
  const generated = mp.generatedForExpression(oracle.expression);
  if (!generated)
    throw new Error(`${oracle.expression} has no generated nested layout`);
  const finalBitmap = cropInk(generated.final);
  expectEqual(`${oracle.expression} reproduces the final nested layout dimensions`,
    [finalBitmap[0].length,finalBitmap.length],
    [oracle.final_bitmap.width,oracle.final_bitmap.height]);
  expectEqual(`${oracle.expression} reproduces the final nested layout bitmap`,
    crypto.createHash('sha256').update(
      packedLcdBytes(finalBitmap))
      .digest('hex'), oracle.final_bitmap.sha256);
}
for (const oracle of liveEditorOracles.cases) {
  expectEqual(`${oracle.expression} decodes the live transient-root graph`,
    rom.decodeSettledExpressionGraph(oracle.nodes, oracle.wrapper_id),
    oracle.spec);
  const operations = rom.executeSettledRecordProgram(
    oracle.nodes, oracle.wrapper_id, {
      origin:oracle.origin,
      glyphAdvance:settledGlyphAdvance,
    });
  const rendered = rom.rasterizeSettledOperations(operations, font);
  const writeBytes = Buffer.from(rendered.writes.flatMap(write =>
    [...write.pointer,write.value]));
  expectEqual(`${oracle.expression} reproduces the live translated write stream`,
    {
      count:rendered.writes.length,
      sha256:crypto.createHash('sha256').update(writeBytes).digest('hex'),
    }, {
      count:oracle.translated_write_count,
      sha256:oracle.translated_write_sha256,
    });
  expectEqual(`${oracle.expression} reproduces the live entry-line pixels`,
    {
      dimensions:[cropInk(rendered.grid)[0].length,cropInk(rendered.grid).length],
      sha256:crypto.createHash('sha256').update(
        Buffer.from(cropInk(rendered.grid).flat())).digest('hex'),
    }, {
      dimensions:oracle.entry_crop,
      sha256:oracle.entry_crop_sha256,
    });
  expectEqual(`${oracle.expression} retains the full translated framebuffer`,
    crypto.createHash('sha256').update(
      packedLcdBytes(rendered.grid)).digest('hex'),
    oracle.final_lcd_sha256);
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
for (const oracle of matrixBaselineOracles.cases) {
  const program = rom.constructSettledExpressionProgram(
    oracle.spec, oracle.entry_id, font);
  expectEqual(`${oracle.expression} aligns matrix cells to captured baselines`,
    {entry_id:program.entry_id, origin:program.origin, nodes:program.nodes},
    {entry_id:oracle.entry_id, origin:oracle.display_origin, nodes:oracle.nodes});
  const operations = rom.executeSettledRecordProgram(
    program.nodes, program.entry_id, {
      origin:{x:0,y:0},
      glyphAdvance:settledGlyphAdvance,
    });
  const crop = cropInk(rom.rasterizeSettledOperations(operations, font).grid);
  expectEqual(`${oracle.expression} reproduces the mixed-baseline matrix pixels`,
    {
      width:crop[0].length,
      height:crop.length,
      sha256:crypto.createHash('sha256').update(
        Buffer.from(crop.flat())).digest('hex'),
    }, oracle.final_crop);
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
const tallSummation = mp.constructedProgramForExpression(
  'sum(A,1,1,sqrt(int(1,3,N,A))//sqrt(A)^1^X)');
expectEqual('summation unions a tall body with its independent limit rows',
  tallSummation.nodes.slice(0, 6).map(node => ({
    id:node.record_id, type:node.render_type,
    height:node.word05, recordHeight:node.word07,
    width:node.word09, baseline:node.word0B, y:node.word0D,
  })), [
    {id:1,type:0,height:33,recordHeight:68,width:18,baseline:0,y:0},
    {id:2,type:0x29,height:3,recordHeight:33,width:68,baseline:18,y:0},
    {id:3,type:1,height:5,recordHeight:4,width:2,baseline:0,y:23},
    {id:4,type:0,height:5,recordHeight:4,width:2,baseline:8,y:23},
    {id:5,type:0,height:5,recordHeight:4,width:2,baseline:4,y:9},
    {id:6,type:0,height:33,recordHeight:45,width:18,baseline:18,y:0},
  ]);
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
const structuralMatrixProgram =
  mp.constructedProgramForExpression('matrix(2,2,sqrt(2),X^2,3,4)');
expectEqual('structural matrix trace fixes first-cell reservation and centering',
  structuralMatrixProgram.nodes.map(node => ({
    id:node.record_id, type:node.render_type, parent:node.word03,
    x:node.word0B, y:node.word0D, children:node.child_ids,
  })), [
    {id:1,type:0,parent:0,x:0,y:0,children:[]},
    {id:2,type:0x2b,parent:1,x:9,y:0,children:[3,7,10,11]},
    {id:3,type:0,parent:2,x:6,y:1,children:[]},
    {id:5,type:0x27,parent:3,x:5,y:0,children:[6]},
    {id:6,type:0,parent:5,x:5,y:2,children:[]},
    {id:7,type:0,parent:2,x:23,y:0,children:[]},
    {id:8,type:0x2a,parent:7,x:6,y:6,children:[9]},
    {id:9,type:0,parent:8,x:0,y:0,children:[]},
    {id:10,type:0,parent:2,x:8,y:12,children:[]},
    {id:11,type:0,parent:2,x:25,y:12,children:[]},
  ]);
expectEqual('structural matrix emits native square-bracket cells',
  structuralMatrixProgram.native_tokens,
  [0x06,0x06,0xbc,0x32,0x11,0x2b,0x58,0xf0,0x32,0x07,
   0x06,0x33,0x2b,0x34,0x07,0x07]);
if (mp.generatedForExpression('matrix(2,2,sqrt(2),X^2,3,4)')
    .operations.some(operation => operation.kind.startsWith('unresolved')))
  throw new Error('structural matrix has an unresolved generated operation');
expectEqual('browser places matrix results at the right-aligned LCD origin',
  mp.constructedProgramForExpression('matrix(2,3,4,-2,0,-7,8,8)').origin,
  {x:41,y:9});
const groupedFractionPowerSpec = {
  kind:'power',
  base:{kind:'fraction',
    numerator:{kind:'group',expression:{kind:'sequence',parts:[
      [0x33],[0x82],[0x32],
    ]}},
    denominator:[0x31]},
  exponent:{kind:'power',
    base:{kind:'group',expression:{kind:'sequence',parts:[
      [0x4e],[0x70],[0x58],
    ]}},
    exponent:{kind:'group',expression:{kind:'sequence',parts:[
      [0x33],[0x70],[0x32],
    ]}}},
};
const groupedFractionPowerNative =
  rom.encodeSettledExpressionTokens(groupedFractionPowerSpec);
expectEqual('fraction scanner retains an explicitly grouped numerator',
  groupedFractionPowerNative,
  [0x10,0x10,0x33,0x82,0x32,0x11,0x11,0xef,0x2e,0x31,
   0xf0,0x10,0x10,0x4e,0x70,0x58,0x11,0xf0,0x10,0x10,
   0x33,0x70,0x32,0x11,0x11,0x11]);
const groupedFractionPower = rom.constructSettledProgramFromTokens(
  groupedFractionPowerNative, 1, font);
expectEqual('fraction power-base metrics follow 34:70C1 and 34:77AD',
  groupedFractionPower.nodes.map(node => ({
    id:node.record_id, type:node.render_type,
    word05:node.word05, word07:node.word07, word09:node.word09,
    word0B:node.word0B, word0D:node.word0D, word0F:node.word0F,
  })), [
    {id:1,type:0,word05:19,word07:78,word09:12,word0B:0,word0D:0,word0F:12},
    {id:2,type:0x20,word05:2,word07:13,word09:30,word0B:6,word0D:0,word0F:6},
    {id:3,type:0,word05:5,word07:26,word09:2,word0B:2,word0D:0,word0F:0},
    {id:4,type:0,word05:5,word07:4,word09:2,word0B:13,word0D:8,word0F:1},
    {id:5,type:0x2a,word05:1,word07:19,word09:48,word0B:12,word0D:30,word0F:0},
    {id:6,type:0,word05:8,word07:48,word09:5,word0B:0,word0D:0,word0F:11},
    {id:7,type:0x2a,word05:1,word07:8,word09:24,word0B:5,word0D:24,word0F:0},
    {id:8,type:0,word05:5,word07:24,word09:2,word0B:0,word0D:0,word0F:5},
  ]);
expectEqual('grouped nested-power metrics follow the traced base axis',
  groupedNestedPowerProgram.nodes.filter(node => node.render_type === 0x2a)
    .map(node => ({
      id:node.record_id,height:node.word07,width:node.word09,
      baseline:node.word0B,x:node.word0D,baseDelta:node.word0F,
    })), [
    {id:8,height:10,width:24,baseline:6,x:12,baseDelta:6},
    {id:10,height:16,width:48,baseline:12,x:42,baseDelta:0},
    {id:12,height:8,width:24,baseline:5,x:24,baseDelta:0},
  ]);
const mixedBaselineProgram = rom.constructSettledExpressionProgram({
  kind:'sequence',parts:[
    {kind:'fraction',
      numerator:{kind:'group',expression:{kind:'sequence',parts:[
        {kind:'group',expression:{kind:'sequence',parts:[[0x31],[0x82],[0x41]]}},
        [0x83],[0x58],
      ]}},
      denominator:{kind:'fraction',
        numerator:{kind:'group',expression:{kind:'sequence',parts:[
          [0x4e],[0x71],[0x4e],
        ]}},
        denominator:{kind:'group',expression:{kind:'sequence',parts:[
          [0x31],[0x82],[0x33],
        ]}}}},
    [0x82],
    {kind:'summation',variable:[0x58],lower:[0x32],upper:[0x31],body:[0x4e]},
  ],
}, 1, font);
expectEqual('leaf union preserves top and bottom extents around a raised baseline',
  {
    height:mixedBaselineProgram.nodes[0].word05,
    baseline:mixedBaselineProgram.nodes[0].word09,
  }, {height:24,baseline:9});
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
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
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
const repeatedIntegralSpec = {
  kind:'integral',
  lower:[0x31], upper:[0x33],
  body:{kind:'sequence',parts:[
    {kind:'fraction',numerator:[0x31],denominator:[0x32]}, [0x58],
  ]},
  variable:[0x58],
};
const repeatedIntegralProgram = rom.constructSettledExpressionProgram({
  kind:'sequence',parts:new Array(1024).fill(repeatedIntegralSpec),
}, 1, font);
expectEqual('token-aware record walk ignores EF/type bytes inside record IDs', {
  nodes:repeatedIntegralProgram.nodes.length,
  width:repeatedIntegralProgram.nodes[0].word07,
  maximumRecordId:Math.max(...repeatedIntegralProgram.nodes.map(
    node => node.record_id)),
}, {nodes:8193,width:51200,maximumRecordId:8193});
expectThrows('repeated integral construction rejects genuine word-width exhaustion',
  RangeError, () => rom.constructSettledExpressionProgram({
    kind:'sequence',parts:new Array(1311).fill(repeatedIntegralSpec),
  }, 1, font));
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
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('radical browser path labels translated construction',
  mp.generatedForExpression('sqrt(X^2+1)').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('nth-root browser path labels translated construction',
  mp.generatedForExpression('nthroot(3,X+1)').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('compositional browser path labels translated construction',
  mp.generatedForExpression('X^sqrt(2)').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('fraction browser path labels translated construction',
  mp.generatedForExpression('1//2').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('integral browser path labels translated construction',
  mp.generatedForExpression('int(1,2,X,X)').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('summation browser path labels translated construction',
  mp.generatedForExpression('sum(N,1,3,N^2)').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
expectEqual('nDeriv browser path labels translated construction',
  mp.generatedForExpression('nDeriv(X^2,X,1)').programSource,
  '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction');
if (!mp.generatedForExpression('A+(X)'))
  throw new Error('visible grouped expression has no generated LCD write stream');

// Keep RE and renderer coverage broader than the small set of examples shown
// in the browser. These variants would be repetitive in the gallery but remain
// useful as pixel-level LCD-write regressions.
const regressionExpressions = [
  'Ans+1', 'Ans^2', 'sqrt(Ans)', 'X^Ans',
  'sin(X)', 'sin(sqrt(X))', 'cos(X)', 'tan(X)',
  'sinh(X)', 'cosh(X)', 'tanh(X)', 'ln(X)', 'log(X)',
  'L1', 'L1^2', '[A]', 'Y1', 'Str1', 'cumSum(L1)',
  'remainder(Ans,2)', '1/2', '1//2', 'X^2', '(X+1)^2', 'X^(1+2)',
  'sqrt(X)^2', 'abs(X)^2', 'exp(12)', 'tenpow(X^2)',
  'logbase(12,345)', 'logbase(3,1//2)',
  'matrix(1,1,1)', 'matrix(2,2,1,0,0,1)',
  'matrix(2,3,4,-2,0,-7,8,8)', 'matrix(2,2,sqrt(2),X^2,3,4)',
  '(A+B)//C', '1//(2//3)', 'sqrt(X^2+1)', 'abs(X-3)',
  'abs(X^2+1)', 'abs(sqrt(X^2+1))', 'int(1,2,X^2,X)',
  '(int(1,2,X^2,X))//3', 'int(1,2,(1//2)X,X)',
  'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)',
  'sqrt((X^2+1)//X)', 'sum(N,1,3,N^2)',
  '(sum(N,1,3,N^2))//2', 'nthroot(3,X+1)',
  'nDeriv(X^2,X,1)', '(nDeriv(X^2,X,3))//2', 'nthroot(N,X//2)',
];

for (const expression of regressionExpressions) {
  const label = `regression expression ${expression}`;
  const program = mp.constructedProgramForExpression(expression);
  if (!program)
    throw new Error(`${label} (${expression}) has no constructed record program`);
  const generated = mp.generatedForExpression(expression);
  if (!generated || generated.width !== 96 || generated.height !== 64 ||
      generated.events.length === 0)
    throw new Error(`${label} (${expression}) has no pixel-level LCD write trace`);
  if (generated.events.some(event => !Array.isArray(event.pointer) ||
      !Array.isArray(event.changes) || !Number.isInteger(event.value) ||
      !Number.isInteger(event.beforeValue) || !Array.isArray(event.pixels) ||
      event.pixels.length !== 8 || event.pixels.some(pixel =>
        !Number.isInteger(pixel.x) || !Number.isInteger(pixel.y) ||
        ![0,1].includes(pixel.before) || ![0,1].includes(pixel.value) ||
        pixel.changed !== (pixel.before !== pixel.value))))
    throw new Error(`${label} (${expression}) has an incomplete LCD write event`);
  if (generated.operations.some(operation => operation.kind === 'glyph' &&
      operation.code === 0xf7))
    throw new Error(`${label} (${expression}) renders an empty-slot placeholder`);
  if (generated.operations.some(operation =>
      operation.kind.startsWith('unresolved')))
    throw new Error(`${label} (${expression}) has an unresolved render operation`);
}

expectEqual('browser presents a selective mechanism-diverse example set',
  mp.presets.map(([label]) => label),[
    'Ans plus 1 (RE)',
    'list L1 (RE)',
    'remainder of Ans and 2 (RE)',
    'grouped base squared (RE)',
    '10 raised to X squared (RE)',
    'log base 3 of one half (RE)',
    'nested 2 by 2 matrix (RE)',
    'nested fraction',
    'absolute value of a radical and power (RE)',
    'integral of a fraction',
    'summation (RE)',
    'nth root of a fraction',
    'nDeriv (RE)',
    'repeated integrals with horizontal overflow (RE)',
  ]);

expectEqual('full RE regression corpus remains independent of the visible gallery',
  [regressionExpressions.length,
   mp.presets.every(([, expression]) => regressionExpressions.includes(expression))],
  [52, true]);

const sharedMarkerPathClasses = [
  {a:0x00,bit:false,word:0,terminal:'bitmap_61BE',count:32505856,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:taken','34:619F:fallthrough',
     '34:61A5:fallthrough','34:61AB:fallthrough']},
  {a:0x2b,bit:false,word:0,terminal:'bitmap_61C7_clear_iy_minus1_bit0',count:6,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:fallthrough','34:6178:fallthrough',
     '34:6181:taken','34:6186:fallthrough','34:618E:fallthrough']},
  {a:0x27,bit:false,word:0,terminal:'bitmap_6304',count:65536,
   path:['34:6145:fallthrough','34:614E:fallthrough']},
  {a:0x27,bit:true,word:0,terminal:'bitmap_630C',count:65536,
   path:['34:6145:fallthrough','34:614E:taken']},
  {a:0x26,bit:false,word:0,terminal:'glyph_1D_set_iy32_bit2',count:131072,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:taken','34:619F:taken']},
  {a:0x28,bit:false,word:0,terminal:'glyph_6C',count:131072,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:taken','34:619F:fallthrough',
     '34:61A5:taken']},
  {a:0x22,bit:false,word:0,terminal:'glyph_7C_set_iy32_bit2',count:131072,
   path:['34:6145:taken','34:6157:fallthrough']},
  {a:0x2b,bit:true,word:8,terminal:'glyph_7C_set_iy32_bit2',count:248,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:fallthrough','34:6178:fallthrough',
     '34:6181:fallthrough','34:6186:taken']},
  {a:0x2b,bit:false,word:6,terminal:'glyph_7C_set_iy32_bit2',count:250,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:fallthrough','34:6178:fallthrough',
     '34:6181:taken','34:6186:taken']},
  {a:0x2b,bit:false,word:0x100,terminal:'glyph_7C_set_iy32_bit2',count:130560,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:fallthrough','34:6178:taken']},
  {a:0x21,bit:false,word:0,terminal:'glyph_7C_set_iy32_bit2',count:131072,
   path:['34:6145:taken','34:6157:taken','34:6166:taken']},
  {a:0x2b,bit:true,word:0,terminal:'glyph_C1',count:8,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:fallthrough','34:6178:fallthrough',
     '34:6181:fallthrough','34:6186:fallthrough','34:618E:taken']},
  {a:0x29,bit:false,word:0,terminal:'glyph_C6',count:131072,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:fallthrough','34:6170:taken','34:619F:fallthrough',
     '34:61A5:fallthrough','34:61AB:taken']},
  {a:0x25,bit:false,word:0,terminal:'glyph_DB_set_iy32_bit2',count:131072,
   path:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
     '34:616C:taken']},
];
const sharedMarkerTerminalEffects = {
  bitmap_61BE:{operation:{kind:'bitmap',rows:[2,1,0,31,0,2,6]},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:false}},
  bitmap_61C7_clear_iy_minus1_bit0:{
    operation:{kind:'bitmap',rows:[6,4,4,4,6]},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:true}},
  bitmap_6304:{operation:{kind:'bitmap',rows:[0,4,4,20,12,4,0]},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:false}},
  bitmap_630C:{operation:{kind:'bitmap',rows:[4,4,4,4,20,12,4]},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:false}},
  glyph_1D_set_iy32_bit2:{operation:{kind:'display-code',code:0x1d},
    sideEffects:{setIy32Bit2:true,clearIyMinus1Bit0:false}},
  glyph_6C:{operation:{kind:'display-code',code:0x6c},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:false}},
  glyph_7C_set_iy32_bit2:{operation:{kind:'display-code',code:0x7c},
    sideEffects:{setIy32Bit2:true,clearIyMinus1Bit0:false}},
  glyph_C1:{operation:{kind:'display-code',code:0xc1},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:false}},
  glyph_C6:{operation:{kind:'display-code',code:0xc6},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:false}},
  glyph_DB_set_iy32_bit2:{operation:{kind:'display-code',code:0xdb},
    sideEffects:{setIy32Bit2:true,clearIyMinus1Bit0:false}},
};
for (const row of sharedMarkerPathClasses) {
  const result = rom.settledSharedMarkerPrimitive(row.a,{
    iy44Bit3:row.bit,word8520:row.word,
  });
  expectEqual(`34:6143 ${row.terminal} representative`,{
    terminal:result.terminal,branchOutcomes:result.branchOutcomes,
  },{terminal:row.terminal,branchOutcomes:row.path});
  expectEqual(`34:6143 ${row.terminal} operation and side effects`,{
    operation:result.operation.kind === 'bitmap'
      ? {kind:result.operation.kind,rows:result.operation.rows}
      : {kind:result.operation.kind,code:result.operation.code},
    sideEffects:result.sideEffects,
  },sharedMarkerTerminalEffects[row.terminal]);
}
const sharedMarkerClasses = new Map();
const sharedMarkerOutcomes = new Set();
for (let a = 0; a <= 0xff; a++) {
  for (const iy44Bit3 of [false,true]) {
    const wordLimit = a === 0x2b ? 0x10000 : 1;
    for (let word8520 = 0; word8520 < wordLimit; word8520++) {
      const result = rom.settledSharedMarkerPrimitive(
        a,{iy44Bit3,word8520});
      const signature = `${result.terminal}|${result.branchOutcomes.join(',')}`;
      sharedMarkerClasses.set(
        signature,(sharedMarkerClasses.get(signature) || 0) +
        (a === 0x2b ? 1 : 0x10000));
      for (const outcome of result.branchOutcomes)
        sharedMarkerOutcomes.add(outcome);
    }
  }
}
expectEqual('34:6143 exhausts its 33,554,432-state projection',{
  classes:sharedMarkerClasses.size,
  outcomes:sharedMarkerOutcomes.size,
  states:Array.from(sharedMarkerClasses.values()).reduce((sum,count) => sum + count,0),
  classCounts:Array.from(sharedMarkerClasses.values()).sort((a,b) => a - b),
},{
  classes:14,outcomes:26,states:0x2000000,
  classCounts:sharedMarkerPathClasses.map(row => row.count).sort((a,b) => a - b),
});
expectEqual('34:6143 matrix low-count primitive and side effect',
  rom.settledSharedMarkerPrimitive(0x2b,{iy44Bit3:false,word8520:5}),{
    incomingA:0x2b,iy44Bit3:false,word8520:5,
    terminal:'bitmap_61C7_clear_iy_minus1_bit0',
    operation:{kind:'bitmap',x:0,y:0,width:5,height:5,
      rows:[0x06,0x04,0x04,0x04,0x06],retainUnchanged:true,
      routine:'34:6143 → 34:61C7'},
    sideEffects:{setIy32Bit2:false,clearIyMinus1Bit0:true},
    branchOutcomes:['34:6145:taken','34:6157:taken','34:6166:fallthrough',
      '34:616C:fallthrough','34:6170:fallthrough','34:6178:fallthrough',
      '34:6181:taken','34:6186:fallthrough','34:618E:fallthrough'],
    routine:'34:6143–61BD',
  });
expectEqual('34:6143 matrix focused primitive',
  rom.settledSharedMarkerPrimitive(0x2b,{iy44Bit3:true,word8520:7}).operation,
  {kind:'display-code',code:0xc1,
   routine:'34:6143 → 34:615F → ram:3CE1'});
expectThrows('34:6143 rejects a non-Boolean editor flag',TypeError,
  () => rom.settledSharedMarkerPrimitive(0x2b,{iy44Bit3:1}));
expectThrows('34:6143 rejects an oversized matrix state word',RangeError,
  () => rom.settledSharedMarkerPrimitive(0x2b,{word8520:0x10000}));

const renderNestingTailProjection = result => ({
  nestingCounterAfter:result.nestingCounterAfter,
  decremented:result.decremented,
  returnA:result.returnA,
  branchOutcomes:result.branchOutcomes,
});
for (const [label,type,child,decremented] of [
  ['integral leading child',0x22,2,false],
  ['integral third child',0x22,3,true],
  ['absolute value',0x21,1,true],
  ['radical',0x27,1,true],
  ['matrix',0x2b,9,true],
  ['log first child',0x28,1,false],
  ['log second child',0x28,2,true],
  ['nth-root first child',0x24,1,false],
  ['nth-root second child',0x24,2,true],
  ['derivative first child',0x23,1,false],
  ['derivative second child',0x23,2,true],
  ['derivative third child',0x23,3,false],
  ['summation third child',0x29,3,false],
  ['summation fourth child',0x29,4,true],
  ['ordinary type',0x20,2,false],
]) {
  const result = rom.settledRenderNestingTail(type,child,7);
  expectEqual(`34:61CE ${label} decrement decision`,{
    decremented:result.decremented,
    nestingCounterAfter:result.nestingCounterAfter,
  },{decremented,nestingCounterAfter:decremented ? 6 : 7});
}
let renderNestingTailStates = 0;
for (let type = 0; type <= 0xff; type++) {
  for (let child = 0; child <= 0xff; child++) {
    for (const nestingCounter of [0,1,2,0xff]) {
      const translated = rom.settledRenderNestingTail(
        type,child,nestingCounter);
      const raw = runRawRenderNestingTail(type,child,nestingCounter);
      expectEqual('34:61CE exhaustive type/child byte-flow basis',
        renderNestingTailProjection(translated),raw);
      renderNestingTailStates++;
    }
  }
}
for (let nestingCounter = 0; nestingCounter <= 0xff; nestingCounter++) {
  for (const [type,child] of [[0x2b,1],[0x20,1]]) {
    expectEqual('34:79C9 exhaustive nesting-counter byte basis',
      renderNestingTailProjection(
        rom.settledRenderNestingTail(type,child,nestingCounter)),
      runRawRenderNestingTail(type,child,nestingCounter));
    renderNestingTailStates++;
  }
}
expectEqual('34:61CE projected differential state count',
  renderNestingTailStates,0x40200);
expectThrows('34:61CE rejects an oversized child index',RangeError,
  () => rom.settledRenderNestingTail(0x22,0x100,1));
expectThrows('34:61CE rejects an oversized nesting counter',RangeError,
  () => rom.settledRenderNestingTail(0x22,1,0x100));

expectEqual('34:759C returns before the Y= guard on a pointer mismatch',
  rom.settledMetricMarkerTailGate({
    recordPointer:0x9007,editTail:0x9000,incomingA:0x2b,
    cxCurApp:0x49,tblFlags:1,markerType:0x20,nestingCounter:0,
  }),{
    recordPointer:0x9007,editTail:0x9000,incomingA:0x2b,
    cxCurApp:0x49,tblFlags:1,markerType:0x20,nestingCounter:0,
    terminal:'return_nz_pointer_mismatch',returnA:0x2b,zero:false,
    returnedFlags:'NZ',branchOutcomes:['34:75A5:returned'],
    routine:'34:759C–75C1',
  });
expectEqual('34:789A preserves the raw Y= selection early return',
  rom.settledMetricMarkerTailGate({
    recordPointer:0x9006,editTail:0x9000,incomingA:0x2a,
    cxCurApp:0x49,tblFlags:0x41,markerType:0x20,nestingCounter:0,
  }),{
    recordPointer:0x9006,editTail:0x9000,incomingA:0x2a,
    cxCurApp:0x49,tblFlags:0x41,markerType:0x20,nestingCounter:0,
    terminal:'return_nz_yequ_selection',returnA:0x2b,zero:false,
    returnedFlags:'NZ',branchOutcomes:[
      '34:75A5:fallthrough','34:75A9:taken'],
    routine:'34:759C–75C1',
  });
expectEqual('34:759C wraps the six-byte source-pointer subtraction',
  rom.settledMetricMarkerTailGate({
    recordPointer:4,editTail:0xfffe,incomingA:0,
    cxCurApp:0,tblFlags:0,markerType:0x24,nestingCounter:1,
  }).terminal,'return_z_special_marker_nested');
expectEqual('34:75B0 rejects an ordinary marker',
  rom.settledMetricMarkerTailGate({
    recordPointer:0x9006,editTail:0x9000,incomingA:0x1f,
    cxCurApp:0,tblFlags:0,markerType:0x29,nestingCounter:0,
  }),{
    recordPointer:0x9006,editTail:0x9000,incomingA:0x1f,
    cxCurApp:0,tblFlags:0,markerType:0x29,nestingCounter:0,
    terminal:'return_nz_other_marker',returnA:0x29,zero:false,
    returnedFlags:'NZ',branchOutcomes:[
      '34:75A5:fallthrough','34:75A9:fallthrough','34:75B0:fallthrough'],
    routine:'34:759C–75C1',
  });
expectEqual('34:75BB selects six outer pixels and five nested pixels',[
  rom.settledMetricMarkerTailGate({
    recordPointer:0x9006,editTail:0x9000,incomingA:0,
    cxCurApp:0,tblFlags:0,markerType:0x20,nestingCounter:0,
  }).returnA,
  rom.settledMetricMarkerTailGate({
    recordPointer:0x9006,editTail:0x9000,incomingA:0,
    cxCurApp:0,tblFlags:0,markerType:0x2a,nestingCounter:1,
  }).returnA,
],[6,5]);
const metricMarkerClasses = new Set(), metricMarkerOutcomes = new Set();
for (const atTail of [false,true]) {
  for (const cxCurApp of [0,0x49]) {
    for (const tblFlags of [0,1]) {
      for (let markerType = 0; markerType <= 0xff; markerType++) {
        for (const nestingCounter of [0,1]) {
          const result = rom.settledMetricMarkerTailGate({
            recordPointer:atTail ? 0x9006 : 0x9007,editTail:0x9000,
            incomingA:0x2a,cxCurApp,tblFlags,markerType,nestingCounter,
          });
          metricMarkerClasses.add(
            `${result.terminal}|${result.branchOutcomes.join(',')}`);
          for (const outcome of result.branchOutcomes)
            metricMarkerOutcomes.add(outcome);
        }
      }
    }
  }
}
expectEqual('34:759C exhausts its representative raw-state projection',{
  states:2 * 2 * 2 * 0x100 * 2,
  classes:metricMarkerClasses.size,outcomes:metricMarkerOutcomes.size,
},{states:4096,classes:5,outcomes:8});
expectThrows('34:759C rejects an oversized record pointer',RangeError,
  () => rom.settledMetricMarkerTailGate({
    recordPointer:0x10000,editTail:0,cxCurApp:0,tblFlags:0,
    markerType:0,nestingCounter:0,
  }));
for (const [captureName,capture] of
  Object.entries(yEquSelectionOracle.captures)) {
  expectEqual(`${captureName} Y= selection macro identity`,
    crypto.createHash('sha256').update(
      fs.readFileSync(path.join(root,capture.macro))).digest('hex'),
    capture.macro_sha256);
}
const shortYEquSelection =
  yEquSelectionOracle.captures.short_power_selection.selection_entry;
for (const call of shortYEquSelection.metric_calls) {
  const result = rom.settledMetricMarkerTailGate({
    recordPointer:Number(call.record_pointer),
    editTail:Number(shortYEquSelection.edit_tail),
    incomingA:Number(call.incoming_a),cxCurApp:0x49,tblFlags:1,
    markerType:0x20,nestingCounter:0,
  });
  expectEqual('natural Y= selection returns at the pointer comparison',{
    terminal:result.terminal,
    sourcePointer:(result.recordPointer - 6) & 0xffff,
    tailDelta:call.tail_delta,
  },{
    terminal:'return_nz_pointer_mismatch',
    sourcePointer:(Number(shortYEquSelection.edit_tail) + call.tail_delta) & 0xffff,
    tailDelta:1,
  });
}
const overflowYEquSelection =
  yEquSelectionOracle.captures.overflowing_power_sequence.selection_entry;
expectEqual('overflowing Y= selection keeps every record past the prefix',{
  calls:overflowYEquSelection.metric_call_count_while_selected,
  allPastPrefix:overflowYEquSelection.source_pointer_tail_deltas_per_pass
    .every(delta => delta > 0),
  passes:overflowYEquSelection.incoming_a_values.length,
},{calls:12,allPastPrefix:true,passes:2});
expectEqual('empty Y= selection has no metric record to test',
  yEquSelectionOracle.captures.empty_selection.selection_entry
    .metric_call_count_while_selected,0);

expectEqual('34:6119 fixes type-1F table dispatch to the default bitmap',
  rom.executeSettledRecordGraph([settledRecord(1,0x1f)],1), [{
    kind:'bitmap', x:0, y:0, width:5, height:7,
    rows:[0x02,0x01,0x00,0x1f,0x00,0x02,0x06],
    retainUnchanged:true, tableEntry:[0x43,0x61], incomingA:0x43,
    routine:'34:6105 → 34:6119 → 00:0033 → 34:6143 → 34:61BE',
    recordId:1, recordType:0x1f, depth:1,
  }]);
expectEqual('34:4FD9 transient type-1F root renders its one child directly',
  rom.executeSettledRecordGraph([
    settledRecord(1,0x1f,{},[2]),
    settledRecord(2,0x00,{word07:4,word0B:4,word0D:2}),
  ],1,{renderLeaf:leafGlyph}), [{
    kind:'glyph',code:2,x:4,y:2,routine:'test leaf',
    recordId:2,recordType:0,depth:1,
  }]);
expectThrows('transient type-1F root rejects multiple children', RangeError,
  () => rom.executeSettledRecordGraph([
    settledRecord(1,0x1f,{},[2,3]),
    settledRecord(2,0x00), settledRecord(3,0x00),
  ],1,{renderLeaf:leafGlyph}));
expectEqual('34:62A1 radical primitive order', rom.settledRadicalOperations(12, 0x1d), [
  {kind:'bitmap', x:0, y:5, width:5, height:7,
   rows:[0x04,0x04,0x04,0x04,0x14,0x0c,0x04], retainUnchanged:true,
   viewportAdvance:5,
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
    viewportAdvance:5,
    routine:'34:62A4 → 34:62D0 → 34:630C',
  });
expectEqual('34:62A7 extends a tall raised-radical stem below five hook rows',
  rom.settledRadicalOperations(17, 36, 1)[1], {
    kind:'line', axis:'vertical', from:{x:2,y:1}, to:{x:2,y:11},
    routine:'34:62AE → 34:5D96',
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
    viewportAdvance:5,
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
  'int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)',
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
