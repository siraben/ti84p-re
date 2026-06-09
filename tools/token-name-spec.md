# TI-84 Plus OS 2.55MP — token → drawn-string spec (MathPrint name path)

How the page-0x39 MathPrint engine turns a *token-name* cell into the exact
glyph/character sequence it typesets. This resolves the two gaps flagged in
`tools/cell-glyph-spec.md`:

  1. the page-01 generic token-name drawer's name source, and
  2. the recursive resolution of the FE/FC/FB-expanded 2-byte tokens.

Addresses are `page:offset`; raw bytes are from `tools/rom.bin` (flash page P at
file offset `P*0x4000`, logical window `0x4000..0x7FFF`). Strings are shown ASCII
where printable, `\xNN` otherwise.

---

## 0. Summary (definitive)

* The MathPrint name source is the **standard OS token-name table**, *not* a
  separate MathPrint table. The resolver is `_Get_Tok_Strng` / `_GETTOKSTRING`
  (`01:66EA` → `01:6702`), the same routine every OS subsystem uses.
* A token name is found by a two-level lookup on **page 01**:
  a *lead-byte* selects a **WORD pointer table**; the *second byte* indexes it;
  the WORD points at a record `[displaybyte][len][name…]`.
* The 1-byte (`D=0x00`) family table is at **`01:0x4252`**. The cell's `E`
  is a **display byte** and is first mapped to an internal token via the
  page-07 table at **`07:0x4000`** (`tok = byte[07:0x4000 + (E−0x5A)]` for
  `E≥0x5A`, else `tok = E`). That `07:0x4000` table and the `01:0x4252` record
  *displaybytes* are mutual inverses (verified across all 256 entries).

---

## 1. Tracing 39:6B66 → bcall 0xC945

`39:6B66` (raw, leading bytes):
```
26 01            ld h,1
7a fe fb 20 2f   ld a,d ; cp 0FBh ; jr nz ->6B9C     ; D!=0xFB: generic path
...              (FB-special inline strings, cell-glyph-spec §6)
6B9C: ef 45 c9   rst 28h ; .dw 0C945h                 ; bcall 0xC945
6BA0: 11 f2 97   ld de,097F2h
6BA3: d5 cd 2b 19 push de ; call 0192Bh ; pop hl ; ret
```

The 3 bytes at `6B9C` are `EF 45 C9` = **`rst 28h` (the bcall trampoline)
followed by the 16-bit bcall ID `0xC945`** (little-endian `45 C9`).
z80dasm mis-renders `ca 45 c9` as a `jp` — it is data, the bcall ID.

`rst 28h` → `0x0028: jp 02A2Fh`, the bcall dispatcher. For an ID with bit 15
set (`0xC945`, D=0xC9) the dispatcher does `res 7,d` (→ `0x4945`), forces the
page to `0x7F`, then reads its jump-table entry at `0x4000 + 0x4945 = 0x8945`
— i.e. **out of flash, in the RAM-resident relocated bcall table**
(`02A56..02A73`). So `0xC945`'s flash target cannot be read statically; it is
the RAM copy of the OS token-name drawer.

**Resolution (verified functionally, not by chasing RAM):** `0xC945` draws the
same string that `_Get_Tok_Strng` (`bcall 0x4594` → `01:66EA`) produces, with
the cell's `D:E` taken as the token. Every observed cell name matches that
routine's output exactly (§4). The drawer is `01:6702` and its name source is
the table described below.

---

## 2. The name resolver `01:6702` (input DE = token, output HL = `[len][name]`)

Raw control flow (`01:6702..01:6789`, decoded from bytes; all conditional
branches merge at `01:6782`):

