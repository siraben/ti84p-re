# MathPrint rendering — context & open issue

## 2026-06-06 update

The `screenshot2.png` stress case now matches pixel-for-pixel in
`tools/render-mathprint.py`. Keep the provenance split explicit: the glyphs,
handler records, descriptor choices, xrefs, and fraction/rule helpers below are
backed by ROM bytes and page-39 code; the current tall-symbol stretch routines
are ROM-glyph-anchored reconstruction models until their exact callers are
named.

- Compact numeric limit text (`1/2`) uses the ordinary small-font `/`
  (`0x2F`), not the thicker MathPrint `0xF6` fraction-slash glyph.
- `sqrt(X^2+1)` uses the `Lroot` large-font glyph (`0x10`) from the class
  `0x2A`/`0x31` records. The renderer currently models a stretched middle stem
  and a rule vinculum; only the glyph identity, class records, action-to-kind
  route, and rule-helper arithmetic are ROM-backed so far.
- The rule endpoint behavior is backed by `eqdisp_draw_fraction_bar`
  (`39:6ABF`) and `eqdisp_advance_col6` (`39:6B1C`): start from `0x1B`, add
  `7 px` per cell, then expand endpoints in the caller before
  `gr_set_window_draw` (`39:4833`).
- Tall parens are structural stretched-delimiter models in the renderer. They
  are not yet backed by a named ROM delimiter-stretch caller.

Verification command used against `screenshot2.png` downsampled to calculator
resolution: rendered `70 x 25`, mismatch `0 []`.

Residual for **full** recovery: the exact callers that measure tall radicals,
integrals, and delimiters still need to be named. The `fnInt(` operand identity
order is now byte-anchored as an ordered parser-slot pass-through, but the final
row/column placement and tall-symbol construction still need the missing caller
trace. Do not promote screenshot-only stretch behavior to recovered ROM logic
without that trace.

`screenshot3.png` follow-up: this is a different stress expression from
`screenshot2.png`. Downsampling the 192x128 capture to the calculator's 96x64
LCD buffer shows the entry-line expression is the definite integral of
`sqrt((X^2+1)/X)` with the same `1/2` lower limit and `3^2` upper limit, not
`sqrt(X^2+1)`. `tools/render-mathprint.py` now keeps that as a separate
`definite_integral_fraction_radical_example` reconstruction so the pixel-matched
`screenshot2.png` case is not conflated with this taller radical/fraction case.
The screenshot3 model is not yet claimed pixel-equivalent; the old comparison was
`70 x 25` against a `58 x 28` entry box with best offset `(0, 3)` and mismatch
`287` when the answer/cursor lines were excluded.

The radical-fraction form also exposes a structural left sweep / radical wall
around a dynamically tall fraction radicand. The nested fraction itself is on the
ROM-backed kind-2 path (`69C8 -> 6A8A`), but the code path that expands the
surrounding radical/delimiters is still not isolated. Do **not** encode that shape
as a renderer fact until it is tied to the page-39 descriptor/box path
(`69C8` -> `6AF5` -> `4833`) or a specific template caller. Reproducible static
evidence so far:

- `tools/dump-mathprint-layout.py --xref 0x6ABF` -> direct calls only at
  `6998` and `69A0`, both inside the kind-2/fraction cursor redraw path.
- `--xref 0x6B1C` -> direct calls at `6ADA` and `6B14`, the two rule endpoint
  arithmetic callers.
- `--xref 0x68AE` -> the geometry/menu-token dispatcher is reached from
  `4FD9`.
- `tools/dump-mathprint-layout.py --fraction-template-flow` verifies the
  recovered kind-2 fraction template UI: `6A8A` requires `85EE`, draws the fixed
  box via `6AF5`, prints ROM counted strings `ROW:  ` / `COL:  ` plus `OK`,
  uses `6AFD` to invert the focused numerator/denominator extent through
  `_InvertRect`, and uses `6ABF` to draw/erase row rectangles through
  `_DrawRectBorder` / `_EraseRectBorder`. This explains the fraction template
  editor UI and its measured `85EE/85EF` state, but not the surrounding
  radical/delimiter stretch in `screenshot3.png`.
- `tools/dump-mathprint-layout.py --template-state-flow` -> `6761` writes the
  selected kind byte to `85E8` and forces `85DE = 0x48` (`'H'`), `4C40` routes
  that special state to the geometry redraw helper `682A`, and the `4FC4` gate
  sends non-`09`/`40` actions to `68AE`. In that `85DE='H'` state, `68AE` maps
  action `0x48` to kind `0x11`, and `69C8` routes kind `0x11` to descriptor
  `0x6880`.
- `tools/dump-mathprint-layout.py --template-actions` -> class `0x31`
  (`record 0x6433`) has the root/power-family row whose cells begin with
  `00 10` (`Lroot`) and row action byte `0x48`; class `0x2A` (`record 0x654D`)
  has `Lroot` and row action byte `0x62`. Those decoded record bytes are weaker
  evidence than the `85DE='H'` state transition above and should not be treated
  as the final tall-radical caller.
- `tools/dump-mathprint-layout.py --root-flow` -> the root/power records are
  table-driven: handler table entries point class `0x29 -> 6546`, `0x2A ->
  654D`, and `0x31 -> 6433`; the record bodies have no direct page-39 code
  xrefs. Class `0x2A` action `0x62` is not in the geometry-mode action set,
  while class `0x31` action `0x48` maps to kind `0x11` only after `6761` has
  forced `85DE='H'`.
- `tools/dump-mathprint-layout.py --row-action-flow` sharpens that claim:
  `4D92` emits handler-record `row_action[]` bytes through the page-1 indexed
  string bjump, `4DCA` skips those bytes before locating cell payloads, and
  `4F9A` saves an incoming action byte in `B` before dispatching to `68AE`.
  So class `0x31` row action `0x48` is ROM-backed row-label/menu metadata; the
  same byte becomes geometry kind `0x11` only on the separate incoming-action
  path after geometry state is active.
- `tools/dump-mathprint-layout.py --suffix-1f-flow` separates high-byte
  `D=1F` from low-byte `E=1F` cells. The actual `D=1F` special path at `4E8E`
  appears only as class `0x14` cell `1F12`. The root/power and fnInt-related
  cells are low-byte suffix cells (`061F`, `0C1F`, `FE1F`, `FC1F`, ...); they
  fall through the generic `_KeyToString`/`_PutPSB` path and are not direct
  `4F1A` glyph mappings or measured tall-symbol callers.
- `tools/dump-mathprint-layout.py --key-string-1f-flow` pins that generic path
  across pages: page 39 calls `_KeyToString` through inline bcall `45CA`, and
  page `01:6D10` handles `E=0x1F` by computing table index `0x50 + D` before
  copying a token string. This keeps root/power `xx1F` cells in the string path,
  not in a measured-height draw path.
- Raw Ghidra HTTP is usable for disassembly/decompile even though the MCP wrapper
  closes transport here: `get_function_by_address?address=page_39:69C8`
  identifies `eqdisp_compute_dims`, and its decompile confirms kind `2` is the
  `6A8A` fraction path while other kinds walk fixed descriptors.
- `tools/dump-mathprint-layout.py --geometry-flow` verifies descriptor geometry:
  `69C8` selects `686F/6880/689C/68A5/6893` or jumps to `6A8A`, `6A00` reads
  descriptor words through `6BE2`, `6A27/6A4B` walks cells via `683D`, `6B62/6B66`
  handles only known FB menu/answer strings, and `6ABF`/`6B1C` draw fraction
  rule endpoints.
- `tools/dump-mathprint-layout.py --geometry-selector-closed-flow` makes the
  `69C8..6BFE` closure executable. It byte-anchors the selector, descriptor
  reader, cell walker, kind-2 fraction UI, string loader, and width helpers;
  lists every range-local direct call to `683D`, `6A8A`, `6AF5`, `6B1C`, `6B2D`,
  `6B62`, `6BE2`, `6BE7`, `3CDB`, `4833`, `4822`, `4F44`, and `4F6C`; and checks
  the aligned inline `RST 28` sites. The only inline bcalls in that selector/
  helper range are `_DrawRectBorder`, `_EraseRectBorder`, `_DrawRectBorderClear`,
  `_InvertRect`, and `_KeyToString`; `9D27` is absent, and `85EE/85EF` are used
  only by the kind-2 fraction UI. This rules out `69C8` and its immediate helper
  tail as a hidden top/middle/bottom glyph-piece or variable-height glyph loop.
- `tools/dump-mathprint-layout.py --template-chrome-flow` verifies the
  geometry-mode chrome/rectangle emitter: `67A0` saves graph-window state, calls
  `67AC`, restores state, then enters `69C8`; `67AC` clears the template/menu
  rectangle with `_ClearRect`, loops over the literal ROM label string
  `FRACFUNCMTRXYVAR`, draws tab separators through `_DarkLine`, and uses
  `85EE == 0` only to draw the fixed empty-template cue line. `680F` highlights
  the active tab from `85E8 & 0x0F` by inverting one of the tab rectangles. The
  same check anchors
  `_DrawRectBorderClear`, `_DrawRectBorder`, `_EraseRectBorder`, and focused
  `_InvertRect` calls used by descriptor/fraction boxes. This is confirmed
  template UI/chrome emission, not a hidden tall-symbol stretch table.
- `tools/dump-mathprint-layout.py --entry-dispatch-flow` and
  `--geometry-handoff-flow` verify a measured geometry handoff: `496C` and
  `4A74` test byte `0x3D` as an incoming token/action byte before ordinary
  class remap, and `4A74` jumps to `672E`; that path stores either `0` or
  `(9D27)` into `85EE` before forcing `85DE='H'`. The kind-2 fraction branch at
  `696E/697C` is the only page-39 writer of `9D27`, copying the updated
  `85EE/85EF` pair after `6AFD`; the `6753/6758` handoff is the only page-39
  reader. This is ROM evidence for carrying measured fraction geometry into a
  later template redraw, not yet a complete tall-radical/delimiter algorithm.
- `tools/dump-mathprint-layout.py --dispatch-context-flow` byte-checks the
  context-sensitive class algorithm at `4A74`: raw `0x3D` branches to `672E`
  before becoming a class, raw `0x3B` is biased by `(IY+2)` exponent bits 4/6/5,
  and `(IY+9)` bit 0 remaps ordinary classes `0x03..0x08` to `0x2B..0x30`
  before the `5E45 + 2*class` handler lookup. This closes the upstream
  token/action-to-layout-class remap, not the final tall-symbol pixel builder.
