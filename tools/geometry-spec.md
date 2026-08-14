# MathPrint placement geometry

*TI-84 Plus OS 2.55MP — page `0x39` coordinate and placement formulas.*

This note gives byte-decoded pen and pixel formulas for the MathPrint layout
engine. Addresses use `pp:addr`; RAM addresses use bare hexadecimal notation. Unless marked
otherwise, the ROM-byte and control-flow claims below are [confirmed].

Read alongside `tools/cell-glyph-spec.md` (cell→glyph), `tools/token-name-spec.md`
(cell→string), and `docs/sub-equation-display.md` (architecture). Ghidra's
decompiler renders the tight register-passed loops at `39:683D` and `39:6B1C`
as decrement loops. The decoded bytes below determine the formulas.

---

## Coordinate systems

The engine uses two distinct pen models. Which one a glyph uses depends on its
blitter, not on the cell value.

| Pen vars | Meaning | Units | Used by |
|----------|---------|-------|---------|
| `0x844B` / `0x844C` | curRow / curCol | text cells (8-pixel rows and 6-pixel hardware columns) | large-font glyphs via `_PutMap` (`01:5A98`) |
| `0x86D7` / `0x86D8` | penX / penY | pixels | small/variable-width font via `_VPutMap` (`01:6293`); descriptor templates; fraction rules |

`0x86D7` is the low byte (penX), and `0x86D8` is the high byte (penY). The engine writes
the pair with `ld (086d7h),hl` or `ld (086d7h),de`, so L/E maps to penX and H/D maps to penY
(verified at `39:67C5`, `39:6A2A`, `39:6B2F`).

### curRow to penY

Every large-font row maps to pixels by `penY = curRow * 8`:

```z80
39:4F62  3a 4b 84   ld a,(0844bh)   ; curRow at 0x844B
         87 87 87   add a,a ×3      ; ×8
                    -> penY
35:60D1  3a 4b 84 / 87 87 87 / 32 d8 86   ; 0x844B * 8 -> 0x86D8
```

Large glyph rows are 8 pixels apart. `curCol` to penX conversion for the
hardware large font uses the LCD text-column register.

---

## Descriptor cell-to-pixel mapper

The bytes at `39:683D`–`39:685E` are:

```z80
683d  ed 5b e9 85   ld de,(085e9h)   ; E = base_x (085E9), D = base_y (085EA)
6841  ed 4b df 85   ld bc,(085dfh)   ; C = (085DF) "row", B = (085E0) "slot/col"
6845  7a            ld a,d           ; a = base_y
6846  05            dec b            ;  X-step loop counter = B
6847  fa 4e 68      jp m,0684eh      ;  exit when B underflows past 0
684a  c6 07         add a,007h       ;  += 7  per slot
684c  18 f8         jr 06846h
684e  57            ld d,a           ; D = base_y + 7*B
684f  21 eb 85      ld hl,085ebh     ; (085EB) = rowHeight
6852  7b            ld a,e           ; a = base_x
6853  0d            dec c            ;  loop counter = C
6854  fa 5c 68      jp m,0685ch
6857  86            add a,(hl)       ;  += rowHeight
6858  c6 02         add a,002h       ;  += 2
685a  18 f7         jr 06853h
685c  6f            ld l,a           ; L = base_x + (rowHeight+2)*C
685d  62            ld h,d           ; H = base_y + 7*B
685e  c9            ret
```

`dec`-then-`jp m` means the counter value `N` produces exactly `N` additions
(`N=0` → no add; underflow to `0xFF` sets the sign flag and exits).

`39:6A2A` stores `HL` directly into the pen pair:

```text
penX (0x86D7) = base_x + (rowHeight + 2) · (0x85DF)
penY (0x86D8) = base_y + 7 · (0x85E0)
```

The per-row X step is `rowHeight + 2`, and the per-slot Y step is `7`. The menu
grid is transposed: the slot counter advances Y, while the row counter advances
X. `add a,7` uses `B` from `0x85E0` for H/penY. `add a,(rowHeight)+2` uses `C`
from `0x85DF` for L/penX. [confirmed]

### Descriptor origins and row height

Loaded by the descriptor selector `eqdisp_compute_dims` `39:69C8` from the chosen
`EqDispTemplateDescriptor` (selected on `0x85E8 & 0x0F`):

