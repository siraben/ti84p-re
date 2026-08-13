// Executable translations of closed TI-84 Plus OS 2.55MP MathPrint routines.
//
// These functions mirror byte-decoded page-0x39 logic. They deliberately stop
// at unresolved boundaries instead of filling them with renderer heuristics.
// `layout` is the ROM-derived web/mathprint/layout.json artifact.
(function install(factory) {
  const api = factory();
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof globalThis !== 'undefined') globalThis.MathPrintRomEngine = api;
})(function buildRomEngine() {
  'use strict';

  const byte = (value, label) => {
    if (!Number.isInteger(value) || value < 0 || value > 0xff)
      throw new RangeError(`${label} must be an unsigned byte`);
    return value;
  };

  function requireLayout(layout) {
    if (!layout || !Array.isArray(layout.classes) || !Array.isArray(layout.descriptors))
      throw new TypeError('expected a decoded MathPrint layout artifact');
    return layout;
  }

  // 39:4C27 reads WORD[39:5E45 + 2*class]. layout.json has already performed
  // that ROM-table read, but this lookup retains and validates the same ABI.
  function handlerRecord(layout, layoutClass) {
    requireLayout(layout);
    byte(layoutClass, 'layout class');
    const record = layout.classes.find(item => item.cls === layoutClass);
    if (!record || !Number.isInteger(record.ptr))
      throw new RangeError(`layout class 0x${layoutClass.toString(16)} is absent`);
    if (!Array.isArray(record.items) || record.rows !== record.items.length)
      throw new RangeError(`layout class 0x${layoutClass.toString(16)} has no decoded record`);
    return record;
  }

  // 39:4DCA skips row_count, row cell-count bytes, row-action bytes, and the
  // preceding packed D:E cells. Return both the decoded row and its ROM offsets.
  function handlerRow(layout, layoutClass, rowIndex) {
    const record = handlerRecord(layout, layoutClass);
    byte(rowIndex, 'row index');
    if (rowIndex >= record.rows)
      throw new RangeError(`row ${rowIndex} is outside class 0x${layoutClass.toString(16)}`);
    const priorCells = record.items.slice(0, rowIndex)
      .reduce((sum, row) => sum + row.count, 0);
    const row = record.items[rowIndex];
    return {
      layoutClass,
      recordAddress: record.ptr,
      rowIndex,
      countAddress: record.ptr + 1 + rowIndex,
      actionAddress: record.ptr + 1 + record.rows + rowIndex,
      cellsAddress: record.ptr + 1 + 2 * record.rows + 2 * priorCells,
      count: row.count,
      action: row.action,
      cells: row.cells.map(cell => cell.slice()),
    };
  }

  // 39:4F1A. A null result is the routine's carry-set return.
  function mapDirectGlyph(d, e) {
    byte(d, 'cell D');
    byte(e, 'cell E');
    if (d === 0xfc && e >= 0x3c && e < 0x41) return e - 0x3c + 5;
    if (d === 0xfe && e >= 0x7d && e < 0x82) return e - 0x7d;
    if (e === 0x42 && d < 0x0a) return d;
    return null;
  }

  function delimiterFamily(layout, d, e) {
    requireLayout(layout);
    // 39:6675 scans the ten cells following the records at 39:62C8, 62DF,
    // and 62F6. Those are classes 17h, 18h, and 19h in the extracted table.
    for (const layoutClass of [0x17, 0x18, 0x19]) {
      const record = handlerRecord(layout, layoutClass);
      const cells = record.items[0].cells;
      const index = cells.findIndex(cell => cell[0] === d && cell[1] === e);
      if (index >= 0) return { layoutClass, index };
    }
    return null;
  }

  // The non-prefix index arithmetic in _KeyToString at 01:6D10. A null index
  // is an explicit prefix/control branch whose remaining interpreter is open.
  function keyToStringIndex(d, e) {
    byte(d, 'cell D');
    byte(e, 'cell E');
    if ([0xff, 0xfe, 0xfc, 0xfb].includes(d))
      return { index: null, branch: 'prefix dispatch' };
    if (e >= 0x5a) return { index: null, branch: 'control dispatch' };
    if (e === 0x1f) return { index: (0x50 + d) & 0xff, branch: 'E=1F' };
    if (e >= 0x40) {
      if (e === 0x59) return { index: (0x61 + d) & 0xff, branch: 'E=59' };
      if (e === 0x40 && d === 0x10)
        return { index: null, branch: 'special literal at 01:6F4D' };
      if (e === 0x4c) return { index: (0x5f + d) & 0xff, branch: 'E=4C' };
      const adjusted = e === 0x56 || e === 0x42
        ? (e + 0x16 + d - 0x1b - 0x10) & 0xff
        : (e - 0x1b - 0x10) & 0xff;
      return { index: adjusted <= 0x64 ? adjusted : 0x13,
               branch: e === 0x56 || e === 0x42 ? 'E=56/42 adjusted' : 'E>=40 adjusted' };
    }
    const adjusted = (e - 0x10) & 0xff;
    return { index: adjusted <= 0x64 ? adjusted : 0x13, branch: 'ordinary E-10' };
  }

  // 39:4E8E branch selection, ending at the known output boundary.
  function classifyCell(layout, d, e) {
    byte(d, 'cell D');
    byte(e, 'cell E');
    if (d === 0x1f) return { kind: 'cursorMarker', d, e, routine: '39:4E93' };
    if (d === 0x82)
      return { kind: 'indexedString', d, e, index: (e - 0x3e) & 0xff, routine: '39:4EBF' };
    const delimiter = delimiterFamily(layout, d, e);
    if (delimiter)
      return { kind: 'fixedDelimiter', d, e, ...delimiter, routine: '39:6675' };
    const glyph = mapDirectGlyph(d, e);
    if (glyph !== null)
      return { kind: 'directGlyph', d, e, glyph, routine: '39:4F1A' };
    if (d === 0xff) return { kind: 'skip', d, e, routine: '39:4EF3' };
    if (e === 0x55) return { kind: 'specialAction', d, e, routine: '39:4EFD' };
    if (d === 0xfb && e === 0xc8)
      return { kind: 'conditionalInlineString', d, e, condition: 'bit 0,H', routine: '39:6B66' };
    if (d === 0xfb && [0xca, 0xcb, 0xd6, 0xd7, 0xd8].includes(e))
      return { kind: 'inlineString', d, e, routine: '39:6B66' };
    return { kind: 'keyString', d, e, ...keyToStringIndex(d, e), routine: '01:6D10' };
  }

  // 39:4DE6 walks a selected row in slot order and calls 39:4E8E for each cell.
  function emitHandlerRow(layout, layoutClass, rowIndex) {
    const row = handlerRow(layout, layoutClass, rowIndex);
    return {
      ...row,
      emissions: row.cells.map(([d, e], slot) => ({
        slot,
        address: row.cellsAddress + 2 * slot,
        cell: [d, e],
        output: classifyCell(layout, d, e),
      })),
    };
  }

  function descriptor(layout, address) {
    requireLayout(layout);
    const record = layout.descriptors.find(item => item.addr === address);
    if (!record) throw new RangeError(`descriptor 39:${address.toString(16)} is absent`);
    const columns = record.cols_rows >> 8;
    const rows = record.cols_rows & 0xff;
    if (record.cells.length !== rows * columns)
      throw new RangeError(`descriptor 39:${address.toString(16)} has inconsistent cells`);
    return { ...record, columns, rows };
  }

  // Closed branches at 39:69C8. Kinds >=3 require the still-untranslated
  // family-shape comparisons at ram:025E/0254, so they fail explicitly.
  function selectDescriptor(layout, kind) {
    byte(kind, 'template kind');
    const nibble = kind & 0x0f;
    if (nibble === 0) return { kind: 'descriptor', descriptor: descriptor(layout, 0x686f) };
    if (nibble === 1) return { kind: 'descriptor', descriptor: descriptor(layout, 0x6880) };
    if (nibble === 2) return { kind: 'measuredFraction', routine: '39:6A8A' };
    return { kind: 'unresolvedDescriptorFamily', templateKind: nibble,
             missing: 'ram:025E/0254 family-shape predicates' };
  }

  // 39:6A00 reads the nine-byte descriptor ABI. The two increments of E and
  // one increment of D are preserved as low/high pen-register adjustments.
  function descriptorState(layout, address) {
    const record = descriptor(layout, address);
    return {
      descriptorAddress: address,
      penBaseLow: ((record.base_yx & 0xff) + 2) & 0xff,
      penBaseHigh: (((record.base_yx >> 8) & 0xff) + 1) & 0xff,
      boxWord: record.box_yx,
      rowHeight: record.row_height,
      rows: record.rows,
      columns: record.columns,
      cellPointer: record.cell_ptr,
      cells: record.cells.map(cell => cell.slice()),
    };
  }

  // 39:683D. The names low/high avoid imposing screen-axis terminology on the
  // 0x86D7/0x86D8 register pair; the Z80 returns H=high and L=low.
  function descriptorPen(state, row, column) {
    byte(row, 'descriptor row');
    byte(column, 'descriptor column');
    if (row >= state.rows || column >= state.columns)
      throw new RangeError(`descriptor cell ${row},${column} is outside ${state.rows}x${state.columns}`);
    const low = (state.penBaseLow + (state.rowHeight + 2) * row) & 0xff;
    const high = (state.penBaseHigh + 7 * column) & 0xff;
    return { low, high, hl: (high << 8) | low };
  }

  // 39:6A27..6A89: columns advance inside rows, and the cell pointer advances
  // by two bytes for each emitted D:E pair.
  function emitDescriptor(layout, address) {
    const state = descriptorState(layout, address);
    const emissions = [];
    for (let row = 0; row < state.rows; row++) {
      for (let column = 0; column < state.columns; column++) {
        const index = row * state.columns + column;
        const [d, e] = state.cells[index];
        emissions.push({
          index,
          row,
          column,
          address: state.cellPointer + 2 * index,
          pen: descriptorPen(state, row, column),
          cell: [d, e],
          output: classifyCell(layout, d, e),
        });
      }
    }
    return { state, emissions };
  }

  // 39:6B1C. DJNZ with zero would loop 256 times; callers pass n>=1.
  function fractionEndpoint(count, yTop) {
    byte(count, 'fraction cell count');
    byte(yTop, 'fraction y top');
    if (count === 0) throw new RangeError('fraction cell count must be at least one');
    const left = (0x1b + 7 * count) & 0xff;
    return { left, right: (left + 4) & 0xff, top: yTop, bottom: (yTop + 6) & 0xff };
  }

  // 39:5949 and the INC sequence at 39:51D9. Only class 06 slots 0..2
  // receive the extra row increment.
  function multiArgumentRowStep(layoutClass, slot) {
    byte(layoutClass, 'layout class');
    byte(slot, 'argument slot');
    return layoutClass === 0x06 && slot <= 2 ? 2 : 1;
  }

  // 34:5E98..5EA6. The preceding 5DD1/5DEF calls clip the object coordinate
  // against the active display bounds. The closed tail converts the accepted
  // coordinate to page-4 graph coordinates, selects point-on mode D=1, calls
  // 04:4155, and restores graph state through the surrounding bjumps.
  function settledPointOperation(x, y) {
    byte(x, 'settled point x');
    byte(y, 'settled point y');
    if (x >= 0x60 || y >= 0x40) return null;
    return {
      kind: 'point',
      x,
      y,
      registers: { b: x, c: 0x3f - y, d: 1 },
      routine: '34:5E98–5EA6 → 04:4155',
    };
  }

  function settledViewport(viewport) {
    if (!viewport || typeof viewport !== 'object')
      throw new TypeError('settled viewport is required');
    const result = {};
    for (const field of ['xOrigin', 'yOrigin', 'xMax', 'yMax', 'xClip', 'yClip'])
      result[field] = byte(viewport[field], `settled viewport ${field}`);
    return result;
  }

  const clipRange = (first, last, origin, clip, max) => {
    let low = Math.min(first, last) + origin - clip;
    let high = Math.max(first, last) + origin - clip;
    if (high < 0 || low > max) return null;
    low = Math.max(0, low);
    high = Math.min(max, high);
    return [low, high];
  };

  // 34:5D96..5DA5 -> ram:3573 -> 04:431D. HL is the fixed x coordinate;
  // BC and DE are inclusive y endpoints. Page 4 converts y to 63-y before its
  // line primitive, so the returned graph endpoints preserve that orientation.
  function settledVerticalOperation(x, y1, y2, viewport) {
    byte(x, 'settled vertical x');
    byte(y1, 'settled vertical y1');
    byte(y2, 'settled vertical y2');
    const v = settledViewport(viewport);
    const graphX = x + v.xOrigin - v.xClip;
    if (graphX < 0 || graphX > v.xMax) return null;
    const ys = clipRange(y1, y2, v.yOrigin, v.yClip, v.yMax);
    if (!ys) return null;
    return {
      kind: 'line', axis: 'vertical',
      from: { x: graphX, y: 0x3f - ys[0] },
      to: { x: graphX, y: 0x3f - ys[1] },
      routine: '34:5D96–5DA5 → 04:431D',
    };
  }

  // 34:5DA6..5DBD -> ram:3579 -> 04:4382. The wrapper swaps axes before
  // applying the same viewport family, yielding an inclusive horizontal line.
  function settledHorizontalOperation(x1, x2, y, viewport) {
    byte(x1, 'settled horizontal x1');
    byte(x2, 'settled horizontal x2');
    byte(y, 'settled horizontal y');
    const v = settledViewport(viewport);
    const graphY = y + v.yOrigin - v.yClip;
    if (graphY < 0 || graphY > v.yMax) return null;
    const xs = clipRange(x1, x2, v.xOrigin, v.xClip, v.xMax);
    if (!xs) return null;
    return {
      kind: 'line', axis: 'horizontal',
      from: { x: xs[0], y: 0x3f - graphY },
      to: { x: xs[1], y: 0x3f - graphY },
      routine: '34:5DA6–5DBD → 04:4382',
    };
  }

  // Word table at 34:7012, dispatched through 34:700C -> 34:6105. Kinds 6
  // and 7 intentionally share one handler. This identifies the next Z80 entry;
  // it does not assign semantic construct names before each record ABI is closed.
  const SETTLED_OBJECT_HANDLERS = Object.freeze([
    0x6d0c, 0x706a, 0x70b8, 0x702c, 0x7133, 0x70a0, 0x70e2,
    0x70e2, 0x7087, 0x7102, 0x717e, 0x70c1, 0x71c6,
  ]);

  function settledObjectHandler(kind) {
    byte(kind, 'settled object kind');
    if (kind >= SETTLED_OBJECT_HANDLERS.length)
      throw new RangeError(`settled object kind ${kind} is outside the 34:7012 table`);
    return {
      kind,
      handler: SETTLED_OBJECT_HANDLERS[kind],
      tableAddress: 0x7012 + 2 * kind,
      routine: '34:700C → 34:6105',
    };
  }

  // 34:5935 scans the 16 triples at 34:594D. The routine receives the
  // two-byte source token in D:E order, while each table triple stores E,D,type.
  const SETTLED_STRUCTURAL_TOKEN_TYPES = Object.freeze([
    [0x00,0xf0,0x2a], [0x00,0xf1,0x24], [0xef,0x36,0x2c],
    [0x00,0x06,0x2b], [0xef,0x2e,0x20], [0xef,0x2f,0x20],
    [0x00,0x06,0x2b], [0xef,0x2b,0x2b], [0xef,0x33,0x29],
    [0xef,0x34,0x28], [0x00,0x24,0x22], [0x00,0x25,0x23],
    [0x00,0xbf,0x25], [0x00,0xc1,0x26], [0x00,0xbc,0x27],
    [0x00,0xb2,0x21],
  ]);

  function settledStructuralTokenType(prefix, token) {
    byte(prefix, 'settled structural token prefix');
    byte(token, 'settled structural token');
    const row = SETTLED_STRUCTURAL_TOKEN_TYPES.find(
      item => item[0] === prefix && item[1] === token);
    return row ? row[2] : null;
  }

  // 34:5996 computes 34:59AC + 5*(type-1Fh). Retain address-based byte
  // names until each constructor's use of the metadata has been translated.
  const SETTLED_RECORD_METADATA = Object.freeze([
    [0x00,0x01,0x02,0x00,0x00], [0x02,0x01,0x02,0x00,0x00],
    [0x03,0x01,0x00,0x00,0x00], [0x04,0x03,0x04,0x01,0x02],
    [0x04,0x02,0x01,0x03,0x00], [0x01,0x01,0x02,0x00,0x00],
    [0x03,0x01,0x00,0x00,0x00], [0x03,0x01,0x00,0x00,0x00],
    [0x03,0x01,0x00,0x00,0x00], [0x04,0x02,0x01,0x00,0x00],
    [0x04,0x04,0x01,0x02,0x03], [0x01,0x01,0x00,0x00,0x00],
    [0x06,0x10,0xda,0xdb,0x9c],
  ].map(Object.freeze));

  function settledRecordMetadata(renderType) {
    byte(renderType, 'settled render type');
    if (renderType < 0x1f || renderType > 0x2b)
      throw new RangeError('settled record metadata type must be 1Fh..2Bh');
    return SETTLED_RECORD_METADATA[renderType - 0x1f].slice();
  }

  // Settled records store an ID at +0, a type byte at +2, eight unaligned
  // little-endian words at +3..+11h, and a final byte at +13h. Keep the word
  // names address-based until each type-specific interpretation is closed.
  function decodeSettledRecord(header) {
    if (!Array.isArray(header) && !(header instanceof Uint8Array))
      throw new TypeError('settled record header must be an array of bytes');
    if (header.length !== 0x14)
      throw new RangeError('settled record header must contain 20 bytes');
    const bytes = Array.from(header, (value, index) =>
      byte(value, `settled record +${index.toString(16)}`));
    const word = offset => bytes[offset] | (bytes[offset + 1] << 8);
    return {
      id: word(0), type: bytes[2],
      word03: word(3), word05: word(5), word07: word(7), word09: word(9),
      word0B: word(0x0b), word0D: word(0x0d), word0F: word(0x0f),
      word11: word(0x11), byte13: bytes[0x13],
    };
  }

  const SETTLED_RENDER_HANDLERS = Object.freeze({
    0x1f: 0x6143, 0x20: 0x620a, 0x21: 0x6347, 0x22: 0x622f,
    0x23: 0x640e, 0x24: 0x6315, 0x25: 0x637e, 0x26: 0x63ad,
    0x27: 0x62a1, 0x28: 0x63b2, 0x29: 0x6504, 0x2a: 0x6375,
    0x2b: 0x65aa,
  });

  function settledRenderHandler(renderType) {
    byte(renderType, 'settled render type');
    const handler = SETTLED_RENDER_HANDLERS[renderType];
    if (handler === undefined)
      throw new RangeError(`settled render type 0x${renderType.toString(16)} is outside the 34:6119 table`);
    return {
      renderType,
      handler,
      tableAddress: 0x6119 + 2 * (renderType - 0x1f),
      routine: '34:6105 → 34:6119',
    };
  }

  function decodedSettledNode(input) {
    if (!input || typeof input !== 'object')
      throw new TypeError('settled record node must be an object');
    const decoded = input.header ? decodeSettledRecord(input.header) : input;
    const type = decoded.type === undefined ? decoded.render_type : decoded.type;
    const id = decoded.id === undefined ? decoded.record_id : decoded.id;
    const normalized = {...decoded, id, type};
    for (const field of [
      'id', 'type', 'word03', 'word05', 'word07', 'word09', 'word0B',
      'word0D', 'word0F', 'word11', 'byte13',
    ]) {
      if (!Number.isInteger(normalized[field]) || normalized[field] < 0 || normalized[field] > 0xffff)
        throw new RangeError(`settled record field ${field} is missing or invalid`);
    }
    byte(normalized.type, 'settled record type');
    byte(normalized.byte13, 'settled record byte13');
    const childIds = Array.from(input.childIds || input.child_ids || normalized.childIds || [], value => {
      if (!Number.isInteger(value) || value < 0 || value > 0xffff)
        throw new RangeError('settled child ID must be an unsigned word');
      return value;
    });
    const payload = Array.from(input.payload || normalized.payload || [], (value, index) =>
      byte(value, `settled record payload ${index}`));
    return {...normalized, childIds, payload};
  }

  // 34:5D1A and 34:5D07 emit two endpoint points before either a straight
  // five-row segment or two inner points plus a vertical segment. The selected
  // current record's +5 word supplies the height. Keep the two wrapper modes
  // separate because their outer and inner x coordinates cross over.
  function settledCompoundOperations(mode, x, y, height) {
    if (mode !== 'open' && mode !== 'close')
      throw new RangeError('settled compound mode must be open or close');
    byte(x, 'settled compound x');
    byte(y, 'settled compound y');
    byte(height, 'settled compound height');
    if (height < 3)
      throw new RangeError('settled compound height must be at least three');
    const routine = mode === 'open' ? '34:5D1A' : '34:5D07';
    const outerX = x + (mode === 'open' ? 3 : 1);
    const operations = [
      {kind:'point', x:outerX, y, routine:`${routine} → 34:5E85`},
      {kind:'point', x:outerX, y:y + height - 1, routine:`${routine} → 34:5E85`},
    ];
    if (height === 5) {
      operations.push({
        kind:'line', axis:'vertical',
        from:{x:x + 2,y:y + 1}, to:{x:x + 2,y:y + height - 2},
        routine:`${routine} → 34:5D96`,
      });
      return operations;
    }
    operations.push(
      {kind:'point', x:x + 2, y:y + 1, routine:`${routine} → 34:5E85`},
      {kind:'point', x:x + 2, y:y + height - 2, routine:`${routine} → 34:5E85`},
      {
        kind:'line', axis:'vertical',
        from:{x:x + (mode === 'open' ? 1 : 3),y:y + 2},
        to:{x:x + (mode === 'open' ? 1 : 3),y:y + height - 3},
        routine:`${routine} → 34:5D96`,
      },
    );
    return operations;
  }

  const addPointOrigin = (operation, origin) => ({
    ...operation, x: operation.x + origin.x, y: operation.y + origin.y,
  });

  function addOperationOrigin(operation, origin) {
    if (operation.kind === 'line') return {
      ...operation,
      from:{x:operation.from.x + origin.x, y:operation.from.y + origin.y},
      to:{x:operation.to.x + origin.x, y:operation.to.y + origin.y},
    };
    if (operation.kind === 'point' || operation.kind === 'glyph' ||
        operation.kind === 'bitmap' || operation.kind === 'glyph-run')
      return addPointOrigin(operation, origin);
    return {...operation, origin:{...origin}};
  }

  function matrixChildCount(record) {
    // 33:4F23 reads the dimensions at +12/+13, multiplies them through the
    // 1EF6h service, and returns product+1. 34:65D0 decrements that loop bound.
    const rows = record.word11 >> 8;
    const columns = record.byte13;
    const count = rows * columns;
    if (!count || count > 0xff)
      throw new RangeError(`matrix dimensions ${rows}x${columns} are invalid`);
    return count;
  }

  // Execute structural render records as a graph. Child words following a
  // parent header are IDs; this map performs the same logical resolution as
  // 34:6CCD -> 34:4B05 -> 34:4A83. Recursive child origins come only from the
  // selected child's +0Bh/+0Dh words, matching 34:6BCD/6BFD.
  //
  // Leaf records are outside the 1Fh..2Bh structural table. A caller may supply
  // renderLeaf(record, context) to translate their object/glyph representation;
  // otherwise the executor retains an explicit leaf operation.
  function executeSettledRecordGraph(inputs, rootId, options = {}) {
    if (!Array.isArray(inputs))
      throw new TypeError('settled record graph must be an array');
    if (!Number.isInteger(rootId) || rootId < 0 || rootId > 0xffff)
      throw new RangeError('settled graph root ID must be an unsigned word');
    const records = new Map();
    for (const input of inputs) {
      const record = decodedSettledNode(input);
      if (records.has(record.id))
        throw new RangeError(`duplicate settled record ID 0x${record.id.toString(16)}`);
      records.set(record.id, record);
    }
    if (!records.has(rootId))
      throw new RangeError(`settled root ID 0x${rootId.toString(16)} is absent`);

    const output = [];
    const active = new Set();
    const state = {depth: options.depth === undefined ? 1 : byte(options.depth, 'settled depth')};

    const child = (record, index) => {
      const id = record.childIds[index - 1];
      if (id === undefined)
        throw new RangeError(`record 0x${record.id.toString(16)} has no child ${index}`);
      const result = records.get(id);
      if (!result)
        throw new RangeError(`child ID 0x${id.toString(16)} is absent from the graph`);
      return result;
    };

    const emit = (record, origin, operation) => {
      const absolute = addOperationOrigin(operation, origin);
      if (options.acceptOperation && !options.acceptOperation(absolute, record, state)) return;
      output.push({...absolute, recordId:record.id, recordType:record.type, depth:state.depth});
    };

    const compound = (record, origin, mode, x, y, current) => {
      for (const operation of settledCompoundOperations(mode, x, y, current.word05))
        emit(record, origin, operation);
    };

    const visit = (record, origin) => {
      if (active.has(record.id))
        throw new RangeError(`cycle through settled record ID 0x${record.id.toString(16)}`);
      active.add(record.id);

      const renderChild = index => {
        const next = child(record, index);
        visit(next, {x:origin.x + next.word0B, y:origin.y + next.word0D});
      };
      const renderChildAt = (index, x, y) => {
        const next = child(record, index);
        visit(next, {x:origin.x + x, y:origin.y + y});
      };
      const emitChildLeaf = () => {
        const context = {origin:{...origin}, depth:state.depth};
        const controls = {
          emit: operation => emit(record, origin, operation),
          record: id => {
            if (!Number.isInteger(id) || id < 0 || id > 0xffff)
              throw new RangeError('settled record ID must be an unsigned word');
            const result = records.get(id);
            if (!result)
              throw new RangeError(`record ID 0x${id.toString(16)} is absent from the graph`);
            return result;
          },
          visit: (id, nestedOrigin) => {
            const result = records.get(id);
            if (!result)
              throw new RangeError(`record ID 0x${id.toString(16)} is absent from the graph`);
            if (!nestedOrigin || !Number.isInteger(nestedOrigin.x) ||
                !Number.isInteger(nestedOrigin.y))
              throw new RangeError('settled nested origin must contain integer x and y');
            visit(result, nestedOrigin);
          },
          state,
        };
        const operations = options.renderLeaf
          ? options.renderLeaf(record, context, controls)
          : [{kind:'leaf', objectType:record.type, routine:'34:660A object renderer'}];
        if (operations === undefined) return;
        if (!Array.isArray(operations))
          throw new TypeError('renderLeaf must return an array of operations or undefined');
        for (const operation of operations) emit(record, origin, operation);
      };

      if (record.type < 0x1f || record.type > 0x2b) {
        emitChildLeaf();
        active.delete(record.id);
        return;
      }

      switch (record.type) {
      case 0x1f:
        emit(record, origin, {
          kind:'unresolved-render',
          missing:'incoming A and the selected 34:6143 branch',
          routine:'34:6143',
        });
        break;
      case 0x20: {
        const first = child(record, 1), second = child(record, 2);
        renderChild(1);
        renderChild(2);
        emit(record, origin, settledFractionOperations(
          first.word07, second.word07, record.word0B)[2]);
        break;
      }
      case 0x21:
        for (const operation of settledAbsoluteOperations(record.word09, record.word07))
          if (operation.kind === 'line') emit(record, origin, operation);
        state.depth--;
        renderChild(1);
        state.depth++;
        break;
      case 0x22: {
        for (const operation of settledIntegralOperations(record.word07))
          emit(record, origin, operation);
        renderChild(1);
        renderChild(2);
        const third = child(record, 3);
        compound(record, origin, 'open', third.word0B - 6, third.word0D, third);
        state.depth--;
        renderChild(3);
        compound(record, origin, 'close', third.word0B + third.word07,
                 third.word0D, third);
        const fourth = child(record, 4);
        emit(record, origin, {
          kind:'glyph', code:0x64,
          x:third.word0B + third.word07 + 6, y:fourth.word0D,
          condition:'34:67C8 accepts child-4 vertical position',
          routine:'34:6298 → 34:6C35 → 34:6C37',
        });
        renderChild(4);
        state.depth++;
        break;
      }
      case 0x23: {
        const savedDepth = state.depth;
        state.depth = 1;
        emit(record, origin, {
          kind:'glyph', code:0x64, x:3, y:record.word0B - 6,
          condition:'34:6421 finds clipping bit 1 clear',
          routine:'34:641E → 34:642A → 34:6C32',
        });
        emit(record, origin, {
          kind:'glyph', code:0x64, x:1, y:record.word0B + 2,
          condition:'34:6431 accepts the vertical position',
          routine:'34:6431 → 34:6439 → 34:6C32',
        });
        const first = child(record, 1);
        emit(record, origin, {
          kind:'line', axis:'horizontal',
          from:{x:0,y:record.word0B}, to:{x:first.word07 + 4,y:record.word0B},
          routine:'34:644B → 34:5DA6',
        });
        state.depth = savedDepth;
        renderChild(1);
        const second = child(record, 2);
        compound(record, origin, 'open', first.word07 + 6, second.word0D, second);
        state.depth--;
        renderChild(2);
        const secondEnd = first.word07 + second.word07 + 12;
        compound(record, origin, 'close', secondEnd, second.word0D, second);
        emit(record, origin, {
          kind:'line', axis:'vertical',
          from:{x:secondEnd + 6,y:record.word0B - 3},
          to:{x:secondEnd + 6,y:record.word0B + 6},
          routine:'34:6472 → 34:5D96',
        });
        state.depth = 1;
        const repeatX = secondEnd + 9;
        renderChildAt(1, repeatX, record.word0B + 2);
        emit(record, origin, {
          kind:'glyph', code:0x3d, x:repeatX + first.word07,
          y:record.word0B + 2,
          condition:'34:64C1 finds clipping bit 1 clear',
          routine:'34:64CB → 34:6C37',
        });
        renderChild(3);
        state.depth = savedDepth;
        break;
      }
      case 0x24: {
        const first = child(record, 1), second = child(record, 2);
        const operations = settledNthRootOperations(
          first.word07, second.word07, record.word07, state.depth - 1);
        renderChild(1);
        state.depth--;
        emit(record, origin, operations[1]);
        emit(record, origin, operations[2]);
        emit(record, origin, operations[4]);
        renderChild(2);
        break;
      }
      case 0x25:
      case 0x26: {
        const savedDepth = state.depth;
        state.depth--;
        emit(record, origin, {
          kind:'glyph', code:record.type === 0x25 ? 0xdb : 0x1d,
          x:0, y:record.word07 - 7,
          condition:'34:67C8 accepts the vertical position',
          routine:record.type === 0x25 ? '34:637E → 34:6C37' : '34:63AD → 34:6C37',
        });
        state.depth = 1;
        renderChild(1);
        state.depth = savedDepth;
        break;
      }
      case 0x27: {
        const first = child(record, 1);
        const operations = settledRadicalOperations(
          record.word07, first.word07, state.depth - 1);
        state.depth--;
        emit(record, origin, operations[0]);
        emit(record, origin, operations[1]);
        emit(record, origin, operations[3]);
        renderChild(1);
        break;
      }
      case 0x28: {
        state.depth--;
        const y = record.word0B - (state.depth === 0 ? 3 : 2);
        emit(record, origin, {
          kind:'glyph-run', codes:[0x6c,0x6f,0x67], x:0, y,
          condition:'34:67C8 accepts the vertical position',
          routine:'34:63C7 → _KeyToString = 45CAh → 34:6C26',
        });
        const savedDepth = state.depth;
        state.depth = 1;
        renderChild(1);
        state.depth = savedDepth;
        const first = child(record, 1), second = child(record, 2);
        const openX = first.word07 + (state.depth === 0 ? 18 : 11);
        compound(record, origin, 'open', openX, 0, second);
        renderChild(2);
        state.depth++;
        compound(record, origin, 'close', second.word07 + second.word0B, 0, second);
        break;
      }
      case 0x29: {
        const savedDepth = state.depth;
        state.depth = 0;
        const first = child(record, 1), second = child(record, 2);
        const third = child(record, 3), fourth = child(record, 4);
        const sigmaX = Math.floor((Math.max(
          first.word07 + second.word07 + 4, third.word07) - 5) / 2);
        emit(record, origin, {
          kind:'glyph', code:0xc6, x:sigmaX, y:record.word0B - 3,
          condition:'34:67C8 accepts the vertical position',
          routine:'34:6517–651F → 34:6C37',
        });
        state.depth++;
        renderChild(1);
        emit(record, origin, {
          kind:'glyph', code:0x3d,
          x:first.word0B + first.word07, y:first.word0D + first.word09 - 2,
          condition:'34:6536 accepts the vertical position',
          routine:'34:653B–654F → 34:6C37',
        });
        renderChild(2);
        renderChild(3);
        state.depth = savedDepth - 1;
        compound(record, origin, 'open', fourth.word0B - 6, fourth.word0D, fourth);
        renderChild(4);
        compound(record, origin, 'close', fourth.word0B + fourth.word07,
                 fourth.word0D, fourth);
        state.depth++;
        break;
      }
      case 0x2a:
        renderChild(1);
        break;
      case 0x2b: {
        const h = record.word07 - 1;
        emit(record, origin, {kind:'line', axis:'vertical',
          from:{x:2,y:0}, to:{x:2,y:h}, routine:'34:65B4 → 34:5D96'});
        emit(record, origin, {kind:'point', x:3, y:0, routine:'34:65BD → 34:5E85'});
        emit(record, origin, {kind:'point', x:3, y:h, routine:'34:65C4 → 34:5E85'});
        state.depth--;
        const count = matrixChildCount(record);
        for (let index = 1; index <= count; index++) renderChild(index);
        state.depth++;
        const x = record.word09 - 4;
        emit(record, origin, {kind:'line', axis:'vertical',
          from:{x,y:0}, to:{x,y:h}, routine:'34:65F9 → 34:5D96'});
        emit(record, origin, {kind:'point', x:x - 1, y:0, routine:'34:6602 → 34:5E85'});
        emit(record, origin, {kind:'point', x:x - 1, y:h, routine:'34:6607 → 34:5E85'});
        break;
      }
      }
      active.delete(record.id);
    };

    const startOrigin = options.origin || {x:0,y:0};
    if (!Number.isInteger(startOrigin.x) || !Number.isInteger(startOrigin.y))
      throw new RangeError('settled graph origin must contain integer x and y');
    visit(records.get(rootId), {x:startOrigin.x,y:startOrigin.y});
    return output;
  }

  // The generic token renderer at 34:660A ultimately passes display codes to
  // 34:6C37. These are the single-byte TI-BASIC tokens whose settled spelling
  // is one glyph. Multi-glyph names and the remaining extended-token families
  // stay explicit until their ROM string paths are translated.
  const SETTLED_SINGLE_GLYPH_TOKENS = Object.freeze({
    0x04:0x1c,
    0x06:0x5b, 0x07:0x5d, 0x08:0x7b, 0x09:0x7d,
    0x0a:0x15, 0x0b:0x14, 0x0c:0x11, 0x0d:0x12, 0x0e:0x16,
    0x10:0x28, 0x11:0x29, 0x29:0x20, 0x2a:0x22, 0x2b:0x2c,
    0x30:0x30, 0x31:0x31, 0x32:0x32, 0x33:0x33, 0x34:0x34,
    0x35:0x35, 0x36:0x36, 0x37:0x37, 0x38:0x38, 0x39:0x39,
    0x3a:0x2e,
    0x41:0x41, 0x42:0x42, 0x43:0x43, 0x44:0x44, 0x45:0x45,
    0x46:0x46, 0x47:0x47, 0x48:0x48, 0x49:0x49, 0x4a:0x4a,
    0x4b:0x4b, 0x4c:0x4c, 0x4d:0x4d, 0x4e:0x4e, 0x4f:0x4f,
    0x50:0x50, 0x51:0x51, 0x52:0x52, 0x53:0x53, 0x54:0x54,
    0x55:0x55, 0x56:0x56, 0x57:0x57, 0x58:0x58, 0x59:0x59,
    0x5a:0x5a,
    0x6a:0x3d, 0x6b:0x3c, 0x6c:0x3e, 0x6d:0x17, 0x6e:0x19,
    0x6f:0x18, 0x70:0x2b, 0x71:0x2d, 0x82:0x2a, 0x83:0x2f,
    0xb0:0x1a,
  });

  function settledTokenGlyph(token) {
    byte(token, 'settled token');
    const code = SETTLED_SINGLE_GLYPH_TOKENS[token];
    return code === undefined ? null : code;
  }

  function settledLargeTokenAdvance(token) {
    byte(token, 'settled leaf token');
    if (settledTokenGlyph(token) === null)
      throw new RangeError(`token 0x${token.toString(16)} has no translated large glyph`);
    // The page-34 metrics pass counts the 5-pixel large cell plus its one-pixel
    // advance. The settled record stores ink width in +9h and cell extent in +7h.
    return 6;
  }

  // Closed token-to-record slice for the final abs( leaf program. 34:5935 maps
  // B2h to record type 21h. 34:4900 allocates the containing leaf, structural
  // record, and child leaf; 34:7393/7609 calculate their settled metrics.
  // IDs remain caller-selected because 34:4B36 draws them from the arena's
  // monotonically increasing counter.
  function constructSettledAbsoluteProgram(payload, firstId = 1) {
    if (!Array.isArray(payload) && !(payload instanceof Uint8Array))
      throw new TypeError('absolute child payload must be an array of token bytes');
    const tokens = Array.from(payload, (value, index) =>
      byte(value, `absolute child token ${index}`));
    if (!tokens.length)
      throw new RangeError('absolute child payload must not be empty');
    if (!Number.isInteger(firstId) || firstId < 1 || firstId > 0xfffd)
      throw new RangeError('absolute first record ID must leave three unsigned words');
    const renderType = settledStructuralTokenType(0x00, 0xb2);
    if (renderType !== 0x21)
      throw new Error('34:594D absolute token mapping is inconsistent');
    const leafWidth = tokens.reduce(
      (sum, token) => sum + settledLargeTokenAdvance(token), 0);
    if (leafWidth > 0xff - 12)
      throw new RangeError('absolute child width exceeds the translated byte-sized metric');
    const childId = firstId + 2;
    const structuralId = firstId + 1;
    const embedded = [0xef, renderType, structuralId & 0xff, structuralId >> 8,
                      0xef, 0x2d];
    return {
      entry_id:firstId,
      origin:{x:0,y:0},
      source:'34:4900, 34:5935, 34:7393, and 34:7609 translated construction',
      nodes:[
        {
          record_id:firstId, render_type:0, word03:firstId - 1,
          word05:7, word07:leafWidth + 12, word09:3,
          word0B:0, word0D:0, word0F:embedded.length,
          word11:embedded.length, byte13:embedded[0],
          child_ids:[], payload:embedded,
        },
        {
          record_id:structuralId, render_type:renderType, word03:firstId,
          word05:settledRecordMetadata(renderType)[1],
          word07:7, word09:leafWidth + 12,
          word0B:3, word0D:0, word0F:0, word11:1, byte13:0xef,
          child_ids:[childId], payload:[],
        },
        {
          record_id:childId, render_type:0, word03:structuralId,
          word05:7, word07:leafWidth, word09:3,
          word0B:6, word0D:0, word0F:tokens.length,
          word11:tokens.length, byte13:tokens[0],
          child_ids:[], payload:tokens,
        },
      ],
    };
  }

  function settledLeafMetrics(tokens, depth, font) {
    const payload = Array.from(tokens, (value, index) =>
      byte(value, `settled leaf token ${index}`));
    if (!payload.length)
      throw new RangeError('settled leaf payload must not be empty');
    let width = 0;
    for (let index = 0; index < payload.length; index++) {
      const token = payload[index];
      if (token === 0xef && payload[index + 1] === 0x1e) {
        width += 6;
        index++;
        continue;
      }
      const code = settledTokenGlyph(token);
      if (code === null)
        throw new RangeError(`token 0x${token.toString(16)} has no translated glyph`);
      if (depth === 0) {
        width += settledLargeTokenAdvance(token);
        continue;
      }
      const glyph = font && font.small && font.small.glyphs
        ? font.small.glyphs[code]
        : null;
      if (!glyph || !Number.isInteger(glyph.w) || glyph.w < 0)
        throw new RangeError(
          `small glyph 0x${code.toString(16)} requires ROM font metrics`);
      width += glyph.w;
    }
    return {payload, height:depth === 0 ? 7 : 5, width,
            baseline:depth === 0 ? 3 : 2};
  }

  function settledExpressionSpec(input, label = 'settled expression', active = new Set()) {
    if (Array.isArray(input) || input instanceof Uint8Array) {
      const tokens = Array.from(input, (value, index) =>
        byte(value, `${label} token ${index}`));
      if (!tokens.length) throw new RangeError(`${label} must not be empty`);
      return {kind:'tokens', tokens};
    }
    if (!input || typeof input !== 'object')
      throw new TypeError(`${label} must be token bytes or a structural expression`);
    if (active.has(input)) throw new RangeError(`${label} contains a cycle`);
    active.add(input);
    try {
      const kind = input.kind ||
        (Object.prototype.hasOwnProperty.call(input, 'base') ? 'power' : null);
      if (kind === 'tokens')
        return settledExpressionSpec(input.tokens, label, active);
      if (kind === 'sequence') {
        if (!Array.isArray(input.parts) || !input.parts.length)
          throw new RangeError(`${label} sequence must contain at least one part`);
        return {kind, parts:input.parts.map((part, index) =>
          settledExpressionSpec(part, `${label} part ${index}`, active))};
      }
      if (kind === 'power') {
        const base = Array.from(input.base || [], (value, index) =>
          byte(value, `${label} power base token ${index}`));
        if (!base.length) throw new RangeError(`${label} power base must not be empty`);
        return {
          kind, base,
          exponent:settledExpressionSpec(input.exponent, `${label} exponent`, active),
        };
      }
      if (kind === 'ePower' || kind === 'tenPower') return {
        kind,
        exponent:settledExpressionSpec(input.exponent, `${label} exponent`, active),
      };
      if (kind === 'logBase') return {
        kind,
        base:settledExpressionSpec(input.base, `${label} base`, active),
        argument:settledExpressionSpec(input.argument, `${label} argument`, active),
      };
      if (kind === 'radical') return {
        kind,
        radicand:settledExpressionSpec(
          input.radicand, `${label} radicand`, active),
      };
      if (kind === 'nthRoot') return {
        kind,
        index:settledExpressionSpec(input.index, `${label} index`, active),
        radicand:settledExpressionSpec(
          input.radicand, `${label} radicand`, active),
      };
      if (kind === 'fraction') return {
        kind,
        numerator:settledExpressionSpec(
          input.numerator, `${label} numerator`, active),
        denominator:settledExpressionSpec(
          input.denominator, `${label} denominator`, active),
      };
      if (kind === 'integral') return {
        kind,
        lower:settledExpressionSpec(input.lower, `${label} lower bound`, active),
        upper:settledExpressionSpec(input.upper, `${label} upper bound`, active),
        body:settledExpressionSpec(input.body, `${label} body`, active),
        variable:settledExpressionSpec(
          input.variable, `${label} variable`, active),
      };
      if (kind === 'nDeriv') return {
        kind,
        variable:settledExpressionSpec(
          input.variable, `${label} variable`, active),
        body:settledExpressionSpec(input.body, `${label} body`, active),
        value:settledExpressionSpec(
          input.value, `${label} evaluation value`, active),
      };
      if (kind === 'summation') return {
        kind,
        variable:settledExpressionSpec(
          input.variable, `${label} variable`, active),
        lower:settledExpressionSpec(input.lower, `${label} lower bound`, active),
        upper:settledExpressionSpec(input.upper, `${label} upper bound`, active),
        body:settledExpressionSpec(input.body, `${label} body`, active),
      };
      throw new RangeError(`${label} has unsupported kind ${JSON.stringify(kind)}`);
    } finally {
      active.delete(input);
    }
  }

  // 34:4900 allocates records as the token pass encounters each structural
  // object. 34:5935 maps the source tokens to render types, and 34:7393/7609
  // fill the record metrics. A leaf can therefore interleave ordinary tokens
  // with embedded structural IDs. This builder retains that allocation and
  // payload order so different translated object types can compose.
  function constructSettledExpressionProgram(input, firstId = 1, font = null) {
    const spec = settledExpressionSpec(input);
    if (!Number.isInteger(firstId) || firstId < 1 || firstId > 0xffff)
      throw new RangeError('settled first record ID must be an unsigned word');
    const nodes = [];
    let nextId = firstId;
    const allocate = () => {
      if (nextId > 0xffff)
        throw new RangeError('settled record construction exhausted unsigned IDs');
      return nextId++;
    };
    const checkedWord = (value, label) => {
      if (!Number.isInteger(value) || value < 0 || value > 0xffff)
        throw new RangeError(`${label} must fit an unsigned word`);
      return value;
    };
    const embedded = (renderType, recordId) =>
      [0xef, renderType, recordId & 0xff, recordId >> 8, 0xef, 0x2d];
    const leadingByte = expression => {
      if (expression.kind === 'tokens') return expression.tokens[0];
      if (expression.kind === 'sequence') return leadingByte(expression.parts[0]);
      if (expression.kind === 'power') return expression.base[0];
      if (expression.kind === 'ePower') return 0xef;
      if (expression.kind === 'tenPower') return 0xef;
      if (expression.kind === 'logBase') return 0xef;
      if (expression.kind === 'radical') return 0xef;
      if (expression.kind === 'nthRoot') return leadingByte(expression.index);
      if (expression.kind === 'fraction') return 0xef;
      if (expression.kind === 'integral') return 0xef;
      if (expression.kind === 'nDeriv') return 0xef;
      if (expression.kind === 'summation') return 0xef;
      throw new RangeError(`unsupported settled leading-byte kind ${expression.kind}`);
    };

    const newLeaf = parentId => {
      const leafId = allocate();
      const leaf = {
        record_id:leafId, render_type:0, word03:parentId,
        word05:0, word07:0, word09:0, word0B:0, word0D:0,
        word0F:0, word11:0, byte13:0, child_ids:[], payload:[],
      };
      nodes.push(leaf);
      return leaf;
    };

    const finishLeaf = leaf => {
      if (!leaf.payload.length)
        throw new RangeError('settled leaf construction produced an empty payload');
      checkedWord(leaf.payload.length, 'settled leaf payload length');
      leaf.word0F = leaf.payload.length;
      leaf.word11 = leaf.payload.length;
      leaf.byte13 = leaf.payload[0];
      return leaf;
    };

    const fillLeaf = (leaf, prepared, renderDepth) => {

      const addTokens = tokens => {
        const metrics = settledLeafMetrics(tokens, renderDepth, font);
        leaf.word05 = Math.max(leaf.word05, metrics.height);
        leaf.word07 = checkedWord(
          leaf.word07 + metrics.width, 'settled leaf width');
        leaf.word09 = Math.max(leaf.word09, metrics.baseline);
        leaf.payload.push(...metrics.payload);
      };
      const addStructural = structural => {
        structural.word03 = leaf.record_id;
        leaf.word05 = Math.max(leaf.word05, structural.word07);
        leaf.word07 = checkedWord(
          leaf.word07 + structural.word09, 'settled structural leaf width');
        leaf.word09 = Math.max(leaf.word09, structural.word0B);
        leaf.payload.push(...embedded(structural.render_type, structural.record_id));
      };

      const addPart = part => {
        if (part.kind === 'tokens') {
          addTokens(part.tokens);
          return;
        }
        if (part.kind === 'sequence') {
          for (const child of part.parts) addPart(child);
          return;
        }
        if (part.kind === 'embedded') {
          addStructural(part.structural);
          return;
        }
        throw new RangeError(`unsupported settled expression part ${part.kind}`);
      };

      addPart(prepared);
      return finishLeaf(leaf);
    };

    const materializeLeaf = (prepared, renderDepth, parentId) =>
      fillLeaf(newLeaf(parentId), prepared, renderDepth);

    // The record pass builds structural objects found in a fraction numerator
    // before it allocates the enclosing type-20h record. The numerator leaf is
    // allocated afterward and receives pointers to those earlier objects. This
    // differs from the denominator and from every other translated child path.
    // Preparing a leaf separately from materializing it retains that ROM order.
    const prepare = (expression, renderDepth, structuralDepth,
                     fractionNumerator = false) => {
      if (expression.kind === 'tokens') return {
        ...expression, fractionByte13:expression.tokens[0],
      };
      if (expression.kind === 'sequence') {
        const parts = expression.parts.map((part, index) =>
          prepare(part, renderDepth, structuralDepth,
                  fractionNumerator && index === 0));
        return {
          kind:'sequence', parts,
          fractionByte13:parts[0].fractionByte13,
        };
      }
      if (expression.kind === 'power') {
        const renderType = settledStructuralTokenType(0x00, 0xf0);
        if (renderType !== 0x2a)
          throw new Error('34:594D power token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[1],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0,
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const child = build(
          expression.exponent, renderDepth + 1, structuralId, structuralDepth + 1);
        const firstRaisedRow = renderDepth === 0;
        structural.word07 = checkedWord(
          child.word05 + (firstRaisedRow ? 5 : 3), 'power height');
        structural.word09 = child.word07;
        structural.word0B = checkedWord(
          firstRaisedRow ? child.word05 + 1 : child.word09 + 3,
          'power baseline');
        structural.word0D = firstRaisedRow ? 6 : 4;
        structural.child_ids = [child.record_id];
        return {
          kind:'sequence',
          parts:[{kind:'tokens',tokens:expression.base},
                 {kind:'embedded',structural}],
          fractionByte13:0x10,
        };
      }
      if (expression.kind === 'ePower' || expression.kind === 'tenPower') {
        const sourceToken = expression.kind === 'ePower' ? 0xbf : 0xc1;
        const renderType = settledStructuralTokenType(0x00, sourceToken);
        const expectedType = expression.kind === 'ePower' ? 0x25 : 0x26;
        if (renderType !== expectedType)
          throw new Error(`34:594D ${expression.kind} token mapping is inconsistent`);
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[1],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0,
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const exponent = build(
          expression.exponent, renderDepth + 1,
          structuralId, structuralDepth + 1);
        exponent.word0B = 6;
        exponent.word0D = 0;
        structural.word07 = checkedWord(
          exponent.word05 + 4, `${expression.kind} height`);
        structural.word09 = checkedWord(
          exponent.word07 + 6, `${expression.kind} width`);
        structural.word0B = exponent.word05;
        structural.child_ids = [exponent.record_id];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      if (expression.kind === 'logBase') {
        const renderType = settledStructuralTokenType(0xef, 0x34);
        if (renderType !== 0x28)
          throw new Error('34:594D log-base token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[2],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0,
          child_ids:[], payload:[],
        };
        nodes.push(structural);

        // The two-argument pass reserves both leaves before scanning either
        // payload for nested structural records.
        const base = newLeaf(structuralId);
        const argument = newLeaf(structuralId);
        fillLeaf(base, prepare(
          expression.base, renderDepth + 1, structuralDepth + 1,
          fractionNumerator), renderDepth + 1);
        fillLeaf(argument, prepare(
          expression.argument, renderDepth, structuralDepth + 1,
          fractionNumerator), renderDepth);
        base.word0B = 18;
        base.word0D = checkedWord(
          argument.word09 + 1, 'log-base base y');
        argument.word0B = checkedWord(
          base.word07 + 24, 'log-base argument x');
        argument.word0D = 0;
        structural.word07 = checkedWord(Math.max(
          argument.word05, base.word0D + base.word05), 'log-base height');
        structural.word09 = checkedWord(
          argument.word0B + argument.word07 + 6, 'log-base width');
        structural.word0B = argument.word09;
        structural.child_ids = [base.record_id, argument.record_id];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      if (expression.kind === 'radical') {
        const renderType = settledStructuralTokenType(0x00, 0xbc);
        if (renderType !== 0x27)
          throw new Error('34:594D radical token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[1],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0,
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const child = build(
          expression.radicand, renderDepth, structuralId, structuralDepth + 1);
        child.word0B = 5;
        child.word0D = 2;
        structural.word07 = checkedWord(child.word05 + 2, 'radical height');
        structural.word09 = checkedWord(child.word07 + 5, 'radical width');
        structural.word0B = checkedWord(child.word09 + 2, 'radical baseline');
        structural.child_ids = [child.record_id];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      if (expression.kind === 'nthRoot') {
        const renderType = settledStructuralTokenType(0x00, 0xf1);
        if (renderType !== 0x24)
          throw new Error('34:594D nth-root token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[2],
          word07:0, word09:0, word0B:0, word0D:0,
          word0F:0, word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10
            : structuralDepth === 0 ? leadingByte(expression.index) : 0,
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const index = build(
          expression.index, renderDepth + 1, structuralId, structuralDepth + 1);
        // The type-24 metric pass keeps the index payload length at +11h but
        // clears its +0Fh word. The renderer still consumes the full payload.
        index.word0F = 0;
        const radicand = build(
          expression.radicand, renderDepth, structuralId, structuralDepth + 1);
        radicand.word0B = checkedWord(index.word07 + 4, 'nth-root radicand x');
        radicand.word0D = 4;
        structural.word07 = checkedWord(radicand.word05 + 4, 'nth-root height');
        structural.word09 = checkedWord(
          index.word07 + radicand.word07 + 4, 'nth-root width');
        structural.word0B = checkedWord(
          radicand.word09 + 4, 'nth-root baseline');
        structural.child_ids = [index.record_id, radicand.record_id];
        return {kind:'embedded',structural,fractionByte13:0xef};
      }
      if (expression.kind === 'fraction') {
        const numeratorPrepared = prepare(
          expression.numerator, renderDepth + 1, structuralDepth + 1, true);
        const renderType = settledStructuralTokenType(0xef, 0x2e);
        if (renderType !== 0x20)
          throw new Error('34:594D fraction token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[0],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10
            : structuralDepth === 0 ? numeratorPrepared.fractionByte13 : 0,
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const numerator = materializeLeaf(
          numeratorPrepared, renderDepth + 1, structuralId);
        numerator.word0F = 0;
        const denominator = build(
          expression.denominator, renderDepth + 1,
          structuralId, structuralDepth + 1);
        const width = Math.max(numerator.word07, denominator.word07);
        numerator.word0B = checkedWord(
          2 + Math.floor((width - numerator.word07) / 2),
          'fraction numerator x');
        numerator.word0D = 0;
        denominator.word0B = checkedWord(
          2 + Math.floor((width - denominator.word07) / 2),
          'fraction denominator x');
        denominator.word0D = checkedWord(
          numerator.word05 + 3, 'fraction denominator y');
        structural.word07 = checkedWord(
          numerator.word05 + denominator.word05 + 3, 'fraction height');
        structural.word09 = checkedWord(width + 4, 'fraction width');
        structural.word0B = checkedWord(
          numerator.word05 + 1, 'fraction baseline');
        structural.child_ids = [numerator.record_id, denominator.record_id];
        return {kind:'embedded',structural,fractionByte13:0xef};
      }
      if (expression.kind === 'integral') {
        if (expression.variable.kind !== 'tokens')
          throw new RangeError('integral variable must be an ordinary token run');
        const renderType = settledStructuralTokenType(0x00, 0x24);
        if (renderType !== 0x22)
          throw new Error('34:594D integral token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[4],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0xef,
          child_ids:[], payload:[],
        };
        nodes.push(structural);

        // 34:4900 reserves the four multi-argument leaf IDs before it scans
        // any argument payload for embedded structural records.
        const lower = newLeaf(structuralId);
        const upper = newLeaf(structuralId);
        const body = newLeaf(structuralId);
        const variable = newLeaf(structuralId);
        fillLeaf(lower, prepare(
          expression.lower, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        fillLeaf(upper, prepare(
          expression.upper, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        fillLeaf(body, prepare(
          expression.body, renderDepth, structuralDepth + 1,
          fractionNumerator), renderDepth);
        fillLeaf(variable, prepare(
          expression.variable, renderDepth, structuralDepth + 1,
          fractionNumerator), renderDepth);
        variable.render_type = 1;

        const boundWidth = Math.max(lower.word07, upper.word07);
        const bodyX = checkedWord(boundWidth + 12, 'integral body x');
        const bodyY = Math.max(5, upper.word05);
        const lowerSpace = Math.max(5, lower.word05);
        const height = checkedWord(
          bodyY + body.word05 + lowerSpace, 'integral height');
        const baseline = checkedWord(
          body.word09 + bodyY, 'integral baseline');
        const differentialGap = renderDepth === 0 ? 12 : 10;
        const variableX = checkedWord(
          bodyX + body.word07 + differentialGap, 'integral variable x');
        lower.word0B = 6;
        lower.word0D = checkedWord(height - lower.word05, 'integral lower-bound y');
        upper.word0B = 6;
        upper.word0D = 0;
        body.word0B = bodyX;
        body.word0D = bodyY;
        variable.word0B = variableX;
        variable.word0D = checkedWord(
          baseline - variable.word09, 'integral variable y');
        structural.word07 = height;
        structural.word09 = checkedWord(
          variableX + variable.word07 + 2, 'integral width');
        structural.word0B = baseline;
        structural.child_ids = [
          lower.record_id, upper.record_id, body.record_id, variable.record_id,
        ];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      if (expression.kind === 'nDeriv') {
        if (expression.variable.kind !== 'tokens')
          throw new RangeError('nDeriv variable must be an ordinary token run');
        const renderType = settledStructuralTokenType(0x00, 0x25);
        if (renderType !== 0x23)
          throw new Error('34:594D nDeriv token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          // Type 23h selects the fourth byte in the 34:5996 metadata row.
          word05:settledRecordMetadata(renderType)[3],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0xef,
          child_ids:[], payload:[],
        };
        nodes.push(structural);

        // The three-argument pass reserves variable, body, and evaluation-value
        // leaves before it scans any child payload for structural records.
        const variable = newLeaf(structuralId);
        const body = newLeaf(structuralId);
        const value = newLeaf(structuralId);
        fillLeaf(variable, prepare(
          expression.variable, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        fillLeaf(body, prepare(
          expression.body, renderDepth, structuralDepth + 1,
          fractionNumerator), renderDepth);
        fillLeaf(value, prepare(
          expression.value, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        variable.render_type = 1;

        // Type 23h's two metric passes at 34:7485 and 34:76C2 place the
        // derivative fraction at the left, the body in delimiters, then
        // repeat the variable after the evaluation bar before "=value".
        const baseline = Math.max(6, body.word09);
        const height = Math.max(body.word05, baseline + 7);
        variable.word0B = 5;
        variable.word0D = checkedWord(
          baseline + 2, 'nDeriv variable y');
        body.word0B = 16;
        body.word0D = checkedWord(
          baseline - body.word09, 'nDeriv body y');
        value.word0B = checkedWord(
          body.word07 + variable.word07 + 29, 'nDeriv value x');
        value.word0D = checkedWord(
          baseline + 2, 'nDeriv evaluation-value y');
        structural.word07 = checkedWord(height, 'nDeriv height');
        structural.word09 = checkedWord(
          value.word0B + value.word07, 'nDeriv width');
        structural.word0B = checkedWord(baseline, 'nDeriv baseline');
        structural.child_ids = [
          variable.record_id, body.record_id, value.record_id,
        ];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      if (expression.kind === 'summation') {
        if (expression.variable.kind !== 'tokens')
          throw new RangeError('summation variable must be an ordinary token run');
        const renderType = settledStructuralTokenType(0xef, 0x33);
        if (renderType !== 0x29)
          throw new Error('34:594D summation token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:3,
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:fractionNumerator ? 0x10 : 0xef,
          child_ids:[], payload:[],
        };
        nodes.push(structural);

        // The multi-argument pass reserves all four child leaves before it
        // scans any payload for nested structural records.
        const variable = newLeaf(structuralId);
        const lower = newLeaf(structuralId);
        const upper = newLeaf(structuralId);
        const body = newLeaf(structuralId);
        fillLeaf(variable, prepare(
          expression.variable, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        fillLeaf(lower, prepare(
          expression.lower, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        fillLeaf(upper, prepare(
          expression.upper, renderDepth + 1, structuralDepth + 1,
          fractionNumerator),
        renderDepth + 1);
        fillLeaf(body, prepare(
          expression.body, renderDepth, structuralDepth + 1,
          fractionNumerator), renderDepth);
        variable.render_type = 1;

        const upperWidth = upper.word07;
        const lowerWidth = checkedWord(
          variable.word07 + 4 + lower.word07, 'summation lower row width');
        const operatorWidth = Math.max(upperWidth, lowerWidth, 12);
        const upperSpace = Math.max(5, upper.word05);
        const lowerSpace = Math.max(variable.word05, lower.word05);
        const height = checkedWord(
          upperSpace + 9 + lowerSpace, 'summation height');
        const baseline = checkedWord(
          upperSpace + 4, 'summation baseline');
        const bodyX = checkedWord(operatorWidth + 6, 'summation body x');
        const lowerRowY = checkedWord(
          height - lowerSpace, 'summation lower row y');
        variable.word0B = 0;
        variable.word0D = lowerRowY;
        lower.word0B = checkedWord(
          variable.word07 + 4, 'summation lower-bound x');
        lower.word0D = lowerRowY;
        upper.word0B = checkedWord(
          Math.floor((operatorWidth - upper.word07) / 2),
          'summation upper-bound x');
        upper.word0D = 0;
        body.word0B = bodyX;
        body.word0D = checkedWord(
          baseline - body.word09, 'summation body y');
        structural.word07 = height;
        structural.word09 = checkedWord(
          bodyX + body.word07 + 5, 'summation width');
        structural.word0B = baseline;
        structural.child_ids = [
          variable.record_id, lower.record_id, upper.record_id, body.record_id,
        ];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      throw new RangeError(`unsupported settled expression part ${expression.kind}`);
    };

    function build(expression, renderDepth, parentId, structuralDepth) {
      const leaf = newLeaf(parentId);
      return fillLeaf(
        leaf, prepare(expression, renderDepth, structuralDepth), renderDepth);
    }

    const root = build(spec, 0, firstId - 1, 0);
    for (const node of nodes)
      if (node.render_type >= 0x1f && node.byte13 === 0)
        node.byte13 = root.payload[0];
    const nodeMap = new Map(nodes.map(node => [node.record_id,node]));
    const orderedNodes = [];
    const visited = new Set();
    const visit = recordId => {
      if (visited.has(recordId)) return;
      const node = nodeMap.get(recordId);
      if (!node) throw new Error(`constructed record 0x${recordId.toString(16)} is absent`);
      visited.add(recordId);
      orderedNodes.push(node);
      for (const childId of node.child_ids) visit(childId);
      for (let index = 0; index + 3 < node.payload.length; index++)
        if (node.payload[index] === 0xef &&
            0x1f <= node.payload[index + 1] && node.payload[index + 1] <= 0x2b)
          visit(node.payload[index + 2] | node.payload[index + 3] << 8);
    };
    visit(root.record_id);
    return {
      entry_id:root.record_id,
      origin:{x:0,y:0},
      source:'34:4900, 34:5935, 34:7393, and 34:7609 translated compositional construction',
      nodes:orderedNodes,
    };
  }

  // Compatibility entry for the closed power slice. The exponent may itself
  // contain any expression kind accepted by the compositional builder.
  function constructSettledPowerProgram(input, firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {...input, kind:'power'}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated power construction';
    return program;
  }

  function constructSettledRadicalProgram(radicand, firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'radical', radicand}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated radical construction';
    return program;
  }

  function constructSettledNthRootProgram(index, radicand, firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'nthRoot', index, radicand}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated nth-root construction';
    return program;
  }

  function constructSettledFractionProgram(numerator, denominator,
                                           firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'fraction', numerator, denominator}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated fraction construction';
    return program;
  }

  function constructSettledIntegralProgram(lower, upper, body, variable,
                                           firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'integral', lower, upper, body, variable}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated integral construction';
    return program;
  }

  function constructSettledSummationProgram(variable, lower, upper, body,
                                             firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'summation', variable, lower, upper, body}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated summation construction';
    return program;
  }

  function constructSettledNDerivProgram(variable, body, value,
                                          firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'nDeriv', variable, body, value}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated nDeriv construction';
    return program;
  }

  // Execute the complete leaf byte stream entered at 34:660A. EF 1Fh..2Bh
  // embeds a structural record ID, while EF 2Dh closes that embedded object.
  // Structural handlers temporarily enter one depth below the containing leaf;
  // their translated depth mutations then select the same large/small font as
  // the ROM. The containing pen advances by the structural record's +9 word.
  function executeSettledRecordProgram(inputs, entryId, options = {}) {
    const initialDepth = options.depth === undefined ? 0 : byte(options.depth, 'settled depth');
    const fontAdvance = (depth, code) => {
      if (options.glyphAdvance) {
        const value = options.glyphAdvance(depth, code);
        if (!Number.isInteger(value) || value < 0 || value > 0xffff)
          throw new RangeError('glyphAdvance must return a nonnegative integer');
        return value;
      }
      return depth === 0 ? 6 : 4;
    };

    const renderLeaf = (record, context, controls) => {
      const pen = {
        x:0,
        y:controls.state.depth === 0 ? record.word09 - 3 : record.word09 - 2,
      };
      for (let index = 0; index < record.payload.length;) {
        const token = record.payload[index];
        if (token === 0xef && index + 1 < record.payload.length) {
          const subtype = record.payload[index + 1];
          if (subtype === 0x2d) {
            index += 2;
            continue;
          }
          if (0x1f <= subtype && subtype <= 0x2b) {
            if (index + 3 >= record.payload.length)
              throw new RangeError(`record 0x${record.id.toString(16)} has a truncated embedded record`);
            const id = record.payload[index + 2] | record.payload[index + 3] << 8;
            const nested = controls.record(id);
            if (nested.type !== subtype)
              throw new RangeError(
                `record 0x${record.id.toString(16)} embeds type 0x${subtype.toString(16)} ` +
                `but record 0x${id.toString(16)} has type 0x${nested.type.toString(16)}`);
            const savedDepth = controls.state.depth;
            controls.state.depth = savedDepth + 1;
            controls.visit(id, {
              x:context.origin.x + pen.x,
              y:context.origin.y + pen.y -
                (nested.word0B - (savedDepth === 0 ? 3 : 2)),
            });
            controls.state.depth = savedDepth;
            pen.x += nested.word09;
            index += 4;
            continue;
          }
          if (subtype === 0x1e) {
            const code = 0xf7;
            controls.emit({kind:'glyph', code, x:pen.x, y:pen.y,
              tokenBytes:[0xef,subtype], routine:'34:660A–6704 → 34:6C37'});
            pen.x += fontAdvance(controls.state.depth, code);
            index += 2;
            continue;
          }
        }

        const resolved = options.resolveToken
          ? options.resolveToken(record.payload, index, controls.state.depth)
          : null;
        if (resolved) {
          if (!Array.isArray(resolved.codes) || !Number.isInteger(resolved.length) || resolved.length < 1)
            throw new TypeError('resolveToken must return {codes, length}');
          for (const rawCode of resolved.codes) {
            const code = byte(rawCode, 'resolved settled glyph');
            controls.emit({kind:'glyph', code, x:pen.x, y:pen.y,
              tokenBytes:record.payload.slice(index, index + resolved.length),
              routine:'34:660A–6704 → 34:6C37'});
            pen.x += fontAdvance(controls.state.depth, code);
          }
          index += resolved.length;
          continue;
        }
        const code = settledTokenGlyph(token);
        if (code !== null) {
          controls.emit({kind:'glyph', code, x:pen.x, y:pen.y,
            tokenBytes:[token], routine:'34:660A–6704 → 34:6C37'});
          pen.x += fontAdvance(controls.state.depth, code);
        } else {
          controls.emit({kind:'unresolved-token', bytes:[token], x:pen.x, y:pen.y,
            routine:'34:660A–6704 token/string path'});
        }
        index++;
      }
    };

    return executeSettledRecordGraph(inputs, entryId, {
      ...options, depth:initialDepth, renderLeaf,
    });
  }

  function settledOperationPixels(operation, font) {
    if (!operation || typeof operation !== 'object')
      throw new TypeError('settled operation must be an object');
    const pixels = [];
    const point = (x, y) => {
      if (!Number.isInteger(x) || !Number.isInteger(y))
        throw new RangeError('settled pixel coordinate must be an integer');
      pixels.push([x,y,1]);
    };
    if (operation.kind === 'point') {
      point(operation.x, operation.y);
    } else if (operation.kind === 'line') {
      const dx = Math.sign(operation.to.x - operation.from.x);
      const dy = Math.sign(operation.to.y - operation.from.y);
      if (dx && dy) throw new RangeError('settled line must be axis-aligned');
      let x = operation.from.x, y = operation.from.y;
      for (;;) {
        point(x,y);
        if (x === operation.to.x && y === operation.to.y) break;
        x += dx; y += dy;
      }
    } else if (operation.kind === 'glyph') {
      if (!font || !font.large || !font.small)
        throw new TypeError('settled glyph rasterization requires font data');
      const small = operation.depth !== 0;
      const glyph = small
        ? font.small.glyphs[operation.code]
        : {w:font.large.width,rows:font.large.glyphs[operation.code]};
      if (!glyph || !Array.isArray(glyph.rows))
        throw new RangeError(`font has no glyph 0x${operation.code.toString(16)}`);
      // 34:6C37 reports the small-font pen row one pixel below the bitmap's
      // first row. The large-font pen already names the bitmap's top row.
      const top = operation.y - (small ? 1 : 0);
      for (let row = 0; row < glyph.rows.length; row++)
        for (let column = 0; column < glyph.w; column++)
          if (glyph.rows[row] & 1 << (glyph.w - 1 - column))
            point(operation.x + column, top + row);
    } else if (operation.kind === 'glyph-run') {
      if (!font || !font.large || !font.small)
        throw new TypeError('settled glyph rasterization requires font data');
      let x = operation.x;
      for (const code of operation.codes) {
        const glyph = operation.depth !== 0
          ? font.small.glyphs[code]
          : {w:font.large.width,rows:font.large.glyphs[code]};
        if (!glyph) throw new RangeError(`font has no glyph 0x${code.toString(16)}`);
        pixels.push(...settledOperationPixels(
          {...operation,kind:'glyph',code,x}, font));
        x += operation.depth !== 0 ? glyph.w : font.large.width + 1;
      }
    } else if (operation.kind === 'bitmap') {
      if (!Array.isArray(operation.rows) || operation.rows.length !== operation.height)
        throw new RangeError('settled bitmap must provide one row mask per row');
      for (let row = 0; row < operation.height; row++)
        for (let column = 0; column < operation.width; column++)
          if (operation.rows[row] & 1 << (operation.width - 1 - column))
            point(operation.x + column, operation.y + row);
    } else if (!operation.kind.startsWith('unresolved-')) {
      throw new RangeError(`cannot rasterize settled operation kind ${operation.kind}`);
    }
    return pixels;
  }

  function settledBlits(operation, font) {
    if (!font || !font.large || !font.small)
      throw new TypeError('settled blit translation requires font data');
    if (operation.kind === 'glyph') {
      const small = operation.depth !== 0;
      const glyph = small
        ? font.small.glyphs[operation.code]
        : {w:font.large.width,rows:font.large.glyphs[operation.code]};
      if (!glyph || !Array.isArray(glyph.rows))
        throw new RangeError(`font has no glyph 0x${operation.code.toString(16)}`);
      return [{
        x:operation.x,
        y:operation.y - (small ? 1 : 0),
        // 07:45B6 gives the large-font pattern a six-pixel cell and shifts
        // each five-pixel row left, leaving the pen-advance column clear.
        width:small ? glyph.w : font.large.width + 1,
        rows:small ? glyph.rows : glyph.rows.map(row => row << 1),
      }];
    }
    if (operation.kind === 'glyph-run') {
      const result = [];
      let x = operation.x;
      for (const code of operation.codes) {
        const glyph = operation.depth !== 0
          ? font.small.glyphs[code]
          : {w:font.large.width,rows:font.large.glyphs[code]};
        if (!glyph) throw new RangeError(`font has no glyph 0x${code.toString(16)}`);
        result.push(...settledBlits({...operation,kind:'glyph',code,x}, font));
        x += operation.depth !== 0 ? glyph.w : font.large.width + 1;
      }
      return result;
    }
    if (operation.kind === 'bitmap') {
      if (!Array.isArray(operation.rows) || operation.rows.length !== operation.height)
        throw new RangeError('settled bitmap must provide one row mask per row');
      return [{x:operation.x,y:operation.y,width:operation.width,rows:operation.rows}];
    }
    return [];
  }

  const settledGridByte = (grid, byteColumn, row) => {
    let value = 0;
    for (let bit = 0; bit < 8; bit++)
      value |= grid[row][8 * byteColumn + bit] << (7 - bit);
    return value;
  };

  const settledByteChanges = (before, after, byteColumn, row) => {
    const changes = [];
    for (let bit = 0; bit < 8; bit++) {
      const mask = 1 << (7 - bit);
      if ((before & mask) !== (after & mask))
        changes.push([8 * byteColumn + bit,row,(after & mask) ? 1 : 0]);
    }
    return changes;
  };

  const settledStoreByte = (grid, byteColumn, row, value) => {
    for (let bit = 0; bit < 8; bit++)
      grid[row][8 * byteColumn + bit] = (value >> (7 - bit)) & 1;
  };

  // Translate the normal settled-render paths into accepted LCD data writes.
  // Page 4 visits geometry one point at a time. _VPutMap at 01:6293 replaces
  // the glyph cell row by row and writes a crossing row's right byte before
  // its left byte (01:63CE–641A).
  function settledOperationWrites(operation, font, grid) {
    if (!Array.isArray(grid) || !grid.length || !Array.isArray(grid[0]))
      throw new TypeError('settled LCD write translation requires a pixel grid');
    const height = grid.length, width = grid[0].length;
    if (width % 8)
      throw new RangeError('settled LCD write grid width must be byte-aligned');
    const writes = [];
    const write = (byteColumn, row, value, retainUnchanged = false) => {
      if (byteColumn < 0 || row < 0 || byteColumn >= width / 8 || row >= height) return;
      const before = settledGridByte(grid, byteColumn, row);
      value &= 0xff;
      if (!retainUnchanged && before === value) return;
      const changes = settledByteChanges(before, value, byteColumn, row);
      settledStoreByte(grid, byteColumn, row, value);
      writes.push({pointer:[byteColumn,row],value,changes});
    };

    if (operation.kind === 'point' || operation.kind === 'line') {
      for (const [x,y] of settledOperationPixels(operation, font)) {
        if (x < 0 || y < 0 || x >= width || y >= height) continue;
        const byteColumn = x >> 3;
        write(byteColumn, y,
              settledGridByte(grid, byteColumn, y) | 1 << (7 - (x & 7)), true);
      }
      return writes;
    }

    const largeGlyph = (operation.kind === 'glyph' || operation.kind === 'glyph-run') &&
      operation.depth === 0;
    const smallGlyph = (operation.kind === 'glyph' || operation.kind === 'glyph-run') &&
      operation.depth !== 0;
    for (const blit of settledBlits(operation, font)) {
      // The ROM font export includes one padding row above and below the five
      // rows consumed by _VPutMap. 01:637E emits all five interior rows, even
      // when a row is zero. This is observable for '=' and the division sign.
      const firstRow = smallGlyph ? 1 : 0;
      const lastRow = smallGlyph ? blit.rows.length - 2 : blit.rows.length - 1;
      for (let row = 0; row < blit.rows.length; row++) {
        if (smallGlyph && (row < firstRow || row > lastRow)) continue;
        const y = blit.y + row;
        if (y < 0 || y >= height) continue;
        const firstByte = Math.floor(blit.x / 8);
        const lastByte = Math.floor((blit.x + blit.width - 1) / 8);
        for (let byteColumn = lastByte; byteColumn >= firstByte; byteColumn--) {
          if (byteColumn < 0 || byteColumn >= width / 8) continue;
          let coverage = 0, ink = 0;
          for (let column = 0; column < blit.width; column++) {
            const x = blit.x + column;
            if ((x >> 3) !== byteColumn) continue;
            const screenMask = 1 << (7 - (x & 7));
            coverage |= screenMask;
            if (blit.rows[row] & 1 << (blit.width - 1 - column)) ink |= screenMask;
          }
          const before = settledGridByte(grid, byteColumn, y);
          write(byteColumn, y, (before & ~coverage) | ink,
                largeGlyph || smallGlyph || operation.retainUnchanged === true);
        }
      }
    }
    return writes;
  }

  function rasterizeSettledOperations(operations, font, options = {}) {
    if (!Array.isArray(operations))
      throw new TypeError('settled operations must be an array');
    const width = options.width === undefined ? 96 : options.width;
    const height = options.height === undefined ? 64 : options.height;
    if (!Number.isInteger(width) || width < 1 || !Number.isInteger(height) || height < 1)
      throw new RangeError('settled raster dimensions must be positive integers');
    const grid = options.initialGrid === undefined
      ? Array.from({length:height}, () => new Array(width).fill(0))
      : options.initialGrid.map(row => row.slice());
    if (grid.length !== height || grid.some(row => row.length !== width ||
        row.some(value => value !== 0 && value !== 1)))
      throw new RangeError('settled initial grid must match the raster dimensions and contain bits');
    const writes = [];
    const events = operations.map((operation, operationIndex) => {
      const operationWrites = settledOperationWrites(operation, font, grid)
        .map((item, writeIndex) => ({...item,operationIndex,writeIndex}));
      writes.push(...operationWrites);
      return {
        operationIndex, operation, writes:operationWrites,
        changes:operationWrites.flatMap(item => item.changes),
      };
    });
    return {width,height,events,writes,grid};
  }

  // Render-record type 20h dispatches through 34:6105/6119 to 34:620A. It
  // renders child records 1 and 2, reads each child's word at +7, and chooses
  // the larger value. The inclusive rule runs from x=1 through max+1 at the
  // parent record's word at +0Bh.
  function settledFractionOperations(firstWidth, secondWidth, y) {
    byte(firstWidth, 'settled fraction first-child width');
    byte(secondWidth, 'settled fraction second-child width');
    byte(y, 'settled fraction rule y');
    const x2 = Math.max(firstWidth, secondWidth) + 1;
    byte(x2, 'settled fraction rule endpoint');
    return [
      {kind:'child', index:1, routine:'34:620A → 34:636C'},
      {kind:'child', index:2, routine:'34:6214 → 34:6378'},
      {kind:'line', axis:'horizontal', from:{x:1,y}, to:{x:x2,y},
       routine:'34:622C → 34:5DA6'},
    ];
  }

  // Render-record type 2Ah dispatches to the single JP at 34:6375. That jump
  // enters the child-1 wrapper at 34:636C; the record itself emits no primitive.
  function settledSingleChildOperations() {
    return [
      {kind:'child', index:1, routine:'34:6375 → 34:636C'},
    ];
  }

  // Render-record type 21h dispatches to 34:6347. The record's +7 word is the
  // bar height and +9 is its width. It emits the two inclusive vertical bars,
  // then traverses child 1. The intermediate 34:79C9 bookkeeping calls do not
  // emit a visible primitive.
  function settledAbsoluteOperations(width, height) {
    byte(width, 'settled absolute width');
    byte(height, 'settled absolute height');
    if (width < 4)
      throw new RangeError('settled absolute width must be at least four');
    if (height < 1)
      throw new RangeError('settled absolute height must be positive');
    return [
      {kind:'line', axis:'vertical', from:{x:2,y:0}, to:{x:2,y:height - 1},
       routine:'34:6351 → 34:5D96'},
      {kind:'line', axis:'vertical', from:{x:width - 4,y:0},
       to:{x:width - 4,y:height - 1}, routine:'34:6360 → 34:5D96'},
      {kind:'child', index:1, routine:'34:6366 → 34:636C'},
    ];
  }

  // Render-record type 24h dispatches to 34:6315. It renders child 1, draws the
  // root hook at x=child1(+7)-1, emits the hook's vertical segment, renders
  // child 2, and draws an inclusive vinculum. 34:62D0 selects seven bitmap
  // rows at outer depth and five in a raised row. The vinculum uses child 2's
  // +7 word and starts at the hook x.
  function settledNthRootOperations(indexWidth, radicandWidth, height = 11, depth = 0) {
    byte(indexWidth, 'settled nth-root index width');
    byte(radicandWidth, 'settled nth-root radicand width');
    byte(height, 'settled nth-root height');
    byte(depth, 'settled nth-root depth');
    if (indexWidth < 1)
      throw new RangeError('settled nth-root index width must be positive');
    const fullRows = [0x04,0x04,0x04,0x04,0x14,0x0c,0x04];
    const rows = depth === 0 ? fullRows : fullRows.slice(2);
    if (height < rows.length)
      throw new RangeError('settled nth-root height cannot place its hook');
    const hookX = indexWidth - 1;
    const hookY = height - rows.length;
    const ruleEnd = radicandWidth + hookX + 3;
    byte(ruleEnd, 'settled nth-root vinculum endpoint');
    return [
      {kind:'child', index:1, routine:'34:6315 → 34:636C'},
      {kind:'bitmap', x:hookX, y:hookY, width:5, height:rows.length,
       rows, retainUnchanged:true,
       routine:'34:6321 → 34:62D0 → 34:630C'},
      {kind:'line', axis:'vertical', from:{x:hookX + 2,y:3},
       to:{x:hookX + 2,y:hookY}, routine:'34:6331 → 34:5D96'},
      {kind:'child-select', index:2, routine:'34:6334 → 34:6CCA'},
      {kind:'line', axis:'horizontal', from:{x:hookX + 2,y:2},
       to:{x:ruleEnd,y:2}, routine:'34:6344 → 34:5DA6'},
      {kind:'child', index:2, routine:'34:6344 → 34:62C3 → 34:62C6'},
    ];
  }

  // Render-record type 27h dispatches to 34:62A1. 34:62D0 emits the seven-row
  // root-hook bitmap first. The handler then draws its vertical stem, selects
  // child 1, reads that child's +7 width, emits the inclusive vinculum, and
  // finally enters the child renderer at 34:660A.
  function settledRadicalOperations(height, childWidth, depth = 0) {
    byte(height, 'settled radical height');
    byte(childWidth, 'settled radical child width');
    byte(depth, 'settled radical depth');
    const fullRows = [0x04,0x04,0x04,0x04,0x14,0x0c,0x04];
    const rows = depth === 0 ? fullRows : fullRows.slice(2);
    const hookY = height - rows.length;
    if (hookY < 0)
      throw new RangeError('settled radical height cannot place its hook');
    const stemEnd = Math.max(1, height - 8);
    const ruleEnd = childWidth + 3;
    byte(ruleEnd, 'settled radical vinculum endpoint');
    return [
      {kind:'bitmap', x:0, y:hookY, width:5, height:rows.length,
       rows,
       retainUnchanged:true,
       routine:'34:62A4 → 34:62D0 → 34:630C'},
      {kind:'line', axis:'vertical', from:{x:2,y:1}, to:{x:2,y:stemEnd},
       routine:'34:62AE → 34:5D96'},
      {kind:'child-select', index:1, routine:'34:62B1 → 34:6D4B'},
      {kind:'line', axis:'horizontal', from:{x:2,y:0}, to:{x:ruleEnd,y:0},
       routine:'34:62C3 → 34:5DA6'},
      {kind:'child', index:1, routine:'34:62C6 → 34:660A'},
    ];
  }

  // Render-record type 22h dispatches through 34:6105/6119 to 34:622F. The
  // record's word at +7 is the sign height. The handler emits one inclusive
  // vertical segment, then four hook points in this exact order.
  function settledIntegralOperations(height) {
    byte(height, 'settled integral height');
    if (height < 3)
      throw new RangeError('settled integral height must be at least three');
    return [
      {kind:'line', axis:'vertical', from:{x:2,y:1}, to:{x:2,y:height - 2},
       routine:'34:6239 → 34:5D96'},
      {kind:'point', x:3, y:0, routine:'34:6244 → 34:5E85'},
      {kind:'point', x:4, y:1, routine:'34:624B → 34:5E85'},
      {kind:'point', x:1, y:height - 1, routine:'34:6257 → 34:5E85'},
      {kind:'point', x:0, y:height - 2, routine:'34:625D → 34:5E85'},
    ];
  }

  return {
    handlerRecord,
    handlerRow,
    emitHandlerRow,
    mapDirectGlyph,
    classifyCell,
    keyToStringIndex,
    descriptor,
    selectDescriptor,
    descriptorState,
    descriptorPen,
    emitDescriptor,
    fractionEndpoint,
    multiArgumentRowStep,
    settledPointOperation,
    settledVerticalOperation,
    settledHorizontalOperation,
    settledObjectHandler,
    settledStructuralTokenType,
    settledRecordMetadata,
    decodeSettledRecord,
    settledRenderHandler,
    settledCompoundOperations,
    matrixChildCount,
    executeSettledRecordGraph,
    executeSettledRecordProgram,
    settledOperationPixels,
    settledOperationWrites,
    rasterizeSettledOperations,
    settledTokenGlyph,
    constructSettledAbsoluteProgram,
    constructSettledExpressionProgram,
    constructSettledFractionProgram,
    constructSettledIntegralProgram,
    constructSettledNthRootProgram,
    constructSettledNDerivProgram,
    constructSettledPowerProgram,
    constructSettledRadicalProgram,
    constructSettledSummationProgram,
    settledFractionOperations,
    settledSingleChildOperations,
    settledAbsoluteOperations,
    settledNthRootOperations,
    settledRadicalOperations,
    settledIntegralOperations,
  };
});