- `tools/dump-mathprint-layout.py --template-handoff-guard-flow` tightens the
  `672E` guard. Raw Ghidra HTTP resolves `ram:2077` to `BIT 5,(IY+44)` and
  `ram:36FF` to a bjump into page `04:7FBA`; byte anchors show the page-4 guard
  tests `859A=49`, MathPrintActive, `(IY+44)` bit 6, `(IY+35)` bit 4, and `9B98`
  state. On page 39, `672E` reloads `(9D27)` only on the surviving menu/state
  path; otherwise it seeds `85EE=0000` and still forces `85DE='H'`. The wrapper
  at `6773` sets template box flags, routes through menu/editor state, sets
  `85E8/85DE` through `6761`, and re-enters drawing. This proves a guarded
  state handoff into geometry mode, not the measured tall-symbol piece builder.
- `tools/dump-mathprint-layout.py --template-draw-bridge-flow` pins the draw-pass
  bridge after that state handoff. Raw Ghidra names `49A8` as `eqdisp_begin`,
  `4C40` as `eqdisp_setup_indent`, and `67A0` as `eqdisp_draw_window`; `682A`
  is not split as a function, but byte anchors and xrefs prove the path. `49A8`
  sets template box flags, normalizes state, calls `4A74`, then falls into
  `4A02`; `4A02` calls `4C40`; `4C40` jumps to `682A` only when `85DE=0x48`;
  `682A` is the only direct caller of `67A0`; and `67A0` saves graph-window
  state, draws template chrome, restores, then jumps to `69C8`. The verifier
  classifies both direct `4C40` callers: `4A02` is the normal draw wrapper, and
  `5077` is the generic action-`01/02` row-navigation redraw tail after the
  `4FC4` class-`0x48` gate has already routed template actions to `68AE`. It
  also classifies the extra raw `4A02` word at `650E` as class-`0x27`
  handler-record count/action bytes (`02 4A`), not an indirect draw caller. This
  proves the ROM-backed bridge from recursive template-cell emission into
  descriptor/fraction geometry, but the final variable-height radical/integral
  builder is still delegated below `69C8` or elsewhere.
- `tools/dump-mathprint-layout.py --template-emission-closure-flow` closes the
  direct static exits from that dispatcher. It byte-anchors `4F9A/4FC4/4FD9`,
  the record-cell loop at `4DE6 -> 4E8E`, the saved-operand cell tail
  `5B63 -> 4E8E`, and the delimiter classifier call `6692 -> 3B37`. Its xref
  audit proves `68AE` has only the `4FD9` page-39 caller, `4E8E` is reached only
  from `4DF5/5B63`, page 39 never directly calls the large-font blitter bjump
  `3B3D`, `_VPutMap` calls are confined to the descriptor/string output tail
  inside `69C8..6BFE`, `6ABF/6B1C` stay scoped to the kind-2 fraction path, and
  `_FillRect`/`_FillRectPattern`/`_DisplayImage` bcalls are absent. This rules
  out a hidden direct draw exit from template actions to tall-symbol pixels; the
  remaining proof needs either an off-path caller or a dynamic pen/glyph trace.
- `tools/dump-mathprint-layout.py --geometry-action-flow` recovers the action
  algorithm in raw Ghidra's `eqdisp_layout_token_geom` (`39:68AE`). While
  `85DE=0x48`, actions `49/48/2E/5A` choose template kinds `10/11/12/13`;
  descriptor-backed kinds use actions `3/4` for row movement, action `5` for
  current-cell dispatch through `595F -> 53AD`, and direct `8F..97` visible-slot
  selection. Kind `12` is the measured fraction editor: action `5` calls `6AFD`,
  updates `85EE/85EF`, copies the pair to `9D27`, and redraws focus; actions
  `1/2/3/4` adjust columns/rows by erasing/drawing through `6ABF`. This is the
  editable template-geometry action path, not a variable-height glyph table.
- `tools/dump-mathprint-layout.py --measured-state-flow` audits the remaining
  obvious page-39 measured-state words. The non-geometry `85E9` read at `5BD7`
  is inside the saved-OP/list-token class-`0x10` branch: it writes
  `8446=85E9+0x77` for small indices or takes a class-49 menu/editor path for
  larger indices. The actual descriptor geometry producer/consumer remains
  `6A00`/`683D`, while `85EE/85EF/9D27` remain scoped to the measured
  fraction/template handoff. This rules out that `85E9` outlier as the
  tall-symbol emitter.
- `tools/dump-mathprint-layout.py --class10-saved-tail-flow` closes the earlier
  class-`0x10` saved-tail branch at `5B66`: it calls `66AB`, which is
  `_ChkFindSym` plus the no-op `1785` check and optional `'*'` output, then
  checks `85E8`/adjacent `85E9` before the only ROM-wide `RST28 51F7` bcall at
  `39:5B85` followed by erase-to-EOL. The raw bcall table resolves `51F7` to
  `35:6485`, a string-output wrapper that selects a ROM string, copies 18 bytes
  to `keyForStr` (`9D76`), and prints through `_PutS` (`01:5C39`). The branch
  has no `85EE/85EF/9D27` refs, no descriptor-height loop, and no repeated
  glyph-row construction.
- `tools/dump-mathprint-layout.py --emit-boundary-flow` verifies the
  record/operand/geometry boundary: `4C40` sends only `85DE='H'` into geometry
  redraw, `4CDF/4CE4` enter the saved-OP or named-argument bridges, `59D0`/
  `59E0`/`59F9` are parser-token operand emitters, and `6ABF`/`6B1C` have only
  fraction-path direct xrefs (`6998`/`69A0` and `6ADA`/`6B14`). This rules out
  those ordinary operand emitters and fraction-rule helpers as the missing
  tall-radical/integral builder.
- `tools/dump-mathprint-layout.py --glyph-emission-flow` verifies the decoded
  cell/display boundary: `4E8E` emits record/descriptor cells generically,
  `4F1A` directly maps only `FC3C..40`, `FE7D..81`, and `xx42` cells to
  large-font codes. Class `0x0D` row 0 contains `FC3C..FC40`, including
  `FC3F -> L08` (`Lintegral`), and row 2 contains `0042..0942`, including
  `0842 -> L08` (`Lintegral`), but `00C8`/`00C7` are not direct integral/
  derivative glyph mappings. The `FB` string loader at
  `6B62/6B66` only copies `FBCA/FBCB/FBD6/FBD8/FBD7` menu/answer strings, and
  page `07:4588` is fixed `45FF + code*7` stride / 8-byte-record glyph-copy
  machinery, not a tall-symbol stretch routine.
- `tools/dump-mathprint-layout.py --structural-glyph-census` makes the
  structural-glyph search executable: `FC3F` (`Lintegral`) appears at page-39 raw
  hit `6110`, inside class `0x0D` row 0, and `0842` (`Lintegral`) appears at raw
  hit `6144`, inside class `0x0D` row 2; `0010` (`Lroot`) appears only at
  `6438/6550`, inside class `0x31`/`0x2A` root/power rows; `00C6` (`Σ`
  candidate) has no page-39 raw hit and no decoded record/descriptor hit; and
  `00C8`/`FB C8`/`FB C7` are only the `fnInt(`/template-menu cells already
  known. This rules out the obvious page-39 raw cells and decoded
  record/descriptor cells as hidden tall-symbol recipes.
- `tools/dump-mathprint-layout.py --structural-symbol-flow` pins the emission
  side of those cells and now prints the class/row provenance split. `00C8` is
  selected from class `0x08`/`0x30` row 0 slot 8 under the `MATH` row label,
  while `FC3F` and `0842` are class `0x0D` structural cells, so the `fnInt(`
  menu cell is not the direct `Lintegral` glyph cell. `FC3F` and `0842` are
  fixed-glyph paths:
  `4E8E -> 6675 -> 66A0 -> 4F1A -> RST28`, mapping the `FC3C..FC40` branch and
  the `xx42` branch to large-font code `L08` for `Lintegral`. `0010` (`Lroot`)
  is a root/power record cell but not a `4F1A` direct glyph; it falls through the generic
  `6B66 -> _KeyToString` string path. Neither path consumes measured height,
  repeat counts, or fraction/rule endpoints.
- `tools/dump-mathprint-layout.py --structural-record-placement-flow` closes the
  fixed-record false shortcut: class `0x0D` at `60F9` is a three-row
  `NAMES`/`MATH`/`EDIT` record selected by raw byte `0x37`, with `FC3F` and
  `0842` emitted by ordinary row-cell placement through `4DE6/4E8E/4F1A`.
  `BB24` (`tFnInt`) and `BB25` (`tNDeriv`) remain page-7 parser-token table
  entries, so this fixed structural record is not the inserted definite-integral
  template or its final tall-symbol placement caller.
- `tools/dump-mathprint-layout.py --structural-piece-census` audits ROM glyph
  codepoints `L08`/`L10`/`LC6`/`LF5`/`LF6`/`LF7` against decoded page-39 record
  and descriptor cells. `Lintegral` has direct record cells `FC3F` and `0842`;
  `Lroot` appears as literal `0010`; `Sigma` and the MathPrint `F5`/`F6`/`F7`
  piece candidates have no decoded page-39 record/descriptor hits. The same
  census checks ROM-wide bitmap byte patterns: the fixed `Lintegral` bytes
  appear at `07:4637` and `3F:46B8`, fixed `Lroot` at `07:466F`, and fixed
  `Sigma` at `07:4B69`, while modeled tall-integral and tall-root
  stretch-family byte sequences are absent ROM-wide for heights `8..40`. It
  also byte-anchors the raw `0008` hit at `39:6D49`
  as an `HL=0008` state-save literal inside the class-49 path, not a glyph cell.
  That rules out decoded top/middle/bottom piece tables and modeled bitmap-table
  copies, but does not recover the later pixel-placement routine.
- `tools/dump-mathprint-layout.py --structural-immediate-draw-flow` closes the
  related procedural-immediate false lead. It scans ROM-wide for structural
  glyph/piece code bytes `08/10/C6/F5/F6/F7` loaded by simple immediate forms
  (`LD A/E/D/L/B/C,n`) within `+/-0x40` bytes of display/draw services
  (`3B37`, `3B3D`, `3CDB`, `_DarkLine`, `_PutPSB`, and rectangle/invert
  bcalls). The complete hit set is nine byte-checked contexts: page-1 fixed
  glyph-copy count / `_KeyToString` branch constants, page-3/page-5/page-37/
  page-3B UI or graph constants, page-39 template-chrome line coordinate
  `67E7`, and one unaligned raw `2E F5` false positive inside a `CALL` operand
  at `39:6C32`. There are no unexpected hits, so no hidden procedural load of
  `Lintegral`/`Lroot`/`Sigma`/MathPrint-piece code remains near those draw
  services.
