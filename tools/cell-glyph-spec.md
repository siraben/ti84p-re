# MathPrint cell dispatch

*TI-84 Plus OS 2.55MP — page `0x39` cell, glyph, and action decoding.*

This note explains how a two-byte MathPrint handler-record cell `D:E`, such as
`00C8`, `FE18`, or `FC3F`, maps to a large-font codepoint or a layout action.

All addresses use `pp:addr`. Raw bytes come from the pinned OS image identified
by `tools/rom_signatures.py`. Unless marked otherwise, byte, table, and control-
flow claims below are [confirmed]. Glyph codepoints index the large font on
page `0x07` at `07:45FF`, with a 7-byte stride:
`glyph(code) = ROM[07:45FF + code*7]`
(see `tools/render-mathprint.py`).

The authoritative emitter for `layout.json` cells is the page `0x39` routine
`eqdisp_emit_glyph` (`39:4E8E`). The page `0x07` classifier `07:44DE` is the
classic non-MathPrint editor char→token/glyph map; its FE/FC/FB subtables
are reproduced here because they are the canonical family glyph tables. They
return expanded TI tokens, not direct font codepoints.

---

## D-byte dispatch

Cells are read as a stream of `(D,E)` pairs: the feeder
`eqdisp_emit_arglist` (`39:4DE6`) does `ld d,(hl); inc hl; ld e,(hl); inc hl`
then `call 4E8E`, so `D` is the first byte and `E` is the second.

`39:4E8E` begins:

```z80
7a fe 1f 20 2c ...        ; ld a,d / cp 1F / jr nz
... fe 82 20 08 ...       ; cp 82 / jr nz
... d5 cd 75 66 ...       ; (default) push de / call 6675
```

Dispatch on `D`:

| D value      | meaning / branch | what happens |
|--------------|------------------|--------------|
| `D = 0x1F`   | cursor / answer marker (`39:4E93`) | Runs cursor/edit-area setup, decrements `0x844B`, and draws no glyph. |
| `D = 0x82`   | indexed string/title (`39:4EBF`) | `A = E - 0x3E; call ram:3B2B` reaches the indexed-string printer at `01:7183`. `E` selects an entry, not a font code. |
| everything else | generic path (`39:4ECB`) | Checks archived fixed-token names at `39:6675`, selects a string at `39:6B66`, then tries the direct mapper at `39:4F1A`. |

### Generic path

1. `call 6675` matches `D:E` against three 10-entry fixed-token lists. On a
   match it stores `E` to `0x8446`, moves `D` to `A`, remaps the pair, and looks
   up the resulting `GDB`, `Pic`, or `Str` name in the VAT. An archived match
   emits `*` before the remaining cell stages.
2. `bit 6,(iy+036h)` selects alternate handling through `ram:2CBB` when set.
   If `D = 0xFD`, force `D = 0x00` (`16 00` at `39:4EE1`) before:
3. `39:6B66` selects an inline counted string when `D = 0xFB` and `E` is one of
   the special named codes.
   Otherwise `_KeyToString = 45CAh` (body `01:6D10`) selects a
   counted display string from the pair `D:E`.
   This path renders a `00:E` cell as a function name.
4. `39:4F1A` (`eqdisp_map_token_glyph`) returns NC with a large-font codepoint
   in `A`, or C when no direct mapping exists. The tail reaches bcall ID
   `51F4h`. Its resolved target is a post-overflow display/menu helper, so this
   boundary does not identify the final glyph blitter. On the carry path, the
   cell has no single-glyph mapping. `D = 0xFF` or `D = 0xFC` finishes, while
   `E = 0x55` takes a special path.

These stages are sequential. In particular, a match at `39:6675` does not
return from `39:4E8E`: the caller restores the original `D:E`, may emit the
counted string, and still probes `39:4F1A`. The JavaScript translation models
the complete outer controller through `39:4F19`. A pinned-byte oracle checks
196,608 representative full-byte states, and the finite model partitions all
1,048,576 projected flag/result states into 39 paths. The installed callback
and output helpers remain explicit boundaries. [confirmed]

The result can therefore be an ordered sequence of a layout prepass, a counted
string, a direct large-font glyph, and post-output handling; it is not always a
single mutually exclusive action. [confirmed]

---

## Direct glyph mapping

Input `D:E`; output NC means `A` holds a large-font codepoint. Carry means no
single-glyph mapping. The bytes at `39:4F1A` are:

