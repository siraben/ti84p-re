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
const matrixOracles = JSON.parse(fs.readFileSync(
  path.join(root, 'tools', 'mathprint-matrix-oracles.json')));
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
];
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

// Page-39 operand-emitter span.  The fixed-bank calls are stubbed with their
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
    throw new Error(`operand-emitter oracle reached unpinned byte 39:${address.toString(16)}`);
  return operandEmitterByteMap.get(address);
};
const operandEmitterWord = address =>
  operandEmitterByte(address) | (operandEmitterByte(address + 1) << 8);

function runRawOperandEmitter(service, tokenClass, tokenSubClass, options = {}) {
  const start = service === 'normal' ? 0x59e0 : 0x59f9;
  const serviceResults = options.serviceResults || [];
  const special = options.specialResult || {};
  const savedOperand = options.savedOperand || new Array(9).fill(0);
  const memory = new Map([[0x85de,tokenClass],[0x85df,tokenSubClass]]);
  let pc = start, a = 0, h = 0, hl = 0, zero = false, carry = false;
  let serviceIndex = 0, loopCount = 0, specialPath = null, postService = false;
  let callReturn = null, rstReturn = null;
  const effects = [];
  const finish = branch => ({
    branch:specialPath ? 'class-2-special' : postService ? 'post-service-complete' : branch,
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
      const result = serviceResults[serviceIndex++];
      if (!result) throw new Error('raw operand-emitter service result underflow');
      carry = !!result.carry;
      if (result.tokenClass !== undefined) memory.set(0x85de,result.tokenClass);
      if (result.tokenSubClass !== undefined) memory.set(0x85df,result.tokenSubClass);
      pc = callReturn;
      effects.push({kind:'call-service',index:serviceIndex - 1,carry});
      continue;
    }
    if (pc === 0x5c2e) {
      zero = (memory.get(0x85de) || 0) === 3 &&
        (memory.get(0x85df) || 0) === 1;
      postService = zero;
      pc = callReturn;
      continue;
    }
    if (pc === 0x1942) {
      const result = serviceResults[serviceIndex - 1];
      a = result.postCode;
      if (result.nextTokenClass !== undefined)
        memory.set(0x85de,result.nextTokenClass);
      if (result.nextTokenSubClass !== undefined)
        memory.set(0x85df,result.nextTokenSubClass);
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
      else throw new Error(`raw operand-emitter unsupported call 39:${target.toString(16)}`);
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
      if (carry) return finish('service-carry');
      pc++;
    } else if (opcode === 0xc9) {
      return finish('service-complete');
    } else {
      throw new Error(`raw operand-emitter unsupported opcode 0x${opcode.toString(16)} at 39:${pc.toString(16)}`);
    }
  }
  throw new Error('raw operand-emitter exceeded its instruction bound');
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

function runRawSavedOperandWrapper(source, service, recordFlags, buffers,
                                   serviceResult) {
  const entries = {
    'saved-E7:normal':0x5b10, 'saved-E7:variable':0x5b1d,
    'saved-F2:normal':0x5b2b, 'saved-F2:variable':0x5b38,
  };
  let pc = entries[`${source}:${service}`];
  if (pc === undefined)
    throw new RangeError('raw saved-operand oracle received an invalid wrapper');
  const memory = new Map();
  const writeBuffer = (address, values) =>
    values.forEach((value, index) => memory.set(address + index,value));
  const readBuffer = address =>
    Array.from({length:9}, (_, index) => memory.get(address + index) || 0);
  writeBuffer(0x8478,buffers.op1);
  writeBuffer(0x85e7,buffers.savedE7);
  writeBuffer(0x85f2,buffers.savedF2);
  const literalWord = address =>
    savedOperandByte(address) | (savedOperandByte(address + 1) << 8);
  const callStack = [];
  let hl = 0, de = 0;
  let zero = false;
  let carry = serviceResult.incomingCarry || false;
  let serviceInput = null;
  const finish = branch => ({
    branch, serviceInput, carry,
    buffers:{
      op1:readBuffer(0x8478),
      savedE7:readBuffer(0x85e7),
      savedF2:readBuffer(0x85f2),
    },
  });
  for (let instructions = 0; instructions < 64; instructions++) {
    if (pc === 0x1a92) {
      writeBuffer(de,readBuffer(hl));
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
        serviceInput = readBuffer(0x8478);
        writeBuffer(0x8478,serviceResult.op1);
        carry = serviceResult.carry;
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
      if (carry) return finish('service-carry');
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
      de = memory.get(literalWord(pc + 2)) || 0; pc += 4;
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
    extraWidth, rightBound, xOrigin:0, yOrigin:0, xClip,
    effectiveX:-xClip, cursorX:expressionEndpoint - xClip,
    comparisonCoordinate,
    branch:branchOutcomes[2] === '34:5F81:returned'
      ? 'return-before-right-bound' : 'store-horizontal-clip',
    branchOutcomes,
    routine:'34:5F5D–5F8A; applied by 34:5DBE–5DC9',
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

const savedOperandBuffers = {
  op1:[0x01,0x02,0x03,0x04,0x05,0x06,0x07,0x08,0x09],
  savedE7:[0x11,0x12,0x13,0x14,0x15,0x16,0x17,0x18,0x19],
  savedF2:[0x21,0x22,0x23,0x24,0x25,0x26,0x27,0x28,0x29],
};
const savedOperandServiceOp1 =
  [0xa1,0xa2,0xa3,0xa4,0xa5,0xa6,0xa7,0xa8,0xa9];
expectEqual('39:5B10 preserves buffers and carry when bit 5 is clear', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-E7','normal',0,savedOperandBuffers,{incomingCarry:true});
  return {
    branch:result.branch, serviceCalled:result.serviceCalled,
    carry:result.carry, copies:result.copies, buffers:result.buffers,
  };
})(), {
  branch:'gated-return',serviceCalled:false,carry:true,copies:[],
  buffers:savedOperandBuffers,
});
expectEqual('39:5B10 restores E7 and saves a carry-clear service result', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-E7','normal',0x20,savedOperandBuffers,{
      carry:false,op1:savedOperandServiceOp1,
    });
  return {
    branch:result.branch, serviceInput:result.serviceInput,
    carry:result.carry, copies:result.copies, buffers:result.buffers,
  };
})(), {
  branch:'save-result',serviceInput:savedOperandBuffers.savedE7,
  carry:false,copies:[
    {from:0x85e7,to:0x8478,bytes:9,routine:'39:5AE1 → 00:1A92'},
    {from:0x8478,to:0x85e7,bytes:9,routine:'39:5AD2 → 00:1A92'},
  ],buffers:{
    op1:savedOperandServiceOp1,
    savedE7:savedOperandServiceOp1,
    savedF2:savedOperandBuffers.savedF2,
  },
});
expectEqual('39:5B38 carry exit leaves E7 unchanged after restoring F2', (() => {
  const result = rom.editorSavedOperandWrapper(
    'saved-F2','variable',0x20,savedOperandBuffers,{
      carry:true,op1:savedOperandServiceOp1,
    });
  return {
    branch:result.branch, serviceInput:result.serviceInput,
    carry:result.carry, copies:result.copies, buffers:result.buffers,
  };
})(), {
  branch:'service-carry',serviceInput:savedOperandBuffers.savedF2,
  carry:true,copies:[
    {from:0x85f2,to:0x8478,bytes:9,routine:'39:5B00 → 00:1A92'},
  ],buffers:{
    op1:savedOperandServiceOp1,
    savedE7:savedOperandBuffers.savedE7,
    savedF2:savedOperandBuffers.savedF2,
  },
});
expectThrows('39:5B10 rejects an enabled service without an OP1 result',
  TypeError, () => rom.editorSavedOperandWrapper(
    'saved-E7','normal',0x20,savedOperandBuffers,{carry:false}));