- `tools/dump-mathprint-layout.py --menu-cell-flow` verifies the active
  menu/template-cell dispatch path: internal action `0x05` loads the current
  row/descriptor cell through `5955`; `52E5` sends `C == 0x82` cells to the
  recursive token-display path (`9D2C` + `49A8 -> 4A74`), otherwise the flow
  proceeds through edit/menu guards, the two-byte form selectors, and `53AD`.
  The `FB C7/C8` square-marker cells call the page-0/RAM stub at `3891` with
  action bytes `6/7/8`; in the current 64-page ROM model the inline page byte
  resolves to page `3D:7CBA`. Raw Ghidra identifies that target as
  `j_flash_obj_dispatch`, and the byte anchors show action `7 -> BC=0804`,
  action `6 -> BC=0402`, and both pass through page-3D `7DC4` flash/object
  bit-mask checks. The branch then restarts `eqdisp_layout_main` with internal
  action `0x09`. This is template-control flow, not the final tall-symbol
  measurement routine.
- `tools/dump-mathprint-layout.py --active-cell-recurse-flow` closes the
  recursive-token side of that split. The verifier byte-checks the
  `52DA -> 5955 -> 52E5` action-`0x05` gate, the `52E5 -> 49A8` recursive
  entry, the `595F` selected-cell scanner, and the non-`82` continuations at
  `5373`/`53AD`. The only decoded handler-record cells with high byte `0x82`
  are in classes `0x0B`, `0x0C`, and `0x20`; `00C8` (`fnInt(`),
  `FB C8`/`FB C7`, `FC3F`/`0842` (`Lintegral`), and `0010` (`Lroot`) are not
  in that prefix set. Therefore action `0x05` does not transform the `fnInt(`
  menu cell or square markers into the fixed structural glyph records through
  the `49A8` recursive-token path.
- `tools/dump-mathprint-layout.py --descriptor-marker-flow` verifies the same
  square-marker cells inside the descriptor walker. Descriptor `6880` contains
  `FE09`, `FB C8`, `00 C7`, `00 C8`, `FB C7`; the class `0x08/0x30` records
  contain the same operator family in row 0. The descriptor loop at `6A4B`
  loads each two-byte cell, runs known `FB` strings through `6B62`, measures
  width through `6BE7`, then calls `4F44`. Raw Ghidra names `4F44`
  `eqdisp_cmp_cursor_bounds`, but the bytes compare `DE` against `FB C8` and
  `FB C7` and dispatch page-3D actions `7` and `6` through `3891`; marker hits
  can then enter `4F6C` (`eqdisp_setnorm_split2`) for split/display
  normalization. This is descriptor square-marker handling, not hidden
  tall-symbol drawing.
- `tools/dump-mathprint-layout.py --marker-retouch-flow` isolates that final
  line helper. The decoded-cell tail calls `4F62` only after the `4F44`
  `FB C8`/`FB C7` marker gate; the descriptor-cell loop calls shared helper
  `4F6C` only from `6A66`, with `A=86D8-1`, `B=1D`, and `D=46`. Raw Ghidra
  identifies `4F6C` as `eqdisp_setnorm_split2`; the bytes normalize split/window
  state and call the RAM trampoline `00:3555 -> 04:4025` (`_DarkLine`). The
  local retouch windows contain no `85EE`/`85EF`/`9D27`, so this is fixed
  marker/split retouch, not the measured tall-symbol pixel builder.
- `tools/dump-mathprint-layout.py --two-byte-form-flow` audits the selector
  tables behind that branch using raw ROM bytes plus raw Ghidra identities.
  Ghidra names `39:5E1F` as `eqdisp_lookup_tbl_6203`, `39:5E26` as
  `eqdisp_lookup_tbl_63e3`, and `39:5E32` as `eqdisp_table_lookup2`; ROM bytes
  expose the unsplit sibling at `39:5E2D` for table `63C3`. The decoded tables
  are `6203` (14 entries), `63E3` (4 entries), and `63C3` (16 entries).
  `BB24`/`BB25`, `00C8`, `FB C7/C8`, `0842`, `0010`, and `00C6` have no hit in
  any of those tables, so the form selector is not the missing `fnInt(` field
  mapper or tall-symbol stretch recipe.
- `tools/dump-mathprint-layout.py --square-marker-flow` follows the `FB C7/C8`
  path through the off-page ROM code. `FB C8` tests page-3D action `7`, then on
  success calls bcall `_grc_4611` (`52FF -> 37:4611`) with `A=8`; `FB C7` tests
  action `6`, then calls `_grc_4611` with `A=7`. Page `3D:7CC6` maps those tests
  to bit-mask pairs `0804` and `0402`, and the `7D5A/7D76/7DB2/7DC4` helper
  cluster preserves `OP1` type while deriving/testing the bit mask. `_grc_4611`
  selects disabled-feature messages (`A=8 -> summation`, `A=7 -> logBASE(`),
  so this is ROM-backed square-marker disabled-feature handling, not a
  measured-height template emitter.
- `tools/dump-mathprint-layout.py --class49-flow` verifies the other special
  dispatcher state at `4FC4`: `85DE=0x48` routes non-`09`/`40` actions to
  geometry dispatch (`68AE`), while `85DE=0x49` jumps to `6CC1`. The class-49
  branch is menu/editor handling: `6D54` forces `85DE=49` and calls `_edt_69f8`
  (`5461`), `6CC1` handles action `0x40` by restoring menu/app state and calling
  `mnu_show_and_getkey` (`5466`), and `6CEC` normalizes `FF`/`FE`/`FC`/`FB`
  cells before `_edt_6bd1` (`5458`). The verifier now also closes the direct
  class-49 entries: `6CB9` is reached only from menu/saved-OP post-state paths
  (`53DF`/`5BE8`), and `6CC1` only from the dispatcher gate (`4FC9`). Its local
  `6CB9..6DE3` window has no
  `85E8/85E9/85EB/85EC/85EE/85EF/9D27/86D7` measured-template refs. The only
  decoded handler row action `0x49` is class `0x06` row 0. This rules out
  `85DE=49`/`6CC1` as the hidden tall-template geometry branch.
- `tools/dump-mathprint-layout.py --bjump-flow` verifies the display-service
  boundary below page 39: `3B2B` lands at page `01:7183` and prints indexed
  strings, `3B37` lands at page `07:44DE` and maps token display bytes,
  `3B3D`/page `07:4588` is the large-font glyph blitter, and `3CDB`/page
  `01:6293` is `_VPutMap`. Page 39 calls `3B2B` at `4D08/4DB3/4EC6`, `3B37`
  at `6692`, and `3CDB` only in descriptor/fraction geometry. This bjump layer
  consumes positions/classes chosen by page 39; it is not the hidden
  tall-template layout builder.
- `tools/dump-mathprint-layout.py --indexed-string-caller-flow` closes the
  caller/body side of the `3B2B` indexed-string bjump. Raw Ghidra identifies
  `01:7183` as `put_indexed_string`, whose decompilation indexes the page-1
  pointer table at `71A1` and prints the selected string. A ROM-wide
  `CALL 3B2B` scan finds only page-39 callers `4D08`, `4DB3`, and `4EC6`; local
  `+/-0x60` windows around them contain row/menu-title state (`844B/844C`,
  `85DE`, `85DF`, `85E0..85E2`) but no `85E8/85E9/85EB/85EC/85EE/85EF/9D27`
  measured-template refs. The page-1 target body also has no measured-template
  refs, so `3B2B` is fixed row-label/string output, not a tall-symbol builder.
- `tools/dump-mathprint-layout.py --overflow-flow` verifies the horizontal
  overflow/erase boundary and corrects the previous page-0x3A attribution:
  page-39 `4F08` calls bjump `3CB7` when `844C >= 0x0F`, and `3CB7` lands at
  page `01:61C5` (`_EraseEOL`), which fills remaining columns with spaces and
  restores `844C`; `3CBD` lands at page `01:61F4` for erase-to-end-of-screen.
  `6712` only sets `844C=1`, emits `':'` through `3FDB`, and gates display
  modes via `85E5`. This is page-1 display cleanup, not a separate MathPrint
  template-emission page.
- `tools/dump-mathprint-layout.py --mathprint-mode-flow` verifies the
  MathPrint/Classic selector: page `01:5A07` contains the `MATHPRINT`/`CLASSIC`
  mode strings as data, while the executable option handlers are page `02:7AA2`
  and `02:7AB9`. `(IY+0x44)` bit 5 is the persistent MathPrintActive flag, and
  `(IY+0x48)` bit 0 is only the `n/d` vs `Un/d` fraction-display selector.
- `tools/dump-mathprint-layout.py --draw-primitive-flow` verifies the page-39
  draw primitive census. Raw Ghidra HTTP reports 25 executable page-39 `RST28`
  callsites after collapsing duplicate parent functions, and the verifier
  byte-checks each against `tools/rom.bin`. The draw-relevant inline bcalls are
  `_PutPSB` at `4EE6`, template chrome rectangles at `67B6`/`6826`,
  descriptor/fraction rectangles at `6AE9`/`6AEE`/`6AF8`/`6B17`, and
  `_KeyToString` at `6B9C`; the other callsites are menu/editor/app/display-state
  helpers. The extra raw-byte candidate at `4F04` (`51F4`) is now resolved:
  bcall table entry `3B:51F4 = D1 60 75` points to page `35:60D1`, a
  display/menu helper that saves/restores `92FC`, changes `97A6`, derives graph
  pen `y` from `844B`, writes fixed graph pen `x` positions, and calls page-1
  display helpers; it has no `85EE/85EF/9D27` measured-state input. The other
  raw-byte candidate at `5D90` is `_RestoreDisp` inside the display-buffer
  wrapper closed by `--restore-display-flow`. `_FillRect`, `_FillRectPattern`,
  and `_DisplayImage` have no page-39 inline call sites, and page 39 has no
  direct call to the large-glyph bjump `3B3D`. The same verifier now accounts for the
  non-`RST28` line primitive: every page-39 `CALL 3555` resolves through the RAM
  trampoline to page `04:4025` (`_DarkLine`), and the complete caller set is
  `4F84`, `67E1`, `67EB`, `67F3`, and `680C`. Those are post-marker split/window
  retouch and template chrome tab/empty-cue lines; the only measured-state touch
  is `6802` reading `85EE` as a zero/nonzero guard for the fixed empty-template
  cue. This rules out another local rectangle/fill/image/line primitive as the
  missing tall radical/integral stretcher.
