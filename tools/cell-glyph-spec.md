# TI-84 Plus OS 2.55MP — page-0x39 cell → glyph / action spec

How a MathPrint "handler record" CELL (a two-byte value `D:E`, e.g. `00C8`,
`FE18`, `FC3F`) maps to a drawn large-font codepoint or a layout action.

All addresses are `page:offset`. Raw bytes are quoted from `tools/rom.bin`
(flash page P at file offset `P*0x4000`, logical window `0x4000..0x7FFF`).
Glyph codepoints are indices into the **large font** on page 0x07 at
base `0x45FF`, 7-byte stride: `glyph(code) = ROM[page07: 0x45FF + code*7]`
(see `tools/render-mathprint.py`).

The authoritative emitter for layout.json cells is the page-0x39 routine
`eqdisp_emit_glyph` (`39:4E8E`). The page-0x07 classifier `07:44DE` is the
*classic* (non-MathPrint) editor char→token/glyph map; its FE/FC/FB sub-tables
are reproduced here because they are the canonical family glyph tables, but note
(see §3) that they return **expanded TI tokens**, not directly font codepoints.

---

## 1. The D-byte dispatch rule (`eqdisp_emit_glyph`, 39:4E8E)

Cells are read as a stream of `(D,E)` pairs: the feeder
`eqdisp_emit_arglist` (`39:4DE6`) does `ld d,(hl); inc hl; ld e,(hl); inc hl`
then `call 4E8E`, so **D = first byte, E = second byte** of each pair.

`39:4E8E` raw:
```
7a fe 1f 20 2c ...        ; ld a,d / cp 1F / jr nz
... fe 82 20 08 ...       ; cp 82 / jr nz
... d5 cd 75 66 ...       ; (default) push de / call 6675
```

Dispatch on **D**:

| D value      | meaning / branch | what happens |
|--------------|------------------|--------------|
| `D = 0x1F`   | cursor / answer marker (`4E93`) | not a glyph; runs cursor/edit-area setup (`bcall 01B07`, `bcall 01790`, `02D09`, `03E85`), decrements `(0844Bh)`. **Layout action, draws nothing itself.** |
| `D = 0x82`   | "raw column glyph" (`4EBF`) | `a = E - 0x3E; call 3B2B` — draws via the column/small-glyph routine. (E is a column index, not a font code.) |
| everything else | generic path (`4ECB`) | 3-stage resolve: (a) named-token list check `6675`, (b) token-name draw `6B66`, (c) remap-to-glyph `eqdisp_map_token_glyph` `4F1A`. See §1.1. |

### 1.1 Generic path (D ∉ {0x1F, 0x82})

1. **`call 6675` (`eqdisp_classify_paren`)** — matches `D:E` against three
   10-entry token lists (see §5). On match it stores `E→(08446h)`, `D→A` and
   routes to the *styled / sub-table* name-draw path (used for ∑, ∏, integrals,
   etc.).
2. **`bit 6,(iy+036h)`** mode bit: if set, `call 2CBB` (alternate handling).
   If `D = 0xFD`, force `D = 0x00` (`16 00` at `4EE1`) before:
3. **`call 6B66` (named-token string draw)** — if `D = 0xFB` and `E` is one of
   the special "named" codes, an inline Pascal string is drawn (see §6).
   Otherwise `bcall 0xC945` draws the pair `D:E` as a **TI token, by name**.
   This is the path that renders e.g. a `00:E` cell as a function name.
4. **`call 4F1A` (`eqdisp_map_token_glyph`)** — if it returns **NC**, A holds a
   large-font codepoint and `bcall 0x51F4` (page35:60D1) draws that glyph.
   If it returns **C** (carry), the cell was *not* remappable to a single glyph
   and the draw already happened in step 3 (token name) or is a no-op.
   - On the carry path: `D = 0xFF` or `D = 0xFC` → finished; `E = 0x55` →
     special; else cleanup.