expectThrows('39:5B10 rejects an eleven-byte OP scratch value',
  RangeError, () => rom.editorSavedOperandWrapper(
    'saved-E7','normal',0x20,{...savedOperandBuffers,savedE7:new Array(11).fill(0)},
    {carry:false,op1:savedOperandServiceOp1}));

const savedOperandProjection = result => ({
  branch:result.branch,
  serviceInput:result.serviceInput,
  carry:result.carry,
  buffers:result.buffers,
});
let savedOperandWrapperStates = 0;
for (const source of ['saved-E7','saved-F2']) {
  for (const service of ['normal','variable']) {
    for (let recordFlags = 0; recordFlags <= 0xff; recordFlags++) {
      for (const incomingCarry of [false,true]) {
        for (const serviceCarry of [false,true]) {
          const serviceResult = {
            incomingCarry,carry:serviceCarry,op1:savedOperandServiceOp1,
          };
          const raw = runRawSavedOperandWrapper(
            source,service,recordFlags,savedOperandBuffers,serviceResult);
          const translated = rom.editorSavedOperandWrapper(
            source,service,recordFlags,savedOperandBuffers,serviceResult);
          expectEqual('39:5B10–5B44 exhaustive wrapper state',
            savedOperandProjection(translated), raw);
          savedOperandWrapperStates++;
        }
      }
    }
  }
}
expectEqual('39:5B10–5B44 exhaustive wrapper state count',
  savedOperandWrapperStates, 0x1000);