```z80
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

`settledPage39DirectGlyphSelection()` preserves the accumulator, carry flag,
and all eight conditional sites through `39:4F43`. The handler-cell classifier
uses that translation. A pinned-byte interpreter compares all 65,536 `D:E`
inputs and reduces them to nine complete paths. [confirmed]

The FC/FE codepoints `5`–`9` and `0`–`4` occupy consecutive font cells. In the
ROM large font, `0x00`–`0x09` are small/subscript digit forms, and
`0x05`–`0x09` are the alternate forms used by exponent layouts.

---

## Page-`0x07` classifier and family tables

`07:44DE` takes a single classic-editor display byte in `A` and returns `D:E`.
It is not the page `0x39` cell emitter, but its subtables are the
canonical family glyph/token tables.

The bytes at `07:44DE` are:

```z80
fe fe 28 3c     cp FE / jr z ->l451E   (FE family)
fe fc 28 30     cp FC / jr z ->l4516   (FC family)
fe fb 28 1e     cp FB / jr z ->l4508   (FB family)
fe 05 20 05     cp 05 / jr nz
1e 3f 16 00 c9  E=3F ; D=00 ; ret      (cp 0x05 -> glyph 0x3F)
d6 5a 21 00 40  sub 5A ; hl=0x4000     (default)
5f 16 00 19     E=a ; D=00 ; add hl,de
5e c9           E=(hl) ; ret           (default: glyph = byte[0x4000+(A-0x5A)])
```

The in-family index is the font/mode subcode at `0x8446`, stored by `07:4539`.

- `cp 0x05` maps directly to glyph `0x3F`.
- The default case reads `glyph = byte[07:4000 + (A - 0x5A)]`.
- The FE family (`l451E`) uses `i = 0x8446`.
  - If `i < 0x69`, `glyph = byte[07:4099 + i]`.
  - If `i >= 0x69`, subtract `0x69` and read the pair at `07:4102 + 2*i`.
- The FC family (`l4516`) reads a word at `07:422C + 2*i`.
- The FB family (`l4508`) subtracts `0x7F` when `i >= 0x8C`, then reads
  a word at `07:4426 + 2*i`.

The FE-high, FC, and FB word tables contain expanded TI tokens, not
font codepoints. Each 2-byte entry is itself a TI token `(lead, second)` — the
lead bytes seen are 0x7E, 0x5D, 0x5C, 0x63, 0x60, 0x61, 0x62, 0xAA, 0xBB, 0xEF,
0xFE, 0x28. `07:44DE` therefore *expands* a 1-byte editor code into a 2-byte
token, which is then drawn by name or recursively classified. Only the default
and `cp 0x05` cases yield a font glyph directly.

`settledPage7DisplayByteRemap()` executes the main-entry branch and index
logic. `web/mathprint/layout.json` contains every table entry that the two-byte
input domain can address. A pinned-byte interpreter compares all 65,536
display-byte and `keyExtend` pairs. The separate entry at `07:44FE` is outside
this domain. [confirmed]

`settledPage7SOKForKeyToString()` executes the caller-valid part of that
separate entry. `_KeyToString` supplies `H=2` for `FB` and `FC`, or `H=1` for
`FE` and `FF`. All 1,024 admitted prefix/index pairs are compared with the
pinned bytes. `settledPage1KeyToStringSelection()` then carries the mapped
cell through `01:6702` to the extracted counted display string. [confirmed]

### Default table at `07:4000`
Code to large-font glyph:

```text
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

### FE-low table at `07:4099`
Index to glyph:

```text
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

### FE-high token table at `07:4102`
Each entry is a 2-byte TI token `(D,E)`:

```text
00:7E00 01:7E01 02:7E02 03:7E03 04:7E04 05:7E05 06:7E06 07:7E07 08:7E08 09:7E09
0A:7E0A 0B:7E0B 0C:7E0C 0D:7E0D 0E:5D00 0F:5D01 10:5D02 11:5D03 12:5D04 13:5D05
14:5C00 15:5C01 16:5C02 17:5C03 18:5C04 19:630A 1A:630B 1B:6302 1C:630C 1D:630D
1E:6303 1F:630E 20:630F 21:6322 22:6310 23:6311 24:6323 25:6304 26:6305 27:631F
28:631D 29:6327 2A:6326 2B:6312 2C:6313 2D:6300 2E:6314 2F:6315 30:6301 31:6318
32:6319 33:6324 34:6316 35:6317 36:6325 37:6308 38:6309 39:6320 3A:631E 3B:BB57
3C:BB32 3D:BB31 3E:6000 3F:6001 ...
```

### FC token table at `07:422C`

```text
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

### FB token table at `07:4426`

