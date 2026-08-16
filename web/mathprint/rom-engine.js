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

  const unsignedWord = (value, label) => {
    if (!Number.isInteger(value) || value < 0 || value > 0xffff)
      throw new RangeError(`${label} must be an unsigned word`);
    return value;
  };

  const addWord = (left, right) => (left + right) & 0xffff;

  const boolean = (value, label) => {
    if (typeof value !== 'boolean')
      throw new TypeError(`${label} must be a boolean`);
    return value;
  };

  let SETTLED_TOKEN_STRINGS = null;

  const SETTLED_TWO_BYTE_TABLES = Object.freeze({
    '5C':0x4452, '5D':0x4466,
    '5E10':0x4472, '5E20':0x4486, '5E40':0x449e, '5E80':0x44aa,
    '60':0x44b0, '61':0x44c4, 'AA':0x44d8,
    '62':0x44ec, '63':0x4566, '7E':0x45d6,
    'BB':0x45fc, 'EF':0x47e8,
  });

  // _IsA2ByteTok at 00:1FE8 scans this 11-byte set. Keep token-width
  // decoding available before the optional 01:6702 spelling artifact loads.
  const SETTLED_TWO_BYTE_LEADS = new Set([
    0x5c, 0x5d, 0x5e, 0x60, 0x61, 0x62,
    0x63, 0x7e, 0xaa, 0xbb, 0xef,
  ]);

  function setSettledTokenStrings(input) {
    const table = input && input.singleByte;
    const twoByte = input && input.twoByte;
    if (!table || table.page !== 0x01 || table.pointerTableAddress !== 0x4252 ||
        !Array.isArray(table.entries) || table.entries.length !== 0x100 ||
        !twoByte || twoByte.page !== 0x01 || !Array.isArray(twoByte.leadBytes) ||
        !twoByte.tables || twoByte.bbClampIndex !== 0xf6)
      throw new TypeError('expected the decoded 01:6702 token-string artifact');
    const decodeEntries = (rawEntries, label) => rawEntries.map((entry, token) => {
      if (!entry || !Number.isInteger(entry.pointer) ||
          !Number.isInteger(entry.metadata) || !Array.isArray(entry.codes) ||
          !entry.codes.length)
        throw new TypeError(`${label} entry 0x${token.toString(16)} is invalid`);
      return {
        pointer:entry.pointer,
        metadata:byte(entry.metadata, `${label} 0x${token.toString(16)} metadata`),
        codes:entry.codes.map((code, index) =>
          byte(code, `${label} 0x${token.toString(16)} display code ${index}`)),
      };
    });
    const entries = decodeEntries(table.entries, 'single-byte token');
    const tables = {};
    for (const [name, address] of Object.entries(SETTLED_TWO_BYTE_TABLES)) {
      const decoded = twoByte.tables[name];
      if (!decoded || decoded.pointerTableAddress !== address ||
          !Array.isArray(decoded.entries) || !decoded.entries.length)
        throw new TypeError(`two-byte token table ${name} is invalid`);
      tables[name] = decodeEntries(decoded.entries, `two-byte table ${name}`);
    }
    SETTLED_TOKEN_STRINGS = {
      entries,
      tables,
      bbClampIndex:twoByte.bbClampIndex,
      twoByteLeadBytes:new Set(twoByte.leadBytes.map((lead, index) =>
        byte(lead, `two-byte token lead ${index}`))),
    };
  }

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

  // 39:4A74–4AFD translates the incoming token/action byte into the class
  // index used by 39:4C27. The three IY+2 bits only affect raw 3Bh (the
  // exponent-context case); IY+9 bit 0 remaps ordinary classes 03h–08h to
  // their stacked-argument counterparts. Keep the table lookup separate from
  // handlerRecord(): class 00h is a valid table entry but has no row record.
  function editorTokenDispatch(layout, raw, options = {}) {
    requireLayout(layout);
    byte(raw, 'editor token/action byte');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor token dispatch options must be an object');
    const iy2 = options.iy2 === undefined ? 0xff : byte(options.iy2, 'editor IY+2');
    const iy9 = options.iy9 === undefined ? 0 : byte(options.iy9, 'editor IY+9');
    if (raw === 0x3d) return {
      raw, iy2, iy9, coarseClass:null, normalizedClass:null,
      adjustments:[], handlerPointer:null, handlerRows:null,
      kind:'templateHandoff', routine:'39:4A74 → 39:672E',
    };
    const coarseClass = (raw - 0x2a) & 0xff;
    let normalizedClass = coarseClass;
    const adjustments = [];
    if (coarseClass === 0x11 && (iy2 & 0x10) === 0) {
      normalizedClass = (raw - 1) & 0xff;
      adjustments.push('IY+2 bit 4 clear: raw-1');
      if ((iy2 & 0x40) === 0) {
        normalizedClass = (normalizedClass + 1) & 0xff;
        adjustments.push('IY+2 bit 6 clear: increment');
        if ((iy2 & 0x20) === 0) {
          normalizedClass = (normalizedClass + 1) & 0xff;
          adjustments.push('IY+2 bit 5 clear: increment');
        }
      }
    }
    if ((iy9 & 1) && normalizedClass >= 0x03 && normalizedClass <= 0x08) {
      normalizedClass = (normalizedClass + 0x28) & 0xff;
      adjustments.push('IY+9 bit 0 set: add 0x28');
    }
    const entry = layout.classes.find(item => item.cls === normalizedClass);
    const hasRows = entry && Array.isArray(entry.items) &&
      entry.rows === entry.items.length;
    return {
      raw, iy2, iy9, coarseClass, normalizedClass, adjustments,
      handlerPointer:entry && Number.isInteger(entry.ptr) ? entry.ptr : null,
      handlerRows:hasRows ? entry.rows : null,
      kind:'handlerLookup', routine:'39:4A74 → 39:4C27',
    };
  }

  // 39:50CF clamps the selected argument against the high byte of 85E1
  // (the argument count at 85E2), then computes the six-row window origin
  // returned in C. Its final continuation depends on the global key byte;
  // expose that boundary instead of pretending the cross-page jump is a
  // local return. 39:5101 maps the clamped argument to the visible row.
  function editorArgumentClamp(argumentIndex, argumentCount, options = {}) {
    byte(argumentIndex, 'editor argument index');
    byte(argumentCount, 'editor argument count');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor argument clamp options must be an object');
    const kbdKey = options.kbdKey === undefined ? null :
      byte(options.kbdKey, 'editor keyboard key');
    const clampedArgument = argumentIndex >= argumentCount
      ? argumentCount === 0 ? 0 : argumentCount - 1
      : argumentIndex;
    const windowStart = clampedArgument < 6 ? 0 : clampedArgument - 6;
    const returnsWindow = kbdKey === 0x04 && argumentCount < 8;
    return {
      argumentIndex, argumentCount, clampedArgument, windowStart, kbdKey,
      continuation:returnsWindow ? 'return-window-start' : 'cross-page-jump',
      routine:'39:50CF',
    };
  }

  function editorRowFromArg(argumentIndex) {
    byte(argumentIndex, 'editor argument index');
    return {
      argumentIndex,
      row:Math.min(argumentIndex + 1, 7),
      routine:'39:5101',
    };
  }

  // 39:513E stores the requested argument, runs the clamp/row helpers, then
  // restores 844B from 984A before returning through 513A. The parser and
  // operand emission around that call remain caller state, so the pure result
  // reports the restored baseline only when the caller supplies it.
  function editorLayoutArgument(argumentIndex, argumentCount, options = {}) {
    const clamp = editorArgumentClamp(argumentIndex, argumentCount, options);
    const row = editorRowFromArg(clamp.clampedArgument);
    const baselineRow = options.baselineRow === undefined ? null :
      byte(options.baselineRow, 'editor baseline row');
    return {
      ...clamp,
      visibleRow:row.row,
      baselineRow,
      restoredRow:baselineRow,
      routine:'39:513E → 39:50CF → 39:5101',
    };
  }

  function editorSubexpressionBranch(slot, cellPointer, baselineRow,
                                     recordFlags, argumentCount, options, routine,
                                     setsPreEmissionRow) {
    const menuCurrent = options.menuCurrent === undefined ? null :
      byte(options.menuCurrent, 'editor current menu');
    const cellOffset = (slot << 1) & 0xff;
    const cellAddress = (cellPointer + cellOffset) & 0xffff;
    const base = {
      slot, cellPointer, cellOffset, cellAddress, baselineRow,
      preEmissionRow:setsPreEmissionRow ? (baselineRow - 1) & 0xff : null,
      recordFlags, argumentCount, menuCurrent,
      measuresArgumentWidths:true, routine,
    };
    if (recordFlags & 0x20)
      return {
        ...base, branch:'styled-argument', emission:'styled', finalRow:1,
        continuation:'unresolved-styled-argument',
      };
    if (argumentCount !== 0)
      return {
        ...base, branch:'argument-list', emission:'arglist',
        finalRow:baselineRow, continuation:'return',
      };
    if (menuCurrent === 0x41 || menuCurrent === 0x32)
      return {
        ...base, branch:'empty-menu-fallback', emission:null,
        menuReset:0, finalRow:null, continuation:'cross-page-jump',
      };
    return {
      ...base, branch:'empty', emission:null, finalRow:1,
      continuation:'return',
    };
  }

  // 39:4C5A computes the visible argument slot from the current row and
  // baseline, then emits the row-cell list from the 984Ah base. The styled
  // and menu/error exits intentionally remain explicit continuations.
  function editorSubexpressionWindow(argumentIndex, currentRow, baselineRow,
                                     recordFlags, argumentCount, options = {}) {
    byte(argumentIndex, 'editor argument index');
    byte(currentRow, 'editor current row');
    byte(baselineRow, 'editor baseline row');
    byte(recordFlags, 'editor record flags');
    byte(argumentCount, 'editor argument count');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor subexpression options must be an object');
    const rowDelta = (currentRow - baselineRow) & 0xff;
    if (argumentIndex < rowDelta)
      return {
        argumentIndex, currentRow, baselineRow, recordFlags, argumentCount,
        rowDelta, branch:'argument-before-visible-row', emission:null,
        continuation:'cross-page-jump', routine:'39:4C5A',
      };
    const slot = argumentIndex - rowDelta;
    return {
      argumentIndex, currentRow, rowDelta,
      ...editorSubexpressionBranch(
      slot, 0x984a, baselineRow, recordFlags, argumentCount, options,
      '39:4C5A', true),
    };
  }

  // 39:4CA4 is the direct-slot variant. Its caller supplies the handler-cell
  // base, so only the byte-sized slot-to-cell offset is computed here.
  function editorSubexpressionCell(slot, cellPointer, baselineRow, recordFlags,
                                   argumentCount, options = {}) {
    byte(slot, 'editor visible argument slot');
    if (!Number.isInteger(cellPointer) || cellPointer < 0 || cellPointer > 0xffff)
      throw new RangeError('editor argument cell pointer must be an unsigned word');
    byte(baselineRow, 'editor baseline row');
    byte(recordFlags, 'editor record flags');
    byte(argumentCount, 'editor argument count');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor subexpression options must be an object');
    return editorSubexpressionBranch(
      slot, cellPointer, baselineRow, recordFlags, argumentCount, options,
      '39:4CA4', false);
  }

  function editorNineByteBuffer(value, label) {
    if (!Array.isArray(value) && !(value instanceof Uint8Array))
      throw new TypeError(`${label} must be a nine-byte array`);
    if (value.length !== 9)
      throw new RangeError(`${label} must contain exactly nine bytes`);
    return Array.from(value, (item, index) => byte(item, `${label} byte ${index}`));
  }

  // _FindAlphaUp/_FindAlphaDn normalize the type class through 07:5247 and
  // subtract the eight OP name bytes from OPx+8 down to OPx+1. Borrow
  // propagation makes OPx+1 the most-significant alphabetic byte. Program
  // and protected-program entries share one search class, as do the other
  // aliases below. Types 18h and 19h collapse to class zero.
  function editorAlphaTypeClass(type) {
    let value = byte(type, 'alphabetic VAT-search type') & 0x1f;
    if (value === 0x0d) value = 0x01;
    else if (value === 0x06) value = 0x05;
    else if (value === 0x0b) value = 0x03;
    else if (value === 0x18 || value === 0x19) value = 0;
    return value;
  }

  function editorAlphaNameCompare(left, right) {
    for (let index = 1; index <= 8; index++) {
      if (left[index] !== right[index])
        return left[index] < right[index] ? -1 : 1;
    }
    return 0;
  }

  function editorAlphaNamedType(type) {
    return type === 0x05 || type === 0x06 || type === 0x15 ||
      type === 0x16 || type === 0x17;
  }

  // 07:50C4-50F7 chooses the scan region and clears unused bytes in the
  // eight-byte comparison key. Named types and 5Dh names use the program/VAT
  // region; list classes additionally admit the FFh start sentinel. Other
  // list encodings, including 72h and 3Ah, use the fixed-token region. The
  // original OP1 is retained because the carry return restores it from OP3.
  function editorPrepareAlphaSearchKey(op1Value, label) {
    const original = editorNineByteBuffer(op1Value, label);
    const key = original.slice();
    const type = key[0] & 0x1f;
    const listClass = type === 0x01 || type === 0x0d;
    const namedRegion = editorAlphaNamedType(type) || key[1] === 0x5d ||
      (listClass && key[1] === 0xff);
    if (namedRegion) {
      let length = 8;
      for (let index = 1; index <= 8; index++) {
        if (key[index] === 0) {
          length = index - 1;
          break;
        }
      }
      // _CmpPrgNamLen treats the one-byte 5Dh list prefix as two bytes.
      if (length === 1 && key[1] === 0x5d) length = 2;
      for (let index = length + 1; index <= 8; index++) key[index] = 0;
    } else {
      // The fixed path enters the clearing loop with A=5, preserving only
      // the three name bytes represented by OP1+1 through OP1+3.
      for (let index = 4; index <= 8; index++) key[index] = 0;
    }
    return {original,key,namedRegion};
  }

  // Decode one contiguous VAT scan region from a 64 KiB RAM snapshot. The
  // region starts at a type cursor and ends just above the lower bound, which
  // matches the range test at 07:510B. Fixed entries step nine bytes. Named,
  // list, and type-09h entries use the marker/length step at 07:511F–5149.
  function editorDecodeAlphaVatRegion(ram, start, bound) {
    if (!(ram instanceof Uint8Array) || ram.length !== 0x10000)
      throw new TypeError('alphabetic VAT RAM snapshot must be 65536 bytes');
    if (!Number.isInteger(start) || start < 0 || start > 0xffff ||
        !Number.isInteger(bound) || bound < 0 || bound > 0xffff)
      throw new RangeError('alphabetic VAT region bounds must be unsigned words');
    if (start < bound)
      throw new RangeError(
        'alphabetic VAT region start must not fall below its bound');
    const entries = [];
    let cursor = start;
    while (cursor > bound) {
      if (cursor < 8)
        throw new RangeError('alphabetic VAT entry crosses the bottom of RAM');
      const type = ram[cursor] & 0x1f;
      const listClass = type === 0x01 || type === 0x0d;
      const named = editorAlphaNamedType(type);
      const variableStep = named || listClass || type === 0x09;
      let next = cursor - 9;
      let names;
      if (named || listClass) {
        let marker = cursor - 6;
        if (ram[marker] === 0x72 || ram[marker] === 0x3a) {
          names = [ram[cursor - 6],ram[cursor - 7],ram[cursor - 8]];
        } else {
          const storedCount = ram[marker];
          const copyCount = listClass ? storedCount - 1 : storedCount;
          if (copyCount < 0 || copyCount > 8)
            throw new RangeError(
              `alphabetic VAT entry at 0x${cursor.toString(16)} has invalid name length`);
          if (marker - storedCount - 1 < bound)
            throw new RangeError(
              `alphabetic VAT entry at 0x${cursor.toString(16)} crosses its bound`);
          names = Array.from({length:copyCount},
            (_unused,index) => ram[marker - 1 - index]);
          next = marker - storedCount - 1;
        }
      } else {
        names = [ram[cursor - 6],ram[cursor - 7],ram[cursor - 8]];
      }
      if (variableStep && !(named || listClass)) {
        let marker = cursor - 6;
        if (ram[marker] !== 0x72 && ram[marker] !== 0x3a) {
          next = marker - ram[marker] - 1;
        }
      }
      if (next >= cursor || next < bound)
        throw new RangeError(
          `alphabetic VAT entry at 0x${cursor.toString(16)} has an invalid next cursor`);
      const op1 = [type,...names.slice(0,8)];
      while (op1.length < 9) op1.push(0);
      entries.push({op1,pointer:cursor,page:ram[cursor - 5]});
      cursor = next;
    }
    if (cursor !== bound)
      throw new RangeError('alphabetic VAT entries do not end at the region bound');
    return entries;
  }

  function editorDecodeAlphaVatSnapshot(ram, op1Value, pointers = {}) {
    if (!(ram instanceof Uint8Array) || ram.length !== 0x10000)
      throw new TypeError('alphabetic VAT RAM snapshot must be 65536 bytes');
    const prepared = editorPrepareAlphaSearchKey(
      op1Value, 'alphabetic VAT snapshot OP1');
    if (!pointers || typeof pointers !== 'object' || Array.isArray(pointers))
      throw new TypeError('alphabetic VAT pointers must be an object');
    const wordAt = address => ram[address] | (ram[address + 1] << 8);
    const pTemp = pointers.pTemp === undefined ? wordAt(0x982e) : pointers.pTemp;
    const progPtr = pointers.progPtr === undefined ? wordAt(0x9830) : pointers.progPtr;
    const symTable = pointers.symTable === undefined ? 0xfe66 : pointers.symTable;
    for (const [label,value] of Object.entries({pTemp,progPtr,symTable})) {
      if (!Number.isInteger(value) || value < 0 || value > 0xffff)
        throw new RangeError(`alphabetic VAT ${label} must be an unsigned word`);
    }
    const namedRegion = prepared.namedRegion;
    const start = namedRegion ? progPtr : symTable;
    const bound = namedRegion ? pTemp : progPtr;
    return {
      region:namedRegion ? 'named/list' : 'fixed-token',
      start, bound, pTemp, progPtr, symTable,
      entries:editorDecodeAlphaVatRegion(ram,start,bound),
      routine:'07:50BE–50F9',
    };
  }

  // Translate the page-39 use of 07:50B5/50B8 over a logical VAT snapshot.
  // Each entry supplies its nine-byte OP-format identity and the address of
  // its VAT type byte. The 2.55MP routine discards caller A and always compares
  // normalized type classes. It keeps the nearest qualifying name in OP3 and
  // returns it in both OP1 and OP3 when the scan ends.
  function editorFindAlphaVat(direction, op1Value, vatSnapshot, context = {}) {
    if (direction !== 'up' && direction !== 'down')
      throw new RangeError('alphabetic VAT-search direction must be up or down');
    const prepared = editorPrepareAlphaSearchKey(
      op1Value, 'alphabetic VAT-search OP1');
    const op1 = prepared.original;
    const searchKey = prepared.key;
    if (!Array.isArray(vatSnapshot))
      throw new TypeError('alphabetic VAT snapshot must be an array');
    if (!context || typeof context !== 'object' || Array.isArray(context))
      throw new TypeError('alphabetic VAT-search context must be an object');
    const menuCurrent = context.menuCurrent === undefined ? 0 :
      byte(context.menuCurrent, 'alphabetic VAT-search MenuCurrent');
    const inGroup = context.inGroup === undefined ? false :
      boolean(context.inGroup, 'alphabetic VAT-search inGroup flag');
    const iy0Bit0 = context.iy0Bit0 === undefined ? false :
      boolean(context.iy0Bit0, 'alphabetic VAT-search IY+0 bit 0');
    const sourceClass = editorAlphaTypeClass(op1[0]);
    const unconditionalUp = searchKey[2] === 0xff;
    let selected = null;
    let compared = 0;
    const entries = vatSnapshot.map((entry, index) => {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry))
        throw new TypeError(`alphabetic VAT entry ${index} must be an object`);
      const identity = editorNineByteBuffer(
        entry.op1, `alphabetic VAT entry ${index} OP1`);
      if (!Number.isInteger(entry.pointer) || entry.pointer < 0 ||
          entry.pointer > 0xffff)
        throw new RangeError(
          `alphabetic VAT entry ${index} pointer must be an unsigned word`);
      const page = byte(entry.page, `alphabetic VAT entry ${index} page`);
      identity[0] &= 0x1f;
      return {identity, pointer:entry.pointer, page, index};
    });
    for (const entry of entries) {
      if (editorAlphaTypeClass(entry.identity[0]) !== sourceClass)
        continue;
      const firstName = entry.identity[1];
      const listClass = entry.identity[0] === 0x01 ||
        entry.identity[0] === 0x0d;
      if (listClass && (firstName === 0x72 || firstName === 0x3a))
        continue;
      if (listClass && firstName === 0x5d && entry.identity[2] === 0x40) {
        if (menuCurrent !== 0 || inGroup || !iy0Bit0)
          continue;
      } else {
        const gate = inGroup && entry.page !== 0 ? entry.page : firstName;
        if (gate < 0x41 || gate === 0x72)
          continue;
      }
      if (unconditionalUp && direction === 'down')
        continue;
      const relativeToSource = unconditionalUp ? 1 :
        editorAlphaNameCompare(entry.identity, searchKey);
      compared++;
      if ((direction === 'up' && relativeToSource <= 0) ||
          (direction === 'down' && relativeToSource >= 0))
        continue;
      if (selected !== null) {
        const relativeToBest = editorAlphaNameCompare(
          entry.identity, selected.identity);
        if ((direction === 'up' && relativeToBest >= 0) ||
            (direction === 'down' && relativeToBest <= 0))
          continue;
      }
      selected = entry;
    }
    if (selected === null)
      return {
        direction, sameType:true, sourceClass, carry:true, a:0xfe, zero:false,
        op1:op1.slice(), op3:op1.slice(), vatPointer:null,
        selectedIndex:null, compared, routine:direction === 'up'
          ? '07:50B5 (_FindAlphaUp)' : '07:50B8 (_FindAlphaDn)',
      };
    return {
      direction, sameType:true, sourceClass, carry:false, a:0, zero:true,
      op1:selected.identity.slice(), op3:selected.identity.slice(),
      vatPointer:selected.pointer, selectedIndex:selected.index, compared,
      routine:direction === 'up'
        ? '07:50B5 (_FindAlphaUp)' : '07:50B8 (_FindAlphaDn)',
    };
  }

  // 39:5B10/5B1D and 39:5B2B/5B38 wrap the ascending 59E0h and descending
  // 59F9h alphabetic VAT searches. Bit 5 of IY+11h gates the entire wrapper. An
  // enabled wrapper restores a nine-byte saved operand to OP1 before the
  // search call; carry returns immediately. Carry clear saves the search's
  // OP1 result back to the source scratch slot through 5AD2h (E7) or 5B08h
  // (F2). The dispatcher and page-7 VAT walk derive their result from the
  // restored buffer and the supplied VAT state.
  function editorSavedOperandWrapper(source, direction, recordFlags,
                                     buffers, searchState = {}) {
    if (source !== 'saved-E7' && source !== 'saved-F2')
      throw new RangeError('editor saved operand source must be saved-E7 or saved-F2');
    if (direction !== 'up' && direction !== 'down')
      throw new RangeError('editor saved operand direction must be up or down');
    byte(recordFlags, 'editor record flags');
    if (!buffers || typeof buffers !== 'object' || Array.isArray(buffers))
      throw new TypeError('editor saved operand buffers must be an object');
    if (!searchState || typeof searchState !== 'object' ||
        Array.isArray(searchState))
      throw new TypeError('editor saved operand search state must be an object');
    let op1 = editorNineByteBuffer(buffers.op1, 'editor OP1');
    let savedE7 = editorNineByteBuffer(buffers.savedE7, 'editor saved E7');
    let savedF2 = editorNineByteBuffer(buffers.savedF2, 'editor saved F2');
    const incomingCarry = searchState.incomingCarry === undefined ? false :
      boolean(searchState.incomingCarry, 'editor wrapper incoming carry');
    const entry = source === 'saved-E7'
      ? direction === 'up' ? '39:5B10' : '39:5B1D'
      : direction === 'up' ? '39:5B2B' : '39:5B38';
    const bit5Set = (recordFlags & 0x20) !== 0;
    const base = {
      source, direction, recordFlags, bit5Set, incomingCarry,
      searchRoutine:direction === 'up' ? '39:59E0' : '39:59F9',
      routine:entry,
    };
    if (!bit5Set)
      return {
        ...base, branch:'gated-return', searchCalled:false,
        searchInput:null, carry:incomingCarry, copies:[],
        buffers:{op1,savedE7,savedF2},
      };
    const restoreRoutine = source === 'saved-E7' ? '39:5AE1' : '39:5B00';
    const sourceBuffer = source === 'saved-E7' ? savedE7 : savedF2;
    op1 = sourceBuffer.slice();
    const searchInput = op1.slice();
    const copies = [{
      from:source === 'saved-E7' ? 0x85e7 : 0x85f2,
      to:0x8478, bytes:9, routine:`${restoreRoutine} → 00:1A92`,
    }];
    if (searchState.editorClass === undefined)
      throw new TypeError('enabled editor saved operand search requires editorClass');
    const editorClass = byte(
      searchState.editorClass, 'editor saved operand search class');
    const editorSubClass = searchState.editorSubClass === undefined ? 0 :
      byte(searchState.editorSubClass, 'editor saved operand search subclass');
    const alphaOptions = {...searchState,op1:searchInput,savedOperand:savedE7};
    delete alphaOptions.editorClass;
    delete alphaOptions.editorSubClass;
    delete alphaOptions.incomingCarry;
    const search = editorAlphaSearch(
      direction,editorClass,editorSubClass,alphaOptions);
    op1 = editorNineByteBuffer(search.op1, 'editor saved operand search OP1');
    if (search.carry)
      return {
        ...base, branch:'search-carry', searchCalled:true,
        searchInput, search, carry:true, copies,
        buffers:{op1,savedE7,savedF2},
      };
    if (source === 'saved-E7') savedE7 = op1.slice();
    else savedF2 = op1.slice();
    const saveAddress = source === 'saved-E7' ? 0x85e7 : 0x85f2;
    const saveRoutine = source === 'saved-E7' ? '39:5AD2' : '39:5B08';
    copies.push({
      from:0x8478, to:saveAddress, bytes:9,
      routine:`${saveRoutine} → 00:1A92`,
    });
    return {
      ...base, branch:'save-result', searchCalled:true,
      searchInput, search, carry:false, copies,
      buffers:{op1,savedE7,savedF2},
    };
  }

  // 39:59E0 and 39:59F9 are small local dispatchers around _FindAlphaUp and
  // _FindAlphaDn on page 7. They are easy to mistake for renderers because
  // they sit beside the row compositor, but their only local state is
  // 85DE/85DF and the flags returned by the cross-page VAT search. The caller
  // supplies OP1 and a logical or raw VAT snapshot; every search result is
  // derived by editorFindAlphaVat(). A protected-program result has type 06h,
  // so the 39:1942 post-check repeats until the search reaches another type or
  // the alphabetic endpoint.
  //
  // The class-2 paths are closed on page 39. The ascending path emits 0Dh and
  // finishes with the 14h OP1 seed at 39:59C6. The descending path inspects the
  // eight payload bytes at saved OP1+1 (39:5A2E), emit 0Ch, optionally cross
  // 39:1BAF when the emitter leaves carry set, and then use the same 14h
  // seed.  A carry returned by the 28h emitter is therefore an explicit
  // input, not a guessed parser result.
  function editorAlphaSearch(direction, editorClass, editorSubClass = 0,
                             options = {}) {
    if (direction !== 'up' && direction !== 'down')
      throw new RangeError('editor alpha-search direction must be up or down');
    byte(editorClass, 'editor alpha-search class');
    byte(editorSubClass, 'editor alpha-search subclass');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor alpha-search options must be an object');
    let currentOp1 = editorNineByteBuffer(
      options.op1, 'editor alpha-search OP1');
    const special = options.specialResult === undefined ? null : options.specialResult;
    if (special !== null && (!special || typeof special !== 'object' ||
                             Array.isArray(special)))
      throw new TypeError('editor alpha-search special result must be an object');
    const savedOperand = options.savedOperand === undefined ? null :
      editorNineByteBuffer(options.savedOperand, 'editor alpha-search saved OP1');
    const searchRoutine = direction === 'up'
      ? '00:3A53 → 07:50B5 (_FindAlphaUp)'
      : '00:306F → 07:50B8 (_FindAlphaDn)';
    const dispatcherRoutine = direction === 'up' ? '39:59E0' : '39:59F9';
    const effects = [];
    const base = {
      direction, editorClass, editorSubClass, dispatcherRoutine, searchRoutine,
      routine:dispatcherRoutine,
    };
    const requireCarry = (value, label) => {
      if (value === undefined)
        throw new TypeError(`${label} must supply carry`);
      return boolean(value, label);
    };
    const specialCarry = () => special === null ? false :
      requireCarry(special.carry, 'editor alpha-search special result');

    if (editorClass === 0x02) {
      if (special === null)
        throw new TypeError('class-2 operand path requires specialResult');
      if (direction === 'up') {
        effects.push({kind:'emit-token', code:0x0d,
          routine:'39:59AF → RST 28'});
        effects.push({kind:'seed-op1', code:0x14, address:0x8478,
          routine:'39:59C6'});
        currentOp1[0] = 0x14;
        return {
          ...base, branch:'class-2-special', specialPath:'39:59AF',
          carry:specialCarry(), op1:currentOp1.slice(), effects,
          unresolved:special.carry === undefined ? '00:0028' : null,
        };
      }
      const payloadEmpty = savedOperand === null ? null :
        savedOperand.slice(1).every(value => value === 0);
      effects.push({kind:'scan-saved-op1', address:0x85e7, bytes:8,
        payloadEmpty, routine:'39:5B23 → 39:5A2E'});
      effects.push({kind:'emit-token', code:0x0c,
        routine:'39:59B6 → RST 28'});
      const rstCarry = specialCarry();
      if (rstCarry) {
        if (special.call1BAFCarry === undefined)
          throw new TypeError('carrying descending class-2 path requires call1BAFCarry');
        const callCarry = boolean(special.call1BAFCarry,
          'editor alpha-search 39:1BAF carry');
        effects.push({kind:'call',routine:'39:1BAF',carry:callCarry});
      }
      effects.push({kind:'seed-op1', code:0x14, address:0x8478,
        routine:'39:59C6'});
      currentOp1[0] = 0x14;
      return {
        ...base, branch:'class-2-special', specialPath:'39:59B6',
        payloadEmpty, rstCarry, carry:rstCarry ? boolean(special.call1BAFCarry,
          'editor alpha-search 39:1BAF carry') : false,
        op1:currentOp1.slice(), effects,
        unresolved:rstCarry ? '39:1BAF' : null,
      };
    }

    let vatSnapshot = options.vatSnapshot;
    if (vatSnapshot === undefined && options.vatRam !== undefined)
      vatSnapshot = editorDecodeAlphaVatSnapshot(
        options.vatRam,currentOp1,options.vatPointers).entries;
    if (!Array.isArray(vatSnapshot))
      throw new TypeError(
        'non-class-2 alpha-search requires a logical or raw VAT snapshot');
    for (let index = 0; index <= vatSnapshot.length; index++) {
      const result = editorFindAlphaVat(direction,currentOp1,vatSnapshot,{
        ...(options.vatContext || {}), menuCurrent:editorClass,
      });
      effects.push({kind:'find-alpha',routine:searchRoutine,index,
        carry:result.carry, editorClass, editorSubClass,
        typeMode:'normalized-class', input:currentOp1.slice(),
        output:result.op1.slice(),
        vatPointer:result.vatPointer, selectedIndex:result.selectedIndex});
      if (result.carry)
        return {
          ...base, branch:'search-carry', loopCount:index,
          carry:true, op1:result.op1, op3:result.op3,
          vatPointer:null, effects,
          terminal:'return-carry',
        };
      const selected = editorClass === 0x03 && editorSubClass === 0x01;
      effects.push({kind:'class-3-subclass-1-check',selected,
        routine:'39:5C2E'});
      if (!selected)
        return {
          ...base, branch:'search-complete', loopCount:index,
          carry:false, op1:result.op1, op3:result.op3,
          vatPointer:result.vatPointer, effects, terminal:'return-clear',
        };
      const postCode = result.op1[0] & 0x1f;
      effects.push({kind:'post-search-call',routine:'39:1942',code:postCode});
      if (postCode !== 0x06)
        return {
          ...base, branch:'post-search-complete', loopCount:index,
          postCode, carry:false, op1:result.op1, op3:result.op3,
          vatPointer:result.vatPointer, effects, terminal:'return-clear',
        };
      effects.push({kind:'repeat-alpha-search',routine:dispatcherRoutine,
        reason:'post-search A=06'});
      currentOp1 = result.op1.slice();
    }
    throw new RangeError(`${dispatcherRoutine} repeated beyond the VAT snapshot`);
  }

  // 39:66FE temporarily moves the text cursor to row 1, column 1, emits the
  // forward-overflow code 1Eh, then restores the word at 844Bh. The cursor
  // restore makes the state transition independent of _PutC's own advance.
  function editorForwardOverflowCue() {
    return {
      direction:'forward', branch:'emit-cue', remainingArguments:null,
      emission:{row:1,column:1,code:0x1e}, cursorPreserved:true,
      routine:'39:66FE',
    };
  }

  // 39:66E9 subtracts the selected argument at 85E0h from the argument count
  // at 85E2h using byte arithmetic. Fewer than eight remaining arguments
  // return before drawing. Otherwise the routine emits code 1Fh at column 1
  // and row winBtm-1, including the 00h -> FFh wrap, then restores 844Bh.
  function editorReverseOverflowCue(argumentIndex, argumentCount, winBottom) {
    byte(argumentIndex, 'editor argument index');
    byte(argumentCount, 'editor argument count');
    byte(winBottom, 'editor window bottom');
    const remainingArguments = (argumentCount - argumentIndex) & 0xff;
    if (remainingArguments < 8)
      return {
        direction:'reverse', argumentIndex, argumentCount, winBottom,
        remainingArguments, branch:'return', emission:null,
        cursorPreserved:true, routine:'39:66E9',
      };
    return {
      direction:'reverse', argumentIndex, argumentCount, winBottom,
      remainingArguments, branch:'emit-cue',
      emission:{row:(winBottom - 1) & 0xff,column:1,code:0x1f},
      cursorPreserved:true, routine:'39:66E9',
    };
  }

  // 39:5167 advances the current multi-argument slot. Calls that fetch or
  // render parser operands are returned as ordered effects; the state changes
  // and branch predicates are translated directly from the routine.
  function editorAdvanceArgument(layoutClass, argumentIndex, argumentCount,
                                 currentRow, recordFlags, options = {}) {
    byte(layoutClass, 'editor layout class');
    byte(argumentIndex, 'editor argument index');
    byte(argumentCount, 'editor argument count');
    byte(currentRow, 'editor current row');
    byte(recordFlags, 'editor record flags');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor argument advance options must be an object');
    const winTop = options.winTop === undefined ? null :
      byte(options.winTop, 'editor window top');
    const layoutRow = options.layoutRow === undefined ? 0 :
      byte(options.layoutRow, 'editor layout row');
    const savedOperandState = options.savedOperandState === undefined
      ? null : options.savedOperandState;
    if (savedOperandState !== null &&
        (!savedOperandState || typeof savedOperandState !== 'object' ||
         Array.isArray(savedOperandState)))
      throw new TypeError('editor saved operand state must be an object');
    const initialBuffers = savedOperandState === null
      ? null : savedOperandState.buffers;
    const transitionFor = (source, state = initialBuffers) => {
      if (savedOperandState === null) return null;
      if (state === undefined)
        throw new TypeError('editor saved operand state requires buffers');
      const searchState = {...savedOperandState,
        editorClass:layoutClass,editorSubClass:layoutRow};
      delete searchState.buffers;
      return editorSavedOperandWrapper(
        source, 'up', recordFlags, state, searchState);
    };
    const base = {
      layoutClass, argumentIndex, argumentCount, currentRow, recordFlags,
      winTop, routine:'39:5167',
    };
    if (argumentCount === 0)
      return {
        ...base, lastArgument:null, nextArgument:argumentIndex, rowStep:0,
        placementRow:null, nextRow:null, branch:'empty',
        effects:[{kind:'set-row-for-token',routine:'39:5447'}],
        continuation:'row-token-tail',
      };
    const lastArgument = argumentCount - 1;
    if (argumentIndex >= lastArgument)
      return {
        ...base, lastArgument, nextArgument:argumentIndex, rowStep:0,
        placementRow:null, nextRow:null, branch:'at-or-past-last',
        effects:[{kind:'set-row-for-token',routine:'39:5447'}],
        continuation:'row-token-tail',
      };
    const nextArgument = (argumentIndex + 1) & 0xff;
    const rowStep = multiArgumentRowStep(layoutClass, argumentIndex);
    if (nextArgument === 0)
      return {
        ...base, lastArgument, nextArgument:argumentIndex, rowStep:0,
        placementRow:null, nextRow:null, branch:'argument-wrap-guard',
        effects:[
          {kind:'restore-argument-index'},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'row-token-tail',
      };
    const rowLimit = rowStep === 2 ? 6 : 7;
    if (currentRow < rowLimit) {
      const placementRow = (currentRow + rowStep) & 0xff;
      const e7Transition = transitionFor('saved-E7');
      return {
        ...base, lastArgument, nextArgument, rowStep, rowLimit,
        placementRow, nextRow:null,
        branch:'in-row',
        effects:[
          {kind:'emit-argument-index',argument:argumentIndex,routine:'39:4E0A'},
          {kind:'advance-row',rows:rowStep,value:placementRow},
          {kind:'emit-argument-index',argument:nextArgument,routine:'39:4E0A'},
          {kind:'find-alpha',direction:'up',source:'saved-E7',routine:'39:5B10',
            ...(e7Transition ? {transition:e7Transition} : {})},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'row-token-tail',
      };
    }
    // The class-06 two-row guard jumps directly to 51E5 before the styled
    // record-bit test. Rows 6 and 7 therefore always use 4C5A on that path.
    if (rowStep === 2 || (recordFlags & 0x20) === 0)
      return {
        ...base, lastArgument, nextArgument, rowStep, rowLimit,
        placementRow:currentRow, nextRow:null,
        branch:'subexpression-overflow',
        effects:[
          {kind:'emit-subexpression',routine:'39:4C5A'},
          {kind:'restore-row',value:currentRow},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'subexpression-window',
      };
    const f2Transition = transitionFor('saved-F2');
    if (f2Transition === null)
      return {
        ...base, lastArgument, nextArgument, rowStep, rowLimit,
        placementRow:null, nextRow:null, branch:'styled-overflow-unresolved',
        effects:[
          {kind:'find-alpha',direction:'up',source:'saved-F2',
            routine:'39:5B2B',unresolved:'VAT state'},
        ],
        continuation:'saved-F2-search',
      };
    if (f2Transition.carry)
      return {
        ...base, lastArgument, nextArgument, rowStep, rowLimit,
        savedF2Carry:true,
        placementRow:null, nextRow:null, branch:'styled-overflow-carry',
        effects:[
          {kind:'find-alpha',direction:'up',source:'saved-F2',routine:'39:5B2B',carry:true,
            ...(f2Transition ? {transition:f2Transition} : {})},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'row-token-tail',
      };
    const e7Transition = transitionFor('saved-E7',f2Transition.buffers);
    return {
      ...base, lastArgument, nextArgument, rowStep, rowLimit,
      savedF2Carry:false,
      placementRow:null, nextRow:null, branch:'styled-overflow',
      effects:[
        {kind:'find-alpha',direction:'up',source:'saved-F2',routine:'39:5B2B',carry:false,
          ...(f2Transition ? {transition:f2Transition} : {})},
        {kind:'emit-argument-index',argument:argumentIndex,routine:'39:4E0A'},
        {kind:'set-overflow',curCol:1,routine:'39:6712'},
        {kind:'save-window-top',value:winTop},
        {kind:'set-window-top',value:1},
        {kind:'scroll-editor',direction:'forward',routine:'39:3C81'},
        {kind:'find-alpha',direction:'up',source:'saved-E7',routine:'39:5B10',
          ...(e7Transition ? {transition:e7Transition} : {})},
        {kind:'emit-saved-operand-tail',argument:nextArgument,routine:'39:5B46'},
        {kind:'finish-forward-overflow',...editorForwardOverflowCue()},
        {kind:'restore-window-top',value:winTop},
        {kind:'set-row-for-token',routine:'39:5447'},
      ],
      continuation:'row-token-tail',
    };
  }

  // 39:523B is the reverse half of the action-03 argument walker. It first
  // decrements 85E0, then chooses the row step from the new slot. A supplied
  // saved-operand state executes the wrapper and VAT-search transitions.
  // Parser and scroll bodies remain ordered effects.
  function editorRetreatArgument(layoutClass, argumentIndex, argumentCount,
                                 currentRow, baselineRow, recordFlags,
                                 options = {}) {
    byte(layoutClass, 'editor layout class');
    byte(argumentIndex, 'editor argument index');
    byte(argumentCount, 'editor argument count');
    byte(currentRow, 'editor current row');
    byte(baselineRow, 'editor baseline row');
    byte(recordFlags, 'editor record flags');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor argument retreat options must be an object');
    const winTop = options.winTop === undefined ? null :
      byte(options.winTop, 'editor window top');
    const winBottom = options.winBottom === undefined ? null :
      byte(options.winBottom, 'editor window bottom');
    const layoutRow = options.layoutRow === undefined ? 0 :
      byte(options.layoutRow, 'editor layout row');
    const savedOperandState = options.savedOperandState === undefined
      ? null : options.savedOperandState;
    if (savedOperandState !== null &&
        (!savedOperandState || typeof savedOperandState !== 'object' ||
         Array.isArray(savedOperandState)))
      throw new TypeError('editor saved operand state must be an object');
    const initialBuffers = savedOperandState === null
      ? null : savedOperandState.buffers;
    const transitionFor = (source, state = initialBuffers) => {
      if (savedOperandState === null) return null;
      if (state === undefined)
        throw new TypeError('editor saved operand state requires buffers');
      const searchState = {...savedOperandState,
        editorClass:layoutClass,editorSubClass:layoutRow};
      delete searchState.buffers;
      return editorSavedOperandWrapper(
        source, 'down', recordFlags, state, searchState);
    };
    const base = {
      layoutClass, argumentIndex, argumentCount, currentRow, baselineRow,
      recordFlags, winTop, routine:'39:523B',
    };
    if (argumentIndex === 0)
      return {
        ...base, nextArgument:0, rowStep:0, placementRow:null, nextRow:null,
        branch:'at-first', effects:[], continuation:'action-03-first-argument',
      };
    const nextArgument = argumentIndex - 1;
    const rowStep = multiArgumentRowStep(layoutClass, nextArgument);
    const twoRowUnderflow = rowStep === 2 && currentRow < 3;
    if (!twoRowUnderflow && currentRow > baselineRow) {
      const placementRow = (currentRow - rowStep) & 0xff;
      const e7Transition = transitionFor('saved-E7');
      return {
        ...base, nextArgument, rowStep, twoRowUnderflow,
        placementRow, nextRow:null, branch:'in-row',
        effects:[
          {kind:'emit-argument-index',argument:argumentIndex,routine:'39:4E0A'},
          {kind:'retreat-row',rows:rowStep,value:placementRow},
          {kind:'emit-argument-index',argument:nextArgument,routine:'39:4E0A'},
          {kind:'find-alpha',direction:'down',source:'saved-E7',routine:'39:5B1D',
            ...(e7Transition ? {transition:e7Transition} : {})},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'row-token-tail',
      };
    }
    // The two-row underflow jump reaches 51E6 before the styled-record test.
    if (twoRowUnderflow || (recordFlags & 0x20) === 0)
      return {
        ...base, nextArgument, rowStep, twoRowUnderflow,
        placementRow:currentRow, nextRow:null,
        branch:'subexpression-overflow',
        effects:[
          {kind:'emit-subexpression',routine:'39:4C5A'},
          {kind:'restore-row',value:currentRow},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'subexpression-window',
      };
    const f2Transition = transitionFor('saved-F2');
    if (f2Transition === null)
      return {
        ...base, nextArgument, rowStep, twoRowUnderflow,
        placementRow:null, nextRow:null, branch:'styled-overflow-unresolved',
        effects:[
          {kind:'find-alpha',direction:'down',source:'saved-F2',
            routine:'39:5B38',unresolved:'VAT state'},
        ],
        continuation:'saved-F2-search',
      };
    if (f2Transition.carry)
      return {
        ...base, nextArgument, rowStep, twoRowUnderflow,
        savedF2Carry:true,
        placementRow:null, nextRow:null, branch:'styled-overflow-carry',
        effects:[
          {kind:'find-alpha',direction:'down',source:'saved-F2',routine:'39:5B38',carry:true,
            ...(f2Transition ? {transition:f2Transition} : {})},
          {kind:'set-row-for-token',routine:'39:5447'},
        ],
        continuation:'row-token-tail',
      };
    const remainingArguments = (argumentCount - nextArgument) & 0xff;
    const e7Transition = transitionFor('saved-E7',f2Transition.buffers);
    return {
      ...base, nextArgument, rowStep, twoRowUnderflow,
      savedF2Carry:false,
      placementRow:null, nextRow:null, remainingArguments,
      branch:'styled-overflow',
      effects:[
        {kind:'find-alpha',direction:'down',source:'saved-F2',routine:'39:5B38',carry:false,
          ...(f2Transition ? {transition:f2Transition} : {})},
        {kind:'emit-argument-index',argument:argumentIndex,routine:'39:4E0A'},
        {kind:'set-overflow',curCol:1,routine:'39:6712'},
        {kind:'save-window-top',value:winTop},
        {kind:'set-window-top',value:1},
        {kind:'scroll-editor',direction:'reverse',routine:'39:3C93'},
        {kind:'find-alpha',direction:'down',source:'saved-E7',routine:'39:5B1D',
          ...(e7Transition ? {transition:e7Transition} : {})},
        {kind:'emit-saved-operand-tail',argument:nextArgument,routine:'39:5B46'},
        {kind:'finish-reverse-overflow',remainingArguments,
          branch:remainingArguments < 8 ? 'return' : 'window-bottom',
          cue:winBottom === null ? null : editorReverseOverflowCue(
            nextArgument, argumentCount, winBottom),
          routine:'39:66E9'},
        {kind:'restore-window-top',value:winTop},
        {kind:'set-row-for-token',routine:'39:5447'},
      ],
      continuation:'row-token-tail',
    };
  }

  // Action 03 at 39:51F1 either delegates to the reverse walker, returns
  // through the row-token tail, runs the short-list call loop, or selects the
  // last visible argument of a list with at least eight entries. The short
  // path is a byte-counter do-while loop: a zero count therefore calls 5167h
  // 256 times. Calls whose parser/display bodies remain open are kept as
  // ordered effects instead of manufacturing their resulting row state.
  function editorFirstArgumentAction(layoutClass, argumentIndex, argumentCount,
                                     currentRow, baselineRow, recordFlags,
                                     options = {}) {
    byte(layoutClass, 'editor layout class');
    byte(argumentIndex, 'editor argument index');
    byte(argumentCount, 'editor argument count');
    byte(currentRow, 'editor current row');
    byte(baselineRow, 'editor baseline row');
    byte(recordFlags, 'editor record flags');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor first-argument options must be an object');
    const editorFlags = options.editorFlags === undefined ? 0 :
      byte(options.editorFlags, 'editor IY+1Dh flags');
    const editorFlagBit0 = (editorFlags & 1) !== 0;
    const base = {
      layoutClass, argumentIndex, argumentCount, currentRow, baselineRow,
      recordFlags, editorFlags, editorFlagBit0, routine:'39:51F1',
    };
    if (argumentIndex !== 0)
      return {
        ...base, iterations:null, finalArgument:null, firstVisibleSlot:null,
        preCallRow:null, finalRow:null, branch:'reverse-walker',
        effects:[{kind:'delegate-reverse-argument',routine:'39:523B'}],
        delegate:editorRetreatArgument(
          layoutClass, argumentIndex, argumentCount, currentRow, baselineRow,
          recordFlags, options),
        continuation:'reverse-walker',
      };
    if (editorFlagBit0)
      return {
        ...base, iterations:0, finalArgument:0, firstVisibleSlot:null,
        preCallRow:null, highlightRow:null, finalRow:null,
        branch:'row-token-tail',
        effects:[{kind:'set-row-for-token',routine:'39:51EE → 39:5447'}],
        continuation:'row-token-tail',
      };
    if (argumentCount < 8) {
      const iterations = argumentCount === 0 ? 0x100 : argumentCount;
      const finalArgument = argumentCount === 0 ? 0 : argumentCount - 1;
      return {
        ...base, iterations, finalArgument, firstVisibleSlot:null,
        preCallRow:null, highlightRow:null, finalRow:null,
        branch:'short-list-loop',
        effects:[
          {kind:'set-loop-counter',address:0x844d,value:argumentCount},
          {kind:'repeat-call-advance-argument',iterations,
            counterAddress:0x844d,counterFinal:0,
            counterUpdate:'decrement-after-call',routine:'39:50A1 → 39:5167'},
          {kind:'set-row-for-token',routine:'39:50AD → 39:5447'},
        ],
        continuation:'row-token-tail',
      };
    }
    const finalArgument = argumentCount - 1;
    const firstVisibleSlot = (argumentCount - 8 + baselineRow) & 0xff;
    const preCallRow = (baselineRow - 1) & 0xff;
    return {
      ...base, iterations:0, finalArgument, firstVisibleSlot, preCallRow,
      highlightRow:7, finalRow:null, branch:'last-visible-argument',
      effects:[
        {kind:'clear-saved-F2',address:0x85f2,value:0},
        {kind:'set-argument-index',value:finalArgument},
        {kind:'lookup-handler-row',rowSource:0x85df,routine:'39:4DCA'},
        {kind:'set-row',value:preCallRow},
        {kind:'emit-subexpression-from-slot',slot:firstVisibleSlot,
          routine:'39:4CA4'},
        {kind:'set-row-column',row:7,column:0},
        {kind:'emit-highlighted-argument',argument:finalArgument,routine:'39:4E14'},
        {kind:'set-row-for-token',routine:'39:51EE → 39:5447'},
      ],
      continuation:'row-token-tail',
    };
  }

  // Action 04 at 39:52A5 computes the unsigned-byte distance from the current
  // argument to count-1 once. A nonzero result calls 5167h once; 52B6h then
  // jumps to the row-token tail at 52A2h. Only an initially zero difference
  // reaches the IY+1Dh flag test. On that flag-clear exit A remains zero, so
  // 513Eh lays out argument zero.
  function editorAdvanceAction(layoutClass, argumentIndex, argumentCount,
                               currentRow, recordFlags, options = {}) {
    byte(layoutClass, 'editor layout class');
    byte(argumentIndex, 'editor argument index');
    byte(argumentCount, 'editor argument count');
    byte(currentRow, 'editor current row');
    byte(recordFlags, 'editor record flags');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('editor advance-action options must be an object');
    const editorFlags = options.editorFlags === undefined ? 0 :
      byte(options.editorFlags, 'editor IY+1Dh flags');
    const editorFlagBit0 = (editorFlags & 1) !== 0;
    const baselineRow = options.baselineRow === undefined ? null :
      byte(options.baselineRow, 'editor baseline row');
    const kbdKey = options.kbdKey === undefined ? null :
      byte(options.kbdKey, 'editor keyboard key');
    const lastArgument = (argumentCount - 1) & 0xff;
    const delta = (lastArgument - argumentIndex) & 0xff;
    const base = {
      layoutClass, argumentIndex, argumentCount, currentRow, recordFlags,
      lastArgument, delta, editorFlags, editorFlagBit0, baselineRow, kbdKey,
      routine:'39:52A5',
    };
    if (delta !== 0) {
      const delegate = editorAdvanceArgument(
        layoutClass, argumentIndex, argumentCount, currentRow, recordFlags,
        options);
      return {
        ...base, advanceCalls:1, layout:null, delegate,
        branch:'advance-once',
        effects:[
          {kind:'delegate-advance-argument',routine:'39:52B3 → 39:5167'},
          {kind:'set-row-for-token',routine:'39:52B6 → 39:52A2 → 39:5447'},
        ],
        continuation:'row-token-tail',
      };
    }
    if (editorFlagBit0)
      return {
        ...base, advanceCalls:0, layout:null, delegate:null,
        branch:'row-token-tail',
        effects:[
          {kind:'set-row-for-token',routine:'39:52A2 → 39:5447'},
        ],
        continuation:'row-token-tail',
      };
    const layoutOptions = {};
    if (baselineRow !== null) layoutOptions.baselineRow = baselineRow;
    if (kbdKey !== null) layoutOptions.kbdKey = kbdKey;
    const layout = editorLayoutArgument(0, argumentCount, layoutOptions);
    return {
      ...base, advanceCalls:0, layout, delegate:null,
      branch:'layout-first-argument',
      effects:[
        {kind:'layout-argument',argument:0,routine:'39:513E'},
      ],
      continuation:'argument-layout',
    };
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

  // 39:69C8 selects the descriptor family after the fixed kind-0, kind-1, and
  // kind-2 exits. The two RAM helpers are BIT 6 and BIT 5 of (IY+2), each
  // returning Z when its flag is clear. Keep the flag byte explicit because it
  // is caller state, not part of the template-kind argument.
  function selectDescriptor(layout, kind, options = undefined) {
    byte(kind, 'template kind');
    const nibble = kind & 0x0f;
    if (nibble === 0) return {
      kind: 'descriptor', descriptor: descriptor(layout, 0x686f),
      normalizedKind: 0x10,
    };
    if (nibble === 1) return {
      kind: 'descriptor', descriptor: descriptor(layout, 0x6880),
      normalizedKind: 0x11,
    };
    if (nibble === 2) return { kind: 'measuredFraction', routine: '39:6A8A' };
    if (options === undefined) return {
      kind: 'unresolvedDescriptorFamily', templateKind: nibble,
      missing: 'ram:025E/0254 flag02 state (BIT 6, then BIT 5)',
    };
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('descriptor selector options must be an object');
    const flag02 = options.flag02;
    byte(flag02, 'descriptor selector flag02');
    if (flag02 & 0x40)
      return {
        kind: 'descriptor', descriptor: descriptor(layout, 0x689c),
        normalizedKind: nibble + 0x20,
      };
    if (flag02 & 0x20)
      return {
        kind: 'descriptor', descriptor: descriptor(layout, 0x68a5),
        normalizedKind: nibble + 0x30,
      };
    return {
      kind: 'descriptor', descriptor: descriptor(layout, 0x6893),
      normalizedKind: nibble + 0x10,
    };
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

  // The editable-entry path keeps the record origin and horizontal clip in
  // separate words. 34:5DBE adds ram:8DFE to a local x coordinate, and
  // 34:5DC2 subtracts ram:8E02. 34:5F5D performs its endpoint, cursor, caller
  // padding, and right-bound arithmetic as 16-bit Z80 operations. An endpoint
  // left of the previous clip clears that clip before continuing. (IY+44h).3
  // selects a six-pixel cursor when set and a five-pixel cursor when clear.
  function settledEditorViewport(expressionEndpoint, options = {}) {
    const unsignedWord = (value, label) => {
      if (!Number.isInteger(value) || value < 0 || value > 0xffff)
        throw new RangeError(`${label} must fit an unsigned word`);
      return value;
    };
    const endpoint = unsignedWord(
      expressionEndpoint, 'settled editor expression endpoint');
    const previousXClip = unsignedWord(
      options.previousXClip === undefined ? 0 : options.previousXClip,
      'settled editor previous horizontal clip');
    const iy44Bit3 = options.iy44Bit3 === undefined ? true :
      boolean(options.iy44Bit3, 'settled editor IY+44h bit 3');
    const cursorWidth = iy44Bit3 ? 6 : 5;
    const extraWidth = unsignedWord(
      options.extraWidth === undefined ? 0 : options.extraWidth,
      'settled editor caller width');
    if (extraWidth !== 0 && extraWidth !== 3)
      throw new RangeError('settled editor caller width must be zero or three');
    const rightBound = byte(
      options.rightBound === undefined ? 0x5f : options.rightBound,
      'settled editor right bound');
    const xOrigin = unsignedWord(
      options.xOrigin === undefined ? 0 : options.xOrigin,
      'settled editor x origin');
    const yOrigin = unsignedWord(
      options.yOrigin === undefined ? 0 : options.yOrigin,
      'settled editor y origin');
    const screenXOrigin = byte(
      options.screenXOrigin === undefined ? 0 : options.screenXOrigin,
      'settled editor screen x origin');
    const wordAdd = (left, right) => (left + right) & 0xffff;
    const resetPreviousClip = endpoint < previousXClip;
    let xClip = resetPreviousClip ? 0 : previousXClip;
    let comparisonCoordinate = resetPreviousClip
      ? endpoint : (endpoint - previousXClip) & 0xffff;
    comparisonCoordinate = wordAdd(comparisonCoordinate, cursorWidth);
    comparisonCoordinate = wordAdd(comparisonCoordinate, extraWidth);
    const beforeRightBound = comparisonCoordinate < rightBound;
    if (!beforeRightBound)
      xClip = wordAdd(
        (comparisonCoordinate - rightBound) & 0xffff, xClip);
    return {
      expressionEndpoint:endpoint,
      previousXClip,
      resetPreviousClip,
      iy44Bit3,
      cursorWidth,
      extraWidth,
      rightBound,
      xOrigin,
      yOrigin,
      screenXOrigin,
      xClip,
      effectiveX:xOrigin - xClip + screenXOrigin,
      cursorX:endpoint + xOrigin - xClip + screenXOrigin,
      comparisonCoordinate,
      branch:beforeRightBound ? 'return-before-right-bound' :
        'store-horizontal-clip',
      branchOutcomes:[
        `34:5F64:${resetPreviousClip ? 'fallthrough' : 'taken'}`,
        `34:5F75:${iy44Bit3 ? 'taken' : 'fallthrough'}`,
        `34:5F81:${beforeRightBound ? 'returned' : 'fallthrough'}`,
      ],
      routine:'34:5F5D–5F8A; applied by 34:5DBE–5DC9',
    };
  }

  // 34:5F8B–5FC0 is the vertical counterpart to 34:5F5D. 8518h holds
  // the logical top row of the entry cursor. The routine subtracts the
  // previous 8E04h clip, adds a seven-row cursor when (IY+44h).3 is set or a
  // five-row cursor when it is clear, adds the caller's optional four rows,
  // and keeps the result below the low byte at 8DFDh. All arithmetic before
  // the low-byte bound comparison is 16-bit and wraps like the Z80.
  function settledEditorVerticalViewport(cursorTop, options = {}) {
    const unsignedWord = (value, label) => {
      if (!Number.isInteger(value) || value < 0 || value > 0xffff)
        throw new RangeError(`${label} must fit an unsigned word`);
      return value;
    };
    const top = unsignedWord(cursorTop, 'settled editor cursor top');
    const previousYClip = unsignedWord(
      options.previousYClip === undefined ? 0 : options.previousYClip,
      'settled editor previous vertical clip');
    const iy44Bit3 = options.iy44Bit3 === undefined ? true :
      boolean(options.iy44Bit3, 'settled editor IY+44h bit 3');
    const cursorHeight = iy44Bit3 ? 7 : 5;
    const extraHeight = unsignedWord(
      options.extraHeight === undefined ? 0 : options.extraHeight,
      'settled editor vertical caller height');
    if (extraHeight !== 0 && extraHeight !== 4)
      throw new RangeError(
        'settled editor vertical caller height must be zero or four');
    const bottomBound = byte(
      options.bottomBound === undefined ? 0x3e : options.bottomBound,
      'settled editor vertical bound');
    const yOrigin = unsignedWord(
      options.yOrigin === undefined ? 0 : options.yOrigin,
      'settled editor y origin');
    const screenYOrigin = byte(
      options.screenYOrigin === undefined ? 0 : options.screenYOrigin,
      'settled editor screen y origin');
    const resetPreviousClip = top < previousYClip;
    let yClip = resetPreviousClip ? 0 : previousYClip;
    let comparisonCoordinate = resetPreviousClip
      ? top : (top - previousYClip) & 0xffff;
    comparisonCoordinate = (comparisonCoordinate + cursorHeight) & 0xffff;
    comparisonCoordinate = (comparisonCoordinate + extraHeight) & 0xffff;
    const beforeBottomBound = comparisonCoordinate < bottomBound;
    if (!beforeBottomBound)
      yClip = (comparisonCoordinate - bottomBound + yClip) & 0xffff;
    return {
      cursorTop:top,
      previousYClip,
      resetPreviousClip,
      iy44Bit3,
      cursorHeight,
      extraHeight,
      bottomBound,
      yOrigin,
      screenYOrigin,
      yClip,
      effectiveY:yOrigin - yClip + screenYOrigin,
      cursorY:top + yOrigin - yClip + screenYOrigin,
      comparisonCoordinate,
      branch:beforeBottomBound ? 'return-before-bottom-bound' :
        'store-vertical-clip',
      branchOutcomes:[
        `34:5F96:${resetPreviousClip ? 'fallthrough' : 'taken'}`,
        `34:5FA7:${iy44Bit3 ? 'taken' : 'fallthrough'}`,
        `34:5FB7:${beforeBottomBound ? 'returned' : 'fallthrough'}`,
      ],
      routine:'34:5F8B–5FC0; applied by 34:6BE5–6BFC and 34:67C8–6872',
    };
  }

  // The live editor calls 34:5F8B first with DE=0 and, on the MathPrint
  // redraw path, again with DE=4. Preserve both state transitions rather than
  // collapsing them into one arithmetic shortcut: the first call can clear a
  // stale clip before the second call observes it.
  function settledEditorViewport2D(expressionEndpoint, cursorTop, options = {}) {
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('settled 2-D editor viewport options must be an object');
    const horizontal = settledEditorViewport(expressionEndpoint, options);
    const firstVertical = settledEditorVerticalViewport(cursorTop, {
      previousYClip:options.previousYClip,
      iy44Bit3:options.iy44Bit3,
      extraHeight:0,
      bottomBound:options.bottomBound,
      yOrigin:options.yOrigin,
      screenYOrigin:options.screenYOrigin,
    });
    const secondVertical = settledEditorVerticalViewport(cursorTop, {
      previousYClip:firstVertical.yClip,
      iy44Bit3:options.iy44Bit3,
      extraHeight:options.extraHeight === undefined ? 4 : options.extraHeight,
      bottomBound:options.bottomBound,
      yOrigin:options.yOrigin,
      screenYOrigin:options.screenYOrigin,
    });
    return {
      ...horizontal,
      cursorTop:secondVertical.cursorTop,
      previousYClip:firstVertical.previousYClip,
      yClip:secondVertical.yClip,
      effectiveY:secondVertical.effectiveY,
      cursorY:secondVertical.cursorY,
      cursorHeight:secondVertical.cursorHeight,
      extraHeight:secondVertical.extraHeight,
      bottomBound:secondVertical.bottomBound,
      screenYOrigin:secondVertical.screenYOrigin,
      verticalPasses:[firstVertical,secondVertical],
    };
  }

  // 34:67C8–6872 rejects a complete glyph cell above or below the active
  // vertical window. A crossing cell remains admitted; 9D01h and 9B72h then
  // select its visible rows. The small-font path uses a five-row cell and the
  // large-font path uses seven rows.
  function settledGlyphVerticalViewportDecision(
    logicalTop, depth, yClip, bottomBound = 0x3e) {
    unsignedWord(logicalTop, 'settled glyph logical top');
    byte(depth, 'settled glyph depth');
    unsignedWord(yClip, 'settled glyph vertical clip');
    byte(bottomBound, 'settled glyph vertical bound');
    const cellHeight = depth === 0 ? 7 : 5;
    const bottomExclusive = addWord(yClip,bottomBound);
    if (logicalTop < yClip) {
      const endpoint = addWord(logicalTop,cellHeight);
      if (endpoint <= yClip) return {
        action:'skip-above', logicalTop, endpoint, cellHeight,
        yClip, bottomExclusive,
        branchOutcomes:['34:67E6:fallthrough',
          `34:67EE:${depth === 0 ? 'taken' : 'fallthrough'}`,
          `34:67F7:${endpoint < yClip ? 'taken' : 'fallthrough'}`,
          ...(endpoint === yClip ? ['34:67FA:taken'] : []),
        ],
      };
      return {
        action:'clip-top', logicalTop, endpoint, cellHeight,
        yClip, bottomExclusive, topRows:yClip - logicalTop,
        visibleRows:cellHeight - (yClip - logicalTop),
      };
    }
    if (bottomExclusive <= logicalTop) return {
      action:'skip-below', logicalTop, endpoint:addWord(logicalTop,cellHeight),
      cellHeight, yClip, bottomExclusive,
      branchOutcomes:['34:67E6:taken','34:6827:taken'],
    };
    const endpoint = addWord(logicalTop,cellHeight);
    if (endpoint > bottomExclusive) return {
      action:'clip-bottom', logicalTop, endpoint, cellHeight,
      yClip, bottomExclusive, visibleRows:bottomExclusive - logicalTop,
    };
    return {
      action:'draw', logicalTop, endpoint, cellHeight,
      yClip, bottomExclusive, visibleRows:cellHeight,
    };
  }

  // 34:6C5F–6C87 performs both glyph gates in logical word coordinates.
  // The right comparison uses the glyph advance, not its set-pixel bounding
  // box, and every addition wraps before the unsigned compare.
  function settledGlyphViewportDecision(
    logicalPen, advance, xClip, rightBound = 0x5f) {
    for (const [value,label] of [
      [logicalPen,'settled glyph logical pen'],
      [advance,'settled glyph advance'],
      [xClip,'settled glyph horizontal clip'],
    ]) if (!Number.isInteger(value) || value < 0 || value > 0xffff)
      throw new RangeError(`${label} must fit an unsigned word`);
    byte(rightBound, 'settled glyph right bound');
    if (logicalPen < xClip) return {
      action:'skip-left',
      logicalPen,
      endpoint:null,
      rightExclusive:null,
      branchOutcomes:['34:6C69:taken'],
    };
    const endpoint = (logicalPen + advance) & 0xffff;
    const rightExclusive = (xClip + rightBound + 1) & 0xffff;
    const skipRight = rightExclusive < endpoint;
    return {
      action:skipRight ? 'skip-right' : 'draw',
      logicalPen,
      endpoint,
      rightExclusive,
      branchOutcomes:[
        '34:6C69:fallthrough',
        `34:6C7F:${skipRight ? 'fallthrough' : 'taken'}`,
      ],
    };
  }

  // 34:6641–6659 adds an embedded record's +09h width to the current
  // logical pen and record origin, then applies 34:5DC2's word subtraction.
  // Carry skips the complete embedded renderer; equality remains visible.
  function settledEmbeddedViewportDecision(logicalEndpoint, xClip) {
    for (const [value,label] of [
      [logicalEndpoint,'settled embedded logical endpoint'],
      [xClip,'settled embedded horizontal clip'],
    ]) if (!Number.isInteger(value) || value < 0 || value > 0xffff)
      throw new RangeError(`${label} must fit an unsigned word`);
    const translatedEndpoint = (logicalEndpoint - xClip) & 0xffff;
    const skipLeft = logicalEndpoint < xClip;
    return {
      action:skipLeft ? 'skip-left' : 'draw',
      logicalEndpoint,
      translatedEndpoint,
      branchOutcomes:[`34:6659:${skipLeft ? 'taken' : 'fallthrough'}`],
    };
  }

  const SETTLED_LEFT_OVERFLOW_ROWS = Object.freeze([
    0x00,0x02,0x06,0x0e,0x06,0x02,0x00,
  ]);
  const SETTLED_RIGHT_OVERFLOW_ROWS = Object.freeze([
    0x00,0x04,0x06,0x07,0x06,0x04,0x00,
  ]);
  const SETTLED_VERTICAL_UP_ROWS = Object.freeze([
    0x08,0x1c,0x3e,0x00,
  ]);
  const SETTLED_VERTICAL_DOWN_ROWS = Object.freeze([
    0x00,0x3e,0x1c,0x08,
  ]);

  // 34:6031 and 34:608F share the placement tail at 34:603A. Editor mode
  // 49h uses ram:8DFDh directly. Other modes load the root +07h height word
  // through 34:753F and clamp either a nonzero high byte or an oversized low
  // byte to the same bound. The final coordinates are stored as bytes at
  // 86D7h/86D8h, and use the screen origins at 8DFAh/8DFBh rather than the
  // logical record origins at 8DFEh/8E00h.
  function settledEditorHorizontalCuePlacement(
    viewport, recordHeight, options = {}) {
    if (!viewport || typeof viewport !== 'object')
      throw new TypeError('settled horizontal-cue viewport state is invalid');
    if (!Number.isInteger(recordHeight) ||
        recordHeight < 1 || recordHeight > 0xffff)
      throw new RangeError(
        'settled horizontal-cue record height must fit an unsigned word');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('settled horizontal-cue options must be an object');
    const bottomBound = byte(
      viewport.bottomBound === undefined ? 0x3e : viewport.bottomBound,
      'settled horizontal-cue bottom bound');
    const screenXOrigin = byte(
      viewport.screenXOrigin === undefined ? 0 : viewport.screenXOrigin,
      'settled horizontal-cue screen x origin');
    const screenYOrigin = byte(
      viewport.screenYOrigin === undefined ? 0 : viewport.screenYOrigin,
      'settled horizontal-cue screen y origin');
    const editorMode = byte(
      options.editorMode === undefined ? 0 : options.editorMode,
      'settled horizontal-cue editor mode');
    const mode49 = editorMode === 0x49;
    const highByteNonzero = recordHeight > 0xff;
    const lowByteExceedsBound = !highByteNonzero && recordHeight > bottomBound;
    const cueHeight = mode49 || highByteNonzero || lowByteExceedsBound
      ? bottomBound : recordHeight;
    return {
      cueHeight,
      screenXOrigin,
      screenYOrigin,
      y:(screenYOrigin + (cueHeight >>> 1) - 3) & 0xff,
      editorMode,
      bottomBound,
      branchOutcomes:[
        `34:603E:${mode49 ? 'taken' : 'fallthrough'}`,
        ...(mode49 ? [] : [
          `34:6045:${highByteNonzero ? 'taken' : 'fallthrough'}`,
          ...(highByteNonzero ? [] : [
            `34:604B:${lowByteExceedsBound ? 'taken' : 'fallthrough'}`,
          ]),
        ]),
      ],
      routine:'34:603A–6059; height load at 34:753F',
    };
  }

  // 34:6000–6015 draws editor chrome after the settled record. A nonzero
  // ram:8E04 clip calls bcall 53DAh for the upper cue. 34:60A0–60B7 loads
  // the root's height word, subtracts one and the vertical clip, and calls
  // bcall 53D7h when the remaining endpoint reaches or exceeds ram:8DFDh's
  // bottom boundary. The bcall bodies are 35:7116 and 35:715B.
  function settledEditorVerticalCueOperations(
    viewport, recordHeight, options = {}) {
    if (!viewport || typeof viewport !== 'object' ||
        !Number.isInteger(viewport.xOrigin) ||
        !Number.isInteger(viewport.yClip) ||
        !Number.isInteger(viewport.bottomBound))
      throw new TypeError('settled vertical-cue viewport state is invalid');
    if (!Number.isInteger(recordHeight) ||
        recordHeight < 1 || recordHeight > 0xffff)
      throw new RangeError(
        'settled vertical-cue record height must fit an unsigned word');
    if (!options || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('settled vertical-cue options must be an object');
    const yClip = unsignedWord(
      viewport.yClip, 'settled vertical-cue clip');
    const bottomBound = byte(
      viewport.bottomBound, 'settled vertical-cue bottom bound');
    const screenXOrigin = byte(
      viewport.screenXOrigin === undefined ? 0 : viewport.screenXOrigin,
      'settled vertical-cue screen x origin');
    const screenYOrigin = byte(
      viewport.screenYOrigin === undefined ? 0 : viewport.screenYOrigin,
      'settled vertical-cue y origin');
    const editorMode = byte(
      options.editorMode === undefined ? 0 : options.editorMode,
      'settled vertical-cue editor mode');
    const horizontalBound = byte(
      options.horizontalBound === undefined
        ? (viewport.rightBound === undefined ? 0x5f : viewport.rightBound)
        : options.horizontalBound,
      'settled vertical-cue horizontal bound');
    const x = editorMode === 0x49
      ? (screenXOrigin - 7) & 0xff
      : (screenXOrigin + (horizontalBound >>> 1) - 3) & 0xff;
    const endpoint = (recordHeight - 1) & 0xffff;
    const endpointBeforeClip = endpoint < yClip;
    const visibleEndpoint = endpointBeforeClip
      ? null : (endpoint - yClip) & 0xffff;
    const showUp = yClip !== 0;
    const showDown = visibleEndpoint !== null &&
      visibleEndpoint >= bottomBound;
    const operations = [];
    if (showUp) operations.push({
      kind:'bitmap',
      x,
      y:screenYOrigin,
      width:7,
      height:4,
      rows:SETTLED_VERTICAL_UP_ROWS.slice(),
      retainUnchanged:true,
      editorChrome:true,
      routine:'34:6009 → bcall 53DAh → 35:7116–715A; table 35:717D',
    });
    if (showDown) operations.push({
      kind:'bitmap',
      x,
      y:(screenYOrigin + bottomBound - 4) & 0xff,
      width:7,
      height:4,
      rows:SETTLED_VERTICAL_DOWN_ROWS.slice(),
      retainUnchanged:true,
      editorChrome:true,
      routine:'34:6011 → bcall 53D7h → 35:715B–717B; table 35:7182',
    });
    return {
      showUp,
      showDown,
      endpoint,
      endpointBeforeClip,
      visibleEndpoint,
      x,
      topY:screenYOrigin,
      bottomY:(screenYOrigin + bottomBound - 4) & 0xff,
      editorMode,
      horizontalBound,
      branchOutcomes:[
        `34:6009:${showUp ? 'fallthrough' : 'taken'}`,
        `34:60B3:${endpointBeforeClip ? 'fallthrough' : 'taken'}`,
        ...(endpointBeforeClip ? [] : [
          `34:5E01:${showDown ? 'taken' : 'fallthrough'}`,
        ]),
        `34:6011:${showDown ? 'fallthrough' : 'returned'}`,
      ],
      operations,
      routine:'34:6000–6015 → 34:60A0–60B7 → bcall 53DAh/53D7h',
    };
  }

  // ram:027B decrements indicCounter and returns until it reaches zero.
  // 01:6BBA–6BFA then reloads 14h, rotates indicBusy right, and uses the
  // rotated byte low-bit first to rewrite pixel 95 on LCD rows 0..7. The
  // handler runs from the standard timer interrupt, so callers choose where
  // its operation interleaves with a synchronous renderer stream.
  function settledRunIndicatorTick(indicCounter, indicBusy) {
    byte(indicCounter, 'run-indicator counter');
    byte(indicBusy, 'run-indicator busy pattern');
    const decremented = (indicCounter - 1) & 0xff;
    if (decremented !== 0) return {
      indicCounter:decremented,
      indicBusy,
      operation:null,
      routine:'ram:027B–0283',
    };
    const rotated = (indicBusy >>> 1) | ((indicBusy & 1) << 7);
    return {
      indicCounter:0x14,
      indicBusy:rotated,
      operation:{
        kind:'bitmap',
        x:95,
        y:0,
        width:1,
        height:8,
        rows:Array.from({length:8}, (_, row) => (rotated >>> row) & 1),
        retainUnchanged:true,
        asynchronous:true,
        routine:'ram:027B–0283 → 01:6BBA–6BFA',
      },
      routine:'ram:027B–0283 → 01:6BBA–6BFA',
    };
  }

  function translateSettledOperation(operation, dx, dy) {
    if (!operation || typeof operation !== 'object')
      throw new TypeError('settled translated operation must be an object');
    if (!Number.isInteger(dx) || !Number.isInteger(dy))
      throw new RangeError('settled operation translation must be integral');
    if (operation.kind === 'line') return {
      ...operation,
      from:{x:operation.from.x + dx,y:operation.from.y + dy},
      to:{x:operation.to.x + dx,y:operation.to.y + dy},
    };
    if (Number.isInteger(operation.x) && Number.isInteger(operation.y))
      return {...operation,x:operation.x + dx,y:operation.y + dy};
    return {...operation};
  }

  // 34:5FF2 selects the left-overflow cue whenever ram:8E02 is nonzero.
  // 34:6031 centers the seven-row bitmap at 34:60B8 against the current
  // record height and sends it through 34:61B2 after the expression draw.
  // In the normal editor, 34:753F loads the root's height word. A nonzero
  // high byte or a low byte beyond ram:8DFDh substitutes that bottom bound,
  // so a tall record keeps the cue centered in the physical viewport.
  function settledEditorViewportOperations(
    operations, viewport, recordHeight, options = {}) {
    if (!Array.isArray(operations))
      throw new TypeError('settled editor operations must be an array');
    if (!viewport || typeof viewport !== 'object' ||
        !Number.isInteger(viewport.effectiveX) ||
        !Number.isInteger(viewport.yOrigin) ||
        !Number.isInteger(viewport.xClip))
      throw new TypeError('settled editor viewport state is invalid');
    if (!Number.isInteger(recordHeight) || recordHeight < 1 || recordHeight > 0xffff)
      throw new RangeError('settled editor record height must fit an unsigned word');
    if (options === null || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('settled editor operation options must be an object');
    const glyphAdvance = options.glyphAdvance;
    if (glyphAdvance !== undefined && typeof glyphAdvance !== 'function')
      throw new TypeError('settled editor glyph advance must be a function');
    const hasVerticalViewport = viewport.yClip !== undefined;
    const yClip = hasVerticalViewport ? viewport.yClip : 0;
    const screenYOrigin = viewport.screenYOrigin === undefined
      ? 0 : viewport.screenYOrigin;
    const screenXOrigin = viewport.screenXOrigin === undefined
      ? 0 : viewport.screenXOrigin;
    const bottomBound = viewport.bottomBound === undefined
      ? 0x3e : viewport.bottomBound;
    const editorMode = byte(
      options.editorMode === undefined ? 0 : options.editorMode,
      'settled editor mode');
    for (const [value,label] of [
      [yClip,'settled editor vertical clip'],
      [screenYOrigin,'settled editor screen y origin'],
    ]) if (!Number.isInteger(value) || value < 0 || value > 0xffff)
      throw new RangeError(`${label} must fit an unsigned word`);
    byte(screenXOrigin, 'settled editor screen x origin');
    byte(bottomBound, 'settled editor vertical bound');
    const clip = {
      left:screenXOrigin,
      rightExclusive:screenXOrigin + viewport.rightBound + 1,
      top:screenYOrigin,
      bottomExclusive:screenYOrigin + bottomBound,
    };
    const translated = [];
    for (const operation of operations) {
      const positioned = translateSettledOperation(
        operation, viewport.effectiveX,
        viewport.yOrigin - (hasVerticalViewport ? yClip : 0) + screenYOrigin);
      // 34:6C5F–6C84 compares a glyph's left edge with ram:8E02 before
      // entering either font blitter. A glyph that begins left of the clip is
      // omitted as a unit; the ROM does not draw its still-visible suffix.
      if (positioned.kind === 'glyph' || positioned.kind === 'glyph-run') {
        const logicalPen = (operation.x + viewport.xOrigin) & 0xffff;
        if (logicalPen < viewport.xClip) continue;
      }
      // 34:630C enters the same 34:6C37 display-unit path as a glyph. The
      // bitmap header supplies its five-pixel advance before 34:6C5F compares
      // the unit's logical left edge with ram:8E02. A root hook that begins
      // left of the clip is therefore omitted as a unit instead of raster-
      // clipping its visible columns.
      if (operation.viewportAdvance !== undefined) {
        if (!Number.isInteger(operation.viewportAdvance) ||
            operation.viewportAdvance < 0 || operation.viewportAdvance > 0xffff)
          throw new RangeError(
            'settled editor operation viewport advance must fit an unsigned word');
        const logicalPen = (operation.x + viewport.xOrigin) & 0xffff;
        if (settledGlyphViewportDecision(
          logicalPen,operation.viewportAdvance,
          viewport.xClip,viewport.rightBound).action !== 'draw')
          continue;
      }
      // 34:6C6B–6C7F adds the glyph advance to the logical pen, derives the
      // one-past-right viewport coordinate, and skips the whole glyph when
      // that endpoint is larger. Equality is accepted: a four-pixel advance
      // from visible x=92 ends at 96 and can still occupy pixel 95.
      if (positioned.kind === 'glyph' && glyphAdvance !== undefined) {
        const advance = glyphAdvance(
          positioned.depth === undefined ? 0 : positioned.depth,
          positioned.code);
        if (!Number.isInteger(advance) || advance < 0 || advance > 0xffff)
          throw new RangeError('settled editor glyph advance must fit an unsigned word');
        const logicalPen = (operation.x + viewport.xOrigin) & 0xffff;
        if (settledGlyphViewportDecision(
          logicalPen,advance,viewport.xClip,viewport.rightBound).action !== 'draw')
          continue;
      }
      if (hasVerticalViewport &&
          (positioned.kind === 'glyph' || positioned.kind === 'glyph-run' ||
           operation.viewportAdvance !== undefined)) {
        const logicalTop = addWord(operation.y,viewport.yOrigin);
        const vertical = settledGlyphVerticalViewportDecision(
          logicalTop,
          operation.depth === undefined ? 0 : operation.depth,
          yClip,bottomBound);
        if (vertical.action === 'skip-above' ||
            vertical.action === 'skip-below')
          continue;
      }
      if (hasVerticalViewport)
        Object.defineProperty(positioned,'clip',{
          value:clip, enumerable:false, configurable:false, writable:false,
        });
      translated.push(positioned);
    }
    if (viewport.xClip !== 0) {
      // 34:78A3 skips the root-height lookup in editor mode 49h. Otherwise,
      // 34:753F reads the +07h height word and 34:6043–6050 clamps it to the
      // one-byte bottom bound before 34:6053 halves the chosen value.
      const cue = settledEditorHorizontalCuePlacement(
        viewport,recordHeight,{editorMode});
      translated.push({
        kind:'bitmap',
        x:cue.screenXOrigin,
        y:cue.y,
        width:4,
        height:7,
        rows:SETTLED_LEFT_OVERFLOW_ROWS.slice(),
        retainUnchanged:true,
        routine:'34:5FF2 → 34:6031 → 34:61B2; bitmap at 34:60B8',
      });
    }
    return translated;
  }

  // 34:607A loads the wrapper record's +09h width, converts its last pixel to
  // the logical viewport, and returns NZ only when the remaining endpoint is
  // at or beyond ram:8DFCh. The caller at 34:5FFD draws 34:60C0 only for that
  // result. Keep this state decision separate from bitmap placement so the
  // auxiliary 34:6CA8 stream cannot be mistaken for this cue.
  function settledEditorRightCueDecision(wrapperWidth, viewport) {
    if (!Number.isInteger(wrapperWidth) ||
        wrapperWidth < 0 || wrapperWidth > 0xffff)
      throw new RangeError(
        'settled right-cue wrapper width must fit an unsigned word');
    if (!viewport || typeof viewport !== 'object' ||
        !Number.isInteger(viewport.xOrigin) ||
        !Number.isInteger(viewport.xClip) ||
        !Number.isInteger(viewport.rightBound))
      throw new TypeError('settled right-cue viewport state is invalid');
    for (const [value,label] of [
      [viewport.xOrigin,'settled right-cue logical x origin'],
      [viewport.xClip,'settled right-cue horizontal clip'],
    ]) if (value < 0 || value > 0xffff)
      throw new RangeError(`${label} must fit an unsigned word`);
    const rightBound = byte(
      viewport.rightBound, 'settled right-cue horizontal bound');
    if (wrapperWidth === 0) return {
      action:'return', showRight:false, wrapperWidth,
      endpoint:null, originEndpoint:null, translatedEndpoint:null,
      comparisonCoordinate:null, subtractionCarry:null,
      branchOutcomes:['34:607F:returned','34:5FFD:fallthrough'],
      routine:'34:607A–608E; caller 34:5FFA–5FFD',
    };
    const endpoint = wrapperWidth - 1;
    const originEndpoint = addWord(endpoint,viewport.xOrigin);
    const subtractionCarry = originEndpoint < viewport.xClip;
    const translatedEndpoint =
      (originEndpoint - viewport.xClip) & 0xffff;
    const outcomes = [
      '34:607F:fallthrough',
      `34:6085:${subtractionCarry ? 'taken' : 'fallthrough'}`,
    ];
    if (subtractionCarry) return {
      action:'return', showRight:false, wrapperWidth,
      endpoint,originEndpoint,translatedEndpoint,
      comparisonCoordinate:null,subtractionCarry,
      branchOutcomes:outcomes.concat('34:5FFD:fallthrough'),
      routine:'34:607A–608E; caller 34:5FFA–5FFD',
    };
    const translatedZero = translatedEndpoint === 0;
    outcomes.push(`34:6087:${translatedZero ? 'taken' : 'fallthrough'}`);
    const comparisonCoordinate = translatedZero
      ? 0 : translatedEndpoint - 1;
    const showRight = comparisonCoordinate >= rightBound;
    outcomes.push(`34:5DE1:${showRight ? 'taken' : 'fallthrough'}`);
    outcomes.push(`34:5FFD:${showRight ? 'taken' : 'fallthrough'}`);
    return {
      action:showRight ? 'draw' : 'return',showRight,wrapperWidth,
      endpoint,originEndpoint,translatedEndpoint,comparisonCoordinate,
      subtractionCarry,branchOutcomes:outcomes,
      routine:'34:607A–608E; caller 34:5FFA–5FFD',
    };
  }

  function settledEditorRightCueOperation(
    viewport, recordHeight, options = {}) {
    if (!viewport || typeof viewport !== 'object' ||
        !Number.isInteger(viewport.rightBound))
      throw new TypeError('settled right-cue viewport state is invalid');
    if (!Number.isInteger(recordHeight) || recordHeight < 1 || recordHeight > 0xffff)
      throw new RangeError('settled right-cue record height must fit an unsigned word');
    const placement = settledEditorHorizontalCuePlacement(
      viewport,recordHeight,options);
    return {
      kind:'bitmap',
      x:(placement.screenXOrigin + viewport.rightBound - 4) & 0xff,
      y:placement.y,
      width:4,
      height:7,
      rows:SETTLED_RIGHT_OVERFLOW_ROWS.slice(),
      retainUnchanged:true,
      routine:'34:5FFA → 34:607A → 34:608F; bitmap at 34:60C0',
    };
  }

  function settledEditorRightCue(
    wrapperWidth, viewport, recordHeight, options = {}) {
    const decision = settledEditorRightCueDecision(wrapperWidth,viewport);
    return {
      ...decision,
      operation:decision.showRight
        ? settledEditorRightCueOperation(viewport,recordHeight,options)
        : null,
    };
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

  // Every structural insertion routed through 34:473A calls the page-35 gate
  // at 35:7B37. It increments the byte at 8DB6h modulo 256, compares the
  // result with 05h, and preserves the incoming A on the carry-clear path.
  // At depths 04h..FEh it instead returns A=03h with carry set. FFh wraps to
  // zero and is accepted exactly as the Z80 byte operation does.
  function settledStructuralDepthGate(structuralDepth, inputA) {
    byte(structuralDepth, 'settled structural depth');
    byte(inputA, 'settled structural gate A');
    const incrementedDepth = (structuralDepth + 1) & 0xff;
    const carry = incrementedDepth >= 5;
    return {
      structuralDepth,
      incrementedDepth,
      status:carry ? 'depth-limit' : 'accept',
      returnA:carry ? 0x03 : inputA,
      carry,
      routine:'34:473A → ram:2E41 → 35:7B37',
    };
  }

  // EF36h takes the alternate editor path at 34:473A rather than the normal
  // metadata-driven scanner. It therefore shares the gate above with ordinary
  // structural types such as power (2Ah). On the carry-set path, 34:54D2 sets
  // (IY+45h).6 and writes 05h to 9D20h.
  //
  // Below the cap, 34:58A0 inserts EF 2C 00 00 EF 2D. The allocator at
  // 33:4F42 indexes one row past its legitimate type-1Fh..2Bh table and reads
  // the adjacent bytes at 33:4FA9 as E=42h, BC=0002h, and HL=0018h. Retain
  // this exceptional behavior separately from settledRecordMetadata(); 2Ch
  // has no metadata row or renderer.
  function settledEf36SourcePath(structuralDepth = 0, options = {}) {
    byte(structuralDepth, 'EF36h structural depth');
    if (options === null || typeof options !== 'object' || Array.isArray(options))
      throw new TypeError('EF36h options must be an object');
    const parentId = options.parentId === undefined ? 7 : options.parentId;
    const recordId = options.recordId === undefined ? 8 : options.recordId;
    for (const [value, label] of [
      [parentId,'EF36h parent record ID'], [recordId,'EF36h allocated record ID'],
    ]) if (!Number.isInteger(value) || value < 0 || value > 0xffff)
      throw new RangeError(`${label} must be an unsigned word`);

    const common = {
      sourceToken:[0xef,0x36], mappedType:0x2c,
      sourceBranch:'34:4690 → 34:473A', structuralDepth,
    };
    const depthGate = settledStructuralDepthGate(structuralDepth, 0x2c);
    if (depthGate.carry) return {
      ...common,
      status:'depth-limit', carry:true, returnA:depthGate.returnA,
      incrementedDepth:depthGate.incrementedDepth,
      error:{flags45Bit6:true,address:0x9d20,value:0x05},
      routine:'34:473A → ram:2E41 → 35:7B37 → 34:54D2',
    };

    const placeholderBytes = [0xef,0x2c,0x00,0x00,0xef,0x2d];
    const patchedBytes = [
      0xef,0x2c,recordId & 0xff,recordId >> 8,0xef,0x2d,
    ];
    return {
      ...common,
      status:'reset', carry:false, returnA:depthGate.returnA,
      incrementedDepth:depthGate.incrementedDepth,
      insertion:{
        placeholderBytes, patchedBytes,
        routine:'34:4744 → 34:4169 → 34:5026 → 34:5473 → 34:58A0',
      },
      allocation:{
        tableBase:0x4f82, tableAddress:0x4fa9,
        recordSize:0x18, childCount:0x0002, byteE:0x42,
        recordHeader:[
          recordId & 0xff,recordId >> 8,0x2c,
          parentId & 0xff,parentId >> 8,
          0x01,0x00,0x06,0x00,0x03,0x00,0x00,0x00,0x00,0x00,
          0x06,0x00,0x01,0x00,0xef,
        ],
        routine:'34:4862 → ram:2EA1 → 33:4F42',
      },
      terminal:{
        geometryTableBase:0x7611, geometryTableAddress:0x762b,
        geometryWord:0x3bcd,
        path:['34:7609','34:6105','ram:3BCD','03:467F','ram:0002','ram:028C','3F:412C'],
        reason:'type 0x2C indexes code bytes after the 34:7611 geometry table',
      },
    };
  }

  function settledEf36ResetError(path = settledEf36SourcePath()) {
    const error = new RangeError(
      'EF36h constructs type 0x2C, whose out-of-range 34:7611 geometry ' +
      'dispatch resets through ram:3BCD');
    error.code = 'SETTLED_EF36_RESET';
    error.romPath = path;
    return error;
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

  // 33:4F6D indexes the three-byte rows at 33:4F82. The returned registers
  // feed 34:4862: DE is the workspace request checked by 34:4B7C, BC is the
  // child-slot count, and HL is the record size later copied back to DE.
  const SETTLED_RECORD_ALLOCATION_GEOMETRY = Object.freeze([
    [0x29,0x01,0x16], [0x42,0x02,0x18], [0x2b,0x01,0x16],
    [0x70,0x04,0x1c], [0x59,0x03,0x1a], [0x42,0x02,0x18],
    [0x2b,0x01,0x16], [0x2b,0x01,0x16], [0x2b,0x01,0x16],
    [0x42,0x02,0x18], [0x70,0x04,0x1c], [0x2b,0x01,0x16],
    [0x2b,0x01,0x16],
  ].map(Object.freeze));

  function settledRecordAllocationGeometry(renderType, matrixElements = null) {
    byte(renderType, 'settled allocation render type');
    if (renderType < 0x1f || renderType > 0x2b)
      throw new RangeError('settled allocation type must be 1Fh..2Bh');
    if (renderType !== 0x2b) {
      if (matrixElements !== null)
        throw new RangeError('settled matrix element count applies only to type 2Bh');
      const [workspaceRequest,childCount,recordBytes] =
        SETTLED_RECORD_ALLOCATION_GEOMETRY[renderType - 0x1f];
      return {
        renderType, matrixElements:null,
        workspaceRequest, childCount, recordBytes,
        tableAddress:0x4f82 + 3 * (renderType - 0x1f),
        branchOutcomes:[],
        routine:'33:4F6D–4F81',
      };
    }
    if (!Number.isInteger(matrixElements) ||
        matrixElements < 0 || matrixElements > 0xffff)
      throw new RangeError('settled matrix element count must be an unsigned word');
    // 33:4F4E treats a zero product as two slots. Matrix creation rejects a
    // zero dimension before this point, but retain the raw branch here.
    const zeroProduct = matrixElements === 0;
    const childCount = zeroProduct ? 2 : (matrixElements + 1) & 0xffff;
    const recordBytes = (2 * childCount + 20) & 0xffff;
    const workspaceRequest = (22 * childCount + 20) & 0xffff;
    return {
      renderType, matrixElements,
      workspaceRequest, childCount, recordBytes,
      tableAddress:0x4f82 + 3 * (renderType - 0x1f),
      branchOutcomes:[
        `33:4F4E:${zeroProduct ? 'fallthrough' : 'taken'}`,
        ...new Array(19).fill('33:4F65:taken'),
        '33:4F65:fallthrough',
      ],
      routine:'33:4F42–4F6C',
    };
  }

  // 34:4B86 subtracts a conditional reserve and the current record tail from
  // the workspace bound. Each OR A clears carry before the following SBC, so
  // an earlier underflow wraps and does not feed the next subtraction. 34:4B7C
  // then subtracts the requested bytes unless the record-tail subtraction
  // borrowed. The allocator caller at 34:486F returns A=02h on either carry.
  function settledRecordAllocationCapacity(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input))
      throw new TypeError('settled allocation capacity input must be an object');
    const unsignedWord = (value, label) => {
      if (!Number.isInteger(value) || value < 0 || value > 0xffff)
        throw new RangeError(`${label} must be an unsigned word`);
      return value;
    };
    const workspaceTop = unsignedWord(
      input.workspaceTop, 'settled allocation workspace bound');
    const recordTail = unsignedWord(
      input.recordTail, 'settled allocation record tail');
    const reservedSpan = unsignedWord(
      input.reservedSpan, 'settled allocation conditional reserve');
    const requestedBytes = unsignedWord(
      input.requestedBytes, 'settled allocation request');
    const iy2dBit0 = boolean(
      input.iy2dBit0, 'settled allocation IY+2Dh bit 0');
    const subtractReserved = !iy2dBit0;
    const afterReserved = subtractReserved
      ? (workspaceTop - reservedSpan) & 0xffff : workspaceTop;
    const rangeBorrow = afterReserved < recordTail;
    const availableBeforeRequest = (afterReserved - recordTail) & 0xffff;
    const requestCompared = !rangeBorrow;
    const requestBorrow = requestCompared &&
      availableBeforeRequest < requestedBytes;
    const carry = rangeBorrow || requestBorrow;
    const remainingBytes = requestCompared
      ? (availableBeforeRequest - requestedBytes) & 0xffff
      : availableBeforeRequest;
    return {
      workspaceTop, recordTail, reservedSpan, requestedBytes,
      iy2dBit0, subtractReserved, afterReserved,
      rangeBorrow, availableBeforeRequest,
      requestCompared, requestBorrow, remainingBytes,
      carry, returnA:0x02,
      terminal:carry ? 'return-allocation-carry' : 'continue-allocation',
      branchOutcomes:[
        `34:4B8D:${iy2dBit0 ? 'taken' : 'fallthrough'}`,
        `34:4B80:${rangeBorrow ? 'taken' : 'fallthrough'}`,
        `34:486F:${carry ? 'returned' : 'fallthrough'}`,
      ],
      routine:'34:4B7C–4B9D; caller 34:4862–4870',
    };
  }

  // 34:4862 stores the incoming render type at 0x8DDD, obtains the request
  // from the page-33 geometry helper, and passes that request to 34:4B7C.
  // Keep the arena words explicit because their producers are record-list
  // callers, but make the request/geometry ABI executable instead of asking
  // callers to duplicate the table lookup themselves.
  function settledRecordAllocationCheck(renderType, matrixElements = null, input) {
    if (input === undefined && matrixElements && typeof matrixElements === 'object' &&
        !Array.isArray(matrixElements)) {
      input = matrixElements;
      matrixElements = null;
    }
    const geometry = settledRecordAllocationGeometry(renderType, matrixElements);
    if (!input || typeof input !== 'object' || Array.isArray(input))
      throw new TypeError('settled allocation check input must be an object');
    if (input.requestedBytes !== undefined &&
        input.requestedBytes !== geometry.workspaceRequest)
      throw new RangeError(
        'settled allocation request must equal the geometry workspace request');
    const capacity = settledRecordAllocationCapacity({
      ...input, requestedBytes:geometry.workspaceRequest,
    });
    return {
      renderType, matrixElements:geometry.matrixElements,
      geometry, capacity,
      carry:capacity.carry, returnA:capacity.returnA,
      routine:'34:4862 → 33:4F6D → 34:4B7C → 34:486F',
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
    unsignedWord(x, 'settled compound x');
    unsignedWord(y, 'settled compound y');
    unsignedWord(height, 'settled compound height');
    if (height < 3)
      throw new RangeError('settled compound height must be at least three');
    const routine = mode === 'open' ? '34:5D1A' : '34:5D07';
    const outerX = addWord(x, mode === 'open' ? 3 : 1);
    const bottom = addWord(y, height - 1);
    const operations = [
      {kind:'point', x:outerX, y, routine:`${routine} → 34:5E85`},
      {kind:'point', x:outerX, y:bottom, routine:`${routine} → 34:5E85`},
    ];
    if (height === 5) {
      operations.push({
        kind:'line', axis:'vertical',
        from:{x:addWord(x,2),y:addWord(y,1)},
        to:{x:addWord(x,2),y:addWord(y,height - 2)},
        routine:`${routine} → 34:5D96`,
      });
      return operations;
    }
    operations.push(
      {kind:'point', x:addWord(x,2), y:addWord(y,1), routine:`${routine} → 34:5E85`},
      {kind:'point', x:addWord(x,2), y:addWord(y,height - 2),
       routine:`${routine} → 34:5E85`},
      {
        kind:'line', axis:'vertical',
        from:{x:addWord(x,mode === 'open' ? 1 : 3),y:addWord(y,2)},
        to:{x:addWord(x,mode === 'open' ? 1 : 3),y:addWord(y,height - 3)},
        routine:`${routine} → 34:5D96`,
      },
    );
    return operations;
  }

  // 34:5E0F and 34:5E14 draw an opening or closing brace around the metrics
  // selected by 34:6873. The waist follows the enclosed expression's baseline,
  // rather than the geometric midpoint, so an asymmetric radical moves the
  // notch down with its axis. Preserve the ROM's point/line emission order.
  function settledBraceOperations(mode, x, y, height, baseline) {
    if (mode !== 'open' && mode !== 'close')
      throw new RangeError('settled brace mode must be open or close');
    unsignedWord(x, 'settled brace x');
    unsignedWord(y, 'settled brace y');
    unsignedWord(height, 'settled brace height');
    unsignedWord(baseline, 'settled brace baseline');
    if (height < 3 || baseline < 1 || baseline >= height - 1)
      throw new RangeError(
        'settled brace baseline must leave rows above and below the waist');
    const routine = mode === 'open' ? '34:5E0F' : '34:5E14';
    const outerX = addWord(x, mode === 'open' ? 4 : 0);
    const innerX = addWord(x, mode === 'open' ? 3 : 1);
    const stemX = addWord(x,2);
    const waistX = addWord(x,mode === 'open' ? 1 : 3);
    const bottom = addWord(y,height - 1);
    return [
      {kind:'point',x:outerX,y,routine:`${routine} → 34:5E85`},
      {kind:'point',x:innerX,y,routine:`${routine} → 34:5E85`},
      {kind:'line',axis:'vertical',
       from:{x:stemX,y:addWord(y,1)},
       to:{x:stemX,y:addWord(y,baseline - 1)},
       routine:`${routine} → 34:5D96`},
      {kind:'point',x:waistX,y:addWord(y,baseline),
       routine:`${routine} → 34:5E85`},
      {kind:'line',axis:'vertical',
       from:{x:stemX,y:addWord(y,baseline + 1)},
       to:{x:stemX,y:addWord(y,height - 2)},
       routine:`${routine} → 34:5D96`},
      {kind:'point',x:innerX,y:bottom,routine:`${routine} → 34:5E85`},
      {kind:'point',x:outerX,y:bottom,routine:`${routine} → 34:5E85`},
    ];
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
    const columns = record.word11 >> 8;
    const rows = record.byte13;
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
      const depth = absolute.depth === undefined
        ? state.depth : byte(absolute.depth, 'settled operation depth');
      output.push({...absolute, recordId:record.id, recordType:record.type, depth});
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
        if (record.childIds.length) {
          // 34:4FD9 allocates type 1Fh as a transient one-child root.  The
          // editor redraw reaches 34:636C directly, so this ABI does not run
          // through the 34:6119 table and does not emit the default bitmap.
          // Keep the table-dispatch form below for a standalone synthetic
          // record, whose 34:6119 entry is still independently decoded.
          if (record.childIds.length !== 1)
            throw new RangeError('type 1Fh transient root must have one child');
          renderChild(1);
        } else {
          // The 34:6119 row is the little-endian pointer 6143h. _LdHLind at
          // 00:0033 loads its low byte into A as a side effect, so table
          // dispatch reaches the shared helper with A=43h. Every comparison
          // falls through to the fixed width byte plus seven bitmap rows at
          // 34:61BE.
          emit(record, origin, {
            kind:'bitmap', x:0, y:0, width:5, height:7,
            rows:[0x02,0x01,0x00,0x1f,0x00,0x02,0x06],
            retainUnchanged:true,
            tableEntry:[0x43,0x61], incomingA:0x43,
            routine:'34:6105 → 34:6119 → 00:0033 → 34:6143 → 34:61BE',
          });
        }
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
          x:0, y:record.word07 - 7, depth:0,
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
  // 34:6C37. Keep the original closed one-glyph subset as a fallback for
  // consumers that have not installed the ROM-extracted 01:4252 table.
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

  // `_GetTokLen` and `_Get_Tok_Strng` share `smallfont_glyph_ptr` at 01:6702.
  // It selects a pointer table from D, transforms/clamps index E, and reads a
  // pointer to one metadata byte followed by a counted display-code string.
  // The proprietary ROM is absent from the web build, so
  // export-token-strings.py commits those immutable decoded tables.
  function settledTwoByteTokenSelection(lead, second) {
    byte(lead, 'settled two-byte lead');
    byte(second, 'settled two-byte index');
    if (lead === 0x5c) return {table:'5C',index:second};
    if (lead === 0x5d) return {table:'5D',index:second};
    if (lead === 0x5e) {
      // 01:671C clears each selected bank bit before using the remaining low
      // bits as the pointer-table index. The first set bit wins.
      if (second & 0x10) return {table:'5E10',index:second & ~0x10};
      if (second & 0x20) return {table:'5E20',index:second & ~0x20};
      if (second & 0x40) return {table:'5E40',index:second & ~0x40};
      return {table:'5E80',index:second & ~0x80};
    }
    if (lead === 0x60) return {table:'60',index:second};
    if (lead === 0x61) return {table:'61',index:second};
    if (lead === 0x62) return {table:'62',index:second};
    if (lead === 0x63) return {table:'63',index:second};
    if (lead === 0x7e) return {table:'7E',index:second};
    if (lead === 0xaa) return {table:'AA',index:second};
    if (lead === 0xbb)
      return {table:'BB',index:Math.min(second,0xf6)};
    if (lead === 0xef) return {table:'EF',index:second};
    return null;
  }

  function settledTokenSpelling(payload, index) {
    if (!Array.isArray(payload) || !Number.isInteger(index) ||
        index < 0 || index >= payload.length)
      throw new RangeError('settled token spelling requires a payload index');
    const token = byte(payload[index], 'settled token spelling byte');
    if (SETTLED_TOKEN_STRINGS) {
      if (SETTLED_TOKEN_STRINGS.twoByteLeadBytes.has(token)) {
        if (index + 1 >= payload.length) return null;
        const selection = settledTwoByteTokenSelection(
          token, byte(payload[index + 1], 'settled two-byte token index'));
        if (!selection) return null;
        const table = SETTLED_TOKEN_STRINGS.tables[selection.table];
        const entry = table && table[selection.index];
        if (!entry) return null;
        return {
          codes:entry.codes.slice(), length:2,
          table:selection.table, tableIndex:selection.index,
        };
      }
      return {codes:SETTLED_TOKEN_STRINGS.entries[token].codes.slice(),length:1};
    }
    const code = settledTokenGlyph(token);
    return code === null ? null : {codes:[code],length:1};
  }

  function settledLargeTokenAdvance(token) {
    byte(token, 'settled leaf token');
    if (settledTokenGlyph(token) === null)
      throw new RangeError(`token 0x${token.toString(16)} has no translated large glyph`);
    // The page-34 metrics pass counts the 5-pixel large cell plus its one-pixel
    // advance. The settled record stores ink width in +9h and cell extent in +7h.
    return 6;
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
      const resolved = settledTokenSpelling(payload, index);
      if (!resolved)
        throw new RangeError(`token 0x${token.toString(16)} has no translated spelling`);
      for (const code of resolved.codes) {
        if (depth === 0 || code === 0x28 || code === 0x29 ||
            code === 0x7b || code === 0x7d) {
          width += 6;
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
      index += resolved.length - 1;
    }
    return {payload, height:depth === 0 ? 7 : 5, width,
            baseline:depth === 0 ? 3 : 2};
  }

  function settledExpressionSpec(input, label = 'settled expression',
                                 active = new Set(), editor = false) {
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
      const editorRecordState = editor &&
        input.editor_record_byte13 !== undefined ? {
          editor_record_byte13:byte(
            input.editor_record_byte13,`${label} retained record +13h byte`),
        } : {};
      if (kind === 'tokens')
        return settledExpressionSpec(input.tokens, label, active, editor);
      if (editor && kind === 'extendedToken')
        return settledExpressionSpec(input.tokens, label, active, editor);
      if (editor && kind === 'editorCursor') {
        const recordId = input.record_id;
        const byteOffset = input.byte_offset;
        if (recordId !== undefined &&
            (!Number.isInteger(recordId) || recordId < 0 || recordId > 0xffff))
          throw new RangeError(`${label} record ID must be an unsigned word`);
        if (byteOffset !== undefined &&
            (!Number.isInteger(byteOffset) || byteOffset < 0 || byteOffset > 0xffff))
          throw new RangeError(`${label} byte offset must be an unsigned word`);
        const recordWord0F = input.record_word0F;
        const recordWord11 = input.record_word11;
        for (const [value,field] of [
          [recordWord0F,'record +0Fh word'],
          [recordWord11,'record +11h word'],
        ]) if (value !== undefined &&
               (!Number.isInteger(value) || value < 0 || value > 0xffff))
          throw new RangeError(`${label} ${field} must be an unsigned word`);
        return {
          kind,record_id:recordId,byte_offset:byteOffset,
          record_word0F:recordWord0F,record_word11:recordWord11,
        };
      }
      if (kind === 'sequence') {
        if (!Array.isArray(input.parts) || !input.parts.length)
          throw new RangeError(`${label} sequence must contain at least one part`);
        return {kind, parts:input.parts.map((part, index) =>
          settledExpressionSpec(part, `${label} part ${index}`, active, editor))};
      }
      if (kind === 'group') return {
        kind,
        expression:settledExpressionSpec(
          input.expression, `${label} grouped expression`, active, editor),
      };
      if (kind === 'list') {
        if (!Array.isArray(input.elements) || !input.elements.length)
          throw new RangeError(`${label} list must contain at least one element`);
        return {
          kind,
          elements:input.elements.map((element, index) =>
            settledExpressionSpec(
              element, `${label} list element ${index}`, active, editor)),
        };
      }
      if (kind === 'power') {
        return {
          kind,...editorRecordState,
          base:settledExpressionSpec(
            input.base, `${label} power base`, active, editor),
          exponent:settledExpressionSpec(
            input.exponent, `${label} exponent`, active, editor),
        };
      }
      if (kind === 'absolute') return {
        kind,...editorRecordState,
        body:settledExpressionSpec(
          input.body, `${label} absolute body`, active, editor),
      };
      if (kind === 'ePower' || kind === 'tenPower') return {
        kind,...editorRecordState,
        exponent:settledExpressionSpec(
          input.exponent, `${label} exponent`, active, editor),
      };
      if (kind === 'logBase') return {
        kind,...editorRecordState,
        base:settledExpressionSpec(input.base, `${label} base`, active, editor),
        argument:settledExpressionSpec(
          input.argument, `${label} argument`, active, editor),
      };
      if (kind === 'matrix') {
        if (!Number.isInteger(input.rows) || input.rows < 1 || input.rows > 0xff ||
            !Number.isInteger(input.columns) || input.columns < 1 || input.columns > 0xff)
          throw new RangeError(`${label} matrix dimensions must be nonzero bytes`);
        if (input.rows * input.columns > 0xff)
          throw new RangeError(`${label} matrix element count must fit a byte`);
        if (!Array.isArray(input.elements) ||
            input.elements.length !== input.rows * input.columns)
          throw new RangeError(`${label} matrix requires rows*columns elements`);
        return {
          kind,...editorRecordState, rows:input.rows, columns:input.columns,
          elements:input.elements.map((element, index) =>
            settledExpressionSpec(
              element, `${label} element ${index}`, active, editor)),
        };
      }
      if (kind === 'radical') return {
        kind,...editorRecordState,
        radicand:settledExpressionSpec(
          input.radicand, `${label} radicand`, active, editor),
      };
      if (kind === 'nthRoot') return {
        kind,...editorRecordState,
        index:settledExpressionSpec(
          input.index, `${label} index`, active, editor),
        radicand:settledExpressionSpec(
          input.radicand, `${label} radicand`, active, editor),
      };
      if (kind === 'fraction') return {
        kind,...editorRecordState,
        numerator:settledExpressionSpec(
          input.numerator, `${label} numerator`, active, editor),
        denominator:settledExpressionSpec(
          input.denominator, `${label} denominator`, active, editor),
      };
      if (kind === 'integral') return {
        kind,...editorRecordState,
        lower:settledExpressionSpec(
          input.lower, `${label} lower bound`, active, editor),
        upper:settledExpressionSpec(
          input.upper, `${label} upper bound`, active, editor),
        body:settledExpressionSpec(input.body, `${label} body`, active, editor),
        variable:settledExpressionSpec(
          input.variable, `${label} variable`, active, editor),
      };
      if (kind === 'nDeriv') return {
        kind,...editorRecordState,
        variable:settledExpressionSpec(
          input.variable, `${label} variable`, active, editor),
        body:settledExpressionSpec(input.body, `${label} body`, active, editor),
        value:settledExpressionSpec(
          input.value, `${label} evaluation value`, active, editor),
      };
      if (kind === 'summation') return {
        kind,...editorRecordState,
        variable:settledExpressionSpec(
          input.variable, `${label} variable`, active, editor),
        lower:settledExpressionSpec(
          input.lower, `${label} lower bound`, active, editor),
        upper:settledExpressionSpec(
          input.upper, `${label} upper bound`, active, editor),
        body:settledExpressionSpec(input.body, `${label} body`, active, editor),
      };
      throw new RangeError(`${label} has unsupported kind ${JSON.stringify(kind)}`);
    } finally {
      active.delete(input);
    }
  }

  // 34:58F9 fetches a packed native token in D:E order. 34:5911 performs the
  // same width decision while walking backward. These helpers translate that
  // byte-level boundary without detokenizing the source stream.
  function settledReadPackedToken(input, offset = 0, end = undefined) {
    if (!Array.isArray(input) && !(input instanceof Uint8Array))
      throw new TypeError('settled native token stream must be an array of bytes');
    const limit = end === undefined ? input.length : end;
    if (!Number.isInteger(offset) || !Number.isInteger(limit) ||
        offset < 0 || limit < offset || limit > input.length)
      throw new RangeError('settled native token bounds are invalid');
    if (offset === limit) return null;
    const lead = byte(input[offset], `settled native token byte ${offset}`);
    if (!SETTLED_TWO_BYTE_LEADS.has(lead)) return {
      prefix:0, token:lead, packed:lead, bytes:[lead],
      offset, next:offset + 1, length:1,
    };
    if (offset + 1 >= limit)
      throw new RangeError(
        `settled two-byte token 0x${lead.toString(16)} is truncated`);
    const second = byte(input[offset + 1],
      `settled native token byte ${offset + 1}`);
    return {
      prefix:lead, token:second, packed:(lead << 8) | second,
      bytes:[lead,second], offset, next:offset + 2, length:2,
    };
  }

  function settledReadPackedTokenBackward(input, end = undefined, start = 0) {
    if (!Array.isArray(input) && !(input instanceof Uint8Array))
      throw new TypeError('settled native token stream must be an array of bytes');
    const limit = end === undefined ? input.length : end;
    if (!Number.isInteger(start) || !Number.isInteger(limit) ||
        start < 0 || limit < start || limit > input.length)
      throw new RangeError('settled backward token bounds are invalid');
    if (limit === start) return null;
    const secondOffset = limit - 1;
    const second = byte(input[secondOffset],
      `settled native token byte ${secondOffset}`);
    if (secondOffset > start) {
      const lead = byte(input[secondOffset - 1],
        `settled native token byte ${secondOffset - 1}`);
      if (SETTLED_TWO_BYTE_LEADS.has(lead)) return {
        prefix:lead, token:second, packed:(lead << 8) | second,
        bytes:[lead,second], offset:secondOffset - 1, next:limit, length:2,
      };
    }
    return {
      prefix:0, token:second, packed:second, bytes:[second],
      offset:secondOffset, next:limit, length:1,
    };
  }

  function settledNativeTokenUnits(input) {
    const bytes = Array.from(input, (value, index) =>
      byte(value, `settled native token byte ${index}`));
    if (!bytes.length)
      throw new RangeError('settled native token stream must not be empty');
    const units = [];
    for (let offset = 0; offset < bytes.length;) {
      const unit = settledReadPackedToken(bytes, offset);
      units.push(unit);
      offset = unit.next;
    }
    return {bytes,units};
  }

  const SETTLED_PARSE_AHEAD_TABLE_59E9 = new Set([
    0x10,0xda,0xdb,0x9c,0x93,0xa7,0xd2,0xd3,0xe0,
    0xe2,0xe3,0xe4,0xe6,0xe7,0xe8,0xec,0xed,0xee,
  ]);
  const SETTLED_PARSE_AHEAD_TABLE_59FB = new Set([
    0x3d,0x3e,0x3f,0x40,0x49,0x53,0x55,0x56,0x58,0x59,
  ]);
  const SETTLED_PARSE_AHEAD_OPERATORS_7F05 = new Set([
    0x3c,0x3d,0x40,0x70,0x71,0x6a,0x6b,0x6c,0x6d,
    0x6e,0x6f,0x82,0x83,0x95,0x94,0xf0,0xf1,
  ]);

  // Zero-result predicates at 34:5A14, 34:5A28, and 34:5A52. Keep the
  // address names because their token classes have not all been assigned a
  // stable semantic name.
  function settledParseAheadClass5A14(token) {
    return token === 0x13 || token < 0x09 ||
      (0x32 <= token && token < 0x36) || token === 0xbb;
  }

  function settledParseAheadClass5A28(token) {
    return token < 0x20 ||
      (0x25 <= token && token < 0x2f) ||
      (0x35 <= token && token < 0x3c) ||
      (0x42 <= token && token < 0x48) ||
      SETTLED_PARSE_AHEAD_TABLE_59FB.has(token);
  }

  function settledParseAheadClass5A52(token) {
    return (0xb1 <= token && token < 0xce) ||
      (0x12 <= token && token < 0x29) ||
      (0x9e <= token && token < 0xa6) ||
      SETTLED_PARSE_AHEAD_TABLE_59E9.has(token);
  }

  // 34:5A05 selects the function-opener class used by the source scanner.
  // D:E is the packed token returned by 34:58F9: ordinary one-byte tokens use
  // D=0, while only BB and EF leads dispatch through secondary class tables.
  function settledParseAheadFunctionToken(prefix, token) {
    byte(prefix, 'parse-ahead function-token prefix');
    byte(token, 'parse-ahead function token');
    if (prefix === 0) return settledParseAheadClass5A52(token);
    if (prefix === 0xbb) return settledParseAheadClass5A28(token);
    if (prefix === 0xef) return settledParseAheadClass5A14(token);
    return false;
  }

  // The first byte in each 34:59AC metadata row selects the source scan at
  // 34:5678. For scan kinds 3 and 4, the remaining nonzero bytes map source
  // arguments to child-record indices. Kind 3 enters 34:56E3 with B=2; kind 4
  // enters 34:56EC with C=1. Return half-open byte ranges for those arguments
  // and retain every translated parse-ahead result as an ABI oracle.
  function settledStructuralArgumentScan(input, openerOffset = 0) {
    const native = settledNativeTokenUnits(input);
    if (!Number.isInteger(openerOffset) || openerOffset < 0 ||
        openerOffset >= native.bytes.length)
      throw new RangeError('settled structural opener offset is outside the input');
    const opener = native.units.find(unit => unit.offset === openerOffset);
    if (!opener)
      throw new RangeError(
        'settled structural opener offset is inside a two-byte token');
    const renderType = settledStructuralTokenType(opener.prefix, opener.token);
    if (renderType === null)
      throw new RangeError('settled structural opener is not in the 34:594D table');
    if (opener.prefix === 0xef && opener.token === 0x36)
      throw new RangeError(
        'EF36h takes the alternate 34:473A path, not a 34:59AC argument scan');
    if (renderType > 0x2b)
      throw new RangeError(
        `settled structural type 0x${renderType.toString(16)} has no 34:59AC metadata row`);
    const metadata = settledRecordMetadata(renderType);
    const scanKind = metadata[0];
    if (scanKind !== 3 && scanKind !== 4)
      throw new RangeError(
        `settled structural scan kind ${scanKind} is not an argument scan`);
    const argumentChildOrder = metadata.slice(1).filter(value => value !== 0);
    const expectedCount = scanKind === 3 ? 1 : argumentChildOrder.length;
    if (argumentChildOrder.length !== expectedCount)
      throw new Error('34:59AC unary argument metadata is inconsistent');
    const args = [];
    let cursor = opener.next - 1;
    for (let index = 0; index < expectedCount; index++) {
      const start = cursor + 1;
      const parseAhead = settledParseAhead(native.bytes, scanKind === 3 ? {
        entry:'direct5AA7', b:2, cursor,
      } : {
        entry:'internal5AA3', c:1, cursor,
      });
      const delimiterOffset = parseAhead.stopCursor;
      const delimiter = native.bytes[delimiterOffset];
      const expectedDelimiter = index + 1 < expectedCount ? 0x2b : 0x11;
      if (delimiter !== expectedDelimiter)
        throw new RangeError(
          `settled structural argument ${index + 1} ends with ` +
          `${delimiter === undefined ? 'end of input' :
            `0x${delimiter.toString(16)}`} instead of ` +
          `0x${expectedDelimiter.toString(16)}`);
      if (delimiterOffset <= start)
        throw new RangeError(
          `settled structural argument ${index + 1} is empty`);
      args.push({
        index:index + 1,
        childIndex:argumentChildOrder[index],
        start,
        end:delimiterOffset,
        delimiterOffset,
        delimiter,
        parseAhead,
      });
      cursor = delimiterOffset;
    }
    return {
      renderType,
      scanKind,
      metadata,
      opener:{
        offset:opener.offset, next:opener.next, length:opener.length,
        prefix:opener.prefix, token:opener.token, packed:opener.packed,
      },
      argumentChildOrder,
      arguments:args,
      stopCursor:cursor,
    };
  }

  const SETTLED_RAISED_NUMERIC_TOKENS = new Set([
    0x30,0x31,0x32,0x33,0x34,0x35,0x36,0x37,0x38,0x39,0x3a,0x3b,
  ]);

  // 34:580C is the extended classifier reached after 34:5866 rejects a
  // numeric run. A is the first byte selected by 34:56A4: ordinary tokens use
  // their byte, while packed two-byte tokens use the lead byte. The routine
  // accepts one token, or a bounded raw name after 5Fh and EBh. It returns Z
  // for every accepted class and NZ for the default rejection.
  function settledRaisedExtendedTokenClass(prefix, token) {
    byte(prefix, 'settled raised classifier prefix');
    byte(token, 'settled raised classifier token');
    const a = prefix || token;
    const path = [];
    const branch = (address, taken) =>
      path.push(`34:${address.toString(16).toUpperCase()}:` +
        (taken ? 'taken' : 'fallthrough'));
    branch(0x580e,a < 0x40);
    if (a >= 0x40) {
      branch(0x5812,a < 0x5c);
      if (a < 0x5c) {
        branch(0x585f,a === 0x5f);
        return {accepted:true,nameByteLimit:a === 0x5f ? 8 : 0,path};
      }
      branch(0x5816,a < 0x64);
      if (a < 0x64) {
        branch(0x585f,a === 0x5f);
        return {accepted:true,nameByteLimit:a === 0x5f ? 8 : 0,path};
      }
    }
    branch(0x581b,a === 0x72);
    if (a === 0x72) return {accepted:true,nameByteLimit:0,path};
    branch(0x581f,a === 0xaa);
    if (a === 0xaa) return {accepted:true,nameByteLimit:0,path};
    branch(0x5823,a === 0xeb);
    if (a === 0xeb) return {accepted:true,nameByteLimit:5,path};
    branch(0x5827,a === 0x2c);
    if (a === 0x2c) return {accepted:true,nameByteLimit:0,path};
    branch(0x582b,a === 0xac);
    if (a === 0xac) return {accepted:true,nameByteLimit:0,path};
    branch(0x582f,a !== 0xbb);
    if (a !== 0xbb) return {accepted:false,nameByteLimit:0,path};
    branch(0x5833,token === 0x31);
    return {accepted:token === 0x31,nameByteLimit:0,path};
  }

  function settledRaisedNameScan(bytes, start, limit) {
    if (!Number.isInteger(start) || start < 0 || start > bytes.length)
      throw new RangeError('settled raised name start is outside the input');
    if (!Number.isInteger(limit) || limit < 1)
      throw new RangeError('settled raised name limit must be positive');
    const path = [];
    const branch = (address, taken) =>
      path.push(`34:${address.toString(16).toUpperCase()}:` +
        (taken ? 'taken' : 'fallthrough'));
    let end = start;
    let stop = 'source_boundary';
    for (let count = 0; count < limit; count++) {
      branch(0x5840,end >= bytes.length);
      if (end >= bytes.length) break;
      const value = bytes[end];
      const digit = 0x30 <= value && value < 0x3a;
      branch(0x5845,digit);
      if (!digit) {
        branch(0x5849,value < 0x41);
        if (value < 0x41) {
          stop = 'non_name_byte_below_41h';
          break;
        }
        branch(0x584d,value >= 0x5c);
        if (value >= 0x5c) {
          stop = 'non_name_byte_at_or_above_5Ch';
          break;
        }
      }
      end++;
      const more = count + 1 < limit;
      branch(0x5853,more);
      if (!more) stop = 'byte_limit';
    }
    return {start,end,acceptedBytes:end - start,limit,stop,path};
  }

  // Scan kind 1 enters 34:5699 for the F0h power and F1h nth-root
  // operators. The routine saves 0x965D, scans the raised operand, returns
  // its endpoint in BC, and restores 0x965D at 34:56AC–56B3. The retained
  // native traces cover the numeric path through 34:5866 and explicit
  // 10h… 11h editor slots through 34:56BF–56D3. The 34:580C classifier is a
  // finite packed-token partition. The 5Fh and EBh paths additionally scan at
  // most eight or five following name bytes through 34:5836–5853.
  function settledRaisedOperandScan(input, operatorOffset = 0) {
    const native = settledNativeTokenUnits(input);
    if (!Number.isInteger(operatorOffset) || operatorOffset < 0 ||
        operatorOffset >= native.bytes.length)
      throw new RangeError('settled raised operator offset is outside the input');
    const operator = native.units.find(unit => unit.offset === operatorOffset);
    if (!operator)
      throw new RangeError(
        'settled raised operator offset is inside a two-byte token');
    const renderType = settledStructuralTokenType(
      operator.prefix,operator.token);
    if (renderType === null || settledRecordMetadata(renderType)[0] !== 1)
      throw new RangeError(
        'settled raised operator does not select scan kind 1');
    const start = operator.next;
    if (start >= native.bytes.length)
      throw new RangeError('settled raised operator has no operand');
    const first = native.units.find(unit => unit.offset === start);
    if (!first)
      throw new Error('settled raised operand does not start on a token boundary');

    let end;
    let branch;
    let parseAhead = null;
    let classifier = null;
    if (first.prefix === 0 && first.token === 0x10) {
      parseAhead = settledParseAhead(native.bytes,{
        entry:'direct5AA7', b:2, cursor:start,
      });
      if (native.bytes[parseAhead.stopCursor] !== 0x11)
        throw new RangeError(
          'settled raised editor slot has no closing 11h token');
      end = parseAhead.stopCursor + 1;
      branch = '34:56BB–56D3';
    } else if (first.prefix === 0 &&
               SETTLED_RAISED_NUMERIC_TOKENS.has(first.token)) {
      let unitIndex = native.units.indexOf(first);
      do {
        end = native.units[unitIndex].next;
        unitIndex++;
      } while (unitIndex < native.units.length &&
               native.units[unitIndex].prefix === 0 &&
               SETTLED_RAISED_NUMERIC_TOKENS.has(
                 native.units[unitIndex].token));
      branch = '34:56A7 → 34:5866';
    } else {
      const classified = settledRaisedExtendedTokenClass(
        first.prefix,first.token);
      classifier = classified;
      if (!classified.accepted)
        throw new RangeError(
          `settled raised operand token at byte ${start} is rejected by ` +
          '34:580C');
      end = first.next;
      if (classified.nameByteLimit) {
        // 34:58B8 advances past the designator token. The 34:583D loop then
        // reads raw source bytes. 34:5CFB admits digits; 34:5847–584D admits
        // 41h–5Bh. The carry return from 34:57E6 marks the source boundary.
        classified.nameScan = settledRaisedNameScan(
          native.bytes,end,classified.nameByteLimit);
        end = classified.nameScan.end;
      }
      branch = classified.nameByteLimit
        ? `34:580C → 34:5836 (max ${classified.nameByteLimit})`
        : '34:580C → 34:5861';
    }
    return {
      renderType,
      scanKind:1,
      metadata:settledRecordMetadata(renderType),
      operator:{
        offset:operator.offset, next:operator.next, length:operator.length,
        prefix:operator.prefix, token:operator.token, packed:operator.packed,
      },
      start,
      end,
      returnedCursor:end,
      restoredCursor:start,
      branch,
      classifier,
      parseAhead,
    };
  }

  // Scan kind 2 enters 34:56DF → 34:5795 for EF2Eh and EF2Fh stacked
  // fractions. The parser calls 34:5AA7 with B=14h. A scan from immediately
  // before the numerator returns the EF lead-byte offset, so the two-byte
  // operator lies at [stopCursor, stopCursor+2). The kind-2 scan begins from
  // that EF byte. 34:57A1–57C1 advances the saved source cursor when D or
  // 0x9D05 is nonzero; expose that wrapper predicate separately from the
  // parse-ahead counter in E.
  function settledFractionOperandScan(input, operatorOffset,
                                      numeratorStart = 0) {
    const native = settledNativeTokenUnits(input);
    if (!Number.isInteger(operatorOffset) || operatorOffset < 0 ||
        operatorOffset >= native.bytes.length)
      throw new RangeError('settled fraction operator offset is outside the input');
    const operator = native.units.find(unit => unit.offset === operatorOffset);
    if (!operator)
      throw new RangeError(
        'settled fraction operator offset is inside a two-byte token');
    const renderType = settledStructuralTokenType(
      operator.prefix,operator.token);
    if (renderType !== 0x20 || settledRecordMetadata(renderType)[0] !== 2)
      throw new RangeError(
        'settled fraction operator does not select scan kind 2');
    if (!Number.isInteger(numeratorStart) || numeratorStart < 0 ||
        numeratorStart >= operator.offset)
      throw new RangeError('settled fraction numerator start is invalid');
    if (!native.units.some(unit => unit.offset === numeratorStart))
      throw new RangeError(
        'settled fraction numerator starts inside a two-byte token');
    if (operator.offset === numeratorStart)
      throw new RangeError('settled fraction numerator is empty');
    if (operator.next >= native.bytes.length)
      throw new RangeError('settled fraction denominator is empty');

    const numeratorParseAhead = settledParseAhead(native.bytes,{
      entry:'direct5AA7', b:0x14, cursor:numeratorStart - 1,
    });
    if (numeratorParseAhead.stopCursor !== operator.offset)
      throw new RangeError(
        `34:5795 found a fraction operator at byte ` +
        `${numeratorParseAhead.stopCursor}, not byte ${operator.offset}`);
    const denominatorParseAhead = settledParseAhead(native.bytes,{
      entry:'direct5AA7', b:0x14, cursor:operator.offset,
    });
    const unwoundBoundaries = denominatorParseAhead.de & 0xff;
    let denominatorEnd = denominatorParseAhead.stopCursor;
    let remainingBoundaries = unwoundBoundaries;
    while (remainingBoundaries && denominatorEnd > operator.next) {
      denominatorEnd--;
      if (native.bytes[denominatorEnd] === 0x11 ||
          native.bytes[denominatorEnd] === 0x09) remainingBoundaries--;
    }
    if (denominatorEnd <= operator.next)
      throw new RangeError('settled fraction denominator is empty');
    if (denominatorEnd < native.bytes.length &&
        !native.units.some(unit => unit.offset === denominatorEnd))
      throw new Error(
        'settled fraction denominator ends inside a two-byte token');
    const wrapper = result => ({
      nestingDepth:result.d,
      unwoundBoundaryCount:result.e,
      savedDepth:result.scratch[3],
      parseCursor:result.stopCursor,
      advancedSavedCursor:result.d !== 0 || result.scratch[3] !== 0,
    });
    return {
      renderType,
      scanKind:2,
      metadata:settledRecordMetadata(renderType),
      operator:{
        offset:operator.offset, next:operator.next, length:operator.length,
        prefix:operator.prefix, token:operator.token, packed:operator.packed,
      },
      numerator:{
        start:numeratorStart, end:operator.offset,
        parseAhead:numeratorParseAhead,
        wrapper:wrapper(numeratorParseAhead),
      },
      denominator:{
        start:operator.next, end:denominatorEnd,
        parseAhead:denominatorParseAhead,
        wrapper:wrapper(denominatorParseAhead),
      },
      stopCursor:denominatorEnd,
    };
  }

  // Scan kind 6 enters 34:568A for a matrix element. 34:57C2 reads the
  // current token and then rewinds 0x965D by one byte. The dispatcher calls
  // 34:5AA7 with B=20h, which returns the depth-zero comma or the row-closing
  // 07h token in BC. Matrix values use nested 06h...07h square-bracket
  // containers. Translate every element scan and retain its parse-ahead ABI;
  // the surrounding walk supplies the row and column coordinates that the
  // caller accumulates while constructing the type-2Bh record.
  function settledMatrixContainerScan(input, openerOffset = 0) {
    const native = settledNativeTokenUnits(input);
    if (!Number.isInteger(openerOffset) || openerOffset < 0 ||
        openerOffset >= native.bytes.length)
      throw new RangeError('settled matrix opener offset is outside the input');
    const opener = native.units.find(unit => unit.offset === openerOffset);
    if (!opener)
      throw new RangeError(
        'settled matrix opener offset is inside a two-byte token');
    const renderType = settledStructuralTokenType(opener.prefix,opener.token);
    const metadata = renderType === null ? null
      : settledRecordMetadata(renderType);
    if (renderType !== 0x2b || metadata[0] !== 6 ||
        opener.prefix !== 0 || opener.token !== 0x06)
      throw new RangeError(
        'settled matrix opener does not select the kind-6 square-bracket path');

    const unitAt = offset => native.units.find(unit => unit.offset === offset);
    const expectByte = (offset, value, label) => {
      const unit = unitAt(offset);
      if (!unit || unit.prefix !== 0 || unit.token !== value)
        throw new RangeError(`settled matrix ${label} is missing at byte ${offset}`);
      return unit.next;
    };

    const rows = [];
    let cursor = opener.next;
    for (;;) {
      const unit = unitAt(cursor);
      if (!unit)
        throw new RangeError('settled matrix has no outer closing 07h token');
      if (unit.prefix === 0 && unit.token === 0x07) {
        if (!rows.length)
          throw new RangeError('settled matrix has no rows');
        cursor = unit.next;
        break;
      }
      cursor = expectByte(cursor,0x06,'row-opening 06h token');
      const row = [];
      for (;;) {
        const first = unitAt(cursor);
        if (!first || first.prefix === 0 &&
            (first.token === 0x2b || first.token === 0x07))
          throw new RangeError(
            `settled matrix row ${rows.length + 1} has an empty element`);
        const start = cursor;
        const parseAhead = settledParseAhead(native.bytes,{
          entry:'direct5AA7', b:0x20, cursor:start - 1,
        });
        const delimiterOffset = parseAhead.stopCursor;
        const delimiter = native.bytes[delimiterOffset];
        if (delimiter !== 0x2b && delimiter !== 0x07)
          throw new RangeError(
            `settled matrix element at byte ${start} ends with ` +
            `${delimiter === undefined ? 'end of input' :
              `0x${delimiter.toString(16)}`} instead of 2Bh or 07h`);
        if (delimiterOffset <= start)
          throw new RangeError(
            `settled matrix element at byte ${start} is empty`);
        if (!unitAt(delimiterOffset))
          throw new Error('settled matrix delimiter is inside a two-byte token');
        row.push({
          row:rows.length + 1,
          column:row.length + 1,
          start,
          end:delimiterOffset,
          delimiterOffset,
          delimiter,
          incomingCursor:start,
          rewoundCursor:start - 1,
          returnedCursor:delimiterOffset,
          parseAhead,
        });
        cursor = delimiterOffset + 1;
        if (delimiter === 0x07) break;
      }
      rows.push(row);
    }
    const columns = rows[0].length;
    if (rows.some(row => row.length !== columns))
      throw new RangeError('settled matrix rows must have equal width');
    return {
      renderType,
      scanKind:6,
      metadata,
      opener:{
        offset:opener.offset, next:opener.next, length:opener.length,
        prefix:opener.prefix, token:opener.token, packed:opener.packed,
      },
      rows:rows.length,
      columns,
      elements:rows.flat(),
      stopCursor:cursor,
    };
  }

  // Zero-result predicate at 34:5A75. 34:7EF5 supplies the first 17 entries;
  // the remaining comparisons are inline at 34:5A79–5A98.
  function settledParseAheadClass5A75(token) {
    return SETTLED_PARSE_AHEAD_OPERATORS_7F05.has(token) ||
      token === 0 || token === 0x29 || token === 0x2a || token === 0xb0 ||
      (0x6a <= token && token < 0x72);
  }

  // Translate _AHEADEQUAL = 4B49h, _PARSAHEADS = 4B4Ch, _PARSAHEAD =
  // 4B4Fh, and the internal entries at 34:5AA3, 34:5AA7, and 34:5AA9. The
  // cursor follows 0x965D: it points immediately before the next byte. The
  // inclusive end follows 0x965F. Returned offsets mirror HL, BC, DE, A,
  // 0x9D02–0x9D05, Z, and C.
  function settledParseAhead(input, options = {}) {
    if (!Array.isArray(input) && !(input instanceof Uint8Array))
      throw new TypeError('parse-ahead input must be an array of bytes');
    const bytes = Array.from(input, (value, index) =>
      byte(value, `parse-ahead byte ${index}`));
    // The native scanner receives an editor buffer whose two-byte tokens are
    // already complete. Reject malformed standalone inputs before translating
    // pointer movement beyond a lead byte.
    if (bytes.length) settledNativeTokenUnits(bytes);
    const entry = options.entry === undefined ? 'parsAhead' : options.entry;
    if (!['aheadEqual','parsAheadS','parsAhead','direct5AA7',
          'internal5AA3','internal5AA9'].includes(entry))
      throw new RangeError('parse-ahead entry is not recognized');
    const originalCursor = options.cursor === undefined ? -1 : options.cursor;
    const end = options.end === undefined ? bytes.length - 1 : options.end;
    if (!Number.isInteger(originalCursor) || !Number.isInteger(end) ||
        originalCursor < -1 || end < originalCursor || end >= bytes.length)
      throw new RangeError('parse-ahead cursor or end is outside the input');
    const callerB = byte(options.b === undefined ? 0 : options.b,
      'parse-ahead B');
    const callerC = byte(options.c === undefined ? 0 : options.c,
      'parse-ahead C');
    let b = entry === 'aheadEqual' ? 0x80
      : entry === 'parsAheadS' ? 0x01
      : entry === 'parsAhead' || entry === 'internal5AA3' ? 0
      : callerB;
    let c = entry === 'internal5AA3' || entry === 'internal5AA9'
      ? callerC : 0;
    b &= 0xbf; // 34:5ABA RES 6,B
    let cursor = originalCursor;
    let bc = cursor;
    let d = 0, e = 0, counter = 0, braceCount = 0;
    const events = [];
    const maxSteps = options.maxSteps === undefined
      ? Math.max(256, 32 * (end - originalCursor + 2))
      : options.maxSteps;
    if (!Number.isInteger(maxSteps) || maxSteps < 1)
      throw new RangeError('parse-ahead maxSteps must be positive');
    let steps = 0;
    const bit = (value, index) => !!(value & 1 << index);
    const mode23 = () => bit(b,3) || bit(b,2);
    const modeBroad = () =>
      bit(b,1) || bit(c,0) || bit(b,5) || bit(b,3) || bit(b,2);
    const signed = value => value & 0x80 ? value - 0x100 : value;
    const guard = () => {
      if (++steps > maxSteps)
        throw new RangeError(
          'parse-ahead exceeded its bounded malformed-stream guard');
    };
    const peekNext = () => {
      bc = cursor + 1;
      return bc > end ? 0 : bytes[bc];
    };
    const advanceByte = () => {
      cursor++;
      bc = cursor;
      return cursor > end ? 0 : bytes[cursor];
    };
    const record = (offset, token, branch) => events.push({
      offset, token, branch, b, c, d, e, counter, braceCount,
    });
    const finish = (exitByte, accumulator, branch) => {
      const scratch = [b,c,braceCount,e];
      const status = byte(exitByte, 'parse-ahead exit byte');
      return {
        entry,
        a:byte(accumulator, 'parse-ahead returned A'),
        bc,
        de:(d << 8) | counter,
        hl:originalCursor,
        b:(bc >> 8) & 0xff,
        c:bc & 0xff,
        d,
        e:counter,
        zero:status === 1,
        carry:status === 1,
        exitByte:status,
        cursor:originalCursor,
        stopCursor:bc,
        scratch,
        events,
        branch,
      };
    };
    const finishStatus1Zero = branch => finish(1,0,branch);
    const finishStatus1 = (a, branch) => finish(1,a,branch);
    const exitDepth = branch => {
      if ((d | e) !== 0) return null;
      return finish(0,0,branch);
    };

    // 34:7CC4 walks backward from BC for the quote branch. Its only caller
    // here consumes the returned carry, so preserve that result directly.
    const quoteBackwardCarry = () => {
      let position = bc;
      const previous = () => {
        if (position <= 0) return null;
        const unit = settledReadPackedTokenBackward(bytes, position, 0);
        position = unit.offset;
        return unit;
      };
      // 34:5911 returns the lead byte in A and sets carry for a two-byte
      // token. It returns the ordinary token byte with carry clear otherwise.
      const accumulator = unit => unit.length === 2
        ? unit.prefix : unit.token;
      const digitCarry = value => !(0x30 <= value && value < 0x3a);
      let unit = previous();
      if (!unit || digitCarry(accumulator(unit))) return true;
      for (;;) {
        unit = previous();
        if (!unit) return true;
        if (unit.length === 2) return true;
        if (unit.token === 0xb0 ||
            0x30 <= unit.token && unit.token < 0x3c) continue;
        if (unit.token !== 0xae) return true;
        unit = previous();
        return !unit || digitCarry(accumulator(unit));
      }
    };

    const scanQuotedRun = () => {
      for (;;) {
        guard();
        const value = advanceByte();
        if (cursor > end)
          throw new RangeError(
            'parse-ahead quoted run has no quote or enter terminator');
        if (SETTLED_TWO_BYTE_LEADS.has(value)) {
          advanceByte();
          continue;
        }
        if (value === 0x2a || value === 0x3f) return value;
      }
    };

    for (;;) {
      guard();
      if (bit(b,6)) {
        // 34:5AD4 clears an editor flag outside this routine's returned ABI.
      }
      let a = peekNext();
      record(bc,a,'34:5ACE');
      if (a === 0x3e) {
        if (mode23()) {
          d = e = 0;
          const result = exitDepth('34:5ADF–5AE7');
          if (result) return result;
          continue;
        }
        if (bit(b,7) || !bit(b,0))
          return finishStatus1Zero('34:5AEA–5AF5');
        cursor = bc;
      } else {
        if (a === 0 || a === 0x3f)
          return finishStatus1Zero('34:5AFF–5B02');
        if (a === 0x04) {
          if (mode23()) {
            d = e = 0;
            const result = exitDepth('34:5B05–5B0C');
            if (result) return result;
            continue;
          }
          return finishStatus1(a,'34:5B05–5B0E');
        }
        if (bit(b,0) && a === 0x2a)
          return finishStatus1(a,'34:5B11–5B19');
        cursor = bc;
        if (a === 0xbb) {
          a = advanceByte(); // bjump 00:3057 -> 38:7248
          if (settledParseAheadClass5A28(a)) {
            // 34:5BA7–5BB1 increments D when bit 5 is set OR E is zero.
            if (bit(b,5) || e === 0) d = (d + 1) & 0xff;
            continue;
          }
          continue;
        }
        if (a === 0xef) {
          a = advanceByte(); // bjump 00:3057 -> 38:7248
          if (settledParseAheadClass5A14(a)) {
            if (bit(b,5) || e === 0) d = (d + 1) & 0xff;
            continue;
          }
          if (!mode23()) {
            if (0x1f <= a && a < 0x2c) cursor = bc + 4;
            continue;
          }
          if (0x1f <= a && a < 0x2c) {
            cursor = bc + 4;
            const next = peekNext();
            if (next === 0 || next === 0x3f) continue;
            bc = cursor;
            const result = exitDepth('34:5B51–5B6A');
            if (result) return result;
            continue;
          }
          bc--;
          if (a === 0x2e || a === 0x2f) {
            const result = exitDepth('34:5B6C–5B73');
            if (result) return result;
          }
          continue;
        }

        if (settledParseAheadClass5A52(a)) {
          if (bit(b,5) || e === 0) d = (d + 1) & 0xff;
          continue;
        }
        if (bit(b,3)) {
          if (a === 0x82 || a === 0x83 || a === 0x94) {
            const result = exitDepth('34:5B7E–5B95');
            if (result) return result;
            continue;
          }
          if (a < 0x82 || 0x84 <= a && a < 0x94) {
            if (bit(b,2) && settledParseAheadClass5A75(a)) {
              const result = exitDepth('34:5B98–5BA2');
              if (result) return result;
              continue;
            }
          }
        } else if (bit(b,2) && settledParseAheadClass5A75(a)) {
          const result = exitDepth('34:5B98–5BA2');
          if (result) return result;
          continue;
        }

        if (a === 0x2a) {
          if (!modeBroad() || !quoteBackwardCarry()) {
            a = scanQuotedRun();
            if (a === 0x3f)
              return finishStatus1Zero('34:5BB5–5BD2');
            continue;
          }
        }
        if (SETTLED_TWO_BYTE_LEADS.has(a)) {
          cursor = bc + 1;
          continue;
        }
        if (bit(b,0)) continue;
        if (a === 0x11) {
          if (!bit(b,5) && e !== 0) continue;
          if (!modeBroad()) {
            if (!bit(b,4)) {
              d = (d - 1) & 0xff;
              if (signed(d) < 0)
                return finishStatus1(a,'34:5C21–5C34');
            } else {
              d = (d - 1) & 0xff;
              if (signed(d) >= 0) continue;
              counter = (counter + 1) & 0xff;
              d = 0;
              continue;
            }
          } else {
            d = (d - 1) & 0xff;
            if (d === 0) {
              b |= 0x40;
              continue;
            }
            if (signed(d) >= 0 || bit(c,0) || bit(b,5) || !bit(b,4)) {
              d = (d + 1) & 0xff;
              d = (d - 1) & 0xff;
              if (signed(d) < 0)
                return finishStatus1(a,'34:5BF8–5C34');
              continue;
            }
            counter = (counter + 1) & 0xff;
            d = 0;
            continue;
          }
        }
      }

      if (a === 0x06 || a === 0x08) {
        e = (e + 1) & 0xff;
        braceCount = (braceCount + 1) & 0xff;
        continue;
      }
      if (a === 0x07) {
        if (!bit(b,5)) {
          if (e !== 0) e = (e - 1) & 0xff;
          continue;
        }
        if (d !== 0) {
          if (e !== 0) e = (e - 1) & 0xff;
          continue;
        }
        e = (e - 1) & 0xff;
        if (signed(e) < 0) return finish(0,0,'34:5C45–5C5B');
        continue;
      }
      if (a === 0x09) {
        if (e !== 0) e = (e - 1) & 0xff;
        continue;
      }
      if (!bit(b,7) && a === 0x2b && !bit(b,1)) {
        const result = exitDepth('34:5C6C–5C84');
        if (result) return result;
      }
    }
  }

  const settledSequence = parts => {
    const flat = [];
    const append = part => {
      if (part.kind === 'sequence') {
        for (const child of part.parts) append(child);
        return;
      }
      const previous = flat[flat.length - 1];
      if (part.kind === 'tokens' && previous && previous.kind === 'tokens') {
        previous.tokens.push(...part.tokens);
        return;
      }
      flat.push(part);
    };
    for (const part of parts) append(part);
    if (!flat.length)
      throw new RangeError('settled native scanner produced an empty sequence');
    return flat.length === 1 ? flat[0] : {kind:'sequence',parts:flat};
  };

  // Translate the source expression into the calculator's native token order.
  // Multi-argument MathPrint templates do not store children in screen order:
  // fnInt and summation store body, variable, lower, upper, while logBASE stores
  // argument before base. The page-34 scanner consumes these orders directly.
  function encodeSettledExpressionTokens(input) {
    const spec = settledExpressionSpec(input);
    const encode = expression => {
      if (expression.kind === 'tokens') return expression.tokens.slice();
      if (expression.kind === 'sequence') return expression.parts.flatMap(part =>
        part.kind === 'fraction' ? [0x10,...encode(part),0x11] : encode(part));
      if (expression.kind === 'group')
        return [0x10,...encode(expression.expression),0x11];
      if (expression.kind === 'list') {
        const result = [0x08];
        for (let index = 0; index < expression.elements.length; index++) {
          if (index) result.push(0x2b);
          result.push(...encode(expression.elements[index]));
        }
        result.push(0x09);
        return result;
      }
      if (expression.kind === 'power') {
        const exponent = encode(expression.exponent);
        const numeric = expression.exponent.kind === 'tokens' &&
          expression.exponent.tokens.every(token =>
            SETTLED_RAISED_NUMERIC_TOKENS.has(token));
        // A stacked-fraction template in a raised slot contributes two native
        // boundary pairs. The page-34 scanner consumes both as range markers;
        // they do not become visible parenthesis glyphs in the child record.
        return expression.exponent.kind === 'fraction'
          ? [...encode(expression.base),0xf0,0x10,0x10,
             ...exponent,0x11,0x11]
          : numeric
            ? [...encode(expression.base),0xf0,...exponent]
            : [...encode(expression.base),0xf0,0x10,...exponent,0x11];
      }
      if (expression.kind === 'absolute')
        return [0xb2,...encode(expression.body),0x11];
      if (expression.kind === 'ePower')
        return [0xbf,...encode(expression.exponent),0x11];
      if (expression.kind === 'tenPower')
        return [0xc1,...encode(expression.exponent),0x11];
      if (expression.kind === 'logBase') return [
        0xef,0x34,...encode(expression.argument),0x2b,
        ...encode(expression.base),0x11,
      ];
      if (expression.kind === 'matrix') {
        const result = [0x06];
        for (let row = 0; row < expression.rows; row++) {
          result.push(0x06);
          for (let column = 0; column < expression.columns; column++) {
            if (column) result.push(0x2b);
            result.push(...encode(
              expression.elements[row * expression.columns + column]));
          }
          result.push(0x07);
        }
        result.push(0x07);
        return result;
      }
      if (expression.kind === 'radical')
        return [0xbc,...encode(expression.radicand),0x11];
      if (expression.kind === 'nthRoot') return [
        ...encode(expression.index),0xf1,
        // The template slot supplies a range boundary. Parenthesis tokens are
        // the native byte representation available to a standalone stream;
        // settledExpressionFromTokens removes this one boundary layer.
        0x10,...encode(expression.radicand),0x11,
      ];
      if (expression.kind === 'fraction') {
        const operand = child => {
          if (child.kind === 'tokens') return encode(child);
          // The fraction scanner consumes one 10h…11h pair as its operand
          // boundary. An explicit group needs its own inner pair so the child
          // leaf retains visible parentheses after that boundary is removed.
          return [0x10,...encode(child),0x11];
        };
        return [
          ...operand(expression.numerator),0xef,0x2e,
          ...operand(expression.denominator),
        ];
      }
      if (expression.kind === 'integral') return [
        0x24,...encode(expression.body),0x2b,...encode(expression.variable),
        0x2b,...encode(expression.lower),0x2b,...encode(expression.upper),0x11,
      ];
      if (expression.kind === 'summation') return [
        0xef,0x33,...encode(expression.body),0x2b,...encode(expression.variable),
        0x2b,...encode(expression.lower),0x2b,...encode(expression.upper),0x11,
      ];
      if (expression.kind === 'nDeriv') return [
        0x25,...encode(expression.body),0x2b,...encode(expression.variable),
        0x2b,...encode(expression.value),0x11,
      ];
      throw new RangeError(
        `unsupported native token encoding kind ${expression.kind}`);
    };
    return encode(spec);
  }

  // Byte-oriented translation of the page-34 source-token classification
  // boundary. It recognizes the structural tokens mapped by 34:594D, retains
  // all ordinary bytes in leaf order, and applies the native template argument
  // order before the settled-record constructor runs.
  function settledExpressionFromTokens(input) {
    const native = settledNativeTokenUnits(input);
    const units = native.units;
    let cursor = 0;
    // Fraction scanning supplies a half-open byte endpoint for a complex
    // denominator. Keep the recursive expression parser inside that endpoint;
    // otherwise a following power or product is consumed as part of the
    // denominator before 34:5795's boundary can be checked.
    let parseLimit = null;
    const atLimit = () => cursor >= units.length ||
      (parseLimit !== null && units[cursor].offset >= parseLimit);
    const currentOffset = () => cursor < units.length
      ? units[cursor].offset : native.bytes.length;
    const peek = (prefix, token, ahead = 0) => {
      const unit = units[cursor + ahead];
      return !!unit && (parseLimit === null || unit.offset < parseLimit) &&
        unit.prefix === prefix && unit.token === token;
    };
    const take = () => units[cursor++];
    const tokenNode = unit => ({kind:'tokens',tokens:unit.bytes.slice()});
    const expect = (prefix, token, label) => {
      if (!peek(prefix,token))
        throw new RangeError(`settled native ${label} is missing`);
      return take();
    };
    const unwrapFractionBoundary = expression => expression.kind === 'group'
      ? expression.expression : expression;

    let expression;
    let product;
    let fraction;
    let power;
    let atom;

    const parseAheadArgument = (label, scanned = null) => {
      if (atLimit())
        throw new RangeError(`${label} is empty`);
      const start = units[cursor].offset;
      const boundary = scanned ? scanned.parseAhead
        : settledParseAhead(native.bytes,{
          entry:'internal5AA3', c:1, cursor:start - 1,
        });
      if (scanned && start !== scanned.start)
        throw new RangeError(
          `${label} starts at byte ${start}; 34:5678 selected byte ${scanned.start}`);
      // Structural scanners return a half-open child endpoint. Restrict the
      // recursive expression parser to that endpoint so a nested power or
      // function cannot consume the following argument delimiter.
      const savedLimit = parseLimit;
      parseLimit = scanned ? scanned.end : boundary.stopCursor;
      let value;
      try {
        value = expression();
      } finally {
        parseLimit = savedLimit;
      }
      if (!value)
        throw new RangeError(`${label} is empty`);
      const parsedEnd = currentOffset();
      const scannedEnd = scanned ? scanned.end : boundary.stopCursor;
      if (parsedEnd !== scannedEnd)
        throw new RangeError(
          `${label} parser stopped at byte ${parsedEnd}; ` +
          `${scanned ? '34:5678' : '34:5AA3'} stopped at byte ${scannedEnd}`);
      return value;
    };

    const parseArguments = (count, label, structuralScan = null) => {
      if (structuralScan && structuralScan.arguments.length !== count)
        throw new Error(
          `${label} expected ${count} arguments; 34:59AC selected ` +
          `${structuralScan.arguments.length}`);
      const result = [];
      for (let index = 0; index < count; index++) {
        result.push(parseAheadArgument(
          `${label} argument ${index + 1}`,
          structuralScan && structuralScan.arguments[index]));
        if (index + 1 < count) expect(0,0x2b,`${label} comma`);
      }
      expect(0,0x11,`${label} closing parenthesis`);
      return result;
    };

    const parseStructuralArguments = (scan, label) => {
      const source = parseArguments(scan.arguments.length, label, scan);
      return new Map(source.map((value, index) =>
        [scan.argumentChildOrder[index],value]));
    };

    const parseFunctionRun = opener => {
      const parts = [tokenNode(opener)];
      parts.push(parseAheadArgument('settled native function argument'));
      while (peek(0,0x2b)) {
        parts.push(tokenNode(take()));
        parts.push(parseAheadArgument('settled native function argument'));
      }
      parts.push(tokenNode(expect(0,0x11,'function closing parenthesis')));
      return settledSequence(parts);
    };

    const parseMatrix = () => {
      const scan = settledMatrixContainerScan(
        native.bytes,units[cursor].offset);
      expect(0,0x06,'matrix opening square bracket');
      const rows = [];
      let elementIndex = 0;
      while (peek(0,0x06)) {
        take();
        const row = [];
        for (let column = 0; column < scan.columns; column++) {
          row.push(parseAheadArgument(
            `settled native matrix element ${elementIndex + 1}`,
            scan.elements[elementIndex++]));
          if (column + 1 < scan.columns)
            expect(0,0x2b,'matrix element comma');
        }
        expect(0,0x07,'matrix row closing square bracket');
        rows.push(row);
      }
      expect(0,0x07,'matrix closing square bracket');
      const parsedEnd = currentOffset();
      if (elementIndex !== scan.elements.length || parsedEnd !== scan.stopCursor)
        throw new RangeError(
          `settled native matrix parser stopped at byte ${parsedEnd}; ` +
          `kind 6 stopped at byte ${scan.stopCursor}`);
      return {
        kind:'matrix', rows:scan.rows, columns:scan.columns,
        elements:rows.flat(),
      };
    };

    const parseList = () => {
      expect(0,0x08,'list opening brace');
      if (peek(0,0x09))
        throw new RangeError('settled native list is empty');
      const elements = [];
      for (;;) {
        const element = expression();
        if (!element)
          throw new RangeError(
            `settled native list element ${elements.length + 1} is empty`);
        elements.push(element);
        if (!peek(0,0x2b)) break;
        take();
      }
      expect(0,0x09,'list closing brace');
      return {kind:'list',elements};
    };

    atom = () => {
      if (atLimit() || peek(0,0x11) || peek(0,0x07) ||
          peek(0,0x09) ||
          peek(0,0x2b)) return null;
      if (peek(0,0x10)) {
        take();
        const grouped = expression();
        if (!grouped)
          throw new RangeError('settled native parenthesized expression is empty');
        expect(0,0x11,'group closing parenthesis');
        if (grouped.kind === 'fraction') return grouped;
        return {kind:'group',expression:grouped};
      }
      if (peek(0,0x08)) return parseList();
      if (peek(0,0x06) && peek(0,0x06,1)) return parseMatrix();
      if (peek(0,0xb0)) {
        const sign = take();
        const operand = atom();
        if (!operand)
          throw new RangeError('settled native negation has no operand');
        return operand.kind === 'tokens'
          ? {kind:'tokens',tokens:[...sign.bytes,...operand.tokens]}
          : settledSequence([tokenNode(sign),operand]);
      }
      if (peek(0,0xb2)) {
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,'absolute value');
        return {kind:'absolute',body:children.get(1)};
      }
      if (peek(0,0xbc)) {
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,'radical');
        return {kind:'radical',radicand:children.get(1)};
      }
      if (peek(0,0xbd)) {
        take();
        const [radicand] = parseArguments(1,'cube root');
        return {kind:'nthRoot',index:{kind:'tokens',tokens:[0x33]},radicand};
      }
      if (peek(0,0xbf) || peek(0,0xc1)) {
        const kind = peek(0,0xbf) ? 'ePower' : 'tenPower';
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,kind);
        return {kind,exponent:children.get(1)};
      }
      if (peek(0,0x24)) {
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,'integral');
        return {
          kind:'integral', lower:children.get(1), upper:children.get(2),
          body:children.get(3), variable:children.get(4),
        };
      }
      if (peek(0,0x25)) {
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,'nDeriv');
        return {
          kind:'nDeriv', variable:children.get(1), body:children.get(2),
          value:children.get(3),
        };
      }
      if (peek(0xef,0x33)) {
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,'summation');
        return {
          kind:'summation', variable:children.get(1), lower:children.get(2),
          upper:children.get(3), body:children.get(4),
        };
      }
      if (peek(0xef,0x34)) {
        const scan = settledStructuralArgumentScan(
          native.bytes,units[cursor].offset);
        take();
        const children = parseStructuralArguments(scan,'logBASE');
        return {
          kind:'logBase', base:children.get(1), argument:children.get(2),
        };
      }
      if (settledParseAheadFunctionToken(
          units[cursor].prefix, units[cursor].token))
        return parseFunctionRun(take());

      const unsupportedStructuralType = settledStructuralTokenType(
        units[cursor].prefix, units[cursor].token);
      if (units[cursor].prefix === 0xef && units[cursor].token === 0x36)
        throw settledEf36ResetError(settledEf36SourcePath());
      if (unsupportedStructuralType !== null)
        throw new RangeError(
          `settled native structural type 0x${unsupportedStructuralType.toString(16)} ` +
          `at byte ${units[cursor].offset} has no translated constructor`);

      // The 5Fh and EBh designators plus their bounded alphanumeric name are
      // one parser atom. This matches the raised-operand endpoint selected by
      // 34:5836–5855 instead of treating each name character as an implicit
      // multiplication factor.
      if (peek(0,0x5f) || peek(0,0xeb)) {
        const designator = take();
        const limit = designator.token === 0x5f ? 8 : 5;
        const scan = settledRaisedNameScan(
          native.bytes,designator.next,limit);
        const bytes = designator.bytes.slice();
        while (!atLimit() && units[cursor].offset < scan.end)
          bytes.push(...take().bytes);
        return {kind:'tokens',tokens:bytes};
      }

      // A numeric literal is one scanner atom. Letters and named two-byte
      // variables remain separate atoms so X^2 in 2X^2 binds only X.
      if (units[cursor].prefix === 0 &&
          0x30 <= units[cursor].token && units[cursor].token <= 0x3b) {
        const bytes = [];
        while (!atLimit() && units[cursor].prefix === 0 &&
               0x30 <= units[cursor].token && units[cursor].token <= 0x3b)
          bytes.push(...take().bytes);
        return {kind:'tokens',tokens:bytes};
      }
      return tokenNode(take());
    };

    power = () => {
      let left = atom();
      if (!left) return null;
      while (peek(0,0x0d) || peek(0,0x0f)) {
        const exponent = peek(0,0x0d) ? 0x32 : 0x33;
        take();
        left = {kind:'power',base:left,
                exponent:{kind:'tokens',tokens:[exponent]}};
      }
      for (;;) {
        if (!peek(0,0xf0) && !peek(0,0xf1)) break;
        const nthRoot = peek(0,0xf1);
        const operator = take();
        const scan = settledRaisedOperandScan(native.bytes,operator.offset);
        // The raised scanner returns a half-open endpoint. Keep the recursive
        // parser inside an explicit 10h…11h slot so a following F0/F1 is
        // assigned to the enclosing expression rather than to the slot.
        const savedLimit = parseLimit;
        const raisedEnd = savedLimit === null
          ? scan.end : Math.min(scan.end,savedLimit);
        parseLimit = raisedEnd;
        let right;
        try {
          right = power();
        } finally {
          parseLimit = savedLimit;
        }
        if (!right)
          throw new RangeError('settled native raised operator has no right operand');
        const parsedEnd = currentOffset();
        if (parsedEnd !== raisedEnd)
          throw new RangeError(
            `settled raised parser stopped at byte ${parsedEnd}; ` +
            `34:5699 stopped at byte ${raisedEnd}`);
        const raised = scan.branch === '34:56BB–56D3' &&
          right.kind === 'group' ? right.expression : right;
        left = nthRoot
          ? {kind:'nthRoot',index:left,
             radicand:raised}
          : {kind:'power',base:left,exponent:raised};
      }
      return left;
    };

    const beginsImplicitFactor = () => {
      if (atLimit()) return false;
      return !(peek(0,0x11) || peek(0,0x07) || peek(0,0x09) ||
        peek(0,0x2b) ||
        peek(0,0x70) || peek(0,0x71) || peek(0,0x82) || peek(0,0x83) ||
        peek(0,0xf0) || peek(0,0xf1) || peek(0xef,0x2e) ||
        peek(0xef,0x2f));
    };

    product = () => {
      const parts = [];
      const first = power();
      if (!first) return null;
      parts.push(first);
      while (peek(0,0x82) || peek(0,0x83) || beginsImplicitFactor()) {
        if (peek(0,0x82) || peek(0,0x83)) parts.push(tokenNode(take()));
        const right = power();
        if (!right)
          throw new RangeError('settled native product has no right operand');
        parts.push(right);
      }
      return settledSequence(parts);
    };

    fraction = () => {
      const startCursor = cursor;
      const left = product();
      if (!left) return null;
      if (peek(0xef,0x2e) || peek(0xef,0x2f)) {
        const operator = take();
        const scan = settledFractionOperandScan(
          native.bytes,operator.offset,units[startCursor].offset);
        const savedLimit = parseLimit;
        const denominatorEnd = savedLimit === null
          ? scan.denominator.end : Math.min(scan.denominator.end,savedLimit);
        parseLimit = denominatorEnd;
        let right;
        try {
          right = fraction();
        } finally {
          parseLimit = savedLimit;
        }
        if (!right)
          throw new RangeError('settled native stacked fraction has no denominator');
        const parsedEnd = currentOffset();
        // The direct 34:5795 walk can continue through wrapper delimiters
        // belonging to an enclosing function or matrix. Once the recursive
        // parser has reached one of those delimiters, its endpoint is the
        // denominator endpoint for this nested expression.
        const next = units[cursor];
        const nestedBoundary = parsedEnd < denominatorEnd && next &&
          (next.prefix === 0 && (next.token === 0x11 || next.token === 0x07 ||
            next.token === 0x09 || next.token === 0x2b));
        const denominatorStop = nestedBoundary ? parsedEnd : denominatorEnd;
        if (parsedEnd !== denominatorStop)
          throw new RangeError(
            `settled native denominator parser stopped at byte ${parsedEnd}; ` +
            `34:5795 stopped at byte ${denominatorStop}`);
        const result = {
          kind:'fraction', numerator:unwrapFractionBoundary(left),
          denominator:unwrapFractionBoundary(right),
        };
        // A parenthesized stacked fraction is emitted without an enclosing
        // 10h…11h pair when it occupies the base slot of a following power.
        // 34:5699 therefore sees F0/F1 immediately after the fraction's
        // denominator. Parse that suffix here; power() has already consumed
        // the raised suffix for ordinary atoms.
        if (peek(0,0xf0) || peek(0,0xf1)) {
          const nthRoot = peek(0,0xf1);
          const raisedOperator = take();
          const raisedScan = settledRaisedOperandScan(
            native.bytes,raisedOperator.offset);
          const savedRaisedLimit = parseLimit;
          const raisedEnd = savedRaisedLimit === null
            ? raisedScan.end : Math.min(raisedScan.end,savedRaisedLimit);
          parseLimit = raisedEnd;
          let raised;
          try {
            raised = power();
          } finally {
            parseLimit = savedRaisedLimit;
          }
          if (!raised)
            throw new RangeError(
              'settled native fraction raised operator has no right operand');
          const parsedRaisedEnd = currentOffset();
          if (parsedRaisedEnd !== raisedEnd)
            throw new RangeError(
              `settled native raised parser stopped at byte ${parsedRaisedEnd}; ` +
              `34:5699 stopped at byte ${raisedEnd}`);
          return nthRoot
            ? {kind:'nthRoot',index:result,radicand:
               raised.kind === 'group' ? raised.expression : raised}
            : {kind:'power',base:result,
               exponent:raised.kind === 'group' ? raised.expression : raised};
        }
        return result;
      }
      return left;
    };

    expression = () => {
      const parts = [];
      const first = fraction();
      if (!first) return null;
      parts.push(first);
      while (peek(0,0x70) || peek(0,0x71)) {
        parts.push(tokenNode(take()));
        const right = fraction();
        if (!right)
          throw new RangeError('settled native sum has no right operand');
        parts.push(right);
      }
      return settledSequence(parts);
    };

    const result = expression();
    if (!result || cursor !== units.length) {
      const offset = cursor < units.length ? units[cursor].offset : native.bytes.length;
      throw new RangeError(
        `settled native scanner stopped at byte ${offset} of ${native.bytes.length}`);
    }
    return result;
  }

  // Decode the settled graph consumed by 34:660A into the semantic structure
  // recovered by the record analyzer.  This is deliberately separate from
  // settledExpressionFromTokens(): the token parser reconstructs a graph from
  // native bytes, while this routine reads the graph's actual child IDs and
  // leaf payload markers.  Type 2Ah is postfix, so its marker binds to the
  // expression immediately before EF 2A id_lo id_hi.
  function decodeSettledExpressionGraph(inputs, entryId, activeLeafIds = null,
                                        editorCursorState = null) {
    if (!Array.isArray(inputs))
      throw new TypeError('settled expression graph must be an array');
    if (!Number.isInteger(entryId) || entryId < 0 || entryId > 0xffff)
      throw new RangeError('settled expression entry ID must be an unsigned word');
    const byId = new Map();
    for (const input of inputs) {
      if (!input || typeof input !== 'object')
        throw new TypeError('settled expression node must be an object');
      const id = input.record_id === undefined ? input.id : input.record_id;
      if (!Number.isInteger(id) || id < 0 || id > 0xffff)
        throw new RangeError('settled expression node ID must be an unsigned word');
      if (byId.has(id))
        throw new RangeError(`duplicate settled expression record ID 0x${id.toString(16)}`);
      byId.set(id, input);
    }
    if (!byId.has(entryId))
      throw new RangeError(`settled expression entry ID 0x${entryId.toString(16)} is absent`);

    const active = new Set(activeLeafIds || []);
    const activeStructural = new Set();
    const children = (node, count) => {
      const raw = node.child_ids === undefined ? node.childIds : node.child_ids;
      const id = node.record_id === undefined ? node.id : node.record_id;
      if (!Array.isArray(raw) || raw.length !== count || raw.some(value =>
          !Number.isInteger(value) || value < 0 || value > 0xffff))
        throw new RangeError(
          `settled record 0x${id.toString(16)} requires ${count} child IDs`);
      return raw.slice();
    };
    const collapse = parts => {
      const merged = [];
      for (const part of parts) {
        if (Array.isArray(part) && merged.length &&
            Array.isArray(merged[merged.length - 1]))
          merged[merged.length - 1].push(...part);
        else merged.push(part);
      }
      if (!merged.length) throw new RangeError('settled leaf decodes to an empty expression');
      return merged.length === 1 ? merged[0] : {kind:'sequence',parts:merged};
    };
    const nodeType = node => {
      const type = node.render_type === undefined ? node.type : node.render_type;
      const id = node.record_id === undefined ? node.id : node.record_id;
      if (!Number.isInteger(type) || type < 0 || type > 0xff)
        throw new RangeError(`settled record 0x${id.toString(16)} has no valid type`);
      return type;
    };

    const structural = recordId => {
      if (activeStructural.has(recordId))
        throw new RangeError(
          `settled expression contains a structural cycle at ID 0x${recordId.toString(16)}`);
      const node = byId.get(recordId);
      if (!node) throw new RangeError(
        `embedded settled record ID 0x${recordId.toString(16)} is absent`);
      const type = nodeType(node);
      activeStructural.add(recordId);
      try {
        const withEditorRecordState = expression =>
          editorCursorState && Number.isInteger(node.byte13) ? {
            ...expression,editor_record_byte13:node.byte13,
          } : expression;
        if (type === 0x1f) {
          const ids = children(node, 1);
          return leaf(ids[0]);
        }
        if (type === 0x2b) {
          const rows = node.byte13;
          const columns = Number.isInteger(node.word11) ? node.word11 >> 8 : 0;
          if (!rows || !columns)
            throw new RangeError(
              `settled matrix record 0x${recordId.toString(16)} has zero dimensions`);
          const ids = children(node, rows * columns);
          return withEditorRecordState({
            kind:'matrix',rows,columns,elements:ids.map(leaf),
          });
        }
        const count = {
          0x20:2, 0x21:1, 0x22:4, 0x23:3, 0x24:2,
          0x25:1, 0x26:1, 0x27:1, 0x28:2, 0x29:4, 0x2a:1,
        }[type];
        if (count === undefined)
          throw new RangeError(
            `settled record 0x${recordId.toString(16)} type 0x${type.toString(16)} ` +
            'has no translated expression decoder');
        const ids = children(node, count);
        switch (type) {
        case 0x20: return withEditorRecordState({
          kind:'fraction',numerator:leaf(ids[0]),denominator:leaf(ids[1]),
        });
        case 0x21: return withEditorRecordState({
          kind:'absolute',body:leaf(ids[0]),
        });
        case 0x22: return withEditorRecordState({
          kind:'integral',lower:leaf(ids[0]),upper:leaf(ids[1]),
          body:leaf(ids[2]),variable:leaf(ids[3]),
        });
        case 0x23: return withEditorRecordState({
          kind:'nDeriv',variable:leaf(ids[0]),body:leaf(ids[1]),value:leaf(ids[2]),
        });
        case 0x24: return withEditorRecordState({
          kind:'nthRoot',index:leaf(ids[0]),radicand:leaf(ids[1]),
        });
        case 0x25: return withEditorRecordState({
          kind:'ePower',exponent:leaf(ids[0]),
        });
        case 0x26: return withEditorRecordState({
          kind:'tenPower',exponent:leaf(ids[0]),
        });
        case 0x27: return withEditorRecordState({
          kind:'radical',radicand:leaf(ids[0]),
        });
        case 0x28: return withEditorRecordState({
          kind:'logBase',base:leaf(ids[0]),argument:leaf(ids[1]),
        });
        case 0x29: return withEditorRecordState({
          kind:'summation',variable:leaf(ids[0]),lower:leaf(ids[1]),
          upper:leaf(ids[2]),body:leaf(ids[3]),
        });
        case 0x2a: return withEditorRecordState({
          kind:'powerExponent',exponent:leaf(ids[0]),
        });
        default: throw new Error('unreachable settled structural decoder case');
        }
      } finally {
        activeStructural.delete(recordId);
      }
    };

    function leaf(recordId) {
      if (active.has(recordId))
        throw new RangeError(`settled expression contains a cycle at ID 0x${recordId.toString(16)}`);
      const node = byId.get(recordId);
      if (!node) throw new RangeError(
        `settled leaf ID 0x${recordId.toString(16)} is absent`);
      const type = nodeType(node);
      if (type >= 0x1f)
        throw new RangeError(
          `settled record 0x${recordId.toString(16)} is not a leaf`);
      const payload = node.payload;
      if (!Array.isArray(payload) || payload.some((value, index) =>
          !Number.isInteger(value) || value < 0 || value > 0xff))
        throw new RangeError(
          `settled leaf 0x${recordId.toString(16)} has no byte payload`);
      active.add(recordId);
      try {
        // The leaf payload is a small postfix bytecode, not merely a token
        // run. 34:5699 replaces F0h with an EF 2Ah record marker after leaving
        // its base in the parent leaf. Preserve native atom boundaries here so
        // the marker binds X rather than 2X or A+X, and preserve function
        // frames so sin(X) remains one base even when X is structural.
        const frames = [{kind:'root',items:[],opener:null,pendingNegations:0}];
        const frame = () => frames[frames.length - 1];
        const publicParts = current => current.items.map(item => item.value);
        const flushNegations = current => {
          if (!current.pendingNegations) return;
          current.items.push({role:'raw',value:
            Array(current.pendingNegations).fill(0xb0)});
          current.pendingNegations = 0;
        };
        const appendRaw = bytes => {
          const current = frame();
          flushNegations(current);
          current.items.push({role:'raw',value:bytes.slice()});
        };
        const appendAtom = value => {
          const current = frame();
          if (current.pendingNegations) {
            value = collapse([
              Array(current.pendingNegations).fill(0xb0),value,
            ]);
            current.pendingNegations = 0;
          }
          current.items.push({role:'atom',value});
        };
        const appendEditorCursor = () => {
          frame().items.push({role:'editor-cursor',value:editorCursorState.node});
          editorCursorState.insertions++;
        };
        const insertEditorCursor = index => {
          if (editorCursorState && editorCursorState.recordId === recordId &&
              editorCursorState.byteOffset === index)
            appendEditorCursor();
        };
        const closeFrame = closing => {
          const current = frame();
          flushNegations(current);
          const parts = publicParts(current);
          frames.pop();
          if (current.kind === 'group') {
            if (!parts.length)
              throw new RangeError('settled parenthesized expression is empty');
            appendAtom({kind:'group',expression:collapse(parts)});
            return;
          }
          if (current.kind === 'list') {
            if (!parts.length)
              throw new RangeError('settled list has an empty element');
            current.elements.push(collapse(parts));
            appendAtom({kind:'list',elements:current.elements});
            return;
          }
          appendAtom(collapse([current.opener,...parts,closing]));
        };
        const isRawOperator = (prefix, token) => prefix === 0 &&
          (SETTLED_PARSE_AHEAD_OPERATORS_7F05.has(token) ||
           token === 0x2b || token === 0x07 || token === 0x09);
        const isNameCharacter = token =>
          (0x30 <= token && token <= 0x39) ||
          (0x41 <= token && token <= 0x5b);
        const decodeInline = bytes => {
          let inlineId = 0xffff;
          while (inlineId >= 0 && byId.has(inlineId)) inlineId--;
          if (inlineId < 0)
            throw new RangeError('settled graph has no free inline record ID');
          return decodeSettledExpressionGraph([
            ...inputs,
            {record_id:inlineId,render_type:0,child_ids:[],payload:bytes},
          ],inlineId,active);
        };
        const matrixContainer = start => {
          if (payload[start] !== 0x06 || payload[start + 1] !== 0x06)
            throw new RangeError('settled matrix has no outer and row opener');
          let cursor = start + 1;
          const rows = [];
          for (;;) {
            if (cursor >= payload.length)
              throw new RangeError(
                'settled matrix has no outer closing 07h token');
            if (payload[cursor] === 0x07) {
              if (!rows.length)
                throw new RangeError('settled matrix has no rows');
              cursor++;
              break;
            }
            if (payload[cursor] !== 0x06)
              throw new RangeError(
                'settled matrix row-opening 06h token is missing');
            cursor++;
            const row = [];
            for (;;) {
              const elementStart = cursor;
              const closers = [];
              while (cursor < payload.length) {
                const token = payload[cursor];
                if (!closers.length && (token === 0x2b || token === 0x07))
                  break;
                if (token === 0xef && cursor + 1 < payload.length &&
                    0x1f <= payload[cursor + 1] &&
                    payload[cursor + 1] <= 0x2b) {
                  if (cursor + 5 >= payload.length ||
                      payload[cursor + 4] !== 0xef ||
                      payload[cursor + 5] !== 0x2d)
                    throw new RangeError(
                      'settled matrix element has a truncated record marker');
                  cursor += 6;
                  continue;
                }
                let prefix = 0, subtype = token, length = 1;
                if (SETTLED_TWO_BYTE_LEADS.has(token)) {
                  if (cursor + 1 >= payload.length)
                    throw new RangeError(
                      'settled matrix element ends in a two-byte token lead');
                  prefix = token;
                  subtype = payload[cursor + 1];
                  length = 2;
                }
                if (prefix === 0 &&
                    (subtype === 0x10 || subtype === 0x08 || subtype === 0x06))
                  closers.push({0x10:0x11,0x08:0x09,0x06:0x07}[subtype]);
                else if (settledParseAheadFunctionToken(prefix,subtype))
                  closers.push(0x11);
                else if (prefix === 0 &&
                         (subtype === 0x11 || subtype === 0x09 || subtype === 0x07)) {
                  if (!closers.length || closers[closers.length - 1] !== subtype)
                    throw new RangeError(
                      'settled matrix element has an unmatched delimiter');
                  closers.pop();
                }
                cursor += length;
              }
              if (closers.length)
                throw new RangeError(
                  'settled matrix element has an unclosed delimiter');
              if (cursor === elementStart)
                throw new RangeError('settled matrix row has an empty element');
              row.push(decodeInline(payload.slice(elementStart,cursor)));
              if (cursor >= payload.length)
                throw new RangeError(
                  'settled matrix row has no closing 07h token');
              const delimiter = payload[cursor++];
              if (delimiter === 0x07) break;
            }
            rows.push(row);
          }
          const columns = rows[0].length;
          if (!columns || rows.some(row => row.length !== columns))
            throw new RangeError('settled matrix rows must have equal width');
          return {
            end:cursor,
            expression:{kind:'matrix',rows:rows.length,columns,
              elements:rows.flat()},
          };
        };
        for (let index = 0; index < payload.length;) {
          insertEditorCursor(index);
          const token = payload[index];
          if (token === 0x06 && payload[index + 1] === 0x06) {
            const matrix = matrixContainer(index);
            appendAtom(matrix.expression);
            index = matrix.end;
            continue;
          }
          if (token === 0x10) {
            frames.push({kind:'group',items:[],opener:[0x10],pendingNegations:0});
            index++;
            continue;
          }
          if (token === 0x08) {
            frames.push({kind:'list',items:[],elements:[],opener:[0x08],
              pendingNegations:0});
            index++;
            continue;
          }
          if (token === 0x11) {
            if (frames.length === 1 || frame().kind === 'list') {
              appendAtom([token]);
              index++;
              continue;
            }
            closeFrame([token]);
            index++;
            continue;
          }
          if (token === 0x09) {
            if (frames.length === 1 || frame().kind !== 'list') {
              appendAtom([token]);
              index++;
              continue;
            }
            closeFrame([token]);
            index++;
            continue;
          }
          let prefix = 0;
          let subtype = token;
          let unitBytes = [token];
          if (SETTLED_TWO_BYTE_LEADS.has(token)) {
            if (index + 1 >= payload.length)
              throw new RangeError(
                `settled leaf 0x${recordId.toString(16)} ends with ` +
                `${token.toString(16).padStart(2,'0')}`);
            prefix = token;
            subtype = payload[index + 1];
            unitBytes = [token,subtype];
          }
          if (prefix === 0xef && subtype === 0x2d) {
            index += 2;
            continue;
          }
          if (prefix === 0xef && subtype === 0x1e) {
            appendAtom({kind:'extendedToken',tokens:[0xef,0x1e]});
            index += 2;
            continue;
          }
          if (prefix === 0xef && 0x1f <= subtype && subtype <= 0x2b) {
            if (index + 3 >= payload.length)
              throw new RangeError(
                `settled leaf 0x${recordId.toString(16)} has unsupported EF ` +
                `subtype 0x${subtype.toString(16)}`);
            const embeddedId = payload[index + 2] | payload[index + 3] << 8;
            const embedded = structural(embeddedId);
            if (subtype === 0x2a) {
              if (embedded.kind !== 'powerExponent')
                throw new RangeError(
                  `settled power marker references non-power ID 0x${embeddedId.toString(16)}`);
              const current = frame();
              flushNegations(current);
              let candidateIndex = current.items.length - 1;
              while (candidateIndex >= 0 &&
                     current.items[candidateIndex].role === 'editor-cursor')
                candidateIndex--;
              const candidate = current.items[candidateIndex];
              if (!candidate || candidate.role !== 'atom')
                throw new RangeError(
                  `settled power ID 0x${embeddedId.toString(16)} in leaf ` +
                  `0x${recordId.toString(16)} has no preceding base; payload ` +
                  payload.map(value => value.toString(16).padStart(2,'0')).join(' '));
              candidate.value = {
                kind:'power',base:candidate.value,
                exponent:embedded.exponent,
                ...(embedded.editor_record_byte13 === undefined ? {} : {
                  editor_record_byte13:embedded.editor_record_byte13,
                }),
              };
            } else appendAtom(embedded);
            index += 4;
            continue;
          }
          if (settledParseAheadFunctionToken(prefix,subtype)) {
            frames.push({kind:'function',items:[],opener:unitBytes,
              pendingNegations:0});
            index += unitBytes.length;
            continue;
          }
          if (prefix === 0 && subtype === 0xb0) {
            frame().pendingNegations++;
            index++;
            continue;
          }
          if (prefix === 0 && (subtype === 0x5f || subtype === 0xeb)) {
            const limit = subtype === 0x5f ? 8 : 5;
            const bytes = [subtype];
            index++;
            while (bytes.length <= limit && index < payload.length &&
                   (!editorCursorState ||
                    editorCursorState.recordId !== recordId ||
                    editorCursorState.byteOffset !== index) &&
                   isNameCharacter(payload[index])) bytes.push(payload[index++]);
            appendAtom(bytes);
            continue;
          }
          if (prefix === 0 && 0x30 <= subtype && subtype <= 0x3b) {
            const bytes = [];
            while (index < payload.length &&
                   (!editorCursorState ||
                    editorCursorState.recordId !== recordId ||
                    editorCursorState.byteOffset !== index) &&
                   0x30 <= payload[index] && payload[index] <= 0x3b)
              bytes.push(payload[index++]);
            appendAtom(bytes);
            continue;
          }
          if (prefix === 0 && subtype === 0x2b && frame().kind === 'list') {
            const current = frame();
            flushNegations(current);
            const parts = publicParts(current);
            if (!parts.length)
              throw new RangeError('settled list has an empty element');
            current.elements.push(collapse(parts));
            current.items = [];
          } else if (isRawOperator(prefix,subtype)) appendRaw(unitBytes);
          else appendAtom(unitBytes);
          index += unitBytes.length;
        }
        insertEditorCursor(payload.length);
        flushNegations(frame());
        while (frames.length > 1) {
          const unfinished = frame();
          flushNegations(unfinished);
          frames.pop();
          appendAtom(collapse([unfinished.opener,...publicParts(unfinished)]));
        }
        return collapse(publicParts(frame()));
      } finally {
        active.delete(recordId);
      }
    }

    const entry = byId.get(entryId);
    return nodeType(entry) >= 0x1f ? structural(entryId) : leaf(entryId);
  }

  // The editor moves across a complete six-byte EF record marker as one
  // structural object. Every other native unit follows _IsA2ByteTok. These are
  // the byte boundaries at which editCursor can split an active leaf without
  // bisecting a packed token or record marker.
  function editorPayloadCursorBoundaries(input) {
    if (!Array.isArray(input) && !(input instanceof Uint8Array))
      throw new TypeError('editor leaf payload must be an array of bytes');
    const payload = Array.from(input, (value, index) =>
      byte(value, `editor leaf payload byte ${index}`));
    const boundaries = [0];
    for (let index = 0; index < payload.length;) {
      let length = 1;
      if (payload[index] === 0xef && index + 1 < payload.length &&
          0x1f <= payload[index + 1] && payload[index + 1] <= 0x2b) {
        if (index + 5 >= payload.length || payload[index + 4] !== 0xef ||
            payload[index + 5] !== 0x2d)
          throw new RangeError(
            `editor structural marker at byte ${index} is truncated`);
        length = 6;
      } else if (SETTLED_TWO_BYTE_LEADS.has(payload[index])) {
        if (index + 1 >= payload.length)
          throw new RangeError(
            `editor two-byte token at byte ${index} is truncated`);
        length = 2;
      }
      index += length;
      boundaries.push(index);
    }
    return boundaries;
  }

  // Ordinary MathPrint key insertion reaches 34:4BB9 after key-to-token
  // conversion. Its non-structural path calls the page-6 gap-buffer writer:
  // it stores the packed native token at editCursor and advances editCursor by
  // one or two bytes. EF 1Eh is the editable empty-slot token; inserting at a
  // cursor immediately before it replaces the slot instead of retaining both.
  function editorInsertPackedToken(input, tokenInput) {
    const inserted = Array.from(tokenInput || [], (value, index) =>
      byte(value, `editor inserted token byte ${index}`));
    const boundaries = editorPayloadCursorBoundaries(inserted);
    if (boundaries.length !== 2 || boundaries[1] !== inserted.length)
      throw new RangeError('editor insertion requires one packed native token');
    if (inserted.length === 6 && inserted[0] === 0xef &&
        0x1f <= inserted[1] && inserted[1] <= 0x2b)
      throw new RangeError(
        'editor structural markers require the structural insertion path');

    const cursorCount = value => {
      if (!value || typeof value !== 'object') return 0;
      if (value.kind === 'editorCursor') return 1;
      if (Array.isArray(value) || value instanceof Uint8Array)
        return Array.from(value).reduce(
          (count, item) => count + cursorCount(item),0);
      return Object.values(value).reduce(
        (count, item) => count + cursorCount(item),0);
    };
    const count = cursorCount(input);
    if (count !== 1)
      throw new RangeError(
        `editor insertion requires one cursor, found ${count}`);

    const tokenBytes = value => {
      if (Array.isArray(value) || value instanceof Uint8Array)
        return Array.from(value);
      if (value && (value.kind === 'tokens' ||
                    value.kind === 'extendedToken') &&
          (Array.isArray(value.tokens) || value.tokens instanceof Uint8Array))
        return Array.from(value.tokens);
      return null;
    };
    const appendToken = value => {
      const bytes = tokenBytes(value);
      if (!bytes) return null;
      if (Array.isArray(value) || value instanceof Uint8Array)
        return [...bytes,...inserted];
      return {...value,tokens:[...bytes,...inserted]};
    };
    const stripLeadingEmptySlot = value => {
      const bytes = tokenBytes(value);
      if (bytes && bytes[0] === 0xef && bytes[1] === 0x1e) {
        const rest = bytes.slice(2);
        if (!rest.length) return {value:null,replaced:true};
        if (Array.isArray(value) || value instanceof Uint8Array)
          return {value:rest,replaced:true};
        return {value:{...value,tokens:rest},replaced:true};
      }
      if (value && value.kind === 'sequence' &&
          Array.isArray(value.parts) && value.parts.length) {
        const stripped = stripLeadingEmptySlot(value.parts[0]);
        if (!stripped.replaced) return {value,replaced:false};
        const parts = stripped.value === null
          ? value.parts.slice(1) : [stripped.value,...value.parts.slice(1)];
        return {
          value:parts.length ? {...value,parts} : null,
          replaced:true,
        };
      }
      return {value,replaced:false};
    };

    let mutation = null;
    const updatedCursor = cursor => {
      const before = cursor.byte_offset;
      const after = before === undefined ? undefined : before + inserted.length;
      mutation = {
        inserted:inserted.slice(),
        record_id:cursor.record_id,
        before_byte_offset:before,
        after_byte_offset:after,
        replaced_empty_slot:false,
        routine:'34:4775–47A4 → 34:4BB9–4C0D → 00:3699 → 06:4341–4388',
      };
      return {
        ...cursor,
        ...(after === undefined ? {} : {byte_offset:after}),
      };
    };
    const visit = value => {
      if (!value || typeof value !== 'object') return value;
      if (value.kind === 'editorCursor')
        return {kind:'sequence',parts:[inserted.slice(),updatedCursor(value)]};
      if (Array.isArray(value) || value instanceof Uint8Array) return value;
      if (value.kind === 'sequence' && Array.isArray(value.parts)) {
        const direct = value.parts.findIndex(
          part => part && part.kind === 'editorCursor');
        if (direct >= 0) {
          const parts = value.parts.slice();
          const cursor = updatedCursor(parts[direct]);
          const appended = direct > 0 ? appendToken(parts[direct - 1]) : null;
          if (appended) {
            parts[direct - 1] = appended;
            parts[direct] = cursor;
          } else {
            parts.splice(direct,0,inserted.slice());
            parts[direct + 1] = cursor;
          }
          const cursorIndex = appended ? direct : direct + 1;
          if (cursorIndex + 1 < parts.length) {
            const stripped = stripLeadingEmptySlot(parts[cursorIndex + 1]);
            if (stripped.replaced) {
              mutation.replaced_empty_slot = true;
              if (stripped.value === null) parts.splice(cursorIndex + 1,1);
              else parts[cursorIndex + 1] = stripped.value;
            }
          }
          return {...value,parts};
        }
      }
      const result = {};
      for (const [key,child] of Object.entries(value)) {
        if (Array.isArray(child) && child.every(item =>
          Number.isInteger(item))) {
          result[key] = child.slice();
        } else if (Array.isArray(child)) {
          result[key] = child.map(visit);
        } else {
          result[key] = visit(child);
        }
      }
      return result;
    };
    const expression = visit(input);
    if (!mutation)
      throw new RangeError('editor insertion could not locate the cursor');
    return {expression,mutation};
  }

  function editorCursorIdentityPath(value, target, path = [], seen = new Set()) {
    if (value === target) return path;
    if (!value || typeof value !== 'object' || seen.has(value)) return null;
    seen.add(value);
    if (Array.isArray(value)) {
      for (let index = 0; index < value.length; index++) {
        const found = editorCursorIdentityPath(
          value[index],target,[...path,index],seen);
        if (found) return found;
      }
      return null;
    }
    for (const key of Object.keys(value)) {
      const found = editorCursorIdentityPath(value[key],target,[...path,key],seen);
      if (found) return found;
    }
    return null;
  }

  // A live page-34 graph differs from its cursor-free form only at the active
  // leaf selected by 8DC2h. Insert a semantic cursor at editCursor-editTop in
  // that leaf and let the same record-ID decoder recover its nested position.
  function decodeEditorExpressionGraph(inputs, entryId, activeLeafId,
                                       cursorByteOffset) {
    if (!Array.isArray(inputs))
      throw new TypeError('editor expression graph must be an array');
    if (!Number.isInteger(activeLeafId) || activeLeafId < 0 ||
        activeLeafId > 0xffff)
      throw new RangeError('editor active leaf ID must be an unsigned word');
    if (!Number.isInteger(cursorByteOffset) || cursorByteOffset < 0)
      throw new RangeError('editor cursor byte offset must be nonnegative');
    const active = inputs.find(input => input &&
      (input.record_id === undefined ? input.id : input.record_id) === activeLeafId);
    if (!active)
      throw new RangeError(
        `editor active leaf ID 0x${activeLeafId.toString(16)} is absent`);
    const activeType = active.render_type === undefined
      ? active.type : active.render_type;
    if (!Number.isInteger(activeType) || activeType < 0 || activeType >= 0x1f)
      throw new RangeError('editor active record must be a leaf');
    const boundaries = editorPayloadCursorBoundaries(active.payload);
    if (!boundaries.includes(cursorByteOffset))
      throw new RangeError(
        `editor cursor byte ${cursorByteOffset} bisects a native unit`);
    const cursorNode = Object.freeze({
      kind:'editorCursor', record_id:activeLeafId,
      byte_offset:cursorByteOffset,
      record_word0F:active.word0F,
      record_word11:active.word11,
    });
    const state = {
      recordId:activeLeafId, byteOffset:cursorByteOffset,
      node:cursorNode, insertions:0,
    };
    const expression = decodeSettledExpressionGraph(
      inputs,entryId,null,state);
    if (state.insertions !== 1)
      throw new RangeError(
        `editor cursor was inserted ${state.insertions} times`);
    const path = editorCursorIdentityPath(expression,cursorNode);
    if (!path)
      throw new RangeError('editor cursor is absent from the decoded expression');
    return {
      expression,
      cursor:{
        recordId:activeLeafId, byteOffset:cursorByteOffset,
        boundaries, path,
        routine:'34:4AAF; editTop/editCursor at 0x96F4/0x96F6',
      },
    };
  }

  const EDITOR_STRUCTURAL_CHILD_COUNTS = Object.freeze({
    0x1f:1, 0x20:2, 0x21:1, 0x22:4, 0x23:3, 0x24:2,
    0x25:1, 0x26:1, 0x27:1, 0x28:2, 0x29:4, 0x2a:1,
  });

  // Decode the logical 8000h-FFFFh RAM window used by the MathPrint editor.
  // 34:4ACE walks structural records, 34:4A83 walks leaf records, and 34:4AAF
  // substitutes the editTop/editCursor + editTail/editBtm gap payload when the
  // current pointer equals 8DC2h.
  function decodeMathPrintEditorRam(input) {
    if (!Array.isArray(input) && !(input instanceof Uint8Array))
      throw new TypeError('MathPrint editor RAM must be an array of bytes');
    if (input.length < 0x8000)
      throw new RangeError(
        'MathPrint editor RAM must contain the logical 8000h-FFFFh window');
    const ram = Array.from(input.slice(0,0x8000), (value, index) =>
      byte(value, `MathPrint editor RAM byte ${index}`));
    const offset = address => {
      if (!Number.isInteger(address) || address < 0x8000 || address > 0xffff)
        throw new RangeError('MathPrint editor RAM address is outside 8000h-FFFFh');
      return address - 0x8000;
    };
    const word = address => {
      if (address > 0xfffe)
        throw new RangeError('MathPrint editor RAM word crosses FFFFh');
      const start = offset(address);
      return ram[start] | ram[start + 1] << 8;
    };
    const span = (start, end) => {
      if (!Number.isInteger(start) || !Number.isInteger(end) ||
          start < 0x8000 || start > end || end > 0x10000)
        throw new RangeError('MathPrint editor RAM span is inconsistent');
      return ram.slice(start - 0x8000,end - 0x8000);
    };
    const recordAt = pointer => ({
      ...decodeSettledRecord(span(pointer,pointer + 0x14)),
      pointer, child_ids:[], payload:[],
    });

    const structuralStart = word(0x8daf);
    const editorBoundary = word(0x8db1);
    const entryPointer = word(0x8dbc);
    const mainTail = word(0x8dbe);
    const gapRecordPointer = word(0x8dc2);
    if (!(0x8000 <= structuralStart && structuralStart <= entryPointer &&
          entryPointer <= mainTail && mainTail <= 0xffff))
      throw new RangeError('MathPrint record-arena pointers are inconsistent');

    const nodes = [];
    let pointer = structuralStart;
    while (pointer < entryPointer) {
      if (pointer + 0x14 > entryPointer)
        throw new RangeError(
          `structural record at 0x${pointer.toString(16)} has a truncated header`);
      const node = recordAt(pointer);
      if (node.type < 0x1f)
        throw new RangeError(
          `record 0x${node.id.toString(16)} before the entry boundary is a leaf`);
      let semanticChildren;
      let physicalChildren;
      if (node.type === 0x2b) {
        const rows = node.byte13;
        const columns = node.word11 >> 8;
        semanticChildren = rows * columns;
        if (!rows || !columns || semanticChildren > 0xff)
          throw new RangeError(
            `matrix record 0x${node.id.toString(16)} has invalid dimensions`);
        physicalChildren = semanticChildren + 1;
      } else {
        semanticChildren = EDITOR_STRUCTURAL_CHILD_COUNTS[node.type];
        if (semanticChildren === undefined)
          throw new RangeError(
            `structural record 0x${node.id.toString(16)} has unsupported type`);
        physicalChildren = semanticChildren;
      }
      const size = 0x14 + 2 * physicalChildren;
      if (pointer + size > entryPointer)
        throw new RangeError(
          `structural record 0x${node.id.toString(16)} crosses the entry boundary`);
      node.child_ids = new Array(semanticChildren).fill(0).map((_, index) =>
        word(pointer + 0x14 + 2 * index));
      nodes.push(node);
      pointer += size;
    }
    if (pointer !== entryPointer)
      throw new RangeError('MathPrint structural walk missed the entry boundary');

    const gapActive = Boolean(ram[offset(0x89f1)] & 0x04);
    const leafBoundary = gapActive ? editorBoundary : mainTail;
    if (!(entryPointer < leafBoundary && leafBoundary <= 0xffff))
      throw new RangeError('MathPrint leaf-record boundary is inconsistent');
    const editTop = word(0x96f4);
    const editCursor = word(0x96f6);
    const editTail = word(0x96f8);
    const editBottom = word(0x96fa);
    if (!(0x8000 <= editTop && editTop <= editCursor && editCursor <= 0xffff))
      throw new RangeError('MathPrint editor left gap segment is inconsistent');
    if (!(0x8000 <= editTail && editTail <= editBottom && editBottom <= 0xffff))
      throw new RangeError('MathPrint editor right gap segment is inconsistent');
    const left = span(editTop,editCursor);
    const right = span(editTail,editBottom);

    pointer = entryPointer;
    const visited = new Set();
    let activeNode = null;
    while (pointer < leafBoundary) {
      if (visited.has(pointer))
        throw new RangeError(
          `MathPrint leaf-record walk cycles at 0x${pointer.toString(16)}`);
      visited.add(pointer);
      if (pointer > 0xffec)
        throw new RangeError('MathPrint leaf record has no complete header');
      const node = recordAt(pointer);
      if (node.type >= 0x1f)
        throw new RangeError(
          `record 0x${node.id.toString(16)} after the entry boundary is structural`);
      let nextPointer;
      if (gapActive && pointer === gapRecordPointer) {
        node.payload = [...left,...right];
        nextPointer = editBottom;
        activeNode = node;
      } else {
        const payloadEnd = pointer + 0x13 + node.word11;
        if (payloadEnd > 0x10000)
          throw new RangeError(
            `leaf record 0x${node.id.toString(16)} payload crosses FFFFh`);
        node.payload = span(pointer + 0x13,payloadEnd);
        nextPointer = payloadEnd;
      }
      if (!node.payload.length)
        throw new RangeError(
          `leaf record 0x${node.id.toString(16)} has an empty payload`);
      node.byte13 = node.payload[0];
      if (nextPointer <= pointer)
        throw new RangeError(
          `leaf record 0x${node.id.toString(16)} does not advance`);
      nodes.push(node);
      pointer = nextPointer;
    }
    if (pointer !== leafBoundary)
      throw new RangeError('MathPrint leaf walk missed its boundary');

    const byPointer = new Map();
    for (const node of nodes) {
      if (byPointer.has(node.pointer))
        throw new RangeError('MathPrint graph contains duplicate record pointers');
      byPointer.set(node.pointer,node);
    }
    const entry = byPointer.get(entryPointer);
    if (!entry)
      throw new RangeError('MathPrint entry pointer is not a record boundary');
    const expression = decodeSettledExpressionGraph(nodes,entry.id);
    let editor = null;
    if (gapActive) {
      if (!activeNode)
        throw new RangeError('MathPrint active gap record was not visited');
      const decoded = decodeEditorExpressionGraph(
        nodes,entry.id,activeNode.id,left.length);
      editor = {
        expression:decoded.expression,
        cursor:{
          ...decoded.cursor, recordPointer:activeNode.pointer,
          left:left.slice(), right:right.slice(),
        },
      };
    }
    return {
      structuralStart, editorBoundary, entryPointer, mainTail,
      gapRecordPointer, leafBoundary, gapActive,
      editTop, editCursor, editTail, editBottom,
      entryId:entry.id, nodes, expression, editor,
      routine:'34:4A83/4AAF and 34:4ACE/4AF0',
    };
  }

  function constructSettledProgramFromTokens(input, firstId = 1, font = null) {
    const native = settledNativeTokenUnits(input);
    const spec = settledExpressionFromTokens(native.bytes);
    const program = constructSettledExpressionProgram(spec, firstId, font);
    program.native_tokens = native.bytes.slice();
    program.native_units = native.units.map(unit => ({
      offset:unit.offset, length:unit.length, prefix:unit.prefix,
      token:unit.token, packed:unit.packed,
    }));
    program.source =
      '34:5678, 34:58F9, 34:5911, 34:5AA3, 34:5935, 34:4900, 34:7393, and 34:7609 translated native-token construction';
    return program;
  }

  // 34:4900 allocates records as the token pass encounters each structural
  // object. 34:5935 maps the source tokens to render types, and 34:7393/7609
  // fill the record metrics. A leaf can therefore interleave ordinary tokens
  // with embedded structural IDs. This builder retains that allocation and
  // payload order so different translated object types can compose.
  function constructExpressionProgram(spec, firstId = 1, font = null,
                                      editorState = null) {
    if (!Number.isInteger(firstId) || firstId < 1 || firstId > 0xffff)
      throw new RangeError('settled first record ID must be an unsigned word');
    const editorMode = editorState !== null;
    const editorCursorCount = expression => {
      if (!expression || typeof expression !== 'object') return 0;
      if (expression.kind === 'editorCursor') return 1;
      if (expression.kind === 'tokens') return 0;
      let count = 0;
      for (const value of Object.values(expression)) {
        if (Array.isArray(value)) {
          for (const item of value) count += editorCursorCount(item);
        } else if (value && typeof value === 'object') {
          count += editorCursorCount(value);
        }
      }
      return count;
    };
    const cursorCount = editorCursorCount(spec);
    if (editorMode && cursorCount !== 1)
      throw new RangeError(
        `editor expression must contain one cursor, found ${cursorCount}`);
    if (!editorMode && cursorCount)
      throw new RangeError('settled expression must not contain an editor cursor');
    const editorChildSelector = (expression, children, fallback) => {
      if (!editorMode) return fallback;
      const selected = [];
      for (let index = 0; index < children.length; index++)
        if (editorCursorCount(children[index])) selected.push(index + 1);
      if (selected.length > 1)
        throw new RangeError(
          `${expression.kind} contains an editor cursor in multiple children`);
      // A completed template retains its last child as the editor selector.
      // An ancestor of the active leaf instead names the selected child.
      return selected.length ? selected[0] : children.length;
    };
    const nodes = [];
    const retainedStructuralByte13 = new Set();
    // A type-2Ah record is allocated after its base has been prepared, but the
    // base's trailing structural record is updated only after the exponent
    // metrics establish the power baseline. Keep that construction-only
    // relationship outside the serialized record graph.
    const powerBaseStructures = new Map();
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
    const editorRecordByte13 = (expression, fallback, recordId) => {
      if (!editorMode || expression.editor_record_byte13 === undefined)
        return fallback;
      retainedStructuralByte13.add(recordId);
      return byte(expression.editor_record_byte13,
        `${expression.kind} retained record +13h byte`);
    };
    const embedded = (renderType, recordId) =>
      [0xef, renderType, recordId & 0xff, recordId >> 8, 0xef, 0x2d];
    const leadingByte = expression => {
      if (expression.kind === 'tokens') return expression.tokens[0];
      if (expression.kind === 'sequence') {
        const first = expression.parts.find(
          part => part.kind !== 'editorCursor');
        if (!first)
          throw new RangeError('editor cursor has no following expression byte');
        return leadingByte(first);
      }
      if (expression.kind === 'group') return 0x10;
      if (expression.kind === 'list') return 0x08;
      if (expression.kind === 'power') return leadingByte(expression.base);
      if (expression.kind === 'absolute') return 0xef;
      if (expression.kind === 'ePower') return 0xef;
      if (expression.kind === 'tenPower') return 0xef;
      if (expression.kind === 'logBase') return 0xef;
      if (expression.kind === 'matrix') return 0xef;
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
      const embeddedStructures = [];

      const mergeVerticalMetrics = (height, baseline) => {
        const mergedBaseline = Math.max(leaf.word09, baseline);
        const lowerExtent = Math.max(
          leaf.word05 - leaf.word09, height - baseline);
        leaf.word05 = checkedWord(
          mergedBaseline + lowerExtent, 'settled leaf height');
        leaf.word09 = mergedBaseline;
      };

      const addTokens = tokens => {
        const metrics = settledLeafMetrics(tokens, renderDepth, font);
        mergeVerticalMetrics(metrics.height, metrics.baseline);
        leaf.word07 = checkedWord(
          leaf.word07 + metrics.width, 'settled leaf width');
        leaf.payload.push(...metrics.payload);
      };
      const addStructural = structural => {
        structural.word03 = leaf.record_id;
        // The metric pass records the object's horizontal anchor in the
        // containing leaf before appending its six-byte embedded marker.
        structural.word0D = leaf.word07;
        // The type-2Ah metric pass records the exponent's horizontal anchor at
        // +0Dh when the object is appended. It is the containing leaf's width
        // before the power object, including a grouped or structural base.
        if (structural.render_type === 0x2a) {
          const ordinaryBaseline = renderDepth === 0 ? 3 : 2;
          const baseStructural = powerBaseStructures.get(structural.record_id);
          // 34:70C1 merges the immediate base, not the containing leaf's
          // accumulated axis. An earlier radical or fraction to the left must
          // not raise a later plain-token power.
          const baseBaseline = baseStructural
            ? baseStructural.word0B : ordinaryBaseline;
          const baseBaselineDelta = Math.max(
            0, baseBaseline - ordinaryBaseline);
          const powerLowerExtent = structural.word07 - structural.word0B;
          // The accumulator may already contain unrelated objects to the
          // left. Only the immediate base participates in 34:70C1's lower
          // extent merge. A plain-token base has the same four-row lower
          // extent as the initial power metrics.
          const baseLowerExtent = baseStructural
            ? baseStructural.word07 - baseStructural.word0B
            : powerLowerExtent;
          structural.word07 = checkedWord(
            structural.word07 + baseBaselineDelta, 'power height after base');
          structural.word0B = checkedWord(
            structural.word0B + baseBaselineDelta, 'power baseline after base');
          // 34:70C1–7084 retains the base's lower extent after moving the
          // exponent baseline. This is observable when a fraction, whose
          // denominator extends farther below the axis, is the power base.
          structural.word07 = checkedWord(
            structural.word07 + Math.max(
              0, baseLowerExtent - powerLowerExtent),
            'power height after lower base extent');
        }
        mergeVerticalMetrics(structural.word07, structural.word0B);
        leaf.word07 = checkedWord(
          leaf.word07 + structural.word09, 'settled structural leaf width');
        leaf.payload.push(...embedded(structural.render_type, structural.record_id));
        embeddedStructures.push(structural);
      };

      const addEditorCursor = (cursor, beforeEmptySlot) => {
        if (!editorMode)
          throw new RangeError('settled leaf contains an editor cursor');
        if (editorState.activeLeafId !== null)
          throw new RangeError('editor expression contains multiple active leaves');
        const byteOffset = leaf.payload.length;
        if (cursor.record_id !== undefined && cursor.record_id !== leaf.record_id)
          throw new RangeError(
            `editor cursor record ID 0x${cursor.record_id.toString(16)} ` +
            `does not match constructed leaf 0x${leaf.record_id.toString(16)}`);
        if (cursor.byte_offset !== undefined && cursor.byte_offset !== byteOffset)
          throw new RangeError(
            `editor cursor byte ${cursor.byte_offset} does not match ` +
            `constructed byte ${byteOffset}`);
        const height = renderDepth === 0 ? 7 : 5;
        const baseline = renderDepth === 0 ? 3 : 2;
        const width = beforeEmptySlot ? 0 : renderDepth === 0 ? 6 : 5;
        if (!beforeEmptySlot) {
          mergeVerticalMetrics(height,baseline);
          leaf.word07 = checkedWord(
            leaf.word07 + width, 'editor cursor leaf width');
        }
        leaf.editor_cursor_offset = byteOffset;
        leaf.editor_cursor_width = width;
        leaf.editor_cursor_height = height;
        leaf.editor_cursor_baseline = baseline;
        leaf.editor_cursor_uses_empty_slot = beforeEmptySlot;
        leaf.editor_cursor_record_word0F = cursor.record_word0F;
        leaf.editor_cursor_record_word11 = cursor.record_word11;
        editorState.activeLeafId = leaf.record_id;
        editorState.byteOffset = byteOffset;
        editorState.width = width;
        editorState.height = height;
        editorState.baseline = baseline;
        editorState.usesEmptySlot = beforeEmptySlot;
      };

      const beginsWithEmptySlot = part => {
        if (!part || typeof part !== 'object') return false;
        if (part.kind === 'tokens')
          return part.tokens.length === 2 &&
            part.tokens[0] === 0xef && part.tokens[1] === 0x1e;
        return part.kind === 'sequence' && part.parts.length &&
          beginsWithEmptySlot(part.parts[0]);
      };

      const addPart = (part, nextPart = null) => {
        if (part.kind === 'tokens') {
          addTokens(part.tokens);
          return;
        }
        if (part.kind === 'sequence') {
          for (let index = 0; index < part.parts.length; index++)
            addPart(part.parts[index],part.parts[index + 1] || nextPart);
          return;
        }
        if (part.kind === 'embedded') {
          addStructural(part.structural);
          return;
        }
        if (part.kind === 'editorCursor') {
          addEditorCursor(part,beginsWithEmptySlot(nextPart));
          return;
        }
        throw new RangeError(`unsupported settled expression part ${part.kind}`);
      };

      addPart(prepared);
      // 34:77AD–77C1 revisits every structural marker in the completed leaf.
      // It stores the difference between the leaf's merged baseline at 850Ah
      // and the embedded record's +0Bh baseline in that record's +0Fh word.
      // This applies to every direct structural child, not only to a structure
      // immediately used as a power base.
      for (const structural of embeddedStructures)
        structural.word0F = checkedWord(
          leaf.word09 - structural.word0B,
          'embedded structural baseline delta');
      finishLeaf(leaf);
      if (editorMode && leaf.payload.length === 2 &&
          leaf.payload[0] === 0xef && leaf.payload[1] === 0x1e)
        leaf.word0F = 0;
      if (leaf.editor_cursor_offset !== undefined) {
        if (leaf.editor_cursor_record_word0F !== undefined)
          leaf.word0F = leaf.editor_cursor_record_word0F;
        if (leaf.editor_cursor_record_word11 !== undefined)
          leaf.word11 = leaf.editor_cursor_record_word11;
      }
      return leaf;
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
      if (expression.kind === 'editorCursor') return expression;
      if (expression.kind === 'tokens') return {
        ...expression, fractionByte13:expression.tokens[0],
      };
      if (expression.kind === 'sequence') {
        const firstPayloadIndex = expression.parts.findIndex(
          part => part.kind !== 'editorCursor');
        const parts = expression.parts.map((part, index) =>
          prepare(part, renderDepth, structuralDepth,
                  fractionNumerator && index === firstPayloadIndex));
        const leading = parts.find(part => part.fractionByte13 !== undefined);
        return {
          kind:'sequence', parts,
          fractionByte13:leading ? leading.fractionByte13 : undefined,
        };
      }
      if (expression.kind === 'group') {
        const body = prepare(
          expression.expression, renderDepth, structuralDepth,
          fractionNumerator);
        return {
          kind:'sequence',
          parts:[{kind:'tokens',tokens:[0x10]}, body,
                 {kind:'tokens',tokens:[0x11]}],
          fractionByte13:0x10,
        };
      }
      if (expression.kind === 'list') {
        const parts = [{kind:'tokens',tokens:[0x08]}];
        for (let index = 0; index < expression.elements.length; index++) {
          if (index) parts.push({kind:'tokens',tokens:[0x2b]});
          parts.push(prepare(
            expression.elements[index], renderDepth, structuralDepth,
            fractionNumerator && index === 0));
        }
        parts.push({kind:'tokens',tokens:[0x09]});
        return {kind:'sequence',parts,fractionByte13:0x08};
      }
      if (expression.kind === 'power') {
        // The base belongs to the containing leaf. Prepare it before allocating
        // the exponent record so structural bases retain encounter order.
        const base = prepare(
          expression.base, renderDepth, structuralDepth, fractionNumerator);
        const trailingStructural = part => {
          if (part.kind === 'embedded') return part.structural;
          if (part.kind !== 'sequence' || !part.parts.length) return null;
          for (let index = part.parts.length - 1; index >= 0; index--) {
            const child = part.parts[index];
            // A grouped base ends with one or more ordinary 11h close tokens.
            // 34:70C1 measures the expression inside those closes, so continue
            // backward to its trailing structural record. Other trailing tokens
            // make the immediate base ordinary and stop the search.
            if (child.kind === 'tokens' && child.tokens.length &&
                child.tokens.every(token => token === 0x11))
              continue;
            return trailingStructural(child);
          }
          return null;
        };
        const baseStructural = trailingStructural(base);
        const renderType = settledStructuralTokenType(0x00, 0xf0);
        if (renderType !== 0x2a)
          throw new Error('34:594D power token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[1],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0,structuralId),
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
        structural.child_ids = [child.record_id];
        if (baseStructural)
          powerBaseStructures.set(structural.record_id, baseStructural);
        return {
          kind:'sequence',
          parts:[base,{kind:'embedded',structural}],
          fractionByte13:0x10,
        };
      }
      if (expression.kind === 'absolute') {
        const renderType = settledStructuralTokenType(0x00, 0xb2);
        if (renderType !== 0x21)
          throw new Error('34:594D absolute token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:settledRecordMetadata(renderType)[1],
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0,structuralId),
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const child = build(
          expression.body, renderDepth, structuralId, structuralDepth + 1);
        child.word0B = 6;
        child.word0D = 0;
        structural.word07 = child.word05;
        structural.word09 = checkedWord(child.word07 + 12, 'absolute width');
        structural.word0B = child.word09;
        structural.child_ids = [child.record_id];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
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
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0,structuralId),
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
        // 34:73DB seeds the raised metric path with six rows. The recursive
        // child metric can increase that baseline, while the outer large-row
        // path retains the exponent height used by the existing reset-origin
        // exponential oracles.
        structural.word0B = Math.max(
          exponent.word05, renderDepth === 0 ? 0 : 6);
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
        const metadata = settledRecordMetadata(renderType);
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          // Native-source construction visits child 2 and then child 1, as
          // encoded by the 34:59AC row [04,02,01,00,00], and therefore leaves
          // the active-child selector at 1. Template-key navigation can leave
          // the same completed record at 2; that editor state is not a metric
          // and is not derived from structural depth.
          word05:editorChildSelector(
            expression,[expression.base,expression.argument],metadata[2]),
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0,structuralId),
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
        // The type-28h handler uses the large-row offsets 18/24 at depth zero
        // and the small-row offsets 11/17 below a raised renderer. The two
        // pairs differ by seven while retaining the six-pixel closing margin.
        const raisedLogBase = renderDepth !== 0;
        base.word0B = raisedLogBase ? 11 : 18;
        // 34:76A9–76BF obtains child 2's baseline, decrements the structural
        // depth through 34:79C9, and selects an offset of four only when that
        // depth reaches zero. Deeper log-base records use an offset of three;
        // the final three subtracts leave +1 at depth one and +0 below it.
        base.word0D = checkedWord(
          argument.word09 + (structuralDepth === 0 ? 1 : 0),
          'log-base base y');
        argument.word0B = checkedWord(
          base.word07 + (raisedLogBase ? 17 : 24),
          'log-base argument x');
        argument.word0D = 0;
        // The metric pass reserves one row between the argument baseline and
        // the base only at large-font depth. A raised type-28h record uses the
        // small-row union without that extra row.
        structural.word07 = checkedWord(Math.max(
          argument.word05,
          argument.word09 + (raisedLogBase ? 0 : 1) + base.word05),
          'log-base height');
        structural.word09 = checkedWord(
          argument.word0B + argument.word07 + 6, 'log-base width');
        structural.word0B = argument.word09;
        structural.child_ids = [base.record_id, argument.record_id];
        return {
          kind:'embedded', structural,
          fractionByte13:fractionNumerator ? 0x10 : 0xef,
        };
      }
      if (expression.kind === 'matrix') {
        const renderType = settledStructuralTokenType(0xef, 0x2b);
        if (renderType !== 0x2b)
          throw new Error('34:594D matrix token mapping is inconsistent');
        const structuralId = allocate();
        const structural = {
          record_id:structuralId, render_type:renderType, word03:0,
          word05:editorChildSelector(
            expression,expression.elements,
            expression.rows * expression.columns),
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:(expression.columns << 8) | (structuralDepth + 1),
          byte13:editorRecordByte13(
            expression,expression.rows,structuralId),
          child_ids:[], payload:[],
        };
        nodes.push(structural);

        const elements = [];
        for (let index = 0; index < expression.elements.length; index++) {
          // The matrix pass reserves the first element leaf, then one internal
          // ID, before it scans that leaf for nested structural records. The
          // reserved ID is absent from the settled render graph.
          const element = newLeaf(structuralId);
          if (index === 0 && expression.elements.length > 1) allocate();
          fillLeaf(element, prepare(
            expression.elements[index], renderDepth, structuralDepth + 1),
          renderDepth);
          elements.push(element);
        }
        const columnWidths = Array.from({length:expression.columns}, () => 0);
        const rowBaselines = Array.from({length:expression.rows}, () => 0);
        const rowDescents = Array.from({length:expression.rows}, () => 0);
        for (let row = 0; row < expression.rows; row++)
          for (let column = 0; column < expression.columns; column++) {
            const element = elements[row * expression.columns + column];
            columnWidths[column] = Math.max(columnWidths[column], element.word07);
            rowBaselines[row] = Math.max(rowBaselines[row], element.word09);
            rowDescents[row] = Math.max(
              rowDescents[row], element.word05 - element.word09);
          }
        const rowHeights = rowBaselines.map(
          (baseline, row) => baseline + rowDescents[row]);
        const columnStarts = [];
        let x = 6;
        for (const width of columnWidths) {
          columnStarts.push(x);
          x = checkedWord(x + width + 6, 'matrix column extent');
        }
        const rowStarts = [];
        let y = 0;
        for (const height of rowHeights) {
          rowStarts.push(y);
          y = checkedWord(y + height + 2, 'matrix row extent');
        }
        for (let row = 0; row < expression.rows; row++)
          for (let column = 0; column < expression.columns; column++) {
            const element = elements[row * expression.columns + column];
            element.word0B = checkedWord(
              columnStarts[column] +
              Math.floor((columnWidths[column] - element.word07) / 2),
              'matrix element x');
            element.word0D = checkedWord(
              rowStarts[row] + rowBaselines[row] - element.word09,
              'matrix element y');
          }
        structural.word07 = checkedWord(y - 2, 'matrix height');
        structural.word09 = checkedWord(x, 'matrix width');
        structural.word0B = Math.floor(structural.word07 / 2);
        structural.child_ids = elements.map(element => element.record_id);
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
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0,structuralId),
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
          word05:editorChildSelector(
            expression,[expression.index,expression.radicand],
            settledRecordMetadata(renderType)[2]),
          word07:0, word09:0, word0B:0, word0D:0,
          word0F:0, word11:structuralDepth + 1,
          byte13:editorRecordByte13(expression,
            fractionNumerator ? 0x10
              : structuralDepth === 0 ? leadingByte(expression.index) : 0,
            structuralId),
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
          word05:editorChildSelector(
            expression,[expression.numerator,expression.denominator],
            settledRecordMetadata(renderType)[0]),
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(expression,
            fractionNumerator ? 0x10
              : structuralDepth === 0 ? numeratorPrepared.fractionByte13 : 0,
            structuralId),
          child_ids:[], payload:[],
        };
        nodes.push(structural);
        const numerator = materializeLeaf(
          numeratorPrepared, renderDepth + 1, structuralId);
        if (!editorMode) numerator.word0F = 0;
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
          word05:editorChildSelector(expression,[
            expression.lower,expression.upper,expression.body,
            expression.variable,
          ],settledRecordMetadata(renderType)[4]),
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0xef,structuralId),
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
          word05:editorChildSelector(expression,[
            expression.variable,expression.body,expression.value,
          ],settledRecordMetadata(renderType)[3]),
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0xef,structuralId),
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
        // 34:76C2–76EF places child 2 on the record baseline, child 1 two
        // rows below it, and child 3 so its own baseline lands four rows below
        // it. Include all three positioned extents; the old baseline+7 shortcut
        // omitted a tall evaluation-value structure.
        const baseline = Math.max(6, body.word09, value.word09 - 4);
        const bodyY = baseline - body.word09;
        const variableY = baseline + 2;
        const valueY = baseline + 4 - value.word09;
        const height = Math.max(
          bodyY + body.word05,
          variableY + variable.word05,
          valueY + value.word05);
        variable.word0B = 5;
        variable.word0D = checkedWord(variableY, 'nDeriv variable y');
        body.word0B = 16;
        body.word0D = checkedWord(bodyY, 'nDeriv body y');
        value.word0B = checkedWord(
          body.word07 + variable.word07 + 29, 'nDeriv value x');
        value.word0D = checkedWord(valueY, 'nDeriv evaluation-value y');
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
          word05:editorChildSelector(expression,[
            expression.variable,expression.lower,expression.upper,
            expression.body,
          ],3),
          word07:0, word09:0, word0B:0, word0D:0, word0F:0,
          word11:structuralDepth + 1,
          byte13:editorRecordByte13(
            expression,fractionNumerator ? 0x10 : 0xef,structuralId),
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
        // 34:74AA and 34:76F1 keep the sigma rows and the body in separate
        // horizontal regions. A tall body can therefore overlap the upper or
        // lower row vertically without increasing the space reserved for that
        // row. The record height is the union of those independently placed
        // regions.
        const nominalBaseline = upperSpace + 4;
        const baseline = Math.max(nominalBaseline, body.word09);
        const bodyY = baseline - body.word09;
        const nominalHeight = upperSpace + 9 + lowerSpace;
        const lowerRowY = baseline + 5;
        const height = checkedWord(Math.max(
          nominalHeight,
          lowerRowY + lowerSpace,
          bodyY + body.word05), 'summation height');
        const bodyX = checkedWord(operatorWidth + 6, 'summation body x');
        variable.word0B = 0;
        variable.word0D = checkedWord(lowerRowY, 'summation variable y');
        lower.word0B = checkedWord(
          variable.word07 + 4, 'summation lower-bound x');
        lower.word0D = checkedWord(lowerRowY, 'summation lower-bound y');
        upper.word0B = checkedWord(
          Math.floor((operatorWidth - upper.word07) / 2),
          'summation upper-bound x');
        upper.word0D = checkedWord(
          baseline - nominalBaseline, 'summation upper-bound y');
        body.word0B = bodyX;
        body.word0D = checkedWord(bodyY, 'summation body y');
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
      if (node.render_type >= 0x1f &&
          !retainedStructuralByte13.has(node.record_id) &&
          (node.byte13 === 0 || node.byte13 === undefined))
        node.byte13 = root.payload[0];
    const nodeMap = new Map(nodes.map(node => [node.record_id,node]));
    if (editorMode) {
      // While the gap sits inside a structural descendant, +0Fh in each
      // containing leaf points to that descendant's six-byte marker. Moving
      // back to the containing leaf finalizes the marker and advances +0Fh.
      // Follow the constructed parent chain instead of inferring this retained
      // state from the current gap payload.
      const cursorAncestors = new Set();
      let current = nodeMap.get(editorState.activeLeafId);
      while (current && !cursorAncestors.has(current.record_id)) {
        cursorAncestors.add(current.record_id);
        const parent = nodeMap.get(current.word03);
        if (!parent) break;
        if (current.render_type >= 0x1f && parent.render_type < 0x1f) {
          let markerOffset = -1;
          for (let index = 0; index + 5 < parent.payload.length; index++) {
            if (parent.payload[index] === 0xef &&
                parent.payload[index + 1] === current.render_type &&
                (parent.payload[index + 2] |
                 parent.payload[index + 3] << 8) === current.record_id &&
                parent.payload[index + 4] === 0xef &&
                parent.payload[index + 5] === 0x2d) {
              markerOffset = index;
              break;
            }
          }
          if (markerOffset < 0)
            throw new RangeError(
              `editor ancestor record 0x${current.record_id.toString(16)} ` +
              'has no containing marker');
          parent.word0F = markerOffset;
        }
        current = parent;
      }
    }
    const orderedNodes = [];
    const visited = new Set();
    const visit = recordId => {
      if (visited.has(recordId)) return;
      const node = nodeMap.get(recordId);
      if (!node) throw new Error(`constructed record 0x${recordId.toString(16)} is absent`);
      visited.add(recordId);
      orderedNodes.push(node);
      for (const childId of node.child_ids) visit(childId);
      // The payload interleaves native tokens with six-byte structural
      // markers. Advance across a complete marker or packed token so the EF
      // and type-looking bytes inside a little-endian record ID cannot become
      // a second, false marker.
      for (let index = 0; index < node.payload.length;) {
        if (node.payload[index] === 0xef && index + 1 < node.payload.length &&
            0x1f <= node.payload[index + 1] && node.payload[index + 1] <= 0x2b) {
          if (index + 5 >= node.payload.length ||
              node.payload[index + 4] !== 0xef ||
              node.payload[index + 5] !== 0x2d)
            throw new RangeError(
              `constructed record 0x${node.record_id.toString(16)} has a truncated embedded marker`);
          visit(node.payload[index + 2] | node.payload[index + 3] << 8);
          index += 6;
          continue;
        }
        const token = settledReadPackedToken(node.payload, index);
        index = token.next;
      }
    };
    visit(root.record_id);
    const matrixResult = spec.kind === 'matrix';
    const wrapper = editorMode ? {
      record_id:firstId - 1, render_type:0x1f, word03:0, word05:1,
      word07:root.word05, word09:root.word07, word0B:root.word09,
      word0D:0, word0F:0, word11:0, byte13:0,
      child_ids:[root.record_id], payload:[],
    } : null;
    return {
      entry_id:root.record_id,
      ...(editorMode ? {
        wrapper_id:wrapper.record_id,
        editor:{
          active_record_id:editorState.activeLeafId,
          cursor_byte_offset:editorState.byteOffset,
          width:editorState.width,
          height:editorState.height,
          baseline:editorState.baseline,
          uses_empty_slot:editorState.usesEmptySlot,
        },
      } : {}),
      // The answer-display path places a matrix against the right edge and
      // begins its first row at LCD row 9. Scalar results enter at (0,0).
      origin:matrixResult ? {x:95 - root.word07,y:9} : {x:0,y:0},
      source:editorMode
        ? '34:4A83, 34:4AAF, 34:4ACE, 34:7393, and 34:7609 translated live-editor construction'
        : matrixResult
        ? '34:4900, 34:5935, 34:65AA, 34:7393, and 34:7609 translated matrix construction'
        : '34:4900, 34:5935, 34:7393, and 34:7609 translated compositional construction',
      nodes:editorMode ? [wrapper,...orderedNodes] : orderedNodes,
    };
  }

  function constructSettledExpressionProgram(input, firstId = 1, font = null) {
    return constructExpressionProgram(
      settledExpressionSpec(input),firstId,font);
  }

  function constructEditorExpressionProgram(input, firstId = 7, font = null) {
    if (!Number.isInteger(firstId) || firstId < 2 || firstId > 0xffff)
      throw new RangeError(
        'editor first leaf record ID must leave room for a wrapper ID');
    return constructExpressionProgram(
      settledExpressionSpec(input,'editor expression',new Set(),true),
      firstId,font,{
        activeLeafId:null, byteOffset:null, width:null,
        height:null, baseline:null, usesEmptySlot:null,
      });
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

  // Compatibility entry for the absolute-value constructor. Its body may
  // contain any expression kind accepted by the compositional builder.
  function constructSettledAbsoluteProgram(body, firstId = 1, font = null) {
    const program = constructSettledExpressionProgram(
      {kind:'absolute', body}, firstId, font);
    program.source =
      '34:4900, 34:5935, 34:7393, and 34:7609 translated absolute construction';
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
    const editorViewport = options.editorViewport;
    if (editorViewport !== undefined &&
        (!editorViewport || typeof editorViewport !== 'object' ||
         !Number.isInteger(editorViewport.xClip) || editorViewport.xClip < 0 ||
         editorViewport.xClip > 0xffff ||
         !Number.isInteger(editorViewport.xOrigin) || editorViewport.xOrigin < 0 ||
         editorViewport.xOrigin > 0xffff))
      throw new TypeError(
        'settled record editor viewport must contain unsigned xClip and xOrigin words');
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
      const cursorOffset = record.editor_cursor_offset;
      const cursorWidth = record.editor_cursor_width;
      const cursorHeight = record.editor_cursor_height;
      const cursorBaseline = record.editor_cursor_baseline;
      const hasEditorCursor = cursorOffset !== undefined;
      if (hasEditorCursor) {
        const boundaries = editorPayloadCursorBoundaries(record.payload);
        if (!boundaries.includes(cursorOffset))
          throw new RangeError(
            `record 0x${record.id.toString(16)} editor cursor bisects a native unit`);
        for (const [value,label] of [
          [cursorWidth,'width'],[cursorHeight,'height'],
          [cursorBaseline,'baseline'],
        ]) if (!Number.isInteger(value) || value < 0 || value > 0xffff)
          throw new RangeError(`editor cursor ${label} must fit an unsigned word`);
        if (cursorBaseline > cursorHeight)
          throw new RangeError('editor cursor baseline exceeds its height');
      }
      let cursorEmissions = 0;
      const emitEditorCursor = index => {
        if (!hasEditorCursor || cursorOffset !== index) return;
        cursorEmissions++;
        if (cursorEmissions > 1)
          throw new RangeError('editor cursor was emitted more than once');
        if (cursorWidth) {
          controls.emit({
            kind:'editor-cursor-cell', x:pen.x,
            y:record.word09 - cursorBaseline,
            width:cursorWidth, height:cursorHeight, baseline:cursorBaseline,
            visible:false,
            routine:'34:785E–7876 → 34:779F and 34:79A9',
          });
          pen.x += cursorWidth;
        }
      };
      const delimiterMetrics = new Map();
      const stack = [];
      const delimiterKey = (index, codeIndex = 0) => `${index}:${codeIndex}`;
      const mergeMetrics = (left, right) => {
        if (!left) return right;
        const baseline = Math.max(left.baseline, right.baseline);
        return {
          baseline,
          height:baseline + Math.max(
            left.height - left.baseline, right.height - right.baseline),
        };
      };
      const rangeMetrics = (start, end) => {
        let result = null;
        for (let cursor = start; cursor < end;) {
          if (hasEditorCursor && cursorOffset === cursor)
            result = mergeMetrics(result,{
              height:cursorHeight,baseline:cursorBaseline,
            });
          const token = record.payload[cursor];
          const grouped = delimiterMetrics.get(delimiterKey(cursor));
          if ((token === 0x10 || token === 0x08) && grouped) {
            result = mergeMetrics(result, grouped);
            cursor = grouped.close + 1;
            continue;
          }
          if (token === 0xef && cursor + 3 < end &&
              0x1f <= record.payload[cursor + 1] &&
              record.payload[cursor + 1] <= 0x2b) {
            const nested = controls.record(
              record.payload[cursor + 2] | record.payload[cursor + 3] << 8);
            result = mergeMetrics(result, {
              height:nested.word07, baseline:nested.word0B,
            });
            cursor += 4;
            continue;
          }
          if (token === 0xef && record.payload[cursor + 1] === 0x2d) {
            cursor += 2;
            continue;
          }
          result = mergeMetrics(result, controls.state.depth === 0
            ? {height:7,baseline:3} : {height:5,baseline:2});
          const resolved = settledTokenSpelling(record.payload, cursor);
          cursor += resolved ? resolved.length : 1;
        }
        if (hasEditorCursor && cursorOffset === end)
          result = mergeMetrics(result,{
            height:cursorHeight,baseline:cursorBaseline,
          });
        return result;
      };
      for (let cursor = 0; cursor < record.payload.length;) {
        if (record.payload[cursor] === 0xef && cursor + 1 < record.payload.length) {
          const subtype = record.payload[cursor + 1];
          if (subtype === 0x1e || subtype === 0x2d) {
            cursor += 2;
            continue;
          }
          if (0x1f <= subtype && subtype <= 0x2b) {
            cursor += 4;
            continue;
          }
        }
        const resolved = settledTokenSpelling(record.payload, cursor);
        const codes = resolved ? resolved.codes : [record.payload[cursor]];
        for (let codeIndex = 0; codeIndex < codes.length; codeIndex++) {
          const code = codes[codeIndex];
          const key = delimiterKey(cursor, codeIndex);
          if (code === 0x28 || code === 0x7b)
            stack.push({cursor,key,code,
              after:cursor + (resolved ? resolved.length : 1)});
          else if ((code === 0x29 || code === 0x7d) && stack.length &&
                   stack[stack.length - 1].code ===
                     (code === 0x29 ? 0x28 : 0x7b)) {
            const open = stack.pop();
            const metrics = rangeMetrics(open.after, cursor) ||
              (controls.state.depth === 0
                ? {height:7,baseline:3} : {height:5,baseline:2});
            const pair = {...metrics,open:open.cursor,close:cursor,
              kind:code === 0x29 ? 'parenthesis' : 'brace'};
            delimiterMetrics.set(open.key, pair);
            delimiterMetrics.set(key, pair);
          }
        }
        cursor += resolved ? resolved.length : 1;
      }

      const emitDisplayCode = (code, tokenBytes, codeIndex, payloadIndex) => {
        // 34:6873 applies after token detokenization. Parentheses embedded in
        // spellings and direct 10h/11h tokens use 34:5D28/5D15; list braces
        // 08h/09h use the separate 34:5E0F/5E14 draw path.
        if (code === 0x28 || code === 0x29 || code === 0x7b || code === 0x7d) {
          const mode = code === 0x28 || code === 0x7b ? 'open' : 'close';
          const metrics = delimiterMetrics.get(
            delimiterKey(payloadIndex, codeIndex)) ||
            (controls.state.depth === 0
              ? {height:7,baseline:3} : {height:5,baseline:2});
          const operations = code === 0x7b || code === 0x7d
            ? settledBraceOperations(
              mode, pen.x, record.word09 - metrics.baseline,
              metrics.height, metrics.baseline)
            : settledCompoundOperations(
              mode, pen.x, record.word09 - metrics.baseline,
              metrics.height);
          for (const operation of operations) controls.emit(operation);
          pen.x += 6;
          return;
        }
        controls.emit({kind:'glyph', code, x:pen.x, y:pen.y,
          tokenBytes, routine:'34:660A–6704 → 34:6C37'});
        pen.x += fontAdvance(controls.state.depth, code);
      };

      for (let index = 0; index < record.payload.length;) {
        emitEditorCursor(index);
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
            const logicalEndpoint = (
              context.origin.x + pen.x + nested.word09 +
              (editorViewport === undefined ? 0 : editorViewport.xOrigin)
            ) & 0xffff;
            const drawEmbedded = editorViewport === undefined ||
              settledEmbeddedViewportDecision(
                logicalEndpoint,editorViewport.xClip).action === 'draw';
            if (drawEmbedded) {
              const savedDepth = controls.state.depth;
              controls.state.depth = savedDepth + 1;
              controls.visit(id, {
                x:context.origin.x + pen.x,
                y:context.origin.y + pen.y -
                  (nested.word0B - (savedDepth === 0 ? 3 : 2)),
              });
              controls.state.depth = savedDepth;
            }
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

        // The direct parenthesis tokens also resolve to display codes 28h/29h.
        if (token === 0x10 || token === 0x11) {
          emitDisplayCode(token === 0x10 ? 0x28 : 0x29, [token], 0, index);
          index++;
          continue;
        }

        const resolved = (options.resolveToken
          ? options.resolveToken(record.payload, index, controls.state.depth)
          : null) || settledTokenSpelling(record.payload, index);
        if (resolved) {
          if (!Array.isArray(resolved.codes) || !Number.isInteger(resolved.length) || resolved.length < 1)
            throw new TypeError('resolveToken must return {codes, length}');
          for (let codeIndex = 0; codeIndex < resolved.codes.length; codeIndex++) {
            const rawCode = resolved.codes[codeIndex];
            const code = byte(rawCode, 'resolved settled glyph');
            emitDisplayCode(
              code, record.payload.slice(index, index + resolved.length),
              codeIndex, index);
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
      emitEditorCursor(record.payload.length);
      if (hasEditorCursor && cursorEmissions !== 1)
        throw new RangeError('editor cursor was not emitted at its byte boundary');
    };

    return executeSettledRecordGraph(inputs, entryId, {
      ...options, depth:initialDepth, renderLeaf,
    });
  }

  function settledOperationClip(operation) {
    if (operation.clip === undefined) return null;
    const clip = operation.clip;
    if (!clip || typeof clip !== 'object' ||
        !Number.isInteger(clip.left) ||
        !Number.isInteger(clip.rightExclusive) ||
        !Number.isInteger(clip.top) ||
        !Number.isInteger(clip.bottomExclusive) ||
        clip.rightExclusive < clip.left ||
        clip.bottomExclusive < clip.top)
      throw new RangeError(
        'settled operation clip must contain ordered integer bounds');
    return clip;
  }

  function settledOperationPixels(operation, font) {
    if (!operation || typeof operation !== 'object')
      throw new TypeError('settled operation must be an object');
    const clip = settledOperationClip(operation);
    const pixels = [];
    const point = (x, y) => {
      if (!Number.isInteger(x) || !Number.isInteger(y))
        throw new RangeError('settled pixel coordinate must be an integer');
      if (clip && (x < clip.left || x >= clip.rightExclusive ||
                   y < clip.top || y >= clip.bottomExclusive)) return;
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
    } else if (operation.kind === 'editor-cursor-cell') {
      if (operation.visible)
        throw new RangeError(
          'visible editor cursor rasterization requires a captured blink bitmap');
    } else if (!operation.kind.startsWith('unresolved-')) {
      throw new RangeError(`cannot rasterize settled operation kind ${operation.kind}`);
    }
    return clip ? pixels.filter(([x,y]) =>
      clip.left <= x && x < clip.rightExclusive &&
      clip.top <= y && y < clip.bottomExclusive) : pixels;
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

  const settledBytePixels = (before, after, byteColumn, row) => {
    const pixels = [];
    for (let bit = 0; bit < 8; bit++) {
      const mask = 1 << (7 - bit);
      const previous = (before & mask) ? 1 : 0;
      const value = (after & mask) ? 1 : 0;
      pixels.push({
        x:8 * byteColumn + bit,
        y:row,
        before:previous,
        value,
        changed:previous !== value,
      });
    }
    return pixels;
  };

  const settledStoreByte = (grid, byteColumn, row, value) => {
    for (let bit = 0; bit < 8; bit++)
      grid[row][8 * byteColumn + bit] = (value >> (7 - bit)) & 1;
  };

  // Replay accepted T6A04 data bytes into its 96x64 visible bitmap. The LCD
  // pointer names an eight-pixel byte column and a row; each accepted data
  // write replaces all eight pixels in that byte. Supplying count exposes the
  // pixel-level frame after any prefix of a draw stream.
  function replaySettledLcdWrites(writes, options = {}) {
    if (!Array.isArray(writes))
      throw new TypeError('settled LCD writes must be an array');
    const width = options.width === undefined ? 96 : options.width;
    const height = options.height === undefined ? 64 : options.height;
    const count = options.count === undefined ? writes.length : options.count;
    if (!Number.isInteger(width) || width < 1 || width % 8 ||
        !Number.isInteger(height) || height < 1)
      throw new RangeError(
        'settled LCD replay dimensions must be positive and byte-aligned');
    if (!Number.isInteger(count) || count < 0 || count > writes.length)
      throw new RangeError('settled LCD replay count is outside the write stream');
    const grid = options.initialGrid === undefined
      ? Array.from({length:height}, () => new Array(width).fill(0))
      : options.initialGrid.map(row => row.slice());
    if (grid.length !== height || grid.some(row => row.length !== width ||
        row.some(value => value !== 0 && value !== 1)))
      throw new RangeError(
        'settled LCD replay grid must match the dimensions and contain bits');
    for (let index = 0; index < count; index++) {
      const write = writes[index];
      if (!write || !Array.isArray(write.pointer) || write.pointer.length !== 2)
        throw new TypeError(`settled LCD write ${index} has no pointer`);
      const [byteColumn,row] = write.pointer;
      if (!Number.isInteger(byteColumn) || !Number.isInteger(row) ||
          byteColumn < 0 || byteColumn >= width / 8 || row < 0 || row >= height)
        throw new RangeError(`settled LCD write ${index} is outside the display`);
      settledStoreByte(grid, byteColumn, row,
        byte(write.value, `settled LCD write ${index} value`));
    }
    return grid;
  }

  // Expand each accepted LCD byte into the eight visible pixels it replaces.
  // This retains unchanged zero and one bits, which a mutation-only event list
  // omits even though the controller accepts and stores the complete byte.
  function traceSettledLcdWrites(writes, options = {}) {
    if (!Array.isArray(writes))
      throw new TypeError('settled LCD writes must be an array');
    const width = options.width === undefined ? 96 : options.width;
    const height = options.height === undefined ? 64 : options.height;
    if (!Number.isInteger(width) || width < 1 || width % 8 ||
        !Number.isInteger(height) || height < 1)
      throw new RangeError(
        'settled LCD trace dimensions must be positive and byte-aligned');
    const grid = options.initialGrid === undefined
      ? Array.from({length:height}, () => new Array(width).fill(0))
      : options.initialGrid.map(row => row.slice());
    if (grid.length !== height || grid.some(row => row.length !== width ||
        row.some(value => value !== 0 && value !== 1)))
      throw new RangeError(
        'settled LCD trace grid must match the dimensions and contain bits');
    const events = writes.map((write, index) => {
      if (!write || !Array.isArray(write.pointer) || write.pointer.length !== 2)
        throw new TypeError(`settled LCD write ${index} has no pointer`);
      const [byteColumn,row] = write.pointer;
      if (!Number.isInteger(byteColumn) || !Number.isInteger(row) ||
          byteColumn < 0 || byteColumn >= width / 8 || row < 0 || row >= height)
        throw new RangeError(`settled LCD write ${index} is outside the display`);
      const value = byte(write.value, `settled LCD write ${index} value`);
      const beforeValue = settledGridByte(grid, byteColumn, row);
      const pixels = settledBytePixels(beforeValue, value, byteColumn, row);
      settledStoreByte(grid, byteColumn, row, value);
      return {
        ...write,
        beforeValue,
        value,
        pixels,
        changes:pixels.filter(pixel => pixel.changed)
          .map(pixel => [pixel.x,pixel.y,pixel.value]),
      };
    });
    return {width,height,events,grid};
  }

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
    const clip = settledOperationClip(operation);
    const writes = [];
    const write = (byteColumn, row, value, retainUnchanged = false) => {
      if (byteColumn < 0 || row < 0 || byteColumn >= width / 8 || row >= height) return;
      const before = settledGridByte(grid, byteColumn, row);
      value &= 0xff;
      if (!retainUnchanged && before === value) return;
      const pixels = settledBytePixels(before, value, byteColumn, row);
      const changes = pixels.filter(pixel => pixel.changed)
        .map(pixel => [pixel.x,pixel.y,pixel.value]);
      settledStoreByte(grid, byteColumn, row, value);
      writes.push({pointer:[byteColumn,row],beforeValue:before,value,pixels,changes});
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
        if (clip && (y < clip.top || y >= clip.bottomExclusive)) continue;
        if (y < 0 || y >= height) continue;
        const firstByte = Math.floor(blit.x / 8);
        const lastByte = Math.floor((blit.x + blit.width - 1) / 8);
        for (let byteColumn = lastByte; byteColumn >= firstByte; byteColumn--) {
          if (byteColumn < 0 || byteColumn >= width / 8) continue;
          let coverage = 0, ink = 0;
          for (let column = 0; column < blit.width; column++) {
            const x = blit.x + column;
            if (clip && (x < clip.left || x >= clip.rightExclusive)) continue;
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
    unsignedWord(firstWidth, 'settled fraction first-child width');
    unsignedWord(secondWidth, 'settled fraction second-child width');
    unsignedWord(y, 'settled fraction rule y');
    const x2 = addWord(Math.max(firstWidth, secondWidth), 1);
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
    unsignedWord(width, 'settled absolute width');
    unsignedWord(height, 'settled absolute height');
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
    unsignedWord(indexWidth, 'settled nth-root index width');
    unsignedWord(radicandWidth, 'settled nth-root radicand width');
    unsignedWord(height, 'settled nth-root height');
    byte(depth, 'settled nth-root depth');
    if (indexWidth < 1)
      throw new RangeError('settled nth-root index width must be positive');
    const fullRows = [0x04,0x04,0x04,0x04,0x14,0x0c,0x04];
    const rows = depth === 0 ? fullRows : fullRows.slice(2);
    if (height < rows.length)
      throw new RangeError('settled nth-root height cannot place its hook');
    const hookX = indexWidth - 1;
    const hookY = height - rows.length;
    const ruleEnd = addWord(radicandWidth, hookX + 3);
    return [
      {kind:'child', index:1, routine:'34:6315 → 34:636C'},
      {kind:'bitmap', x:hookX, y:hookY, width:5, height:rows.length,
       rows, retainUnchanged:true, viewportAdvance:5,
       routine:'34:6321 → 34:62D0 → 34:630C'},
      {kind:'line', axis:'vertical', from:{x:addWord(hookX,2),y:3},
       to:{x:addWord(hookX,2),y:hookY}, routine:'34:6331 → 34:5D96'},
      {kind:'child-select', index:2, routine:'34:6334 → 34:6CCA'},
      {kind:'line', axis:'horizontal', from:{x:addWord(hookX,2),y:2},
       to:{x:ruleEnd,y:2}, routine:'34:6344 → 34:5DA6'},
      {kind:'child', index:2, routine:'34:6344 → 34:62C3 → 34:62C6'},
    ];
  }

  // Render-record type 27h dispatches to 34:62A1. 34:62D0 emits the seven-row
  // root-hook bitmap first. The handler then draws its vertical stem, selects
  // child 1, reads that child's +7 width, emits the inclusive vinculum, and
  // finally enters the child renderer at 34:660A.
  function settledRadicalOperations(height, childWidth, depth = 0) {
    unsignedWord(height, 'settled radical height');
    unsignedWord(childWidth, 'settled radical child width');
    byte(depth, 'settled radical depth');
    const fullRows = [0x04,0x04,0x04,0x04,0x14,0x0c,0x04];
    const rows = depth === 0 ? fullRows : fullRows.slice(2);
    const hookY = height - rows.length;
    if (hookY < 0)
      throw new RangeError('settled radical height cannot place its hook');
    // 34:62D0 returns height minus the selected bitmap-row count in DE.
    // 34:62A7 then decrements DE before 34:62AE draws the stem.
    const stemEnd = Math.max(1, height - rows.length - 1);
    const ruleEnd = addWord(childWidth, 3);
    return [
      {kind:'bitmap', x:0, y:hookY, width:5, height:rows.length,
       rows,
       retainUnchanged:true, viewportAdvance:5,
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
    unsignedWord(height, 'settled integral height');
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
    editorTokenDispatch,
    editorArgumentClamp,
    editorRowFromArg,
    editorLayoutArgument,
    editorSubexpressionWindow,
    editorSubexpressionCell,
    editorDecodeAlphaVatRegion,
    editorDecodeAlphaVatSnapshot,
    editorFindAlphaVat,
    editorSavedOperandWrapper,
    editorAlphaSearch,
    editorForwardOverflowCue,
    editorReverseOverflowCue,
    editorAdvanceArgument,
    editorRetreatArgument,
    editorFirstArgumentAction,
    editorAdvanceAction,
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
    settledEditorViewport,
    settledEditorVerticalViewport,
    settledEditorViewport2D,
    settledGlyphViewportDecision,
    settledGlyphVerticalViewportDecision,
    settledEmbeddedViewportDecision,
    settledEditorHorizontalCuePlacement,
    settledEditorVerticalCueOperations,
    settledEditorViewportOperations,
    settledEditorRightCueDecision,
    settledEditorRightCueOperation,
    settledEditorRightCue,
    settledRunIndicatorTick,
    settledObjectHandler,
    settledStructuralTokenType,
    settledStructuralDepthGate,
    settledEf36SourcePath,
    settledRecordMetadata,
    settledRecordAllocationGeometry,
    settledRecordAllocationCapacity,
    settledRecordAllocationCheck,
    decodeSettledRecord,
    settledRenderHandler,
    settledCompoundOperations,
    settledBraceOperations,
    matrixChildCount,
    executeSettledRecordGraph,
    executeSettledRecordProgram,
    settledOperationPixels,
    settledOperationWrites,
    rasterizeSettledOperations,
    settledTokenGlyph,
    settledTokenSpelling,
    setSettledTokenStrings,
    settledReadPackedToken,
    settledReadPackedTokenBackward,
    settledNativeTokenUnits,
    settledParseAhead,
    settledParseAheadFunctionToken,
    settledStructuralArgumentScan,
    settledRaisedExtendedTokenClass,
    settledRaisedNameScan,
    settledRaisedOperandScan,
    settledFractionOperandScan,
    settledMatrixContainerScan,
    encodeSettledExpressionTokens,
    settledExpressionFromTokens,
    decodeSettledExpressionGraph,
    editorPayloadCursorBoundaries,
    editorInsertPackedToken,
    decodeEditorExpressionGraph,
    decodeMathPrintEditorRam,
    constructSettledProgramFromTokens,
    replaySettledLcdWrites,
    traceSettledLcdWrites,
    constructSettledAbsoluteProgram,
    constructEditorExpressionProgram,
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