// Exercise every value in every byte position across both restore sources and
// the carry-clear OP1 writeback. This is the complete basis of each Mov9B.
for (const source of ['saved-E7','saved-F2']) {
  for (let position = 0; position < 9; position++) {
    for (let value = 0; value <= 0xff; value++) {
      const sourceValue = new Array(9).fill(0);
      const resultValue = new Array(9).fill(0);
      sourceValue[position] = value;
      resultValue[position] = value ^ 0xff;
      const buffers = {
        op1:new Array(9).fill(0x55),
        savedE7:source === 'saved-E7'
          ? sourceValue : new Array(9).fill(0x11),
        savedF2:source === 'saved-F2'
          ? sourceValue : new Array(9).fill(0x22),
      };
      const serviceResult = {carry:false,op1:resultValue};
      expectEqual('39:5AE1/5B00/5AD2 exhaustive Mov9B basis',
        savedOperandProjection(rom.editorSavedOperandWrapper(
          source,'normal',0x20,buffers,serviceResult)),
        runRawSavedOperandWrapper(
          source,'normal',0x20,buffers,serviceResult));
    }
  }
}

const operandProjection = result => ({
  branch:result.branch, specialPath:result.specialPath || null,
  loopCount:result.loopCount === undefined ? 0 : result.loopCount,
  emitted:(result.effects || []).filter(effect => effect.kind === 'emit-token')
    .map(effect => effect.code),
});
const operandCases = [
  ['normal class-2 marker', 'normal', 0x02, 0x00,
   {specialResult:{carry:false}}],
  ['variable class-2 empty saved operand', 'variable', 0x02, 0x00,
   {savedOperand:[0x02,0,0,0,0,0,0,0,0],specialResult:{carry:false}}],
  ['normal scanner carry', 'normal', 0x04, 0x00,
   {serviceResults:[{carry:true}]}],
  ['normal scanner clear', 'normal', 0x04, 0x00,
   {serviceResults:[{carry:false}]}],
  ['normal scanner changes class before post-check', 'normal', 0x04, 0x00,
   {serviceResults:[{carry:false,tokenClass:0x02}]}],
  ['normal scanner repeat then clear', 'normal', 0x03, 0x01,
   {serviceResults:[{carry:false,postCode:0x06,nextTokenClass:0x03,
                     nextTokenSubClass:0x01},
                    {carry:false,tokenClass:0x04,tokenSubClass:0x00}]}],
  ['variable scanner post-service exit', 'variable', 0x03, 0x01,
   {serviceResults:[{carry:false,postCode:0x05}]}],
];
for (const [label, service, tokenClass, tokenSubClass, options] of operandCases) {
  const raw = runRawOperandEmitter(service,tokenClass,tokenSubClass,options);
  const translated = rom.editorOperandEmitter(
    service,tokenClass,tokenSubClass,options);
  expectEqual(`39:59E0/59F9 ${label} byte-flow`,
    operandProjection(translated), operandProjection(raw));
}
expectThrows('39:59E0 rejects an omitted scanner result', TypeError,
  () => rom.editorOperandEmitter('normal',0x04));
