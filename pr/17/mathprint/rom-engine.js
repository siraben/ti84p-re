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
    settledFractionOperations,
    settledSingleChildOperations,
    settledIntegralOperations,
  };
});
