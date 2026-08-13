// MathPrint layout model — composes real TI-84 Plus ROM font glyphs into
// trace-fitted 2-D layouts inspired by the page-0x39 engine documented in
// docs/sub-equation-display.md. A "box" is { rows: number[][] (0/1),
// baseline: number } where baseline is the math-axis row index.
//
// Geometry inputs have different evidence scopes:
//   large glyph: 5 px wide, 7 rows, 1 px advance gap  (07:45FF)
//   exponent: bottom sits 2 px below base top (trace: base penY~11, exp penY~0)
//   selected horizontal spacing: 7 px (trace-fitted; separate from 39:683D)
//   descriptor axes: 39:683D maps 7*column to penY and rowHeight+2 to penX

let FONT = null;
let LAYOUT = null;
let DRAW_ORDER = { scenarios: {} };
let RECORD_PROGRAMS = { programs: {} };

const ROM_ENGINE = typeof MathPrintRomEngine !== 'undefined'
  ? MathPrintRomEngine
  : (typeof require !== 'undefined' ? require('./rom-engine.js') : null);

const GAP = 1;            // px between adjacent glyphs in a text run
const EXP_DROP = 2;       // px the exponent bottom sits below the base top (was raise=3)
const FRAC_PAD = 2;       // px the fraction bar overhangs the wider operand

// ---- box primitives -------------------------------------------------------

function blank(h, w) {
  return Array.from({ length: h }, () => new Array(w).fill(0));
}
function bw(box) { return box.rows.length ? box.rows[0].length : 0; }
function bh(box) { return box.rows.length; }

// Pen log: each glyph carries a mark {ch, x, y} at its top-left in box-local
// coordinates; composition shifts child marks so the final box holds the full
// model placement list. It is not a captured OS emission trace.
function shift(marks, dx, dy) {
  return (marks || []).map(m => ({ ...m, x: m.x + dx, y: m.y + dy }));
}
function glyphName(code) {
  if (code >= 0x20 && code <= 0x7e) return String.fromCharCode(code);
  return (FONT.names && FONT.names[code]) || ('0x' + code.toString(16));
}

function largeGlyph(code) {
  const rows = FONT.large.glyphs[code] || new Array(7).fill(0);
  const W = FONT.large.width;
  const grid = rows.map(r => Array.from({ length: W }, (_, i) => (r >> (W - 1 - i)) & 1));
  return { rows: grid, baseline: (grid.length >> 1),  // centre on the math axis
           recordWidth: W + 1,
           marks: [{ ch: glyphName(code), x: 0, y: 0, w: W, h: grid.length,
                     type: 'glyph', font: 'large', via: 'put_glyph_large 07:4588' }] };
}
function smallGlyph(code) {
  if (!FONT.small.glyphs[code]) return { rows: blank(7, 3), baseline: 3, marks: [] };
  const g = FONT.small.glyphs[code];
  const grid = g.rows.map(r => Array.from({ length: g.w }, (_, i) => (r >> (g.w - 1 - i)) & 1));
  return { rows: grid, baseline: (grid.length >> 1),
           recordWidth: g.w,
           marks: [{ ch: glyphName(code), x: 0, y: 0, w: g.w, h: grid.length,
                     type: 'glyph', font: 'small', via: '_VPutMap 01:6293' }] };
}

// Pen advance of a box: how far the pen moves after drawing it. Defaults to the
// bitmap width, but a box may advance LESS than its extent so following glyphs
// overhang it (the OS does this for superscripts — the exponent sits above-right
// of the next glyph rather than pushing it over). Like the OS pen pipeline.
function adv(box) { return box.adv != null ? box.adv : bw(box); }

// A record's +7 width includes the trailing structural edge that bitmap
// cropping omits. Preserve it separately from both ink width and pen advance.
function recordWidth(box) {
  return box.recordWidth != null ? box.recordWidth : adv(box) + 1;
}

// Horizontal layout, aligned on the math axis (baseline). Each box is drawn
// (OR'd) at its pen x; the pen moves by adv()+gap, so a low-adv box lets the
// next one overhang it at non-colliding rows.
function hcat(boxes, gap = GAP) {
  boxes = boxes.filter(b => b && bh(b) && bw(b));
  if (!boxes.length) return { rows: [], baseline: 0, marks: [], adv: 0 };
  const above = Math.max(...boxes.map(b => b.baseline));
  const below = Math.max(...boxes.map(b => bh(b) - b.baseline));
  const h = above + below;
  const xs = [];
  let pen = 0;
  boxes.forEach((b, k) => { if (k) pen += gap; xs.push(pen); pen += adv(b); });
  const W = Math.max(...boxes.map((b, k) => xs[k] + bw(b)));
  const out = blank(h, W);
  const marks = [];
  boxes.forEach((b, k) => {
    const top = above - b.baseline;
    for (let y = 0; y < bh(b); y++)
      for (let x = 0; x < bw(b); x++)
        if (b.rows[y][x]) out[top + y][xs[k] + x] = 1;
    marks.push(...shift(b.marks, xs[k], top));
  });
  const last = boxes[boxes.length - 1];
  const trailing = Math.max(0, recordWidth(last) - adv(last));
  return { rows: out, baseline: above, marks, adv: pen, recordWidth: pen + trailing };
}

function trim(box) {
  const nonblank = box.rows.map(r => r.some(Boolean));
  let top = nonblank.indexOf(true);
  if (top < 0) return { rows: [[0]], baseline: 0 };
  let bot = nonblank.lastIndexOf(true) + 1;
  const W = bw(box);
  const cols = [];
  for (let i = 0; i < W; i++) if (box.rows.slice(top, bot).some(r => r[i])) cols.push(i);
  const left = cols[0], right = cols[cols.length - 1] + 1;
  return {
    rows: box.rows.slice(top, bot).map(r => r.slice(left, right)),
    baseline: Math.max(0, box.baseline - top),
    marks: shift(box.marks, -left, -top),
    recordWidth: box.recordWidth,
  };
}

function clipMarks(box) {
  const W = bw(box), H = bh(box);
  const marks = (box.marks || []).flatMap(m => {
    const x0 = Math.max(0, m.x), y0 = Math.max(0, m.y);
    const x1 = Math.min(W, m.x + (m.w || 1));
    const y1 = Math.min(H, m.y + (m.h || 1));
    return x1 > x0 && y1 > y0
      ? [{ ...m, x: x0, y: y0, w: x1 - x0, h: y1 - y0 }]
      : [];
  });
  return { ...box, marks };
}

function center(rows, w) {
  return rows.map(r => {
    const pad = (w - r.length) >> 1;
    return new Array(pad).fill(0).concat(r, new Array(w - r.length - pad).fill(0));
  });
}

// ---- layout constructs ----------------------------------------------------
// Each composes child boxes into one box (fraction, exponent, radical, the big
// operators, nth root). Text helpers used here (text/smallText/glyphFor) are
// defined in the "text runs" section below and hoisted.

// Fraction: numerator over a full-width rule over the denominator.
// Bar row is the math axis (matches the OS centring a sibling glyph on the bar).
const FRAC_SIDE = 1;     // px of horizontal side-bearing the OS reserves around a
                         // fraction box. Trimmed away when a fraction stands alone
                         // (so 1//2 stays 5 px wide), but it shows as real spacing
                         // when the fraction abuts other glyphs — e.g. inside the
                         // integral body's delimiters the calc leaves a 3 px gap
                         // ( ( right edge x13, frac bar x17 ) = parens gap 2 + this 1.