expectThrows('39:59F9 rejects an omitted class-2 special result', TypeError,
  () => rom.editorOperandEmitter('variable',0x02));
expectThrows('39:59F9 rejects a carrying class-2 1BAF result', TypeError,
  () => rom.editorOperandEmitter('variable',0x02,0,
    {specialResult:{carry:true}}));

let operandEmitterStates = 0;
for (const service of ['normal','variable']) {
  for (const tokenClass of [0x00,0x02,0x03,0x04,0xff]) {
    for (const tokenSubClass of [0x00,0x01,0xff]) {
      if (tokenClass === 0x02) {
        const options = service === 'variable'
          ? {savedOperand:new Array(9).fill(0),specialResult:{carry:false}}
          : {specialResult:{carry:false}};
        const raw = runRawOperandEmitter(service,tokenClass,tokenSubClass,options);
        const translated = rom.editorOperandEmitter(
          service,tokenClass,tokenSubClass,options);
        expectEqual('39:59E0/59F9 class-2 byte-flow basis',
          operandProjection(translated), operandProjection(raw));
        operandEmitterStates++;
        continue;
      }
      for (const carry of [false,true]) {
        const result = {carry};
        if (!carry && tokenClass === 0x03 && tokenSubClass === 0x01)
          result.postCode = 0x05;
        const options = {serviceResults:[result]};
        const raw = runRawOperandEmitter(service,tokenClass,tokenSubClass,options);
        const translated = rom.editorOperandEmitter(
          service,tokenClass,tokenSubClass,options);
        expectEqual('39:59E0/59F9 scanner byte-flow basis',
          operandProjection(translated), operandProjection(raw));
        operandEmitterStates++;
      }
    }
  }
}
expectEqual('39:59E0/59F9 projected operand state count', operandEmitterStates, 54);

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
    recordFlags:0, winTop:null, savedF2EmitterCarry:false,
    routine:'39:5167', lastArgument:null, nextArgument:0, rowStep:0,
    placementRow:null, nextRow:null, branch:'empty',
    effects:[{kind:'set-row-for-token',routine:'39:5447'}],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 stops at the final argument',
  rom.editorAdvanceArgument(8, 3, 4, 1, 0), {
    layoutClass:8, argumentIndex:3, argumentCount:4, currentRow:1,
    recordFlags:0, winTop:null, savedF2EmitterCarry:false,
    routine:'39:5167', lastArgument:3, nextArgument:3, rowStep:0,
    placementRow:null, nextRow:null, branch:'at-or-past-last',
    effects:[{kind:'set-row-for-token',routine:'39:5447'}],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 advances an ordinary argument by one row',
  rom.editorAdvanceArgument(8, 0, 4, 1, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:1,
    recordFlags:0, winTop:null, savedF2EmitterCarry:false,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:1,
    rowLimit:7, placementRow:2, nextRow:null, branch:'in-row',
    effects:[
      {kind:'emit-argument-index',argument:0,routine:'39:4E0A'},
      {kind:'advance-row',rows:1,value:2},
      {kind:'emit-argument-index',argument:1,routine:'39:4E0A'},
      {kind:'emit-operand',source:'saved-E7',routine:'39:5B10'},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 advances a low class-06 argument by two rows',
  rom.editorAdvanceArgument(6, 0, 4, 1, 0), {
    layoutClass:6, argumentIndex:0, argumentCount:4, currentRow:1,
    recordFlags:0, winTop:null, savedF2EmitterCarry:false,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:2,
    rowLimit:6, placementRow:3, nextRow:null, branch:'in-row',
    effects:[
      {kind:'emit-argument-index',argument:0,routine:'39:4E0A'},
      {kind:'advance-row',rows:2,value:3},
      {kind:'emit-argument-index',argument:1,routine:'39:4E0A'},
      {kind:'emit-operand',source:'saved-E7',routine:'39:5B10'},
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
    recordFlags:0, winTop:null, savedF2EmitterCarry:false,
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
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {winTop:5}), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:7,
    recordFlags:0x20, winTop:5, savedF2EmitterCarry:false,
    routine:'39:5167', lastArgument:3, nextArgument:1, rowStep:1,
    rowLimit:7, placementRow:null, nextRow:null, branch:'styled-overflow',
    effects:[
      {kind:'emit-operand',source:'saved-F2',routine:'39:5B2B',carry:false},
      {kind:'emit-argument-index',argument:0,routine:'39:4E0A'},
      {kind:'set-overflow',curCol:1,routine:'39:6712'},
      {kind:'save-window-top',value:5},
      {kind:'set-window-top',value:1},
      {kind:'scroll-editor',direction:'forward',routine:'39:3C81'},
      {kind:'emit-operand',source:'saved-E7',routine:'39:5B10'},
      {kind:'emit-saved-operand-tail',argument:1,routine:'39:5B46'},
      {kind:'finish-forward-overflow',direction:'forward',branch:'emit-cue',
        remainingArguments:null,emission:{row:1,column:1,code:0x1e},
        cursorPreserved:true,routine:'39:66FE'},
      {kind:'restore-window-top',value:5},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'row-token-tail',
  });
expectEqual('39:5167 stops styled overflow when the saved-F2 emitter carries',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedF2EmitterCarry:true,
  }).branch, 'styled-overflow-carry');
expectEqual('39:5167 composes F2 and E7 normal-wrapper state', (() => {
  const f2Result = {carry:false,op1:new Array(9).fill(0xf2)};
  const e7Result = {carry:false,op1:new Array(9).fill(0xe7)};
  const result = rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandBuffers,
    savedF2ServiceResult:f2Result,
    savedE7ServiceResult:e7Result,
  });
  const f2 = result.effects.find(effect => effect.source === 'saved-F2');
  const e7 = result.effects.find(effect => effect.source === 'saved-E7');
  return {
    branch:result.branch,carry:result.savedF2EmitterCarry,
    f2Input:f2.transition.serviceInput,
    f2Saved:f2.transition.buffers.savedF2,
    e7Input:e7.transition.serviceInput,
    e7Saved:e7.transition.buffers.savedE7,
    e7SeesF2:e7.transition.buffers.savedF2,
  };
})(), {
  branch:'styled-overflow',carry:false,
  f2Input:savedOperandBuffers.savedF2,f2Saved:new Array(9).fill(0xf2),
  e7Input:savedOperandBuffers.savedE7,e7Saved:new Array(9).fill(0xe7),
  e7SeesF2:new Array(9).fill(0xf2),
});
expectEqual('39:5167 derives the styled carry branch from the F2 wrapper',
  rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedOperandBuffers,
    savedF2ServiceResult:{carry:true,op1:new Array(9).fill(0xcc)},
  }).branch, 'styled-overflow-carry');
