'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const graph = require('./graph-coordinate.js');

let checks = 0;

function check(name, actual, expected) {
  assert.deepStrictEqual(actual, expected, name);
  checks += 1;
}

const localRomPath = path.join(__dirname, '..', 'rom.bin');
const localRom = fs.existsSync(localRomPath) ? fs.readFileSync(localRomPath) : null;

function romBytes(page, address, length) {
  const rom = localRom;
  const offset = page * 0x4000 + (address & 0x3fff);
  return rom.subarray(offset, offset + length).toString('hex');
}

function bcd(value) {
  return ((Math.floor(value / 10) << 4) | (value % 10)) & 0xff;
}

function op1(exponent, firstPair, secondPair, sign = 0, tail = 0x12) {
  return Uint8Array.of(
    sign,
    exponent,
    bcd(firstPair),
    bcd(secondPair),
    bcd(tail),
    0x34,
    0x56,
    0x78,
    0x90,
  );
}

function oracleAdd(bytes, index, amount, count) {
  let carry = 0;
  for (let offset = 0; offset < count; offset += 1) {
    const target = index - offset;
    const old = 10 * (bytes[target] >>> 4) + (bytes[target] & 15);
    const add = 10 * (amount >>> 4) + (amount & 15);
    const sum = old + add + carry;
    bytes[target] = bcd(sum % 100);
    carry = sum >= 100 ? 1 : 0;
    amount = 0;
    if (!carry) break;
  }
  return carry;
}

// Independent semantic transcription used for exhaustive comparison.
function oracleRound(source) {
  const bytes = Uint8Array.from(source);
  const exponent = bytes[1];
  if (exponent < 0x7f || (exponent === 0x7f && bytes[2] < 0x50)) {
    bytes.fill(0, 0, 9);
    bytes[1] = 0x80;
    return bytes;
  }
  if (exponent === 0x7f) {
    bytes[1] = 0x80;
    bytes[2] = 0x10;
    bytes[3] = 0;
    return bytes;
  }
  const twoDigits = exponent === 0x81;
  const carry = oracleAdd(bytes, twoDigits ? 3 : 2, twoDigits ? 0x50 : 0x05,
    twoDigits ? 2 : 1);
  if (carry) {
    bytes[1] = (exponent + 1) & 0xff;
    bytes[2] = 0x10;
    bytes[3] = 0;
    if (bytes[1] === 0) return 'overflow';
  }
  return bytes;
}

if (localRom !== null) {
  check('local ROM SHA-256', crypto.createHash('sha256').update(localRom).digest('hex'),
    '7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d');
  check('37:41DF–37:420E ROM body', romBytes(0x37, 0x41df, 0x30),
    '016b8f216d91b7cdf2413cc9016a8e21649137f5e5c5ebe7e1cd8f22e1cd8523f1300621738ecd8f22cd2942cd893ac9');
  check('37:4229–37:4259 rounding body', romBytes(0x37, 0x4229, 0x31),
    '3a7984d67f3827281e0602217b84fe023e5028043e05052bcd911cd0217a843610233600c3931e3a7a84fe5030eec3a41b');
  check('00:1BA4 `_OP1Set0` entry', romBytes(0, 0x1ba4, 6),
    '217884af18bb');
  check('00:1B65 OP-register digit setter', romBytes(0, 0x1b65, 0x1b),
    '36002336802377af1802af772377237723772377237723772377c9');
  check('38:7433 `_ConvOP1` body', romBytes(0x38, 0x7433, 0x40),
    '3a7a84b7cca41b2179843e839638ee47217b842809af2bed6723ed6710f7eb1ae60f6f26000e0a44cd73741b1a0e64e60fcd777401e803cd7374eb7223737bc9');
}