function fraction(num, den) {
  const n = trim(num), d = trim(den);   // the OS stacks tight small-font digits
  const ruleY = bh(n) + 1;
  const operations = ROM_ENGINE
    ? ROM_ENGINE.settledFractionOperations(bw(n) + 1, bw(d) + 1, ruleY)
    : null;
  const rule = operations ? operations[2] : {
    from:{x:FRAC_SIDE,y:ruleY},
    to:{x:FRAC_SIDE + Math.max(bw(n), bw(d)) + FRAC_PAD - 1,y:ruleY},
    routine:'modeled fraction rule',
  };
  const inner = rule.to.x - rule.from.x + 1;
  const w = inner + 2 * FRAC_SIDE;      // bar width plus a side-bearing column each side
  const gap = [new Array(w).fill(0)];
  const bar = [new Array(w).fill(0)];
  for (let x = rule.from.x; x <= rule.to.x; x++) bar[0][x] = 1;
  // 1px gap above and below the rule, matching the calculator
  const rows = center(n.rows, w).concat(gap, bar, gap, center(d.rows, w));
  const nPad = (w - bw(n)) >> 1, dPad = (w - bw(d)) >> 1;
  const barMark = { ch: '─ bar', x: rule.from.x, y: ruleY, w: inner, h: 1, type: 'rule',
                    via: rule.routine, vars: 'child +7 widths; parent +0x0B y' };
  // 34:620A renders both children before tail-calling the rule wrapper.
  const marks = shift(n.marks, nPad, 0)
    .concat(shift(d.marks, dPad, bh(n) + 3), [barMark]);
  return { rows, baseline: bh(n) + 1, marks, kind: 'fraction' };   // math axis = the bar row
}

// Superscript: the exponent (small font, already trimmed) is anchored by its
// BOTTOM, sitting EXP_DROP px below the base's top, then extends upward. The OS
// places the base low and the raised content high (trace: base penY~11, exponent
// penY~0); a tall fraction exponent thus rises above the base instead of hanging
// into it. For a single small digit this reduces to the old fixed 3px raise.
// Trim blank rows (top/bottom) and trailing blank columns, but PRESERVE leading
// blank columns — so an exponent keeps its left side-bearing (e.g. the 2 px the
// OS reserves before a parenthesised group) while a trailing blank cell (the
// small font's baked-in advance) is still cropped so a following glyph abuts it.
function trimExp(box) {
  const nb = box.rows.map(r => r.some(Boolean));
  let top = nb.indexOf(true);
  if (top < 0) return { rows: [[0]], baseline: 0, marks: [] };
  const bot = nb.lastIndexOf(true) + 1;
  const W = bw(box);
  let right = 0;
  for (let x = 0; x < W; x++)
    if (box.rows.slice(top, bot).some(r => r[x])) right = x + 1;
  return {
    rows: box.rows.slice(top, bot).map(r => r.slice(0, right)),
    baseline: Math.max(0, box.baseline - top),
    marks: shift(box.marks, 0, -top),
    recordWidth: box.recordWidth,
  };
}

function superscript(base, exp) {
  const e = trimExp(exp);
  const bwid = bw(base), ewid = bw(e), eh = bh(e), bbh = bh(base);
  const baseTop = Math.max(eh - EXP_DROP, 0);
  const h = Math.max(baseTop + bbh, eh);
  // The exponent starts at the base's pen ADVANCE, not its bitmap width: a base with
  // a right side-bearing (a typed-paren group, adv = bw+1) carries that bearing into
  // the gap before the exponent (calc (2-3)^(N-N): the "N" exponent is one px further
  // right than over a bare-glyph base). gap = 1 + base right bearing.
  const gap = 1 + Math.max(0, adv(base) - bwid);
  const out = [];
  for (let r = 0; r < h; r++) {
    const left = (r >= baseTop && r < baseTop + bbh)
      ? base.rows[r - baseTop] : new Array(bwid).fill(0);
    const right = (r < eh) ? e.rows[r] : new Array(ewid).fill(0);
    out.push(left.concat(new Array(gap).fill(0), right));
  }
  const marks = shift(base.marks, 0, baseTop).concat(shift(e.marks, bwid + gap, 0));
  // A parenthesised exponent keeps a leading blank side-bearing (trimExp preserves
  // it); the OS mirrors it as a right bearing, so a glyph that follows the raised
  // group (the tall ")" closing an integrand around X^(1/2)) sits that far past the
  // exponent's last ink, not abutting it. Advance the pen by that bearing without
  // widening the bitmap, so a trailing context lands where the calc draws it.
  let lead = 0;
  while (lead < ewid && !e.rows.some(r => r[lead])) lead++;
  const sbox = { rows: out, baseline: baseTop + base.baseline, marks };
  return lead > 0 ? { ...sbox, adv: bw(sbox) + lead } : sbox;
}

// Stretch a fixed glyph's middle rows to a target height (tall ∫ and radicals).
function stretch(box, height, splitTop) {
  const rows = box.rows;
  if (!rows.length) return { rows: blank(Math.max(height, 1), 1), baseline: height >> 1 };
  if (height <= rows.length) return { rows, baseline: rows.length >> 1 };
  const at = Math.min(Math.max(splitTop, 0), rows.length - 1);
  const extra = height - rows.length;
  const fill = Array.from({ length: extra }, () => rows[at].slice());
  return { rows: rows.slice(0, at + 1).concat(fill, rows.slice(at + 1)),
           baseline: height >> 1 };
}

// Radical: ROM Lroot hook on the left, a vinculum bar across the radicand top.
function radical(radicand) {
  // trimExp (rows + trailing only) so a parenthesised radicand keeps its 1 px left
  // side-bearing — the calc draws sqrt((X)) with the "(" one px further from the
  // hook than a bare radicand; a bare radicand (no leading blank) is unaffected.
  const rad = trimExp(radicand);
  // The vinculum spans the radicand's pen ADVANCE, not just its ink. trimExp keeps
  // leading blanks (placed at the root) but trims trailing ones; the calc draws the
  // bar flush with the radicand's last CELL, which includes a baked-in trailing
  // blank (large "1" in sqrt(X^2+1)) or a delimiter's right bearing (the ")" in
  // sqrt((X)), adv > bw), but not for a flush glyph (large "3" in sqrt(3)). So
  // measure the radicand's advance past its leading bearing.
  // adv(radicand) is the radicand's full pen advance (bitmap width incl any baked-in
  // trailing blank, plus a delimiter's right bearing); the radicand is drawn at the
  // root with its leading blank intact (trimExp keeps it), so the bar runs from the
  // root across exactly that advance.
  const radvance = Math.max(bw(rad), adv(radicand));
  const childRecordWidth = recordWidth(radicand);
  const h = bh(rad) + 2;                       // vinculum + 1 px gap above radicand
  const root = stretch(trim(largeGlyph(0x10)), h, 3);
  // Short heuristic boxes do not carry the settled record height required by
  // the translated handler. Keep those arbitrary-expression previews on the
  // labeled compositor path instead of inventing a record metric.
  const operations = ROM_ENGINE && h >= 9
    ? ROM_ENGINE.settledRadicalOperations(h, childRecordWidth)
    : null;
  const rw = bw(root);
  const rule = operations ? operations[3] : {from:{x:rw,y:0}, to:{x:rw+radvance-1,y:0}};
  const w = Math.max(rw + radvance, rule.to.x + 1);
  const out = blank(h, w);
  for (let y = 0; y < bh(root); y++)
    for (let x = 0; x < rw; x++) if (root.rows[y][x]) out[h - bh(root) + y][x] = 1;
  for (let y = 0; y < bh(rad); y++)
    for (let x = 0; x < bw(rad); x++) if (rad.rows[y][x]) out[2 + y][rw + x] = 1;
  for (let x = rule.from.x; x <= rule.to.x; x++) out[0][x] = 1;
  const marks = [
    { ch: '√ Lroot', x: 0, y: h - bh(root), w: rw, h: bh(root), type: 'glyph',
      font: 'large', via: operations ? operations[0].routine : 'Lroot 07:466F (stretched)' },
    { ch: '√ stem', x: 2, y: 1, w: 1, h: Math.max(1, h - 1), type: 'rule',
      via: operations ? operations[1].routine : 'modeled radical stem' },
    { ch: '─ vinculum', x: rule.from.x, y: 0, w: rule.to.x-rule.from.x+1, h: 1, type: 'rule',
      via: operations ? operations[3].routine : 'graph-buffer rule' },
    ...shift(rad.marks, rw, 2),
  ];
  return { rows: out, baseline: (h >> 1) + 1, marks };
}

