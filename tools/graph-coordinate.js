'use strict';

// ROM-derived model of the final graph coordinate conversion steps in
// TI-84 Plus OS 2.55MP. Addresses use physical-page notation.

const AXES = Object.freeze({
  x: Object.freeze({
    entry: '37:41EB',
    baseAddress: 0x8e6a,
    multiplierAddress: 0x9164,
    originAddress: 0x8e73,
    resultBias: 0,
  }),
  y: Object.freeze({
    entry: '37:41DF',
    baseAddress: 0x8f6b,
    multiplierAddress: 0x916d,
    originAddress: null,
    resultBias: 1,
  }),
});

class CoordinateConversionError extends RangeError {
  constructor(kind, message) {
    super(message);
    this.name = 'CoordinateConversionError';
    this.kind = kind;
  }
}

function assertBytes(value, minimumLength = 9) {
  if (!(value instanceof Uint8Array) && !Buffer.isBuffer(value)) {
    throw new TypeError('OP1 must be a Uint8Array or Buffer');
  }
  if (value.length < minimumLength) {
    throw new RangeError(`OP1 must contain at least ${minimumLength} bytes`);
  }
}

function isPackedBcd(byte) {
  return (byte >>> 4) <= 9 && (byte & 0x0f) <= 9;
}

function assertCoordinateFloat(op1) {
  assertBytes(op1);
  for (let index = 2; index < 9; index += 1) {
    if (!isPackedBcd(op1[index])) {
      throw new RangeError(`OP1 byte ${index} is not packed BCD`);
    }
  }
}

function packedBcdValue(byte) {
  return 10 * (byte >>> 4) + (byte & 0x0f);
}

function packedBcdByte(value) {
  return ((Math.floor(value / 10) << 4) | (value % 10)) & 0xff;
}

function addPackedBcd(op1, index, addend, byteCount) {
  let carry = 0;
  for (let offset = 0; offset < byteCount; offset += 1) {
    const target = index - offset;
    const sum = packedBcdValue(op1[target]) + packedBcdValue(addend) + carry;
    op1[target] = packedBcdByte(sum % 100);
    carry = sum >= 100 ? 1 : 0;
    addend = 0;
    if (carry === 0) {
      break;
    }
  }
  return carry;
}

function setOp1Zero(op1) {
  op1.fill(0, 0, Math.min(11, op1.length));
  op1[1] = 0x80;
}

// Translate 37:4229–37:4259 byte for byte at the OP1 data boundary. The
// routine rounds magnitudes below 100 to the nearest integer with .5 upward.
// For exponents 0x82 and above it instead applies the ROM's out-of-frame bias
// to the leading BCD byte. The sign/type byte is never read.
function roundCoordinateOp1(source) {
  assertCoordinateFloat(source);
  const op1 = Uint8Array.from(source);
  const exponent = op1[1];

  if (exponent < 0x7f) {
    setOp1Zero(op1);
    return op1;
  }

  if (exponent === 0x7f) {
    if (op1[2] < 0x50) {
      setOp1Zero(op1);
      return op1;
    }
    op1[2] = 0x10;
    op1[3] = 0;
    op1[1] = 0x80;
    return op1;
  }

  const decimalDigits = (exponent - 0x7f) & 0xff;
  const addend = decimalDigits === 2 ? 0x50 : 0x05;
  const index = decimalDigits === 2 ? 3 : 2;
  const byteCount = decimalDigits === 2 ? 2 : 1;
  if (addPackedBcd(op1, index, addend, byteCount) === 0) {
    return op1;
  }

  op1[2] = 0x10;
  op1[3] = 0;
  op1[1] = (exponent + 1) & 0xff;
  if (op1[1] === 0) {
    throw new CoordinateConversionError(
      'overflow',
      '37:4229 reaches the page-zero overflow handler',
    );
  }
  return op1;
}

function mantissaDigits(op1) {
  const digits = [];
  for (let index = 2; index < 9; index += 1) {
    digits.push(op1[index] >>> 4, op1[index] & 0x0f);
  }
  return digits;
}

// `_ConvOP1` at 38:7433 ignores the sign byte and converts at most four
// integer digits. It writes the binary word to DE and returns E in A.
function convOp1Magnitude(source) {
  assertCoordinateFloat(source);
  const op1 = Uint8Array.from(source);
  if (op1[2] === 0) {
    setOp1Zero(op1);
  }
  if (op1[1] > 0x83) {
    throw new CoordinateConversionError(
      'dimension',
      '_ConvOP1 reaches the page-zero dimension-error handler',
    );
  }

  const integerDigits = Math.max(0, op1[1] - 0x7f);
  const digits = mantissaDigits(op1);
  let de = 0;
  for (let index = 0; index < integerDigits; index += 1) {
    de = de * 10 + digits[index];
  }
  de &= 0xffff;

  // 38:746E–38:7470 stores the binary result over OP1 mantissa bytes 1–2.
  op1[3] = de >>> 8;
  op1[4] = de & 0xff;
  return Object.freeze({a: de & 0xff, de, op1});
}

function finishCoordinateOp1(source, axis = 'x') {
  const descriptor = AXES[axis];
  if (descriptor === undefined) {
    throw new RangeError(`unknown graph axis: ${axis}`);
  }
  const rounded = roundCoordinateOp1(source);
  const converted = convOp1Magnitude(rounded);
  return Object.freeze({
    a: (converted.a + descriptor.resultBias) & 0xff,
    de: converted.de,
    op1: converted.op1,
  });
}

// Execute the operand order at 37:41F2 with a supplied FP adapter. This keeps
// the page-37 translation exact without claiming that host binary64 arithmetic
// reproduces page-zero BCD subtraction, multiplication, and addition.
function executeCoordinateCore(axis, input, fp) {
  const descriptor = AXES[axis];
  if (descriptor === undefined) {
    throw new RangeError(`unknown graph axis: ${axis}`);
  }
  for (const method of ['load', 'subtract', 'multiply', 'exportOp1']) {
    if (fp === null || typeof fp !== 'object' || typeof fp[method] !== 'function') {
      throw new TypeError(`FP adapter must implement ${method}()`);
    }
  }

  fp.load(input);
  fp.subtract(descriptor.baseAddress);
  fp.multiply(descriptor.multiplierAddress);
  if (descriptor.originAddress !== null) {
    if (typeof fp.add !== 'function') {
      throw new TypeError('FP adapter must implement add() for the X path');
    }
    fp.add(descriptor.originAddress);
  }
  return finishCoordinateOp1(fp.exportOp1(), axis);
}

module.exports = Object.freeze({
  AXES,
  CoordinateConversionError,
  convOp1Magnitude,
  executeCoordinateCore,
  finishCoordinateOp1,
  roundCoordinateOp1,
});