```z80
6a00  cd e2 6b   call 06be2h        ; DE = WORD[desc+0] = base_yx (LE: E=x, D=y)
6a04  14         inc d              ; base_y += 1
6a05  1c 1c      inc e ; inc e      ; base_x += 2
6a07  ed 53 e9 85  ld (085e9h),de   ; (085E9)=base_x, (085EA)=base_y
...
6a13  7e         ld a,(hl)          ; desc+4 = row_height
6a14  32 eb 85   ld (085ebh),a      ; (085EB)=rowHeight
```

`39:6BE2` is `ld e,(hl); inc hl; ld d,(hl); inc hl; ret`, a little-endian
word read.

Each descriptor in `web/mathprint/layout.json` gives:

```text
base_x = (base_yx & 0xFF) + 2
base_y = (base_yx >> 8)   + 1
rowHeight = desc[+4]
```

| Descriptor | kind (`0x85E8 & 0x0F`) | base_yx | base_x | base_y | rowHeight | step_x=rh+2 | step_y=7 | cols×rows |
|------------|------|---------|--------|--------|-----------|------|----|---------|
| `39:686F` | 0 | `1801` | 3  | 25 | 6  | 8  | 7 | 4×1 |
| `39:6880` | 1 | `1115` | 23 | 18 | 6  | 8  | 7 | 5×1 |
| `39:6893` | (2-row) | `113A` | 60 | 18 | 8  | 10 | 7 | 5×2 |
| `39:689C` | (2-row,6col) | `0A3A` | 60 | 11 | 12 | 14 | 7 | 6×2 |
| `39:68A5` | (2-row,3col) | `1F3A` | 60 | 32 | 8  | 10 | 7 | 3×2 |

`base_yx`/`box_yx`/`cols_rows` are packed `(hi=y/col, lo=x/row)`; the
`box_yx`/`row_height`/`cols_rows`/`cell_ptr` fields follow at desc `+2/+4/+5/+7`
(see the `EqDispTemplateDescriptor` struct in `docs/sub-equation-display.md`).

The menu/template cell loop (`39:6A4C`–`39:6A89`) walks the `0x85E0` slot from
zero through `cols - 1`, then the `0x85DF` row from zero through `rows - 1`.
It calls `39:683D` for each cell and draws at the returned pen. [confirmed]

---

## Fraction box and focus-rectangle geometry

### Endpoint helper at `39:6B1C`

The bytes at `39:6B1C`–`39:6B2C` are:

```z80
6b1c  2e 07        ld l,007h        ; step = 7
6b1e  47           ld b,a           ; B = n (column count); A on entry = n
6b1f  3e 1b        ld a,01bh        ; a = 0x1B
6b21  85           add a,l          ;  += 7
6b22  10 fd        djnz 06b21h      ;  repeat n times -> a = 0x1B + 7n
6b24  6f           ld l,a           ; x_left  = 0x1B + 7n
6b25  c6 04        add a,004h
6b27  5f           ld e,a           ; x_right = x_left + 4
6b28  7c           ld a,h           ; H on entry = y_top
6b29  c6 06        add a,006h
6b2b  57           ld d,a           ; y_bottom = y_top + 6
6b2c  c9           ret
```

The helper computes: [confirmed]

```text
x_left   = 0x1B + 7·n
x_right  = x_left + 4
y_bottom = y_top + 6        (y_top supplied by the caller in H)
```

Caveat: `djnz` with `n=0` underflows (256 iterations); callers always pass `n ≥ 1`
(the measured numerator/denominator cell count).

### Box wrappers

`39:6AFD` (numerator/denominator box) sets the y-top per the focused row from
`0x85E0` bits and passes the measured width:

```z80
6b07  26 17   ld h,017h        ; numerator:   y_top = 0x17 (23)
6b09  3a ee 85 ld a,(085eeh)    ;   n = numerator cell count
6b0e  26 22   ld h,022h        ; denominator: y_top = 0x22 (34)
6b10  3a ef 85 ld a,(085efh)    ;   n = denominator cell count
```

`39:6ABF` sets y-top from the `0x85DF`/`0x85E0` row bits:

```z80
6ad0  26 15   ld h,015h        ; y_top = 0x15 (21)   (row bit0 clear)
6ad6  26 20   ld h,020h        ; y_top = 0x20 (32)   (row bit0 set)
6ad8  79 / 3c / cd 1c 6b       ; n = (085DF)+1 ; call 6B1C
```

