// MathPrint layout renderer — composes real TI-84 Plus ROM font glyphs into
// 2-D layouts, mirroring the page-0x39 engine documented in
// docs/sub-equation-display.md. A "box" is { rows: number[][] (0/1),
// baseline: number } where baseline is the math-axis row index.
//
// Geometry constants are the ROM-confirmed ones:
//   large glyph: 5 px wide, 7 rows, 1 px advance gap  (07:45FF)
//   exponent raise: 3 px        (eqdisp_set_row_for_tok; pixel-matched vs binary)
//   fraction column unit: 7 px  (683D cell-to-pixel mapper, x = base + 7*col)
//   row step: row_height + 2 px (6857 height accumulator)

let FONT = null;

const GAP = 1;            // px between adjacent glyphs in a text run
const EXP_RAISE = 3;      // px an exponent is lifted above the base axis
const FRAC_PAD = 2;       // px the fraction bar overhangs the wider operand

// ---- box primitives -------------------------------------------------------

function blank(h, w) {
  return Array.from({ length: h }, () => new Array(w).fill(0));
}
function bw(box) { return box.rows.length ? box.rows[0].length : 0; }
function bh(box) { return box.rows.length; }

function largeGlyph(code) {
  const rows = FONT.large.glyphs[code] || new Array(7).fill(0);
  const W = FONT.large.width;
  const grid = rows.map(r => Array.from({ length: W }, (_, i) => (r >> (W - 1 - i)) & 1));
  return { rows: grid, baseline: (grid.length >> 1) };  // centre on the math axis
}
function smallGlyph(code) {
  const g = FONT.small.glyphs[code];
  if (!g) return { rows: blank(7, 3), baseline: 3 };
  const grid = g.rows.map(r => Array.from({ length: g.w }, (_, i) => (r >> (g.w - 1 - i)) & 1));
  return { rows: grid, baseline: (grid.length >> 1) };
}

// Horizontal concatenation, aligned on the math axis (baseline).
function hcat(boxes, gap = GAP) {
  boxes = boxes.filter(b => b && bh(b) && bw(b));
  if (!boxes.length) return { rows: [], baseline: 0 };
  const above = Math.max(...boxes.map(b => b.baseline));
  const below = Math.max(...boxes.map(b => bh(b) - b.baseline));
  const h = above + below;
  const out = Array.from({ length: h }, () => []);
  boxes.forEach((b, k) => {
    const w = bw(b);
    const top = above - b.baseline, bot = below - (bh(b) - b.baseline);
    const padded = blank(top, w).concat(b.rows, blank(bot, w));
    for (let r = 0; r < h; r++) {
      if (k) for (let i = 0; i < gap; i++) out[r].push(0);
      out[r].push(...padded[r]);
    }
  });
  return { rows: out, baseline: above };
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
  };
}

function center(rows, w) {
  return rows.map(r => {
    const pad = (w - r.length) >> 1;
    return new Array(pad).fill(0).concat(r, new Array(w - r.length - pad).fill(0));
  });
}

// Fraction: numerator over a full-width rule over the denominator.
// Bar row is the math axis (matches the OS centring a sibling glyph on the bar).
function fraction(num, den) {
  const n = trim(num), d = trim(den);   // the OS stacks tight small-font digits
  const w = Math.max(bw(n), bw(d)) + FRAC_PAD;
  const gap = [new Array(w).fill(0)];
  const bar = [new Array(w).fill(1)];
  // 1px gap above and below the rule, matching the calculator
  const rows = center(n.rows, w).concat(gap, bar, gap, center(d.rows, w));
  return { rows, baseline: bh(n) + 1 };   // math axis = the bar row
}