```text
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

## `00:E` cells

For `D = 0x00`, the cell takes the generic path. `39:4F1A` returns carry
(D=0 matches none of FC/FE/xx42), so no single-glyph mapping; instead the draw
happens inside `39:6B66`:

- `39:6B66`: `D ≠ 0xFB` falls to `39:6B9C`, whose complete bytes are
  `EF CA 45 C9`: `_KeyToString = 45CAh` followed by `RET`.
  `_KeyToString` uses the pair `D:E` to select a counted display string. The
  branch-specific index arithmetic is documented in `tools/token-name-spec.md`.

So a `00:E` cell selects a `_KeyToString` display string. It is not a direct
index into the standard token table. Selected `FB:E` values use inline strings;
`1F` is a cursor action; and the FC, FE, and `xx42` forms above are single glyphs.

---

## Archived fixed-token markers

`39:6675` calls `39:6667` three times. The latter scans 10 two-byte entries and
returns Z on a `D:E` match. The ROM scans class `0x18`, then `0x17`, then
`0x19`. `ram:3B37` reaches the display-byte remapper at `07:44DE`, and
`ram:1BAF` clears OP1 before the mapped name is stored at `0x8479`.
Page `0x07` maps the lists to `6100`–`6109` (`GDB1`–`GDB0`),
`6000`–`6009` (`Pic1`–`Pic0`), and `AA00`–`AA09` (`Str1`–`Str0`). [confirmed]

The mapped path calls `_ChkFindSym` at `ram:0E60`. An unmatched list cell may
instead map through `39:4F1A`; `05:4056` then constructs matrix name `5C:A`
before `_FindSym`. On either successful lookup, `ram:1785` decrements `HL` five
times from the returned VAT type byte to the page byte. Page zero returns.
A nonzero page emits `2Ah` (`*`) through `ram:3FDB`. [confirmed]

The JavaScript translation accepts the same logical VAT snapshots used by the
editor search model. A pinned-byte oracle checks all 196,608 `D:E` and
absent/RAM/archive projections. The finite model reduces them to 13 paths and
14 branch outcomes. [confirmed]

- `39:62CB`: `FC00 FC01 FC02 FC1F FC20 FC21 FC25 FC26 FC27 FC28`
- `39:62E2`: `FEA7 FEA8 FEA9 FC22 FC23 FC24 FC29 FC2A FC2B FC2C`
- `39:62F9`: `FC50 FC51 FC52 FC53 FC54 FC55 FC56 FC57 FC58 FC59`

(The `01 0a XX` bytes following each list are unrelated data, not list entries —
`39:6667` reads exactly 10 entries.)

---

## Inline `FB` strings

When `D = 0xFB`, `39:6B66` maps certain `E` values to a hardcoded
length-prefixed ASCII string in `0x97F2`. The caller at `39:4EE6` then invokes
`_PutPSB = 450Dh` (body `01:5C52`) to draw the selected string. [confirmed]

| cell `FB:E` | E    | string drawn (len-prefixed) |
|-------------|------|-----------------------------|
| `FBC8`      | 0xC8 | `summation Σ(` (12 bytes, `39:6BB2`) — only when `bit0,h` set |
| `FBCA`      | 0xCA | `nΣd` (3 bytes, `39:6BA9`) |
| `FBCB`      | 0xCB | `UnΣd` (4 bytes, `39:6BAD`) |
| `FBD6`      | 0xD6 | `AUTO Answer` (11 bytes, `39:6BBF`) |
| `FBD7`      | 0xD7 | `DEC Answer` (10 bytes, `39:6BD7`) |
| `FBD8`      | 0xD8 | `FRAC Answer` (11 bytes, `39:6BCB`) |

Any other `FB:E` (and any non-FB pair on this path) falls through to
`_KeyToString = 45CAh`.

---

## Cell actions

| cell           | action |
|----------------|--------|
| `D = 0x1F`     | Cursor/answer-area marker; runs edit-area setup, draws no glyph, and decrements `0x844B` at `39:4E93`. |
| `D = 0xFF, *`  | on the `4F1A`-carry path (`39:4EF3`) treated as a terminator/skip (no glyph). |
| `D = 0xFC` with `E >= 0x41` | Carry path; either a styled operator or a token name, not a single glyph. |
| `*:0x55` on the carry path | Special case at `39:4EFD`; calls `ram:3CB7` and bcall ID `51F4h`. |
| `D:E` matching the fixed-token lists | Remap to a `GDB`, `Pic`, or `Str` VAT name; emit `*` first when the variable is archived. |
| `D = 0x82`     | Indexed string/title: `index = E - 0x3E`, printed by `01:7183` through the `ram:3B2B` bjump. |

---

## Referenced bcalls

- `_PutPSB = 450Dh` → `01:5C52` (draw length-prefixed string).
- `_KeyToString = 45CAh` → `01:6D10` (counted-string selector used by `39:6B66`).
- Bcall ID `51F4h` → `35:60D1` (post-overflow display/menu helper, not a glyph-width service).
- Bcall ID `51E5h` (`_scr_4619`) → `05:4619`.
- `ram:3FDB` → inter-page trampoline (`call ram:2B09`, 3-byte target) into the
  page `0x01` glyph blit routine.

---

## Open questions

- Installed font and token hooks can replace `_KeyToString` pointers. Their
  external bodies remain explicit boundaries. The normal hook-disabled path is
  translated for every `D:E` input. See `tools/token-name-spec.md`.
- FE-high, FC, and FB word tables emit *expanded TI tokens*, not font
  codepoints. `_KeyToString` sends those pairs through `01:6702`; the
  JavaScript translation now performs that second selection. Only the default
  and `cp 0x05` branches of `07:44DE` produce font codepoints directly.
- `0x8446` is a RAM mode/subcode byte set by the classic editor encoder
  (`07:4539`); the page `0x39` MathPrint path sets it from `E` in the
  styled path. Its full lifecycle across both paths was not exhaustively
  traced. [hypothesis]