```
6702: ld l,e ; ld h,0 ; ld a,d ; or a ; jr z ->677F   ; D==0 : 1-byte table 0x4252
      (D!=0) select WORD-pointer base by lead byte D:
        D < 0x5D            -> de = 4452h   (matrix [A]…[J])
        D == 0x5D           -> de = 4466h   (lists  L1…)
        D == 0x5E / 0x5F    -> de = 4472h, then E-bit remap:
                                  bit4(E) -> 4486h (res4 E)
                                  bit5(E) -> 449Eh (res5 E)
                                  else    -> 44AAh (res6,res7 E)   (equation vars)
        D == 0x60           -> de = 44B0h   (Pic1…)
        D == 0x61           -> de = 44C4h   (GDB1…)
        D == 0x62           -> de = 44ECh   (stat/regression vars)
        D == 0x63           -> de = 4566h   (window & system vars)
        D == 0x7E           -> de = 45D6h   (graph-format / mode tokens)
        0x64 <= D < 0xBB    -> de = 44D8h   (string vars; includes lead 0xAA)
        D == 0xBB           -> de = 45FCh   (extended 2-byte commands;
                                             E clamped to 0xF6)
        D >  0xBB           -> de = 47E8h   (TI-84+ extended: 0xEF date/time…)
6782: add hl,hl ; add hl,de ; ld e,(hl) ; inc hl ; ld d,(hl) ; ex de,hl
                                ;  hl = WORD[ base + 2*E ]  = record pointer
6788: bit 0,(iy+035h) ; jr z ->67B8                ; language toggle (off by default)
67B8: inc hl ; ret                                 ; skip [displaybyte], hl -> [len][name]
```

`01:66EA` (`_Get_Tok_Strng`) then: `ld a,(hl)` = `len`, `inc hl`, copy `len`
name bytes (to `0848Eh`). So the **record format is
`[displaybyte] [len] [name bytes…]`** and the name = `[len][name]` at
`record+1`.

### 2.1 The 1-byte (D=0x00) family — `01:0x4252`

`WORD[0x4252 + 2*token]` → record. The token here is **not** the cell's `E`;
it is the *internal token number*. The cell `00:E` carries a **display byte**
`E`, mapped first via the page-07 table at `07:0x4000`:

```
tok = byte[ 07:0x4000 + (E − 0x5A) ]      for E >= 0x5A
tok = E                                     for E <  0x5A   (digits/letters)
```

Verified inverse: e.g. `07:0x4000[0xC8−0x5A] = 0x24`, and `01:0x4252[0x24]`'s
record begins `C8 06 'fnInt('` — displaybyte `0xC8`, name `fnInt(`. Across all
256 internal tokens the record's displaybyte equals the page-07 inverse.

This is the same `07:0x4000` "default" table reproduced in
`cell-glyph-spec.md §3a` (there read as display→glyph; it is simultaneously
display→internal-token, because token number and large-font glyph index
coincide for these entries).

---

## 3. The FE/FC/FB cells are *not* names

Page-39 cells whose lead byte is `0xFE / 0xFC / 0xFB` do **not** reach the
token-name drawer as a 2-byte token (FE/FC/FB are not valid lead bytes for
`01:6702`). Per `cell-glyph-spec.md §1.1/§2/§5/§6` they are:

* **single large-font glyphs** via `39:4F1A` — `FC3C..FC40 → glyph 5..9`,
  `FE7D..FE81 → glyph 0..4`, `xx42 (D<0x0A) → glyph D`; or
* **2-D template operators** (∑ ∏ ∫ …) drawn from the styled sub-tables keyed
  by `E→(08446h)` (§5 lists `FC00/FC01/FC02/FC1F…`, `FEA7..FC2C`, `FC50..FC59`);
  or
* **FB-special inline ASCII strings** (§6, e.g. `FBCA → "nΣd"`).

The page-07 §3c–§3e word tables (`07:0x4102 / 0x422C / 0x4426`) belong to the
**classic editor** classifier `07:44DE` (indexed by RAM `0844Bh`/`08446h`), not
to the page-39 cell stream; their `(lead,second)` outputs *are* real 2-byte
tokens (lead bytes `5C 5D 5E 60 61 62 63 7E AA BB EF`) which, when they do
occur, resolve through the §2 multi-table above. They are **not** indexed by a
page-39 cell's raw `E`.

---

## 4. Dumped MathPrint operator tokens → drawn strings

### 4.1 `00:E` operator/function cells (class 0x08 / 0x0D and canonical ops)

`E` = display byte; `tok` = `07:0x4000` remap; pointer is into `01:0x4252`'s
records (name shown is the `[len][name]` payload).