// Superscript: base on the axis, exponent lifted EXP_RAISE px above-right.
function superscript(base, exp) {
  const e = trim(exp);
  const bwid = bw(base), ewid = bw(e);
  const h = EXP_RAISE + bh(base);
  const out = [];
  for (let r = 0; r < h; r++) {
    const left = (r >= EXP_RAISE) ? base.rows[r - EXP_RAISE] : new Array(bwid).fill(0);
    const right = (r < bh(e)) ? e.rows[r] : new Array(ewid).fill(0);
    out.push(left.concat([0], right));
  }
  return { rows: out, baseline: EXP_RAISE + base.baseline };
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
  const rad = trim(radicand);
  const h = bh(rad) + 2;                       // vinculum + 1 px gap above radicand
  const root = stretch(trim(largeGlyph(0x10)), h, 3);
  const rw = bw(root), w = rw + 1 + bw(rad);
  const out = blank(h, w);
  for (let y = 0; y < bh(root); y++)
    for (let x = 0; x < rw; x++) if (root.rows[y][x]) out[h - bh(root) + y][x] = 1;
  for (let y = 0; y < bh(rad); y++)
    for (let x = 0; x < bw(rad); x++) if (rad.rows[y][x]) out[2 + y][rw + 1 + x] = 1;
  for (let x = rw; x < w; x++) out[0][x] = 1;  // vinculum
  return { rows: out, baseline: (h >> 1) + 1 };
}

// Parentheses stretched to wrap a box (delimiter height follows content).
function parens(box) {
  const h = bh(box);
  const lp = stretch(trim(largeGlyph(0x28)), h, 3);
  const rp = stretch(trim(largeGlyph(0x29)), h, 3);
  return hcat([lp, box, rp], 1);
}

// Definite integral: tall ∫ with upper/lower limits, then ( body ) d var.
// lo/hi may be a string (rendered in the small font, like the OS) or a box.
function integral(lo, hi, body, varBox) {
  const inner = hcat([parens(body), text('d'), varBox || text('X')], 1);
  const limit = v => trim(typeof v === 'string' ? smallText(v) : v);
  const loB = limit(lo), hiB = limit(hi);
  // the ∫ spans the body plus the upper and lower limits stacked at its corners.
  // Lintegral 0x08 = top hook (rows 0-1), vertical stem (rows 2-4), bottom hook
  // (rows 5-6); repeat a stem row so the straight middle grows between the hooks.
  const symH = Math.max(bh(inner) + bh(hiB) + bh(loB), 11);
  const sign = stretch(trim(largeGlyph(0x08)), symH, 3);
  const rw = Math.max(bw(loB), bw(hiB));
  const h = bh(sign);
  const out = blank(h, bw(sign) + 1 + rw);
  for (let y = 0; y < h; y++)
    for (let x = 0; x < bw(sign); x++) if (sign.rows[y][x]) out[y][x] = 1;
  for (let y = 0; y < bh(hiB); y++)
    for (let x = 0; x < bw(hiB); x++) if (hiB.rows[y][x]) out[y][bw(sign) + 1 + x] = 1;
  for (let y = 0; y < bh(loB); y++)
    for (let x = 0; x < bw(loB); x++) if (loB.rows[y][x]) out[h - bh(loB) + y][bw(sign) + 1 + x] = 1;
  const signBox = { rows: out, baseline: h >> 1 };
  return hcat([signBox, inner], 1);
}

// ---- text runs ------------------------------------------------------------
// The OS draws raised/subscript content (exponents, integral limits) in the
// small variable-width font. SMALL tracks that mode so nested exponents and
// limits pick the right glyph table, the way the page-39 draw pass does.

let SMALL = false;
function glyphFor(code) { return SMALL ? smallGlyph(code) : largeGlyph(code); }

function text(s) { return hcat([...s].map(ch => glyphFor(ch.charCodeAt(0)))); }
function smallText(s) {
  const t = hcat([...s].map(ch => smallGlyph(ch.charCodeAt(0))));
  return t.rows.length ? t : largeGlyph(0x20);
}