- `tools/dump-mathprint-layout.py --graph-table-helper-flow` closes the nearby
  low-level graph-table helper lead. Raw Ghidra names `39:66DC` as
  `gr_draw_tbl_glyph`, but the verifier byte-checks the helper and proves it has
  no page-39 direct or raw xrefs. The graph-window setup helper `4833` is called
  only by `67A0`, `6AE4`, and `6AF5`, and the restore helper `4822` only by
  `67A6` and `6AF1`; those callers are template chrome plus
  descriptor/fraction rectangle wrappers, not a procedural tall-symbol glyph
  stretcher.
- `tools/dump-mathprint-layout.py --lcd-capture-flow` verifies the direct LCD
  I/O path found in page 39. Raw Ghidra names `39:5DD1` as
  `lcd_screen_shift_capture` and the fall-through body at `39:5DD8` as bcall
  `_SaveDisp`; the ROM bytes set `HL=9872`, write LCD commands through port
  `0x10`, and read 64 columns of 12 bytes through port `0x11` into
  `appBackUpScreen`. The only page-39 xrefs are the render-loop context gates
  and the direct `_SaveDisp` caller, so this is display capture/save plumbing,
  not token/class dispatch or measured tall-symbol drawing.
- `tools/dump-mathprint-layout.py --restore-display-flow` closes the paired
  page-39 `_RestoreDisp` wrapper that raw Ghidra does not split as a function.
  `39:5D86` saves `(IY+0x14)`, clears bit 1, calls `_RestoreDisp`
  (`EF 70 48`), restores `(IY+0x14)`, and returns. Its exact direct caller set
  is `4AD3`, `579E`, `5873`, `5DA1`, and `6C26`; those paths load `9872`
  (`appBackUpScreen`) or `86EC` before restoring a display buffer, and their
  local windows have no `85EE`/`85EF`/`9D27` measured-template refs. This is
  display restore plumbing, not a tall-symbol emitter.
- `tools/dump-mathprint-layout.py --draw-mode-callback-flow` verifies the
  opaque `2CBB` draw-pass callback: the page-0 stub jumps to `3B:7CA8`, page 39
  reaches it only from draw-mode gates, and page 3B checks/stores `HL/A` triples
  in `9Bxx` draw-state slots while setting or clearing `(IY+0x36)` bits. The
  verifier now also scans the page-39 hook windows and page-3B `7ABF/7CA8/7DB0`
  local windows: they have no `85EE/85EF/9D27` measured geometry and no
  local draw/display services beyond the ordinary `_PutPSB` continuation after
  the page-39 cell-emitter hook. This is state validation, not glyph output or
  measured template drawing.
- `tools/dump-mathprint-layout.py --large-font-flow` verifies the off-page
  large-font boundary: page `07:44DE` maps display bytes, `07:4588` uses
  `07:45EB` to turn `_PutMap`'s `code*8` offset into the real
  `0x45FF + code*7` table pointer, then copies a fixed 8-byte render record into
  `845A`; `07:45FB` is a fixed seven-iteration shifted-copy helper. None of
  these page-7 paths reads template dimensions or measured radicand state, so it
  is not the missing tall-symbol builder.
- `tools/dump-mathprint-layout.py --display-byte-map-flow` decodes `07:44DE` as
  a fixed prefix/table remapper. `FE` uses `4099`/`4102`, `FC` uses `422C`, `FB`
  uses `4426` after the low-byte bias, and ordinary inputs require `A>=5A`.
  Sample ROM mappings include `FB C8 -> EF33`, `FB C7 -> EF34`, `FE A7 -> 6000`,
  `FC00 -> 6100`, and `FC8C -> BB1B`; `00C8`/`00C7`, `0842`, and `0010` are not
  valid direct inputs. This is also not the measured tall-symbol builder.
- `tools/dump-mathprint-layout.py --display-byte-caller-flow` closes the caller
  side of that page-7 display-byte mapper. A ROM-wide `CALL 3B37` scan finds only
  `01:6D31`, `03:4684`, `04:477B`, `05:420D`, `06:4592/47E9/4901`, `34:4634`,
  `37:618F/6535`, and `39:6692`. Local `+/-0x60` windows around those callers
  contain only ordinary display row/column or graph pen refs (`844B/844C` or
  `86D7`) plus the page-39 fixed delimiter classifier's `85DE` test; none has
  `85E8/85E9/85EB/85EC/85EE/85EF/9D27`. The page-7 `44DE..453A` classifier body
  also has no measured/template refs. Raw Ghidra names `07:44DE` as
  `arc_chk_type`, but the bytes are the fixed `FE`/`FC`/`FB` display-byte
  classifier, so `3B37` is closed as a fixed remap surface rather than a hidden
  variable-height template builder.
- `tools/dump-mathprint-layout.py --offpage-render-flow` extends that audit to
  the display-service callers. `_PutMap` (`01:5A98`) clamps the display code,
  computes `code*8`, and calls the `3B3D` bjump; its row loop is fixed at
  `B=8`. `_LoadPattern` (`01:6267`) and the page-6 helper at `7F66` also compute
  `code*8` and call fixed pattern/glyph copy helpers. The only ROM-wide direct
  `3B3D` call sites are `01:5ABC`, `01:627D`, and `06:7F6C`; `_FillRect`,
  `_FillRectPattern`, and `_DisplayImage` have no inline bcall sites anywhere
  in the ROM. Off-page `9D27` writes at `35:734E` and `37:6D30` just seed the
  default `0202` measurement during reset/startup. This rules out the generic
  display/blit service as the hidden measured tall-symbol emitter.
- `tools/dump-mathprint-layout.py --glyph-service-closed-flow` is the stricter
  closed-world version of that boundary. It byte-checks `_PutMap`,
  `_LoadPattern`, the unsplit page-6 helper, `put_glyph_large`, and the
  `07:45EB` stride adjuster; raw Ghidra names `01:5A98` as `_PutMap`,
  `01:6267` as `_LoadPattern`, and `07:4588` as `put_glyph_large`. A ROM-wide
  `CALL 3B3D` scan finds only `01:5ABC`, `01:627D`, and `06:7F6C`, and each is a
  fixed `code*8` glyph/pattern service caller. The same verifier checks that
  inline `_FillRect`/`_FillRectPattern`/`_DisplayImage` bcalls are absent
  ROM-wide and that off-page `85EE/85EF/9D27` word references do not form a
  measured variable-height glyph builder.
- `tools/dump-mathprint-layout.py --large-glyph-caller-flow` tightens the
  caller side of that proof. It scans local windows around all `CALL 3B3D`
  sites (`01:5ABC`, `01:627D`, `06:7F6C`) and the page-7 `put_glyph_large`
  body. The only state in the `_PutMap` caller window is ordinary `844B/844C`
  display row/column state; none of the windows references `85EE`, `85EF`, or
  `9D27`, and none contains fill/image/line draw primitives. This rules out the
  off-page large-glyph bjump caller surface as the measured tall-symbol builder.
- `tools/dump-mathprint-layout.py --vputmap-caller-flow` closes the page-1
  `_VPutMap` bjump surface. Raw Ghidra identifies `01:6293` as `_VPutMap`, whose
  body uses `86D7/86D8` pen coordinates and `_LoadPattern` but has no
  `85EE`/`85EF`/`9D27` refs. ROM-wide `CALL 3CDB` sites are enumerated; the
  page-39 callers are exactly `6A39/6A3E/6A43/6A48`, `6AB0/6AB5`,
  `6B3C/6B41/6B46/6B4A`, and `6BF4`. The only caller windows with nearby
  template/measured refs are the already-closed descriptor-cell and kind-2
  fraction UI windows, so `_VPutMap` is small-label pixel output, not the final
  tall integral/radical builder.
- `tools/dump-mathprint-layout.py --offpage-state-intersection-flow` byte-audits
  the remaining page-level off-page intersections after that broad census. Page
  6 shares `85E8`/`85DE` action state in a key/cursor helper and preserves
  `86D7` around one `3CDB` cursor draw, but it has no local
  `85EE/85EF/9D27` geometry refs. Page 7 clears `85DE`/`984B` in an
  editor/parser cleanup path, while its nearby draw helper has no MathPrint
  state refs. Page 37 tests `85DE` in an app/UI helper, writes fixed coordinates
  to `86D7`, and seeds `9D27=0202` during startup/default setup. These are
  cursor/UI/startup false positives, not measured tall-symbol emitters.
- `tools/dump-mathprint-layout.py --offpage-draw-state-flow` adds a broader
  page-granularity census: it scans ROM-wide for plausible Z80 word-operand
  references to MathPrint state words (`85DE..85F2` plus `9D27`) and intersects
  those pages with display/draw byte patterns (`CALL 3555 -> _DarkLine`, `3B37`,
  `3B3D`, `3CDB`, rectangle bcalls, `_PutPSB`, `_RestoreDisp`, line/point/circle
  graph command wrappers, and graph-table helpers). It filters inline bcall/data
  byte coincidences by requiring a plausible word-operand prefix. The high-risk
  intersections are now explicit: `85EE` appears with draw/display services on
  pages `33`, `34`, and `39`; `85EF` only on page `39`; `9D27` on pages `35`,
  `37`, and `39`. The expanded command-level set adds only non-measured
  page-level coincidences (`_PixelTest`, `_DrawCirc2`, `_DrawZeroOP1`,
  `_GraphParseTok`, `_VertSplitDraw`, `_Regraph`, `_grf_5e06`, and graph-table
  helpers); the local command-helper windows have no `85EE`/`85EF`/`9D27` refs.
  The page-35 `9D27`/`_DarkLine`
  intersection is only page-granular: the byte-checked local window around
  `35:6887` uses `86D7` and fixed `0x3F/0x39` line coordinates before
  `_DarkLine`, while the `9D27` default `0202` seed is far away at `35:734F`.
  Page-5 `_DarkLine` callers are graph helpers with no MathPrint state refs, and
  page-39 `_DarkLine` callers remain chrome/post-marker retouch. Nearest
  same-page draw-service distances still make pages `33`/`34` the only off-page
  `85EE` static candidates audited by the next verifier.