// Parentheses stretched to wrap a box (delimiter height follows content).
function parens(box) {
  // In a raised/subscript slot (exponent, integral/sum limit) the OS does NOT
  // stretch the delimiters: it draws ordinary small-font ( and ) glyphs inline
  // with the surrounding small run (trace X^(1/2): the exponent is the small
  // single-row run "(1/2)", parens 5 px tall like the digits, 1 px gap — not a
  // tall delimiter pair around a 2-D fraction). So in SMALL mode treat parens as
  // a plain glyph run.
  if (SMALL) {
    // The OS reserves a 1 px left side-bearing for a parenthesised raised group: a
    // digit exponent sits at base_width+1 (X^2: "2" one px past the base), and a
    // parenthesised exponent's "(" sits one px further still (X^(1/2), A^(N-N): the
    // "(" two px past the base). Prepend one blank column for that bearing; the
    // trailing side comes from atom()'s post-")" advance. The parens-to-content
    // join keeps the normal 1 px gap (trace (1/2): "(" to "1" is 1 px); only the
    // inner operators (/, -, …) abut with 0 px (runGap).
    const run = hcat([smallGlyph(0x28), box, smallGlyph(0x29)]);
    const PAD = 1;
    return {
      rows: run.rows.map(r => new Array(PAD).fill(0).concat(r)),
      baseline: run.baseline,
      marks: shift(run.marks, PAD, 0),
    };
  }
  const h = bh(box);
  const lp = stretch(trim(largeGlyph(0x28)), h, 3);
  const rp = stretch(trim(largeGlyph(0x29)), h, 3);
  // The OS wraps the content in delimiters of exactly the content's height,
  // centred on the content (trace: ( spans the same rows as the body, no taller).
  // stretch() centres the baseline at h>>1, which can disagree with the content
  // baseline and make hcat add a phantom row; pin the delimiters to the content's
  // baseline so the wrapped box is the same height as the body.
  lp.baseline = rp.baseline = box.baseline;
  // emit the delimiters as ordered elements ( body ) so the draw animation shows
  // them as separate steps, matching the trace, not lumped into the final reveal
  lp.marks = [{ ch: '(', x: 0, y: 0, w: bw(lp), h: bh(lp), type: 'glyph',
               font: 'large', via: 'delimiter (stretched)' }];
  rp.marks = [{ ch: ')', x: 0, y: 0, w: bw(rp), h: bh(rp), type: 'glyph',
               font: 'large', via: 'delimiter (stretched)' }];
  // The OS leaves a 2 px gap between a delimiter and the wrapped content (trace
  // int(1,2,(...)X,X): ( right edge x13, content X left edge x16 -> 2 blank cols),
  // one more than the default text gap.
  return hcat([lp, box, rp], 2);
}

// Absolute-value record type 21h emits structural bars rather than large-font
// "|" glyphs. The child is placed three pixels from the left record edge; the
// handler draws both bars before entering the child renderer.
function absoluteValue(body) {
  const child = trimExp(body);
  const h = bh(child);
  const recordW = recordWidth(child) + 0x0c;
  const operations = ROM_ENGINE
    ? ROM_ENGINE.settledAbsoluteOperations(recordW, h)
    : null;
  const left = operations ? operations[0].from.x : 2;
  const right = operations ? operations[1].from.x : recordW - 4;
  const out = blank(h, right - left + 1);
  const origin = left;
  for (let y = 0; y < h; y++) {
    out[y][left - origin] = 1;
    out[y][right - origin] = 1;
  }
  const childX = 4;
  for (let y = 0; y < bh(child); y++)
    for (let x = 0; x < bw(child); x++)
      if (child.rows[y][x]) out[y][childX + x] = 1;
  const marks = [
    {ch:'| left', x:0, y:0, w:1, h, type:'rule',
     via:operations ? operations[0].routine : 'modeled absolute bar'},
    {ch:'| right', x:right-origin, y:0, w:1, h, type:'rule',
     via:operations ? operations[1].routine : 'modeled absolute bar'},
    ...shift(child.marks, childX, 0),
  ];
  return {rows:out, baseline:child.baseline, marks, recordWidth:recordW};
}

// A big operator (∫, Σ): a tall sign with upper/lower limits stacked at its
// corners, then the body. `inner` is the already-composed body; `signCode` is the
// large-font glyph; `stem` is the stem-row index to repeat when stretching (null
// = do not stretch, e.g. Σ whose diagonals do not tile).
function bigOp(signCode, signName, lo, hi, inner, stem, signBuilder) {
  const limit = v => trim(typeof v === 'string' ? smallText(v) : v);
  const loB = limit(lo), hiB = limit(hi);
  const symH = Math.max(bh(inner) + bh(hiB) + bh(loB), 11);
  const sign = signBuilder ? signBuilder(symH)
    : (stem == null ? trim(largeGlyph(signCode))
                    : stretch(trim(largeGlyph(signCode)), symH, stem));
  const rw = Math.max(bw(loB), bw(hiB));
  const h = bh(sign);
  const out = blank(h, bw(sign) + 1 + rw);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < bw(sign); x++) if (sign.rows[y][x]) out[y][x] = 1;
  for (let y = 0; y < bh(hiB); y++)
    for (let x = 0; x < bw(hiB); x++) if (hiB.rows[y][x]) out[y][bw(sign) + 1 + x] = 1;
  for (let y = 0; y < bh(loB); y++)
    for (let x = 0; x < bw(loB); x++) if (loB.rows[y][x]) out[h - bh(loB) + y][bw(sign) + 1 + x] = 1;
  // The OS centres the body vertically on the sign and starts it 2 px after the
  // sign+limit block (trace int(1,2,X^2,X): sign rows 0-19, limits at the sign's
  // top/bottom corners, body ( at x = sign+limit_right + 2, body rows 5-14 i.e.
  // (h-bodyH)/2). Place the body directly so its midpoint lands on the sign centre
  // rather than its (off-centre) text baseline.
  const blockW = bw(sign) + 1 + rw;        // sign + gap + limit column
  const bodyX = blockW + 2;
  const bodyTop = Math.max(0, Math.round((h - bh(inner)) / 2));
  const W = Math.max(blockW, bodyX + bw(inner));
  const fullH = Math.max(h, bodyTop + bh(inner));
  const grid = blank(fullH, W);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < blockW; x++) if (out[y][x]) grid[y][x] = 1;
  for (let y = 0; y < bh(inner); y++)
    for (let x = 0; x < bw(inner); x++) if (inner.rows[y][x]) grid[bodyTop + y][bodyX + x] = 1;
  const signMarks = signBuilder ? sign.marks : [
    { ch: signName, x: 0, y: 0, w: bw(sign), h, type: 'glyph', font: 'large',
      via: `0x${signCode.toString(16)}` + (stem == null ? '' : ' (stretched)') },
  ];
  const marks = [
    ...signMarks,
    ...shift(hiB.marks, bw(sign) + 1, 0),
    ...shift(loB.marks, bw(sign) + 1, h - bh(loB)),
    ...shift(inner.marks, bodyX, bodyTop),
  ];
  // The OS reserves a 2 px right bearing after a big-operator box: anything that
  // follows it (an additive "+", or a wrapping closing delimiter) sits 2 px past
  // the integrand's last column (trace int(1,2,(1//2)X,X)+2: dX right edge x46,
  // "+" left edge x48 -> 2 blank cols; and (int(...))+2: closing ) leftmost ink
  // 4 px past dX = parens' 2 px gap + this 2 px bearing). adv > bw advances the
  // pen that far without widening the bitmap.
  return { rows: grid, baseline: bodyTop + inner.baseline, marks, adv: W + 2 };
}