| cell `00:E` | E | tok | record ptr | drawn string |
|---|---|---|---|---|
| `00C3` | C3 | 03 | 01:487A | `\x05Frac`  (►Frac) |
| `00C4` | C4 | FB | 01:51FD | `ClrTable` |
| `00C6` | C6 | 3E | 01:4981 | `:` |
| `00C7` | C7 | 25 | 01:4929 | `nDeriv(` |
| `00C8` | C8 | 24 | 01:4921 | `fnInt(` |
| `00C9` | C9 | 22 | 01:4913 | `solve(` |
| `00CA` | CA | AF | 01:4BFE | `\x3F`  (? glyph) |
| `00CB` | CB | 2A | 01:4935 | `"` |
| `00CC` | CC | 5B | 01:49D9 | `[` |
| `00EC` | EC | 08 | 01:488A | `{` |
| `00ED` | ED | 09 | 01:488D | `}` |
| `00EE` | EE | 2C | 01:5207 | `\xD7`  (× / list-mark) |
| `00F1` | F1 | 27 | 01:51EF | `fMin(` |
| `00F2` | F2 | 28 | 01:51F6 | `fMax(` |
| `00F3` | F3 | A8 | 01:4BD7 | `DrawInv ` |
| `00F5` | F5 | A1 | 01:4B8F | `Pxl-On(` |
| `00F6` | F6 | A2 | 01:4B98 | `Pxl-Off(` |
| `0042` | 42 | 42 | 01:498E | `B` |
| `0054` | 54 | 54 | 01:49C4 | `T` |

(The class-0x08/0x0D cells that are not in this table are `xx42` digit glyphs,
`FC3C..FC40` / `FE7D..FE81` digit glyphs, `FF3D` terminator, or FE/FC/FB styled
2-D operators — see §3.)

### 4.2 2-byte token families (when a real `lead:E` token appears)

Resolved by the §2 multi-table (faithful simulation of `01:6702`):

| token | family (base) | drawn string |
|---|---|---|
| `5C00` | matrix (01:4452) | `\xC1A]`  ([A]) |
| `5D00` | list (01:4466) | `L\x81`  (L₁) |
| `5E00` | equation var (01:44AA) | `u` |
| `6000` | Pic (01:44B0) | `Pic1` |
| `6100` | GDB (01:44C4) | `GDB1` |
| `6300` | window var (01:4566) | `ZXscl` |
| `7E00` | graph-format (01:45D6) | `Sequential` |
| `AA00` | string (01:44D8) | `Str1` |
| `BB25` | extended cmd (01:45FC) | `conj(` |
| `BB0A` | extended cmd (01:45FC) | `randInt(` |
| `EF00` | TI-84+ ext (01:47E8) | `setDate(` |
| `EF09` | TI-84+ ext (01:47E8) | `getDate` |

---

## 5. Cross-check vs `tools/ti83plus.inc` and `docs/token-tables.md`

* `ti83plus.inc`: `_Get_Tok_Strng equ 4594h` ("input: hl=ptr to token; output:
  op3=string, a=length") and `_GETTOKSTRING equ 4597h` ("DE=token; HL=ptr to
  string on page 1") name exactly the routine traced here (`01:66EA`/`01:6702`,
  page 01). The MathPrint drawer `0xC945` is the RAM-resident alias of this same
  page-01 token-name path.
* `tools/gen-token-tables.py` (generator for `docs/token-tables.md`) enumerates
  the 2-byte lead bytes `$5C $5D $5E $60 $61 $62 $63 $7E $AA $BB $EF` — an
  **exact match** to the lead-byte dispatch decoded from `01:6702` (§2). The
  resolved names (`conj(`, `Str1`, `Pic1`, `setDate(`, …) match the standard TI
  token names.

**Definitive:** the MathPrint name source is the **same standard OS token-name
table** used by the rest of the OS — there is no separate MathPrint name table.
MathPrint only adds (a) the display-byte→token remap via `07:0x4000` for the
`00:E` 1-byte cells, and (b) the FB-special inline strings / styled-operator
templates that bypass the name path entirely (§3).

---

## 6. Flagged / partially resolved

* **`0xC945` flash target not statically resolvable.** Its dispatcher entry is
  read from the RAM-resident bcall table at `0x8945` (bit-15 path,
  `02A56..02A73`). Identity with `01:6702` is established functionally (every
  dumped cell name matches) and by the `ti83plus.inc` `_GETTOKSTRING` semantics,
  not by reading the RAM table.
* **`(iy+035h) bit 0`** is a language/localization toggle in `01:6788`. With it
  set, an alternate (localized) name path runs (`67A7: ld hl,0546h …
  call 03BA3h`); the dumps here assume the default (bit clear → English).
* **`5E/5F` equation-var E-bit remap** (`01:671C..0173A`) was decoded and
  simulated (`5E00→"u"`); the full enumeration of Yn/parametric/polar/seq names
  under the bit4/5/6 remap was not exhaustively dumped.
