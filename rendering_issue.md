# MathPrint rendering — context & open issue

## 2026-06-05 update

The tall-integral screenshot mismatch is fixed in `tools/render-mathprint.py`, but
that renderer fix is still a bitmap-equivalent model rather than a full ROM
execution of the template row actions.

New ROM/Ghidra facts supersede the descriptor dead end below:

- The `0x5E45` table entries are **handler record pointers**, not executable
  handler entry points. A record is:
  `[row_count][arg_count per row][row_action per row][2-byte display-token cells]`.
- `eqdisp_sum_arg_widths` (`39:4DCA`) computes the current row's token-cell
  pointer as `record + 1 + 2*row_count + 2*sum(previous row arg_counts)`.
- The `fnInt(`/`nDeriv(`/summation family is in class `0x08` (`record 0x608B`)
  and its `+0x28` fraction-context variant class `0x30` (`record 0x6030`).
  `record 0x608B` row 0 contains `00 C7` (`nDeriv(`), `00 C8` (`fnInt(`),
  `FB C8`, and `FB C7`.
- Page 1's token-name table confirms `C8 06 "fnInt("` and `C7 07 "nDeriv("`.
- The `0x686F`/`0x6880` descriptors are **fixed menu/box descriptors**, not
  integral segment tables. Dump them with `tools/dump-mathprint-layout.py
  --descriptors`.
- `FB C7`/`FB C8` are not integral bitmaps. `eqdisp_menu_or_emit` (`39:53AD`)
  special-cases them as square down/up marker emission (`0x07`/`0x06`), and
  `eqdisp_load_glyph18b[2]` routes only proven menu-string cases such as
  `FB CA` -> `n/d`, `FB CB` -> `Un/d`, draw-path `FB C8` -> the summation menu
  string, and `FB D6/D8/D7` -> answer-mode strings.

Remaining blocker for **full** recovery: trace how the `fnInt(` operand slots in
the class `0x08`/`0x30` records drive the recursive raised/lowered-limit
placement that yields the 17-pixel tall captured layout. The per-row bytes
`0x35`, `0x3B`, `0x25`, `0x43` are row title/selector bytes emitted by
`_DispMenuTitle` (`39:4D21`), not integral segment opcodes.

Working notes for pixel-accurate reconstruction of the TI-84 Plus (OS 2.55MP)
MathPrint 2-D typesetter, and the specific blocker on the **definite-integral
template**. ROM image: `tools/rom.bin` (1 MiB, gitignored). Ghidra MCP HTTP
bridge: `http://127.0.0.1:8080` (disassemble overlays with the `page_NN::addr`
form; `decompile` by symbol name). Renderer: `tools/render-mathprint.py`.

## Goal

Render MathPrint expressions exactly as the calculator draws them, glyph-for-glyph
and pixel-for-pixel. Reference screenshot (`screenshot.png`) is the definite
integral entered via `MATH → 9` (`fnInt(`), keys `9 1 RIGHT 2 RIGHT X RIGHT X`:

```
⌠2
⌡  (X)dX           result: 1.5
 1
```

i.e. `∫₁²(X)dX = [X²/2]₁² = (4−1)/2 = 1.5`. The integrand is shown wrapped as
`(X)`, the variable as `dX`, the limits `1`/`2` as small sub/superscripts, and
**the `∫` symbol is TALL** — it spans roughly the full height of the limit stack,
clearly taller than a single 7px character.

## Confirmed facts (read straight from the ROM)

### Fonts — both decoded, bit-exact
- **Large font** (homescreen / `_PutMap`, and MathPrint baseline text): flash
  **page 7, base `0x45FF`, 7-byte stride**. `glyph(code) = ROM[0x45FF + code*7]`,
  7 rows, the 5-pixel glyph in the **low 5 bits** of each row byte. Reached via
  `_PutMap` (`01:5A98`) → bjump `3B3D` → `put_glyph_large` (`07:4588`), which does
  `LD DE,0x45FF; ADD HL,DE` after `HL=code*8`, then `07:45EB` subtracts `code`
  (→ `code*7`) and `_Mov8B`-copies 8 bytes to RAM `0x845A`.
- **Small font** (MathPrint super/subscripts, limits, exponents): flash
  **page 3, base `0x4CD6`, 8-byte stride**. `glyph(code) = ROM[0x4CD6 + code*8]`
  = `[width byte][7 rows]`, the glyph in the **low `width` bits** of each row.
  Reached via `_LoadPattern` (`01:6267`) → bjump `3B61` → `page_03:4A8F`, which
  does `LD DE,0x4CD6; ADD HL,DE` (HL=`code*8`) then `_Mov8B` → RAM `0x8462`.
  Alternate fonts: `3B8B → 07:45B6`, plus `(IY+0x35)` bits 5/1 select localize/hook
  font sources.
- Font codepoint names come from `ti83plus.inc` `L*` equates (240 of them).
  Relevant symbols: `Lintegral=0x08` (a small `∫`), `Lroot=0x10` (`√`),
  `LcubeR=0x0E`, `LsqUp=0x06`/`LsqDown=0x07` (the sub/superscript boxes),
  `Lexponent=0x1B`, `Σ=0xC6`; `0xF5/F6/F7` (MathPrint `_`, fraction slash,
  placeholder box) were added in OS 2.53MP.