// ---- expression parser (recursive descent) -------------------------------
// grammar: expr := add ; add := frac (('+'|'-') frac)* ;
//          frac := mul (('/') mul)* ; mul := pow (('*') pow | juxtaposition)* ;
//          pow  := atom ('^' atom)* ; atom := num | ident | '(' expr ')' | func

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
    while (peek() === '+' || peek() === '-') { guard(); const op = s[i++]; b = hcat([b, text(op), frac()]); }
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
        i++; b = hcat([b, text('/'), mul()]); start = i;
      } else break;
    }
    return b;
  }
  function mul() {
    let b = pow();
    for (;;) {
      guard();
      if (peek() === '*') { i++; b = hcat([b, text('*'), pow()]); }
      else if (isAtomStart(peek())) { b = hcat([b, pow()]); }   // implicit multiply
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
    if (eat('(')) { const b = expr(); eat(')'); return b; }
    if (/[0-9.]/.test(peek())) return text(number());
    if (/[A-Za-z]/.test(peek())) {
      const id = ident();
      if (peek() === '(') {
        if (id === 'int' || id === 'integral') return intCall();
        const args = call();
        if (id === 'sqrt' || id === 'root') return radical(args[0]);
        if (id === 'abs') return hcat([text('|'), args[0], text('|')]);
        // unknown function: name followed by its parenthesised args
        return hcat([text(id), parens(args[0] || text(''))]);
      }
      return text(id);
    }
    i++; return text('');  // skip stray char
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
  function limitArg() {
    const j = i;
    while (/[0-9.A-Za-z]/.test(peek())) i++;
    if (i > j && (s[i] === ',' || s[i] === ')')) return s.slice(j, i);  // simple -> string
    i = j; return expr();                                               // complex -> box
  }

  return expr();
}

// ---- canvas rendering -----------------------------------------------------

function draw(box, scale, color) {
  const canvas = document.getElementById('screen');
  const ctx = canvas.getContext('2d');
  const W = Math.max(bw(box), 1), H = Math.max(bh(box), 1);
  const pad = 4;
  canvas.width = (W + pad * 2) * scale;
  canvas.height = (H + pad * 2) * scale;
  ctx.fillStyle = color.bg;
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = color.fg;
  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++)
      if (box.rows[y][x]) ctx.fillRect((x + pad) * scale, (y + pad) * scale, scale, scale);
  document.getElementById('dims').textContent = `${W}×${H} px`;
}

const PRESETS = [
  ['linear 1/2', '1/2'],
  ['stacked 1//2', '1//2'],
  ['X squared', 'X^2'],
  ['(A+B)//C', '(A+B)//C'],
  ['nested fraction', '1//(2//3)'],
  ['radical', 'sqrt(X^2+1)'],
  ['definite integral', 'int(1,2,X^2,X)'],
  ['integral of a fraction', 'int(1,2,(1//2)X,X)'],
  ['radical of a fraction', 'sqrt((X^2+1)//X)'],
];

function render() {
  const src = document.getElementById('expr').value;
  const scale = +document.getElementById('scale').value;
  const lcd = document.getElementById('lcd').checked;
  const color = lcd ? { bg: '#c7d4b8', fg: '#2a3326' } : { bg: '#ffffff', fg: '#000000' };
  try {
    const box = parse(src);
    draw(box, scale, color);
    document.getElementById('err').textContent = '';
  } catch (e) {
    document.getElementById('err').textContent = String(e);
  }
}

async function main() {
  FONT = await (await fetch('font.json')).json();
  const bar = document.getElementById('presets');
  PRESETS.forEach(([label, src]) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.onclick = () => { document.getElementById('expr').value = src; render(); };
    bar.appendChild(b);
  });
  document.getElementById('expr').addEventListener('input', render);
  document.getElementById('scale').addEventListener('input', render);
  document.getElementById('lcd').addEventListener('change', render);
  document.getElementById('expr').value = 'int(1,2,(1/2)X,X)';
  render();
}

if (typeof document !== 'undefined') main();

// Node-side hook for tools/test-mathprint.js (headless layout verification).
if (typeof module !== 'undefined') {
  module.exports = {
    setFont: f => { FONT = f; },
    parse,
    toText: box => box.rows.map(r => r.map(c => (c ? '#' : '.')).join('')).join('\n'),
  };
}