So a cell can resolve to **(i)** a layout/cursor action (D=0x1F),
**(ii)** a token *name string* (steps 1/3, e.g. D=0x00 or FB-special), or
**(iii)** a single large-font glyph (step 4 via `4F1A`).

---

## 2. `eqdisp_map_token_glyph` (39:4F1A) — exact arithmetic

Input `D:E`, output: **NC** ⇒ A = large-font codepoint; **C** ⇒ no single-glyph
mapping. Raw (`39:4F1A`):
```
7a fe fc 20 0b      cp FC ; jr nz
7b fe 41 30 1e      ld a,e ; cp 41 ; jr nc ->scf
d6 3c d8            sub 3C ; ret c
c6 05 c9            add 05 ; ret            ; FC: glyph = (E-0x3C)+5
... fe fe 7b 20 08  cp FE ; ld a,e ; jr nz
fe 82 30 0f         cp 82 ; jr nc ->scf
d6 7d d8 c9         sub 7D ; ret c ; ret    ; FE: glyph = (E-0x7D)
... fe 42 20 07     cp 42 ; jr nz ->scf     ; (E==0x42 branch)
7a fe 0a 30 02      ld a,d ; cp 0A ; jr nc ->scf
b7 c9               or a ; ret              ; xx42: glyph = D  (carry clear)
37 c9               scf ; ret               ; otherwise: no mapping
```

| Cell form        | condition            | result (large-font codepoint) |
|------------------|----------------------|-------------------------------|
| `D=0xFC, E`      | `0x3C ≤ E ≤ 0x40`    | `glyph = (E − 0x3C) + 5`  → FC3C→5, FC3D→6, FC3E→7, FC3F→8, FC40→9 |
| `D=0xFC, E`      | `E < 0x3C` or `E ≥ 0x41` | carry (no single glyph) |
| `D=0xFE, E`      | `0x7D ≤ E ≤ 0x81`    | `glyph = (E − 0x7D)`     → FE7D→0, FE7E→1, FE7F→2, FE80→3, FE81→4 |
| `D=0xFE, E`      | `E < 0x7D` or `E ≥ 0x82` | carry |
| `D, E=0x42`      | `D < 0x0A`           | `glyph = D`              → e.g. `0142`→1, `0942`→9 |
| any other        | —                    | carry (handled elsewhere, usually a token name) |

These five FC/FE codepoints `5..9` and `0..4` are consecutive font cells; in the
ROM large font 0x00..0x09 are the small/sub-script style digit forms and
0x05..0x09 the super/alt forms used by exponent layouts.

---

## 3. Page-0x07 classifier `07:44DE` and the FE/FC/FB family tables

`07:44DE` takes a **single display byte in A** (the classic editor encoding) and
returns `D:E`. It is *not* the page-0x39 cell emitter, but its sub-tables are the
canonical family glyph/token tables.

Raw (`07:44DE`):
```
fe fe 28 3c     cp FE / jr z ->l451E   (FE family)
fe fc 28 30     cp FC / jr z ->l4516   (FC family)
fe fb 28 1e     cp FB / jr z ->l4508   (FB family)
fe 05 20 05     cp 05 / jr nz
1e 3f 16 00 c9  E=3F ; D=00 ; ret      (cp 0x05 -> glyph 0x3F)
d6 5a 21 00 40  sub 5A ; hl=0x4000     (default)
5f 16 00 19     E=a ; D=00 ; add hl,de
5e c9           E=(hl) ; ret           (default: glyph = byte[0x4000+(A-0x5A)])
```

