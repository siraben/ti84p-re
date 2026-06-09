# TI-84 Plus OS 2.55MP — page-0x39 MathPrint placement geometry

Exact pen/pixel placement formulas for the MathPrint layout engine, derived from
**raw** z80dasm of flash page `0x39` (and the leaf blitters on pages `01`/`07`).
Addresses are `page:offset`; raw bytes are quoted from `tools/rom.bin`
(flash page `P` at file offset `P*0x4000`, logical window `0x4000..0x7FFF`).

Read alongside `tools/cell-glyph-spec.md` (cell→glyph), `tools/token-name-spec.md`
(cell→string), and `docs/sub-equation-display.md` (architecture). **The Ghidra
decompiler mis-analyzes the tight register-passing routines here (`683D`, `6B1C`)
as bare decrement loops — every formula below is from the bytes, not the
decompiler.**

---

## 0. The two coordinate systems

The engine uses two distinct pen models. Which one a glyph uses depends on its
blitter, not on the cell value.

| Pen vars | Meaning | Units | Used by |
|----------|---------|-------|---------|
| `0x844B` / `0x844C` | curRow / curCol | **text cells** (rows of 8 px; cols are hardware 6-px text columns) | large-font glyphs via `_PutMap` (`01:5A98`) |
| `0x86D7` / `0x86D8` | penX / penY | **pixels** (penX = `86D7`, penY = `86D8`) | small/variable-width font via `_VPutMap` (`01:6293`); descriptor templates; fraction rules |

`0x86D7` is the low byte (penX), `0x86D8` the high byte (penY); the engine writes
the pair with `ld (086d7h),hl` / `ld (086d7h),de` so **L/E → penX, H/D → penY**
(verified at `39:67C5`, `39:6A2A`, `39:6B2F`).

### 0.1 curRow → penY (the universal large-font vertical rule)

Every large-font row maps to pixels by **penY = curRow × 8**:

```
39:4F62  3a 4b 84   ld a,(0844bh)   ; curRow
         87 87 87   add a,a ×3      ; ×8
                    -> penY
35:60D1  3a 4b 84 / 87 87 87 / 32 d8 86   ; (0844b)*8 -> (086d8h)  (same rule in the glyph composite drawer)
```

So row spacing for large glyphs is a fixed **8 px**. (`curCol`→penX for the
hardware large font is the LCD text-column register; see §5.)

---

## 1. Descriptor cell → pixel mapper `39:683D`