- `tools/dump-mathprint-layout.py --direct-pixel-surface-flow` closes the lower
  direct-pixel bypass possibility. It scans ROM-wide for `plotSScreen` (`9340`),
  `appBackUpScreen` (`9872`), display-backup buffer `86EC`, and direct LCD port
  I/O (`OUT 10`, `OUT 11`, `IN 11`) before intersecting those pages with
  MathPrint state refs. Page 39 has no direct `plotSScreen` word refs, and its
  direct LCD I/O is confined to the `_SaveDisp`/`_RestoreDisp` buffer path. The
  local windows prove page-33 `85EE` and `86EC` refs are separated, page-35 and
  page-37 LCD helpers are separated from their `9D27` default seeds, and the
  page-39 measured geometry window `6750..6B30` has no direct LCD port I/O or
  graph/backup-buffer word refs.
- `tools/dump-mathprint-layout.py --pen-surface-flow` closes the related
  staged-pen-coordinate bypass. It scans ROM-wide `86D7/86D8` word refs,
  intersects them with draw/display services, and byte-checks local high-risk
  windows. Off-page pen/draw intersections are page-6 cursor preservation around
  one `3CDB` call, fixed page-35/page-37 UI/display helpers, or generic graph/
  text pages with no `85EE/85EF/9D27` measured geometry. Page-39 intersections
  are template chrome, descriptor cell emission, or kind-2 fraction UI already
  closed by the local geometry verifiers.
- `tools/dump-mathprint-layout.py --offpage-85ee-candidate-flow` byte-anchors
  and closes those page-33/page-34 candidates as non-renderers. `33:4F42` is a
  `0x2B` token/value helper that loads `HL=(85EE)`, scales the count through
  `_HTimesL` (`00:1EF6`), and returns offsets; `34:4880` stores `85EE` into an
  object/record field at offset `+0x12`; `34:4DC8` copies a stream word into
  `85EE`; and `34:5130` seeds `85EE=0101` inside parser/object case handling.
  The extended verifier also byte-checks the surrounding page-33 prologue,
  page-34 parser/object switch, page-34 parser wrapper, and off-page `9D27`
  reset/startup seeds. It now asserts the page-local control-ref closure
  (`4F42` is reached only by `33:4F3B`; `34:4880/4DC8/5130` have no direct/raw
  page-local word refs) and byte-checks helper/context bodies for `_HTimesL`
  (`00:1EF6`), `_CpHLDE` (`00:21BB`), `33:4F3B`, and `34:4DCA`. The candidate
  windows contain only `85EE` among the measured-state words, have no local
  draw/display pattern within `+/-0x100` bytes, and are parser/evaluator/object
  bookkeeping rather than tall-symbol emitters.
- `tools/dump-mathprint-layout.py --delimiter-flow` verifies the page-39
  paren/delimiter classifier: `62CB`, `62E2`, and `62F9` are fixed ten-entry
  display-cell pair tables; `6667` scans exactly ten entries; `6675` tries those
  tables, stores matched low bytes in `8446`, and routes matched high bytes
  through bjump `3B37`; unmatched cells fall back to `4F1A`. This is ROM-backed
  fixed delimiter-pair mapping, not a measured-height delimiter builder.
- `tools/dump-mathprint-layout.py --delimiter-display-map-flow` follows those
  fixed pairs through the page-7 display-byte classifier. The three page-39
  delimiter tables map to fixed encoded families `6100..6109`, `6000..6009`,
  and `AA00..AA09`; all 30 entries are byte-checked against the page-7
  `FE`/`FC` pair-table logic. Raw page-39 coincidences for `6000/6002/6003` are
  not decoded records or descriptors. This closes the fixed delimiter-map
  surface; it still does not name the dynamic caller that chooses a tall
  delimiter variant.
- `tools/dump-mathprint-layout.py --delimiter-record-family-flow` proves those
  fixed delimiter families are backed by ROM handler records, not just free
  table bytes: handler classes `0x17/0x18/0x19` point to `62C8/62DF/62F6`,
  each record has one ten-cell row, and actions `31/3F/52` carry the cells that
  page 7 maps to `6100..6109`, `6000..6009`, and `AA00..AA09`. The cells have
  decoded record provenance and no descriptor provenance. The remaining gap is
  still the upstream dynamic variant selector.
- `tools/dump-mathprint-layout.py --cell-emission-algorithm-flow` closes the
  final decoded-cell emitter at `39:4E8E`: `D=1F` uses the IX-backed OP/string
  special form, `D=82` enters the indexed-string bjump path, all other cells go
  through the delimiter classifier, optional `6B66`/`_PutPSB` string output, and
  then the direct `4F1A` fixed-glyph mapper. The overflow/square-marker tail at
  `4F08`/`4F44`/`4F62` has no measured-height input, repeat loop, or variable
  line/fill primitive; its `_DarkLine` caller is split/window retouch.
  This proves the final cell-emission algorithm is fixed-cell/string/control
  handling; any remaining tall-symbol placement must happen before this cell
  stream or in a dynamic pen/glyph trace.
- `tools/dump-mathprint-layout.py --generic-string-caller-flow` closes the
  optional string branch inside that emitter. It byte-anchors the page-39
  `4ECB..4F08` generic cell tail, the `6B62/6B66` FB string selector and
  `_KeyToString` fallback, and page-1 `_KeyToString` (`01:6D10`). Page-39 direct
  output sites are exactly `4EE3` (`CALL 6B66`), `4EE6` (`_PutPSB`), `6A52`
  (`CALL 6B62` from the descriptor walker), and `6B9C` (`_KeyToString`); no
  unexpected page-39 string-output site remains. Local windows around the
  generic tail, selector body, and `_KeyToString` body have no
  `85E8/85E9/85EB/85EC/85EE/85EF/9D27` measured-template refs, so this path is
  fixed counted-string output, not a variable-height template builder.
- `tools/dump-mathprint-layout.py --fnint-token-flow` verifies the cross-page
  token/display bridge: page 7 contains the `BB24` extended-command table entry,
  page 2 recognises second byte `0x24` as `tFnInt` and `0x25` as `tNDeriv`,
  page 1 has the `C8 06 "fnInt("` / `C7 07 "nDeriv("` display strings, and
  page 39 uses `00C8`/`00C7` display cells in class `0x08`/`0x30` records and
  descriptor `0x6880`. This proves identity only; the operand-slot order is
  handled by `--fnint-argument-order-flow`.
- `tools/dump-mathprint-layout.py --extended-token-table-flow` tightens the
  page-7 side of that bridge: `BB24` and `BB25` occur only in page-7
  extended-token table data, the `42EE`/`42F6`/`428A` table-entry addresses have
  no page-local word refs, and the reachable `50B5`/`50B8` consumers are
  parser/editor scanner entries. This rules out the raw `BB24` token table as a
  hidden tall-symbol renderer.
- `tools/dump-mathprint-layout.py --fnint-template-flow` verifies the next
  operator/menu boundary: page `01:7183` resolves row-action bytes through the
  indexed string table, so class `0x08`/`0x30` rows label as `MATH`, `NUM`,
  `CPX`, and `PRB`; in both records `nDeriv(` is `MATH` row slot 7 and
  `fnInt(` is `MATH` row slot 8, followed by square-up/down markers in slots
  9/10. The same check byte-anchors the page-2 evaluator prologue for
  `BB24`/`BB25`. This proves operator row/slot identity, not final visible
  integrand/variable/lower/upper placement.
- `tools/dump-mathprint-layout.py --fnint-eval-flow` verifies the evaluator-side
  `fnInt(` FPS flow. Raw Ghidra names page `33:4D00` as `fnint_body`; the
  prologue calls `_CpyTo2FPS3`, `_CpyTo1FPS2`, `_FPSub`, and `_TimesPt5`, so it
  consumes parsed FPS slots 2 and 3 as interval endpoints and halves their
  difference. The same verifier anchors the page-2 `BB24` branch and the
  shared `6AF6` default-tolerance setup. This backs the endpoint/tolerance side
  of `fnInt(expr,var,a,b[,tol])`, but it is not the page-39 visible field
  layout routine.
- `tools/dump-mathprint-layout.py --fnint-slot-flow` verifies the action-byte
  mapping that selects those row slots. The normal path at `53F8` maps
  `0x8F..0x97` to slots `0..8`, `0x8E` to slot 9, and `0x9A..0xB3` to slots
  `10..35` before calling `5955`; `5955/595F` reject out-of-range slots and
  skip `2*slot` bytes through the current row cells. Therefore on the `MATH`
  row action `0x96` selects `00 C7 = nDeriv(`, action `0x97` selects
  `00 C8 = fnInt(`, `0x8E` selects `FB C8`, and normal action `0x9A` selects
  `FB C7`. This is now ROM-backed operator/menu-cell selection.
- `tools/dump-mathprint-layout.py --fnint-argument-order-flow` verifies the
  ordered parser-slot pass-through after `fnInt(` is selected. `5167` keeps
  current slot `85E0` and count `85E2`, forward placement calls `5B10` after
  incrementing the slot, reverse placement calls `5B1D` after decrementing, and
  both wrappers call the parser scanners `59E0`/`59F9` without a field
  permutation. Combined with `--fnint-eval-flow`, this identifies slot 0 as the
  expression/integrand, slot 1 as the differential variable, slots 2/3 as the
  interval endpoints, and optional slot 4 as tolerance. Final row/column
  placement around the tall integral remains separate.
- `tools/dump-mathprint-layout.py --fnint-row-window-flow` recovers the generic
  visible operand window around that ordered parser stream. `50CF` clamps
  `85E0` below `85E2` and computes the six-row overflow window, `5101` maps the
  selected slot to `844B = min(85E0 + 1, 7)`, `513E` restores `844B` from
  baseline `984A`, and `4C5A/4CA4` emit row cells at
  `base + 2*visible_slot`. Classes `0x08`/`0x30` take the one-row path for the
  tested `fnInt(` slots. This is now ROM-backed row-window placement, not the
  special tall-symbol pixel builder.
- `--xref 0x5167` -> the multi-argument operand walker is reached from `50A4`
  and `52B3`; `5B10`/`5B1D` are its saved-OP operand emitters.
- `tools/dump-mathprint-layout.py --operand-flow` verifies byte anchors for
  `5167`, the `51B8`/`51E0` calls to `5B10`, the `5273`/`529F` calls to `5B1D`,
  the paired `5B2B`/`5B38` scratch-slot helpers, the `5955` argument-cell
  loader, and the `595F` scanner that skips `2*slot` bytes and normalizes
  `FF/FE/FC/FB` prefix cells into `B`/`8446`. It now also byte-anchors the
  fixed-bank display/cursor bjumps around that walker: `3C81 -> 01:5FF1`,
  `3C93 -> 01:6076`, `3DE9 -> 01:60E4`, and `3FDB -> 01:5B4C`. Raw Ghidra names
  those targets as cursor-left-edge, cursor-home/scroll, full-LCD-clear, and
  `_PutC` display helpers, not tall-template construction.