So a fraction focus/box rectangle is, for measured width `n` cells:

```text
numerator box:    (x_left, 23) to (x_right, 23+6)   x_left=0x1B+7n, x_right=x_left+4
denominator box:  (x_left, 34) to (x_right, 34+6)
focus rect:       y_top ∈ {21, 32} by focused row; x as above with n=(0x85DF)+1
```

All callers of `39:6ABF` belong to the kind-2 fraction-template focus UI. Carry
selects erase versus draw through the rectangle-border bcalls. `39:6AF5` draws
descriptor and fraction-template boxes. Neither helper establishes the visible
bar in a generic expression. [confirmed]

---

## Multi-argument tall-operator compositor

`eqdisp_layout_multiarg` at `39:5167` implements multi-row argument placement
when selected. The filled-integral and nested-fraction trace fixtures execute
the separate subexpression path at `39:4CA4`; neither reaches this entry.
[confirmed]

### Row advance per argument

The bytes at `39:5949`–`39:5954` are:

```z80
5949  3a de 85   ld a,(085deh)    ; current layout class
594c  fe 06      cp 006h
594e  c0         ret nz           ; class != 6  -> return NZ
594f  3e 02      ld a,002h
5951  be         cp (hl)          ; HL = 085E0 (slot index); compare 2 vs slot
5952  d8         ret c            ; slot > 2  -> return NZ (carry)
5953  97         sub a            ; a = 0 (Z set)
5954  c9         ret              ; class==6 && slot<=2 -> return Z
```

`39:5949` returns Z only when the class is `0x06` and the current slot at
`0x85E0` is at most 2. It returns NZ otherwise. [confirmed]

In `39:5167` the returned flag selects the cursor-row (`0x844B`) step:

```z80
51d5  21 4b 84   ld hl,0844bh
51d8  f1         pop af            ; the saved 5949 result
51d9  20 01      jr nz,051dch      ; NZ: skip the extra inc
51db  34         inc (hl)          ; (only when Z)  -> +1
51dc  34         inc (hl)          ;                -> +1
```

The row step is `0x844B += 1` normally and `0x844B += 2` when `39:5949` returns
Z. Class 6 therefore gives its low slots two display rows. [confirmed]

The overflow boundary depends on that step. The forward two-row branch compares
`0x844B` with 6 at `39:5181`, while the ordinary branch compares it with 7 at
`39:5191`. A class-`0x06` low slot therefore falls back to `39:4C5A` from row 6
or 7. This jump occurs before the `IY+0x11` bit-5 styled-record test at
`39:5195`. [confirmed]

The reverse path decrements `0x85E0` at `39:523B` before calling `39:5949`.
For a two-row result, rows below 3 jump to `39:4C5A` at `39:5246`. Otherwise,
`39:524C` selects in-row placement only when `0x844B` is greater than the saved
baseline at `0x984A`. Equality and borrow enter the overflow path. The styled
test at `39:5251` follows both predicates. [confirmed]

### Action controllers

Action `0x03` at `39:51F1` sends nonzero `0x85E0` values to the reverse
walker. At index zero, `(IY+1Dh).0` can return through `39:5447`. Otherwise,
counts below 8 enter the do-while loop at `39:50A1`. Its byte counter makes
`count` calls to `39:5167` for counts 1–7 and 256 calls for count zero. Counts
of at least 8 select these byte-sized values before emitting the highlighted
final argument at row 7:

```text
final_argument     = count - 1
first_visible_slot = (count - 8 + baseline_row) & 0xFF
pre_call_row       = (baseline_row - 1) & 0xFF
```

Action `0x04` at `39:52A5` computes this byte difference once:

```text
delta = ((count - 1) - argument_index) & 0xFF
```

A nonzero delta calls `39:5167` once. That walker returns through `39:5447`.
`39:52B6` then jumps to `39:52A2` and enters the same row-token tail again; it
does not recompute the difference. A zero delta tests `(IY+1Dh).0`. The set-bit
path uses the same tail. On the clear-bit path, `A=0` reaches `39:513E` and
selects argument zero. [confirmed]

### Slot-to-baseline placement

State used by `39:5167`:

- `0x85E0` is the current argument slot: integrand, variable, lower endpoint,
  upper endpoint, then tolerance.
- `0x85E2` is the argument count, and `0x85E1` is the handler row count.
- `0x984A` is the baseline row saved around operand emission.
- `0x844B` is curRow. `39:522C` resets it to 7, with curCol at zero, before
  re-emitting the body.