Raw (`39:683D..685E`):
```
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

**Result (HL stored straight into the pen pair at `39:6A2A`):**

```
penX (086D7) = base_x + (rowHeight + 2) · (085DF)
penY (086D8) = base_y + 7 · (085E0)
```

i.e. the **per-row X step is `rowHeight + 2`** and the **per-slot/col Y step is
`7`**. (Note the engine drives a *transposed* menu grid here: the slot/column
counter advances Y by 7, the row counter advances X by `rowHeight+2`. The bytes
are unambiguous — `add a,7` uses the `B`=`085E0` counter into the H/penY byte,
`add a,(rowHeight)+2` uses the `C`=`085DF` counter into the L/penX byte.)

### 1.1 Where base_x / base_y / rowHeight come from

Loaded by the descriptor selector `eqdisp_compute_dims` `39:69C8` from the chosen
`EqDispTemplateDescriptor` (selected on `0x85E8 & 0x0F`):

```
6a00  cd e2 6b   call 06be2h        ; DE = WORD[desc+0] = base_yx (LE: E=x, D=y)
6a04  14         inc d              ; base_y += 1
6a05  1c 1c      inc e ; inc e      ; base_x += 2
6a07  ed 53 e9 85  ld (085e9h),de   ; (085E9)=base_x, (085EA)=base_y
...
6a13  7e         ld a,(hl)          ; desc+4 = row_height
6a14  32 eb 85   ld (085ebh),a      ; (085EB)=rowHeight
```

(`6BE2` = `ld e,(hl);inc hl;ld d,(hl);inc hl;ret`, a plain LE word read.)

So for **each descriptor** (raw words from `web/mathprint/layout.json`):

```
base_x = (base_yx & 0xFF) + 2
base_y = (base_yx >> 8)   + 1
rowHeight = desc[+4]
```

| Descriptor | kind (`85E8&0F`) | base_yx | base_x | base_y | rowHeight | step_x=rh+2 | step_y=7 | cols×rows |
|------------|------|---------|--------|--------|-----------|------|----|---------|
| `39:686F` | 0 | `1801` | 3  | 25 | 6  | 8  | 7 | 4×1 |
| `39:6880` | 1 | `1115` | 23 | 18 | 6  | 8  | 7 | 5×1 |
| `39:6893` | (2-row) | `113A` | 60 | 18 | 8  | 10 | 7 | 5×2 |
| `39:689C` | (2-row,6col) | `0A3A` | 60 | 11 | 12 | 14 | 7 | 6×2 |
| `39:68A5` | (2-row,3col) | `1F3A` | 60 | 32 | 8  | 10 | 7 | 3×2 |

`base_yx`/`box_yx`/`cols_rows` are packed `(hi=y/col, lo=x/row)`; the
`box_yx`/`row_height`/`cols_rows`/`cell_ptr` fields follow at desc `+2/+4/+5/+7`
(see the `EqDispTemplateDescriptor` struct in `docs/sub-equation-display.md`).

The menu/template cell loop (`39:6A4C..6A89`) walks slot=`085E0` 0..cols-1 then
row=`085DF` 0..rows-1, calling `683D` per cell and drawing at the returned pen.

---

## 2. Fraction box / focus-rectangle geometry

### 2.1 Endpoint helper `39:6B1C`

Raw (`39:6B1C..6B2C`):
```
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

**Confirmed:**
```
x_left   = 0x1B + 7·n
x_right  = x_left + 4
y_bottom = y_top + 6        (y_top supplied by the caller in H)
```

Caveat: `djnz` with `n=0` underflows (256 iterations); callers always pass `n ≥ 1`
(the measured numerator/denominator cell count).

### 2.2 Box wrappers (callers of `6B1C`)

`39:6AFD` (numerator/denominator box) sets the y-top per the focused row from
`085E0` bits and passes the measured width:
```
6b07  26 17   ld h,017h        ; numerator:   y_top = 0x17 (23)
6b09  3a ee 85 ld a,(085eeh)    ;   n = numerator cell count
6b0e  26 22   ld h,022h        ; denominator: y_top = 0x22 (34)
6b10  3a ef 85 ld a,(085efh)    ;   n = denominator cell count
```

`39:6ABF` (focus rectangle) sets y-top from the `085DF`/`085E0` row bits:
```
6ad0  26 15   ld h,015h        ; y_top = 0x15 (21)   (row bit0 clear)
6ad6  26 20   ld h,020h        ; y_top = 0x20 (32)   (row bit0 set)
6ad8  79 / 3c / cd 1c 6b       ; n = (085DF)+1 ; call 6B1C
```

So a fraction focus/box rectangle is, for measured width `n` cells:

```
numerator box:    (x_left, 23) .. (x_right, 23+6)   x_left=0x1B+7n, x_right=x_left+4
denominator box:  (x_left, 34) .. (x_right, 34+6)
focus rect:       y_top ∈ {21, 32} by focused row; x as above with n=(085DF)+1
```

The visible **fraction bar** in a generic expression is a graph-buffer rule drawn
by `eqdisp_draw_fraction_bar` `39:6ABF`→`00:3555` (a horizontal line), not a
character cell; its endpoints are the same `x_left..x_right` span. The box-draw
primitive is `39:6AF5` → `04822h/04833h` (rectangle fill/outline).

---

## 3. Multi-argument tall-operator compositor `39:5167`
(`eqdisp_layout_multiarg` — ∫, Σ-style operators with limits + body)