- `tools/dump-mathprint-layout.py --multiarg-placement-flow` verifies the
  generic row-placement rule inside that walker. Raw Ghidra names `5167` as
  `eqdisp_layout_multiarg`, `4C5A`/`4CA4` as subexpression emit helpers,
  `4E0A`/`4E14` as argument-index glyph helpers, and `5A3C` as
  `eqdisp_emit_named_arg`. The ROM bytes prove `5949` is the row-step
  classifier: class `0x06` slots `0..2` consume two display rows, while class
  `0x08`/`0x30` slots consume one row. Forward placement emits the previous
  slot index, moves `844B`, emits the current slot index, and calls `5B10`;
  reverse placement mirrors this and calls `5B1D`. The saved-OP direct-slot path
  at `5CF6` writes `85E0`, clears `844B`, and emits operands until
  `844B == 85E0`. The verifier now also byte-anchors the wide-argument window
  controls: action `0x08` advances the visible argument window and can run six
  `5167` steps, action `0x07` backs/remaps through the `50CF/5101` clamp, action
  `0x03` jumps to the last visible argument for eight-or-more-argument forms and
  emits it on row 7, and action `0x04` drains by repeatedly calling `5167` until
  the final argument is reached.
- `tools/dump-mathprint-layout.py --operand-service-flow` follows the operand
  emitters one layer lower: `59E0` calls fixed-bank service `3A53`, which raw
  Ghidra HTTP identifies as `cross_page_jump -> page_07:50B5`, and `59F9` calls
  `306F -> page_07:50B8`. The page-7 bytes at `50B5`, `5104`, and `5199` walk
  expression pointers such as `982E/9830`, store scan state at `84E3`, and
  compare scratch values around `8480/8496`. The verifier now also byte-anchors
  the unsplit `50B5` scanner context and page-7 caller contexts at `5544`,
  `6361`, `70D6`, and `7207`; those callers continue into parser/evaluator token
  classification and FPS setup, not display emission. This is shared
  parser-token traversal below operand recursion, not a display-side field mapper
  or local tall-symbol graphics routine.
- `tools/dump-mathprint-layout.py --page39-external-entry-flow` closes the public
  page-39 bjump entry surface. The only external page-39 bjump targets are
  `3B01 -> 48A6` (set `85DE=46` plus structural-class predicates), `3B0D ->
  53AD` (marker/menu emit), `3B13 -> 4F9A` (the known layout/action dispatcher),
  `3B19 -> 5421` (token/menu emit), `3B1F -> 6B66` (FB string loader /
  `_KeyToString` fallback), and `3B67 -> 5DD8` (`_SaveDisp`). The byte-checked
  predicate chain tests classes `14/41/2A/21/42/44/37/36/35/34/43/38/39/33/32/31`,
  but has no record walk or draw primitive. This leaves no additional public
  page-39 bjump target as a hidden `BB24` definite-integral pixel-placement
  routine.
- `tools/dump-mathprint-layout.py --structural-predicate-flow` closes that
  predicate chain directly. Ghidra splits `48B6` as a tiny thunk, but the ROM
  bytes form a shared `48B6/48BE/48CE` class-predicate family. The exact caller
  set is `4990`, `4A0C`, `52CB`, `52E5`, `5969`, plus mid-chain calls at
  `4FFE`/`5003`; those caller windows are render-loop, active-cell,
  row-navigation, and selected-cell scanner gates. They have no
  `85EE/85EF/9D27` measured-state use and no draw/rectangle/glyph service call,
  so the predicate family is a classifier/control gate, not the tall-symbol
  placement routine.
- `tools/dump-mathprint-layout.py --page39-bjump-caller-flow` closes the ROM-wide
  caller side for those public page-39 entries. `CALL 3B01`, `3B0D`, `3B13`,
  `3B19`, and `3B1F` occur only in the page-1 display bridge: it sets template
  box flags, normalizes prefix bytes through `8446`, sends action `0x09` to the
  known `4F9A` dispatcher, routes token/menu fallbacks, and uses `3B1F` only as
  a string/cell loader before page-1 measurement/output. `CALL 3B67` occurs only
  in LCD-save/capture plumbing on pages 1 and 36. The verifier now scans the
  off-page caller windows (`01:775C..7C9A`, `01:5EDA..5F3C`, and
  `36:5050..5068`) and finds no `85E8/85E9/85EB/85EC/85EE/85EF/9D27`
  measured-template refs and no rectangle/line/large-glyph draw service. That
  bridge delegates layout back to page 39; it is not a separate tall-symbol
  piece table or renderer.
- `tools/dump-mathprint-layout.py --page1-display-bridge-flow` audits that page-1
  bridge directly. The range `01:775C..7C9A` touches text row/column state,
  prefix byte `8446`, saved pointer `85DA`, and entry class state `85DE`, but it
  has no refs to `85E8/85E9/85EB/85EC/85EE/85EF`, `86D7/86D8`, or `9D27`. Its
  local services are text output/cleanup (`_PutC`, a blank/space `_PutMap` path,
  `_PutS`, `_PutPSB`, `_EraseEOL`, erase-to-end-of-screen, `_homeup`), with no
  graph `_VPutMap`, page-7 display-byte mapper, large-font blitter, rectangle
  bcall, or `_DarkLine` call. This rules out the only off-page bridge block as
  the measured tall-symbol placement routine.
- `tools/dump-mathprint-layout.py --saved-op-flow` verifies the saved-OP/list
  branch inside the large page-39 layout routine: `52D3` gates on `(IY+11)` bit
  5 and jumps to `5B8C`, `5B8C` handles saved-OP action `0x05` and routes
  list/named/menu-token handling, `5C41` classifies the `8F..97`/`8E` and
  `9A..B3`/`CC` token ranges, and `5CF6` writes `85E0` only after the
  range-subtracted slot is below `85E2`. Raw Ghidra HTTP exposes these blocks
  inside `eqdisp_layout_main`, not as separate functions.
- `tools/dump-mathprint-layout.py --record-flow` verifies handler-record
  emission anchors: `4C27` loads `0x5E45 + 2*(85DE)`, `4D92` skips row counts to
  emit row-action/title bytes, `4DCA` computes current-row cell pointers, and
  `4DE6` emits two-byte display cells via `4E8E`.
- `tools/dump-mathprint-layout.py --record-cell-stream-flow` closes the
  pre-`4E8E` stream: `4DCA` returns the packed row-cell base after
  `row_count`/`arg_count[]`/`row_action[]`, `4DE6` emits each visible slot as a
  fixed `4E0A` gutter label/separator followed by the `D:E` cell, and the loop
  stops at `85E2` or display row 7. The gutter logic is class/row/slot UI
  handling, not bitmap or measured-height construction.
- `tools/dump-mathprint-layout.py --argument-gutter-caller-flow` closes all
  page-39 callers of that gutter: `4DEC`, `51A6`, `51CE`, `51DD`, `5261`,
  `528B`, `529C`, and `5B46` call `4E0A`, and `5236` is the only `4E14`
  mid-entry caller. Those are record-cell output, forward/reverse `5167`
  multi-argument slot markers, the action-`0x03` row-7 highlighted slot, and
  saved-operand tail handling. There are no unexpected direct or raw refs.
- `tools/dump-mathprint-layout.py --row-action-flow` verifies the boundary
  between handler-record row-action/title bytes and internal action bytes:
  record row actions are emitted by `4D92` and skipped by `4DCA`, while the
  geometry dispatcher at `4F9A` uses the incoming `A` value saved in `B`.
- `tools/dump-mathprint-layout.py --setup-flow` verifies template setup anchors:
  `4AFD` writes `85DF/85DE`, `4B0A` stores row count in `85E1`, `4B24` stores
  current-row arg count in `85E2` and zeros `85E0`, and `50CF/5101/513E` clamp
  and map operand slots to display rows.
- `tools/dump-mathprint-layout.py --row-placement-flow` verifies the
  raised-row render helper: `49A8` enters `4A02` after token dispatch, `4A02`
  calls `4C40`, sets `(IY+0x0C)` bit 4, and calls `4CE9`; `4CE9` forces
  classes `0x24..0x27` to row `4`, class `0x28` to row `3`, and class `0x39` to
  row `4` before emitting indexed strings through `3B2B`. Its only direct
  callers are `4A09` and the carry-preserving return wrapper at `5449`, so this
  is exponent-style row placement, not a measured tall-symbol builder.
- `tools/dump-mathprint-layout.py --layout-flow` verifies internal dispatcher
  anchors: `4F9A` saves the incoming action, `0x01/0x02` move rows, `0x08`
  reaches the six-pass `5167` continuation loop, `0x03/0x04` walk wide argument
  pages, `0x05` loads the current argument cell, `0x5A` runs the close/menu
  guard, and the `FB C7`/`FB C8` path restarts dispatch with action `0x09`.

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
- Page 1's token-name table confirms `C8 06 "fnInt("` and `C7 07 "nDeriv("`;
  `--fnint-token-flow` additionally byte-anchors the parser-token side (`BB24`
  for `tFnInt`) and the page-39 display-cell side (`00C8` for `fnInt(`).
- The `0x686F`/`0x6880` descriptors are **fixed menu/box descriptors**, not
  integral segment tables. Dump them with `tools/dump-mathprint-layout.py
  --descriptors`.
- `FB C7`/`FB C8` are not integral bitmaps. `eqdisp_menu_or_emit` (`39:53AD`)
  special-cases them as square down/up marker emission (`0x07`/`0x06`), and
  `eqdisp_load_glyph18b[2]` routes only proven menu-string cases such as
  `FB CA` -> `n/d`, `FB CB` -> `Un/d`, draw-path `FB C8` -> the summation menu
  string, and `FB D6/D8/D7` -> answer-mode strings.

Remaining blocker for **full** recovery: trace how the ordered `fnInt(` operands
are assigned to final baseline/lower/raised row and column positions around the
tall integral symbol. The class `0x08`/`0x30` records only prove the MATH
menu/operator row: the per-row bytes `0x35`, `0x3B`, `0x25`, `0x43` are row
title/selector bytes emitted by `_DispMenuTitle` (`39:4D21`), not integral
segment opcodes or final placement data.

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
  `tools/dump-mathprint-layout.py --cell-pixel-mapper-flow` byte-checks `682A`,
  `6833`, `683D`, `68AE`, and `6A27`, proving the exact caller set:
  `682A` only from `4C51`, `6833` only from `68CB/68FB`, and `683D` only from
  `6833/6A27`. The mapper windows contain descriptor base/height/cursor state,
  but no measured `85EE/85EF/9D27`, so this is coordinate/highlight plumbing
  rather than tall-symbol construction.
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
  overflow check (`0x844C ≥ 0x0F`). The descriptor walker separately calls
  `4F44`, whose bytes prove an `FB C8`/`FB C7` square-marker gate rather than a
  generic cursor-bounds check.