function settledIntegralSign(height) {
  if (!ROM_ENGINE) return stretch(trim(largeGlyph(0x08)), height, 3);
  const operations = ROM_ENGINE.settledIntegralOperations(height);
  const rows = blank(height, 5);
  const marks = [];
  for (const operation of operations) {
    if (operation.kind === 'point') {
      rows[operation.y][operation.x] = 1;
      marks.push({ch:'∫ hook point', x:operation.x, y:operation.y, w:1, h:1,
                  type:'point', via:operation.routine});
      continue;
    }
    const y0 = Math.min(operation.from.y, operation.to.y);
    const y1 = Math.max(operation.from.y, operation.to.y);
    for (let y = y0; y <= y1; y++) rows[y][operation.from.x] = 1;
    marks.push({ch:'∫ stem', x:operation.from.x, y:y0, w:1, h:y1-y0+1,
                type:'rule', via:operation.routine});
  }
  return {rows, baseline:height >> 1, marks};
}

// Definite integral: ∫ with limits, then ( body ) d var. lo/hi may be a string
// (small font, like the OS) or a box. Lintegral 0x08 = top hook (rows 0-1),
// stem (rows 2-4), bottom hook (rows 5-6); repeat a stem row when stretching.
function integral(lo, hi, body, varBox) {
  // The OS wraps the whole integrand in tall parentheses (trace ∫((1/2)X)dX shows a
  // single ( ... ) pair around the 1/2-times-X body; the user's literal parens
  // around the fraction are elided, since a stacked fraction needs none). The
  // closing delimiter then has a 2 px right bearing before the differential "d",
  // and 1 px between "d" and the variable.
  const diff = hcat([text('d'), varBox || text('X')], 1);
  const inner = hcat([parens(body), diff], 2);
  // Class 0Dh row 2, slot 8 is 0842. The translated 4DCA/4DE6/4E8E/4F1A
  // path resolves that structural cell to Lintegral glyph 08h.
  let signCode = 0x08;
  let signVia = '0x08 (fallback before layout.json loads)';
  if (LAYOUT && ROM_ENGINE) {
    const emitted = ROM_ENGINE.emitHandlerRow(LAYOUT, 0x0d, 2).emissions[8];
    if (emitted.output.kind !== 'directGlyph')
      throw new Error('class 0D integral cell is not a direct glyph');
    signCode = emitted.output.glyph;
    signVia = `39:${emitted.address.toString(16).toUpperCase()} → 39:4F1A`;
  }
  const result = bigOp(signCode, '∫ Lintegral', lo, hi, inner, 3,
                       settledIntegralSign);
  if (result.marks && result.marks.length)
    result.marks[0].via += `; glyph selected by ${signVia}`;
  return result;
}
// Summation Σ (MATH>0, glyph 0xC6): the OS stacks the limits vertically - the
// upper limit (end) small-centered ABOVE the sign, the lower limit "var=start"
// small BELOW it (left-aligned), the sign in the middle, then the body to the
// right at the sign's vertical centre. [confirmed vs calc]
function stackedOp(signCode, signName, varStr, lo, hi, body) {
  const small = s => trim(smallText(s));
  const hiB = small(hi);
  const loB = small(varStr + '=' + lo);
  const sign = trim(largeGlyph(signCode));
  const colW = Math.max(bw(hiB), bw(sign), bw(loB));
  const padL = (w) => (colW - w) >> 1;
  const gapRow = () => new Array(colW).fill(0);
  // calc stacks: upper limit, 1px gap, sign, 1px gap, lower limit
  const rows = center(hiB.rows, colW);
  rows.push(gapRow());
  const signTop = rows.length;
  rows.push(...center(sign.rows, colW));
  rows.push(gapRow());
  const loTop = rows.length;
  rows.push(...loB.rows.map(r => r.concat(new Array(colW - bw(loB)).fill(0))));
  const stack = { rows, baseline: signTop + sign.baseline, marks: [
    ...shift(hiB.marks, padL(bw(hiB)), 0),
    { ch: signName, x: padL(bw(sign)), y: signTop, w: bw(sign), h: bh(sign),
      type: 'glyph', font: 'large', via: `0x${signCode.toString(16)}` },
    ...shift(loB.marks, 0, loTop),
  ] };
  return hcat([stack, parens(body)], 2);
}
function summation(varStr, lo, hi, body) { return stackedOp(0xC6, 'Σ Sigma', varStr, lo, hi, body); }

// nth root: a small-font index raised at the radical's upper-left "notch". The OS
// lifts the index above the vinculum (raising the whole box) and tucks the radical
// just to its right with a 1 px overlap, so the index sits in the hook's corner
// (trace nthroot(2,3): index "2" rows 0-4 cols 0-3, radical stem at col 5, vinculum
// from row 2 — the index rises 2 px above the radical top and the radical shifts
// right by index_width-1).
function nthRoot(indexStr, body) {
  const wasSmall = SMALL; SMALL = true;
  const idx = trim(text(indexStr));
  SMALL = wasSmall;
  const radicand = trimExp(body);
  const iw = bw(idx), ih = bh(idx);
  const operations = ROM_ENGINE
    ? ROM_ENGINE.settledNthRootOperations(recordWidth(idx), recordWidth(body))
    : null;
  const RAISE = 2;
  const hookX = operations ? operations[1].x : iw - 1;
  const radX = hookX + 5;
  const h = RAISE + bh(radicand) + 2;
  const rule = operations ? operations[4] : {
    from:{x:radX,y:RAISE}, to:{x:radX + recordWidth(body) - 1,y:RAISE},
  };
  const w = Math.max(iw, rule.to.x + 1, radX + bw(radicand));
  const out = blank(h, w);
  for (let y = 0; y < ih; y++)
    for (let x = 0; x < iw; x++) if (idx.rows[y][x]) out[y][x] = 1;
  const hook = stretch(trim(largeGlyph(0x10)), bh(radicand) + 2, 3);
  for (let y = 0; y < bh(hook); y++)
    for (let x = 0; x < bw(hook); x++)
      if (hook.rows[y][x] && hookX + x < w) out[RAISE + y][hookX + x] = 1;
  for (let x = rule.from.x; x <= rule.to.x; x++) out[rule.from.y][x] = 1;
  for (let y = 0; y < bh(radicand); y++)
    for (let x = 0; x < bw(radicand); x++)
      if (radicand.rows[y][x]) out[RAISE + 2 + y][radX + x] = 1;
  const marks = [
    ...shift(idx.marks, 0, 0),
    {ch:'ⁿ√ hook', x:hookX, y:RAISE, w:5, h:5, type:'glyph', font:'large',
     via:operations ? operations[1].routine : 'modeled nth-root hook'},
    {ch:'ⁿ√ stem', x:hookX+2, y:RAISE+3, w:1, h:Math.max(1,h-RAISE-3), type:'rule',
     via:operations ? operations[2].routine : 'modeled nth-root stem'},
    ...shift(radicand.marks, radX, RAISE+2),
    {ch:'─ vinculum', x:rule.from.x, y:rule.from.y,
     w:rule.to.x-rule.from.x+1, h:1, type:'rule',
     via:operations ? operations[4].routine : 'modeled nth-root vinculum'},
  ];
  return { rows: out, baseline: RAISE + 2 + radicand.baseline, marks };
}