### Layout engine (page 0x39) — structure understood
- Cell-grid typesetter. RAM state block `0x85DE–0x85F2`; cursor `(row,col)` =
  word `(85DF,85E0)` read as `BC`, dims `(85E9,85EA)` read as `DE`, counts
  `(85E1,85E2)` written as a word. `0x844B`=curRow, `0x844C`=curCol/overflow.
- **`eqdisp_decr_counters` (39:683D)** maps a cell to a pixel:
  `x = base + 7·col`, `y = base + Σ(row_height + 2)`. Vertical position is purely
  by **row assignment**, so adjacent items align on the math axis.
- **`eqdisp_compute_dims` (39:69C8)** picks a structure's geometry by **kind** =
  `(0x85E8) & 0xF`:
  - kind 0 → descriptor `0x686F`
  - kind 1 → descriptor `0x6880`
  - kind 2 → **fraction** special path (`6A8A`): stacks numerator+denominator and
    draws the bar (`gr_set_window_draw` 39:4833) + end-pieces (glyph `6B5B`/`6B54`).
    This is the **only kind whose height grows with its operands.**
  - kind ≥3 → descriptors `0x689C` / `0x68A5` / `0x6893`
  - Descriptor byte 0 → `0x85EB` (row height); `6BE2` is just `LD E,(HL);INC HL;
    LD D,(HL);INC HL;RET` (a word reader).
- Dispatch: class byte in `0x85DE` indexes the handler pointer table at
  **`0x5E45`** (`HL = 0x5E45 + class*2`, then `_LdHLind`). Context-bias in
  `eqdisp_dispatch_token` (39:4A74): `+0x29` superscript form when `(IY+2)` bit 4
  is **reset** (`4A7F: BIT 4 / JR NZ` skips the `ADD`), `+0x28` fraction-context
  for classes `0x03–0x08` when `(IY+9)` bit 0 set. `eqdisp_set_row_for_tok`
  (39:4CE9) forces classes `[0x24,0x29)` and `0x39` onto a raised row (3/4).
- `eqdisp_emit_glyph` (39:4E8E) dispatches on token high byte `D`: `0x1F` special;
  `0x82` → `A=E-0x3E`, bjump `3B2B`; otherwise `classify_paren` (6675) +
  `map_token_glyph` (4F1A) + emit via `RST 28` / the `2CBB` draw bjump; then
  overflow check (`0x844C ≥ 0x0F`) and cursor-bounds (`4F44`).

## Current residual

The captured definite-integral bitmap now matches in `tools/render-mathprint.py`.
That match uses a bitmap-equivalent stretch of `Lintegral` rather than a full
execution of the ROM's recursive template-placement path.

The old descriptor theory is resolved as a dead end:

1. `0x686F`/`0x6880` are fixed box/menu descriptors, not integral segment tables.
2. `FB CA`/`FB CB` route to menu strings (`n/d`, `Un/d`), and the proven
   `FB D6/D8/D7` cases route to answer-mode strings.
3. `FB C7`/`FB C8` are square marker cases handled around `39:53AD`/`39:4F44`,
   not integral top/middle/bottom bitmap pieces.

The remaining work for full recovery is narrower: trace how the stored `fnInt(`
operator and its argument slots enter the recursive layout path that assigns the
integrand, differential variable, lower bound, and upper bound to baseline,
lowered, and raised rows. Static evidence currently proves the menu/name cells
(`00 C8` for `fnInt(`) and the handler record format, but not every operand-slot
transition inside the final expression renderer.

## Earlier wrong turns (so they aren't repeated)
- "Integrals/summations are CE-only / not 2-D on the mono 84+" — **false**; they
  are 2-D templates (corrected in `docs/sub-equation-display.md`).
- "The `∫` is stroked dynamically (no glyph)" — **false**; `Lintegral 0x08` is a
  font glyph (but the *tall* template `∫` is more than that one glyph).
- `eqdisp_load_glyph18b` "18-byte tall-glyph table at `0x6BA9`" — actually the
  MathPrint **mode-menu string table**.
- `0x82`-token path → `page_01:7183` → `0x71A1` table — that table is **object-
  type name strings** (`Window`, `Function`, `Polar`…), not symbol drawers.

## Renderer status (`tools/render-mathprint.py`)
- Loads both fonts from the ROM; `--font-index` dumps every codepoint + glyph.
- Builders: `glyph`/`text` (large), `sglyph`/`stext` (small), `fraction`,
  `superscript`, `subsup` (sub+superscript on a base), `hcat` (math-axis aligned).
- Examples render correctly: `1/2`, `X²`, `(A+B)/C`, nested `1/(2/3)`, the `Σ`/`∫`/
  `√` glyphs. The `∫₁²(X)dX` example is pixel-equivalent to `screenshot.png`,
  but its tall-symbol construction is still modeled rather than derived from all
  ROM row transitions.

## Recommended next step

Continue tracing the transition from the raw `tFnInt` token (`BB 24`, recognised
by the page-0x02 evaluator) to the page-39 normalized class/action stream used
for display. A dynamic trace is still the fastest proof: breakpoint the page-0x39
render / glyph path while drawing `∫₁²(X)dX`, and capture emitted glyph codes plus
pen `(x,y)` and `(row,col)` state.