check('0.499999 rounds to zero', Array.from(graph.roundCoordinateOp1(
  op1(0x7f, 49, 99),
)), [0, 0x80, 0, 0, 0, 0, 0, 0, 0]);
check('zeroing preserves bytes after the TIFloat body', (() => {
  const extended = Uint8Array.of(...op1(0x7e, 99, 99), 0xaa, 0x55);
  return Array.from(graph.roundCoordinateOp1(extended).slice(9));
})(), [0xaa, 0x55]);
check('0.5 rounds upward', Array.from(graph.roundCoordinateOp1(
  op1(0x7f, 50, 0),
)).slice(0, 4), [0, 0x80, 0x10, 0]);
check('9.5 carries to 10', Array.from(graph.roundCoordinateOp1(
  op1(0x80, 95, 0),
)).slice(0, 4), [0, 0x81, 0x10, 0]);
check('99.5 carries to 100', Array.from(graph.roundCoordinateOp1(
  op1(0x81, 99, 50),
)).slice(0, 4), [0, 0x82, 0x10, 0]);
check('100-scale values receive the leading-byte bias', Array.from(
  graph.roundCoordinateOp1(op1(0x82, 12, 34)),
).slice(0, 4), [0, 0x82, 0x17, 0x34]);

let exhaustiveCases = 0;
for (const exponent of [0x00, 0x70, 0x7e, 0x7f, 0x80, 0x81, 0x82, 0x83, 0x84, 0xfe, 0xff]) {
  for (let first = 0; first < 100; first += 1) {
    for (let second = 0; second < 100; second += 1) {
      for (const sign of [0, 0x80]) {
        const input = op1(exponent, first, second, sign);
        const expected = oracleRound(input);
        if (expected === 'overflow') {
          assert.throws(() => graph.roundCoordinateOp1(input), error =>
            error instanceof graph.CoordinateConversionError && error.kind === 'overflow');
        } else {
          assert.deepStrictEqual(graph.roundCoordinateOp1(input), expected);
        }
        exhaustiveCases += 1;
      }
    }
  }
}
checks += 1;

check('conversion returns DE and its low byte in A', (() => {
  const result = graph.convOp1Magnitude(op1(0x82, 12, 34));
  return {a: result.a, de: result.de, binaryBytes: Array.from(result.op1.slice(2, 4))};
})(), {a: 123, de: 123, binaryBytes: [0, 123]});
check('conversion preserves the byte after its binary overlay', (() => {
  const result = graph.convOp1Magnitude(op1(0x82, 12, 34));
  return result.op1[4];
})(), 0x18);
assert.throws(() => graph.convOp1Magnitude(op1(0x84, 10, 0)), error =>
  error instanceof graph.CoordinateConversionError && error.kind === 'dimension');
checks += 1;

check('Y return bias wraps at one byte', graph.finishCoordinateOp1(
  op1(0x82, 20, 50), 'y',
).a, 0);

function adapterFor(output) {
  const calls = [];
  return {
    calls,
    load(value) { calls.push(['load', value]); },
    subtract(address) { calls.push(['subtract', address]); },
    multiply(address) { calls.push(['multiply', address]); },
    add(address) { calls.push(['add', address]); },
    exportOp1() { calls.push(['exportOp1']); return output; },
  };
}

const xAdapter = adapterFor(op1(0x80, 14, 90));
check('X core operand order', graph.executeCoordinateCore('x', 0x9000, xAdapter).a, 1);
check('X core calls', xAdapter.calls, [
  ['load', 0x9000], ['subtract', 0x8e6a], ['multiply', 0x9164],
  ['add', 0x8e73], ['exportOp1'],
]);

const yAdapter = adapterFor(op1(0x80, 14, 90));
check('Y result adds one', graph.executeCoordinateCore('y', 0x9009, yAdapter).a, 2);
check('Y core calls', yAdapter.calls, [
  ['load', 0x9009], ['subtract', 0x8f6b], ['multiply', 0x916d],
  ['exportOp1'],
]);

console.log(`graph-coordinate: ${checks} checks passed; ${exhaustiveCases} raw OP1 cases compared`);