expectThrows('39:5167 rejects contradictory modeled and supplied F2 carry',
  RangeError, () => rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedF2EmitterCarry:false,
    savedOperandBuffers,
    savedF2ServiceResult:{carry:true,op1:new Array(9).fill(0xcc)},
  }));
expectEqual('39:523B stops before decrementing the first argument',
  rom.editorRetreatArgument(8, 0, 4, 4, 1, 0), {
    layoutClass:8, argumentIndex:0, argumentCount:4, currentRow:4,
    baselineRow:1, recordFlags:0, winTop:null, savedF2EmitterCarry:false,
    routine:'39:523B', nextArgument:0, rowStep:0, placementRow:null,
    nextRow:null, branch:'at-first', effects:[],
    continuation:'action-03-first-argument',
  });
expectEqual('39:523B retreats an ordinary argument by one row',
  rom.editorRetreatArgument(8, 2, 4, 4, 1, 0), {
    layoutClass:8, argumentIndex:2, argumentCount:4, currentRow:4,
    baselineRow:1, recordFlags:0, winTop:null, savedF2EmitterCarry:false,
    routine:'39:523B', nextArgument:1, rowStep:1,
    twoRowUnderflow:false, placementRow:3, nextRow:null, branch:'in-row',
    effects:[
      {kind:'emit-argument-index',argument:2,routine:'39:4E0A'},
      {kind:'retreat-row',rows:1,value:3},
      {kind:'emit-argument-index',argument:1,routine:'39:4E0A'},
      {kind:'emit-variable',source:'saved-E7',routine:'39:5B1D'},
      {kind:'set-row-for-token',routine:'39:5447'},
    ],
    continuation:'row-token-tail',
  });