// ---- text runs ------------------------------------------------------------
// The OS draws raised/subscript content (exponents, integral limits) in the
// small variable-width font. SMALL tracks that mode so nested exponents and
// limits pick the right glyph table, the way the page-39 draw pass does.

let SMALL = false;
function glyphFor(code) { return SMALL ? smallGlyph(code) : largeGlyph(code); }
// Inter-token gap for a run. Large 5x7 glyphs advance by width+1 (a 1 px gap). The
// small variable-width glyphs bake their advance into the cell (each carries a
// trailing blank column), so a raised/subscript run abuts edge-to-edge with NO
// extra gap (trace X^(1/2), A^(N-N): the exponent operators "/" and "-" are drawn
// flush; GAP=1 over-spaces them 1 px per boundary). Used by every text-run join.
function runGap() { return SMALL ? 0 : GAP; }

function text(s) { return hcat([...s].map(ch => glyphFor(ch.charCodeAt(0)))); }
function smallText(s) {
  const t = hcat([...s].map(ch => smallGlyph(ch.charCodeAt(0))));
  return t.rows.length ? t : largeGlyph(0x20);
}

// ---- expression parser (recursive descent) -------------------------------
// grammar: expr := add ; add := frac (('+'|'-') frac)* ;
//          frac := mul (('/') mul)* ; mul := pow (('*') pow | juxtaposition)* ;
//          pow  := atom ('^' atom)* ; atom := num | ident | '(' expr ')' | func

// Lenient recursive-descent parser: it renders whatever is well-formed so far,
// so the layout updates live as you type. A partial expression — an unclosed
// paren or a template still missing arguments — lays out what it has rather
// than refusing to render.
function parse(src) {
  let i = 0;
  const s = src.replace(/\s+/g, '');
  const peek = () => (i < s.length ? s[i] : '');   // '' at EOF: regex.test('') is false
  const eat = c => { if (s[i] === c) { i++; return true; } return false; };
  let steps = 0;
  const guard = () => { if (++steps > 100000) throw new Error('parse step cap'); };

  function expr() { return add(); }
  function add() {
    let b = frac();
    while (peek() === '+' || peek() === '-') { guard(); const op = s[i++]; b = hcat([b, text(op), frac()], runGap()); }
    return b;
  }
  function frac() {
    let start = i;
    let b = mul();
    for (;;) {
      guard();
      if (s[i] === '/' && s[i + 1] === '/') {                 // stacked n/d template
        const wasSmall = SMALL;
        if (!wasSmall) { i = start; SMALL = true; b = mul(); } // re-render numerator small
        i += 2;
        const den = mul();                                    // denominator (still small)
        SMALL = wasSmall;
        b = fraction(b, den);
        start = i;
      } else if (s[i] === '/') {                              // linear (the ÷ key)
        // A raised/subscript linear divide (an exponent or limit "a/b") abuts its
        // operands and the small "/" with no gap (trace X^(1/2): the exponent is
        // "(1/2)" with the slash drawn edge-to-edge). At large size "/" keeps 1 px.
        i++; b = hcat([b, text('/'), mul()], runGap()); start = i;
      } else break;
    }
    return b;
  }
  function mul() {
    let b = pow();
    for (;;) {
      guard();
      if (peek() === '*') { i++; b = hcat([b, text('*'), pow()], runGap()); }
      else if (isAtomStart(peek())) { b = hcat([b, pow()], runGap()); }   // implicit multiply
      else break;
    }
    return b;
  }
  function pow() {
    let b = atom();
    while (peek() === '^') {
      i++;
      const wasSmall = SMALL; SMALL = true;   // exponents render in the small font
      const e = atom();
      SMALL = wasSmall;
      b = superscript(b, e);
    }
    return b;
  }
  function isAtomStart(c) { return c && (/[A-Za-z0-9.]/.test(c) || c === '('); }
  function ident() { let j = i; while (/[A-Za-z]/.test(peek())) i++; return s.slice(j, i); }
  function number() { let j = i; while (/[0-9.]/.test(peek())) i++; return s.slice(j, i); }

  function atom() {
    // Typed parens render as tall delimiters, matching the calculator. A lone
    // stacked fraction is self-delimiting, so parens around just a fraction are
    // elided (e.g. (1//2)X shows ½X, not (½)X).
    if (eat('(')) {
      const b = expr(); eat(')');
      if (b.kind === 'fraction') return b;   // self-delimiting; no tall parens
      // The OS reserves a 1 px bearing on BOTH sides of a typed parenthesised
      // group. Right: a following glyph sits 1 px past the closing delimiter (trace
      // (X)+2, (1//2+1)+2, (int(...))+2 — the post-")" glyph one column further
      // right than the default text gap). Left: a preceding glyph leaves 1 px before
      // the opening delimiter (1//X+(A), sqrt((X)): the "(" sits one column right of
      // a plain abutment). Model the left bearing as a leading blank column (a lone
      // leading group is cropped away, so leading parens are unaffected); advance
      // the pen 1 px past the bitmap for the right bearing.
      const p = parens(b);
      const lp = {
        rows: p.rows.map(r => [0].concat(r)),
        baseline: p.baseline,
        marks: shift(p.marks, 1, 0),
      };
      return { ...lp, adv: bw(lp) + 1 };
    }
    if (/[0-9.]/.test(peek())) return text(number());
    if (/[A-Za-z]/.test(peek())) {
      const id = ident();
      if (peek() === '(') {
        if (id === 'int' || id === 'integral') return intCall();
        if (id === 'sum') return bigOpCall(id);
        if (id === 'nthroot') return nthRootCall();
        const args = call();
        if (id === 'sqrt' || id === 'root') return radical(args[0] || text(''));
        if (id === 'abs') return absoluteValue(args[0] || text(''));
        // unknown function: name followed by its parenthesised args
        return hcat([text(id), parens(args[0] || text(''))]);
      }
      return text(id);
    }
    i++; return text('');  // skip a stray char so live typing keeps rendering
  }
  function call() {
    eat('(');
    const args = [];
    if (peek() !== ')') { args.push(expr()); while (eat(',')) args.push(expr()); }
    eat(')');
    return args;
  }
  // int(lo, hi, body, var): read lo/hi as small-font strings when they are plain
  // tokens, otherwise as composed boxes; body and var as full expressions.
  function intCall() {
    eat('(');
    const lo = limitArg(); eat(',');
    const hi = limitArg(); eat(',');
    const body = expr(); eat(',');
    const varBox = atom(); eat(')');
    return integral(lo, hi, body, varBox);
  }
  // sum(var,lo,hi,body): "var=lo" below the Σ, "hi" above, body to the right.
  function bigOpCall(id) {
    eat('(');
    const v = limitArg(); eat(',');
    const lo = limitArg(); eat(',');
    const hi = limitArg(); eat(',');
    const body = expr(); eat(')');
    const vs = typeof v === 'string' ? v : 'N';
    const ls = typeof lo === 'string' ? lo : '1';
    const hs = typeof hi === 'string' ? hi : 'n';
    return summation(vs, ls, hs, body);
  }
  // nthroot(n, body): small-font index over the radical hook.
  function nthRootCall() {
    eat('(');
    const n = limitArg(); eat(',');
    const body = expr(); eat(')');
    return nthRoot(n, body);
  }
  function limitArg() {
    const j = i;
    while (/[0-9.A-Za-z]/.test(peek())) i++;
    if (i > j && (s[i] === ',' || s[i] === ')')) return s.slice(j, i);  // simple -> string
    i = j; return expr();                                               // complex -> box
  }

  return clipMarks(expr());
}

// ---- canvas rendering -----------------------------------------------------