For each argument, the routine:

1. Calls `39:5949` to select a one- or two-row step and apply it to `0x844B`.
2. Calls `39:4E0A` to mark the slot and set `0x844C` to zero, with `C = 0x85E0`.
3. `39:5B10` emits forward, while `39:5B1D`/`39:5B38` emit in reverse.
4. `39:4E14`/`39:4E0A` advance and mark the next argument.

Styled overflow saves `0x97A5`, writes 1, calls `39:3C81` while moving forward
or `39:3C93` while moving backward, and restores `0x97A5`. Carry from
`39:5B2B` or `39:5B38` skips that scroll sequence. [confirmed]

The bytes restore the baseline at `0x984A` and reset `0x844B` to row 7 at
`39:522C` before re-emitting the body. No retained exact trace connects this
path to the filled-integral fixtures. [confirmed]

---

## Per-glyph horizontal advance

### Small variable-width font

penX is a true pixel coordinate. `01:6293` reads `0x86D7` as penX, converts to the
LCD column register by `penX >> 3` (`or 0x20`) with the low three bits as the bit
offset, draws the glyph, then writes back `0x86D7 = penX + glyph_width`
(`01:6315  32 d7 86  ld (086d7h),a`, where `a = penX + measured width`). Likewise,
penY reads `0x86D8` directly at `01:62B5`. Small-font advance is the measured
ink width (variable). This path renders exponents, integral/Σ limits, and the
fraction numerator/denominator digits.

### Post-overflow display helper

The bytes at `39:4F04` are `EF F4 51 C9`: bcall ID `51F4h`, followed by `RET`.
The page `0x3B` bcall table resolves it to `35:60D1`. That target uses
fixed graph-pen positions and page `0x01` display helpers; the byte-anchored
scan finds no references to the measured fraction fields `0x85EE`, `0x85EF`,
or `0x9D27`. It is therefore a post-overflow display/menu helper, not evidence
for a proportional MathPrint glyph-width service. [confirmed]

The `C9` byte after the bcall is a `RET`. The owner of MathPrint body-glyph
advance remains [hypothesis].

### Classic hardware large font

When a large glyph instead goes through `_PutMap` (the homescreen text writer),
positioning uses the hardware text grid rather than pixel penX:

```z80
01:5AC2  ld a,(0844bh) ; curRow -> Y via 01:6956
01:5ACB  ld a,(0844ch) ; curCol
         e6 1f         ; & 0x1F
         c6 20         ; + 0x20   -> LCD column register (out (010h))
```

curCol selects a fixed 6-pixel hardware text column (`column reg = (curCol &
0x1F) + 0x20`). This is the fixed-pitch path. The owner of MathPrint body
advance is still unresolved.

---

## Placement formulas

```text
penY (large font)            = curRow(0x844B) · 8

Descriptor template cell:    penX = base_x + (rowHeight+2)·(0x85DF)
  (39:683D, menus/templates) penY = base_y + 7·(0x85E0)
  base_x = desc.base_yx_lo + 2,  base_y = desc.base_yx_hi + 1,  rowHeight = desc[+4]

Fraction endpoint (39:6B1C): x_left  = 0x1B + 7·n      (n = measured width in cells)
                             x_right = x_left + 4
                             y_bottom= y_top + 6
  numerator   y_top = 0x17 (23), n = (0x85EE)
  denominator y_top = 0x22 (34), n = (0x85EF)
  focus rect  y_top ∈ {0x15(21), 0x20(32)}, n = (0x85DF)+1

Multi-arg row step (39:5167/5949): 0x844B += 2 if (class==6 && slot<=2) else += 1
  body re-emit resets curRow=7 (0x844B), curCol=0 (0x844C)  at 39:522C

Body glyph advance:
  small/variable font (_VPutMap 01:6293): penX += measured glyph width
  MathPrint body glyph advance:            not statically attributed here
  classic hardware (_PutMap 01:5A98):     LCD col reg = (curCol & 0x1F) + 0x20  (6-px pitch)
```

---

## Open questions

- Body-glyph advance remains [hypothesis]. Bcall ID `51F4h` does not identify
  the routine that owns each advance.
- The runtime selector for `39:5167` remains [hypothesis]. The retained filled
  and nested-integral traces use `39:4CA4` instead.