expectEqual('39:523B executes the E7 variable-wrapper transition', (() => {
  const result = rom.editorRetreatArgument(8, 2, 4, 4, 1, 0x20, {
    savedOperandBuffers,
    savedE7ServiceResult:{carry:false,op1:new Array(9).fill(0x77)},
  });
  const effect = result.effects.find(item => item.source === 'saved-E7');
  return {
    branch:result.branch,
    service:effect.transition.service,
    input:effect.transition.serviceInput,
    result:effect.transition.buffers.savedE7,
  };
})(), {
  branch:'in-row',service:'variable',input:savedOperandBuffers.savedE7,
  result:new Array(9).fill(0x77),
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
    8, 2, 12, 1, 1, 0x20, {winTop:5,winBottom:7}).effects, [
    {kind:'emit-variable',source:'saved-F2',routine:'39:5B38',carry:false},
    {kind:'emit-argument-index',argument:2,routine:'39:4E0A'},
    {kind:'set-overflow',curCol:1,routine:'39:6712'},
    {kind:'save-window-top',value:5},
    {kind:'set-window-top',value:1},
    {kind:'scroll-editor',direction:'reverse',routine:'39:3C93'},
    {kind:'emit-variable',source:'saved-E7',routine:'39:5B1D'},
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
expectEqual('39:523B stops styled overflow when the saved-F2 emitter carries',
  rom.editorRetreatArgument(8, 2, 4, 1, 1, 0x20, {
    savedF2EmitterCarry:true,
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
expectThrows('39:5167 rejects a non-boolean saved-F2 carry', TypeError,
  () => rom.editorAdvanceArgument(8, 0, 4, 7, 0x20, {
    savedF2EmitterCarry:1,
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
expectEqual('34:608F selects and positions the right overflow bitmap',
  rom.settledEditorRightCueOperation(rom.settledEditorViewport(106), 23), {
    kind:'bitmap', x:91, y:8, width:4, height:7,
    rows:[0x00,0x04,0x06,0x07,0x06,0x04,0x00], retainUnchanged:true,
    routine:'34:5FFA → 34:607A → 34:608F; bitmap at 34:60C0',
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
expectEqual('browser decodes a transparent transient root',
  rom.decodeSettledExpressionGraph([
    {id:1,type:0x1f,childIds:[2]},
    {id:2,type:0,payload:[0x58]},
  ], 1), [0x58]);
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
    172,'96f8cf4140ea734e73908e195608d03972e1baa1003798e2ee5995cf006587a4',
    '52573ba7527565e61c5af338d8634feaf9bbbf75ab716ecc745b0a9a6edcbbf3'],
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
    156, 60],
  ['nthroot(N,logbase(123,A)//123^Ans)^Y1*abs(123)', 101, 5],
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

// Child geometry fields are byte-sized in the settled records. The text
// compositor can still preview a larger expression, while the ROM-faithful
// record constructor rejects a vinculum endpoint that cannot fit its field.
const oversizedRadical =
  'sqrt(logbase(Ans,nDeriv(L1,X,1))+' +
  'logbase(456,logbase(L1,N))*(int(2,X,Ans,X)))';
expectThrows('ROM rejects an oversized radical vinculum endpoint', RangeError,
  () => mp.generatedForExpression(oversizedRadical));

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
expectEqual('35:7B37 applies its byte-exact EF36h structural-depth test',
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