## Current residual

The captured definite-integral bitmap now matches in `tools/render-mathprint.py`.
That match uses a bitmap-equivalent stretch of `Lintegral` rather than a full
execution of the ROM's recursive template-placement path.

The old descriptor theory is resolved as a dead end:

1. `0x686F`/`0x6880` are fixed box/menu descriptors, not integral segment tables.
2. `FB CA`/`FB CB` route to menu strings (`n/d`, `Un/d`), and the proven
   `FB D6/D8/D7` cases route to answer-mode strings.
3. `FB C7`/`FB C8` are square marker cases handled around `39:53AD` and by the
   descriptor-side `39:4F44` marker gate, not integral top/middle/bottom bitmap
   pieces. `--marker-retouch-flow` further proves the follow-on `4F62/6A66 ->
   4F6C -> _DarkLine` branch has fixed retouch endpoints and no
   `85EE`/`85EF`/`9D27` measured-state input.
4. `67AC` draws the FRAC/FUNC/MTRX/YVAR tab chrome, rectangle borders, and
   fixed `_DarkLine` tab/empty-cue lines from ROM bytes; it is not an
   integral/radical stretch table.
5. Page 39 has no extra `_FillRect`/`_FillRectPattern`/`_DisplayImage`, hidden
   `_DarkLine` caller, or direct `3B3D` large-glyph call site hiding a tall stretch routine.
6. `2CBB -> 3B:7CA8` is draw-state slot validation, not a renderer. The
   callback windows contain only the expected `9BC0/9BC2` saved `HL/A` slots on
   page 3B, no `85EE/85EF/9D27` measured geometry, and no local draw/display
   service.
7. Page 7's large-font service is fixed-stride/fixed-copy glyph output and does
   not measure or build tall templates.
8. The ROM-wide generic glyph-service boundary is closed: all direct `3B3D`
   callers are fixed `code*8`/8-row record paths, their local caller windows
   have no `85EE`/`85EF`/`9D27` measured-state refs, and there are no hidden
   ROM-wide inline fill-primitive call sites.
9. The page-1 `_VPutMap` boundary is closed: `3CDB` callers with nearby
   template state are only the descriptor/fraction UI label emitters, and the
   `_VPutMap` body reads `86D7/86D8` but not `85EE`/`85EF`/`9D27`.
10. Low-byte `E=1F` root/power cells resolve through `_KeyToString` table
   strings, not through a template-height builder.
   `--key-string-structural-flow` adds the matching negative proof for the
   literal `0010` root/power cell: `_KeyToString` would compute index `00`
   and load the counted string `All+`, so `0010` is ROM-backed as a
   root/power record cell plus page-7 `Lroot` glyph bytes, not as an ordinary
   `_KeyToString` root glyph.
10. The `5167` walker overflow/recovery bjumps land in page-1 display cursor,
   scroll, clear, and `_PutC` helpers; they are not measured template builders.
11. `4CE9` only forces raised rows for exponent-style classes and emits indexed
    strings through `3B2B`; it does not measure operands or draw tall symbols.
12. `5DD1 -> 5DD8` is the context-gated `_SaveDisp`/LCD capture path that reads
    port `0x11` bytes into `9872`; it is display backup plumbing, not a hidden
    tall-symbol emitter.
13. `5D86` is the paired `_RestoreDisp` wrapper:
    it saves/restores `(IY+0x14)`, calls `_RestoreDisp`, and is reached only
    from `4AD3`, `579E`, `5873`, `5DA1`, and `6C26` display-buffer restore
    paths using `9872` or `86EC`; no caller window contains `85EE`/`85EF`/`9D27`.
14. `68AE` (`eqdisp_layout_token_geom`) is now recovered as the template-geometry
    action dispatcher and kind-2 fraction editor; it selects descriptor kinds,
    moves template focus, dispatches descriptor cells, and updates
    `85EE/85EF -> 9D27`, but it does not contain a stretch table or variable-height
    glyph emitter.
15. The decoded record/descriptor census has no hidden `Σ`/integral/radical
    structural recipe: `FC3F` and `0842` are the direct `Lintegral` record cells,
    `0010` is limited to root/power records, and `00C6` has no page-39 raw hit
    or decoded record/descriptor hit.
16. Class `0x0D` is not the inserted definite-integral template: raw byte `0x37`
    selects a fixed `NAMES`/`MATH`/`EDIT` record, while `BB24` (`tFnInt`) remains
    a page-7 parser-token table entry with no direct page-39 record-cell hit.
17. The public page-39 bjump entry surface is closed: the only entries are the
    known structural predicate/state setter, layout dispatcher, menu/cell emitters,
    string loader, and `_SaveDisp`; none is an independent `BB24` tall-template
    pixel-placement routine.
18. The ROM-wide caller surface into those public page-39 entries is closed:
    the non-LCD entries are called only by the page-1 display bridge, and
    `_SaveDisp` is called only by LCD-save/capture plumbing on pages 1 and 36.
19. The page-1 display bridge itself is closed as a text/display orchestration
    layer: it has no measured geometry words and no graph/rectangle/large-glyph
    draw primitive that could build the tall integral/radical pixels.
20. The remaining page-level off-page state/draw intersections are closed:
    page 6 is key/cursor display state, page 7 is editor/parser cleanup plus an
    unrelated draw helper, and page 37 is app/UI/default-seed handling. None has
    the measured `85EE/85EF/9D27` geometry plus draw primitive needed for the
    tall integral/radical pixel placement routine. The ROM-wide draw-service
    set now also includes command-level graph/display wrappers and graph-table
    helpers; they add only non-measured page-level coincidences and no new
    measured-state risk page.
21. The direct graph-buffer/LCD-port bypass is closed:
    `tools/dump-mathprint-layout.py --direct-pixel-surface-flow` proves page 39
    has no direct `plotSScreen` refs, confines page-39 direct LCD I/O to
    `_SaveDisp`/`_RestoreDisp`, separates page-33 `85EE` from `86EC`, separates
    page-35/page-37 LCD helpers from their `9D27` seeds, and shows the page-39
    measured geometry window has no direct LCD or graph/backup-buffer refs.
22. The staged pen-coordinate bypass is closed:
    `tools/dump-mathprint-layout.py --pen-surface-flow` byte-checks the high-risk
    `86D7/86D8` windows. Off-page pen/draw hits are cursor preservation or fixed
    UI/display helpers with no `85EE/85EF/9D27` measured geometry. Page-39
    pen/draw hits stay in template chrome, descriptor cell emission, or kind-2
    fraction UI already closed by local geometry verifiers, so `86D7/86D8` are
    not an independent variable-height tall-symbol emitter.
23. The action-`0x05` active-cell recursion branch is closed as a bridge from
    `fnInt(` / square markers to fixed structural glyph records: only decoded
    `82xx` cells in classes `0x0B`, `0x0C`, and `0x20` can recurse through
    `49A8`, while `00C8`, `FB C7/C8`, `FC3F`/`0842`, and `0010` stay outside
    that prefix set.
24. The low-level graph-table helper at `39:66DC` is closed: it has no page-39
    direct or raw xrefs, and the graph-window helpers `4833`/`4822` are called
    only by template chrome plus descriptor/fraction rectangle wrappers.
25. The `48B6/48BE/48CE` structural-class predicate chain is closed as a
    classifier/control gate: its exact callers are render-loop, active-cell,
    row-navigation, and selected-cell scanner gates with no measured-state or
    draw-service output.
26. The `682A/6833/683D` coordinate path is closed: `682A` is only the special
    template-state redraw helper, `6833` only draws the indented current-cell
    cue, and `683D` is only called by that cue wrapper plus the descriptor
    cell loop at `6A27`. The local windows use descriptor base/row-height/cursor
    state and `86D7` coordinates, not measured `85EE/85EF/9D27` geometry or a
    variable-height glyph loop.
27. `lcdTallP` (`8DA3`) is closed as a misleading name-based lead:
    `tools/dump-mathprint-layout.py --lcd-tallp-flow` byte-checks representative
    off-page refs and raw Ghidra identifies page `04:42EC` as `_IBounds`. Page 39
    has no filtered `8DA3` refs, and pages with `lcdTallP` refs do not combine it
    with `85EE/85EF/9D27` plus a local variable-height glyph loop. This is generic
    LCD/graph bounds state, not MathPrint tall-symbol construction.
28. The local page-39 static state/draw surface is closed:
    `tools/dump-mathprint-layout.py --page39-tall-surface-flow` scans filtered
    word-operand refs to `85DE..85EF`, `86D7`, and `9D27` plus draw/display
    service byte patterns, then requires every hit to land in a ROM-backed bucket.
    Raw Ghidra names the loose regions as entry predicates, menu/key dispatch,
    `disp_set_flag10`, token peek/fullscreen/glyph helpers, and the measured
    fraction geometry action routine at `68AE`. The verifier now reports no
    unclassified page-39 candidate hit, so any remaining tall-template proof has
    to come from off-page code or a dynamic pen/glyph trace rather than a hidden
    page-39 static state/draw window.
29. The descriptor-backed template menu emitter is recovered:
    `tools/dump-mathprint-layout.py --template-descriptor-algorithm-flow` byte-
    anchors `68AE -> 6773 -> 6761 -> 69C8`, decodes the descriptor ABI
    `[base][box][row_h][cols:rows][cells]`, and derives cell pixels through
    `683D` as `x=base_x+7*col`, `y=base_y+row*(row_h+2)`. This proves action
    `0x48` selects kind `0x11` and descriptor `6880`, where `00 C8` (`fnInt(`)
    is cell 3 at `x=2A,y=11`, between the square-marker cells `FB C8` and
    `FB C7`. This is recovered descriptor/menu emission, not the still-missing
    measured tall-symbol stretch caller.
30. The page-1 action-table remap is closed:
    `tools/dump-mathprint-layout.py --page1-action-table-flow` byte-anchors the
    `01:79B9` range check and the `01:7BEB` pointer table for actions
    `9A..B3` plus `CC` normalized to `B4`. The decoded packed lists contain
    display-name cells `00C8`/`00C7` and square-marker cells `FB C8`/`FB C7`,
    but no `BB24`/`BB25` parser tokens, no `FC3F`/`0842` direct `Lintegral`
    cells, and no `0010` literal `Lroot` cell. This table is another
    display-cell remap path, not the hidden tall-integral/radical pixel builder.