// Draw the box. `step` (the emission element index, null = all) animates the
// model composition order: each glyph/rule is revealed at its modeled position.
function draw(box, scale, color, showPen, step) {
  const canvas = document.getElementById('screen');
  const ctx = canvas.getContext('2d');
  const W = Math.max(bw(box), 1), H = Math.max(bh(box), 1);
  const marks = box.marks || [];
  const full = step == null || step >= marks.length;
  const pad = 4;
  canvas.width = (W + pad * 2) * scale;
  canvas.height = (H + pad * 2) * scale;
  ctx.fillStyle = color.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  let mask = null;
  if (!full) {
    mask = blank(H, W);
    for (let i = 0; i < step; i++) {
      const m = marks[i];
      for (let yy = Math.max(0, m.y); yy < Math.min(H, m.y + (m.h || 1)); yy++)
        for (let xx = Math.max(0, m.x); xx < Math.min(W, m.x + (m.w || 1)); xx++)
          mask[yy][xx] = 1;
    }
  }
  ctx.fillStyle = color.fg;
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++)
      if (box.rows[y][x] && (full || mask[y][x]))
        ctx.fillRect((x + pad) * scale, (y + pad) * scale, scale, scale);

  if (!full && step > 0) {                     // highlight the element just drawn
    const m = marks[step - 1];
    ctx.strokeStyle = '#6ea8fe';
    ctx.lineWidth = Math.max(1, scale / 4);
    ctx.strokeRect((m.x + pad) * scale, (m.y + pad) * scale,
                   (m.w || 1) * scale, (m.h || 1) * scale);
  }
  if (showPen) {
    ctx.font = `${Math.max(8, scale)}px monospace`;
    marks.forEach((m, i) => {
      ctx.fillStyle = '#ff5050';
      ctx.fillRect((m.x + pad) * scale - 1, (m.y + pad) * scale - 1, 2, 2);
      ctx.fillText(String(i), (m.x + pad) * scale + 1, (m.y + pad) * scale - 1);
    });
  }
  document.getElementById('dims').textContent = `${W}×${H} px · ${marks.length} emitted elements`;
  return marks;
}

// Pen log = elements in emission (draw) order.
function penLog(box) { return (box.marks || []).slice(); }

const PRESETS = [
  ['linear 1/2', '1/2'],
  ['stacked 1//2', '1//2'],
  ['X squared', 'X^2'],
  ['(A+B)//C', '(A+B)//C'],
  ['nested fraction', '1//(2//3)'],
  ['radical', 'sqrt(X^2+1)'],
  ['absolute value (RE)', 'abs(X-3)'],
  ['definite integral', 'int(1,2,X^2,X)'],
  ['integral of a fraction', 'int(1,2,(1//2)X,X)'],
  ['radical of a fraction', 'sqrt((X^2+1)//X)'],
  ['summation (RE)', 'sum(N,1,3,N^2)'],
  ['cube root', 'nthroot(3,X+1)'],
  ['nDeriv (RE)', 'nDeriv(X^2,X,1)'],
  ['nth root of a fraction', 'nthroot(N,X//2)'],
];

let CUR = null, CUR_TRACE = null, CUR_GENERATED = null, ANIM = null;

function curColor() {
  return document.getElementById('lcd').checked
    ? { bg: '#c7d4b8', fg: '#2a3326' } : { bg: '#ffffff', fg: '#000000' };
}

function drawTraceGrid(grid, scale, color, changes) {
  const canvas = document.getElementById('screen');
  const ctx = canvas.getContext('2d');
  const H = grid.length, W = H ? grid[0].length : 0;
  const pad = 2;
  canvas.width = (W + pad * 2) * scale;
  canvas.height = (H + pad * 2) * scale;
  ctx.fillStyle = color.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = color.fg;
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++)
      if (grid[y][x]) ctx.fillRect((x + pad) * scale, (y + pad) * scale, scale, scale);
  for (const [x, y, value] of changes || []) {
    if (value) {
      ctx.fillStyle = '#6ea8fe';
      ctx.fillRect((x + pad) * scale, (y + pad) * scale, scale, scale);
    } else {
      // Use filled, integer-aligned edges. Canvas strokes straddle their path,
      // which antialiases this one-pixel overlay at common odd line widths.
      const left = (x + pad) * scale;
      const top = (y + pad) * scale;
      const edge = Math.max(1, Math.floor(scale / 4));
      ctx.fillStyle = '#ff5050';
      ctx.fillRect(left, top, scale, edge);
      ctx.fillRect(left, top + scale - edge, scale, edge);
      ctx.fillRect(left, top + edge, edge, Math.max(0, scale - 2 * edge));
      ctx.fillRect(left + scale - edge, top + edge, edge,
                   Math.max(0, scale - 2 * edge));
    }
  }
}

function decodeTraceGrid(rows) {
  return rows.map(row => Array.from(row, pixel => pixel === '1' ? 1 : 0));
}

function traceFrame(record, step) {
  const grid = decodeTraceGrid(record.initial);
  const count = Math.max(0, Math.min(record.events.length, step));
  for (let i = 0; i < count; i++)
    for (const [x, y, value] of record.events[i].changes) grid[y][x] = value;
  return grid;
}

function traceForExpression(expression) {
  return (DRAW_ORDER.scenarios || {})[expression.trim()] || null;
}

function generateRecordProgram(program) {
  if (!program || !ROM_ENGINE) return null;
  const operations = ROM_ENGINE.executeSettledRecordProgram(
    program.nodes, program.entry_id, {
      origin:program.origin,
      glyphAdvance:(depth, code) => depth ? FONT.small.glyphs[code].w : 6,
    });
  const rendered = ROM_ENGINE.rasterizeSettledOperations(operations, FONT);
  return {
    width:rendered.width, height:rendered.height,
    initial:Array.from({length:rendered.height}, () => '0'.repeat(rendered.width)),
    final:rendered.grid.map(row => row.join('')),
    operations,
    events:rendered.writes.map((write, index) => ({
      ...write,
      source:'RE-generated',
      operation:operations[write.operationIndex],
      sequence:index,
    })),
    programSource:program.source || 'captured settled record snapshot',
  };
}

const FLAT_SETTLED_OPERATOR_TOKENS = Object.freeze({
  '+':0x70, '-':0x71, '*':0x82, '/':0x83,
});

function flatSettledTokenBytes(source) {
  const bytes = [];
  for (const ch of source) {
    if (/[A-Z0-9]/.test(ch)) bytes.push(ch.charCodeAt(0));
    else if (ch === '.') bytes.push(0x3a);
    else if (FLAT_SETTLED_OPERATOR_TOKENS[ch] !== undefined)
      bytes.push(FLAT_SETTLED_OPERATOR_TOKENS[ch]);
    else return null;
  }
  return bytes.length ? bytes : null;
}

// Closed expression grammar for the translated record constructor. It keeps
// ordinary token runs in their leaf order and makes power right-associative,
// matching the page-34 record pass. Parenthesized, multi-argument, and other
// untranslated template families remain outside this grammar.
function constructedSettledSpec(source) {
  let offset = 0;
  const atom = () => {
    if (source.startsWith('nthroot(', offset)) {
      offset += 8;
      const index = expression(',');
      if (!index || source[offset] !== ',') return null;
      offset++;
      const radicand = expression(')');
      if (!radicand || source[offset] !== ')') return null;
      offset++;
      return {kind:'nthRoot', index, radicand};
    }
    if (source.startsWith('sqrt(', offset)) {
      offset += 5;
      const radicand = expression(')');
      if (!radicand || source[offset] !== ')') return null;
      offset++;
      return {kind:'radical', radicand};
    }
    const match = /^[A-Z0-9.]+/.exec(source.slice(offset));
    if (!match) return null;
    offset += match[0].length;
    const tokens = flatSettledTokenBytes(match[0]);
    return tokens ? {kind:'tokens', tokens} : null;
  };
  const power = () => {
    const base = atom();
    if (!base) return null;
    if (source[offset] !== '^') return base;
    // The translated power slice currently closes ordinary-token bases. Its
    // exponent may contain another translated structural expression.
    if (base.kind !== 'tokens') return null;
    offset++;
    const exponent = power();
    return exponent ? {kind:'power', base:base.tokens, exponent} : null;
  };
  const expression = stop => {
    const parts = [];
    const first = power();
    if (!first) return null;
    parts.push(first);
    while (offset < source.length && source[offset] !== stop) {
      const operator = source[offset++];
      if (!'+-*/'.includes(operator)) return null;
      const right = power();
      if (!right) return null;
      parts.push(
        {kind:'tokens', tokens:[FLAT_SETTLED_OPERATOR_TOKENS[operator]]}, right);
    }
    return parts.length === 1 ? parts[0] : {kind:'sequence', parts};
  };
  const result = expression('');
  return result && offset === source.length ? result : null;
}