### 3.1 Row advance per argument — `39:5949`

Raw (`39:5949..5954`):
```
5949  3a de 85   ld a,(085deh)    ; current layout class
594c  fe 06      cp 006h
594e  c0         ret nz           ; class != 6  -> return NZ
594f  3e 02      ld a,002h
5951  be         cp (hl)          ; HL = 085E0 (slot index); compare 2 vs slot
5952  d8         ret c            ; slot > 2  -> return NZ (carry)
5953  97         sub a            ; a = 0 (Z set)
5954  c9         ret              ; class==6 && slot<=2 -> return Z
```

`5949` returns **Z** only when the class is `0x06` *and* the current slot
(`085E0`) is ≤ 2; otherwise **NZ**.

In `39:5167` the returned flag selects the cursor-row (`0x844B`) step:
```
51d5  21 4b 84   ld hl,0844bh
51d8  f1         pop af            ; the saved 5949 result
51d9  20 01      jr nz,051dch      ; NZ: skip the extra inc
51db  34         inc (hl)          ; (only when Z)  -> +1
51dc  34         inc (hl)          ;                -> +1
```

**Row step rule:** `0x844B += 1` normally; `0x844B += 2` when `5949` returned Z
(class 6, low slots) — i.e. a two-display-row argument. This is the "+1 or +2"
the architecture note describes.

### 3.2 Slot → row/baseline placement

State used by `5167`:
- `085E0` = current argument slot (parser order: integrand, var, lower, upper, tol).
- `085E2` = argument count; `085E1` = handler row count.
- `0984A` = baseline row (saved/restored around operand emission).
- `0844B` = curRow; reset to **7** at the drain (`522C  21 07 00  ld hl,0007 ; ld (0844bh),hl` → curRow=7, curCol=0) before re-emitting the body.

Per-argument the routine:
1. `call 5949` → decide +1/+2 row step (§3.1), apply to `0844B`.
2. `call 4E0A` (slot marker; sets `curCol=0`, `(0844C)=0`) with `C = 085E0`.
3. Emit the saved operand via `5B10` (forward) or `5B1D`/`5B38` (reverse).
4. `4E14` / `4E0A` advance the argument index and re-mark.

The operator-sign glyph (the `∫`/`Σ` cell) is emitted on the **baseline** axis
(`0984A`), the limits on the rows above/below it (the +1/+2 stepped rows), and the
body is re-emitted after `0844B` is reset to row 7 (`522C`) — i.e. the body
starts on the baseline immediately to the right of the sign+limits block, at the
penX left after the limits have been drawn.

### 3.3 Limit small-font placement

Limits are drawn in the **variable-width small font** (`_VPutMap` `01:6293`) at
explicit pixel pen coords (`086D7`/`086D8`), *not* at curRow×8. From the live
trace of `int(1,2,1/2,X)`:

```
upper limit  penX=6  penY=0
lower limit  penX=6  penY=18
```

So for the ∫ form the limits sit at the operator's **corners** (`penX≈6`, the
upper at `penY=0`, the lower at `penY=18`); the sign occupies the rows between.
(For a Σ form the limits are stacked **centered** over/under the sign rather than
at the corners — same small-font pen path, different x centering.)

---

## 4. Per-glyph horizontal advance (body)

### 4.1 Small / variable-width font (`_VPutMap`, `01:6293`)

penX is a true pixel coordinate. `01:6293` reads `086D7` as penX, converts to the
LCD column register by `penX >> 3` (`or 0x20`) with the low 3 bits as the bit
offset, draws the glyph, then writes back **`086D7 = penX + glyph_width`**
(`6315  32 d7 86  ld (086d7h),a`, where `a = penX + measured width`). Likewise
penY = `086D8` directly (`62B5`). So small-font advance = the glyph's measured
ink width (variable). This path renders exponents, integral/Σ limits, and the
fraction numerator/denominator digits.