31. The duplicate fixed `Lintegral` bitmap on page 3F is closed:
    `tools/dump-mathprint-layout.py --page3f-glyph-duplicate-flow` byte-checks
    the canonical page-7 glyph rows at `07:4637` and the width-prefixed page-3F
    data duplicate at `3F:46B7` / row bytes at `3F:46B8`. The duplicate record
    and row addresses have no ROM-wide raw word refs, raw Ghidra reports no
    function at `page_3F:46B8`, and the local page-3F window has no MathPrint
    measured-state refs or draw/display service patterns. This is font/data
    duplication, not a measured tall-symbol placement caller.
32. The `0010` root/power record cell is now bounded against the page-1
    `_KeyToString` table:
    `tools/dump-mathprint-layout.py --key-string-structural-flow` byte-checks
    the `39:4E8E -> 39:6B66 -> 01:6D10` ordinary string path, the
    `01:6E05` pointer table, and the fixed page-7 `Lroot` glyph bytes at
    `07:466F`. For `0010`, the computed `_KeyToString` index is `00`, which
    points at `All+`; therefore the current root renderer is backed by ROM
    glyph data and root/power records, but the exact special caller that chooses
    `Lroot` and draws the vinculum is still not recovered.
33. The final generic cell emitter cannot be the `Lroot`/vinculum builder:
    `tools/dump-mathprint-layout.py --lroot-final-emitter-boundary-flow`
    byte-checks the `4E8E` draw-pass hook/string/direct-glyph tail, `4F1A`,
    `4D92/4DCA`, class `0x2A/0x31` root records, the `2CBB -> page 3B:7CA8`
    callback, `_KeyToString`'s ordinary `0010` table path, and the page-7
    fixed `Lroot` bytes. It proves `0010` is a decoded root payload cell but
    not a descriptor cell, delimiter-family cell, direct `4F1A` glyph, or
    ordinary `_KeyToString` root glyph; row actions `0x62/0x48` are labels
    skipped before payload emission, and the draw-mode callback has no measured
    geometry or glyph/rule output. The special root caller must therefore be
    upstream of final generic cell emission or visible only in a dynamic trace.
34. The remaining dynamic proof surface is now byte-anchored:
    `tools/dump-mathprint-layout.py --template-tracepoint-flow` emits a
    breakpoint manifest for the static exits that any real tall-template trace
    has to pass through: `39:4F9A`, `39:4FD9`, `39:68AE`, `39:67A0`,
    `39:69C8`, `39:6A27`, `39:4DE6`, `39:4E8E`, `39:4EEA`, `39:6ABF`,
    `39:6B1C`, `39:6AF5`, page-7 large-font blitter `07:4588`, and page-1
    `_VPutMap` at `01:6293`. It also states what to capture at each point
    while rendering the screenshot2/screenshot3 stress expressions. This
    converts "needs a dynamic trace" from a vague blocker into a ROM-backed
    trace checklist; it is not itself the final recovered algorithm.
35. The page-39 rectangle/rule event sequence is closed:
    `tools/dump-mathprint-layout.py --rectangle-rule-event-flow` byte-checks
    the kind-2 action branch at `39:6987/69B0`, the rectangle helper `6ABF`,
    endpoint helper `6B1C`, and box wrapper `6AF5`. It proves `6ABF` has only
    callers `6998` and `69A0`, forming an old-rectangle erase
    (`SCF; CALL 6ABF`) followed by `85DF` update and new-rectangle draw
    (`OR A; CALL 6ABF`). It also proves `6B1C` is only used by `6ABF` and the
    focused-cell inverter `6AFD`, and `6AF5` is only used by descriptor/fraction
    box callers `6A0F/6A95`. Therefore all static `6ABF/6B1C/6AF5` events are
    fraction-template UI rectangles/focus inversion, not radical/integral bars.
36. The descriptor/fraction pixel formulas now have concrete ROM-backed samples:
    `tools/dump-mathprint-layout.py --template-pixel-sample-flow` byte-checks
    the selector/descriptor/coordinate anchors at `69C8`, `6A00`, `683D`, and
    `6A27`, plus `6ABF`, `6B1C`, and `6AF5`. It verifies the descriptor ABI for
    `686F`, `6880`, `6893`, `689C`, and `68A5`, then checks sample coordinates
    such as descriptor `6880` cell 3 (`00C8` / `fnInt(`) at `(x=0x2A,y=0x11)`
    and descriptor `689C` cell 11 at `(x=0x5D,y=0x18)`. It also rechecks the
    `6B1C` `x=0x1B+7*n`, `right=x+4` endpoint samples. This makes the
    descriptor-backed template and kind-2 fraction UI pixel algorithm concrete;
    it still does not prove the non-descriptor tall radical/integral pixels.
37. The class-`0x10` `85E9` dynamic selector is ROM-backed and bounded:
    `tools/dump-mathprint-layout.py --class10-dynamic-selector-flow`
    byte-checks the action-`0x05` saved-operand branch at `5BA1`, the `5BD0`
    `85E9 < 6` arm, the `5BED` `85E9 >= 6` arm, the `6CB9` class-49 boundary,
    and the page-7 `FE` pair-table entries at `07:411E`. It proves the low arm
    generates `FE77..FE7C`, which page 7 maps to `5D00..5D05`; none of those
    six cells is a decoded record cell, descriptor cell, or direct `4F1A`
    glyph. The local branch has no `85EE`/`85EF`/`9D27` measured-height refs,
    no `86D7` pen refs, and no graph/rectangle/fill primitive. This classifies
    the saved-operand selector without promoting it to the missing tall-symbol
    pixel placer.
38. The `4A74` context-sensitive class remap is ROM-backed:
    `tools/dump-mathprint-layout.py --dispatch-context-flow` byte-checks the
    `0x3D` special handoff to `672E`, the ordinary `A-0x2A` class calculation,
    the raw-`0x3B` exponent-context bias controlled by `(IY+2)` bits 4/6/5, the
    `(IY+9)` bit-0 remap from classes `0x03..0x08` to `0x2B..0x30`, and the
    downstream `5E45 + 2*85DE` handler lookup. This proves the pre-template
    class-selection algorithm, but still leaves final tall-symbol pixel
    placement open.
39. The local image-blit candidate is closed:
    `tools/dump-mathprint-layout.py --draw-primitive-flow` now includes
    `_DisplayImage` (`4D9B`) in its absent inline-bcall set, alongside
    `_FillRect` and `_FillRectPattern`. A direct `--xref 0x4D9B` scan also finds
    no page-39 control-flow or raw word references. Therefore the missing
    tall-symbol builder is not a page-39 inline `_DisplayImage` bitmap blit.
40. The image/fill absence is ROM-wide, not only page 39:
    `tools/dump-mathprint-layout.py --offpage-render-flow` and
    `--glyph-service-closed-flow` now scan the inline `_DisplayImage` bcall byte
    pattern (`EF 9B 4D`) alongside `_FillRect`/`_FillRectPattern` and report no
    hits anywhere in `tools/rom.bin`. Therefore no hidden ROM-wide inline
    `_DisplayImage` bitmap-table or stretcher path remains.
41. The page-7 display-byte mapper caller surface is closed:
    `tools/dump-mathprint-layout.py --display-byte-caller-flow` enumerates every
    ROM-wide `CALL 3B37` and audits each caller window plus the `07:44DE..453A`
    classifier body. The only page-39 caller is the fixed delimiter-pair
    classifier at `6692`; off-page callers are generic display/UI/parser helpers.
    No caller window or classifier-body window contains the measured
    `85E8/85E9/85EB/85EC/85EE/85EF/9D27` template-state cluster, so this remap
    bjump is not the hidden tall integral/radical emitter.

The remaining work for full recovery is narrower: trace how the ordered
`fnInt(` operands are assigned to final baseline/lower/raised row and column
positions around the tall integral symbol. Static evidence now proves the
menu/name cells (`00 C8` for `fnInt(`), the descriptor-backed template menu ABI
and cell coordinates (`--template-descriptor-algorithm-flow`: descriptor `6880`
places `00 C8` at `x=2A,y=11`), the `0x97 -> row 0 slot 8` action-byte
selection, the page-1 action-table remap closure, the raw-token/display-cell
bridge, the page-7 token-table/parser-scanner boundary, the page-2/page-33
endpoint/tolerance FPS flow, the handler
record format, the generic `5167` row-step/direct-slot render loop,
`--fnint-argument-order-flow`'s ordered parser-slot pass-through, and
`--fnint-row-window-flow`'s visible row-window mapping, plus the
`--active-cell-recurse-flow` exclusion for the action-`0x05` `82xx` recursive
branch and `--graph-table-helper-flow`'s unused `66DC` graph-table helper
closure, `--structural-predicate-flow`'s classifier-gate closure, and
`--page3f-glyph-duplicate-flow`'s fixed-glyph data-duplicate closure,
`--structural-immediate-draw-flow`'s procedural structural-code immediate
closure, and
`--key-string-structural-flow`'s `0010`/`_KeyToString` boundary and
`--lroot-final-emitter-boundary-flow`'s final-emitter exclusion, with
`--template-tracepoint-flow` defining the dynamic breakpoint proof surface and
`--rectangle-rule-event-flow` closing the known page-39 rectangle/rule events,
`--template-pixel-sample-flow` making the descriptor/fraction pixel formulas
concrete, plus `--class10-dynamic-selector-flow` classifying the `5BD7`
`85E9` selector and `--dispatch-context-flow` proving the context-sensitive
`4A74` class remap.
What remains is the exact measured tall-symbol builder and final pixel placement
around the already-recovered descriptor/menu and operand-window machinery.

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
- `definite_integral_stress_example` remains the `screenshot2.png`
  `fnInt(sqrt(X^2+1),X,1/2,3^2)` model. `definite_integral_fraction_radical_example`
  covers the `screenshot3.png` formula,
  `fnInt(sqrt((X^2+1)/X),X,1/2,3^2)`, as a separate reconstruction stress case.
  It is intentionally not marked pixel-equivalent until the surrounding tall
  radical/delimiter construction is ROM-proven.

## Recommended next step

Continue tracing the transition from the ordered `fnInt(` operand window to the
special tall-symbol pixels. A dynamic trace is still the fastest proof:
breakpoint the page-0x39 render / glyph path while drawing `∫₁²(X)dX`, and
capture emitted glyph codes plus pen `(x,y)` and `(row,col)` state.