function constructedProgramForExpression(expression) {
  if (!ROM_ENGINE) return null;
  const source = expression.trim();
  const absolute = /^abs\(([A-Z0-9.+*/-]+)\)$/.exec(source);
  if (absolute && !absolute[1].includes('//')) {
    const payload = flatSettledTokenBytes(absolute[1]);
    if (payload) return ROM_ENGINE.constructSettledAbsoluteProgram(payload);
  }
  const radical = /^sqrt\(([^()]*)\)$/.exec(source);
  if (radical) {
    const radicand = constructedSettledSpec(radical[1]);
    return radicand
      ? ROM_ENGINE.constructSettledRadicalProgram(radicand, 1, FONT)
      : null;
  }
  const spec = constructedSettledSpec(source);
  if (!spec) return null;
  return spec.kind === 'power'
    ? ROM_ENGINE.constructSettledPowerProgram(spec, 1, FONT)
    : spec.kind === 'nthRoot'
      ? ROM_ENGINE.constructSettledNthRootProgram(
          spec.index, spec.radicand, 1, FONT)
    : ROM_ENGINE.constructSettledExpressionProgram(spec, 1, FONT);
}

function generatedForExpression(expression) {
  const constructed = constructedProgramForExpression(expression);
  const fixture = (RECORD_PROGRAMS.programs || {})[expression.trim()];
  return generateRecordProgram(constructed || fixture);
}

function activeTimeline() {
  const source = document.getElementById('source').value;
  if (source === 'generated' && CUR_GENERATED) return CUR_GENERATED;
  if (source === 'trace' && CUR_TRACE) return CUR_TRACE;
  return null;
}

function renderTrace(record, step, scale) {
  const n = record.events.length;
  const count = step == null ? n : Math.max(0, Math.min(n, step));
  const current = step != null && count > 0 ? record.events[count - 1] : null;
  drawTraceGrid(traceFrame(record, count), scale, curColor(), current && current.changes);
  const rows = record.events.map((event, i) => {
    const sets = event.changes.filter(change => change[2]).length;
    const clears = event.changes.length - sets;
    return `<tr class="${current && i === count - 1 ? 'cur' : ''}" data-step="${i + 1}">` +
      `<td>${i}</td><td>${event.instruction_index}</td><td>${event.clock}</td>` +
      `<td>0x${event.port.toString(16).padStart(2, '0')}</td>` +
      `<td>0x${event.value.toString(16).padStart(2, '0')}</td>` +
      `<td>${event.pointer[0]},${event.pointer[1]}</td>` +
      `<td><span class="trace-set">+${sets}</span> ` +
      `<span class="trace-clear">−${clears}</span></td></tr>`;
  }).join('');
  document.getElementById('penlog').innerHTML =
    `<p class="note">Captured T6A04 writes in TLMT instruction order. Only accepted ` +
    `writes that change a visible pixel appear. Click a row to jump to that write.</p>` +
    `<table><thead><tr><th>#</th><th>instruction</th><th>clock</th><th>port</th>` +
    `<th>byte</th><th>LCD x,y</th><th>pixels</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById('dims').textContent =
    `${record.width}×${record.height} LCD · write ${count}/${n} · captured trace`;
  const tl = document.getElementById('timeline');
  if (step == null) { tl.max = n; tl.value = n; }
}

function operationLabel(operation) {
  if (!operation) return '';
  if (operation.kind === 'glyph') return `${glyphName(operation.code)} glyph`;
  if (operation.kind === 'glyph-run') return 'glyph run';
  if (operation.kind === 'bitmap') return 'fixed bitmap';
  return operation.kind;
}

function renderGenerated(record, step, scale) {
  const n = record.events.length;
  const count = step == null ? n : Math.max(0, Math.min(n, step));
  const current = step != null && count > 0 ? record.events[count - 1] : null;
  drawTraceGrid(traceFrame(record, count), scale, curColor(), current && current.changes);
  const rows = record.events.map((event, i) => {
    const sets = event.changes.filter(change => change[2]).length;
    const clears = event.changes.length - sets;
    return `<tr class="${current && i === count - 1 ? 'cur' : ''}" data-step="${i + 1}">` +
      `<td>${i}</td><td>${escapeHtml(operationLabel(event.operation))}</td>` +
      `<td>0x${event.value.toString(16).padStart(2, '0')}</td>` +
      `<td>${event.pointer[0]},${event.pointer[1]}</td>` +
      `<td><span class="trace-set">+${sets}</span> ` +
      `<span class="trace-clear">−${clears}</span></td>` +
      `<td>${escapeHtml(event.operation.routine || '')}</td></tr>`;
  }).join('');
  document.getElementById('penlog').innerHTML =
    `<p class="note">RE-generated LCD data writes. JavaScript executes the settled ` +
    `record program, geometry routines, glyph blitter, and byte packing. Input: ` +
    `<code>${escapeHtml(record.programSource)}</code>. No captured ` +
    `LCD events are used as input. Click a row to jump to that write.</p>` +
    `<table><thead><tr><th>#</th><th>operation</th><th>byte</th><th>LCD x,y</th>` +
    `<th>pixels</th><th>translated path</th></tr></thead><tbody>${rows}</tbody></table>`;
  document.getElementById('dims').textContent =
    `${record.width}×${record.height} LCD · write ${count}/${n} · RE-generated`;
  const tl = document.getElementById('timeline');
  if (step == null) { tl.max = n; tl.value = n; }
}

function renderModel(box, step, scale, showPen) {
  const marks = draw(box, scale, curColor(), showPen, step);
  const cur = (step != null && step > 0 && step <= marks.length) ? step - 1 : -1;
  const rows = marks.map((m, i) =>
    `<tr class="${i === cur ? 'cur' : ''}" data-step="${i + 1}"><td>${i}</td><td>${escapeHtml(m.ch)}</td>` +
    `<td>${m.x}</td><td>${m.y}</td><td>${m.font || (m.type === 'rule' ? 'rule' : '')}</td>` +
    `<td>${escapeHtml(m.via || '')}</td></tr>`).join('');
  document.getElementById('penlog').innerHTML =
    `<p class="note">Model display list — elements in composition order with ` +
    `X/Y (top-left), font, and the corresponding ROM routine where known. ` +
    `Click a row to jump the timeline to that draw step. ` +
    `These coordinates are model-local, not RAM pen variables. Large glyph records pass through ` +
    `put_glyph_large (07:4588); ` +
    `small (exponents, limits, fraction digits) through _VPutMap (01:6293).</p>` +
    `<table><thead><tr><th>#</th><th>elem</th><th>penX</th><th>penY</th>` +
    `<th>font</th><th>emitted by</th></tr></thead><tbody>${rows}</tbody></table>`;
  const tl = document.getElementById('timeline');
  if (step == null) { tl.max = marks.length; tl.value = marks.length; }
}