Indexing per family (the in-family index is **RAM (08446h)**, the "font/mode
sub-code" that the editor's encoder `07:4539` stored earlier):

- **`cp 0x05` → glyph `0x3F`** (direct).
- **default** → `glyph = byte[ page07: 0x4000 + (A − 0x5A) ]` (table §3a).
- **FE family** (`l451E`): `i = (08446h)`.
  - if `i < 0x69`: `glyph = byte[ 0x4099 + i ]`  (single-byte table §3b).
  - if `i ≥ 0x69`: `i -= 0x69`; entry = WORD at `0x4102 + 2*i` → returns the
    pair `D=byte[0x4102+2i], E=byte[+1]` (word table §3c).
- **FC family** (`l4516`): `i = (08446h)`; entry = WORD at `0x422C + 2*i` (§3d).
- **FB family** (`l4508`): `i = (08446h)`; **if `i ≥ 0x8C`, `i -= 0x7F`**;
  entry = WORD at `0x4426 + 2*i` (§3e).

**Important:** the FE-high / FC / FB word tables (§3c–§3e) do **not** contain
font codepoints. Each 2-byte entry is itself a TI token `(lead, second)` — the
lead bytes seen are 0x7E, 0x5D, 0x5C, 0x63, 0x60, 0x61, 0x62, 0xAA, 0xBB, 0xEF,
0xFE, 0x28. `07:44DE` therefore *expands* a 1-byte editor code into a 2-byte
token, which is then drawn by name / recursively classified. Only the **default**
and **cp 0x05** cases yield a font glyph directly.

### 3a. Default table — `page07:0x4000`, glyph = byte[0x4000+(code−0x5A)]
code → glyph (large-font codepoint):
```
5A→84 5B→00 5C→89 5D→8A 5E→8D 5F→88 60→8E 61→00 62→8B 63→86 64→87 65→90
66→92 67→8C 68→8F 69→00 6A→A5 6B→85 6C→9C 6D→00 6E→A0 6F→9F 70→9E 71→9D
72→A6 73→93 74→A7 75→00 76→00 77→00 78→00 79→00 7A→00 7B→00 7C→00 7D→00
7E→00 7F→EB 80→70 81→71 82→82 83→83 84→F0 85→10 86→11 87→06 88→07 89→A4
8A→04 8B→2B 8C→B0 8D→3A 8E→30 8F→31 90→32 91→33 92→34 93→35 94→36 95→37
96→38 97→39 98→3B 99→29 9A→41 9B→42 9C→43 9D→44 9E→45 9F→46 A0→47 A1→48
A2→49 A3→4A A4→4B A5→4C A6→4D A7→4E A8→4F A9→50 AA→51 AB→52 AC→53 AD→54
AE→55 AF→56 B0→57 B1→58 B2→59 B3→5A B4→00 B5→AC B6→0C B7→C2 B8→C3 B9→C4
BA→C5 BB→C6 BC→C7 BD→0D BE→BC BF→BE C0→BF C1→C0 C2→C1 C3→03 C4→FB C5→72
C6→3E C7→25 C8→24 C9→22 CA→AF CB→2A CC→5B CD→CE CE→CF CF→D0 D0→D3 D1→D1
D2→D2 D3→D4 D4→D8 D5→D6 D6→D7 D7→DA D8→DB D9→E6 DA→5F DB→D5 DC→D9 DD→DC
DE→DD DF→DE E0→DF E1→E5 E2→E0 E3→AD E4→E1 E5→91 E6→C8 E7→CA E8→CC E9→C9
EA→CB EB→CD EC→08 ED→09 EE→2C EF→00 F0→EE F1→27 F2→28 F3→A8 F4→A9 F5→A1
F6→A2 F7→13 F8→9B F9→99 FA→9A FB→98 FC→B2 FD→6A FE→6F FF→6C
```
(Note: maps the editor's letter/op codes onto the large font; e.g. C7→0x25 "/",
C8→0x24, C9→0x22, B6→0x0C etc.)

### 3b. FE-low table — `page07:0x4099`, glyph = byte[0x4099+i] (i = (08446h) < 0x69)
idx → glyph:
```
00→A8 01→A9 02→A1 03→A2 04→13 05→9B 06→99 07→9A 08→98 09→B2 0A→6A 0B→6F
0C→6C 0D→6E 0E→6B 0F→6D 10→40 11→3C 12→3D 13→B8 14→FF 15→F1 16→0F 17→BD
18→02 19→2E 1A→2F 1B→EC 1C→ED 1D→12 1E→B9 1F→BA 20→B1 21→AB 22→94 23→95
24→2D 25→0A 26→0B 27→AE 28→01 29→1C 2A→1B 2B→1D 2C→1E 2D→15 2E→16 2F→17
30→18 31→E3 32→E4 33→23 34→1A 35→19 36→21 37→1F 38→B6 39→B7 3A→B3 3B→0E
3C→B5 3D→E2 3E→B4 3F→20 40→14 41→F2 42→F3 43→F4 44→F5 45→F6 46→F7 47→F8
48→F9 49→FA 4A→FC 4B→FD 4C→FE 4D→64 4E→65 4F→66 50→67 51→68 52→69 53→73
54→74 55→75 56→76 57→77 58→78 59→79 5A→7A 5B→7B 5C→7C 5D→7D 5E→96 5F→97
60→E9 61→EA 62→A3 63→E7 64→E8 65→05 66→7F 67→80 68→81
```

### 3c. FE-high token table — `page07:0x4102`, WORD[2*i] (i = (08446h)−0x69)
Each entry is a 2-byte TI token `(D,E)`:
```
00:7E00 01:7E01 02:7E02 03:7E03 04:7E04 05:7E05 06:7E06 07:7E07 08:7E08 09:7E09
0A:7E0A 0B:7E0B 0C:7E0C 0D:7E0D 0E:5D00 0F:5D01 10:5D02 11:5D03 12:5D04 13:5D05
14:5C00 15:5C01 16:5C02 17:5C03 18:5C04 19:630A 1A:630B 1B:6302 1C:630C 1D:630D
1E:6303 1F:630E 20:630F 21:6322 22:6310 23:6311 24:6323 25:6304 26:6305 27:631F
28:631D 29:6327 2A:6326 2B:6312 2C:6313 2D:6300 2E:6314 2F:6315 30:6301 31:6318
32:6319 33:6324 34:6316 35:6317 36:6325 37:6308 38:6309 39:6320 3A:631E 3B:BB57
3C:BB32 3D:BB31 3E:6000 3F:6001 ...
```

### 3d. FC token table — `page07:0x422C`, WORD[2*i] (i = (08446h))
```
00:6100 01:6101 02:6102 03:5E10 04:5E11 05:5E12 06:5E13 07:5E14 08:5E15 09:5E16
0A:5E17 0B:5E18 0C:5E19 0D:5E20 0E:5E21 0F:5E22 10:5E23 11:5E24 12:5E25 13:5E26
14:5E27 15:5E28 16:5E29 17:5E2A 18:5E2B 19:5E40 1A:5E41 1B:5E42 1C:5E43 1D:5E44
1E:5E45 1F:6103 20:6104 21:6105 22:6003 23:6004 24:6005 25:6106 26:6107 27:6108
28:6109 29:6006 2A:6007 2B:6008 2C:6009 2D:6202 2E:6203 2F:BB25 30:BB26 31:BB28
32:BB08 33:BB09 34:BB0A 35:BB1F 36:BB30 37:BB2F 38:620C 39:6206 3A:6207 3B:6332
3C:5C05 3D:5C06 3E:5C07 3F:5C08 40:5C09 41:0000 42:620F 43:6210 44:BB39 45:BB3A
46:BB29 47:BB2C 48:BB0D 49:BB0E 4A:BB2B 4B:BB55 4C:BB56 4D:BB2A 4E:BB0C 4F:BB0F
50:AA00 51:AA01 52:AA02 53:AA03 54:AA04 55:AA05 56:AA06 57:AA07 58:AA08 59:AA09
5A:632B 5B:632C 5C:632D 5D:632E 5E:632F 5F:6330 ...
```

### 3e. FB token table — `page07:0x4426`, WORD[2*i] (i = (08446h); if i≥0x8C, i−=0x7F)
```
00:5E82 01:BBD0 02:BBD1 03:BBD2 04:BBD3 05:BBD4 06:BBD5 07:BBD6 08:BBD7 09:BBD8
0A:BBD9 0B:BBCF 0C:BBDA 0D:BBDB 0E:BBDC 0F:BBDD 10:BBDE 11:BBDF 12:BBE0 13:BBE1
14:BBE2 15:BBE3 16:BBE4 17:BBE5 18:BBE6 19:BBE7 1A:BBE8 1B:BBE9 1C:BBEA 1D:BBEB
1E:BBEC 1F:BBED 20:BBEE 21:BBF0 22:BBF1 23:BBF2 24:BBF3 25:BBF4 26:BBF5 27:EF00
28:EF01 29:EF02 2A:EF03 2B:EF04 2C:EF05 2D:EF06 2E:EF07 2F:EF08 30:EF09 31:EF0A
32:EF0B 33:EF0C 34:EF0D 35:EF0E 36:EF0F 37:EF10 38:EF11 39:EF12 3A:EF13 3B:EF14
3C:EF15 3D:EF3E 3E:EF16 3F:0000 40:0000 41:EF17 42:EF18 43:EF19 44:EF1A 45:EF1B
46:EF1C 47:EF1D 48:EF34 49:EF33 4A:EF36 4B:EF2E 4C:EF2F 4D:EF30 4E:EF31 4F:EF32
50:EF35 51:EF2B 52:EF1E 53:EF37 54:EF38 55:EF39 56:EF3A 57:EF3B 58:EF3C 59:EF3D
5A:EF3F 5B:EF40 5C:FEFE 5D:283C 5E:FEFC 5F:2830 ...
```

---

## 4. The `00:E` cell — token-name vs direct glyph

For `D = 0x00` the cell takes the **generic path** (§1.1). `4F1A` returns carry
(D=0 matches none of FC/FE/xx42), so no single-glyph mapping; instead the draw
happens inside `6B66`:

- `6B66` (`39:6B66`): `D ≠ 0xFB` ⇒ falls to `l6B9C`: `rst 28h` `ca 45 c9`
  = `bcall 0xC945`. This is the generic **token-name string drawer**: it takes
  the 2-byte value `D:E` as a TI token and renders the token's NAME using the
  font. Hence `00C8` draws the *name* `fnInt(`, not a glyph.

So a `00:E` cell is interpreted as the (synthetic) two-byte token `0x00,E` and
its **name string** is typeset. (Contrast: `FB:E` specials in §6 use inline
hardcoded strings; `1F` is a cursor action; FC/FE/xx42 from §2 are single
glyphs.)

---

## 5. Named-token lists checked by `6675` (`39:62CB / 62E2 / 62F9`)

`6675` calls `6667` three times; `6667` linear-scans **10** two-byte entries and
returns Z on a `D:E` match. Matching cells take the *styled / sub-table* draw
path (`E→(08446h)`, `D→A`, draw via `03B37`/`01BAF`, save `D:E`→`(08479h)`).
These are the ∑/∏/integral-style operators that own a 2-D template.

- `62CB` (raw `fc 00 fc 01 fc 02 fc 1f fc 20 fc 21 fc 25 fc 26 fc 27 fc 28`):
  **FC00 FC01 FC02 FC1F FC20 FC21 FC25 FC26 FC27 FC28**
- `62E2` (raw `fe a7 fe a8 fe a9 fc 22 fc 23 fc 24 fc 29 fc 2a fc 2b fc 2c`):
  **FEA7 FEA8 FEA9 FC22 FC23 FC24 FC29 FC2A FC2B FC2C**
- `62F9` (raw `fc 50 fc 51 fc 52 fc 53 fc 54 fc 55 fc 56 fc 57 fc 58 fc 59`):
  **FC50 FC51 FC52 FC53 FC54 FC55 FC56 FC57 FC58 FC59**

(The `01 0a XX` bytes following each list are unrelated data, not list entries —
`6667` reads exactly 10 entries.)

---

## 6. FB-special inline name strings (`6B66`, 39:6BA9..6BDF)

When `D = 0xFB`, `6B66` maps certain `E` to a **hardcoded length-prefixed ASCII
string** drawn via `bcall 0x192B` / `(097F2h)`:

| cell `FB:E` | E    | string drawn (len-prefixed) |
|-------------|------|-----------------------------|
| `FBC8`      | 0xC8 | `summation Σ(` (12 bytes, `6BB2`) — only when `bit0,h` set |
| `FBCA`      | 0xCA | `nΣd` (3 bytes, `6BA9`) |
| `FBCB`      | 0xCB | `UnΣd` (4 bytes, `6BAD`) |
| `FBD6`      | 0xD6 | `AUTO Answer` (11 bytes, `6BBF`) |
| `FBD7`      | 0xD7 | `DEC Answer` (10 bytes, `6BD7`) |
| `FBD8`      | 0xD8 | `FRAC Answer` (11 bytes, `6BCB`) |

Any other `FB:E` (and any non-FB pair on this path) falls through to the generic
`bcall 0xC945` token-name drawer.

---

## 7. Cell → action (layout, not drawing) markers

| cell           | action |
|----------------|--------|
| `D = 0x1F`     | cursor / answer-area marker; runs edit-area setup, draws no glyph, decrements line counter `(0844Bh)` (`39:4E8E` @4E93). |
| `D = 0xFF, *`  | on the `4F1A`-carry path (`39:4EF3`) treated as a terminator/skip (no glyph). |
| `D = 0xFC` with `E ≥ 0x41` (not in §2 range) | carry path; not a single glyph — either a §5-styled operator or a token name. |
| `*:0x55` (E=0x55) on carry path | special-cased at `39:4EFD` (`call 03CB7`, `bcall 0x51F4`) — a layout/positioning helper. |
| `D` matching §5 lists | 2-D template operator (∑, ∏, ∫, ...), drawn from a sub-table keyed by `E`→`(08446h)`. |
| `D = 0x82`     | column glyph: `glyph index = E − 0x3E`, drawn by `03B2B` (the small/column draw path) — positional, not a font-table lookup. |

---

## Bcalls referenced (resolved from the page-0x3B bcall table)

- `_PutPSB` = `0x450D` → page01:5C52 (draw length-prefixed string).
- `0xC945` → page01 (token-name drawer used by `6B66`).
- `0x51F4` → page35:60D1 (draw a single large-font glyph from A).
- `0x51E5` (`_scr_4619`) → page05:4619.
- `03FDB` (page-0, always-mapped) → inter-page trampoline (`call 2B09`,
  3-byte target) into the page-01 glyph blit routine — the low-level char draw.

---

## Unresolved / flagged

- The exact NAME-string source for the generic `bcall 0xC945` token drawer
  (page-01 routine) was not fully traced; it is the standard OS token-name
  expander, so `00:E` → name follows OS token semantics. The assertion
  `00C8 = "fnInt("` is consistent with this path but the OS token table itself
  was not dumped here.
- FE-high / FC / FB word tables (§3c–§3e) emit *expanded TI tokens*, not font
  codepoints; resolving those tokens to glyphs requires a second classification
  pass (recursively through `07:44DE` / the OS token drawer). Only the §3a
  default and the `cp 0x05` cases give a font codepoint directly.
- `(08446h)` is a RAM mode/sub-code byte set by the classic editor encoder
  (`07:4539`); for the page-0x39 MathPrint cell path it is set from `E` in the
  §5 styled path. Its full lifecycle across both paths was not exhaustively
  traced.
