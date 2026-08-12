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
          kind:'bitmap', x:0, y:0, width:5, height:7,
          bytes:[0x05,0x02,0x01,0x00,0x1f,0x00,0x02,0x06],
          routine:'34:6143 → 34:61BE → ram:3CCF',
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
        const operations = settledNthRootOperations(first.word07, second.word07);
        renderChild(1);
        state.depth--;
        emit(record, origin, operations[1]);
        emit(record, origin, operations[2]);
        renderChild(2);
        emit(record, origin, operations[4]);
        break;
      }
      case 0x25:
      case 0x26: {
        const savedDepth = state.depth;
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
        const operations = settledRadicalOperations(record.word07, first.word07);
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
        y:controls.state.depth === 0 ? record.word09 - 3 : 0,
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
              y:context.origin.y + pen.y - (nested.word0B - 3),
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
  // five-byte root hook at x=child1(+7)-1, emits the hook's vertical segment,
  // renders child 2, and draws an inclusive vinculum. The vinculum uses child
  // 2's +7 word and starts at the hook x.
  function settledNthRootOperations(indexWidth, radicandWidth) {
    byte(indexWidth, 'settled nth-root index width');
    byte(radicandWidth, 'settled nth-root radicand width');
    if (indexWidth < 1)
      throw new RangeError('settled nth-root index width must be positive');
    const hookX = indexWidth - 1;
    const ruleEnd = radicandWidth + hookX + 3;
    byte(ruleEnd, 'settled nth-root vinculum endpoint');
    return [
      {kind:'child', index:1, routine:'34:6315 → 34:636C'},
      {kind:'bitmap', x:hookX, y:0, width:5, height:5,
       routine:'34:6321 → 34:62D0'},
      {kind:'line', axis:'vertical', from:{x:hookX + 2,y:3},
       to:{x:hookX + 2,y:4}, routine:'34:6331 → 34:5D96'},
      {kind:'child', index:2, routine:'34:6334 → 34:6378'},
      {kind:'line', axis:'horizontal', from:{x:hookX + 2,y:2},
       to:{x:ruleEnd,y:2}, routine:'34:6344 → 34:5DA6'},
    ];
  }

  // Render-record type 27h dispatches to 34:62A1. 34:62D0 emits the ten-byte
  // root-hook bitmap first. The handler then draws its vertical stem, selects
  // child 1, reads that child's +7 width, emits the inclusive vinculum, and
  // finally enters the child renderer at 34:660A.
  function settledRadicalOperations(height, childWidth) {
    byte(height, 'settled radical height');
    byte(childWidth, 'settled radical child width');
    if (height < 2)
      throw new RangeError('settled radical height must be at least two');
    const stemEnd = height - 1;
    const ruleEnd = childWidth + 3;
    byte(ruleEnd, 'settled radical vinculum endpoint');
    return [
      {kind:'bitmap', x:0, y:0, width:5, height:10,
       routine:'34:62A4 → 34:62D0'},
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
    decodeSettledRecord,
    settledRenderHandler,
    settledCompoundOperations,
    matrixChildCount,
    executeSettledRecordGraph,
    executeSettledRecordProgram,
    settledTokenGlyph,
    settledFractionOperations,
    settledSingleChildOperations,
    settledAbsoluteOperations,
    settledNthRootOperations,
    settledRadicalOperations,
    settledIntegralOperations,
  };
});