function render(step) {
  const scale = +document.getElementById('scale').value;
  const showPen = document.getElementById('pen').checked;
  try {
    const expression = document.getElementById('expr').value;
    const box = CUR = parse(expression);
    CUR_TRACE = traceForExpression(expression);
    CUR_GENERATED = generatedForExpression(expression);
    const requested = document.getElementById('source').value;
    const generated = requested === 'generated' && CUR_GENERATED;
    const captured = requested === 'trace' && CUR_TRACE;
    if (generated) renderGenerated(CUR_GENERATED, step, scale);
    else if (captured) renderTrace(CUR_TRACE, step, scale);
    else renderModel(box, step, scale, showPen);
    document.getElementById('timeline-hint').textContent = generated || captured
      ? (generated ? 'step every accepted LCD data write' : 'step visible-changing LCD writes')
      : 'step model composition order';
    document.getElementById('timeline-note').innerHTML = captured
      ? `Captured mode replays accepted T6A04 writes from trace <code>${escapeHtml(CUR_TRACE.trace_sha256.slice(0, 12))}…</code> ` +
        `in instruction order. Blue pixels are set; outlined red pixels are cleared.`
      : generated
        ? `RE-generated mode starts from ${escapeHtml(CUR_GENERATED.programSource)}, then executes ` +
          `record bytes through the translated structural renderer and ` +
          `blitters. Captured LCD events are comparison oracles only and are not loaded by this path.`
        : (requested === 'model'
            ? `Model mode steps inferred composition elements. It is not an OS draw timeline.`
            : `No ${requested === 'trace' ? 'captured' : 'executable record-program'} timeline matches ` +
              `this expression. Showing the labeled heuristic model instead.`);
    document.getElementById('err').textContent = '';
  } catch (e) {
    document.getElementById('err').textContent = String(e);
  }
}

function stopAnim() { if (ANIM) { clearInterval(ANIM); ANIM = null; } }

function playAnim() {
  stopAnim();
  if (!CUR) render();
  const timeline = activeTimeline();
  const n = timeline ? timeline.events.length : (CUR.marks || []).length;
  let step = 0;
  const tl = document.getElementById('timeline');
  ANIM = setInterval(() => {
    step += 1;
    if (tl) tl.value = step;
    render(step);
    if (step >= n) { stopAnim(); render(); }   // final: reveal structural rules too
  }, timeline ? 30 : 350);
}
function escapeHtml(s) {
  return s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

// ---- font-table tab -------------------------------------------------------

// Draw one glyph bitmap (rows of 0/1) on a square pixel grid.
function glyphCanvas(grid, cell = 9) {
  const h = grid.length, w = grid.length ? grid[0].length : 0;
  const cv = document.createElement('canvas');
  cv.width = w * cell + 1;
  cv.height = h * cell + 1;
  const ctx = cv.getContext('2d');
  ctx.fillStyle = '#0f1217';
  ctx.fillRect(0, 0, cv.width, cv.height);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < w; x++) {
      ctx.fillStyle = grid[y][x] ? '#e6e9ee' : '#1c222c';
      ctx.fillRect(x * cell + 1, y * cell + 1, cell - 1, cell - 1);
    }
  return cv;
}

// Build the font-table view once, on first visit: every ROM glyph on its grid.
function buildFontTable() {
  const host = document.getElementById('fonttable');
  if (!host || host.dataset.built) return;
  host.dataset.built = '1';
  const sections = [
    ['Large font — 5×7, page 7 (_PutMap)', FONT.large.glyphs, c => largeGlyph(c).rows],
    ['Small / variable-width font — page 3 (_VPutMap)', FONT.small.glyphs, c => smallGlyph(c).rows],
  ];
  for (const [title, glyphs, toGrid] of sections) {
    const h2 = document.createElement('h2');
    h2.textContent = title;
    host.appendChild(h2);
    const grid = document.createElement('div');
    grid.className = 'glyphgrid';
    for (const code of Object.keys(glyphs).map(Number).sort((a, b) => a - b)) {
      const cell = document.createElement('figure');
      cell.className = 'glyphcell';
      cell.appendChild(glyphCanvas(toGrid(code)));
      const cap = document.createElement('figcaption');
      const hex = '0x' + code.toString(16).toUpperCase().padStart(2, '0');
      cap.innerHTML = `<span class="gcode">${hex}</span><span class="gname">${escapeHtml(glyphName(code))}</span>`;
      cell.appendChild(cap);
      grid.appendChild(cell);
    }
    host.appendChild(grid);
  }
}

function showTab(name) {
  document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.getElementById('tab-renderer').hidden = name !== 'renderer';
  document.getElementById('tab-font').hidden = name !== 'font';
  if (name === 'font') buildFontTable();
}

async function main() {
  const [fontResponse, layoutResponse, orderResponse, programsResponse] = await Promise.all([
    fetch('font.json'), fetch('layout.json'), fetch('draw-order.json'),
    fetch('record-programs.json'),
  ]);
  FONT = await fontResponse.json();
  LAYOUT = await layoutResponse.json();
  DRAW_ORDER = await orderResponse.json();
  RECORD_PROGRAMS = await programsResponse.json();
  const bar = document.getElementById('presets');
  PRESETS.forEach(([label, src]) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.onclick = () => { document.getElementById('expr').value = src; render(); };
    bar.appendChild(b);
  });
  document.getElementById('expr').addEventListener('input', () => { stopAnim(); render(); });
  document.getElementById('scale').addEventListener('input', () => render());
  document.getElementById('lcd').addEventListener('change', () => render());
  document.getElementById('pen').addEventListener('change', () => render());
  document.getElementById('source').addEventListener('change', () => { stopAnim(); render(); });
  document.getElementById('play').addEventListener('click', playAnim);
  document.querySelectorAll('.tab').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  document.getElementById('penlog').addEventListener('click', e => {
    const tr = e.target.closest('tr[data-step]');
    if (!tr) return;
    stopAnim();
    const step = +tr.dataset.step;
    const timeline = activeTimeline();
    const n = timeline ? timeline.events.length : ((CUR && CUR.marks) ? CUR.marks.length : 0);
    const tl = document.getElementById('timeline');
    if (tl) tl.value = step;
    render(step >= n ? null : step);   // last row: reveal structural rules, like the timeline at max
  });
  // Left/Right arrow keys step the draw order (when not typing in a field).
  document.addEventListener('keydown', e => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const ae = document.activeElement;
    if (ae && ae.matches('input, select, textarea')) return;
    if (document.getElementById('tab-renderer').hidden) return;
    const timeline = activeTimeline();
    const n = timeline ? timeline.events.length : ((CUR && CUR.marks) ? CUR.marks.length : 0);
    if (!n) return;
    const tl = document.getElementById('timeline');
    let step = tl ? +tl.value : n;
    step = Math.max(0, Math.min(n, step + (e.key === 'ArrowRight' ? 1 : -1)));
    stopAnim();
    if (tl) tl.value = step;
    render(step >= n ? null : step);
    e.preventDefault();
  });
  document.getElementById('timeline').addEventListener('input', e => {
    stopAnim();
    const timeline = activeTimeline();
    const n = timeline ? timeline.events.length : (CUR.marks || []).length;
    render(+e.target.value >= n ? null : +e.target.value);
  });
  document.getElementById('expr').value = 'int(1,2,(1//2)X,X)';
  render();
}

if (typeof document !== 'undefined') main();

// Node-side hook for tools/test-mathprint.js (headless layout verification).
if (typeof module !== 'undefined') {
  module.exports = {
    setFont: f => { FONT = f; },
    setLayout: value => { LAYOUT = value; },
    setRecordPrograms: value => { RECORD_PROGRAMS = value; },
    parse,
    penLog,
    traceFrame,
    generateRecordProgram,
    constructedProgramForExpression,
    generatedForExpression,
    toText: box => box.rows.map(r => r.map(c => (c ? '#' : '.')).join('')).join('\n'),
  };
}