### 4.2 Large font — proportional MathPrint glyphs

The structural body glyphs are emitted through the cell path `39:4E8E` →
(`4F1A` NC) → **`bcall 0xC951`** at `39:4F04` (raw `ef 51 c9` = `rst 28h`,
ID `0xC951`). `0xC951` has bit 15 set, so its dispatcher entry is read from the
**RAM-resident** relocated bcall table (`res 7,d` → `0x4951`, page forced 0x7F);
its flash body cannot be read statically (same situation as `0xC945`, the
token-name drawer — see `tools/token-name-spec.md §1`). This is the proportional
large-glyph drawer that advances penX by each glyph's rendered width.

Its advance rule is pinned by the live trace of `int(1,2,X^2,X)` body:

```
glyph   penX   advance
  (      16      —
  X      24     +8   (open-paren is the wide cell)
  )      30     +6
  d      36     +6
  X      42     +6
```

**Rule:** large-font body glyphs advance penX by their **proportional width**:
≈ **6 px** for ordinary glyphs (digits, letters, `d`, `)`), and **8 px** for the
wider parenthesis/operator cells. penY is the baseline `curRow × 8` (§0.1). The
6-px nominal stride is the large font's standard advance; the parenthesis cell is
2 px wider.

### 4.3 The classic hardware large font (`_PutMap`, `01:5A98`)

When a large glyph instead goes through `_PutMap` (the homescreen text writer),
positioning is by the **hardware text grid**, not pixel penX:
```
01:5AC2  ld a,(0844bh) ; curRow -> Y via 01:6956
01:5ACB  ld a,(0844ch) ; curCol
         e6 1f         ; & 0x1F
         c6 20         ; + 0x20   -> LCD column register (out (010h))
```
i.e. curCol selects a fixed 6-px hardware text column (`column reg = (curCol &
0x1F) + 0x20`). This is the fixed-pitch path; the proportional MathPrint body uses
§4.2 instead.

---

## 5. Summary of placement formulas

```
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

Integral (∫) limits (small font, 39:5167 + _VPutMap):
  upper  penX≈6, penY=0     ; lower penX≈6, penY=18   (operator corners)
  sign on baseline rows between; body starts right of the sign+limits block.
Summation (Σ) limits: stacked & centered over/under the sign (same small-font pen).

Body glyph advance:
  small/variable font (_VPutMap 01:6293): penX += measured glyph width
  large proportional (bcall 0xC951):      penX += ~6 px (parens/wide ops ~8 px)
  classic hardware (_PutMap 01:5A98):     LCD col reg = (curCol & 0x1F) + 0x20  (6-px pitch)
```

---

## 6. Flagged / unresolved

- **Proportional large-glyph widths are not statically derivable.** The body
  drawer `bcall 0xC951` (and the token-name drawer `0xC945`) live in the
  RAM-resident relocated bcall table (bit-15 IDs); their flash bodies cannot be
  read from the ROM. The ≈6 px / 8 px advances in §4.2 are pinned by the live
  pen-coordinate trace, not by reading the width table.
- **Σ vs ∫ limit centering.** `39:5167` selects the operator template, but the
  exact x-centering offset for the stacked Σ limits (vs ∫ corner limits) is set in
  the slot-marker/operand emitters (`4E0A`, `5B10`/`5B1D`) using the measured limit
  width; the precise centering arithmetic was not isolated to a single constant.
- **The `683D` grid is transposed** relative to the `docs/sub-equation-display.md`
  prose (`x = base_x + 7·col`). The bytes put the 7-step into **penY** (via the
  `0x85E0` slot counter) and the `rowHeight+2` step into **penX** (via the
  `0x85DF` row counter). The formula in §1 is the byte-accurate one; this only
  governs the **descriptor menu/template** grids, not the main expression body
  (which uses §3/§4).
- `0x85DF`/`0x85E0` role names ("row"/"slot") follow the architecture doc field
  map; the mapper consumes them positionally as above regardless of name.
